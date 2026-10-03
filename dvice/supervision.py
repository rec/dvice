"""Shut down an isolated device process without losing its final updates."""

import multiprocessing as mp
import threading
from multiprocessing import connection


def join_draining[T](
    process: mp.Process,
    updates: connection.Connection,
    received: list[T],
    timeout: float,
    stop_timeout: float,
) -> bool:
    finished = threading.Event()
    reader = threading.Thread(
        target=_drain_updates,
        args=(updates, received, finished),
        daemon=True,
        name='DeviceFinalUpdates',
    )
    reader.start()
    process.join(timeout)
    forced = False
    if process.is_alive():
        process.terminate()
        process.join(stop_timeout)
        forced = True
    if process.is_alive():
        process.kill()
        process.join(stop_timeout)
    finished.set()
    reader.join(stop_timeout)
    return forced


def _drain_updates[T](
    updates: connection.Connection,
    received: list[T],
    finished: threading.Event,
) -> None:
    while True:
        try:
            ready = updates.poll()
        except OSError:
            ready = False
        if not ready:
            if finished.wait(0.01):
                try:
                    if not updates.poll():
                        return
                except OSError:
                    return
            continue
        try:
            received.append(updates.recv())
        except (EOFError, OSError):
            return
