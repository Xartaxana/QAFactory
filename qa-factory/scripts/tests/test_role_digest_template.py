#!/usr/bin/env python3
"""F11 (t-1701 D5-C): the digest template a brief carries - code fills in the label, the scope ids and the path;
the role fills in the verdict, the states and the reasons. Advice only: `role_digest.check` is unchanged."""
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import role_digest as RD  # noqa: E402

ROLE, STAGE, LABEL = "qa-case-designer", "S4", "S4-qa-case-designer-1"
PATH = "work/test-cases/"


def fill(text: str) -> str:
    """What a role does with the template: every `<...>` replaced, the hint line dropped."""
    out = []
    for line in text.splitlines():
        if line.startswith("States: "):
            continue
        line = line.replace("<ok|concerns|halt|impossible>", "ok").replace("<state>", "created")
        out.append(line.split(" · <reason")[0] + " · x" if " · <reason" in line else line)
    return "\n".join(out)


def rows_of(text: str) -> list:
    return [ln for ln in text.splitlines() if " · <state> · " in ln]


def t1_t2_round_trip_and_negative_control() -> None:
    scope = ["TC-1", "TC-2", "TS-2"]
    text = RD.template(ROLE, STAGE, LABEL, scope, PATH)
    filled = fill(text)
    check_eq("T1 round trip: the filled template passes the gate's own check", RD.check(filled, scope), [])
    without = "\n".join(ln for ln in filled.splitlines() if not ln.startswith("TS-2 "))
    errors = RD.check(without, scope)
    check("T2 negative control: a template with the TS-2 row removed names TS-2", any("TS-2" in e for e in errors), str(errors))
    check_eq("T2 (positive pair): and the whole one names nothing", RD.check(filled, scope), [])


def t3_nothing_prefilled() -> None:
    text = RD.template(ROLE, STAGE, LABEL, ["TC-1", "TC-2"], PATH)
    body = [ln for ln in text.splitlines() if not ln.startswith("States: ")]
    parsed = RD.parse("\n".join(body))
    check_eq("T3 the unfilled header reads no verdict (nothing pre-filled)", parsed["header"].get("verdict"), "")
    for ln in rows_of(text):
        fields = [f.strip() for f in RD.SEPARATOR.split(ln, 2)]
        check(f"T3 the state field of `{fields[0]}` is a placeholder, not a state word",
              fields[1] == "<state>" and fields[1] not in RD.ROW_STATES and not RD._row_state(fields[1]), fields[1])
    check_eq("T3 and the unfilled rows parse as no row at all", parsed["rows"], [])
    first = text.splitlines()[0]
    check("T3 the first line is the header with the verdict as a placeholder",
          first.endswith("· <ok|concerns|halt|impossible>") and first.startswith(f"{ROLE} {STAGE} {LABEL} "), first)


def t5_bounds() -> None:
    ids40 = [f"TC-{i:03d}" for i in range(40)]
    at = RD.template(ROLE, STAGE, LABEL, ids40, PATH)
    check_eq("T5 at the bound: 40 ids give 40 rows", len(rows_of(at)), 40)
    check_not_in("T5 ... and no tail", "more ids of your scope", at)
    ids41 = ids40 + ["TC-040"]
    beyond = RD.template(ROLE, STAGE, LABEL, ids41, PATH)
    check_eq("T5 beyond the bound: 41 ids give 40 rows", len(rows_of(beyond)), 40)
    tail = next((ln for ln in beyond.splitlines() if "more ids of your scope" in ln), "")
    check_in("T5 ... and a tail naming the 41st", "TC-040", tail)
    check_in("T5 ... and counting the rest", "… and 1 more ids", tail)
    many = ids40 + [f"TC-LONG-{i:05d}" for i in range(200)]
    long_tail = next(ln for ln in RD.template(ROLE, STAGE, LABEL, many, PATH).splitlines() if "more ids of your scope" in ln)
    check_eq("T5 a tail over the cut is exactly the cut plus the mark", len(long_tail), RD.TEMPLATE_TAIL_CHARS + 1)
    check("T5 ... and ends with the mark", long_tail.endswith("…"), long_tail[-10:])
    check("T5 the long form keeps the rows to the bound", len(rows_of(RD.template(ROLE, STAGE, LABEL, many, PATH))) == 40)
    dup = RD.template(ROLE, STAGE, LABEL, ["TC-1", "TC-1", " TC-2 ", ""], PATH)
    check_eq("T5 a repeated id is written once, blanks dropped", len(rows_of(dup)), 2)


def t6_empty_and_no_path() -> None:
    empty = RD.template(ROLE, STAGE, LABEL, [], PATH).splitlines()
    check_eq("T6/E-C1 an empty scope gives the header, the path and the hint line only", len(empty), 3)
    check_eq("T6 ... the path line is the path", empty[1], PATH)
    check_eq("T6/E-C1 ... no rows", rows_of("\n".join(empty)), [])
    for none in (None, "", "  "):
        text = RD.template(ROLE, STAGE, LABEL, ["TC-1"], none)
        check_in(f"T6/E-C4 path={none!r} gives the placeholder", RD.TEMPLATE_PATH_PLACEHOLDER, text)
    odd = RD.template(ROLE, STAGE, LABEL, ["TC-1 · x", "A|B"], PATH)
    check_in("E-C3 an id with a separator is written as it is", "TC-1 · x · <state> ·", odd)
    check_in("E-C3 ... both of them", "A|B · <state> ·", odd)


def seed_task(root: Path, dispatches: dict) -> None:
    task = root / "qa-factory/artifacts/QA-9"
    (task / "work").mkdir(parents=True)
    (task / "state").mkdir()
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": "QA-9", "size": "S", "environment": "local", "implementation_source": "diff",
         "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    (task / "state/controller.json").write_text(json.dumps({"scope": ["TC-001", "TC-002"], "revision": 1,
                                                            "dispatches": dispatches}), encoding="utf-8")


def t4_t7_through_the_brief() -> None:
    root = harness.temp_project("qa-digest-template-")
    try:
        harness.use_project(root)
        seed_task(root, {
            "S4-qa-case-designer-1": {"id": "S4-qa-case-designer-1", "stage": "S4", "role": "qa-case-designer",
                                      "status": "running", "scope": ["TC-001", "TC-002"]},
            "S4-qa-case-designer-2": {"id": "S4-qa-case-designer-2", "stage": "S4", "role": "qa-case-designer",
                                      "status": "running", "cases": ["TC-007", "TC-008"]},
            "S4-qa-case-designer-3": {"id": "S4-qa-case-designer-3", "stage": "S4", "role": "qa-case-designer",
                                      "status": "running", "scope": []},
            "S7-qa-bug-reporter-1": {"id": "S7-qa-bug-reporter-1", "stage": "S7", "role": "qa-bug-reporter",
                                     "status": "running", "scope": ["TC-001", "TC-002"]},
        })
        disp = {"scope": ["TC-001", "TC-002"]}
        check_eq("T7 a role outside ROLE_ITEM gets no section", brief_pack.digest_template_lines("qa-nobody", "S4", "x-1", disp), [])
        built = brief_pack.build("QA-9", "S4", ROLE, "S4-qa-case-designer-1", write=False)["markdown"]
        check_in("T7 a built S4 designer brief has the section", "## Your final message", built)
        check_in("T7 ... the first scope id as a row", "TC-001 · <state> ·", built)
        check_in("T7 ... the header with the dispatch id", f"{ROLE} S4 S4-qa-case-designer-1 · <ok|concerns|halt|impossible>", built)
        check_in("T7 ... and the stage's witness path", "\nwork/test-cases/\n", built)
        check_eq("T7 the section sits once", built.count("## Your final message"), 1)
        # T4: the gate's own scope reader
        cases_only = brief_pack.build("QA-9", "S4", ROLE, "S4-qa-case-designer-2", write=False)["markdown"]
        check("T4 a dispatch with `cases` and no `scope` gets rows from `cases`",
              "TC-007 · <state> ·" in cases_only and "TC-008 · <state> ·" in cases_only)
        check_not_in("T4 ... not the controller's scope", "TC-001 · <state> ·", cases_only)
        reporter = brief_pack.digest_template_lines("qa-bug-reporter", "S7", "S7-qa-bug-reporter-1",
                                                    {"scope": ["TC-001", "TC-002"]})
        check("T4 a bug-reporter dispatch gets no rows", reporter != [] and not any(" · <state> · " in ln for ln in reporter), str(reporter))
        check_in("T4/E-C4 ... and a `project:` witness gives the placeholder path", RD.TEMPLATE_PATH_PLACEHOLDER, "\n".join(reporter))
        check_in("T4 pin: the source of `digest_template_lines` reads the scope through the gate's reader", "_scope_of(",
                 inspect.getsource(brief_pack.digest_template_lines))
        empty = brief_pack.build("QA-9", "S4", ROLE, "S4-qa-case-designer-3", write=False)["markdown"]
        check_not_in("E-C1 an empty scope: no rows in the brief", " · <state> · ", empty)
        check_in("E-C1 ... the header and the path stay", "## Your final message", empty)
        missing = brief_pack.digest_template_lines(ROLE, "S4", "S4-nobody-9", {})
        check_not_in("E-C7/E-C1 a dispatch that is not recorded gives no rows", " · <state> · ", "\n".join(missing))
        # E-C5: a brief over 6 KB keeps the section (the section is a door, never trimmed)
        # a 1-byte ceiling cannot be met: every trimmable line goes and the brief leaves over it (the B-K7 shape of test_brief_pack)
        real_ceiling = brief_pack.BRIEF_MAX_BYTES
        brief_pack.BRIEF_MAX_BYTES = 1
        try:
            big = brief_pack.build("QA-9", "S4", ROLE, "S4-qa-case-designer-1", write=False)
        finally:
            brief_pack.BRIEF_MAX_BYTES = real_ceiling
        check("E-C5 precondition: this brief really is over the ceiling", big["bytes"] > 1024, str(big["bytes"]))
        check_in("E-C5 the section survives the 6 KB ceiling", "TC-002 · <state> ·", big["markdown"])
        # N4 (F-4, t-1755 B2): the section is the LAST one and sits OUTSIDE the budget, so it never competes with the words
        headings = [ln for ln in big["markdown"].splitlines() if ln.startswith("## ")]
        check_eq("N4 the section is the LAST heading of a brief squeezed to 1 byte", headings[-1], "## Your final message")
        check_eq("N4 ... the words come before everything but the head", headings[0], "## The person's words that concern you")
        check("N4 ... and the brief ends with the closing fence of the template", big["markdown"].rstrip().endswith("```"))
        # CI fix C raise 498 -> 1517: the charter head of t-1765 X1 (the seven SD lines, form outside the budget, capped at
        # SD_HEAD_MAX_BYTES) leaves the budget too; the template is still the 498 B left out (asserted below), the head is the 1019 B rest.
        template_bytes = len("\n".join(brief_pack.digest_template_lines(ROLE, "S4", "S4-qa-case-designer-1", {"scope": ["TC-001", "TC-002"]})).encode("utf-8")) + 1
        check_eq("N4 ... the template is 498 B", template_bytes, 498)
        check_eq("N4 ... the budget leaves the section out (and the charter head): bytes - budget_bytes", big["bytes"] - big["budget_bytes"], 1515)  # 1517 -> 1515: the FL-4 fix round trimmed 2 B of a charter head (F5, craft-line trim)
    finally:
        harness.cleanup(root)


def main() -> None:
    t1_t2_round_trip_and_negative_control()
    t3_nothing_prefilled()
    t5_bounds()
    t6_empty_and_no_path()
    t4_t7_through_the_brief()
    harness.finish("test_role_digest_template")


if __name__ == "__main__":
    main()
