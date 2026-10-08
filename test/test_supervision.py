import multiprocessing as mp
from typing import cast

import pytest

from dvice.supervision import join_process


class FakeProcess:
    pid = 123

    def __init__(self, *, hangs: bool, ignores_terminate: bool = False) -> None:
        self.alive = hangs
        self.terminated = False
        self.killed = False
        self.ignores_terminate = ignores_terminate

    def join(self, timeout: float) -> None:
        if self.terminated and not self.ignores_terminate:
            self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.alive = False


def test_join_preserves_completed_process() -> None:
    process = FakeProcess(hangs=False)

    forced = join_process(cast(mp.Process, process), 0, 0.1)

    assert not forced
    assert not process.terminated


def test_join_terminates_stalled_process() -> None:
    process = FakeProcess(hangs=True)
    forced = join_process(cast(mp.Process, process), 0, 0.1)

    assert forced
    assert process.terminated
    assert not process.killed


def test_join_kills_process_that_ignores_termination() -> None:
    process = FakeProcess(hangs=True, ignores_terminate=True)

    forced = join_process(cast(mp.Process, process), 0, 0.1)

    assert forced
    assert process.killed


def test_join_reports_unresolved_shutdown() -> None:
    class UnkillableProcess(FakeProcess):
        def kill(self) -> None:
            self.killed = True

    process = UnkillableProcess(hangs=True, ignores_terminate=True)
    with pytest.raises(TimeoutError, match='still alive'):
        join_process(cast(mp.Process, process), 0, 0)
    assert process.alive and process.killed


@pytest.mark.parametrize(
    'timeout,stop_timeout', [(-1, 0), (0, -1), (float('inf'), 0), (0, float('nan'))]
)
def test_join_rejects_unbounded_or_negative_timeouts(
    timeout: float, stop_timeout: float
) -> None:
    process = FakeProcess(hangs=True)
    with pytest.raises(ValueError, match='finite and non-negative'):
        join_process(cast(mp.Process, process), timeout, stop_timeout)
    assert not process.terminated and not process.killed


def test_join_rejects_unstarted_process() -> None:
    process = mp.Process()
    try:
        with pytest.raises(ValueError, match='must be started'):
            join_process(process, 0, 0)
    finally:
        process.close()
