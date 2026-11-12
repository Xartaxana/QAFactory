# Every block in the controller, and the route through it

`controller.py` refuses **351** times: 351 raises or collected `(Class, message)` problems (a request's problems are gathered and refused whole by `_raise_all`), as `DerivedViewStale`, `EventCommitted`, `IdempotencyKeyReused`, `ProjectionStale`, `StateConflict`, `ValueError` - two kinds that do not
mean the same thing. `StateConflict` says the request is fine and the story's recorded state is not
ready for it (`DerivedViewStale`, a subclass of it, says the event IS committed and only what
follows it failed); `ValueError` says the request itself is malformed and the story was never consulted. The
factory's oldest rule - a check stops a SILENT pass, never an informed one - applies to the
first kind, and this file is the walk that gives every block of both kinds a route (PLAN P21.4,
rules FR-4 and FR-5).

It exists because the rule had been kept per-check: S5's completion demanded a window
acceptance record with no way for a person's word to pass it, and that cost three answers and a
halt in TP1-13797 run 5. The walk found two more of exactly that shape - S1's sources and
S3's plan rows, five conductor sessions and $1.94 on the second - and it also found why: that
gate raised `ValueError`, the class for a malformed request, for a block about the story's own
evidence.

| route | blocks | what it means |
|---|---|---|
| `person` | 17 | their recorded words pass it: `waiver.py --stage <S> --block "<part of the line>" --words-file <file>` |
| `command` | 219 | a factory command clears it. The person decides, the command records; the message names it |
| `caller` | 102 | the call was built wrong. Whoever built it fixes it, and no person is involved |
| `unpassable` | 13 | no word passes it, and the reason is here. These are invariants of the record itself: passing one would destroy what the block protects |

The table was built by a classifier that lives with the plans, outside the package
(`tools/controller-blocks-gen.py` in the factory development repository): it reads every raise out of the controller and names
the ones it cannot place and writes nothing while one has no route, so a walk after the next controller change starts from what changed
rather than from scratch. The file is edited by hand as easily - the test below is what makes
either way safe.

`scripts/tests/test_controller_blocks.py` holds this file to the source: a block with no row
fails the build, a row with no block fails, and an `unpassable` row without its reason fails.
Add the row in the same change as the block - naming the route is part of writing the refusal
(FR-1, FR-2). The key is the function and the message, never a line number: a line moves with
every edit above it. Rows are in source order.

| where | class | block | route | the way through |
|---|---|---|---|---|
| `known_paths_problems` | `ValueError` | known_paths must be an object of named paths, not a list: copy the `resolved_paths` object that | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `known_paths_problems` | `ValueError` | known_paths.{key} must be a nonempty path string | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `known_paths_problems` | `ValueError` | known_paths.{key} must map names to path strings | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `manual_blocks` | `ValueError` | a block holds at least one case, got size {size} | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate_manual_runner_block` | `StateConflict` | manual runner block must name 1..5 unique in-scope cases: | `command` | the refusal lists each problem with its door; a block over 5 is split (`story_step.py start` prints the next block) |
| `code_close_conflicts` | `StateConflict` | checkpoint active work before code-only completion | `command` | `--operation checkpoint` |
| `code_close_conflicts` | `StateConflict` | required prior logical stage incomplete | `command` | close that stage, or skip it with a recorded reason |
| `code_close_conflicts` | `StateConflict` | stage already completed | `command` | nothing: it is already closed |
| `projection` | `ValueError` | unknown coverage migration target | `unpassable` | a migration to a version this build does not know would write a record nothing can read back |
| `_with_environment_jobs` | `ValueError` | missing environment job identity | `unpassable` | a job record without its identity cannot be observed or settled, and a word cannot give it one; the file is repaired |
| `_with_environment_jobs` | `ValueError` | environment job path does not match its identity | `unpassable` | the same: the record and its name disagree, so nothing can say which job it is |
| `prepare` | `ValueError` | new-task qa-runner packet requires execution_kind manual or automation | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `prepare` | `StateConflict` | the automated half of the approved plan is empty: no case is disposed automate and left to a runner, | `command` | a manual block (`story_step.py start --stage S6 --role qa-runner --execution-kind manual --scope <1..5 ids>`) for the manual-agent cases, or a plan row's disposition changed (S3 rework, then gate A) |
| `prepare` | `StateConflict` | raise StateConflict(self.automation_half_refusal(refused)) | `command` | the refusal lists each cause with its door: a manual block for a manual-agent case, leaving a handed case out, `--operation stage-scope` with `execution_kind: automation` for the cases the half may name; a plan that cannot be read is passed by the person's word (`waiver.py --stage S6 --block "S6 half membership: unreadable"`) |
| `prepare` | `ValueError` | (ValueError, issue) | `caller` | a reference in the request that does not resolve - the path is not there, or its sha does not match; fix the call |
| `baseline_inputs` | `ValueError` | baseline requires exactly one approved current-task plan row | `command` | the plan carries one baseline row; revise the plan |
| `deployment_inputs` | `StateConflict` | approved Gate A required before deployment | `command` | the gate decision itself (`gate-decision`) |
| `_plan_document` | `StateConflict` | managed lifecycle requires work/test-plan.json | `command` | the strategist writes the plan; `plan_row.py --add-row` adds one row |
| `_plan_document` | `StateConflict` | structured test plan is unreadable | `unpassable` | nothing can be decided about a document that cannot be parsed - not by a person either. The file is repaired first, and then the decision is real |
| `_case_rows` | `StateConflict` | structured test plan rows must be a list | `unpassable` | the same: a shape nothing can read carries no decision, so passing it would only move the failure further down |
| `_own_key_problem` | `ValueError` | scope holds case ids, and {', '.join(own)} is the story's own key, not a case; at S0 | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_revise_scope_problems` | `StateConflict` | the case index cannot be built: | `command` | fix the case files the message names, then `case_versions.py --task-root <root> --all` pins the cases again |
| `_revise_scope_problems` | `ValueError` | scope member(s) that are not pinned case ids: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_decision_problems` | `ValueError` | decision record invalid: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_decision_problems` | `ValueError` | decision must name action, revision and authorization | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_decision_problems` | `ValueError` | status must be one of: approved, declined, deferred | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_decision_problems` | `StateConflict` | decision references stale source revision | `command` | `gate-decision` builds the request from the current source revision |
| `_decision_problems` | `StateConflict` | gate decision must bind the exact approved scope | `command` | `gate-decision` builds the request with the approved scope |
| `_decision_problems` | `StateConflict` | gate decision must bind the current reviewed input | `command` | `gate-decision` builds the request with the current reviewed input revision |
| `_decision_problems` | `StateConflict` | gate before prerequisite completion: gate must be A | `command` | close the prerequisite stage; if its last role was accepted, `--operation recover` closes it from its own receipts |
| `_decision_problems` | `ValueError` | Gate B receipt requires selected_drafts array of original | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_decision_problems` | `ValueError` | Gate B `orders` is an object of order -> due \| not_ordered | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_decision_problems` | `ValueError` | Gate B decision request carries {', '.join(owned)}: the controller's projection writes | `command` | leave the projection's keys out; `gate-decision --gate B` builds the request with `orders` only |
| `_decision_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_decision_problems` | `StateConflict` | Gate A must bind current source inventory hash | `command` | `gate-decision` copies the current source inventory hash |
| `_decision_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_decision_problems` | `ValueError` | structured test plan rows must be a list | `unpassable` | the same: a shape nothing can read carries no decision, so passing it would only move the failure further down |
| `_decision_problems` | `StateConflict` | managed Gate A cannot approve a nonempty scope with an | `command` | the strategist writes the plan rows (`plan_row.py --add-row`); the gate is decided after |
| `_decision_problems` | `StateConflict` | ; record the reviewed scope with | `person` | raised from the list `_passed_by_person` has already filtered |
| `_decision_problems` | `StateConflict` | structured test plan invalid: | `command` | the strategist repairs the rows `planning_contract.py` names; `gate-decision` rehearses the gate again |
| `_decision_problems` | `StateConflict` | Gate A receipt must bind exact current structured plan | `command` | `gate-decision` copies `--operation gate-inputs` unchanged |
| `_decision_problems` | `StateConflict` | Gate A receipt must bind server-derived semantic plan hash | `command` | `gate-decision` copies `--operation gate-inputs` unchanged |
| `_decision_problems` | `StateConflict` | Gate A receipt must bind exact requirement oracle content hashes | `command` | `gate-decision` copies `--operation gate-inputs` unchanged |
| `_decision_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_decision_problems` | `StateConflict` | Gate A receipt must bind exact coverage-contract revisions | `command` | `gate-decision` copies `--operation gate-inputs` unchanged |
| `_decision_problems` | `StateConflict` | lifecycle actions invalid: | `command` | the strategist repairs the lifecycle actions in the plan (`case_lifecycle.py` names each one) |
| `_decision_problems` | `StateConflict` | managed Gate A requires nonempty pinned case versions for | `command` | the case designer pins the versions of the approved cases at S4, then the gate is decided |
| `_decision_problems` | `StateConflict` | (StateConflict, message) | `command` | a design-review problem of one plan row; the message says which review is missing and `--operation gate-decision` builds the request with the reviews the story holds |
| `_lifecycle_problems` | `StateConflict` | Gate A receipt must bind exact lifecycle actions hash | `command` | `gate-decision` copies `--operation gate-inputs` unchanged |
| `_lifecycle_problems` | `StateConflict` | retirement needs approved reviewable code removal at Gate A | `command` | the strategist adds `proposed_code_changes` to the retire action in the plan |
| `_lifecycle_problems` | `StateConflict` | Gate A must include lifecycle actions or explicit | `command` | `gate-decision` includes the plan's lifecycle actions |
| `_lifecycle_problems` | `StateConflict` | each lifecycle decision must bind action, source | `command` | `gate-decision` builds each lifecycle decision with its action, revision and hash |
| `_lifecycle_problems` | `StateConflict` | retirement needs approved reviewable code removal at Gate A | `command` | the strategist adds `proposed_code_changes` to the retire action in the plan |
| `record_as_is` | `StateConflict` | approve as is: the word for {label} could not be recorded ({type(exc).__name__}: {exc}); no decision | `command` | `gate-decision --as-is` again (a waiver already written is replaced, so a retry is harmless), or the person's word with `waiver.py` |
| `record_as_is` | `StateConflict` | approve as is: still open after recording: | `command` | the refusal names the items still open; `waiver.py --stage <S> --block <the item's block>` records the person's word on each |
| `build_gate_decision` | `ValueError` | gate must be one of: A, B | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_gate_decision` | `ValueError` | {flag} orders work of gate B (the bug reporter, the MR) and is gate B only: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_gate_decision` | `ValueError` | {flag} must be one of: {', '.join(allowed)}; got {value!r} | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_gate_decision` | `ValueError` | --bugs not_ordered says no bug is to be filed, but --drafts chose drafts to file: the | `command` | drop `--drafts`, or record `--bugs ordered` |
| `build_gate_decision` | `ValueError` | --risks-file records a decision to deliver with known gaps, which orders a delivery and is | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_gate_decision` | `ValueError` | the decision to deliver with known gaps carries no reason: a reason is never invented. Ask the | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_gate_decision` | `ValueError` | a decision to deliver with known gaps and --mr {mr} contradict each other: delivering opens | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_gate_decision` | `ValueError` | --words must carry the person's own words; they are the | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_rework_request` | `ValueError` | stage {stage!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_rework_request` | `ValueError` | purpose {purpose!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_rework_request` | `ValueError` | this story is closed (gate B is decided and S8 is done), and | `command` | reopening is the person's word: `--operation rework --reason <their words>` |
| `build_rework_request` | `ValueError` | --reason must say what this round repairs; it is what the role reads | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_rework_request` | `ValueError` | --cause {cause!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_rework_request` | `StateConflict` | this story is held for code ({hold['cause']}) from S{held_number}: a rework of {stage} | `command` | the doors the message prints: the code arrives (`--operation arrive`), the person stops the wait (`--operation stop_waiting`), or an earlier stage is reworked with their words |
| `build_rework_request` | `StateConflict` | this story was stopped while it waited for code: a rework of {stage} reopens it, | `command` | `controller.py --operation rework --stage <earlier stage> --role <role> --words-file <file>` with the person's own words (a typed `--reason` is refused) |
| `build_rework_request` | `ValueError` | --cases must name at least one case of the approved scope: `controller.py --operation | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_rework_request` | `ValueError` | case(s) outside the approved scope: {', '.join(unknown)}; the approved | `command` | name cases of the approved scope, or revise the scope at the gate |
| `build_rework_request` | `ValueError` | plan row(s) not in the approved plan: {', '.join(missing)}; | `command` | name rows of the approved plan, or revise the plan |
| `build_rework_request` | `ValueError` | (ValueError, text) | `caller` | a sentence of `_rework_kind` / `_rework_block_problems` passed on whole, or of the automated half's membership check (`_half_membership_problems`, `build_rework_request`): the cases name both halves, a case outside either half, an unknown kind, a manual block that is over 5 or not a manual-agent case, or - automated half - a manual-agent case, a case handed to the person, or a case of no half; each names its own door (a rework per half or per block of at most 5, leaving a handed case out, `--operation stage-scope`). One sentence is the exception and its door is the PERSON's word, not the caller's: a plan that cannot be read (`waiver.py --stage S6 --block "S6 half membership: unreadable"`) |
| `build_rework_request` | `ValueError` | (ValueError, text) | `caller` | a sentence of `_rework_kind` / `_rework_block_problems` passed on whole, or of the automated half's membership check (`_half_membership_problems`, `build_rework_request`): the cases name both halves, a case outside either half, an unknown kind, a manual block that is over 5 or not a manual-agent case, or - automated half - a manual-agent case, a case handed to the person, or a case of no half; each names its own door (a rework per half or per block of at most 5, leaving a handed case out, `--operation stage-scope`). One sentence is the exception and its door is the PERSON's word, not the caller's: a plan that cannot be read (`waiver.py --stage S6 --block "S6 half membership: unreadable"`) |
| `build_rework_request` | `ValueError` | (ValueError, text) | `caller` | a sentence of `_rework_kind` / `_rework_block_problems` passed on whole, or of the automated half's membership check (`_half_membership_problems`, `build_rework_request`): the cases name both halves, a case outside either half, an unknown kind, a manual block that is over 5 or not a manual-agent case, or - automated half - a manual-agent case, a case handed to the person, or a case of no half; each names its own door (a rework per half or per block of at most 5, leaving a handed case out, `--operation stage-scope`). One sentence is the exception and its door is the PERSON's word, not the caller's: a plan that cannot be read (`waiver.py --stage S6 --block "S6 half membership: unreadable"`) |
| `build_rework_request` | `ValueError` | no accepted S5 plan dispatch of {role} to rework; a plan never accepted is | `command` | rework needs an accepted dispatch of that role on that stage; accept one first |
| `build_rework_request` | `ValueError` | no accepted S5 window of {role} yet; the plan is reworked with | `command` | rework needs an accepted dispatch of that role on that stage; accept one first |
| `build_rework_request` | `ValueError` | no accepted {role} dispatch on {stage} to rework: {found.get('id')} is | `command` | rework needs an accepted dispatch of that role on that stage; accept one first |
| `build_rework_request` | `ValueError` | no accepted {role} dispatch on {stage} to rework | `command` | rework needs an accepted dispatch of that role on that stage; accept one first |
| `build_rework_request` | `ValueError` | --cases meets {len(spans)} windows of S5 ({'; '.join(spans)}); a rework of a window | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_validate_rerun_after` | `ValueError` | rerun_after must be an object with the lists stages, reviews, decisions | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_validate_rerun_after` | `ValueError` | rerun_after belongs to a rework request, which names the dispatch it reworks | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_validate_rerun_after` | `ValueError` | rerun_after.{field} must be a list of ids | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_validate_rerun_after` | `ValueError` | rerun_after.stages must be a stage after {p['stage']}, up to S8 | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_validate_rerun_after` | `ValueError` | rerun_after.reviews must be an accepted dispatch of {p['stage']} by its | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_validate_rerun_after` | `ValueError` | rerun_after.decisions must be an approved gate decision a rework of | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_coverage_contract_revisions` | `StateConflict` | COVERAGE_CONTRACT_REVISION_REQUIRED | `command` | `--operation coverage_migration` with its dry-run receipt |
| `_coverage_contract_revisions` | `StateConflict` | COVERAGE_CONTRACT_REVISION_REQUIRED | `command` | `--operation coverage_migration` with its dry-run receipt |
| `_validate_gate_a_content_current` | `StateConflict` | current Gate A decision required | `command` | `gate-decision --words-file <file>` records the person's approval |
| `_validate_gate_a_content_current` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_validate_gate_a_content_current` | `StateConflict` | Gate A sources changed; review affected requirements | `command` | `--operation semantic_reopen`, then a new gate decision |
| `_validate_gate_a_content_current` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_plan_drift` | `StateConflict` | Gate A plan content changed after approval; re-review affected scope | `command` | `--operation semantic_reopen`, then a new gate decision |
| `_plan_drift` | `StateConflict` | Gate A semantic plan content changed after approval | `command` | `--operation semantic_reopen`, then a new gate decision |
| `_plan_drift` | `StateConflict` | Gate A oracle content changed after approval | `command` | `--operation semantic_reopen`, then a new gate decision |
| `_plan_drift` | `StateConflict` | Gate A coverage-contract revisions changed after approval | `command` | `--operation semantic_reopen`, then a new gate decision |
| `source_inputs` | `StateConflict` | source inventory required before completed discovery | `command` | `ticket_adapter.py collect` writes the inventory |
| `source_inputs` | `StateConflict` | sources pending/invalid: | `command` | `ticket_adapter.py collect|assess`, then `accept-gap` for what is unreachable |
| `gate_inputs` | `ValueError` | structured test plan rows must be a list | `unpassable` | the same: a shape nothing can read carries no decision, so passing it would only move the failure further down |
| `gate_inputs` | `ValueError` | lifecycle_actions must be an array | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `refresh_derived` | `DerivedViewStale` | event committed; derived view not refreshed ({what}); do not repeat the action; | `command` | `--operation recover` refreshes the view; the event is committed, so the action is NOT repeated |
| `apply` | `StateConflict` | controller mutation rejected: stale or missing orchestrator lease | `unpassable` | the lease is what makes this record one story's. A word cannot make a stale writer current, and two writers would interleave the log |
| `apply` | `ValueError` | the {operation} request requires an `idempotency_key` and has none. | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `apply` | `StateConflict` | dispatch reconciliation requires current expected_revision | `command` | read `where` again and retry with the current revision |
| `apply` | `ValueError` | model_policy requires 'parent' (the orchestrator's own | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `apply` | `IdempotencyKeyReused` | idempotency key reused with a different scope: the key | `command` | a new `--operation revise_plan` request with a key of its own and the current `expected_revision`; the refusal names both, and the scope the key was committed with |
| `apply` | `IdempotencyKeyReused` | idempotency key reused with different | `command` | a new `--operation revise_plan` request with a key of its own and the current `expected_revision`; the refusal names the fields that differ |
| `apply` | `IdempotencyKeyReused` | idempotency key reused with different inputs: dispatch | `command` | re-send the scope the dispatch was committed with, or `--operation revise_plan` with the new scope and a new gate A decision |
| `_import_legacy_pipeline` | `ValueError` | legacy pipeline must be an object | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | agent_id is the host's own id of the launched agent, as a | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | initialize once with explicit scope | `unpassable` | a second initialize would start a second story inside the same record, and nothing could tell the two apart afterwards |
| `validate` | `ValueError` | source_revision and known_paths required | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | unsupported coverage contract version | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | initialize requires new or legacy plan contract mode | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | initialize task before work | `command` | `--operation initialize` |
| `validate` | `StateConflict` | checkpoint active work before revising scope | `command` | `--operation checkpoint` |
| `validate` | `ValueError` | plan revision requires scope, content revision and reason | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | plan revision contains unsupported state fields | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | only a stopped dispatch can be reconciled | `command` | `--operation checkpoint` or `release` first |
| `validate` | `StateConflict` | reconciliation requires an accepted successor without unresolved scope | `command` | accept the successor first |
| `validate` | `StateConflict` | successor must cover the same stopped work and inputs | `command` | dispatch a successor with the same scope and inputs |
| `validate` | `ValueError` | reconciliation requires reason and accepted evidence | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | (StateConflict, issue) | `command` | dispatch a successor with the same scope and inputs, accept it, reconcile against it (the stored successor's evidence no longer resolves: its file is gone or its sha changed, and a recorded receipt is replaced by a new successor, never rewritten) |
| `validate` | `ValueError` | technical normalization requires allowlisted kind and both semantic hashes | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | technical normalization preserves an existing current Gate A only | `command` | `gate-decision --words-file <file>` records the person's approval of that gate |
| `validate` | `StateConflict` | semantic content changed; use semantic_reopen | `command` | `--operation semantic_reopen` |
| `validate` | `ValueError` | semantic reopen needs reason and nonempty affected current scope | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | checkpoint active work before reopening Gate A | `command` | `--operation checkpoint` |
| `validate` | `StateConflict` | semantic reopen requires current approved Gate A | `command` | `gate-decision` first |
| `validate` | `StateConflict` | fresh orchestrator context is not verified for this host; use manual_continuation | `command` | `host_capability: manual_continuation` in the handoff |
| `validate` | `ValueError` | handoff needs a new owner lease | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | orchestrator telemetry requires current lease | `command` | `--operation handoff` takes the lease first |
| `validate` | `StateConflict` | host cannot provide verified orchestrator telemetry | `command` | nothing: the host has no such capability, and the counters stay unknown |
| `validate` | `ValueError` | orchestrator telemetry requires a nonnegative model request count | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | context_percent must be 0..100 or unknown | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | coverage migration requires an active version 1 task and known target version 2 | `command` | nothing: the story is already v2 |
| `validate` | `ValueError` | coverage migration requires exact plan hash, backup and migration ID | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | coverage migration plan hash is stale | `command` | re-run the dry-run on the current plan |
| `validate` | `ValueError` | coverage migration requires a current dry_run receipt | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | coverage migration dry_run failed: | `command` | fix what the dry-run names, then migrate |
| `validate` | `StateConflict` | sequential task already has an active dispatch: {', '.join(running)}. Finish it first (`story_step.py finish`) | `command` | `where` answers it with `wait_existing_job`; the driver knows this one by name |
| `validate` | `ValueError` | dispatch contract incomplete | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | raise StateConflict(closed_refusal) | `command` | `--operation reopen_story --dispatch <held ids> --words-file <file>` for work that never started (`next` lists it as `held`); `--operation rework --stage <Sn> --role <role> --cases <ids> --words-file <file>` for new work |
| `validate` | `StateConflict` | resume existing dispatch; do not replace its checkpoint | `command` | `--operation dispatch` with the retry packet `recover` prints |
| `validate` | `StateConflict` | CASE_REVIEW_AFTER_GATE_A: use technical_normalize or semantic_reopen before a new review | `command` | `--operation technical_normalize` or `semantic_reopen` |
| `validate` | `ValueError` | new-task qa-runner dispatch requires execution_kind manual or automation | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | raise StateConflict(self.automation_half_refusal(refused)) | `command` | the refusal lists each cause with its door: a manual block for a manual-agent case, leaving a handed case out, `--operation stage-scope` with `execution_kind: automation` for the cases the half may name; a plan that cannot be read is passed by the person's word (`waiver.py --stage S6 --block "S6 half membership: unreadable"`) |
| `validate` | `StateConflict` | packet checkpoint threshold reached | `command` | `--operation checkpoint`, then a fresh packet |
| `validate` | `StateConflict` | cumulative packet budget reached; resume cannot reset counters | `command` | the person's word on the story budget (`STORY BUDGET` reaches them by the driver's own table) |
| `validate` | `ValueError` | stage {p.get('stage')!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | stage {p['stage']!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | required prior logical stage incomplete | `command` | close that stage, or skip it with a recorded reason |
| `validate` | `StateConflict` | current Gate {gate} decision required | `command` | `gate-decision --words-file <file>` records the person's approval of that gate |
| `validate` | `StateConflict` | the review scope does not hold yet: | `command` | `case_versions.py --task-root <root> --all` for a case file that exists; name the cases for a plan row |
| `validate` | `StateConflict` | scope expansion requires plan/gate revision | `command` | `--operation revise_plan`, then the gate |
| `validate` | `StateConflict` | raise StateConflict(unreadable[0]) | `person` | the sentence of `_unreadable_plan_problems` already passed through `_passed_by_person`: a plan that cannot be read stops the empty-scope check of S6 until the person's word (`waiver.py --stage S6 --block "S6 half membership: unreadable"`) and of S5 until the person's word (`waiver.py --stage S5 --block "S5 scope: unreadable"`), or a repaired plan |
| `validate` | `StateConflict` | . Take the scope from the controller — | `person` | raised from the list `_passed_by_person` has already filtered |
| `validate` | `ValueError` | repair_cause {p['repair_cause']!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | a {cause} round needs `reason`: one sentence of what happened. | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | . A mechanical fix is closed by the author's own | `person` | raised from the list `_passed_by_person` has already filtered |
| `validate` | `StateConflict` | . A second list of mechanical fixes means the | `person` | raised from the list `_passed_by_person` has already filtered |
| `validate` | `StateConflict` | raise StateConflict( blocking[0] + ". " + free + "Otherwise carry what | `person` | raised from the list `_passed_by_person` has already filtered |
| `validate` | `ValueError` | purpose {p['purpose']!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | purpose {S3_LABELLING} requires a fresh qa-test-strategist dispatch of S3: it is window 1 of S3 and nothing el | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | parent_retry {p['parent_retry']!r} names no dispatch of this story. A | `command` | dispatch the `dispatch_request` (relaunch) or `packet` (retry) that `--operation next` prints for it, as it stands |
| `validate` | `StateConflict` | only a checkpointed dispatch can be resumed | `command` | `--operation checkpoint` first |
| `validate` | `StateConflict` | changed retry inputs require explicit invalidation | `command` | `--operation invalidate` names what changed |
| `validate` | `StateConflict` | hard quota exhaustion is not automatically retried | `command` | a person's decision to go on, recorded at the gate or as a waiver on the stage |
| `validate` | `StateConflict` | retry must inherit checkpoint | `command` | the retry packet `recover` prints carries it |
| `validate` | `StateConflict` | relaunch_of {p['relaunch_of']!r} names no dispatch of this story. A | `command` | dispatch the `dispatch_request` (relaunch) or `packet` (retry) that `--operation next` prints for it, as it stands |
| `validate` | `StateConflict` | relaunch_of {p['relaunch_of']!r} is {old.get('status')}: only a | `command` | go back over accepted work with `--operation rework`; resume a stopped role with its retry packet (`recover` prints it) |
| `validate` | `StateConflict` | relaunch_of {p['relaunch_of']!r} repeats that dispatch's work, and this | `command` | dispatch the `dispatch_request` that `--operation next` prints, as it stands; different work is a new dispatch sent without `relaunch_of` |
| `validate` | `StateConflict` | raise StateConflict("; ".join(guard)) | `person` | `stage_guard.dispatch_errors` passes its messages through the person's recorded word before they arrive, and appends the waiver command |
| `validate` | `StateConflict` | cancellation requires the active dispatch | `command` | `--operation request_cancel` on the running dispatch |
| `validate` | `ValueError` | (ValueError, issue) | `caller` | a reference in the request that does not resolve - the path is not there, or its sha does not match; fix the call |
| `validate` | `StateConflict` | unknown dispatch: the request names no dispatch - \"id\" is absent (keys given: | `command` | put the dispatch's id in the request's `\"id\"`; the refusal lists the keys the request had and prints the door (`story_step.py finish`, or `--operation checkpoint` with flags) |
| `validate` | `StateConflict` | unknown dispatch | `command` | `--operation dispatch` registers it; `recover` prints the packet |
| `validate` | `StateConflict` | {d.get('id')} was passed over when its stage was closed by code (receipt {d['passed_over_by']}): | `command` | `controller.py --operation rework`, which the message names: going back over the stage |
| `validate` | `StateConflict` | accept {retry[-1]} | `command` | accept the retry, which the message names |
| `validate` | `StateConflict` | {d.get('id')} is {d['status']}: a stopped dispatch is not accepted | `command` | retry it and accept the retry; the message carries the command |
| `validate` | `StateConflict` | only the active dispatch can finish; | `command` | finish the active one |
| `validate` | `StateConflict` | host worker is still active or cancellation unacknowledged; preserve progress and wait | `command` | wait for it, or cancel and acknowledge |
| `validate` | `ValueError` | invalid completion status: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | accept requires evidence, never an empty digest | `command` | name the artifacts the role wrote as `evidence_refs` |
| `validate` | `ValueError` | (ValueError, issue) | `caller` | a reference in the request that does not resolve - the path is not there, or its sha does not match; fix the call |
| `validate` | `ValueError` | \"unresolved\" is given without \"reason\": \"reason\" carries why the work is | `command` | say what is unresolved, in the accept: `reason` carries it (S1: the person's accept-gap words); the refusal prints the door |
| `validate` | `StateConflict` | accepting {d.get('id')} with stage_complete: false leaves | `command` | pass `stage_complete: true` with the unresolved work named; the message carries the shape |
| `validate` | `StateConflict` | S1 requires canonical source inventory | `command` | `ticket_adapter.py collect` writes it |
| `validate` | `StateConflict` | S1 unavailable sources require explicit unresolved gap handoff: the inventory | `command` | the person's `ticket_adapter.py accept-gap` first (the refusal prints it), then a plain `story_step.py finish`, which derives `unresolved` and `reason` from the inventory |
| `validate` | `StateConflict` | raise StateConflict(refusal) | `command` | dispatch the stage critic (`story_step.py start --stage <Sn> --role <acceptance_by role, e.g. qa-case-critic>`) and record its verdict with `stage_done.py --task <key> --stage <Sn> --acceptance work/handoffs/<its dispatch>.yaml`; or the person's word with `waiver.py --stage <Sn> --block "stage acceptance"` |
| `validate` | `StateConflict` | (StateConflict, "; ".join(blocking) + ". Accept this dispatch with `st | `person` | raised from the list `_passed_by_person` has already filtered |
| `validate` | `ValueError` | checkpoint is not acceptance; use accept with validated evidence | `unpassable` | acceptance and a checkpoint are different facts about the same work, and calling one the other loses the difference the next session needs |
| `validate` | `ValueError` | checkpoint requires remaining work and reason | `unpassable` | a checkpoint with neither says nothing at all, and the next session reads it as the only record of what is left |
| `validate` | `StateConflict` | (StateConflict, item_sentence) | `command` | the person words each open item (a door line, or a block `waiver.py` records), or answers the closed word `approve as is`; `gate-decision` lists the items with their doors |
| `validate` | `ValueError` | policy mode must be preparatory or no_implementation | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | policy requires id, reason and source revision | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | policy references stale source revision | `command` | read the current source revision into the policy |
| `validate` | `StateConflict` | policy must bind the exact approved scope | `command` | bind the approved scope |
| `validate` | `ValueError` | policy requires evidence for the no-implementation decision | `command` | name the evidence for the decision |
| `validate` | `ValueError` | (ValueError, issue) | `caller` | a reference in the request that does not resolve - the path is not there, or its sha does not match; fix the call |
| `validate` | `StateConflict` | preparatory policy requires completed S4 | `command` | close S4 first |
| `validate` | `StateConflict` | preparatory policy requires current Gate A approval | `command` | `gate-decision --words-file <file>` records the person's approval of that gate |
| `validate` | `StateConflict` | preparatory policy cannot replace completed execution | `command` | nothing: the execution already happened |
| `validate` | `StateConflict` | policy already recorded | `command` | nothing: it is idempotent and already there |
| `validate` | `ValueError` | code-only receipts are allowed only for S0, S6, S7 or S8 | `command` | a stage with a role is closed by that role, not by code |
| `validate` | `ValueError` | code-only receipt requires id and reason | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | code-only receipt requires evidence | `command` | name the artifact code produced |
| `validate` | `StateConflict` | the state moved while the close was prepared: the dispatches it passes over changed, send it again | `command` | send the close again: the request is rebuilt from the state as it is now |
| `validate` | `ValueError` | (ValueError, issue) | `caller` | a reference in the request that does not resolve - the path is not there, or its sha does not match; fix the call |
| `validate` | `ValueError` | invalidation requires a cause | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `ValueError` | invalidation must name a nonempty affected current scope | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | invalidation names unknown records | `command` | name records this story has |
| `validate` | `StateConflict` | checkpoint active work before invalidation | `command` | `--operation checkpoint` |
| `validate` | `StateConflict` | invalidation may name only dispatches in its affected scope | `command` | widen the affected scope, or invalidate the right dispatch |
| `validate` | `ValueError` | Gate A applicability carry requires a new source revision | `command` | carry it onto the new revision, not the old one |
| `validate` | `StateConflict` | Gate A applicability must name the current approved Gate A decision | `command` | name the current decision |
| `validate` | `StateConflict` | Gate A applicability requires explicit unchanged requirements and oracle | `command` | say which are unchanged, explicitly |
| `validate` | `StateConflict` | Gate A applicability must bind the unchanged current plan revision | `command` | bind the current plan revision |
| `validate` | `StateConflict` | Gate A applicability must preserve the exact approved scope | `command` | keep the approved scope |
| `validate` | `ValueError` | Gate A applicability requires evidence of unchanged requirements | `command` | name that evidence |
| `validate` | `ValueError` | (ValueError, issue) | `caller` | a reference in the request that does not resolve - the path is not there, or its sha does not match; fix the call |
| `validate` | `ValueError` | mutation requires intent, owned paths and before hashes | `command` | record the intent mutation first, with its paths and hashes |
| `validate` | `StateConflict` | mutation names an unknown author dispatch | `command` | name an author dispatch that exists |
| `validate` | `StateConflict` | mutation ownership and original content are immutable | `unpassable` | the record of who wrote what IS the evidence; a word that changed it would erase the thing it is evidence of |
| `validate` | `ValueError` | unknown mutation progress | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `validate` | `StateConflict` | persist intent before changing files | `command` | record the intent mutation first |
| `validate` | `StateConflict` | mutation progress cannot skip evidence steps | `command` | record the steps in order |
| `validate` | `ValueError` | written progress requires content hashes | `command` | record the hashes with the progress |
| `validate` | `ValueError` | execution/review requires receipts | `command` | name the receipts |
| `validate` | `ValueError` | operation {op!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_mutation_dispatch_problems` | `StateConflict` | reviewed mutation needs an active independent qa-code-critic dispatch | `command` | dispatch the critic |
| `_mutation_dispatch_problems` | `StateConflict` | author mutation must be checkpointed before independent review | `command` | `--operation checkpoint` |
| `_mutation_dispatch_problems` | `StateConflict` | mutation writes must belong to an active author dispatch | `command` | dispatch the author |
| `_unknown_dispatch` | `ValueError` | unknown dispatch | `command` | `--operation dispatch` registers it; `recover` prints the packet |
| `_resume_status_problems` | `StateConflict` | finish or pause {retry[-1]} | `command` | finish or pause the retry, which the message names (`story_step.py finish` / `pause`) |
| `_resume_status_problems` | `StateConflict` | {did} is superseded: this work was set aside; {door}next` prints what holds the | `command` | `--operation next` prints what holds the stage now |
| `_resume_status_problems` | `StateConflict` | {did} is {status}: it is not stopped; `story_step.py finish --task {self._ticket()} | `command` | `story_step.py finish` or `pause` takes the dispatch as it is |
| `_resume_status_problems` | `StateConflict` | {did} is incomplete: it stopped with work left, not for a person's answer, so no | `command` | the retry packet `--operation recover` prints |
| `_resume_status_problems` | `StateConflict` | {did} is {status}: it never reached an agent, or a person set it free, so no agent | `command` | the relaunch packet `--operation next` prints |
| `_resume_status_problems` | `StateConflict` | {did} is {status}: its work is closed; going back over it is {door}rework` | `command` | `--operation rework` |
| `_resume_status_problems` | `StateConflict` | {did} is {status}: only a dispatch stopped for a person (blocked or paused) is resumed; | `command` | `--operation next` prints what the story does now |
| `_resume_stop_problems` | `StateConflict` | {did} stopped on the story budget ({BUDGET_EXHAUSTED}): hard quota exhaustion | `command` | a person's word on the story budget, or fresh work with a new input hash |
| `_resume_stop_problems` | `StateConflict` | {did} has no recorded agent and the request names none: a resume names the | `command` | `--agent-id <the id the Agent call returned>`, or the retry packet when that agent is gone |
| `_resume_stop_problems` | `StateConflict` | {did} is held by agent {mine}, the request names {theirs}: a different agent | `command` | the retry packet `--operation recover` prints |
| `_resume_stop_problems` | `StateConflict` | stale stop: the request retires the stop at sequence {p.get('stop_sequence')}, | `command` | `story_step.py resume` builds the request again from the journal |
| `_resume_problems` | `StateConflict` | sequential task already has an active dispatch: {', '.join(running)}. Finish | `command` | `where` answers it with `wait_existing_job`; the driver knows this one by name |
| `_resume_problems` | `StateConflict` | (StateConflict, closed) | `command` | `--operation reopen_story --dispatch <held ids> --words-file <file>` for work that never started; `--operation rework --stage <Sn> --role <role> --cases <ids> --words-file <file>` for new work; the retro (S9) needs no word |
| `build_resume_request` | `ValueError` | --dispatch-id names the dispatch to resume; this story has: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_resume_request` | `ValueError` | (ValueError, status_problem) | `command` | a status's own refusal of `resume`, passed on whole: it names the door of that status (`next`, `recover`, `rework`, `finish`) |
| `build_resume_request` | `ValueError` | no recorded stop to resume ({identifier} is {dispatch.get('status')} without a checkpoint of | `command` | the retry packet `--operation recover` prints |
| `_code_review_refusal` | `StateConflict` | (StateConflict, "; ".join(blocking) + ". These are the review's own re | `person` | raised from the list `_passed_by_person` has already filtered |
| `_plan_refusal` | `StateConflict` | (StateConflict, blocking[0] + ". " + then + " If a person decides, the | `person` | raised from the list `_passed_by_person` has already filtered |
| `_s5_plan_request_problems` | `ValueError` | purpose {S5_PLAN} requires a dispatch of S5 by qa-automator or qa-code-critic: it is the plan | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_s5_plan_request_problems` | `ValueError` | purpose {S5_PLAN} requires a rework of a plan dispatch (here: rework of | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_s5_plan_request_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_s5_plan_request_problems` | `StateConflict` | the plan critic judges the author's plan, and no plan dispatch of qa-automator is accepted | `command` | `story_step.py start --stage S5 --role qa-automator --purpose s5_plan` dispatches the author's plan first |
| `_s5_plan_request_problems` | `StateConflict` | the plan of {role} is accepted ({live[-1].get('id')}); the plan is reworked, not | `command` | `--operation rework --stage S5 --role <role> --purpose s5_plan`: an accepted plan is reworked, not dispatched again |
| `_s5_window_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_s5_window_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_s5_plan_accept_problems` | `StateConflict` | a plan never closes S5 (accepting {d.get('id')} with stage_complete: true): accept it with | `command` | pass `stage_complete: true` with the unresolved work named; the message carries the shape |
| `_s5_plan_accept_problems` | `StateConflict` | the plan has {len(findings)} gap(s): | `command` | the author mends the gaps `s5_plan.py --task <T> --check` names; the conductor returns them whole |
| `_plan_rework_rows_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_plan_rework_rows_problems` | `StateConflict` | the rows the rework may change cannot be told: the review {last['dispatch']} cannot be read | `command` | the critic completes the form of the last review and `finish` stamps its receipt; the conductor returns it whole |
| `_plan_rework_rows_problems` | `StateConflict` | the rework changed the rows of {', '.join(extra)}, which no blocker of {last['dispatch']} names and | `command` | the author keeps to the blocker rows; the conductor returns the refusal whole (a person's words on the rework lift the bound) |
| `_plan_review_problems` | `StateConflict` | (StateConflict, str(exc)) | `command` | a helper's own refusal passed on whole (`source_inputs`, the plan document, the coverage-contract revisions); the message names its command, e.g. `ticket_adapter.py collect` or the strategist writing the plan |
| `_plan_review_problems` | `StateConflict` | the review {d['id']} cannot be read: {element['unreadable']} | `command` | the critic completes the handover form; `finish` stamps the receipt; the conductor returns the refusal whole |
| `_plan_review_problems` | `StateConflict` | the review contradicts itself: {disagree} | `command` | the critic makes the verdict and the list of remarks say one thing; the conductor returns the refusal whole |
| `_plan_review_problems` | `StateConflict` | the plan changed after this review was stamped ({d['id']} saw other bytes than | `command` | the critic looks again at the current plan; the conductor returns the refusal whole |
| `_plan_review_problems` | `StateConflict` | remark id(s) {', '.join(repeated)} repeat the ids of an earlier review of the plan: | `command` | the critic continues the numbering of the chain (PR-n); the conductor returns the refusal whole |
| `_plan_review_problems` | `StateConflict` | (StateConflict, blocking[0] + ". " + then + end + " If a person decide | `person` | raised from the list `_passed_by_person` has already filtered |
| `_s5_completion_problems` | `StateConflict` | (StateConflict, blocking[0]) | `person` | raised from the list `_passed_by_person` has already filtered |
| `_s5_completion_problems` | `ValueError` | S5 window record is incomplete: | `command` | `window_record.py --task <T> --dispatch <ID>` writes every one of these from what is on disk |
| `_open_windows_problems` | `ValueError` | open_windows requires a plain --not-complete, not unresolved: unresolved already says why | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_open_windows_problems` | `ValueError` | open_windows must be a non-empty list of case ids, one or more of each other window still open | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_open_windows_problems` | `ValueError` | open_windows requires cases of another window of {stage}; {named(bad, SCOPE_SHOWN)} | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_s5_running_beside_problems` | `StateConflict` | . The stage closes with the last window to finish: finish this one with | `person` | raised from the list `_passed_by_person` has already filtered |
| `_s6_running_beside_problems` | `StateConflict` | . The stage closes with the last lane to finish: wait for the running lane, or finish | `person` | raised from the list `_passed_by_person` has already filtered |
| `_s5_collect` | `ValueError` | S5 window needs a nonempty exact scope_instances map | `command` | `window_record.py` builds the map from the manifest |
| `_s5_collect` | `ValueError` | S5 window needs a nonempty exact scope_instances map: | `command` | `window_record.py` builds the map from the manifest |
| `_s5_collect` | `ValueError` | S5 window instances do not exactly cover the dispatched scope map | `command` | `window_record.py` rebuilds it for the dispatched scope |
| `_s5_collect` | `ValueError` | coverage v2 task requires an S5 window schema_version 2 | `command` | `window_record.py` writes the current schema |
| `_s5_collect` | `ValueError` | S5 window input hash does not match its dispatch | `command` | rebuild the record for THIS dispatch (`window_record.py --dispatch <ID>`) |
| `_s5_collect` | `ValueError` | S5 window source revision is stale | `command` | rebuild the record after the source moved |
| `_s5_collect` | `ValueError` | window cannot omit project quality checks | `command` | run the project's quality checks and name them in the record |
| `_s5_v2_collect` | `StateConflict` | coverage v2 S5 completion requires distinct accepted author and active critic for the same window | `command` | dispatch the missing half of the author/critic pair |
| `_s5_v2_collect` | `StateConflict` | ( StateConflict, "; ".join(blocking) + ". Only the active qa-code-crit | `person` | raised from the list `_passed_by_person` has already filtered |
| `_s5_v2_collect` | `ValueError` | coverage v2 instance requires unique obligation_refs with exact hashes | `command` | `manifest_put.py --fragment` binds the obligations |
| `_s5_v2_collect` | `ValueError` | coverage v2 instance requires execution_fingerprint | `command` | `execution_fingerprint.py` writes it into the run block |
| `_s5_v2_collect` | `StateConflict` | instance obligation_refs do not match the current approved plan | `command` | `manifest_put.py --fragment` re-binds them, or the plan is revised |
| `_s5_v2_collect` | `ValueError` | instance obligation IDs must match obligation_refs | `command` | `manifest_put.py --fragment` re-binds them |
| `_s5_v2_collect` | `ValueError` | instance obligation_hash must bind exact obligation_refs | `command` | `manifest_put.py --fragment` recomputes the hash |
| `_s5_gap_problems` | `StateConflict` | this window claims a probe gap no recorded word of the person names ( | `command` | the orchestrator records the person's waiver (`waiver.py --stage S5 --block "<probe gap prefix> <instance id>"`), then `window_record.py` builds the record again; otherwise `probe_by_code.py` writes the receipt |
| `_s5_gap_problems` | `StateConflict` | this window hands | `command` | accept with `unresolved` naming the handed outcome and a reason |
| `_s5_gap_problems` | `StateConflict` | this window holds instances the stand blocked ( | `command` | accept it as `unresolved` naming `blocked_by_env` with a reason; `story_step.py finish` derives that pair from the window record |
| `_s5_gap_problems` | `StateConflict` | this window holds named probe gaps ( | `command` | accept with `unresolved` naming `probe_gap` and a reason; `story_step.py finish` derives that pair from the window record |
| `_s5_gap_problems` | `StateConflict` | this window holds red tests the requirement contradicts ( | `command` | accept it as `unresolved` naming `contradicts_requirement`; `story_step.py finish` derives that pair from the window record |
| `_s5_gap_problems` | `StateConflict` | unresolved window: | `command` | the role resolves them, or the accept names them `unresolved` with a reason |
| `_s5_gap_problems` | `StateConflict` | a completed process with gaps cannot be passed_green | `command` | name the gaps in the accept instead of claiming green |
| `_s3_completion_gate` | `StateConflict` | a window-1 (labelling) dispatch of S3 cannot close the stage; it is accepted with | `command` | the driver accepts window 1 with `story_step.py finish --not-complete --unresolved plan_pending`; the stage is closed by the exit window |
| `_s3_completion_gate` | `ValueError` | structured test plan rows must be a list | `unpassable` | the same: a shape nothing can read carries no decision, so passing it would only move the failure further down |
| `_s3_completion_gate` | `StateConflict` | S3 structured test plan invalid: | `person` | reads `stage_overrides[]` through `_passed_by_person` |
| `_s3_completion_gate` | `StateConflict` | S3 grounding: | `person` | raised from the list `_passed_by_person` has already filtered |
| `build_checkpoint_request` | `ValueError` | --dispatch names the dispatch to checkpoint; running | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_checkpoint_request` | `ValueError` | --status must be one of: blocked, paused, incomplete | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `build_checkpoint_request` | `ValueError` | --reason says what this dispatch is waiting on; `next` reads it | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `release_dispatch` | `ValueError` | --dispatch names the dispatch to release; open dispatches: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `release_dispatch` | `ValueError` | --words records the person's own words: a release is their decision, | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `release_dispatch` | `StateConflict` | {identifier} is {dispatch.get('status')}, which holds nothing back; | `command` | nothing: that status releases nothing |
| `_held_work_refusal` | `ValueError` | --dispatch names the held dispatches the person's word covers, comma-separated; | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_held_work_refusal` | `ValueError` | --words-file records the person's own words: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_held_work_refusal` | `StateConflict` | the story is not closed and holds no work back, so there is nothing to {verb}: | `command` | nothing: no work is held back, and `--operation next` says what the story does now |
| `_held_work_refusal` | `StateConflict` | {did} is the retro (S9), which runs on a closed story with no word of | `command` | nothing: the retro needs no word on a closed story, and `--operation next` relaunches it |
| `_held_work_refusal` | `StateConflict` | {did} is {dispatch.get('status')}, not {NEVER_STARTED}: {what}. | `command` | only a dispatch that never reached an agent is left; `--operation next` lists what is held (a released one asks for nothing) |
| `_held_work_refusal` | `StateConflict` | {did} is not held back on this story ({dispatch.get('status')}): a word | `command` | name the dispatches `--operation next` lists as `held`; the message carries them |
| `_hold_op_refusal` | `ValueError` | `cause` and `held_from` go together: a cause names why the story is held and `held_from` the | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_op_refusal` | `ValueError` | `cause` must be a non-empty word naming why the story is held, e.g. `s5_absent_side` or `first_look_stop` | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_op_refusal` | `ValueError` | `held_from` must be a stage id `S0`..`S9`, got {held_from!r} | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_op_refusal` | `StateConflict` | this story was stopped while it waited, and a bare `await` does not take that back: {door_arrive}, | `command` | the code arrives (`--operation arrive`), or the person's words reopen an earlier stage (`--operation rework --words-file`); the message names both |
| `_hold_op_refusal` | `ValueError` | --words-file records the person's own words: {op.replace('_', ' ')} is their decision, not the | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_op_refusal` | `StateConflict` | nothing is held for code, so there is no wait to stop: `--operation next` says what the story does now | `command` | nothing: no wait is held, and `--operation next` says what the story does now |
| `_hold_op_refusal` | `StateConflict` | the wait was stopped already: {door_arrive}, or {door_rework} | `command` | the code arrives (`--operation arrive`), or the person's words reopen an earlier stage (`--operation rework --words-file`); the message names both |
| `_hold_op_refusal` | `ValueError` | --source-head is the text of the code heads the first look saw, as the caller computed it: {keys} | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_op_refusal` | `ValueError` | --register-hash must be 64 hex characters, got {register!r}: {keys} | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_op_refusal` | `StateConflict` | the wait was stopped: `first_look_continue` does not reopen it. {door_arrive}, or {door_rework} | `command` | the code arrives (`--operation arrive`), or the person's words reopen an earlier stage (`--operation rework --words-file`); the message names both |
| `_hold_op_refusal` | `StateConflict` | this story is held for {hold['cause']}, and only the code arriving clears that hold, never | `command` | the code arriving or the person's stop (`--operation stop_waiting --words-file`): the only word that lifts a hold for code is the person's `not ours` about an absent side, carried out by the driver (`arrive` naming that side); the message names the doors |
| `_hold_dispatch_refusal` | `ValueError` | `await_reopened` is the person's word reopening a stopped story: it carries their own words | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_hold_dispatch_refusal` | `StateConflict` | `await_reopened` reopens a STOPPED story and this one is not stopped: | `command` | nothing: the story is not stopped; `--operation next` says what it does now |
| `_hold_dispatch_refusal` | `StateConflict` | a stopped story is reopened only by the rework of an accepted dispatch of S0-S{number - 1} | `command` | `--operation rework` of an accepted dispatch below the held stage with the person's words, or the code arriving (`--operation arrive`) |
| `_hold_dispatch_refusal` | `StateConflict` | this story was stopped while it waited for code: no dispatch starts on it by itself. | `command` | `--operation rework --words-file <file>` of an earlier stage, or the code arriving (`--operation arrive`) |
| `_settle_order_refusal` | `ValueError` | --order names the order of gate B to settle, one of: {', '.join(table) or 'none declared'}; | `command` | name an order the refusal lists (`bugs`, `mr`) |
| `_settle_order_refusal` | `ValueError` | --outcome is how the order ended, one of: {', '.join(SETTLE_OUTCOMES)}; got {outcome!r} | `command` | `--outcome done` (an MR with its record) or `cancelled` (a person's words or a coded reason) |
| `_settle_order_refusal` | `ValueError` | bugs is done by the accepted qa-bug-reporter dispatch, not by a word: run the reporter | `command` | run the reporter (`--operation next` names it), or call the order off with `--outcome cancelled` and the person's words |
| `_settle_order_refusal` | `ValueError` | --ref is the MR's link or id: an MR order is `done` only with the record of the MR that was opened | `command` | `--ref <the MR link or id>` |
| `_settle_order_refusal` | `ValueError` | --reason-code is the delivery step's reason for the `mr` order only; {order} is called off | `command` | `--words-file <the person's words>` for `bugs` (or `release` of the reporter's dispatch); the code goes with `--order mr` |
| `_settle_order_refusal` | `ValueError` | --reason-code is the factory's own reason, one of: {', '.join(SETTLE_REASON_CODES)}; got {code!r} | `command` | one of the reasons the refusal lists, with `--ref` |
| `_settle_order_refusal` | `ValueError` | --reason-code goes with --ref, the delivery step's own one-line record of why | `command` | `--ref <the delivery step's one-line record>` |
| `_settle_order_refusal` | `ValueError` | a cancelled order is the person's call or the factory's coded reason: pass the person's own | `command` | `--words-file <the person's words>`, or `--reason-code` with `--ref` |
| `_settle_order_refusal` | `ValueError` | --ref holds an MR link or id, or the delivery step's one-line record, at most {SETTLE_REF_MAX} characters | `command` | a `--ref` of at most 2000 characters |
| `_settle_order_refusal` | `StateConflict` | gate B is not decided, so it has no orders to settle: record the person's decision with | `command` | record the decision: `gate-decision --gate B` |
| `_settle_order_refusal` | `StateConflict` | the order {order} is {statuses.get(order, 'unknown')}, not due, so there is nothing to settle | `command` | `--operation next` says what the story does now |
| `_settle_order_refusal` | `StateConflict` | the request settles an order of {p.get('decision_id')!r}, but the newest gate B decision | `command` | build the call again; `--operation next` names the orders of the newest decision |
| `_cli_story_root` | `ValueError` | operation {a.operation!r} must be one of: | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_cli_story_root` | `ValueError` | (ValueError, str(exc)) | `caller` | `hooklib.story_root`'s own refusal passed on whole: the key is not one folder name, or names no existing story folder; the call names the wrong story and the message says which folder it looked in |
| `_cli_story_root` | `ValueError` | --operation {a.operation} takes its request from --input <file.json>, and none was given. | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_cli_story_root` | `ValueError` | {root} is not a story folder: it holds neither a story journal | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `_cli_story_root` | `StateConflict` | initialize task before work: {root} holds no story journal | `command` | `--operation initialize` |
| `main` | `ValueError` | raise ValueError("; ".join(bad_flags)) | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `main` | `ValueError` | --as-is is gate A only: `approve as is` passes the open items of gate A; gate B's questions have | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `main` | `ValueError` | --operation resume is built from flags, never from a file: run `story_step.py resume --task | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
| `main` | `ValueError` | gate_preflight.py is not installed beside controller.py; | `caller` | the request is malformed: whoever built the call fixes it, and no person is involved |
