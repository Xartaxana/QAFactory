# <TICKET-ID> — questions for the requirements owner

Source: the requirements register and contradiction matrix, `qa-factory/artifacts/<TICKET-ID>/requirements-register.md`. Assembled by `qa-requirements-tester` (S2) or `qa-test-strategist` (S3) and delivered as part of gate A — never as a separate round of questions.

**How to use this:** the table below is short wording; details with quotes and code
references are in the numbered items after the table. Answer in the "Answer" column or
directly in the item.

Q1–Q<k> are blockers: until answered, the plan for the affected requirement does not get an
`automate` disposition. The rest are important; each carries a proposed working
interpretation — silence adopts it, but it becomes a decision only after confirmation at
gate A.

## Summary table

| # | Question | Readings | Answer |
|---|---|---|---|
| **Q1** blocker | <one line; references the contradiction-matrix row> | a) …; b) … | |
| Q2 | <one line> | a) …; b) … | |

Addressees: name who each question is for (product owner, developer, QA) next to the
question — the register does not assume one role answers everything.

---

## Details

Every question below is also a record in `requirements-readiness.json`'s `open_questions[]`,
in the shape `references/artifact-contract-json.md` states: `source_says` (what the sources
say, each with where) and at least two `readings` (`reading`, `from`, `if_chosen`). One
reading is a decision, not a question; the person's own wording is always open to them and is
never written down as a third reading.

### Q1 — <title>

**The source says:** "<quote>" — <where it is written, e.g. AC-4>.
"<the quote that disagrees>" — <where, e.g. a comment by the implementing developer on the
parent ticket, with its date>.

**Readings:**

- **a)** <the first reading> — from `acceptance_criteria:AC-n`.
  **If chosen:** <which Then is written or rewritten, which row stays manual, which bug closes>.
- **b)** <the second reading> — from `comment:<TICKET> <date>`.
  **If chosen:** <the same, for this answer>.

<Facts from the code with `path:line` where they settle anything. Do not propose a working
interpretation in place of the readings: a proposal the person skims becomes a silent
decision — TP1-15045 is that story.>

### Q2 — <title>

<The same three blocks: what the sources say, the readings with their origins, what each
answer costs.>

---

## Requirements with no observable in code

Every requirement whose register row has `observable: none` is a mandatory question here,
never a silent "will check manually":

- **R-n** — <requirement text>. Confirm the expected behavior (an expected-red test plus a
  bug "not implemented" follows) / defer to a later story / call it a mistake in the
  requirement.
