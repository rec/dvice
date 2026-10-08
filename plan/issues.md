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
Further API changes require a user decision.

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

**Deferred by user agreement: platform-specific crash/tree ownership.** The
single-process helper contract and host cleanup obligations are now documented.
One-shot queries clean up on interruption; streaming cleanup retains handles for
a caller to retry. Abrupt parent death can still leave a direct helper alive.
Arbitrary descendant trees are not supported. A future guarantee requires a
separate platform-specific design, including Windows job objects; do not claim
that graceful cleanup or process isolation provides crash supervision.

## P2/P3: public API clarity and project boundaries

### 22. Release policy and inherited dependency behavior remain unpinned

**Deferred by user agreement: release policy unchanged.** Device descriptions
and identity helpers are now owned by dvice. The checked-in lockfile pins this checkout's resolution, but downstream
applications resolving their own environments need not use that lockfile.
Unbounded future threa versions can also change inherited lifecycle behavior.

**Recommendation:** consider release/pin policy when publishing for independent
consumers. Moving descriptor ownership does not settle version policy or guarantee
unchanging inherited thread behavior.

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
