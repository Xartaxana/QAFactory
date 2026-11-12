# Where the factory breaks its own rules — 2026-09-27

A walk of this package against `factory-rules.md`. It started at twenty of the forty-four rules
with a live violation, which is what you would expect — the rules were written FROM defects, and
fifteen of those defects were fixed while they were being written. **Twenty-five rows are open
today** (eleven in the run 5 table, three walk entries, eleven in the FR-47 … FR-57 table); what left
the list since the walk is at the end of this file, not deleted.

Every entry names the file and line, what it costs, and the fix. Nothing is listed on a grep alone
(FR-26): each line below was read. Entries are removed when the fix lands, not when it is planned.

## Blocking a run today

Nothing. The one entry that stood here — FR-19 + FR-3, the delivery reasons that called our
bookkeeping the product's — is fixed; it is the first item under "Fixed since this walk".

## Measured in run 5, still open

| Rule | Where | What it costs |
|---|---|---|
| FR-11 | **narrowed 07.10 (B-373 c, D-0028)**: the default live level (D-0010) now exists for a test in C#, Java and TypeScript/JavaScript (`references/detectors.json` `assertion_probes`, read by `probe_by_code.py`); it still does not exist for a suffix with no `assertion_probes` entry: `probe_by_code.py` refuses it as a factory data gap, and the door is `red_sandbox.py --probe` (the row to add is data, FR-13). Open until the live proof on a non-Python project (FR-33; backlog B-337 / B-373) | on a project whose language has no entry (Kotlin, Go, Ruby) every probe is the product-breaking one |
| FR-16, FR-17 | **narrowed 28.09**: `manifest_from_tests.py --collect -- <test command>` resolves every id it is about to write through a real pytest collection, rewrites what a plugin renamed, and refuses an id pytest does not collect; without the flag its output says the ids are unverified and the phase file tells the automator to pass it. What is left: a fragment typed by hand and handed to `manifest_put.py` is still unresolved, and `s5_precheck` still diagnoses a spelling mismatch from the run side (`_why_no_row`) instead of asking pytest | 15 of 27 run rows never joined the manifest; 16 obligations read "not proven" against a green execution; discovered at S8, after the window was accepted |
| FR-21 | **narrowed 20.10 (grounding G1-3)**: the second word exists and blocks - `pending_implementation` (the product does not carry the behaviour yet) and `impossible` map to `no` in `references/delivery-verdict-kinds.json`. What is left is the first word: `skipped` maps to `planned_skip` (`none`), and nothing asks whether a row was skipped because the product has no such surface; the grounding step that writes `pending_implementation` for a requirement the diff does not implement is grounding batch 2 (G2-2) | a P1 `blocked-flow` row skipped because the UI field does not exist blocked nothing |
| FR-22 | **narrowed (G2-3)**: a bug candidate no executed check stands behind (a `K-n` risk of the grounding table, a register row marked `bug:candidate-defect`) is a `bug_candidate` line in "Left with you" (`check_delivery.grounding_records`), never silence, and the conductor can send it to the failure analyst at S7 on the person's gate B words. What is left: the road to `bugs/` still runs S7 triage → S8 reporter, and the S7 rework refuses a call with no case (`--cases must name at least one case of the approved scope`) while a candidate has none, so the conductor must borrow a case of the scope for it; the live proof of the whole road (FR-33) is not run | an acceptance criterion unmet in the product can never produce a red test, so the bug the gate ordered had no path; the report had to say "its bug proposal is unfiled" |
| FR-23 | `story_run.delivery()` knows a branch, commits, a push and a Draft MR, and has no state for "nothing goes out". The gap is only here: `code_only()` gives S0, S6 ("the approved plan names no automate or manual-agent case") and S7 ("no failures — nothing to triage") their null outcome, and S9 has `retro_mode: skip` | the delivery step had to ask a person when the decision forbade all four |
| FR-23, FR-5 | the null outcome is DECLARED for one item only (S7's `scope`, the pilot, `null_outcome` in `handoffs/s7-analyst-to-automator.yaml`); every other required list, stage output and tool-filled field is a `never_empty` row with its guard or a row of `pending[]` in `references/null-outcomes.json` (t-305 N0, B-253), 53 pending today, each at a named node; `scripts/tests/test_null_outcomes.py` pins the walk and lets the count only shrink. FR-23's and FR-5's *Check* lines do not name the declaration and the detector yet (the amendment is queued to the maintainers of this file) | TP1-15045 (cmp2r, 02.10): the S7 form refused the empty `scope` of a triage with nothing to repair and the story stopped; the same shape stands undeclared on the other 13 item lists |
| FR-31 | `test_stand_lease.py` | 37/38 under the parallel selftest on a busy machine, 38/38 alone — a test reporting a defect that is not there. Seen twice more on 27.09; it survives six copies of itself running at once and fails only inside the full run, so the load that breaks it is the subprocess-heavy neighbours, not its own concurrency. The suspect is the takeover check: it kills the holder inside the third poll and expects exactly `waited_s == 15`, which one extra poll would break |
| FR-36 | the tracker-write probe runs and the gate packet advertises "tracker write: confirmed" regardless of the run's standing decision | a dispatch spent establishing a right the run forbids, and an invitation to use it printed to the person |
| FR-37 | gate A's own wording said "under `qa-factory/bugs`"; the factory writes the task root's `bugs/` | the filed bug's dedup note describes a directory the bug is not in |
| FR-41 | narrowed twice more on 27.09 — `stand_lease` answers `alive`/`gone`/`unknown` instead of calling an unverifiable holder alive, and the driver's `wait_existing_job` refusal says "nobody can tell whether its agent is running" instead of printing `liveness=None`. What is left is the real limit: on a host with none of the four kinds of evidence the verdict IS `unknown`, the controller closes nothing on it, and only a person can settle such a dispatch | five of the first nine questions to a person were "confirm this dispatch is dead" |
| FR-43 | `story_run.py` writes its progress block-buffered | the log ran up to 40 minutes behind; a stall was diagnosed twice that was not there |

## Found by this walk

### FR-13 — a vocabulary the code keeps a second copy of

`candidate_evidence.py:7`: `EXECUTION_BOUNDARIES = {"unit", "component", "integration", "api",
"e2e-ui", "unknown"}`. `references/vocabularies.md:89` owns **Level**: `unit · component · api ·
integration · e2e-ui · manual-agent · manual-human`. The two already disagree — the code adds
`unknown` and drops both manual levels — so a manual-agent candidate is judged against a set that
does not contain it. One fact, two owners (audit A21 says the same).

### FR-1, FR-2 — 109 blocks name a door nobody has opened in a test

`design/controller-blocks.md` walks all **189** refusals of the controller (98 `StateConflict`,
91 `ValueError`) and gives each a route. For **109** of them the route is `command`: the block's own
message names the command that clears it. Not one of those names is checked against the command.

That matters because the walk found two where the named door did not open: `S3 structured test plan
invalid` and `S1 source collection pending/invalid` both advertised `waiver.py --stage ... --block`,
and the word so recorded lifted the role's exit gate while the stage stayed shut — five conductor
sessions and $1.94 on the S3 one alone in run 5. Both are fixed; the other 109 are unproven.

**Fix:** for each `command` row, a case that runs the named command against a story in that state and
shows the block gone. The cheap first pass is the family that repeats — `--operation checkpoint`,
`gate-decision`, `semantic_reopen`, `recover` — which covers most of the 109.

### FR-41 — the witness gate passes five of twelve roles vacuously

`stages.json witness` names an artifact for every one of the twelve roles, and `exit_gate.witness_errors`
re-runs `check_witness.py` over it. But `check_witness.RULES` holds a contract for four file names only
(`automation-manifest.json`, `run-report.json`, `triage.json`, `requirements-readiness.json`, plus
`code-review.md` and `release-readiness.json` outside this map). For `context-manifest.json`,
`test-plan.md`, `story-case-links.json`, `test-report.md` and `retro.md` the script prints
`OK (no rule for <name> — contract undefined, add it to RULES)` and **exits 0**, so the gate records a
witness acceptance that never happened. The text is honest; the exit code is not, and only the exit code
is read.

These five are not unchecked overall — `validate_artifacts` carries their shape, and that is what the
scope errors bring — but the witness question ("is there evidence this was run, not written") is not
asked of them at all. **Fix:** a rule per artifact, or an exit code that says "no contract" distinctly
from "satisfied"; whichever lands, the ahead card of that role says what the rule demands (FR-38).

## Open under the rules added on 29.09 (FR-47 … FR-57)

The eleven rules came from the owner's standing principles and from TP1-13877; this is where
the package breaks them on the day they were written. Each line was read, not grepped (FR-26). The
fixes are tracked as `B-nnn` in the development repository's backlog (`plans/BACKLOG.md`).

| Rule | Where | What it costs |
|---|---|---|
| FR-47 | scripts that decide in the role's place: no editor for `context-manifest.json`, `requirements-register.md`, `understanding.md`, `test-report.md`, so roles patch them with Python | scout S1: 224 turns, 20 % on hand-written manifest patchers, 11 helper scripts, 12 tracebacks; a stand or tooling finding used to spend one of two test-repair rounds (t-058, B-007 closed that by code: the repair route reads the typed cause; unproven until a live run, FR-33) |
| FR-13 | the case id shape is data now (`case_forms.py`, `config.case_id_form`; `contract.CASE_ID_RE` is deleted, B-013), and what is left of the row is the automation layer, which knows only pytest markers (`manifest_from_tests.py`, `s5_precheck.py:327`); `cost_capture.py:385` recognises the `testproject1` CLI by regex. 01.10: the unresolved-reason words live in ONE place now (`contract.UNRESOLVED_REASONS`, `expectation_unconfirmed` added by t-227; `stage_guard.py` and `manifest_from_tests.py` read it instead of literal copies), and the tracker-prefix list moved from code to data (`jira-fields.json` `not_tracker_prefixes`, t-267) | TP1-13877: `then_bindings` found for none of 3 cases, the automator read factory code for ~35 calls and halted |
| FR-48 | the conductor's prompt is appended to the default system prompt (`Driver.run_claude`), so every call pays for a general assistant; an infrastructure failure of a role session reaches the conductor as a role's digest (`Driver.digest_of`) | TP1-13877: five questions to a person made of "Not logged in", a usage limit and a Cloudflare HTML page |
| FR-50 | the ladder exists for the ticket (REST in a light form → the person, t-267; the agent read path is gone, D-06) and merge requests (`mr-access-routes.md`) and for nothing else a stage fetches; the ticket snapshot now says its route (`provenance.source`: `fetched` / `person_pasted`) and the MR route does not; a lost login on the MR route is still indistinguishable from "not found" (B-246) | on TP1-13877 the person had to ask whether the MR was really read with the VPN off; on TP1-15045 the agent route lost 15 of 15 AC |
| FR-53 | delivery has no "nothing goes out" state (`story_run.delivery()`), and the delivery prompt hard-codes "Jira is never written" instead of reading `external_writes` (`Driver.outward_rule`) | a comparison run cannot close delivery without a person |
| FR-54 | `design/factory-map.md` does not exist yet; the map lives in the development repository (`docs/factory-map/`, Russian) | twins found by hand, as in FR-17 |
| FR-56 | role tool sets are not checked against their phase instructions | one unused tool schema is ~10K tokens of every turn |
| FR-57 | a write over a partial `test-plan.json` is refused with no door to continue or restart (`guard_pre_tool.py`) | TP1-13877: a person deleted the file by hand |
| FR-13 | the scopes of a finding about the factory (`local-urgent`, `local-calibration`, `upstream-candidate`) are a dict in code, `project_decisions.FINDING_SCOPES`, the one list the writer, the CLI's `--scope` choices, the refusal and the dashboard's colours all read (02.10, t-299); the template `references/templates/factory-backlog.md` carries the same three words and their meanings as prose, so the meanings are copied, and the dashboard legend (`factory_dashboard.tab_factory`) and `scope_span` still spell the three words as presentation. Fix: one data file for the words and their meanings, read by all of them, and a project that brings a fourth addressee adds a line, not a code change | TP1-15045 (cmp2r, 02.10): `add-finding` refused a scope with a bare traceback naming no word, the conductor invented a scope, and the finding that the S7 form had no empty answer was never recorded |
| FR-57 | a person's recorded word on a **`review` gap** of an S5 window is read by nothing: `window_record.py` prints "recorded, not read by this window" (t-299, Q7 B'), and the only doors are the critic's `manifest_put.py` record (`unverified` for an instance the stand blocked) or the unresolved acceptance - the person's own word has no executor on this gap, so the ban has no door the person can use. Fix (queued in the development repository's backlog as Q7 A, with a critic review of the plan first): the window gate reads a word for a `review` gap the way it reads `not receipted`, and records the pass | cmp2r, 02.10: `waiver.py --stage S5 --block "review is missing"` recorded a word, said "block lifted", and the next `window_record.py` printed the same gaps; the line had promised the word would pass |
| FR-6 | the driver's own texts still relay raw output as the question body: a role's halt digest (`story_run.py` halt and resume), the S0 person texts, the `run` and guarded-step stops; the checker (`human_text.py`) now catches ids, HTML pages, tracebacks and `/login` and journals them, so these texts are recorded as breaking the rules until they are rewritten in plain words with the raw text in the details file (backlog row B-171; the parent row B-009 was closed by the owner's word 09.10.2026) | TP1-13877: 6 of 6 recorded questions had `problems: []`; a login error and a Cloudflare page reached the person as-is |
| FR-47 | **the first judgment census (03.11.2026, t-1765 node A3; AR-29)**, `stage_guard.py::rule_manifest`: a blocking rule that matches a role's `unresolved[]` reasons against a closed list of words (class `word-list`, computed `blocks: true`). Counted in the `breach` ceiling of `scripts/tests/fixtures/judgment-census.json` | code refuses on the wording of a role's field; the role cannot say what the list did not foresee. Fix direction: the refusal becomes advice for the acceptor, the role's reason travels whole; the ceiling only shrinks (`test_judgment_census.py`). **Closed by X7-2 (spec t-1765)**: the route word is checked first against the closed list (data, `closed_unresolved_reasons`), the role's words go after the `:`, an empty reason and a bare-words reason are refused with the expected list; the row is class `shape`, owner `data`, and leaves `breach` |
| FR-47 | **the first judgment census**, `exit_gate.py::judge_words` and `exit_gate.py::_judged_digest_errors`: a person's or a role's words are reduced to a closed list by the gate (class `word-list`, in a blocking entry file). Counted in `breach`. **Closed by X2-3 (spec t-1765)**: `_judged_digest_errors` is removed (a digest verdict or state word outside the list is advice in `work/advice-<stage>.json`, `exit_gate._digest_word_split`; the refusal keeps only what is absent); `judge_words` stays as it is and is re-classed `xref`, `owner: intent` (it carries a person's recorded word to its record, FR-8, P13) - the census row is B4's | a record that fits no word of the list blocks the handoff, whatever the role meant. Fix direction: as above (advice, not refusal, for what the list cannot read) - done for the digest; the person's word door is data and stays |
| FR-47 | **the first judgment census**, `judge_form.py::unresolved_reason` (`digest` and `digest_errors` left the unit: closed by B1 837f168c, X2-3) (class `word-list`; the file is a blocking entry file): "a word outside a closed list" refuses the digest or the reason. Counted in `breach` | the model judge softens it (`judged_refusal`), but with the judge off the refusal stands on the wording alone. Fix direction: as above. **Closed by X7-2 (spec t-1765)**: `unresolved_reason` is cut with `normalise_unresolved`, `manifest_put._judged_reasons` and their tests; the role chooses the route word and the refusal of `rule_manifest` names the closed list |
| FR-47 | **the first judgment census**, `s5_precheck.py::check_smells`, `check_case_is_oracle`, `check_copies`, `check_relative_oracle`, `check_open_oracle_asserted`, `check_parameterization`, `check_expectation_changes` (class `meaning-proxy`; the file is a detector of the automator's S5 in `stages.json`): quality of the code judged by a pattern, and a hit blocks. Counted in `breach` | a pattern stands in for the code critic's judgment of a test; a good test with the shape of a smell is refused. Fix direction: the hit becomes advice for the code critic (P17: the critic judges the automator's choice). **Closed by X7-2 (spec t-1765)**: `check_smells`, `check_relative_oracle`, `check_parameterization`, `check_copies` print an `ADVICE` block (filed in `work/advice-S5.json`) and carry `blocks_override: false`; `check_case_is_oracle` is a shape refusal (a closed `disputes` value), `check_open_oracle_asserted` and `check_expectation_changes` are xref (a Then's state against its binding; a pair of runs against a record); none is in `breach` any more |
| FR-47 | **the first judgment census**, `validate_artifacts.py::check_test_code`, `check_behaviour_claims` (class `meaning-proxy`) and `check_report_forbidden`, `check_report_human_text` (class `word-list`): the validator refuses by a pattern or a word list over a role's content. Counted in `breach`. **`check_report_forbidden` and `check_report_human_text` closed by X7-5 (spec t-1765)**: the first checks the SHAPES of the factory's ids and markers (`cv_<hex>`, `ti_<hex>`, `work/`, the summary marker; the phrase «look here first» is cut), the second reads the rows of `references/human-text.json` that name a factory id and no longer the two that judge a phrase about a tool run (`exit_code`, `slash_command`: a question only); both are class `shape`, owner `data` | the same: a pattern decides what only the reading role or its acceptor can. Fix direction: advice for the acceptor, the pattern kept as a hint. **`check_test_code` closed by X7-2 (spec t-1765)**: cut with its helpers and tests (a retry, a broad status set and a skip in test code are the code critic's to judge, rubric items 2, 3, 8); the rest of the row stays open (`check_behaviour_claims` X2; the report checks X7-5) |
| FR-47 | **the first judgment census, widened (critic t-1793 F1, F2)**, `validate_artifacts.py::check_bug_form` (class `word-list`): a bug whose `violates` is not on the closed list of oracle kinds is refused ("this is an observation, not a bug"), and a role-set `severity` that differs from the one the scale derives from `impact` is refused. Counted in `breach`. **Closed by X7-5 (spec t-1765; the owner's word 04.11.2026, F-X7-8 (a))**: `violates` is a route word (`code:` is refused with P20 and the six kinds named; an unknown kind is refused), the `severity` comparison is cut (the scale is a suggestion in the charter; the severity word stays one of `BUG_SEVERITY`), the red test (`red_test` or `red_test_none`) must be with the bug; the unit is class `xref`, owner `data` | code decides what is a bug and overrides the role's severity judgment by a closed table. Fix direction: the refusal becomes advice for the bug reporter's acceptor; the scale stays as a suggested severity |
| FR-47 | **the first judgment census, widened (critic t-1793 F1)**, `handoff_check.py::check` and `handoff_check.py::_blocked_row_problems` (class `word-list`; the file is a blocking entry file): a form value outside a field's closed list is refused after the judge's mapping (`_ask_judge`, which can only avoid the refusal), and a blocked row whose `blocked.problem` is empty or a placeholder word is refused. Counted in `breach`. **Closed by X7-5 (spec t-1765)**: `OPEN_LIST_CONTRACTS` is an explicit tuple and the five S5-S9 fields no code reads take `new: <word> -- <why>`; the other list fields are route words and stay closed (E-16); `_blocked_row_problems` reads a state value against the presence of a field (`handoff.is_placeholder` has no word dictionary); both are class `shape`, owner `data` | the role's own wording is checked against a list written from wordings already met (the 26.09 `contradiction` case); the form's repair marker routes it back to the role, but the refusal stands on the word alone. Fix direction: as above (the mapped value is advice; the role's word travels whole) |

## Open under FR-59 (03.10, the gate registry — t-302 T1)

FR-59 landed with the registry (`references/gate-registry.json`) and the scanner (`scripts/gate_registry.py
--check`, audit A26). Thirteen gates are registered as `debt`: each still decides on an unknown with
a comparison of its own, and its row names the backlog id that converts it. The detector is the
scanner itself: a `debt` row with no backlog id, or a comparison outside a registered site, fails
`--check`. The rows close one by one as T2 (`gate_template.py`, `acceptable()` at the literal sites)
and the named backlog rows land; `--check` prints the count that is left.

| Rule | Where | What it costs |
|---|---|---|
| FR-59 | gate `stand_identity` (references/gate-registry.json) | no unknown branch yet, owner B-257: automation on uitest was `env_blocked` because code required `matched` |
| FR-59 | gate `provenance_acceptance` | no unknown branch yet, owner B-255: one predicate (`profile_contract.acceptable_provenance`) serves the run, rehearsal, capture and record sites since t-300 N2; the residue - the local_source and fingerprint bare `not_applicable`, the baseline's literal, gate A's identity read - waits for T2 (`gate_template.acceptable`), the only call the scanner counts as converted |
| FR-59 | gate `test_identity` | no unknown branch yet, owner B-217: a non-match is an unknown whose answer is "run again", not a verdict |
| FR-59 | gate `collected_ids` | the non-pytest and import-error parts are closed (B-407 B-run: a "node ids were not verified" note); the collect-error part is residue: a pytest collect error is a note ("collect failed: ...") and the run goes on, and that note does not say "not verified"; the gate-registry template still has no unknown branch, owner B-278 |
| FR-59 | gate `live_check_demand` | no unknown branch yet, owner B-279: a legacy row whose novelty nobody measured passes |
| FR-59 | gate `s5_coverage` | no unknown branch yet, owner B-221 |
| FR-59 | gate `s5_window` | no unknown branch yet, owner B-179: an unmeasured detector reads as a pass |
| FR-59 | gate `delivery` | no unknown branch yet, owner B-061: the aggregator maps classes to reasons and never asks |
| FR-59 | gate `case_preconditions` | no unknown branch yet, owner B-280: an `error` of the stand reads as a factory defect |
| FR-59 | gate `environment_preparation` | no unknown branch yet, owner B-255 |
| FR-59 | gate `baseline_identity` | no unknown branch yet, owner B-281: baseline readiness advises, it does not decide |
| FR-59 | gate `s5_stand_limits` | no unknown branch yet, owner B-282: an unmeasured limit passes |
| FR-59 | gate `reporter_rehearsal_identity` | no unknown branch yet, owner B-283: an unknown identity keys a rehearsal as the same |
| FR-13 | `gate_registry.ANCHOR_FLOOR` (`matched`, `mismatched`, `person_confirmed`) is a list in code: the registry may add anchors and never drop them, so a data edit cannot blind the scan (builder t-356, D3) | a fourth anchor word is a code change, not a data line |
| FR-13 | the heads a role without Bash may run (`host_adapter._READ_HEAD`: rg, cat, ls, pwd, Get-Content, Get-ChildItem, Select-String) are constants in code, as is the list of readers the runner guard lets mention the runner (`stage_guard.READER_COMMANDS`); a project whose reader has another name is a code change (CX1-5, 19.10.2026, t-942). The flags and scripts that make a reader run another program (`rg --pre`, `find -exec`, awk `system(`, sed `e`) are DATA since CX1-20 (t-995, 20.10.2026): `references/launch-causes.json` `reader_runs`, read through `hooklib.reader_runs` by the runner guard, the read guard and the launch matcher - one table keyed by head, with the per-reader exceptions (`rg -e`, `find -exec grep`) | a read command outside the list is refused with its door (`rg`/`Get-Content`); a launching flag of a reader whose head is not in the table passes the read guard (a table that cannot be read falls back to the built-in `rg --pre` / `find -exec` floor, never to nothing) |
| FR-59 | the shell-substitution reads of the launch guard (CX2-27 / OH3-22, release 0.10.7; `stage_guard.py`, `adapter_forms.py`): the rows `a=gh; $a $(cat words.txt)`, `$a $(f) $(g)` and `python x.py --a $(f) --b $(g)` are an unknown that passes by decision, the AR-28 exception named in the spec (`docs/tasks/specs/r0107-s4a-cx2-27-oh3-22-32.md`, E7); a PowerShell here-string reaching a script block (`[scriptblock]::Create($c).Invoke()`, `InvokeScript`) is not read either (round-2 report F8) | a guard cannot read what a command substitution yields, and refusing every such word is the false refusal the finding reports; until a form is named or a tier above the guard reads the word, these launches pass unread |

## Open under FR-42 (15.10, the no-move audit A27 — conductor/1 C1-8)

The driver's states without a move outside the seam are listed by audit A27 as a shrink-only baseline; each converting node shrinks its rows in the same commit.

| rule | what is open | why it matters |
|---|---|---|
| FR-42 | the driver's states without a move outside the seam: 105 sites in A27's shrink-only baseline (`audit_factory.NO_MOVE_BASELINE`, classes P/S/U; `python -B scripts/audit_factory.py --no-move` prints each); conversions are conductor/1 C1-5b2, C1-6, C1-7 and conductor/2, each shrinking its rows in the same commit | a P/S site asks a person without the conductor's priced options; a U site lets a failed factory script pass in silence (P22) |

## Open under FR-7 (30.10, GW1-15 / release 0.10.7)

| rule | what is open | why it matters |
|---|---|---|
| FR-7 | an `accept` on the story-level question `integration missing: <name>` (asked for a `required` row, a `named_here` row, an unreadable plan or case) is not a stand-gap word and no key of it reaches the late S5 `blocked_by_env` row of the case, so gate B asks the same case again; the direction is the question, pinned by `test_stand_gap_carry.py` K15.9. Closing it needs a typed `integration` field on the `blocked_by_env` row, tied by equality, never by reading the row's detail (`gates-and-words`, the node after GW1-15; the finding names it) | a person who answered at gate A is asked a second time for a service they already accepted, with no word that the first answer did not cover it |

## Fixed since this walk

- **FR-18 - eight claims a role asserted and nothing read back: 3 verified, 5 removed** (27.10.2026, node SC1-2 part C,
  B-023). Found by the FR-11 walk of the handoff contracts (28.09): `handoff_check.CLAIMS` re-computed five claims and
  eight had no verifier, so the role typed `true` to get past a form. Now `handoff_check.CLAIMS` holds nine, and every
  one of the eight is either verified or gone:
  `size_computed_by_sizing_py_not_quoted` (the form's `size.computed` against `work/sizing.json`),
  `the_verdict_was_computed_by_rollcall_not_typed` (the form's outcome and `review.rollcall` against
  `critic_rollcall.derive`) and `every_instance_carries_a_fingerprint_or_says_never_run` (a row that says it ran has its
  receipt on disk) got a verifier that answers `None` - never `true` - for what it cannot measure; `--fix` writes `true` into
  an empty claim only where its verifier proves it. Five were removed from their contracts and from the pending list of
  `references/null-outcomes.json` (58 to 53; `field-producers.json` and the pins follow): S1
  `every_retrieved_attachment_has_an_inspection_receipt` (`source_preflight.py` already refuses an S1 exit without the
  receipts), S2 `every_requirement_names_its_source_and_revision` and S3 `every_row_carries_a_coverage_contract_revision`
  (they repeat the required `scope[].source` and `scope[].coverage_contract_revision`), S6
  `every_rerun_names_the_fingerprint_that_moved` and S9 `the_numbers_were_computed_by_code_and_not_recomputed_by_the_role`
  (decision F6 (a), Lead, 27.10.2026). The S6 verifier was once called cheap here (it reads the fingerprints the runner
  already opens); it can come back as a finding. About sixty other claims stay the role's own statement. Closed by code and
  data; proven by a live run (FR-33) at the next story.
- **FR-21, half - the product's missing behaviour now blocks** (20.10, grounding G1-3,
  `references/delivery-verdict-kinds.json`). `pending_implementation` maps to `no` (owner product): a story whose ledger carries it is not
  delivery-ready, and a story written ahead of its implementation is no longer offered the MR at gate B. The `skipped` half stays open above.
  Closed by data; proven only by a live run (FR-33).
- **FR-11 — the receipt the code critic's tool could not produce** (30.09, t-016 A-C, D-0010/D-0012,
  B-002). `probe_by_code.py` now writes the immutable typed receipt itself (the level "the check is
  live") and publishes it to both readers, for every new or changed test; `red_sandbox.py --probe`
  (the level "catches a broken product") is the critic's choice on doubt, and only a failed or absent
  live check blocks delivery (`references/verification-levels.json`, `scripts/proof_level.py`,
  `field-producers.json` names both scripts, held by `test_field_producers.py`). Closed by code;
  proven only by a live run (FR-33): the critic's window on a live story is the proof.
- **FR-35 — every non-approved verdict reported as a rejection** (30.09, t-016 B-C, D-0013, B-010).
  `ledger.test_state` keeps each verdict its own word: `review_rejected`, `review_unverified` (the
  person's debt, "Left with you", never a delivery block) and `review_unrecognised:<word>` (our own
  defect, owner factory); `traceability`, the dashboard and the scribe's report print the critic's own
  words. Closed by code; proven only by a live run (FR-33): a critic that says `unverified` on a live
  story is the proof.
- **FR-49 — the ticket snapshot the scout's brief never carried** (29.09, `story_run.py` S0,
  `ticket_adapter.read_ticket_file`, B-008). The driver wrote `work/ticket-snapshot.md` from the
  glued stdout and stderr of `get --json`, while `brief_pack` names `work/ticket-snapshot.json`.
  The snapshot is now that file and nothing else: the adapter's stdout byte for byte, stderr kept
  out (`py_stdout`), hashed by `initialize` as the controller's `source_revision`; the adapter's
  `--ticket-file` and `diff` read the JSON form (and the legacy form with a stderr tail), and a
  story in flight that has only the `.md` gets its `.json` once (`adopt_legacy_snapshot`). Held by
  `test_story_run_s0.py` (`D1(a)`-`D1(e)`) and `test_ticket_adapter.py`. Not yet exercised by a live
  run (FR-33): the scout's brief on a live story is the proof. On the skill path the staleness
  check is one `ticket_adapter.py freshness` command with a `work/ticket-freshness.json` record
  beside the snapshot and no `.prev` copy; the driver runs the same command at the same trigger
  (`Driver.ticket_freshness`; rows B-259 and B-364 closed by the owner's word 09.10.2026, the code is in
  0.9.0); proven only by a live resumed driver story (FR-33) — that proof is owed in the live-runs pile.
- **FR-40 — every state walked, and the two things the walk found** (28.09,
  `design/state-exits.md` + `test_state_exits.py`, P21.5). The doors were nearly all there; what
  was missing was a place where they are written down together, which is why
  `retracted_instances` was invented twice before it was found once. The test enumerates the
  states from the source — `controller.projection([])`, `manifest_put`'s merge keys, `waiver.py` —
  so a new field cannot be added without saying how a story leaves it. Two findings:
  `stage_overrides[]` had no way out at all (a person's word passed a block and nothing could take
  it back except editing `pipeline.json` by hand), which `waiver.py --revoke` now is — appending
  `revoked_at`/`revoked_decision` rather than deleting, so the record of the pass survives; and
  `unknown_external_writes[]` has no writer, which is a missing fact rather than a missing door
  and is now recorded as such.
- **FR-16 — a case's marker read as an instance's identity** (28.09, `contract.instance_id_aliases`
  + `legacy_identity_is_the_case`). Found by writing the FR-40 walk's test: the 0.7.x selector hash
  is the same for every instance of a case when the only legacy field a row carries is the case's
  own `marker`, and `manifest_put._retract_aliases` read that hash as a shared alias — so
  retracting one partition of a case **dropped its sibling**, evidence and all. The hash is an
  alias only when the fields it hashes can tell two instances apart (`test`, `parameters`, or a
  `selector` that is not the case's marker). Regression in `test_case_identity.py`.
- **FR-39 + FR-17 — the write side of the guard against the artifact homes** (28.09, P21.10).
  `guard_pre_tool.OWNED_ARTIFACTS` held a second, shorter copy of `artifact-writers.json`: eight
  of the sixteen artifacts a role owns, so the readiness, the machine plan, the diff, the bug
  drafts, the retro and the two project ledgers could be repaired by whoever noticed — the defect
  `owner_check` exists for, on nine artifacts it never looked at. The permission is derived from
  the registry now ("one artifact, one writer"), the in-code map is the floor under a broken
  checkout and a test holds it to be a subset, and a project-level ledger with no ticket in its
  path is answered by `_any_story_open_for_owner` instead of being skipped.
  `test_guard_write_owners.py` walks every row of the registry against the guard — the owner
  writes, another role is refused with the rework door, an open dispatch of the owner is the other
  way through — 92 checks, and 11 of them go red when the eight-entry map is put back. What is
  still unexercised on the write side: the artifacts whose writer is a SCRIPT (`work/evidence/`,
  `state/story-case-links.json`, the ledgers), where the guard has no opinion by design.
- **FR-12 — the five detectors that read prose by a phrase list** (28.09, P21.7). Each one now
  reads a field, and where no field says, the answer is `unknown` and it is printed:
  - `s5_precheck.CASE_DOUBT_RE` + `OBSERVED_RE` are gone. A `deferred_by_decision:*` row says
    what it disputes in its own `disputes` field (`contract.UNRESOLVED_DISPUTES`:
    `nothing|derivation|case_expectation`), the automator's ahead card asks for it (FR-38), and a
    row that does not say is asked once, with the `manifest_put.py` fragment that answers it. Both
    directions of the old defect are closed: a dispute worded otherwise no longer escapes, and a
    legitimate deferral worded like a dispute is no longer accused.
  - `judge_cases.NEGATIVE` and the Then half of `judge_code.NEGATIVE_RE` are replaced by
    `grammar.negative_case`, which reads three fields — the case's `defect_class`
    (`NEGATIVE_OUTCOME_CLASSES`), a `negative` variant among the plan row's applicable scenarios,
    and a 4xx/5xx status the Then fixes, which is arithmetic on a value. `None` is a third answer:
    `judge-cases.json` carries `not_judged` per case and the render names the dimension, the case
    and why, so the critic scores it instead of it going quietly missing. The code half of
    `NEGATIVE_RE` stays, renamed `NEGATIVE_CODE_RE` — code is not prose.
  - `critic_rollcall.UNREVIEWED_RE` is gone: `reviewed` is `True|False|None`, a table with no
    `reviewed` column states nothing about its rows, `derive` returns them as `unstated`, and an
    approving verdict over them is refused with the column named as the repair. `gate_brief` no
    longer parses that table with a regex of its own (FR-17, FR-10) — it calls `parse_rollcall`,
    and the brief prints "whether N rows were reviewed is not stated" where it used to print
    "every row reviewed" (FR-41).
  - `audit_factory.WRITE_VERBS` + `FILE_HINT`: A2 and A2b ask the registry
    (`artifact-writers.json`, "one artifact, one writer") and the role's own mandatory
    `## Outputs` section. The first thing the field-based check found was true and small: the code
    critic's Outputs named no file although its Procedure has it writing `critic-findings.md`;
    the charter now says so.
- **FR-19 + FR-3 + FR-20 — the reasons that called our bookkeeping the product's** (28.09,
  `references/delivery-reason-owners.json`). The walk's own number was wrong in both directions,
  which FR-26 predicts: the 18-of-24 count came from calling `reason_owner()` with the text alone,
  while the runtime road is `reason_record()`, which derives the typed code from the prefix first.
  Measured on all **42 literals the script can emit**: 14 answered `factory` or `environment` with
  the code and `product` without it, and 16 read `product` at runtime, nine of them ours. The
  families now live in data, matched by the words a reason starts with (longest first, so
  `traceability: requirements-register.md has no R rows` is ours while `traceability: R-4 …` stays
  the product's); both roads agree on all 42 and `product` is down to 7. A reason no family matches
  is reported as `REASON_OWNER_UNCLASSIFIED` beside the reasons — the default owner is printed as a
  default, not as a reading (FR-41) — and `assess` sorts the list into `OWNER_ORDER`, which closes
  FR-20: the task's own terms come first. Held to the source by a test that reads the reason
  literals out of `check_delivery.py`, and by the mutation that drops one family.
- **FR-42 — the three controller actions with no move** (27.09, `story_run` + a new
  `environment_preparation.py observe` door). `observe_environment_job` now observes the recorded
  stand job and never starts a second one — waiting while its process lives, asking the person when
  the outcome is unknowable; `handoff_ready` takes the lease by code, because a code driver has no
  context window to roll over; `rollover_pending` refuses with each unsettled item and its own door.
  The check the rule asks for is a test: the actions are enumerated from the other side's own source
  (`controller._next_action_for_state` plus `story_step.where` — eleven and one) and every one must
  have a branch. Not yet exercised by a live run (FR-33).
- **FR-38 — nine roles told their checker's rules only after the work** (27.09,
  `references/ahead-cards.json`). All twelve have a card now, read out of the code that judges them,
  and `test_ahead_cards.py` holds the closed lists they quote to the modules that own them.
- **FR-2 — a refusal naming a door the refused party may not open** (27.09, `source_preflight.py`):
  it told the scout to run `ticket_adapter.py accept-gap`, which the guard closes to every role.
- **FR-4, FR-5 — the blocks of the controller, walked** (27.09, `design/controller-blocks.md` +
  `test_controller_blocks.py`). Every one of the 189 refusals has a named route, held to the source by
  a test. Two blocks that named a door which did not open (S1 sources, S3 plan rows) now read the
  person's word like S5 does; S5's own record of the pass was being written to a projection that is
  thrown away, so it never survived - that is fixed too, with a regression. What remains is the
  `command` rows: see above.
- **FR-6 — the filler question and the pasted refusal** (27.09, `human_text.py`, P13).
- **FR-7 — the same question asked twice, word for word** (27.09, `story_run.question_body_sha`).
  `take_answer` records the hash of the question's BODY - without the head that carries a timestamp
  and without the answer block that carries a path - and `ask()` compares against it. A boundary
  already answered comes back with what was said, when, and a request to say what should happen if
  that answer is followed and the block is still there. The round trip is the test: ask, answer,
  ask the same thing again (`test_human_questions.py`). The first version of the hash was itself
  broken - `re.S` in the head pattern ate the whole document, so every question hashed alike - and
  the round-trip test is what caught it.
- **FR-15 — the paths a role reaches for** (27.09, `brief_pack.file_lines`,
  `story_run.Driver.KNOWN_ARTIFACTS`). Re-measured before fixing: **129 of run 5's 644 reads
  missed**, not the 11 the plan carried, and the largest single cause was one file hunted at two
  levels. A declared input that is not there yet is now named in the brief instead of dropped, and
  `known_paths` carries thirteen artifacts by the registry's own spelling. What stays: roles also
  reached into the plugin about twenty times, which the guard refuses by design and the card
  already answers.
- **FR-28 — all nine measurers** (27.09 for the first five, then t-013/t-020/t-026,
  `experiments/measurers/test_measurers.py`): all nine are tested, and mutations that put the
  historical wrong numbers back turn it red (t-019 F4).

## Checked and clean

Worth recording, so the next walk does not redo it:

- **FR-14** — the four scripts whose stdout the driver parses (`controller.py`, `handoff_check.py`,
  `ticket_adapter.py`, `environment_selection.py`): every one returns immediately after printing its
  JSON, and the two the driver reads whole are wrapped in a `ValueError` fallback. No stray print.
- **FR-29** — no file in the package carries 0x07, 0x08, 0x0b or 0x0c, and since 28.09
  `selftest.py --lang` reads every file's bytes for them. Run 5's eaten `\b` was NOT the last one:
  writing the FR-10 walk put one into a test file, where the check that test was making then passed
  because its regex matched nothing, and the docstring of this very check ate another in the same
  hour. Both are gone, and what changed is that the next one is caught by the build instead of by
  eye. The rule's `Check` asked for exactly this and nothing enforced it package-wide.
- **FR-30** — `selftest.py --lang` green.
- **FR-41 (partly)** — `candidate_evidence.py` does this right: no evidence yields
  `assertion_status: "unknown"` with `valid: False`, never a positive.
- **FR-1, FR-2 — the twelve role contracts.** Every `## Refusals` bullet read names the exact digest
  to write and what goes in it: the scout's `qa-scout S1 halt · <path> · no diff · give
  --mr/--branch/--commit, or name an environment…`, the runner's `env_blocked` row with its `remedy`
  and the `env_probe.py` line that failed, the case critic's `done · verdict=reject … round cap, for
  gate A to decide`. The door is on the continuation line, which is why a first pass looking for a
  backtick inside the bullet read them as doorless — a false signal, twice over (the first sweep also
  lost its regex to shell quoting and reported "no Refusals section" for all twelve). FR-26 applies
  to this walk as much as to anything it measures.
- **FR-44** — held in both directions by `selftest.py --homes`, proven by probe in both directions.
