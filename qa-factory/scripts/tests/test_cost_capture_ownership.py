"""The cost pass reads only this project's transcripts (I-93).

TP1-15045 ended with 10 cost files in the project, 8 of them sessions opened one and two
directories ABOVE it (the factory's own development in `D:/ws3`): 273 MB of
transcripts, one of them a live session still growing. Both halves of the cost layer read
them — the hook wrote a foreign session's file here in the first place, and every dashboard
build recomputed the stale ones from those transcripts, so a render took minutes unless a
person set QA_FACTORY_SKIP_DASHBOARD_REFRESH=1 by hand.

What this test pins: the recapture pass skips a parent-directory session and says so, skips a
transcript that is too large or still being written, and recomputes a parent session anyway
when a person asks for that one by id; the hook writes nothing for a parent-directory session
and still writes for this project's session and for a host that names no project folder.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import temp_project, temp_dir, cleanup, use_project, check, check_eq, check_in, finish, SCRIPTS

TASK = "TP1-OWN"
HOUR_AGO = time.time() - 3600


def _row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def _assistant(request_id, ts, with_marker=False):
    usage = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    content = [{"type": "tool_use", "id": "toolu_marker", "name": "Write",
                "input": {"file_path": f"qa-factory/artifacts/{TASK}/understanding.md"}}] if with_marker else []
    return _row(type="assistant", isSidechain=False, requestId=request_id, uuid="u-" + request_id,
                timestamp=ts, message={"model": "claude-sonnet-5", "usage": usage, "content": content})


def _transcript(store: Path, slug: str, session_id: str, aged: bool = True) -> Path:
    """One session transcript where the host puts it: <store>/projects/<slug>/<id>.jsonl —
    the slug is how `session_project_slug` learns which directory the session was opened in."""
    folder = store / "projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    path.write_text(_assistant("req-1", "2026-09-20T19:00:00Z", with_marker=True) + "\n", encoding="utf-8")
    if aged:
        os.utime(path, (HOUR_AGO, HOUR_AGO))
    return path


def _stale_cost_file(root: Path, session_id: str, transcript: Path) -> Path:
    """A cost file in the shape 0.7.4 wrote them: no has_factory_activity, so the pass finds
    it stale and has to decide whether it may read the transcript at all."""
    out = root / "qa-factory" / "state" / "cost" / f"{session_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"session_id": session_id, "transcript": str(transcript),
                               "generated": "2026-09-20T19:05:00+00:00", "total_cost_usd": None,
                               "by_task": {}, "requests": []}), encoding="utf-8")
    return out


def _hook_capture(root: Path, session_id: str, transcript: Path):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1",
               QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
    event = {"hook_event_name": "Stop", "session_id": session_id,
             "transcript_path": str(transcript), "cwd": str(root)}
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")],
                          input=json.dumps(event), text=True, capture_output=True,
                          encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)


def main() -> None:
    root = temp_project()
    use_project(root)
    store = temp_dir(prefix="qa-transcripts-")
    try:
        here = C.project_slug(Path(root).resolve())
        above = C.project_slug(Path(root).resolve().parent)

        own = _transcript(store, here, "sess-own")
        parent = _transcript(store, above, "sess-parent")
        live = _transcript(store, here, "sess-live", aged=False)
        big = _transcript(store, here, "sess-big")
        # Rule 4: the subagent folder is read with the main chain, so it weighs with it.
        subagents = big.parent / big.stem / "subagents"
        subagents.mkdir(parents=True)
        (subagents / "agent-1.jsonl").write_text(
            "\n".join(_assistant(f"req-sub-{i}", "2026-09-20T19:00:01Z") for i in range(200)) + "\n",
            encoding="utf-8")
        os.utime(subagents / "agent-1.jsonl", (HOUR_AGO, HOUR_AGO))

        for session_id, transcript in (("sess-own", own), ("sess-parent", parent),
                                       ("sess-live", live), ("sess-big", big)):
            _stale_cost_file(root, session_id, transcript)

        check_eq("session opened above the project reads as 'parent'",
                 C.session_belongs_to({"transcript": str(parent)}, here), "parent")
        check_eq("session opened in the project reads as 'this'",
                 C.session_belongs_to({"transcript": str(own)}, here), "this")

        size, age = C.transcript_footprint(big)
        check("the subagent folder counts toward the transcript's size",
              size > (subagents / "agent-1.jsonl").stat().st_size, f"{size} bytes")
        check("an aged transcript reports its age in seconds", age is not None and age > 3000, str(age))

        # --- the unattended pass: ownership, size, liveness -------------------------------
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["cost"] = dict(cfg.get("cost") or {}, recapture_max_mb=0.01)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        by_session = {r["session_id"]: r for r in C.recapture_stale(root)}
        check_eq("a parent-directory session is skipped by the pass",
                 by_session.get("sess-parent", {}).get("status"), "skipped")
        check_eq("and the skip names the reason in the agreed words",
                 by_session.get("sess-parent", {}).get("reason"), "parent directory - not recaptured")
        check_eq("a transcript over cost.recapture_max_mb is skipped",
                 by_session.get("sess-big", {}).get("status"), "skipped")
        check_in("and the skip names both sizes", "exceeds 0.01 MB",
                 by_session.get("sess-big", {}).get("reason", ""))
        check_eq("a transcript written minutes ago is skipped as still live",
                 by_session.get("sess-live", {}).get("status"), "skipped")
        check_in("and the skip says how long ago it changed", "still live",
                 by_session.get("sess-live", {}).get("reason", ""))
        check_eq("this project's own stale session is recomputed",
                 by_session.get("sess-own", {}).get("status"), "recomputed")
        check_eq("nothing was written for the parent session while it was skipped",
                 json.loads((root / "qa-factory" / "state" / "cost" / "sess-parent.json")
                            .read_text(encoding="utf-8")).get("total_cost_usd"), None)

        # --- the CLI pass: thresholds lifted, ownership still enforced ---------------------
        explicit = {r["session_id"]: r for r in C.recapture_stale(root, explicit=True)}
        check_eq("--all-stale recomputes the oversize transcript",
                 explicit.get("sess-big", {}).get("status"), "recomputed")
        check_eq("--all-stale recomputes the live transcript",
                 explicit.get("sess-live", {}).get("status"), "recomputed")
        check_eq("--all-stale still leaves a parent-directory session alone",
                 explicit.get("sess-parent", {}).get("status"), "skipped")

        # A person naming the session passes the block — the standing rule of this factory.
        outcome = C.recapture_session(root, "sess-parent")
        check_eq("--recapture --session recomputes a parent session on demand",
                 outcome["status"], "recomputed")
        recomputed = json.loads((root / "qa-factory" / "state" / "cost" / "sess-parent.json")
                                .read_text(encoding="utf-8"))
        check("the named parent session now carries a real capture",
              recomputed.get("total_cost_usd") is not None, str(recomputed.get("total_cost_usd")))

        # --- the default, read with no config key at all -----------------------------------
        cfg.pop("cost", None)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        check_eq("the shipped default is 64 MB", C.RECAPTURE_MAX_MB_DEFAULT, 64)
        skip = C._recapture_skip({"transcript": str(big)}, here, float(C.RECAPTURE_MAX_MB_DEFAULT), False)
        check_eq("a 40 KB transcript is nowhere near the default cap", skip, None)

        # --- the hook path -----------------------------------------------------------------
        hook_parent = _transcript(store, above, "hook-parent")
        hook_own = _transcript(store, here, "hook-own")
        unknown = store / "chats" / "hook-unknown.jsonl"   # Codex: no project folder in the path
        unknown.parent.mkdir(parents=True, exist_ok=True)
        unknown.write_text(_assistant("req-1", "2026-09-20T19:00:00Z", with_marker=True) + "\n",
                           encoding="utf-8")

        cost_dir = root / "qa-factory" / "state" / "cost"
        result = _hook_capture(root, "hook-parent", hook_parent)
        check_eq("the hook exits 0 for a parent-directory session", result.returncode, 0)
        check_eq("and writes no cost file for it", (cost_dir / "hook-parent.json").exists(), False)

        _hook_capture(root, "hook-own", hook_own)
        check_eq("the hook still writes this project's own session",
                 (cost_dir / "hook-own.json").exists(), True)

        _hook_capture(root, "hook-unknown", unknown)
        check_eq("a host that names no project folder keeps today's behaviour",
                 (cost_dir / "hook-unknown.json").exists(), True)
    finally:
        cleanup(store)
        cleanup(root)
    finish("test_cost_capture_ownership")


if __name__ == "__main__":
    main()
