"""Post-compaction guard (SessionStart, source=compact) — the pair of precompact_guard.py.

That one saves the carriers BEFORE compression; this one reminds to restore the instructions
AFTER. Host fact (qafactory lesson, confirmed on 2026-09-01): after a compaction the bodies
of previously loaded skills are re-injected into context TRUNCATED (~20k characters) — the tail
of the instructions drops out silently and the agent does not know it. The reminder is printed
to the SessionStart hook's stdout and becomes the freshest piece of context (the "instruction
travels with the result" principle).

Never blocks: any error -> exit 0 (guard fail-open)."""
import json
import sys


def onboarding_line(payload: dict) -> str:
    """Line 5, only when an unfinished onboarding is on disk (B-411): "\\n5. ..." naming the status command and
    the phase text to re-read. SessionStart output reaches the model on both hosts, so this one is addressed to
    it. "" when no run is open or anything fails: the output is then byte-identical to what it always was."""
    try:
        from pathlib import Path as _Path
        sys.path.insert(0, str(_Path(__file__).resolve().parent))
        import onboarding_notes
        import hooklib
        saved = hooklib._PROJECT_ROOT_CACHE     # the root is looked up with the event, but never pinned for what runs after
        try:
            root = hooklib.project_root(payload)
        finally:
            hooklib._PROJECT_ROOT_CACHE = saved
        found = onboarding_notes.open_onboarding(root, payload)
        if not found["open"]:
            return ""
        script = _Path(onboarding_notes.__file__).resolve()
        try:
            phase_text = onboarding_notes.phase_file(found["phase"], onboarding_notes.load_data())
        except Exception:
            phase_text = ""
        reread = f"re-read {phase_text}" if phase_text else "re-read the phase text its `phase` names"
        return (f'\n5. An unfinished onboarding is on disk: run python "{script}" --root "{found["root"]}" status, '
                f"{reread}, and continue from the notes: a topic they list as answered is not asked again.")
    except Exception:
        return ""


def main() -> None:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if payload.get("source") != "compact" and payload.get("hook_event_name") != "PostCompact":
        return
    # a compact does not start a new session_id on Claude Code, so the turn counter
    # (keyed by session_id) would otherwise keep the whole morning's count and re-trigger a
    # stale "N tool calls" notice on the very first call of what is, for the orchestrator,
    # a brand new window.
    try:
        session_id = str(payload.get("session_id") or "")
        if session_id:
            from pathlib import Path as _Path
            import sys as _sys
            _sys.path.insert(0, str(_Path(__file__).resolve().parent))
            import turn_budget
            turn_budget.reset(session_id, payload, "compact")
    except Exception:
        pass  # a reset that fails never blocks the session from starting
    print(
        "CONTEXT WAS COMPACTED. Before continuing factory work:\n"
        "1. Re-read the active skill's SKILL.md — after a compaction its body in context is truncated (~20k characters), the tail dropped silently.\n"
        "2. The current stage has a card: `story_step.py card --stage S<n>` prints it - run it.\n"
        "3. Re-read the task's pipeline.json checkpoint (qa-factory/artifacts/<task>/pipeline.json) — current stage, next_stage, notes.\n"
        "4. The compaction summary is not a carrier: post-compaction decisions rely on files, not on session memory."
        + onboarding_line(payload)
    )


if __name__ == "__main__":
    try:
        main()
        from metric_signals import context as signal_context
        from hooklib import project_root
        notice = signal_context(project_root())
        if notice: print(notice)
    finally:
        sys.exit(0)
