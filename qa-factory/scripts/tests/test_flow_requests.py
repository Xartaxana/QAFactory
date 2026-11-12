#!/usr/bin/env python3
"""RN1-6: the requests of the flow reach the S3 brief and the S3 exit owes each one a failure (500, timeout).
KEYS: R1 the LOCAL-1 shape (five requests through the config's checkout and a file named in a note), R2 one request, R3 duplicates (one
entry, `also_at`; two spellings of one endpoint are one), R4 adversarial call sites (a map `get`, a comment, a template prefix, a
concatenation, a non-literal address, two calls on one line, the method window stopping at the next call, a nested template), R5 empty
(a reason, never "no requests"), R6 an unreadable table, R7 relative paths, R8 one file set with the failures, R9 AR-1 pins,
B1 the brief cap AT and BEYOND, B2 the closing line, B3 the wiring, B4 a script that raises, B5 the head's size and the site names (RN1-6 N2-2),
N1 the neighbours of the flow through the requests (N2-1),
C1-C9 the S3 exit (covered, missing, 500 vs timeout, `*`, an unlisted request, absent / broken / empty list, a bad kind, the cap, the R of the row).
Mutations (each killed by THIS file): dedupe off -> R3; `bare_method` ignored -> R1; the method window not stopped at the next call -> R4;
`MAX_REQUEST_LINES` + 1 -> B1; the closure counts the key only (not the kind) -> C3; `*` not honoured -> C4; the OK condition without
`requests_found` -> C2; a nested template left unclosed -> R4; the unreadable file read as OK -> C6;
the site names off -> B5; the neighbours not added for the requests -> N1."""
import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack as BP  # noqa: E402
import branch_accounting as BA  # noqa: E402
import planning_contract as PC  # noqa: E402
import user_path_failures as UPF  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "user-path-failures"
LIST = "qa-factory/artifacts/QA-9/work/flow-requests.json"
CART, CARTS, LOGIN = "App/src/pages/CartPage.tsx", "App/src/lib/cartService.ts", "App/src/pages/LoginPage.tsx"
APP = {"src/pages/CartPage.tsx": "CartPage.tsx", "src/lib/cartService.ts": "cartService.ts", "src/pages/LoginPage.tsx": "LoginPage.tsx"}


def world(app_files, facts, git=False):
    """A project `proj/` whose config maps repo `App` to the sibling checkout `../app` holding `app_files` {path: fixture name | lines}, and a
    story QA-9 whose bundle names `facts` ([(path, note)]). Returns (base dir, project, task root); the caller cleans `base` up."""
    base = harness.temp_dir("qa-flow-")
    proj = harness.mark_project(base / "proj")
    cfg = json.loads((proj / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    cfg["implementation_repos"] = [{"repo_id": "App", "local_path": "../app"}]
    (proj / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    for rel, body in app_files.items():
        target = base / "app" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (FIX / body).read_text(encoding="utf-8") if isinstance(body, str) else "\n".join(body) + "\n"
        target.write_text(text, encoding="utf-8")
    if git:
        subprocess.run(["git", "init", "-q"], cwd=str(base / "app"), check=True)
        subprocess.run(["git", "add", "-A"], cwd=str(base / "app"), check=True)
    task = proj / "qa-factory" / "artifacts" / "QA-9"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "stages": {}, "gates": {}, "halts": []}), encoding="utf-8")
    bundle = {"facts": [{"id": f"f{i}", "path": p, "line": 1, **({"note": n} if n else {})} for i, (p, n) in enumerate(facts, 1)],
              "source_revisions": [{"repo": "App"}]}
    (task / "work" / "context-bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    return base, proj, task


def flow(app_files, facts, git=False, **kw):
    base, proj, task = world(app_files, facts, git)
    try:
        return UPF.flow_requests(task, project_root=proj, **kw)
    finally:
        harness.cleanup(base)


def keys_of(lines, name="x.ts", **kw):
    """The request keys of one file of `lines`, and the whole result."""
    got = flow({f"src/{name}": lines}, [(f"App/src/{name}", None)], **kw)
    return [UPF.request_key(r) for r in got["requests"]], got


def r1_local_shape() -> None:
    base, proj, task = world(APP, [(CART, "called from LoginPage.tsx:8"), (CARTS, None)], git=True)
    try:
        got = UPF.flow_requests(task, project_root=proj)
        check_eq("R1 the five requests of the LOCAL-1 shape, in (path, line) order of their first site, placeholders named after the variable",
                 [UPF.request_key(r) for r in got["requests"]],
                 ["GET /api/cart", "GET /api/books/{bookId}", "PUT /api/cart/{itemId}", "DELETE /api/cart/{itemId}", "POST /api/cart/merge"])
        check("R1 each entry has the fields, `source` code and an int line", all(
            list(r) == ["method", "url_template", "source", "path", "line", "also_at"] and r["source"] == "code" and isinstance(r["line"], int)
            for r in got["requests"]), str(got["requests"]))
        check_eq("R1 the file named only in a note is among the files read (via `git ls-files`)", got["checked"], sorted([CART, CARTS, LOGIN]))   # MERGE t-1696: main reads the bundle files in sorted label order (RN1-5 `_bundle_files`)
        first = got["requests"][0]
        check_eq("R7 the stored path is the bundle's relative spelling", (first["path"], first["line"]), (CART, 4))
        check("R7 no stored path is absolute", all(not r["path"].startswith("/") and ":" not in r["path"].split("/")[0] for r in got["requests"]))
        import user_path_failures as other
        found = other.find(task, project_root=proj)
        check_eq("R8 the failures and the requests read ONE file set (no diff)", found["checked"], got["checked"])
    finally:
        harness.cleanup(base)


def r2_to_r5_call_sites() -> None:
    keys, _ = keys_of(["const r = fetch('/api/x')"])
    check_eq("R2 one request", keys, ["GET /api/x"])
    cases = [("a map `get` is no request", ["const v = map.get('key')"], []),
             ("a client verb with a path", ["api.get('/v1/a')"], ["GET /v1/a"]),
             ("a `$`-named client", ["$http.post('/b')"], ["POST /b"]),
             ("a comment", ["// fetch('/c')", " * fetch('/c2')"], []),
             ("a template prefix and a query string", ["fetch(`${base}/d?x=${y}`)"], ["GET {base}/d"]),
             ("a concatenated operand is named", ["fetch('/api/books/' + id)"], ["GET /api/books/{id}"]),
             ("a dotted interpolation is named by its last identifier", ["fetch(`/api/b/${item.bookId}`)"], ["GET /api/b/{bookId}"]),
             ("an interpolated call is the unnamed placeholder", ["fetch(`/api/b/${make(x)}`)"], ["GET /api/b/{*}"]),
             ("options of unknown content: the verb is not claimed", ["fetch('/e', opts)"], ["ANY /e"]),
             ("two calls on one line", ["fetch('/f'); fetch('/g', { method: 'DELETE' })"], ["GET /f", "DELETE /g"]),
             ("the verb window stops at the next call", ["fetch('/a', opts)", "fetch('/b', { method: 'POST' })"], ["ANY /a", "POST /b"]),
             ("the verb 1-7 lines below", ["fetch('/m', {", "  headers: {},", "  method: 'PATCH',", "})"], ["PATCH /m"]),
             ("a nested template literal (A-2): cut at the unclosed interpolation, never a broken key",
              ["fetch(`/api/books${q ? `?${q}` : ''}`)"], ["ANY /api/books{*}"])]
    for label, lines, expected in cases:
        keys, _ = keys_of(lines)
        check_eq(f"R4 {label}", keys, expected)
    keys, got = keys_of(["fetch(url, opts)", "const ok = 1"])
    check("R4 an address that is no literal: no entry, a reason naming its line", keys == [] and any(
        "x.ts: 1 call site(s) whose address is not a literal: 1" in u for u in got["unmeasured"]), str(got))
    keys, got = keys_of(["a();", "b();"])
    check("R5 a file with no call: no requests and a reason that says where it looked, never `no requests`", keys == [] and any(
        u.startswith("no call site") and "(1 checked)" in u for u in got["unmeasured"]) and not any("no requests" in u for u in got["unmeasured"]), str(got))
    base, proj, task = world({}, [])
    try:
        got = UPF.flow_requests(task, project_root=proj)
        check_eq("R5 nothing to read at all: `no code`", (got["requests"], got["unmeasured"]), ([], ["no code"]))
    finally:
        harness.cleanup(base)
    keys, got = keys_of(["fetch('/a')", "x();", "fetch('/a')"], name="dup.ts")
    check_eq("R3 one request twice in one file: ONE entry, the other site in `also_at`", [(r["line"], r["also_at"]) for r in got["requests"]],
             [(1, ["App/src/dup.ts:3"])])
    got = flow({"src/a.ts": ["fetch('/api/cart')", "x();", "fetch('/api/cart')"], "src/b.ts": ["fetch('/api/cart')"]},
               [("App/src/a.ts", None), ("App/src/b.ts", None)])
    check_eq("R3 the same request in two files and twice in one: ONE entry at the first site, 2 other sites",
             [(r["path"], r["line"], r["also_at"]) for r in got["requests"]], [("App/src/a.ts", 1, ["App/src/a.ts:3", "App/src/b.ts:1"])])
    got = flow({"src/a.ts": ["fetch(`/api/books/${bookId}`)"], "src/b.ts": ["fetch(`/api/books/${item.bookId}`)"],
                "src/c.ts": ["fetch(`/api/books/${x.id}`)"]}, [("App/src/a.ts", None), ("App/src/b.ts", None), ("App/src/c.ts", None)])
    check_eq("R3b two spellings of one endpoint share one entry (the glob is the key), at the first site's template",
             [(UPF.request_key(r), len(r["also_at"])) for r in got["requests"]], [("GET /api/books/{bookId}", 2)])


def r6_table() -> None:
    base = harness.temp_dir("qa-flow-bad-")
    try:
        bad = base / "request-call-patterns.json"
        for body in ("not json", json.dumps({"calls": "x"}), json.dumps({"languages": [".ts"], "calls": []})):
            bad.write_text(body, encoding="utf-8")
            with patch.object(UPF, "REQUESTS_FILE", bad):
                keys, got = keys_of(["fetch('/a')"])
            check("R6 an unreadable table: no requests, a reason naming the table, nothing raised",
                  keys == [] and any("request-call-patterns.json" in u and "a defect of the factory" in u for u in got["unmeasured"]), str(got))
        row = {"languages": [".ts"], "comment": "^x", "non_literal": "y", "interpolation": "z", "interpolation_open": "${", "name_of": "n",
               "named_as": "{<name>}", "unnamed_as": "{*}", "concat_tail": "t", "query_mark": "?", "glob_match": "g", "glob_as": "*",
               "calls": [{"id": "broken", "start": "("}, {"id": "ok", "start": "\\bget\\((?P<q>')(?P<url>[^']*)(?P=q)\\)"}]}
        bad.write_text(json.dumps(row), encoding="utf-8")
        table, problems = UPF.load_request_table(bad)
        check("R6 a row that does not compile is named and skipped, the others stay", table is not None and [c["id"] for c in table["calls"]] == ["ok"]
              and len(problems) == 1 and "broken" in problems[0], str(problems))
    finally:
        harness.cleanup(base)


def r9_pins() -> None:
    table = json.loads((SCRIPTS.parent / "references" / "request-call-patterns.json").read_text(encoding="utf-8"))
    check_eq("R9 the request table compiles without a problem", UPF.load_request_table()[1], [])
    check("R9 the table holds the call shapes", [c["id"] for c in table["calls"]] == ["fetch", "client_verb"])
    check_eq("R9 the perturbation table gives the kinds and the oracle", UPF.failure_axis()[0], ["500", "timeout"])
    check_in("R9 ... and its oracle is the axis oracle, not a value read from code", "the person is told of the error in words", UPF.failure_axis()[1])
    with patch.object(UPF, "PERTURBATIONS_FILE", Path("nowhere.json")):
        check("R9 an unreadable perturbation table is named, never raised", UPF.failure_axis()[0] is None and "cannot be read" in UPF.failure_axis()[2])


def req(n, method="GET", url=None):
    return {"method": method, "url_template": url or f"/api/r{n}", "source": "code", "path": "App/src/a.ts", "line": n, "also_at": []}


def b_brief() -> None:
    cap = BP.MAX_REQUEST_LINES
    for n, more in ((cap, False), (cap + 1, True)):
        base = harness.temp_dir("qa-flow-b-")
        try:
            task = base / "qa-factory" / "artifacts" / "QA-9"
            found = {"requests": [req(i) for i in range(1, n + 1)], "unmeasured": [], "checked": ["App/src/a.ts"]}
            UPF.write_requests(task, found)
            out = BP.request_lines(found, "QA-9")
            check_eq(f"B1 {n} requests: {cap} request lines", sum(x.startswith("Flow requests: GET /api/r") for x in out), cap)
            more_lines = [x for x in out if " more, the list is in " in x]
            check_eq(f"B1 {n} requests: the 'more' line", more_lines, [f"Flow requests: 1 more, the list is in {LIST}"] if more else [])
            check_eq(f"B1 {n} requests: the file is whole", len(json.loads((task / "work" / "flow-requests.json").read_text(encoding="utf-8"))["requests"]), n)
        finally:
            harness.cleanup(base)
    out = BP.request_lines({"requests": [dict(req(1), also_at=["a:1", "b:2"])], "unmeasured": ["no request pattern for .java"]}, "QA-9")
    check_in("B2 one request: the line carries its place and the other files that make it (B5 below)", "Flow requests: GET /api/r1 - App/src/a.ts:1 (also in a, b)", out)
    check_in("B2 ... a reason is a `not measured` line", "Flow requests: not measured: no request pattern for .java", out)
    closing = out[-1]
    check("B2 the closing line names the file, the kinds, the oracle read from the table, the R and both doors", all(s in closing for s in (
        LIST, "500 and timeout", UPF.failure_axis()[1], "`requirements`", "`requests`", "`request_homes`")), closing)
    clause = "A row closes the request only for the pages it names: another page that makes the same request needs its own row or a stated reason."
    check_in("B2 (t-1692 F2) the closing line says a row closes the request only for the pages it names", clause, closing)
    check_eq("B2 no request: no closing line", [x for x in BP.request_lines({"requests": [], "unmeasured": ["no code"]}, "QA-9") if "each one gets" in x], [])
    with patch.object(UPF, "flow_requests", side_effect=RuntimeError("boom")):
        check_eq("B4 a script that raises: exactly one line, the brief is built", BP.flow_request_lines(Path("nowhere"), "QA-9", write=False),
                 ["Flow requests: not measured: user_path_failures.py, a defect of the factory"])
    big = {"requests": [req(i, url="/api/a/very/long/path/of/a/request/" + "x" * 60 + str(i)) for i in range(1, cap + 6)], "unmeasured": ["no code"] * 3}
    size = len("\n".join(BP.request_lines(big, "QA-9")).encode("utf-8"))
    check("B5 the lines added to the S3 head stay under half of the brief ceiling (the head is never shrunk)", size <= BP.BRIEF_MAX_BYTES // 2,
          f"{size} bytes")


def b5_site_names() -> None:
    """RN1-6 N2-2: a request's other callers are named by file, not counted."""
    def line(also):
        out = BP.request_lines({"requests": [dict(req(1), also_at=also)], "unmeasured": []}, "QA-9")
        return out[0].split(" - App/src/a.ts:1", 1)[1]
    other = [f"App/src/pages/p{i}.tsx:{i}" for i in range(1, 5)]
    check_eq("B5 one other file: its basename", line(other[:1]), " (also in p1.tsx)")
    check_eq("B5 three other files (AT SITE_FILES_SHOWN): three names, no tail", line(other[:3]), " (also in p1.tsx, p2.tsx, p3.tsx)")
    check_eq("B5 four other files (BEYOND): three names and the count of the rest", line(other), " (also in p1.tsx, p2.tsx, p3.tsx, +1 more)")
    check_eq("B5 two sites of one other file: one name", line(["App/src/pages/p1.tsx:3", "App/src/pages/p1.tsx:9"]), " (also in p1.tsx)")
    check_eq("B5 only the first site's own file: the count, in this file", line(["App/src/a.ts:5", "App/src/a.ts:9"]), " (+2 more sites in this file)")
    check_eq("B5 own file and another: the other is named, the own file is not", line(["App/src/a.ts:5", "App/src/pages/p1.tsx:3"]), " (also in p1.tsx)")
    check_eq("B5 no other site: nothing added", line([]), "")
    many = {"requests": [dict(req(i, url="/api/a/very/long/path/of/a/request/" + "x" * 200 + str(i)), also_at=other) for i in range(1, BP.MAX_REQUEST_LINES + 1)],
            "unmeasured": ["no code"] * 3}
    out = BP.request_lines(many, "QA-9")
    check("B5 over the room (half of the brief ceiling) the names are cut first: the old `(+N more sites)` returns, every request line stays",
          sum("(+4 more sites)" in x for x in out) == BP.MAX_REQUEST_LINES and not any("also in" in x for x in out)
          and sum(x.startswith("Flow requests: GET /api/a/") for x in out) == BP.MAX_REQUEST_LINES, str(out[:2]))
    check("B5 ... and under the room the names stay", all("also in" in x for x in BP.request_lines({"requests": [dict(req(1), also_at=other)], "unmeasured": []}, "QA-9")[:1]))


def n1_neighbours() -> None:
    """RN1-6 N2-1 through the requests: the bundle names the page that adds to the cart, never the cart page."""
    add = ["const add = () => fetch('/api/cart', { method: 'POST' })"]
    base, proj, task = world({**APP, "src/pages/AddToCart.tsx": add}, [("App/src/pages/AddToCart.tsx", None)], git=True)
    try:
        got = UPF.flow_requests(task, project_root=proj)
        keys = [UPF.request_key(r) for r in got["requests"]]
        check("N1 the cart page joined as a neighbour: its requests are in the list, named placeholders", all(
            k in keys for k in ("POST /api/cart", "GET /api/books/{bookId}", "PUT /api/cart/{itemId}", "DELETE /api/cart/{itemId}")), str(keys))
        check_in("N1 ... the cart page is among the files read", CART, got["checked"])
        entry = next(r for r in got["requests"] if r["url_template"] == "/api/books/{bookId}")
        check_eq("N1 ... and its place is the cart page", entry["path"], CART)
    finally:
        harness.cleanup(base)


REGISTER = "## Register\n\n| R | requirement | source | derived_from |\n|---|---|---|---|\n"


def detector(task: Path, doc: dict, requests=None, raw=None, plan_errors=()):
    """Run `planning_contract.detector_main` over the story `task` (the plan's own checks stubbed clean, the register empty); `requests` is
    written as `work/flow-requests.json` by the one writer, `raw` as its text. (exit code, printed text)."""
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (task / "work" / "test-plan.json").write_text(json.dumps(doc), encoding="utf-8")
    if requests is not None:
        UPF.write_requests(task, {"requests": requests, "unmeasured": [], "checked": []})
    if raw is not None:
        (task / "work" / "flow-requests.json").write_text(raw, encoding="utf-8")
    saved = PC.detector_story, PC.gate_plan_errors
    PC.detector_story, PC.gate_plan_errors = (lambda *a, **k: task), (lambda *a, **k: list(plan_errors))
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = PC.detector_main(task)
    finally:
        PC.detector_story, PC.gate_plan_errors = saved
    return code, out.getvalue()


def row(rid="TS-1", requests=None, requirements=("R-9",)):
    out = {"id": rid, "disposition": "skip", "reason": "r"}
    if requirements is not None:
        out["requirements"] = list(requirements)
    if requests is not None:
        out["requests"] = requests
    return out


def covers(key, *failures):
    return {"request": key, "failures": list(failures)}


def c_closure() -> None:
    base = harness.temp_project("qa-flow-c-")
    task = base / "qa-factory" / "artifacts" / "QA-1"
    cart, merge = req(4, url="/api/cart"), req(8, "POST", "/api/cart/merge")
    both = lambda *keys: [covers(k, "500", "timeout") for k in keys]     # noqa: E731
    try:
        code, text = detector(task, {"rows": [row(requests=both("GET /api/cart", "POST /api/cart/merge"))]}, [cart, merge])
        check("C1 both requests covered with both kinds: OK, exit 0", code == 0 and "OK:" in text and "flow requests" not in text, f"{code} {text}")
        code, text = detector(task, {"rows": [row(requests=both("GET /api/cart"))]}, [cart, merge])
        check("C2 one request left: REJECT (exit 1), never OK", code == 1 and "OK:" not in text, f"{code} {text}")
        check_in("C2 ... the block", "REJECT — 1 problem(s) in the plan's flow requests", text)
        line = next(x for x in text.splitlines() if x.startswith("- POST /api/cart/merge"))
        check("C2 ... the line names the request, its place and both doors", all(s in line for s in ("(App/src/a.ts:8)", "`requests`", "`request_homes`")), line)
        check_in("C2 ... the summary counts it", "1 request problem(s)", text)
        check_in("C2 ... and the person's word passes it", "A person's word passes any of these", text)
        one = [cart]
        code, text = detector(task, {"rows": [row(requests=[covers("GET /api/cart", "500")])]}, one)
        check("C3 only 500 planned: the line names timeout, and only timeout", code == 1 and "no plan row fails it with timeout -" in text
              and "fails it with 500" not in text, f"{code} {text}")
        home = {"request": "GET /api/cart", "failure": "timeout", "reason": "the server never times out here"}
        code, text = detector(task, {"rows": [row(requests=[covers("GET /api/cart", "500")])], "request_homes": [home]}, one)
        check("C3 ... homed with a reason: exit 0", code == 0 and "OK:" in text, f"{code} {text}")
        code, text = detector(task, {"rows": [row(requests=[covers("GET /api/cart", "500")])], "request_homes": [dict(home, reason=" ")]}, one)
        check("C3 ... a home with a blank reason: a form line, still refused", code == 1 and "request_homes[0] has no `reason`" in text, f"{code} {text}")
        code, text = detector(task, {"rows": [], "request_homes": [dict(home, failure="*")]}, one)
        check("C4 `failure: *` homes both kinds", code == 0 and "OK:" in text, f"{code} {text}")
        code, text = detector(task, {"rows": [row(requests=both("GET /api/cart", "GET /api/unlisted"))]}, one)
        check("C5 a row naming a request the list lacks: no problem from it, a WARN says it counts for nothing", code == 0 and "OK:" in text
              and "WARN row(s) name a request that is no request of work/flow-requests.json" in text, f"{code} {text}")
        code, text = detector(task, {"rows": [row(requests=both("GET /api/cart/{id}"))]}, [req(1, url="/api/cart/{itemId}")])
        check("C5 two spellings of one endpoint: the row covers it (compared by method and glob)", code == 0 and "OK:" in text, f"{code} {text}")
        code, text = detector(task, {"rows": [row(requests=[covers("GET /api/cart", "404")])]}, one)
        check("C7 a failure outside the kinds: a form line naming the kinds", code == 1 and "requests[0] names a failure outside 500, timeout" in text, f"{code} {text}")
        code, text = detector(task, {"rows": [row(requests=both("GET /api/cart"), requirements=None)]}, one)
        check("C9 a row with requests and no requirements (AR-26): a form line", code == 1 and "has `requests` and no `requirements`" in text, f"{code} {text}")
        many = [req(i) for i in range(1, 22)]
        code, text = detector(task, {"rows": []}, many)
        shown = BA.limit("refusal_units_shown")
        check_eq("C8 the refusal cap: `refusal_units_shown` lines and the tail", (sum(x.startswith("- GET /api/r") for x in text.splitlines()), code), (shown, 1))
        check_in("C8 ... the tail names what was cut", f"{len(many) - shown} more problems ({len(many)} in all)", text)
        (task / "work" / "flow-requests.json").unlink()
        code, text = detector(task, {"rows": []})
        check("C6 no flow-requests.json (a story planned before it existed): silent, exit 0", code == 0 and "OK:" in text and "request" not in text.lower(), f"{code} {text}")
        code, text = detector(task, {"rows": []}, [])
        check("C6 `requests: []`: nothing owed, exit 0", code == 0 and "OK:" in text, f"{code} {text}")
    finally:
        harness.cleanup(base)


def c_unreadable() -> None:
    base, proj, task = world(APP, [(CART, None)])
    try:
        plan = {"rows": [row()]}
        code, text = detector(task, plan, raw="not json")
        check("C6 a broken file is recomputed from the code and judged: the requests found are refused, never OK",
              code == 1 and "GET /api/cart" in text and "OK:" not in text, f"{code} {text}")
        with patch.object(UPF, "flow_requests", side_effect=RuntimeError("boom")):
            code, text = detector(task, plan, raw="not json")
        check("C6 ... a recomputation that fails too: UNREADABLE (exit 3) with a WARN, never OK", code == 3 and "UNREADABLE:" in text
              and "WARN the request closure could not run" in text and "OK:" not in text, f"{code} {text}")
        with patch.object(UPF, "flow_requests", side_effect=RuntimeError("boom")):
            code, text = detector(task, plan, raw="not json", plan_errors=["an older refusal"])
        check("C6 ... with an older REJECT standing: that REJECT is printed, no UNREADABLE hides it", code == 1 and "an older refusal" in text
              and "UNREADABLE" not in text, f"{code} {text}")
        with patch.object(UPF, "PERTURBATIONS_FILE", Path("nowhere.json")):
            code, text = detector(task, plan, requests=[req(1)])
        check("C6 an unreadable perturbation table is the same unknown: exit 3, never OK", code == 3 and "OK:" not in text, f"{code} {text}")
    finally:
        harness.cleanup(base)


for step in (r1_local_shape, r2_to_r5_call_sites, r6_table, r9_pins, b_brief, b5_site_names, n1_neighbours, c_closure, c_unreadable):
    step()
finish("flow requests")
