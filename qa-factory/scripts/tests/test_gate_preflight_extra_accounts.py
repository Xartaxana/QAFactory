#!/usr/bin/env python3
"""TR3-10 D8 (t-2284): gate A also probes the project's EXTRA accounts (`manual.accounts_way.more_accounts`), fast and self-contained.

The rig is the gate-A sign-in probe rig of `test_gate_preflight.py` (fake browser, real files in a temp project); this file is fast, the
neighbour is on the slow list and is not run locally. Mutation -> the ONE test that kills it: an extra never probed ->
extra_account_probed_at_gate_a; a failed extra turned into a question or left an `ok` row -> extra_account_failure_dropped_from_pool_no_question;
an absent / empty / non-mapping block probing or noting anything -> no_extra_block_is_todays_behaviour; an extra of a role no case names probed ->
extra_of_a_role_no_case_names_not_probed; an extra equal to the base account, or listed twice, probed twice -> extra_equal_to_base_or_listed_twice_probed_once;
an unreadable supply read as a refusal -> unreadable_supply_no_extra_probe_no_refusal; a handle printed in a note -> handle_never_printed.
`pool_keeps_only_ok_rows` (the pool side of the invariant) lives in `test_walk_pool.py`.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import config_contract as CC  # noqa: E402
import test_gate_preflight as TG  # noqa: E402
import walk_pool as WP  # noqa: E402

X1_EMAIL, X2_EMAIL = "extra-one@example.invalid", "extra-two@example.invalid"
X1, X2 = "env:EXTRA_ONE_EMAIL/EXTRA_ONE_PASSWORD", "env:EXTRA_TWO_EMAIL/EXTRA_TWO_PASSWORD"
BASE_PAIR = "env:USER_EMAIL/USER_PASSWORD"          # the keys the role `user` of the probe story names
ENV = [f"EXTRA_ONE_EMAIL={X1_EMAIL}", "EXTRA_ONE_PASSWORD=pw-x1-not-printed", f"EXTRA_TWO_EMAIL={X2_EMAIL}", "EXTRA_TWO_PASSWORD=pw-x2-not-printed"]
USER_KEY = "stand_account:user"


def _story(cases, manual):
    lines = ["AUTH_USERNAME=admin@example.invalid", "AUTH_PASSWORD=not-printed-1"] + [f"{k}=x" for k in TG.CMP2_EXTRA_KEYS] + [
        f"USER_EMAIL={TG.PROBE_USER}", "USER_PASSWORD=pw-user-not-printed", f"ADMIN_EMAIL={TG.PROBE_ADMIN}", "ADMIN_PASSWORD=pw-admin-not-printed"] + ENV

    def edit(cfg):
        if manual is not None:
            cfg["manual"] = manual
    return TG._probe_story(cases, config=edit, env_lines=lines)


def _more(**roles):
    return {"accounts_way": {"more_accounts": roles}}


def _go(root, lands):
    world = TG._ProbeWorld(lands=lands)
    result = TG._probe_run(root, world)
    return result, TG._probe_rows(root), world


def _probe_texts(result):
    return json.dumps([f for f in result["findings"] if f["check"] == "actor_sign_in"]) + json.dumps(
        [i for i in result["info"] if i["check"] == "actor_sign_in"])


def test_extra_account_probed_at_gate_a():
    root = _story([(1, "user")], _more(user=[X1, X2]))
    try:
        result, rows, world = _go(root, (TG.PROBE_USER, X1_EMAIL, X2_EMAIL))
        assert TG.by_check(result, "actor_sign_in") == [], result["findings"]
        assert sorted(rows) == sorted(["user", X1, X2]) and all(row["outcome"] == "ok" for row in rows.values()), rows
        assert sorted(world.logins) == sorted([TG.PROBE_USER, X1_EMAIL, X2_EMAIL]), world.logins      # one sign-in per account, own keys
        assert (world.opened, world.closed) == (3, 3)
        task = root / "qa-factory" / "artifacts" / TG.CMP2_TICKET
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        pool, _notes = WP.pool_of(task, cfg, "TS-1", USER_KEY, CC.walk_supply(cfg)[0], (set(), ""))
        assert list(pool) == ["user", X1, X2], pool                          # the reader of the pool sees the extras' `ok` rows
        assert "pw-" not in json.dumps(rows) + _probe_texts(result)
    finally:
        TG.cleanup(root)


def test_extra_account_failure_dropped_from_pool_no_question():
    root = _story([(1, "user")], _more(user=[X1, X2]))
    try:
        result, rows, _world = _go(root, (TG.PROBE_USER, X2_EMAIL))           # the stand refuses X1 only
        assert TG.by_check(result, "actor_sign_in") == [], result["findings"]               # no question, no finding of any class
        notes = [i["message"] for i in result["info"] if i["check"] == "actor_sign_in"]
        assert len(notes) == 1 and "extra account 1 of the role user" in notes[0] and "dropped from the pool" in notes[0], notes
        assert rows["user"]["outcome"] == "ok" and rows[X2]["outcome"] == "ok" and rows[X1]["outcome"] == "failed", rows
        task = root / "qa-factory" / "artifacts" / TG.CMP2_TICKET
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        pool, _notes = WP.pool_of(task, cfg, "TS-1", USER_KEY, CC.walk_supply(cfg)[0], (set(), ""))
        assert list(pool) == ["user", X2], pool                              # a failed extra never reaches a lane
        # the base account failing too: its question stays exactly as it was (one finding, the person's), the extra adds nothing
        result, rows, _world = _go(root, (X1_EMAIL,))
        found = TG.by_check(result, "actor_sign_in")
        assert len(found) == 1 and found[0]["class"] == TG.gate_preflight.PERSON_DECIDES and "the account user" in found[0]["message"], found
        assert rows["user"]["outcome"] == "failed" and rows[X1]["outcome"] == "ok" and rows[X2]["outcome"] == "failed", rows
    finally:
        TG.cleanup(root)


def test_extra_account_other_failures_are_notes_too():
    # keys not set, a browser that cannot open, a form that is not on the page: each a note + dropped, never a question
    root = _story([(1, "user")], _more(user=["env:GHOST_ONE/GHOST_TWO"]))
    try:
        result, rows, world = _go(root, (TG.PROBE_USER,))
        assert TG.by_check(result, "actor_sign_in") == [] and rows["user"]["outcome"] == "ok", (result["findings"], rows)
        assert rows["env:GHOST_ONE/GHOST_TWO"]["outcome"] == "not_proved" and world.logins == [TG.PROBE_USER]
        assert any("keys are not set" in i["message"] for i in result["info"]), result["info"]
    finally:
        TG.cleanup(root)
    root = _story([(1, "user")], _more(user=[X1]))
    try:
        world = TG._ProbeWorld(form_missing=True)
        result = TG._probe_run(root, world)
        found = TG.by_check(result, "actor_sign_in")
        assert [f["message"] for f in found if "extra account" in f["message"]] == [], found      # the base's own finding is as today
        assert any("extra account 1" in i["message"] and "dropped" in i["message"] for i in result["info"]), result["info"]
    finally:
        TG.cleanup(root)


def test_no_extra_block_is_todays_behaviour():
    baseline = None
    for label, manual in (("manual absent", None), ("accounts_way absent", {}), ("more_accounts absent", {"accounts_way": {}}),
                          ("more_accounts empty", _more()), ("more_accounts a list", {"accounts_way": {"more_accounts": [X1]}}),
                          ("more_accounts a text", {"accounts_way": {"more_accounts": "env:A/B"}}),
                          ("role entry not a list", _more(user=X1))):
        root = _story([(1, "user")], manual)
        try:
            result, rows, world = _go(root, (TG.PROBE_USER, X1_EMAIL))
            seen = (sorted(rows), [i["message"] for i in result["info"] if i["check"] == "actor_sign_in"], world.logins)
            assert seen == (["user"], [], [TG.PROBE_USER]), (label, seen)         # no extra probe, no note
            assert TG.by_check(result, "actor_sign_in") == [], label
            baseline = baseline or seen
            assert seen == baseline, label
        finally:
            TG.cleanup(root)


def test_extra_of_a_role_no_case_names_not_probed():
    root = _story([(1, "user")], _more(admin=[X1], user=[X2]))
    try:
        result, rows, world = _go(root, (TG.PROBE_USER, TG.PROBE_ADMIN, X1_EMAIL, X2_EMAIL))
        assert sorted(rows) == sorted(["user", X2]), rows                     # X1 belongs to `admin`, which no manual case names
        assert X1_EMAIL not in world.logins and TG.by_check(result, "actor_sign_in") == []
    finally:
        TG.cleanup(root)


def test_extra_equal_to_base_or_listed_twice_probed_once():
    root = _story([(1, "user"), (2, "admin")], _more(user=[BASE_PAIR, X1, X1], admin=[X1]))
    try:
        result, rows, world = _go(root, (TG.PROBE_USER, TG.PROBE_ADMIN, X1_EMAIL))
        assert sorted(rows) == sorted(["user", "admin", X1]), rows            # the base's own key pair is not a second account
        assert world.logins.count(X1_EMAIL) == 1 and world.logins.count(TG.PROBE_USER) == 1, world.logins
        assert TG.by_check(result, "actor_sign_in") == []
    finally:
        TG.cleanup(root)


def test_unreadable_supply_no_extra_probe_no_refusal():
    for label, manual in (("manual not an object", "x"), ("accounts_way not an object", {"accounts_way": "x"}),
                          ("one bad entry, no good one", _more(user=["not-an-env-handle", 5, None]))):
        root = _story([(1, "user")], manual)
        try:
            result, rows, world = _go(root, (TG.PROBE_USER, X1_EMAIL))
            assert sorted(rows) == ["user"] and world.logins == [TG.PROBE_USER], (label, rows)
            assert TG.by_check(result, "actor_sign_in") == [] and not [i for i in result["info"] if i["check"] == "actor_sign_in"], label
        finally:
            TG.cleanup(root)


def test_handle_never_printed():
    secret = "env:USER_KEY/password: 'abcdefghijklmnop1234'"                 # the reader drops it: never probed, never printed
    root = _story([(1, "user")], _more(user=[secret, X1]))
    try:
        result, rows, _world = _go(root, (TG.PROBE_USER,))                   # X1 fails: its note names the role and the position
        text = _probe_texts(result)
        assert "abcdefghijklmnop1234" not in text and "EXTRA_ONE" not in text and X1_EMAIL not in text, text
        assert "abcdefghijklmnop1234" not in json.dumps(rows)
        assert "extra account 1 of the role user" in text
    finally:
        TG.cleanup(root)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
