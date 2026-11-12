#!/usr/bin/env python3
"""PK0-8: the project-knowledge registry's write commands (`project_knowledge.py account|role|revoke`) and its file
(`qa-factory/records/project-knowledge.json`) are closed to every role; `show` stays open (FR-39), the conductor is never
blocked, and another script that happens to take the word `role` is not caught."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import guard_pre_tool as G  # noqa: E402

ROLE = {"agent_type": "qa-factory:qa-automator"}


def _word(command, who=ROLE):
    return G._blocked(G.human_word_check, dict(who, tool_name="Bash", tool_input={"command": command}), {})


def test_role_running_account_role_revoke_is_blocked():
    for sub in ("account", "role", "revoke"):
        for command in (f"python project_knowledge.py {sub} --task T",
                        f"python -B scripts/project_knowledge.py {sub} --id PK-1",
                        f"python -c \"import subprocess; subprocess.run(['python', 'project_knowledge.py', '{sub}', '--task', 'T'])\"",
                        f"python -c \"import subprocess; subprocess.run(['project_knowledge.py','{sub}'])\""):
            assert _word(command) is not None, command


def test_role_running_side_is_blocked():
    """PC-1b: `side` is a person-word door like `account`, in the space and the argv-list spellings; `sides` is not it."""
    for command in ("python project_knowledge.py side --name ui --reality real --words-file w.txt",
                    "python -B scripts/project_knowledge.py side --name ui --reference --stand old",
                    "python -c \"import subprocess; subprocess.run(['python', 'project_knowledge.py', 'side', '--name', 'ui'])\"",
                    "python -c \"import subprocess; subprocess.run(['project_knowledge.py','side'])\""):
        assert _word(command) is not None, command
        assert _word(command, who={}) is None, command          # the conductor is never blocked
    assert _word("python project_knowledge.py sides") is None
    assert _word("python project_knowledge.py show") is None     # `show` stays open beside it
    message = _word("python project_knowledge.py side --name ui") or ""
    assert "`project_knowledge.py side`" in message and "(`show` is open to you)" in message.split("project_knowledge.py side", 1)[1]


def test_show_stays_open():
    assert _word("python project_knowledge.py show") is None
    assert _word("python -c \"import subprocess; subprocess.run(['project_knowledge.py', 'show'])\"") is None


def test_conductor_not_blocked():
    for sub in ("account", "role", "revoke"):
        assert _word(f"python project_knowledge.py {sub} --task T", who={}) is None


def test_another_script_with_role_word_not_blocked():
    assert _word("python role_load.py role") is None
    assert _word("python project_knowledge.py roles") is None


def test_role_write_to_project_knowledge_json_blocked():
    root = temp_project()
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        use_project(root)
        record = (root / "qa-factory" / "records" / "project-knowledge.json").as_posix()
        role = dict(ROLE, cwd=str(root))
        for tool in ("Write", "Edit"):
            assert G._blocked(G.stand_record_write_check, dict(role, tool_name=tool, tool_input={"file_path": record}), {}) is not None
        text = G._blocked(G.stand_record_write_check, dict(role, tool_name="Write", tool_input={"file_path": record}), {}) or ""
        assert "qa-factory/records/project-knowledge.json" in text and "answer registry" in text      # F5: says what it is
        assert "`project_knowledge.py show` is open to you" in text and "conductor records it" in text   # the open command, the door
        assert "stand halt below does not apply to this file" in text
        for command in (f"echo '{{}}' > {record}", "echo x >> qa-factory/records/project-knowledge.json"):
            assert G._blocked(G.stand_record_write_check, dict(role, tool_name="Bash", tool_input={"command": command}), {}) is not None
        assert G._blocked(G.stand_record_write_check, dict(role, tool_name="Bash", tool_input={"command": f"cat {record}"}), {}) is None
        assert G._blocked(G.stand_record_write_check,
                          {"cwd": str(root), "tool_name": "Write", "tool_input": {"file_path": record}}, {}) is None
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(root)


def test_message_names_show_as_open():
    message = _word("python project_knowledge.py role --task T") or ""
    assert "`project_knowledge.py account`, `role` and `revoke`" in message
    assert "(`show` is open to you)" in message.split("project_knowledge.py account", 1)[1]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                check(name, True)
            except AssertionError as exc:
                check(name, False, str(exc))
    finish("test_guard_project_knowledge")
