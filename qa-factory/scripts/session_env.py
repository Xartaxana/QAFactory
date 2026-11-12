"""SessionStart hook: writes CLAUDE_SESSION_ID into $CLAUDE_ENV_FILE, when the host supplies
one, so a later Bash tool call in the SAME session can read its own session id straight out of
the environment. It is the package's own best-effort copy; the host's own variable is
CLAUDE_CODE_SESSION_ID (and CODEX_THREAD_ID on Codex). Every reader asks
session_identity.resolve, which takes the id from the hook's receipt of the very call and from
these variables and requires them to agree (B-410); this file is one of the variables it may read.

CLAUDE_ENV_FILE is NOT a documented Claude Code mechanism as of 2026-09-21 (checked against
https://code.claude.com/docs/en/hooks: the documented SessionStart input fields and the
documented hook-visible environment variables — CLAUDE_PROJECT_DIR, CLAUDE_PLUGIN_ROOT,
CLAUDE_PLUGIN_DATA, CLAUDE_EFFORT, CLAUDE_CODE_REMOTE, CLAUDE_CODE_BRIDGE_SESSION_ID — do not
include it). This script is therefore best-effort only, for a host version that does support
it; nothing in this package depends on it working. The path this factory actually relies on
and proves with a test is the receipt: the PreToolUse hook that fires moments before the Bash
call that runs activity_capture.py, host_probe.py or onboard_apply.py already carries the session
id and the command, in the very same event telemetry_hook.py already reads — see
telemetry_hook.py's _write_pretool_receipt and session_identity.write_receipt.

It also prints the ONE version line (hooklib.session_start_version_line) when the carriers disagree
in a way that needs a move: the plugin is behind, a frozen package differs, or the project's
configuration needs a migration; a project installed by an older release whose configuration is
current gets no line (AR-3); telemetry_hook forwards this hook's stdout to the session.

Never blocks the session: any error here -> exit 0, silently."""
import json
import os
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    # The version line (F-VERSION, t-232): ONE line, only when the four carriers (the running plugin,
    # the marketplace, the project's install record, its readiness report) disagree in a way that needs
    # a move (an older project with a current configuration is not one, AR-3). It goes
    # BEFORE the early return below: most hosts supply no CLAUDE_ENV_FILE, and the line must not wait
    # for one. A version note never stops a session from starting: any failure prints nothing.
    try:
        import hooklib
        line = hooklib.session_start_version_line(payload if isinstance(payload, dict) else {})
        if line:
            print(line)
    except Exception:
        pass
    session_id = str(payload.get("session_id") or "").strip()
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not session_id or not env_file:
        return
    try:
        with open(env_file, "a", encoding="utf-8") as fh:
            fh.write(f"CLAUDE_SESSION_ID={session_id}\n")
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
