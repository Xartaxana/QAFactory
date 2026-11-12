"""activity capture on the Claude Code host.

Regression this guards: a Bash-invoked `activity_capture.py` is given neither --session nor a hook
event - every start/end of a real session (58e0f9dc) printed "ACTIVITY NOT RECORDED: session identity
missing" to stderr, so the whole session's cost fell under "(no task)" / non-factory. Pieces tested here:

  1. session_env.py (SessionStart hook, best-effort): writes CLAUDE_SESSION_ID into the file
     named by $CLAUDE_ENV_FILE when the host supplies one.
  2. The receipt (the path this factory actually relies on): telemetry_hook.py drops a small receipt
     naming the session, the script and the directories it can run in on every PreToolUse call that
     names a reader script, WHETHER OR NOT the project is onboarded (B-410; before config.json it goes
     to the spool under the home). `session_identity.resolve` reads it for activity_capture.py.
  3. K1: a fresh project, none of the variables the rules read, the home redirected: after the hook's
     receipt `activity_capture --action start --type onboarding` records an open onboarding activity
     in the spool, creates no `qa-factory/` and prints no refusal.
  4. E24: an activity recorded in the temp-folder spool before the upgrade is carried over once.
  5. hooklib.session_has_factory_activity: the scope gate the pre-tool guard needs.

And the backfill CLI that recovers a past session's already-lost activity intervals from its
own transcript's (failed) activity_capture.py Bash calls.

Mutations this file kills (each by this file alone): the writer gated on config again (K1).
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity_capture as A
import hooklib as H
import session_identity as SI
from harness import temp_dir, temp_project, cleanup, SCRIPTS

SESSION = "fixture-i36-session"


def clean_env(home, **extra):
    """E26: every name the rules read removed, the home and the temp folders redirected."""
    env = {k: v for k, v in os.environ.items() if k not in SI.load_rules()["env_vars"] and k != "CLAUDE_PROJECT_DIR"}
    for key in ("HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR"):
        env[key] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def test_session_env_writes_claude_session_id():
    env_path = SCRIPTS.parent / f".session-env-test-{os.getpid()}.txt"
    try:
        env = dict(os.environ, CLAUDE_ENV_FILE=str(env_path))
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "session_env.py")],
                                input=json.dumps({"hook_event_name": "SessionStart", "session_id": SESSION}),
                                text=True, capture_output=True, encoding="utf-8", env=env, timeout=30)
        assert result.returncode == 0, result.stderr
        assert env_path.exists() and f"CLAUDE_SESSION_ID={SESSION}" in env_path.read_text(encoding="utf-8")
    finally:
        env_path.unlink(missing_ok=True)


def test_session_env_never_fails_with_no_env_file():
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_ENV_FILE"}
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "session_env.py")],
                            input=json.dumps({"hook_event_name": "SessionStart", "session_id": SESSION}),
                            text=True, capture_output=True, encoding="utf-8", env=env, timeout=30)
    assert result.returncode == 0, result.stderr


def test_pretool_receipt_written_and_fallback_resolves_session():
    root = temp_project()
    H._PROJECT_ROOT_CACHE = None  # per-process cache (see hooklib.project_root); each test uses a fresh root
    try:
        target = root / "noop.py"
        target.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        event = {"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(root),
                  "tool_name": "Bash", "tool_input": {"command":
                  "python scripts/activity_capture.py --action start --type story --task T-1"}}
        home = temp_dir("qa-act-home-")
        try:
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "telemetry_hook.py"), str(target)],
                                    input=json.dumps(event), text=True, capture_output=True,
                                    encoding="utf-8", cwd=str(root), env=clean_env(home, CLAUDE_PROJECT_DIR=str(root)), timeout=30)
            assert result.returncode == 0, result.stderr

            receipts = list((root / "qa-factory" / "state" / "host-receipts").glob("pretool-*-activity_capture.json"))
            assert len(receipts) == 1, "telemetry_hook.py did not write one per-script PreToolUse receipt"
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            assert receipt["session_id"] == SESSION and receipt["script"] == "activity_capture.py"
            assert "activity_capture.py" in receipt["command"] and os.path.normcase(str(root)) in [os.path.normcase(c) for c in receipt["cwds"]]
            assert not (home / ".qa-factory").exists(), "an onboarded project's receipt must not go to the spool"

            # A Bash-invoked activity_capture.py with an empty event has no --session and no
            # hook-event session_id - only the receipt (the environment is empty here: E26).
            H._PROJECT_ROOT_CACHE = None
            found = SI.resolve({"cwd": str(root)}, "", "activity_capture.py", cwd=str(root), env={})
            assert (found["session_id"], found["source"]) == (SESSION, "receipt"), found
        finally:
            cleanup(home)
    finally:
        cleanup(root)


def test_stale_receipt_is_not_trusted():
    root = temp_project()
    H._PROJECT_ROOT_CACHE = None  # per-process cache; the previous test cached a different root
    try:
        receipts_dir = root / "qa-factory" / "state" / "host-receipts"
        receipts_dir.mkdir(parents=True)
        stale = receipts_dir / "pretool-0123456789abcdef-activity_capture.json"
        stale.write_text(json.dumps({"session_id": "stale-session", "script": "activity_capture.py", "cwds": [str(root)],
            "command": "python scripts/activity_capture.py --action start"}), encoding="utf-8")
        old = time.time() - 120
        os.utime(stale, (old, old))
        found = SI.resolve({"cwd": str(root)}, "", "activity_capture.py", cwd=str(root), env={})
        assert (found["session_id"], found["problem"]) == ("", "missing"), found
    finally:
        cleanup(root)


def test_k1_fresh_project_records_an_activity_before_any_config():
    """K1, through real processes: the hook's receipt, then the CLI, in a project with no qa-factory/."""
    proj, home = temp_dir("qa-act-fresh-"), temp_dir("qa-act-home-")
    try:
        env = clean_env(home)
        command = "python scripts/activity_capture.py --action start --type onboarding"
        event = {"hook_event_name": "PreToolUse", "session_id": "s-k1", "cwd": str(proj), "tool_name": "Bash",
                 "tool_input": {"command": command}}
        hook = subprocess.run([sys.executable, "-B", str(SCRIPTS / "telemetry_hook.py"), str(SCRIPTS / "guard_pre_tool.py")],
                              input=json.dumps(event), text=True, capture_output=True, encoding="utf-8", cwd=str(proj), env=env, timeout=60)
        assert hook.returncode == 0, hook.stderr
        spool = home / ".qa-factory" / "spool"
        assert list((spool / "qa-factory-receipts").glob("pretool-*-activity_capture.json")), "the hook wrote no receipt in the spool"
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "activity_capture.py"), "--action", "start", "--type", "onboarding"],
                              input="", text=True, capture_output=True, encoding="utf-8", cwd=str(proj), env=env, timeout=60)
        assert done.returncode == 0 and done.stderr == "", (done.returncode, done.stderr)
        files = list((spool / "qa-factory-activities").glob("*/s-k1.json"))
        assert len(files) == 1, f"no activity file under {spool}: {list(spool.rglob('*'))}"
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        assert [(a["type"], a["status"]) for a in doc["activities"]] == [("onboarding", "open")], doc["activities"]
        assert doc["session_id"] == "s-k1"
        assert not (proj / "qa-factory").exists(), "no qa-factory/ may appear before onboarding"
        # the control of the whole key: with no receipt (another cwd), the same CLI says why and records nothing
        other = temp_dir("qa-act-other-")
        try:
            refused = subprocess.run([sys.executable, "-B", str(SCRIPTS / "activity_capture.py"), "--action", "start", "--type", "doctor"],
                                     input="", text=True, capture_output=True, encoding="utf-8", cwd=str(other), env=env, timeout=60)
            assert refused.returncode == 0 and refused.stderr.startswith("ACTIVITY NOT RECORDED: Could not tell which session"), refused.stderr
            assert "as its own shell call" in refused.stderr and "qa-doctor" in refused.stderr and "<" not in refused.stderr, refused.stderr
            assert len(list((spool / "qa-factory-activities").glob("*/*.json"))) == 1
        finally:
            cleanup(other)
    finally:
        cleanup(proj)
        cleanup(home)


def test_e24_legacy_temp_spool_is_carried_over_once():
    root = temp_project()
    H._PROJECT_ROOT_CACHE = None
    session = f"legacy-{os.getpid()}"
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    legacy = Path(tempfile.gettempdir()) / "qa-factory-activities" / identity / f"{session}.json"
    home = temp_dir("qa-act-home-")
    saved = SI.spool_root
    SI.spool_root = lambda: home / ".qa-factory" / "spool"
    try:
        event = {"cwd": str(root)}
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"schema_version": 1, "session_id": session, "marker": "legacy"}), encoding="utf-8")
        target = A.activity_path(event, session)
        assert target.resolve() == (root / "qa-factory" / "state" / "activities" / f"{session}.json").resolve(), target
        assert json.loads(target.read_text(encoding="utf-8"))["marker"] == "legacy" and not legacy.exists(), "the legacy file is moved"
        # both present: the new-root file wins, the legacy file is left alone
        target.unlink()
        new = home / ".qa-factory" / "spool" / "qa-factory-activities" / identity / f"{session}.json"
        new.parent.mkdir(parents=True)
        new.write_text(json.dumps({"schema_version": 1, "session_id": session, "marker": "new"}), encoding="utf-8")
        legacy.write_text(json.dumps({"schema_version": 1, "session_id": session, "marker": "legacy"}), encoding="utf-8")
        target = A.activity_path(event, session)
        assert json.loads(target.read_text(encoding="utf-8"))["marker"] == "new", "the new-root file wins"
        assert legacy.is_file() and not new.exists(), "the legacy file is not merged and not deleted"
        # before config: the spool is the new root, never the temp folder
        bare = temp_dir("qa-act-bare-")
        try:
            H._PROJECT_ROOT_CACHE = None
            where = A.activity_path({"cwd": str(bare)}, session)
            assert str(where).startswith(str(home / ".qa-factory" / "spool")), where
        finally:
            cleanup(bare)
    finally:
        SI.spool_root = saved
        legacy.unlink(missing_ok=True)
        cleanup(home)
        cleanup(root)


def test_session_has_factory_activity_true_only_after_a_factory_type():
    root = temp_project()
    H._PROJECT_ROOT_CACHE = None  # per-process cache (see hooklib.project_root); each test uses a fresh root
    try:
        event = {"cwd": str(root)}
        assert H.session_has_factory_activity(SESSION, event) is False
        assert H.session_has_factory_activity("", event) is False
        path = A.activity_path(event, SESSION)
        A.update(path, SESSION, "start", "story", task="T-1", event_id="e1", timestamp="2026-09-21T08:00:00Z")
        assert H.session_has_factory_activity(SESSION, event) is True
    finally:
        cleanup(root)


def test_backfill_recovers_lost_story_activity_from_transcript():
    root = temp_project()
    H._PROJECT_ROOT_CACHE = None  # per-process cache; the previous test cached a different root
    transcript = root / "transcripts" / f"{SESSION}.jsonl"
    transcript.parent.mkdir(parents=True)
    try:
        def row(action, ts, tool_id):
            return json.dumps({"type": "assistant", "uuid": tool_id, "timestamp": ts,
                "message": {"model": "claude-sonnet-5", "content": [{"type": "tool_use",
                    "id": tool_id, "name": "Bash", "input": {"command":
                    f"python scripts/activity_capture.py --action {action} --type story --task T-1"}}]}})
        lines = [row("start", "2026-09-20T19:22:00Z", "tool-1"),
                 row("end", "2026-09-20T19:40:00Z", "tool-2")]
        transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = A.backfill(transcript, SESSION, "story", "T-1", event={"cwd": str(root)})
        assert result["replayed"] == 2, result

        doc = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        story = next(a for a in doc["activities"] if a["type"] == "story")
        assert story["task"] == "T-1"
        assert story["status"] == "closed"
        assert story["start_time"] == "2026-09-20T19:22:00Z"
        assert story["end_time"] == "2026-09-20T19:40:00Z"
        assert doc["recovery"]["backfilled_from_transcript"] is True
        assert doc["recovery"]["backfilled_events"] == 2

        # Idempotent: replaying the same transcript again must not duplicate the activity.
        result2 = A.backfill(transcript, SESSION, "story", "T-1", event={"cwd": str(root)})
        doc2 = json.loads(Path(result2["path"]).read_text(encoding="utf-8"))
        assert len(doc2["activities"]) == len(doc["activities"])
    finally:
        cleanup(root)


def main():
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print("PASS test_activity_session_identity")
    print(f"=== test_activity_session_identity: {len(tests)}/{len(tests)} ok ===")


if __name__ == "__main__":
    main()
