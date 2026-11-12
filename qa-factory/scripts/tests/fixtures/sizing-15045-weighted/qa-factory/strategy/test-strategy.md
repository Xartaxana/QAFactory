# Test strategy — testproject1-test-harness

As-of date: 2026-09-14

## Scope

Functional testing only in v0. Non-functional checks — performance, security, accessibility,
localization, compatibility, privacy — are out of scope in this version.

## Test layers

Two layers, both pytest, both in this repository under `testproject1_test_harness/tests/`.
Scale at onboarding: 315 test files, 1411 `test_` functions, 23 `conftest.py` files.

| Layer | Marker | Where | Stack |
|---|---|---|---|
| API integration | `api` (1046 uses) | `testproject1_test_harness/tests/<domain>/` — every dir except `ui/` | pytest 8.4 + PyHamcrest 2.1, all calls through the Test Project 1 SDK client and `tests/utils/*_utils.py` |
| E2E UI | `ui` (321 uses) | `testproject1_test_harness/tests/ui/<area>/` | pytest-playwright 0.8 / Playwright 1.61 (sync API), Page Object Model under `tests/ui/pageobject/` (71 classes) |

Supporting layers: `pytest-xdist` (parallelism), `pytest-rerunfailures` (`--reruns 2` by
convention), `pytest-timeout` (300s default), `pytest-repeat`. Poetry, Python 3.12.

Domain directories, largest first: `ui` (86 files), `workflow` (83), `assistant` (51),
`budgets` (22), `vendor` (12), `integrations` (9), `skill` (7), `llm` (7), `auditor` (6),
`projects` (5), `activity` (5), `search` (4), `conversations` (4), `user` (3),
`scheduler` (2), `administration` (2), and one each for `webhook`, `swagger`, `roles`,
`providers`, `mermaid`, `e2e`, `analytics`.

There are no unit tests here and that is by design — this repository is a test harness, not
unit-tested itself. The application repositories carry their own suites: `../../testproject1`
1011 pytest files (749 of them using `mock`/`patch`, live HTTP in only 8 — unit level), and
`../../testproject1-ui` 613 vitest files under `environment: 'jsdom'`. Counts as of `82c81e41c`
and `5084e1120`.

Those suites are the app teams' to own, and the factory neither runs nor writes them. It
**reviews** them, and only within the story's diff: for each story, how complete and how
correct the unit coverage is for the files that story actually touched (team decision,
onboarding 2026-09-18). They are registered as `implementation_repos[]` with `role: review`
and mapped in `config.run.levels.unit`, so the board can place them in the pyramid instead
of showing them as `level not recorded`.

The two contours the factory does execute are declared as `config.profiles[]`: `api`
(adapter `pytest` 8.4.1) and `e2e-ui` (adapter `pytest-playwright` 0.8.0). Only selected
profiles participate in readiness.

## Code-level rules live in framework-rules.md

One fact, one owner: everything about how test CODE is written and executed is owned by
`strategy/framework-rules.md` (delivered to `qa-automator` and `qa-code-critic`), not restated
here. Look there for:

- **Run commands** — the pytest invocations, `--ui-headless`, what `-n` silently deselects,
  and which suite needs AWS.
- **Team conventions (declared by humans)** — the rules the team stated: credentials through
  `CredentialsManager`, SDK-first, marker stack order, worker counts, `--reruns 2`.
- **Confirmed conventions** — what is enforced on new code: PyHamcrest over bare `assert`, no
  raw `requests`, no loops in test bodies, selectors only in page objects.
- **Traps in this repository** — the known potholes a test author walks into.

A plan is decided with this document; code is written against that one. When the two would
disagree, framework-rules.md wins on anything code touches.

## Case-id convention

Case ids are allocated here, at plan and case design, in the form
`TP1-<ticket>_TC_<nnn>` — the same id is used in the markdown case file and in the test
that covers it, which is what joins the two. How code points back at an id (the `@case`
docstring) is owned by `framework-rules.md` § Naming the covered case in code.

## Git conventions

- Branch: `TP1-<ticket>_<slug>` — e.g. `TP1-14705_dynamic-configuration-single-component-resolver`. Never commit to `main`.
- Commit: `TP1-<ticket>: <Subject>` — holds for 30/30 of recent history. The colon is required; Conventional-Commits prefixes are not used.
- MR title: same as the commit form. MRs are merged server-side on GitLab, so local history has no merge commits.
- Pre-commit: `poetry run ruff check --fix`, `poetry run ruff check`, `poetry run ruff format` (equivalent to `make ruff`). A PostToolUse hook in `.claude/settings.json` already runs ruff after every Python edit.

## Risk and impact scale

Canonical impact mapping for defects and test planning:

| Impact | Priority | Severity |
|---|---|---|
| data-loss | P0 | blocker |
| money | P0 | blocker |
| access | P0 | critical |
| blocked-flow | P1 | major |
| degraded | P2 | minor |
| cosmetic | P3 | minor |
| none | P3 | minor |

**P1 areas.** Assistant chat including tool invocation · workflow execution (sequential,
parallel, multi-state) · budgets, spend tracking and chargeback — *the most important area on
this project* · skills CRUD and subagents · API integrations (GitLab, Jira, Confluence, MCP)
· authentication, authorization and role enforcement · datasource create/index/query ·
project and user management · LLM model management and routing.

**P2 areas.** Search · analytics · scheduler · webhooks · vendor integrations (guardrails,
knowledge bases) · conversations (listing, sharing, deletion).

**P3 areas.** UI visual styling, tooltip and hover text, animation, labels not on an action
path. Explicitly not critical for this project.

**Unclassified.** `tests/mermaid/`, `tests/swagger/`, `tests/providers/`,
`tests/administration/`.

## Adapters and external writes

- **Tickets** — Jira, project `TP1`, is available through the `jira-assistant` session
  agent and through the direct Jira API using `QA_JIRA_EMAIL` and `QA_JIRA_API_TOKEN`.
  The direct API preserves original attachments; secret values are stored only in the local
  user environment. Every assistant call needs a fresh per-task conversation id.
- **Test management** — none exists. Cases and results are markdown under `qa-factory/`.
- **VCS** — GitLab at `git.example`, group `tp1-group`, project `testproject1-sdk`, via `glab`.
  Authentication verified during onboarding.
- **Bugs** — written as a proposal file first, then submitted to Jira by a role or the human.
  The factory never writes to Jira unattended.
- **ReportPortal** — configured in `.env` and supported by the harness, but factory runs do
  **not** report there. Factory runs are iterative and include deliberate red probes; sending
  them would pollute the team's real results history.

## Environments

**`localhost` — the default stand since 2026-09-15**: the local docker-compose stack, API
`http://localhost:8080`, frontend `http://localhost:5173`, local IDP (no Keycloak), one
account — the superadmin. Safe to break. It cannot cover the role matrix, the auditor, or
anything needing integration credentials from AWS Parameter Store.

**`preview`** stays registered for exactly those cases —
`https://example.net/code-assistant-api`, Keycloak, pre-deployed, safe to
break — and needs AWS-issued secrets this machine does not have.

**Production is deliberately not registered**, so it cannot be selected by name. Any other
stand is added to `config.json` first, only when a task explicitly names it. Full detail in
`project-profile.md`.

## Definition of done

A story is tested when every case in its plan either has a passing automated test or was
manually verified on the target stand, with no open blockers.
