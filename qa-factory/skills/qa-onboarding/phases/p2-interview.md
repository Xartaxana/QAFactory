# Phase 2 — Interview (gaps only, batches of at most 4)

Record each question before moving on. An explicit unknown, defer/decline, continuation
without an answer, or interrupted saved interview stays pending and becomes one DD matched
by `field_refs`: a JSON pointer, or a document ref `doc:<path>[#<anchor>]` (`--field-values` is
omitted when every ref is a document ref). Do not file a DD for a question never asked. Use typed
triggers (`manual`, `capability_verified`, `story_count`, `date`); manual never becomes
overdue by age.

Existing numeric `impact_scale` values have no safe translation. Preserve each one, expose
a migration conflict and ask for its `{priority,severity}`. Do not ask about `turns.soft`
or `turns.repeat`; their defaults are 60 and 30. Requirements sources record source id,
kind, locator, method/invocation reference, status and evidence, never credentials.

Canon of a `qa-onboarding` phase. Read on entering the phase. Ask **only** what phase 1's
discovery left open. A topic discovery already answered with confidence is not asked "just
to confirm" — it is shown in the phase 3 summary as a found fact instead. On a
re-onboarding run (phase 0), every question below offers the existing `config.json`/
strategy value as its default, so answering is a confirmation, not a re-interrogation.

On entering, run `onboarding_notes.py --root . phase --set p2` (the script is
`${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py`, run as the other scripts of this skill are), then
`onboarding_notes.py --root . status`: its `answered`, `not_answered` and `awaiting_reply` say what an
earlier window already settled. A section it reports `pending` because of a `problem` is an open gap, never treated as found.

## Batching rule

Group the open topics below into messages of **at most four questions each**, in the order
listed (skip an entire topic when discovery already closed it). Do not send one question
per message (that is not economical) and do not send every open topic in one wall (a wall
gets one answer and the rest defaults by omission). A natural batch: topic 1 with 1b (both
"how is this project laid out"); **topic 2 on its own** — its stand questions plus the
access question already fill a batch, and pushing repos in front of them is what turns four
questions into a wall; **3 on its own** — its four named test-data questions fill a batch;
4 on its own, or with 9–10 when the four-question cap allows (it is two questions); 5 on
its own (git conventions); 7–8 together (adapters and channels); 9–10 together (DoD and
passport) — adjust the grouping to how many topics discovery actually left open.

## Required facts are asked, not skipped

A topic is skipped only when discovery **found** the fact — never because discovery came
back with nothing and left no guess to confirm.

Which topics are required is not a matter of taste: **a fact is required when code later
complains about its absence.** That is `readiness.py`'s capability list (test root,
application paths, the environment block, the ticket/TMS adapters, the external-writes
channels) and `references/inject-map.json`'s project inputs — what a strategy document must
contain for a role to be dispatched with something to read. Hence:

| Topic | Mark | Rule |
|---|---|---|
| 1 repos · 2 environments · 3 test data · 7 adapters · 8 external writes | **required** | discovery found it, or it is asked. There is no third branch. |
| 4 · 5 · 9 · 10 | optional | asked while open; a run that never asks records nothing at all for it |
| 6 | **not asked** | inferred from the repository, shown for correction at the summary gate |

Test data is required by the same criterion, not by taste: `common-rules.md`'s "your own test
data" rule **changes meaning** depending on the answer — depending on an existing record is a
defect *unless* the project declared shared records — so a role with no answer decides for
itself what the rule means.

When discovery could not resolve a required fact, the question is asked from a blank page
with the reason stated out loud ("this repository holds the tests; I could not find the
application code under it"). The two that the pilot lost silently:

- **where the application code lives locally** — a path per application repository (topic 1);
- **how each stand is reached** — its address and how access is obtained (topic 2).

A required fact that was asked and left unanswered becomes a `[DEFERRED: …]` marker plus a
`factory-backlog.md` row, named out loud in the phase-3 summary. It is never a placeholder:
not an invented URL, not a `.` standing in for a path nobody gave, not a "probably the
sibling directory" guess written as if it were an answer.

**A deferral requires a question.** `[DEFERRED: …]` records "we asked, the answer did not
come" — never "we did not ask". A topic that was never put to the team produces no marker
and no `DD-n` row: if it was required, not asking is a defect of this phase to fix here and
now, and if it was optional, silence about something the factory does not need is not a
debt worth a row. Every `DD-n` row therefore carries the question **verbatim** and the batch
it was asked in, in `factory-backlog.md`'s `asked` column — audit A13 rejects a row without
one, which is what makes this rule a check rather than a hope.

## The ordered question bank

1. **Test repo vs application repo(s).** Driven by phase 1's three-outcome table.
   *Single root* → skip entirely. *Split, located* → confirm each path and default branch,
   **and ask once whether there are others**: "we found `<path>`; are there other
   repositories for this product — a UI, services — and where are they checked out?", with
   the names discovery surfaced. Finding one application repository is not evidence that
   there is one: QA-EXAMPLE's change was a backend MR and a frontend MR, and because
   nobody was asked, the UI repository had to be found by guesswork mid-story.
   *Split, not located* → ask, naming what was searched and what was found: "this
   repository holds the tests; where are the application repositories checked out
   locally?" Collect per application repository: a short **name**, its **local path**, and
   its **default branch** — and list the repository names discovery surfaced (UI, backend,
   services) so the team fills in paths rather than recalling an inventory. Ask for paths
   **relative to this repository's root** (`../testproject1`, `../../testproject1-ui`) so the
   generated config stays portable across machines. A team member will answer with what
   their terminal shows — `/Users/anna/Projects/testproject1`, `C:\work\testproject1` — and that is
   fine as an *answer*: convert it to the relative form before it reaches the config, and
   show the converted value back in the summary so the correction is visible. An absolute
   path is never written down (audit A20); one that cannot be expressed relatively becomes
   a deferral. "There is no local checkout" is a legitimate answer — record
   it and move on: the `app_repo` capability stays unconfigured, grounding by diff is
   unavailable, and `qa-story` asks per story (`s1.md`'s grounding question) instead.
   For each needed repository also confirm its source ref/SHA and profile. Resolve these
   before asking for or choosing a writable branch/base. Missing required repositories block
   only their dependent contours; independent profiles remain available.
1b. **Where the test cases live.** Same batch as topic 1 — both are "how is this project
   laid out", and phase 1 already looked: a `test-cases/` directory, files named by a case id, a
   TMS link in the docs. *Found* → confirm it and its grouping: "we found `<path>`, cases
   grouped by `<area>` — do new cases go there too?" *Not found* → ask once: "where should
   written test cases live — a directory in this repository, or does the team keep them in
   a TMS?" A team that keeps no case library is a real answer, recorded as such: cases then
   stay with the factory, per story, and `cases_root` is left empty. What is never done is
   choosing a directory ourselves — on green-lantern the store was found and then ignored,
   and every new case went into the factory's own tree beside the project's real library.
   The answer becomes `config.cases_root`, relative to this repository's root (audit A20),
   and it may not point inside `protected_app_paths`: the factory does not write into
   application code, and a config key cannot grant what P-00 refuses.
1c. **Tests inside the application code.** Asked whenever phase 1's `--suggest` found
   candidates - including on a Single root, where topic 1 itself is skipped; it goes into
   topic 1's batch when there is one, otherwise it is its own short batch. Show each
   candidate with its counts from `test_locations.py --root . --app-root <cand> --protected
   <cand>... --check --candidate "<p>" --json` (phase 1's own `--app-root`/`--protected`: no config
   exists yet, and an unreadable count says so in `unreadable`, it is not "0 files"): "<N> files, <M>
   without a usual test name" ("at least" when `truncated`), and ask
   whether there are other places inside the application folders where tests live under
   other names. The project's answer is its own word: any name the team uses is accepted.
   The answer becomes `config.test_locations` (entries relative to `app_root`, written like
   `protected_app_paths`; audit A20). An entry that covers a whole application folder is asked
   once more, naming what it would unprotect. With no candidates, 1c is not asked.
2. **Environments and credentials** — the `environment` block per `references/environments.md`:
   which stands exist (`local`, `QA`, `staging`, …), how each is brought up, credentials by
   role, what may safely be broken on each, and which preparation actions are authorized.
   Discover runtime probes, mounts, startup commands and build inputs from project code.
   Use the environment preparation adapter contract; missing facts require observation,
   never an unconditional rebuild. Confirm authority to change the selected stand.
   When discovery found no address for a stand, **ask for it outright** — a stand with no
   reachable address is not an environment entry, and `environments.md` forbids "a
   placeholder URL substituted because nobody answered".
   **Which env file carries the address, the account and the secrets is no longer a
   question**: phase 1 read the files and the login call sites, so those names are *shown*
   in the summary for correction like any other found fact. What is asked instead — by name,
   never by value, one question so the batch does not grow:

   **Which access scheme is the one.** Offer phase 1's proposal and the alternatives it
      saw, and the harness's own login command **first** when one exists (if the project can
      log itself in, the factory calls it rather than reimplementing the protocol): `access.kind`
      = `harness_command` · `local_login` · `oidc_password` · `bearer_env` · `none`, with the
      key names each needs (`user_key`, `secret_key`, `client_id_key`, `realm_key`,
      `token_key`) and the command or URL; for `local_login` the proposal also shows the JSON body
      field names (`user_field`, `secret_field`); empty = the probe tries the pairs of
      references/login-body-fields.json and onboarding records the one the endpoint accepted —
      confirm what phase 1 found; nothing else is asked about them. Add, in the same question: **what does an
      unauthenticated request to this stand answer, and which of those codes is the norm?**
      (`access.unauth_status` — a redirect to an identity provider, a 401, a 200 without a
      token). A stand behind an identity provider answering 302 is healthy; the factory only
      knows that because somebody said so here. When phase 1 found no login site, or a scheme
      the five kinds do not model, ask outright which of them applies — an access scheme this
      version cannot record is a `[DEFERRED: …]` and its backlog row, not a guessed kind.
      Ask one more thing when phase 1 printed `account_pairs` — **the accounts of the stand**, one
      question that shows the pairs by NAME: for each pair, **which role is this account on the stand**
      (an administrator, a plain user, ...), or "not an account of the stand". The login pair is offered as
      the main user's role, but the word "administrator" is never taken from its name: the person says it.
      A role the person does not name is not written; a guess is not a fact. Roles already recorded in
      `environments[].credentials_by_role` are shown, not asked again (a re-onboarding counts them in the
      whole of topic 2 below). No pairs = no question. Never ask for a value, only for names.
      Ask one more thing when phase 1 printed `frontend_candidates` — **which variable holds the stand's
      UI address**, one question that shows the candidate NAMES (never a value). You propose the key you judge to be the UI
      (one fitting name = the default answer); the person confirms it, picks another, or says "none of these is the UI".
      Then, for the confirmed key, the question below. When the project's UI tests open the address under `base_url_key`
      (phase 1 recorded that judgment from `frontend_same_origin`), the UI is on the API's own address: propose <base_url_key>
      by NAME as the default answer of this same one question, even though discovery leaves it out of `frontend_candidates`.
      The question is asked only when there are candidates OR the UI tests open the base key. No UI tests and no candidates =
      no question: the stand is API-only. (The question is put in the person's words, by names, as `human-questions.md` asks:
      the stand's UI address and what it means for the cases, never a field path.)
      Ask one more thing only when the stand has a frontend but no path through it to
      the API: **which path of the frontend answers with the API's own JSON** (`environment.frontend.api_path`,
      for example `/api/v1/config`)? No frontend found = no question: the stand is API-only.
   The keys the code reads that the env file does not hold are **not a question** (OH3-8): the
   person is not asked about them here or anywhere in onboarding. Phase 1 records them as
   `integrations[]` from the facts it printed, and they never become `secret_keys`. The keys the
   proposed login itself uses are facts of the access proposal above, shown for correction like the
   rest, not a separate question; a key that is only read in a file with a login call and is not
   one of them goes to `integrations[]` with the others.

   Values are never asked for and never stored in `config.json`.
   **Re-onboarding a project whose `environment` block has no `access`, or one with an empty
   `kind` and no recorded answer** (every config written before this version, and one reinstalled
   once without answering): this question is the *whole* of topic 2 together with the pairs question
   above (for `account_pairs` not yet recorded as roles) — stands,
   bring-up, credentials by role, `safe_to_break` and the authorized preparation actions are
   already on record and are shown, not re-asked. Phase 1's key lists are re-derived either
   way, because a project's env file changes without anybody re-onboarding.
   For each selected execution profile, ask how runtime identity is read and linked to source.
   An owner statement may be retained as evidence but never upgraded to a technical match.
   **A mobile application stand (only when phase 1 recorded a `mobile_surface` section).** One closed batch, each
   answer offered from what phase 1 read (path:line), never from a guess: the platforms the tests drive (a row name of
   `references/surfaces.json`, as the `surface` of the stand), the Appium server address (`driver.url`, http or https, never
   with a user or a password in it), the application id (`app.id`), and the NAME of the variable that holds the device
   serial (`device.serial_key`; a name, never a serial), and one element only the application's sign-in screen has
   (`<strategy>=<value>`, a strategy of that platform's `selectors`; it becomes `manual_capture.login.app.sign_in_selector`,
   and without it the sign-in window of a device capture never closes). Each is one `environments[]` row (`name`, `surface`, `driver`,
   `device`, `app`) beside the API stand's own row; a project with both keeps both rows, and a second platform is a second
   row. "I do not know" on a field leaves it empty and says so in the summary: the doctor then names the stand as not
   described instead of reading it as ready. The device itself is never asked about here (no emulator is needed to
   finish onboarding); the doctor checks it.

2b. **Profile and dependency gaps.** Ask only for contours needed by known project work. For
each, close gaps in selectors, reporter, canonical scoped commands and execution prerequisites
(runtime, package manager, dependency state, hook executables). If a selected capability needs
an absent external tool, ask whether to prepare that exact pinned dependency, who is responsible for it, and
where it may be installed. Do not ask about or prepare browser tooling for API-only/native-only
profiles. Unsupported selector or adapter stays unsupported; offer manual/preparatory work.
3. **Test-data lifecycle** — its own batch, because this is four questions and one open
   "tell me about your test data" comes back with one of them. Ask by name, offering what
   phase 1 found as the default:
   1. **Accounts and datasets** — where do role accounts come from, and how is a fresh
      dataset created: fixtures, data factories, a seed script, a shared seeded stand?
   2. **Real data and PII** — is any of it real, and what is the masking rule?
   3. **Cleanup and reset** — who resets or cleans up, and when?
   4. **Shared records** — is there an entity type a test may depend on instead of creating
      it? This is the **only** exception to `common-rules.md`'s "your own test data"; no
      answer means no exception, not a blanket permission.

   Each answer lands in its own `config.json` `test_data` key. `unknown` is a legitimate
   answer and is **written as `unknown`** — what is not legitimate is a key nobody was asked
   about. What may safely be *broken* on a particular stand belongs to topic 2
   (`environments[].safe_to_break`) and is not asked again here.
4. **Risk areas and the impact-class map.** Two questions, risk areas first. Record them as two topics, `4` (the
   risk areas) and `4-map` (the impact-class map), so that a deferred risk question never marks the map as unanswered.
   1. **The project's main risk areas.** Offer what discovery read as the default, when it read anything: a project
      document that ranks areas (`discovery.yaml` section `risk_ranking`, named by its path; a linked one is named as a
      link the factory did not open), the `**P1 areas.**` paragraph already on record (re-onboarding),
      the area names a legacy numeric `impact_scale` weighed (said as "your earlier configuration weighed: ...";
      nothing is translated, and the migration conflict below stays as it is). Never offer folder sizes as if they
      were the team's answer. The alternative "Nothing in the repository says which parts of the product matter most."
      is said only when that section is `not_read_nothing_found`; while the section is still `pending`, the question is
      put with no found-sentence at all. The same holds when the section is `not_read_no_checkout` or `inferred`:
      nothing was read that ranks areas, so the question is put with no found-sentence and without the alternative
      above, which claims a search that found nothing. Put it as:
      "<What the factory found, or: Nothing in the repository says which parts of the product matter most.>
      Which parts of the product - features, screens, services - would hurt most if they broke? The factory counts a
      requirement in one of these parts as more work when it estimates a story, and the test plan leans towards
      automating it; each name also becomes a question the requirements check asks of every requirement.
      (a) Name the areas, most important first.
          the factory: a record only. you: this answer. the story: requirements in these areas are sized higher
          and lean towards automation; delivery unchanged.
      (b) No area stands out.
          the factory: a record only. you: nothing more. the story: every requirement is sized by its own
          impact; delivery unchanged.
      (c) Later.
          the factory: a record only; the question stays open in the factory's backlog. you: nothing more now.
          the story: sized by impact only until you answer; delivery unchanged.
      How to answer: write the areas in your own words, most important first (for example: checkout, user
      accounts, the nightly import) - a few, not every part of the product - or reply (b) or (c). None is a
      legitimate answer."
      (a) is written by phase 4 steps 2 and 5. (b) is an answer and is written as one; it is not a deferral. A
      whole-product answer ("everything is critical") is taken as (b): nothing is riskier than the rest; the sentence
      phase 4 writes quotes their words, and the summary says so. A damage class given as an area is not an area (phase
      4 step 2): the summary says the impact-class map already weighs it. (c), silence, or "I don't know" is a
      deferred decision: the marker `[DEFERRED: risk areas not named]` and its backlog row, whose `asked` column
      carries this question as it was put (one marker text and one row for `test-strategy.md` and `aspect-profile.md`;
      phase 4 steps 2, 5 and 8), and the topic goes in `--not-answered`. With a `**P1 areas.**` paragraph already on
      record, (c) reads "Keep what is on record." and ALL THREE of its lines change to "the factory: nothing runs.
      you: nothing more. the story: sized by the areas on record; delivery unchanged." (the backlog promise of the
      first-onboarding (c) is not shown, because nothing is filed): (c) or silence then keeps the paragraph as it is,
      with no marker and no backlog row, because a person's earlier answer is never erased by a later deferral, and
      the topic goes in `--answered`, never `--not-answered`: the record stands as the default, and answering is a
      confirmation. The words file keeps the person's own language; the phrases phase 4 writes are English.
   2. **The impact-class map.** Ask only whether the project's impact-class mapping differs from the canonical
      priority/severity map. Keep the canonical map when no project rule was discovered. A legacy numeric value is
      invalid, remains preserved in the migration conflict, and gets a targeted question; never guess a translation.
      Unanswered with no legacy value: the canonical map stands; record `4-map` in `--not-answered`; no marker and no
      backlog row (the canonical map is a complete answer, not a hole). Unanswered with a preserved legacy numeric
      value: the targeted question was asked, so the marker `[DEFERRED: impact scale not set]` and its backlog row
      stand (phase 4 steps 2 and 8), and `4-map` goes in `--not-answered`; a legacy value never asked about gets
      neither (a deferral requires a question).
5. **Git conventions and pre-commit commands.** Confirm (or correct) the branch/commit/MR
   pattern discovery inferred from history; ask for `pre_commit_commands` (linter,
   formatter — e.g. `ruff check`) and confirm any the repo's own docs already named.
   Record `format_changed` and `format_all` as two separate keys: `format_changed` formats
   ONLY the files a story touched (the project's formatter over `git diff --name-only
   <base>...HEAD`) and is the only formatting a role may run; `format_all` is the wide
   command and is a separate cleanup. When the project offers only a wide command, DERIVE
   the narrow one here rather than leaving the choice to a role — on TP2-2520 the
   configured command was `prettier --write src`, the story changed one test file, and
   running it would have rewritten drift in 39 files belonging to other people. Also ask
   `records_policy` (`with_story` · `separate` · `local_only`): where the factory's shared
   records — `obligations.md`, `factory-backlog.md`, `strategy/*`, which accumulate across
   stories — are committed. `artifacts/<TICKET>/` always travels with its own story. This
   topic owns naming *conventions* only. **How the factory talks to the VCS** — `glab`, `gh`,
   a connector — belongs to topic 7 and is not asked here; asking it in both places is how
   the same question got put to a team twice. Also ask, in plain words, **which command brings
   the project's environment to its lock** ("when the libraries the tests need are out of date,
   what do you type to update them?" - `poetry install`, `uv sync`, `make deps`): it is
   `commands.install` of the selected profile (kind `setup`, phase 4 writes it). The doctor
   and gate A print this command beside the pair of versions when the installed libraries
   differ from the lock; the factory never runs it. No answer: the line stays out of the
   profile, and the package manager's usual command is shown instead when one is known.
   Also ask once, in plain words, **whether the project's build or test runner compiles the whole test
   folder every time** ("when two people edit different test files at the same moment, can a
   half-written file in one break the other's test run - for example a TypeScript or Java build that
   compiles every test file together?"). The answer is `dispatch.parallel_windows`; its note reads
   "windows run in parallel; serial if the build compiles the whole test folder" - on a yes record `1`. "No" or "not sure" keeps the default of 3, and a
   person who does not answer stays at 3 with nothing recorded. The factory never runs this
   question's answer as a command; it only sets how many automation windows work at once.
   Also ask once, in plain words, **how many manual walkers may work at once** ("how many manual walk-throughs of the app may run side by side; 1 = one at a time"). The answer is `manual.walkers`; 1 = one walker at a time, a person who does not answer stays at 3 with nothing recorded.
6. **Nothing.** The inferred code conventions from phase 1 — assertion style, SDK/client
   layer, loops in tests, fixture placement, naming, mocking library — are **not asked**.
   The repository already answered them; they are shown in the summary gate (phase 3, part
   2b) as one block marked `inferred`, for a correction in place. Asking a team to confirm
   six things their own test files already say is how an interview grows without adding a
   fact. A convention written `inferred` and wrong surfaces where it is cheap: at the code
   critic, against `framework-rules.md`.
7. **Adapters — tickets, test management, and version control.** All three in one topic,
   because they are one question asked three times and splitting them is what produced a
   duplicate. For **version control**: which host (`gitlab`, `github`, …) and how it is
   reached (`glab`, `gh`, a connector, or a skill/agent) → `adapters.vcs = {name, status,
   method}`. For tickets and test management, two answers each, not one: **which** system
   holds tickets (and, separately, test cases/results), and **how this session reaches it**.
   For **reading tickets** there is one route and it is asked as one: a direct API — a CLI
   command or an MCP tool that returns the ticket itself (`method: command` / `mcp`, plus
   its key or token). **Do not offer an assistant here.** An assistant answers "the
   orchestrator already got the ticket once" to every follow-up key, so the scout cannot
   fetch the parent, the linked tickets or an attachment, and the story is built on one
   paraphrase. A team whose only reading route is an assistant is `status: not configured`
   with the reason ("configure a direct API for reading") — their assistant is still
   first-class where it works, as a **write** channel in topic 8. Offer phase 1's candidates
   as defaults. Record the name in `adapters.ticket.name`, the access in `method` + the key
   or command it needs (`references/adapters-read.md`). When the tracker or the VCS host is not
   one `references/adapter-forms.json` knows, ask for the shape of one ticket key
   (`adapters.ticket.key_pattern`) and for the command that opens a merge or pull request
   (`adapters.vcs.delivery_commands`).

   **Then verify the answer before believing it.** `status: configured` means *this session
   reached it*, not *the team named it*. For a **CLI** (`method: command`), run the check in
   the session — `which <tool>` / `<tool> --version`, and where it is cheap, the real
   command against a known ticket. The pilot's defect was exactly this step missing:
   onboarding wrote `command: dmtools jira get {key}` with `status: configured` for a
   `dmtools` that was not installed, readiness echoed the claim back as `ok`, and the first
   story died in S0. A CLI that does not answer is `status: not configured` **plus the
   question re-asked**: "that one is not on PATH here — is there another way this session
   reaches the tracker?" — another CLI, or the API token an MCP tool needs. For an **MCP
   tool**, the probe is the call itself: fetch one real ticket during
   onboarding if the team can name one, and record what came back. Unverifiable at
   onboarding time is `not configured` + a deferral, never `configured` on trust.
8. **External-writes channels** — ask explicitly, do not infer: where should found bugs go
   (`markdown` in the repo, the default, or `jira`), and where should cases and results go
   (`markdown`, the default, or `xray`/`testrail`/`zephyr`)? State the default out loud
   before asking, since many teams are content with files they can diff like code: "the
   default is `markdown` for both — files in this repo, nothing configured. Say so if you
   want bugs or cases synced to a tracker instead." A team that does not answer stays on
   `markdown` — that is a legitimate, first-class outcome, not a degraded one.
   A tracker channel closes only on a confirmed **write** right (TP2-2534 ran green
   and filed nothing: the assistant could only read). Offer exactly three: an assistant that
   can write (`channels.<name>.writes: true`, confirmed by one question to it), a direct API
   token (`channels.<name>.method: "api"` + `external_writes.bugs_project`), or a deliberate
   `bugs: markdown`. Run `tracker_write.py --force --where onboarding` before phase 4 and
   write its answer into the receipt.
   A non-`markdown` channel needs a second answer: **how is that channel written** — a CLI
   command, or a skill/agent? This is where an assistant belongs, and it is the only place
   it does: reading a tracker and writing to it are not the same route (topic 7 reads
   through a direct API only). A channel with no delivery configured refuses at gate B with
   the two ways out; a channel named here and nowhere else is the quiet kind of broken.

   **Strategy permissions in the same batch:** for each discovered pre-existing strategy
   group ask "update this exact existing file, or create a separate factory document?".
   Record the answer once in `strategy_documents[]`; an opt-in grants only that exact file.
   Factory-created documents record creation evidence and are editable. Unknown provenance
   remains propose-only. The legacy boolean is limited to the two historical factory files.
9. **Definition of done.** One sentence: when is a story considered tested, from this
   team's own standard.
10. **Product basics.** Only what phase 1 did not already surface: business goal and
    primary users in one or two sentences, and — if not obvious from the repo — the source
    of truth for requirements (where specs/tickets actually live). Keep it short: these are
    the opening lines of `project-profile.md`, not a product brief, and there is no separate
    passport document to fill.

## What is never asked here

No question about testing cadences, a metrics menu, or any non-functional testing type
(performance, security, accessibility, localization, compatibility, privacy) — v0 has no
mode for any of them, so there is nothing to configure. If the team volunteers a
non-functional concern unprompted, note it once in `project-profile.md` at phase 4 as an
out-of-scope observation, and move on without opening a sub-interview about it.

## Recording answers

Every answer goes into the run's notes as it is given, in `<notes>` (the folder `status` prints as
`path`); phase 3 is still the gate and phase 4 the write of the project's files. Record a batch before
sending it (`onboarding_notes.py --root . ask`), and record the reply, as given, before doing anything
else (`onboarding_notes.py --root . answer --words-file <file>`). In full:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py" --root . ask --batch <id> --questions-file <json>
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py" --root . answer --batch <id> --words-file <file> --answered <topic,...> [--not-answered <topic,...>]
```

`<json>` is a list `[{"topic": "<id>", "text": "<the question as it is put>"}]`. The words file holds the
person's reply exactly as given, written with the file tool to `<notes>/words/batch-<id>-<YYYYMMDD-HHMMSS>.txt`
(never overwritten, never deleted). Batch and topic ids use letters, digits, `_`, `.` and `-` only. A topic
the notes list as `answered` or `not_answered` is never asked again. A batch the notes show as asked with no
reply recorded is asked once more, saying why: the context was compacted before the reply was written down.
Name every topic of the batch in `--answered` or `--not-answered`; one left out stays awaiting and is asked
again (`status` lists it under `awaiting_topics`, `answer` prints `still_open`). A file `status` lists under
`unrecorded_words` is a reply already on disk: record such a file with `answer` instead of asking again. A topic
answered in one batch is refused under a new batch id; a changed answer goes in a `p3-edit-<n>` or `p4-` batch.
An unanswered question that the run proceeds past anyway (the team skips a batch item, or says "later") is recorded as a **deferred
decision** for phase 4: it becomes a `[DEFERRED: …]` marker plus a `factory-backlog.md` row
carrying the question as it was asked, never a silently invented default. The one exception is topic `4-map` with no
legacy numeric value: the canonical map stands as a complete answer (topic 4, question 2), so it is recorded in
`--not-answered` with no marker and no row.

**One topic, one batch.** Every topic above has exactly one owning batch, and a topic
answered in an earlier batch is never reopened in a later one — a resolved question asked
again is a defect, not diligence. If a later batch needs a fact an earlier one settled, use
the answer on record.

Record each topic in exactly one state, because phase 3 prints these and nothing else:
**found by discovery** (with its evidence), **asked and answered**, or **asked and not
answered** (with the question text, which becomes the `asked` column). There is no
"skipped" state for a required topic, and an optional topic nobody asked simply leaves no
trace — not a row, not a marker, not a default written as if it were a decision.

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
