# Text shown to a person

Every question the factory puts in front of a human being obeys this file: the gate questions,
the boundary questions of the driver (`s1_review`, `s1_gap`, `gate_A`, `gate_B`, `halt`, `retro`,
`conductor`), the halt a role writes, the "Factory defects" section of the test report, and the one
closing question of S9. One file, because the rules were kept in the heads of whoever wrote each
question, and so they held at one boundary and failed at the next.

The machine channels are NOT governed by this file and never reach a person: the role → conductor
forms (`work/handoffs/*.help.yaml`), the handover forms, the events log, the refusal a script prints
to a role. Their wording is for a reader who has the plugin in context. A person does not.

## Who the reader is

Someone who knows the product and the story, and knows nothing about the factory's insides. They
have not read the plugin, do not know what a handover form is, cannot look up what `TS-14` means,
and will not open a script to find out what it wanted. They are being asked because a decision is
theirs — not to debug us.

## What the text must carry

1. **What the factory decided by itself** — so the person can see the work is done and only the
   decision is missing.
2. **Why the answer cannot be derived** — the specific thing that is missing or contradictory,
   named in the story's own words.
3. **What exactly is needed from the person** — one question, not a list of concerns. N items of
   one kind are one question: one answer for all, the exceptions named, or stop.
4. **A closed set of answers** where one exists ("approve / name the fix / it is out of scope"),
   and for something unreachable that the person can open, the three standing answers: *I will fix it*,
   *you fix it*, *accept it as it is*; what the factory itself established it cannot reach is a gap in
   the report, not a question. Code asks only closed questions and reads back only the offered tokens; any other
   answer is the conductor's to read.
5. **How to answer**, at the bottom, in its own block. This is the only place a script name, a
   flag, or a path may appear, because here it is an instruction to type, not jargon. One narrow exception: a
   file of the person's own project that they keep and commit (the record of how each stand's build is read,
   `qa-factory/records/stand-identity.json`) may be named in the body, because the question asks them to look after it;
   a path inside the plugin never may.
6. **Price and consequences, per option.** Every option of the closed set is followed by three lines: `the factory:` what it costs the factory (nothing runs / a record only / a factory command runs, no agent works / one more working session of the role, named in words / the stages, named in words, run again); `you:` what it costs the person (nothing more / this answer / work of theirs outside the factory, named; checks left with them); `the story:` what stays unverified, in the story's words, what goes into the report as an open item, and what it does to delivery, said as one of: ready, not ready, ready after your checks, waits, unchanged, not known. A cost nobody measured is said as a class, never as a number; an unknown is said as not known. A question has at least two options and no two options make the same move; one possible move is not a question but a report.

An option is called recommended only after you named who carries it out: the function or field of the factory that reads what the option changes. None found: the option is not recommended, and if it stays, the text says it is unchecked, and why. An option that changes a config key: look for that key's reader first; no reader, no option, and the text says why.

## What the text may never carry

- a form or schema field name: `person.review_recorded`, `header.verdict: not filled`,
  `inputs_read[0].requirements`, `reviewed=false`
- a script name or refusal id outside the "how to answer" block: `planning_contract.py`,
  `waiver.py --task ... --stage S3 --block`, `FB-27`, `PT-plan-rewrite`, `exit 1`
- a path inside the plugin, or a dispatch id (`S3-qa-test-strategist-1`) anywhere in the text —
  a person is not asked about a dispatch, they are asked about the story
- the machine shapes the check finds: a raw HTML page, a stack trace, a slash command
  (`/login`), a ledger state or field name inside code quotes, and a row id (`TS-14`, `OBL-7`,
  `SURF-`, `SRC-`, `REQ-`, `TC-`) not explained where it first appears (`TS-14 (the import size
  limit)`, `the import size limit (TS-14)`)
- a config key path of the factory's own config (`profiles[api].commands.one_test`, a dotted root of
  `config-keys.json`) or a `/qa-factory:` command: it belongs in the how-to-answer block, never in the body
  (`human_text.py` checks it; the data row is `references/human-text.json`)
- the factory's own records: a JSON, YAML, JSONL or text file, the ledger, the manifest, an attempt id (`a9`,
  `ti_`). A person is named a markdown document or a screenshot, anything else in words; the how-to-answer block
  (rule 5) and a project file the question asks them to edit are the exceptions (data row `technical_file_named`, a report only)
- an internal stage name without saying what it is ("S3" alone; "the test plan (S3)" is fine)
- the raw text of a refusal, relayed as-is. A refusal is written for the role that called the
  script. Shown to a person it is our failure to translate, not their failure to read.

## The measured reason this file exists

On TP1-13797 the scout's boundary question reached the person as the line
`cannot fill person.review_recorded` — a field of a form the person has never seen, about a
decision (are these four merge requests the right sources?) that they could have answered in a
sentence. At S3 the conductor's question to the person was the strategist's refusal, verbatim:
two detector lines about `TS-14`, four `not filled` form paths, and `waiver.py --block`. Both
questions were answerable; both spent the person's attention on our vocabulary.

## One that obeyed them

TP1-13797, 27.09 10:15, the conductor to the person — quoted because a rule is easier to
follow from an example than from a list, and because this one was measured in the same run as
the two failures above:

> The code review for the two webhook tests in this window (the oversized-payload test and the
> event-type-filter test) is finished and both passed — the reviewer found no real problems,
> just one optional style note that needs no action. The only thing missing is our own
> paperwork: the tool that stamps a review as officially accepted isn't yet able to check a
> couple of technical details on these two tests (whether enough hashed proof is attached, and
> whether the receipt is shaped the way we'll eventually require) — that's a gap in our tooling,
> not a flaw in the tests, and deciding exactly what proof we'll require is a separate decision
> still to be made. So: do you want to (a) accept this window now, on the strength of the review
> that's already done, (b) hold it here and wait until that proof-requirement decision is made,
> or (c) send it back for rework?

Every part is there: what the factory finished, what is missing, **whose gap it is**, and three
closed answers. No field name, no script, no exit code; the tests are named by what they check.

## One with price and consequences

The stand question when the answer was not one of the offered words (the stand remedy is
authorized for the story). Every option carries its three lines (rule 6):

> The tests of this story need a stand, and none is confirmed for it yet. Your answer, "the
> staging one should be up by now, please try it", is not one of the answers the question
> offered, so nothing was recorded and nothing has run. The factory may start the stand itself,
> because you allowed that for this story. Which of these should happen?
> (a) `prepare the stand` — the factory starts the stand with the command your project names for it and checks that it answers.
> the factory: a factory command runs; no agent works.
> you: nothing more.
> the story: the tests wait until the stand answers; delivery waits until then.
> (b) `retry` — you start the stand yourself and tell me to look again.
> the factory: nothing runs now.
> you: work of yours outside the factory: starting the stand.
> the story: delivery waits for you.
> (c) `stop` — stop the story here.
> the factory: nothing runs.
> you: nothing more.
> the story: delivery is not ready while this stands.

## One at a gate

A gate answer that was not the approval word: nothing is recorded as approved, and the factory
offers the moves with their prices. Gate A reads the same, with the stages before the tests.

> The tests for this story are written, run and reviewed, and the report is ready for the delivery check (gate B). Your answer was not an approval: you wrote "the automation needs changes — the export test checks only the status code". The factory cannot tell from those words alone which tests to change or how, so nothing is recorded as approved and nothing has gone out. Which of these should happen?
> (a) `rework` — the test writer changes the tests you named, with your words as its instruction; then the tests are reviewed again, run again, the report is rebuilt, and you see this gate again.
> the factory: the automation stage (S5) and everything after it run again.
> you: this answer, and one more look at this gate.
> the story: nothing stays unverified by this choice; delivery waits until the gate is shown again.
> (b) `approve` — deliver as it is now.
> the factory: a record only; no agent works.
> you: nothing more.
> the story: what the export test should prove stays unproven, and your words are kept with the approval; the delivery verdict stays as the report has it.
> (c) `retry` — you change the tests yourself, then answer this gate again.
> the factory: nothing runs now; the tests do not run again on their own — say so in your answer and the factory offers it.
> you: the change itself, outside the factory.
> the story: delivery waits for you.

## What holds these rules

`human_text.py` reads a text and names the rules it breaks; the shapes live beside it in
`human-text.json`, so a new one is added there, not in code. It checks the SHAPE of what we wrote
and never anybody's meaning — what a person's answer means stays theirs and the conductor's to
read. A case id whose first mention is a link to its own case file on the same line counts as
explained, because the person opens the file and reads what the case is (`link_explains` in
`human-text.json`); a link on another line explains nothing.

For a question that offers tokens, `human_text.price_problems` checks item 6: every offered token's option
line is followed by the three price labels (`price_lines` in `human-text.json`), in order.

The driver runs it on every question before showing it (`story_run.judge_own_question`) and writes
the result to `state/driver-questions.jsonl`: the kind, the size, and the rules broken. A text that
breaks one is still shown — our defect is not the person's problem — and the share of questions
that break our own rules is a number the next run can read instead of an impression. The
report's "Factory defects" section is checked by the same file when the report is written.

## The gap this file closed, and what it cost

The driver used to paste the refusal under the question, and on TP1-13797 run 5 that put
detector lines, form field paths and an exit code on the person's screen twelve times out of
twelve. Sixteen more conductor sessions answered with no question at all.

The factory's own words now go to `state/driver-question-details.md`, named in the answer block;
the question stays a question. When nobody wrote one, the driver writes its own from what it knows
and records the empty answer as our defect (`log_append --event defect_found`).
