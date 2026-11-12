# Automation candidacy

The single answer to *which plan rows get code*. Every row of `test-plan.md` carries a
disposition with a stated reason; the human can override any of them at gate A. Severity
alone never decides — see the four inputs below.

## Defect hypothesis and impact class come first

Every plan row starts from a defect hypothesis `class @ place` and an impact class (the row's
`impact_class`), from which **priority is derived, never assigned by hand**; the closed lists are
the `defect hypothesis` and `impact class` rows of the plan contract. A row with no hypothesis is
`smoke` at most, one per requirement.

Code checks: the plan validator; the refusal names the class list and the `<class> @ <place>` form.

## The five dispositions

| Disposition | Meaning |
|---|---|
| `automate` | earns test code, runs on every future execution of the suite |
| `manual-agent` | executed once by `qa-runner` on the live stand, evidence as screenshots |
| `manual-human` | handed to the human whole; the runner never starts it |
| `skip` | deliberately not tested, with a reason |
| `unverifiable` | no observable check exists (fed back as a requirements defect), or the check waits for a gate A question (`if_answered` says what each answer does) |

Every disposition carries a non-empty reason. A disposition without a reason is a guess
with a label, and the validator rejects it.

## The four inputs to `automate` — not priority alone

`automate` is set when at least one of these holds, and the row is observable and
deterministic (see below, always required):

1. **Intent or DoD requires it.** The ticket's stated intent, or the project's "when is a
   story considered tested" answer from onboarding, calls for automated coverage of new
   behavior — this alone is enough, `P2` priority does not block it.
2. **A coverage gap on the main path or the API contract.** The behavior is not defended by
   any existing test and sits on the user's main path or in a contract boundary. Already-
   covered behavior is extended, not duplicated.
3. **A risk signal from the strategy.** A critical flow, a fragile area, a P1 area, a history
   of bugs, a shared component, or a migration in the blast radius — named in
   `test-strategy.md` — pulls a row into `automate` that would otherwise stay manual.
4. **Observable and deterministic — always required.** Without this, `automate` is
   impossible regardless of priority; the row goes `manual-agent` (one-off, or depends on a
   non-deterministic third party) or `unverifiable` (subjective).

Impact class sets the order inside the budget and what gets cut first — never the
switch itself. `automate` is for what will run many times (it joins the regression)
and what is red (its failing test is proof and retest); a one-off check of new
behavior is `manual-agent`; the reason says "regression: yes/no". Level: manifesto ladder. Gate A overrides
that repeatedly flip a row are a retro calibration signal.

## Anti-patterns — never earn `automate`

A closed list the plan validator and the case critic catch mechanically. A row matching one
of these is `smoke` at most, never `automate`:

- checks only that an element is visible;
- checks only the page title;
- checks only the URL after navigation;
- checks only that "a first available record exists".

A persistence requirement needs an independent read-back of owned data. A no-write
requirement instead proves unchanged state through a completed operation. Select the
sequence from the oracle; visibility/title alone cannot establish either contract.

## Embedding ladder — insert before you write

Before writing new code, walk this ladder top down; the first fit wins:

1. **Existing assertions already prove the obligation** → reuse unchanged; no comment-only
   modification and no extra assertion. Map selectors and pinned cases in the manifest.
2. **An existing test has a demonstrated gap** → extend its assertion or parameterization
   with the minimum new behavior. Count parameter instances only when adding a data row.
3. **No sufficient reusable/extendable test** → create at the lowest sufficient layer,
   following project placement conventions. Several candidate matches require comparison,
   not an automatic new file.

The plan's fit column names reuse/extend/parameterize/new and the concrete target before
Gate A. See coverage-design.md for assertion sufficiency and incomplete-search limits.

## Budget — computed, not a wall

`sizing.py` weighs each verifiable requirement by impact class (`config.impact_scale` →
priority → `config.sizing.weights`) and sums `2 × weight` into `work/sizing.json`. The test
ceiling is `cap` in that file, whatever the size label says: the label counts the story's
functions, the ceiling follows what the requirements weigh. **XXL** (above XL) is a
recommendation the person's word passes, never a block. `candidates → planned` is shown in the
plan so the human sees what the ceiling cut. Exceeding `cap` is not silently trimmed — it goes
to gate A as an overage, and the size is not reconsidered.
