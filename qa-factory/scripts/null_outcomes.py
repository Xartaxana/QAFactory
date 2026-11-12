"""Null outcomes: what each required list, stage output and tool-filled field says when it is empty (FR-23, t-305).

FR-23 says every step has a recordable completed state for the null outcome. On TP1-15045 (cmp2r, 02.10) the
S7 handover form had `scope`, the one list the check refuses empty, and a triage of two product bugs and five
stand blocks had no legal handover: the story stopped. The pilot (t-299) gave that one contract a declaration.
This module is the rest: a REGISTRY of the conditions a declaration may name, and a DETECTOR that walks everything
the factory requires and demands that each walked item has exactly one home:

  declared     the contract's own `null_outcome` entry (`handoff.null_outcomes`) - the empty is accepted on a
               named condition, which only code can judge (FR-13: the condition's logic is code, its parameters
               are data in the contract);
  never_empty  a row of `references/null-outcomes.json` - the item is never legitimately empty, and the row
               names the guard that refuses the empty, or says why no guard is needed;
  pending      a row of the same file - the declaration arrives at a NAMED node of t-305. The count only
               shrinks (the ratchet), so a new required item can never be born pending.

What is walked is enumerated from the source, never copied: the index rows that carry a REQUIRED_LISTS list
(14), the other rows, which must be setup/decision/report (4), every stage's `required_outputs` (16), the tool
fields the FR-11 walk selects (33), plus the conditional fields the data file names (11). The walk sizes are PINNED
by the caller: a detector that walks nothing is green for the wrong reason (t-317 F4).

N0 implements ONE condition, the pilot's `triage_has_no_repair`; the rest are registered with their parameter
schema, source and owning node and are `reserved` - each later node implements its own under its own critic-on-plan
(PROJECT.md p.6). A declaration that names a reserved condition is red.

The detector is a measurer (FR-28) and a validator, so it writes nothing (FR-45): `audit()` is pure over what it
is given, and the real tree is its default. Never run it with a hand-edited tree as "proof" - corrupt a COPY.
"""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
import handoff  # noqa: E402

DATA = PLUGIN / "references" / "null-outcomes.json"
STAGES = PLUGIN / "references" / "stages.json"

# --------------------------------------------------------------------------------------- the FR-11 selection
# A value no role can write out of its own prose. `_ref$` and `revision` are in; a path to the role's own artifact
# is not - the contract states that path and the role wrote the file. ONE copy: test_field_producers reads it here.
NEEDS_A_TOOL = re.compile(
    "receipt|witness|sha256|content_hash|_hash|provenance|fingerprint|totals"
    "|execution_status|computed|_ref$|revision")


_SPECS, _DOCS = {}, {}


def _stamp(*paths: Path):
    """The cache key of these files, or None when one cannot be read: for each one its PATH, (mtime, size) and a
    digest of its bytes. The path (t-335 C-n2): `handoff.CONTRACTS` is swapped to a copy of the tree by the tests
    that corrupt a copy, and a copy keeps the name and, after a same-size rewrite inside one clock tick, the stamp -
    the real tree's parse was then served for the copy, or the copy's for the real tree (66 of 200 same-size
    rewrites kept an identical (mtime, size) when measured). The digest closes the same hole inside one path: the
    file is read (a few kilobytes) and hashed, and only the parse - the expensive step - is kept."""
    out = []
    for path in paths:
        try:
            st = path.stat()
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
        except OSError:
            return None
        out.append((str(path), st.st_mtime_ns, st.st_size, digest))
    return tuple(out)


def doc_of(contract: str) -> "handoff.Doc":
    """The parsed contract template, kept by the file's stamp (read only: nothing here writes a Doc). The detector
    reads each contract's shape, declaration and sections, and parsing it three times per walk was most of the
    time of its own test; an edit to the file changes the stamp, so a stale parse is never read. A contract with no
    file raises `FileNotFoundError`, as `handoff.template` does."""
    stamp = _stamp(handoff.CONTRACTS / f"{contract}.yaml")
    if stamp is None:
        return handoff.template(contract)
    key = (contract, stamp)
    if key not in _DOCS:
        _DOCS[key] = handoff.template(contract)
    return _DOCS[key]


def cached_spec(contract: str) -> dict:
    """`handoff.spec(contract)`, kept by the stamp of the two files it is derived from (the contract and the
    vocabulary its `one of vocabulary.*` placeholders read). `spec` re-parses the whole vocabulary for every such
    placeholder - measured 6.3 of the 7.0 seconds of one walk - and the detector asks for every contract's spec,
    again and again in its own test; an edit to either file changes the stamp, so a stale entry is never read."""
    stamp = _stamp(handoff.CONTRACTS / f"{contract}.yaml", handoff.CONTRACTS / "vocabulary.yaml")
    if stamp is None:
        return handoff.spec(contract)                   # the caller's own error (a missing contract) stays its own
    key = (contract, stamp)
    if key not in _SPECS:
        _SPECS[key] = handoff.spec_of(doc_of(contract))
    return _SPECS[key]


def cached_sections(contract: str) -> dict:
    return handoff.sections_of(doc_of(contract))


def cached_raw(contract: str):
    """The contract's raw `null_outcome` block (`None` when it has none)."""
    return doc_of(contract).data.get("null_outcome")


def cached_reader(contract: str) -> dict:
    """`handoff.null_outcomes` over the cached parse: the same reader function applied to the same block."""
    return handoff.null_outcome_entries(cached_raw(contract))


def tool_fields(index_rows=None, spec_of=None) -> list:
    """`[(contract, from_role, path, hint)]`: every required scalar of every handoff contract that needs a tool
    to produce it - the FR-11 walk's selection (`test_field_producers.walk`), minus the optional fields and the
    ones the contract writes itself. Over-selecting is the allowed error (one more pending row); a field renamed
    out of the regex (`witness` -> `proof`) is NOT caught, and that limit is stated here, not hidden."""
    rows = (handoff.index().get("handoffs") or []) if index_rows is None else index_rows
    spec_of = spec_of or cached_spec
    out = []
    for entry in rows:
        contract = str(entry.get("contract") or "")
        for path, field in sorted(spec_of(contract).items()):
            if field.optional or handoff.owned_by_contract(path):
                continue
            hint = str(field.hint or "")
            leaf = path.rsplit(".", 1)[-1]
            if NEEDS_A_TOOL.search(leaf) or NEEDS_A_TOOL.search(hint):
                out.append((contract, entry.get("from"), path, hint))
    return out


# ------------------------------------------------------------------------------------------- the registry
class Condition(NamedTuple):
    """One named condition under which an empty section is the contract's own legitimate answer."""
    params: dict            # parameter name -> kind (PARAM_KINDS)
    source: str | None      # the artifact the condition reads; a declaration's `source:` must equal it (Q-N0-4)
    sources_read: tuple     # everything it reads, `source` included
    node: str               # the node of t-305 that owns it
    status: str             # "live" (implemented) | "reserved" (registered, its node implements it)
    impl: str | None        # "<scripts file>.py::<function>" with the signature (doc, section, entry, contract, art)
    opens_rows: bool        # `--fix` may open rows for it


PARAM_KINDS = ("list_section", "field_path", "words", "word", "stage", "kind")
STAGE_KINDS = ("automation", "manual")

CONDITIONS = {
    # The pilot (t-299). Its logic stays in handoff_check (Q-N0-3): the registry points at it, and the
    # t-309/t-323 sentinels that read handoff_check for `C.bind_triage(` keep finding it there.
    "triage_has_no_repair": Condition(
        {"repair_verdicts": "words", "listed_in": "list_section"}, "work/triage.json",
        ("work/triage.json", "work/run-report.json"), "N0", "live", "handoff_check.py::_null_outcome_view", True),
    "sibling_in": Condition({"field": "field_path", "in": "words"}, "form", (), "N1", "reserved", None, False),
    "sibling_equals": Condition({"field": "field_path", "value": "word"}, "form", (), "N4/N6", "reserved", None,
                                False),
    "sibling_all": Condition({"list": "list_section", "field": "field_path", "value": "word"}, "form", (), "N4",
                             "reserved", None, False),
    "stage_scope_empty": Condition({"stage": "stage", "kind": "kind"}, "controller stage-scope", (), "N2/N4",
                                   "reserved", None, False),
    "no_runtime_record": Condition({}, "evidence/runtime-provenance-*.json", (), "N2/N3", "reserved", None, False),
    "no_run_in_dispatch": Condition({}, "manifest runs[] / run blocks", (), "N2/N3", "reserved", None, False),
    "inventory_complete": Condition({}, "work/source-inventory.json", (), "N5", "reserved", None, False),
    "nothing_owed": Condition({"states": "words"}, "work/ledger.json", (), "N6", "reserved", None, False),
    "upstream_form_field": Condition({"contract": "word", "field": "word", "value": "word"}, "the upstream form",
                                     (), "N4", "reserved", None, False),
    "all_instances_not_in_scope": Condition({"list": "list_section"}, "form + manifest", (), "N2", "reserved",
                                            None, False),
    "no_channel_configured": Condition({}, "config external_writes", (), "N6", "reserved", None, False),
}
# `plan_defers_all` is NOT registered: an empty S3/S4 plan is the open-questions halt, never a null (Q14-b).

# ------------------------------------------------------------------------------------- the data file's shape
SCOPE_KINDS = ("produce", "review", "ledger")        # index kinds that carry an item list
NO_SCOPE_KINDS = ("setup", "decision", "report")     # index kinds that have none (index.yaml says so)
TOP_KEYS = ("schema_version", "note", "default_node_by_stage", "never_empty", "pending", "tightening_exceptions",
            "ratchet")
NE_KEYS = ("id", "kind", "carrier", "requirement", "why", "guard")
NE_KINDS = ("scope", "output", "validator")
PENDING_KEYS = ("kind", "carrier", "node", "default", "intent", "inventory")
PENDING_KINDS = ("scope", "output", "tool_field", "conditional")
INTENTS = ("declare", "never_empty")
EXCEPTION_KEYS = ("node", "contract", "field", "condition", "pattern_a", "pattern_b", "count_a", "count_b",
                  "control_a", "control_b")
NODE_RE = re.compile(r"^N[1-8]$")
NE_ID_RE = re.compile(r"^NE[0-9]+$")
GUARD_RE = re.compile(r"^([a-z][a-z0-9_]*\.py)::([A-Za-z_][A-Za-z0-9_]*)$")
LINE_NUMBER = re.compile(r":\d+")
NO_GUARD = "no guard: "
WHY_MIN = 30
# A guard that says "no guard" owes its reason, at the same length as `why`: a bare "n/a" is no statement.
NO_GUARD_WHY_MIN = 30


def load_data(path: Path = DATA) -> tuple:
    """`(data, "")`, or `(None, why)` - an absent, unreadable or malformed file is a reason, never a pass (E8)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, f"{path.name} cannot be read ({exc.__class__.__name__})"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"{path.name} is not valid JSON ({exc})"
    if not isinstance(data, dict):
        return None, f"{path.name} is not an object"
    return data, ""


def stage_ids() -> set:
    """The stage ids of stages.json (a `stage` parameter must name one); empty when the file cannot be read."""
    data, _why = load_data(STAGES)
    return {str(s.get("id")) for s in (data or {}).get("stages") or [] if isinstance(s, dict)}


# ---------------------------------------------------------------------------------------- guard resolution
# Parsing story_run.py (five thousand lines) once per guard would make the detector the slowest test of the
# package; the parse is keyed by the file's own stamp, so an edited file is never read from a stale entry.
_DEFS = {}


def _defs_of(path: Path) -> set | None:
    """Every function or method NAMED in the file, by AST - a name in a comment or a string is not one."""
    stamp = _stamp(path)           # the path, (mtime, size) and the bytes' digest, as for the contracts (C-n2)
    if stamp is None:
        return None
    if stamp not in _DEFS:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            _DEFS[stamp] = None
        else:
            _DEFS[stamp] = {node.name for node in ast.walk(tree)
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return _DEFS[stamp]


def unresolved(ref: str, scripts: Path) -> str:
    """"" when `<file>.py::<function>` names a function defined in `scripts/<file>`, else why it does not.
    Presence only (a same-named method of another class counts - stated, not hidden)."""
    found = GUARD_RE.match(str(ref))
    if not found:
        return f"`{ref}` is not `<scripts file>.py::<function>`"
    name, function = found.groups()
    names = _defs_of(scripts / name)
    if names is None:
        return f"`{name}` cannot be read in scripts/"
    return "" if function in names else f"no function `{function}` is defined in scripts/{name}"


# ----------------------------------------------------------------------------------- one declaration's shape
def _kind_problem(kind: str, value, spec: dict, sections: dict, stage_ids) -> str:
    """"" when `value` is a good value of the parameter kind, else what is wrong with it."""
    if kind == "list_section":
        if isinstance(value, str) and sections.get(value) == "list":
            return ""
        return f"{value!r} names no list section of the contract"
    if kind == "field_path":
        return "" if isinstance(value, str) and value in spec else f"{value!r} is no field of the contract"
    if kind == "words":
        ok = isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value)
        return "" if ok else f"{value!r} is not a non-empty list of words"
    if kind == "word":
        return "" if isinstance(value, str) and value.strip() else f"{value!r} is not a word"
    if kind == "stage":
        return "" if isinstance(value, str) and value in stage_ids else f"{value!r} is no stage of stages.json"
    if kind == "kind":
        return "" if value in STAGE_KINDS else f"{value!r} is not one of {', '.join(STAGE_KINDS)}"
    return f"parameter kind `{kind}` is not one of {', '.join(PARAM_KINDS)}"


def entry_problems(section: str, entry, *, spec: dict, sections: dict, stage_ids=()) -> list:
    """What is wrong with ONE declaration (`null_outcome.<section>`), as sentences; [] when it is well formed.

    PURE: the contract is given as its `spec` ({path: FieldSpec}) and `sections` ({name: kind}), so a synthetic
    contract text parsed with `handoff.parse` can be judged without a file. The runtime reads the same sentences:
    a declaration with any problem is not applied (fail closed), and the detector prints them."""
    if section not in handoff.REQUIRED_LISTS:
        return [f"`{section}` is not a list of handoff.REQUIRED_LISTS ({', '.join(handoff.REQUIRED_LISTS)}); a "
                "declaration under any other key arrives with N1 - it must never sit in data with no reader behind it"]
    if sections.get(section) != "list":
        return [f"`{section}` is not a list section of the contract"]
    if not isinstance(entry, dict):
        return [f"`{section}` is not a map of condition, params, words and source"]
    out = []
    for key in entry:
        if key not in handoff.NULL_ENTRY_KEYS:
            out.append(f"`{key}` belongs to node N1 and is refused in N0" if key in ("joint", "only_when")
                       else f"unknown key `{key}` (a declaration holds {', '.join(handoff.NULL_ENTRY_KEYS)})")
    name = entry.get("condition")
    if not isinstance(name, str) or not name.strip():
        return out + [f"`{section}` has no `condition`"]
    condition = CONDITIONS.get(name)
    if condition is None:
        return out + [f"unknown condition `{name}` (registered: {', '.join(CONDITIONS)})"]
    if condition.status != "live":
        return out + [f"condition `{name}` is reserved for node {condition.node}; no implementation yet"]
    params = entry.get("params", {})
    if not isinstance(params, dict):
        out.append("`params` is not a map")
        params = {}
    for pname, kind in condition.params.items():
        if pname not in params:
            out.append(f"missing param `{pname}` of condition `{name}`")
        else:
            why = _kind_problem(kind, params[pname], spec, sections, stage_ids)
            if why:
                out.append(f"param `{pname}`: {why}")
    for pname in params:
        if pname not in condition.params:
            out.append(f"unknown param `{pname}` of condition `{name}` (it takes {', '.join(condition.params) or 'none'})")
    if name == "triage_has_no_repair":
        field = spec.get(f"{section}[].state")
        verdicts = params.get("repair_verdicts")
        if field is not None and isinstance(verdicts, list) and verdicts:
            stray = [str(v) for v in verdicts if str(v) not in field.options]
            if stray:
                out.append(f"param `repair_verdicts` names {', '.join(stray)}, which `{section}[].state` does not "
                           f"offer (it offers {', '.join(field.options) or 'nothing'})")
    words = entry.get("words", {})
    if not isinstance(words, dict):
        out.append("`words` is not a map")
        words = {}
    for path, said in words.items():
        if path not in spec:
            out.append(f"`words` names `{path}`, which is no field of the contract")
        if not isinstance(said, dict) or set(said) != {"word", "means"} \
                or not all(isinstance(said[k], str) and said[k].strip() for k in ("word", "means")):
            out.append(f"`words.{path}` is not a `word` and a `means`, both text")
    if "source" in entry and entry["source"] != condition.source:
        out.append(f"`source` is {entry['source']!r}, and condition `{name}` reads {condition.source!r}")
    return out


# ------------------------------------------------------------------------------------------ the data's rows
def _keys_problems(label: str, row, allowed: tuple) -> list:
    if not isinstance(row, dict):
        return [f"{label} is not an object"]
    out = [f"{label} has an unknown key `{k}`" for k in row if k not in allowed]
    out += [f"{label} lacks `{k}`" for k in allowed if k not in row]
    return out


def _data_shape_problems(data: dict) -> list:
    """The file's own shape is closed: an unknown key at any level is red, by name (E8)."""
    out = [f"null-outcomes.json has an unknown key `{k}`" for k in data if k not in TOP_KEYS]
    out += [f"null-outcomes.json lacks `{k}`" for k in TOP_KEYS if k not in data]
    if data.get("schema_version") != 1:
        out.append(f"null-outcomes.json schema_version is {data.get('schema_version')!r}, this reader reads 1")
    if not isinstance(data.get("default_node_by_stage"), dict):
        out.append("null-outcomes.json `default_node_by_stage` is not an object")
    for key in ("never_empty", "pending", "tightening_exceptions", "ratchet"):
        if key in data and not isinstance(data[key], list):
            out.append(f"null-outcomes.json `{key}` is not a list")
    return out


def _never_empty_problems(rows: list, scripts: Path) -> list:
    out, seen = [], set()
    for i, row in enumerate(rows):
        label = f"never_empty[{i}]" + (f" ({row.get('id')})" if isinstance(row, dict) and row.get("id") else "")
        shape = _keys_problems(label, row, NE_KEYS)
        out += shape
        if shape:
            continue
        ident = row["id"]
        if not isinstance(ident, str) or not NE_ID_RE.match(ident):
            out.append(f"{label}: id {ident!r} is not NE<number>")
        elif ident in seen:
            out.append(f"{label}: duplicate id {ident}")
        seen.add(ident)
        if row["kind"] not in NE_KINDS:
            out.append(f"{label}: kind {row['kind']!r} is not one of {', '.join(NE_KINDS)}")
        for key in ("carrier", "requirement"):
            if not isinstance(row[key], str) or not row[key].strip():
                out.append(f"{label}: `{key}` is empty")
        if not isinstance(row["why"], str) or len(row["why"].strip()) < WHY_MIN:
            out.append(f"{label}: `why` is shorter than {WHY_MIN} characters - say why the item is never empty")
        guard = row["guard"]
        if not isinstance(guard, str):
            out.append(f"{label}: `guard` is not text")
        elif LINE_NUMBER.search(guard):
            out.append(f"{label}: guard `{guard}` holds a line number; name the function (line numbers drift)")
        elif guard.startswith(NO_GUARD):
            if len(guard[len(NO_GUARD):].strip()) < NO_GUARD_WHY_MIN:
                out.append(f"{label}: `no guard:` owes its reason, at least {NO_GUARD_WHY_MIN} characters")
        else:
            why = unresolved(guard, scripts)
            if why:
                out.append(f"{label}: guard {why}")
    return out


def _pending_problems(rows: list, defaults: dict, stage_of_carrier) -> list:
    out = []
    for i, row in enumerate(rows):
        label = f"pending[{i}]" + (f" ({row.get('carrier')})" if isinstance(row, dict) and row.get("carrier") else "")
        shape = _keys_problems(label, row, PENDING_KEYS)
        out += shape
        if shape:
            continue
        if row["kind"] not in PENDING_KINDS:
            out.append(f"{label}: kind {row['kind']!r} is not one of {', '.join(PENDING_KINDS)}")
        if not isinstance(row["carrier"], str) or not row["carrier"].strip():
            out.append(f"{label}: `carrier` is empty")
        if not isinstance(row["node"], str) or not NODE_RE.match(row["node"]):
            out.append(f"{label}: node {row['node']!r} is not one of N1..N8 - a pending item arrives at a NAMED node")
        if not isinstance(row["default"], bool):
            out.append(f"{label}: `default` is not true or false")
        if row["intent"] not in INTENTS:
            out.append(f"{label}: intent {row['intent']!r} is not one of {', '.join(INTENTS)}")
        if not isinstance(row["inventory"], str):
            out.append(f"{label}: `inventory` is not text")
        if row["default"] is True:
            if row["kind"] == "conditional":
                out.append(f"{label}: a conditional field is named by the inventory, never by the default rule")
                continue
            stage = stage_of_carrier(row["kind"], str(row["carrier"]))
            want = defaults.get(stage) if isinstance(defaults, dict) else None
            if not want:
                out.append(f"{label}: no default node for stage {stage!r} in default_node_by_stage")
            elif row["node"] != want:
                out.append(f"{label}: the default rule puts stage {stage} at {want}, the row says {row['node']}")
    return out


def _ratchet_problems(rows: list, count: int, *, key: str = "pending", node_re: str = r"^N[0-8]$",
                      node_words: str = "one of N0..N8", rise: str = "a new required item is declared or given a "
                      "never_empty row in the commit that adds it", noun: str = "pending",
                      unit: str = "rows", drift: str = "a row added without a declaration, or removed without "
                      "lowering the ratchet") -> list:
    """A count only shrinks: the history never rises, and the last entry is the real count (E6).

    The defaults are the pending ratchet of this file. A second shrink-only ratchet (`stage_joints`: the declared gaps)
    reads the SAME function with its own key, node pattern and words (AR-15, AR-20) - one ratchet checker, not a clone."""
    keys = ("node", key)
    out, history = [], []
    for i, row in enumerate(rows):
        shape = _keys_problems(f"ratchet[{i}]", row, keys)
        out += shape
        if shape:
            continue
        if not isinstance(row["node"], str) or not re.match(node_re, row["node"]):
            out.append(f"ratchet[{i}]: node {row['node']!r} is not {node_words}")
        if not isinstance(row[key], int) or isinstance(row[key], bool) or row[key] < 0:
            out.append(f"ratchet[{i}]: `{key}` is not a count")
        else:
            history.append(row[key])
    if not rows:
        out.append(f"ratchet is empty: the history of the {noun} count is the detector's memory")
    for before, after in zip(history, history[1:]):
        if after > before:
            out.append(f"ratchet rises from {before} to {after}: {noun} only shrinks, {rise}")
    if history and history[-1] != count:
        out.append(f"{noun} has {count} {unit} and the ratchet's last entry says {history[-1]}: {drift}")
    return out


ratchet_problems = _ratchet_problems            # the public name for the second reader (stage_joints)


# --------------------------------------------------------------------------------------------- the detector
class Report:
    """What `audit` found: `problems` (sentences, [] = green) and `counts` for the summary line."""

    def __init__(self):
        self.problems = []
        self.counts = {"scope": 0, "other": 0, "outputs": 0, "tool_fields": 0, "conditional": 0, "declared": 0,
                       "never_empty": 0, "validator": 0, "pending": 0, "default": 0, "reserved_declared": 0}

    @property
    def ok(self) -> bool:
        return not self.problems

    def line(self) -> str:
        c = self.counts
        return (f"null outcomes: walked scope {c['scope']}, outputs {c['outputs']}, tool fields {c['tool_fields']}, "
                f"conditional {c['conditional']} | declared {c['declared']}, never_empty {c['never_empty']} "
                f"(+{c['validator']} validator), pending {c['pending']} of which by default {c['default']}")


def audit(*, index=None, stages=None, fields=None, data=None, raw=None, reader=None, spec_of=None,
          sections_of=None, scripts=None, pins=None) -> Report:
    """Walk what the factory requires and say what has no home. Everything is injectable so a negative control
    can feed a stub; the defaults are the real package.

    index      the `handoffs:` rows of index.yaml;        stages   the parsed stages.json
    fields     `tool_fields()` rows;                      data     the parsed null-outcomes.json (a str = why not)
    raw        contract -> its raw `null_outcome` block;  reader   contract -> `{section: entry}`
    spec_of / sections_of   contract -> spec / sections;  scripts  the directory the guards resolve in
    pins       the walk sizes the caller expects (scope, other, outputs, tool_fields, conditional, validator,
               registry); a size that differs is red, in BOTH directions."""
    report = Report()
    problems = report.problems
    red = problems.append
    index = (handoff.index().get("handoffs") or []) if index is None else index
    spec_of = spec_of or cached_spec
    sections_of = sections_of or cached_sections
    raw = raw or cached_raw
    reader = reader or cached_reader
    scripts = scripts or HERE
    pins = pins or {}
    if stages is None:
        stages_data, why = load_data(STAGES)
        if stages_data is None:
            red(why)
            stages_data = {}
    else:
        stages_data = stages
    stage_rows = [s for s in stages_data.get("stages") or [] if isinstance(s, dict)]
    stage_ids = {str(s.get("id")) for s in stage_rows}
    gate_ids = {str(g) for g in (stages_data.get("gates") or {})}
    if isinstance(data, str):
        red(data)
        data = None
    elif data is None:
        data, why = load_data()
        if data is None:
            red(why)
    if data is None:
        return report
    shape = _data_shape_problems(data)
    problems.extend(shape)
    if shape:
        return report
    never_empty = data["never_empty"]
    pending = data["pending"]
    defaults = data["default_node_by_stage"]

    def pin(label: str, got: int, key: str) -> None:
        if key in pins and got != pins[key]:
            red(f"{label}: {got}, pinned {pins[key]}")

    # ---- the registry itself
    for name, condition in CONDITIONS.items():
        if condition.status == "live":
            if not condition.impl:
                red(f"condition `{name}` is live and names no impl")
            else:
                why = unresolved(condition.impl, scripts)
                if why:
                    red(f"condition `{name}` impl: {why}")
        elif condition.impl:
            red(f"condition `{name}` is reserved and still names an impl")
        for pname, kind in condition.params.items():
            if kind not in PARAM_KINDS:
                red(f"condition `{name}` param `{pname}` has the kind `{kind}`, not one of {', '.join(PARAM_KINDS)}")
    pin("registered conditions", len(CONDITIONS), "registry")

    # ---- W1 / W1b: the index rows
    walked = {"scope": [], "output": [], "tool_field": []}
    stage_of, contracts, others = {}, [], []
    for row in index:
        contract = str(row.get("contract") or "")
        kind = str(row.get("kind") or "")
        stage_of[contract] = str(row.get("stage") or row.get("gate") or "")
        try:
            sections = sections_of(contract)
        except FileNotFoundError:
            red(f"{contract}: the index row names a contract with no file")
            continue
        contracts.append(contract)
        lists = [n for n in handoff.REQUIRED_LISTS if sections.get(n) == "list"]
        not_lists = [n for n in handoff.REQUIRED_LISTS if n in sections and sections[n] != "list"]
        for name in not_lists:
            red(f"{contract}: `{name}` is a {sections[name]}, and a required item list is a list")
        if kind in SCOPE_KINDS:
            if not lists and not not_lists:
                red(f"{contract}: kind {kind} carries an item list, and the contract has no "
                    f"{'/'.join(handoff.REQUIRED_LISTS)}")
            walked["scope"] += [f"{contract}:{n}" for n in lists]
        elif kind in NO_SCOPE_KINDS:
            if lists or not_lists:
                red(f"{contract}: kind {kind} has no item list, and the contract carries `{(lists + not_lists)[0]}`")
            else:
                others.append(contract)
        else:
            red(f"{contract}: kind {kind!r} is not one of {', '.join(SCOPE_KINDS + NO_SCOPE_KINDS)}")
    pin("scope contracts", len(walked["scope"]), "scope")
    pin("contracts with no item list", len(others), "other")

    # ---- W2: stage outputs.  W3: tool fields
    for stage in stage_rows:
        for out in stage.get("required_outputs") or []:
            walked["output"].append(f"{stage.get('id')}:{out}")
    pin("required outputs", len(walked["output"]), "outputs")
    if fields is None:
        fields = tool_fields(index, spec_of)
    walked["tool_field"] = [f"{contract}:{path}" for contract, _role, path, _hint in fields]
    pin("tool fields", len(walked["tool_field"]), "tool_fields")
    for kind, items in walked.items():
        for carrier in {c for c in items if items.count(c) > 1}:
            red(f"the walk meets {carrier} twice ({kind})")

    # ---- the declarations (raw, for the shape; the reader, for the homes)
    stage_vocab = stage_ids
    for contract in contracts:
        block = raw(contract)
        if block is None:
            continue
        if not isinstance(block, dict) or not block:
            red(f"{contract}: `null_outcome` declares nothing - an empty block never loosens, and a half-edit must "
                "not pass; remove it or declare")
            continue
        if isinstance(block.get("section"), str):
            if any(key not in handoff.LEGACY_NULL_KEYS for key in block):
                red(f"{contract}: `null_outcome` mixes the legacy `section:` shape with keyed entries - malformed")
            else:
                red(f"{contract}: `null_outcome` is in the legacy shape (section/repair_verdicts/listed_in/window): "
                    "convert to the keyed shape (`<section>: {condition, params, words, source}`)")
            continue
        spec, sections = spec_of(contract), sections_of(contract)
        for section, entry in block.items():
            for sentence in entry_problems(section, entry, spec=spec, sections=sections, stage_ids=stage_vocab):
                red(f"{contract}: null_outcome.{section}: {sentence}")
            if isinstance(entry, dict) and CONDITIONS.get(entry.get("condition")) is not None \
                    and CONDITIONS[entry["condition"]].status != "live":
                report.counts["reserved_declared"] += 1
    declared = set()
    for contract in contracts:
        for section in reader(contract):
            declared.add(f"{contract}:{section}")
    every_walked = {c for items in walked.values() for c in items}
    for carrier in sorted(declared - every_walked):
        red(f"{carrier} declares a null outcome the walk does not meet")

    # ---- the rows: shape
    def stage_of_carrier(kind: str, carrier: str) -> str:
        head = carrier.split(":", 1)[0]
        return head if kind == "output" else stage_of.get(head, "")

    problems.extend(_never_empty_problems(never_empty, scripts))
    problems.extend(_pending_problems(pending, defaults, stage_of_carrier))
    problems.extend(_ratchet_problems(data["ratchet"], len(pending)))
    if isinstance(defaults, dict):
        known = stage_ids | gate_ids
        for key in sorted(known - set(defaults)):
            red(f"default_node_by_stage has no node for `{key}`")
        for key, node in defaults.items():
            if key not in known:
                red(f"default_node_by_stage names `{key}`, which is no stage or gate")
            if not isinstance(node, str) or not NODE_RE.match(node):
                red(f"default_node_by_stage: `{key}` -> {node!r} is not one of N1..N8")

    # ---- homes: one for each walked item
    rows = [r for r in never_empty if isinstance(r, dict)]
    waiting = [r for r in pending if isinstance(r, dict)]
    for kind, items in walked.items():
        for carrier in items:
            homes = []
            if carrier in declared:
                homes.append("declared")
            homes += [f"never_empty {r.get('id')}" for r in rows if r.get("kind") == kind and r.get("carrier") == carrier]
            homes += [f"pending at {r.get('node')}" for r in waiting if r.get("kind") == kind and r.get("carrier") == carrier]
            if not homes:
                red(f"{carrier} has no home: declare its null outcome in the contract, or give it a never_empty "
                    "row with its guard (the pending list is closed by the ratchet - a new item cannot be born pending)")
            elif len(homes) > 1:
                red(f"{carrier} has two homes ({', '.join(homes)}): one of them is stale")
    # ---- stale rows: a row whose carrier the walk does not meet
    for r in rows:
        if r.get("kind") in ("scope", "output") and r.get("carrier") not in set(walked[r["kind"]]):
            red(f"never_empty {r.get('id')}: stale row - the walk meets no {r['kind']} `{r.get('carrier')}`")
    for r in waiting:
        kind = r.get("kind")
        if kind in walked and r.get("carrier") not in set(walked[kind]):
            red(f"pending {r.get('carrier')}: stale row - the walk meets no {kind} by that name")
        elif kind == "conditional":
            contract, _, path = str(r.get("carrier") or "").partition(":")
            try:
                known_paths = spec_of(contract)
            except FileNotFoundError:
                red(f"pending {r.get('carrier')}: stale row - no contract `{contract}`")
                continue
            if path not in known_paths:
                red(f"pending {r.get('carrier')}: stale row - `{contract}` has no field `{path}`")

    # ---- the F1 exceptions
    for i, row in enumerate(data["tightening_exceptions"]):
        label = f"tightening_exceptions[{i}]"
        shape = _keys_problems(label, row, EXCEPTION_KEYS)
        problems.extend(shape)
        if shape:
            continue
        if not isinstance(row["node"], str) or not NODE_RE.match(row["node"]):
            red(f"{label}: node {row['node']!r} is not one of N1..N8")
        if row["condition"] not in CONDITIONS:
            red(f"{label}: condition `{row['condition']}` is not registered")
        try:
            if row["field"] not in spec_of(str(row["contract"])):
                red(f"{label}: `{row['contract']}` has no field `{row['field']}`")
        except FileNotFoundError:
            red(f"{label}: no contract `{row['contract']}`")
        for key in ("count_a", "count_b", "control_a", "control_b"):
            if not isinstance(row[key], int) or isinstance(row[key], bool) or row[key] < 0:
                red(f"{label}: `{key}` is not a count")
        for key in ("pattern_a", "pattern_b"):
            if not isinstance(row[key], str) or not row[key].strip():
                red(f"{label}: `{key}` is empty")

    # ---- counts, the pins that need the rows, the summary
    conditional = [r for r in waiting if r.get("kind") == "conditional"]
    validators = [r for r in rows if r.get("kind") == "validator"]
    pin("conditional fields", len(conditional), "conditional")
    pin("validator rows", len(validators), "validator")
    counts = report.counts
    counts.update({"scope": len(walked["scope"]), "other": len(others), "outputs": len(walked["output"]),
                   "tool_fields": len(walked["tool_field"]), "conditional": len(conditional),
                   "declared": len(declared & every_walked), "validator": len(validators),
                   "never_empty": len(rows) - len(validators), "pending": len(pending),
                   "default": len([r for r in waiting if r.get("default") is True])})
    return report
