# Codex 0.7.0 scout incident: evidence and limits

Status: historical 0.7.0 findings, investigated 2026-09-19. Repairs are tracked in [the reliability plan](codex-scout-reliability-plan.md); installed-host results are in [the audit](codex-compatibility-audit.md). This investigation does not establish successful S1 acceptance or full parity.

## Run and cancellation timeline

The inspected desktop session subsequently ran a story (anonymized as QA-EXAMPLE). The historical transcript recorded these UTC events:

| Event | UTC | Elapsed since dispatch |
|---|---|---|
| First scout dispatch | 17:48:43.867 | 0 |
| Orchestrator follow-up | 17:54:07.222 | 5m 23s |
| Orchestrator interrupts first scout | 17:56:17.245 | 7m 33s |
| Retry scout dispatch | 17:57:55.035 | 0 |
| Orchestrator interrupts retry | 18:01:10.314 | 3m 15s |

The orchestrator described a normal/bounded collection window and then explicitly cancelled both agents. There is no evidence that a factory five-minute hard timer fired. Tool work and partial source artifacts existed; lack of a final digest did not prove a dead worker. The final checkpoint attributed recovery to native dispatch availability, which these cancellations do not demonstrate.

`scripts/runtime_policy.py` sets discovery_active_seconds to 900 and emits nonblocking warnings. `agents/qa-scout.md` explicitly makes these milestones soft. `design/orchestrator-handoff.md` says to let active work settle. These written instructions did not prevent the orchestrator's cancellation decisions.

## Source collection was incomplete

The inspected project-relative `qa-factory/artifacts/QA-EXAMPLE/work/source-inventory.json` records:

- QA-EXAMPLE: one comment, two original Markdown attachments with hashes and inspection references. Overall source inspection was still pending. Presence of receipts alone does not validate every extracted requirement.
- Linked tested ticket QA-PARENT: a saved ticket body includes three comments, but collection failed during attachments with a Windows path-length error. The inventory marks the source unavailable; complete attachment/comment coverage is not established.
- Required MR material was unavailable. Git refs and a partially written context manifest existed, but neither replaces complete ticket/MR evidence. No stage was accepted.

`scripts/source_inventory.py` caps the filename at 120 characters, not the full nested path, and the attachment loop catches FetchError rather than filesystem errors. A body saved before failure can coexist with an incomplete inventory.

There is a separate gate defect: completeness excludes unavailable sources/materials from `gate_blocked`; `scripts/source_preflight.py` reports them as gaps without adding errors. Other pending inspection checks blocked this incident, but unavailable required evidence alone is not consistently a blocking condition. Scout instructions also conflict: one passage permits unavailable evidence to reach S2 as an oracle gap, while another requires a capability halt.

## Git access did not establish GitLab API access

The scout first used unsupported `glab mr view --json` syntax, then retried with `--output json`. Requests for UI MRs 1881/1924 and backend MR 4214 returned 404; SSH queries for UI MR refs succeeded. The scout continued deriving local diff context without obtaining the MR material.

Read-only diagnostic requests during this investigation returned 401 Unauthorized from the GitLab user endpoint and 404 Project Not Found from the relevant project/MR endpoints. The inspected glab configuration had no entry/token for the target host; the checked process and Windows user environment had no GitLab token variables. This identifies an authentication gap in the selected glab route, not proof that no other credential provider exists on the computer. No credential values were printed or changed. A 404 alone cannot distinguish a nonexistent MR from hidden unauthorized resources.

`scripts/readiness.py::check_vcs` only checks Git and the existence of a remote. Its successful result did not verify GitLab authentication or MR read access.

## Doctor and pricing limitations

`scripts/host_capabilities.py::inspect` aggregates script-hash receipts, always returns live_parity=not_certified, and has no active host-origin behavior probe. Installed script smoke tests cannot establish live hook trust, enforcement or delivered context. Missing receipts also do not prove hooks are disabled. Doctor needs explicit per-mechanism verification with actionable unknown states.

The bundled model-rate catalog currently has one OpenAI entry, gpt-5.6-terra. A fresh project therefore lacks complete default Codex-model rate coverage. Unconfirmed pricing presentation already exists; broader model coverage and fresh-install acceptance remain necessary.
