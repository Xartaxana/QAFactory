<!-- generated from plugin:references/artifact-contract-automation.md for qa-automator by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract — the automation artifact

What S5 produces and every later stage reads.

## `automation-manifest.json`

**Writer** `qa-automator`, S5 (and after `TEST_BUG`/`FLAKY` fixes at S7).
**Written only through `manifest_put.py --fragment`** — never by hand.

```json
{
  "tests": [{"covers": ["TC-001"], "file": "tests/test_coupon.py", "marker": "TC-001",
             "instance_id": "test_limit", "shape": "new", "status": "green",
             "critic_verdict": "approved"}],
  "unresolved": [{"case": "TC-004", "reason": "pending_implementation"}],
  "self_fixes": [{"test": "tests/t.py::test_limit", "what": "selector",
                  "why_test_defect": "locator renamed in the diff",
                  "evidence": "evidence/sanity.json",
                  "before": "assert x == 1", "after": "assert x == 1"}],
  "probe": {"layers": "ok", "reuse": "ok", "then_channel": "ok", "duplicates": "none",
            "own_data": "yes", "collected": 12},
  "runs": [{"role": "qa-automator", "label": "w", "scope": ["tests/t.py::test_limit"],
            "code_fingerprint": "a1b2c3d", "warranted": true, "result": "1 passed"}]
}
```

`tests[]` `status` is `green|red|red_lock`; no `critic_verdict` makes the ledger's
`review_skipped` true. `unresolved[]` takes a `reason` from the closed list, plus
`partitions[]` when only a slice of the case is unresolved. `blocked_by_env` is one row per
case: `instance_ids[]` (every instance the stand blocked), `remedy` `{kind:
flag|credential|data|service, where: <file:lines or variable NAME>, change, restart?}` and
`detail` — required when the instance ran and failed: the control that shows the stand, not the
product, blocked it. `self_fixes[]` `before`/`after`: the Then-lines around the fix.
`witness` {`author_green`, `critic_red_probe`, `restored_hashes`}: author receipt, critic red-probe and
restoration proofs; no duplicate green. `run_witness` str — the `run_suite` summary path
(`evidence/sanity.json exit 0 12 passed`; `check_witness.py`'s flat form).
`unprojected_events[]`: projection-written; a committed fragment the merge refused. Fix it, send again.
`introduced_helpers[]`: in each row `manifest_from_tests.py` wrote, fill `purpose`, `searched`, `similar_found` (`none` counts),
`keep`, by `manifest_put.py --fragment`. None: `[]`.

## Instance identity

One test is `<function>[<parameter>]`, built by `contract.instance_id`. Manifest, `stage-scope`, stage guard, RunRequests and `then_bindings`
use that one spelling; `instance_id_aliases(entry)` matches the older spellings to the same
row. **One `tests[]` entry per instance, never one per case.** An id names no case: an
instance proves the cases in its `covers` and the pinned `case_version_links[]`.

### `then_bindings`

`then_bindings[]` says which test and assertion proves each Then clause:
`{case, then (number), instance_id, assertion_ref (file:line), status covered|unresolved, reason?, detail?,
question?, observed?}`. A case is `green` only when every partition and Then clause is covered or
recorded unresolved with a reason. Code checks: `s5_precheck.py`, before the critic; the refusal
names the missing row and the fragment to send. A manifest with no `then_bindings` is read, not refused.

A Then whose oracle is `unknown` (open question) is `{status: unresolved, reason:
expectation_unconfirmed, question: Q-n, observed?}` with a null `instance_id`, never a literal.

A Then a person takes beside the case's green test is a `handed_to_person` remainder (`owner`
`person|other_environment`, `part`, `detail` = the steps): an `unresolved` row with a null
`instance_id` and `assertion_ref`. A Then is proved by a test or left, never both.

A Then another check stops is its own row, never an `unresolved[]` row: `{case, then, status: unresolved,
reason: blocked_by_check, blocking_check, detail}` (no `owner`; `blocking_check` is the red case's key or test's id).
A `contradicts_requirement` row may carry `thens: [n]` and, when the response lacks a field the Then reads, `field_absent`;
a re-sent `contradicts_requirement` row replaces its slice, and its `thens` separately;
`retracted_unresolved` drops a row. A commented-out Then: rubric dimension 8.

A fragment adds, it does not replace: a Then of a unit you name that the fragment does not send stays. To replace a list
whole, or to take a Then out of a unit, send `"retract": ["then_bindings"]` (or the list key) with the full rows; a
retract names top-level keys only, and `tests[]`, `unresolved[]`, `obligation_bindings[]` keep their own doors
(`retracted_instances`, `retracted_unresolved`, `retracted_obligations`).

### One instance, several cases

A `tests[]` entry records the shape its author chose:
`shape: reuse | extend | parameterize | consolidate | new`, `consolidates: [cases]`, and one
line of why (`consolidates` means two lists: in the S5 plan, the tests a consolidated test merges; in the manifest, the cases the instance proves). One instance may carry SEVERAL cases (N:M; a consolidated test is not a finding), each with its
own `then_bindings` rows; each `case_version_links` pin is the task's active `{case_id, version}`.

### Sides and assumptions

A story with a non-real side (`absent`, `substituted`), and the one real-side row below. `tests[].sides` `{<side>: real|substituted|absent}`: an `absent` side is
collected, never run, and listed in a `pending_implementation` row with `instance_ids`. `then_bindings[].about` `[<side>]`.
`tests[].provisional` `[P-n]`. `runs[].kind` `collect` (+ `partial: true`); absent reads `run`.

`provisional[]` via `manifest_put.py --fragment`, merged by `id`: `{id: P-n, kind (key of references/provisional-kinds.json), what,
assumed_from, home {file, line_hint}, dependents [{case, then}], settles_on (a side), status
open|settled_matched|settled_edited|kept_by_decision|retracted, evidence {run: <run id>, home_hash_after}}`. The home is the line
marked `qa-provisional: P-n` in `file`. `home_hash` and `evidence.home_hash_after` are tool-stamped (send `home` with a settling
status): never send them. `retracted_provisional: ["P-n"]` retires a row. A provisional value never sets what a Then expects. None:
`[]`; every side real: no key.

On a REAL side one row is legal, as accounting only (the grounding rule does not change): `placeholder_locator` (`on_real:
first_look_only`; `never` or none is refused), `assumed_from: first_look:<R-n>`, while the first-look record holds R-n `missing` or
`unreachable`, `blocked_by: product`. A test bound to a Then of its `dependents`, or leaning on it, names the row in `tests[].provisional`
(an accounting, not a claim: also a test not touching it), is run, never `blocked_by_env`, handed over or skipped; its green proves no Then.

### `runs[]`

`runs[]` — **every** launch in this story, appended by its maker, never
rewritten; `scope` is the node ids run. `warranted` is `true` when `code_fingerprint` (short git
hash of the touched test files) differs from the last run of that scope or the run changed the
code on purpose; `false` re-proved an unchanged green, the retro counts it.

### `expectation_changes[]`

One row per test that went red and later passed on changed code, or was deleted or renamed
after its red run; `s5_precheck.py --json` lists them. Merged by (sorted functions,
`red_attempt`, `green_attempt`); an omitted field survives; an absent list is not refused.
```json
{"expectation_changes": [{"function": "test_coupon.test_limit", "red_attempt": "5a24a4a316eed5d6254d",
  "green_attempt": "f302be5b9c0d4e71a8b2", "then_refs": [{"case": "TC-001", "then": 2}],
  "what_changed": "limit 5 -> 10", "reason": "Then 2 names no number; TS-1-O1 sets 10"}]}
```

### Author's fields

Author: `functions` may replace `function` when several share one pair of runs; the attempts are job
ids as the finding prints them (`null`, but present, for a deleted or renamed test); each `then_refs`
entry is a case of your dispatch scope and a Then number that exists in it.

### Checked before the critic

**Checked** completeness: every `automate` case is in `tests[]` (existing file, `<case id>`
marker or validated `trace_binding`) or in `unresolved[]` with a closed-list reason.
`stage_guard` rule 3 blocks S6–S8 and any test-code commit while an `unresolved` entry lacks
`deferred_by_decision:`; such a row carries `disputes`, its values in your card. A `self_fixes` whose `after` dropped an assert line present in
`before` is rejected: a FLAKY fix may not weaken a Then.

**Branches** (`branch_accounting.py`): each (branch, Then, partition) of a case's `branches` line is `covered` in `then_bindings` by a
test declaring that partition (or none), or held: a remainder row, or an `unresolved[]` row with `partitions[]`. Silence on one is refused;
manual cases and cases outside your window are not judged.

## Coverage v2 bindings and S5 review window

A v2 `tests[]` item that reuses existing code proves it with `trace_binding`
`{selector, assertion_refs, test_content_sha}` — the executed check, its real assertions, the
exact bytes; a marker may stay as a locator, never as its content binding. Each instance
carries `obligation_refs` (`[{obligation_id, obligation_hash}]`), agreeing `obligation_ids`,
`change_disposition`, `change_basis_ref` and `case_version_links`.

`obligation_bindings[]`, keyed by `obligation_id`, merged by `manifest_put.py`:
`{obligation_id, obligation_hash (sha256 of the approved obligation), instance_ids[],
design_assessment sufficient|partial|unknown, assertion_refs[],
change_disposition new_or_changed|unchanged, change_basis_ref,
code_validity valid|unverified, sensitivity proven|not_required|missing,
quality_receipt_refs[], quality_not_applicable_reason?, probe_receipt_ref,
review_receipt_ref}`.

Quality refs are ids from the WINDOW's `required_quality_checks`, not paths; an empty list takes neither
`quality_receipt_refs` nor `quality_not_applicable_reason`. An unchanged instance
uses `sensitivity: not_required` with a nonempty basis, a new or changed one the live receipt
(`probe_by_code.py`; the product level on the critic's doubt); partial, stale, failed or
unwitnessed evidence stays a gap. A probe whose mutation changes no behaviour is a PROBE
defect (owner: factory), not a surviving test; the automator repairs nothing for it.

### Obligation ids

An `obligation_id` is the plan's `coverage_obligations[].obligation_id`, verbatim (`TS-1-O1`),
in the instance and in the binding: `manifest_put.py` refuses any other spelling and
names the plan's ids; `retracted_obligations[]` drops the one
replaced; `s5_precheck.py` names an unbound obligation before you hand off.
