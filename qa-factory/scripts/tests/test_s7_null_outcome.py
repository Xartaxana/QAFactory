#!/usr/bin/env python3
"""S7 may end with nothing to repair, and that is a recorded result (FR-23, t-299).

TP1-15045, rehearsal on cmp2r, 02.10: the failure analyst triaged seven failures - two product bugs and
five stand blocks, not one of them a test defect - and the handover form it had to fill has `scope`, the one
list the check refuses empty. `scope: []` was refused ("scope: no rows"); a scope row would have been an
invented repair; the conductor could not tell the person's way past the form from the form's own repair and
stopped the story. The contract now carries a `null_outcome` block, and the check accepts an empty `scope` only
while `work/triage.json` agrees.

What is proved here (keys K1-K3, K7 and edges S1-S4 of t-294 node B):
  * K1  the cmp2r shape - 2 APP_BUG, 5 ENV_ISSUE, `scope: []`, `header.window: none`, seven `not_for_repair`
        rows - is accepted by the check, by the CLI and by `story_step finish` (exit 0, "accepted", the stage
        complete); under `--fix` the seven rows are opened by code, with their verdicts, and the role is left
        only `where_it_went`.
  * K2  every way an empty `scope` could hide a repair is refused, naming the instance or the reason: one
        TEST_BUG among seven rows, TEST_BUG:collection, a FLAKY row already fixed, a verdict in another case, a
        verdict nobody knows, a missing / malformed / mis-shaped triage, a triage row not listed, an id listed
        that nobody triaged, and - with no triage row at all - a run report that shows a failure.
  * K3  every other contract behaves as it did: the scribe form with an empty scope is still refused, and no
        contract but the S7 one names a null outcome.
  * S4  `header.window: none` beside a `scope` that lists a repair is refused.
  * K7  the refusal of `finish` keeps its first line byte for byte (the driver routes on it) and says that a
        person's word passes the form for one dispatch.
"""
import contextlib
import io
import json
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, driver_sources, finish,  # noqa: E402
                     run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as HC  # noqa: E402
import handoff_init  # noqa: E402

CONTRACT = "s7-analyst-to-automator"
TICKET = "QA-NULL-1"
DISPATCH = "S7-qa-failure-analyst-1"

# The cmp2r triage, in the shapes its rows really had: an instance row names `instance_id` and `test`, a manual
# check names only its `case`.
APP_BUG_A = "test_validate_rejects_bad_input_with_same_code_as_put[json]"
APP_BUG_B = "test_put_invalid_input_returns_stable_code_and_stores_nothing[multi]"
ENV_A = "test_version_history_button_accessible_from_visual_editor[chromium]"
ENV_B = "test_shortcuts_with_history_popup_open_change_neither_diff_nor_editor[chromium]"
MANUAL = ["TP1-15045_TC_005", "TP1-15045_TC_007", "TP1-15045_TC_009"]


def instance_row(instance: str, verdict: str, **extra) -> dict:
    return {"test": "tests/test_x.py::" + instance, "instance_id": instance, "verdict": verdict,
            "evidence": "evidence/runs/x.json", "attempt_id": "a1", **extra}


def manual_row(case: str, verdict: str = "ENV_ISSUE") -> dict:
    return {"case": case, "verdict": verdict, "evidence": "evidence/manual/x.json"}


def cmp2r_rows() -> list:
    return ([instance_row(APP_BUG_A, "APP_BUG"), instance_row(APP_BUG_B, "APP_BUG"),
             instance_row(ENV_A, "ENV_ISSUE"), instance_row(ENV_B, "ENV_ISSUE")]
            + [manual_row(case) for case in MANUAL])


def first_id(row: dict) -> str:
    return row.get("instance_id") or row.get("case") or ""


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


def a_task(rows=None, *, report="clean") -> Path:
    """A task root with a triage (`rows`, or no file at all for None) and a run report."""
    task = temp_dir("qa-s7-null-")
    if rows is not None:
        write_json(task / "work" / "triage.json", {"schema_version": 2, "task_id": TICKET, "triage": rows})
    if report == "clean":
        # a real report always carries `current_results` (finalize_task.reduce writes it, empty when nothing is current);
        # t-323 B4: with rows present a report with no results list is a refusal, so the fixture has the list
        write_json(task / "work" / "run-report.json", {"execution_status": "passed", "current_results": [],
                                                       "current_totals": {"passed": 12}, "current_manual_checks": []})
    elif report is not None:
        write_json(task / "work" / "run-report.json", report)
    return task


def untouched_form() -> str:
    text = (handoff.CONTRACTS / f"{CONTRACT}.yaml").read_text(encoding="utf-8")
    return handoff_init.fill_head(text, task=TICKET, dispatch=DISPATCH, role="qa-failure-analyst",
                                  stage="S7", scope="")


def replace_section(text: str, name: str, body: str) -> str:
    """Swap one top-level section of a form for `body`; the comment lines of the NEXT section stay."""
    done = re.sub(r"(?ms)^" + re.escape(name) + r":.*?(?=^\S)", body.rstrip("\n") + "\n\n", text, count=1)
    assert done != text, f"section {name} not found"
    return done


def nfr_block(rows: list, where: str = "bug-drafts/x.json") -> str:
    if not rows:
        return "not_for_repair: []"
    out = ["not_for_repair:"]
    for ident, verdict in rows:
        out += [f"  - id: {handoff._render(ident)}", f"    verdict: {verdict}", f"    where_it_went: {where}"]
    return "\n".join(out)


def scope_block(rows: list) -> str:
    if not rows:
        return "scope: []"
    out = ["scope:"]
    for ident, state in rows:
        out += [f"  - id: {handoff._render(ident)}", f"    state: {state}", "    reason: the test waits for a race",
                f"    case: {TICKET}_TC_001", "    round: 1 of 2"]
    return "\n".join(out)


def a_form(*, scope=(), nfr=None, window="none", filled=True) -> str:
    """The real contract, headed by `handoff_init`, with every other field filled the way a role fills it.
    `nfr`: [(id, verdict)] rows, or None to leave the template's example row, [] to write `[]`."""
    text = untouched_form()
    doc = handoff.parse(text)
    for path, value in (("inputs_read[0].version", "cfa50cc02493c8b8"), ("inputs_read[0].failures", 7),
                        ("inputs_read[1].path", "work/triage.json"),
                        ("inputs_read[1].version", "runtime-1"), ("header.verdict", "concerns"),
                        ("header.window", window),
                        ("claims.every_repair_names_evidence_expected_and_check", True),
                        ("claims.no_app_bug_expectation_was_handed_for_repair", True),
                        ("claims.every_flaky_verdict_carries_three_isolated_reruns_and_a_mechanism", True)):
        handoff.set_value(doc, path, value)
        doc = handoff.parse(doc.text())
    text = doc.text()
    text = replace_section(text, "scope", scope_block(list(scope)))
    text = replace_section(text, "repairs", "repairs: []")
    text = replace_section(text, "unresolved", "unresolved: []")
    if nfr is not None:
        text = replace_section(text, "not_for_repair", nfr_block(nfr))
    return text


NOT_REPAIRED = ("APP_BUG", "ENV_ISSUE", "APP_CHANGED", "CASE_DEFECT")


def nfr_of(rows: list) -> list:
    """The `not_for_repair` rows a careful role would write for these triage rows: every one that has an id,
    with a verdict of the field's own list (a row whose verdict is a repair or unknown is listed as ENV_ISSUE -
    what is under test is the empty scope, not the listing)."""
    return [(first_id(row), row.get("verdict") if row.get("verdict") in NOT_REPAIRED else "ENV_ISSUE")
            for row in rows if isinstance(row, dict) and first_id(row)]


def verdict_of(form: str, task: Path, *, fix: bool = False) -> tuple:
    """`handoff_check.check` over a form text: (doc, fixed, problems, derived)."""
    doc, fixed, problems, _judged, derived = HC.check(handoff.parse(form), CONTRACT, HC.Artifacts(task),
                                                      fix=fix, use_judge=False)
    return doc, fixed, problems, derived


def text_of(problems: list) -> str:
    return "\n".join(f"{p.path}: {p.text} || {p.fix}" for p in problems)


# ---------------------------------------------------------------------------------------------- K1
def the_cmp2r_shape_is_accepted() -> None:
    rows = cmp2r_rows()
    task = a_task(rows)
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
        check_eq("K1: scope [], window none and seven not_for_repair rows: no problem", [p.path for p in problems], [])
        # the window word is not required: an empty scope with the ticket as its window is the same answer
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows), window=TICKET), task)
        check_eq("an empty scope with the ticket in `window` is accepted too", [p.path for p in problems], [])
        # the null outcome opens nothing for a contract that names none: and for this one, no rows are touched
        # when the role wrote them
        doc, fixed, problems, derived = verdict_of(a_form(nfr=nfr_of(rows)), task, fix=True)
        check_eq("with --fix and the rows already written: nothing opened, nothing derived",
                 ([f for f in fixed if "not_for_repair" in f], derived), ([], []))
        check_eq("...and the seven rows are the role's own, untouched", len(doc.data["not_for_repair"]), 7)
    finally:
        cleanup(task)


def a_reorder_row_is_a_repair() -> None:
    """AR-23 (t-1508 R7): a triage row that carries `reorder` IS a repair - the empty scope is refused while one stands, an APP_BUG row
    alone included; `reorder: false` and no key keep the null outcome as before; the key is unchanged for a row with no `reorder`."""
    for label, extra, refused in (("APP_BUG + reorder true alone", {"reorder": True}, True),
                                  ("a malformed reorder (a string) is refused, not skipped", {"reorder": "yes"}, True),
                                  ("reorder false", {"reorder": False}, False), ("no reorder key", {}, False)):
        rows = [instance_row(APP_BUG_A, "APP_BUG", **extra)]
        task = a_task(rows)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
            text = text_of(problems)
            check_eq(f"AR-23 {label}: the empty scope is {'refused' if refused else 'accepted'}", bool(problems), refused)
            if refused:
                check_in(f"AR-23 {label}: and the refusal names the row", APP_BUG_A, text)
                check_in(f"F14 {label}: and says a row that asks for a `reorder` is a repair, so 'nothing to repair' is true of it",
                         ", and no row that asks for a `reorder`.", text)
        finally:
            cleanup(task)


def fix_opens_the_rows_from_the_triage() -> None:
    rows = cmp2r_rows()
    task = a_task(rows)
    try:
        for label, nfr in (("the template's example row left in place", None), ("`not_for_repair: []`", []),
                           ("the section left out", "absent")):
            form = a_form(nfr=nfr if nfr != "absent" else None)
            if nfr == "absent":
                form = replace_section(form, "not_for_repair", "")
            doc, fixed, problems, derived = verdict_of(form, task, fix=True)
            opened = doc.data.get("not_for_repair") or []
            check_eq(f"--fix, {label}: seven rows are opened, in the triage's order, each with its verdict",
                     [(r.get("id"), r.get("verdict")) for r in opened], nfr_of(rows))
            check_eq(f"--fix, {label}: the role is left only `where_it_went`, one problem per row",
                     sorted(p.path for p in problems), [f"not_for_repair[{i}].where_it_went" for i in range(7)])
            check_in(f"--fix, {label}: said as 'filled by code'", "not_for_repair = 7 row(s) opened", fixed)
            check_eq(f"--fix, {label}: recorded as derived, so an untouched form still reads untouched",
                     sorted(d["field"] for d in derived),
                     sorted(f"not_for_repair[{i}].{n}" for i in range(7) for n in ("id", "verdict")))
            check_eq(f"--fix, {label}: the where_it_went the role must write is still the contract's placeholder",
                     {handoff.is_placeholder(r.get("where_it_went")) for r in opened}, {True})
        # the role fills `where_it_went` on what code opened: the form is green
        doc, _f, _p, _d = verdict_of(a_form(nfr=[]), task, fix=True)
        filled = doc.text()
        for _ in range(7):
            # the placeholder is the contract's own line (HF2-18 extended it): match the line, not its wording
            filled = re.sub(r"where_it_went: <bug draft path[^\n]*>", "where_it_went: environment owner; gate B", filled, count=1)
        _doc, _f, problems, _d = verdict_of(filled, task)
        check_eq("K1: the role writes `where_it_went` on the opened rows and the form is green",
                 [p.path for p in problems], [])
    finally:
        cleanup(task)


def fix_opens_nothing_when_the_triage_is_not_clean() -> None:
    """Rows that look like a finished handover must never paper over a repair the role forgot."""
    rows = cmp2r_rows()[:2] + [instance_row("test_b[1]", "TEST_BUG")]
    task = a_task(rows)
    try:
        doc, fixed, problems, derived = verdict_of(a_form(nfr=[]), task, fix=True)
        check_eq("a TEST_BUG in the triage: --fix opens no row", ([f for f in fixed if "not_for_repair" in f], derived),
                 ([], []))
        check_in("...and the refusal is about the repair", "test_b[1] (TEST_BUG)", text_of(problems))
    finally:
        cleanup(task)


def the_cli_runs_the_same_check() -> None:
    """The check is reached from `main()`: the CLI of the script says what the function says."""
    rows = cmp2r_rows()
    task = a_task(rows)
    try:
        form = task / "work" / "handoffs" / f"{DISPATCH}.yaml"
        form.parent.mkdir(parents=True)
        form.write_text(a_form(nfr=nfr_of(rows)), encoding="utf-8")
        done = run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge", "--json")
        report = json.loads(done.stdout)
        check_eq("CLI K1: exit 0 and no problem for the cmp2r shape", (done.returncode, report["problems"]), (0, []))
        # a repair beside the empty scope: exit 1, naming the instance
        write_json(task / "work" / "triage.json", {"triage": rows + [instance_row("test_late[1]", "FLAKY",
                                                                                   fix_result="fixed")]})
        done = run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge", "--json")
        report = json.loads(done.stdout)
        check_eq("CLI: a FLAKY row beside the empty scope: exit 1", done.returncode, 1)
        check_in("CLI: and the problem names the instance and its verdict", "test_late[1] (FLAKY)",
                 (report["problems"] or [{"problem": "<no problem reported>"}])[0]["problem"])
        # --fix through the CLI opens the rows and records them in the form itself
        write_json(task / "work" / "triage.json", {"triage": rows})
        form.write_text(a_form(nfr=[]), encoding="utf-8")
        done = run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge", "--fix", "--json")
        report = json.loads(done.stdout)
        check_in("CLI --fix: says what code filled", "not_for_repair = 7 row(s) opened", report["fixed"])
        written = handoff.parse(form.read_text(encoding="utf-8"))
        check_eq("CLI --fix: the file now holds seven rows with their ids", len(written.data["not_for_repair"]), 7)
        check_eq("CLI --fix: and the form carries the derived record of them",
                 len([d for d in written.data.get("derived") or [] if str(d.get("field", "")).startswith("not_for_repair")]), 14)
    finally:
        cleanup(task)


def the_rows_code_opens_do_not_count_as_the_roles_work() -> None:
    """`filled_share` must not read the rows `--fix` opened as the role's own, or a form the role ignored would
    look touched the moment code answered one question for it (the reason `derived[]` exists)."""
    rows = cmp2r_rows()
    task = a_task(rows)
    try:
        form = task / "work" / "handoffs" / f"{DISPATCH}.yaml"
        form.parent.mkdir(parents=True)
        # a role that wrote `scope: []` and nothing else
        form.write_text(replace_section(untouched_form(), "scope", "scope: []"), encoding="utf-8")
        before = json.loads(run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge",
                                       "--json").stdout)["filled"]
        done = run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge", "--fix", "--json")
        check_in("--fix opened the rows in the blank form", "not_for_repair = 7 row(s) opened", json.loads(done.stdout)["fixed"])
        after = json.loads(run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge",
                                      "--json").stdout)["filled"]
        check_eq("the share the role filled is the same after code opened fourteen fields (ids and verdicts)",
                 after, before)
    finally:
        cleanup(task)


# ---------------------------------------------------------------------------------------------- K2
def refused(name: str, rows, form_rows=None, *, report="clean", scope=(), expect=(), nfr="match") -> None:
    """One adversarial case: the empty scope over this triage is refused, and the refusal holds `expect`."""
    task = a_task(rows, report=report)
    try:
        listed = nfr_of([r for r in rows if isinstance(r, dict)]) if (nfr == "match" and rows) else (nfr or [])
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=form_rows if form_rows is not None else listed,
                                                       scope=scope), task)
        shown = text_of(problems)
        check(f"K2: {name}: refused", bool(problems), "accepted an empty scope")
        for needle in expect:
            check_in(f"K2: {name}: names {needle!r}", needle, shown)
    finally:
        cleanup(task)


def the_adversarial_set_is_refused() -> None:
    base = cmp2r_rows()
    refused("one TEST_BUG among seven rows", base[:6] + [instance_row("test_late[1]", "TEST_BUG")],
            expect=("test_late[1] (TEST_BUG)", "repair verdict"))
    refused("TEST_BUG:collection", base + [instance_row("test_coll[1]", "TEST_BUG:collection")],
            expect=("test_coll[1] (TEST_BUG:collection)",))
    refused("a FLAKY row with fix_result fixed (a repair verdict is a repair, fixed or not)",
            base + [instance_row("test_flaky[1]", "FLAKY", fix_result="fixed")], expect=("test_flaky[1] (FLAKY)",))
    refused("a lower-case verdict is still a repair", base + [instance_row("test_low[1]", "flaky")],
            expect=("test_low[1] (flaky)",))
    refused("a verdict the check does not know", base + [instance_row("test_odd[1]", "WHATEVER")],
            expect=("test_odd[1] (WHATEVER)", "no verdict this check knows"))
    refused("a row with no verdict at all", base + [{"instance_id": "test_nv[1]"}],
            expect=("test_nv[1] (no verdict)",))
    refused("a row that names no instance", base + [{"verdict": "ENV_ISSUE"}], expect=("name no instance",))
    refused("a repair verdict in a manual check's row", base + [manual_row("TP1-15045_TC_011", "TEST_BUG")],
            expect=("TP1-15045_TC_011 (TEST_BUG)",))
    # the triage itself cannot be read: every shape is a reason
    for label, payload, why in (("a missing triage.json", None, "missing or cannot be read"),
                                ("malformed JSON", "{not json", "not valid JSON"),
                                ("a document that is a list", "[1, 2]", "not an object"),
                                ("a `triage` that is a string", {"triage": "none"}, "no `triage` list"),
                                ("a `triage` that is an object", {"triage": {"a": 1}}, "no `triage` list"),
                                ("a `triage` entry that is not a row", {"triage": [cmp2r_rows()[0], "x"]}, "not a row"),
                                ("no `triage` key", {"rows": []}, "no `triage` list")):
        task = a_task(None)
        try:
            if payload is not None:
                write_json(task / "work" / "triage.json", payload)
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[]), task)
            check(f"K2: {label}: refused", bool(problems))
            check_in(f"K2: {label}: says why", why, text_of(problems))
            check_in(f"K2: {label}: names the door (the analyst writes the triage)", "work/triage.json", text_of(problems))
        finally:
            cleanup(task)
    # the two lists disagree
    rows = cmp2r_rows()
    refused("a triage row that is not listed", rows, form_rows=nfr_of(rows)[:-1],
            expect=("1 triage row(s) are not listed", MANUAL[-1]))
    refused("an id listed that nobody triaged", rows, form_rows=nfr_of(rows) + [("test_ghost[1]", "ENV_ISSUE")],
            expect=("test_ghost[1]", "nobody triaged"))
    refused("the case id of an instance row instead of its instance id", rows,
            form_rows=nfr_of(rows)[:-1] + [("TP1-15045_TC_001", "APP_BUG")], expect=("TP1-15045_TC_001",))
    # a repair listed under `not_for_repair`, or a list row that carries a repair word, is not a way round
    refused("scope empty while `repairs` of the triage stand (the id is listed under not_for_repair)",
            [instance_row("test_r[1]", "TEST_BUG")], form_rows=[("test_r[1]", "ENV_ISSUE")], expect=("test_r[1] (TEST_BUG)",))
    # no triage row at all: only a clean run report passes
    # (t-323 F2: a report that cannot be read, or shows no results list, is ONE refusal for zero rows and rows alike -
    # these shapes therefore carry `current_results`, as every real report does; the shapeless ones are below)
    for label, report, why in (("a failed result", {"current_results": [], "current_totals": {"failed": 1}}, "1 result(s) `failed`"),
                               ("an error result", {"current_results": [], "current_totals": {"error": 2}}, "2 result(s) `error`"),
                               ("failures only in the raw totals",
                                {"current_results": [], "current_totals": {}, "totals": {"failed": 3}}, "3 result(s) `failed`"),
                               ("a manual check that failed", {"current_results": [], "current_totals": {"passed": 1},
                                                              "current_manual_checks": [{"case": "TC-5", "result": "fail"}]},
                                "TC-5"),
                               ("a manual check that was inconclusive", {"current_results": [], "current_totals": {"passed": 1},
                                                                         "manual_checks": [{"case": "TC-6", "result": "inconclusive"}]},
                                "TC-6"),
                               ("totals that are not a count", {"current_results": [], "current_totals": {"failed": "many"}},
                                "not a count"),
                               ("a report with no totals", {"current_results": [], "execution_status": "passed"}, "shows no totals"),
                               ("a report that is not an object", "[]", "work/run-report.json cannot be read"),
                               ("a malformed report", "{nope", "work/run-report.json cannot be read"),
                               ("a report with no results list", {"current_totals": {"failed": 1}},
                                "work/run-report.json shows no results list"),
                               ("manual_checks that is not a list",
                                {"current_results": [], "current_totals": {"passed": 1}, "manual_checks": {"a": 1}},
                                "`manual_checks` is not a list"),
                               ("no run report", None, "work/run-report.json cannot be read")):
        task = a_task([], report=report)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[]), task)
            check(f"K2: zero triage rows over {label}: refused", bool(problems))
            check_in(f"K2: zero triage rows over {label}: says why", why, text_of(problems))
        finally:
            cleanup(task)
    # zero rows with a clean report is the one empty case that passes (S1, S2 in orchestrator mode)
    for label, report in (("current totals", {"current_results": [], "current_totals": {"passed": 4}}),
                          ("an empty run (no result at all)", {"current_results": [], "current_totals": {}, "totals": {}}),
                          ("raw totals only", {"current_results": [], "totals": {"passed": 2, "skipped": 1}}),
                          ("manual checks that all passed", {"current_results": [], "current_totals": {"passed": 1},
                                                             "current_manual_checks": [{"case": "TC-5", "result": "pass"}]})):
        task = a_task([], report=report)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[]), task)
            check_eq(f"S1/S2: no triage row and a run report that shows no failure ({label}): accepted",
                     [p.path for p in problems], [])
        finally:
            cleanup(task)
    # zero rows, clean report, but something listed under not_for_repair: nobody triaged it
    task = a_task([])
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[("test_ghost[1]", "ENV_ISSUE")]), task)
        check("K2: zero triage rows and a listed id: refused", bool(problems))
        check_in("K2: ...naming the id", "test_ghost[1]", text_of(problems))
    finally:
        cleanup(task)
    # the other three verdicts of the contract are not repairs: they pass
    rows = [instance_row("test_c[1]", "CASE_DEFECT"), instance_row("test_d[1]", "APP_CHANGED"),
            instance_row("test_e[1]", "APP_BUG"), instance_row("test_f[1]", "ENV_ISSUE")]
    task = a_task(rows)
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
        check_eq("CASE_DEFECT, APP_CHANGED, APP_BUG and ENV_ISSUE are the four verdicts that are not repaired",
                 [p.path for p in problems], [])
    finally:
        cleanup(task)


def the_refusal_lists_are_cut_AT_and_BEYOND_the_cap() -> None:
    cap = HC.NULL_IDS_SHOWN
    for count, tail in ((cap, ""), (cap + 1, " and 1 more"), (cap + 5, " and 5 more")):
        rows = [instance_row(f"test_t{i}[1]", "TEST_BUG") for i in range(count)]
        task = a_task(rows)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[]), task)
            shown = problems[0].text if problems else ""
            check_eq(f"{count} repair verdicts: {cap} ids are named", len(re.findall(r"test_t\d+\[1\] \(TEST_BUG\)", shown)),
                     cap)
            check_eq(f"{count} repair verdicts: the rest is counted, not listed", ("more" in shown), bool(tail))
            check(f"{count} repair verdicts: the count is the whole count ('{count} repair' stands in the line)",
                  f"holds {count} repair verdict(s)" in shown, shown)
            if tail:
                check_in(f"{count} repair verdicts: the cut says how many are left", tail.strip(), shown)
        finally:
            cleanup(task)


# ---------------------------------------------------------------------------------------------- K3, S3
def every_other_contract_behaves_as_it_did() -> None:
    check_eq("REQUIRED_LISTS is unchanged: `scope`, and only it", handoff.REQUIRED_LISTS, ("scope",))
    named = [p.stem for p in sorted(handoff.CONTRACTS.glob("*.yaml"))
             if p.stem not in ("index", "vocabulary") and handoff.null_outcomes(p.stem)]
    check_eq("S3: exactly one contract names a null outcome - the S7 hand to the automator", named, [CONTRACT])
    entries = handoff.null_outcomes(CONTRACT)
    entry = entries.get("scope") or {}
    check_eq("its declaration is keyed by the section and names the condition, the repair verdicts, the list that "
             "holds the triage, the window word and the source (t-305 N0: the keyed shape)",
             (list(entries), entry.get("condition"), list((entry.get("params") or {}).get("repair_verdicts") or []),
              (entry.get("params") or {}).get("listed_in"),
              ((entry.get("words") or {}).get("header.window") or {}).get("word"), entry.get("source")),
             (["scope"], "triage_has_no_repair", ["TEST_BUG", "TEST_BUG:collection", "FLAKY"], "not_for_repair",
              "none", "work/triage.json"))
    check("`null_outcome` is the contract's own: a role is never refused for not filling it",
          handoff.owned_by_contract("null_outcome.scope.condition") and handoff.owned_by_contract("null_outcome"))
    # K3: the scribe form, empty scope, a clean triage and a clean run: still refused
    scribe = "s7-analyst-to-scribe"
    task = a_task([])
    try:
        text = (handoff.CONTRACTS / f"{scribe}.yaml").read_text(encoding="utf-8")
        form = handoff_init.fill_head(text, task=TICKET, dispatch="S7-scribe-1", role="qa-failure-analyst",
                                      stage="S7", scope="")
        form = replace_section(form, "scope", "scope: []")
        _doc, _fixed, problems, _j, _d = HC.check(handoff.parse(form), scribe, HC.Artifacts(task), fix=True, use_judge=False)
        scope_problem = [p for p in problems if p.path == "scope"]
        check_eq("K3: the scribe form with an empty scope is refused, as it always was", len(scope_problem), 1)
        check_in("K3: with the unchanged text", "no rows. One row per item in scope", scope_problem[0].text)
        check_not_in("K3: and with no word about a null outcome", "work/triage.json", scope_problem[0].text)
    finally:
        cleanup(task)
    # the S7 form WITHOUT the exception behaves the old way too: a `null_outcome`-less copy of the contract
    # (t-305 N0: the reader is `null_outcomes`; the old name is gone with no alias, so a patch of it can never miss)
    check("the old reader is gone", not hasattr(handoff, "null_outcome"))
    task = a_task([])
    try:
        before = HC.handoff.null_outcomes
        HC.handoff.null_outcomes = lambda _c: {}
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[]), task)
        finally:
            HC.handoff.null_outcomes = before
        check_in("S3: a contract with no `null_outcome` block refuses the empty scope in the old words",
                 "no rows. One row per item in scope", text_of(problems))
    finally:
        cleanup(task)


# ---------------------------------------------------------------------------------------------- S4
def window_none_belongs_to_the_null_outcome_only() -> None:
    rows = [instance_row("test_r[1]", "TEST_BUG")]
    task = a_task(rows)
    try:
        _doc, _f, problems, _d = verdict_of(a_form(scope=[("test_r[1]", "TEST_BUG")], nfr=[], window="none"), task)
        check_eq("S4: `window: none` beside a scope that lists a repair is refused, and only on the header",
                 [p.path for p in problems], ["header.window"])
        check_in("S4: the refusal says what `none` means and where it belongs", "belongs only to the empty `scope`",
                 problems[0].text)
        check_in("S4: and the way out", '--set header.window="<the instance ids handed for repair>"', problems[0].fix)
        for spelling in ("None", " NONE ", "none"):
            _doc, _f, problems, _d = verdict_of(a_form(scope=[("test_r[1]", "TEST_BUG")], nfr=[], window=spelling), task)
            check(f"S4: the word is read case-insensitively ({spelling!r})", [p.path for p in problems] == ["header.window"])
        _doc, _f, problems, _d = verdict_of(a_form(scope=[("test_r[1]", "TEST_BUG")], nfr=[], window="test_r[1]"), task)
        check_eq("S4: the same repair with the instance ids in `window`: green", [p.path for p in problems], [])
    finally:
        cleanup(task)


# ---------------------------------------------------------------------------------------------- K1, K7 end to end
class StandInController:
    """Only what `story_step.finish` asks of a controller: the dispatch, a packet, an acceptance."""

    applied: list = []

    def __init__(self, _root, wait_seconds=0.0):
        pass

    def state(self):
        return {"dispatches": {DISPATCH: {"stage": "S7", "role": "qa-failure-analyst"}}}

    def prepare(self, options):
        return {"accept_request": dict(options)}

    def apply(self, operation, request):
        StandInController.applied.append((operation, request))

    def next_action(self):
        return {"action": "prepare_stage", "stage": "S8"}

    def _next_action_for_state(self, _state):
        return self.next_action()


def finish_story(task: Path, *, ignore: bool = False) -> tuple:
    """`story_step.finish` over a stand-in controller and the REAL form check (a subprocess, as in a run)."""
    import argparse
    import story_step
    names = ("Controller", "_task_root", "_stages", "_run", "_post_work", "_judge_line", "config_finding", "_config")
    saved = {name: getattr(story_step, name) for name in names}
    real_run = story_step._run
    story_step.Controller = StandInController
    story_step._task_root = lambda _task: task
    story_step._stages = lambda: {"S7": {"roles": ["qa-failure-analyst"], "required_outputs": ["work/triage.json"],
                                         "outputs": []}}
    story_step._run = lambda script, *args: ((0, "stage_done: S7 done") if script == "stage_done.py"
                                             else real_run(script, *args))
    story_step._post_work = lambda *_a: []
    story_step._judge_line = lambda _task: "judge: off"
    story_step.config_finding = lambda *_a: []
    story_step._config = lambda: {}
    StandInController.applied = []
    out = io.StringIO()
    try:
        args = argparse.Namespace(task=TICKET, dispatch_id=DISPATCH, digest="qa-failure-analyst S7 done", output=None,
                                  not_complete=False, complete=False, ignore_handoff=ignore, window=None,
                                  unresolved=None, reason=None)
        with contextlib.redirect_stdout(out):
            code = story_step.finish(args)
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)
    return code, out.getvalue()


def story_step_finish_accepts_the_null_outcome() -> None:
    project = temp_project("qa-s7-finish-")
    use_project(project)
    try:
        rows = cmp2r_rows()
        task = project / "qa-factory" / "artifacts" / TICKET
        write_json(task / "work" / "triage.json", {"schema_version": 2, "triage": rows})
        # t-323 B4: with rows present the report must carry its results list; the cmp2r report is the real shape of
        # these seven failures (it replaces `{"current_totals": {"failed": 7}}`, which has no list to compare)
        write_json(task / "work" / "run-report.json", cmp2r_report())
        form = task / "work" / "handoffs" / f"{DISPATCH}.yaml"
        form.parent.mkdir(parents=True, exist_ok=True)
        form.write_text(a_form(nfr=nfr_of(rows)), encoding="utf-8")
        code, out = finish_story(task)
        check_eq("K1: `story_step finish` exits 0 over the cmp2r S7 shape", code, 0)
        check_in("K1: and says it accepted the dispatch", f"accepted {DISPATCH}", out)
        check_in("K1: with the stage complete", "stage complete", out)
        check_eq("K1: the controller was asked to accept it", [op for op, _r in StandInController.applied], ["accept"])
        check_not_in("K1: no refusal of the form is printed", "handover form is not complete", out)
        # the same with the role leaving `not_for_repair` for code: --fix inside `finish` opens the rows, and the
        # role's `where_it_went` is the only thing missing - the refusal names exactly that
        form.write_text(a_form(nfr=[]), encoding="utf-8")
        code, out = finish_story(task)
        check_eq("K1: with `not_for_repair: []` the finish is refused (the role writes where_it_went)", code, 3)
        check_in("K1: the refusal names the field", "not_for_repair[0].where_it_went", out)
        check_eq("K1: and code had opened the seven rows in the file by then",
                 len(handoff.parse(form.read_text(encoding="utf-8")).data["not_for_repair"]), 7)
        # K7: a refusal for a repair left out of `scope`
        write_json(task / "work" / "triage.json", {"triage": rows + [instance_row("test_late[1]", "TEST_BUG")]})
        form.write_text(a_form(nfr=nfr_of(rows)), encoding="utf-8")
        code, out = finish_story(task)
        lines = out.splitlines()
        check_eq("K7: a repair beside the empty scope is refused with exit 3", code, 3)
        check("K7: the FIRST line of the refusal is byte for byte what the driver keys on "
              "(story_run.KNOWN_REFUSALS `handover_form`)",
              lines[0].startswith("story_step: the handover form is not complete - ") and "test_late[1] (TEST_BUG)" in lines[0],
              lines[0])
        check_in("K7: the refusal says it is the form's own repair, not a question for the person",
                 "This is a repair, not a question for the person.", out)
        check_in("K7: and the older-build door is still there", "`handoffs.required: false`", out)
        check_in("K7: and `--ignore-handoff` is presented as a person's word passing the form for one dispatch",
                 "A person's word passes this form for this one dispatch: `finish --ignore-handoff`", out)
        check_in("K7: recorded by whoever records the person's words, not by the flag", "recorded by whoever records the person's words", out)
        check_not_in("K7: and no longer ONLY for a story under an older build", "this one dispatch: `finish --ignore-handoff`.", out)
        import story_run
        check_eq("K7: the driver still routes that first line to the role (`handover_form` -> resume_handoff)",
                 (story_run.match_known(lines[0]) or ("", "<no row>"))[1], "resume_handoff")
        # a person's word passes it: the flag, one dispatch
        code, out = finish_story(task, ignore=True)
        check_eq("K7: `--ignore-handoff` still passes the form for the dispatch", code, 0)
    finally:
        cleanup(project)


# ---------------------------------------------------------------------------------------------- t-309
# ONE definition of "a failure that needs triage": the reducer, the driver and this check read it from
# `contract.triage_targets`. TP1-15045 (cmp2r): `finalize_task.refresh` archived the analyst's five ENV rows
# ("not bound to current failure") because the three manual `inconclusive` were not failures there and the two
# UI instance ids carry `[chromium]` where the run report's do not - so S7 refused the null outcome it had just
# been taught to accept.
UI_MODULE = "tests.ui.workflows.test_workflow_version_history"
API_MODULE = "tests.workflow.test_workflow_validate_endpoint"


def cmp2r_report() -> dict:
    """The run report of the rehearsal in its real shapes: instance ids WITHOUT the parameter suffix the
    analyst's UI rows carry (`..[chromium]`), the three sign-in-page cases `inconclusive`, one manual pass."""
    def result(name: str, status: str, module: str) -> dict:
        return {"instance_id": name, "test_id": module + "::" + name, "status": status}
    return {"execution_status": "failed",
            "current_results": [result(APP_BUG_A, "failed", API_MODULE), result(APP_BUG_B, "failed", API_MODULE),
                                result(ENV_A.replace("[chromium]", ""), "failed", UI_MODULE),
                                result(ENV_B.replace("[chromium]", ""), "failed", UI_MODULE),
                                result("test_ok_one", "passed", API_MODULE), result("test_ok_two", "skipped", API_MODULE)],
            "current_manual_checks": [{"case": "TP1-15045_TC_012", "result": "pass"}]
                                     + [{"case": case, "result": "inconclusive"} for case in MANUAL],
            "current_totals": {"failed": 4, "inconclusive": 3, "passed": 9, "skipped": 2}}


class _Reduced:
    """`finalize_task.reduce` replaced by a fixed answer, so `refresh` is exercised over exactly this report."""

    def __init__(self, report: dict):
        self.report = report

    def __enter__(self):
        import finalize_task
        self.module, self.saved = finalize_task, finalize_task.reduce
        reducer = {"name": "finalize_task", "sources": []}
        whole = dict({"reducer": reducer, "results": [], "manual_checks": []}, **self.report)
        finalize_task.reduce = lambda task: (whole, {"schema_version": 2, "task_id": task.name, "triage": [],
                                                     "reducer": reducer})
        return finalize_task

    def __exit__(self, *_exc):
        self.module.reduce = self.saved


def archived_rows(task: Path) -> list:
    rows = []
    for path in sorted((task / "state" / "migration").glob("stale-triage-*.json")):
        rows += json.loads(path.read_text(encoding="utf-8"))["rows"]
    return rows


def the_three_definitions_are_one() -> None:
    import contract as C
    import story_run
    rows = cmp2r_rows()
    task = a_task(rows, report=None)
    try:
        write_json(task / "work" / "run-report.json", cmp2r_report())
        with _Reduced(cmp2r_report()) as finalize:
            finalize.refresh(task)
        kept = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"]
        check_eq("K1: `refresh` keeps all seven rows of the analyst (two APP_BUG, five ENV)",
                 [first_id(r) for r in kept], [first_id(r) for r in rows])
        check_eq("K1: and archives none of them", archived_rows(task), [])
        names = story_run.Driver.failures_to_triage(types.SimpleNamespace(task_root=task))
        check_eq("K1: the driver names the same failures: four failed results by count, the three manual cases by id",
                 names, "failed=4; manual " + ",".join(MANUAL))
        targets = C.triage_targets(cmp2r_report())
        for row in rows:
            check(f"K1: the row {first_id(row)} is a failure `triage_targets` knows",
                  any(C.id_spellings(n) & targets["all"] for n in (row.get("instance_id"), row.get("test"), row.get("case"))
                      if n), first_id(row))
        # the S7 form of the cmp2r run, over the files `refresh` left: accepted
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
        check_eq("K1: the S7 form with `scope: []` and seven `not_for_repair` rows is accepted over the refreshed triage",
                 [p.path for p in problems], [])
    finally:
        cleanup(task)

    # K2 (negative control): a row naming an id no reading knows is not a failure of this run - archived, and
    # an id listed under not_for_repair that nobody triaged is still refused
    ghost = instance_row("test_ghost[1]", "ENV_ISSUE")
    task = a_task(rows + [ghost], report=None)
    try:
        with _Reduced(cmp2r_report()) as finalize:
            finalize.refresh(task)
        kept = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"]
        check_eq("K2: a row whose id no failure carries in any spelling is archived, the seven stay",
                 ([first_id(r) for r in kept], [first_id(r) for r in archived_rows(task)]),
                 ([first_id(r) for r in rows], ["test_ghost[1]"]))
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows) + [("test_ghost[1]", "ENV_ISSUE")]), task)
        check_in("K2: ...and listing the ghost under not_for_repair is refused as named by nobody", "nobody triaged",
                 text_of(problems))
        check_in("K2: ...naming it", "test_ghost[1]", text_of(problems))
    finally:
        cleanup(task)

    # K4 (control): a row whose failure was repaired is still archived - the widening is not "keep everything"
    task = a_task(rows, report=None)
    try:
        fixed_report = cmp2r_report()
        fixed_report["current_results"][0]["status"] = "passed"
        with _Reduced(fixed_report) as finalize:
            finalize.refresh(task)
        kept = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"]
        check_eq("K4: the APP_BUG row of the repaired test is archived, the other six stay",
                 ([first_id(r) for r in archived_rows(task)], len(kept)), ([APP_BUG_A], 6))
        allgreen = {"execution_status": "passed", "current_results": [{"instance_id": "t", "status": "passed"}],
                    "current_manual_checks": [{"case": "TC-1", "result": "pass"}], "current_totals": {"passed": 2}}
        with _Reduced(allgreen) as finalize:
            finalize.refresh(task)
        check_eq("K4: with no failure left every remaining row is archived (the old behaviour, kept)",
                 (json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"], len(archived_rows(task))),
                 ([], 7))
    finally:
        cleanup(task)

    # the failure with no name at all is still a failure: it keeps the rows (never "repaired") and is said
    task = a_task(rows, report=None)
    try:
        nameless = {"execution_status": "failed", "current_results": [], "current_totals": {"inconclusive": 1},
                    "current_manual_checks": [{"result": "inconclusive"}]}
        with _Reduced(nameless) as finalize:
            finalize.refresh(task)
        reasons = [json.loads(p.read_text(encoding="utf-8"))["reason"]
                   for p in (task / "state" / "migration").glob("stale-triage-*.json")]
        check_eq("a failing manual check with no case/instance/test is a failure, not 'no failure': the rows are "
                 "archived as unbound, never as 'current failures repaired'", reasons, ["not bound to current failure"])
        check_in("...and the driver says so", "manual check #1 has no case, instance_id or test",
                 story_run.Driver.failures_to_triage(types.SimpleNamespace(task_root=task)))
    finally:
        cleanup(task)

    # t-323 C2: a failed RESULT row with no id is worded as such, never as a "manual" check; a nameless manual check
    # keeps the "manual" wording; the two together are two reasons
    for label, report, want, unwanted in (
            ("a nameless failed result row", {"execution_status": "failed", "current_totals": {"passed": 1},
                                              "current_results": [{"status": "failed"}], "current_manual_checks": []},
             "1 failed result row(s) with no id", "manual"),
            ("a nameless manual check", {"execution_status": "failed", "current_totals": {"passed": 1},
                                         "current_results": [], "current_manual_checks": [{"result": "fail"}]},
             "manual manual check #1 has no case, instance_id or test", "no id"),
            ("both", {"execution_status": "failed", "current_totals": {"passed": 1}, "current_results": [{"status": "error"}],
                      "current_manual_checks": [{"result": "inconclusive"}]},
             "manual manual check #1 has no case, instance_id or test; 1 failed result row(s) with no id", None)):
        task = a_task(rows, report=report)
        try:
            said = story_run.Driver.failures_to_triage(types.SimpleNamespace(task_root=task))
            check_in(f"C2: {label} is worded as what it is", want, said)
            if unwanted:
                check_not_in(f"C2: {label} is not worded as the other kind", unwanted, said)
        finally:
            cleanup(task)


def the_named_so_test_reads_spellings_one_side_at_a_time() -> None:
    """The analyst's list may carry the id without the `[param]` the triage row has (or the reverse); two
    siblings of one test (`x[json]`, `x[multi]`) are two failures and never stand for each other."""
    row = instance_row("test_param[chromium]", "ENV_ISSUE")
    task = a_task([row])
    try:
        for listed, label in (("test_param", "the base id of a parametrised row"), ("test_param[chromium]", "the exact id")):
            _doc, _f, problems, _d = verdict_of(a_form(nfr=[(listed, "ENV_ISSUE")]), task)
            check_eq(f"named so: {label} is accepted", [p.path for p in problems], [])
        for listed, label in (("test_param[firefox]", "a sibling parameter"), ("test_param[chromium][x][y]", "an id two "
                              "groups longer (stripped once, it is still not the row)"), ("", "an empty id")):
            _doc, _f, problems, _d = verdict_of(a_form(nfr=[(listed, "ENV_ISSUE")]), task)
            check(f"named so: {label} is refused", bool(problems), "accepted")
    finally:
        cleanup(task)
    # the row without a suffix, listed with one: the widening runs the other way too
    task = a_task([instance_row("test_base", "ENV_ISSUE")])
    try:
        _doc, _f, problems, _d = verdict_of(a_form(nfr=[("test_base[chromium]", "ENV_ISSUE")]), task)
        check_eq("named so: a listed id with a suffix over a triage row without one is accepted", [p.path for p in problems], [])
    finally:
        cleanup(task)
    # two siblings: only `x[multi]` triaged, only `x[json]` listed - nobody triaged what was listed
    task = a_task([instance_row("test_s[multi]", "ENV_ISSUE")])
    try:
        _doc, _f, problems, _d = verdict_of(a_form(nfr=[("test_s[json]", "ENV_ISSUE")]), task)
        check_in("named so: x[json] listed over a triage row x[multi] is refused", "test_s[json]", text_of(problems))
        check_in("...as named by no triage row", "nobody triaged", text_of(problems))
    finally:
        cleanup(task)


# ---------------------------------------------------------------------------------------------- t-319
# Critic t-312 F2: the S1 invariant "an empty scope is never accepted while a failure has no verdict" was checked
# on the zero-row branch only. With ONE triage row an empty scope passed while the run report showed another
# failed test no row named (probe P1).
def run_report_of(failed=(), manual=(), unnamed_results=0) -> dict:
    results = [{"instance_id": name, "test": "tests/test_x.py::" + name, "status": "failed"} for name in failed]
    results += [{"status": "failed", "nodeid": "z"} for _ in range(unnamed_results)]
    return {"execution_status": "failed", "current_totals": {"failed": len(failed) + unnamed_results},
            "current_results": results,
            "current_manual_checks": [{"case": case, "result": "inconclusive"} for case in manual]}


def a_failure_with_no_row_is_refused() -> None:
    # K1: the P1 probe - one ENV row, two failed results, the second one untriaged
    rows = [instance_row(ENV_A, "ENV_ISSUE")]
    task = a_task(rows, report=run_report_of([ENV_A, APP_BUG_A]))
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
        check_in("K1/P1: a failed result that no triage row names is refused, naming it", APP_BUG_A, text_of(problems))
        check_in("K1/P1: ...saying it has no verdict", "no verdict", text_of(problems))
        check_not_in("K1/P1: ...and not naming the failure that HAS its row", ENV_A + ",", text_of(problems))
        # --fix opens nothing over a triage that is missing a failure (the rows opened would be the whole answer)
        _doc, fixed, problems, _d = verdict_of(a_form(nfr=[]), task, fix=True)
        check_eq("K1: with --fix the rows are not opened over an incomplete triage", [f for f in fixed if "not_for_repair" in f], [])
        # control: the same report with the second failure triaged (APP_BUG is not a repair) is accepted
        both = rows + [instance_row(APP_BUG_A, "APP_BUG")]
        write_json(task / "work" / "triage.json", {"schema_version": 2, "task_id": TICKET, "triage": both})
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(both)), task)
        check_eq("K1 control: with the second failure triaged the empty scope is accepted", [p.path for p in problems], [])
    finally:
        cleanup(task)
    # a manual failure with no row: the same refusal, by its case id (the P1 shape for the other kind of failure)
    task = a_task(rows, report=run_report_of([ENV_A], manual=[MANUAL[0]]))
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
        check_in("K1: a manual `inconclusive` with no row is refused, by its case", MANUAL[0], text_of(problems))
    finally:
        cleanup(task)
    # K3: a failed result row with no name at all is a failure nobody can answer: refused (with rows AND with none)
    for label, triage_rows, want in (("with one row", rows, "has no instance_id, test_instance_id, test_id or test"),
                                     ("with no row (totals say nothing)", [], "failed result row")):
        report = run_report_of([ENV_A] if triage_rows else [], unnamed_results=1)
        if not triage_rows:
            report["current_totals"] = {"passed": 1}        # only the row itself shows the failure
        task = a_task(triage_rows, report=report)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(triage_rows)), task)
            check_in(f"K3: a nameless failed result {label} is refused", want, text_of(problems))
        finally:
            cleanup(task)
    # t-323 BL-2 (critic t-327): a failed result row that carries only a `case` has NO name a row could answer to:
    # fail-closed through `unnamed` - a row `{case: C1}` is no verdict of it, and two such rows are two failures
    for label, triage_rows in (("with a row naming the case", [manual_row("C1")]), ("with no row", [])):
        report = {"execution_status": "failed", "current_manual_checks": [], "current_totals": {"passed": 1},
                  "current_results": [{"case": "C1", "status": "failed"}, {"case": "C1", "status": "failed"}]}
        task = a_task(triage_rows, report=report)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(triage_rows)), task)
            check_in(f"BL-2: case-only failed results {label}: refused as having no name",
                     "has no instance_id, test_instance_id, test_id or test", text_of(problems))
            if triage_rows:
                check_in("BL-2: two failures, two notes", "2 failure(s) carry no name", text_of(problems))
        finally:
            cleanup(task)
    # a failed result with a `test` only (no instance_id) is answered by a row naming that test
    task = a_task([{"test": "tests/test_x.py::t1", "verdict": "ENV_ISSUE", "evidence": "e"}],
                  report={"execution_status": "failed", "current_totals": {"failed": 1}, "current_manual_checks": [],
                          "current_results": [{"test": "tests/test_x.py::t1", "status": "failed"}]})
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(nfr=[("tests/test_x.py::t1", "ENV_ISSUE")]), task)
        check_eq("a failure named only by its `test` is answered by the row that names that test", [p.path for p in problems], [])
    finally:
        cleanup(task)
    # t-323 B4 (critic t-322 Q2): a run report that cannot be read, or has no results list, with rows present is a
    # REFUSAL naming the file and the door - the null outcome's own invariant "every branch that cannot tell ends in a
    # refusal"; the pin that accepted it is inverted. The zero-row branch keeps its text (one sentence for both).
    for label, report in (("missing", None), ("not JSON", "{not json"), ("not an object", "[1, 2]"),
                          ("with no results list", {"execution_status": "failed", "current_totals": {"passed": 1}}),
                          ("whose results are not a list", {"current_results": "x", "results": {"a": 1}})):
        task = a_task(rows, report=report)
        try:
            _doc, _fixed, problems, _d = verdict_of(a_form(nfr=nfr_of(rows)), task)
            check_eq(f"B4: a run report {label}, rows present: refused on `scope`", [p.path for p in problems], ["scope"])
            check_in(f"B4: {label}: names the file", "work/run-report.json", text_of(problems))
            check_in(f"B4: {label}: and the door (the conductor restores it; the analyst says so under `blocked`)",
                     "say so under `blocked` in the form, so the conductor can restore work/run-report.json",
                     text_of(problems))
            # t-323 F2-cosmetic: the door is said ONCE - in `fix`, not again in the text
            check_eq(f"F2: {label}: the `blocked` door sentence appears once", text_of(problems).count("under `blocked`"), 1)
            check_not_in(f"F2: {label}: the refusal text itself names no door", "under `blocked`",
                         " ".join(p.text for p in problems))
            check_in(f"B4/F2: {label}: says it cannot tell which failures exist", "cannot tell which failures exist",
                     text_of(problems))
            check_not_in(f"B4/F2: {label}: never says `a failure has no verdict` (an unknown is not a fact)",
                         "a failure has no verdict", text_of(problems))
            # --fix opens nothing over a refusal that cannot tell
            _doc, fixed, _p, _d = verdict_of(a_form(nfr=[]), task, fix=True)
            check_eq(f"B4: {label}: --fix opens no rows", [f for f in fixed if "not_for_repair" in f], [])
        finally:
            cleanup(task)
    # F2 (critic t-327, decided): the SAME text and door with ZERO rows - one sentence, one door
    for label, report, said in (("missing", None, "the run report work/run-report.json cannot be read"),
                                ("with no results list", {"current_totals": {"passed": 1}},
                                 "the run report work/run-report.json shows no results list")):
        with_rows, with_none = a_task(cmp2r_rows(), report=report), a_task([], report=report)
        try:
            _d1, _f1, rows_problems, _x = verdict_of(a_form(nfr=nfr_of(cmp2r_rows())), with_rows)
            _d2, _f2, zero_problems, _y = verdict_of(a_form(nfr=[]), with_none)
            check_eq(f"F2: {label}: zero rows and rows present are refused with the same text and the same door",
                     [(p.text, p.fix) for p in zero_problems], [(p.text, p.fix) for p in rows_problems])
            check_in(f"F2: {label}: the sentence", said, text_of(zero_problems))
            check_not_in(f"F2: {label}: the unusable zero-row door is gone", "triage every failure", text_of(zero_problems))
        finally:
            cleanup(with_rows)
            cleanup(with_none)


def ambiguity_and_multiple_rows_are_refused_on_both_s7_paths() -> None:
    """t-323 F1 (critic t-327): a row that names two failures, or two rows for one failure, is refused with a NON-EMPTY
    `scope` too - before, only the empty-section path said it, and a kept ambiguous TEST_BUG row beside a repair list
    reached `s7_repairs`."""
    report = {"execution_status": "failed", "current_manual_checks": [], "current_totals": {"failed": 2},
              "current_results": [{"instance_id": "test_s[json]", "status": "failed"},
                                  {"instance_id": "test_s[multi]", "status": "failed"}]}
    cases = (("ambiguous", [instance_row("test_s", "TEST_BUG")], "names 2 failures"),
             ("multiple", [instance_row("test_s[json]", "TEST_BUG"), instance_row("test_s[json]", "TEST_BUG", attempt_id="a2"),
                           instance_row("test_s[multi]", "ENV_ISSUE")], "2 rows answer the failure test_s[json]; keep one"))
    for label, rows, said in cases:
        for path, form in (("non-empty scope", a_form(scope=[("test_s[json]", "red")], window=TICKET)),
                           ("empty scope", a_form(nfr=nfr_of(rows)))):
            task = a_task(rows, report=report)
            try:
                _doc, _fixed, problems, _d = verdict_of(form, task)
                check_in(f"F1: {label} rows, {path}: refused with the one wording", said, text_of(problems))
                check_in(f"F1: {label} rows, {path}: on `scope`", "scope", " ".join(p.path for p in problems))
            finally:
                cleanup(task)
    # control: one row per failure, non-empty scope: no binding problem is raised
    rows = [instance_row("test_s[json]", "TEST_BUG"), instance_row("test_s[multi]", "ENV_ISSUE")]
    task = a_task(rows, report=report)
    try:
        _doc, _fixed, problems, _d = verdict_of(a_form(scope=[("test_s[json]", "red")], window=TICKET), task)
        check_not_in("F1 control: one row per failure, non-empty scope", "cannot be a verdict", text_of(problems))
    finally:
        cleanup(task)


def refresh_keeps_a_row_by_the_one_matching_rule() -> None:
    """K2 (critic t-312 F3): `finalize_task.refresh` kept `x[multi]` for the failure `x[json]` because it met the UNION of
    the spellings of every failure; the S7 check and gate B read it one side at a time. Now all three call
    `contract.same_id`: a stale TEST_BUG row of a sibling is archived, and `s7_repairs` no longer repairs a test that
    passes."""
    def failed_x(*names: str) -> dict:
        return {"execution_status": "failed", "current_manual_checks": [], "current_totals": {"failed": len(names)},
                "current_results": [{"instance_id": n, "status": "failed"} for n in names]}

    def run(report: dict, rows: list) -> tuple:
        task = a_task(rows, report=None)
        try:
            with _Reduced(report) as finalize:
                finalize.refresh(task)
            kept = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"]
            return [first_id(r) for r in kept], [first_id(r) for r in archived_rows(task)]
        finally:
            cleanup(task)

    exact, sibling = instance_row("x[json]", "TEST_BUG"), instance_row("x[multi]", "TEST_BUG")
    check_eq("K2: failure x[json], rows x[json] and x[multi]: the exact row stays, the sibling's row is archived",
             run(failed_x("x[json]"), [exact, sibling]), (["x[json]"], ["x[multi]"]))
    check_eq("K2 control: with BOTH siblings failing, both rows stay",
             run(failed_x("x[json]", "x[multi]"), [exact, sibling]), (["x[json]", "x[multi]"], []))
    check_eq("K2: a base row `x` answers the failure `x[json]` (one side widened)",
             run(failed_x("x[json]"), [instance_row("x", "ENV_ISSUE")]), (["x"], []))
    check_eq("K2: a row `x[chromium]` answers the failure `x` (the other side)",
             run(failed_x("x"), [instance_row("x[chromium]", "ENV_ISSUE")]), (["x[chromium]"], []))
    # two-bracket ids: stripped ONCE, from the last `[` - one rule at every site
    two = instance_row("a::b[x][y]", "ENV_ISSUE")
    check_eq("K2 two brackets: the row `a::b[x][y]` answers the failure `a::b[x]`",
             run(failed_x("a::b[x]"), [two]), (["a::b[x][y]"], []))
    check_eq("K2 two brackets: ...and NOT the failure `a::b` (stripped once - the same rule as `same_id`)",
             run(failed_x("a::b"), [two]), ([], ["a::b[x][y]"]))
    # a row that names a failure by its `test` only
    check_eq("K2: a row with no instance_id answers the failure its `test` names",
             run({"execution_status": "failed", "current_manual_checks": [], "current_totals": {"failed": 1},
                  "current_results": [{"test": "tests/test_x.py::t1", "status": "failed"}]},
                 [{"test": "tests/test_x.py::t1", "verdict": "ENV_ISSUE"}]),
             ([""], []))       # `first_id` is "" for a row with no instance_id: one row kept, none archived


def one_definition_no_local_set_building() -> None:
    """The class sentinel (FR-17: grep for the problem, not for the helper). In the three places that decide
    "this failure needs triage" - `finalize_task.refresh`/`reduce`, `story_run.failures_to_triage` and the S7
    handover check - no `result_status(` call is compared with the failed/error tuple: that is
    `contract.triage_targets`' job. With a positive control: the same scan, same pattern, over a place known to
    hold such a line, finds it."""
    import ast
    scripts = PLUGIN_ROOT / "scripts"
    pattern = re.compile(r"result_status\(.*[\(\{]\s*\"failed\",\s*\"error\"")

    DRIVER = "the driver set"        # a `path` that is this string stands for every file of `harness.driver_sources()`

    def label(path) -> str:
        return path if isinstance(path, str) else path.name

    def texts_of(path) -> list:
        if isinstance(path, str):
            return [(p.name, text) for p, text in driver_sources()]
        return [(path.name, path.read_text(encoding="utf-8"))]

    def scan_lines(regex, path, functions=None, what="the sentinel") -> list:
        """[(file name, line no)] of `regex` over the whole file, or over the named functions only (each must be found)."""
        found, rows = 0, []
        for name, text in texts_of(path):
            lines = text.splitlines()
            if functions is None:
                spans = [(1, len(lines))]
            else:
                spans = [(n.lineno, n.end_lineno) for n in ast.walk(ast.parse(text))
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in functions]
                found += len(spans)
            rows += [(name, no) for lo, hi in spans for no in range(lo, hi + 1) if regex.search(lines[no - 1])]
        if functions is not None:
            check(f"{what} found the functions {sorted(functions)} in {label(path)}", found == len(functions), str(found))
        return rows

    def hits(path, functions=None) -> list:
        return scan_lines(pattern, path, functions)

    # `reduce` keeps one such line for another question (an evidence error on a red row, :472 - not a triage
    # set), so for it the sentinel is positive: its triage reason asks `triage_targets`.
    reduce_source = ast.get_source_segment(
        (scripts / "finalize_task.py").read_text(encoding="utf-8"),
        next(n for n in ast.walk(ast.parse((scripts / "finalize_task.py").read_text(encoding="utf-8")))
             if isinstance(n, ast.FunctionDef) and n.name == "reduce"))
    check("sentinel: finalize_task.reduce decides its triage `reason` through contract.triage_targets",
          "C.triage_targets(report)" in reduce_source)
    for path, functions in ((scripts / "finalize_task.py", {"refresh"}),
                            (DRIVER, {"failures_to_triage"}),
                            (scripts / "handoff_check.py", None)):
        check_eq(f"sentinel: no local failed/error set-building in {label(path)} {sorted(functions or ['<whole file>'])}",
                 hits(path, functions), [])
    # t-311 moved check_delivery's reading onto the one definition too; the tuple now lives only in
    # contract.triage_targets, which is the positive control of the scan.
    control = hits(scripts / "contract.py")
    check("sentinel positive control: the same scan finds the tuple where it is known to be (contract.py)",
          len(control) >= 1, str(control))
    check("sentinel positive control: and in finalize_task.py's evidence check (inside `reduce`, outside `refresh`)",
          len(hits(scripts / "finalize_task.py")) >= 1)
    # t-319 (critic t-312 F5): the sentinel's pattern had required `result_status(`, so the fifth reading -
    # `judge_results._failed_rows`' raw `row.get("status") in ("failed", "error")` - went unseen. The RAW form is
    # swept now over the readers that decide triage: a `status ... in ("failed", "error")` tuple (or set / list).
    raw = re.compile(r"status[^\n]*\bin\s*[\(\{\[]\s*[\"']failed[\"'],\s*[\"']error[\"']")

    def raw_hits(path, functions=None) -> list:
        return scan_lines(raw, path, functions, "the raw sentinel")

    check("raw sentinel positive control: the SAME pattern finds the tuple in contract.triage_targets",
          len(raw_hits(scripts / "contract.py", {"triage_targets"})) == 1)
    check("raw sentinel positive control: ...and the old `_failed_rows` form, as a string, matches it",
          bool(raw.search('return [r for r in rows if r.get("status") in ("failed", "error")]')))
    for path, functions in ((scripts / "judge_results.py", None), (scripts / "ledger.py", None),
                            (scripts / "traceability.py", None), (scripts / "handoff_check.py", None),
                            (scripts / "finalize_task.py", {"refresh"}), (scripts / "check_delivery.py", {"_triage_failures", "_bind_triage", "triage_reasons"}),
                            (DRIVER, {"failures_to_triage"})):
        check_eq(f"raw sentinel: no raw failed/error tuple in {label(path)} {sorted(functions or ['<whole file>'])}",
                 raw_hits(path, functions), [])
    # t-323 A1: the BINDING of rows to failures is one too (`contract.bind_triage`); the six readers call it - the
    # check names the problem (a local `same_id(` over failure names), with the SAME pattern finding it in contract.py
    local_binding = re.compile(r"\bsame_id\(")
    check("binding sentinel positive control: the pattern finds `same_id(` where the binding lives (contract.py)",
          bool(local_binding.search((scripts / "contract.py").read_text(encoding="utf-8"))))
    for name, call in (("handoff_check.py", "C.bind_triage("), ("finalize_task.py", "C.bind_triage("),
                       ("check_delivery.py", "C.bind_triage("), ("ledger.py", "C.triage_row_for("),
                       ("traceability.py", "C.triage_row_for("), ("factory_dashboard.py", "C.triage_row_for(")):
        text = (scripts / name).read_text(encoding="utf-8")
        check(f"binding sentinel: {name} reads through {call.rstrip('(')}", call in text)
        if name in ("finalize_task.py", "check_delivery.py", "ledger.py", "traceability.py", "factory_dashboard.py"):
            check(f"binding sentinel: {name} keeps no local `same_id(` binding", not local_binding.search(text))


def main() -> None:
    the_three_definitions_are_one()
    the_named_so_test_reads_spellings_one_side_at_a_time()
    a_failure_with_no_row_is_refused()
    ambiguity_and_multiple_rows_are_refused_on_both_s7_paths()
    refresh_keeps_a_row_by_the_one_matching_rule()
    one_definition_no_local_set_building()
    the_cmp2r_shape_is_accepted()
    a_reorder_row_is_a_repair()
    fix_opens_the_rows_from_the_triage()
    fix_opens_nothing_when_the_triage_is_not_clean()
    the_cli_runs_the_same_check()
    the_rows_code_opens_do_not_count_as_the_roles_work()
    the_adversarial_set_is_refused()
    the_refusal_lists_are_cut_AT_and_BEYOND_the_cap()
    every_other_contract_behaves_as_it_did()
    window_none_belongs_to_the_null_outcome_only()
    story_step_finish_accepts_the_null_outcome()
    finish("s7 null outcome")


if __name__ == "__main__":
    main()
