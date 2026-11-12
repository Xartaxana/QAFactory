# Code review rubric

## Required proofs

1. **The rubric** (below) — nine dimensions.
2. **The author's matching green receipt** (no duplicate green).
3. **A probe of every new or changed test**: the assertion must fail for the
   intended reason; a survivor or a wrong failure reason is a rubric fail.

A fix that makes a test pass without addressing the finding is not a fix.

## On the plan

Judged once, before any window; no probe, no run. Not re-reported: what `s5_plan.py --check`
named (your charter's list). Judge what code cannot:

- **Coverage and shape** (dimension 7, K1-K5). A split made only over the number of Then
  clauses; consolidated parameter ids that do not name the case (P16); the same setup and action not
  parameterized; an `apart_reason` that is not another setup, surface or fixture; a case expected
  red inside a consolidated body. A `remark`, never a `blocker` on its own; the window may
  parameterize and declare the `deviation`.
- **Level and fit** (K6, K7). Not a level above what the Then needs, no
  new test where one can be extended, no repeat of an existing test, the manifesto rung. A
  row with no `level` or `fit` is "not checked", never "matches".
- **Oracle** (dimensions 1-2, K8, K9). A Then's value comes from the requirements, the S3 row
  and the case, never the code; an `open`/`invalid` oracle plans a `qa_unresolved`, not a literal.
- **Obligations, reuse, refactor** (dimension 5, K10, K16, K23). Each obligation has a planned
  binding, existing fixtures and helpers are named, the refactor promised is concrete.

## Conformance to the plan

A window answers its plan slice. Not re-reported: code's checks (your charter's list). Yours: the assert
fits its planned Then (C2); the level is the planned one (C6); the plan's fixtures and helpers are
used, no parallel mechanism (C11); each `applied` row and `not_applicable` reason is true (C12); each
difference is declared with a legitimate reason, an undeclared one is a finding (C13); the promised
helper or deduplication is done (C14); the data strategy is the plan's (C15).

## On the code: nine dimensions (pass / concern / fail)

Written well: 1–6, 8–9. ALL written: 7 (planned window: only the roll-call).

1. **Fit to the case** — every Then of the source case is checked; the case's data table is
   present, not trimmed.
2. **Check quality** — assertions are substantive; tautologies are yours (no detector). A negative test checks
   the error and that state did NOT change. Proof reaches an observable outcome through the real exercised path.
   Check that a refusal test discriminates the cause: the reason the product names (code, message
   key, body field) or a control run that passes without the violated condition
   (a permission refusal: the SAME credentials doing an allowed call, in the test or its fixture);
   `pytest.raises(HTTPError)` on any 4xx proves nothing. A code the sources leave open is a 4xx range on a line ending `# oracle_unknown: Q<n>` (the exact-code Then, on one mixed Then that same Then, is
   bound `qa_unresolved(... reason="expectation_unconfirmed", question="Q<n>")`); a range a requirement or an answer states ends
   `# broad_status: range per R-<n>|Q<n>`. Verify each marker's R/Q states the range; `not a status` on a status line fails. A relative result (old/new, before/after, side, order) asserts BOTH sides against expected values and the side;
   cancelling actions assert after each action, the positive control stays. A test that raises before its
   assert is a finding: the red line names the Then only when the count is asserted first. Likewise
   a masked value compared with a masked value is not a preservation check: compare through a reader that returns the value, or
   assert the write's effect. A value taken before an action and compared after it needs a base asserted as WORKING and
   distinguishable from a refusal; a negative base value is yours.
   A Then its case lists in `alternatives` must fail under each reading B. Model B where the test reads the
   product's value, never the expected side or a constant of the assert; B's value is one A cannot give and the assert reads (a model that changes nothing the assert reads proves nothing: `unverified`, never `test_defect`).
3. **Waits and stability** — no sleep, hard-coded time or run-order dependence; state that can still change is read after waiting for the final state; a time fork uses the case's tolerance and its cannot-tell skip, and a zero-width bound on an async write is a fail.
4. **Isolation** — own data, cleaned up; parallel runs are safe; data and accounts made the project's way (the
   brief's `Project approach` lines). A deviation with no `approach:` comment giving a reason, in the test's own
   comment syntax, at the line is `cause: test_defect`; with one, judge the reason: legitimate is a note, not a finding.
5. **Reuse and layering** — uses the framework's existing fixtures/helpers; every anti-pattern of
   `test-code-patterns.md` is a finding. Likewise the same fixture created twice in one window is a finding.
6. **Hygiene** — no secrets, no commented-out checks outside the dimension-8 sanctioned path; an independent Then placed after a failing assert, with no `blocked_by_check` row, is
   `cause: mechanical` (the framework's non-stopping form, else before the red one, or recorded blocked); so is a soft check whose next read is junk behind a failure.
7. **Completeness against the automate set** — roll-call: every `automate` case of this run
   is covered by an instance that NAMES it, in the code and in `automation-manifest.json`
   (`covers`/`case_version_links`, `then_bindings`), not on the manifest's word. Count and split as in
   "On the plan"; near-copies of a consolidated test are a dimension-5 finding. A case with neither
   a covering instance nor an `unresolved[]` entry with a closed-list reason is a fail.
8. **Masking, closed list** — skip/xfail without reason, a deleted or commented-out
   assertion, a strong assertion weakened, an expectation adjusted toward the observed
   behavior. Without the sanctioned path (`Known defect: BUG-n` + `red_lock`, an
   honest failure, a `legitimate_correction` of 9, or
   a commented-out Then with its reason, its `then_bindings` row with reason `handed_to_person` or `blocked_by_check`, and its Left with you line) → fail.
9. **`self_fixes` honesty** — every automator self-fix (selectors, imports, data prep) carries a
   defect explanation and evidence the product behaves per spec; a fix that changed an expected
   value is an `expectation_changes[]` row, judged by you: `legitimate_correction` (the
   case leaves the value open or the author invented it, and the change matches case and
   product), `fitted_to_code` (`test_defect`), `could_not_judge` (the conductor records the window as unresolved with the reason).

## A blocked row that ran red

- **ran red: read the reason against the change.** For every `blocked_by_env` row whose `last_run` is
  `failed`, read `last_run.reason` against the changed files, runtime provenance and the author's
  `detail`. A reason the product explains (a status code, a body, an assertion on its answer) is
  RED: refuse the row as blocked, name it in the verdict.
- **unverified is not a pass.** `critic_verdict: unverified` is only for a window where the test
  could not run, never a test that ran red.

## An expected value with no source

- **`invented_expectation`.** Per Then a new or changed test asserts, `traceability.py --task
  <TICKET> --oracles` gives the resolver's `settled`, `open` or `invalid`. A literal asserted at
  `open`/`invalid` (an `unknown` Then) is `invented_expectation`: `cause: test_defect`, approval
  blocked.

## An assert stricter than the requirement

- **`stricter_assert`.** Put each assert of a new or changed test beside the Then it binds and the
  `R-n` behind that Then, not beside the code. (1) The assert asks more than the Then (equality of a
  whole object where the Then says the given values are kept; an order, a format or a count the Then
  never names): `cause: test_defect`, narrow the assert to the Then. (2) The assert is the Then, and the
  Then asks more than the `R-n`: after gate A the approved case is the oracle, no finding, no round. One note with no `cause`, only in your findings file, never in the form's `findings[]` (there, a finding without a `cause` is a blocking `test_defect`). S7 runs its control experiment on such a red anyway; the note is for the reader of the review.

## STLC's smells — blocking

Each blocks delivery on sight and goes back with its `cause` (your charter's table; the rest are `test_defect`).

Checked before you (`s5_precheck.py`, `validate_artifacts.py`; meaning is yours): manifest invariants, `then_bindings` and run-mapping completeness, and these smells: sleep, secrets, retry markers,
no assert, a weakened Then-line, a missing case-id trace, a broad negative status, dead
code, an off-ladder fixture, a stray locator, an env-credential `assert`, two values that can both be
`None`, `equal_to` on an unnormalized body, a copy of a helper; an `arch_check` import violation you
run yourself.
The four nobody can detect for you (the third is `invented_expectation`, above):

| Smell | What it looks like |
|---|---|
| Shared state | Module-level fixtures mutated in place; order-dependent tests |
| Over-mocking | Mocks the unit under test, or asserts a mock was called instead of an outcome (never proof of an obligation) |
| Ungrounded | An expected value with no source |
| Refactor goal unmet | The plan promised a helper or deduplication; the file still duplicates the steps |
