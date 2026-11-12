# Codex scout reliability and default pricing: follow-up plan

Status: implemented in 0.7.1; Windows host fixes in 0.7.2; live acceptance tracked separately. Extends the [dashboard/parity plan](dashboard-cost-repair-plan.md). See [incident evidence](codex-scout-incident-2026-09-19.md). All P0 items block reliable Codex story acceptance.

## P0. Worker lifecycle must not turn waiting into cancellation

Targets: controller.py, runtime_policy.py, host_dispatch.py, orchestrator-handoff.md and story/S1 instructions.

- Separate host polling timeout, progress notice, discovery soft milestone, proven worker failure and an explicitly configured hard execution budget. A wait timeout or missing final digest is not worker failure. Existing 15-minute milestones remain informational; discovery lasting 30 minutes or longer is valid while required collection continues.
- Persist worker identity, status, last observed progress/tool operation, checkpoint and cancellation reason. Missing heartbeat means unknown liveness until checked, not automatic death. Do not start a replacement while the original worker is active or cancellation is unacknowledged.
- Route supported stop/retry actions through a controller decision with an explicit cause: user stop, confirmed terminal worker failure, acknowledged evidence blocker, or a separately authorized hard budget. Elapsed discovery time alone cannot authorize interruption. A suspected stall triggers inspection/follow-up, not an invented deadline.
- Enforce the rule at the host dispatch/tool boundary where interception is supported. Inventory direct interrupt/spawn paths; if a host cannot enforce them, report that limitation and require observed acceptance rather than claiming that instruction text is enforcement.
- On a required-source blocker, notify the user immediately, persist partial work and allow an orderly blocked handoff. Finishing an in-flight operation or preserving already collected data is allowed; accepting incomplete discovery is not. Stop automatically restarting the same inaccessible work.
- Record orchestrator-initiated cancellation distinctly from scout failure or unavailable native dispatch. Premature controller cancellation must not consume the scout's failure retry allowance. Resume the existing worker when possible, otherwise resume a confirmed terminal worker's durable checkpoint without repeating completed retrieval.

Acceptance: deterministic clock-driven tests at 5, 15 and 30+ minutes; active long tool call, sparse progress, polling timeout, unknown liveness, true terminal failure, explicit stop and late handoff. Assert no duplicate scout, no elapsed-only cancellation, truthful checkpoint reasons, preserved artifacts and correct retry accounting. Also observe one real host run across multiple wait intervals.

## P0. Complete both tickets and every relevant MR before S1 acceptance

Targets: qa-scout.md, phases/s1.md, adapters-read.md, source_inventory.py, source_preflight.py and context_bundle.py.

- Distinguish launch/source and tested subject tickets. For both, collect full body/acceptance criteria, all comment pages, attachment metadata, original bytes and inspection receipts. Follow relevant references with provenance and cycle protection; exclude unrelated tickets.
- Inventory all relevant MRs from both tickets, their attachments and comments across every code repository. Preserve multiple MRs in one repository; the current first-hit-per-repository cascade is insufficient. Distinguish QA-only changes from tested product changes, recording the reason for any exclusion.
- Collect MR metadata, description, all comment/discussion pages and changed-file/diff evidence, pinned to the inspected revisions. Represent truncated, binary and unavailable content explicitly. Resolve source disagreement visibly rather than silently choosing a convenient local branch.
- Track retrieval and semantic inspection separately. A downloaded file, partial JSON manifest or local ref does not constitute complete context. Source instructions remain untrusted input; their existence does not authorize executing embedded instructions.
- Make every unavailable required source/material an S1 blocker, consistently in inventory completeness, preflight, bundle validation, digest and controller. Remove the contradiction that allows required unavailable sources to advance as S2 oracle gaps. Optional exclusions require explicit relevance reasons. Any user-approved alternative scope must be recorded and revalidated, never silently inferred from access failure.
- Provide per-ticket and per-MR coverage: retrieved/expected, inspected/expected, pending/unavailable and reason. Unknown totals remain unknown. A blocked scout must send a structured blocker that the orchestrator promptly presents to the user with the affected source and exact next step.

Acceptance: two linked tickets with paginated comments and multiple attachments; several MRs in the same repository and across repositories; links embedded in comments/attachments; missing source, failed download, uninspected attachment, incomplete discussion page and changed revision. Every missing required element blocks acceptance, without discarding valid partial work. No fabricated complete coverage or silent MR-to-local-ref substitution.

## P0. Diagnose MR access before trusting the VCS capability

Targets: readiness.py, qa-doctor/SKILL.md and adapters-read.md.

- Separate Git access, provider API authentication and MR read capability. Probe the configured route and exact host/project/MR when required. A remote listing cannot make MR readiness green.
- Inspect existing configured credential providers and environment visibility without logging secrets before asking for credentials. Distinguish unsupported CLI options, sandbox/config-file denial, network failure, 401, 403 and ambiguous 404. Check supported CLI syntax; do not conflate GitHub and GitLab flags.
- On 404, verify authentication and project visibility before asserting the MR is absent. SSH success does not authenticate the API. Report the actual failed capability immediately, including whether repair belongs to factory configuration, the selected adapter or user access.
- Stop fallback on authentication/authorization failure. Local refs may preserve provisional evidence but cannot replace unread required MR metadata/discussions. Verify recovery with read-only requests, then resume from the checkpoint.

Acceptance: SSH works/API unauthenticated, authenticated without project permission, wrong IID, wrong host, valid API route, missing inherited environment, unsupported flag and sandbox denial. No secret values in diagnostics and no request for a new token while an existing supported route remains unchecked.

## P0. Attachment collection must survive Windows paths and partial failure

Targets: source inventory storage and receipt verification.

- Use stable compact storage identifiers; retain the original filename in metadata. Budget the entire absolute path, including atomic temporary suffixes, Unicode filenames and deep project roots. Do not rely only on truncating the attachment basename or changing machine-wide Windows settings.
- Handle filesystem failures per material; preserve already fetched ticket bodies/comments, valid attachments and precise error receipts. Resume idempotently from verified hashes. A failed attachment cannot silently become read, disappear from the expected count, or cause all prior evidence to be lost.

Acceptance: deep Windows project path matching the pilot shape, long Unicode filenames, duplicate names, interruption during atomic write and successful resumed retrieval. Required attachment failures stay visible blockers.

## P0. Doctor must verify actual Codex hooks and injections

Targets: host capabilities/readiness, doctor and host adapter.

- Report installation, registration, enablement, trust, invocation and verified behavior separately for the detected CLI/Desktop host and version. Script smoke tests only prove scripts run. Freshness must include relevant host/session, configuration and script identity, not merely a matching script hash.
- Exercise isolated, harmless host-origin probes: permitted and rejected tool actions, actual delivered role context, artifact/exit gates, child dispatch/delivery, journal and cost receipts. Verify outcomes, not just receipt presence or successful exits. Synthetic event tests remain a separate test category.
- Include compaction/reload and interruption recovery in full parity acceptance. Separate essential pre-story checks from later lifecycle checks, avoiding a circular prerequisite for S1.
- Doctor/readiness must expose failed or unknown essential enforcement/injection checks as actionable story-readiness blockers. When the host cannot expose trust or run a probe, say exactly what is unverified and how to verify it; do not infer trust or bypass its approval mechanism.
- Replace the permanently hardcoded aggregate with evidence-derived per-mechanism status. Full parity can be certified only when the complete live acceptance matrix passes; partial receipts cannot certify it. Keep existing Claude behavior and verify both hosts.

Acceptance: installed but disabled/untrusted hooks, enabled scripts never invoked, stale receipts, invocation with wrong behavior, successful allow/deny and injection probes, child completion, compaction and interruption. Doctor must distinguish every state and agree with story readiness.

## P1. Default OpenAI model prices on a fresh installation

Targets: rate catalog, resolver, install/upgrade defaults and Cost UI.

- Inventory supported Codex model IDs and documented aliases; cover every model with an available authoritative rate. Verify official provider sources, effective dates, input/output/cache categories, context bands and applicable service tiers when implementing. Do not invent rates for unsupported or undocumented IDs or map all models to Terra.
- Ship versioned defaults so a new project gets reference estimates as soon as matching usage exists, without manual tariff setup. Show the rate source/date and a persistent unconfirmed-tariff label until the project confirms its own pricing. An API reference estimate is not a Codex subscription bill.
- Unknown model or rate yields explicitly unavailable/partial USD, never zero or a guessed tariff. Preserve existing project overrides and confirmation state through upgrades; make catalog changes auditable and avoid silently repricing history.

Acceptance: clean installation with no tariff file, each supported catalog model, input/cache/output reconciliation, rate/context boundaries, unknown model, mixed known/unknown totals, project override and upgrade preservation. Cost grouping remains separate for each story, doctor and onboarding.

## Order, consistency and completion

Implement lifecycle/evidence gates, access diagnostics, Windows-safe collection, then live doctor probes and pricing defaults. Update instructions and executable gates together. Run fixture checks before live acceptance; resume the pilot from preserved evidence after access and essential-host blockers are resolved.

Consistency checks: no new implicit five- or thirty-minute hard deadline; no duplicate worker; blockers notify without sacrificing checkpoints; required evidence cannot become a nonblocking gap; Git reachability is not API readiness; script smoke is not live parity; bundled reference pricing is not confirmed billing. Keep the existing dashboard/47-metric acceptance and preserve project roles, settings and historical evidence. Updating an installed plugin must not add duplicate project-local roles.

Completion requires accepted pilot S1, observed Codex lifecycle/hooks, Claude regression acceptance and fresh-project pricing coverage. Record results/limitations in the compatibility audit. Installed 0.7.0 does not prove completion. Release base: 0.7.2; Codex builds carry a cache suffix. Live acceptance remains separate.
