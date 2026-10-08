import sys
import threading
import time
from pathlib import Path

import pytest

from dvice import poller
from dvice.health import DiscoveryFailure, DiscoveryHealth
from dvice.poller import DevicePoller, DeviceQueryStream


def command(mode: str) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).parent / 'helpers/query_worker.py'),
        mode,
    ]


def wait_for_health(stream: DeviceQueryStream, health: DiscoveryHealth) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        stream.devices()
        if stream.status.health == health:
            return
        time.sleep(0.005)
    pytest.fail(f'helper did not reach {health}')


def test_independent_status_readers_do_not_start_helpers_or_consume_observations() -> (
    None
):
    device = DevicePoller(1, command('once_idle'))
    assert device.status.health == DiscoveryHealth.idle
    assert device.status.devices is None
    assert device.query_stream.process is None
    try:
        wait_for_health(device.query_stream, DiscoveryHealth.healthy)
        first, second = device.status, device.status
        assert first == second
        assert first.devices is not None and second.devices is not None
        first.devices[0]['name'] = 'changed by caller'
        first.devices.clear()
        assert device.status == second
        assert second.devices == [{'name': 'Mic', 'max_input_channels': 1}]
        assert second.observed_at is not None
        assert second.generation == 1
        device.stop()
        stopped = device.status
        assert stopped.health == DiscoveryHealth.stopped
        assert stopped.devices == second.devices
        assert stopped.observed_at == second.observed_at
        assert stopped.sequence > second.sequence
    finally:
        device.stop()


def test_successful_empty_observation_is_not_never_observed() -> None:
    stream = DeviceQueryStream(command('empty_idle'))
    try:
        wait_for_health(stream, DiscoveryHealth.healthy)
        assert stream.status.devices == []
        assert stream.status.observed_at is not None
    finally:
        stream.stop()


def test_failure_retains_last_observation_and_recovery_has_a_new_generation() -> None:
    stream = DeviceQueryStream(command('once_idle'))
    try:
        wait_for_health(stream, DiscoveryHealth.healthy)
        before = stream.status
        assert stream.process is not None
        stream.process.kill()
        stream.process.wait(3)
        stream.devices()
        failed = stream.status
        assert failed.health == DiscoveryHealth.retrying
        assert failed.failure == DiscoveryFailure.exited
        assert failed.devices == before.devices
        assert failed.observed_at == before.observed_at
        assert failed.generation == before.generation
        assert failed.sequence > before.sequence
        assert failed.next_retry is not None
        stream.command = command('healthy')
        wait_for_health(stream, DiscoveryHealth.healthy)
        recovered = stream.status
        assert recovered.generation > before.generation
        assert recovered.failure is None and recovered.next_retry is None
        assert recovered.observed_at is not None
        assert recovered.observed_at > before.observed_at
    finally:
        stream.stop()


def test_status_reads_remain_prompt_during_blocked_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = DevicePoller(1, command('once_idle'))
    stream = device.query_stream
    wait_for_health(stream, DiscoveryHealth.healthy)
    process = stream.process
    assert process is not None
    entered, release = threading.Event(), threading.Event()
    wait = process.wait

    def blocked_wait(timeout: float | None = None) -> int:
        entered.set()
        assert release.wait(3)
        return wait(timeout)

    monkeypatch.setattr(process, 'wait', blocked_wait)
    stopper = threading.Thread(target=device.stop)
    stopper.start()
    try:
        assert entered.wait(3)
        started = time.monotonic()
        status = device.status
        assert time.monotonic() - started < 0.2
        assert status.health == DiscoveryHealth.stopped
        assert status.devices is not None
    finally:
        release.set()
        stopper.join(3)
        device.stop()
    assert not stopper.is_alive()


def test_explicit_start_during_backoff_is_retrying_not_stopped() -> None:
    stream = DeviceQueryStream(command('once_idle'))
    try:
        wait_for_health(stream, DiscoveryHealth.healthy)
        stream.restart()
        retry = stream.status.next_retry
        stream.stop()
        stream.start()
        assert stream.status.health == DiscoveryHealth.retrying
        assert stream.status.next_retry == retry
        assert stream.process is None
    finally:
        stream.stop()


def test_spawn_failure_reports_retry_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError('process limit')

    monkeypatch.setattr(poller.subprocess, 'Popen', fail)
    stream = DeviceQueryStream()
    stream.start()
    status = stream.status
    assert status.health == DiscoveryHealth.retrying
    assert status.failure == DiscoveryFailure.spawn
    assert status.devices is None
    assert status.next_retry is not None
    assert status.next_retry > time.monotonic()
