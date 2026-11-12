"""t-1936 F1 (B-7): a rework dispatch gets its handover form and launch card from the ONE writer, once; a form already on disk is never rewritten.

Run: `python -B -m pytest <this file> -q`. Fast: `story_step` and `run_claude` are stubbed; no controller, no subprocess.
"""
import sys
import pytest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402
import story_step  # noqa: E402


class Stop(Exception):
    """Raised by the stubbed `run_claude`: everything before it is the branch under test."""


def driver(tmp_path):
    d = SR.Driver.__new__(SR.Driver)
    d.task, d.task_root = "QA-1", tmp_path
    d.stages = lambda: {"S3": {"id": "S3"}}
    d.boundary = ""
    d.state_dir = tmp_path / "state"
    d.plugin, d.scripts = "plugin", "plugin/scripts"
    d.system_file = lambda *a, **k: None
    d.progress_line = lambda: None
    d.retire_infra_result = lambda *a, **k: False

    def run_claude(*a, **k):
        raise Stop()
    d.run_claude = run_claude
    return d


def rework(**over):
    return dict({"id": "S3-qa-test-strategist-2", "scope": ["TS-1"], "reason": "fix it"}, **over)


def patch(monkeypatch, calls):
    monkeypatch.setattr(story_step, "_write_dispatch_files", lambda *a, **k: calls.append(("write", a, k)) or ("", []))
    monkeypatch.setattr(story_step, "_brief", lambda *a, **k: calls.append(("brief", a, k)) or ("brief.md", ""))
    monkeypatch.setattr(story_step, "_prompt", lambda *a, **k: "PROMPT")


def run(d):
    try:
        d.run_role("S3", "qa-test-strategist", rework=rework())
    except Stop:
        pass


def put_form_and_card(tmp_path):
    form = tmp_path / story_step.FORM_REL.format(dispatch_id="S3-qa-test-strategist-2")
    form.parent.mkdir(parents=True, exist_ok=True)
    form.write_text("role's own words", encoding="utf-8")
    card = story_step.launch_card.card_path(tmp_path, "S3-qa-test-strategist-2")
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("card", encoding="utf-8")
    return form


def test_rework_branch_writes_form_and_card_when_absent(tmp_path, monkeypatch):
    calls = []
    patch(monkeypatch, calls)
    run(driver(tmp_path))
    kinds = [c[0] for c in calls]
    assert kinds == ["write"], kinds
    _, args, kwargs = calls[0]
    assert args[:5] == ("QA-1", "S3", "qa-test-strategist", "S3-qa-test-strategist-2", tmp_path)
    assert args[5] == "TS-1" and kwargs.get("keep") is True


def test_rework_branch_keeps_brief_road_when_form_present(tmp_path, monkeypatch):
    calls = []
    patch(monkeypatch, calls)
    form = put_form_and_card(tmp_path)
    run(driver(tmp_path))
    assert [c[0] for c in calls] == ["brief"], "today's road: a fresh brief only, no rewrite of the form"
    assert form.read_text(encoding="utf-8") == "role's own words"


def test_rework_branch_card_mismatch_is_one_note(tmp_path, monkeypatch, capsys):
    def differs(*a, **k):
        raise ValueError("the launch card of X exists and differs")
    monkeypatch.setattr(story_step, "_write_dispatch_files", differs)
    monkeypatch.setattr(story_step, "_prompt", lambda *a, **k: "PROMPT")
    run(driver(tmp_path))
    said = capsys.readouterr().out
    assert said.count("note: the launch card of X exists and differs") == 1


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
