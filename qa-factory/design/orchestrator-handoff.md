# Orchestrator handoff

`state/checkpoint.json` is an atomically refreshed, revision-bound index of scope, Gate
decisions (including authorization), blockers, remaining checkpoints, cumulative counters and
accepted artifact hashes. Use `controller.py --operation checkpoint-packet` with `page` and
`page_size` for additional decision/remaining-work pages. It contains no secrets, artifact
bytes or transcript.

A 40-model-request window or 70% reported context sets `rollover_pending`; it never interrupts
active work. Handoff waits for dispatches/jobs/external writes to settle. A fresh context needs
a verified host adapter, a monotonic lease generation and host acknowledgement
`{session_id, fresh_context:true}`. Otherwise use `manual_continuation`; never claim a fresh
session. Every mutation after handoff carries the current owner lease.

Window metrics come only from verified `orchestrator_telemetry`, never agent counters. They
reset to unknown at handoff. Cumulative story costs and repair counters persist.

For scout waiting, cancellation authority, source blockers and checkpoint recovery, follow [scout recovery](scout-recovery.md). A poll timeout does not authorize cancellation, even after 30 minutes; use controller request_cancel with recorded evidence for any supported stop.
