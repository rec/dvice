# dvice

Reusable supervision of unreliable audio devices. dvice queries PortAudio in
an isolated helper process, publishes current input-device snapshots, and
restarts a stalled or failed query helper with bounded backoff. It also provides
bounded process shutdown for applications that isolate audio streams in child
processes.

dvice does not decide what to record, how to name tracks, or where to write
media. Its first consumer is recs.

`query_devices()` returns a list on successful enumeration, including an empty
list when no devices exist. Spawn, backend, timeout, and protocol failures raise
exceptions instead of implying device removal. The streaming poller discards
malformed observations without treating them as healthy updates.
Both query paths reject output exceeding 1 MiB. One-shot output collection is
nonblocking and deadline-limited, including a helper that leaves its stdout pipe
open. Timeouts and interrupts kill and reap the direct child before propagating
the exception, subject to the OS being able to terminate it.

## Polling and lifecycle

Import `DevicePoller` from `dvice.poller`. It publishes only input-capable
devices, as a list in enumeration order. Every endpoint is preserved, including
duplicate names and endpoints exposed by different host APIs. Descriptions retain
the backend's host API and any supplied identity fields. List positions and
PortAudio indices identify only the current enumeration, not persistent hardware.
Positions in this input-only list are not PortAudio indices; output-only endpoints
have been filtered out. dvice does not invent missing endpoint identifiers.
dvice does not match, merge, or deduplicate endpoints across refreshes; renaming
and reordering appear as the backend reports them. Consumers must define their
own matching policy and must not assume display names are unique.
`latest()` consumes the pending
snapshot: `None` means no new observation, and `[]` means successful enumeration
found no inputs. Snapshots are latest-only, not a journal of every unplug/replug.

Use a finite positive polling `interval` (seconds). It is the delay between
consumer polls, not the helper's enumeration rate. A poller is single-use:
start it once, call `stop()` to cancel polling and clean up its helper, then
`join()` to wait for the thread. `join(timeout)` only waits; it does not stop the
helper or extend that timeout with additional cleanup. Interval waits are
interruptible by `stop()`. The inherited context manager owns normal cleanup.

`DeviceQueryStream.devices()` consumes a validated update and advances helper
supervision. `stop()` disables implicit starts; explicit `start()` re-enables
them when backoff permits. `restart()` schedules replacement with backoff rather
than guaranteeing an immediate new process. Backoff resets only after five
seconds of continuous valid observations, not after one line in a crash loop.
Old-generation and dead-helper observations are not delivered as fresh data.
Healthy helpers are replaced every five seconds, without failure backoff, to
refresh PortAudio initialization. No nested enumeration subprocess is needed.
Discovery latency includes helper startup and the consumer polling interval;
five seconds is a refresh cadence, not a sample-exact detection deadline.

Discovery cost measurements and a repeatable, discovery-only benchmark are in
[discovery-performance.md](doc/discovery-performance.md), including complete
streaming lifetimes and concurrent helpers. Prefer one discovery owner per
application; dispatch its observations rather than creating a helper for every
consumer. Local macOS results do not establish cost or recovery bounds for other
backends, and a slow consumer delays supervision rather than providing a cheap
independent watchdog.

Terminate, kill, and reader cleanup share a five-second budget per cleanup
operation. OS process creation and waiting for a concurrent lifecycle operation
are outside that budget. If exit cannot be verified, the stream retains its
handles and does not start another helper; callers can retry `stop()`. Reader
messages are capped at 1 MiB, including unterminated output. Helper stderr is
inherited so import and backend failures remain visible without accumulating an
unbounded diagnostic buffer in dvice.

`devices_json()` queries PortAudio in the caller and is intended for the worker;
it is not the isolated, timed API. `stream_devices()` is the blocking worker
stdout loop, not an iterator or an audio stream.

## Boundaries

dvice supervises discovery, not audio delivery. A listed endpoint can still be
unresponsive. Consumers own stream opening/recovery, callback-progress monitoring,
recording policy, and resource cleanup. dvice does not reset or reboot hardware.
Snapshot coalescing can hide brief remove/reappear transitions, so enumeration
alone cannot establish that an existing audio stream survived a device reboot.

Physical hot-plug and audio-service restart qualification on macOS, Windows, and
Linux is separate from the unit suite; mocked snapshots do not prove hardware
recovery. Helpers are trusted local commands, not a sandbox for arbitrary code.
Custom commands must implement the newline-delimited device-list protocol in a
single process and must not spawn descendants. dvice owns only its direct helper.
The built-in helper watches a private stdin pipe held open by its parent and
exits immediately on EOF, even if native enumeration is blocked. This also covers
abrupt parent termination or a crash; it depends on the OS closing the parent's
handles and scheduling the helper's watcher. It is not a hard real-time guarantee
and cannot overcome an OS-uninterruptible process or a backend holding Python's
interpreter lock indefinitely. Do not share or inherit the lifeline write handle.
Custom helpers receive no lifeline and have no parent-death guarantee. Hosts must
still arrange graceful cleanup, including retrying `stop()` if an interrupt aborts
cleanup. Arbitrary process-tree ownership remains unsupported.

For standalone streaming supervision, keep ownership explicit:

```python
from dvice.poller import DeviceQueryStream

stream = DeviceQueryStream()
try:
    stream.start()
    # Repeatedly call stream.devices() from the host's control loop.
finally:
    stream.stop()
```

`DeviceDict`, `device_key()`, and `STABLE_DEVICE_ID_FIELDS` are defined in
`dvice.device`. The key helper prefers a supplied persistent ID but falls back to
a display name, which is not guaranteed unique. threa supplies the inherited
thread API. Release/version policy is unchanged; this checkout's lockfile is not
a downstream application's dependency pin.

`join_process()` in `dvice.supervision` accepts a started, unclosed multiprocessing
process and finite non-negative timeouts. Its nominal wait budget is
`timeout + 2 * stop_timeout`. On verified exit it returns whether termination
was forced; it raises `TimeoutError` if the process survives the final kill wait.
The caller retains ownership on failure. Forced termination can corrupt consumer
queues or leave locks held, so discard/recreate affected IPC before recovery.
This utility does not repair arbitrary consumer state or terminate descendants.
