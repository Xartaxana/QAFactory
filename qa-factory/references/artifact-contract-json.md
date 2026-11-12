# Artifact contract — the story's state files

The JSON the factory keeps about ITSELF: where a story stands and what the project can do.
The artifacts a role writes are split by reader, so a dispatch carries the contract it needs
and not the other five: `artifact-contract-grounding.md` (context-manifest),
`artifact-contract-automation.md` (automation-manifest), `artifact-contract-run.md`
(run-report, triage), `artifact-contract-ledger.md` (ledger). Markdown artifacts and the closed
vocabularies are in `artifact-contract.md`. Types: `str`, `int`, `bool`, `[]` list, `{}`
object, `?` optional.

## `pipeline.json`

**Writer** the `qa-story` orchestrator after every stage. **Readers** `stage_guard.py`,
`ledger.py`, the validator, `qa-doctor`, the retro analyst.

```json
{
  "ticket": "QA-1",
  "parent_feature": "QA-EPIC-1",
  "size": "S",
  "environment": "local",
  "environment_pending": false,
  "implementation_source": "diff",
  "warnings": ["S0 vcs_api: <the script's own line, with its remedy>"],
  "retro_mode": "full",
  "stages": {
    "S0": {"status": "done", "started": "2026-09-11T09:00:00Z",
           "finished": "2026-09-11T09:02:00Z", "role": null, "digest": "preflight green"}
  },
  "gates": {
    "A": {"decision": "approved", "status": "approved", "at": "2026-09-11T10:00:00Z",
          "by": "human", "edits": []},
    "B": {"decision": "approved", "status": "approved", "at": "2026-09-11T12:00:00Z",
          "deliver_with_risks": null}
  },
  "stage_overrides": [
    {"stage": "S5", "match": "gate A is not approved", "decision": "<the person's words>",
     "at": "2026-09-11T10:05:00Z", "by": "human"}
  ],
  "halts": []
}
```

`ticket` str · `size` str (`XS|S|M|L|XL|XXL`; `XXL` is `sizing.py`'s recommendation the
person's word passes, never a block) · `environment` str|null · `environment_pending` bool? (`true` = no stand is
confirmed as usable: `environment: null`, or the name kept after a failed probe; checked before
S5/S6 — nothing is executed on a stand until it is confirmed or a person's word passes it —
and S1 says so in the same message as the source review) · `no_trace` bool? (`true` = an
experiment: nothing leaves the project, no tracker write and no merge request; absent = an
ordinary story) · `implementation_source`
str (`diff | current-code | ungrounded`) · `warnings` []? of str — one line per fact S0 must
not swallow (`vcs_api`, `data_cleanup`, `app_repo`, `tracker_write`), each carrying the
script's own remedy; written by the orchestrator, read by `gate_brief.py`, and every one of
them is repeated in the gate A message ·
`retro_mode` str? (`full | numbers | skip`; written at gate B, default
`full`) · `stages` {} keyed `S0`..`S9`, each
`{status: pending|running|done|halted, started: str?, finished: str?, role: str|null,
digest: str}` · `gates.A` `{decision: approved|declined|deferred|edit, status: same word, at:
str, by: str, edits: []}` · `gates.B` `{decision: str, status: str?, at: str,
deliver_with_risks: {reason: str}|null, orders: {}?, orders_due: []?, orders_settled: {}?, decided_seq: int?, decided_at: str?}` · `stage_overrides` [] of `{stage, match, decision,
at, by}` · `halts` [] of `{stage, reason, at, resolved: bool}`.

**One reader for the gate.** `controller.py` writes `approved`; stories written before it
carry `approve`, and gate B also `deliver` / `deliver_with_risks`. Nothing reads that field
directly: `contract.gate_approved(pipeline, gate)` accepts every spelling and every reader
calls it (`stage_guard`, `metrics_projection`, `factory_dashboard`, `external_writes`), with
`contract.gate_answered` for the separate question `archive_task.py` asks. Four private
copies of this vocabulary once cost TP1-15045 its entry into S5 with a green selftest.

`stage_overrides[]` is a person's recorded word passing a block of one stage, written only by
`waiver.py --stage <S> --block "<text>" --words-file <file>`. `match` names the
refusal by whole words (`contract.names_whole`), or is `*` for every block of that stage. `stage_guard.dispatch_errors`,
`stage_done.py` and `exit_gate.py` all drop a matching error and journal `gate_override`; the
refusals themselves print the ready command, and `refusal_registry.py --check` fails when a
refusal on the dispatch path has no recorded way through.

`parent_feature` is the parent's **key alone** (`QA-EPIC-1`, never with a title), written by
S0, `null` when there is no parent — the dashboard groups a feature's stories by this value.
`archived: true` hides a story from the dashboard and from `stage_guard --stories`, and is
written **only** by `archive_task.py`, on a person's word to `qa-doctor`.
`closed_at` (ISO time) and `closed_by` say the story is **closed**: gate B has a decision and
S8 is `done` (S9 may still run). Stamped by `stage_done.py` and the controller's projection;
a story from before 0.7.14 without the key reads as closed from those two facts, and a
`running` stage never reopens it. Only a person's word does: `controller.py --operation
release|rework` on a closed story writes `reopened_at` and `reopened_by_words`. Readers —
the stage guard's fallback, `--stories`, `archive_task --candidates` — ask
`hooklib.story_closed()` and never re-derive it (TP2-2534, I-92).

**Gate B orders (0.10.5).** What the person decided at gate B is carried out before the story is closed. `gates.B.orders` is
`{bugs, mr}` -> `due | done | cancelled | not_ordered` (`not_ordered` is the empty outcome: nothing was ordered, so nothing is
owed), `gates.B.orders_due` the names still `due`, `gates.B.orders_settled` `{order: {outcome, seq, at, dispatch_id?, ref?,
words?, reason_code?}}`, `gates.B.decided_seq` the number of the decision's event and `gates.B.decided_at` its time in UTC (the
form of `closed_at`). `mr` is `done` only with the record of the MR (`ref`, a link or an id). Writer: the controller's projection
only (`controller.gate_b_orders` / `orders_due`); the table of orders and their executors is `references/stages.json` S8
`gate_orders`, read by `hooklib.gate_orders`. Reader: `hooklib.story_closure(pipeline)` -> `{state: open|executing|closed,
closed_at, due}`; `story_closed()` is the time while `closed`, `""` otherwise. `executing` = gate B answered, S8 `done`, `orders_due`
not empty and no person's word (`reopened_at`) as late as `decided_at`; a damaged `orders_due` reads `executing` with `due:
["unknown"]`; a file with no `orders_due` (before 0.10.5) is read as above, by `closed_at` or by the two facts. `closed_at` is
stamped once, when the story becomes `closed` (the last settlement, else the decision).

**Checked** `ticket`, `stages` and `gates` are required; every stage id exists in
`references/stages.json` and its `status` is one of the four. `stage_guard` rule 1 reads
`stages[*].status`, rule 2 reads `gates.A.decision`.
A stage the report names while `pipeline.json` has it `pending` or `halted` is NOTED to the author, never refused: the validator reads the id, not the wording.
## `state/controller.json` — a dispatch that resumes another

**Writer** `controller.py` only (nobody edits this file; the full API is in
[controller-api.md](controller-api.md)). **Readers** `metrics_projection.py` (F05),
`factory_dashboard.py`, the retro.

A dispatch record created with `parent_retry` (or `relaunch_of`) carries two more fields:

`retry_reason` str — why the work is being done a second time, one value of the closed list
in [vocabularies.md](vocabularies.md) (`host_error:<code>` carries the host's code after the
colon). Stamped from the payload when the caller names a valid one, otherwise classified from
the parent's own recorded status and reason · `retry_words` str? — the person's own words when
the repeat was theirs.

**Checked** nothing refuses a dispatch for a missing `retry_reason`: a story started before
0.7.15 has none, and its readers classify the parent on the fly through
`contract.retry_reason_for`, so old and new stories read in one vocabulary.

## `requirements-readiness.json`

**Writer** `qa-requirements-tester`, S2. **Readers** `check_witness.py`, gate A.
`verdict` (`ready|blocked`) · `goal_summary` str · `aspects` {} each
`{status: ready|blocked|n/a, reason?}` · `open_questions` [] of `{id, question, source_says,
readings, severity: blocker|major|minor, owner_role: po_ba|dev_arch|qa}` · `register` {}
(`total`, `by_source`) · `confidence` (`high|low`). **Checked** by `check_witness.py`: verdict
consistent with the facts; a register built from AC alone while a parent feature exists
must set `confidence: low`.

A question carries the two things that let a person answer it in a minute instead of scrolling
past it: `source_says` [] of `{quote, where}` — what the sources say,
each with where — and `readings` [], at least two, each `{reading, from,
if_chosen}`. `from` is `<origin>` or `<origin>:<detail>` out of the closed list in
`contract.READING_ORIGINS` (`acceptance_criteria`, `description`, `comment`, `parent_ticket`,
`code`, `test`, `precedent`, `person`, `claim`, `attachment`: what a picture shows, e.g. `attachment:mockup.png`) — e.g. `acceptance_criteria:AC-4`. `if_chosen` says what the factory DOES with that answer: which Then is rewritten,
which row stays manual, which bug closes. The person's own wording is never listed as a third reading. A before/now question's readings carry
`claim`: `now` (the behaviour now is expected) and `before` (a regression). `id` is the question's ONLY id: plan rows (`question_refs`,
`if_answered`) and cases (`question_thens`) name it exactly (`Q1` is not `Q10`),
and a reading's letter is its position in `readings` (`a` first). **Checked** by the gate-A
rehearsal, not by the validator:
`contract.question_errors` names what a question lacks, `gate_preflight` raises it as one
`factory_fixable` finding per question (`qa-requirements-tester` rewrites it), and a story
whose readiness predates 0.7.16 is neither refused nor re-asked once a waiver names the
question id.
## `readiness.json` (project level)

**Writer** `scripts/readiness.py`. **Readers** S0 preflight, `qa-doctor`.
`schema_version` int · `capabilities` {} keyed `ticket_adapter`, `test_repo`, `app_repo`
(evidence of application code: a `code_repos[]` path that exists, or an `app_root` whose
`protected_app_paths` are on disk — a bare `app_root: "."` is not evidence),
`vcs`, `environment`, `external_writes`, `config_schema`, each
`{status: ok|missing|not_configured|unknown, owner: user|factory, note: str}`;
`config_schema` also carries `migration_hint` [] when the schema is stale.
**Checked** `readiness.py --require <caps>` exits 1 naming each missing capability and its
owner — that is the S0 halt text.
