# qa-doctor

Diagnoses whether the qa-factory plugin and the current project are healthy, and tells
you the one thing to do next.

## What it does

Runs five checks, in order, each backed by one of the plugin's own scripts so nothing is
re-derived by hand:

1. **Install smoke** (`install_smoke.py`) — confirms the plugin's files, Python, and the
   hook mechanics answer at all.
2. **Project state** — is the current directory a git repository; does
   `qa-factory/config.json` exist; if it does, `readiness.py --json` reports every
   capability a story might need (`ticket_adapter`, `test_repo`, `app_repo`, `vcs`,
   `environment`, `external_writes`, `config_schema`) as `ok`, `missing`,
   `not_configured`, or `unknown`, each with an owner and a note.
3. **Factory audit** (`audit_factory.py`, `role_permissions.py`) — current checks (hook
   liveness, artifact schemas, journal completeness, the injection map, skill size,
   deferred decisions, whether a role's charter asks it to run a script its own `tools:`
   don't include, and more). Doctor never creates or implies a review schedule.
4. **Where every story is** — reads every `qa-factory/artifacts/<TICKET>/pipeline.json`
   and reports, per ticket, the last completed stage, any stage currently running or
   halted, both gate decisions, and every unresolved halt.
5. **Dashboard rebuild** (`factory_dashboard.py`) — the only file this skill writes.

Then it prints **exactly one** recommended next action, chosen by priority: a broken
install outranks everything else, then "this isn't a git repo", then "no config — run
onboarding", then a stale config schema, then a missing capability a story needs, then an
open story halt, then an open gate, then the first audit failure, and only once all of
that is clean does it suggest starting or continuing a story.

## When to use it

- Before the first `qa-story` run in a project, to confirm the setup landed correctly
- After a story halted or a session ended abruptly, to see where things stand without
  re-reading every artifact by hand
- Any time something in the factory feels wrong and you want one place that has already
  checked it
- To regenerate the dashboard without waiting for the next story's closing stage (S9)

## How to ask

- "check the qa-factory setup"
- "qa doctor"
- "where is the story?"
- "/qa-factory:qa-doctor"

## Prerequisites

- The `qa-factory` plugin installed (`claude plugin install qa-factory@qafactory`)
- `git` and Python 3.10+ on `PATH`
- A git repository as the working directory (steps 2–5 need a project root to look at;
  step 1 works anywhere)

## What it does not do

- Does not create or repair `qa-factory/config.json` — that is `qa-onboarding`
- Does not run tests
- Does not answer a gate or resolve a halt on your behalf — it names which one is open
- Does not modify any file other than `qa-factory/state/factory-dashboard.html`
- Never asks a question
