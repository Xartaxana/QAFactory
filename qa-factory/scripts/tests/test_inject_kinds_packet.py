#!/usr/bin/env python3
"""RC1-14 part 2, N1: the task packet without the duplicate, the dispatch kind, and the sections a kind drops (`inject_context.py`).

Keys (the spec's names, t-1757 N1 and section 3a):
  K1   `dispatch_kind` on the whole table of record shapes the controller writes (a first window, a checkpoint-resumed first
       window, the environment start stamp, a rework, a repair, a retry of a repair): errs only toward `first`
  K2   `entries_for` / `delivered_text` on a synthetic map: the drop is applied; `first`, an unknown kind, a common or common-rules
       row, a heading that is not there, an entry the role is not delivered and every wrong-typed table deliver the full text
  K3   `map_problems`: the shipped map is clean; a dangling heading, a `first` row, a common row, a foreign entry are each named
  K4   `task_packet`: ONE `known_paths`; the record wins a key both name, a state-only key is kept; the projection is the whitelist;
       a record that is None or lacks role/scope takes them from the arguments (S2)
  K4b  `dispatch.checkpoint` is the record's
  K5   MEASURED packet bytes before / after on a rework-class fixture (a static `role_load` cannot show it: the packet is an allowance)
  K6   `collect_blocks(kind="repair")` for the automator lacks the three dropped headings; `first` has them
  K7   an over-budget hook dispatch exits 2 AND leaves a `dispatch-denials.jsonl` line naming the reason (TP1-15045 class); AT
       26 000 chars the file is delivered, one beyond it is refused
  K8   every rule the repair role keeps is in its repair text, and `role_load` measures that same text (the same function)
  K9   the hook end to end: a repair record gets the cut text and `dispatch.kind: repair`; a first record gets the full text
Runnable on its own: `python scripts/tests/test_inject_kinds_packet.py`.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import inject_context as IC  # noqa: E402
import role_load as RL  # noqa: E402
import test_inject_notices as N  # noqa: E402  (its hook runner and story fixture; importing it runs nothing)

SLICE = "plugin:references/slices/qa-automator/execution-lifecycle.md"
DROPPED = ["### Importing a developer or CI result", "### Profiles, leases and build commands"]


def shipped() -> dict:
    return json.loads((IC.PLUGIN_ROOT / "references" / "inject-map.json").read_text(encoding="utf-8"))


def slice_text() -> str:
    return (IC.PLUGIN_ROOT / SLICE.split(":", 1)[1]).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------- K1
def k1_dispatch_kind() -> None:
    first = [("None", None), ("a list", []), ("an empty dict", {}), ("a string", "repair"), ("a number", 7),
             ("rework_of empty", {"rework_of": ""}), ("repair_cause 0", {"repair_cause": 0}),
             ("execution_kind manual alone", {"execution_kind": "manual"}),
             ("a checkpoint-resumed FIRST window (parent_retry, no rework_of)", {"parent_retry": "S5-qa-automator-2"}),
             ("the environment start stamp (repair_cause environment alone)", {"repair_cause": "environment"}),
             ("a blank rework_of beside a cause", {"rework_of": " ", "repair_cause": "test_defect"}),
             ("a cause and no rework_of", {"repair_cause": "test_defect"}),
             ("rework_of that is not text", {"rework_of": 5, "repair_cause": "test_defect"}),
             ("rework_of None", {"rework_of": None, "repair_cause": "mechanical"}),
             ("a list rework_of", {"rework_of": ["S5-qa-automator-1"], "repair_cause": "mechanical"})]
    for label, record in first:
        check_eq(f"K1 first: {label}", IC.dispatch_kind(record), "first")
    other = [("a repair", {"rework_of": "S5-qa-automator-2", "repair_cause": "test_defect"}, "repair"),
             ("a mechanical repair of another stage", {"rework_of": "S7-qa-automator-1", "repair_cause": "mechanical"}, "repair"),
             ("a retry of a repair (the binding is copied)", {"parent_retry": "S5-qa-automator-3", "rework_of": "S5-qa-automator-2",
                                                              "repair_cause": "test_defect"}, "repair"),
             ("a rework", {"rework_of": "S4-qa-case-designer-1"}, "rework"),
             ("a rework with a blank cause", {"rework_of": "S4-qa-case-designer-1", "repair_cause": "  "}, "rework"),
             ("a retry of a rework", {"parent_retry": "S4-qa-case-designer-3", "rework_of": "S4-qa-case-designer-2"}, "rework")]
    for label, record, kind in other:
        check_eq(f"K1 {kind}: {label}", IC.dispatch_kind(record), kind)
    check_eq("K1: parent_retry is never read: adding it to a repair or a rework changes nothing",
             [IC.dispatch_kind(dict(r, parent_retry="P")) for _l, r, _k in other], [k for _l, _r, k in other])


# ---------------------------------------------------------------------------------------------------------------- K2, K3
TEXT = "lead\n\n## A\na1\n\n### A1\nx1\n\n### A2\ny1\n\n## B\nb1\n"
S_REL, RULES_REL, COMMON_REL, FOREIGN = ("plugin:references/slices/qa-x/s.md", "plugin:references/slices/qa-x/common-rules.md",
                                         "plugin:references/common.md", "plugin:references/slices/qa-x/other.md")


def synthetic(kinds) -> dict:
    return {"common": [COMMON_REL], "roles": {"qa-x": [RULES_REL, S_REL]}, "kinds": kinds}


def cut(kinds, kind="repair", rel=S_REL, text=TEXT) -> str:
    return IC.delivered_text(rel, text, "qa-x", synthetic(kinds), kind)


def k2_delivery() -> None:
    row = {"repair": {"qa-x": {"drop_sections": {S_REL: ["### A1"]}}}}
    check_eq("K2: the named section goes, its own lines with it, nothing else",
             cut(row), "lead\n\n## A\na1\n\n### A2\ny1\n\n## B\nb1\n")
    check_eq("K2: `first` is the full text", cut(row, "first"), TEXT)
    check_eq("K2: a kind with no row (`rework`) is the full text", cut(row, "rework"), TEXT)
    check_eq("K2: an unknown kind (`resume`, a typo, None) is the full text", [cut(row, k) for k in ("resume", "Repair", None, 3)], [TEXT] * 4)
    check_eq("K2: a `first` row is ignored", cut({"first": {"qa-x": {"drop_sections": {S_REL: ["### A1"]}}}}, "first"), TEXT)
    check_eq("K2: a `##` with `###` children drops only its OWN lines", cut({"repair": {"qa-x": {"drop_sections": {S_REL: ["## A"]}}}}),
             "lead\n\n### A1\nx1\n\n### A2\ny1\n\n## B\nb1\n")
    check_eq("K2: a last section can be dropped too (the text then ends with the section before)",
             cut({"repair": {"qa-x": {"drop_sections": {S_REL: ["## B"]}}}}), "lead\n\n## A\na1\n\n### A1\nx1\n\n### A2\ny1\n")
    check_eq("K2: a heading is matched exactly (a prefix, another level, other case are not it)",
             [cut({"repair": {"qa-x": {"drop_sections": {S_REL: [h]}}}}) for h in ("### A", "## A1", "### a1", "### A1 ")], [TEXT] * 4)
    check_eq("K2: a heading the text does not hold is ignored", cut({"repair": {"qa-x": {"drop_sections": {S_REL: ["### Nope"]}}}}), TEXT)
    check_eq("K2: a common-rules slice is never cut", cut({"repair": {"qa-x": {"drop_sections": {RULES_REL: ["## A"]}}}}, rel=RULES_REL), TEXT)
    check_eq("K2: a common entry is never cut", cut({"repair": {"qa-x": {"drop_sections": {COMMON_REL: ["## A"]}}}}, rel=COMMON_REL), TEXT)
    check_eq("K2: an entry the role is not delivered is never cut", cut({"repair": {"qa-x": {"drop_sections": {FOREIGN: ["## A"]}}}}, rel=FOREIGN), TEXT)
    check_eq("K2: another role's row is not this role's", IC.delivered_text(S_REL, TEXT, "qa-y", synthetic(
        {"repair": {"qa-x": {"drop_sections": {S_REL: ["### A1"]}}}}), "repair"), TEXT)
    check_eq("K2: a project entry is never cut", IC.delivered_text("project:a.md", TEXT, "qa-x", {"common": [], "roles": {"qa-x": ["project:a.md"]},
             "kinds": {"repair": {"qa-x": {"drop_sections": {"project:a.md": ["## A"]}}}}}, "repair"), TEXT)
    broken = [("kinds absent", None), ("kinds []", []), ("kinds 3", 3), ("repair 3", {"repair": 3}), ("repair []", {"repair": []}),
              ("role row 5", {"repair": {"qa-x": 5}}), ("drop_sections a list", {"repair": {"qa-x": {"drop_sections": [S_REL]}}}),
              ("entry maps to a string", {"repair": {"qa-x": {"drop_sections": {S_REL: "### A1"}}}}),
              ("headings not text", {"repair": {"qa-x": {"drop_sections": {S_REL: [3, None]}}}}),
              ("empty headings", {"repair": {"qa-x": {"drop_sections": {S_REL: []}}}})]
    for label, kinds in broken:
        imap = synthetic(kinds) if kinds is not None else {"common": [COMMON_REL], "roles": {"qa-x": [RULES_REL, S_REL]}}
        check_eq(f"K2 E1: {label}: the full text, no raise", IC.delivered_text(S_REL, TEXT, "qa-x", imap, "repair"), TEXT)
    check_eq("K2 E1: an imap that is not an object delivers the full text", IC.delivered_text(S_REL, TEXT, "qa-x", [], "repair"), TEXT)
    imap = synthetic(row)
    check_eq("K2: `entries_for` is the same list for every kind (a kind never removes a whole entry)",
             [IC.entries_for("qa-x", imap, k) for k in ("first", "repair", "rework")], [[COMMON_REL, RULES_REL, S_REL]] * 3)
    check_eq("K2: `entries_for` of an unknown role is the common list; of a broken map, []", (IC.entries_for("qa-z", imap), IC.entries_for("qa-x", [])),
             ([COMMON_REL], []))
    check_eq("K2: a text with no marker lines and no section is returned as it is", cut(row, text="no headings here\n"), "no headings here\n")


def k3_map_problems() -> None:
    real = shipped()
    check_eq("K3: the shipped map says only what actually happens", IC.map_problems(real), [])
    bad = copy.deepcopy(real)
    bad["kinds"]["repair"]["qa-automator"]["drop_sections"][SLICE].append("### A heading that is not there")
    problems = IC.map_problems(bad)
    check("K3 negative control: a dangling heading is named", len(problems) == 1 and "A heading that is not there" in problems[0], str(problems))
    for label, mutate, needle in (
            ("a `first` row", lambda m: m["kinds"].update({"first": {"qa-automator": {}}}), "kinds.first"),
            ("an unknown kind", lambda m: m["kinds"].update({"resume": {}}), "kinds.resume"),
            ("an entry not in the role's list", lambda m: m["kinds"]["repair"]["qa-automator"]["drop_sections"].update(
                {"plugin:references/slices/qa-scout/coverage-design.md": ["## X"]}), "not in the list of qa-automator"),
            ("a common entry", lambda m: m["kinds"]["repair"]["qa-automator"]["drop_sections"].update(
                {"plugin:references/tester-manifesto.md": ["## X"]}), "never cut"),
            ("a common-rules slice", lambda m: m["kinds"]["repair"]["qa-automator"]["drop_sections"].update(
                {"plugin:references/slices/qa-automator/common-rules.md": ["## X"]}), "never cut"),
            ("a project entry", lambda m: m["kinds"]["repair"]["qa-automator"]["drop_sections"].update(
                {"project:qa-factory/strategy/framework-rules.md": ["## X"]}), "only a `plugin:` entry"),
            ("an empty heading list", lambda m: m["kinds"]["repair"]["qa-automator"]["drop_sections"].update({SLICE: []}), "non-empty list"),
            ("a role row that is not an object", lambda m: m["kinds"]["repair"].update({"qa-scout": 5}), "`drop_sections` is not an object"),
            ("a kind table that is not an object", lambda m: m.update({"kinds": 3}), "`kinds` is not an object"),
            ("a kind that is not an object", lambda m: m["kinds"].update({"repair": 3}), "not an object of role -> row"),
            ("an entry whose file is missing", lambda m: (m["roles"]["qa-automator"].append("plugin:references/no-such.md"),
                                                          m["kinds"]["repair"]["qa-automator"]["drop_sections"].update(
                                                              {"plugin:references/no-such.md": ["## X"]})), "could not be read")):
        m = copy.deepcopy(real)
        mutate(m)
        got = IC.map_problems(m)
        check(f"K3: {label} is named", any(needle in line for line in got), str(got))
    check_eq("K3: no `kinds` at all is no problem (E1)", IC.map_problems({"common": [], "roles": {}}), [])
    check_eq("K3: the shipped map's rows are exactly the three sections of the spec table",
             real["kinds"], {"repair": {"qa-automator": {"drop_sections": {SLICE: DROPPED}}}})


# ---------------------------------------------------------------------------------------------------------------- K4, K5
def record_fixture() -> dict:
    """A rework-class record as the controller stores it: the request as dispatched, the binding copied, the bookkeeping on top."""
    links = [{"case": f"TC-{n}", "area": "api", "version": n, "sha256": "0" * 64} for n in range(1, 4)]
    request = {"id": "S5-qa-automator-4", "stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2", "TC-3"],
               "input_hash": "h" * 64, "known_paths": {"plan": "{task_root}/work/test-plan.json", "task_root": "R:/proj/qa-factory/artifacts/QA-1",
                                                       "project_root": "R:/proj", "plugin_root": "R:/pkg", "entrypoints": {"run": "run-py.cmd"},
                                                       "repository_roots": {"app": "R:/proj/app"}, "package_fingerprint": "f" * 64,
                                                       "package_version": "0.10.9"},
               "budget": {"max_turns": 80}, "purpose": "rework", "rework_of": "S5-qa-automator-3", "reason": "the critic's finding 2",
               "expected_revision": 12, "idempotency_key": "dispatch:S5-qa-automator-4", "repair_cause": "test_defect",
               "read_first": ["work/s5-notes.md"], "case_version_links": links, "plan_rows": ["TS-1", "TS-2"], "person_words": True,
               "rerun_after": {"stages": ["S6"]}, "limits": {"repair_cycles": 2}}
    return dict(request, status="running", agent_id="agent-7", resolved_model={"model": "sonnet", "effort": "inherit"},
                request_binding={k: copy.deepcopy(request[k]) for k in ("case_version_links", "repair_cause", "rework_of", "reason", "purpose",
                                                                         "plan_rows", "limits")},
                dispatched_seq=41, checkpoint={"completed": ["TC-1"], "remaining": ["TC-2", "TC-3"], "counters": {"requests": 9}})


STATE = {"revision": 12, "scope": ["TC-1", "TC-2", "TC-3"], "known_paths": {"project_root": "R:/proj", "state_only": "S"}}
KNOWN = {"project_root": "R:/resolved", "state_only": "S-resolved", "plugin_root": "R:/pkg"}
WHITELIST = ("purpose", "reason", "rework_of", "parent_retry", "relaunch_of", "repair_cause", "repair_cause_source", "read_first",
             "checkpoint", "case_version_links", "plan_rows", "manual_case_ids", "execution_kind", "retry_reason", "retry_words")


def k4_packet() -> None:
    record = record_fixture()
    resolved = dict(record, known_paths={"project_root": "R:/record-resolved", "entrypoints": {"run": "run-py.cmd"}})
    packet = IC.task_packet("QA-1", STATE, resolved, KNOWN, role="qa-automator")
    check_eq("K4: `known_paths` occurs once in the whole packet", json.dumps(packet).count('"known_paths"'), 1)
    check_eq("K4: the record's resolved key wins a key both name, a state-only key is kept, a record-only key is added",
             packet["known_paths"], {"project_root": "R:/record-resolved", "state_only": "S-resolved", "plugin_root": "R:/pkg",
                                     "entrypoints": {"run": "run-py.cmd"}})
    check_eq("K4: the top level is task_id, revision, known_paths, scope, dispatch", list(packet),
             ["task_id", "revision", "known_paths", "scope", "dispatch"])
    shown = packet["dispatch"]
    check_eq("K4: the projection leads with id, stage, role, kind, scope", list(shown)[:5], ["id", "stage", "role", "kind", "scope"])
    check_eq("K4: ...kind repair, the record's own scope", (shown["kind"], shown["scope"]), ("repair", record["scope"]))
    check_eq("K4: ...then exactly the whitelisted keys the record holds, with its values",
             {k: v for k, v in shown.items() if k not in ("id", "stage", "role", "kind", "scope")},
             {k: record[k] for k in WHITELIST if k in record})
    gone = ("known_paths", "input_hash", "idempotency_key", "expected_revision", "resolved_model", "budget", "status", "agent_id",
            "request_binding", "dispatched_seq", "limits", "person_words", "rerun_after")
    check("K4: the bookkeeping of the record is not in the projection", not [k for k in gone if k in shown], str(sorted(shown)))
    check_eq("K4: the input is not changed", resolved, dict(record, known_paths=resolved["known_paths"]))
    # empties are not carried
    empty = dict(record, reason="  ", purpose="", plan_rows=[], manual_case_ids=[], checkpoint={}, read_first=None)
    check_eq("K4: a present but empty value (blank text, [], {}, None) is not carried",
             [k for k in ("reason", "purpose", "plan_rows", "manual_case_ids", "checkpoint", "read_first")
              if k in IC.task_packet("QA-1", STATE, empty, KNOWN)["dispatch"]], [])
    # a record that is None: kind first, role and scope from the arguments (S2)
    none = IC.task_packet("QA-1", STATE, None, KNOWN, dispatch_id="D9", role="qa-scout")
    check_eq("K4 S2: a record of None is kind `first`, with role from the argument, the state's scope, the dispatch id given",
             none["dispatch"], {"id": "D9", "stage": None, "role": "qa-scout", "kind": "first", "scope": STATE["scope"]})
    check_eq("K4 S2: ...and the known paths are the state's resolved ones", none["known_paths"], KNOWN)
    partial = IC.task_packet("QA-1", STATE, {"id": "D1", "stage": "S5"}, KNOWN, role="qa-automator", scope=["TC-9"])
    check_eq("K4 S2: a record that lacks role and scope takes them from the arguments",
             (partial["dispatch"]["role"], partial["dispatch"]["scope"], partial["dispatch"]["id"]), ("qa-automator", ["TC-9"], "D1"))
    own = IC.task_packet("QA-1", STATE, {"id": "D1", "role": "qa-runner", "scope": []}, KNOWN, role="qa-automator", scope=["TC-9"])
    check_eq("K4 S2: the record's own role and its own EMPTY scope win over the arguments", (own["dispatch"]["role"], own["dispatch"]["scope"]),
             ("qa-runner", []))
    check_eq("K4: a state with no scope and no revision gives scope [] and revision None", [IC.task_packet("T", {}, None, {})[k] for k in ("scope", "revision")], [[], None])
    check_eq("K4: known that is not an object, a record's known_paths that is not an object: no raise, the other one stands",
             (IC.task_packet("T", STATE, {"known_paths": 5}, KNOWN)["known_paths"], IC.task_packet("T", STATE, None, None)["known_paths"]), (KNOWN, {}))
    # K4b: the checkpoint is the record's, whole
    check_eq("K4b: dispatch.checkpoint equals the record's checkpoint", shown["checkpoint"], record["checkpoint"])
    check("K4b: ...and a copy is not required (the packet is serialized at once)", "checkpoint" in shown)


def k5_measure() -> None:
    record = record_fixture()
    known = {k: v.replace("{task_root}", "R:/proj/qa-factory/artifacts/QA-1") if isinstance(v, str) else v for k, v in record["known_paths"].items()}
    resolved = dict(record, known_paths=known)
    before = {"task_id": "QA-1", "revision": STATE["revision"], "known_paths": known, "scope": STATE["scope"], "dispatch": resolved}
    after = IC.task_packet("QA-1", STATE, resolved, known, role="qa-automator")
    b, a = len(json.dumps(before)), len(json.dumps(after))
    print(f"MEASURED packet bytes before={b} after={a} (a rework-class fixture: the whole record twice-over `known_paths` vs the projection)")
    check("K5: the packet of a rework-class record is smaller than before the change", a < b, f"{a} >= {b}")
    check("K5: ... by at least the second `known_paths` (the bytes of the map itself)", b - a >= len(json.dumps(known)), f"saved {b - a}, map {len(json.dumps(known))}")


# ---------------------------------------------------------------------------------------------------------------- K6, K8
def k6_collect_and_k8_kept() -> None:
    imap = shipped()
    repair = "\n".join(IC.collect_blocks("qa-automator", imap, None, "repair"))
    first = "\n".join(IC.collect_blocks("qa-automator", imap))
    default = "\n".join(IC.collect_blocks("qa-automator", imap, None))
    check_eq("K6: the default kind is `first`", default, first)
    for h in DROPPED:
        check_in(f"K6: the `first` text has {h}", h, first)
        check_not_in(f"K6: the repair text lacks {h}", h, repair)
    check_eq("K6: another role's repair text is the full text", "\n".join(IC.collect_blocks("qa-scout", imap, None, "repair")),
             "\n".join(IC.collect_blocks("qa-scout", imap)))
    check_eq("K6: a rework of the automator is the full text (no `rework` row)", "\n".join(IC.collect_blocks("qa-automator", imap, None, "rework")), first)
    kept = ["## Before the first write", "## Author and critic", "### After a mechanical fix", "mechanical_round", "### Requests, receipts and reuse",
            "### Runtime provenance of a request", "### Every run goes through `run_suite.py`", "--reparse-block", "## Outcomes that are not `passed`"]
    for needle in kept:
        check_in(f"K8: the repair text keeps {needle!r}", needle, repair)
    # role_load measures the same function's text
    path = IC.PLUGIN_ROOT / SLICE.split(":", 1)[1]
    text = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    cut_text = IC.delivered_text(SLICE, text, "qa-automator", imap, "repair")
    check_eq("K8: role_load's bytes for the slice are the bytes of that very text", RL._delivered_bytes(path, SLICE, "qa-automator", imap, "repair")[0],
             len(cut_text.encode("utf-8")))
    in_slice = [n for n in kept if n in text]
    check("K8: the slice itself holds most of the kept strings (the rest are in the role's other entries)", len(in_slice) >= 8, str(in_slice))
    for needle in in_slice:
        check_in(f"K8: ...and the text role_load measures keeps {needle!r}", needle, cut_text)


# ---------------------------------------------------------------------------------------------------------------- K7, K9
def k7_denial() -> None:
    root = temp_project("qa-inject-k7-")
    try:
        use_project(root)
        N.make_story(root, json.dumps({"revision": 1}))
        strategy = root / "qa-factory" / "strategy"
        strategy.mkdir(parents=True, exist_ok=True)
        entry = "project:qa-factory/strategy/big.md"
        imap = {"common": [], "roles": {N.ROLE: [entry]}}
        patch = {"load_map": lambda: imap}
        denials = root / "qa-factory" / "artifacts" / N.TASK / "state" / "dispatch-denials.jsonl"

        def lines():
            return [json.loads(x) for x in denials.read_text(encoding="utf-8").splitlines()] if denials.is_file() else []
        (strategy / "big.md").write_text("x" * IC.MAX_BLOCK_CHARS, encoding="utf-8")
        code, out, err = N.run_hook(root, N.agent_event(root), patch=patch)
        check("K7 AT the limit: a file of exactly MAX_BLOCK_CHARS is delivered, no denial", code == 0 and "x" * 100 in N.prompt_of(out) and lines() == [], f"{code} {err[:200]}")
        (strategy / "big.md").write_text("x" * (IC.MAX_BLOCK_CHARS + 1), encoding="utf-8")
        code, out, err = N.run_hook(root, N.agent_event(root), patch=patch)
        check("K7 BEYOND the limit: exit 2, the refusal on stderr, nothing on stdout", code == 2 and "exceeds budget" in err and out == "", f"{code} {err[:200]}")
        rows = lines()
        check("K7: ... and ONE line in dispatch-denials.jsonl names the reason, the role and the receipt",
              len(rows) == 1 and "exceeds budget" in rows[0]["reason"] and entry in rows[0]["reason"]
              and rows[0]["role"] == N.ROLE and rows[0]["dispatch_id"] == f"S0-{N.ROLE}-1", str(rows))
        # the whitespace edge: the budget judges the stripped text, as it always did
        (strategy / "big.md").write_text("  " + "x" * IC.MAX_BLOCK_CHARS + "\n\n", encoding="utf-8")
        code, _out, _err = N.run_hook(root, N.agent_event(root), patch=patch)
        check("K7 edge: 26 000 chars padded with whitespace is within the budget (the text is stripped first)", code == 0)
    finally:
        cleanup(root)


def k9_hook() -> None:
    root = temp_project("qa-inject-k9-")
    try:
        use_project(root)
        role = "qa-automator"
        base = {"id": f"S5-{role}-2", "role": role, "status": "running", "stage": "S5", "scope": ["TC-1"]}
        records = {"first": base,
                   "repair": dict(base, rework_of=f"S5-{role}-1", repair_cause="test_defect", reason="fix it"),
                   "rework": dict(base, rework_of=f"S5-{role}-1", reason="redo"),
                   "resumed-first": dict(base, parent_retry=f"S5-{role}-1")}
        N.make_story(root, json.dumps({"revision": 1}))
        controller = root / "qa-factory" / "artifacts" / N.TASK / "state" / "controller.json"
        event = N.agent_event(root)
        event["tool_input"]["subagent_type"] = role
        got = {}
        for name, record in records.items():
            controller.write_text(json.dumps({"revision": 1, "scope": ["TC-1"], "dispatches": {record["id"]: record}}), encoding="utf-8")
            code, out, err = N.run_hook(root, event)
            prompt = N.prompt_of(out)
            packet = json.loads(prompt.split(IC.PACKET_HEADING)[1].split("\n", 2)[1]) if code == 0 else {}
            got[name] = (code, "### Importing a developer or CI result" in prompt, packet.get("dispatch", {}).get("kind"))
            check(f"K9 {name}: the hook allows the dispatch", code == 0, f"{code} {err[:200]}")
        check_eq("K9: a repair is delivered the cut text and told its kind; every other record the full text",
                 got, {"first": (0, True, "first"), "repair": (0, False, "repair"), "rework": (0, True, "rework"), "resumed-first": (0, True, "first")})
        controller.write_text(json.dumps({"revision": 1, "scope": ["TC-1"], "dispatches": {}}), encoding="utf-8")
        code, out, _err = N.run_hook(root, event)
        check("K9: no running dispatch of the role: the full text, a packet whose dispatch is kind `first`",
              code == 0 and "### Importing a developer or CI result" in N.prompt_of(out)
              and '"kind": "first"' in N.prompt_of(out))
        controller.write_text("{ not json", encoding="utf-8")
        code, _out, err = N.run_hook(root, event)
        check("K9 control: an unreadable controller.json is still the receipt refusal", code == 2 and IC.RECEIPT_REASON in err, f"{code} {err[:200]}")
    finally:
        cleanup(root)


k1_dispatch_kind()
k2_delivery()
k3_map_problems()
k4_packet()
k5_measure()
k6_collect_and_k8_kept()
k7_denial()
k9_hook()
finish("test_inject_kinds_packet (the packet, the dispatch kind, the sections a kind drops)")
