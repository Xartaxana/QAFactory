---
name: qa-story
description: >-
  Run the QA Factory story pipeline S0-S9 for one ticket — preflight, context and
  grounding, requirements, plan, cases, automation, run, triage, results, retro —
  dispatching the twelve qa-* roles, recording every stage in pipeline.json, and stopping
  for the human at exactly two gates: reviewed plan and cases (gate A), then results (gate B). Trigger
  phrases: "qa this ticket", "run qa-story", "test story ID", "qa TICKET-ID",
  "/qa-factory:qa-story". Requires a project already onboarded by qa-onboarding.
metadata:
  author: Xartaxana
  version: "0.10.8"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Write
  - Edit
  - Agent
---

# qa-story

At entry run `"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" activity_capture.py --action start --type story --task "<ticket>"`.
It finds its own session; pass `--session` only with an id a person gives you, never a placeholder. Right before the final response run it with `--action end --type story --task "<ticket>" --after-response` (a nested workflow returning to its caller ends without it). Missing identity leaves usage unclassified; never infer activities from prose.

**You own the process, not the methodology.** You dispatch roles, call scripts, record
state, and ask the human only at the two gates and a halt. You never write a test case,
a test, a verdict, a triage class, a bug or a brief yourself — a role does, or a script
does. If you find yourself authoring content, you took a role's job and nobody reviews it.

On Codex, use the native hook manifest `hooks/codex.json`. CLI dispatch uses exported `.codex/agents/*.toml` profiles and the canonical `agent_type` (`qa-scout`); desktop dispatch uses `task_name=qa_scout__<story_slug>`, which the native adapter resolves to `qa-scout`; `<story_slug>` = ticket lower-cased, `-`→`_`, optional `_<suffix>`; the desktop `message` is opaque, so the guard reads the story from `task_name`. Keep the native agent ID for repairs; model and effort inherit the host. Stories run via the driver: story_run.py --task <T> --host codex (design/driver.md). `readiness.py --write` tells observed receipts from an unverified install.

## Arguments

```
qa-story <ticket>
  [--mr <url|id>] the merge request to ground on
  [--branch <name>] a branch to diff against the default branch
  [--commit <sha>] a commit to diff
  [--env <name>] the stand this story is tested on (a config.environments name)
  [--ungrounded] requirements only, on the code the stand runs now
  [--side <name>=<reality>] a part of the product with its reality word (`real`, `substituted`, `absent`); `--side product=absent` is "not built yet"
  [--reference <side>=<stand>] the stand that stands in for a side
  [--ticket-file <path>] this file is the requirement; REST is read beside it if set up
```

Parse them before S0; only S0 and S1 read them. `--mr`, `--branch` and `--commit` are mutually exclusive — more than one is a halt. When `config.adapters.ticket.name` is `file` and no
`--ticket-file` is given, the ticket is read from `config.adapters.ticket.path/<ticket>.md`.
A tracker is read by the S1 role itself through `adapters.ticket.direct_api`; a route only
this session holds (`mcp_tool`/`agent`/`skill`) is a write channel, and S0 §5 says so before S1.

## Invariants

- **One line in, one line out.** A role returns a header, one line per item in its scope,
  and a path; the exit gate refuses any other shape. You read the digest and the paths, never
  an artifact's body; a gate's content comes from the artifact it names, read once.
- **State after every stage.** One `stage_done.py` call writes `pipeline.json` and the
  journal event together, before the next dispatch — never by hand, never two calls.
- **The stage guard runs itself** — inside `controller.py --operation dispatch`, on every
  `Agent` dispatch and on git/MR/TMS commands. A denial is a halt: report it verbatim with
  the `waiver.py` command it ends with; never reshape a dispatch or route around the guard.
- **Validators run themselves.** `validate_artifacts.py` fires PostToolUse on Write/Edit.
  A rejected artifact returns to its writer:
  `controller.py --operation rework --stage S<n> --role <role> --cases <ids> --reason "<why>" --brief`
  then `story_step.py materialize`, and launch its card by the stage's `rework_mode` (`fresh`: NEW agent,
  else `SendMessage`). A hand repair leaves it unreviewed; the guard refuses it.
- **No questions between gates.** Gate A after S4, gate B after S8; a gate-A question shows
  its quotes and readings, never a one-liner — one without readings is the factory's to
  rewrite (`qa-requirements-tester`), not the person's to answer. Everything else is
  your own decision, recorded in `pipeline.json`, or a **halt** naming what is needed. The one
  planned stop besides them is the S1 source review, asked with the stand (`phases/s1.md`).
- **Settle it yourself first; the person is asked only what a person decides.** Before any question read
  what the code left (the refusal, its record, logs, notes) and resolve what you can; what the code recorded is evidence, never the
  question's text. Ask only a class of `references/person-owned.json` and record their word with `--why-person <id>`. An
  inconsistency in the factory's own
  state is never handed over as something "to fix": run `controller.py --operation recover`;
  if that does not settle it, say one line — `owner: factory`, the fact — record it with
  `project_decisions.py add-finding --scope local-urgent|local-calibration|upstream-candidate`,
  and go on unless the story truly cannot. Never offer a plugin edit. A person's request to change the factory is a
  finding whatever else you do (`--words-file <f>`, key `change-request:<T>`), except an S9 answer the retro analyst
  records. Told to wait for a job nobody started, run
  `recover`. An orchestrator share over `retro.orchestrator_share_max` (0.35) and a stage
  finished before it started are findings about the factory, not questions.
  **A gate is the last stop before its next stage:**
  rehearse it (`gate_preflight.py --task <T> --gate A|B`), repair what is the factory's, ask
  the rest in the gate message, record with `--operation gate-decision`. After the answer
  nothing is asked or refused that could have been computed before it. Gate A also runs one
  existing test per profile to prove its report (none written = stand-gap card `RP-<profile>`,
  never an S5 surprise) and asks one three-answer question when no `profiles[].commands.one_test`
  runs the story's automate cases: onboard, name the command, or run them yourself.
  A role reporting a tool as unavailable is a halt naming the role, the tool and the remedy.
  Never reopen an accepted stage: rework goes by
  `--operation rework` or `revise_plan`. S5/S6 scope comes only from
  `--operation stage-scope`. At S4 you pin the cases (`case_versions.py --all`, `--verify`);
  a critic's verdict comes from its roll-call; a code review is accepted only with its
  findings file and `review_receipt_ref` — never retype findings. An obligation id is the
  plan's: `manifest_put.py` refuses any other, `s5_precheck.py` names an unbound one;
  `waiver.py --stage S5 --block "obligation-id"` passes.
- **Follow `next`.** `resolve_return` (accept, block, or rework), `relaunch` (a ready
  request, never rebuilt by hand; a retry names `retry_reason`/`retry_words`), `launch` / `wait_start`
  (`references/codex-host.md`), `wait_existing_job` with `liveness: unknown` (nothing is proven; never
  cancel), stuck waits end by the person's word: `--operation release --dispatch <id> --words-file`;
  `closed` (gate B decided, S8 done; reopening is a person's word via `--operation rework --reason`,
  never a silent `running`).
- **The person hears one sentence, or a question.** What a role said to another role, a
  guard's refusal you passed, a state repair — not theirs to read. Print
  `stage_status.py --task <T> --event <critic_returned|author_repair|role_halt|window_done>`,
  nothing more; a refusal repeating on a different call is the factory's: one line,
  `/qa-factory:qa-doctor`, stop.
- **A person's word passes any block.** A check stops a *silent* pass, never an informed
  one. When the person answers a halt or gate block, record their words —
  `ticket_adapter.py accept-gap` for a source, `waiver.py --gate` for a requirement,
  `waiver.py --task <T> --stage S<n> --block "<a refusal line, whole or in part>" --words-file <f>`
  for anything else, `--block "wait_existing_job"` to release a dispatch nobody is doing; read
  what it prints: `block lifted`, `not verified` (its own door too: run the step again) or a
  refusal listing the standing lines (record again with one, or `--remark`). Only you record it,
  only what they named; gates A and B repeat every passed block.
- **Stage card on entry.** Run `story_step.py card --stage S<n>` right before stage `n`; read a phase
  section only where the card points. A config key: `config_view.py --get <key>`, never config.json whole.
- **Your window changes at a stage boundary, never one step before a gate.** Close the stage
  with `stage_done.py`: it prints the budgets and, when the next stage will not fit, asks
  for `/compact` or a fresh `/qa-factory:qa-story <TICKET>`. Gate A is asked in the window
  that closed S4, gate B in the one that closed S8, over `gate_brief.py --task <TICKET>
  --gate A|B`. Read the gate-decision answer whole: follow `next_action` in this window;
  only its `window` line changes it. A window that only recovered or recorded
  has not done its stage: go on, no second restart.
- **English only** in every file, message, question and dispatch.
- **Grep/Read over Bash** for reading; `Bash` executes.
- **Never modify application code** — except the one file a recorded `apply` on a stand-gap
  card names, once (`phases/s5.md`); P-00 holds everywhere else. The factory files bugs.
- **A stand gap is a card, not a reason code.** `stand_gaps.py --task <T> --gate A|B`
  (embedded by `gate_brief.py`): the fix by name, four answers — apply / theirs / handed /
  accept. `blocked_by_env`/`env_blocked` rows need `remedy` (names only, never a value); a
  fixture the case never asks for is a test defect, not a stand gap.
- **Gate B question lines** `<case id>: intended|bug|open` are carried out by you: `intended`
  `exploratory_findings.py correct --by person --oracle-status person_confirmed`; `bug` an S7 `qa-failure-analyst` `--operation rework --cause question_answer --words-file`,
  led by the finding's case, statement and before/now; `open` `question_register.py --defer`. Other words are asked in
  words; after the approval word only these lines are read.
- **The stand answers in three lines** — `liveness`, `login`, `keys`, each its own verdict.
  Layer 1 is only: no answer, login refused, or a login key missing; any other missing key
  names who needs it and blocks nothing.
- **Runs go through `run_suite.py`**, never a runner directly — you or any role. A typed
  request is written in one call and run in the next; flags that launch nothing
  (`--reparse-block`, `--recover`, `--detail`) pass while a dispatch is open.

## Stages

| # | Stage | Phase file | Roles | Gate |
|---|---|---|---|---|
| S0 | Start and preflight | `phases/s0.md` | none (orchestrator + code) | — |
| S1 | Context and grounding | `phases/s1.md` | `qa-scout` | — |
| S2 | Understanding and size | `phases/s2.md` | `qa-requirements-tester` | halt on `blocked` |
| S3 | Plan | `phases/s3.md` | `qa-test-strategist` | — |
| S4 | Cases | `phases/s4.md` | `qa-case-designer` and `qa-case-critic` (max 2 rounds) | **GATE A** |
| S5 | Automation | `phases/s5.md` | `qa-automator` and `qa-code-critic` (max 2 test rounds) | — |
| S6 | Run | `phases/s6.md` | code (`run_suite.py`) + `qa-runner` | — |
| S7 | Triage | `phases/s7.md` | `qa-failure-analyst` (+ `qa-automator` fixes); a red result with no verdict is the factory's block, never a bug; a draft nobody can reproduce by hand is an observation for gate B | — |
| S8 | Results | `phases/s8.md` | `qa-doc-scribe` then **GATE B** then `qa-bug-reporter` | **GATE B** |
| S9 | Closure and retro | `phases/s9.md` | `qa-retro-analyst` | one optional question |

## Dispatch protocol

`story_step.py start` prints the `Agent` call filled in — use it verbatim. Its shape, and the
fallback when the command cannot run: `subagent_type: "<role>"`, `description: "<role> <stage>
<TICKET>"`, and a prompt of `You are <role>. Ticket: <TICKET>.` + `Artifacts dir:` + the
inputs that role's `## Inputs` table lists **as paths** + `Return your digest line only.`

`start` also writes the role's **handover form** from the contract in `handoffs/` and names it
in that prompt (`handoffs/README.md`). The role fills it; `handoff_check.py --fix` writes in
what code can derive and refuses with the field and the values THAT role may write; `finish`
accepts on a green check and keeps the form as evidence. A field the role cannot fill goes
under `blocked` and to the conductor (`handoff_help.py`) — never to the person.

- Wait for the digest (header `<role> <stage> <scope> · ok|concerns|halt|impossible`).
  - `done` → record and continue.
  - `halt` → find it in `references/halts.md` and stop there.
  - `review` (S1 only) → the source table and the stand question, one message (`phases/s1.md`).
  - No digest, or one with no path → exactly ONE re-dispatch; a second miss is a halt.
- Never dispatch two roles of one stage in one turn unless the phase file says so.

## Recording a stage

`story_step.py finish` records S1–S9. Where it cannot run, **one command** writes
`pipeline.json` and the journal together:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> --stage S<n> \
  --status done|halted [--role <role>] --digest "<the digest line>"
```

`--status running` when you dispatch, `done` or `halted` when the role hands back. A
code-only stage (S0, S7 with nothing to triage) takes no `--role`. **Never edit
`pipeline.json` by hand.**

## The two gates — the protocol both share

- **One message.** Everything the human decides arrives in a single message, in the order
  the phase file fixes — never one message per question or a question after an answer.
- **Code first.** Print the code's gate text whole, then your words.
- **Answers are not approval.** Approval is its own word, asked as its own item.
- **Verbatim in the decision receipt** (`--operation gate-decision`) before any work it
  authorizes begins. Edits mean one re-dispatch of the role that wrote the artifact, then
  the same message — never a third.
- **The factory waits with no deadline.** An answer matching no option is re-asked once only
  if it changes scope, oracle or stand; else `waiver.py --remark` keeps it and gate B lists
  it before the MR.

Gate A's decision items are in `phases/s4.md`, gate B's in `phases/s8.md`.

## Halts

A halt stops the pipeline where it stands: `stage_done.py --status halted` writes `halts[]`
and resolves it when the stage runs again — never by hand. Read what the halt left and settle what is
yours; `references/halts.md` says, per digest or condition, where to read and what is left for the person; "go on without it" is
always an answer. Resume from the same stage.

## Resume

A restart rechecks historical blockers before refusing work (`references/scout-recovery.md`):
a saved failure is not current evidence; prior artifacts and gates stay.

On any start, before anything else:

1. `Read qa-factory/artifacts/<TICKET>/pipeline.json`. Absent → a fresh story, go to S0.
   Present → `migrate_artifacts.py --task-root <T> --if-older`: it migrates by code once;
   never ask the person about it.
2. Recover from it: the environment, the implementation source, every `done` stage, both
   gate decisions, cross-checked against `records/journal.jsonl` (an older project: `state/`). Anything recorded there is
   answered; asking again is a defect.
3. Resume at the first stage that is not `done`, with its card. A `running`
   stage (interrupted session) is reconciled from its durable receipt; resume only the
   remaining work.
4. A stage `done` whose `required_outputs` (`references/stages.json`) are missing on disk is
   not done: set it to `pending` and re-run. Its other `outputs` may legitimately not exist
   (S8's `bugs/`); on a `cases_root` project `case_versions.py --task-root <T> --verify`
   proves S4, an empty `work/test-cases/` does not.

## Orchestrator economy

- Artifacts travel by path. You never read `test-plan.md`, a case, a diff or a run
  report whole; a record or log a refusal names is read to settle it; besides the two gate briefs you open only the references this file names.
- Independent calls go in one turn.
- A controller window marks `rollover_pending` at 40 model requests or 70% reported context
  and hands over only after active dispatches are accepted or checkpointed; costs and repair
  budgets never reset. A cap limits attempts, never scope: what a cap left undone is named
  at the next gate, never dropped.
- After a compaction, re-read this file, the stage card and `pipeline.json`.

## Finish

S9 ends with a summary of at most 10 lines: what was delivered, what stays open, the one
next action.

## Durable dispatch protocol

Before the first role dispatch read `${CLAUDE_PLUGIN_ROOT}/references/controller-api.md` — it
carries the protocol: acceptance and recording order, who closes a stage, how a stopped role
resumes, what an S5 window record is built from. Resolve `next`, never reconstruct progress from chat.
