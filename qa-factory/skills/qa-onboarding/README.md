# qa-onboarding

Teaches QA Factory this repository, once. Run it before the first `qa-story` in any
project; run it again after a major change to tests, environments, or conventions.

## What it does

1. **Preflight** — confirms the plugin and Python answer, confirms the working directory
   is a git repository, and states (does not ask) that QA Factory v0 covers functional
   testing only. If this project was already onboarded, it offers a plain choice:
   re-onboard or leave everything as it is.
2. **Discovery** — reads the repository, not just its file names: the test framework and
   layers, real run commands, CI gates, conventions already written down by the team
   (README/CONTRIBUTING/CLAUDE.md/docs), conventions it can infer from the tests
   themselves (assertion style, an SDK layer instead of raw API calls, fixture placement),
   git-history conventions, existing cases, and where the application and test code
   actually live — which are not always the same repository. No questions in this step.
3. **Interview** — asks only what discovery could not answer, in short batches (at most
   four questions at a time): the test and application repos, environments and
   credentials, test-data ownership, risk areas, git conventions, the inferred conventions
   (confirm/edit/add), the ticket and test-management adapters, where bugs and cases
   should be written (files in the repo by default, or a tracker), the definition of done,
   and the product basics that open the project profile. A fact the factory needs and
   discovery could not find is asked outright here — never skipped for lack of a guess to
   confirm, and never turned into a "deferred" item without the question having been put.
4. **Summary gate** — one screen: what was found, what was answered, what will be written,
   and what is being deferred. No project file is written until you say `yes` (the run keeps its
   own notes in `qa-factory/state/onboarding/`, which git ignores, so a compaction or a new
   session does not lose what you already answered); `edit` gets you one more round of the same summary.
5. **Generate** — writes `qa-factory/config.json` and a `qa-factory/strategy/` folder
   (test strategy, project profile, framework rules, aspect profile, FAQ, a starting
   coverage map), an empty dashboard, and a readiness report, then commits just that
   directory. One document describes the project — `project-profile.md`; the product's
   goal, users and requirements source are its opening sections, not a second file.

## When to use it

- Before the first `/qa-factory:qa-story <ticket>` in a repository.
- After a significant change to the test setup, environments, or team conventions.
- When `/qa-factory:qa-doctor` tells you to.

## How to ask

- "onboard this repository for QA"
- "set up qa-factory"
- "qa onboarding"
- "install the factory"
- `/qa-factory:qa-onboarding`

## Prerequisites

- A git repository as the working directory.
- Python 3.10+ on `PATH` (the plugin's scripts are Python).
- The `qa-factory` plugin installed (`claude plugin install qa-factory@qafactory`) —
  see the package `INSTALL.md`.
- Optional: an MCP tool or CLI for your ticket system and test-management system. Without
  one, onboarding still completes — bugs and cases default to markdown files in the repo.

## What it writes into your project

Only `<project>/qa-factory/` — never `.claude/agents`, `.claude/settings.json`, or any copy
of the plugin's own code. The plugin's code stays where it was installed; this directory is
the only thing that travels with your repository.

## What it does not do

- Onboarding records how to reach and prepare each environment, including authorization;
  story execution inspects the runtime before using those commands.
- It never writes anything before you approve the phase-3 summary with `yes`.
- It never asks about testing cadences, a metrics dashboard menu, or non-functional
  testing types (performance, security, accessibility, localization, compatibility,
  privacy) — v0 has no mode for any of these yet.
- It does not generate test cases, write test code, or run tests — that is `qa-story`.

## Re-running

Safe. Phase 0 detects an existing `qa-factory/config.json` and offers re-onboarding; every
interview question in a re-onboarding run shows the existing answer as its default, so a
refresh is a confirmation pass, not a fresh interrogation.
