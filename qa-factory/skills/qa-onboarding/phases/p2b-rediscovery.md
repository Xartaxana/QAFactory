# Phase 2b — Second-pass discovery (read-only, after the interview)

Canon of a `qa-onboarding` phase. Read on entering the phase. **No question is asked here**
— the interview is over. This pass exists because phase 1 could only read what was already
reachable: the application repositories, the stand and the systems the team named become
readable only once phase 2 has said where they are. Without it every fact about the
application under test is missing from the generated documents, and the hole reads as a
finding about the project instead of a gap in the reading.

On entering, run `onboarding_notes.py --root . phase --set p2b` (the script is
`${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py`, run as the other scripts of this skill are).

## When it runs, and when it is skipped

Between phase 2 and phase 3, once, whenever the interview made a source reachable that
phase 1 could not read. Skipped entirely — say so in one line, do not invent work for it —
when the interview named nothing new: a single-root repository whose application code phase
1 already read has nothing left to open.

## What is re-read, and nothing else

Only the signal-table rows whose source was unreachable in phase 1, over the locations the
interview named:

| Row | Re-read over | Produces |
|---|---|---|
| Application stack | each `code_repos` path from topic 1 | entry points, services, how the app runs locally |
| Architecture and data | the same paths | DB/ORM and migrations, compose services, integrations, queues/events |
| Components and API inventory | the same paths | the component list `project-profile.md` opens with |
| Candidate environments | the same paths plus what topic 2 named | stand addresses and how each is brought up |
| How the stand is reached | the same paths (`project_inventory.py --root <path> --access` per repository) | the login call sites the application repositories hold, and their key NAMES |
| Existing cases / TMS | a test location the team named outside this repository | coverage that already exists |

The access row is the one place this phase may reopen a question, and only this one: if the
application repositories show a login scheme that contradicts the kind topic 2 settled on
(the harness logs in through its own command, not the endpoint the test repo names), put
*that single question* back as a one-item batch with both candidates and their file:line
evidence, and record the answer like any other: the batch is `p2b-access`, through
`onboarding_notes.py --root . ask` and `answer` as phase 2 does. A contradiction swallowed here becomes a
`login: failed` the first story cannot explain. Everything else found here is a fact for
phase 3's summary, not a new question.

Nothing else. Conventions, git history and the framework were read from the **test**
repository in phase 1 and are not re-derived here — the application repository's commit
style is not this test suite's convention, and overwriting a confirmed convention with a
second repository's habits is a regression, not an enrichment.

## Budget and rights

Read-only and bounded: this is an inventory, not an audit of somebody else's code. Sample
entry points and manifests, follow the directories the interview named, and stop as soon as
the five rows above have an answer or are demonstrably unavailable. Never write, never run
the application, never clone or check anything out — a path that is not on disk is "not
read: no local checkout", not an invitation to fetch it. The application repositories are
the code under test: P-00 covers them through `protected_app_paths`, and this phase only
reads.

## Output of this phase

Phase 1's notes, `<notes>/discovery.yaml`, extended in place: each row is written to its section as soon as it
is read, each new fact carrying the repository and file it came from (the section's `evidence` and `notes`).
Every row above ends in exactly one of three states, written as the section's `state` (`read`,
`not_read_no_checkout`, `not_read_nothing_found`; the sections are `application_stack`, `architecture_data`,
`components_api`, `candidate_environments`, `stand_access` and `cases_tms`), and phase 3 shows which:

- **read** — with the evidence;
- **not read: no local checkout** — the path was never given (topic 1 went unanswered);
- **not read: nothing found** — the path was given and searched, and the row genuinely has
  no answer there (the same positive control phase 1 demands).

The second state is not the third. "No integrations" written because nobody could open the
repository is a false fact about the project, and it is the whole reason this phase exists.
