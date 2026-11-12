# Architecture of the factory — the load-bearing invariants

This file is a map of the invariants the factory's architecture rests on. For each invariant it gives the carriers (the rule, the data and the code that hold it), the detector (what goes red when it breaks), one recorded breakage, and the check a change runs before it touches the invariant. It is not a rule book. The rules stay in `design/factory-rules.md` (FR-n), the owner's principles in `dev:PROJECT.md` (P1-P23), the symmetry axes in `dev:docs/SIBLING_MAP.md`, and the stage contracts in `references/` and `handoffs/`. This file points at them and says which of them hold one invariant together.

**Who reads it.** Any session or worker before changing the package (the sections the change touches), the designer drafting a package spec, and the critic on a package diff. Nothing loads it at runtime (FR-44). A one-line index is generated from the `**AR-n — title**` openers into `dev:docs/ARCHITECTURE_INDEX.md` and is never edited by hand.

**The rule it serves** (the development repository's CLAUDE.md): *A change to the package names the AR-n invariants it touches and keeps them; a producer and its readers change in one commit.*

**Fields.** Each invariant carries five fields:

- *Invariant*: what must stay true.
- *Carriers*: where it lives.
- *Detector*: what fails when it breaks, or `none — discipline` with the gap named.
- *Breakage*: a recorded case.
- *Change check*: what to verify and run before the change.

**Paths.** A path with no prefix is relative to the package root, and tests are `scripts/tests/<file>.py`. A `dev:` path belongs to the development repository and is not shipped. Functions are named in preference to line numbers; the line numbers given were read on main 41fb1346.

The owner set four goals on 20.10.2026, one section each:

- A: universality across projects.
- B: low friction with our code.
- C: one action, one way, everywhere.
- D: continuity between stages.

| Section | Invariants |
|---|---|
| A. Universality across projects | AR-1, AR-2, AR-3, AR-4, AR-5, AR-6 |
| B. Low friction with our code | AR-7, AR-8, AR-9, AR-10, AR-11, AR-12, AR-29 |
| C. One action, one way, everywhere | AR-13, AR-14, AR-15, AR-16, AR-17, AR-18, AR-19, AR-20 |
| D. Continuity between stages | AR-21, AR-22, AR-23, AR-24, AR-25, AR-26, AR-27, AR-28 |

## A. Universality across projects

**AR-1 — Closed variety is a data row, never a list in code.**
- Invariant: a closed set of values lives in one `references/*.json` table with one reader. Examples: tracker key forms, VCS delivery commands, test-file markers, assertion shapes, HTTP answer markers, external-agent call forms, build-identity methods, friction markers. A new project's value becomes a row, never a second regex at a site.
- Carriers: FR-13, P2. Each table and its reader:
  - `references/adapter-forms.json` with `scripts/adapter_forms.py`
  - `references/test-path-markers.json` with `scripts/test_files.py`
  - `references/detectors.json` with `scripts/assertion_detectors.py`
  - `references/http-answers.json` with `scripts/http_client.py`
  - `references/external-agent-calls.json` with `scripts/cost_capture.py`
  - `references/build-identity-methods.json` with `scripts/runtime_probe.py`
  - `references/friction-markers.json` with `scripts/friction.py`
  - `references/project-dependencies.json` (lock kinds, package manager to install command) with `scripts/dependency_drift.py` (`load_table`, `install_command`)
  - `references/user-path-failure-patterns.json` (the code shapes that swallow a failure) with `scripts/user_path_failures.py` (`load_patterns`)
  - `references/collect-loops.json` (which recorded state means a story looped: the repeat limits and the cap, limit and question records) with `scripts/collect_stall.py` (`load_loops`)
  - `references/request-call-patterns.json` (the call shapes of a request, the placeholder spelling) with `scripts/user_path_failures.py` (`load_request_table`)
  - `references/perturbations.json` (the failure kinds and the oracle of the S3 request rows) with `scripts/user_path_failures.py` (`perturbation_axis`, the one reader; S3 rows and S6 cells)
  - Axes 5 and 9 of SIBLING_MAP.
- Detector: `test_adapter_forms.py`, `test_test_files.py`, `test_assertion_detectors.py` and `test_http_client.py`. Gap: nothing catches a NEW hard-coded list at a new site; only the critic's duplication question does. Queued twins: `ticket_adapter.COMMAND_ADAPTERS` and `readiness.BUILTIN_TICKET_ADAPTERS` (B-435).
- Breakage: B-405 (30.09). The Jira key regex was hard-coded at six sites, so other trackers' keys were never found.
- Change check: grep `scripts/` for the shape of the problem (an id regex, a tracker or framework name, a tuple of words), not for the helper (FR-17). A new value goes into the table. If a project can bring a value the table lacks, the table is only a hint to a role (AR-2).

**AR-2 — Open variety is a role's judgment; code reports and leaves a move.**
- Invariant: some variety no table can close: layouts, id spellings, sources, frameworks, a person's or role's wording. The owning role or the conductor judges it. Code triggers on a field, a state or the presence of words, reports what it found, and never decides meaning.
- Carriers: FR-12, FR-13, FR-47, P1, P2; `handoffs/README.md` "When the judge is on" (a judged value never lifts a block).
- Detector: the census (AR-29): test_judgment_census.py; calibration check 41. Gap: FR-47's check ("run the script on a project shaped differently") has no gate, and nothing scans for phrase lists (FR-12).
- Breakage: FR-13's record. On TP1-13877 the contract knew only `TC-\d+` while the project wrote `TP1-13877_TC_001`. The automator spent about 35 calls reading factory code, then halted.
- Change check: for each decision moved into code, name what the role still decides. Add no regex over prose meaning. Run the changed script on one fixture shaped unlike the default; it must report, not halt.

**AR-3 — A project's facts live in its config or in the answer registry, with a default for every key.**
- Invariant: what varies per project is a config key or a strategy-file section, and onboarding asks for it; a fact only a person's answer can give (which role is a product role, which is not) also lives in the answer registry `records/project-knowledge.json`, whose one writer is `project_knowledge.py` and which is read config first, registry second. Every template key has `since` and `absent_means`. Migration fills missing keys and never touches a person's value, so an older project runs without re-onboarding.
- Carriers: `references/templates/config.json`; `references/config-keys.json`; `scripts/config_contract.py` (`migration_plan`); `scripts/readiness.py`; `skills/qa-onboarding/phases/p2-interview.md`; `dev:plans/builder-rules.md` rules 1 and 9; `records/project-knowledge.json` with `scripts/project_knowledge.py` (`state`, `record`).
- Detector: `test_config_migration.py`. Gap: nothing pairs a key read in code with its template row and interview topic; this is the reader side of AR-22.
- Breakage: none recorded for the migration itself (the reader-side case is under AR-22).
- Change check: one commit carries the template row, the `config-keys.json` row, a read with a default, and the interview topic that asks it. A changed note appends to `note_history`. Run `test_config_migration.py`.

**AR-4 — Nothing the factory writes is tied to one machine or one layout.**
- Invariant: a stored or printed path is relative to the project root and resolved through `scripts/runtime_paths.py`; a stored path is a hint, never a fact. A project may sit in a subfolder of a git repository. The one project-marker walk is `runtime_paths.nearest_project`.
- Carriers: FR-37; audit A20 (`audit_factory.a20_portable_paths`); `runtime_paths` (`project_for_task`, `known_paths`, `state_paths`, `contained`, `nearest_project`); axes 8 and 10.
- Detector: A20, `test_state_portability.py`, `test_resolver.py` K7, `test_runtime_paths.py` (`OUTSIDE_WALKS`) and `test_story_run_monorepo.py`. Gap: the five git-top readers have no one helper yet (B-437).
- Breakage: B-412 (07.10). The onboarding text assumed `qa-factory/` sits at a git root, so a subfolder project took silent branches.
- Change check: a new stored path goes through the resolver and gets a K7 row, and a new project walk calls `nearest_project`. Run the four tests above.

**AR-5 — The host is read through one adapter; no host naming is assumed.**
- Invariant: what differs between hosts (the role name, the session id, a role file's `tools:` line, receipt names; Claude Code and Codex) has one reader each. Hooks, guards and injection therefore fire for every role on every host.
- Carriers: `hooklib.role_name`; `host_adapter.role_tools` and `tools_line`; `scripts/session_identity.py` with `references/session-identity.json`; `host_dispatch.binding_names`; axes 19 and 20.
- Detector: the host-name probe in `scripts/install_smoke.py` (nightly `package-full`); `test_codex_tool_guidance.py` K7; `test_resume_story_isolation.py`.
- Breakage: in pilot TP1-13958, injection and the stage guard were silent for all 12 roles because the host named them `qa-factory:<role>` (`dev:plans/MEASUREMENTS.md:116`).
- Change check: a new reader of a host fact calls the one reader; a `startswith` or regex reader of a role file is refused. Run both tests.

**AR-6 — Data is read by every route; an LLM agent is never a read route.**
- Invariant: ticket, links, comments, attachments and repositories are read by API, git, SSH or browser in a light form. An agent only writes, and only where the project writes that way. What the factory's own probe proves unreachable is a reported gap, not a question. A person is asked only for access they can give, with three answers.
- Carriers: FR-50, P5 (D-06, D-0043); `scripts/ticket_adapter.py`; `references/mr-access-routes.md`; `references/adapters-read.md`; `question-prices.json` `s0.ticket_read`.
- Detector: `test_story_run_s0.py` K5 (no agent-read names in `story_run.py`, positive control); `dev:experiments/measurers/stage_compare.py` (manual).
- Breakage: TP1-15045 (01.10). An S0 that read the ticket through an agent lost 15 of 15 acceptance criteria, plus the attachments and comments.
- Change check: a new ticket field or source is read by the API route, and its snapshot is compared with an LLM run (`stage_compare.py <stage>`). Anything less than the LLM output stops the change (`dev:PROJECT.md`, acceptance rule 5).

## B. Low friction with our code

**AR-7 — Code is an instrument the role calls, never its substitute.**
- Invariant: the role runs our script, reads the report and decides what is missing. Code meeting the unforeseen says what it could not do and leaves a move. Code takes expensive actions off the model (P6). A step moved from a role into code is compared first with the role's output on a reference run.
- Carriers: P1, P6, FR-47, FR-51; `dev:PROJECT.md` acceptance rule 5; `dev:experiments/measurers/stage_compare.py`.
- Detector: the census (AR-29): test_judgment_census.py; calibration check 41. Gap: no gate asks for FR-47's "what the role still decides" or FR-51's spend before and after, and the reference compare is manual.
- Breakage: FR-47's record. The driver sent every repair as `test_defect` although the critic had named the real cause (B-007).
- Change check: name what the role still decides. Run `stage_compare.py <stage>` before the code lands. Report the stage's LLM spend before and after.

**AR-8 — A role is handed its paths and commands, never searches the plugin.**
- Invariant: every path the work needs is in `known_paths` or in the dispatch's lines, and the brief carries the commands. A role reads `references/` and its brief; reading other plugin files is refused.
- Carriers: FR-15; `runtime_paths.known_paths`; `scripts/brief_pack.py`; `scripts/inject_context.py` with `references/inject-map.json`; `guard_pre_tool.plugin_read_check` (`PT-plugin-read` in `scripts/refusal_registry.py`).
- Detector: the guard, registered under A24; the friction meter counts a miss (AR-12). Gap: nothing checks that a newly named path reaches `known_paths`.
- Breakage: FR-15's record. One run had 11 `Read` misses, and the whole-file reads that followed were a role's largest context cost.
- Change check: a path a phase or contract newly names joins `known_paths` or the brief in the same commit, spelled as the code writes it (FR-37).

**AR-9 — Every refusal names what it expected and a door its receiver can use.**
- Invariant: every refusal says what is wrong, what was expected, and the command or field that produces it. The door is in the refused party's own permitted set. A ban is never a dead end, and a person's word passes it, recorded.
- Carriers: FR-1, FR-2, FR-4, FR-57, P13, P15; `role_cli.refuse` with `references/role-commands.json`; `scripts/refusal_registry.py` (A24); `design/controller-blocks.md`, generated by `dev:tools/controller-blocks-gen.py`.
- Detector: A24 (`refusal_registry.py --check`); `test_controller_blocks.py` (blocks against source, both ways); FR-2's rule that a test opens each door.
- Breakage: FR-57's record. On TP1-13877 an interrupted write left a 3-row `test-plan.json`, and the guard refused any write over it; a person had to delete the file by hand. FR-2's record: on 29.09, 108 blocks named doors no test had opened.
- Change check: a new refusal arrives in one commit with its A24 row, its door and its person's-word route. Regenerate `controller-blocks.md`, then run both detectors.

**AR-10 — A check's requirement reaches the role before the work, in its fields.**
- Invariant: whatever judges a role's artifact is stated up front, as fields in the form, slice or card. The guard permits exactly what the rules permit. A value code can derive is written by code, so a role never copies what is on disk.
- Carriers: FR-11, FR-38, FR-39; `handoffs/*.yaml` (`expected_of_the_receiver`); `scripts/handoff_init.py`; `scripts/handoff_check.py` (`--fix`, `derived`); `scripts/contract_slices.py`; `scripts/guard_pre_tool.py`.
- Detector: `test_field_producers.py`; A9 and `selftest.py --slices` (a stale slice); FR-39 guard tests; `test_stage_joints.py` (`selftest.py --contracts`: the census `references/stage-joints.json` of every exit-gate family, blocking detector and S5 window gap, each with its producer and the file its role receives; a leg that does not exist is a declared gap under a shrink-only ratchet) and `test_stage_joints_12586.py` (recorded run-12586 artifacts fed to the checks that judge them). Gap: the walk covers the exit-gate families, the stage detectors and the window gap kinds; `gate_preflight` checks and the demands inside `check_case`, the register claims and `check_bug` are outside it (declared gaps), and the window rows are code-to-code (the fields a role supplies to the window are not walked).
- Breakage: FR-38's record. S3's rule lived only in code, and S3 took 176 turns and $12.83 over four attempts, against 51 turns and $2.53 once the card named the fields.
- Change check: a new check names its field and where the role reads it, in the same commit. A new required field enters the contract, the skeleton and the refusal text together.

**AR-11 — A role gets only the tools and the context its work needs.**
- Invariant: a role's tools are those its phase steps name. Its whole start load (charter, the project's CLAUDE.md, injection, packet, launch card, brief with its side files, form) is ONE number per role, summed by `scripts/role_load.py` in tokens, and stays under one threshold. Text added to a role's context removes at least as much.
- Carriers: FR-56, P14, FR-52; audits A2, A19, A22 (role start load), A23; `scripts/role_load.py`, `references/role-load.json`; `scripts/role_permissions.py`; `selftest.py --limits`; `dev:plans/builder-rules.md` rule 5.
- Detector: `test_audit_rules.py` and `selftest.py --limits` (CI `package-fast`).
- Breakage: FR-56's record. The scout's fixed prompt was 36.7K tokens with Bash and about 25K without.
- Change check: a new tool is named by a phase step. Added text comes with `role_load.py --all` before and after. Run both detectors.

**AR-12 — Friction is measured; code that makes a stage dearer is a defect.**
- Invariant: every run counts, at full context price, the turns our code costs a role. These are tracebacks, hook refusals, argument-shape errors, validator refusals of our own artifacts, and self-written helpers. A change that raises a stage's friction is a defect.
- Carriers: P11, P12, FR-51, FR-55; `scripts/friction.py` with `references/friction-markers.json`; `scripts/retro_numbers.py`; `dev:experiments/measurers/code_friction.py`.
- Detector: `test_friction.py` tests only the meter; `retro_numbers.journal_counts(...)["gate_block_classes"]` counts the exit-gate refusals of a run by class (`gate_block_class`, the first finding) and the retro says so when one class reaches `friction.same_class_gate_blocks` of `references/stage-joints.json` (`test_retro_numbers.py` R1-R6); beyond that, none — discipline. FR-55's before/after check has no gate, and the weekly calibration has no friction check. Finding: none filed yet (census t-1160 q2-b-gap).
- Breakage: on 0.7.6, S5 of TP1-15045 had 127 of 1,668 calls (7.6 %) refused by our own hooks (`dev:plans/MEASUREMENTS.md:110`).
- Change check: a change to a hook, guard, validator or a script a role calls names the roles it affects. It reports their `code_friction` before and after, or "not measured" as an open item.

**AR-29 — A code check judges data: shape, joins, presence; a role's judgment is judged by a tier above.**
- Invariant: a check in code judges the SHAPE of an artifact (keys, types, a form), its JOINS (every R-n reached, every Then bound,
  counts equal) or the PRESENCE of an input, a witness or a person's word. A check that classifies a role's judgment (is this a bug,
  is this case good, does this text support the requirement), closes a role's obligation by a closed-list reason, or refuses a role's
  output on its content is a breach. Such a judgment belongs to the role and is accepted on meaning by a tier above (a stage critic or
  the driver) with a witness; code may compute ADVICE for that acceptor and never a refusal. Protection of the application, secrets,
  external writes and the person's words is not judgment and stays a refusal (class `safety`).
- Carriers: P1, P3, P22, P27; FR-12, FR-13, FR-47; AR-2, AR-7; `scripts/tests/fixtures/judgment-census.json` with
  `scripts/tests/test_judgment_census.py`; `scripts/refusal_registry.py` (`sites()`, the one scanner of refusal sites);
  `references/role-load.json` (`process_ratchet_tokens`); `references/stages.json` (`advice`);
  `dev:tools/architecture_gate.py` (the `judgment:` line); `dev:docs/tasks/critic-diff-brief.md` question 11; axis 32 of
  `dev:docs/SIBLING_MAP.md`.
- Detector: `test_judgment_census.py` (every check unit of every `scripts/*.py` outside `scripts/tests/` has a census row with a class;
  whether a unit blocks is computed - refusal sites through `refusal_registry.sites()` and the declared blocking path - never hand-labelled;
  the counts of `word-list`, `meaning-proxy`, `meaning` and `safety` units, of blocking units per role, of `blocks_override` exceptions
  and of breaches only shrink); `role_load.py --all` against `process_ratchet_tokens`; the commit-msg `judgment:` gate; calibration
  check 41. Gap: the class of a unit is a human label; a unit labelled `shape` that reads meaning is caught only by the critic's
  question 11.
- Breakage: LOCAL-1 (0.10.8, 02.11.2026). The automator knew 8.5 hours before S7 that the price was asserted in a field `GET /api/cart`
  does not return, and still recorded 11 reds as `contradicts_requirement`: the gate needed closed obligations, and "the field does not
  exist, the case is defective" was not a move the form accepted (`dev:docs/tasks/specs/reviews/t-1672-local-1-whole-run.md:15-17`).
- Change check: for every check the change adds or alters, name its class (shape / xref / word-list / meaning-proxy / meaning / safety)
  and the owner it serves (data / judgment / intent). A new refusal on a role's content is not added: it becomes advice for the
  acceptor. Run `test_judgment_census.py`; a raised count is named in the verdict (AR-20).

## C. One action, one way, everywhere

**AR-13 — A fact with a reader function is read only through it.**
- Invariant: where the package has one reader for a file or fact, every consumer calls it. A second parser of the same bytes is a defect even when it agrees today.
- Carriers: axes 16 (`hooklib.read_json`), 19 (`host_adapter.role_tools`), 20 (`host_dispatch.binding_names`) and 21 (`grammar.split_cells`, written back by `grammar.escape_cell`; `project_decisions._cells` delegates to it). Axis 5 rows: `person_words.read`, `delivery_verdict.word_of`, `contract.bind_triage`, `critic_rollcall.scoped_verdict`, `bug_records`. The answer registry `records/project-knowledge.json` is read only through `project_knowledge.state` and `roster` (an account value only through `account_role` / `account_keys`). A story's sides and hold are read only through `contract.story_sides` and `contract.awaiting`, its provisional rows through `contract.manifest_provisional` (and `acceptance.pending_instances` for the pending instances); `report_facts` counts them through these, reads a dispatch's repair cause through `controller.repair_cause` and the journal's money through `factory_dashboard.journal_records` (with `driver_journal.root_charged`), and parses none of them itself. Two raw reads remain, for want of a reader: `pipeline.sides_unknown` and `request_binding.purpose` (`bind`).
- Detector: `test_read_json.py` G5, `test_codex_tool_guidance.py` K7, `test_bug_records.py`, `test_words_doors.py`, `test_one_source_per_fact.py`, `test_grammar.py` (the cell reader), and the clone ratchet (growth only). Gap: a reader with no census is held only by the critic.
- Breakage: CX1-12 (20.10). Six readers take the critic's word from the whole `critic-findings.md` instead of through `scoped_verdict` (queued CX2-25).
- Change check: grep SIBLING_MAP for the file or fact. If an axis names a survivor, call it. Grep the package for the same shape (`json.loads`, `split("|")`) with a positive control. A new reader joins the axis row.

**AR-14 — One artifact, one writer.**
- Invariant: every artifact a stage declares has exactly one writer, plus that writer's own machinery. Anything else asks the owner's command or writes its own file.
- Carriers: `references/artifact-writers.json`; `references/stages.json`; `scripts/stage_done.py` (`pipeline.json`); `person_words.write_words` (`state/words/`); axis 8's one-writer records; `state/collect-gaps.json` with `scripts/collect_gaps.py` (`record` is the only writer, `read` the only reader); `records/project-knowledge.json` with `project_knowledge.record` (the only writer; `guard_pre_tool` closes its write commands to roles).
- Detector: `test_artifact_writers.py` (every declared artifact has an existing owner). Gap: a second writer in code is not detected (B-176 open).
- Breakage: TP1-13797. The ticket probe wrote its receipt into `source-inventory.json` and erased the scout's sources; nothing said who owned the file.
- Change check: a new artifact gets its `stages.json` output and its writer row in one commit. Code writing into another's artifact calls the owner's command instead.

**AR-15 — A shared problem is solved at one survivor and wired everywhere.**
- Invariant: a problem that recurs at many sites has one survivor function. Examples: shell-command words, the story's location, "is this a test file", outbound HTTP, safe URL, secret patterns. A hole is fixed in the survivor and every site calls it.
- Carriers: FR-17, FR-54, P10; `hooklib.walk` (axis 11); `runtime_paths` and `hooklib.story_root` (axis 8); `test_files.is_test_for` (axis 9); `http_client.fetch` and `http_client.safe_url` (axis 5); `project_knowledge.py` for a person's answer kept across stories (the "decided once" road at gate A and gate B); `scripts/walk_session.py` `capture_cited` (the one cited-capture check), `scripts/manual_capture.py` `http_call` (the HTTP step of the walker, twin of the screen step) and `controller.py` `first_look_continue` (the one operation that carries the person's word on the first look); `report_facts.knowledge_use` (the one reader of the usage of what the factory knew: registry facts and first-look rows).
- Detector: `test_hooklib_scan.py`, `test_run_forms.py`, `test_resolver.py`, `test_test_files.py`, `test_http_client.py`; open twins are queued per axis (B-431, B-434, B-437, B-447, B-450). Two secret-pattern tables are still queued.
- Breakage: B-408 (07.10). Six sites made outbound HTTP calls without a User-Agent, and a firewall's 403 page was read as "token lost". FR-17's record: `node_ids.py` was wired into three of four sites.
- Change check: grep for the problem, not the helper (FR-17), and list every site. A site that cannot call the survivor is named on its axis. A new survivor gets an axis in the same commit.

**AR-16 — Every text a person reads goes through one question form.**
- Invariant: every text a person reads obeys `references/human-questions.md`: gate and boundary questions, halts, the factory-defects section and the S9 question. It uses the story's words and asks one closed question, each option priced for the factory, the person and the story. Code reads back only offered tokens; a free answer goes to the conductor.
- Carriers: FR-3, FR-6, FR-7, P9, P22; `scripts/human_text.py` (`problems`, `price_problems`); `references/question-prices.json` (one loader in `scripts/no_move.py`); `Person` -> `ask` -> `Driver.take_answer` in the driver set (`scripts/story_run.py`, `scripts/driver_*.py`; axis 5); `scripts/gate_brief.py`.
- Detector: `human_text.py --selftest` (in `selftest.py`); `test_human_questions.py`; `test_gate_question_form.py`; A27. Gap: the check reads the form, not the reader (FR-6).
- Breakage: FR-6's record. On TP1-13877 all six recorded questions passed, among them a Cloudflare HTML page.
- Change check: a new question is a `question-prices.json` key, goes through `Person` / `ask` / `take_answer` and passes `human_text.problems`. A question asked again changes its text (FR-7).

**AR-17 — A state code has no move for goes through one seam to the conductor, which settles it before it asks.**
- Invariant: a state with no move goes through `Driver.no_move`, and only `Driver._ask_conductor` calls the conductor. The conductor gets the problem, the evidence and priced options. It runs the chosen one with existing commands and records a finding. It is never called to run a routine command. Before any question to a person the conductor reads what the code left (records, logs, notes, the refusal's evidence) and resolves what it can; what the code recorded is evidence for the investigation, never the text of the question. A question carries a class of `references/person-owned.json` (`why_person`) and what was read (`checked`); the seam refuses one without them once, then falls to its priced fallback with a factory defect. The interactive road records the class with `waiver.py --why-person`; a word without it is recorded and counted (calibration check 38).
- Carriers: P3, P22, FR-42, FR-48; `Driver.no_move` and `Driver._ask_conductor` (the driver set: `scripts/story_run.py`, `scripts/driver_*.py`); `scripts/no_move.py`; `references/person-owned.json` with `scripts/person_owned.py` (the one reader; `no_move.validate_options`, `Driver.pass_to_person`, `waiver.main` call it); `state/driver-questions.jsonl` keys `source`, `why_person`, `checked`, `class_check`; `references/conductor-actions.json`; `references/conductor.md`; `references/halts.md`; `skills/qa-story/phases/s4.md` (the role, twins and confirm cards: free words go to the conductor, code reads only `accept` / `myself` / `ask again`).
- Detector: A27 (`audit_factory.py --no-move`, via `test_audit_rules.py`) against the shrink-only `NO_MOVE_BASELINE` (`NO_MOVE_BASELINE_MAX = 102`, :1582); `test_no_move_seam_n1_n9.py`, `test_no_move_seam_n2b_n15.py`, `test_no_move_seam_sites.py`, `test_no_move_seam_k4s.py`, `test_no_move_seam_c26_g27_f2.py`; `test_person_owned.py`; `test_person_owned_paths.py`; `test_conductor_investigates_first.py`; `person_owned.py --share` read by calibration check 38 (`dev:PROCESS/WEEKLY_CALIBRATION_PROTOCOL.md`).
- Breakage: FR-48's record. The conductor held 76 sessions in one run, 21 of them ($9.01) spent parsing words. P22's case: at gate B, "automation needs rework" had no executor (`dev:plans/piles/gates-and-words/findings/20261009-gate-b-pravka-avtomatizacii-bez-ispolnitelya.md`). P22's second case: LOCAL-1 (02.11.2026), the probe record and the UI login were the factory's own and still reached the person as questions (`dev:plans/piles/release-next/findings/20261102-dirizhyor-sprashivaet-cheloveka-ne-razobravshis-sam.md`).
- Change check: a new driver stop goes through the seam or carries `# remains: <reason>`. A baseline raise is named (AR-20). A new conductor action is a data row. A new question site names its class from `person-owned.json` (a code route: its `code_routes` row); a phase line that tells the orchestrator to ask a person about a recorded state carries `person-owned: <id>` and a row in `test_conductor_investigates_first.SITES`. Run `test_person_owned.py`, `test_person_owned_paths.py`, `test_conductor_investigates_first.py`.

**AR-18 — Detectors and refusals have one output shape and one reader.**
- Invariant: a detector prints `REJECT — N finding(s)` with one line per finding, capped by bytes with the full list in a file, and is read only through `scripts/detector_verdict.py`. A refusal's lines are built once (`story_run.refusal_lines`). A combined controller refusal lists every problem (`Controller._raise_all`).
- Carriers: axis 17; `detector_verdict.parse`, `refusal_text`, `render`; producers `s5_precheck.py`, `planning_contract.py`, `critic_rollcall.py`, `check_coverage.py`, `check_witness.py`, `grounding_table.py`, `exit_gate.py`.
- Detector: `test_detector_verdict.py` (every producer prints the shape); `test_exit_gate_scope.py`; the clone ratchet.
- Breakage: 16.10 (critic t-894). Three parsers read the `executor unavailable:` prefix in three different ways (`dev:plans/piles/conductor/findings/20261016-tri-parsera-prefiksa-executor-unavailable.md`).
- Change check: a new detector prints the shape and joins the producer list. Consumers parse only through `detector_verdict`. A contract change updates the reader, every producer and the test in one commit.

**AR-19 — Stage twins change together, named by the map.**
- Invariant: logic repeated across stages is listed with every side's files. Examples: the repair loop at S4, S5 and S7; code-only closes via `Driver.close_by_code`; the stage before gate A and gate B; the gate A and B cards; a skill phase and its driver twin. A change to one side names the others and changes them, or says why not.
- Carriers: FR-54, P10, P12; axis 5 (the twin list); `dev:docs/factory-map/qa-factory-paths.md` (a 28.09 snapshot); `design/factory-map.md`, named by FR-54, is absent (B-051).
- Detector: none — discipline. The critic's class-wide-completeness question carries it; `dev:tools/mechanism_gate.py` does not cover package paths. Finding: B-051; `dev:plans/piles/forge/findings/20261020-opisanie-arhitektury-fabriki-i-pravilo-ne-lomat.md`.
- Breakage: FR-54's record. The repair cause was hard-coded identically at S4, S5 and S7; S0 ignored the person's word, and S9 halted `--until end`.
- Change check: grep axis 5 for the touched function and name each twin in the report and the commit. A new twin joins axis 5.

**AR-20 — Shrink-only ratchets only shrink; a raise is named in the verdict.**
- Invariant: census baselines never grow silently. A diff that adds a site and raises its own row is green in-tree, so each raise is named row by row in the critic verdict. A stale row is refused, never shrunk silently.
- Carriers:
  - Axis 18.
  - `audit_factory.py`: `NO_MOVE_BASELINE` and `ANCHOR_FLOOR`.
  - `test_runtime_paths.py`: `OUTSIDE_WALKS`.
  - `fixtures/env-facts-baseline.json` and `fixtures/driver-layers.json`.
  - `dev:tools/dup_ratchet.py` with `dev:tools/dup-baseline.json`, and `dev:tools/lint_ratchet.py`.
  - `references/stage-joints.json` `ratchet` (declared gaps; only node F6-51 may lower it), checked by `stage_joints.py --check`.
  - `scripts/tests/test-layers.json`: `quarantine` shrinks only by `dev:tools/test_quarantine.py purge`, and `pin_holds` only shrinks once files have entered the quarantine. A `keep` row leaves only through that tool. The rows naming detector tests in this map change only in a phase-2 commit that names the replacement.
- Detector: both ratchets' `--check` (CI `forge-check`); `dev:tools/test_quarantine.py check` in the same job; calibration check 35 (b); critic-diff-brief question 9.
- Breakage: B-420. Pyflakes findings brought in by merges held CI red on main until 07.10 (`dev:plans/builder-rules.md` rule 7).
- Change check: list every row added or raised (key, old -> new, reason). A new ratchet joins axis 18 and question 9 in the commit that creates it.

## D. Continuity between stages

**AR-21 — What a stage gathers travels whole in its handoff.**
- Invariant: each of the twenty handovers has one file in `handoffs/` that is both contract and form, so the receiver hunts for nothing. A form states the size of what it hands over, and the receiver confirms what it read (`inputs_read`). The next stage never gathers it again, and nothing is dropped between contracts.
- Carriers: P4, FR-49; `handoffs/index.yaml` (resolved by `handoff_init.py`); `handoffs/vocabulary.yaml`; `scripts/handoff_check.py`; `scripts/story_step.py` (`start`, `finish`); `references/stages.json` (`required_outputs`, enforced by `exit_gate.py`); `work/first-look.yaml` (the first look, one YAML, input of S3-S7 and of the two critics' briefs; its fields are read by FL-4/FL-6 or counted by `report_facts.py`, `stand_needs` and `gaps` included).
- Detector: the `handoffs/README.md` rule that every field is code-checked or read by the receiver, asserted by a test; `test_field_producers.py`; `dev:experiments/measurers/check_all_contracts.py` (manual, on a real run).
- Breakage: TP1-13797. The tester read part of `impl-diff.txt` and wrote 14 requirements where 21 existed, and every later stage was right about the wrong 14.
- Change check: a newly gathered item names its downstream reader or is declared terminal (FR-49). A new handover gets its `index.yaml` row in the same commit.

**AR-22 — Every field read has a producer; every field produced has a reader.**
- Invariant: the walk runs both ways. Whatever a script, role or phase reads has a producer the factory can run: a field, config key, strategy paragraph or interview answer, produced by an interview question, a permitted tool or a deriver. What is produced is read downstream or declared terminal. Removing or rewording a producer removes or re-homes its readers in the same commit.
- Carriers: FR-5; FR-11; FR-49 (its check walks producer -> reader only, `design/factory-rules.md:223`); `references/field-producers.json` with `handoff_check.DERIVERS` (738 required handoff fields, 28 tool-made); A13 `REQUIRED_FACTS` (`scripts/audit_factory.py:758`, topics 1, 2, 3 and 7, run against a project's state).
- Detector: `test_field_producers.py` covers the handoff contracts only; `test_stage_joints.py` walks the producer and the demanded token of every exit-gate family, blocking detector and S5 window gap (direction B: a producer entry names a role or a defined function; direction C: a demanded token is named in a file its role receives). Elsewhere: none — discipline. Nothing walks reader -> producer for interview answers read from `config.json` or the strategy files, and A13 skips topic 4. Finding: `dev:plans/piles/forge/findings/20261020-opisanie-arhitektury-fabriki-i-pravilo-ne-lomat.md`.
- Breakage: commit 28fc7170 (18.09.2026) dropped "main risk areas" from interview topic 4. Its readers stayed and starved for a month (node OH1-10): `scripts/sizing.py` (`strategy_area_state`, which reads the `**P1 areas.**` label and says "weight bump unavailable"), `skills/qa-onboarding/phases/p4-generate.md:431` and `references/automation-candidacy.md`.
- Change check: before removing, renaming or rewording an onboarding question, a `references/templates/config.json` key, a strategy heading or label, or a contract field: grep its name (for example `P1 areas`) case-insensitively over `scripts/`, `agents/`, `skills/`, `references/` and `handoffs/`, with a positive control. Every hit is a reader, and readers change with the producer. Run `test_field_producers.py`.

**AR-23 — Every required list or field declares its empty outcome.**
- Invariant: every required list, stage output and tool field has exactly one home for "empty": a contract `null_outcome`, a `never_empty` row with its guard, or a `pending` row that only shrinks. A null result is a recorded completed state, not an escalation.
- Carriers: FR-23; `references/null-outcomes.json`; `scripts/null_outcomes.py`; `Driver.close_by_code` (S6, S7); `work/first-look.yaml` (`null: <reason>` with `rows: []` and one gap line) and `state/first-look-attempt.json` (the attempt and its outcome; none is "no attempt", never a settled one).
- Detector: `test_null_outcomes.py` (`selftest.py --contracts`, CI `package-fast`).
- Breakage: FR-23's record. Once the gate forbade a branch, a push and an MR, the delivery step could only stop and ask, with nothing to ask.
- Change check: a new required field or list is declared in the commit that adds it, never born `pending`.

**AR-24 — A person's words reach whatever acts on them, whole.**
- Invariant: an answer is recorded through one reader and one writer and reaches, in full, the executor the refusal named. Everything a gate decision can order has an executor. A pass records the block, the words and the speaker. A pass over a factory-owned block becomes a finding.
- Carriers: FR-4, FR-8, FR-9, P13, P22; `scripts/person_words.py` (`read`, `door`, `write_words`); `Driver.words_file` (a second writer, queued); `handoffs/gate-a-to-automator.yaml` and `handoffs/gate-b-to-delivery.yaml`; `scripts/waiver.py`; axis 5.
- Detector: `test_words_doors.py`. Open doors are queued as B-343, B-365 and B-387.
- Breakage: FR-8's record. Four conductor sessions journaled `"words": false` while 1,900 characters of the answer sat on disk.
- Change check: a new recording command takes `--words-file` through `person_words.read` and prints `door()`. Follow each answer to the command that consumes it.

**AR-25 — Every recorded state has a way out, and every returned state a move.**
- Invariant: every recorded state has a command that reverses it. Every state the other side can return has a move here, or a refusal that names who acts. Stage run marks survive a second close.
- Carriers: FR-40, FR-42; `design/state-exits.md` (with a row per state of the answer registry `records/project-knowledge.json`); `controller.STAGE_RUN_MARKS` (`controller.py:539`); `scripts/manifest_put.py --fragment {retracted_instances}`.
- Detector: `test_state_exits.py` (states enumerated from source); `test_controller_state.py` P1-P4; `test_awaiting_state.py` (no held story reaches S6 or gate B; a stopped story is terminal).
- Breakage: FR-40's record. A stale `tests[]` row could never leave. FR-42's record: `resolve_return` had no move.
- Change check: a new state names its reversing command and gets a `state-exits.md` row, and a new returned state is matched to a branch.

**AR-26 — Requirements, not code and not AC, are the unit from S2 to delivery.**
- Invariant: completeness is counted by the S2 register's requirements through the plan, the cases, the binding and the verdict. An expectation comes from a requirement, never from the implementation. If it is unconfirmed, it stays `unresolved: expectation_unconfirmed` and is reported as a gap.
- Carriers: P20, P23, FR-18, FR-21, FR-58; `contract.ORACLE_CUTOFF` (`contract.py:394`); `then_oracles` in `scripts/validate_artifacts.py`; the "requirement" row of axis 5.
- Detector: `test_oracle_provenance.py` and `test_validators.py`. For the wording: none — discipline. The census `dev:docs/tasks/specs/reports/t-928-ac-vocabulary-census.md` is re-run by hand.
- Breakage: FR-58's record. On cmp2 of TP1-15045 (01.10), R-17 took its expected 403 from the implementation diff; before the refactoring, the behaviour was 400.
- Change check: text that counts completeness says "requirement", and a new expectation names its oracle. Re-run the census grep on the files touched.

**AR-27 — A finding, bug or gap reaches the report under its own owner.**
- Invariant: a discrepancy has a road to `bugs/` even when no test fails. Every blocking reason names an owner, and the factory's own reasons are reported, never asked. The verdict has three words and one reader. "Left with you" lists every handed-over item and the regression scope.
- Carriers: FR-3, FR-19, FR-20, FR-21, FR-22, FR-35, P21; `scripts/check_delivery.py`; `delivery_verdict.word_of` (:221) with `references/delivery-verdict-kinds.json` (an unknown kind means `no`); `scripts/bug_records.py`.
- Detector: `test_bug_records.py`. Gap: a bug draft's identity is not pinned across its two homes.
- Breakage: FR-22's record. AC7 was ordered filed at gate A, and nothing filed it, because the only road ran through S7, which had no failures.
- Change check: a new reason family joins the owner vocabulary (FR-19). A new verdict reader calls `word_of`. A new discrepancy source names its road to `bugs/`.

**AR-28 — An unknown never becomes a pass at a stage boundary.**
- Invariant: a gate that cannot read its input (missing, unreadable, no evidence, an unknown word) names what it could not establish and asks whoever can know, or takes its declared safe default. It never passes. A measure with no evidence prints `unknown`.
- Carriers: FR-4, FR-41, FR-59; `references/gate-registry.json` with `scripts/gate_registry.py` (A26); `hooklib.read_json`, which returns a default on a missing file.
- Detector: A26 (`gate_registry.py --check`) and `test_gate_registry.py`; `test_sides_ledger.py` (no `on_substitute` or `sides_unknown` input reads `passed`, for tests and walks); `test_first_look_provisional.py` (a green on a substitute or behind an open marked locator is no pass; an unreadable first-look record is a gap line); `test_report_facts.py` (a counter with no carrier prints `unmeasured: <why>`, never 0: the first-look and knowledge counters). In the forge, check 44 of `dev:PROCESS/WEEKLY_CALIBRATION_PROTOCOL.md` reads the `sides_measure` counters of `report_facts.py --json` (a story with a non-real side whose report says `yes` must be 0). Gap: A26 sees only verdict-word comparisons, not a pass on input read as `{}`. Finding: `dev:plans/piles/conductor/findings/20261016-gejt-s6-s8-prohodit-molcha-bez-manifesta-avtomatizacii.md`.
- Breakage: 16.10, in the same finding. The S6-S8 gate passed silently with no `automation-manifest.json`.
- Change check: the spec states each new gate read's behaviour on missing, unreadable and empty input, and a test pins it. A new gate is a registry row with its unknown branch.

## How a change walks this map

1. Grep this file for each changed file and function. Every AR-n that lists one as a carrier is touched.
2. Name those AR-n in the spec, the report and the commit (the form is set by the CLAUDE.md rule). A change that touches none says so in one line, with the reason. An invariant the change cannot keep is stated, never reworded.
3. Apply the producer-reader rule in both directions (AR-22; FR-5, FR-11, FR-49). Anything removed, renamed or reworded gets a grep of its readers, with a positive control. A new reader names its producer, and both sides change in one commit.
4. Walk `dev:docs/SIBLING_MAP.md` for each touched function (FR-54). Each twin is changed or queued with a pointer.
5. Walk the FR sections the change touches (`dev:PROJECT.md`, acceptance rule 1).
6. Friction (AR-12): give `code_friction` before and after for the roles touched, or "not measured".
7. Ratchets (AR-20): name every raised row.
8. Run each named AR-n's detector. For a `none — discipline` detector, answer its change check in words.
9. The critic asks four questions. Which AR-n is touched but not named? Is each change check done? Was the producer-reader walk controlled? Is every raise named?
10. A new invariant (a single reader, table, handover or seam) gets an entry here in the same commit, and the index is regenerated. The index stays at or under 3 KB: past 30 entries, a new invariant merges into its nearest entry.
