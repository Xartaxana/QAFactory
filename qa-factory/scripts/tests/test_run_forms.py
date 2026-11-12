#!/usr/bin/env python3
"""B-404: the quiet-runs guard reads the forms of a test launch from data, not from a regex.

Until now the guard knew one runner: `pytest`, written as a regex in hooklib.py. A project on
dotnet, jest or gradle was not guarded at all - the prefilter did not even load the guard for it.
The forms are closed variety (FR-13), so they live in references/launch-causes.json `run_forms`;
hooklib.direct_test_form reads them, and what stays in code is shell grammar only.

This file is the whole proof (acceptance keys 1-15 of docs/tasks/specs/t-466-b-404-run-forms.md):
every form is blocked in every spelling of a real launch, the near misses are not, a diagnostic
and run_suite.py exempt only their own command segment, the data failing never leaves the guard
with fewer forms than it had, and - key 13 - NOTHING the old regex blocked stops being blocked
except a named list. The old regex is frozen below, inside this file, so that key does not
depend on the code under test.
"""
import contextlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import hooklib as H  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import launch_check as LC  # noqa: E402

FORM_IDS = ["pytest", "dotnet-test", "jest", "vitest", "mocha", "playwright-test",
            "npm-test", "yarn-test", "pnpm-test", "bun-test", "go-test", "cargo-test",
            "mvn-test", "mvn-verify", "mvnw-test", "mvnw-verify",
            "gradle-test", "gradle-check", "gradlew-test", "gradlew-check", "rspec", "phpunit"]

# Key 13: today's matcher, verbatim from hooklib.py before B-404 (:425-436), frozen.
OLD_DIRECT = re.compile(r"(?:^|[;&|(]\s*|\brun\s+|python(?:3)?\s+-m\s+)pytest(?![\w.-])", re.MULTILINE)
OLD_DIAG = re.compile(r"--collect-only|--co\b|--version|--help|(?<!\S)-h\b|--fixtures|--markers")


def old_is_direct_test_run(command: str) -> bool:
    cmd = command or ""
    if "run_suite" in cmd:
        return False
    if not OLD_DIRECT.search(cmd):
        return False
    return not OLD_DIAG.search(cmd)


def dq(text: str) -> str:
    """`text` as ONE bash double-quoted word, escaped the way bash reads it back."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def nest(levels: int, inner: str) -> str:
    out = inner
    for _ in range(levels):
        out = "bash -c " + dq(out)
    return out


def verdicts(name: str, commands, expected: bool, dialects=("bash",)) -> None:
    """One check per group; the failing commands are named in the red line (P16: the id of the case)."""
    wrong = [f"{c!r} [{d}]" for c in commands for d in dialects if H.is_direct_test_run(c, d) is not expected]
    check(f"{name}: {len(commands)} command(s), all {'blocked' if expected else 'passed'}", not wrong,
          "; ".join(wrong))


def shapes(argv: list) -> list:
    """Every spelling of one launch that key 2 asks for."""
    text = " ".join(argv)
    rest = " ".join(argv[1:])
    win = ".venv\\Scripts\\" + argv[0] + ".exe" + (" " + rest if rest else "")
    return [text, "/usr/bin/" + text, win, text.upper(), "cd x && " + text, "nohup " + text,
            "HEADLESS=1 " + text, f'bash -c "{text}"', f'bash -lc "cd app && {text}"',
            f'pwsh -Command "{text}"', f'pwsh -NoProfile -Command "cd app; {text}"',
            f'echo "$({text})"']


# --- key 1 ---------------------------------------------------------------------------------------

def k1_shipped_data() -> None:
    check_eq("k1 the shipped run_forms have no invalid item", H.run_forms_problems(), [])
    check_eq("k1 the form ids are exactly the R1 list", [f["id"] for f in H.run_forms()["forms"]], FORM_IDS)
    check_eq("k1 the shipped data is not the fallback", H.run_forms()["fallback"], False)
    data, note = LC.load_data()
    check_eq("k1 launch_check.load_data() still reads the file (E10)", note, "")
    check_eq("k1 collect_forms is unchanged except the two B-407 runner facts and the five RH1-3 partial-collect keys "
             "(continue_tokens, partial_exits, broken_line, count_line, stopped_line) and the three RH2-9 timeout keys "
             "(timeout_kill_line, timeout_failure_message, timeout_header_line)",
             data["collect_forms"], [{"tool": "pytest", "append": ["--collect-only", "-q"], "ok_exits": [0, 5],
                                      "not_executed_exits": [2, 3, 4, 5], "node_ids": "pytest",
                                      "continue_tokens": ["--continue-on-collection-errors"], "partial_exits": [1],
                                      "broken_line": r"^ERROR (?P<path>\S+)(?: - (?P<cause>.*))?$",
                                      "count_line": r"^=*\s*(?:(?P<selected>\d+)(?:/(?P<total>\d+))?|no) tests? collected"
                                                    r"(?: \((?P<deselected>\d+) deselected\))?(?:, (?P<errors>\d+) errors?)?",
                                      "stopped_line": r"stopping after \d+ failures",
                                      "timeout_kill_line": r"^\+{3,} Timeout \+{3,}\s*$",
                                      "timeout_failure_message": r"^Failed: Timeout \(?>\s*(?P<limit>[0-9]+(?:\.[0-9]+)?)s\)?",
                                      "timeout_header_line": r"^timeout: (?P<limit>[0-9]+(?:\.[0-9]+)?)s\s*$"}])
    check_eq("k1 wrappers are unchanged (pnpm exec, npx, ...)",
             {k: v for k, v in data["wrappers"].items() if k in ("poetry", "pnpm", "npx")},
             {"poetry": ["run"], "pnpm": ["exec"], "npx": []})
    # the union (A3): pnpm is in `wrappers` with ["exec"] and in `launchers` with [] - passed over
    # unconditionally, and still a candidate for `pnpm test`
    check_eq("k1 the launcher family is wrappers + launchers: pnpm unconditional, poetry `run` only, python `-m`",
             (H.run_forms()["launchers"]["pnpm"], H.run_forms()["launchers"]["poetry"],
              H.run_forms()["launchers"]["python"]), (None, {"run"}, {"-m"}))


# --- key 2 ---------------------------------------------------------------------------------------

def k2_every_form_is_blocked_and_admitted() -> None:
    forms = H.run_forms()["forms"]
    bad_block, bad_admit = [], []
    for form in forms:
        for command in shapes(form["argv"]):
            for dialect in ("bash", "powershell"):
                got = H.direct_test_form(command, dialect)
                if got is None or got["id"] != form["id"]:
                    bad_block.append(f"{form['id']}: {command!r} [{dialect}] -> {got and got['id']}")
            if not H.needs_guard(command, {}):
                bad_admit.append(f"{form['id']}: {command!r}")
    check(f"k2 every form ({len(forms)}) x 12 spellings x 2 dialects is blocked as THAT form",
          not bad_block, "; ".join(bad_block[:6]))
    check("k2 and the prefilter admits each of them", not bad_admit, "; ".join(bad_admit[:6]))
    extra = ["yarn test", "pnpm test", "coverage run -m pytest", "py -3.11 -m pytest", "python -B -m pytest",
             "npx jest", "npx jest --runInBand", "poetry run pytest tests/x.py -q", "pnpm exec jest",
             "bundle exec rspec", "./gradlew test", "mvnw test", "dotnet test --no-build", "python3.11 -m pytest",
             "xvfb-run -a npx playwright test", "npm run test", "go test ./...", "cargo test -- --nocapture",
             "uv run pytest -x | tail -20", "bash -lc \"cd app && pytest -q\"",
             "pwsh -NoProfile -Command \"cd app; pytest\"", "iex \"cd app; dotnet test\"",
             "cmd /c \"cd app & npm test\"", "echo hi; (npm test)", "timeout 30 pytest",
             "env FOO=1 pytest", "docker exec pytest",
             # an UNQUOTED payload is found only through the flag (a quoted one is read without it)
             "bash -lc pytest", "zsh -ic pytest", "pwsh -NoProfile -Command pytest", "pwsh -c pytest",
             "powershell -Comm pytest", "cmd /k pytest", "cmd /C jest",
             # PowerShell -Command and cmd /c, /k run the REST OF THE LINE
             "pwsh -Command dotnet test", "cmd /c npm test", "powershell -c pytest -q",
             "pwsh -NoProfile -Command cd app; dotnet test"]
    verdicts("k2 more spellings", extra, True, ("bash", "powershell"))
    check("k2 and the prefilter admits them", all(H.needs_guard(c, {}) for c in extra),
          str([c for c in extra if not H.needs_guard(c, {})]))
    # a launcher with an option before its subcommand, and `help`-free forms of the same words
    check_eq("k2 which form: `npm run test` is npm-test", H.direct_test_form("npm run test")["id"], "npm-test")
    check_eq("k2 which form: `mvnw verify` is mvnw-verify", H.direct_test_form("./mvnw verify")["id"], "mvnw-verify")


# --- key 3 ---------------------------------------------------------------------------------------

NEAR_MISSES = [
    "cat pytest.ini", "grep -rn pytest tests/", "poetry add pytest-rerunfailures", "pip install pytest",
    "npm install jest", "yarn add jest", "npm install --save-dev mocha", "dotnet build", "dotnet restore",
    "cargo build", "go build ./...", "go version", "mvn install", "mvn package", "./gradlew build",
    "gradle assemble", "dotnet --info", "npm install", "playwright install", "mvn clean",
    "git commit -m \"dotnet test\"", "echo \"npm test\"", "grep \"go test\" notes.md", "ls # npm test",
    "ls tests/ && grep -rn categories src/", "docker run img pytest", "docker run img dotnet test",
    "python script.py", "python -c \"print(1)\"", "node app.js", "jest-extended", "cat jest.config.js",
    "bash -c npm test",  # bash -c takes ONE argument: the payload is `npm` alone (as today)
    "./gradlew build -x test", "mvn -pl test install", "npm --prefix test install",
    "dotnet run --project test", "cargo build -p test", "yarn --cwd test install",
]


def k3_near_misses_are_not_blocked() -> None:
    verdicts("k3 the near-miss battery", NEAR_MISSES, False, ("bash", "powershell"))
    # the same words as a real call are blocked: the battery is not blocked for being unreadable
    verdicts("k3 NEGATIVE CONTROL: the real calls of the same words", [
        "./gradlew test -x lint", "mvn test -pl test", "npm test --prefix app", "dotnet test --project test"], True)


# --- key 4 ---------------------------------------------------------------------------------------

def k4_diagnostics() -> None:
    verdicts("k4 a diagnostic in its own segment passes", [
        "pytest --collect-only -q", "pytest --co", "pytest --fixtures", "pytest --markers", "pytest --version",
        "pytest -h", "jest --listTests", "npx jest --version", "dotnet test --list-tests", "go test -list .",
        "cargo test --no-run", "cargo test -- --list", "mvn test -DskipTests", "mvn verify -Dmaven.test.skip=true",
        "vitest list", "npx playwright test --list", "rspec --dry-run", "mocha --dry-run", "phpunit --list-tests",
        "npm test --help", "pytest --collect-only=yes", "npm help test", "go help test", "ls; pytest --version",
        "pytest --fixtures-per-test",
    ], False)
    verdicts("k4 a diagnostic in ANOTHER segment never exempts the launch", [
        "pytest x; pytest --version", "pytest --collect-only; pytest tests", "dotnet test; dotnet --version",
        "jest --version && jest",
    ], True)
    verdicts("k4 `help` is not a diagnostic as a test-name filter, nor away from the program", [
        "pytest tests -k help", "cargo test help", "jest help", "pytest help", "mocha help", "go test -run help",
    ], True)


# --- key 5 ---------------------------------------------------------------------------------------

def k5_run_suite_exempts_its_own_segment() -> None:
    verdicts("k5 a segment that goes through run_suite before the form is exempt", [
        "python run_suite.py --task T --label l -- poetry run pytest tests",
        "run-py.cmd run_suite.py --task T --label l -- npx jest",
        "uv run run_suite.py --task T --label l -- uv run pytest tests",
        "python scripts/run_suite.py --task T --label l -- dotnet test",
    ], False)
    verdicts("k5 run_suite in one segment opens no other segment", [
        "cat run_suite.log; dotnet test", "python run_suite.py --task T --label l -- npx jest; dotnet test",
        "echo run_suite; pytest", "dotnet test && python run_suite.py --task T --label l -- npx jest",
        "pytest run_suite.py",
    ], True)


# --- key 6 and E9: the data absent, unreadable or partly invalid ---------------------------------

def with_data(content, fn) -> None:
    """Run `fn` with the loader pointed at a temp file holding `content` (None = no such file)."""
    saved = H.RUN_FORMS_PATH
    folder = Path(tempfile.mkdtemp(prefix="qa-run-forms-"))
    try:
        path = folder / "launch-causes.json"
        if content is not None:
            path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        H.RUN_FORMS_PATH = path
        fn()
    finally:
        H.RUN_FORMS_PATH = saved
        cleanup(folder)


def k6_fallback_and_invalid_items() -> None:
    def fallback_world(label: str):
        def run():
            check_eq(f"k6 {label}: the fallback pytest form is in", [f["id"] for f in H.run_forms()["forms"]][-1], "pytest")
            verdicts(f"k6 {label}: today's pytest launches are still blocked", [
                "pytest", "poetry run pytest tests/x.py -q", "cd repo && python -m pytest tests",
                "python3 -m pytest -q", "uv run pytest -x | tail -20", "ls; pytest",
                'bash -c "x; pytest"', 'pwsh -Command "cd app; pytest"', 'cmd /c "cd app & pytest"'], True)
            verdicts(f"k6 {label}: today's diagnostics still pass", [
                "pytest --collect-only -q", "pytest --version", "pytest -h", "pytest --fixtures"], False)
            check(f"k6 {label}: and the prefilter admits a pytest launch", H.needs_guard("pytest x", {}))
            check(f"k6 {label}: no exception on odd input", all(
                isinstance(H.is_direct_test_run(x), bool) for x in (None, "", "   ", ["pytest"], 5, "a'b \"c")))
        return run

    with_data(None, fallback_world("no file"))
    with_data("{ not json", fallback_world("invalid JSON"))
    with_data({"causes": []}, fallback_world("run_forms absent"))
    with_data({"run_forms": {"forms": []}}, fallback_world("an empty forms list"))
    with_data([1, 2], fallback_world("a JSON list"))

    def jest_only():
        ids = [f["id"] for f in H.run_forms()["forms"]]
        check_eq("k6 a file without a pytest row: its own forms, then the built-in pytest", ids, ["jest", "pytest"])
        verdicts("k6 jest and pytest both blocked", ["jest --ci", "pytest"], True)
        verdicts("k6 dotnet is not (not in this file)", ["dotnet test"], False)
    with_data({"run_forms": {"forms": [{"id": "jest", "argv": ["jest"]}]}}, jest_only)

    def partly_invalid():
        problems = H.run_forms_problems()
        check_eq("k6 each invalid item is named: six", len(problems), 7)
        check_eq("k6 the valid rows stay", [f["id"] for f in H.run_forms()["forms"]], ["jest", "pytest"])
        verdicts("k6 and still guard", ["jest --ci", "pytest"], True)
        check("k6 a problem names its place", any("forms[1]" in p for p in problems), str(problems))
    with_data({"run_forms": {"forms": [
        {"id": "jest", "argv": ["jest"]},
        {"id": "two words", "argv": ["a b"]},                 # whitespace in a word
        {"id": "quoted", "argv": ["x\"y"]},                   # a quote in a form word (A6)
        {"id": "empty", "argv": []},
        {"id": "backtick", "argv": ["a`b"]},
        {"id": "diag", "argv": ["ok"], "diagnostics": "no"},  # not a list
        {"argv": ["noid"]}], "shells": [{"program": "sh", "flag_style": "weird", "dialect": "bash"}]}},
        partly_invalid)

    # the loader is restored: the shipped data rules again
    check_eq("k6 the shipped data is back after the test worlds", H.run_forms_problems(), [])


# --- key 7 and E8: depth, empty and broken input --------------------------------------------------

def k7_depth() -> None:
    check_eq("k7 a launch at depth 3 is blocked", H.is_direct_test_run(nest(3, "pytest")), True)
    check_eq("k7 a launch at depth 4 passes uninspected", H.is_direct_test_run(nest(4, "pytest")), False)
    check_eq("k7 depth 3 with another form", H.is_direct_test_run(nest(3, "dotnet test")), True)
    check_eq("k7 depth 4 with another form", H.is_direct_test_run(nest(4, "dotnet test")), False)
    check_eq("k7 a $( ) region inside a payload counts one level",
             H.is_direct_test_run(nest(2, 'echo "$(pytest)"')), True)
    deep = nest(12, "pytest")  # the escapes double per level: 12 levels is already 4 KB of backslashes
    check_eq("k7 12 levels deep: no crash, no hang, passes", H.is_direct_test_run(deep), False)
    check_eq("k7 3000 levels of `bash -c` without quotes: no crash, no hang", H.is_direct_test_run("bash -c " * 3000 + "pytest"), False)
    check_eq("k7 a long unbalanced $( run: no crash", isinstance(H.is_direct_test_run("echo " + "$(" * 400), bool), True)


def k7_edges_empty_and_broken() -> None:
    for value in (None, "", "   ", "\n\n", [], 0, "  \t "):
        check_eq(f"E8 {value!r} is no launch", H.direct_test_form(value), None)
    check_eq("E8 a list is joined", H.is_direct_test_run(["npx", "jest"]), True)
    check_eq("E8 an argv list with run_suite is exempt", H.is_direct_test_run(["python", "run_suite.py", "--", "uv", "run", "pytest"]), False)
    verdicts("E8 an unclosed quote hides nothing: the text after it is read as unquoted", [
        'echo "x ; pytest', "echo 'x ; dotnet test", 'git commit -m "a ; npx jest', "echo `x ; pytest",
        'bash -c "echo hi ; pytest'], True, ("bash", "powershell"))
    verdicts("E8 nothing raises on hostile text", [
        "\x00pytest", "pytest\x00", "\ufeffpytest", "$(", "$($(", "`", "``", "\\", '"', "'", "()", ";;;", "&|",
        "# pytest", "pyt\u0435st", "\U0001F600 dotnet test", "{ ", "A=1", "A=1 B=2",
        "bash -c", "bash -c ''", "pwsh -Command", "cmd /c", "iex", "env", "env -i", "timeout", "run", "run --",
        "poetry run", "python -m", "npx", "yarn", "xargs -I{}"], False, ("bash", "powershell"))
    check_eq("E8 `{ pytest }` (a brace group) is a launch", H.is_direct_test_run("{ pytest }"), True)
    check_eq("E8 magnitude: a launch at the end of 60 KB is found", H.is_direct_test_run("echo a; " * 8000 + "pytest"), True)
    check_eq("E8 magnitude: 60 KB of text with no launch passes", H.is_direct_test_run("echo a; " * 8000), False)
    check_eq("E8 an unknown dialect reads as bash", H.is_direct_test_run("pytest", "klingon"), True)


# --- key 8 and 9: the refusal and the Codex host --------------------------------------------------

def event(command, tool="Bash", **extra) -> dict:
    return dict({"tool_name": tool, "tool_input": {"command": command}}, **extra)


def k8_k9_messages_and_codex() -> None:
    root = temp_project("qa-run-forms-msg-")
    harness.use_project(root)
    try:
        msg = G._blocked(G.runs_check, event("dotnet test --no-build"), {}) or ""
        check_in("k8 the standalone message names the form", "a direct dotnet test launch is blocked", msg)
        check_in("k8 the standalone door", "--task <id> --label <label> -- <your command>", msg)
        check_in("k8 the standalone detail door", "--detail", msg)
        check_in("k8 the no-run flags of the form are listed", "--list-tests", msg)
        check_in("k8 and the global ones", "--version", msg)
        check_in("k8 the false-match sentence (F10)", "add the runner's no-run flag listed above", msg)
        check("k8 the message is ASCII (FR-30; the shared footer `block` adds is not this message's)",
              msg.split("\n")[0].isascii(), msg)
        role = G._blocked(G.runs_check, event("npx jest", agent_type="qa-factory:qa-automator"), {}) or ""
        check_in("k8 a dispatch caller: the form is named", "a direct jest launch is blocked", role)
        check_in("k8 the typed request", "--request <request.json>", role)
        check_in("k8 the ordinary run", "--mine", role)
        check_in("k8 the skeleton", "--template request", role)
        check_not_in("k8 never the interface the stage guard refuses there", "--label <label> -- <your command>", role)
        check_in("k8 the false-match sentence there too", "add the runner's no-run flag listed above", role)
        py = G._blocked(G.runs_check, event("poetry run pytest tests/x.py"), {}) or ""
        check_in("k8 pytest keeps its substrings: the form", "a direct pytest launch is blocked", py)
        check_in("k8 pytest keeps the standalone door", "--task <id> --label <label> -- <your command>", py)
        check_eq("k8 a diagnostic is not refused", G._blocked(G.runs_check, event("npx jest --listTests"), {}), None)
        check_eq("k8 run_suite is not refused",
                 G._blocked(G.runs_check, event("run-py.cmd run_suite.py --task T --label l -- npx jest"), {}), None)
        ps = G._blocked(G.runs_check, event("dotnet test", tool="PowerShell"), {}) or ""
        check_in("k8 the PowerShell tool is refused the same way", "a direct dotnet test launch is blocked", ps)
        as_list = G._blocked(G.runs_check, event(["dotnet", "test"]), {}) or ""
        check_in("k8 a list-valued command is joined and refused", "a direct dotnet test launch is blocked", as_list)
        check_eq("k8 a text-only mention is not refused (command_text_parts)",
                 G._blocked(G.runs_check, event('echo "dotnet test"'), {}), None)
        check_eq("k8 a heredoc body is not refused", G._blocked(
            G.runs_check, event("cat > notes.md <<'EOF'\nrun: dotnet test\nEOF"), {}), None)
        # key 9: the Codex host goes through the same code, in the bash dialect
        from host_adapter import normalize
        for raw in ({"cmd": "dotnet test"}, {"command": "npx jest"}):
            codex = normalize({"host": "codex", "tool_name": "exec_command", "tool_input": raw})
            check_eq(f"k9 a Codex exec_command {raw} is normalised to Bash", codex["tool_name"], "Bash")
            check_in(f"k9 and refused {raw}", "launch is blocked", G._blocked(G.runs_check, codex, {}) or "")
        shell = normalize({"host": "codex", "tool_name": "shell_command", "tool_input": {"command": "cd x; go test ./..."}})
        check_in("k9 a Codex shell_command is refused", "a direct go test launch is blocked",
                 G._blocked(G.runs_check, shell, {}) or "")
    finally:
        cleanup(root)


# --- key 10: today's ten pytest cases (guard_pre_tool.py --selftest) --------------------------------

def k10_the_ten_selftest_cases() -> None:
    for command, expected in [
        ("poetry run pytest tests/x.py -q", True), ("pytest", True), ("cd repo && python -m pytest tests", True),
        ("uv run pytest -x | tail -20", True),
        ("python run_suite.py --task T --label l -- poetry run pytest tests", False),
        ("poetry run pytest --collect-only -q", False), ("pytest --version", False), ("cat pytest.ini", False),
        ("grep -rn pytest tests/", False), ("poetry add pytest-rerunfailures", False)]:
        check_eq(f"k10 is_direct_test_run({command!r})", H.is_direct_test_run(command), expected)


# --- key 11: the hook as a process ----------------------------------------------------------------

def run_hook(root: Path, ev: dict, prelude: str = "") -> tuple:
    """(exit code, stderr) of the hook process; `prelude` (Python) runs first in that process, then the hook as __main__."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    guard = str(harness.SCRIPTS / "guard_pre_tool.py")
    argv = [sys.executable, "-B", guard] if not prelude else [
        sys.executable, "-B", "-c", prelude + f"\nimport runpy\nrunpy.run_path({guard!r}, run_name='__main__')\n"]
    done = subprocess.run(argv,
                          input=json.dumps(dict(ev, cwd=str(root))), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)
    return done.returncode, done.stderr


def k11_hook_level() -> None:
    root = temp_project("qa-run-forms-hook-")
    harness.use_project(root)
    try:
        code, err = run_hook(root, event("dotnet test"))
        check_eq("k11 hook: `dotnet test` exits 2", code, 2)
        check_in("k11 hook: and names the form", "direct dotnet test launch", err)
        code, err = run_hook(root, event("npx jest"))
        check_eq("k11 hook: `npx jest` exits 2 (the prefilter loaded the guard for a non-pytest runner)", code, 2)
        code, err = run_hook(root, event("dotnet test", tool="PowerShell"))
        check_eq("k11 hook: the PowerShell tool is refused too", code, 2)
        code, err = run_hook(root, event("npx jest --listTests"))
        check_eq("k11 hook: a diagnostic passes", (code, "launch is blocked" in err), (0, False))
        code, err = run_hook(root, event("run-py.cmd run_suite.py --task T --label l -- npx jest"))
        check_eq("k11 hook: the run_suite door passes", (code, "launch is blocked" in err), (0, False))
        code, err = run_hook(root, event("git status"))
        check_eq("k11 hook: an unrelated command passes", code, 0)
    finally:
        cleanup(root)


# --- key 12: the data is read once ------------------------------------------------------------------

def k12_the_loader_reads_once() -> None:
    reads = []
    real = H._read_run_forms_file

    def counting(path):
        reads.append(str(path))
        return real(path)

    H._read_run_forms_file = counting
    H._RUN_FORMS_CACHE = None
    try:
        for i in range(50):
            H.needs_guard(f"ls -la {i}", {})
            H.is_direct_test_run("pytest x")
        check_eq("k12 50 prefilter calls and 50 matcher calls read the file once", len(reads), 1)
    finally:
        H._read_run_forms_file = real
        H._RUN_FORMS_CACHE = None
    check_eq("k12 the shipped data is read again after the reset", H.run_forms_problems(), [])


# --- key 13: nothing blocked today stops being blocked, except a named list -------------------------

STAYS_BLOCKED = [
    "pytest", "poetry run pytest tests/x.py -q", "cd repo && python -m pytest tests", "uv run pytest -x | tail -20",
    "python3 -m pytest -q", "conda run pytest -q",
    "ls; pytest", "ls & pytest", "ls || pytest", "(pytest)", "echo x\npytest", "x=$(pytest -q)", "echo run pytest",
    'bash -lc "cd app && pytest -q"', 'pwsh -NoProfile -Command "cd app; pytest"',
    'bash -c "echo \\"a b\\" && pytest"', "bash -c 'cd app; pytest'", 'cmd /c "cd app & pytest"',
    'echo "$(cd app; pytest)"', "pytest tests -k help", "poetry run pytest tests/x.py > qa-factory/config.json",
]
# F7 (quoted text and comments are not a call) and F12 (a program that only ENDS in `python`): the
# whole list of commands the new matcher is allowed to stop blocking.
NAMED_NARROWINGS = [
    'git commit -m "fix; pytest"',                                    # a quoted argument
    "python -c \"import os; os.system('cd x; pytest')\"",             # a quoted argument of a non-shell (A8)
    'grep -rn "a|pytest" src',                                        # a quoted argument
    "ls # ; pytest",                                                  # a comment
    "mypython -m pytest",                                             # F12 (a): not a launcher name
    # F4 (critic t-517): a narrowing of the same kind, named. `pytest\<LF> -q` is a line continuation
    # glued to the program word: in unquoted text a backslash is literal (A2), so the token is
    # `pytest\` - a real launch the new reader does not see. `X-run pytest` was a false positive of
    # today's `\brun` (a program that merely ENDS in `run`), so losing it does no harm.
    "pytest\\\n -q",
    "foo-run pytest", "npm-run pytest", "a.run pytest",
]
BASELINE_NOW_BLOCKED = ["yarn test", "/usr/bin/pytest x", "HEADLESS=1 pytest", ".venv\\Scripts\\pytest.exe x",
                        "pytest x; pytest --version", "cat run_suite.log; pytest",
                        'bash -c "\\"pytest\\" -q"']  # CX1-19 k19: kills the mutant "backslash literal in bash double quotes"


def generated_corpus() -> list:
    """Unquoted shapes of an old-style launch: the old regex's own positions x tails. Nothing
    quoted: a quoted shape is the named narrowing, not part of the generated witness."""
    heads = ["", "cd x && ", "ls; ", "ls | ", "ls & ", "ls || ", "(", "poetry run ", "uv run ", "pipenv run ",
             "python -m ", "python3 -m ", "run ", "conda run ", "x=$(", "echo hi\n", "cd a; cd b && ", "a | b | "]
    tails = ["", " tests/x.py -q", " -k help", " --maxfail=1", " 2>&1 | tail -5", " > out.txt", " -x -q tests",
             "; echo done", ")"]
    return [h + "pytest" + t for h in heads for t in tails]


def k13_nothing_blocked_today_stops_being_blocked() -> None:
    check("k13 PRECONDITION: the frozen old matcher blocks the whole must-stay corpus",
          all(old_is_direct_test_run(c) for c in STAYS_BLOCKED),
          str([c for c in STAYS_BLOCKED if not old_is_direct_test_run(c)]))
    check("k13 PRECONDITION: and the named list (old True)", all(old_is_direct_test_run(c) for c in NAMED_NARROWINGS),
          str([c for c in NAMED_NARROWINGS if not old_is_direct_test_run(c)]))
    verdicts("k13 the must-stay corpus is still blocked", STAYS_BLOCKED, True, ("bash",))
    check_eq("k13 the named list: OLD True, NEW False (exactly)",
             [(old_is_direct_test_run(c), H.is_direct_test_run(c)) for c in NAMED_NARROWINGS],
             [(True, False)] * len(NAMED_NARROWINGS))
    check_eq("k13 the old baseline, new value: OLD False, NEW True",
             [(old_is_direct_test_run(c), H.is_direct_test_run(c)) for c in BASELINE_NOW_BLOCKED],
             [(False, True)] * len(BASELINE_NOW_BLOCKED))
    check_eq("k13 `./gradlew build -x test` stays False in both",
             (old_is_direct_test_run("./gradlew build -x test"), H.is_direct_test_run("./gradlew build -x test")),
             (False, False))
    corpus = generated_corpus() + STAYS_BLOCKED + NAMED_NARROWINGS
    stopped = sorted({c for c in corpus if old_is_direct_test_run(c) and not H.is_direct_test_run(c)})
    check_eq(f"k13 over {len(corpus)} commands, the ones that stop being blocked are EXACTLY the named list",
             stopped, sorted(NAMED_NARROWINGS))
    check("k13 the generated corpus is real: most of it was blocked before",
          sum(old_is_direct_test_run(c) for c in generated_corpus()) > 100, "")


def k13_without_the_data() -> None:
    """The superset-of-today invariant holds in BOTH worlds (FR-59): with the data file missing,
    the code fallback (pytest form, `run` verb, python -m launchers, the shells) still blocks
    everything the old matcher blocked, except the same named list."""
    def world():
        print("k13 fallback world, run_forms_problems():", H.run_forms_problems())
        check("k13 fallback: the problems line names the unreadable file", bool(H.run_forms_problems()))
        verdicts("k13 fallback: the must-stay corpus is still blocked", STAYS_BLOCKED, True, ("bash",))
        check_eq("k13 fallback: the named list: OLD True, NEW False (exactly)",
                 [(old_is_direct_test_run(c), H.is_direct_test_run(c)) for c in NAMED_NARROWINGS],
                 [(True, False)] * len(NAMED_NARROWINGS))
        corpus = generated_corpus() + STAYS_BLOCKED + NAMED_NARROWINGS
        stopped = sorted({c for c in corpus if old_is_direct_test_run(c) and not H.is_direct_test_run(c)})
        check_eq(f"k13 fallback: over {len(corpus)} commands, what stops being blocked is EXACTLY the named list",
                 stopped, sorted(NAMED_NARROWINGS))
        check_eq("k13 fallback: a runner with no form in the fallback is not guarded", H.is_direct_test_run("dotnet test"), False)
        # E19 (critic F3): today's `--fixtures` was a substring test, so `--fixtures-per-test` passed
        # before; the fallback names it, so it passes without the data too
        check_eq("k13 fallback E19: OLD admitted `pytest --fixtures-per-test` (a diagnostic)",
                 old_is_direct_test_run("pytest --fixtures-per-test"), False)
        check_eq("k13 fallback E19: and so does the fallback",
                 H.is_direct_test_run("pytest --fixtures-per-test"), False)
        check_eq("k13 fallback E19 NEGATIVE CONTROL: a run with another flag is still blocked",
                 H.is_direct_test_run("pytest --fixtures-x"), True)
    with_data(None, world)


# --- key 14: the two dialects ------------------------------------------------------------------------

def k14_dialects() -> None:
    bash_escaped = 'git commit -m "a\\" ; dotnet test"'
    # CX1-20 F-3 (a), the three named flips (t-995 L-2 M-3): every reader takes BOTH dialects, the tool label decides nothing.
    # Rewritten: "the Bash tool reads one argument, no launch" (False) is now True - the PowerShell reading ends the quote.
    check_eq("k14 \\\" inside double quotes: bash reads one argument but the PowerShell reading ends the quote - a launch (flip 1)",
             H.is_direct_test_run(bash_escaped, "bash"), True)
    check_eq("k14 the same text through the PowerShell tool: the quote ends, the launch is found",
             H.is_direct_test_run(bash_escaped, "powershell"), True)
    ps_escaped = 'git commit -m "a`" ; dotnet test"'
    check_eq("k14 a backtick-escaped quote: the PowerShell tool reads one argument, but the bash reading ends the quote - a launch (flip 2)",
             H.is_direct_test_run(ps_escaped, "powershell"), True)
    check_eq("k14 the same text through the Bash tool: the quote ends, the launch is found",
             H.is_direct_test_run(ps_escaped, "bash"), True)
    check_eq("k14 `pwsh -Command` reads its payload as PowerShell, whatever tool carries it",
             H.is_direct_test_run("pwsh -Command '" + ps_escaped + "'", "bash"), False)
    check_eq("k14 `bash -c` reads its payload as bash, whatever tool carries it",
             H.is_direct_test_run("bash -c '" + ps_escaped + "'", "powershell"), True)
    check_eq("k14 a Windows path keeps its backslashes (bash: a backslash outside quotes is literal)",
             H.is_direct_test_run('C:\\tools\\dotnet.exe test', "bash"), True)
    bash_blocked = G._blocked(G.runs_check, event(bash_escaped), {}) or ""
    check_eq("k14 runs_check on both tools (flip 3): both block; only the Bash tool's refusal carries the PowerShell door (FR-1, M-3)",
             ("launch is blocked" in bash_blocked, "read as PowerShell this runs dotnet test" in bash_blocked,
              "launch is blocked" in (G._blocked(G.runs_check, event(bash_escaped, tool="PowerShell"), {}) or ""),
              "read as PowerShell" in (G._blocked(G.runs_check, event(bash_escaped, tool="PowerShell"), {}) or "")),
             (True, True, True, False))


# --- key 15: the prefilter admits everything the matcher blocks -------------------------------------

def k15_prefilter_covers_the_matcher() -> None:
    commands = []
    for form in H.run_forms()["forms"]:
        commands += shapes(form["argv"])
    commands += STAYS_BLOCKED + generated_corpus() + [
        'git commit -m "a\\" ; dotnet test"', 'git commit -m "a`" ; dotnet test"',
        "pwsh -Command 'git commit -m \"a`\" ; dotnet test\"'", "bash -c 'git commit -m \"a`\" ; dotnet test\"'"]
    blocked = [(c, d) for c in commands for d in ("bash", "powershell") if H.direct_test_form(c, d) is not None]
    missed = [(c, d) for c, d in blocked if not H.needs_guard(c, {})]
    check(f"k15 over {len(blocked)} blocked commands the prefilter admits every one", not missed, str(missed[:5]))
    for command, dialect in (('py"test" -q', "bash"), ("py`test -q", "powershell"), ('"pyt""est"', "bash"),
                             ('"jes""t" --ci', "bash"), ("dot`net te`st", "powershell"), ("'jest' ", "bash"),
                             ("bash -c \"pyt\\\"\\\"est\"", "bash"), ("PY\"TEST\"", "bash"),
                             # M13 (review t-1071): a name built by a substitution - the prefilter must not need the words
                             ("py$(true)test -q", "bash"), ("dot$(true)net test", "bash"), ("py`true`test -q", "bash")):
        check_eq(f"k15 {command!r}: the shell runs it, so the matcher blocks", H.is_direct_test_run(command, dialect), True)
        check_eq(f"k15 {command!r}: and the prefilter admits it", H.needs_guard(command, {}), True)
    check_eq("k15 the cost side: the prefilter has no regex and exits for plain reads",
             [H.needs_guard(c, {}) for c in ("ls -la", "git status", "cat a.txt", "git log --oneline")],
             [False, False, False, False])


# --- key 16 (critic t-517 F1, E16, E17): the REAL call path -------------------------------------------
# runs_check feeds the matcher the text with only the heredoc / here-string bodies out. Fed the whole
# `command_text_parts(...)["exec"]`, a quoted argument followed by an unquoted runner name became a
# launch: the second pass joins the pieces of one segment with a newline, which the matcher reads as
# a new command position. The matcher alone never saw the joined text, so key 13 missed it: these
# cases go THROUGH runs_check, as the hook does.

E16_ADMITTED = ['echo "a" pytest -q', "printf '%s' pytest", 'Write-Host "x" pytest', 'Set-Content "x" pytest',
                'echo "run:" dotnet test']
# a here-string body, then a runner name: a mention (E4). `cmd` runs its here-string, so it is never
# cut; the others are cut, and the cut must not create a command position (a here-string never ends a segment)
E17_ADMITTED = ['cmd <<< "a" pytest', 'cat <<< "a" pytest', 'grep x <<< "a" pytest -q', "cat <<< a pytest",
                # a PowerShell here-string: what follows the closer on its line is an argument (pwsh prints `pytest`)
                "Write-Output @'\nhello\n'@ pytest", "Write-Output @'\nhello\n'@ dotnet test"]
E16_STILL_BLOCKED = ["pytest -q", 'bash -c "cd app && pytest"', 'echo "a"; pytest -q', 'echo "a" && dotnet test',
                     'Write-Host "x"; dotnet test',
                     'cat <<< "a" | pytest',  # a real pipe after the here-string: the launch stays a launch
                     'cat <<< "a"; pytest -q',
                     "Write-Output @'\nhello\n'@\npytest -q", "Write-Output @'\nhello\n'@; pytest -q",
                     "Write-Output @'\nhello\n'@ | pytest"]


def refused(command, tool="Bash") -> bool:
    return bool(G._blocked(G.runs_check, event(command, tool=tool), {}))


def k16_a_quoted_argument_before_a_runner_name() -> None:
    root = temp_project("qa-run-forms-e16-")
    harness.use_project(root)
    try:
        tools = ("Bash", "PowerShell")
        wrong = [f"{c!r} [{t}]" for c in E16_ADMITTED + E17_ADMITTED for t in tools if refused(c, t)]
        check(f"k16 E16/E17: {len(E16_ADMITTED + E17_ADMITTED)} commands, runs_check admits all on both tools",
              not wrong, "; ".join(wrong))
        wrong = [f"{c!r} [{t}]" for c in E16_STILL_BLOCKED for t in tools if not refused(c, t)]
        check(f"k16 NEGATIVE CONTROL: {len(E16_STILL_BLOCKED)} real launches are still refused by runs_check",
              not wrong, "; ".join(wrong))
        check_eq("k16 a heredoc body is still text through runs_check",
                 refused("cat > notes.md <<'EOF'\nrun: pytest -q\nEOF"), False)
        check_eq("k16 and the launch after a heredoc is still a launch",
                 refused("cat > notes.md <<'EOF'\nnote\nEOF\npytest -q"), True)
        for command, expected in (('echo "a" pytest -q', 0), ("pytest -q", 2)):
            code, err = run_hook(root, event(command))
            check_eq(f"k16 hook as a process: {command!r} exits {expected}", code, expected)
    finally:
        cleanup(root)


def k22_cut_bodies_joins() -> None:
    """t-430: the joins of `hooklib.cut_bodies` (the one cut of heredoc / here-string bodies since OH3-22, ea9dbf5e) through the
    module `H` itself - the guard imports the function by name, so a mutant of `H` reaches it only through a key that calls `H`.
    An inline body (a here-string, a PowerShell here-string) leaves a BLANK where it was and never a line feed (a line feed would
    end the segment and make the word after the closer a command: E17); a heredoc leaves its line feed."""
    cases = (('cat <<< "a" pytest', "cat   pytest"),
             ("Write-Output @'\nhello\n'@ pytest", "Write-Output   pytest"),
             ('cat <<< "a"; pytest', "cat  ; pytest"),
             ("cat > n.md <<'EOF'\nrun: x\nEOF\npytest -q", "cat > n.md <<'EOF'\n\npytest -q"))
    for src, expected in cases:
        check_eq(f"k22 cut_bodies joins {src!r}", H.cut_bodies(src, H.scan_bodies(src))[0], expected)


# --- key 17 (critic t-517 F2, E18): linear matching ----------------------------------------------------

def reference_matches(form: dict, c: int, low: list, data: dict) -> bool:
    """The pre-F2 scan, the slow obvious way, plus the E20 rule: the oracle `_SegmentWords.matches` is
    compared with (it lives in the test, so the comparison does not depend on the code under test)."""
    n = len(low)
    pos = c + 1
    for word in form["_argv"][1:]:
        p = pos
        while p < n and not (low[p] == word and not (p - 1 > c and low[p - 1] in form["_negators"])):
            p += 1
        if p >= n or any(low[d] == "--" for d in range(c + 1, p)):
            return False
        pos = p + 1
    diagnostics = form["_diagnostics"] | data["diagnostics"]
    for token in low[c + 1:]:
        head = token.split("=", 1)[0]
        if token in diagnostics or (head != token and head in diagnostics):
            return False
    return not (len(form["argv"]) >= 2 and c + 1 < n and low[c + 1] in data["subcommand_diagnostics"])


LINEAR_CASES = [("run mvn " * 5000 + "pytest", False), ("run mvn " * 5000 + "test", True),
                ("run pytest " * 3636 + "--co", False), ("run pytest " * 3636 + "x", True)]
READS_PER_TOKEN = 60  # K: the reads of a segment's words allowed per word; the linear matcher needs ~7


class CountingList(list):
    """The words of a segment, counting every read: 1 per index, the length for a slice or a pass.
    A count is not a clock: it cannot fail under load (FR-31), and a scan to the segment's end per
    candidate position (the pre-F2 matcher, 11.6 s on 40 KB) reads ~n^2/2 times."""
    reads = 0

    def __getitem__(self, index):
        got = super().__getitem__(index)
        self.reads += len(got) if isinstance(index, slice) else 1
        return got

    def __iter__(self):
        self.reads += len(self)
        return super().__iter__()


def k17_reads_are_linear() -> None:
    """E18: matching a segment of ~500 words reads its words O(n), not O(n^2), however many candidate
    positions and forms there are."""
    data = H.run_forms()
    for text in ("run mvn " * 249 + "run mvn test", "run pytest " * 250 + "--co"):
        plain = text.split()
        low = CountingList(plain)
        words = H._SegmentWords(low, data)
        answers = []
        for form in data["forms"]:
            for c in range(len(plain)):
                if plain[c] == form["_argv"][0]:  # every candidate the head walk and the verbs would offer
                    answers.append(words.matches(form, c))
        n = len(plain)
        check(f"k17 E18 {text[:11]!r}... ({n} words, {len(answers)} candidate matches): "
              f"{low.reads} reads <= {READS_PER_TOKEN} x n = {READS_PER_TOKEN * n}",
              low.reads <= READS_PER_TOKEN * n, f"{low.reads} reads")
        check("k17 E18 and the counted run is a real run: over 100 candidate positions were matched",
              len(answers) > 100, str(len(answers)))


def k17_linear_matching() -> None:
    for command, expected in LINEAR_CASES:
        check_eq(f"k17 E18 {command[:12]!r}...{command[-6:]!r} ({len(command)} bytes) gives {expected}",
                 H.is_direct_test_run(command), expected)
    # the same answers as the quadratic reference, over random segments of the words that matter
    data = H.run_forms()
    vocab = ["dotnet", "test", "-o", "--output", "--", "-n", "verify", "mvn", "-pl", "--version", "help", "x",
             "cargo", "--list", "pytest", "-h", "--co=1", "run", "npm", "--prefix", "check", "-x", "gradlew"]
    rng = random.Random(404)
    differing = []
    for _ in range(1500):
        low = [rng.choice(vocab) for _ in range(rng.randint(1, 9))]
        words = H._SegmentWords(low, data)
        for form in data["forms"]:
            for c in range(len(low)):
                if words.matches(form, c) != reference_matches(form, c, low, data):
                    differing.append((form["id"], c, low))
    check("k17 the linear matcher equals the quadratic reference over 1500 random segments x every form x every position",
          not differing, str(differing[:2]))
    # the merge "first form in DATA order" (critic 7b, written once): across segments, a payload against the
    # segment's own match, and a $( ) region
    check_eq("k17 the first form in data order wins: two segments, payload vs own match, region vs segment",
             [H.direct_test_form(c)["id"] for c in ("dotnet test; pytest", "bash -c pytest run dotnet test",
                                                   'echo "$(pytest)"; dotnet test', "npm test && go test")],
             ["pytest", "pytest", "pytest", "npm-test"])


# --- key 18 (critic t-517 F5, E20, E21) --------------------------------------------------------------

def k18_dashdash_and_the_dotnet_negators() -> None:
    both = ("bash", "powershell")
    verdicts("k18 E20 a word after a literal `--` is never the form's subcommand", [
        "cargo run -- test", "npm run build -- test", "go run ./cmd/x -- test", "yarn run build -- test"], False, both)
    verdicts("k18 E20 NEGATIVE CONTROL: the subcommand before the `--`, or no `--` at all, is still a launch", [
        "cargo test", "dotnet test", "cargo test -- --nocapture", "npm test -- --watch", "go test ./... -- test",
        "dotnet test -- RunConfiguration.X=1"], True, both)
    # F-B (critic t-528, Lead decision (a)): for npm `--` ends npm's own options and the next word is still
    # the script name, so these two ARE launches (npm 10 prints `> p test`); the rule is by token shape and
    # cargo has the same shape with the opposite meaning, so they are NAMED narrowings of E20: the matcher of
    # the commit before the `--` rule refused them, this one admits them; today's pytest-only guard never did.
    NPM_NARROWINGS = ["npm run -- test", "npm -- test"]
    verdicts("k18 F-B named narrowing: `npm run -- test` and `npm -- test` are admitted (E20)", NPM_NARROWINGS, False, both)
    verdicts("k18 F-B NEGATIVE CONTROL: the same scripts without the `--` are refused", [
        "npm run test", "npm test"], True, both)
    verdicts("k18 E21 `-n` / `--name` are dotnet negators: the value `test` is a name", [
        "dotnet new xunit -n test", "dotnet new xunit --name test"], False, both)
    verdicts("k18 E21 NEGATIVE CONTROL: `dotnet test` itself, with those flags elsewhere, is blocked", [
        "dotnet test", "dotnet test -n x", "dotnet new xunit -n x && dotnet test"], True, both)


# --- key 20 (critic t-528 F-E): the neighbour that reads the same second-pass text -----------------------
# command_text_parts joins the segments of one command with a newline and drops the `; && || |` between
# them; git_config_check split only on those, so a read put first hid a write.

def k20_git_config_check_splits_on_newline() -> None:
    root = temp_project("qa-run-forms-gitcfg-")
    harness.use_project(root)
    try:
        def refused_by_git_config(command: str) -> bool:
            return G._blocked(G.git_config_check, event(command), {}) is not None
        for sep in (";", "&&", "||", "|"):
            command = f"git config --get a {sep} git config --global user.name x"
            check_eq(f"k20 F-E a read, `{sep}`, then a write: refused", refused_by_git_config(command), True)
        check_eq("k20 F-E a read, then a write on the next line: refused",
                 refused_by_git_config("git config --list\ngit config --global user.name x"), True)
        check_eq("k20 F-E NEGATIVE CONTROL: the write alone is refused",
                 refused_by_git_config("git config --global user.name x"), True)
        check_eq("k20 F-E and the read alone is admitted", refused_by_git_config("git config --get a"), False)
        check_eq("k20 F-E two reads are admitted",
                 refused_by_git_config("git config --get a; git config --list | head"), False)
    finally:
        cleanup(root)


# --- key 21 (review t-1071, the fix round of CX1-20): the backtick region through the hook's view, the size cap ------

def k21_fix_round_hook_path() -> None:
    tick = chr(96)
    root = temp_project("qa-run-forms-k21-")
    harness.use_project(root)
    try:
        # B-2: an unquoted-delimiter heredoc whose body holds `${HOME}` and an odd double quote stays in the text runs_check
        # reads (the body expands, so it is not text), and the dropped quote makes the reader rewind (E8); the backtick
        # pair after it still has a partner, so `pytest -q` in it is a launch - bash runs it
        heredoc = 'cat <<EOF\n${HOME} "\nEOF\n'
        launch = heredoc + "echo '" + tick + "'" + tick + "pytest -q" + tick
        check_eq("k21 B-2 through runs_check: a launch in a backtick pair after a rewind is refused", refused(launch), True)
        check_eq("k21 B-2 control: the same text with `ls -la` in the pair is admitted",
                 refused(heredoc + "echo '" + tick + "'" + tick + "ls -la" + tick), False)
        check_eq("k21 B-2 the hook view: both tools refuse it", [refused(launch, tool) for tool in ("Bash", "PowerShell")], [True, True])
        # F-8: a command over 64 KB is refused before any reader walks it; AT the cap it is read as before
        cap = G.MAX_COMMAND_CHARS
        check_eq("k21 F-8 the cap is 64 KB", cap, 64 * 1024)
        at, beyond = "a" * cap, "a" * (cap + 1)
        sized = lambda command, tool="Bash": G._blocked(G.size_check, event(command, tool=tool), {})  # noqa: E731
        check_eq("k21 F-8 AT the cap: not refused", sized(at), None)
        message = sized(beyond) or ""
        check_in("k21 F-8 BEYOND the cap: refused, names the size, the limit and the door", "the guard reads at most 64 KB", message)
        check_in("k21 F-8 ... the door is a split or a file", "Split the work into several commands", message)
        check_in("k21 F-8 ... and the size", f"{cap + 1:,} characters long", message)
        check_eq("k21 F-8 the PowerShell tool and a Codex argv list are capped the same",
                 [bool(sized(beyond, "PowerShell")), bool(sized(["a" * cap, "b"])), sized(["a" * 10, "b"])], [True, True, None])
        check_eq("k21 F-8 a tool that is no shell is not the cap's business", sized(beyond, "Read"), None)
        check_eq("k21 F-8 an absent, empty or None command is admitted", [sized(None), sized(""), G._blocked(G.size_check, {}, {})], [None] * 3)
        # the operation count: the refusal builds no reader, so its cost is one len(), not a walk of 400 KB of openers
        readers = [0]

        def counting(real_init):
            def build(self, *args, **kwargs):
                readers[0] += 1
                real_init(self, *args, **kwargs)
            return build

        # SC1-5b: warm the control's text first. `reader_patched` clears the reading cache on the way in, so the control still
        # builds readers; without the clear the warm text is a cache hit, the control goes falsely red, and "not one reader
        # was built" would be true of a walk that merely never reached the reader.
        H.is_direct_test_run("$(" * 10)
        with harness.reader_patched("__init__", counting):
            refused_big = bool(sized("$(" * 200000))
            check_eq("k21 F-8 400 KB of `$(`: refused, and not one reader was built", (refused_big, readers[0]), (True, 0))
            readers[0] = 0
            H.is_direct_test_run("$(" * 10)
            check_eq("k21 F-8 control: the counter counts the readers a walk builds (from a cache that was warm)", readers[0] > 0, True)
        # and as the hook runs it: stdin, exit code, the one stderr line - far inside the timeout run_hook sets
        code, err = run_hook(root, event("$(" * 200000))
        check_eq("k21 F-8 the hook process refuses 400 KB with exit 2", code, 2)
        check_in("k21 F-8 ... and says why", "the guard reads at most 64 KB", err)
        code, err = run_hook(root, event("git status"))
        check_eq("k21 F-8 control: an ordinary command passes the hook", code, 0)
        # N-1 (review t-1082): the walker raised on this text and the hook exited 1 - a non-blocking error, the call went
        # ahead with every later check skipped; bash runs the command after the heredoc. As on main: exit 2, the launch named
        crash = 'cat <<EOF\n${HOME} "\nEOF\npytest -q #' + tick + " " + chr(92) + tick
        code, err = run_hook(root, event(crash))
        check_eq("k21 N-1 the hook refuses the re-check's heredoc text with exit 2 (it exited 1, fail-open)", (code, "launch is blocked" in err),
                 (2, True))
        # and a walker that raises for ANY reason is a block with the door - never exit 1 (the synthetic internal error)
        boom = ("import sys\nsys.path.insert(0, " + repr(str(harness.SCRIPTS)) + ")\nimport hooklib\n"
                "def boom(self, *args, **kwargs):\n    raise IndexError('synthetic walker failure')\n"
                "hooklib._Reader._code = boom\n")
        for command in ("pytest -q", "git commit -m x tests/test_a.py"):
            code, err = run_hook(root, event(command), prelude=boom)
            check_eq(f"k21 N-1 a walker exception blocks the hook with exit 2, not 1 ({command})", code, 2)
            check_in(f"k21 N-1 ... the door names the guard's failure ({command})",
                     "could not read this command (IndexError: synthetic walker failure)", err)
            check_in(f"k21 N-1 ... and the way on ({command})", "split it into several simpler commands", err)
        code, err = run_hook(root, event("pytest -q"), prelude="import sys\n")
        check_eq("k21 N-1 control: the same process without the failure refuses the launch as always", (code, "launch is blocked" in err),
                 (2, True))
        # Q-9 sibling: the cutter every text check reads (`command_text_parts`) takes an argv list as its line, never str(list)
        argv = ["git", "config", "--global", "core.editor", "vim"]
        check_eq("k21 Q-9 command_text_parts reads an argv list as its line", G.command_text_parts(argv)["exec"],
                 "git config --global core.editor vim")
        check_in("k21 Q-9 ... so git_config_check refuses the argv list as it refuses the line", "changing git configuration is blocked",
                 G._blocked(G.git_config_check, event(argv), {}) or "")
    finally:
        cleanup(root)


# --- key 19 (critic 7b / F7): the mutants, as a committed table ----------------------------------------
# Every mutation is applied IN MEMORY to a copy of the module source (nothing on disk is touched) and
# the ONE key it names must go red. The table is the spec's twenty (t-466 Tests) plus the ones for the
# t-517 fixes; a snippet that no longer occurs exactly once fails the test (the table cannot rot).

HOOKLIB_PATH = harness.SCRIPTS / "hooklib.py"
GUARD_PATH = harness.SCRIPTS / "guard_pre_tool.py"


def mutant_module(path: Path, edits: list, name: str):
    source = path.read_text(encoding="utf-8")
    for old, new in edits:
        if source.count(old) != 1:
            return None, f"snippet occurs {source.count(old)} times: {old[:60]!r}"
        source = source.replace(old, new)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module, ""


def failures_with(world: dict, keys: list) -> list:
    """Run the key functions with `H` / `G` swapped for the mutants; the names of the checks that went red.
    The printing and the results of those runs are dropped: only the verdict is recorded by the caller."""
    saved = {name: globals()[name] for name in world}
    before = len(harness.RESULTS)
    globals().update(world)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            for key in keys:
                try:
                    key()
                except Exception as exc:  # a mutant that crashes the matcher is killed too
                    harness.RESULTS.append((False, f"{key.__name__} raised {type(exc).__name__}"))
    finally:
        globals().update(saved)
        added = harness.RESULTS[before:]
        del harness.RESULTS[before:]
    return [name for ok, name in added if not ok]


# (id, module, [(old, new)], key). `module` is "H" (hooklib) or "G" (guard_pre_tool).
SOURCE_MUTANTS = [
    ("hard-coded prefilter", "H",
     [('if any(all(word in norm for word in words) for words in launch_prefilter_tokens()):', 'if "pytest" in norm:')],
     k2_every_form_is_blocked_and_admitted),
    ("prefilter without the deletions", "H",
     [('norm = cmd.lower().translate(_STRIP_TABLE)', 'norm = cmd.lower()')], k15_prefilter_covers_the_matcher),
    ("a whole-command run_suite exemption", "H",
     [('    for reading in dialects:\n        walk(text, reading, hops)\n    return best',
       '    for reading in dialects:\n        if "run_suite" not in text:\n            walk(text, reading, hops)\n    return best')],
     k5_run_suite_exempts_its_own_segment),
    ("a whole-command diagnostic exemption", "H",
     [('    for reading in dialects:\n        walk(text, reading, hops)\n    return best',
       '    for reading in dialects:\n        if "--version" not in text and "--collect-only" not in text:\n            walk(text, reading, hops)\n    return best')],
     k4_diagnostics),
    ("`help` counted anywhere", "H",
     [('        return not (len(form["argv"]) >= 2 and c + 1 < len(low)\n'
       '                    and low[c + 1] in self.data["subcommand_diagnostics"])',
       '        return not any(w in self.data["subcommand_diagnostics"] for w in low[c + 1:])')],
     k4_diagnostics),
    ("the fallback removed", "H",
     [('    fallback = not any([f["argv"] == ["pytest"] for f in forms])', '    fallback = False')],
     k6_fallback_and_invalid_items),
    ("depth off by one", "H", [('_MAX_PAYLOAD_DEPTH = 3  #', '_MAX_PAYLOAD_DEPTH = 4  #')], k7_depth),
    ("a plain split (quotes not read)", "H",
     [('        elif ch == "\'":\n            self._single(f)', '        elif False:\n            self._single(f)'),
      ('        elif ch == \'"\':\n            self.stack.append(_Frame("dq"', '        elif False:\n            self.stack.append(_Frame("dq"')],
     k13_nothing_blocked_today_stops_being_blocked),
    ("payload flag only an exact -c", "H",
     [('return bool(_POSIX_PAYLOAD_FLAG_RE.fullmatch(word))', 'return word == "-c"')],
     k2_every_form_is_blocked_and_admitted),
    ("pwsh flag only right after the program", "H",
     [('flag = next((k for k in range(pos + 1, n) if _payload_flag(style, texts[k])), None)',
       'flag = next((k for k in range(pos + 1, min(n, pos + 2)) if _payload_flag(style, texts[k])), None)')],
     k2_every_form_is_blocked_and_admitted),
    ("backslash literal in bash double quotes", "H",
     [('elif not self.ps and ch == "\\\\" and i + 1 < n and', 'elif False and i + 1 < n and')],
     k13_nothing_blocked_today_stops_being_blocked),
    ("one dialect for both tools", "H",
     [('    for reading in dialects:\n        walk(text, reading, hops)\n    return best',
       '    for reading in dialects[:1]:\n        walk(text, reading, hops)\n    return best')], k14_dialects),
    ("the unbalanced quote hides the rest", "H",
     [('        self.dq_dead = True\n        self.i = frame.start', '        self.dq_dead = True\n        self.i = self.n')],
     k7_edges_empty_and_broken),
    ("a program word is not a candidate (the chain skips it)", "H",
     [('        chain.append(idx)\n        if wild[idx]:', '        if wild[idx]:\n            chain.append(idx)')],
     k2_every_form_is_blocked_and_admitted),
    ("negators ignored", "H",
     [('p = self.subcommand_at(word, form["_negators"], pos, c)', 'p = self.subcommand_at(word, frozenset(), pos, c)')],
     k3_near_misses_are_not_blocked),
    ("no option skip before -m", "H",
     [('        while j < n and not wild[j] and low[j].startswith("-") and low[j] not in subs:\n            j += 1',
       '        while False:\n            j += 1')],
     k2_every_form_is_blocked_and_admitted),
    ("payload recursion removed", "H",
     [('                        todo.append((inner, inner_dialect, depth + 1))', '                        pass')],
     k2_every_form_is_blocked_and_admitted),
    ("the form name dropped from the message", "G",
     [('a direct {form} launch is blocked - suites', 'a direct test launch is blocked - suites')],
     k8_k9_messages_and_codex),
    ("case-sensitive matching", "H",
     [('base = re.split(r"[\\\\/]", token)[-1].lower()', 'base = re.split(r"[\\\\/]", token)[-1]')],
     k2_every_form_is_blocked_and_admitted),
    # --- the t-517 fixes
    ("F1: runs_check back on command_text_parts", "G",
     [('    command = _split_off_bodies(str(raw or ""))[0]', '    command = command_text_parts(raw)["exec"]')],
     k16_a_quoted_argument_before_a_runner_name),
    # OH3-22 (ea9dbf5e) moved the body cut from guard_pre_tool into `hooklib.cut_bodies`: E17 and F-A below are aimed at its two
    # joins (an inline body's blank, and the blank's very existence), the module "H" now
    ("E17: the here-string join back to a newline", "H",
     [('        if record.inline:\n            glue = " "\n        kept = record.closer_end',
       '        kept = record.closer_end')],
     k22_cut_bodies_joins),
    ("F2: the subcommand scan back to the segment end", "H",
     [('found = self._table(word, negators)[pos]  #',
       'found = next((p for p in range(pos, len(low)) if low[p] == word and not (p > 0 and low[p - 1] in negators)), None)  #')],
     k17_reads_are_linear),
    ("F2: the diagnostic scan back to the segment end", "H",
     [('        return last > c\n', '        return any(token in diagnostics for token in self.low[c + 1:])\n')],
     k17_reads_are_linear),
    ("F-A: a PowerShell here-string joined with nothing at all", "H",
     [('        if record.inline:\n            glue = " "\n        kept = record.closer_end',
       '        if record.inline:\n            glue = ""\n        kept = record.closer_end')],
     k22_cut_bodies_joins),
    ("F-E: git_config_check back to splitting without the newline", "G",
     [('re.split(r"&&|\\|\\||;|\\||\\n", parts["exec"])', 're.split(r"&&|\\|\\||;|\\|", parts["exec"])')],
     k20_git_config_check_splits_on_newline),
    ("F3: --fixtures-per-test off the fallback", "H",
     [('"--fixtures", "--fixtures-per-test", "--markers"],', '"--fixtures", "--markers"],')],
     k13_without_the_data),
    ("F5: a word after `--` counts as a subcommand", "H",
     [('    if found is None or found >= self._next_dash[c + 1]:', '    if found is None:')],
     k18_dashdash_and_the_dotnet_negators),
    ("F6: an invalid word no longer named", "H",
     [('            problems.extend(sub)\n            continue', '            continue')],
     k6_fallback_and_invalid_items),
    ("7b: the earlier form picked backwards", "H",
     [('    return found if best is None or found < best else best', '    return found if best is None or found > best else best')],
     k17_linear_matching),
    ("7b: a $( ) region of a double-quoted run not recorded", "H",
     [('        elif ch == "$" and text.startswith("(", i + 1):\n            self._open(', '        elif False and text.startswith("(", i + 1):\n            self._open(')],
     k2_every_form_is_blocked_and_admitted),
]


def data_without(mutate) -> str:
    raw = json.loads((H.PLUGIN_ROOT / "references" / "launch-causes.json").read_text(encoding="utf-8-sig"))
    mutate(raw["run_forms"])
    return json.dumps(raw)


DATA_MUTANTS = [
    ("a form row removed (jest)", lambda rf: rf["forms"].remove(next(f for f in rf["forms"] if f["id"] == "jest")),
     k2_every_form_is_blocked_and_admitted),
    ("F5: -n / --name not dotnet negators",
     lambda rf: next(f for f in rf["forms"] if f["id"] == "dotnet-test")["negators"].remove("-n"),
     k18_dashdash_and_the_dotnet_negators),
]


def k19_every_mutant_is_killed() -> None:
    control, note = mutant_module(HOOKLIB_PATH, [("_MAX_PAYLOAD_DEPTH = 3  #", "_MAX_PAYLOAD_DEPTH = 3  #")], "hooklib_control")
    check("k19 CONTROL: an unchanged copy of hooklib loads", control is not None, note)
    if control is not None:
        red = failures_with({"H": control}, [k2_every_form_is_blocked_and_admitted, k13_nothing_blocked_today_stops_being_blocked])
        check("k19 CONTROL: and the keys stay green on it (so a red mutant is the mutation's doing)", not red, str(red[:3]))
    survivors = []
    for name, which, edits, key in SOURCE_MUTANTS:
        path = HOOKLIB_PATH if which == "H" else GUARD_PATH
        module, note = mutant_module(path, edits, f"{path.stem}_mutant")
        if module is None:
            survivors.append(f"{name}: {note}")
            continue
        if not failures_with({which: module}, [key]):
            survivors.append(f"{name}: {key.__name__} stayed green")
    for name, mutate, key in DATA_MUTANTS:
        def world(key=key):
            return failures_with({}, [key])
        result = []
        with_data(data_without(mutate), lambda: result.extend(world()))
        if not result:
            survivors.append(f"{name}: {key.__name__} stayed green")
    check(f"k19 all {len(SOURCE_MUTANTS) + len(DATA_MUTANTS)} mutants are killed by the key each names",
          not survivors, "; ".join(survivors))


def main() -> None:
    k1_shipped_data()
    k2_every_form_is_blocked_and_admitted()
    k3_near_misses_are_not_blocked()
    k4_diagnostics()
    k5_run_suite_exempts_its_own_segment()
    k6_fallback_and_invalid_items()
    k7_depth()
    k7_edges_empty_and_broken()
    k8_k9_messages_and_codex()
    k10_the_ten_selftest_cases()
    k11_hook_level()
    k12_the_loader_reads_once()
    k13_nothing_blocked_today_stops_being_blocked()
    k13_without_the_data()
    k14_dialects()
    k15_prefilter_covers_the_matcher()
    k16_a_quoted_argument_before_a_runner_name()
    k17_reads_are_linear()
    k17_linear_matching()
    k18_dashdash_and_the_dotnet_negators()
    k20_git_config_check_splits_on_newline()
    k21_fix_round_hook_path()
    k22_cut_bodies_joins()
    k19_every_mutant_is_killed()
    finish("test_run_forms")


if __name__ == "__main__":
    main()
