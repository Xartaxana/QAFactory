#!/usr/bin/env python3
"""Package F: onboarding discovery (judge_discovery.py), the S1 attachment screen added to
judge_sources.py (disc_attachment_worth_opening), and the diff-hunk screen (judge_diff.py).

No test here reaches the network: `judge._post` is replaced by a table transport exactly as
test_judge.py does, so what is checked is this package's own code - candidate selection,
threshold behaviour, the inventory write for a skipped attachment, and the diff-hunk skip list.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import judge  # noqa: E402
import judge_discovery  # noqa: E402
import judge_diff  # noqa: E402
import judge_sources  # noqa: E402
from source_inventory import load_inventory  # noqa: E402


def fake_transport(table):
    calls = []

    def post(payload, key, timeout, attempts=4):
        calls.append(payload)
        answers = {}
        for name, question in payload["questions"].items():
            value = table(payload["state"], name, question)
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": value}
            elif question["type"] == "choice":
                answers[name] = {"type": "choice", "choice": value[0], "confidence": value[1],
                                 "probabilities": {value[0]: value[1]}}
            else:
                answers[name] = {"type": "score", "score": value[0], "confidence": value[1],
                                 "probabilities": {str(value[0]): 1.0}}
        return {"model": "judge-test", "answers": answers, "usage": {"input_tokens": 50}}
    post.calls = calls
    return post


def on_cfg(key_env="QA_JUDGE_DISC_TEST_KEY"):
    return {"provider": "typesafe", "mode": "on", "model": "judge-test", "api_key_env": key_env,
           "thresholds": {}, "disabled": [], "project_root": None}


def shadow_cfg(key_env="QA_JUDGE_DISC_TEST_KEY"):
    return {**on_cfg(key_env), "mode": "shadow"}


def none_cfg():
    return {"provider": "none", "mode": "on", "model": "judge-test", "api_key_env": "x",
           "thresholds": {}, "disabled": [], "project_root": None}


def seed_attachment_inventory(work: Path) -> Path:
    """A task source (for story_state) plus one referenced source with two attachments
    already fetched (`status: read`) and still `analysis_status: pending`."""
    (work / "sources/SRC-TASK/rev1").mkdir(parents=True)
    (work / "sources/SRC-TASK/rev1/ticket.json").write_text(json.dumps(
        {"key": "T-1", "type": "Story", "title": "Visual diff shows node colours",
         "description": "Added/removed/modified nodes get a distinct border colour.",
         "acceptance_criteria": "Added node: green border. Removed node: red border."}),
        encoding="utf-8")
    output = work / "source-inventory.json"
    inventory = {"schema_version": 1, "sources": [
        {"source_id": "SRC-TASK", "canonical_ref": "https://x/T-1", "relation": "task",
         "relevance": "relevant", "relevance_reason": "explicit required source",
         "assessment_ref": "sources/SRC-TASK/rev1/ticket.json", "discovered_from": None,
         "relation_evidence": None, "required": True, "status": "read", "revision": "r1",
         "content_hash": "x", "snapshot_ref": "sources/SRC-TASK/rev1/ticket.json",
         "fetched_at": "2026-01-01T00:00:00Z", "exclusion_or_error": None,
         "inspection_status": "read", "inspection_ref": "sources/SRC-TASK/rev1/ticket.json",
         "materials": {"comments": {"status": "read", "count": 0},
                      "attachments": {"status": "read", "count": 0, "items": []},
                      "external_media": {"status": "read", "count": 0, "items": []}},
         "mentioned_ticket_keys": []},
        {"source_id": "SRC-REF", "canonical_ref": "https://x/T-2", "relation": "referenced",
         "relevance": "relevant", "relevance_reason": "judge", "required": True, "status": "read",
         "revision": "r1", "content_hash": "y", "assessment_ref": "sources/SRC-REF/rev1/ticket.json",
         "snapshot_ref": "sources/SRC-REF/rev1/ticket.json", "discovered_from": "SRC-TASK",
         "relation_evidence": "mentioned in a comment about the diff mockup",
         "fetched_at": "2026-01-01T00:00:00Z", "exclusion_or_error": None,
         "inspection_status": "pending", "inspection_ref": None,
         "materials": {"comments": {"status": "read", "count": 0},
                      "attachments": {"status": "read", "count": 2, "items": [
                          {"attachment_id": "1", "filename": "diff-mockup.png",
                           "media_type": "image/png", "size": 1000, "original_ref": "u1",
                           "status": "read", "local_ref": "blobs/aaa", "content_hash": "aaa",
                           "analysis_status": "pending", "error": None},
                          {"attachment_id": "2", "filename": "unrelated-analytics-export.html",
                           "media_type": "text/html", "size": 400000, "original_ref": "u2",
                           "status": "read", "local_ref": "blobs/bbb", "content_hash": "bbb",
                           "analysis_status": "pending", "error": None}]},
                      "external_media": {"status": "read", "count": 0, "items": []}},
         "mentioned_ticket_keys": []}]}
    output.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return output


def attachment_table(state, name, question):
    # The mockup names the feature the story is about; the analytics export does not.
    return True if "mockup" in state["filename"] else False


def seed_diff_task(root: Path) -> Path:
    task_root = root / "qa-factory/artifacts/T-1"
    (task_root / "work").mkdir(parents=True)
    manifest = {"acceptance_criteria": [{"id": "AC-1", "text": "Added node has a green border"}],
               "implementation": {"repo": "app", "diff_path": "artifacts/T-1/work/impl-diff.txt"}}
    (task_root / "work/context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    diff_text = (
        "diff --git a/src/feature.py b/src/feature.py\n"
        "--- a/src/feature.py\n"
        "+++ b/src/feature.py\n"
        "@@ -1,2 +1,3 @@ def render():\n"
        " def render():\n"
        "+    draw_border(color=\"green\")\n"
        " \n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,2 @@\n"
        " # Title\n"
        "+Updated docs.\n")
    (task_root / "work/impl-diff.txt").write_text(diff_text, encoding="utf-8")
    return task_root


def diff_table(state, name, question):
    return ("AC-1", 0.9) if "green" in state["hunk"] else ("unrelated", 0.95)


def main() -> None:
    check_eq("the shipped discovery registry is valid", judge.registry_errors(), [])
    registry = judge.load_registry()
    for jid in ("disc_test_command", "disc_env_file", "disc_login_site", "disc_key_role",
               "disc_attachment_worth_opening", "disc_hunk_relates"):
        check(f"{jid} is registered with what it replaces", jid in registry and registry[jid].get("replaces"))

    real_post = judge._post
    os.environ["QA_JUDGE_DISC_TEST_KEY"] = "not-a-real-key"
    try:
        # --- judge_discovery: provider none is a pure no-op ---
        off = judge_discovery.choose("test_command", [{"command": "pytest", "evidence": "ci.yml:12"}],
                                     cfg=none_cfg())
        check_eq("provider none: test_command is off", off["status"], "off")
        check_eq("and chooses nothing", off["chosen"], None)

        # --- judge_discovery: choice among candidates ---
        candidates = [{"command": "pytest tests/unit", "evidence": "Makefile:3 (unit target)"},
                     {"command": "pytest tests/e2e --browser=chrome", "evidence": "ci.yml:40 (e2e job)"}]
        judge._post = fake_transport(lambda state, name, q: ("cand_0", 0.95))
        picked = judge_discovery.choose("test_command", candidates, level="unit", cfg=on_cfg())
        check_eq("a confident pick is chosen", picked["chosen"], candidates[0])
        check("the criteria sent describe the real candidates, not a placeholder",
              "Makefile:3" in json.dumps(judge._post.calls[-1]["questions"]["pick"]["criteria"]))

        judge._post = fake_transport(lambda state, name, q: ("cand_0", 0.3))
        unsure = judge_discovery.choose("env_file", [{"path": ".env", "keys": ["A"], "example": False},
                                                     {"path": ".env.local", "keys": ["A", "B"], "example": False}],
                                        cfg=on_cfg())
        check("a low-confidence pick stays undecided", unsure["chosen"] is None and not unsure["decided"])

        judge._post = fake_transport(lambda state, name, q: ("none", 0.95))
        no_fit = judge_discovery.choose("login_site", [{"where": "a.py:1", "kind": "harness_command",
                                                        "evidence": "run_login()"}], cfg=on_cfg())
        check("a confident `none` is reported as none, not as a chosen candidate",
              no_fit["none"] is True and no_fit["chosen"] is None)

        # --- judge_discovery: key_role, one small state per name ---
        judge._post = fake_transport(lambda state, name, q: ("token" if "TOKEN" in state["name"] else "unrelated", 0.95))
        roles = judge_discovery.classify_keys(["JIRA_TOKEN", "BUILD_NUMBER"], cfg=on_cfg())
        check_eq("each name is judged on its own", roles["results"]["JIRA_TOKEN"]["value"], "token")
        check_eq("and an unrelated name is not forced into a slot",
                 roles["results"]["BUILD_NUMBER"]["value"], "unrelated")
        check("each key_role request is its own tiny state (one name, not the whole list)",
              all(list(call["state"].keys()) == ["name"] for call in judge._post.calls[-2:]))

        # --- judge_sources: disc_attachment_worth_opening ---
        # Calibration on TP1-15045 (see the final report) rejected this judgment: 0 of 21
        # real attachments decided, and the story's own mockup scored BELOW several documents
        # of an unrelated ticket. It ships `enabled: false`, so the shipped registry must never
        # ask it - checked first, exactly as test_judge.py checks a rejected S1-S4 judgment.
        registry = judge.load_registry()
        check("disc_attachment_worth_opening shipped disabled: calibration on TP1-15045 never decided",
              registry["disc_attachment_worth_opening"].get("enabled") is False
              and registry["disc_attachment_worth_opening"].get("calibration"))

        root = harness.temp_project("qa-judge-disc-")
        try:
            harness.use_project(root)
            work = root / "qa-factory/artifacts/T-1/work"
            work.mkdir(parents=True)
            output = seed_attachment_inventory(work)

            judge._post = fake_transport(attachment_table)
            off = judge_sources.assess_attachments(output, "T-1", on_cfg())
            check_eq("the shipped (disabled) judgment is never asked", (off["status"], len(judge._post.calls)),
                     ("off", 0))

            # The mechanism itself (one small state per attachment, the inventory write for a
            # decided `false`, the evidence file) is exercised against a registry with this one
            # judgment force-enabled, exactly as it would run if a later calibration re-enables it.
            real_load_registry = judge.load_registry

            def enabled_registry():
                reg = dict(real_load_registry())
                reg["disc_attachment_worth_opening"] = {**reg["disc_attachment_worth_opening"], "enabled": True}
                return reg
            judge.load_registry = enabled_registry
            try:
                judge._post = fake_transport(attachment_table)
                shadow = judge_sources.assess_attachments(output, "T-1", shadow_cfg())
                check_eq("shadow mode checks both attachments", shadow["checked"], 2)
                check_eq("the judge's skip verdict is counted", shadow["skipped"], 1)
                check("but nothing is recorded in shadow mode",
                      not any(row["recorded"] for row in shadow["decisions"]))
                check_eq("the inventory is untouched in shadow mode",
                         load_inventory(output)["sources"][1]["materials"]["attachments"]["items"][1]["analysis_status"],
                         "pending")

                judge._post = fake_transport(attachment_table)
                recorded = judge_sources.assess_attachments(output, "T-1", on_cfg())
                check_eq("mode on records the one attachment the judge rejected", recorded["skipped"], 1)
                after = load_inventory(output)["sources"][1]["materials"]["attachments"]["items"]
                mockup, export = after[0], after[1]
                check_eq("the mockup (worth opening) is left pending for the scout",
                         mockup["analysis_status"], "pending")
                check_eq("the analytics export is recorded as a judge's skip, not as unreachable "
                         "and not silently dropped", export["analysis_status"], "skipped")
                check_in("its reason names the judge, so a person reviewing the gap sees why",
                         "skipped_by_judge", export["analysis_reason"])
                check("an evidence file backs the decision", (work / "judge-attachment-SRC-REF-2.json").is_file())

                again = judge_sources.assess_attachments(output, "T-1", on_cfg())
                check_eq("a re-run does not re-judge an attachment that already has a verdict", again["checked"], 1)
            finally:
                judge.load_registry = real_load_registry
        finally:
            harness.cleanup(root)

        # --- judge_diff: per-hunk screen against the AC list ---
        root2 = harness.temp_project("qa-judge-diff-")
        try:
            task_root = seed_diff_task(root2)
            judge._post = fake_transport(diff_table)
            report = judge_diff.run(task_root, "T-1", on_cfg())
            check_eq("both hunks were judged", report["hunks"], 2)
            check_eq("the README hunk is flagged unrelated", report["unrelated"], 1)
            by_path = {row["path"]: row for row in report["results"]}
            check_eq("the feature hunk is matched to its AC", by_path["src/feature.py"]["relates"], "AC-1")
            check_eq("the README hunk is matched to nothing an AC describes",
                     by_path["README.md"]["relates"], "unrelated")
            check("work/judge-diff.json is written for the scout to read",
                  (task_root / "work/judge-diff.json").is_file())

            off_report = judge_diff.run(task_root, "T-1", none_cfg())
            check_eq("provider none: judge_diff is a pure no-op", off_report["status"], "off")
        finally:
            harness.cleanup(root2)
    finally:
        judge._post = real_post
    harness.finish("test_judge_discovery")


if __name__ == "__main__":
    main()
