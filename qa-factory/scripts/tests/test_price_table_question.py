"""The question about an old project price table (B-225, piece Q7 of the task-price spec).

A config may still carry `cost.model_prices`, a table keyed by model FAMILY ("claude-sonnet"
prices every model whose id contains it). The factory prices by its built-in list, so a key
that shadows a listed model at a different rate is a fact only the person can settle: the old
numbers are either their real prices or stale. `migration_plan` asks, with three answers:
(a) the built-in prices, (b) own prices for named models, (c) the person's own words.

What these checks protect:
- FR-7: after (a) or (b) the plan of the result asks nothing about that table again.
- The error direction of the equality test: a doubtful rate counts as different (one question
  too many), never as equal (a silent pass).
- A key for a model the catalogue does not know is nobody's business here: never asked about,
  never removed.
Run: python -B scripts/tests/test_price_table_question.py
"""
import copy
import json
import sys
from pathlib import Path

from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import human_text  # noqa: E402
from config_contract import (PRICE_TABLE_PATH, _json_hash, apply_plan, canonical_template,  # noqa: E402
                             migration_plan, price_table_conflict, record_approval, validate)

OLD = {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6}
NEW = {"input": 2, "output": 10, "cache_read": 0.2, "cache_write_5m": 2.5, "cache_write_1h": 4}
HAIKU = {"input": 1, "output": 5, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2}
LITE = {"input": 2, "output": 12, "cache_read": 0.2}

CAT = {"entries": [
    {"model_id": "claude-sonnet-4-6", "aliases": [], "rates": OLD},
    {"model_id": "claude-sonnet-5-5", "aliases": [], "rates": NEW},
    {"model_id": "claude-haiku-4-5-20251001", "aliases": ["claude-haiku-4-5"], "rates": HAIKU},
    {"model_id": "gpt-lite", "aliases": [], "rates": LITE},
]}
CAT_ONE = {"entries": [{"model_id": "claude-sonnet-5-5", "aliases": [], "rates": NEW}]}
# t-298: `environment.access` is asked until answered, and an apply refuses while it is open. The flows below are about the price table,
# so the person's answer to that other question is "no login at all" (the whole value at the pointer, as the role passes it).
NO_LOGIN = {"/environment/access": {**canonical_template()["environment"]["access"], "kind": "none"}}


def cfg(table, **cost) -> dict:
    return {"schema_version": 1, "cost": {"model_prices": table, **cost}}


def conflicts_of(config, catalogue=CAT) -> list:
    return migration_plan(config, catalogue=catalogue)["conflicts"]


def price_conflicts(plan) -> list:
    return [c for c in plan["conflicts"] if c.get("path") == PRICE_TABLE_PATH]


def overrides(config) -> list:
    return (config.get("cost") or {}).get("rate_overrides") or []


ABSENT_ROW = {"model_id": "", "table_key": "", "table_rates": None, "catalogue_rates": None, "line": ""}


def first(plan) -> dict:
    """The price conflict of a plan, or an empty shell: a missing conflict fails the check
    that reads it, it does not crash the run with an IndexError."""
    found = price_conflicts(plan)
    return found[0] if found else {"path": None, "default": None, "question": "", "rows": []}


def first_row(conflict) -> dict:
    return conflict["rows"][0] if conflict["rows"] else ABSENT_ROW


def edges() -> None:
    # An absent, empty or null table has nothing to ask about, and no shape of it raises.
    shapes = {"no cost key": {"schema_version": 1},
              "cost without model_prices": {"schema_version": 1, "cost": {"rate_overrides": []}},
              "model_prices empty": cfg({}),
              "model_prices null": cfg(None),
              "model_prices a list": cfg([1, 2]),
              "cost null": {"schema_version": 1, "cost": None},
              "cost a string": {"schema_version": 1, "cost": "x"}}
    for name, config in shapes.items():
        try:
            found = conflicts_of(config)
        except Exception as exc:  # noqa: BLE001 - the point is that nothing is raised
            found = f"raised {exc!r}"
        # A `cost` that is not an object is the deep fill's own question (t-239 O2-1: a scalar where
        # the template has an object is never overwritten, and it is asked); never a PRICE question.
        shown = found if isinstance(found, str) else [c["path"] for c in found]
        check_eq(f"E-absent: {name}: no price conflict, no exception",
                 shown, ["/cost"] if name in ("cost null", "cost a string") else [])
    check_eq("E-absent: the real catalogue with no table: no conflict",
             migration_plan({"schema_version": 1})["conflicts"], [])

    # Equal rates for every shadowed id: nothing to decide, the table is left as it is.
    equal = cfg({"claude-sonnet-4": OLD})
    plan = migration_plan(equal, catalogue=CAT)
    check_eq("E-equal: table equal to the catalogue: no conflict", plan["conflicts"], [])
    check_eq("E-equal: the table is left as it is", plan["proposed_config"]["cost"]["model_prices"],
             {"claude-sonnet-4": OLD})
    check_eq("E-equal: no change is proposed for it", plan["changes"], [])
    legacy = {"claude-haiku": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 1.25}}
    # `cache_write` alone stood for both tiers; the catalogue's tiers differ (1.25 / 2), so this
    # is different - and the same single figure against equal tiers is equal.
    check_eq("E-legacy: a single cache_write that does not equal both tiers is different",
             len(conflicts_of(cfg(legacy))), 1)
    even = {"entries": [{"model_id": "claude-x-1", "rates": {"input": 1, "output": 5, "cache_read": 0.1,
                                                             "cache_write_5m": 2, "cache_write_1h": 2}}]}
    check_eq("E-legacy: a single cache_write equal to both tiers is equal",
             conflicts_of(cfg({"claude-x": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 2}}),
                          even), [])

    # A family key that reaches several ids, equal to some and different from others.
    plan = migration_plan(cfg({"claude-sonnet": OLD}), catalogue=CAT)
    found = price_conflicts(plan)
    check_eq("E-several: conflict emitted", len(found), 1)
    check_eq("E-several: rows only for the differing id", [r["model_id"] for r in first(plan)["rows"]],
             ["claude-sonnet-5-5"])

    # A key that matches no catalogue id is never part of it.
    check_eq("E-unknown: a table of only unknown keys: no conflict",
             conflicts_of(cfg({"my-local-model": {"input": 99}})), [])
    check_eq("E-unknown: the unknown key is not a row", [r["model_id"] for r in first(
        migration_plan(cfg({"my-local-model": {"input": 99}, "claude-sonnet": OLD}), catalogue=CAT))["rows"]],
             ["claude-sonnet-5-5"])

    # Doubtful entries are different, shown as written, and never raise.
    for name, bad in {"missing fields": {"input": 3}, "non-numeric": {**OLD, "input": "three"},
                      "a bool": {**OLD, "output": True}, "not an object": "cheap", "null": None,
                      "extra field only": {**NEW, "cache_write_1h": None}}.items():
        try:
            found = price_conflicts(migration_plan(cfg({"claude-sonnet-5": bad}), catalogue=CAT_ONE_PLUS_FIVE))
            ok = len(found) == 1 and first_row(found[0])["table_rates"] == bad
            detail = found
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"raised {exc!r}"
        check(f"E-doubtful: {name}: one conflict, the row carries the entry as written", ok, str(detail))

    # cmp1: family key `claude-sonnet` 3/15/0.3/3.75/6 against `claude-sonnet-5-5` 2/10/0.2/2.5/4.
    plan = migration_plan(cfg({"claude-sonnet": OLD}), catalogue=CAT_ONE)
    found = price_conflicts(plan)
    check_eq("E-cmp1: conflict emitted, one row", [len(found), len(first(plan)["rows"])], [1, 1])
    row = first_row(first(plan))
    check_eq("E-cmp1: the row names the model, the table's rate and the catalogue's rate",
             [row["model_id"], row["table_rates"], row["catalogue_rates"]], ["claude-sonnet-5-5", OLD, NEW])
    # The spec expected one row against the REAL catalogue too; it holds two, because
    # `claude-sonnet-5` (2/10 as well) also contains the key. Both differ, so both are asked.
    real = price_conflicts(migration_plan(cfg({"claude-sonnet": OLD})))
    check_eq("E-cmp1: against the real catalogue the conflict is emitted",
             [len(real), sorted(r["model_id"] for r in real[0]["rows"]) if real else []],
             [1, ["claude-sonnet-5", "claude-sonnet-5-5"]])
    # Temporal: a config already cleaned (the key gone) produces none.
    check_eq("E-temporal: a cleaned config produces none", conflicts_of(cfg({})), [])


CAT_ONE_PLUS_FIVE = {"entries": [{"model_id": "claude-sonnet-5", "aliases": [], "rates": NEW}]}


def override_one() -> None:
    # O1: the conflict, in plain words, with the three answers.
    plan = migration_plan(cfg({"claude-sonnet": OLD, "my-local-model": {"input": 1}}), catalogue=CAT)
    found = first(plan)
    text = found["question"]
    body, how = human_text.split(text)
    check_eq("O1: the conflict carries the path, and the default is the built-in prices",
             [found["path"], found["default"]], [PRICE_TABLE_PATH, "builtin"])
    check_in("O1: says the factory prices by its built-in list prices", "built-in list prices", body)
    check_in("O1: says this project carries an older table", "older price table", body)
    check_in("O1: names the models the table prices differently", "claude-sonnet-5-5", body)
    check_not_in("O1: a model at an equal price is not named", "claude-sonnet-4-6", body)
    for mark in ("(a) The built-in prices (the default)", "(b) Our own prices", "(c) Something else"):
        check_in(f"O1: answer offered: {mark}", mark, body)
    check_in("O1: (a) removes the entries that cover known models, unknown stay",
             "entries for models it does not know stay", body)
    check_in("O1: (b) asks for exact models", "Name the exact models", body)
    check_in("O1: (c) passes the words on as written", "passes your words on as written", body)
    check_not_in("O1: there is no separate remove-the-table answer", "remove the table", text.lower())
    check_eq("O1: exactly three answers", sum(body.count(f"({x}) ") for x in "abcd"), 3)
    check_eq("O1: the question obeys the text rules (human-questions.md)", human_text.problems(text), [])
    check("O1: the commands are in the how-to-answer block, not in the body",
          "--price-table-answer builtin" in how and "--price-table-answer" not in body)
    check_not_in("O1: no config key reaches the person in the body", "model_prices", body)
    check_not_in("O1: no config key reaches the person in the body (overrides)", "rate_overrides", body)


def override_three() -> None:
    # O3: per shadowed model - id, the table's rate, the catalogue's rate; only rows that differ.
    config = cfg({"claude-sonnet": OLD, "claude-haiku": {**HAIKU}})
    rows = first(migration_plan(config, catalogue=CAT))["rows"]
    check_eq("O3: only the rows that differ (equal sonnet-4-6 and haiku are absent)",
             [r["model_id"] for r in rows], ["claude-sonnet-5-5"])
    row = rows[0] if rows else ABSENT_ROW
    check_eq("O3: the row keeps the table's numbers and the catalogue's numbers",
             [row["table_rates"], row["catalogue_rates"], row["table_key"]], [OLD, NEW, "claude-sonnet"])
    check_in("O3: the shown line carries the model id", "claude-sonnet-5-5", row["line"])
    check_in("O3: the shown line carries the table's rate", "3 / 15 / 0.3 / 3.75 / 6", row["line"])
    check_in("O3: the shown line carries the catalogue's rate", "2 / 10 / 0.2 / 2.5 / 4", row["line"])
    check_in("O3: the same line reaches the person in the question", row["line"],
             first(migration_plan(config, catalogue=CAT))["question"])
    shown = first_row(first(migration_plan(cfg({"claude-sonnet-5-5": {"input": 3}}), catalogue=CAT)))
    check_in("O3: a doubtful entry is shown as written, a missing field as 'not set'",
             "3 / not set / not set / not set / not set", shown["line"])
    check_eq("O3: the catalogue's own missing field is not set too (openai-like entry)",
             first_row(first(migration_plan(cfg({"gpt-lite": OLD}), catalogue=CAT)))["line"].split("built-in ")[-1],
             "2 / 12 / 0.2 / not set / not set")


def override_two_builtin() -> None:
    # O2 (a): apply the default on a copy, plan again: no conflict for that table.
    original = cfg({"claude-sonnet": OLD, "claude-haiku": {**HAIKU}, "my-local-model": {"input": 1}})
    before = copy.deepcopy(original)
    plan = migration_plan(original, "builtin", catalogue=CAT)
    check_eq("O2-a: the input config is not touched", original, before)
    check_eq("O2-a: no price conflict remains in the plan that carries the answer",
             price_conflicts(plan), [])
    table = plan["proposed_config"]["cost"]["model_prices"]
    check_eq("O2-a: every key that shadows a catalogue model is removed, the unknown one stays",
             table, {"my-local-model": {"input": 1}})
    check_eq("O2-a: the change names where: the path, the old table, the new table",
             [(c["path"], c["from"], c["to"]) for c in plan["changes"][:1]],
             [(PRICE_TABLE_PATH, before["cost"]["model_prices"], table)])
    check_eq("O2-a: the proposal is bound to the config it was made from",
             plan["input_hash"], _json_hash(before))
    again = migration_plan(plan["proposed_config"], catalogue=CAT)
    check_eq("O2-a: the plan of the resulting config emits NO conflict for that table (FR-7)",
             price_conflicts(again), [])
    check_eq("O2-a: the plan of the resulting config proposes nothing more for it", again["changes"], [])
    check_eq("O2-a: the answer with no conflict present is a no-op",
             migration_plan(cfg({"my-local-model": {"input": 1}}), "builtin", catalogue=CAT)["changes"], [])
    # The default also removes the shadowing key whose own rates were equal: it shadows a model.
    both = migration_plan(cfg({"claude-sonnet-4": OLD, "claude-sonnet-5": NEW, "claude-sonnet-5-5": OLD}),
                          "builtin", catalogue=CAT)
    check_eq("O2-a: equal-rate shadowing keys go too when the question is answered",
             both["proposed_config"]["cost"]["model_prices"], {})
    # The cost block stays, and the fill (O2-1) brought the template's nested keys into it: the
    # emptied table is still an empty object, the person's key is not replaced.
    cost_block = both["proposed_config"]["cost"]
    check_eq("O2-a: an emptied table stays an empty object, the cost block stays (filled to the template's shape)",
             (cost_block["model_prices"], set(cost_block) - {"model_prices"}),
             ({}, set(canonical_template()["cost"])))

    # The same through the existing approval flow on disk, against the REAL catalogue.
    root = temp_project("qa-price-table-")
    try:
        path = root / "qa-factory" / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["cost"] = {"model_prices": {"claude-sonnet": OLD, "my-local-model": {"input": 1}},
                          "rate_overrides": [], "rate_confirmation": {"status": "unconfirmed", "decision_ref": None}}
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        plan = migration_plan(config, "builtin", answers=NO_LOGIN)
        check_eq("O2-a flow: the answer leaves no conflict in the proposal", price_conflicts(plan), [])
        record_approval(root, plan, "onboarding:price-a", "transcript:price-a")
        backup = apply_plan(root, plan, "onboarding:price-a")
        written = json.loads(path.read_text(encoding="utf-8"))
        check_eq("O2-a flow: the written config keeps only the unknown model's entry",
                 written["cost"]["model_prices"], {"my-local-model": {"input": 1}})
        check_eq("O2-a flow: the plan of the written config emits no conflict for that table",
                 price_conflicts(migration_plan(written)), [])
        check_in("O2-a flow: the decision is recorded: the approval log names the proposal",
                 plan["proposal_hash"], (root / "qa-factory" / "records" / "onboarding-approvals.jsonl").read_text(encoding="utf-8"))
        check_eq("O2-a flow: the prior table is kept in the backup of qa-factory/records/config-migrations",
                 json.loads(backup.read_text(encoding="utf-8"))["config"]["cost"]["model_prices"]["claude-sonnet"], OLD)
        check_eq("O2-a flow: the written config is valid", validate(written), [])
    finally:
        cleanup(root)


def override_two_own() -> None:
    # O2 (b): named ids become rate_overrides; the shadowing family keys are removed.
    original = cfg({"claude-sonnet": OLD, "my-local-model": {"input": 1}})
    plan = migration_plan(original, "own", ["claude-sonnet-5-5"], catalogue=CAT)
    proposed = plan["proposed_config"]
    check_eq("O2-b: the named model becomes an override carrying the table's rate",
             [(o["model_id"], o["rates"]) for o in overrides(proposed)],
             [("claude-sonnet-5-5", OLD)])
    check_eq("O2-b: the shadowing key is removed, the unknown key stays",
             proposed["cost"]["model_prices"], {"my-local-model": {"input": 1}})
    check_eq("O2-b: the changes name both places",
             [c["path"] for c in plan["changes"]], [PRICE_TABLE_PATH, "/cost/rate_overrides"])
    check_eq("O2-b: the proposed config is valid", validate(proposed), [])
    check_eq("O2-b: no price conflict in the plan that carries the answer", price_conflicts(plan), [])
    check_eq("O2-b: the plan of the resulting config emits NO conflict for that table (FR-7)",
             price_conflicts(migration_plan(proposed, catalogue=CAT)), [])
    check_eq("O2-b: the resulting overrides are kept by the next plan untouched",
             overrides(migration_plan(proposed, catalogue=CAT)["proposed_config"]), overrides(proposed))
    keep = overrides(migration_plan(
        cfg({"claude-sonnet": OLD}, rate_overrides=[{"model_id": "other", "aliases": [], "rates": {"input": 1}}]),
        "own", ["claude-sonnet-5-5"], catalogue=CAT)["proposed_config"])
    check_eq("O2-b: an approved override already there is kept, the new one is appended",
             [o["model_id"] for o in keep], ["other", "claude-sonnet-5-5"])
    several = overrides(migration_plan(
        cfg({"claude-sonnet": OLD}), "own", ["claude-sonnet-5-5", " claude-sonnet-4-6 ", "claude-sonnet-5-5"],
        catalogue=CAT)["proposed_config"])
    check_eq("O2-b: several ids, trimmed and without repeats", [o["model_id"] for o in several],
             ["claude-sonnet-5-5", "claude-sonnet-4-6"])

    # A refusal says what is wrong and what to do (FR-1), and nothing is half-applied.
    refusals = {
        "an id the table does not reach": ("own", ["claude-opus-9"], "not a model the old price table reaches"),
        "no ids at all": ("own", [], "at least one exact model id"),
        "a table entry that is not numbers": ("own", ["claude-sonnet-5-5"], "not a set of numbers"),
        "an unknown answer": ("catalogue", [], "must be one of"),
    }
    # (The old refusal "an id that already has its own price" is gone: the person's answer is the
    # newer word, see override_own_replaces.)
    for name, (answer, ids, words) in refusals.items():
        config = cfg({"claude-sonnet": OLD})
        if name == "a table entry that is not numbers":
            config = cfg({"claude-sonnet": {"input": "three"}})
        try:
            migration_plan(config, answer, ids, catalogue=CAT)
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in(f"O2-b refusal: {name}: a ValueError that says what is wrong", words, raised)

    root = temp_project("qa-price-table-own-")
    try:
        path = root / "qa-factory" / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["cost"] = {"model_prices": {"claude-sonnet": OLD}, "rate_overrides": [],
                          "rate_confirmation": {"status": "unconfirmed", "decision_ref": None}}
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        plan = migration_plan(config, "own", ["claude-sonnet-5-5"], answers=NO_LOGIN)
        record_approval(root, plan, "onboarding:price-b", "transcript:price-b")
        apply_plan(root, plan, "onboarding:price-b")
        written = json.loads(path.read_text(encoding="utf-8"))
        check_eq("O2-b flow: the override is in the written config",
                 [o["model_id"] for o in overrides(written)], ["claude-sonnet-5-5"])
        check_eq("O2-b flow: the plan of the written config emits no conflict for that table",
                 price_conflicts(migration_plan(written)), [])
    finally:
        cleanup(root)


def own_entry(model_id, rates, **extra) -> dict:
    return {"model_id": model_id, "aliases": [], "rates": rates, **extra}


def model_rows(plan, model_id) -> list:
    return [c for c in plan["changes"] if c["path"] == f"/cost/rate_overrides/{model_id}"]


def override_own_replaces() -> None:
    # The owner, 30.09 (P13): a person's word must not be blocked by code. Naming a model that
    # already has its own price replaces that price; the approval shows old beside new.
    sonnet = "claude-sonnet-5-5"
    existing = own_entry(sonnet, NEW, note="approved earlier")
    config = cfg({"claude-sonnet": OLD}, rate_overrides=[own_entry("other", {"input": 1}), existing])
    try:
        plan = migration_plan(config, "own", [sonnet], catalogue=CAT)
        refused = ""
    except ValueError as exc:
        plan, refused = None, str(exc)
    check_eq("R-replace: an id that already has its own price is NOT refused", refused, "")
    plan = plan or migration_plan(cfg({}), catalogue=CAT)
    proposed = plan["proposed_config"]
    check_eq("R-replace: the override of that model carries the old table's rate, the others stay in place",
             [(o["model_id"], o["rates"]) for o in overrides(proposed)], [("other", {"input": 1}), (sonnet, OLD)])
    check_eq("R-replace: the input config is not touched", overrides(config)[1], existing)
    rows = model_rows(plan, sonnet)
    check_eq("R-replace: one row for that model, previous override beside the new one",
             [(r["from"], r["to"]["rates"]) for r in rows], [(existing, OLD)])
    check_eq("R-replace: the person reads it in plain words",
             [r["reason"] for r in rows],
             [f"{sonnet} already has your own price 2 / 10 / 0.2 / 2.5 / 4; "
              "your answer replaces it with 3 / 15 / 0.3 / 3.75 / 6"])
    check_eq("R-replace: the approval is bound to the plan that shows the row",
             [c["path"] for c in plan["changes"]], [PRICE_TABLE_PATH, "/cost/rate_overrides",
                                                    f"/cost/rate_overrides/{sonnet}"])
    check_eq("R-replace: the proposed config is valid", validate(proposed), [])
    check_eq("R-replace: FR-7: the plan of the resulting config asks nothing about the table",
             price_conflicts(migration_plan(proposed, catalogue=CAT)), [])
    check_eq("R-replace: and proposes nothing more", migration_plan(proposed, catalogue=CAT)["changes"], [])

    # Equal: nothing changes, no row.
    same = cfg({"claude-sonnet": OLD}, rate_overrides=[own_entry(sonnet, dict(OLD), note="mine")])
    plan = migration_plan(same, "own", [sonnet], catalogue=CAT)
    check_eq("R-equal: an equal own price is kept exactly", overrides(plan["proposed_config"]), overrides(same))
    check_eq("R-equal: no row is added, only the table goes", [c["path"] for c in plan["changes"]],
             [PRICE_TABLE_PATH])

    # An alias-only cover: the id leaves that entry and gets its own; the entry keeps the rest.
    aliased = cfg({"claude-sonnet": OLD},
                  rate_overrides=[{"model_id": "team-model", "aliases": [sonnet, "x"], "rates": {"input": 1}}])
    plan = migration_plan(aliased, "own", [sonnet], catalogue=CAT)
    got = overrides(plan["proposed_config"])
    check_eq("R-alias: the id leaves the other entry's aliases and gets its own entry first",
             [(o["model_id"], o["aliases"], o["rates"]) for o in got],
             [(sonnet, [], OLD), ("team-model", ["x"], {"input": 1})])
    check_eq("R-alias: the row shows the previous entry", [r["from"]["model_id"] for r in model_rows(plan, sonnet)],
             ["team-model"])

    # Edge: an own price and NO price for it in the old table - left, said in plain words, not refused.
    haiku = "claude-haiku-4-5-20251001"
    plan = migration_plan(cfg({"claude-sonnet": OLD}, rate_overrides=[own_entry(haiku, {"input": 9, "output": 9})]),
                          "own", [sonnet, haiku], catalogue=CAT)
    check_eq("R-no-rate: that override is left as it is",
             [(o["model_id"], o["rates"]) for o in overrides(plan["proposed_config"])],
             [(haiku, {"input": 9, "output": 9}), (sonnet, OLD)])
    check_eq("R-no-rate: the plan says the old table has no price for it",
             [r["reason"] for r in model_rows(plan, haiku)],
             [f"the old price table has no price for {haiku}; its own price 9 / 9 / not set / not set / not set "
              "is left as it is"])
    check_eq("R-no-rate: the other named id is handled on its own (added)",
             [c["path"] for c in plan["changes"]], [PRICE_TABLE_PATH, "/cost/rate_overrides",
                                                    f"/cost/rate_overrides/{haiku}"])
    check_eq("R-no-rate: a model with neither an override nor a table price is still refused with the ids",
             [m in str(exc_of(lambda: migration_plan(cfg({"claude-sonnet": OLD}), "own", [haiku], catalogue=CAT)))
              for m in ("not a model the old price table reaches", sonnet)], [True, True])

    # Several ids, each on its own: replaced, equal and new together.
    four = cfg({"claude-sonnet": OLD, "claude-haiku": HAIKU},
               rate_overrides=[own_entry(sonnet, NEW), own_entry("claude-sonnet-4-6", dict(OLD))])
    plan = migration_plan(four, "own", [sonnet, "claude-sonnet-4-6", haiku], catalogue=CAT)
    check_eq("R-several: replaced, equal kept, new appended",
             [(o["model_id"], o["rates"]) for o in overrides(plan["proposed_config"])],
             [(sonnet, OLD), ("claude-sonnet-4-6", OLD), (haiku, HAIKU)])
    check_eq("R-several: a row only for the replaced one", [c["path"] for c in plan["changes"][2:]],
             [f"/cost/rate_overrides/{sonnet}"])

    # Malformed entries are replaced and shown as written; a value that is no object names no model.
    for name, bad, shown in [("no rates", {"model_id": sonnet}, "with no rates set"),
                             ("rates not an object", {"model_id": sonnet, "rates": "cheap"}, '"cheap"'),
                             ("rates with a word", {"model_id": sonnet, "rates": {"input": "three"}}, '"three"'),
                             ("aliases not a list", {"model_id": sonnet, "aliases": "x", "rates": NEW}, "2 / 10")]:
        try:
            plan = migration_plan(cfg({"claude-sonnet": OLD}, rate_overrides=["stray", bad]), "own", [sonnet],
                                  catalogue=CAT)
            got = [(o["rates"] if isinstance(o, dict) else o) for o in overrides(plan["proposed_config"])]
            row = model_rows(plan, sonnet)
            ok = got == ["stray", OLD] and len(row) == 1 and row[0]["from"] == bad and shown in row[0]["reason"]
            detail = plan["changes"]
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"raised {exc!r}"
        check(f"R-malformed: {name}: replaced, the row shows it as written, the stray value stays", ok, str(detail))

    # The same through the approval flow on disk: the prior config, with the old override, is kept.
    root = temp_project("qa-price-table-replace-")
    try:
        path = root / "qa-factory" / "config.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["cost"] = {"model_prices": {"claude-sonnet": OLD}, "rate_overrides": [own_entry(sonnet, NEW)],
                          "rate_confirmation": {"status": "unconfirmed", "decision_ref": None}}
        path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        plan = migration_plan(stored, "own", [sonnet], answers=NO_LOGIN)
        record_approval(root, plan, "onboarding:price-r", "transcript:price-r")
        backup = apply_plan(root, plan, "onboarding:price-r")
        written = json.loads(path.read_text(encoding="utf-8"))
        check_eq("R-flow: the written config carries the new own price", [o["rates"] for o in overrides(written)], [OLD])
        check_eq("R-flow: the prior own price is kept in the backup in config-migrations",
                 json.loads(backup.read_text(encoding="utf-8"))["config"]["cost"]["rate_overrides"][0]["rates"], NEW)
        check_eq("R-flow: the plan of the written config emits no conflict for that table",
                 price_conflicts(migration_plan(written)), [])
    finally:
        cleanup(root)


def exc_of(call) -> str:
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return ""


def override_words() -> None:
    # (c): not applied by code. The question stays a conflict, the table stays, and apply refuses
    # the proposal until the person's words have been acted on by whoever can judge them.
    config = cfg({"claude-sonnet": OLD})
    plan = migration_plan(config, catalogue=CAT)
    check_eq("O1-c: no answer given: the conflict stays", len(price_conflicts(plan)), 1)
    check_eq("O1-c: no answer given: the proposed table is exactly the old one",
             plan["proposed_config"]["cost"]["model_prices"], {"claude-sonnet": OLD})
    check_eq("O1-c: no answer given: no change is proposed", plan["changes"], [])
    root = temp_project("qa-price-table-words-")
    try:
        path = root / "qa-factory" / "config.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["cost"] = {"model_prices": {"claude-sonnet": OLD}}
        path.write_text(json.dumps(stored), encoding="utf-8")
        plan = migration_plan(stored)
        record_approval(root, plan, "onboarding:price-c", "transcript:price-c")
        try:
            apply_plan(root, plan, "onboarding:price-c")
            refused = False
        except ValueError as exc:
            refused = "unresolved conflicts" in str(exc)
        check("O1-c: apply refuses a proposal whose price question is still open", refused)
    finally:
        cleanup(root)


def command_line() -> None:
    root = temp_project("qa-price-table-cli-")
    try:
        path = root / "qa-factory" / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["cost"] = {"model_prices": {"claude-sonnet": OLD}}
        path.write_text(json.dumps(config), encoding="utf-8")
        shown = run_script("config_contract.py", "--root", root, "--migration-plan")
        plan = json.loads(shown.stdout)
        check_eq("CLI: the plan without an answer shows the conflict", len(price_conflicts(plan)), 1)
        done = run_script("config_contract.py", "--root", root, "--migration-plan", "--price-table-answer", "builtin")
        check_eq("CLI: builtin leaves no price conflict", price_conflicts(json.loads(done.stdout)), [])
        own = run_script("config_contract.py", "--root", root, "--migration-plan", "--price-table-answer", "own",
                         "--model-id", "claude-sonnet-5-5")
        check_eq("CLI: own with an id writes the override into the proposal",
                 [o["model_id"] for o in overrides(json.loads(own.stdout)["proposed_config"])],
                 ["claude-sonnet-5-5"])
        bare = run_script("config_contract.py", "--root", root, "--migration-plan", "--price-table-answer", "own")
        check("CLI: own without an id is refused with the way out", bare.returncode != 0
              and "at least one exact model id" in bare.stderr and "builtin" in bare.stderr, bare.stderr)
        check_eq("CLI: the config file itself is never written by a plan",
                 json.loads(path.read_text(encoding="utf-8")), config)
    finally:
        cleanup(root)


def direct_function() -> None:
    check_eq("price_table_conflict: None when nothing differs", price_table_conflict(cfg({"claude-sonnet-4": OLD}), CAT), None)
    check("price_table_conflict: a dict when something differs",
          isinstance(price_table_conflict(cfg({"claude-sonnet": OLD}), CAT), dict))


def main() -> None:
    edges()
    override_one()
    override_three()
    override_two_builtin()
    override_two_own()
    override_own_replaces()
    override_words()
    command_line()
    direct_function()
    finish("test_price_table_question")


if __name__ == "__main__":
    main()
