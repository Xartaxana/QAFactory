#!/usr/bin/env python3
"""The stage joints: every check the factory makes of a role is produced by something and told to the role (F6-51, FR-5, FR-38).

Run 12586 had 17 `gate_block` "digest: your final message is not the handoff form" and S5 quality receipts nobody
wrote. Both are one class: a gate demanded something of a role that nothing produced, or that the role was never told.
`references/stage-joints.json` is the census of those joints and this module is its reader and its walker. Three
directions, all red when they fail (AR-28: an unreadable input is never green):

  A  code -> registry   every check the walk meets in code has exactly one row. The universe is computed from the
                        package, never copied: the error families `exit_gate.all_errors`/`main` collect (AST), the
                        detectors of `stages.json` (read through `stage_guard.stage_model`, advisers excluded) and
                        the gap kinds `acceptance.validate_window` appends (AST).
  B  registry -> code   every producer entry names a role that exists (`agents/<role>.md`) or a function that is
                        defined (`null_outcomes.unresolved`); every `told` path exists and holds its anchor, and the
                        role RECEIVES it (its agent file, or the file the injection map delivers to it).
  C  demand -> told     every token an entry demands of a role is named in a file that role is told. Tokens come from
                        the existing tables through their readers (`demands_from`), never from a hand-made copy.

A leg that honestly does not exist today is a declared `gap` (ref + reason) under a shrink-only ratchet
(`ratchet[]`, checked by `null_outcomes.ratchet_problems`): an informed pass of the walk, counted, never silent (FR-4).
`told` and `demands` are PER ROLE: an entry lists the roles it speaks for, a `<role>` in a path is expanded for each,
and each role is judged on its own files. A `code:` producer is "told" where it is CALLED on the factory's path.

The walker is a measurer (FR-28) and a validator, so it writes nothing (FR-45): `audit()` is pure over what it is
given and the real tree is its default. Heavy imports (`null_outcomes`, `stage_guard`, `inject_context`,
`validate_artifacts`, `acceptance`) are taken inside the functions: the retro reads `threshold()` and must not import
the walker's graph.

CLI: `python -B scripts/stage_joints.py --check [--data <file>]` - exit 0 clean, 1 problems (the detector shape
`REJECT — N finding(s)`), 3 when the data file cannot be read (`detector_verdict.EXIT_UNREADABLE`, the `UNREADABLE:`
line; AR-18), 2 for a usage error (`--data` with no file).
"""
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))

DATA = PLUGIN / "references" / "stage-joints.json"
KEY = "same_class_gate_blocks"
FRICTION_MIN = 2
TOP_KEYS = ("schema_version", "note", "friction", "joints", "ratchet")
ROW_KEYS = ("check", "stages", "producers", "joint")
ENTRY_KEYS = ("roles", "code", "field", "told", "demands", "demands_from", "gap", "role_leg")
ENTRY_REQUIRED = ("field", "told")
TOLD_KEYS = ("path", "anchor")
GAP_KEYS = ("leg", "ref", "why")
LEGS = ("producer", "told", "demands")
CARRIERS = ("stages.json:required_outputs", "stages.json:witness", "stages.json:detectors",
            "validate_artifacts.PHASE_JSON_KEYS", "check:script")
GAP_REF = re.compile(r"^(B-\d+|F6-51/\d+)$")
GAP_WHY_MIN = 30
NOTE_MIN = 40
FIELD_MIN = 3
RATCHET_NODE = r"^F6-51$"
EXIT_SKIP = ("list", "all_errors")                  # the aggregator and a copy of the list are not families
EXIT_FUNCTIONS = ("all_errors", "main")
USAGE_EXIT = 2                                      # `--data` with no file; the unreadable file is the contract's exit 3
ROLE_LEG_KEY = "role_leg"                           # a code row whose role leg the walk does not judge says so in data
ROLE_LEG_NOT_WALKED = "not walked"


# ------------------------------------------------------------------------------------------- the universe
def _leaves(node) -> list:
    """The leaves of a `+` chain at any depth."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _leaves(node.left) + _leaves(node.right)
    return [node]


def exit_members(src: str, filename: str = "exit_gate.py") -> tuple:
    """`({key: where}, [walk errors])`: the families collected into `errors` by `all_errors` and `main`.

    Every `errors = ...` / `errors += ...` in those two bodies (nested statements included: `ast.walk`) has its value
    split at `+`; a leaf that is a call of a bare name is a family (the aggregator and `list` are not). A call of
    anything else (an attribute, a subscript) is a shape the walk cannot name: a walk error, never skipped (E6). A leaf
    that is no call (a name, a comprehension) is neither a member nor an error."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {}, [f"cannot read the check at {filename}:{exc.lineno} - not Python ({exc.msg})"]
    members, errors = {}, []
    found = {fn.name for fn in tree.body if isinstance(fn, ast.FunctionDef)}
    for name in EXIT_FUNCTIONS:
        if name not in found:
            errors.append(f"cannot read the check at {filename}: no function `{name}`; extend the walk or restore it")
    for fn in (f for f in tree.body if isinstance(f, ast.FunctionDef) and f.name in EXIT_FUNCTIONS):
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AugAssign):
                targets, value = [node.target], node.value
            else:
                continue
            if not any(isinstance(t, ast.Name) and t.id == "errors" for t in targets):
                continue
            for leaf in _leaves(value):
                if not isinstance(leaf, ast.Call):
                    continue
                if isinstance(leaf.func, ast.Name):
                    if leaf.func.id not in EXIT_SKIP:
                        members.setdefault(f"exit:{leaf.func.id}", f"{filename}::{fn.name}:{leaf.lineno}")
                else:
                    errors.append(f"cannot read the check at {filename}:{leaf.lineno} - a call of a "
                                  f"{type(leaf.func).__name__} in `errors`; extend the walk or simplify the call")
    return members, errors


def detector_members(model: dict, filename: str = "stages.json") -> dict:
    """`{key: where}` for the blocking detectors of the stage model (the advisers - `advice` - never block)."""
    out = {}
    for stage in model.get("stages") or []:
        advisers = {str(s) for s in stage.get("advice") or []}
        for role, scripts in (stage.get("detectors") or {}).items():
            for script in scripts or []:
                if str(script) not in advisers:
                    out.setdefault(f"detector:{stage.get('id')}:{role}:{script}", f"{filename} {stage.get('id')}")
    return out


def _leftmost(node):
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        node = node.left
    return node


def _kinds(leaf, names: dict):
    """The kinds a gap's leading leaf stands for (text before the first `:`), or None when the shape is unreadable."""
    if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
        return [leaf.value.split(":", 1)[0]]
    if isinstance(leaf, ast.Name):
        value = names.get(leaf.id)
        return [value.split(":", 1)[0]] if isinstance(value, str) else None
    if isinstance(leaf, ast.IfExp):
        left, right = _kinds(_leftmost(leaf.body), names), _kinds(_leftmost(leaf.orelse), names)
        return left + right if left is not None and right is not None else None
    return None


def window_members(src: str, names: dict, filename: str = "acceptance.py") -> tuple:
    """`({key: where}, [walk errors])`: the gap kinds `validate_window` appends. A `gaps.append(X)` stands for the kind of
    the leftmost leaf of X (a constant, a module name resolved through `names`, or both branches of a conditional);
    a `gaps.extend(<expr>)` stands for `window:<f>` for each call of a bare name `f` inside it. Any other shape is a
    walk error (E6). Many sites of one kind are one member."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {}, [f"cannot read the check at {filename}:{exc.lineno} - not Python ({exc.msg})"]
    fn = next((f for f in tree.body if isinstance(f, ast.FunctionDef) and f.name == "validate_window"), None)
    if fn is None:
        return {}, [f"cannot read the check at {filename}: no function `validate_window`; extend the walk or restore it"]
    members, errors = {}, []
    for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
        func = call.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "gaps"
                and func.attr in ("append", "extend")):
            continue
        where = f"{filename}::validate_window:{call.lineno}"
        arg = call.args[0] if len(call.args) == 1 else None
        if arg is None:
            errors.append(f"cannot read the check at {filename}:{call.lineno} - gaps.{func.attr} with "
                          f"{len(call.args)} arguments; extend the walk or simplify the call")
        elif func.attr == "append":
            kinds = _kinds(_leftmost(arg), names)
            if kinds is None:
                errors.append(f"cannot read the check at {filename}:{call.lineno} - the leading part of the gap is "
                              f"a {type(_leftmost(arg)).__name__}, not a text, a module text or a conditional of two; "
                              "extend the walk or simplify the call")
            for kind in kinds or []:
                members.setdefault(f"window:{kind}", where)
        else:
            called = [n.func.id for n in ast.walk(arg) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
            if not called:
                errors.append(f"cannot read the check at {filename}:{call.lineno} - gaps.extend of an expression "
                              "with no call of a named function; extend the walk or simplify the call")
            for name in called:
                members.setdefault(f"window:{name}", where)
    return members, errors


def acceptance_names() -> dict:
    """The module-level texts of `acceptance` (the names a gap may start with); read at the call (lazy import)."""
    import acceptance
    return {k: v for k, v in vars(acceptance).items() if isinstance(v, str)}


def universe(exit_src=None, stages=None, acceptance_src=None, names=None) -> tuple:
    """`({key: where}, [walk errors])` of the three kinds. Every argument has the real default."""
    if exit_src is None:
        exit_src = (HERE / "exit_gate.py").read_text(encoding="utf-8")
    if stages is None:
        import stage_guard
        stages = stage_guard.stage_model()
    if acceptance_src is None:
        acceptance_src = (HERE / "acceptance.py").read_text(encoding="utf-8")
    if names is None:
        names = acceptance_names()
    keys, errors = exit_members(exit_src)
    w_keys, w_errors = window_members(acceptance_src, names)
    out = dict(keys)
    out.update(detector_members(stages))
    out.update(w_keys)
    return out, errors + w_errors


# --------------------------------------------------------------------------------------------- the world
class Env:
    """What the walk reads besides the data: the stage model, the injection map, the tables a demand is read from."""

    def __init__(self, *, model, load_map, phase_keys, phase_writers, stage_of_role, plugin=PLUGIN, scripts=HERE):
        self.model, self.load_map = model, load_map
        self.phase_keys, self.phase_writers = phase_keys, phase_writers
        self.stage_of_role = stage_of_role
        self.plugin, self.scripts = Path(plugin), Path(scripts)
        self._texts, self._trees = {}, {}

    @classmethod
    def real(cls):
        import inject_context
        import stage_guard
        import validate_artifacts
        return cls(model=stage_guard.stage_model(), load_map=inject_context.load_map(),
                   phase_keys=validate_artifacts.PHASE_JSON_KEYS, phase_writers=validate_artifacts.PHASE_JSON_WRITERS,
                   stage_of_role=stage_guard.stage_of_role)

    def text(self, rel: str):
        """The text of a package file, or None when it cannot be read."""
        if rel not in self._texts:
            try:
                self._texts[rel] = (self.plugin / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._texts[rel] = None
        return self._texts[rel]

    def calls(self, rel: str, function: str):
        """Line numbers of the CALLS of `function` in a package script, outside the function's own body; None when the
        file cannot be parsed. A name in a comment, a docstring or a string is no call (an AST walk)."""
        if rel not in self._trees:
            text = self.text(rel)
            try:
                self._trees[rel] = ast.parse(text) if text is not None else None
            except (SyntaxError, ValueError):
                self._trees[rel] = None
        tree = self._trees[rel]
        if tree is None:
            return None
        spans = [(n.lineno, n.end_lineno) for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function]
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if called == function and not any(a <= node.lineno <= b for a, b in spans):
                hits.append(node.lineno)
        return hits

    def reaches(self, role: str, rel: str) -> bool:
        """True when `role` RECEIVES `rel`: its own agent file, or a file the injection map delivers to it."""
        if rel == f"agents/{role}.md":
            return True
        listed = list(self.load_map.get("common") or []) + list((self.load_map.get("roles") or {}).get(role) or [])
        return f"plugin:{rel}" in listed

    def role_exists(self, role: str) -> bool:
        return (self.plugin / "agents" / f"{role}.md").is_file()


def _base(artifact) -> str:
    text = str(artifact)
    return Path(text[len("project:"):] if text.startswith("project:") else text).name


def demand_tokens(carrier, role: str, check: str, env: Env) -> tuple:
    """`(tokens, why)`: what a carrier says the gate demands of `role`, read through the existing table (B-2)."""
    if carrier == "check:script":
        return [check.rsplit(":", 1)[-1]], ""
    if carrier == "stages.json:witness":
        found = (env.model.get("witness") or {}).get(role)
        return ([_base(found)] if found else []), ""
    stage = env.stage_of_role(env.model, role)
    if carrier == "validate_artifacts.PHASE_JSON_KEYS":
        tokens = []
        for artifact, writer in env.phase_writers.items():
            if str(writer).removesuffix(".md") == role:
                tokens += list(env.phase_keys.get(artifact) or [])
        return tokens, ""
    if stage is None:
        return [], f"{role} is in no stage of stages.json"
    if carrier == "stages.json:required_outputs":
        return [_base(o) for o in stage.get("required_outputs") or []], ""
    if carrier == "stages.json:detectors":
        advisers = {str(s) for s in stage.get("advice") or []}
        return [s for s in (stage.get("detectors") or {}).get(role) or [] if s not in advisers], ""
    return [], f"unknown carrier {carrier!r}"


# ------------------------------------------------------------------------------------- the data's shape
def _shape_problems(data: dict) -> list:
    out = [f"stage-joints.json has an unknown key `{k}`" for k in data if k not in TOP_KEYS]
    out += [f"stage-joints.json lacks `{k}`" for k in TOP_KEYS if k not in data]
    if data.get("schema_version") != 1:
        out.append(f"stage-joints.json schema_version is {data.get('schema_version')!r}, this reader reads 1")
    if not isinstance(data.get("note"), str) or len(data.get("note").strip()) < NOTE_MIN:
        out.append(f"stage-joints.json `note` is shorter than {NOTE_MIN} characters - say what the file is")
    friction = data.get("friction")
    if not isinstance(friction, dict) or set(friction) != {KEY}:
        out.append(f"stage-joints.json `friction` is not an object holding exactly `{KEY}`")
    elif not _is_count(friction[KEY], FRICTION_MIN):
        out.append(f"stage-joints.json friction.{KEY} is {friction[KEY]!r}, an integer of at least {FRICTION_MIN} "
                   "is expected (one block of one class is the norm of MAX_BLOCKS, a repeat is the signal)")
    for key in ("joints", "ratchet"):
        if key in data and not isinstance(data[key], list):
            out.append(f"stage-joints.json `{key}` is not a list")
    if isinstance(data.get("joints"), list) and not data["joints"]:
        out.append("stage-joints.json has no joint rows (`joints` is empty): a lost file is not a state - the walk "
                   "meets checks in code")
    return out


def _is_count(value, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _gap_problems(label: str, gap) -> list:
    if gap is None:
        return []
    if not isinstance(gap, dict) or set(gap) != set(GAP_KEYS):
        return [f"stage-joints: {label}: `gap` is null or an object of exactly {', '.join(GAP_KEYS)}"]
    out = []
    if gap["leg"] not in LEGS:
        out.append(f"stage-joints: {label}: gap leg {gap['leg']!r} is not one of {', '.join(LEGS)}")
    if not isinstance(gap["ref"], str) or not GAP_REF.match(gap["ref"]):
        out.append(f"stage-joints: {label}: gap ref {gap['ref']!r} is not `B-<n>` or `F6-51/<n>` - a gap points at the "
                   "item that closes it")
    if not isinstance(gap["why"], str) or len(gap["why"].strip()) < GAP_WHY_MIN:
        out.append(f"stage-joints: {label}: gap `why` is shorter than {GAP_WHY_MIN} characters - say why the leg is missing")
    return out


# ---------------------------------------------------------------------------------- one producer entry
def _producer_leg(entry: dict, env: Env) -> list:
    """What is wrong with the producer leg of one entry: [] when it names an existing role or a defined function."""
    roles, code = entry.get("roles"), entry.get("code")
    if (roles in (None, [])) and not code:
        return ["the producer leg is missing"]
    if roles and code:
        return ["`roles` and `code` are both given: an entry is a role's or a function's"]
    if roles:
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            return ["`roles` is not a list of role names"]
        return [f"role `{r}` has no agents/{r}.md" for r in roles if not env.role_exists(r)]
    import null_outcomes
    why = null_outcomes.unresolved(str(code), env.scripts)
    return [f"`code` {why}"] if why else []


def _expand(rel: str, role: str) -> str:
    return rel.replace("<role>", role)


def _told_leg(entry: dict, env: Env) -> list:
    """What is wrong with the told leg. An empty `told` is its own sentence, so a gap can name it."""
    told = entry.get("told")
    if not isinstance(told, list):
        return ["`told` is not a list"]
    if not told:
        return ["the told leg is missing"]
    out = []
    for item in told:
        if not isinstance(item, dict) or not set(item) <= set(TOLD_KEYS) or "path" not in item:
            out.append(f"a told entry is not an object of path and anchor: {item!r}")
            continue
        if entry.get("code"):
            out += _called_problems(entry, item, env)
        else:
            out += _reach_problems(entry, item, env)
    return out


def _called_problems(entry: dict, item: dict, env: Env) -> list:
    rel, function = str(item["path"]), str(entry["code"]).split("::")[-1]
    if "anchor" in item:
        return [f"told {rel}: a code producer is told where it is CALLED; an anchor has no meaning here"]
    if not re.match(r"^scripts/[A-Za-z0-9_]+\.py$", rel):
        return [f"told {rel}: a code producer is called in a `scripts/*.py` file (not under tests/)"]
    hits = env.calls(rel, function)
    if hits is None:
        return [f"told {rel}: cannot be read or parsed"]
    return [] if hits else [f"told {rel}: no call of `{function}` outside its own definition (a name in a comment "
                            "or a string is no call) - the producer is not run on this path"]


def _reach_problems(entry: dict, item: dict, env: Env) -> list:
    out, anchor = [], item.get("anchor")
    if not isinstance(anchor, str) or not anchor.strip():
        return [f"told {item['path']}: `anchor` is missing - a verbatim phrase of the file proves what it says"]
    for role in entry.get("roles") or []:
        rel = _expand(str(item["path"]), role)
        text = env.text(rel)
        if text is None:
            out.append(f"told {rel}: the file does not exist ({role})")
        elif not env.reaches(role, rel):
            out.append(f"told {rel} is not read by {role} (not its agent file, not injected for it by inject-map.json)")
        elif anchor not in text:
            out.append(f"told {rel}: the anchor {anchor!r} is not in the file ({role})")
    return out


def _demands_leg(check: str, entry: dict, env: Env) -> list:
    """Direction C for one role entry: every demanded token occurs in a told file the role receives. A code producer
    demands nothing of a role."""
    if entry.get("code"):
        return []
    literal, carrier = entry.get("demands"), entry.get("demands_from")
    if not isinstance(literal, list) or not all(isinstance(t, str) and t for t in literal):
        return ["`demands` is not a list of tokens"]
    if carrier is not None and carrier not in CARRIERS:
        return [f"`demands_from` {carrier!r} is not one of {', '.join(CARRIERS)}"]
    out = []
    for role in entry.get("roles") or []:
        tokens, why = list(literal), ""
        if carrier:
            more, why = demand_tokens(carrier, role, check, env)
            tokens += more
        if why or not tokens:
            out.append(why or f"the demands leg is missing for {role}")
            continue
        texts = [env.text(_expand(str(t["path"]), role)) or "" for t in entry.get("told") or []
                 if isinstance(t, dict) and "path" in t and env.reaches(role, _expand(str(t["path"]), role))]
        out += [f"{role} is not told `{token}` in any of its told files" for token in dict.fromkeys(tokens)
                if not any(token in text for text in texts)]
    return out


def _entry_problems(check: str, index: int, entry, env: Env) -> tuple:
    """`(problems, has_gap)` of one producer entry: the sentences, and a bool - True when the entry declares a well-formed
    gap on a leg of LEGS (counted against the ratchet). A gap lets its leg be incomplete, once and by name."""
    label = f"{check} producer[{index}]"
    if not isinstance(entry, dict):
        return [f"stage-joints: {label} is not an object"], False
    out = [f"stage-joints: {label} has an unknown key `{k}`" for k in entry if k not in ENTRY_KEYS]
    out += [f"stage-joints: {label} lacks `{k}`" for k in ENTRY_REQUIRED if k not in entry]
    if out:
        return out, False
    if ROLE_LEG_KEY in entry and (entry[ROLE_LEG_KEY] != ROLE_LEG_NOT_WALKED or not entry.get("code")):
        out.append(f"stage-joints: {label}: `{ROLE_LEG_KEY}` is only `{ROLE_LEG_NOT_WALKED}`, on an entry with `code`")
    gap = entry.get("gap")
    out += _gap_problems(label, gap)
    if not isinstance(entry["field"], str) or len(entry["field"].strip()) < FIELD_MIN:
        out.append(f"stage-joints: {label}: `field` is shorter than {FIELD_MIN} characters - say what is produced")
    legs = {"producer": _producer_leg(entry, env)}
    if not legs["producer"]:
        legs["told"] = _told_leg(entry, env)
        if entry.get("told"):            # a missing told leg is said once; the tokens are judged against files that exist
            legs["demands"] = _demands_leg(check, entry, env)
    declared = gap.get("leg") if isinstance(gap, dict) else None
    for leg in LEGS:
        found = legs.get(leg)
        if found is None:
            continue
        if leg == declared:
            if not found:
                out.append(f"stage-joints: {label}: gap declared on a complete leg ({leg}) - remove it")
            continue
        for sentence in found:
            hint = (' and no gap is declared - name it, or declare {"leg","ref","why"} (FR-5, FR-38)'
                    if sentence.startswith(f"the {leg} leg is missing") else "")
            out.append(f"stage-joints: {label}: {sentence}{hint}")
    if declared in ("told", "demands") and declared not in legs:
        out.append(f"stage-joints: {label}: gap declared on the {declared} leg, which is not judged "
                   "(the producer leg, or an empty told leg, comes first)")
    return out, isinstance(gap, dict) and declared in LEGS


# --------------------------------------------------------------------------------------- one row, the rows
def _row_problems(row, env: Env, stage_ids: set) -> tuple:
    """`(problems, [declared gap legs])` of one row."""
    if not isinstance(row, dict):
        return ["stage-joints: a joint row is not an object"], []
    check = str(row.get("check"))
    unknown = [k for k in row if k not in ROW_KEYS]
    lacking = [k for k in ROW_KEYS if k not in row]
    out = [f"stage-joints: {check}: unknown key `{k}`" for k in unknown]
    out += [f"stage-joints: {check}: lacks `{k}`" for k in lacking]
    if unknown or lacking:
        return out, []
    stages = row["stages"]
    if not isinstance(stages, list) or not stages:
        out.append(f"stage-joints: {check}: `stages` is empty - a check that runs at no stage")
    elif not all(s in stage_ids for s in stages):
        out.append(f"stage-joints: {check}: `stages` names {[s for s in stages if s not in stage_ids]}, "
                   "which are no stage of stages.json")
    elif check.startswith("detector:") and stages != [check.split(":")[1]]:
        out.append(f"stage-joints: {check}: `stages` is {stages}, a detector row runs at the stage in its key")
    producers, gaps = row["producers"], []
    if not isinstance(producers, list) or not producers:
        out.append(f"stage-joints: {check}: `producers` is empty - an entry for each writer, or an entry whose gap "
                   "declares the producer leg")
        return out, gaps
    for index, entry in enumerate(producers):
        problems, has_gap = _entry_problems(check, index, entry, env)
        out += problems
        if has_gap:
            gaps.append(entry["gap"]["leg"])
    out += _joint_problems(check, row["joint"], env)
    return out, gaps


def _joint_problems(check: str, joint, env: Env) -> list:
    """The census of recorded-run tests: `null` is counted, never red; a joint names a test and a fixture that exist and
    the test must mention the fixture folder (the test really reads it)."""
    if joint is None:
        return []
    if not isinstance(joint, dict) or set(joint) != {"test", "fixture"}:
        return [f"stage-joints: {check}: `joint` is null or an object of `test` and `fixture`"]
    test, fixture = str(joint["test"]), str(joint["fixture"])
    out = []
    text = env.text(test)
    if text is None:
        out.append(f"stage-joints: {check}: joint test {test} does not exist")
    if not (env.plugin / fixture).exists():
        out.append(f"stage-joints: {check}: joint fixture {fixture} does not exist")
    elif text is not None and Path(fixture.rstrip("/")).name not in text:
        out.append(f"stage-joints: {check}: joint test {test} never mentions the fixture folder "
                   f"{Path(fixture.rstrip('/')).name} - it does not read it")
    return out


def _direction_a(rows: list, uni: dict) -> list:
    """Every check in code has exactly one row; a row for a check the walk does not meet is stale."""
    out, seen = [], {}
    for row in rows:
        key = row.get("check") if isinstance(row, dict) else None
        seen[key] = seen.get(key, 0) + 1
    for key, n in seen.items():
        if n > 1:
            out.append(f"stage-joints: {key} has two rows")
        if key not in uni:
            out.append(f"stage-joints: row {key}: stale - the walk does not meet this check; remove the row or fix its key")
    for key, where in uni.items():
        if key not in seen:
            out.append(f"stage-joints: {key} is a check in code ({where}) and has no row in references/stage-joints.json - "
                       "add its producer and where the role is told (FR-38, AR-10)")
    return out


def _pins(uni: dict, pins: dict) -> list:
    out = []
    for kind, pinned in (pins or {}).items():
        got = sum(1 for key in uni if key.split(":", 1)[0] == kind)
        if got != pinned:
            out.append(f"{kind} checks: {got}, pinned {pinned}")
    return out


def _ratchet(data: dict, gaps: int) -> list:
    import null_outcomes
    rows = data.get("ratchet")
    if not isinstance(rows, list):
        return []
    return [f"stage-joints: {sentence}" for sentence in null_outcomes.ratchet_problems(
        rows, gaps, key="gaps", node_re=RATCHET_NODE, node_words="F6-51 (the node that keeps this ratchet)",
        rise="a raise is named in the verdict (AR-20); close a gap instead, or declare none", noun="gaps",
        unit="declared gaps", drift="a gap declared without raising the ratchet in the open, or closed without lowering it")]


# ------------------------------------------------------------------------------------------- the report
class Report:
    """What `audit` found: `problems` (sentences, [] = green) and `counts` for the summary line."""

    def __init__(self):
        self.problems = []
        self.counts = {"exit": 0, "detector": 0, "window": 0, "rows": 0, "gaps": 0, "producer": 0, "told": 0,
                       "demands": 0, "held": 0, "role_leg": 0}
        self.no_detector = []

    @property
    def ok(self) -> bool:
        return not self.problems

    def line(self) -> str:
        c = self.counts
        return (f"stage joints: walked exit {c['exit']}, detector {c['detector']}, window {c['window']} | rows "
                f"{c['rows']}, gaps {c['gaps']} (producer {c['producer']}, told {c['told']}, demands {c['demands']}), "
                f"joints held {c['held']} of {c['rows']} | role leg not walked (code-to-code rows): {c['role_leg']} | "
                f"stages with no detector: "
                f"{', '.join(self.no_detector) or 'none'}")


def audit(data=None, uni=None, pins=None, env=None, path=None) -> Report:
    """Walk the registry against the package and say what has no home. Everything is injectable; the defaults are the
    real tree. `data` may be a str (the reason the file could not be read) - red, never an empty registry (E8).

    uni   `universe()`'s answer: ({key: where}, [walk errors]);  env   an `Env`;  pins  {kind: size} (red in both
    directions);  path  the data file to read when `data` is None."""
    report = Report()
    red = report.problems.append
    if data is None:
        import null_outcomes
        data, why = null_outcomes.load_data(Path(path) if path else DATA)
        if data is None:
            red(f"stage-joints: {why}")
            return report
    elif isinstance(data, str):
        red(f"stage-joints: {data}")
        return report
    shape = _shape_problems(data)
    report.problems.extend(shape)
    if not isinstance(data.get("joints"), list) or not data["joints"]:
        return report
    env = env or Env.real()
    uni, walk_errors = universe() if uni is None else uni
    report.problems.extend(f"stage-joints: {e}" for e in walk_errors)
    report.problems.extend(f"stage-joints: {p}" for p in _pins(uni, pins))
    rows = data["joints"]
    report.problems.extend(_direction_a(rows, uni))
    stage_ids = {str(s.get("id")) for s in env.model.get("stages") or [] if isinstance(s, dict)}
    declared = []
    for row in rows:
        problems, legs = _row_problems(row, env, stage_ids)
        report.problems.extend(problems)
        declared += legs
    report.problems.extend(_ratchet(data, len(declared)))
    c = report.counts
    c.update({kind: sum(1 for key in uni if key.split(":", 1)[0] == kind) for kind in ("exit", "detector", "window")})
    c.update({"rows": len(rows), "gaps": len(declared), "held": sum(1 for r in rows if isinstance(r, dict) and r.get("joint")),
              "role_leg": sum(1 for r in rows if isinstance(r, dict) for e in r.get("producers") or []
                              if isinstance(e, dict) and e.get(ROLE_LEG_KEY) == ROLE_LEG_NOT_WALKED)})
    for leg in LEGS:
        c[leg] = declared.count(leg)
    report.no_detector = [str(s.get("id")) for s in env.model.get("stages") or []
                          if not any(k.startswith(f"detector:{s.get('id')}:") for k in uni)]
    return report


# ----------------------------------------------------------------------------------------- the threshold
def threshold(path=None):
    """The count of one class of gate block at which the retro says it is a finding, or None when the registry cannot
    say (absent file, bad JSON, no `friction`, not an integer of at least 2). None is "threshold unknown" to the reader,
    never a hidden default (E9)."""
    import null_outcomes
    data, _why = null_outcomes.load_data(Path(path) if path else DATA)
    friction = (data or {}).get("friction")
    value = friction.get(KEY) if isinstance(friction, dict) else None
    return value if _is_count(value, FRICTION_MIN) else None


# ---------------------------------------------------------------------------------------------- the CLI
def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    args = list(sys.argv[1:] if argv is None else argv)
    path = None
    if "--data" in args:
        at = args.index("--data")
        path = args[at + 1] if at + 1 < len(args) else None
        if path is None:
            print("stage_joints: --data needs a file", file=sys.stderr)
            return USAGE_EXIT
    import null_outcomes
    data, why = null_outcomes.load_data(Path(path) if path else DATA)
    if data is None:
        import detector_verdict
        print(detector_verdict.unreadable_line(why))
        return detector_verdict.EXIT_UNREADABLE
    report = audit(data)
    print(report.line())
    if report.problems:
        print(f"REJECT — {len(report.problems)} finding(s):")
        for problem in report.problems:
            print(f"- {problem}")
        return 1
    print("stage joints: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
