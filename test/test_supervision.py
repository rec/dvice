import multiprocessing as mp
from multiprocessing import connection
from typing import cast

from dvice.supervision import join_draining


class FakeProcess:
    def __init__(self, *, hangs: bool) -> None:
        self.alive = hangs
        self.terminated = False
        self.killed = False

    def join(self, timeout: float) -> None:
        if self.terminated:
            self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.alive = False


class FakeUpdates:
    def __init__(self) -> None:
        self.values = ['final update']

    def poll(self) -> bool:
        return bool(self.values)

    def recv(self) -> object:
        return self.values.pop(0)


def test_join_drains_final_update() -> None:
    process = FakeProcess(hangs=False)
    updates = FakeUpdates()

    received, forced = join_draining(
        cast(mp.Process, process), cast(connection.Connection, updates), 0, 0.1
    )

    assert received == ['final update']
    assert not forced
    assert not process.terminated


def test_join_terminates_stalled_process() -> None:
    process = FakeProcess(hangs=True)

    received, forced = join_draining(
        cast(mp.Process, process), cast(connection.Connection, FakeUpdates()), 0, 0.1
    )

    assert received == ['final update']
    assert forced
    assert process.terminated
    assert not process.killed
