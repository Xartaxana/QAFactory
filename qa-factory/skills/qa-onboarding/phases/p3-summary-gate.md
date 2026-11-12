# Phase 3 — Summary gate

Show every collected rule and setting with provenance, the full repository inventory, all
pending questions and all open DD rows. Never abbreviate the inventory. For each strategy
group show the original and exact editable path. Save the approval reference used by config
migration and project-decision writes.

Before the summary, make the proposal and seal it with what the install would change. For a
project with a configuration, the proposal is `config_contract.py --root <project> --migration-plan`
(with `--answers` for the keys it lists as needing an answer, kept as `<notes>/answers.json`). For one with
none, it is a JSON file holding the `proposed_config` the role built from phases 1-2 (the fill phase 4, step
1, describes); it is written to `<notes>/proposal.json`, the run's own notes, and nothing else under
`qa-factory/`. The shape of each `profiles[]` row is `references/profile-shape.json`
(`${CLAUDE_PLUGIN_ROOT}/references/profile-shape.json`): `commands` is an object keyed by command name,
never a list. A dispatched helper cannot read the phase files: if one builds `proposal.json`, its dispatch names that
file and the rows' facts. The seal below refuses any other shape and lists each problem: correct the proposal
and seal again. On entering, run `onboarding_notes.py --root . phase --set p3` (the script is
`${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py`). Build the summary from the notes
(`onboarding_notes.py --root . status` names their folder), not from memory. Then:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboard_apply.py" --root <project> --proposal <notes>/proposal.json --out <notes>/sealed.json --listing
```

It writes nothing into the project. It prints the text of part 3b below (show it as it stands) and
saves the proposal together with its removal listing as `<notes>/sealed.json`. The plan also lists the
keys it still waits on: ask them once, in one batch (`p3-keys`, through `onboarding_notes.py --root . ask` and
`answer` as phase 2 does), in the person's words. A question the person
answered at an earlier approval is filled in by the plan and is not asked again.

The keys the plan waits on are asked with the question text the plan gives each, and only those keys.
"Keep everything as before" does not answer them: a key with no earlier value has nothing to keep.
The answer is the whole value at the pointer the plan lists, given in `--answers`. "Not now" is
recorded as the key's current empty value, given in `--answers` like any answer, and is not asked
again. An answer that is not valid is refused before anything is written: correct it, seal again
and ask "yes" again for the corrected summary.

On `yes`, call `config_contract.py --root <project> --record-approval <sealed.json>
--approval-ref <ref> --evidence-ref <host-event-or-transcript-ref>` before generation (the
sealed file, not the bare proposal: the approval covers the listing). It
records the exact migration `input_hash` and `proposal_hash` in
`qa-factory/records/onboarding-approvals.jsonl` (an older project: `state/`, moved by the install).
Free-form approval text is insufficient. Right after it, freeze the notes: `python
"${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py" --root . phase --set p4 --approval-ref <ref> --sealed
<notes>/sealed.json` (refused when the approval is not on record; after it only phase 4's own batches are
accepted).

Canon of a `qa-onboarding` phase. Read on entering the phase. **This is the only gate before
anything is written in the project** (other than the run's own notes; phase 4 may then ask one "Do it?"
per profile whose test command a probe-proven cure would change; that question is its own and this yes
never covers it). Until the human answers `yes` here, phase 4 does not run and no project file
under `qa-factory/` is created, edited, or touched — not a draft, not a partial write, not
a "just the config" head start.

## The summary — one screen, four parts

Present exactly once per round, in this order:

1. **What was found** (phases 1 and 2b) — framework, layers, run-command templates, CI,
   declared conventions with source links, git-history conventions, app repo / test repo
   split, candidate environments, and what the second pass read in the application
   repositories (stack, architecture and data, component inventory). One line each; this is
   a recap, not a re-explanation. Phase 2b's rows keep their state verbatim: **read**, **not
   read: no local checkout**, or **not read: nothing found** — the summary never flattens
   the first two into "none", because a hole in the reading and an empty project look
   identical once flattened and mean opposite things. One more line: each place the team
   named as holding its tests inside the application folders, with its
   `test_locations.py --root . --app-root <cand> --protected <cand>... --check --json` counts (phase
   1's overrides: the config is written only at phase 4; "<N> files, <M> without a usual test name";
   "at least" when `truncated`), or "none found inside the application folders: name them if
   your tests live there". One more line: `found requirement sources: <source_id (kind, status)>, ... - correct?` from
   phase 1's section `requirements_sources`; a question (in the form of `human-questions.md`) only when the probe found none.
2. **What was answered** (phase 2) — the batch answers: the chosen external-writes
   channels, whether the factory may edit the strategy documents, the ticket/TMS adapter
   status, and the DoD sentence; and, when topic 4 was asked, the risk areas as they will be written
   (the area phrases in English with the file they come from, "no area stands out" with the person's words
   quoted when they said everything matters, or "kept as on record"), saying out loud any damage class
   given as an area that is not written as one, and the `**P2 areas.**` line added to a paragraph on record; an
   impact-class map left unanswered with no legacy value is shown here as "kept the canonical map" (it is not a deferred item).
2b. **What was inferred from the repository, for one look** — the conventions phase 1 read
   out of the actual test files (assertion style, SDK/client layer, loops in tests, fixture
   placement, test-file naming, mocking library), each marked `inferred`, as a block the
   human scans and corrects in place rather than a batch of questions. They were questions
   until now, and they should not have been: the repository already answered them, and a
   wrong guess surfaces where it is cheap — at the code critic, against
   `framework-rules.md`. Correct a line here and it is written as confirmed; say nothing
   and it is written as `inferred`, which is an honest label.
3. **What will be written** — the file list phase 4 would produce (`config.json`,
   `strategy/test-strategy.md`, `project-profile.md`, `framework-rules.md`,
   `aspect-profile.md`, `faq.md`, `records/coverage-map.md`, `obligations.md`,
   `factory-backlog.md`, `state/factory-dashboard.html`, `state/readiness.json`), and, if no test
   framework was found in phase 1, the shorter list (`config.json`, `project-profile.md`
   only) with the reason stated. Add one line, in words, for the report probe: after writing,
   one existing test of each execution profile is run once through its own command, to see
   whether it leaves a report the factory can read (what it writes goes to the OS temp folder and
   nothing of the project changes; a change to a command is asked separately and is never covered
   by this yes).
3b. **What the install would delete, set aside and keep** — the text `onboard_apply.py --listing`
   printed, as it stands: what is written, rebuilt, deleted (the factory's own technical data: what
   no current script rebuilds any more, and the old reports of other packages), set aside (moved to
   `qa-factory/state/retired/<day>/`, never deleted: any file inside `qa-factory/` that the factory
   does not recognise, and what the person names) and left alone (a lock file is never removed
   unless it is provably a leftover; the others are named), one line per file with its size, day and
   first line. Every file of every group is listed in full, none is left out or replaced by a count
   (a person who says yes to a deletion sees every file; this listing is the one place the
   one-screen rule below does not shorten), and the record of the removal keeps the whole list too. With no earlier installation record it says the list is only what the factory
   recognises by name and that the person's word is the only authority. In a git project it also
   names every tracked path inside the ignored `qa-factory/state/` and every tracked file the
   install deletes or moves, each with its `git rm --cached` line (after the "yes" the role runs
   those lines, phase 4 step 9; this script only reads git); with no git it says so in one line.
   The team's own dev factory (`docs/superpowers/`) is never in it. To have a file the text keeps
   set aside, the person names it: seal again with `--also-retire <path>` and show the text again.
   A section "Held right now by a running session" is part of the text, not a stop: show it with the
   rest (the listing never refuses; your own session's lock is marked "this session"). Only the
   apply refuses on a lock still held after it waited, and then you show its message (path, holder, the
   move) and stop. If it says there is nothing to do, say so
   and end the run without the question. A text that says a newer factory wrote this project: show
   it, change nothing, and tell the person to update the plugin.
4. **Deferred items** — every topic **that was asked** and left unanswered or answered
   "later", each as it will appear: the question as it was put, a `[DEFERRED: …]` marker
   location, and the `factory-backlog.md` row it will get. Topic 4 kept as on record is not a
   deferred item (it has no marker and no row): it is shown in part 2. An empty list here is stated as
   "nothing deferred", not omitted. A **required** fact (phase 2: repos, environments,
   adapters, external writes) that stayed unanswered is listed with its consequence attached
   — "no local application checkout: `app_repo` unconfigured, grounding by diff unavailable,
   `qa-story` will ask per story" — so approving the summary is an informed decision.

   There is no fifth part for topics nobody asked about. A required topic missing from both
   part 1 and part 2 is not summarized, it is **asked**: go back to phase 2, put the
   question, and rebuild this summary. Listing an unasked topic as "deferred" is the exact
   defect this structure exists to prevent.

Keep the whole thing to roughly one screen: names and one-line summaries, not full file
contents — the full documents exist to be read after they are written, not before approval.

## The single question

End the summary with exactly this question, no other options attached:

> Write these files? yes / edit

The one yes covers everything the summary showed, the removal listing of part 3b included; there is
no second question for it.

## Handling the answer

- **`yes`** → proceed to phase 4 immediately, in the same turn if possible. No further
  questions before writing.
- **`edit`** → ask what to change (one short prompt, not a re-run of the whole interview).
  Apply the correction to the notes from phases 1–2 (the person's words go through `answer` as batch
  `p3-edit-<n>`, a changed finding into `discovery.yaml`), then rebuild and re-present
  the **same four-part summary** exactly once more. This phase allows exactly one such
  round-trip per onboarding run — a second `edit` after the rebuild is still honored (this
  is not a hard cap the user can hit a wall against), but the summary is never silently
  abbreviated on a second pass; it stays the full four parts every time.
- Anything else (a question about a detail, a request to see a full document) → answer it
  without writing anything, then re-ask the exact question above; this is not an implicit
  `edit`.

## Exit

Phase 3 ends only in one of two states: an explicit `yes` recorded in the transcript (the
signal phase 4 checks for before writing anything), or the onboarding run ending without
writing to the project (the human stops responding, or explicitly cancels). A cancel keeps the notes: the
next phase 0 offers them. "Forget it" in the person's words runs `onboarding_notes.py --root . set-aside`.
There is no third path where files get written without this word having been said.
The summary must enumerate each selected profile and capability, every implementation
repository with source ref/SHA and write baseline, canonical quality commands, and each
dependency action with exact upstream source/version/location/owner. Separate already-ready,
unavailable/unsupported, and proposed installation. General catalogue entries do not become
installation actions.

On re-onboarding, show a field-level merge: existing human value, new discovery fact, proposed
value, and any conflict. Unknown adapter extension keys are retained. Only listed changes are
covered by approval.

The gate question approves the listed file edits, the report probe of part 3 (a test run once per
profile; it is a listed action, so the yes covers it and no more) and explicitly listed dependency
preparation. It does not authorize commit, push, application deployment, or an unlisted installation,
and it never authorizes a changed test command. Reuse
authorization already given in the conversation; otherwise leave that action pending.
