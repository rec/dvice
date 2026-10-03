import multiprocessing as mp
from typing import cast

from dvice.supervision import join_process


class FakeProcess:
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
