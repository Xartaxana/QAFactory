# References — index

Everything a role reads as "the rules", delivered automatically at dispatch by
`inject_context.py` per `inject-map.json` (Layer 1 = `common`, Layer 2 = the role's own
slice), or read directly by the orchestrator skill (`qa-story`, `qa-onboarding`,
`qa-doctor`) as part of its own phase instructions. No file a role is injected exceeds
12 000 bytes; none contains a `model` field or a model name.

**Slices.** A subject is ONE file here — one owner per fact (audit A21) — but a role is
injected only the sections marked for it. A section carries its readers on a marker line
directly above its heading (`<!-- roles: qa-automator, qa-code-critic -->`, or `all`) — above
and never inside, because other checks match heading text exactly; an unmarked `###`
belongs to its `##`. `scripts/contract_slices.py --write` renders
`slices/<role>/<subject>.md` (lead + the sections that role acts on) and those files are
committed — the injection hook renders nothing, it has milliseconds. `inject-map.json`
points at the slices, audit A22 (role start load, `scripts/role_load.py`, thresholds in `role-load.json`) weighs them, audit A9 and `selftest.py --slices` refuse a
stale one. To give a role a section: mark the SOURCE, add the entry to `inject-map.json`,
re-run `--write`. Never edit a file under `slices/`.

| File | Who reads it | When |
|---|---|---|
| `tester-manifesto.md` | every `qa-*` role | every dispatch (Layer 1, `common`) |
| `common-rules.md` | every `qa-*` role, as its own slice | every dispatch (Layer 1; sections by role) |
| `vocabularies.md` | every role that writes a value from a closed list (9 of 12) | on write — the validator rejects anything outside these lists |
| `artifact-contract.md` | every role that writes an artifact | where artifacts live, and the project-level files |
| `artifact-contract-plan.md` | `qa-requirements-tester`; `qa-test-strategist`; `qa-case-designer`; `qa-case-critic` | S2–S4 — the documents gate A is built from |
| `artifact-contract-results.md` | `qa-doc-scribe`; `qa-retro-analyst` | S8–S9 — the ledger, the report, the retro |
| `stage-model.md` | orchestrator (`qa-story`); `qa-doc-scribe` | orchestrator: every stage transition, to drive `stage_guard`/gates; doc-scribe: assembling the gate-B ledger |
| `automation-candidacy.md` | `qa-test-strategist`; `qa-automator` | S3 — deciding each row's disposition and `fit`; S5 — following the embedding ladder |
| `code-review-rubric.md` | `qa-code-critic` | S5 — the nine-dimension rubric, the twelve smells |
| `test-code-patterns.md` | `qa-automator`; `qa-code-critic` | S5 — which pattern fits a recurring problem in test code, and when not to introduce one |
| `adapters-read.md` | `qa-scout` | S1 — reading the ticket, how a tracker is reached, freshness, the VCS cascade |
| `external-writes.md` | `qa-bug-reporter`; the `external_writes.py` script | after gate B — the proposal-file contract and the channel vocabulary |
| `environments.md` | `qa-runner`; `qa-failure-analyst`; the `env_probe.py` script | S6 — resolving the stand and preflight; S7 — `execution_status` and ENV_ISSUE ownership |
| `templates/requirements-register.md` | `qa-requirements-tester` | S2 — the register's exact form |
| `templates/understanding.md` | `qa-requirements-tester` | S2 — the ≤40-line gate-A summary |
| `templates/test-report.md` | `qa-doc-scribe` | S8 — the one report the human reads at gate B |
| `templates/retro.md` | `qa-retro-analyst` | S9 — the retro artifact's shape |
| `templates/obligations.md` | `qa-doc-scribe`; the orchestrator | S8/S9 write; S0 of the next story reads what has ripened |
| `templates/factory-backlog.md` | `qa-retro-analyst` | S9 — findings about the factory itself, and deferred onboarding decisions |
| `templates/questions-for-owner.md` | `qa-requirements-tester`; `qa-test-strategist` | S2/S3 — assembled as part of the gate-A message |
| `templates/config.json` | `qa-onboarding` | onboarding generation — the project's `qa-factory/config.json` starting shape |
| `templates/readiness.json` | `qa-onboarding`; the `readiness.py` script | onboarding generation, and every `--require` check at S0 |
| `case-lifecycle.md` | `qa-case-critic` (sliced); the orchestrator | S4 — the findings file's shape, `## Gate A debts`, who pins a case version |
| `inject-map.json` | the `inject_context.py` hook | every `PreToolUse Agent\|Task` dispatch — what to deliver to which role |
| `slices/<role>/*.md` | generated, never hand-edited | what `inject_context.py` actually delivers — see "Slices" above |

**Everything in this directory is loaded while the factory runs** — injected to a role, read by a
script, or named by a skill phase as a thing to read while working. That is why each `.md` file is
capped at 12 000 bytes, and why every file here with a recipe suffix enters the package fingerprint a
dispatch is bound to (`release_fingerprint.package_fingerprint()`, the one recipe `install_smoke` and
`runtime_paths` call; audit A14 reads `release_fingerprint.compare()` and `factory_manifest.py --stamp`
pins the same map). The
one exception is `release-fingerprint.json`: the release step writes it in the release copy only, the
collector's `release_fingerprint.compare()` reads it, and it is excluded from the fingerprint it records.

**A document nothing loads belongs in `../design/`,** not here: the rules every change to the factory
must satisfy (`design/factory-rules.md`, `FR-1` … `FR-44` — read that one first), the driver's own
design, the dashboard contracts and plans, the Codex compatibility audit and the scout incident.
`design/README.md` states the boundary, and `selftest.py --homes` holds it in both directions: a
reference nothing consumes belongs in `design/`, and a document in `design/` that something starts
loading must come back here.

`artifact-contract.md` defines artifact homes; `detectors.json` supplies the mechanical
checks referenced by the review rubric. `controller-api.md` describes lifecycle mutations
and links the continuation contract. Runtime paths come from `runtime_paths.py`; producer
validation comes from `artifact_producer.py`, not a second set of handwritten schemas.
