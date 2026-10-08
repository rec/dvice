# Useful additions to dvice

Status: proposed, not implemented. Written 8 October 2026 against `d97f173`.
This is a shortlist for implementation decisions, not authorization to change
the public API. Keep dvice focused on discovering audio endpoints and supervising
unreliable native operations. Applications still own what their devices do.

## Recommended order

| Order | Feature | Immediate consumer benefit |
| --- | --- | --- |
| 1 | Readable discovery health and current observation | Distinguish absent devices from unavailable discovery; share one discovery owner |
| 2 | Output and duplex discovery with useful backend information | Use the same supervision for playback endpoints and explain duplicate names |
| 3 | Ambiguity-aware selection and snapshot differences | Avoid selecting the wrong endpoint; handle observed arrivals and removals consistently |
| 4 | Explicit fresh-discovery requests | Respond to a user's Refresh or Retry action without manipulating helper internals |
| 5 | Bounded waits for initial discovery or a selected device | Start services and interactive applications without ad hoc sleep loops |

Start with feature 1. Implement the others in small, separately reviewed slices.
Each slice should have a concrete consumer integration before the next begins.

## 1. Readable discovery health and current observation

**Current gap:** `latest()` consumes an observation. `None` cannot tell an
application whether nothing changed, discovery is starting, or a helper failed.
Useful helper state exists, but consumers must inspect lifecycle internals and
interpret logs. Multiple readers can also accidentally steal each other's data.

**Plan:** provide one canonical, non-consuming observation/status contract on
the thread-owning poller. Include the last successful endpoint list, a sequence
number, host-monotonic receipt time, helper generation, and discovery health.
Expose a concise failure category and next retry time when applicable. Status
reads must not launch processes, wait for cleanup, or require a new helper.

Keep a never-observed result distinct from a successful empty list. Retain the
last successful observation through failures, clearly marked as no longer current.
Stop must be distinguishable from retrying. Callers track the sequence themselves;
no per-reader queues, subscription registry, or unbounded history is needed.
Returned descriptions must not let one reader mutate another reader's view.

Receipt time means the host received a valid observation, not that hardware was
just refreshed. A helper generation identifies an enumeration process, not a
physical device reboot. Discovery health does not establish audio-stream health.

**Acceptance:** independent readers see the same observation; failures never
become empty inventories; old generations are rejected; status reads remain
prompt during helper replacement and shutdown. Use deterministic unit tests and
audio-free helper fixtures, not claims about physical hardware from mocks.

**API decision before implementation:** agree on the observation model and the
replacement for consumptive `latest()`, then update consumers together. Do not
silently change its meaning or maintain parallel legacy delivery paths.

## 2. Output and duplex discovery with useful backend information

**Current gap:** one-shot discovery returns all endpoints, but `DevicePoller`
publishes only input-capable endpoints. Descriptions contain a host-API number,
but not enough context for a person to distinguish otherwise identical names.

**Plan:** support input, output, or all-endpoint selection within the existing
discovery owner, retaining inputs as the default. A duplex endpoint appears once
in an all-endpoint observation. Include host-API names alongside channel counts
and sample-rate information already supplied by the backend. Keep duplicate
endpoints; filtering must not cause extra enumeration helpers.

Identify enumeration-local indices explicitly if exposed. Positions in a filtered
list are not PortAudio indices. An index from the isolated helper cannot be
assumed to address the same endpoint in a consumer's separately initialized
PortAudio process. Do not invent persistent IDs, infer cross-process addresses,
or add a native CoreAudio/ALSA/WASAPI identity bridge as part of this feature.

**Acceptance:** cover input-only, output-only, duplex, duplicate names across
host APIs, and empty observations. One-shot and polling descriptions must agree
on the same underlying endpoint information. Backend qualification is separate.

## 3. Ambiguity-aware selection and snapshot differences

**Current gap:** `device_key()` is an identity hint with a non-unique name
fallback. It is not a safe selector or a cross-refresh matching algorithm.
Consumers repeatedly write name matching and inventory comparison logic.

**Plan:** add small, pure operations for selecting an endpoint from an
observation and comparing two successful observations. Prefer an explicitly
supplied persistent ID, with its backend scope. Allow exact-name selection with
host-API and input/output constraints. Return distinct not-found and ambiguous
outcomes instead of selecting the first match. Avoid fuzzy or prefix matching.

Match across observations only when the evidence is unique and sufficient.
Duplicate IDs and indistinguishable endpoints remain ambiguous. A name-only match
is a weak match, not proof of hardware continuity. Without an ID, a rename may
remain unmatched. Do not match by list position or a previous enumeration index.

Differences describe observed inventory changes, not sample-exact unplug events.
Never compute removals from a failed discovery observation. No persistent
assignment database, automatic deduplication, or application reconnect policy.

**Acceptance:** cover unique IDs, duplicate IDs, identical names across backends,
reordering, renamed devices with and without IDs, channel-count changes, and
ambiguous matches. Operations must not mutate either input observation.

## 4. Explicit fresh-discovery requests

**Current gap:** `restart()` applies failure backoff. It does not express a
healthy request for fresh PortAudio initialization, such as a user's Refresh
button after plugging in a device.

**Plan:** provide one clearly named request operation that schedules a fresh
built-in enumeration helper through the existing serialized lifecycle. Coalesce
repeated requests while a refresh is pending. Return promptly; feature 1 supplies
the eventual observation and health outcome. Do not overlap helpers or bypass
unverified cleanup, shutdown, or genuine failure backoff.

Keep the agreed five-second automatic refresh unchanged. Custom helpers must
not be advertised as refreshing native initialization unless their contract
actually guarantees that behavior.

**Acceptance:** cover concurrent requests, requests during backoff or cleanup,
and shutdown racing with a request. An intentional refresh must not count as a
failure; a failed refresh must still follow normal failure handling.

## 5. Bounded waits for initial discovery or a selected device

**Current gap:** applications often need a first observation before showing a
device picker, or must wait for a known interface before proceeding. They must
currently build their own polling, timeout, and error interpretation loops.

**Plan:** build a synchronous, deadline-limited wait on the observation changes
from feature 1 and selection rules from feature 3. Reuse the existing discovery
owner; waiting must not spawn another helper or consume another reader's data.
Support cancellation and stop without busy-waiting or introducing async/await.

Distinguish a successful empty inventory, a missing selected device, ambiguity,
discovery failure, cancellation, and timeout. Waiting for a listed endpoint does
not mean opening it will succeed or that an audio stream is ready. Do not retry
stream opening or resurrect a stopped poller on the caller's behalf.

**Acceptance:** cover already-present and later-arriving endpoints, ambiguity,
discovery failure during a wait, cancellation, deadline expiry, and shutdown.
Use a monotonic deadline; cleanup must not silently extend the stated wait.

## Implementation boundaries

- Prefer the existing thread, helper lifecycle, logging, and bounded protocol.
  No new dependency or process architecture is justified by this shortlist.
- Resolve API shape and affected consumers before each public-contract change.
  Use a single canonical model rather than adapters or duplicate implementations.
- Preserve failure-versus-absence semantics and verified process ownership.
- Extend existing focused tests. Use physical tests only to qualify actual
  backends; record untested platforms honestly.
- Recheck helper count and CPU with `scripts/discovery_benchmark.py` after
  changes affecting observation delivery or lifecycle. Multiple UI readers
  should not multiply helpers or make a slow reader delay supervision.

## Not proposed

Recording, playback engines, mixing, routing, DSP, musician/session models,
device profiles or persisted assignments, microphone privacy policy, network
device protocols, hardware resets, a discovery daemon, and arbitrary process-tree
ownership. Automatic audio-stream recovery could be evaluated later only with a
concrete consumer and a separate design; it is not bundled into these features.

Release and dependency-pinning policy remains unchanged, as agreed for finding 22.

## Additional work beyond the prompt

None.
