#!/usr/bin/env python3
"""qa-factory self-test entry point.

Subcommands (all but --hooks run when no flag is given):
  --selftest-scripts   guard_pre_tool.py --selftest, form_selftest.py, run_suite.py --selftest,
                        external_writes.py --selftest — each as a subprocess, non-zero = fail.
  --roots               builds a temp git repo, seeds qa-factory/config.json from
                        references/templates/config.json, points CLAUDE_PROJECT_DIR at it and
                        asserts hooklib.state_dir() resolves inside that repo while
                        hooklib.ref("common-rules.md") resolves inside the plugin.
  --lang                fails on any Cyrillic character anywhere in the package, and on any
                        control byte an eaten escape sequence leaves behind (FR-29: a backslash-b
                        swallowed by a heredoc becomes 0x08 and the regex around it silently
                        stops matching). No
                        exemption: the repository is English, whoever the reader is. The
                        agreed change plans are working documents for the owner, they are
                        not the factory's content, and they live outside this repository.
  --limits               fails when any skills/*/SKILL.md exceeds 19000 bytes or 500 lines,
                        any agents/*.md exceeds 9000 bytes, or any references/*.md exceeds
                        12000 bytes. A missing directory is not a violation.
  --wiring               every `project:` file references/inject-map.json delivers to a role
                        is named by the onboarding generator (phases/p4-generate.md). A file
                        a role is injected with but onboarding never writes is a hole the
                        role reads; a file onboarding writes that no role reads is a document
                        nobody will notice going stale.
  --slices               contract_slices.py --check: every generated role slice named in
                        inject-map.json exists and matches what its source renders today. The
                        slices ship in the package (the injection hook renders nothing), so a
                        stale one delivers a rule the source no longer states.
  --hooks                runs scripts/tests/test_hooks_wiring.py (the A3 wiring test) on its
                        own. Not part of a full run: --tests runs that same file, and running
                        it twice cost 25 s and reported one result under two names.
  --contracts            runs the registry walks on their own: scripts/tests/test_null_outcomes.py
                         (the null outcomes), test_gate_registry.py (the gate registry, audit A26) and
                         test_stage_joints.py (the stage joints: every check has its producer and its told place, F6-51).
                        Not part of a full run: --tests runs the same file.
  --tests                runs every scripts/tests/test_*.py as its own subprocess, --jobs of
                        them at a time (default 4, 1 = serial). Result lines keep file order
                        and each carries its own duration; the summary adds the slowest five.
  --fast                 the commit-time tier: --limits --lang --slices --wiring --tests
                        (skipping the files scripts/slow_tests.json names) --hygiene. No
                        --selftest-scripts, --roots or --hooks. ~90 s on 4 workers; the full,
                        flagless run is what the release run must still pass before a push.
  --slow-tests           diffs scripts/slow_tests.json against a measurement: this process's own
                        --tests run (put --tests in the same call), or `--from <selftest.txt>`, a
                        saved selftest output. `+ file` is over the slow threshold and not listed,
                        `- file` is listed and under the fast threshold (or gone from disk); exit 1
                        when more than "max_drift" files differ. `--update` rewrites the file from
                        the measurement and exits 0. Needs the data file: absent or malformed = exit 2.
  --shard I/N            with --tests (or a flagless run): runs only the I-th of N weight-balanced
                        parts of the test files (longest-processing-time greedy; weights are the seconds
                        in scripts/slow_tests.json, an unlisted file counts half of "fast_under_s"; a file
                        is never split) and prints the header line `selftest shard I/N: K of M test files`
                        first. In a flagless run shard 1 runs every check, a shard I > 1 only its tests and
                        --hygiene; the summary reads `(shard I/N)`. An empty part prints an explicit note and
                        passes. Not with --fast or --slow-tests: concatenate every shard's output once and
                        pass it as --slow-tests --from; a missing, repeated or mixed-N shard is exit 2.
  --quarantined          runs ONLY the files scripts/tests/test-layers.json lists under "quarantine" (implies --tests;
                        not with --fast or --slow-tests; --shard works, weighted by each row's "seconds"). A measurement,
                        not a gate: exit 0 whatever the files do, 2 when the runner itself fails.
  --watch-out PATH       with --quarantined: writes the watch record (sha, package_version, shard, expected, one status
                        per file: green|red|timeout|ran_nothing|missing, FAIL names, last traceback line) to PATH.
  --hygiene              fails when the package directory holds anything git does not track.
                        A marketplace whose source is a local directory copies the tree as it
                        lies on disk, so a leftover of a test run is installed for the next
                        user. Runs last, because the run itself is what leaves them.
  --ping                 prints "pong" and exits 0 (kept from the A1 skeleton).

Prints one PASS/FAIL line per check and a final summary; exits 1 on any failure.
"""
import argparse
import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from content_size import content_bytes

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
TESTS_DIR = SCRIPTS_DIR / "tests"


def _sorted_paths(paths) -> list:
    """mirror of hooklib.sorted_paths (key=Path.as_posix) - the runner does not import hooklib (it runs it in a subprocess)"""
    return sorted(paths, key=lambda p: p.as_posix())

# The list of slow test files is a data file, scripts/slow_tests.json (FR-13), read by
# slow_tests() in the --slow-tests section below.
SLOW_TESTS_FILE = SCRIPTS_DIR / "slow_tests.json"

# Per-file ceiling (seconds) for a test file that legitimately needs more than the default 300 s;
# read by _test_outcome(), a file not listed keeps 300. A file that needs more than 300 s is a
# cost defect (the old test_story_run.py was one, B-155 split it into test_story_run_*.py), so this
# is a ceiling, not a target: it stops a slow-but-green file from reading as a failure, it does not
# make the slowness fine.
TEST_TIMEOUTS = {
    # 11.11: TD-15, a story replays a recorded run through the real doors: every `handed` facet is a real
    # `story_step start` on its own copy of the world. 330 s on a loaded Windows box; full tier only.
    "test_scenario_cart_1.py": 1200,
    "test_scenario_local_1_arm_b.py": 1200,
    "test_scenario_local_1_0108.py": 1800,
    "test_red_sandbox_probe.py": 600,
    # 05.10: 345 checks split out of test_red_sandbox_probe.py (which ran 769 s as one file): 327 s alone on
    # the second developer's machine, where the sibling runs 385 s under the same 600. The ceiling only
    # keeps a green file green.
    "test_red_sandbox_reports.py": 600,
    "test_state_portability.py": 600,
    # 03.10: 513 cases, 305 s alone on the Lead's machine after the night's batches (the driver's
    # launched row, line-buffered stdout, the resolver); timed out under load in the full run. The
    # split is queued (B-297, the B-155 class); the ceiling only keeps a green file green.
    "test_story_run_s0.py": 600,
    "test_story_run_gate_repair.py": 600,
    # 05.10: 313 checks, 329 s alone on the second developer's machine (177 s before the merge of 0.8.1;
    # 25 min 46 s under the shared load of a verification window): over the default 300 s, so a full
    # run killed it. The split is queued (B-381, the B-155 class); the ceiling only keeps a green file green.
    "test_words_doors.py": 600,
    # 21.10: G1-2, 285.6 s in the builder's run against the default 300 s (it builds temp git repos, B21 alone 300 files twice); it
    # runs only in the nightly package-full, where a loaded runner would turn it red (FR-31). The cost cut is queued (the B-155 class);
    # the ceiling only keeps a green file green.
    "test_blast_radius.py": 600,
    # 10.11: TR4-4, 13 checks, 238 s in the builder's run on Windows (t-2053 F5) against 20.0 s on the CI canon 8063481: every check builds
    # its own seeded project and runs the S0 stage_done subprocess, so the cost is process spawn on a loaded machine (FR-31). The
    # ceiling only keeps a green file green.
    "test_exit_limit_halt_answered.py": 600,
    # 10.11: t-2197, five live worlds (each a real controller init + seeded S5 rework/finish subprocesses + several Driver.run processes),
    # 211-229 s on a normal CI runner and timed out at 300 s on three jobs co-scheduled on contended GKE nodes (28303701, 28303725,
    # 28303050; every file in those shards ran 1.3-1.6x slower). FR-31: the ceiling only keeps a green file green; the split of the
    # file (the B-155 class) is queued.
    "test_story_run_s7_live.py": 600,
    # 10.11: t-2202, the same class: 258.6 s seen on a loaded GKE node (shard 2) against 129-146 s normal. FR-31: the ceiling only keeps
    # a green file green; the cost cut is queued (the B-155 class).
    "test_story_run_refusals.py": 600,
}

# A child that imports the package writes __pycache__ into it, and what lies in the package
# is what a local-directory marketplace installs (see cmd_hygiene). Setting it here, not only
# in run_subprocess, is what makes it true for every child: each of them is started from a
# copy of this environment.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

RESULTS: list[tuple[bool, str]] = []
TEST_DURATIONS: dict[str, float] = {}  # relative test file -> seconds, filled by cmd_tests()
TEST_CAPTURE: dict[str, dict] = {}     # test file name -> {"fails": every FAIL line, "crash": last traceback line}


def check(name: str, ok: bool, detail: str = "", seconds: float | None = None) -> bool:
    RESULTS.append((ok, name))
    line = ("PASS " if ok else "FAIL ") + name
    if seconds is not None:
        line += f"  {seconds:.1f}s"
    if detail and not ok:
        line += f" — {detail}"
    print(line)
    return ok


def run_subprocess(args: list, cwd: Path | None = None, env: dict | None = None,
                    timeout: int = 300) -> subprocess.CompletedProcess:
    # -B and PYTHONDONTWRITEBYTECODE: a child that imports the package writes __pycache__
    # into the package, and what lies in the package is what a local-directory marketplace
    # installs (see cmd_hygiene). The variable carries the rule on to grandchildren.
    child_env = dict(env if env is not None else os.environ)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    # PYTEST_DISABLE_PLUGIN_AUTOLOAD: the tests that launch a real pytest launch it to collect
    # node ids, and a measured `--collect-only` cost 3.11 s with the machine's installed
    # plugins autoloading and 1.12 s without them — ~45 s over one selftest. It is also the
    # more honest run: node_ids.py states that pytest-playwright "is never needed", the temp
    # project's conftest simulates what that plugin does, and a real plugin loading on top of
    # it would parametrize the same fixture twice. Only the selftest's own children are set
    # this way — a project's pytest plugins are the project's business, and run_suite.py and
    # the other runtime scripts never touch this variable.
    child_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(
        [sys.executable, "-B"] + args, capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None,
        env=child_env, timeout=timeout,
    )


# --- --selftest-scripts ------------------------------------------------------------------

def cmd_selftest_scripts() -> bool:
    ok = True
    for label, script, args in (
        ("guard_pre_tool.py --selftest", "guard_pre_tool.py", ["--selftest"]),
        ("form_selftest.py", "form_selftest.py", []),
        ("run_suite.py --selftest", "run_suite.py", ["--selftest"]),
        ("external_writes.py --selftest", "external_writes.py", ["--selftest"]),
        ("diff_pass.py --selftest", "diff_pass.py", ["--selftest"]),
        ("stage_done.py --selftest", "stage_done.py", ["--selftest"]),
        ("turn_budget.py --selftest", "turn_budget.py", ["--selftest"]),
        ("diff_scope.py --selftest", "diff_scope.py", ["--selftest"]),
        ("manifest_view.py --selftest", "manifest_view.py", ["--selftest"]),
        ("manifest_put.py --selftest", "manifest_put.py", ["--selftest"]),
        ("waiver.py --selftest", "waiver.py", ["--selftest"]),
        ("window_budget.py --selftest", "window_budget.py", ["--selftest"]),
        ("gate_brief.py --selftest", "gate_brief.py", ["--selftest"]),
        ("gate_preflight.py --selftest", "gate_preflight.py", ["--selftest"]),
        ("stand_gaps.py --selftest", "stand_gaps.py", ["--selftest"]),
        ("traceability.py --selftest", "traceability.py", ["--selftest"]),
        ("tracker_write.py --selftest", "tracker_write.py", ["--selftest"]),
        ("stage_status.py --selftest", "stage_status.py", ["--selftest"]),
        ("sizing.py --selftest", "sizing.py", ["--selftest"]),
        ("retro_numbers.py --selftest", "retro_numbers.py", ["--selftest"]),
        ("node_ids.py --selftest", "node_ids.py", ["--selftest"]),
        ("stand_lease.py --selftest", "stand_lease.py", ["--selftest"]),
        ("stand_health.py --selftest", "stand_health.py", ["--selftest"]),
        ("story_budget.py --selftest", "story_budget.py", ["--selftest"]),
        ("human_text.py --selftest", "human_text.py", ["--selftest"]),
    ):
        p = run_subprocess([str(SCRIPTS_DIR / script)] + args)
        tail = (p.stdout or p.stderr).strip().splitlines()
        ok = check(f"selftest-scripts: {label}", p.returncode == 0,
                   f"exit {p.returncode}" + (f" | {tail[-1][:200]}" if tail else "")) and ok
    return ok


# --- --roots -------------------------------------------------------------------------------

def cmd_roots() -> bool:
    ok = True
    with tempfile.TemporaryDirectory(prefix="qa-factory-roots-") as td:
        proj = Path(td) / "project"
        proj.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=proj, capture_output=True)
        qf = proj / "qa-factory"
        qf.mkdir()
        example = PLUGIN_ROOT / "references/templates/config.json"
        (qf / "config.json").write_text(
            example.read_text(encoding="utf-8") if example.exists() else "{}", encoding="utf-8"
        )
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
            "import hooklib\n"
            "print(str(hooklib.state_dir()))\n"
            "print(str(hooklib.ref('common-rules.md')))\n"
        )
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(proj)
        p = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(proj), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env)
        if p.returncode != 0:
            tail = (p.stderr or p.stdout or "").strip().splitlines()
            return check("roots: hooklib evaluates cleanly under CLAUDE_PROJECT_DIR", False,
                        tail[-1][:200] if tail else f"exit {p.returncode}")
        lines = p.stdout.strip().splitlines()
        state_dir_out = Path(lines[0]) if len(lines) > 0 else None
        ref_out = Path(lines[1]) if len(lines) > 1 else None

        def is_inside(child: Path | None, parent: Path) -> bool:
            if child is None:
                return False
            try:
                child.resolve().relative_to(parent.resolve())
                return True
            except Exception:
                return False

        ok = check("roots: state_dir() resolves inside the temp project",
                   is_inside(state_dir_out, proj), str(state_dir_out)) and ok
        ok = check("roots: ref('common-rules.md') resolves inside the plugin",
                   is_inside(ref_out, PLUGIN_ROOT), str(ref_out)) and ok
    return ok


# --- --lang ---------------------------------------------------------------------------------

# Built from code points (not a literal char class) so this very file stays Cyrillic-free.
CYRILLIC = re.compile("[" + chr(0x0400) + "-" + chr(0x04FF) + "]")
SKIP_DIR_NAMES = {"__pycache__", ".git"}


def _package_files():
    for p in PLUGIN_ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        yield p


def cmd_lang() -> bool:
    # All distributed package files must be English. Working documents belong outside
    # the plugin source tree and must not be included in the published package.
    violations = []
    for p in _package_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue  # binary or unreadable — not a language-check target
        if CYRILLIC.search(text):
            violations.append(str(p.relative_to(PLUGIN_ROOT)))
    ok = check("lang: no Cyrillic anywhere in the package", not violations,
               f"{len(violations)} file(s)")
    for v in violations[:30]:
        print(f"  - {v}")
    return cmd_control_bytes() and ok


# The bytes a heredoc leaves behind when it eats an escape: `\b` becomes 0x08, `\f` 0x0c. FR-29's
# own Check asks for this and nothing enforced it package-wide — on 28.09 a `\b` was eaten into a
# literal 0x08 inside a TEST file, and the check that test was making passed because its regex
# matched nothing. A whole file's worth of bytes, read here rather than by eye.
CONTROL_BYTES = {7: "0x07 (bell)", 8: "0x08 (an eaten backslash-b)", 11: "0x0b (vertical tab)",
                 12: "0x0c (an eaten backslash-f)"}


def cmd_control_bytes() -> bool:
    violations = []
    for p in _package_files():
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff",
                                ".woff2", ".ttf"):
            continue
        try:
            raw = p.read_bytes()
        except (OSError, PermissionError):
            continue
        found = [name for code, name in CONTROL_BYTES.items() if bytes([code]) in raw]
        if found:
            violations.append(f"{p.relative_to(PLUGIN_ROOT)}: {', '.join(found)}")
    ok = check("lang: no control byte left by an eaten escape sequence (FR-29)", not violations,
               f"{len(violations)} file(s)")
    for v in violations[:30]:
        print(f"  - {v}")
    return ok


# --- --limits ---------------------------------------------------------------------------------

SKILL_MD_MAX_BYTES = 19_000
SKILL_MD_MAX_LINES = 500
AGENT_MD_MAX_BYTES = 9_000
REFERENCE_MD_MAX_BYTES = 12_000


def cmd_limits() -> bool:
    violations = []

    skills_dir = PLUGIN_ROOT / "skills"
    for f in _sorted_paths(skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else []:
        size = content_bytes(f)
        lines = f.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        if size > SKILL_MD_MAX_BYTES:
            violations.append(f"{f.relative_to(PLUGIN_ROOT)}: {size} bytes > {SKILL_MD_MAX_BYTES}")
        if lines > SKILL_MD_MAX_LINES:
            violations.append(f"{f.relative_to(PLUGIN_ROOT)}: {lines} lines > {SKILL_MD_MAX_LINES}")

    # A charter's own size is a NOTE, not a violation (P7.1): it is the lightest of the three
    # layers a dispatch pays for, it was the only one capped, and audit A22 (role_load.py) now bounds the sum
    # of all of them. Printed, never failed - the same verdict the audit gives.
    agents_dir = PLUGIN_ROOT / "agents"
    oversized = []
    for f in _sorted_paths(agents_dir.glob("*.md")) if agents_dir.exists() else []:
        size = content_bytes(f)
        if size > AGENT_MD_MAX_BYTES:
            oversized.append(f"{f.relative_to(PLUGIN_ROOT)}: {size} bytes "
                             f"(over the old {AGENT_MD_MAX_BYTES} per-file cap; audit A22 bounds "
                             "the whole start load)")

    # The reference cap exists because a reference is INJECTED: it bounds what one role is
    # handed. A source carrying role markers is never injected whole (contract_slices.findings
    # refuses that), so what it costs a role is its slice — that is what this cap judges, while
    # the subject itself stays one file with one owner (audit A21). The total a role pays is
    # still A22's business (role_load.py, in tokens).
    import contract_slices
    refs_dir = PLUGIN_ROOT / "references"
    for f in _sorted_paths(refs_dir.glob("*.md")) if refs_dir.exists() else []:
        size = content_bytes(f)
        if contract_slices.marked(f.read_text(encoding="utf-8", errors="replace")):
            continue
        if size > REFERENCE_MD_MAX_BYTES:
            violations.append(f"{f.relative_to(PLUGIN_ROOT)}: {size} bytes > {REFERENCE_MD_MAX_BYTES}")
    slices_dir = refs_dir / "slices"
    for f in _sorted_paths(slices_dir.rglob("*.md")) if slices_dir.exists() else []:
        size = content_bytes(f)
        if size > REFERENCE_MD_MAX_BYTES:
            violations.append(f"{f.relative_to(PLUGIN_ROOT)}: {size} bytes > {REFERENCE_MD_MAX_BYTES} "
                              "(a generated slice: move the section to the roles that act on it)")

    for note in oversized:
        print("  limits (info): " + note)
    ok = check("limits: SKILL.md / agents / references within size caps", not violations,
               f"{len(violations)} file(s)")
    for v in violations[:30]:
        print(f"  - {v}")
    # A rule a role must keep is a row of design/role-rules.json; trimming a file to its cap must not take one out silently.
    import role_rules
    lost = role_rules.findings(PLUGIN_ROOT)
    ok_rules = check("limits: every mandatory role rule of design/role-rules.json holds in its carrier", not lost,
                     f"{len(lost)} finding(s)")
    for line in lost:
        print(f"  - {line}")
    return ok and ok_rules


# --- --hooks / --tests ----------------------------------------------------------------------

# Four, because the analysis of 24.09 scanned all 151 test files for what they share: none
# writes to the user's home or into the package, none sets git config --global, none uses a
# fixed %TEMP% name, and each file is its own process, so os.environ writes and use_project()
# cannot collide. CPU and %TEMP% capacity are the only shared resources, and four workers on
# an 8-CPU box leaves room for the other selftests that run on the same machine.
TEST_WORKERS = 4


# "Ran nothing" (TR2-12): a test file is judged by its exit code, and a pytest-style file (functions
# `test_*`, no entry) run as a script defines functions, exits 0 and executes no check. A script-style
# file prints its tally (`finish()` / `N/N ok`), a pytest-style file with the entry prints pytest's
# summary. The evidence of execution is DATA in the output: a tally `N/M ok` with M > 0, a pytest summary
# with at least one passed or failed, or unittest's `Ran N tests`. A 0/0 tally, a summary of skips only and
# any other output (a print at import) are not evidence. The definitions are read from the parsed source
# (an `ast` walk), so a `def test_x():` inside a string is not a test; a working script that calls its own
# `test_a()` by name and prints no tally is a stated limit (it reads as ran nothing). pytest exit 5 (nothing
# collected) is already non-zero. The door is a script entry in the file.
RAN_NOTHING_TEXT = "ran nothing: add a script entry"
_TALLY = re.compile(r"(\d+)/(\d+) ok ===")
_PYTEST_SUMMARY = re.compile(r"\b(\d+) (?:passed|failed)\b")
_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests?\b", re.MULTILINE)


def defines_tests(source: str) -> bool:
    """True when the parsed source defines a function named `test_*` (any depth, async too)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
               for n in ast.walk(tree))


def executed_checks(text: str) -> bool:
    """True when the output carries evidence that at least one check ran."""
    if any(int(m.group(2)) > 0 for m in _TALLY.finditer(text)):
        return True
    if any(int(m.group(1)) > 0 for m in _PYTEST_SUMMARY.finditer(text)):
        return True
    return any(int(m.group(1)) > 0 for m in _UNITTEST_RAN.finditer(text))


def ran_nothing(path: Path, stdout: str, stderr: str) -> bool:
    """True when the file exited 0, defines `test_*` functions and its output shows no check executed."""
    if executed_checks(stdout + "\n" + stderr):
        return False
    return defines_tests(path.read_text(encoding="utf-8", errors="replace"))


def _crash_line(p) -> str:
    """The exception line that closes the last traceback in a child's output (200 chars), or '' when there is none."""
    for text in (p.stderr or "", p.stdout or ""):
        rows = text.splitlines()
        marks = [i for i, row in enumerate(rows) if row.startswith("Traceback (most recent call last)")]
        if marks:
            tail = [row for row in rows[marks[-1] + 1:] if row.strip() and not row[0].isspace()]
            return tail[-1][:200] if tail else ""
    return ""


def _test_outcome(path: Path) -> tuple[Path, bool, str, float]:
    # A file that never returns is one red file, not a traceback out of the middle of the
    # run: with workers, the exception would surface at future.result() and take the summary
    # and the other files' result lines with it.
    start = time.perf_counter()
    try:
        p = run_subprocess([str(path)], timeout=TEST_TIMEOUTS.get(path.name, 300))
    except subprocess.TimeoutExpired as exc:
        return path, False, f"timed out after {exc.timeout:.0f}s", time.perf_counter() - start
    elapsed = time.perf_counter() - start
    lines = (p.stdout or p.stderr).strip().splitlines()
    # The failing CHECKS, not only the summary line. A file that fails under the parallel
    # runner and passes alone is the shape of `test_stand_lease` (FR-31), and with the summary
    # alone the only way to learn which check broke was to reproduce the load — twice this
    # cost an hour. Three lines here answer it from the run that actually failed.
    failed = [line for line in lines if line.startswith("FAIL")]
    TEST_CAPTURE[path.name] = {"fails": failed, "crash": _crash_line(p)}
    detail = f"exit {p.returncode}" + (f" | {lines[-1][:200]}" if lines else "")
    if failed:
        detail += "".join("\n      " + line[:300] for line in failed[:3])
    ok = p.returncode == 0
    if ok and ran_nothing(path, p.stdout or "", p.stderr or ""):
        return path, False, detail + " | " + RAN_NOTHING_TEXT, elapsed
    return path, ok, detail, elapsed


def _report_test(outcome: tuple[Path, bool, str, float]) -> bool:
    path, ok, detail, elapsed = outcome
    rel = str(path.relative_to(PLUGIN_ROOT))
    TEST_DURATIONS[rel] = elapsed
    return check(f"tests: {rel}", ok, detail, seconds=elapsed)


def _run_test_file(path: Path) -> bool:
    return _report_test(_test_outcome(path))


# --- --wiring ---------------------------------------------------------------------------

def cmd_wiring() -> bool:
    """What onboarding generates and what roles are injected with are two lists, and in 0.1.0
    they drifted apart in both directions: aspect-profile.md was injected but never generated
    (audit A9 fired in the pilot project), product-passport.md was generated but injected to
    nobody and quietly rotted. Tie the two lists together."""
    import json as _json
    inject_map = PLUGIN_ROOT / "references" / "inject-map.json"
    generator = PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases" / "p4-generate.md"
    if not inject_map.exists() or not generator.exists():
        return check("wiring: inject-map.json and p4-generate.md exist", False,
                     "one of the two files is missing")

    data = _json.loads(inject_map.read_text(encoding="utf-8"))
    entries = list(data.get("common") or [])
    for role_files in (data.get("roles") or {}).values():
        entries.extend(role_files)
    names = {e.split("/")[-1] for e in entries if isinstance(e, str) and e.startswith("project:")}

    text = generator.read_text(encoding="utf-8")
    missing = sorted(n for n in names if n not in text)
    return check("wiring: every injected project: file is generated by onboarding", not missing,
                 "p4-generate.md never writes: " + ", ".join(missing))


def cmd_slices() -> bool:
    import contract_slices
    problems = contract_slices.findings(PLUGIN_ROOT)
    ok = check("slices: every role slice is present and matches its source", not problems,
               f"{len(problems)} problem(s) — run `python -B scripts/contract_slices.py --write`")
    for line in problems[:10]:
        print(f"  - {line}")
    return ok


def cmd_hooks() -> bool:
    wiring_test = TESTS_DIR / "test_hooks_wiring.py"
    if not wiring_test.exists():
        return check("hooks: scripts/tests/test_hooks_wiring.py exists", False, "not found")
    return _run_test_file(wiring_test)


CONTRACT_TESTS = ("test_null_outcomes.py", "test_gate_registry.py", "test_stage_joints.py")


def cmd_contracts() -> bool:
    """The registry walks: the null-outcome walk, the gate registry (audit A26) and the stage joints (F6-51), each on its own."""
    ok = True
    for name in CONTRACT_TESTS:
        walk_test = TESTS_DIR / name
        if not walk_test.exists():
            ok = check(f"contracts: scripts/tests/{name} exists", False, "not found") and ok
            continue
        ok = _run_test_file(walk_test) and ok
    return ok


# --- test layers (scripts/tests/test-layers.json) ----------------------------------------------
# Which package test files run in the canon (keep) and which sit in quarantine. The file is DATA (FR-13), read only
# by test_layers(); this runner filters by it and judges nothing about a file's content. Absent = today's behaviour.
LAYER_WORDS = ("scenario", "data_join", "table", "register", "gate_named", "detector")
_TEST_FILE_NAME = re.compile(r"test_[A-Za-z0-9_]+\.py")
_TEST_NAME_IN_TEXT = re.compile(r"test_[a-z0-9_]+\.py")
# A fixture whose owner test is named by the fixture's place, not by its text (a ratchet fixture's owner) is a row of
# the "fixture_owners" section of test-layers.json (fixture file -> owning test file): data, FR-13.


class TestLayersError(ValueError):
    """test-layers.json is malformed; the message is the one sentence main() prints."""


def layers_problems(raw, tests_dir: Path) -> list[str]:
    """What is wrong with the parsed layers file, one sentence each; [] when its shape is right."""
    if not isinstance(raw, dict):
        return ["the top level is not a JSON object; expected an object with keep, quarantine, pin_holds, cohorts"]
    layers = raw.get("layers", list(LAYER_WORDS))
    if not (isinstance(layers, list) and all(isinstance(w, str) for w in layers)):
        return ['"layers" must be a list of layer words']
    for key in ("keep", "quarantine", "pin_holds", "cohorts"):
        if not isinstance(raw.get(key, {}), dict):
            return [f'"{key}" must be an object keyed by test file name']
    owners = raw.get("fixture_owners", {})
    if not (isinstance(owners, dict) and all(isinstance(k, str) and isinstance(v, str) and _TEST_FILE_NAME.fullmatch(v)
                                             for k, v in owners.items())):
        return ['"fixture_owners" must be an object mapping a fixture file name to its owning test_*.py file']
    if not isinstance(raw.get("enforce_listing", False), bool):
        return ['"enforce_listing" must be true or false']
    keep, quarantine = raw.get("keep", {}), raw.get("quarantine", {})
    pins, cohorts = raw.get("pin_holds", {}), raw.get("cohorts", {})
    out: list[str] = []
    for section, rows in (("keep", keep), ("quarantine", quarantine), ("pin_holds", pins)):
        out += [f'"{section}" key {n!r} is not a bare test file name; expected test_*.py with no folder'
                for n in rows if not _TEST_FILE_NAME.fullmatch(n)]
    out += [f"{n} is in both keep and quarantine; expected it in one section" for n in sorted(set(keep) & set(quarantine))]
    for name, row in keep.items():
        if not isinstance(row, dict):
            out.append(f"keep row {name} must be an object with layer and why")
            continue
        if row.get("layer") not in layers:
            out.append(f"keep row {name}: layer {row.get('layer')!r} is not one of {', '.join(layers)}")
        if not (isinstance(row.get("why"), str) and row["why"].strip()):
            out.append(f"keep row {name}: why is empty; expected one line saying what the file protects")
        if row.get("layer") == "detector":
            if not (isinstance(row.get("named_by"), list) and row["named_by"]):
                out.append(f"keep row {name}: a detector needs named_by, the carriers that name it")
            if "replaced_by" not in row:
                out.append(f"keep row {name}: a detector needs the key replaced_by (null until replaced)")
    for name, row in quarantine.items():
        if not isinstance(row, dict):
            out.append(f"quarantine row {name} must be an object with cohort, entered, release_at_entry")
            continue
        out += [f"quarantine row {name}: {k} is missing; expected a non-empty value"
                for k in ("cohort", "entered", "release_at_entry") if not row.get(k)]
        if row.get("cohort") and not (isinstance(row["cohort"], str) and row["cohort"] in cohorts):
            out.append(f"quarantine row {name}: cohort {row['cohort']!r} is not in cohorts")
    out += [f"pin_holds names {n}, which is not in scripts/tests/; expected an existing test file (restore it, or remove "
            "the pin_holds row)" for n in pins if _TEST_FILE_NAME.fullmatch(n) and not (tests_dir / n).is_file()]
    out += [f"quarantine row {n}: seconds must be a number, got {row['seconds']!r}"
            for n, row in quarantine.items() if isinstance(row, dict) and "seconds" in row
            and (isinstance(row["seconds"], bool) or not isinstance(row["seconds"], (int, float)))]
    return out


def test_layers(path: Path | None = None) -> dict:
    """The one reader of scripts/tests/test-layers.json. Absent: the world before the file exists (`absent: True`,
    nothing filtered). Malformed or a form `layers_problems` refuses: TestLayersError, one sentence."""
    path = path or TESTS_DIR / "test-layers.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"keep": {}, "quarantine": {}, "pin_holds": {}, "cohorts": {}, "fixture_owners": {},
                "enforce_listing": False, "absent": True}
    except (OSError, ValueError) as exc:
        raise TestLayersError(f"{path}: cannot be read as JSON ({' '.join(str(exc).split())}); expected an object "
                              "with keep, quarantine, pin_holds, cohorts") from None
    problems = layers_problems(raw, path.parent)
    if problems:
        raise TestLayersError(f"{path}: {problems[0]}")
    return {"keep": dict(raw.get("keep", {})), "quarantine": dict(raw.get("quarantine", {})),
            "pin_holds": dict(raw.get("pin_holds", {})), "cohorts": dict(raw.get("cohorts", {})),
            "fixture_owners": dict(raw.get("fixture_owners", {})),
            "enforce_listing": raw.get("enforce_listing", False), "layers": list(raw.get("layers", LAYER_WORDS)),
            "story_coverage_required": list(raw.get("story_coverage_required", [])), "absent": False}


_PROOF_IN_BACKTICKS = re.compile(r"`(test_[a-z0-9_]+\.py)`")
# Carriers read as PROSE (a name anywhere in the text counts); the structured ones are read by their field below.
_PROSE_CARRIERS = ("scripts/install_smoke.py", "design/architecture.md", "design/factory-rules.md")


def _carrier_text(rel: str) -> str:
    carrier = PLUGIN_ROOT / rel
    return carrier.read_text(encoding="utf-8", errors="replace") if carrier.is_file() else ""


def _field_names(rows, *path) -> set[str]:
    """The test_*.py names in the string found at `path` of each row of a JSON carrier; another shape names nothing."""
    out: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        for key in path:
            row = row.get(key) if isinstance(row, dict) else None
        if isinstance(row, str):
            out.update(_TEST_NAME_IN_TEXT.findall(row))
    return out


def _json_carrier(rel: str) -> dict:
    try:
        data = json.loads(_carrier_text(rel) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def registry_proof_names(text: str) -> set[str]:
    """The test_*.py names in the `test` field of every row of REGISTRY in scripts/refusal_registry.py (read by AST, not
    imported: the FR-57 proof of a refusal). A docstring that mentions a test names nothing."""
    names: set[str] = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return names
    for node in ast.walk(tree):
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0] if isinstance(node, ast.Assign) else None
        if not (isinstance(target, ast.Name) and target.id == "REGISTRY" and node.value is not None):
            continue
        for row in (d for d in ast.walk(node.value) if isinstance(d, ast.Dict)):
            for key, value in zip(row.keys, row.values):
                if isinstance(key, ast.Constant) and key.value == "test":
                    for part in ast.walk(value):
                        if isinstance(part, ast.Constant) and isinstance(part.value, str):
                            names.update(_TEST_NAME_IN_TEXT.findall(part.value))
    return names


def gate_named_files(extra_texts=()) -> set[str]:
    """Test files a carrier of the package names: the selftest contract and hooks walks; by FIELD, gate-registry.json
    `rows[].test`, stage-joints.json `joints[].joint.test`, the REGISTRY `test` field of scripts/refusal_registry.py, the
    owner of a fixture (`fixture_owners` of test-layers.json); as PROSE, install_smoke.py, design/architecture.md,
    design/factory-rules.md and the backticked proofs of design/state-exits.md; plus the names in `extra_texts` (carriers
    outside the package: the forge passes them). Only names present in scripts/tests/ come back."""
    names = set(CONTRACT_TESTS) | {"test_hooks_wiring.py"}
    for text in [*extra_texts, *(_carrier_text(rel) for rel in _PROSE_CARRIERS)]:
        names.update(_TEST_NAME_IN_TEXT.findall(text))
    names.update(_PROOF_IN_BACKTICKS.findall(_carrier_text("design/state-exits.md")))
    names.update(_field_names(_json_carrier("references/gate-registry.json").get("rows"), "test"))
    names.update(_field_names(_json_carrier("references/stage-joints.json").get("joints"), "joint", "test"))
    names.update(registry_proof_names(_carrier_text("scripts/refusal_registry.py")))
    names.update(owner for fixture, owner in test_layers(TESTS_DIR / "test-layers.json")["fixture_owners"].items()
                 if (TESTS_DIR / "fixtures" / fixture).is_file())
    return {n for n in names if (TESTS_DIR / n).is_file()}


_UNLISTED_DOOR = ("add a keep row (layer + why) to scripts/tests/test-layers.json, or put its case as a scenario/table "
                  "row and remove the file (docs/TESTING.md)")


def _listing_ok(layers: dict, selected: list, once: bool) -> bool:
    """The enforce_listing FAIL lines. A file in neither section still runs (it is in `selected`) and is reported;
    the keep-wide lines print once per pipeline (`once`: no shard, or shard 1)."""
    if layers["absent"] or not layers["enforce_listing"]:
        return True
    keep, ok = layers["keep"], True
    if once and not keep:
        ok = check("tests: keep list empty", False, "every file runs; add keep rows to scripts/tests/test-layers.json")
    if once:
        for name in sorted(keep):
            if not (TESTS_DIR / name).is_file():
                ok = check(f"tests: keep row names no file: {name}", False) and ok
    if keep:
        listed = set(keep) | set(layers["quarantine"]) | set(layers["pin_holds"])
        for f in selected:
            if f.name not in listed:
                ok = check(f"tests: unlisted: {f.name} -- {_UNLISTED_DOOR}", False) and ok
    return ok


def _head_sha() -> str:
    sha = os.environ.get("CI_COMMIT_SHA", "").strip()
    if sha:
        return sha
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PLUGIN_ROOT), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else "unknown"


def _package_version() -> str:
    try:
        import install_paths
        return install_paths.plugin_version(PLUGIN_ROOT)
    except (ImportError, ValueError):
        return "unknown"


def _watch_entry(outcome: tuple) -> dict:
    """One file's record: status green|red|timeout|ran_nothing, seconds, FAIL names (50 x 160 chars + `+N more`), crash."""
    _, ok, detail, elapsed = outcome
    status = ("green" if ok else "timeout" if detail.startswith("timed out") else
              "ran_nothing" if RAN_NOTHING_TEXT in detail else "red")
    captured = TEST_CAPTURE.get(outcome[0].name, {"fails": [], "crash": ""})
    fails = [line[5:].strip()[:160] for line in captured["fails"][:50]]
    if len(captured["fails"]) > 50:
        fails.append(f"+{len(captured['fails']) - 50} more")
    return {"status": status, "seconds": round(elapsed, 1), "fails": fails, "crash": captured["crash"][:200]}


def _write_watch(path: str, shard, expected: list, entries: dict) -> None:
    record = {"sha": _head_sha(), "package_version": _package_version(),
              "shard": f"{shard[0]}/{shard[1]}" if shard else "1/1", "expected": expected, "files": entries}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")


_SHARD_FORM = re.compile(r"([0-9]+)/([0-9]+)")


def parse_shard(value: str) -> tuple[int, int] | None:
    """`I/N` with 1 <= I <= N as (I, N); anything else is None (the caller refuses it with the expected form)."""
    match = _SHARD_FORM.fullmatch(value or "")
    if not match:
        return None
    try:
        i, n = int(match.group(1)), int(match.group(2))
    except ValueError:      # a digit string past the interpreter's integer-conversion limit
        return None
    return (i, n) if 1 <= i <= n else None


def _lpt_parts(files, weights: dict, n: int, default: float) -> list[list[Path]]:
    """Longest-processing-time greedy over at most min(n, len(files)) bins (a bin past that count stays empty
    anyway, and an absurd N must not allocate N lists). Files sorted by (-weight, name); a file goes to the bin
    with the least total weight, a tie to the lowest index."""
    def weight(f: Path) -> float:
        secs = weights.get(f.name)
        return float(secs) if secs is not None else default

    bins: list[list[Path]] = [[] for _ in range(min(n, len(files)))]
    totals = [0.0] * len(bins)
    for f in sorted(files, key=lambda p: (-weight(p), p.name)):
        target = totals.index(min(totals))
        bins[target].append(f)
        totals[target] += weight(f)
    return bins


def shard_files(files, weights: dict, n: int, default: float = 0.0) -> list[list[Path]]:
    """Split the test files into `n` shards, pure (no clock, no disk). `weights` maps a file NAME to its measured
    seconds (scripts/slow_tests.json "files"; None or absent = `default`, which cmd_tests sets to half of
    "fast_under_s"). The shards are pairwise disjoint, their union is `files`, and the partition depends only on
    the file list and the weights, so every shard of one pipeline computes the same split. A file is never split."""
    parts = _lpt_parts(list(files), weights, n, default)
    return parts + [[] for _ in range(n - len(parts))]


def _quarantine_branch(quarantine: dict, quarantined: bool) -> tuple[list[Path], dict, str | None]:
    """The quarantine branch of cmd_tests: which files this run takes, their weights, and the line that says so.

    quarantined=True takes only the quarantine rows (weights = each row's "seconds") and the line counts them;
    otherwise it takes every test_*.py that is not a quarantine row, weights are left empty (the caller takes them
    from slow_tests.json), and the line names how many files were not run, or is None when none were."""
    if quarantined:
        files = [TESTS_DIR / name for name in sorted(quarantine)]
        weights = {name: row.get("seconds") for name, row in quarantine.items()}
        return files, weights, f"tests: quarantine: {len(quarantine)} files"
    files = [f for f in _sorted_paths(TESTS_DIR.glob("test_*.py")) if f.name not in quarantine]
    line = (f"tests: quarantine: {len(quarantine)} file(s) not run (scripts/tests/test-layers.json)"
            if quarantine else None)
    return files, {}, line


def cmd_tests(workers: int = TEST_WORKERS, fast: bool = False, shard: tuple[int, int] | None = None,
              quarantined: bool = False, watch_out: str | None = None) -> bool:
    """Every test file as its own process, `workers` of them at a time.

    shard=(I, N) runs only the I-th of N weight-balanced parts of the file list (shard_files); the first line
    printed is the header `selftest shard I/N: K of M test files` that `--slow-tests --from` reads back to check
    that every shard's output was joined. An empty part prints an explicit note and passes (AR-23).

    The result lines stay in file order and the summary stays one summary: the files are
    submitted in order and printed in that same order as each one becomes available, so a
    parallel run and a serial run print the same transcript and a diff of two runs still
    means what it meant. The exit code is unchanged — one red file, exit 1.

    fast=True skips the files scripts/slow_tests.json names (the release run — a plain `--tests`
    or `--fast`'s absence — still covers them). Whether that list has gone stale is no longer
    an INFO line here: `--slow-tests` diffs it against the run (cmd_slow_tests).

    scripts/tests/test-layers.json (test_layers): the "quarantine" rows are filtered out BEFORE sharding and `fast`, so a
    quarantined file is in no shard and no tier; `quarantined=True` runs only them (weights = each row's "seconds") and,
    with `watch_out`, writes the watch record. A file in neither section is never dropped: it runs, and with
    "enforce_listing" it is reported. The file absent = none of this, today's behaviour."""
    layers = test_layers()
    quarantine = layers["quarantine"]
    if not quarantined:
        if not TESTS_DIR.exists():
            if shard:
                print(f"selftest shard {shard[0]}/{shard[1]}: 0 of 0 test files")
            print("tests: scripts/tests/ does not exist yet — nothing to run (explicit note)")
            return True
        if not _sorted_paths(TESTS_DIR.glob("test_*.py")):
            if shard:
                print(f"selftest shard {shard[0]}/{shard[1]}: 0 of 0 test files")
            print("tests: no test_*.py files under scripts/tests/ yet (explicit note)")
            return True
    files, weights, quarantine_line = _quarantine_branch(quarantine, quarantined)
    if shard:
        total = len(files)
        data = slow_tests()
        default = data["thresholds"]["fast_under_s"] / 2
        if not quarantined:
            weights = data["files"]
        # the tested selection, asked for at most `total` shards: a shard past that is empty either way, and an
        # absurd N must not allocate N lists
        parts = shard_files(files, weights, min(shard[1], total), default)
        files = parts[shard[0] - 1] if shard[0] <= len(parts) else []
        print(f"selftest shard {shard[0]}/{shard[1]}: {len(files)} of {total} test files")
    if quarantine_line:
        print(quarantine_line)
    entries: dict = {}
    expected = [f.name for f in files]
    listing_ok = quarantined or _listing_ok(layers, files, shard is None or shard[0] == 1)
    if shard and not files:
        ok = check(f"tests: shard {shard[0]}/{shard[1]}: 0 test files (explicit note)", True)
        if quarantined and watch_out:
            _write_watch(watch_out, shard, expected, entries)
        return ok and listing_ok
    if quarantined and not files:
        if watch_out:
            _write_watch(watch_out, shard, expected, entries)
        return True
    if quarantined:
        runnable = [f for f in files if f.is_file()]
        for f in files:
            if f not in runnable:
                check(f"tests: quarantine row names no file: {f.name}", False)
                entries[f.name] = {"status": "missing", "seconds": 0.0, "fails": [], "crash": ""}
        ok = True
        pool = ThreadPoolExecutor(max_workers=max(1, workers))
        with pool:
            futures = [(f, pool.submit(_test_outcome, f)) for f in runnable]
            for f, future in futures:
                outcome = future.result()
                ok = _report_test(outcome) and ok
                entries[f.name] = _watch_entry(outcome)
        if watch_out:
            _write_watch(watch_out, shard, expected, {n: entries[n] for n in expected})
        return ok
    skipped = 0
    if fast:
        before = len(files)
        slow = slow_tests()["files"]
        files = [f for f in files if f.name not in slow]
        skipped = before - len(files)

    if workers <= 1:
        ok = listing_ok
        for f in files:
            ok = _run_test_file(f) and ok
    else:
        ok = listing_ok
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # Threads, not processes: every one of them only waits on a subprocess.
            for future in [pool.submit(_test_outcome, f) for f in files]:
                ok = _report_test(future.result()) and ok

    ran = {f.name: TEST_DURATIONS.get(str(f.relative_to(PLUGIN_ROOT))) for f in files}
    timed = [(name, secs) for name, secs in ran.items() if secs is not None]
    if timed:
        slowest = sorted(timed, key=lambda pair: pair[1], reverse=True)[:5]
        print("tests: slowest 5 — " + ", ".join(f"{n} {s:.1f}s" for n, s in slowest))

    if fast:
        print(f"tests: fast tier: {skipped} file(s) skipped (the release run covers them)")
    return ok


# --- --slow-tests -----------------------------------------------------------------------------

DEFAULT_MAX_DRIFT = 5


class SlowTestsError(ValueError):
    """scripts/slow_tests.json is absent or malformed; the message is the one line main() prints."""


def _is_seconds(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _slow_tests_problem(raw) -> str | None:
    """What is wrong with the parsed data file, as one phrase; None when its shape is right."""
    if not isinstance(raw, dict):
        return "the top level is not a JSON object"
    thresholds = raw.get("thresholds")
    if (not isinstance(thresholds, dict) or not _is_seconds(thresholds.get("slow_over_s"))
            or not _is_seconds(thresholds.get("fast_under_s"))):
        return '"thresholds" must be an object with numeric "slow_over_s" and "fast_under_s"'
    if "max_drift" in raw and (not isinstance(raw["max_drift"], int)
                               or isinstance(raw["max_drift"], bool) or raw["max_drift"] < 0):
        return '"max_drift" must be a whole number, 0 or more'
    for key in ("measured_on", "source"):
        if key in raw and not isinstance(raw[key], str):
            return f'"{key}" must be a string'
    files = raw.get("files")
    if not isinstance(files, dict):
        return '"files" must be an object: test file name -> measured seconds or null'
    for name, secs in files.items():
        if not name or name != Path(name).name:
            return f'"files" key {name!r} is not a test file name'
        if secs is not None and not _is_seconds(secs):
            return f'"files" value for {name} must be seconds (a number) or null'
    return None


def slow_tests(path: Path | None = None) -> dict:
    """The one reader of scripts/slow_tests.json (FR-13: a closed list lives in a data file).

    What the list is for: `--fast` skips the files it names, so the commit-time tier stays near
    90 s; the release run (flagless, or `--tests`) still runs them all. A file over `slow_over_s`
    belongs on the list, a listed file under `fast_under_s` does not, and between the two it keeps
    whatever it has. `--slow-tests` diffs the file against a measurement and `--update` rewrites it
    (so nobody edits it by hand, the way the old tuple was edited until it drifted by 18 and 14
    files on the nightly of 15.10). The seconds are the duration the measuring run printed for the
    file: the nightly package-full runs `--jobs 4` on the CI image, so the thresholds are judged
    in-parallel on that machine, not single-file; the numbers from before 16.10 were measured
    alone, on loaded developer machines (source "hand"). A file near a threshold can flip between
    two runs, which is what "max_drift" absorbs. TEST_TIMEOUTS, in this module, is still the ONE
    place that decides a test file's timeout: being listed here changes only the tier.

    Shape: {"measured_on": "<date>", "source": "<pipeline/job id | file | hand>",
    "thresholds": {"slow_over_s": 10, "fast_under_s": 5}, "max_drift": 5,
    "files": {"<test file name>": <seconds | null>}}. Unknown keys are ignored. An absent
    "max_drift" is 5 and says so in "notes". Returns the same keys, thresholds and max_drift
    filled, plus "notes". The file absent or malformed raises SlowTestsError - there is no
    fallback list, because a silent empty list would make `--fast` run everything."""
    path = path or SLOW_TESTS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise SlowTestsError(f"{path}: not found - the slow-test list is a data file next to "
                             "selftest.py") from None
    except (OSError, ValueError) as exc:     # json and unicode decode errors are ValueErrors
        raise SlowTestsError(f"{path}: cannot be read as JSON ({' '.join(str(exc).split())})") from None
    problem = _slow_tests_problem(raw)
    if problem:
        raise SlowTestsError(f"{path}: {problem}")
    notes = []
    if "max_drift" not in raw:
        notes.append(f"max_drift is absent in {path.name}, using {DEFAULT_MAX_DRIFT}")
    return {
        "measured_on": raw.get("measured_on", ""),
        "source": raw.get("source", ""),
        "thresholds": {"slow_over_s": raw["thresholds"]["slow_over_s"],
                       "fast_under_s": raw["thresholds"]["fast_under_s"]},
        "max_drift": raw.get("max_drift", DEFAULT_MAX_DRIFT),
        "files": dict(raw["files"]),
        "notes": notes,
    }


# The per-file line cmd_tests prints through check(): `PASS tests: scripts/tests/<file>  <s>s`, FAIL the
# same (a failing file's detail follows the seconds). The seconds are required to END in `s`, so a
# saved output cut in the middle of a line parses as no line at all. A path outside scripts/tests/
# (a fixture, a nested folder) is no test file. Either slash: a Windows run prints backslashes.
_DURATION_LINE = re.compile(
    r"^(?:PASS|FAIL) tests: scripts[\\/]tests[\\/]([^\\/\s]+\.py)\s+(\d+(?:\.\d+)?)s(?:\s|$)")


def parse_durations(text: str) -> dict[str, float]:
    """test file name -> seconds, from a saved selftest output. A file that appears twice in one
    output (a retry) keeps its LAST duration; a line that is not a complete duration line is skipped."""
    found: dict[str, float] = {}
    for line in text.splitlines():
        match = _DURATION_LINE.match(line)
        if match:
            found[match.group(1)] = float(match.group(2))
    return found


_SHARD_HEADER = re.compile(r"^selftest shard ([0-9]+)/([0-9]+): ", re.MULTILINE)


def shard_join_problem(text: str) -> str | None:
    """None when the saved output holds no shard header (a whole run, today's behaviour) or holds exactly the
    shards 1..N of one N, each once. Otherwise the one stderr line naming what is wrong (AR-28: a missing shard
    output must never read as a measurement of an unchanged list)."""
    found = [(int(i), int(n)) for i, n in _SHARD_HEADER.findall(text)]
    if not found:
        return None
    totals = sorted({n for _, n in found})
    seen = [i for i, _ in found]
    mixed = len(totals) > 1
    expected = set(range(1, totals[0] + 1))
    missing = sorted(expected - set(seen)) if not mixed else []
    repeated = sorted({i for i in seen if seen.count(i) > 1})
    outside = sorted(set(seen) - expected) if not mixed else []
    if not (mixed or missing or repeated or outside):
        return None
    holds = ", ".join(str(i) for i in sorted(seen))
    return (f"slow tests: the saved output holds shards {holds} of {', '.join(str(n) for n in totals)}; "
            f"missing {missing or 'none'} / repeated {repeated or 'none'} / "
            f"mixed totals {'yes' if mixed else 'no'}"
            f"{f' / outside 1..N {outside}' if outside else ''}"
            " -- concatenate every shard's output once")


def this_run_durations() -> dict[str, float]:
    return {Path(rel).name: secs for rel, secs in TEST_DURATIONS.items()}


def slow_tests_diff(data: dict, measured: dict, tests_dir: Path | None = None) -> dict:
    """The list against a measurement. A file that is not on disk is ignored when it is only
    measured (a stale artifact) and reported as `missing` when it is listed. A file at exactly a
    threshold is unchanged; a listed file nobody measured is unchanged (nothing says it moved). A quarantined
    file (test-layers.json) is not in the canon's list, so it is neither added, removed, missing nor counted."""
    tests_dir = tests_dir or TESTS_DIR
    over = data["thresholds"]["slow_over_s"]
    under = data["thresholds"]["fast_under_s"]
    benched = set(test_layers(tests_dir / "test-layers.json")["quarantine"])
    listed = {n: s for n, s in data["files"].items() if n not in benched}
    measured = {n: s for n, s in measured.items() if n not in benched}

    def on_disk(name: str) -> bool:
        return (tests_dir / name).is_file()

    added = [(n, s) for n, s in sorted(measured.items()) if s > over and n not in listed and on_disk(n)]
    removed = [(n, measured[n]) for n in sorted(listed) if n in measured and measured[n] < under and on_disk(n)]
    missing = [n for n in sorted(listed) if not on_disk(n)]
    known = {n for n in set(measured) | set(listed) if on_disk(n)}
    return {"added": added, "removed": removed, "missing": missing,
            "unchanged": len(known) - len(added) - len(removed),
            "changes": len(added) + len(removed) + len(missing)}


def slow_tests_updated(data: dict, measured: dict, measured_on: str, source: str,
                       tests_dir: Path | None = None) -> dict:
    """The data file as the measurement says it should be: every measured file over the slow
    threshold in, every listed file under the fast threshold out, a listed file gone from disk out,
    seconds refreshed for every listed file that was measured. Thresholds and max_drift carry over."""
    tests_dir = tests_dir or TESTS_DIR
    over = data["thresholds"]["slow_over_s"]
    under = data["thresholds"]["fast_under_s"]
    benched = set(test_layers(tests_dir / "test-layers.json")["quarantine"])
    files: dict = {}
    for name, secs in data["files"].items():
        if name in benched or not (tests_dir / name).is_file():
            continue
        if name not in measured:
            files[name] = secs
        elif measured[name] >= under:
            files[name] = round(measured[name], 1)
    for name, secs in measured.items():
        if secs > over and name not in benched and (tests_dir / name).is_file():
            files[name] = round(secs, 1)
    return {"measured_on": measured_on, "source": source, "thresholds": dict(data["thresholds"]),
            "max_drift": data["max_drift"], "files": files}


def render_slow_tests(data: dict) -> str:
    body = {"measured_on": data["measured_on"], "source": data["source"],
            "thresholds": data["thresholds"], "max_drift": data["max_drift"],
            "files": {name: data["files"][name] for name in sorted(data["files"])}}
    return json.dumps(body, indent=2) + "\n"


def cmd_slow_tests(from_file: str | None = None, update: bool = False,
                   today: str | None = None) -> int:
    """Print the diff of scripts/slow_tests.json against a measurement; return the exit code.

    The measurement is the saved output named by `from_file`, else this process's own --tests run
    (TEST_DURATIONS). 0 = within "max_drift" changes (or --update, which rewrites the file), 1 =
    more changes than the limit, 2 = nothing to measure (no file, no duration lines, no --tests in
    this call): an empty measurement is never read as "nothing changed" and never written."""
    data = slow_tests()
    if from_file:
        try:
            text = Path(from_file).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            print(f"slow tests: cannot read {from_file}: {exc.strerror or exc}", file=sys.stderr)
            return 2
        problem = shard_join_problem(text)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        measured, label = parse_durations(text), Path(from_file).name
    else:
        measured, label = this_run_durations(), "local run"
    if not measured:
        print(f"slow tests: no test durations in {label} - pass --from <selftest.txt> (a saved output "
              "with `PASS tests: scripts/tests/<file>  <s>s` lines) or put --tests in this call",
              file=sys.stderr)
        return 2
    diff = slow_tests_diff(data, measured)
    for note in data["notes"]:
        print(f"slow tests: note: {note}")
    for name, secs in diff["added"]:
        print(f"+ {name} {secs:.1f}s")
    for name, secs in diff["removed"]:
        print(f"- {name} {secs:.1f}s")
    for name in diff["missing"]:
        print(f"- {name} (missing)")
    print(f"= {diff['unchanged']} unchanged")
    limit = data["max_drift"]
    print(f"slow tests: {diff['changes']} change(s) (limit {limit})")
    if update:
        new = slow_tests_updated(data, measured, today or date.today().isoformat(), label)
        SLOW_TESTS_FILE.write_text(render_slow_tests(new), encoding="utf-8", newline="\n")
        print(f"slow tests: {SLOW_TESTS_FILE.name} rewritten from {label} ({len(new['files'])} file(s))")
        return 0
    if diff["changes"] > limit:
        print("slow tests: over the limit - run `python -B scripts/selftest.py --slow-tests --from "
              "<selftest.txt> --update` and commit scripts/slow_tests.json")
        return 1
    return 0


# --- --hygiene -------------------------------------------------------------------------------

def cmd_homes() -> bool:
    """Where a document lives is decided by who loads it.

    `references/` is the definition layer: injected to roles, capped per file because it is
    somebody's context, and inside the package fingerprint a dispatch is bound to. `design/` is read
    only by whoever changes the factory. Eighteen documents used to pay all three prices for
    nothing — three of them sat within 100 bytes of the cap, so the next paragraph anyone wrote
    would have broken the build over a limit that protects a role from a file no role receives.

    Held in both directions, because either drift is silent: a reference nothing consumes belongs
    in `design/`, and a document in `design/` that something starts loading must come back.
    """
    import contract_slices
    inject_path = PLUGIN_ROOT / "references" / "inject-map.json"
    inject = inject_path.read_text(encoding="utf-8", errors="replace") if inject_path.is_file() else ""
    consumers = []
    for pattern in ("scripts/*.py", "hooks/*", "skills/**/*.md", "agents/*.md",
                    "references/*.md", "references/*.json", "references/templates/*",
                    "handoffs/*"):
        for path in PLUGIN_ROOT.glob(pattern):
            if path.is_file():
                try:
                    consumers.append((path, path.read_text(encoding="utf-8", errors="replace")))
                except Exception:
                    continue

    def named_by_a_consumer(name: str, itself: Path) -> bool:
        return any(name in body for path, body in consumers if path != itself)

    orphans, stowaways = [], []
    refs_dir = PLUGIN_ROOT / "references"
    for path in _sorted_paths(refs_dir.glob("*.md")) if refs_dir.exists() else []:
        if path.name == "README.md":
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        if path.name in inject or contract_slices.marked(body) or named_by_a_consumer(path.name, path):
            continue
        orphans.append(f"references/{path.name}: nothing loads it — it belongs in design/")
    design_dir = PLUGIN_ROOT / "design"
    for path in _sorted_paths(design_dir.glob("*.md")) if design_dir.exists() else []:
        body = path.read_text(encoding="utf-8", errors="replace")
        if path.name in inject:
            stowaways.append(f"design/{path.name}: named by inject-map.json — a role is handed it, "
                             "so it belongs in references/")
        elif contract_slices.marked(body):
            stowaways.append(f"design/{path.name}: carries role markers — it is sliced to a role, "
                             "so it belongs in references/")
    problems = orphans + stowaways
    ok = check("homes: a document lives where its reader is", not problems, f"{len(problems)} file(s)")
    for line in problems[:20]:
        print("  - " + line)
    return ok


def cmd_hygiene() -> bool:
    """What lies in the package directory is what ships. A marketplace whose source is a local
    directory copies the tree as it is on disk — .gitignore is a git rule, not a copy rule —
    so a test run's leftover is installed for the next user along with the factory. An EMPTY
    leftover directory is the worst of them: git cannot see one at all, so `git status` stays
    clean, the review never mentions it, and it still gets copied. `git ls-files` is the only
    statement of what package content is; an installed copy has no clone to ask and says so."""
    # Bytecode caches are derived files and nothing is lost by deleting them, so this check
    # removes them instead of reporting them: `python scripts/tests/test_x.py` is the way the
    # test files say to run one, and that alone leaves a cache the next install would carry.
    removed = 0
    for cache in list(PLUGIN_ROOT.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
        removed += 1
    for stray in list(PLUGIN_ROOT.rglob("*.py[co]")):
        stray.unlink(missing_ok=True)
        removed += 1
    if removed:
        print(f"hygiene: removed {removed} bytecode cache(s) — derived files, and a "
              "local-directory marketplace would have installed them (explicit note)")

    listing = subprocess.run(["git", "ls-files", "-z"], cwd=str(PLUGIN_ROOT), capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
    tracked_paths = [p for p in (listing.stdout or "").split("\0") if p]
    if listing.returncode != 0 or not tracked_paths:
        print("hygiene: no git clone here — nothing states what package content is (explicit note)")
        return True

    tracked = {PLUGIN_ROOT / p for p in tracked_paths}
    carriers = {parent for path in tracked for parent in path.parents}
    extra: list = []

    def walk(directory: Path) -> None:
        for entry in _sorted_paths(directory.iterdir()):
            if entry.name == ".git" or entry in tracked:
                continue
            if entry.is_dir() and entry in carriers:
                walk(entry)
            else:
                extra.append(entry)

    walk(PLUGIN_ROOT)
    names = [e.relative_to(PLUGIN_ROOT).as_posix() + ("/" if e.is_dir() else "") for e in extra]
    return check("hygiene: the package directory carries only package content", not names,
                 "a local-directory marketplace would install: " + ", ".join(names[:10])
                 + (f" (+{len(names) - 10} more)" if len(names) > 10 else ""))


# --- --ping ---------------------------------------------------------------------------------

def cmd_ping() -> bool:
    print("pong")
    return True


def main() -> None:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="qa-factory self-test")
    ap.add_argument("--selftest-scripts", action="store_true")
    ap.add_argument("--roots", action="store_true")
    ap.add_argument("--lang", action="store_true")
    ap.add_argument("--limits", action="store_true")
    ap.add_argument("--wiring", action="store_true")
    ap.add_argument("--slices", action="store_true")
    ap.add_argument("--hooks", action="store_true")
    ap.add_argument("--contracts", action="store_true")
    ap.add_argument("--tests", action="store_true")
    ap.add_argument("--jobs", type=int, default=TEST_WORKERS,
                    help=f"--tests workers (default {TEST_WORKERS}; 1 = serial)")
    ap.add_argument("--homes", action="store_true")
    ap.add_argument("--hygiene", action="store_true")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--fast", action="store_true",
                    help="limits + lang + slices + wiring + tests (skipping the files in "
                         "scripts/slow_tests.json) + hygiene — for every commit; the release run "
                         "is the full, flagless one")
    ap.add_argument("--slow-tests", action="store_true",
                    help="diff scripts/slow_tests.json against a measurement (this call's --tests "
                         "run, or --from); exit 1 when more than max_drift files differ")
    ap.add_argument("--from", dest="from_file", metavar="SELFTEST_TXT",
                    help="--slow-tests: measure from this saved selftest output instead of this call's run")
    ap.add_argument("--update", action="store_true",
                    help="--slow-tests: rewrite scripts/slow_tests.json from the measurement")
    ap.add_argument("--shard", metavar="I/N",
                    help="--tests (or a flagless run): run only the I-th of N weight-balanced parts of the "
                         "test files; shard 1 also runs every other check, the rest run tests + hygiene")
    ap.add_argument("--quarantined", action="store_true",
                    help="run ONLY the quarantine rows of scripts/tests/test-layers.json (implies --tests); a "
                         "measurement: exit 0 whatever the files do, 2 when the runner fails")
    ap.add_argument("--watch-out", metavar="PATH",
                    help="--quarantined: write the watch record (JSON) to PATH, creating its folder")
    args = ap.parse_args()
    if (args.from_file or args.update) and not args.slow_tests:
        ap.error("--from and --update belong to --slow-tests")
    if args.watch_out and not args.quarantined:
        ap.error("--watch-out belongs to --quarantined: it writes the record of a quarantine run")
    if args.quarantined and (args.fast or args.slow_tests):
        ap.error("--quarantined runs only the quarantine rows; it does not combine with "
                 + ("--fast, which is a tier of the canon" if args.fast else
                    "--slow-tests, which measures the canon's whole run"))
    if args.slow_tests and args.fast:
        ap.error("--slow-tests measures a run that includes the slow files; it does not combine with --fast")
    shard = None
    if args.shard is not None:
        shard = parse_shard(args.shard)
        if shard is None:
            ap.error(f"--shard expects I/N with 1 <= I <= N, e.g. 1/2; got {args.shard}")
        if args.fast or args.slow_tests:
            ap.error("--shard splits a full run's test files; --fast is one tier, --slow-tests measures a whole "
                     "run: concatenate the shard outputs and pass --from")

    flags_given = any([args.selftest_scripts, args.roots, args.lang, args.limits,
                       args.wiring, args.slices, args.hooks, args.contracts, args.tests,
                       args.homes, args.hygiene, args.slow_tests, args.quarantined])
    if shard and (flags_given or args.ping) and not (args.tests or args.quarantined):
        ap.error("--shard splits the test files: use it with --tests or with no check flag")
    run_all = not flags_given and not args.ping and not args.fast
    # a flagless sharded run: only shard 1 carries the non-test checks, so each runs once per pipeline
    rest = run_all and (shard is None or shard[0] == 1)

    if args.ping and not any([args.selftest_scripts, args.roots, args.lang, args.limits,
                              args.wiring, args.slices, args.hooks, args.contracts, args.tests,
                              args.hygiene, args.fast, args.slow_tests]):
        cmd_ping()
        sys.exit(0)

    # The slow-test list is read at the START of every run that uses it (the fast tier, any run
    # that includes --tests, --slow-tests): absent or malformed it is one line and exit 2, never a
    # fast tier that quietly runs everything.
    if args.fast or args.tests or args.quarantined or args.slow_tests or run_all:
        try:
            slow_tests()
            test_layers()
        except (SlowTestsError, TestLayersError) as exc:
            print(f"selftest: {exc}", file=sys.stderr)
            sys.exit(2)

    if args.fast:
        ok = True
        ok = cmd_limits() and ok
        ok = cmd_lang() and ok
        ok = cmd_slices() and ok
        ok = cmd_wiring() and ok
        ok = cmd_tests(max(1, args.jobs), fast=True) and ok
        # Last: the checks above are what leave litter behind, so this one has to see the
        # tree they leave, not the tree they started from.
        ok = cmd_hygiene() and ok
        bad = sum(1 for good, _ in RESULTS if not good)
        print(f"\n=== qa-factory selftest (fast): {len(RESULTS) - bad}/{len(RESULTS)} ok ===")
        sys.exit(0 if ok else 1)

    ok = True
    if rest or args.selftest_scripts:
        ok = cmd_selftest_scripts() and ok
    if rest or args.roots:
        ok = cmd_roots() and ok
    if rest or args.lang:
        ok = cmd_lang() and ok
    if rest or args.limits:
        ok = cmd_limits() and ok
    if rest or args.wiring:
        ok = cmd_wiring() and ok
    if rest or args.slices:
        ok = cmd_slices() and ok
    # --hooks only when it is asked for. It runs scripts/tests/test_hooks_wiring.py, and the
    # --tests glob runs that same file again: a full selftest paid 25 s twice for one file's
    # 15 shell launches, and the transcript carried the same result under two names.
    if args.hooks:
        ok = cmd_hooks() and ok
    if args.contracts:
        ok = cmd_contracts() and ok
    if args.quarantined:
        try:
            cmd_tests(max(1, args.jobs), shard=shard, quarantined=True, watch_out=args.watch_out)
        except Exception as exc:    # the runner itself failed (an unwritable --watch-out, say): 2, not a measurement
            print(f"selftest: the quarantine run failed: {' '.join(str(exc).split())}", file=sys.stderr)
            sys.exit(2)
    elif run_all or args.tests:
        ok = cmd_tests(max(1, args.jobs), shard=shard) and ok
    # After --tests, which is what fills this process's durations; its own exit code (1 = more
    # changes than the limit, 2 = nothing to measure) is not a PASS/FAIL line.
    slow_code = cmd_slow_tests(args.from_file, args.update) if args.slow_tests else 0
    # Last: the checks above are what leave litter behind, so this one has to see the tree
    # they leave, not the tree they started from.
    if rest or args.homes:
        ok = cmd_homes() and ok
    if run_all or args.hygiene:
        ok = cmd_hygiene() and ok
    if args.ping:
        ok = cmd_ping() and ok

    if RESULTS or not args.slow_tests:
        bad = sum(1 for good, _ in RESULTS if not good)
        tag = f" (shard {shard[0]}/{shard[1]})" if shard else ""
        print(f"\n=== qa-factory selftest{tag}: {len(RESULTS) - bad}/{len(RESULTS)} ok ===")
    if args.quarantined:
        # a measurement of the quarantine, not a gate: its own result never fails the call, but another check flag
        # given in the same call (--limits, --lang ...) keeps its own verdict
        sys.exit(0 if ok else 1)
    sys.exit(2 if slow_code == 2 else (0 if ok and not slow_code else 1))


if __name__ == "__main__":
    main()
