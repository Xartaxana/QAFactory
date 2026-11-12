#!/usr/bin/env python3
"""Every required thing has a home for its null outcome - the detector, its pins and its negative controls (FR-23, t-305 N0).

`null_outcomes.audit` walks what the factory requires (the index rows with an item list, every stage's
`required_outputs`, the tool fields of the FR-11 walk, plus the conditional fields the data file names) and demands
ONE home for each: a declaration in the contract, a `never_empty` row with its guard, or a `pending` row at a named
node. A detector that walks nothing is green for the wrong reason, so the walk sizes are pinned HERE, in both
directions (t-317 F4), and every refusal below is shown on a synthetic input next to the real tree passing.

The real package is never mutated: a negative control feeds `audit()` a stub, a synthetic contract text parsed with
`handoff.parse`, or a deep copy of the data file (FR-45, command hygiene 7d).

Keys (t-305 N0): K0.2 reader, K0.3 registry and shape, K0.4 walk sizes, K0.5 one home, K0.6 never_empty rows,
K0.7 ratchet, K0.8 the default rule is printed, K0.9 F1 rows, K0.10 one copy of the FR-11 selection, K0.12 undeclared
contracts unchanged, K0.15 the debt row, K0.16 the verdict-list formatter.
"""
import copy
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as HC  # noqa: E402
import handoff_init  # noqa: E402
import null_outcomes as NO  # noqa: E402

S7 = "s7-analyst-to-automator"
SCRIPTS = PLUGIN_ROOT / "scripts"
# The walk sizes. A change of any of them is a change of the factory's contracts, and the Lead's question:
# the detector is not adjusted to agree with the tree (t-305 N0 step 0).
PINS = {"scope": 19, "other": 4, "outputs": 16, "tool_fields": 27, "conditional": 11, "validator": 16, "registry": 12}

REAL_INDEX = handoff.index()["handoffs"]
OLD_EMPTY_SCOPE = "no rows. One row per item in scope: the id, a state and a reason of at most 80 characters."
ROW_FORM_SENTENCE = 'a row of a list is written one line per key: `"scope[0].id": <value>`, the next row `"scope[1].id"`'
REAL_STAGES = json.loads(NO.STAGES.read_text(encoding="utf-8"))
REAL_DATA = json.loads(NO.DATA.read_text(encoding="utf-8"))
REAL_FIELDS = NO.tool_fields()
STAGE_IDS = {s["id"] for s in REAL_STAGES["stages"]}

# ------------------------------------------------------------------------------ synthetic contracts
SYN = {}                       # name -> parsed synthetic contract text; consulted before the real files


def s_spec(contract):
    return handoff.spec_of(SYN[contract]) if contract in SYN else NO.cached_spec(contract)


def s_sections(contract):
    return handoff.sections_of(SYN[contract]) if contract in SYN else NO.cached_sections(contract)


def s_raw(contract):
    return SYN[contract].data.get("null_outcome") if contract in SYN else NO.cached_raw(contract)


def s_reader(contract):
    return handoff.null_outcome_entries(s_raw(contract))


SYN_TEXT = """schema_version: 1
contract: syn
stage: S7
from_role: a
to_role: b
{block}
header:
  window: <the instance ids handed for repair>
{scope}
not_for_repair:
  - id: <instance id>
    verdict: <APP_BUG|ENV_ISSUE>
"""
SCOPE_LIST = """scope:
  - id: <instance id>
    state: <TEST_BUG|TEST_BUG:collection|FLAKY>"""
VALID = """null_outcome:
  scope:
    condition: triage_has_no_repair
    params:
      repair_verdicts: [TEST_BUG, "TEST_BUG:collection", FLAKY]
      listed_in: not_for_repair
    words:
      header.window:
        word: none
        means: "nothing is handed for repair"
    source: work/triage.json"""
LEGACY = """null_outcome:
  section: scope
  repair_verdicts: [TEST_BUG, "TEST_BUG:collection", FLAKY]
  listed_in: not_for_repair
  window: none"""


def syn_doc(block: str, scope: str = SCOPE_LIST):
    return handoff.parse(SYN_TEXT.format(block=block, scope=scope))


def entry_problems(block: str) -> list:
    """`null_outcomes.entry_problems` for the `scope` entry of a synthetic contract holding `block`."""
    doc = syn_doc(block)
    raw = doc.data.get("null_outcome")
    entry = raw.get("scope") if isinstance(raw, dict) else None
    return NO.entry_problems("scope", entry, spec=handoff.spec_of(doc), sections=handoff.sections_of(doc),
                             stage_ids=STAGE_IDS)


def audit(**kw):
    """The detector over the real tree, with the walk pins, unless a stub is given."""
    kw.setdefault("pins", PINS)
    return NO.audit(**kw)


def audit_syn(block: str, kind: str = "review", scope: str = SCOPE_LIST):
    """The detector over the real tree PLUS one synthetic contract `syn` - its own declaration is what is judged."""
    SYN["syn"] = syn_doc(block, scope)
    row = {"stage": "S7", "from": "a", "to": "b", "contract": "syn", "kind": kind}
    return NO.audit(index=REAL_INDEX + [row], spec_of=s_spec, sections_of=s_sections, raw=s_raw, reader=s_reader)


def about(report, contract: str = "syn") -> list:
    return [p for p in report.problems if p.startswith(contract + ":") and "has no home" not in p]


def mutated(fn):
    data = copy.deepcopy(REAL_DATA)
    fn(data)
    return data


def has(report, needle: str) -> bool:
    return any(needle in p for p in report.problems)


# -------------------------------------------------------------------------------------- the real tree
REAL = audit()


def the_real_tree_is_green_and_the_line_is_printed() -> None:
    check_eq("the detector over the real package finds nothing wrong", REAL.problems, [])
    print(REAL.line())                      # never silent: the default rule's count is on every run (FR-41)
    c = REAL.counts
    check_eq("K0.4: the walk sizes AT their pins (19 scope contracts, 4 others, 16 outputs, 27 tool fields, 11 "
"conditional, 16 validator rows, 12 conditions)",
             (c["scope"], c["other"], c["outputs"], c["tool_fields"], c["conditional"], c["validator"],
              len(NO.CONDITIONS)), (19, 4, 16, 27, 11, 16, 12))
    check_eq("homes: one declared, 20 never_empty (+16 validator), 52 pending",
             (c["declared"], c["never_empty"], c["pending"]), (1, 20, 52))
    check_in("K0.8: the summary line says what was walked and what each home holds",
             "walked scope 19, outputs 16, tool fields 27, conditional 11 | declared 1, never_empty 20 (+16 validator), "
             "pending 52 of which by default ", REAL.line())
    defaults = [r for r in REAL_DATA["pending"] if r["default"] is True]
    check_eq("K0.8: Z in the line is COMPUTED - it is the count of `default: true` rows", c["default"], len(defaults))
    check("K0.8: and the default rule is not the whole list (the inventory named the rest)",
          0 < len(defaults) < len(REAL_DATA["pending"]), str(len(defaults)))
    lower = audit(data=mutated(lambda d: d["pending"][5].update(default=False)))
    check_eq("K0.8 negative: a stub with one fewer default row prints Z-1", lower.counts["default"], len(defaults) - 1)
    check_eq("an item declared only by the reserved conditions: none of the package's contracts carries one",
             c["reserved_declared"], 0)
    import test_field_producers as walker  # the FR-11 walk itself: same fields, in the same order
    needs, _gaps = walker.walk()
    check_eq("K0.10: the detector walks the same 27 fields test_field_producers walks",
             [(c_, p) for c_, _r, p, _h in REAL_FIELDS], [(c_, p) for c_, _r, p, _prod in needs])


# -------------------------------------------------------------------------------------------- K0.2
def the_reader() -> None:
    entries = handoff.null_outcomes(S7)
    check_eq("K0.2: S7 -> one keyed entry, under `scope`", list(entries), ["scope"])
    entry = entries["scope"]
    check_eq("K0.2: ...naming the condition, its params, its words and its source",
             (entry["condition"], entry["params"]["listed_in"], entry["params"]["repair_verdicts"],
              entry["words"]["header.window"], entry["source"]),
             ("triage_has_no_repair", "not_for_repair", ["TEST_BUG", "TEST_BUG:collection", "FLAKY"],
              {"word": "none", "means": "nothing is handed for repair"}, "work/triage.json"))
    check_eq("K0.2: an undeclared contract -> {}", handoff.null_outcomes("s3-strategist-to-designer"), {})
    check_eq("K0.2: a contract that does not exist -> {}", handoff.null_outcomes("no-such-contract"), {})
    check("K0.2: the old reader is gone, with no alias", not hasattr(handoff, "null_outcome"))
    legacy = handoff.null_outcome_entries(syn_doc(LEGACY).data["null_outcome"])
    check_eq("K0.2: a synthetic LEGACY block -> the one-entry map of the keyed shape",
             legacy, {"scope": {"condition": "triage_has_no_repair",
                                "params": {"repair_verdicts": ["TEST_BUG", "TEST_BUG:collection", "FLAKY"],
                                           "listed_in": "not_for_repair"},
                                "words": {"header.window": {"word": "none", "means": "nothing is handed for repair"}}}})
    # fail closed: each of these gives nothing for the entry, so the contract behaves as if it declared nothing
    shapes = {
        "an empty block": "null_outcome:",
        "an entry that is not a map": "null_outcome:\n  scope: none",
        "an entry with no condition": VALID.replace("    condition: triage_has_no_repair\n", ""),
        "an entry whose condition is not text": VALID.replace("condition: triage_has_no_repair", "condition: 7"),
        "a mixed shape (legacy `section` beside keyed entries)": "null_outcome:\n  section: scope\n" + VALID.split("\n", 1)[1],
        "a key outside REQUIRED_LISTS": VALID.replace("  scope:", "  person:", 1),
        "an entry holding a key a declaration does not have (`joint`)": VALID + "\n    joint: x",
        "params that are not a map": VALID.replace("    params:\n      repair_verdicts: [TEST_BUG, \"TEST_BUG:collection\", FLAKY]\n"
                                                    "      listed_in: not_for_repair\n", "    params: nope\n"),
        "words whose entry lacks `means`": VALID.replace('        means: "nothing is handed for repair"\n', ""),
        "a legacy block with a key of its own (`extra`)": LEGACY + "\n  extra: 1",
        "a legacy block naming a section outside REQUIRED_LISTS": LEGACY.replace("section: scope", "section: person"),
    }
    for label, block in shapes.items():
        got = handoff.null_outcome_entries(syn_doc(block).data.get("null_outcome"))
        check_eq(f"K0.2: {label} -> {{}} for that entry (the old refusal stands)", got, {})
        report = audit_syn(block)
        check(f"K0.2 negative: {label} fed to audit() is red, naming the contract and the defect",
              any(p.startswith("syn:") and "null_outcome" in p for p in report.problems), "; ".join(about(report)))
    check_eq("K0.2: the legacy shape in a contract is red in the detector - convert to the keyed shape",
             [p for p in about(audit_syn(LEGACY)) if "legacy" in p][:1] != [], True)
    check_in("K0.2: ...and says to convert", "convert to the keyed shape", " ".join(about(audit_syn(LEGACY))))
    green = audit_syn(VALID)
    check_eq("K0.2 control: the well-formed block is accepted by the same call (nothing about its declaration is red)",
             [p for p in green.problems if "syn" in p and "null_outcome" in p], [])
    check_eq("K0.2: a half-edit of the real tree is red too - the real S7 file with an empty block",
             about(audit(raw=lambda c: {} if c == S7 else NO.cached_raw(c)), S7)[:1] != [],
             True)


# -------------------------------------------------------------------------------------------- K0.3
def the_registry_and_the_declaration_shape() -> None:
    check_eq("K0.3 control: the real S7 block (and its synthetic twin) has nothing wrong", entry_problems(VALID), [])
    real_doc = handoff.template(S7)
    check_eq("K0.3 control: ...nor does the file itself",
             NO.entry_problems("scope", real_doc.data["null_outcome"]["scope"], spec=handoff.spec(S7),
                               sections=handoff.sections(S7), stage_ids=STAGE_IDS), [])
    cases = (
        ("a misspelled condition", VALID.replace("triage_has_no_repair", "triage_has_no_repairs"), "unknown condition"),
        ("a reserved condition", VALID.replace("triage_has_no_repair", "sibling_in"),
         "reserved for node N1; no implementation yet"),
        ("a missing param", VALID.replace("      listed_in: not_for_repair\n", ""), "missing param `listed_in`"),
        ("an unknown param", VALID.replace("      listed_in: not_for_repair\n", "      listed_in: not_for_repair\n      extra: 1\n"),
         "unknown param `extra`"),
        ("a listed_in naming no list section", VALID.replace("listed_in: not_for_repair", "listed_in: not_for_repairs"),
         "names no list section"),
        ("empty repair_verdicts", VALID.replace('[TEST_BUG, "TEST_BUG:collection", FLAKY]', "[]"),
         "not a non-empty list of words"),
        ("repair_verdicts that the state field does not offer",
         VALID.replace("FLAKY]", "FLAKY, WHATEVER]"), "WHATEVER"),
        ("a words key that is no field of the contract", VALID.replace("header.window:", "header.windows:"),
         "`words` names `header.windows`"),
        ("a source that is not the condition's", VALID.replace("source: work/triage.json", "source: work/other.json"),
         "`source` is 'work/other.json'"),
        ("a `joint` key (node N1's)", VALID + "\n    joint: x", "`joint` belongs to node N1"),
        ("an `only_when` key (node N1's)", VALID + "\n    only_when: x", "`only_when` belongs to node N1"),
        ("a declaration under a key that is not a REQUIRED_LISTS list (E13)", VALID.replace("  scope:", "  person:", 1),
         "arrives with N1"),
    )
    for label, block, needle in cases:
        doc = syn_doc(block)
        raw = doc.data.get("null_outcome") or {}
        section, entry = next(iter(raw.items())) if raw else ("scope", None)
        found = NO.entry_problems(section, entry, spec=handoff.spec_of(doc), sections=handoff.sections_of(doc),
                                  stage_ids=STAGE_IDS)
        check_in(f"K0.3: {label} is refused, in words", needle, " | ".join(found))
    check_eq("K0.3: the registry holds 12 conditions (plan_defers_all is not one of them: Q14-b)",
             (len(NO.CONDITIONS), "plan_defers_all" in NO.CONDITIONS), (12, False))
    live = sorted(name for name, c in NO.CONDITIONS.items() if c.status == "live")
    check_eq("K0.3: exactly one condition is live - the pilot's; every other is reserved for its node (Q-N0-1)",
             live, ["triage_has_no_repair"])
    for name, condition in NO.CONDITIONS.items():
        check(f"K0.3: {name}: its parameter kinds are in the closed set",
              all(kind in NO.PARAM_KINDS for kind in condition.params.values()), str(condition.params))
        check(f"K0.3: {name}: a reserved condition names no impl, a live one names one that resolves",
              (condition.impl is None) if condition.status == "reserved" else (NO.unresolved(condition.impl, SCRIPTS) == ""),
              str(condition.impl))
    check_eq("K0.3: the live impl is the pilot's function, which stays in handoff_check (Q-N0-3)",
             NO.CONDITIONS["triage_has_no_repair"].impl, "handoff_check.py::_null_outcome_view")
    check("K0.3: ...and the module the check imports defines it", callable(HC._null_outcome_view))
    check_eq("K0.3: the live condition's source is the artifact the runtime reads (Q-N0-4)",
             NO.CONDITIONS["triage_has_no_repair"].source, "work/triage.json")
    check_in("K0.3: a declared source is checked against it, never read from it",
             "work/triage.json", HC.NO.CONDITIONS["triage_has_no_repair"].source)


# -------------------------------------------------------------------------------------------- K0.4
def the_walk_sizes_AT_and_BEYOND() -> None:
    check_eq("K0.4: AT the pins - the real tree is green", REAL.problems, [])
    short = audit(index=[r for r in REAL_INDEX if r["contract"] != "s9-retro-to-project"])
    check_in("K0.4 negative: a stubbed index minus one scope contract", "scope contracts: 18, pinned 19", " | ".join(short.problems))
    SYN["syn"] = syn_doc(VALID)
    extra = {"stage": "S7", "from": "a", "to": "b", "contract": "syn", "kind": "review"}
    plus = NO.audit(index=REAL_INDEX + [extra], spec_of=s_spec, sections_of=s_sections, raw=s_raw, reader=s_reader,
                    pins=PINS)
    check_in("K0.4 negative: plus one scope contract - the size is red", "scope contracts: 20, pinned 19", " | ".join(plus.problems))
    SYN["syn"] = syn_doc("")            # the same new contract, declaring nothing: it has no home, and is named
    unhomed = NO.audit(index=REAL_INDEX + [extra], spec_of=s_spec, sections_of=s_sections, raw=s_raw, reader=s_reader,
                       pins=PINS)
    check_in("K0.4 negative: ...and the new one is NAMED (it has no home)", "syn:scope has no home", " | ".join(unhomed.problems))
    less = copy.deepcopy(REAL_STAGES)
    less["stages"][8]["required_outputs"] = less["stages"][8]["required_outputs"][:-1]
    check_in("K0.4 negative: stages minus one output", "required outputs: 15, pinned 16", " | ".join(audit(stages=less).problems))
    more = copy.deepcopy(REAL_STAGES)
    more["stages"][8]["required_outputs"] = more["stages"][8]["required_outputs"] + ["work/new.json"]
    found = " | ".join(audit(stages=more).problems)
    check_in("K0.4 negative: stages plus one output - the size is red", "required outputs: 17, pinned 16", found)
    check_in("K0.4 negative: ...and it is named", "S8:work/new.json has no home", found)
    pinned = PINS["tool_fields"]
    check_in("K0.4 negative: a `tool_fields` stub returning one fewer", f"tool fields: {pinned - 1}, pinned {pinned}",
             " | ".join(audit(fields=REAL_FIELDS[:-1]).problems))
    check_in("K0.4 negative: a `tool_fields` stub returning one more", f"tool fields: {pinned + 1}, pinned {pinned}",
             " | ".join(audit(fields=REAL_FIELDS + [("s9-retro-to-project", "x", "claims.new_receipt", "")]).problems))
    produce_no_scope = audit_syn(VALID, kind="produce", scope="")
    check_in("K0.4 negative: a `produce` contract with no `scope`", "kind produce carries an item list, and the contract has no",
             " | ".join(produce_no_scope.problems))
    setup_scope = audit_syn(VALID, kind="setup")
    check_in("K0.4 negative: a `setup` contract with a `scope`", "kind setup has no item list, and the contract carries `scope`",
             " | ".join(setup_scope.problems))
    as_map = audit_syn(VALID, kind="produce", scope="scope:\n  id: <instance id>")
    check_in("K0.4 negative: a `scope` that is a map", "`scope` is a map, and a required item list is a list",
             " | ".join(as_map.problems))
    odd = audit_syn(VALID, kind="mystery")
    check_in("K0.4 negative: a kind that is none of the six", "kind 'mystery' is not one of", " | ".join(odd.problems))
    check_eq("K0.4: the 4 contracts with no item list are exactly the setup / decision / report ones",
             sorted(r["kind"] for r in REAL_INDEX if r["kind"] in NO.NO_SCOPE_KINDS), ["decision", "decision", "report", "setup"])
    few = audit(data=mutated(lambda d: d["pending"].pop() if d["pending"][-1]["kind"] == "conditional" else None))
    check_in("K0.4 negative: a conditional row less", "conditional fields: 10, pinned 11", " | ".join(few.problems))
    fewer = audit(data=mutated(lambda d: d["never_empty"].pop(8)))
    check_in("K0.4 negative: a validator row less", "validator rows: 15, pinned 16", " | ".join(fewer.problems))


# -------------------------------------------------------------------------------------------- K0.5
def one_home_for_each_item() -> None:
    gone = audit(reader=lambda c: {} if c == S7 else NO.cached_reader(c))
    check_in("K0.5 negative: the reader stubbed to return {} for s7-analyst-to-automator -> red", "s7-analyst-to-automator:scope has no home",
             " | ".join(gone.problems))
    twice = audit(data=mutated(lambda d: d["pending"].append(
        {"kind": "scope", "carrier": "s7-analyst-to-automator:scope", "node": "N1", "default": False,
         "intent": "declare", "inventory": ""})))
    check_in("K0.5 negative: a pending row duplicating a declared item -> two homes", "s7-analyst-to-automator:scope has two homes",
             " | ".join(twice.problems))
    both = audit(data=mutated(lambda d: d["pending"].append(
        {"kind": "scope", "carrier": "s1-scout-to-tester:scope", "node": "N5", "default": False,
         "intent": "declare", "inventory": ""})))
    check_in("K0.5 negative: a pending row beside a never_empty row -> two homes", "s1-scout-to-tester:scope has two homes",
             " | ".join(both.problems))
    stale = audit(data=mutated(lambda d: d["pending"].append(
        {"kind": "scope", "carrier": "no-such:scope", "node": "N1", "default": False, "intent": "declare", "inventory": ""})))
    check_in("K0.5 negative: a row whose carrier the walk does not meet -> stale", "no-such:scope: stale row", " | ".join(stale.problems))
    stale_ne = audit(data=mutated(lambda d: d["never_empty"].append(
        {"id": "NE99", "kind": "output", "carrier": "S3:work/gone.json", "requirement": "x" * 5, "why": "w" * 40,
         "guard": "no guard: " + "g" * 40})))
    check_in("K0.5 negative: a never_empty row the walk does not meet -> stale", "S3:work/gone.json", " | ".join(stale_ne.problems))
    stale_cond = audit(data=mutated(lambda d: d["pending"][-1].update(carrier="gate-b-to-delivery:external_writes.nothing")))
    check_in("K0.5 negative: a conditional row whose field is not in the contract -> stale", "has no field `external_writes.nothing`",
             " | ".join(stale_cond.problems))
    removed = audit(data=mutated(lambda d: d["pending"].pop(0)))
    check_in("K0.5 negative (E6): an item with no home is red BY NAME", "s3-strategist-to-designer:scope has no home",
             " | ".join(removed.problems))
    check_eq("K0.5 control: the validator rows are never 'stale' - the walk does not meet them",
             [p for p in REAL.problems if "stale" in p], [])
    new_field = audit(fields=REAL_FIELDS + [("s9-retro-to-project", "qa-retro-analyst", "claims.new_receipt", "")],
                      pins={**PINS, "tool_fields": PINS["tool_fields"] + 1})
    check_in("K0.5 (E6): a NEW tool field cannot be born pending - it is red by name", "s9-retro-to-project:claims.new_receipt has no home",
             " | ".join(new_field.problems))


# -------------------------------------------------------------------------------------------- K0.6
def the_never_empty_rows() -> None:
    rows = REAL_DATA["never_empty"]
    ids = [r["id"] for r in rows]
    check_eq("K0.6: the ids are unique", len(ids), len(set(ids)))
    check("K0.6: NE6 and NE8 are absent (NE6: F10; NE8: Q-N0-8 - role-to-conductor sits under `escalation:`, never walked)",
          "NE6" not in ids and "NE8" not in ids, str(ids))
    check_eq("K0.6: the row ids are the 22 the plan lists and the two of the S5 plan handovers (NE25, NE26), NE27 (gate B orders), NE28 (the register evidence ref), NE29 (the Then quotes) and NE30, NE31 (the register's branches and source obligations, G2-11) and NE32 (the register's pictures) and NE33 (the bug reporter's scope, HF8-21)",
             sorted(ids, key=lambda i: int(i[2:])),
             [f"NE{n}" for n in (1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38)])
    row = next(r for r in rows if r["id"] == "NE37")
    check_eq("K0.6: NE37 (the first look's rows, t-2277 FL-2) is guarded by its one validator",
             (row["kind"], row["guard"]), ("validator", "first_look.py::put_problems"))
    row = next(r for r in rows if r["id"] == "NE36")
    check_eq("K0.6: NE36 (the provisional registry, t-2181 PC-3) is guarded by its one reader",
             (row["kind"], row["guard"]), ("validator", "contract.py::manifest_provisional"))
    check("K0.6: every `why` is at least 30 characters", all(len(r["why"]) >= 30 for r in rows))
    for r in rows:
        guard = r["guard"]
        if guard.startswith("no guard: "):
            check(f"K0.6: {r['id']}: `no guard:` carries its reason (>= 30 characters)", len(guard[10:].strip()) >= 30, guard)
        else:
            check_eq(f"K0.6: {r['id']}: the guard `{guard}` resolves by AST", NO.unresolved(guard, SCRIPTS), "")
        check(f"K0.6: {r['id']}: no line number in the guard", not re.search(r":\d+", guard), guard)

    def with_row(**changes):
        def fn(data):
            data["never_empty"][2].update(changes)
        return audit(data=mutated(fn))

    AT = with_row(why="x" * 30)
    check_eq("K0.6 AT: a `why` of 30 characters is green", [p for p in AT.problems if "`why`" in p], [])
    BEYOND = with_row(why="x" * 29)
    check_in("K0.6 BEYOND: a `why` of 29 characters is red", "`why` is shorter than 30", " | ".join(BEYOND.problems))
    check_in("K0.6 negative: a guard naming a function that is not there (stage_S5x)", "no function `stage_S5x`",
             " | ".join(with_row(guard="story_run.py::stage_S5x").problems))
    check_in("K0.6 negative: a guard naming a file that is not there", "cannot be read",
             " | ".join(with_row(guard="nothing_here.py::main").problems))
    check_in("K0.6 negative: a guard that is neither a function nor a `no guard:`", "is not `<scripts file>.py::<function>`",
             " | ".join(with_row(guard="story_run.py").problems))
    check_in("K0.6 negative: a line number in a guard", "holds a line number",
             " | ".join(with_row(guard="story_run.py:4624").problems))
    check_in("K0.6 negative: a line number after the function", "holds a line number",
             " | ".join(with_row(guard="story_run.py::stage_S5:12").problems))
    check_eq("K0.6 AT: `no guard:` with 30 characters of reason is green",
             [p for p in with_row(guard="no guard: " + "y" * 30).problems if "guard" in p], [])
    check_in("K0.6 BEYOND: `no guard:` with 29 is red", "owes its reason",
             " | ".join(with_row(guard="no guard: " + "y" * 29).problems))
    dup = audit(data=mutated(lambda d: d["never_empty"][1].update(id="NE1")))
    check_in("K0.6 negative: a duplicate id is red, by id", "duplicate id NE1", " | ".join(dup.problems))
    # the AST resolution (E14): presence of a DEFINITION only
    with tempfile.TemporaryDirectory(prefix="qa-null-ast-") as tmp:
        (Path(tmp) / "x.py").write_text(
            "# def in_comment(): pass\n"
            "TEXT = \"def in_string(): pass\"\n"
            "def outer():\n    def nested(): pass\n"
            "class K:\n    def method(self): pass\n", encoding="utf-8")
        for name, want in (("outer", True), ("nested", True), ("method", True), ("in_comment", False),
                           ("in_string", False), ("absent", False)):
            check_eq(f"K0.6 AST: `{name}` {'counts' if want else 'does NOT count'} as a definition",
                     NO.unresolved(f"x.py::{name}", Path(tmp)) == "", want)


# -------------------------------------------------------------------------------------------- K0.7
def the_ratchet() -> None:
    check_eq("K0.7: pending equals the last entry of the history", (len(REAL_DATA["pending"]), REAL_DATA["ratchet"][-1]["pending"]),
             (52, 52))
    check_eq("K0.7: SC1-2 part C lowered the history 58 -> 53 -> 52 (five claims, then the S3 form revision field, nothing read them)",
             [row["pending"] for row in REAL_DATA["ratchet"]], [58, 53, 52])
    extra = {"kind": "tool_field", "carrier": "s9-retro-to-project:claims.zzz", "node": "N6", "default": True, "intent": "declare", "inventory": ""}
    check_in("K0.7 negative: one extra pending row", "pending has 53 rows and the ratchet's last entry says 52",
             " | ".join(audit(data=mutated(lambda d: d["pending"].append(extra))).problems))
    check_in("K0.7 negative: a history that rises ([58, 53, 52, 53])", "ratchet rises from 52 to 53",
             " | ".join(audit(data=mutated(lambda d: d["ratchet"].append({"node": "N1", "pending": 53}))).problems))
    check_eq("K0.7 control: a history that falls ([60, 58, 53, 52]) is green - only the real count has to match",
             audit(data=mutated(lambda d: d["ratchet"].insert(0, {"node": "N0", "pending": 60}))).problems, [])
    check_in("K0.7 negative: a pending row at node N9", "node 'N9' is not one of N1..N8",
             " | ".join(audit(data=mutated(lambda d: d["pending"][0].update(node="N9"))).problems))

    def drop_node(data):
        del data["pending"][0]["node"]
    check_in("K0.7 negative: a pending row with no node", "lacks `node`", " | ".join(audit(data=mutated(drop_node)).problems))
    check_in("K0.7 negative: an empty history", "ratchet is empty",
             " | ".join(audit(data=mutated(lambda d: d.update(ratchet=[]))).problems))
    check_in("K0.7 negative: a default row at the wrong node (the default rule says S6 -> N3)", "the default rule puts stage S6 at N3",
             " | ".join(audit(data=mutated(lambda d: next(r for r in d["pending"] if r["carrier"] == "s6-runner-to-analyst:run.totals").update(node="N2"))).problems))
    check_in("K0.7 negative: a conditional row that claims the default rule", "never by the default rule",
             " | ".join(audit(data=mutated(lambda d: d["pending"][-1].update(default=True))).problems))


# -------------------------------------------------------------------------------------------- E8
def the_data_file_is_closed() -> None:
    check_in("E8: an absent file is red, naming it", "cannot be read",
             " | ".join(NO.audit(data=NO.load_data(Path(tempfile.gettempdir()) / "qa-no-such-null-outcomes.json")[1]).problems))
    with tempfile.TemporaryDirectory(prefix="qa-null-data-") as tmp:
        broken = Path(tmp) / "null-outcomes.json"
        broken.write_text("{not json", encoding="utf-8")
        data, why = NO.load_data(broken)
        check_eq("E8: a malformed file -> no data and a reason that names the file", (data, "null-outcomes.json is not valid JSON" in why), (None, True))
        check_in("E8: ...and the detector is red on it", "not valid JSON", " | ".join(NO.audit(data=why).problems))
        broken.write_text("[]", encoding="utf-8")
        check_in("E8: a file that is not an object", "is not an object", NO.load_data(broken)[1])
    check_in("E8: an unknown key at the top", "unknown key `extra`", " | ".join(audit(data=mutated(lambda d: d.update(extra=1))).problems))
    check_in("E8: an unknown key in a row", "unknown key `nope`",
             " | ".join(audit(data=mutated(lambda d: d["pending"][0].update(nope=1))).problems))
    check_in("E8: a missing top key", "lacks `ratchet`", " | ".join(audit(data=mutated(lambda d: d.pop("ratchet"))).problems))
    check_in("E8: a schema this reader does not read", "schema_version is 2",
             " | ".join(audit(data=mutated(lambda d: d.update(schema_version=2))).problems))
    check_in("E8: a default_node_by_stage with a hole", "default_node_by_stage has no node for `S3`",
             " | ".join(audit(data=mutated(lambda d: d["default_node_by_stage"].pop("S3"))).problems))
    check_in("E8: a default_node_by_stage naming a stage that does not exist", "which is no stage or gate",
             " | ".join(audit(data=mutated(lambda d: d["default_node_by_stage"].update(S99="N1"))).problems))


# -------------------------------------------------------------------------------------------- K0.9
def the_f1_rows() -> None:
    rows = REAL_DATA["tightening_exceptions"]
    check_eq("K0.9: four F1 rows (the scalars a later node's declaration will make refuse `none`)", len(rows), 4)
    for row in rows:
        spec = NO.cached_spec(row["contract"])
        check(f"K0.9: {row['contract']}:{row['field']} is a field of its contract", row["field"] in spec)
        check(f"K0.9: {row['condition']} is a registered condition - and not an implemented one (N0 records, it tightens nothing)",
              row["condition"] in NO.CONDITIONS and NO.CONDITIONS[row["condition"]].status == "reserved", row["condition"])
        check_eq(f"K0.9: {row['field']}: the measurement - 0 hits in either form, controls 3 and 2",
                 (row["count_a"], row["count_b"], row["control_a"], row["control_b"]), (0, 0, 3, 2))
    check_eq("K0.9: the fields are the four of F1", sorted(r["field"] for r in rows),
             ["budget.if_over", "person.words", "review_scope.cases", "run.witness"])
    bad = audit(data=mutated(lambda d: d["tightening_exceptions"][0].update(field="person.nothing")))
    check_in("K0.9 negative: a row with an absent field", "has no field `person.nothing`", " | ".join(bad.problems))
    bad = audit(data=mutated(lambda d: d["tightening_exceptions"][0].update(condition="nonesuch")))
    check_in("K0.9 negative: a condition that is not registered", "`nonesuch` is not registered", " | ".join(bad.problems))
    bad = audit(data=mutated(lambda d: d["tightening_exceptions"][0].update(count_a=-1)))
    check_in("K0.9 negative: a count that is not a count", "`count_a` is not a count", " | ".join(bad.problems))


# ------------------------------------------------------------------------------------------- K0.10
def one_copy_of_the_fr11_selection() -> None:
    walker = (SCRIPTS / "tests" / "test_field_producers.py").read_text(encoding="utf-8")
    pattern = re.compile(r"^NEEDS_A_TOOL\s*=", re.M)
    check("K0.10 positive control: the same pattern finds the definition where it lives (null_outcomes.py)",
          bool(pattern.search((SCRIPTS / "null_outcomes.py").read_text(encoding="utf-8"))))
    check("K0.10: NEEDS_A_TOOL is no longer defined in test_field_producers.py", not pattern.search(walker))
    check_in("K0.10: ...it asks null_outcomes for the selection", "NO.tool_fields()", walker)
    check_eq("K0.10: the selection is the 27 fields of the FR-11 walk", len(REAL_FIELDS), 27)
    check("K0.10: every selected field is a tool field - the regex matches its leaf or its hint",
          all(NO.NEEDS_A_TOOL.search(p.rsplit(".", 1)[-1]) or NO.NEEDS_A_TOOL.search(h) for _c, _r, p, h in REAL_FIELDS))


# ------------------------------------------------------------------------------------------- K0.12
def undeclared_contracts_refuse_as_before() -> None:
    task = temp_dir("qa-null-k012-")
    try:
        scope_contracts = [r for r in REAL_INDEX if r["kind"] in NO.SCOPE_KINDS and r["contract"] != S7]
        check_eq("K0.12: eighteen undeclared contracts carry a scope", len(scope_contracts), 18)

        def problems_of(contract: str, row: dict) -> list:
            text = (handoff.CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8")
            form = handoff_init.fill_head(text, task="QA-NULL-1", dispatch="X-1", role=str(row.get("from") or "x"),
                                          stage=str(row.get("stage") or row.get("gate") or "S0"), scope="")
            done = re.sub(r"(?ms)^scope:.*?(?=^\S)", "scope: []\n\n", form, count=1)
            _doc, _fixed, problems, _j, _d = HC.check(handoff.parse(done), contract, HC.Artifacts(task), fix=False, use_judge=False)
            return [p for p in problems if p.path == "scope"]

        for row in scope_contracts:
            got = problems_of(row["contract"], row)
            # Re-pinned (t-298; HF8-7, t-204 added the row-form sentence): the old words still open the text, and the
            # text now also says how a row is written (what is wrong, what is expected, how to pass - FR-1).
            texts = [p.text for p in got]
            check_eq(f"K0.12: {row['contract']}: an empty scope is ONE `scope` problem", len(texts), 1)
            check(f"K0.12: {row['contract']}: ...it opens with the old words",
                  bool(texts) and texts[0].startswith(OLD_EMPTY_SCOPE), str(texts))
            check(f"K0.12: {row['contract']}: ...and then says how a row of a list is written",
                  bool(texts) and texts[0][len(OLD_EMPTY_SCOPE):].strip() == ROW_FORM_SENTENCE, str(texts))
        control = problems_of(S7, next(r for r in REAL_INDEX if r["contract"] == S7))
        check_not_in("K0.12 control: the same probe on S7 does NOT yield that text", "no rows. One row per item in scope",
                     " ".join(p.text for p in control))
    finally:
        cleanup(task)


def the_runtime_fails_closed() -> None:
    """E3 and the Lead's edge: a declaration that is malformed, or names a RESERVED condition, is not applied - the old
    refusal stands - and nothing in the package carries such a declaration today (pinned at 0)."""
    real = handoff.null_outcomes
    task = temp_dir("qa-null-closed-")
    try:
        (task / "work").mkdir(parents=True)
        (task / "work" / "triage.json").write_text(json.dumps({"triage": []}), encoding="utf-8")
        (task / "work" / "run-report.json").write_text(json.dumps({"current_results": [], "current_totals": {"passed": 1}}), encoding="utf-8")
        text = (handoff.CONTRACTS / f"{S7}.yaml").read_text(encoding="utf-8")
        form = handoff_init.fill_head(text, task="QA-NULL-1", dispatch="S7-x-1", role="qa-failure-analyst", stage="S7", scope="")
        form = re.sub(r"(?ms)^scope:.*?(?=^\S)", "scope: []\n\n", form, count=1)
        base = real(S7)["scope"]

        def refused(label: str, entry) -> None:
            handoff.null_outcomes = lambda _c: {"scope": entry}
            try:
                _d, _f, problems, _j, _dd = HC.check(handoff.parse(form), S7, HC.Artifacts(task), fix=False, use_judge=False)
            finally:
                handoff.null_outcomes = real
            check_in(f"E3: {label}: not applied - the old refusal stands", "no rows. One row per item in scope", " ".join(p.text for p in problems))

        refused("a listed_in naming a field that is not there",
                dict(base, params=dict(base["params"], listed_in="not_for_repairs")))
        refused("a param missing", dict(base, params={"repair_verdicts": base["params"]["repair_verdicts"]}))
        refused("a RESERVED condition", {"condition": "sibling_in", "params": {"field": "header.window", "in": ["x"]}})
        refused("a source that is not the condition's", dict(base, source="work/elsewhere.json"))
        _d, _f, problems, _j, _dd = HC.check(handoff.parse(form), S7, HC.Artifacts(task), fix=False, use_judge=False)
        check("E3 control: the real declaration, on the same form, accepts the empty scope", not [p for p in problems if p.path == "scope"],
              " ".join(p.text for p in problems))
        # E10: the check reads the PACKAGE template - what a role writes into the block of its own form changes nothing
        edited = re.sub(r"(?ms)^null_outcome:.*?(?=^\S)", "null_outcome:\n  scope: nothing here\n\n", form, count=1)
        check("E10 control: the edit is really in the form", "scope: nothing here" in edited)
        _d, _f, problems, _j, _dd = HC.check(handoff.parse(edited), S7, HC.Artifacts(task), fix=False, use_judge=False)
        check("E10: a role's edit of the block in its own form neither loosens nor tightens the check",
              not [p for p in problems if p.path == "scope"], " ".join(p.text for p in problems))
        removed = re.sub(r"(?ms)^null_outcome:.*?(?=^\S)", "", form, count=1)
        _d, _f, problems, _j, _dd = HC.check(handoff.parse(removed), S7, HC.Artifacts(task), fix=False, use_judge=False)
        check("E10: nor does deleting it", not [p for p in problems if p.path == "scope"], " ".join(p.text for p in problems))
    finally:
        handoff.null_outcomes = real
        cleanup(task)
    reserved = audit_syn(VALID.replace("triage_has_no_repair", "sibling_in"))
    check_eq("the Lead's edge: a reserved condition in a declaration is counted (the package's own count is pinned at 0)",
             (reserved.counts["reserved_declared"], REAL.counts["reserved_declared"]), (1, 0))


# ------------------------------------------------------------------------------------------- K0.15
def the_debt_row() -> None:
    debt = (PLUGIN_ROOT / "design" / "factory-rules-debt.md").read_text(encoding="utf-8")
    rows = [ln for ln in debt.splitlines() if ln.startswith("|") and "FR-23" in ln and "FR-5" in ln]
    check_eq("K0.15: factory-rules-debt.md carries one FR-23 / FR-5 row", len(rows), 1)
    row = rows[0] if rows else ""
    for needle in ("references/null-outcomes.json", "`pending[]`", "t-305", "B-253"):
        check_in(f"K0.15: the row names {needle}", needle, row)
    check("K0.15 positive control: the same line filter finds the pilot's FR-23 row (one more row mentions FR-23 alone)",
          len([ln for ln in debt.splitlines() if ln.startswith("|") and "FR-23" in ln]) >= 2)


# ------------------------------------------------------------------------------------------- K0.16
def the_verdict_list_formatter() -> None:
    for n, want in ((1, "A"), (2, "A or B"), (3, "A, B or C"), (4, "A, B, C or D")):
        check_eq(f"K0.16: {n} verdict(s) render as {want!r}", HC._or_list(list("ABCD"[:n])), want)
    check_eq("K0.16: the pilot's three render byte for byte as the old refusal spelled them",
             HC._or_list(["TEST_BUG", "TEST_BUG:collection", "FLAKY"]), "TEST_BUG, TEST_BUG:collection or FLAKY")
    check_eq("K0.16: NULL_IDS_SHOWN is still 6 and importable from handoff_check", HC.NULL_IDS_SHOWN, 6)
    task = temp_dir("qa-null-fmt-")
    try:
        (task / "work").mkdir(parents=True)
        (task / "work" / "triage.json").write_text(json.dumps({"triage": [
            {"instance_id": "t[1]", "test": "x::t[1]", "verdict": "TEST_BUG"}]}), encoding="utf-8")
        (task / "work" / "run-report.json").write_text(json.dumps({"current_results": [{"instance_id": "t[1]", "status": "failed"}],
                                                                   "current_totals": {"failed": 1}}), encoding="utf-8")
        text = (handoff.CONTRACTS / f"{S7}.yaml").read_text(encoding="utf-8")
        form = handoff_init.fill_head(text, task="QA-NULL-1", dispatch="S7-x-1", role="qa-failure-analyst", stage="S7", scope="")
        doc = handoff.parse(re.sub(r"(?ms)^scope:.*?(?=^\S)", "scope: []\n\n", form, count=1))
        base = handoff.null_outcomes(S7)["scope"]

        def refusal(verdicts: list) -> str:
            entry = dict(base, params=dict(base["params"], repair_verdicts=verdicts))
            problems, _openable = HC._null_outcome_view(doc, "scope", entry, S7, HC.Artifacts(task))
            return " ".join(p.text for p in problems)

        flaky = refusal(["TEST_BUG", "TEST_BUG:collection", "FLAKY"])
        check_in("K0.16: with FLAKY in the params the clause about a FLAKY row already fixed is said",
                 "no TEST_BUG, TEST_BUG:collection or FLAKY row at all, a FLAKY row already fixed included.", flaky)
        check_not_in("F14: ...and the `reorder` clause is NOT said when no row asks for one", "reorder", flaky)
        plain = refusal(["TEST_BUG", "TEST_BUG:collection"])
        check_in("K0.16: without FLAKY the verdict list shrinks with it", "means no TEST_BUG or TEST_BUG:collection row at all.", plain)
        check_not_in("K0.16: ...and the FLAKY clause is NOT said", "FLAKY", plain)
        one = refusal(["TEST_BUG"])
        check_in("K0.16: one verdict reads as one word", "means no TEST_BUG row at all.", one)
    finally:
        cleanup(task)


# ------------------------------------------------------------------------------------------- t-335 C-n2
def the_parse_caches_are_keyed_by_path_and_content() -> None:
    """t-335 C-n2 (critic t-334): the caches were keyed by (contract name, (mtime, size)). A copy of the tree, which the
    tests that corrupt a copy point `handoff.CONTRACTS` at, keeps the name and - after a same-size rewrite inside one
    clock tick, 66 of 200 measured - the stamp, so the real tree's parse was served for the copy (or the copy's for the
    real tree). The key now holds the PATH and a digest of the bytes. Two controls on a pair of directories and one on a
    rewrite that keeps size AND mtime; the negative control is the old key, written out."""
    import os
    real_dir = handoff.CONTRACTS
    a, b = temp_dir("qa-null-cache-a-"), temp_dir("qa-null-cache-b-")
    try:
        source = (real_dir / f"{S7}.yaml").read_text(encoding="utf-8")
        marker = "to_role: qa-automator"
        check("C-n2 fixture: the contract has the marker line the rewrite changes", source.count(marker) == 1)
        same_size = source.replace(marker, "to_role: qa-automatoX")
        check("C-n2 fixture: the rewrite keeps the byte size", len(same_size.encode("utf-8")) == len(source.encode("utf-8")))
        for folder, text in ((a, source), (b, same_size)):
            (folder / f"{S7}.yaml").write_text(text, encoding="utf-8")
            (folder / "vocabulary.yaml").write_bytes((real_dir / "vocabulary.yaml").read_bytes())
        # one mtime for both files: the stamp the old key was made of is identical
        ns = (a / f"{S7}.yaml").stat().st_mtime_ns
        os.utime(b / f"{S7}.yaml", ns=(ns, ns))
        old_key = lambda folder: (S7, ((folder / f"{S7}.yaml").stat().st_mtime_ns, (folder / f"{S7}.yaml").stat().st_size))  # noqa: E731
        check("C-n2 negative control: the OLD key (name, mtime, size) is identical for the two directories' files",
              old_key(a) == old_key(b), f"{old_key(a)} {old_key(b)}")
        handoff.CONTRACTS = a
        try:
            from_a = NO.doc_of(S7).data.get("to_role")
            spec_a = NO.cached_spec(S7)
            handoff.CONTRACTS = b
            from_b = NO.doc_of(S7).data.get("to_role")
            spec_b = NO.cached_spec(S7)
            check_eq("C-n2: two directories with one name and one stamp: each is parsed from its own file",
                     (from_a, from_b), ("qa-automator", "qa-automatoX"))
            check("C-n2: ...and the spec cache keeps them apart too (a different object per directory)", spec_a is not spec_b)
            # the same file rewritten with the same size and the same mtime (a clock tick): the digest tells
            (b / f"{S7}.yaml").write_text(source, encoding="utf-8")
            os.utime(b / f"{S7}.yaml", ns=(ns, ns))
            check_eq("C-n2: a same-size rewrite of one file that keeps its mtime is read anew, never from the stale entry",
                     NO.doc_of(S7).data.get("to_role"), "qa-automator")
            check("C-n2: an unchanged file is served from the cache (one parse, the same object twice)",
                  NO.doc_of(S7) is NO.doc_of(S7) and NO.cached_spec(S7) is NO.cached_spec(S7))
            handoff.CONTRACTS = b / "nowhere"
            try:
                NO.doc_of(S7)
                missing = ""
            except FileNotFoundError as exc:
                missing = str(exc)
            check("C-n2 edge: a contract with no file still raises FileNotFoundError, as `handoff.template` does", S7 in missing, missing)
        finally:
            handoff.CONTRACTS = real_dir
        # the guard-resolution cache: the same class, the same key
        code = temp_dir("qa-null-defs-")
        try:
            (code / "g.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
            first = NO.unresolved("g.py::alpha", code)
            (code / "g.py").write_text("def omega():\n    return 1\n", encoding="utf-8")        # the same size, one tick
            os.utime(code / "g.py", ns=(ns, ns))
            check("C-n2 (guards): `alpha` resolves, then the same-size rewrite that renames it is seen",
                  first == "" and NO.unresolved("g.py::alpha", code) != "" and NO.unresolved("g.py::omega", code) == "")
        finally:
            cleanup(code)
    finally:
        handoff.CONTRACTS = real_dir
        cleanup(a)
        cleanup(b)


def main() -> None:
    the_parse_caches_are_keyed_by_path_and_content()
    the_real_tree_is_green_and_the_line_is_printed()
    the_reader()
    the_registry_and_the_declaration_shape()
    the_walk_sizes_AT_and_BEYOND()
    one_home_for_each_item()
    the_never_empty_rows()
    the_ratchet()
    the_data_file_is_closed()
    the_f1_rows()
    one_copy_of_the_fr11_selection()
    undeclared_contracts_refuse_as_before()
    the_runtime_fails_closed()
    the_debt_row()
    the_verdict_list_formatter()
    finish("test_null_outcomes")


if __name__ == "__main__":
    main()
