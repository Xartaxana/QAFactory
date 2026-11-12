# Phase 1 — Discovery (read-only, no questions)

Build the complete repository view with `scripts/project_inventory.py --root <project>`.
Keep every configured entry and distinct checkout visible. Merge duplicate references to
one checkout while preserving all names, roles and config pointers; keep separate worktrees
separate. Never fetch a remote or stop at the first existing repository. A missing or
invalid path remains an unresolved row for the interview.

Canon of a `qa-onboarding` phase. Read on entering the phase. **No question is asked in
this phase.** Everything here is read with `Read`/`Glob`/`Grep` and light `Bash` (`git
log`, `git branch`), and written to the run's notes for phase 2 (what remains a gap) and phase 4
(what gets written). The project's own files are only read.

On entering, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py" --root . start --tree <clean|dirty>`
(phase 0's working-tree note). It makes the notes folder, which git ignores from its first file, and prints
`{"path": ...}`: that folder is `<notes>` in every phase text. Write each row's finding into its section of
`discovery.yaml` in the notes folder as soon as the row is resolved, before reading the next row's sources;
write `notes:` lines indented deeper than the `notes:` key. A section is `state: "<word>"`, `evidence:`
(a list of `"path:line"`) and `notes:`; the states are `pending`, `found`, `gap` and `inferred`. Edit one
section at a time, and add a section of your own for a finding the skeleton has no row for. If `start`
refuses because a run is open, phase 0 missed it: go back to its step 5.

## Rule: read files, not names

A framework or convention is confirmed by reading an actual test file, not by recognizing a
dependency name in a manifest. "The project has no X" is only ever recorded after a
positive control — show that the same search method finds an X where one is known to
exist (e.g. a fixture file), before concluding the repository has none.

## Signal table

| Looking for | Where to look |
|---|---|
| Execution profiles | Real tests/config per contour: repo/test roots, framework version, adapter id/version, capabilities, selectors, reporter, named build/collect/run/typecheck/lint commands as argv plus cwd, conventions/environment/data/ownership refs, and versioned adapter extensions |
| Run commands | The actual command that runs one test, the whole suite, and a quiet/CI mode — from CI config or scripts, not invented; templated with a `<test-file>` placeholder. **Note whether it writes a machine-readable report** (a JUnit XML or TRX flag, a reporter package in the manifest, a report path in CI): that is `run.reporter`/`run.report_path`, and without it every run of this stack is recorded as `not_executed` |
| CI gates | `.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`, `azure-pipelines.yml` — extract the literal test/lint commands they run |
| Declared conventions | `README*`, `CONTRIBUTING*`, `CLAUDE.md`, `AGENTS.md`, `docs/testing*` — human-written instructions, each with a source link |
| Risk ranking | A project document that ranks areas or names fragile places — a risk register, SLO/SLA documents, incident post-mortems, an ownership map that marks critical services — read, and recorded in section `risk_ranking` with its path:line. A link to a document outside the repository is recorded as a gap with the link, not opened. Folder size, churn or test counts are never a ranking |
| Existing cases / TMS | `test-cases/`, directories with case-id file names (`TC-001.md`, `<ticket>_TC_001.md`), a TMS link in docs — only follow up on a TMS if one is actually declared somewhere; do not go hunting for one |
| How the tracker is reachable | The skills and agents available in **this session** whose name or description names the tracker (a "Jira assistant"), `.claude/agents/*`, `.claude/skills/*`, `.mcp.json`, and a tracker CLI on PATH (`jira`, `glab`, `gh`, `dmtools`) — candidates for topic 7's answer, offered as the default rather than asked from a blank page |
| Requirement sources | `adapters.ticket` (the tracker row: `verified` only when `adapters.ticket.status` is `configured`, the probe of this session, otherwise `unknown`); wiki links in sample tickets and README; `docs/`, ADR and spec folders of `code_repos`. Section `requirements_sources`, one entry per source with source_id, kind (`tracker`, `wiki`, `repository`, `file`, `other`: `references/requirement-source-kinds.json`), locator, status (`verified`, `unavailable` with the reason in evidence_refs when the probe failed, `unknown` when it could not establish), evidence_refs and, when not the tracker's, optional auth_type, secret_ref, username_ref as NAMES only (never a value, never a secret in a locator). The tracker row also gives which system and `method` plus `invoke_or_command_ref` as a route the scout's own Bash, API or browser can follow (SS1-15). Nothing found is an empty section, not a gap to ask about here |
| Application stack | Entry points, how the app runs locally, endpoints/screens, package manifests |
| Mobile surface | A manifest or a test file, in any language, names Appium; a client such as WebdriverIO counts when the test file's capabilities name a mobile platform. Read the file and cite path:line. The names are examples, not a list. Record it in section `mobile_surface` |
| Architecture and data | DB/ORM (migrations, schemas), docker-compose services, external integrations (SDK/API clients, env vars naming URLs), queues/events |
| Test-data lifecycle | Seed scripts and migrations carrying seed data, data factories (`factory_boy`, `faker`, fixture builders), `conftest`/setup fixtures that CREATE records rather than read them, compose services that seed a database, CI steps that reset one, `.env.example` naming test accounts — the defaults topic 3 confirms instead of asking from a blank page |
| Candidate environments | `docker-compose*.yml`, `.env.example`, CI environment matrices, README "how to run against QA/staging" sections |
| How the stand is reached | `python "${CLAUDE_PLUGIN_ROOT}/scripts/project_inventory.py" --root . --access` — the login call sites (a harness CLI login command, an SDK client constructor, `POST .../login`, an OIDC token endpoint, `Authorization: Bearer`, a cookie jar), the key NAMES each reads, and every env file with the names it holds. See the section below |
| Runtime provenance | Read-only version/build endpoints, deployment manifests, image/package/build IDs and metadata linking them to source revisions; absence remains unknown |
| External dependencies | Existing executable and exact version/revision, official upstream source already declared by the project, location, integrity when available, capability/consumer and owner. Catalogue only; do not install, update, log in, or fetch in phase 1 |

Section `risk_ranking` is never left `pending` when this phase ends: phase 2 reads it before topic 4 asks. With no
such document it is `not_read_nothing_found`, and its `notes:` name the paths and patterns searched, after the
positive control above. With several documents, each gets its own `evidence:` line, the one that ranks areas first.

For every relevant repository, resolve the source reference before branch selection and record
the immutable source SHA, remote identity, local path, role, execution profile, write target,
and readiness evidence. Finding a second repository means it receives the same read-only
preflight; one MR never implies one repository.

## Application repo vs test repo — detect separately

Tests and application code are not assumed to share a root. Record an `app_root` and a
`tests_root` candidate separately, each with the evidence that led to it, and classify the
result into exactly one of three outcomes:

| Outcome | Evidence | What phase 2 does with it |
|---|---|---|
| **Single root** | application code and tests in this repository, application directories actually read — not merely named in a manifest | nothing to ask |
| **Split, located** | the application checkout was found on disk: a sibling directory, or a path named in a README, a compose file or CI config that exists | confirm the path and its default branch |
| **Split, not located** | this repository holds tests and no application code, or application repositories are named somewhere but no local checkout exists | **ask** — a required gap, never a skip |

The third outcome is a positive finding, not an absence, and it is the common shape of a
dedicated test repository. Reach it the way this file's positive-control rule demands: "no
application code under this root" is recorded only after the same search that finds
`src`-style code in a repository that has it comes back empty here. Record it in the
open-gaps list as `app_repo: not located`, together with every repository name discovery
did surface (a compose service image, a CI `include`, a README link, an SDK package name)
— phase 2 then asks for their local paths instead of asking from a blank page.

An application repository whose local path nobody can give is a legitimate end state; an
unasked one is not.

**Tests inside the application folders.** Once the application directories are known (every
layout, a Single root included), run `python "${CLAUDE_PLUGIN_ROOT}/scripts/test_locations.py"
--root . --app-root <cand> --protected <cand>... --suggest --json` and record the candidates
with their counts for topic 1c: it names folders and files that carry a usual test name, so
the team confirms or corrects them; it decides nothing, and `truncated: true` means "at least".

## How the stand is reached — two lists, never one

The command above prints a proposed `environment.access` (its `kind`, the harness's own login
command when one exists, and the key NAMES the login reads) plus **two separate key lists**:
the names the env file actually holds, and the names the code reads that the file does not.
They are never merged, and the second list never becomes `secret_keys`: it is the input to
phase 1's own record of `integrations[]` (nobody is asked about it, OH3-8) and lands there,
where a missing key blocks an area instead of the stand.

`--access --json` carries `integration_proposals`: one record per key prefix with at least one
name the env file lacks, holding ALL the names the code reads under that prefix (`keys`; not the ones the proposed login itself uses, and a key that is only read in a login file stays in), which
of them the file holds (`set_in_env_file`), the places the code reads them (`read_at`), and the
folders of the call sites that are tests (`required_by`, absent when no call site is a test).
You write each as an `integrations[]` row and judge two things the script does not:
- **Alternatives.** Split a group into `credential_alternatives` (any ONE complete set is
  enough: a list of lists of names) only on evidence that the sets are other ways into the
  same service: each set is complete on its own, the call sites differ or the choice between
  them is visible in the code. A set the env file already holds whole is such evidence, and
  you decide. When in doubt write NO alternatives: every key is then needed, the direction
  that asks. A name suffix alone is not evidence (`AUTH_SERVER_URL` is not a "server" way).
  `keys` is always the union of the sets.
- **Area.** Copy `required_by` and `read_at` as the proposal gives them (with their `*_more`
  counters when the list was cut). A row with no `required_by` is legal when it carries
  `read_at`: the factory knows where the code reads the keys and nobody settled who needs them.

`--access --json` also carries `account_pairs`: the user/password name pairs the env file holds (`user_key`,
`secret_key`, and `is_login` for the pair the proposed login uses), up to 8, with `account_pairs_more` when
the list was cut and `account_pairs_unreadable` for pairs the gate cannot read back from a role's note (no
underscore, lower case: a case takes such an account as `--as env:USER_KEY/SECRET_KEY`). Record them for
topic 2. The code does not decide whose account a pair is: it matched names only. A pair whose call sites or
prefix show an integration (a tracker, a cloud service) and not a sign-in to the stand is **not a sign-in to
the stand**: you take it out yourself and write it into `integrations[]` without asking; a doubt is shown to
the person with the rest. No pairs found = nothing to ask: that is not a statement that the stand has no
accounts, the gate asks when a case needs one.

`--access --json` also carries `frontend_candidates`: the NAMES the env file holds an http(s) address under (never the value;
at most 5, with `frontend_candidates_more` when cut; none from an `.env.example`; the API's own address is left out). Record them
for topic 2. Which of them is the stand's UI, if any, you judge from the code that reads it and from the name - a name suffix such
as `_URL` is not evidence, and an integration's address (a tracker, a cloud service) is not the UI. The code does not decide it.
It also carries `frontend_same_origin`: the API's own address key (`base_url_key`) and the keys on its origin. You judge from the
project's UI test config (for example a runner `baseURL` that reads that key, or a UI login test) whether the UI tests open the API's own
address, and record that judgment for topic 2. At a first onboarding, before `base_url_key` is known, the base key appears among
`frontend_candidates` itself, and the same judgment applies.

The sign-in of the stand's UI is recorded as a recipe for phase 4 (`manual_capture.login.ui`: the sign-in page's path, the fields and the button of its form as a `test_id` or a `role` with a `name`, and a `landed` rule), read from the project's own page object or UI login test with its path:line, never guessed; gate A proves it for every account a manual case signs in as, through the one sign-in a manual capture uses, and a recipe that does not land is a finding there. Write the recipe as a JSON file and record it with `python "${CLAUDE_PLUGIN_ROOT}/scripts/onboard_apply.py" --root . --set-login-ui <recipe.json>` - the one writer of the config; it refuses a malformed recipe naming the field, and recording the same recipe twice changes nothing.

Reading a project's key *inventory* is how that goes wrong. Another checkout of one harness
had a `cli/constants.py` with about a hundred `KEY_X = "X"` lines; onboarding took four of
them into `secret_keys`, no env file held them, no test of the first story needed them, and
the story stopped there. A constant assignment is not a read — only an actual
`getenv`/`environ`/`get_parameter` call site counts, which is what the command matches.

Record, for phase 2: the proposed kind with the file and line that proposed it, the key names
per slot, the env file chosen, and the code-only key list. When no login call site was found,
or the only evidence is a scheme `access.kind` does not model (a cookie session, mTLS), that
is a finding to **ask** outright — never a kind bent into the nearest neighbour. Values are
never read out of an env file, here or anywhere: names only.

### Judge-assisted narrowing (silent when off)

When code found more than one candidate for a signal below, ask before recording it as an open
gap. An off, unavailable or undecided judge changes nothing — record the candidates as before
and let phase 2 ask. A decided one becomes phase 1's proposal with provenance `judge (N
candidates, confidence C)`, still shown and correctable in phase 2/3 like any other found fact
— never a silent write.

- several run commands for one level: `python "${CLAUDE_PLUGIN_ROOT}/scripts/judge_discovery.py" --ask test_command --level <unit|component|api|e2e> --candidates '[{"command":"...","evidence":"..."}]'`
- several non-example env files: `... --ask env_file --candidates '[{"path":"...","keys":[...],"example":false}]'`
- several login call sites: `... --ask login_site --candidates '[{"where":"file:line","kind":"...","evidence":"..."}]'`
- a code-only key NAME's role (base_url/user/secret/token/unrelated), before it is offered to a slot or dropped into a prefix group: `... --ask key_role --candidates '["KEY_NAME"]'`

## Draft conventions inferred from the repository itself

Independent of anything a README says, read a sample of actual test files and note, each
explicitly marked `inferred`:

- assertion style (built-in `assert` vs a library like Hamcrest/Chai);
- whether API/UI calls go through an SDK or client layer rather than raw calls;
- whether loops appear inside test bodies (an anti-pattern the team may or may not enforce
  against);
- fixture/helper placement (per-file, per-feature `conftest`, or a shared location);
  test/file naming pattern.

These are a draft for phase 2 to confirm, edit, or extend — never written into
`framework-rules.md` as fact before that confirmation. On a thin or inconsistent
repository, propose the list anyway with the explicit note "inferred, not confirmed" next
to it; an empty inferred-conventions list is itself a finding worth surfacing, not a reason
to skip the section.

Separately, human-written instructions found in README/CONTRIBUTING/CLAUDE.md/docs are
**not** inferred — they go straight into `framework-rules.md`'s "Team conventions" section
(phase 4) with a link to their source, no confirmation needed since a human already wrote
them down on purpose.

## Git conventions from history

Sample recent commits and branches (`git log --oneline -30`, `git branch -a`, `git log
--grep` for merge/PR patterns) for: branch-naming pattern, commit-message format, MR/PR
title pattern. This is evidence for phase 2's git-conventions question, offered as the
default rather than asked from a blank page.

## The case store is a finding, not a note in passing

The "Existing cases / TMS" row of the table above resolves into a **candidate path**, kept
beside `app_root` and `tests_root` with the evidence that led to it — the directory, the
case files in it and the id form their names use (`TC-001.md`, `TP1-13797_TC_001.md`: the
ticket part and the number part are what phase 4 writes as `case_id_form`), how they are
grouped (by area, by feature, flat). This is the value
phase 4 writes as `cases_root`, and phase 2 topic 1 confirms; a store that is found and
then goes into nobody's notes is how a project ends up with the factory's case library
beside its own. No store found is equally a finding: it goes into the open gaps, and topic
1 asks rather than the factory choosing a directory of its own.

## Output of this phase

`<notes>/discovery.yaml`, no other file, organized as: **confirmed facts** (framework, run commands,
CI, declared conventions, app/test repo split, case store, git-history pattern) and **open
gaps** (
everything the signal table above did not resolve, which becomes the input list for phase
2). Do not carry inferred conventions into "confirmed facts" — they stay a draft until
phase 2 confirms them.

Name the language of the test files found. The factory reads tests in Python and in every language with an entry in references/detectors.json assertion_probes. Another language is no stop: say "Tests in <language>: they run by the project's command; the automator writes their manifest rows itself, and the can-fail probe takes the throwaway-copy road."

# Evidence capability inventory

For each declared repository, record exact test selectors, reporters, artifact locations and
manual-evidence capture capability. Record unavailable/unknown honestly; discovery is read-only
and does not install tools or run suites.

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
