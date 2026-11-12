<!-- generated from plugin:references/execution-lifecycle.md for qa-code-critic by scripts/contract_slices.py; edit the source, never this file -->
# Execution lifecycle

Shared S5/S6 contract; CLI: `controller-api.md`.

### The probe is mechanical, at two levels

Every new or changed instance gets `probe_by_code.py`, the level "the check is live" (its
assertion fails when made false), in any language with an `assertion_probes` entry in
`references/detectors.json`: `intended_failure` writes the receipt into BOTH readers —
the row's `sensitivity_proof.receipt_ref` (delivery) and the binding's `probe_receipt_ref`
(coverage); a row proven by the binding alone is a defect.

The "catches a broken product" level is `red_sandbox.py --probe --request <mutations.json>
--task-root <task> --repo <root> [--dispatch <id>]`, only when the critic doubts the check
looks at the product. It replaces `probe_by_code.py` for that instance (its receipt also
satisfies the live level), runs no baseline while the author's green stands, and
answers a repeat `already_probed`. In a schema-v2 window each changed instance's `probe` carries `proof_level` and an `evidence_ref` among its `evidence_refs`; only the product level (or a block naming no level) demands `mutation_kind:
real_behavior`. An unbound log path or an import, collection, setup, timeout, environment
or unrelated failure is incomplete proof. Schema-v1 windows are unchanged.

A probe row binds to its target by the request's `report_test_id`; a TRX report is
read like a JUnit one. A failure at a site a non-pytest JUnit report does not give is
`incomplete`, not `survived`; so is what `probe_by_code.py` cannot read of a non-Python test
(frame, a launcher that may not rebuild): no verdict; a failure at the mutated line it cannot read is yours to judge (`--judge`). One path takes one
mutation per probe; a red probe with a baseline needs the target's baseline row to pass.

### After a mechanical fix

The critic words a `mechanical` finding and still approves and probes the bytes as they are.
The author fixes it and runs green ONLY changed instances
(`run_suite.py --mine`); no critic follows. The window record then carries `mechanical_round`
`{author_dispatch_id, reviewer_dispatch_id, reviewed_input_hash}`; acceptance takes the
review and probe as current when the author's run block is green on the current `input_hash`. Both are raw test-file hashes.

### Requests, receipts and reuse

Requests and receipts are scoped to task, revision, dispatch, profile, selected instances,
purpose and input fingerprint. Reuse requires matching test/helper/dependency and
source/runtime/environment fingerprints. Missing or stale freshness is `unverified`, not green. A new run needs changed inputs or missing evidence. Generate the fingerprint with
`execution_fingerprint.py` from actual files: its specification file holds `source_revision`, `test_files`,
`config_files`, `dependency_files`, `runtime_provenance` and `profile_id` (`helper_files` optional; `project_config`,
the `qa-factory/config.json` path in `config_files`, optional: with it `config_sha` hashes that
profile's execution-relevant configuration). Map every selected instance through
`instance_contracts.<id>.report_test_id`; a missing or ambiguous row is `not_run`.

### Every run goes through `run_suite.py`

Roles run `run_suite.py --mine <CASES>` (the typed request built from the open dispatch) or,
for a shape it cannot build, `--request`/`--schedule` from `--template`; nothing else. The
legacy `--task/--label` full suite is a user command, never a factory regression path. A
mapping-only error is reparsed without a rerun — `--task <task> --reparse-block <block>
--mapping <exact-map>`; that flag, `--recover`, `--detail`, `--template` and `--help` pass
the stage guard while a dispatch is open.
