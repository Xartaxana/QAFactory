"""PK0-5: the stand's default login is asked on need - ONE rule, `gate_preflight.default_login_needed`, read by gate A
(`Rehearsal.check_s5_credentials`) and by S6 (`Driver.stand_login_problem`). The story is a real project folder (config, plan,
case files, the registry of project knowledge); only the browser-side `manual_capture` of the S6 tests is a fake.
"""
import json
import shutil
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_preflight as GP  # noqa: E402
import manual_capture as REAL_CAPTURE  # noqa: E402
import manual_evidence as ME  # noqa: E402  (imported before the fake `manual_capture` goes in)
import project_knowledge as PK  # noqa: E402
import story_run  # noqa: E402

ADMIN = {"id": "PC-1", "kind": "account", "what": "an admin signs in", "partitions": [], "check": {"stand_account": "admin"}}


def account(role):
    return dict(ADMIN, check={"stand_account": role})


def story(tmp_path, cases, *, rows=None, stands=("dev",), pipeline=None, roles=None, env=None):
    """A project and a story. `cases`: [(case id, plan disposition, preconditions)]; a preconditions value that is a str is written
    as the raw line. Returns (task_root, cfg)."""
    cfg = {"environments": [{"name": n, "credentials_by_role": {"admin": "ADMIN_USER / ADMIN_PASS"} if roles is None else roles}
                            for n in stands], "environment": env or {"env_file": "login.env"}}
    (tmp_path / "qa-factory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    task = tmp_path / "qa-factory" / "artifacts" / "QA-1"
    shutil.rmtree(task, ignore_errors=True)         # one story per call, the project (and its registry) stays
    (task / "work" / "test-cases").mkdir(parents=True)
    if pipeline:
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    plan = [{"id": f"TS-{n}", "disposition": d} for n, (_, d, _) in enumerate(cases, 1)] if rows is None else rows
    (task / "work" / "test-plan.json").write_text(json.dumps(plan) if not isinstance(plan, str) else plan, encoding="utf-8")
    for n, (cid, _, pre) in enumerate(cases, 1):
        line = "" if pre is None else "preconditions: " + (pre if isinstance(pre, str) else json.dumps(pre)) + "\n"
        (task / "work" / "test-cases" / f"{cid}.md").write_text(
            f"---\nid: {cid}\ntask: QA-1\n{line}---\n# {cid}\nPlan row: TS-{n}\n", encoding="utf-8")
    return task, cfg


def needed(task, cfg):
    return GP.default_login_needed(task, cfg)


def say(tmp_path, role, state, story_id="QA-0"):
    row, problem, _ = PK.record(tmp_path, key=PK.ROLES_KEY, environment="", element=role, state=state, scope="project", value={},
                                words="the person's words", source="person", story=story_id, by="conductor")
    assert row, problem
    return row


def test_default_declared_needs_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("default")])])
    assert needed(task, cfg) is True


def test_automate_row_needs_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "automate", [account("admin")])])
    assert needed(task, cfg) is True


def test_manual_case_without_account_needs_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", None)])
    assert needed(task, cfg) is True


def test_seeded_case_needs_login(tmp_path):
    seeds = {"id": "PC-2", "kind": "data", "what": "the case creates its data", "partitions": [], "check": {"case_seeds": "a project"}}
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin"), seeds])])
    assert needed(task, cfg) is True


def test_unprovisioned_role_needs_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("ghost")])])
    assert needed(task, cfg) is True


def test_no_chosen_stand_needs_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])], stands=("dev", "stage"))
    assert needed(task, cfg) is True
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])], stands=("dev", "stage"), pipeline={"environment": "stage"})
    assert needed(task, cfg) is False


def test_all_cases_named_known_roles_no_default_ask(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")]), ("TC-002", "manual-agent", [account(" Admin ")])])
    assert needed(task, cfg) is False


def test_only_manual_human_rows_no_ask(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-human", None), ("TC-002", "skip", None), ("TC-003", "unverifiable", None)])
    assert needed(task, cfg) is False
    task, cfg = story(tmp_path, [])
    assert needed(task, cfg) is False


@pytest.mark.parametrize("plan", ["{not json", "7", ""])
def test_unreadable_plan_needs_login(tmp_path, plan):
    task, cfg = story(tmp_path, [("TC-001", "manual-human", None)], rows=plan)
    assert needed(task, cfg) is True
    (task / "work" / "test-plan.json").unlink()
    assert needed(task, cfg) is True


@pytest.mark.parametrize("pre", ["{not json", '[{"id": "PC-1"}]', '"text"'])
def test_unreadable_case_needs_login(tmp_path, pre):
    task, cfg = story(tmp_path, [("TC-001", "manual-human", pre)])
    assert needed(task, cfg) is True


def test_unknown_disposition_needs_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-human", None)], rows=[{"id": "TS-1", "disposition": "maybe"}])
    assert needed(task, cfg) is True
    task, cfg = story(tmp_path, [("TC-001", "manual-human", None)], rows=[{"id": "TS-9", "disposition": "manual-human"}])
    assert needed(task, cfg) is True      # the case's plan row is not in the plan


def test_exception_means_needed(tmp_path, monkeypatch):
    assert needed(None, {}) is True
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])])
    assert needed(task, cfg) is False

    def broken(*args, **kwargs):
        raise RuntimeError("the registry reader broke")
    monkeypatch.setattr(PK, "state", broken)
    assert needed(task, cfg) is True


def test_not_needed_role_does_not_need_default_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("superuser")])])
    assert needed(task, cfg) is True
    say(tmp_path, "superuser", PK.NOT_NEEDED)
    assert needed(task, cfg) is False
    assert needed(story(tmp_path, [("TC-001", "manual-agent", [account(" SuperUser ")])])[0], cfg) is False    # equal under the role form
    assert needed(story(tmp_path, [("TC-001", "manual-agent", [account("Super-User")])])[0], cfg) is True      # only resembles it


def test_carded_role_still_needs_default_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("auditor")])])
    say(tmp_path, "auditor", PK.NOTICED)
    assert needed(task, cfg) is True


def test_unreadable_registry_role_needs_default_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("superuser")])])
    say(tmp_path, "superuser", PK.NOT_NEEDED)
    assert needed(task, cfg) is False
    PK.record_path(tmp_path).write_text("{broken", encoding="utf-8")
    assert needed(task, cfg) is True


def test_revoked_not_needed_needs_default_login(tmp_path):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("superuser")])])
    row = say(tmp_path, "superuser", PK.NOT_NEEDED)
    assert needed(task, cfg) is False
    PK.revoke(tmp_path, row["id"], "ask again")
    assert needed(task, cfg) is True
    say(tmp_path, "superuser", PK.NOT_NEEDED)
    say(tmp_path, "superuser", PK.KNOWN)       # a later `known` row of the role supersedes it; its account is still not known
    assert needed(task, cfg) is True


@pytest.mark.parametrize("state, sign_in, broken, asks", [(PK.KNOWN, "none", False, False), (PK.NOTICED, "none", False, True),
                                                          (PK.KNOWN, "account", False, True), (PK.KNOWN, "none", True, True)],
                         ids=["known-guest", "noticed-guest", "known-visitor-account", "known-guest-broken-registry"])
def test_guest_role_does_not_need_default_login(tmp_path, state, sign_in, broken, asks):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("visitor")])])
    row, problem, _ = PK.record(tmp_path, key=PK.ROLES_KEY, environment="", element="visitor", state=state, scope="project",
                                value={"sign_in": sign_in}, words="the person's words", source="person", story="QA-0", by="conductor")
    assert row, problem
    if broken:
        PK.record_path(tmp_path).write_text("{broken", encoding="utf-8")
    assert needed(task, cfg) is asks


def test_gate_a_note_when_not_asked(tmp_path):
    for cases, asks in ((("manual-agent", [account("admin")]), False), (("automate", [account("admin")]), True)):
        task, cfg = story(tmp_path, [("TC-001", *cases)])
        rehearsal = GP.Rehearsal(task, "A")
        rehearsal.check_s5_credentials()
        notes = [i["message"] for i in rehearsal.info if "default account is not asked" in i["message"]]
        keys = [f["message"] for f in rehearsal.findings if "keys not set" in f["message"] or "is not on disk" in f["message"]]
        assert bool(keys) is asks and bool(notes) is not asks, (rehearsal.info, rehearsal.findings)


# --- S6: `Driver.stand_login_problem` ------------------------------------------------------------------------------------------

class FakeCapture(types.ModuleType):
    """`manual_capture` as `stand_login_problem` uses it: the reads are recorded as (actor, stand name), and `refuse` names the actor
    whose read raises."""

    class LoginMaterialMissing(ValueError):
        part = "key"

    def __init__(self, cfg, root, refuse=None):
        super().__init__("manual_capture")
        self.cfg, self.root, self.reads, self.refuse = cfg, root, [], refuse

    def __getattr__(self, name):        # whatever else `manual_evidence` asks of the module (`case_root`) is the real one's
        return getattr(REAL_CAPTURE, name)

    def load_config(self, task_root):
        return self.cfg, self.root

    def login_declared_none(self, cfg, kind):
        return False

    def read_login(self, cfg, root, actor=None, stand=None, task_root=None):
        self.reads.append((actor, (stand or {}).get("name")))
        if actor and actor == self.refuse:
            raise ValueError(f"the keys of {actor} are not set")
        return ("user", "secret")


def driver_over(tmp_path, monkeypatch, task, cfg, refuse=None):
    capture = FakeCapture(cfg, tmp_path, refuse)
    monkeypatch.setitem(sys.modules, "manual_capture", capture)
    driver = object.__new__(story_run.Driver)
    driver.task_root = task
    return driver, capture


def request(task, case, check):
    target = ME.request_path(task, case)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"actors": [{"id": "PC-1", "what": "w", "check": check}]}), encoding="utf-8")


@pytest.mark.parametrize("disposition", ["automate", "manual-agent"])
def test_s6_uses_the_same_rule(tmp_path, monkeypatch, disposition):
    task, cfg = story(tmp_path, [("TC-001", disposition, [account("admin")])])
    request(task, "TC-001", {"stand_account": "admin"})
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg)
    assert driver.stand_login_problem(["TC-001"]) == ("", "")
    default_read = (None, None) in capture.reads
    assert default_read is needed(task, cfg) is (disposition == "automate")


def test_s6_keeps_default_for_unreadable_request(tmp_path, monkeypatch):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])])
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg)
    assert needed(task, cfg) is False
    assert driver.stand_login_problem(["TC-001"]) == ("", "")       # no prepared request: its capture signs in as default
    assert capture.reads == [(None, None)]
    ME.request_path(task, "TC-001").parent.mkdir(parents=True, exist_ok=True)
    ME.request_path(task, "TC-001").write_text("{broken", encoding="utf-8")
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg)
    driver.stand_login_problem(["TC-001"])
    assert capture.reads == [(None, None)]                           # read once, not once more per case


def test_role_accounts_still_read_in_s6(tmp_path, monkeypatch):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])])
    request(task, "TC-001", {"stand_account": "admin"})
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg, refuse="admin")
    kind, details = driver.stand_login_problem(["TC-001"])
    assert (kind, "TC-001" in details, "admin" in details) == ("missing_key", True, True)
    assert capture.reads == [("admin", "dev")]


def test_s6_reads_role_on_chosen_stand_only(tmp_path, monkeypatch):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])], stands=("dev", "stage"), pipeline={"environment": "stage"})
    request(task, "TC-001", {"stand_account": "admin"})
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg)
    assert driver.stand_login_problem(["TC-001"]) == ("", "")
    assert capture.reads == [("admin", "stage")]


def test_s6_no_chosen_stand_refuses_role_read(tmp_path, monkeypatch):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account("admin")])], stands=("dev", "stage"))
    request(task, "TC-001", {"stand_account": "admin"})
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg)
    kind, details = driver.stand_login_problem(["TC-001"])
    assert kind == "missing_key" and "no chosen stand" in details and "admin" in details and "PC-1" in details
    assert capture.reads == [(None, None)] and needed(task, cfg) is True


@pytest.mark.parametrize("value", ["env:U/S", "created:x"])
def test_s6_reserved_role_needs_no_chosen_stand(tmp_path, monkeypatch, value):
    task, cfg = story(tmp_path, [("TC-001", "manual-agent", [account(value)])], stands=("dev", "stage"))
    request(task, "TC-001", {"stand_account": value})
    driver, capture = driver_over(tmp_path, monkeypatch, task, cfg)
    assert driver.stand_login_problem(["TC-001"]) == ("", "")        # not refused for a missing stand
    assert (value, None) in capture.reads


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
