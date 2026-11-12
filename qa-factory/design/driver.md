# The driver — `scripts/story_run.py`

The orchestrator model of `qa-story` is replaced by a loop in code. Between two boundaries
of the pipeline there is nothing to decide: `story_step.py where` says what is next, `start`
registers the dispatch and prints the prompt, the role runs as its own headless session,
`bind` and `finish` record it. The driver calls those in the order the phase files fix, asks
the person at the two gates (and at a halt, the S1 source review and the S9 retro question),
and hands what it cannot resolve to a **conductor** — a fresh `claude -p` with
`references/conductor.md` as its system prompt — before it hands it to the person.

## Running

```text
python <plugin>/scripts/story_run.py --task <T> [--until gate_A|gate_B|end] [--model sonnet]
       [--host claude|codex] [--plugin-dir <plugin root>] [--project <project root>]
       [--mr <url|id> | --branch <name> | --commit <sha>] [--ungrounded] [--ticket-file <path>]
       [--side <name>=<reality>] [--reference <side>=<stand>] [--env <stand>] [--branch-suffix <s>] [--max-boundaries 80] [--dry-run]
python <plugin>/scripts/story_run.py --task <T> --answer <file with the person's words>
```

Run it from inside the project (the folder that holds `qa-factory/config.json`) or pass
`--project`. Every role runs with that folder as its cwd, `CLAUDE_PROJECT_DIR` set, and
`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`. The `claude` executable comes from `PATH`;
`STORY_RUN_CLAUDE=<path>` replaces it (a `.py` path is run through the same interpreter —
the tests use a stub that prints canned JSON).

### The Codex host

`--host codex` (or `"driver": {"host": "codex"}` in `qa-factory/config.json`) runs the same loop
with the Codex CLI in place of `claude -p`. Nothing of the loop is host-specific but the call
itself: `story_step.py start|bind|finish|where`, the handoff check, the conductor, the in-flight
record, `dispatch_liveness`, the journals and the saved results are the same code and the same
files. The `codex` executable comes from `PATH`; `STORY_RUN_CODEX=<path>` replaces it the way
`STORY_RUN_CLAUDE` does. Verified against `codex exec --help` and `codex exec resume --help` of
codex-cli 0.158.0 and the event names in its binary; NOT against a live run yet - the first live
story is the proof, as it was for 0.8.0's driver (a live-evidence row of the batch).

| On Claude | On Codex |
|---|---|
| `claude -p --agent qa-factory:<role> --append-system-prompt-file <layer> --output-format json --model <m>`, the prompt on stdin | `codex exec --json -C <project> [-s <sandbox>] --skip-git-repo-check -m <model> [-c k=v ...] -`, the prompt on stdin |
| `claude -p --resume <session id>` | `codex exec resume <thread id> --json --skip-git-repo-check -m <model> [-c ...] -` (the subcommand takes `--json` but not `-C` or `-s`: the thread keeps its own cwd and sandbox) |
| the role's definition is `--agent`, the rule layer is the appended system prompt | both travel in a FRESH prompt: the role file's body under `# Factory role instructions: <role>` (the one function the Codex hook also reads, `inject_context.role_block`, without its Desktop tool block), `# Rule layer (your system prompt)` (the same file the driver builds), `# Task`; a continuation gets the words alone - the thread holds its role |
| `session_id`, `result`, `num_turns`, `total_cost_usd` of the result record | `thread_id` of `thread.started`; the LAST terminal event decides: `turn.completed` is the text of the last `agent_message` item, `turn.failed` is ITS message as the result (what the infrastructure rows read; the agent text is kept apart as `partial`, never the result); the count of `item.completed` events (a session that ran one command and answered has two, so `worked` means what it means on Claude; reasoning items count too, which errs toward continuing a session); `usage` of `turn.completed`, summed, in the result and the journal row |
| `--model` default `sonnet` | `--model`, else `default_model.codex` of `references/driver-infra.json` (the latest Terra, `gpt-5.6-terra`: the owner's word 20.10.2026, data not code); `-m` is always passed; the journal's `model` names the one used |
| `total_cost_usd` is the CLI's own number | the CLI reports no price, so the driver works the call's out: `usage` valued by `cost_capture.value_usage` (the one pricer; `references/model-rates.json` or the project's `cost.rate_overrides`, the same list as everywhere; the long-context tier chosen by the call's sum of input tokens, as for one Claude request). `total_cost_usd` keeps ONE meaning in every row of every host, the RUNNING total of the thread (the earlier rows of the same thread in the journal, plus this call); the call's own price is `call_cost_usd`; `cost_basis` is the label `estimate: default tariffs (references/model-rates.json); long-context tier by the turn's sum`, which the dashboard's story card and the retro print once. A call with no price (no tariff for the model, no usage, a count that cannot be counted) has `call_cost_usd` `null`, `total_cost_usd` as the thread had it (`null` for a first call) and a `cost_basis` that says `price unknown: <why>` and that the thread's total does not include the call - never `0` |

What a role's thread is on Codex is what a session is on Claude: **one dispatch, one thread**. A
fresh dispatch (`story_step start`, a rework, a relaunch, an S5 window) is a fresh `codex exec`;
the SAME dispatch goes on in its own thread when the driver resumes it (the handoff repair, the
person's words after a halt, a call the service cut off, a transient retry) - the same rules, in
the same code (`run_claude`, `handoff`, `resume_role`), with `resume_reason` in the journal. A
continuation answered in ANOTHER thread is an error of that call (`subtype: resume_mismatch`), never
a new session of the dispatch: the driver's own continuation then takes the one fresh attempt with
the whole prompt, a caller's continuation gets the error. No rule here says "always fresh" and none
says "always the same thread": the TP2-2406 analysis measured 20 of 24 follow-ups as justified
continuations of an interrupted dispatch and the 4 cross-scope reuses (a second S5 window on the
automator's and the critic's threads) as the ones not justified by continuity; the dispatch boundary
is exactly that line.

What the driver removes on Codex is the waiting: the desktop host's `spawn_agent` returns at
once and the orchestrator model must poll `wait_agent` (TP2-2406: 501 `wait_agent`, 403
`wait` and 26 `sleep` turns, 129.9M input tokens, 46% of the orchestrator's input, at a full
context each). The driver waits on the child process in `launch` (`Popen.communicate`): no model
turn is spent while a role runs, on either host.

Config: `driver.host` (`claude` | `codex`; `null` or absent is no word, any other value is compared
after a strip, with its case, and refused with the hosts listed, exit 1), `driver.codex.sandbox`
(`read-only` | `workspace-write` | `danger-full-access`, passed as `-s` on a fresh call; absent, no `-s`
and one `note:` line - the project's own `.codex/config.toml` rules, as INSTALL.md sets it up),
`driver.codex.config` (an object of `-c key=value` overrides, sorted by key; a string value that must
reach Codex quoted carries its own quotes, `"approval_policy": "\"never\""`). A key of the wrong type is
ignored with one `note:` line. A story keeps its host: the state records `host` when a Codex session is
stored, and a run of the OTHER host over a story that holds sessions is refused at start naming the door
(`--host <the host it started on>`, or a new story); a state with sessions and no `host` is a Claude story.

Start refusals (exit codes): an unknown host - 1; the Codex host with no `--model` and no
`default_model.codex` in the data file (an older file) - 2, naming the key and the file, never a
silent host default; sessions of the other host - 1.

Known gaps, named rather than hidden: `codex exec` has no `--allowedTools` and no `--max-turns`, so
a role's tool surface is the host's and the conductor's turn count is unbounded; a role whose agent
file lists no Bash (`qa-test-strategist`, `qa-case-critic`, `qa-case-designer`) runs as is and the gap
is a `kind: note` row of `driver-runs.jsonl` for its dispatch (the CLI block of its tools is a later
node); whether the plugin's hooks fire inside `codex exec` is not verified - a session whose hooks
left no package receipt is asked about by `package_check`, as any session is, and `go on` records the
word; the rollouts (`.jsonl.zst`) are not read by the driver. A stream with no terminal event, a
stream that is empty, or a line that is no event is named in the journal (`kind: note`) and the call
is `unclassified` to the infrastructure rows (no retry, no stop), its price `price unknown`.
The infrastructure rows for the Codex CLI (`references/driver-infra.json`, `codex_*`: a login refusal, a
usage limit, a broken stream) carry `hosts: ["codex"]` - a role's own text on Claude never reads as one
- and are `unmeasured` until a run records their wording; a `turn.failed` message is the result text
those rows read. The long-context tier of a tariff is not applied to a Codex call (one `turn.completed`
carries a turn's sum, not a request's size), so a call that held a request over the threshold is priced
low - the label says estimate.

A fresh story (no `pipeline.json`) starts with S0 by code: `ticket_adapter.py get`,
`environment_selection.py`, `readiness.py --write --probe-vcs` and `--require`, `env_probe.py`,
the first `pipeline.json`, `stage_done.py --stage S0 --status done`, `controller.py
--operation initialize`. `--env`, `--mr/--branch/--commit`, `--ungrounded`, `--side`, `--reference` and `--ticket-file`
are the `qa-story` arguments; S0 and the S1 dispatch are the only readers (`--side` and `--reference` are recorded into `pipeline.sides`
when the first `pipeline.json` is written).

A resumed story (a `pipeline.json` exists) looks at its ticket once before the loop (B-364, D-0027): after the answer a
run carries is recorded, before the next step, never in the process that ran S0, and again before gate B is asked - the
same `ticket_adapter.py freshness` and the same trigger as the skill's (`phases/s0.md` section 2b). Not asked of a story
with no `state/controller.json` (the loop's `initialize` hashes the S0 snapshot first), of one whose person said the
ticket is not needed (`launch.ticket_not_needed`), of a closed story, or while another question is open. A look that
cannot be made (a tracker that does not answer, a protection service, 300 seconds with no answer) is one line and
`ticket_unchecked` at most once per 6 hours: the story goes on with the text it was built on; a lost login stops the
run, and a fault of the factory is reported. A full S4 re-run after the gate A reopen can meet "cumulative packet budget
reached" (the S4 designer's budget is story-wide): the driver adds no move of its own, the refusal takes the existing road.

`--until gate_A` stops with exit 0 once the action after gate A's decision is reached (the
gate itself is still asked and its answer recorded); `gate_B` likewise; `end` runs to S9.
`pipeline.stop_after` in `config.json` is honoured through `story_step` as before.

`--dry-run` prints, for the current state, what the driver would do — the `where` action, the
S5 windows still open, the S7 entry check, the shape of the `claude -p` command — and runs
nothing: no dispatch, no role, no conductor.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | the story is complete (`where` answered `complete`), `--until` was reached, `pipeline.stop_after` stopped it, or `--max-boundaries` paused it (run again) |
| 2 | a start refusal from the driver's data: the Codex host has no model (`--model` absent and `default_model.codex` of `references/driver-infra.json` missing or not a model name) |
| 3 | a person is needed — the question is in `qa-factory/artifacts/<T>/state/driver-question.md` and was printed; also no project here (no `qa-factory/config.json`, `hooklib.require_project`) |
| 4 | the conductor gave up (`stop`) — `state/driver-question.md` carries its reason |
| 5 | the infrastructure under `claude -p` failed and nobody has anything to decide: a login, a usage limit, or a broken answer that outlived its retries. The message and the command that goes on are printed; there is no question file, no `asked` flag and no conductor row. See "Infrastructure failures" |
| 1 | an error of the driver's own (no `claude` / `codex` executable, an unknown host, a story that holds the other host's sessions, an empty answer file) |

## Infrastructure failures (B-012)

A `claude -p` call can fail for a reason that is not about the story: the login is missing, the account's usage
limit is reached, the service answers with a broken page. On TP1-13877 each of the three came back as the
"final message" of a role, and the driver read it as a handoff that was not in the form: it resumed the role,
called the conductor with the login error as the refusal and put "Not logged in" to the person as the
conductor's question (5 conductor sessions and 4 resumes in `state/driver-runs.jsonl` rows 1-4, 7 and 17).

`Driver.run_claude` recognises such a failure in ONE place, right after the process exits and before the
journal line, the stored session or the return (`scripts/infra_failure.py`, reading
`references/driver-infra.json`): a typed kind `auth`, `limit`, `transient`, or `unclassified` for a failure
no row knows. Only a call that failed (`is_error` or a non-zero exit) has its text read, and the subtype
`error_max_turns` is the role's own outcome; the words of a successful call are never matched.

- `transient` is retried in place by `runtime_policy.retry_decision`: after 5 s, then after 15 s, and a
  third failure stops. The retry resumes the failed session when it did work (`num_turns` above one and a
  session id), else it is the caller's own resume, else fresh; a retry is the same call and is never counted
  by `guarded`, the handoff resumes or the conductor's calls.
- `auth`, `limit` and an exhausted `transient` raise `InfraStop` (exit 5). The message says in plain words what
  happened, that nothing about the story is wrong or lost, and, in its own block, the command that goes on -
  the task, the project and every non-default flag of this run, `--answer <file>` only while the question it
  answers is still open. For `limit` the reset is quoted as the service wrote it; when it named none the
  message says so. Nothing is saved as a reusable role result and no attempt is counted.
- The cut-off call is recorded in `state/driver-state.json` under `interrupted` (below). The same command run
  again continues it: the session that did work is resumed with a short note, or a session that did nothing
  starts fresh with the note after the dispatch prompt. The note lists the files the role had already written
  and tells it to continue them; a role that has Bash is also given `artifact_supersede.py` for the case
  where nothing in a file is usable (a role without Bash keeps `Edit`).
- A result saved by an older driver under `state/driver-runs/<dispatch>.json` is classified before it is
  reused: an infrastructure failure is renamed `<dispatch>.infra.json`, recorded as the interruption, and
  treated as absent. The person's words for a dispatch and a valid saved result both outrank an interruption.
- The S8 delivery call is keyed `S8:delivery` and is continued the same way. A `claude -p` call that is not a
  role's (the conductor) gets a generic note. S0 calls no model: the ticket is read by `ticket_adapter.py get --raw-dir`
  (REST; t-267). A read that fails has three owners, said by the adapter's exit code and its `--json` error object
  (t-281): the tracker's (exit 1/3) is the `ticket_read` question (`not needed`, `retry`, the ticket as text; `retry_at`
  from the object), the factory's (exit 4: a broken data table or setting, an unexpected error, or an adapter that printed
  no object) is a Refusal naming the file, and a lost login (exit 5) is an `InfraStop:auth` naming the token variable (exit 5 with owner `intermediary` is the `ticket_read` question naming the protection, not a login stop). A
  pasted text is parsed by the same parser as a fetched description; no `# ` line is the `ticket_title` question (first line
  taken, `go on` keeps it), a criteria section the reader lost (text under the heading, no criteria read) is the `ticket_incomplete` question (the factory's defect; paste / `go on` / stop) while a ticket with no such section is a first line of `pipeline.warnings` (D-0050), and a
  snapshot already on disk is read as it is and never rewritten. The tracker agent is a write channel only.

## Child environment

Every child of the driver gets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`: a script that printed a dash
under the machine's code page reached the driver as replacement characters. Factory scripts (`py()`) get the
driver's environment otherwise as it is, because one may use a gateway on purpose. A `claude -p` child also
loses what a desktop-app host put in the driver's environment - its proxy address without the per-process
token, which made every child answer "Not logged in" while a valid login sat in the credentials file: the
names in `child_env` of `references/driver-infra.json` (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`,
`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, `CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH`,
`CLAUDE_CODE_HOST_AUTH_ENV_VAR`, `CLAUDE_CODE_CHILD_SESSION`, the prefixes `CLAUDE_CODE_USE_` and
`CLAUDE_CODE_MESSAGING_`, and the variable whose name `CLAUDE_CODE_HOST_AUTH_ENV_VAR` holds). The list is
printed with an auth stop. `ANTHROPIC_API_KEY` is not on it.

Config key `driver.child_env` = `{"keep": [], "remove": []}` in `qa-factory/config.json`, absent = the data
file's list: `keep` passes host variables through (a gateway or an API-key setup used on purpose), `remove`
adds names; a name in both is kept and the driver says so; a value that is not a list of names is ignored
and the driver says so. A data file that cannot be read is one printed note, and every failure is then
`unclassified` (today's behaviour) with nothing removed from the child's environment.

## Questions and answers

`state/driver-question.md` starts with `kind:`, `stage:` and `dispatch:` lines; the kinds:

| kind | When | What the answer does |
|---|---|---|
| `gate_A`, `gate_B` | `where` says `await_gate`, and before the text the rehearsal ran (`gate_preflight.py --gate X`): its `factory_fixable` findings were repaired by code per t-211 (see "Gate entry" below), so the gate is shown only with an empty set, or with the unrepaired remainder stated at its top; the text is `gate_brief.py` + `gate_preflight.py --text` + the waivers so far (+ ledger and report §3 at B) | recorded by code (`record_by_code`: `gate-decision --words-file <file>`, the driver writes the file); what does not record goes to the conductor: `waiver.py` per named item, `stage_done --set retro_mode`; `deliver_with_risks` is recorded by the same `gate-decision` call (HF8-23: a `deliver with known gaps: <reason>` line of the words, whole, is read by the controller, which writes the journal line the delivery guard reads), and only words in another form go to the conductor, whose door is `log_append.py --event deliver_with_risks --reason-file <file>` |
| `s1_review` | the scout's digest reads `S1 review`; the text is `ticket_adapter.py review` + the stand question | the conductor records assess / accept-gap / review --record / the stand; the driver then resumes the **same** scout session with the words |
| `halt` | a role's digest verdict is `halt` or `impossible` (`stage_done --status halted` was written) | the conductor records the decision; the driver resumes the same session with the words |
| `retro` | S9, the fixed question from `phases/s9.md` | recorded by code (`log_append --event escalated "retro feedback: ..."`); `skip` = declined |
| `refusal` | a known refusal only a person passes (`STORY BUDGET`, `executor unavailable`, readiness `missing`); a refusal of the role's handoff or of its `finish` (exit 3) that the role's OWN resume did not settle (the same finding set again, t-217: see "Refusals"); an S5 window whose rework rounds are spent (`window_rounds`) | the conductor records the word that passes it (`waiver.py --block ...`) |
| `conductor` | the conductor answered `ask_person` (or its three calls at one boundary ran out) | the conductor gets the words together with the original refusal |
| `package` | one package generation per run (B-014), two causes. (1) After a `claude -p` session the receipt `state/host-receipts/package-<session>.json` (written by `telemetry_hook.py`) (or a `plugin_root` in another host receipt of the session; partial - both copies share a receipt key, the last writer wins) names a plugin root other than the driver's `--plugin-dir`, several roots, or no receipt at all: nothing of that session is accepted (its saved result is set aside as `.mixed.json`) and the step runs again. (2) At the start of a run, `pipeline.run_mode` (stamped by `story_step start`) differs from `driver`, with no "mode switch" override for the first stage not done | a CLOSED set of tokens (the S0 stop's pattern; the words are never read for meaning): `go on` passes and is recorded - (1) `package_pass` in `driver-state.json` keyed on the (driver root, hook roots) pair, so the same pair passes without asking again, plus `defect_found` (owner factory); (2) `waiver.py --stage <S> --block "mode switch"`, per stage, no `defect_found` (a mode switch is the person's choice). `retry` (1): record the word, pass nothing, go on - the step runs again and the copies are compared again. `desktop` (2) and `stop`: record the word and end the run without a role call or spend; the question stays open with the same door. Anything else: asked again, naming the tokens. Every answer also writes a `human_answer` event |
| `ticket_changed` | B-364 (D-0027): `Driver.ticket_freshness` ran `ticket_adapter.py freshness` (the one command, the one 6 hour trigger of `phases/s0.md` section 2b) and the REQUIREMENTS of the ticket moved since the story was built (title, type, description, acceptance criteria): the baseline is kept and the new text waits as `work/ticket-snapshot.next.json`. The question names what moved and the three answers; a text the person already declined is one line and never asked again (FR-7) | a CLOSED set of tokens, read from the FIRST non-empty line (`s0_normalize`; the code never reads a meaning, FR-12; no conductor): `new text` - `freshness --adopt`, the words recorded (`human_answer`), then S2 and S3 re-run one at a time with `rework --cause ticket_changed` (spends no repair cap; `complete=True`, so the plan baseline is re-captured), then gate A re-opened by `semantic_reopen` with a line at its top when it was decided, and the S5-S8 work of its scope invalidated; `old text` - `freshness --decline` with the WHOLE answer as the words: kept as a remark of S0 that gate B shows; `stop` - recorded, nothing runs, the question comes back. Anything else, or an adapter refusal, is asked again quoting the words; the question is always rebuilt from the two files, never from the tracker |

The person's words go to `state/driver-answers.jsonl`; the answered question is kept as
`state/driver-question.answered.md`. Nothing is re-asked: a recorded gate decision makes
`where` move on, a halt's words are held in `state/driver-state.json` until the role resumed.

**Whose answer it is (t-217, F-cmp2-22).** The `dispatch:` line of a question is a FIELD (`asked.dispatch`), set when the
question was raised: a Person raised from a refusal carries the refusal's own dispatch (`Refusal.dispatch`, which every raise
site that knows its dispatch passes), else the dispatch the boundary names by its shape (`S5:S5-qa-code-critic-2`; `S0:ticket`,
`gate_A` and `S5:TC-1,TC-2` name none). The words of a `conductor` or `refusal` question are filed for THAT dispatch
(`pending_words`), and an id quoted in the question's text is never read: two runs filed words for the wrong dispatch that way (a gate
packet quoting a handoff; a probe's hint `--dispatch <critic id>`). Gate answers are never filed to a dispatch (their keeper is
`gate_answer_kept`). Only a question an OLDER driver asked (its `asked` has no `blocks` key) keeps the text reading, and a capture
counts only when it is a dispatch id by shape and the only one the text names; when unsure the words are filed to no dispatch and the
boundary asks again with the "you have answered this" block. `asked.blocks` is written by `ask()` for `conductor` and `refusal`
questions (an empty list until the parser of the blocks a question names lands). The questions t-217 adds (a second identical
refusal, a stand that does not answer, an S5 window whose rounds are spent) offer the closed answers `retry` / `go on` / `stop`
(`TOKEN_ANSWERS`); until the answer path reads those tokens by code (queued, with the recording of a pass per named block), every
answer still goes to the conductor with the person's words, as before.

## Refusals

A refusal is a non-zero exit of a factory script, or an exit-gate error a role left after one
`--resume` asking for the handoff form. The driver checks each handoff the way `exit_gate.py`
does (`exit_gate.all_errors`: artifact validators, stage detectors, the witness re-run, the
digest form, required outputs; a waiver passes what the person passed).

The known-refusal table is tried first. It lives in the script, once
(`KNOWN_REFUSALS` in the driver set, `scripts/story_run.py` and `scripts/driver_*.py`, regex → action, one comment per row): a copy of it
here is a second list to keep in step, and the factory has paid for that habit already. What
the actions mean: a FORM refusal (the handoff form, the handover form, a missing required key)
resumes the ROLE with the refusal, because the answer is the role's own; a `story_step finish`
refusal of the role's STRUCTURED artifact (`structured_artifact`: `S3 structured test plan invalid: ...`)
resumes the role's OWN session once with the refusal verbatim and runs `finish` again - the same refusal
a second time, or no known session, is the person's, never the conductor's and never a fresh dispatch
(the count is `structured_resumes` in `driver-state.json`, keyed by dispatch); `story_budget`,
`executor` and a missing capability ask the person; a stale revision retries; an already-closed
stage continues; an uninitialized task initializes; a dead dispatch recovers; `stage_done` refusing to
record the stage in front of a gate (`gate_stage`, the FIRST row, because its text carries rehearsal
findings that can hold a later row's phrase) continues while the controller holds that stage
`completed` - the gate-entry step below repairs what it lists - and goes to the conductor otherwise.

**The role is resumed once per finding set (t-217, F-cmp2-23).** A saved result is handed to `handoff` again on every entry
(`wait_existing_job`), and every entry used to resume the role over the same findings and then call the conductor (cmp2: eight
resumes and four conductor calls over one dispatch, $0.3 a call, and no word that the stand was back). Now the findings of a refusal
are a SET (`finding_lines`: whitespace collapsed, a dispatch id replaced by `<dispatch>`, de-duplicated, sorted), and the state keeps
`refusal_resumes` `{dispatch: {session id: {sha256 of the set: handoff|refusal|stand}}}`: (b) `handoff` resumes the role for a set it
has not resumed it on (and records that BEFORE the paid call - a crash costs one resume, never repeats one); (c) a refusal whose HEAD is
`exit gate for <id>` or `story_step finish <id> (exit 3)` (anchored matches: the refusals of the `finish` CALL, exit 2, carry the marker
too but are the driver's own mistake and stay with the conductor) and whose row is `resume_handoff` / `resume_repair` resumes the
role's own session once with the refusal whole when that set was not yet resumed on, writes the result as the dispatch's saved
result, and goes on from it (`where`); (d) a set already resumed on, with a digest row whose state is `blocked_by_env` and a stand named
by the story, looks at the stand ONCE per dispatch+session (`env_probe.py --env <stand> --task <T>`, the tool `stand_check` uses) and,
when it answers (exit 0 and some output), resumes the role once more with the probe's words whole; otherwise, and for the same set a
second time, the PERSON is asked - a declared change of "below it is the conductor's": the conductor can add nothing to a finding the
role has already been given (a refusal is the person's the second time, with the refusal and the probe beside the question). No dispatch
or no session known: the person, nothing called. A resumed result that halts is heard by `wait_existing_job` (the halt road) before
`finish` sees it. `resume_structured` is unchanged and keeps `structured_resumes`. An accepted finish of the dispatch drops its record.

Anything else is a conductor call: the refusal text, the `where` output, up to three files the
refusal names (≤ 8 KB each), the stand-remedy authorization, and the person's words when
there are any. Tools `Bash,Read,Grep`, `--max-turns 20`, the same `--model`. Its last line is
`{"action": "continue|retry|ask_person|stop", "did": ..., "question": ...}`; at most three
calls per boundary, then the person. A decision that repeats in `state/conductor.jsonl` is a
candidate row for the table above.

**A cap on the rework rounds of one window (t-217, F-cmp2-28c).** The per-boundary cap lives in memory, keyed by the boundary, so
the loop unmatched refusal -> conductor -> rework -> new dispatch -> new boundary gave three fresh conductor calls every time (cmp2: 11
automators and 4 critics on one S5 window over the same five gap lines, $7.28). Just before an unmatched refusal is handed to the
conductor, at a stage in `WINDOW_ROUND_STAGES` (S5 now; S3, S4 and S7 have the same loop and are queued), the round is recorded in
`window_rounds` `{"<stage>|<the dispatch's sorted scope>": [{at, dispatch, set, outcome, cause}]}` (`cause` is `window` when the set is the window record's gap lines, else `refusal`; absent or
unknown = `window`): a finding set equal to an earlier round's (`outcome: same_set`, judged across both causes) or a third round of
its cause (`WINDOW_ROUND_CAP` = 2, `cap`; a round over a refusal whose set is not the window record's gap lines spends its own cap of
`WINDOW_ROUND_CAP`, not the window's) is the PERSON's - one plain sentence naming the round, the
closed answers, the refusal and the set beside it - and every other round goes to the conductor (`to_conductor`, written before the
call). The set is the window record's gap lines when `window_record.py` exited 1 (`Refusal.window_findings`, never part of the text),
else the refusal's own body after its head; an empty set is never recorded and never equal. Known rows act first and are never counted,
and the gate-entry hand-over (`conductor_round`) never meets the cap. Only the accepted completion of the stage's closing role (the
code critic at S5) ends the series: an author's accepted finish between two reviews does not.

**The window note.** `window_record.py` exiting non-zero before the S5 critic's `finish` is told as what is true: found N gap(s) and
the record it wrote is passed by `story_step finish` itself, or an older record is on disk, or none exists - by the file's own stamp
before and after the call, never by the exit code (`window_record.py` writes the record first and a later failure is caught after
the write). The gap lines are printed; a line carrying a refusal marker is not. Print only: `--window` and `--unresolved` are decided as before.

**Stand remedy.** The conductor may bring a stand up or fix it only when the selected
environment's `bring_up` text in `config.environments[]` carries the word `AUTHORIZED`, or
`config.driver.stand_remedy_authorized` is `true`. Otherwise a stand problem is a question.

## What the driver does at each stage

| Stage | Moves |
|---|---|
| S0 | by code (above); on an initialized task with S0 still open, a `code_only` receipt |
| S1 | `qa-scout` with the launch flags, environment, ticket source and repositories in the prompt; a `review` digest is the source-review stop (dispatch kept running, session resumed on the answer); required outputs and the S1 inventory checks as at the exit gate |
| S2 | one role |
| S3 | on a diff story two strategist dispatches: window 1 (`purpose: s3_labelling`) labels `work/grounding.yaml` and writes no plan; window 2 writes the plan in parts; the driver prepares the table (`blast_radius.py`, refresh, `base_slice.py`) before window 1 and projects the claims after each window; off the diff, one dispatch as before |
| S4 | designer → `case_versions.py --all` (records the scope itself)/`--verify` → `revise_plan` to the pinned ids (a no-op, or the controller's refusal when the record failed) → critic scoped to the `design_review_required` rows (all pinned cases when none); `concerns` with a round left → `rework` of the designer, re-pin, critic again (2 rounds, then the gate); `approve_with_fixes` applied by `critic_rollcall.py --apply-fixes` → `render_case_appendix.py` → gate A; after the critic's finish, gate entry repairs what the rehearsal still lists (t-211) |
| S5 | `stage-scope` windows; per window: automator (`--not-complete`), critic; `concerns` → `rework --cause test_defect` of the automator (≤ 2 rounds); the last window's critic closes the stage; a window the controller still refuses is the conductor's for at most `WINDOW_ROUND_CAP` (2) rounds with different findings, then the person's (`window_rounds`, "Refusals") |
| S6 | `stage-scope` automation block → runner; manual block → runner registered with `execution_kind: manual` in-process (`story_step start` cannot say it); nothing to run → `code_only` |
| S7 | entry check by code (failed totals, failing or inconclusive manual checks, `contradicts_requirement` rows); nothing → `code_only` + `stage_done` + `dispatch_skipped`; else the analyst, then ≤ 2 `rework` rounds per `TEST_BUG`/`FLAKY` row and `finalize_task.py` |
| S8 | `check_traceability.py`, `ledger.py`, `check_delivery.py`, the scribe with `--complete`, gate B; after the scribe's finish, gate entry runs the same step (t-211): at B every finding the rehearsal lists goes to the conductor once, there is no B move yet |
| gate entry (A after S4, B after S8) | `where` says `await_gate` → `gate_repair`, BEFORE the question: owed steps first (the case appendix, or the report rebuild, when a refused finish skipped it), then `gate_preflight.py --gate X` as JSON. Nothing listed as `factory_fixable` (or no rehearsal: it raised, exited non-zero, printed no JSON, or `findings` is no list) → the gate as it always was. Else a round: A `case_versions` → `case_versions.py --all`, `--verify`, then `revise_plan` to the pinned ids (as stage S4 does); a repaired round owes the next gate entry the case appendix again; A `gate_decision` → ONE role dispatch by `rework --cause test_defect`: the case critic over the cases a designer reworked AFTER its review (re-pin first), else the case designer over the cases of a critic that did not approve (only while a round is left for the critic that follows and the designer's own cap has room). Moves read `check`, `class` and the controller's design reviews and `accept` events, never a finding's wording. Cap 2 rounds per gate (`state/driver-state.json` `gate_repair.<gate>`, stamped with `source_revision`, dropped with the gate's approval at that revision); a round whose key set (check + message, never the positional id) equals ANY earlier round's, the cap, or no move that applies, stops the series: what is not `direct` goes to the conductor once (`conductor_round`, never the known-refusal table), and the next `await_gate` shows the gate with the list at its top. `question_branches` is only ever listed. No repair under an open question about the gate, none after the person's answer is kept (`gate_answer_kept`: the decision is recorded again; if it still does not record, the gate is asked again only with their kept words and the controller's refusal verbatim on top). A failed move is printed, recorded (`outcome: failed`) and handed to the conductor with its last 20 lines. `--dry-run` prints `would: rehearse gate X, then repair: ...` and writes nothing |
| after B | the bug reporter for the chosen drafts (`--not-complete`); then **one** conductor call with the delivery section of `phases/s8.md`, the gate B decision, `git_conventions`, the VCS adapter and `--branch-suffix` (tools `Bash,Read,Grep,Write`, `--max-turns 40`), recorded once in `state/driver-state.json` |
| S9 | `retro_mode` from `pipeline.json`; the fixed question (exit 3 once); `retro_numbers.py`; `full` → the analyst, `numbers` → `--write-retro` + `estimate_record.py`, `skip` → `stage_done --status skipped`; `complete` → `factory_dashboard.py` |

Every role prompt is the block `story_step start` printed, plus the dispatch scope, the lines
the phase file adds for that role, the plugin root and the handoff form. What
`inject_context.py` would have injected on an `Agent` call (`references/inject-map.json`) is
written to `state/driver-tmp/<dispatch>.system.md` and passed as
`--append-system-prompt-file`, with the resolved task packet at its end — a headless
`--agent` session has no `Agent` PreToolUse hook. Each role's result is saved under
`state/driver-runs/<dispatch>.json` until its `finish`, so a driver that dies mid-boundary
resumes without paying the role again (`where` then says `wait_existing_job`).

## Where the story stands (`[progress]`, t-310)

The roles run as `claude -p` subprocesses, so they are not in the desktop's task list; the story's own
records say where it is. `scripts/story_progress.py` has ONE function, `progress(task_root)`, computed from
`controller.json`, `pipeline.json`, `state/events.jsonl`, `state/driver-state.json`, `state/driver-runs.jsonl`
and `task_price` (the cost files) — never from a running process's memory — and three readers of the same
dict: the driver's log, the dashboard's story card (`render_html`), and `python story_progress.py --task-root
<root> [--json]` (exit 2 with the path named when there is no story or a record is damaged).

The driver prints `[progress] <line>` (flushed per line, FR-43) once per transition: at the start, before a role
is launched, after it returned and its work is recorded, when a question is posted (a gate is reached by being
asked, so it is that one line), when a stage is closed by code, and at the end of the run. The line is code
informing, never stopping (P1): a reader that cannot answer is one line saying so.

The line reads `S5 Automation · window 2 of 4 planned · round 1 of 2 (critic) · the code critic running 14 min ·
$4.10–4.60 so far (sources disagree) · done S0–S4`, at most 160 characters; a longer one loses the case names,
then the list of finished stages. It names a role in words and never a dispatch id (FR-6: `human_text` rejects
ids); the ids stay in the dict. Rules that keep it honest (FR-41, P18):

| Question | Answer |
|---|---|
| Window `i` of `n` | `n` is the plan's window count (`Controller.stage_scope`) when it holds one and is not smaller than the windows already seen; else `null`, and the line says "total not known yet". A one-case rework inside a window's scope is that window |
| Round | `controller.repair_ledger` for the window's author — a superseded dispatch and its retry are one round, only a `test_defect` round spends the cap — out of `runtime_policy.DEFAULT_LIMITS["repair_cycles"]`; before any repair, "first pass" |
| "running N min" | only when `dispatch_liveness` proves the role alive. Under the driver no role leaves a subagent transcript, so the proof is the driver's own `in_flight` entry (below): its pid is alive -> "running N min". Its pid is gone -> "started 05:12, the process is gone" (a fact, never "not proven alive"). Otherwise - no entry, an entry with no pid (a legacy one), a pid that could not be asked - "recorded running since 05:12, not proven alive" (or "started 05:12, no proof of work yet" within `never_started_after_s`): a stale record is never shown as live. A gone pid changes nothing else. When `dispatch_liveness` answers `returned` the line says "returned 05:38, its dispatch still open" (no time when the record holds none) - from the driver's end row in `state/driver-runs.jsonl`, a return the hook journalled, a terminal host receipt, or, for a `story_step` receipt, the host's own rollout: a clean `task_complete` of this launch, older than `dispatch.native_completion_grace_s` (300 s) and alone among the rollouts of that path that are not finished (a rollout still written, cut mid-row, aborted, unreadable or compressed is no evidence). A gone pid is said first. `recover` and `next` close a dispatch on every one of those returns or on a silent transcript, never on a pid, and the rollout writes no receipt and accepts no work |
| Start time | the driver's `in_flight` entry when there is one, else the controller's own `dispatch` event, else none (a legacy story: no duration, no error) |
| Price | `task_price`'s answer: one figure when the two records agree, a range with "(sources disagree)" when they differ, "(recorded only)" when one is missing, "no cost recorded yet" when there is none — never a zero for an unknown |
| The clock | read once, at the top of `progress`; every duration is measured against that one instant |

`state/driver-runs.jsonl` — two lines per `claude -p` the driver made (a `{"kind": "launched", "call": ..., "dispatch_id": ..., "stage": ..., "started_at": ...}` row before the process starts, with no pid, session, cost or exit code - a `launched` row with no row after it is a call that was running when the driver died - and the call's own row when it ends):

```json
{"ts": "...", "kind": "role|conductor", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
 "session_id": "...", "num_turns": 12, "total_cost_usd": 0.41, "duration_ms": 93000,
 "resumed": false, "exit_code": 0, "is_error": false, "model": "sonnet"}
```

`kind: conductor` lines have an empty `role` and `dispatch`; `stage` is the boundary's stage
(`S8` for the delivery call). `resumed: true` is a `--resume` of an existing session (the
handoff-form retry, a halt continued on the person's words, a call continued after an
interruption). Since B-012 every line also carries `subtype` (the result's own, or `""`), `infra`
(`auth`, `limit`, `transient`, `unclassified`, or `null` for a call that was not a failure) with its
`infra_rule` (the id of the row in `references/driver-infra.json` that matched: `""` for `unclassified`, `null` for a call that did not fail) and
`retry` (0, 1 or 2: which try of the same call this line is). A retry writes its own line, so a
transient failure that was retried once leaves two lines.

`state/conductor.jsonl` — one line per refusal handled, by the table or by the conductor:

```json
{"ts": "...", "boundary": "S1:S1-qa-scout-1", "stage": "S1", "refusal": "<text, ≤ 2000 chars>",
 "action": "known:story_budget|continue|retry|ask_person|stop", "did": "...", "question": "...",
 "session_id": "...", "total_cost_usd": 0.05, "num_turns": 4, "duration_ms": 12000, "words": false}
```

Rows written by the table carry `action: known:<name>` and `did: <the table's action>` and no
session; the delivery call is journaled here with `refusal: "delivery"`. `compare.py` reads
`driver-runs.jsonl` as the driver's own cost line: sum `total_cost_usd` by `kind` and `role`,
and `num_turns` the same way; the orchestrator's row of the earlier runs is the `conductor`
kind plus the driver's own zero.

`state/driver-state.json` holds the driver's bookkeeping: `sessions` (dispatch → session id),
`pending_words` (dispatch → the person's answer not yet delivered to the resumed role),
`asked` (the open question), `in_flight` (B-268: dispatch id -> `{dispatch_id, pid, started_at, session_id?}`, written the moment a
ROLE's `claude -p` process has a pid and removed when the call returns by any road, so an entry left on disk is a driver that
died with its role; the conductor's and the delivery call's own processes write none; the key is absent when nobody is
in flight; the child's environment carries `QA_FACTORY_DRIVER_RUN=<dispatch id>`, which its hooks and tools inherit; the one reader of that word
and of the gate's `QA_FACTORY_DETECTOR_DISPATCH` is `scripts/dispatch_identity.py`, AR-13),
`retro_asked` / `retro_feedback`, `delivery`, and `interrupted`: key (a
dispatch id, or `S8:delivery`) -> `{kind, rule, session_id, num_turns, worked, call, stage, role, dispatch,
reset, at}`, the call an infrastructure failure cut off (`kind` is the failure, `call` the driver's kind of
call, `worked` says whether the session did more than one turn and can be resumed). A state file without
the key is read as an empty one. Gate entry (t-211) adds `gate_repair` (gate → `{source_revision, rounds:
[{at, keys, moves, outcome, stop}]}`; `outcome` is `started`, `repaired`, `failed`, `to_conductor` or `shown`,
`stop` is `""`, `same_set`, `cap`, `no_move` or `failed`), `gate_entry_owed` (stage → when a refused finish
skipped its closing step) and `gate_answer_kept` (the person's gate answer that did not record, with the
revision it was given at); each record also writes a `kind: gate_repair` line (no `session_id`, no cost) to
`driver-runs.jsonl`. t-217 adds `refusal_resumes` (dispatch → session id → sha256 of a finding set → `handoff`, `refusal` or `stand`:
the resumes the role has had, so that none is repeated across entries and relaunches), `window_rounds` (`<stage>|<sorted scope>` →
`[{at, dispatch, set, outcome, cause}]`, `outcome` is `to_conductor`, `same_set` or `cap`, `cause` is `window` or `refusal` (absent or unknown = `window`): the conductor's rounds over one window) and, in
`asked`, `blocks` (a list, empty until the parser of the blocks a question names lands) for the kinds `conductor` and `refusal`; a state
file without these keys is read as an empty record. B-364 adds `ticket_unchecked_at` (when `ticket_unchecked` was last
journaled), `ticket_rework` (`{stages, words, at, before, reopened?, invalidated?}`: the S2/S3 re-run the person chose and how
far the gate A reopen got; removed when it is done) and `ticket_gate_note` (gate → the line its next question carries at the
top, popped by it), and `launch.ticket_not_needed` (S0 writes it when the person said the ticket is not needed, before its
answers are popped); all absent until first written. State-exits: `design/state-exits.md`.

C1-7a adds two keys for the journal rows the story's later roles read (the person's `human_answer` words, an FR-4 finding, a
`--warn` line). `owed_rows` is a list of `{id, script, args, what, stage, at, tries, exit, tail, word?}`: `Driver.owe_row` appends a
row when the journal script exited non-zero on its first run (the flow goes on, because the executor at hand already holds the
words), and `Driver.owed_rows_step` — run after the answer is taken and first in every loop turn, before any brief is built —
runs each row again, removes the ones that write, counts `tries`, and raises, for the rows refused `OWED_ROW_TRIES` (2) times,
the seam's question, which carries their ids (`asked.rows`) (`no_move`: kind `refusal`, no paid call, the block `journal rows not written`; its text is
row ids and a count, never the person's words). `rows_given_up` is a list of the rows the person's `go on` released (a waiver over
that block in `pipeline.json`, paired with the question by the row ids it carried: `take_seam_answer` marks `word` on those rows once
the pass is recorded): `owed_rows_step` writes it, with one `rows_given_up` line in
`driver-runs.jsonl`, and from then on a failing row of the same script is given up with no new question. The word is the story's, as
every waiver is. A state without either key reads as no rows owed; a value that is not a list is set aside with a `trace_failed`
line and read as empty.

A result saved before an interruption was recognised is renamed `state/driver-runs/<dispatch>.infra.json`
when it turns out to be an infrastructure failure; nothing reads it afterwards.

## Limits worth knowing

- The driver never checkpoints a dispatch for a halt or the S1 review: the dispatch stays
  `running`, the question goes out, and the same session is resumed on the answer. A driver
  restarted without an answer re-prints the same question.
- `source_preflight.py` is not run at S0 (nothing in the guard needs its receipt before S5;
  the conductor runs it when a refusal names it).
- The S7 repair loop judges a round by the automator's digest rows (`green`/`passed`); a row
  that stays red after two rounds travels to the ledger as the phase file says.
- The S4 critic scope is derived from `design_review_required` rows through the controller's
  own case→row binding; when the binding is not readable, every pinned case is in scope.
- Three conductor calls per boundary, six refusals in a row per boundary, four identical
  `where` answers in a row, two conductor rounds per S5 window and one resume of a role per finding set: each ends in a question,
  never in a loop.
