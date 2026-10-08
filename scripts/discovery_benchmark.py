"""Discovery-only qualification: never opens an audio stream."""

import json
import platform
import statistics
import time

import tyro
from pydantic import BaseModel, Field

from dvice.discovery import DEVICE_QUERY_TIMEOUT, query_devices
from dvice.health import DiscoveryHealth
from dvice.poller import RESTART_BACKOFF_SECONDS, DeviceQueryStream


class Benchmark(BaseModel, frozen=True):
    warm_queries: int = Field(default=100, ge=1)
    fresh_queries: int = Field(default=10, ge=1)
    stream_seconds: float = Field(default=16.0, gt=0, allow_inf_nan=False)
    pollers: int = Field(default=1, ge=1)
    consumer_interval: float = Field(default=0.1, gt=0, allow_inf_nan=False)


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
    streaming = benchmark_streams(args)
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
                'streaming': streaming,
            },
            indent=2,
        )
    )


def benchmark_streams(args: Benchmark) -> dict[str, object]:
    streams = [DeviceQueryStream() for _ in range(args.pollers)]
    previous: list[object] = [None] * args.pollers
    generations = [0] * args.pollers
    observations = [0] * args.pollers
    sequences = [-1] * args.pollers
    first_updates: list[float | None] = [None] * args.pollers
    counts: set[int] = set()
    cpu_before = child_cpu_time()
    parent_cpu_before = time.process_time()
    started = time.monotonic()
    try:
        while time.monotonic() - started < args.stream_seconds:
            for i, stream in enumerate(streams):
                stream.devices()
                if stream.restart_backoff > RESTART_BACKOFF_SECONDS:
                    raise RuntimeError('Helper failed; not a healthy-refresh benchmark')
                status = stream.status
                devices = (
                    status.devices if status.health == DiscoveryHealth.healthy else None
                )
                if stream.process is not None and stream.process is not previous[i]:
                    generations[i] += 1
                    previous[i] = stream.process
                if devices is not None and status.sequence != sequences[i]:
                    sequences[i] = status.sequence
                    observations[i] += 1
                    counts.add(len(devices))
                    if first_updates[i] is None:
                        first_updates[i] = time.monotonic() - started
            if (
                time.monotonic() - started > DEVICE_QUERY_TIMEOUT
                and None in first_updates
            ):
                raise TimeoutError('A streaming helper supplied no valid observations')
            time.sleep(
                min(
                    args.consumer_interval,
                    max(0.0, args.stream_seconds - (time.monotonic() - started)),
                )
            )
        if None in first_updates:
            raise TimeoutError('A streaming helper supplied no valid observations')
    finally:
        for stream in streams:
            stream.stop()
    elapsed = time.monotonic() - started
    parent_cpu = time.process_time() - parent_cpu_before
    cpu_after = child_cpu_time()
    helper_cpu = (
        cpu_after - cpu_before
        if cpu_before is not None and cpu_after is not None
        else None
    )
    return {
        'pollers': args.pollers,
        'consumer_interval_seconds': args.consumer_interval,
        'elapsed_seconds_including_cleanup': elapsed,
        'endpoint_counts': sorted(counts),
        'helper_generations_per_poller': generations,
        'observations_per_poller': observations,
        'first_observation_seconds_per_poller': first_updates,
        'parent_cpu_seconds': parent_cpu,
        'helper_cpu_seconds': helper_cpu,
        'total_cpu_percent_of_one_core': (
            100 * (parent_cpu + helper_cpu) / elapsed
            if helper_cpu is not None
            else None
        ),
    }


def child_cpu_time() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


if __name__ == '__main__':
    main()
