"""Bounded shutdown for an isolated device process."""

import multiprocessing as mp


def join_process(
    process: mp.Process,
    timeout: float,
    stop_timeout: float,
) -> bool:
    """Wait, terminate, then kill if needed; return whether termination was forced."""
    process.join(timeout)
    forced = False
    if process.is_alive():
        process.terminate()
        process.join(stop_timeout)
        forced = True
    if process.is_alive():
        process.kill()
        process.join(stop_timeout)
    return forced
