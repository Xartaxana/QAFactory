# <TICKET-ID> — understanding

<!-- Written by qa-requirements-tester at S2. ≤ 40 lines. One of the two documents the
     human approves at gate A (the other is test-plan.md; the list is `gate_brief.GATE_A_DOCUMENTS`): this one says what we understood the
     change to be and what we will and will not check; the plan says how.
     Checked by validate_artifacts.py against work/requirements-register.md: every R is
     either in "What we verify" or in "What we do not verify"; every blocking question
     exists as a contradicts:/silent cell in the register's contradiction matrix. The
     register itself is a working artifact under work/ — the human never needs to open it,
     because everything that follows from it is here or in the plan. -->

## Why this change

<One or two sentences: what the ticket changes and for whom.>

## Size

<One line copied from `work/sizing.json`, which YOU wrote at step 5 by running
`sizing.py --task <TICKET>` — never arithmetic done in prose here: size and the functions it
counts, cap (the test ceiling), computed budget, overage if any, count of unverifiable
requirements. e.g. "M (4 functions) · cap 28 · budget 43 · overage 15 · unverifiable 1".
A `size_override` and its reason, if you recorded one with
`--size-override`, follow on the same line.>

## What we verify

- R-1 — <one line, the verifiable statement, not the whole requirement text>
- R-2 — <one line>

## What we do not verify, and why

- R-5 — <one line reason: out of scope / covered by an existing suite / deferred to <ticket>>

## What else the change may touch

<3–7 items: adjacent areas, shared components, or seams the diff crosses that are not
covered by an R above — named so the human can flag a miss before the plan is built, not
after.>

- <area/component — why it might be touched>

## Questions without which testing is pointless

<Only true blockers — a requirement with no observable, a contradiction between sources, an
ambiguous reading with real behavior difference. Everything else is a plan row, not a
question here.>

- Q1 — <one line; full detail in questions-for-owner.md>
