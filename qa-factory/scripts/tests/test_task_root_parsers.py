#!/usr/bin/env python3
"""Every CLI with `--task-root` reads its flags EXACTLY and refuses a phantom story at once (CX1-18, half B).

On a Codex run `controller.py --task TP2-2406` was read by argparse as the abbreviation of `--task-root`, and
the same hole stood in 34 more scripts: `--task-r X` became a root, a root that names no story was answered with a
green "OK ... 0 case(s)", `{"verified": true}`, `"older": true`, or a folder made on the spot. The class is closed by
`hooklib.exact_options` (no abbreviations, subparsers too) and `hooklib.story_cli` / `story_of` (the story first, right
after parsing, before an input is read or a byte is written). This file pins the CLASS, not the 31 scripts one by
one: an AST census of every script that declares `--task-root` (the detector; a new script that does not call the
helpers is red), and one battery over a table of the 31 scripts of half B plus the three that half A-rest converts
(`handoff_init`, `stand_gaps`, `sizing`): the abbreviation refused, the phantom root refused with the driver's text and
exit 2 and nothing written, a real root past the gate. The rows of the three A-rest scripts are marked
"converted by A-rest": they are written against the state AFTER that half and are red on a tree without it.

Positions the table cannot see are pinned apart: `render_case_appendix` makes its `--output` folder only after the
story is known, `artifact_packet` reads its `--input` only after, `report_facts` / `traceability` exit 2 (they said 1),
a judge with the feature off still refuses a phantom (E-4), a guarded script refuses on its own channel (E-5).
"""
import ast
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project)

PHANTOM = "TP3-404"
CYRILLIC_E = chr(0x415)          # looks like the Latin E of TP3-1
B_SCRIPTS = ("artifact_packet artifact_producer artifact_supersede branch_accounting case_stamp case_versions delivery_manifest "
             "delivery_summary exploratory_findings grounding_section handoff_check investigation investigation_probe judge_cases judge_code judge_diff judge_plan judge_requirements "
             "judge_results judge_run manual_capture manual_evidence migrate_artifacts plan_row red_sandbox "
             "regression_scope render_case_appendix report_facts runtime_paths runtime_probe s5_precheck s7_reorder stage_status story_progress "
             "story_version ticket_adapter tms_publication traceability").split() + ["bug_records", "product_gaps"] + ["walk_session", "walk_timing", "place_answers", "driver_timing", "bug_neighbours"]   # bug_neighbours: t-2187 N6; t-1782 (leftover of t-1781); the walker (t-1957): exact flags + story_of / story_cli
A_REST = "handoff_init stand_gaps gate_preflight sizing".split()         # converted by A-rest, not by this half
UNCONVERTED = ["person_owned", "app_card", "interim_packet", "reference_snapshot", "first_look"]
# interim_packet (t-2181 PC-7), reference_snapshot (PC-9a) and first_look (t-2277 FL-2) arrived on plain argparse, no exact_options / story gate; named so the census
# sees them, the conversion is queued (a finding of the t-2470 CI triage, row 16).
# person_owned: RN1-9 A (t-744): a read-only `--share --task-root` on plain argparse; NOT yet exact_options/story_of
# (a phantom root is not refused). Named so the census sees it; the conversion is queued (t-774 report).
# app_card: the walker N1 card builder (`build --task-root`) is plain argparse as well, no exact_options / story gate yet; named so the census sees it (queued).
# bug_records (open-bugs) and product_gaps (record/revoke) arrived on plain argparse the same way and were converted by t-1782
# (they sit in B_SCRIPTS now: exact flags, the story resolved by story_cli, exit 2).
KEPT = {"controller": "allow_abbrev=False"}                # CX1-10: a literal in its own parser, `--task` is exclusive there
HELPERS = ("story_cli", "story_of", "story_root_at")


# --- the census (the detector of the class) ------------------------------------------------------------------

def census(source: str, name: str) -> list:
    """What is wrong with the way `source` reads `--task-root`; [] when it is as the class demands."""
    tree = ast.parse(source)
    problems = []
    imported = {a.asname or a.name: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "hooklib"
                for a in n.names}          # `from hooklib import exact_options` (a bare name counts ONLY when hooklib gave it)

    def hooklib_name(call) -> str:
        """The hooklib function a call reaches: `x.name(...)` (hooklib.name, an alias of the module) or a bare `name(...)`
        that a `from hooklib import name` brought in; "" for any other call - a local function of the same name is not it."""
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return imported.get(call.func.id, "") if isinstance(call.func, ast.Name) else ""

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    called = {hooklib_name(n) for n in calls}
    exact = [n for n in calls if hooklib_name(n) == "exact_options"]
    if not exact:
        problems.append("no hooklib.exact_options( call: the flags are still read by abbreviation")
    if not called & set(HELPERS):
        problems.append("no story_cli / story_of / story_root_at call: a phantom root is not refused")
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module))]
    for call in exact:      # E-11: nothing is added to a parser after the call that fixes its flags
        owner = min((s for s in scopes if any(c is call for c in ast.walk(s))),
                    key=lambda s: len(list(ast.walk(s))))
        for late in ast.walk(owner):
            if (isinstance(late, ast.Call) and isinstance(late.func, ast.Attribute)
                    and late.func.attr in ("add_argument", "add_parser") and late.lineno > call.lineno):
                problems.append(f"{late.func.attr} after exact_options (line {late.lineno}): that flag keeps abbreviations")
    imports_guard = "run_guarded" in source
    uses_cli = "story_cli" in called
    if imports_guard and uses_cli:
        problems.append("story_cli in a module that runs under run_guarded: use story_of and the script's own refuse (E-5)")
    return problems


def read_script(module: str) -> str:
    return (SCRIPTS / f"{module}.py").read_text(encoding="utf-8")


def _declares_or_fixes_flags(text: str) -> bool:
    """The SHAPE of a delegate that matters to the census: its text declares `--task-root`, calls `exact_options(`, or calls a
    story-gate helper (`story_cli(`, `story_of(`, `story_root_at(`)."""
    return ('add_argument("--task-root"' in text or "add_argument('--task-root'" in text or "exact_options(" in text
            or any(f"{helper}(" in text for helper in HELPERS))


_FLAG_FUNCTIONS = {}      # module text -> {function name: its source} for the module-level functions that pass _declares_or_fixes_flags


def _flag_functions(text: str) -> dict:
    """The module-level functions of `text` whose own text declares `--task-root` or calls `exact_options(` (parsed once per text)."""
    if text not in _FLAG_FUNCTIONS:
        found = {}
        rows = text.splitlines()      # sliced by line numbers: get_source_segment re-splits the whole module on every call
        for n in ast.parse(text).body:
            if isinstance(n, ast.FunctionDef):
                start = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                segment = "\n".join(rows[start:n.end_lineno])
                if segment and _declares_or_fixes_flags(segment):
                    found[n.name] = segment
        _FLAG_FUNCTIONS[text] = found
    return _FLAG_FUNCTIONS[text]


def effective_source(source: str, read=read_script) -> str:
    """G8 -> X9: a script may hand its flags or its whole command line to a shared function (AR-15): the three judge scripts call
    `judge_requirements.cli_main` (`from judge_requirements import cli_main`), `report_facts` calls `traceability.add_story_options`
    (`import traceability as T`). The census must see the flags and the story gate THROUGH the delegate (one reader of the question,
    AR-13), so the text of each delegate that the script CALLS is appended to the script's own text.

    The class of a delegate (read by SHAPE, not by a name list): a called MODULE-LEVEL function of a module of the scripts folder
    (`from m import f; f(...)` or `import m; m.f(...)`) whose own text holds `add_argument("--task-root"`, `exact_options(` or a call of a story-gate
    helper (`story_cli(`, `story_of(`, `story_root_at(`: the gate is read through the delegate too). Every
    such delegate is followed, so a script that calls two of them gets both. NOT followed, and the census then goes red for the
    missing calls: a method (`obj.f(...)`, a function nested in a class), a function of a module outside the scripts folder (stdlib,
    `read` finds nothing), a name imported and never called, a called function without the flag or `exact_options(` in its text.
    ONE level only: a delegate that itself delegates to a third function is not followed through (name its home in the script, or
    make the delegate declare the flags). `read(module)` returns the text of a module of the scripts folder (a parameter, so a
    control can feed a doctored delegate)."""
    tree = ast.parse(source)
    modules = {a.asname or a.name: a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}      # alias -> module
    names = {a.asname or a.name: (n.module, a.name) for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module and n.module != "hooklib" for a in n.names}                  # bare name -> (module, name)
    wanted = set()
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        if isinstance(call.func, ast.Name) and call.func.id in names:
            wanted.add(names[call.func.id])
        elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in modules \
                and modules[call.func.value.id] != "hooklib":      # hooklib holds the REQUIRED helpers, it is never a delegate
            wanted.add((modules[call.func.value.id], call.func.attr))
    out = source
    for module, func in sorted(wanted):
        try:
            segment = _flag_functions(read(module)).get(func)
            if segment:
                out += "\n\n" + segment
        except (OSError, SyntaxError, ValueError):
            pass
    return out


def declares_task_root(source: str, read=read_script) -> bool:
    full = effective_source(source, read)
    return 'add_argument("--task-root"' in full or "add_argument('--task-root'" in full


def census_battery() -> None:
    declared = sorted(p.stem for p in SCRIPTS.glob("*.py") if declares_task_root(p.read_text(encoding="utf-8")))
    expected = sorted(B_SCRIPTS + A_REST + UNCONVERTED + list(KEPT))
    check_eq("the census sees every script that declares --task-root, and the lists name exactly them (a new one is red)",
             declared, expected)
    for name in B_SCRIPTS:
        found = census(effective_source(read_script(name)), name)
        check(f"census {name}: exact flags, the story resolved, one refusal channel", not found, "; ".join(found))
    for name in A_REST:      # converted by A-rest: red until that half is merged
        found = census(effective_source(read_script(name)), name)
        check(f"census {name} [converted by A-rest]", not found, "; ".join(found))
    # the delegation (G8): judge_cases / judge_plan declare nothing themselves and are seen through `judge_requirements.cli_main`
    for name in ("judge_cases", "judge_plan", "report_facts"):      # report_facts: the options come from traceability.add_story_options
        own = read_script(name)
        seen = effective_source(own)
        check(f"delegation: {name} has no flags of its own and the census follows its delegate (cli_main / add_story_options)",
              not declares_task_root(own, read=lambda m: "") and declares_task_root(own)
              and ("def cli_main" in seen or "def add_story_options" in seen))
    # negative controls of the delegation: the census can fail through a delegate, and a new script that declares the flag is in no list
    deleg = read_script("judge_cases")
    doctored = read_script("judge_requirements").replace("hooklib.story_cli(", "print(")
    check("control: a delegate whose cli_main lost the story gate -> the delegating script is red",
          bool(census(effective_source(deleg, read=lambda m: doctored), "x")))
    doctored = read_script("judge_requirements").replace("hooklib.exact_options(parser)", "parser")
    check("control: a delegate whose cli_main lost exact_options -> red",
          bool(census(effective_source(deleg, read=lambda m: doctored), "x")))
    check("control: a cli_main imported but never called delegates nothing -> red", bool(census(
        effective_source(deleg.replace("return cli_main(", "return (lambda *a: 0)("), read=read_script), "x")))
    new_script = 'import argparse\np = argparse.ArgumentParser()\np.add_argument("--task-root")\n'
    check("control: a new script that declares --task-root is seen, and it is in no list",
          declares_task_root(new_script) and "brand_new_script" not in B_SCRIPTS + A_REST + UNCONVERTED + list(KEPT))
    check_eq("control: with it among the scripts the equality of the census is red",
             sorted(declared + ["brand_new_script"]) == expected, False)
    new_delegating = "from judge_requirements import cli_main\n\ndef main():\n    return cli_main('x.py', None, None, '')\n"
    check("control: a new script that only delegates to cli_main is seen as declaring --task-root too", declares_task_root(new_delegating))
    # X9 M-1: the delegate is found by SHAPE, not by name - a third-named helper that declares the flag is censused, and red when it loses the gate
    helper = ('import hooklib\n\ndef run_cli(argv):\n    parser = make()\n    parser.add_argument("--task-root")\n'
              '    hooklib.exact_options(parser)\n    args = parser.parse_args(argv)\n    hooklib.story_cli(args)\n')
    third = "from shared_cli import run_cli\n\ndef main():\n    return run_cli(None)\n"
    check("control (M-1): a script delegating to a THIRD-named helper that declares the flag is seen as declaring --task-root",
          declares_task_root(third, read=lambda m: helper) and not declares_task_root(third, read=lambda m: ""))
    check("control (M-1): ... and it is censused clean while the helper keeps the gate",
          census(effective_source(third, read=lambda m: helper), "x") == [])
    check("control (M-1): ... and RED when the helper loses the story gate",
          bool(census(effective_source(third, read=lambda m: helper.replace("hooklib.story_cli(", "print(")), "x")))
    check("control (M-1): ... and RED when the helper loses exact_options",
          bool(census(effective_source(third, read=lambda m: helper.replace("hooklib.exact_options(parser)", "parser")), "x")))
    two = "from shared_cli import run_cli\nfrom other_cli import add_options\n\ndef main():\n    run_cli(None)\n    add_options(None)\n"
    both = {"shared_cli": helper, "other_cli": "def add_options(p):\n    p.add_argument('--task-root')\n    exact_options(p)\n"}
    seen_two = effective_source(two, read=lambda m: both[m])
    check("control (M-1): a script that calls two delegates gets both", "def run_cli" in seen_two and "def add_options" in seen_two)
    method = "import shared_cli\n\ndef main(obj):\n    return obj.run_cli(None)\n"
    check("control (M-1): a method (obj.f) is not followed", "def run_cli" not in effective_source(method, read=lambda m: helper))
    nested = ("class Cli:\n    def run_cli(self):\n        parser.add_argument('--task-root')\n")
    check("control (M-1): a method defined in a class of the delegate module is not followed",
          effective_source(third, read=lambda m: nested) == third)
    check("control (M-1): a function of a module outside the scripts folder (nothing to read) delegates nothing",
          effective_source("import json\n\njson.dumps(1)\n", read=read_script) == "import json\n\njson.dumps(1)\n")
    deeper = {"shared_cli": "def run_cli(argv):\n    return inner(argv)\n", "inner_mod": helper}
    check("control (M-1): one level only - a delegate with no flag text that itself delegates is not followed through",
          not declares_task_root(third, read=lambda m: deeper.get(m, "")))
    gate_only = "def resolve(args):\n    return story_cli('x.py', key=args.task, root=args.task_root)\n"
    gated = "from shared_gate import resolve\n\ndef main(a):\n    return resolve(a)\n"
    check("control (M-1b): a delegate whose text has only `story_cli(` (no flag, no exact_options) is followed for the gate census",
          "def resolve" in effective_source(gated, read=lambda m: gate_only)
          and "def resolve" not in effective_source(gated, read=lambda m: "def resolve(a):\n    return 1\n"))
    for name, literal in KEPT.items():
        check(f"KEPT {name}: its own literal {literal} is still there (a stale row is red)",
              literal in (SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
    # positive controls: a copy of a real script with one piece missing must be red (the census can fail)
    source = (SCRIPTS / "case_stamp.py").read_text(encoding="utf-8")
    check("control: case_stamp as it is is clean", census(source, "case_stamp") == [])
    check("control: no exact_options -> red", bool(census(source.replace("hooklib.exact_options(parser)", "parser"), "x")))
    check("control: no story_cli -> red", bool(census(source.replace("hooklib.story_cli(", "print("), "x")))
    check("control: an add_argument after the call -> red", bool(census(
        source.replace("    result = stamp(", "    parser.add_argument('--late')\n    result = stamp("), "x")))
    bare = source.replace("hooklib.exact_options(", "exact_options(").replace("hooklib.story_cli(", "story_cli(")
    check("control: the bare-name form after `from hooklib import exact_options, story_cli` is clean",
          census("from hooklib import exact_options, story_cli\n" + bare, "x") == [])
    check("control: the bare-name form with NO hooklib import is red (a local function of the same name)",
          len(census(bare, "x")) == 2)
    check("control: story_cli under run_guarded -> red", bool(census(source + "\nfrom role_cli import run_guarded\n", "x")))
    # the controller's second path rule is the driver's now (CX1-18 half B), not a local is_dir
    tree = ast.parse((SCRIPTS / "controller.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_cli_story_root")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    check("controller._cli_story_root: --task-root goes through story_root_at, not is_dir_or_no",
          "story_root_at" in names and "is_dir_or_no" not in names, str(sorted(names & {"story_root_at", "is_dir_or_no"})))


# --- the table of scripts -------------------------------------------------------------------------------------

def snapshot(*roots) -> list:
    """(path, size) of everything under the roots: "nothing was written" is this being equal."""
    out = []
    for root in roots:
        out += sorted((str(p), p.stat().st_size if p.is_file() else -1) for p in Path(root).rglob("*"))
    return out


def table(aux: Path) -> dict:
    """name -> argv builder `(flag, root) -> list`. `flag` is the root flag as spelled (or abbreviated), `root` its value;
    `real` False where a run on a real story would reach for the network or a browser (the gate is pinned by the
    phantom and abbreviation rows alone)."""
    miss = aux / "missing.json"
    return {
        "artifact_packet": lambda f, r: ["--operation", "skeleton", "--input", miss, f, r],
        "artifact_producer": lambda f, r: ["prepare", "--kind", "readiness", f, r],
        "artifact_supersede": lambda f, r: ["--task", "TP3-1", "--path", "work/x.json", "--role", "qa-test-strategist",
                                            "--reason", "unusable", f, r],
        "branch_accounting": lambda f, r: [f, r, "--units"],      # TQ1-17 (0d0ecee5): a read-only listing, written after the class
        "case_stamp": lambda f, r: [f, r, "--dry-run"],
        "case_versions": lambda f, r: [f, r, "--verify"],
        "delivery_manifest": lambda f, r: [f, r, "--output", aux / "manifest.json"],
        "delivery_summary": lambda f, r: [f, r],
        "exploratory_findings": lambda f, r: ["list", f, r],
        "grounding_section": lambda f, r: ["--task", "TP3-1", "--show", "G-1", f, r],
        "handoff_check": lambda f, r: ["--file", aux / "form.yaml", f, r],
        "investigation": lambda f, r: ["targets", f, r],
        "investigation_probe": lambda f, r: ["http", f, r, "--dispatch", "D", "--target", "X", "--method", "GET", "--url",
                                             "http://127.0.0.1:9/"],
        "judge_cases": lambda f, r: [f, r], "judge_code": lambda f, r: [f, r], "judge_diff": lambda f, r: [f, r],
        "judge_plan": lambda f, r: [f, r], "judge_requirements": lambda f, r: [f, r],
        "judge_results": lambda f, r: [f, r, "--triage"],
        "judge_run": lambda f, r: [f, r, "--summary", miss],
        "manual_capture": lambda f, r: ["http", f, r, "--case", "TC-1", "--method", "GET", "--url", "http://127.0.0.1:9/"],
        "manual_evidence": lambda f, r: ["prepare", f, r],
        "migrate_artifacts": lambda f, r: [f, r],
        "plan_row": lambda f, r: ["--task", "TP3-1", "--row", "TS-1", "--show", f, r],
        "red_sandbox": lambda f, r: ["--request", miss, f, r],
        "regression_scope": lambda f, r: [f, r, "--check"],
        "render_case_appendix": lambda f, r: [f, r, "--output", aux / "appendix.md"],
        "report_facts": lambda f, r: [f, r, "--check"],
        "runtime_paths": lambda f, r: [f, r],
        "runtime_probe": lambda f, r: ["--profile", "p", "--checkout", aux, f, r],
        "s5_precheck": lambda f, r: [f, r, "--json"],
        "s7_reorder": lambda f, r: ["start", "--instance", "tests/test_x.py::test_x", f, r],
        "stage_status": lambda f, r: [f, r, "--event", "role_halt"],
        "story_progress": lambda f, r: [f, r],
        "story_version": lambda f, r: [f, r, "--check"],
        "ticket_adapter": lambda f, r: ["freshness", "TP3-1", f, r, "--ticket-file", miss],
        "bug_records": lambda f, r: ["open-bugs", f, r],
        "product_gaps": lambda f, r: ["revoke", f, r, "--requirement", "R-1", "--words-file", aux / "words.txt"],
        "tms_publication": lambda f, r: ["record", aux / "receipts.json", f, r],
        "traceability": lambda f, r: [f, r, "--check"],
        "place_answers": lambda f, r: ["list", f, r],      # S7 places (t-1995): exact_options + story_of, a read-only listing
        "walk_timing": lambda f, r: [f, r],
        "driver_timing": lambda f, r: [f, r],
        "walk_session": lambda f, r: ["status", f, r, "--walk", "W"],      # the walker (t-1957): a read of a record, no server is started
        # converted by A-rest (red on a tree without that half)
        "handoff_init": lambda f, r: ["--task", "TP3-1", "--stage", "S5", "--role", "qa-automator", f, r],
        "stand_gaps": lambda f, r: [f, r, "--json"],
        "gate_preflight": lambda f, r: [f, r, "--text"],      # X9: found by the shape reader; its flags and gate come from stand_gaps
        "sizing": lambda f, r: [f, r],
    }


NOT_REAL = {"manual_capture", "investigation_probe", "walk_session"}      # a real root would start a capture or a probe; the other rows pin the gate


def parsers_battery() -> None:
    project = temp_project("qa-task-root-parsers-")
    aux = temp_dir("qa-task-root-aux-")
    artifacts = project / "qa-factory" / "artifacts"
    real = artifacts / "TP3-1"
    (real / "work").mkdir(parents=True)
    (real / "pipeline.json").write_text("{}", encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    try:
        for name, build in table(aux).items():
            mark = " [converted by A-rest]" if name in A_REST else ""
            before = snapshot(project, aux)
            short = run_script(f"{name}.py", *build("--task-r", real), cwd=project, env=env)
            text = short.stdout + short.stderr
            check(f"{name}: --task-r is not --task-root{mark}",
                  short.returncode == 2 and ("unrecognized" in text or "required" in text or "ambiguous" in text)
                  and "names no story" not in text, f"rc {short.returncode}: {text[:160]!r}")
            check(f"{name}: and the refused abbreviation wrote nothing{mark}", snapshot(project, aux) == before)
            gone = run_script(f"{name}.py", *build("--task-root", artifacts / PHANTOM), cwd=project, env=env)
            text = gone.stdout + gone.stderr
            check(f"{name}: a phantom root is refused with the driver's text, exit 2{mark}",
                  gone.returncode == 2 and "names no story" in text and PHANTOM in text, f"rc {gone.returncode}: {text[:200]!r}")
            check(f"{name}: and nothing is created or written for it{mark}",
                  snapshot(project, aux) == before and not (artifacts / PHANTOM).exists())
            check_not_in(f"{name}: no green answer for a phantom{mark}", "OK", gone.stdout)
            if name in NOT_REAL:
                continue
            ok = run_script(f"{name}.py", *build("--task-root", real), cwd=project, env=env)
            text = ok.stdout + ok.stderr
            check(f"{name}: a real root passes the gate (whatever the script then says){mark}",
                  "names no story" not in text and "requires the story's folder" not in text, f"rc {ok.returncode}: {text[:200]!r}")
    finally:
        cleanup(project)
        cleanup(aux)


def edges_battery() -> None:
    """The mini-battery of the spec (P4-P8, P15, P16, E-3, E-4, E-6) on three representatives of the three channels:
    `case_stamp` (story_cli), `manual_evidence` (a guarded script's own refuse), `judge_cases` (a judge that can be off)."""
    project = temp_project("qa-task-root-edges-")
    spaced = Path(temp_dir("qa-task root space-"))
    artifacts = project / "qa-factory" / "artifacts"
    (artifacts / "TP3-1").mkdir(parents=True)
    (spaced / "qa-factory" / "artifacts" / "TP3-1").mkdir(parents=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    try:
        before = snapshot(project)
        for label, value in (("empty (P8, E-3)", ""), ("blank (P8, E-3)", "   "), ("parent step", "../nowhere-qa-404/TP3-404"),
                             ("a file", str(project / "qa-factory" / "config.json")),
                             ("300 characters (P15)", str(artifacts / ("k" * 300))),
                             ("Cyrillic E (P16)", str(artifacts / (CYRILLIC_E + "PM-1")))):
            for script, args in (("case_stamp.py", ["--task-root", value, "--dry-run"]),
                                 ("manual_evidence.py", ["prepare", "--task-root", value]),
                                 ("judge_cases.py", ["--task-root", value])):
                got = run_script(script, *args, cwd=project, env=env)
                text = got.stdout + got.stderr
                check(f"{script} --task-root {label}: refused, exit 2, the cwd is not read as a story",
                      got.returncode == 2 and ("names no story" in text or "requires the story's folder" in text),
                      f"rc {got.returncode}: {text[:160]!r}")
        check("none of the unfriendly values wrote anything", snapshot(project) == before)
        # the Cyrillic E is shown escaped by story_cli (the homoglyph is visible), not as a lookalike
        homoglyph = run_script("case_stamp.py", "--task-root", artifacts / (CYRILLIC_E + "PM-1"), cwd=project, env=env)
        check_in("P16: the JSON refusal escapes the Cyrillic E", "\\" + "u0415PM-1", homoglyph.stderr)
        check("P16: story_cli says it as one JSON object on stderr and nothing on stdout",
              homoglyph.stdout == "" and "error" in json.loads(homoglyph.stderr.strip().splitlines()[-1]))
        # P4, P5: a path with a space, a relative form from the doctor, a trailing slash - the real story passes
        for label, root, cwd in (("a path with a space (P4)", spaced / "qa-factory" / "artifacts" / "TP3-1", project),
                                 ("a relative path (P5)", "qa-factory/artifacts/TP3-1", project),
                                 ("a trailing slash", str(artifacts / "TP3-1") + "/", project)):
            ok = run_script("case_stamp.py", "--task-root", root, "--dry-run", cwd=cwd,
                            env=dict(env, CLAUDE_PROJECT_DIR=str(spaced if "space" in label else project)))
            check(f"case_stamp --task-root {label}: accepted", "names no story" not in ok.stdout + ok.stderr,
                  (ok.stdout + ok.stderr)[:160])
        # P10: the exact `=` spelling is legal
        eq = run_script("case_versions.py", f"--task-root={artifacts / 'TP3-1'}", "--verify", cwd=project, env=env)
        check("P10: --task-root=<folder> (the exact = form) is accepted", "names no story" not in eq.stdout + eq.stderr)
        # P14: --help is untouched
        for script in ("s5_precheck.py", "tms_publication.py"):
            helped = run_script(script, "--help", cwd=project, env=env)
            check(f"P14: {script} --help exits 0 and names --task-root or its commands",
                  helped.returncode == 0 and ("--task-root" in helped.stdout or "record" in helped.stdout))
        # E-4: a judge with the feature off answers a phantom with the refusal, not with "off"
        # (G8/X9: the refusal channel is the shared `cli_main`, so it is exercised through judge_cases AND judge_plan, not assumed from one)
        for script in ("judge_cases.py", "judge_plan.py"):
            gone = run_script(script, "--task-root", artifacts / PHANTOM, "--json", cwd=project, env=env)
            check(f"E-4: {script}, a judge that is off, still refuses a phantom root (no {{status: off}})",
                  gone.returncode == 2 and '"off"' not in gone.stdout and "names no story" in gone.stdout + gone.stderr,
                  gone.stdout[:100] + gone.stderr[:100])
        # E-6: report_facts and traceability said 1 for a phantom; it is a refusal of the call now, 2
        for script in ("report_facts.py", "traceability.py"):
            for flags in (["--task", PHANTOM], ["--task-root", artifacts / PHANTOM]):
                got = run_script(script, *flags, "--check", cwd=project, env=env)
                check(f"E-6: {script} {flags[0]} <phantom> exits 2 (it was 1)", got.returncode == 2
                      and "names no story" in got.stderr, f"rc {got.returncode}: {got.stderr[:120]!r}")
        # E-1 positions the table cannot see
        out_dir = artifacts / PHANTOM / "work"
        got = run_script("render_case_appendix.py", "--task-root", artifacts / PHANTOM, "--output", out_dir / "a.md",
                         cwd=project, env=env)
        check("P12/M-B4: render_case_appendix makes no --output folder under a phantom",
              got.returncode == 2 and "names no story" in got.stderr and not (artifacts / PHANTOM).exists(), got.stderr[:120])
        broken = project / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        got = run_script("artifact_packet.py", "--task-root", artifacts / PHANTOM, "--operation", "skeleton",
                         "--input", broken, cwd=project, env=env)
        check("P13/M-B5: artifact_packet names the story before it reads a broken --input",
              got.returncode == 2 and "names no story" in got.stderr and "JSONDecodeError" not in got.stderr, got.stderr[:160])
        got = run_script("artifact_packet.py", "--task-root", artifacts / "TP3-1", "--operation", "skeleton",
                         "--input", broken, cwd=project, env=env)
        err = got.stderr.strip().splitlines()[-1] if got.stderr.strip() else ""
        check("artifact_packet: a bad request on a real story is a JSON refusal (exit 2), not a traceback",
              got.returncode == 2 and "Traceback" not in got.stderr and err.startswith('{"error": "artifact_packet.py: '), err[:160])
        # E-5: a guarded script refuses on its OWN channel (role_cli.refuse: the command, the text, the way out)
        got = run_script("manual_evidence.py", "prepare", "--task-root", artifacts / PHANTOM, cwd=project, env=env)
        check("E-5: manual_evidence refuses through role_cli.refuse, no traceback, no JSON",
              got.returncode == 2 and got.stderr.startswith("manual_evidence.py prepare: ") and "Traceback" not in got.stderr
              and "\"error\"" not in got.stderr, got.stderr[:160])
        # F-8: a pair that names two different stories is refused, the same story twice is work
        (artifacts / "TP3-2").mkdir()
        got = run_script("artifact_supersede.py", "--task", "TP3-1", "--task-root", artifacts / "TP3-2", "--path", "work/x.json",
                         "--role", "qa-test-strategist", "--reason", "r", cwd=project, env=env)
        check("P9: --task TP3-1 --task-root <TP3-2> is refused as two different folders", "different folders" in got.stderr,
              got.stderr[:160])
        got = run_script("artifact_supersede.py", "--task", "TP3-1", "--task-root", artifacts / "TP3-1", "--path", "work/x.json",
                         "--role", "qa-test-strategist", "--reason", "r", cwd=project, env=env)
        check("P9: the same folder by both flags is not a conflict", "different folders" not in got.stderr
              and "names no story" not in got.stderr, got.stderr[:160])
    finally:
        cleanup(project)
        cleanup(spaced)


def controller_battery() -> None:
    """`controller.py --task-root` is the driver's path rule now (R1', R2'): an empty value, a phantom, a file."""
    project = temp_project("qa-task-root-controller-")
    (project / "qa-factory" / "artifacts" / "TP3-1").mkdir(parents=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    try:
        before = snapshot(project)
        for label, value, needle in (("empty", "", "requires the story's folder"), ("phantom", "nowhere/TP3-404", "names no story"),
                                     ("a file", "qa-factory/config.json", "names no story")):
            got = run_script("controller.py", "--task-root", value, "--operation", "next", cwd=project, env=env)
            check(f"controller --task-root {label}: refused with the driver's text, exit 2, nothing written",
                  got.returncode == 2 and needle in got.stdout + got.stderr and snapshot(project) == before,
                  (got.stdout + got.stderr)[:160])
    finally:
        cleanup(project)


def probe_subfolder_battery() -> None:
    """B2 (t-1230): `runtime_probe` run from a SUBFOLDER of the project writes only under the story the driver resolved
    (I1, I3): never a `qa-factory/artifacts/<KEY>` built from the cwd, for a key or for a phantom root."""
    project = temp_project("qa-task-root-probe-sub-")
    artifacts = project / "qa-factory" / "artifacts"
    (artifacts / "TP3-1" / "work").mkdir(parents=True)
    (artifacts / "TP3-1" / "pipeline.json").write_text("{}", encoding="utf-8")
    (artifacts / "TP3-1" / "work" / "impl-diff.txt").write_text("--- a/src/app.py\n+++ b/src/app.py\n+x = 1\n", encoding="utf-8")
    sub = project / "deep" / "er"
    sub.mkdir(parents=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    try:
        before = snapshot(sub)
        for label, flags in (("a phantom --task-root", ["--task-root", artifacts / PHANTOM]), ("a phantom --task", ["--task", PHANTOM])):
            got = run_script("runtime_probe.py", "--profile", "p", "--checkout", sub, "--expected", "abc", *flags, cwd=sub, env=env)
            check(f"probe from a subfolder, {label}: refused with exit 2 and nothing is created under the cwd",
                  got.returncode == 2 and "names no story" in got.stderr and snapshot(sub) == before
                  and not (artifacts / PHANTOM).exists(), f"rc {got.returncode}: {got.stderr[:160]!r}")
        got = run_script("runtime_probe.py", "--profile", "p", "--checkout", sub, "--expected", "abc", "--task", "TP3-1",
                         cwd=sub, env=env)
        verdict = got.stdout.strip().splitlines()[-1] if got.stdout.strip() else ""
        check("probe from a subfolder, a real --task: it reads THE story's diff (not_applicable: src/app.py is not in the "
              "checkout) and the cwd has no qa-factory folder",
              '"result": "not_applicable"' in verdict and snapshot(sub) == before and not (sub / "qa-factory").exists(),
              f"rc {got.returncode}: {(got.stdout + got.stderr)[:200]!r}")
    finally:
        cleanup(project)


def main() -> None:
    for battery in (census_battery, parsers_battery, edges_battery, controller_battery, probe_subfolder_battery):
        try:
            battery()
        except Exception as exc:  # noqa: BLE001 - a traceback is a failed row here, never the end of the run
            check(f"{battery.__name__}: ran to the end", False, f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0]}")
    finish("test_task_root_parsers")


if __name__ == "__main__":
    main()
