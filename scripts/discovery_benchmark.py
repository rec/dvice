"""Discovery-only qualification: never opens an audio stream."""

import json
import platform
import statistics
import time

import tyro
from pydantic import BaseModel, Field

from dvice.discovery import query_devices


class Benchmark(BaseModel, frozen=True):
    warm_queries: int = Field(default=100, ge=1)
    fresh_queries: int = Field(default=10, ge=1)


def main() -> None:
    args = tyro.cli(Benchmark)
    started = time.perf_counter()
    import sounddevice

    initialization = time.perf_counter() - started
    warm: list[float] = []
    counts: set[int] = set()
    cpu = time.process_time()
    for _ in range(args.warm_queries):
        started = time.perf_counter()
        devices = list(sounddevice.query_devices())
        json.dumps(devices)
        warm.append(time.perf_counter() - started)
        counts.add(len(devices))
    warm_cpu = (time.process_time() - cpu) / args.warm_queries
    fresh: list[float] = []
    cpu_before = child_cpu_time()
    for _ in range(args.fresh_queries):
        started = time.perf_counter()
        devices = query_devices()
        fresh.append(time.perf_counter() - started)
        counts.add(len(devices))
    cpu_after = child_cpu_time()
    fresh_cpu = (
        (cpu_after - cpu_before) / args.fresh_queries
        if cpu_before is not None and cpu_after is not None
        else None
    )
    print(
        json.dumps(
            {
                'platform': platform.platform(),
                'python': platform.python_version(),
                'portaudio': sounddevice.get_portaudio_version()[1],
                'endpoint_counts': sorted(counts),
                'initialization_seconds': initialization,
                'warm_queries': args.warm_queries,
                'warm_wall_median_seconds': statistics.median(warm),
                'warm_wall_max_seconds': max(warm),
                'warm_cpu_mean_seconds': warm_cpu,
                'fresh_queries': args.fresh_queries,
                'fresh_wall_median_seconds': statistics.median(fresh),
                'fresh_wall_max_seconds': max(fresh),
                'fresh_cpu_mean_seconds': fresh_cpu,
            },
            indent=2,
        )
    )


def child_cpu_time() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


if __name__ == '__main__':
    main()
