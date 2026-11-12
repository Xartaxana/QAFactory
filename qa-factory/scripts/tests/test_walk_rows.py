#!/usr/bin/env python3
"""RN1-6 (t-1685 N2): the strategist is told which functions to walk (a brief line, no code check - owner's word 03.11.2026, F2 b). The
question-branch check at the S3 exit is main's `planning_contract.s3_branch_refusals` (RN1-2), pinned in test_question_branches.py and
test_s3_s4_chain.py.
KEYS: W6 no `## Functions` table (or none counted) -> no line, W7 a broken sizing reader -> ONE `not measured` line and the brief is built,
W9 the line names 8 / 9 functions (8 + `(+1 more: ...)`), the fold of `functions_of` is the reader's, W10 the wiring (ONE line in the S3 block of
`build`), W11 the charter holds rule 1c and no longer the text coverage-design.md holds.
Mutations (each killed by THIS file): `FUNCTIONS_SHOWN` 8 -> 9 -> W9; the walk line wired outside the S3 block -> W10."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack as BP  # noqa: E402
import sizing  # noqa: E402

HEAD = ("## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |\n"
        "|---|---|---|---|---|---|---|---|---|\n")
FHEAD = "| Function | Requirements |\n|---|---|\n"
PLUGIN = SCRIPTS.parent


def reg_row(n: int) -> str:
    return f"| R-{n} | requirement {n} | story | — | yes | — | diff:src/f{n}.py:1 | degraded | new |\n"


def register(n_rows: int, functions=None) -> str:
    return HEAD + "".join(reg_row(i) for i in range(1, n_rows + 1)) + "\n" + ("" if functions is None else "## Functions\n\n" + FHEAD + functions)


def story(register_text, plan=None, questions=None):
    """(project, task root): a story with the register text, and optionally a plan and the readiness register."""
    project = harness.temp_project("qa-walk-")
    task = project / "qa-factory" / "artifacts" / "QA-1"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}, "halts": []}), encoding="utf-8")
    if register_text is not None:
        (task / "work" / "requirements-register.md").write_text(register_text, encoding="utf-8")
    if plan is not None:
        (task / "work" / "test-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if questions is not None:
        (task / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": questions}), encoding="utf-8")
    return project, task


def walk(register_text) -> list:
    project, task = story(register_text)
    try:
        return BP.walk_lines(task)
    finally:
        harness.cleanup(project)


def functions(n: int) -> str:
    return "".join(f"| function {i} | R-{i} |\n" for i in range(1, n + 1))


def w_brief() -> None:
    check_eq("W6 no `## Functions` table: no line (the unit is requirements, sizing's own world)", walk(register(2)), [])
    check_eq("W6 no register at all: no line", walk(None), [])
    check_eq("W6 a table that lists no requirement: no line", walk(register(2, "| function 1 |  |\n")), [])
    out = walk(register(2, "| Add a book | R-1 |\n| Change a cart line quantity | R-2 |\n"))
    check_eq("W9 two functions: ONE line", len(out), 1)
    check_in("W9 ... names each function with its requirements, in table order",
             "Functions to walk: Add a book (R-1); Change a cart line quantity (R-2) - each gets a row that walks it as a person does", out[0])
    check_in("W9 ... and says where to name it, and the way out", "named in the row's `walks`, or a `walk_homes` entry with a reason", out[0])
    cap = BP.FUNCTIONS_SHOWN
    for n, more in ((cap, False), (cap + 1, True)):
        line = walk(register(n, functions(n)))[0]
        check_eq(f"W9 {n} functions: {cap} named", sum(f"function {i} (R-{i})" in line for i in range(1, n + 1)), cap)
        check_eq(f"W9 {n} functions: the rest is counted ('+1 more' only beyond the cap)", "(+1 more: the register's ## Functions)" in line, more)
    folded = walk(register(2, "| Change a cart line quantity | R-1 |\n| change a cart line  quantity | R-2 |\n"))[0]
    check_in("W9 the reader's fold: two spellings of one function are ONE entry holding both requirements",
             "Change a cart line quantity (R-1, R-2) - each gets", folded)
    with patch.object(sizing, "functions_of", side_effect=RuntimeError("boom")):
        check_eq("W7 the sizing reader raising: ONE line saying it was not measured, nothing raised",
                 walk(register(2, functions(2))), ["Functions to walk: not measured: sizing.functions_of, a defect of the factory"])
    src = (SCRIPTS / "brief_pack.py").read_text(encoding="utf-8")
    s3 = src[src.index('    if stage == "S3" and not first_look:'):src.index('    if stage == "S2":\n        head += user_path_failure_lines(')]
    check_eq("W10 build adds the walk line inside the S3 block, once", s3.count("head += walk_lines("), 1)
    check_eq("W10 ... and nowhere else in `build`", src.count("head += walk_lines("), 1)
    charter = (PLUGIN / "agents" / "qa-test-strategist.md").read_text(encoding="utf-8")
    # spec t-1765 X1 (B-D): the step number is gone with the old procedure; the sentence stands in "Good outcome" item 4
    check_in("W11 the charter holds the walk rule", "Every function of the register's `## Functions` gets a row that WALKS it", charter)
    check_not_in("W11 control: a wrong walk rule is not in the charter", "Every function of the register's `## Functions` gets a row that SKIPS it", charter)


w_brief()
finish("walk rows")
