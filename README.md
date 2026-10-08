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
devices, keyed by display name. Duplicate names currently collide; do not use
these keys as guaranteed hardware identities. `latest()` consumes the pending
snapshot: `None` means no new observation, and `{}` means successful enumeration
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
