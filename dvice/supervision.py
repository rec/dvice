"""Bounded shutdown for an isolated device process."""

import multiprocessing as mp
from math import isfinite


def join_process(
    process: mp.Process,
    timeout: float,
    stop_timeout: float,
) -> bool:
    """Wait, terminate, then kill; return whether intervention was forced.

    The process must be started and not closed. Timeouts are finite non-negative
    seconds. If the process survives the final wait, raise TimeoutError; the
    caller still owns it. After forced termination, consumer IPC may be unsafe
    to reuse, including queues and locks that the child might have held.
    """
    if any(not isfinite(t) or t < 0 for t in (timeout, stop_timeout)):
        raise ValueError('timeouts must be finite and non-negative')
    if process.pid is None:
        raise ValueError('process must be started before joining')
    process.join(timeout)
    forced = False
    if process.is_alive():
        process.terminate()
        process.join(stop_timeout)
        forced = True
    if process.is_alive():
        process.kill()
        process.join(stop_timeout)
    if process.is_alive():
        raise TimeoutError('Process is still alive after terminate and kill')
    return forced
