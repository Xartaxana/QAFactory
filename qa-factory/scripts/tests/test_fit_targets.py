#!/usr/bin/env python3
"""TQ1-21 (t-696): the test an S3 `extend` / `param` / `reuse` builds on is a file of the project's working tree, and S4/S5 get its
path ready (spec docs/tasks/specs/t-696-tq1-21-extend-target-exists.md, section 2).
KEYS: K-BUNDLE (the one bundle parser), K-WORDS / K-SPLIT / K-NONE, K-EXISTS / K-ABSENT / K-FOLDER / K-OUTSIDE-* / K-WINSEP / K-NOBASE /
K-ADV / K-SYMLINK (`base_test_file`, error direction: never toward `exists`), K-CAND* (a candidate id resolves through the bundle),
K-REUSE-* (`reuse` links), K-PATCH (an `if_answered` patch is checked), K-DETECTOR-* (the S3 exit), K-BRIEF-* (`brief_pack.fit_target_lines`).
Mutations (spec section 4, M1-M12) are named at their keys; the builder does not run them (batch canon)."""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import branch_accounting as BA  # noqa: E402
import brief_pack  # noqa: E402
import planning_contract as PC  # noqa: E402

OUTER = harness.temp_dir("qa-fit-targets-")
PROJECT = harness.mark_project(OUTER / "proj")
(PROJECT / "tests" / "a").mkdir(parents=True)
(PROJECT / "tests" / "a" / "b.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
(PROJECT / "tests" / "my cart.spec.ts").write_text("// a test\n", encoding="utf-8")
(OUTER / "x.py").write_text("# outside the working tree\n", encoding="utf-8")      # exists, but is NOT a file of the base
(PROJECT / "tests" / "x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")


def base(target, cfg=None, project=PROJECT):
    return PC.base_test_file(project, cfg if cfg is not None else {}, target)


# --- K-WORDS / K-SPLIT / K-NONE ----------------------------------------------------------------------------------------------
check_eq("K-WORDS the fit words that name an existing test are the vocabulary's, those whose shapes hold no `new`",
         PC.fit_words_with_target(), ("extend", "param"))                       # M11: returning every key (with `new`) kills K-NONE
check_eq("K-SPLIT word and the REST (a target holds spaces)", PC.split_fit("extend tests/my cart.spec.ts::adds item"),
         ("extend", "tests/my cart.spec.ts::adds item"))
check_eq("K-SPLIT extra blanks around the word are not the target's", PC.split_fit("  param   tests/a/b.py  "), ("param", "tests/a/b.py"))
check_eq("K-SPLIT a bare word has an empty target", PC.split_fit("extend"), ("extend", ""))
check_eq("K-SPLIT blank / not a string / None", [PC.split_fit(v) for v in ("", "   ", 5, None, ["extend x"])], [("", "")] * 5)

# --- K-EXISTS / K-ABSENT / K-FOLDER / K-WINSEP -------------------------------------------------------------------------------
got = base("tests/a/b.py::test_it")
check("K-EXISTS a file of the tree exists, with its project-relative `/` path and selector",
      (got["state"], got["path"], got["file"], got["selector"]) == ("exists", "tests/a/b.py", "tests/a/b.py", "test_it"), str(got))
got = base("tests\\a\\b.py::test_it")
check_eq("K-WINSEP `\\` is read as `/` (the file asserted, so it kills on Windows too)", (got["file"], got["state"], got["path"]),
         ("tests/a/b.py", "exists", "tests/a/b.py"))                             # M4: dropping the replace kills here
check_eq("K-WINSEP a leading ./ is dropped", base("./tests/a/b.py")["file"], "tests/a/b.py")
got = base("tests/my cart.spec.ts::adds item")
check_eq("K-EXISTS a path with a space and a selector with a space", (got["state"], got["path"], got["selector"]),
         ("exists", "tests/my cart.spec.ts", "adds item"))
got = base("tests/ghost.py::t")
check("K-ABSENT no such file is `absent` (not `unknown`, not `exists`)", got["state"] == "absent" and got["path"] == "", str(got))
check_eq("K-EXISTS `tests/x.py::` is the file with an empty selector", (base("tests/x.py::")["state"], base("tests/x.py::")["selector"]), ("exists", ""))
for folder in ("tests", "tests/", "tests/a"):
    check_eq(f"K-FOLDER {folder!r} is a folder, never a test file", base(folder)["state"], "folder")   # M3: is_file -> exists kills here
check_eq("K-ABSENT prose in the cell is read as the file and is absent (a path, never prose read by a phrase list)",
         base("tests/x.py (adds 12)")["state"], "absent")
check_eq("K-CASE the casing the OS finds is the casing given back (the OS answers; the path is the resolved one)",
         base("TESTS/A/B.PY")["state"] in ("exists", "absent"), True)

# --- K-OUTSIDE-*: decided on the text, before any filesystem call -------------------------------------------------------------
touched = []
real_test_path = None
import probe_by_code as PB  # noqa: E402
real_test_path = PB._test_path
PB._test_path = lambda *a, **k: touched.append(a) or real_test_path(*a, **k)
try:
    for name, text in (("DOTDOT", "../x.py"), ("DOTDOT-MID", "tests/../../x.py"), ("DOTDOT-BACK", "tests\\..\\..\\x.py"),
                       ("ABS-POSIX", "/etc/passwd"), ("DRIVE", "C:\\x.py"), ("DRIVE-REL", "C:x.py"), ("UNC-BACK", "\\\\srv\\share\\x.py"),
                       ("UNC", "//srv/share/x.py"), ("HOME", "~/x.py")):
        got = base(text)
        check(f"K-OUTSIDE-{name} {text!r} is `outside` and the lookup was never called", got["state"] == "outside" and not touched, str(got))
        touched.clear()
finally:
    PB._test_path = real_test_path                                                # M2: removing the textual `..` check kills K-OUTSIDE-DOTDOT
check_eq("K-OUTSIDE-DOTDOT-RESOLVED a file that DOES exist beyond `..` never counts", base("../x.py")["state"], "outside")

# --- K-NOBASE ------------------------------------------------------------------------------------------------------------------
check_eq("K-NOBASE no project (None) is `unknown`, not `absent`", base("tests/x.py", project=None)["state"], "unknown")   # M5 kills here
check_eq("K-NOBASE a project folder that is not there is `unknown`", base("tests/x.py", project=OUTER / "nope")["state"], "unknown")
check_in("K-NOBASE says what is wrong", "working tree is not found", base("tests/x.py", project=None)["why"])
check_eq("K-NOBASE a textual refusal stays a refusal even with no base (never becomes `unknown`)", base("../x.py", project=None)["state"], "outside")

# --- K-ADV: adversarial inputs, each on the safe side --------------------------------------------------------------------------
check_eq("K-ADV a NUL in the name is `unnamed`", base("te\x00st.py")["state"], "unnamed")
check_eq("K-ADV a control character is `unnamed`", base("tests/\x07x.py")["state"], "unnamed")
check_eq("K-ADV `::t` names no file", base("::t")["state"], "unnamed")
check_eq("K-ADV an empty target names no file", base("")["state"], "unnamed")
check_eq("K-ADV a non-string target names no file", base(None)["state"], "unnamed")
check("K-ADV a 5000-character name is never `exists`", base("a" * 5000 + ".py")["state"] in ("absent", "unknown"), "")
got = base("tests/x.py/")
check("K-ADV `tests/x.py/` (a file with a slash) is never a `folder`, and `exists` only as the very file (POSIX: absent; Windows strips the slash)",
      got["state"] != "folder" and (got["state"] != "exists" or got["path"] == "tests/x.py"), str(got))

# --- K-SYMLINK ------------------------------------------------------------------------------------------------------------------
LINKS = PROJECT / "links"
LINKS.mkdir()
try:
    (LINKS / "out.py").symlink_to(OUTER / "x.py")
    (LINKS / "broken.py").symlink_to(OUTER / "nothing-here.py")
    (LINKS / "loop-a").symlink_to(LINKS / "loop-b")
    (LINKS / "loop-b").symlink_to(LINKS / "loop-a")
    (LINKS / "inside.py").symlink_to(PROJECT / "tests" / "x.py")
    linked = True
except (OSError, NotImplementedError):
    linked = False
    print("not checked: symlinks not permitted here (K-SYMLINK-* run on CI Linux)")
if linked:
    check_eq("K-SYMLINK-OUT a link inside the base to a file outside it is `outside`", base("links/out.py")["state"], "outside")  # M1 kills here
    check_eq("K-SYMLINK-BROKEN a broken link is `absent`, never `exists`", base("links/broken.py")["state"] in ("absent", "unknown"), True)
    check_eq("K-SYMLINK-LOOP a link loop is never `exists`", base("links/loop-a")["state"] in ("absent", "unknown"), True)
    got = base("links/inside.py")
    check_eq("K-SYMLINK-INSIDE a link to a file inside the base resolves to the real file", (got["state"], got["path"]), ("exists", "tests/x.py"))

# where the OS refuses a link, the same branch is driven by a lookup that answers with a file outside the tree (M1: `is_relative_to` dropped)
PB._test_path = lambda *a, **k: (OUTER / "x.py", PROJECT)
try:
    check_eq("K-SYMLINK-OUT-MOCK a lookup that resolves outside the tree is `outside`, never `exists`", base("tests/x.py")["state"], "outside")
finally:
    PB._test_path = real_test_path

# --- the story fixtures ----------------------------------------------------------------------------------------------------------
HEAD = "## Register\n\n| R | requirement | source | derived_from |\n|---|---|---|---|\n"


def row(rid="TS-1", disposition="skip", reqs=("R-9",), **extra) -> dict:
    return {"id": rid, "requirements": list(reqs), "disposition": disposition, "reason": "r", **extra}


def story(name, rows=None, register=HEAD + "| R-9 | a | s | d |\n", bundle=None, md_ids=("R-9",), project=PROJECT) -> Path:
    root = (project / "qa-factory" / "artifacts" / name) if project is not None else OUTER / "loose" / name
    (root / "work").mkdir(parents=True, exist_ok=True)
    (root / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
    if rows is not None:
        (root / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    if bundle is not None:
        (root / "work" / "context-bundle.json").write_text(bundle if isinstance(bundle, str) else json.dumps(bundle), encoding="utf-8")
    cells = "".join(f"| TS-{i + 1} | {r} | x | automate | y | z | w | v | u |\n" for i, r in enumerate(md_ids))
    (root / "test-plan.md").write_text("## Plan\n\n| TS | R | observable | disposition + reason | level | fit | a | b | c |\n"
                                       "|---|---|---|---|---|---|---|---|---|\n" + cells
                                       + "\n## Recommended regression\n\nNo regression: nothing outside this change.\n", encoding="utf-8")
    return root


def run(root):
    saved_story, saved_errors = PC.detector_story, PC.gate_plan_errors
    PC.detector_story = lambda *a, **k: root
    PC.gate_plan_errors = lambda *a, **k: []       # the plan's own checks are clean: the target check alone decides
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = PC.detector_main(root)
    finally:
        PC.detector_story, PC.gate_plan_errors = saved_story, saved_errors
    return code, out.getvalue()


import runtime_paths  # noqa: E402
check_eq("fixture: the story is inside the project (project_for_task finds it)",
         Path(runtime_paths.project_for_task(story("T0", [row()]))).resolve(), PROJECT.resolve())

# --- K-BUNDLE ---------------------------------------------------------------------------------------------------------------------
check_eq("K-BUNDLE no bundle: ([], '')", BA.bundle_candidate_records(story("B0", [row()])), ([], ""))
check_eq("K-BUNDLE a bundle without the key: ([], '')", BA.bundle_candidate_records(story("B1", [row()], bundle={"x": 1})), ([], ""))
records, why = BA.bundle_candidate_records(story("B2", [row()], bundle={"existing_test_candidates": [
    {"candidate_id": "CAND-1", "path": "tests/x.py"}, {"path": "no id"}, "text", {"candidate_id": "  "}, {"candidate_id": "CAND-2"}]}))
check_eq("K-BUNDLE only the objects with a non-empty id, in file order", ([c["candidate_id"] for c in records], why), (["CAND-1", "CAND-2"], ""))
check_eq("K-BUNDLE `_bundle_candidates` is a view of it (ids)", BA._bundle_candidates(story("B2", [row()])), (["CAND-1", "CAND-2"], ""))
got, why = BA.bundle_candidate_records(story("B3", [row()], bundle="{not json"))
check("K-BUNDLE an unreadable bundle is (None, why) with the words the gate prints today",
      got is None and why.startswith("context-bundle.json cannot be read ("), why)
got, why = BA.bundle_candidate_records(story("B4", [row()], bundle={"existing_test_candidates": "x"}))
check_eq("K-BUNDLE the key not a list", (got, why), (None, "context-bundle.json is not an object with a list `existing_test_candidates`"))
check_eq("K-BUNDLE `_bundle_candidates` keeps (None, why)", BA._bundle_candidates(story("B4", [row()]))[0], None)

# --- K-NONE / K-CAND* ---------------------------------------------------------------------------------------------------------------
T1 = story("T1", [row()], bundle={"existing_test_candidates": [
    {"candidate_id": "CAND-1", "repo": "app", "path": "tests/x.py", "selector": "test_x"},
    {"candidate_id": "CAND-2", "repo": "app", "path": ""},
    {"candidate_id": "CAND-3", "repo": "app", "path": "tests/ghost.py"},
    {"candidate_id": "CAND-4", "repo": "", "path": "../x.py"}]})
for name, value in (("`new`", row(fit="new")), ("no fit", row()), ("a non-automate row with an empty fit", row(fit="")),
                    ("a non-dict row", "x"), ("an unknown word", row(fit="reshape tests/x.py"))):
    check_eq(f"K-NONE {name}: nothing to check", PC.fit_target(T1, value), None)
got = PC.fit_target(T1, row(fit="extend CAND-1"))
check_eq("K-CAND a candidate id resolves through the bundle to its path", (got["state"], got["path"], got["selector"], got["via"]),
         ("exists", "tests/x.py", "test_x", "candidate"))                          # M10: the candidate lookup skipped kills here
check_eq("K-CAND-NOPATH a candidate with no path is `unnamed`", PC.fit_target(T1, row(fit="extend CAND-2"))["state"], "unnamed")
check_eq("K-CAND a candidate whose file is absent is `absent`", PC.fit_target(T1, row(fit="param CAND-3"))["state"], "absent")
check_eq("K-CAND a candidate path with `..` is `outside`", PC.fit_target(T1, row(fit="extend CAND-4"))["state"], "outside")
check_eq("K-CAND an id the bundle does not hold is read as a path (absent here)", PC.fit_target(T1, row(fit="extend CAND-9"))["state"], "absent")
# K-CAND-BUNDLE-UNREAD (t-751 B-1): a bundle nobody can read makes an id-shaped target `unknown` (the machine's fault, FR-46), never a REJECT
TU = story("TU", [row()], bundle="{bad")
got = PC.fit_target(TU, row(fit="extend CAND-1"))
check("K-CAND-BUNDLE-UNREAD `extend CAND-1` with an unreadable bundle is `unknown`, naming the bundle", got["state"] == "unknown"
      and "context-bundle.json cannot be read" in got["why"], str(got))                # mutation: that branch returns `absent` -> killed here
refused, warns, unread = PC.fit_target_findings(TU, [row(fit="extend CAND-1"), row("TS-2", coverage_obligations=[{"obligation_id": "O-1", "decision": "reuse",
                                                                                   "coverage_links": [{"candidate_id": "CAND-1"}]}])])
check("K-CAND-BUNDLE-UNREAD the findings: 0 refused, one WARN per use naming the bundle", refused == [] and len(warns) == 2
      and all("context-bundle.json cannot be read" in w for w in warns), str((refused, warns)))
check_eq("K-CAND-BUNDLE-UNREAD control: a path-shaped token stays `absent` with the bundle unreadable", PC.fit_target(TU, row(fit="extend tests/ghost.py"))["state"], "absent")
check_eq("K-CAND-BUNDLE-UNREAD control: an id a READABLE bundle does not hold stays `absent`", PC.fit_target(T1, row(fit="extend CAND-9"))["state"], "absent")
check_eq("K-NONE `extend` with no target is `unnamed`", PC.fit_target(T1, row(fit="extend"))["state"], "unnamed")
check_eq("K-NONE `extend ::t` is `unnamed`", PC.fit_target(T1, row(fit="extend ::t"))["state"], "unnamed")
# the checkout of the candidate's repository, named by the project's config
(PROJECT / "app-checkout" / "tests").mkdir(parents=True)
(PROJECT / "app-checkout" / "tests" / "c.py").write_text("def test_c():\n    pass\n", encoding="utf-8")
cfg = {"implementation_repos": [{"repo_id": "app", "local_path": "app-checkout"}, {"repo_id": "far", "local_path": str(OUTER)}]}
cands = [{"candidate_id": "CAND-7", "repo": "app", "path": "tests/c.py", "selector": "test_c"},
         {"candidate_id": "CAND-8", "repo": "far", "path": "x.py"}, {"candidate_id": "CAND-9", "repo": "app", "path": "tests/x.py"}]
got = PC.fit_target(T1, row(fit="extend CAND-7"), cfg=cfg, candidates=cands)
check_eq("K-CAND-CHECKOUT the configured checkout of the repository is the one try", (got["state"], got["path"]), ("exists", "app-checkout/tests/c.py"))
got = PC.fit_target(T1, row(fit="extend CAND-8"), cfg=cfg, candidates=cands)
check("K-CAND-CHECKOUT a checkout outside the working tree is `outside`", got["state"] == "outside" and "checkout of far" in got["why"], str(got))
check_eq("K-CAND-CHECKOUT only ONE try: the checkout is not first-of-many (tests/x.py is in the project, not in the checkout)",
         PC.fit_target(T1, row(fit="extend CAND-9"), cfg=cfg, candidates=cands)["state"], "absent")

# --- K-REUSE-* / K-PATCH: the findings ----------------------------------------------------------------------------------------------
reuse_row = row(fit="", coverage_obligations=[{"obligation_id": "O-1", "decision": "reuse", "coverage_links": [
    {"test_ref": "tests/ghost.py::t"}, {"candidate_id": "CAND-1"}, {"test_ref": "CartTest#adds"}, {"test_ref": "tests/a/b.py::test_it"}]},
    {"obligation_id": "O-2", "decision": "new", "coverage_links": [{"test_ref": "tests/nothing.py"}]}])
refused, warns, unread = PC.fit_target_findings(T1, [reuse_row])
check_eq("K-REUSE-ABSENT exactly one refusal: the absent `test_ref` path (a candidate that exists, a path that exists, a `new` obligation and a "
         "framework id are not)", [(f["where"], f["state"]) for f in refused], [("TS-1 O-1 coverage_links[0]", "absent")])   # M9 kills here
check_in("K-REUSE-ABSENT the reuse door reads `test_ref` or `candidate_id` or plan extend/new", "or plan the obligation `extend`/`new`", refused[0]["line"])
check_eq("K-REUSE-ID a framework id is not refused: ONE aggregate WARN", warns, [
    "1 reuse link(s) name a test by a framework id, not a file (TS-1 O-1 coverage_links[2]): not checked at S3; S5 joins them to the discovery inventory."])
check_eq("K-REUSE-ID the check ran", unread, "")
refused, warns, unread = PC.fit_target_findings(T1, [row(fit="extend tests/ghost.py::t",
                                                      if_answered={"Q1": {"a": {"fit": "extend tests/ghost2.py::t"}},
                                                                   "Q2": {"a": {"reason": "no fit here"}},
                                                                   "Q3": {"a": {"fit": "extend tests/a/b.py"}}})])
check_eq("K-PATCH the row as written AND each patch that sets a bad `fit` (a good one and a patch with no fit are not findings)",
         [f["where"] for f in refused], ["TS-1", "TS-1 if_answered[Q1][a]"])        # M12: patches not walked kills here
two_patches = {"Q1": {"a": {"fit": "extend tests/ghost.py"}}}
refused, _w, _u = PC.fit_target_findings(T1, [row(fit="extend tests/x.py", if_answered=two_patches), row("TS-2", fit="extend tests/x.py", if_answered=two_patches)])
check_eq("K-PATCH-TWO-ROWS two rows with the same question and the same bad patch: two findings, each with its own `where`",
         [f["where"] for f in refused], ["TS-1 if_answered[Q1][a]", "TS-2 if_answered[Q1][a]"])   # mutation: `rid` out of the mark kills here
refused, _w, _u = PC.fit_target_findings(T1, [row(fit="extend tests/x.py", if_answered={"Q1": {"a": {"fit": "extend tests/ghost.py"}, "b": {"fit": "extend tests/ghost.py"}}})])
check_eq("K-PATCH-TWO-ROWS control: two answer keys of ONE row's entry with the same patched fit stay one finding", len(refused), 1)
# m-2: a `test_ref` is a path by a separator or by a `code_extensions` suffix (data), not by a regex in code
refused, warns, _u = PC.fit_target_findings(T1, [row(fit="", coverage_obligations=[{"obligation_id": "O-1", "decision": "reuse", "coverage_links": [
    {"test_ref": "com.acme.cart"}, {"test_ref": "CartTest#adds"}, {"test_ref": "ghost.py"}]}])])
check_eq("K-REUSE-EXT `com.acme.cart` is a framework id (not refused); a bare `ghost.py` (a code_extensions suffix) is a path -> refused",
         ([f["where"] for f in refused], len(warns)), (["TS-1 O-1 coverage_links[2]"], 1))
check_in("K-REUSE-EXT the aggregate WARN names the framework id link", "TS-1 O-1 coverage_links[0]", warns[0])
check_eq("K-FINDINGS rows that are not a list: nothing, and no raise", PC.fit_target_findings(T1, "x"), ([], [], ""))
check_eq("K-FINDINGS no target-bearing row: nothing", PC.fit_target_findings(T1, [row(), row("TS-2", fit="new")]), ([], [], ""))
refused, warns, unread = PC.fit_target_findings(T1, [row(fit="extend tests/ghost.py::t"), row("TS-2", fit="extend tests/ghost.py::t")])
check_eq("K-FINDINGS two rows naming one missing test: two findings, one lookup per token", len(refused), 2)
check("K-FINDINGS the line is ONE physical line with the path, the doors and `fit_absent`",
      "\n" not in refused[0]["line"] and "no file at tests/ghost.py under the project root or the run folder of its profile" in refused[0]["line"]
      and "`fit: new` with `fit_absent: \"tests/ghost.py::t\"`" in refused[0]["line"] and "candidate id of work/context-bundle.json" in refused[0]["line"],
      refused[0]["line"])
refused, warns, unread = PC.fit_target_findings(story("T2", [row()], project=None), [row(fit="extend tests/x.py")])
check("K-NOBASE the findings: no working tree found is ONE WARN, never a refusal", refused == [] and len(warns) == 1 and "could not be checked" in warns[0]
      and "S4 writes its case as new and S5 checks the test again." in warns[0], str((refused, warns)))
saved = PC.fit_words_with_target
PC.fit_words_with_target = lambda: (_ for _ in ()).throw(ValueError("vocabulary gone"))
refused, warns, unread = PC.fit_target_findings(T1, [row(fit="extend tests/x.py")])
PC.fit_words_with_target = saved
check_eq("K-FINDINGS a check that raises is `why_unread`, never a pass", (refused, warns, unread),
         ([], [], "plan targets could not be checked (ValueError: vocabulary gone)"))

# --- K-DETECTOR-* -------------------------------------------------------------------------------------------------------------------
code, text = run(story("D1", [row(fit="extend tests/ghost.py::t")]))
check("K-DETECTOR-ABSENT REJECT, exit 1, the line names the path and both doors", code == 1 and "REJECT — 1 plan target(s) name a test the "
      "project's working tree does not have; S4 would search for it:" in text and "no file at tests/ghost.py" in text
      and "`fit: new` with `fit_absent:" in text and "candidate id of work/context-bundle.json" in text, f"{code}\n{text}")   # M6 kills here
check_in("K-DETECTOR-ABSENT the summary tail counts it at its END", "1 plan target problem(s)", text.splitlines()[-2])
check_in("K-DETECTOR-ABSENT the waiver covers the block", "waiver.py --task <TICKET> --stage S3", text)
code, text = run(story("D1b", [row(fit="new", fit_absent="tests/ghost.py::t")]))
check("K-DETECTOR-DOOR the door the refusal names (`fit: new` + `fit_absent`) passes the S3 exit: exit 0, no target line", code == 0
      and "plan target" not in text and "REJECT" not in text, f"{code}\n{text}")
code, text = run(story("D2", [row(fit="extend tests/a/b.py::test_it")]))
check("K-DETECTOR-PRESENT a test that exists: no target line, exit 0, OK", code == 0 and "plan target" not in text and "OK:" in text, f"{code}\n{text}")
code, text = run(story("D3", [row(fit="extend tests/x.py")], project=None))
check("K-DETECTOR-UNKNOWN no working tree: a WARN, no REJECT from targets, the old OK path", code == 0 and
      "WARN TS-1: `extend tests/x.py` could not be checked" in text and "REJECT" not in text, f"{code}\n{text}")
PC.fit_words_with_target = lambda: (_ for _ in ()).throw(ValueError("vocabulary gone"))
code, text = run(story("D4", [row(fit="extend tests/x.py")]))
check("K-DETECTOR-UNREAD a raising check alone: UNREADABLE, exit 3, no OK", code == 3 and "UNREADABLE:" in text and "OK:" not in text, f"{code}\n{text}")
code, text = run(story("D5", [row(reqs=("R-1",), fit="extend tests/x.py")], register=HEAD + "| R-9 | a | s | d |\n| R-1 | b | s | d |\n| R-8 | c | s | d |\n"))
check("K-DETECTOR-UNREAD beside another REJECT: no UNREADABLE line (the exit gate would hide the refusals)", code == 1 and "REJECT" in text
      and "UNREADABLE" not in text, f"{code}\n{text}")
PC.fit_words_with_target = saved
check_eq("K-DETECTOR-UNREAD the real words are back", PC.fit_words_with_target(), ("extend", "param"))

# --- K-BRIEF-* -----------------------------------------------------------------------------------------------------------------------
def plan_rows(*rows) -> Path:
    name = f"BR{len(list(PROJECT.glob('qa-factory/artifacts/BR*')))}"
    return story(name, list(rows))


HEADER = brief_pack.FIT_HEAD
check_eq("constants", (brief_pack.FIT_LINES_MAX, brief_pack.FIT_ABSENT_CHARS), (8, 160))
task = plan_rows(row(fit="extend tests\\a\\b.py::test_it", disposition="automate"), row("TS-2", fit="extend tests/ghost.py::t", disposition="automate"),
                 row("TS-3", fit="new", disposition="automate"))
lines, side = brief_pack.fit_target_lines("T", task, "S4", "qa-case-designer", {}, [], "S4-1")
check_eq("K-BRIEF-EXISTS the header, then a `/` path for an existing target (no `search` in the row line)", lines[:2],
         [HEADER, "- TS-1: extend tests/a/b.py::test_it (in the working tree)"])
check_not_in("K-BRIEF-EXISTS the row line does not say search", "search", lines[1])
check("K-BRIEF-ABSENT an absent target is NOT a bare `extend`: it is written as new, support layer in scope",
      lines[2] == "- TS-2: extend tests/ghost.py::t - NOT in the working tree (no file at tests/ghost.py): write the case as new; "
                  "the page objects and helpers it needs are part of it", lines[2])                          # M7 kills here
check_eq("K-BRIEF a `new` row with no `fit_absent` has no line; one line per target row; no side file", (len(lines), side), (3, ""))
lines5, _ = brief_pack.fit_target_lines("T", task, "S5", "qa-automator", {}, ["TS-2"], "S5-1")
check("K-BRIEF-EXISTS S5 takes the rows of the scope only, and says `test`, not `case`", len(lines5) == 2 and lines5[1].startswith("- TS-2:")
      and "write the test as new" in lines5[1], str(lines5))
check_eq("K-BRIEF-EXISTS S5 with no scope rows: nothing", brief_pack.fit_target_lines("T", task, "S5", "qa-automator", {}, [], "S5-1"), ([], ""))
lines4, _ = brief_pack.fit_target_lines("T", task, "S4", "qa-case-critic", {"plan_rows": ["TS-1"]}, [], "S4-2")
check_eq("K-BRIEF a rework's `plan_rows` narrow the S4 lines (the case critic is given them too)", len(lines4), 2)
lines, _ = brief_pack.fit_target_lines("T", plan_rows(row(fit="extend", disposition="automate")), "S4", "qa-case-designer", {}, [], "S4-1")
check("K-BRIEF-ABSENT an `unnamed` target (`extend` and no test) is not handed as a path either", len(lines) == 2 and "NOT in the working tree (it names no test file)" in lines[1], str(lines))
task_loose = story("L1", [row(fit="extend tests/x.py", disposition="automate")], project=None)
lines, _ = brief_pack.fit_target_lines("T", task_loose, "S4", "qa-case-designer", {}, [], "S4-1")
check("K-BRIEF-UNKNOWN no working tree: `not verified`, write as new", len(lines) == 2 and "not verified (the project's working tree is not found)" in lines[1]
      and "write the case as new" in lines[1] and "NOT in" not in lines[1], str(lines))
long_text = "tests/old-name.spec.ts " + "word " * 80
task = plan_rows(row(fit="new", disposition="automate", fit_absent=long_text), row("TS-2", fit="new", disposition="skip", fit_absent="x"),
                 row("TS-3", fit="extend tests/x.py", disposition="automate", fit_absent="ignored"), row("TS-4", fit="new", disposition="automate", fit_absent="  "))
lines, _ = brief_pack.fit_target_lines("T", task, "S4", "qa-case-designer", {}, [], "S4-1")
check("K-BRIEF-FITABSENT clipped at 160 with `...`, path-free; ignored on a non-automate row, on a row with a target, and when empty",
      len(lines) == 3 and lines[1].startswith("- TS-1: new - S3: the test it was to build on is not in the working tree (\"tests/old-name.spec.ts")
      and "...\"): the page objects and helpers it needs are part of this case" in lines[1]
      and len(lines[1].split("(\"", 1)[1].split("\"):")[0]) == brief_pack.FIT_ABSENT_CHARS and lines[2].startswith("- TS-3: extend tests/x.py"), str(lines))
huge = "tests/" + "g" * 5000 + ".py"
lines, _ = brief_pack.fit_target_lines("T", plan_rows(row(fit=f"extend {huge}", disposition="automate")), "S4", "qa-case-designer", {}, [], "S4-1")
check("K-BRIEF-CLIP a 5000-character target is clipped in the line (twice at most: the target and the file), never whole",
      len(lines) == 2 and len(lines[1]) < 3 * brief_pack.FIT_ABSENT_CHARS + 200 and huge not in lines[1], str(len(lines[1])))
task = plan_rows(*[row(f"TS-{n}", fit="extend tests/x.py", disposition="automate") for n in range(1, 9)])
lines, side = brief_pack.fit_target_lines("T", task, "S4", "qa-case-designer", {}, [], "S4-1")
check_eq("K-BRIEF-CAP-8 eight rows: eight lines, no more-line, no side file", (len(lines), side), (9, ""))             # M8: `>` -> `>=` kills here
task = plan_rows(*[row(f"TS-{n}", fit="extend tests/x.py", disposition="automate") for n in range(1, 10)])
lines, side = brief_pack.fit_target_lines("T", task, "S4", "qa-case-designer", {}, [], "S4-1")
check("K-BRIEF-CAP-9 nine rows: eight lines and ONE more-line naming the rest and the side file; the side holds all nine",
      len(lines) == 10 and lines[-1] == "- and 1 more: TS-9 - qa-factory/artifacts/T/work/briefs/S4-1-targets.md"
      and side.count("(in the working tree)") == 9 and side.startswith(HEADER), f"{lines[-1]!r} {side.count('(in the working tree)')}")
for stage, role in (("S2", "qa-requirements-tester"), ("S4", "qa-scout"), ("S3", "qa-test-strategist"), ("S5", "qa-code-critic"), ("S6", "qa-automator")):
    check_eq(f"K-BRIEF-OTHER-ROLE {stage}/{role}: nothing", brief_pack.fit_target_lines("T", task, stage, role, {}, ["TS-1"], "D-1"), ([], ""))
empty = story("N1", None)
check_eq("K-BRIEF-NOPLAN no plan file: nothing (a stage without a plan says nothing it cannot know)",
         brief_pack.fit_target_lines("T", empty, "S4", "qa-case-designer", {}, [], "S4-1"), ([], ""))
(empty / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
lines, side = brief_pack.fit_target_lines("T", empty, "S4", "qa-case-designer", {}, [], "S4-1")
check("K-BRIEF-BADPLAN an unreadable plan: ONE `not read` line that says do not search", len(lines) == 1 and side == "" and "not read" in lines[0]
      and "do not search for them - ask the conductor" in lines[0], str(lines))
(empty / "work" / "test-plan.json").write_text('{"rows": "x"}', encoding="utf-8")
check("K-BRIEF-BADPLAN rows that are no list: the same line", len(brief_pack.fit_target_lines("T", empty, "S4", "qa-case-designer", {}, [], "S4-1")[0]) == 1, "")
late = plan_rows(row(fit="extend tests/late.py::t", disposition="automate"))
check_in("K-BRIEF the target is read at brief time (TEMPORAL): absent now ...", "NOT in the working tree",
         brief_pack.fit_target_lines("T", late, "S4", "qa-case-designer", {}, [], "S4-1")[0][1])
(PROJECT / "tests" / "late.py").write_text("def t():\n    pass\n", encoding="utf-8")
check_in("K-BRIEF the target is read at brief time (TEMPORAL): ... and in the tree once it is there", "- TS-1: extend tests/late.py::t (in the working tree)",
         brief_pack.fit_target_lines("T", late, "S4", "qa-case-designer", {}, [], "S4-1")[0][1])

# --- K-BRIEF-BUILD: through `brief_pack.build`, head and side file --------------------------------------------------------------------
import test_brief_pack as TBP  # noqa: E402  (its `seed` builds a story the S4 brief can be built for)
BUILD = harness.temp_project("qa-fit-build-")
try:
    harness.use_project(BUILD)
    (BUILD / "tests" / "x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    task_root = TBP.seed(BUILD, "QA-9")
    (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": [
        row(f"TS-{n}", fit="extend tests/x.py", disposition="automate") for n in range(1, 10)]}), encoding="utf-8")
    (task_root / "state").mkdir(exist_ok=True)
    (task_root / "state" / "controller.json").write_text(json.dumps({"scope": [], "revision": 1, "dispatches": {
        "S4-qa-case-designer-1": {"id": "S4-qa-case-designer-1", "stage": "S4", "role": "qa-case-designer", "status": "running", "scope": []}}}),
        encoding="utf-8")
    built = brief_pack.build("QA-9", "S4", "qa-case-designer", "S4-qa-case-designer-1", write=True)
    md = built["markdown"]
    check("K-BRIEF-BUILD the S4 brief head carries the header, eight rows and the more-line", md.count("(in the working tree)") == 8
          and "- and 1 more: TS-9 - qa-factory/artifacts/QA-9/work/briefs/S4-qa-case-designer-1-targets.md" in md, md[:1500])
    side_file = task_root / "work" / "briefs" / "S4-qa-case-designer-1-targets.md"
    check("K-BRIEF-BUILD the side file is written and holds all nine", side_file.is_file() and side_file.read_text(encoding="utf-8").count("TS-") == 9, "")
    built = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)
    check_not_in("K-BRIEF-BUILD another stage's brief has no such header", HEADER, built["markdown"])
finally:
    harness.cleanup(BUILD)

harness.cleanup(OUTER)
finish("test_fit_targets")
