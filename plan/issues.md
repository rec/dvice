# dvice issues and review findings

Reviewed 8 October 2026 at commit `bf2f3276ad3072479f4e4a3c8ffeb0a3182273f1`.
Resolved findings are removed below; original issue numbers are retained.

## Scope and evidence

Read every package module, every test, README, package configuration, and lockfile.
Also inspected the installed threa thread implementation, installed sounddevice
enumeration code, reccy's device types, and recs' current consumer. This is a
source review, not a hardware qualification or a reproduction of every race.
The fixes are verified with unit tests and audio-free subprocess fixtures.
No audio application or hardware experiment was run.

- **Confirmed** means a behavior follows directly from the implementation.
- **Possible** means an identified interleaving, backend behavior, or exceptional
  condition can expose it; it still needs a targeted reproduction.
- **Contract gap** means callers cannot determine the intended behavior safely
  from the API or documentation.
- **P1**: discovery correctness, shutdown liveness, or silent device loss.
- **P2**: robustness, diagnostics, resource usage, or significant API traps.
- **P3**: smaller naming, documentation, and maintainability concerns.

No P0 is established. Do not interpret a possible issue as proven on every OS.
Further API changes require a user decision. Duplicate-name changes are deferred
by user agreement while the name-keyed result contract is preserved.

## P1: discovery and lifecycle

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

### 6. join_process does not distinguish unresolved shutdown

**Confirmed on the failure path.** `join_process()` returns `True` even if a process remains alive after
the kill wait (`supervision.py:18-21`). Its boolean reports forced intervention,
not verified exit. A caller can incorrectly assume resources are safe to reuse.

**Recommendation:** expose verified exit separately from escalation. Test a process that remains alive after kill;
the current fake always becomes dead immediately when killed.

## P2: watchdog, exceptional conditions, and resources

### 14. Enumeration cost and slow-consumer recovery latency need qualification

**Confirmed tradeoff.** Finite positive polling intervals are now enforced and
waits are interruptible. Very large consumer intervals still postpone supervision;
this is documented rather than pretending a consumer delay is a watchdog deadline.
The worker enumerates every 0.1 seconds independently of the consumer interval.
Slowing the consumer does not reduce
native enumeration/JSON work. Multiple pollers each create their own helper.

**Recommendation:** measure enumeration and fresh-helper startup cost on realistic backends;
do not presume 10 Hz is cheap on every machine.

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

## P2/P3: public API clarity and project boundaries

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

There are four nonempty package modules. No oversized file,
substantial internal duplication, or need to inline worker/supervision is evident:
the worker is a real subprocess entry point and supervision has a distinct API.
The latest-value helper is reused rather than duplicated. The empty `__init__.py`
does not create re-export ambiguity.

The tests now cover blocked/idle real pipes, shutdown during start, partial-start
cleanup, dead/stale generation rejection, malformed/oversized protocol, sustained
health before resetting backoff, and interruptible interval waits. Remaining
qualification includes helper descendants, parent death, and physical hot-plug
and host-service recovery across supported platforms. Report physical results
separately from unit tests.

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
