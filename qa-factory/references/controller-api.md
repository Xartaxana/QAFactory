# Controller and execution API

Use JSON request files; never embed a shell command in a JSON string to be evaluated.

## Lifecycle writer

`python scripts/controller.py --task-root TASK_ROOT --operation OP --input request.json`

Every mutation request carries `idempotency_key` and `expected_revision` (last observed revision); reuse the key on
transport uncertainty. A conflicting revision requires reading `--operation next` and authorizes
no repeat of external work. `recover` repairs a torn last journal line, rebuilds projections,
completes a stage its own receipts already closed, through a journalled `state_repair`, and prints
`retry_packets` for every stopped dispatch nothing replaced (a retry is the orchestrator's).
Corruption mid-journal blocks writes; nobody hand-edits `controller.json`.

Four operations build their request from state:
`gate-decision --gate A|B --words-file <path> [--drafts <ref,ref>]` (build, check, record;
`--build-only` inspects; `--drafts` is gate B's chosen bug drafts, into `selected_drafts`),
`rework --stage S4 --role qa-case-designer --cases TC-1 --reason "<why>"|--words-file <path>
[--build-only] --brief`, `checkpoint --dispatch <id> --status blocked|paused|incomplete --reason
"<what it waits on>" [--remaining "a;b"] --brief` (`--dispatch` optional when one runs), and
read-only `gate-preflight --gate A|B`. `dispatch` runs the stage guard BEFORE the receipt: a
refusal leaves none and names the `waiver.py` command.

## A dispatch nobody is doing

`dispatch_liveness.state()` answers from proof; the first proof that holds decides:
the driver's `in_flight` pid alive = `alive`; the role's transcript fresh = `alive`; the
driver-runs end row = `returned`; a non-terminal receipt in `state/host-dispatches/` within `dispatch.abandoned_after_s` (default 600 s) of `bound_at` (else file time) =
`alive`, older or untimed = `unknown`, never `abandoned` by age; an unbound receipt of the story and
role = `unknown`; a later `subagent_stop` of that role = `returned`; the transcript inventory: silent
past `abandoned_after_s` = `abandoned`, none past `dispatch.never_started_after_s` (default 180 s)
while the host kept others = `never_started`. No proof = `unknown`: nothing closes.
`recover` and `next` close settled verdicts and a denial in `<task>/state/dispatch-denials.jsonl`
through journalled `state_repair`. A denial closes a running dispatch as `never_started` only if it
names it, or names none and falls between its start (minus 60 s) and the next start of its role and
stage; a later non-terminal receipt naming it, or an `alive` verdict, outranks it. `next` then answers
`resolve_return` or `relaunch`, both with `retry_reason`; `wait_existing_job` carries `liveness`, `release`.

`--operation release --dispatch <id> --words-file <path>` frees a dispatch a person says
nobody is doing: `released_by_person`, artifacts kept, stage startable. A stage
waiver naming `wait_existing_job` ends here. Words by file: `conductor.md`.

A CLOSED story's `next` is `closed`; `held` lists work that never started (no packet).
`reopen_story --dispatch a,b` reopens it for exactly those, `next` relaunches them, the rest stays
`held`; `leave_unlaunched --dispatch a,b` ends them (`superseded`, stage `person_left`); both take
the person's `--words-file`. A closed story refuses `dispatch` unless S9 or a rework's stamp rides on it.

`gate-decision --gate B` also takes `--bugs ordered|not_ordered` and
`--mr open|do_not_open|not_offered`: the orders; the story is `executing` until each is done or cancelled.
`settle_order --order bugs|mr --outcome done|cancelled [--ref <text>] [--words-file <path>]
[--reason-code no_trace|delivered_without_mr]`: `mr` done only with `--ref` (link or id); `bugs` done only
by the accepted reporter; cancelled takes `--words-file`, or a code with `--ref`; a repeat is a no-op.

## Rework of an accepted stage, and derived S5/S6 scope

A `stage_transition` of `running`/`halted`/`paused` on an accepted stage records `rework`
instead of lowering it, and `stage_done.py --status running` refuses such a stage. Rework is
`--operation rework`, which takes input hash, paths and budget from the role's last accepted
dispatch, never `SendMessage` (it misses after a session change). On S1-S3, whose
roles have no cases, `--rows TS-3` names plan rows instead of `--cases` (`plan_rows`).

`stage-scope` is read-only, takes `{"stage", "execution_kind": "manual"|"automation"}` and
returns the scope from the approved plan's dispositions (`automate` rows for S5, plus
`manual-agent` for S6), `instances` (the manifest's test instances per case) and
`windows[]` (`surface` ui|other, `scope`, `accepted_by`): one dispatch each. `prepare` carries
it as `stage_scope`. Never type an S5/S6 scope: an empty one is refused while the plan names
cases, at Gate A too; `waiver.py --stage S5 --block "empty scope"` passes on a person's word.
`repair_cause` test_defect|mechanical|environment|tooling|reviewer_error|question_answer|source_arrived|ticket_changed (+`reason`;
`rework --cause`): only test_defect spends the cap, counted by receipts (a retry chain =
1 round); mechanical: author-only, `dispatch.mechanical_rounds` per window. `prepare`
adds `repair_budget`; S5 `read_first` carries `work/s5-notes.md` and `work/s5-notes/`.

## Gate-A repair and continuation

`technical_normalize` is permitted after Gate A only for an allowlisted, semantic-hash-equal
transformation (formatting, key order, CRLF, derived Markdown). A changed semantic hash
requires `semantic_reopen` (affected current scope, reason): it stales that Gate-A decision,
returns S4 to pending and is the only road to a new `qa-case-critic` dispatch (a direct one is
rejected with `CASE_REVIEW_AFTER_GATE_A`).

`prepare` resolves `runtime_paths` (plugin/project/repository roots, entrypoints). Fresh tasks
record `plan_contract_mode: new`: every row binds a coverage-observation revision; only an
imported legacy task may omit it until a validated migration dry-run succeeds. Leases and window
telemetry: [orchestrator-handoff.md](orchestrator-handoff.md).

1. S0 `initialize`, AFTER S0 is closed (`phases/s0.md` §9): `source_revision` (source
   snapshot hash), `scope` (case ids; S0: []), `known_paths` (named absolute-path object),
   `required_quality_checks` (quality check IDs with a producer). Legacy receipts can be imported;
   it runs once. Resolve sources with `source_preflight.py` before branch changes (`s0.md` §10).
   Copy `prepare.resolved_paths` into `known_paths`; see [path recovery](controller-paths.md).
2. Before every role call, `dispatch`: `id`, `stage`, `role`, `input_hash`, `scope`,
   `known_paths`, `budget`, optional `counters`, `limits`, `purpose` (a closed list) and
   `model_policy` (`parent` plus the host's verified `supported` map;
   `project`/`task` overrides optional). Use `resolved_model` in the host
   call; report an unsupported effort, never substitute one.
3. The role returns bounded evidence paths/hashes. `accept` names dispatch `id`,
   `status: accepted`, `evidence_refs: [{path,sha256}]` and `stage_complete`: the stage's LAST
   role closes it, so an omitted flag is true there and a bare `false` is refused. S5 adds the
   `window`, built by `window_record.py --task <T> --dispatch <critic-id> [--review-receipt]`
   from the manifest, run blocks and receipts, passed as
   `accept --window <path>`, never typed. Explicit `unresolved` + reason closes a partial process, never a clean delivery.
   Once a manifest exists, a `qa-code-critic` accept also needs its review receipts: a
   findings file in the evidence, `review_receipt_ref` on the manifest bindings, and a reason
   wherever `sensitivity_proof` is absent. A person's word passes it.
4. `checkpoint`: the flags above, or `--input` with `id`, `status`, `reason` and a `checkpoint`
   of completed checks, remaining work, counters and running job IDs. A retry names `parent_retry`
   and inherits its input hash, scope and checkpoint. Hard quota exhaustion blocks automatic
   retries. Its record carries `retry_reason` (closed list in [vocabularies.md](vocabularies.md))
   and `retry_words` when a person asked for the repeat. `resume` (flags only) returns a stopped
   dispatch to `running`, same agent.
5. S4: `case_versions.py --all` records the scope (see `scope_note`); `revise_plan` by hand changes
   it. `--operation gate-decision` derives id, exact `scope`, current `input_revision`, the
   `gate-inputs` hashes and `design_reviews[]` and records their words verbatim as
   authorization_source. `verdict` is per plan row: the accepted critic's hashed
   `verdict` column, else that round's word (`reject`/`partial` refuse). A row a person
   changed at gate A is marked on `work/test-plan.json` by code: `overridden: true`,
   `overridden_by: "gate A"`, their words. A critical row binds to its cases through the case
   front matter (`Plan row:`), never `required_scenarios`; the controller verifies distinct
   accepted S4 designer/critic dispatches; a designer counts by `plan_rows`, an empty `scope` by a roll-call naming it.
6. `invalidate` names changed source_revision, reason, nonempty `affected_scope` and the
   affected dispatch/decision ids; it may name only dispatches intersecting that scope, and
   active work is checkpointed first. A new source needs verified deployed identity before new
   runtime proof; a new requirement, revised S2-S4/A.
   A code-only update with unchanged requirements, oracle, plan and scope may carry Gate A
   by adding `gate_a_applicability`: the prior current Gate-A `decision_id`,
   `requirements_unchanged: true`, unchanged `plan_revision`, exact `scope`, hashed
   `evidence_refs`: provenance, not a new decision; missing or stale evidence makes Gate A
   stale. Gate B is never carried. `gate-inputs` hashes the plan and the cases, never the
   source revision: S5 runs `invalidate` on the revision it checked out.
7. `next` returns one action: wait_existing_job, resolve_return, resume_checkpoint (with
   `packet`: the ready retry request; `resume_command`: same agent, no retry), relaunch, await_gate,
   execute_gate_b (`orders[]`: `executor`, `selected_drafts`, `released_by_person`; `held[]`), prepare_stage or complete. Never poll by invoking an LLM while waiting.

For an approved scope with no implementation, record `policy` (`mode` `preparatory` or
`no_implementation`, Gate-A scope and revision, reason, hashed evidence): skipped
receipts for S5/S6, no automator dispatch. `code_only` (`{id, stage, reason, evidence_refs}`)
covers an evidenced zero-work S6, the preparatory S7/S8 projection, and **S0 on an
initialized task** (no role runs preflight; evidence is the `pipeline.json` S0 wrote).
Neither bypasses a gate; S9 stays a retro dispatch. `stage_done.py` is never controller acceptance.

## Execution and red proof

Request contracts, fingerprints, reuse, the red probe and job recovery live in
[execution-lifecycle.md](execution-lifecycle.md) alone; a `run_suite.py --request` names the
exact instance IDs `stage-scope` returned, never a whole suite.

## Projection consumers, environment and reconciliation

`finalize_task.py TASK_ROOT` reduces immutable work/run-blocks and manual-blocks in code.
Dashboard, traceability and delivery read those projections; raw
files stay in work/evidence. Use `artifact_packet.py` for bounded document patches,
[environments.md](environments.md) for integration readiness, and
[environment-preparation.md](environment-preparation.md): `next` and `checkpoint-packet`
expose unsettled `state/environment-jobs/` as `observe_environment_job`; `deployment-inputs`
reports baseline gaps whose `ready` flag authorizes nothing; a missing before capture is shown at S8, never a blocker.

`reconcile_dispatch` takes `id`, `accepted_dispatch_id`, `reason` and the current
`owner_session_id` when leased. It supersedes only stopped work an accepted successor
covers: same stage/role/input hash, covering scope, current hash-verified evidence.
