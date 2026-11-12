#!/usr/bin/env python3
"""t-2142 PK0-1: the project's answer registry `project_knowledge.py` (AR-13, AR-14, AR-24, AR-25, AR-28, AR-29; FR-45, FR-59).

Keys: a fact recorded during a story outlives `restore_config` (the FIRST test); an absent file reads as config only and every
reader writes nothing; the ERROR DIRECTION is toward asking - an unreadable registry, a foreign `schema_version`, `facts` not a list,
a revoked row, a row for another spelling of a stand, twins, a malformed note, a state outside the list, an `asked` row and an
unparseable `at` never read as `known`; the latest row wins; the same state again is not a new row; a `no_trace` story, a busy lock
and an unreadable registry write nothing; `record` loads, decides, numbers and writes inside the lock (two writers keep both rows);
the account CLI writes the config first through `record_stand_account` and the registry second; the words travel whole.

Mutations this file kills: `state()` reading a registry row before the config | a revoked row still covering | `Dev` meeting `dev` |
an unparseable `at` winning | a second row for the same state | a write under `no_trace` | `load` called before the lock | a reader that
writes | a placeholder row of the template read as a role.

Run: python -B scripts/tests/test_project_knowledge.py    or    python -m pytest scripts/tests/test_project_knowledge.py -q
"""
import json
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import pytest  # noqa: E402

import config_contract as CC  # noqa: E402
import event_store as ES  # noqa: E402
import hooklib  # noqa: E402
import project_decisions as PD  # noqa: E402
import project_knowledge as PK  # noqa: E402

AUDITOR = "QA_AUDITOR_EMAIL / QA_AUDITOR_PASSWORD"
NON_ASCII = "".join(chr(code) for code in (0x2014, 0x20, 0x430, 0x443, 0x434, 0x438, 0x442, 0x43E, 0x440))      # a dash and a Cyrillic word, by code point
WORDS = "yes, auditor is a read-only role;\nits account is QA_AUDITOR_EMAIL / QA_AUDITOR_PASSWORD " + NON_ASCII
STAND_ARGS = ["--task", "T-1", "--role", "auditor", "--user-key", "QA_AUDITOR_EMAIL", "--secret-key", "QA_AUDITOR_PASSWORD"]


class Proj:
    """A throwaway project: `qa-factory/config.json` with the stands, one story folder `T-1`, the hook layer pointed at it."""

    def __init__(self, path: Path, monkeypatch, stands=None, pipeline=None):
        self.root = path / "proj"
        self.stands = stands if stands is not None else [{"name": "dev", "base_url": "http://localhost:8080", "credentials_by_role": {}}]
        self.config = self.root / "qa-factory" / "config.json"
        self.config.parent.mkdir(parents=True)
        self.write_config()
        self.task = self.root / "qa-factory" / "artifacts" / "T-1"
        self.task.mkdir(parents=True)
        if pipeline is not None:
            (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        self.words = path / "words.txt"
        self.words.write_bytes(WORDS.encode("utf-8"))                                        # bytes: no platform line-ending change
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(self.root))
        monkeypatch.setattr(hooklib, "_PROJECT_ROOT_CACHE", None, raising=False)

    def write_config(self, **extra):
        self.config.write_text(json.dumps(dict({"environment": {}, "environments": self.stands}, **extra), indent=2) + "\n", encoding="utf-8")

    def cfg(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def path(self) -> Path:
        return PK.record_path(self.root)

    def facts(self, rows) -> None:
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(json.dumps({"schema_version": 1, "facts": rows}), encoding="utf-8")

    def rows(self) -> list:
        return json.loads(self.path().read_text(encoding="utf-8"))["facts"]

    def record(self, **over):
        args = dict(key=PK.ROLES_KEY, environment="", element="auditor", state="known", scope="project", value={"sign_in": "account"},
                    words="the person said so", source="person", story="T-1", by="conductor")
        args.update(over)
        return PK.record(self.root, **args)

    def state(self, key=PK.ROLES_KEY, environment="", element="auditor") -> dict:
        return PK.state(self.root, key, environment, element)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    return Proj(tmp_path, monkeypatch)


def fact(id, key, environment, element, state, at, **extra) -> dict:
    scope = "stand" if key == PK.ACCOUNTS_KEY else "project"
    return dict({"id": id, "key": key, "environment": environment, "element": element, "state": state, "scope": scope, "value": None,
                 "provenance": {"source": "person", "words": "w", "story": "S-1", "by": "conductor", "where": ""}, "at": at}, **extra)


def role_fact(id, element, state, at, **extra) -> dict:
    return fact(id, PK.ROLES_KEY, "", element, state, at, **extra)


def account_fact(id, environment, element, at, **extra) -> dict:
    return fact(id, PK.ACCOUNTS_KEY, environment, element, "known", at, **extra)


def short_lock(monkeypatch):
    """The writers' lock with a 0.2 s wait, so a busy lock is a quick test."""
    real = PK.lock
    monkeypatch.setattr(PK, "lock", lambda root: real(root, 0.2))


def hold(proj: Proj):
    """Another handle holds the writers' lock (a second handle in one process is busy)."""
    return ES.take_file_lock(proj.root / Path(PK.LOCK_REL), 0.0, record_holder=True)


def run(argv) -> int:
    return PK.main(argv)


# --- the first test: the fact outlives the story ---------------------------------------------------------------------------

def test_fact_survives_restore_config(proj):
    proj.write_config()
    CC.snapshot_config(proj.root, proj.task, True)
    proj.write_config(note_by_hand="a hand edit of the story, no recorded writer")           # reverted at the end, unlike the account
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 0
    assert proj.cfg()["environments"][0]["credentials_by_role"] == {"auditor": AUDITOR}
    result = CC.restore_config(proj.root, proj.task)
    assert result["state"] == "reverted" and result["kept"] == ["/environments"], result       # the decision receipt is a recorded writer
    assert proj.cfg()["environments"][0]["credentials_by_role"] == {"auditor": AUDITOR}
    assert "note_by_hand" not in proj.cfg()
    assert [r["key"] for r in proj.rows()] == [PK.ACCOUNTS_KEY, PK.ROLES_KEY]                 # records/ is never reverted
    got = proj.state(PK.ACCOUNTS_KEY, "dev")
    assert got["state"] == "known" and got["row"]["id"] == "PK-1" and got["source"] == "person"


# --- reading ---------------------------------------------------------------------------------------------------------------

def test_absent_file_reads_config_only(proj):
    proj.stands[0]["credentials_by_role"] = {"auditor": AUDITOR}
    proj.write_config()
    assert not proj.path().exists()
    got = proj.state(PK.ACCOUNTS_KEY, "dev")
    assert (got["state"], got["source"], got["problem"], got["row"]) == ("known", "legacy_config", "", None)
    assert proj.state()["state"] == "unknown" and proj.state()["problem"] == ""
    roster = PK.roster(proj.root, proj.cfg(), "dev")
    assert [(e["role"], e["source"], e["account"]) for e in roster["elements"]] == [("auditor", "legacy_config", True)]
    assert not proj.path().exists() and not (proj.root / Path(PK.LOCK_REL)).exists(), "a reader wrote something"


def test_first_record_creates_file(proj):
    assert not proj.path().exists()
    row, problem, created = proj.record()
    assert problem == "" and created is True and row["id"] == "PK-1"
    assert proj.rows() == [row]
    assert (row["key"], row["environment"], row["element"], row["state"], row["scope"]) == ("product.roles", "", "auditor", "known", "project")
    assert row["provenance"] == {"source": "person", "words": "the person said so", "story": "T-1", "by": "conductor", "where": ""}
    assert row["at"].endswith("+00:00") and "revoked_at" not in row


def test_unreadable_registry_refuses_write_and_reads_config(proj):
    proj.stands[0]["credentials_by_role"] = {"auditor": AUDITOR}
    proj.write_config()
    for label, text in (("not json", "{ not json"), ("facts not a list", json.dumps({"schema_version": 1, "facts": {"a": 1}})),
                        ("not an object", "[1, 2]")):
        proj.path().parent.mkdir(parents=True, exist_ok=True)
        proj.path().write_text(text, encoding="utf-8")
        held = proj.path().read_bytes()
        got = proj.state(PK.ACCOUNTS_KEY, "dev")
        assert got["state"] == "known" and got["problem"], label                             # config first, the problem said (FR-41)
        assert proj.state()["state"] == "unknown" and proj.state()["problem"], label
        row, problem, created = proj.record()
        assert row is None and created is False and "nothing was written over it" in problem and "project_knowledge.py show" in problem, label
        assert proj.path().read_bytes() == held, label


def test_foreign_schema_version_is_unknown(proj):
    proj.path().parent.mkdir(parents=True)
    proj.path().write_text(json.dumps({"schema_version": 2, "facts": [role_fact("PK-1", "auditor", "not_needed", "2026-11-01T10:00:00+00:00")]}),
                           encoding="utf-8")
    got = proj.state()
    assert got["state"] == "unknown" and "schema_version" in got["problem"]
    assert PK.roster(proj.root, proj.cfg(), "dev")["removed"] == []
    row, problem, _ = proj.record()
    assert row is None and "schema_version" in problem


def test_revoked_row_covers_nothing(proj):
    row, _, _ = proj.record(state="not_needed", value=None)
    assert proj.state()["state"] == "not_needed"
    taken, problem = PK.revoke(proj.root, row["id"], "ask again")
    assert problem == "" and taken["revoked_at"] and taken["revoked_words"] == "ask again"
    assert proj.state()["state"] == "unknown"
    assert PK.roster(proj.root, proj.cfg(), "dev")["removed"] == []
    assert PK.revoke(proj.root, row["id"], "again")[0] is None                                 # already taken back
    assert "PK-9" in PK.revoke(proj.root, "PK-9", "x")[1] and "project_knowledge.py show" in PK.revoke(proj.root, "PK-9", "x")[1]
    assert PK.revoke(proj.root, row["id"], "  ")[0] is None                                    # empty words
    # a revoked LATER row does not hide the earlier live one (the live state is the latest LIVE row)
    proj.facts([role_fact("PK-1", "auditor", "known", "2026-11-01T10:00:00+00:00"),
                role_fact("PK-2", "auditor", "not_needed", "2026-11-02T10:00:00+00:00", revoked_at="2026-11-03T10:00:00+00:00")])
    assert proj.state()["state"] == "known"


def test_stand_name_exact(proj):
    proj.stands[0]["credentials_by_role"] = {"auditor": AUDITOR}
    proj.write_config()
    proj.facts([account_fact("PK-1", "Dev", "auditor", "2026-11-01T10:00:00+00:00"),
                account_fact("PK-2", "", "auditor", "2026-11-01T10:00:00+00:00")])           # another spelling; an empty stand: skipped
    assert proj.state(PK.ACCOUNTS_KEY, "Dev")["state"] == "unknown"                          # no stand `Dev` in the config
    assert proj.state(PK.ACCOUNTS_KEY, "")["state"] == "unknown"
    got = proj.state(PK.ACCOUNTS_KEY, "dev")
    assert got["state"] == "known" and got["row"] is None and got["source"] == "legacy_config"   # the row of `Dev` is not the row of `dev`
    assert PK.roster(proj.root, proj.cfg(), "")["elements"][0]["account"] is None            # no stand chosen: not shown, not "no"


def test_twin_roles_are_unknown_with_twins(proj):
    proj.stands[0]["credentials_by_role"] = {"Admin": "A_USER / A_PASS", "admin": "B_USER / B_PASS"}
    proj.write_config()
    got = proj.state(PK.ACCOUNTS_KEY, "dev", "ADMIN")
    assert got["state"] == "unknown" and sorted(got["twins"]) == ["Admin", "admin"]
    exact = proj.state(PK.ACCOUNTS_KEY, "dev", "admin")                                      # the exact key wins beside a twin
    assert exact["state"] == "known" and exact["twins"] == []


def test_malformed_note_is_unknown_with_flag(proj):
    proj.stands[0]["credentials_by_role"] = {"auditor": "ONLY_ONE_KEY"}
    proj.write_config()
    got = proj.state(PK.ACCOUNTS_KEY, "dev")
    assert got["state"] == "unknown" and got["malformed"] is True and got["twins"] == []
    proj.stands[0]["credentials_by_role"] = {"auditor": "NOT provisioned locally"}
    proj.write_config()
    assert proj.state(PK.ACCOUNTS_KEY, "dev")["malformed"] is True


def test_known_row_without_config_is_unknown(proj):
    proj.facts([account_fact("PK-1", "dev", "auditor", "2026-11-01T10:00:00+00:00")])
    assert proj.state(PK.ACCOUNTS_KEY, "dev")["state"] == "unknown"                          # the value carrier is gone: the row believes nothing
    proj.stands[0]["credentials_by_role"] = {"auditor": "ONLY_ONE_KEY"}                      # a note that names one key now
    proj.write_config()
    got = proj.state(PK.ACCOUNTS_KEY, "dev")
    assert got["state"] == "unknown" and got["malformed"] is True
    proj.stands[0]["credentials_by_role"] = {"Auditor": AUDITOR, "auditor": AUDITOR}         # twinned now
    proj.write_config()
    assert proj.state(PK.ACCOUNTS_KEY, "dev", "AUDITOR")["state"] == "unknown"


def test_noticed_is_never_known(proj):
    proj.record(state="noticed_unconfirmed", source="role", by="driver", words="", where="R-2: a visitor sees the catalogue")
    got = proj.state()
    assert got["state"] == "noticed_unconfirmed" and got["state"] != "known" and got["source"] == "role"
    roster = PK.roster(proj.root, proj.cfg(), "dev")
    assert [(e["role"], e["state"]) for e in roster["elements"]] == [("auditor", "noticed_unconfirmed")]
    assert proj.state(PK.ACCOUNTS_KEY, "dev")["state"] == "unknown"                          # noticing a role never makes an account
    assert proj.rows()[0]["provenance"]["where"] == "R-2: a visitor sees the catalogue"


def test_unknown_state_value_ignored(proj):
    proj.facts([role_fact("PK-1", "auditor", "maybe", "2026-11-01T10:00:00+00:00"),
                role_fact("PK-2", "guest", "unknown", "2026-11-01T10:00:00+00:00"),
                dict(role_fact("PK-3", "viewer", "known", "2026-11-01T10:00:00+00:00"), key="product.colours"),
                dict(role_fact("PK-4", "editor", "known", "2026-11-01T10:00:00+00:00"), scope="story")])
    for name in ("auditor", "guest", "viewer", "editor"):
        assert proj.state(element=name)["state"] == "unknown", name
    assert PK.roster(proj.root, proj.cfg(), "dev")["elements"] == []
    row, problem, _ = proj.record(state="maybe")
    assert row is None and "maybe" in problem


def test_asked_row_is_skipped(proj):
    proj.facts([role_fact("PK-1", "auditor", "asked", "2026-11-01T10:00:00+00:00")])         # reserved for phase 2: no producer
    assert proj.state()["state"] == "unknown"
    assert PK.roster(proj.root, proj.cfg(), "dev") == {"elements": [], "removed": [], "problem": ""}
    row, problem, _ = proj.record(state="asked")
    assert row is None and "asked" in problem
    proj.facts([role_fact("PK-1", "auditor", "not_needed", "2026-11-01T10:00:00+00:00"),
                role_fact("PK-2", "auditor", "asked", "2026-11-02T10:00:00+00:00")])
    assert proj.state()["state"] == "not_needed"                                             # an `asked` row never suppresses nor lifts


def test_unparseable_at_loses(proj):
    good = role_fact("PK-1", "auditor", "known", "2026-11-01T10:00:00+00:00")
    for bad_at in ("not a time", "", None, 7):
        bad = role_fact("PK-2", "auditor", "not_needed", bad_at)
        for rows in ([good, bad], [bad, good]):
            proj.facts(rows)
            assert proj.state()["state"] == "known", (bad_at, [r["id"] for r in rows])
    proj.facts([role_fact("PK-1", "auditor", "known", "bad"), role_fact("PK-2", "auditor", "not_needed", "worse")])
    assert proj.state()["state"] == "not_needed"                                             # both unparseable: the tie, the later row


def test_latest_row_wins(proj):
    proj.facts([role_fact("PK-2", "auditor", "not_needed", "2026-11-02T10:00:00+00:00"),
                role_fact("PK-1", "auditor", "known", "2026-11-01T10:00:00+00:00")])         # file order is not time order
    assert proj.state()["state"] == "not_needed"
    proj.facts([role_fact("PK-1", "auditor", "known", "2026-11-01T10:00:00+00:00"),
                role_fact("PK-2", "auditor", "not_needed", "2026-11-01T10:00:00+00:00")])    # a tie: the later row
    assert proj.state()["state"] == "not_needed"
    proj.facts([role_fact("PK-1", "Auditor", "known", "2026-11-03T10:00:00+00:00"),
                role_fact("PK-2", "auditor", "not_needed", "2026-11-02T10:00:00+00:00")])    # elements meet by the role form
    assert proj.state(element="AUDITOR")["state"] == "known"
    assert [e["role"] for e in PK.roster(proj.root, proj.cfg(), "dev")["elements"]] == ["Auditor"]


def test_same_state_again_not_created(proj):
    first, _, created = proj.record()
    again, problem, created_again = proj.record(element="AUDITOR", words="said again")
    assert (created, created_again, problem) == (True, False, "") and again == first and len(proj.rows()) == 1
    proj.record(state="not_needed", value=None)
    back, _, created_back = proj.record()                                                    # a changed answer is a NEW row
    assert created_back is True and back["id"] == "PK-3" and [r["state"] for r in proj.rows()] == ["known", "not_needed", "known"]


def test_changed_value_is_a_new_row(proj, capsys):
    proj.record(value={"sign_in": "account"})
    assert run(["role", "--task", "T-1", "--role", "auditor", "--state", "known", "--sign-in", "none", "--words-file", str(proj.words)]) == 0
    assert "recorded (PK-2)" in capsys.readouterr().out and len(proj.rows()) == 2
    assert proj.state()["row"]["value"] == {"sign_in": "none"}                               # the person's latest word, not "already recorded"
    assert proj.record(value={"sign_in": "none"})[2] is False                                # same state and value: still deduplicated


def test_revoke_cli_needs_a_task_and_works(proj, capsys):
    row, _, _ = proj.record()
    with pytest.raises(SystemExit):
        run(["revoke", "--id", row["id"], "--words-file", str(proj.words)])                  # --task is required
    capsys.readouterr()
    assert run(["revoke", "--task", "T-1", "--id", row["id"], "--words-file", str(proj.words)]) == 0
    assert proj.rows()[0]["revoked_at"] and proj.state()["state"] == "unknown"


def test_account_lock_that_cannot_be_made_has_its_own_sentence(proj, monkeypatch, capsys):
    broken = ES.LockBroken(proj.root / "x.lock", "open failed", "open")
    cause = TimeoutError(str(broken))
    cause.__cause__ = broken

    def refuse(root, **kwargs):
        raise cause

    monkeypatch.setattr(PD, "record_stand_account", refuse)
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 2
    err = capsys.readouterr().err
    assert "not another writer" in err and "writable file" in err and "run the same command again" not in err


def test_account_record_failure_after_config_names_the_move(proj, monkeypatch, capsys):
    monkeypatch.setattr(PK, "record", lambda *a, **k: (None, "the disk is full", False))
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 2
    err = capsys.readouterr().err
    assert proj.cfg()["environments"][0]["credentials_by_role"] == {"auditor": AUDITOR}      # the config was written first
    assert "the disk is full" in err and "run the same command again once that is fixed" in err


# --- writing ---------------------------------------------------------------------------------------------------------------

def test_no_trace_refused(tmp_path, monkeypatch):
    proj = Proj(tmp_path, monkeypatch, pipeline={"ticket": "T-1", "no_trace": True})
    row, problem, created = proj.record(task_root=proj.task)
    assert row is None and created is False and "an experiment leaves no trace" in problem and "waiver" in problem
    assert not proj.path().exists()
    assert PK._refuse_no_trace(None) == "" and PK._refuse_no_trace(proj.task) != ""
    before = proj.config.read_bytes()
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 2
    assert run(["role", "--task", "T-1", "--role", "auditor", "--state", "not_needed", "--words-file", str(proj.words)]) == 2
    assert proj.config.read_bytes() == before and not proj.path().exists()                    # nothing recorded anywhere
    proj.task.joinpath("pipeline.json").write_text(json.dumps({"ticket": "T-1"}), encoding="utf-8")
    row, _, _ = proj.record()                                                                # a carried row, then the story becomes an experiment
    proj.task.joinpath("pipeline.json").write_text(json.dumps({"ticket": "T-1", "no_trace": True}), encoding="utf-8")
    held = proj.path().read_bytes()
    assert run(["revoke", "--task", "T-1", "--id", row["id"], "--words-file", str(proj.words)]) == 2
    assert proj.path().read_bytes() == held                                                  # a revoke is a trace too (P8)
    proj.task.joinpath("pipeline.json").write_text(json.dumps({"ticket": "T-1", "no_trace": False}), encoding="utf-8")
    assert proj.record(task_root=proj.task, element="other")[2] is True                      # the way out: the story is no experiment


def test_lock_busy_refused(proj, monkeypatch, capsys):
    short_lock(monkeypatch)
    holder = hold(proj)
    try:
        with pytest.raises(TimeoutError) as raised:
            proj.record()
        assert "busy" in str(raised.value) and "run the same command again" in str(raised.value)
        assert not proj.path().exists()
        assert run(["role", "--task", "T-1", "--role", "auditor", "--state", "known", "--words-file", str(proj.words)]) == 2
        assert "busy" in capsys.readouterr().err and not proj.path().exists()
    finally:
        holder.release()
    assert proj.record()[2] is True                                                          # free again: the same command works


def test_record_loads_inside_the_lock(proj, monkeypatch):
    real_load, seen = PK.load, []

    def watched(root):
        try:
            ES.take_file_lock(Path(root) / Path(PK.LOCK_REL), 0.0).release()
            seen.append("free")
        except ES.LockBusy:
            seen.append("held")
        return real_load(root)

    monkeypatch.setattr(PK, "load", watched)
    proj.record()
    assert seen == ["held"], "record read the registry outside its lock"
    monkeypatch.setattr(PK, "load", real_load)
    roles = [f"role{i}" for i in range(6)]
    errors = []

    def one(role):
        try:
            assert proj.record(element=role)[2] is True
        except Exception as exc:        # noqa: BLE001 - a thread reports into the list
            errors.append(repr(exc))

    threads = [threading.Thread(target=one, args=(r,)) for r in roles]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    rows = proj.rows()
    assert sorted(r["element"] for r in rows) == sorted(["auditor", *roles])               # two racing writers keep both rows
    assert len({r["id"] for r in rows}) == len(rows)


def test_revoke_holds_the_lock(proj, monkeypatch):
    row, _, _ = proj.record()
    held = proj.path().read_bytes()
    short_lock(monkeypatch)
    holder = hold(proj)
    try:
        with pytest.raises(TimeoutError):
            PK.revoke(proj.root, row["id"], "ask again")
        assert proj.path().read_bytes() == held
    finally:
        holder.release()
    assert PK.revoke(proj.root, row["id"], "ask again")[1] == ""


# --- the account command ---------------------------------------------------------------------------------------------------

def test_account_cli_config_then_registry(proj, monkeypatch, capsys):
    calls = []
    real = PD.record_stand_account

    def spy(root, **kwargs):
        calls.append({"registry_before": proj.path().exists(), "config_before": proj.cfg()["environments"][0]["credentials_by_role"]})
        result = real(root, **kwargs)
        calls[-1].update(registry_after_writer=proj.path().exists(), config_after=proj.cfg()["environments"][0]["credentials_by_role"])
        return result

    monkeypatch.setattr(PD, "record_stand_account", spy)
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 0
    assert len(calls) == 1 and calls[0]["config_before"] == {} and calls[0]["registry_before"] is False
    assert calls[0]["config_after"] == {"auditor": AUDITOR} and calls[0]["registry_after_writer"] is False   # config first, registry second
    assert capsys.readouterr().out.startswith("auditor on dev: recorded (DD-1, PK-1)")
    assert proj.rows()[0]["key"] == PK.ACCOUNTS_KEY and proj.rows()[0]["value"] is None       # the value stays in config (FK-1)
    source = Path(PK.__file__).read_text(encoding="utf-8")
    assert "config.json\", \"w" not in source and "write_text" not in source and "credentials_by_role\"] =" not in source
    # a refusal of the config writer leaves the registry untouched
    assert run(["account", *STAND_ARGS[:-1], "QA_AUDITOR_EMAIL", "--words-file", str(proj.words)]) == 2     # the same name twice
    assert len(proj.rows()) == 2 and "refused" in capsys.readouterr().err


def test_account_cli_element_is_real_key(proj):
    proj.stands[0]["credentials_by_role"] = {"auditor": AUDITOR}
    proj.write_config()
    args = ["account", "--task", "T-1", "--role", "Auditor", "--user-key", "QA_AUDITOR_EMAIL", "--secret-key", "QA_AUDITOR_PASSWORD",
            "--words-file", str(proj.words)]
    assert run(args) == 0
    account = [r for r in proj.rows() if r["key"] == PK.ACCOUNTS_KEY]
    assert [r["element"] for r in account] == ["auditor"]                                    # the key the readers read, not the spelling given
    assert proj.state(PK.ACCOUNTS_KEY, "dev", "Auditor")["row"]["id"] == account[0]["id"]


def test_account_cli_unchanged_prints_already_recorded(proj, capsys):
    argv = ["account", *STAND_ARGS, "--words-file", str(proj.words)]
    assert run(argv) == 0
    capsys.readouterr()
    assert run(argv) == 0
    assert capsys.readouterr().out.strip() == "auditor on dev: already recorded (PK-1)"
    assert len(proj.rows()) == 2 and len(list((proj.root / "qa-factory" / "state" / "decision-transactions").glob("DD-*.json"))) == 1


def test_account_cli_no_stand_refused(tmp_path, monkeypatch, capsys):
    stands = [{"name": "dev", "base_url": "http://a", "credentials_by_role": {}}, {"name": "stage", "base_url": "http://b", "credentials_by_role": {}}]
    proj = Proj(tmp_path, monkeypatch, stands=stands, pipeline={"ticket": "T-1"})
    before = proj.config.read_bytes()
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 2
    err = capsys.readouterr().err
    assert "no chosen stand" in err and "`dev`" in err and "`stage`" in err
    assert proj.config.read_bytes() == before and not proj.path().exists()
    # no `environments[]` row at all: the account writer's own refusal is printed whole
    bare = Proj(tmp_path / "bare", monkeypatch, stands=[])
    assert run(["account", *STAND_ARGS, "--words-file", str(bare.words)]) == 2
    assert "environments[]" in capsys.readouterr().err and not bare.path().exists()


def test_account_cli_adds_roster_element(proj):
    assert PK.roster(proj.root, proj.cfg(), "dev")["elements"] == []
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 0
    assert proj.state()["state"] == "known"
    roster = PK.roster(proj.root, proj.cfg(), "dev")
    assert [(e["role"], e["state"], e["source"], e["sign_in"], e["account"]) for e in roster["elements"]] == \
        [("auditor", "known", "person", "account", True)]
    proj.facts([role_fact("PK-1", "auditor", "noticed_unconfirmed", "2026-11-01T10:00:00+00:00")])
    assert run(["account", *STAND_ARGS, "--words-file", str(proj.words)]) == 0
    assert proj.state()["state"] == "known"                                                  # an account confirms a noticed role


def test_role_cli_not_needed_removes_from_roster(proj, capsys):
    proj.record(element="superuser", state="known")
    assert [e["role"] for e in PK.roster(proj.root, proj.cfg(), "dev")["elements"]] == ["superuser"]
    assert run(["role", "--task", "T-1", "--role", "superuser", "--state", "not_needed", "--words-file", str(proj.words)]) == 0
    assert "superuser: not_needed recorded (PK-2)" in capsys.readouterr().out
    roster = PK.roster(proj.root, proj.cfg(), "dev")
    assert roster["elements"] == [] and [(r["role"], r["story"], r["id"]) for r in roster["removed"]] == [("superuser", "T-1", "PK-2")]
    assert proj.rows()[1]["value"] is None and proj.rows()[1]["provenance"]["words"] == WORDS
    assert run(["role", "--task", "T-1", "--role", "superuser", "--state", "known", "--words-file", str(proj.words)]) == 0     # taken back by a word
    assert PK.roster(proj.root, proj.cfg(), "dev")["removed"] == []


def test_not_needed_with_config_account_out_of_roster_account_known(proj):
    proj.stands[0]["credentials_by_role"] = {"superuser": "SU_USER / SU_PASS", "admin": "AD_USER / AD_PASS"}
    proj.write_config()
    proj.record(element="superuser", state="not_needed", value=None)
    roster = PK.roster(proj.root, proj.cfg(), "dev")
    assert [e["role"] for e in roster["elements"]] == ["admin"] and [r["role"] for r in roster["removed"]] == ["superuser"]
    assert proj.state(PK.ACCOUNTS_KEY, "dev", "superuser")["state"] == "known"               # config first: could the factory sign in
    assert proj.state(element="superuser")["state"] == "not_needed"                          # is it a product role
    assert proj.state(element="SuperUser")["state"] == "not_needed"
    assert proj.state(element="Super_User")["state"] == "unknown"                            # another form (a separator is a space, not nothing)
    assert proj.state(element="superusers")["state"] == "unknown"                            # merely resembling is not equal


def test_unsafe_role_name_refused(proj, capsys):
    for name in ("a,b", "a|b", "a\\b", "a\nb", "a\x00b", "", "   ", "default", "env:X", "created:y", "_ -",
                 "a b", "a b", "a\x85b", "a\x80b", "a\x9fb"):
        row, problem, created = proj.record(element=name)
        assert row is None and created is False and "nothing was recorded" in problem, repr(name)
    assert not proj.path().exists()
    assert run(["role", "--task", "T-1", "--role", "a,b", "--state", "known", "--words-file", str(proj.words)]) == 2
    assert "comma" in capsys.readouterr().err and not proj.path().exists()


def test_key_outside_keys_refused(proj):
    for key in ("product.colours", "", "environments.base_url", "PRODUCT.ROLES"):
        row, problem, _ = proj.record(key=key)
        assert row is None and "not a project-knowledge key" in problem and PK.ROLES_KEY in problem, key
    row, problem, _ = proj.record(key=PK.ACCOUNTS_KEY, environment="")                         # a fact of a stand with no stand
    assert row is None and "no stand is named" in problem
    row, problem, _ = proj.record(scope="story")                                             # a story answer is a waiver, not a row
    assert row is None and "waiver" in problem
    row, problem, _ = proj.record(key=PK.ACCOUNTS_KEY, environment="dev", scope="stand", state="not_needed")      # per-stand not_needed is not phase 0
    assert row is None and "`known` only" in problem
    assert not proj.path().exists()


def test_words_whole_and_door(proj, capsys):
    row, _, _ = proj.record(words=f"  {WORDS}  ")
    assert row["provenance"]["words"] == WORDS                                               # whole: line break, dash, Cyrillic - nothing cut
    assert proj.rows()[0]["provenance"]["words"] == WORDS
    empty, problem, _ = proj.record(element="x", words="  \n ")
    assert empty is None and "--words-file" in problem
    assert proj.record(element="x", words="", source="role", by="driver")[2] is True        # a role's inference carries no person's words
    assert run(["role", "--task", "T-1", "--role", "y", "--state", "known"]) == 2
    assert "--words-file" in capsys.readouterr().err and len(proj.rows()) == 2
    proj.words.write_text("   \n", encoding="utf-8")
    assert run(["role", "--task", "T-1", "--role", "y", "--state", "known", "--words-file", str(proj.words)]) == 2
    assert "--words-file" in capsys.readouterr().err and len(proj.rows()) == 2
    assert run(["show", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["facts"][0]["provenance"]["words"] == WORDS


# --- the roster ------------------------------------------------------------------------------------------------------------

def test_roster_legacy_accounts_dedup_by_form(tmp_path, monkeypatch):
    stands = [{"name": "dev", "base_url": "http://a", "credentials_by_role": {"Admin": "A_USER / A_PASS", "reader": "R_USER / R_PASS"}},
              {"name": "stage", "base_url": "http://b", "credentials_by_role": {"admin": "B_USER / B_PASS"}}]
    proj = Proj(tmp_path, monkeypatch, stands=stands)
    first = PK.roster(proj.root, proj.cfg(), "dev")
    assert [(e["role"], e["source"]) for e in first["elements"]] == [("Admin", "legacy_config"), ("reader", "legacy_config")]
    assert {e["role"]: e["account"] for e in first["elements"]} == {"Admin": True, "reader": True}
    assert {e["role"]: e["account"] for e in PK.roster(proj.root, proj.cfg(), "stage")["elements"]} == {"Admin": True, "reader": False}
    proj.record(element="ADMIN", words="the person confirmed admin")
    again = PK.roster(proj.root, proj.cfg(), "dev")
    assert [(e["role"], e["source"], e["story"]) for e in again["elements"]] == [("ADMIN", "person", "T-1"), ("reader", "legacy_config", "")]
    assert again["elements"][0]["account"] is True                                           # the account is read by the role form too


def test_reserved_roles_never_in_roster(tmp_path, monkeypatch):
    stands = [{"name": "dev", "base_url": "http://a", "credentials_by_role": {
        "default": "D_USER / D_PASS", "env:X_USER/X_PASS": "-", "created:walker": "-", "auditor": AUDITOR, "": "E_USER / E_PASS"}}]
    proj = Proj(tmp_path, monkeypatch, stands=stands)
    assert [e["role"] for e in PK.roster(proj.root, proj.cfg(), "dev")["elements"]] == ["auditor"]
    proj.facts([role_fact("PK-1", "default", "known", "2026-11-01T10:00:00+00:00")])         # a hand-written row of a reserved form
    assert [e["role"] for e in PK.roster(proj.root, proj.cfg(), "dev")["elements"]] == ["auditor"]
    assert proj.record(element="default")[0] is None


# --- the S3 form -----------------------------------------------------------------------------------------------------------

def strategist_form(proj: Proj, body: str, *, accepted=True) -> None:
    (proj.task / "state").mkdir(parents=True, exist_ok=True)
    (proj.task / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
    dispatches = {"d1": {"id": "d1", "stage": "S3", "role": "qa-test-strategist", "status": "accepted" if accepted else "running"}}
    (proj.task / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
    (proj.task / "work" / "handoffs" / "d1.yaml").write_text(body, encoding="utf-8")


def test_story_roles_absent_empty_and_rows(proj):
    assert PK.story_roles(proj.task) == ([], "")                                             # no form at all
    strategist_form(proj, "scope:\n  - id: R-1\nblocked: none\n", accepted=False)
    assert PK.story_roles(proj.task) == ([], "")                                             # a form not accepted yet is no form
    strategist_form(proj, "scope:\n  - id: R-1\nblocked: none\n")
    assert PK.story_roles(proj.task) == ([], "")                                             # an old form: no section
    strategist_form(proj, "scope:\n  - id: R-1\nproduct_roles: []\nblocked: none\n")
    assert PK.story_roles(proj.task) == ([], "")                                             # an empty list
    strategist_form(proj, "product_roles:\n  - role: auditor\n    sign_in: account\n    where: R-2: a read-only user\n"
                          "  - role: guest\n    sign_in: none\n    where: R-3\nblocked: none\n")
    roles, reason = PK.story_roles(proj.task)
    assert reason == "" and roles == [{"role": "auditor", "sign_in": "account", "where": "R-2: a read-only user"},
                                      {"role": "guest", "sign_in": "none", "where": "R-3"}]
    (proj.task / "work" / "handoffs" / "d1.yaml").unlink()
    roles, reason = PK.story_roles(proj.task)
    assert roles == [] and "cannot be read" in reason                                        # an unreadable form says so
    before = proj.task.joinpath("state", "controller.json").read_bytes()
    assert PK.story_roles(proj.task / "nowhere") == ([], "")
    assert proj.task.joinpath("state", "controller.json").read_bytes() == before and not proj.path().exists()


def test_story_roles_skips_placeholder_row(proj):
    template = ("product_roles:\n  - role: <optional: the role's name as the requirements say it>\n    sign_in: <optional: account or none>\n"
                "    where: <optional: the requirement id and the words that name the role>\nblocked: none\n")
    strategist_form(proj, template)
    assert PK.story_roles(proj.task) == ([], "")                                             # the template's own row is never a role
    strategist_form(proj, "product_roles:\n  - role: <fill>\n    sign_in: account\n    where: R-1\n  - role: \"\"\n  - role: reader\nblocked: none\n")
    assert PK.story_roles(proj.task) == ([{"role": "reader", "sign_in": "account", "where": ""}], "")
    strategist_form(proj, "product_roles:\n  - role: auditor\n    sign_in: <optional: account or none>\n    where: <optional: the id>\nblocked: none\n")
    assert PK.story_roles(proj.task) == ([{"role": "auditor", "sign_in": "account", "where": ""}], "")      # a placeholder sign_in reads as account
    strategist_form(proj, "product_roles:\n  - role: auditor\n    sign_in: sometimes\nblocked: none\n")
    assert PK.story_roles(proj.task)[0][0]["sign_in"] == "account"                           # an unknown sign_in: toward asking


def test_acting_line_names_the_answers():
    row = account_fact("PK-3", "dev", "auditor", "2026-11-12T09:40:00+00:00")
    row["provenance"]["story"] = "LOCAL-7"
    assert PK.acting_line([row]) == ('Acting on your earlier answers: the account of "auditor" on "dev" (given in LOCAL-7 on 2026-11-12). '
                                     'To change it, say so.')
    assert PK.acting_line([]) == "" and PK.acting_line(None) == "" and PK.acting_line(["junk"]) == ""
    assert PK.acting_line([row, row]).count("the account of") == 2


# --- t-2181 PC-1b: the three side keys ---------------------------------------------------------------------------------------

def side_args(*more):
    return ["side", "--task", "T-1", *more]


def test_side_cli_writes_known_rows_for_each_key(proj, capsys):
    words = str(proj.words)
    assert run(side_args("--name", "ui", "--stand", "dev", "--reality", "substituted", "--words-file", words)) == 0
    assert run(side_args("--name", "ui", "--deliverable", "no", "--words-file", words)) == 0
    assert run(side_args("--name", "ui", "--stand", "old", "--reference", "--words-file", words)) == 0
    rows = {row["key"]: row for row in proj.rows()}
    assert set(rows) == {PK.STAND_SIDES_KEY, PK.SIDES_KEY, PK.REFERENCE_KEY}
    assert all(row["state"] == "known" and row["element"] == "ui" for row in rows.values())
    assert rows[PK.STAND_SIDES_KEY]["value"] == {"reality": "substituted"} and rows[PK.STAND_SIDES_KEY]["environment"] == "dev"
    assert rows[PK.SIDES_KEY]["value"] == {"deliverable": False, "settles_by": ""} and rows[PK.SIDES_KEY]["environment"] == ""
    assert rows[PK.REFERENCE_KEY]["value"] == {"reference": True} and rows[PK.REFERENCE_KEY]["environment"] == "old"
    assert rows[PK.SIDES_KEY]["provenance"]["words"] == WORDS.strip() and rows[PK.SIDES_KEY]["provenance"]["by"] == "conductor"
    settles = proj.words.parent / "settles.txt"
    settles.write_text("platform team\n", encoding="utf-8")
    assert run(side_args("--name", "api", "--deliverable", "yes", "--settles-by-file", str(settles), "--words-file", words)) == 0
    assert [r for r in proj.rows() if r["element"] == "api"][0]["value"] == {"deliverable": True, "settles_by": "platform team"}


def test_a_later_word_overwrites_whose_side_it_is_and_the_history_stays(proj, capsys):
    """t-2277 batch 2b W2 (2): the person's later word about `--deliverable` is the project's value from then on - the earlier row stays
    (it is history, with its words and time), the latest one is read, and a third word flips it back only by being a third row."""
    words = str(proj.words)
    assert run(side_args("--name", "backend", "--deliverable", "yes", "--words-file", words)) == 0
    assert PK.state(proj.root, PK.SIDES_KEY, "", "backend")["row"]["value"]["deliverable"] is True
    assert run(side_args("--name", "backend", "--deliverable", "no", "--words-file", words)) == 0
    latest = PK.state(proj.root, PK.SIDES_KEY, "", "backend")["row"]
    assert latest["value"] == {"deliverable": False, "settles_by": ""}                       # the later word overwrites
    assert latest["provenance"]["source"] == "person" and latest["provenance"]["by"] == "conductor" and latest["provenance"]["words"] == WORDS.strip()
    assert latest["provenance"]["story"] == "T-1" and latest["at"]                            # who and when are recorded with the value
    assert len([r for r in proj.rows() if r["element"] == "backend"]) == 2                    # the earlier row is not rewritten
    assert run(side_args("--name", "backend", "--deliverable", "no", "--words-file", words)) == 0
    assert len([r for r in proj.rows() if r["element"] == "backend"]) == 2                    # the same word again is the existing row
    assert run(side_args("--name", "backend", "--deliverable", "yes", "--words-file", words)) == 0
    assert PK.state(proj.root, PK.SIDES_KEY, "", "backend")["row"]["value"]["deliverable"] is True
    assert len([r for r in proj.rows() if r["element"] == "backend"]) == 3                    # flipping back is a row of its own, never silent


def test_side_deliverable_beside_stand_says_it_is_project_wide(proj, capsys):
    """t-2277 batch 2b (critic t-2475 N3): `--stand` beside `--deliverable` is dropped, and the output says so; no `--stand`, no note."""
    words = str(proj.words)
    assert run(side_args("--name", "ui", "--deliverable", "no", "--stand", "dev", "--words-file", words)) == 0
    out = capsys.readouterr().out
    assert "--stand dev was not used" in out and "whole project" in out, out
    assert [r for r in proj.rows() if r["element"] == "ui"][0]["environment"] == ""         # the row is the project's, as before
    assert run(side_args("--name", "api", "--deliverable", "no", "--words-file", words)) == 0
    assert "was not used" not in capsys.readouterr().out
    assert run(side_args("--name", "ui", "--stand", "dev", "--reality", "substituted", "--words-file", words)) == 0
    assert "was not used" not in capsys.readouterr().out                                      # a stand beside `--reality` is used


def test_record_refuses_a_bad_side_value(proj):
    base = dict(environment="dev", element="ui", scope="stand", key=PK.STAND_SIDES_KEY)
    for value in ({"reality": "mocked"}, {"reality": "real", "x": 1}, {}, None, "real"):
        row, problem, _ = proj.record(value=value, **base)
        assert row is None and "references/side-realities.json" not in problem and "reality" in problem, value
    row, problem, _ = proj.record(key=PK.SIDES_KEY, environment="", element="ui", scope="project", value={"settles_by": "x"})
    assert row is None and "deliverable" in problem
    row, problem, _ = proj.record(key=PK.SIDES_KEY, environment="", element="ui", scope="project", value={"deliverable": "yes"})
    assert row is None and "deliverable" in problem
    row, problem, _ = proj.record(key=PK.REFERENCE_KEY, environment="old", element="ui", scope="stand", value={"reference": False})
    assert row is None and "reference" in problem
    row, problem, _ = proj.record(key=PK.SIDES_KEY, environment="", element="ui", scope="project", state="not_needed",
                                  value={"deliverable": True})
    assert row is None and "`known` only" in problem
    row, problem, _ = proj.record(key=PK.SIDES_KEY, environment="", element=" ui", scope="project", value={"deliverable": True})
    assert row is None and "compared exactly" in problem
    for name in ("web.app", "a=b"):     # a key of the story's record (`sides.<name>.<attribute>=<value>`): refused, with the door
        row, problem, _ = proj.record(key=PK.SIDES_KEY, environment="", element=name, scope="project", value={"deliverable": True})
        assert row is None and "without them" in problem and "nothing was recorded" in problem, name
    assert not proj.path().exists()                                                           # nothing was written by any refusal


def test_ui_and_ui_are_two_subjects(proj):
    for name in ("UI", "ui"):
        assert proj.record(key=PK.SIDES_KEY, environment="", element=name, scope="project", value={"deliverable": True})[2] is True
    assert PK.subjects(proj.root, PK.SIDES_KEY) == {"subjects": [("", "UI"), ("", "ui")], "problem": ""}
    assert PK.state(proj.root, PK.SIDES_KEY, "", "UI")["row"]["id"] != PK.state(proj.root, PK.SIDES_KEY, "", "ui")["row"]["id"]
    assert PK.state(proj.root, PK.SIDES_KEY, "", "Ui")["state"] == "unknown"


def test_subjects_skips_revoked_latest_wins_unparseable_at_loses(proj):
    def side_fact(id, env, element, at, **extra):
        return fact(id, PK.STAND_SIDES_KEY, env, element, "known", at, **dict({"scope": "stand", "value": {"reality": "real"}}, **extra))
    proj.facts([side_fact("PK-1", "dev", "ui", "2026-11-01T10:00:00+00:00"),
                side_fact("PK-2", "dev", "ui", "2026-11-02T10:00:00+00:00", value={"reality": "substituted"}),
                side_fact("PK-3", "dev", "ui", "garbage", value={"reality": "absent"}),
                side_fact("PK-4", "dev", "gone", "2026-11-01T10:00:00+00:00", revoked_at="2026-11-03T10:00:00+00:00"),
                side_fact("PK-5", "Dev", "api", "2026-11-01T10:00:00+00:00"),
                fact("PK-6", PK.STAND_SIDES_KEY, "dev", "odd", "asked", "2026-11-01T10:00:00+00:00", scope="stand")])
    assert PK.subjects(proj.root, PK.STAND_SIDES_KEY)["subjects"] == [("Dev", "api"), ("dev", "ui")]       # revoked and `asked` skipped
    assert PK.subjects(proj.root, PK.STAND_SIDES_KEY, "dev")["subjects"] == [("dev", "ui")]               # the stand is exact
    assert PK.state(proj.root, PK.STAND_SIDES_KEY, "dev", "ui")["row"]["id"] == "PK-2"                    # latest wins; the bad `at` loses
    assert PK.subjects(proj.root, PK.REFERENCE_KEY) == {"subjects": [], "problem": ""}


def test_subjects_never_raises_and_says_the_problem(proj):
    proj.path().parent.mkdir(parents=True, exist_ok=True)
    proj.path().write_text("{not json", encoding="utf-8")
    got = PK.subjects(proj.root, PK.SIDES_KEY)
    assert got["subjects"] == [] and got["problem"]
    assert PK.subjects(proj.root / "nowhere", PK.SIDES_KEY) == {"subjects": [], "problem": ""}


def test_side_refused_on_a_no_trace_story_with_the_door(tmp_path, monkeypatch, capsys):
    proj = Proj(tmp_path, monkeypatch, pipeline={"ticket": "T-1", "no_trace": True})
    assert run(side_args("--name", "ui", "--stand", "dev", "--reality", "real", "--words-file", str(proj.words))) == 2
    assert "an experiment leaves no trace" in capsys.readouterr().err and not proj.path().exists()


def test_side_cli_needs_one_mode_and_a_stand(proj, capsys):
    with pytest.raises(SystemExit):
        run(side_args("--name", "ui", "--words-file", str(proj.words)))
    capsys.readouterr()
    assert run(side_args("--name", "ui", "--stand", "dev", "--reality", "mocked", "--words-file", str(proj.words))) == 2
    assert "reality" in capsys.readouterr().err and not proj.path().exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
