"""Acceptance coverage for C1/C2 configuration, inventory, DD and strategy grants."""
import json
import subprocess
import sys
from pathlib import Path

from harness import check, check_eq, cleanup, finish, temp_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_contract import (RUNTIME_DEFAULTS, apply_plan, canonical_template,
                             editable_strategy_paths, effective_config, migration_plan,
                             record_approval, validate)
from project_decisions import add_finding, due, parse_findings, parse_rows, resolve, upsert
from project_inventory import build_inventory
from factory_dashboard import parse_deferred_decisions


def main() -> None:
    template = canonical_template()
    effective = effective_config(template)
    check_eq("template schema is canonical", template["schema_version"], 1)
    check_eq("template and code agree on parallel defaults", effective["execution"]["parallel"],
             RUNTIME_DEFAULTS["execution"]["parallel"])
    check_eq("canonical template validates", validate(template), [])
    forbidden = {"gate_green_runs", "audit_cadence_days", "exploratory_cadence_days",
                 "maintenance_cadence_days", "maintenance_sla_days", "artifacts_retention"}
    check("canonical config emits no inactive policy", forbidden.isdisjoint(template))

    # Built on the whole template: a bare schema-1 config lacks required keys, and apply_plan now
    # refuses to write the values it would have invented for them (t-239 O2-5).
    # `environment.access` is asked until answered (t-298): this config records the person's answer ("no login at all"), so it is no open row here
    old = {**template, "custom_extension": {"keep": True},
           "environment": {**template["environment"], "access": {**template["environment"]["access"], "kind": "none"}},
           "external_writes": {"commands": {"jira": "deliver --ticket {id}"}, "channels": {}}}
    plan = migration_plan(old)
    check_eq("legacy command proposes exact channel", plan["proposed_config"]["external_writes"]["channels"]["jira"]["command"], "deliver --ticket {id}")
    check_eq("migration preserves unknown extension", plan["proposed_config"]["custom_extension"], {"keep": True})
    conflict = migration_plan({"schema_version": 1, "external_writes": {
        "commands": {"jira": "old"}, "channels": {"jira": {"method": "command", "command": "new"}}}})
    check_eq("conflicting channels are explicit", len(conflict["conflicts"]), 1)

    root = temp_project("qa-config-contract-")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg_path.write_text(json.dumps(old), encoding="utf-8")
        record_approval(root, plan, "onboarding:approval-1", "transcript:event-7")
        try:
            apply_plan(root, plan, "typed-yes-but-not-recorded")
            unrecorded_refused = False
        except ValueError:
            unrecorded_refused = True
        check("arbitrary approval text cannot authorize apply", unrecorded_refused)
        backup = apply_plan(root, plan, "onboarding:approval-1")
        check("apply writes content-addressed backup", backup.exists())
        applied = json.loads(cfg_path.read_text(encoding="utf-8"))
        check_eq("apply retains original command as a value", applied["external_writes"]["channels"]["jira"]["command"], "deliver --ticket {id}")
        cfg_path.write_text(json.dumps({"schema_version": 1, "external_writes": {
            "commands": {"jira": "old"}, "channels": {"jira": {"method": "command", "command": "new"}}}}), encoding="utf-8")
        try:
            apply_plan(root, conflict, "approval")
            refused = False
        except ValueError:
            refused = True
        check("apply refuses unresolved conflict", refused)

        # One real checkout referenced twice, one missing and one invalid entry.
        repo = root / "repo"; repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=10)
        inv_cfg = {"tests_root": "repo", "code_repos": [
            {"name": "app", "path": "repo", "default_branch": "main"},
            {"name": "missing", "path": "missing"}],
            "implementation_repos": [{"repo_id": "same", "local_path": "repo", "role": "service"},
                                     {"repo_id": "invalid", "local_path": ""}]}
        inventory = build_inventory(inv_cfg, root, {"missing"})
        check_eq("inventory preserves every configured entry", inventory["configured_entries"], 5)
        check_eq("duplicate checkout references merge", len([r for r in inventory["repositories"] if "app" in r["names"]]), 1)
        missing = next(r for r in inventory["repositories"] if "missing" in r["names"])
        check_eq("selected missing checkout is scoped", missing["scope_required"], True)
        check("all unresolved entries remain visible", inventory["unresolved_entries"] >= 2)

        backlog = root / "qa-factory" / "factory-backlog.md"
        backlog.write_text("# Findings about the factory itself\n", encoding="utf-8")
        first = upsert(root, field_refs=["/test_data/seeds"], essence="Seeds unresolved",
                       asked="batch 2: how are seeds created?", scope="project", owner="user")
        second = upsert(root, field_refs=["/test_data/seeds"], essence="Different prose",
                        asked="asked again", scope="project", owner="user")
        check_eq("repeated onboarding reuses DD by field refs", second["id"], first["id"])
        closed = resolve(root, first["id"], "fixtures.py, approved by owner", "decision:42",
                         {"/test_data/seeds": "fixtures.py"})
        check_eq("evidence closes DD", closed["status"], "closed")
        check_eq("resolution updates exact config field",
                 json.loads(cfg_path.read_text(encoding="utf-8"))["test_data"]["seeds"], "fixtures.py")
        rows = parse_rows(backlog.read_text(encoding="utf-8"))
        check_eq("canonical markdown row is closed", rows[0]["resolution_ref"], "decision:42")
        dashboard_rows = parse_deferred_decisions(backlog)
        check_eq("dashboard maps canonical status by column name", dashboard_rows[0]["status"], "closed")
        check_eq("dashboard maps canonical trigger by column name", dashboard_rows[0]["trigger_type"], "manual")
        check_eq("manual trigger never ages overdue", due({"trigger_type": "manual", "trigger_value": ""}), False)

        strategy = root / "qa-factory" / "strategy" / "test-strategy.md"
        strategy.parent.mkdir(parents=True, exist_ok=True)
        strategy.write_text("[DEFERRED: impact decision]\n", encoding="utf-8")
        marked = upsert(root, field_refs=["/dod"], essence="impact decision",
                        asked="batch 3: what is done?", scope="project", owner="user")
        try:
            resolve(root, marked["id"], "done means reviewed", "decision:43", {"/dod": "reviewed"})
            marker_refused = False
        except ValueError:
            marker_refused = True
        check("DD cannot close while paired marker remains", marker_refused)
        resolved_marked = resolve(root, marked["id"], "done means reviewed", "decision:43",
                                  {"/dod": "reviewed"}, ["qa-factory/strategy/test-strategy.md"],
                                  "[DEFERRED: impact decision]")
        check_eq("marker and field close together", resolved_marked["status"], "closed")
        check("paired marker is removed", "[DEFERRED:" not in strategy.read_text(encoding="utf-8"))

        finding = add_finding(root, essence="Feedback: too much report noise",
                              scope="local-calibration", witness="retro.md#feedback",
                              idempotency_key="QA-1:human-feedback")
        finding_retry = add_finding(root, essence="Feedback: too much report noise",
                                    scope="local-calibration", witness="retro.md#feedback",
                                    idempotency_key="QA-1:human-feedback")
        check_eq("finding retry reuses stable FB id", finding_retry["id"], finding["id"])
        check_eq("canonical finding is appended once",
                 len(parse_findings(backlog.read_text(encoding="utf-8"))), 1)

        cfg = {"factory_may_edit_strategy": False, "strategy_documents": [
            {"path": "docs/testing.md", "provenance": "pre_existing", "editable": True,
             "decision_ref": "decision:7", "source_refs": ["docs/testing.md"]}]}
        allowed = editable_strategy_paths(cfg, root)
        check("exact opted-in strategy file is editable", (root / "docs/testing.md").resolve() in allowed)
        check("adjacent strategy file is not editable", (root / "docs/other.md").resolve() not in allowed)
        legacy = editable_strategy_paths({"factory_may_edit_strategy": True}, root)
        check_eq("legacy permission remains limited to two targets", len(legacy), 2)
    finally:
        cleanup(root)
    finish("test_config_discovery")


if __name__ == "__main__": main()
