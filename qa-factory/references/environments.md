# Environments

How a story resolves where to run, how to authenticate, and who owns fixing what breaks.
The durable answers live in the project's `qa-factory/config.json`; this document is how
that data is produced and used.

## The `environment` block and the `environments[]` list

Onboarding fills `config.environment` (how a role obtains address, account, and health —
an env file, or the process environment for CI secrets/a secret manager; `env_probe.py`
covers both and never prints secret values) and a list `config.environments[]`, one entry
per named stand (`local`, `QA`, `staging`, …): name, `base_url`, how to bring it up,
credentials by role, and what may safely be broken there (a destructive test needs an
explicit "safe" marking on that entry — absence means unsafe, not unknown). A role's account:
`credentials_by_role["<role>"] = "<USER_KEY> / <SECRET_KEY>"` (env-file names, no values), recorded by
`project_knowledge.py account` (config).

## Authorized environment preparation

Use the stand selected by the user or the approved project policy. Inspect its actual
runtime before deciding whether anything needs updating. Authorization to prepare a test
stand permits the selected adapter's minimal update; it does not authorize arbitrary
application-code patches, production changes or a rollback solely to collect baseline.
Follow `references/environment-preparation.md` for observations, command jobs and readiness.
A missing before state never blocks current-version tests: report the incomplete comparison
and offer the user a source or self-check choice at the end.

## Preflight, before any suite runs

**`env_probe`** — is the stand and its account reachable at all (address, health check,
declared integration prerequisites with their owners). No diagnostic run per area follows it:
the factory answers `reused` / `already_run` for a test with a result on unchanged bytes,
stand and version, and launches nothing.

A failing line marks the affected area `blocked_by_env` with an owner attached
immediately — it does not wait to be discovered mid-suite.

## Every block carries its own fix (`remedy`)

A row that blocks on the environment — `unresolved[] blocked_by_env` in the automation
manifest, `env_blocked[]` in a run report — carries the change that would end the block:

`remedy: {kind: flag | credential | data | service, where: <file:lines, or the variable
NAME>, change: <what to set>, restart: <what to restart>}`

You have already read the file to know it is blocked, so the fix costs nothing to record —
and without it the person is handed a state instead of one line they could act on. **Names
only**: the variable name and the file it belongs in, never its value; an artifact is read by
everyone the story is shown to. `s5_precheck.py` and `validate_artifacts.py` refuse a row
that blocks with no remedy or prints a value, and the gate turns the remedy into the card the
person answers (apply it on their word, do it themselves, take the case and run it where the
prerequisite exists, or accept it blocked).

A block that comes from the test's own fixture is not an environment block at all: if the
case's Given/When/Then and `preconditions` never ask for that fixture, tool or integration,
it is a test defect — build the minimum the Then requires, through the API.

## `execution_status` — closed vocabulary

Every run's outcome is one of exactly these, assigned by the runner from the run's own
evidence, never hand-written by a role:

`passed · failed · env_blocked · not_executed · broken_run · timeout`

`env_preflight: blocked` maps to `env_blocked` — one field, one source; a role never
overrides it with its own judgment of what "really" happened.

## Test data

Onboarding records the project's strategy — fixtures, factories built per run, a shared
seeded stand, or human-prepared data — the same way it records everything else about the
environment. `common-rules.md`'s "own test data" rule follows from whichever strategy is
recorded: a shared seeded stand is the only case where depending on an existing record is
not itself a finding, and only for the entities the project named as shared.

## ENV_ISSUE ownership

An environment problem is a blocker, not a debt line, and it has exactly one of two owners:

- **`owner: factory`** — data seeding, bringing up or mounting test-stack services, test
  config: the factory fixes it itself in the same stage (this is not application code,
  P-00 stays intact).
- **`owner: user`** — beyond the factory's rights or access (a missing credential, a
  feature flag only an admin can flip, VPN access). This becomes a gate B item with a
  concrete list of what is needed from whom — never silently worked around, never left as
  "chronic" or "pre-existing" as a reason not to fix it. A perpetual ENV_ISSUE means tests
  systematically cannot execute; that is a finding about the factory's setup, escalated,
  not absorbed.

## What a role does with a blocked area

Stop and report the blocker with the concrete list of what is missing (which credential,
which access, which seeding) — this is a halt, not a question of taste, and not something a
role decides to route around on its own. Only the human's explicit "defer it" decision (a
gate B event in the journal) turns a blocker into a legitimate, tracked deferral.


## Recorded environment properties

A person may accept a stand gap once as a property of the environment (`accept always` on a card). The answer is kept, with
their own words, in `qa-factory/records/environment-properties.json` (`environment_record.py show` lists it); no later gate or
story asks that gap again, and a card says so in "Decided once for this environment". Only a gap whose cause is the environment's
configuration (mocks instead of a real API, a service this stand does not have) is kept, as "on this environment X cannot be
checked"; a file or the machine (a report not written, a runner that failed, a missing dependency) is a fault and is never kept.
The key is exact: a level (every test of one execution contour) is kept for that command and that failure, a case gap for that
stand as configured. A changed command, another failure or a re-pointed stand asks again, and so does `<name>: ask again`.
Roles never write the file; the driver and the conductor do.

## Scoped integration discovery

Integration readiness is scoped: `env_probe.py --env NAME --obligation ID` accepts repeated
obligation IDs. A row without `credential_alternatives` is read by `env_probe.py` as `unknown`
(legacy keys are not interpreted there), while gate A asks about every key of it, as an AND;
that is why onboarding writes the alternatives it can establish, and `keys` is their union.
`read_at` (`path:line` where the code reads the keys) may stand in for `required_by`.
During discovery, identify `required_by` obligation IDs, applicable `environments`, and
`credential_alternatives` (OR of arrays; AND inside each array). Preserve unknown if code
or an access probe cannot establish a fact. A Markdown case store does not imply that the
application has no runtime integration requirements. Do not probe not_required services.
