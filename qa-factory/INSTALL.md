# Installing qa-factory

QA Factory 0.11.0 ships separate Claude and Codex hook manifests. Project state lives under `qa-factory/`; native Codex role export also creates explicitly managed `.codex/agents/*.toml` profiles.

## Codex

1. Register this repository's marketplace with `codex plugin marketplace add <local-clone-or-git-source>`.
   Use `codex plugin marketplace list` and `codex plugin list` to verify the actual source and
   marketplace name before installing. Do not assume a Claude cache is a Codex installation.
2. Install `codex plugin add qa-factory@<verified-marketplace-name>`. Confirm the installed
   manifest matches the source version (including its Codex build suffix) and points to `./hooks/codex.json`.
3. Review/enable the plugin hooks in the host's trust flow. Repository trust, source smoke,
   and file existence do not grant hook trust. Do not bypass this review in configuration.
4. Configure **Full access for this project** using the [Codex access setup](#codex-project-access)
   below, before the first doctor/onboarding smoke test. Installing the plugin alone does
   not change the current task's permissions.
5. Existing plugin roles need no project-local reinstallation during an upgrade. Only when
   the chosen CLI host requires explicit custom-agent profiles, preview `python <plugin>/scripts/codex_roles.py --root <project>`;
   add `--write` to export the canonical roles into `.codex/agents/`. Existing user-owned
   profiles are protected. `--policy <json>` accepts explicit `roles.<role>.model/effort`
   overrides; omitted values inherit the host. Reload the host after changing profiles.
6. Start a fresh Codex task, verify its active permissions are **Full access**, and run
   qa-doctor. Inspect `host_integration` in `state/readiness.json` (an older project: `readiness.json`
   beside `config.json`) and `state/host-receipts/`: missing or stale mechanisms are unverified, never green.
   Follow [the native acceptance procedure](design/codex-native-acceptance.md).
7. Run a story through the driver, not through a desktop orchestrator:
   `python <plugin>/scripts/story_run.py --task <TICKET> --host codex` from the project root (or
   `"driver": {"host": "codex"}` in `config.json`); with `--model` absent the run uses `default_model.codex`
   of `references/driver-infra.json`. The driver's exit codes and the cost line are in [design/driver.md](design/driver.md).

The adapter targets the documented native event contract. Usage format was observed in
`0.155.0-alpha.2.6`; source/launcher fixtures are tested on Windows. This is not a claim
that every client version activates all hooks or that live parity has been certified.
See [the audit](design/codex-compatibility-audit.md) for current acceptance evidence.

### Codex project access

The Codex installation procedure includes selecting **Full access** for the project that
will run QA Factory. This removes the shell sandbox's filesystem and network restrictions
and automatic approval prompts for that task. It applies to all Codex work in the task,
not only factory commands. Factory review gates and hook trust remain separate.

In **Codex Desktop**, select **Full access** in the permissions menu below the composer.
For a persistent project default, merge these two top-level settings into
`<target-project>/.codex/config.toml` (the test project, not the installed plugin cache):

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"
```

Keep these keys before the first `[table]`; update existing definitions instead of adding
duplicates. Preserve all other settings. Use the project-local file rather than changing
the user's global defaults. The project must be trusted for Codex to load its configuration.
Do not combine these legacy sandbox settings with `default_permissions` / `[permissions]`;
if the project already uses permission profiles, select Full access through the host's
permissions control instead of merging incompatible configuration schemes.

After changing the default, start a new task in that project and check its actual permission
mode. A previously opened Desktop task may retain its selected permissions; switch that
task to Full access explicitly. A config file alone is not proof that the active task is
unsandboxed. Organization-managed restrictions may prevent this mode; report the policy
restriction and use the allowed mode rather than attempting to bypass it.

For **Codex CLI**, launch from the target project with explicit settings when needed:

```sh
codex --sandbox danger-full-access --ask-for-approval never
```

This is a host setup step performed by the project owner or an installer acting on their
instruction. Plugin hooks and normal doctor/onboarding runs do not rewrite permissions or
grant themselves hook trust. Full access does not prove Git/API credentials or live hook
behavior: run the existing doctor checks after selecting it. A sandbox-denied temporary
directory or network call is an execution-permission issue, not evidence of a broken plugin
or invalid credentials; report it separately instead of repeatedly running the same probe.

See the official [sandbox settings](https://learn.chatgpt.com/docs/sandboxing) and
[project configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#project-config-files-codexconfigtoml).

## From GitHub

```bash
claude plugin marketplace add Xartaxana/QAFactory
claude plugin install qa-factory@qafactory
```

The marketplace is named `qafactory`; `qa-factory` is its plugin. Source: https://github.com/Xartaxana/QAFactory.

## From a local clone

```bash
git clone https://github.com/Xartaxana/QAFactory.git
claude plugin marketplace add /path/to/QAFactory
claude plugin install qa-factory@qafactory
```

Clone it **outside every project you onboard with the factory** — a sibling directory is the
usual place (`~/code/QAFactory` beside `~/code/my-project`). Hooks and self-tests
resolve "the project" by the nearest `qa-factory/config.json` above their working directory,
so a plugin root that lies inside an onboarded project makes that project's stories the answer
for code that meant to look at its own sandbox. The layout that broke a 0.7.11 install was a marketplace clone inside the project
(`<project>/<clone>/.../qa-factory`): `install_smoke.py` reported five
failures against the user's real stories, and two reinstalls changed nothing. Since 0.7.12 the
smoke runs its self-tests from a neutral directory and prints one `INFO` line when it finds
the plugin root inside a project — the layout still works, but keep the clone outside.

A local clone is installed as it lies on disk: the marketplace copies the directory, and
`.gitignore` is a git rule, not a copy rule, so anything a test run left inside
the package directory is installed along with the factory — an empty leftover directory
included, which `git status` cannot even see. Run `python scripts/selftest.py --hygiene` in
the clone before installing; it names every file that is not package content. The installed
copy checks the other end of the same copy: `python scripts/install_smoke.py` reports the
development leftovers that reached the install.

Verify:

```bash
claude plugin list | grep qa-factory
```

## Requirements

| Requirement | Why |
|---|---|
| `git` on PATH | Branches, MR conventions, project root detection |
| Python 3.10+ on PATH (`py`, `python` or `python3`) | Every hook and helper is Python; the launcher `hooks/run-py.cmd` finds the interpreter |
| A git repository as cwd | `qa-onboarding` and `qa-story` write their state into `<project>/qa-factory/` |

Optional: MCP tools or CLIs for your ticket system (Jira, Azure DevOps, GitLab, GitHub) and test management (Xray, TestRail, Zephyr). Channels are chosen during onboarding; the default writes markdown files only.

## Upgrading an existing installation

Follow [UPGRADE.md](UPGRADE.md). It covers the cached plugin, existing
project settings, and explicit migration of unfinished stories. Do not delete project state.

## After installing

```
/qa-factory:qa-doctor
```

It reports what is missing and the one thing to do next — normally `/qa-factory:qa-onboarding`.

## Uninstalling

```bash
claude plugin uninstall qa-factory
```

`<project>/qa-factory/` is yours and stays in place.

## Developing the package

Claude Code caches an installed plugin's files. After editing anything under this
package (a skill, a script, a reference, an agent), the cache is refreshed only by the
full cycle — a plain re-`install` over the same version does not pick up the change:

```bash
claude plugin uninstall qa-factory@qafactory
claude plugin marketplace update qafactory
claude plugin install qa-factory@qafactory
```

Run `python scripts/selftest.py --fast` from the package root before every commit and the
full `python scripts/selftest.py` before a release — they catch wiring, language and size
problems before they reach an install. See `README.md`'s
"Development" section for the full local-check list.
