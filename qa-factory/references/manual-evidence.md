# Manual evidence v2

Manual evidence is a measured current-attempt record, never a prose claim, and you do not type it:
`manual_capture.py` saves the files, `manual_evidence.py build` assembles the record from them. Before your
dispatch the factory ran `manual_evidence.py prepare`; its answer per case is
`work/evidence/manual/<case>/request.json`. A `refused` request is not yours: leave that case out.

## Capture, then build

- UI: `manual_capture.py ui --task-root <T> --case <C> --steps-file <S>`, one step per line from the closed
  list in `references/manual-capture-steps.json`: `goto <url>`, `click <selector>`, `fill <selector> <text>`,
  `type <selector> <text> [<ms>]` (per character: value and focus logged, then `settled`),
  `press <selector> <key>`, `paste <selector> <text>` (fires `input`, not `paste`: no `onPaste` check),
  `fail_request <glob> <status|timeout>` / `restore_request <glob>` (a page request gets 400-599 with an empty JSON body, or is
  dropped; the glob has no host or a stand's; `capture post_action` is refused while a failure caught nothing, else
  shows `hits_at_capture`; the page's server is not seen; sign-in by code precedes the steps: test a refused login with
  `fill-account`),
  `drag <selector> dx dy`, `wait <ms>|<selector>`, `read <selector> [attr=<n>|style=<p>|state=<s>|text]` (`attr=`: `<absent>` is no such attribute),
  `capture <pre_action|post_action|supporting> [label]`, `fill-account <selector> <actor> user|secret` (quote a
  selector or text that holds a space). One browser session; the first `goto` names the stand.
- You see the screen: the stdout summary's `steps[]` rows are `{step, outcome, screenshot, text}` for the first 40
  steps (later ones: `outcome` only, and a limitation says so). `text` is an excerpt of the page after the step
  (<= 160 characters; a failed step <= 600, its screenshot also a `supporting` capture); the screen of a
  passed step is saved in `<attempt>/observe/NNN-<word>.png`, NOT in `captures.jsonl` and never in the record.
  Excerpts are cut at 8000 characters (the oldest passed ones emptied, `observation_trimmed` counts them); a
  secret-looking text is replaced by a note, an account's value by `[redacted]`.
- `fill-account` signs an account in through the form: the actor is a form of `--as` (`default`, a role,
  `env:USER_KEY/SECRET_KEY`, `created:<name>`), the value is read by code and the steps file holds only names. From the
  first `fill-account` until the URL leaves the sign-in addresses (`login.ui.landed.url_not`) no screen is saved, a
  failed step has no screenshot, and a `capture` is refused; an unknown actor is refused before the browser opens.
- API/CLI: `manual_capture.py http --task-root <T> --case <C> --method M --url U [--body-file F] [--header
  "K: V"] [--state-url U2] [--phase P] [--proves W]`; the call is `request_response`, `--state-url` `state`.
- Who signs in (`--as`, on `ui` and `http`): with no `--as`, a case naming no account signs in as the default, one
  naming a stand role with two keys as it, any other account is refused with its doors; `--as default` is the default account (seeding under the admin),
  `--as "<role>"` a role of the stand's `credentials_by_role`, `--as env:USER_KEY/SECRET_KEY` two key names in the
  project's env file (a person's account; never kept), `--as created:<name>` a
  user this story made. To create a user, `http --as default --method POST --url
  <the stand's create-user endpoint> --body-file F` with `{generated_username}` and `{generated_password}` in the
  body (never in the url or a header): the template check runs on the file as written, the values are put in only
  into the bytes sent, the saved request keeps the placeholders, the answer is saved without them, the password
  stays on this machine, the summary's `created_account` is the name for `--as created:<name>`. Give it the least
  rights the precondition's `what` needs, never a global admin unless it says so.
- `pre_action` is the state before the action under test, `post_action` after it, `supporting` anything
  else; `before`/`after` are the old words, still read, never written. The label of a capture is what it
  proves: `capture post_action completion` (or `--proves completion`) is the ONE line that proves
  completion; code never writes it for you.
- Code logs in (the stand's `.env`, never printed) and proves it landed (`login.ui.landed`); a login that does not
  land exits 3 with `do_not_retry` and an owner. Owner `user` (the account was refused after the submit): make no
  further capture in this block, put the case in env_blocked[] with the printed `login by code: ...`
  line, halt the block; a steps file with `fill-account` after it is refused (exit 2). Owner `factory` (the recipe did
  not fit the page): you may sign in ONCE through `fill-account` steps in a new attempt; if that fails too, the same
  halt. Cause `login_unknown` (not tried, nothing sent: the factory's gap): sign in through
  `fill-account` and do the seed through the screens, in a new attempt; the block goes on. Never
  `build` a blocked attempt. Code probes the stand's build at the start and the end, hashes
  every file and refuses a host that is not a configured stand. Authorization, Cookie and Set-Cookie are saved
  as `[redacted]`; a text matching `secret_content_patterns` is not saved. A step may take the stand's measured
  page load + 30 s (else 180 s); a body is stored up to 2 MB, cut beyond with a limitation. A failed step stops
  the case.
- On a container with no sources (a built bundle) the probe cannot compare files; it reads the image's label
  or a file the person named, and when it can read nothing it answers `unknown`. A capture never proceeds on an
  `unknown`, image or none: it exits 3, `env_blocked`, and `do_not_retry` when the person must answer (the stand
  runs another build, or it is not known): do not capture again. The person
  answers the build question at the stage entry; the decision is in `qa-factory/records/stand-identity.json`. A build confirmed by the person (`person_confirmed`, given for THIS
  story) is taken and stored as the probe said it, never as `matched`; the record's `limitations[]` then carry
  code's sentence (who confirmed it, when, "not read by the factory", and for `test deployed` the build that was
  under test; the person's `test as is` for a content mismatch has its own sentence naming the differing files). A word
  given for another story, or one whose build moved, is refused. Automation reads the same word.
- One attempt, one test profile: a cleanup `http` call after a `ui` session of ANOTHER profile opens
  the next attempt (one profile: the open one): `build --attempt <the proving one>`. `--profile <id>`: several fit.
- Seed: `http` calls in `work/evidence/manual/<case>/seed-steps.md` beside `request.json` (`area/TC` is `area__TC`);
  retry runs it. Secrets: `{generated_*}`, `--as`. Not `http`: words, why.
- Files per attempt (`a1`, `a2` ...) under `work/evidence/manual/<case>/<attempt>/`: the evidence files,
  `captures.jsonl` (`path`, `content_hash`, `kind`, `phase`, `captured_at`, `proves`, `command`, `limitation?`),
  `steps.jsonl`, `probes.jsonl`, and `env_blocked.json` when the probe was unmatched or the login by code did not
  land (no record: the case goes to `env_blocked[]`).
- `manual_evidence.py build --task-root <T> --case <C> --result pass|fail|inconclusive --actual "<what you saw
  now>" --masked [--limitation "<words>"] --then-quote "<n>=<words>"...`; your `--result` is never changed. An
  attempt already written is never rebuilt: capture again, then `build --attempt a<n+1>`.
- Your verdict stands on the text you captured. `request.json` lists the case's `thens` (`{"1": "<text>", ...}`).
  A `pass` carries `--then-quote "<n>=<words>"` for EVERY Then, a `fail` for at least the Then it failed on (a Then
  you never reached: `--then-unreached <n>`), an `inconclusive` for none. The words are copied from a text capture of
  THIS attempt (`.txt .log .json .xml .csv`; whitespace is folded, case counts), at most 300 characters, the shortest
  part that decides; a Then only the picture shows: `--then-seen "<n>=<what it shows>"`. Code checks that the words
  are there, never what they mean. A request with no `thens` (or `{}`) asks for none.
  Recorded as `then_quotes[]` (`{then, quote, source, kind: text|seen}` or `{then, reached: false}`).
- One record, two stand profiles (a ui check and an api read): capture each as its own attempt, then
  `build --attempt a<main> --with-attempt a<other>` (repeat per profile). Each joined attempt must be open, of
  another profile, on the same expected source revision; the record carries them as `other_profiles[]` with their
  own probes and steps, the joined attempt is marked `{"part_of": "a<main>"}`.
- A verdict you now see was wrong, on files already captured: `manual_evidence.py rejudge --task-root <T> --case <C>
  --of-attempt a<n> --result pass|fail|inconclusive --actual "<words>" --then-quote ... --reason "<why the first
  verdict was wrong>" [--completion <path of the post_action capture that proves it>] [--limitation "<words>"]`. The check is not run
  again: the new record `a<n>-r<k>` copies the evidence, probes and steps of `a<n>` as they were, changes only
  result, actual and quotes, starts now, and says so in `limitations[]`; `record.json` is untouched and it passes every rule a
  built one does (a changed file, a stale revision, a `pass` with no completion proof: refused). It needs an open S6
  dispatch. An `inconclusive` re-judge needs your own `--limitation "<what stopped the check>"`. An attempt older than
  another with its own record cannot be re-judged: re-judge the newer, or capture again.

## The record

`schema_version: 2`, pinned `case`/`case_version`, `obligation_ids` with exact `obligation_hashes`,
`attempt_id`, current S6 `dispatch_id`, `source_revision`, `runtime_identity` (the build the probe saw),
`runtime_before`/`runtime_after`, timestamps, `steps_actual[]`, `expected`, `actual`, `completion_condition`,
`result`, `evidence_policy`, `limitations[]`, `evidence_refs[]` and `before_change`; and, when they apply,
`then_quotes[]`, `other_profiles[]`, and `rejudge_of`/`rejudge_reason` (a re-judged record).

`before_change: {r, value, ref, source}` is the ONE "before" a person sees: `claim` copies the register's
`## Behaviour claims` row of a requirement the case covers, `not_recorded` means the requirements say nothing
and never reads as "unchanged". Code writes it.

Each evidence ref has `kind: image|log|request_response|state|trace|other`, `phase`
(`pre_action|post_action|supporting`), a task-relative path under `work/evidence` or `evidence`,
`content_hash`, `captured_at`, nonempty `proves[]` and `mask_acknowledged: true` (your `--masked`). UI needs
visual or trace evidence in `pre_action` and `post_action`; for API/CLI the refusal reads
"api/cli requires request/output and post_action state evidence": the call that proves the check carries
`--state-url` (a `state` capture in `post_action`);
`no_write` state in both and the completion proof; static an explicit `before_not_applicable_reason` and
`post_action` evidence: static reason equals the planned text.
A pass needs `completion` in a post_action `proves`.
`inconclusive` is recordable under every policy with at least one ref and a limitation, never as coverage.

`manual_evidence.py validate --task-root <T> --input <record.json>` checks a record; `write-block` takes only
records bound by `coverage_contract.validate_manual_current` (hashes, pins, source, S6 dispatch, a stable runtime
(`matched`, or the person's word for this story), or `not_applicable` for verified local source or `reason_code: no_changed_file`). Export takes a finalized list and
writes masked copies under `evidence/` named by content hash (active HTML/JavaScript/SVG and unknown suffixes
become inert `.bin`). The copies stay on this machine, never in a commit.
