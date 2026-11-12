# Stage model

`references/stages.json` is the machine-readable authority used by guards and dispatch.
Artifacts are scoped to the task and revision; a completed stage is reusable only while
its inputs remain current.

| Stage | Outcome | Boundary |
|---|---|---|
| S0 | preflight, task paths, requirements snapshot and readiness records | bootstrap binds to requirements evidence, not a placeholder implementation SHA |
| S1 | grounded context, verified repository/source SHAs and bounded diff | resolve source and a suitable branch before application-code writes; unresolved material facts remain explicit |
| S2 | requirements register and stable `understanding.md` | blocked contradictions halt planning |
| S3 | stable `test-plan.md` | no human gate yet |
| S4 | reused/updated/new text cases plus independent case review | **Gate A after S4, before S5**; approved TMS actions may then publish |
| S5 | automation windows, independent review | author one run per version; critic one probe call per instance, each check, by code; no post-restore green |
| S6 | fresh remaining automated instances and `manual-agent` work | no impact regression; reuse requires source/runtime/environment freshness |
| S7 | evidence-based triage | test validity and product outcome remain separate |
| S8 | ledger and stable `test-report.md` | **Gate B after S8** controls delivery actions |
| S9 | closure and retro | existing S9 process is unchanged |

Gate A presents `understanding.md`, `test-plan.md`, reviewed cases, risks, gaps, execution
split, source SHAs, regression recommendations and proposed external actions. Gate B
presents verified/failed/unverified/accepted-risk results, manual-human work, regression
recommendations and delivery choices. Approval applies only to the shown action and
revision; edits invalidate affected decisions.

After Gate A, a semantic test-design change reopens S4 and stales only the affected
approval before any new case review. Verified semantic-preserving normalizations retain their
review and approval receipt. S5 code review remains an implementation review.

See `execution-lifecycle.md` for S5/S6 run, fingerprint and red-probe rules.
