"""config_contract.migration_plan - installing IS migrating (t-232 B2).

A reinstall over an old configuration must end with the config a fresh install writes, by code:
every template key present, canonical key order, deprecated keys removed (each listed with its
reason), a person's changed notes moved whole to `answers_legacy`, launch commands that name the
writer's own machine dropped. A project with no config is the empty input of the SAME plan.

K3   the old-generation config comes out as the template's shape, on a live-shaped fixture
K14  the machine-local gate: 10 inputs that must be refused, 5 that must pass
C2   an approval is of the proposal's content (proposal_hash), never of its input alone
C4   canonical key order, a changed order listed
C5   notes: any known template text resets, a person's text moves, a non-template note stays
C8   config-keys.json names every template key, and the live-shaped config is not `not_configured`
O2-1 the fill reaches keys nested in template objects (never lists, never over a value)
O2-2 nested notes (environment.note, cost.note) follow the C5 rule under their dotted key
O2-3 apply writes the template's key order, whoever filled the proposal
O2-4 a fresh install leaves no backup file and no config-migrations directory
O2-5 a required key the plan invented, or a re-asked key, is open until the person answers it
F0.1 no config.json: plan, approval and apply do not crash; an unreadable one is refused with its door

Runnable on its own: `python -B scripts/tests/test_config_migration.py`.
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (  # noqa: E402
    FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, run_script,
    temp_dir, temp_project, use_project,
)

use_project(temp_project("qa-config-migration-audit-"))  # audit_factory reads the hook layer on import

import config_contract as C  # noqa: E402
import readiness as R  # noqa: E402
from audit_factory import _machine_local  # noqa: E402

TEMPLATE = C.canonical_template()
KEYS = C.config_keys()
VERSION = C.package_version()
FIXTURE_PATH = FIXTURES / "config-live-shape.json"
B = chr(92)  # a backslash, spelled so no escape survives a copy (FR-29)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def template_notes() -> list:
    return [k for k in TEMPLATE if k.endswith("_note")]


def template_value_keys() -> list:
    return [k for k in TEMPLATE if not k.endswith("_note")]


def uncovered(template: dict, table: dict) -> list:
    """Template keys config-keys.json does not describe (C8): a top-level value key needs `since`
    and `absent_means`, a note key - top-level or nested in a template object (O2-2) - needs
    `since` and `note_history` ending in the template text. Nested value keys need no entry:
    they inherit their top-level key's `since` and are `default`."""
    bad = []

    def note_ok(dotted, value):
        meta = (table.get("notes") or {}).get(dotted) or {}
        history = meta.get("note_history")
        return bool(meta.get("since") and isinstance(history, list) and history and history[-1] == value)

    def nested_notes(node, parts):
        for key, value in node.items():
            if isinstance(value, dict):
                yield from nested_notes(value, parts + [key])
            elif parts and (key == "note" or key.endswith("_note")) and isinstance(value, str):
                yield ".".join(parts + [key]), value

    for key, value in template.items():
        if key.endswith("_note"):
            if not note_ok(key, value):
                bad.append(key)
        else:
            meta = (table.get("keys") or {}).get(key) or {}
            if not (meta.get("since") and meta.get("absent_means") in ("default", "required")):
                bad.append(key)
        if isinstance(value, dict):
            bad.extend(dotted for dotted, text in nested_notes({key: value}, []) if not note_ok(dotted, text))
    return bad


LIGHT_FORM_DEFAULTS = {"adapters.ticket.direct_api.custom_fields": [],
                       "adapters.ticket.direct_api.acceptance_headings": [],
                       "adapters.ticket.attachments": {}}


def light_form_wrong(template: dict) -> list:
    """Dotted keys of the light ticket form whose template value is absent or is not the default."""
    return [dotted for dotted, default in LIGHT_FORM_DEFAULTS.items()
            if _at(template, "/" + dotted.replace(".", "/")) != default]


def _at(config: dict, pointer: str):
    """The value at a JSON pointer, or the word MISSING."""
    node = config
    for part in pointer[1:].split("/"):
        if not isinstance(node, dict) or part not in node:
            return "MISSING"
        node = node[part]
    return node


def seal(proposal: dict) -> dict:
    proposal["proposal_hash"] = C.proposal_hash(proposal)
    return proposal


def plan_of(old, **kw) -> dict:
    return C.migration_plan(old, **kw)


def message_of(call) -> str:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the text is what is asserted
        return f"{type(exc).__name__}: {exc}"
    return ""


def table_with(**parts) -> dict:
    """The real table with some parts replaced: a rule is proved on a table of the test's own."""
    table = copy.deepcopy(KEYS)
    table.update(parts)
    return table


# --- C8: the table names every template key ---------------------------------------------------

def table_coverage() -> None:
    check_eq("C8: config-keys.json describes every top-level key of the template", uncovered(TEMPLATE, KEYS), [])
    probe = dict(TEMPLATE, some_new_key=1, some_new_key_note="x")
    check_eq("C8 negative control: a template key the table lacks is reported (value key and note)",
             uncovered(probe, KEYS), ["some_new_key", "some_new_key_note"])
    stale = copy.deepcopy(KEYS)
    stale["notes"]["app_root_note"]["note_history"] = stale["notes"]["app_root_note"]["note_history"][:-1]
    check_eq("C8 negative control: a note whose current template text is not in its history is reported",
             uncovered(TEMPLATE, stale), ["app_root_note"])
    check_eq("O2-2: the table names the template's nested notes by dotted path (environment.note, cost.note)",
             sorted(k for k in KEYS["notes"] if "." in k), ["cost.note", "environment.note"])
    nested_stale = copy.deepcopy(KEYS)
    del nested_stale["notes"]["cost.note"]
    check_eq("O2-2 negative control: a nested template note the table lacks is reported",
             uncovered(TEMPLATE, nested_stale), ["cost.note"])
    nested_stale = copy.deepcopy(KEYS)
    nested_stale["notes"]["environment.note"]["note_history"].pop()
    check_eq("O2-2 negative control: a nested note whose current text is not in its history is reported",
             uncovered(TEMPLATE, nested_stale), ["environment.note"])
    # The light ticket form's three optional keys (0.7.19) are in the template with their defaults, so a
    # fresh config shows them and a migration of an older one adds them.
    check_eq("C8 light form: the table names the three keys with an absent-means-default entry",
             sorted(k for k, m in KEYS["keys"].items() if k in LIGHT_FORM_DEFAULTS and m["absent_means"] == "default"),
             sorted(LIGHT_FORM_DEFAULTS))
    check_eq("C8 light form: the template carries the three keys with their defaults", light_form_wrong(TEMPLATE), [])
    for dotted in LIGHT_FORM_DEFAULTS:
        parts = dotted.split(".")
        for label, change in (("without it", lambda node: node.pop(parts[-1], None)),
                              ("with another default", lambda node: node.__setitem__(parts[-1], "x"))):
            scratch = copy.deepcopy(TEMPLATE)
            node = scratch
            for part in parts[:-1]:
                node = node.setdefault(part, {})       # a template that lacks the parent is still no crash
            change(node)
            check_eq(f"C8 light form negative control: `{dotted}` {label} is reported",
                     [d for d in light_form_wrong(scratch) if d == dotted], [dotted])
    check("C8: `since` reads as a version", all(re.fullmatch(r"\d+\.\d+\.\d+", str(m["since"]))
                                                for m in [*KEYS["keys"].values(), *KEYS["notes"].values()]))
    check("C8: the three keys that made the live config not_configured are named with a default",
          all(KEYS["keys"].get(k, {}).get("absent_means") == "default" for k in ("handoffs", "prompts", "retro")))
    check_eq("C8: readiness.OPTIONAL_TOP_KEYS is exactly the table's `default` keys",
             sorted(R.OPTIONAL_TOP_KEYS),
             sorted(k for k, m in KEYS["keys"].items() if "." not in k and m["absent_means"] == "default"))
    check_eq("C8: and what readiness requires is exactly the `required` ones",
             sorted(R.template_top_keys()),
             sorted(k for k in template_value_keys() if KEYS["keys"].get(k, {}).get("absent_means") == "required"))
    check("the nested key the migration adds exists in the template",
          "access" in TEMPLATE["environment"] and "environment.access" in KEYS["keys"])
    check("a note's history is oldest first and holds no duplicate",
          all(len(set(m["note_history"])) == len(m["note_history"]) for m in KEYS["notes"].values()))
    # E4: the keys a script rewrites after the approval are declared, with the script that does it
    check_eq("E4: execution.runtime_probes is declared REGENERATED, written by runtime_probe.py",
             KEYS["written_by"]["execution.runtime_probes"], {"class": "REGENERATED", "written_by": "runtime_probe.py"})
    check("E4: every declared writer is a script of the package",
          all((PLUGIN_ROOT / "scripts" / m["written_by"]).is_file() for m in KEYS["written_by"].values()))
    check("E4: a declared key is a key of the template (or of one of its objects)",
          all(p.split(".")[0] in TEMPLATE for p in KEYS["written_by"]))


# --- the fixture itself: shape, never content -------------------------------------------------

def fixture_is_shape_only() -> None:
    leaks = []

    def walk(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str):
            ok = (value == "" or re.fullmatch(r"PLACEHOLDER_KEY_\d+", value)
                  or (key.endswith("note") and len(value.split()) <= 3))
            if not ok:
                leaks.append((key, value[:30]))

    walk(fixture())
    check_eq("fixture: every string is blank, a placeholder, or a note of at most 3 words", leaks, [])
    live_missing = [k for k in TEMPLATE if k not in fixture()]
    check("fixture C8: the keys the live-shaped config lacks today include handoffs, prompts, retro",
          {"handoffs", "prompts", "retro"} <= set(live_missing), str(live_missing))
    print("INFO fixture lacks template keys:", ", ".join(live_missing))
    check("fixture C8: every value key it lacks is declared `default` (so none makes it not_configured)",
          all(KEYS["keys"].get(k, {}).get("absent_means") == "default" for k in live_missing if not k.endswith("_note")),
          str([k for k in live_missing if not k.endswith("_note")
               and KEYS["keys"].get(k, {}).get("absent_means") != "default"]))


# --- K3: the old-generation config comes out as a fresh install's shape ------------------------

def old_generation_config() -> dict:
    """The live-shaped fixture as an OLD installation left it: the factory's retired keys, a legacy
    command map, a launch command naming the writer's machine, a person's note and a note nobody owns."""
    old = fixture()
    old = {"audit_cadence_days": 30, "gate_green_runs": 3, **old}
    old["adapters"]["test_management"]["adapter"] = "legacy"
    old["external_writes"]["commands"] = {"jira": "deliver --ticket {id}"}
    old["external_writes"]["channels"]["jira"] = {"method": "command", "command": "deliver --ticket {id}"}
    old["execution"]["runtime_probes"] = {
        "api": {"argv": [B.join(["C:", "Py", "python.exe"]), B.join(["C:", "p", "runtime_probe.py"])],
                "cwd": ".", "timeout_s": 30}}
    return old


def k3_fixture() -> None:
    old = old_generation_config()
    before = copy.deepcopy(old)
    plan = plan_of(old, price_table_answer="builtin")
    proposed = plan["proposed_config"]
    check_eq("K3: the input is not touched", old, before)
    check_eq("K3: nothing is left open once the price answer is given", plan["conflicts"], [])
    for key in ("audit_cadence_days", "gate_green_runs"):
        check(f"K3: deprecated top-level key {key} is gone from proposed_config", key not in proposed)
    check("K3: adapters.test_management.adapter is gone", "adapter" not in proposed["adapters"]["test_management"])
    check("K3: external_writes.commands is gone once its commands are channels",
          "commands" not in proposed["external_writes"])
    removed = {row["path"]: row for row in plan["removed"]}
    for path in ("/audit_cadence_days", "/gate_green_runs", "/adapters/test_management/adapter",
                 "/external_writes/commands", "/execution/runtime_probes/api"):
        check(f"K3: removed[] lists {path} with the old value and a reason",
              path in removed and removed[path]["reason"] and "was" in removed[path])
    check_eq("K3: removed[] keeps the old value of a retired key", removed["/audit_cadence_days"]["was"], 30)
    check_eq("K3: runtime_probes is an empty object, the machine-local entry was dropped",
             proposed["execution"]["runtime_probes"], {})
    check_in("K3: the dropped launch command says how it comes back",
             "runtime_probe.py --suggest", removed.get("/execution/runtime_probes/api", {}).get("reason", ""))
    check_eq("K3: deprecated_keys still names the retired keys",
             plan["deprecated_keys"], ["adapters.test_management.adapter", "audit_cadence_days", "gate_green_runs"])
    missing = [k for k in TEMPLATE if k not in proposed]
    check_eq("K3: every template key is present in proposed_config", missing, [])
    check("K3: environment.access (a nested key) is present", isinstance(proposed["environment"].get("access"), dict))
    added = {row["path"] for row in plan["added"]}
    check("K3: added[] names the keys the old config lacked, with since and absent_means",
          {"/handoffs", "/prompts", "/retro", "/environment/access"} <= added
          and all(row["since"] and row["absent_means"] for row in plan["added"]), str(sorted(added))[:300])
    check_eq("K3: nothing that was present is listed as added", sorted(added & {f"/{k}" for k in old}), [])
    template_order = [k for k in TEMPLATE]
    check_eq("K3: canonical order - the template's keys come first, in the template's order",
             list(proposed)[:len(template_order)], template_order)
    unknown_old = [k for k in old if k not in TEMPLATE and k not in ("audit_cadence_days", "gate_green_runs")]
    check_eq("K3: and the person's own keys follow in their original order",
             list(proposed)[len(template_order):], unknown_old + (["answers_legacy"] if "answers_legacy" not in unknown_old else []))
    check("C4: the order change is listed, values unchanged", "/" in plan["reordered"], str(plan["reordered"]))
    # notes (C5): every fixture note that is a template key differs from the template -> moved whole
    moved_keys = [k for k in old if k.endswith("_note") and k in TEMPLATE]
    check_eq("K3: each changed template note moved whole into answers_legacy.<key>",
             {k: proposed.get("answers_legacy", {}).get(k) for k in moved_keys}, {k: old[k] for k in moved_keys})
    check("K3: and the note itself is the template's current text again",
          all(proposed[k] == TEMPLATE[k] for k in moved_keys))
    nested_moved = {"environment.note": old["environment"]["note"], "cost.note": old["cost"]["note"]}
    check_eq("O2-2 K3: the person's environment.note (and the old cost.note) moved whole under their dotted key",
             {k: proposed.get("answers_legacy", {}).get(k) for k in nested_moved}, nested_moved)
    check("O2-2 K3: ...and each nested note is the template's current text again, listed in changes",
          proposed["environment"]["note"] == TEMPLATE["environment"]["note"] and proposed["cost"]["note"] == TEMPLATE["cost"]["note"]
          and {"/environment/note", "/cost/note"} <= {c["path"] for c in plan["changes"]})
    check_eq("K3: the plan's answers_legacy is what moved (top-level notes and the two nested ones)",
             plan["answers_legacy"], {**{k: old[k] for k in moved_keys}, **nested_moved})
    # O2-1: the 14 keys nested in template objects that the live shape lacks, every one filled and listed
    nested_14 = ["/environment/env_files", "/adapters/ticket/project_keys", "/external_writes/bugs_project",
                 "/external_writes/probe", "/turns/window", "/turns/stage_default", "/execution/parallel",
                 "/execution/node_id_collect_timeout_s", "/execution/runtime_probes", "/execution/s5_window_cases",
                 "/run/stand_wait_s", "/cost/recapture_max_mb", "/cost/rate_overrides", "/cost/rate_confirmation"]
    live = plan_of(fixture(), price_table_answer="builtin")      # the live shape as it is: no injected runtime_probes
    by_path = {row["path"]: row for row in live["added"]}
    check_eq("O2-1 K3: all 14 nested keys of the live shape are listed in added[]", [p for p in nested_14 if p not in by_path], [])
    check_eq("O2-1 K3: ...and each is present in proposed_config with the template's value",
             [p for p in nested_14 if _at(live["proposed_config"], p) != _at(TEMPLATE, p)], [])
    check_eq("O2-1 K3: runtime_probes is {} on the live shape too (K3)", _at(live["proposed_config"], "/execution/runtime_probes"), {})
    light = ["/adapters/ticket/attachments", "/adapters/ticket/direct_api/custom_fields",
             "/adapters/ticket/direct_api/acceptance_headings"]
    check_eq("O2-1 K3: exactly those 14, environment.access, the light form's three and the two 0.8.1 adapter keys (B-405/B-406) "
             "and the two 0.9.0 keys and the 0.10.3 non_runtime_files (FB-8) are the nested rows of the live shape",
             sorted(p for p in by_path if p.count("/") > 1),
             sorted(nested_14 + ["/environment/access"] + light
                    + ["/adapters/ticket/key_pattern", "/adapters/vcs/delivery_commands",
                       "/cost/external_agent_forms", "/run/dependency_files", "/execution/non_runtime_files",
                       "/environment/frontend",
                       "/cost/usage_final_after_idle_min", "/cost/usage_final_after_open_h"]))   # RH1-7: the empty frontend default of an API-only stand
    check_eq("O2-1 K3: the light form's three are added with their own since (0.7.19) and their default",
             [(by_path[p]["since"], by_path[p]["absent_means"], _at(live["proposed_config"], p) == _at(TEMPLATE, p))
              for p in light], [("0.7.19", "default", True)] * 3)
    check_eq("O2-1 K3: a nested key inherits the since of its top-level key (turns.window: turns 0.3.0), a listed pointer keeps its own",
             (by_path["/turns/window"]["since"], by_path["/environment/access"]["since"]), ("0.3.0", "0.7.11"))
    check("O2-1 K3: a nested key is `default` unless the table says otherwise",
          all(by_path[p]["absent_means"] == "default" for p in nested_14))
    check("O2-1 K3: what the person had inside a nested object is not touched by the fill",
          proposed["run"]["levels"] == old["run"]["levels"] and proposed["run"]["parallel"] is False
          and all(proposed["adapters"]["ticket"]["direct_api"].get(k) == v
                  for k, v in old["adapters"]["ticket"]["direct_api"].items())
          and proposed["cost"]["human_wait_cap_s"] == old["cost"]["human_wait_cap_s"]
          and proposed["environment"]["secret_keys"] == old["environment"]["secret_keys"])
    kept = {row["path"]: row["reason"] for row in plan["kept"]}
    check_eq("K3: a note that is not a template key is kept as it is and listed",
             {k: kept.get(f"/{k}") for k in ("execution_note", "pre_commit_note")},
             {k: "kept: not a template key" for k in ("execution_note", "pre_commit_note")})
    check("K3: kept notes are not moved", all(proposed[k] == old[k] for k in ("execution_note", "pre_commit_note")))
    check("K3: the proposed config validates", C.validate(proposed) == [], str(C.validate(proposed)))
    # values the person gave are untouched
    check("K3: a person's value is carried as it was",
          proposed["factory_may_edit_strategy"] is True and proposed["execution"]["verify_node_ids"] is False
          and {k: proposed["turns"][k] for k in old["turns"]} == old["turns"] and proposed["code_repos"] == old["code_repos"])
    # a second plan over the result is a fixed point
    again = plan_of(proposed, price_table_answer="builtin")
    check_eq("K3: planning the result again changes nothing (bytes)",
             json.dumps(again["proposed_config"], indent=2), json.dumps(proposed, indent=2))
    check_eq("K3: ... and lists nothing to remove, rename, add, move or reorder, and re-asks ONLY `/environment/access` "
             "(t-298: the template default of that key is the empty 'not recorded', which a person has not answered)",
             (again["removed"], again["renamed"], [r["path"] for r in again["reasked"]], again["added"], again["answers_legacy"],
              again["reordered"], again["changes"]), ([], [], ["/environment/access"], [], {}, [], []))


def x9_retired_surprise_ignore() -> None:
    """X9 (E2-1): a config that still carries the retired `manual_capture.surprise.ignore` loses it in the migration plan, with its old value
    and a reason; the other `manual_capture` keys are untouched. Negative control: the table without that `removed` row keeps the key."""
    old = fixture()
    old["manual_capture"] = {"type_delay_ms": 50, "settle_ms": 300, "surprise": {"ignore": [{"kind": "status", "match": "*"}]}}
    plan = plan_of(old, price_table_answer="builtin")
    manual = plan["proposed_config"]["manual_capture"]
    check_eq("X9: the retired `surprise` key is dropped from proposed_config, the two live keys stay", manual, {"type_delay_ms": 50, "settle_ms": 300})
    row = {r["path"]: r for r in plan["removed"]}.get("/manual_capture/surprise", {})
    check("X9: removed[] lists /manual_capture/surprise with its old value and a reason",
          row.get("was") == {"ignore": [{"kind": "status", "match": "*"}]} and bool(row.get("reason")), str(row))
    rows = {k: v for k, v in KEYS["removed"].items() if k != "manual_capture.surprise"}
    kept = plan_of(old, price_table_answer="builtin", keys=table_with(removed=rows))
    check("X9 negative control: without the `removed` row the key is kept (the check can fail)",
          "surprise" in kept["proposed_config"]["manual_capture"], str(kept["proposed_config"]["manual_capture"]))


def reinstall_equals_fresh() -> None:
    """Fresh = the template. An old config with keys missing, order reversed, older note texts and
    retired keys must end as the template, byte for byte."""
    old = copy.deepcopy(TEMPLATE)
    for key in ("handoffs", "prompts", "retro", "records_policy", "format_changed", "format_all",
                "requirements_sources", "strategy_documents", "metrics", "records_policy_note", "retro_note"):
        del old[key]
    del old["environment"]["access"]
    old["audit_cadence_days"] = 30
    history_keys = [k for k, m in KEYS["notes"].items() if len(m["note_history"]) > 1 and k in old]
    check("setup: the table holds notes with an earlier text", len(history_keys) >= 3, str(history_keys))
    for key in history_keys:
        old[key] = KEYS["notes"][key]["note_history"][0]
    old = dict(reversed(list(old.items())))
    old["environment"] = dict(reversed(list(old["environment"].items())))
    plan = plan_of(old)
    check_eq("K3 reinstall: the old config ends as the template, byte for byte",
             json.dumps(plan["proposed_config"], indent=2), json.dumps(TEMPLATE, indent=2))
    check_eq("K3 reinstall: earlier TEMPLATE texts of a note move nothing", plan["answers_legacy"], {})
    check("C4 reinstall: both reordered objects are listed", {"/", "/environment"} <= set(plan["reordered"]),
          str(plan["reordered"]))
    check_eq("K3 reinstall: the template itself is a fixed point with nothing listed - EXCEPT that it now opens exactly `/environment/access` "
             "(t-298, the Lead's decision: the key's template default is empty, i.e. 'not recorded', so it is asked until answered, "
             "and the template IS that default; nothing else changes)",
             {k: ([r["path"] for r in plan_of(TEMPLATE)[k]] if k == "reasked" else plan_of(TEMPLATE)[k])
              for k in ("removed", "renamed", "reasked", "added", "kept", "reordered", "answers_legacy", "changes", "conflicts")},
             {"removed": [], "renamed": [], "reasked": ["/environment/access"], "added": [], "kept": [], "reordered": [],
              "answers_legacy": {}, "changes": [], "conflicts": []})


# --- C5: notes ---------------------------------------------------------------------------------

def notes() -> None:
    key = "app_root_note"
    history = KEYS["notes"][key]["note_history"]
    base = {"schema_version": 1}
    for text in history:
        plan = plan_of({**base, key: text})
        check(f"C5: a known text of {key} resets to the current one, nothing moves ({text[:24]}...)",
              plan["proposed_config"][key] == TEMPLATE[key] and plan["answers_legacy"] == {}
              and "answers_legacy" not in plan["proposed_config"])
    for other in [k for k, m in KEYS["notes"].items() if len(m["note_history"]) > 1]:
        for text in KEYS["notes"][other]["note_history"]:
            plan = plan_of({**base, other: text})
            if plan["answers_legacy"]:
                check(f"C5: a known text of {other} moved nothing", False, text[:40])
                break
        else:
            continue
        break
    else:
        check("C5: every known text of every note resets without moving anything", True)
    person = "Resolves to the common parent of the two repositories (this project's own words)."
    plan = plan_of({**base, key: person})
    check_eq("C5: a person's text moves whole into answers_legacy.<key>",
             plan["proposed_config"].get("answers_legacy"), {key: person})
    check_eq("C5: and the note is the current template text", plan["proposed_config"][key], TEMPLATE[key])
    check_eq("C5: the plan names what moved", plan["answers_legacy"], {key: person})
    # never overwrite an existing entry; a second move appends under <key>@<package_version>
    held = {**base, key: "second text", "answers_legacy": {key: "first text"}}
    plan = plan_of(held)
    check_eq("C5: an existing answers_legacy.<key> is never overwritten",
             plan["proposed_config"].get("answers_legacy", {}).get(key), "first text")
    check_eq("C5: the second move lands under <key>@<package_version>",
             plan["proposed_config"].get("answers_legacy", {}).get(f"{key}@{VERSION}"), "second text")
    third = plan_of({**base, key: "third text", "answers_legacy": plan["proposed_config"].get("answers_legacy", {})})
    check_eq("C5: a third move never overwrites either",
             {k: v for k, v in third["proposed_config"].get("answers_legacy", {}).items()},
             {key: "first text", f"{key}@{VERSION}": "second text", f"{key}@{VERSION}#2": "third text"})
    same = plan_of({**base, key: "first text", "answers_legacy": {key: "first text"}})
    check_eq("C5: a text already kept under answers_legacy is not stored twice",
             (same["answers_legacy"], same["proposed_config"].get("answers_legacy")), ({}, {key: "first text"}))
    check_eq("C5: the note is reset in both cases", same["proposed_config"][key], TEMPLATE[key])
    # a note that is not a template key stays, listed; a non-string or empty note is handled
    free = plan_of({**base, "my_own_note": "mine", "x_note": "also mine"})
    check_eq("C5: a note with no template key is kept as it is",
             (free["proposed_config"]["my_own_note"], free["proposed_config"]["x_note"]), ("mine", "also mine"))
    check_eq("C5: ... and listed as kept: not a template key",
             sorted((r["path"], r["reason"]) for r in free["kept"]),
             [("/my_own_note", "kept: not a template key"), ("/x_note", "kept: not a template key")])
    check_eq("C5: a kept note moves nothing", free["answers_legacy"], {})
    odd = plan_of({**base, key: {"not": "text"}})
    check_eq("C5: a note that is not text is a person's answer: kept whole",
             odd["proposed_config"].get("answers_legacy"), {key: {"not": "text"}})
    empty = plan_of({**base, key: "   "})
    check("C5: an empty note carries nothing to keep",
          empty["proposed_config"][key] == TEMPLATE[key] and empty["answers_legacy"] == {})
    broken = plan_of({**base, key: "words", "answers_legacy": "not an object"})
    check("C5: an answers_legacy that is not an object is an open question, not a crash",
          any(c["path"] == "/answers_legacy" for c in broken["conflicts"]))


def turns_note_history() -> None:
    """SC1-6 fix round (F2, t-1318): the turn-budget note lost its sentence "the same call again proceeds". The
    old text stays in `note_history` (APPENDED to, never edited), which is the only way `settle_note` knows a text as
    the factory's own: edit the old entries and a project holding them would have its factory text moved to
    `answers_legacy` as a person's words."""
    key = "turns_note"
    history = KEYS["notes"][key]["note_history"]
    old_text = "same call again proceeds"
    check_eq("F2: the table's last text IS the template's", history[-1], TEMPLATE[key])
    check("F2: the template no longer promises 'the same call again proceeds'", old_text not in TEMPLATE[key])
    previous = [t for t in history if old_text in t]
    check_eq("F2: both earlier texts stay in the history, unedited", len(previous), 2)
    base = {"schema_version": 1}
    for text in previous:
        plan = plan_of({**base, key: text})
        check_eq("F2: a project holding an earlier text settles to the new one", plan["proposed_config"][key], TEMPLATE[key])
        check_eq("F2: and nothing goes to answers_legacy (it stays a factory note)",
                 (plan["answers_legacy"], "answers_legacy" in plan["proposed_config"]), ({}, False))
    edited = "Our own turn budget words: ask the lead before the second notice."
    plan = plan_of({**base, key: edited})
    check_eq("F2: a note the person edited is a person's text, kept whole under answers_legacy",
             plan["proposed_config"].get("answers_legacy"), {key: edited})
    check_eq("F2: a config with no turns_note gets the template value",
             plan_of(dict(base))["proposed_config"][key], TEMPLATE[key])


# --- the removed / renamed / reasked tables, on a table of the test's own ----------------------

def tables() -> None:
    tmpl = {"schema_version": 1, "alpha": "a-default", "beta": "b-default", "gamma": {"x": 1}}
    table = {"keys": {"schema_version": {"since": "0.1.0", "absent_means": "required"},
                      "alpha": {"since": "0.2.0", "absent_means": "default"},
                      "beta": {"since": "0.3.0", "absent_means": "default"},
                      "gamma": {"since": "0.3.0", "absent_means": "default"},
                      "gamma.y": {"since": "0.4.0", "absent_means": "default"}},
             "notes": {}, "removed": {"old_key": {"reason": "nothing reads it"}, "gamma.legacy": {"reason": "moved"}},
             "renamed": {"was_named": "beta"},
             "reasked": {"alpha": {"question": "What does alpha mean now?"}}}
    tmpl["gamma"] = {"x": 1, "y": 2}
    old = {"old_key": 1, "was_named": "carried value", "alpha": "changed by a person", "gamma": {"legacy": 1, "x": 5}}
    plan = C.migration_plan(old, template=tmpl, keys=table)
    got = plan["proposed_config"]
    check_eq("tables: removed key and nested removed key are gone", ("old_key" in got, "legacy" in got["gamma"]), (False, False))
    check_eq("tables: removed[] carries path, old value and the table's reason",
             [(r["path"], r["was"], r["reason"]) for r in plan["removed"]],
             [("/old_key", 1, "nothing reads it"), ("/gamma/legacy", 1, "moved")])
    check_eq("tables: renamed moves the value, the old name is gone", (got["beta"], "was_named" in got), ("carried value", False))
    check_eq("tables: renamed[] lists from, to and the value",
             plan["renamed"], [{"from": "/was_named", "to": "/beta", "value": "carried value"}])
    check_eq("tables: a reasked key is not carried: the template default stands in", got["alpha"], "a-default")
    check_eq("tables: reasked[] says what it was and the question",
             plan["reasked"], [{"path": "/alpha", "was": "changed by a person",
                                "question": "What does alpha mean now?"}])
    check_eq("tables: a nested key from the table is added when missing", got["gamma"], {"x": 5, "y": 2})
    check("tables: ... and listed", {"path": "/gamma/y", "since": "0.4.0", "absent_means": "default"} in plan["added"])
    again = C.migration_plan(got, template=tmpl, keys=table)
    check_eq("tables: planning the result again re-asks nothing (the default is what stands)",
             (again["reasked"], again["removed"], again["renamed"]), ([], [], []))
    both = C.migration_plan({"was_named": "old", "beta": "new", "schema_version": 1}, template=tmpl, keys=table)
    check("tables: a renamed key whose new name is also set is a question, both values kept",
          any(c["path"] == "/beta" for c in both["conflicts"]) and both["proposed_config"]["was_named"] == "old"
          and both["proposed_config"]["beta"] == "new")
    gone = C.migration_plan({"schema_version": 1, "alpha": "a-default"},
                            template={k: v for k, v in tmpl.items() if k != "alpha"},
                            keys=table_with(removed={}, renamed={}, reasked={"alpha": {"question": "?"}}))
    check("tables: a reasked key the template no longer has is dropped and listed",
          "alpha" not in gone["proposed_config"] and gone["reasked"][0]["was"] == "a-default")
    kept_by_template = C.migration_plan({"schema_version": 1, "alpha": "x"}, template=tmpl,
                                        keys=table_with(removed={"alpha": {"reason": "r"}}, renamed={}, reasked={}))
    check("tables: a key the template carries is never treated as removed",
          kept_by_template["proposed_config"]["alpha"] == "x" and kept_by_template["removed"] == [])


def legacy_commands() -> None:
    conflict = plan_of({"schema_version": 1, "external_writes": {
        "commands": {"jira": "old"}, "channels": {"jira": {"method": "command", "command": "new"}}}})
    check("legacy: while a command conflicts, the old map stays as the evidence",
          conflict["proposed_config"]["external_writes"].get("commands") == {"jira": "old"}
          and len(conflict["conflicts"]) == 1 and conflict["removed"] == [])
    clean = plan_of({"schema_version": 1, "external_writes": {"commands": {"jira": "deliver"}, "channels": {}}})
    check("legacy: a copied command map is removed after the copy and listed",
          "commands" not in clean["proposed_config"]["external_writes"]
          and clean["proposed_config"]["external_writes"]["channels"]["jira"]["command"] == "deliver"
          and [r["path"] for r in clean["removed"]] == ["/external_writes/commands"])


# --- K14: the machine-local gate and the launch commands it drops ------------------------------

def machine_local() -> None:
    refused = {"C:" + B + "Py" + B + "python.exe": "drive path", "c:/x": "drive path, slash",
               B + B + "srv" + B + "s": "UNC", "/usr/bin/python": "posix absolute", "~/x": "home",
               "%TEMP%" + B + "x": "percent variable", "$HOME/x": "shell variable", "C:foo": "drive-relative",
               "--config=C:" + B + "x": "option with a path", }
    for value, why in refused.items():
        check(f"K14: machine-local: {value!r} ({why})", _machine_local(value) is True)
    check("K14: machine-local: a LIST argv holding one of them", _machine_local(["python", "-m", "C:" + B + "x"]) is True)
    check("K14: machine-local: a list whose LAST item is the only one", _machine_local(["a", "b", "/usr/bin/x"]) is True)
    check("K14: machine-local: a quoted value", _machine_local('"C:' + B + 'Program Files' + B + 'x.exe"') is True)
    for value in ("../testproject1", "./run.sh", "poetry", "{python}", "{plugin_root}/scripts/x.py"):
        check(f"K14: portable kept: {value!r}", _machine_local(value) is False)
    check("K14: portable kept: a list of portable tokens", _machine_local(["{python}", "{plugin_root}/scripts/x.py", "-q"]) is False)
    check("K14: portable kept: empty, None, empty list", [_machine_local(v) for v in ("", None, [], [""])] == [False] * 4)
    check("K14: an option value that is portable stays portable", _machine_local("--config=./x.ini") is False)

    probes = {
        "abs": {"argv": ["C:" + B + "Py" + B + "python.exe", "x.py"], "cwd": ".", "timeout_s": 30},
        "cwd": {"argv": ["{python}", "x.py"], "cwd": "/srv/work", "timeout_s": 30},
        "opt": {"argv": ["{python}", "--config=C:" + B + "x"], "cwd": ".", "timeout_s": 30},
        "env": {"argv": ["$HOME/bin/py"], "cwd": ".", "timeout_s": 30},
        "ok": {"argv": ["{python}", "{plugin_root}/scripts/runtime_probe.py"], "cwd": ".", "timeout_s": 30},
        "rel": {"argv": ["poetry", "run", "python"], "cwd": "../testproject1", "timeout_s": 30},
    }
    plan = plan_of({"schema_version": 1, "execution": {"runtime_probes": copy.deepcopy(probes)}})
    kept = plan["proposed_config"]["execution"]["runtime_probes"]
    check_eq("K14: only the portable runtime probes survive the plan", sorted(kept), ["ok", "rel"])
    check_eq("K14: the portable ones are carried unchanged", {k: kept[k] for k in kept}, {k: probes[k] for k in ("ok", "rel")})
    check_eq("K14: each dropped one is listed with the old spec",
             sorted((r["path"], r["was"] == probes[r["path"].rsplit("/", 1)[1]]) for r in plan["removed"]),
             sorted((f"/execution/runtime_probes/{k}", True) for k in ("abs", "cwd", "opt", "env")))
    for malformed in ({"api": "text"}, [], None):
        got = plan_of({"schema_version": 1, "execution": {"runtime_probes": malformed}})
        check(f"K14: runtime_probes of a shape the plan does not know ({malformed!r}) is left alone, no crash",
              got["proposed_config"]["execution"]["runtime_probes"] == malformed or malformed is None)
    k42_a_container_path_in_a_probe_survives_the_migration()


def k42_a_container_path_in_a_probe_survives_the_migration() -> None:
    """K42 (t-300 Q5, B-260 first half): `--app-root /app` is a place INSIDE the stand's container, the same on every machine.
    The migration judged the probe with the plain gate over the whole argv, which reads a leading slash as a place on the
    writing machine, and dropped BOTH cmp2r probes on every reinstall - and with no probe the build question has nothing
    to ask. It now judges one probe entry with audit A20's own container-aware gate."""
    cmp2r = {"argv": ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--profile", "e2e-ui", "--environment", "localhost",
                      "--container", "testproject1-dev-fresh-testproject1-ui-static-1", "--checkout", "../../testproject1-ui", "--app-root", "/app"],
             "cwd": ".", "timeout_s": 120}
    api = {**cmp2r, "argv": [a if a != "../../testproject1-ui" else "../../testproject1" for a in cmp2r["argv"]]}
    plan = plan_of({"schema_version": 1, "execution": {"runtime_probes": {"e2e-ui": copy.deepcopy(cmp2r), "api": copy.deepcopy(api)}}})
    kept = plan["proposed_config"]["execution"]["runtime_probes"]
    check_eq("K42: an entry with `--app-root /app` and `--checkout ../../testproject1-ui` survives the migration, unchanged",
             (sorted(kept), kept.get("e2e-ui") == cmp2r, kept.get("api") == api), (["api", "e2e-ui"], True, True))
    check_eq("K42: and nothing about the probes is listed as removed", [r["path"] for r in plan["removed"] if "runtime_probes" in r["path"]], [])
    equals = copy.deepcopy(cmp2r)
    equals["argv"][equals["argv"].index("--app-root") + 1] = "/app"
    spelled = copy.deepcopy(cmp2r)
    spelled["argv"] = [a for a in spelled["argv"] if a != "--app-root" and a != "/app"] + ["--app-root=/srv/app"]
    check_eq("K42: `--app-root=/srv/app` (the same flag in its `=` spelling) is a container path too",
             sorted(plan_of({"schema_version": 1, "execution": {"runtime_probes": {"x": spelled}}})["proposed_config"]["execution"]["runtime_probes"]), ["x"])
    # CONTROLS: what the gate drops, it still drops
    absolute_interpreter = {**cmp2r, "argv": ["C:" + B + "Py" + B + "python.exe", *cmp2r["argv"][1:]]}
    absolute_checkout = {**cmp2r, "argv": [a if a != "../../testproject1-ui" else "/home/ann/testproject1-ui" for a in cmp2r["argv"]]}
    drive_checkout = {**cmp2r, "argv": [a if a != "../../testproject1-ui" else "D:/work/testproject1-ui" for a in cmp2r["argv"]]}
    absolute_cwd = {**cmp2r, "cwd": "/srv/work"}
    absolute_script = {**cmp2r, "argv": ["{python}", "/opt/probes/probe.py", *cmp2r["argv"][2:]]}
    dropped = plan_of({"schema_version": 1, "execution": {"runtime_probes": {
        "interpreter": absolute_interpreter, "checkout": absolute_checkout, "drive": drive_checkout, "cwd": absolute_cwd,
        "script": absolute_script, "keep": copy.deepcopy(cmp2r)}}})
    check_eq("K42 CONTROL: an absolute argv[1] / interpreter / checkout / drive / cwd is STILL dropped; the container path alone keeps nothing it should not",
             (sorted(dropped["proposed_config"]["execution"]["runtime_probes"]),
              sorted(r["path"].rsplit("/", 1)[1] for r in dropped["removed"] if "runtime_probes" in r["path"])),
             (["keep"], ["checkout", "cwd", "drive", "interpreter", "script"]))
    check_eq("K42 CONTROL: a container path does not hide a machine path in the SAME argv (`--app-root /app` + `--checkout /home/ann/x`)",
             "checkout" in [r["path"].rsplit("/", 1)[1] for r in dropped["removed"]], True)


# --- the proposal shape, the doors, no config at all --------------------------------------------

SHAPE = {"schema_version", "input_hash", "proposal_hash", "proposed_config", "conflicts", "changes", "removed",
         "renamed", "reasked", "answers_legacy", "added", "kept", "reordered", "deprecated_keys", "evidence_refs"}


def none_case() -> None:
    fresh = plan_of(None)
    check_eq("None: the proposal has the same fields as any other (one shape, G1)", set(fresh), SHAPE)
    check_eq("None: and the same fields as a plan over a config", set(plan_of(fixture())), SHAPE)
    check("None: proposed_config is None - the role fills it from discovery, the code invents nothing",
          fresh["proposed_config"] is None)
    check_eq("None: removed, renamed, reasked and the rest are empty",
             [fresh[k] for k in ("removed", "renamed", "reasked", "added", "kept", "reordered", "changes", "conflicts")],
             [[]] * 8)
    check_eq("None: answers_legacy is empty", fresh["answers_legacy"], {})
    check_eq("None: input_hash is the hash of nothing", fresh["input_hash"], C._json_hash(None))
    check_eq("None: the proposal is sealed", fresh["proposal_hash"], C.proposal_hash(fresh))
    check("None: an answer to a price question with no config is a no-op",
          plan_of(None, price_table_answer="builtin")["proposed_config"] is None)
    check("a config that is not an object is refused", "must be a JSON object" in message_of(lambda: plan_of([1])))
    check("an unknown price answer is still refused", "must be one of" in message_of(lambda: plan_of(None, price_table_answer="x")))


def no_config_tree() -> None:
    root = temp_dir("qa-config-none-")
    try:
        check("read_config_file: no qa-factory/config.json is None, not an error", C.read_config_file(root) is None)
        shown = run_script("config_contract.py", "--root", root, "--migration-plan")
        check_eq("None CLI: --migration-plan on a tree with no config exits 0", shown.returncode, 0)
        plan = json.loads(shown.stdout) if shown.returncode == 0 else {}
        check("None CLI: ... and prints the empty-input proposal", plan.get("proposed_config", 1) is None
              and set(plan) == SHAPE, shown.stderr[-300:])
        check("None CLI: nothing was written by a plan", not (root / "qa-factory").exists())
        proposal = root / "p.json"
        proposal.write_text(json.dumps(plan), encoding="utf-8")
        rec = run_script("config_contract.py", "--root", root, "--record-approval", proposal,
                         "--approval-ref", "onboarding:a1", "--evidence-ref", "t:1")
        check("None CLI: --record-approval of a proposal with no proposed_config is refused, no traceback",
              rec.returncode == 1 and "proposed_config" in rec.stderr and "Traceback" not in rec.stderr,
              rec.stderr[-300:])
        app = run_script("config_contract.py", "--root", root, "--apply", proposal, "--approval-ref", "onboarding:a1")
        check("None CLI: --apply with no config and no recorded approval is refused, no traceback",
              app.returncode == 1 and "approval" in app.stderr and "Traceback" not in app.stderr, app.stderr[-300:])
        for flag in ("--validate", "--check-environment"):
            got = run_script("config_contract.py", "--root", root, flag)
            check(f"None CLI: {flag} says there is nothing to read and how to get one",
                  got.returncode == 1 and "qa-onboarding" in got.stderr and "Traceback" not in got.stderr, got.stderr[-300:])
    finally:
        cleanup(root)


def fresh_flow() -> None:
    """The fresh install through the SAME approval and apply path: no config.json, a role-filled
    proposal sealed with proposal_hash, approved, applied."""
    root = temp_dir("qa-config-fresh-")
    try:
        fresh = plan_of(None)
        filled = copy.deepcopy(TEMPLATE)
        filled["tests_root"] = "tests"
        fresh["proposed_config"] = filled
        seal(fresh)
        check("fresh: not approved before anyone said yes", C.is_approved(root, fresh) is False)
        C.record_approval(root, fresh, "onboarding:fresh-1", "transcript:1")
        check("fresh: approved after the word, no question needed again (FR-7)", C.is_approved(root, fresh) is True)
        backup = C.apply_plan(root, fresh, "onboarding:fresh-1")
        written = (root / "qa-factory" / "config.json").read_text(encoding="utf-8")
        check_eq("fresh: the config is written, canonical bytes", written, json.dumps(filled, indent=2, ensure_ascii=False) + "\n")
        check("O2-4 fresh: there was nothing to back up, so no backup path is returned", backup is None)
        check_eq("O2-4 fresh: no config-migrations directory and no backup file is created",
                 (root / "qa-factory" / "records" / "config-migrations").exists(), False)
        check_eq("O2-4 fresh: the only thing under records/ is the approval log the word was recorded in",
                 sorted(p.name for p in (root / "qa-factory" / "records").iterdir()), ["onboarding-approvals.jsonl"])
        check_eq("fresh: and now the project has a config the plan reads", plan_of(C.read_config_file(root))["removed"], [])
        stale = message_of(lambda: C.record_approval(root, fresh, "onboarding:fresh-2", "transcript:2"))
        check_in("fresh: the same fresh proposal is stale once the config exists", "stale", stale)
    finally:
        cleanup(root)


def unreadable_config() -> None:
    door_words = ("fix the file by hand", "move it aside")
    cases = {"empty file": "", "whitespace only": "  \n\t\n", "invalid JSON": "{", "trailing comma": '{"a": 1,}',
             "a JSON list": "[1, 2]", "a JSON string": '"x"', "a null": "null"}
    for name, text in cases.items():
        root = temp_dir("qa-config-bad-")
        try:
            (root / "qa-factory").mkdir()
            (root / "qa-factory" / "config.json").write_text(text, encoding="utf-8")
            problem = message_of(lambda: C.read_config_file(root))
            check(f"door ({name}): read_config_file refuses with ConfigUnreadable", problem.startswith("ConfigUnreadable"), problem)
            check(f"door ({name}): the message names what is wrong, what is expected and both ways out",
                  all(w in problem for w in door_words) and "JSON object" in problem, problem)
            for flag in ("--migration-plan", "--validate", "--check-environment"):
                out = run_script("config_contract.py", "--root", root, flag)
                check(f"door ({name}): {flag} exits 2 with the door on stderr, no traceback, nothing on stdout",
                      out.returncode == 2 and all(w in out.stderr for w in door_words) and "Traceback" not in out.stderr
                      and out.stdout == "", f"{out.returncode} {out.stderr[-200:]}")
            # a sealed proposal that is fine in itself: only the config on disk is the trouble. The
            # approval it needs for --apply was recorded while the config was still readable.
            proposal = seal({**plan_of(None), "proposed_config": copy.deepcopy(TEMPLATE)})
            pr = root / "p.json"
            pr.write_text(json.dumps(proposal), encoding="utf-8")
            good = root / "qa-factory" / "config.json"
            good.unlink()
            C.record_approval(root, proposal, "r:1", "t:1")
            good.write_text(text, encoding="utf-8")
            for flag, extra in (("--record-approval", ["--evidence-ref", "t:2"]), ("--apply", [])):
                out = run_script("config_contract.py", "--root", root, flag, pr, "--approval-ref", "r:1", *extra)
                check(f"door ({name}): {flag} refuses the same way",
                      out.returncode == 2 and all(w in out.stderr for w in door_words), out.stderr[-200:])
            check(f"door ({name}): the unreadable file is never touched", good.read_text(encoding="utf-8") == text)
        finally:
            cleanup(root)
    root = temp_dir("qa-config-bom-")
    try:
        (root / "qa-factory").mkdir()
        (root / "qa-factory" / "config.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"schema_version": 1}).encode("utf-8"))
        check_eq("a byte-order mark in front of valid JSON is tolerated", C.read_config_file(root), {"schema_version": 1})
    finally:
        cleanup(root)


# --- schema_version: named, never a crash -------------------------------------------------------

def schema_version() -> None:
    for found in (2, 0, "1", True, None, 1.5):
        plan = plan_of({"schema_version": found})
        row = [c for c in plan["conflicts"] if c["path"] == "/schema_version"]
        check(f"schema {found!r}: named in the result as an open question carrying the found value",
              len(row) == 1 and row[0]["current"] == found and "schema_version" in row[0]["question"], str(plan["conflicts"]))
        check(f"schema {found!r}: the value is not rewritten", plan["proposed_config"]["schema_version"] == found)
    root = temp_dir("qa-config-schema2-")
    try:
        (root / "qa-factory").mkdir()
        old = {"schema_version": 2}
        (root / "qa-factory" / "config.json").write_text(json.dumps(old), encoding="utf-8")
        plan = plan_of(old)
        C.record_approval(root, plan, "onboarding:s2", "t:1")
        check_in("schema 2: apply refuses, naming the open question", "unresolved conflicts",
                 message_of(lambda: C.apply_plan(root, plan, "onboarding:s2")))
    finally:
        cleanup(root)
    absent = plan_of({"app_root": "."})
    check("schema missing: it is a missing template key - added as 1, listed, no question",
          absent["proposed_config"]["schema_version"] == 1 and not absent["conflicts"]
          and "/schema_version" in [a["path"] for a in absent["added"]])
    check_eq("schema_version stays 1 in the template and in the code", (TEMPLATE["schema_version"], C.SCHEMA_VERSION), (1, 1))
    check("schema 1 raises no question", plan_of({"schema_version": 1})["conflicts"] == [])


# --- C2: an approval is of the proposal, never of its input alone --------------------------------

def approval() -> None:
    base = plan_of(old_generation_config(), price_table_answer="builtin")
    for part, change in (("proposed_config", lambda p: p["proposed_config"].update(dod="changed")),
                         ("removed", lambda p: p["removed"].append({"path": "/x"})),
                         ("renamed", lambda p: p["renamed"].append({"from": "/a", "to": "/b"})),
                         ("answers_legacy", lambda p: p["answers_legacy"].update(k="v")),
                         ("conflicts", lambda p: p["conflicts"].append({"path": "/c"})),
                         ("reasked", lambda p: p["reasked"].append({"path": "/r"})),
                         ("added", lambda p: p["added"].append({"path": "/dod", "since": "0.1.0", "absent_means": "required"})),
                         ("listing", lambda p: p.__setitem__("listing", {"retire": ["a"]}))):
        other = copy.deepcopy(base)
        change(other)
        check(f"C2: proposal_hash covers {part}", C.proposal_hash(other) != base["proposal_hash"])
    for part, change in (("input_hash", lambda p: p.__setitem__("input_hash", "x")),
                         ("changes", lambda p: p["changes"].append({"path": "/x"})),
                         ("kept", lambda p: p["kept"].append({"path": "/x", "reason": "r"}))):
        other = copy.deepcopy(base)
        change(other)
        check(f"C2: proposal_hash does not move with {part} (apply_plan checks input_hash against the file itself)",
              C.proposal_hash(other) == base["proposal_hash"])
    check("C2: the extra hook is part of the hash", C.proposal_hash(base, {"k": 1}) != C.proposal_hash(base))
    check("C2: ... and the same extra gives the same hash", C.proposal_hash(base, {"k": 1}) == C.proposal_hash(base, {"k": 1}))

    root = temp_project("qa-config-approval-")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        old = old_generation_config()
        cfg_path.write_text(json.dumps(old), encoding="utf-8")
        plan = plan_of(old, price_table_answer="builtin", answers={"/environment/access": ACCESS})   # t-298: this config records no access
        check("C2: nothing approved yet: is_approved says no", C.is_approved(root, plan) is False)
        C.record_approval(root, plan, "onboarding:c2", "transcript:c2")
        check("C2/FR-7: the same proposal_hash approved -> is_approved true without a question", C.is_approved(root, plan) is True)
        # the same INPUT, a different proposal: input_hash alone never counts
        other = plan_of(old, price_table_answer="builtin",
                        keys=table_with(removed={**KEYS["removed"], "execution_note": {"reason": "test"}}))
        check_eq("C2 setup: the two proposals share their input", other["input_hash"], plan["input_hash"])
        check("C2 setup: and differ in content", other["proposal_hash"] != plan["proposal_hash"])
        check("C2: same input_hash, another proposal_hash: NOT approved", C.is_approved(root, other) is False)
        check_in("C2: and apply refuses it", "does not authorize", message_of(lambda: C.apply_plan(root, other, "onboarding:c2")))
        # a forged hash on changed content
        forged = copy.deepcopy(plan)
        forged["proposed_config"]["dod"] = "forged"
        check("C2: an approved proposal_hash pasted onto other content is not approved", C.is_approved(root, forged) is False)
        check_in("C2: and apply refuses it as an invalid hash", "proposal hash is invalid",
                 message_of(lambda: C.apply_plan(root, forged, "onboarding:c2")))
        # the same content from another input: approved as a proposal; apply still compares the input with the file
        moved = copy.deepcopy(plan)
        moved["input_hash"] = "0" * 64
        check("C2: the same proposed content with another input_hash is the approved proposal", C.is_approved(root, moved) is True)
        check_in("C2: but apply compares the input with the config on disk", "does not match current config",
                 message_of(lambda: C.apply_plan(root, moved, "onboarding:c2")))
        # a recorded decision that is not 'approved' counts for nothing
        log = root / "qa-factory" / "records" / "onboarding-approvals.jsonl"
        good = log.read_text(encoding="utf-8")
        record = json.loads(good.splitlines()[0])
        log.write_text(json.dumps({**record, "status": "rejected"}) + "\n", encoding="utf-8")
        check("C2: a record whose status is not approved is not an approval", C.is_approved(root, plan) is False)
        log.write_text("not json\n" + good, encoding="utf-8")
        check("C2: a log line that cannot be read is skipped; a readable approval after it still counts",
              C.is_approved(root, plan) is True)
        log.write_text("not json\n", encoding="utf-8")
        check("C2: a log with nothing readable approves nothing (asked again: a question too many, never a silent pass)",
              C.is_approved(root, plan) is False)
        log.unlink()
        check("C2: no approvals log: not approved", C.is_approved(root, plan) is False)
        log.write_text(good, encoding="utf-8")
        # the whole flow, then the written bytes
        backup = C.apply_plan(root, plan, "onboarding:c2")
        written = cfg_path.read_text(encoding="utf-8")
        check_eq("flow: the config on disk is the proposal, canonical bytes",
                 written, json.dumps(plan["proposed_config"], indent=2, ensure_ascii=False) + "\n")
        check_eq("flow: the backup keeps the old config whole", json.loads(backup.read_text(encoding="utf-8"))["config"], old)
        check("flow: the written config validates", C.validate(json.loads(written)) == [])
        again = plan_of(json.loads(written), price_table_answer="builtin")
        check("flow: a plan over the written config has nothing to ask and nothing to change",
              not again["conflicts"] and not again["removed"] and not again["added"] and not again["answers_legacy"]
              and not again["reordered"])
        check("FR-7 flow: the first proposal is not asked about again, and a new one over the result is a new question",
              C.is_approved(root, plan) is True and C.is_approved(root, again) is False)
        check("an approved proposal with a listing: the listing is part of what was approved",
              C.is_approved(root, {**plan, "listing": {"retire": ["x"]}}) is False)
    finally:
        cleanup(root)
    listing = copy.deepcopy(base)
    listing["listing"] = {"retire": ["a"]}
    listing["proposal_hash"] = C.proposal_hash(listing)
    check("C2: a proposal that carries a listing is sealed over it and checks out", C.proposal_hash(listing) == listing["proposal_hash"])
    check("C2: the extra hook flows through is_approved", C.is_approved(temp_dir("qa-none-"), listing, extra={"n": 1}) is False)


# --- O2-1: the fill reaches the keys nested in template objects --------------------------------

def deep_fill() -> None:
    tmpl = {"schema_version": 1,
            "a": {"x": 1, "inner": {"deep": 2, "leaf_list": [1, 2]}, "items": [{"id": "t"}], "opts": {}},
            "scalar_here": {"k": 1}, "lst": [], "holder": {"note": "T", "v": 5}, "plain": {"p": 1}}
    keys = {"keys": {"schema_version": {"since": "0.1.0", "absent_means": "required"},
                     "a": {"since": "0.2.0", "absent_means": "default"},
                     "scalar_here": {"since": "0.3.0", "absent_means": "default"},
                     "lst": {"since": "0.3.0", "absent_means": "default"},
                     "holder": {"since": "0.4.0", "absent_means": "default"},
                     "plain": {"since": "0.5.0", "absent_means": "default"},
                     "a.inner.deep": {"since": "0.9.0", "absent_means": "required"}},
            "notes": {"holder.note": {"since": "0.4.5", "note_history": ["T"]}},
            "removed": {}, "renamed": {}, "reasked": {}}
    old = {"schema_version": 1, "a": {"inner": {}, "items": ["mine"], "opts": {"mine": 1}}, "scalar_here": "text",
           "lst": ["kept"], "plain": {"p": 7}}
    before = copy.deepcopy(old)
    plan = C.migration_plan(old, template=tmpl, keys=keys)
    got = plan["proposed_config"]
    check_eq("O2-1: the input is not touched", old, before)
    check_eq("O2-1: a nested key is filled at any depth (a.x, a.inner.deep)", (got["a"]["x"], got["a"]["inner"]["deep"]), (1, 2))
    check_eq("O2-1: a template LIST is never filled into (a.items keeps only the person's entry, lst too)",
             (got["a"]["items"], got["lst"], got["a"]["inner"].get("leaf_list")), (["mine"], ["kept"], [1, 2]))
    check_eq("O2-1: ...an existing value of any type is kept, an existing object is never replaced",
             (got["a"]["opts"], got["plain"]), ({"mine": 1}, {"p": 7}))
    check_eq("O2-1: an existing scalar where the template has an object is NOT overwritten",
             got["scalar_here"], "text")
    check_eq("O2-1: ...it is an open question naming the pointer and the value (a conflicts row)",
             [(c["path"], c["current"]) for c in plan["conflicts"]], [("/scalar_here", "text")])
    check_in("O2-1: ...in the person's words, not the code's", "fix it by hand", plan["conflicts"][0]["question"])
    rows = {r["path"]: r for r in plan["added"]}
    check_eq("O2-1: every filled nested key is an added row with its pointer",
             sorted(rows), ["/a/inner/deep", "/a/inner/leaf_list", "/a/x", "/holder"])
    check_eq("O2-1: a nested key inherits the top-level key's since and is `default`",
             (rows["/a/x"]["since"], rows["/a/x"]["absent_means"], rows["/a/inner/leaf_list"]["since"]), ("0.2.0", "default", "0.2.0"))
    check_eq("O2-1: a pointer the table lists keeps its own since and absent_means",
             (rows["/a/inner/deep"]["since"], rows["/a/inner/deep"]["absent_means"]), ("0.9.0", "required"))
    check_eq("O2-1: an object that was absent is added whole, as ONE row (its nested keys are not listed again)",
             (got["holder"], [p for p in rows if p.startswith("/holder")]), ({"note": "T", "v": 5}, ["/holder"]))
    again = C.migration_plan(got, template=tmpl, keys=keys)
    check_eq("O2-1: a second plan over the result fills nothing more", again["added"], [])
    wrong = C.migration_plan({"schema_version": 1, "plain": None}, template=tmpl, keys=keys)
    check_eq("O2-1: null where the template has an object is a value too: kept, and a question",
             (wrong["proposed_config"]["plain"], [c["path"] for c in wrong["conflicts"]]), (None, ["/plain"]))
    numbers = C.migration_plan({"schema_version": 1, "impact_scale": {"money": 3}})
    check_eq("O2-1: a numeric impact class has ONE question, not two (the older numeric-multiplier one stands)",
             [c["path"] for c in numbers["conflicts"]], ["/impact_scale/money"])
    check_eq("O2-1: ...and the person's number is still there", numbers["proposed_config"]["impact_scale"]["money"], 3)


def fill_missing_keys_copies_what_it_fills() -> None:
    """t-442 (canon part D). A value filled from the template is the person's own copy: filling two configurations from one
    template and then editing the first leaves the second and the template as they were (no aliasing). KILLS: the filled value
    shared with the template (`node[key] = value`)."""
    template = {"holder": {"note": "T", "tags": ["a"]}, "group": {"inner": {"list": [1, 2]}}, "scalar": 5}
    pristine = copy.deepcopy(template)
    first, second = {}, {"group": {}}
    added_first, added_second = [], []
    C.fill_missing_keys(first, template, [], added_first, [], lambda parts: "/".join(parts))
    C.fill_missing_keys(second, template, [], added_second, [], lambda parts: "/".join(parts))
    check_eq("O2-1 copy: the first node is filled whole from the template", first, pristine)
    check_eq("O2-1 copy: the second node is filled at its own depth (group.inner), and the rows say where",
             (second["group"]["inner"], sorted(added_second)), ({"list": [1, 2]}, ["group/inner", "holder", "scalar"]))
    first["holder"]["tags"].append("edited")
    first["holder"]["note"] = "edited"
    first["group"]["inner"]["list"].append(3)
    check_eq("O2-1 copy: editing the first node leaves the template as it was", template, pristine)
    check_eq("O2-1 copy: ... and leaves the second node's own copy as it was",
             (second["holder"], second["group"]["inner"]), (pristine["holder"], pristine["group"]["inner"]))
    check("O2-1 copy: the two nodes share no object with each other or with the template",
          first["holder"] is not second["holder"] and first["holder"] is not template["holder"]
          and second["holder"] is not template["holder"] and second["group"]["inner"] is not template["group"]["inner"])


# --- O2-2: notes nested in template objects ------------------------------------------------------

def nested_notes() -> None:
    env_history = KEYS["notes"]["environment.note"]["note_history"]
    cost_history = KEYS["notes"]["cost.note"]["note_history"]
    base = {"schema_version": 1}
    for label, history, top in (("environment.note", env_history, "environment"), ("cost.note", cost_history, "cost")):
        for text in history:
            plan = plan_of({**base, top: {"note": text}})
            check(f"O2-2: a known text of {label} resets to the current one, nothing moves ({text[:24]}...)",
                  plan["proposed_config"][top]["note"] == TEMPLATE[top]["note"] and plan["answers_legacy"] == {}
                  and "answers_legacy" not in plan["proposed_config"])
        person = "Our own words about the stand (not a text the factory ever wrote)."
        plan = plan_of({**base, top: {"note": person}})
        check_eq(f"O2-2: a person's text in {label} moves whole into answers_legacy under its dotted key",
                 plan["proposed_config"].get("answers_legacy"), {label: person})
        check_eq("O2-2: ...the note is the current template text, and the move is listed in changes",
                 (plan["proposed_config"][top]["note"], [c["path"] for c in plan["changes"] if c["path"].endswith("/note")]),
                 (TEMPLATE[top]["note"], [f"/{top}/note"]))
        check_eq("O2-2: ...and the plan names what moved", plan["answers_legacy"], {label: person})
        held = plan_of({**base, top: {"note": "second text"}, "answers_legacy": {label: "first text"}})
        check_eq(f"O2-2: an existing answers_legacy.{label} is never overwritten; the second move lands under @<version>",
                 (held["proposed_config"]["answers_legacy"].get(label), held["proposed_config"]["answers_legacy"].get(f"{label}@{VERSION}")),
                 ("first text", "second text"))
        same = plan_of({**base, top: {"note": "first text"}, "answers_legacy": {label: "first text"}})
        check_eq("O2-2: a text already kept under answers_legacy is not stored twice",
                 (same["answers_legacy"], same["proposed_config"][top]["note"]), ({}, TEMPLATE[top]["note"]))
        empty = plan_of({**base, top: {"note": "  "}})
        check(f"O2-2: an empty {label} carries nothing to keep",
              empty["answers_legacy"] == {} and empty["proposed_config"][top]["note"] == TEMPLATE[top]["note"])
        odd = plan_of({**base, top: {"note": {"not": "text"}}})
        check_eq(f"O2-2: a {label} that is not text is a person's answer: kept whole",
                 odd["proposed_config"].get("answers_legacy"), {label: {"not": "text"}})
        broken = plan_of({**base, top: {"note": "words"}, "answers_legacy": "not an object"})
        check(f"O2-2: an answers_legacy that is not an object is an open question for {label}, not a crash",
              any(c["path"] == "/answers_legacy" for c in broken["conflicts"]))
        # the parent object, or the note itself, is absent: the fill creates it with the current text
        gone = plan_of(dict(base))
        check_eq(f"O2-2: a parent object that is absent is created with the fill and the current text of {label}",
                 (gone["proposed_config"][top]["note"], gone["answers_legacy"]), (TEMPLATE[top]["note"], {}))
        no_note = plan_of({**base, top: {}})
        check_eq("O2-2: a parent that is present without its note gets the current text, listed as added (default)",
                 ([(r["path"], r["absent_means"]) for r in no_note["added"] if r["path"] == f"/{top}/note"],
                  no_note["proposed_config"][top]["note"]), ([(f"/{top}/note", "default")], TEMPLATE[top]["note"]))
    live = old_generation_config()
    plan = plan_of(live, price_table_answer="builtin")
    check_eq("O2-2: on the live shape the person's environment.note is MOVED and listed, never silently reset",
             (plan["proposed_config"]["answers_legacy"]["environment.note"], plan["answers_legacy"]["environment.note"],
              plan["proposed_config"]["environment"]["note"]),
             (live["environment"]["note"], live["environment"]["note"], TEMPLATE["environment"]["note"]))
    again = plan_of(plan["proposed_config"], price_table_answer="builtin")
    check_eq("O2-2: planning the result again moves nothing more", (again["answers_legacy"], again["changes"]), ({}, []))


# --- O2-3 / O2-4: what apply writes -------------------------------------------------------------

def apply_writes() -> None:
    root = temp_dir("qa-config-order-")
    try:
        fresh = plan_of(None)
        filled = copy.deepcopy(TEMPLATE)
        filled["tests_root"] = "tests"
        filled["zeta_own"], filled["alpha_own"] = 1, 2
        filled["environment"]["secret_keys"] = ["K1"]
        scrambled = dict(reversed(list(filled.items())))
        scrambled["environment"] = dict(reversed(list(filled["environment"].items())))
        fresh["proposed_config"] = scrambled
        seal(fresh)
        check_eq("O2-3 setup: the approval hash does not depend on key order",
                 C.proposal_hash(fresh), C.proposal_hash({**fresh, "proposed_config": filled}))
        check("O2-3 setup: the proposal's own order is NOT the template's",
              list(scrambled) != list(TEMPLATE) and list(scrambled["environment"]) != list(TEMPLATE["environment"]))
        C.record_approval(root, fresh, "onboarding:order", "t:order")
        C.apply_plan(root, fresh, "onboarding:order")
        text = (root / "qa-factory" / "config.json").read_text(encoding="utf-8")
        written = json.loads(text)
        check_eq("O2-3: a role-filled proposal is written in the template's key order, the person's own keys after, in their order",
                 list(written), list(TEMPLATE) + list(k for k in scrambled if k not in TEMPLATE))
        check_eq("O2-3: ...and those unknown keys are the two this test added, in the proposal's order",
                 list(k for k in scrambled if k not in TEMPLATE), ["alpha_own", "zeta_own"])
        check_eq("O2-3: nested objects follow the template's order too", list(written["environment"]), list(TEMPLATE["environment"]))
        check_eq("O2-3: values are untouched by the ordering", written["environment"]["secret_keys"], ["K1"])
        ordered = {**{k: filled[k] for k in TEMPLATE}, "alpha_own": 2, "zeta_own": 1}
        ordered["environment"] = {k: filled["environment"][k] for k in TEMPLATE["environment"]}
        check_eq("O2-3: the bytes are the canonical bytes", text, json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
    finally:
        cleanup(root)


# --- O2-5: a value the plan invented is not an answer ------------------------------------------

def project_with(config: dict) -> Path:
    root = temp_dir("qa-config-answers-")
    (root / "qa-factory").mkdir()
    (root / "qa-factory" / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return root


ACCESS = {"kind": "oidc_password", "command": "", "url": "https://sso.example.test/login", "client_id_key": "OIDC_CLIENT",
          "realm_key": "OIDC_REALM", "user_key": "STAND_USER", "secret_key": "STAND_SECRET", "user_field": "", "secret_field": "", "token_key": "",
          "unauth_status": [302], "login_probe": {}}


def with_access(config: dict, access=None) -> dict:
    """A copy whose `environment.access` is a person's value (not the template's empty default): the key t-298 asks until answered."""
    out = copy.deepcopy(config)
    out["environment"]["access"] = copy.deepcopy(ACCESS if access is None else access)
    return out


def without(*names) -> dict:
    """The template minus some keys, with the access block a person recorded (so the key t-298 asks about is not an open row here)."""
    config = with_access(TEMPLATE)
    for name in names:
        del config[name]
    return config


GATE_WORDS = "the factory needs these answers before it writes the config:"


def answers_gate() -> None:
    complete = plan_of(with_access(TEMPLATE))
    check_eq("O2-5: a complete config has no row that needs an answer",
             (C.unanswered_pointers(complete), complete["reasked"]), ([], []))
    # no required row, no answers: apply proceeds
    root = project_with(with_access(TEMPLATE))
    try:
        C.record_approval(root, complete, "onboarding:a0", "t:a0")
        check("O2-5: answers=None with nothing required or re-asked: apply proceeds", C.apply_plan(root, complete, "onboarding:a0") is not None)
    finally:
        cleanup(root)
    # required keys missing, no answers: the plan lists them, apply refuses
    old = without("dod", "app_root")
    root = project_with(old)
    try:
        plan = plan_of(old)
        required = [r["path"] for r in plan["added"] if r["absent_means"] == "required"]
        check_eq("O2-5: the plan lists every required key it had to invent, once", sorted(required), ["/app_root", "/dod"])
        check_eq("O2-5: schema_version is never one of them (the plan fills it itself)",
                 [r["path"] for r in plan_of({"app_root": ".", "dod": "x"})["added"] if r["path"] == "/schema_version"], ["/schema_version"])
        check_eq("O2-5: ...and a config that only lacks schema_version asks for no answer there",
                 [p for p in C.unanswered_pointers(plan_of({k: v for k, v in with_access(TEMPLATE).items() if k != "schema_version"}))], [])
        before = (root / "qa-factory" / "config.json").read_bytes()
        C.record_approval(root, plan, "onboarding:a1", "t:a1")
        problem = message_of(lambda: C.apply_plan(root, plan, "onboarding:a1"))
        check("O2-5: apply REFUSES while a required key has no answer", problem.startswith("ValueError: " + GATE_WORDS), problem)
        check("O2-5: ...naming each pointer once, in one list", problem.count("/dod") == 1 and problem.count("/app_root") == 1, problem)
        check("O2-5: ...in human words: no script name, no file name", ".py" not in problem and "config_contract" not in problem
              and "reasked" not in problem and "absent_means" not in problem, problem)
        check_eq("O2-5: nothing was written: the config is byte-identical and no backup directory exists",
                 ((root / "qa-factory" / "config.json").read_bytes() == before,
                  (root / "qa-factory" / "records" / "config-migrations").exists()), (True, False))
        # the same through the command line: exit code and the stderr text
        proposal = root / "p.json"
        proposal.write_text(json.dumps(plan), encoding="utf-8")
        out = run_script("config_contract.py", "--root", root, "--apply", proposal, "--approval-ref", "onboarding:a1")
        check("O2-5 CLI: --apply exits 1 with the list on stderr and no traceback",
              out.returncode == 1 and GATE_WORDS in out.stderr and "/dod" in out.stderr and "/app_root" in out.stderr
              and "Traceback" not in out.stderr and out.stdout == "", f"{out.returncode} {out.stderr[-300:]}")
        # deleting the open row from the proposal file must not slip past the approval
        stripped = copy.deepcopy(plan)
        stripped["added"] = [r for r in stripped["added"] if r["path"] not in ("/dod", "/app_root")]
        check("O2-5: a proposal whose open rows were deleted is not the approved one", C.is_approved(root, stripped) is False)
        check_in("O2-5: ...and apply refuses it as an invalid hash", "proposal hash is invalid",
                 message_of(lambda: C.apply_plan(root, stripped, "onboarding:a1")))
        # every pointer answered: values written, rows move to kept
        answers = {"/dod": "Done means reviewed and green in CI", "/app_root": ".."}
        answered = plan_of(old, answers=answers)
        check_eq("O2-5: an answer is written into proposed_config", (answered["proposed_config"]["dod"], answered["proposed_config"]["app_root"]),
                 ("Done means reviewed and green in CI", ".."))
        check_eq("O2-5: ...and its row leaves added[] for kept[]",
                 ([r["path"] for r in answered["added"] if r["path"] in answers],
                  sorted((k["path"], k["reason"]) for k in answered["kept"] if k["path"] in answers)),
                 ([], [("/app_root", "answered by the person"), ("/dod", "answered by the person")]))
        check_eq("O2-5: nothing is left waiting", C.unanswered_pointers(answered), [])
        check_eq("O2-5: the key order stays canonical after an answer",
                 list(answered["proposed_config"])[:len(TEMPLATE)], list(TEMPLATE))
        C.record_approval(root, answered, "onboarding:a2", "t:a2")
        backup = C.apply_plan(root, answered, "onboarding:a2")
        written = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        check_eq("O2-5: apply writes the answers", (written["dod"], written["app_root"]), (answers["/dod"], answers["/app_root"]))
        check("O2-5: and this is a migration from an existing config: its backup exists", backup is not None and backup.is_file())
        check_eq("O2-5: a second plan over the result asks nothing",
                 (C.unanswered_pointers(plan_of(written)), plan_of(written)["added"]), ([], []))
        # a partial answer is not enough
        partial = plan_of(old, answers={"/dod": "x"})
        check_eq("O2-5: one pointer answered of two: the other is still waiting", C.unanswered_pointers(partial), ["/app_root"])
        # answers are read from a file by the command line
        answers_file = root / "answers.json"
        answers_file.write_text(json.dumps(answers), encoding="utf-8")
        (root / "qa-factory" / "config.json").write_text(json.dumps(old, indent=2), encoding="utf-8")
        shown = run_script("config_contract.py", "--root", root, "--migration-plan", "--answers", answers_file)
        got = json.loads(shown.stdout) if shown.returncode == 0 else {}
        check("O2-5 CLI: --migration-plan --answers carries the answers into the proposal",
              shown.returncode == 0 and got.get("proposed_config", {}).get("dod") == answers["/dod"]
              and C.unanswered_pointers(got) == [], shown.stderr[-300:])
        answers_file.write_text("{ not json", encoding="utf-8")
        bad = run_script("config_contract.py", "--root", root, "--migration-plan", "--answers", answers_file)
        check("O2-5 CLI: an answers file that is not JSON is refused with what is expected, no traceback",
              bad.returncode == 2 and "JSON object" in bad.stderr and "Traceback" not in bad.stderr, bad.stderr[-300:])
    finally:
        cleanup(root)
    # answers that nobody asked for
    plan = plan_of(without("dod"), answers={"/dod": "x", "/tests_root": "elsewhere", "/handoffs/required": False, "nonsense": 1})
    check_eq("O2-5: an answer for a pointer that is NOT required or re-asked is ignored",
             (plan["proposed_config"]["tests_root"], plan["proposed_config"]["handoffs"]), (TEMPLATE["tests_root"], TEMPLATE["handoffs"]))
    check_eq("O2-5: ...and listed as not asked, one row per pointer",
             sorted(k["reason"] for k in plan["kept"] if k["reason"].startswith("not asked")),
             ["not asked: /handoffs/required", "not asked: /tests_root", "not asked: nonsense"])
    check_eq("O2-5: the answer that was asked is used", (plan["proposed_config"]["dod"], C.unanswered_pointers(plan)), ("x", []))
    check("O2-5: answers that are not an object are refused", "must be a JSON object" in message_of(lambda: plan_of(without("dod"), answers=["/dod"])))
    check_eq("O2-5: with no config at all there is nothing to ask and answers are not read",
             (plan_of(None, answers={"/dod": "x"})["proposed_config"], plan_of(None, answers={"/dod": "x"})["kept"]), (None, []))
    # reasked: a key whose meaning changed is open until answered; the default is a legal answer
    table = table_with(reasked={"cases_root": {"question": "Where do this project's cases live now?"}})
    moved = {**with_access(TEMPLATE), "cases_root": "tests/cases"}
    asked = plan_of(moved, keys=table)
    check_eq("O2-5 reasked: the old value is not carried, and the row waits",
             (asked["proposed_config"]["cases_root"], [r["path"] for r in asked["reasked"]], C.unanswered_pointers(asked)),
             (TEMPLATE["cases_root"], ["/cases_root"], ["/cases_root"]))
    root = project_with(moved)
    try:
        C.record_approval(root, asked, "onboarding:r1", "t:r1")
        check_in("O2-5 reasked: apply refuses while the question is open, naming the pointer", "/cases_root",
                 message_of(lambda: C.apply_plan(root, asked, "onboarding:r1")))
        for label, value in (("a new value", "docs/cases"), ("an answer equal to the template default", TEMPLATE["cases_root"]),
                             ("the old value again", "tests/cases")):
            given = plan_of(moved, keys=table, answers={"/cases_root": value})
            check_eq(f"O2-5 reasked: {label} is an answer: the row is closed and the value is written",
                     (given["reasked"], C.unanswered_pointers(given), given["proposed_config"]["cases_root"],
                      [(k["path"], k["reason"]) for k in given["kept"]]), ([], [], value, [("/cases_root", "answered by the person")]))
        done = plan_of(moved, keys=table, answers={"/cases_root": TEMPLATE["cases_root"]})
        C.record_approval(root, done, "onboarding:r2", "t:r2")
        C.apply_plan(root, done, "onboarding:r2")
        written = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        check_eq("O2-5 reasked: an answer equal to the default is written and the next plan asks nothing (FR-7)",
                 (written["cases_root"], plan_of(written, keys=table)["reasked"], C.is_approved(root, done)),
                 (TEMPLATE["cases_root"], [], True))
    finally:
        cleanup(root)


# --- t-232 F7+F8 follow-ups: the memory MERGES with an explicit partial answers; the fold receipt ----

def memory_merge() -> None:
    """An explicit partial `answers` wins per pointer and the memory (the answers earlier approvals
    recorded) fills the rest: a headless caller that answers ONE new question must not bring the ones
    already answered back, and must not lose its own value to an older one."""
    old = without("dod", "app_root")
    root = project_with(old)
    try:
        first = plan_of(old, answers={"/dod": "Done means green (earlier)", "/app_root": "../earlier"}, root=root)
        C.record_approval(root, first, "onboarding:mm1", "t:mm1")
        # the memory alone fills both
        alone = plan_of(old, root=root)
        check_eq("memory merge: with no answers the memory fills both rows",
                 (C.unanswered_pointers(alone), alone["proposed_config"]["dod"], alone["proposed_config"]["app_root"]),
                 ([], "Done means green (earlier)", "../earlier"))
        # an explicit partial answers: /dod from the explicit value, /app_root from the memory
        merged = plan_of(old, answers={"/dod": "Done means reviewed (now)"}, root=root)
        check_eq("memory merge: BOTH rows are answered - nothing is asked again", C.unanswered_pointers(merged), [])
        check_eq("memory merge: /dod is the EXPLICIT value, not the older remembered one",
                 merged["proposed_config"]["dod"], "Done means reviewed (now)")
        check_eq("memory merge: /app_root is filled from the memory", merged["proposed_config"]["app_root"], "../earlier")
        check_eq("memory merge: each row says where its answer came from",
                 sorted((k["path"], k["reason"]) for k in merged["kept"] if k["path"] in ("/dod", "/app_root")),
                 [("/app_root", "answered earlier, not asked again"), ("/dod", "answered by the person")])
        check_eq("memory merge: nothing is listed as 'not asked' for what the memory supplied",
                 [k for k in merged["kept"] if k["reason"].startswith("not asked")], [])
        # an explicit answer for something nobody asked is still ignored, and the memory is silent about it
        extra = plan_of(old, answers={"/tests_root": "elsewhere"}, root=root)
        check_eq("memory merge: an explicit answer for a pointer nobody asked is ignored and listed; the memory still fills the asked ones",
                 ([k["reason"] for k in extra["kept"] if k["reason"].startswith("not asked")], C.unanswered_pointers(extra),
                  extra["proposed_config"]["tests_root"]), (["not asked: /tests_root"], [], TEMPLATE["tests_root"]))
        # no project to read from: no memory, the call stays pure
        check_eq("memory merge: without a project root there is no memory (the call stays pure)",
                 C.unanswered_pointers(plan_of(old, answers={"/dod": "x"})), ["/app_root"])
    finally:
        cleanup(root)


def fold_receipt() -> None:
    """`config_contract.py --record-approval <sealed> --approval-ref <ref> --fold` records that the old
    product passport was folded into the project profile, FOR that approval: one line in the approvals
    log, named by `for_approval` (never `approval_ref`), once per approval."""
    import onboard_apply
    root = project_with(copy.deepcopy(TEMPLATE))
    try:
        plan = plan_of(C.read_config_file(root), root=root)
        sealed = root / "sealed.json"
        sealed.write_text(json.dumps(plan), encoding="utf-8")
        log = root / "qa-factory" / "records" / "onboarding-approvals.jsonl"
        # the fold of an approval that was never recorded is refused, with the way out
        nothing = run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", "onboarding:f1", "--fold")
        check("fold: no recorded approval for the ref: refused, exit 1, nothing written, the door named",
              nothing.returncode == 1 and "recorded onboarding approval was not found" in nothing.stderr and "sealed proposal" in nothing.stderr
              and not log.exists() and "Traceback" not in nothing.stderr, nothing.stderr[-400:])
        approved = run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", "onboarding:f1", "--evidence-ref", "t:f1")
        check_eq("fold: the approval itself is recorded first (exit 0)", approved.returncode, 0)
        before = log.read_bytes()
        check_eq("fold: no receipt yet", onboard_apply.fold_receipt(root, "onboarding:f1"), False)
        first = run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", "onboarding:f1", "--evidence-ref", "t:f1", "--fold")
        check_eq("fold: the first fold for this approval is recorded (exit 0, stdout one JSON document)", (first.returncode, "fold_log" in json.loads(first.stdout or "{}")), (0, True))
        lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
        check_eq("fold: ONE line was added, naming the approval by `for_approval` and carrying no `approval_ref`",
                 (len(lines), lines[-1]["fold"], lines[-1]["for_approval"], "approval_ref" in lines[-1]),
                 (2, "product-passport -> project-profile", "onboarding:f1", False))
        check_eq("fold: the receipt is the one onboard_apply reads, and only for THIS approval",
                 (onboard_apply.fold_receipt(root, "onboarding:f1"), onboard_apply.fold_receipt(root, "onboarding:another")), (True, False))
        check("fold: the earlier lines are untouched (the log is only appended to)", log.read_bytes().startswith(before))
        # the same fold again: refused, nothing written
        after_first = log.read_bytes()
        again = run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", "onboarding:f1", "--fold")
        check("fold: twice for one approval: refused, exit 1, 'already folded for this approval', no traceback",
              again.returncode == 1 and "already folded for this approval" in again.stderr and "Traceback" not in again.stderr, again.stderr[-400:])
        check_eq("fold: ...and the log is byte-identical to after the first", log.read_bytes(), after_first)
        check_eq("fold: the approval's own line still resolves to exactly one record (the fold line did not make it ambiguous)",
                 C._approval_record(root, "onboarding:f1", plan)["approval_ref"], "onboarding:f1")
        # --fold alone is a malformed call, said as one
        bare = run_script("config_contract.py", "--root", root, "--fold")
        check("fold: --fold without --record-approval is refused with what it goes with",
              bare.returncode == 2 and "--record-approval" in bare.stderr and "Traceback" not in bare.stderr, bare.stderr[-300:])
        # a proposal that is not the approved one cannot carry a fold
        other = copy.deepcopy(plan)
        other["proposal_hash"] = "f" * 64
        check_in("fold: a proposal other than the one approved is refused", "does not authorize this exact proposal",
                 message_of(lambda: C.record_fold(root, other, "onboarding:f1")))
    finally:
        cleanup(root)


def value_migration_normaliser() -> None:
    """t-272 item 5: the F2 value migration compares through runtime_paths.normalise_project_path, the normaliser the writer
    (`runtime_paths.configured`) uses, so a spelling the writer resolves to the old default is renamed too."""
    import runtime_paths as RP
    new = TEMPLATE["journal_path"]
    old = KEYS["value_migrations"]["journal_path"]["from_default"]
    check_eq("the template's journal_path is the records/ spelling and the table's from_default the state/ one", (new, old),
             ("qa-factory/records/journal.jsonl", "qa-factory/state/journal.jsonl"))
    old_spellings = [old, "qa-factory" + B + "state" + B + "journal.jsonl", "./" + old, "." + B + "qa-factory" + B + "state" + B + "journal.jsonl",
                     old + "/", "  " + old + " ", ".//" + old]
    own = [old + ".bak", "qa-factory/state/Journal.jsonl", "my-logs/journal.jsonl", "state/journal.jsonl", new, "", "/" + old, "C:/x/" + old,
           "../" + old, "qa-factory/state/sub/journal.jsonl", "./" + new]
    for value in old_spellings:
        cfg = fixture()
        cfg["journal_path"] = value
        plan = C.migration_plan(cfg, "builtin")
        check_eq(f"{value!r} (a spelling of the old default) migrates to the records/ place and is listed under the label that says it CHANGED",
                 (plan["proposed_config"]["journal_path"], {"path": "/journal_path", "reason": "changed: default path renamed"} in plan["kept"],
                  [c["reason"] for c in plan["changes"] if c["path"] == "/journal_path"]),
                 (new, True, ["changed: default path renamed"]))
        check_eq(f"...and the writer resolves {value!r} and the migrated value to ONE file",
                 {RP.configured("P", value, "journal.jsonl"), RP.configured("P", plan["proposed_config"]["journal_path"], "journal.jsonl")},
                 {RP.configured("P", new, "journal.jsonl")})
    for value in own:
        cfg = fixture()
        cfg["journal_path"] = value
        plan = C.migration_plan(cfg, "builtin")
        check_eq(f"{value!r} is a person's own (or the new spelling already): untouched, nothing listed",
                 (plan["proposed_config"]["journal_path"], [k for k in plan["kept"] if k["path"] == "/journal_path"]), (value, []))
    check_eq("the listing's label is one word 'changed' (the value changes), never 'kept'", C.DEFAULT_RENAMED, "changed: default path renamed")


# --- t-298 B: a key with no answer is asked even under "keep as before" (config-keys.json `asked_until_answered`) ----

ACCESS_PTR = "/environment/access"
ACCESS_DEFAULT = TEMPLATE["environment"]["access"]
ACCESS_QUESTION = KEYS["asked_until_answered"]["environment.access"]["question"]


def asked_until_answered_keys() -> None:
    import onboard_apply as OA

    def rows(plan) -> list:
        return [r for r in plan["reasked"] if r["path"] == ACCESS_PTR]
    # K-B1: the live shape has no access at all; ONE pointer is open, among many added keys
    live = plan_of(fixture(), price_table_answer="builtin")
    check_eq("K-B1: over the live shape (no access) exactly ONE pointer is open: /environment/access", C.unanswered_pointers(live), [ACCESS_PTR])
    check("K-B1: ...while the plan still lists many added keys (the rule asks only the keys the table names, F5)", len(live["added"]) > 1, str(len(live["added"])))
    check_eq("K-B1: the row carries the table's question text and `was` None (nothing was there)",
             [(r["question"], r["was"]) for r in rows(live)], [(ACCESS_QUESTION, None)])
    check_eq("K-B1: the question is the table's, in human words (no pointer, file or script name in it)",
             ("/" in ACCESS_QUESTION or ".py" in ACCESS_QUESTION or "environment.access" in ACCESS_QUESTION, ACCESS_QUESTION.count("?") >= 1), (False, True))
    check_eq("K-B1: the proposed config holds the template default meanwhile (the fill), so nothing is invented as an answer",
             _at(live["proposed_config"], ACCESS_PTR), ACCESS_DEFAULT)
    check_eq("K-B1: the added row of the key is still listed while it is open", [r["path"] for r in live["added"] if r["path"] == ACCESS_PTR], [ACCESS_PTR])
    # K-B2: absent and empty are one rule; a person's value (AT: the default; BEYOND: one field different) never gets a row
    at = plan_of(copy.deepcopy(TEMPLATE))
    check_eq("K-B2 AT the default: a config that holds the template's access gets the same single pointer, `was` == the default",
             (C.unanswered_pointers(at), [r["was"] for r in rows(at)]), ([ACCESS_PTR], [ACCESS_DEFAULT]))
    check_eq("K-B2 BEYOND the default: kind oidc_password + url is the person's value: no row", C.unanswered_pointers(plan_of(with_access(TEMPLATE))), [])
    one_field = copy.deepcopy(TEMPLATE)
    one_field["environment"]["access"]["unauth_status"] = [302]
    check_eq("K-B2 BEYOND by one field: the default with ONE field changed is a person's value: no row", C.unanswered_pointers(plan_of(one_field)), [])
    # K-B3: an explicit whole-object answer
    root = project_with(fixture())
    try:
        answered = plan_of(C.read_config_file(root), price_table_answer="builtin", answers={ACCESS_PTR: ACCESS}, root=root)
        check_eq("K-B3: the answer is written into proposed_config", _at(answered["proposed_config"], ACCESS_PTR), ACCESS)
        check_eq("K-B3: its row is kept as `answered by the person`, and no row waits",
                 ([(k["path"], k["reason"]) for k in answered["kept"] if k["path"] == ACCESS_PTR], C.unanswered_pointers(answered)),
                 ([(ACCESS_PTR, "answered by the person")], []))
        check_eq("K-B3: ...and the `added` row of the pointer is gone, so the listing does not call a person's value 'a value a fresh install writes' (FR-10)",
                 [r["path"] for r in answered["added"] if r["path"] == ACCESS_PTR], [])
        check("K-B3: ...while the other added keys stay listed", len(answered["added"]) > 1)
        C.record_approval(root, answered, "onboarding:b3", "t:b3")
        backup = C.apply_plan(root, answered, "onboarding:b3")
        check("K-B3: apply proceeds (a migration of an existing config: its backup exists)", backup is not None and backup.is_file())
        check_eq("K-B3: the config on disk holds the answer", _at(json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")), ACCESS_PTR), ACCESS)
        line = [json.loads(l) for l in C.approvals_path(root).read_text(encoding="utf-8").splitlines() if l.strip()][-1]
        check_eq("K-B3: the approval line carries the pointer in `answers` and the template default in `answer_defaults`",
                 (line["answers"].get(ACCESS_PTR), line["answer_defaults"].get(ACCESS_PTR)), (ACCESS, ACCESS_DEFAULT))
        check_eq("K-B3: the next plan over the written config asks nothing about it", ACCESS_PTR in C.unanswered_pointers(plan_of(C.read_config_file(root), price_table_answer="builtin", root=root)), False)
    finally:
        cleanup(root)
    # K-B4: "not now" = the template default given explicitly; recorded; not asked again while the template default stands
    root = project_with(copy.deepcopy(TEMPLATE))
    try:
        not_now = plan_of(C.read_config_file(root), answers={ACCESS_PTR: copy.deepcopy(ACCESS_DEFAULT)}, root=root)
        check_eq("K-B4: 'not now' (the default, explicitly) closes the row and is kept as an answer",
                 (C.unanswered_pointers(not_now), [(k["path"], k["reason"]) for k in not_now["kept"] if k["path"] == ACCESS_PTR]),
                 ([], [(ACCESS_PTR, "answered by the person")]))
        C.record_approval(root, not_now, "onboarding:b4", "t:b4")
        later = plan_of(C.read_config_file(root), root=root)
        check_eq("K-B4: the next plan with the memory asks nothing, and says why (answered earlier, not asked again)",
                 (C.unanswered_pointers(later), [(k["path"], k["reason"]) for k in later["kept"] if k["path"] == ACCESS_PTR]),
                 ([], [(ACCESS_PTR, "answered earlier, not asked again")]))
        check_eq("K-B4: ...and the row left added[] too (a person's word, even 'not now', is not a fresh-install value)",
                 [r["path"] for r in later["added"] if r["path"] == ACCESS_PTR], [])
        check_eq("K-B4 control: the same project WITHOUT the memory (no root) asks again", C.unanswered_pointers(plan_of(C.read_config_file(root))), [ACCESS_PTR])
        # K-B5: the memory is good only while the template default it was given against stands
        changed = copy.deepcopy(TEMPLATE)
        changed["environment"]["access"]["unauth_status"] = [401]
        stored = copy.deepcopy(changed)
        check_eq("K-B5: a template whose access default DIFFERS: the earlier 'not now' is forgotten and it is asked again",
                 C.unanswered_pointers(C.migration_plan(stored, template=changed, root=root)), [ACCESS_PTR])
    finally:
        cleanup(root)
    # K-B6: an answer at a sub-pointer is not the unit: ignored and listed, the row stays open
    sub = plan_of(copy.deepcopy(TEMPLATE), answers={ACCESS_PTR + "/kind": "oidc_password"})
    check_eq("K-B6: an answer for /environment/access/kind is listed `not asked:` and the row stays open",
             ([k["reason"] for k in sub["kept"] if k["reason"].startswith("not asked")], C.unanswered_pointers(sub),
              _at(sub["proposed_config"], ACCESS_PTR + "/kind")), (["not asked: /environment/access/kind"], [ACCESS_PTR], ""))
    # an answer at an ANCESTOR: honoured before the check (the position), and if it sets the default the row stays open
    bare = without("environment")           # `environment` is a REQUIRED key: absent, the plan opens a row at /environment itself
    whole = copy.deepcopy(TEMPLATE["environment"])
    whole["access"] = copy.deepcopy(ACCESS)
    above = plan_of(bare, answers={"/environment": whole})
    check_eq("K-B2 position: an answer at the ancestor /environment that sets access to a person's value closes it (the check runs AFTER the required rows)",
             (C.unanswered_pointers(above), above["proposed_config"]["environment"]["access"]), ([], ACCESS))
    above_default = plan_of(bare, answers={"/environment": copy.deepcopy(TEMPLATE["environment"])})
    check_eq("K-B2 position: an ancestor answer that sets the DEFAULT leaves the access row open",
             C.unanswered_pointers(above_default), [ACCESS_PTR])
    # K-B7: no config at all: no rows (the role asks through topic 2 of the interview)
    fresh = plan_of(None)
    check_eq("K-B7: a fresh install (config None) opens no row by code", (fresh["reasked"], fresh["added"], C.unanswered_pointers(fresh)), ([], [], []))
    # K-B8: the shipped table's keys resolve in the template outside any list; a key that does not, or sits in a list, is no row and no crash
    def resolves(dotted: str) -> bool:
        node = TEMPLATE
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True
    check_eq("K-B8: every key of the shipped `asked_until_answered` resolves in the template, through objects only",
             [d for d in KEYS["asked_until_answered"] if not resolves(d)], [])
    check_eq("K-B8: the shipped section names exactly one key today (F5: the question lists only keys this table names)",
             sorted(KEYS["asked_until_answered"]), ["environment.access"])
    bogus = table_with(asked_until_answered={"environment.access": {"question": ACCESS_QUESTION}, "no.such.key": {"question": "?"},
                                             "environments.name": {"question": "inside a list?"}, "": {"question": "e"}, "dod.x": {"question": "below a string"},
                                             "environment": {"meta": "is not a question"}})
    odd = C.migration_plan(copy.deepcopy(TEMPLATE), keys=bogus)
    check_eq("K-B8: a key the template lacks, one inside a list, an empty name, a path below a string and an entry with no question text "
             "give no crash and no row of their own (the one real key is asked; `environment` as a whole equals its default only if every "
             "field does, which the template does - so it asks with the generic wording)",
             sorted(C.unanswered_pointers(odd)), sorted([ACCESS_PTR, "/environment"]))
    check_eq("K-B8: ...and the row of an entry with no question text carries a generic one, never an empty string",
             [bool(r["question"]) for r in odd["reasked"]], [True, True])
    check_eq("K-B3 control: with the table lacking the section, nothing is asked (an injected table decides)",
             C.unanswered_pointers(C.migration_plan(copy.deepcopy(TEMPLATE), keys=table_with(asked_until_answered={}))), [])
    # K-B9: the apply refuses over an open plan, naming the pointer, writing nothing
    root = project_with(fixture())
    try:
        made = OA.plan(root, plan_of(C.read_config_file(root), price_table_answer="builtin", root=root), context={"package_fingerprint": "f"})
        check_eq("K-B9: the install plan waits on exactly the access pointer", made["needs_answers"], [ACCESS_PTR])
        C.record_approval(root, made["proposal"], "onboarding:b9", "t:b9")
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
        refusal = message_of(lambda: OA.apply(root, made, "onboarding:b9"))
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
        check("K-B9: apply refuses, naming /environment/access and the door (--answers)",
              refusal.startswith("ApplyRefused") and ACCESS_PTR in refusal and "--answers" in refusal, refusal)
        check_eq("K-B9: ...and nothing was written (every file byte for byte as it was)", after, before)
        headless = run_script("onboard_apply.py", "--root", root, "--price-table-answer", "builtin", "--apply")
        check("K-B9 CLI: a headless --apply with no --answers exits 1, names /environment/access and --answers, no traceback",
              headless.returncode == 1 and ACCESS_PTR in headless.stderr and "--answers" in headless.stderr and "Traceback" not in headless.stderr,
              f"{headless.returncode} {headless.stderr[-300:]}")
        # F7-B: an answer that is not valid is refused at apply, before anything is written
        bad = plan_of(C.read_config_file(root), price_table_answer="builtin", answers={ACCESS_PTR: {**ACCESS, "kind": "bogus"}}, root=root)
        C.record_approval(root, bad, "onboarding:b10", "t:b10")
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
        invalid = message_of(lambda: C.apply_plan(root, bad, "onboarding:b10"))
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
        check("F7-B: an invalid answer (an unknown kind) is refused at apply, naming the field and saying nothing was written and what to do",
              "proposed config is invalid" in invalid and "environment.access.kind" in invalid and "Nothing was written" in invalid
              and "make the proposal again" in invalid, invalid)
        check_eq("F7-B: ...and no config, backup or record was written (the invariant: no invalid config is ever written)", after, before)
        not_object = plan_of(C.read_config_file(root), price_table_answer="builtin", answers={ACCESS_PTR: "oidc_password"}, root=root)
        C.record_approval(root, not_object, "onboarding:b11", "t:b11")
        check_in("F7-B: an answer that is not an object is refused too, as what is expected", "environment.access must be an object",
                 message_of(lambda: C.apply_plan(root, not_object, "onboarding:b11")))
    finally:
        cleanup(root)


def frontend_key_and_outcome() -> None:
    """RH1-7 N2 (AR-3): the frontend key is a template default that migrates in empty; `login_probe.outcome` is documented,
    validated, and NEVER planted by the migration. K-N2-1 .. K-N2-7."""
    base = {"schema_version": 1}
    mine = {"base_url_key": "STAND_URL", "user_key": "AUTH_USER", "health_path": "/v1/config"}
    plan = plan_of({**base, "environment": dict(mine)})
    env = plan["proposed_config"]["environment"]
    check_eq("K-N2-1 an old config gets environment.frontend added, empty", env.get("frontend"), {"url_key": "", "api_path": ""})
    check_eq("K-N2-1 ... and no value the person wrote is touched", {k: env[k] for k in mine}, mine)
    check("K-N2-1 ... listed as added, default, with a since", any(r["path"] == "/environment/frontend" and r["absent_means"] == "default"
                                                                 and r["since"] for r in plan["added"]))
    text = "environment.frontend.api_path must be a path starting with one /"
    for bad in ("api/x", "//evil.host/x", "http://other/x", "/" + B + "x", "@evil/x"):
        got = C.environment_errors({"frontend": {"url_key": "FRONTEND_URL", "api_path": bad}})
        check_eq(f"K-N2-2 E-F9 a path {bad!r} gives the one error text", got, [text])
    check_eq("K-N2-2 /api/v1/config passes", C.environment_errors({"frontend": {"url_key": "FRONTEND_URL", "api_path": "/api/v1/config"}}), [])
    check_eq("K-N2-2 an entry of environments[] is checked the same way",
             C.environments_frontend_errors([{"name": "a", "frontend": {"url": "http://h:5173", "api_path": "//x"}}]),
             ["environments[0].frontend.api_path must be a path starting with one /"])
    check_eq("K-N2-2 ... and an entry without a frontend is silent", C.environments_frontend_errors([{"name": "a"}]), [])
    device_stand_row_errors()
    check_in("K-N2-3 environment.note names the empty frontend and the outcome-less record", "empty = an API-only stand", TEMPLATE["environment"]["note"])
    check_in("K-N2-3 ... and what a record without outcome is", "a record without outcome predates it and is not confirmed", TEMPLATE["environment"]["note"])
    check_in("K-N2-3 environments_note names the absent frontend", "absent = no frontend", TEMPLATE["environments_note"])
    for label, shape in (("a list", []), ("a string", "x"), ("a number", 5), ("null", None)):
        check_eq(f"K-N2-4 E-F18 {label} is not a frontend object", C.environment_errors({"frontend": shape}),
                 ["environment.frontend must be an object {url_key, api_path}"])
    check_eq("K-N2-4 E-F7 an api_path with no url_key is an error",
             C.environment_errors({"frontend": {"url_key": "", "api_path": "/api/x"}}),
             ["environment.frontend.api_path is set but environment.frontend.url_key is empty: a path needs the frontend's address"])
    check_eq("K-N2-4 E-F8 both empty is the API-only default", C.environment_errors({"frontend": {"url_key": "", "api_path": ""}}), [])
    check("K-N2-4 nesting: a dict as url_key and a list as api_path are errors, not a crash",
          len(C.environment_errors({"frontend": {"url_key": {"a": 1}, "api_path": ["/x"]}})) >= 2)
    proof = {"user_key": "AUTH_USER", "status": 200, "checked_at": "2026-10-27T10:00:00"}
    for word in ("OK", "", "success", None):
        errors = C.access_errors({"kind": "none", "login_probe": {**proof, "outcome": word}})
        check(f"K-N2-5 E-L8 outcome {word!r} is refused and the error names the set",
              len(errors) == 1 and "ok | failed | skipped | not_recorded" in errors[0], str(errors))
    check_eq("K-N2-5 the four words pass", [C.access_errors({"kind": "none", "login_probe": {**proof, "outcome": w}})
                                           for w in ("ok", "failed", "skipped", "not_recorded")], [[], [], [], []])
    check_eq("K-N2-5 an old record without outcome passes", C.access_errors({"kind": "none", "login_probe": proof}), [])
    old = {**base, "environment": {"access": {"kind": "local_login", "login_probe": dict(proof)}}}
    plan = plan_of(old)
    probe = plan["proposed_config"]["environment"]["access"]["login_probe"]
    check_eq("K-N2-6 migrating an old login_probe adds NO outcome and touches nothing", probe, proof)
    check_eq("K-N2-6 the template keeps login_probe empty", TEMPLATE["environment"]["access"]["login_probe"], {})
    for key in ("environment.note", "environments_note"):
        history = KEYS["notes"][key]["note_history"]
        template = TEMPLATE["environment"]["note"] if key == "environment.note" else TEMPLATE[key]
        check(f"K-N2-7 {key}: note_history ends with the template text and has the new text appended", history[-1] == template and len(history) >= 2)


def device_stand_row_errors() -> None:
    """EP1-41c: `environments_surface_errors` - an entry that names a `surface` is told by references/surfaces.json; an entry that names
    none is silent and the table is not read (the web pin). Expectations come from the requirement: a typo never becomes the web, a
    secret is never kept in a committed address, an error never repeats an address."""
    import surfaces
    row = {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:4723", "base_path": "/"},
           "device": {"serial_key": "ANDROID_SERIAL"}, "app": {"id": "com.example.app"}}
    errs = C.environments_surface_errors
    reads = {"n": 0}
    real_rows = surfaces.rows

    def counted():
        reads["n"] += 1
        return real_rows()
    surfaces.rows = counted
    try:
        check_eq("EP1-41c: entries with no `surface` are silent", errs([{"name": "a"}, {"name": "b", "base_url": "http://x"}]), [])
        check_eq("EP1-41c: ...and a project with none reads the table 0 times", reads["n"], 0)
        check_eq("EP1-41c: no environments, a non-list and a non-object entry are silent", (errs(None), errs("x"), errs([5, None])), ([], [], []))
        check_eq("EP1-41c: a whole device row passes", errs([dict(row)]), [])
        check_eq("EP1-41c: the serial key and the app are optional", errs([{"name": "e", "surface": "android", "driver": {"url": "https://h:4723"}}]), [])
        check_eq("EP1-41c: a surface of another hands needs no driver (`web`, `api`)", errs([{"name": "w", "surface": "web"}, {"name": "a", "surface": "api"}]), [])
    finally:
        surfaces.rows = real_rows
    typo = errs([dict(row, surface="andriod")])
    check("EP1-41c: a `surface` the table lacks is named with the list of rows", len(typo) == 1 and "andriod" in typo[0] and "android" in typo[0]
          and typo[0].startswith("environments[0].surface"), str(typo))
    for label, value in (("a number", 5), ("null", None), ("a list", ["android"]), ("empty", "")):
        got = errs([dict(row, surface=value)])
        check(f"EP1-41c: `surface` as {label} is one error, not a crash", len(got) == 1 and got[0].startswith("environments[0].surface"), str(got))
    secret = errs([dict(row, driver={"url": "http://user:hunter2@127.0.0.1:4723"})])
    check("EP1-41c: an address with a user and a password is refused, and the error does not repeat it",
          len(secret) == 1 and "a user, a password" in secret[0] and "hunter2" not in secret[0], str(secret))
    check("EP1-41c: ...a password alone is refused as well", len(errs([dict(row, driver={"url": "http://:hunter2@h:1"})])) == 1)
    for label, url in (("a query", "http://h:4723/?token=abc"), ("a fragment", "http://h:4723/#frag")):      # F-7: the same reading as device_stand
        got = errs([dict(row, driver={"url": url})])
        check(f"EP1-41c (F-7): an address with {label} is refused as a secret, and the error does not repeat it",
              len(got) == 1 and "a query or a fragment" in got[0] and "token=abc" not in got[0] and "#frag" not in got[0], str(got))
    for label, driver in (("ftp", {"url": "ftp://h:1"}), ("no scheme", {"url": "127.0.0.1:4723"}),
                          ("a bad port", {"url": "http://h:notaport"}), ("a number", {"url": 5}), ("not an object", "http://h:1")):
        got = errs([dict(row, driver=driver)])
        check(f"EP1-41c: driver {label} is one error that says what is expected", len(got) == 1 and "http(s) address" in got[0], str(got))
    for label, driver in (("empty", {"url": ""}), ("blank", {"url": "  "}), ("no url", {}), ("absent", None), ("empty object", {})):
        check_eq(f"EP1-41c (F-7): driver {label} is \"I do not know\" (the onboarding leaves it for the doctor): no contract error",
                 errs([dict(row, driver=driver)]), [])
    check_eq("EP1-41c (F-7): a missing `driver` key is no contract error either", errs([{k: v for k, v in row.items() if k != "driver"}]), [])
    for bad in ("emulator-5554", "a b", "5", "x" * 80):
        check_eq(f"EP1-41c: a serial key {bad[:12]!r} is a value, not a NAME", len(errs([dict(row, device={"serial_key": bad})])), 1)
    check_eq("EP1-41c: `device` not an object and `app` not an object are one error each",
             (len(errs([dict(row, device="x")])), len(errs([dict(row, app=["id"])]))), (1, 1))
    check_eq("EP1-41c: an entry's index is in its label", errs([{"name": "w"}, dict(row, driver={"url": "ftp://h:1"})])[0][:15], "environments[1]")
    # wired in both places: `validate` and `--check-environment`
    config = copy.deepcopy(TEMPLATE)
    config["environments"] = [dict(row, surface="andriod")]
    check("EP1-41c: validate carries it", any("andriod" in e for e in C.validate(config)), str(C.validate(config)))
    config["environments"] = [dict(row)]
    check("EP1-41c: ...and a whole device row adds nothing to validate", not any("environments[0]" in e for e in C.validate(config)))
    root = temp_dir("qa-config-device-row-")
    try:
        (root / "qa-factory").mkdir()
        (root / "qa-factory" / "config.json").write_text(json.dumps({"environments": [dict(row, surface="andriod")]}), encoding="utf-8")
        done = run_script("config_contract.py", "--root", root, "--check-environment")
        listed = json.loads(done.stdout)
        check("EP1-41c: --check-environment carries it and exits 1", done.returncode == 1 and any("andriod" in e for e in listed["errors"]), done.stdout[-300:])
    finally:
        cleanup(root)


def install_command_key() -> None:
    """RH1-4 4.2 (AR-3): `commands.install`, kind `setup`. One writer (p4-generate.md), one reader (dependency_drift.install_command).
    K-4.2-migrate is the temporal edge: before the key exists the command is the table row or none, after it the profile's own."""
    import dependency_drift as DD
    import profile_contract as PC
    prof = {"profile_id": "api", "revision": "1", "roots": {"repo": ".", "test": "tests"}, "adapter_id": "native",
            "adapter_version": "1", "capabilities": ["api"], "dependency_ids": [],
            "commands": {"run": {"kind": "run", "argv": ["pytest"], "cwd": ".", "scope": "selected"}},
            "selectors": {"test_id": "{selector}"}, "reporter": {"kind": "junit"}, "quality_gates": {},
            "execution_prerequisites": {"runtime": "python 3.12", "package_manager": "poetry 2.4.1",
                                        "dependency_state": "locked", "hook_executables": []},
            "conventions_refs": [], "environment_refs": [], "data_refs": [], "ownership_refs": [],
            "extensions": {"schema_version": "native/1"}}
    check_eq("K-4.2-migrate: a profile with no install line is valid (the key is optional)", PC.validate_profile(prof), [])
    before = DD.install_command(prof, "svc")
    check_eq("K-4.2-migrate BEFORE the key exists: the table row of the package manager, in the lock's folder",
             (before["source"], before["argv"], before["cwd"]), ("table", ["poetry", "install"], "svc"))
    check_eq("K-4.2-migrate BEFORE, no manager and no key: none",
             DD.install_command(dict(prof, execution_prerequisites={}))["source"], "none")
    prof["commands"]["install"] = {"kind": "setup", "argv": ["make", "deps"], "cwd": "backend"}
    check_eq("K-4.2-migrate: kind `setup` with no scope, no reporter, no selectors is valid", PC.validate_profile(prof), [])
    after = DD.install_command(prof, "svc")
    check_eq("K-4.2-migrate AFTER the key exists: the profile's own command first, its own cwd",
             (after["source"], after["argv"], after["cwd"]), ("profile", ["make", "deps"], "backend"))
    prof["commands"]["install"]["kind"] = "test"
    check("negative control: the same line as kind `test` still needs its scope", any(".install.scope" in e for e in PC.validate_profile(prof)))
    prof["commands"]["install"] = {"kind": "setup", "argv": [], "cwd": "."}
    check("negative control: kind `setup` is still a command - an empty argv is refused", any(".install.argv" in e for e in PC.validate_profile(prof)))
    exec_prof = dict(prof, extensions={"schema_version": "native/1", "execution": {
        "schema_version": 1, "concurrency": {"native_supported": False, "isolation": "unknown"}}})
    exec_prof["commands"] = {"run": dict(prof["commands"]["run"], repo_id="r", framework_adapter="f", reporter={"format": "none"},
                                         selectors={}),
                             "install": {"kind": "setup", "argv": ["make"], "cwd": "."}}
    check_eq("K-4.2-migrate: under execution schema 1 a setup command needs no reporter", [e for e in PC.validate_profile(exec_prof)
                                                                                              if "install.reporter" in e], [])
    check_eq("F3: under execution schema 1 the shape p4-generate.md tells ({kind, argv, cwd} only) is valid - no repo_id, no framework_adapter",
             [e for e in PC.validate_profile(exec_prof) if ".install" in e], [])
    exec_prof["commands"]["install"]["kind"] = "test"
    check("F3 negative control: the same line as kind `test` still needs repo_id and framework_adapter under schema 1",
          sum(".install.repo_id" in e or ".install.framework_adapter" in e for e in PC.validate_profile(exec_prof)) == 2)
    ready = {"profiles": [dict(prof, capabilities=[], commands={"run": dict(prof["commands"]["run"], argv=[sys.executable]),
                                               "install": {"kind": "setup", "argv": ["no-such-tool-zz", "x"], "cwd": "no-such-dir"}})]}
    check_eq("RH1-4 F2: a printed-only `setup` command with a missing tool and a missing cwd never makes the profile unavailable",
             PC.profile_readiness(ready, ["api"], Path.cwd())["api"]["status"], "ready")
    ready["profiles"][0]["commands"]["install"]["kind"] = "run"
    check_eq("RH1-4 F2 negative control: the same command as kind `run` does (the executable is not found)",
             PC.profile_readiness(ready, ["api"], Path.cwd())["api"]["status"], "unavailable")
    old = {"schema_version": 1, "profiles": [json.loads(json.dumps(dict(prof, commands={"run": prof["commands"]["run"]})))]}
    plan = plan_of(old)
    check_eq("K-4.2-migrate: migrating an old config plants NO install command into a person's profile",
             plan["proposed_config"]["profiles"], old["profiles"])
    check_in("K-4.2: the template's profiles_note names `install` and kind `setup`", "`install`", TEMPLATE["profiles_note"])
    history = KEYS["notes"]["profiles_note"]["note_history"]
    check("K-4.2: profiles_note history keeps the old text and ENDS with the template text", len(history) >= 2 and history[-1] == TEMPLATE["profiles_note"])
    meta = KEYS["keys"].get("profiles.commands.install") or {}
    check_eq("K-4.2: config-keys.json names the key with a since and the absent meaning",
             (meta.get("since"), meta.get("absent_means")),
             ("0.10.3", "no install command recorded: the table row of the package manager is shown, else none"))
    skills = PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases"
    p4, p2 = (skills / "p4-generate.md").read_text(encoding="utf-8"), (skills / "p2-interview.md").read_text(encoding="utf-8")
    check("K-4.2: ONE writer - the profile form of phase 4 writes commands.install", "`commands.install`" in p4 and '"kind": "setup"' in p4)
    check("K-4.2: the interview asks the topic that feeds it", "commands.install" in p2 and "environment to its lock" in p2)


def parallel_windows_key() -> None:
    """N-P1-3: dispatch.parallel_windows - template row, keys row, a reader with a default (AR-3)."""
    check_eq("template carries dispatch.parallel_windows = 3", TEMPLATE["dispatch"].get("parallel_windows"), 3)
    check_eq("the constant is 3", C.PARALLEL_WINDOWS_DEFAULT, 3)
    check_in("config-keys.json has a row for it", "dispatch.parallel_windows", KEYS["keys"])
    check_eq("the row says an absent key means the default",
             KEYS["keys"]["dispatch.parallel_windows"].get("absent_means"), "default")
    for label, cfg in (("no key", {"dispatch": {}}), ("no dispatch block", {}), ("config not an object", None),
                       ("dispatch not an object", {"dispatch": 5})):
        check_eq("missing key reads 3, no note: " + label, C.parallel_windows(cfg), (3, None))
    check_eq("2 reads 2", C.parallel_windows({"dispatch": {"parallel_windows": 2}}), (2, None))
    check_eq("1 reads 1 (a project may choose serial)", C.parallel_windows({"dispatch": {"parallel_windows": 1}}), (1, None))
    for bad in (0, -1, "3", 1.5, True, None):
        value, note = C.parallel_windows({"dispatch": {"parallel_windows": bad}})
        check_eq(f"bad value {bad!r} reads the default", value, 3)
        check(f"bad value {bad!r} gives exactly one note line",
              isinstance(note, str) and note.startswith("note:") and "\n" not in note, note)


def manual_walkers_key() -> None:
    """t-2147 TR3-9d: manual.walkers - template row, keys rows, the interview line, and a config written before the block
    migrates with no question (AR-3)."""
    check_eq("template carries manual.walkers = 3", TEMPLATE["manual"].get("walkers"), 3)
    check_eq("the constant is 3", C.MANUAL_WALKERS_DEFAULT, 3)
    check_in("the template carries the note beside it", "manual_note", TEMPLATE)
    check_in("config-keys.json has a row for the block", "manual", KEYS["keys"])
    check_in("config-keys.json has a row for the key", "manual.walkers", KEYS["keys"])
    check_eq("the row says an absent key means the default", KEYS["keys"]["manual.walkers"].get("absent_means"), "default")
    check_eq("the note history ends with the template text", KEYS["notes"]["manual_note"]["note_history"][-1], TEMPLATE["manual_note"])
    old = {k: v for k, v in TEMPLATE.items() if k not in ("manual", "manual_note")}
    plan = C.migration_plan(old)
    check_eq("a config with no `manual` block gets the template's block filled in (walkers 3 and, since TR3-10b, the two ways)",
             (plan["proposed_config"] or {}).get("manual"), TEMPLATE["manual"])
    check("...with no conflict and no re-asked question about it",
          not any("manual" in json.dumps(row) for row in list(plan.get("conflicts") or []) + list(plan.get("reasked") or [])), plan)
    p2 = (PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases" / "p2-interview.md").read_text(encoding="utf-8")
    check_in("the interview names the key it writes", "`manual.walkers`", p2)
    check_in("the interview says 1 is one at a time", "1 = one at a time", p2)


def manual_supply_keys() -> None:
    """t-2174 TR3-10b: manual.accounts_way / manual.data_way - template rows, keys rows, the note, and migration that fills the
    defaults into a config written with only `walkers` and never overwrites a person's value (B.1)."""
    block = TEMPLATE["manual"]
    check_eq("template: accounts_way defaults", block.get("accounts_way"),
             {"words": "not known", "self_sign_up": {}, "more_accounts": {}, "limit_by_role": {}})
    check_eq("template: data_way defaults", block.get("data_way"), {"words": "not known", "pools": {}, "may": "not known"})
    check_in("the template carries the supply note", "manual_supply_note", TEMPLATE)
    for key in ("manual.accounts_way", "manual.data_way"):
        check_in(f"config-keys.json has a row for {key}", key, KEYS["keys"])
        check_eq(f"{key}: an absent key means the default", KEYS["keys"][key].get("absent_means"), "default")
        check(f"{key}: a `since` per since_basis", bool(KEYS["keys"][key].get("since")))
    check_eq("the supply note history ends with the template text", KEYS["notes"]["manual_supply_note"]["note_history"][-1],
             TEMPLATE["manual_supply_note"])
    old = copy.deepcopy(TEMPLATE)
    old["manual"] = {"walkers": 2}
    old.pop("manual_supply_note")
    plan = C.migration_plan(old)
    manual = (plan["proposed_config"] or {}).get("manual") or {}
    check_eq("a config with only walkers keeps walkers 2 and gains both ways with defaults", manual,
             {"walkers": 2, "accounts_way": block["accounts_way"], "data_way": block["data_way"]})
    check("...with no conflict and no re-asked question about it",
          not any("accounts_way" in json.dumps(r) or "data_way" in json.dumps(r)
                  for r in list(plan.get("conflicts") or []) + list(plan.get("reasked") or [])), plan)
    answered = copy.deepcopy(TEMPLATE)
    answered["manual"] = {"walkers": 3, "accounts_way": {"words": "the app makes them", "self_sign_up": {"roles": ["default"]}},
                          "data_way": {"may": "may create, never delete"}}
    kept = ((C.migration_plan(answered)["proposed_config"] or {}).get("manual")) or {}
    check_eq("a person's words are never overwritten by the default", kept["accounts_way"]["words"], "the app makes them")
    check_eq("...nor a mapped sign-up role list", kept["accounts_way"]["self_sign_up"], {"roles": ["default"]})
    check_eq("...nor the data-change answer", kept["data_way"]["may"], "may create, never delete")
    check_eq("...and a missing sibling key of an answered block gets its default", kept["data_way"]["words"], "not known")


def interview_asks_the_compile_question() -> None:
    """TR3-12 F11: the interview asks once, in plain words, whether the build compiles the whole test folder."""
    p2 = (PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases" / "p2-interview.md").read_text(encoding="utf-8")
    check_in("the interview names the key it writes", "`dispatch.parallel_windows`", p2)
    check_in("the note says windows run in parallel and serial on a yes", "windows run in parallel; serial if", p2)
    check_in("the question is in plain words (P9), not a key name", "compiles every test file together", p2)
    check_in("a person who does not answer stays at 3", "stays at 3", p2)


def _seeded_dispatch(**kwargs):
    import story_run_common as T
    root, _task_root, _env = T.seed("TR312-1", **kwargs)
    try:
        return json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")).get("dispatch")
    finally:
        cleanup(root)


def seed_pins_one() -> None:
    """TR3-12: `seed` pins `dispatch.parallel_windows` to 1; a caller's own dispatch block merges, its key wins."""
    check_eq("seed pins one", (_seeded_dispatch() or {}).get("parallel_windows"), 1)
    block = _seeded_dispatch(dispatch={"other_key": "kept"}) or {}
    check_eq("a caller's other keys stay and the pin merges in", (block.get("other_key"), block.get("parallel_windows")), ("kept", 1))
    check_eq("a caller that sets the key wins", (_seeded_dispatch(dispatch={"parallel_windows": 3}) or {}).get("parallel_windows"), 3)


def seed_none_leaves_key_out() -> None:
    """TR3-12: `parallel_windows=None` leaves the key out, so the reader's default (3) applies."""
    block = _seeded_dispatch(parallel_windows=None) or {}
    check("the key is absent", "parallel_windows" not in block, block)
    check_eq("the reader then gives the default", C.parallel_windows({"dispatch": block}), (3, None))


def main() -> None:
    interview_asks_the_compile_question()
    seed_pins_one()
    seed_none_leaves_key_out()
    install_command_key()
    frontend_key_and_outcome()
    table_coverage()
    parallel_windows_key()
    manual_walkers_key()
    manual_supply_keys()
    fixture_is_shape_only()
    value_migration_normaliser()
    k3_fixture()
    x9_retired_surprise_ignore()
    reinstall_equals_fresh()
    notes()
    turns_note_history()
    nested_notes()
    deep_fill()
    fill_missing_keys_copies_what_it_fills()
    asked_until_answered_keys()
    apply_writes()
    answers_gate()
    tables()
    legacy_commands()
    machine_local()
    none_case()
    no_config_tree()
    fresh_flow()
    unreadable_config()
    schema_version()
    approval()
    memory_merge()
    fold_receipt()
    finish("test_config_migration")


if __name__ == "__main__":
    main()
