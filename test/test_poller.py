import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

import pytest
from reccy.device import DeviceDict

from dvice import poller
from dvice.poller import DevicePoller, DeviceQueryStream


def test_invalid_messages_do_not_keep_helper_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poller, 'STREAM_TIMEOUT', 0.15)
    stream = DeviceQueryStream(
        [
            sys.executable,
            str(Path(__file__).parent / 'helpers/query_worker.py'),
            'invalid',
        ]
    )
    stream.start()
    process = stream.process
    try:
        deadline = time.monotonic() + 3
        while stream.process is process and time.monotonic() < deadline:
            assert stream.devices() is None
            time.sleep(0.01)
        assert stream.process is None
        assert stream.restart_backoff == 2 * poller.RESTART_BACKOFF_SECONDS
    finally:
        stream.stop()


class FakeQueryStream:
    def __init__(self, command: object = None) -> None:
        self.snapshots: list[list[DeviceDict]] = [
            [
                {'max_input_channels': 1, 'name': 'Mic'},
                {'max_input_channels': 0, 'name': 'Speaker'},
            ],
            [{'max_input_channels': 2, 'name': 'Interface'}],
        ]
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def devices(self) -> list[DeviceDict] | None:
        if self.snapshots:
            return self.snapshots.pop(0)
        return None


class FakeDeadProcess:
    stdout = None

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> None:
        pass

    def kill(self) -> None:
        pass

    def poll(self) -> int:
        return 1


class FakeLiveProcess:
    stdout = None

    def poll(self) -> None:
        return None


class FakeUnresponsiveProcess:
    def __init__(self) -> None:
        self.killed = False
        self.stdout = FakeStdout()

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> None:
        if not self.killed:
            raise subprocess.TimeoutExpired(['recs', 'query-devices-stream'], timeout)

    def kill(self) -> None:
        self.killed = True

    def poll(self) -> int | None:
        return -9 if self.killed else None


class FakeStdout:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_poller_keeps_only_latest_input_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poller, 'DeviceQueryStream', FakeQueryStream)
    device = DevicePoller(1)

    device.poll()
    device.poll()

    assert device.latest() == {
        'Interface': {'max_input_channels': 2, 'name': 'Interface'}
    }
    assert device.latest() is None


def test_poller_ignores_malformed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poller, 'DeviceQueryStream', FakeQueryStream)
    device = DevicePoller(1)
    device.query_stream.snapshots = [[{'name': 'Mic'}]]

    device.poll()

    assert device.latest() is None


def test_poller_starts_and_stops_query_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poller, 'DeviceQueryStream', FakeQueryStream)
    device = DevicePoller(0.01)

    device.start()
    device.stop()
    device.join(1)

    assert device.query_stream.started
    assert device.query_stream.stopped


def test_query_stream_restarts_when_process_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restarted = False
    stream = DeviceQueryStream()
    stream.process = cast(subprocess.Popen[str], FakeDeadProcess())

    def restart() -> None:
        nonlocal restarted
        restarted = True

    monkeypatch.setattr(stream, 'restart', restart)

    assert stream.devices() is None
    assert restarted


def test_query_stream_restarts_when_updates_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restarted = False
    stream = DeviceQueryStream()
    stream.process = cast(subprocess.Popen[str], FakeLiveProcess())
    stream.last_update = 0

    def restart() -> None:
        nonlocal restarted
        restarted = True

    monkeypatch.setattr(stream, 'restart', restart)
    monkeypatch.setattr(poller.time, 'monotonic', lambda: 10)

    assert stream.devices() is None
    assert restarted


def test_query_stream_kills_unresponsive_process() -> None:
    stream = DeviceQueryStream()
    process = FakeUnresponsiveProcess()
    stream.process = cast(subprocess.Popen[str], process)

    stream.stop()

    assert process.killed
    assert process.stdout.closed
    assert stream.process is None


def test_query_stream_uses_restart_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    starts: list[object] = []

    def popen(*args: object, **kwargs: object) -> FakeDeadProcess:
        process = FakeDeadProcess()
        starts.append(process)
        return process

    monkeypatch.setattr(poller.time, 'monotonic', lambda: now)
    monkeypatch.setattr(poller.subprocess, 'Popen', popen)
    stream = DeviceQueryStream()

    stream.devices()
    assert len(starts) == 1
    assert stream.last_exitcode == 1
    assert stream.next_start == poller.RESTART_BACKOFF_SECONDS
    assert stream.restart_backoff == 2 * poller.RESTART_BACKOFF_SECONDS

    now = 0.5
    stream.devices()
    assert len(starts) == 1

    now = 1.0
    stream.devices()
    assert len(starts) == 2


def test_query_stream_retries_helper_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10.0

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError('process limit')

    monkeypatch.setattr(poller.time, 'monotonic', lambda: now)
    monkeypatch.setattr(poller.subprocess, 'Popen', fail)
    stream = DeviceQueryStream()

    stream.start()

    assert stream.process is None
    assert stream.next_start == now + poller.RESTART_BACKOFF_SECONDS


def helper_command(mode: str) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).parent / 'helpers/query_worker.py'),
        mode,
    ]


def wait_for_update(stream: DeviceQueryStream) -> list[DeviceDict]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if (devices := stream.devices()) is not None:
            return devices
        time.sleep(0.005)
    pytest.fail('helper did not produce an update')


def test_stop_cancels_idle_reader_and_prevents_implicit_start() -> None:
    stream = DeviceQueryStream(helper_command('idle'))
    stream.start()
    process, reader = stream.process, stream.reader
    try:
        started = time.monotonic()
        stream.stop()
        assert time.monotonic() - started < 1
        assert process is not None and process.poll() is not None
        assert reader is not None and not reader.is_alive()
        assert stream.devices() is None
        assert stream.process is None
    finally:
        stream.stop()


def test_stop_serializes_with_helper_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release, requested = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    popen = subprocess.Popen

    def paused_popen(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        entered.set()
        assert release.wait(3)
        return popen(*args, **kwargs)

    monkeypatch.setattr(poller.subprocess, 'Popen', paused_popen)
    stream = DeviceQueryStream(helper_command('idle'))
    starter = threading.Thread(target=stream.start)

    def stop() -> None:
        requested.set()
        stream.stop()

    stopper = threading.Thread(target=stop)
    starter.start()
    try:
        assert entered.wait(3)
        stopper.start()
        assert requested.wait(3)
    finally:
        release.set()
        starter.join(3)
        if stopper.ident is not None:
            stopper.join(3)
        stream.stop()
    assert not starter.is_alive() and not stopper.is_alive()
    assert stream.devices() is None
    assert stream.process is None


def test_reader_cleanup_does_not_require_pipe_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_descriptor, write_descriptor = os.pipe()

    class PipeProcess:
        def __init__(self) -> None:
            self.stdout = open(read_descriptor)
            self.exitcode: int | None = None

        def poll(self) -> int | None:
            return self.exitcode

        def terminate(self) -> None:
            self.exitcode = 0

        def wait(self, timeout: float | None = None) -> int:
            assert self.exitcode is not None
            return self.exitcode

        def kill(self) -> None:
            self.exitcode = -9

    process = PipeProcess()
    fake_process = cast(subprocess.Popen[str], process)

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        return fake_process

    monkeypatch.setattr(poller.subprocess, 'Popen', popen)
    stream = DeviceQueryStream()
    try:
        stream.start()
        os.write(write_descriptor, b'[{"name":"Mic","max_input_channels":1}]\n')
        assert wait_for_update(stream) == [{'name': 'Mic', 'max_input_channels': 1}]
        reader = stream.reader
        started = time.monotonic()
        stream.stop()
        assert time.monotonic() - started < 1
        assert reader is not None and not reader.is_alive()
        assert process.stdout.closed
    finally:
        os.close(write_descriptor)
        stream.stop()
        process.stdout.close()


def test_stop_wakes_poller_with_long_interval() -> None:
    device = DevicePoller(60, helper_command('healthy'))
    device.start()
    try:
        device.stop()
        device.join(1)
        assert not device.thread.is_alive()
        assert device.query_stream.process is None
        device.poll()
        assert device.latest() is None
    finally:
        device.stop()
        device.join(3)


def test_timed_join_does_not_stop_live_helper() -> None:
    device = DevicePoller(0.01, helper_command('healthy'))
    device.start()
    try:
        process = device.query_stream.process
        device.join(0.01)
        assert device.thread.is_alive()
        assert device.query_stream.process is process
    finally:
        device.stop()
        device.join(3)


def test_poller_cannot_start_twice_or_restart() -> None:
    device = DevicePoller(0.01, helper_command('idle'))
    device.start()
    process = device.query_stream.process
    try:
        with pytest.raises(RuntimeError):
            device.start()
        assert device.query_stream.process is process
    finally:
        device.stop()
        device.join(3)
    with pytest.raises(RuntimeError):
        device.start()
    assert device.query_stream.process is None


def test_poller_stopped_before_start_cannot_launch_helper() -> None:
    device = DevicePoller(1, helper_command('idle'))
    device.stop()
    with pytest.raises(RuntimeError):
        device.start()
    assert device.query_stream.process is None


@pytest.mark.parametrize('interval', [0.0, -1.0, float('nan'), float('inf')])
def test_poller_rejects_unusable_intervals(interval: float) -> None:
    with pytest.raises(ValueError, match='finite and positive'):
        DevicePoller(interval)


def test_failed_reader_start_cleans_up_child(monkeypatch: pytest.MonkeyPatch) -> None:
    children: list[subprocess.Popen[str]] = []
    popen = subprocess.Popen

    def remember(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        process = popen(*args, **kwargs)
        children.append(process)
        return process

    def fail_start(thread: threading.Thread) -> None:
        raise RuntimeError('thread limit')

    monkeypatch.setattr(poller.subprocess, 'Popen', remember)
    monkeypatch.setattr(threading.Thread, 'start', fail_start)
    stream = DeviceQueryStream(helper_command('idle'))
    with pytest.raises(RuntimeError, match='thread limit'):
        stream.start()
    assert len(children) == 1 and children[0].poll() is not None
    assert stream.process is None
    assert stream.next_start > time.monotonic()


def test_failed_poller_start_cleans_up_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    start = threading.Thread.start

    def fail_start(thread: threading.Thread) -> None:
        if thread.name == 'QueryDevices':
            start(thread)
        else:
            raise RuntimeError('thread limit')

    monkeypatch.setattr(threading.Thread, 'start', fail_start)
    device = DevicePoller(1, helper_command('idle'))
    with pytest.raises(RuntimeError, match='thread limit'):
        device.start()
    assert device.query_stream.process is None


def test_unresolved_shutdown_retains_process_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnkillableProcess(FakeUnresponsiveProcess):
        def kill(self) -> None:
            pass

    stream = DeviceQueryStream()
    process = UnkillableProcess()
    stream.process = cast(subprocess.Popen[str], process)
    stream.stop()
    assert stream.process is process
    assert stream.devices() is None
    stream.start()
    assert stream.process is process


def test_receiving_a_snapshot_does_not_reset_crash_backoff() -> None:
    stream = DeviceQueryStream(helper_command('once_idle'))
    stream.restart_backoff = 8
    try:
        assert wait_for_update(stream) == [{'name': 'Mic', 'max_input_channels': 1}]
        assert stream.restart_backoff == 8
        stream.restart()
        assert stream.restart_backoff == 16
    finally:
        stream.stop()


def test_consuming_old_snapshot_does_not_refresh_watchdog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = DeviceQueryStream(helper_command('once_idle'))
    stream.start()
    try:
        deadline = time.monotonic() + 3
        while stream.updates.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not stream.updates.empty()
        now = stream.last_update + poller.STREAM_TIMEOUT + 1
        monkeypatch.setattr(poller.time, 'monotonic', lambda: now)
        assert stream.devices() is None
        assert stream.process is None
        assert stream.updates.empty()
    finally:
        stream.stop()


def test_stop_and_start_discard_previous_updates() -> None:
    stream = DeviceQueryStream(helper_command('once_idle'))
    stream.start()
    try:
        deadline = time.monotonic() + 3
        while stream.updates.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not stream.updates.empty()
        stream.stop()
        assert stream.updates.empty()
        stream.command = helper_command('idle')
        stream.start()
        assert stream.devices() is None
    finally:
        stream.stop()


def test_dead_helpers_do_not_deliver_queued_snapshots() -> None:
    stream = DeviceQueryStream(helper_command('once_idle'))
    stream.start()
    try:
        deadline = time.monotonic() + 3
        while stream.updates.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not stream.updates.empty()
        assert stream.process is not None
        stream.process.kill()
        stream.process.wait(3)
        assert stream.devices() is None
        assert stream.updates.empty()
    finally:
        stream.stop()


def test_backoff_resets_only_after_sustained_valid_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poller, 'STREAM_TIMEOUT', 0.2)
    stream = DeviceQueryStream(helper_command('healthy'))
    stream.restart_backoff = 8
    try:
        wait_for_update(stream)
        deadline = time.monotonic() + 3
        while stream.restart_backoff != 1 and time.monotonic() < deadline:
            stream.devices()
            time.sleep(0.005)
        assert stream.restart_backoff == 1
    finally:
        stream.stop()


def test_oversized_unterminated_messages_are_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = DeviceQueryStream(helper_command('oversized'))
    stream.start()
    try:
        deadline = time.monotonic() + 3
        while 'exceeds byte limit' not in caplog.text and time.monotonic() < deadline:
            assert stream.devices() is None
            time.sleep(0.005)
        assert 'exceeds byte limit' in caplog.text
        assert stream.updates.empty()
    finally:
        stream.stop()
