# Native Codex acceptance for 0.7.x

This is a release gate, not a statement that a Python fixture proves host integration.
Use an isolated project and local mock ticket/TMS/VCS adapters. Never create real external
records or run a product suite just to exercise the dashboard.

1. Verify the installed plugin version/path and reviewed `hooks/codex.json`. Start a fresh
   host task. Reuse installed roles; export CLI profiles only if that host requires them. Preserve the current model
   and effort unless the test explicitly supplies a supported override. Record host version.
2. Run doctor, then a multi-turn onboarding. Confirm one continued onboarding identity,
   disjoint nested doctor intervals, a pending final-response close and captured final usage.
   Session usage stays provisional until completeness is actually established.
3. Invoke three isolated mock stories, including two concurrent story contexts and a
   second session continuing one story. Use real returned child IDs. Confirm common/role
   injection and the task/dispatch packet in each child, without posting raw prompts.
4. Attempt a protected application patch, a two-file patch whose second file is protected,
   a protected delete and a move into/out of the protected tree. Expect exit 2 before writes.
   Probe secret, case-store, manifest ownership, direct test execution and publication gates
   with synthetic values. Test nested code-mode calls. Interactive shell command input is
   explicitly blocked; use individually guarded non-interactive commands.
5. Produce two invalid artifacts in one patch; both errors must reach the author. Attempt
   an early-stage dispatch. Attempt a repair addressed to a foreign story's child. Both must
   be rejected. Repair the original child's output and verify bounded exit-gate receipts;
   an incomplete handoff is not accepted merely because the hook released a repeated Stop.
6. Exercise quiet execution/scheduler, execution evidence, environment preparation and both
   human gates using fixture adapters. Interruption/resume must preserve controller state,
   approvals, lease fencing, budgets and settled jobs. Fresh-session creation is still a
   manual continuation when the host capability is unverified.
7. Trigger compaction; observe JSON PreCompact feedback and PostCompact/SessionStart restoration.
   Resume from actual persisted state, not from a claimed summary. Test model/effort inheritance
   and a deliberately unsupported override. CLI overrides must match the exported TOML;
   desktop overrides require a spawn schema/history mode that supports them.
8. Compare normalized outcomes with the same fixture workflow on Claude Code. Compare
   allow/deny, injected role/context, final accepted artifacts, lifecycle and usage records.
   Reconcile request tokens and priced subtotals across stories, roles, models and activities.
9. Trigger a versioned metric rule; check its banner on all tabs and delivery at the next
   lifecycle boundary. Check replay, acknowledgement, insufficient samples, recovery and
   regression. Preserve unpriced/unattributed usage and gaps in historical trends.

Record the observed tool/hook identities, script hashes, timestamp, result and artifact
references under `state/host-receipts/` and the acceptance report. File presence is not trust;
receipts are not a substitute for the paired assertions above. A missing or stale mechanism
blocks a full parity claim. The bundled readiness report deliberately says `not_certified`
until an independently reviewed live acceptance report exists; it does not self-certify.

Observed usage format: Codex rollout `session_meta`, `turn_context` and unique
`token_usage_record` responses. Aggregate `token_count` notifications are excluded. Cached
input is split from total input once; reasoning remains included in output. Unknown cache
write semantics, conflicting duplicates or malformed records produce explicit diagnostics.
This local format is versioned by the adapter and is not assumed to be a stable public API.

Tariff reference: [Terra pricing](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
verified 2026-09-19. Standard API equivalent USD estimates use exact model identity and
per-request context length. They are not Codex subscription invoices. Historical request
valuations remain pinned; revaluation requires a distinct comparison receipt.

## 0.7.1 essential pre-story probes

Doctor prepares `host_probe.py --prepare --session <real-id>`. Execute the two returned
native shell calls separately, then dispatch qa-scout with exactly
`QA_FACTORY_CONTEXT_PROBE`, native task name `qa_factory_context_probe`, and no ticket. Wait for natural completion and run --check.
The wrapper correlates allow/deny with host transcript call IDs; injection requires the
bound child's actual assistant response to the injected challenge. Config/script changes
or expired probes invalidate readiness. Do not expose the challenge in the caller prompt.
Synthetic fixture transcripts test the verifier but do not certify the installed host.
`essential_verified` certifies these probes only, never the full matrix above. Hooks on
specialized host paths that bypass interception remain a host limitation to test explicitly.

Codex context is delivered through SubagentStart, without rewriting encrypted spawn messages.
Native launches from one parent are serialized only until SubagentStart consumes the pending
packet; already-running workers can remain concurrent. Use a task name containing the exact
story key for multi-story dispatch. Never infer a story from whichever file was newest.
