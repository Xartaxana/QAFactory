#!/usr/bin/env python3
"""TR3-10 C: `walk_pool.py` - an account per lane and the records a lane may change (real files in a temp project, no browser, no network).

Mutation -> the ONE test that kills it: a lift that drifts from `Driver.walk_actors` -> lane_handles_same_as_walk_actors; an extra account
whose key names are not in the env files -> pool_adds_more_accounts_existing_keys_only; a doubted handle kept -> pool_drops_doubted; the
cap ignored -> pool_capped_by_limit; one key pair counted twice -> pool_dedupes_same_pair; an extra with no ok probe row -> pool_keeps_only_ok_rows;
an unreadable doubts store read as no doubt -> doubts_unreadable_base_only; a handle given to two lanes while another is free ->
assign_round_robin_deterministic; obtain for a role not listed or on a stand that may not be changed -> obtain_only_listed_role_and_changeable_stand;
parts that come from different rounds -> two_part_key_same_round; the way question's list wrong -> short_parts_only_when_not_known; a shared guest ->
guest_pool_one_per_lane; one instance for two lanes -> assign_entities_distinct_instances; half an item given -> assign_all_or_none_of_an_item; a pool of
one given twice -> assign_pool_of_one_two_lanes_in_turn; an unreadable store used -> assign_unreadable_store_runs_alone; the instance written after the
dispatch -> assign_instance_written_in_use_before_dispatch; a constraint made up for an item that says none -> no_walk_data_no_assignment; a create
before an answer or under `existing_only` -> data_may_*; a removal line under `create` -> data_may_create_makes_lane_private_record_no_delete_line;
the stand's mark overriding the answer or granting a create -> data_answer_create_rules_on_stand_not_safe_to_break /
data_default_existing_only_on_stand_not_safe_to_break; an id of 300 characters cut in the list -> instance_odd_texts_kept_whole_cut_in_lines;
an obtain lane past `limit_by_role` -> limit_caps_obtain_lanes_at_and_beyond; a row assigned before its walk opened read dirty or free to
a second pass -> second_assignment_pass_keeps_the_given_instance; an id `*` written as a whole-list row -> star_instance_id_is_skipped_with_note.
"""
import json
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import config_contract as CC  # noqa: E402
import event_store as ES  # noqa: E402
import manual_capture as MC  # noqa: E402
import test_walk_lanes as L  # noqa: E402
import walk_pool as WP  # noqa: E402
import walk_session as WS  # noqa: E402

ROLES = {"user": ".env: QA_USER / QA_PASS - a user", "admin": ".env: AUTH_USERNAME / AUTH_PASSWORD - the admin",
         "reader": ".env: READER_USER / READER_PASS - a reader", "plain": "a note with no keys"}
SECRET_VALUES = ("VALUE-ADMIN-1", "VALUE-USER-2", "VALUE-USER2-3", "VALUE-USER3-4", "VALUE-READER-5")
ENV = ("AUTH_USERNAME=admin-a\nAUTH_PASSWORD=VALUE-ADMIN-1\nQA_USER=user-a\nQA_PASS=VALUE-USER-2\nQA_USER2=user-b\nQA_PASS2=VALUE-USER2-3\n"
       "QA_USER3=user-c\nQA_PASS3=VALUE-USER3-4\nREADER_USER=reader-a\nREADER_PASS=VALUE-READER-5\n")
X2, X3, GHOST = "env:QA_USER2/QA_PASS2", "env:QA_USER3/QA_PASS3", "env:GHOST_U/GHOST_P"
USER_KEY, ADMIN_KEY = "stand_account:user", "stand_account:admin"


class Proj:
    """A project with a real `qa-factory/config.json`, an env file and a story folder (the readers read real files)."""

    def __init__(self, tmp_path, safe_to_break=None, **config):
        self.root = tmp_path / "proj"
        self.task = self.root / "qa-factory" / "artifacts" / "QA-9"
        self.task.mkdir(parents=True)
        stand = {"name": "local", "credentials_by_role": ROLES, **({} if safe_to_break is None else {"safe_to_break": safe_to_break})}
        self.cfg = {"environment": {"env_file": ".env"}, "environments": [stand], **config}
        (self.root / "qa-factory" / "config.json").write_text(json.dumps(self.cfg), encoding="utf-8")
        (self.root / ".env").write_text(ENV, encoding="utf-8")

    def probe(self, *handles):
        recipe = MC.login_recipe(self.cfg, MC.spec(), "ui")
        path = self.task / "state" / "sign-in-probe.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({h: {"outcome": "ok", "recipe_sha": MC.recipe_sha(recipe)} for h in handles}), encoding="utf-8")

    def supply(self):
        return CC.walk_supply(self.cfg)[0]

    def pool(self, part, more=None, limit=None, doubts=None):
        supply = {"accounts": {"more_accounts": more or {}, "limit_by_role": limit or {}}}
        return WP.pool_of(self.task, self.cfg, "TC-1", part, supply, doubts if doubts is not None else (set(), ""))


def no_values(notes):
    text = " ".join(notes)
    assert not any(v in text for v in SECRET_VALUES) and "user-a" not in text and "admin-a" not in text, notes


def lanes_of(*cases):
    return [[c] for c in cases]


# --- lane_handles ---------------------------------------------------------------------------------------------------------------------

def test_driver_calls_walk_pool(tmp_path):
    """Part D step 1 (AR-15): `Driver.walk_actors` / `walk_env_pair` hold no body of their own - they call the pool's functions."""
    driver = L.make_driver(tmp_path)
    with mock.patch.object(WP, "lane_handles", return_value=(["x"], "")) as lane, mock.patch.object(WP, "walk_env_pair", return_value=("y", "")) as pair:
        assert driver.walk_actors("TC-1", "stand_account:admin") == (["x"], "")
        assert driver.walk_env_pair({}, "QA_USER") == ("y", "")
    assert lane.call_args.args[1:] == ("TC-1", "stand_account:admin") and pair.call_args.args == ({}, "QA_USER")


def test_obtain_cap_counts_the_role_across_two_parts():
    """R2: two parts that resolve to one role share ONE cap of `limit_by_role` (at the limit, one beyond it, with no limit)."""
    def lanes_for(limit):
        pools = {"stand_account:user": WP.Pool(["user"], "user", limit), "env:QA_USER": WP.Pool(["user"], "user", limit)}
        lanes = [["TC-1"], ["TC-2"], ["TC-3"], ["TC-4"]]
        keys = {"TC-1": "stand_account:user", "TC-2": "stand_account:user", "TC-3": "env:QA_USER", "TC-4": "env:QA_USER"}
        out, _notes = WP.assign_lanes(lanes, pools, ["user"], True, keys)
        return sum(1 for parts in out.values() for h in parts.values() if h.startswith("obtain:")), sum(1 for p in out.values() for h in p.values() if h == "user")
    assert lanes_for(2) == (1, 3)       # 1 pool lane + 1 obtain lane = the cap of 2; the other two lanes take the shared handle in turn
    assert lanes_for(3) == (2, 2)       # beyond the limit by one: 3 lanes at once
    assert lanes_for(0) == (2, 2)       # no limit: every lane past the pool takes its own user (the second part's first lane shares the pool handle)


def test_lane_handles_same_as_walk_actors(tmp_path):
    proj = Proj(tmp_path)
    cases = {"TC-1": ADMIN_KEY, "TC-2": "stand_account:default", "TC-3": "stand_account:ghost", "TC-4": "stand_account:plain"}
    for case, key in cases.items():
        L.write_request(proj.task, case, L.account(key.partition(":")[2]))
    driver = L.make_driver(proj.task)
    keys = ["env:QA_USER", "env:GHOST_KEY", "env:QA_USER+stand_account:user", ADMIN_KEY + "+" + USER_KEY, USER_KEY + "+" + ADMIN_KEY,
            "env:QA_USER+stand_account:ghost", ADMIN_KEY + "+" + USER_KEY + "+stand_account:reader", "", "+", "stand_account:default+" + ADMIN_KEY]
    for case, key in cases.items():
        keys.append(key)
    for key in keys:
        case = next((c for c, k in cases.items() if k == key), "TC-1")
        assert WP.lane_handles(proj.task, case, key) == driver.walk_actors(case, key), key
    bare = tmp_path / "nowhere"                                  # no config above the story: `{}`, one reason, the same text
    bare.mkdir()
    L.write_request(bare, "TC-1", L.account("admin"))
    twin = L.make_driver(bare)
    for key in ("stand_account:admin", "env:QA_USER", USER_KEY + "+" + ADMIN_KEY):
        assert WP.lane_handles(bare, "TC-1", key) == twin.walk_actors("TC-1", key), key
    assert WP.walk_env_pair(WP._stand_of(proj.cfg), "QA_USER") == driver.walk_env_pair(WP._stand_of(proj.cfg), "QA_USER") == ("user", "")
    assert WP.lane_handles(proj.task, "TC-1", USER_KEY + "+" + ADMIN_KEY) == (["user", "admin"], "")


# --- pool_of --------------------------------------------------------------------------------------------------------------------------

def test_pool_adds_more_accounts_existing_keys_only(tmp_path):
    proj = Proj(tmp_path)
    proj.probe(X2)
    pool, notes = proj.pool(USER_KEY, more={"user": [X2, GHOST]})
    assert list(pool) == ["user", X2] and pool.role == "user", (pool, notes)
    assert any("GHOST_U" in n and "not set in the env files" in n for n in notes), notes      # key NAMES only
    no_values(notes)
    assert proj.pool(ADMIN_KEY, more={"user": [X2]})[0] == ["admin"]                           # another role's extras are not its own
    assert proj.pool("stand_account:default", more={"default": [X2]})[0].role == "default"
    other = Proj(tmp_path / "second", environment={"env_file": "missing.env"})
    other.probe(X2)
    pool2, notes2 = other.pool(USER_KEY, more={"user": [X2]})
    assert list(pool2) == ["user"] and any("env files" in n for n in notes2), (pool2, notes2)   # no readable env file: no extra account


def test_pool_drops_doubted(tmp_path):
    proj = Proj(tmp_path)
    proj.probe(X2, X3)
    more = {"user": [X2, X3]}
    assert list(proj.pool(USER_KEY, more, doubts=({X2}, ""))[0]) == ["user", X3]
    assert list(proj.pool(USER_KEY, more, doubts=({"user"}, ""))[0]) == [X2, X3]                 # a doubted base leaves when something is better
    pool, notes = proj.pool(USER_KEY, doubts=({"user"}, ""))
    assert list(pool) == ["user"] and any("doubted" in n and "nothing better" in n for n in notes), (pool, notes)     # no extras: the base stays
    pool, notes = proj.pool(USER_KEY, more, doubts=({"user", X2, X3}, ""))
    assert list(pool) == ["user"] and notes, (pool, notes)                                       # everything doubted: the base, with a note


def test_pool_capped_by_limit(tmp_path):
    proj = Proj(tmp_path)
    proj.probe(X2, X3)
    pool, notes = proj.pool(USER_KEY, more={"user": [X2, X3]}, limit={"user": 2})
    assert list(pool) == ["user", X2] and any("cut to 2" in n for n in notes), (pool, notes)
    assert list(proj.pool(USER_KEY, more={"user": [X2, X3]}, limit={"user": 1})[0]) == ["user"]     # `limit_by_role: 1` with 3 accounts
    assert len(proj.pool(USER_KEY, more={"user": [X2, X3]}, limit={"user": 9})[0]) == 3
    assert len(proj.pool(USER_KEY, more={"user": [X2, X3]}, limit={"admin": 1})[0]) == 3         # another role's limit is not its own


def test_pool_dedupes_same_pair(tmp_path):
    proj = Proj(tmp_path)
    proj.probe("env:QA_USER/QA_PASS", X2)
    pool, notes = proj.pool(USER_KEY, more={"user": ["env:QA_USER/QA_PASS", X2, X2]})
    assert list(pool) == ["user", X2], (pool, notes)                      # the role's note names QA_USER/QA_PASS: ONE account
    assert any("same key pair" in n for n in notes), notes
    default, _ = proj.pool("stand_account:default", more={"default": ["env:AUTH_USERNAME/AUTH_PASSWORD"]})
    assert list(default) == ["default"]


def test_pool_keeps_only_ok_rows(tmp_path):
    proj = Proj(tmp_path)
    proj.probe(X3)                                                        # X2 has no row, the base has none either
    pool, notes = proj.pool(USER_KEY, more={"user": [X2, X3]})
    assert list(pool) == ["user", X3], (pool, notes)                      # the base is never dropped for a missing row (today's road asks none)
    assert any("no `ok` sign-in probe row" in n and "QA_USER2" in n for n in notes), notes
    path = proj.task / "state" / "sign-in-probe.json"
    recipe = MC.login_recipe(proj.cfg, MC.spec(), "ui")
    path.write_text(json.dumps({X3: {"outcome": "fail", "recipe_sha": MC.recipe_sha(recipe)}, X2: {"outcome": "ok", "recipe_sha": "other recipe"}}), encoding="utf-8")
    assert list(proj.pool(USER_KEY, more={"user": [X2, X3]})[0]) == ["user"]     # a failed row and a row of another recipe prove nothing
    path.write_text("{not json", encoding="utf-8")
    assert list(proj.pool(USER_KEY, more={"user": [X2, X3]})[0]) == ["user"]     # an unreadable file proves nothing


def test_doubts_unreadable_base_only(tmp_path):
    proj = Proj(tmp_path)
    proj.probe(X2)
    path = MC.account_doubts_path(proj.task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    doubts = MC.account_doubts(proj.task)
    assert doubts[0] == set() and doubts[1], doubts
    pool, notes = proj.pool(USER_KEY, more={"user": [X2]}, doubts=doubts)
    assert list(pool) == ["user"] and any("cannot be read" in n for n in notes), (pool, notes)       # no extra account is used on an unknown
    path.unlink()
    assert list(proj.pool(USER_KEY, more={"user": [X2]}, doubts=MC.account_doubts(proj.task))[0]) == ["user", X2]    # a missing file is no doubt


# --- assign_lanes ---------------------------------------------------------------------------------------------------------------------

def keyed(n, key):
    return {f"TC-{i}": key for i in range(1, n + 1)}


def test_assign_round_robin_deterministic(tmp_path):
    lanes = lanes_of(*(f"TC-{i}" for i in range(1, 6)))
    keys = keyed(5, USER_KEY)
    pools = {USER_KEY: WP.Pool(["user", "x", "y"], "user")}
    first, notes = WP.assign_lanes(lanes, pools, [], False, keys)
    assert [first[n][USER_KEY] for n in range(1, 6)] == ["user", "x", "y", "user", "x"], first
    assert WP.assign_lanes(lanes, pools, [], False, keys) == (first, notes)               # deterministic
    one, _ = WP.assign_lanes(lanes, {USER_KEY: WP.Pool(["user"], "user")}, [], False, keys)         # pool of 1 and 5 lanes: all in turn
    assert {one[n][USER_KEY] for n in one} == {"user"} and len(one) == 5
    proj = Proj(tmp_path)                       # `limit_by_role: 1` with 3 env accounts: the pool is one handle, every lane shares it (in turn)
    proj.probe(X2, X3)
    capped, _ = proj.pool(USER_KEY, more={"user": [X2, X3]}, limit={"user": 1})
    out, _ = WP.assign_lanes(lanes_of("TC-1", "TC-2", "TC-3"), {USER_KEY: capped}, [], False, keyed(3, USER_KEY))
    assert list(capped) == ["user"] and [out[n][USER_KEY] for n in (1, 2, 3)] == ["user"] * 3, out
    # C.7: a doubt with no extras keeps the base for every lane; lanes that carry no pool get NO handle (never a guess)
    bare, notes = WP.assign_lanes(lanes_of("TC-1", "TC-2"), {}, [], False, {"TC-1": USER_KEY, "TC-2": USER_KEY})
    assert bare == {1: {}, 2: {}} and notes, (bare, notes)
    unreadable, notes = WP.assign_lanes(lanes_of("TC-1", "TC-2"), pools, [], False, {"TC-1": USER_KEY})
    assert 2 not in unreadable and any("lane 2" in n for n in notes), (unreadable, notes)     # a lane whose key cannot be read gets no handle


def test_obtain_only_listed_role_and_changeable_stand():
    lanes = lanes_of("TC-1", "TC-2", "TC-3")
    keys = keyed(3, USER_KEY)
    pools = {USER_KEY: WP.Pool(["user"], "user")}
    got, _ = WP.assign_lanes(lanes, pools, ["user"], True, keys)
    assert [got[n][USER_KEY] for n in (1, 2, 3)] == ["user", "obtain:user#2", "obtain:user#3"], got
    for roles, may in ((["admin"], True), ([], True), (["user"], False)):     # not listed / nothing said / the stand may not be changed: none
        none, _ = WP.assign_lanes(lanes, pools, roles, may, keys)
        assert not any(h.startswith("obtain:") for n in none for h in none[n].values()), (roles, may, none)
    assert WP.open_as("obtain:user#2") == "guest" and WP.open_as("guest#4") == "guest" and WP.open_as("guest") == "guest"     # C.8
    assert WP.open_as("user") == "user" and WP.open_as("env:A/B") == "env:A/B"
    supply = {"accounts": {"self_sign_up_roles": ["user", "ghost", "default", "User"]}}
    roles, notes = WP.obtain_roles_of(supply, ROLES)
    assert roles == ["user", "default"] and any("ghost" in n for n in notes), (roles, notes)
    assert WP.obtain_roles_of({}, ROLES) == ([], []) and WP.obtain_roles_of(supply, None)[0] == ["default"]


def test_limit_caps_obtain_lanes_at_and_beyond(tmp_path):
    proj = Proj(tmp_path)
    lanes, keys = lanes_of("TC-1", "TC-2", "TC-3"), keyed(3, USER_KEY)

    def handles(limit):
        pool, _ = proj.pool(USER_KEY, limit={"user": limit} if limit else None)
        got, _ = WP.assign_lanes(lanes, {USER_KEY: pool}, ["user"], True, keys)
        return [got[n][USER_KEY] for n in (1, 2, 3)]
    assert handles(2) == ["user", "obtain:user#2", "user"]                     # AT the limit: 2 lanes run, the 3rd waits for the shared handle
    assert handles(1) == ["user", "user", "user"]                              # limit 1: no obtain lane at all, all three in turn
    assert handles(3) == ["user", "obtain:user#2", "obtain:user#3"]            # the limit is room for all three
    assert handles(0) == ["user", "obtain:user#2", "obtain:user#3"]            # no limit: as before
    assert len({h for h in handles(2) if h.startswith("obtain:")}) == 1


def test_two_part_key_same_round():
    both = ADMIN_KEY + "+" + USER_KEY
    keys = {"TC-1": both, "TC-2": both, "TC-3": both}
    pools = {ADMIN_KEY: WP.Pool(["admin", "admin2"], "admin"), USER_KEY: WP.Pool(["user", "user2"], "user")}
    got, _ = WP.assign_lanes(lanes_of("TC-1", "TC-2", "TC-3"), pools, [], False, keys)
    assert [(got[n][ADMIN_KEY], got[n][USER_KEY]) for n in (1, 2, 3)] == [("admin", "user"), ("admin2", "user2"), ("admin", "user")], got
    solo = {ADMIN_KEY: pools[ADMIN_KEY], USER_KEY: WP.Pool(["user"], "user")}      # a second part with a pool of 1: that handle is shared (in turn)
    got, _ = WP.assign_lanes(lanes_of("TC-1", "TC-2"), solo, [], False, keys)
    assert got[1][USER_KEY] == got[2][USER_KEY] == "user" and got[1][ADMIN_KEY] != got[2][ADMIN_KEY], got


def test_short_parts_only_when_not_known():
    lanes, keys = lanes_of("TC-1", "TC-2", "TC-3"), keyed(3, USER_KEY)
    pools = {USER_KEY: WP.Pool(["user"], "user")}
    shared, _ = WP.assign_lanes(lanes, pools, [], False, keys)
    unknown = {"accounts": {"known": False}}
    assert WP.short_parts(shared, pools, unknown, 3)[0] == [(USER_KEY, 2, 1)]
    assert WP.short_parts(shared, pools, unknown, 1)[0] == []                                   # one walker: nothing waits for a handle
    assert WP.short_parts(shared, pools, {"accounts": {"known": True}}, 3)[0] == []             # the person already answered
    obtained, _ = WP.assign_lanes(lanes, pools, ["user"], True, keys)
    assert WP.short_parts(obtained, pools, unknown, 3)[0] == []                                 # an obtain applies: no sharing
    roomy, _ = WP.assign_lanes(lanes, {USER_KEY: WP.Pool(["a", "b", "c"], "user")}, [], False, keys)
    assert WP.short_parts(roomy, pools, unknown, 3)[0] == []                                    # a handle each
    guests, _ = WP.assign_lanes(lanes_of("TC-1", "TC-2"), {}, [], False, {"TC-1": "", "TC-2": ""})
    assert WP.short_parts(guests, {}, unknown, 3)[0] == []                                      # guests share nothing


def test_guest_pool_one_per_lane(tmp_path):
    proj = Proj(tmp_path)
    assert list(WP.pool_of(proj.task, proj.cfg, "TC-1", "", {}, (set(), ""))[0]) == ["guest"]
    keys = {"TC-1": "", "TC-2": "", "TC-3": USER_KEY, "TC-4": ""}
    got, _ = WP.assign_lanes(lanes_of("TC-1", "TC-2", "TC-3", "TC-4"), {USER_KEY: WP.Pool(["user"], "user")}, [], False, keys)
    assert got[1] == {"": "guest#1"} and got[2] == {"": "guest#2"} and got[4] == {"": "guest#4"} and got[3] == {USER_KEY: "user"}, got
    assert len({got[n][""] for n in (1, 2, 4)}) == 3 and all(WP.open_as(got[n][""]) == "guest" for n in (1, 2, 4))


# --- assign_entities ------------------------------------------------------------------------------------------------------------------

def request(*kinds, exclusive=True):
    return {"walk_data": [{"kind": k, "exclusive": exclusive, "changes": "deletes one"} for k in kinds]}


def data_pools(**kinds):
    return {k: dict(v) for k, v in kinds.items()}


def live_walk(root, name, items=("TC-1",)):
    walk = WS.Walk(root, name, list(items), ["guest"], place="case")
    walk.state = "ready"
    walk.write_state()          # a record of THIS process: alive
    return walk


def rows_of(root):
    return WS.claims_of(root)[0]


def test_assign_entities_distinct_instances(tmp_path):
    lanes = lanes_of("TC-1", "TC-2", "TC-3")
    requests = {c: request("Book") for c in ("TC-1", "TC-2", "TC-3")}
    pools = data_pools(book={"existing": ["17", "18", "19"]})
    got, notes = WP.assign_entities(lanes, requests, pools, tmp_path, {1: "W1", 2: "W2", 3: "W3"})
    assert {n: got[n]["entries"][f"TC-{n}"][0]["instance"] for n in (1, 2, 3)} == {1: "17", 2: "18", 3: "19"}, (got, notes)
    assert all(got[n]["state"] == "given" for n in got)
    assert {(r["walk"], r["instance"], r["state"], r["kind"]) for r in rows_of(tmp_path)} == {("W1", "17", "in_use", "book"), ("W2", "18", "in_use", "book"),
                                                                                              ("W3", "19", "in_use", "book")}
    assert got[1]["entries"]["TC-1"][0]["kind"] == "Book"                                       # the plan's own word for the prompt, the row's folded
    held = {r["instance"]: r for r in rows_of(tmp_path)}["17"]
    assert WS.claim_problems(rows_of(tmp_path), {"kind": "book", "instance": "17", "walk": "W9"}, {"W1"}), held    # the walker's claim of it is refused


def test_assign_all_or_none_of_an_item(tmp_path):
    lanes = lanes_of("TC-1", "TC-2")
    requests = {"TC-1": request("book", "shelf"), "TC-2": request("book", "shelf")}
    pools = data_pools(book={"existing": ["17", "18"]}, shelf={"existing": ["s1"]})
    got, _ = WP.assign_entities(lanes, requests, pools, tmp_path, {1: "W1", 2: "W2"})
    assert got[1]["state"] == "given" and len(got[1]["entries"]["TC-1"]) == 2, got
    assert got[2]["state"] == "wait" and got[2]["entries"] == {}, got                           # no shelf left: NOT the book alone
    assert {(r["walk"], r["instance"]) for r in rows_of(tmp_path)} == {("W1", "17"), ("W1", "s1")}, rows_of(tmp_path)     # nothing of lane 2 written
    items = WP.assign_entities(lanes_of("TC-1"), {"TC-1": request("book", "ghost")}, pools, tmp_path / "other", {1: "W5"})[0]
    assert items[1]["entries"]["TC-1"][0]["instance"] == "17" and len(items[1]["entries"]["TC-1"]) == 1      # a kind with no pool is not constrained
    two = {"TC-1": {"walk_data": [{"kind": "book", "exclusive": True, "changes": "a"}, {"kind": " BOOK ", "exclusive": True, "changes": "b"}]}}
    again = WP.assign_entities(lanes_of("TC-1"), two, pools, tmp_path / "again", {1: "W6"})[0]
    assert len(again[1]["entries"]["TC-1"]) == 1, again                                         # one kind named twice is one record


def test_assign_pool_of_one_two_lanes_in_turn(tmp_path):
    lanes = lanes_of("TC-1", "TC-2")
    requests = {"TC-1": request("book"), "TC-2": request("book")}
    pools = data_pools(book={"existing": ["17"]})
    first = live_walk(tmp_path, "W1")
    got, _ = WP.assign_entities(lanes, requests, pools, tmp_path, {1: "W1", 2: "W2"})
    assert got[1]["state"] == "given" and got[2]["state"] == "wait", got
    assert [(r["walk"], r["instance"]) for r in rows_of(tmp_path)] == [("W1", "17")]            # never two `in_use` of one instance
    again, _ = WP.assign_entities(lanes_of("TC-2"), {"TC-2": request("book")}, pools, tmp_path, {1: "W2"})
    assert again[1]["state"] == "wait", again                                                   # still held by a live lane
    WS._release_claims(first, "TC-1", teardown=True)                                            # the first lane ended with its record restored
    third, _ = WP.assign_entities(lanes_of("TC-2"), {"TC-2": request("book")}, pools, tmp_path, {1: "W2"})
    assert third[1]["state"] == "given" and third[1]["entries"]["TC-2"][0]["instance"] == "17", third
    empty, notes = WP.assign_entities(lanes_of("TC-9"), {"TC-9": request("book")}, data_pools(book={"existing": []}), tmp_path / "e", {1: "W9"})
    assert empty[1]["state"] == "alone", (empty, notes)                                         # an empty pool: alone, as today


def test_second_assignment_pass_keeps_the_given_instance(tmp_path):
    requests = {"TC-1": request("book"), "TC-2": request("book")}
    first, _ = WP.assign_entities(lanes_of("TC-1"), requests, data_pools(book={"existing": ["17"]}), tmp_path, {1: "W1"})
    assert first[1]["state"] == "given"                                                         # W1's agent has not opened the walk: no record
    again, notes = WP.assign_entities(lanes_of("TC-2"), requests, data_pools(book={"existing": ["17"]}), tmp_path, {1: "W2"})
    assert again[1]["state"] == "wait", (again, notes)                                          # not `alone`: the row is held, not dirty
    assert "changed" not in again[1]["why"] and "not restored" not in again[1]["why"], again
    more, _ = WP.assign_entities(lanes_of("TC-2"), requests, data_pools(book={"existing": ["17", "18"]}), tmp_path, {1: "W2"})
    assert more[1]["entries"]["TC-2"][0]["instance"] == "18", more                              # W1 keeps 17
    assert {(r["walk"], r["instance"]) for r in rows_of(tmp_path)} == {("W1", "17"), ("W2", "18")}
    live_walk(tmp_path, "W1")                                                                   # the agent opens the walk: the live rule reads the row
    assert WP.assign_entities(lanes_of("TC-3"), {"TC-3": request("book")}, data_pools(book={"existing": ["17"]}), tmp_path, {1: "W3"})[0][1]["state"] == "wait"
    ended = WS.Walk(tmp_path, "W1", ["TC-1"], ["guest"], place="case")
    ended.state = "dead"
    ended.write_state()                                                                         # a record that is not alive: dirty, the lane runs alone
    assert WP.assign_entities(lanes_of("TC-3"), {"TC-3": request("book")}, data_pools(book={"existing": ["17"]}), tmp_path, {1: "W3"})[0][1]["state"] == "alone"


def test_star_instance_id_is_skipped_with_note(tmp_path):
    got, notes = WP.assign_entities(lanes_of("TC-1", "TC-2"), {c: request("book") for c in ("TC-1", "TC-2")}, data_pools(book={"existing": ["*", "17"]}),
                                    tmp_path, {1: "W1", 2: "W2"})
    assert got[1]["entries"]["TC-1"][0]["instance"] == "17" and got[2]["state"] == "wait", got
    assert any("`*`" in n and "skipped" in n for n in notes), notes
    assert {r["instance"] for r in rows_of(tmp_path)} == {"17"}                                 # no whole-list row is ever written
    only, _ = WP.assign_entities(lanes_of("TC-1"), {"TC-1": request("book")}, data_pools(book={"existing": ["*"]}), tmp_path / "o", {1: "W1"})
    assert only[1]["state"] == "alone", only


def test_assign_unreadable_store_runs_alone(tmp_path):
    path = WS.claims_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    lanes = lanes_of("TC-1", "TC-2")
    requests = {"TC-1": request("book"), "TC-2": request("book")}
    got, notes = WP.assign_entities(lanes, requests, data_pools(book={"existing": ["17", "18"]}), tmp_path, {1: "W1", 2: "W2"})
    assert {n: got[n]["state"] for n in got} == {1: "alone", 2: "alone"} and all(not got[n]["entries"] for n in got), got
    assert notes and "cannot be read" in got[1]["why"], (notes, got)
    assert path.read_text(encoding="utf-8") == "{not json"                                      # nothing written, nothing granted
    path.unlink()
    held = ES.take_file_lock(WS.claims_path(tmp_path).with_suffix(".lock"), 0, purpose="test holds it", record_holder=True)
    try:
        with mock.patch.object(WS, "CLAIM_LOCK_WAIT_S", 0.2):
            got, notes = WP.assign_entities(lanes, requests, data_pools(book={"existing": ["17"]}), tmp_path, {1: "W1", 2: "W2"})
    finally:
        held.release()
    assert all(got[n]["state"] == "alone" for n in got) and "held by another walker" in got[1]["why"], got       # a lock not got: alone
    assert not WS.claims_path(tmp_path).exists()


def test_assign_instance_written_in_use_before_dispatch(tmp_path):
    seen = []

    def dispatch(lane_n):                                            # the driver's order: assignment first, then each dispatch
        seen.append((lane_n, {(r["walk"], r["instance"], r["state"]) for r in rows_of(tmp_path)}))
    got, _ = WP.assign_entities(lanes_of("TC-1", "TC-2"), {"TC-1": request("book"), "TC-2": request("book")}, data_pools(book={"existing": ["17", "18"]}),
                                tmp_path, {1: "W1", 2: "W2"})
    for n in got:
        dispatch(n)
    assert all(rows == {("W1", "17", "in_use"), ("W2", "18", "in_use")} for _n, rows in seen) and len(seen) == 2, seen
    assert all(row["at"] and row["item"] in ("TC-1", "TC-2") for row in rows_of(tmp_path))
    nothing, _ = WP.assign_entities(lanes_of("TC-3"), {"TC-3": request("book")}, data_pools(book={"existing": ["17", "18", "19"]}), tmp_path, {})   # no walk id
    assert nothing[1]["state"] == "alone" and "no walk id" in nothing[1]["why"] and len(rows_of(tmp_path)) == 2


def test_no_walk_data_no_assignment(tmp_path):
    pools = data_pools(book={"existing": ["17"]})
    cases = ({}, {"TC-1": {}}, {"TC-1": {"walk_data": []}}, {"TC-1": request("book", exclusive=False)}, {"TC-1": {"walk_data": "book"}},
             {"TC-1": {"walk_data": [{"kind": "", "exclusive": True, "changes": "x"}]}}, {"TC-1": "not a request"}, {"TC-1": {"walk_global": "every book"}})
    for requests in cases:
        assert WP.assign_entities(lanes_of("TC-1"), requests, pools, tmp_path, {1: "W1"}) == ({}, []), requests
    assert not WS.claims_path(tmp_path).exists() and not WS.claims_path(tmp_path).with_suffix(".lock").exists()        # the store is never touched


def two_lane_create(tmp_path, pools, may):
    return WP.assign_entities(lanes_of("TC-1", "TC-2"), {"TC-1": request("book"), "TC-2": request("book")}, pools, tmp_path, {1: "W1", 2: "W2"}, may=may)


def test_data_may_existing_only_no_create_assignment(tmp_path):
    pools = data_pools(book={"existing": ["17"], "create_request": "POST /books", "delete_request": "DELETE /books/<id>"})
    got, _ = two_lane_create(tmp_path, pools, "existing_only")
    assert got[1]["state"] == "given" and got[2]["state"] == "wait" and got[2]["entries"] == {}, got      # no `create:` assignment: in turn
    alone, _ = WP.assign_entities(lanes_of("TC-1"), {"TC-1": request("book")}, data_pools(book={"existing": [], "create_request": "POST /books"}),
                                  tmp_path / "x", {1: "W1"}, may="existing_only")
    assert alone[1]["state"] == "alone", alone                                                   # nothing exists, nothing may be made: alone
    junk, _ = two_lane_create(tmp_path / "y", pools, "anything else")                          # an unknown answer reads existing_only
    assert junk[2]["state"] == "wait"


def test_data_may_create_makes_lane_private_record_no_delete_line(tmp_path):
    pools = data_pools(book={"existing": ["17"], "create_request": "POST /books", "delete_request": "DELETE /books/<id>"})
    got, _ = two_lane_create(tmp_path, pools, "create")
    entry = got[2]["entries"]["TC-2"][0]
    assert got[2]["state"] == "given" and entry["how"] == "create" and entry["handle"] == "create:book#2" and entry["create_request"] == "POST /books", got
    assert "delete_request" not in entry and not any("remove" in line for line in WP.entity_lines(got[2]["entries"])), got       # never delete
    assert [(r["walk"], r["instance"]) for r in rows_of(tmp_path)] == [("W1", "17")]            # a made record is the walker's to claim: nothing held for it
    assert any("POST /books" in line for line in WP.entity_lines(got[2]["entries"]))
    third = WP.assign_entities(lanes_of("TC-1", "TC-2", "TC-3"), {c: request("book") for c in ("TC-1", "TC-2", "TC-3")}, pools, tmp_path / "t",
                               {1: "W1", 2: "W2", 3: "W3"}, may="create")[0]
    assert third[2]["entries"]["TC-2"][0]["handle"] == "create:book#2" and third[3]["entries"]["TC-3"][0]["handle"] == "create:book#3"     # one each, never shared


def test_data_may_create_and_delete_carries_delete_request(tmp_path):
    pools = data_pools(book={"existing": ["17"], "create_request": "POST /books", "delete_request": "DELETE /books/<id>"})
    got, _ = two_lane_create(tmp_path, pools, "create_and_delete")
    entry = got[2]["entries"]["TC-2"][0]
    assert entry["delete_request"] == "DELETE /books/<id>", entry
    assert any("remove the record you made with: DELETE /books/<id>" in line for line in WP.entity_lines(got[2]["entries"]))
    no_delete = data_pools(book={"existing": ["17"], "create_request": "POST /books"})
    entry = two_lane_create(tmp_path / "n", no_delete, "create_and_delete")[0][2]["entries"]["TC-2"][0]
    assert entry["how"] == "create" and "delete_request" not in entry                           # a permission never becomes a request nobody gave (B.6)


def book_config(may=None, stand=None):
    way = {"words": "use books 17", "pools": {"book": {"existing": ["17"], "create_request": "POST /books", "delete_request": "DELETE /books/<id>"}}}
    if may is not None:
        way["may"] = may
    return way


def assign_from_config(proj):
    supply = proj.supply()["data"]
    return WP.assign_entities(lanes_of("TC-1", "TC-2"), {"TC-1": request("book"), "TC-2": request("book")}, supply["pools"], proj.task, {1: "W1", 2: "W2"},
                              may=supply["may"]), supply


def test_data_may_default_before_answer_is_existing_only(tmp_path):
    proj = Proj(tmp_path, manual={"data_way": book_config()})
    (got, _), supply = assign_from_config(proj)
    assert supply["may"] == "existing_only" and supply["may_known"] is False and "create_request" not in supply["pools"]["book"], supply
    assert got[2]["state"] == "wait" and not any(e["how"] == "create" for n in got for es in got[n]["entries"].values() for e in es), got


def test_data_answer_create_rules_on_stand_not_safe_to_break(tmp_path):
    for i, (sentence, delete) in enumerate((("may create, never delete", False), ("may create and delete", True))):
        proj = Proj(tmp_path / f"answer{i}", safe_to_break=False, manual={"data_way": book_config(sentence)})
        (got, _), supply = assign_from_config(proj)
        entry = got[2]["entries"]["TC-2"][0]
        assert supply["may_known"] is True and entry["how"] == "create" and ("delete_request" in entry) is delete, (got, supply)   # the mark never overrides the answer
        assert MC._stand_may_change(WP._stand_of(proj.cfg)) is False


def test_data_default_existing_only_on_stand_not_safe_to_break(tmp_path):
    for i, mark in enumerate((False, True, "yes, local only")):          # the mark alone grants nothing, whatever it says
        proj = Proj(tmp_path / f"mark{i}", safe_to_break=mark, manual={"data_way": book_config()})
        (got, _), supply = assign_from_config(proj)
        assert got[2]["state"] == "wait" and supply["may"] == "existing_only", (mark, got)
    stand_off = Proj(tmp_path / "off", safe_to_break=False, manual={"data_way": book_config("not an answer at all")})
    (got, _), supply = assign_from_config(stand_off)
    assert supply["may"] == "existing_only" and supply["may_known"] is False and got[2]["state"] == "wait", (got, supply)


def test_instance_odd_texts_kept_whole_cut_in_lines(tmp_path):
    odd = ["a/b\"c'd", "x" * 300, "plain"]
    got, _ = WP.assign_entities(lanes_of("TC-1", "TC-2", "TC-3"), {c: request("k" * 250) for c in ("TC-1", "TC-2", "TC-3")},
                                data_pools(**{"k" * 250: {"existing": odd}}), tmp_path, {1: "W1", 2: "W2", 3: "W3"})
    assert [got[n]["entries"][f"TC-{n}"][0]["instance"] for n in (1, 2, 3)] == odd, got             # kept as given in the entry and the list
    assert {r["instance"] for r in rows_of(tmp_path)} == set(odd)
    lines = " ".join(WP.entity_lines(got[2]["entries"]))
    assert ("x" * 200) in lines and ("x" * 201) not in lines and ("k" * 200) in lines and ("k" * 201) not in lines, lines
    assert "a/b\"c'd" in " ".join(WP.entity_lines(got[1]["entries"]))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
