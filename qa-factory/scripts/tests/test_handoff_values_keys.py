#!/usr/bin/env python3
"""keys: a part of test_handoff_values.py, split by tools/test_split.py (TD-11c). The shared helpers are in handoff_values_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as H  # noqa: E402
from handoff_values_common import (  # noqa: E402
    CONTRACT, DISPATCH, FIXTURE, _doc, _form, _form5, _hc, _hc_stdin, _paths, _sha, _story,
)


OLD_JSON_KEYS = ("contract", "fixed", "shortened", "judged", "filled", "fields", "untouched", "no_verdict", "problems")


def _apply(form: Path, text: str, raw: bool = False):
    """The values text through the one applier, in memory: `(document, applied, problems, notes)`."""
    pairs, bad = H.parse_values(text)
    assert not bad, [p.text for p in bad]
    doc = _doc(form)
    return H.apply_values(doc, CONTRACT, pairs, raw=raw)


# ---------------------------------------------------------------------------------------------------- the keys
def one_call_fills_the_real_s2_form() -> None:
    """K-A1: the values of the real 13877 form, every path the CURRENT spec knows, go in with ONE call and leave no
    problem the form itself did not already have (the baseline is `check` on the fixture, same root)."""
    root = temp_project("qa-values-a1-")
    try:
        art = _story(root)
        form = _form(art)
        spec = handoff.spec(CONTRACT)
        fixture = handoff.parse(FIXTURE.read_text(encoding="utf-8"))
        lines = [f"{path}: {json.dumps(node.value, ensure_ascii=False)}" for path, node in fixture.nodes.items()
                 if not handoff.owned_by_contract(path) and H.INDEXED.sub("[]", path) in spec
                 and not handoff.is_placeholder(node.value)]
        values = art / "work" / "all-values.txt"
        values.write_text("\n".join(lines) + "\n", encoding="utf-8")
        check("K-A1: the values file carries many paths, rows included", len(lines) > 100 and any(
            line.startswith("scope[14].id:") for line in lines), str(len(lines)))
        base_doc, _f, base_problems, _j, _d = H.check(handoff.parse(FIXTURE.read_text(encoding="utf-8")), CONTRACT,
                                                      H.Artifacts(art, dispatch=DISPATCH), fix=True, use_judge=False)
        baseline = set(_paths(base_problems))
        code, report = _hc(art, form, "--fix", "--values", str(values), "--json")
        check_eq("K-A1: one call - the report is JSON and counts what was applied", report["values_applied"], len(lines))
        extra = sorted(set(_paths(report["problems"])) - baseline)
        check_eq("K-A1: no problem beyond the ones the fixture itself has", extra, [])
        if not baseline:
            check_eq("K-A1: the fixture has no problems, so neither has the form (exit 0)", code, 0)
        doc = _doc(form)
        check_eq("K-A1: fifteen requirement rows exist", doc.rows("scope"), list(range(15)))
        check_eq("K-A1: the last row is the fixture's", doc.get("scope[14].id"), fixture.get("scope[14].id"))
        check_eq("K-A1: a nested reading row exists", doc.get("open_questions[1].readings[1].id"), "b")
    finally:
        cleanup(root)


def stdin_is_the_same_door() -> None:
    """K-A1b: `--values -` reads the same text from stdin (the role with Bash writes no file at all)."""
    root = temp_project("qa-values-stdin-")
    try:
        art = _story(root)
        form = _form(art)
        code, out = _hc_stdin(art, form, "scope[0].id: R-1\nheader.verdict: ok\n", "--values", "-")
        doc = _doc(form)
        check_eq("K-A1b: stdin values are written", (doc.get("scope[0].id"), doc.get("header.verdict")), ("R-1", "ok"))
        check_eq("K-A1b: and no file beside the form is left behind", sorted(p.name for p in form.parent.iterdir()),
                 [form.name])
    finally:
        cleanup(root)


def an_index_equal_to_the_row_count_opens_a_row_from_the_contract() -> None:
    """K-A2: `scope[1].id` on a one-row form opens row 1. The other rows' values are never copied into it."""
    root = temp_project("qa-values-a2-")
    try:
        art = _story(root)
        form = _form(art)
        _hc(art, form, "--set", "scope[0].id=R-1", "--set", "scope[0].reason=first")
        doc, applied, problems, notes = _apply(form, "scope[1].id: R-2\n")
        check_eq("K-A2: the row opens and the id is written", (doc.rows("scope"), doc.get("scope[1].id"), applied),
                 ([0, 1], "R-2", 1))
        check_eq("K-A2: no problem", _paths(problems), [])
        check_eq("K-A2: row 1 carries the contract's placeholder, not row 0's reason",
                 doc.get("scope[1].reason"), handoff.template(CONTRACT).get("scope[0].reason"))
        check_eq("K-A2: row 0 is untouched", (doc.get("scope[0].id"), doc.get("scope[0].reason")), ("R-1", "first"))
    finally:
        cleanup(root)


def the_opened_row_is_the_contracts_template_row() -> None:
    """K-A2b: there is ONE row builder - `_row_template` of the contract; the opened lines equal its lines."""
    root = temp_project("qa-values-a2b-")
    try:
        art = _story(root)
        form = _form(art)
        _hc(art, form, "--set", "scope[0].id=R-1")                 # the form's own row 0 now differs from the contract's
        doc = _doc(form)
        tpl = H._row_template(handoff.template(CONTRACT), "scope")[2]
        last = max(n.end_line for p, n in doc.nodes.items() if p.startswith("scope[0]"))
        check("K-A2b: open_row says it opened the row", H.open_row(doc, CONTRACT, "scope", 1))
        check_eq("K-A2b: the lines after the last row are the contract's row, line for line",
                 doc.lines[last + 1:last + 1 + len(tpl)], tpl)
        check_eq("K-A2b: an index of an existing row opens nothing", H.open_row(doc, CONTRACT, "scope", 0), False)
        check_eq("K-A2b: nor does an index past the next one", H.open_row(doc, CONTRACT, "scope", 5), False)
    finally:
        cleanup(root)


def an_index_beyond_the_row_count_is_refused_and_opens_nothing() -> None:
    """K-A3: a hole is the role's mistake - no row appears and the problem names the row that is next; in-order
    indexes of one file open one row after another."""
    root = temp_project("qa-values-a3-")
    try:
        art = _story(root)
        form = _form(art)
        before = form.read_text(encoding="utf-8")
        doc, applied, problems, _n = _apply(form, "scope[2].id: R-3\n")
        check_eq("K-A3: a hole is one problem on that path", _paths(problems), ["scope[2].id"])
        check_in("K-A3: it names the next row", "the next row is `scope[1]`", problems[0].text)
        check_eq("K-A3: nothing is written and no row is opened", (applied, doc.text()), (0, before))
        doc, applied, problems, _n = _apply(form, "scope[3].id: R-4\nscope[1].id: R-2\n")
        check_eq("K-A3: scope[1] opens, scope[3] still has a hole before it", (doc.rows("scope"), _paths(problems)),
                 ([0, 1], ["scope[3].id"]))
        # AT the limit: two rows in order in one file, written backwards - the applier orders them
        _hc(art, form, "--set", "scope[1].id=R-2")
        doc, applied, problems, _n = _apply(form, "scope[3].id: R-4\nscope[2].id: R-3\n")
        check_eq("K-A3: scope[2] and scope[3] in one file open in order", (doc.rows("scope"), _paths(problems), applied),
                 ([0, 1, 2, 3], [], 2))
        check_eq("K-A3: each row has its own id", [doc.get(f"scope[{i}].id") for i in (1, 2, 3)], ["R-2", "R-3", "R-4"])
        doc, applied, problems, _n = _apply(form, "scope[3].id: R-4\nscope[2].id: R-3\nscope[5].id: R-6\n")
        check_eq("K-A3: BEYOND - scope[5] after scope[3] is refused, the rest stands",
                 (doc.rows("scope"), _paths(problems)), ([0, 1, 2, 3], ["scope[5].id"]))
    finally:
        cleanup(root)


def a_nested_row_opens_inside_its_parent() -> None:
    """K-A4: `open_questions[0].readings[1]` lands inside question 0, not at the end of the list or in question 1."""
    root = temp_project("qa-values-a4-")
    try:
        art = _story(root)
        form = _form(art)
        text = ("open_questions[1].id: Q-2\n"
                "open_questions[0].readings[1].id: b\n"
                "open_questions[0].readings[1].reading: the other way\n")
        doc, applied, problems, _n = _apply(form, text)
        check_eq("K-A4: no problem", _paths(problems), [])
        check_eq("K-A4: question 0 has two readings, the new question brings its template reading",
                 (doc.rows("open_questions"), doc.rows("open_questions[0].readings"),
                  doc.rows("open_questions[1].readings")), ([0, 1], [0, 1], [0]))
        line = lambda path: doc.nodes[path].line  # noqa: E731
        check("K-A4: the new reading sits between reading 0 and question 1",
              line("open_questions[0].readings[0].cost") < line("open_questions[0].readings[1].id")
              < line("open_questions[1].id"))
        check_eq("K-A4: its words are where they were said",
                 (doc.get("open_questions[0].readings[1].reading"), doc.get("open_questions[1].id")),
                 ("the other way", "Q-2"))
        doc, _a, problems, _n = _apply(form, "open_questions[0].readings[4].id: z\n")
        check_in("K-A4: a hole inside a nested list is refused too", "the next row is `open_questions[0].readings[1]`",
                 problems[0].text)
    finally:
        cleanup(root)


def a_placeholder_left_in_the_values_is_not_written() -> None:
    """K-A5: a skeleton line the role left as it was is not a word - it neither overwrites a value nor opens a row."""
    root = temp_project("qa-values-a5-")
    try:
        art = _story(root)
        form = _form(art)
        _hc(art, form, "--set", "header.verdict=ok")
        text = ("header.verdict: <ok|concerns|halt|impossible>\n"
                "scope[1].id: <R-n>\n"
                "scope[0].reason: \"\"\n"
                "blocked.tried: [<command or step>]\n")
        doc, applied, problems, notes = _apply(form, text)
        check_eq("K-A5: nothing is written, nothing is counted", (applied, _paths(problems)), (0, []))
        check_eq("K-A5: the value stays and no row opened", (doc.get("header.verdict"), doc.rows("scope")), ("ok", [0]))
        check_eq("K-A5: the role is told, once per line", len(notes), 4)
    finally:
        cleanup(root)


def a_malformed_line_applies_nothing() -> None:
    """K-A6: one line that does not parse and NOT ONE line of the file is applied - and the pairs that did parse are
    still returned (the guard keeps them for the role)."""
    cases = {
        "no colon": "scope[0].id: R-1\nthis is a sentence\n",
        "path twice": "header.verdict: ok\nheader.verdict: halt\n",
        "no space after the colon": "header.verdict:ok\n",
        "a list item": "scope:\n  - id: R-1\n",
        "nested json": json.dumps({"header.verdict": {"a": 1}}),
        "json array": json.dumps(["header.verdict", "ok"]),
        "broken json": "{\"header.verdict\": ",
        "json list of maps": json.dumps({"blocked.tried": [{"a": 1}]}),
    }
    for name, text in cases.items():
        pairs, bad = H.parse_values(text)
        check(f"K-A6: {name} - a problem", len(bad) >= 1, str(bad))
    pairs, bad = H.parse_values("scope[0].id: R-1\nthis is a sentence\n")
    check_eq("K-A6: the problem carries the line number", [p.path for p in bad], ["values line 2"])
    check_eq("K-A6: the good line is still returned for the guard", [(p[0], p[2]) for p in pairs], [("scope[0].id", 1)])
    root = temp_project("qa-values-a6-")
    try:
        art = _story(root)
        form = _form(art)
        values = art / "work" / "bad.txt"
        values.write_text("scope[0].id: R-1\nthis is a sentence\n", encoding="utf-8")
        before = _sha(form)
        code, report = _hc(art, form, "--values", str(values), "--json")
        check_eq("K-A6: applied by none - the form is the same bytes", (_sha(form), report["values_applied"]),
                 (before, 0))
        check("K-A6: the refusal names the file and the line", "bad.txt line 2" in _paths(report["problems"]),
              str(report["problems"])[:300])
        sibling = H.sibling_values(form)
        sibling.write_text("scope[0].id: R-1\nthis is a sentence\n", encoding="utf-8")
        code, out = _hc(art, form, "--fix")
        check_eq("K-A6: a waiting file that does not parse is not applied and not renamed",
                 (sibling.is_file(), form.with_name(f"{form.stem}.values.applied.yaml").exists(), _doc(form).get("scope[0].id")),
                 (True, False, handoff.template(CONTRACT).get("scope[0].id")))
        check_in("K-A6: and its problem refuses the form until it is rewritten", f"{sibling.name} line 2", out)
        # accepted shapes: a BOM and CRLF
        sibling.write_bytes(b"\xef\xbb\xbfheader.verdict: ok\r\nscope[0].id: R-1  # first\r\n")
        _hc(art, form, "--fix")
        doc = _doc(form)
        check_eq("K-A6: a BOM and CRLF are accepted (and a trailing comment is a comment)",
                 (doc.get("header.verdict"), doc.get("scope[0].id")), ("ok", "R-1"))
    finally:
        cleanup(root)


def an_unknown_path_is_a_problem_beside_the_applied_ones() -> None:
    """K-A7: one wrong path used to stop `--set` with exit 2 and the rest was lost; now it is one problem in the
    common list, with the closest known path, and every other pair is applied."""
    root = temp_project("qa-values-a7-")
    try:
        art = _story(root)
        form = _form(art)
        values = art / "work" / "v.txt"
        values.write_text("header.verdict: ok\nscope[0].idd: R-1\nscope[0].reason: fine\n", encoding="utf-8")
        code, report = _hc(art, form, "--values", str(values), "--json")
        doc = _doc(form)
        check_eq("K-A7: exit 1, the two good values are in", (code, report["values_applied"], doc.get("scope[0].reason")),
                 (1, 2, "fine"))
        wrong = [p for p in report["problems"] if p["path"] == "scope[0].idd"]
        check_eq("K-A7: one problem for the wrong path", len(wrong), 1)
        check_in("K-A7: it names the closest path", "did you mean `scope[0].id`", wrong[0]["problem"])
        code, report = _hc(art, form, "--set", "nothing.here=1", "--set", "scope[0].reason=still", "--json")
        check_eq("K-A7: --set with an unknown path is exit 1, not 2, and the other --set is applied",
                 (code, _doc(form).get("scope[0].reason"), "nothing.here" in _paths(report["problems"])),
                 (1, "still", True))
        doc, applied, problems, _n = _apply(form, "claims.never_heard_of_it: true\n")
        check_eq("K-A7: a path that is in neither the spec nor the form is a problem",
                 (applied, _paths(problems)), (0, ["claims.never_heard_of_it"]))
        doc, applied, problems, _n = _apply(form, "inputs[0].path: x\nschema_version: 2\n")
        check_eq("K-A7: a path the contract writes itself is refused", _paths(problems), ["inputs[0].path", "schema_version"])
    finally:
        cleanup(root)


def values_make_the_form_touched_and_code_derived_values_do_not() -> None:
    """K-A8: `untouched` (measured after the role's words, before `--fix`) is what `story_step finish` reads; a form
    the role wrote into is touched, a form code filled for it is not."""
    root = temp_project("qa-values-a8-")
    try:
        art = _story(root)
        form = _form(art)
        code, before = _hc(art, form, "--json")
        (art / "work" / "sizing.json").write_text(json.dumps({"size": "XS"}), encoding="utf-8")
        code, report = _hc(art, form, "--fix", "--json")
        check_in("K-A8: code derives the size", "size.computed = XS (from sizing.json)", report["fixed"])
        check_eq("K-A8: and the derived field is not counted as the role's (filled does not move)",
                 report["filled"], before["filled"])
        # an S5 critic form is untouched at birth (the S2 form is not: its third `inputs_read` row is a
        # placeholder that makes the first two count - the existing rule, not this node's)
        critic = _form5(art, "S5-qa-code-critic-1")
        code, report = _hc(art, critic, "--json")
        check_eq("K-A8: a fresh critic form is untouched", report["untouched"], True)
        values = art / "work" / "v.txt"
        values.write_text("scope[0].id: test_one\n", encoding="utf-8")
        code, report = _hc(art, critic, "--values", str(values), "--json")
        check_eq("K-A8: one value of the role makes it touched", report["untouched"], False)
        second = _form5(art, "S5-qa-code-critic-2")
        H.sibling_values(second).write_text("scope[0].id: test_one\n", encoding="utf-8")
        code, report = _hc(art, second, "--json")
        check_eq("K-A8: so does a waiting file, in a read-only run", report["untouched"], False)
    finally:
        cleanup(root)


def order_is_sibling_then_values_then_set() -> None:
    """K-A9: the latest and most explicit word wins - the waiting file, then `--values`, then `--set`."""
    root = temp_project("qa-values-a9-")
    try:
        art = _story(root)
        values = art / "work" / "v.txt"
        values.write_text("scope[0].reason: from values\n", encoding="utf-8")
        results = {}
        for name, with_sibling, with_values, with_set in (("all three", True, True, True), ("no --set", True, True, False),
                                                           ("sibling only", True, False, False)):
            form = _form(art, f"S2-qa-requirements-tester-{len(results) + 1}")
            if with_sibling:
                H.sibling_values(form).write_text("scope[0].reason: from sibling\nscope[0].id: R-1\n", encoding="utf-8")
            flags = (["--values", str(values)] if with_values else []) + (["--set", "scope[0].reason=from set"]
                                                                        if with_set else [])
            _hc(art, form, "--fix", *flags)
            results[name] = (_doc(form).get("scope[0].reason"), _doc(form).get("scope[0].id"))
        check_eq("K-A9: --set is last", results["all three"], ("from set", "R-1"))
        check_eq("K-A9: --values beats the waiting file", results["no --set"], ("from values", "R-1"))
        check_eq("K-A9: the waiting file alone", results["sibling only"], ("from sibling", "R-1"))
    finally:
        cleanup(root)


def a_sibling_is_applied_once() -> None:
    """K-A10: the file is renamed `.values.applied.yaml` after the form is written, so a later word of the role
    (a `--set`, an Edit) is never overwritten by the earlier file; `.values.stale.yaml` is never read."""
    root = temp_project("qa-values-a10-")
    try:
        art = _story(root)
        form = _form(art)
        sibling = H.sibling_values(form)
        stale = form.with_name(f"{form.stem}.values.stale.yaml")
        stale.write_text("scope[0].reason: from a form long gone\n", encoding="utf-8")
        sibling.write_text("scope[0].reason: first word\nscope[0].id: R-1\n", encoding="utf-8")
        code, out = _hc(art, form, "--fix")
        applied = form.with_name(f"{form.stem}.values.applied.yaml")
        check_eq("K-A10: renamed, not deleted", (sibling.exists(), applied.is_file()), (False, True))
        check_in("K-A10: the run says so", f"applied 2 value(s) from {sibling.name}; it is now {applied.name}", out)
        check_eq("K-A10: the stale file was not applied", _doc(form).get("scope[0].reason"), "first word")
        _hc(art, form, "--set", "scope[0].reason=later word")
        _hc(art, form, "--fix")
        check_eq("K-A10: a later word survives the next --fix", _doc(form).get("scope[0].reason"), "later word")
        sibling.write_text("scope[0].reason: second file\n", encoding="utf-8")
        _hc(art, form, "--fix")
        check_eq("K-A10: a new file is applied and replaces the trace",
                 (_doc(form).get("scope[0].reason"), applied.read_text(encoding="utf-8").strip(), sibling.exists()),
                 ("second file", "scope[0].reason: second file", False))
        explicit = art / "work" / "named.txt"
        explicit.write_text("scope[0].reason: named\n", encoding="utf-8")
        _hc(art, form, "--values", str(explicit))
        check_eq("K-A10: a file named by --values is applied and never renamed", (explicit.is_file(), _doc(form).get("scope[0].reason")),
                 (True, "named"))
    finally:
        cleanup(root)


def a_read_only_check_reports_the_merged_view_and_writes_nothing() -> None:
    """K-A11: FR-45 - a run that does not write (no --fix/--set/--values) shows the form as the next writing run will,
    and touches neither the form nor the waiting file."""
    root = temp_project("qa-values-a11-")
    try:
        art = _story(root)
        form = _form(art)
        sibling = H.sibling_values(form)
        sibling.write_text("scope[0].id: R-1\n", encoding="utf-8")
        hashes = (_sha(form), _sha(sibling))
        code, report = _hc(art, form, "--json")
        check_eq("K-A11: nothing on disk changed", (_sha(form), _sha(sibling)), hashes)
        check_eq("K-A11: the report says what is pending", (report["values_applied"], report["values_pending"]),
                 (1, sibling.name))
        check_not_in("K-A11: the merged field is not reported as unfilled", "scope[0].id", _paths(report["problems"]))
        check_in("K-A11: another field of the same row is", "scope[0].state", _paths(report["problems"]))
        code, out = _hc(art, form)
        check_in("K-A11: the text run says the file waits for a writing run", f"pending values from {sibling.name} - applied by --fix", out)
        check_eq("K-A11: and still writes nothing", (_sha(form), _sha(sibling)), hashes)
    finally:
        cleanup(root)


def an_empty_values_file_changes_nothing() -> None:
    """K-A14: an empty file or one of comments is neither a green form nor a touched one."""
    root = temp_project("qa-values-a14-")
    try:
        art = _story(root)
        form = _form5(art, "S5-qa-code-critic-1")
        before = form.read_text(encoding="utf-8")
        for name, text in (("empty", ""), ("comments", "# nothing yet\n\n   \n# still nothing\n"), ("only a BOM", "﻿")):
            values = art / "work" / "v.txt"
            values.write_text(text, encoding="utf-8")
            code, report = _hc(art, form, "--values", str(values), "--json")
            check_eq(f"K-A14: {name} - the form text is the same, the form is untouched, the form is not green",
                     (form.read_text(encoding="utf-8"), report["values_applied"], report["untouched"], code),
                     (before, 0, True, 1))
        H.sibling_values(form).write_text("# nothing yet\n", encoding="utf-8")
        code, report = _hc(art, form, "--json")
        check_eq("K-A14: an empty waiting file changes nothing either", (form.read_text(encoding="utf-8"),
                                                                       report["untouched"]), (before, True))
    finally:
        cleanup(root)


def a_named_values_file_that_does_not_exist_is_exit_2() -> None:
    """K-A15: a named input is never read as an empty one."""
    root = temp_project("qa-values-a15-")
    try:
        art = _story(root)
        form = _form(art)
        before = _sha(form)
        code, out = _hc(art, form, "--fix", "--values", str(art / "work" / "no-such.txt"))
        check_eq("K-A15: exit 2 and the form is untouched", (code, _sha(form)), (2, before))
        check_in("K-A15: the message names the file", "no such values file:", out)
    finally:
        cleanup(root)


def json_keeps_its_keys() -> None:
    """K-A16: FR-14 - `--json` only adds keys: the readers (story_step, the driver) parse the old ones."""
    root = temp_project("qa-values-a16-")
    try:
        art = _story(root)
        form = _form(art)
        code, report = _hc(art, form, "--json")
        check_eq("K-A16: every old key is there", [k for k in OLD_JSON_KEYS if k not in report], [])
        check_eq("K-A16: the new keys are values_* (A1) and the skeleton (A2)", sorted(k for k in report if k not in OLD_JSON_KEYS),
                 ["values_applied", "values_notes", "values_pending", "values_skeleton"])
        check_eq("K-A16: a problem keeps its three keys and gains `kind` and `also` (A2) and `code_fills` (SC2-38)", sorted(report["problems"][0]),
                 ["also", "code_fills", "fix", "kind", "path", "problem"])
    finally:
        cleanup(root)


def a_path_a_form_in_flight_still_holds_is_written_not_refused() -> None:
    """K-A18: M-7 - the spec and the form can disagree (a form begun on an older package). Written, never refused,
    when only the form has the line; not written, with a note, when only the spec has it; refused when neither."""
    root = temp_project("qa-values-a18-")
    try:
        art = _story(root)
        form = art / "work" / "handoffs" / f"{DISPATCH}.yaml"
        form.parent.mkdir(parents=True)
        form.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")        # a form begun elsewhere, in flight
        spec = handoff.spec(CONTRACT)
        old = "claims.every_production_file_reaches_a_requirement_or_is_named_not_requirement_bearing"
        kept = "claims.every_requirement_names_its_source_and_revision"
        check("K-A18: the first key is a line only the form holds", old not in spec and old in _doc(form).nodes)
        doc, applied, problems, notes = _apply(form, f"{old}: false\n{kept}: false\n")
        check_eq("K-A18: both are written, neither is a problem", (doc.get(old), doc.get(kept), applied, _paths(problems)),
                 (False, False, 2, []))
        said = [n for n in notes if old in n]
        check_eq("K-A18: the one the contract lost comes with a note", len(said), 1)
        check_in("K-A18: that says why", "is not in `s2-tester-to-strategist` any more", said[0])
        # the same key is an ordinary field now and a form-only line once part C drops it: both worlds are right
        check_eq("K-A18: the other key has a note exactly when the contract no longer holds it",
                 len([n for n in notes if kept in n]), 0 if kept in spec else 1)
        doc, applied, problems, notes = _apply(form, "claims.never_heard_of_it: true\n")
        check_eq("K-A18: neither in the spec nor in the form - a problem", _paths(problems), ["claims.never_heard_of_it"])
        # the other world: the spec has a line the form never had
        bare = _form(art, "S2-qa-requirements-tester-2")
        doc = _doc(bare)
        doc.lines = [line for line in doc.lines if line.strip() != doc.lines[doc.nodes["size.computed"].line].strip()]
        bare.write_text(doc.text(), encoding="utf-8")
        check("K-A18: the synthetic form has no size.computed line", "size.computed" not in _doc(bare).nodes)
        doc, applied, problems, notes = _apply(bare, "size.computed: XS\n")
        check_eq("K-A18: a spec path with no line in the form is not written, and is not a problem",
                 (applied, _paths(problems), "size.computed" in doc.nodes), (0, [], False))
        check_in("K-A18: the role is told", "this form has no line for it", notes[0])
    finally:
        cleanup(root)


def an_index_on_a_list_of_values_is_refused_with_the_whole_list_hint() -> None:
    """K-A22: `blocked.tried[1]: x` is not a way to append to a list of values (a `- key: value` line must never open
    inside it): the problem says to write the whole list on one line, and that line replaces the list whole."""
    root = temp_project("qa-values-a22-")
    try:
        art = _story(root)
        form = _form(art)
        doc, applied, problems, _n = _apply(form, "blocked.tried[1]: x\n")
        check_eq("K-A22: one problem, nothing written", (_paths(problems), applied), (["blocked.tried[1]"], 0))
        check_in("K-A22: it gives the whole-list line", "blocked.tried: [", problems[0].text)
        doc, applied, problems, _n = _apply(form, "scope[1]: x\n")
        check_in("K-A22: a row index with no field says to name the field", "scope[1].<field>", problems[0].text)
        doc, applied, problems, _n = _apply(form, "blocked.tried: [one, two, three]\n")
        check_eq("K-A22: the whole list is written", ([doc.get(f"blocked.tried[{i}]") for i in range(3)], _paths(problems)),
                 (["one", "two", "three"], []))
        form.write_text(doc.text(), encoding="utf-8")
        doc, applied, problems, _n = _apply(form, "blocked.tried: [only]\n")
        check_eq("K-A22: a shorter list replaces the longer one", [p for p in doc.nodes if p.startswith("blocked.tried")],
                 ["blocked.tried[0]"])
        doc, applied, problems, _n = _apply(form, "blocked.tried: just one\n")
        check_eq("K-A22: a single word for a list is refused (write it as a list)", _paths(problems), ["blocked.tried"])
        doc, applied, problems, _n = _apply(form, "header.verdict: [ok]\n")
        check_eq("K-A22: and a list for a single value is refused", _paths(problems), ["header.verdict"])
    finally:
        cleanup(root)


def set_keeps_its_raw_meaning() -> None:
    """K-A23: `--set` is the typed text byte for byte (the placeholder included) on a line the form holds; the same
    placeholder in a values file is not written (K-A5)."""
    root = temp_project("qa-values-a23-")
    try:
        art = _story(root)
        form = _form(art)
        expected = _doc(form)
        handoff.set_value(expected, "scope[0].reason", "a: b")
        handoff.set_value(expected, "header.verdict", "<one of the above>")
        _hc(art, form, "--set", "scope[0].reason=a: b", "--set", "header.verdict=<one of the above>")
        check_eq("K-A23: the form is byte for byte what handoff.set_value writes", form.read_text(encoding="utf-8"),
                 expected.text())
        check_eq("K-A23: the placeholder is the value", _doc(form).get("header.verdict"), "<one of the above>")
        doc, applied, problems, _n = _apply(form, "header.verdict: <one of the above>\nscope[0].reason: <= 80 characters>\n")
        check_eq("K-A23: the same words in a values file are not written", (applied, doc.text()), (0, form.read_text(encoding="utf-8")))
        doc, applied, problems, _n = _apply(form, "header.verdict: <one of the above>\n", raw=True)
        check_eq("K-A23: the raw flag is the only difference", (applied, doc.get("header.verdict")), (1, "<one of the above>"))
    finally:
        cleanup(root)


def a_value_from_the_file_meets_the_ordinary_limits() -> None:
    """L3: the values path does not bypass the field's length check - AT the limit there is no problem, BEYOND it the
    ordinary length problem (with its limit as data)."""
    root = temp_project("qa-values-l3-")
    try:
        art = _story(root)
        form = _form(art)
        values = art / "work" / "v.txt"
        values.write_text("scope[0].reason: " + "x" * 80 + "\n", encoding="utf-8")
        code, report = _hc(art, form, "--values", str(values), "--json")
        check_not_in("L3: 80 characters is the limit and passes", "scope[0].reason", _paths(report["problems"]))
        values.write_text("scope[0].reason: " + "x" * 81 + "\n", encoding="utf-8")
        code, report = _hc(art, form, "--values", str(values), "--json")
        long = [p for p in report["problems"] if p["path"] == "scope[0].reason"]
        check_eq("L3: 81 is refused with the limit as data", [p.get("limit") for p in long], [80])
    finally:
        cleanup(root)


# split: runner piece 1
if __name__ == "__main__":
    one_call_fills_the_real_s2_form()
    stdin_is_the_same_door()
    an_index_equal_to_the_row_count_opens_a_row_from_the_contract()
    the_opened_row_is_the_contracts_template_row()
    an_index_beyond_the_row_count_is_refused_and_opens_nothing()
    a_nested_row_opens_inside_its_parent()
    a_placeholder_left_in_the_values_is_not_written()
    a_malformed_line_applies_nothing()
    an_unknown_path_is_a_problem_beside_the_applied_ones()
    values_make_the_form_touched_and_code_derived_values_do_not()
    order_is_sibling_then_values_then_set()
    a_sibling_is_applied_once()
    a_read_only_check_reports_the_merged_view_and_writes_nothing()
    an_empty_values_file_changes_nothing()
    a_named_values_file_that_does_not_exist_is_exit_2()
    json_keeps_its_keys()
    a_path_a_form_in_flight_still_holds_is_written_not_refused()
    an_index_on_a_list_of_values_is_refused_with_the_whole_list_hint()
    set_keeps_its_raw_meaning()
    a_value_from_the_file_meets_the_ordinary_limits()
    finish("test_handoff_values_keys")
