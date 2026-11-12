# Test code patterns (injection Layer 2: qa-automator, qa-code-critic)

A factory file for any surface (web, mobile, desktop, API, integrations). The project's
embodiment (adopted patterns, where they live, their names) is in the test repo's
`framework-rules.md`; this is the vocabulary and the decision rules for when it has none.

<!-- roles: all -->
## Principle

A pattern answers a RECURRING problem in the code: the trigger is a symptom (duplication,
knowledge on the wrong layer, brittleness), never a wish to apply a familiar construct.

<!-- roles: qa-automator, qa-code-critic -->
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

<!-- roles: qa-automator -->
## Decision ladder (top down; the first fitting answer is final)

1. **The project's framework already has an embodiment** (`framework-rules.md`, existing
   code: layers, base classes, helpers) → use it.
2. **No embodiment, but a similar mechanism exists** (e.g. there is `clients/`, but no
   wrapper for the new transport) → extend the existing mechanism in its own style, do not
   start a parallel one.
3. **Nothing exists, and the symptom recurs** — ≥2 places in this batch of tests, or a
   single scenario already mixes knowledge of different layers → introduce the pattern, per
   the introduction rules below. First check the "Candidates" table in `framework-rules.md`
   (the onboarding backlog): a symptom recurring from there → introduce exactly the pattern
   proposed and move the row to "Adopted".
4. **Nothing exists, the symptom is a one-off** → write it straight, with no abstraction;
   note "candidate for pattern X on recurrence" in the report.
5. **The factory builds the framework from scratch** (bootstrap) → a minimal set from the
   catalog for the project's surface, every chosen pattern as a row in `framework-rules.md`
   with its place in the skeleton. Do not build "for growth".

<!-- roles: all -->
## Rules for introducing a new pattern

- Lives in a framework layer (steps / pages·screens / clients / core / data), not the test
  file; the test only uses it.
- Same commit: a `framework-rules.md` row (name, problem, where it lives, how to use it) and
  an `introduced_patterns` manifest entry with the demanding symptom (≥2 references); a
  pattern absent from either does not exist next run, and the critic cross-checks.
- Keeps the skeleton's downward-only dependency rule, and is named from the vocabulary below, not invented.

<!-- roles: qa-automator -->
## Catalog by problem (not by surface)

Format: **symptom → pattern → what it gives → when NOT to**.

**Knowledge about the surface (locators, handles, routes, schemas) leaks into tests** →
*surface object*: Page Object (web), Screen Object (mobile), Window/View Object (desktop),
Endpoint/Service Client (API), Topic/Queue Client (queues). The same idea for every
surface: how to find and how to poke lives in one layer, the test speaks the domain
language ("log in", "create an order"). NOT: an object per element; one asserting business
results (it returns state, the test checks).

**One business step made of many actions repeats across several tests** → *step / task*
(Steps layer; a Screenplay Task for complex role-actors). Gives: the test as a sequence of
business steps, a single source of truth for the procedure. NOT: a step that wraps a single
surface-object call.

**Preparing an object of many fields is copied around, with 1–2 fields changing** → *Test
Data Builder* (fluent, defaults valid, only what matters changes) or *Object Mother* (named
ready-made instances: "an overdue order"). Gives: the test shows only what matters for the
scenario. NOT: a builder for a two-field object; one that talks to the application (a
fixture).

**Creating a driver / client / connection depends on the environment or platform** (iOS vs
Android, staging vs local, http vs grpc, emulator vs device) → *Factory* (Factory Method /
Abstract Factory). NOT: a factory when there
is a single variant.

**An operation requires coordinated calls to several services / systems** (create a user =
API + queue + file storage) → *Facade*. NOT: a facade that merely renames a single call.

**A test depends directly on a third-party SDK / protocol / integration format** (gRPC
stubs, a payment-provider SDK, a Kafka client, an ORM) → *Adapter* over the third-party API
in domain terms. NOT: an
adapter over your own core library.

**Interchangeable variants of one behavior** (authorization methods, transport, test-data
source, live/replay wait mode) → *Strategy*, chosen via config. NOT: one variant with no
second one foreseen.

**Cross-cutting wrapping around calls** (retries, logging, tracing, timings, a screenshot
on failure) → *Decorator / Proxy* around the client/driver, in core, not every test. NOT:
retries around assertions (defect masking).

**An asynchronous effect that must be caught** (an event, a message in a queue, a push, a
log record) → *Observer / event capture*: a subscriber-collector with an explicit condition
wait from core, instead of sleep. NOT: hand-rolled polling in the test body.

**A resource with a lifecycle** (a session, a temporary user, a file, a DB transaction, a
launched application, an emulator) → *Fixture* with guaranteed cleanup (setup/teardown,
context manager, scope). Gives: isolation and parallelism. NOT: a global resource with no
cleanup "for speed".

**The same check of a complex structure in several tests** (a response schema, a screen
state, an entity invariant) → *Assertion helper / custom matcher* with a clear mismatch
message. NOT: a helper hiding a weak check (`not None`) behind a strong name.

**The same scenario skeleton with variable steps** → *parametrization* first; *Template
Method* — only if the steps really differ in composition, not in data. NOT: hierarchies of
base test classes deeper than one level.

**An entity's state transitions are checked many times** → *transition table + driver*
(state-machine helper): state, event, expected state — as data, one executor. NOT: if there
are ≤3 transitions.

**A before-action value, compared after** → assert the base WORKS, or `base_checked="<file>::<function>"`.

**A refusal for a missing permission** → the SAME credentials make an allowed call in the test or its fixture. A code the sources
leave open is a 4xx range on a line ending `# oracle_unknown: Q<n>`, and the exact-code Then (on one mixed Then, that same Then) is bound
`qa_unresolved(..., reason="expectation_unconfirmed", question="Q<n>")`; a range a requirement or an answer states ends
`# broad_status: range per R-<n>|Q<n>`; a line that is no status check ends `# broad_status: not a status (<why>)`.

**A Then the case lists in `alternatives`** → reading B must fall outside the oracle (`stamp <= t_done - tolerance`,
not `update_date > stamp`); the critic probes B.

**A stamp written after the response, compared with the test's clock** → the window is `[t_before - tolerance, t_after + tolerance]` with the case's tolerance; inside the tolerance the outcome is `pytest.skip("cannot tell: ...")`, never a pass or a red.

<!-- roles: all -->
## Client/SDK reuse

Before a new request: extend the project's client/SDK, then its utilities, only then write
your own; use its typed data models over raw dicts. Missing credentials are `pytest.skip` or a
disposable-user fixture, never an `assert` on an env var.

<!-- roles: qa-automator, qa-code-critic -->
## The red line names the Then

Unpacking hides the Then: assert the count before unpacking (`found = find(...)`,
`assert len(found) == 1, "Then 2: exactly one integration after the move"`, then `[after_move] = found`); a bare
`[x] = find(...)` raises a `ValueError` naming no Then. Likewise an index into a `pytest.param`
(`project_change_kinds[1].values[0]`): read data through the parameter, not the param object.

<!-- roles: all -->
## Anti-patterns (the critic counts them as findings)

- Locators, handles, routes, response schemas, topics — in the test body.
- Assertions inside surface objects and in steps (a step returns state, the test checks).
- An abstraction with a single place of use, introduced "for the future".
- Two mechanisms for one task (a home-grown builder next to the framework's).
- Inheritance for code reuse instead of composition / fixtures.
- A "utility" dump module (`utils.py` / `helpers.ts`) as a substitute for layers.
- Wrapping (retries, waits) in the test instead of core.
