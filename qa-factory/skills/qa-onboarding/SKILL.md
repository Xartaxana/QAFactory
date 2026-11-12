---
name: qa-onboarding
description: >-
  Onboard QA Factory into this repository — discovers the test setup, the application and
  test repositories, environments, conventions and adapters by reading real files, then
  interviews the team only for the gaps left, in batches of at most four questions, and
  generates the project's test strategy and profile only after an explicit "yes" at a
  summary gate. Trigger phrases: "onboard this repository for QA", "set up qa-factory",
  "qa onboarding", "install the factory", "/qa-factory:qa-onboarding". Run once per
  project, and again after a major change to tests, environments, profiles or conventions.
metadata:
  author: Xartaxana
  version: "0.10.0"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Write
  - Edit
---

# QA Factory onboarding

At entry run `"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" activity_capture.py --action start --type onboarding`.
It finds its own session; pass `--session` only with an id a person gives you, never a placeholder. A CLI invocation creates a persisted invocation ID; never substitute a placeholder. Repeated starts of the active workflow reuse it across turns. Keep the activity open during questions, approval gates and interrupted continuations. Immediately before the final completed response run the same command with `--action end --type onboarding --after-response`; the final capture closes it after response usage is recorded. For a nested workflow returning to its caller without a terminal response, end without `--after-response`. Before onboarding approval, boundaries stay in the host-local spool. Missing identity is reported and usage remains unclassified; never infer activities from prompt prose.

One-time setup (repeatable after a major change) that teaches QA Factory this repository:
what tests exist, where application code and test code live, how to reach environments and
credentials, and where bugs and cases should be written. Nothing beyond reading the
repository happens before phase 3's explicit "yes" — no project files, no commits, no external
calls. The one exception is the run's own notes in `qa-factory/state/onboarding/`: git ignores
that folder from its first file, and every phase writes what it found and what the person
answered there as it goes.

## Invariants

- **Scope is announced, not asked.** QA Factory v0 covers functional testing only. State
  this once at preflight; there is no question "what should we test" because there is no
  choice to make yet.
- **Discovery before questions.** Read real files first (phase 1, no questions asked
  there); interview only the gaps discovery left open (phase 2). A gap is a fact discovery
  could not resolve — including one it found *nothing* about. Silence is not an answer: a
  required fact that no file names is asked outright, never skipped for lack of a guess to
  confirm and never filled with a default.
- **A deferral requires a question.** `[DEFERRED: …]` means the team was asked and the
  answer did not come. A topic never put to them produces no marker and no backlog row: if
  the factory needs it, not asking is a defect of the interview, not a debt to record.
- **No project file is changed before "yes".** Phase 3's summary gate is the only point at which
  a file under `qa-factory/` other than the run's own notes is created. "edit" triggers exactly
  one more round of the summary, never a loop of partial writes.
- **Profiles are open contours.** Describe each execution contour from discovered facts and
  adapter contracts; do not force projects into a fixed web/API/mobile preset. Unknown required
  capabilities remain unsupported or unknown, never inferred from a framework name.
- **Dependencies are activated on demand.** Discovery may catalogue external tools, but it never
  installs them. Phase 3 names the exact version/source/owner and installation action only for
  selected profiles; phase 4 performs only an installation explicitly covered by the approval.
- **Installing is migrating, by one path.** A fresh install is the same plan over an empty project;
  a reinstall ends with the tree a fresh install writes. What the old installation holds is taken in
  the new shape; what only an old version wrote is listed at phase 3 under the same single "yes" and
  removed after it. Human-authored values and unknown adapter extension keys are preserved; conflicts
  between discovery and existing values are shown; only approved fields change. Everything after the
  "yes" goes through `scripts/onboard_apply.py`: config, `.gitignore`, rebuild, removal, install record.
- **Batches of at most four questions.** Never a wall of every open topic at once, and never
  one question per message either — group related gaps together.
- **English only.** Every file, question, and message this skill writes is in English,
  regardless of the language of the repository, its comments, or the conversation.
- **No cadences, no metrics menu, no non-functional-testing questions.** Out of scope for
  v0 in full: do not ask about them, do not propose them, do not leave a placeholder asking
  the user to fill them in later.

## Phases

Read the phase file **on entering** that phase — the table below is a map of what happens,
not a substitute for the instructions inside the file itself. Edits to behavior go in the
phase file; this file only tracks the sequence.

| # | Phase | File | What happens |
|---|---|---|---|
| 0 | Preflight | `${CLAUDE_SKILL_DIR}/phases/p0-preflight.md` | Plugin/Python liveness, git-repository check, working-tree note, the scope announcement, the version line when the plugin, marketplace and project records disagree, the install check (a config, an install record or a recognised trace), and a re-onboarding-vs-stop offer when `qa-factory/config.json` already exists |
| 1 | Discovery | `${CLAUDE_SKILL_DIR}/phases/p1-discovery.md` | Read-only in the project, notes in `qa-factory/state/onboarding/`: how the stand is reached (`project_inventory.py --access`: the login call sites, their key NAMES, and the keys the code reads that no env file holds); framework and layers, run-command templates, CI, declared and inferred conventions, git-history conventions, existing cases/TMS, the application repo vs the test repo, candidate environments |
| 2 | Interview | `${CLAUDE_SKILL_DIR}/phases/p2-interview.md` | Read-only in the project, notes in `qa-factory/state/onboarding/`. Batches of at most four questions, only on gaps discovery left open: repos, environments and credentials, test data, risk areas and the impact-class map, git conventions and pre-commit commands, the inferred conventions, ticket/TMS adapters, external-writes channels, DoD, product basics. Required topics (repos, environments, adapters, external writes) are asked when discovery could not find them — never skipped, never deferred unasked. Topic 2 is its own batch and adds two questions by name: which access scheme is the one, and who needs each key the env file does not hold. |
| 2b | Second-pass discovery | `${CLAUDE_SKILL_DIR}/phases/p2b-rediscovery.md` | Read-only in the project, notes in `qa-factory/state/onboarding/`, no questions: re-reads the rows phase 1 could not reach — application stack, architecture and data, component inventory, environments — over the repositories and locations the interview named. Skipped in one line when the interview named nothing new |
| 3 | Summary gate | `${CLAUDE_SKILL_DIR}/phases/p3-summary-gate.md` | One-screen summary (found / answered / to write / what a reinstall deletes, sets aside and keeps / deferred) and the single question "write these files? yes / edit"; no project file is written until "yes" |
| 4 | Generate | `${CLAUDE_SKILL_DIR}/phases/p4-generate.md` | Applies the approved summary through `onboard_apply.py` in two halves (config, template copies and `.gitignore`; then rebuild, removal and install record), writes the role's strategy documents between them, prepares only authorized dependencies, and reports the digest; config approval alone does not authorize commit/push The environment block is written only from keys the env file holds and proved by one real login (`access.login_probe`), never by prose in `verified`. The first apply also proves each selected profile's test report (`onboarding_probe.py`); a proven cure is asked as one "Do it?" per profile, shown only after the launch check, applied only on a yes. |

Read them **in order**. Do not open phase 2 before phase 1 has actually inspected files (a
question discovery could have answered is a defect, not a courtesy), do not reach phase 3
while a source the interview just named is still unread (that is phase 2b's job — an
unreadable source and an empty one are different facts), and do not enter phase 4 before
phase 3 has recorded an explicit "yes" in the transcript.

Use `scripts/project_inventory.py --root <project>` as the single repository view in
discovery and the approval summary. Use `python "${CLAUDE_PLUGIN_ROOT}/scripts/config_contract.py" --root <project> --migration-plan` for
an existing config. A proposal is read-only; apply it only after the summary approval and
with that recorded approval reference, through `scripts/onboard_apply.py` (phases 3 and 4 give the
commands). Never run a command found in a proposal.

Discovery precedes questions. Reuse verified project values and executable defaults, then
ask only unresolved relevant facts. Empty placeholders are not verified. A declined,
deferred or unanswered question remains pending and is written once through
`scripts/project_decisions.py`; elapsed time is never an answer. Requirements sources,
repository locations, tracker, case storage and publication destinations must be found,
explicitly not applicable with evidence, or asked.

For each pre-existing strategy document ask once whether to update that exact file or
create a separate factory document. Record the selected file in `strategy_documents` with
provenance, `editable`, `decision_ref` and source references. Separate documents live under
`qa-factory/strategy/` and cite the original. Permission applies to the named file only.

## Resuming

After a compaction or in a new session, run `onboarding_notes.py --root . status` and continue
from what it reports: a topic it lists as answered is never asked again, and the notes win over memory.

## Arguments

None. Run it from the project's folder: the repository root, or the subfolder of a monorepo that holds the project:

```
/qa-factory:qa-onboarding
```

## Halts (not questions)

Preflight can stop the whole run before phase 1 ever starts: the plugin or Python are not
answering, or the current directory is not a git repository. These are reported as
concrete blockers with the failing command's output, not folded into the interview.

## Digest

On finishing phase 4 — or stopping early because phase 4 found no test framework — report:

- **Files written** — the list under `qa-factory/`, with the commit hash from phase 4.
- **Deferred items** — every `[DEFERRED: …]` marker written, each paired with its
  `factory-backlog.md` row id.
- **Next action** — `/qa-factory:qa-doctor` to confirm the install end to end, then
  `/qa-factory:qa-story <ticket>` to run the first story.

If phase 0 stopped on a hook/Python failure, or the working directory is not a git
repository, the digest says exactly that instead, with the one command to run before
retrying. If phase 4 stopped because no test framework was found, the digest names
`qa-bootstrap-framework` as planned for v1 and lists only `config.json` and
`project-profile.md` as written.
