# Phase 0 — Preflight

Canon of a `qa-onboarding` phase. Read on entering the phase; the table in `SKILL.md` is a
map, not a substitute. Nothing in this phase writes a file (a start over only sets the run's own notes aside) — it only checks, announces, and
(once) asks a single yes/no gate question when a prior onboarding already exists.

## 1. Plugin and Python are alive

Resolve the plugin root first — `common-rules.md`, "Resolving the plugin root".
For Codex, first check the active permission mode supplied by the host against
`${CLAUDE_PLUGIN_ROOT}/INSTALL.md`, "Codex project access". Installation includes Full access
selection for the target project. If setup was skipped, point to that step; do not edit
host permissions as an onboarding side effect. Do not infer active Full access from a
config file or a successful command alone. If the mode is unavailable, report it as unknown.
Distinguish sandbox-denied temporary-directory/network access from a plugin failure;
use the host's supported permission/approval flow instead of repeatedly retrying the
same blocked smoke test. Then:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/install_smoke.py"
```

`python: can't open file '/scripts/install_smoke.py'` is not a failing check: the variable
was empty and the path collapsed to `/scripts/...`. Resolve the root and run it again; do
not report the plugin as broken on that message.

This runs the plugin's own hooks and helpers against a disposable sandbox project — it
never touches the real project. Any `FAIL` line stops onboarding here: report the failing
check verbatim and name the one fix ("reinstall the plugin", "install Python 3.10+ on
PATH"). This is a blocker, not a question — do not proceed into discovery on a partial
liveness result.

## 2. The current directory is inside a git repository

```
git rev-parse --show-toplevel
```

Git not found → halt, naming git as the missing program. No output / an error → halt: "run
`qa-onboarding` from inside a git repository" and stop; there is nothing sensible to onboard
otherwise.

The project root is the current directory: `qa-factory/` and the ignore block are written here.
The project may be a subfolder of the repository (a monorepo): the factory finds its project by
`qa-factory/config.json`, not by the top level (`common-rules.md`, "What a path is relative to").
When the printed top level is not the current directory, say so in ONE line naming both, ask
nothing, and go on.

## 3. Working-tree state — informational only

```
git status --porcelain
```

Note whether the tree is clean or dirty. Onboarding never blocks on this and never asks
about it here: it writes only under `qa-factory/`, creates no branch, and commits only that
one directory at phase 4 regardless of what else is dirty. Carry the note forward — phase 1
records it in the notes (`start --tree clean|dirty`), and phase 4 restates it before its own commit.

## 4. Announce the scope — state it, do not ask it

Print, once, verbatim:

> QA Factory v0 covers functional testing only. Non-functional checks (performance,
> security, accessibility, localization, compatibility, privacy) are out of scope in this
> version — there is no question here because there is no choice to make yet.

No question is attached to this line. If discovery or the interview later surfaces a
non-functional concern, note it as an out-of-scope observation in `project-profile.md`
(phase 4), never as a question to the team.

## 5. Versions, and the install that is already there

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboard_apply.py" --root . --preflight
```

It reads and writes nothing in the project and prints one JSON document: `install_exists`,
`config_present`, `manifest`, `table_hits` and `version_line`. The same version check also runs
when a Claude Code session starts (one implementation, two callers).

- `version_line` is not empty → show that one line to the person, as it stands. It says what runs,
  what the marketplace has, what installed this project, and the one move that follows. It is
  information, not a question: go on unless the person wants to update the plugin first.
- An install exists if there is a `config.json`, **or** an install record (`manifest`, even an
  unreadable one), **or** any `table_hits` (files the factory recognises as its own, or its
  first-generation `.gitignore` line). A project with old traces and no config is never "clean".

Then ask what the run left behind, before the config is read:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/onboarding_notes.py" --root . status
```

It writes nothing and always answers. When `onboarding_notes.py --root . status` reports an
unfinished onboarding, show its date, its phase and the topics already answered, and ask one
question: resume it, start over (its notes are set aside, never deleted), or stop. This is the one
question of this phase: with a `config.json` present as well, "re-onboard from the start" takes the
place of "start over", and the question further down is not asked a second time.

- `readable: false` (the progress file is empty, damaged or from a newer factory): nothing of the run
  is reused. Offer start over or stop only.
- `resume` → read the phase text its `phase` names and continue from the notes. A section listed in
  `stale_sections` is re-read, the others are kept; a topic listed as answered is never asked again.
- `start over` → `onboarding_notes.py --root . set-aside`, then go on as for a first onboarding.

Then read `qa-factory/config.json` if it exists at the project root.

- **Does not exist, `install_exists` false** → this is the first onboarding. Proceed straight to
  phase 1.
- **Does not exist, `install_exists` true** → traces of an earlier installation with no
  configuration. Say so in one sentence, naming a few of the `table_hits`: "this project has traces
  of an earlier QA Factory installation but no configuration; onboarding takes what it needs, lists
  at the summary what it would remove, and changes nothing before your yes". Ask nothing here;
  proceed to phase 1. Installing is migrating: this case and a fresh install take the same path.
- **Exists, `schema_version` matches** `references/templates/config.json`'s current value
  (`1`) → this project has already been onboarded. Ask exactly one binary question — this
  is the single question this phase is allowed to ask, separate from phase 2's topic
  batches:

  > This project already has a QA Factory setup (`qa-factory/config.json`, onboarded
  > <date from the file if recoverable, else "previously">). Re-onboard — re-run discovery
  > and the interview, and merge approved discoveries with the existing human values — or stop here and
  > leave everything as it is?

  `stop` → end the skill run immediately with a one-line digest ("no changes made, existing
  setup left in place"). `re-onboard` → proceed to phase 1; phase 2 offers each existing
  answer as the default so re-onboarding is a confirmation pass, not a fresh interrogation
  from zero.

The existing configuration is the config file itself, unchanged until the yes; its sha256 is in the
notes. Re-onboarding must later compare three inputs: existing values, new read-only discovery
facts, and human edits. Existing human values and unknown `profiles[].extensions` keys are never overwritten
silently.

- **Exists, `schema_version` missing or older than current** → same two options, but name
  what changed: list the top-level keys present in `references/templates/config.json` that
  are absent from the project's `config.json` ("this version added: `environments[]`,
  `adapters`"), so a "re-onboard" choice is an informed migration, not a guess.

## Exit

Phase 0 ends either in a halt (liveness failure, git missing or no repository, or an explicit "stop" on
re-onboarding) or with the scope announced, the version line shown when there is one, and a clear
decision to proceed into phase 1.
