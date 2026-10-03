import subprocess
from typing import cast

import pytest
from reccy.device import DeviceDict

from dvice import poller
from dvice.poller import DevicePoller, DeviceQueryStream


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

    def poll(self) -> int:
        return -9 if self.killed else 1


class FakeStdout:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeStreamProcess:
    stdout = [
        '[{"max_input_channels": 1, "name": "Old"}]\n',
        '[{"max_input_channels": 1, "name": "New"}]\n',
    ]

    def poll(self) -> None:
        return None


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


def test_query_stream_keeps_only_latest_update() -> None:
    stream = DeviceQueryStream()
    stream.process = cast(subprocess.Popen[str], FakeStreamProcess())

    stream._read()

    assert stream.devices() == [{'max_input_channels': 1, 'name': 'New'}]


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
