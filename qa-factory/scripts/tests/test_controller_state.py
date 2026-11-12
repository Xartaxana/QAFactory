#!/usr/bin/env python3
"""Managed lifecycle seams: ordered stages, exact Gate A, invalidation and S5 bypass."""
import hashlib
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project, s5_window_form
from story_run_common import accept_record
import controller as controller_module
from controller import Controller, validate_manual_runner_block
from event_store import StateConflict, content_hash
import hooklib
import stage_done
# The REAL reader of the combined refusal (C2-1), not a copy of its grammar.
from detector_verdict import split_items

# t-2113: since TR1-9 B3 the `code_only` refusal for a running row also names who holds the close and the release door
# (`_code_close_holders_words`). The first sentence is what these checks pin, so the clause is cut before comparing; its own words
# are pinned by the "names the holder and the release door" check of A-K11.
import re
HOLDER_CLAUSE = re.compile(r"(checkpoint active work before (?:code-only completion|revising scope|reopening Gate A|invalidation)) \(.*?`\)")

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if not ok else ""))
    CHECKS += 1
    FAILS += not ok


def record_stage_acceptance(root, stage, reviewed_dispatch=""):
    """X2-7: the name the ~25 callers use; the writer is `story_run_common.accept_record` (the one writer of the record)."""
    accept_record(root, stage, reviewed_dispatch)


def accept_stage(controller, root, stage):
    if stage == "S3" and not (root / "work/test-plan.json").exists():
        seed_plan(root)
    record_stage_acceptance(root, stage)
    evidence = root / f"{stage}.txt"
    evidence.write_text(stage, encoding="utf-8")
    if stage == "S5":
        author_ref = evidence_ref(root, "S5-author.txt", "author")
        # SC1-14 B1b: a desktop process runs S5 on the plan form, where no window is dispatched before a reviewed plan
        with s5_window_form(controller, root):
            controller.apply("dispatch", {"id": "dS5-author", "stage": "S5", "role": "qa-automator",
                             "scope": ["TC-1"], "input_hash": stage, "budget": {}, "known_paths": {},
                             "idempotency_key": "dispatch-S5-author"})
        controller.apply("accept", {"id": "dS5-author", "status": "accepted", "stage_complete": False,
                         "evidence_refs": [author_ref], "idempotency_key": "accept-S5-author"})
    dispatch = {"id": f"d{stage}", "stage": stage,
                "role": "qa-code-critic" if stage == "S5" else "qa-worker", "scope": ["TC-1"],
                "input_hash": stage, "budget": {}, "known_paths": {}, "idempotency_key": f"dispatch-{stage}"}
    controller.apply("dispatch", dispatch)
    receipt = {"id": dispatch["id"], "status": "accepted", "stage_complete": True,
               "evidence_refs": [{"path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
               "idempotency_key": f"accept-{stage}"}
    if stage == "S5":
        planned_hash = plan_obligation_hash(root)
        receipt["window"] = {"schema_version": 2, "input_hash": stage,
                             "author_dispatch_id": "dS5-author", "reviewer_dispatch_id": "dS5",
                             "required_quality_checks": [], "quality_receipts": [],
                             "scope_instances": {"TC-1": ["i"]},
                             "instances": [dict({"instance_id": "i", "outcome": "passed", "input_hash": stage,
                                            "review": {"verdict": "approved", "input_hash": stage},
                                            "change_disposition": "unchanged", "change_basis_ref": "manifest:TC-1",
                                            "evidence_refs": receipt["evidence_refs"]}, **v2_binding(obligation_hash=planned_hash))]}
    controller.apply("accept", receipt)
    if stage == "S5":
        # what a real S5 leaves once it is closed: the stage guard refuses S6-S8 without a readable manifest (C4-1)
        (root / "work").mkdir(exist_ok=True)
        (root / "work" / "automation-manifest.json").write_text('{"tests": [], "unresolved": []}', encoding="utf-8")


def evidence_ref(root, name, content="receipt"):
    path = root / name
    path.write_text(content, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def plan_obligation_hash(root):
    document = json.loads((root / "work/test-plan.json").read_text(encoding="utf-8"))
    rows = document["rows"] if isinstance(document, dict) else document
    return content_hash(rows[0]["coverage_obligations"][0])


def v2_binding(obligation_id="OB-TS-1", obligation_hash="planned-hash"):
    refs = [{"obligation_id": obligation_id, "obligation_hash": obligation_hash}]
    return {"schema_version": 2, "obligation_ids": [obligation_id],
            "obligation_refs": refs, "obligation_hash": content_hash(refs),
            "assertion_id": "tests/test_one.py:2", "defect_location": "src/one.py:1",
            "execution_fingerprint": "fixture-fingerprint"}


def seed_plan(root, rows=None):
    row = {"id": "TS-1", "impact": "low", "likelihood": "low", "confidence": "high",
           "risk_rationale": "bounded", "risk_source_refs": ["R-1"], "risk_policy_revision": "factory-starter-v1",
           "coverage_refs": ["R-1"], "unknowns": [], "verification_depth": "low", "required_scenarios": ["TC-1"],
           "test_level_rationale": "unit", "design_review_required": False, "bounded_reversible": True}
    selected = rows if rows is not None else [row]
    upgraded = []
    for source in selected:
        item = dict(source)
        item["schema_version"] = 2
        item["coverage_obligations"] = [{
            "obligation_id": "OB-" + item["id"], "requirement_refs": [{"ref": "R-1", "revision": "1"}],
            "behavior": "planned behavior", "oracle_source_ref": "requirements:R-1", "oracle_status": "resolved",
            "applicable_scenarios": [{"kind": "positive", "rationale": "main behavior"}],
            "observation_boundary": "result", "completion_condition": "operation completed",
            "coverage_links": [{"test_ref": "tests/test_one.py::test_one", "assertion_refs": ["tests/test_one.py:2"],
                                "proves": ["planned behavior"], "does_not_prove": [],
                                "assessment": "sufficient", "assessment_reason": "direct assertion"}],
            "decision": "reuse", "remaining_gap": "", "planned_check_refs": [],
            "execution_scope": "current_task",
            "sufficiency_review": {"author_dispatch_id": "strategy", "input_hash": "plan", "rationale": "direct"},
            "observation_contract": {"claim_kind": ["ordinary"],
                "oracle_ref": {"ref": "R-1", "revision": "1"},
                "surfaces": [{"id": "result", "boundary": "result", "status": "planned",
                              "assertion_ref": "tests/test_one.py:2"}],
                "controls": ["tests/test_one.py:2"], "completion_ref": "tests/test_one.py:2",
                "independent_expectations": [], "source_conflicts": []},
        }]
        item["coverage_contract_revision"] = "coverage-observation-v1"
        item["coverage_delta"] = {"baseline_kind": "initial", "initial_scope_rationale": "new task baseline",
            "entries": [{"obligation_id": item["coverage_obligations"][0]["obligation_id"],
                         "disposition": "reuse", "rationale": "existing direct assertion",
                         "existing_case_refs": ["TC-1@cv_1"]}],
            "counts": {"logical_cases_before": 1, "logical_cases_after": 1,
                       "executable_instances_before": 1, "executable_instances_after": 1},
            "planned_instance_ids": ["i"]}
        upgraded.append(item)
    path = root / "work" / "test-plan.json"; path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"rows": upgraded, "lifecycle_actions": []}), encoding="utf-8")
    state = root / "state"; state.mkdir(exist_ok=True)
    (state / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": "TC-1", "version": "cv_1"}]}), encoding="utf-8")


def bind_gate_a(root, decision):
    decision.update(Controller(root).gate_inputs())
    return decision


FIXTURE_ITEM_BLOCK = "no execution profile in"     # the `person_decides` item a fixture's rehearsal holds when no execution profile is onboarded


def add_override(root, stage, match, decision="accept - the person's word (fixture)"):
    """A recorded person's word, written the way `waiver.apply_stage_override` writes it (the fixtures' own writer; no journal line)."""
    import waiver
    path = root / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    waiver.apply_stage_override(pipeline, stage, match, decision, waiver.now_iso())
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def word_for_open_items(root, block=FIXTURE_ITEM_BLOCK):
    """RH1-6 (F-2): a gate A decision is recorded only over items the person has worded. A fixture whose rehearsal holds the item (no
    execution profile, no `waives`) gives it the person's word, so the decision it is really about still records. Never a bypass in
    the product: the check stays as it is."""
    add_override(root, "S5", block)


def accept_case_review_stage(controller, root, input_hash):
    for role, dispatch_id, complete in (("qa-case-designer", "case-author", False),
                                        ("qa-case-critic", "case-critic", True)):
        evidence = root / f"{dispatch_id}.txt"; evidence.write_text(role, encoding="utf-8")
        if complete:
            record_stage_acceptance(root, "S4", "case-author")
        controller.apply("dispatch", {"id": dispatch_id, "stage": "S4", "role": role,
                         "scope": ["TC-1"], "input_hash": input_hash, "budget": {},
                         "known_paths": {}, "idempotency_key": "dispatch-" + dispatch_id})
        controller.apply("accept", {"id": dispatch_id, "status": "accepted",
                         "stage_complete": complete,
                         "evidence_refs": [{"path": evidence.name,
                                            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                         "idempotency_key": "accept-" + dispatch_id})


def two_projects(root):
    """Two projects of the same package, each with one task `QA-1` - 'the copy' of t-329: A wrote the packet, B reads it."""
    out = []
    for name in ("copy-a", "copy-b"):
        project = (root / name).resolve()
        task = project / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True)
        mark_project(project)
        controller = Controller(task)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(task)},
                                        "idempotency_key": "init"})
        out.append((project, task, controller))
    return out


def portable_packets() -> None:
    """t-329 item 3 (B-249): a dispatch packet carries no absolute path of the machine and package that wrote it.
    `prepare` stores `{project_root}/...`, `{plugin_root}/...` and `{python}`; `dispatch` resolves them against the roots
    of the process that reads the packet, and never writes the packet back (FR-45); a packet of another package is
    refused with both fingerprints and the way on; a legacy absolute packet is read as before while its paths exist."""
    with tempfile.TemporaryDirectory(prefix="qa-portable-") as td:
        portable_packets_in(Path(td).resolve())


def portable_packets_in(root) -> None:
    import copy
    import contract
    (proj_a, task_a, ctl_a), (proj_b, task_b, ctl_b) = two_projects(root)
    plugin = Path(contract.__file__).resolve().parent.parent
    options = {"stage": "S0", "role": "qa-worker", "id": "S0-qa-worker-1"}
    packet = ctl_a.prepare(options)
    request = packet["dispatch_request"]
    known = request["known_paths"]
    dumped = json.dumps(known)
    check("T329-3 prepare: the project and plugin roots and the interpreter are tokens",
          (known["project_root"], known["plugin_root"], known["scripts_root"], known["python_executable"])
          == ("{project_root}", "{plugin_root}", "{plugin_root}/scripts", "{python}"), str(known)[:300])
    check("T329-3 prepare: the task's own paths are relative to the project, the entrypoints to the plugin",
          known["task_root"] == "{project_root}/qa-factory/artifacts/QA-1" and known["plan"].startswith("{project_root}/qa-factory/")
          and known["entrypoints"]["controller"] == "{plugin_root}/scripts/controller.py", str(known)[:400])
    check("T329-3 prepare: no absolute path of the writing machine is left in the packet",
          str(proj_a) not in dumped and str(proj_a).replace(chr(92), "/") not in dumped and str(plugin) not in dumped
          and str(plugin).replace(chr(92), "/") not in dumped, dumped[:400])
    check("T329-3 prepare: the fingerprint and version travel with it (the compare needs them)",
          len(known["package_fingerprint"]) == 64 and bool(known["package_version"]))
    check("T329-3 prepare: `resolved_paths` is this machine's own, absolute (what a person or a role reads)",
          packet["resolved_paths"]["project_root"] == str(proj_a) and packet["resolved_paths"]["task_root"] == str(task_a))

    # written under root A, read under root B: resolves, and the packet is not written back
    before = copy.deepcopy(request)
    bad_replay = dict(request, expected_revision=ctl_b.state()["revision"], idempotency_key="dispatch:b-1")
    sent = copy.deepcopy(bad_replay)
    ctl_b.apply("dispatch", bad_replay)
    stored = ctl_b.state()["dispatches"]["S0-qa-worker-1"]["known_paths"]
    check("T329-3 dispatch: a packet written under root A resolves under root B (project, task, plan, plugin, interpreter)",
          (stored["project_root"], stored["task_root"], stored["plan"], stored["plugin_root"], stored["python_executable"])
          == (str(proj_b), str(task_b), str(task_b / "work" / "test-plan.json"), str(plugin), sys.executable), str(stored)[:400])
    check("T329-3 dispatch: ...entrypoints and scripts included, and nothing of A is recorded",
          stored["entrypoints"]["controller"] == str(plugin / "scripts" / "controller.py") and stored["scripts_root"] == str(plugin / "scripts")
          and str(proj_a) not in json.dumps(stored), str(stored)[:400])
    check("T329-3 dispatch: the packet the caller holds was not written back (FR-45)", bad_replay == sent and request == before)
    check("T329-3 dispatch: and a resolved dispatch has no token left",
          not any(token in json.dumps(stored) for token in (contract.PROJECT_TOKEN, contract.PLUGIN_TOKEN, contract.PYTHON_TOKEN)))

    # a packet of another package is refused, naming both generations, and records nothing
    events = len(ctl_a.store.read())
    other = copy.deepcopy(request)
    other["id"], other["idempotency_key"], other["expected_revision"] = "S0-qa-worker-2", "dispatch:a-2", ctl_a.state()["revision"]
    other["known_paths"]["package_fingerprint"] = "0123456789ab" + "f" * 52
    other["known_paths"]["package_version"] = "0.0.1-old"
    try:
        ctl_a.apply("dispatch", other)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    now = known["package_fingerprint"][:12]
    check("T329-3 fingerprint mismatch: refused, naming both fingerprints (12 chars) and both versions",
          "0123456789ab" in refused and now in refused and "0.0.1-old" in refused and str(known["package_version"]) in refused
          and "f" * 20 not in refused, refused)
    check("T329-3 fingerprint mismatch: with the way on (prepare for this package, then dispatch) and 'nothing was dispatched'",
          "--operation prepare" in refused and "--operation dispatch" in refused and "Nothing was dispatched" in refused, refused)
    check("T329-3 fingerprint mismatch: no event was recorded", len(ctl_a.store.read()) == events)
    control = copy.deepcopy(other)
    control["known_paths"]["package_fingerprint"] = known["package_fingerprint"]
    ctl_a.apply("dispatch", control)
    check("T329-3 control: the same packet with this package's own fingerprint is dispatched silently",
          "S0-qa-worker-2" in ctl_a.state()["dispatches"])
    ctl_a.apply("checkpoint", {"id": "S0-qa-worker-2", "status": "paused", "reason": "x", "checkpoint": {"remaining": ["TC-1"]},
                               "counters": {"active_seconds": 0, "requests": 0, "output_tokens": 0, "repair_cycles": 0},
                               "idempotency_key": "cp-a-2"})        # one open dispatch at a time: free the stage
    absent = dict(copy.deepcopy(request), id="S0-qa-worker-3", idempotency_key="dispatch:a-3",
                  expected_revision=ctl_a.state()["revision"])
    absent["known_paths"].pop("package_fingerprint")
    ctl_a.apply("dispatch", absent)
    check("T329-3 edge: a packet with no fingerprint is not compared (an unknown is not a mismatch), its tokens still resolve",
          ctl_a.state()["dispatches"]["S0-qa-worker-3"]["known_paths"]["project_root"] == str(proj_a))

    # legacy: absolute paths that exist are read as before; paths that are gone are refused by name
    ctl_c = two_projects_extra(root)
    elsewhere = copy.deepcopy(packet["resolved_paths"])       # project A's absolute paths, every one of them on this disk
    legacy_request = {"id": "S0-qa-worker-1", "stage": "S0", "role": "qa-worker", "scope": ["TC-1"], "input_hash": "h",
                      "budget": {}, "known_paths": elsewhere, "idempotency_key": "dispatch:legacy",
                      "expected_revision": ctl_c.state()["revision"]}
    events = len(ctl_c.store.read())
    try:
        ctl_c.apply("dispatch", legacy_request)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("T335 A-n3 legacy: another project's absolute packet (its paths exist here too) is refused, naming both projects",
          str(proj_a) in refused and str(root / "copy-c") in refused and "another project or story" in refused, refused)
    check("T335 A-n3 legacy: with the way on (prepare) and 'Nothing was dispatched'; nothing recorded",
          "--operation prepare" in refused and "Nothing was dispatched" in refused and len(ctl_c.store.read()) == events, refused)
    legacy = copy.deepcopy(ctl_c.prepare({"stage": "S0"})["resolved_paths"])    # the SAME project's absolute packet
    legacy.pop("package_fingerprint"), legacy.pop("package_version")          # a legacy packet carries no stamp
    legacy_request["known_paths"], legacy_request["expected_revision"] = legacy, ctl_c.state()["revision"]
    ctl_c.apply("dispatch", legacy_request)
    kept = ctl_c.state()["dispatches"]["S0-qa-worker-1"]["known_paths"]
    check("T329-3 legacy: this project's packet with absolute paths that exist is recorded exactly as it came (T335 A-n3 control)",
          kept == legacy, str(kept)[:300])
    gone = {"project_root": str(root / "no-such-copy"), "plugin_root": str(root / "no-such-package"),
            "python_executable": str(root / "no-python.exe"), "root": str(root)}
    ctl_c.apply("checkpoint", {"id": "S0-qa-worker-1", "status": "paused", "reason": "x", "checkpoint": {"remaining": ["TC-1"]},
                               "counters": {"active_seconds": 0, "requests": 0, "output_tokens": 0, "repair_cycles": 0},
                               "idempotency_key": "cp-legacy"})
    events = len(ctl_c.store.read())
    try:
        ctl_c.apply("dispatch", dict(legacy_request, id="S0-qa-worker-9", idempotency_key="dispatch:gone", known_paths=gone,
                                     expected_revision=ctl_c.state()["revision"]))
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("T329-3 legacy: absolute paths that are not on this machine are refused, each named, with the way on",
          str(root / "no-such-copy") in refused and str(root / "no-such-package") in refused and "no-python.exe" in refused
          and "--operation prepare" in refused and "Nothing was dispatched" in refused, refused)
    check("T329-3 legacy: and nothing was recorded", len(ctl_c.store.read()) == events)
    ctl_c.apply("dispatch", dict(legacy_request, id="S0-qa-worker-9", idempotency_key="dispatch:ok",
                                 known_paths={"root": str(root)}, expected_revision=ctl_c.state()["revision"]))
    check("T329-3 legacy control: a packet with no run path at all (`{root}` only) is dispatched as before",
          "S0-qa-worker-9" in ctl_c.state()["dispatches"])

    # the retry packet of a stopped dispatch is portable, made against the roots THE RECORD names
    old = {"project_root": "D:/ws/testproject1-dev-fresh\\testproject1-sdk-cmp2\\test-harness",
           "plugin_root": "C:\\Users\\dev4\\AppData\\Local\\Temp\\cmp2-pkg\\qa-factory",
           "scripts_root": "C:\\Users\\dev4\\AppData\\Local\\Temp\\cmp2-pkg\\qa-factory\\scripts",
           "python_executable": "C:\\Python312\\python.exe",
           "task_root": "D:/ws/testproject1-dev-fresh\\testproject1-sdk-cmp2\\test-harness\\qa-factory\\artifacts\\TP1-15045",
           "repository_roots": {"testproject1-backend": "D:/ws/testproject1-dev-fresh\\testproject1"},
           "entrypoints": {"controller": "C:\\Users\\dev4\\AppData\\Local\\Temp\\cmp2-pkg\\qa-factory\\scripts\\controller.py"},
           "package_version": "0.7.19", "package_fingerprint": "6d0e2ceae70ec5e0dfd2d59c3e07a77411cacf217a0fb5302f4b4b60fd0093ea"}
    record = {"id": "S5-qa-code-critic-5", "stage": "S5", "role": "qa-code-critic", "input_hash": "h", "scope": ["TC-1"],
              "known_paths": copy.deepcopy(old), "budget": {}, "status": "blocked", "checkpoint": {"remaining": ["x"]}}
    for label, builder in (("retry", Controller._retry_packet), ("relaunch", Controller._relaunch_packet)):
        made = builder({"revision": 3, "dispatches": {record["id"]: record}}, record)["known_paths"]
        check(f"T329-3 {label} packet: project, plugin, interpreter and entrypoints are tokens; the other repository stays",
              (made["project_root"], made["task_root"], made["scripts_root"], made["python_executable"],
               made["entrypoints"]["controller"], made["repository_roots"]["testproject1-backend"])
              == ("{project_root}", "{project_root}/qa-factory/artifacts/TP1-15045", "{plugin_root}/scripts", "{python}",
                  "{plugin_root}/scripts/controller.py", old["repository_roots"]["testproject1-backend"]), str(made)[:400])
        check(f"T335 A1 {label} packet: stamped with THIS package's fingerprint and version, not the record's (the check compares "
              "the package that BUILT the packet with the one that dispatches it)",
              (made["package_fingerprint"], made["package_version"]) == (known["package_fingerprint"], known["package_version"])
              and made["package_fingerprint"] != old["package_fingerprint"], str(made)[-200:])
        check(f"T329-3 {label} packet: the stopped record itself is not touched", record["known_paths"] == old)
    bare = dict(record, known_paths={"root": "/x"})
    check("T329-3 retry edge: a record with no roots and no run path comes back as it was (T335 A1: a record with NO stamp gets "
          "none - it was never compared, A-n3's project check stands for it)",
          Controller._retry_packet({"revision": 1}, bare)["known_paths"] == {"root": "/x"}
          and Controller._relaunch_packet({"revision": 1}, bare)["known_paths"] == {"root": "/x"}
          and Controller._retry_packet({"revision": 1}, dict(record, known_paths={}))["known_paths"] == {})
    check("T335 A1 edge: a stamped record whose own stamp is replaced keeps every other key and its position-independent paths",
          {k: v for k, v in Controller._retry_packet({"revision": 1}, record)["known_paths"].items()
           if k not in ("package_fingerprint", "package_version")} ==
          {k: v for k, v in contract.portable_known_paths(old, old["project_root"], old["plugin_root"]).items()
           if k not in ("package_fingerprint", "package_version")})
    check("T335 A1 control: the stamp the builders use is the one `prepare` prints (one definition, runtime_paths)",
          Controller._package_stamp() == {"package_fingerprint": known["package_fingerprint"], "package_version": known["package_version"]})

    # the pure functions: the edges the controller does not reach
    rt = contract.portable_known_paths({"project_root": "C:/p", "plugin_root": "C:/pkg", "python_executable": "C:/py/python.exe",
                                        "x": "c:\\P\\sub\\f.txt", "outside": "D:/other/repo", "same-prefix": "C:/pXtra/f",
                                        "package_version": "1.2", "n": 5, "nested": {"a": "C:/pkg/s/a.py", "b": 7}}, "C:/p", "C:/pkg")
    check_pure = {"project_root": "{project_root}", "plugin_root": "{plugin_root}", "python_executable": "{python}",
                  "same-prefix": "C:/pXtra/f", "outside": "D:/other/repo", "package_version": "1.2", "n": 5,
                  "nested": {"a": "{plugin_root}/s/a.py", "b": 7}}
    check("T329-3 pure: the roots, the interpreter, a nested map; a sibling folder with the same prefix, another drive, a version "
          "and a number are not touched", all(rt[k] == v for k, v in check_pure.items()), str(rt))
    check("T329-3 pure: case and slash spelling of the root do not matter on this OS (c:\\P\\sub\\f.txt under C:/p)",
          rt["x"] == "{project_root}/sub/f.txt" or os.name != "nt", rt["x"])
    back = contract.resolve_known_paths(rt, str(proj_b), str(plugin), sys.executable)
    check("T329-3 pure: resolving the tokens gives this machine's paths, and an absolute path / a version / a number stay",
          (back["project_root"], back["python_executable"], back["nested"]["a"], back["outside"], back["n"])
          == (str(proj_b), sys.executable, str(plugin / "s" / "a.py"), "D:/other/repo", 5), str(back))
    check("T329-3 pure: not a dict is returned as it is, an unknown token is not touched",
          (contract.portable_known_paths([1], "a", "b"), contract.resolve_known_paths("x", "a", "b", "p"),
           contract.resolve_known_paths({"k": "{nope}/x"}, "a", "b", "p")) == ([1], "x", {"k": "{nope}/x"}))


def two_projects_extra(root):
    """One more project with a story to dispatch into (the legacy cases)."""
    project = (root / "copy-c").resolve()
    task = project / "qa-factory" / "artifacts" / "QA-1"
    task.mkdir(parents=True)
    mark_project(project)
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(task)},
                                    "idempotency_key": "init"})
    return controller


def a_respelled_dispatch_is_recorded_and_keyed_as_the_approved_case() -> None:
    """CX1-11 M-3: the gate admits `session-feedback/TC-001` (I1) and RECORDS the approved key, so every reader of a
    dispatch's scope (the window and budget keys here; S6 coverage, `invalidate` and the ticket rework read the same
    field) sees one spelling of one case."""
    import test_controller_rework_scope as RS
    from controller import budget_scope, window_key
    from harness import cleanup
    root, parent, c = RS.keyed_story()
    try:
        for name, scope in (("S5-a", ["session-feedback/TC-001", "TC-002"]), ("S5-b", ["TC-001", "TC-002"])):
            with s5_window_form(c, root):
                c.apply("dispatch", dict(RS.window(scope, name), idempotency_key=name))
            c.apply("accept", {"id": name, "status": "accepted", "stage_complete": False,
                               "evidence_refs": [evidence_ref(root, name + ".txt")], "idempotency_key": name + "-ok"})
        first, second = (c.state()["dispatches"][name] for name in ("S5-a", "S5-b"))
        check("the recorded scope is the approved keys, not the words of the request", first["scope"] == ["TC-001", "TC-002"],
              str(first["scope"]))
        check("a respelled window shares its window key and its budget scope with the canonical one",
              window_key(first) == window_key(second) and budget_scope(first) == budget_scope(second))
    finally:
        cleanup(parent)


def rework_is_built_by_the_package_that_dispatches_it() -> None:
    """t-335 A1 (critic t-334): `build_rework_request` copied the stored record's `package_fingerprint`, so after ANY
    package change `apply("dispatch")` refused every rework (the record names the package of the OLD dispatch), and the
    door the refusal names - `prepare` - cannot make a rework. The packet now carries the fingerprint of the package that
    BUILDS it. Both directions: a rework built under package Y over a record made under X is dispatched; a rework
    printed under X and dispatched under Y is refused, naming both. Packages X / Y are the real `resolve_runtime` with
    its fingerprint swapped (one definition, the one `prepare`, the compare and the builders all read)."""
    import runtime_paths
    real = runtime_paths.resolve_runtime

    def as_package(tag, version):
        def resolve(*args, **kwargs):
            return dict(real(*args, **kwargs), package_fingerprint=tag, package_version=version)
        return resolve

    with tempfile.TemporaryDirectory(prefix="qa-rework-") as td:
        root = Path(td).resolve()
        ctl = two_projects_extra(root)
        task = ctl.store.root
        runtime_paths.resolve_runtime = as_package("a" * 64, "0.7.19")
        try:
            sent = ctl.prepare({"stage": "S0", "role": "qa-worker", "id": "S0-qa-worker-1"})["dispatch_request"]
            ctl.apply("dispatch", sent)
            evidence = task / "S0.txt"
            evidence.write_text("S0", encoding="utf-8")
            ctl.apply("accept", {"id": "S0-qa-worker-1", "status": "accepted", "stage_complete": True,
                                 "evidence_refs": [{"path": "S0.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                                 "idempotency_key": "accept-S0-1"})
            record = ctl.state()["dispatches"]["S0-qa-worker-1"]["known_paths"]
            built_under_x = ctl.build_rework_request("S0", "qa-worker", [], "repair the first answer")
        finally:
            runtime_paths.resolve_runtime = real
        check("T335 A1 fixture: the accepted record names package X, and the rework printed under X is stamped X",
              record["package_fingerprint"] == "a" * 64 and built_under_x["known_paths"]["package_fingerprint"] == "a" * 64,
              str(record.get("package_fingerprint")))
        events = len(ctl.store.read())
        try:
            ctl.apply("dispatch", dict(built_under_x))
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        now = real(task, None)["package_fingerprint"]
        check("T335 A1 direction 1: a rework PRINTED under X and dispatched under Y is refused, naming both packages",
              "aaaaaaaaaaaa" in refused and now[:12] in refused and "0.7.19" in refused and "--operation prepare" in refused, refused)
        check("T335 A1 direction 1: ...and nothing was recorded", len(ctl.store.read()) == events)
        made = ctl.build_rework_request("S0", "qa-worker", [], "repair the first answer", cause=None)
        check("T335 A1 direction 2: a rework built under Y over a record made under X carries Y's stamp and portable paths",
              made["known_paths"]["package_fingerprint"] == now and made["known_paths"]["project_root"] == "{project_root}"
              and made["known_paths"]["task_root"].startswith("{project_root}/"), str(made["known_paths"])[:300])
        ctl.apply("dispatch", dict(made))
        stored = ctl.state()["dispatches"][made["id"]]
        check("T335 A1 direction 2: ...and it is DISPATCHED, resolved against this project, rework_of kept",
              stored["known_paths"]["project_root"] == str(root / "copy-c") and stored.get("rework_of") == "S0-qa-worker-1"
              and stored["known_paths"]["package_fingerprint"] == now, str(stored)[:300])
        check("T335 A1 control: the record of the OLD dispatch was not rewritten",
              ctl.state()["dispatches"]["S0-qa-worker-1"]["known_paths"]["package_fingerprint"] == "a" * 64)


def s5_window_is_refused_in_one_list():
    """K1 (cmp3): the independent defects of an S5 window are ONE refusal, in tiers (t-720 §4.2)."""
    with tempfile.TemporaryDirectory(prefix="qa-s5-list-") as td:
        root = mark_project(Path(td))
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})
        for number in range(5):
            accept_stage(c, root, f"S{number}")
        seed_plan(root)
        c.apply("decision", bind_gate_a(root, {"id": "A", "gate": "A", "action": "approve", "status": "approved",
                                               "authorization_source": "human", "source_revision": "r",
                                               "scope": ["TC-1"], "input_revision": "r", "idempotency_key": "A"}))
        evidence = root / "s5.txt"
        evidence.write_text("ok", encoding="utf-8")
        with s5_window_form(c, root):
            c.apply("dispatch", {"id": "s5", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                 "input_hash": "s5", "budget": {}, "known_paths": {}, "idempotency_key": "s5"})
        c.apply("accept", {"id": "s5", "status": "accepted", "stage_complete": False,
                           "evidence_refs": [evidence_ref(root, "s5-author.txt")], "idempotency_key": "s5-author"})
        c.apply("dispatch", {"id": "s5critic", "stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"],
                             "input_hash": "s5", "budget": {}, "known_paths": {}, "idempotency_key": "s5critic"})
        ref = {"path": "s5.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
        planned = plan_obligation_hash(root)

        def instance(name="i", **over):
            built = dict({"instance_id": name, "outcome": "passed", "input_hash": "s5",
                          "review": {"verdict": "approved", "input_hash": "s5"}, "change_disposition": "unchanged",
                          "change_basis_ref": "manifest:TC-1", "evidence_refs": [ref]},
                         **v2_binding(obligation_hash=planned))
            built.update(over)
            return built

        def window(**over):
            return dict({"schema_version": 2, "input_hash": "s5", "author_dispatch_id": "s5",
                         "reviewer_dispatch_id": "s5critic", "required_quality_checks": [],
                         "quality_receipts": [], "scope_instances": {"TC-1": ["i"]},
                         "instances": [instance()]}, **over)

        counter = [0]

        def refused(win, **receipt):
            counter[0] += 1
            body = {"id": "s5critic", "status": "accepted", "stage_complete": True, "window": win,
                    "evidence_refs": [ref], "idempotency_key": f"s5-try-{counter[0]}"}
            body.update(receipt)
            try:
                c.apply("accept", body)
            except (StateConflict, ValueError) as exc:
                return type(exc), str(exc)
            return None, ""

        # three independent defects of the fields: the map's keys, the input hash, the quality checks
        # HF4-10 (t-1480): only a check some factory script produces a receipt for is demanded, so the data names `lint`
        import window_record as _wr
        prod_file = root / "quality-producers.json"
        prod_file.write_text(json.dumps({"schema_version": 1, "producers": {"lint": "lint_receipt.py"}, "why": {}}),
                             encoding="utf-8")
        saved_file, _wr.QUALITY_PRODUCERS_FILE = _wr.QUALITY_PRODUCERS_FILE, prod_file
        try:
            cls, text = refused(window(scope_instances={"TC-9": ["i"]}, input_hash="other",
                                       required_quality_checks=["lint"]))
        finally:
            _wr.QUALITY_PRODUCERS_FILE = saved_file
        items = split_items(text) or []
        check("three independent defects of one window are ONE refusal, one line each",
              len(items) >= 3 and text.startswith(f"{len(items)} problems - the request"), text[:400])
        for needle in ("exact scope_instances map", "input hash does not match", "omit project quality checks"):
            check(f"...and the list carries `{needle}`", any(needle in item for item in items), text[:400])
        check("...with the gap checks named as not run",
              bool(items) and "gap checks" in items[-1] and "did not run" in items[-1], text[-200:])
        check("...in the class of the first problem (the request's, ValueError)", cls is ValueError, str(cls))
        # a broken SHAPE stops at tier 2 with the whole shape list and says what did not run
        cls, text = refused(window(scope_instances="TC-1", input_hash="other"))
        check("a window of the wrong shape is refused as a shape, naming the checks that did not run",
              "S5 window record is incomplete" in text and "field checks below did not run" in text
              and "input hash" not in text and split_items(text) is None, text[:400])
        # no window object: the sentence, and the phrase that the rest did not run
        cls, text = refused(None)
        check("no window record: one sentence in the story's class, the other checks named as not run",
              cls is StateConflict and "needs a window acceptance record" in text
              and "other window checks did not run" in text and split_items(text) is None, text[:300])
        # tier 4 runs only on a clean tier 3: an input hash that does not match and a receipt without an id
        cls, text = refused(window(input_hash="other", quality_receipts=[{}]))
        check("a bad input hash with `quality_receipts: [{}]` is a clean refusal, not a KeyError",
              cls is not None and "input hash does not match" in text and "gap checks" in text
              and "did not run" in text, f"{cls} {text[:300]}")
        # one instance: the first failure stops THAT instance; two instances are collected and merged
        two = window(scope_instances={"TC-1": ["i", "j"]},
                     instances=[instance("i", obligation_hash="x"), instance("j", obligation_hash="x")])
        cls, text = refused(two)
        check("the same defect on two instances is one line with its count",
              "instance obligation_hash must bind exact obligation_refs (×2)" in text and split_items(text) is None,
              text[:300])
        broken = instance("i", execution_fingerprint="", obligation_hash="x")
        cls, text = refused(window(instances=[broken]))
        check("inside ONE instance the first failure stops it (the hash behind it is not judged)",
              "requires execution_fingerprint" in text and "obligation_hash must bind" not in text, text[:300])
        # schema_version != 2 on a coverage v2 story: the v2 checks name themselves as skipped
        cls, text = refused(window(schema_version=1, input_hash="other"))
        check("a window that is not schema_version 2 names the coverage v2 checks it skipped",
              "coverage v2 checks did not run" in text, text[:300])
        # a helper that refuses ends the tier with its own text as the LAST item
        original = c._plan_document

        def unreadable():
            raise StateConflict("structured test plan is unreadable")
        c._plan_document = unreadable
        try:
            cls, text = refused(window(scope_instances={"TC-9": ["i"]}, input_hash="other"))
        finally:
            c._plan_document = original
        items = split_items(text) or []
        check("a tier-3 helper's StateConflict is the last item, with the checks after it named as not run",
              len(items) >= 2 and "structured test plan is unreadable" in items[-1]
              and "checks after it did not run" in items[-1] and "exact scope_instances map" in items[0]
              and not any("input hash" in item for item in items), text[:400])
        # a mixed list is raised as the FIRST problem's class
        cls, text = refused(window(scope_instances={"TC-9": ["i"]}, author_dispatch_id="nobody"))
        check("a mixed list is raised as the class of its first problem (ValueError before StateConflict)",
              cls is ValueError and "distinct accepted author" in text, f"{cls} {text[:300]}")
        # the code critic's receipts (tier 3a) are collected in EVERY tier, first in the list (t-791, M1/M2):
        # an unreceipted critic window with a clean record is refused - the mutation `problems = list(review)`
        # -> `[]` in the controller must die HERE (it accepted such a window silently before this test).
        from role_cli import REPAIR_MARKER
        manifest_path = root / "work" / "automation-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"schema_version": 2, "tests": []}), encoding="utf-8")
        findings = root / "critic-findings.md"
        findings.write_text("# findings", encoding="utf-8")
        findings_ref = {"path": "critic-findings.md", "sha256": hashlib.sha256(findings.read_bytes()).hexdigest()}
        try:
            cls, text = refused(window())
            check("an unreceipted critic window with a clean record is refused with the receipts",
                  cls is StateConflict and "not receipted" in text and "no findings file" in text
                  and REPAIR_MARKER in text and split_items(text) is None, f"{cls} {text[:400]}")
            cls, text = refused(window(input_hash="other"))
            items = split_items(text) or []
            check("a receipts problem AND a window defect are ONE list, the receipts first",
                  len(items) >= 2 and "not receipted" in items[0]
                  and any("input hash does not match" in item for item in items[1:]), text[:500])
            check("...in the class of the first item (the receipts', StateConflict)", cls is StateConflict, str(cls))
            cls, text = refused(window(scope_instances="TC-1", input_hash="other"))
            items = split_items(text) or []
            check("tier 2 (a window of the wrong shape) carries the receipts in front of the shape item",
                  len(items) == 2 and "not receipted" in items[0] and "S5 window record is incomplete" in items[1]
                  and "field checks below did not run" in items[1], text[:500])
            cls, text = refused(None)
            items = split_items(text) or []
            check("tier 1 (no window record) carries the receipts in front of the record item",
                  len(items) == 2 and "not receipted" in items[0] and "needs a window acceptance record" in items[1]
                  and "other window checks did not run" in items[1], text[:500])
            cls, text = refused(window(input_hash="other"), evidence_refs=[ref, findings_ref])
            check("a receipted window adds no receipts line: only the window's own defect is refused",
                  "not receipted" not in text and "input hash does not match" in text, text[:400])
        finally:
            manifest_path.unlink()
        # the control: the same window, whole, is accepted; nothing above recorded anything
        cls, text = refused(window())
        check("the control: the window with none of those defects is accepted", cls is None, f"{cls} {text[:200]}")


def a_case_with_no_instance_needs_the_manifest_row():
    """t-721 C2-3 (T8): a window that lists NO instance for a case (TC-2) is accepted only when the manifest carries that
    case as `handed_to_person` AND the completion names it. The pair alone, with no manifest row, is refused: the refusal
    says the manifest does not carry the case (the `stray` check of the S5 completion, tier 3)."""
    import test_fixes_13797 as FIX
    with tempfile.TemporaryDirectory(prefix="qa-s5-empty-") as td:
        root = Path(td)
        controller, window = FIX.v2_story_at_s5(root)
        FIX.write_json(root / "work/automation-manifest.json", {
            "tests": [{"instance_id": "i-1", "case": "TC-1", "covers": ["TC-1"], "status": "green",
                       "test": "tests/test_one.py::test_one"}], "unresolved": []})
        pair = {"unresolved": ["TC-2"], "reason": "handed_to_person; full list: work/windows/s5-critic.json; "
                                                  "handed_to_person:TC-2"}
        text = FIX.refused(controller.apply, "accept", FIX.completion(window, "no-row", **pair))
        check("T8: a window with TC-2 listing no instance and a pair, but no manifest row for TC-2 - refused",
              "TC-2 lists no instance" in text, text[:300])
        check("T8: and the refusal says the manifest does not carry it", "(it does not carry TC-2)" in text, text[:400])
        FIX.manifest_with(root, "handed_to_person")
        text = FIX.refused(controller.apply, "accept", FIX.completion(window, "with-row", **pair))
        check("T8: with the manifest row (handed_to_person) the same pair is accepted", text == "", text[:300])
        state = controller.state()
        check("T8: S5 completed on the critic's acceptance",
              (state["stages"]["S5"]["status"], state["dispatches"]["s5-critic"]["status"]) == ("completed", "accepted"))


def an_empty_case_answers_to_the_scope_key_its_manifest_cell_gives():
    """t-845 C3-12 (finding 20261015, critic t-826 F12): the `stray` check of an S5 window compares the window's EXACT scope
    keys with the manifest cell through `contract.scope_keys`, not through the bare ids of `case_ids` (which turned
    `speakers/TC-009` into `TC-009` and refused every area-keyed case with no instance, row or no row). Tier 3 is called
    directly (`_s5_collect`), because the v2 story fixture is bare-keyed; only the "lists no instance" item is read."""
    def row(case, reason="handed_to_person"):
        return {"case": case, "reason": reason, "detail": "by hand"}
    pair = {"unresolved": ["x"], "reason": "handed_to_person; full list: work/windows/s5-critic.json"}
    with tempfile.TemporaryDirectory(prefix="qa-s5-scopekeys-") as td:
        root = Path(td)
        controller = Controller(root)

        def put(rows):
            (root / "work").mkdir(exist_ok=True)
            (root / "work/automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": rows}), encoding="utf-8")

        def empty_item(keys, rows, completion=pair):
            put(rows)
            problems = []
            window = {"scope_instances": {key: [] for key in keys}, "instances": []}
            controller._s5_collect({"scope": list(keys), "input_hash": "h"}, dict(completion), {}, window, problems)
            return " | ".join(text for _cls, text in problems if "lists no instance" in text)
        check("C3-12 (a): window {speakers/TC-009: []} + a manifest row speakers/TC-009 handed_to_person + the pair - accepted",
              empty_item(["speakers/TC-009"], [row("speakers/TC-009")]) == "")
        text = empty_item(["speakers/TC-009"], [])
        check("C3-12 (b): the same window with no row - refused: it does not carry speakers/TC-009",
              "(it does not carry speakers/TC-009)" in text, text[:300])
        check("C3-12 (c): a compound row TC-001/TC-002 + window {TC-001: [], TC-002: []} - accepted (today's behavior)",
              empty_item(["TC-001", "TC-002"], [row("TC-001/TC-002")]) == "")
        check("C3-12 (c): ...and the exact compound cell is a key of its own", empty_item(["TC-001/TC-002"], [row("TC-001/TC-002")]) == "")
        text = empty_item(["speakers/TC-009", "speakers/TC-010"], [row("speakers/TC-009")])
        check("C3-12: of two area-keyed cases only the one the manifest lacks is stray",
              "(it does not carry speakers/TC-010)" in text and "carry speakers/TC-009" not in text, text[:300])
        check("C3-12: an area-keyed row with the reason `impossible` answers too",
              empty_item(["speakers/TC-009"], [row("speakers/TC-009", "impossible")]) == "")
        text = empty_item(["speakers/TC-009"], [row("speakers/TC-009", "could_not_judge")])
        check("C3-12: a row with another reason carries nothing (as before)", "(it does not carry speakers/TC-009)" in text, text[:300])
        text = empty_item(["speakers/TC-009"], [row("speakers/TC-009")], {})
        check("C3-12: the pair is still owed - an answered key with no `unresolved`/`reason` is refused for THAT",
              "lists no instance" in text and "(it does not carry" not in text, text[:300])
        # edges named by the spec: no cross-match between a bare cell and an area cell; a trailing slash; a duplicate cell
        put([row("TC-009", "impossible"), row("speakers/TC-009")])
        check("C3-12 edge: TC-009 and speakers/TC-009 in one manifest - two rows, two keys, each with its own reason",
              controller._cases_without_instances() == {"TC-009": "impossible", "speakers/TC-009": "handed_to_person"},
              str(controller._cases_without_instances()))
        check("C3-12 edge: a bare row does not answer to the area key", "(it does not carry speakers/TC-009)" in
              empty_item(["speakers/TC-009"], [row("TC-009")]))
        check("C3-12 edge: an area row does not answer to the bare key", "(it does not carry TC-009)" in
              empty_item(["TC-009"], [row("speakers/TC-009")]))
        put([row("speakers/")])
        check("C3-12 edge: a cell with a trailing slash is its exact text only - no id part",
              controller._cases_without_instances() == {"speakers/": "handed_to_person"},
              str(controller._cases_without_instances()))
        put([row("speakers/TC-009", "impossible"), row("speakers/TC-009", "handed_to_person")])
        check("C3-12 edge: a duplicate exact cell - the LATER row's reason wins",
              controller._cases_without_instances() == {"speakers/TC-009": "handed_to_person"},
              str(controller._cases_without_instances()))
        put([row("speakers/TC-009", "handed_to_person"), row("speakers/TC-009", "impossible")])
        check("C3-12 edge: ...in either order", controller._cases_without_instances() == {"speakers/TC-009": "impossible"},
              str(controller._cases_without_instances()))
        put([row("speakers/TC-009", "handed_to_person"), row("speakers/TC-009", "could_not_judge")])
        check("C3-12 edge (t-853 F4): a LATER row with a non-no-instance reason does not override - the earlier row stands",
              controller._cases_without_instances() == {"speakers/TC-009": "handed_to_person"},
              str(controller._cases_without_instances()))
        (root / "work/automation-manifest.json").unlink()
        check("C3-12 edge: no manifest at all - the map is empty, never a refusal", controller._cases_without_instances() == {})


def s1_reacceptance_is_judged_by_one_summary():
    """t-721 C2-3 (T9b, F-7): S1 is already `completed`; its source carries the whole-source acceptance an older recorder
    wrote (`legacy`), and one more S1 dispatch is accepted. ONE summary decides - `source_inputs`, with `s1_closed` - so the
    old meaning stands (nothing blocks again) and no "passed by a person's recorded word" line is printed (the second
    `completeness(inventory)` read the same inventory with `s1_closed=False` and could block it)."""
    import contextlib
    import io
    import test_gap_points as GAP
    with tempfile.TemporaryDirectory(prefix="qa-s1-again-") as td:
        root = Path(td)
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})
        for number in range(2):
            accept_stage(c, root, f"S{number}")
        GAP.controller_inventory(root)           # after S1 closed: the legacy acceptance, one unavailable merge request
        check("T9b: S1 is completed before the inventory appears", c.state()["stages"]["S1"]["status"] == "completed")
        (root / "S1-again.txt").write_text("again", encoding="utf-8")
        ref = {"path": "S1-again.txt", "sha256": hashlib.sha256(b"again").hexdigest()}
        c.apply("dispatch", {"id": "S1-again", "stage": "S1", "role": "qa-worker", "scope": ["TC-1"], "input_hash": "again",
                             "budget": {}, "known_paths": {}, "idempotency_key": "d-again"})
        refusal = ""
        try:
            c.apply("accept", {"id": "S1-again", "status": "accepted", "stage_complete": True, "evidence_refs": [ref],
                               "idempotency_key": "a-again-bare"})
        except StateConflict as exc:
            refusal = str(exc)
        check("T9b: the source is not complete, so a completion without the gap handoff is refused for THAT (one summary)",
              "S1 unavailable sources require explicit unresolved gap handoff" in refusal, refusal[:300])
        said, second = io.StringIO(), ""
        with contextlib.redirect_stdout(said):
            try:
                c.apply("accept", {"id": "S1-again", "status": "accepted", "stage_complete": True, "evidence_refs": [ref],
                                   "unresolved": ["SRC-c1"], "reason": "the merge request is unavailable",
                                   "idempotency_key": "a-again"})
            except StateConflict as exc:
                second = str(exc)
        check("T9b: with the handoff the re-acceptance goes through under the old meaning (no second summary to block it)",
              second == "" and c.state()["dispatches"]["S1-again"]["status"] == "accepted", second[:300])
        check("T9b: and no 'passed by a person's recorded word' line is printed", "recorded word" not in said.getvalue(),
              said.getvalue()[:300])


# C3-11: what each chain refused ALONE at ed8cddf2, before `_raise_all` took it over: the class and the exact
# text, one per defect in the order of the case's flags. A chain with one failing item must still raise this.
CHAIN_BEFORE = {
    'known_paths keys': [
        ['ValueError', 'known_paths.root must be a nonempty path string'],
        ['ValueError', 'known_paths.entrypoints must map names to path strings'],
    ],
    'known_paths and agent_id': [
        ['ValueError', 'known_paths.root must be a nonempty path string'],
        ['ValueError', "agent_id is the host's own id of the launched agent, as a nonempty string; omit it when the host reported none"],
    ],
    'initialize fields': [
        ['ValueError', 'source_revision and known_paths required'],
        ['ValueError', 'unsupported coverage contract version'],
        ['ValueError', 'initialize requires new or legacy plan contract mode'],
    ],
    'revise_plan fields': [
        ['ValueError', 'plan revision requires scope, content revision and reason'],
        ['ValueError', 'plan revision contains unsupported state fields'],
    ],
    'semantic_reopen state': [
        ['StateConflict', 'checkpoint active work before reopening Gate A'],
        ['StateConflict', 'semantic reopen requires current approved Gate A'],
    ],
    'telemetry state': [
        ['StateConflict', 'orchestrator telemetry requires current lease'],
        ['StateConflict', 'host cannot provide verified orchestrator telemetry'],
    ],
    'telemetry fields': [
        ['ValueError', 'orchestrator telemetry requires a nonnegative model request count'],
        ['ValueError', 'context_percent must be 0..100 or unknown'],
    ],
    'dispatch id and case review': [
        ['StateConflict', 'resume existing dispatch; do not replace its checkpoint'],
        ['StateConflict', 'CASE_REVIEW_AFTER_GATE_A: use technical_normalize or semantic_reopen before a new review'],
    ],
    'policy fields': [
        ['ValueError', 'policy mode must be preparatory or no_implementation'],
        ['ValueError', 'policy requires id, reason and source revision'],
    ],
    'policy state': [
        ['StateConflict', 'policy references stale source revision'],
        ['StateConflict', 'policy must bind the exact approved scope'],
    ],
    'code_only fields': [
        ['ValueError', 'code-only receipts are allowed only for S0, S6, S7 or S8'],
        ['ValueError', 'code-only receipt requires id and reason'],
        ['ValueError', 'code-only receipt requires evidence'],
    ],
    'code_only state': [
        ['StateConflict', 'checkpoint active work before code-only completion'],
        ['StateConflict', 'required prior logical stage incomplete'],
        ['StateConflict', 'stage already completed'],
    ],
    'invalidate fields': [
        ['ValueError', 'invalidation requires a cause'],
        ['ValueError', 'invalidation must name a nonempty affected current scope'],
    ],
    'invalidate dispatches': [
        ['StateConflict', 'checkpoint active work before invalidation'],
        ['StateConflict', 'invalidation may name only dispatches in its affected scope'],
    ],
    'invalidate applicability': [   # items 2 to 4 of the carry; item 1 (the decision) is pinned on its own below
        ['StateConflict', 'Gate A applicability requires explicit unchanged requirements and oracle'],
        ['StateConflict', 'Gate A applicability must bind the unchanged current plan revision'],
        ['StateConflict', 'Gate A applicability must preserve the exact approved scope'],
    ],
    'mutation intent': [
        ['StateConflict', 'mutation names an unknown author dispatch'],
        ['StateConflict', 'mutation ownership and original content are immutable'],
    ],
    'mutation progress': [
        ['StateConflict', 'reviewed mutation needs an active independent qa-code-critic dispatch'],
        ['StateConflict', 'author mutation must be checkpointed before independent review'],
        ['StateConflict', 'mutation progress cannot skip evidence steps'],
    ],
    'mutation receipts': [
        ['ValueError', 'written progress requires content hashes'],
        ['ValueError', 'execution/review requires receipts'],
    ],
    'gate decision call': [
        ['ValueError', 'gate must be one of: A, B'],
        ['ValueError', "--words must carry the person's own words; they are the authorization_source of the recorded decision. Pass --words-file <path to their words, as they were given>"],
    ],
    'rework call': [
        ['ValueError', "stage 'S99' must be one of: S0, S1, S2, S3, S4, S5, S6, S7, S8, S9"],
        ['ValueError', "purpose 'zz' must be one of: bind, build, collect, diagnostic, first_look, flaky_diagnostic, initial, investigation, manual, quality, red_probe, reference_walk, repair_verify, s3_labelling, s5_plan"],
        ['ValueError', '--reason must say what this round repairs; it is what the role reads'],
        ['ValueError', "--cause 'zzz' must be one of: test_defect, mechanical, environment, tooling, reviewer_error, question_answer, source_arrived, ticket_changed"],
        ['ValueError', 'case(s) outside the approved scope: TC-9; the approved scope is TC-1'],
    ],
    'rework prior': [
        ['ValueError', '--reason must say what this round repairs; it is what the role reads'],
        ['ValueError', 'no accepted qa-nobody dispatch on S0 to rework; accepted roles on S0: qa-worker'],
    ],
    'rerun_after shape': [
        ['ValueError', 'rerun_after must be an object with the lists stages, reviews, decisions only; build it with `--operation rework --words-file`, never by hand'],
        ['ValueError', 'rerun_after belongs to a rework request, which names the dispatch it reworks in `rework_of`; build it with `--operation rework --words-file`'],
    ],
    'rerun_after lists': [
        ['ValueError', 'rerun_after.stages must be a list of ids'],
        ['ValueError', "rerun_after.reviews must be an accepted dispatch of S4 by its closing role, not by qa-x (the role being reworked); got 'nope'"],
        ['ValueError', "rerun_after.decisions must be an approved gate decision a rework of S4 sets aside (gate A only when the stage is S4 or before, gate B up to S8); got 'nope'"],
    ],
    'checkpoint call': [
        ['ValueError', '--dispatch names the dispatch to checkpoint; running dispatches: none'],
        ['ValueError', '--status must be one of: blocked, paused, incomplete (`accepted` is `--operation accept`, which needs evidence)'],
        ['ValueError', '--reason says what this dispatch is waiting on; `next` reads it back to whoever resumes the story'],
    ],
    'release call': [
        ['ValueError', '--dispatch names the dispatch to release; open dispatches: none'],
        ['ValueError', "--words records the person's own words: a release is their decision, not the factory's. Pass --words-file <path to their words, as they were given>"],
    ],
    'prepare outputs': [
        ['ValueError', 'evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['ValueError', 'evidence path ghost-b.txt is not a file under the task root <ROOT>\\main'],
    ],
    'gate_inputs plan': [
        ['ValueError', 'structured test plan rows must be a list'],
        ['ValueError', 'lifecycle_actions must be an array'],
    ],
    'gate A content (sources, plan missing)': [
        ['StateConflict', 'source inventory required before completed discovery'],
        ['StateConflict', 'managed lifecycle requires work/test-plan.json'],
    ],
    'gate A content (sources, plan drift)': [
        ['StateConflict', 'source inventory required before completed discovery'],
        ['StateConflict', 'Gate A plan content changed after approval; re-review affected scope'],
    ],
    # C4-4, captured at ef7b437c (each loop raised its FIRST unresolvable reference alone)
    'reconcile refs': [
        ['StateConflict', 'successor evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['StateConflict', 'successor evidence path ghost-b.txt is not a file under the task root <ROOT>\\main'],
    ],
    # t-913 (Lead, FR-46): the class is ValueError since C4-10 - these references are fields of the request, the call's fault
    'request_cancel refs': [
        ['ValueError', 'cancellation evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['ValueError', 'cancellation authorization path ghost-b.txt is not a file under the task root <ROOT>\\main'],
    ],
    'accept refs and reason': [
        ['ValueError', 'evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['ValueError', 'evidence path ghost-b.txt is not a file under the task root <ROOT>\\main'],
        # SC1-7 R8 (the Lead's decision 27.10): the field, what it carries, and the conductor's accept door
        ['ValueError', '"unresolved" is given without "reason": "reason" carries why the work is accepted unresolved '
                       "(S1: the person's words of the accepted gap, as ticket_adapter.py accept-gap recorded them). "
                       'Run instead `story_step.py finish --task main --dispatch-id d --digest "<the role\'s digest line>"`: '
                       'it writes this request whole (idempotency_key, expected_revision, evidence) and records the stage. '
                       "Accepting a role's work is the conductor's move - a role that reads this returns its digest instead."],
    ],
    'policy refs': [
        ['ValueError', 'policy evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['ValueError', 'policy evidence path ghost-b.txt is not a file under the task root <ROOT>\\main'],
    ],
    'code_only refs': [
        ['ValueError', 'code-only evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['ValueError', 'code-only evidence path ghost-b.txt is not a file under the task root <ROOT>\\main'],
    ],
    'invalidate carry refs': [
        ['ValueError', 'Gate A applicability evidence path ghost-a.txt is not a file under the task root <ROOT>\\main'],
        ['ValueError', 'Gate A applicability evidence path ghost-b.txt is not a file under the task root <ROOT>\\main'],
    ],
}

# C3-11 fix round (t-876 F-3): a chain whose later checks did not run because an earlier one failed says so, in
# `_noted`'s form (the sentence appended to the LAST item). Per chain: the flag whose failure skips the checks, and
# the sentence. Every other flag leaves the chain's text as it was (the note is owed only when a check was skipped).
NOT_RUN_UNKNOWN = "(the unknown-dispatch check did not run: no dispatch is named)"
CHAIN_SKIPPED = {
    'rework call': (0, "(the cases-required and accepted-dispatch checks did not run: they read the stage as a number)"),
    'rerun_after shape': (0, "(the checks of the stages, reviews and decisions lists did not run: they read the "
                             "stamp as an object with those lists)"),
    'rerun_after lists': (0, "(the checks of the members of rerun_after.stages did not run: they read a list of ids)"),
    'checkpoint call': (0, NOT_RUN_UNKNOWN),
    'release call': (0, NOT_RUN_UNKNOWN),
}


def controller_chains_are_refused_whole():
    """K1 (C3-11): the controller's chains of independent checks refuse every problem at once, in chain order.

    Per chain, defects are flags: ONE flag alone must raise the BEFORE text (`CHAIN_BEFORE`, byte for byte,
    same class), ALL flags together must be one compound refusal whose numbered lines are those texts in the
    chain's order, in the class of the first. `CHAINS_CAPTURE=1` prints the singles instead (the BEFORE run)."""
    capture = bool(os.environ.get("CHAINS_CAPTURE"))
    with tempfile.TemporaryDirectory(prefix="qa-chains-") as td:
        base_root = mark_project(Path(td))

        def story(name, scope=("TC-1",)):
            sub = base_root / name; sub.mkdir()
            ctl = Controller(sub)
            ctl.apply("initialize", {"scope": list(scope), "source_revision": "r-" + name,
                                     "known_paths": {"root": str(sub)}, "idempotency_key": "init-" + name})
            return ctl, sub

        c, root = story("main")
        accept_stage(c, root, "S0")
        st = c.state()
        rev = st["source_revision"]
        gate_a = {"A": {"id": "A", "gate": "A", "status": "approved", "source_revision": rev, "scope": ["TC-1"]}}
        running = {"d": {"id": "d", "status": "running", "scope": ["TC-1"]}}
        ref = {"path": "x", "sha256": "y"}
        mut = {"id": "m", "dispatch_id": "d", "paths": ["f"], "before_hashes": {"f": "h"}, "status": "planned"}
        lease = {"orchestrator": {"owner_session_id": "s1"}}
        done = {f"S{i}": {"status": "completed"} for i in range(6)}

        def refuse(call):
            try:
                call()
            except (StateConflict, ValueError) as exc:
                # the temp dir is a different one every run: the text is compared with its place named `<ROOT>`
                text = HOLDER_CLAUSE.sub(r"\1", str(exc))
                for place in (base_root, base_root.resolve()):
                    text = text.replace(str(place), "<ROOT>").replace(place.as_posix(), "<ROOT>")
                # the texts below were captured on Windows: `<ROOT>\main` is the one spelling, whatever the platform's separator
                return type(exc).__name__, text.replace("<ROOT>/", "<ROOT>\\")
            return None, ""

        def val(op, p, state=None):
            return lambda: c.validate(op, p, st if state is None else state)

        def plan_story(name):
            """A story whose Gate A decision binds a seeded plan (the decision is what the plan is now)."""
            ctl, sub = story(name)
            seed_plan(sub)
            decision = dict(gate_a["A"], source_revision="r-" + name, **ctl.gate_inputs())
            return ctl, sub, decision

        gi, gi_root = story("gate-inputs")

        def gate_inputs_call(a, b):
            (gi_root / "work").mkdir(exist_ok=True)
            (gi_root / "work" / "test-plan.json").write_text(json.dumps(
                {"rows": "x" if a else [], "lifecycle_actions": "y" if b else []}), encoding="utf-8")
            return gi.gate_inputs

        def content_call(second):
            """Gate A content drift: a = the sources refused (inventory required, none on disk); b = `second`."""
            def build(a, b):
                ctl, sub, decision = plan_story("content-" + second + "-" + str(int(a)) + str(int(b)))
                if second == "plan missing" and b:
                    (sub / "work" / "test-plan.json").unlink()
                if second == "plan drift" and b:
                    decision["plan_content_hash"] = "stale"
                state = dict(ctl.state(), decisions={"A": decision}, source_inventory_required=bool(a))
                return lambda: ctl._validate_gate_a_content_current(state)
            return build

        applicability = lambda a, b, k, d: {  # noqa: E731
            "decision_id": "A", "requirements_unchanged": not b, "evidence_refs": [ref],
            "plan_revision": "other" if k else (st.get("plan_revision") or rev),
            "scope": ["TC-9"] if d else ["TC-1"]}
        carry_call = lambda carry: {"reason": "r", "affected_scope": ["TC-1"], "source_revision": "new-rev",  # noqa: E731
                                    "gate_a_applicability": carry}
        stamp_p = lambda stamp, **over: dict({"stage": "S4", "role": "qa-x", "rework_of": "w",  # noqa: E731
                                              "rerun_after": stamp}, **over)
        no_state = {"dispatches": {}, "decisions": {}}
        # C4-4: the per-reference loops. A flag makes ONE of the two references unresolvable (its path is no file); the
        # refusal of a reference is the sentence `contract.evidence_ref_issue` writes for it, one item per reference.
        good_ref = evidence_ref(root, "ok.txt")
        refs_of = lambda a, b: [{"path": "ghost-a.txt", "sha256": "x"} if a else good_ref,  # noqa: E731
                                {"path": "ghost-b.txt", "sha256": "x"} if b else good_ref]
        stopped_pair = lambda refs: {  # noqa: E731
            "o": {"id": "o", "status": "paused", "scope": ["TC-1"], "stage": "S1", "role": "qa-w", "input_hash": "h"},
            "s": {"id": "s", "status": "accepted", "scope": ["TC-1"], "stage": "S1", "role": "qa-w", "input_hash": "h",
                  "evidence_refs": refs}}
        running_s0 = {"d": {"id": "d", "status": "running", "stage": "S0", "role": "qa-worker", "scope": ["TC-1"]}}
        through_s4 = {f"S{i}": {"status": "completed"} for i in range(5)}
        policy_p = lambda refs: {"mode": "preparatory", "id": "pol", "reason": "r", "source_revision": rev,  # noqa: E731
                                 "scope": ["TC-1"], "evidence_refs": refs}
        cases = {
            "known_paths keys": (2, lambda a, b: val("initialize", {"known_paths": dict(
                {"root": ""} if a else {}, **({"entrypoints": {"x": ""}} if b else {}))})),
            "known_paths and agent_id": (2, lambda a, b: val("dispatch", dict(
                {"known_paths": {"root": ""} if a else {}}, **({"agent_id": ""} if b else {})))),
            "initialize fields": (3, lambda a, b, k: val("initialize", dict(
                {"scope": [], "known_paths": {"root": "x"}, "coverage_contract_version": 3 if b else 2,
                 "plan_contract_mode": "x" if k else "new"}, **({} if a else {"source_revision": "r"})),
                {"source_revision": None})),
            "revise_plan fields": (2, lambda a, b: val("revise_plan", dict(
                {"scope": ["TC-1"], "plan_revision": "p"}, **({} if a else {"reason": "r"}),
                **({"bogus": 1} if b else {})))),
            "semantic_reopen state": (2, lambda a, b: val(
                "semantic_reopen", {"reason": "r", "affected_scope": ["TC-1"]},
                dict(st, dispatches=running if a else {}, decisions={} if b else gate_a))),
            "telemetry state": (2, lambda a, b: val(
                "orchestrator_telemetry", {"owner_session_id": "other" if a else "s1", "model_requests": 1},
                dict(st, leases=lease, host_capabilities=[] if b else ["orchestrator_telemetry"]))),
            "telemetry fields": (2, lambda a, b: val(
                "orchestrator_telemetry", {"owner_session_id": "s1", "model_requests": -1 if a else 1,
                                           "context_percent": 101 if b else 5},
                dict(st, leases=lease, host_capabilities=["orchestrator_telemetry"]))),
            "dispatch id and case review": (2, lambda a, b: val(
                "dispatch", {"id": "x", "stage": "S4", "role": "qa-case-critic", "scope": ["TC-1"],
                             "input_hash": "h", "budget": {}, "known_paths": {}},
                dict(st, dispatches={"x": {"id": "x", "status": "accepted"}} if a else {},
                     decisions=gate_a if b else {}))),
            "policy fields": (2, lambda a, b: val("policy", dict(
                {"mode": "bad" if a else "preparatory", "reason": "r", "source_revision": rev},
                **({} if b else {"id": "pol"})))),
            "policy state": (2, lambda a, b: val("policy", {
                "mode": "preparatory", "id": "pol", "reason": "r", "source_revision": "other" if a else rev,
                "scope": ["TC-9"] if b else ["TC-1"]})),
            "code_only fields": (3, lambda a, b, k: val("code_only", dict(
                {"stage": "S3" if a else "S6", "reason": "r", "evidence_refs": [] if k else [ref]},
                **({} if b else {"id": "i"})))),
            "code_only state": (3, lambda a, b, k: val(
                "code_only", {"stage": "S6", "id": "i", "reason": "r", "evidence_refs": [ref]},
                dict(st, dispatches=running if a else {},
                     stages=dict({} if b else done, **({"S6": {"status": "completed"}} if k else {}))))),
            "invalidate fields": (2, lambda a, b: val("invalidate", dict(
                {"affected_scope": ["TC-9"] if b else ["TC-1"]}, **({} if a else {"reason": "r"})))),
            "invalidate dispatches": (2, lambda a, b: val(
                "invalidate", {"reason": "r", "affected_scope": ["TC-1"], "dispatch_ids": ["d"]},
                dict(st, dispatches={"d": {"id": "d", "status": "running" if a else "accepted",
                                           "scope": ["TC-9"] if b else ["TC-1"]}}))),
            "invalidate applicability": (3, lambda a, b, k: val(    # the decision holds: items 2 to 4 of the carry
                "invalidate", carry_call(applicability(None, a, b, k)), dict(st, decisions=gate_a))),
            "mutation intent": (2, lambda a, b: val("mutation", mut, dict(
                st, dispatches={} if a else running,
                mutations={"m": dict(mut, before_hashes={"f": "changed"})} if b else {}))),
            "mutation progress": (3, lambda a, b, k: val(
                "mutation", dict(mut, status="reviewed", reviewer_dispatch_id="r", after_hashes={"f": "a"},
                                 evidence_refs=[ref]),
                dict(st, dispatches={"d": {"id": "d", "status": "running" if b else "accepted"},
                                     "r": {"id": "r", "status": "idle" if a else "running", "role": "qa-code-critic"}},
                     mutations={"m": dict(mut, status="planned" if k else "executed")}))),
            "mutation receipts": (2, lambda a, b: val(
                "mutation", dict(mut, status="executed", **({} if a else {"after_hashes": {"f": "a"}}),
                                 **({} if b else {"evidence_refs": [ref]})),
                dict(st, dispatches=running, mutations={"m": dict(mut, status="written")}))),
            "gate decision call": (2, lambda a, b: lambda: c.build_gate_decision(
                "Q" if a else "A", "" if b else "w")),
            "rework call": (5, lambda a, b, k, d, e: lambda: c.build_rework_request(
                "S99" if a else "S0", "qa-worker", ["TC-9"] if e else [], "" if k else "why",
                "zz" if b else "repair_verify", None, "zzz" if d else None)),
            "rework prior": (2, lambda a, b: lambda: c.build_rework_request(
                "S0", "qa-nobody" if b else "qa-worker", [], "" if a else "why")),
            "rerun_after shape": (2, lambda a, b: lambda: Controller._validate_rerun_after(
                stamp_p({"extra": 1} if a else {}, **({"rework_of": ""} if b else {})), no_state, 4)),
            "rerun_after lists": (3, lambda a, b, k: lambda: Controller._validate_rerun_after(
                stamp_p(dict({"stages": "x"} if a else {}, **({"reviews": ["nope"]} if b else {}),
                             **({"decisions": ["nope"]} if k else {}))), no_state, 4)),
            "checkpoint call": (3, lambda a, b, k: lambda: c.build_checkpoint_request(
                "" if a else "dS0", "zz" if b else "paused", "" if k else "why")),
            "release call": (2, lambda a, b: lambda: c.release_dispatch("" if a else "dS0", "" if b else "w")),
            "prepare outputs": (2, lambda a, b: lambda: c.prepare({"dispatch_id": "dS0", "outputs": (
                ["ghost-a.txt"] if a else []) + (["ghost-b.txt"] if b else [])})),
            "gate_inputs plan": (2, lambda a, b: lambda: gate_inputs_call(a, b)()),
            "gate A content (sources, plan missing)": (2, content_call("plan missing")),
            "gate A content (sources, plan drift)": (2, content_call("plan drift")),
            "reconcile refs": (2, lambda a, b: val(
                "reconcile_dispatch", {"id": "o", "accepted_dispatch_id": "s", "reason": "r"},
                dict(st, dispatches=stopped_pair(refs_of(a, b))))),
            "request_cancel refs": (2, lambda a, b: val(
                "request_cancel", {"id": "d", "cause": "authorized_budget", "evidence_ref": "ghost-a.txt" if a else "ok.txt",
                                   "authorization_ref": "ghost-b.txt" if b else "ok.txt"},
                dict(st, dispatches=running))),
            "accept refs and reason": (3, lambda a, b, k: val(
                "accept", dict({"id": "d", "status": "accepted", "evidence_refs": refs_of(a, b)},
                               **({"unresolved": ["TC-1"]} if k else {})),
                dict(st, dispatches=running_s0))),
            "policy refs": (2, lambda a, b: val(
                "policy", policy_p(refs_of(a, b)), dict(st, stages=through_s4, decisions=gate_a))),
            "code_only refs": (2, lambda a, b: val(
                "code_only", {"stage": "S6", "id": "i", "reason": "r", "evidence_refs": refs_of(a, b)},
                dict(st, dispatches={}, stages=done))),
            "invalidate carry refs": (2, lambda a, b: val(
                "invalidate", carry_call(dict(applicability(None, False, False, False), evidence_refs=refs_of(a, b))),
                dict(st, decisions=gate_a))),
        }
        for name, (count, build) in cases.items():
            singles = [refuse(build(*[index == only for index in range(count)])) for only in range(count)]
            if capture:
                CHAIN_BEFORE[name] = singles
                continue
            skip_at, note = CHAIN_SKIPPED.get(name, (None, ""))
            # the sentence of the checks that did not run rides on the item of the flag that skipped them
            alone = [[cls, text + (" " + note if index == skip_at else "")]
                     for index, (cls, text) in enumerate(CHAIN_BEFORE[name])]
            check(f"{name}: one failing item raises what it raised before, byte for byte, same class"
                  + (", plus the sentence of the checks that did not run" if skip_at is not None else ""),
                  [list(one) for one in singles] == alone, f"{singles!r} != {alone!r}")
            cls, text = refuse(build(*[True] * count))
            wanted_items = [one[1] for one in CHAIN_BEFORE[name]]
            if skip_at is not None:     # all flags set: the skipped checks' sentence closes the LAST item
                wanted_items[-1] += " " + note
            check(f"{name}: {count} independent problems are ONE refusal, in the chain's order, in the first's class",
                  cls == singles[0][0] and text.startswith(f"{count} problems - the request")
                  and split_items(text) == wanted_items, f"{cls}: {text[:400]}")
        if capture:
            print("CHAIN_BEFORE =", json.dumps(CHAIN_BEFORE, indent=1, ensure_ascii=False))
            return
        # the edges named by the spec
        check("an empty problem list refuses nothing (the contract of `_raise_all`)", Controller._raise_all([]) is None)
        ghost = CHAIN_BEFORE["prepare outputs"][0]
        cls, text = refuse(lambda: c.prepare({"dispatch_id": "dS0", "outputs": ["ghost-a.txt", "ghost-a.txt"]}))
        check("two failing items with the SAME text fold into one line `<text> (×2)` (`_merged`)",
              (cls, text) == (ghost[0], ghost[1] + " (×2)"), f"{cls}: {text[:300]}")
        cls, text = refuse(val("initialize", {"scope": [], "known_paths": {"root": "x"},
                                                "coverage_contract_version": [1]}, {"source_revision": None}))
        check("an unhashable value of a later check is a refusal of its own, not a TypeError hiding the earlier ones",
              cls == "ValueError" and len(split_items(text) or []) == 3, f"{cls}: {text[:300]}")
        cls, text = refuse(lambda: c.build_rework_request("S99", "qa-nobody", [], "why"))
        stage_item = CHAIN_BEFORE["rework call"][0]
        check("a check that reads the stage as a number does not run for a stage that is none: one item (not two), "
              "and the refusal NAMES the two checks that did not run (`_noted`, FR-59)",
              [cls, text] == [stage_item[0], stage_item[1] + " " + CHAIN_SKIPPED["rework call"][1]]
              and split_items(text) is None, f"{cls}: {text[:400]}")
        cls, text = refuse(lambda: c.build_rework_request("S0", "qa-nobody", [], ""))
        check("no check was skipped, no sentence of skipped checks (`_noted` owes the line only to a skip)",
              cls == "ValueError" and len(split_items(text) or []) == 2 and "did not run" not in text,
              f"{cls}: {text[:400]}")
        # t-876 F-1: the exact-scope item of the Gate A carry reads `prior`, the record the decision item validates
        item_1 = "Gate A applicability must name the current approved Gate A decision"
        note_1 = ("(the checks of the unchanged requirements, the plan revision and the exact scope did not run: "
                  "they read the decision named here)")
        right = applicability(None, False, False, False)
        for label, decisions, carry in (
                ("an unknown decision_id", gate_a, dict(right, decision_id="NOPE")),
                ("the decision of another gate", {"B": dict(gate_a["A"], id="B", gate="B")}, dict(right, decision_id="B")),
                ("a stale Gate A decision", {"A": dict(gate_a["A"], status="stale")}, right)):
            cls, text = refuse(val("invalidate", carry_call(carry), dict(st, decisions=decisions)))
            check(f"a carry naming {label} with a correct scope is ONE item (the scope item reads that decision), "
                  "with the sentence of the checks that did not run",
                  (cls, text) == ("StateConflict", item_1 + " " + note_1) and split_items(text) is None,
                  f"{cls}: {text[:400]}")
        # t-876 F-5: the same unhashable guard on the identical check of semantic_reopen (was a TypeError)
        cls, text = refuse(val("semantic_reopen", {"reason": "r", "affected_scope": [["TC-1"]]}, dict(st, decisions=gate_a)))
        check("an unhashable entry of semantic_reopen's affected_scope is a refusal, not a TypeError",
              (cls, text) == ("ValueError", "semantic reopen needs reason and nonempty affected current scope"),
              f"{cls}: {text[:300]}")
        # C4-4: the per-reference loops (reconcile, request_cancel, accept, policy, code_only, the Gate A carry)
        ghost_a = {"path": "ghost-a.txt", "sha256": "x"}
        ghost_b = {"path": "ghost-b.txt", "sha256": "x"}
        text_a, text_b = (f"policy evidence path ghost-{n}.txt is not a file under the task root <ROOT>\\main"
                          for n in "ab")
        for name in ("reconcile refs", "request_cancel refs", "accept refs and reason", "policy refs", "code_only refs",
                     "invalidate carry refs"):
            count, build = cases[name]
            check(f"{name}: references that all resolve give no item and no refusal",
                  refuse(build(*[False] * count)) == (None, ""), str(refuse(build(*[False] * count))))
        cls, text = refuse(val("policy", policy_p([ghost_b, ghost_a]), dict(st, stages=through_s4, decisions=gate_a)))
        check("two bad references are listed in the order of the REFERENCES, not of their names",
              cls == "ValueError" and split_items(text) == [text_b, text_a], f"{cls}: {text[:300]}")
        cls, text = refuse(val("policy", policy_p([ghost_a, ghost_a]), dict(st, stages=through_s4, decisions=gate_a)))
        check("the same bad reference twice folds into one line `<text> (×2)`",
              (cls, text) == ("ValueError", text_a + " (×2)") and split_items(text) is None, f"{cls}: {text[:300]}")
        for label, call, want in (      # the four list checks: one plain sentence each
                ("reconcile", val("reconcile_dispatch", {"id": "o", "accepted_dispatch_id": "s", "reason": "r"},
                                  dict(st, dispatches=stopped_pair([]))),
                 ("ValueError", "reconciliation requires reason and accepted evidence")),
                ("policy", val("policy", policy_p([]), dict(st, stages=through_s4, decisions=gate_a)),
                 ("ValueError", "policy requires evidence for the no-implementation decision")),
                ("accept", val("accept", {"id": "d", "status": "accepted", "evidence_refs": []},
                               dict(st, dispatches=running_s0)),
                 ("ValueError", "accept requires evidence, never an empty digest")),
                ("Gate A carry", val("invalidate", carry_call(dict(applicability(None, False, False, False), evidence_refs=[])),
                                     dict(st, decisions=gate_a)),
                 ("ValueError", "Gate A applicability requires evidence of unchanged requirements"))):
            check(f"an empty reference list is the list's own sentence, plain: {label}",
                  refuse(call) == want, f"{refuse(call)}")
        # mixed classes split at the boundary: the stop of another class does not list the references behind it
        cls, text = refuse(val("request_cancel", {"id": "d", "cause": "nope", "evidence_ref": "ghost-a.txt"},
                               dict(st, dispatches=running)))
        check("request_cancel: the call's own fault (`cancellation`, ValueError) stops before the story's references",
              cls == "ValueError" and text.startswith("cancellation requires an explicit cause") and "ghost" not in text,
              f"{cls}: {text[:300]}")
        cls, text = refuse(val("reconcile_dispatch", {"id": "o", "accepted_dispatch_id": "s", "reason": ""},
                               dict(st, dispatches=stopped_pair([ghost_a]))))
        check("reconcile: the missing reason (ValueError) stops before the story's references (StateConflict)",
              (cls, text) == ("ValueError", "reconciliation requires reason and accepted evidence"), f"{cls}: {text[:300]}")
        cls, text = refuse(val("code_only", {"stage": "S6", "id": "i", "reason": "r", "evidence_refs": [ghost_a]},
                               dict(st, dispatches=running, stages=done)))
        check("code_only: the story's facts (StateConflict) stop before the call's references (ValueError)",
              (cls, text) == ("StateConflict", "checkpoint active work before code-only completion"), f"{cls}: {text[:300]}")
        # accept: the references are read from evidence that holds; a wrong status leaves them unread and SAYS so (`_noted`)
        unread = "(the evidence references were not checked: the status is not accepted)"
        for label, refs in (("resolving", [good_ref]), ("unresolvable", [ghost_a])):
            cls, text = refuse(val("accept", {"id": "d", "status": "paused", "evidence_refs": refs},
                                   dict(st, dispatches=running_s0)))
            check(f"accept with the status paused and {label} references: the evidence item names the unread references",
                  (cls, text) == ("ValueError", "accept requires evidence, never an empty digest " + unread)
                  and split_items(text) is None, f"{cls}: {text[:300]}")
        cls, text = refuse(val("accept", {"id": "d", "status": "accepted", "evidence_refs": []},
                               dict(st, dispatches=running_s0)))
        check("no references to read, nothing skipped: the empty digest carries no sentence of unread references",
              "were not checked" not in text, f"{cls}: {text[:300]}")
        # t-893 F-1: the evidence and the reason of an unresolved handoff are independent facts of one accept - ONE
        # refusal of two items (evidence first), each the same text it has alone; the joint `_raise_all` form (C3-11)
        evidence_item = "accept requires evidence, never an empty digest"
        reason_item = CHAIN_BEFORE["accept refs and reason"][2][1]      # the R8 text of SC1-7: pinned once, above
        cls, text = refuse(val("accept", {"id": "d", "status": "accepted", "evidence_refs": [], "unresolved": ["TC-1"]},
                               dict(st, dispatches=running_s0)))
        check("accept with no evidence AND an unresolved handoff without a reason: TWO items, the evidence first, "
              "the reason second, each the text it has alone",
              cls == "ValueError" and split_items(text) == [evidence_item, reason_item], f"{cls}: {text[:300]}")
        cls, text = refuse(val("accept", {"id": "d", "status": "accepted", "evidence_refs": [good_ref],
                                          "unresolved": ["TC-1"]}, dict(st, dispatches=running_s0)))
        check("NEGATIVE control: the same input with the evidence present is ONE item, the reason",
              (cls, text) == ("ValueError", reason_item) and split_items(text) is None, f"{cls}: {text[:300]}")
        cls, text = refuse(val("accept", {"id": "d", "status": "accepted", "evidence_refs": [],
                                          "unresolved": ["TC-1"], "reason": "handed_to_person"},
                               dict(st, dispatches=running_s0)))
        check("NEGATIVE control: an unresolved handoff WITH a reason and no evidence is ONE item, the evidence",
              (cls, text) == ("ValueError", evidence_item) and split_items(text) is None, f"{cls}: {text[:300]}")
        # NEGATIVE control: reconcile_dispatch is a DEPENDENT chain (the cover check reads both records), untouched
        cls, text = refuse(val("reconcile_dispatch", {"id": "dS0", "accepted_dispatch_id": "nobody", "reason": "r"}))
        check("a chain marked dependent still stops at its first failure (plain text, no compound head)",
              (cls, text) == ("StateConflict", "only a stopped dispatch can be reconciled"), f"{cls}: {text[:300]}")
        # t-913 C4-10 (t-893 F-5): an unhashable entry of the dispatch's scope is a refusal, not a TypeError - at the
        # scope check of `validate` and at the manual runner block, on the same operation
        dispatch_p = lambda scope: {"id": "x2", "stage": "S1", "role": "qa-x", "scope": scope,  # noqa: E731
                                    "input_hash": "h", "budget": {}, "known_paths": {}}
        cls, text = refuse(val("dispatch", dispatch_p([["TC-1"]])))
        check("dispatch with an unhashable scope entry: the schema refusal that NAMES the field comes first",
              cls == "ValueError" and text.startswith("$.scope[0]"), f"{cls}: {text[:300]}")
        # the scope check behind the schema is a guard of its own: with the schema out of the way it still refuses
        schema_check, controller_module.validate_record = controller_module.validate_record, lambda *_: None
        try:
            cls, text = refuse(val("dispatch", dispatch_p([["TC-1"]])))
        finally:
            controller_module.validate_record = schema_check
        check("dispatch with an unhashable scope entry, past the schema: the scope refusal, never a TypeError",
              cls == "StateConflict" and text.startswith("scope expansion requires plan/gate revision: ['TC-1'];")
              and "--operation revise_plan" in text, f"{cls}: {text[:300]}")   # CX1-11 R4: the old words, then the member and the door
        check("NEGATIVE control: the same dispatch with a scope inside the story's passes the scope check",
              not refuse(val("dispatch", dispatch_p(["TC-1"])))[1].startswith("scope expansion requires plan/gate revision"))
        # FB-9 (R2): ONE problem is the prefix and its own sentence on one line; the same inputs and classes as before
        manual_block = "manual runner block must name 1..5 unique in-scope cases:"
        for label, scope, cases_named, want in (
                ("an unhashable scope entry", [["TC-1"]], ["TC-1"],
                 ("StateConflict", manual_block + " the dispatch scope is not a list of case ids")),
                ("a scope that is no collection", 5, ["TC-1"],
                 ("StateConflict", manual_block + " the dispatch scope is not a list of case ids")),
                ("a case in the scope (control)", ["TC-1", "TC-2"], ["TC-1"], (None, "")),
                ("a case out of the scope (control)", ["TC-2"], ["TC-1"],
                 ("StateConflict", manual_block + " not in the dispatch scope: TC-1"))):
            check(f"manual runner block, {label}",
                  refuse(lambda: validate_manual_runner_block(scope, cases_named)) == want,
                  str(refuse(lambda: validate_manual_runner_block(scope, cases_named))))
        # t-913 C4-10 (t-893 F-6): the refusal with no Gate A decision says which checks it did not run (`_noted`, FR-59)
        c2, _sub, decision_a = plan_story("no-decision")
        no_decision = "current Gate A decision required"
        cls, text = refuse(lambda: c2._validate_gate_a_content_current(dict(c2.state(), decisions={})))
        check("no current Gate A decision: ONE item, and it names the drift checks that did not run",
              (cls, text) == ("StateConflict", no_decision + " (the sources and the plan were not checked for drift: "
                                                              "drift is measured against this decision)")
              and split_items(text) is None, f"{cls}: {text[:300]}")
        cls, text = refuse(lambda: c2._validate_gate_a_content_current(dict(c2.state(), decisions={"A": decision_a})))
        check("NEGATIVE control: with the decision there is no such sentence", "not checked for drift" not in text, f"{cls}: {text[:300]}")


def the_transition_carries_the_agent_onto_the_dispatch() -> None:
    """CX1-13 (F-3 (a), I5): `story_step bind` passes `--dispatch-id`, the transition payload carries it, and the
    projection puts the agent id on THAT dispatch only. KILLS: restore the guess `mine = named or running` (a
    transition without `dispatch_id` then names the one running dispatch: pin 1), let the block write into
    `state["stages"]` (pin 'the id lives on the dispatch'), or drop the `running` condition (pin 2)."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})

        def dispatch(identifier, stage="S0", role="qa-automator"):
            c.apply("dispatch", {"id": identifier, "stage": stage, "role": role, "scope": ["TC-1"], "input_hash": "h",
                                 "budget": {}, "known_paths": {}, "idempotency_key": "d:" + identifier})

        counter = [0]

        def transition(agent, named=None, stage="S0", status="running"):
            counter[0] += 1
            payload = {"task": root.name, "stage": stage, "status": status, "role": "qa-automator", "digest": "",
                       "agent_id": agent}
            if named is not None:
                payload["dispatch_id"] = named
            c.store.commit("stage_transition", payload, f"stage:t{counter[0]}", project=c.project)
            return c.state()

        dispatch("S0-qa-automator-1")
        state = transition("agent-A")
        entry_before = dict(state["stages"]["S0"])
        check("pin 1: a transition with an agent id and NO dispatch_id, exactly one running dispatch: the record is unchanged",
              "agent_id" not in state["dispatches"]["S0-qa-automator-1"], json.dumps(state["dispatches"]["S0-qa-automator-1"])[:300])
        for label, agent in (("blank", "   "), ("empty", ""), ("not a string", 7), ("none", None)):
            state = transition(agent, named="S0-qa-automator-1")
            check(f"an agent id that is {label}: nothing changes", "agent_id" not in state["dispatches"]["S0-qa-automator-1"])
        state = transition("agent-B", named="S0-qa-automator-1")
        check("the dispatch the transition names gets the id (stripped to the host's own text)",
              state["dispatches"]["S0-qa-automator-1"].get("agent_id") == "agent-B")
        check("the id lives on the dispatch: the stage entry carries no agent_id and its run marks are as they were",
              "agent_id" not in state["stages"]["S0"] and state["stages"]["S0"] == entry_before,
              json.dumps(state["stages"]["S0"]))
        state = transition("agent-C", named="S0-qa-automator-1")
        check("a second bind names the new agent", state["dispatches"]["S0-qa-automator-1"].get("agent_id") == "agent-C")
        state = transition("agent-D", named="S0-qa-automator-NOPE")
        check("a name the record does not know: nothing changes", state["dispatches"]["S0-qa-automator-1"].get("agent_id") == "agent-C")
        state = transition("agent-D", named="S0-qa-automator-1", stage="S1")
        check("a dispatch of another stage than the transition's: nothing changes",
              state["dispatches"]["S0-qa-automator-1"].get("agent_id") == "agent-C")
        # two running dispatches of one pair: only the named one
        for number in (2, 3):   # the controller itself refuses a second running dispatch: the journal gets them directly
            c.store.commit("dispatch", {"id": f"S0-qa-automator-{number}", "stage": "S0", "role": "qa-automator",
                                        "scope": ["TC-1"], "input_hash": "h", "budget": {}, "known_paths": {}},
                           f"d:{number}", project=c.project)
        state = transition("agent-E", named="S0-qa-automator-3")
        check("pin 3: two running dispatches of the pair, the third named: only the third gets the id",
              (state["dispatches"]["S0-qa-automator-3"].get("agent_id"), state["dispatches"]["S0-qa-automator-2"].get("agent_id"))
              == ("agent-E", None))
        check("and without a name the two get nothing", "agent_id" not in transition("agent-F")["dispatches"]["S0-qa-automator-2"])
        # a dispatch that is no longer running keeps its record (a host whose Agent call returns after the role stopped)
        c.apply("checkpoint", {"id": "S0-qa-automator-2", "status": "blocked", "reason": "stopped", "checkpoint": {"remaining": []},
                               "idempotency_key": "cp2"})
        state = transition("agent-G", named="S0-qa-automator-2")
        check("pin 2: the named dispatch is not running: nothing changes (the id is dropped, said here on purpose)",
              state["dispatches"]["S0-qa-automator-2"].get("status") != "running"
              and "agent_id" not in state["dispatches"]["S0-qa-automator-2"], json.dumps(state["dispatches"]["S0-qa-automator-2"])[:300])
        # the projection is a replay: the same journal gives the same record
        replay = controller_module.projection(list(c.store.read()))
        check("replaying the journal gives the same agent ids",
              {k: v.get("agent_id") for k, v in replay["dispatches"].items()}
              == {k: v.get("agent_id") for k, v in c.state()["dispatches"].items()})


def the_stage_names_the_agent_of_its_last_bind() -> None:
    """CX1-13 fix round (t-1126 F-1, t-997 L-2 M-5): `pipeline.json` names a stage's agent by the LAST BIND of that
    stage (the position of the bind event), never by the last dispatch CREATED. The invariant `stage_guard.check_resume`
    relies on: the follow-up goes to the agent bound last. KILLS: `_project_pipeline` taking the id of the last created
    dispatch that has one again (pins 1 and 2), or the projection not stamping the bind (pin 1, pin 3). The identity
    and the idempotency key of the transition are not touched by the stamp (it is read off the event order)."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})
        counter = [0]

        def create(identifier, role):   # the journal gets the dispatches directly: the controller refuses a second running one of a stage
            c.store.commit("dispatch", {"id": identifier, "stage": "S0", "role": role, "scope": ["TC-1"], "input_hash": "h",
                                        "budget": {}, "known_paths": {}}, f"d:{identifier}", project=c.project)

        def bind(agent, named):
            counter[0] += 1
            payload = {"task": root.name, "stage": "S0", "status": "running", "role": "qa-automator", "digest": "",
                       "agent_id": agent, "dispatch_id": named}
            c.store.commit("stage_transition", payload, f"stage:b{counter[0]}", project=c.project)

        def staged():
            return (json.loads((root / "pipeline.json").read_text(encoding="utf-8")).get("stages", {}).get("S0") or {}).get("agent_id")

        create("S0-qa-scribe-1", "qa-scribe")
        create("S0-qa-bug-reporter-1", "qa-bug-reporter")
        check("no bind at all: the stage names no agent", staged() is None, str(staged()))
        bind("agent-reporter", "S0-qa-bug-reporter-1")
        bind("agent-scribe", "S0-qa-scribe-1")
        dispatches = c.state()["dispatches"]
        check("pin 1: the scribe was created FIRST and bound LAST - the stage names the scribe's agent, not the last created's",
              staged() == "agent-scribe", f"{staged()} {[(k, v.get('agent_id'), v.get('agent_bound_seq')) for k, v in dispatches.items()]}")
        check("the bind stamp is the bind event's position: later bind, higher stamp",
              dispatches["S0-qa-scribe-1"]["agent_bound_seq"] > dispatches["S0-qa-bug-reporter-1"]["agent_bound_seq"])
        create("S0-qa-scribe-2", "qa-scribe")
        check("pin 2: a dispatch created after a bound one and never bound changes nothing", staged() == "agent-scribe", str(staged()))
        bind("agent-reporter-again", "S0-qa-bug-reporter-1")
        check("pin 3: a later bind of an earlier-created dispatch is the last bind (a repeat bind names the new agent)",
              staged() == "agent-reporter-again", str(staged()))
        control = tempfile.TemporaryDirectory()
        try:
            root2 = Path(control.name)
            c2 = Controller(root2)
            c2.apply("initialize", {"scope": ["TC-1"], "source_revision": "r", "known_paths": {"root": str(root2)},
                                    "idempotency_key": "init"})
            for identifier, role in (("S0-qa-scribe-1", "qa-scribe"), ("S0-qa-bug-reporter-1", "qa-bug-reporter")):
                c2.store.commit("dispatch", {"id": identifier, "stage": "S0", "role": role, "scope": ["TC-1"], "input_hash": "h",
                                             "budget": {}, "known_paths": {}}, f"d:{identifier}", project=c2.project)
            for number, (agent, named) in enumerate((("agent-scribe", "S0-qa-scribe-1"), ("agent-reporter", "S0-qa-bug-reporter-1"))):
                c2.store.commit("stage_transition", {"task": root2.name, "stage": "S0", "status": "running", "role": "qa-automator",
                                                     "digest": "", "agent_id": agent, "dispatch_id": named}, f"stage:c{number}", project=c2.project)
            named_in = (json.loads((root2 / "pipeline.json").read_text(encoding="utf-8"))["stages"]["S0"]).get("agent_id")
            check("control: bound in creation order, the last created is the last bound", named_in == "agent-reporter", str(named_in))
        finally:
            control.cleanup()
        replay = controller_module.projection(list(c.store.read()))
        check("replaying the journal gives the same bind stamps",
              {k: v.get("agent_bound_seq") for k, v in replay["dispatches"].items()}
              == {k: v.get("agent_bound_seq") for k, v in c.state()["dispatches"].items()})


def code_close_conflicts_is_the_one_predicate() -> None:
    """HF3-6 A-K11 (AR-13): "this stage can be closed by code now" is ONE function. `code_only` refuses by it, and
    `execution_request.s6_close_dispatch` allows the S6 close context by it; the same messages, in the same order."""

    def check_eq(name, got, want):
        return check(name, got == want, f"got {got!r}, wanted {want!r}")
    done = {f"S{i}": {"status": "completed"} for i in range(6)}
    running = {"d1": {"id": "d1", "status": "running", "stage": "S6"}}
    states = {
        "running": ({"dispatches": running, "stages": dict(done)},
                    ["checkpoint active work before code-only completion"]),
        "prior": ({"dispatches": {}, "stages": {**done, "S5": {"status": "running"}}},
                  ["required prior logical stage incomplete"]),
        "completed": ({"dispatches": {}, "stages": {**done, "S6": {"status": "completed"}}},
                      ["stage already completed"]),
        "clean": ({"dispatches": {"d1": {"id": "d1", "status": "accepted"}}, "stages": dict(done)}, []),
        "all three": ({"dispatches": running, "stages": {**done, "S5": {"status": "pending"},
                                                         "S6": {"status": "completed"}}},
                      ["checkpoint active work before code-only completion",
                       "required prior logical stage incomplete", "stage already completed"]),
        "no stages at all": ({"dispatches": {}}, ["required prior logical stage incomplete"]),
    }
    scratch = Path(tempfile.mkdtemp(prefix="qa-close-conflicts-"))
    try:
        controller = Controller(scratch)
        for label, (state, want) in states.items():
            got = [(cls.__name__, text) for cls, text in controller_module.code_close_conflicts(state, "S6")]
            check(f"A-K11 {label}: the predicate gives {len(want)} conflict(s), in refusal order",
                  got == [("StateConflict", text) for text in want], str(got))
            payload = {"stage": "S6", "id": "i", "reason": "r", "evidence_refs": [{"path": "x", "sha256": "0" * 64}]}
            try:
                controller.validate("code_only", payload, {**state, "source_revision": "r"})
                refused = []
            except (StateConflict, ValueError) as exc:   # a clean state meets the evidence reference next (ValueError)
                refused = str(exc).splitlines()
            # the operation refuses by the same facts: one sentence, or the numbered text of all of them
            ours = [HOLDER_CLAUSE.sub(r"\1", line.split(") ", 1)[-1]) for line in refused if line[:1].isdigit() and ") " in line[:4]] or \
                [HOLDER_CLAUSE.sub(r"\1", line) for line in refused]
            if "checkpoint active work before code-only completion" in " ".join(want):
                check(f"A-K11 {label}: the running sentence names the holder and the release door (TR1-9 B3)",
                      "(dispatch d1)" in " ".join(refused) and "controller.py --operation release --dispatch d1" in " ".join(refused),
                      f"{refused}")
            if want:
                check(f"A-K11 {label}: Controller.validate refuses with the predicate's messages", ours == want,
                      f"{refused}")
            else:
                check(f"A-K11 {label}: Controller.validate names none of the three conflicts",
                      not any(text in " ".join(refused) for _s, (_st, ws) in states.items() for text in ws), f"{refused}")
        # F-1: the facts are the ONE reading - the conflicts are exactly what the facts say, on every state above
        sentences = (("running", "checkpoint active work before code-only completion"),
                     ("behind", "required prior logical stage incomplete"), ("completed", "stage already completed"))
        for label, (state, _want) in states.items():
            facts = controller_module.code_close_facts(state, "S6")
            check(f"A-K11 {label}: the conflicts are the facts' keys, in order",
                  [text for _c, text in controller_module.code_close_conflicts(state, "S6")]
                  == [text for key, text in sentences if facts[key]], str(facts))
        check_eq("A-K11 facts: a running dispatch is named by its id",
                 controller_module.code_close_facts(states["running"][0], "S6"),
                 {"running": ["d1"], "behind": None, "completed": False})
        check_eq("A-K11 facts: the stage behind comes with its status",
                 controller_module.code_close_facts(states["prior"][0], "S6")["behind"], ("S5", "running"))
        check_eq("A-K11 facts: no `stages` at all is S0, status not recorded",
                 controller_module.code_close_facts(states["no stages at all"][0], "S6")["behind"], ("S0", None))
        # F-3: a row of the wrong shape is read as the unsafe thing, never as a pass and never as a crash
        malformed = {
            "a dispatch row that is not a dict": ({"dispatches": {"d1": "accepted"}, "stages": dict(done)},
                                                  {"running": ["d1"], "behind": None, "completed": False}),
            "a dispatch row with no status": ({"dispatches": {"k": {"id": "d9"}}, "stages": dict(done)},
                                              {"running": ["d9"], "behind": None, "completed": False}),
            "a dispatch row with a status that is not a string": ({"dispatches": {"k": {"status": ["running"]}},
                                                                   "stages": dict(done)},
                                                                  {"running": ["k"], "behind": None, "completed": False}),
            "an earlier stage entry that is not a dict": ({"dispatches": {}, "stages": {**done, "S3": "completed"}},
                                                          {"running": [], "behind": ("S3", None), "completed": False}),
            "an earlier stage status that is not a string": ({"dispatches": {}, "stages": {**done, "S2": {"status": 1}}},
                                                             {"running": [], "behind": ("S2", None), "completed": False}),
            "the stage's own entry that is not a dict": ({"dispatches": {}, "stages": {**done, "S6": "completed"}},
                                                         {"running": [], "behind": None, "completed": True}),
            "the stage's own status that is not a string": ({"dispatches": {}, "stages": {**done, "S6": {"status": 1}}},
                                                            {"running": [], "behind": None, "completed": True}),
            "control: the stage's own entry absent or empty is not completed": (
                {"dispatches": {}, "stages": {**done, "S6": {}}}, {"running": [], "behind": None, "completed": False}),
        }
        for label, (state, want_facts) in malformed.items():
            try:
                got_facts = controller_module.code_close_facts(state, "S6")
                got_conflicts = [text for _c, text in controller_module.code_close_conflicts(state, "S6")]
            except Exception as exc:   # a crash is not a refusal
                got_facts, got_conflicts = repr(exc), []
            check_eq(f"A-K11 F-3 {label}: the facts", got_facts, want_facts)
            check(f"A-K11 F-3 {label}: refused exactly when a fact says so",
                  bool(got_conflicts) == any((want_facts["running"], want_facts["behind"], want_facts["completed"])),
                  str(got_conflicts))
            if not label.startswith("control"):
                try:
                    controller.validate("code_only", {"stage": "S6", "id": "i", "reason": "r",
                                                      "evidence_refs": [{"path": "x", "sha256": "0" * 64}]},
                                        {**state, "source_revision": "r"})
                    outcome = "passed"
                except (StateConflict, ValueError):
                    outcome = "refused"
                except Exception as exc:   # AttributeError and the like: a traceback, not a refusal
                    outcome = repr(exc)
                check_eq(f"A-K11 F-3 {label}: Controller.validate refuses", outcome, "refused")
        # the stage number is read from the stage: S7 wants S0..S6, so the same state that closes S6 does not close S7
        check("A-K11 the stage is a parameter: S7 is not closable over a pending S6",
              [text for _cls, text in controller_module.code_close_conflicts(
                  {"dispatches": {}, "stages": {**done, "S6": {"status": "pending"}}}, "S7")]
              == ["required prior logical stage incomplete"])
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)


def refused(call):
    """The text of the StateConflict (or ValueError) `call` raises, '' when it does not raise."""
    try:
        call()
    except (StateConflict, ValueError) as exc:
        return str(exc)
    return ""


def the_s3_gate_runs_on_every_s3_acceptance():
    """G1-5: `validate` calls `_s3_completion_gate` for EVERY S3 acceptance. Window 1 never closes the stage (no word passes that), its role
    findings stop it without `stage_complete`; the exit takes the plan and the grounding as one list through the person's word; a story on a
    diff with no table is refused (an old story's stop is not reversed); a check that raised is a refusal; without a grounding finding the
    plan's refusal keeps its head byte for byte."""
    import grounding_table as GT
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "g15", "known_paths": {"root": str(root)}, "idempotency_key": "g15-init"})
        for number in range(3):
            accept_stage(c, root, f"S{number}")

        def pipeline(**more):
            (root / "pipeline.json").write_text(json.dumps(dict({"ticket": root.name}, **more)), encoding="utf-8")
            record_stage_acceptance(root, "S3")  # E-B11: the rewrite drops the acceptance record; the qa-worker stub has no author dispatch

        def request(name, **more):
            seed_plan(root)
            c.apply("dispatch", dict({"id": name, "stage": "S3", "role": "qa-worker", "scope": ["TC-1"], "input_hash": "g15", "budget": {},
                                      "known_paths": {}, "idempotency_key": "dispatch-" + name}, **more))
            return {"id": name, "status": "accepted", "stage_complete": True, "evidence_refs": [evidence_ref(root, name + ".txt")],
                    "idempotency_key": "accept-" + name}

        close = request("g15-a")        # dispatched while no pipeline.json holds the stage guard's statuses
        pipeline(implementation_source="diff")
        text = refused(lambda: c.apply("accept", close))
        check("G1-5 an old story (a diff, no grounding table) is refused at the S3 exit, through validate", "S3 grounding" in text and "missing" in text, text[:200])
        check("G1-5 ...and the refusal names the person's door", "waiver.py --task" in text and "--stage S3" in text, text[:300])
        pipeline(implementation_source="diff", stage_overrides=[{"stage": "S3", "match": "missing while implementation_source is diff",
                                                                  "decision": "go on without the table", "at": "t"}])
        check("G1-5 a person's recorded word passes the same refusal, and the pass is journalled",
              refused(lambda: c.apply("accept", close)) == "" and "S3" in (root / "state" / "passed-by-person.jsonl").read_text(encoding="utf-8"))

        win1 = {"id": "w1", "stage": "S3", "request_binding": {"purpose": "s3_labelling"}}
        exit_d = {"id": "w2", "stage": "S3", "request_binding": {"purpose": "initial"}}
        pipeline(implementation_source="diff", stage_overrides=[{"stage": "S3", "match": "*", "decision": "everything", "at": "t"}])
        for given in (True, "true", 1):
            check(f"G1-5 a window-1 dispatch cannot close S3 (stage_complete {given!r}), and no word of a person passes it",
                  "cannot close the stage" in refused(lambda: c._s3_completion_gate(win1, {"stage_complete": given}, {})))
        check("G1-5 window 1 accepted without stage_complete passes with a word that matches everything",
              refused(lambda: c._s3_completion_gate(win1, {"stage_complete": False}, {})) == "")
        pipeline(implementation_source="diff")
        real_check, real_exit = GT.check, GT.exit_findings
        try:
            GT.check = lambda root: [GT.Finding("R1", "1 hunks have no label", "role"), GT.Finding("R5", "the diff moved", "driver")]
            text = refused(lambda: c._s3_completion_gate(win1, {"stage_complete": False}, {}))
            check("G1-5 window 1 without stage_complete: the ROLE's findings refuse, the driver's do not",
                  "S3 grounding" in text and "R1" in text and "R5" not in text, text[:200])
            GT.check = real_check
            GT.exit_findings = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            text = refused(lambda: c._s3_completion_gate(exit_d, {"stage_complete": True}, {}))
            check("G1-5 a check that raised is a refusal that names the exception and the conductor, not a pass",
                  "could not run" in text and "RuntimeError: boom" in text and "conductor" in text, text[:200])
            GT.exit_findings = lambda *a, **k: [GT.Finding("R7", "K-1 reaches no row", "role"), GT.Finding("R5", "diff moved", "driver")]
            text = refused(lambda: c._s3_completion_gate(exit_d, {"stage_complete": True}, {}))
            check("G1-5 the exit refuses on every finding (the role's and the driver's), in the grounding head",
                  text.startswith("S3 grounding: ") and "R7" in text and "R5" in text, text[:200])
            check("G1-5 an exit with stage_complete false is not an exit: no gate", refused(lambda: c._s3_completion_gate(exit_d, {"stage_complete": False}, {})) == "")
            GT.exit_findings = lambda *a, **k: []
        finally:
            GT.check, GT.exit_findings = real_check, real_exit
        (root / "work" / "test-plan.json").write_text(json.dumps([{"id": "TS-1"}]), encoding="utf-8")
        GT.exit_findings = lambda *a, **k: []
        try:
            text = refused(lambda: c._s3_completion_gate(exit_d, {"stage_complete": True}, {}))
        finally:
            GT.exit_findings = real_exit
        check("G1-5 with no grounding finding the plan's refusal keeps its head, byte for byte", text.startswith("S3 structured test plan invalid: ")
              and "S3 grounding" not in text, text[:160])
        try:
            GT.exit_findings = lambda *a, **k: [GT.Finding("R7", "K-1 reaches no row", "role")]
            text = refused(lambda: c._s3_completion_gate(exit_d, {"stage_complete": True}, {}))
        finally:
            GT.exit_findings = real_exit
        check("G1-5 plan errors and grounding findings are ONE refusal: the plan's head first, then `S3 grounding: `",
              text.startswith("S3 structured test plan invalid: ") and "; S3 grounding: " in text, text[:200])


# --- TR4-7: every "checkpoint active work" refusal reads what holds and whether it is alive through ONE helper -----------------------------
def holding_controller(verdicts):
    """A Controller with no store whose liveness reader answers per dispatch id (`verdicts`: id -> dict, or an Exception to raise)."""
    c = Controller.__new__(Controller)
    c._project_root = lambda: Path(".")
    c._dispatch_starts = lambda: {}
    c.store = types.SimpleNamespace(root=Path("QA-TR47"))     # the story's name is read by the plan-scope check that follows the refusal

    def reader(project, record, now=None, names=None):
        verdict = verdicts[record["id"]]
        if isinstance(verdict, Exception):
            raise verdict
        return verdict
    c._liveness = reader
    return c


def tr4_7_state(*rows):
    return {"source_revision": "r", "scope": ["TC-1"], "revision": 5, "decisions": {}, "stages": {},
            "dispatches": {ident: {"id": ident, "stage": stage, "role": role, "status": "running", "scope": ["TC-1"]}
                           for ident, stage, role in rows}}


TR4_7_CALLS = {
    "revise_plan": ("revise_plan", {"scope": ["TC-1"], "plan_revision": "p2", "reason": "why"}, "checkpoint active work before revising scope"),
    "semantic_reopen": ("semantic_reopen", {"affected_scope": ["TC-1"], "reason": "why"}, "checkpoint active work before reopening Gate A"),
    "invalidate": ("invalidate", {"affected_scope": ["TC-1"], "reason": "why", "dispatch_ids": ["S5-w1"]},
                   "checkpoint active work before invalidation"),
}


def tr4_7_refusal(c, name, state):
    op, request, _text = TR4_7_CALLS[name]
    try:
        c.validate(op, dict(request), state)
    except (StateConflict, ValueError) as exc:
        return str(exc)
    return ""


def test_tr4_7_a_dead_holder_does_not_block_any_site():
    dead = {"state": "abandoned", "evidence": ["the session ended"]}
    state = tr4_7_state(("S5-w1", "S5", "qa-automator"), ("S5-w2", "S5", "qa-code-critic"))
    c = holding_controller({"S5-w1": dead, "S5-w2": {"state": "returned", "evidence": []}})
    for name, (_op, _request, sentence) in TR4_7_CALLS.items():
        assert sentence not in tr4_7_refusal(c, name, state), name
    held = c._holding(state)
    assert held["holders"] == [] and held["dead"] == ["S5-w1", "S5-w2"], held


def test_tr4_7_a_live_holder_is_refused_by_name_with_its_door():
    state = tr4_7_state(("S5-w1", "S5", "qa-automator"))
    c = holding_controller({"S5-w1": {"state": "alive", "evidence": []}})
    for name, (_op, _request, sentence) in TR4_7_CALLS.items():
        text = tr4_7_refusal(c, name, state)
        assert sentence in text, (name, text)
        for needle in ("S5-w1", "qa-automator", "S5", "is still running", "wait for it", "--operation checkpoint --dispatch S5-w1",
                       "--operation release --dispatch S5-w1"):
            assert needle in text, (name, needle, text)


def test_tr4_7_unknown_and_an_unreadable_verdict_keep_the_refusal_and_say_so():
    state = tr4_7_state(("S5-w1", "S5", "qa-automator"))
    for verdict in ({"state": "unknown", "evidence": []}, RuntimeError("boom"), None, {"state": "something-new"}):
        c = holding_controller({"S5-w1": verdict})
        for name, (_op, _request, sentence) in TR4_7_CALLS.items():
            text = tr4_7_refusal(c, name, state)
            assert sentence in text and "could not tell" in text and "S5-w1" in text, (name, verdict, text)
    c = Controller.__new__(Controller)
    c._project_root = lambda: None
    c._dispatch_starts = lambda: {}
    assert c._holding(state)["holders"] == ["S5-w1"], "no project to read in: it holds"


def test_tr4_7_several_holders_are_each_named_and_a_dead_one_is_left_out():
    state = tr4_7_state(("S5-w1", "S5", "qa-automator"), ("S5-w2", "S5", "qa-code-critic"))
    c = holding_controller({"S5-w1": {"state": "alive"}, "S5-w2": {"state": "alive"}})
    text = tr4_7_refusal(c, "revise_plan", state)
    assert "S5-w1" in text and "S5-w2" in text and "qa-automator" in text and "qa-code-critic" in text, text
    mixed = holding_controller({"S5-w1": {"state": "alive"}, "S5-w2": {"state": "abandoned"}})
    text = tr4_7_refusal(mixed, "revise_plan", state)
    assert "S5-w1" in text and "S5-w2" not in text, text
    # an invalidation counts only the dispatches it names
    state["dispatches"]["other"] = {"id": "other", "stage": "S5", "role": "qa-automator", "status": "running", "scope": ["TC-1"]}
    c = holding_controller({"S5-w1": {"state": "alive"}, "S5-w2": {"state": "alive"}, "other": {"state": "alive"}})
    try:
        c.validate("invalidate", {"affected_scope": ["TC-1"], "reason": "why", "dispatch_ids": ["S5-w1", "S5-w2"]}, state)
        text = ""
    except StateConflict as exc:
        text = str(exc)
    assert "S5-w1" in text and "S5-w2" in text and "other" not in text, text


def test_tr4_7_no_running_row_means_no_refusal_whatever_a_stage_says():
    state = tr4_7_state()
    state["stages"] = {"S5": {"status": "running", "dispatch_id": "gone"}}
    c = holding_controller({})
    for name, (_op, _request, sentence) in TR4_7_CALLS.items():
        assert sentence not in tr4_7_refusal(c, name, state), name
    assert c._holding(state) == {"holders": [], "dead": [], "verdicts": {}}


TR4_7_DEAD = {"state": "abandoned", "evidence": ["the session ended"]}


def tr4_7_story(td, scope=("TC-1",)):
    """A real Controller over a store with ONE running dispatch `S0-w` (stage S0)."""
    sub = mark_project(Path(td)) / "main"
    sub.mkdir()
    c = Controller(sub)
    c.apply("initialize", {"scope": list(scope), "source_revision": "r", "known_paths": {"root": str(sub)}, "idempotency_key": "init"})
    c.apply("dispatch", {"id": "S0-w", "stage": "S0", "role": "qa-worker", "scope": ["TC-1"], "input_hash": "h", "budget": {},
                         "known_paths": {}, "idempotency_key": "d1"})
    return c


def tr4_7_repairs(c):
    return [e for e in c.store.read() if e.get("type") == "state_repair"]


def tr4_7_refused(call):
    try:
        call()
    except StateConflict as exc:
        return str(exc)
    return ""


def test_tr4_7_apply_records_a_dead_dispatch_once_and_the_operation_goes_on():
    with tempfile.TemporaryDirectory(prefix="qa-tr47-") as td:
        c = tr4_7_story(td)
        revision = c.state()["revision"]
        request = {"scope": ["TC-1"], "plan_revision": "p2", "reason": "why", "expected_revision": revision, "idempotency_key": "rp1"}
        c._liveness = lambda project, record, now=None, names=None: {"state": "alive", "evidence": []}
        refused = tr4_7_refused(lambda: c.apply("revise_plan", dict(request)))
        assert "checkpoint active work before revising scope" in refused and "S0-w" in refused and "qa-worker" in refused, refused
        assert c.state()["dispatches"]["S0-w"]["status"] == "running", "a live dispatch is never closed"
        assert not tr4_7_repairs(c), "a live dispatch is never repaired"
        c._liveness = lambda project, record, now=None, names=None: TR4_7_DEAD
        # B1 (d): the caller's revision is NOT carried past the repair: it is judged against the fresh one, by the ordinary rule
        stale = tr4_7_refused(lambda: c.apply("revise_plan", dict(request, idempotency_key="rp2")))
        assert stale == "stale expected revision", stale
        state = c.state()
        assert state["dispatches"]["S0-w"]["status"] != "running", state["dispatches"]["S0-w"]
        repairs = tr4_7_repairs(c)
        assert len(repairs) == 1 and repairs[0]["payload"]["fixes"][0]["dispatch_id"] == "S0-w", repairs
        assert "the session ended" in repairs[0]["payload"]["fixes"][0]["reason"], repairs
        # F4: the record names the operation that closed the row, not `recover`
        assert repairs[0]["payload"]["reason"] == "revise_plan closed dispatches nobody is doing", repairs[0]["payload"]
        assert repairs[0]["payload"]["fixes"][0]["reason"].startswith("revise_plan: S0-w was recorded as running"), repairs
        # the stale caller reads the state and sends again: nothing running, nothing to repair, the operation goes on
        c.apply("revise_plan", dict(request, expected_revision=c.state()["revision"], idempotency_key="rp3"))
        assert len(tr4_7_repairs(c)) == 1, "no second repair"


def test_tr4_7_a_writer_between_the_read_and_the_repair_is_not_overwritten():
    with tempfile.TemporaryDirectory(prefix="qa-tr47-race-") as td:
        c = tr4_7_story(td)
        c._liveness = lambda project, record, now=None, names=None: TR4_7_DEAD
        real = c.liveness_fixes

        def fixes_then_the_other_writer_acts(state=None, now=None, by=None):
            fixes = real(state, now, by=by)
            c.store.commit("release", {"dispatch_id": "S0-w", "words": "the person set it free", "reason": "x"}, "rel:race")
            return fixes
        c.liveness_fixes = fixes_then_the_other_writer_acts
        assert c.close_settled(c.state(), by="revise_plan") == [], "the revision moved: nothing is written"
        assert not tr4_7_repairs(c), "the repair never lands on a state it did not read"
        assert c.state()["dispatches"]["S0-w"]["status"] == "released_by_person", c.state()["dispatches"]["S0-w"]
        # the operation re-reads and proceeds on the fresh state: nothing runs any more
        c.apply("revise_plan", {"scope": ["TC-1"], "plan_revision": "p2", "reason": "why", "idempotency_key": "rp-race"})
        assert not tr4_7_repairs(c) and c.state()["dispatches"]["S0-w"]["status"] == "released_by_person"


def test_tr4_7_an_event_committed_in_between_is_not_let_through_by_the_caller_revision():
    with tempfile.TemporaryDirectory(prefix="qa-tr47-gap-") as td:
        c = tr4_7_story(td)
        c._liveness = lambda project, record, now=None, names=None: TR4_7_DEAD
        before = c.state()["revision"]
        real = c.liveness_fixes

        def fixes_then_a_decision(state=None, now=None, by=None):
            fixes = real(state, now, by=by)
            c.store.commit("decision", {"id": "dec-1", "gate": "A", "status": "approved"}, "k-dec-gap")
            return fixes
        c.liveness_fixes = fixes_then_a_decision
        request = {"scope": ["TC-1"], "plan_revision": "p2", "reason": "why", "expected_revision": before, "idempotency_key": "rp-gap"}
        text = tr4_7_refused(lambda: c.apply("revise_plan", dict(request)))
        assert text == "stale expected revision", text
        assert not tr4_7_repairs(c), "no repair on a revision it did not read"
        assert not [e for e in c.store.read() if e.get("type") == "revise_plan"], "the stale request committed nothing"
        assert c.state()["dispatches"]["S0-w"]["status"] == "running", "the row was not touched"


def test_tr4_7_an_admitted_s5_window_never_repairs_a_sibling():
    with tempfile.TemporaryDirectory(prefix="qa-tr47-window-") as td:
        c = tr4_7_story(td, scope=("TC-1", "TC-2"))
        c.store.commit("release", {"dispatch_id": "S0-w", "words": "w", "reason": "x"}, "k-rel-s0")
        c.store.commit("dispatch", {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                    "input_hash": "h", "budget": {}, "known_paths": {}}, "k-w1", None, None, c.project)
        c._liveness = lambda project, record, now=None, names=None: TR4_7_DEAD
        state = c.state()
        window = {"id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator", "scope": ["TC-2"], "parallel_window": True}
        assert c._holder_would_refuse("dispatch", window, state) is False, "admitted beside the sibling: nothing refuses"
        assert c._holder_would_refuse("dispatch", dict(window, parallel_window=False), state) is True
        assert c._holder_would_refuse("dispatch", dict(window, scope=["TC-1"]), state) is True, "a shared case is refused"
        assert c._holder_would_refuse("revise_plan", {}, state) is True
        assert c._holder_would_refuse("revise_plan", {}, dict(state, dispatches={})) is False
        calls = []
        real = c.close_settled
        c.close_settled = lambda *a, **k: calls.append(k.get("by")) or real(*a, **k)
        try:
            c.apply("dispatch", dict(window, input_hash="h", budget={}, known_paths={}, idempotency_key="k-w2"))
        except (StateConflict, ValueError):
            pass            # the rest of the admission may refuse this bare packet: only the prelude is judged here
        assert calls == [], "an admitted window never reaches the repair"
        assert not tr4_7_repairs(c) and c.state()["dispatches"]["S5-qa-automator-1"]["status"] == "running"
        try:
            c.apply("dispatch", {"id": "S5-qa-automator-3", "stage": "S5", "role": "qa-automator", "scope": ["TC-2"], "input_hash": "h",
                                 "budget": {}, "known_paths": {}, "idempotency_key": "k-w3"})
        except (StateConflict, ValueError):
            pass
        assert calls == ["dispatch"], "a sequential dispatch blocked by a dead-reading holder is freed through the repair"
        assert c.state()["dispatches"]["S5-qa-automator-1"]["status"] != "running"


def test_tr4_7_a_repair_leaves_a_row_that_is_no_longer_running_alone():
    with tempfile.TemporaryDirectory(prefix="qa-tr47-reducer-") as td:
        c = tr4_7_story(td)
        c.store.commit("release", {"dispatch_id": "S0-w", "words": "the person set it free", "reason": "x"}, "k-rel-red")
        row = dict(c.state()["dispatches"]["S0-w"])
        stages = {name: dict(entry) for name, entry in c.state()["stages"].items()}
        c.store.commit("state_repair", {"fixes": [{"kind": "abandoned", "dispatch_id": "S0-w", "stage": "S0", "role": "qa-worker",
                                                   "digest": "", "reason": "late repair"}], "reason": "t"}, "k-late-repair")
        after = c.state()
        assert after["dispatches"]["S0-w"] == row, (row, after["dispatches"]["S0-w"])
        assert after["stages"] == stages, "the stage of a row that moved on is not reopened"


def test_tr4_7_invalidate_reads_liveness_for_the_named_dispatches_only():
    state = tr4_7_state(("S5-w1", "S5", "qa-automator"), ("S5-w2", "S5", "qa-code-critic"))
    asked = []
    c = holding_controller({"S5-w1": {"state": "alive"}, "S5-w2": {"state": "alive"}})
    inner = c._liveness
    c._liveness = lambda project, record, now=None, names=None: asked.append(record["id"]) or inner(project, record, now, names)
    text = tr4_7_refusal(c, "invalidate", state)
    assert "S5-w1" in text and "S5-w2" not in text, text
    assert asked == ["S5-w1"], asked


def test_tr4_7_the_s6_close_context_reads_liveness_through_the_same_helper():
    import execution_request as ER
    import controller as controller_module_
    state = {"revision": 3, "stages": {**{f"S{i}": {"status": "completed"} for i in range(6)}, "S6": {"status": "pending"}},
             "dispatches": {"S6-a": {"id": "S6-a", "stage": "S6", "role": "qa-runner", "status": "running"},
                            "S6-b": {"id": "S6-b", "stage": "S6", "role": "qa-runner", "status": "running"}}}
    real = controller_module_.Controller

    def said_for(factory, td):
        controller_module_.Controller = factory
        try:
            ER.s6_close_from_state(Path(td), state, ["TC-1"])
            return ""
        except ER.MineRefusal as exc:
            return str(exc)

    def cannot_build(root):
        raise OSError("no store")
    with tempfile.TemporaryDirectory(prefix="qa-tr47-s6-") as td:
        try:
            alive = holding_controller({"S6-a": {"state": "alive"}, "S6-b": {"state": "alive"}})
            said = said_for(lambda root: alive, td)
            # several holders: a door per holder, never the first alone (critic t-2183 F2; pin A-K2 of test_execution_request)
            assert "S6-a" in said and "S6-b" in said and "is still running" in said and "`--dispatch S6-a` or `--dispatch S6-b`" in said, said
            dead = holding_controller({"S6-a": {"state": "abandoned"}, "S6-b": {"state": "returned"}})
            assert "a dispatch is open" not in said_for(lambda root: dead, td)
            assert "a dispatch is open" in said_for(cannot_build, td), "a reader that cannot be built keeps the refusal"
        finally:
            controller_module_.Controller = real


def main() -> int:
    if os.environ.get("CHAINS_CAPTURE"):   # the BEFORE run of C3-11: print what each chain refuses alone, nothing else
        controller_chains_are_refused_whole()
        return 0
    with tempfile.TemporaryDirectory(prefix="qa-controller-") as td:
        root = mark_project(Path(td))
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})
        for number in range(5):
            accept_stage(c, root, f"S{number}")
        seed_plan(root)
        before_events = len(c.store.read())
        before_dispatches = len(c.state()["dispatches"])
        generated = c.gate_inputs()
        check("gate-inputs is code-only and emits exact bindings without launch/event",
              set(generated) == {"plan_content_hash", "plan_semantic_hash", "oracle_content_hashes",
                                 "coverage_contract_revisions", "lifecycle_actions_hash"}
              and len(c.store.read()) == before_events
              and len(c.state()["dispatches"]) == before_dispatches)
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                    "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1"],
                    "input_revision": "src-1", "idempotency_key": "gate-a"}
        decision.update(generated)
        c.apply("decision", decision)
        check("S0 through S4 and exact Gate A permit S5", c.next_action()["stage"] == "S5", c.next_action())
        approved_plan = (root / "work/test-plan.json").read_text(encoding="utf-8")
        edited = json.loads(approved_plan); edited["rows"][0]["coverage_obligations"][0]["behavior"] = "edited after approval"
        (root / "work/test-plan.json").write_text(json.dumps(edited), encoding="utf-8")
        try:
            c.apply("dispatch", {"id": "stale-plan-s5", "stage": "S5", "role": "qa-automator",
                                  "scope": ["TC-1"], "input_hash": "stale", "budget": {}, "known_paths": {},
                                  "idempotency_key": "stale-plan-s5"})
            post_a_rejected = False
        except StateConflict:
            post_a_rejected = True
        (root / "work/test-plan.json").write_text(approved_plan, encoding="utf-8")
        check("post-Gate-A oracle edit makes approval stale before S5", post_a_rejected)
        bad = dict(decision, id="bad", scope=["TC-X"], idempotency_key="bad")
        try:
            c.apply("decision", bad)
            rejected = False
        except StateConflict:
            rejected = True
        check("Gate A rejects a different approved scope", rejected)
        missing_root = root / "missing-v2"; missing_root.mkdir()
        missing = Controller(missing_root)
        missing.apply("initialize", {"scope": ["TC-1"], "source_revision": "mv2", "known_paths": {"root": str(missing_root)}, "idempotency_key": "mv2-init"})
        for number in range(3):
            accept_stage(missing, missing_root, f"S{number}")
        legacy_row = {"id": "TS-1", "impact": "low", "likelihood": "low", "confidence": "high",
                      "risk_rationale": "legacy", "risk_source_refs": ["R-1"], "risk_policy_revision": "factory-starter-v1",
                      "coverage_refs": ["R-1"], "unknowns": [], "verification_depth": "low",
                      "required_scenarios": ["TC-1"], "test_level_rationale": "unit",
                      "design_review_required": False, "bounded_reversible": True}
        plan_path = missing_root / "work/test-plan.json"; plan_path.parent.mkdir()
        plan_path.write_text(json.dumps([legacy_row]), encoding="utf-8")
        missing.apply("dispatch", {"id": "mv2-s3", "stage": "S3", "role": "qa-test-strategist",
                                    "scope": ["TC-1"], "input_hash": "mv2", "budget": {}, "known_paths": {},
                                    "idempotency_key": "mv2-s3"})
        try:
            missing.apply("accept", {"id": "mv2-s3", "status": "accepted", "stage_complete": True,
                                      "evidence_refs": [evidence_ref(missing_root, "mv2.txt")],
                                      "idempotency_key": "mv2-accept"})
            missing_rejected = False
        except StateConflict:
            missing_rejected = True
        check("new task rejects S3 plan rows missing coverage v2", missing_rejected)
        critical_root = root / "critical"; critical_root.mkdir()
        critical = Controller(critical_root)
        critical.apply("initialize", {"scope": ["TC-1"], "source_revision": "critical-r", "known_paths": {"root": str(critical_root)}, "idempotency_key": "critical-init"})
        for number in range(4):
            accept_stage(critical, critical_root, f"S{number}")
        accept_case_review_stage(critical, critical_root, "critical-cases")
        critical_row = {"id": "TS-1", "impact": "unknown", "likelihood": "high", "confidence": "low", "risk_rationale": "unknown oracle", "risk_source_refs": ["R-1"], "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1"], "unknowns": ["oracle"], "verification_depth": "critical", "required_scenarios": ["TC-1"], "test_level_rationale": "contract", "design_review_required": True}
        seed_plan(critical_root, [critical_row])
        gate = {"id": "critical-A", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human", "source_revision": "critical-r", "scope": ["TC-1"], "input_revision": "critical-r", "idempotency_key": "critical-A"}
        bind_gate_a(critical_root, gate)
        try:
            critical.apply("decision", gate)
            rejected_review = False
        except StateConflict:
            rejected_review = True
        gate.update(idempotency_key="critical-A-self", id="critical-A-self", design_reviews=[{"plan_row": "TS-1", "verdict": "accepted", "plan_revision": "critical-r", "case_versions": ["cv_1"], "input_hash": "critical-cases", "author_dispatch_id": "case-author", "reviewer_dispatch_id": "case-author"}])
        try:
            critical.apply("decision", gate)
            rejected_self_review = False
        except StateConflict:
            rejected_self_review = True
        gate.update(idempotency_key="critical-A-ok", id="critical-A-ok", design_reviews=[{"plan_row": "TS-1", "verdict": "accepted", "plan_revision": "critical-r", "case_versions": ["cv_1"], "input_hash": "critical-cases", "author_dispatch_id": "case-author", "reviewer_dispatch_id": "case-critic"}])
        critical.apply("decision", gate)
        check("critical plan refuses missing/self review and accepts independent current dispatch evidence",
              rejected_review and rejected_self_review and critical.next_action()["stage"] == "S5")
        # Mark a completed S5 dispatch stale without affecting its earlier S4 acceptance.
        evidence = root / "s5.txt"; evidence.write_text("ok", encoding="utf-8")
        d = {"id": "d5", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"], "input_hash": "h",
             "budget": {}, "known_paths": {}, "idempotency_key": "d5"}
        with s5_window_form(c, root):
            c.apply("dispatch", d)
        c.apply("accept", {"id": "d5", "status": "accepted", "stage_complete": False,
                            "evidence_refs": [evidence_ref(root, "d5-author.txt")], "idempotency_key": "d5-author-a"})
        c.apply("dispatch", {"id": "d5critic", "stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"],
                                "input_hash": "h", "budget": {}, "known_paths": {}, "idempotency_key": "d5critic"})
        window = {"schema_version": 2, "input_hash": "h", "author_dispatch_id": "d5",
                  "reviewer_dispatch_id": "d5critic", "required_quality_checks": [], "quality_receipts": [], "scope_instances": {"TC-1": ["i"]},
                  "instances": [dict({"instance_id": "i", "outcome": "passed", "input_hash": "h",
                                 "review": {"verdict": "approved", "input_hash": "h"}, "change_disposition": "unchanged",
                                 "change_basis_ref": "manifest:TC-1", "evidence_refs": [{"path": "s5.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]}, **v2_binding(obligation_hash=plan_obligation_hash(root)))]}
        c.apply("accept", {"id": "d5critic", "status": "accepted", "stage_complete": True, "window": window,
                            "evidence_refs": [{"path": "s5.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                            "idempotency_key": "a5"})
        c.apply("invalidate", {"reason": "changed helper", "affected_scope": ["TC-1"], "dispatch_ids": ["d5"],
                                 "decision_ids": [], "idempotency_key": "invalidate"})
        check("invalidation stales only named accepted dispatch", c.state()["dispatches"]["d5"]["status"] == "stale"
              and c.state()["stages"]["S4"]["status"] == "completed")

        carry_root = root / "gate-carry"; carry_root.mkdir()
        carry = Controller(carry_root)
        carry.apply("initialize", {"scope": ["TC-1"], "source_revision": "code-1",
                                    "known_paths": {"root": str(carry_root)}, "idempotency_key": "carry-init"})
        for number in range(5):
            accept_stage(carry, carry_root, f"S{number}")
        seed_plan(carry_root)
        carry_gate = {"id": "carry-A", "gate": "A", "action": "approve", "status": "approved",
                                  "authorization_source": "human", "source_revision": "code-1", "scope": ["TC-1"],
                                  "input_revision": "code-1", "idempotency_key": "carry-A"}
        carry.apply("decision", bind_gate_a(carry_root, carry_gate))
        applicability_ref = evidence_ref(carry_root, "requirements-unchanged.txt", "requirements and oracle unchanged")
        carry.apply("invalidate", {"reason": "implementation-only merge request update", "source_revision": "code-2",
                                    "affected_scope": ["TC-1"], "dispatch_ids": [], "decision_ids": [],
                                    "gate_a_applicability": {"decision_id": "carry-A", "requirements_unchanged": True,
                                                             "plan_revision": "code-1", "scope": ["TC-1"],
                                                             "evidence_refs": [applicability_ref]},
                                    "idempotency_key": "carry-source"})
        carried = [d for d in carry.state()["decisions"].values() if d.get("approval_kind") == "applicability_carry"]
        check("code-only source update carries Gate A with explicit unchanged-plan evidence and provenance",
              carry.next_action().get("stage") == "S5" and len(carried) == 1
              and carried[0].get("prior_decision_id") == "carry-A"
              and carried[0].get("prior_authorization_source") == "human")

        stale_root = root / "gate-stale"; stale_root.mkdir()
        stale = Controller(stale_root)
        stale.apply("initialize", {"scope": ["TC-1"], "source_revision": "code-1",
                                    "known_paths": {"root": str(stale_root)}, "idempotency_key": "stale-init"})
        for number in range(5):
            accept_stage(stale, stale_root, f"S{number}")
        seed_plan(stale_root)
        stale_gate = {"id": "stale-A", "gate": "A", "action": "approve", "status": "approved",
                                  "authorization_source": "human", "source_revision": "code-1", "scope": ["TC-1"],
                                  "input_revision": "code-1", "idempotency_key": "stale-A"}
        stale.apply("decision", bind_gate_a(stale_root, stale_gate))
        stale.apply("invalidate", {"reason": "requirements may have changed", "source_revision": "code-2",
                                    "affected_scope": ["TC-1"], "dispatch_ids": [], "decision_ids": [],
                                    "idempotency_key": "stale-source"})
        check("source update without applicability evidence stales Gate A",
              stale.next_action().get("action") == "await_gate" and stale.next_action().get("gate") == "A")

        full_root = root / "full"; full_root.mkdir()
        full = Controller(full_root)
        full.apply("initialize", {"scope": ["TC-1"], "source_revision": "r", "known_paths": {"root": str(full_root)}, "idempotency_key": "init"})
        for number in range(5):
            accept_stage(full, full_root, f"S{number}")
        seed_plan(full_root)
        full.apply("decision", bind_gate_a(full_root, {"id": "A", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human", "source_revision": "r", "scope": ["TC-1"], "input_revision": "r", "idempotency_key": "A"}))
        evidence5 = full_root / "s5.txt"; evidence5.write_text("ok", encoding="utf-8")
        with s5_window_form(full, full_root):
            full.apply("dispatch", {"id": "s5", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"], "input_hash": "s5", "budget": {}, "known_paths": {}, "idempotency_key": "s5"})
        full.apply("accept", {"id": "s5", "status": "accepted", "stage_complete": False,
                               "evidence_refs": [evidence_ref(full_root, "s5-author.txt")], "idempotency_key": "s5-author-a"})
        full.apply("dispatch", {"id": "s5critic", "stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "s5", "budget": {}, "known_paths": {}, "idempotency_key": "s5critic"})
        full_instance = dict({"instance_id": "i", "outcome": "passed", "input_hash": "s5", "review": {"verdict": "approved", "input_hash": "s5"}, "change_disposition": "unchanged", "change_basis_ref": "manifest:TC-1", "evidence_refs": [{"path": "s5.txt", "sha256": hashlib.sha256(evidence5.read_bytes()).hexdigest()}]}, **v2_binding(obligation_hash=plan_obligation_hash(full_root)))
        full.apply("accept", {"id": "s5critic", "status": "accepted", "stage_complete": True, "window": {"schema_version": 2, "input_hash": "s5", "author_dispatch_id": "s5", "reviewer_dispatch_id": "s5critic", "required_quality_checks": [], "quality_receipts": [], "scope_instances": {"TC-1": ["i"]}, "instances": [full_instance]}, "evidence_refs": [{"path": "s5.txt", "sha256": hashlib.sha256(evidence5.read_bytes()).hexdigest()}], "idempotency_key": "s5a"})
        (full_root / "work").mkdir(exist_ok=True)   # what a real S5 leaves (C4-1): S6-S8 are refused without a manifest
        (full_root / "work" / "automation-manifest.json").write_text('{"tests": [], "unresolved": []}', encoding="utf-8")
        for number in range(6, 9):
            accept_stage(full, full_root, f"S{number}")
        full.apply("decision", {"id": "B", "gate": "B", "action": "deliver", "status": "approved", "authorization_source": "human", "source_revision": "r", "scope": ["TC-1"], "input_revision": "r", "selected_drafts": [], "idempotency_key": "B"})
        accept_stage(full, full_root, "S9")
        # `complete` until 0.7.13. A story past gate B with S8 done IS closed, and saying so
        # is what stops a finished story from being counted as a running one (I-92).
        check("controller reaches S9 only through both exact gates",
              full.state()["stages"]["S9"]["status"] == "completed"
              and full.next_action()["action"] == "closed", full.next_action())
        closed = json.loads((full_root / "pipeline.json").read_text(encoding="utf-8"))
        check("and the finished story carries its own closure",
              bool(closed.get("closed_at")) and closed.get("closed_by") == "gate B + S8 done",
              json.dumps({k: closed.get(k) for k in ("closed_at", "closed_by")}))

        preparatory_root = root / "preparatory"; preparatory_root.mkdir()
        preparatory = Controller(preparatory_root)
        preparatory.apply("initialize", {"scope": ["TC-1"], "source_revision": "prep-r",
                                          "known_paths": {"root": str(preparatory_root)}, "idempotency_key": "prep-init"})
        for number in range(5):
            accept_stage(preparatory, preparatory_root, f"S{number}")
        seed_plan(preparatory_root)
        prep_gate = {"id": "prep-A", "gate": "A", "action": "approve", "status": "approved",
                                        "authorization_source": "human", "source_revision": "prep-r", "scope": ["TC-1"],
                                        "input_revision": "prep-r", "idempotency_key": "prep-A"}
        preparatory.apply("decision", bind_gate_a(preparatory_root, prep_gate))
        preparatory.apply("policy", {"id": "no-implementation", "mode": "preparatory", "reason": "implementation absent",
                                      "source_revision": "prep-r", "scope": ["TC-1"],
                                      "evidence_refs": [evidence_ref(preparatory_root, "policy.txt")],
                                      "idempotency_key": "no-implementation"})
        check("preparatory policy skips S5/S6 only after Gate A",
              preparatory.state()["stages"]["S5"]["status"] == "skipped"
              and preparatory.next_action()["stage"] == "S7")
        preparatory.apply("code_only", {"id": "prep-s7", "stage": "S7", "reason": "no execution blocks in preparatory mode",
                                         "evidence_refs": [evidence_ref(preparatory_root, "s7.txt")], "idempotency_key": "prep-s7"})
        preparatory.apply("code_only", {"id": "prep-s8", "stage": "S8", "reason": "reduced preparatory report",
                                         "evidence_refs": [evidence_ref(preparatory_root, "s8.txt")], "idempotency_key": "prep-s8"})
        check("preparatory path makes code-only S7/S8 receipts without automator dispatch",
              preparatory.next_action()["action"] == "await_gate"
              and not any(d.get("role") == "qa-automator" for d in preparatory.state()["dispatches"].values()))
        preparatory.apply("decision", {"id": "prep-B", "gate": "B", "action": "deliver_with_known_gaps", "status": "approved",
                                        "authorization_source": "human", "source_revision": "prep-r", "scope": ["TC-1"],
                                        "input_revision": "prep-r", "selected_drafts": [], "idempotency_key": "prep-B"})
        check("preparatory Gate B still leads to the ordinary S9 dispatch", preparatory.next_action()["stage"] == "S9")

        zero_root = root / "zero"; zero_root.mkdir()
        zero = Controller(zero_root)
        zero.apply("initialize", {"scope": ["TC-1"], "source_revision": "zero-r", "known_paths": {"root": str(zero_root)}, "idempotency_key": "zero-init"})
        for number in range(5):
            accept_stage(zero, zero_root, f"S{number}")
        seed_plan(zero_root)
        zero_gate = {"id": "zero-A", "gate": "A", "action": "approve", "status": "approved",
                                "authorization_source": "human", "source_revision": "zero-r", "scope": ["TC-1"],
                                "input_revision": "zero-r", "idempotency_key": "zero-A"}
        zero.apply("decision", bind_gate_a(zero_root, zero_gate))
        accept_stage(zero, zero_root, "S5")
        zero.apply("code_only", {"id": "zero-s6", "stage": "S6", "reason": "all current checks already have valid evidence",
                                  "evidence_refs": [evidence_ref(zero_root, "zero-s6.txt")], "idempotency_key": "zero-s6"})
        check("zero-work S6 writes a code-only receipt and reduced run report",
              zero.state()["stages"]["S6"].get("code_only") is True
              and (zero_root / "work" / "run-report.json").exists())

        # C3-14 (critic t-831 F4): `close_by_code` writes the receipt and THEN runs `stage_done`; the
        # `stage_transition` projection used to rewrite the entry and erase `code_only`/`receipt_id`.
        def close_again(stage, key, digest):
            zero.store.commit("stage_transition", {"task": "QA-1", "stage": stage, "status": "done",
                                                    "digest": digest}, key, project=zero.project)

        def pipeline_stage(stage):
            return json.loads((zero_root / "pipeline.json").read_text(encoding="utf-8"))["stages"][stage]

        import s7_pretriage
        receipt_s6 = zero.state()["stages"]["S6"].get("receipt_id")
        close_again("S6", "stage:zero-s6-done", "S6 closed by code")
        s6 = zero.state()["stages"]["S6"]
        check("P1 stage_done after the S6 code-only receipt keeps code_only and the receipt id",
              s6.get("code_only") is True and bool(receipt_s6) and s6.get("receipt_id") == receipt_s6
              and s6.get("status") == "completed" and s6.get("reason") == "S6 closed by code"
              and pipeline_stage("S6").get("code_only") is True and pipeline_stage("S6").get("status") == "done",
              json.dumps(s6))
        check("P1 and the reader S7 asks, s6_closed_by_code, is true for the S6 closed by code",
              s7_pretriage.s6_closed_by_code(zero_root) is True)

        zero.apply("code_only", {"id": "zero-s7", "stage": "S7", "reason": "no test was executed, nothing to triage",
                                  "evidence_refs": [evidence_ref(zero_root, "zero-s7.txt")], "idempotency_key": "zero-s7"})
        receipt_s7 = zero.state()["stages"]["S7"].get("receipt_id")
        close_again("S7", "stage:zero-s7-done", "S7 closed by code")
        s7 = zero.state()["stages"]["S7"]
        check("P2 stage_done after the S7 code-only receipt keeps code_only and the receipt id",
              s7.get("code_only") is True and bool(receipt_s7) and s7.get("receipt_id") == receipt_s7
              and s7.get("status") == "completed" and pipeline_stage("S7").get("code_only") is True,
              json.dumps(s7))

        close_again("S5", "stage:zero-s5-done", "S5 closed again")
        # The clock keys are the telemetry capture's, laid over every entry after the projection.
        clock = ("stage_started", "stage_finished", "provenance", "wall_seconds")
        s5_entry = {k: v for k, v in zero.state()["stages"]["S5"].items() if k not in clock}
        check("P4 a completed stage with no marks closed again gets exactly the fresh entry",
              s5_entry == {"status": "completed", "reason": "S5 closed again"}, json.dumps(s5_entry))

        zero.store.commit("stage_transition", {"task": "QA-1", "stage": "S6", "status": "running",
                                                "digest": "S6 reworked"}, "stage:zero-s6-running", project=zero.project)
        check("P3 setup: a running transition on the code-closed S6 is rework and keeps the marks",
              zero.state()["stages"]["S6"].get("rework") is True and zero.state()["stages"]["S6"].get("code_only") is True)
        close_again("S6", "stage:zero-s6-redone", "S6 run for real")
        s6_again = zero.state()["stages"]["S6"]
        check("P3 a stage reworked and closed again by a real run drops the code-only marks",
              "code_only" not in s6_again and "receipt_id" not in s6_again and "rework" not in s6_again
              and s6_again == {"status": "completed", "reason": "S6 run for real"}
              and "code_only" not in pipeline_stage("S6") and s7_pretriage.s6_closed_by_code(zero_root) is False,
              json.dumps(s6_again))

        # C3-20: the ONE rule for the run marks over every writer of a stage entry (the table above
        # `STAGE_RUN_MARKS`): `set_stage` carries them over completed -> completed, `state_repair` drops them.
        def code_close_s6(tag):
            # The operation door refuses `code_only` on a completed stage ("stage already completed"), so the
            # event is committed through the store, as the C3-14 pins commit `stage_transition`.
            zero.store.commit("code_only", {"id": f"zero-s6-{tag}", "stage": "S6", "reason": f"closed by code {tag}",
                                            "evidence_refs": [evidence_ref(zero_root, f"zero-s6-{tag}.txt")]},
                              f"zero-s6-{tag}", project=zero.project)
            return zero.state()["stages"]["S6"]

        def repair_s6(key, **fix):
            zero.store.commit("state_repair", {"fixes": [dict(kind="stage_completed", stage="S6", reason="recover", **fix)],
                                               "reason": "recover repaired internal state"},
                              key, project=zero.project)
            return zero.state()["stages"]["S6"]

        # (a) a late `accept` with `stage_complete` on the code-closed S6 (a real dispatch, a real receipt).
        before = code_close_s6("a")
        zero.apply("dispatch", {"id": "late-s6", "stage": "S6", "role": "qa-runner", "execution_kind": "automation", "scope": ["TC-1"], "input_hash": "late",
                                "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-late-s6"})
        record_stage_acceptance(zero_root, "S6", "late-s6")         # X7-6c: S6 closes over the consumer's record, never on the author's own finish
        zero.apply("accept", {"id": "late-s6", "status": "accepted", "stage_complete": True,
                              "evidence_refs": [evidence_ref(zero_root, "late-s6.txt")], "idempotency_key": "accept-late-s6"})
        late = zero.state()["stages"]["S6"]
        check("C3-20 (a) accept with stage_complete on the code-closed S6 keeps code_only and the receipt id (the marks "
              "describe the close, not the dispatch id)",
              before.get("code_only") is True and late.get("status") == "completed" and late.get("dispatch_id") == "late-s6"
              and late.get("code_only") is True and late.get("receipt_id") == "zero-s6-a" == before.get("receipt_id"),
              json.dumps(late))
        check("C3-20 (e) and _project_pipeline keeps code_only for it, so the reader S7 asks still says closed by code",
              pipeline_stage("S6").get("code_only") is True and pipeline_stage("S6").get("receipt_id") == "zero-s6-a"
              and pipeline_stage("S6").get("status") == "done" and s7_pretriage.s6_closed_by_code(zero_root) is True,
              json.dumps(pipeline_stage("S6")))

        # (c) state_repair: a repair naming the dispatch that closed the stage re-closes what a ROLE ran.
        repaired = repair_s6("state_repair:c3-20-c1", dispatch_id="late-s6")
        check("C3-20 (c) state_repair naming a dispatch drops the stale code_only, keeps repaired_by_recover",
              repaired.get("status") == "completed" and repaired.get("repaired_by_recover") is True
              and repaired.get("dispatch_id") == "late-s6" and "code_only" not in repaired and "receipt_id" not in repaired,
              json.dumps(repaired))
        # ... and the stale case itself: a reworked code-closed S6 (rework keeps the marks), repaired after a role ran it.
        code_close_s6("c")
        zero.store.commit("stage_transition", {"task": "QA-1", "stage": "S6", "status": "running", "digest": "S6 reworked again"},
                          "stage:zero-s6-running-c", project=zero.project)
        reworked = zero.state()["stages"]["S6"]
        repaired = repair_s6("state_repair:c3-20-c2", dispatch_id="late-s6")
        check("C3-20 (c) state_repair on a reworked code-closed S6 a role ran leaves no stale code_only and no rework",
              reworked.get("rework") is True and reworked.get("code_only") is True
              and repaired.get("repaired_by_recover") is True and "code_only" not in repaired and "receipt_id" not in repaired
              and "rework" not in repaired and "code_only" not in pipeline_stage("S6"),
              json.dumps(repaired))
        # The chosen way for a repair that names NO dispatch (nothing ran): the entry it re-closes keeps its receipt.
        code_close_s6("d")
        repaired = repair_s6("state_repair:c3-20-c3", dispatch_id=None)
        check("C3-20 (c) state_repair naming no dispatch on the code-closed S6 keeps code_only and the receipt id",
              repaired.get("repaired_by_recover") is True and repaired.get("code_only") is True
              and repaired.get("receipt_id") == "zero-s6-d", json.dumps(repaired))
        # a repair on a stage that was never completed is today's entry, whole
        zero.store.commit("state_repair", {"fixes": [{"kind": "stage_completed", "stage": "S9", "dispatch_id": "d9", "reason": "recover"}],
                                           "reason": "recover repaired internal state"}, "state_repair:c3-20-s9", project=zero.project)
        check("C3-20 (c) state_repair on a stage with no entry yet writes the fresh repaired entry",
              zero.state()["stages"]["S9"] == {"status": "completed", "repaired_by_recover": True,
                                               "reason": "recover", "dispatch_id": "d9"},
              json.dumps(zero.state()["stages"]["S9"]))

        # (b) `set_stage` itself, over a hand-built state: which entries are fresh and which carry.
        from controller import set_stage, lower_stage
        marks = {"code_only": True, "receipt_id": "r1", "rerun_after": "rw", "later_work_status": "pending", "later_work_settled": True}
        code_closed = {"status": "completed", "reason": "by code", **marks}
        fresh_running = {"status": "running", "dispatch_id": "d1"}
        state = {"stages": {}}
        set_stage(state, "S6", dict(fresh_running))
        check("C3-20 (b) set_stage on a stage with no entry yet writes the fresh entry", state["stages"]["S6"] == fresh_running)
        state = {"stages": {"S6": dict(code_closed)}}
        lower_stage(state, "S6", "invalidated scope requires fresh acceptance")
        set_stage(state, "S6", dict(fresh_running))
        check("C3-20 (b) a code-closed stage lowered (lower_stage), then running again, is a fresh entry with no marks",
              state["stages"]["S6"] == fresh_running, json.dumps(state["stages"]["S6"]))
        state = {"stages": {"S6": dict(code_closed)}}
        set_stage(state, "S6", dict(fresh_running))
        check("C3-20 (b) set_stage(running) on a COMPLETED code-closed stage is later work: it stays completed, marks kept (as before)",
              state["stages"]["S6"]["status"] == "completed" and state["stages"]["S6"].get("code_only") is True
              and state["stages"]["S6"].get("receipt_id") == "r1" and state["stages"]["S6"].get("later_work_status") == "running",
              json.dumps(state["stages"]["S6"]))
        state = {"stages": {"S6": dict(code_closed, dispatch_id="d0")}}
        set_stage(state, "S6", {"status": "completed", "dispatch_id": "d2", "reason": "again"})
        check("C3-20 (b) completed -> completed with a DIFFERENT dispatch id carries every mark, the rest is the new close",
              state["stages"]["S6"] == {"status": "completed", "dispatch_id": "d2", "reason": "again", **marks},
              json.dumps(state["stages"]["S6"]))
        state = {"stages": {"S6": dict(code_closed, rework=True, rework_status="running")}}
        set_stage(state, "S6", {"status": "completed", "dispatch_id": "d3", "reason": "run for real"})
        check("C3-20 (b) a close after a rework (a real run) is the fresh entry, marks dropped",
              state["stages"]["S6"] == {"status": "completed", "dispatch_id": "d3", "reason": "run for real"},
              json.dumps(state["stages"]["S6"]))
        state = {"stages": {"S6": {"status": "running", "dispatch_id": "d1", "rerun_after": "rw"}}}
        set_stage(state, "S6", {"status": "completed", "dispatch_id": "d1", "reason": ""})
        check("C3-20 (b) a stage that was running (not completed) closes with a fresh entry, rerun_after dropped",
              state["stages"]["S6"] == {"status": "completed", "dispatch_id": "d1", "reason": ""},
              json.dumps(state["stages"]["S6"]))

        legacy_root = root / "legacy"; legacy_root.mkdir()
        (legacy_root / "pipeline.json").write_text(json.dumps({"stages": {"S1": {"status": "done", "digest": "legacy facts"},
                                                                     "S2": {"status": "running", "role": "qa-strategist"}},
                                                                "gates": {"A": {"decision": "approved"}}}), encoding="utf-8")
        legacy = Controller(legacy_root)
        legacy.apply("initialize", {"scope": ["TC-1"], "source_revision": "legacy-r", "known_paths": {"root": str(legacy_root)}, "idempotency_key": "legacy-init"})
        legacy_state = legacy.state()
        check("legacy pipeline imports evidenced done stages and checkpoints an unknown running role",
              legacy_state["stages"]["S1"]["status"] == "completed"
              and legacy.next_action()["action"] == "resume_checkpoint"
              and legacy_state["decisions"]["legacy-gate:A"]["status"] == "stale")

        mutation_root = root / "mutation"; mutation_root.mkdir()
        mutation = Controller(mutation_root)
        mutation.apply("initialize", {"scope": ["TC-1"], "source_revision": "m-r", "known_paths": {"root": str(mutation_root)}, "idempotency_key": "m-init"})
        mutation.apply("dispatch", {"id": "author", "stage": "S0", "role": "qa-automator", "scope": ["TC-1"], "input_hash": "m", "budget": {}, "known_paths": {}, "idempotency_key": "author"})
        base = {"id": "change", "dispatch_id": "author", "paths": ["test.py"], "before_hashes": {"test.py": "before"}, "after_hashes": {"test.py": "after"}}
        mutation.apply("mutation", dict(base, status="planned", idempotency_key="mp"))
        mutation.apply("mutation", dict(base, status="writing", idempotency_key="mw"))
        mutation.apply("mutation", dict(base, status="written", idempotency_key="mwritten"))
        mutation.apply("mutation", dict(base, status="executed", evidence_refs=[evidence_ref(mutation_root, "execute.txt")], idempotency_key="me"))
        mutation.apply("accept", {"id": "author", "status": "accepted", "stage_complete": False, "evidence_refs": [evidence_ref(mutation_root, "author.txt")], "idempotency_key": "author-a"})
        mutation.apply("dispatch", {"id": "critic", "stage": "S0", "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "m", "budget": {}, "known_paths": {}, "idempotency_key": "critic"})
        mutation.apply("mutation", dict(base, status="reviewed", reviewer_dispatch_id="critic", evidence_refs=[evidence_ref(mutation_root, "review.txt")], idempotency_key="mr"))
        check("independent critic can review a checkpointed author mutation without taking ownership",
              mutation.state()["mutations"]["change"].get("reviewer_dispatch_id") == "critic")

        budget_root = root / "budget"; budget_root.mkdir()
        budget = Controller(budget_root)
        budget.apply("initialize", {"scope": ["TC-1"], "source_revision": "budget-r", "known_paths": {"root": str(budget_root)}, "idempotency_key": "budget-init"})
        limited = {"id": "limited", "stage": "S0", "role": "qa-automator", "scope": ["TC-1"], "input_hash": "b", "budget": {}, "known_paths": {}, "limits": {"automator_requests": 1}, "idempotency_key": "limited"}
        budget.apply("dispatch", limited)
        budget.apply("checkpoint", {"id": "limited", "status": "paused", "reason": "limit", "checkpoint": {"remaining": ["TC-1"]}, "counters": {"active_seconds": 0, "requests": 1, "output_tokens": 0, "repair_cycles": 0}, "idempotency_key": "limited-cp"})
        try:
            budget.apply("dispatch", dict(limited, id="fresh", idempotency_key="fresh"))
            cap_enforced = False
        except StateConflict:
            cap_enforced = True
        check("fresh dispatch cannot reset cumulative role request budget", cap_enforced)

        project = root / "project"; task = project / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True); mark_project(project)
        old = hooklib._PROJECT_ROOT_CACHE; hooklib._PROJECT_ROOT_CACHE = project
        try:
            managed = Controller(task)
            managed.apply("initialize", {"scope": ["TC-1"], "source_revision": "x", "known_paths": {"root": str(project)}, "idempotency_key": "i"})
            check("stage_done cannot bypass a managed S5", stage_done.run("QA-1", "S5", "done", "qa-automator", "", True) == stage_done.EXIT_BAD_ARGS)
        finally:
            hooklib._PROJECT_ROOT_CACHE = old
    portable_packets()
    rework_is_built_by_the_package_that_dispatches_it()
    s5_window_is_refused_in_one_list()
    a_case_with_no_instance_needs_the_manifest_row()
    an_empty_case_answers_to_the_scope_key_its_manifest_cell_gives()
    s1_reacceptance_is_judged_by_one_summary()
    controller_chains_are_refused_whole()
    a_respelled_dispatch_is_recorded_and_keyed_as_the_approved_case()
    the_transition_carries_the_agent_onto_the_dispatch()
    the_stage_names_the_agent_of_its_last_bind()
    code_close_conflicts_is_the_one_predicate()
    the_s3_gate_runs_on_every_s3_acceptance()
    for tr4_7 in (test_tr4_7_a_dead_holder_does_not_block_any_site, test_tr4_7_a_live_holder_is_refused_by_name_with_its_door,
                  test_tr4_7_unknown_and_an_unreadable_verdict_keep_the_refusal_and_say_so,
                  test_tr4_7_several_holders_are_each_named_and_a_dead_one_is_left_out,
                  test_tr4_7_no_running_row_means_no_refusal_whatever_a_stage_says,
                  test_tr4_7_apply_records_a_dead_dispatch_once_and_the_operation_goes_on,
                  test_tr4_7_the_s6_close_context_reads_liveness_through_the_same_helper,
                  test_tr4_7_a_writer_between_the_read_and_the_repair_is_not_overwritten,
                  test_tr4_7_an_event_committed_in_between_is_not_let_through_by_the_caller_revision,
                  test_tr4_7_an_admitted_s5_window_never_repairs_a_sibling,
                  test_tr4_7_a_repair_leaves_a_row_that_is_no_longer_running_alone,
                  test_tr4_7_invalidate_reads_liveness_for_the_named_dispatches_only):
        try:
            tr4_7()
            check(tr4_7.__name__, True)
        except AssertionError as exc:
            check(tr4_7.__name__, False, str(exc)[:400])
    print(f"=== test_controller_state: {CHECKS - FAILS}/{CHECKS} ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
