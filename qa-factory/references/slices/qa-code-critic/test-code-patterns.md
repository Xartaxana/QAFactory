<!-- generated from plugin:references/test-code-patterns.md for qa-code-critic by scripts/contract_slices.py; edit the source, never this file -->
# Test code patterns (injection Layer 2: qa-automator, qa-code-critic)

A factory file for any surface (web, mobile, desktop, API, integrations). The project's
embodiment (adopted patterns, where they live, their names) is in the test repo's
`framework-rules.md`; this is the vocabulary and the decision rules for when it has none.

## Principle

A pattern answers a RECURRING problem in the code: the trigger is a symptom (duplication,
knowledge on the wrong layer, brittleness), never a wish to apply a familiar construct.

## Executable shape

Cases specify coverage; the number of test methods is chosen here. For
each group of cases pick `reuse | extend | parameterize | consolidate | new` and record it on
the manifest entry (`shape`, `consolidates`). Parameterize when setup and action are the same:
the data and the expected value (from the case's oracle) are the parameter's data, each
parameter id names its case. Other Thens: a consolidated scenario, or a test kept
apart (`apart_reason`: another setup, surface or fixture). A case expected red by its
requirement gets its own instance, or a parameter with its `blocked_by_check` marker
on that case's `pytest.param`, never on the function, never in a consolidated body.
A relative result (old/new, before/after, order) asserts BOTH sides against expected values and the side;
cancelling actions (delete then undo) assert after each action, the positive control stays.
Keep several asserts of ONE behavioural outcome together; optimize for maintainability,
diagnostic value and execution cost.
`s5_precheck.py` and `s5_plan.py --check` hint at tests that could merge: advice only.

## Rules for introducing a new pattern

- Lives in a framework layer (steps / pages·screens / clients / core / data), not the test
  file; the test only uses it.
- Same commit: a `framework-rules.md` row (name, problem, where it lives, how to use it) and
  an `introduced_patterns` manifest entry with the demanding symptom (≥2 references); a
  pattern absent from either does not exist next run, and the critic cross-checks.
- Keeps the skeleton's downward-only dependency rule, and is named from the vocabulary below, not invented.

## Client/SDK reuse

Before a new request: extend the project's client/SDK, then its utilities, only then write
your own; use its typed data models over raw dicts. Missing credentials are `pytest.skip` or a
disposable-user fixture, never an `assert` on an env var.

## The red line names the Then

Unpacking hides the Then: assert the count before unpacking (`found = find(...)`,
`assert len(found) == 1, "Then 2: exactly one integration after the move"`, then `[after_move] = found`); a bare
`[x] = find(...)` raises a `ValueError` naming no Then. Likewise an index into a `pytest.param`
(`project_change_kinds[1].values[0]`): read data through the parameter, not the param object.

## Anti-patterns (the critic counts them as findings)

- Locators, handles, routes, response schemas, topics — in the test body.
- Assertions inside surface objects and in steps (a step returns state, the test checks).
- An abstraction with a single place of use, introduced "for the future".
- Two mechanisms for one task (a home-grown builder next to the framework's).
- Inheritance for code reuse instead of composition / fixtures.
- A "utility" dump module (`utils.py` / `helpers.ts`) as a substitute for layers.
- Wrapping (retries, waits) in the test instead of core.
