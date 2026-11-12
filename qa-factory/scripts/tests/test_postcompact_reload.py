"""a compact resets the turn counter of the session it fires in.

Claude Code keeps ONE session_id across a `/compact` (unlike a brand new session), so the
turn counter — keyed only by session_id — used to keep climbing as if nothing had happened.
On TP1-15045 one counter survived a compact and two fresh `/qa-story` starts
(`{"count": 94, "started": "...00:30:17", "notified": 90}`), and the stale total came back
as a hook denial worded "this dispatch has made 90 tool calls" on the very next qualifying
tool call of a brand new window. `postcompact_reload.py` is the `SessionStart` (source:
compact) hook; it now zeroes that session's `state/turns/<session>.json` before printing its
carrier-refresh reminder.
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import postcompact_reload  # noqa: E402
import turn_budget  # noqa: E402
import hooklib  # noqa: E402


def invoke(payload: dict) -> str:
    """Runs postcompact_reload.main() with `payload` as its stdin JSON, returns stdout."""
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            postcompact_reload.main()
    finally:
        sys.stdin = old_stdin
    return out.getvalue()


def main() -> None:
    root = temp_dir("qa-postcompact-")
    (root / "qa-factory" / "state").mkdir(parents=True)
    template = PLUGIN_ROOT / "references" / "templates" / "config.json"
    (root / "qa-factory" / "config.json").write_text(template.read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    old_cache = hooklib._PROJECT_ROOT_CACHE
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        session = "sess-compact-1"
        event = {"tool_name": "Bash", "session_id": session, "tool_input": {"command": "ls"}}
        cfg = {"turns": {"soft": 5, "repeat": 5}}
        for _ in range(7):
            turn_budget.check(event, cfg)
        before = turn_budget.read_count(turn_budget.counter_path(session))
        check("the session carries a real count before the compact fires",
              before.get("count", 0) >= 7, True)

        invoke({"hook_event_name": "SessionStart", "source": "compact", "session_id": session})
        after = turn_budget.read_count(turn_budget.counter_path(session))
        check_eq("SessionStart:compact resets the count to zero", after.get("count"), 0)
        check_eq("and the notified mark", after.get("notified"), 0)
        check_eq("and records why", after.get("reset_reason"), "compact")

        for _ in range(3):
            turn_budget.check(event, cfg)
        after_more = turn_budget.read_count(turn_budget.counter_path(session))
        check_eq("the counter counts fresh calls again after a reset",
                 after_more.get("count"), 3)

        other_session = "sess-untouched"
        other_event = dict(event, session_id=other_session)
        turn_budget.check(other_event, cfg)
        before_other = turn_budget.read_count(turn_budget.counter_path(other_session)).get("count")
        invoke({"hook_event_name": "SessionStart", "source": "startup", "session_id": other_session})
        after_other = turn_budget.read_count(turn_budget.counter_path(other_session))
        check_eq("a SessionStart that is NOT a compact does not reset anything",
                 after_other.get("count"), before_other)

        turn_budget.check(event, cfg)
        carried = turn_budget.read_count(turn_budget.counter_path(session)).get("count", 0)
        out = invoke({"hook_event_name": "SessionStart", "source": "compact", "session_id": session})
        check("the compact reminder is still printed", "CONTEXT WAS COMPACTED" in out)
        reset_again = turn_budget.read_count(turn_budget.counter_path(session))
        check_eq("a second compact resets again, regardless of what was carried",
                 reset_again.get("count"), 0)
        check("the carried count was indeed nonzero going in (the reset had work to do)",
              carried > 0)

        out_no_session = invoke({"hook_event_name": "SessionStart", "source": "compact"})
        check("a compact event with no session_id never raises — the reminder still prints",
              "CONTEXT WAS COMPACTED" in out_no_session)
    finally:
        hooklib._PROJECT_ROOT_CACHE = old_cache
        cleanup(root)

    finish("postcompact_reload: turn-counter reset on compact")


if __name__ == "__main__":
    main()
