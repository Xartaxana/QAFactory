# Codex integration and cost acceptance for 0.7.0

Companion to [the repair plan](dashboard-cost-repair-plan.md).

## 0. Make the entire host integration verifiable (P0)

1. **Installation and hook trust.** Provide a native Codex installation/upgrade path, discoverable roles and skills, version/build identity and a host capability report. Confirm enabled plugin and reviewed hook definitions; a trusted repository is not proof of trusted hooks. Do not auto-bypass trust or silently claim hooks are active from file existence.
2. **Normalize tool events.** Map actual Codex events into common policy inputs: canonical Bash commands, multi-file `apply_patch` add/update/delete/move operations, actual dispatch and follow-up tools, and relevant connector writes. Matcher aliases do not change `tool_name` or the input schema. Preserve blocking exit codes and encode feedback in each host's supported output format.
3. **Enforce policies.** Run application-boundary, secret, ownership, manifest/case-store, direct-run and publication/gate checks for every supported equivalent operation. Protect both source and destination of moves. Test nested code-mode calls and shell sessions; identify unsupported tool surfaces explicitly. No silent allow on an unrecognized mutating event.
4. **Roles and injection.** Adapt the role roster, exact role instructions, allowed/disallowed tool intent, context slices, dispatch IDs, task identity, model/effort inheritance and repair-to-original-agent protocol. Preserve the existing common and per-role injection map, budget caps and provenance. Prove that each child receives the complete required context and that forbidden-stage dispatch is rejected.
5. **Validation and completion.** Validate all affected artifacts after a patch; do not stop at the first path. Apply exit gates and journal receipts to real Codex subagent identities; preserve incomplete versus accepted status, bounded repair and concurrency isolation. Codex feedback must reach the intended agent.
6. **Compaction, interruption and recovery.** Encode PreCompact context as supported JSON; keep the compatible SessionStart/compact restoration and verify delivery. Check persisted controller state, approvals, repair budgets, execution jobs and resume across turns, interruption and fresh sessions. Record explicit manual continuation where automatic handoff is unverified.
7. **Execution and integrations.** Exercise quiet runner, witness generation, scheduler, environment preparation, ticket/TMS/VCS adapters and both approval gates through Codex. Use local fixture adapters for destructive/publication cases; no live ticket creation is needed for parity validation. Do not run product suites just to populate dashboard graphs.
8. **Self-diagnosis.** Upgrade doctor/install smoke to distinguish source files, loaded hooks, hook trust, observed invocations, valid receipts and supported capabilities. A green standalone Python smoke must never be reported as green Codex integration.

Acceptance: paired Claude/Codex event fixtures and isolated live-host smoke produce equivalent allow/deny, context, lifecycle and artifact results. Critical parity failures block release. A prompt telling the model to call the checks is not an equivalent enforced hook.

## 1. Establish the Codex evidence contract (P0)

Inspect a small, redacted sample from the actual host before selecting a supported local usage source. Record available session, invocation, request, timestamp, exact model and token fields; distinguish request deltas from cumulative counters. Do not infer capabilities from a product name or equate account quota percentages with task usage.

Normalize evidence behind a host adapter into the existing cost projection. Preserve provenance and coverage status. Count cached input once, handle included reasoning tokens without double counting, and avoid adding child usage already included in parent totals. When request identity or granularity cannot be verified, expose the narrower supported scope and leave the activity split unknown.

Deliverables: a documented adapter contract, redacted fixtures, adapter implementation and readiness capability checks. If no sufficiently detailed source exists, the implemented result must explicitly report the limitation rather than inventing numbers.

## 2. Record activities reliably (P0)

Update doctor, onboarding and story invocation paths to pass explicit host, project, session, invocation ID and evidence reference. Reuse invocation identity across continuations; do not create a new activity for every human answer. Cover discovery, interview, approved generation and final response usage. Nested doctor/story intervals must be disjoint. Link child dispatches through evidence, not time alone.

Surface missing identity as a telemetry diagnostic while allowing the workflow to continue. Handle duplicate starts/ends, interruption and recovery; retain unclassified usage when attribution is ambiguous. Import usage at supported lifecycle boundaries without assuming a Claude Stop hook exists in Codex.

Acceptance: one doctor and one multi-turn onboarding produce distinct activities, with no cross-task leakage or double counting after replay.

## 3. Price only verified usage (P0)

Resolve the exact model and effective tariff through a versioned catalogue or explicit rate override with provenance. Verify official rates during implementation; do not invent or substitute a Terra tariff. Keep usage completeness, attribution completeness and pricing coverage as separate dimensions.

Label computed USD as an estimate, not a subscription charge or invoice. Show tokens even when price is unknown. Use a known subtotal only when part of the request set is priced, alongside unpriced tokens/requests. Keep external consumer receipts separate until deduplication is evidenced. Reconcile the same request set across activity, task, role and model; exact tokens and USD tolerance of 0.000001 before rounding.
