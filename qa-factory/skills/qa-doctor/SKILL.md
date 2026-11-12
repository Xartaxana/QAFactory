---
name: qa-doctor
description: >-
  Diagnose the qa-factory installation and the current project's story state - runs the
  install smoke test, checks project readiness by capability, runs the factory audit,
  reports where every open story stands in its pipeline, ends in exactly one recommended
  next action, and then offers to archive the stories that have stood still. Trigger phrases: "check the qa-factory
  setup", "qa doctor", "where is the story", "/qa-factory:qa-doctor".
metadata:
  author: Xartaxana
  version: "0.10.0"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Agent
  - Task
---

# qa-doctor

Before any command, resolve the installed root using `references/common-rules.md` relative to
the plugin root, not `skills/qa-doctor/` ("Resolving the plugin root"); an empty shell
variable is not a missing installation.
At entry run `"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" activity_capture.py --action start --type doctor`.
It finds the session itself. `ACTIVITY NOT RECORDED` is a finding, `owner: factory`.
Keep it open through questions, gates and interrupted continuations. Right before the
final response run `--action end --type doctor --after-response`; a nested workflow returning
to its caller ends without `--after-response`. Before onboarding approval boundaries stay in
the host-local spool. Missing identity is reported, usage stays unclassified; never infer
activities from prompt prose.

Diagnosis, run between stories or whenever something feels wrong. It reports and names
**one** next action. Three questions, all after the report, never instead of a fact: the
archive offer in step 6, `phases/repair.md`'s "is anybody working on this story?", and the
price-table question in step 2.
**It writes the dashboard, activity telemetry, smoke and host-probe receipts, and - only on
a person's explicit word - `archive_task.py`'s flag and `repair.md`'s `controller.py
--operation recover|release`.** It never edits a `pipeline.json` by hand.

## Execution - seven steps, in order, each one Bash call

Never re-derive with Read/Glob/Grep what a script answers in one call. Use its summary
verbatim; do not re-judge it.

### 1. Install smoke

```
python -u "${CLAUDE_PLUGIN_ROOT}/scripts/install_smoke.py" --reuse-within 24 --report "qa-factory/state/doctor-install-smoke-latest.json"
```

`--reuse-within 24` reuses a passed report of this package (`SMOKE REUSED` - say so); drop
it for a fresh run.

Run once and wait. In Codex code mode print
the **whole** shell result (`text(r)`), keeping `session_id` and `exit_code`; an outer
`functions.wait` ends the JS cell while the shell may still run, so continue it with
`tools.write_stdin` until `exit_code` appears. Never relaunch the smoke on an empty poll: a
missing exit code means pending, never failed.

Read the saved report afterwards. `status: running`
means wait; a missing report means evidence is unavailable, not an outdated installation.
`status: passed` requires exit 0, no `FAIL` lines and both `PASS injection delivers to
'qa-factory:qa-scout'` and `PASS injection delivers to 'qa-scout'` - synthetic delivery checks
that do not certify live hooks. Report `plugin_line` verbatim plus `failures`. An exception or
missing required check in a **completed** run is a failure: name its evidence, not a guessed
reinstall. Only a completed legacy smoke lacking those checks, or a version below 0.2.0,
establishes the old-install verdict; pending or truncated output does not.

### 1b. Live hook behaviour - on every host

Report sandbox denials separately from plugin/auth failures. Follow `INSTALL.md`, "Codex
project access"; never rewrite host permissions or loop on blocked probes. Every host: Codex
through `hooks/codex.json`, Claude Code through `hooks/hooks.json` - the probe reacts to hook
events, not to a product name.

Run `host_probe.py --prepare` (it finds its own session) through the installed
launcher, then execute the two returned echo commands as separate native shell calls in the
same project/session: ALLOW must execute; DENY must be rejected by the factory guard. Never
feed synthetic JSON to hook scripts as a substitute. In Codex code mode use exactly
`text(await tools.exec_command({"cmd":"<echo command>"}));` per echo, in separate calls.

Run `--check` after the pair. Its `status` is guard verification; `injection` is separate.
With `status: verified` and `injection: unverified`, go to the probe below
(`next_action: dispatch_context_probe`): never require injection verification before the probe
that establishes it. `injection_detail` = partial answer: re-probe. Guard unverified: report missing/correlation evidence, never broken hooks.
Exit 3 (not onboarded): no pair, no probe; `host_hooks` unknown, owner factory; row 3.

Then dispatch exactly one diagnostic qa-scout (no ticket, model inherited) with the exact
prompt `QA_FACTORY_CONTEXT_PROBE` and native `task_name: qa_factory_context_probe` (a re-probe:
`qa_factory_context_probe__<suffix>`). On Codex desktop the message is
opaque to hooks, so only that `task_name` marks the probe; any other name is a real qa-scout
dispatch of the running story, refused for a missing receipt. The probe must return only the
challenge injection delivered; never put it in the prompt or simulate a child response. Wait
for its natural completion, then run `host_probe.py --check`. This is the only doctor child
dispatch: it collects no project evidence and writes nothing.
Read `host_integration.mechanisms` and `guard_probe` from readiness. `host_integration.host`
is EVIDENCE from the receipts on disk, not a label: `mixed` (opened from two tools) is a real
state. Report invocation and behaviour separately; trust/enablement as unknown if not exposed
- use the host's hook review UI for trust, never edit trust files. Two probes are not full
parity. `guard_parse` in that report: `phases/repair.md`, last section.

### 2. Project state

```
git rev-parse --show-toplevel
```

No output → not a git repository. Otherwise, if `qa-factory/config.json` exists in the current directory, run:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/readiness.py" --json --probe-vcs
```

Parse `capabilities.*`: every capability whose `status` is not `ok` is listed with its
`note`, `owner` and `remedy`. `unknown` is listed too - unverified is not "fine"; print the `note` verbatim.
Print `surfaces` when present (each `words`) and `config_schema`'s `migration_hint` (stale schema: re-onboarding instruction), verbatim.

Show `vcs` (local Git), `vcs.remote_read` (real transport, SSH included) and `vcs_api`
separately, successful Git access included. A configured remote is not proof of access;
`--probe-vcs` uses read-only `git ls-remote`. An API, network or sandbox failure never negates a
successful SSH probe and is never diagnosed as bad auth.
`vcs_api` is diagnostic unless a story needs provider API operations or MR metadata, comments
or discussions - then probe that exact MR/route; SSH refs are not its review evidence.
Else skip API gaps when choosing the action. An empty `case_store` is nonblocking.

With profiles, print `profiles` and `implementation_repos` separately. Diagnose only the
selected contours: an unselected browser or mobile dependency never reddens an API contour.
`ready` requires verified adapter support, executable/cwd probes, runtime/dependency evidence
and resolvable scoped commands; unknown provenance, SHA, adapter support or hook availability
stays unknown. Doctor never runs project tests, installs dependencies, deploys the
application, or calls independent profile results a global green.

Print every `repository_inventory.repositories[]` row, ready ones included, then the
configured-entry, distinct-checkout and unresolved-entry counts. It never says "and more". With no selected scope, `scope_required: null` is diagnostic and
supports no global ready claim; a missing selected repository blocks that scope only.

When configuration diagnostics are needed run `config_contract.py --root <project>
--migration-plan` read-only: report conflicts and deprecated inactive keys, never `--apply`.
A `/cost/model_prices` conflict: after the report ask its `question` and `rows` verbatim, apply
nothing, pass (c) on as written; one already answered (a `factory-backlog.md` row) is not repeated.
Report cost-hook and host-usage availability, rate confirmation and missing exact rates; cost
metadata alone blocks nothing.

### 2b. Settle what a read-only probe can settle

Every non-`ok` capability carries `remedy`. Run each whose `remedy.autorun` is true - read-only
probes writing nothing outside `qa-factory/state/` - then re-run `readiness.py --json` and
report. Run the probe; never print "verify this with a probe".

The Jira probe needs a sample ticket: the latest touched open story (step 4), else
`adapters.ticket.direct_api.sample_ticket`, else ask once. With none the row stays `unknown`, saying so.

`ticket_adapter: not_configured` where the session itself reaches the tracker
(`method: mcp_tool|agent|skill`) has no probe to run: no tool of yours is the role's. Its
remedy, `adapters.ticket.direct_api`, is the next action, and it blocks S1 only.

**Report the outcome, never the journey.** A row the probe settled prints as `ok` with its
`evidence_ref` - no "was unknown, now ok", no mention that a probe ran.

`environment`: the note carries the probe's three verdicts (`liveness` / `login` / `keys`).
`missing` with `owner: factory` means onboarding wrote a config that fails its own probe -
print the remedy, own it, never ask for a key value; `gap_id: login-field-unknown` is that case:
the stand asked for unsent login body fields; the note starts with the fix; re-onboarding applies it.
The login line says "proved" only for a recorded success. `env_probe` `liveness` asks the API address, `stand_health.py --probe` names the dead part: "alive" and `down, frontend_proxy` can both be true.
`unknown` with "access scheme not recorded" means the stand is alive but how this project logs
in was never recorded: not broken - re-run `qa-onboarding`; only topic 2's access question is asked.

### 3. Factory audit

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/audit_factory.py"
python "${CLAUDE_PLUGIN_ROOT}/scripts/role_permissions.py"
python "${CLAUDE_PLUGIN_ROOT}/scripts/project_gitignore.py" --root . --check
```

The third lists the `.gitignore` lines it lacks; `--write` rewrites the block. The
first two take no `--next`: every `<check>: VIOLATIONS (n)` line plus its bullets is one
item, `no violations` needs no mention. Never re-run a detector yourself.

### 4. Where every story is

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_guard.py" --stories
```

One line per story: last `done` stage, any `running`/`halted` stage or `closed <date>`
(gate B decided, S8 done), both gate decisions, every unresolved `halts[]` entry. A closed
story that still carries a running stage or an open dispatch ends with
`STALE ACTIVE STATE AFTER CLOSURE — controller.py … --operation recover`: a tail, not work
in flight. Archived stories (the flag, legacy
`_archive/`) are filtered and counted in a closing line that **names** any still carrying an
open item: archiving is "stop showing me this", not a claim the story finished. Print the
lines; never re-open a `pipeline.json`. Factory bookkeeping is repaired by code, never by
hand: `${CLAUDE_SKILL_DIR}/phases/repair.md`.

### 5. The report and the one next action

Print the report (format below) and the single next action from the verdict table. This
happens **before** any question.

### 6. Offer to archive what has stood still

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/archive_task.py" --candidates --days 14
```

No output - say nothing and this step disappears. Otherwise read
`phases/archive.md` and follow it: the two candidate classes are two different
conversations.

### 7. Dashboard

Skip entirely if `qa-factory/config.json` does not exist (nothing to render). Otherwise,
last, so the board shows this run's archiving:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/factory_dashboard.py"
```

### 7b. The permission block - only when asked

When asked why every command needs a confirmation, print this block
to paste into the project's `.claude/settings.json`, and say what it does and does not allow:

```json
{"permissions": {"allow": [
  "Bash(python \"${CLAUDE_PLUGIN_ROOT}/scripts/*.py\":*)",
  "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
  "Bash(git rev-parse:*)", "Bash(grep:*)", "Bash(find:*)", "Bash(ls:*)"
]}}
```

Reading and the factory's own scripts, nothing else: no commit, push, tracker command or
test framework. It saves wall-clock time, not money. **The human writes that file, not
you**: the factory writes nothing into a project except `qa-factory/`.

## Verdict - exactly ONE next action

Capability scope rules above apply first. Walk top to bottom, report the first row that
applies, stop.

`vcs_api`/`host_hooks` are never the next action unless an open story needs them (a dropped VPN
once became a project's single next action).

| # | Condition | Next action |
|---|---|---|
| 0 | completed legacy smoke lacks `PLUGIN:`/injection checks, or reports a version below 0.2.0 | update the plugin per `INSTALL.md` - required install checks are absent in this build |
| 0a | smoke still running or execution evidence unavailable | finish or recover the running smoke; do not infer an installation failure |
| 1 | step 1 had a `FAIL` | fix the install: name the failing check and its remedy |
| 2 | not a git repository | `cd` into the project's git working tree and re-run |
| 3 | no `qa-factory/config.json` | `/qa-factory:qa-onboarding` |
| 4 | `config_schema` capability not `ok` | re-run `/qa-factory:qa-onboarding` - cite the `migration_hint` keys |
| 5 | a capability is `missing` with `remedy.owner: user` | that `remedy`, printed in full - `missing` means the host answered and refused |
| 5a | a capability is not `ok` with `remedy.owner: factory` - an unreachable host, an unrun probe, a factory defect | NOT an action: print it, own it, next row. Never ask a person to fix the factory or turn a dropped network into a credentials errand |
| 5b | a required capability is `not_configured` or `unknown` with `remedy.owner: user` | that `remedy`; distinguish an unrun probe, inconclusive evidence and a session-only check |
| 6 | a story has an unresolved `halts[]` entry | that halt's own instruction, for that ticket |
| 6a | a closed story still carries a running/halted stage or an open dispatch (the STALE line) | `controller.py --task-root <T> --operation recover` (owner: factory) |
| 7 | a story sits at `gates.A` or `gates.B` with no `decision` recorded | "answer gate A/B for `<ticket>`" |
| 8 | step 3 found any violation | the first `<check>` line, verbatim |
| 9 | otherwise | `/qa-factory:qa-story <ticket>` - the latest touched open ticket; none named when every story is closed |

## Report format - 30 narrative lines or fewer

```
PLUGIN: qa-factory <version> — <path>   (or: version not reported - plugin older than 0.2.0)
SMOKE: <one line: PASSED / FAILED and why>

READINESS: ok - <n> of <n>            (or: <n> of <n>, your help is needed)
  <capability>  ok  <evidence_ref>    ... one line each, no history
  tracker_write  confirmed <date> | no: <reason> | not checked (the probe runs and records)

  <capability>  <status>  owner: <owner>      ... only when help IS needed
    <one line: what is unavailable, in plain words>
    <one line: what this costs AND what still works>
    -> <numbered steps, each executable as written>

STORIES
  <ticket>  last done: <Sn>  active: <Sn running|halted|none|closed <date>>  gate A: <d>  gate B: <d>

AUDIT
  <check>: VIOLATIONS (n)  owner: <user|factory>
  ... (only violating checks; if none, print "AUDIT: clean")

Next action: <exactly one line>
```

Rules of printing:

- **Steps are printed by `remedy.owner`, not by the capability's `owner`.** The capability's
  owner says whose domain the gap is; `remedy.owner` says who must act: an unreachable host is
  nobody's fault (`owner: factory`), yet only a person turns a VPN on (`remedy.owner: user`).
  A `remedy.owner: factory` row gets no steps and is never the next action.
- **A step needing something the person does not hold says where to get it**, with the minimal
  rights: a bare command that will stop and ask for a token is not a step. Routes the factory
  can take itself come before anything asked of a person.
- **What is legitimately `not_configured`** (`remedy.kind: not_a_defect`, e.g. an empty
  `cases_root`) is an ordinary line in the first part. No third bucket: everything outside
  "here is what to do" reads as "all is well", and that is true.
- **An unreachable host is reported once, above the capabilities it explains**, which say "not
  verified" and nothing about credentials.
- **Next action is drawn only from what is genuinely addressed to the person.** With no
  `owner: user` row, the next action is the work itself, not "go sort out the diagnostics".

The complete repository inventory follows this block and is exempt from the line limit.

## Never report a green it cannot back

Its green lines are worth something only while they are backed: readiness once reported
`ticket_adapter: ok - reachable per config` for a CLI that was not installed, the doctor
repeated it, and the first story halted in S0 on a missing executable.

- **A line is as good as its evidence.** Print what the script printed and never upgrade a
  status while summarizing; a row settled by a probe in step 2b is backed by its receipt.
- **Silence is not a pass.** A section with nothing to show says so ("no stories yet").
- **The verdict line is not an opinion.** It comes from the table above; `/qa-factory:qa-story`
  is row 9 only. Diagnostic API gaps and an unused case library stay visible, blocking nothing.

## What this skill never does

- Never asks a clarifying question to produce a **fact**: facts come from a script or a git/
  file check. Its questions are decisions - the archive offer, `repair.md`'s and the price table's - plus the
  sample ticket in step 2b when no story supplies one.
- Never sets `archived` by its own judgement: only `archive_task.py` on a person's word.
- Never writes a config, a strategy file or anything under `artifacts/` - that is
  `qa-onboarding` and `qa-story`. A read-only probe is not writing; its receipts live in `state/`.
- Never fixes an audit finding itself: names it, names its owner, moves on. Its only repairs
  are `controller.py --operation recover` and, on their word, `release` (`phases/repair.md`).
- Never debugs the factory. Evidence missing after one `--prepare`/pair/`--check` is one line
  - `unknown / owner: factory`, the fact, one recommendation - never a grep of the plugin.
# Evidence capability checks

Inspect configured selectors, reporters and manual-evidence artifact paths read-only. Report a
missing selected capability as a scoped blocker.
