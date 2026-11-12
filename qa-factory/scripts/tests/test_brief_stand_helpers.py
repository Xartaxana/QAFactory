#!/usr/bin/env python3
"""SC2-38 item 4 (b): the manual runner brief's `## The stand` names the helpers of the repo map's utilities
(`brief_pack._repo_helper_lines`, through the ONE formatter `_names_by_module`, the window's `helper_lines` goes through it too).

  K4-1  AT the cap (8 names) all are named, no count; BEYOND (9) eight and `(+1 more: <map path>)` (FR-41)
  K4-2  the empty outcomes (no map, a map error, no utils, `defs` empty / None / not a list, a non-Python utility, names that are
        not strings): no `Helpers` line, the `Page objects` line as it was
  K4-3  the brief of an AUTOMATION block: byte for byte as before (no `Helpers`, no section)
  K4-4  private names are never printed
  K4-5  both fixtures (3 cases, 1 case) with 8 names named: body bytes <= BRIEF_MAX_BYTES + SD_HEAD_MAX_BYTES, the `work/automation-manifest.json` line is there
  K4-6  the shared formatter: the window's lines are the formatter's (TQ1-19 bytes) - cap AT / BEYOND

Mutants: STAND_HELPER_NAMES = 24 -> K4-5; no cap -> K4-1; the section for an automation block -> K4-3; a crash on `defs` None -> K4-2;
the `Page objects` label changed -> K4-2.
"""
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_brief_pack_manual as TBM  # noqa: E402  (its fixtures: `story()`, `real_requests()`, `repo_of()`, `brief()`)
from harness import check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

brief_pack, judge = TBM.brief_pack, TBM.judge
MAP_PATH, UTILS = TBM.MAP_PATH, TBM.UTILS
HELPERS = "- Helpers (repo map): "
PAGES = "- Page objects (repo map): "


def repo_with(defs_by_path: dict, **extra) -> dict:
    base = TBM.repo_of(list(defs_by_path))
    base["doc"]["utils"] = [{"path": p, "bytes": 1, "classes": [], "defs": d} for p, d in defs_by_path.items()]
    return {**base, **extra}


def names(n: int, prefix="m") -> list:
    return [f"{prefix}{i}" for i in range(n)]


def line_of(text: str, head: str) -> str:
    return next((x for x in text.splitlines() if x.startswith(head)), "")


def stand_text(requests, repo, dispatch=None, **kw):
    root, _task = TBM.story(requests=requests, dispatch=dispatch)
    try:
        return TBM.brief(repo, **kw)
    finally:
        cleanup(root)


def k1_cap(requests):
    four = {UTILS[0]: ["a1", "a2", "a3", "a4", "a5"], UTILS[1]: ["b1", "b2", "b3", "b4"]}     # 9 names in all
    nine = repo_with(four)
    got = line_of(stand_text(requests, nine)["markdown"], HELPERS)
    check_eq("K4-1 BEYOND the cap (9): eight names, the rest counted with the map's path", got,
             f"{HELPERS}`{UTILS[0]}`: `a1`, `a2`, `a3`, `a4`, `a5`; `{UTILS[1]}`: `b1`, `b2`, `b3` (+1 more: {MAP_PATH})")
    check_not_in("K4-1 ... the ninth is not named", "b4", got)
    eight = repo_with({UTILS[0]: ["a1", "a2", "a3", "a4", "a5"], UTILS[1]: ["b1", "b2", "b3"]})
    got = line_of(stand_text(requests, eight)["markdown"], HELPERS)
    check_eq("K4-1 AT the cap (8): all named, no count", got,
             f"{HELPERS}`{UTILS[0]}`: `a1`, `a2`, `a3`, `a4`, `a5`; `{UTILS[1]}`: `b1`, `b2`, `b3`")
    # the line sits right after the Page objects line
    text = stand_text(requests, eight)["markdown"].splitlines()
    pos = next(i for i, x in enumerate(text) if x.startswith(PAGES))
    check("K4-1 the Helpers line follows the Page objects line", text[pos + 1].startswith(HELPERS), text[pos + 1][:60])
    # a class-less method name stays a bare name (E3): printed as it is
    got = line_of(stand_text(requests, repo_with({UTILS[0]: ["create", "get"]}))["markdown"], HELPERS)
    check_in("K4-1 methods of a client come as bare names (the class is not printed)", "`create`, `get`", got)


def k2_empty(requests):
    plain = TBM.repo_of()
    base_page = line_of(stand_text(requests, plain)["markdown"], PAGES)
    check("K4-2 control: the page objects line is there", base_page.startswith(PAGES), base_page[:40])
    cases = {
        "defs empty": repo_with({UTILS[0]: []}),
        "defs None": repo_with({UTILS[0]: None}),
        "defs not a list": repo_with({UTILS[0]: "abc"}),
        "names not strings": repo_with({UTILS[0]: [1, None, {"a": 1}, ""]}),
        "private only": repo_with({UTILS[0]: ["_a", "__b"]}),
        "no utils": {**plain, "doc": {"utils": [], "empty": True}},
        "utils missing": {**plain, "doc": {}},
        "a util that is not a dict": {**plain, "doc": {"utils": ["x", None, 3]}},
        "non-python utility": {**repo_with({"pages/login.ts": []}), },
        "path missing": {**plain, "doc": {"utils": [{"defs": ["a"]}]}},
    }
    for label, repo in cases.items():
        out = stand_text(requests, repo)["markdown"]
        check_not_in(f"K4-2 {label}: no Helpers line", HELPERS, out)
        check_in(f"K4-2 {label}: the Page objects label is as it was", PAGES, out)
    out = stand_text(requests, {"error": "OSError: boom"})["markdown"]
    check_not_in("K4-2 a map error: no Helpers line", HELPERS, out)
    check_in("K4-2 ... the error line as it was", PAGES + "the map could not be built (OSError: boom)", out)
    root, _task = TBM.story(requests=requests)
    try:
        with patch.object(judge, "active", return_value=False), patch.object(brief_pack, "repo_map_for", return_value=None):
            out = brief_pack.build(TBM.TICKET, "S6", "qa-runner", TBM.DISPATCH_ID, write=False)["markdown"]
    finally:
        cleanup(root)
    check_not_in("K4-2 no map asked: no Helpers line", HELPERS, out)
    check_in("K4-2 ... the line as it was", PAGES + "no map was built for this block", out)
    # a Helpers line never changes the Page objects line
    with_defs = line_of(stand_text(requests, repo_with({p: ["x"] for p in UTILS}))["markdown"], PAGES)
    check_eq("K4-2 the Page objects line is the same with and without helpers", with_defs, base_page)


def k3_automation(requests):
    auto = {**TBM.DISPATCH, "execution_kind": "automation", "request_binding": {"purpose": "manual", "execution_kind": "automation"}}
    auto.pop("manual_case_ids")
    withd, without = repo_with({UTILS[0]: ["a1", "a2"]}), repo_with({UTILS[0]: []})
    a = stand_text(requests, withd, dispatch=auto)
    b = stand_text(requests, without, dispatch=auto)
    check_eq("K4-3 an automation block: the brief is the same byte for byte with and without helper names", a["markdown"], b["markdown"])
    check_not_in("K4-3 ... no Helpers line", HELPERS, a["markdown"])


def k4_private(requests):
    got = line_of(stand_text(requests, repo_with({UTILS[0]: ["_hidden", "shown", "__dunder__"]}))["markdown"], HELPERS)
    check_in("K4-4 a public name is named", "`shown`", got)
    check_not_in("K4-4 a private name is not", "_hidden", got)
    check_not_in("K4-4 a dunder is not", "__dunder__", got)
    got = line_of(stand_text(requests, repo_with({UTILS[0]: ["good", ["x"], {"a": 1}, 3]}))["markdown"], HELPERS)
    check_in("K4-2 an unhashable element is skipped, the good name is kept (E3)", "`good`", got)


def k5_fixtures(requests):
    full = repo_with({UTILS[0]: names(5), UTILS[1]: names(5, "n")})                     # 10 names, 8 named
    one_case = "TC-014"
    for label, dispatch in (("3 cases", None),
                            ("1 case", {**TBM.DISPATCH, "scope": [one_case], "manual_case_ids": [one_case]})):
        root, _task = TBM.story(requests=requests, dispatch=dispatch)
        try:
            out = TBM.brief(full)
            without = TBM.brief(repo_with({UTILS[0]: [], UTILS[1]: []}))
        finally:
            cleanup(root)
        print(f"MEASURED K4-5 {label}: bytes with Helpers={out['bytes']} without={without['bytes']} cap={brief_pack.BRIEF_MAX_BYTES}")
        cap = brief_pack.BRIEF_MAX_BYTES + brief_pack.SD_HEAD_MAX_BYTES     # the SD head is form outside the body budget (t-1765 X1 fix-3)
        check(f"K4-5 {label}: bytes <= body cap + SD head cap ({cap})", out["budget_bytes"] <= cap, str(out["budget_bytes"]))
        check_in(f"K4-5 {label}: the Helpers line is there", HELPERS, out["markdown"])
        check_in(f"K4-5 {label}: the manifest line stays, with its door", "work/automation-manifest.json", out["markdown"])
        check_in(f"K4-5 {label}: ... the door", "manifest_view.py", out["markdown"])
        check_in(f"K4-5 {label}: the count", "(+2 more:", out["markdown"])


def k6_formatter():
    f = brief_pack._names_by_module
    check_eq("K4-6 AT the cap: lines, no count", f([("p", ["a", "b"]), ("q", ["c"])], 3, "map"), ["`p`: `a`, `b`", "`q`: `c`"])
    check_eq("K4-6 BEYOND the cap: the count line", f([("p", ["a", "b"]), ("q", ["c"])], 2, "map"), ["`p`: `a`, `b`", "(+1 more: map)"])
    check_eq("K4-6 no modules: no lines", f([], 8, "map"), [])
    # the window: the same shape, unchanged bytes (TQ1-19): "- " + the formatter's line
    check_eq("K4-6 the window's section is the formatter's lines behind '- '",
             ["- " + x for x in f([("p", ["a"])], 60, "repo map")], ["- `p`: `a`"])


def main():
    requests = TBM.real_requests()
    k1_cap(requests)
    k2_empty(requests)
    k3_automation(requests)
    k4_private(requests)
    k5_fixtures(requests)
    k6_formatter()
    finish("test_brief_stand_helpers")


if __name__ == "__main__":
    main()
