"""HF4-9 F-4 (hotfix-12586/4): the S5 window brief shows an `oracle_unknown` plan row's expected value as SETTLED when every question in
its `question_refs` is answered. The approved plan is never written - the reader (`s5_plan.window_slice` / `render_slice`) derives it
from the answers, through the one answered-reader (`gate_brief.answered_questions`: AR-13).

Keys: K1 the seam (a real S5 story; the recorded run-12586 register, answers AND the recorded TS-14 plan row, Q7 answered; the row
carries question_refs [Q7]) -> the brief prints the settled line with the WHOLE of Q7's words (the deciding rule of Q7 included) and
names the answers file; K2 a ref not answered -> `not settled yet; unanswered: Qn`, no settled claim; K3 answers file absent -> the
unanswered line, answers file not read in full or register missing -> no line at all; K4 a row without question_refs or not
oracle_unknown -> as today; K5 words are never cut at 160, several refs each whole, a text over `person_words_whole`'s maximum is
cut with the cut named and the file; K6 the plan on disk is not written.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import s5_plan as SP  # noqa: E402
from test_s5_plan import put, s5_story  # noqa: E402

FIX = FIXTURES / "run-12586-gate-a" / "work"
HEAD = "Q7 "
RECORDED_ROW = next(r for r in json.loads((FIX / "test-plan.json").read_text(encoding="utf-8"))["rows"] if r["id"] == "TS-14")
# the recorded run-12586 TS-14 row in the place of the synthetic one; only what the story's own state owns is kept (id, disposition,
# level, required_scenarios)
RECORDED = {k: v for k, v in RECORDED_ROW.items() if k not in ("id", "disposition", "level", "required_scenarios")}


def story(extra, answers=True, refs_cases=("TC-1",)):
    root = temp_dir("qa-s5settled-")
    s5_story(root, cases=("TC-1", "TC-2"), with_case_files=True)
    # the approved plan as the run left it: gate A passed, the row is oracle_unknown and names the question (set on the file
    # after approval - the validator at gate A would demand a design review of such a row)
    plan_file = root / "work" / "test-plan.json"
    document = json.loads(plan_file.read_text(encoding="utf-8"))
    for row in document["rows"]:
        if row["id"] == "TS-1":
            row.update(extra)
    plan_file.write_text(json.dumps(document), encoding="utf-8")
    (root / "work").mkdir(exist_ok=True)
    shutil.copyfile(FIX / "requirements-readiness.json", root / "work" / "requirements-readiness.json")
    if answers:
        shutil.copyfile(FIX / "question-answers.jsonl", root / "work" / "question-answers.jsonl")
    plan = {"schema": SP.SCHEMA, "scope_hash": "s", "gate_a_plan_hash": "g",
            "cases": [{"case": c, "requirements": [], "s3": {"row": f"TS-{i}"}, "thens": [{"n": 1, "text": "x"}], "remainders": []}
                      for i, c in enumerate(("TC-1", "TC-2"), 1)], "tests": [], "fixtures": [], "refactor": ""}
    put(root, SP.PLAN_REL, json.dumps(plan))
    return root


def brief(root):
    return SP.render_slice(SP.window_slice(root, cases=["TC-1"]))


def q7_words():
    for line in (FIX / "question-answers.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["id"] == "Q7":
            return " ".join(record["words"].split())[3:].strip()
    raise AssertionError("fixture has no Q7 answer")


def test_k1_settled_line():
    root = story(dict(RECORDED, question_refs=["Q7"]))
    try:
        before = (root / "work" / "test-plan.json").read_bytes() if (root / "work" / "test-plan.json").exists() else b""
        text = brief(root)
        check("K1: the recorded row is the oracle_unknown one", RECORDED["oracle_unknown"] is True)
        check_in("K1: the settled line names Q7 and the person's WHOLE words (432 characters, no cut)",
                 "expected value settled by the person (Q7): " + q7_words() + " [answers file:", text)
        check_in("K1: ... the deciding rule of Q7 is there in full", "If there the user must be an admin of the target project, so for the "
                 "integration too; if there any member of the project can do it, the same requirement holds in this story.", text)
        check_in("K1: ... the line names the answers file", "work/question-answers.jsonl]", text)
        check_not_in("K1: ... and it is not the open line", "unanswered", text)
        check_eq("K6: the plan on disk is not written", (root / "work" / "test-plan.json").read_bytes() if (root / "work" / "test-plan.json").exists() else b"", before)
    finally:
        cleanup(root)


def test_k2_open_ref():
    root = story({"oracle_unknown": True, "question_refs": ["Q7", "Q99"]})
    try:
        text = brief(root)
        check_in("K2: a ref with no answer -> `unanswered: Q99`", "expected value not settled yet; unanswered: Q99", text)
        check_not_in("K2: ... and no settled claim", "settled by the person", text)
    finally:
        cleanup(root)


def test_k3_no_answers():
    root = story({"oracle_unknown": True, "question_refs": ["Q7"]}, answers=False)
    try:
        text = brief(root)
        check_not_in("K3: answers file absent -> no settled line", "settled by the person", text)
        check_in("K3: ... the unanswered ref stays open (true: nothing is answered)", "unanswered: Q7", text)
        (root / "work" / "question-answers.jsonl").write_text(
            (FIX / "question-answers.jsonl").read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
        text = brief(root)
        check_not_in("K3: a broken answers line -> today's brief, no settled claim", "settled by the person", text)
        check_not_in("K3: ... and no open claim either (it is not known)", "unanswered", text)
        (root / "work" / "question-answers.jsonl").write_text((FIX / "question-answers.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        (root / "work" / "requirements-readiness.json").unlink()
        text = brief(root)
        check_not_in("K3: register missing -> no settled line", "settled by the person", text)
        check_not_in("K3: ... and no open claim (the docstring's edge: no line)", "unanswered", text)
    finally:
        cleanup(root)


def test_k4_other_rows():
    for label, extra in (("no question_refs", {"oracle_unknown": True}), ("not oracle_unknown", {"oracle_unknown": False, "question_refs": ["Q7"]}),
                         ("empty refs", {"oracle_unknown": True, "question_refs": []})):
        root = story(extra)
        try:
            text = brief(root)
            check_not_in(f"K4: {label} -> as today (no settled line)", "settled by the person", text)
            check_not_in(f"K4: {label} -> as today (no open line)", "unanswered", text)
        finally:
            cleanup(root)


def test_k5_clip_and_several():
    root = story({"oracle_unknown": True, "question_refs": ["Q7", "Q3"]})
    try:
        text = brief(root)
        check_in("K5: several refs all answered -> each `Qn: words`", "(Q7, Q3): Q7: " + q7_words(), text)
        check_in("K5: ... the second", "; Q3: ", text)
    finally:
        cleanup(root)
    # no cut at the old 160; a text over person_words_whole's maximum is cut WITH the cut named
    import brief_pack as BP
    marker = "(Q7): "
    for label, size in (("beyond 160 (400)", 400), ("AT the maximum", BP.PERSON_WORDS_MAX), ("beyond the maximum", BP.PERSON_WORDS_MAX + 5)):
        root = story({"oracle_unknown": True, "question_refs": ["Q7"]})
        try:
            lines = root / "work" / "question-answers.jsonl"
            records = [json.loads(x) for x in lines.read_text(encoding="utf-8").splitlines()]
            for r in records:
                if r["id"] == "Q7":
                    r["status"], r["reading"], r["words"] = "answered", "", "Q7 " + "w" * size
            lines.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            shown = brief(root).split(marker, 1)[1].splitlines()[0]
            if size <= BP.PERSON_WORDS_MAX:
                check_in(f"K5: {label}: the words are whole", "w" * size + " [answers file:", shown)
                check_not_in(f"K5: {label}: nothing is cut", "[cut:", shown)
            else:
                check_in(f"K5: {label}: the cut says how much is missing", "[cut: 5 more characters, the whole text is in "
                         "qa-factory/artifacts/", shown)
                check_in(f"K5: {label}: ... and names the file", "work/question-answers.jsonl", shown)
        finally:
            cleanup(root)


if __name__ == "__main__":
    test_k1_settled_line()
    test_k2_open_ref()
    test_k3_no_answers()
    test_k4_other_rows()
    test_k5_clip_and_several()
    finish("test_s5_settled_oracle")
