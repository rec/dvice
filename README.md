# dvice

Reusable supervision of unreliable audio devices. dvice queries PortAudio in
an isolated helper process, publishes current input-device snapshots, and
restarts a stalled or failed query helper with bounded backoff. It also provides
bounded process shutdown for applications that isolate audio streams in child
processes.

dvice does not decide what to record, how to name tracks, or where to write
media. Its first consumer is recs.
