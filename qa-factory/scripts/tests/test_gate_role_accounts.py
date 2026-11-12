"""PK0-4 (t-2142): ONE card per (stand, role) at gate A - the role card, the twins card, the confirm card, the acting line.

The story is a real project folder (config, case files, the registry of project knowledge, a pipeline with the person's answers); the rehearsal is
the real `gate_preflight.Rehearsal` and the cards are rendered by the real `gate_brief`. Only `planning_contract._applied_records` (the question
register's applied answers) and `project_knowledge.story_roles` (the strategist's form; read by its own tests, PK0-1) are replaced where a test
needs one answer. Fast; the neighbours (`test_gate_preflight.py`, `test_gate_brief_and_retro.py`) are on the slow list and are judged by CI.
"""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_brief as GB  # noqa: E402
import gate_preflight as GP  # noqa: E402
import human_text  # noqa: E402
import manual_capture as MC  # noqa: E402
import project_knowledge as PK  # noqa: E402
import stand_gaps as SG  # noqa: E402

LABELS = ["the factory:", "you:", "the story:"]
# non-ASCII role names, written as escapes (the package is English, FR-30): "auditor", "manager", "admin-department", "admin-warehouse" in Cyrillic
def _cyrillic(*codes):
    return "".join(chr(code) for code in codes)


AUDITOR, MANAGER = _cyrillic(0x430, 0x443, 0x434, 0x438, 0x442, 0x43e, 0x440), _cyrillic(0x43c, 0x435, 0x43d, 0x435, 0x434, 0x436, 0x435, 0x440)
ADMIN_DEPT, ADMIN_STORE = "admin-" + _cyrillic(0x43e, 0x442, 0x434, 0x435, 0x43b), "admin-" + _cyrillic(0x441, 0x43a, 0x43b, 0x430, 0x434)


def pc(n, role, remedy=True):
    item = {"id": f"PC-{n}", "kind": "account", "what": f"the account of {role}", "partitions": [], "check": {"stand_account": role}}
    if remedy:
        item["remedy"] = {"kind": "credential", "where": "the env file", "change": "two variables"}
    return item


def story(tmp_path, cases, *, stands=("dev",), roles=None, pipeline=None, titles=None):
    """A project and a story. `cases`: [(case id, [roles] | raw preconditions text)]. Returns the story root."""
    cfg = {"environments": [{"name": n, "credentials_by_role": dict(roles or {})} for n in stands], "environment": {"env_file": "login.env"}}
    (tmp_path / "qa-factory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "login.env").write_text("", encoding="utf-8")
    task = tmp_path / "qa-factory" / "artifacts" / "QA-1"
    shutil.rmtree(task, ignore_errors=True)
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(pipeline or {}), encoding="utf-8")
    for n, (cid, declared) in enumerate(cases, 1):
        raw = declared if isinstance(declared, str) else json.dumps([pc(i, r) for i, r in enumerate(declared, 1)])
        title = (titles or {}).get(cid, f"{cid} checks the order screen")
        (task / "work" / "test-cases" / f"{cid}.md").write_text(
            f"---\nid: {cid}\ntask: QA-1\ntitle: {title}\npreconditions: {raw}\n---\n# {title}\n", encoding="utf-8")
    return task


def go(task, check_cases=True):
    r = GP.Rehearsal(task, "A")
    r.check_role_accounts()
    if check_cases:
        r.check_case_preconditions()
    return r


def cards(r, scope="role"):
    return [g for g in r.stand_gaps if g.get("scope") == scope]


def found(r, check="role_accounts"):
    return [f for f in r.findings if f["check"] == check]


def packet(task, r):
    gaps = SG._gate_a_gaps(task, r.stand_gaps)
    return gaps, GB.stand_gap_card_lines(task, gaps, limit=None)


def say(root, key, element, state, env="", scope=None, story_id="LOCAL-7"):
    row, problem, _ = PK.record(root, key=key, environment=env, element=element, state=state,
                                scope=scope or PK.KEYS[key]["scope"], value={}, words="the person's words", source="person",
                                story=story_id, by="conductor")
    assert row, problem
    return row


def override(task, match, decision="accept", **extra):
    pipe = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    pipe.setdefault("stage_overrides", []).append(dict({"stage": "S5", "match": match, "decision": decision, "at": "2026-11-01T10:00:00Z"}, **extra))
    (task / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")


def priced(lines):
    """Every option line (`  - ...`) of the card text is followed by the three price labels, in order."""
    starts = [i for i, line in enumerate(lines) if line.startswith("  - ")]
    assert starts
    for i in starts:
        assert [lines[i + 1 + n].strip().startswith(label) for n, label in enumerate(LABELS)] == [True] * 3, lines[i:i + 4]
    return len(starts)


def test_one_card_per_stand_role_holding_only_its_cases(tmp_path):
    task = story(tmp_path, [("TC-1", ["admin", "auditor"]), ("TC-2", ["auditor"]), ("TC-3", ["admin"])])
    r = go(task)
    rows = {g["id"]: g for g in cards(r)}
    assert sorted(rows) == ["RA-dev-admin", "RA-dev-auditor"]
    assert rows["RA-dev-admin"]["cases"] == ["TC-1", "TC-3"] and rows["RA-dev-auditor"]["cases"] == ["TC-1", "TC-2"]
    assert sorted(f["id"] for f in r.findings) == ["role_accounts-dev-admin", "role_accounts-dev-auditor"]
    assert cards(r)[0]["remedy"]["where"] == "login.env" and cards(r)[0]["remedy"]["where_words"] == "the project's env file"      # F5: the path
    assert found(r, "case_preconditions") == [] and not [g for g in r.stand_gaps if g.get("scope") == "case"]


@pytest.mark.parametrize("stand,role", [("a" * 40, "r" * 40), ("the stand name of exactly forty chars", "the role name of exactly forty chars!")])
def test_finding_lead_within_brief_cut_and_names_stand_role_question(tmp_path, stand, role):
    task = story(tmp_path, [("TC-1", [role]), ("TC-2", [role])], stands=(stand,))
    message = found(go(task))[0]["message"]
    assert len(message) <= GP.BRIEF_CUT and message.index("?") < GP.BRIEF_CUT
    assert "account" in message and stand[:6] in message and role[:6] in message      # the 84-character id leaves room for the compact form only
    assert "TC-" not in message          # no case id: no per-case block can match the lead


def test_card_rendered_whole_in_packet(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"]), ("TC-2", ["auditor"])])
    gaps, lines = packet(task, go(task))
    assert lines[2] == 'Stand gap: RA-dev-auditor — the account of the role "auditor" on the stand "dev" (2 cases)'
    assert any(line.startswith("  the test: TC-1 (TC-1 checks the order screen) and TC-2 (TC-2 checks") for line in lines)
    assert any(line.startswith("  missing:  an account for the role \"auditor\" on \"dev\"") for line in lines)
    assert "  - `RA-dev-auditor: accept` - only this story" in lines
    assert priced(lines) == 3 and not any("the fix:" in line for line in lines)
    assert any(line.startswith("To answer a stand gap") for line in lines) and "`RA-dev-auditor: accept`" not in lines[-1]


def test_story_waiver_for_one_role_does_not_pass_another(tmp_path):
    task = story(tmp_path, [("TC-1", ["admin", "auditor"]), ("TC-2", ["admin", "auditor"])])
    override(task, "stand gap: RA-dev-auditor")
    r = go(task)
    assert [f["id"] for f in found(r)] == ["role_accounts-dev-admin"]
    assert sorted(g["id"] for g in cards(r)) == ["RA-dev-admin", "RA-dev-auditor"]
    assert cards(r)[0]["cases"] == cards(r)[1]["cases"] == ["TC-1", "TC-2"]


def test_accept_blocks_only_its_cases(tmp_path):
    task = story(tmp_path, [("TC-1", ["admin", "auditor"]), ("TC-2", ["auditor"]), ("TC-3", ["admin"])])
    gaps, _ = packet(task, go(task))
    read = GB.read_stand_gap_answers("RA-dev-auditor: accept", gaps)
    assert [e["option"] for e in read["read"]] == ["accept"] and read["unread"] == []
    assert SG.gap_cases(read["read"][0]["gap"]) == ["TC-1", "TC-2"]


def test_finding_id_roundtrip(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])])
    fid = found(go(task))[0]["id"]
    assert fid == "role_accounts-dev-auditor" and GP.FINDING_ID_RE.fullmatch(fid)


def test_non_ascii_role_gap_id_stable(tmp_path):
    task = story(tmp_path, [("TC-1", [AUDITOR])])
    first, second = go(task), go(task)
    gap = cards(first)[0]["id"]
    assert re.fullmatch(r"RA-dev-[0-9a-f]{8}", gap) and gap == cards(second)[0]["id"]
    assert found(first)[0]["id"] == f"role_accounts-{gap[3:]}" and GP.FINDING_ID_RE.fullmatch(found(first)[0]["id"])


def test_two_non_ascii_roles_two_gap_ids(tmp_path):
    task = story(tmp_path, [("TC-1", [AUDITOR, MANAGER])])
    first = go(task)
    ids = [g["id"] for g in cards(first)]
    assert len(set(ids)) == 2 and all(re.fullmatch(r"RA-dev-[0-9a-f]{8}", i) for i in ids)
    fids = [f["id"] for f in found(first)]
    assert len(set(fids)) == 2 and not any(re.search(r"-\d$", f) and not re.search(r"[0-9a-f]{8}$", f) for f in fids)
    override(task, f"stand gap: {ids[0]}")
    again = go(task)
    assert [g["id"] for g in cards(again)] == ids and [f["id"] for f in found(again)] == [fids[1]]


def test_mixed_script_roles_two_gap_ids(tmp_path):
    task = story(tmp_path, [("TC-1", [ADMIN_DEPT, ADMIN_STORE])])
    ids = [g["id"] for g in cards(go(task))]
    assert len(set(ids)) == 2 and "RA-dev-admin" not in ids and all(re.fullmatch(r"RA-dev-[0-9a-f]{8}", i) for i in ids)


def test_lossless_role_keeps_readable_id():
    assert GP.role_gap_id("dev", "auditor") == "RA-dev-auditor" and GP.role_gap_id("dev", "ADMIN") == "RA-dev-admin"
    assert GP.role_gap_id("dev", "Default_User") == "RA-dev-default-user" == GP.role_gap_id("dev", "default user")
    assert re.fullmatch(r"RA-[0-9a-f]{8}-auditor", GP.role_gap_id("dév", "auditor"))
    assert GP.role_gap_id("dev", AUDITOR) != GP.role_gap_id("dev", MANAGER)


def test_stand_with_hyphen_or_space_never_shares_an_id():
    """F4: `RA-dev-a-b` was stand `dev-a` + role `b` AND stand `dev` + role `a b`; a stand holding `-` or whitespace takes the hash of its name."""
    pairs = [("dev-a", "b"), ("dev", "a b"), ("dev a", "b"), ("dev", "a"), ("dev-a-b", ""), ("dev", "a b c"), ("dev-a", "b c")]
    ids = [GP.role_gap_id(stand, role) for stand, role in pairs if role]
    assert len(set(ids)) == len(ids), ids
    assert GP.role_gap_id("dev", "a b") == "RA-dev-a-b"                    # a plain stand keeps its readable id
    assert re.fullmatch(r"RA-[0-9a-f]{8}-b", GP.role_gap_id("dev-a", "b"))
    assert GP.role_gap_id("dev-a", "b") == GP.role_gap_id("dev-a", "b") != GP.role_gap_id("dev-b", "b")        # stable, and per exact name


def known_story(tmp_path, keys="A_USER / A_PASS", cases=(("TC-1", ["auditor"]),)):
    task = story(tmp_path, list(cases), roles={"auditor": keys})
    say(tmp_path, PK.ACCOUNTS_KEY, "auditor", PK.KNOWN, env="dev")
    return task


def test_known_role_no_card_acting_line(tmp_path):
    task = known_story(tmp_path)
    (tmp_path / "login.env").write_text("A_USER=u\nA_PASS=p\n", encoding="utf-8")
    r = go(task)
    assert cards(r) == [] and r.findings == [] and r.stand_gaps == []
    notes = [i["message"] for i in r.info if "Acting on your earlier answers" in i["message"]]
    assert len(notes) == 1 and 'the account of "auditor" on "dev" (given in LOCAL-7 on ' in notes[0]


def test_known_answer_marker_is_a_machine_field_never_text(tmp_path):
    task = known_story(tmp_path)
    (tmp_path / "login.env").write_text("A_USER=u\nA_PASS=p\n", encoding="utf-8")
    r = go(task)
    note = [i for i in r.info if "Acting on your earlier answers" in i["message"]][0]
    assert "[knowledge:" not in note["message"] and note["mark"] == GP.ACCOUNT_MARK == "[knowledge:credentials_by_role]"
    assert human_text.shape_problems(note["message"]) == []
    result = {"gate": "A", "task": "QA-1", "next_stage": "S5", "can_proceed": True, "by_class": {}, "findings": [], "info": r.info}
    assert "Acting on your earlier answers" in GP.render(result) and "[knowledge:" not in GP.render(result)       # the printed packet
    assert any(i.get("mark") == GP.ACCOUNT_MARK for i in r.info)                                                    # the count reads the field


def test_legacy_account_not_voiced(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])], roles={"auditor": "A_USER / A_PASS"})
    (tmp_path / "login.env").write_text("A_USER=u\nA_PASS=p\n", encoding="utf-8")
    r = go(task)
    assert r.findings == [] and not [i for i in r.info if "Acting on" in i["message"]]


def test_keys_not_set_stays_per_case_card_and_probe_notes(tmp_path):
    task = known_story(tmp_path)
    r = go(task)
    assert cards(r) == [] and r._account_carded == {"auditor": "case"}
    assert [g["scope"] for g in r.stand_gaps] == ["case"] and len(found(r, "case_preconditions")) == 1
    r._probe_actor(MC, "auditor", ["TC-1"], r._precondition_ctx({}), r._selected_environment())
    assert found(r, "actor_sign_in") == [] and any("waits for the card about its account" in i["message"] for i in r.info)


def test_every_unmet_item_exactly_one_card(tmp_path):
    cases = [("TC-1", ["admin", "auditor"]), ("TC-2", ["admin", "auditor"]), ("TC-3", ["admin", "auditor"]), ("TC-4", ["keyed"]),
             ("TC-5", "[{broken")]
    task = story(tmp_path, cases, roles={"keyed": "K_USER / K_PASS"})
    say(tmp_path, PK.ACCOUNTS_KEY, "keyed", PK.KNOWN, env="dev")
    r = go(task)
    by_scope = {}
    for g in r.stand_gaps:
        by_scope.setdefault(g["scope"], []).append(g)
    assert sorted(g["id"] for g in by_scope["role"]) == ["RA-dev-admin", "RA-dev-auditor"] and [g["case"] for g in by_scope["case"]] == ["TC-4"]
    assert not any(c in ("TC-1", "TC-2", "TC-3") for g in by_scope["case"] for c in [g["case"]])
    person = [f for f in r.findings if f["class"] == GP.PERSON_DECIDES]
    assert len(person) == 3 and any(f["class"] == GP.FACTORY_FIXABLE for f in r.findings)      # the partial parse is the designer's finding


def test_probe_actor_no_second_card(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"]), ("TC-2", ["ghost"])])
    r = GP.Rehearsal(task, "A")
    r.check_role_accounts()
    ctx, stand = r._precondition_ctx({}), r._selected_environment()
    r._probe_actor(MC, "Auditor", ["TC-1"], ctx, stand)
    assert found(r, "actor_sign_in") == [] and any("sign-in of Auditor waits" in i["message"] for i in r.info)
    fresh = GP.Rehearsal(task, "A")        # the control: with no card the probe asks as today
    fresh._probe_actor(MC, "auditor", ["TC-1"], ctx, stand)
    assert len(found(fresh, "actor_sign_in")) == 1


def test_run_cards_the_role_before_the_sign_in_probe(tmp_path, monkeypatch):
    """The order of `GP.run`, by behaviour: a manual case that signs in as `auditor` makes ONE role card and no `actor_sign_in` finding."""
    task = story(tmp_path, [("TC-1", ["auditor"])])
    for name in dir(GP.Rehearsal):
        if name.startswith("check_") and name not in ("check_role_accounts", "check_actor_sign_in", "check_case_preconditions"):
            monkeypatch.setattr(GP.Rehearsal, name, lambda self: None)
    monkeypatch.setattr(GP.Rehearsal, "_actors_of_manual_cases", lambda self: {"auditor": ["TC-1"]})
    result = GP.run(task)
    assert [g["id"] for g in result["stand_gaps"] if g["scope"] == "role"] == ["RA-dev-auditor"]
    assert [f["check"] for f in result["findings"]] == ["role_accounts"]
    assert any("sign-in of auditor waits" in i["message"] for i in result["info"])
    monkeypatch.setattr(GP.Rehearsal, "check_role_accounts", lambda self: None)          # the control: with no role card the probe asks itself
    assert [f["check"] for f in GP.run(task)["findings"] if f["check"] != "case_preconditions"] == ["actor_sign_in"]


def test_a_raise_while_writing_leaves_no_card_without_its_finding(tmp_path, monkeypatch):
    """F6: the cards and their findings are written together, or not at all; the step then reports itself unavailable and the gate is held."""
    task = story(tmp_path, [("TC-1", ["admin", "auditor"])])
    calls = []
    real_add = GP.Rehearsal.add

    def add(self, *args, **kw):
        calls.append(args[0])
        if len(calls) == 2:
            raise RuntimeError("the second finding fails")
        return real_add(self, *args, **kw)
    monkeypatch.setattr(GP.Rehearsal, "add", add)
    r = GP.Rehearsal(task, "A")
    with pytest.raises(RuntimeError):
        r.check_role_accounts()
    assert r.stand_gaps == [] and r.findings == [] and r.info == [] and r._role_carded == set() and r._account_carded == {}
    monkeypatch.setattr(GP.Rehearsal, "add", real_add)          # the control: without the raise both cards and both findings are there
    ok = go(task)
    assert len(cards(ok)) == 2 and len(found(ok)) == 2


def test_role_constants_have_one_home():
    assert GP.ROLE_SCOPES is SG.ROLE_SCOPES and GP.ROLE_NAMED is SG.ROLE_NAMED == 3
    assert GB._role_card({"scope": "role"}) and GB._role_card({"scope": "product_role"}) and not GB._role_card({"scope": "case"})


def test_no_stand_no_role_card(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])], stands=("dev", "stage"))
    r = go(task)
    assert cards(r) == [] and found(r) == []
    task = story(tmp_path, [("TC-1", ["auditor"])], stands=("dev", "stage"), pipeline={"environment": "stage"})
    assert [g["id"] for g in cards(go(task))] == ["RA-stage-auditor"]        # the control: the same story with a chosen stand


def test_partial_parse_case_not_carded(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"]), ("TC-2", '[{"id": "PC-1", "kind": "account"}]')])
    r = go(task)
    assert cards(r)[0]["cases"] == ["TC-1"] and any(f["class"] == GP.FACTORY_FIXABLE for f in found(r, "case_preconditions"))


def test_case_already_accepted_is_dropped(tmp_path, monkeypatch):
    import planning_contract as PC
    task = story(tmp_path, [("TC-1", ["auditor"]), ("TC-2", ["auditor"])])
    monkeypatch.setattr(PC, "_applied_records", lambda root: [{"id": "TC-2", "what": "accept_as_blocked"}])
    assert cards(go(task))[0]["cases"] == ["TC-1"]
    monkeypatch.setattr(PC, "_applied_records", lambda root: (_ for _ in ()).throw(RuntimeError("unreadable")))
    assert cards(go(task))[0]["cases"] == ["TC-1", "TC-2"]       # an unreadable register drops nothing: toward asking


def test_case_accepted_on_its_pc_card_is_dropped(tmp_path):
    task = story(tmp_path, [("TC-3", ["auditor"]), ("TC-4", ["auditor"])])
    override(task, "stand gap: PC-1@TC-3")                       # `PC-1` is shared by the two cases: the id carries the case
    assert cards(go(task))[0]["cases"] == ["TC-4"]
    override(task, "stand gap: PC-1@TC-4")
    assert cards(go(task)) == []
    task = story(tmp_path, [("TC-3", ["auditor"])])
    override(task, "stand gap: PC-1")
    assert cards(go(task)) == []


def test_case_carry_live_is_dropped(tmp_path):
    task = story(tmp_path, [("TC-3", ["auditor"]), ("TC-4", ["auditor"])])
    override(task, "stand gap: TC-3")
    assert cards(go(task))[0]["cases"] == ["TC-4"]


def test_revoked_pc_accept_is_not_dropped(tmp_path):
    task = story(tmp_path, [("TC-3", ["auditor"])])
    override(task, "stand gap: PC-1", revoked_at="2026-11-02T10:00:00Z")
    assert cards(go(task))[0]["cases"] == ["TC-3"]
    task = story(tmp_path, [("TC-3", ["auditor"])])
    override(task, "stand gap: PC-1", decision="myself")
    assert cards(go(task))[0]["cases"] == ["TC-3"]


def test_all_cases_accepted_no_card(tmp_path):
    task = story(tmp_path, [("TC-3", ["auditor"]), ("TC-4", ["auditor"])])
    override(task, "stand gap: TC-3")
    override(task, "stand gap: TC-4")
    assert cards(go(task)) == []


def test_role_not_in_roster_line(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])])
    line = '  "auditor" is not among the product\'s roles yet; an account for it adds it.'
    assert line in packet(task, go(task))[1]
    say(tmp_path, PK.ROLES_KEY, "auditor", PK.KNOWN)
    assert line not in packet(task, go(task))[1]


def twins_story(tmp_path):
    return story(tmp_path, [("TC-1", ["ADMIN"]), ("TC-2", ["ADMIN"])], roles={"Admin": "A_USER / A_PASS", "admin": "B_USER / B_PASS"})


def test_twins_answer_door_is_usable(tmp_path):
    task = twins_story(tmp_path)
    r = go(task)
    gap = cards(r)[0]
    assert gap["id"] == "RA-dev-admin" and gap["variant"] == "twins" and gap["remedy"]["offers"] == ["theirs", "accept"]
    gaps, lines = packet(task, r)
    text = "\n".join(lines)
    assert "`RA-dev-admin: myself` - you remove the wrong one" in text and "give the two names" not in text
    assert [e["option"] for e in GB.read_stand_gap_answers("RA-dev-admin: myself\nRA-dev-admin: accept", gaps)["read"]] == ["accept"]
    assert [e["option"] for e in GB.read_stand_gap_answers("RA-dev-admin: myself", gaps)["read"]] == ["theirs"]
    assert GB.read_stand_gap_answers("RA-dev-admin: A_USER B_USER", gaps)["read"] == []        # no names are an answer


def test_malformed_variant(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])], roles={"auditor": "NOT provisioned here"})
    r = go(task)
    gap = cards(r)[0]
    assert gap["variant"] == "malformed" and len(gap["options"]) == 3
    assert "that does not name two variables, so the factory cannot sign in as it" in "\n".join(packet(task, r)[1])


def test_no_accept_always_offered(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])])
    r = go(task)
    gaps, lines = packet(task, r)
    assert "property_key" not in cards(r)[0] and "accept always" not in "\n".join(lines) and not GB.lasting_offered(gaps[0])
    assert GB.read_stand_gap_answers("RA-dev-auditor: accept always", gaps)["read"] == []


def confirm_story(tmp_path, monkeypatch, named=("guest",), noticed=("guest", "ghostly")):
    task = story(tmp_path, [("TC-1", ["auditor"])])
    for role in noticed:
        say(tmp_path, PK.ROLES_KEY, role, PK.NOTICED)
    monkeypatch.setattr(PK, "story_roles", lambda root: ([{"role": r, "sign_in": "none", "where": 'R-2: "a visitor who is not signed in sees the catalogue"'}
                                                          for r in named], ""))
    return task


def test_confirm_card_only_roles_this_story_names(tmp_path, monkeypatch):
    r = go(confirm_story(tmp_path, monkeypatch))
    assert [g["id"] for g in cards(r, "product_role")] == ["PR-guest"]       # `ghostly` is noticed but this story does not name it
    r = go(confirm_story(tmp_path, monkeypatch, named=("guest", "Guest")))
    assert len(cards(r, "product_role")) == 1                                    # one card per role form


def test_confirm_card_holds_no_finding(tmp_path, monkeypatch):
    r = go(confirm_story(tmp_path, monkeypatch))
    assert [f["id"] for f in r.findings] == ["role_accounts-dev-auditor"]       # the role card's own; the confirm card adds none
    assert cards(r, "product_role")[0]["remedy"] == {"offers": []}


def test_confirm_card_not_in_answer_block(tmp_path, monkeypatch):
    task = confirm_story(tmp_path, monkeypatch)
    r = go(task)
    gaps, lines = packet(task, r)
    text = "\n".join(lines)
    assert "Product role to confirm: PR-guest — \"guest\", a role the test strategist found in this story's requirements" in text
    assert "the fix:" not in text and "`PR-guest: " not in text
    assert any(line.startswith("To answer a stand gap") and "RA-dev-auditor: accept" in line for line in lines)
    only = [g for g in gaps if g["id"] == "PR-guest"]
    assert not any(line.startswith("To answer a stand gap") for line in GB.stand_gap_card_lines(task, only, limit=None))


def test_every_option_has_three_price_lines(tmp_path, monkeypatch):
    total = 0
    for variant in (lambda: story(tmp_path, [("TC-1", ["auditor"])]), lambda: twins_story(tmp_path),
                    lambda: story(tmp_path, [("TC-1", ["auditor"])], roles={"auditor": "none"}),
                    lambda: confirm_story(tmp_path, monkeypatch)):
        task = variant()
        total += priced(packet(task, go(task))[1])
    assert total == 3 + 2 + 3 + 3 + 3          # the confirm story also holds a role card


def test_case_ids_explained_by_title(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"]), ("TC-2", ["auditor"]), ("TC-3", ["auditor"]), ("TC-4", ["auditor"])],
                 titles={"TC-1": "an auditor opens an order and sees no edit button"})
    _, lines = packet(task, go(task))
    first = next(line for line in lines if "TC-1" in line)
    assert first.startswith("  the test: TC-1 (an auditor opens an order and sees no edit button)") and "and 1 more" in first
    assert not any("TC-4" in line for line in lines)          # an id the `the test:` line does not explain is never named
    assert human_text.shape_problems("\n".join(lines)) == []


def test_long_titles_keep_the_end_of_the_test_line(tmp_path):
    """F2: four cases with titles of ~70 characters - `and 1 more` and the sign-in phrase stay on the whole line; `missing:` is whole too."""
    title = "an auditor opens the order list filtered by status and sees no edit"
    ids = ["TC-1", "TC-2", "TC-3", "TC-4"]
    role = "auditor of the second warehouse"
    task = story(tmp_path, [(c, [role]) for c in ids], titles={c: f"{title} {c}" for c in ids})
    r = go(task)
    _, lines = packet(task, r)
    line = next(x for x in lines if x.startswith("  the test:"))
    assert len(line) > 200 and line.endswith(f'and 1 more sign in as "{role}"') and "TC-3 (" in line and "TC-4" not in line
    missing = next(x for x in lines if x.startswith("  missing:"))
    assert missing.endswith("do not need it and are not held by it")
    assert human_text.shape_problems("\n".join(lines)) == []


def test_missing_line_whole_with_long_names_in_every_variant(tmp_path):
    stand, role = "the stand name of exactly forty chars", "the role name of exactly forty chars!"
    for cfg_roles, tail in (({}, "are not held by it"), ({role: "NOT provisioned"}, "cannot sign in as it"),
                            ({role.upper(): "A_USER / A_PASS", role.capitalize(): "B_USER / B_PASS"}, "cannot tell which")):
        task = story(tmp_path, [("TC-1", [role])], stands=(stand,), roles=cfg_roles)
        missing = next(x for x in packet(task, go(task))[1] if x.startswith("  missing:"))
        assert missing.endswith(tail) and len(missing) > 150, missing


def test_lead_stays_in_the_brief_cut_for_a_very_long_gap_id(tmp_path):
    """F8: an id of any length leaves the question inside `BRIEF_CUT` - the last form names no gap (the card's heading does)."""
    stand, role = "s" * 150, "r" * 150
    for variant in (None, "twins"):
        roles = {role.upper(): "A_USER / A_PASS", role.capitalize(): "B_USER / B_PASS"} if variant else None
        task = story(tmp_path, [("TC-1", [role])], stands=(stand,), roles=roles)
        r = go(task)
        message = found(r)[0]["message"]
        assert len(cards(r)[0]["id"]) > GP.BRIEF_CUT and len(message) <= GP.BRIEF_CUT and message.index("?") < GP.BRIEF_CUT, message
        assert GP.GAP_SLOT not in message and human_text.shape_problems(message) == []


def test_unreadable_registry_note(tmp_path):
    task = story(tmp_path, [("TC-1", ["auditor"])])
    (tmp_path / "qa-factory" / "records").mkdir(parents=True)
    (tmp_path / "qa-factory" / "records" / "project-knowledge.json").write_text("{not json", encoding="utf-8")
    r = go(task)
    notes = [i for i in r.info if "could not be read this time" in i["message"]]
    assert len(notes) == 1 and notes[0]["problem"] and "project-knowledge" not in notes[0]["message"]
    assert [g["id"] for g in cards(r)] == ["RA-dev-auditor"]       # an unknown suppresses nothing


def test_texts_pass_human_text(tmp_path, monkeypatch):
    for variant in (lambda: story(tmp_path, [("TC-1", ["auditor"]), ("TC-2", ["auditor"])]), lambda: twins_story(tmp_path),
                    lambda: story(tmp_path, [("TC-1", ["auditor"])], roles={"auditor": "none"}),
                    lambda: confirm_story(tmp_path, monkeypatch)):
        task = variant()
        r = go(task)
        text = "\n".join(packet(task, r)[1]) + "\n" + "\n".join(f["message"] for f in r.findings)
        assert human_text.shape_problems(text) == [], text


def test_info_notes_pass_human_text(tmp_path):
    """F7: the three new INFO notes - the acting line, the unreadable-registry note, the probe note - are text a person reads."""
    task = known_story(tmp_path)
    (tmp_path / "login.env").write_text("A_USER=u\nA_PASS=p\n", encoding="utf-8")
    texts = [i["message"] for i in go(task).info]
    assert any("Acting on your earlier answers" in t for t in texts)
    task = story(tmp_path, [("TC-1", ["auditor"])])
    (tmp_path / "qa-factory" / "records").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa-factory" / "records" / "project-knowledge.json").write_text("{not json", encoding="utf-8")
    texts += [i["message"] for i in go(task).info]
    assert any("could not be read this time" in t for t in texts)
    (tmp_path / "qa-factory" / "records" / "project-knowledge.json").unlink()
    r = GP.Rehearsal(task, "A")
    r.check_role_accounts()
    r._probe_actor(MC, "auditor", ["TC-1"], r._precondition_ctx({}), r._selected_environment())
    texts += [i["message"] for i in r.info]
    assert any("waits for the card" in t for t in texts)
    for text in texts:
        assert human_text.shape_problems(text) == [], text


def test_check_writes_nothing(tmp_path, monkeypatch):
    task = confirm_story(tmp_path, monkeypatch)

    def tree():
        return {str(p.relative_to(tmp_path)): p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    before = tree()
    go(task)
    assert tree() == before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
