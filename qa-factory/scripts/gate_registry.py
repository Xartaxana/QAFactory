"""gate_registry.py — A26 (FR-59): every gate that judges "is this run / test / stand / proof valid"
is a row in references/gate-registry.json, and no verdict-word comparison sits outside a row.

FR-59 says a gate does not decide on an unknown: it names what it could not establish and asks
whoever can know, or takes the safe default it declares, never a pass. Until now that was carried by
memory: twelve places repeated their own copy of "which provenance words are good enough"
(B-255a), each with its own answer to "and if the stand could not be read". A copy added tomorrow
would carry its own answer too, and nothing would be red. So the list of gates is DATA and this
scanner holds the code to it, the way refusal_registry.py (A24) holds the refusals to theirs.

  gate_registry.py --check    # audit A26 (exit 1 on a finding); then the gates left as debt, and the exempt
  gate_registry.py --sites    # every verdict comparison the scanner sees, and the row it belongs to
  gate_registry.py --json     # --check as JSON (with --sites: the sites as JSON)
  gate_registry.py            # the registry as a table

A26 runs under `selftest --tests` / `--contracts` (scripts/tests/test_gate_registry.py) and through
this CLI. It is NEVER wired into audit_factory.main(): that is the project doctor, which runs in
every project at doctor time, and these are package files a project never changes (t-305 Q6(c),
t-313 F9).

WHAT IS A VERDICT COMPARISON. The scan parses every scripts/*.py (not scripts/tests/**) with `ast`.
  * a Compare with an operator in {==, !=, in, not in, is, is not}, or a `match` case, where an
    operand is a str Constant; a Set/Tuple/List display, or set()/frozenset()/tuple()/list() over one,
    holding a str; a dict display (its keys); the branches of a conditional; or a Name that the same
    module (at module level) or the same function assigned such a value;
  * a bare collection display of that kind outside any Compare (a hidden token set such as
    `accepts=("matched", ...)`).
It counts when one of its words is an `anchor_words` member, ANYWHERE in the package, or a word of a
row's `words` inside a function that row registers as a site. A word in a docstring, a comment, an
f-string, a dict KEY, a plain assignment `x = "matched"`, a `.get("matched")` argument or a
subscript index is not a comparison and is never a finding.

THE ANCHOR FLOOR. A26 always scans for `matched`, `mismatched` and `person_confirmed`, even when the
registry names no anchors or fewer: the data may add anchor words, it can never drop these (a data
edit must not silence the detector). A registry whose `anchor_words` omits one of them is a finding.

WHEN IT IS ALLOWED. A comparison inside a registered site is allowed when the site's role is
produce / validate / dispatch / measure / vocabulary / library; or accept, in a row whose status is
`debt` or `exempt`; or accept in a `converted` row ONLY when its source text EQUALS one of the site's
`allow[].compare` entries - the WHOLE comparison, never a prefix (both sides compared with whitespace
collapsed and every `"` read as `'`, the form `ast.unparse` prints). Anything else is a finding that
names file:line, function and the source. A bare token set (`ACCEPTS = (...)`) bound to a name is left to
the comparisons that use it only when EVERY read of the name in its module is such a comparison; one read
as a call argument, a return value, an attribute base or a default parameter reports the set at its
binding line, and the module must register it (`profile_contract.py:<module>` is a `vocabulary` site).

FINDINGS (exit 1). Every one names the row or the site and the door (an edit of the registry).
  F-a  a verdict comparison (or token set) in no registered gate, or in a converted accept site outside `allow`
  F-b  a converted accept site that calls no `acceptable` (the check was deleted, not converted)
  F-c  a stale site: the file, or the function, is gone
  F-d  an `allow` entry that matches no comparison in its site any more, or that is only the START of one
       ("allow must be the whole comparison")
  F-e  an ambiguous site: the function name is defined twice in the file
  F-f  a schema rule of references/gate-registry.json (the rules are in `_check_row`); also: a function
       registered by two rows when one of them is a converted accept site (the other row's role would
       mask the conversion), a consumer id (`<gate>.<consumer>`) used by two rows, a consumer that accepts
       `person_confirmed` under a gate row (named by its id's prefix) that is promotable false, and a
       `converted` row whose `vocabulary` is `target` (its `words` are class words standing in for the
       gate's own, so the scan would check nothing: `vocabulary` is `code` or `target` on every row)
  F-g  the registry cannot be read: absent, 0 bytes, not UTF-8, not JSON, duplicate keys, not an
       object, or carrying no `rows` list; and a scripts/*.py that does not parse

SCOPE AND ITS LIMITS. A26 catches LITERAL verdict-word comparisons. Invisible to it: a literal-free
silent pass (a dict dispatch `{"matched": ok}[r]`, a vocabulary imported from another module, the
truthiness of a field, a check deleted from an unregistered function) and a word passed as a call
argument to a helper in another module. Also invisible, one line each (t-359 F5; B-291 a):
  * a class attribute or an Enum constant as the word (`x == V.OK`);
  * a one-word default parameter (`def f(ok="matched")`);
  * `operator.eq(x, "matched")` and every other call that compares for you;
  * a word cut out of a string (`"a matched b".split()`), and `.startswith("match")`;
  * a dict looked up by the word (`d.get(word)`), a comprehension filter
    (`{w for w in WORDS if w != "x"}`), and a Compare whose only words are not anchors and sit outside
    any registered site.
Stated here and printed under the header of `--check`:

  BLIND SPOT: a gate that compares only non-anchor words, outside any registered site, is not seen.

That class is the per-gate behaviour test's job; its runtime detector is the Forge's per-feature
false-pass count. Also invisible: a `debt_ref` that points at a backlog row since closed. The package
cannot read plans/, so the check of openness is the Lead's (read through the row's status line).
One `allow` entry covers every comparison in its site with that exact text (two identical ones are
both allowed). No limit or truncation is introduced: sources and findings print whole.

THE `--json` CONTRACT (FR-14; the keys are pinned by test_gate_registry.py).
  --check / --json      {"findings": [str, ...],
                         "debt":   [{"id", "decides", "debt_ref"}, ...],
                         "exempt": [{"id", "decides", "exempt_reason"}, ...]}
  --sites --json        [{"file", "line", "function", "source", "rows": [row id, ...], "allowed": bool}, ...]
Nothing else goes to stdout under --json. `findings` strings are the lines of the human form, without
the leading "  - ". The human `--sites` line ends in one of three labels: `[<row>]` (registered),
`[<row> NOT ALLOWED]` (in a converted accept site, outside its `allow` list) or `[UNREGISTERED]` (in no
row); in JSON: `rows` empty = unregistered, `rows` set and `allowed` false = not allowed.

The registry schema and the rows are documented in the registry's own `note` and checked in
`_check_row`. This file writes nothing (FR-45).
"""
import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path
from hooklib import sorted_paths

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_REL = "references/gate-registry.json"
MODULE = "<module>"

ROLES = ("accept", "dispatch", "produce", "validate", "measure", "vocabulary", "library")
STATUSES = ("converted", "debt", "exempt")
UNKNOWN_BRANCHES = ("question", "debt", "rerun", "refuse_with_door", "exempt")
ON_NO_ANSWER = ("wait", "debt", "rerun", "refuse_with_door", "n/a")
WAITS_AT = ("stage_entry", "window_acceptance", "gate_a", "gate_b", "authorization")
OWNERS = ("environment", "person", "role", "factory")
PERSON_SUBJECTS = ("world", "intent")
# The floor of the scan (see the docstring): code, not data, so that no edit of the registry can
# make the detector blind to the three words that are never anything but a verdict.
ANCHOR_FLOOR = ("matched", "mismatched", "person_confirmed")
CLASSES_DEFAULT = ("matched", "mismatched", "unknown", "not_applicable", "person_confirmed")

TOP_KEYS = {"schema_version", "note", "classes", "anchor_words", "rows"}
ROW_KEYS = {"id", "inventory", "decides", "sites", "field", "words", "verdict_map", "accepts", "promotable",
            "unknown_branch", "on_no_answer", "waits_at", "closed_by", "addressee", "person_subject",
            "policy_file", "scope_keys", "binding_keys", "question_kind", "test", "status", "debt_ref",
            "exempt_reason", "vocabulary"}
ROW_REQUIRED = ("id", "inventory", "decides", "sites", "words", "verdict_map", "promotable",
                "unknown_branch", "on_no_answer", "status", "vocabulary")
# `target`: the row's words are the class words standing in for a vocabulary the gate does not have yet;
# `code`: they are the gate's own words, as the code writes them. A converted row must say `code`: a
# comparison against a stand-in word the code never uses would pass the scan with nothing to check.
VOCABULARIES = ("target", "code")
SITE_KEYS = {"file", "function", "role", "allow"}
ALLOW_KEYS = {"compare", "why"}
MAP_KEYS = {"class", "owner", "reason_code"}

ID_RE = re.compile(r"[a-z][a-z0-9_]*")
CONSUMER_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
INVENTORY_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
DEBT_REF_RE = re.compile(r"B-[0-9]{3}")        # ASCII digits only: `\d` would take other scripts' digits
REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
TEST_RE = re.compile(r"scripts/tests/[A-Za-z0-9_]+\.py")
ADDRESSEE_RE = re.compile(r"code_routes|judge_advisory|person|role:[a-z][a-z0-9-]*")

BLIND_SPOT = ("a gate that compares only non-anchor words, outside any registered site, is not seen "
              "(a literal-free pass is the per-gate behaviour test's)")

EQLIKE = (ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Is, ast.IsNot)
SETLIKE = ("set", "frozenset", "tuple", "list")


# --- the scanner --------------------------------------------------------------------------------

def _is_display(node) -> bool:
    return isinstance(node, (ast.Set, ast.Tuple, ast.List))


def _is_setlike_call(node) -> bool:
    """set()/frozenset()/tuple()/list() over a string or a display - the shape of a hidden token set."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SETLIKE
            and bool(node.args) and _is_value_shape(node.args[0]))


def _display_words(node) -> set:
    """The str constants a value is made of: the Constant itself, a display's members (nested ones too),
    or the display under set()/frozenset()/tuple()/list()."""
    out: set = set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.add(node.value)
    elif _is_display(node):
        for elt in node.elts:
            out |= _display_words(elt.value if isinstance(elt, ast.Starred) else elt)
    elif _is_setlike_call(node):
        out |= _display_words(node.args[0])
    return out


def _is_value_shape(node) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)) or _is_display(node) \
        or _is_setlike_call(node)


def norm(text: str) -> str:
    """The comparison form of a source text: whitespace collapsed, and every `"` read as `'` (what
    `ast.unparse` prints), so a registry entry may be written with either quote."""
    return " ".join(str(text).split()).replace('"', "'")


def _source(node) -> str:
    try:
        return " ".join(ast.unparse(node).split())
    except Exception:
        return f"<{type(node).__name__}>"


# Nodes the walk never needs to enter: they hold no comparison and no display, and about half of a
# package's nodes are these (a measured scan of the whole package took 16 s before they were skipped).
_SKIP = {ast.Constant, ast.Name} | {
    cls for cls in vars(ast).values()
    if isinstance(cls, type) and issubclass(cls, (ast.expr_context, ast.operator, ast.cmpop, ast.boolop,
                                                  ast.unaryop))}
_DISPLAYS = (ast.Set, ast.Tuple, ast.List)


def _walk(tree: ast.AST) -> dict:
    """One pass over a module: the OUTERMOST enclosing def's name of every node (A24's owner rule; a
    method is keyed by its bare name; MODULE outside any def), carried down instead of stored.
    Returns the lists the passes below read: outermost displays, Compares, Matches and assignments,
    the defs by name, and the functions that call `acceptable`."""
    got = {"outer": {}, "assigns": [], "compares": [], "matches": [], "displays": [], "acceptable_in": set(),
           "loads": {}}
    outer, assigns, compares = got["outer"], got["assigns"], got["compares"]
    matches, displays, acceptable_in = got["matches"], got["displays"], got["acceptable_in"]
    loads = got["loads"]       # name -> how many times the module READS it (t-360 F2)

    def rec(node, func, cls, in_display):
        t = type(node)
        is_display = False
        if t is ast.FunctionDef or t is ast.AsyncFunctionDef:
            if func == MODULE:
                outer[node.name] = outer.get(node.name, 0) + 1
                func = node.name
            cls = False
        elif t is ast.ClassDef:
            if func == MODULE:
                cls = True
        elif t is ast.Compare:
            compares.append((node, func))
        elif t is ast.Assign or t is ast.AnnAssign:
            assigns.append((node, func, cls))
        elif t is ast.Match:
            matches.append((node, func))
        elif t is ast.Call:
            callee = node.func
            if (type(callee) is ast.Name and callee.id == "acceptable") or \
                    (type(callee) is ast.Attribute and callee.attr == "acceptable"):
                acceptable_in.add(func)
            is_display = _is_setlike_call(node)
        if t in _DISPLAYS:
            is_display = True
        if is_display and not in_display:
            displays.append((node, func))
        for field in node._fields:
            value = getattr(node, field, None)
            if value is None:
                continue
            if value.__class__ is list:
                for child in value:
                    if not isinstance(child, ast.AST):
                        continue
                    if type(child) is ast.Name:
                        if type(child.ctx) is ast.Load:
                            loads[child.id] = loads.get(child.id, 0) + 1
                    elif type(child) not in _SKIP:
                        rec(child, func, cls, is_display)
            elif isinstance(value, ast.AST):
                if type(value) is ast.Name:
                    if type(value.ctx) is ast.Load:
                        loads[value.id] = loads.get(value.id, 0) + 1
                elif type(value) not in _SKIP:
                    rec(value, func, cls, is_display)

    rec(tree, MODULE, False, False)
    return got


def _scan_tree(tree: ast.AST) -> dict:
    got = _walk(tree)
    outer = got["outer"]

    # pass 1: the names a module (at module level) or a function binds to a string or a display
    module_names: dict = {}
    func_names: dict = {}
    bound: dict = {}           # id(display value) -> [(scope, name)]
    for node, scope, cls in got["assigns"]:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not _is_value_shape(value):
            continue
        words = _display_words(value)
        if not words:
            continue
        if scope == MODULE and cls:
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            table = module_names if scope == MODULE else func_names.setdefault(scope, {})
            table.setdefault(target.id, set()).update(words)
            bound.setdefault(id(value), []).append((scope, target.id))

    def names_for(func: str, name: str) -> set:
        out: set = set()
        if name in func_names.get(func, {}):
            out |= func_names[func][name]
        if name in module_names:
            out |= module_names[name]
        return out

    def operand_words(node, func: str) -> tuple:
        """(words, handled): `handled` operands have their displays consumed by the Compare."""
        if _is_value_shape(node):
            return _display_words(node), True
        if isinstance(node, ast.Name):
            return names_for(func, node.id), False
        if isinstance(node, ast.Dict):
            return {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}, True
        if isinstance(node, ast.IfExp):
            a, ha = operand_words(node.body, func)
            b, hb = operand_words(node.orelse, func)
            return a | b, ha or hb
        return set(), False

    # `source` is built when a comparison is first reported (`_src`), not for every one of the thousands
    # of string comparisons a package holds.
    items: list = []
    consumed: set = set()
    in_compare: dict = {}      # name -> reads of it that are a direct operand of a ==/!=/in/not in/is/is not

    # pass 2a: Compares and match cases
    for node, func in got["compares"]:
        if not any(isinstance(op, EQLIKE) for op in node.ops):
            continue
        words: set = set()
        for operand in [node.left, *node.comparators]:
            if isinstance(operand, ast.Name):
                in_compare[operand.id] = in_compare.get(operand.id, 0) + 1
            found, handled = operand_words(operand, func)
            words |= found
            if handled:
                consumed.update(id(d) for d in ast.walk(operand))
        if words:
            items.append({"line": node.lineno, "function": func, "node": node, "words": frozenset(words),
                          "kind": "compare"})
    for node, func in got["matches"]:
        for case in node.cases:
            words = {m.value.value for m in ast.walk(case.pattern)
                     if isinstance(m, ast.MatchValue) and isinstance(m.value, ast.Constant)
                     and isinstance(m.value.value, str)}
            if words:
                items.append({"line": case.pattern.lineno, "function": func, "node": node, "case": case,
                              "words": frozenset(words), "kind": "match"})

    # pass 2b: bare displays (hidden token sets): the outermost of each, not inside a Compare
    for node, func in got["displays"]:
        if id(node) in consumed:
            continue
        words = _display_words(node)
        if not words:
            continue
        pairs = bound.get(id(node))
        # A name-bound set is left to the Compares that use it ONLY when every read of the name in the
        # module is such a Compare (they carry the finding). One read as a call argument, a return value,
        # an attribute base or a default parameter makes it a token set in use elsewhere: reported at its
        # binding line (t-360 F2: profile_contract.ACCEPTS handed to story_run as its acceptance tokens).
        if pairs and all(got["loads"].get(name, 0) > 0 and got["loads"].get(name, 0) == in_compare.get(name, 0)
                         for _scope, name in pairs):
            continue
        items.append({"line": node.lineno, "function": func, "node": node, "words": frozenset(words),
                      "kind": "display"})
    items.sort(key=lambda i: i["line"])
    return {"error": None, "items": items, "outer": outer, "acceptable_in": got["acceptable_in"]}


def _src(item: dict) -> str:
    """The source text of a comparison, built on first use and kept on the item."""
    if "source" not in item:
        if item["kind"] == "match":
            item["source"] = (f"match {_source(item['node'].subject)}: case {_source(item['case'].pattern)}")
        else:
            item["source"] = _source(item["node"])
    return item["source"]


_SCAN_CACHE: dict = {}


def scan_file(path: Path) -> dict:
    """One file's candidate comparisons, cached by (path, mtime, size) so the test file's many
    variants of one registry do not parse the package again."""
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError as exc:
        return {"error": f"cannot be read: {exc}", "items": [], "outer": {}, "acceptable_in": set()}
    if key in _SCAN_CACHE:
        return _SCAN_CACHE[key]
    try:
        text = path.read_bytes().decode("utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text, filename=str(path))
        result = _scan_tree(tree)
    except (UnicodeDecodeError, SyntaxError, ValueError, RecursionError) as exc:
        result = {"error": f"does not parse: {type(exc).__name__}: {exc}", "items": [], "outer": {},
                  "acceptable_in": set()}
    _SCAN_CACHE[key] = result
    return result


def scan_package(root: Path) -> dict:
    """{file name: scan_file result} for every scripts/*.py (not scripts/tests/**)."""
    scripts = Path(root) / "scripts"
    out = {}
    if scripts.is_dir():
        for path in sorted_paths(scripts.glob("*.py")):
            out[path.name] = scan_file(path)
    return out


# --- the registry -------------------------------------------------------------------------------

def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def load_registry(root: Path):
    """(registry, None) or (None, why). Absent, 0 bytes, not UTF-8, not JSON, duplicate keys, not an
    object and no `rows` list all come back as a reason (F-g), never as an empty registry."""
    path = Path(root) / REGISTRY_REL
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "the file is absent"
    except OSError as exc:
        return None, f"it cannot be opened ({exc})"
    if not raw:
        return None, "the file is 0 bytes"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"it is not valid UTF-8 ({exc})"
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates)
    except (ValueError, RecursionError) as exc:
        return None, f"it is not valid JSON ({exc})"
    return data, structural_error(data)


def structural_error(data):
    """None when `data` can be analysed, else why it cannot (F-g)."""
    if not isinstance(data, dict):
        return "it is not a JSON object"
    if not isinstance(data.get("rows"), list):
        return "it carries no `rows` list"
    return None


def _is_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _token_problem(token) -> str | None:
    """Why `token` is not in the accepts grammar, or None. FR-59: unknown and mismatched are never accepted."""
    if not isinstance(token, str) or not token:
        return "an accepts token is not a non-empty string"
    word, _, reason = token.partition(":")
    if word in ("unknown", "mismatched"):
        return (f"token `{token}`: `{word}` is never accepted (FR-59: a gate does not decide on an unknown "
                "or a mismatch) - remove it")
    if word == "matched" or word == "person_confirmed":
        return None if not reason else f"token `{token}`: `{word}` takes no reason code"
    if word == "not_applicable":
        if reason and not REASON_RE.fullmatch(reason):
            return f"token `{token}`: the reason code after `not_applicable:` must match [a-z][a-z0-9_]*"
        return None
    return (f"token `{token}` is not in the grammar: matched | person_confirmed | not_applicable | "
            "not_applicable:<reason_code>")


def _check_row(row, index: int, root: Path, classes: tuple) -> list:
    """The schema rules of one row, each a finding that names the row id and the field."""
    if not isinstance(row, dict):
        return [f"rows[{index}]: a row is not a JSON object"]
    rid = row.get("id")
    who = rid if isinstance(rid, str) and rid else f"rows[{index}]"
    out: list = []

    def bad(field, why):
        out.append(f"{who}.{field}: {why}")

    for key in row:
        if key not in ROW_KEYS:
            out.append(f"{who}: unknown key `{key}` - the schema is strict; add it to gate_registry.ROW_KEYS "
                       "with its rule, or remove it")
    for key in ROW_REQUIRED:
        if key not in row:
            bad(key, "required, and missing")
    if "id" in row and not (isinstance(rid, str) and ID_RE.fullmatch(rid)):
        bad("id", "must match [a-z][a-z0-9_]*")
    if "inventory" in row and not (isinstance(row["inventory"], str) and INVENTORY_RE.fullmatch(row["inventory"])):
        bad("inventory", "one ASCII token (G1..G17, F9, R2-3, t-313)")
    if "decides" in row and not _is_str(row["decides"]):
        bad("decides", "must say, in words, what the gate decides")
    status = row.get("status")
    if "status" in row and status not in STATUSES:
        bad("status", f"must be one of {', '.join(STATUSES)}")
    vocab = row.get("vocabulary")
    if "vocabulary" in row and vocab not in VOCABULARIES:
        bad("vocabulary", f"must be one of {', '.join(VOCABULARIES)}: say whether `words` are the gate's own "
                          "(code) or class words standing in for them (target) - closed variety is explicit (FR-13)")
    elif status == "converted" and vocab == "target":
        bad("vocabulary", "a converted row must say `code`: its `words` are stand-ins, so a comparison "
                          "against the words the code really uses would pass the scan unchecked - give the row "
                          "the gate's own words, or do not convert it")
    words = row.get("words")
    if "words" in row:
        # An exempt row may have no verdict vocabulary at all (a request's shape, a launcher that
        # resolves): an invented word would be worse than an empty list. Every other row names its words.
        if not (isinstance(words, list) and (words or status == "exempt")
                and all(isinstance(w, str) for w in words)):
            bad("words", "must be a non-empty list of strings (only an exempt row may list none)")
        elif len(set(words)) != len(words):
            bad("words", "holds a duplicate word")
    vmap = row.get("verdict_map")
    if "verdict_map" in row:
        if not isinstance(vmap, dict):
            bad("verdict_map", "must be an object keyed by the gate's words")
        else:
            if isinstance(words, list):
                for w in words:
                    if isinstance(w, str) and w not in vmap:
                        bad("verdict_map", f"the word `{w}` has no entry - an unmapped word is a factory "
                                           "defect (FR-19), map it to a class")
                for w in vmap:
                    if w not in words:
                        bad("verdict_map", f"`{w}` is not one of the row's `words`")
            for w, entry in vmap.items():
                if not isinstance(entry, dict):
                    bad("verdict_map", f"the entry of `{w}` must be an object {{class, owner?, reason_code?}}")
                    continue
                for key in entry:
                    if key not in MAP_KEYS:
                        bad("verdict_map", f"`{w}` carries an unknown key `{key}`")
                if entry.get("class") not in classes:
                    bad("verdict_map", f"`{w}` maps to class `{entry.get('class')}`, not one of {', '.join(classes)}")
                if "owner" in entry and entry["owner"] not in OWNERS:
                    bad("verdict_map", f"`{w}` has owner `{entry['owner']}`, not one of {', '.join(OWNERS)}")
                if "reason_code" in entry and not (isinstance(entry["reason_code"], str)
                                                   and REASON_RE.fullmatch(entry["reason_code"])):
                    bad("verdict_map", f"`{w}` has a reason_code that is not [a-z][a-z0-9_]*")
    if "field" in row and row["field"] is not None and not _is_str(row["field"]):
        bad("field", "must be a record key or null")

    # sites
    sites = row.get("sites")
    if "sites" in row:
        if not isinstance(sites, list):
            bad("sites", "must be a list (empty for a gate with no code site of its own)")
        else:
            seen = set()
            for n, site in enumerate(sites):
                if not isinstance(site, dict):
                    bad("sites", f"entry {n} is not an object {{file, function, role, allow?}}")
                    continue
                for key in site:
                    if key not in SITE_KEYS:
                        bad("sites", f"entry {n} carries an unknown key `{key}`")
                fname, func = site.get("file"), site.get("function")
                if not (isinstance(fname, str) and fname.endswith(".py") and "/" not in fname
                        and chr(92) not in fname):
                    bad("sites", f"entry {n}: `file` must be the basename of a scripts/*.py")
                if not _is_str(func):
                    bad("sites", f"entry {n}: `function` must name the outermost def, or {MODULE}")
                if site.get("role") not in ROLES:
                    bad("sites", f"entry {n}: `role` must be one of {', '.join(ROLES)}")
                if isinstance(fname, str) and isinstance(func, str):
                    if (fname, func) in seen:
                        bad("sites", f"{fname}:{func} is registered twice in this row")
                    seen.add((fname, func))
                allow = site.get("allow", [])
                if not isinstance(allow, list):
                    bad("sites", f"entry {n}: `allow` must be a list of {{compare, why}}")
                    continue
                for m, entry in enumerate(allow):
                    if not (isinstance(entry, dict) and set(entry) <= ALLOW_KEYS and _is_str(entry.get("compare"))
                            and _is_str(entry.get("why"))):
                        bad("sites", f"entry {n}: allow[{m}] needs a non-empty `compare` (a source prefix) and "
                                     "a non-empty `why` - an exception with no reason is a hidden acceptance")

    # the decision about an unknown
    branch, no_answer = row.get("unknown_branch"), row.get("on_no_answer")
    if "unknown_branch" in row and branch not in UNKNOWN_BRANCHES:
        bad("unknown_branch", f"`{branch}` is not one of {', '.join(UNKNOWN_BRANCHES)} - a gate never passes "
                              "on an unknown (FR-59)")
    if "on_no_answer" in row and no_answer not in ON_NO_ANSWER:
        bad("on_no_answer", f"`{no_answer}` is not one of {', '.join(ON_NO_ANSWER)} - nothing is passed when "
                            "nobody answers (FR-59)")
    waits_at = row.get("waits_at")
    if waits_at is not None and waits_at not in WAITS_AT:
        bad("waits_at", f"`{waits_at}` is not one of {', '.join(WAITS_AT)} (`stage_exit` does not exist: the "
                        "automator's exit never waits on an item only another role can close)")
    closed_by = row.get("closed_by")
    if closed_by is not None and not _str_list(closed_by):
        bad("closed_by", "must be a list of strings")
    if no_answer == "wait":
        if waits_at is None:
            bad("waits_at", "required when `on_no_answer` is `wait`")
        if not (isinstance(closed_by, list) and closed_by):
            bad("closed_by", "must be non-empty when `on_no_answer` is `wait`")
    if _str_list(closed_by) and any(c.startswith("role:") for c in closed_by) and "person" not in closed_by:
        bad("closed_by", "names a role without `person`: a person's word passes every block (FR-4, P13)")
    addressee = row.get("addressee", [])
    if not isinstance(addressee, list) or not all(isinstance(a, str) and ADDRESSEE_RE.fullmatch(a)
                                                  for a in addressee):
        bad("addressee", "must be a list drawn from code_routes, role:<agent>, judge_advisory, person")
    else:
        if len(set(addressee)) != len(addressee):
            bad("addressee", "holds a duplicate")
        if "person" in addressee:
            if row.get("person_subject") not in PERSON_SUBJECTS:
                bad("person_subject", "required (world | intent) when `person` is an addressee: a person is "
                                      "asked only about the world the run uses, or about intent")
            if isinstance(vmap, dict):
                owners = [e.get("owner") for e in vmap.values()
                          if isinstance(e, dict) and e.get("class") == "unknown"]
                if owners and all(o == "factory" for o in owners):
                    bad("addressee", "a gate whose only unknown owner is `factory` has no `person` "
                                     "(FR-3: our own defects are reported, never asked)")
    if row.get("person_subject") is not None and row.get("person_subject") not in PERSON_SUBJECTS:
        bad("person_subject", f"must be one of {', '.join(PERSON_SUBJECTS)} or null")
    for key in ("scope_keys", "binding_keys"):
        if key in row and not _str_list(row[key]):
            bad(key, "must be a list of strings")
    for key in ("policy_file", "question_kind"):
        if key in row and row[key] is not None and not _is_str(row[key]):
            bad(key, "must be a string or null")

    # what a consumer accepts
    accepts = row.get("accepts", {})
    if not isinstance(accepts, dict):
        bad("accepts", "must be an object {\"<gate>.<consumer>\": [token, ...]}")
    else:
        for consumer, tokens in accepts.items():
            if not CONSUMER_RE.fullmatch(consumer):
                bad("accepts", f"consumer id `{consumer}` must look like <gate>.<consumer>")
            if not isinstance(tokens, list):
                bad("accepts", f"`{consumer}` must list tokens")
                continue
            for token in tokens:
                problem = _token_problem(token)
                if problem:
                    bad("accepts", f"`{consumer}`: {problem}")
                if token == "person_confirmed" and row.get("promotable") is False:
                    bad("promotable", f"is false, yet `{consumer}` accepts `person_confirmed`: a person's word "
                                      "may not lift this gate's unknown, so no consumer may list the token")
    if "promotable" in row and not isinstance(row["promotable"], bool):
        bad("promotable", "must be true or false")

    # test, status, debt
    test = row.get("test")
    if test is not None:
        if not (isinstance(test, str) and TEST_RE.fullmatch(test)):
            bad("test", "must be scripts/tests/<file>.py, or null")
        elif not (Path(root) / test).is_file():
            bad("test", f"{test} does not exist")
        elif status == "exempt":
            bad("test", "must be null for an exempt row")
    if status == "converted" and test is None:
        bad("test", "required for a converted row: the test that proves the gate's unknown branch")
    if status == "debt":
        ref = row.get("debt_ref")
        if not (isinstance(ref, str) and DEBT_REF_RE.fullmatch(ref)):
            bad("debt_ref", f"a debt row must name its open backlog row as B-nnn (ASCII), got {ref!r}")
    if status == "exempt" and not _is_str(row.get("exempt_reason")):
        bad("exempt_reason", "an exempt row must say why, in words")
    return out


def _check_registry(registry: dict, root: Path) -> list:
    """The schema findings of a whole registry (F-f)."""
    out: list = []
    for key in registry:
        if key not in TOP_KEYS:
            out.append(f"registry: unknown top-level key `{key}` - the schema is strict")
    if "schema_version" in registry and registry["schema_version"] != 1:
        out.append("registry.schema_version: must be 1")
    classes = registry.get("classes", list(CLASSES_DEFAULT))
    if not (isinstance(classes, list) and classes and all(isinstance(c, str) for c in classes)):
        out.append("registry.classes: must be a non-empty list of strings")
        classes = list(CLASSES_DEFAULT)
    anchors = registry.get("anchor_words")
    if "anchor_words" in registry:
        if not (isinstance(anchors, list) and anchors and all(isinstance(a, str) for a in anchors)):
            out.append("registry.anchor_words: must be a non-empty list of strings")
        else:
            for a in anchors:
                if a not in classes:
                    out.append(f"registry.anchor_words: `{a}` is not one of the classes")
            for floor in ANCHOR_FLOOR:
                if floor not in anchors:
                    out.append(f"registry.anchor_words: must keep `{floor}` - the data may add anchor words "
                               "but never drop one (the detector would go blind to it)")
    rows = registry["rows"]
    if not rows:
        out.append("registry.rows: the registry holds no rows - every gate would be unregistered")
    seen_ids: dict = {}
    consumers: dict = {}
    for n, row in enumerate(rows):
        out.extend(_check_row(row, n, root, tuple(classes)))
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if isinstance(rid, str):
            if rid in seen_ids:
                out.append(f"{rid}: the row id is used twice (rows[{seen_ids[rid]}] and rows[{n}]) - an id is one gate")
            seen_ids.setdefault(rid, n)
        if isinstance(row.get("accepts"), dict):
            for consumer in row["accepts"]:
                if consumer in consumers and consumers[consumer] != rid:
                    out.append(f"{rid}.accepts: consumer id `{consumer}` is already used by row "
                               f"`{consumers[consumer]}` - a consumer id resolves to one row")
                consumers.setdefault(consumer, rid)
    # A consumer inherits `promotable` from the row its <gate> prefix names, wherever it sits: moving a
    # consumer to a promotable row (or a data edit that adds the token) must not lift a false gate's ban.
    # A prefix that names no row (`provenance`, the namespace of provenance_acceptance's consumers)
    # inherits nothing - the consumer's own row decides, as before.
    promotable = {r.get("id"): r.get("promotable") for r in rows if isinstance(r, dict)}
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("accepts"), dict)):
            continue
        for consumer, tokens in row["accepts"].items():
            prefix = consumer.split(".")[0]
            if (isinstance(tokens, list) and "person_confirmed" in tokens and prefix != row.get("id")
                    and promotable.get(prefix) is False):
                out.append(f"{row.get('id')}.accepts: consumer `{consumer}` accepts `person_confirmed`, but the "
                           f"gate row `{prefix}` its id names is promotable false - a person's word may not "
                           "lift that gate's unknown, so no consumer of it may list the token")
    return out


def anchors_of(registry: dict) -> frozenset:
    data = registry.get("anchor_words")
    extra = [a for a in data if isinstance(a, str)] if isinstance(data, list) else []
    return frozenset(ANCHOR_FLOOR) | frozenset(extra)


def _registered_sites(registry: dict) -> dict:
    """{(file, function): [(row, site)]} for every well-formed site of a row with a valid status. A row
    with some OTHER schema defect still registers its sites: the defect is its own finding, and a flood
    of F-a on top of it would hide it."""
    index: dict = {}
    for row in registry.get("rows", []):
        if not isinstance(row, dict) or row.get("status") not in STATUSES or not isinstance(row.get("sites"), list):
            continue
        for site in row["sites"]:
            if not (isinstance(site, dict) and isinstance(site.get("file"), str)
                    and _is_str(site.get("function")) and site.get("role") in ROLES):
                continue
            index.setdefault((site["file"], site["function"]), []).append((row, site))
    return index


def _row_words(row: dict) -> set:
    return {w for w in row.get("words", []) if isinstance(w, str)} if isinstance(row.get("words"), list) else set()


def _allowed(regs: list, source: str) -> bool:
    text = norm(source)
    for row, site in regs:
        if site["role"] != "accept" or row["status"] != "converted":
            return True
        for entry in site.get("allow", []) if isinstance(site.get("allow"), list) else []:
            # the WHOLE comparison, never a prefix: a prefix such as `rec['result'] ==` would whitelist
            # the acceptance itself, and two comparisons that differ only in their tail (coverage_contract
            # :680 and :685 print the same text, but a longer one would not) could not be told apart
            if isinstance(entry, dict) and _is_str(entry.get("compare")) and text == norm(entry["compare"]):
                return True
    return False


def analyse(plugin_root=None, registry=None) -> dict:
    """The whole audit. `registry` (a dict) replaces the file for a test that varies it in memory.
    Returns {"findings": [str], "items": [{file, line, function, source, rows, allowed}], "debt": [...],
    "exempt": [...], "converted": [...]}."""
    root = Path(plugin_root or PLUGIN_ROOT)
    result = {"findings": [], "items": [], "debt": [], "exempt": [], "converted": []}
    if registry is None:
        registry, why = load_registry(root)
    else:
        why = structural_error(registry)
    if why:
        result["findings"].append(f"{REGISTRY_REL} cannot be read: {why}")
        return result
    findings = result["findings"]
    findings.extend(_check_registry(registry, root))
    anchors = anchors_of(registry)
    index = _registered_sites(registry)
    scans = scan_package(root)
    for name, scan in scans.items():
        if scan["error"]:
            findings.append(f"scripts/{name} {scan['error']} - A26 cannot scan it (errs toward flagging)")

    # sites: stale / ambiguous / a converted accept site with no acceptable() call / masked conversions
    stale_names: set = set()
    hits: dict = {}            # (file, function, allow text) -> True once a counted comparison EQUALS it
    longer: dict = {}          # ... -> True once one is merely LONGER than it (an entry that is a prefix)
    for (fname, func), regs in index.items():
        scan = scans.get(fname)
        rids = ", ".join(dict.fromkeys(str(r.get("id")) for r, _ in regs))
        if scan is None:
            findings.append(f"{rids}: site {fname}:{func} is stale - scripts/{fname} is gone; update the row "
                            f"in {REGISTRY_REL}")
            stale_names.add((fname, func))
            continue
        if scan["error"]:
            continue
        if func != MODULE and func not in scan["outer"]:
            findings.append(f"{rids}: site {fname}:{func} is stale - no def named `{func}` is left in {fname} "
                            f"(renamed or moved?); update the row in {REGISTRY_REL}")
            stale_names.add((fname, func))
            continue
        if func != MODULE and scan["outer"][func] > 1:
            findings.append(f"{rids}: site {fname}:{func} is ambiguous - {scan['outer'][func]} defs named "
                            f"`{func}` in {fname}; one registration would silently cover them all, so "
                            "rename one")
        converted_accept = [(r, s) for r, s in regs if s["role"] == "accept" and r["status"] == "converted"]
        if converted_accept:
            if len(regs) > 1:
                findings.append(f"{fname}:{func} is registered more than once ({rids}) and one registration is a "
                                "converted accept site: another registration's role would mask a literal left "
                                "in the converted site - give each row its own function")
            if func not in scan["acceptable_in"]:
                for row, _ in converted_accept:
                    findings.append(f"{row.get('id')}: converted accept site {fname}:{func} calls no acceptable() - "
                                    "a converted site goes through the one predicate (gate_template.acceptable); "
                                    "otherwise the row is not converted")

    # comparisons
    for name, scan in scans.items():
        if scan["error"]:
            continue
        for item in scan["items"]:
            regs = index.get((name, item["function"]), [])
            relevant = set(anchors)
            for row, _ in regs:
                relevant |= _row_words(row)
            if not (item["words"] & relevant):
                continue
            source = _src(item)
            prefix_covered = False
            for row, site in regs:
                for entry in site.get("allow", []) if isinstance(site.get("allow"), list) else []:
                    if isinstance(entry, dict) and _is_str(entry.get("compare")):
                        key = (name, item["function"], norm(entry["compare"]))
                        if norm(source) == norm(entry["compare"]):
                            hits[key] = True
                        elif norm(source).startswith(norm(entry["compare"])):
                            longer.setdefault(key, source)
                            prefix_covered = True
            allowed = bool(regs) and _allowed(regs, source)
            ids = []
            for row, _ in regs:
                if row.get("id") not in ids:
                    ids.append(row.get("id"))
            result["items"].append({"file": name, "line": item["line"], "function": item["function"],
                                    "source": source, "rows": ids, "allowed": allowed})
            # a comparison a PREFIX entry points at is reported once, by that entry's finding below (it names
            # the entry and this comparison); it stays unwhitelisted, so the audit is red either way
            if not allowed and not prefix_covered:
                what = "verdict token set" if item["kind"] == "display" else "verdict comparison"
                findings.append(f"{name}:{item['line']} ({item['function']}): the {what} "
                                f"`{source}` is in no registered gate - register the site in "
                                f"{REGISTRY_REL} with its unknown branch, or call gate_template.acceptable()")
    # allow entries: each must be the whole text of a comparison in its site (F-d otherwise)
    for (fname, func), regs in index.items():
        scan = scans.get(fname)
        if scan is None or scan["error"] or (fname, func) in stale_names:
            continue
        for row, site in regs:
            for entry in site.get("allow", []) if isinstance(site.get("allow"), list) else []:
                if not (isinstance(entry, dict) and _is_str(entry.get("compare"))):
                    continue
                key = (fname, func, norm(entry["compare"]))
                if hits.get(key):
                    continue
                if longer.get(key):
                    findings.append(f"{row.get('id')}: allow must be the whole comparison: `{entry['compare']}` of "
                                    f"site {fname}:{func} is only the start of `{longer[key]}`, which stays "
                                    "unwhitelisted - write the comparison out in full (ast.unparse form), or the "
                                    "entry would whitelist more than it names")
                else:
                    findings.append(f"{row.get('id')}: the allow entry `{entry['compare']}` of site {fname}:{func} "
                                    "matches no comparison there any more - remove it, or the site hides "
                                    "a literal it no longer names")
    for row in registry["rows"]:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if status == "debt":
            result["debt"].append({"id": row.get("id"), "decides": row.get("decides"), "debt_ref": row.get("debt_ref")})
        elif status == "exempt":
            result["exempt"].append({"id": row.get("id"), "decides": row.get("decides"),
                                     "exempt_reason": row.get("exempt_reason")})
        elif status == "converted":
            result["converted"].append({"id": row.get("id"), "decides": row.get("decides"), "test": row.get("test")})
    result["items"].sort(key=lambda i: (i["file"], i["line"]))
    return result


def findings(plugin_root=None, registry=None) -> list:
    return analyse(plugin_root, registry)["findings"]


def sites(plugin_root=None, registry=None) -> list:
    return analyse(plugin_root, registry)["items"]


# --- output -------------------------------------------------------------------------------------

def report(errors: list) -> None:
    if errors:
        print(f"A26 gate registry: VIOLATIONS ({len(errors)})  owner: factory — nothing wanted from you")
    else:
        print("A26 gate registry: no violations")
    print(f"  blind spot: {BLIND_SPOT}")
    for e in errors:
        print(f"  - {e}")


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="A26: the gates that judge validity, and the code held to them")
    ap.add_argument("--check", action="store_true", help="audit A26 (exit 1 on a finding)")
    ap.add_argument("--sites", action="store_true", help="every verdict comparison the scanner sees, and its row")
    ap.add_argument("--json", action="store_true", help="--check as JSON (with --sites: the sites)")
    ns = ap.parse_args(argv)

    if ns.sites:
        found = sites()
        if ns.json:
            print(json.dumps(found, indent=2, ensure_ascii=False))
        else:
            for s in found:
                if not s["rows"]:
                    label = "UNREGISTERED"                            # in no row at all
                elif s["allowed"]:
                    label = ", ".join(s["rows"])
                else:
                    label = ", ".join(s["rows"]) + " NOT ALLOWED"     # a converted accept site, outside its allow list
                print(f"{s['file']}:{s['line']}  {s['function']}  {s['source']}  [{label}]")
        return 0
    if ns.check or ns.json:
        got = analyse()
        if ns.json:
            print(json.dumps({"findings": got["findings"], "debt": got["debt"], "exempt": got["exempt"]},
                             indent=2, ensure_ascii=False))
        else:
            report(got["findings"])
            if got["debt"]:
                print(f"  {len(got['debt'])} gate(s) left as debt:")
                for d in got["debt"]:
                    print(f"    {d['id']}: {d['decides']} [{d['debt_ref']}]")
            if got["exempt"]:
                print(f"  {len(got['exempt'])} gate(s) exempt:")
                for e in got["exempt"]:
                    print(f"    {e['id']}: {e['decides']} [{e['exempt_reason']}]")
        return 1 if got["findings"] else 0
    registry, why = load_registry(PLUGIN_ROOT)
    if why:
        print(f"{REGISTRY_REL} cannot be read: {why}")
        return 1
    for row in registry["rows"]:
        print(f"{row.get('id')}  {row.get('status')}  {row.get('decides')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
