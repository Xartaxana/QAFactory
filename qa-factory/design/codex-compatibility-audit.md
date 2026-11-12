# Codex compatibility audit

Date: 2026-09-19. Package: QA Factory 0.6.0. Local CLI: `codex-cli 0.154.0`; desktop runtime config reports `26.911.61220`.

**Initial 0.6.0 conclusion: full behavioral parity was not established and event-level failures were reproduced.** Existing internal tests passing does not establish that the installed Codex host loads, invokes or enforces the factory mechanisms.

Scope: package source and hook wiring, local host registration evidence, the inspected neighboring Codex run, official current host contracts, twelve existing test suites, and isolated synthetic event probes. No product source was patched, no live publication was attempted, and no real story was restarted. The native installed/trusted-plugin end-to-end test remains a release requirement, not a completed check.

## 0.7.2 installed Windows-host findings

See [native acceptance results](codex-native-acceptance-results.md) for observed trust,
Windows launch, code-mode correlation and child-identity defects, repairs and live limits.

## 0.7.1 reliability repair

The incident and repair contract are recorded in [the follow-up plan](codex-scout-reliability-plan.md).
Source regression: 75 test modules exercised; the new recovery test initially omitted the
required initialized-state fixture, then all 10 of its tests passed after correction.
The other 74 modules passed the full rerun. Size/language/injection wiring and package
hygiene passed; install smoke passed. These are source/fixture checks, not live parity.

Doctor now exercises actual native allow/deny calls and a bound-child context challenge,
checks host call IDs and freshness, and exposes essential readiness separately from full
lifecycle certification. Unavailable hooks, missing trust, opaque transcript formats or
host tool paths bypassing interception must remain explicit blockers/limitations. No
synthetic hook receipt is presented as a successful installed-host acceptance run.

## 0.7.0 implementation update

The reproduced patch, injection, output-format and launcher defects are repaired in source.
`test_codex_host.py` covers native schemas, all patch paths, multiple artifact validation,
JSON compaction feedback, native role export, request usage replay, final-response activity
closure and the literal native launcher commands. The original fixtures below describe
0.6.0, not the patched result.

Full regression initially reported 89/91 checks passing: the two failures were a split-plan
size limit and duplicate nested activity end handling; both were repaired. Final rerun and
browser evidence are recorded in the delivery validation record below.

Final source, browser and recovery results are recorded in [the validation record](dashboard-release-validation.md#implementation-validation-record-2026-09-19).

The observed neighboring rollout identifies `0.155.0-alpha.2.6`, `gpt-5.6-terra`, unique
response usage and cumulative token notifications. Only the response records are counted.
The shipped adapter labels streaming coverage provisional; missing intervals remain
unclassified. Exact Terra standard API reference prices were verified on 2026-09-19,
including cached input and the >272k input-context boundary. This is not subscription billing.

Native installed/trusted-host E2E is **not certified** by these source tests. `host-receipts`
record observed invocations with script hashes; readiness reports missing/stale entries,
without inferring trust or automatic fresh-session creation. No live story or publication
was restarted. See [native acceptance](codex-native-acceptance.md).

## Reproduced differences

| Probe against the same isolated project | Claude-shaped event | Codex-shaped event | Finding |
|---|---|---|---|
| Protected application-file change | `Write`: exit 2; blocked | `apply_patch`: exit 0; empty response | Application boundary fails for patch events |
| Invalid `pipeline.json` validation | `Write`: exit 2; broken JSON reported | `apply_patch`: exit 0; empty response | Post-write validation skips patches |
| `qa-scout` context injection | `Agent`: updated prompt includes required rules | `spawn_agent`: exit 0; no injected prompt | Context injection and its chained dispatch guard are skipped |
| PreCompact reminder | Script prints plain text | Same plain text output | Codex contract ignores plain stdout for this event; context must use supported JSON |
| Ordinary Stop activity capture | Explicit lifecycle metadata required | `Stop` with session but no activity action creates no activity record | A Stop hook alone does not establish/close skill activity tracking |

The probes invoke the real Python hook entry points using documented event shapes. They reproduce adapter defects without executing the proposed application writes. They are not a claim that a real Codex tool invocation was intercepted during this audit.

## Mechanism-by-mechanism findings

| Mechanism | Current evidence | Required repair/verification |
|---|---|---|
| Plugin/skill loading | `.codex-plugin/plugin.json` exists; the neighboring task reads skills/scripts from a Claude plugin cache. No QA Factory entry was found in the inspected Codex `config.toml` or top-level plugin cache sources. | Native install and enabled/trusted hook discovery with versioned receipts. Absence from those inspected locations alone is not proof of every possible runtime source. |
| Hook discovery and root variables | Codex documents default `hooks/hooks.json` discovery and `CLAUDE_PLUGIN_ROOT` compatibility. | Do not misdiagnose absent explicit manifest `hooks` or the compatible root variable as the cause. Verify actual registration and trust. |
| Shell hook routing | Codex documents `exec_command` as canonical `Bash`, which matches current wiring. Existing shell guard tests pass. | Test actual shell/input/return shapes, nested code mode, asynchronous completion and `write_stdin`; don't rename working aliases without evidence. |
| Application and secret guards | Guards accept legacy `Write`/`Edit` input fields. Protected `apply_patch` probe passes unchecked; secret guard also returns on an unrecognized tool. | Parse every patch path/content, deletes and moves, then apply common policies. Test secret fixtures without real credentials. |
| Ownership, case-store and manifest checks | The same legacy event assumptions occur in `guard_pre_tool.py`. | Adapt multi-file patch input and prove equivalent denial behavior. |
| Role dispatch/stage guard | `inject_context.py` returns unless tool is `Task`, `Agent` or `SendMessage`; stage guard is called only after that test. | Normalize actual dispatch/follow-up names and fields; bind role and dispatch receipt before invocation. |
| Role registration/tool restrictions | Roles are Claude Markdown definitions with `tools`/`disallowedTools`; no Codex-specific role registration/generation path was found. | Prove role instructions and permission intent survive native Codex dispatch; choose a supported native registration or explicit verified dispatch adapter. |
| Context injection | Claude-shaped probe injects common + role-specific rules; Codex-shaped probe injects nothing. | Preserve injection map, project slices, context budget, task packet and full delivery in child context. |
| Post-write validation | Invalid artifact probe is skipped for `apply_patch`. Successful validation hints are plain stdout, which Codex ignores for PostToolUse. | Validate all affected paths and encode model-visible feedback correctly. |
| SubagentStop/exit gate/journal | Internal lifecycle tests pass. `agent_type`/`agent_id` fields have compatible concepts, but role/task/dispatch binding is unverified on this host. Exit-gate success/fuse paths print plain stdout, which the Codex SubagentStop contract rejects. | Encode output correctly; actual child completion with failed and repaired handoffs, bounded fuse, incomplete status and correct story journal. |
| Model/effort routing | `runtime_policy.py` supports explicit inheritance and validates supported pairs; injection assigns a resolved `model` in legacy tool arguments. | Verify the real host dispatch parameters and inherited model/effort, including override rejection. |
| PreCompact/restore | PreCompact outputs ignored plain text; SessionStart/compact plain-text restoration is compatible with the documented contract. | Fix only the incompatible output and test actual automatic/manual compaction and immediate restoration. |
| Durable controller/recovery | Controller and handoff tests pass; fresh-context capability is explicitly unverified/manual continuation. | Preserve approvals/leases/budgets through real host interruption and resume; no false claim of automatic handoff. |
| Quiet execution/jobs/witnesses | Execution-pipeline tests pass using fixture runners. | Verify real orchestration routes selected jobs through the controller/quiet runner and waits for durable evidence; do not rerun product tests for metrics. |
| External writes/human gates | External-write and publication gate tests pass locally. | Verify all host tool routes and fixture connectors obey A/B approvals, without live publication. |
| Activity/cost/latency | Usage/activity tests pass; inspected run has no activity/cost records. Collection expects Claude-style usage; missing session/action silently returns. | Native producer, stable invocation metadata, explicit usage coverage, cost/latency receipts and accurate end-of-turn handling. |
| Readiness/doctor | Local readiness tests pass; telemetry is honestly unverified, but source-level install smoke uses synthetic legacy events. | Add per-mechanism loaded/trusted/invoked/validated evidence and fail host-parity claims when absent. |
| Dashboard refresh | Event projection tests pass. | Verify host lifecycle actually feeds it and retain original UI components; separate stories and prevent duplicate usage. |

## Checks executed

All twelve selected suites exited 0 after running with normal access to isolated temporary directories:

`test_hooks_wiring`, `test_hook_lifecycle`, `test_context_bundle`, `test_usage_activity`, `test_stage_guard`, `test_controller_state`, `test_session_handoff`, `test_execution_pipeline`, `test_external_writes`, `test_dashboard_events`, `test_readiness`, `test_publication_gates`.

Initial sandbox attempts hit Windows temp-directory permission errors for some suites; those are environment failures, not package regressions. The complete rerun succeeded. This was a targeted audit, not the entire repository test suite and not a successful native-host end-to-end certification.

Evidence for this local audit is retained under the task-owned visualization directory in `codex-audit/results.json` and one log per suite. Reproduction runner: `audit_codex.py` in that same directory. It creates isolated fixtures and never applies the probed application patches.

## Official host contract consulted

- [Codex hooks](https://learn.chatgpt.com/docs/hooks): plugin discovery/trust, aliases versus canonical event payloads, output handling and lifecycle semantics.
- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents): custom role registration and configuration.
- [Plugin packaging](https://developers.openai.com/plugins/build/plugins): packaging reference.

Documentation describes current supported contracts, not proof that every installed client version implements them identically. Capture actual event fixtures from the minimum supported desktop/CLI versions as part of 0.7.0 acceptance.
