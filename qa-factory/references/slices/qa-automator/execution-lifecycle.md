<!-- generated from plugin:references/execution-lifecycle.md for qa-automator by scripts/contract_slices.py; edit the source, never this file -->
# Execution lifecycle

Shared S5/S6 contract; CLI: `controller-api.md`.

## Before the first write

Resolve every implementation/test repository, source ref and immutable source SHA, and verify
that the checked-out content contains the intended change: ancestry of your brief's
`Branch check` commit proves it at once; a squash, a rebase or a commit of another repository
is proved by content; a branch NAME in context-manifest is the merge request's source branch,
never the test. Halt only when the change is absent. Preserve the current branch; never
create or switch one yourself.

## Author and critic

The run budget: one run per code version of each instance by the author, one probe call per new
or changed instance by the critic, every check of the test; after a critic's remark only instances whose code changed
run again (a helper/config change may widen that within story scope).

S5 exit `open-oracle-asserted`: a Then whose oracle reads `open` is not asserted; bind it `qa_unresolved(... reason="expectation_unconfirmed", question=...)` and assert only the established part (a status range keeps `# oracle_unknown: <ref>`). `invalid` or no register question: back to S4.

### Importing a developer or CI result

Before the initial run, `import_test_receipt.py` may import a developer/CI result without
executing its command: it validates current bytes and the exact source, tests, helpers,
config, toolchain, runtime/build, instance/parameter, reporter and producer adapter
bindings, and writes immutable run blocks idempotently. A CI badge, prose claim, partial
mapping or stale hash proves nothing; an unverified import falls back to the single scoped
initial run, never regression or a repeat of valid green.

Trust is set on the execution profile, never in the RunRequest:
`profiles[].extensions.external_receipts = {"enabled":true,"producer_id":"<id>","system":"<system>"}`,
the producer matching the profile's `adapter_id`/`adapter_version`. Import with
`import_test_receipt.py --project-root <project> --request <typed-request.json> --receipt
<receipt.json>`; evidence entries are task-relative `{"path","sha256"}`, symlinks are
rejected, copies land under `work/imports/<receipt-digest>/`.

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

### Runtime provenance of a request

The request carries validated runtime provenance; an `unknown` or `mismatched` native/app
build identity cannot reuse a prior result. Local unit/CLI work may use `not_applicable` only
when `runtime_required: false`, `target_kind: local_source` and its actual tree/artifact
fingerprint is in the request. Other profiles configure a read-only JSON `runtime_probe`
(argv/cwd/timeout), matched before launch and identical after. A build the person confirmed for
this story at the stage entry's build question (`person_confirmed`: kind, story and revisions
bound) is taken for the launch like `matched` and is never `matched` in the result: equivalence
stays unverified and the fingerprint differs. A refused probe answer (`mismatched`, `unknown`, a
word that no longer holds) stops the run with the probe's own reason and the door, in the
stand's words: say it in your digest as `environment`. Timeout, malformed output or a mid-batch
identity change makes the run block inconclusive and all selected rows `not_run`. Recover a
durable job only with `run_suite.py --recover <idempotency-key> --task <task>`; a missing PID
birth identity never authorizes retry or reuse.

### Every run goes through `run_suite.py`

Roles run `run_suite.py --mine <CASES>` (the typed request built from the open dispatch) or,
for a shape it cannot build, `--request`/`--schedule` from `--template`; nothing else. The
legacy `--task/--label` full suite is a user command, never a factory regression path. A
mapping-only error is reparsed without a rerun — `--task <task> --reparse-block <block>
--mapping <exact-map>`; that flag, `--recover`, `--detail`, `--template` and `--help` pass
the stage guard while a dispatch is open.

### Scheduling more than one request

For more than one typed request, `run_suite.py --schedule <schedule.json>` (fields from
`--template`; `min_selected_instances` defaults to 8).

One request carries the GROUP of instances the window runs, with a `report_test_id` per
instance — not one request per case. The stage guard scopes a request by the cases the
manifest says its instances `cover`, so a consolidated test proving three cases is one
selection, not three. Under two profiles sharing a test root a manifest row names its profile with
`profile_id` (`manifest_put.py`); one that names none is refused, never run under the first.

### Profiles, leases and build commands

Each profile command declares its repository, adapter, argv/cwd/kind/scope, selector mapping
and reporter `{format,path_template}` (`{report_path}` resolves inside the job's isolated
evidence directory). Gate A proves that reporter on one existing test (a card there, not an S5 surprise). `extensions.execution` schema 1
records concurrency, shared resources and level rules: missing isolation/resource evidence
caps capacity at one, an overlap resolves to `unknown`, never by configuration order.

Named build/collect/quality commands declare `runs_tests` and `quality_kind` from the actual
wrapper/config, never guessed from a command name. A mixed wrapper that also launches tests
splits into a non-test quality request plus typed behavioral requests.

## Outcomes that are not `passed`

Incomplete, blocked, skipped, partial and unstable remain distinct from passed. A released
Stop hook or exhausted retry fuse ends a turn as `incomplete`; it never accepts a stage.
