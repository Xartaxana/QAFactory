# Phase 4 — Generate

Generate config only from `references/templates/config.json` plus approved facts and the
runtime defaults in `scripts/config_contract.py`; never copy `scripts/config.example.json`.
New configs contain no cadence/retention keys or legacy `external_writes.commands`.
Preserve unknown extension keys during re-onboarding.

The config is written by the one apply path below (`--phase early`), from the sealed proposal
phase 3 recorded: atomically, with its prior value stored in `qa-factory/records/config-migrations/`
(a fresh install leaves no backup). Never hand-edit the proposed migration or the sealed file.

## 0. One apply path, in two halves

A fresh install and a reinstall are the same plan; everything after the "yes" that is not the
role's own document goes through `onboard_apply.py`, with the reference of the approval phase 3
recorded and the sealed file it made (`<ref>`, `<sealed.json>`: both are in `<notes>/progress.yaml` as `approval_ref`
and `sealed`; `<notes>` is the folder `onboarding_notes.py --root . status` prints):

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboard_apply.py" --root . --proposal <sealed.json> --apply --approval-ref <ref> --phase early
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboard_apply.py" --root . --proposal <sealed.json> --apply --approval-ref <ref> --phase final
```

- **early** (right after the yes): writes the config (step 1's fill is already in the proposal;
  the proofs below edit the written config in place, as before), copies the obligations and backlog
  templates when absent (step 8), and puts the `.gitignore` block in as one piece (step 8b).
- **final** (after steps 1-8 are done, before the audit): first moves the records an older factory
  kept in `qa-factory/state/` into `qa-factory/records/` (bytes unchanged, before anything is removed);
  removes lock files nobody holds, rebuilds
  readiness and the dashboard (step 9), deletes the factory's own technical data and sets aside what
  the summary listed, and writes the install record last. It reads every listed file again first;
  if one differs from what the summary showed it refuses, names the paths and writes nothing: make
  the summary again. A session that is running refuses it too, with the way out.
- The old `strategy/product-passport.md` goes only behind this run's fold receipt. After folding it
  (step 3) record the fold: `config_contract.py --root . --record-approval <sealed.json> --approval-ref
  <ref> --evidence-ref <ref> --fold`. Without the receipt the final half keeps the file and says it
  waits for the fold. Never delete it by hand.
- A second run over a finished install has nothing to do and says so: it asks nothing.
- With no person present, `onboard_apply.py --root . --proposal <file> [--answers <file>] --apply` runs
  both halves in order and records the command line as the word. It writes the config, the template
  copies, `.gitignore`, readiness, the dashboard, the removal and the record. It leaves to the role:
  discovery and the interview, the strategy documents (steps 2-7), the fold, the launch check and
  the login proof, the commit.

Write deferred decisions through `scripts/project_decisions.py` to
`qa-factory/factory-backlog.md`. Repeated onboarding reuses an open row with the same
`field_refs`; later evidence closes it with `resolution_ref`. Then run readiness and retain
its complete `repository_inventory`.

Create a DD with `project_decisions.py --root <project> add --field-ref <json-pointer-or-doc:path[#anchor]>
--essence <text> --asked <recorded-question> --scope <scope> --owner <owner>
--trigger-type <type> --trigger-value <value>`. Resolve it only with
`project_decisions.py --root <project> resolve --id <DD-n> --words-file <file>
--resolution-ref <evidence> --field-values <json-object>` (`--field-values` is omitted when every ref is a document ref; their exact answer, as given, in
a UTF-8 file written with the host's file tool to `<project>/qa-factory/state/words/<name>.txt` (onboarding has no story folder), named
`<topic>-<YYYYMMDD-HHMMSS>.txt`: never overwritten, never deleted), adding every exact
`--marker-file` and `--marker-text` when a paired marker exists. Run
`project_decisions.py --root <project> recover` before another write if a pending
transaction receipt exists.

Canon of a `qa-onboarding` phase. Read on entering the phase. Runs **only** after phase 3
recorded an explicit `yes`. Everything here writes under `<project>/qa-factory/` — never
into `references/templates/` (plugin-side, read-only from this skill's point of view).

The documents and the DD rows are built from the run's notes, not from memory: what phases 1-2b found is in
`<notes>/discovery.yaml`, what the person answered in `<notes>/interview.yaml` and `<notes>/words/`. Every
question this phase puts (a launch-check question, "Do it?", the explaining question) is a batch recorded
through `onboarding_notes.py --root . ask` and `answer`, named `p4-<profile>-<n>` (`<profile>` is the profile
id with every character other than a letter, a digit, an underscore, a dot or a hyphen replaced by an
underscore): the notes are frozen at the yes and accept only such batches, and after a compaction a profile
already answered is not asked again.

## No test framework found — short-circuit

If phase 1 found no test framework at all, write only `config.json` (step 1) and
`project-profile.md` (step 3, stack/entry-points/architecture sections only — the
framework-dependent sections are omitted with a note), commit them (step 9), then stop and
report: "no test framework detected; `qa-bootstrap-framework` is planned for v1 to build one
from scratch. Re-run `qa-onboarding` once a framework exists." Skip steps 2, 4–8 entirely. Step 9's `close`
still reads the config and refuses a config with no profile, so before it record the gap nobody asked about:
`project_decisions.py --root . add-finding --essence "no test framework recorded: profiles stays empty" --scope
local-urgent --witness "phase 1 found no test framework" --idempotency-key no-test-framework` (a person who was
asked and answered gets `project_decisions.py --root . add --field-ref /profiles --essence "<what they said>"
--asked "<the question as it was put>"` instead).

## 1. `config.json`

This is the fill that makes the proposal's `proposed_config` at phase 3 for a project with no
configuration; the proofs at the end of this step run on the config once `--phase early` has
written it. Start from `references/templates/config.json`; keep `schema_version: 1`. Fill from
discovery + interview: `app_root`, `code_repos`, `protected_app_paths`, `test_locations`
(topic 1c's answer, as given, relative to `app_root`; `[]` when none were named), `tests_root`,
`cases_root` (phase 1's case-store candidate as topic 1b confirmed it, relative to the
project root; empty when the project keeps no case library and cases stay per story),
`case_id_form` (the id form phase 1 noted in the store's file names, as topic 1b confirmed it:
a template of literal text plus `{ticket}` and `{nnn}`, e.g. `{ticket}_TC_{nnn}` for
`TP1-13797_TC_001.md`; `""` when the ids are the default `TC-001` or there is no store; a
form the code cannot read is reported by `readiness.py`, not guessed at),
`test_command_templates` (one_test/suite/quiet, with `<test-file>`), `run.reporter` and
`run.report_path` — **how a run becomes machine-readable on this stack**: pytest needs
nothing (the runner adds `--junitxml`), and every other framework needs the report flag in
the project's own command (`dotnet test --logger "junit;LogFilePath=…"` or the TRX logger, `ng test
--reporters junit`, `jest --reporters=jest-junit`) plus the path to read it from. Without
it a green run of 10 .NET tests is recorded as `not_executed` and a failing one as a broken
launcher, which is exactly what one project spent its stories rebuilding by hand from raw
logs, `environment` +
`environments[]` (phase 2 topic 2), `test_data` (topic 3 — one key per lifecycle fact;
every key carries an answer or the literal `unknown`, never an empty string left behind by
a question nobody asked), `adapters` (ticket/test_management/vcs — reachability
only, per `references/adapters-read.md`; `status: "configured"` is written **only for what topic
7 actually probed in this session** — a CLI that answered, a connector that returned a
ticket; anything else is `"not configured"` plus its deferral, because `readiness.py`
re-probes a command adapter and a config that claims more than the machine can do turns
into a halt at S0 rather than a warning here; `adapters.ticket.method` carries topic 7's
*second* answer, how this session **reads** the tracker, and it is a direct API only:
`command` · `mcp_tool`. `agent`/`skill` is legacy for reading and is not written into a new
config — an assistant cannot answer a second key, so the scout loses the parent, the linked
tickets and the attachments; a project with no direct route is `not configured` with that
reason. An assistant is written as a **write** channel instead, below),
`external_writes` (phase 2 topic 8 — default
stays `{"bugs": "markdown", "cases": "markdown"}` unless the team named a tracker; a named
tracker also gets `external_writes.channels.<name> = {method, invoke|command}`, since how a
channel is *written* is a separate fact from how the tracker is *read*; a tracker channel
also carries `channels.<name>.writes` and, for bugs, `bugs_project`, and the
`tracker_write.py` receipt from phase 2 says whether that right was confirmed),
`requirements_sources` (phase 1's section of that name, as the summary showed it: source_id, kind, locator, status, evidence_refs and, when not the tracker's, auth_type, secret_ref, username_ref as names only; `[]` when none were found; a tracker the factory has no client for (anything but Jira with direct_api) writes its route in method and invoke_or_command_ref, proved once in this session on one real key, names only and never a value, and when topic 7 answered `command` the row takes the same command; an agent, a skill or an MCP tool is a write channel, not a read route: status unavailable with that reason),
`strategy_documents` (topic 8's exact-file permissions and provenance), the legacy
`factory_may_edit_strategy` compatibility value, `pre_commit_commands`, `format_changed`
and `format_all` (never one key doing both jobs), `records_policy`, canonical
`execution.parallel`,
`run.levels` (below), `git_conventions`, `dod` (topic 9), and the canonical `impact_scale`
unless an approved project mapping overrides it. A
gap answered "later" is written as `""`/`[]`/`{}` in the field, **plus** a `[DEFERRED: …]`
marker in the matching strategy doc (never a silently invented value). **`execution.runtime_probes` is not written by hand.** A stand the factory must identify by
content (a docker stand: the project's tests run against a container, not against the local
checkout) gets its entry from `runtime_probe.py --suggest --profile <id> --write`, which reads
`environments[]` and `implementation_repos[]` from the config just written, finds the container
itself, verifies the entry once, and asks you exactly one thing — **which container runs the
application** — when more than one is up. Without that entry the story's first typed run is
refused at S5 with "the factory does not know how to identify what the stand runs", and on
TP1-13797 the automator wrote the probe by hand inside its dispatch, which the next
automator could not repeat. **A device stand** (an `environments[]` row that names a `surface` whose row in `references/surfaces.json` is driven by a driver): right after the row is written, run `runtime_probe.py --suggest --write --profile <the native profile's id> --environment <the stand's name>` — it asks docker nothing and writes the entry with no container; without the entry the S5 run of that profile is refused for want of a probe. Write the sign-in element the person gave as `manual_capture.login.app` = `{"sign_in_selector": "<strategy>=<value>"}` (nothing when they did not know it). Then prove the stand once, with the person present: `python "${CLAUDE_PLUGIN_ROOT}/scripts/device_stand.py" --project-root . --json --deep` (it opens and deletes one session on the device). When its `verdict` is `ok`, write `environments[].device_probe` = `{"checked_at": "<its checked_at>", "state": "ok"}`; when it is not (no device, no driver server), write nothing there, put one line in the summary naming the failed check, record it with `add-finding`, and go on: no device never stops the onboarding and is never written as `ok`. A project onboarded before this, with no entry, is not left to that refusal: gate A of its first story derives the entry from the running stand and registers it, and a refusal at S4 or S5 names the command (`runtime_probe.py --suggest --write --profile <id>`) itself. Whatever is written
here, "Prove the report once `profiles[]` are written" below proves it on one existing test
right now, with the person present, and the gate A rehearsal proves it again before the first
story is planned as the safety net (a profile that still writes no report the factory can read
becomes a card there) - so an answer given now is checked by a real run and not taken on trust.

**`requirements_sources` of a project with a configuration.** The migration plan keeps the value on record as it is and does not ask for it, so after `--phase early` add the rows the summary listed to the written config in place; a row already there stays as it is and is never removed without the person's words; `[]` when none were found.

**The shape of a profile row is `references/profile-shape.json`** (`${CLAUDE_PLUGIN_ROOT}/references/profile-shape.json`):
`commands` is an object keyed by command name, never a list; the seal in phase 3 refuses any other shape.

**The install command is written with the other commands.** When topic 5 of the interview got an answer to "which
command brings the project's environment to its lock", write it into the selected profile as `commands.install`
(`{"kind": "setup", "argv": [...], "cwd": "<the folder the person runs it in, relative to the project root>"}`: no
`scope`, no `reporter`, no `selectors`, and no `repo_id` or `framework_adapter` even under `extensions.execution`
schema 1: a `setup` command is printed, never run). This is the ONE place that key is written; no other step invents it. No answer:
write no `install` line (never an empty argv). It is a command the factory PRINTS beside the pair of versions when the
project's installed libraries differ from its lock; the factory does not run it.

**Prove the launcher once `profiles[]` are written.** Run
`python "${CLAUDE_PLUGIN_ROOT}/scripts/launch_check.py" --deactivated --json`. It collects with
each profile's own one-test command in an environment with no activated virtual environment, so
a bare `pytest` that only works inside YOUR shell shows up now, and it writes nothing. `removed`
in its answer names the variables and PATH entries it took out (an always-active conda `base` is
taken out too: read it before trusting a `failed`) and says why a prefix was left alone. Each
profile answers `ok`, `failed` or `not_checked`. `not_checked` says why and is neither a pass nor
a failure: `gate_rehearsal.skip_collect`, or a runner with no known collect form (`npx jest`,
`npx playwright test`, `dotnet test`) unless the profile writes its own `commands.collect`, which
is then the command probed. On `failed`, read `cause` and `evidence` and choose the project's
own launcher: a **wrapper argv** such as the package manager's `run` (`poetry run pytest ...`,
`uv run pytest ...`, `npx ...`), never an absolute interpreter path (A20). Rewrite that
profile's `commands` argvs and `test_command_templates`, then run the check again. Still
`failed`: `project_decisions.py add` records a question that was put to a person, so write it
only if you asked one (which command starts the project's tests):
`project_decisions.py --root . add --field-ref /profiles/<n>/commands/one_test/argv --essence
"<profile-id>: <cause>, <evidence line>" --asked "<the question as it was put>"` (`<n>` is the
profile's place in `profiles[]`, counting from 0). If you changed the profile yourself and asked
nobody, `--asked` would be an invention: record a finding instead, `project_decisions.py --root
. add-finding --essence "<profile-id>: <cause>, <evidence line>" --scope local-urgent --witness
"launch_check.py --deactivated --json: <evidence line>" --idempotency-key launch-<profile-id>`,
and go on. The check runs the project's `conftest.py` at collect, as the gate A rehearsal does. An `ok` profile may also
carry `broken_files` (`[{path, head}]`): its collect went on past test files that fail to import. Relay them to the person
by path and cause (one line each, the count if there are many) as files the project's runner could not collect - the
launcher is fine and the profile stays as written; those files are not a launch failure and not yours to repair.

**Prove the report once `profiles[]` are written.** A profile whose run writes no report the factory can read is
recorded as not executed at every story, however green its log (TP2-2553), so the factory finds out now, with
the person here. `onboard_apply.py --apply` (phase `early` or `all`) runs the probe ITSELF right after it writes the
profiles and prints it as `report_probe` in its JSON (`--no-probe` skips it); that print comes BEFORE the launch check
above. **Show nothing from it, and ask nothing, until the launch check has run.** A proposal is shown only after the
launch check; if the launch check repaired a profile (rewrote its argvs), run the probe below again FIRST and show that
output, never the earlier one - a yes applied before a repair would be lost in the in-place rewrite. With no repair,
relay each entry of `report_probe.person_text` as it stands, one proposal at most per round. After that you run the probe
yourself only to ask again - after a profile's "no", and after answer (a) or (b) below:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_probe.py" --root . --probe-profiles --proposals-dir <a temp folder OUTSIDE the project> --json
```

It runs ONE existing test through each profile's own one-test command (the gate A rehearsal's own step; the
report goes to the OS temp folder) and writes nothing into the project but the proven-report record gate A
reads. Per profile it answers `report.state` and the next `move`; read the JSON, never the progress lines:

- `nothing`: proven. Say nothing.
- `tell` (no test, timed out, launcher missing, not checked): say its `says` line in words, once. Gate A's card
  asks again at the first story. Nothing is proposed.
- `do_it`: a known one-flag cure that RAN GREEN on this machine and that S5 would accept. Show the sentence
  `onboarding_probe.py --question <proposal.path>` prints, as it stands (it is rendered from the sealed file: the
  yes binds to those words), and ask `yes / no`. Only an explicit yes counts. On `yes`:
  `config_contract.py --root . --record-approval <proposal.path> --approval-ref <proposal.approval_ref>
  --evidence-ref <the person's words in the transcript>`, then `config_contract.py --root . --apply <proposal.path>
  --approval-ref <proposal.approval_ref>`, then the probe again (the confirmation run). A second yes on an applied
  proposal answers "already done". On `no`: record nothing, the command stays, and run the probe again with
  `--profile <id>` for each profile not yet asked. Never edit a sealed file and never write the config any other way
  (`onboard_apply.py --apply` refuses such a file, with or without a ref: one approval changes one key, and
  `config_contract.py --apply` is the door that writes only that key).
- `waits_for_turn`: another profile's question is open. One "Do it?" per profile: its proposal is made, against the
  config as it is then, by running the probe again after that one is answered.
- `explain_and_ask`: no cure is known, or the cure was run and did not prove. Say in words what was run (the
  profile, the test), what came out (`report.why`, the one `detail` line) and why no change is proposed (`says`,
  `cure.words`, `cure.needs`: a package or a config edit is the person's, nothing here installs one), then offer three
  answers: (a) "here is the command that writes a JUnit report: <line>" - run `onboarding_probe.py --root .
  --profile <id> --command "<their line>" [--kind junit-xml|trx] --proposals-dir <dir> --json` (a path of this
  machine in it is refused in words, A20: say so and ask for one relative to the project); a proven command comes
  back as a `do_it` with its own sentence, asked as above; (b) "I fix it myself" - run the probe again for that
  profile (`--profile <id>`) when they say it is done; (c) "not needed now" - record NOTHING: the profile keeps its
  command and gate A's card asks again at the first story. Ask the explaining question at most twice per profile
  (counted with the `times_asked` of that profile's batch in the notes), then take (c).
- `direct_form`, whatever the move: this command is the project's own script; the factory reads no script, so per-test
  selection and the probe stay "not probed" on it, by name. Ask once, closed: (a) "here is the direct test command: <line>"
  - run `onboarding_probe.py --root . --profile <id> --command "<their line>" --proposals-dir <dir> --json` (proven comes
  back as a `do_it`, asked as above); (b) "keep the script": tests run as they do, probes on this profile say not probed;
  (c) "not needed now". Record nothing on (b), (c).

With no person present the probe may run, its `do_it` results are only reported: a headless approval of a changed
command is refused by code. The in-place launcher repair above is not changed by this step.

### The `environment` block — only the keys the login actually used

Write `environment.access` from topic 2's answer, as names and codes: `kind` (one of
`harness_command` · `local_login` · `oidc_password` · `bearer_env` · `none`), `command` or
`url`, the `*_key` names that kind needs, and `unauth_status` — the codes an unauthenticated
request answers on a healthy stand. Every value here is a variable NAME or a URL; a secret
value never enters `config.json`. For `local_login`, `access.user_field` / `access.secret_field`
come from the login proof below, not from a guess.

`user_key`, `base_url_key` and `secret_keys[]` carry **only names the env file holds right
now and the login actually used**. Everything else phase 1 found — a key read in code that
the file does not hold — goes to `integrations[]` as `{name, keys, required_by?, read_at?,
credential_alternatives?}` (`owner` is no longer written) with the proposal's `required_by` and
`read_at` from phase 1; `keys` is the union of `credential_alternatives`. A row with no area
is legal when it carries `read_at`. A missing key blocks that area and not the stand. Nothing the factory sets for the project (`HEADLESS`, `QA_FACTORY_*`) and no
client-library switch (`AWS_PROFILE`, `*_SESSION_TOKEN`) belongs in `secret_keys` or
`extra_keys` at all.

The accounts topic 2 confirmed are written as `environments[<stand>].credentials_by_role["<role>"] =
"<USER_KEY> / <SECRET_KEY>"`: only confirmed roles and only names. A role named `default`, `env:...` or
`created:...` is never written (a capture reads those forms before any role). The same record can be made
later, from a gate, with `project_decisions.py --root . stand-account --stand <name> --role "<role>"
--user-key U --secret-key S --words-file F`.

How a manual capture signs in by code follows what you recorded above (`manual_capture.http_login_source`); only the cases below ask for one more line of config:
- The login proof confirmed `local_login`: write nothing, the capture signs in at the `access.url` you recorded.
- `kind` is `harness_command` (or `bearer_env`, `oidc_password`) and there is no `manual_capture.login.http`: the capture refuses before it sends anything, so ask the person ONE closed question: `Does the application sign in by a request that returns a token? yes, at <path> / no, only through the sign-in page / I do not know`. "Yes" → write `manual_capture.login.http` as `{"path": "<path>", "token_field": "<the answer's token field>"}`; "no, only through the sign-in page" → write `manual_capture.login.http` as `null`; "I do not know" → write nothing (the capture then refuses with the key to record, and says nothing was sent). No other kind is asked this.
- The sign-in PAGE of the application is not at the factory's default address: a present `manual_capture.login.ui` replaces the factory's recipe WHOLE, so copy the `login.ui` object of `references/manual-capture-steps.json` into `manual_capture.login.ui` and set its `landed.url_not` to the fragments of YOUR sign-in page address. Without it the login window closes at the first step on any other sign-in page, and the screenshot shows the account. Then correct what is the factory's guess: path, username, password, submit, landed.session_cookie (or remove it), and remove local_storage. If you cannot read that form now, write nothing but tell the person that screens sign in through fill-account.

Then **prove the scheme with one real login**, and record the proof rather than describing
it:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/config_contract.py" --root . --check-environment
python "${CLAUDE_PLUGIN_ROOT}/scripts/env_probe.py" --project-root . --json
```

The first answers whether this config survives its own probe — every `secret_keys[]`,
`user_key`, `base_url_key` and `access.*_key` present in the env file, no factory-set key, no
integration key without `required_by` or `read_at` — and names each offender with the two places it may go
instead. The second logs in by the recorded scheme and returns `liveness`, `login` and
`keys`. Write `login.record` WHOLE as `environment.access.login_probe` (it is the ready object: the
configured login key name, the code, the outcome `ok|failed|skipped|not_recorded`, the date, and
the body field names when the login learned them, and seconds, how long a harness-command login took; copy it, do not assemble one by hand; when the
output has no `login.record`, no login key is configured and nothing is written), and nothing about
this in prose. Only a record whose `outcome` is `ok` reads as a proof afterwards. When `login.accepted_fields` is present and the block names no field, write the two
names into `access.user_field` / `access.secret_field` too; when the block already names them,
change nothing. A sentence in `verified` saying the stand was reached is what a later probe
cannot check, and one project carried three generations of such sentences while its
`secret_keys` held keys that were never there.

A config whose keys fail either command **is not left standing**: no other step of this
phase proceeds on it. Name the keys and the two places they may go, fix the block, run both
again, and only then continue. This is the factory's own defect, not a repair to
hand the person: "add these four keys" for keys no test needs is exactly the halt this step
exists to prevent. When the person's answer is that a key stays anyway, that is their word
and it passes — record it with `project_decisions.py --root . add --field-ref
/environment/integrations --essence "environment integrations kept by the person's word: config.json" --asked
"<the question as it was put>"` and write the key where they said it belongs, with its `required_by` or `read_at`.

Two cases of a failed login. (a) `login.refusal: body_shape` is a config problem, not a stand
problem: the endpoint refused every body the factory knows and asked for fields it was not sent;
`login.complained` lists them. Write them into `access.user_field` / `access.secret_field` (you
judge which is which), then run both commands again. (b) Any other `login: failed` (including a
400/422 without `refusal` - the stand judged the account), or `liveness: dead`, is a stand
problem: keep the block, write `login.record` whole as `login_probe` (its `outcome` says it failed and
its `status` is the code that came back), and carry it into the phase-3 summary as a `[DEFERRED: …]`
with its backlog row.

When the person confirmed a variable of `frontend_candidates` as the stand's UI address in topic 2, write it as
`environment.frontend.url_key` (its NAME, never the address); the `env_probe.py` line below is the re-check. When topic 2
confirmed the base key as the UI address (the UI is on the API's own address), write url_key = <base_url_key>: that is legal, no check
refuses it. Write `api_path` when a key on the same origin (from `frontend_same_origin.keys`) or the code names the API's path under
that origin and its answer is the API's own JSON; otherwise leave `api_path` empty. Leave `url_key` empty only when the project has
no UI tests and no UI profile. With several
`environments[]` rows the block key is not read: the address goes into the entry of the stand (`frontend.url`), and
`project_decisions.py stand-frontend --stand <name> --url <address> --words-file <file>` records it. When discovery found a frontend for the stand (a UI that proxies to the API), also write
`environment.frontend = {"url_key": "<the env key holding the frontend's address>", "api_path":
"<a path through the frontend whose answer is the API's own JSON, for example /api/v1/config>"}`
(a stand entry in `environments[]` may carry `frontend {url, api_path}` instead). No frontend found =
leave it empty: the stand is API-only (when `env_probe.py` prints a `frontend: not configured; <KEY> ... holds an http address` line, judge that key: write it as `url_key` only if it is this stand's frontend). A path whose answer is the frontend's HTML page proves nothing
about the API.

### `run.levels` — where the project's OWN tests sit in the pyramid

From the layers discovery found (the same ones you are about to write into
`framework-rules.md`), map each pyramid level to the path patterns of the tests that live
there:

```json
"run": {"parallel": false,
        "levels": {"unit": ["tests/unit/**"],
                   "component": ["frontend/**/*.test.tsx"],
                   "api": ["tests/api/**"],
                   "e2e-ui": ["tests/e2e/**"]}}
```

Levels come from the closed list `unit · component · api · integration · e2e-ui`. This map
is **only for the tests the factory did not write**: a test the factory writes carries its
level through its plan row, and needs no pattern. A layer you cannot place — leave it out;
its tests show on the board as `level not recorded`, which is the truth. Never write a
pattern you are not sure of: a wrong level is worse than an admitted gap, because the
pyramid then reports a shape the project does not have.

**Every path in this file is relative to the project root, and converting them is part of
writing the file.** Discovery reports what it found as an absolute path and a human answers
with what their terminal shows (`/Users/anna/Projects/testproject1`); neither goes into the
config in that form. Express each one against this repository's root before writing it
(`..`, `../testproject1`, `../../testproject1-ui`) — `app_root`, `tests_root`, `code_repos[].path`,
`protected_app_paths[]`, `test_locations[]`, `environment.env_file`, `journal_path`, and any path inside a
`test_command_templates` command. This file is committed: an absolute path resolves nowhere
on the next machine and carries a colleague's username into the repository. Audit **A20**
fails on one. A checkout that genuinely cannot be reached relatively (another drive) is a
`[DEFERRED: …]` marker plus its backlog row — never an absolute path written down anyway.

**Where the application code lives** comes from topic 1 and is written the way that topic
collected it. Tests and application in one repository → `app_root: "."` and
`protected_app_paths` naming the application directories (`["src"]`), `code_repos` left
`[]`. Separate repositories → one `code_repos` entry per application repo (`{name, path,
default_branch}`, `path` relative to this repository's root, e.g. `../testproject1`), `app_root`
set to the repositories' common parent, and `protected_app_paths` relative to that parent
(`["testproject1/src", "testproject1-ui/src"]`) so P-00 still covers real directories. Nobody could
give a local path → `code_repos: []` **plus** a `[DEFERRED: application repo paths]`
marker in `project-profile.md` and its `factory-backlog.md` row; never `app_root: "."`
left standing as if the application were here.

**Test locations inside the application code.** After `test_locations` is written, run
`python "${CLAUDE_PLUGIN_ROOT}/scripts/test_locations.py" --root . --check --json`. An entry
with a `problem` (a grammar fault, or one that covers a whole protected folder) is fixed or
asked again before the phase goes on: an entry that opens nothing is a silent hole.

## 2. `strategy/test-strategy.md`

No template exists for this file (v0 project-strategy documents are generated inline, not
from `references/templates/`).

**One fact, one file.** This document and `framework-rules.md` (step 4) reach disjoint
audiences — `inject-map.json` gives this one to the strategist, the case designer and the
retro analyst, and that one to the automator and the code critic — so no role ever sees the
same paragraph twice, and neither file is a summary of the other. The split is by **verb**:
what a *plan is decided with* lives here; what *test code is written and reviewed against*
lives there. A planning role that needs a code rule opens `framework-rules.md` — every role
has Read. Audit **A21** fails when a section heading appears in both files, because the
failure mode is not "someone copied a paragraph" but "two copies drifted and now the
project has two answers": the pilot's pair carried four shared sections whose
*Team conventions* tables had already stopped matching on the day they were generated.

Sections:

- **Scope** — one line: functional testing only in v0 (the phase-0 announcement, restated).
- **Test layers** — from discovery: framework(s), layer(s), where each lives, and the scale
  (file and test counts). *What exists and how much of it* — how a test in a layer is
  actually written is step 4's.
- **Git conventions** — branch/commit/MR pattern + `pre_commit_commands`, the narrow
  `format_changed` command a role may run and the wide `format_all` it may not, and
  `records_policy` for where the shared factory records are committed.
- **Risk and impact scale** — two halves, in this order. First the impact-class map in force, as a table
  `Impact | Priority | Severity`; `[DEFERRED: impact scale not set]` stands in its place only when the targeted question
  about a preserved legacy numeric value was asked and not answered, with its DD (step 8). Then topic 4's risk areas. `scripts/sizing.py` sizes every story from
  the `**P1 areas.**` paragraph: it reads from that bold label up to the `**P2 areas.**` label (or, when that label
  is missing, to the end of the file), splits on `·`, and raises a requirement that shares a word of five or more
  letters with a phrase. So `**P2 areas.**` always follows `**P1 areas.**`, both labels are written exactly as shown,
  and nothing but area phrases stands between them:

  ```
  **P1 areas.** <area> · <area> · <area>.

  **P2 areas.** Not named by the team.

  **P3 areas.** Not named by the team.

  Source: topic 4 of the onboarding interview, batch <batch id>, <YYYY-MM-DD>.
  ```

  - Each phrase is one area of the product in the team's terms, in English, most important first. It carries at
    least one word of five or more letters spelled out: write "single sign-on (SSO)", never "SSO" alone, because
    a phrase of short words matches nothing. A name in another script is written in English; the person's own
    words stay in the words file.
  - No `·` inside a phrase (use a comma or "and"). No emphasis, ranking or comment inside the paragraph: every word
    there can raise a requirement. Areas the team named as P2 or P3 replace that line's "Not named by the team.",
    joined the same way. Areas found in a project document and confirmed name that file in the Source line.
  - A damage class named as a risk ("data loss", "money") is not an area: the impact-class map above already weighs
    it. Say so in the summary; do not write it as a phrase.
  - Answer (b), and a whole-product answer ("everything is critical", taken as (b)): no labels at all, one sentence:
    "No area stands out: the team named no part of the product as riskier than the rest (topic 4, batch <batch id>,
    <YYYY-MM-DD>). Every requirement is weighed by its own impact class." A whole-product answer quotes the
    person's words in that sentence.
  - Deferred (answer (c) or silence, with no paragraph on record): no labels; the line
    `[DEFERRED: risk areas not named]` on its own, and its DD (step 8).
  - Topic 4 never asked: nothing about areas, and no marker.
  - Re-onboarding: a `**P1 areas.**` paragraph already in the file is topic 4's default. Confirmed, the topic not
    asked again, or answered (c) or silence: the paragraph, from that label to the next `## ` heading, is kept byte
    for byte, wherever it stands, with no marker and no DD. The one change made to it is a
    `**P2 areas.** Not named by the team.` line after the P1 paragraph when no P2 label follows, shown in the
    phase-3 summary. Changed by the person: the new paragraphs replace it, shown the same way. Never write a second
    `**P1 areas.**` label: the reader takes the first.
- **Adapters and external writes** — the chosen ticket/TMS adapters and the `bugs`/`cases`
  channels, stated plainly (roles read this from `config.json`, this section is for humans).
- **Environments** — which stands a plan may target, one line each; the detail is
  `project-profile.md`'s.
- **Definition of done** — topic 9's sentence.
- **Case ids** — the id *form* a case file uses, restating `config.json` `case_id_form` for
  humans (e.g. `TP1-13797_TC_001`); the config owns it and roles read it there. Where that
  id goes inside test code is step 4's half; write each half once.
- **Where the code rules live** — one line pointing at `framework-rules.md`. A line, not a
  digest: run commands, the assertion library, fixtures, page objects and the team's code
  conventions are its sections, and a second copy here is exactly what A21 stops.

## 3. `strategy/project-profile.md`

The **one** document about this project — what it is and how to work with it. There is no
separate product passport: a document no role is injected with is a document nobody reads,
and the product sections belong here, where `inject-map.json` delivers them to three
roles and the scout's brief names the file. Inline sections, no template:

- **What this product is** — business goal and primary users in one or two sentences
  (topic 10), and the source of truth for requirements: where specs and tickets actually
  live. `unknown` is a legitimate value where the team has none, not a gap to paper over.
- **Components and entry points** — stack, the services/screens/APIs discovery actually
  read (phase 1 in this repository, phase 2b in the application repositories), and how each
  is reached. Anything phase 2b could not read because no checkout was given is written as
  "not read: no local checkout", never as an absence.
- **How the app runs locally** — the commands or compose services that bring it up. The
  factory records runtime probes, build inputs and authorized preparation actions.
  Follow `references/environment-preparation.md`; never generate a build-on-every-run default.
- **Test data** — one line per `config.json` `test_data` key, in that order: accounts by
  role, seeds, generators, real data and the masking rule, who cleans up, shared records
  (or "none — every test creates its own"). Mirrors the config exactly: humans read this
  file, roles read the config, and the two must not disagree. A key answered `unknown` is
  written as `unknown` here too — a blank line reads as "nothing to say", which is a
  different claim.
- **Environments** — the `environments[]` list, human-readable.
- **Fragile Areas** — empty at first onboarding, carried forward on re-onboarding.
- **Out of scope — manual-only** — flows the team already knows require a human (external
  email/SMS/payment, if named); any unprompted non-functional observation from phase 2,
  labeled "out of scope in v0".

**Re-onboarding a project that still has `strategy/product-passport.md`** (written by an
earlier version): fold its content into the first two sections, then record the fold (section 0,
`--fold`). The file is deleted by the final apply half, after that receipt, because the phase-3
summary listed it. Two documents describing one project is the state this merge exists to end —
leaving the old file in place recreates it; never delete it by hand.

Paths named in this document follow the same rule as the config's (step 1): relative to the
project root, never a home directory — A20 reads the strategy documents too, because a
pasted `/Users/<name>/…` is as unportable in prose as it is in JSON.

## 4. `strategy/framework-rules.md`

The file the automation and code-critic roles read before writing or reviewing test code.
It **owns** everything about how code is written, the way step 2 owns everything about how a
plan is decided. Nothing here mirrors that file and nothing there mirrors this one (A21).

Inline sections:

- **Layers and idioms** — how a test in each layer is actually written: the client and the
  util wrappers everything goes through, page-object rules and selector priority, the
  fixture tiers and where cleanup belongs, where test data lives. Step 2 says which layers
  exist; this says how to add one to them.
- **Readers of the exact state** — for each surface, the helpers that read its exact state
  (the page-object methods, the utils, the fixtures), by name: the code a new helper must
  be checked against before it is written beside them.
- **Case ids in code** — where the id goes in a test (docstring or comment, which one is the
  convention going forward) with one real example from this repository. The id's *form* is
  step 2's line; do not respecify it here.
- **Run commands** — the three templates from `config.json.test_command_templates`, plus
  every flag that changes *what runs* (a flag that silently deselects tests, a mode that is
  the default only in one conftest). Their only prose home: the roles that run a suite are
  the ones injected with this file.
- **Team conventions (declared by humans)** — every code-level convention from
  README/CONTRIBUTING/CLAUDE.md/AGENTS.md/docs with its source link (phase 1). Owned here,
  not mirrored: a convention constrains code, and the roles that write code read this file.
  A rule recovered from git history rather than a live file is marked as such, with the
  commit — provenance is part of the rule.
- **Confirmed conventions** — phase 1's `inferred` list as confirmed in phase 2, each marked
  *enforced on new code* or *recorded but not enforced by team decision*, with the count
  behind it (`2843 uses against 10 bare asserts`) so a reviewer knows whether a rule
  describes the codebase or aspires to it.
- **Traps** — what silently misleads in *this* repository: two config files where one wins,
  dead code that looks live, duplicate file names, a variable a script needs. Nothing
  aspirational; only what has already cost someone an hour.

## 5. `strategy/aspect-profile.md`

The project's completeness lenses — the named aspects `qa-requirements-tester` fills into
`requirements-readiness.json`'s `aspects` map at S2. `references/inject-map.json` delivers
this file to that role, so a project without it hands the role a hole (audit A9 reports it;
this step is why it no longer happens). Inline, no template: one intro line, then one
`## <aspect-name>` section each — the heading is the key the role uses in `aspects` — with:

- **Asks** — the single question this lens puts to a requirement ("which role may do this,
  and what does every other role see?");
- **Why here** — the evidence from discovery or the interview that makes it a lens for
  *this* project (an integration, a role model, a migration, an async job, a shared seeded
  stand), naming the file or the answer it came from.

Derive the starting set from what discovery actually read plus topic 4's P1 areas: an area no discovered lens
already covers becomes its own `## <area>` lens, **Asks** "does this requirement touch <area>, and what must stay
true there when it does?", **Why here** "named by the team as a main risk area (topic 4, <YYYY-MM-DD>)". An aspect
with no evidence behind it is not written: a generic lens catalogue teaches the requirements tester nothing about
this project. When discovery found no lens and the team named no area, write the three lenses every functional
story has anyway — inputs and validation, roles and permissions, failure and error paths — each marked `inferred,
not confirmed`. Whichever lenses are written (those discovery found, those the team's areas added, or the three
inferred ones), put the marker `[DEFERRED: risk areas not named]` on its own line under the intro line when topic 4's
risk question was asked and not answered (answer (c) or silence, with no paragraph on record): the same marker text
as in `test-strategy.md` and the same DD, because one question has one row, and a deferred decision always has its
marker in every file it names. Its `asked` column carries the risk-areas question verbatim (step 8). "No area stands
out", a paragraph kept as on record, or a topic 4 never asked, adds no marker.

## 6. `strategy/faq.md`

Two empty sections with a standing rule at the top: `## Owner answers` and `## Glossary`.
Note: every future gate-A/gate-B answer from the ticket owner gets condensed here by
`qa-doc-scribe`/`qa-retro-analyst` during a story — this file starts empty by design.

## 7. `records/coverage-map.md`

The map is a carried record: it lives in `qa-factory/records/` (git keeps it), not in the ignored
`qa-factory/state/` - the install moves it from there when an older factory kept it in `state/`.
No generator flag exists on `check_coverage.py` (it only reconciles an existing map against
the case files in `cases_root`, or under `qa-factory/artifacts/*/test-cases/` when the
project keeps no store of its own) and no template ships for this file, so build the skeleton directly, matching
the exact contract `check_coverage.py` parses: an `As-of date: YYYY-MM-DD` line, and one
`## Area: <name>` section per area discovery found existing cases or TMS entries for, each
with `| Cases created | N |` and `| Automated | N |` rows. No existing cases anywhere → a
single line "no coverage yet" plus the `As-of date` line — not an empty file. Then run:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_coverage.py"
```

Expect `OK: no local cases …` on a fresh onboarding (nothing to reconcile yet) or a clean
`OK: coverage-map agrees with …` when discovery found existing cases. A `REJECT` here means
the skeleton's counts do not match what discovery actually found — fix the skeleton, not the
script.

## 8. `obligations.md`, `factory-backlog.md`

From `references/templates/obligations.md` and `references/templates/factory-backlog.md` —
the empty table structure and rules are copied verbatim by `--phase early` when the project has
none; never overwritten when it has. Every deferred interview answer from
phase 2 (and every deferred `config.json` field from step 1) gets **both** traces: a
`[DEFERRED: <essence>]` marker at the hole in the document itself, and a paired `DD-n` row
in `factory-backlog.md`'s "Deferred decisions" section with a concrete ripeness trigger
(never "later").

The `DD-n` row's **`asked` column carries the question verbatim and the batch it was asked
in** ("batch 1: where are the application repositories checked out locally?"; both are in `<notes>/interview.yaml`:
`batch <id>: <the question as it was asked>`). A row whose
`asked` cell is empty or a dash is a violation — `audit_factory.py`'s A13 fails on it —
because a deferral for a question nobody put is a skipped question wearing a deferral's
clothes. If a hole has no question behind it, the fix is not a better row: go back and ask,
or write nothing at all.

A deferred risk-areas answer is ONE row for both files: `project_decisions.py --root . add --field-ref
doc:strategy/test-strategy.md#risk-and-impact-scale
--essence "risk areas not named: strategy/test-strategy.md (Risk and impact scale), strategy/aspect-profile.md"
--asked "batch <id>: <the risk-areas question as it was put>" --trigger-type story_count --trigger-value 3` (it
comes due after three sized stories, `project_decisions.due`). The field ref is a document ref
(`doc:<path under qa-factory>[#<anchor>]`): the hole is a paragraph, not a key of `config.json`. Its later resolution names
both files and gives no value: `project_decisions.py --root . resolve --id <DD-n> --words-file <file> --resolution-ref
<evidence> --marker-file qa-factory/strategy/test-strategy.md --marker-file qa-factory/strategy/aspect-profile.md
--marker-text "[DEFERRED: risk areas not named]"`. Write the paragraphs into both files with the marker line left where it stands;
the resolve (`project_decisions.py resolve`) removes it, and the generator never removes the marker. A document ref writes
nothing into `config.json`; the areas live in the paragraphs of the two files, and `/impact_scale` is never a ref of this row,
because it would overwrite the class map.

A deferred impact scale is ONE row too, and it exists only when the targeted question about a preserved legacy numeric
value was put and not answered (an answered one is written as the map; one never put is a question to ask, not a row):
`project_decisions.py --root . add --field-ref /impact_scale/<class>
--essence "impact scale not set: strategy/test-strategy.md (Risk and impact scale)"
--asked "batch <id>: <the question as it was put>" --trigger-type manual`, with one `--field-ref /impact_scale/<class>` for
each preserved numeric class (several classes are still one question and one row). It is `manual` because readiness
already refuses a numeric value on every run, so the hole is loud without a timer. Its later resolution gives the exact
`{"priority": ..., "severity": ...}` value of every class in `--field-values` and names `qa-factory/strategy/test-strategy.md`
as `--marker-file` with `--marker-text "[DEFERRED: impact scale not set]"`.

## 8b. Keep run logs out of the repository

A story's raw run logs, the S5 work fragments and everything machine-local under
`qa-factory/state/` are for the audit on this machine, not for the repository: on the first
pilot the logs alone were 79% of what a five-test story committed, and a re-onboarded project
showed 338 untracked state files (telemetry, host receipts, cost, turn counters).

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/project_gitignore.py" --root . --write
```

`--phase early` runs it. It writes its block as one contiguous piece, by explicit path: it takes
out the one line the first generation wrote and any partial block of an older version, puts the
block back whole at the end, and touches no other line (the project's own rules keep their places).
The block names `work/evidence/` and `evidence/` of a story (the manual evidence stays on the tester's machine and never goes into a commit), `work/*fragment*.json`, `work/impl-diff*.txt`, and ONE line for the
machine-local folder `qa-factory/state/`; `qa-factory/records/` (journal, coverage map, estimation
ledger, decisions, approvals) has no line and stays visible to git. Nothing else in `work/` is
ignored: a story stopped mid-way commits its `work/` deliberately so it can be resumed days
later (see `phases/s8.md`).

An existing config whose `adapters.ticket.method` is `agent` or `skill` next to a full
`direct_api`: run `ticket_adapter.py --migrate-method --config qa-factory/config.json`.
Reading already goes through `direct_api` whatever the label says; the migration only
rewrites the label to `api`, and the assistant stays the write channel.

## 9. State, dashboard, readiness, commit

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboard_apply.py" --root . --proposal <sealed.json> --apply --approval-ref <ref> --phase final
python "${CLAUDE_PLUGIN_ROOT}/scripts/audit_factory.py"
```

The final apply half runs `factory_dashboard.py` and `readiness.py --write` itself (run either alone
again whenever you need to). The audit judges what this phase just wrote, so run it **before** the commit and fix what it
names rather than committing and filing it. The two rules this phase trips are A13 (a
required topic with neither an answer nor a deferral) and A20 (a machine-local path); both
are defects in the generated files, not findings about the project.

The dashboard renders on empty data (a fresh onboarding has no runs, cost, or bugs yet —
that is expected, not an error). `readiness.py --write` computes and writes
`qa-factory/state/readiness.json` from its capabilities (the list is `readiness.py`'s
`CAPABILITIES` — ticket and tracker-write access, repositories, VCS, environment, host
hooks, config schema); an `unknown`/`missing` entry
here is fine at onboarding time — `qa-story` checks readiness again per-story with
`--require`. That holds for those entries, not for a failed `readiness.py` and not for a profile with no
command that runs one test: `close` (below) refuses on either.

**Let git go of what the ignore block now covers** — right after the final half, before the audit
and the commit. The apply result's `tracking.git_rm` (the plan's `tracking.git_rm` held the same
lines, and the "yes" covered the text that named them) has one line `git rm --cached <path>` for
every path git tracks inside `qa-factory/state/`, for every tracked generated file the block now
covers (`tracking.tracked_ignored`: evidence, fragments, impl-diff), and for every tracked file this
install deleted or moved. Run each line as it stands, from the project root: they only stop git tracking the
files (the files themselves are not touched by them). This step is yours - `onboard_apply.py`
only READS git and never writes its state. An empty list, or `tracking.checked` false with a line
saying the project is not a git repository, means there is nothing to run.

Close the notes once the audit is clean, before the commit: `onboarding_notes.py --root . close --approval-ref <ref>`.
The script is `${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py`. Read `tree` from `<notes>/progress.yaml`
first: it is the phase-0 working-tree note. The run moves to `<notes>/done/<ref>/`, stays on this machine, and is no longer offered as unfinished.
`close` first runs the config's first reader on the config as it is now (`readiness.py`, and the command that runs
one test of every profile) and refuses with one line per problem, each carrying its own door. Repair the profile
(the launch check above) and close again; what cannot be repaired is recorded with the command that line carries
(`add` after a person was asked, `add-finding` when nobody was), and then `close` passes.

Commit only when the existing conversation separately authorizes it. Approval to write the
onboarding files does not itself authorize commit or push. When commit is authorized, restate
the phase-0 working-tree note first (`tree`, read before the close): if the tree had unrelated
changes already, commit **only** `.gitignore` together with `qa-factory/`, by explicit path
(`git add .gitignore qa-factory`) — never `git add -A`: the block in `.gitignore` is what keeps
`qa-factory/state/` out of the history, so it goes in the same commit as the files it is about. Use
the message shape from `git_conventions` if one was confirmed, otherwise a plain
`chore(qa-factory): onboarding <date>`. Ask nothing about this commit — onboarding decides
it, per the design ("uncommitted onboarding is unfinished onboarding").
Apply the approved field-level merge rather than replacing config or strategy files wholesale.
Preserve human values not listed in the summary, unknown adapter extension keys, and previous
task revisions. Generate `profiles[]`, `implementation_repos[]`, and
managed dependency records from confirmed facts. For each `adapter_id`, write under `adapter_capabilities` the capabilities the discovered tests of that profile really exercise, and name them in the summary so the one yes covers them; a capability you cannot show from the project's tests is asked with options (`it can / it cannot / not sure`), and `not sure` leaves it out: the profile reads `unknown`, honestly. Never infer it from the framework's name. `supported_capabilities` stays the template's list unless a profile needs another word: add that word and say so in the summary. A missing framework is `profiles: []` with its deferral; readiness says `not_configured` and gate A asks at the first story.
In a project that has a device stand next to a web profile, tell the planning roles that a case run on the device carries the device profile's `profile_id` as `execution_profile_id` in its plan row: without it the web profile of the same level may take the case.

**One root per profile, and a flag once.** A profile's `roots.test` is the folder of ITS tests. No two profiles get
the same `roots.test`: S5 and the gate rehearsal tell which profile runs a test by the deepest root that holds its
file, and two profiles over one folder are refused there (a UI profile and an API profile both at `tests/` ran the
UI tests under the API command, TP1-12586). When discovery finds the kinds in separate sub-folders
(`tests/api`, `tests/ui`), write each profile's own sub-folder and ask nothing. When one folder holds both and the
names under it do not tell them apart, ask the person which folder holds each profile's tests (a batch like any
question of this phase, in the form of `references/human-questions.md`) and write the answer; never write one folder
for two profiles. In the same way a flag the project's own pytest configuration already carries in `addopts`
(`pytest.ini`, `setup.cfg`, `tox.ini`, `pyproject.toml`; typically `-v`) is not repeated in a profile's `commands`
argv: a flag appears once, because a doubled `-v` changes the verbosity the factory's collect and report readers
assume (FB-7).

For an explicitly approved dependency action, use `scripts/managed_dependency.py --install`
with the approved descriptor and an authorization receipt binding the dependency id and
descriptor SHA-256 to the recorded authorization source. It executes argv without a shell, verifies the exact observed
version, and records the receipt. Never use `@latest`, install a catalogue-only dependency, or
prepare Playwright/browser tooling for an unselected web capability. An unavailable/offline
dependency blocks only that profile.
# Manual evidence capability

Generate configuration that names per-repository selectors, reporters and safe manual evidence
artifact locations. Do not install dependencies or execute tests while generating it. A collect
is not a test execution: the launch check in step 1 imports and lists tests, runs none, honours
`gate_rehearsal.skip_collect`, and runs nothing at all for a runner it has no collect form for.
One exception, and only this one: "Prove the report once `profiles[]` are written" (step 1) runs the reporter
slot - ONE existing test per profile, once, through its own command, with its report written to the OS temp
folder - because that run is the proof the step exists for; phase 3's summary lists it, so the one yes covers it.
If the runner takes ONE option for many tests, record selectors.join = {option, separator, group?} in the profile; absent means the option is repeated per test.

## Direct Jira source access

For Jira projects, an available Jira Assistant does not complete source-access setup.
Discover `adapters.ticket.direct_api` first; reuse verified access instead of asking again.
If absent, request secure local API-token setup (never token text in chat or config).
Use `references/jira-direct-access.md`. Record auth_type for the actual server/plugin,
base_url and env secret/username references. Resolution API tokens are not automatically
Atlassian bearer PATs. Keep the assistant as an additional channel. Read & Write capability
supports approved publishing but never bypasses human approval of external writes.
Verify identity, all comments and an original attachment read-only. A ticket without files
cannot prove download capability. Record missing/unverified access as a stable DD visible
in doctor and dashboard; do not call assistant-only setup fully ready. Non-Jira projects
must not be asked for Jira credentials. User approves the discovered setup summary.
