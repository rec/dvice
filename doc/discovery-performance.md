# Discovery performance qualification

Measured 8 October 2026. No audio streams were opened or recorded. These are
local measurements, not a guarantee for all backends or device inventories.

## Reproduce

Run `uv run --frozen python scripts/discovery_benchmark.py` from dvice. The default
run makes 100 cached queries (including JSON serialization) and 10 fresh isolated
queries. It prints endpoint counts, not device names. Fresh-query latency includes
Python and CLI imports, PortAudio initialization, enumeration, protocol transfer,
and verified helper exit. The initial import is measured separately in the host.
The default run also supervises one real streaming helper for 16 seconds at a
0.1-second consumer interval, including repeated healthy-helper replacement.
Streaming output records helper generations, consumed observations, time to first
observation, parent CPU (including reader threads), helper CPU, and combined CPU
as a percentage of one core. Its elapsed time includes startup and final cleanup.
Reaped helper CPU is collected only after all helpers are stopped, so it includes
the complete lifetime of each generation. Failed helpers or a run with no valid
observation abort rather than producing a healthy-refresh baseline.

Run `uv run --frozen python scripts/discovery_benchmark.py --pollers 4` to measure
four concurrent discovery owners. Run with `--consumer-interval 2 --fresh-queries 1`
to demonstrate slower consumer supervision. Use `--stream-seconds` for longer
runs. Keep at least 16 seconds when evaluating refresh cost; shorter measurements
can contain fewer generations or no completed refresh at all.

Fresh/streaming helper CPU is reported on platforms with the standard-library
`resource` module; elsewhere those metrics and the combined CPU percentage are
null, not zero. Parent CPU remains available. Counts include all enumerated
endpoints, not just inputs. Warm queries are back-to-back; they do not measure
device churn or hot-plug recovery latency.

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

## Direct streaming results

Further measurements on the same Mac reported four endpoints throughout each
run. Native enumeration was used; no streams were opened. All helpers remained
healthy. These are short local runs, not sustained worst-case bounds.

| Discovery owners | Consumer interval | Duration | Generations per owner | Parent CPU | Helper CPU | Total share of one core |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.1 s | 16.04 s | 4 | 0.068 s | 0.499 s | 3.53% |
| 4 | 0.1 s | 16.01 s | 4 each | 0.206 s | 2.125 s | 14.57% |
| 1 | 2 s | 16.01 s | 3 | 0.056 s | 0.371 s | 2.67% |

The fast-consumer single-owner run delivered its first observation in 207 ms.
The four-owner run delivered first observations in 314 to 419 ms. With a
two-second consumer interval, the first observation took 2.00 seconds and fewer
refreshes completed. That lower CPU percentage is **not** a free optimization:
the consumer delays both refresh and fault supervision. Reader threads continue
running regardless of the consumer interval.

## Decisions closing review finding 14

- Retain the 0.1-second worker enumeration and five-second healthy refresh.
  Direct streaming measurements support the earlier approximate CPU estimate;
  they do not justify trading away the agreed discovery responsiveness.
- Prefer one discovery owner per application. Dispatch its observations to the
  application's interested components rather than starting independent pollers
  for each component. The new non-consuming `status` permits independent readers
  to share one poller without consuming each other's observations. No shared
  daemon, cross-process cache,
  new dependency, or production API is introduced.
- Keep supervision consumer-driven and document the consequence. Choose a short
  consumer interval for responsive supervision; a five-second refresh cadence is
  not an independent watchdog or a hard five-second detection deadline.
- Treat backend and inventory qualification as deployment evidence, not an
  indefinitely open software defect. The benchmark is reproducible; these local
  figures must not become universal cost or recovery promises.

Finding 14 is closed for measurement tooling, local evidence, and the explicit
cadence/ownership decisions. No production cadence or API changed.

## Discovery-health regression measurement

After adding cached health observations and independent status copies, a further
single-owner run used the same four-endpoint Mac inventory and 0.1-second
consumer interval. It read `status` on each control-loop iteration and counted
new observations by sequence. Four generations over 16.01 seconds used 0.122 s
of parent CPU and 0.603 s of helper CPU, totaling 4.53% of one core. First
observation arrived in 311 ms. No cadence or helper-count change was introduced.
The earlier 3.53% result and this short follow-up are separate local measurements,
not a controlled attribution of the difference to the new feature. Independent
reader copies have workload-dependent cost; this run used one reader.

## Qualification limits

Windows and Linux backends, larger device inventories, and physical hot-plug or
audio-service recovery were not exercised. Concurrent owners were measured only
on macOS with four endpoints. On Windows, helper CPU needs an OS profiler because
the standard library does not provide the child-CPU accounting used here. Repeat
these workloads on target machines before committing to a platform-specific
performance budget. Native-backend stalls remain covered by supervision, not
this performance benchmark. No synthetic inventory would establish the cost of
real native enumeration with that many devices.
