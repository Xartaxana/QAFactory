# Updating an existing QA Factory installation

For Codex projects, also complete the [project access setup](INSTALL.md#codex-project-access)
before running upgrade smoke tests: select Full access and verify the active task's mode.
Keep an existing project default when already configured; a plugin upgrade does not reset
or grant host permissions, and does not replace hook trust review.

## 0.7.0 to 0.7.1

Update the existing plugin through its configured marketplace; verify 0.7.1 in both the
source and installed manifests. Do not export duplicate project roles, rerun onboarding,
replace config/strategy, or erase story evidence. Start a fresh host task to load updated
instructions and review changed hooks through the host trust UI when required.

Run qa-doctor's native allow/deny and diagnostic context probes. Missing essential host
behavior blocks Codex S1; a green script smoke is not a substitute. Diagnose GitLab API
identity/project access separately from SSH before resuming an MR-backed story. Resume
preserved source/checkpoint evidence after fixing access; required unavailable material
now blocks S1, including in old partial inventories. Old attachment references still read;
new downloads use compact content-hash paths. Existing tariffs/confirmations are retained.


## 0.6.x to 0.7.0

For a historical Codex run missing activity files, `scripts/recover_codex_usage.py --root <project> --transcript <rollout.jsonl> --boundaries <reviewed.json>` previews a reviewed import; add `--write` only after reviewing it. Boundary entries require the actual source `call_id`, `timestamp`, `action`, `type` and explicit story `task`. Preserve the old HTML/metrics first. The importer validates recorded tool-call intent, preserves unclassified gaps and refuses conflicting existing activity evidence. It does not infer activities from conversation text or certify command success; exclude failed calls during review.

- Preserve `qa-factory/config.json`, approvals, controller logs, case versions, run evidence,
  cost requests and activities. Do not recreate the project or rerun tests for the dashboard.
- Update the plugin source/cache using the host's install workflow, verify **0.7.0** in the
  installed manifest and doctor, then start a fresh task. Updating source does not update an
  already-running task or a different host's cached 0.6.0 installation.
- On Codex, follow [INSTALL.md](INSTALL.md): review the native hook manifest and export/reload
  native CLI role profiles where needed. No script silently grants hook trust.
- Run `install_smoke.py` for source/launcher checks, then `readiness.py --write` and the
  [native acceptance procedure](design/codex-native-acceptance.md). Missing live receipts
  remain unverified. Fresh-session rollover remains an explicit manual continuation.
- Run `factory_dashboard.py --root <project>` to regenerate only derived views. This creates
  `metrics-history.json` and `metric-signals.json`; no old trend values are invented.
- Existing exact request valuations stay pinned. Terra uses the verified standard API
  reference tariff, including its long-context boundary, only for new/unvalued requests.
  A project-specific tariff requires an explicit override. These are estimates, not invoices.
- Explicit activity starts reuse the open workflow across questions. Final completion uses
  `--after-response`; final capture closes it after the response. Old missing intervals stay
  unclassified. Import history only from evidenced boundaries, not prompt descriptions.
- New trend thresholds are opt-in versioned policy in `metrics.signal_policy`; the existing
  three-precedent estimate rule is built in. See [signal policy](design/metric-signal-policy.md).

The 0.6.0 contract migration below still applies when upgrading an older active story.


## Pending contract changes

The unreleased observation/identity changes require the exact updated installation,
not just a matching version string. Doctor and controller packets report its path and
fingerprint. New tasks require the observation contract before Gate A. Existing task
history stays immutable: run the controller migration dry-run, resolve its listed gaps,
then record the migration receipt. Missing semantics are never invented by migration.

A checkpoint preserves accepted results, approvals and remaining work. Resume in a new
orchestrator session only after active dispatches/jobs and external writes are settled.
Use the controller continuation packet and current lease; do not restart the story.
Automatic fresh-context rollover is unavailable unless the host supplies verified support.

Version 0.6.0 changes execution, coverage and evidence contracts. Verify version 0.6.0
and the installed plugin path after updating. A marketplace refresh cannot fetch uncommitted local edits.

## Plugin

Installed from an earlier marketplace (`claude plugin list` shows an id other than `qa-factory@qafactory`): uninstall that id first (`claude plugin uninstall <that id>`), then add this marketplace as in [INSTALL.md](INSTALL.md).

1. Stop active factory work. A reinstall is a migration: the project's `qa-factory/` ends up the
   same as after a fresh install, so do not remove it by hand. `qa-factory/records/` and the
   person's answers in `config.json` are kept; `qa-factory/state/` is machine-local and is
   regenerated. A file the installer cannot class is moved, never deleted, to
   `qa-factory/state/retired/<date>/`: look at it, then empty the folder. Git tracking is only
   read: the onboarding listing prints the `git rm --cached` lines for paths git tracks under
   `state/`, and the person runs them. From this version on, SessionStart prints one line when the
   plugin cache, the marketplace and the project's manifest differ in version; the first update
   from an older cache is by hand.
2. Ensure the marketplace has the release you want: `claude plugin marketplace update qafactory` fetches it from GitHub; for a local-clone marketplace, pull the clone first.
3. Reinstall in the same installation scope (user, project or local):

   ```sh
   claude plugin uninstall qa-factory@qafactory
   claude plugin marketplace update qafactory
   claude plugin install qa-factory@qafactory
   ```

   These commands show the default scope. Preserve any scope option used for the original
   installation. Reinstalling refreshes the cached package.
4. Restart Claude Code and run `/qa-factory:qa-doctor` inside the project repository.
   Check the reported version is the release you installed, the plugin path, smoke result and capability diagnostics.

## Existing project configuration

Run `/qa-factory:qa-onboarding`, choose `re-onboard`, and review the proposed merge. Existing
human values and unknown extension fields must not be silently overwritten. Confirm only the
repositories, selected capability profiles, scoped commands/reporters, manual evidence and
external destinations needed for that project. External dependencies are provisioned only
for selected capabilities with explicit managed descriptors; no blanket browser/mobile install.
Run `/qa-factory:qa-doctor` again. Its unresolved diagnostics are not a successful readiness
result. New stories may then start normally.

### Source access and usage additions

Jira projects need a direct API connection even if the ticket adapter uses an assistant.
Follow [Jira direct access](references/jira-direct-access.md), keep credentials in local
secret environment references, and run its sample-ticket probe. Existing assistant-only
configuration stays readable but original-material access is a named readiness gap.
Read permission does not authorize issue creation or attachment uploads.

New stories require a canonical source inventory. Older stories are not silently marked
fully inspected: refresh required sources and obtain an explicit updated Gate A when
requirements or approved evidence change. Do not restart accepted executions solely to
populate a new optional field. Unknown historical usage or missing external receipts
remain unknown; changed bundled rates do not override negotiated project rates.

## Existing stories

Completed historical stories remain historical and must not be rewritten to manufacture new
coverage evidence. For an unfinished story, preserve its files and perform an explicit migration:

- `migrate_artifacts.py <task-root>` previews legacy path moves; `--apply` applies the reviewed
  move only when no conflicting canonical file exists.
- Initialize/reconcile the legacy lifecycle through the controller contract before coverage
  migration. Imported legacy receipts remain stale until their actual evidence is reconciled.
- `migrate_coverage.py <task-root>` previews coverage v1-to-v2 migration; `--apply` backs up the
  old plan and records the new contract. A historical story without active controller events
  is deliberately unchanged. A version disagreement is a blocker, not permission to guess.
- Mechanically migrated obligations remain unresolved until their sources, assertions and
  sufficiency are assessed. Revisit Gate A for changed plan/oracle bindings. Reuse only evidence
  that still matches the current source, case, execution and runtime fingerprints.

Run scripts from the verified installed plugin directory; `<task-root>` is the exact existing
`qa-factory/artifacts/<ticket>` path. There is no single automatic in-place upgrade command for
all active stories. Never reset a task to S0 or rerun its full suite merely to perform migration.

## Verification limits

Local contract and integration fixtures cover compatibility, recovery, coverage and delivery.
A real-project update rehearsal, external adapter acceptance and the paired >=2x cost benchmark
remain separate empirical checks.
