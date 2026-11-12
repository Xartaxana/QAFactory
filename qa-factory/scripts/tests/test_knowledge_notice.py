#!/usr/bin/env python3
"""t-2142 PK0-3: the optional `product_roles` section of the S3 form and the noticed recorder (AR-10, AR-21, AR-22, AR-23, AR-28, AR-29).

Keys: a role the strategist names that the roster lacks is written as `noticed_unconfirmed` (never `known`); a role known by form,
a role the person turned down, an absent form, `[]`, a placeholder-only row and a `no_trace` story write nothing; the recorder is
idempotent and never raises; the section is written through the role's sanctioned values road; the check gives an old form and a
placeholder-only new form no problem the same form did not get before the template change; the call sits in `Driver.gate_repair`
after the kept-answer branch and before `gate_entry_steps`.

Mutations this file kills: a placeholder row read as a role | a noticed row written as `known` | a role known by form noticed again |
a not-needed role noticed again | a write under `no_trace` | a raise out of the recorder | the call moved before the kept-answer
returns or after `gate_entry_steps` | a section the check starts to owe.

Run: python -m pytest scripts/tests/test_knowledge_notice.py -q
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import pytest  # noqa: E402

import handoff  # noqa: E402
import handoff_check as HC  # noqa: E402
import handoff_init  # noqa: E402
import hooklib  # noqa: E402
import project_knowledge as PK  # noqa: E402

CONTRACT = "s3-strategist-to-designer"
TICKET = "T-1"
DISPATCH = "S3-qa-test-strategist-1"
SECTION = re.compile(r"(?ms)^# Optional: every role the plan checks.*?^product_roles:.*?(?=^\S)")


def template() -> str:
    return (handoff.CONTRACTS / f"{CONTRACT}.yaml").read_text(encoding="utf-8")


def old_template() -> str:
    """The template as a package before this node shipped it: no `product_roles` section."""
    text = SECTION.sub("", template())
    assert "product_roles" not in text
    return text


def begun(text: str) -> str:
    return handoff_init.fill_head(text, task=TICKET, dispatch=DISPATCH, role="qa-test-strategist", stage="S3", scope="")


def with_values(form: str, pairs: dict) -> tuple:
    doc, applied, problems, notes = HC.apply_values(handoff.parse(form), CONTRACT,
                                                    [(path, value, 0, f"{path}: {value}") for path, value in pairs.items()])
    return doc.text(), applied, problems, notes


class Proj:
    def __init__(self, path: Path, monkeypatch, pipeline=None):
        self.root = path / "proj"
        self.task = self.root / "qa-factory" / "artifacts" / TICKET
        (self.task / "state").mkdir(parents=True)
        (self.task / "work" / "handoffs").mkdir(parents=True)
        (self.root / "qa-factory").joinpath("config.json").write_text(json.dumps({"environment": {}, "environments": []}), encoding="utf-8")
        if pipeline is not None:
            (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(self.root))
        monkeypatch.setattr(hooklib, "_PROJECT_ROOT_CACHE", None, raising=False)

    def accept(self, form: str) -> None:
        """The strategist's dispatch is accepted and its form is on disk (what `brief_pack.last_accepted_form` finds)."""
        (self.task / "work" / "handoffs" / f"{DISPATCH}.yaml").write_text(form, encoding="utf-8")
        record = {"dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S3", "role": "qa-test-strategist", "status": "accepted"}}}
        (self.task / "state" / "controller.json").write_text(json.dumps(record), encoding="utf-8")

    def accept_roles(self, *roles, text=None) -> None:
        pairs = {}
        for n, (role, sign_in, where) in enumerate(roles):
            pairs.update({f"product_roles[{n}].role": role, f"product_roles[{n}].sign_in": sign_in, f"product_roles[{n}].where": where})
        form, _applied, problems, _notes = with_values(begun(text or template()), pairs)
        assert not problems, problems
        self.accept(form)

    def notice(self) -> list:
        return PK.notice_from_handoff(self.root, self.task, TICKET)

    def rows(self) -> list:
        path = PK.record_path(self.root)
        return json.loads(path.read_text(encoding="utf-8"))["facts"] if path.is_file() else []


@pytest.fixture
def proj(tmp_path, monkeypatch):
    return Proj(tmp_path, monkeypatch)


def test_notice_writes_noticed_for_new_role(proj):
    proj.accept_roles(("auditor", "account", "R-2"), ("guest", "none", "R-3"))
    assert len(proj.notice()) == 2
    rows = proj.rows()
    assert [(r["element"], r["state"], r["scope"], r["key"]) for r in rows] == [
        ("auditor", "noticed_unconfirmed", "project", "product.roles"), ("guest", "noticed_unconfirmed", "project", "product.roles")]
    assert rows[0]["provenance"]["source"] == "role" and rows[0]["provenance"]["by"] == "driver"
    assert rows[0]["provenance"]["where"] == "R-2" and rows[1]["value"] == {"sign_in": "none"}
    assert all(r["state"] != "known" for r in rows)
    assert PK.state(proj.root, PK.ROLES_KEY, "", "auditor")["state"] == "noticed_unconfirmed"


def test_notice_skips_known_by_form(proj):
    PK.record(proj.root, key=PK.ROLES_KEY, environment="", element="Auditor", state="known", scope="project",
              value={"sign_in": "account"}, words="yes", source="person", story="T-0", by="conductor")
    proj.accept_roles(("auditor", "account", "R-2"), ("  AUDITOR ", "account", "R-4"))
    assert proj.notice() == []
    assert [r["state"] for r in proj.rows()] == ["known"]


def test_notice_skips_not_needed(proj):
    PK.record(proj.root, key=PK.ROLES_KEY, environment="", element="auditor", state="not_needed", scope="project",
              value=None, words="no, not a role", source="person", story="T-0", by="conductor")
    proj.accept_roles(("auditor", "account", "R-2"))
    assert proj.notice() == []
    assert [r["state"] for r in proj.rows()] == ["not_needed"]


def test_notice_idempotent(proj):
    proj.accept_roles(("auditor", "account", "R-2"))
    assert len(proj.notice()) == 1
    assert proj.notice() == []
    assert len(proj.rows()) == 1


def test_notice_absent_handoff_writes_nothing(proj):
    assert proj.notice() == []                                  # no controller state at all
    proj.accept(begun(old_template()))                          # a form begun on the older package: no section
    assert proj.notice() == []
    assert not PK.record_path(proj.root).exists()


def test_notice_empty_list_writes_nothing(proj):
    form = begun(template())
    form = re.sub(r"(?ms)^product_roles:.*?(?=^\S)", "product_roles: []\n\n", form)
    assert "product_roles: []" in form
    proj.accept(form)
    assert proj.notice() == []
    assert not PK.record_path(proj.root).exists()


def test_notice_placeholder_row_writes_nothing(proj):
    proj.accept(begun(template()))                              # the placeholder row left as handoff_init made it
    assert proj.notice() == []
    assert not PK.record_path(proj.root).exists()


def test_notice_no_trace_writes_nothing(tmp_path, monkeypatch, capsys):
    proj = Proj(tmp_path, monkeypatch, pipeline={"ticket": TICKET, "no_trace": True})
    proj.accept_roles(("auditor", "account", "R-2"), ("guest", "none", "R-3"))
    assert proj.notice() == []
    assert not PK.record_path(proj.root).exists()
    err = capsys.readouterr().err
    assert "no trace" in err and len(err.strip().splitlines()) == 1     # one stderr line for the story, not silence, not one per role


def test_notice_prints_unreadable_form_reason(proj, monkeypatch, capsys):
    monkeypatch.setattr(PK, "story_roles", lambda _task: ([], "the strategist's form could not be read (OSError)"))
    assert proj.notice() == []
    assert "could not be read" in capsys.readouterr().err


def test_notice_never_raises(proj, monkeypatch, capsys):
    proj.accept_roles(("auditor", "account", "R-2"))

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(PK, "record", boom)
    assert proj.notice() == []
    assert "RuntimeError" in capsys.readouterr().err
    monkeypatch.undo()
    assert PK.notice_from_handoff(None, None, TICKET) == []     # nothing to read: still no raise


def test_values_write_product_roles(proj):
    form, applied, problems, notes = with_values(
        begun(template()), {"product_roles[0].role": "auditor", "product_roles[0].sign_in": "account", "product_roles[0].where": "R-2"})
    assert applied == 3 and not problems and not notes
    proj.accept(form)
    roles, reason = PK.story_roles(proj.task)
    assert roles == [{"role": "auditor", "sign_in": "account", "where": "R-2"}] and reason == ""


def check_problems(form: str) -> list:
    _doc, _fixed, problems, _judged, _derived = HC.check(handoff.parse(form), CONTRACT, HC.Artifacts(Path("."), dispatch=DISPATCH),
                                                         use_judge=False)
    return [(p.path, p.text, p.fix) for p in problems]


def test_old_and_new_forms_pass_the_check(tmp_path):
    old_form = begun(old_template())
    new_form = begun(template())
    assert "product_roles" not in old_form and "product_roles:" in new_form
    before = check_problems(old_form)                           # (i) a form WITHOUT the section, the template before the edit
    # (ii) a form begun on the new template with only the placeholder row owes nothing the old form did not owe
    assert check_problems(new_form) == before
    # (i) again, on the new package: the same form with the section cut out
    assert check_problems(SECTION.sub("", new_form)) == before


def test_placeholder_row_reads_empty(proj):
    proj.accept(begun(template()))
    assert PK.story_roles(proj.task) == ([], "")


def test_in_flight_form_values_not_refused(proj):
    """U-5 / F-41: a form begun on the OLD template takes a values line for `product_roles` with no refusal; the outcome is pinned."""
    form, applied, problems, notes = with_values(begun(old_template()), {"product_roles[0].role": "auditor"})
    assert not problems                                         # never a refusal
    # Measured outcome (U-5): WRITTEN, not the M-7 "not written" line - the contract spec (the new template) knows the path, so the
    # section is opened at the end of the old form; the placeholder hints of the other two fields read as `account` and "".
    assert applied == 1 and notes == []
    assert form.rstrip().endswith("  - role: auditor\n    sign_in: <optional: account or none>\n    where: <optional: the requirement id>")
    proj.accept(form)
    assert PK.story_roles(proj.task) == ([{"role": "auditor", "sign_in": "account", "where": ""}], "")
    assert len(proj.notice()) == 1 and proj.rows()[0]["state"] == "noticed_unconfirmed"


def drive_gate_repair(monkeypatch, kept) -> list:
    """`Driver.gate_repair("A")` on a stub `self` that records each step it reaches; the real method decides the order. `kept` is
    the answer `kept_answer` returns ({} = none). The spy replaces `project_knowledge.notice_from_handoff`."""
    import story_run
    order = []
    monkeypatch.setattr(PK, "notice_from_handoff", lambda *args: order.append(("notice", args)) or [])

    def entry(gate):
        order.append(("entry", gate))

    def rehearse(gate):
        raise RuntimeError("stop here")                          # the gate is shown without the rehearsal: the call returns

    me = type("Rig", (), {})()
    me.dry, me.state, me.project, me.task_root, me.task = False, {}, "P", "TR", "T-1"
    me.pipeline = lambda: {"ticket": TICKET}
    me.old_kept_answer = lambda gate: ""
    me.kept_answer = lambda gate: kept
    me.record_by_code = lambda *a, **k: order.append(("recorded", k.get("again"))) or True
    me.save_state = lambda: None
    me.apply_question_answers = lambda stage: {"opened": False}
    me.gate_entry_steps, me.rehearse = entry, rehearse
    story_run.Driver.gate_repair(me, "A")
    return order


def test_gate_a_notices_after_the_kept_answer_branch_and_before_the_entry_steps(monkeypatch):
    """The wiring the source pin guarded, by behaviour: with no kept answer the notice is called once, with the handoff's project,
    task root and ticket, BEFORE `gate_entry_steps`; with a kept answer the decision is recorded again and nothing is noticed."""
    order = drive_gate_repair(monkeypatch, {})
    assert order == [("notice", ("P", "TR", TICKET)), ("entry", "A")]
    order = drive_gate_repair(monkeypatch, {"words": "go on"})
    assert order == [("recorded", True)]                         # nothing is written once the person has spoken


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
