# Discovery performance qualification

Measured 8 October 2026. No audio streams were opened or recorded. These are
local measurements, not a guarantee for all backends or device inventories.

## Reproduce

Run `uv run --frozen python scripts/discovery_benchmark.py` from dvice. The default
run makes 100 cached queries (including JSON serialization) and 10 fresh isolated
queries. It prints endpoint counts, not device names. Fresh-query latency includes
Python and CLI imports, PortAudio initialization, enumeration, protocol transfer,
and verified helper exit. The initial import is measured separately in the host.
Fresh-helper CPU is reported on platforms with the standard-library `resource`
module; elsewhere that metric is null. Warm queries are back-to-back, so this
does not measure a sustained polling workload, device churn, or recovery latency.

## Local results

macOS 14.5, Apple Silicon, Python 3.13.12, PortAudio 19.7.0-devel, four endpoints.
Three runs without helper errors:

| Measurement | Observed |
| --- | --- |
| Cached enumeration and JSON, median wall time | 15.5 to 16.3 microseconds |
| Cached enumeration and JSON, mean CPU time | 18.0 to 18.8 microseconds |
| Fresh isolated query, median wall time | 240 to 273 milliseconds |
| Fresh isolated query, maximum wall time | 266 to 300 milliseconds |
| Fresh helper, mean CPU time, final run | 158 milliseconds |
| Initial host PortAudio import | 110 to 443 milliseconds |

At ten cached queries per second, the measured enumeration/serialization CPU
would be about 0.02% of one core, excluding loop and supervision overhead. Fresh
helper startup is the larger cost here: 158 ms of helper CPU every five seconds
is about 3.2% of one core per poller, excluding parent-side work. This is an
estimate from one-shot helpers, not a measurement of streaming helpers. Costs
scale with independent poller instances.

The existing 0.1-second enumeration interval and five-second healthy-helper
refresh remain unchanged. Cached polling cannot make newly initialized PortAudio
devices appear; the fresh-helper cadence is still necessary. A large consumer
interval delays refresh and fault supervision because `devices()` performs them.

A later repeat reported zero endpoints in both paths (135 ms median fresh-query
latency). It is not included in the four-endpoint figures above. No hardware or
audio-service reset was performed, and the reason for that inventory change was
not established. These runs cannot prove physical device availability or recovery.

## Remaining qualification

Windows and Linux backends, larger device inventories, multiple concurrent
pollers, and physical hot-plug/audio-service recovery remain unqualified. Repeat
the benchmark on those systems before treating this local result as a universal
cost bound. Native-backend stalls remain covered by supervision, not this benchmark.
