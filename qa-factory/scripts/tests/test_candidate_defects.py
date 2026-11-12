#!/usr/bin/env python3
"""G2-15: the register's `bug:candidate-defect` mark reaches the plan and the briefs (A5, A9 of t-525).
KEYS: C1 `contract.candidate_defects` (segment equality, observable forms, typos, no mark), C2 the `derived_from` table of A5 through
`contract.derived_from_legal` AND the S2 form check `validate_artifacts`, C3 `candidates_without_row` (skip, manual-human, a branch on a
missing question / a missing letter / a settled question, not_needed, `*`, questions unreadable), C4 `brief_pack.candidate_defect_line`
(none, one, 5 at the limit, 6 beyond it, no place), C5 the fence names the candidate in the detector's text."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack as BP  # noqa: E402
import contract as C  # noqa: E402
import planning_contract as PC  # noqa: E402

HEAD = "## Register\n\n| R | requirement | source | derived_from | x | ac_ref | observable |\n|---|---|---|---|---|---|---|\n"


def register(*rows) -> str:
    return HEAD + "".join(f"| {r} | {t} | derived | {d} | | | {o} |\n" for r, t, d, o in rows)


MARK = "bug:candidate-defect"
text = register(("R-13", "cart page", MARK, "current-code:MyBooks/src/CartPage.tsx:65"),
                ("R-14", "no place", MARK, "none"),
                ("R-15", "typo", "bug:candidate-defects", "current-code:a.ts:1"),
                ("R-16", "case", "BUG:candidate-defect", "current-code:a.ts:1"),
                ("R-17", "second segment", "bug:none-recorded; " + MARK, "current-code:b.ts:7"),
                ("R-18", "other", "bug:BUG-12", "current-code:c.ts:3"))
found = {c["r"]: c for c in C.candidate_defects(text)}
check_eq("C1 candidates are the rows with a segment equal to the mark", sorted(found), ["R-13", "R-14", "R-17"])
check_eq("C1 file and line from current-code:<file>:<line>", (found["R-13"]["file"], found["R-13"]["line"]), ("MyBooks/src/CartPage.tsx", 65))
check_eq("C1 observable not current-code: file None", (found["R-14"]["file"], found["R-14"]["line"]), (None, None))
check_eq("C1 the requirement text travels", found["R-13"]["requirement"], "cart page")
check_eq("C1 a register with no mark: []", C.candidate_defects(register(("R-1", "a", "bug:BUG-1", "none"))), [])
check_eq("C1 no table: []", C.candidate_defects("# nothing"), [])
check_eq("C1 empty text: []", C.candidate_defects(""), [])

for cell, ok in (("bug:BUG-12", True), ("bug:TP1-123", True), (MARK, True), ("bug:none-recorded; invariant:x", True),
                 ("bug:candidate-defects", False), ("BUG:candidate-defect", False), ("bug:Candidate-Defect", False), ("bug:none-recorded", False),
                 ("aspect:cart", True), ("nonsense", False)):
    check_eq(f"C2 derived_from_legal({cell!r})", C.derived_from_legal(cell), ok)

# the S2 form check says it, with the door
import validate_artifacts as VA  # noqa: E402
tmp = harness.temp_dir()
body = ("---\nids: [R-1]\nby_source: {derived: 1}\nconfidence: high\n---\n\n" + HEAD
        + "| R-1 | a | derived | bug:candidate-defects | | | none |\n")
REG = tmp / "requirements-register.md"
REG.write_text(body, encoding="utf-8")
errors: list = []
required = getattr(VA, "REGISTER_REQUIRED", ())
VA.check_register(REG, errors) if hasattr(VA, "check_register") else None
check("C2 the S2 form refuses a misspelt mark and names the door", any("`bug:` takes a bug id" in e for e in errors), str(errors)[:300])
REG.write_text(body.replace("bug:candidate-defects", MARK), encoding="utf-8")
errors = []
VA.check_register(REG, errors)
check_not_in("C2 the exact mark passes the form check", "`bug:` takes a bug id", " ".join(errors))

# --- C3: candidates_without_row ------------------------------------------------------------------------
cand = [{"r": "R-13", "requirement": "x", "file": None, "line": None}]
Q = {"id": "Q3", "question": "bug?", "source_says": "", "status": "named", "letters": ["a", "b"], "readings": [{"id": "a"}, {"id": "b"}]}


def gap(*rows, questions=(Q,)):
    return [c["r"] for c in PC.candidates_without_row(list(rows), cand, list(questions))]


def r(disposition, **extra):
    return {"id": "TS-1", "requirements": ["R-13"], "disposition": disposition, "reason": "x", **extra}


check_eq("C3 no row at all", gap(), ["R-13"])
check_eq("C3 skip alone does not close", gap(r("skip")), ["R-13"])
check_eq("C3 manual-human alone does not close", gap(r("manual-human")), ["R-13"])
check_eq("C3 automate closes", gap(r("automate")), [])
check_eq("C3 manual-agent closes", gap(r("manual-agent")), [])
check_eq("C3 unverifiable with a branch a -> automate closes", gap(r("unverifiable", if_answered={"Q3": {"a": {"disposition": "automate"}}})), [])
check_eq("C3 only not_needed -> automate does not close (a dropped check is not a test)",
         gap(r("unverifiable", if_answered={"Q3": {"not_needed": {"disposition": "automate"}}})), ["R-13"])
check_eq("C3 * -> automate closes (resolve_patch reads *)", gap(r("unverifiable", if_answered={"Q3": {"*": {"disposition": "automate"}}})), [])
check_eq("C3 a branch on a question that does not exist does not close",
         gap(r("unverifiable", if_answered={"Q99": {"a": {"disposition": "automate"}}})), ["R-13"])
check_eq("C3 a letter beyond the readings does not close", gap(r("unverifiable", if_answered={"Q3": {"z": {"disposition": "automate"}}})), ["R-13"])
check_eq("C3 a branch on a settled question does not close",
         gap(r("unverifiable", if_answered={"Q3": {"a": {"disposition": "automate"}}}), questions=({**Q, "status": "not_needed"},)), ["R-13"])
check_eq("C3 questions unreadable ([]): the branch does not count",
         gap(r("unverifiable", if_answered={"Q3": {"a": {"disposition": "automate"}}}), questions=()), ["R-13"])
check_eq("C3 a row of another requirement does not close", gap({**r("automate"), "requirements": ["R-1"]}), ["R-13"])
two = PC.candidates_without_row([], cand + [{"r": "R-16", "requirement": "y", "file": None, "line": None}], [])
check_eq("C3 two candidates: both named in one round", [c["r"] for c in two], ["R-13", "R-16"])

# --- C4: the brief line --------------------------------------------------------------------------------
def story(rows):
    root = tmp / f"st{len(rows)}"
    (root / "work").mkdir(parents=True, exist_ok=True)
    (root / "work" / "requirements-register.md").write_text(register(*rows), encoding="utf-8")
    return root


one = BP.candidate_defect_line(story([("R-13", "x", MARK, "current-code:MyBooks/src/CartPage.tsx:65")]))
check("C4 one candidate: R-13 and the place", "R-13" in one and "CartPage.tsx:65" in one and one.startswith("Suspect places (candidate defects):"), one)
check_eq("C4 it is ONE line", one.count("\n"), 0)
five = BP.candidate_defect_line(story([(f"R-{n}", "x", MARK, f"current-code:f{n}.ts:{n}") for n in range(1, 6)]))
check("C4 5 candidates at the limit: all with a place, no register pointer", all(f"R-{n} f{n}.ts:{n}" in five for n in range(1, 6)) and "in work/requirements-register.md" not in five, five)
six = BP.candidate_defect_line(story([(f"R-{n}", "x", MARK, f"current-code:f{n}.ts:{n}") for n in range(1, 7)]))
check("C4 6 candidates beyond it: the sixth by id with the register as its place, one line", "R-6 f6.ts:6" not in six and ", and R-6 in work/requirements-register.md" in six and six.count("\n") == 0, six)
check_in("C4 a candidate with no place is said so", "R-14 place in the code not named", BP.candidate_defect_line(story([("R-14", "x", MARK, "none"), ("R-2", "y", "aspect:z", "none")])))
check_eq("C4 no candidates: no line", BP.candidate_defect_line(story([("R-1", "x", "aspect:z", "none")])), "")
check_eq("C4 no register: no line", BP.candidate_defect_line(tmp / "nowhere"), "")

# --- C5: the detector names the candidate ----------------------------------------------------------------
fence = PC.fence_lines({"missing": [], "candidates": cand, "waiting": [], "by_reference": []})
check("C5 the candidate refusal names R-13 and the allowed dispositions",
      len(fence) == 1 and "R-13: the register marks this requirement `bug:candidate-defect`" in fence[0][1][0] and "`automate` or `manual-agent`" in fence[0][1][0], str(fence))

finish("test_candidate_defects")
