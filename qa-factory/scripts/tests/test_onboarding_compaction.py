"""B-411: the compaction hooks know about an unfinished onboarding (C1-C9).

precompact_guard.py prints one line for the PERSON when a run's notes are on disk, even with no config, and
creates nothing; postcompact_reload.py adds line 5 for the MODEL (and nothing at all, byte for byte, when no run
is open). Both run through telemetry_hook.py exactly as hooks.json wires them.

C7 pins the WRAPPING only: on Codex the PreCompact output travels as `systemMessage`; that it reaches the person
there has never been verified (design/codex-native-acceptance.md:29), and the live run L1 records where it appears.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import onboarding_notes as N  # noqa: E402
import postcompact_reload  # noqa: E402
import precompact_guard  # noqa: E402

DATA = N.load_data()
DASH = "—"
# Today's output with no run, as the file printed it before B-411 (the four lines, then print's newline).
TODAY = (
    "CONTEXT WAS COMPACTED. Before continuing factory work:\n"
    "1. Re-read the active skill's SKILL.md " + DASH + " after a compaction its body in context is truncated (~20k characters), the tail dropped silently.\n"
    "2. The current stage has a card: `story_step.py card --stage S<n>` prints it - run it.\n"
    "3. Re-read the task's pipeline.json checkpoint (qa-factory/artifacts/<task>/pipeline.json) " + DASH + " current stage, next_stage, notes.\n"
    "4. The compaction summary is not a carrier: post-compaction decisions rely on files, not on session memory.\n"
)


def tree(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*"))


def hook(script: str, root: Path, event: dict, cwd: Path | None = None, project_dir: bool = True) -> subprocess.CompletedProcess:
    """The hook as hooks.json runs it: telemetry_hook.py <script>, the event on stdin."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = str(root)
    where = cwd or root
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "telemetry_hook.py"), script], input=json.dumps(dict(event, cwd=str(where))),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(where), env=env, timeout=120)


PRE = {"hook_event_name": "PreCompact", "trigger": "manual", "session_id": "s1"}
POST = {"hook_event_name": "SessionStart", "source": "compact", "session_id": ""}


def run_open(prefix: str, phase: str = "p1") -> Path:
    root = temp_dir(prefix)
    notes = N.notes_dir(root, DATA)
    notes.mkdir(parents=True)
    (notes / ".gitignore").write_text("*\n", encoding="utf-8")
    now = "2026-10-06T10:00:00+00:00"
    progress = {"schema_version": 1, "started_at": now, "updated_at": now, "phase": phase, "head": "", "config_sha": "", "tree": "clean",
                "sealed": "", "approval_ref": "", "frozen": False}
    (notes / "progress.yaml").write_text(N.emit_progress(progress), encoding="utf-8")
    return root


def with_batches(root: Path) -> None:
    """Two batches: b1 answered (two topics), b2 awaiting."""
    notes = N.notes_dir(root, DATA)
    words = notes / "words"
    words.mkdir()
    (words / "batch-b1-1.txt").write_text("their words", encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(b"their words").hexdigest()
    batches = [
        {"batch": "b1", "asked_at": "2026-10-06T10:01:00+00:00", "times_asked": 1,
         "questions": [{"topic": "t1", "text": "one?", "ask": 1}, {"topic": "t2", "text": "two?", "ask": 1}],
         "replies": [{"words_file": "words/batch-b1-1.txt", "sha256": sha, "at": "2026-10-06T10:02:00+00:00", "answered": ["t1", "t2"], "not_answered": []}]},
        {"batch": "b2", "asked_at": "2026-10-06T10:03:00+00:00", "times_asked": 1,
         "questions": [{"topic": "t3", "text": "three?", "ask": 1}], "replies": []},
    ]
    (notes / "interview.yaml").write_text(N.emit_interview("2026-10-06T10:03:00+00:00", batches), encoding="utf-8")


def with_config(root: Path) -> None:
    (root / "qa-factory").mkdir(exist_ok=True)
    template = PLUGIN_ROOT / "references" / "templates" / "config.json"
    (root / "qa-factory" / "config.json").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def invoke_post(root: Path, payload: dict) -> str:
    """postcompact_reload.main() in process, with cwd = root and no session id (so no turn counter is touched)."""
    old_stdin, old_cwd = sys.stdin, os.getcwd()
    sys.stdin = io.StringIO(json.dumps(dict(payload, cwd=str(root))))
    out = io.StringIO()
    os.chdir(root)
    try:
        with contextlib.redirect_stdout(out):
            postcompact_reload.main()
    finally:
        os.chdir(old_cwd)
        sys.stdin = old_stdin
    return out.getvalue()


def precompact() -> None:
    # C2: no config, no run: nothing printed, nothing created
    root = temp_dir("qa-oc-none-")
    try:
        before = tree(root)
        p = hook("precompact_guard.py", root, PRE)
        check_eq("C2: no config and no run: exit 0, empty output", (p.returncode, p.stdout), (0, ""))
        check_eq("C2: ...and nothing created (no qa-factory/, no journal)", tree(root), before)
    finally:
        cleanup(root)

    # C1: no config, an open run: the line, exit 0, no journal, nothing created
    root = run_open("qa-oc-open-")
    try:
        with_batches(root)
        before = tree(root)
        p = hook("precompact_guard.py", root, PRE)
        notes = N.notes_dir(root, DATA)
        expected = (f"ONBOARDING IN PROGRESS: what this onboarding found and was told up to now is saved at {notes} "
                    "(phase p1, 2 topics answered, 1 batches awaiting a reply); after the compaction it resumes from there.")
        check_eq("C1: precompact with no config and an open run prints the person's line (before the config exit)", (p.returncode, p.stdout.strip()), (0, expected))
        check_eq("C1: ...and creates nothing: no journal file, no qa-factory/ besides the notes", tree(root), before)
        check("C1: the line says where the notes are, in the person's terms (no script name, no instruction to the model)",
              str(notes) in p.stdout and "onboarding_notes.py" not in p.stdout and "COMPACT GUARD" not in p.stdout)
    finally:
        cleanup(root)

    # C3: an unreadable run
    root = run_open("qa-oc-bad-")
    try:
        (N.notes_dir(root, DATA) / "progress.yaml").write_text("", encoding="utf-8")
        before = tree(root)
        p = hook("precompact_guard.py", root, PRE)
        check("C3: an unreadable run: the unreadable line is printed, exit 0",
              p.returncode == 0 and p.stdout.startswith("ONBOARDING IN PROGRESS: an onboarding folder is at ") and "its progress file cannot be read (" in p.stdout
              and "progress.yaml is empty" in p.stdout and p.stdout.strip().endswith("after the compaction the onboarding says what it can still use."), p.stdout)
        check_eq("C3: ...nothing created", tree(root), before)
    finally:
        cleanup(root)

    # C4: a config and an open run: the line, then the unchanged checklist, one journal event
    root = run_open("qa-oc-cfg-")
    try:
        with_config(root)
        p = hook("precompact_guard.py", root, PRE)
        lines = p.stdout.splitlines()
        check("C4: with a config the onboarding line comes first", p.returncode == 0 and lines and lines[0].startswith("ONBOARDING IN PROGRESS: what this onboarding found"), p.stdout[:200])
        check("C4: ...then the existing checklist, unchanged", len(lines) > 1 and lines[1].startswith("COMPACT GUARD: preserve unfinished work") and "The check: 'what of this work" in p.stdout, p.stdout)
        journals = [f for f in Path(root).rglob("journal.jsonl")]
        events = [json.loads(line) for f in journals for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        check_eq("C4: ...and exactly one compact event in the journal", [e["event"] for e in events], ["compact"])
    finally:
        cleanup(root)

    # a config and no run: the checklist alone, as today
    root = temp_dir("qa-oc-cfg-only-")
    try:
        with_config(root)
        p = hook("precompact_guard.py", root, PRE)
        check("a config and no run: no onboarding line, the checklist as before", p.returncode == 0 and p.stdout.startswith("COMPACT GUARD:") and "ONBOARDING" not in p.stdout, p.stdout[:200])
    finally:
        cleanup(root)

    # C8: the cwd is below the root
    root = run_open("qa-oc-below-")
    try:
        below = root / "src" / "deep"
        below.mkdir(parents=True)
        p = hook("precompact_guard.py", root, PRE, cwd=below, project_dir=False)
        check("C8: a session whose cwd is below the root still finds the run", p.returncode == 0 and "ONBOARDING IN PROGRESS" in p.stdout, p.stdout + p.stderr[-200:])
        p = hook("precompact_guard.py", root, PRE, cwd=below, project_dir=True)
        check("C8: ...and with CLAUDE_PROJECT_DIR at the root too", "ONBOARDING IN PROGRESS" in p.stdout, p.stdout)
        check("the hook created nothing below the root either", tree(below) == [])
    finally:
        cleanup(root)

    # C7: Codex: the line travels inside systemMessage (wrapping pinned; delivery unverified)
    root = run_open("qa-oc-codex-")
    try:
        p = hook("precompact_guard.py", root, dict(PRE, turn_id="t1"))
        wrapped = json.loads(p.stdout)
        check("C7 (wrapping pinned; delivery unverified): a Codex event puts the line in systemMessage",
              p.returncode == 0 and "ONBOARDING IN PROGRESS" in wrapped.get("systemMessage", ""), p.stdout)
    finally:
        cleanup(root)

    # the data file cannot be read: the generic line, naming the folder
    root = run_open("qa-oc-nodata-")
    saved = N.DATA_REL
    try:
        N.DATA_REL = "references/no-such-onboarding-notes.json"
        line = precompact_guard.onboarding_line({"cwd": str(root)})
        check("an unreadable data file: the hook still says where the folder is, generically",
              line.startswith("ONBOARDING IN PROGRESS: an onboarding folder is at ") and "no-such-onboarding-notes.json" in line, line)
        line = postcompact_reload.onboarding_line({"cwd": str(root)})
        check("...and line 5 still names the status command", line.startswith("\n5. An unfinished onboarding is on disk:") and "status" in line, line)
    finally:
        N.DATA_REL = saved
        cleanup(root)


def postcompact() -> None:
    # C5: no run: byte-identical to today's literal
    root = temp_dir("qa-oc-post-none-")
    try:
        out = invoke_post(root, POST)
        check_eq("C5: postcompact with no run is byte-identical to today's four lines", out, TODAY)
        p = hook("postcompact_reload.py", root, POST)
        check_eq("C5: ...through telemetry_hook as wired", (p.returncode, p.stdout), (0, TODAY))
        out = invoke_post(root, {"hook_event_name": "SessionStart", "source": "startup"})
        check_eq("a startup (not a compact) prints nothing, run or no run", out, "")
    finally:
        cleanup(root)

    # C6: a run: line 5 names the absolute status command and the phase file
    root = run_open("qa-oc-post-open-", "p2")
    try:
        with_batches(root)
        before = tree(root)
        out = invoke_post(root, POST)
        script = (SCRIPTS / "onboarding_notes.py").resolve()
        phase_file = (PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases" / "p2-interview.md").resolve()
        check("C6: the first four lines are untouched", out.startswith(TODAY.rstrip("\n")), out[:120])
        line5 = out[len(TODAY.rstrip("\n")):].strip()
        check_eq("C6: line 5 names the absolute status command and the absolute phase file, in the spec's words", line5,
                 f'5. An unfinished onboarding is on disk: run python "{script}" --root "{root.resolve()}" status, '
                 f"re-read {phase_file}, and continue from the notes: a topic they list as answered is not asked again.")
        check_eq("C6: nothing was created", tree(root), before)
        # C9: the phase decides the file
        for phase, name in (("p2", "p2-interview.md"), ("p3", "p3-summary-gate.md"), ("p2b", "p2b-rediscovery.md"), ("p1", "p1-discovery.md"), ("p4", "p4-generate.md")):
            (N.notes_dir(root, DATA) / "progress.yaml").write_text(
                N.emit_progress({"schema_version": 1, "started_at": "a", "updated_at": "a", "phase": phase, "head": "", "config_sha": "", "tree": "clean",
                                 "sealed": "", "approval_ref": "", "frozen": False}), encoding="utf-8")
            out = invoke_post(root, POST)
            check(f"C9: phase {phase} makes line 5 name {name}", f"re-read {(PLUGIN_ROOT / 'skills' / 'qa-onboarding' / 'phases' / name).resolve()}," in out, out[-300:])
        # an unreadable run: line 5 is still there (the status command says what is wrong)
        (N.notes_dir(root, DATA) / "progress.yaml").write_text("garbage", encoding="utf-8")
        out = invoke_post(root, POST)
        check("an unreadable run: line 5 is still printed (status explains)", "5. An unfinished onboarding is on disk:" in out, out[-200:])
        p = hook("postcompact_reload.py", root, POST)
        check("C6: through telemetry_hook as wired the line arrives, exit 0", p.returncode == 0 and "5. An unfinished onboarding" in p.stdout, p.stdout[-200:])
    finally:
        cleanup(root)

    # C8 for the model's line: a cwd below the root
    root = run_open("qa-oc-post-below-", "p3")
    try:
        below = root / "a" / "b"
        below.mkdir(parents=True)
        p = hook("postcompact_reload.py", root, POST, cwd=below, project_dir=False)
        check("C8: postcompact finds the run from a cwd below the root", "5. An unfinished onboarding" in p.stdout and "p3-summary-gate.md" in p.stdout, p.stdout[-300:])
    finally:
        cleanup(root)


def main() -> None:
    precompact()
    postcompact()
    finish("onboarding compaction hooks")


if __name__ == "__main__":
    main()
