#!/usr/bin/env python3
"""t-2174 TR3-10b: `manual.accounts_way` / `manual.data_way` and THE reader `config_contract.walk_supply` (AR-3, AR-13, AR-16, AR-28).

Keys: an absent block, an absent key and no config read the defaults with no note; a bad value reads its default with one note that
names the key (never a secret text); `known` is a recorded answer; `data.may` is one of three sentences and `existing_only` with
`may_known: False` otherwise, and the pools carry only the requests the answer allows; the reader never raises; the three price keys
of the walker questions are data with three options each; the conductor's way rows state merge on write and keep key NAMES only.

Mutations this file kills: a `known` that reads the default text as an answer | a secret text copied into a note | `may` read from a
free sentence | a pool request carried past the answer that does not allow it | `walk_supply` consulting `safe_to_break` | the one
reader duplicated (grep of `accounts_way` in scripts/*.py).

Run: python -B scripts/tests/test_walk_supply_config.py    or    python -m pytest -p no:cacheprovider scripts/tests/test_walk_supply_config.py -q
"""
import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import pytest  # noqa: E402
import config_contract as C  # noqa: E402

REFS = HERE.parents[1] / "references"
SECRET = "password: 'abcdefghijklmnop1234'"          # matches a default secret_content_patterns entry
SECRET_ENTRY = "env:USER_KEY/password: 'abcdefghijklmnop1234'"
THREE = ("only use what exists", "may create, never delete", "may create and delete")


def cfg(manual) -> dict:
    return {"secret_content_patterns": C.canonical_template()["secret_content_patterns"], "manual": manual}


def supply(manual):
    return C.walk_supply(cfg(manual))


def prices(key: str) -> list:
    return json.loads((REFS / "question-prices.json").read_text(encoding="utf-8-sig"))["questions"][key]


def test_absent_all_defaults_not_known():
    expected = {"accounts": {"words": "not known", "known": False, "self_sign_up_roles": [], "more_accounts": {}, "limit_by_role": {}},
                "data": {"words": "not known", "known": False, "pools": {}, "may": "existing_only", "may_known": False}}
    for config in (None, {}, [], {"manual": {"walkers": 2}}, cfg({"accounts_way": {}, "data_way": {}})):
        value, notes = C.walk_supply(config)
        assert value == expected and notes == [], (config, value, notes)
    template = C.canonical_template()
    assert C.walk_supply(template) == (expected, []), "the template's own defaults read as not known, no note (B.1)"
    old = {k: v for k, v in template.items() if k not in ("manual", "manual_supply_note")}
    plan = C.migration_plan(old)
    value, notes = C.walk_supply(plan["proposed_config"])
    assert value == expected and notes == [] and not value["accounts"]["known"] and not value["data"]["may_known"]


def test_manual_not_object_note():
    for bad in ("x", 3, None, ["a"], True):
        value, notes = C.walk_supply({"manual": bad})
        assert value == C.walk_supply({})[0] and len(notes) == 1 and "manual is not an object" in notes[0], (bad, notes)
    value, notes = supply({"accounts_way": "words", "data_way": ["x"]})
    assert value == C.walk_supply({})[0] and len(notes) == 2 and "manual.accounts_way is not an object" in notes[0], notes


def test_words_blank_not_known():
    for bad in ("", "   ", "\n", 5, None, ["x"], {"a": 1}):
        value, notes = supply({"accounts_way": {"words": bad}, "data_way": {"words": bad}})
        assert value["accounts"]["words"] == "not known" and value["accounts"]["known"] is False, bad
        assert value["data"]["words"] == "not known" and value["data"]["known"] is False, bad
        assert len(notes) == 2 and "manual.accounts_way.words" in notes[0] and "manual.data_way.words" in notes[1], notes
    for literal in ("not known", "  Not Known ", "NOT KNOWN"):
        value, notes = supply({"accounts_way": {"words": literal}})
        assert value["accounts"]["known"] is False and notes == [], literal


def test_words_answered_known():
    said = "  the app makes them on its sign-up page\nand there is one more in the env file "
    value, notes = supply({"accounts_way": {"words": said}, "data_way": {"words": "use what is there"}})
    assert value["accounts"]["words"] == said, "the words are returned whole, not stripped"
    assert value["accounts"]["known"] is True and value["data"]["known"] is True and notes == []
    assert value["accounts"]["self_sign_up_roles"] == [] and value["accounts"]["more_accounts"] == {}, "B.2: nothing created from words"
    assert value["data"]["pools"] == {} and value["data"]["may_known"] is False


def test_self_sign_up_bad_shape_note():
    value, notes = supply({"accounts_way": {"words": "w", "self_sign_up": {"roles": ["default", " admin ", "admin", "ghost"]}}})
    assert value["accounts"]["self_sign_up_roles"] == ["default", "admin", "ghost"] and notes == [], "B.4: an unknown role is kept"
    for bad in ("x", ["default"], {"roles": "default"}, {"roles": ["a", ""]}, {"roles": [1]}, {"roles": None}, {"other": 1}):
        value, notes = supply({"accounts_way": {"words": "w", "self_sign_up": bad}})
        assert value["accounts"]["self_sign_up_roles"] == [] and len(notes) == 1 and "self_sign_up" in notes[0], (bad, notes)


def test_more_accounts_bad_handle_dropped():
    good = "env:QA_SECOND_USER/QA_SECOND_PASS"
    bad = ["QA_SECOND_USER/QA_SECOND_PASS", "env:ONLY_ONE", "env:A/B/C", "env:1A/B", "env:/B", "env:A/", 7, None, ["env:A/B"], "default"]
    value, notes = supply({"accounts_way": {"more_accounts": {"admin": [good] + bad, "user": [bad[0]], "x": "env:A/B", "": [good]}}})
    assert value["accounts"]["more_accounts"] == {"admin": [good]}, value
    assert len(notes) == len(bad) + 1 + 1 + 1, notes
    assert all("`admin`" in n or "`user`" in n or "`x`" in n or "no role name" in n for n in notes), notes
    value, notes = supply({"accounts_way": {"more_accounts": ["env:A/B"]}})
    assert value["accounts"]["more_accounts"] == {} and len(notes) == 1


def test_more_accounts_secret_dropped_not_printed():
    value, notes = supply({"accounts_way": {"more_accounts": {"admin": [SECRET_ENTRY, "env:OK_USER/OK_PASS"]}}})
    assert value["accounts"]["more_accounts"] == {"admin": ["env:OK_USER/OK_PASS"]}, value
    assert len(notes) == 1 and "`admin`" in notes[0], notes
    printed = json.dumps([value, notes])
    assert "abcdefghijklmnop1234" not in printed and "password:" not in printed, printed


def test_limit_bad_values_dropped():
    value, notes = supply({"accounts_way": {"limit_by_role": {"a": 0, "b": "2", "c": True, "d": 2.5, "e": 2, "f": -1, "g": None, "h": 1}}})
    assert value["accounts"]["limit_by_role"] == {"e": 2, "h": 1}, value
    assert len(notes) == 6 and all("limit_by_role" in n for n in notes), notes
    for bad in ("x", [1], 3):
        value, notes = supply({"accounts_way": {"limit_by_role": bad}})
        assert value["accounts"]["limit_by_role"] == {} and len(notes) == 1, bad


def test_never_raises_on_garbage():
    garbage = [None, 0, "x", [], [[]], {"manual": {"accounts_way": {"more_accounts": {"a": [object()]}}}},
               {"manual": {"data_way": {"pools": {"k": {"existing": [{}], "create_request": 5}}, "may": ["x"]}}},
               {"manual": {"accounts_way": {"limit_by_role": {"a": float("nan")}, "self_sign_up": {"roles": [None]}}}},
               {"manual": {"data_way": {"pools": {1: {"existing": ["a"]}}}}}, {"manual": {1: 2}},
               {"secret_content_patterns": ["("], "manual": {"accounts_way": {"more_accounts": {"a": ["env:A/B"]}}}},
               {"secret_content_patterns": "x", "manual": {"data_way": {"pools": {"k": {"existing": ["a"]}}}}}]
    for config in garbage:
        value, notes = C.walk_supply(config)
        assert set(value) == {"accounts", "data"} and isinstance(notes, list), config
    # a failure inside reads the defaults with ONE note naming the exception class
    original = C._supply_accounts
    try:
        def boom(*args):
            raise KeyError("x")
        C._supply_accounts = boom
        value, notes = supply({"accounts_way": {"words": "w"}})
    finally:
        C._supply_accounts = original
    assert value == C._supply_defaults() and len(notes) == 1 and "KeyError" in notes[0], notes
    # a pattern that does not compile is named in ONE note (never silently skipped), the entry is still shape-checked
    value, notes = C.walk_supply({"secret_content_patterns": ["(", "[", "ok"], "manual": {"accounts_way": {"more_accounts": {"a": ["env:A/B"]}}}})
    assert value["accounts"]["more_accounts"] == {"a": ["env:A/B"]}
    assert len(notes) == 1 and "secret_content_patterns[0, 1]" in notes[0] and "does not compile" in notes[0], notes


def test_secret_in_dict_words_not_printed():
    for bad in ({"n": SECRET}, [SECRET], 5):
        value, notes = supply({"accounts_way": {"words": bad}, "data_way": {"words": bad}})
        assert len(notes) == 2 and type(bad).__name__ in notes[0], notes
        assert "abcdefghijklmnop1234" not in json.dumps([value, notes]) and "password" not in json.dumps(notes), notes


def test_default_patterns_hold_when_config_list_empty():
    pools = {"order": {"existing": ["o1", SECRET], "create_request": SECRET, "delete_request": "drop it"}}
    manual = {"accounts_way": {"more_accounts": {"admin": [SECRET_ENTRY]}}, "data_way": {"may": "may create and delete", "pools": pools}}
    for patterns in ([], None, "x", [7]):
        config = {"manual": manual} if patterns is None else {"secret_content_patterns": patterns, "manual": manual}
        value, notes = C.walk_supply(config)
        assert value["data"]["pools"] == {"order": {"existing": ["o1"], "delete_request": "drop it"}}, (patterns, value)
        assert value["accounts"]["more_accounts"] == {}, patterns
        assert "abcdefghijklmnop1234" not in json.dumps([value, notes]), (patterns, notes)
    # a project pattern is added on top of the defaults
    value, notes = C.walk_supply({"secret_content_patterns": ["TOPSECRET"], "manual": {"data_way": {"pools": {"o": {"existing": ["TOPSECRET1", "a"]}}}}})
    assert value["data"]["pools"] == {"o": {"existing": ["a"]}} and "TOPSECRET" not in json.dumps(notes), notes


def test_prices_key_present_three_options():
    rows = prices("s6.walk_supply")
    got = {r["answer"]: (r["factory"], r["person"], r["delivery"]) for r in rows}
    assert got == {"the app makes them": ("record", "none", "unchanged"), "one at a time": ("record", "none", "unchanged"),
                   "I will add accounts": ("record", "your_work", "unchanged")}, got
    assert len(rows) == 3


def test_prices_walk_account_three_options():
    rows = prices("s6.walk_account")
    got = {r["answer"]: (r["factory"], r["person"], r["delivery"]) for r in rows}
    assert got == {"added": ("record", "your_work", "waits"), "by hand": ("record", "your_checks", "not_known"),
                   "go on": ("record", "none", "no")}, got
    assert [r["answer"] for r in rows] == ["added", "by hand", "go on"]
    by = {r["answer"]: r for r in rows}
    assert by["by hand"]["unverified"] and by["go on"]["unverified"] and "unverified" not in by["added"]
    assert "the cases named" in by["by hand"]["unverified"] and "the cases named" in by["go on"]["unverified"]


def test_prices_data_change_three_options():
    rows = prices("s6.data_change")
    assert [r["answer"] for r in rows] == list(THREE)
    assert all((r["factory"], r["person"], r["delivery"]) == ("record", "none", "unchanged") for r in rows)
    assert set(C.DATA_MAY_OPTIONS) == set(THREE), "the reader's sentences are the prices' answers"
    actions = json.loads((REFS / "conductor-actions.json").read_text(encoding="utf-8-sig"))
    words = set(json.loads((REFS / "delivery-verdict-kinds.json").read_text(encoding="utf-8-sig"))["words"])
    classes = actions["price_classes"]
    for key in ("s6.walk_supply", "s6.walk_account", "s6.data_change"):          # the K15 rule: classes exist, delivery is in exactly one set
        for r in prices(key):
            assert r["factory"] in classes["factory"] and r["person"] in classes["person"], (key, r)
            assert (r["delivery"] in classes["delivery"]) != (r["delivery"] in words), (key, r)


def test_pools_bad_shape_dropped_note():
    for bad in ("x", ["a"], 3, None):
        value, notes = supply({"data_way": {"pools": bad}})
        assert value["data"]["pools"] == {} and len(notes) == 1 and "manual.data_way.pools" in notes[0], bad
    pools = {"order": {"existing": ["o1", "o2", "o1", ""]}, "empty": {"existing": []}, "badkind": "x", "norequest": {"delete_request": "r"},
             "wrongtype": {"existing": "o1"}, "ok": {"existing": ["a"], "create_request": "POST /x", "delete_request": 5}, "": {"existing": ["z"]}}
    value, notes = supply({"data_way": {"may": "may create and delete", "pools": pools}})
    assert value["data"]["pools"] == {"order": {"existing": ["o1", "o2"]}, "ok": {"existing": ["a"], "create_request": "POST /x"}}, value
    named = "\n".join(notes)
    for kind in ("empty", "badkind", "norequest", "wrongtype", "ok", "order"):
        assert f"`{kind}`" in named, (kind, notes)


def test_pools_kind_casefold():
    pools = {"  Order ": {"existing": ["o1"]}, "ORDER": {"existing": ["o2", "o1"], "create_request": "make it"}}
    value, notes = supply({"data_way": {"may": "may create, never delete", "pools": pools}})
    assert value["data"]["pools"] == {"order": {"existing": ["o1", "o2"], "create_request": "make it"}}, value
    assert notes == []


def test_pools_casefold_collision_differing_request_noted():
    pools = {"Order": {"existing": ["o1"], "create_request": "POST /books"}, "order": {"existing": ["o2"], "create_request": "DELETE /everything"},
             "ORDER ": {"existing": [], "create_request": "POST /books"}}
    value, notes = supply({"data_way": {"may": "may create, never delete", "pools": pools}})
    assert value["data"]["pools"] == {"order": {"existing": ["o1", "o2"], "create_request": "POST /books"}}, value
    assert len(notes) == 1 and "`order`" in notes[0] and "`create_request`" in notes[0] and "first is kept" in notes[0], notes
    assert "DELETE" not in notes[0] and "books" not in notes[0], "the kind is named, never the request text"


def test_pools_instance_secret_dropped_not_printed():
    pools = {"order": {"existing": ["o1", SECRET], "create_request": SECRET, "delete_request": "drop it"}}
    value, notes = supply({"data_way": {"may": "may create and delete", "pools": pools}})
    assert value["data"]["pools"] == {"order": {"existing": ["o1"], "delete_request": "drop it"}}, value
    assert len(notes) == 2 and all("`order`" in n for n in notes), notes
    printed = json.dumps([value, notes])
    assert "abcdefghijklmnop1234" not in printed and "password:" not in printed, printed
    only = {"order": {"existing": [SECRET]}}
    value, notes = supply({"data_way": {"pools": only}})
    assert value["data"]["pools"] == {} and "abcdefghijklmnop1234" not in json.dumps(notes), notes


def test_may_default_before_answer_is_existing_only():
    pools = {"order": {"existing": ["o1"], "create_request": "make", "delete_request": "drop"}}
    for manual in ({"data_way": {"pools": pools}}, {"data_way": {"may": "not known", "pools": pools}}):
        value, notes = supply(manual)
        assert value["data"]["may"] == "existing_only" and value["data"]["may_known"] is False, value
        assert value["data"]["pools"] == {"order": {"existing": ["o1"]}}, "B.6: no request carried before the answer"
        assert len(notes) == 1 and "`create_request` of `order`" in notes[0] and "`delete_request` of `order`" in notes[0], notes


def test_may_each_option_effect_on_pools():
    pools = {"order": {"existing": ["o1"], "create_request": "make", "delete_request": "drop"},
             "cart": {"existing": ["c1"], "create_request": "make cart"}, "tag": {"existing": ["t1"]}}
    got = {}
    for sentence, may in (("only use what exists", "existing_only"), ("may create, never delete", "create"),
                          ("  May Create And Delete ", "create_and_delete")):
        value, notes = supply({"data_way": {"may": sentence, "pools": copy.deepcopy(pools)}})
        assert value["data"]["may"] == may and value["data"]["may_known"] is True, (sentence, value)
        got[may] = (value["data"]["pools"], notes)
    assert got["existing_only"][0] == {"order": {"existing": ["o1"]}, "cart": {"existing": ["c1"]}, "tag": {"existing": ["t1"]}}
    assert len(got["existing_only"][1]) == 1, "ONE note naming every withheld kind and field (spec B)"
    note = got["existing_only"][1][0]
    assert "`create_request` of `cart`" in note and "`create_request` of `order`" in note and "`delete_request` of `order`" in note, note
    assert got["create"][0] == {"order": {"existing": ["o1"], "create_request": "make"},
                                "cart": {"existing": ["c1"], "create_request": "make cart"}, "tag": {"existing": ["t1"]}}
    assert len(got["create"][1]) == 1 and "delete_request" in got["create"][1][0] and "`order`" in got["create"][1][0]
    assert got["create_and_delete"] == (pools | {"tag": {"existing": ["t1"]}}, []), "all kept; a kind without delete_request carries none (B.6)"


def test_may_bad_value_not_known_note():
    for bad in ("sure, go ahead", "may create", "yes", "", 1, True, ["may create and delete"], {"a": 1}):
        value, notes = supply({"data_way": {"may": bad, "pools": {"o": {"existing": ["a"], "create_request": "m", "delete_request": "d"}}}})
        assert value["data"]["may"] == "existing_only" and value["data"]["may_known"] is False, bad
        assert value["data"]["pools"] == {"o": {"existing": ["a"]}}, bad
        assert "manual.data_way.may is not one of the three answers" in notes[0], notes


def test_may_recorded_answer_not_overridden_by_stand():
    manual = {"data_way": {"may": "may create and delete", "pools": {"o": {"existing": ["a"], "create_request": "m", "delete_request": "d"}}}}
    for safe in (True, False, "no", None):
        config = cfg(manual) | {"environments": [{"name": "dev", "safe_to_break": safe}], "environment": {"safe_to_break": safe}}
        value, notes = C.walk_supply(config)
        assert value["data"]["may"] == "create_and_delete" and value["data"]["may_known"] is True and notes == [], (safe, value)
    source = Path(C.__file__).read_text(encoding="utf-8")
    start = source.index("def _supply_defaults")
    end = source.index("def _merge_missing")
    code = re.sub(r'""".*?"""', "", source[start:end], flags=re.DOTALL)           # the docstring may name the mark; the code may not
    assert "safe_to_break" not in code, "B.8: the reader never consults the mark"


def test_answer_keeps_existing_more_accounts():
    import project_decisions as PD
    current = {"words": "old words", "self_sign_up": {"roles": ["default"]}, "more_accounts": {"admin": ["env:A_USER/A_PASS"]},
               "limit_by_role": {"admin": 1}}
    base = {"manual": {"walkers": 3, "accounts_way": copy.deepcopy(current), "data_way": {"words": "d", "may": "may create and delete"}}}
    naive = copy.deepcopy(base)
    PD._set_pointer(naive, "/manual/accounts_way", {"words": "new words"})           # why the rows state the rule: resolve assigns whole
    assert "more_accounts" not in naive["manual"]["accounts_way"]
    merged = copy.deepcopy(base)
    value = copy.deepcopy(merged["manual"]["accounts_way"]); value["words"] = "new words"      # the rule: current object, only set keys replaced
    PD._set_pointer(merged, "/manual/accounts_way", value)
    after, notes = C.walk_supply(cfg(merged["manual"]))
    assert after["accounts"]["more_accounts"] == {"admin": ["env:A_USER/A_PASS"]} and after["accounts"]["limit_by_role"] == {"admin": 1}
    assert after["accounts"]["words"] == "new words" and after["accounts"]["self_sign_up_roles"] == ["default"] and notes == []
    # the walk_account record: the role's current list plus the new entry, written whole at its own pointer
    again = copy.deepcopy(merged)
    PD._set_pointer(again, "/manual/accounts_way/more_accounts/admin", ["env:A_USER/A_PASS", "env:B_USER/B_PASS"])
    assert C.walk_supply(cfg(again["manual"]))[0]["accounts"]["more_accounts"] == {"admin": ["env:A_USER/A_PASS", "env:B_USER/B_PASS"]}
    # the data-change answer is a string at its own pointer: the other data_way keys stay
    PD._set_pointer(again, "/manual/data_way/may", "only use what exists")
    assert again["manual"]["data_way"]["words"] == "d" and again["manual"]["accounts_way"]["words"] == "new words"
    # the conductor rows state it, and carry key NAMES only
    actions = json.loads((REFS / "conductor-actions.json").read_text(encoding="utf-8-sig"))["actions"]
    rows = {r.get("id"): r for r in actions if r.get("id") in ("walk_supply_way", "walk_account_words", "data_change_words")}
    assert set(rows) == {"walk_supply_way", "walk_account_words", "data_change_words"}, sorted(rows)
    assert "MERGE ON WRITE" in rows["walk_supply_way"]["run"] and "CURRENT" in rows["walk_supply_way"]["run"]
    assert "/manual/accounts_way/more_accounts/<role>" in rows["walk_account_words"]["run"] and "merge on write" in rows["walk_account_words"]["run"]
    assert "/manual/data_way/may" in rows["data_change_words"]["run"] and all(t in rows["data_change_words"]["run"] for t in THREE)
    assert "stand-account" in rows["walk_account_words"]["run"]
    for row in rows.values():
        assert C._supply_secret_hit(row["run"] + row["says"], C.canonical_template()["secret_content_patterns"]) is False, "names only"
        assert "never a value" in row["run"] or "names of the two keys only" in row["run"] or "not touched" in row["run"]


def test_walk_supply_raw_keeps_what_the_config_holds():
    node = {"words": "w", "more_accounts": {"admin": ["env:A/B"]}, "hand_added": [1, {"x": 2}]}
    raw = C.walk_supply_raw(cfg({"accounts_way": node, "data_way": {"pools": {"k": 1}, "extra": True}}))
    assert raw["accounts"] == node and raw["accounts"] is not node and raw["data"] == {"pools": {"k": 1}, "extra": True}
    assert C.walk_supply_keys() == {"accounts": "accounts_way", "data": "data_way"}


def test_walk_supply_raw_missing_or_bad_is_empty():
    empty = {"accounts": {}, "data": {}}
    for config in (cfg({}), cfg({"accounts_way": "x", "data_way": []}), {"manual": []}, {}):
        assert C.walk_supply_raw(config) == empty, config
    for config in (None, 0, "x", [], [[]]):
        assert C.walk_supply_raw(config) == empty, config


def test_one_reader_of_accounts_way():
    """AR-13: `accounts_way` / `data_way` are read in config_contract.py only (positive control: `parallel_windows` is found there)."""
    scripts = HERE.parent
    def reads(source: str, word: str) -> bool:
        """A READ: the word as a name/attribute, or a string that is a bare key or dotted key path (no spaces) - never prose naming it."""
        import ast
        path = re.compile(r"^[\w.]*" + re.escape(word) + r"[\w.]*$")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Name) and node.id == word or isinstance(node, ast.Attribute) and node.attr == word:
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and path.match(node.value):
                return True
        return False
    def holders(word: str) -> list:
        return sorted(p.name for p in scripts.glob("*.py") if reads(p.read_text(encoding="utf-8", errors="replace"), word))
    # negative controls: real reads are caught, a mention inside a message is not
    assert reads('x = cfg["manual"]["accounts_way"]', "accounts_way") and reads('cfg.get("accounts_way", {})', "accounts_way")
    assert reads('get_path(cfg, "manual.accounts_way")', "accounts_way") and reads("accounts_way = 1", "accounts_way")
    assert not reads('msg = ("set `manual.accounts_way`; the factory asks")  # accounts_way', "accounts_way")
    assert "config_contract.py" in holders("parallel_windows")
    assert holders("accounts_way") == ["config_contract.py"], holders("accounts_way")
    assert holders("data_way") == ["config_contract.py"], holders("data_way")


def test_template_and_keys_rows():
    template = C.canonical_template()
    assert template["manual"]["walkers"] == 3
    assert template["manual"]["accounts_way"] == {"words": "not known", "self_sign_up": {}, "more_accounts": {}, "limit_by_role": {}}
    assert template["manual"]["data_way"] == {"words": "not known", "pools": {}, "may": "not known"}
    keys = C.config_keys()
    for key in ("manual.accounts_way", "manual.data_way"):
        assert keys["keys"][key]["absent_means"] == "default" and keys["keys"][key]["since"]
    assert keys["notes"]["manual_supply_note"]["note_history"][-1] == template["manual_supply_note"]
    assert re.search(r"(?i)\bpassword\b\s*[=:]", template["manual_supply_note"]) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
