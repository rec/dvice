import pytest

from scripts import discovery_benchmark


@pytest.mark.parametrize('helper_cpu', [0.4, None])
def test_streaming_measurement_counts_generations_and_parent_cpu(
    monkeypatch: pytest.MonkeyPatch,
    helper_cpu: float | None,
) -> None:
    now = 0.0

    class FakeStream:
        restart_backoff = 1

        def __init__(self) -> None:
            self.process = object()
            self.replaced = False
            self.stopped = False
            streams.append(self)

        def devices(self) -> list[dict[str, int | str]]:
            if now >= 5 and not self.replaced:
                self.process = object()
                self.replaced = True
            return [{'name': 'Mic', 'max_input_channels': 1}]

        def stop(self) -> None:
            self.stopped = True

    streams: list[FakeStream] = []

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds

    child_cpu = iter([0.0 if helper_cpu is not None else None, helper_cpu])
    parent_cpu = iter([0.0, 0.2])
    monkeypatch.setattr(discovery_benchmark, 'DeviceQueryStream', FakeStream)
    monkeypatch.setattr(discovery_benchmark.time, 'monotonic', lambda: now)
    monkeypatch.setattr(discovery_benchmark.time, 'sleep', advance)
    monkeypatch.setattr(
        discovery_benchmark.time, 'process_time', lambda: next(parent_cpu)
    )
    monkeypatch.setattr(discovery_benchmark, 'child_cpu_time', lambda: next(child_cpu))

    result = discovery_benchmark.benchmark_streams(
        discovery_benchmark.Benchmark(stream_seconds=6, pollers=2, consumer_interval=1)
    )

    assert result['helper_generations_per_poller'] == [2, 2]
    assert result['observations_per_poller'] == [6, 6]
    assert result['endpoint_counts'] == [1]
    assert result['elapsed_seconds_including_cleanup'] == 6
    assert result['parent_cpu_seconds'] == 0.2
    if helper_cpu is None:
        assert result['total_cpu_percent_of_one_core'] is None
    else:
        assert result['total_cpu_percent_of_one_core'] == pytest.approx(10)
    assert all(s.stopped for s in streams)


@pytest.mark.parametrize('failure', ['crash', 'no_observation'])
def test_failed_measurement_cleans_up_every_helper(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    now = 0.0

    class FakeStream:
        restart_backoff = 2 if failure == 'crash' else 1
        process = None

        def __init__(self) -> None:
            self.stopped = False
            streams.append(self)

        def devices(self) -> None:
            return None

        def stop(self) -> None:
            self.stopped = True

    streams: list[FakeStream] = []

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(discovery_benchmark, 'DeviceQueryStream', FakeStream)
    monkeypatch.setattr(discovery_benchmark.time, 'monotonic', lambda: now)
    monkeypatch.setattr(discovery_benchmark.time, 'sleep', advance)
    expected = RuntimeError if failure == 'crash' else TimeoutError
    with pytest.raises(expected):
        discovery_benchmark.benchmark_streams(
            discovery_benchmark.Benchmark(pollers=2, stream_seconds=0.1)
        )
    assert len(streams) == 2 and all(s.stopped for s in streams)
