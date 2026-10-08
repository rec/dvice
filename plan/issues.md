# dvice issues and review findings

Reviewed 8 October 2026 at commit `bf2f3276ad3072479f4e4a3c8ffeb0a3182273f1`.

## Scope and evidence

Read every package module, every test, README, package configuration, and lockfile.
Also inspected the installed threa thread implementation, installed sounddevice
enumeration code, reccy's device types, and recs' current consumer. This is a
source review, not a hardware qualification or a reproduction of every race.
No application, audio worker, or hardware experiment was run.

- **Confirmed** means a behavior follows directly from the implementation.
- **Possible** means an identified interleaving, backend behavior, or exceptional
  condition can expose it; it still needs a targeted reproduction.
- **Contract gap** means callers cannot determine the intended behavior safely
  from the API or documentation.
- **P1**: discovery correctness, shutdown liveness, or silent device loss.
- **P2**: robustness, diagnostics, resource usage, or significant API traps.
- **P3**: smaller naming, documentation, and maintainability concerns.

No P0 is established. Do not interpret a possible issue as proven on every OS.
Recommendations below are proposed fixes, not authorization to implement them.

## P1: discovery and lifecycle

### 1. Repeated enumeration does not refresh PortAudio initialization

**Possible, backend-dependent.** `discovery.py:36-48` imports sounddevice once
and repeatedly calls `query_devices()` in a long-lived helper. There is no
reinitialization or periodic fresh-process enumeration. A helper is replaced
only when it exits or stops supplying updates (`poller.py:134-165`).

PortAudio device lists can be fixed at initialization. A cached list keeps
arriving every 0.1 seconds and therefore passes the watchdog while unplugged
devices remain listed or newly connected/rebooted devices remain absent.
Repeated enumeration alone is not evidence of hot-plug support.

The [PortAudio hot-plug discussion](https://github.com/PortAudio/portaudio/wiki/HotPlug)
describes this limitation and a proposed API, not a guarantee that the shipped
backend has that API. Installed sounddevice calls `Pa_GetDeviceCount()` and
initializes on import. Its [implementation](https://python-sounddevice.readthedocs.io/en/latest/_modules/sounddevice.html)
supports the code-path observation, not a claim that all backends are stale.

**Recommendation:** choose a bounded refresh policy in the isolated helper,
using supported lifecycle operations or fresh processes. Qualify actual packaged
backends on macOS, Windows, and Linux with unplug/replug, power cycle, reboot,
same-name replacement, and host audio-service restart tests. Existing tests
feed fabricated lists and cannot establish physical rediscovery.

### 2. Query failure is represented as authoritative device absence

**Confirmed.** `discovery.py:27-28` returns `[]` on timeout; `:45-48` returns
`[]` on PortAudio errors. `DevicePoller.poll()` publishes `{}` for such a list.
Actual absence, a hung query, and a failed audio backend are indistinguishable.
Continuous PortAudio errors also count as successful watchdog updates.

The current recs consumer treats missing entries as offline and stops their
source processes. A backend fault can therefore become a false mass-removal
event rather than an unknown observation. Conversely, the failing helper need
never restart while it emits empty lists.

**Recommendation:** distinguish successful empty enumeration from failed or
unknown enumeration, with an explicit stale-state policy. Preserve failure
information through both one-shot and streaming APIs. Test recovery from
PortAudio errors without inventing removal observations. Existing timeout tests
currently enshrine the ambiguous behavior and would need an intentional change.

### 3. Shutdown races with polling and helper restart

**Possible, directly supported by the control flow.** `DevicePoller.stop()`
stops the helper before clearing the polling thread's running flag
(`poller.py:37-39`). In that window the polling thread can call `devices()`,
observe `process is None`, and launch a replacement. Even reversing those two
calls alone does not finish an already-running callback.

`DeviceQueryStream.start/stop/restart/devices` mutate shared process, reader,
and backoff fields without a lock or single-owner lifecycle contract. Concurrent
shutdown and restart can terminate the wrong generation, overwrite a new handle,
or leave a live helper after `stop()` returns. Concurrent `stop()` calls can
operate on the same pipe and process.

**Recommendation:** stop requests must prevent future starts, then synchronize
with the lifecycle owner before final cleanup. Specify supported thread usage.
Use deterministic barriers to test stop during start, restart, and publication.

### 4. The claimed bounded shutdown contains an unbounded pipe close

**Possible.** `poller.py:117-129` times out terminate and kill waits, but then
calls `process.stdout.close()` before joining the reader. A reader blocked in
text iteration may hold the buffered reader's lock. Closing it from another
thread can wait for that lock without the nominal five-second deadline.

An unkillable helper, or a custom helper's descendant retaining the write end,
can keep the read blocked even after the direct child's wait finishes. The
existing fake stdout test has no blocked reader and cannot detect this.

**Recommendation:** make reader/pipe cleanup obey an end-to-end shutdown budget;
do not rely on a timed join after a potentially blocking close. Test with a
blocked real pipe and a descendant that keeps stdout open. See Python's
[subprocess pipe and process rules](https://docs.python.org/3.13/library/subprocess.html).

### 5. Name-keyed snapshots silently discard distinct devices

**Confirmed.** `poller.py:56-58` uses `info['name']` as the sole dictionary key.
Two devices with the same display name collapse to the last entry. This can
occur with identical interfaces or the same hardware exposed by different host
APIs. Reordering enumeration can change which device survives. Renaming a
device looks like removal plus arrival, not an identity-preserving update.

reccy's `device_key()` explicitly notes that its name fallback is not unique;
using that fallback alone would not solve this problem. PortAudio indices are
also enumeration-specific, not persistent hardware identities.

**Recommendation:** preserve every enumerated endpoint and explicitly define
identity, host API, and cross-refresh matching semantics. Do not promise stable
identity where the backend lacks it. Test duplicate names, host-API duplicates,
reordered lists, and renamed devices before selecting an API shape.

### 6. Process handles are discarded without proving shutdown

**Confirmed on the failure path.** After both waits time out,
`DeviceQueryStream.stop()` logs an error but clears `process` and `reader`
(`poller.py:124-132`). The reader join result is not checked. A later call can
launch another helper while the old helper/reader is still alive. Repeated
failures can accumulate processes, threads, handles, and native backend clients.

`join_process()` similarly returns `True` even if a process remains alive after
the kill wait (`supervision.py:18-21`). Its boolean reports forced intervention,
not verified exit. A caller can incorrectly assume resources are safe to reuse.

**Recommendation:** retain ownership of unresolved cleanup and expose verified
exit separately from escalation. Test a process that remains alive after kill;
the current fake always becomes dead immediately when killed.

## P2: watchdog, exceptional conditions, and resources

### 7. Malformed JSON values can keep a broken helper healthy indefinitely

**Confirmed.** `_read()` queues any decodable JSON. `devices()` resets freshness
and backoff before `DevicePoller.poll()` validates the value (`poller.py:141-145,
48-55, 173-177`). A helper emitting `{}`, a number, or lists with missing fields
never publishes useful snapshots, yet keeps postponing recovery. JSON syntax
errors behave differently: they are dropped and eventually trigger timeout.

**Recommendation:** only valid enumeration messages establish health. Separate
protocol failure from genuine empty discovery and retain useful diagnostics.
Test syntactically valid but structurally invalid messages for longer than the
watchdog deadline, not only one rejected list.

### 8. Freshness measures consumption time, not observation time

**Confirmed.** `last_update` changes when `devices()` drains the queue, not when
the worker observes devices or the reader receives a message. A queued old
snapshot from a dead helper is returned as fresh before checking process exit.
Stopping/restarting does not clear queued updates, so a previous generation's
snapshot can be delivered after shutdown or replacement.

If a consumer polls less often than five seconds, each old buffered update can
also defer dead-helper detection by another polling period. No timestamp or
generation lets the consumer tell what it received.

**Recommendation:** define freshness at valid message receipt, distinguish
generation boundaries, and specify stale-delivery behavior. Test a queued update
followed by helper death and stop/restart with an undrained update.

### 9. Briefly productive crash loops bypass exponential backoff

**Confirmed.** Every non-None JSON update resets backoff to one second. A helper
that emits one snapshot and crashes on each launch repeatedly resets the failure
streak (`poller.py:141-159`). Process creation and native initialization continue
at roughly the initial retry rate rather than backing off toward 30 seconds.

**Recommendation:** reset backoff after an explicitly defined healthy period,
not merely one line. Test repeated one-update-then-exit generations separately
from the existing never-produces-an-update backoff test.

### 10. Thread creation/start failures leave partially initialized ownership

**Confirmed exceptional path.** `DeviceQueryStream.start()` creates the process
before starting its reader (`poller.py:89-110`). Thread-limit or memory-related
failure after Popen leaves a child and pipe owned by an incomplete stream.
`DevicePoller.start()` likewise launches a helper before starting its poll thread.
An already-started or previously-used Python thread raises on another start,
potentially leaving a newly created helper without polling.

**Recommendation:** clean up partial starts and document single-use versus
restartable objects. Test reader-start failure, poller-thread-start failure,
double start, and start after stop/join. Popen OSError retry alone is insufficient.

### 11. Stop and join do not have ordinary thread-like timing semantics

**Confirmed / contract gap.** `DevicePoller.stop()` can wait for terminate, kill,
and reader join, nominally up to 15 seconds plus unbounded close. `join(timeout)`
first waits for the poller thread, then stops the helper regardless of whether
that thread finished. It can exceed the supplied timeout and race with a still
running thread that restarts the helper. `join()` without first stopping an
otherwise healthy poller waits indefinitely, as with a looping thread, but this
requirement is undocumented.

The installed threa 1.11.0 implementation uses an uninterruptible post-delay
sleep and sets its running event inside the new thread. Very long intervals
delay join; an early stop before that event is set can be overwritten. These
are dependency-sensitive risks, not independent guarantees in dvice.

**Recommendation:** publish lifecycle semantics and a total shutdown deadline;
test immediate start/stop, sleeping poller shutdown, and timed join while active.

### 12. Latest-value replacement is not atomic for multiple producers

**Possible when public methods overlap.** `_put_latest()` drains a queue and
then calls `put_nowait()` without covering both operations atomically
(`poller.py:182-188`). Two writers can both drain, then one gets `queue.Full`.
The reader does not catch it. Normal single-reader/single-poller operation does
not by itself establish this race; concurrent public `poll()` calls or surviving
old-generation readers from lifecycle failures do.

**Recommendation:** either enforce the single-producer contract or make
replacement safe for supported concurrency. Do not describe Queue's individually
thread-safe calls as an atomic replace. Test the interleaving if multi-producer
use is supported.

### 13. Output memory is not bounded by the one-slot queues

**Confirmed lack of limit; impact depends on helper output.** `query_devices()`
buffers all stdout, and the reader buffers a complete line before JSON parsing.
A custom/broken helper can emit an enormous line or endless data without a
newline. Queue capacity bounds message count, not bytes, and does not prevent
parent memory exhaustion. JSON decoding and enumeration-to-dictionary conversion
can also consume excessive CPU for large messages.

**Recommendation:** define a reasonable protocol byte/device bound for helper
output and a failure policy. Do not catch MemoryError and claim reliable recovery
without accounting for remaining resources. Normal device enumeration is small;
this is a robustness concern, not evidence of an ordinary memory leak.

### 14. Polling intervals permit busy loops and confusing recovery latency

**Confirmed / contract gap.** `interval` has no validation (`poller.py:23-31`).
Zero and negative values remove threa's delay, causing a busy polling loop.
NaN also fails its `> 0` check; infinity can cause sleep failure. Very large
values postpone failure detection and retry well beyond the five-second watchdog.

Meanwhile the worker always enumerates every 0.1 seconds independently of the
poller interval (`discovery.py:12, 36-39`). Slowing the consumer does not reduce
native enumeration/JSON work. Multiple pollers each create their own helper.

**Recommendation:** validate finite supported intervals and distinguish producer
cadence from consumer cadence. Measure enumeration cost on realistic backends;
do not presume 10 Hz is cheap on every machine.

### 15. Error diagnostics are lost, and failure modes are inconsistent

**Confirmed.** Streaming stderr goes to DEVNULL. Crashes/import failures and
invalid JSON have no contextual diagnostic; `last_exitcode` is only captured at
cleanup. A nonzero helper exit is restarted without logging its cause. Invalid
encoding can end the reader through ValueError, also silently.

The one-shot API propagates spawn, nonzero-exit, decoding, and JSON exceptions,
but turns timeout and PortAudio failure into empty results and trusts a `cast`
rather than runtime validation. Some exceptions are appropriate to propagate;
the problem is the inconsistent and undocumented contract.

**Recommendation:** document result/error semantics, validate the one-shot
protocol too, and expose bounded diagnostics for streaming failure without
blocking on or retaining unlimited stderr. Test spawn/import failure, nonzero
exit, malformed JSON, wrong shape, and encoding failure.

### 16. Interrupts, parent exit, and helper descendants lack an ownership policy

**Possible / contract gap.** Helpers start in a new session and streaming helpers
have no context-manager cleanup of their own. Parent crash or forgotten stop
can leave a child alive. KeyboardInterrupt during streaming stop can interrupt
cleanup before ownership fields are finalized. The one-shot `subprocess.run()`
path has different built-in cleanup behavior and should not be conflated with
streaming Popen ownership.

`terminate()`/`kill()` target only the direct child, not an entire descendant
tree. Custom commands are accepted, and can spawn descendants that retain pipes
or survive shutdown. `join_process()` has the same direct-process scope. Python
[documents descendant and IPC limitations of termination](https://docs.python.org/3.13/library/multiprocessing.html#process-and-exceptions).

**Recommendation:** explicitly restrict helper commands or define descendant
ownership, document host cleanup obligations, and test interrupted cleanup and
parent death. Do not advertise process isolation as automatic orphan prevention.

### 17. Forced multiprocessing termination can damage consumer IPC

**Possible, consumer-dependent.** `supervision.join_process()` escalates without
knowledge of the process's queues, pipes, locks, or shared resources. Python
documents that forced termination can corrupt queues or leave locks held. A
consumer that reuses those resources after a forced stop may lose liveness.
Unstarted/closed processes and invalid/unbounded timeout inputs also have no
declared preconditions; callers can get exceptions or defeat boundedness.

**Recommendation:** document started-process and finite-timeout preconditions,
the nominal budget `timeout + 2 * stop_timeout`, verified-exit responsibility,
and the need to discard/recreate unsafe IPC after forced termination. This
utility cannot itself guarantee recovery of arbitrary consumer state.

### 18. Device validation accepts impossible values and promises too much typing

**Confirmed.** Only string name and integer input-channel count are checked.
Python booleans pass the integer check, negative channel counts pass the truthy
filter, and empty names are accepted. Remaining dictionary values are unchecked.
`DeviceDict` is a broad scalar dictionary alias, not a validated schema; the
one-shot `cast` does not enforce even the streaming checks.

**Recommendation:** define the minimum protocol contract required by consumers,
including non-negative channel counts and usable names, without inventing fields
the backend cannot supply. Align one-shot and streaming validation and test
those boundaries. Decide where the portable descriptor belongs before moving
types or adding a second representation.

## P2/P3: public API clarity and project boundaries

### 19. Public names hide filtering, consumption, and side effects

**Contract gap.** The short names are easy to type and do not conflict with
Python built-ins, but several imply behavior they do not provide:

| Name | Current behavior or ambiguity | Suggested direction |
| --- | --- | --- |
| `DevicePoller` | Publishes only input-capable devices, keyed by display name | Say input-device explicitly or document/filter explicitly |
| `latest()` | Consumes pending data; a second call returns None, not the last snapshot | A `take_latest`-style name communicates consumption |
| `DeviceQueryStream.devices()` | Consumes updates and may start/restart a child | Describe this as polling/advancing, not a passive accessor |
| `DeviceQueryStream.restart()` | Usually stops and schedules a restart; backoff prevents immediate start | Distinguish scheduled restart from immediate restart |
| `DeviceQueryStream.stop()` | Does not disable later implicit starts from `devices()` | Distinguish helper cleanup from permanently stopping the stream |
| `devices_json()` | Queries PortAudio in the caller, without process isolation or timeout | Mark as worker-side/in-process behavior, not a safe public query |
| `stream_devices()` | Blocking infinite stdout loop, not an iterator or audio stream | Document the worker protocol and blocking behavior |
| `join_process()` | Can terminate/kill, returns intervention rather than successful join | Give escalation a visible name and document result precisely |
| `interval` | Consumer-thread delay, not enumeration cadence | Name or document the exact clock it controls |

The three query paths also differ in shape: all devices as a list, input devices
as a name-keyed map, or serialized JSON. `None`, `[]`, and `{}` have different
meanings that are currently easy to misread. Document these before changing names;
renaming alone must not hide a behavior decision. Add a small public API example
showing lifecycle ownership, errors, and consuming updates.

### 20. Project description overstates hardware supervision

**Contract gap.** dvice restarts the query helper and provides a process shutdown
utility. It does not open audio streams, monitor callback progress, reset actual
hardware, reboot devices, retry stream opens, or distinguish a listed but
unresponsive endpoint. An interface can remain listed while audio delivery is
dead. Those responsibilities currently remain with consumers such as recs.

**Recommendation:** distinguish enumeration health, endpoint presence, and stream
health in README/API documentation. List the actual scope and supported platform
evidence. Do not silently add a hardware-reset or recording subsystem as a fix.

### 21. Latest-only snapshots cannot guarantee observation of every transition

**Confirmed intentional behavior, undocumented consequence.** Both queues retain
only the latest value. A device can disappear and reappear between consumer reads,
especially with the same name/capabilities, with no visible transition. A caller
must not treat these snapshots as a complete unplug/replug journal or proof that
an existing stream survived a reboot.

**Recommendation:** document snapshot semantics and require independent stream
health monitoring where needed. Decide separately whether transition history is
a real requirement; do not replace bounded latest-only queues with an unbounded
event log by default.

### 22. Packaging and dependency ownership limit reuse and reproducibility

**Confirmed tradeoff, P3.** dvice depends on reccy mainly for `DeviceDict`, tying
a small device utility to a broader shared package and its Git source on moving
`main`. The checked-in lockfile pins this checkout's resolution, but downstream
applications resolving their own environments need not use that lockfile.
Unbounded future threa versions can also change inherited lifecycle behavior.

**Recommendation:** document supported dependency behavior and the intended
descriptor owner. Consider release/pin policy when publishing for independent
consumers. Do not introduce a duplicate type or dependency migration without an
ownership decision. Source URLs are already consistently HTTPS here; the earlier
SSH/HTTPS conflict is not an outstanding issue in this checkout.

## Testing and structure

There are four nonempty package modules, all at most 188 lines. No oversized file,
substantial internal duplication, or need to inline worker/supervision is evident:
the worker is a real subprocess entry point and supervision has a distinct API.
The latest-value helper is reused rather than duplicated. The empty `__init__.py`
does not create re-export ambiguity.

The tests cover basic filtering, rejected fields, exit/stall restart, initial
backoff, Popen failure, query timeout/exit error, and terminate/kill escalation.
They are small and not excessively duplicated. However most lifecycle checks use
fake processes/pipes or call the private reader synchronously. They do not
exercise the interleavings and real pipe behavior described above. Prioritize:

1. Deterministic shutdown/start/restart races and failed partial starts.
2. Real helper/pipe fixtures for blocked reads, killed helpers, reader termination,
   malformed protocol, and surviving descendants, without opening audio hardware.
3. Failure-versus-empty semantics, duplicate endpoints, stale generations, and
   briefly productive crash loops.
4. Platform-specific physical qualification of hot-plug and host-service recovery,
   reported separately from unit tests.

No new test framework is indicated. Do not unit-test external hardware behavior
as though mocked enumeration establishes backend support.

## Disk, network, and other exceptional conditions

dvice performs no application disk writes and has no network protocol or network
retry loop. Runtime network-failure and disk-full recovery features would be out
of scope. Package installation uses Git/package-network access, and startup
imports depend on available files. A network audio backend can fail behind
PortAudio; dvice sees only enumeration results/errors, not its transport health.

Existing protections worth retaining are subprocess isolation for one-shot
queries, timeout/kill escalation, bounded message-count queues, a dedicated pipe
reader, monotonic clocks, and Popen OSError backoff. These reduce but do not remove
the process/thread/FD/memory/CPU risks above. No arbitrary retry of every exception,
generic network framework, database, or recording-file recovery belongs here.

## Additional work beyond the prompt

None.
