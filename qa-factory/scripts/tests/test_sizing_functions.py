"""OH3-15: the story's size is counted in FUNCTIONS (the register's `## Functions` table), not in how thoroughly it is described.

Keys K1..K19 and the adversarial battery of `docs/tasks/specs/r0107-s4b-oh3-15.md` (section 2). The two golden stories are the
operator's word (30.10.2026): TP1-12586 is M and TP1-14857 is S; their registers are byte copies of the run fixtures
plus the table (`fixtures/sizing-12586/`, `fixtures/sizing-14857/`, each with a `golden.json`). Run: `python -B test_sizing_functions.py`.
No Cyrillic here (the package is English, FR-30): non-Latin names are built from escapes.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import gate_brief  # noqa: E402
import handoff_check  # noqa: E402
import human_text  # noqa: E402
import report_facts  # noqa: E402
import sizing  # noqa: E402

CONFIG_TEXT = (FIXTURES / "sizing-15045-weighted" / "qa-factory" / "config.json").read_text(encoding="utf-8")
PLUGIN = SCRIPTS.parent
HEAD = ("---\ntask: T-1\n---\n\n## Register\n\n"
        "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |\n"
        "|---|---|---|---|---|---|---|---|---|\n")
FHEAD = "| Function | Requirements |\n|---|---|\n"
CLAIMS = ("\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question | origin |\n"
          "|---|---|---|---|---|---|---|---|\n")


def row(n, verifiable="yes", impact="degraded") -> str:
    observable = f"diff:src/f{n}.py:1" if verifiable == "yes" else "none"
    return f"| R-{n} | requirement {n} | story | — | {verifiable} | — | {observable} | {impact} | new |\n"


def register(rows, functions=None, tail="") -> str:
    """A register text: `rows` (strings of `row`), then `## Functions` when `functions` is not None, then `tail`."""
    return HEAD + "".join(rows) + "\n" + ("" if functions is None else "## Functions\n\n" + functions + "\n") + tail


def ftable(*pairs) -> str:
    return FHEAD + "".join(f"| {name} | {ids} |\n" for name, ids in pairs)


def one_each(n, name="function") -> str:
    """N functions, each holding one row."""
    return ftable(*[(f"{name} {i}", f"R-{i}") for i in range(1, n + 1)])


def sized(text, ticket=None, run=False):
    """(result, task_root, project) of a register text in a private temp project (the caller cleans `project`)."""
    project = temp_dir("qa-sizing-fn-")
    (project / "qa-factory").mkdir()
    (project / "qa-factory" / "config.json").write_text(CONFIG_TEXT, encoding="utf-8")
    task = project / "qa-factory" / "artifacts" / "T-1"
    (task / "work").mkdir(parents=True)
    if text is not None:
        (task / "work" / "requirements-register.md").write_text(text, encoding="utf-8")
    result = sizing.run(task, project, ticket) if run else sizing.compute(task, project, ticket)
    return result, task, project


def once(text, ticket=None):
    result, _task, project = sized(text, ticket)
    cleanup(project)
    return result


def fixture(key, ticket=None):
    project = FIXTURES / f"sizing-{key}" / "qa-factory"
    return sizing.compute(project / "stories" / f"TP1-{key}", project.parent, ticket)


def golden(key) -> dict:
    return json.loads((FIXTURES / f"sizing-{key}" / "golden.json").read_text(encoding="utf-8"))


def line_of(data) -> str:
    """The gate line of a sizing record, through the real writer and reader (work/sizing.json on disk)."""
    base = temp_dir("qa-sizing-line-")
    try:
        (base / "work").mkdir()
        (base / "work" / "sizing.json").write_text(json.dumps(data), encoding="utf-8")
        return gate_brief.sizing_line(base)
    finally:
        cleanup(base)


def report_of(data, pipeline=None) -> str:
    """`report_facts._r_size` over a sizing record, through `_size` (the real fact builder)."""
    base = temp_dir("qa-sizing-report-")
    try:
        (base / "work").mkdir()
        (base / "work" / "sizing.json").write_text(json.dumps(data), encoding="utf-8")
        facts = {"requirements": None}
        facts["size"] = report_facts._size(base, pipeline or {}, [], {}, None, facts)
        return report_facts._r_size(facts)
    finally:
        cleanup(base)


def keys_of(result, *names):
    return {k: result[k] for k in names}


def main() -> int:
    # --- K1 golden M: 12586 ---
    g = golden(12586)
    r = fixture(12586)
    check_eq("K1: 12586 is the operator's M (golden.json), counted in functions", (r["size"], r["size_unit"]), (g["size"], "functions"))
    check_eq("K1: four functions (the grain of 14857, C-3)", r["function_count"], 4)
    check_eq("K1: every verifiable row is placed, none unknown", (r["functions_unlisted"], r["functions_unknown_ids"]), ([], []))
    check_eq("K1: the weight is what it was: 43 (R5), ceiling 28, over by 15", (r["computed_budget"], r["cap"], r["overage"]), (43, 28, 15))
    check_eq("K1: U (cited_files) is printed beside N", r["cited_files"], 5)
    # --- K1b golden S: 14857, both worlds of the defect cap ---
    g = golden(14857)
    r = fixture(14857)
    check_eq("K1b: 14857 is the operator's S (ticket type unknown)", (r["size"], r["size_unit"], r["function_count"]), (g["size"], "functions", 2))
    check_eq("K1b: all 18 verifiable rows are listed: nothing unlisted, nothing unknown", (r["functions_unlisted"], r["functions_unknown_ids"]), ([], []))
    check_eq("K1b: no ticket type: budget 32 against a ceiling of 28", (r["computed_budget"], r["cap"], "computed_budget_uncapped" in r), (32, 28, False))
    r = fixture(14857, g["ticket_type"])
    check_eq("K1b: a Bug is S too (F-9 a): the size follows the functions", (r["size"], r["size_unit"]), (g["size"], "functions"))
    check_eq("K1b: and the defect cap still limits what is planned",
             keys_of(r, "computed_budget", "cap", "recommended_budget", "computed_budget_uncapped"),
             {"computed_budget": 1, "cap": 2, "recommended_budget": 1, "computed_budget_uncapped": 32})
    check("K1b: no budget_band key (no reader, C-6)", "budget_band" not in r)

    # --- K2 detail invariance ---
    base = once(register([row(i) for i in range(1, 5)], one_each(4)))
    more = once(register([row(i) for i in range(1, 8)],
                         ftable(("function 1", "R-1, R-5, R-6, R-7"), ("function 2", "R-2"), ("function 3", "R-3"), ("function 4", "R-4"))))
    check_eq("K2: three more rows in one function: size and N unchanged", (more["size"], more["function_count"]), (base["size"], base["function_count"]))
    check("K2: but the weight is higher", more["computed_budget"] > base["computed_budget"], f"{more['computed_budget']} vs {base['computed_budget']}")

    # --- K3 boundaries (each function one verifiable row; N=0 is K12) ---
    for n, want in ((1, "XS"), (2, "S"), (3, "M"), (5, "M"), (6, "L"), (9, "L"), (10, "XL"), (14, "XL"), (15, "XXL")):
        got = once(register([row(i) for i in range(1, n + 1)], one_each(n)))
        check_eq(f"K3: {n} functions -> {want}", (got["size"], got["function_count"]), (want, n))

    # --- K4 absent table: the old world, every old pin ---
    old = sizing.compute(FIXTURES / "sizing-15045" / "qa-factory" / "stories" / "TP1-15045", FIXTURES / "sizing-15045")
    # OH3-34 (critic B-1): an area names a surface ONLY through a path token. None of 15045's nine P1 areas holds one ("API integrations
    # (GitLab, Jira, Confluence, MCP)" has a kind word and no path), so no row is placed in an area and nothing is bumped: the budget is the
    # old 28 and the pin is the old ('XL', 28, 0). Derived from the rule; the kind-word rule gave 30 / XXL / 2 by bumping R-10..R-12, which
    # are the `/validate` dry-run and no integration.
    check_eq("K4: 15045 without a table: XL, ceiling 28, no overage (no area names a path, so nothing is bumped)",
             (old["size"], old["cap"], old["overage"], old["computed_budget"]), ("XL", 28, 0, 28))
    check_eq("K4: the unit says requirements, and there is no count", (old["size_unit"], old["function_count"]), ("requirements", None))
    check_in("K4: the reasoning names the absent table", "has no '## Functions' table", old["reasoning"])
    # --- K5 empty table ---
    for label, table in (("header only", FHEAD), ("every requirements cell blank", ftable(("a", ""), ("b", "  ")))):
        got = once(register([row(1), row(2)], table))
        check_eq(f"K5: {label}: as K4 (the weight's band, unit requirements)", (got["size"], got["size_unit"]), ("S", "requirements"))
        check_in(f"K5: {label}: says the table is there and empty", "is there and empty", got["reasoning"])
        check_not_in(f"K5: {label}: and is not the absent-table sentence", "has no '## Functions' table", got["reasoning"])
    # --- K5b one blank cell among several ---
    got = once(register([row(1), row(2), row(3)], ftable(("alpha", "R-1"), ("beta", ""), ("gamma", "R-2, R-3"))))
    check_eq("K5b: the blank function is not counted, the others are", (got["function_count"], [f["name"] for f in got["functions"]]), (2, ["alpha", "gamma"]))
    check_in("K5b: the blank function is named in the reasoning", "blank requirements cell are not counted: beta", got["reasoning"])
    # --- K6 unlisted row: its own function, said aloud ---
    got = once(register([row(i) for i in range(1, 5)], ftable(("a", "R-1"), ("b", "R-2"), ("c", "R-3"))))
    check_eq("K6: 3 functions + one row in none = N 4, the row named by its id", (got["function_count"], got["functions_unlisted"]), (4, ["R-4"]))
    check_in("K6: the line says '4 functions, 1 of them requirements nobody placed'", "4 functions, 1 of them requirements nobody placed: a, b, c, R-4", line_of(got))
    check_in("K6: the reasoning names the row", "R-4", [x for x in got["reasoning"] if "in no function" in x])
    many = once(register([row(i) for i in range(1, 17)], ftable(("one", "R-99"))))
    check_eq("K6: R-99 only plus 16 verifiable rows is 16 functions", (many["function_count"], len(many["functions_unlisted"]), many["functions"]), (16, 16, []))
    check_in("K6: and the line never reads as a plain count", "16 functions, 16 of them requirements nobody placed", line_of(many))
    # --- K6b rows projected after S2 ---
    claim = "| R-3 | 400 | absent | 403 | diff:src/f3.py:1 | yes | Q1 | S3-grounding |\n"
    got = once(register([row(i) for i in range(1, 4)], ftable(("a", "R-1"), ("b", "R-2")), CLAIMS + claim))
    check_eq("K6b: an S3-grounding row in no function is not an unlisted function (N stays 2)", (got["function_count"], got["functions_unlisted"]), (2, []))
    check_in("K6b: it is named in the reasoning", "added after S2 by the grounding step, in no function and not counted as one: R-3", got["reasoning"])
    ctrl = once(register([row(i) for i in range(1, 4)], ftable(("a", "R-1"), ("b", "R-2")), CLAIMS + claim.replace("S3-grounding", "")))
    check_eq("K6b control: the same row with no origin IS counted (N 3)", (ctrl["function_count"], ctrl["functions_unlisted"]), (3, ["R-3"]))
    # --- K7 unknown id ---
    got = once(register([row(1), row(2)], ftable(("ghost", "R-99"), ("real", "R-1, R-98"), ("rest", "R-2"))))
    check_eq("K7: R-99 alone is not a function; R-1 with R-98 is one", [f["name"] for f in got["functions"]], ["real", "rest"])
    check_eq("K7: both unknown ids are named", got["functions_unknown_ids"], ["R-98", "R-99"])
    # --- K8 unverifiable ---
    got = once(register([row(1), row(2, "no"), row(3)], ftable(("only the unverifiable", "R-2"), ("live", "R-1, R-3"))))
    check_eq("K8: a function of unverifiable rows only is not counted", (got["function_count"], [f["name"] for f in got["functions"]]), (1, ["live"]))
    check_eq("K8: the row stays in unverifiable[], and is not 'unknown'", ([u["r"] for u in got["unverifiable"]], got["functions_unknown_ids"]), (["R-2"], []))
    check_in("K8: the function is named in the reasoning", "function 'only the unverifiable' holds no verifiable requirement - not counted (R-2 unverifiable)", got["reasoning"])
    # --- K9 shared row ---
    rows3 = [row(i) for i in range(1, 4)]
    shared = once(register(rows3, ftable(("f1", "R-1, R-2"), ("f2", "R-2, R-3"))))
    bare = once(register(rows3))
    check_eq("K9: one R in two functions: both count", shared["function_count"], 2)
    check_eq("K9: the weight counts the row once", shared["computed_budget"], bare["computed_budget"])
    # --- K10 same name ---
    got = once(register([row(1), row(2), row(3)], ftable(("Move", "R-1"), (" move ", "R-2"), ("MOVE  ", "R-1, R-3"), ("the  move", "R-3"), ("the move", "R-1"))))
    check_eq("K10: case and whitespace folded: 'Move' x3 is one function with the union, 'the move' another",
             [(f["name"], f["requirements"]) for f in got["functions"]], [("Move", ["R-1", "R-2", "R-3"]), ("the move", ["R-3", "R-1"])])
    # --- K11 defect ---
    r12586 = fixture(12586, "Bug")
    check_eq("K11: a defect with named functions: size by functions, budget and ceiling by the defect cap",
             (r12586["size"], r12586["size_unit"], r12586["computed_budget"], r12586["cap"], r12586["recommended_budget"]), ("M", "functions", 1, 2, 1))
    old_bug = once(register([row(i) for i in range(1, 6)]), "Bug")
    check_eq("K11: old world with a Bug: XS as today, unit requirements", (old_bug["size"], old_bug["size_unit"], old_bug["computed_budget"]), ("XS", "requirements", 1))
    check_eq("K11: the functions are still listed in the new world", len(r12586["functions"]), 4)
    # --- F-3 the notes follow the folding: a row folded into a counted function is not "not counted" / "not placed" ---
    got = once(register([row(1), row(2)], ftable(("Move", "R-99"), ("move", "R-1, R-2"))))
    check_eq("F-3: same name, unknown-id row: N=1", got["function_count"], 1)
    check_not_in("F-3: no 'holds no verifiable requirement' for a name that is counted", "holds no verifiable", "\n".join(got["reasoning"]))
    got = once(register([row(1), row(2)], ftable(("Move", ""), ("move", "R-1, R-2"))))
    check_not_in("F-3: no 'blank requirements cell' for a name that is counted", "blank requirements cell", "\n".join(got["reasoning"]))
    got = once(register([row(1), row(2)], ftable(("-", "R-1"), ("real", "R-1, R-2"))))
    check_eq("F-3: an unnamed row's id placed elsewhere: N=1", got["function_count"], 1)
    check_not_in("F-3: and it is not called 'not placed'", "not placed", "\n".join(got["reasoning"]))
    got = once(register([row(1), row(2)], ftable(("-", "R-1"), ("real", "R-2"))))
    check_in("F-3 control: an id placed nowhere is still named", "no name are not placed: R-1", "\n".join(got["reasoning"]))
    got = once(register([row(1), row(2)], ftable(("Move", ""), ("real", "R-1, R-2"))))
    check_in("F-3 control: a blank row of a name nobody counts is still named", "blank requirements cell are not counted: Move", "\n".join(got["reasoning"]))

    # --- F-6 an old-world Bug record (no table): the defect sentence ---
    old_bug_line = line_of(old_bug)
    check_in("F-6: a new old-world Bug record says the defect sentence", "a defect ticket: 1 regression case is planned (uncapped, the requirements weigh", old_bug_line)

    # --- K11b the defect line, twins ---
    said = "a defect ticket: 1 regression case is planned (uncapped, the requirements weigh 32)"
    r14857 = fixture(14857, "Bug")
    for label, text in (("gate line", line_of(r14857)), ("report", report_of(r14857))):
        check_in(f"K11b: the {label} says the one ceiling", said, text)
        check_not_in(f"K11b: the {label} never says 'the requirements weigh 1'", "the requirements weigh 1 ", text.replace(")", " "))
        check_not_in(f"K11b: the {label} does not print the XS band as a second ceiling", "the test ceiling is 2", text)
    plain = fixture(14857)
    check_in("K11b: with no defect cap the sentence is the plain weight", "the requirements weigh 32 (each weighted", line_of(plain))
    check_not_in("K11b: and no defect sentence", "a defect ticket", line_of(plain))
    old_defect = {"size": "XS", "cap": 2, "computed_budget": 1, "recommended_budget": 1, "overage": 0, "reducers_applied": [{"name": "defect-cap"}]}
    check_in("K11b: an older record (no computed_budget_uncapped) keeps its old sentence", "the requirements weigh 1 (each weighted", line_of(old_defect))

    # --- K12 no register, nothing verifiable ---
    got = once(None)
    check_eq("K12: no register: XS, unit requirements, no exception", (got["size"], got["size_unit"], got["function_count"]), ("XS", "requirements", None))
    got = once(register([row(1, "no"), row(2, "no")], ftable(("only", "R-1, R-2"))))
    check_eq("K12: a table with nothing verifiable: XS, N=0, unit functions", (got["size"], got["size_unit"], got["function_count"]), ("XS", "functions", 0))

    # --- K13 the advice never says split or decompose, in either world ---
    heavy_rows = [row(i, impact="data-loss") for i in range(1, 21)]          # 20 x 3.2 = 64 > 28, no table
    old_xxl = once(register(heavy_rows))
    new_xxl = once(register([row(i) for i in range(1, 16)], one_each(15)))
    for label, got, advice in (("old world", old_xxl, sizing.XXL_ADVICE_ROWS), ("new world", new_xxl, sizing.XXL_ADVICE_FUNCTIONS)):
        check_eq(f"K13: {label} is XXL", got["size"], "XXL")
        text = "\n".join(got["reasoning"]) + "\n" + line_of(got)
        check_in(f"K13: {label}: reasoning and gate line carry the advice", advice, text)
        for word in ("decompos", "split", "several stories"):
            check_not_in(f"K13: {label}: no '{word}'", word, text.lower())
    check_in("K13: the new world offers both moves", "name the functions to leave out", line_of(new_xxl))
    check_in("K13: and the old one", "say what to leave out", line_of(old_xxl))
    check_in("K13: the overage sentence says 'test ceiling' in the new world", "exceeds the test ceiling of 28", new_xxl["reasoning"])
    check_in("K13: old world keeps its own overage words", "exceeds the XXL cap of 28", old_xxl["reasoning"])

    # --- K14 the gate line ---
    for n, tail in ((6, "alpha, beta, gamma, delta, epsilon, zeta"), (7, "alpha, beta, gamma, delta, epsilon, zeta and 1 more")):
        names = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"][:n]
        got = once(register([row(i) for i in range(1, n + 1)], ftable(*[(names[i - 1], f"R-{i}") for i in range(1, n + 1)])))
        check_in(f"K14: N={n}: {tail!r}", f"({n} functions: {tail})", line_of(got))
    check_in("K14: N>=15 points at the full list", "listed in full in work/sizing.json", line_of(new_xxl))
    check_eq("K14: and the whole list is in sizing.json", len(new_xxl["functions"]), 15)
    old_line = line_of({"size": "M", "cap": 10, "computed_budget": 8, "overage": 0, "unverifiable": []})
    check_eq("K14: an old-world line is byte-identical to today's", old_line,
             "**Size** — size **M**, the requirements weigh 8 (each weighted by its priority and area); the M cap is 10. Arithmetic: work/sizing.json.")
    check_in("K14: the old-world XXL tail is the new advice, nothing about splitting",
             sizing.XXL_ADVICE_ROWS, line_of({"size": "XXL", "cap": 28, "computed_budget": 34, "overage": 6}))

    # --- K15 twins: the same phrases through the gate line and the report ---
    r = fixture(12586)
    gate, rep = line_of(r), report_of(r)
    words = sizing.function_words(r)
    check_in("K15: the function phrase is the same words, gate line", f"({words})", gate)
    check_in("K15: the function phrase is the same words, report", f"({words})", rep)
    check_in("K15: the gate line's phrase, literally", "(4 functions: change the project of an integration in the UI, the move itself: settings and links follow, atomically, who may move, and what a refusal says, both projects refresh after the move)", gate)
    check_in("K15: the ceiling phrase, gate line", "the test ceiling is 28", gate)
    check_in("K15: the ceiling phrase, report", "the test ceiling is 28", rep)
    check_in("K15: the same weight sentence, both", "the requirements weigh 43 (each weighted by its priority and area)", gate + rep)
    check_in("K15: the gate line says by how much", "**over it by 15**", gate)
    check_not_in("K15: neither says 'the M cap' in the new world", "M cap", gate + rep)
    # --- F-1: the pipeline's recorded label differs from sizing.json's size (a re-run): the report names both ---
    two = once(register([row(1), row(2)], ftable(("a", "R-1"), ("b", "R-2"))))
    stale = report_of(two, {"size_initial": "XXL"})
    check_in("F-1: the stale label and the current one are both named", "Forecast: **XXL** (recorded; work/sizing.json now says S, 2 functions: a, b)", stale)
    check_not_in("F-1 control: with the same label there is no 'recorded;'", "recorded;", report_of(two, {"size_initial": "S"}))
    # --- AR-16: both new sentences are text a person reads ---
    for label, text in (("function sentence", words), ("XXL advice, functions", sizing.XXL_ADVICE_FUNCTIONS), ("XXL advice, rows", sizing.XXL_ADVICE_ROWS),
                        ("defect sentence", sizing.defect_words(r14857)), ("heavy-function note", "one function named for 6 requirements (a coarse grain sizes the story low)")):
        check_eq(f"AR-16: human_text.problems over the {label}", human_text.problems(text, kind="report"), [])

    # --- K16 override survives, the size stays computed, the handoff claim reads sizing.json ---
    text = register([row(i) for i in range(1, 4)], one_each(3))
    first, task, project = sized(text, run=True)
    try:
        again = sizing.run(task, project, None, "L", "two teams")
        later = sizing.run(task, project)
        check_eq("K16: the override survives a re-run", (later["size_override"], later["size_override_reason"]), ("L", "two teams"))
        check_eq("K16: the size stays the computed one", (again["size"], later["size"]), ("M", "M"))

        class Art:
            def json(self, rel):
                return json.loads((task / rel).read_text(encoding="utf-8"))
        check_eq("K16: the handoff claim `size.computed` reads sizing.json's size", handoff_check._size(Art(), None), ("M", "sizing.json"))
    finally:
        cleanup(project)

    # --- K17 one heavy function ---
    five = once(register([row(i) for i in range(1, 6)], ftable(("everything", "R-1, R-2, R-3, R-4, R-5"))))
    six = once(register([row(i) for i in range(1, 7)], ftable(("everything", "R-1, R-2, R-3, R-4, R-5, R-6"))))
    check_eq("K17: at 5 requirements: no note", (sizing.heavy_words(five), "named for" in " ".join(five["reasoning"])), ("", False))
    check_eq("K17: at 6: said, in the reasoning, the gate line and the report",
             ["one function named for 6 requirements" in t for t in ("\n".join(six["reasoning"]), line_of(six), report_of(six))], [True, True, True])
    check_eq("K17: loud, never silent: one function is XS", six["size"], "XS")
    two = once(register([row(i) for i in range(1, 8)], ftable(("a", "R-1, R-2, R-3, R-4, R-5, R-6"), ("b", "R-7"))))
    check_eq("K17: two functions never trigger it", sizing.heavy_words(two), "")

    # --- K18 nothing is cut: the table moves only the size and its own keys ---
    rows = [row(i) for i in range(1, 9)]
    with_table = once(register(rows, ftable(("a", "R-1, R-2, R-3, R-4"), ("b", "R-5, R-6, R-7, R-8"))))
    without = once(register(rows))
    same = ("requirements", "verifiable_count", "unverifiable", "computed_budget", "computed_budget_raw", "recommended_budget", "cap", "overage", "cited_files")
    check_eq("K18: the same register with and without the table: every other key is equal",
             keys_of(with_table, *same), keys_of(without, *same))
    check_eq("K18: only the size and the function keys differ",
             sorted(k for k in with_table if with_table[k] != without[k] and k != "reasoning"),
             ["function_count", "functions", "size", "size_unit"])

    # --- K19 S3 reads the ceiling from sizing.json, not from a size -> number pairing ---
    candidacy = (PLUGIN / "references" / "automation-candidacy.md").read_text(encoding="utf-8")
    charter = (PLUGIN / "agents" / "qa-test-strategist.md").read_text(encoding="utf-8")
    form = (PLUGIN / "handoffs" / "s3-strategist-to-designer.yaml").read_text(encoding="utf-8")
    check("K19: no `size -> number` pairing in automation-candidacy.md", not re.search(r"\b(XS|S|M|L|XL)\s+\d+\b", candidacy), "a pairing like 'M 10' is back")
    for label, text in (("the charter", charter), ("the candidacy file", candidacy), ("the s3 form", form)):
        check_not_in(f"K19: {label}: no 'a size reconsideration'", "size reconsideration", text)
    check("K19: no 'size cap' anywhere in the charter (F-2)", "size cap" not in charter.lower(), "the charter still says 'size cap'")
    check("K19: the charter points at `cap` in work/sizing.json", "`cap` in `work/sizing.json`" in charter)
    check("K19: the candidacy file names `cap` in work/sizing.json as the ceiling", "`cap` in that file" in candidacy and "`work/sizing.json`" in candidacy)
    check("K19: the s3 form's budget.cap comment names sizing.json `cap`", "`cap` in work/sizing.json" in form)

    # --- the adversarial battery: a role-written table never raises, errs upward ---
    big = once(register([row(i) for i in range(1, 501)], one_each(500)))
    check_eq("battery: 500 functions: N=500, XXL", (big["function_count"], big["size"]), (500, "XXL"))
    check_in("battery: 500 functions: the line is clipped at six names", "and 494 more", line_of(big))
    long_name = "x" * 10000
    got = once(register([row(1), row(2)], ftable((long_name, "R-1"), ("short", "R-2"))))
    check_eq("battery: a 10000-character name is counted once and kept whole", (got["function_count"], len(got["functions"][0]["name"])), (2, 10000))
    check_eq("battery: displayed at 60 characters + '...'", sizing.clip_name(long_name), "x" * 60 + "...")
    check_eq("battery: AT the limit (60) it is whole, BEYOND (61) it is clipped", (sizing.clip_name("y" * 60), sizing.clip_name("y" * 61)), ("y" * 60, "y" * 60 + "..."))
    check_in("battery: the clipped name is what the line shows", "x" * 60 + "...", line_of(got))
    non_latin = "".join(chr(code) for code in (0x43C, 0x435, 0x442, 0x43E, 0x434, 0x20, 0x1F600))   # code points, so this file stays Cyrillic-free
    got = once(register([row(1)], ftable((non_latin, "R-1"))))
    check_eq("battery: a non-Latin or emoji name is counted and shown as it is", (got["function_count"], got["functions"][0]["name"]), (1, non_latin))
    got = once(register([row(i) for i in range(1, 7)], ftable(("range", "R-1..R-5"))))
    check_eq("battery: `R-1..R-5` is no id: nothing is placed by it, every row is its own function (upward)", (got["function_count"], len(got["functions_unlisted"])), (6, 6))
    got = once(register([row(i) for i in range(1, 7)], ftable(("to", "R-1 to R-5"))))
    check_eq("battery: `R-1 to R-5` places R-1 and R-5 only: 1 function + 4 unlisted rows",
             (got["function_count"], got["functions"][0]["requirements"], got["functions_unlisted"]), (5, ["R-1", "R-5"], ["R-2", "R-3", "R-4", "R-6"]))
    got = once(register([row(i) for i in range(1, 5)], ftable(("semi", "R-1;R-2"), ("space", "R-3 R-4"))))
    check_eq("battery: `R-1;R-2` and `R-3 R-4` are read as two ids each", (got["function_count"], got["functions_unlisted"], [f["requirements"] for f in got["functions"]]),
             (2, [], [["R-1", "R-2"], ["R-3", "R-4"]]))
    got = once(register([row(i) for i in range(1, 5)], ftable(("comma", "R-1,R-2"), ("ticks", "`R-3`, `R-4`"))))
    check_eq("battery: `R-1,R-2` and backticked ids are read", (got["function_count"], got["functions_unlisted"]), (2, []))
    got = once(register([row(1), row(2)], FHEAD + "| a | b | R-1, R-2 |\n"))
    check_eq("battery: a pipe inside a name shifts the cells: not counted, rows unlisted (upward)", (got["function_count"], got["functions_unlisted"]), (2, ["R-1", "R-2"]))
    got = once(register([row(1), row(2)], ftable(("lower", "r-1, r-2"))))
    check_eq("battery: lower-case r-1 is no id: named, the rows unlisted", (got["function_count"], got["functions_unknown_ids"]), (2, ["r-1", "r-2"]))
    got = once(register([row(1), row(2)], "| Name | Notes |\n|---|---|\n| a | b |\n"))
    check_eq("battery: a table without the headers: as K5, the missing header is named", got["size_unit"], "requirements")
    check_in("battery: ... by name", "has no function and requirements header", got["reasoning"])
    got = once(register([row(1), row(2)], ftable(("first", "R-1")) + "\n## Functions\n\n" + ftable(("second", "R-2"))))
    check_eq("battery: two '## Functions' headings: the first is read, a note says so", ([f["name"] for f in got["functions"]], got["functions_unlisted"]), (["first"], ["R-2"]))
    check_in("battery: and the note", "holds 2 '## Functions' headings - the first is read", got["reasoning"])
    got = once(register([row(1), row(2), row(3)], ftable(("-", "R-1"), ("—", "R-2"), ("none", "R-3"), ("", "R-1"))))
    check_eq("battery: names that name nothing (`-`, dash, `none`, empty): the rows are unlisted", (got["functions"], got["functions_unlisted"]), ([], ["R-1", "R-2", "R-3"]))
    got = once(register([row(i) for i in range(1, 31)], ftable(("everything", ", ".join(f"R-{i}" for i in range(1, 31))))))
    check_eq("battery: one function holding a large register: XS and LOUD", (got["size"], bool(sizing.heavy_words(got))), ("XS", True))

    # --- AR-13: one reader of the table, found by the same grep that finds the register's readers ---
    readers = sorted(p.name for p in SCRIPTS.glob("*.py") if "## Functions" in p.read_text(encoding="utf-8", errors="replace"))
    check_eq("AR-13: `## Functions` is read in one script", readers, ["sizing.py"])
    control = [p.name for p in SCRIPTS.glob("*.py") if "## Register" in p.read_text(encoding="utf-8", errors="replace")]
    check("AR-13 control: the same grep finds `## Register` in several scripts", len(control) > 3, str(control))
    return 0


if __name__ == "__main__":
    main()
    finish("test_sizing_functions")
