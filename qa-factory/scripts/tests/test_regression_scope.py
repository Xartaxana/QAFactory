#!/usr/bin/env python3
"""RG1-1, RG1-2, RG1-4 (docs/tasks/specs/t-532-s5-final.md, block RG): the plan's `## Recommended regression` is checked by
`regression_scope.py` and nothing else (the strategist writes, the tool checks, FR-47), against a REAL git repository whose
`refs/remotes/origin` is made by hand (no network).

Keys: M the main branch (`main_ref`: origin/HEAD, the declared branch, the conventional names, unknown), B `on_main` (True / False /
None kept apart; a tests root below the repository's top), S the section (every problem of `problems`, one key each), D the S3 exit
(`planning_contract._detector_body`: REJECT, OK, the WARN door, the summary), R the report (`report_facts._regression` and
`_r_regression`: `story_tests`, `notes`, `lines` untouched), T the briefs (`main_coverage_line`), the fragments of runs 12586 / 14857 /
the MyBooks run as text.
"""
import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import delivery_verdict as DV  # noqa: E402
import planning_contract as PC  # noqa: E402
import regression_scope as RS  # noqa: E402
import report_facts as RF  # noqa: E402
import traceability as T  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
ON_MAIN = ("tests/unit/test_a.py", "tests/api/test_b.py", "tests/e2e/cart.spec.ts", "tests/scheduler/test_scheduler_service.py",
           "tests/integrations/test_integration_update.py", "tests/integrations/test_edit_integration.py")
NO_STAND = "stand: no stand requirements"


def git(root: Path, *args: str) -> str:
    done = subprocess.run([*GIT, *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8")
    return done.stdout.strip()


def repo(files=ON_MAIN, head=True, branch="main", extra=(), root=None) -> Path:
    """A project root that is a git repository: `files` are committed, `refs/remotes/origin/<branch>` points at that commit (and
    `origin/HEAD` at it when `head`), `extra` files are written AFTER and never committed - a test written in the run."""
    root = root or temp_project("qa-regression-")
    marker = root / "qa-factory" / "config.json"
    if marker.is_file():      # item paths are read from the tests root: here the project root, so the fixture's paths say `tests/...`
        marker.write_text(json.dumps(dict(json.loads(marker.read_text(encoding="utf-8")), tests_root=".")), encoding="utf-8")
    git(root, "init", "-q")
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    if branch:
        git(root, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
        if head:
            git(root, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")
    for name in extra:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("y\n", encoding="utf-8")
    return root


def plan(task: Path, *lines: str) -> None:
    task.mkdir(parents=True, exist_ok=True)
    body = "## Plan\n\n| TS | R |\n|---|---|\n| TS-1 | R-9 |\n\n" + ("## Recommended regression\n" + "\n".join(lines) + "\n" if lines else "")
    (task / "test-plan.md").write_text(body, encoding="utf-8")


def found(root: Path, *lines: str, cfg=None) -> list:
    task = root / "qa-factory" / "artifacts" / "QA-1"
    plan(task, *lines)
    return RS.problems(task, root, cfg if cfg is not None else {})


def item(path: str, stand: str = NO_STAND, area: str = "blast:B-1") -> str:
    return f"- `{path}` ({area}) — {stand}"


A, B = "tests/unit/test_a.py", "tests/api/test_b.py"
CMD = f"Command: poetry run pytest {A} {B}"
GOOD = (CMD, item(A), item(B, "stand: needs a scheduler that starts the cron of the data sources", "blast:B-2"),
        "Developers: check the cart total at component level")


def has(problems: list, needle: str) -> bool:
    return any(needle in p for p in problems)


def exercise_main_ref() -> None:
    root = repo()
    try:
        check_eq("M origin/HEAD names the main branch", RS.main_ref(root, {}), ("origin/main", "origin/HEAD"))
    finally:
        cleanup(root)
    root = repo(head=False, branch="master")
    try:
        check_eq("M no origin/HEAD: the conventional names, origin/master", RS.main_ref(root, {})[0], "origin/master")
    finally:
        cleanup(root)
    root = repo(head=False, branch="develop")
    try:
        check_eq("M develop is named by nobody: unknown", RS.main_ref(root, {})[0], "")
        import project_inventory as PI
        real = PI.build_inventory
        try:      # the reader's output is stubbed here (its shapes: a string, a list, None, blanks); the real producer is pinned below
            for declared, want in (("develop", "origin/develop"), (["develop", "x"], ""), (None, ""), ("  ", "")):
                PI.build_inventory = lambda cfg, project, declared=declared: {"repositories": [
                    {"path": str(root), "declared_default_branch": declared}]}
                check_eq(f"M the DECLARED default branch {declared!r} (a string only, project_inventory's reader)", RS.main_ref(root, {})[0], want)
        finally:
            PI.build_inventory = real
        # F-6: NO stub - the declaration travels from the config through `configured_entries` (the producer) to the reader (AR-22)
        for key, entry in (("code_repos", {"name": "app", "path": ".", "default_branch": "develop"}),
                           ("implementation_repos", {"repo_id": "app", "local_path": ".", "default_branch": "develop"})):
            check_eq(f"M F-6 `default_branch` of a `{key}` entry reaches main_ref with the real inventory",
                     RS.main_ref(root, {key: [entry]})[0], "origin/develop")
        check_eq("M F-6 ... and a config that declares none stays unknown (develop is named by nobody)",
                 RS.main_ref(root, {"code_repos": [{"name": "app", "path": "."}]})[0], "")
    finally:
        cleanup(root)
    root = repo(branch="")
    try:
        ref, why = RS.main_ref(root, {})
        check("M no origin ref at all: ('', why) naming what was tried", ref == "" and "origin/main" in why, why)
    finally:
        cleanup(root)
    plain = temp_dir("qa-regression-nogit-")
    try:
        check_eq("M not a repository: unknown, no raise", RS.main_ref(plain, {})[0], "")
    finally:
        cleanup(plain)


def exercise_on_main() -> None:
    root = repo(extra=("tests/unit/test_new.py",))
    try:
        found_ = RS.on_main(root, "origin/main", [A, "tests/unit/test_new.py", "tests/unit"])
        check_eq("B a file on main is True, a file written in the run is False (not None: cat-file made it unknown), a folder is True",
                 found_, {A: True, "tests/unit/test_new.py": False, "tests/unit": True})
        bad = RS.on_main(root, "origin/nope", [A])
        check_eq("B an unknown ref is None, never False (a false refusal)", bad, {A: None})
        check_eq("B no ref at all is None", RS.on_main(root, "", [A]), {A: None})
        check_eq("B a path out of the repository (..) or absolute is None",
                 RS.on_main(root, "origin/main", ["../x.py", "/etc/passwd"]), {"../x.py": None, "/etc/passwd": None})
    finally:
        cleanup(root)
    # a tests root BELOW the repository's top: ls-tree reads the path from the cwd
    root = temp_dir("qa-regression-sub-")
    try:
        repo(files=("harness/tests/test_h.py", "other.py"), root=root)
        sub = root / "harness" / "tests"
        check_eq("B ls-tree from the tests root: test_h.py is True", RS.on_main(sub, "origin/main", ["test_h.py", "other.py"]),
                 {"test_h.py": True, "other.py": False})
        cfg = {"tests_root": "harness/tests"}
        check_eq("B base_root is the tests root when it is a directory", RS.base_root(root, cfg), sub.resolve())
        check_eq("B ...and the project when it is not", RS.base_root(root, {"tests_root": "nowhere"}), root.resolve())
        check_eq("S a project whose tests live below the top: the file on main passes", found(root, "Command: pytest test_h.py",
                 item("test_h.py"), cfg=cfg), [])
        check("S ...and a file that is not there is refused", has(found(root, "Command: pytest test_zz.py", item("test_zz.py"), cfg=cfg),
                                                                  "test_zz.py is not on origin/main"))
    finally:
        cleanup(root)


def exercise_section() -> None:
    root = repo(extra=("tests/unit/test_new.py",))
    try:
        check_eq("S a good section (a command per runner, items with stand, Developers) has no problem", found(root, *GOOD), [])
        for label, lines in (("absent", ()), ("blank", ("  ",))):
            got = found(root, *lines)
            check(f"S a {label} section is a problem naming the way out", len(got) == 1 and "No regression: <reason>" in got[0], str(got))
        check_eq("S `No regression: <reason>` alone is the declared empty outcome", found(root, "No regression: nothing defends this change"), [])
        check("S `No regression:` without a reason is a problem", has(found(root, "No regression:"), "has no reason"))
        check("S `No regression:` beside a Command is a problem", has(found(root, "No regression: none", *GOOD), "not both"))
        check("S `No regression:` beside an item is a problem", has(found(root, "No regression: none", item(A)), "not both"))
        check("S prose and nothing else names no test: a problem (silence is no answer)",
              has(found(root, "Nothing to add, really."), "names no test"))
        check("S items without a Command line", has(found(root, item(A)), "items but no `Command:`"))
        check("S a Command line without items", has(found(root, CMD), "`Command:` line but no items"))
        # repeats
        check("S a path listed twice", has(found(root, CMD, item(A), item(A), item(B)), "is listed twice"))
        check("S `a.py` and `a.py::t` are one repeat", has(found(root, f"Command: pytest {A} {A}::t", item(A), item(A + "::t")),
                                                          "is listed twice"))
        check_eq("S `a.py::t1` and `a.py::t2` are two tests, not a repeat",
                 found(root, f"Command: pytest {A}::t1 {A}::t2", item(A + "::t1"), item(A + "::t2")), [])
        check("S a file under another item's folder", has(found(root, "Command: pytest tests/unit tests/unit/test_a.py",
                                                               item("tests/unit"), item(A)), "lies under the folder"))
        # commands
        check("S an item in no Command line", has(found(root, "Command: pytest tests/unit/other.py", item(A)), "stands in no `Command:`"))
        check("S an item in two Command lines", has(found(root, f"Command: pytest {A}", f"Command: poetry run pytest {A}", item(A)),
                                                    "2 times"))
        check("S two equal Command lines", has(found(root, CMD, CMD, item(A), item(B)), "Two `Command:` lines are the same"))
        check("S the plugin's run_suite.py in a Command", has(found(root, f'Command: python "${{CLAUDE_PLUGIN_ROOT}}/scripts/run_suite.py" '
                                                                  f"--label x -- {A}", item(A)), "runs the factory's scripts"))
        check("S run_suite.py alone is the same", has(found(root, f"Command: python run_suite.py {A}", item(A)), "runs the factory's scripts"))
        check("S an absolute path item", has(found(root, "Command: pytest /home/me/tests/test_a.py", item("/home/me/tests/test_a.py")),
                                             "absolute path"))
        check("S a Windows absolute path item", has(found(root, r"Command: pytest C:\x\test_a.py", item(r"C:\x\test_a.py")),
                                                    "absolute path"))
        # the main branch
        got = found(root, "Command: pytest tests/unit/test_new.py", item("tests/unit/test_new.py"))
        check("S a file that is not on main is refused and says why", has(got, "tests/unit/test_new.py is not on origin/main") and
              has(got, "regression names tests that already exist"), str(got))
        check_eq("S ...once, however the path is spelled (./ and backslashes)", len(found(
            root, r"Command: pytest .\tests\unit\test_new.py", item(r".\tests\unit\test_new.py"))), 1)
        check("S a node of a file that is not on main is refused by its file", has(
            found(root, "Command: pytest tests/unit/test_new.py::t", item("tests/unit/test_new.py::t")), "tests/unit/test_new.py is not on"))
        check("S an item with no stand", has(found(root, CMD, f"- `{A}` (blast:B-1)", item(B)), "has no `stand:`"))
        check("S an item with an empty stand", has(found(root, CMD, f"- `{A}` (blast:B-1) — stand:", item(B)), "has no `stand:`"))
        # forms of the runners (the Command's syntax is never parsed: only its words are looked at)
        check_eq("S poetry run pytest a b passes the form", found(root, CMD, item(A), item(B)), [])
        check_eq("S npx playwright test a b passes the form",
                 found(root, "Command: npx playwright test tests/e2e/cart.spec.ts", item("tests/e2e/cart.spec.ts")), [])
        check_eq("S two runners (unit and Playwright), one Command each, pass", found(
            root, f"Command: npm run test:unit -- {A}", "Command: npx playwright test tests/e2e/cart.spec.ts", item(A),
            item("tests/e2e/cart.spec.ts")), [])
        check_eq("S targets() reads the ITEMS, never the Command", RS.targets(list(GOOD)), [A, B])
        check_eq("S targets() normalizes (./, backslash, trailing /)", RS.targets([item(r".\tests\unit\\")]), ["tests/unit"])
    finally:
        cleanup(root)


def exercise_runs_as_text() -> None:
    """The fragments of the real runs: text only (the original artifacts are not in the tree)."""
    root = repo(extra=("tests/ui/datasource/test_code_datasource_reindex_last_indexed.py",))
    try:
        reindex = "tests/ui/datasource/test_code_datasource_reindex_last_indexed.py"
        got = found(root, f"Command: poetry run pytest {reindex} tests/scheduler/test_scheduler_service.py", item(reindex),
                    item("tests/scheduler/test_scheduler_service.py", "stand: needs a scheduler that starts the cron of the data sources"))
        check("14857: the test written in the run is refused, and only it", len(got) == 1 and has(got, f"{reindex} is not on origin/main"),
              str(got))
        check_eq("14857: the scheduler test carries its stand and passes", found(
            root, "Command: poetry run pytest tests/scheduler/test_scheduler_service.py",
            item("tests/scheduler/test_scheduler_service.py", "stand: needs a scheduler that starts the cron of the data sources")), [])
        update, edit = "tests/integrations/test_integration_update.py", "tests/integrations/test_edit_integration.py"
        check_eq("12586: the files under tests/integrations that exist pass", found(
            root, f"Command: poetry run pytest {update} {edit}", item(update), item(edit)), [])
        got = found(root, f"Command: poetry run pytest {update} {edit} tests/integrations", item(update), item(edit), item("tests/integrations"))
        check_eq("12586: the same files AND their folder: each file lies under the folder", sum("lies under the folder" in p for p in got), 2)
    finally:
        cleanup(root)


def exercise_unknown_main() -> None:
    root = repo(branch="", extra=("tests/unit/test_new.py",))
    try:
        check_eq("S main unknown: a file that is not there raises NO path problem (FR-59: silent, not 'checked')",
                 found(root, "Command: pytest tests/unit/test_new.py", item("tests/unit/test_new.py")), [])
        check("S ...and the other checks still work (a repeat)", has(found(root, CMD, item(A), item(A), item(B)), "is listed twice"))
        check("S ...and an absent section is still a problem", len(found(root)) == 1)
    finally:
        cleanup(root)


# --- D: the S3 exit -----------------------------------------------------------------------------------------------------

REGISTER = "## Register\n\n| R | requirement | source | derived_from |\n|---|---|---|---|\n"


def detector(root: Path, *lines: str, write_plan=True) -> tuple:
    """Run `planning_contract.detector_main` over a clean story of `root` (the plan's own checks stubbed clean, the register empty), the
    section being `lines`; (exit code, printed text)."""
    task = root / "qa-factory" / "artifacts" / "QA-1"
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [
        {"id": "TS-1", "requirements": ["R-9"], "disposition": "skip", "reason": "r"}]}), encoding="utf-8")
    if write_plan:
        plan(task, *lines)
    saved = PC.detector_story, PC.gate_plan_errors
    PC.detector_story, PC.gate_plan_errors = (lambda *a, **k: task), (lambda *a, **k: [])
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = PC.detector_main(task)
    finally:
        PC.detector_story, PC.gate_plan_errors = saved
    return code, out.getvalue()


def exercise_detector() -> None:
    root = repo(extra=("tests/unit/test_new.py",))
    try:
        code, text = detector(root, *GOOD)
        check("D a good section: OK, exit 0, no regression line", code == 0 and "OK:" in text and "Recommended regression" not in text,
              f"{code} {text}")
        code, text = detector(root)
        check("D no section on the story's test-plan.md: REJECT (exit 1), never OK", code == 1 and "OK:" not in text, f"{code} {text}")
        check_in("D ...the block is the fourth kind of the same form", "REJECT — 1 problem(s) in the plan's `## Recommended regression`", text)
        check_in("D ...with the line", "- no `## Recommended regression` in test-plan.md", text)
        check_in("D ...the summary counts it", "1 regression problem(s)", text)
        check_in("D ...and the door of a person's word stays the waiver line", "A person's word passes any of these", text)
        code, text = detector(root, "No regression: nothing defends this change")
        check("D `No regression: <reason>` passes the exit", code == 0 and "OK:" in text, f"{code} {text}")
        code, text = detector(root, "Command: pytest tests/unit/test_new.py", item("tests/unit/test_new.py"))
        check("D a test of this run named as regression: REJECT naming the path", code == 1 and "tests/unit/test_new.py is not on origin/main" in text,
              f"{code} {text}")
        (root / "qa-factory" / "artifacts" / "QA-1" / "test-plan.md").unlink(missing_ok=True)
        code, text = detector(root, write_plan=False)
        check("D no test-plan.md on disk: the regression check says nothing (other checks answer for the file)",
              code == 0 and "regression" not in text.lower(), f"{code} {text}")
        # a check that cannot run is a WARN and the exit goes on
        saved = RS.problems
        RS.problems = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            code, text = detector(root, *GOOD)
        finally:
            RS.problems = saved
        check("D problems() raising: a WARN line, exit 0, never UNREADABLE (exit 3)", code == 0 and "WARN regression check could not run" in text
              and "UNREADABLE" not in text, f"{code} {text}")
    finally:
        cleanup(root)
    # a story outside any project: the project is not found, the check is a WARN, not a pass of the section and not a refusal
    plain = temp_dir("qa-regression-noproject-")
    try:
        task = plain / "QA-1"
        plan(task, *GOOD)
        check_eq("D a story with no project: the helper returns [] (WARN printed)", _quiet(PC._regression_findings, task), [])
    finally:
        cleanup(plain)


def _quiet(func, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args)


# --- R: the report ------------------------------------------------------------------------------------------------------

def exercise_report() -> None:
    root = repo(extra=("tests/unit/test_new.py",))
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True, exist_ok=True)
        section = ("Command: pytest tests/unit/test_new.py tests/unit/test_a.py", item("tests/unit/test_new.py"), item(A))
        plan(task, *section)
        manifest = {"tests": [
            {"file": "tests/unit/test_new.py", "instance_id": "i1"}, {"file": "tests/unit/test_new.py", "instance_id": "i2"},
            {"file": "tests/api/test_dead.py", "instance_id": "i3", "note": T.DEAD_NOTE_PREFIX + " delinked"},
            {"file": "tests/api/test_live.py", "instance_id": "i4"}]}
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = RF._regression(task, root)
        verbatim = DV.regression_lines((task / "test-plan.md").read_text(encoding="utf-8"))
        check_eq("R lines are the plan's lines, byte for byte (FR-49)", got["lines"], verbatim)
        check_eq("R story_tests: live files, sorted, no repeats, the delinked one is not here",
                 got["story_tests"], ["tests/api/test_live.py", "tests/unit/test_new.py"])
        check_eq("R a story test named as regression and not on main: one note",
                 got["notes"], ["tests/unit/test_new.py is a test of this story and not on origin/main; it is not regression"])
        check_in("R ...and the same finding on stderr", "report: tests/unit/test_new.py is a test of this story", err.getvalue())
        block = RF._r_regression({"regression": got})
        check_in("R the block lists the lines first", "Command: pytest tests/unit/test_new.py", block)
        check_in("R ...then the tests of this story on their own line", "Tests of this story (not regression): tests/api/test_live.py, "
                 "tests/unit/test_new.py", block)
        check_in("R ...then the note", "it is not regression", block)
        # the plan names only a test of main: no note, but the line of the story's tests is there
        plan(task, CMD, item(A), item(B))
        with contextlib.redirect_stderr(io.StringIO()):
            got = RF._regression(task, root)
        check_eq("R existing tests only: no note", got["notes"], [])
        # the report without a manifest: story_tests is [], never a raise, lines unchanged
        (task / "work" / "automation-manifest.json").write_text("{ not json", encoding="utf-8")
        got = RF._regression(task, root)
        check_eq("R an unreadable manifest: story_tests [], the lines stay", (got["story_tests"], got["lines"]),
                 ([], DV.regression_lines((task / "test-plan.md").read_text(encoding="utf-8"))))
        check_not_in("R ...and no 'Tests of this story' line in the block", "Tests of this story", RF._r_regression({"regression": got}))
        # no plan at all: the gap line as before
        (task / "test-plan.md").unlink()
        got = RF._regression(task, root)
        check_eq("R no plan: lines [], notes [], the gap line renders as before", (got["lines"], got["notes"]), ([], []))
        check_in("R ...the gap line", DV.GAP_LINE, RF._r_regression({"regression": got}))
    finally:
        cleanup(root)
    # the main branch unknown with items named: the note says it could not check
    root = repo(branch="")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        plan(task, CMD, item(A), item(B))
        (task / "work").mkdir(parents=True, exist_ok=True)
        got = RF._regression(task, root)
        check("R main unknown and items named: the note says the paths could not be checked and why",
              len(got["notes"]) == 1 and got["notes"][0].startswith("the paths could not be checked against the main branch: "), str(got))
        plan(task, "No regression: none")
        check_eq("R main unknown and no item: no note", RF._regression(task, root)["notes"], [])
    finally:
        cleanup(root)
    # an exception inside the helper never reaches the caller
    saved = RS.targets
    RS.targets = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        root = repo()
        task = root / "qa-factory" / "artifacts" / "QA-1"
        plan(task, *GOOD)
        got = RF._regression(task, root)
        check_eq("R the measurer never raises: story_tests and notes are [] on a failure", (got["story_tests"], got["notes"]), ([], []))
    finally:
        RS.targets = saved
        cleanup(root)


# --- T: the briefs, the command line ------------------------------------------------------------------------------------

def exercise_brief_and_cli() -> None:
    import brief_pack
    root = repo()
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True, exist_ok=True)
        check_eq("T the brief line names the ref", brief_pack.main_coverage_line(task),
                 "Test files of the diff already on origin/main are existing coverage, not part of this change.")
        plan(task, *GOOD)
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "regression_scope.py"), "--task", "QA-1", "--root", str(root), "--check"],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(root))
        check("T the CLI: a good section is exit 0 and OK", done.returncode == 0 and done.stdout.startswith("OK:"), done.stdout + done.stderr)
        plan(task, CMD, item(A), item(A), item(B))
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "regression_scope.py"), "--task", "QA-1", "--root", str(root), "--check"],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(root))
        check("T the CLI: a problem is exit 1 and one line each", done.returncode == 1 and "- `tests/unit/test_a.py` is listed twice" in done.stdout,
              done.stdout + done.stderr)
    finally:
        cleanup(root)
    root = repo(branch="")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True, exist_ok=True)
        check_eq("T main unknown: NO line (an unknown is never a fact)", brief_pack.main_coverage_line(task), "")
    finally:
        cleanup(root)
    plain = temp_dir("qa-regression-brief-")
    try:
        check_eq("T no project at all: no line, no raise", brief_pack.main_coverage_line(plain / "QA-1"), "")
    finally:
        cleanup(plain)


def exercise_report_check() -> None:
    """R: a report written with the new lines (the story's tests, the note) passes `--check`: `check` reads the same `_regression`."""
    import shutil
    work = temp_dir("qa-regression-check-")
    try:
        task = work / "QA-1"
        shutil.copytree(harness.FIXTURES / "after-checks", task)
        res = RF.write(task)
        got = RF._regression(task)
        check("R the fixture story has tests, so the block carries the line", bool(got["story_tests"]) and res["ok"], str(res["lines"]))
        check_in("R ...in the written report", "Tests of this story (not regression):", (task / "test-report.md").read_text(encoding="utf-8"))
        check_eq("R write then check: no problem (no loop at S9)", RF.check(task), [])
    finally:
        cleanup(work)


def main() -> None:
    exercise_report_check()
    exercise_main_ref()
    exercise_on_main()
    exercise_section()
    exercise_runs_as_text()
    exercise_unknown_main()
    exercise_detector()
    exercise_report()
    exercise_brief_and_cli()
    finish("test_regression_scope")


if __name__ == "__main__":
    main()
