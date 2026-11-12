#!/usr/bin/env python3
"""G2-14: places of the code that swallow a failure reach the S2 brief (t-527 s10).
KEYS: U1 the fixtures (`catch { console.error }` after a `fetch` matches; a catch with a toast and `if (!response.ok)` does not),
U2 inconvenient inputs (toast AT and BEYOND the window, multi-line fetch, `catch` in a comment, minified file), U3 the limit
(20 -> 20 lines and no "more", 21 -> 20 + "1 more, the list is in work/user-path-failures.json", the file whole), U4 not measured
(a language with no pattern, an unreadable table, a broken brief, no code, the first S2 vs a repeat S2, unparsed places), U5 AR-1
(the shapes are data, not code), U6 the brief wiring (S2 only, never raises), U7 the shapes the finding names, U8 files of the
context bundle on a story with no diff (`file:line`, a backslash, a checkout inside and outside the project, a label relative
to its root), U9 "no code" only when there was nothing at all to look at (a)-(l), U10 one match from two files and no repeated
label, U11 the S2 brief line carries it, U12 the diff keeps its scope (the bundle unread with a diff, read when the diff cannot be).
Mutations (one key each, each killed by THIS file; named, not run): `loud` not read -> U1; the limit 21 -> U3; a language with no
pattern read as empty -> U4; a broken table breaks the brief -> U4/U6; the bundle branch removed -> U8; the bundle read even with
a diff -> U12 (a); `no code` back to "no diff and no register" -> U9 (d); unreadable bundle paths dropped silently -> U9 (e); the
root check removed (an absolute path outside) -> U9 (h); the root check removed on a relative path (a link out) -> U9 (h) link
case, skipped where no link can be made; the `file_kind` filter off -> U9 (f); the `checked` dedup off -> U10 (repeat S2);
NAMES_SHOWN 8 -> 9 -> U9 (i); the `:<line>` tail kept -> U8 (second form); a backslash not replaced -> U8 (third form); checkout
roots not added -> U8 (b); an absolute label -> U8 (e); the `is absent` line not written -> U10 (third case); the bundle defect
silent -> U9 (g); `is absent` also with no register places -> U9 (k); a blank path put in `unreadable` -> U9 (c); the bundle
branch off when the diff raised -> U12 (b).
U13 RN1-5 (a repo-prefixed place through the config's checkout; the files its notes name, AT and BEYOND 5 name matches; the register's
whole-file scan kept beside the bundle's; a configured repo with no checkout named), U14 the discarded response, U15 (N1-N7, RN1-6 N2-1)
the neighbours of the flow: the pages that call an address the set calls join it (N1 the LOCAL-1 shape, N2 AT and BEYOND `NEIGHBOURS_MAX`,
N3 the scan cap AT and BEYOND, N4 a one-segment stem, N5 not a git checkout, N6 a story with a diff keeps its failures, N7 an unreadable
neighbour is named).
Mutations of RN1-5 / RN1-6 (each killed by THIS file): `with_bundle` never true -> U8 (a); the resolver without the repo-id candidate -> U13
layout; `NAME_MATCH_MAX` 5 -> 6 -> U13 notes; the `discarded_response` row removed -> U14; `NEIGHBOURS_MAX` 8 -> 9 -> N2; the stem-length
guard off -> N4; the scan cap off by one -> N3; an unreadable neighbour dropped silently -> N7."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack as BP  # noqa: E402
import user_path_failures as UPF  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "user-path-failures"
LIST = "work/user-path-failures.json"


def diff_of(files: dict) -> str:
    """A unified diff that ADDS each file {path: [lines]} whole."""
    out = []
    for path, lines in files.items():
        out += [f"diff --git a/{path} b/{path}", "new file mode 100644", "--- /dev/null", f"+++ b/{path}",
                f"@@ -0,0 +1,{len(lines)} @@"] + ["+" + t for t in lines]
    return "\n".join(out) + "\n"


def story(root: Path, files=None, register=None, bundle=None) -> Path:
    task = root / "qa-factory" / "artifacts" / "QA-9"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "stages": {}, "gates": {}, "halts": []}), encoding="utf-8")
    if files is not None:
        (task / "work" / "impl-diff.txt").write_text(diff_of(files), encoding="utf-8")
    if register is not None:
        head = "## Register\n\n| R | requirement | source | derived_from | x | ac_ref | observable |\n|---|---|---|---|---|---|---|\n"
        (task / "work" / "requirements-register.md").write_text(
            head + "".join(f"| R-{i} | t | derived | bug:candidate-defect | | | {o} |\n" for i, o in enumerate(register, 1)), encoding="utf-8")
    if bundle is not None:        # as given: a str is written raw (a broken file), anything else as JSON
        (task / "work" / "context-bundle.json").write_text(bundle if isinstance(bundle, str) else json.dumps(bundle), encoding="utf-8")
    return task


def fixture(name: str) -> list:
    return (FIX / name).read_text(encoding="utf-8").splitlines()


def hits(files: dict, register=None, project=None) -> dict:
    root = harness.temp_project("qa-upf-")
    try:
        return UPF.find(story(root, files, register), project_root=project or root)
    finally:
        harness.cleanup(root)


def put(root: Path, rel: str, lines: list) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text("\n".join(lines), encoding="utf-8")


def paths(*names) -> dict:
    return {"facts": [{"id": f"F{i}", "path": n} for i, n in enumerate(names, 1)]}


def with_bundle(disk: dict, bundle, register=None, files=None, config=None) -> dict:
    """find() on a story whose project holds `disk` {path: [lines]}, with a context bundle (and a register / a diff / config keys);
    the brief lines of the result are under `_text`."""
    root = harness.temp_project("qa-upf-")
    try:
        for rel, body in disk.items():
            put(root, rel, body)
        if config:
            cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            cfg.update(config)
            (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        got = UPF.find(story(root, files, register, bundle), project_root=root)
        got["_text"] = UPF.lines(got)
        return got
    finally:
        harness.cleanup(root)


NO_CODE = ["User-path failures: not measured: no code"]
SWALLOWED = [("swallowed_catch", "src/LoginPage.tsx", 5), ("unchecked_response", "src/LoginPage.tsx", 3)]


def tuples(got) -> list:
    return [(m["pattern"], m["file"], m["line"]) for m in got["matches"]]


def catch_with(toast_at: int) -> list:
    """A catch at line 1, a console.error at line 2, filler, a toast at line `toast_at` (0: none)."""
    lines = ["} catch (e) {", "  console.error(e);"] + ["  x();"] * 30
    if toast_at:
        lines[toast_at - 1] = "  toast.error('failed');"
    return lines


def u1_fixtures() -> None:
    got = hits({"src/swallowed.ts": fixture("swallowed.ts")})
    check_eq("U1 `catch { console.error }` after a fetch: the catch, and the fetch whose answer is read unchecked (an extra match, F-4: the role discards)",
             [(m["pattern"], m["line"]) for m in got["matches"]], [("swallowed_catch", 5), ("unchecked_response", 3)])
    got = hits({"src/handled.ts": fixture("handled.ts")})
    check_eq("U1 a catch with a toast and `if (!response.ok)`: no match", got["matches"], [])
    check_in("U1 ... and the brief says what was checked", "no match, checked: src/handled.ts", UPF.lines(got))


def u2_inconvenient() -> None:
    for at, expect in ((11, False), (12, False), (13, True), (0, True)):
        got = hits({"a.ts": catch_with(at)})
        check_eq(f"U2 toast at line {at} of a 12-line window: match is {expect}", bool(got["matches"]), expect)
    multi = ["const r = await fetch(", "  url,", "  opts", ");", "return r.json();"]
    check_eq("U2 a fetch over several lines whose answer is read unchecked: a match", [m["pattern"] for m in hits({"a.ts": multi})["matches"]],
             ["unchecked_response"])
    check_eq("U2 ... the same with `.ok` read: none", hits({"a.ts": multi + ["if (!r.ok) fail();"]})["matches"], [])
    comment = ["// } catch (e) {", "//   console.error(e);", " * catch {", " *  console.error(e)"]
    check_eq("U2 `catch` in a comment: no match", hits({"a.ts": comment})["matches"], [])
    check_eq("U2 a promise `.catch(` that only logs: a match", len(hits({"a.ts": ["p.catch((e) => console.error(e));"]})["matches"]), 1)
    mini = hits({"app.min.js": ["} catch (e) {", "console.error(e)"]})
    check("U2 a `.min.` file is not measured", mini["matches"] == [] and any("minified" in u for u in mini["unmeasured"]), str(mini))
    mini = hits({"app.js": ["x" * (UPF.MINIFIED_CHARS + 1), "} catch (e) {", "console.error(e)"]})
    check("U2 a file with a line over the limit is not measured", mini["matches"] == [] and any("minified" in u for u in mini["unmeasured"]), str(mini))
    mini = hits({"app.js": ["x" * UPF.MINIFIED_CHARS, "} catch (e) {", "console.error(e)"]})
    check_eq("U2 ... a line AT the limit is measured", len(mini["matches"]), 1)
    check_eq("U2 a test file is not scanned", hits({"tests/a.test.ts": catch_with(0)})["matches"], [])
    check_eq("U2 a test-looking name outside a test place is production (the doubt goes to a match)",
             len(hits({"src/a.test.ts": catch_with(0)})["matches"]), 1)


def u3_limit() -> None:
    def blocks(n):
        return ["} catch (e) {", "  console.error(e);", "}"] * n
    for n, extra in ((UPF.MAX_LINES, None), (UPF.MAX_LINES + 1, "1 more, the list is in work/user-path-failures.json")):
        root = harness.temp_project("qa-upf-")
        try:
            task = story(root, {"a.ts": blocks(n)})
            found = UPF.find(task, project_root=root)
            UPF.write_list(task, found)
            out = UPF.lines(found)
            check_eq(f"U3 {n} matches: {min(n, UPF.MAX_LINES)} match lines", sum("swallowed_catch" in x for x in out), min(n, UPF.MAX_LINES))
            more = [x for x in out if " more," in x]
            check_eq(f"U3 {n} matches: the 'more' line", [x.split(UPF.PREFIX)[1] for x in more], [extra] if extra else [])
            check_eq(f"U3 {n} matches: the file is whole", len(json.loads((task / LIST).read_text(encoding="utf-8"))["matches"]), n)
        finally:
            harness.cleanup(root)


def u4_not_measured() -> None:
    got = hits({"Foo.kt": ["} catch (e: Exception) {", "  println(e)"]})
    check_in("U4 a language with no pattern: said by name", "not measured: no pattern for .kt", UPF.lines(got))
    check_not_in("U4 ... and never 'no match'", "no match", UPF.lines(got))
    bad = harness.temp_project("qa-upf-bad-")
    try:
        table = bad / "patterns.json"
        for body in ("not json", json.dumps({"patterns": "x"}), json.dumps({"patterns": [{"id": "p", "window_lines": 3, "languages": [".ts"],
                                                                                         "start": "(", "quiet": "x", "loud": "y"}]})):
            table.write_text(body, encoding="utf-8")
            root = harness.temp_project("qa-upf-")
            try:
                got = UPF.find(story(root, {"a.ts": catch_with(0)}), project_root=root, patterns_file=table)
                out = UPF.lines(got)
                check("U4 a broken table is a 'not measured ... a defect of the factory' line, not 'no match'",
                      any("not measured: " in x and "a defect of the factory" in x for x in out) and not any("no match" in x for x in out), str(out))
            finally:
                harness.cleanup(root)
        # the brief is still built when the table is unreadable (P1)
        root = harness.temp_project("qa-upf-")
        try:
            task = story(root, {"a.ts": catch_with(0)})
            with patch.object(UPF, "PATTERNS_FILE", table):
                out = BP.user_path_failure_lines(task)
            check("U4 the brief lines are built and carry the defect", any("a defect of the factory" in x for x in out), str(out))
            with patch.object(UPF, "find", side_effect=RuntimeError("boom")):
                out = BP.user_path_failure_lines(task)
            check_eq("U4 a script that raises: one line, the brief is built", out,
                     ["User-path failures: not measured: user_path_failures.py, a defect of the factory"])
        finally:
            harness.cleanup(root)
    finally:
        harness.cleanup(bad)
    root = harness.temp_project("qa-upf-")
    try:
        check_eq("U4 no code and no diff: 'not measured: no code'", UPF.lines(UPF.find(story(root), project_root=root)),
                 ["User-path failures: not measured: no code"])
    finally:
        harness.cleanup(root)
    first = UPF.lines(hits({"a.ts": catch_with(0)}))
    check_in("U4 the first S2 (a diff, no register yet): the places outside the diff are not measured", "register does not exist yet", first)
    root = harness.temp_project("qa-upf-")
    try:
        (root / "src").mkdir()
        (root / "src" / "cart.ts").write_text("\n".join(["a();"] * 3 + fixture("swallowed.ts")), encoding="utf-8")
        again = UPF.find(story(root, {"b.ts": ["ok();"]}, ["current-code:src/cart.ts:4", "current-code:nowhere", "current-code:../x.ts:1",
                                                            "current-code:src/missing.ts:1", "diff:b.ts:1"]), project_root=root)
        check_eq("U4 a repeat S2: a `current-code:` place outside the diff is read", [(m["file"], m["line"]) for m in again["matches"]],
                 [("src/cart.ts", 8), ("src/cart.ts", 6)])
        check_not_in("U4 ... and the zero of the first S2 is not repeated", "register does not exist yet", again["unmeasured"])
        check_eq("U4 an unparsed place, an escaping one and a missing one are named, 3 reasons",
                 sum("cannot be parsed" in u or "not a readable file" in u for u in again["unmeasured"]), 3)
    finally:
        harness.cleanup(root)


def u5_data_not_code() -> None:
    source = (SCRIPTS / "user_path_failures.py").read_text(encoding="utf-8")
    check("U5 AR-1: no shape of a failure and no language in the script", not any(s in source for s in ("console", ".kt", "toast")))
    table = json.loads((SCRIPTS.parent / "references" / "user-path-failure-patterns.json").read_text(encoding="utf-8"))
    check_eq("U5 the table holds the three shapes", [p["id"] for p in table["patterns"]],
             ["swallowed_catch", "unchecked_response", "discarded_response"])
    check_eq("U5 the table compiles without a problem", UPF.load_patterns()[1], [])
    check_in("U5 AR-18: nothing is printed as a verdict", "return 0", (SCRIPTS / "user_path_failures.py").read_text(encoding="utf-8"))
    check_not_in("U5 ... the word REJECT is never printed", "REJECT", source)


def u6_wiring() -> None:
    src = (SCRIPTS / "brief_pack.py").read_text(encoding="utf-8")
    check_in("U6 build adds the lines at S2 only", 'if stage == "S2":\n        head += user_path_failure_lines(', src)


def u7_shapes_the_finding_names() -> None:
    """F-4 (t-612): the direction is an EXTRA match, never a miss. Each row is a shape that was missed. Mutations named, NOT run, each killed
    here: `\\bcatch\\b` back in `unchecked_response.loud` -> row 1; `logger|log` out of `quiet` -> row 2; the closing-brace line out of `quiet`
    -> rows 3, 4; the `.catch(() => null)` shape out -> row 5; context lines dropped from `_diff_files` -> row 6."""
    def kinds(lines):
        return sorted({(m["pattern"]) for m in hits({"a.ts": lines})["matches"]})
    check_eq("U7 1 a fetch read with .json() whose catch only toasts (a 500 never throws): the unchecked answer",
             kinds(["try {", "  const r = await fetch(url);", "  return r.json();", "} catch (e) {", "  toast(e);", "}"]), ["unchecked_response"])
    check_eq("U7 2 `logger.error` in a catch", kinds(["} catch (e) {", "  logger.error(e);"]), ["swallowed_catch"])
    java = hits({"A.java": ["} catch (Exception e) {", "  log.error(e);"]})
    check_eq("U7 2 ... and Java `log.error`", [m["pattern"] for m in java["matches"]], ["swallowed_catch"])
    check_eq("U7 3 an empty catch over several lines", kinds(["} catch (e) {", "}"]), ["swallowed_catch"])
    check_eq("U7 4 a comment-only catch body", kinds(["} catch (e) {", "  // ignore", "}"]), ["swallowed_catch"])
    check_eq("U7 5 `.catch(() => null)`", kinds(["load().catch(() => null);"]), ["swallowed_catch"])
    check_eq("U7 5 ... and `.catch(e => undefined)`", kinds(["load().catch(e => undefined);"]), ["swallowed_catch"])
    check_eq("U7 control: a catch that rethrows after the log is still not matched on the throw", kinds(["} catch (e) {", "  console.error(e);", "  throw e;", "}"]), [])
    why = json.loads((SCRIPTS.parent / "references" / "user-path-failure-patterns.json").read_text(encoding="utf-8"))["patterns"][0]["why"]
    check_in("U7 the block-end limit (a window of lines, not the block) is NAMED in the line the role reads", "the window is lines, not the block", why)
    root = harness.temp_project("qa-upf-")
    try:
        task = story(root)
        (task / "work" / "impl-diff.txt").write_text(
            "diff --git a/src/a.ts b/src/a.ts\n--- a/src/a.ts\n+++ b/src/a.ts\n@@ -10,2 +10,3 @@\n } catch (e) {\n+  console.error(e);\n   x();\n", encoding="utf-8")
        got = UPF.find(task, project_root=root)
        check_eq("U7 6 an ADDED log call inside an OLD catch (the catch line is context): matched at the catch",
                 [(m["pattern"], m["line"]) for m in got["matches"]], [("swallowed_catch", 10)])
    finally:
        harness.cleanup(root)


def u8_bundle_without_diff() -> None:
    page = {"src/LoginPage.tsx": fixture("swallowed.ts")}
    for form, name in (("plain", "src/LoginPage.tsx"), ("file:line", "src/LoginPage.tsx:36"), ("backslash", "src\\LoginPage.tsx")):
        got = with_bundle(page, paths(name))
        check_eq(f"U8 (a) no diff, no register, the bundle names the file ({form}): the matches, whole file", tuples(got), SWALLOWED)
        check_eq(f"U8 (a) ({form}) checked", got["checked"], ["src/LoginPage.tsx"])
        check_not_in(f"U8 (a) ({form}) no 'no code'", "no code", got["unmeasured"])
    bundle = {"facts": [{"id": "F1", "path": "src/x.ts"}], "source_revisions": [{"repo": "app", "source_sha": "x"}]}
    got = with_bundle({"app/src/x.ts": fixture("swallowed.ts")}, bundle, config={"implementation_repos": [{"repo_id": "app", "local_path": "app"}]})
    check_eq("U8 (b) a checkout inside the project: found through the configured checkout, the label from the project",
             [m["file"] for m in got["matches"]], ["app/src/x.ts", "app/src/x.ts"])
    out = Path(tempfile.mkdtemp(prefix="qa-upf-out-"))
    try:
        put(out, "src/y.ts", fixture("swallowed.ts"))
        cfg = {"implementation_repos": [{"repo_id": "app", "local_path": str(out)}]}
        revisions = [{"repo": "app", "source_sha": "x"}]
        for form, name in (("relative", "src/y.ts"), ("absolute", str(out / "src" / "y.ts"))):
            got = with_bundle({}, {"facts": [{"id": "F1", "path": name}], "source_revisions": revisions}, config=cfg)
            files = {m["file"] for m in got["matches"]}
            check_eq(f"U8 (e) a checkout OUTSIDE the project, {form} path: the label is relative to the checkout", files, {"src/y.ts"})
            blob = json.dumps(got)
            check(f"U8 (e) ({form}) no machine path in matches, checked or the list (AR-4)",
                  out.name not in blob and ":" not in "".join(files | set(got["checked"])) and not any(f.startswith("/") for f in files), blob[:300])
        got = with_bundle({"src/y.ts": ["ok();"]}, {"facts": [{"id": "F1", "path": "src/y.ts"}], "source_revisions": revisions}, config=cfg)
        check_eq("U8 (f) the same relative path in the project and in a checkout: the project's file is read under one label",
                 (got["checked"], got["matches"]), (["src/y.ts"], []))
        check_in("U8 (f) ... and the second is named", "more than one checkout, only the first was read: src/y.ts", got["_text"])
    finally:
        shutil.rmtree(out, ignore_errors=True)


def u9_no_code_only_when_nothing_was_there() -> None:
    blank = {"facts": [{"id": "F1", "path": "   "}, {"id": "F2", "path": ""}, {"id": "F3", "path": 7}, "text", {"id": "F4", "path": None}]}
    for name, bundle in (("(a) no bundle", None), ("(b) no facts", {"facts": []}), ("(c) facts with no path", {"facts": [{"id": "F1", "value": "x"}]}),
                         ("(c) blank, empty and non-string paths", blank), ("(c) facts that is no list", {"facts": {"path": "src/a.ts"}})):
        check_eq(f"U9 {name}: exactly 'no code'", with_bundle({}, bundle)["_text"], NO_CODE)
    got = with_bundle({"src/clean.ts": ["export const a = 1;"]}, paths("src/clean.ts"))
    check_in("U9 (d) a file with no match: 'no match, checked'", "no match, checked: src/clean.ts", got["_text"])
    check_not_in("U9 (d) ... and no 'no code'", "no code", got["_text"])
    got = with_bundle({}, paths("src/gone.ts"))
    check_in("U9 (e) only a missing path: named as not readable",
             "1 file(s) the context bundle names are not readable files of the project or its checkouts: src/gone.ts", got["_text"])
    check_not_in("U9 (e) ... and no 'no code'", "no code", got["_text"])
    got = with_bundle({"tests/a.test.ts": catch_with(0)}, paths("tests/a.test.ts"))
    check_in("U9 (f) only a test file: 'no production file'", "names no production file (1 test, docs, config or generated)", got["_text"])
    check_eq("U9 (f) ... not scanned, no 'no code'", (got["matches"], got["checked"], "no code" in "\n".join(got["_text"])), ([], [], False))
    for body in ("not json", []):
        got = with_bundle({}, body)
        check_in(f"U9 (g) a bundle that is {body!r}: a defect of the factory", "work/context-bundle.json cannot be read, a defect of the factory", got["_text"])
        check_not_in(f"U9 (g) ({body!r}) no 'no code'", "no code", got["_text"])
    outside = Path(tempfile.mkdtemp(prefix="qa-upf-out-"))
    try:
        put(outside, "x.ts", fixture("swallowed.ts"))
        absolute = str(outside / "x.ts")
        got = with_bundle({"x.ts": ["ok();"]}, paths("../x.ts", absolute, "a\x00b.ts", "src/../../x.ts"))
        check_in("U9 (h) `..`, an absolute path outside, a NUL, an escaping middle: 4 names, nothing read",
                 "4 file(s) the context bundle names are not readable files", got["_text"])
        check_eq("U9 (h) ... no match, nothing checked", (got["matches"], got["checked"]), ([], []))
        check_in("U9 (h) the absolute path outside is among the names", absolute.replace("\\", "/"), got["_text"])
        # a folder link out of the project: the one way a relative path can leave a root once `..` is refused (a symlink, or a junction
        # on Windows; skipped where neither can be made)
        root = harness.temp_project("qa-upf-")
        try:
            try:
                os.symlink(outside, root / "lnk", target_is_directory=True)
            except (OSError, NotImplementedError):
                made = os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "lnk"), str(outside)], capture_output=True).returncode == 0
            else:
                made = True
            if not made:
                print("SKIP U9 (h) a link out of the project: no link can be made on this machine")
            else:
                got = UPF.find(story(root, None, None, paths("lnk/x.ts")), project_root=root)
                check_eq("U9 (h) a link that leaves the project is not read", (got["matches"], got["checked"]), ([], []))
                check("U9 (h) ... and it is named", any("not readable files" in u for u in got["unmeasured"]), str(got))
        finally:
            harness.cleanup(root)
    finally:
        shutil.rmtree(outside, ignore_errors=True)
    for n in (UPF.NAMES_SHOWN, UPF.NAMES_SHOWN + 1):
        got = with_bundle({}, paths(*[f"src/n{i}.ts" for i in range(n)]))
        line = next(x for x in got["_text"] if "not readable files" in x)
        check_eq(f"U9 (i) {n} missing paths: 8 names printed", sum(f"src/n{i}.ts" in line for i in range(n)), 8)
        check_eq(f"U9 (i) {n} missing paths: 'and 1 more' only beyond 8", "and 1 more" in line, n == 9)
    check_in("U9 (j) the same missing path twice: counted once", "1 file(s) the context bundle names", with_bundle({}, paths("src/a.ts", "src/a.ts"))["_text"])
    check_eq("U9 (k) a register with no `current-code:` place, no bundle, no diff: exactly 'no code' (`is absent` is for a register with places)",
             with_bundle({}, None, register=["diff:b.ts:1"])["_text"], NO_CODE)
    check_eq("U9 (l) a bundle file whose language has no pattern: named, never 'no code'",
             with_bundle({"Foo.kt": ["x"]}, paths("Foo.kt"))["_text"], ["User-path failures: not measured: no pattern for .kt"])


def u10_negative_control_and_repeat() -> None:
    disk = {"src/a.ts": ["} catch (e) {", "  console.error(e);", "}"], "src/b.ts": fixture("handled.ts")}
    got = with_bundle(disk, paths("src/a.ts", "src/b.ts"))
    check_eq("U10 two files of the bundle: one match", tuples(got), [("swallowed_catch", "src/a.ts", 1)])
    check_eq("U10 ... and both are 'checked' (looked at, so the empty one is not 'not looked')", got["checked"], ["src/a.ts", "src/b.ts"])
    got = with_bundle(disk, paths("src/a.ts", "src/b.ts"), register=["current-code:src/a.ts:1"])
    check_eq("U10 a repeat S2 (one file in the bundle and in a register place): the label once, the match once",
             (got["checked"], len(got["matches"])), (["src/a.ts", "src/b.ts"], 1))
    got = with_bundle(disk, None, register=["current-code:src/a.ts:1"])
    check_eq("U10 a register without a bundle: the place is read", [m["file"] for m in got["matches"]], ["src/a.ts"])
    check_in("U10 ... and the narrowing is named", "work/context-bundle.json is absent: only the register's places were read", got["_text"])


def u11_brief_line() -> None:
    root = harness.temp_project("qa-upf-")
    try:
        put(root, "src/LoginPage.tsx", fixture("swallowed.ts"))
        task = story(root, None, None, paths("src/LoginPage.tsx"))
        out = BP.user_path_failure_lines(task)
        check("U11 the S2 brief line carries the match", any(x.startswith(f"{UPF.PREFIX}swallowed_catch src/LoginPage.tsx:5 - ") for x in out), str(out))
        check_not_in("U11 ... and not 'no code'", "no code", out)
        listed = json.loads((task / LIST).read_text(encoding="utf-8"))
        check_eq("U11 the full list holds the match", tuples(listed), SWALLOWED)
    finally:
        harness.cleanup(root)


def u12_diff_keeps_its_scope() -> None:
    page = {"src/LoginPage.tsx": fixture("swallowed.ts")}
    got = with_bundle(page, paths("src/LoginPage.tsx"), files={"b.ts": ["ok();"]})
    check_eq("U12 (a) a diff AND a bundle: the bundle is not read", (got["matches"], "src/LoginPage.tsx" in got["checked"]), ([], False))
    check_in("U12 (a) ... the first-S2 line of 0.10.8 stays", "register does not exist yet", got["_text"])
    with patch.object(UPF, "_diff_files", side_effect=RuntimeError("boom")):
        got = with_bundle(page, paths("src/LoginPage.tsx"), files={"b.ts": ["ok();"]})
    check_eq("U12 (b) a diff that cannot be read: the bundle's file is read", tuples(got), SWALLOWED)
    check_in("U12 (b) ... and the defect of the diff is named", "the diff cannot be read (RuntimeError: boom), a defect of the factory", got["unmeasured"])



def world(bundle=None, app_files=None, git=False, prefix="qa-upf-w-"):
    """RN1-5: a project `proj/` whose config maps repo `App` to the sibling checkout `../app` (the repo lives OUTSIDE the project), the checkout
    holding `app_files` {relative path: fixture name or lines}, and a story QA-9 with `bundle` as its `context-bundle.json` (a dict, a raw
    string or None). Returns (base dir, project, task root); the caller cleans `base` up."""
    base = harness.temp_dir(prefix)
    proj = harness.mark_project(base / "proj")
    cfg = json.loads((proj / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    cfg["implementation_repos"] = [{"repo_id": "App", "local_path": "../app"}]
    (proj / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    for rel, body in (app_files or {}).items():
        target = base / "app" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(fixture(body) if isinstance(body, str) else body) + "\n", encoding="utf-8")
    if git:
        harness.subprocess.run(["git", "init", "-q"], cwd=str(base / "app"), check=True)
        harness.subprocess.run(["git", "add", "-A"], cwd=str(base / "app"), check=True)
    task = proj / "qa-factory" / "artifacts" / "QA-9"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "stages": {}, "gates": {}, "halts": []}), encoding="utf-8")
    if bundle is not None:
        (task / "work" / "context-bundle.json").write_text(bundle if isinstance(bundle, str) else json.dumps(bundle), encoding="utf-8")
    return base, proj, task


def facts_of(*paths, note=None) -> dict:
    return {"facts": [{"id": f"f{i}", "path": p, "line": 1, **({"note": note} if note else {})} for i, p in enumerate(paths, 1)],
            "source_revisions": [{"repo": "App"}]}


CART, CARTS, LOGIN = "App/src/pages/CartPage.tsx", "App/src/lib/cartService.ts", "App/src/pages/LoginPage.tsx"
APP = {"src/pages/CartPage.tsx": "CartPage.tsx", "src/lib/cartService.ts": "cartService.ts", "src/pages/LoginPage.tsx": "LoginPage.tsx"}


def run_find(bundle=None, app_files=None, git=False, register=None, diff=None):
    base, proj, task = world(bundle, app_files if app_files is not None else APP, git)
    try:
        if diff is not None:
            (task / "work" / "impl-diff.txt").write_text(diff_of(diff), encoding="utf-8")
        if register is not None:
            head = "## Register\n\n| R | requirement | source | derived_from | x | ac_ref | observable |\n|---|---|---|---|---|---|---|\n"
            (task / "work" / "requirements-register.md").write_text(
                head + "".join(f"| R-{i} | t | derived | bug:candidate-defect | | | {o} |\n" for i, o in enumerate(register, 1)), encoding="utf-8")
        return UPF.find(task, project_root=proj), task, proj
    finally:
        harness.cleanup(base)


def u13_layout() -> None:
    """3.1: a repo-prefixed place resolves through the config's checkout; an escaping one is named and not read."""
    # the cited line is 10, not the spec's 20: a place reaches `reach` (the widest window, 15) lines each way, so :20 starts at line 5 and misses the fetch at :4
    got, _, _ = run_find(register=[f"current-code:{CART}:10"], diff={"b.ts": ["ok();"]})
    check_eq("U13 layout: a register place `App/...` (the repo lives at `../app`) is read through the config, under its own spelling",
             [(m["file"], m["pattern"], m["line"]) for m in got["matches"] if m["file"] == CART],
             [(CART, "unchecked_response", 4), (CART, "unchecked_response", 8)])
    got, _, _ = run_find(register=["current-code:App/../x.ts:1"], diff={"b.ts": ["ok();"]})
    check("U13 layout: `App/../x.ts` is named as not canonical and never read",
          sum("not a canonical" in u or "cannot be parsed" in u for u in got["unmeasured"]) == 1 and "App/../x.ts" not in got["checked"], str(got))


def u13_notes() -> None:
    """F1: file names in fact notes (`called from LoginPage.tsx:8`) are looked up by `git ls-files` in the configured checkouts."""
    note = "the merge is called from LoginPage.tsx:8"
    got, _, _ = run_find(facts_of(CARTS, note=note), git=True)
    check_in("U13e a file named in a note is read through `git ls-files`", LOGIN, got["checked"])
    check("U13e ... and its discarded request is found", ("discarded_response", 8) in [(m["pattern"], m["line"]) for m in got["matches"]], str(got["matches"]))
    got, _, _ = run_find(facts_of(CART, note="see CartPage.tsx:62"), git=True)
    check_eq("U13e2 a note naming a file the fact path already holds adds nothing (resolved path equals the key; LoginPage joins as a neighbour, N1)",
             got["checked"], [CART, LOGIN])
    many = {f"src/d{i}/LoginPage.tsx": ["x()"] for i in range(UPF.NAME_MATCH_MAX - 1)}      # with src/pages/LoginPage.tsx: NAME_MATCH_MAX files
    got, _, _ = run_find(facts_of(CARTS, note=note), {**APP, **many}, git=True)
    check_eq(f"U13e {UPF.NAME_MATCH_MAX} files named LoginPage.tsx: all are checked (AT the limit)", sum(c.endswith("LoginPage.tsx") for c in got["checked"]),
             UPF.NAME_MATCH_MAX)
    many[f"src/d{UPF.NAME_MATCH_MAX}/LoginPage.tsx"] = ["x()"]
    got, _, _ = run_find(facts_of(CARTS, note=note), {**APP, **many}, git=True)
    check("U13e BEYOND the limit: none read, the count named", not any(c.endswith("LoginPage.tsx") for c in got["checked"])
          and any(f"matches {UPF.NAME_MATCH_MAX + 1} files of App: not read" in u for u in got["unmeasured"]), str(got))
    got, _, _ = run_find(facts_of(CARTS, note=note), git=False)
    check("U13e the checkout is no git repository: one reason, nothing read", any("App is not a git checkout" in u for u in got["unmeasured"])
          and LOGIN not in got["checked"], str(got["unmeasured"]))
    got, _, _ = run_find(facts_of(CARTS, note="and Ghost.tsx:3"), git=True)
    check("U13e a name no checkout holds is named", any("Ghost.tsx named in context-bundle.json is no file of a configured checkout" in u
                                                       for u in got["unmeasured"]), str(got["unmeasured"]))


def u13_no_code() -> None:
    got, _, _ = run_find(facts_of(CARTS, CART))
    check_eq("U13g a negative control: a file with no shape beside one with two: 2 matches, both files checked",
             ([(m["file"], m["line"]) for m in got["matches"]], got["checked"]), ([(CART, 4), (CART, 8)], [CARTS, CART]))
    got, _, _ = run_find(facts_of(CARTS))
    check_eq("U13h a bundle with only the file that has no shape: no match", got["matches"], [])
    check_in("U13h ... the brief says what was checked and never `no code`", f"no match, checked: {CARTS}", UPF.lines(got))
    check_not_in("U13h ... no `not measured: no code`", "no code", UPF.lines(got))
    got, _, _ = run_find(facts_of(CART), diff={"b.ts": ["ok();"]})
    check("U13i a story WITH a diff keeps its S2: the bundle's files are not read", CART not in got["checked"], str(got["checked"]))
    got, _, _ = run_find({"facts": []})
    check_eq("U13j an empty bundle and no diff: exactly `no code`", UPF.lines(got), ["User-path failures: not measured: no code"])
    base, proj, task = world(facts_of(CART), APP)
    try:
        out = BP.user_path_failure_lines(task)
        check_in("U13k the S2 brief of a no-diff story carries the bundle's file", f"User-path failures: unchecked_response {CART}:4", out)
        check_not_in("U13k ... and no `no code`", "no code", out)
    finally:
        harness.cleanup(base)
    # U8l (A-M1): a repeat S2 whose register cites the bundle's file far from the shapes: the bundle's whole-file scan is kept
    got, _, _ = run_find(facts_of(CART), register=[f"current-code:{CART}:40"])
    check_eq("U13l a register place on the bundle's file does not hide the bundle's whole-file scan",
             [(m["file"], m["pattern"], m["line"]) for m in got["matches"]], [(CART, "unchecked_response", 4), (CART, "unchecked_response", 8)])
    # U8m (A-m2): a configured repo with no checkout is named, not silent
    base, proj, task = world(facts_of(CARTS, note="called from LoginPage.tsx:8"), APP)
    try:
        cfg = json.loads((proj / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg["implementation_repos"] = [{"repo_id": "App", "local_path": "../app"}, {"repo_id": "Gone", "local_path": "../gone"}]
        (proj / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        got = UPF.find(task, project_root=proj)
        check("U13m a configured repo with no checkout is named", any("Gone has no readable checkout" in u for u in got["unmeasured"]), str(got["unmeasured"]))
    finally:
        harness.cleanup(base)


def u14_discarded_response() -> None:
    def kinds(lines):
        return sorted({m["pattern"] for m in hits({"a.ts": lines})["matches"]})
    got = hits({"src/LoginPage.tsx": fixture("LoginPage.tsx")})
    check("U14 the fixture: `await fetch('/api/cart/merge', ...)` whose answer is dropped is matched at its line",
          ("discarded_response", 8) in [(m["pattern"], m["line"]) for m in got["matches"]], str(got["matches"]))
    check_eq("U14 `const r = await fetch('/x')`: not a discarded response", kinds(["const r = await fetch('/x')"]), [])
    check_eq("U14 `await fetch('/x').then(r => r.ok)`: read", kinds(["await fetch('/x').then(r => r.ok)"]), [])
    check_eq("U14 `return fetch('/x')`: handed on", kinds(["return fetch('/x')"]), [])
    check_eq("U14 `// await fetch('/x')`: a comment", kinds(["// await fetch('/x')"]), [])


ADD = "App/src/pages/AddToCart.tsx"
ADD_APP = {**APP, "src/pages/AddToCart.tsx": "AddToCart.tsx"}


def neighbour_world(extra=None, git=True, diff=None):
    """The LOCAL-1 shape of N1: the bundle names only the page that ADDS to the cart and a service, never the cart page."""
    base, proj, task = world(facts_of(ADD, CARTS), {**ADD_APP, **(extra or {})}, git)
    if diff is not None:
        (task / "work" / "impl-diff.txt").write_text(diff_of(diff), encoding="utf-8")
    return base, proj, task


def u15_neighbours() -> None:
    """RN1-6 N2-1: the pages that read and change what the flow writes join the flow."""
    base, proj, task = neighbour_world()
    try:
        got = UPF.code_files(task, proj, True)
        check_eq("N1 the cart page and the login page (both call an address of the flow) join, via `neighbour`; the named files keep their via",
                 {k: v["via"] for k, v in got["files"].items()}, {ADD: "bundle", CARTS: "bundle", CART: "neighbour", LOGIN: "neighbour"})
        found = UPF.find(task, project_root=proj)
        check("N1 the failures include the cart page's two unchecked responses (lines 4 and 8)",
              [(m["pattern"], m["line"]) for m in found["matches"] if m["file"] == CART] == [("unchecked_response", 4), ("unchecked_response", 8)],
              str(found["matches"]))
        reqs = UPF.flow_requests(task, project_root=proj)
        keys = [UPF.request_key(r) for r in reqs["requests"]]
        check("N1 the requests include GET /api/cart, PUT and DELETE /api/cart/{itemId} (named placeholders)", all(
            k in keys for k in ("GET /api/cart", "PUT /api/cart/{itemId}", "DELETE /api/cart/{itemId}", "GET /api/books/{bookId}")), str(keys))
    finally:
        harness.cleanup(base)
    for pages, more in ((UPF.NEIGHBOURS_MAX - 2, False), (UPF.NEIGHBOURS_MAX - 1, True)):         # + the cart page and the login page
        base, proj, task = neighbour_world({f"src/pages/p{i}.tsx": ["fetch('/api/cart')"] for i in range(pages)})
        try:
            got = UPF.code_files(task, proj, True)
            reasons = [u for u in got["unmeasured"] if "more files call the flow's addresses" in u]
            check_eq(f"N2 {pages + 2} files call the flow's addresses: {min(pages + 2, UPF.NEIGHBOURS_MAX)} join (AT / BEYOND NEIGHBOURS_MAX)",
                     sum(v["via"] == "neighbour" for v in got["files"].values()), min(pages + 2, UPF.NEIGHBOURS_MAX))
            check_eq(f"N2 {pages + 2} files: the rest is named in {'ONE reason' if more else 'no reason'}", len(reasons), 1 if more else 0)
            if more:
                check_in("N2 ... the reason counts the rest and names the stems", "1 more files call the flow's addresses (/api/cart): not read", reasons[0])
        finally:
            harness.cleanup(base)
    base, proj, task = world(facts_of(ADD), {"src/pages/AddToCart.tsx": ["fetch('/api')"], "src/pages/CartPage.tsx": "CartPage.tsx"}, True)
    try:
        got = UPF.code_files(task, proj, True)
        check_eq("N4 a stem of one segment (`/api`) names everything: no neighbour, no reason", (sorted(got["files"]), got["unmeasured"]), ([ADD], []))
    finally:
        harness.cleanup(base)
    base, proj, task = neighbour_world(git=False)
    try:
        got = UPF.code_files(task, proj, True)
        check("N5 the checkout is no git repository: one reason, no neighbour", [u for u in got["unmeasured"] if "neighbours of the flow not looked for" in u]
              == ["App is not a git checkout: neighbours of the flow not looked for"] and CART not in got["files"], str(got["unmeasured"]))
    finally:
        harness.cleanup(base)
    base, proj, task = neighbour_world(diff={"b.ts": ["ok();"]})
    try:
        found = UPF.find(task, project_root=proj)
        check_eq("N6 a story WITH a diff: the failures' checked files are unchanged (no neighbour)", found["checked"], ["b.ts"])
        reqs = UPF.flow_requests(task, project_root=proj)
        check_in("N6 ... the requests still gain the neighbour", CART, reqs["checked"])
    finally:
        harness.cleanup(base)
    base, proj, task = neighbour_world()
    real = UPF._file_lines
    try:
        with patch.object(UPF, "_file_lines", side_effect=lambda t: None if Path(t).name == "CartPage.tsx" else real(t)):
            got = UPF.code_files(task, proj, True)
        check("N7 a neighbour page that cannot be read is named, never silently dropped", CART not in got["files"] and any(
            "cannot be read, not looked at for neighbours of the flow" in u and CART in u for u in got["unmeasured"]), str(got["unmeasured"]))
    finally:
        harness.cleanup(base)
    for cap, more in ((0, False), (1, True)):
        extra = {f"src/lib/x{i}.ts": ["x();"] for i in range(3)}
        base, proj, task = neighbour_world(extra)
        try:
            total = 4 + len(extra)          # AddToCart, CartPage, LoginPage, cartService + the extras
            with patch.object(UPF, "NEIGHBOUR_SCAN_MAX", total - cap):
                got = UPF.code_files(task, proj, True)
            reasons = [u for u in got["unmeasured"] if "not scanned for neighbours of the flow" in u]
            check_eq(f"N3 the scan cap: {'one file beyond' if more else 'exactly at'} the cap -> {'the count named' if more else 'no reason'}",
                     reasons, ["App: 1 files not scanned for neighbours of the flow"] if more else [])
        finally:
            harness.cleanup(base)


for step in (u1_fixtures, u2_inconvenient, u3_limit, u4_not_measured, u5_data_not_code, u6_wiring, u7_shapes_the_finding_names,
             u8_bundle_without_diff, u9_no_code_only_when_nothing_was_there, u10_negative_control_and_repeat, u11_brief_line,
             u12_diff_keeps_its_scope, u13_layout, u13_notes, u13_no_code, u14_discarded_response, u15_neighbours):
    step()
finish("user path failure patterns")
