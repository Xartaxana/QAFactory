# Artifact contract — the checks ledger

The generated projection gate B is decided from, never written by a role.

Companion to `artifact-contract.md` (closed vocabularies and the markdown artifacts) and `artifact-contract-json.md` (the story's state files). Types: `str`, `int`, `bool`, `[]` list, `{}` object, `?` optional.

## `ledger.json`

**Writer** `scripts/ledger.py`, then `check_delivery.py` fills `delivery_verdict`,
`delivery_ready`, `reasons`, `left_items`. **Readers** the human at gate B,
`test-report.md`, the MR body, `stage_guard` rule 4.

**Path** `work/ledger.json`, as `artifact-registry.json` records it. Every writer resolves
it with `contract.artifact_write_path` and every reader with `contract.artifact` (which
also finds a pre-0.7 flat copy): a path joined by hand reads a file nothing writes and
reports a green story as undeliverable.

```json
{"ticket": "QA-1", "generated": "2026-09-11T12:00:00Z",
 "rows": [{"ref": "TS-1", "kind": "plan_row", "state": "passed_green", "detail": "TC-001"}],
 "delivery_verdict": "yes", "delivery_ready": true, "reasons": [], "reason_records": [],
 "left_items": [], "blocked_by": [], "superseded_blocks": [], "subtasks_open": [],
 "review_skipped": false}
```

`rows[]` `{ref, kind: plan_row|test, state, detail}` — exactly one row per plan row and
one per manifest test, `state` from the checks-ledger vocabulary. `delivery_verdict`: `yes` ·
`after_checks` (ready once the person finishes the checks left with them) · `no`, from typed
records and `references/delivery-verdict-kinds.json`; `delivery_ready` bool is `yes` only.
`reasons` [] str (verbatim from `check_delivery.py`, only what blocks) · `subtasks_open` []
of `{key, status}` · `review_skipped` bool.

`left_items` [] of `{kind, ref, case, to_check, how, words, source, ...}`: one row per case left
with the person, plus a `regression` row (never counted); `source: gate_b` = born at gate B.

`reason_records` [] of `{code, entity, detail, owner, kind}` — one per reason, same order.
**`owner`** is a closed list: `product` · `factory` · `environment` · `review`. It says
whose problem this is, which `delivery_ready: no` never did. A gap in
our own machinery (a reducer that could not join two of its own records, an untriaged
failure, a flake) is `factory` and is **reported, never asked**. `blocked_by` [] str — the
owners present, in that order; `[]` when nothing blocks, and exactly `["factory"]` means
the product is not what is unready. `delivery_ready` stays conservative whoever owns the reason.

`superseded_blocks` [] of `{kind: manifest_unresolved|run_env_blocked, ref, block,
superseded_by: {instance_id, attempt_id, status}}` — environment blocks a later terminal
attempt of the **same instance** has answered. They stay in the manifest and in
`run-report.json`'s `env_blocked[]` (marked `superseded`) and decide nothing. A block with no later result of that instance still blocks; a human
decision (`deferred_by_decision`), `impossible` and `pending_implementation` are never
superseded by a run.

**Checked** the file is generated; row count equals plan rows plus manifest tests. A
`test-report.md` whose `delivery_ready` line disagrees with this file is rejected.
