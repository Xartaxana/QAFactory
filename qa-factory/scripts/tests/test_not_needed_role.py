"""PK0-9 (t-2142 §3 (2b), N4): "not a role of this product" is not asked again - at gate A (no account card, one covered row) and at gate B
(its cases are not carded again) - through the ONE "decided once" road (`covered_gaps`, B-414), with a `record` dispatch on its readers.

The story is a real project folder (config, case files, the registry of project knowledge, a pipeline with the overrides the driver writes); the
rehearsal is the real `gate_preflight.Rehearsal`; the gate B view is the real `stand_gaps` readers. Only the driver's `py` (the command runner)
and `words_file` are fakes. Fast: no role runs, no stand. The neighbours (`test_stand_gap_carry.py`, `test_gate_preflight.py`,
`test_gate_brief_and_retro.py`) are judged by CI.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_brief as GB  # noqa: E402
import gate_preflight as GP  # noqa: E402
import project_knowledge as PK  # noqa: E402
import stand_gaps as SG  # noqa: E402

ANSWER = "2026-10-05T11:00:00+00:00"
SHA40, SHA64 = "a" * 40, "b" * 64
GAP = "RA-dev-superuser"


def pc(n, role):
    return {"id": f"PC-{n}", "kind": "account", "what": f"the account of {role}", "partitions": [], "check": {"stand_account": role},
            "remedy": {"kind": "credential", "where": "the env file", "change": "two variables"}}


def story(tmp_path, cases, *, task_id="QA-1", pipeline=None):
    """A project and a story. `cases`: [(case id, [roles])]. Returns the story root."""
    cfg = {"environments": [{"name": "dev", "credentials_by_role": {}}], "environment": {"env_file": "login.env"}}
    (tmp_path / "qa-factory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "login.env").write_text("", encoding="utf-8")
    task = tmp_path / "qa-factory" / "artifacts" / task_id
    shutil.rmtree(task, ignore_errors=True)
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(pipeline or {}), encoding="utf-8")
    for cid, roles in cases:
        raw = json.dumps([pc(i, r) for i, r in enumerate(roles, 1)])
        (task / "work" / "test-cases" / f"{cid}.md").write_text(
            f"---\nid: {cid}\ntask: {task_id}\ntitle: {cid} purges the cache\npreconditions: {raw}\n---\n# {cid}\n", encoding="utf-8")
    return task


def go(task):
    r = GP.Rehearsal(task, "A")
    r.check_role_accounts()
    r.check_case_preconditions()
    return r


def say(root, element, state, story_id="LOCAL-8", words="superuser is not a role here, it is a technical account"):
    row, problem, _ = PK.record(root, key="product.roles", environment="", element=element, state=state, scope="project", value={},
                                words=words, source="person", story=story_id, by="conductor")
    assert row, problem
    return row


def cards(r):
    return [g for g in r.stand_gaps if g.get("scope") == "role"]


def pk_prop(row, gap=GAP):
    return {"id": row["id"], "record": "project_knowledge", "subject": "product.roles||superuser", "gap": gap}


def put(task, match, by, props, at=ANSWER, **extra):
    """One stage override, as the driver's carry leaves it (`waiver.py --by`, then the typed `property` annotated onto it)."""
    path = task / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    entry = dict({"stage": "S5", "match": f"stand gap: {match}", "decision": "accept - the person wrote: not a role", "at": at}, **extra)
    if by:
        entry["by"] = by
    if props is not None:
        entry["property"] = props
    pipeline.setdefault("stage_overrides", []).append(entry)
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def carried(task, row, *, by=SG.PK_BY, props="default", gap_too=True, case="TC-9"):
    """What gate A leaves for the covered not-a-role gap: the gap's own override and the case carry, both `by` the registry."""
    props = [pk_prop(row)] if props == "default" else props
    if gap_too:
        put(task, GAP, by, props)
    put(task, case, by, props, declared=SG.declared_ids(task, case, None, SG._integration_ids(task, case)))   # the precondition ids of the case now (C5)


def confirm(task, at, revision=SHA40, sha=SHA64, kind="deployed"):
    row = {"schema_version": 1, "at": at, "task": task.name, "environment_id": "dev", "profile_id": "api", "kind": kind,
           "words": "the person confirmed", "recorded_by": "test"}
    if kind != "withdrawn":
        row.update(revision=revision, image="absent", stand_definition_sha=sha)
    path = task / "state" / "stand-confirmations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def gate_b(task, **gap):
    """`(asked, covered, answers)` of gate B for the one case TC-9."""
    gaps = [dict({"id": "TC-9", "case_id": "TC-9"}, **gap)]
    asked, covered = SG.gate_b_split(task, gaps)
    return asked, covered, SG.gate_b_answers(task, gaps)[0]


def change_of(task):
    return gate_b(task)[2].get("TC-9", {}).get("change", "<no answer>")


class Fake:
    """The driver's `py` and `words_file`: every command is recorded, none is run."""
    def __init__(self, tmp_path, code=0):
        self.calls, self.said, self.code, self.tmp = [], [], code, tmp_path

    def py(self, script, *args):
        self.calls.append((script,) + tuple(args))
        return self.code, "refused: nothing was changed"

    def words_file(self, text, name):
        return self.tmp / f"{name}.txt"


def covered_gap(tmp_path, cases=(("TC-9", ["superuser"]),)):
    """(task, the covered gap a later story's rehearsal writes, the registry row)."""
    task = story(tmp_path, list(cases))
    row = say(tmp_path, "superuser", "not_needed")
    r = go(task)
    assert len(r.covered_gaps) == 1, r.covered_gaps
    return task, r.covered_gaps[0], row


# --- gate A -----------------------------------------------------------------------------------------------------------------

def test_not_needed_role_is_not_asked_for_an_account_again(tmp_path):
    task = story(tmp_path, [("TC-9", ["superuser"]), ("TC-10", ["superuser"])])
    row = say(tmp_path, "superuser", "not_needed")
    r = go(task)
    assert cards(r) == [] and not [g for g in r.stand_gaps if g.get("scope") == "case"]
    assert [f for f in r.findings if f["check"] in ("role_accounts", "case_preconditions")] == []
    assert len(r.covered_gaps) == 1
    gap = r.covered_gaps[0]
    assert gap["id"] == GAP and sorted(gap["cases"]) == ["TC-10", "TC-9"] and gap["scope"] == "role"
    assert gap["property"]["record"] == "project_knowledge" and gap["property"]["id"] == row["id"] and gap["property"]["gap"] == GAP
    assert gap["property"]["subject"] == "product.roles||superuser" and gap["property"]["story"] == "LOCAL-8"
    assert gap["property"]["words"].startswith("superuser is not a role")
    # control: a role the person said nothing about is asked as before, so the keys above can fail
    other = go(story(tmp_path, [("TC-9", ["auditor"])]))
    assert [g["id"] for g in cards(other)] == ["RA-dev-auditor"] and other.covered_gaps == []


def test_covered_line_names_role_story_date(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    said = SG.covered_says(gap)
    assert said == (f'"superuser" is not a role of this product (your answer in LOCAL-8 on {row["at"][:10]}), '
                    "so TC-9 (TC-9 purges the cache) is reported as not run")
    lines = GB._covered_block([gap], {})
    assert lines[0] == "## Decided once for this environment (1)"
    assert lines[2].startswith(f"- {GAP}: {said} — you wrote: \"superuser is not a role here")
    assert any("write `<name>: ask again`" in line for line in lines)
    # control: an environment-record gap keeps its own sentence and its date in the line (the road is unchanged)
    env = {"id": "RP-web", "scope": "level", "contour": "web", "cases": ["TC-1"],
           "property": {"id": "EP-1", "about": "the web tests", "words": "web: accept always", "at": "2026-10-05T11:00:00+00:00"}}
    assert GB._covered_block([env], {})[2] == ('- web: on this environment the web tests cannot be checked — you wrote on 2026-10-05: '
                                              '"web: accept always"')


def test_covered_line_explains_every_case_id_at_both_gates(tmp_path):
    """B2: the "Decided once" line names each case by id AND title (human_text `explained_ids`), at gate A and at gate B; more than
    `ROLE_NAMED` cases end on "and K more"; a case with no file says so in the role card's words."""
    import human_text
    cases = [(f"TC-{n}", ["superuser"]) for n in range(9, 14)]
    task, gap, row = covered_gap(tmp_path, cases)
    assert gap["case_titles"]["TC-9"] == "TC-9 purges the cache"
    block = GB._covered_block([gap], {})
    assert human_text.shape_problems("\n".join(block)) == [], block
    assert "TC-10 (TC-10 purges the cache)" in SG.covered_says(gap)
    assert SG.covered_says(gap).endswith(", and 2 more are reported as not run"), SG.covered_says(gap)
    carried(task, row, case="TC-9")
    asked, covered, _answers = gate_b(task)
    assert asked == [] and covered[0]["case_titles"] == {"TC-9": "TC-9 purges the cache"}
    assert human_text.shape_problems("\n".join(GB._covered_block(covered, {}))) == []
    # control: without the titles the bare id IS flagged, so the check above can fail
    bare = dict(gap, case_titles={}, cases=["TC-9"])
    assert SG.covered_says(bare).count(SG.CASE_FILE_MISSING) == 1
    assert human_text.shape_problems("- x: TC-9 is reported as not run") != []


def test_cover_row_and_card_row_share_one_builder(tmp_path):
    """D1: the covered row carries the env-file path as `remedy.where` (the card's F5 form), its id is `role_gap_id`'s, and its property is
    `stand_gaps.pk_property`'s; D4: the reader is public."""
    task, gap, row = covered_gap(tmp_path)
    assert gap["remedy"]["where"] == "login.env" and gap["remedy"]["where_words"] == "the project's env file"
    assert gap["id"] == GP.role_gap_id("dev", "superuser", ["superuser"])
    assert gap["property"] == SG.pk_property(row, GAP)
    assert SG.pk_property_of(gap) == gap["property"] and SG.pk_property_of({"property": {"id": "EP-1"}}) == {}


def test_probe_of_a_not_needed_role_with_a_config_account_never_signs_in(tmp_path):
    """B1: not_needed wins over a config account in the probe too: no sign-in, no `actor_sign_in` finding."""
    import manual_capture as MC
    task = story(tmp_path, [("TC-9", ["superuser"])])
    cfg_path = tmp_path / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["environments"][0]["credentials_by_role"] = {"superuser": "S_USER / S_PASS"}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "login.env").write_text("S_USER=u\nS_PASS=p\n", encoding="utf-8")
    say(tmp_path, "superuser", "not_needed")
    calls = []

    def probed(rehearsal):
        rehearsal._probe_sign_in = lambda *a, **k: calls.append(a) or {"signed_in": False, "kind": "not_landed"}
        rehearsal.check_role_accounts()
        rehearsal._probe_actor(MC, "superuser", ["TC-9"], rehearsal._precondition_ctx({}), rehearsal._selected_environment())
        return rehearsal
    r = probed(GP.Rehearsal(task, "A"))
    assert r.covered_gaps and calls == [] and [f for f in r.findings if f["check"] == "actor_sign_in"] == []
    # control: the same account with no answer IS signed in as (and the failed sign-in is the person's question)
    PK.revoke(tmp_path, PK.load(tmp_path)[0][-1]["id"], "ask again")
    o = probed(GP.Rehearsal(task, "A"))
    assert len(calls) == 1 and [f["check"] for f in o.findings if f["check"] == "actor_sign_in"] == ["actor_sign_in"]


def test_probe_of_a_not_needed_role_does_not_wait_for_a_card(tmp_path):
    """PK0-4 F-open: no card exists for a not_needed role, so the sign-in probe never says it waits for one; it says why it did not try."""
    import human_text
    import manual_capture as MC
    task = story(tmp_path, [("TC-9", ["superuser"])])
    say(tmp_path, "superuser", "not_needed")
    r = GP.Rehearsal(task, "A")
    r.check_role_accounts()
    r._probe_actor(MC, "superuser", ["TC-9"], r._precondition_ctx({}), r._selected_environment())
    texts = [i["message"] for i in r.info if i["check"] == "actor_sign_in"]
    assert [f for f in r.findings if f["check"] == "actor_sign_in"] == [] and cards(r) == []
    assert texts == ["the sign-in of superuser was not tried: you said it is not a role of this product"]
    assert not any("waits for the card" in i["message"] for i in r.info) and human_text.shape_problems(texts[0]) == []
    # control: a role nobody answered about still has its card and says the probe waits for it
    other = story(tmp_path, [("TC-9", ["auditor"])])
    o = GP.Rehearsal(other, "A")
    o.check_role_accounts()
    o._probe_actor(MC, "auditor", ["TC-9"], o._precondition_ctx({}), o._selected_environment())
    assert [g["id"] for g in cards(o)] == ["RA-dev-auditor"] and any("waits for the card" in i["message"] for i in o.info)


def test_revoked_not_needed_asks_again(tmp_path):
    task = story(tmp_path, [("TC-9", ["superuser"])])
    row = say(tmp_path, "superuser", "not_needed")
    assert go(task).covered_gaps != []
    revoked, problem = PK.revoke(tmp_path, row["id"], "ask again")
    assert revoked is not None, problem
    r = go(task)
    assert r.covered_gaps == [] and [g["id"] for g in cards(r)] == [GAP]
    assert [f["check"] for f in r.findings if f["check"] == "role_accounts"] == ["role_accounts"]


def test_later_known_row_wins_over_not_needed(tmp_path):
    task = story(tmp_path, [("TC-9", ["superuser"])])
    say(tmp_path, "superuser", "not_needed")
    say(tmp_path, "superuser", "known")
    r = go(task)
    assert r.covered_gaps == [] and [g["id"] for g in cards(r)] == [GAP]
    # the same word in another spelling of the role (equal under the comparator) decides too: not_needed again, after the known row
    say(tmp_path, "SuperUser", "not_needed")
    assert [g["id"] for g in go(task).covered_gaps] == [GAP]


def test_unreadable_registry_no_cover(tmp_path):
    task = story(tmp_path, [("TC-9", ["superuser"])])
    say(tmp_path, "superuser", "not_needed")
    PK.record_path(tmp_path).write_text("{broken", encoding="utf-8")
    r = go(task)
    assert r.covered_gaps == [] and [g["id"] for g in cards(r)] == [GAP]          # toward asking (FR-59)
    assert any("could not be read" in str(f.get("message") or f) for f in r.info + r.findings), "the unreadable registry is said"


# --- the driver: carry and take-back ---------------------------------------------------------------------------------------

def test_cases_carried_as_not_run(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    entries = SG.covered_entries([gap])
    assert len(entries) == 1 and entries[0]["by"] == SG.PK_BY and entries[0]["option"] == "accept"
    assert entries[0]["property"] == [{"id": row["id"], "record": "project_knowledge", "subject": "product.roles||superuser", "gap": GAP}]
    assert SG.covered_says(gap) in entries[0]["line"] and "superuser is not a role here" in entries[0]["line"]
    fake, said = Fake(tmp_path), []
    assert SG.write_environment_overrides(task, "QA-1", [gap], [GAP], fake.py, fake.words_file, said.append) == set()
    own = [c for c in fake.calls if c[0] == "waiver.py"]
    assert len(own) == 1 and own[0][own[0].index("--block") + 1] == f"stand gap: {GAP}" and own[0][-2:] == ("--by", "project-knowledge")
    assert said == [f"gate A: {GAP}: not asked - {SG.covered_says(gap)}"]
    # the case carry: `--by project-knowledge`, the case, and the typed property (with its record) stored with it
    put(task, "TC-9", None, None)                       # the live override `annotate_override` adds the property to (waiver would have written it)
    fake.calls.clear()
    SG.write_carries(task, "QA-1", [gap], entries, ["TC-9"], {}, set(), fake.py, fake.words_file, said.append)
    carry = [c for c in fake.calls if c[0] == "waiver.py"]
    assert len(carry) == 1 and carry[0][carry[0].index("--block") + 1] == "stand gap: TC-9" and carry[0][-2:] == ("--by", "project-knowledge")
    stored = [o for o in json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["stage_overrides"] if o["match"] == "stand gap: TC-9"][0]
    assert stored["property"] == entries[0]["property"] and stored["declared"] == ["PC-1"]


def test_gate_a_mixed_records_carry_has_no_by_and_names_both(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    env = {"id": "RP-web", "scope": "level", "contour": "web", "cases": ["TC-9"],
           "property": {"id": "EP-1", "subject": {"scope": "level", "contour": "web"}, "words": "web: accept always", "at": ANSWER}}
    entries = SG.covered_entries([gap, env])
    assert [e["by"] for e in entries] == [SG.PK_BY, SG.ENV_BY]
    put(task, "TC-9", None, None)
    fake = Fake(tmp_path)
    SG.write_carries(task, "QA-1", [gap, env], entries, ["TC-9"], {}, set(), fake.py, fake.words_file, lambda text: None)
    carry = [c for c in fake.calls if c[0] == "waiver.py"][0]
    assert "--by" not in carry
    stored = [o for o in json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["stage_overrides"] if o["match"] == "stand gap: TC-9"][0]
    assert [p["id"] for p in stored["property"]] == [row["id"], "EP-1"]


def test_ask_again_revokes_the_registry_row(tmp_path):
    import story_run as SR
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    fake = Fake(tmp_path)
    d = SR.Driver.__new__(SR.Driver)
    d.py, d.words_file, d.task_root, d.task = fake.py, fake.words_file, task, "QA-1"
    d.state = {"shown_gaps": {"A": {"covered": [gap], "gaps": []}}, "stand_accept_cases": ["TC-9", "TC-1"], "stand_accept_remedies": {"TC-9": {}}}
    line = f"{GAP}: ask again"
    out = d.revoke_environment_properties("A", [{"gap": gap, "line": line, "option": "ask again"}])
    assert fake.calls[0][:4] == ("project_knowledge.py", "revoke", "--id", row["id"])
    assert not any(c[0] == "environment_record.py" for c in fake.calls)
    revoked_blocks = [c[c.index("--block") + 1] for c in fake.calls if c[0] == "waiver.py" and "--revoke" in c]
    assert sorted(revoked_blocks) == sorted([f"stand gap: {GAP}", "stand gap: TC-9"])      # this story's records that rest on the row
    assert out and out[0]["line"] == line and "record of earlier answers" in out[0]["why"]
    assert d.state["stand_accept_cases"] == ["TC-1"] and d.state["stand_accept_remedies"] == {}
    assert d.state["shown_gaps"]["A"]["covered"] == [] and d.state["shown_gaps"]["A"]["reopened"] == [gap]
    # a refused revoke changes nothing and says so (the door of the refusal is the tool's own printed line)
    failing = Fake(tmp_path, code=2)
    d.py, d.state = failing.py, {"shown_gaps": {"A": {"covered": [gap], "gaps": []}}, "stand_accept_cases": ["TC-9"]}
    out = d.revoke_environment_properties("A", [{"gap": gap, "line": line, "option": "ask again"}])
    assert [c[0] for c in failing.calls] == ["project_knowledge.py"] and "nothing was changed" in out[0]["why"]
    assert d.state["stand_accept_cases"] == ["TC-9"] and d.state["shown_gaps"]["A"]["covered"] == [gap]


# --- gate B (N4) ----------------------------------------------------------------------------------------------------------------

def test_gate_b_does_not_reask_not_needed_cases(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    asked, covered, answers = gate_b(task)
    assert asked == [] and answers["TC-9"]["by"] == SG.PK_BY and answers["TC-9"]["change"] == ""
    assert SG.carried_change(task, "TC-9", answers["TC-9"]) == ""
    assert len(covered) == 1 and covered[0]["id"] == GAP and covered[0]["gate"] == "B" and covered[0]["cases"] == ["TC-9"]
    assert covered[0]["property"]["record"] == "project_knowledge" and covered[0]["property"]["id"] == row["id"]
    assert SG.covered_says(covered[0]) == SG.covered_says(gap)
    assert any(GAP in line and "is not a role of this product" in line for line in GB._covered_block(covered, {}))


def test_c2_commit_change_keeps_pk_carry(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    confirm(task, "2026-10-01T09:00:00+00:00")
    confirm(task, "2026-10-06T09:00:00+00:00", revision="c" * 40)
    assert change_of(task) == ""                                  # a new commit after the answer is no change for a not-a-role answer
    confirm(task, "2026-10-07T09:00:00+00:00", revision="c" * 40, sha="d" * 64)
    assert "the stand's address" in change_of(task)               # a re-pointed stand still reopens it
    # control: the same commit change reopens an answer that is not the registry's
    path = task / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    for entry in pipeline["stage_overrides"]:
        entry["by"] = "human"
    path.write_text(json.dumps(pipeline), encoding="utf-8")
    (task / "state" / "stand-confirmations.jsonl").unlink()
    confirm(task, "2026-10-01T09:00:00+00:00")
    confirm(task, "2026-10-06T09:00:00+00:00", revision="c" * 40)
    assert "the commit" in change_of(task)


def test_c4_revoked_pk_row_reopens(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    assert gate_b(task)[0] == []
    PK.revoke(tmp_path, row["id"], "ask again")
    asked, covered, answers = gate_b(task)
    assert [g["id"] for g in asked] == ["TC-9"] and covered == []
    assert "it was taken back" in answers["TC-9"]["change"]


def test_c4_role_no_longer_not_needed_reopens(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    say(tmp_path, "superuser", "known")
    asked, covered, answers = gate_b(task)
    assert [g["id"] for g in asked] == ["TC-9"] and covered == []
    assert "the person's answer about the role has changed" in answers["TC-9"]["change"]


def test_c4_pk_only_carry_ignores_unreadable_environment_record(tmp_path):
    import environment_record as ER
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    ER.record_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    ER.record_path(tmp_path).write_text("{broken", encoding="utf-8")
    asked, covered, answers = gate_b(task)
    assert asked == [] and len(covered) == 1 and answers["TC-9"]["change"] == ""
    # control: an environment property in the same carry DOES need the record, and reopens
    carried(task, row, props=[pk_prop(row), {"id": "EP-1", "subject": {"scope": "level", "contour": "web"}}], gap_too=False)
    assert "the environment record cannot be read" in change_of(task)


def test_c4_pk_carry_without_property_reopens(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row, props=None)
    asked, covered, answers = gate_b(task)
    assert [g["id"] for g in asked] == ["TC-9"] and covered == []
    assert "the answer names no record of it" in answers["TC-9"]["change"]


def test_c4_unreadable_registry_reopens(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row)
    PK.record_path(tmp_path).write_text("{broken", encoding="utf-8")
    asked, covered, answers = gate_b(task)
    assert [g["id"] for g in asked] == ["TC-9"] and covered == []
    assert "the record of earlier answers cannot be read" in answers["TC-9"]["change"]


def test_gate_b_split_mixed_carry_not_covered_by_pk(tmp_path):
    task, gap, row = covered_gap(tmp_path)
    carried(task, row, by="")                                       # a mixed carry has no `--by`: the registry does not cover it
    asked, covered, answers = gate_b(task)
    assert [g["id"] for g in asked] == ["TC-9"] and covered == []
    assert answers["TC-9"].get("by") == ""


def test_pk_carry_adversarial_inputs_stay_on_the_asking_side(tmp_path):
    task, gap, row = covered_gap(tmp_path)

    def fresh(**kw):
        (task / "pipeline.json").write_text("{}", encoding="utf-8")
        carried(task, row, **kw)

    fresh()                                    # control: the settled fixture IS covered
    assert gate_b(task)[0] == []
    fresh(props=[dict(pk_prop(row), id="EP-1")])      # the record is the registry but the id is an environment-record id
    assert [g["id"] for g in gate_b(task)[0]] == ["TC-9"]
    fresh(gap_too=False)                       # the property's gap id is not among the live PK_BY keys (no override of the gap here)
    assert [g["id"] for g in gate_b(task)[0]] == ["TC-9"]
    fresh(gap_too=False)                       # the gap's override is another's: its key is not a PK_BY key
    put(task, GAP, "human", None)
    assert [g["id"] for g in gate_b(task)[0]] == ["TC-9"]
    fresh()                                    # a gate B gap that ran red is asked whatever the registry says
    assert [g["id"] for g in gate_b(task, ran_red="ran red: the node lost its state")[0]] == ["TC-9"]
    assert gate_b(task)[0] == []


# --- the environment-record road is unchanged -----------------------------------------------------------------------------------

def test_environment_record_rows_unchanged(tmp_path):
    import environment_record as ER
    import test_stand_gaps as TSG
    root, task_root, ep = TSG.level_story("qa-not-needed-env-")
    try:
        TSG.env_overrides(task_root, ep)
        asked, covered = SG.gate_b_split(task_root)
        assert asked == [] and len(covered) == 1
        gap = covered[0]
        assert set(gap) == {"id", "gate", "stage", "scope", "case_id", "case", "contour", "cases", "property"} and gap["property"] == ep
        assert SG.covered_says(gap) == ER.says(ep) == "on this environment the web tests cannot be checked"
        date = str(ep["at"])[:10]
        entries = SG.covered_entries(covered)
        assert entries == [{"gap": gap, "option": "accept", "by": "environment-record",
                            "line": f"web: accept always (recorded for this environment on {date}, EP-1)",
                            "property": [{"id": "EP-1", "subject": ep["subject"]}]}]
        assert GB._covered_block(covered, {})[2] == (f'- web: on this environment the web tests cannot be checked — you wrote on {date}: '
                                                     '"web: accept always"')
        # write_environment_overrides / write_carries: the same commands and lines as before
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "T-414", "environment": "QA"}), encoding="utf-8")
        fake, said = Fake(task_root), []
        assert SG.write_environment_overrides(task_root, "T-414", covered, ["RP-web"], fake.py, fake.words_file, said.append) == set()
        assert fake.calls == [("waiver.py", "--task", "T-414", "--stage", "S5", "--block", "stand gap: RP-web", "--words-file",
                               str(task_root / "env-gap.txt"), "--by", "environment-record")]
        assert said == [f"gate A: web: not asked - you recorded on {date} that on this environment the web tests cannot be checked"]
        fake.calls.clear()
        SG.write_carries(task_root, "T-414", covered, entries, ["TC-001", "TC-002"], {}, set(), fake.py, fake.words_file, said.append)
        assert [(c[c.index("--block") + 1], c[-2:]) for c in fake.calls] == [("stand gap: TC-001", ("--by", "environment-record")),
                                                                              ("stand gap: TC-002", ("--by", "environment-record"))]
        # _c2: a commit change is no change for it, a re-pointed stand is; _c4: the record decides - and its road is the environment record's
        TSG.env_overrides(task_root, ep)
        answer = {"option": "accept", "by": "environment-record", "at": "2026-10-05T11:00:00+00:00", "property": [{"id": "EP-1", "subject": ep["subject"]}]}
        confirm(task_root, "2026-10-01T09:00:00+00:00")
        confirm(task_root, "2026-10-06T09:00:00+00:00", revision="c" * 40)
        assert SG.carried_change(task_root, "TC-001", answer, only=("C2",)) == ""
        confirm(task_root, "2026-10-07T09:00:00+00:00", revision="c" * 40, sha="d" * 64)
        assert "the stand's address" in SG.carried_change(task_root, "TC-001", answer, only=("C2",))
        assert SG.carried_change(task_root, "TC-001", answer, only=("C4",)) == ""
        ER.revoke(root, "EP-1", "ask again")
        assert "the recorded environment property no longer holds (it was taken back)" in SG.carried_change(task_root, "TC-001", answer, only=("C4",))
        assert SG.carried_change(task_root, "TC-001", dict(answer, by="environment-record", property=None), only=("C4",)) == (
            "the recorded environment property no longer holds (the answer names no record of it)")
    finally:
        TSG.cleanup(root)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
