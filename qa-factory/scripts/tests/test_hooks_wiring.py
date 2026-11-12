"""Wiring test for hooks/hooks.json (A3 acceptance).

1. Reads hooks/hooks.json; every command's script must exist under scripts/.
2. In a temp directory WITHOUT qa-factory/ (an un-onboarded project), every wired script
   gets a minimal, matcher-appropriate event on stdin with CLAUDE_PROJECT_DIR pointed at
   that directory — every one of them must exit 0 (silent no-op outside onboarded projects,
   per the build plan's hard rule; guard_pre_tool.py still runs, it just finds nothing to
   block in these events).
3. In a temp git repo WITH qa-factory/config.json (app_root: "src", protected_app_paths:
   ["."]), guard_pre_tool.py must refuse (non-zero exit): a Write into src/app.py (P-00,
   the app-under-test boundary) and a Bash `pytest tests/` (the direct-test-run guard).
4. The LAUNCHER: parts 1-3 run each script with this interpreter, which is not what the
   harness does — it runs the command line verbatim, through hooks/run-py.cmd, with the
   event on stdin. Part 4 runs those literal command lines, and a red probe proves the
   check is load-bearing: the same line with ${CLAUDE_PLUGIN_ROOT} left unexpanded (the
   field failure where the hook becomes `python "/scripts/x.py"`) must NOT exit 0.

Run directly: python test_hooks_wiring.py  (also picked up by selftest.py --hooks/--tests)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PLUGIN_ROOT / "scripts"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"

RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((ok, name))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    return ok


def load_wiring() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


SCRIPT_RE = re.compile(r"([\w.-]+\.py)\s*$")


def iter_entries(wiring: dict):
    """Yields (event_name, matcher, script) for every hook command in hooks.json."""
    for event_name, entries in (wiring.get("hooks") or {}).items():
        for entry in entries:
            matcher = entry.get("matcher", "")
            for h in entry.get("hooks", []):
                m = SCRIPT_RE.search(str(h.get("command", "")))
                if m:
                    yield event_name, matcher, m.group(1)


def build_event(event_name: str, matcher: str) -> dict:
    """A minimal, matcher-appropriate event — just enough shape for the script's main() to
    read tool_name/tool_input or the event-specific fields it expects."""
    if event_name == "PreToolUse":
        first = (matcher.split("|") or [""])[0]
        if first in ("Write", "Edit", "NotebookEdit"):
            return {"hook_event_name": event_name, "tool_name": "Write",
                    "tool_input": {"file_path": "x.py", "content": "y"}}
        if first in ("Bash", "PowerShell"):
            return {"hook_event_name": event_name, "tool_name": "Bash",
                    "tool_input": {"command": "echo hi"}}
        # Agent|Task
        return {"hook_event_name": event_name, "tool_name": "Agent",
                "tool_input": {"subagent_type": "qa-scout", "prompt": "hi"}}
    if event_name == "PostToolUse":
        return {"hook_event_name": event_name, "tool_name": "Write",
                "tool_input": {"file_path": "x.py", "content": "y"}}
    if event_name == "SubagentStop":
        return {"hook_event_name": event_name, "session_id": "s1", "agent_type": "qa-scout"}
    if event_name == "Stop":
        return {"hook_event_name": event_name, "session_id": "s1"}
    if event_name == "PreCompact":
        return {"hook_event_name": event_name, "trigger": "manual", "session_id": "s1"}
    if event_name == "SessionStart":
        return {"hook_event_name": event_name, "source": matcher or "startup", "session_id": "s1"}
    return {"hook_event_name": event_name}


def run_script(script: str, event: dict, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        input=json.dumps(event), capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(cwd), env=env,
    )


def iter_command_lines(wiring: dict):
    """Yields (event_name, matcher, the literal command string) — the harness's own input,
    before any substitution."""
    for event_name, entries in (wiring.get("hooks") or {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                line = str(h.get("command", "")).strip()
                if line:
                    yield event_name, entry.get("matcher", ""), line


def part4_launcher(wiring: dict, tmp_root: Path) -> bool:
    """A hook that works when called as `python scripts/x.py` and fails as the harness calls
    it is a hook that does not work. Two known ways it breaks live in the launcher, not in
    the script: ${CLAUDE_PLUGIN_ROOT} not expanding, and no Python on the launcher's PATH."""
    ok = True
    proj = tmp_root / "launcher-project"
    proj.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # children must not litter the package
    env["CLAUDE_PROJECT_DIR"] = str(proj)

    def shell(line: str, event: dict) -> subprocess.CompletedProcess:
        return subprocess.run(line, shell=True, input=json.dumps(event), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", cwd=str(proj),
                              env=env, timeout=120)

    probed = False
    for event_name, matcher, line in iter_command_lines(wiring):
        event = build_event(event_name, matcher)
        p = shell(line.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT)), event)
        tail = (p.stderr or p.stdout).strip().splitlines()
        ok = check(f"runs through the launcher: {line.split()[-1]} ({event_name})",
                   p.returncode == 0,
                   f"exit {p.returncode}" + (f" — {tail[-1][:100]}" if tail else "")) and ok

        if not probed:  # once is enough — the launcher is the same file for every entry
            probed = True
            red = shell(line.replace("${CLAUDE_PLUGIN_ROOT}", ""), event)
            ok = check("RED PROBE: the same line with ${CLAUDE_PLUGIN_ROOT} unexpanded fails",
                       red.returncode != 0,
                       "it exited 0 — this part is not testing the launcher at all") and ok
    return ok


def part4b_receipt_before_config(wiring: dict, tmp_root: Path) -> bool:
    """K7 (B-410, E1): the receipt is written before any config exists, and the hook creates no `qa-factory/`.

    Part 2 runs only the inner script and gives PreToolUse no session, so a writer that created `qa-factory/` (or
    wrote nothing at all) would pass it. This part runs the literal launcher line of the PreToolUse hook
    (`telemetry_hook.py guard_pre_tool.py`, which is where the writer lives) with an event that names a reader
    script and carries a session, in a project with no `qa-factory/`; HOME, USERPROFILE and the temp folders are
    pointed at a test folder, so the spool is the test's. Asserts both sides: nothing appears in the project, and the
    receipt exists in the spool (the positive control: without it "nothing appears" holds for any code at all)."""
    rules = json.loads((PLUGIN_ROOT / "references" / "session-identity.json").read_text(encoding="utf-8"))
    line = next((l for e, _m, l in iter_command_lines(wiring)
                 if e == "PreToolUse" and l.endswith("telemetry_hook.py guard_pre_tool.py")), "")
    if not check("K7: hooks.json wires `telemetry_hook.py guard_pre_tool.py` on PreToolUse", bool(line)):
        return False
    proj, home = tmp_root / "k7-project", tmp_root / "k7-home"
    proj.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in rules["env_vars"]}   # E26: no id of the session that runs this test
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    for key in ("HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR"):
        env[key] = str(home)
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s-k7", "cwd": str(proj),
             "tool_input": {"command": "python activity_capture.py --action start"}}
    p = subprocess.run(line.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT)), shell=True, input=json.dumps(event),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(proj), env=env, timeout=120)
    ok = check("K7: the launcher line exits 0 for an event naming a reader script, with no qa-factory/ in the project",
               p.returncode == 0, f"exit {p.returncode} | {(p.stderr or p.stdout).strip()[-200:]}")
    ok = check("K7: ...and the hook created no qa-factory/ in the project", not (proj / "qa-factory").exists(),
               str(sorted(x.name for x in proj.rglob("*")))) and ok
    spool = home / ".qa-factory" / "spool" / rules["spool_dir"]
    made = sorted(x.name for x in spool.glob("pretool-*-activity_capture.json")) if spool.is_dir() else []
    return check("K7: ...and the receipt is in the spool under the home (the positive control)", len(made) == 1, f"found {made} under {spool}") and ok


def part1_scripts_exist(wiring: dict) -> bool:
    ok = True
    for event_name, matcher, script in iter_entries(wiring):
        exists = (SCRIPTS / script).exists()
        ok = check(f"script exists: {script} ({event_name} / {matcher!r})", exists,
                   "not found under scripts/") and ok
    return ok


def part2_noop_unonboarded(wiring: dict, tmp_root: Path) -> bool:
    ok = True
    proj = tmp_root / "unonboarded-project"
    proj.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # children must not litter the package
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    for event_name, matcher, script in iter_entries(wiring):
        event = build_event(event_name, matcher)
        p = run_script(script, event, proj, env)
        tail = (p.stdout or p.stderr).strip().splitlines()
        ok = check(
            f"exit 0 outside an onboarded project: {script} ({event_name} / {matcher!r})",
            p.returncode == 0,
            f"exit {p.returncode}" + (f" | {tail[-1][:160]}" if tail else ""),
        ) and ok
    return ok


def part2b_open_notes_no_config(wiring: dict, tmp_root: Path) -> bool:
    """B-411 (A11): an onboarding run's notes are on disk and there is no config yet. Every wired hook
    must still exit 0 and must create nothing: the notes folder is the only thing under qa-factory/, and its
    file list is the same after all of them have run (no hook ever creates `qa-factory/` on its own) - but for the
    one known exception named below."""
    ok = True
    proj = tmp_root / "open-notes-project"
    notes = proj / "qa-factory" / "state" / "onboarding"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / ".gitignore").write_text("*\n", encoding="utf-8")
    (notes / "progress.yaml").write_text(
        'schema_version: 1\nstarted_at: "2026-10-06T10:00:00+00:00"\nupdated_at: "2026-10-06T10:00:00+00:00"\nphase: "p2"\n'
        'head: ""\nconfig_sha: ""\ntree: "clean"\nsealed: ""\napproval_ref: ""\nfrozen: false\n', encoding="utf-8")

    def listing() -> list:
        return sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*"))
    before = listing()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # children must not litter the package
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    for event_name, matcher, script in iter_entries(wiring):
        event = build_event(event_name, matcher)
        p = run_script(script, event, proj, env)
        tail = (p.stdout or p.stderr).strip().splitlines()
        ok = check(
            f"exit 0 with open onboarding notes and no config: {script} ({event_name} / {matcher!r})",
            p.returncode == 0,
            f"exit {p.returncode}" + (f" | {tail[-1][:160]}" if tail else ""),
        ) and ok
    new = sorted(set(listing()) - set(before))
    # KNOWN DIVERGENCE (found by this test, B-411; exit_gate.py is not this node's file): the SubagentStop hook writes
    # `qa-factory/state/.exit_gate_blocks.json` whenever the event names an agent type, with or without a config - and in a
    # project with no `qa-factory/` at all it creates `qa-factory/` and `state/` to do it (measured by probe, 07.10.2026).
    # That file is the ONLY allowed difference; anything else a hook leaves behind fails here. When exit_gate.py learns to
    # stay out of a project with no config, this name has no work left to do and goes.
    # TR4-2 part D: exit_gate takes the one file-lock helper (event_store.take_file_lock), which by design never deletes its
    # lock file, so the known file leaves exactly its own `.lock` sidecar - that name only, nothing wider.
    known = ["qa-factory/state/.exit_gate_blocks.json", "qa-factory/state/.exit_gate_blocks.json.lock"]
    ok = check("open notes, no config: the file list under the project is unchanged after every hook ran "
               "(but for the one file exit_gate.py is known to write)",
               [p for p in new if p not in known] == [] and [p for p in before if p not in listing()] == [],
               f"new: {new}") and ok
    ok = check("open notes, no config: the notes folder itself is untouched by every hook",
               [p for p in listing() if p.startswith("qa-factory/state/onboarding")] == [p for p in before if p.startswith("qa-factory/state/onboarding")]) and ok
    return ok


def part3_p00_and_runs_refusal(tmp_root: Path) -> bool:
    ok = True
    repo = tmp_root / "onboarded-repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True)
    qf = repo / "qa-factory"
    qf.mkdir()
    (qf / "config.json").write_text(json.dumps({
        "app_root": "src",
        "protected_app_paths": ["."],
    }), encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # children must not litter the package
    env["CLAUDE_PROJECT_DIR"] = str(repo)

    write_event = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": str(repo / "src" / "app.py"), "content": "x = 1"}}
    p = run_script("guard_pre_tool.py", write_event, repo, env)
    ok = check("P-00 refusal: Write into src/app.py is blocked", p.returncode != 0,
               f"exit {p.returncode} (expected non-zero)") and ok

    bash_event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                  "tool_input": {"command": "pytest tests/"}}
    p = run_script("guard_pre_tool.py", bash_event, repo, env)
    ok = check("direct-test-run refusal: `pytest tests/` in Bash is blocked", p.returncode != 0,
               f"exit {p.returncode} (expected non-zero)") and ok
    return ok


def part5_role_specific_runtime_injection(tmp_root: Path) -> bool:
    """Exercise the hook process, not just the map: each lifecycle reference reaches only
    the roles that need it, while common injection stays bounded."""
    expected = {
        # the slices references/slices/<role>/handoff-keys.md replaced coverage-design.md for these four (inject-map.json)
        "qa-scout": ["plugin:references/slices/qa-scout/handoff-keys.md"],
        "qa-requirements-tester": ["plugin:references/slices/qa-requirements-tester/handoff-keys.md"],
        "qa-test-strategist": ["plugin:references/slices/qa-test-strategist/handoff-keys.md", "plugin:references/risk-policy.md"],
        "qa-case-designer": ["plugin:references/slices/qa-case-designer/handoff-keys.md"],
        "qa-case-critic": ["plugin:references/coverage-design.md", "plugin:references/risk-policy.md"],
        "qa-automator": ["plugin:references/execution-lifecycle.md"],
        "qa-code-critic": ["plugin:references/execution-lifecycle.md"],
        # t-1957 N4: the walk charter replaced manual-evidence.md in the runner's injection (inject-map.json); the old grammar is reached by the path
        # a fallback brief names (brief_pack.fallback_grammar_line), not injected
        "qa-runner": ["plugin:references/walk-charter.md"],
    }
    proj = tmp_root / "runtime-injection"
    proj.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # children must not litter the package
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    ok = True
    for role, refs in expected.items():
        event = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
                 "tool_input": {"subagent_type": role, "prompt": "bounded task"}}
        p = run_script("inject_context.py", event, proj, env)
        try:
            output = json.loads(p.stdout)
            delivered = output["hookSpecificOutput"]["updatedInput"]["prompt"]
        except (json.JSONDecodeError, KeyError):
            delivered = ""
        present = p.returncode == 0 and all(ref in delivered for ref in refs)
        ok = check(f"runtime injection delivers lifecycle references to {role}", present,
                   f"exit {p.returncode}; missing expected source header") and ok
    imap = json.loads((PLUGIN_ROOT / "references" / "inject-map.json").read_text(encoding="utf-8"))
    lifecycle_refs = {ref for ref in imap.get("common", [])
                      if ref.endswith(("coverage-design.md", "risk-policy.md",
                                       "execution-lifecycle.md", "manual-evidence.md"))}
    ok = check("lifecycle references are role-specific, not common", not lifecycle_refs,
               f"unexpected common entries: {sorted(lifecycle_refs)}") and ok
    return ok


def main() -> int:
    import tempfile

    if not HOOKS_JSON.exists():
        print(f"FAIL hooks/hooks.json is missing at {HOOKS_JSON}")
        return 1
    wiring = load_wiring()

    ok = part1_scripts_exist(wiring)
    with tempfile.TemporaryDirectory(prefix="qa-factory-hooks-wiring-") as td:
        tmp_root = Path(td)
        ok = part2_noop_unonboarded(wiring, tmp_root) and ok
        ok = part2b_open_notes_no_config(wiring, tmp_root) and ok
        ok = part3_p00_and_runs_refusal(tmp_root) and ok
        ok = part4_launcher(wiring, tmp_root) and ok
        ok = part4b_receipt_before_config(wiring, tmp_root) and ok
        ok = part5_role_specific_runtime_injection(tmp_root) and ok

    bad = sum(1 for good, _ in RESULTS if not good)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} ok")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
