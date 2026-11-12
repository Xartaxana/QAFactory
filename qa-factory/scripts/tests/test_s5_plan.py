#!/usr/bin/env python3
"""SC1-14 A1a: the record kind of an S5 dispatch, the plan's words, and the plan's reader, skeleton, hash, form and stamp.

One plan for every case of S5 is written before any window (the owner's form, 25.10.2026). This file holds the foundations the
later parts stand on: `controller.s5_part_of` (plan | window - read from the binding, never from the top of a record),
`handoffs/vocabulary.yaml` (the plan's words, read by `manifest_from_tests.SHAPES`), and `scripts/s5_plan.py` (`load`, `init`,
`rows_sha`, `mode`, `stamp_review`). Every key names the mutation it kills (spec t-1246 section 5, A1a).
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, cleanup, finish, mark_project, s5_plan_ready, temp_dir,  # noqa: E402
                     temp_project)

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402
import handoff  # noqa: E402
import manifest_from_tests as MFT  # noqa: E402
import s5_plan as SP  # noqa: E402
from controller import Controller  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
from test_controller_rework_scope import evidence, plan_row  # noqa: E402

CASE_TEXT = """---
id: {case}
status: Draft
task: QA-1
---
Requirements: R-1, R-2
Plan row: {row}
# {case} title
## Then
1. The first outcome holds.
2. The second   outcome holds.
"""


# --- the kind of a record: s5_part_of -------------------------------------------------------------------

def record(binding=None, stage="S5", **top):
    item = {"id": "d", "stage": stage, "role": "qa-automator", "status": "accepted"}
    if binding is not None:
        item["request_binding"] = binding
    item.update(top)
    return item


def k1_the_kind_of_a_record():
    plan = {"purpose": CT.S5_PLAN}
    check_eq("K1: the word in the binding of an S5 record is a plan", CT.s5_part_of(record(plan)), "plan")
    check_eq("K1: another purpose in the binding is a window", CT.s5_part_of(record({"purpose": "repair_verify"})), "window")
    check_eq("K1: no purpose in the binding is a window", CT.s5_part_of(record({"reason": "x"})), "window")
    # M1: the top of a record is never read when the record HAS a binding ("top of record is never read")
    check_eq("K1: top of record is never read - the binding has no purpose, the top says s5_plan",
             CT.s5_part_of(record({"reason": "x"}, purpose=CT.S5_PLAN)), "window")
    check_eq("K1: top of record is never read - the binding says repair_verify, the top says s5_plan",
             CT.s5_part_of(record({"purpose": "repair_verify"}, purpose=CT.S5_PLAN)), "window")
    check_eq("K1: top of record is never read - the binding says s5_plan, the top was overwritten",
             CT.s5_part_of(record(plan, purpose="accepted")), "plan")
    for label, binding in (("a list", ["s5_plan"]), ("a string", "s5_plan"), ("None", None), ("a number", 5)):
        item = record(purpose=CT.S5_PLAN)
        item["request_binding"] = binding
        check_eq(f"K1: a binding that is {label} reads as a window, whatever the top says", CT.s5_part_of(item), "window")
    # a request (not yet a record) carries the word on its own key, and request_binding() builds the binding from that key
    check_eq("K1: a request without a binding with purpose s5_plan is a plan",
             CT.s5_part_of({"stage": "S5", "purpose": CT.S5_PLAN}), "plan")
    check_eq("K1: the binding request_binding() builds from that request agrees with it",
             CT.s5_part_of({"stage": "S5", "request_binding": CT.request_binding({"purpose": CT.S5_PLAN})}), "plan")
    check_eq("K1: an imported record without a binding and with the top word is a plan (cannot be older than 0.10.3)",
             CT.s5_part_of(record(purpose=CT.S5_PLAN)), "plan")
    for label, item in (("stage S4", record({"purpose": CT.S5_PLAN}, stage="S4")),
                        ("stage 'S5 ' with a blank", record({"purpose": CT.S5_PLAN}, stage="S5 ")),
                        ("stage s5 in lower case", record({"purpose": CT.S5_PLAN}, stage="s5")),
                        ("no stage", {"request_binding": {"purpose": CT.S5_PLAN}}),
                        ("stage None", record({"purpose": CT.S5_PLAN}, stage=None)),
                        ("not a dict: a string", "s5_plan"), ("not a dict: None", None), ("not a dict: a list", [record()]),
                        ("not a dict: a number", 7)):
        check_eq(f"K1: {label} reads as a window", CT.s5_part_of(item), "window")
    check_in("K1: the closed set of purposes holds the word", CT.S5_PLAN, sorted(CT.PURPOSES))
    check_eq("K1: the word is s5_plan", CT.S5_PLAN, "s5_plan")


def k1b_the_kind_of_a_record_the_controller_writes():
    root = temp_dir("qa-s5plan-kind-")
    try:
        c = s5_story(root, with_case_files=True)
        # SC1-14 B1b: the plan is a real one (the author's dispatch with the word, the critic's), the plan order is what lets the window in
        s5_plan_ready(c, root, ["TC-1", "TC-2"], ids=("S5-qa-automator-1", "S5-qa-code-critic-1"))
        for identifier, extra in (("S5-qa-automator-2", {}),):
            c.apply("dispatch", dict({"id": identifier, "stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2"],
                                      "input_hash": "h", "budget": {}, "known_paths": {}, "idempotency_key": identifier}, **extra))
            # dispatches of a sequential task are one at a time: the first is accepted mid-flight before the second starts
            c.apply("accept", {"id": identifier, "status": "accepted", "stage_complete": False, "unresolved": True,
                               "reason": "the stage's windows are still open", "evidence_refs": [evidence(root, identifier + ".txt")],
                               "idempotency_key": identifier + "-ok"})
        records = c.state()["dispatches"]
        check_eq("K1b: a dispatch the controller wrote with purpose s5_plan is a plan",
                 CT.s5_part_of(records["S5-qa-automator-1"]), "plan")
        check_eq("K1b: a dispatch the controller wrote without it is a window", CT.s5_part_of(records["S5-qa-automator-2"]), "window")
        check_eq("K1b: the binding of the record carries the word", records["S5-qa-automator-1"]["request_binding"]["purpose"], "s5_plan")
    finally:
        cleanup(root)


# --- the plan's words ----------------------------------------------------------------------------------

def k2_the_words():
    vocabulary = handoff.vocabulary()
    check_eq("K2: test_shapes", vocabulary.get("test_shapes"), ["reuse", "extend", "parameterize", "consolidate", "new"])
    check_eq("K2: fit_to_shapes", vocabulary.get("fit_to_shapes"),
             {"extend": ["extend", "reuse", "consolidate"], "param": ["parameterize", "consolidate"],
              "new": ["new", "parameterize", "consolidate"]})      # t-1502 G-2: new cases with the same setup and action may be one parameterized test
    check_eq("K2: plan_verdicts", vocabulary.get("plan_verdicts"), ["approved", "approved_with_remarks", "blocked"])
    check_eq("K2: plan_remark_kinds", vocabulary.get("plan_remark_kinds"), ["blocker", "remark"])
    check_eq("K2: plan_remark_rows", vocabulary.get("plan_remark_rows"), ["applied", "not_applicable"])
    check_eq("K2: data_strategies", vocabulary.get("data_strategies"), ["own", "run_tag", "seeded"])
    check_eq("K2: plan_deviation_kinds", vocabulary.get("plan_deviation_kinds"),
             ["file", "function", "shape", "level", "count", "fixture", "remainder"])
    # the `fit` words of the S3 plan row are the ones artifact-contract-plan.md names: `extend <test>` | `param <test>` | `new`
    check_eq("K2: fit_to_shapes is keyed by the three fit words of the S3 row", sorted(vocabulary["fit_to_shapes"]),
             ["extend", "new", "param"])
    check("K2: every shape a fit word allows is a shape",
          all(set(shapes) <= set(vocabulary["test_shapes"]) for shapes in vocabulary["fit_to_shapes"].values()))


def k3_shapes_never_diverge():
    vocabulary = handoff.vocabulary()
    # M-never-diverge: the literal fallback, the generator's list and the vocabulary are one list
    check_eq("K3: SHAPES (never diverge) == the vocabulary's test_shapes", list(MFT.SHAPES), vocabulary["test_shapes"])
    check_eq("K3: the offline fallback == the vocabulary's test_shapes", list(MFT.SHAPES_FALLBACK), vocabulary["test_shapes"])
    real = handoff.vocabulary

    def broken():
        raise OSError("handoffs/vocabulary.yaml is not there")
    handoff.vocabulary = broken
    try:
        check_eq("K3: a vocabulary that cannot be read leaves no word, so the fallback stands", MFT._vocabulary_shapes(), ())
    finally:
        handoff.vocabulary = real
    check_eq("K3: a readable vocabulary gives its list", list(MFT._vocabulary_shapes()), vocabulary["test_shapes"])


# --- load ----------------------------------------------------------------------------------------------

def put(root, rel, content):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def refusal(call):
    try:
        call()
    except SP.PlanUnreadable as exc:
        return str(exc)
    return ""


def k4_load():
    root = temp_dir("qa-s5plan-load-")
    try:
        check_eq("K4: no file is None, not a refusal", SP.load(root), None)
        put(root, SP.PLAN_REL, b"")
        check_in("K4: an empty file is unreadable and names the file and a door", SP.PLAN_REL, refusal(lambda: SP.load(root)))
        check_in("K4: the refusal names the door", "--init", refusal(lambda: SP.load(root)))
        for label, content in (("not JSON", b"{not json"), ("a list", b"[1, 2]"), ("a number", b"7"), ("null", b"null"),
                               ("an object without schema", b'{"cases": []}'), ("schema beyond (2)", b'{"schema": 2}'),
                               ("schema below (0)", b'{"schema": 0}'), ("schema true", b'{"schema": true}'),
                               ("schema a string", b'{"schema": "1"}'), ("not UTF-8", b'{"schema": 1, "x": "\xff\xfe"}')):
            put(root, SP.PLAN_REL, content)
            check(f"K4: {label} is PlanUnreadable", bool(refusal(lambda: SP.load(root))))
        put(root, SP.PLAN_REL, b'\xef\xbb\xbf{"schema": 1, "cases": []}')
        check_eq("K4: schema 1 at the boundary reads (a BOM is encoding)", SP.load(root), {"schema": 1, "cases": []})
        (root / SP.PLAN_REL).unlink()
        (root / SP.PLAN_REL).mkdir()
        check("K4: a directory in its place is PlanUnreadable, not None", bool(refusal(lambda: SP.load(root))))
    finally:
        cleanup(root)


# --- rows_sha ------------------------------------------------------------------------------------------

def sample_plan():
    return {"schema": 1,
            "cases": [{"case": "TC-1", "thens": [{"n": 1, "text": "a"}], "remainders": []},
                      {"case": "TC-2", "thens": [{"n": 1, "text": "b"}], "remainders": []},
                      {"case": "TC-3", "thens": [{"n": 1, "text": "c"}], "remainders": []}],
            "tests": [{"id": "T-1", "file": "tests/test_a.py", "function": "test_a", "cases": ["TC-1", "TC-2"], "shape": "new"},
                      {"id": "T-2", "file": "tests/test_b.py", "function": "test_b", "cases": ["TC-3"], "shape": "new"}]}


def k5_rows_sha():
    plan = sample_plan()
    before = SP.rows_sha(plan)
    check_eq("K5: one hash per case", sorted(before), ["TC-1", "TC-2", "TC-3"])
    plan["tests"][0]["function"] = "test_a_changed"
    after = SP.rows_sha(plan)
    check("K5: a change to a test over two cases changes the hash of BOTH cases", after["TC-1"] != before["TC-1"] and after["TC-2"] != before["TC-2"])
    check_eq("K5: and not the hash of a case the test does not touch", after["TC-3"], before["TC-3"])
    plan = sample_plan()
    plan["cases"][2]["remainders"] = [{"then": 1, "reason": "impossible", "detail": "x"}]
    changed = SP.rows_sha(plan)
    check("K5: a change to a case's own row changes its hash only",
          changed["TC-3"] != before["TC-3"] and changed["TC-1"] == before["TC-1"] and changed["TC-2"] == before["TC-2"])
    plan = sample_plan()
    plan["tests"].reverse()
    check_eq("K5: the order of tests[] is no change", SP.rows_sha(plan), before)
    plan = sample_plan()
    plan["tests"][0]["cases"] = ["TC-1"]
    check("K5: a test dropped from a case changes that case's hash", SP.rows_sha(plan)["TC-2"] != before["TC-2"])
    plan = sample_plan()
    plan["cases"].append({"thens": []})
    plan["cases"].append("not a row")
    plan["tests"].append("not a row")
    check_eq("K5: rows that are not rows of a case are skipped, nothing raises", SP.rows_sha(plan), before)
    check_eq("K5: no cases, no hashes", SP.rows_sha({"schema": 1}), {})
    check_eq("K5: cases that are not a list, no hashes", SP.rows_sha({"schema": 1, "cases": "x", "tests": 5}), {})


# --- mode ----------------------------------------------------------------------------------------------

def s5(identifier, status="accepted", binding=None, **top):
    return dict({"id": identifier, "stage": "S5", "role": "qa-automator", "status": status,
                 "request_binding": binding if binding is not None else {}}, **top)


def plan_record(identifier="P", status="accepted"):
    return s5(identifier, status, {"purpose": CT.S5_PLAN})


def state_of(*records, **extra):
    return dict({"dispatches": {r["id"]: r for r in records}}, **extra)


def k6_mode():
    root = temp_dir("qa-s5plan-mode-")
    try:
        def m(*records, run_mode="desktop"):
            return SP.mode(root, state_of(*records), run_mode)[0]

        # M4: empty dispatches -> planned (a plan is owed); only the driver process keeps the earlier form
        check_eq("K6 (E21): empty dispatches -> planned", m(), "planned")
        check_eq("K6 (E21): no `dispatches` key at all -> planned", SP.mode(root, {})[0], "planned")
        check_eq("K6 (E21): `dispatches` null -> planned", SP.mode(root, {"dispatches": None})[0], "planned")
        check_eq("K6 (E21): empty dispatches + the driver process -> legacy", m(run_mode="driver"), "legacy")
        check_eq("K6 (E21): only plan records -> planned", m(plan_record()), "planned")
        check_eq("K6 (E21): plan + window records -> planned", m(plan_record(), s5("W1")), "planned")
        check_eq("K6 (E21): a live window and no plan -> legacy", m(s5("W1")), "legacy")
        check_eq("K6 (E21): a live window of any live status (running) -> legacy", m(s5("W1", "running")), "legacy")
        check_eq("K6 (E21): a live window of the driver process is still legacy, the record decides", m(s5("W1"), run_mode="driver"), "legacy")
        check_eq("K6 (E21): a plan record wins over the driver process (the form is fixed by the first dispatch)",
                 m(plan_record(), run_mode="driver"), "planned")
        for status in sorted(CT.DISCOUNTED):
            check_eq(f"K6 (E21): a plan record in status {status} still fixes planned", m(plan_record(status=status)), "planned")
        # M4c: every S5 record stale after a rework of S3 is a new life: no live window -> planned
        check_eq("K6 (E21, new life): every S5 record stale (plan and window) -> planned",
                 m(plan_record(status="stale"), s5("W1", "stale")), "planned")
        check_eq("K6 (E21, new life): only stale windows -> planned", m(s5("W1", "stale"), s5("W2", "superseded")), "planned")
        check_eq("K6 (E21, new life): a stale window beside a live one is still legacy", m(s5("W1", "stale"), s5("W2")), "legacy")
        # the plan word on the TOP of a window record only: that is a window, so legacy; with a plan beside it, planned
        crooked = s5("W1", binding={"reason": "x"}, purpose=CT.S5_PLAN)
        check_eq("K6 (E21): s5_plan on the top of a window record only -> that is a window -> legacy", m(crooked), "legacy")
        check_eq("K6 (E21): ... and with a real plan record beside it -> planned", m(crooked, plan_record()), "planned")
        check_eq("K6 (E21): other stages are not S5 records", m({"id": "S3", "stage": "S3", "status": "accepted",
                                                               "request_binding": {"purpose": CT.S5_PLAN}}), "planned")
        check_eq("K6 (E21): a record that is not a mapping is no S5 record", SP.mode(root, {"dispatches": {"x": "junk"}})[0], "planned")
        # M4b: the stamp pipeline.run_mode is not read
        check_eq("K6 (E37): the stamp is not read - an object stamp saying driver changes nothing",
                 SP.mode(root, dict(state_of(), pipeline={"run_mode": {"mode": "driver"}}))[0], "planned")
        check_eq("K6 (E37): the stamp is not read - a stamp saying desktop does not make a driver planned",
                 SP.mode(root, dict(state_of(), pipeline={"run_mode": {"mode": "desktop"}}), "driver")[0], "legacy")
        # M4a: a plan record, no file: still planned, and the reason says so
        mode_name, why = SP.mode(root, state_of(plan_record()))
        check_eq("K6 (E21): plan record, no file -> planned", mode_name, "planned")
        check_in("K6 (E21): plan record, no file - the reason says it", "plan record, no file", why)
        put(root, SP.PLAN_REL, '{"schema": 1}')
        check("K6 (E21): with the file there the reason does not say 'no file'", "no file" not in SP.mode(root, state_of(plan_record()))[1])
        # an unreadable state is an exception, never legacy
        for label, state in (("None", None), ("a list", []), ("a string", "x"), ("dispatches a list", {"dispatches": [plan_record()]}),
                             ("dispatches a string", {"dispatches": "x"})):
            check(f"K6 (E21): an unreadable state ({label}) raises PlanUnreadable", bool(refusal(lambda s=state: SP.mode(root, s))))
        check("K6 (E21): every answer carries a reason", all(SP.mode(root, s)[1] for s in (state_of(), state_of(s5("W")), state_of(plan_record()))))
    finally:
        cleanup(root)


# --- a story on disk: init and the stamp ----------------------------------------------------------------

def s5_story(root, cases=("TC-1", "TC-2"), with_case_files=False, plan_extra=None, mark=True):
    """A real controller task accepted through S0..S4 with an approved plan of `automate` rows (the shape of test_s5_process).
    `mark=False` when the task already lies inside a marked project (the CLI key)."""
    if mark:
        mark_project(root)
    c = Controller(root)
    c.apply("initialize", {"scope": list(cases), "source_revision": "src-1",
                           "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    rows = []
    for index, case in enumerate(cases, start=1):
        row = plan_row(index, "automate")
        row["required_scenarios"] = [case]
        row["level"] = "api"
        row.update((plan_extra or {}).get(case, {}))
        rows.append(row)
    BASE.seed_plan(root, rows)
    links = []
    for index, case in enumerate(cases, start=1):
        link = {"case_id": case, "version": f"cv_{index}"}
        if with_case_files:
            link["path"] = f"state/cases/{case}.md"
            put(root, link["path"], CASE_TEXT.format(case=case, row=f"TS-{index}"))
        links.append(link)
    put(root, "state/story-case-links.json", json.dumps({"links": links}))
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                "authorization_source": "human", "source_revision": "src-1", "scope": list(cases),
                "input_revision": "src-1", "idempotency_key": "gate-a"}
    BASE.word_for_open_items(root)       # RH1-6: the rehearsal's one open item has the person's word, so this fixture's decision records
    c.apply("decision", BASE.bind_gate_a(root, decision))
    return c


def k7_init():
    root = temp_dir("qa-s5plan-init-")
    try:
        extra = {"TC-1": {"fit": "extend tests/test_x.py::test_x", "oracle": "requirement:R-1", "requirements": ["R-1", "R-2"]},
                 "TC-2": {"fit": "new"}}
        c = s5_story(root, with_case_files=True, plan_extra=extra)
        plan = SP.init(root, c)
        check_eq("K7: the skeleton is the file on disk", SP.load(root), plan)
        check_eq("K7: schema 1", plan["schema"], 1)
        check_eq("K7: one row per case of the scope, in scope order", [row["case"] for row in plan["cases"]], ["TC-1", "TC-2"])
        first, second = plan["cases"]
        check_eq("init writes no window: the plan holds none, the controller cuts them from the tests", ["window" in row for row in plan["cases"]],
                 [False, False])
        check_eq("init writes no window: a row has the keys of the skeleton and no more",
                 sorted(first), ["case", "remainders", "requirements", "s3", "thens"])
        check_eq("K7: the S3 row, level, fit and oracle are carried",
                 first["s3"], {"row": "TS-1", "level": "api", "fit": "extend tests/test_x.py::test_x", "oracle": "requirement:R-1"})
        check_eq("K7: what S3 did not say is null, not an empty string",
                 second["s3"], {"row": "TS-2", "level": "api", "fit": "new", "oracle": None})
        check_eq("K7: the requirements the S3 row names", first["requirements"], ["R-1", "R-2"])
        check_eq("K7: a row that names none -> []", second["requirements"], [])
        check_eq("K7: the Then clauses of the case file, whitespace folded",
                 first["thens"], [{"n": 1, "text": "The first outcome holds."}, {"n": 2, "text": "The second outcome holds."}])
        check_eq("K7: remainders start empty", first["remainders"], [])
        check_eq("K7: the places only the author fills are empty", (plan["tests"], plan["fixtures"], plan["refactor"]), ([], [], ""))
        check_eq("K7: gate_a_plan_hash is the plan hash gate-inputs gives", plan["gate_a_plan_hash"], c.gate_inputs()["plan_content_hash"])
        check("K7: scope_hash is a hash", len(plan["scope_hash"]) == 64)

        # M2: equal hashes -> NOT overwritten ("init keeps")
        written = SP.load(root)
        written["tests"] = [{"id": "T-1", "file": "tests/t.py", "function": "test_t", "cases": ["TC-1"], "thens": ["TC-1#1"]}]
        put(root, SP.PLAN_REL, json.dumps(written))
        kept = SP.init(root, c)
        check_eq("K7 (M2): init keeps the author's plan on the same cases and plan", kept, written)
        check_eq("K7 (M2): init keeps - the file is the author's bytes", SP.load(root), written)
        check("K7 (M2): and nothing was moved aside", not (root / SP.PREV_REL).exists())

        # M3: another scope_hash -> the old file goes to .prev, a new skeleton is written (E38)
        changed = dict(written, scope_hash="0" * 64)
        put(root, SP.PLAN_REL, json.dumps(changed))
        old_bytes = (root / SP.PLAN_REL).read_bytes()
        fresh = SP.init(root, c)
        check_eq("K7 (M3, E38): another scope_hash -> a new skeleton", fresh["tests"], [])
        check_eq("K7 (M3, E38): the old plan is in .prev, byte for byte", (root / SP.PREV_REL).read_bytes(), old_bytes)
        check_eq("K7 (M3, E38): the new skeleton is on disk", SP.load(root), fresh)
        # ... and another gate_a_plan_hash does the same, replacing the previous .prev
        again = dict(fresh, gate_a_plan_hash="f" * 64, refactor="mine")
        put(root, SP.PLAN_REL, json.dumps(again))
        second_old = (root / SP.PLAN_REL).read_bytes()
        SP.init(root, c)
        check_eq("K7 (E38): another gate_a_plan_hash -> .prev is replaced by the newer old plan", (root / SP.PREV_REL).read_bytes(), second_old)
        # a plan with neither hash is another plan
        put(root, SP.PLAN_REL, '{"schema": 1}')
        SP.init(root, c)
        check_eq("K7 (E38): a plan that carries no hashes is another plan", json.loads((root / SP.PREV_REL).read_text(encoding="utf-8")), {"schema": 1})

        # an unreadable plan is touched by nothing and refused
        put(root, SP.PLAN_REL, b"{half a plan")
        prev_before = (root / SP.PREV_REL).read_bytes()
        message = refusal(lambda: SP.init(root, c))
        check_in("K7: an unreadable plan is refused with a door", "--init", message)
        check_eq("K7: and left where it is", (root / SP.PLAN_REL).read_bytes(), b"{half a plan")
        check_eq("K7: and .prev is untouched", (root / SP.PREV_REL).read_bytes(), prev_before)

        # no tmp litter of the atomic writer
        check_eq("K7: no temporary file is left in work/", sorted(p.name for p in (root / "work").glob("*.tmp")), [])
    finally:
        cleanup(root)


def k7b_init_without_case_files():
    root = temp_dir("qa-s5plan-nocase-")
    try:
        c = s5_story(root)
        plan = SP.init(root, c)
        first = plan["cases"][0]
        check_eq("K7b: no case file -> no Then clause (check reports it; init invents none)", first["thens"], [])
        check_eq("K7b: the pin outlives the missing file - scope_hash is of (case, version) pairs",
                 plan["scope_hash"], SP.content_hash([["TC-1", "cv_1"], ["TC-2", "cv_2"]]))
        (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [{"case_id": "TC-1"}, {"case_id": "TC-2"}]}), encoding="utf-8")
        check_eq("K7b: no pin -> the version is the empty string", SP.init(root, c)["scope_hash"], SP.load(root)["scope_hash"])
        check("K7b: ... and that is another scope than the pinned one (the old plan went to .prev)", (root / SP.PREV_REL).exists())
        check_eq("K7b: ... computed from empty versions", SP.load(root)["scope_hash"], SP.content_hash([["TC-1", ""], ["TC-2", ""]]))
    finally:
        cleanup(root)


class FakeController:
    """The four things `init` asks a controller; the scope and the plan hash are the test's."""

    def __init__(self, scope, derived=True, reason="", gate=None):
        self._scope, self._derived, self._reason, self._gate = scope, derived, reason, gate

    def state(self):
        return {}

    def stage_scope(self, stage, state=None):
        return {"stage": stage, "scope": list(self._scope), "derived": self._derived, "reason": self._reason,
                "windows": [{"index": 1, "scope": list(self._scope)}] if self._scope else []}

    def _case_rows(self, state):
        return {c: f"TS-{n}" for n, c in enumerate(self._scope, 1)}, {}, "case_index"

    def _plan_rows(self):
        return [{"id": f"TS-{n}", "level": "api", "fit": "new", "oracle": "requirement:R-1", "requirements": ["R-1"]}
                for n, _ in enumerate(self._scope, 1)]

    def gate_inputs(self):
        if self._gate is None:
            raise ValueError("sources pending/invalid")
        return {"plan_content_hash": self._gate}


def k8_init_edges():
    root = temp_dir("qa-s5plan-edges-")
    try:
        empty = SP.init(root, FakeController([]))
        check_eq("K8 (E7): an empty scope has no cases", empty["cases"], [])
        check("K8 (E7): and no file is written - there is no plan", not (root / SP.PLAN_REL).exists())
        check_in("K8 (AR-28): a scope that cannot be derived is refused, not read as empty", "cannot be derived",
                 refusal(lambda: SP.init(root, FakeController([], derived=False, reason="plan rows declare no disposition"))))
        check("K8: ... and nothing is written for it either", not (root / SP.PLAN_REL).exists())
        plan = SP.init(root, FakeController(["TC-9"], gate=None))
        check_eq("K8: gate-inputs that cannot be read -> '' (B1b reads it as 'not checked' and refuses)", plan["gate_a_plan_hash"], "")
        kept = SP.init(root, FakeController(["TC-9"], gate="abc"))
        check_eq("K8: a plan hash that appears later is another plan - the '' one went to .prev", kept["gate_a_plan_hash"], "abc")
        check("K8: ... and .prev holds it", json.loads((root / SP.PREV_REL).read_text(encoding="utf-8"))["gate_a_plan_hash"] == "")
        check("K8: init writes no window, whatever the controller's cut says", "window" not in SP.load(root)["cases"][0])
    finally:
        cleanup(root)


# --- stamp_review --------------------------------------------------------------------------------------

def k9_stamp_review():
    root = temp_dir("qa-s5plan-stamp-")
    try:
        check_in("K9: no plan, no stamp - the refusal names the door", "--init", refusal(lambda: SP.stamp_review(root, "S5-qa-code-critic-1")))
        check("K9: ... and no receipt file is created", not (root / SP.REVIEWS_REL).exists())
        put(root, SP.PLAN_REL, json.dumps(sample_plan()))
        first = SP.stamp_review(root, "S5-qa-code-critic-1")
        check_eq("K9: plan_sha256 is the sha of the file's bytes", first["plan_sha256"], hashlib.sha256((root / SP.PLAN_REL).read_bytes()).hexdigest())
        check_eq("K9: rows_sha is the plan's per-case hashes", first["rows_sha"], SP.rows_sha(sample_plan()))
        check_eq("K9: the line has exactly dispatch, plan_sha256, rows_sha, tests", sorted(first),
                 ["dispatch", "plan_sha256", "rows_sha", "tests"])
        check_eq("K9 (t-1320 F-2): `tests` is the test -> cases map the critic saw", first["tests"],
                 {"T-1": ["TC-1", "TC-2"], "T-2": ["TC-3"]})
        check_eq("K9: the receipt file is a list of that line", json.loads((root / SP.REVIEWS_REL).read_text(encoding="utf-8")), [first])
        changed = sample_plan()
        changed["tests"][1]["function"] = "test_b2"
        put(root, SP.PLAN_REL, json.dumps(changed))
        second = SP.stamp_review(root, "S5-qa-code-critic-2")
        chain = json.loads((root / SP.REVIEWS_REL).read_text(encoding="utf-8"))
        check_eq("K9: another dispatch appends - the chain keeps the first line", [row["dispatch"] for row in chain],
                 ["S5-qa-code-critic-1", "S5-qa-code-critic-2"])
        check("K9: the two stamps are of different bytes", first["plan_sha256"] != second["plan_sha256"])
        put(root, SP.PLAN_REL, json.dumps(sample_plan()))
        third = SP.stamp_review(root, "S5-qa-code-critic-2")
        chain = json.loads((root / SP.REVIEWS_REL).read_text(encoding="utf-8"))
        check_eq("K9: the same dispatch REPLACES its line, the others stay", [row["dispatch"] for row in chain],
                 ["S5-qa-code-critic-1", "S5-qa-code-critic-2"])
        check_eq("K9: ... and the replacing line is the new one", chain[1], third)
        check_eq("K9: ... the kept line is untouched", chain[0], first)
        for bad in ("", "  ", None):
            try:
                SP.stamp_review(root, bad)
                raised = False
            except ValueError:
                raised = True
            check(f"K9: a dispatch id {bad!r} is a request fault (ValueError)", raised)
        # a receipt file that is not a list is never rewritten over
        for label, content in (("a dict", b'{"dispatch": "x"}'), ("broken", b"[{"), ("empty", b"")):
            put(root, SP.REVIEWS_REL, content)
            check(f"K9: a receipt file that is {label} is refused", bool(refusal(lambda: SP.stamp_review(root, "S5-qa-code-critic-3"))))
            check_eq(f"K9: ... and left as it was ({label})", (root / SP.REVIEWS_REL).read_bytes(), content)
        (root / SP.PLAN_REL).write_bytes(b"{broken")
        put(root, SP.REVIEWS_REL, "[]")
        check("K9: an unreadable plan is refused, not stamped", bool(refusal(lambda: SP.stamp_review(root, "S5-qa-code-critic-4"))))
        check_eq("K9: no temporary file is left in work/", sorted(p.name for p in (root / "work").glob("*.tmp")), [])
    finally:
        cleanup(root)


# --- the command line ----------------------------------------------------------------------------------

def k10_cli():
    project = temp_project("qa-s5plan-cli-")
    try:
        task = project / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True)
        put(task, "pipeline.json", json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}))
        s5_story(task, with_case_files=True, mark=False)
        env = {**os.environ,"CLAUDE_PROJECT_DIR": str(project), "PYTHONDONTWRITEBYTECODE": "1"}

        def run(*args):
            return subprocess.run([sys.executable, "-B", str(SCRIPTS / "s5_plan.py"), *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=env, cwd=str(project), timeout=300)

        done = run("--task", "QA-1", "--mode")
        check_eq("K10: --mode exits 0", done.returncode, 0)
        answer = json.loads(done.stdout)
        check_eq("K10: --mode answers planned for a story with no S5 dispatch (the default process)", answer["mode"], "planned")
        check_eq("K10: stdout is the JSON line and nothing else (FR-14)", done.stdout.strip().count("\n"), 0)
        done = run("--task", "QA-1", "--init")
        check_eq("K10: --init exits 0", done.returncode, 0)
        answer = json.loads(done.stdout)
        check_eq("K10: --init names the file and counts the cases", (answer["path"], answer["cases"]), ("work/s5-plan.json", 2))
        check("K10: the skeleton is on disk", (task / "work" / "s5-plan.json").is_file())
        put(task, SP.PLAN_REL, b"{half")
        refused = run("--task", "QA-1", "--init")
        check_eq("K10: an unreadable plan is exit 2 (a refusal, not a traceback)", refused.returncode, 2)
        check_in("K10: ... with the door on stderr", "--init", refused.stderr)
        check("K10: ... and no traceback", "Traceback" not in refused.stderr)
        check_eq("K10: --init and --mode together are refused by the parser", run("--task", "QA-1", "--init", "--mode").returncode, 2)
        check_eq("K10: neither is refused by the parser", run("--task", "QA-1").returncode, 2)
        check_eq("K10: an unknown ticket is a refusal", run("--task", "NOPE-9", "--mode").returncode, 2)
    finally:
        cleanup(project)


# --- the chain fix round (t-1340): refresh (F13) and the blocker's cases (t-1320 F-2) ----------------------------------------

def k11_refresh():
    """`refresh` is the rework of a plan whose scope grew: rows kept, new rows added, both hashes current, never `.prev`.
    KILLS: M-R1 `refresh` that is `init` (old plan to .prev, the author's tests lost); M-R2 a rewrite on an unchanged plan; M-R3 a
    refresh that drops the rows of cases that left the scope."""
    root = temp_dir("qa-s5plan-refresh-")
    try:
        fake = FakeController(["TC-1"], gate="g1")
        SP.init(root, fake)
        written = SP.load(root)
        written["tests"] = [{"id": "T-1", "file": "tests/t.py", "function": "test_t", "cases": ["TC-1"], "thens": ["TC-1#1"]}]
        written["refactor"] = "mine"
        put(root, SP.PLAN_REL, json.dumps(written, indent=4))       # the author's own formatting
        before = (root / SP.PLAN_REL).read_bytes()
        check_eq("refresh on an unchanged plan returns it", SP.refresh(root, fake), written)
        check_eq("refresh on an unchanged plan is a no-op: the bytes are the author's (the critic's receipt measured them)",
                 (root / SP.PLAN_REL).read_bytes(), before)

        grown = FakeController(["TC-1", "TC-2"], gate="g2")
        plan = SP.refresh(root, grown)
        check_eq("refresh: the author's rows come first, the new case's skeleton row is added",
                 [row["case"] for row in plan["cases"]], ["TC-1", "TC-2"])
        check_eq("refresh: the old row is the author's, untouched", plan["cases"][0], written["cases"][0])
        check_eq("refresh: the new row is the skeleton's", plan["cases"][1], SP._skeleton(root, grown, "x")["cases"][1])
        check_eq("refresh keeps the author's tests and adds the new case: tests and refactor are kept",
                 (plan["tests"], plan["refactor"], [row["case"] for row in plan["cases"]]), (written["tests"], "mine", ["TC-1", "TC-2"]))
        check_eq("refresh refreshes both hashes: the current ones", (plan["scope_hash"], plan["gate_a_plan_hash"]),
                 (SP.current_hashes(root, grown)[0], "g2"))
        check_eq("refresh: what it returns is on disk", SP.load(root), plan)
        check("refresh never moves the plan to .prev (E38 is init's)", not (root / SP.PREV_REL).exists())
        check_eq("refresh again on the same scope is a no-op", SP.refresh(root, grown), plan)

        shrunk = FakeController(["TC-2"], gate="g2")
        gone = SP.refresh(root, shrunk)
        check_eq("refresh: the row of a case that left the scope STAYS (`check` names it, the author decides)",
                 [row["case"] for row in gone["cases"]], ["TC-1", "TC-2"])
        check_eq("refresh: ... and the hash is the smaller scope's", gone["scope_hash"], SP.current_hashes(root, shrunk)[0])
        check("refresh: still no .prev", not (root / SP.PREV_REL).exists())
        check_eq("refresh: an empty scope owes no plan - nothing is written", SP.refresh(root, FakeController([])), gone)
        check_in("refresh (AR-28): a scope that cannot be derived is refused", "cannot be derived",
                 refusal(lambda: SP.refresh(root, FakeController([], derived=False, reason="no disposition"))))
        kept = (root / SP.PLAN_REL).read_bytes()

        put(root, SP.PLAN_REL, json.dumps(dict(gone, cases="not a list")))
        message = refusal(lambda: SP.refresh(root, grown))
        check_in("refresh: a plan with no `cases` list is refused with the door", "no `cases` list", message)
        put(root, SP.PLAN_REL, b"{half a plan")
        check_in("refresh on an unreadable plan refuses", "cannot be read", refusal(lambda: SP.refresh(root, grown)))
        check_eq("refresh on an unreadable plan refuses: ... and leaves it where it is, never moved to .prev",
                 ((root / SP.PLAN_REL).read_bytes(), (root / SP.PREV_REL).exists()), (b"{half a plan", False))
        (root / SP.PLAN_REL).unlink()
        check_eq("refresh: no file is `init` (the skeleton is written)", SP.refresh(root, grown), SP.load(root))
        check_eq("refresh: ... for both cases", [row["case"] for row in SP.load(root)["cases"]], ["TC-1", "TC-2"])
        check("fixture: the earlier bytes were the plan's", kept.startswith(b"{"))
    finally:
        cleanup(root)


def k12_blocker_cases_by_the_receipt():
    """t-1320 F-2. KILLS: M-F2a the test of a blocker resolved by the CURRENT plan (a removed test lifts the bound: None); M-F2b None for
    a blocker that names something the map does not hold; M-F2c a receipt's map ignored."""
    plan = sample_plan()
    stamp = SP.tests_cases(plan)
    check_eq("tests_cases: id -> cases", stamp, {"T-1": ["TC-1", "TC-2"], "T-2": ["TC-3"]})
    blocker = {"kind": "blocker", "case": None, "test": "T-2", "then": None}
    plan["tests"] = [t for t in plan["tests"] if t["id"] != "T-2"]          # the author removed the blocker's test
    check_eq("F-2: the test is resolved by the receipt's map, so its case is still the bound", SP.blocker_cases(plan, [blocker], stamp), {"TC-3"})
    check_eq("F-2: a receipt that predates the map is read by the plan as it stands - and the missing test binds NO case (not 'all')",
             SP.blocker_cases(plan, [blocker], None), set())
    check_eq("F-2: only a blocker with no case, no test and no then is about the whole plan",
             SP.blocker_cases(plan, [{"kind": "blocker", "case": None, "test": None, "then": None}], stamp), None)
    check_eq("F-2: one such blocker among others still lifts the bound (it names nothing)",
             SP.blocker_cases(plan, [blocker, {"kind": "blocker", "case": None, "test": None, "then": None}], stamp), None)
    check_eq("F-2: a test no map holds binds no case, and does not lift the bound",
             SP.blocker_cases(plan, [{"kind": "blocker", "case": "TC-1", "test": "T-9", "then": None}], stamp), {"TC-1"})
    check_eq("F-2: a `then` binds its case, a `remark` binds nothing",
             SP.blocker_cases(plan, [{"kind": "blocker", "case": None, "test": None, "then": "TC-2#1"},
                                     {"kind": "remark", "case": "TC-3", "test": None, "then": None}], stamp), {"TC-2"})
    both = {"kind": "blocker", "case": "TC-1", "test": "T-1", "then": "TC-3#1"}
    check_eq("_remark_cases: case, then and test together", SP._remark_cases(both, stamp), ({"TC-1", "TC-2", "TC-3"}, False))
    check_eq("_remark_cases: an unknown test is unresolved", SP._remark_cases({"test": "T-9"}, stamp), (set(), True))
    # the placement of a remark in a window reads the SAME resolution, against the plan as it stands; the window of a case is the
    # controller's cut (`{case: window number}`), the plan holds none
    window_of = {"TC-1": 1, "TC-2": 1, "TC-3": 2}
    check_eq("_placement: a remark naming a removed test is unplaced (goes to every window)",
             SP._placement({"case": None, "test": "T-2", "then": None}, window_of, plan["tests"]), (set(), "unplaced"))
    check_eq("_placement: a remark naming a test of the plan sits in its window",
             SP._placement({"case": None, "test": "T-1", "then": None}, window_of, plan["tests"]), ({1}, "window"))
    check_eq("_placement: a case the cut does not hold is unplaced, never lost",
             SP._placement({"case": "TC-9", "test": None, "then": None}, window_of, plan["tests"]), (set(), "unplaced"))


if __name__ == "__main__":
    k1_the_kind_of_a_record()
    k1b_the_kind_of_a_record_the_controller_writes()
    k2_the_words()
    k3_shapes_never_diverge()
    k4_load()
    k5_rows_sha()
    k6_mode()
    k7_init()
    k7b_init_without_case_files()
    k8_init_edges()
    k9_stamp_review()
    k10_cli()
    k11_refresh()
    k12_blocker_cases_by_the_receipt()
    finish("test_s5_plan")
