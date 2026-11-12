#!/usr/bin/env python3
"""t-1765 X3: the exploration cells of the first manual window of S6 - the perturbation table is data with ONE reader, the brief prints
its cells, an unmeasured flow is "not measured" and never "no bugs".

T1 cells of three requests   T2 the brief lines   T3 zero requests / no file / broken file (negative control)   T4 the ceiling
T5 keyboard axis -> steps -> a record   T6 a request cell -> a step   T7 the real guard lets qa-runner write tried.md
T8 the carrier window   T9 an unreadable table   T10 a violated oracle reaches S7 as `<case>#obs<n>`
Mutations -> killing key: the kinds as a literal in `exploration_cells` -> T1; "no requests" for "not measured" -> T3; no ceiling -> T4;
`fill` for `type` in the multi_digit row -> T5; exploration lines in every manual window -> T8; in an automated brief -> T8.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_brief_pack_manual as B  # noqa: E402  (its story/brief fixtures; main() runs only under __main__)
import test_manual_capture as T  # noqa: E402
import test_manual_seed_path as SP  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

import brief_pack  # noqa: E402
import contract as C  # noqa: E402
import user_path_failures as UPF  # noqa: E402

S, MC = T.S, T.MC
FIX = HERE / "fixtures" / "exploration"
PERTURBATIONS = UPF.PERTURBATIONS_FILE
TABLE = json.loads(PERTURBATIONS.read_text(encoding="utf-8"))


def task_with(flow=None, text=None):
    """A bare task folder; `flow` is a fixture of fixtures/exploration, `text` a raw body of work/flow-requests.json."""
    task = Path(tempfile.mkdtemp(prefix="qa-explore-")) / "task"
    (task / "work").mkdir(parents=True)
    if flow is not None:
        shutil.copyfile(FIX / flow, task / "work" / "flow-requests.json")
    if text is not None:
        (task / "work" / "flow-requests.json").write_text(text, encoding="utf-8")
    return task


def drop(task):
    shutil.rmtree(task.parent, ignore_errors=True)


def axis(axis_id):
    return next(a for a in TABLE["axes"] if a["id"] == axis_id)


def t1_cells():
    task = task_with("flow-three-requests.json")
    try:
        got = UPF.exploration_cells(task)
        kinds = [k["id"] for k in axis("request_failure")["kinds"]]
        cells = got["cells"]
        check_eq("T1 three requests x the kinds of the table: six cells", len(cells), 3 * len(kinds))
        check_eq("T1 the order is (path, line), then the table's kinds",
                 [(c["request"], c["kind"]) for c in cells],
                 [(r, k) for r in ("PUT /api/basket/{lineId}", "GET /api/orders", "GET /api/products/{productId}") for k in kinds])
        check_eq("T1 the glob of every cell is request_route_glob's (what fail_request takes)",
                 [c["glob"] for c in cells[::2]],
                 [UPF.request_route_glob(r)[0] for r in ("PUT /api/basket/{lineId}", "GET /api/orders", "GET /api/products/{productId}")])
        check_eq("T1 a cell names its site", cells[2]["at"], "src/pages/Orders.tsx:12")
        check_eq("T1 nothing unmeasured", got["unmeasured"], [])
        # the kinds are the DATA's: a table with one kind `503` gives 503 cells (mutation: the kinds as a literal in code)
        other = Path(tempfile.mkdtemp(prefix="qa-explore-table-")) / "perturbations.json"
        other.write_text(json.dumps({"axes": [{"id": "request_failure", "applies_to": "requests", "kinds": [{"id": "503"}],
                                               "oracle": "stays alive"}]}), encoding="utf-8")
        again = UPF.exploration_cells(task, other)
        check_eq("T1 the kinds come from the file given: 3 cells of 503", [c["kind"] for c in again["cells"]], ["503"] * 3)
        shutil.rmtree(other.parent, ignore_errors=True)
        check_eq("T1 failure_axis is the one reader's view of request_failure", UPF.failure_axis(),
                 UPF.perturbation_axis("request_failure"))
    finally:
        drop(task)


def t2_lines():
    task = task_with("flow-three-requests.json")
    try:
        head = brief_pack.exploration_lines(task, "T-1", "D-1")
        check_eq("T2 the head is the charter line and ONE pointer line (no cell in the brief)", len(head), 2)
        check_in("T2 the pointer names the side file and says it is not written in a run that writes nothing",
                 "Exploration cells: qa-factory/artifacts/T-1/work/briefs/D-1-cells.md (not written in this run)", head[1])
        lines, usable = brief_pack.exploration_cell_lines(task)
        text = "\n".join(lines)
        path = head[0].split("Exploration charter: ", 1)[1].split(" - read it", 1)[0]
        check("T2 the charter path printed exists in the package", Path(path).is_file(), path)
        check_in("T2 the brief names the table the role writes", "work/evidence/manual/<case>/tried.md", head[0])
        check_not_in("T2 the charter is data: its text is not in the brief", "## Outcome", text)
        rows = [x for x in lines if x.startswith("- request_failure x ")]
        check_eq("T2 one line per request", len(rows), 3)
        for glob in (UPF.request_route_glob(r)[0] for r in ("PUT /api/basket/{lineId}", "GET /api/orders", "GET /api/products/{productId}")):
            check("T2 a line carries `fail_request \"<glob>\"` and both kinds", any(
                f'fail_request "{glob}"' in x and "500 | timeout" in x for x in rows), glob)
        check_in("T2 the keyboard axis line", "- keyboard_input x every input field of the flow you meet x multi_digit | empty | paste | beyond_limit", text)
        check_in("T2 the reload axis line", "- reload_mid_operation x every action that saves x reload", text)
        check_in("T2 the session axis line (guest state merged on sign-in)",
                 "- session_transition x every sign-in you can reach with state built as a guest x sign_in_with_state | sign_in_merge_failed", text)
        oracles = lines[-1]
        want = "Axis oracles: " + "; ".join(f"{a['id']} - {' '.join(a['oracle'].split())}" for a in TABLE["axes"])
        check_eq("T2 the axis oracles are the data's, verbatim", oracles, want)
    finally:
        drop(task)


def t3_unmeasured():
    cases = (("zero requests with a reason", task_with("flow-zero-requests.json"), "- request_failure - not measured: no code"),
             ("no file", task_with(), "- request_failure - not measured: work/flow-requests.json does not exist (S3 did not write it)"),
             ("an unreadable file", task_with(text="{not json"),
              "- request_failure - not measured: work/flow-requests.json is not a JSON object with a list `requests`"),
             ("an empty list that gives no reason", task_with(text='{"requests": []}'),
              "- request_failure - not measured: work/flow-requests.json lists no request and gives no reason"))
    for label, task, line in cases:
        try:
            lines = brief_pack.exploration_cell_lines(task)[0]
            text = "\n".join(lines)
            check_in(f"T3 {label}: the line says not measured, with the reason", line, text)
            check_eq(f"T3 {label}: no cell of a request", [x for x in lines if x.startswith("- request_failure x ")], [])
            check_eq(f"T3 {label}: UPF has no cell either", UPF.exploration_cells(task)["cells"], [])
            for word in ("no requests", "no bugs", "No requests"):
                check_not_in(f"T3 {label}: never `{word}`", word, text)
            check_in(f"T3 {label}: the field and action axes are printed all the same", "- keyboard_input x", text)
            check_in(f"T3 {label}: ... and the reload axis", "- reload_mid_operation x", text)
        finally:
            drop(task)


def t4_ceiling():
    top = brief_pack.MAX_REQUEST_LINES
    for count, label in ((top, "AT the ceiling"), (top + 1, "BEYOND the ceiling")):
        requests = [{"method": "GET", "url_template": f"/api/item{i:02d}", "source": "code", "path": "src/a.tsx", "line": i + 1,
                     "also_at": []} for i in range(count)]
        task = task_with(text=json.dumps({"requests": requests, "unmeasured": [], "checked": ["src/a.tsx"]}))
        try:
            lines = brief_pack.exploration_cell_lines(task)[0]
            rows = [x for x in lines if x.startswith("- request_failure x ")]
            tail = [x for x in lines if "more requests:" in x]
            check_eq(f"T4 {label} ({count} requests): the request lines", len(rows), top)
            check_eq(f"T4 {label}: the cut is named", tail, [] if count == top else ["- request_failure: 1 more requests: work/flow-requests.json"])
            check_eq(f"T4 {label}: the cells are whole in UPF", len(UPF.exploration_cells(task)["cells"]), count * 2)
        finally:
            drop(task)


def t5_keyboard():
    kinds = {k["id"]: k["steps"] for k in axis("keyboard_input")["kinds"]}
    t = S.make_task()
    try:
        for kind, steps in kinds.items():
            for step in steps:
                line = step.replace("<selector>", "input").replace("<the limit plus one, 0, -1>", "101")
                check_eq(f"T5 {kind}: `{line}` is a step the capture parses", T.problem_with(MC.spec(), line), "")
        reload_step = axis("reload_mid_operation")["kinds"][0]["steps"][0].replace("<the same address>", T.UI)
        check_eq("T5 reload: `goto <the same address>` parses", T.problem_with(MC.spec(), reload_step), "")
        for kind in axis("session_transition")["kinds"]:
            for step in kind["steps"]:
                line = (step.replace("<selector>", "input").replace("<actor>", "default")
                        .replace("<the glob of the merge request>", '"**/api/basket/merge{,\\?*}"')
                        .replace("<the control that builds the guest state>", "button.add").replace("<the sign-in control>", "a.login")
                        .replace("<the sign-in submit>", "button.submit"))
                check_eq(f"T5 session_transition {kind['id']}: `{line}` is a step the capture parses", T.problem_with(MC.spec(), line), "")
        word = kinds["multi_digit"][0].replace("<selector>", "input")
        # X8-4: the multi_digit row is `fill <selector> 12`; a human `fill` (clear, then the characters one at a time) keys it, so the
        # fake carries the human path (clear_field + field_traits + type_chars) - the same characters, the same log, now under `fill-`.
        class Human(S.FakeBrowser):
            def field_traits(self, selector):
                return {"type": None, "tag": "input"}, 0.01

            def clear_field(self, selector):
                return {"n": "cleared", "value": "", "focus": True}, 0.01, 0.01

        browser = Human()
        browser.typed = {"input": [{"n": 1, "value": "1", "focus": True}, {"n": 2, "value": "1", "focus": False},
                                   {"n": "settled", "value": "1", "focus": False}]}
        entry, attempt = T._input_step(t, browser, word)
        check_eq("T5 multi_digit is keyed one character at a time (a `fill` that types, not a whole-value set)", browser.calls[0][0], "type")
        check_in("T5 the redraw after the first character is told", "focus lost after character 1", entry["detail"])
        log = next(p for p in attempt.dir.glob("*fill-input*")).read_text(encoding="utf-8").splitlines()
        check_eq("T5 the per-character log (the clearing first)", log,
                 ["cleared\t\tfocus=yes", "1\t1\tfocus=yes", "2\t1\tfocus=no", "settled\t1\tfocus=no"])
        entry, _ = T._input_step(t, Human(), word)
        check_not_in("T5 control: a page that keeps the focus says nothing of it", "focus lost", entry["detail"])
    finally:
        S.cleanup(t)


def t6_request_cell_to_step():
    task = task_with("flow-three-requests.json")
    try:
        cell = UPF.exploration_cells(task)["cells"][2]
        for how in (cell["kind"], "timeout"):
            check_eq(f"T6 `fail_request \"{cell['glob']}\" {how}` parses", T.problem_with(MC.spec(), f'fail_request "{cell["glob"]}" {how}'), "")
        check_in("T6 a 200 is no failure: refused at the data's bound", "from 400 to 599",
                 T.problem_with(MC.spec(), f'fail_request "{cell["glob"]}" 200'))
    finally:
        drop(task)


def route_matches(glob, url) -> bool:
    """Does `page.route(glob)` fire for `url`: Playwright's own matcher when it is importable, else a translation of its glob rules
    (`**` any, `*` any but `/`, `?` one character, `{a,b}` alternatives, `\\x` literal)."""
    try:
        from playwright._impl._helper import url_matches
        return bool(url_matches(None, url, glob))
    except ImportError:
        import re
        out, i, depth = "", 0, 0
        while i < len(glob):
            c = glob[i]
            if c == "\\" and i + 1 < len(glob):
                out += re.escape(glob[i + 1])
                i += 1
            elif c == "*":
                if glob[i:i + 2] == "**":
                    out += ".*"
                    i += 1
                else:
                    out += "[^/]*"
            elif c == "?":
                out += "."
            elif c == "{":
                out += "("
                depth += 1
            elif c == "}" and depth:
                out += ")"
                depth -= 1
            elif c == "," and depth:
                out += "|"
            else:
                out += re.escape(c)
            i += 1
        return re.fullmatch(out, url) is not None


def t6b_route_match():
    """F1 (critic t-1811): the glob of a cell is a ROUTE pattern - it matches the whole URL of a stand request; the bare path never does."""
    task = task_with("flow-three-requests.json")
    try:
        cells = UPF.exploration_cells(task)["cells"]
        stand = {"PUT /api/basket/{lineId}": "http://localhost:5173/api/basket/3", "GET /api/orders": "http://localhost:5173/api/orders",
                 "GET /api/products/{productId}": "http://localhost:8080/api/products/7"}
        for request, url in stand.items():
            glob = next(c["glob"] for c in cells if c["request"] == request)
            check(f"T6b {request}: the cell glob matches a stand URL", route_matches(glob, url), f"{glob} {url}")
            check(f"T6b {request}: ... with a query string", route_matches(glob, url + "?page=1&q=a"), glob)
            check(f"T6b {request} negative control: the bare path (request_identity) does NOT match", not route_matches(UPF.request_identity(request)[1], url),
                  UPF.request_identity(request)[1])
        orders = next(c["glob"] for c in cells if c["request"] == "GET /api/orders")
        check("T6b a longer path is not matched", not route_matches(orders, "http://localhost:5173/api/orders2"), orders)
        check("T6b ... nor a deeper one", not route_matches(orders, "http://localhost:5173/api/orders/5"), orders)
    finally:
        drop(task)
    for template, url, label in (("/api/orders?page=1", "http://h:1/api/orders?page=2", "a template with a query string"),
                                 ("${API}/orders", "http://localhost:8080/orders", "a variable host prefix"),
                                 ("{base}/orders", "http://localhost:8080/orders", "a placeholder host prefix"),
                                 ("api/orders", "http://localhost:8080/api/orders", "a relative path"),
                                 ("http://localhost:8080/api/x", "http://localhost:8080/api/x", "a literal host")):
        glob, why = UPF.request_route_glob({"method": "GET", "url_template": template})
        check(f"T6b {label}: a pattern, never a bare `**`", glob not in (None, "**") and why == "", f"{glob!r} {why}")
        check(f"T6b {label}: it matches the stand URL", route_matches(glob, url), f"{glob} {url}")
        check(f"T6b {label} negative control: a pattern with its `**` cut off ({glob[2:] if glob.startswith('**') else glob}) does not match",
              glob.startswith("http") or not route_matches(glob[2:], url), glob)
    for template in ("", "/", "**", "${API}", "*/"):
        glob, why = UPF.request_route_glob({"method": "GET", "url_template": template})
        check_eq(f"T6b an empty path ({template!r}): no pattern, a reason", (glob, bool(why)), (None, True))
    # the cell list: a request with no pattern has no cell and a gap line - never a bare `**`
    body = json.dumps({"requests": [{"method": "GET", "url_template": "/", "source": "code", "path": "a.ts", "line": 1, "also_at": []},
                                    {"method": "GET", "url_template": "/api/ok", "source": "code", "path": "a.ts", "line": 2, "also_at": []}],
                       "unmeasured": [], "checked": ["a.ts"]})
    task = task_with(text=body)
    try:
        got = UPF.exploration_cells(task)
        check_eq("T6b the empty-path request has no cell; the other has its two", [c["request"] for c in got["cells"]], ["GET /api/ok"] * 2)
        check("T6b ... no cell carries a bare `**`", all(c["glob"] != "**" for c in got["cells"]))
        check_eq("T6b ... and the gap is named", len(got["unmeasured"]), 1)
        gap_lines = [x for x in brief_pack.exploration_cell_lines(task)[0] if x.startswith("- gap: ")]
        check_in("T6b ... and printed as a gap line", "GET / (a.ts:1): no cell", gap_lines[0] if gap_lines else "")
    finally:
        drop(task)


def t11_side_file():
    """F3 (critic t-1811): the cells live in a side file behind ONE pointer line; a file that cannot be written is a dash, not the cells inline."""
    task = task_with("flow-three-requests.json")
    briefs = task / "work" / "briefs"
    try:
        head = brief_pack.exploration_lines(task, "T-1", "D-1", briefs, True)
        written = (briefs / "D-1-cells.md").read_text(encoding="utf-8")
        check_in("T11 the cells are in the side file", "- request_failure x GET /api/orders", written)
        check_in("T11 ... and the axis oracles", "Axis oracles: request_failure - ", written)
        check_eq("T11 the brief holds the charter line and one pointer", len(head), 2)
        check_not_in("T11 ... no cell inline", "fail_request", "\n".join(head))
        check_not_in("T11 ... a written file is not called unwritten", "not written", head[1])
        blocked = task / "work" / "blocked"
        blocked.write_text("x", encoding="utf-8")          # a FILE where the folder should be: mkdir/write fails for real
        head = brief_pack.exploration_lines(task, "T-1", "D-1", blocked / "briefs", True)
        check_eq("T11 an unwritable side file: still charter + ONE pointer", len(head), 2)
        check_in("T11 ... the pointer is a dash with the reason", "Exploration cells: — not written (", head[1])
        check_not_in("T11 ... and the cells are NOT inline", "fail_request", "\n".join(head))
    finally:
        drop(task)


def t7_guard():
    t = S.make_task(manual=("api",))
    try:
        project = t.task.parents[2]
        case_dir = MC.case_root(t.task, T.API_CASE)
        (t.task / "state").mkdir(exist_ok=True)
        (t.task / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"S6-qa-runner-1": {"role": "qa-runner", "status": "running"}}, "stages": {}}), encoding="utf-8")
        code, _ = SP.guard(project, SP.write_event(case_dir / "tried.md"))
        check_eq("T7 the real guard lets qa-runner write tried.md beside the case (exit 0)", code, 0)
        code, err = SP.guard(project, SP.write_event(t.task / "work" / "test-plan.md"))
        check_eq("T7 control of the same shape: work/test-plan.md is refused (exit 2)", code, 2)
    finally:
        S.cleanup(t)


def story_brief(dispatch=None, tried=None):
    root, task = B.story(dispatch=dispatch)
    try:
        shutil.copyfile(FIX / "flow-three-requests.json", task / "work" / "flow-requests.json")
        if tried:
            (task / "work" / "evidence" / "manual" / tried).mkdir(parents=True)
            (task / "work" / "evidence" / "manual" / tried / "tried.md").write_text("| cell |\n", encoding="utf-8")
        return B.brief()["markdown"]
    finally:
        cleanup(root)


def t8_carrier_window():
    first = story_brief()
    check_in("T8 the first manual window: the charter line", "Exploration charter:", first)
    check_in("T8 ... and ONE pointer line to its cells", "Exploration cells: qa-factory/artifacts/TP1-12586/work/briefs/S6-qa-runner-2-cells.md", first)
    check_not_in("T8 ... and no cell inline", "Axis oracles:", first)
    second = story_brief(tried="OTHER-CASE")
    # X7-3: the charter's Good-outcome item "Exploration cells are rows" is now the brief's DoD in EVERY S6 brief, so the bare word is no
    # longer a carrier mark; the carrier lines are the two with their colon.
    check_not_in("T8 a tried.md in ANOTHER case's folder: no exploration lines", "Exploration charter:", second)
    check_not_in("T8 ... and no cells pointer", "Exploration cells:", second)
    auto = {**B.DISPATCH, "execution_kind": "automation", "request_binding": {"purpose": "manual", "execution_kind": "automation"}}
    plain = story_brief(dispatch=auto)
    check_not_in("T8 an automated S6 brief: no exploration lines", "Exploration charter:", plain)
    check_not_in("T8 ... and no cells pointer", "Exploration cells:", plain)
    with patch.object(brief_pack, "exploration_lines", return_value=[]):
        without = story_brief(dispatch=auto)
    check_eq("T8 ... and it is byte for byte the brief without X3", plain, without)


def t9_unreadable_table():
    task = task_with("flow-three-requests.json")
    folder = Path(tempfile.mkdtemp(prefix="qa-explore-bad-"))
    broken = folder / "perturbations.json"
    broken.write_text("{ not json", encoding="utf-8")
    try:
        with patch.object(UPF, "PERTURBATIONS_FILE", broken):
            lines = brief_pack.exploration_lines(task, "T-1")
            failure = UPF.failure_axis()
        cells = [x for x in lines if x.startswith("Exploration cells")]
        check_eq("T9 one line says the table cannot be read", len(cells), 1)
        check_in("T9 ... and names it", "references/perturbations.json cannot be read (", cells[0])
        check_eq("T9 the brief is still built (the charter line stands)", lines[0].startswith("Exploration charter:"), True)
        check_eq("T9 failure_axis answers as before: no kinds, no oracle, the reason", (failure[0], failure[1], "cannot be read" in failure[2]),
                 (None, "", True))
    finally:
        drop(task)
        shutil.rmtree(folder, ignore_errors=True)


def t10_road_to_s7():
    row = {"case": "TC-1", "result": "pass", "observations": [
        {"step": "type input 12", "expected": "12 kept", "seen": "1", "evidence": "work/evidence/manual/TC-1/a1/003-type-input.txt",
         "quote": "2\t1\tfocus=no"}]}
    check_eq("T10 a violated oracle recorded in observations[] is a target of triage", C.triage_targets(
        {"current_manual_checks": [row]})["observations"], {"TC-1#obs1"})
    check_eq("T10 control: no observation, no target", C.triage_targets(
        {"current_manual_checks": [{**row, "observations": []}]})["observations"], set())


def main():
    t1_cells()
    t2_lines()
    t3_unmeasured()
    t4_ceiling()
    t5_keyboard()
    t6_request_cell_to_step()
    t6b_route_match()
    t7_guard()
    t8_carrier_window()
    t9_unreadable_table()
    t10_road_to_s7()
    t11_side_file()
    finish("test_exploration_perturbations")


if __name__ == "__main__":
    main()
