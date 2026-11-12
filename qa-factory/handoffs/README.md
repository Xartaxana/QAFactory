# Handoff contracts

One file per handoff between two roles. The file is both the **contract** (what must be
passed, in which words) and the **form** the sending role fills in. The receiving role reads
that filled file and needs to hunt for nothing else.

A story has ten stages but **twenty-one handovers**: ten between stages, seven inside a stage
(author ↔ critic at S4 and S5, the repair round at S7, at S5 the plan and its review before
the windows, and at S8 the bug reporter's own filing after gate B), two that are a person's decision, one
that skips a stage entirely (manual cases go from S4 straight to S6), and one that leaves the
story altogether (what S9 hands to the project). Every one of them is a place where the next
role can start without something it needs, so every one of them has a file.

## Why

Three stages of TP1-13797 stopped for reasons that were never decisions:

- a role wrote `unverified`, `inconclusive`, `filed` — words its own charter and the artifact
  contracts use — and the digest form had never heard of them;
- the critic's findings file was complete on disk and the acceptance refused the window,
  because no stage declares that file among its outputs and the orchestrator used to pass it
  by hand;
- the controller wanted `unresolved` + `reason` in a completion, and the handoff form had no
  field for it.

Each was the same defect: **the contract between two roles lived in three places and in
nobody's hands.** These files are that contract, in one place, machine-checked.

And one failure had no refusal at all, which is the worse kind: the tester never opened the
rest of `impl-diff.txt`, wrote 14 requirements where a full read gives 21, and every later
stage was correct about the wrong 14. That is why a contract states the **size** of what it
hands over and the receiver's own file answers `21 of 21`.

## The files

| File | Hands over |
|---|---|
| `index.yaml` | which contract governs which handover; what `handoff_init.py` resolves |
| `vocabulary.yaml` | every closed list the factory uses, and which roles may write each word |
| `s0-setup-to-scout.yaml` | the ticket, the flags as the person typed them, the repos, the stand, the tools |
| `s1-scout-to-tester.yaml` | the ground: sources with decisions, the diff **counted**, the accepted gaps |
| `s2-tester-to-strategist.yaml` | the register, the contradiction matrix, the size, and how much of the diff was read (`<read> of <handed>`) |
| `s3-strategist-to-designer.yaml` | the grounding table's account of every diff hunk, the plan rows with dispositions, obligation ids and the manual evidence policy |
| `s4-designer-to-case-critic.yaml` | the pinned cases and the critic's scope, named rather than guessed |
| `s4-case-critic-to-designer.yaml` | the review: verdict, roll-call, findings with `expected`, `check` and a replacement |
| `s4-designer-to-runner.yaml` | manual-agent cases: steps, preconditions, evidence policy, what makes them inconclusive |
| `gate-a-to-automator.yaml` | the person's approval: scope, waivers, handed profiles, stand-gap answers |
| `s5-automator-to-critic.yaml` | one S5 window: tests, manifest, run witness, probes, case versions |
| `s5-critic-to-automator.yaml` | the review of that window, and what stayed unproven |
| `s5-automator-plan-to-critic.yaml` | the S5 plan for every case, before any window (a dispatch of purpose `s5_plan`): the cases it covers and the plan file |
| `s5-critic-plan-to-automator.yaml` | the review of that plan: the verdict, and a remark per place the plan must change or a window must answer |
| `s5-automator-to-runner.yaml` | the instances with their fingerprints, and what is fresh, stale or never run |
| `s6-runner-to-analyst.yaml` | the run: rows with evidence, manual observations, env blocks with remedies |
| `s7-analyst-to-automator.yaml` | the three repairable verdicts, each with evidence, `expected` and `check` |
| `s7-automator-to-analyst.yaml` | the repair round, and the proof the Then lines did not move |
| `s7-analyst-to-scribe.yaml` | the triage and the bug drafts, each resting on a verdict |
| `s8-scribe-to-gate-b.yaml` | what the person is shown, what they are not, and what they are asked |
| `gate-b-to-delivery.yaml` | the decision: drafts by ref, MR, external writes, `retro_mode` |
| `s8-bug-reporter-to-scribe.yaml` | what the bug reporter filed after gate B: bug, draft, case, requirements; the drafts not filed and the quarantined tests; never whether the tracker has it |
| `s9-retro-to-project.yaml` | what outlives the story: obligations with triggers, traps with one owner |
| `role-to-conductor.yaml` | the way out when a role cannot fill one of the above |

## The shape they share

A role that has filled one has filled them all:

- `inputs` — what the **receiving** role must read, each with `required`;
- `inputs_read` — what the **sending** role confirms it read of its predecessor, with versions
  and counts; this is what catches the read that never happened;
- `header` — role, stage, window, and a verdict from `vocabulary.header_verdicts`;
- `scope` — one row per item, with a `state` from `vocabulary.row_states` and a reason of at
  most 80 characters (the explanation belongs in the artifact, not in the form);
- `artifacts` — the files the receiver is entitled to, by path;
- `claims` — what the sender asserts, each one checkable by code, so a false claim costs the
  sender a check and not the receiver a turn;
- `expected_of_the_receiver` — what this handoff requires of the next role, in the next role's
  own terms, and it is answered field by field in that role's file;
- `unresolved` — what stays open on purpose, with a reason from `vocabulary.unresolved_reasons`;
- `blocked` — the field that could not be filled, what was tried, and the data the conductor
  needs.

**A review contract carries `findings`, and every finding carries `expected` and `check`.** A
refusal that does not say what the reviewer expects is not a refusal, it is a riddle: the
author guesses, and every guess is a round — S4 and S7 allow two. `expected` is the condition
the author can check its own work against; `check` is how to check it without asking again;
at S4 an exact `replacement` lets code apply the fix with no dispatch at all.

## When the judge is on

With `judge.provider` configured, a value the judge decided is written into the field it
belongs to, and one row per repair is appended to the form's `judged` section — the field, the
value, the role's own `as_written` words, the confidence and the question that decided it
(`index.yaml`, `judged_row`). Three rules hold:

- the judge is called by the **code at the boundary** — `handoff_check`, `story_step`,
  `exit_gate` — never by a model inside a dispatch, and it asks the questions that already
  exist (`form_row_state`, `form_digest_verdict`, `form_unresolved_reason`) rather than new ones;
- a decided answer maps a word into a closed list or supplies a first guess; it never lifts a
  block, passes a gate, authorises a write, or answers a question that is the person's;
- the receiving role sees every judged field and may refuse it as it would any other claim.

Wiring it any other way is what made the judged run of TP1-13797 more expensive than the
unjudged one: the judge itself cost $0.011 for 477 answers, while handing those answers around
through an orchestrator model cost $18.78.

## How a role uses one

1. `story_step start` writes the empty instance beside the brief:
   `work/handoffs/<dispatch>.yaml`, every value `<fill>`, every artifact path already named.
2. The role does its work and fills the file. Its message in the chat stays one line: the
   header and the path to this file.
3. `handoff_check.py --file work/handoffs/<dispatch>.yaml --fix` first writes in everything
   the artifacts already answer and records each one under `derived` (the field and where it
   came from), then answers with the fields that are missing or wrong, **the allowed values
   for this role**, and the command that fixes each. A role is never woken to copy a value
   that is already on disk, and the receiving role can see which values are code's.
4. `story_step finish` runs the check itself (with `--fix`), refuses a form the role never
   filled or left incomplete, and records the file as evidence — so a receipt nobody wrote
   cannot close a stage. **The form is required by default.** A project that does not want
   the form sets `handoffs.required: false` in `qa-factory/config.json`; for one dispatch a
   person's word passes it — `finish --ignore-handoff`, recorded like any other block by
   whoever records their words (the conductor with their words in the prompt, or the person).
5. The next role's brief names this file under "read first"; its own handoff carries
   `inputs_read`, so a review of a stale version is caught by code.

## When a role cannot fill it

It fills `blocked` — the field, what it tried, what refused it, and the paths to the data —
and runs `handoff_help.py --file <its file>`. The conductor gets the file, the contract, the
refusal and the vocabulary, and answers in the second half of `role-to-conductor.yaml`: fill
it, repair the work, ask the person, or change the contract. **A role never takes a filling
problem to the person.**

The most useful line of that form is `candidate` — the word the role *would* write. A role
reaching for `inconclusive` is not making a mistake; it is telling the factory its vocabulary
has a hole. Four of those cost a round each before anyone noticed.

## Rules for changing these files

- A word a role may write exists in `vocabulary.yaml` first; the charters and the artifact
  contracts quote it and never invent their own.
- Adding a required field means adding it to the contract, to `handoff_init`'s skeleton and to
  the check's refusal text in the same change.
- A contract may not ask for anything the factory does not read: every field is either checked
  by code or read by the receiving role, and a test asserts it.
- A new handover gets a row in `index.yaml` in the same change as its file; nothing resolves a
  contract by file name.
- A handover that serves one kind of dispatch of a stage that has another usual contract (S5's plan
  dispatch) names it in the row's `purpose`; `handoff.contract_of` returns such a row only for a lookup
  that asks for that purpose, and never to a lookup that names none.
