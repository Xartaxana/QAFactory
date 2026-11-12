# qa-factory

QA Factory **0.11.0** keeps closed variety in data files a project can extend, not in code: launch forms, test
locations, dependency files, adapter forms and a probe's language are rows; a story's price is one number from
two sources that must agree; the fixes of a legacy Codex run are home.
QA Factory **0.8.1** lets a red run outrank the manifest: a test that failed is never shown as passing in
the report and is not stamped `Automated`.
QA Factory **0.8.0** runs the story loop by code: a driver moves the story between the boundaries
and calls a model only where judgment is needed. It also brings the third delivery verdict
(`after_checks`), the test command proved at onboarding, and a person's word for the build.
0.7.19 added the native Codex adapter, response-scoped usage and activity costs, and restored the
original dashboard graphics, full case detail, trends and metric warnings.
[Install/upgrade](INSTALL.md) · [Acceptance status](design/codex-compatibility-audit.md).
A shipped adapter or passing local smoke does not certify installed hook trust or live parity.


A ticket-driven functional testing factory. Give it a ticket and it takes the story from
context and grounding through a plan, test cases, automation, quiet test runs and triage
to a code-computed checks ledger — and stops for a human decision exactly twice before
anything reaches a merge request. Installs as a Claude Code plugin. Project state lives in
`qa-factory/`; test changes target the explicitly resolved project repositories.

## Entry points

| Command | What it does |
|---|---|
| `/qa-factory:qa-onboarding` | One-time (repeatable) setup — discovers the repository, interviews only the gaps, writes `qa-factory/config.json` and the strategy files after an explicit "yes". |
| `/qa-factory:qa-story <ticket> [--mr\|--branch\|--commit] [--env] [--ungrounded] [--side <name>=<reality>] [--reference <side>=<stand>]` | Runs the ten-stage pipeline for one ticket, stopping at gate A (the plan and cases) and gate B (the results). |
| `/qa-factory:qa-doctor` | Read-only diagnosis — install health, project readiness, factory audit, every open story's state — ending in exactly one recommended next action. |

## How a story runs

`qa-story` moves one ticket through ten sequential stages. A task event journal is the
source of lifecycle state; `pipeline.json`, reports and the dashboard are code projections.

1. **S0 Preflight** resolves task paths, existing work, required capabilities and an
   immutable requirements snapshot. Bootstrap never invents an implementation SHA.
2. **S1 Context** — `qa-scout` gathers bounded source evidence, resolves verified
   repository/source SHAs and a suitable branch, and builds a reusable context bundle.
3. **S2 Understanding** — `qa-requirements-tester` builds requirements and `understanding.md`.
4. **S3 Plan** — `qa-test-strategist` defines risk, depth, scope and regression recommendations.
5. **S4 Cases** — `qa-case-designer` compares automated and manual scenarios with existing
   cases; `qa-case-critic` independently reviews critical or ambiguous designs. **Gate A**
   presents `understanding.md` and `test-plan.md`, including cases. Exact authorized TMS
   description changes may be published after approval.
6. **S5 Automation** — `qa-automator` runs the initial selected tests, then only failed or
   invalidated instances after a fix. `qa-code-critic` reviews current code and performs
   isolated, assertion-specific red proof using that green evidence.
7. **S6 Run** reuses current S5 evidence and executes only outstanding current-scope checks
   and agent-manual work. A stage transition never repeats a current green run. Missing or
   stale execution requires an explicit fingerprint or provenance reason, such as detected
   new merge-request content or deployment identity, and remains inside the existing budget.
   Regression is recommended to the user and is never run by the factory.
8. **S7 Triage** — `qa-failure-analyst` classifies remaining failures; deterministic empty
   triage needs no role call. Repair and infrastructure retries have cumulative limits.
9. **S8 Results** — `qa-doc-scribe` presents the code-computed ledger inside `test-report.md`.
   **Gate B** records decisions per gap and external action; delivery uses those decisions.
10. **S9 Retro** — the orchestrator asks the existing optional feedback question and always
    dispatches `qa-retro-analyst`, preserving its knowledge, cost, feedback and closure work.
    The final human documents are `test-report.md` and `retro.md`.

See [the controller API](references/controller-api.md), [risk policy](references/risk-policy.md)
for executable contracts. Host model defaults are inherited; explicit supported role overrides are
independent of test risk. Capability profiles are discovered and extensible. External tools
are provisioned only for selected capabilities with an exact authorized dependency descriptor.

Existing projects retain their configuration: use the read-only doctor and explicit artifact
migration before resuming old tasks. Legacy receipts are reconciled as stale evidence rather
than automatically accepted under the new contract. The target of at least 2x lower cost
requires paired real-story measurement; local tests do not establish that result.

## What the human sees

**Gate A** (after S4): one message — paths to the full documents, the scope card, the
complete plan table with every row — and a fixed set of decisions: is the understanding right,
is the size right, is the plan approved or edited row by row, is each row's `fit` target
correct, and what to do with every requirement that has no counterpart in the code.

**Gate B** (after S8): one message, fixed order — the **checks ledger first** (every plan
row and every test in exactly one state), then `delivery_ready: yes`, `after_checks` (ready once you finish the checks left with you) or `no` with its reasons,
then a summary under 2 KB. The human decides which bugs to file, whether to open the MR,
whether to publish cases, and what stays open. When the verdict is `no` there is no
"open the MR" option — only **`deliver_with_risks`**, and only with a stated reason, which
the guard then requires in the journal before the MR or a TMS write can run, and which
lands in the MR as a banner. The bug reporter does not wait for the verdict: it opens on the
recorded gate B decision, and the story counts as closed only after the orders that decision
gave (the bugs filed, the MR opened or called off) are carried out.

## What is enforced by code

From `hooks/hooks.json`, on every matching tool call — not a role's discretion:

- **P-00 and secrets** — `guard_pre_tool.py` blocks any write into a protected application
  path and any file or content matching a secret pattern, on `Write`/`Edit`/`NotebookEdit`
  and on `Bash`/`PowerShell`.
- **Stage guard, four rules** — order (a stage's prerequisites must be `done`), gate A
  recorded after S4 and before S5, the automation manifest free of undecided `unresolved[]` entries
  before S6–S8, and delivery gated on the verdict (`yes` and `after_checks` open it) or a recorded `deliver_with_risks` —
  checked on every role dispatch and every git/MR/TMS-shaped command.
- **Validators and detectors** — `validate_artifacts.py` checks every artifact `Write`/
  `Edit` against its schema and `references/detectors.json`'s regex list (skip-marker
  masking, plan antipatterns, and more) before the role can move on.
- **Exit gate** — `exit_gate.py` checks a role's `required_outputs`/witness artifact
  actually exists on `SubagentStop`, and re-runs a stage's extra detectors on a clean
  handoff.
- **Cost capture** — supported host telemetry is recorded by request, activity, role and
  exact model. Known default rates show an unconfirmed estimate immediately; missing rates
  leave an explicit partial subtotal. Onboarding and doctor are named activities.

## Configuration and dashboard contracts

`references/templates/config.json` is the single installation template. Onboarding
discovers repository settings first, asks only unresolved relevant questions, then presents
the complete proposal for approval. Doctor lists every configured repository. Unanswered
questions become stable deferred decisions (DD) visible on the dashboard.

Use the onboarding migration proposal to upgrade an existing configuration; changes need
its recorded approval and retain a backup. Strategy permissions apply to exact files.
Legacy schedules are not armed or required. Dashboard updates are local code-only projections
after accepted artifacts, registry changes and usage capture, with a doctor refresh on demand.

The [metric contract](references/metrics-contract.md) defines four groups, missing-data states
and sources. Each formula expansion uses the same catalogue as the computed projection.
Regression remains a recommendation for the user to execute; no dashboard update runs tests.

## What it never does

- **Never deploys anything.** You say where an environment is reachable; the factory
  never brings one up.
- **Never writes to Jira or a TMS directly.** A role writes a local file plus a proposal;
  a separate deterministic script executes only the exact authorized action: case descriptions
  after Gate A; results, bugs, delivery and retirement/archive actions after Gate B.
- **Never launches product-test commands outside the authorized runner.** Automated execution
  uses typed requests through `run_suite.py`; manual captures use validated immutable blocks.
- **Routine decisions stay within the approved scope.** Missing authorization or evidence
  becomes a concrete blocker. S9 retains the optional human feedback question.
- **Never modifies application code.** It only files bugs; a hook blocks the write.

## Try it on the fixture

```bash
python scripts/make_fixture_repo.py --out /tmp/qa-fixture
cd /tmp/qa-fixture
```

Then, from inside that repository:

```
/qa-factory:qa-onboarding
/qa-factory:qa-story QA-1 --branch feature/qa-1 --env local \
  --ticket-file "${CLAUDE_PLUGIN_ROOT}/evals/fixtures/tickets/QA-1.md"
```

`QA-1.md` is read through the `file` ticket adapter — the same one the evals use — pointed
at `evals/fixtures/tickets`; no tracker is required.

## Development

```bash
python scripts/selftest.py --fast   # commit-time tier: static checks + every test file under ten seconds
python scripts/selftest.py          # the full run, with the slow files — before a release
npm run eval:check              # from the repository root — validates skills/*/evals/evals.json
```

`scripts/selftest.py` (see its own docstring) runs every script's own `--selftest`, the
fixture-repo root resolution, an English-only package check,
skill/agent/reference size caps, every `scripts/tests/test_*.py`, and last a package-hygiene
check: a marketplace whose source is a local directory installs whatever lies in this
directory, so anything git does not track here would be shipped to the next user. `npm run eval:check`
validates each skill's `evals/evals.json` against the repository's eval schema.
`evals/plugin-eval-benchmark.json` holds 17 end-to-end scenarios on the fixture repo for
the live plugin-eval runner.

## More

New tasks bind observation surfaces, independent expected values and case versions before
Gate A. Technical normalization preserves that approval only when code verifies unchanged
semantics; changed requirements reopen Gate A before another design review. Accepted
product scope does not grow without an explicit decision.

Controller checkpoints retain approvals, accepted evidence and remaining work. A normal
orchestrator handoff waits for all dispatches, jobs and external writes to settle. Automatic
fresh-context continuation needs verified host support; otherwise the packet supports a
manual new-session resume. Unknown usage remains unknown, and agent usage is accounted
separately from orchestrator window usage. No measured cost reduction is claimed.

- [`UPGRADE.md`](UPGRADE.md) — updating an existing installation and project
- [`INSTALL.md`](INSTALL.md) — installing, uninstalling, developing the package
- [`references/README.md`](references/README.md) — the index of every reference file, who
  reads it, and when

## License

Apache License 2.0 - see [LICENSE](LICENSE). Author: Xartaxana.
