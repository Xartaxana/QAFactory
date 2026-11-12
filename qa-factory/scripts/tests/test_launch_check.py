"""launch_check.py: why a profile's own test command did not launch (B-193, t-110 R-A1).

One named group of checks per edge of the spec: E1 classify (E1b: a cause confirmed against the
argv), E2 probe (E2b: the collect form per runner, E2c: positional placeholders), E3 --deactivated
(E3b: which PATH entries go), E4 the CLI, E5 the battery, E6 the data file (E6b: doors per
audience), E7 the onboarding text. Nothing here starts a real
pytest or any project command: `run` and `which` are injected (the CLI's exit-2 and
`not found` paths, run as a subprocess, launch nothing either)."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, finish, temp_dir

sys.path.insert(0, str(SCRIPTS))
import launch_check as lc  # noqa: E402

REAL_DATA = PLUGIN_ROOT / "references" / "launch-causes.json"
PARTIAL_KEYS = ("continue_tokens", "partial_exits", "broken_line", "count_line", "stopped_line")
TIMEOUT_KEYS = ("timeout_kill_line", "timeout_failure_message", "timeout_header_line")   # RH2-9: the runner's per-test timeout lines
PARTIAL_FLAG = "--continue-on-collection-errors"
ONBOARDING = PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases" / "p4-generate.md"
ESC = chr(27)
TMP = temp_dir("qa-launch-check-")
LAUNCHER_DOOR = ("`<argv0>` started as `<resolved>` and rejected this project's own options. "
                "The command is the profile's (onboarding's), not your test. Do not edit "
                "qa-factory/config.json. Name `launch: launcher_rejected_arguments` and the "
                "evidence line in your digest, and stop repairing this run. After the profile "
                "is fixed: `--mine \u2026 --again --reason \"profile fixed\"`.")
LAUNCHER_LINE = "pytest: error: unrecognized arguments: --reruns --ui-headless"
CMP1_ONE_TEST = ["pytest", "<test-file>", "--reruns", "2", "--ui-headless"]


# --- fakes -------------------------------------------------------------------------------------

class Run:
    """An injected `run`: records every call, answers what it was told to."""

    def __init__(self, returncode=0, stdout=b"", stderr=b"", raises=None):
        self.returncode, self.stdout, self.stderr, self.raises = returncode, stdout, stderr, raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def which_in(installed):
    """An injected `which`: searches the PATH it is GIVEN, like shutil.which, over a fake disk."""
    seen = []

    def which(cmd, path=None):
        seen.append(path)
        for directory in (path or "").split(os.pathsep):
            candidate = os.path.join(directory, cmd)
            if candidate in installed:
                return candidate
        return None

    which.seen = seen
    return which


def project(profiles=None, **extra):
    root = Path(tempfile.mkdtemp(prefix="qa-lc-\u00e9-", dir=TMP))
    (root / "qa-factory").mkdir()
    (root / "tests").mkdir()
    cfg = {"schema_version": 1, "tests_root": "tests"}
    if profiles is not None:
        cfg["profiles"] = profiles
    cfg.update(extra)
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


def profile(pid="api", one=CMP1_ONE_TEST, cwd=".", collect=None):
    commands = {}
    if one is not None:
        commands["one_test"] = {"argv": list(one), "cwd": cwd, "kind": "test", "scope": "selected"}
    if collect is not None:
        commands["collect"] = {"argv": list(collect), "cwd": cwd, "kind": "collect"}
    return {"profile_id": pid, "commands": commands}


def probe(prof, root, run=None, which=None, env=None, config=None):
    return lc.probe(prof, root, env=env if env is not None else {"PATH": ""},
                    run=run or Run(), which=which or which_in({"pytest"}),
                    config=config if config is not None else {})


def any_placeholder(argv):
    return any(re.search(r"<[^<>]+>", t) for t in argv)


def with_data(content, fn):
    """Run `fn` with the data file pointed at `content` (bytes or dict), then restore."""
    path = TMP / "causes-under-test.json"
    path.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode("utf-8"))
    saved = lc.CAUSES_PATH
    lc.CAUSES_PATH = path
    try:
        return fn()
    finally:
        lc.CAUSES_PATH = saved


def real_data():
    return json.loads(REAL_DATA.read_text(encoding="utf-8"))


def snapshot(root):
    import hashlib
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- E1: classify ------------------------------------------------------------------------------

def e1_classify():
    dep = "ModuleNotFoundError: No module named 'pydantic'"
    # totals decide "did anything run": ANY record, even a collection error, is a run.
    for label, totals in (("tests=1 errors=1 (a collection error)", {"tests": 1, "errors": 1}),
                          ("tests=5", {"tests": 5, "failures": 0}), ("an empty record", {})):
        check_eq(f"E1 a run with totals ({label}) is not classified",
                 lc.classify(2, [dep], totals), {"cause": None})
    check_eq("E1 totals=None and a marker: the cause is named",
             lc.classify(2, [dep], None)["cause"], "dependency_missing")
    check_eq("E1 evidence is the matching line", lc.classify(2, ["a", dep, "b"], None)["evidence"], dep)

    # every cause of the data file, from ITS OWN markers, in the data file's order
    data = real_data()
    ids = [c["id"] for c in data["causes"]]
    check_eq("E1 the closed list, in order", ids, [
        "executable_not_found", "launcher_rejected_arguments", "dependency_missing",
        "collection_error", "unknown"])
    for cause in data["causes"]:
        for marker in cause["markers"]:
            line = f"x {marker}: y"
            if cause["id"] == "executable_not_found":
                line = f"p: {marker}"  # this cause holds only for a line about the program run
            got = lc.classify(2, [line], None, argv=["p", "--reruns", "--foo"])
            want = cause["id"]
            if cause["id"] == "launcher_rejected_arguments":
                # the marker alone names no option: the honest answer is unknown, never a guess
                want = "unknown"
            check_eq(f"E1 marker {marker!r} -> {want}", got["cause"], want)
    seeds = {"executable_not_found": ("command not found", "Command not found",
                                      "is not recognized as an internal or external command"),
             "dependency_missing": ("ModuleNotFoundError", "No module named", "ImportError"),
             "collection_error": ("ERROR collecting", "errors during collection",
                                  "1 error during collection")}
    for cause, markers in seeds.items():
        held = next(c["markers"] for c in data["causes"] if c["id"] == cause)
        check(f"E1 the seed markers of {cause} are in the data file",
              all(m in held for m in markers), f"{markers} vs {held}")

    # first cause in data order wins: over lines, and over one line
    two_lines = ["ModuleNotFoundError: No module named 'x'", LAUNCHER_LINE]
    check_eq("E1 data order beats line order (dependency line first)",
             lc.classify(4, two_lines, None, argv=CMP1_ONE_TEST)["cause"],
             "launcher_rejected_arguments")
    one_line = LAUNCHER_LINE + "; ModuleNotFoundError: No module named 'x'"
    check_eq("E1 data order on a single line matching two causes",
             lc.classify(4, [one_line], None, argv=CMP1_ONE_TEST)["cause"],
             "launcher_rejected_arguments")
    reordered = dict(data, causes=list(reversed(data["causes"])))
    check_eq("E1 the order is the FILE's (a reversed copy picks the other cause)",
             with_data(reordered, lambda: lc.classify(4, two_lines, None, argv=CMP1_ONE_TEST))["cause"],
             "dependency_missing")
    # first matching LINE of the winning cause
    first = lc.classify(2, ["No module named 'a'", "No module named 'b'"], None)["evidence"]
    check_eq("E1 the first line of the winning cause is the evidence", first, "No module named 'a'")

    # case-sensitive, ANSI stripped first
    check_eq("E1 matching is case-sensitive", lc.classify(2, ["modulenotfounderror"], None)["cause"],
             "unknown")
    coloured = f"{ESC}[31mModuleNotFound{ESC}[0mError: No module named{ESC}[1m 'z'{ESC}[0m"
    got = lc.classify(2, [coloured], None)
    check_eq("E1 an ANSI escape inside the marker does not hide it", got["cause"], "dependency_missing")
    check_not_in("E1 the evidence carries no escape byte", ESC, got["evidence"])
    osc = f"{ESC}]0;title{chr(7)}ImportError: cannot import name 'q'"
    check_eq("E1 an OSC sequence is stripped too", lc.classify(2, [osc], None)["evidence"],
             "ImportError: cannot import name 'q'")

    # evidence: clipped to 200 (test AT and BEYOND)
    marker = "No module named"
    for length in (199, 200, 201, 5000):
        line = marker + "x" * (length - len(marker))
        got = lc.classify(2, [line], None)
        check_eq(f"E1 a {length}-char line: cause still named", got["cause"], "dependency_missing")
        check_eq(f"E1 a {length}-char line: evidence is {min(length, 200)} chars",
                 len(got["evidence"]), min(length, 200))
    # a marker past character 200 still matches (the clip is of the answer, not of the search)
    late = "x" * 300 + "No module named 'late'"
    check_eq("E1 a marker beyond char 200 matches", lc.classify(2, [late], None)["cause"],
             "dependency_missing")

    # launcher_rejected_arguments only for an option that is in the profile's argv
    argv = CMP1_ONE_TEST
    got = lc.classify(4, [LAUNCHER_LINE], None, argv=argv)
    check_eq("E1 launcher rejected: an option of the profile is named",
             (got["cause"], got["evidence"]), ("launcher_rejected_arguments", LAUNCHER_LINE))
    got = lc.classify(4, [LAUNCHER_LINE], None, argv=["pytest", "-q"])
    check_eq("E1 launcher rejected: the named options are NOT in the argv -> unknown",
             got["cause"], "unknown")
    check_eq("E1 ... and the evidence line is still given", got["evidence"], LAUNCHER_LINE)
    check_eq("E1 launcher rejected: no argv given -> unknown",
             lc.classify(4, [LAUNCHER_LINE], None)["cause"], "unknown")
    check_eq("E1 launcher rejected: `--opt=value` in the argv counts as the option",
             lc.classify(4, [LAUNCHER_LINE], None, argv=["pytest", "--reruns=2"])["cause"],
             "launcher_rejected_arguments")
    check_eq("E1 launcher rejected: a longer option is not a match (`--rerunsX`)",
             lc.classify(4, [LAUNCHER_LINE], None, argv=["pytest", "--rerunsX"])["cause"], "unknown")
    check_eq("E1 launcher rejected: the click spelling `No such option: --foo`",
             lc.classify(2, ["Error: No such option: --foo"], None, argv=["tool", "--foo"])["cause"],
             "launcher_rejected_arguments")
    check_eq("E1 launcher rejected: numeric argv items are read as strings",
             lc.classify(4, ["unrecognized arguments: -n"], None, argv=["pytest", "-n", 4])["cause"],
             "launcher_rejected_arguments")

    # error direction: toward unknown, never an exception
    for label, lines in (("None", None), ("no lines", []), ("empty lines", ["", "  "]),
                         ("numbers", [1, 2.5, None]), ("a generator", (x for x in ["boom"])),
                         ("not iterable", 42)):
        got = lc.classify(1, lines, None)
        check_eq(f"E1 lines={label}: unknown, no exception", got["cause"], "unknown")
    check_eq("E1 an unmatched output has empty evidence", lc.classify(1, ["rootdir: C:\\x"], None)["evidence"], "")

    # unreadable / malformed data file: unknown plus a note
    bad_cases = {
        "missing file": None, "invalid JSON": b"{not json", "non-UTF-8 bytes": b"\xff\xfe\x00{",
        "a list at the top": b"[]", "empty causes": b'{"causes": []}',
        "a cause with an empty marker": json.dumps({"causes": [{"id": "a", "markers": [""], "doors": {}}]}).encode(),
        "a cause with no doors": json.dumps({"causes": [{"id": "a", "markers": ["m"]}]}).encode(),
        "a cause with the old single `door` string only": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "door": "d"}]}).encode(),
        "doors that is a list": json.dumps({"causes": [{"id": "a", "markers": ["m"], "doors": ["d"]}]}).encode(),
        "a door sentence that is not a string": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {"role": 3}}]}).encode(),
        "a `requires` the code cannot check": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}, "requires": "moon_phase"}]}).encode(),
        "duplicate ids": json.dumps({"causes": [{"id": "a", "markers": ["m"], "doors": {}},
                                                {"id": "a", "markers": ["n"], "doors": {}}]}).encode(),
        "a pattern that does not compile": json.dumps({"causes": [{"id": "a", "markers": ["m"], "doors": {},
                                                                   "named_option_patterns": ["(["]}]}).encode(),
        "a pattern with no group": json.dumps({"causes": [{"id": "a", "markers": ["m"], "doors": {},
                                                           "named_option_patterns": ["x"]}]}).encode(),
        "collect_forms without `ok_exits`": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"]}]}).encode(),
        "collect_forms with a boolean exit": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [True]}]}).encode(),
        "collect_forms with `not_executed_exits` that is not a list": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [0], "not_executed_exits": 4}]}).encode(),
        "collect_forms with a boolean in `not_executed_exits`": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [0],
                                "not_executed_exits": [True]}]}).encode(),
        "collect_forms with the runner's own 124 in `not_executed_exits`": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [0],
                                "not_executed_exits": [4, 124]}]}).encode(),
        "collect_forms with 127 in `not_executed_exits`": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [0],
                                "not_executed_exits": [127]}]}).encode(),
        "collect_forms with an empty `node_ids`": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [0], "node_ids": " "}]}).encode(),
        "collect_forms with a `node_ids` that is not a string": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "collect_forms": [{"tool": "pytest", "append": ["-q"], "ok_exits": [0], "node_ids": ["pytest"]}]}).encode(),
        "a wrapper without `subcommands`": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "wrappers": [{"program": "poetry"}]}).encode(),
        "a positional placeholder that is no placeholder": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "positional_placeholders": ["test-file"]}).encode(),
        "environment_folders that is a string": json.dumps(
            {"causes": [{"id": "a", "markers": ["m"], "doors": {}}],
             "environment_folders": "Scripts"}).encode(),
    }
    for label, content in bad_cases.items():
        def under():
            return lc.classify(2, ["ModuleNotFoundError: x"], None)
        if content is None:
            saved = lc.CAUSES_PATH
            lc.CAUSES_PATH = TMP / "does-not-exist.json"
            try:
                got = under()
            finally:
                lc.CAUSES_PATH = saved
        else:
            got = with_data(content, under)
        check_eq(f"E1 data file: {label} -> unknown", got["cause"], "unknown")
        check(f"E1 data file: {label} -> a note, no exception", bool(got.get("note")), str(got))
    check_eq("E1 door() of an unreadable file is empty, not an exception",
             with_data(b"{nope", lambda: lc.door("dependency_missing")), "")


# --- E1b: a cause confirmed against the argv beats one that is not -----------------------------

def e1b_confirmed_causes():
    aws = "bash: aws: command not found"
    got = lc.classify(4, [aws, LAUNCHER_LINE], None, argv=CMP1_ONE_TEST)
    check_eq("E1b a stray `aws` line before the launcher's own rejection: launcher_rejected_arguments",
             (got["cause"], got["evidence"]), ("launcher_rejected_arguments", LAUNCHER_LINE))
    got = lc.classify(4, [LAUNCHER_LINE, aws], None, argv=CMP1_ONE_TEST)
    check_eq("E1b ... in the other line order too", got["cause"], "launcher_rejected_arguments")
    data = real_data()
    reordered = dict(data, causes=list(reversed(data["causes"])))
    check_eq("E1b ... and under a reordered data file (confirmation beats data order)",
             with_data(reordered, lambda: lc.classify(4, [aws, LAUNCHER_LINE], None, argv=CMP1_ONE_TEST))["cause"],
             "launcher_rejected_arguments")
    got = lc.classify(4, [aws], None, argv=CMP1_ONE_TEST)
    check_eq("E1b the stray line alone is not believed: unknown, evidence kept, a note says why",
             (got["cause"], got["evidence"], bool(got.get("note"))), ("unknown", aws, True))
    got = lc.classify(2, [aws, "ModuleNotFoundError: No module named 'x'"], None, argv=CMP1_ONE_TEST)
    check_eq("E1b an unbelieved not-found line falls to the next cause that holds", got["cause"], "dependency_missing")

    # the line names the program actually run
    for label, line, argv in (
            ("posix", "bash: pytest: command not found", ["pytest", "<f>"]),
            ("posix with a line number", "bash: line 1: pytest: command not found", ["pytest"]),
            ("windows", "'pytest' is not recognized as an internal or external command,", ["pytest", "-q"]),
            ("windows, a path with a space",
             "'C:\\Program Files\\x\\poetry.exe' is not recognized as an internal or external command,",
             ["poetry", "run", "pytest"]),
            ("zsh spelling", "zsh: command not found: pytest", ["pytest"]),
            ("poetry's own spelling of a wrapped program", "Command not found: pytest",
             ["poetry", "run", "pytest", "<f>"]),
            ("the wrapper itself", "bash: poetry: command not found", ["poetry", "run", "pytest"]),
            ("npx: the wrapped program", "bash: playwright: command not found", ["npx", "playwright", "test"]),
            ("uv run with an option", "bash: pytest: command not found", ["uv", "run", "--frozen", "pytest"]),
            ("an .exe argv0", "bash: pytest: command not found", ["C:\\tools\\pytest.exe", "-q"]),
            ("a script path", "./bin/run.sh: command not found", ["./bin/run.sh", "<f>"])):
        got = lc.classify(127, [line], None, argv=argv)
        check_eq(f"E1b executable_not_found is confirmed: {label}", (got["cause"], got["evidence"]),
                 ("executable_not_found", line))

    # and refused when it does not
    for label, line, argv in (
            ("another program", "bash: aws: command not found", ["pytest", "<f>"]),
            ("a script's own missing tool", "run.sh: line 3: aws: command not found", ["./bin/run.sh", "<f>"]),
            ("zsh spelling, another program", "zsh: command not found: aws", ["pytest"]),
            ("the shell is the argv0 and the missing program is another", "zsh: command not found: aws",
             ["zsh", "-c", "aws s3 ls"]),
            ("a name that only starts like the program", "bash: pytest-xdist: command not found", ["pytest"]),
            ("the program is mentioned but is not the one not found",
             "pytest: warning: aws: command not found", ["pytest"]),
            ("a subcommand of a wrapper is not the program", "bash: run: command not found",
             ["poetry", "run", "pytest"]),
            ("a wrapper's program is not confirmed by another wrapper's", "bash: pytest: command not found",
             ["npm", "run", "test"]),
            ("no argv items at all", "bash: pytest: command not found", [])):
        got = lc.classify(127, [line], None, argv=argv)
        check_eq(f"E1b executable_not_found is refused: {label}", got["cause"], "unknown")
    got = lc.classify(127, ["bash: pytest: command not found"], None)
    check_eq("E1b no argv given: it cannot be confirmed -> unknown, evidence kept, a note",
             (got["cause"], got["evidence"], bool(got.get("note"))),
             ("unknown", "bash: pytest: command not found", True))
    for label, argv in (("a string", "pytest -q"), ("a number", 7), ("bytes", b"pytest")):
        check_eq(f"E1b an argv that is {label} confirms nothing and raises nothing",
                 lc.classify(127, ["bash: pytest: command not found"], None, argv=argv)["cause"], "unknown")
    check_eq("E1b a numeric argv item is read as a string",
             lc.classify(127, ["bash: 7z: command not found"], None, argv=["7z", 1])["cause"],
             "executable_not_found")

    # equal standing: data order decides
    both = ["bash: pytest: command not found", LAUNCHER_LINE]
    check_eq("E1b both hold: the data order decides (executable_not_found first)",
             lc.classify(4, both, None, argv=CMP1_ONE_TEST)["cause"], "executable_not_found")
    check_eq("E1b ... and a reordered data file picks the other one",
             with_data(reordered, lambda: lc.classify(4, both, None, argv=CMP1_ONE_TEST))["cause"],
             "launcher_rejected_arguments")
    # a later line of the same cause can confirm what an earlier one did not
    got = lc.classify(127, [aws, "bash: pytest: command not found"], None, argv=CMP1_ONE_TEST)
    check_eq("E1b the first line that CONFIRMS is the evidence (the stray one is skipped)",
             (got["cause"], got["evidence"]), ("executable_not_found", "bash: pytest: command not found"))

    # the markers added by this change
    check_eq("E1b the singular `1 error during collection` is a collection_error",
             lc.classify(2, ["!!!!!!! Interrupted: 1 error during collection !!!!!!!"], None)["cause"],
             "collection_error")
    check_eq("E1b the plural still is", lc.classify(2, ["Interrupted: 2 errors during collection"], None)["cause"],
             "collection_error")
    got = lc.classify(1, ["Command not found: pytest"], None, argv=["poetry", "run", "pytest"])
    check_eq("E1b poetry's `Command not found: pytest` is executable_not_found", got["cause"], "executable_not_found")


# --- E2: probe ---------------------------------------------------------------------------------

def e2_probe():
    root = project()
    which = which_in({"pytest"})

    # the command probed
    run = Run()
    got = probe(profile(), root, run, which)
    check_eq("E2 one_test: placeholder `<test-file>` gone, options kept, suffix added (then the runner's continue flag)",
             run.calls[0][0], ["pytest", "--reruns", "2", "--ui-headless", "--collect-only", "-q", PARTIAL_FLAG])
    check_eq("E2 the result names the probed argv", got["argv"],
             ["pytest", "--reruns", "2", "--ui-headless", "--collect-only", "-q", PARTIAL_FLAG])
    check_eq("E2 the result names the resolved path", got["resolved"], "pytest")
    check_eq("E2 the profile id is carried", got["profile"], "api")
    check_eq("E2 the shape is fixed", sorted(got), sorted(
        ["status", "profile", "argv", "resolved", "cause", "evidence", "env", "reason", "exit_code"]))

    shapes = {
        "`-m <test-id>` (the flag goes with it)":
            (["pytest", "-n", "4", "-m", "<test-id>", "--reruns", "2"],
             ["pytest", "-n", "4", "--reruns", "2", "--collect-only", "-q"]),
        "`--flag=<x>` (the token itself)":
            (["pytest", "--junit-prefix=<x>", "--reruns", "2"],
             ["pytest", "--reruns", "2", "--collect-only", "-q"]),
        "a bare positional after a value (`2` stays)":
            (["pytest", "--reruns", "2", "<test-path>"],
             ["pytest", "--reruns", "2", "--collect-only", "-q"]),
        "a bare positional after the program":
            (["pytest", "<test-path>"], ["pytest", "--collect-only", "-q"]),
        "a wrapper launcher":
            (["poetry", "run", "pytest", "<test-file>", "--reruns", "2"],
             ["poetry", "run", "pytest", "--reruns", "2", "--collect-only", "-q"]),
        "two placeholders in a row":
            (["pytest", "-k", "<a>", "<b>", "-x"], ["pytest", "-x", "--collect-only", "-q"]),
        "a placeholder inside a path token":
            (["pytest", "tests/<file>.py", "-x"], ["pytest", "-x", "--collect-only", "-q"]),
        "`-q` already there is not doubled":
            (["pytest", "<t>", "-q"], ["pytest", "-q", "--collect-only"]),
        "a boolean flag before a positional placeholder goes with it (the stated rule)":
            (["pytest", "--ui-headless", "<t>", "-x"], ["pytest", "-x", "--collect-only", "-q"]),
        "a negative number is a value, not a flag":
            (["pytest", "--maxfail", "-1", "<t>"], ["pytest", "--maxfail", "-1", "--collect-only", "-q"]),
    }
    for label, (argv, want) in shapes.items():
        run = Run()
        probe(profile(one=argv), root, run, which_in({"pytest", "poetry"}))
        # the runner's continue flag (RH1-3) follows the form's own `append`, once
        check_eq(f"E2 shape {label}", run.calls[0][0] if run.calls else None, want + [PARTIAL_FLAG])
        check(f"E2 shape {label}: no placeholder reaches the command",
              bool(run.calls) and not any_placeholder(run.calls[0][0]))

    # collect only when there is no one_test; it is not given a second suffix
    run = Run()
    probe(profile(one=None, collect=["pytest", "-m", "<test-id>", "--collect-only", "-q"]), root, run, which)
    check_eq("E2 collect.argv is used when there is no one_test (placeholder and its flag removed)",
             run.calls[0][0], ["pytest", "--collect-only", "-q", PARTIAL_FLAG])
    run = Run()
    probe(profile(collect=["pytest", "--other"]), root, run, which)
    check_eq("E2 one_test wins over collect", run.calls[0][0][1:2], ["--reruns"])
    run = Run()
    probe(profile(one=[], collect=["pytest", "--collect-only"]), root, run, which)
    check_eq("E2 an EMPTY one_test argv counts as no one_test", run.calls[0][0], ["pytest", "--collect-only", PARTIAL_FLAG])

    # not_checked, and nothing was launched
    undecidable = {
        "an argv that is only placeholders": profile(one=["<a>", "<b>"]),
        "only placeholders and a collect exists too": profile(one=["<a>"], collect=["pytest", "--collect-only"]),
        "no commands key": {"profile_id": "api"},
        "commands is empty": {"profile_id": "api", "commands": {}},
        "collect.argv is []": profile(one=None, collect=[]),
        "a one_test with no argv and no collect": {"profile_id": "api", "commands": {"one_test": {"cwd": "."}}},
        "the program is a placeholder": profile(one=["<runner>", "--x"]),
        "a command string holding a placeholder": profile(one=["sh", "-c", "pytest <t> -q"]),
        "argv is a string": profile(one=None, collect=None) | {"commands": {"one_test": {"argv": "pytest -q"}}},
        "argv holds a null": profile(one=["pytest", None]),
        "the profile is not an object": "api",
    }
    for label, prof in undecidable.items():
        run = Run()
        got = probe(prof, root, run, which)
        check_eq(f"E2 {label}: not_checked", got["status"], "not_checked")
        check(f"E2 {label}: a reason, no launch, no cause",
              bool(got["reason"]) and not run.calls and got["cause"] is None, str(got))

    # exit codes
    for code, want in ((0, "ok"), (5, "ok"), (1, "failed"), (2, "failed"), (4, "failed"), (127, "failed")):
        got = probe(profile(), root, Run(returncode=code), which)
        check_eq(f"E2 exit {code} -> {want}", got["status"], want)
    check_eq("E2 an ok probe has no cause", probe(profile(), root, Run(returncode=5), which)["cause"], None)

    # what a failed launch says
    got = probe(profile(), root, Run(returncode=4, stderr=(LAUNCHER_LINE + "\n").encode()), which)
    check_eq("E2 rejected options: cause and evidence", (got["cause"], got["evidence"], got["exit_code"]),
             ("launcher_rejected_arguments", LAUNCHER_LINE, 4))
    got = probe(profile(one=["pytest", "<t>"]), root,
                Run(returncode=4, stderr=b"pytest: error: unrecognized arguments: --collect-only -q\n"), which)
    check_eq("E2 the probe's OWN suffix rejected is `unknown`, never a confident launcher verdict",
             got["cause"], "unknown")
    got = probe(profile(), root, Run(returncode=2, stdout=b"ERROR collecting tests/a.py\nModuleNotFoundError: No module named 'q'\n"), which)
    check_eq("E2 a collect that stops on an import", got["cause"], "dependency_missing")
    got = probe(profile(), root, Run(returncode=3, stdout=b"rootdir: C:\\x\n"), which)
    check_eq("E2 an unrecognised failure: unknown with an empty evidence and a reason",
             (got["cause"], got["evidence"], bool(got["reason"])), ("unknown", "", True))

    # launch errors
    got = probe(profile(), root, Run(raises=FileNotFoundError("[WinError 2] The system cannot find the file")), which)
    check_eq("E2 FileNotFoundError from run -> failed / executable_not_found",
             (got["status"], got["cause"]), ("failed", "executable_not_found"))
    run = Run()
    got = probe(profile(), root, run, which_in(set()))
    check_eq("E2 the program is not on the PATH it was given -> executable_not_found, nothing launched",
             (got["status"], got["cause"], got["resolved"], len(run.calls)),
             ("failed", "executable_not_found", None, 0))
    got = probe(profile(), root, Run(raises=PermissionError("denied")), which)
    check_eq("E2 another OSError is failed / unknown (never `not found`)",
             (got["status"], got["cause"]), ("failed", "unknown"))
    got = probe(profile(), root, Run(raises=RuntimeError("boom")), which)
    check_eq("E2 an unexpected exception is not_checked: cannot tell is not a finding",
             (got["status"], got["cause"]), ("not_checked", None))
    got = probe(profile(), root, Run(returncode=None), which)
    check_eq("E2 no exit code is not_checked", got["status"], "not_checked")

    # timeout
    run = Run()
    probe(profile(), root, run, which)
    check_eq("E2 default timeout is 120", run.calls[0][1]["timeout"], 120)
    for raw, want in (({"collect_timeout_s": 7}, 7), ({"collect_timeout_s": "9"}, 9), ({"collect_timeout_s": 0}, 120),
                      ({"collect_timeout_s": -5}, 120), ({"collect_timeout_s": True}, 120),
                      ({"collect_timeout_s": "soon"}, 120), ({"collect_timeout_s": 2.5}, 2.5)):
        run = Run()
        probe(profile(), root, run, which, config={"gate_rehearsal": raw})
        check_eq(f"E2 collect_timeout_s {raw['collect_timeout_s']!r} -> {want}", run.calls[0][1]["timeout"], want)
    got = probe(profile(), root, Run(raises=subprocess.TimeoutExpired("pytest", 7)), which,
                config={"gate_rehearsal": {"collect_timeout_s": 7}})
    check_eq("E2 TimeoutExpired -> failed / unknown", (got["status"], got["cause"]), ("failed", "unknown"))
    check_in("E2 the timeout says `did not finish within 7s`", "did not finish within 7s", got["evidence"])

    # skip_collect: by the handed config, and by the project's own file
    for label, cfg in (("true", {"gate_rehearsal": {"skip_collect": True}}), ("1", {"gate_rehearsal": {"skip_collect": 1}})):
        run = Run()
        got = probe(profile(), root, run, which, config=cfg)
        check_eq(f"E2 skip_collect {label}: not_checked, nothing launched",
                 (got["status"], len(run.calls)), ("not_checked", 0))
        check_in(f"E2 skip_collect {label}: the reason names it", "skip_collect", got["reason"])
    skipping = project([profile()], gate_rehearsal={"skip_collect": True})
    run = Run()
    got = lc.probe(profile(), skipping, env={"PATH": ""}, run=run, which=which)
    check_eq("E2 skip_collect read from the project's config.json when none is handed over",
             (got["status"], len(run.calls)), ("not_checked", 0))
    run = Run()
    got = probe(profile(), root, run, which, config={"gate_rehearsal": {"skip_collect": False}})
    check_eq("E2 skip_collect false runs", (got["status"], len(run.calls)), ("ok", 1))
    broken = project([profile()])
    (broken / "qa-factory" / "config.json").write_text("{nope", encoding="utf-8")
    run = Run()
    got = lc.probe(profile(), broken, env={"PATH": ""}, run=run, which=which)
    check_eq("E2 an unreadable project config: skip_collect cannot be read -> not_checked, nothing run",
             (got["status"], len(run.calls)), ("not_checked", 0))

    # cwd
    (root / "app" / "sub").mkdir(parents=True)
    run = Run()
    probe(profile(cwd="app/sub"), root, run, which)
    check_eq("E2 cwd = project root joined with the command's cwd",
             Path(run.calls[0][1]["cwd"]), root / "app" / "sub")
    run = Run()
    got = probe(profile(cwd="nowhere"), root, run, which)
    check_eq("E2 a cwd that is not a directory is not_checked (not `executable not found`)",
             (got["status"], len(run.calls)), ("not_checked", 0))
    check_eq("E2 no cwd key -> the project root", (lambda r: (probe(profile(), root, r, which), Path(r.calls[0][1]["cwd"]))[1])(Run()), root)

    # a script path is looked up from the command's cwd, not on PATH
    (root / "bin").mkdir()
    (root / "bin" / "pytest").write_text("#!/bin/sh\n", encoding="utf-8")
    run = Run()
    got = probe(profile(one=["./bin/pytest", "<t>"]), root, run, which_in(set()))
    check_eq("E2 a relative script path resolves under the cwd", Path(got["resolved"]), root / "bin" / "pytest")
    got = probe(profile(one=["./nowhere/pytest"]), root, Run(), which)
    check_eq("E2 a script path that is no file -> executable_not_found", got["cause"], "executable_not_found")
    run = Run()
    got = probe(profile(one=["./bin/missing.sh"]), root, run, which)
    check_eq("E2 a script of no known runner that is no file: not_checked, not `failed` (see E2b)",
             (got["status"], got["cause"], len(run.calls)), ("not_checked", None, 0))

    # the environment the command runs in
    seen_env = {"PATH": "", "VIRTUAL_ENV": "/v", "POETRY_ACTIVE": "1", "HOME": "/h"}
    run = Run()
    got = probe(profile(), root, run, which, env=seen_env)
    check_eq("E2 result env: the activated-environment variables present",
             got["env"], {"VIRTUAL_ENV": "/v", "POETRY_ACTIVE": "1"})
    check_eq("E2 the command runs in the environment it was given", run.calls[0][1]["env"]["VIRTUAL_ENV"], "/v")
    check_eq("E2 no bytecode is written by the probe", run.calls[0][1]["env"]["PYTHONDONTWRITEBYTECODE"], "1")
    check_eq("E2 the caller's env is not mutated", "PYTHONDONTWRITEBYTECODE" in seen_env, False)


# --- E2b: the collect form is data, per runner ---------------------------------------------------

def e2b_collect_forms():
    root = project()
    data = real_data()
    check_eq("E2b the data file has one collect form: pytest (the two B-407 runner facts, the RH1-3 partial-collect facts)",
             [{k: v for k, v in row.items() if k not in PARTIAL_KEYS + TIMEOUT_KEYS} for row in data["collect_forms"]],
             [{"tool": "pytest", "append": ["--collect-only", "-q"], "ok_exits": [0, 5],
               "not_executed_exits": [2, 3, 4, 5], "node_ids": "pytest"}])
    check_eq("E2b ... and the partial-collect facts are the row's own keys",
             sorted(k for k in data["collect_forms"][0] if k in PARTIAL_KEYS), sorted(PARTIAL_KEYS))

    # a runner with no collect form: nothing launched, not_checked, never failed
    for label, argv in (("npx jest", ["npx", "jest", "<f>"]),
                        ("dotnet test", ["dotnet", "test", "<p>"]),
                        ("npx playwright test", ["npx", "playwright", "test", "<f>"]),
                        ("a shell script", ["./run-tests.sh", "<f>"]),
                        ("a Maven wrapper", ["mvn", "-q", "test", "-Dtest=<t>"])):
        for code in (0, 5, 1):
            run = Run(returncode=code)
            got = probe(profile(one=argv), root, run, which_in({"npx", "dotnet", "mvn"}))
            check_eq(f"E2b {label} (a fake that exits {code}): not_checked, nothing launched, no cause",
                     (got["status"], got["cause"], got["evidence"], len(run.calls)), ("not_checked", None, "", 0))
        check_eq(f"E2b {label}: the reason is the stated one", got["reason"], "no collect form known for this runner")
    # the pytest suffix is never put on another runner's command
    run = Run()
    probe(profile(one=["npx", "jest", "<f>"]), root, run, which_in({"npx"}))
    check_eq("E2b no `--collect-only` reaches a non-pytest command", run.calls, [])

    # ... unless the profile has its own collect command for it
    listing = ["npx", "jest", "--listTests"]
    run = Run()
    got = probe(profile(one=["npx", "jest", "<f>"], collect=listing), root, run, which_in({"npx"}))
    check_eq("E2b a non-pytest profile with commands.collect is probed with it, verbatim",
             (run.calls[0][0], got["status"], got["argv"]), (listing, "ok", listing))
    got = probe(profile(one=["dotnet", "test", "<p>"], collect=["dotnet", "test", "--list-tests"]), root,
                Run(returncode=0), which_in({"dotnet"}))
    check_eq("E2b ... dotnet too", (got["status"], got["argv"]), ("ok", ["dotnet", "test", "--list-tests"]))
    got = probe(profile(one=["npx", "jest", "<f>"], collect=listing), root, Run(returncode=5), which_in({"npx"}))
    check_eq("E2b a non-pytest collect that exits 5 is `failed`: no pytest-only exit code is assumed",
             (got["status"], got["exit_code"]), ("failed", 5))
    got = probe(profile(one=["npx", "jest", "<f>"], collect=listing), root,
                Run(returncode=1, stderr=b"ModuleNotFoundError: No module named 'x'\n"), which_in({"npx"}))
    check_eq("E2b a failing non-pytest collect is classified", (got["status"], got["cause"]), ("failed", "dependency_missing"))
    got = probe(profile(one=["npx", "jest", "<f>"], collect=listing), root, Run(), which_in(set()))
    check_eq("E2b a non-pytest collect whose program is not on PATH: executable_not_found",
             (got["status"], got["cause"]), ("failed", "executable_not_found"))
    run = Run()
    got = probe(profile(one=["npx", "jest", "<f>"], collect=["<runner>", "--list"]), root, run, which_in({"npx"}))
    check_eq("E2b a collect that cannot be reduced: not_checked", (got["status"], len(run.calls)), ("not_checked", 0))
    got = probe(profile(one=["npx", "jest", "<f>"], collect=[]), root, Run(), which_in({"npx"}))
    check_eq("E2b an empty collect argv counts as none", got["reason"], "no collect form known for this runner")
    got = probe(profile(one=["npx", "jest", "<f>"]) | {"commands": {"one_test": {"argv": ["npx", "jest"]},
                                                                  "collect": {"argv": "npx jest --listTests"}}},
                root, Run(), which_in({"npx"}))
    check_eq("E2b a collect argv that is a string: not_checked with a reason",
             (got["status"], bool(got["reason"])), ("not_checked", True))

    # the pytest form still holds: one_test + the appended suffix, exits 0 and 5 are ok
    for label, argv in (("pytest", ["pytest", "<f>"]), ("poetry run pytest", ["poetry", "run", "pytest", "<f>"]),
                        ("python -m pytest", ["python", "-m", "pytest", "<f>"]),
                        ("uv run pytest", ["uv", "run", "pytest", "<f>"])):
        run = Run(returncode=5)
        got = probe(profile(one=argv), root, run, which_in({"pytest", "poetry", "python", "uv"}))
        check_eq(f"E2b {label}: the collect suffix (then the runner's continue flag) is added and exit 5 is ok",
                 (run.calls[0][0][-3:], got["status"]) if run.calls else None,
                 (["--collect-only", "-q", PARTIAL_FLAG], "ok"))
    got = probe(profile(one=[], collect=["pytest", "--collect-only"]), root, Run(returncode=5), which_in({"pytest"}))
    check_eq("E2b a pytest-shaped commands.collect (no one_test) keeps exit 5 as ok", got["status"], "ok")

    # the form is DATA: another row changes the command, the exits and the applicability
    changed = dict(data, collect_forms=[{"tool": "pytest", "append": ["--co"], "ok_exits": [0]}])
    run = Run(returncode=5)
    got = with_data(changed, lambda: probe(profile(), root, run, which_in({"pytest"})))
    check_eq("E2b the appended text is read from the data file",
             (run.calls[0][0][-1], got["status"]), ("--co", "failed"))
    for label, rows in (("no rows", []), ("a row for a tool the code cannot recognise",
                                          [{"tool": "jest", "append": ["--listTests"], "ok_exits": [0]}])):
        run = Run()
        got = with_data(dict(data, collect_forms=rows), lambda: probe(profile(), root, run, which_in({"pytest"})))
        check_eq(f"E2b {label}: a pytest command is not probed either (cannot tell)",
                 (got["status"], got["reason"], len(run.calls)), ("not_checked", "no collect form known for this runner", 0))
    run = Run()
    got = with_data(b"{nope", lambda: probe(profile(), root, run, which_in({"pytest"})))
    check_eq("E2b an unreadable data file: not_checked, nothing built, nothing launched",
             (got["status"], len(run.calls), "data file" in got["reason"]), ("not_checked", 0, True))

    # the recogniser is the one S5 uses, and if it cannot be loaded that is "cannot tell"
    import execution_request
    for argv in (["pytest"], ["poetry", "run", "pytest"], ["npx", "jest"], ["dotnet", "test"], ["python", "-m", "pytest"]):
        check_eq(f"E2b the probe's reading of {argv} is execution_request.is_pytest_command's",
                 lc._collect_form(argv, data["collect_forms"]) is not None, execution_request.is_pytest_command(argv))
    saved = lc._SHAPES

    def broken(_tokens):
        raise lc._ShapeUnavailable("ImportError: gone")

    lc._SHAPES = {"pytest": broken}
    try:
        run = Run()
        got = probe(profile(), root, run, which_in({"pytest"}))
    finally:
        lc._SHAPES = saved
    check_eq("E2b a recogniser that cannot be loaded: not_checked, nothing launched, the reason says so",
             (got["status"], len(run.calls), "recogniser" in got["reason"]), ("not_checked", 0, True))

    # the launcher's own rejected option, on the profile's argv, still names the cause
    got = probe(profile(), root, Run(returncode=4, stderr=("bash: aws: command not found\n" + LAUNCHER_LINE + "\n").encode()),
                which_in({"pytest"}))
    check_eq("E2b a stray earlier line does not hide the launcher's rejection in a real probe",
             (got["cause"], got["evidence"]), ("launcher_rejected_arguments", LAUNCHER_LINE))


# --- E2d: the runner row (B-407 B-run): exit facts and the node-id checker, per runner ---------------

def e2d_runner_row():
    data = real_data()
    pytest_row = data["collect_forms"][0]
    for label, argv in (("pytest", ["pytest", "tests/test_a.py"]), ("poetry run pytest", ["poetry", "run", "pytest"]),
                        ("python -m pytest", ["python", "-m", "pytest"])):
        row, problem = lc.runner_row(argv)
        check_eq(f"E2d runner_row({label}) is the pytest row with its two facts (and the partial-collect keys)",
                 ({k: v for k, v in row.items() if k not in PARTIAL_KEYS + TIMEOUT_KEYS}, problem),
                 ({"tool": "pytest", "append": ["--collect-only", "-q"], "ok_exits": [0, 5],
                   "not_executed_exits": [2, 3, 4, 5], "node_ids": "pytest"}, ""))
    for label, argv in (("dotnet test", ["dotnet", "test"]), ("npx jest", ["npx", "jest"]), ("an empty argv", []),
                        ("None", None)):
        check_eq(f"E2d runner_row({label}): no row is an answer, not a problem", lc.runner_row(argv), (None, ""))
    check_eq("E2d the legacy codes are what the shipped pytest row lists (one fact, two spellings)",
             list(lc._LEGACY_NOT_EXECUTED), pytest_row["not_executed_exits"])

    # the two fields are carried only when the raw row has them; an empty list is a fact
    bare = {"tool": "pytest", "append": ["-q"], "ok_exits": [0]}
    check_eq("E2d a row with neither field carries neither",
             with_data(dict(data, collect_forms=[bare]), lambda: lc.runner_row(["pytest"])), (bare, ""))
    empty = dict(bare, not_executed_exits=[])
    check_eq("E2d `not_executed_exits: []` is carried as a fact",
             with_data(dict(data, collect_forms=[empty]), lambda: lc.runner_row(["pytest"])), (empty, ""))
    only_ids = dict(bare, node_ids="pytest")
    check_eq("E2d `node_ids` alone is carried alone",
             with_data(dict(data, collect_forms=[only_ids]), lambda: lc.runner_row(["pytest"])), (only_ids, ""))

    # unreadable data: (None, why), never an exception, never an empty answer
    for label, content in (("not JSON", b"{nope"), ("a bad row", dict(data, collect_forms=[dict(bare, not_executed_exits="4")]))):
        row, problem = with_data(content, lambda: lc.runner_row(["pytest"]))
        check_eq(f"E2d runner_row over data that is {label}: no row", row, None)
        check(f"E2d ... and a problem that says why ({label})", bool(problem), problem)
    _data, why = with_data(dict(data, collect_forms=[dict(bare, not_executed_exits=[124])]), lc.load_data)
    check_eq("F1 a malformed runner field names the file once, then the row and the field",
             (why.count("causes-under-test.json"), "collect_forms[0]" in why, "not_executed_exits" in why), (1, True, True))
    saved = lc.CAUSES_PATH
    lc.CAUSES_PATH = TMP / "does-not-exist.json"
    try:
        row, problem = lc.runner_row(["pytest"])
    finally:
        lc.CAUSES_PATH = saved
    check_eq("E2d a missing data file: a problem", (row, "unreadable" in problem), (None, True))

    # K-R3: a recogniser that cannot be loaded, or that fails, is a problem
    saved_shapes = lc._SHAPES

    def broken(_tokens):
        raise lc._ShapeUnavailable("ImportError: gone")

    def crashing(_tokens):
        raise RuntimeError("boom")
    try:
        lc._SHAPES = {"pytest": broken}
        row, problem = lc.runner_row(["pytest"])
        check_eq("K-R3 a recogniser that cannot be loaded: a problem naming it", (row, "recogniser" in problem, "gone" in problem),
                 (None, True, True))
        lc._SHAPES = {"pytest": crashing}
        row, problem = lc.runner_row(["pytest"])
        check_eq("K-R3 a recogniser that raises: a problem too, not an exception", (row, "boom" in problem), (None, True))
    finally:
        lc._SHAPES = saved_shapes


# --- E2c: positional placeholders --------------------------------------------------------------

def e2c_placeholders():
    root = project()
    data = real_data()
    names = data["positional_placeholders"]
    check_eq("E2c the positional names are in the data file", names, ["<test-file>", "<test-path>"])
    for name in names:
        check_eq(f"E2c `pytest --no-cov {name}` keeps `--no-cov`",
                 lc.strip_placeholders(["pytest", "--no-cov", name]), (["pytest", "--no-cov"], None))
        run = Run()
        probe(profile(one=["pytest", "--no-cov", name]), root, run, which_in({"pytest"}))
        check_eq(f"E2c ... and the probe runs `pytest --no-cov --collect-only -q` ({name})",
                 run.calls[0][0], ["pytest", "--no-cov", "--collect-only", "-q", PARTIAL_FLAG])
    check_eq("E2c a positional after a value keeps the value too",
             lc.strip_placeholders(["pytest", "-n", "4", "--reruns", "2", "<test-file>"]),
             (["pytest", "-n", "4", "--reruns", "2"], None))
    check_eq("E2c a placeholder that is the VALUE of a flag still goes with its flag (`-m <test-id>`)",
             lc.strip_placeholders(["pytest", "-m", "<test-id>", "<test-file>", "--reruns", "2"]),
             (["pytest", "--reruns", "2"], None))
    check_eq("E2c `--flag=<x>` still goes as a token",
             lc.strip_placeholders(["pytest", "--no-cov", "--junit-prefix=<test-file>", "<test-file>"]),
             (["pytest", "--no-cov"], None))
    check_eq("E2c a placeholder name the data file does not hold keeps the old rule (`<t>` takes `--no-cov`)",
             lc.strip_placeholders(["pytest", "--no-cov", "<t>"]), (["pytest"], None))
    check_eq("E2c the name is compared exactly (`<Test-File>` is not `<test-file>`)",
             lc.strip_placeholders(["pytest", "--no-cov", "<Test-File>"]), (["pytest"], None))
    check_eq("E2c a positional name written INSIDE a path token is a token to drop, its flag stays",
             lc.strip_placeholders(["pytest", "--no-cov", "tests/<test-file>.py"]), (["pytest", "--no-cov"], None))
    check_eq("E2c explicit names override the data file", lc.strip_placeholders(["pytest", "--no-cov", "<t>"], ["<t>"]),
             (["pytest", "--no-cov"], None))
    check_eq("E2c with no positional names the old rule holds for every placeholder",
             lc.strip_placeholders(["pytest", "--no-cov", "<test-file>"], []), (["pytest"], None))
    check_eq("E2c a program that is a placeholder is still undecidable",
             lc.strip_placeholders(["<test-file>", "--no-cov"])[0], None)
    # what S5 builds is the same list: one reading, two sides
    import execution_request
    for name in names:
        s5 = execution_request._profile_argv({"commands": {"one_test": {"argv": ["pytest", "--no-cov", "-n", "2", name]}}})
        check_eq(f"E2c the probe's reduction of {name} equals the one S5 builds",
                 lc.strip_placeholders(["pytest", "--no-cov", "-n", "2", name])[0], s5)
    changed = dict(data, positional_placeholders=["<the-file>"])
    check_eq("E2c the names are read from the data file (a changed list changes the result)",
             with_data(changed, lambda: (lc.strip_placeholders(["pytest", "--no-cov", "<test-file>"]),
                                         lc.strip_placeholders(["pytest", "--no-cov", "<the-file>"]))),
             ((["pytest"], None), (["pytest", "--no-cov"], None)))


# --- E3: --deactivated -------------------------------------------------------------------------

def e3_deactivated():
    proj = TMP / "proj"
    venv = str(proj / ".venv")
    scripts = os.path.join(venv, "Scripts" if os.name == "nt" else "bin")
    system = str(TMP / "system" / "bin")
    other = str(proj / ".venv2" / "bin")
    variables = real_data()["deactivated_variables"]
    check_eq("E3 the variable list is in the data file",
             variables, ["VIRTUAL_ENV", "CONDA_PREFIX", "POETRY_ACTIVE", "PIPENV_ACTIVE"])
    env = {"PATH": os.pathsep.join([scripts, other, system]), "VIRTUAL_ENV": venv,
           "POETRY_ACTIVE": "1", "PIPENV_ACTIVE": "1", "HOME": "h"}
    new, removed, dropped = lc.strip_activation(env, variables)
    check("E3 the listed variables are removed", not any(v in new for v in variables), str(new))
    check_eq("E3 the venv's PATH entry is removed", scripts in new["PATH"].split(os.pathsep), False)
    check_eq("E3 a sibling directory that merely shares the prefix stays (`.venv2` is not under `.venv`)",
             new["PATH"].split(os.pathsep), [other, system])
    check_eq("E3 what was removed is reported", (sorted(removed), dropped),
             (["PIPENV_ACTIVE", "POETRY_ACTIVE", "VIRTUAL_ENV"], [scripts]))
    check("E3 the input is not mutated", env["VIRTUAL_ENV"] == venv and scripts in env["PATH"])
    check_eq("E3 other variables stay", new["HOME"], "h")
    conda = str(TMP / "conda" / "envs" / "x")
    new, _r, dropped = lc.strip_activation(
        {"PATH": os.pathsep.join([conda, os.path.join(conda, "bin"), system]), "CONDA_PREFIX": conda}, variables)
    check_eq("E3 CONDA_PREFIX: the prefix itself and what lies under it", new["PATH"], system)
    new, _r, dropped = lc.strip_activation({"PATH": system, "POETRY_ACTIVE": "1"}, variables)
    check_eq("E3 `POETRY_ACTIVE=1` names no directory: PATH is untouched", (new["PATH"], dropped), (system, []))
    root_dir = os.path.abspath(os.sep)
    new, _r, dropped = lc.strip_activation({"PATH": system, "VIRTUAL_ENV": root_dir}, variables)
    check_eq("E3 a filesystem root is never a prefix (it would empty the PATH)", new["PATH"], system)
    new, _r, dropped = lc.strip_activation({"VIRTUAL_ENV": venv}, variables)
    check_eq("E3 no PATH at all: no exception, nothing dropped", (dropped, "PATH" in new), ([], False))
    accented = str(TMP / "pr\u00f6j \u4e2d" / ".venv")
    new, _r, dropped = lc.strip_activation(
        {"PATH": os.pathsep.join([os.path.join(accented, "bin"), system]), "VIRTUAL_ENV": accented}, variables)
    check_eq("E3 a non-ASCII venv path is stripped", new["PATH"], system)
    if os.name == "nt":
        new, _r, dropped = lc.strip_activation(
            {"Path": os.pathsep.join([scripts.upper(), system]), "Virtual_Env": venv}, variables)
        check_eq("E3 Windows: names and paths compare case-insensitively",
                 (new.get("Path"), "Virtual_Env" in new), (system, False))

    # the executable is resolved with the STRIPPED path
    in_venv, in_system = os.path.join(scripts, "pytest"), os.path.join(system, "pytest")
    which = which_in({in_venv, in_system})
    run = Run()
    stripped, _r, _d = lc.strip_activation(env, variables)
    got = lc.probe(profile(), TMP, env=stripped, run=run, which=which, config={})
    check_eq("E3 resolved with the stripped PATH: the system launcher, not the venv's", got["resolved"], in_system)
    check("E3 the path handed to `which` holds no venv entry", scripts not in (which.seen[-1] or ""), str(which.seen))
    check("E3 the run's environment holds no venv variable",
          not any(v in run.calls[0][1]["env"] for v in variables), str(run.calls[0][1]["env"]))
    check_eq("E3 the result's env says nothing was active", got["env"], {})
    not_stripped = lc.probe(profile(), TMP, env=env, run=Run(), which=which, config={})
    check_eq("E3 without --deactivated the venv's launcher wins (and the result names the venv)",
             (not_stripped["resolved"], sorted(not_stripped["env"])),
             (in_venv, ["PIPENV_ACTIVE", "POETRY_ACTIVE", "VIRTUAL_ENV"]))

    # through the CLI
    root = project([profile()])
    run, buf = Run(returncode=4, stderr=LAUNCHER_LINE.encode()), io.StringIO()
    code = lc.main(["--deactivated", "--json"], run=run, which=which, env=env, out=buf, err=io.StringIO(), cwd=root)
    doc = json.loads(buf.getvalue())
    check_eq("E3 CLI --deactivated: exit 0 and the system launcher ran",
             (code, doc["profiles"][0]["resolved"]), (0, in_system))
    check_eq("E3 CLI --deactivated: the JSON says what it removed",
             (doc["deactivated"], doc["removed"]["path_entries"], sorted(doc["removed"]["variables"])),
             (True, [scripts], ["PIPENV_ACTIVE", "POETRY_ACTIVE", "VIRTUAL_ENV"]))
    check_eq("E3 CLI --deactivated: the launcher's rejected options are named (the failed profile)",
             (doc["status"], doc["profiles"][0]["cause"]), ("failed", "launcher_rejected_arguments"))
    buf = io.StringIO()
    lc.main(["--json"], run=Run(), which=which, env=env, out=buf, err=io.StringIO(), cwd=root)
    doc = json.loads(buf.getvalue())
    check_eq("E3 CLI without --deactivated: nothing removed, the venv launcher resolves",
             (doc["deactivated"], doc["profiles"][0]["resolved"]), (False, in_venv))
    # the data file cannot name the variables: --deactivated must not pretend to have stripped
    buf = io.StringIO()
    run = Run()
    with_data(b"{nope", lambda: lc.main(["--deactivated", "--json"], run=run, which=which, env=env,
                                        out=buf, err=io.StringIO(), cwd=root))
    doc = json.loads(buf.getvalue())
    check_eq("E3 an unreadable data file: --deactivated is not_checked, nothing launched",
             (doc["status"], len(run.calls)), ("not_checked", 0))


# --- E3b: which PATH entries --deactivated removes ---------------------------------------------

def other_spelling(path):
    """`(alias, how)`: another spelling of the existing directory `path` that names the same
    directory (a Windows 8.3 short name, else a symlink), or `(None, why)` when this machine
    cannot make one."""
    path = str(path)
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(2048)
            size = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 2048)
            if size and buf.value and buf.value.lower() != path.lower():
                return buf.value, "8.3 short name"
        except Exception as exc:
            return None, f"no short name: {type(exc).__name__}"
        return None, "the volume gives this directory no short name"
    link = path + "-alias"
    try:
        os.symlink(path, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        return None, f"no symlink: {type(exc).__name__}"
    return link, "symlink"


def e3b_deactivated_paths():
    variables = real_data()["deactivated_variables"]
    folders = real_data()["environment_folders"]
    check_eq("E3b the environment folders are in the data file", folders,
             [".", "Scripts", "bin", "Library/bin", "Library/usr/bin", "Library/mingw-w64/bin"])
    away = str(TMP / "away")  # the interpreter is somewhere else: the guard for it does not fire
    system = str(TMP / "system" / "bin")

    # only the environment's OWN folders under the prefix go
    proj = TMP / "proj-b"
    for sub in ("node_modules/.bin", "Scripts", "bin", "tools", "Library/bin", "Library/lib"):
        (proj / sub).mkdir(parents=True)
    entries = [str(proj / "node_modules" / ".bin"), str(proj / "Scripts"), str(proj / "bin"), str(proj / "tools"),
               str(proj / "Library" / "bin"), str(proj / "Library" / "lib"), str(proj), system]
    env = {"PATH": os.pathsep.join(entries), "VIRTUAL_ENV": str(proj) + os.sep}
    new, removed, dropped = lc.strip_activation(env, variables, interpreter=away)
    kept = new["PATH"].split(os.pathsep)
    check_in("E3b `VIRTUAL_ENV=C:\\proj\\` does NOT strip `node_modules\\.bin` under it",
             str(proj / "node_modules" / ".bin"), kept)
    check_in("E3b ... nor another folder of the project (`tools`)", str(proj / "tools"), kept)
    check_in("E3b ... nor `Library\\lib`", str(proj / "Library" / "lib"), kept)
    check_eq("E3b ... but `Scripts`, `bin`, `Library\\bin` and the prefix itself go",
             sorted(dropped), sorted([str(proj / "Scripts"), str(proj / "bin"), str(proj / "Library" / "bin"), str(proj)]))
    check_eq("E3b the variable is removed and named", removed, ["VIRTUAL_ENV"])
    new, _r, dropped = lc.strip_activation(env, variables, folders=[], interpreter=away)
    check_eq("E3b with no folders in the data nothing is stripped from PATH (the safe direction)", dropped, [])
    new, _r, dropped = lc.strip_activation(env, variables, folders=["tools"], interpreter=away)
    check_eq("E3b the folder names come from the data (`tools` alone)", dropped, [str(proj / "tools")])
    new, _r, dropped = lc.strip_activation(env, variables, folders=["Library\\bin"], interpreter=away)
    check_eq("E3b a folder written with a backslash matches (`Library\\bin`)", dropped, [str(proj / "Library" / "bin")])

    # a short (or otherwise different) spelling of the same directory
    real_prefix = TMP / "a_long_directory_name" / ".venv"
    (real_prefix / "Scripts").mkdir(parents=True)
    (real_prefix / "bin").mkdir(parents=True)
    alias, how = other_spelling(real_prefix)
    if alias is None:
        print(f"SKIP E3b the same-directory spelling checks: {how}")
    else:
        for name in ("Scripts", "bin"):
            env = {"PATH": os.pathsep.join([str(real_prefix / name), system]), "VIRTUAL_ENV": alias}
            new, _r, dropped = lc.strip_activation(env, variables, interpreter=away)
            check_eq(f"E3b a {how} in VIRTUAL_ENV matches the long form on PATH ({name})", new["PATH"], system)
            env = {"PATH": os.pathsep.join([os.path.join(alias, name), system]), "VIRTUAL_ENV": str(real_prefix)}
            new, _r, dropped = lc.strip_activation(env, variables, interpreter=away)
            check_eq(f"E3b a {how} on PATH matches the long form in VIRTUAL_ENV ({name})", new["PATH"], system)
        env = {"PATH": os.pathsep.join([os.path.join(alias, "node_modules", ".bin"), system]), "VIRTUAL_ENV": alias}
        new, _r, dropped = lc.strip_activation(env, variables, interpreter=away)
        check_eq(f"E3b a {how} does not widen what goes: an unrelated folder stays", dropped, [])
        # the same through the CLI, with the launcher found only on the stripped PATH
        in_venv = os.path.join(str(real_prefix / "Scripts"), "pytest")
        in_system = os.path.join(system, "pytest")
        root = project([profile()])
        run, buf = Run(returncode=0), io.StringIO()
        code = lc.main(["--deactivated", "--json"], run=run, which=which_in({in_venv, in_system}),
                       env={"PATH": os.pathsep.join([str(real_prefix / "Scripts"), system]), "VIRTUAL_ENV": alias},
                       out=buf, err=io.StringIO(), cwd=root)
        doc = json.loads(buf.getvalue())
        check_eq(f"E3b CLI: a {how} in VIRTUAL_ENV still resolves the system launcher",
                 (code, doc["profiles"][0]["resolved"]), (0, in_system))

    # a prefix that strips nothing says so
    root_dir = os.path.abspath(os.sep)
    notes = []
    new, removed, dropped = lc.strip_activation({"PATH": system, "VIRTUAL_ENV": root_dir}, variables,
                                                interpreter=away, notes=notes)
    check_eq("E3b a filesystem root strips nothing, removes the variable, and says so",
             (new["PATH"], dropped, removed, len(notes), "filesystem root" in " ".join(notes)),
             (system, [], ["VIRTUAL_ENV"], 1, True))
    venv = TMP / "holder" / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "bin").mkdir(parents=True)
    env = {"PATH": os.pathsep.join([str(venv / "Scripts"), str(venv / "bin"), system]), "VIRTUAL_ENV": str(venv)}
    for label, interp in (("its own Scripts", str(venv / "Scripts")),
                          ("a directory deeper inside it", str(venv / "Scripts" / "sub")),
                          ("the prefix itself", str(venv)), ("a parent of it", str(TMP / "holder"))):
        notes = []
        parent_env = dict(env, VIRTUAL_ENV=str(TMP / "holder")) if label == "a parent of it" else env
        new, removed, dropped = lc.strip_activation(parent_env, variables, interpreter=interp, notes=notes)
        check_eq(f"E3b a prefix that holds the interpreter's directory ({label}) strips nothing and says so",
                 (new["PATH"] == env["PATH"], dropped, removed, "interpreter" in " ".join(notes)),
                 (True, [], ["VIRTUAL_ENV"], True))
    notes = []
    new, _r, dropped = lc.strip_activation(env, variables, interpreter=str(TMP / "elsewhere"), notes=notes)
    check_eq("E3b the same prefix with the interpreter elsewhere strips, and notes nothing", (new["PATH"], notes), (system, []))
    new, _r, dropped = lc.strip_activation(env, variables, interpreter=str(TMP / "holder" / ".venv2"))
    check_eq("E3b an interpreter in a sibling directory that merely shares the prefix text does not count",
             new["PATH"], system)
    new, _r, dropped = lc.strip_activation(env, variables, interpreter="")
    check_eq("E3b an interpreter directory that is not known guards nothing", new["PATH"], system)

    # the result says which variables were removed, so a false `failed` can be understood
    conda_base = TMP / "conda-base"
    (conda_base / "Scripts").mkdir(parents=True)
    env = {"PATH": os.pathsep.join([str(conda_base / "Scripts"), system]), "CONDA_PREFIX": str(conda_base),
           "CONDA_DEFAULT_ENV": "base"}
    root = project([profile()])
    buf = io.StringIO()
    lc.main(["--deactivated", "--json"], run=Run(), which=which_in({"pytest"}), env=env, out=buf, err=io.StringIO(), cwd=root)
    doc = json.loads(buf.getvalue())
    check_eq("E3b CLI JSON names the removed variables, the PATH entries and the not-stripped notes",
             (doc["removed"]["variables"], doc["removed"]["path_entries"], doc["removed"]["skipped"]),
             (["CONDA_PREFIX"], [str(conda_base / "Scripts")], []))
    out = io.StringIO()
    lc.main(["--deactivated"], run=Run(), which=which_in({"pytest"}), env=env, out=out, err=io.StringIO(), cwd=root)
    text = out.getvalue()
    check_in("E3b CLI text names the removed variable", "removed variables: CONDA_PREFIX", text)
    check_in("E3b CLI text names the removed PATH entry", str(conda_base / "Scripts"), text)
    env = {"PATH": system, "VIRTUAL_ENV": root_dir}
    out = io.StringIO()
    lc.main(["--deactivated"], run=Run(), which=which_in({"pytest"}), env=env, out=out, err=io.StringIO(), cwd=root)
    check_in("E3b CLI text says which prefix was left alone and why", "filesystem root", out.getvalue())


# --- E4: the CLI -------------------------------------------------------------------------------

def cli(args, root, run=None, which=None, env=None):
    out, err = io.StringIO(), io.StringIO()
    code = lc.main(args, run=run or Run(), which=which or which_in({"pytest"}),
                   env=env if env is not None else {"PATH": ""}, out=out, err=err, cwd=root)
    return code, out.getvalue(), err.getvalue()


def cli_subprocess(args, root):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "launch_check.py"), *args],
                          cwd=str(root), capture_output=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=120)


def e4_cli():
    root = project([profile("api"), profile("ui", one=["npx", "playwright", "test", "<f>"])])
    before = snapshot(root)
    code, out, err = cli(["--json"], root, which=which_in({"pytest", "npx"}))
    doc = json.loads(out)
    check_eq("E4 --json: stdout is ONE JSON document (json.loads takes all of it)", code, 0)
    check_eq("E4 every profile is checked", [p["profile"] for p in doc["profiles"]], ["api", "ui"])
    check_eq("E4 the api profile is ok", doc["profiles"][0]["status"], "ok")
    check_eq("E4 the playwright profile has no collect form: not_checked, even though a fake run would say 0",
             (doc["profiles"][1]["status"], doc["profiles"][1]["reason"]),
             ("not_checked", "no collect form known for this runner"))
    check_eq("E4 one ok and one not_checked -> overall ok", doc["status"], "ok")
    check_eq("E4 it writes nothing (FR-45): the tree is unchanged", snapshot(root), before)
    code, out, _e = cli(["--profile", "ui", "--json"], root, which=which_in({"npx"}))
    check_eq("E4 --profile selects one", [p["profile"] for p in json.loads(out)["profiles"]], ["ui"])

    code, out, _e = cli(["--json"], root, run=Run(returncode=4, stderr=LAUNCHER_LINE.encode()))
    check_eq("E4 a failed profile still exits 0 (a reporter)", (code, json.loads(out)["status"]), (0, "failed"))
    code, out, _e = cli([], root, run=Run(returncode=4, stderr=LAUNCHER_LINE.encode()))
    check_in("E4 the text form names the cause and the evidence", "launcher_rejected_arguments", out)
    check_in("E4 the text form carries the evidence line", LAUNCHER_LINE, out)
    try:
        json.loads(out)
        text_is_json = True
    except ValueError:
        text_is_json = False
    check_eq("E4 without --json the output is text", text_is_json, False)

    # unknown profile: exit 2 naming the ids
    code, out, err = cli(["--profile", "nope", "--json"], root)
    check_eq("E4 an unknown --profile: exit 2", code, 2)
    check("E4 ... naming the known ids on stderr", "api" in err and "ui" in err and "nope" in err, err)
    check_eq("E4 ... and under --json stdout is JSON that names them", json.loads(out)["known"], ["api", "ui"])

    # unreadable config
    bad = project()
    (bad / "qa-factory" / "config.json").write_text("{nope", encoding="utf-8")
    code, out, err = cli(["--json"], bad)
    check_eq("E4 an unreadable config: exit 2", code, 2)
    check_in("E4 ... the message says what to do", "unreadable", err)
    check_eq("E4 ... stdout is still only JSON", json.loads(out)["status"], "error")
    arr = project()
    (arr / "qa-factory" / "config.json").write_text("[1]", encoding="utf-8")
    check_eq("E4 a config that is not an object: exit 2", cli([], arr)[0], 2)
    lone = Path(tempfile.mkdtemp(prefix="qa-lc-none-", dir=TMP))
    check_eq("E4 no project above the cwd: exit 2", cli([], lone)[0], 2)

    # profiles absent
    for label, root_ in (("absent", project()), ("empty", project([])), ("not a list", project({"a": 1})),
                         ("only non-objects", project(["x", 3]))):
        code, out, _e = cli(["--json"], root_)
        doc = json.loads(out)
        check_eq(f"E4 profiles {label}: exit 0 and JSON saying `no profile`",
                 (code, doc["status"], "no profile" in doc["message"]), (0, "no_profile", True))
    code, out, err = cli(["--profile", "x", "--json"], project())
    check_eq("E4 --profile with no profiles at all: exit 2", code, 2)

    # not_checked overall, and an unnamed profile
    code, out, _e = cli(["--json"], project([{"commands": {}}]))
    doc = json.loads(out)
    check_eq("E4 an unnamed profile is checked under `#0`, not_checked overall",
             (doc["profiles"][0]["profile"], doc["status"]), ("#0", "not_checked"))

    # subprocess: the real script, nothing launched (the program does not exist)
    accented = project([profile(one=["./bin/t\u00e9st/pytest", "<f>"], cwd=".")])
    done = cli_subprocess(["--json"], accented)
    check_eq("E4 subprocess --json: exit 0", done.returncode, 0)
    doc = json.loads(done.stdout.decode("utf-8"))
    check_eq("E4 subprocess: a missing program is executable_not_found (nothing was run)",
             (doc["status"], doc["profiles"][0]["cause"]), ("failed", "executable_not_found"))
    check_in("E4 subprocess: a non-ASCII path survives in the JSON", "t\u00e9st", doc["profiles"][0]["evidence"])
    check_eq("E4 subprocess: stderr is empty on a normal run", done.stderr, b"")
    before = snapshot(accented)
    cli_subprocess([], accented)
    check_eq("E4 subprocess: the tree is unchanged", snapshot(accented), before)
    done = cli_subprocess(["--profile", "zzz", "--json"], accented)
    check_eq("E4 subprocess: an unknown profile exits 2", done.returncode, 2)
    done = cli_subprocess(["--json"], lone)
    check_eq("E4 subprocess: no project exits 2", done.returncode, 2)


# --- E5: the battery ---------------------------------------------------------------------------

def e5_battery():
    root = project()
    which = which_in({"pytest"})
    pairs = sum([[f"--o{i}", f"<p{i}>"] for i in range(125)], [])
    argv = ["pytest"] + pairs + [f"a{i}" for i in range(249)]
    check_eq("E5 the argv has 500 tokens", len(argv), 500)
    run = Run()
    got = probe(profile(one=argv), root, run, which)
    check_eq("E5 500 tokens: reduced to the 249 plain ones plus the suffix",
             run.calls[0][0], ["pytest"] + [f"a{i}" for i in range(249)] + ["--collect-only", "-q", PARTIAL_FLAG])
    check_eq("E5 500 tokens: ok", got["status"], "ok")
    argv = ["pytest"] + [f"--x{i}" if i % 2 else f"v{i}" for i in range(499)]
    got = probe(profile(one=argv), root, Run(returncode=4, stderr=b"unrecognized arguments: --x999\n"), which)
    check_eq("E5 500 tokens, an option not in the argv: unknown", got["cause"], "unknown")

    # 2 MB of stderr
    filler = ("E " * 50 + "\n") * 21000
    check("E5 the filler is at least 2 MB", len(filler) >= 2 * 1024 * 1024, str(len(filler)))
    started = time.time()
    got = probe(profile(), root, Run(returncode=2, stderr=(filler + "ModuleNotFoundError: No module named 'q'\n").encode()), which)
    check_eq("E5 2 MB of stderr: the marker at the end is found", got["cause"], "dependency_missing")
    check("E5 2 MB of stderr: evidence within 200 chars", len(got["evidence"]) <= 200, str(len(got["evidence"])))
    one_line = "ImportError: " + "y" * (2 * 1024 * 1024)
    got = probe(profile(), root, Run(returncode=2, stderr=one_line.encode()), which)
    check_eq("E5 one 2 MB line: evidence clipped to 200", (got["cause"], len(got["evidence"])), ("dependency_missing", 200))
    check("E5 both 2 MB runs took under 20 s", time.time() - started < 20, f"{time.time() - started:.1f}s")

    # CRLF
    got = probe(profile(), root, Run(returncode=2, stderr=b"a\r\nERROR collecting tests/x.py\r\nb\r\n"), which)
    check_eq("E5 CRLF: the evidence has no carriage return", got["evidence"], "ERROR collecting tests/x.py")
    got = probe(profile(), root, Run(returncode=2, stdout="ERROR collecting q\r\n"), which)
    check_eq("E5 str output is read like bytes", got["cause"], "collection_error")

    # non-UTF-8 bytes
    raw = b"\xff\xfe garbled \x80\n\x80ModuleNotFoundError: No module named '\xc3\x28'\n"
    got = probe(profile(), root, Run(returncode=2, stderr=raw), which)
    check_eq("E5 non-UTF-8 bytes: still classified, no exception", got["cause"], "dependency_missing")
    got = probe(profile(), root, Run(returncode=2, stderr=b"\xff\xfe\xfd"), which)
    check_eq("E5 only non-UTF-8 bytes: unknown, no exception", got["cause"], "unknown")

    # a non-ASCII resolved path
    fancy = os.path.join(str(TMP), "b\u00edn \u4e2d", "pytest")
    code, out, _e = cli(["--json"], project([profile()]), which=which_in({fancy}),
                        env={"PATH": os.path.dirname(fancy)})
    doc = json.loads(out)
    check_eq("E5 a non-ASCII resolved path round-trips through the JSON", doc["profiles"][0]["resolved"], fancy)
    code, out, _e = cli([], project([profile()]), which=which_in({fancy}), env={"PATH": os.path.dirname(fancy)})
    check_in("E5 ... and through the text form", fancy, out)


# --- E6: the data file -------------------------------------------------------------------------

def e6_data():
    data = real_data()
    for cause in data["causes"]:
        if cause["id"] != "unknown":
            check(f"E6 {cause['id']}: markers present", bool(cause["markers"]) and all(cause["markers"]))
        role = cause["doors"]["role"]
        check(f"E6 {cause['id']}: a door sentence", len(role) > 40, role)
        check_eq(f"E6 {cause['id']}: door() reads it", lc.door(cause["id"]), role)
        check_eq(f"E6 {cause['id']}: door(cause, 'role') is the same text", lc.door(cause["id"], "role"), role)
        check_in(f"E6 {cause['id']}: the role's door is the digest line", f"`launch: {cause['id']}`", role)
        check(f"E6 {cause['id']}: the config is not the role's to edit",
              "do not edit qa-factory/config.json" in role.lower(), role)
        check_not_in(f"E6 {cause['id']}: no door names the wrong party's command", "config_contract.py", role)
    check_eq("E6 launcher_rejected_arguments: the door is the spec's text, verbatim",
             lc.door("launcher_rejected_arguments"), LAUNCHER_DOOR)
    check_eq("E6 door() of an unknown cause id is empty", lc.door("nope"), "")
    check("E6 launcher_rejected_arguments carries its option patterns",
          bool(next(c for c in data["causes"] if c["id"] == "launcher_rejected_arguments")["named_option_patterns"]))
    for path in (REAL_DATA, SCRIPTS / "launch_check.py", Path(__file__)):
        blob = path.read_bytes()
        check(f"E6 no control byte (FR-29) in {path.name}", not any(b in blob for b in (7, 8, 11, 12, 27)))
        check(f"E6 no Cyrillic (FR-30) in {path.name}",
              not re.search("[\u0400-\u04ff]", blob.decode("utf-8")))
    check_eq("E6 the data file decodes as UTF-8 and loads", lc.load_data()[1], "")


# --- E6b: doors keyed by audience --------------------------------------------------------------

def e6b_doors():
    data = real_data()
    audiences = ["gate", "onboarding", "role"]
    # words a person at gate A must not meet: script names, field names, the role's digest line
    forbidden = (".py", "config", "argv", "profile", "commands", "test_command_templates", "json", "launch_check",
                 "qa-factory", "--mine", "`launch:", "digest", "Do not edit")
    for cause in data["causes"]:
        cid, doors = cause["id"], cause["doors"]
        check_eq(f"E6b {cid}: the audiences are role, gate and onboarding", sorted(doors), audiences)
        for audience in audiences:
            check(f"E6b {cid}: the {audience} door is a sentence", len(doors[audience]) > 60, doors[audience])
            check_eq(f"E6b {cid}: door(cause, {audience!r}) reads it", lc.door(cid, audience), doors[audience])
        check_eq(f"E6b {cid}: the three doors are three different texts", len(set(doors.values())), 3)
        gate = doors["gate"].replace("<argv0>", "X").replace("<resolved>", "Y")
        for word in forbidden:
            check_not_in(f"E6b {cid}: the gate door has no `{word}`", word, gate)
        check_in(f"E6b {cid}: the gate door says the project's own launcher is what the factory needs",
                 "your project's own launcher", gate)
        check_not_in(f"E6b {cid}: the gate door is not the role's text", "launch: ", doors["gate"])
        onboarding = doors["onboarding"]
        check_in(f"E6b {cid}: the onboarding door says to choose a wrapper argv", "wrapper argv", onboarding)
        check_in(f"E6b {cid}: ... to rewrite that profile's argvs and templates",
                 "rewrite that profile's `commands` argvs and `test_command_templates`", onboarding)
        check_in(f"E6b {cid}: ... and to run the check again", "launch_check.py --deactivated --json", onboarding)
        check_not_in(f"E6b {cid}: the onboarding door is not the role's `launch:` digest line", "`launch: ", onboarding)
    check_eq("E6b the role's door is what door(cause) with one argument gives", lc.door("launcher_rejected_arguments"),
             LAUNCHER_DOOR)
    check_in("E6b the gate door for a rejected launcher carries the fill-ins for the caller", "<resolved>",
             lc.door("launcher_rejected_arguments", "gate"))
    check_eq("E6b door() of an unknown cause is empty for every audience",
             [lc.door("nope", a) for a in audiences], ["", "", ""])

    # a missing audience is empty, never another audience's text
    partial = {"causes": [{"id": "only_role", "markers": ["m"], "doors": {"role": "the role's sentence"}},
                          {"id": "none", "markers": ["n"], "doors": {}}]}
    got = with_data(partial, lambda: [lc.door("only_role"), lc.door("only_role", "role"), lc.door("only_role", "gate"),
                                      lc.door("only_role", "onboarding"), lc.door("only_role", "nope"),
                                      lc.door("only_role", None), lc.door("only_role", ["gate"]),
                                      lc.door("none"), lc.door("none", "gate")])
    check_eq("E6b a cause with only a role door: gate and onboarding are empty (no fallback to the role's text)", got,
             ["the role's sentence", "the role's sentence", "", "", "", "", "", "", ""])
    only_gate = {"causes": [{"id": "g", "markers": ["m"], "doors": {"gate": "the gate's sentence"}}]}
    got = with_data(only_gate, lambda: [lc.door("g"), lc.door("g", "gate"), lc.door("g", "onboarding")])
    check_eq("E6b a cause with no role door: the default audience is still `role`, so it is empty, not the gate's",
             got, ["", "the gate's sentence", ""])


# --- E7: the onboarding text -------------------------------------------------------------------

def e7_onboarding():
    text = ONBOARDING.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    # The two commands the text gives are run, as written (placeholders filled), against a
    # temporary project: the form is what `project_decisions.py` really accepts.
    # Anchored on the launch check's own commands: since 341c81e0 (OH3-29) the text carries earlier
    # `add` / `add-finding` commands (the no-framework case) that a looser pattern matched first.
    add_re = re.search(r"`(project_decisions\.py --root \. add --field-ref /profiles/<n>/commands/one_test/argv "
                       r"--essence \"[^\"]*\" --asked \"[^\"]*\")`", flat)
    find_re = re.search(r"`(project_decisions\.py --root \. add-finding --essence \"[^\"]*\" --scope \S+ "
                        r"--witness \"[^\"]*\" --idempotency-key launch-<profile-id>)`", flat)
    check("E7 the DD command and the finding command are both in the text", bool(add_re and find_re))
    if add_re and find_re:
        import shlex
        fills = {"<n>": "0", "<profile-id>": "api", "<cause>": "launcher_rejected_arguments",
                 "<evidence line>": "pytest: error: unrecognized arguments: --reruns",
                 "<the question as it was put>": "Which command starts your tests?"}
        workdir = Path(tempfile.mkdtemp(prefix="qa-lc-dd-", dir=TMP))
        (workdir / "qa-factory").mkdir()
        outcomes = []
        for label, found in (("DD", add_re), ("finding", find_re)):
            command = found.group(1)
            for placeholder, value in fills.items():
                command = command.replace(placeholder, value)
            words = shlex.split(command)
            check_eq(f"E7 the {label} command starts with the script", words[0], "project_decisions.py")
            words[words.index("--root") + 1] = str(workdir)
            done = subprocess.run([sys.executable, "-B", str(SCRIPTS / words[0]), *words[1:]], capture_output=True,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=120)
            outcomes.append((label, done.returncode, done.stdout.decode("utf-8", "replace")[:300],
                             done.stderr.decode("utf-8", "replace")[-300:]))
            check_eq(f"E7 the {label} command as written is accepted by project_decisions.py",
                     done.returncode, 0)
        backlog = (workdir / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8") \
            if (workdir / "qa-factory" / "factory-backlog.md").is_file() else ""
        check_in("E7 the DD row holds the pointer of the profile's argv", "/profiles/0/commands/one_test/argv", backlog)
        check_in("E7 the DD row holds the question as it was put", "Which command starts your tests?", backlog)
        check_in("E7 the finding row holds the witness with the evidence line", "unrecognized arguments: --reruns", backlog)
        check_in("E7 the finding is keyed by the profile", "idempotency:launch-api", backlog)
        # the form is exact: without the question the DD command is refused
        bare = shlex.split(add_re.group(1).replace("<n>", "0").replace("<profile-id>", "api")
                           .replace("<cause>", "c").replace("<evidence line>", "e"))
        cut = bare.index("--asked")
        bare = bare[:cut]
        bare[bare.index("--root") + 1] = str(workdir)
        refused = subprocess.run([sys.executable, "-B", str(SCRIPTS / bare[0]), *bare[1:]], capture_output=True,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=120)
        check("E7 negative control: the same DD command without `--asked` is refused (so `--asked` is required)",
              refused.returncode != 0, refused.stderr.decode("utf-8", "replace")[-200:])


def e8_partial_collect():
    """RH1-3: 3.1 the runner's partial-collect facts are data and are validated (K-3.1-*); 3.4b `probe` goes on past
    broken test files (K-3.4b-*), with the live case of the plan review (E3-20) as the fixture."""
    data = real_data()
    base = {"tool": "pytest", "append": ["--collect-only", "-q"], "ok_exits": [0, 5]}
    full = data["collect_forms"][0]

    def row_problem(**changes):
        row = dict(full, **changes)
        row = {k: v for k, v in row.items() if v is not None}
        return with_data(dict(data, collect_forms=[row]), lc.load_data)[1]
    check_eq("K-3.1-valid the shipped row loads", row_problem(), "")
    for label, changes, key in (
            ("continue_tokens that is not a list", {"continue_tokens": "--x"}, "continue_tokens"),
            ("an empty string in continue_tokens", {"continue_tokens": [""]}, "continue_tokens"),
            ("partial_exits that is not a list", {"partial_exits": 1}, "partial_exits"),
            ("a boolean in partial_exits", {"partial_exits": [True]}, "partial_exits"),
            ("the runner's own 124 in partial_exits", {"partial_exits": [124]}, "partial_exits"),
            ("127 in partial_exits", {"partial_exits": [127]}, "partial_exits"),
            ("an ok exit in partial_exits", {"partial_exits": [0]}, "partial_exits"),
            ("broken_line that does not compile", {"broken_line": "(?P<path>"}, "broken_line"),
            ("broken_line without the group path", {"broken_line": "^ERROR (.*)$"}, "broken_line"),
            ("count_line without the group selected", {"count_line": "(\\d+) tests"}, "count_line"),
            ("stopped_line that does not compile", {"stopped_line": "["}, "stopped_line"),
            ("a non-string regex", {"stopped_line": 5}, "stopped_line"),
            ("partial_exits without broken_line", {"broken_line": None}, "partial_exits"),
            ("partial_exits without count_line", {"count_line": None}, "partial_exits")):
        why = row_problem(**changes)
        check(f"K-3.1-refuse {label}: the load is refused and names the key `{key}`", key in why and "collect_forms[0]" in why, why)
    check_eq("K-3.1-optional a row with no partial-collect keys at all is valid, and carries none",
             with_data(dict(data, collect_forms=[base]), lambda: lc.runner_row(["pytest"])), (base, ""))
    check_eq("K-3.1-optional broken_line alone (no partial_exits) is valid",
             row_problem(partial_exits=None, continue_tokens=None, count_line=None, stopped_line=None), "")

    # --- 3.4b: the probe -------------------------------------------------------------------------
    root = project()
    out_ok = ("tests/ok/test_a.py::test_a\n\n==== short test summary info ====\n"
              "ERROR tests/mcp/test_mcp_config_clone.py\nERROR tests/servicenow_budget - ModuleNotFoundError: No module named 'x'\n"
              "!!!!! Interrupted: 2 errors during collection !!!!!\n1 test collected, 2 errors in 1s\n").encode()
    run = Run(returncode=1, stdout=out_ok)
    got = probe(profile(), root, run, which_in({"pytest"}))
    check_eq("K-3.4b-live the live case (a broken module and a broken folder): status ok, exit 1 kept",
             (got["status"], got["cause"], got["exit_code"]), ("ok", None, 1))
    check_eq("K-3.4b-live ... with the two files named, folder included",
             [b["path"] for b in got["broken_files"]], ["tests/mcp/test_mcp_config_clone.py", "tests/servicenow_budget"])
    check_in("K-3.4b-live ... and the reason says the launcher works", "2 test files could not be collected", got["reason"])
    check_in("K-3.4b-live ... naming them", "tests/servicenow_budget", got["reason"])
    check_in("K-3.4b-live ... the launcher works", "the launcher works", got["reason"])
    check_eq("K-3.4b-flag the flag of the row is on the command, once, after the form's own append",
             run.calls[0][0][-3:], ["--collect-only", "-q", PARTIAL_FLAG])
    run = Run(returncode=1, stdout=out_ok)
    probe(profile(one=["pytest", "<test-file>", PARTIAL_FLAG]), root, run, which_in({"pytest"}))
    check_eq("K-3.4b-dup a flag already in the profile's command is not added twice", run.calls[0][0].count(PARTIAL_FLAG), 1)
    run = Run(returncode=0)
    got = probe(profile(), root, run, which_in({"pytest"}))
    check_eq("K-3.4b-clean a clean collect: ok, and no broken_files field at all",
             (got["status"], "broken_files" in got), ("ok", False))

    def run_with(text, code=1, **kw):
        return probe(profile(**kw), root, Run(returncode=code, stdout=text.encode()), which_in({"pytest"}))
    got = run_with("ERROR tests/test_bad.py - ImportError: x\nno tests collected, 1 error in 1s\n")
    check_eq("K-3.4b-all everything broken (nothing collected): failed, classified as before",
             (got["status"], got["cause"], "broken_files" in got), ("failed", "dependency_missing", False))
    got = run_with("ERROR tests/test_bad.py\nno tests collected (5 deselected), 1 error in 1s\n")
    check_eq("K-3.4b-deselected the REAL line when a filter left nothing, one file broken: ok with the field, never failed (B1)",
             (got["status"], len(got["broken_files"])), ("ok", 1))
    got = run_with("tests/a.py::t\nERROR tests/test_bad.py\n!!! stopping after 1 failures !!!\n1 test collected, 1 error in 1s\n")
    check_eq("K-3.4b-stopped `-x` in the addopts: failed, never ok", (got["status"], "broken_files" in got), ("failed", False))
    check_in("K-3.4b-stopped ... and the reason says why", "addopts stop the collect at the first error", got["reason"])
    got = run_with("tests/a.py::t\nERROR tests/test_bad.py\n")
    check_eq("K-3.4b-unread no count line at exit 1: failed (unread), never ok", got["status"], "failed")
    got = run_with("", code=1)
    check_eq("K-3.4b-unread empty output, exit 1: failed", got["status"], "failed")
    got = run_with("ImportError while loading conftest\n", code=4)
    check_eq("K-3.4b-root a root conftest that cannot load (exit 4): failed", (got["status"], got["cause"]),
             ("failed", "dependency_missing"))
    banner = run_with("tests/a.py::t\nERROR tests/test_bad.py\nERROR HARNESS-V2\n1 test collected, 1 error in 1s\n")
    check_eq("K-3.4b-count a count that disagrees with the files named: failed, never ok", banner["status"], "failed")

    # a row without the flag: one broken file hides the rest, as before (E3-4)
    noflag = dict(full)
    for key in ("continue_tokens", "partial_exits"):
        noflag.pop(key)
    run = Run(returncode=1, stdout=out_ok)
    got = with_data(dict(data, collect_forms=[noflag]), lambda: probe(profile(), root, run, which_in({"pytest"})))
    check_eq("K-3.1-noflag a runner row without continue_tokens: no flag on the command, exit 1 is failed as before",
             (PARTIAL_FLAG in run.calls[0][0], got["status"]), (False, "failed"))
    nopartial = dict(full)
    nopartial.pop("partial_exits")
    got = with_data(dict(data, collect_forms=[nopartial]), lambda: probe(profile(), root, Run(returncode=1, stdout=out_ok),
                                                                         which_in({"pytest"})))
    check_eq("K-3.1-noflag ... and a row without partial_exits reads exit 1 as failed", got["status"], "failed")
    check_eq("K-3.4b-names more than five broken files: five named, the field holds all",
             (lambda r: (len(r["broken_files"]), "(+2 more)" in r["reason"]))(
                 run_with("a.py::t\n" + "".join(f"ERROR t/b{n}.py\n" for n in range(7)) + "1 test collected, 7 errors in 1s\n")),
             (7, True))


def e9_one_reader():
    """OH3-27 round 2 (AR-13): `_argv_of` and `probe` read `commands` through `profile_contract`, and `story_step._hand_detail`
    does too (its narrow test lives here: test_story_step.py is a big file the node does not run)."""
    import inspect
    import profile_contract as pc
    root = project()
    which = which_in({"pytest"})
    src = inspect.getsource(lc._argv_of)
    check("O9-1 `_argv_of` calls the reader and holds no parsing of its own",
          "command_argv" in src and "isinstance" not in src and "str(" not in src, src)
    # the empty-words edge: what `command_argv` returns is what `_argv_of` returns
    for label, spec, want in (
            ("no spec", None, ([], "")),
            ("no argv key", {"cwd": "."}, ([], "")),
            ("an empty argv", {"argv": []}, ([], "")),
            ("only empty and blank words: no command (the reader drops them)", {"argv": ["", "  "]}, ([], "")),
            ("an empty word between words is dropped", {"argv": ["pytest", "", "-q"]}, (["pytest", "-q"], "")),
            ("numbers are words", {"argv": ["x", 5]}, (["x", "5"], ""))):
        check_eq(f"O9-1 _argv_of {label}", lc._argv_of(spec), want)
        check_eq(f"O9-1 _argv_of {label}: the reader's own answer", lc._argv_of(spec), (pc.command_argv(spec)[0], ""))
    for label, spec in (("a string argv", {"argv": "pytest -q"}), ("a null word", {"argv": ["pytest", None]}),
                        ("a boolean word", {"argv": [True]}), ("a spec that is a string", "pytest")):
        words, why = lc._argv_of(spec)
        check_eq(f"O9-2 _argv_of {label}: `(None, the reader's problem)`", (words, why), (None, pc.command_argv(spec)[1]))
        check_in(f"O9-2 _argv_of {label}: the problem names the sample", pc.SHAPE_FILE, why)

    # probe: a command_argv refusal, an unparsable commands, empty words
    for label, prof, needle in (
            ("commands is a list", {"profile_id": "api", "commands": [{"kind": "one_test", "argv": ["pytest"]}]},
             "commands is a list"),
            ("one_test is a string", {"profile_id": "api", "commands": {"one_test": "pytest"}},
             "commands.one_test: the command is a string"),
            ("collect is a string", {"profile_id": "api", "commands": {"collect": "pytest"}},
             "commands.collect: the command is a string"),
            ("a boolean word in argv", profile(one=["pytest", True]), "commands.one_test: argv holds a boolean")):
        run = Run()
        got = probe(prof, root, run, which)
        check_eq(f"O9-3 probe {label}: not_checked, nothing launched", (got["status"], run.calls), ("not_checked", []))
        check_in(f"O9-3 probe {label}: the reason is the reader's problem", needle, got["reason"])
    run = Run()
    got = probe(profile(one=["", " "], collect=["pytest", "--collect-only"]), root, run, which)
    check_eq("O9-4 probe: an all-empty one_test argv counts as no one_test, the collect command runs",
             (got["status"], run.calls[0][0][:2]), ("ok", ["pytest", "--collect-only"]))
    run = Run()
    got = probe(profile(one=["", " "]), root, run, which)
    check_eq("O9-4 probe: an all-empty one_test argv and no collect: not_checked, nothing launched",
             (got["status"], run.calls), ("not_checked", []))
    run = Run()
    got = probe(profile(one=["pytest", "", "<test-file>"]), root, run, which)
    check_eq("O9-4 probe: an empty word inside the command is dropped, the launch has none",
             ("" in run.calls[0][0], got["status"]), (False, "ok"))

    # the reader itself cannot be loaded (a None entry makes the import fail): "cannot tell", never a crash, nothing launched
    held = sys.modules.get("profile_contract")
    sys.modules["profile_contract"] = None
    try:
        words, why = lc._argv_of({"argv": ["pytest"]})
        check_eq("O9-6 _argv_of with the reader unloadable: no argv", words, None)
        check_in("O9-6 _argv_of with the reader unloadable: says the reader could not be loaded",
                 "the profile reader could not be loaded", why)
        run = Run()
        got = probe(profile(), root, run, which)
        check_eq("O9-6 probe with the reader unloadable: not_checked, nothing launched",
                 (got["status"], run.calls), ("not_checked", []))
        check_in("O9-6 probe with the reader unloadable: says the reader could not be loaded",
                 "the profile reader could not be loaded", got["reason"])
    finally:
        if held is None:
            sys.modules.pop("profile_contract", None)
        else:
            sys.modules["profile_contract"] = held

    # story_step._hand_detail through the same reader
    import story_step
    import gate_preflight
    art = Path(tempfile.mkdtemp(prefix="qa-lc-hd-", dir=TMP))
    saved = story_step._config, gate_preflight.s5_profiles
    gate_preflight.s5_profiles = lambda _config, _root: {"api": {"cases": ["TC-1"]}}
    rows = [{"selector": "tests/test_one.py::test_one"}]
    try:
        for label, commands, want in (
                ("a valid command, placeholders left out",
                 {"one_test": {"argv": ["python", "-m", "pytest", "<test-file>", "", "-q"], "cwd": "."}},
                 "api: python -m pytest -q tests/test_one.py::test_one"),
                ("commands is a list: no command words, the selectors stay",
                 [{"kind": "one_test", "argv": ["pytest"]}], "api: tests/test_one.py::test_one"),
                ("one_test is a string", {"one_test": "pytest"}, "api: tests/test_one.py::test_one"),
                ("argv is a string: never read by letters", {"one_test": {"argv": "pytest -q"}},
                 "api: tests/test_one.py::test_one")):
            story_step._config = lambda commands=commands: {"profiles": [{"profile_id": "api", "commands": commands}]}
            try:
                got = story_step._hand_detail(art, "TC-1", rows)
            except Exception as exc:
                got = f"RAISED {type(exc).__name__}: {exc}"
            check_eq(f"O9-5 _hand_detail {label}", got, want)
    finally:
        story_step._config, gate_preflight.s5_profiles = saved


def e10_runner_identity():
    """EP1-1: `runner_identity`, the one reader of which runner a command starts, and the `selection` key it reads."""
    data = real_data()
    forms = data["run_forms"]["forms"]
    pw = lc.runner_identity(["npx", "playwright", "test", "tests/pytest"])
    check_eq("E10 the shipped table: playwright test is the form `playwright-test` with its selection",
             (pw["form_id"], pw["problem"], pw["no_direct_form"], pw["collect_row"]),
             ("playwright-test", "", "", None))
    check_eq("E10 ... the selection is the table's own row, joined by ` \\u203a `",
             (pw["selection"] or {}).get("title_join"), " " + chr(0x203a) + " ")
    check_eq("E10 ... and states the form, args, report id and classname mode",
             {k: pw["selection"].get(k) for k in ("form", "args", "report_id", "classname", "escape_file")},
             {"form": "file_line", "args": ["{file}:{line}"], "report_id": "{classname}::{title_path}",
              "classname": "file_suffix", "escape_file": True})
    py = lc.runner_identity(["poetry", "run", "pytest", "-q"])
    check_eq("E10 pytest: the form and the collect row, no selection, no 'no form' words",
             (py["form_id"], (py["collect_row"] or {}).get("tool"), py["selection"], py["problem"], py["no_direct_form"]),
             ("pytest", "pytest", None, "", ""))
    jest = lc.runner_identity(["npx", "jest"])
    check_eq("E10 a form with no `selection` (jest): selection None, no 'no form' words (the code builds nothing)",
             (jest["form_id"], jest["selection"], jest["problem"], jest["no_direct_form"]), ("jest", None, "", ""))
    own = lc.runner_identity(["node", "scripts/run-playwright.mjs"])
    check_eq("E10 the project's own script: no form, no selection, the 'no form' words name argv[0]",
             (own["form_id"], own["selection"], own["problem"]), ("", None, ""))
    check_eq("E10 ... the words", own["no_direct_form"],
             "this command starts node, the project's own script; the factory does not read inside it, "
             "so it builds no selector for it")
    check_eq("E10 an empty or absent command states nothing",
             [lc.runner_identity([])["no_direct_form"], lc.runner_identity(None)["no_direct_form"]], ["", ""])
    saved = lc.CAUSES_PATH
    lc.CAUSES_PATH = TMP / "does-not-exist.json"
    try:
        gone = lc.runner_identity(["npx", "playwright", "test"])
    finally:
        lc.CAUSES_PATH = saved
    check_eq("E10 a table that cannot be read: the problem named, no selection, 'no form' not claimed",
             (bool(gone["problem"]), gone["selection"], gone["no_direct_form"]), (True, None, ""))

    def bad_row(change):
        content = json.loads(json.dumps(data))
        row = next(r for r in content["run_forms"]["forms"] if r["id"] == "playwright-test")
        if change is None:
            row["selection"] = "file_line"
        else:
            row["selection"] = dict(row["selection"])
            row["selection"].pop(change, None) if change != "classname" else row["selection"].update(classname="path")
        return content
    for label, change in (("not an object", None), ("no report_id", "report_id"), ("no args", "args"),
                          ("no title_join", "title_join"), ("a classname other than file / file_suffix", "classname")):
        content = bad_row(change)
        loaded, note = with_data(content, lc.load_data)
        check_eq(f"E10 load_data over a selection with {label}: the table loads, the row is left out and named",
                 (loaded is not None, "playwright-test" in loaded["selection_by_form"],
                  "playwright-test" in loaded["selection_problems"]), (True, False, True))
        got = with_data(content, lambda: lc.runner_identity(["npx", "playwright", "test"]))
        check_eq(f"E10 runner_identity over a selection with {label}: problem named, selection None, no 'no form'",
                 (bool(got["problem"]), got["selection"], got["no_direct_form"], got["form_id"]),
                 (True, None, "", "playwright-test"))
        other = with_data(content, lambda: lc.runner_identity(["pytest"]))
        check_eq("E10 ... a bad row of one form is not a problem of another form (pytest)",
                 (other["problem"], other["form_id"]), ("", "pytest"))
    plain = json.loads(json.dumps(data))
    for row in plain["run_forms"]["forms"]:
        row.pop("selection", None)
    loaded, _ = with_data(plain, lc.load_data)
    check_eq("E10 a table with no `selection` at all loads as before, with an empty map",
             (loaded is not None, loaded["selection_by_form"], loaded["selection_problems"]), (True, {}, {}))
    check_eq("E10 the shipped table keeps all its forms (the selection key is one more key, not a replacement)",
             len(forms) >= 20 and all("id" in f and "argv" in f for f in forms), True)
    # AR-1: no runner name in the readers' code; the positive control is the data file (the same search finds it there).
    # (Older prose in both files names the `pytest-playwright` plugin and an example command; the new readers name no runner.)
    import inspect
    import node_ids
    for label, fn in (("node_ids.is_pytest", node_ids.is_pytest), ("node_ids._left_is_other_runner",
                      node_ids._left_is_other_runner), ("launch_check.runner_identity", lc.runner_identity),
                      ("launch_check._selection_rows", lc._selection_rows)):
        check_eq(f"E10 AR-1: {label} names no playwright", "playwright" in inspect.getsource(fn).lower(), False)
    check_eq("E10 AR-1 control: the same search finds playwright in launch-causes.json",
             "playwright" in REAL_DATA.read_text(encoding="utf-8").lower(), True)


try:
    e10_runner_identity()
    e1_classify()
    e1b_confirmed_causes()
    e2_probe()
    e2b_collect_forms()
    e2d_runner_row()
    e2c_placeholders()
    e3_deactivated()
    e3b_deactivated_paths()
    e4_cli()
    e5_battery()
    e6_data()
    e6b_doors()
    e7_onboarding()
    e8_partial_collect()
    e9_one_reader()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
finish("launch_check")
