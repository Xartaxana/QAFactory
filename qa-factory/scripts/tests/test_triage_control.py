#!/usr/bin/env python3
"""HF2-18 part A: the triage word `ASSERT_STRICTER` and its `control` block (the analyst's control experiment).

An assert that asks for more than the requirement does is neither a product bug nor a pass: the analyst repeats the
action WITHOUT the change under test, and when the same value shows, the red is a line in "Left with you" (kind
`assert_stricter`, verdict `after_checks`). Code checks only the FORM of the record (`contract.triage_control_problems`,
AR-2/FR-12) and carries the word only with its experiment - without it the red stays a product failure (FR-59).

Keys A-K1..A-K9 of the node spec (`docs/tasks/specs/t-1247-hf2-18-s7-control-experiment.md` section 5, written before
the run), plus A-K5b (N1: the task root comes from the caller, the producer's `validate` has none of its own) and A-K8b (N5:
the item names the Then, the requirement and what was observed).
"""
import ast
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir)

sys.path.insert(0, str(SCRIPTS))
import artifact_producer as AP  # noqa: E402
import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import delivery_verdict as DV  # noqa: E402
import human_text as HT  # noqa: E402
import validate_artifacts as V  # noqa: E402

AFTER = FIXTURES / "after-checks"
DOC = DV.load_kinds()[0]
TEST = "tests/test_coupon.py::test_cap_rejected"
EVIDENCE = "evidence/control-save.json"
OBSERVED = "the form saved with no project change and the same three keys appeared"


def task_root() -> Path:
    """A throw-away task root with the experiment's output file in it, and files that exist under the root but are not
    evidence (the triage itself, the plan): t-1339 F2."""
    root = temp_dir("qa-triage-control-") / "QA-1"
    (root / "evidence").mkdir(parents=True)
    (root / "work").mkdir()
    (root / EVIDENCE).write_text('{"exit": 0}\n', encoding="utf-8")
    (root / "work" / "triage.json").write_text("{}\n", encoding="utf-8")
    (root / "test-plan.md").write_text("plan\n", encoding="utf-8")
    return root


def control(**over) -> dict:
    block = {"result": "effect_without_change", "action": "save the integration in the form",
             "without": "the project was not changed", "observed": OBSERVED, "evidence": EVIDENCE}
    block.update(over)
    return {k: v for k, v in block.items() if v is not None}


def row(verdict: str = "ASSERT_STRICTER", ctl="default", **over) -> dict:
    out = {"instance_id": TEST, "attempt_id": "a1", "test": TEST, "verdict": verdict, "evidence": "evidence/read.json"}
    if ctl == "default":
        ctl = control() if verdict == "ASSERT_STRICTER" else None
    if ctl is not None:
        out["control"] = ctl
    out.update(over)
    return out


def said(problems: list) -> str:
    return "\n".join(problems)


# --- A-K1 -----------------------------------------------------------------------------------------------------------

def a_k1_the_word_and_the_results() -> None:
    check("A-K1 TRIAGE_VERDICTS holds ASSERT_STRICTER", "ASSERT_STRICTER" in C.TRIAGE_VERDICTS, str(C.TRIAGE_VERDICTS))
    check_eq("A-K1 the old words are still there (control: nothing was dropped)",
             [v for v in ("APP_BUG", "CASE_DEFECT", "NOT_EXECUTED") if v in C.TRIAGE_VERDICTS],
             ["APP_BUG", "CASE_DEFECT", "NOT_EXECUTED"])
    check_eq("A-K1 TRIAGE_CONTROL_RESULTS is exactly three words", C.TRIAGE_CONTROL_RESULTS,
             ("effect_without_change", "no_effect_without_change", "impossible"))


# --- A-K2, A-K3, A-K4 ------------------------------------------------------------------------------------------------

def a_k2_a_full_block_has_no_problem() -> None:
    root = task_root()
    try:
        check_eq("A-K2 ASSERT_STRICTER with a full control and its evidence file -> no problem",
                 C.triage_control_problems(row(), root), [])
        check_eq("A-K2 ... with the optional `given_gap` said (F2 b) -> no problem",
                 C.triage_control_problems(row(ctl=control(given_gap="the seed leaves the username empty")), root), [])
        check_eq("A-K2 ... with no task root the existence of the file is not judged, the rest still is",
                 C.triage_control_problems(row(ctl=control(evidence="evidence/not-here.json")), None), [])
        check("A-K2 ... but no task root never passes a missing field",
              bool(C.triage_control_problems(row(ctl=control(observed="")), None)))
    finally:
        cleanup(root.parent)


def a_k3_the_battery_of_bad_rows() -> None:
    root = task_root()
    try:
        battery = [
            ("no control", row(ctl=None), "no `control` block"),
            ("control is a string", row(ctl="x"), "`control` must be an object"),
            ("control is a list", row(ctl=["x"]), "`control` must be an object"),
            ("result outside the list", row(ctl=control(result="maybe")), "`control.result`"),
            ("result missing", row(ctl=control(result=None)), "`control.result`"),
            ("no effect without the change", row(ctl=control(result="no_effect_without_change")), "effect_without_change"),
            ("impossible, even with a why", row(ctl={"result": "impossible", "why": "no stand"}), "effect_without_change"),
            ("empty observed", row(ctl=control(observed="  ")), "`control.observed`"),
            ("empty action", row(ctl=control(action="")), "`control.action`"),
            ("empty without", row(ctl=control(without="")), "`control.without`"),
            ("no evidence", row(ctl=control(evidence=None)), "`control.evidence`"),
            ("evidence is not a file", row(ctl=control(evidence="evidence/nope.json")), "is not a file"),
            ("evidence escapes the root", row(ctl=control(evidence="../x")), "escapes the task root"),
            ("evidence is a POSIX absolute path", row(ctl=control(evidence="/x")), "`control.evidence`"),
            ("evidence is a drive path", row(ctl=control(evidence="C:/x")), "`control.evidence`"),
            ("evidence is a directory", row(ctl=control(evidence="evidence")), "is not a file"),
            ("evidence is an object", row(ctl=control(evidence={"path": EVIDENCE})), "`control.evidence`"),
            # F2 (t-1339): a file that merely exists under the root is the analyst's word, not the experiment's output
            ("evidence is the triage file itself", row(ctl=control(evidence="work/triage.json")), "is not under evidence/"),
            ("evidence is the plan", row(ctl=control(evidence="test-plan.md")), "is not under evidence/"),
            ("evidence leaves evidence/ by `..`", row(ctl=control(evidence="evidence/../work/triage.json")),
             "is not under evidence/"),
            ("evidence is under work/ even in a folder named evidence", row(ctl=control(evidence="work/evidence/x.json")),
             "is not under evidence/"),
            ("evidence holds a NUL", row(ctl=control(evidence="evidence/a\x00b")), "`control.evidence`"),
            ("given_gap empty", row(ctl=control(given_gap="")), "`control.given_gap`"),
        ]
        for name, bad, needle in battery:
            got = C.triage_control_problems(bad, root)
            check(f"A-K3 {name}: at least one problem", bool(got), str(got))
            check_in(f"A-K3 {name}: the text names the field", needle, said(got))
        # the positive control of the same form: a nested file under evidence/ passes (the rule is the folder, not a name)
        (root / "evidence" / "sub").mkdir()
        (root / "evidence" / "sub" / "out.json").write_text("{}", encoding="utf-8")
        check_eq("A-K3 control: evidence/sub/out.json under evidence/ -> no problem",
                 C.triage_control_problems(row(ctl=control(evidence="evidence/sub/out.json")), root), [])
        # the reason a person or a role reads gives a door (FR-1): it names the block to write or the verdict to change
        door = said(C.triage_control_problems(row(ctl=None), root))
        check_in("A-K3 the refusal names the way in: write the block", "re-run `validate-batch`", door)
        check_in("A-K3 ... and the way out: change the verdict", "it is `APP_BUG`", door)
        # an absolute path that lies under the root is answered with the spelling that works (the shared helper)
        inside = said(C.triage_control_problems(row(ctl=control(evidence=str((root / EVIDENCE).resolve()))), root))
        check_in("A-K3 an absolute path under the root names the task-relative spelling", EVIDENCE, inside)
    finally:
        cleanup(root.parent)


def a_k4_the_other_verdicts_need_no_control() -> None:
    root = task_root()
    try:
        for verdict in ("APP_BUG", "TEST_BUG", "CASE_DEFECT", "FLAKY", "ENV_ISSUE", "NOT_EXECUTED"):
            check_eq(f"A-K4 {verdict} without a control -> no problem (an old triage reads as it did)",
                     C.triage_control_problems(row(verdict, ctl=None), root), [])
        check_eq("A-K4 `control: null` reads as absent", C.triage_control_problems(row("APP_BUG", ctl=None, control=None), root), [])
        check("A-K4 APP_BUG with `impossible` and no why -> a problem naming `why`",
              "`control.why`" in said(C.triage_control_problems(row("APP_BUG", ctl={"result": "impossible"}), root)))
        check_eq("A-K4 APP_BUG with `impossible` and a why -> no problem",
                 C.triage_control_problems(row("APP_BUG", ctl={"result": "impossible", "why": "the stand cannot save"}), root),
                 [])
        check_eq("A-K4 APP_BUG with an experiment that found no effect -> no problem",
                 C.triage_control_problems(row("APP_BUG", ctl=control(result="no_effect_without_change")), root), [])
        check("A-K4 a carried block is checked on any verdict: APP_BUG with `control: 'x'` -> a problem",
              bool(C.triage_control_problems(row("APP_BUG", ctl="x"), root)))
        # unfit inputs: pure, never raises (FR-47: the code reports, the role decides)
        for odd in (None, "x", 5, [], [row()], {"verdict": ["ASSERT_STRICTER"], "control": {"result": []}},
                    {"verdict": "ASSERT_STRICTER", "control": {"result": [], "action": 5, "evidence": None}}):
            try:
                got = C.triage_control_problems(odd, root)
                check(f"A-K4 unfit input {str(odd)[:40]!r} returns a list", isinstance(got, list))
            except Exception as exc:  # noqa: BLE001
                check(f"A-K4 unfit input {str(odd)[:40]!r} returns a list", False, repr(exc))
    finally:
        cleanup(root.parent)


# --- A-K5, A-K5b: the validator and the producer -----------------------------------------------------------------------

def a_k5_the_validator() -> None:
    root = task_root()
    try:
        errors: list = []
        V.check_triage_v0(Path("triage.json"), {"triage": [row(), row(ctl=None, test="t-bad")]}, errors, root)
        check_eq("A-K5 one bad ASSERT_STRICTER row -> errors, all about that row", len(errors) >= 1 and all("t-bad" in e for e in errors), True)
        check_in("A-K5 ... named with the test and the block", "t-bad: verdict ASSERT_STRICTER needs its control experiment", errors)
        errors = []
        V.check_triage_v0(Path("triage.json"), {"triage": [row(ctl=control(evidence="evidence/gone.json"))]}, errors, root)
        check_in("A-K5 evidence not on disk -> refused with the field", "`control.evidence`", errors)
        errors = []
        V.check_triage_v0(Path("triage.json"), {"triage": [row()]}, errors, root)
        check_eq("A-K5 the good row -> no error", errors, [])
        # E17: the closed list refuses an unknown word FIRST, alone, and the control check never sees it
        errors = []
        V.check_triage_v0(Path("triage.json"), {"triage": [{"test": "t-zzz", "verdict": "ZZZ", "control": "x"}]}, errors, root)
        check_eq("A-K5 an unknown word -> exactly one error", len(errors), 1)
        check_in("A-K5 ... the 'outside' one", "outside", errors)
        check_not_in("A-K5 ... and no `control` error", "control", errors)
        # FLAKY still has its own gate (the branch is unchanged)
        errors = []
        V.check_triage_v0(Path("triage.json"), {"triage": [{"test": "t-flaky", "verdict": "FLAKY", "evidence": "e"}]}, errors, root)
        check_in("A-K5 control: FLAKY still asks for its reruns", "FLAKY with reruns=None", errors)
        # the file route derives the root from the path (the existing idiom): task/work/triage.json -> task
        base = temp_dir("qa-triage-file-")
        try:
            task = base / "qa-factory" / "artifacts" / "QA-1"
            (task / "work").mkdir(parents=True)
            (task / "evidence").mkdir()
            (task / EVIDENCE).write_text("{}", encoding="utf-8")
            path = task / "work" / "triage.json"
            import json
            path.write_text(json.dumps({"triage": [row()]}), encoding="utf-8")
            check_not_in("A-K5 the file route: a task-relative evidence is found from work/triage.json", "control",
                         [e for e in V.collect_errors(path) if "triage" in e])
            (task / EVIDENCE).unlink()
            check_in("A-K5 the file route: gone from disk -> refused", "`control.evidence`", V.collect_errors(path))
        finally:
            cleanup(base)
    finally:
        cleanup(root.parent)


def a_k5b_the_producer_has_no_root_of_its_own() -> None:
    root = task_root()
    try:
        data = {"triage": [row()]}
        check_eq("A-K5b producer `validate` with the task root and a relative evidence -> no error", AP.validate("triage", data, root), [])
        left: list = []
        got = AP.validate("triage", data, None, left)
        check_eq("A-K5b ... without a task root: no error of existence either (the cwd is not the root)", got, [])
        check("A-K5b ... but it is said, in not_checked", len(left) == 1 and "control experiment" in left[0], str(left))
        left = []
        got = AP.validate("triage", {"triage": [row(ctl=control(observed=""))]}, None, left)
        check_in("A-K5b ... a missing field is still refused with no root", "`control.observed`", got)
        got = AP.validate("triage", {"triage": [row(ctl=control(evidence="evidence/gone.json"))]}, root)
        check_in("A-K5b ... with the root, a file that is not there is refused", "is not a file", got)
        result = AP.validate_batch([{"kind": "triage", "path": "work/triage.json", "data": data}])
        check("A-K5b validate_batch without a root: valid, and says what it did not look for",
              result["valid"] and len(result.get("not_checked") or []) == 1, str(result))
    finally:
        cleanup(root.parent)


# --- A-K6, A-K7: the delivery check and the kinds --------------------------------------------------------------------

def story(source: Path = AFTER) -> Path:
    root = temp_dir("qa-triage-control-story-")
    target = root / "QA-1"
    shutil.copytree(source, target)
    return target


def red_with(task: Path, triage_row: dict) -> None:
    import json
    report = task / "work" / "run-report.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    data["results"][0].update(result="failed", attempt_id="a1")
    report.write_text(json.dumps(data, indent=2), encoding="utf-8")
    triage = task / "work" / "triage.json"
    data = json.loads(triage.read_text(encoding="utf-8"))
    data["triage"].append(triage_row)
    triage.write_text(json.dumps(data, indent=2), encoding="utf-8")


def a_k6_the_delivery_check() -> None:
    check_eq("A-K6 OWNER_BY_TRIAGE_VERDICT[ASSERT_STRICTER] is product", CD.OWNER_BY_TRIAGE_VERDICT.get("ASSERT_STRICTER"), "product")
    bare = {"instance_id": TEST, "attempt_id": "a1", "verdict": "ASSERT_STRICTER", "evidence": "evidence/sanity-20260911-105500.json"}
    task = story()
    try:
        red_with(task, dict(bare))
        reasons = CD.triage_reasons(task)
        check_in("A-K6 a row without its experiment -> a `triage:` reason", "ASSERT_STRICTER without its control experiment", reasons)
        check("A-K6 ... it is a factory reason (FR-19: not the product's)",
              any(r.startswith("triage:") and CD.reason_record(r, {"factory_refs": set(), "case_lift": {}})["owner"] == "factory"
                  for r in reasons), str(reasons))
        doc = CD.assess(task)
        check_eq("A-K6 ... and the delivery is `no` (the direction of no)", doc["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)
    task = story()
    try:
        (task / "evidence").mkdir()
        (task / EVIDENCE).write_text("{}", encoding="utf-8")
        red_with(task, dict(bare, control=control()))
        reasons = CD.triage_reasons(task)
        check_not_in("A-K6 a row with its experiment -> no such reason", "ASSERT_STRICTER without", reasons)
        doc = CD.assess(task)
        check_eq("A-K6 ... and the delivery reads after_checks", doc["delivery_verdict"], "after_checks")
        stricter = [i for i in doc["left_items"] if i.get("kind") == "assert_stricter"]
        check_eq("A-K6 ... with ONE item in Left with you, for the case", [i["case"] for i in stricter], ["TC-001"])
        a_k8b_text_of_the_item(stricter[0] if stricter else {})
        a_k8_left_item_stays_open(doc)
    finally:
        cleanup(task.parent)
    # the negative control: the same red with the evidence of another verdict is still a product failure
    task = story()
    try:
        red_with(task, dict(bare, verdict="APP_BUG"))
        check_eq("A-K6 control: the same red triaged APP_BUG -> no", CD.assess(task)["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)
    # F2 (t-1338): a file that exists under the story but is not in evidence/ (the triage itself) is no experiment output
    task = story()
    try:
        red_with(task, dict(bare, control=control(evidence="work/triage.json")))
        reasons = CD.triage_reasons(task)
        check_in("A-K6 control.evidence = work/triage.json -> a `triage:` reason naming the folder", "is not under evidence/", reasons)
        check_eq("A-K6 ... and the delivery is `no`", CD.assess(task)["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)
    # an experiment whose result says the change causes the effect cannot carry the word, whatever the file holds
    task = story()
    try:
        (task / "evidence").mkdir()
        (task / EVIDENCE).write_text("{}", encoding="utf-8")
        red_with(task, dict(bare, control=control(result="no_effect_without_change")))
        doc = CD.assess(task)
        check_eq("A-K6 ASSERT_STRICTER over `no_effect_without_change` -> no", doc["delivery_verdict"], "no")
    finally:
        cleanup(task.parent)


def a_k7_the_kinds() -> None:
    ledger_states = DOC["ledger_states"]
    kind = DV.kind_of_state("failed:ASSERT_STRICTER", DOC)
    check_eq("A-K7 `failed:ASSERT_STRICTER` -> assert_stricter", (DV._lookup("failed:ASSERT_STRICTER", ledger_states), kind),
             ("assert_stricter", "assert_stricter"))
    check_eq("A-K7 the kind's verdict is after_checks", DV.verdict_of_kind("assert_stricter", DOC), "after_checks")
    check_eq("A-K7 the kind's owner is product", DV.owner_of_kind("assert_stricter", DOC), "product")
    check_eq("A-K7 decide([assert_stricter]) -> after_checks", DV.decide(["assert_stricter"], DOC)[0], "after_checks")
    check_eq("A-K7 decide([assert_stricter, triage_gap]) -> no", DV.decide(["assert_stricter", "triage_gap"], DOC)[0], "no")
    check_eq("A-K7 it counts toward the items of Left with you", DV.counts("assert_stricter", DOC), True)
    # a file that lost the row reads `no`: a state the file does not hold is an unknown, never a default
    broken = {**DOC, "ledger_states": {k: v for k, v in ledger_states.items() if k != "failed:ASSERT_STRICTER"}}
    check("A-K7 control: without the row the state falls to the generic `failed` prefix, not to assert_stricter",
          DV.kind_of_state("failed:ASSERT_STRICTER", broken) != "assert_stricter")


# --- A-K8, A-K8b -------------------------------------------------------------------------------------------------------

def a_k8_left_item_stays_open(doc: dict) -> None:
    """E9: the line of Left with you for the case stays open - step 3 of `left_item_is_open` (the case is in left_items)."""
    check_eq("A-K8 the item's line stays open while the case is in left_items",
             DV.left_item_is_open("TC-001: A coupon above the cap is rejected", doc), True)
    shrunk = dict(doc, left_items=[])
    check_eq("A-K8 control: with the item gone, step 4 would read the triaged red as settled",
             DV.left_item_is_open("TC-001: A coupon above the cap is rejected", shrunk), False)


def a_k8_build_left_items_default_how() -> None:
    facts = {"index": {}, "manifest": {}, "cfg": {}, "decisions": {}, "report": {}, "triage": [], "plan": []}
    items = CD.build_left_items([{"kind": "assert_stricter", "case": "TC-9", "ref": "TC-9", "requirements": ["R-9", "R-19"],
                                  "source": "ledger"}], facts, DOC)
    check_eq("A-K8 one record of the kind -> one item for the case", [i["ref"] for i in items], ["TC-9"])
    how = items[0]["how"] if items else ""
    check("A-K8 `how` starts with the two ways out", how.startswith("Decide: remove this check"), how)
    check_in("A-K8 ... names the requirements it goes beyond", "(R-9, R-19)", how)
    check_in("A-K8 ... and the reason", "the same action without this story's change gives the same result", how)
    check_eq("A-K8 ... the words obey the shape rules of text a person reads (FR-6)", HT.shape_problems(how, kind="report"), [])
    words = "; tell the delivery gate in your own words which one you want, and the factory lays out what it can do, at what cost"
    check_in("RD1-19 ... then the person's way to the conductor, word for word, after the first sentence", words, how)
    check("RD1-19 ... between the reason and the seed's gap, with no command named",
          how.index("gives the same result") < how.index(words) and "python" not in how and "--" not in how, how)
    gapped = CD._assert_stricter_how({"requirements": []}, {"given_gap": "no coupon was seeded"})
    check("RD1-19 ... and the gap still comes last", gapped.endswith("also weaker than the case's Given: no coupon was seeded")
          and gapped.index(words) < gapped.index("also weaker"), gapped)
    # a DIRECT caller can hand `build_left_items` a record the triage has no row for; the item says so (FR-41). The ledger never
    # does: `ledger_records` gives the kind only to the word's own cases (A-K8c, t-1339 B1), so this is the reader's floor
    check_in("A-K8 an item whose case has no triage row says so, a direct caller's record only (FR-41)", "not recorded",
             items[0]["to_check"] if items else "")
    # an item that already carries a `how` keeps it (the author's words, FR-8)
    kept = CD.build_left_items([{"kind": "assert_stricter", "case": "TC-9", "ref": "TC-9", "how": "ask the owner",
                                 "source": "ledger"}], facts, DOC)
    check_eq("A-K8 a `how` that is already there is kept", kept[0]["how"] if kept else "", "ask the owner")


def tc018_task(verdict: str, ctl) -> Path:
    """The TC-018 shape: a red the automator handed over with `contradicts_requirement`, triaged `verdict` with `ctl`."""
    import json
    task = story()
    (task / "evidence").mkdir()
    (task / EVIDENCE).write_text("{}", encoding="utf-8")
    triage_row = {"instance_id": TEST, "attempt_id": "a1", "verdict": verdict, "evidence": "evidence/sanity-20260911-105500.json"}
    if ctl is not None:
        triage_row["control"] = ctl
    red_with(task, triage_row)
    manifest = task / "work" / "automation-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["unresolved"].append({"case": "TC-001", "reason": "contradicts_requirement", "thens": [2],
                               "detail": "the test asserts the dictionary equals the one before"})
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return task


def a_k8b_text_of_the_item(item: dict) -> None:
    """N5: the item says WHICH assert the person decides about, against which requirement, and what was observed without
    the change - the fields of the record, never wording code reads."""
    print(f"A-K8b the item a person reads: to_check={item.get('to_check')!r} how={item.get('how')!r}")
    check_in("A-K8b the item's to_check carries what was observed without the change", OBSERVED, item.get("to_check", ""))
    check_in("A-K8b ... in the words 'without this story's change'", "without this story's change", item.get("to_check", ""))
    check_in("A-K8b the item's how names the requirement of the case", "(R-1)", item.get("how", ""))
    check_eq("A-K8b ... and the kind list carries the kind", item.get("kinds"), ["assert_stricter"])
    # F2 (b): the seed's own gap rides on the same line
    task = story()
    try:
        (task / "evidence").mkdir()
        (task / EVIDENCE).write_text("{}", encoding="utf-8")
        red_with(task, {"instance_id": TEST, "attempt_id": "a1", "verdict": "ASSERT_STRICTER",
                        "evidence": "evidence/sanity-20260911-105500.json",
                        "control": control(given_gap="the seed leaves the username empty")})
        doc = CD.assess(task)
        gap = [i for i in doc["left_items"] if i.get("kind") == "assert_stricter"]
        check_in("A-K8b given_gap rides on the same item", "the test's data was also weaker than the case's Given: the seed "
                 "leaves the username empty", gap[0]["how"] if gap else "")
    finally:
        cleanup(task.parent)
    # the Then: a red row of the manifest names it (the automator hands the red over with `contradicts_requirement`)
    # the TC-018 shape: the automator hands the red over with `contradicts_requirement` (Lead 27.10: this reaches after_checks
    # once the analyst's word carries a well-formed experiment, and ONLY then - the chain stays broken for every other word)
    def contradicts(verdict: str, ctl) -> dict:
        task = tc018_task(verdict, ctl)
        try:
            return CD.assess(task)
        finally:
            cleanup(task.parent)

    doc = contradicts("ASSERT_STRICTER", control())
    gap = [i for i in doc["left_items"] if i.get("kind") == "assert_stricter"]
    check_eq("A-K8b TC-018 shape: red + contradicts_requirement row + ASSERT_STRICTER with its experiment -> after_checks",
             (doc["delivery_verdict"], doc["reasons"]), ("after_checks", []))
    check_in("A-K8b ... the item names the Then the red row names", "Then 2 - without", gap[0]["to_check"] if gap else "")
    for name, verdict, ctl in (("a malformed experiment (evidence not on disk)", "ASSERT_STRICTER", control(evidence="evidence/gone.json")),
                               ("no experiment", "ASSERT_STRICTER", None),
                               ("an experiment that found no effect", "ASSERT_STRICTER", control(result="no_effect_without_change")),
                               ("APP_BUG on the same row", "APP_BUG", None),
                               ("CASE_DEFECT on the same row", "CASE_DEFECT", None)):
        doc = contradicts(verdict, ctl)
        check_eq(f"A-K8b TC-018 shape with {name} -> still no", doc["delivery_verdict"], "no")
        check("A-K8b ... and the chain is still broken (the traceability reason stands)",
              any(r.startswith("traceability: R-1 has no terminal outcome") for r in doc["reasons"]), str(doc["reasons"]))
    # the Thens: the manifest's red row names them (`thens`); none named -> the case, no number invented
    facts = {"manifest": {"unresolved": [{"case": "TC-1", "reason": "contradicts_requirement", "thens": [4, "2", 0, True]},
                                         {"case": "TC-1", "reason": "handed_to_person", "thens": [9]},
                                         {"case": "TC-2", "reason": "contradicts_requirement"}]}}
    check_eq("A-K8b the Thens come from the red row's `thens` through then_number", CD._stricter_thens("TC-1", facts), [2, 4])
    check_eq("A-K8b ... a red row naming none names none", CD._stricter_thens("TC-2", facts), [])


# --- A-K8c: the other cases of the word's plan row (t-1338 B1) ---------------------------------------------------------

def neighbour_task(neighbour: str) -> Path:
    """The fixture story with TC-001 red and triaged ASSERT_STRICTER (a well-formed experiment), and a second case on the SAME
    plan row TS-1: `green` (its own passed test TC-003), `app_bug` (its own failed test TC-003, triaged APP_BUG), `handed`
    (TC-006, a manifest hand-off pointing at TS-1), `handed_file` (TC-006, a case file of TS-1 plus a hand-off row)."""
    import json
    task = story()
    (task / "evidence").mkdir()
    (task / EVIDENCE).write_text("{}", encoding="utf-8")
    red_with(task, {"instance_id": TEST, "attempt_id": "a1", "verdict": "ASSERT_STRICTER",
                    "evidence": "evidence/sanity-20260911-105500.json", "control": control()})
    work = task / "work"
    other = "tests/test_other.py::test_neighbour"

    def edit(name: str, change) -> None:
        path = work / name
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    if neighbour in ("green", "app_bug"):
        edit("automation-manifest.json", lambda d: d["tests"].append(
            {"case": "TC-003", "plan_row": "TS-1", "file": "tests/test_other.py", "test": other, "marker": "TC-003",
             "status": "green", "critic_verdict": "approved"}))
        edit("run-report.json", lambda d: d["results"].append(
            {"test": other, "case": "TC-003", "result": "passed" if neighbour == "green" else "failed", "attempt_id": "a1",
             "evidence": "evidence/sanity-20260911-105500.json"}))
        if neighbour == "app_bug":
            edit("triage.json", lambda d: d["triage"].append(
                {"instance_id": other, "attempt_id": "a1", "verdict": "APP_BUG", "evidence": "evidence/x.json"}))
    if neighbour == "handed":
        edit("automation-manifest.json", lambda d: d["unresolved"].append(
            {"case": "TC-006", "reason": "handed_to_person", "plan_row": "TS-1", "detail": "android: npm run e2e -- --grep TC-006"}))
    if neighbour == "handed_file":
        text = (work / "test-cases" / "checkout" / "TC-005.md").read_text(encoding="utf-8")
        (work / "test-cases" / "checkout" / "TC-006.md").write_text(
            text.replace("TC-005", "TC-006").replace("R-5", "R-1").replace("TS-5", "TS-1"), encoding="utf-8")
        edit("automation-manifest.json", lambda d: d["unresolved"].append(
            {"case": "TC-006", "reason": "handed_to_person", "detail": "android: npm run e2e -- --grep TC-006"}))
    return task


def a_k8c_neighbours_of_the_stricter_case() -> None:
    def kinds_by_case(doc: dict) -> dict:
        return {i["case"]: i["kinds"] for i in doc["left_items"] if i.get("case")}

    base = neighbour_task("none")
    try:
        doc = CD.assess(base)
        check_eq("A-K8c control: no neighbour -> after_checks, ONE assert_stricter item, for TC-001",
                 (doc["delivery_verdict"], [c for c, k in kinds_by_case(doc).items() if "assert_stricter" in k]),
                 ("after_checks", ["TC-001"]))
    finally:
        cleanup(base.parent)
    # (i) a green neighbour on the same plan row: no "remove this check" item for a test that passed
    task = neighbour_task("green")
    try:
        doc = CD.assess(task)
        kinds = kinds_by_case(doc)
        check_eq("A-K8c green neighbour: the delivery is still after_checks, no reason", (doc["delivery_verdict"], doc["reasons"]),
                 ("after_checks", []))
        check_eq("A-K8c ... exactly one assert_stricter item, and it is TC-001's",
                 [c for c, k in kinds.items() if "assert_stricter" in k], ["TC-001"])
        check_eq("A-K8c ... the green case TC-003 has NO item at all", "TC-003" in kinds, False)
        check_not_in("A-K8c ... and no item tells the person to remove a check of TC-003",
                     "TC-003", [i["to_check"] + i["how"] for i in doc["left_items"] if "assert_stricter" in (i.get("kinds") or [])])
    finally:
        cleanup(task.parent)
    # (ii) a neighbour triaged APP_BUG: the bug holds the verdict (its own row), and only TC-001 carries the stricter item
    task = neighbour_task("app_bug")
    try:
        doc = CD.assess(task)
        check_eq("A-K8c APP_BUG neighbour -> no", doc["delivery_verdict"], "no")
        check("A-K8c ... the reason is the neighbour's own row", any("failed:APP_BUG" in r for r in doc["reasons"]), str(doc["reasons"]))
        check_eq("A-K8c ... only TC-001 carries the assert_stricter item",
                 [c for c, k in kinds_by_case(doc).items() if "assert_stricter" in k], ["TC-001"])
    finally:
        cleanup(task.parent)
    # (iii) a handed neighbour keeps its handed item, in both shapes of a hand-off on the plan row
    for name in ("handed", "handed_file"):
        task = neighbour_task(name)
        try:
            doc = CD.assess(task)
            kinds = kinds_by_case(doc)
            check_eq(f"A-K8c {name} neighbour: after_checks", (doc["delivery_verdict"], doc["reasons"]), ("after_checks", []))
            check_in(f"A-K8c {name}: the neighbour TC-006 keeps its handed item", "handed", kinds.get("TC-006", []))
            check_not_in(f"A-K8c {name}: ... and it is not an assert_stricter one", "assert_stricter", kinds.get("TC-006", []))
            check_in(f"A-K8c {name}: TC-001 keeps its own assert_stricter item", "assert_stricter", kinds.get("TC-001", []))
        finally:
            cleanup(task.parent)
    # the two functions that scope the word, on a plan row whose cases are told apart (the ledger doc and the facts by hand)
    facts = {"dispositions": {}, "decisions": {}, "cfg": {}, "report": {}, "triage": [], "plan": [], "manifest": {},
             "index": {"c/TC-001": {"plan_row": "TS-1", "case_id": "TC-001"}, "c/TC-003": {"plan_row": "TS-1", "case_id": "TC-003"}}}
    ledger = {"rows": [{"kind": "plan_row", "ref": "TS-1", "state": "failed:ASSERT_STRICTER", "detail": "TC-001"}]}
    check_eq("A-K8c _stricter_scope keeps only the word's own cases", CD._stricter_scope(["TC-001", "TC-003"], frozenset({"TC-001"})),
             ["TC-001"])
    got = CD.ledger_records(ledger, facts)
    check_eq("A-K8c a failed:ASSERT_STRICTER row no case of which holds the word reads as a red -> kind red, verdict no",
             ([r["kind"] for r in got], DV.verdict_of_kind(CD.RED_KIND, DOC)), (["red"], "no"))
    check_in("A-K8c ... with the sentence that says why", "failed:ASSERT_STRICTER", got[0]["text"] if got else "")
    original = CD._stricter_cases
    CD._stricter_cases = lambda _facts: frozenset({"TC-001"})
    try:
        got = CD.ledger_records(ledger, facts)
        check_eq("A-K8c the same row with TC-001 holding the word -> kind assert_stricter, for TC-001 alone",
                 ([r["kind"] for r in got], [r["cases"] for r in got], [r["case"] for r in got]),
                 (["assert_stricter"], [["TC-001"]], ["TC-001"]))
        check_eq("A-K8c _red_cases: of that row only TC-001 is red (TC-003 may carry a handed item)",
                 CD._red_cases(ledger, facts, frozenset({"TC-001"}), DOC), {"TC-001"})
        check_eq("A-K8c _red_cases control: with no case holding the word the row is a plain red - all its cases",
                 CD._red_cases(ledger, facts, frozenset(), DOC), {"TC-001", "TC-003"})
        plain = {"rows": [{"kind": "plan_row", "ref": "TS-1", "state": "failed:APP_BUG", "detail": "TC-001"}]}
        check_eq("A-K8c _red_cases control: a failed:APP_BUG row is red for all its cases, whatever the set",
                 CD._red_cases(plain, facts, frozenset({"TC-001"}), DOC), {"TC-001", "TC-003"})
    finally:
        CD._stricter_cases = original


# --- A-K8d: the command line answers like the delivery check (t-1338 F1) -----------------------------------------------

def a_k8d_the_cli_agrees_with_delivery() -> None:
    import json
    import subprocess

    def cli(task: Path) -> tuple:
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "check_traceability.py"), str(task), "--json"],
                              capture_output=True, text=True, encoding="utf-8")
        text = subprocess.run([sys.executable, "-B", str(SCRIPTS / "check_traceability.py"), str(task)],
                              capture_output=True, text=True, encoding="utf-8")
        return json.loads(done.stdout), text.stdout

    for name, verdict, ctl, ok in (("TC-018 shape: ASSERT_STRICTER with its experiment", "ASSERT_STRICTER", control(), True),
                                   ("no experiment", "ASSERT_STRICTER", None, False),
                                   ("an experiment whose file is gone", "ASSERT_STRICTER", control(evidence="evidence/gone.json"), False),
                                   ("an experiment outside evidence/", "ASSERT_STRICTER", control(evidence="work/triage.json"), False),
                                   ("APP_BUG", "APP_BUG", None, False)):
        task = tc018_task(verdict, ctl)
        try:
            # The fixture's other requirements (R-2, R-4, R-5: a manual check, a hand-off) are the delivery check's debts the bare
            # CLI never knew, so the CLI's whole-story `ok` is False here whatever the word is; the requirement of THIS case is
            # R-1, and it is the one the two must tell alike.
            result, printed = cli(task)
            row = next(r for r in result["rows"] if r["requirement"] == "R-1")
            blocked = [ln for ln in printed.splitlines() if ln.startswith("REQUIREMENTS WITHOUT A TERMINAL OUTCOME")]
            delivery = [r for r in CD.assess(task)["reasons"] if r.startswith("traceability: R-1 has no terminal outcome")]
            check_eq(f"A-K8d {name}: the CLI gives R-1 a terminal outcome = {ok}", (bool(row["outcome"]), row["outcome"] or "NONE"),
                     (ok, "executed_failed" if ok else "NONE"))
            check_eq("A-K8d ... the line the driver prints does not name R-1 as an open chain", "R-1" in "".join(blocked), not ok)
            check_eq("A-K8d ... and the delivery check agrees about R-1", bool(delivery), not ok)
        finally:
            cleanup(task.parent)


# --- A-K9: the census --------------------------------------------------------------------------------------------------

def a_k9_census() -> None:
    def code_of(path: Path) -> str:
        """The file as code: comments are gone with `ast.unparse`, and a docstring is dropped, so a sentence in the
        description of another function (traceability.py `_behind_another_red`, HF8-16, 4ad9eea9) is not a use of the word."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body[0].value.value = ""
        return ast.unparse(tree)

    def files(word: str) -> list:
        return sorted(p.name for p in SCRIPTS.glob("*.py") if re.search(word, code_of(p)))

    found = files("ASSERT_STRICTER")
    print(f"A-K9 census: ASSERT_STRICTER in scripts/*.py -> {found}")
    print(f"A-K9 control (same form): CASE_DEFECT in scripts/*.py -> {files('CASE_DEFECT')}")
    check_eq("A-K9 the word lives in the vocabulary and the delivery owner table, nowhere else in code",
             found, ["check_delivery.py", "contract.py"])
    check("A-K9 control: the same search finds the older word in the same two files",
          set(found) <= set(files("CASE_DEFECT")))


def main() -> None:
    a_k1_the_word_and_the_results()
    a_k2_a_full_block_has_no_problem()
    a_k3_the_battery_of_bad_rows()
    a_k4_the_other_verdicts_need_no_control()
    a_k5_the_validator()
    a_k5b_the_producer_has_no_root_of_its_own()
    a_k6_the_delivery_check()
    a_k7_the_kinds()
    a_k8_build_left_items_default_how()
    a_k8c_neighbours_of_the_stricter_case()
    a_k8d_the_cli_agrees_with_delivery()
    a_k9_census()
    finish("test_triage_control")


if __name__ == "__main__":
    main()
