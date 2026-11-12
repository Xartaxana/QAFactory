"""The layer test of every split family (t-301 N0 for the driver; TD-11 B0b generalised it): a census of every name a family
defines, and the rules that keep the traffic between its modules one-directional (checks L1-L12).

A FAMILY is one original file (the facade) cut into parts `<prefix>*.py`. Every family has one map,
`fixtures/<prefix>-layers.json`; this test globs `fixtures/*-layers.json` and runs every check per map, reading all the family
facts from the map's `family` header: `{"facade": "<stem>", "prefix": "<prefix>_", "class": "<Class>" | null,
"cut": "mixins" | "functions", "installed": true | false}` (FR-44: the maps are read by tests only, so they are not under
`references/`). No family name is written in the check code (AR-1); the first family is the driver (`story_run`, `driver_`, `Driver`).

WHY IT IS AN AST TEST ON `self`. A class family is split into modules assembled into one class (mixins), and mixins never import
each other, so an import-direction test is vacuous: the traffic goes through `self.<attr>`, through `self.state[<key>]`, through
ad-hoc attributes of a `Person`, and through `getattr(self, <name chosen at run time>)`. This test reads the family set (the
facade plus every part) with `ast` and resolves EVERY such access against the map. The tables of those accesses (`attributes`,
`adhoc_attributes`, `state_keys`, `dynamic_state_keys`, `string_dispatch`, `stdout_writers`) are optional: a check over an absent
table is not run for that family, and one informational line says so.

It errs toward refusing: an access it cannot resolve fails; it never passes one. A map whose header is malformed (L10) skips every
other check of that map with one line naming why, so a malformed map never prints `ok` for a check it did not run. Each check
has a bad case, built in a temp directory below, that must be reported BY NAME (an evergreen layer test is impossible by
construction); the bad cases run once more under a second, invented family header to prove no family name is baked in.

    python -B scripts/tests/test_driver_layers.py                       # the checks
    python -B scripts/tests/test_driver_layers.py --draft-missing       # one JSON row, `home: null`, per unmapped name (homes are
                                                                        # a judgment by the rules of the family's spec; never defaulted)
    python -B scripts/tests/test_driver_layers.py --draft-all           # also the rows the census derives for the other tables
    (both draft modes take `--map <file name>` when more than one map exists)

The census counts module-level bindings (def, class, assignments) and the members of every class named `<Class>` or
`<Class><Suffix>` (methods, static and class methods, class constants), keyed `<Class>.<member>` whatever mixin holds them.
Imports, nested functions and the `__main__` block are excluded.
"""

import ast
import gc
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, finish  # noqa: E402

CUTS = ("mixins", "functions")
ALL_CHECKS = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "L12")
# The driver-only tables: absent = the checks over them are not run for the family (data default, AR-1).
OPTIONAL_TABLES = {"attributes": "L3", "adhoc_attributes": "L4", "state_keys": "L4", "dynamic_state_keys": "L4",
                   "string_dispatch": "L3", "stdout_writers": "L9"}
# The tables whose rows are about `self` of the family's class: on `class: null` there is nothing for them to describe.
CLASS_TABLES = ("attributes", "state_keys", "dynamic_state_keys", "string_dispatch")
# L8 counts the rig's tests, not the instrument. `harness.py` holds the readers of the family sets; the layer test itself is
# the other instrument. A family's own instrument files (its golden recorder) are listed in the map's header key `l8_skip`
# (a list of test file names; absent = empty).
L8_SKIP_ALL = {"harness.py", Path(__file__).name}

# The `exceptions` list is SHRINK-ONLY: it may lose rows when a node removes the upward edge, never gain one. PINNED_EXCEPTIONS
# is the per-family pin, keyed by the facade stem the map's `family` header names; a family that is not a key is pinned EMPTY.
# The pin EQUALS the map (one `from>to>kind` per line): a row in a map that is not pinned for its family fails L5 (it is new),
# and a pinned row the map no longer holds fails `pin_problems` (the pin is edited down in the same commit as the node that
# removed the edge), so a removed upward edge cannot come back unseen and a stale pin cannot stay (AR-20, axis 18).
PINNED_EXCEPTIONS = {"story_run": """
Driver.close_window_series>Driver.window_key>call
Driver.conductor_round>Driver.refusal_dispatch>call
Driver.finish>Driver.rebuild_report>call
Driver.handoff>Driver.close_vcs_gaps>call
Driver.run_role>Driver.s1_review_text>call
Driver.s0_quote>Driver.QUOTE_LIMIT>call
Driver.s1_person>Driver.s1_gap_text>call
Driver.s1_person>Driver.s1_review_text>call
"""}


def pinned_for(facade: str) -> set:
    """The pinned `from>to>kind` rows of the family whose facade stem is `facade`; a family with no pin is pinned EMPTY."""
    return {line.strip() for line in PINNED_EXCEPTIONS.get(facade, "").strip().split("\n") if line.strip()}


def pin_problems(rows: list, pinned: set, name: str = "the map", stale: bool = True) -> list:
    """The pin against the map's `exceptions` rows: a row the pin does not hold is new; with `stale`, a pinned row the map does
    not hold is a problem too (both directions run on the real map; a fixture map is not the pinned family's map, so analyse
    asks only the first)."""
    now = {f"{r.get('from')}>{r.get('to')}>{r.get('kind')}" for r in rows if isinstance(r, dict)}
    out = [f"{name}: exceptions row {label} is new: the list is pinned and shrink-only, so an upward edge is never added by "
           f"an exception. Remove the edge instead (hook, port, or move the name)." for label in sorted(now - pinned)]
    if stale:
        out += [f"{name}: the pin holds the row {label} but the map no longer does: drop it from PINNED_EXCEPTIONS in this "
                f"commit (a removed upward edge must not be able to come back unseen)." for label in sorted(pinned - now)]
    return out


# --- reading a family set -------------------------------------------------------------------------------------
def class_regex(fam: dict):
    """The regex of the family's class and its mixins (`<Class>` or `<Class><Suffix>`), or None for a functions family."""
    return re.compile(r"^" + re.escape(fam["class"]) + r"[A-Za-z0-9]*$") if fam.get("class") else None


def camel(area: str) -> str:
    """The mixin class suffix of a part's area: `s0` -> `S0`, `time_base` -> `TimeBase` (CamelCase of the area, spec B 2.3)."""
    return "".join(piece[:1].upper() + piece[1:] for piece in area.split("_"))


def mixin_class(fam: dict, home: str):
    """The class a member homed in `home` is written under by class name, or None when the home is the facade (the assembled
    class) or no part of the family."""
    if not home or home == fam["facade"] or not home.startswith(fam["prefix"]):
        return None
    return fam["class"] + camel(home[len(fam["prefix"]):])


def family_paths(root: Path, fam: dict, exempt=()) -> list:
    """The family's files: `scripts/<facade>.py` first, then the sorted `scripts/<prefix>*.py` minus the stems the map exempts as
    `not_driver` (a module that merely carries the prefix)."""
    scripts = Path(root) / "scripts"
    return [scripts / (fam["facade"] + ".py")] + [p for p in sorted(scripts.glob(fam["prefix"] + "*.py"))
                                                  if p.stem not in set(exempt) and p.stem != fam["facade"]]


def read_modules(root: Path, fam: dict, exempt=()) -> dict:
    """{stem: (path, text, tree)} of the family set. A missing facade raises with its path: an empty set would make every
    census over it pass."""
    paths = family_paths(root, fam, exempt)
    if not paths[0].is_file():
        raise FileNotFoundError(f"read_modules: {paths[0]} is missing; expected the family's facade there")
    out = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        out[path.stem] = (path, text, _parse(text, str(path)))
    return out


def _targets(node):
    out = []
    for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
        for n in ast.walk(target):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                out.append(n.id)
    return out


def definitions(mods: dict, fam: dict) -> dict:
    """{name: [{stem, line, kind}]} for every module-level binding and every member of a class of the family."""
    defs: dict = {}
    cls, cls_re = fam.get("class"), class_regex(fam)

    def add(name, stem, line, kind):
        defs.setdefault(name, []).append({"stem": stem, "line": line, "kind": kind})

    for stem, (_path, _text, tree) in mods.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(node.name, stem, node.lineno, "func")
            elif isinstance(node, ast.ClassDef):
                add(node.name, stem, node.lineno, "class")
                if cls_re and cls_re.match(node.name):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            kind = "method"
                            for deco in sub.decorator_list:
                                if isinstance(deco, ast.Name) and deco.id in ("staticmethod", "classmethod"):
                                    kind = deco.id
                            add(f"{cls}.{sub.name}", stem, sub.lineno, kind)
                        elif isinstance(sub, (ast.Assign, ast.AnnAssign)):
                            for name in _targets(sub):
                                add(f"{cls}.{name}", stem, sub.lineno, "classconst")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                for name in _targets(node):
                    add(name, stem, node.lineno, "const")
    return defs


# --- one function's traffic -------------------------------------------------------------------------------------
class Scan(ast.NodeVisitor):
    """What one function touches: `self.<attr>`, `<Class>.<attr>` by class name, `getattr(self, ...)`, state keys, Person
    attributes, module-level names, and the forms the test refuses to analyse (an alias of `self` or of `self.state`,
    `self.__dict__`, `vars(self)`). `cls_re` is the family's class regex (None: no class, no class-name accesses)."""

    def __init__(self, label: str, node, person_names=("person",), class_member: bool = True, cls_re=None):
        self.label, self.node = label, node
        self.class_member = class_member
        self.cls_re = cls_re
        self.class_use = []         # (class name as written, attr, line)
        self.self_use = []          # (attr, ctx 'load'|'store'|'del', line, how)
        self.dynamic_getattr = []   # (expr text, line)
        self.state_keys = []        # (key or None, line)
        self.person_use = []        # (attr, ctx, line)
        self.refused = []           # (message, line)
        self.names = set()
        self.locals = set()
        self.person_names = set(person_names)
        for n in ast.walk(node):
            if isinstance(n, ast.arg):
                self.locals.add(n.arg)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                self.locals.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
                self.locals.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for alias in n.names:
                    self.locals.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(n, ast.ExceptHandler):
                if n.name:
                    self.locals.add(n.name)
                if isinstance(n.type, ast.Name) and n.type.id == "Person" and n.name:
                    self.person_names.add(n.name)
        self.visit(node)

    @staticmethod
    def _is_self(node) -> bool:
        return isinstance(node, ast.Name) and node.id == "self"

    @staticmethod
    def _is_state(node) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "state"
                and isinstance(node.value, ast.Name) and node.value.id == "self")

    @staticmethod
    def _ctx(node) -> str:
        return {ast.Load: "load", ast.Store: "store", ast.Del: "del"}.get(type(node.ctx), "load")

    def visit_Attribute(self, node):
        if self._is_self(node.value):
            if node.attr == "__dict__":
                self.refused.append(("`self.__dict__` hides every attribute it touches", node.lineno))
            else:
                self.self_use.append((node.attr, self._ctx(node), node.lineno, "self"))
        elif isinstance(node.value, ast.Name) and self.cls_re and self.cls_re.match(node.value.id):
            # `<Class>.<m>` and `<Class><Area>.<m>` (a mixin), by the name as WRITTEN: resolved in analyse (L3, L12) against
            # the member row `<Class>.<m>` and its home - the assembled class, or exactly that home's mixin, never any
            # other name.
            self.class_use.append((node.value.id, node.attr, node.lineno))
        elif (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "type"
              and len(node.value.args) == 1 and self._is_self(node.value.args[0])):
            self.self_use.append((node.attr, "load", node.lineno, "type(self)"))
        elif isinstance(node.value, ast.Name) and node.value.id in self.person_names:
            self.person_use.append((node.attr, self._ctx(node), node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("getattr", "setattr", "hasattr", "delattr") and node.args:
            target = node.args[0]
            if self._is_self(target):
                second = node.args[1] if len(node.args) > 1 else None
                ctx = {"getattr": "load", "hasattr": "load", "setattr": "store", "delattr": "del"}[func.id]
                if isinstance(second, ast.Constant) and isinstance(second.value, str):
                    self.self_use.append((second.value, ctx, node.lineno, func.id))
                else:
                    self.dynamic_getattr.append((ast.unparse(node), node.lineno))
            elif isinstance(target, ast.Name) and target.id in self.person_names and len(node.args) > 1:
                second = node.args[1]
                if isinstance(second, ast.Constant) and isinstance(second.value, str):
                    ctx = {"getattr": "load", "hasattr": "load", "setattr": "store", "delattr": "del"}[func.id]
                    self.person_use.append((second.value, ctx, node.lineno))
        elif isinstance(func, ast.Name) and func.id == "vars" and node.args and self._is_self(node.args[0]):
            self.refused.append(("`vars(self)` hides every attribute it touches", node.lineno))
        elif isinstance(func, ast.Name) and func.id == "once_on" and node.args and self._is_self(node.args[0]):
            # `once_on(self, "<name>", make)` keeps `<name>` on the instance: a touch of that attribute, read like getattr
            second = node.args[1] if len(node.args) > 1 else None
            if isinstance(second, ast.Constant) and isinstance(second.value, str):
                self.self_use.append((second.value, "load", node.lineno, "once_on"))
            else:
                self.refused.append(("`once_on(self, <non-literal>, ...)` hides the attribute it touches", node.lineno))
        if isinstance(func, ast.Attribute) and self._is_state(func.value):
            if func.attr in ("get", "setdefault", "pop", "__contains__", "__getitem__", "__setitem__", "__delitem__"):
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    self.state_keys.append((first.value, node.lineno))
                else:
                    self.state_keys.append((None, node.lineno))
            elif func.attr == "update":
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Dict) and all(isinstance(k, ast.Constant) for k in first.keys):
                    self.state_keys.extend((k.value, node.lineno) for k in first.keys)
                else:
                    self.state_keys.append((None, node.lineno))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if self._is_state(node.value):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.state_keys.append((key.value, node.lineno))
            else:
                self.state_keys.append((None, node.lineno))
        self.generic_visit(node)

    def visit_Compare(self, node):
        if len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)) and self._is_state(node.comparators[0]):
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                self.state_keys.append((node.left.value, node.lineno))
            else:
                self.state_keys.append((None, node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node):
        if self._is_self(node.value):
            self.refused.append(("`x = self` makes an alias, and everything through the alias is invisible", node.lineno))
        elif self._is_state(node.value):
            self.refused.append(("`x = self.state` makes an alias of the state, and its keys are invisible", node.lineno))
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.locals:
            self.names.add(node.id)


def class_uses_outside_functions(tree, cls_re) -> list:
    """[(class name as written, attr, line)] for every `<Class>.<attr>` / `<Class><Area>.<attr>` in module-level code and in
    class bodies (a function body is a Scan's; its decorators and defaults run at module level and are read here)."""
    out = []

    def look(node):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and cls_re.match(node.value.id):
            out.append((node.value.id, node.attr, node.lineno))
        walk(node)

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for expr in [*child.decorator_list, *child.args.defaults, *[d for d in child.args.kw_defaults if d]]:
                    look(expr)
            else:
                look(child)
    walk(tree)
    return out


def person_defined(mods: dict) -> set:
    """The attribute names the class `Person` itself defines (and the ones every Exception has)."""
    out = set(dir(Exception))
    for _stem, (_p, _t, tree) in mods.items():
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Person":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == "self":
                        out.add(sub.attr)
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out.add(sub.name)
    return out


def scans(mods: dict, fam: dict) -> list:
    """[(label, stem, Scan)] for every class member function (of the family's class), every module-level function and every
    method of the other classes (labelled by the class)."""
    out = []
    cls, cls_re = fam.get("class"), class_regex(fam)
    for stem, (_path, _text, tree) in mods.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((node.name, stem, Scan(node.name, node, class_member=False, cls_re=cls_re)))
            elif isinstance(node, ast.ClassDef):
                is_family_class = bool(cls_re and cls_re.match(node.name))
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        label = f"{cls}.{sub.name}" if is_family_class else node.name
                        out.append((label, stem, Scan(label, sub, class_member=is_family_class, cls_re=cls_re)))
    return out


# --- the map header ---------------------------------------------------------------------------------------------
def rank_of(mp: dict) -> dict:
    layers = mp.get("layers")
    if not isinstance(layers, list):
        return {}
    return {module: i for i, group in enumerate(layers) if isinstance(group, list) for module in group}


def header_problems(root: Path, mp: dict, label: str, file_name: str | None = None) -> list:
    """L10, first: the shape of the `family` header and of the optional header keys. A non-empty list means the map cannot be
    read as a family map, and analyse() then runs no other check of it. `file_name` (the map's file name, when it is a file)
    must be `<prefix without the trailing underscore>-layers.json`."""
    out = []
    fam = mp.get("family")
    if not isinstance(fam, dict):
        return [f"{label} has no `family` header object: add {{\"facade\": \"<stem>\", \"prefix\": \"<prefix>_\", "
                f"\"class\": \"<Class>\" or null, \"cut\": \"mixins\" or \"functions\", \"installed\": true or false}} "
                f"(the test reads every family fact from it)."]
    for key in ("facade", "prefix"):
        if not isinstance(fam.get(key), str) or not fam.get(key):
            out.append(f"{label}: family.{key} is {fam.get(key)!r}: expected a non-empty string.")
    if isinstance(fam.get("facade"), str) and fam["facade"] and not fam["facade"].isidentifier():
        out.append(f"{label}: family.facade is {fam['facade']!r}: expected a bare module stem (a name, no path or dot).")
    if isinstance(fam.get("prefix"), str) and fam.get("prefix") and not fam["prefix"].endswith("_"):
        out.append(f"{label}: family.prefix is {fam['prefix']!r}: expected the part prefix ending in `_` (e.g. `<name>_`).")
    elif isinstance(fam.get("prefix"), str) and fam.get("prefix") and file_name is not None \
            and file_name != fam["prefix"][:-1] + "-layers.json":
        out.append(f"{label}: the map file is named {file_name!r}: expected {fam['prefix'][:-1] + '-layers.json'!r} "
                   f"(`<prefix without the trailing underscore>-layers.json`).")
    if fam.get("class") is not None and (not isinstance(fam["class"], str) or not fam["class"].isidentifier()):
        out.append(f"{label}: family.class is {fam['class']!r}: expected a class name or null.")
    if fam.get("cut") not in CUTS:
        out.append(f"{label}: family.cut is {fam.get('cut')!r}: expected one of {list(CUTS)}.")
    elif fam["cut"] == "mixins" and not fam.get("class"):
        out.append(f"{label}: family.cut is `mixins` but family.class is null: a mixin cut assembles a class; name it, or use "
                   f"`functions`.")
    if "class" in fam and fam["class"] is None:
        for table in CLASS_TABLES:
            if table in mp:
                out.append(f"{label}: family.class is null but the map carries the class table `{table}`: a family with no "
                           f"class has no `self` to touch; delete the table, or name the class.")
    if not isinstance(fam.get("installed"), bool):
        out.append(f"{label}: family.installed is {fam.get('installed')!r}: expected true or false.")
    layers = mp.get("layers")
    if not (isinstance(layers, list) and all(isinstance(g, list) and all(isinstance(m, str) for m in g) for g in layers)):
        out.append(f"{label}: `layers` is not a list of lists of module stems: expected index = rank.")
    else:
        flat = [m for g in layers for m in g]
        for stem in sorted({m for m in flat if flat.count(m) > 1}):
            out.append(f"{label}: `layers` lists `{stem}` more than once: a module has one rank; delete the extra entry.")
    rank = rank_of(mp)
    if isinstance(fam.get("facade"), str) and fam["facade"].isidentifier() \
            and not (Path(root) / "scripts" / (fam["facade"] + ".py")).is_file():
        out.append(f"{label}: family.facade `{fam['facade']}` has no scripts/{fam['facade']}.py: expected the family's original file.")
    if "l8_skip" in mp:
        skip = mp["l8_skip"]
        if not (isinstance(skip, list) and all(isinstance(f, str) and f.endswith(".py") and "/" not in f and "\\" not in f
                                               for f in skip)):
            out.append(f"{label}: `l8_skip` is {skip!r}: expected a list of test file names (`<name>.py`, no path).")
    if "setup_import" in mp and (not isinstance(mp["setup_import"], str) or not mp["setup_import"].isidentifier()):
        out.append(f"{label}: `setup_import` is {mp['setup_import']!r}: expected one module stem.")
    if "module_statements" in mp:
        stmts = mp["module_statements"]
        if not isinstance(stmts, dict):
            out.append(f"{label}: `module_statements` is not an object: expected {{statement first line: home in `layers`}}.")
        else:
            for line, home in stmts.items():
                if home not in rank:
                    out.append(f"{label}: module_statements row {line!r} names the home {home!r}, which is not in `layers`: "
                               f"expected a module of the layer list.")
    if "allowed_importers" in mp:
        rows = mp["allowed_importers"]
        parts = {p.stem for p in family_paths(root, fam, {r.get("module") for r in mp.get("not_driver", []) if isinstance(r, dict)})[1:]} \
            if isinstance(fam.get("facade"), str) and isinstance(fam.get("prefix"), str) else set()
        if not isinstance(rows, list):
            out.append(f"{label}: `allowed_importers` is not a list: expected [{{importer, part, reason}}].")
        else:
            for i, row in enumerate(rows):
                if not isinstance(row, dict) or set(row) != {"importer", "part", "reason"}:
                    out.append(f"{label}: allowed_importers[{i}] is {row!r}: expected exactly the keys importer, part, reason.")
                    continue
                if not (isinstance(row["importer"], str) and row["importer"].endswith(".py") and "/" not in row["importer"]):
                    out.append(f"{label}: allowed_importers[{i}].importer is {row['importer']!r}: expected a script file name "
                               f"in scripts/ (`<name>.py`).")
                if row["part"] not in parts:
                    out.append(f"{label}: allowed_importers[{i}].part is {row['part']!r}: expected a part file stem of the "
                               f"family, one of {sorted(parts)}.")
                if not isinstance(row["reason"], str) or not row["reason"].strip():
                    out.append(f"{label}: allowed_importers[{i}] has no reason: say why the outside script imports the part.")
    return out


# --- L11, L12 helpers -------------------------------------------------------------------------------------------
def _imports_of(tree):
    """[(module root, line)] for every import in a tree, at any depth, and every literal `import_module("x")` / `__import__("x")`."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name.split(".")[0], node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.append((node.module.split(".")[0], node.lineno))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)                 and isinstance(node.args[0].value, str):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__"):
                out.append((node.args[0].value.split(".")[0], node.lineno))
    return out


# What the checks read of the rig's scripts and tests is derived ONCE per source text (the key is the text, so a fixture that
# changes a file gets its own entry) and the tree is dropped at once: the scripts are 17 MB and the tests 28 MB of source.
_SCRIPT_IMPORTS: dict = {}
_MENTIONS: dict = {}


def _parse(text: str, filename: str = "<unknown>"):
    """ast.parse with the cycle collector paused: building a tree allocates millions of container nodes and the collector,
    woken by every few thousand of them, walks all live ones again and again (half of the parse time on the rig's tests)."""
    was = gc.isenabled()
    gc.disable()
    try:
        return ast.parse(text, filename)
    finally:
        if was:
            gc.enable()


def _script_imports(path: Path):
    """(imports, None) of a script, read as Python reads it (a BOM is allowed) - `_imports_of` of its tree - or (None, the
    reason) when it cannot be parsed."""
    try:
        text = path.read_text(encoding="utf-8-sig")
        key = (str(path), text)
        if key not in _SCRIPT_IMPORTS:
            _SCRIPT_IMPORTS[key] = _imports_of(_parse(text, str(path)))
        return _SCRIPT_IMPORTS[key], None
    except (SyntaxError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _install_calls(tree) -> list:
    """Every call of `module_facade.install` however it is reached: `module_facade.install(...)`, `<alias>.install(...)` after
    `import module_facade as <alias>`, `install(...)` / `<alias>(...)` after `from module_facade import install [as <alias>]`
    (or `import *`), and `getattr(<module or alias>, "install")(...)`."""
    modules, bare = {"module_facade"}, set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            modules.update(a.asname for a in n.names if a.name == "module_facade" and a.asname)
        elif isinstance(n, ast.ImportFrom) and n.module == "module_facade" and not n.level:
            bare.update((a.asname or a.name) if a.name != "*" else "install" for a in n.names if a.name in ("install", "*"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "install" and isinstance(func.value, ast.Name) \
                and func.value.id in modules:
            out.append(node)
        elif isinstance(func, ast.Name) and func.id in bare:
            out.append(node)
        elif isinstance(func, ast.Call) and isinstance(func.func, ast.Name) and func.func.id == "getattr" \
                and len(func.args) > 1 and isinstance(func.args[0], ast.Name) and func.args[0].id in modules \
                and isinstance(func.args[1], ast.Constant) and func.args[1].value == "install":
            out.append(node)
    return out


def facade_importer_problems(root: Path, facades: set) -> list:
    """Every package script that imports `module_facade` must be the facade of a discovered map (the facade stems are
    `facades`); `module_facade.py` itself is excepted, and `scripts/tests/` is not in the glob. A script that cannot be parsed
    is reported."""
    out = []
    for path in sorted((Path(root) / "scripts").glob("*.py")):
        if path.stem == "module_facade" or path.stem in facades:
            continue
        found, why = _script_imports(path)
        if found is None:
            out.append(f"scripts/{path.name} cannot be parsed ({why}): fix the file; an unreadable script hides whether it "
                       f"installs a facade.")
        elif any(module == "module_facade" for module, _line in found):
            out.append(f"scripts/{path.name} imports module_facade but is the facade of no family map: add "
                       f"fixtures/<prefix>-layers.json for it (its `family.facade` is `{path.stem}`), or stop installing it "
                       f"(a misnamed map is invisible to the glob).")
    return out


def l11_problems(root: Path, mp: dict, fam: dict, mods: dict, rank: dict, rows: dict) -> tuple:
    """L11: who may import a part, and the facade's own shape. Returns (problems, informational lines)."""
    probs, notes = [], []
    facade = fam["facade"]
    part_stems = {s for s in mods if s != facade} | {m for m in rank if m != facade}
    allowed = {(r.get("importer"), r.get("part")): r for r in mp.get("allowed_importers", [])}
    matched = set()
    scripts = Path(root) / "scripts"
    family_files = {mods[s][0].name for s in mods}
    for path in sorted(scripts.glob("*.py")):
        if path.name in family_files:
            continue
        found, why = _script_imports(path)
        if found is None:
            probs.append(f"scripts/{path.name} cannot be parsed ({why}): fix the file; an unreadable script may import a "
                         f"part, and the check cannot tell.")
            continue
        for module, line in found:
            if module in part_stems:
                if (path.name, module) in allowed:
                    matched.add((path.name, module))
                else:
                    probs.append(f"scripts/{path.name}:{line} imports the family part `{module}`: a part is reached through "
                                 f"the facade `{facade}` only (AR-13). Import the name from `{facade}`, or add an "
                                 f"`allowed_importers` row {{importer: {path.name!r}, part: {module!r}, reason: <why>}}.")
    for key, row in sorted(allowed.items()):
        if key not in matched:
            probs.append(f"allowed_importers row {key[0]} -> {key[1]} matches no import in scripts/: delete the row (the list "
                         f"holds the importers the tree has, no others).")
    tree = mods[facade][2]
    calls = _install_calls(tree)
    if fam["installed"] is False:
        for call in calls:
            probs.append(f"{facade}.py:{call.lineno} calls module_facade.install but family.installed is false: the flag and "
                         f"the facade must agree; set `installed` true in the commit that installs the facade.")
        for module, line in _imports_of(tree):
            if module == "module_facade":
                probs.append(f"{facade}.py:{line} imports module_facade but family.installed is false: the flag and the "
                             f"facade must agree (an aliased or getattr call of install is not followed); set `installed` "
                             f"true in the commit that installs the facade.")
        notes.append(f"L11 (b): not run for {facade}: family.installed is false (the facade is not installed yet)")
        return probs, notes
    parts = sorted((s for s in rank if s != facade), key=lambda s: rank[s])
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for part in parts:
        if not (scripts / (part + ".py")).is_file():
            probs.append(f"family part `{part}` named in `layers` has no scripts/{part}.py: family.installed is true, so every "
                         f"part must exist.")
        elif part not in imported:
            probs.append(f"{facade}.py has no literal `import {part}`: the facade imports every part by a literal import (the "
                         f"closure walk follows literal imports only).")
    if len(calls) != 1:
        probs.append(f"{facade}.py calls module_facade.install {len(calls)} times: expected exactly one call "
                     f"`module_facade.install(__name__, [<parts, low rank first>])`.")
    else:
        args = calls[0].args
        top_level = any(isinstance(n, ast.Expr) and n.value is calls[0] for n in tree.body)
        if not top_level:
            probs.append(f"{facade}.py:{calls[0].lineno} calls module_facade.install below module level (inside a function, "
                         f"branch or block): expected the call as a statement of the module body, so it always runs.")
        if not (args and isinstance(args[0], ast.Name) and args[0].id == "__name__"):
            probs.append(f"{facade}.py:{calls[0].lineno} passes install a first argument that is not `__name__`: expected "
                         f"`module_facade.install(__name__, [...])` (a literal name breaks under `__main__`).")
        listed = args[1] if len(args) > 1 else None
        if not (isinstance(listed, ast.List) and all(isinstance(e, ast.Name) for e in listed.elts)):
            probs.append(f"{facade}.py:{calls[0].lineno} passes install a second argument that is not a literal list of part "
                         f"names: expected `[<part>, ...]`, low rank first.")
        else:
            names = [e.id for e in listed.elts]
            ranks = [rank.get(n, -1) for n in names]
            if sorted(names) != sorted(parts) or ranks != sorted(ranks):
                probs.append(f"{facade}.py:{calls[0].lineno} installs {names}: expected exactly the parts {parts}, in rank "
                             f"order (low first).")
    for name, found in sorted(definitions(mods, fam).items()):
        for item in found:
            home = rows.get(name, {}).get("home")
            if item["stem"] == facade and home in rank and home != facade:
                probs.append(f"{facade}.py:{item['line']} defines `{name}`, whose home is the part `{home}`: the facade "
                             f"defines no name that lives in a part; move the definition to `{home}`.")
    return probs, notes


def l12_class_use(fam: dict, written: str, attr: str, members: set, homes: dict, rank: dict, in_part: bool = False) -> tuple:
    """Resolve `<written>.<attr>` by class name. Returns (resolved: bool, problem or None). Resolved means the access names
    the assembled class (in the facade only: a part cannot import the facade's class), or exactly the mixin class of the
    member's home."""
    cls = fam["class"]
    if written == cls:
        if in_part:
            mixin = mixin_class(fam, homes.get(f"{cls}.{attr}"))
            want = f"`{mixin}.{attr}`" if mixin else f"the mixin class of `{attr}`'s home (`{cls}<Area>.{attr}`)"
            return False, (f"`{written}.{attr}` inside a part: the assembled class `{cls}` is not importable there (it is "
                           f"built from the parts): expected {want}, or pass what is needed in.")
        return True, None
    known = {mixin_class(fam, m) for m in rank} - {None}
    if written not in known:
        return False, (f"`{written}.{attr}`: `{written}` is no class of the family (the assembled class is `{cls}`, the mixin "
                       f"classes are {sorted(known)}): expected one of them.")
    home = homes.get(f"{cls}.{attr}")
    if attr in members and home in rank and mixin_class(fam, home) != written:
        want = mixin_class(fam, home) or cls
        return False, (f"`{written}.{attr}` but `{attr}` is homed in `{home}`: expected `{want}.{attr}` (a mixin is named only "
                       f"for a member of its own home).")
    return True, None


# --- the checks ---------------------------------------------------------------------------------------------------
def analyse(root: Path, mp: dict, tests_dir: Path | None = None, map_name: str = "the map",
            file_name: str | None = None) -> dict:
    """{check id: [problem text]} plus `info` (counts and informational lines). Every problem names the thing, what was
    expected, and the door. A malformed header (L10) returns at once: `info["skipped"]` says so and no other check ran.
    `file_name` is the map's file name, when the map is a file (L10 checks it against the prefix)."""
    probs = {k: [] for k in ALL_CHECKS}
    probs["L10"] = header_problems(root, mp, map_name, file_name)
    if probs["L10"]:
        return {"problems": probs, "info": {"skipped": "the `family` header or a header key is malformed (L10)", "notes": []}}
    fam = mp["family"]
    cls = fam["class"]
    facade = fam["facade"]
    exempt = {row["module"] for row in mp.get("not_driver", [])}
    mods = read_modules(root, fam, exempt)
    defs = definitions(mods, fam)
    rank = rank_of(mp)
    notes = []
    for path in sorted((root / "scripts").glob(fam["prefix"] + "*.py")):
        if path.stem not in rank and path.stem not in exempt:
            probs["L1"].append(f"scripts/{path.name} is a `{fam['prefix']}*` module with no layer: add `{path.stem}` to "
                               f"`layers` of {map_name} (a part outside the map is invisible to every check), or to "
                               f"`not_driver` with a reason if it is not part of the family.")
    for row in mp.get("not_driver", []):
        if not str(row.get("reason") or "").strip():
            probs["L10"].append(f"not_driver row {row.get('module')!r} has no reason: say why it is not part of the family.")
    rows = {}
    for row in mp.get("names", []):
        if row["name"] in rows:
            probs["L10"].append(f"{map_name} has two rows for `{row['name']}`: a name has one row; delete one.")
        rows[row["name"]] = row
    homes = {name: row.get("home") for name, row in rows.items()}
    modules_present = set(mods)

    # L10 well-formed
    for name, row in rows.items():
        if not row.get("home"):
            probs["L10"].append(f"row `{name}` has no home; homes are a judgment (the family's assignment rules), never "
                                f"defaulted: choose one of {sorted(rank)}.")
        elif row["home"] not in rank:
            probs["L10"].append(f"row `{name}` names the home `{row['home']}`, which is not in `layers` {sorted(rank)}: "
                                f"expected a module of the layer list.")
    for table, key in (("attributes", "name"), ("state_keys", "key")):
        seen = set()
        for row in mp.get(table, []):
            if row[key] in seen:
                probs["L10"].append(f"`{table}` has two rows for `{row[key]}`: delete one.")
            seen.add(row[key])
            if row.get("owner") not in rank:
                probs["L10"].append(f"`{table}` row `{row[key]}` has owner {row.get('owner')!r}, not a module of `layers`: "
                                    f"expected one of {sorted(rank)}.")
    for row in mp.get("exceptions", []):
        if not str(row.get("reason") or "").strip():
            probs["L10"].append(f"exceptions row {row.get('from')} -> {row.get('to')} has no reason: say why the upward "
                                f"edge exists and which node removes it.")

    # L1 census, both directions; L2 single definition and placement
    for name, found in sorted(defs.items()):
        first = found[0]
        place = f"{mods[first['stem']][0].name}:{first['line']}"
        if name not in rows:
            kind_hint = first["kind"]
            probs["L1"].append(
                f"{place} defines `{name}`; {map_name} has no row for it. Add "
                f"{{\"name\": \"{name}\", \"kind\": \"{kind_hint}\", \"home\": <module>}}, choosing the home by the family's "
                f"assignment rules.")
        elif rows[name].get("kind") != first["kind"]:
            probs["L1"].append(f"{place}: `{name}` is a {first['kind']} but its row says {rows[name].get('kind')!r}: "
                               f"fix the row's kind.")
        if len(found) > 1:
            where = ", ".join(f"{mods[f['stem']][0].name}:{f['line']}" for f in found)
            probs["L2"].append(f"`{name}` is defined {len(found)} times ({where}): a name has one home.")
        elif name in rows and rows[name].get("home") in rank:
            home = rows[name]["home"]
            if home in modules_present and home != first["stem"]:
                probs["L2"].append(f"{place} defines `{name}` but its home {home} exists and is the place for it "
                                   f"({mods[home][0].name}): move it there, or change the row's home.")
            if home not in modules_present and first["stem"] != facade:
                probs["L2"].append(f"{place} defines `{name}` with home {home}, a module that does not exist: expected the "
                                   f"definition in {facade}.py until {home}.py is made.")
    for name in sorted(rows):
        if name not in defs:
            probs["L1"].append(f"row `{name}` names nothing in the family: delete it, or rename it if the function was "
                               f"renamed.")

    # L3 .. L7 over the scans. A check over an absent driver-only table is not run for the family (one informational line).
    absent = sorted(t for t in OPTIONAL_TABLES if t not in mp)
    if absent:
        notes.append(f"{facade}: no {', '.join('`' + t + '`' for t in absent)} table(s): the checks over them are not run "
                     f"({', '.join(sorted({OPTIONAL_TABLES[t] for t in absent}))} in part)")
    if not cls:
        notes.append(f"{facade}: family.class is null: the class clauses of L3 and L12 are not run")
    members = {n.split(".", 1)[1] for n in defs if cls and n.startswith(cls + ".")}
    attrs = {row["name"]: row for row in mp.get("attributes", [])}
    state_rows = {row["key"]: row for row in mp.get("state_keys", [])}
    dyn_rows = {row["function"]: row for row in mp.get("dynamic_state_keys", [])}
    sd_rows = [row for row in mp.get("string_dispatch", [])]
    adhoc_rows = {(row["on"], row["name"]): row for row in mp.get("adhoc_attributes", [])}
    all_scans = scans(mods, fam)
    person_attrs = person_defined(mods)
    attr_seen: dict = {}
    attr_init: dict = {}
    state_seen: dict = {}
    dyn_sites: dict = {}
    dispatch_sites: dict = {}
    adhoc_seen: dict = {}
    edges = set()
    where = {stem: mods[stem][0].name for stem in mods}
    for label, stem, scan in all_scans:
        site = where[stem]
        caller_home = homes.get(label) if label in rows else None
        for message, line in scan.refused:
            probs["L3"].append(f"{site}:{line} in `{label}`: {message}. Expected plain `self.<name>` accesses; rewrite "
                               f"the line so the access is visible to the map.")
        # `<Class>.<m>` by class name: resolved against the member's home (L12); a member goes on as a call edge
        for written, attr, line in scan.class_use:
            resolved, problem = l12_class_use(fam, written, attr, members, homes, rank, in_part=stem != facade)
            if not resolved:
                probs["L12"].append(f"{site}:{line} in `{label}`: {problem}")
            if attr in members:
                if resolved:
                    target = f"{cls}.{attr}"
                    edges.add((label, target, "call", caller_home, homes.get(target), f"{site}:{line}"))
            elif not (attr.startswith("__") and attr.endswith("__")):
                probs["L3"].append(f"{site}:{line} in `{label}` reads `{written}.{attr}`; `{attr}` is not a member of the "
                                   f"{cls} class. Expected a member in the census.")
        for attr, ctx, line, how in scan.self_use:
            if not scan.class_member and how == "self":
                continue
            if attr in members:
                target = f"{cls}.{attr}"
                edges.add((label, target, "call", caller_home, homes.get(target), f"{site}:{line}"))
                continue
            if attr.startswith("__") and attr.endswith("__"):
                continue
            if how == "type(self)":
                probs["L3"].append(f"{site}:{line} in `{label}` reads `{how}.{attr}`; `{attr}` is not a member of the {cls} "
                                   f"class. Expected a member in the census.")
                continue
            if "attributes" not in mp:
                continue
            attr_seen.setdefault(attr, []).append((label, f"{site}:{line}"))
            if label == f"{cls}.__init__" and ctx == "store":
                attr_init[attr] = True
            if attr not in attrs:
                verb = {"load": "reads", "store": "writes", "del": "deletes"}[ctx]
                probs["L3"].append(
                    f"{site}:{line} in `{label}` {verb} `self.{attr}`; nothing owns `{attr}` (not a member, not in "
                    f"`attributes`). Add {{\"name\": \"{attr}\", \"owner\": <the lowest module that touches it>}}.")
            else:
                owner = attrs[attr].get("owner")
                edges.add((label, "attribute:" + attr, "attr", caller_home, owner, f"{site}:{line}"))
        for expr, line in scan.dynamic_getattr:
            dispatch_sites.setdefault(label, []).append((expr, line))
        for key, line in scan.state_keys:
            if key is None:
                dyn_sites.setdefault(label, []).append(line)
            else:
                state_seen.setdefault(key, []).append((label, f"{site}:{line}"))
                if key in state_rows:
                    edges.add((label, "state:" + key, "state", caller_home, state_rows[key].get("owner"), f"{site}:{line}"))
        for attr, ctx, line in scan.person_use:
            if attr in person_attrs:
                continue
            role = "writers" if ctx in ("store", "del") else "readers"
            adhoc_seen.setdefault(attr, {"writers": set(), "readers": set()})[role].add(label)
        if label in rows or (cls and label.startswith(cls + ".")):
            for name in sorted(scan.names):
                if name in rows and name != label and name != cls and not (cls and name.startswith(cls + ".")):
                    edges.add((label, name, "name", caller_home, homes.get(name), f"{site}"))

    # L12 over module-level and class-body code (a function body is a Scan's, above)
    if cls:
        for stem, (path, _t, tree) in mods.items():
            for written, attr, line in class_uses_outside_functions(tree, class_regex(fam)):
                resolved, problem = l12_class_use(fam, written, attr, members, homes, rank, in_part=stem != facade)
                if not resolved:
                    probs["L12"].append(f"{path.name}:{line} in module-level or class-body code: {problem}")

    # L3 closing: dispatch tables, stale rows, attributes both directions
    module_literals = {}
    for stem, (_p, _t, tree) in mods.items():
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for name in _targets(node):
                    try:
                        module_literals[name] = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        pass
    rows_by_function = {}
    for row in sd_rows:
        if "function" in row:
            rows_by_function.setdefault(row["function"], []).append(row)
    if "string_dispatch" not in mp:
        dispatch_sites = {}                                 # the table is absent: the check is not run (see the note above)
    for function, sites in sorted(dispatch_sites.items()):
        if function not in rows_by_function:
            expr, line = sites[0]
            probs["L3"].append(f"{where.get(facade, facade + '.py')}:{line} in `{function}` calls `{expr}`, a name "
                               f"chosen at run time; add a `string_dispatch` row for `{function}` listing every name it can "
                               f"take.")
    for function, found_rows in sorted(rows_by_function.items()):
        if function not in dispatch_sites:
            probs["L3"].append(f"string_dispatch row for `{function}` matches no getattr(self, <non-literal>) in it: delete "
                               f"the row.")
        for row in found_rows:
            names = list(row.get("candidates") or [])
            for part in re.findall(r"(\w+)\[(\d+)\]", row.get("candidates_from", "")):
                table, column = part[0], int(part[1])
                if table not in module_literals:
                    probs["L3"].append(f"string_dispatch row for `{function}` reads {table}[{column}], and {table} is not "
                                       f"a module-level literal: expected a literal table the test can read.")
                    continue
                names.extend(f"{cls}.{entry[column]}" for entry in module_literals[table])
            for cand in names:
                if cand not in defs:
                    probs["L3"].append(f"string_dispatch row for `{function}` lists `{cand}`, which is not defined: "
                                       f"delete it from the row, or define it.")
                else:                                       # a name chosen at run time is still a call: it has a direction
                    edges.add((function, cand, "call", homes.get(function), homes.get(cand), f"{where.get(facade, '')}"))
    for row in sd_rows:
        if "function" not in row and not row.get("planned"):
            probs["L10"].append(f"string_dispatch row {row.get('name')!r} names no function and is not `planned`: "
                                f"expected a function, or planned: <node>.")
    for attr in sorted(attrs):
        if attr not in attr_seen:
            probs["L3"].append(f"`attributes` row `{attr}` is not touched through `self` anywhere: delete it, or rename it "
                               f"if the attribute was renamed.")
        elif bool(attrs[attr].get("set_in_init")) != bool(attr_init.get(attr)):
            probs["L3"].append(f"`attributes` row `{attr}` says set_in_init={bool(attrs[attr].get('set_in_init'))}, but "
                               f"{cls}.__init__ {'does' if attr_init.get(attr) else 'does not'} assign it: fix the row "
                               f"(an attribute absent from __init__ is a hazard the row names).")

    # L4 ad-hoc attributes and state keys
    for attr, roles in sorted(adhoc_seen.items() if "adhoc_attributes" in mp else []):
        row = adhoc_rows.get(("Person", attr))
        if row is None:
            probs["L4"].append(
                f"`person.{attr}` is used (writers {sorted(roles['writers'])}, readers {sorted(roles['readers'])}) but "
                f"Person does not define it and `adhoc_attributes` has no row: add {{\"on\": \"Person\", \"name\": "
                f"\"{attr}\", \"writers\": [...], \"readers\": [...]}}.")
        else:
            if set(row.get("writers", [])) != roles["writers"] or set(row.get("readers", [])) != roles["readers"]:
                probs["L4"].append(f"adhoc attribute `Person.{attr}`: the row says writers {sorted(row.get('writers', []))} "
                                   f"readers {sorted(row.get('readers', []))}, the source says writers "
                                   f"{sorted(roles['writers'])} readers {sorted(roles['readers'])}: update the row.")
    for (on, attr), row in sorted(adhoc_rows.items()):
        if attr not in adhoc_seen:
            probs["L4"].append(f"`adhoc_attributes` row `{on}.{attr}` is used nowhere: delete it.")
    dyn_keys = set()
    for function, row in dyn_rows.items():
        dyn_keys.update(row.get("keys", []))
        if function not in dyn_sites:
            probs["L4"].append(f"`dynamic_state_keys` row for `{function}` matches no non-literal state key site in it: "
                               f"delete the row.")
    for function, lines in sorted(dyn_sites.items() if "dynamic_state_keys" in mp else []):
        if function not in dyn_rows:
            probs["L4"].append(f"{where.get(facade, facade + '.py')}:{lines[0]} in `{function}` uses a state key chosen "
                               f"at run time; add a `dynamic_state_keys` row for it listing every key it can take.")
    for key, seen_at in sorted(state_seen.items() if "state_keys" in mp else []):
        if key not in state_rows:
            label, place = seen_at[0]
            probs["L4"].append(f"{place} in `{label}` uses state key `{key}`; `state_keys` has no row: add "
                               f"{{\"key\": \"{key}\", \"owner\": <the lowest module that touches it>}}.")
    for key in sorted(state_rows):
        if key not in state_seen and key not in dyn_keys:
            probs["L4"].append(f"`state_keys` row `{key}` is used nowhere in the family: delete it, or rename it if the key "
                               f"was renamed.")

    # L5 / L7 direction against the exceptions list
    exc = {(r.get("from"), r.get("to"), r.get("kind")) for r in mp.get("exceptions", [])}
    upward = set()
    collapsed = {}
    for caller, target, kind, caller_home, target_home, place in sorted(edges):
        collapsed.setdefault((caller, target, kind), (caller_home, target_home, place))
    for (caller, target, kind), (caller_home, target_home, place) in sorted(collapsed.items()):
        if caller_home not in rank or target_home not in rank:
            continue
        if rank[target_home] > rank[caller_home]:
            upward.add((caller, target, kind))
            if (caller, target, kind) in exc:
                continue
            what = {"call": "calls", "attr": "touches the attribute", "state": "touches the state key", "name": "uses"}[kind]
            if kind in ("attr", "state"):
                probs["L7"].append(
                    f"{place}: `{caller}` ({caller_home}) {what} `{target.split(':', 1)[-1]}` owned by {target_home}: its "
                    f"owner must be at or below every accessor's home. Move the ownership down, or add it to `exceptions` "
                    f"with a reason; the list only shrinks.")
            else:
                probs["L5"].append(
                    f"{place}: `{caller}` ({caller_home}) {what} `{target}` ({target_home}), a higher layer: a lower layer "
                    f"may not call a higher one. Move the call behind a hook (node N4), or add it to `exceptions` with a "
                    f"reason; the list only shrinks.")
    for row in mp.get("exceptions", []):
        key = (row.get("from"), row.get("to"), row.get("kind"))
        if key not in upward:
            probs["L5"].append(f"exceptions row {key[0]} -> {key[1]} ({key[2]}) no longer occurs as an upward edge: delete "
                               f"the row (the list is shrink-only).")
    probs["L5"].extend(pin_problems(mp.get("exceptions", []), pinned_for(facade), stale=False))

    # L6 import direction: a module never imports a higher-ranked one. L12, one rule for both cuts (P31): a part imports another
    # part of its family only when that part is STRICTLY lower-ranked (or is `<prefix>base`), so an equal-rank import, a
    # two-way cycle included, is refused. Every import form `_imports_of` reads counts (import_module and __import__ too).
    base = fam["prefix"] + "base"
    for stem, (path, _text, tree) in mods.items():
        if stem not in rank:
            continue
        for module, line in _imports_of(tree):
            if module in rank and rank[module] > rank[stem]:
                probs["L6"].append(f"{path.name}:{line} imports {module}, a higher layer: a lower module never "
                                   f"imports a higher one. Move the shared name down, or pass it in.")
            elif module in rank and module != stem and module != base and rank[module] == rank[stem]:
                probs["L12"].append(f"{path.name}:{line} imports {module}, a part of the same rank: a part imports only a "
                                    f"strictly lower-ranked part or `{base}`. Move the shared name down, or pass it in.")

    # L11 the facade and the importers of the parts
    l11, l11_notes = l11_problems(root, mp, fam, mods, rank, rows)
    probs["L11"].extend(l11)
    notes.extend(l11_notes)

    # L8 source readers: every occurrence of a literal file name of the family set in the rig's tests. EVERY name counts, with
    # no temporal rule (critic M8): a test that pins a part's file name needs a row in `source_readers` / `source_mentions`.
    tests = tests_dir if tests_dir is not None else root / "scripts" / "tests"
    family_file_names = [mods[stem][0].name for stem in mods]
    skip = L8_SKIP_ALL | set(mp.get("l8_skip", []))
    census_l8 = {}
    if tests.is_dir():
        for path in sorted(tests.glob("*.py")):
            if path.name in skip:
                continue
            try:
                table = _mention_table(path.read_text(encoding="utf-8"), family_file_names)
            except SyntaxError:
                continue
            for fname in family_file_names:
                for function, line, count in _literal_mentions(table, fname):
                    census_l8.setdefault((path.name, function), []).append((line, count))
    readers = {(r["file"], r["function"]): r for r in mp.get("source_readers", [])}
    mentions = {}
    for r in mp.get("source_mentions", []):
        mentions[(r["file"], r.get("function", ""))] = r
    for (file, function), found in sorted(census_l8.items()):
        total = sum(c for _l, c in found)
        key = (file, function)
        declared = 0
        if key in readers:
            declared += readers[key].get("count", 0)
        if key in mentions:
            declared += mentions[key].get("count", 0)
        if declared != total:
            first_line = found[0][0]
            kind = "reads the family's source" if key not in mentions else "mentions the family"
            probs["L8"].append(
                f"{file}:{first_line}, in `{function}`, {kind} ({total} occurrence(s) of a family file name literal) and the "
                f"map declares {declared}: add or fix a row in `source_readers` (a source-text read, with the names it pins, "
                f"so the node that moves them owns this test, t-301 section 0b F3) or in `source_mentions` (command text).")
    for (file, function), row in sorted({**readers, **mentions}.items()):
        if (file, function) not in census_l8:
            probs["L8"].append(f"the map has a row for {file} in `{function}` but that function holds no literal file name of "
                               f"the family ({', '.join(family_file_names)}): delete the row.")
    for (file, function), row in sorted(readers.items()):
        path = tests / file
        if path.is_file():
            tree = _parse(path.read_text(encoding="utf-8"))
            if not _function_reads(tree, function):
                probs["L8"].append(f"source_readers row {file}::{function} names a function with no read_text/read_bytes: "
                                   f"a row for command text belongs in `source_mentions`.")

    # L9 stdout writers
    allowed = {(w["file"], w.get("function", "")) for w in mp.get("stdout_writers", [])}
    for stem, (path, _text, tree) in mods.items():
        for label, line, what in (_stdout_writes(tree, fam) if "stdout_writers" in mp else []):
            if (path.name, label) not in allowed:
                probs["L9"].append(f"{path.name}:{line} in `{label}` {what}; the family's recorder reads its output through "
                                   f"print() only, so this line is invisible to it. Use print(), or add the site to "
                                   f"`stdout_writers`.")
    info = {"notes": notes, "skipped": None, "family": fam, "names": len(defs), "files": sorted(where.values()), "members": len(members), "attributes": len(attr_seen),
            "state_keys": len(state_seen), "dynamic_state_sites": len(dyn_sites),
            "adhoc": len(adhoc_seen), "edges": len(edges), "upward": len(upward), "l8_sites": sum(
                len(v) for v in census_l8.values()),
            "state_seen": sorted(state_seen), "state_users": {k: sorted({l for l, _ in v}) for k, v in state_seen.items()},
            "attr_seen": {a: sorted({l for l, _ in v}) for a, v in attr_seen.items()},
            "adhoc_seen": {a: {r: sorted(s) for r, s in roles.items()} for a, roles in adhoc_seen.items()},
            "upward_edges": sorted(upward), "defs": defs, "dyn_sites": dyn_sites,
            "dispatch_sites": {k: [e for e, _ in v] for k, v in dispatch_sites.items()}, "census_l8": census_l8,
            "attr_init": attr_init}
    return {"problems": probs, "info": info}


def _string_table(tree) -> list:
    """[(enclosing def name, line, value)] for every non-docstring string constant of a tree, in walk order: ONE walk of the
    tree, however many needles are then looked for (the rig's tests are about 800 files, the family about 17 names)."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(
                    body[0].value.value, str):
                docstrings.add(id(body[0].value))
    out = []

    def walk(node, function):
        for child in ast.iter_child_nodes(node):
            fn = function
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = child.name
            if isinstance(child, ast.Constant) and isinstance(child.value, str) and id(child) not in docstrings:
                out.append((fn, child.lineno, child.value))
            walk(child, fn)
    walk(tree, "<module>")
    return out


def _literal_mentions(table: list, needle: str):
    """[(enclosing def name, line, occurrences)] for each non-docstring string constant of `table` that holds `needle`."""
    return [(fn, line, value.count(needle)) for fn, line, value in table if needle in value]


def _mention_table(text: str, needles: list) -> list:
    """`_string_table` of the tree of `text`, built only when some string constant of it holds a needle (one flat walk says
    so; a tree with none has no mention to report, docstring or not), kept per (text, needles). Raises SyntaxError."""
    key = (text, tuple(needles))
    if key not in _MENTIONS:
        tree = _parse(text)
        found = re.compile("|".join(re.escape(x) for x in needles)).search if needles else (lambda _v: None)
        hit = any(type(n) is ast.Constant and type(n.value) is str and found(n.value) for n in ast.walk(tree))
        _MENTIONS[key] = _string_table(tree) if hit else []
    return _MENTIONS[key]


def _function_reads(tree, function: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and sub.attr in ("read_text", "read_bytes"):
                    return True
                if isinstance(sub, ast.Name) and sub.id == "open":
                    return True
    return False


def _stdout_writes(tree, fam: dict):
    out = []
    cls_re = class_regex(fam)

    def walk(node, label):
        for child in ast.iter_child_nodes(node):
            lab = label
            if isinstance(child, ast.ClassDef):
                lab = (fam["class"] if cls_re and cls_re.match(child.name) else child.name) + "."
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lab = (label + child.name) if label.endswith(".") else child.name
            if isinstance(child, ast.Call):
                func = child.func
                if (isinstance(func, ast.Attribute) and func.attr == "write" and isinstance(func.value, ast.Attribute)
                        and func.value.attr in ("stdout", "stderr") and isinstance(func.value.value, ast.Name)
                        and func.value.value.id == "sys"):
                    out.append((lab, child.lineno, f"writes to sys.{func.value.attr} directly"))
                if isinstance(func, ast.Name) and func.id == "print":
                    for kw in child.keywords:
                        if kw.arg == "file" and not (isinstance(kw.value, ast.Attribute) and kw.value.attr in (
                                "stdout", "stderr") and isinstance(kw.value.value, ast.Name) and kw.value.value.id == "sys"):
                            out.append((lab, child.lineno, "prints to a stream other than sys.stdout/sys.stderr"))
            walk(child, lab)
    walk(tree, "")
    return out


# --- drafting -------------------------------------------------------------------------------------------------
def draft_rows(result: dict, mp: dict) -> dict:
    info = result["info"]
    rows = {n["name"] for n in mp.get("names", [])}
    missing = []
    for name, found in sorted(info["defs"].items(), key=lambda kv: kv[1][0]["line"]):
        if name not in rows:
            missing.append({"name": name, "kind": found[0]["kind"], "home": None, "row": None, "note": ""})
    return {"names": missing}


# --- the test ---------------------------------------------------------------------------------------------------
def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


BASE_SOURCE = '''HERE = 1


class Person(Exception):
    def __init__(self):
        self.kind = "x"


class Driver:
    K = 1

    def __init__(self):
        self.state = {}
        self.boundary = "start"

    def top(self):
        self.low()
        self.boundary = "top"
        return self.state.get("k")

    def low(self):
        person = Person()
        person.stage = "S1"
        return HERE
'''

BASE_MAP = {
    "schema": 1,
    "family": {"facade": "story_run", "prefix": "driver_", "class": "Driver", "cut": "mixins", "installed": False},
    "layers": [["driver_core"], ["driver_dialog"], ["story_run"]],
    "names": [
        {"name": "HERE", "kind": "const", "home": "driver_core"},
        {"name": "Person", "kind": "class", "home": "driver_core"},
        {"name": "Driver", "kind": "class", "home": "story_run"},
        {"name": "Driver.K", "kind": "classconst", "home": "driver_core"},
        {"name": "Driver.__init__", "kind": "method", "home": "driver_core"},
        {"name": "Driver.top", "kind": "method", "home": "driver_dialog"},
        {"name": "Driver.low", "kind": "method", "home": "driver_core"},
    ],
    "attributes": [{"name": "state", "owner": "driver_core", "set_in_init": True},
                   {"name": "boundary", "owner": "driver_core", "set_in_init": True}],
    "adhoc_attributes": [{"on": "Person", "name": "stage", "writers": ["Driver.low"], "readers": []}],
    "state_keys": [{"key": "k", "owner": "driver_core"}],
    "dynamic_state_keys": [],
    "string_dispatch": [],
    "exceptions": [],
    "source_readers": [],
    "source_mentions": [],
    "stdout_writers": [],
}


class Naming:
    """The names a fixture family carries. Every fixture below is WRITTEN with the first family's names (`story_run`,
    `driver_`, `Driver`) and renamed as one text just before it is built, so the same fixtures run under any other family
    header: the rename is applied to the source, the map (after its edit), the extra files and the needle alike."""

    def __init__(self, facade="story_run", prefix="driver_", cls="Driver"):
        self.facade, self.prefix, self.cls = facade, prefix, cls

    def sub(self, text: str) -> str:
        return text.replace("story_run", self.facade).replace("driver_", self.prefix).replace("Driver", self.cls)

    def tag(self, label: str) -> str:
        return label if self.facade == "story_run" else f"[{self.facade}] {label}"


NAMING = Naming()


def fixture(source=BASE_SOURCE, mp=None, extra_files=None, tests_files=None, edit=None):
    """A temp package root holding `source` as the facade, and the map (after `edit`); both renamed by NAMING. Returns
    (root, map)."""
    the_map = json.loads(json.dumps(mp if mp is not None else BASE_MAP))
    if edit:
        edit(the_map)
    the_map = json.loads(NAMING.sub(json.dumps(the_map)))
    root = harness.temp_dir("qa-layers-")
    _write(root, f"scripts/{NAMING.facade}.py", NAMING.sub(source))
    for rel, text in (extra_files or {}).items():
        _write(root, NAMING.sub(rel), NAMING.sub(text))
    for rel, text in (tests_files or {}).items():
        _write(root, "scripts/tests/" + NAMING.sub(rel), NAMING.sub(text))
    return root, the_map


def analysis_of(source=BASE_SOURCE, mp=None, extra_files=None, tests_files=None, edit=None, file_name=None) -> dict:
    """`file_name` is renamed by NAMING like the rest; the token `@ok` stands for the one correct name of the family."""
    root, the_map = fixture(source, mp, extra_files, tests_files, edit)
    if file_name == "@ok":
        file_name = the_map["family"]["prefix"][:-1] + "-layers.json"
    try:
        return analyse(root, the_map, map_name="fixture-layers.json",
                       file_name=NAMING.sub(file_name) if file_name else None)
    finally:
        harness.cleanup(root)


def problems_of(check_id: str, **kw):
    return analysis_of(**kw)["problems"][check_id]


def expect(name: str, check_id: str, needle: str, **kw) -> None:
    found = problems_of(check_id, **kw)
    needle = NAMING.sub(needle)
    check(f"{NAMING.tag(name)}: {check_id} reports it by name ({needle!r})", any(needle in p for p in found),
          f"expected a {check_id} problem containing {needle!r}; got {found}")


def expect_none(name: str, check_id: str, **kw) -> None:
    found = problems_of(check_id, **kw)
    check_eq(f"{NAMING.tag(name)}: {check_id} has no problem", found, [])


# fixtures of L11 / L12: a facade that is installed, and its two parts
PARTS = {"scripts/driver_core.py": "HERE = 1\n", "scripts/driver_dialog.py": "X = 1\n"}
INSTALLED_SOURCE = '''import driver_core
import driver_dialog
import module_facade


class Driver:
    pass


module_facade.install(__name__, [driver_core, driver_dialog])
'''
FUNCTIONS_MAP = {"schema": 1,
                 "family": {"facade": "story_run", "prefix": "driver_", "class": None, "cut": "functions", "installed": False},
                 "layers": [["driver_a", "driver_b"], ["story_run"]], "names": []}


def _installed(m):
    m["family"]["installed"] = True


def _functions(layers):
    def edit(m):
        m["layers"] = layers
    return edit


def bad_fixtures(naming: Naming) -> None:
    global NAMING
    NAMING = naming
    root, the_map = fixture()
    try:
        base = analyse(root, the_map)["problems"]
        check_eq(NAMING.tag("the base fixture is clean (no problem in any check)"), {k: v for k, v in base.items() if v}, {})
    finally:
        harness.cleanup(root)

    expect("L1 a def with no row", "L1", "has no row for it", source=BASE_SOURCE + "\n\ndef extra():\n    return 1\n")
    expect("L1 a row with no def", "L1", "names nothing in the family",
           edit=lambda m: m["names"].append({"name": "ghost", "kind": "func", "home": "driver_core"}))
    expect("L1 a wrong kind", "L1", "fix the row's kind",
           edit=lambda m: m["names"][0].update(kind="func"))
    expect("L2 one name defined twice", "L2", "defined 2 times",
           source=BASE_SOURCE + "\n\ndef HERE():\n    return 2\n")
    expect("L2 a name defined outside its existing home module", "L2", "move it there",
           extra_files={"scripts/driver_core.py": "FILLER = 1\n"},
           edit=lambda m: m["names"].append({"name": "FILLER", "kind": "const", "home": "driver_dialog"}))
    expect("L3 a read of an unowned attribute", "L3", "nothing owns `ghost_attr`",
           source=BASE_SOURCE.replace("self.low()", "self.ghost_attr\n        self.low()"))
    expect("L3 setattr(self, 'x', v)", "L3", "nothing owns `x`",
           source=BASE_SOURCE.replace("self.low()", "setattr(self, 'x', 1)\n        self.low()"))
    expect("L3 del self.x", "L3", "deletes `self.zz`",
           source=BASE_SOURCE.replace("self.low()", "del self.zz\n        self.low()"))
    expect("L3 a non-literal getattr without a row", "L3", "chosen at run time",
           source=BASE_SOURCE.replace("self.low()", "getattr(self, 'low' + str(1))()"))
    expect("L3 self.__dict__", "L3", "`self.__dict__`", source=BASE_SOURCE.replace("self.low()", "self.__dict__\n        self.low()"))
    expect("L3 once_on(self, 'x', make) is a touch of `x`", "L3", "nothing owns `hidden_lock`",
           source=BASE_SOURCE.replace("self.low()", "once_on(self, 'hidden_lock', dict)\n        self.low()"))
    expect("L3 once_on(self, <non-literal>, make)", "L3", "`once_on(self, <non-literal>, ...)`",
           source=BASE_SOURCE.replace("self.low()", "once_on(self, str(1), dict)\n        self.low()"))
    expect("L3 vars(self)", "L3", "`vars(self)`", source=BASE_SOURCE.replace("self.low()", "vars(self)\n        self.low()"))
    expect("L3 me = self", "L3", "makes an alias", source=BASE_SOURCE.replace("self.low()", "me = self\n        self.low()"))
    expect("L3 a lambda closing over self", "L3", "nothing owns `lam`",
           source=BASE_SOURCE.replace("self.low()", "fn = lambda: self.lam\n        self.low()"))
    expect("L3 self.flags.x resolves `flags` only", "L3", "nothing owns `flags`",
           source=BASE_SOURCE.replace("self.low()", "self.flags.x\n        self.low()"))
    expect("L3 Driver.X", "L3", "not a member of the Driver class", source=BASE_SOURCE.replace("self.low()", "Driver.X\n        self.low()"))
    expect("L3 DriverX.nope (a class-name access that does not resolve)", "L3", "not a member of the Driver class",
           source=BASE_SOURCE.replace("self.low()", "DriverX.nope\n        self.low()"))
    expect_none("L3 DriverCore.K resolves to the member row Driver.K", "L3",
                source=BASE_SOURCE.replace("self.low()", "DriverCore.K\n        self.low()"))
    expect("L3 type(self).X", "L3", "not a member of the Driver class",
           source=BASE_SOURCE.replace("self.low()", "type(self).Y\n        self.low()"))
    expect("L3 functools.partial(self.m)", "L3", "nothing owns `m`",
           source=BASE_SOURCE.replace("self.low()", "functools.partial(self.m)\n        self.low()"))
    expect("L3 a stale attributes row", "L3", "is not touched through `self` anywhere",
           edit=lambda m: m["attributes"].append({"name": "stale", "owner": "driver_core", "set_in_init": False}))
    expect("L3 a stale string_dispatch row", "L3", "matches no getattr(self, <non-literal>)",
           edit=lambda m: m["string_dispatch"].append({"function": "Driver.low", "expr": "x", "candidates": ["Driver.top"]}))
    expect("L3 a dispatch candidate that does not exist", "L3", "which is not defined",
           source=BASE_SOURCE.replace("self.low()", "getattr(self, 'a' + 'b')()"),
           edit=lambda m: m["string_dispatch"].append({"function": "Driver.top", "expr": "x", "candidates": ["Driver.nope"]}))
    expect("L3 set_in_init says the wrong thing", "L3", "set_in_init",
           edit=lambda m: m["attributes"][1].update(set_in_init=False))
    expect("L4 a state key with no row", "L4", "uses state key `newkey`",
           source=BASE_SOURCE.replace("self.low()", "self.state['newkey'] = 1\n        self.low()"))
    expect("L4 a stale state key row", "L4", "is used nowhere",
           edit=lambda m: m["state_keys"].append({"key": "gone", "owner": "driver_core"}))
    expect("L4 a state key chosen at run time", "L4", "chosen at run time",
           source=BASE_SOURCE.replace("self.low()", "self.state[str(1)] = 1\n        self.low()"))
    expect("L4 x = self.state", "L3", "alias of the state",
           source=BASE_SOURCE.replace("self.low()", "s = self.state\n        self.low()"))
    expect("L4 a Person attribute with no row", "L4", "`person.extra` is used",
           source=BASE_SOURCE.replace('person.stage = "S1"', 'person.stage = "S1"\n        person.extra = 1'))
    expect("L4 a stale adhoc row", "L4", "is used nowhere",
           edit=lambda m: m["adhoc_attributes"].append({"on": "Person", "name": "old", "writers": [], "readers": []}))
    up = BASE_SOURCE.replace("        return HERE\n", "        return self.top()\n")
    expect("L5 a lower layer calls a higher one", "L5", "a lower layer may not call a higher one", source=up)
    listed = problems_of("L5", source=up, edit=lambda m: m["exceptions"].append(
        {"from": "Driver.low", "to": "Driver.top", "kind": "call", "reason": "residue"}))
    check_eq(NAMING.tag("L5 the same edge listed in `exceptions` passes"), [p for p in listed if "may not call" in p], [])
    expect("L5 an exceptions row that no pin holds is new", "L5", "is new", source=up, edit=lambda m: m["exceptions"].append(
        {"from": "Driver.low", "to": "Driver.top", "kind": "call", "reason": "residue"}))
    expect("L5 a stale exceptions row", "L5", "no longer occurs",
           edit=lambda m: m["exceptions"].append({"from": "Driver.top", "to": "Driver.low", "kind": "call", "reason": "r"}))
    expect("L7 an owner above its accessor", "L7", "must be at or below",
           edit=lambda m: m["attributes"][1].update(owner="driver_dialog"),
           source=BASE_SOURCE.replace("        self.boundary = \"start\"\n", "        self.boundary = \"start\"\n        self.low()\n"))
    expect("L6 an upward import", "L6", "imports driver_dialog, a higher layer",
           extra_files={"scripts/driver_core.py": "import driver_dialog\n", "scripts/driver_dialog.py": "X = 1\n"},
           edit=lambda m: m["names"].extend([{"name": "X", "kind": "const", "home": "driver_dialog"}]))
    expect("L8 a source read with no row", "L8", "reads the family's source",
           tests_files={"test_x.py": 'from pathlib import Path\n\n\ndef reader():\n    return Path("scripts/story_run.py").read_text()\n'})
    expect("L8 a source_readers row for a function that reads nothing", "L8", "belongs in `source_mentions`",
           tests_files={"test_x.py": 'def reader():\n    return "run story_run.py now"\n'},
           edit=lambda m: m["source_readers"].append({"file": "test_x.py", "function": "reader", "count": 1, "targets": []}))
    expect("L8 a driver_x.py literal with a row that names the file", "L8", "test_x.py:6",
           extra_files={"scripts/driver_x.py": "X = 1\n"},
           tests_files={"test_x.py": 'def other():\n    return "driver_x.py"\n\n\ndef reader():\n    return "run driver_x.py now"\n'},
           edit=lambda m: (m["names"].append({"name": "X", "kind": "const", "home": "driver_core"}),
                           m["source_mentions"].append({"file": "test_x.py", "function": "other", "count": 1,
                                                        "note": "driver_x.py"})))
    expect("L8 a part file name literal with no row (no temporal rule: every file name of the family counts)", "L8",
           "test_x.py:2, in `reader`, reads the family's source",
           extra_files={"scripts/driver_x.py": "X = 1\n"},
           tests_files={"test_x.py": 'def reader():\n    return "run driver_x.py now"\n'},
           edit=lambda m: m["names"].append({"name": "X", "kind": "const", "home": "driver_core"}))
    expect("L8 a row for a function that holds no family file name", "L8", "holds no literal file name of the family",
           tests_files={"test_x.py": 'def reader():\n    return "nothing"\n'},
           edit=lambda m: m["source_mentions"].append({"file": "test_x.py", "function": "reader", "count": 1, "why": "x"}))
    expect_none("L8 a tests-directory instrument file (harness.py) is not counted", "L8",
                tests_files={"harness.py": 'def reader():\n    return "run story_run.py now"\n'})
    expect("L9 a direct sys.stdout.write", "L9", "writes to sys.stdout directly",
           source=BASE_SOURCE.replace("self.low()", "sys.stdout.write('x')\n        self.low()"))
    expect("L9 print to another stream", "L9", "prints to a stream other than",
           source=BASE_SOURCE.replace("self.low()", "print('x', file=handle)\n        self.low()"))
    expect("L10 a row with no home", "L10", "has no home", edit=lambda m: m["names"][0].update(home=None))
    expect("L10 a home outside the layers", "L10", "not in `layers`", edit=lambda m: m["names"][0].update(home="nowhere"))
    expect("L10 two rows for one name", "L10", "two rows for `HERE`", edit=lambda m: m["names"].append(dict(m["names"][0])))
    expect("L10 an exception with no reason", "L10", "has no reason",
           edit=lambda m: m["exceptions"].append({"from": "a", "to": "b", "kind": "call", "reason": ""}))

    # --- L10: the family header and the optional header keys (found BEFORE any other check of the map runs)
    header_cases = [
        ("a missing family header", lambda m: m.pop("family"), "has no `family` header"),
        ("an unknown cut", lambda m: m["family"].update(cut="slices"), "family.cut is 'slices'"),
        ("a mixins cut with a null class", lambda m: m["family"].update({"class": None}), "family.class is null"),
        ("an installed flag that is not a boolean", lambda m: m["family"].update(installed="yes"), "family.installed is 'yes'"),
        ("a prefix with no trailing underscore", lambda m: m["family"].update(prefix="driver"), "family.prefix is 'driver'"),
        ("a facade with no file", lambda m: m["family"].update(facade="no_such_file"), "has no scripts/no_such_file.py"),
        ("an allowed_importers row of the wrong shape", lambda m: m.update(allowed_importers=[{"importer": "x.py"}]),
         "expected exactly the keys importer, part, reason"),
        ("an allowed_importers part that is no file of the family",
         lambda m: m.update(allowed_importers=[{"importer": "x.py", "part": "nowhere", "reason": "r"}]),
         "expected a part file stem of the family"),
        ("an allowed_importers row with no reason",
         lambda m: m.update(allowed_importers=[{"importer": "x.py", "part": "driver_core", "reason": " "}]), "has no reason"),
        ("an allowed_importers importer that is not a script file name",
         lambda m: m.update(allowed_importers=[{"importer": "a/x", "part": "driver_core", "reason": "r"}]),
         "expected a script file name"),
        ("a setup_import that is not a module stem", lambda m: m.update(setup_import=123), "`setup_import` is 123"),
        ("a module_statements home outside the layers", lambda m: m.update(module_statements={"print(1)": "nowhere"}),
         "names the home 'nowhere'"),
        ("a facade that is a path, not a bare module stem", lambda m: m["family"].update(facade="tests/harness"),
         "expected a bare module stem"),
        ("a module listed twice in layers", lambda m: m.update(layers=[["driver_core", "driver_core"], ["story_run"]]),
         "lists `driver_core` more than once"),
        ("a class table on a family whose class is null",
         lambda m: m["family"].update({"class": None, "cut": "functions"}), "carries the class table `attributes`"),
        ("an l8_skip that is not a list", lambda m: m.update(l8_skip="x.py"), "`l8_skip` is 'x.py'"),
        ("an l8_skip entry with a path", lambda m: m.update(l8_skip=["tests/x.py"]), "expected a list of test file names"),
    ]
    for case, edit, needle in header_cases:
        expect(f"L10 {case}", "L10", needle, extra_files=PARTS, edit=edit)
    expect("L10 a map file whose name does not match the prefix", "L10", "the map file is named", extra_files=PARTS,
           file_name="driver_layers.json")
    expect_none("L10 a map file named <prefix without the underscore>-layers.json", "L10", extra_files=PARTS, file_name="@ok")
    # a map-file-level problem skips every other check of that map, like any header problem
    check_eq(NAMING.tag("L10 a wrong file name skips every other check of that map"),
             {k: bool(v) for k, v in analysis_of(source=BASE_SOURCE + "\n\ndef extra():\n    return 1\n",
                                                 file_name="driver_layers.json")["problems"].items() if v}, {"L10": True})
    expect_none("L10 a well formed l8_skip", "L10", extra_files=PARTS, edit=lambda m: m.update(l8_skip=["test_x.py"]))
    clash = {"a-layers.json": BASE_MAP, "b-layers.json": {"family": {"facade": "story_run"}}, "c-layers.json": {"family": {
        "facade": "other"}}}
    check(NAMING.tag("L10 two maps naming one facade are a problem"), any("both name the facade `story_run`" in p
          for p in facade_clash_problems(clash)), f"got {facade_clash_problems(clash)}")
    check_eq(NAMING.tag("L10 distinct facades are no clash"), facade_clash_problems({"a-layers.json": BASE_MAP,
                                                                                    "c-layers.json": clash["c-layers.json"]}), [])
    # the pin equals the map, both directions (pure: the pin is given, no family is named)
    pin = {"a>b>call", "c>d>call"}
    rows = [{"from": "a", "to": "b", "kind": "call"}, {"from": "c", "to": "d", "kind": "call"}]
    check_eq(NAMING.tag("pin: a map equal to its pin is clean"), pin_problems(rows, pin), [])
    check(NAMING.tag("pin: a ninth row (a row the pin does not hold) is new"),
          any("e>f>call is new" in p for p in pin_problems(rows + [{"from": "e", "to": "f", "kind": "call"}], pin)),
          f"got {pin_problems(rows + [{'from': 'e', 'to': 'f', 'kind': 'call'}], pin)}")
    check(NAMING.tag("pin: a pinned row the map no longer holds is a problem"),
          any("the pin holds the row c>d>call but the map no longer does" in p for p in pin_problems(rows[:1], pin)),
          f"got {pin_problems(rows[:1], pin)}")
    check_eq(NAMING.tag("pin: analyse's own question is the new-row direction only"), pin_problems(rows[:1], pin, stale=False), [])
    check_eq(NAMING.tag("pin: a family with an empty pin and no exceptions is fine"), pin_problems([], set()), [])
    expect_none("L10 the optional header keys, well formed", "L10", extra_files=PARTS, edit=lambda m: m.update(
        setup_import="hooklib", module_statements={"print(1)": "driver_core"},
        allowed_importers=[{"importer": "x.py", "part": "driver_core", "reason": "r"}]))
    bad_header = analysis_of(source=BASE_SOURCE + "\n\ndef extra():\n    return 1\n", edit=lambda m: m["family"].update(cut="slices"))
    check_eq(NAMING.tag("L10 a malformed header skips every other check of that map (an unmapped def is not reported)"),
             {k: bool(v) for k, v in bad_header["problems"].items() if v}, {"L10": True})
    check(NAMING.tag("L10 a malformed header says so in info['skipped']"), bool(bad_header["info"]["skipped"]),
          f"info: {bad_header['info']}")

    # --- optional tables: a check over an absent table is not run, and one line says so
    table_names = list(OPTIONAL_TABLES)
    absent = analysis_of(source=BASE_SOURCE.replace("self.low()", "self.ghost_attr\n        self.state['newkey'] = 1\n"
                                                    "        sys.stdout.write('x')\n        getattr(self, 'a' + 'b')\n"
                                                    "        self.low()").replace('person.stage = "S1"', 'person.stage = "S1"\n'
                                                                                '        person.extra = 1'),
                         edit=lambda m: [m.pop(t) for t in table_names])
    check_eq(NAMING.tag("tables absent: L3, L4 and L9 report nothing over them"),
             {k: v for k, v in absent["problems"].items() if k in ("L3", "L4", "L9") and v}, {})
    check(NAMING.tag("tables absent: one informational line names them"),
          sum("table(s): the checks over them are not run" in n for n in absent["info"]["notes"]) == 1,
          f"notes: {absent['info']['notes']}")
    expect("L3 an attributes table that is present is checked as before", "L3", "nothing owns `ghost_attr`",
           source=BASE_SOURCE.replace("self.low()", "self.ghost_attr\n        self.low()"))

    # --- L11: who may import a part, and the facade
    outside = {**PARTS, "scripts/other_tool.py": "def f():\n    import driver_core\n"}
    expect("L11 (a) a script outside the family imports a part", "L11", "other_tool.py:2 imports the family part `driver_core`",
           extra_files=outside)
    expect("L11 (a) a literal importlib.import_module of a part", "L11", "imports the family part `driver_dialog`",
           extra_files={**PARTS, "scripts/other_tool.py": "import importlib\nm = importlib.import_module('driver_dialog')\n"})
    allow = {"importer": "other_tool.py", "part": "driver_core", "reason": "a lazy import of the timing clock"}
    expect_none("L11 (a) an allowed_importers row that matches the import passes", "L11", extra_files=outside,
                edit=lambda m: m.update(allowed_importers=[allow]))
    expect("L11 (a) a stale allowed_importers row", "L11", "matches no import in scripts/",
           extra_files={**PARTS, "scripts/other_tool.py": "X = 1\n"}, edit=lambda m: m.update(allowed_importers=[allow]))
    expect_none("L11 (a) imports from a test file and from tools/ are out of scope", "L11",
                extra_files={**PARTS, "scripts/tests/test_y.py": "import driver_core\n", "tools/t.py": "import driver_core\n"})
    expect_none("L11 (b) an installed facade that follows the rule", "L11", source=INSTALLED_SOURCE, extra_files=PARTS,
                edit=_installed)
    expect("L11 (b) the facade misses a part import", "L11", "no literal `import driver_dialog`",
           source=INSTALLED_SOURCE.replace("import driver_dialog\n", ""), extra_files=PARTS, edit=_installed)
    expect("L11 (b) the parts are out of rank order", "L11", "in rank order",
           source=INSTALLED_SOURCE.replace("[driver_core, driver_dialog]", "[driver_dialog, driver_core]"),
           extra_files=PARTS, edit=_installed)
    expect("L11 (b) the install call is missing", "L11", "calls module_facade.install 0 times",
           source=INSTALLED_SOURCE.replace("module_facade.install(__name__, [driver_core, driver_dialog])\n", ""),
           extra_files=PARTS, edit=_installed)
    expect("L11 (b) the facade defines a name whose home is a part", "L11", "defines `HERE`, whose home is the part",
           source=INSTALLED_SOURCE + "\n\nHERE = 2\n", extra_files=PARTS, edit=_installed)
    expect("L11 (b) a part named in layers has no file", "L11", "has no scripts/driver_dialog.py",
           source=INSTALLED_SOURCE, extra_files={"scripts/driver_core.py": "HERE = 1\n"}, edit=_installed)
    expect("L11 (c) installed false but the facade calls install", "L11", "family.installed is false",
           source=INSTALLED_SOURCE, extra_files=PARTS)
    expect_none("L11 (c) installed false and no install call: (b) is not run, so no missing import is reported", "L11",
                source=BASE_SOURCE, extra_files=PARTS)
    call = "module_facade.install(__name__, [driver_core, driver_dialog])"
    aliased = INSTALLED_SOURCE.replace("import module_facade\n", "import module_facade as mf\n").replace(call, "mf." + call[14:])
    from_as = INSTALLED_SOURCE.replace("import module_facade\n", "from module_facade import install as inst\n").replace(
        call, "inst(__name__, [driver_core, driver_dialog])")
    by_getattr = INSTALLED_SOURCE.replace(call, "getattr(module_facade, 'install')(__name__, [driver_core, driver_dialog])")
    for form, text in (("an alias of the module (import module_facade as mf)", aliased),
                       ("from module_facade import install as inst", from_as),
                       ("getattr(module_facade, 'install')", by_getattr)):
        expect(f"L11 (c) installed false with the install call made through {form}", "L11", "family.installed is false",
               source=text, extra_files=PARTS)
        expect(f"L11 (b) installed true, the call made through {form}, is seen (wrong order is reported)", "L11",
               "in rank order", source=text.replace("[driver_core, driver_dialog]", "[driver_dialog, driver_core]"),
               extra_files=PARTS, edit=_installed)
        expect_none(f"L11 (b) installed true, the call made through {form}, in order", "L11", source=text, extra_files=PARTS,
                    edit=_installed)
    expect("L11 (c) installed false with only an import of module_facade", "L11", "imports module_facade but family.installed",
           source=BASE_SOURCE + "\nimport module_facade as mf\n", extra_files=PARTS)
    expect("L11 (b) the first argument of install is a literal, not __name__", "L11", "is not `__name__`",
           source=INSTALLED_SOURCE.replace("(__name__,", "('story_run',"), extra_files=PARTS, edit=_installed)
    expect("L11 (b) the install call is not at module level", "L11", "below module level",
           source=INSTALLED_SOURCE.replace(call, "if False:\n    " + call), extra_files=PARTS, edit=_installed)
    expect("L11 (a) a script that cannot be parsed is reported by name", "L11", "scripts/broken.py cannot be parsed",
           extra_files={**PARTS, "scripts/broken.py": "import driver_core\ndef (:\n"})
    expect("L11 (a) a script that starts with a BOM is still read", "L11", "imports the family part `driver_core`",
           extra_files={**PARTS, "scripts/bom_tool.py": chr(0xFEFF) + "import driver_core\n"})
    # every package script that imports module_facade is the facade of a map (E8): no new data, the maps' facade stems
    root = harness.temp_dir("qa-layers-")
    try:
        for rel, text in (("scripts/module_facade.py", "def install(name, parts):\n    pass\n"),
                          ("scripts/inst_a.py", "import module_facade\n"), ("scripts/inst_b.py", "import module_facade as mf\n"),
                          ("scripts/inst_c.py", "import importlib\nm = importlib.import_module('module_facade')\n"),
                          ("scripts/plain.py", "X = 1\n"), ("scripts/tests/test_z.py", "import module_facade\n"),
                          ("scripts/broken.py", "def (:\n")):
            _write(root, rel, text)
        orphans = facade_importer_problems(root, {"inst_a"})
        check_eq(NAMING.tag("E8 a script importing module_facade with no map is reported (plain, tests/ and the facade of a "
                            "map are not)"),
                 sorted(p.split(" ")[0] for p in orphans), ["scripts/broken.py", "scripts/inst_b.py", "scripts/inst_c.py"])
        check_eq(NAMING.tag("E8 every importer being a map's facade leaves only the unparsable script"),
                 [p.split(" ")[0] for p in facade_importer_problems(root, {"inst_a", "inst_b", "inst_c"})],
                 ["scripts/broken.py"])
    finally:
        harness.cleanup(root)
    # the l8_skip header key: a family's own instrument files are not counted
    reader = {"test_x.py": 'from pathlib import Path\n\n\ndef reader():\n    return Path("scripts/story_run.py").read_text()\n'}
    expect_none("L8 a file named in the map's l8_skip is not counted", "L8", tests_files=reader,
                edit=lambda m: m.update(l8_skip=["test_x.py"]))

    # --- L12: a class-name access resolves to the assembled class or exactly the member's own mixin
    expect("L12 an unknown class (DriverTypo.low)", "L12", "`DriverTypo` is no class of the family",
           source=BASE_SOURCE.replace("self.low()", "DriverTypo.low\n        self.low()"))
    expect("L12 a wrong mixin (DriverCore.top, top is homed in the dialog)", "L12", "expected `DriverDialog.top`",
           source=BASE_SOURCE.replace("self.low()", "DriverCore.top\n        self.low()"))
    expect_none("L12 the member's own mixin and the assembled class resolve", "L12",
                source=BASE_SOURCE.replace("self.low()", "DriverDialog.top\n        DriverCore.low\n        Driver.top\n"
                                                        "        self.low()"))
    expect_none("L3 the member's own mixin resolves too (no problem)", "L3",
                source=BASE_SOURCE.replace("self.low()", "DriverDialog.top\n        self.low()"))
    equal = {"scripts/driver_a.py": "import driver_b\n", "scripts/driver_b.py": "Y = 1\n"}
    expect("L12 (functions cut) a part imports a part of the same rank", "L12", "a part of the same rank",
           mp=FUNCTIONS_MAP, extra_files=equal)
    expect_none("L12 (functions cut) a part imports a LOWER-ranked part", "L12", mp=FUNCTIONS_MAP,
                extra_files={"scripts/driver_a.py": "Y = 1\n", "scripts/driver_b.py": "import driver_a\n"},
                edit=_functions([["driver_a"], ["driver_b"], ["story_run"]]))
    expect("L6 (functions cut) a part imports a HIGHER-ranked part", "L6", "imports driver_b, a higher layer",
           mp=FUNCTIONS_MAP, extra_files=equal, edit=_functions([["driver_a"], ["driver_b"], ["story_run"]]))
    one_rank = lambda m: m.update(layers=[["driver_a", "driver_b"], ["story_run"]], names=[])    # noqa: E731
    expect("L12 (mixins cut) a part imports a part of the same rank (one rule for both cuts)", "L12", "a part of the same rank",
           extra_files=equal, edit=one_rank)
    expect("L12 (mixins cut) a two-way import cycle between equal-rank parts", "L12", "driver_a.py:1 imports driver_b",
           extra_files={"scripts/driver_a.py": "import driver_b\n", "scripts/driver_b.py": "import driver_a\n"}, edit=one_rank)
    expect_none("L12 (mixins cut) a part imports a strictly LOWER-ranked part", "L12",
                extra_files={"scripts/driver_a.py": "Y = 1\n", "scripts/driver_b.py": "import driver_a\n"},
                edit=lambda m: m.update(layers=[["driver_a"], ["driver_b"], ["story_run"]], names=[]))
    expect_none("L12 an equal-rank import of `<prefix>base` is legal", "L12",
                extra_files={"scripts/driver_base.py": "Y = 1\n", "scripts/driver_a.py": "import driver_base\n"},
                edit=lambda m: m.update(layers=[["driver_base", "driver_a"], ["story_run"]], names=[]))
    expect("L12 an equal-rank import through importlib.import_module (the one import reader)", "L12", "a part of the same rank",
           mp=FUNCTIONS_MAP, extra_files={"scripts/driver_a.py": "import importlib\nm = importlib.import_module('driver_b')\n",
                                          "scripts/driver_b.py": "Y = 1\n"})
    expect("L6 an upward import through __import__", "L6", "imports driver_dialog, a higher layer",
           extra_files={"scripts/driver_core.py": "m = __import__('driver_dialog')\n", "scripts/driver_dialog.py": "X = 1\n"},
           edit=lambda m: m["names"].extend([{"name": "X", "kind": "const", "home": "driver_dialog"}]))
    # L12 scope: the assembled class by name inside a part, and module-level / class-body code
    in_part = "class DriverCore:\n    def m(self):\n        return Driver.top\n"
    expect("L12 the assembled class by name inside a part", "L12", "inside a part: the assembled class `Driver` is not importable",
           extra_files={"scripts/driver_core.py": in_part})
    expect("L12 the assembled class by name in the module-level code of a part", "L12", "module-level or class-body code",
           extra_files={"scripts/driver_core.py": "X = Driver.K\n"})
    expect("L12 a wrong mixin at module level of the facade", "L12", "expected `DriverDialog.top`",
           source=BASE_SOURCE + "\n\nT = DriverCore.top\n")
    expect("L12 a wrong mixin in a class body", "L12", "expected `DriverDialog.top`",
           source=BASE_SOURCE + "\n\nclass Other:\n    T2 = DriverCore.top\n")
    expect_none("L12 the assembled class at module level of the FACADE is legal", "L12",
                source=BASE_SOURCE + "\n\nT3 = Driver.top\n")
    nul = analysis_of(mp=FUNCTIONS_MAP, extra_files=equal)
    check(NAMING.tag("class null: one line says the class clauses of L3 and L12 are not run"),
          any("family.class is null" in n for n in nul["info"]["notes"]), f"notes: {nul['info']['notes']}")


def family_maps() -> list:
    """The map files the test runs: every fixtures/*-layers.json (the glob IS the discovery; no family is named here)."""
    return sorted(harness.FIXTURES.glob("*-layers.json"))


def facade_clash_problems(maps: dict) -> list:
    """Two maps that name one facade: the second would inherit the first's pin and census. `maps` is {file name: map}."""
    seen, out = {}, []
    for name, mp in sorted(maps.items()):
        facade = (mp.get("family") or {}).get("facade") if isinstance(mp, dict) else None
        if isinstance(facade, str):
            if facade in seen:
                out.append(f"{name} and {seen[facade]} both name the facade `{facade}`: a facade has one map; merge them or "
                           f"delete one.")
            seen.setdefault(facade, name)
    return out


def real_maps() -> None:
    maps = family_maps()
    check("map discovery: fixtures/*-layers.json finds at least one family map", bool(maps),
          f"expected a map in {harness.FIXTURES}; an empty discovery would pass every check vacuously")
    loaded = {}
    for path in maps:
        try:
            loaded[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            check(f"{path.name} is valid JSON", False, str(exc))
    clashes = facade_clash_problems(loaded)
    check(f"no two maps name one facade ({len(clashes)} problem(s))", not clashes, "\n  " + "\n  ".join(clashes))
    facades = {mp["family"]["facade"] for mp in loaded.values()
               if isinstance(mp.get("family"), dict) and isinstance(mp["family"].get("facade"), str)}
    orphans = facade_importer_problems(harness.PLUGIN_ROOT, facades)
    check(f"every script that imports module_facade is the facade of a map ({len(orphans)} problem(s))", not orphans,
          "\n  " + "\n  ".join(orphans))
    for name, mp in loaded.items():
        result = analyse(harness.PLUGIN_ROOT, mp, map_name=name, file_name=name)
        info = result["info"]
        if info["skipped"]:
            found = result["problems"]["L10"]
            print(f"{name}: every check except L10 is SKIPPED: {info['skipped']}")
            check(f"{name} L10 holds on the real map ({len(found)} problem(s))", not found, "\n  " + "\n  ".join(found))
            continue
        print(f"{name}: census {info['names']} names defined by {', '.join(info['files'])} ({info['members']} class members); "
              f"map rows {len(mp.get('names', []))}; attributes {len(info['attr_seen'])}; state keys {len(info['state_seen'])}; "
              f"dynamic state sites {info['dynamic_state_sites']}; string-dispatch sites {len(info['dispatch_sites'])}; "
              f"ad-hoc Person attributes {info['adhoc']}; edges {info['edges']} of which upward {info['upward']} "
              f"(exceptions rows {len(mp.get('exceptions', []))}); source-text sites {info['l8_sites']}")
        for note in info["notes"]:
            print(f"{name}: not run / informational: {note}")
        for check_id, found in result["problems"].items():
            if check_id == "L6" and len(info["files"]) == 1:
                print(f"{name}: L6 import direction is vacuous here (the facade is the only module); the bad fixtures run it")
            check(f"{name} {check_id} holds on the real family ({len(found)} problem(s))", not found,
                  "\n  " + "\n  ".join(found[:12]))
        readers = mp.get("source_readers", [])
        print(f"{name}: L8 source-pinning sites declared as readers: {sum(r['count'] for r in readers)} in "
              f"{len({r['file'] for r in readers})} files: " + "; ".join(f"{r['file']}::{r['function']}" for r in readers))
        pin = pin_problems(mp.get("exceptions", []), pinned_for(mp["family"]["facade"]), name)
        check(f"{name}: the pin equals the exceptions list, both directions ({len(pin)} problem(s))", not pin,
              "\n  " + "\n  ".join(pin))
    check_eq("a family with no pin is pinned empty", pinned_for("no_such_facade"), set())


def main() -> None:
    if "--draft-missing" in sys.argv or "--draft-all" in sys.argv:
        maps = family_maps()
        if "--map" in sys.argv:
            maps = [harness.FIXTURES / sys.argv[sys.argv.index("--map") + 1]]
        if len(maps) != 1:
            sys.exit(f"draft: {len(maps)} maps found ({[m.name for m in maps]}); expected exactly one, name it with --map <file name>")
        mp = json.loads(maps[0].read_text(encoding="utf-8"))
        result = analyse(harness.PLUGIN_ROOT, mp, map_name=maps[0].name)
        if result["info"]["skipped"]:
            sys.exit(f"draft: {maps[0].name}: {result['problems']['L10']}")
        print(json.dumps(draft_rows(result, mp)["names"], indent=0))
        if "--draft-all" in sys.argv:
            info = result["info"]
            print(json.dumps({"attributes": info["attr_seen"], "attr_init": sorted(info["attr_init"]),
                              "state_keys": info["state_seen"], "dyn_sites": info["dyn_sites"],
                              "dispatch_sites": info["dispatch_sites"], "adhoc": info["adhoc_seen"],
                              "upward_edges": info["upward_edges"],
                              "census_l8": {f"{k[0]}::{k[1]}": v for k, v in info["census_l8"].items()}}, indent=1))
        return
    real_maps()
    bad_fixtures(Naming())
    # the same fixtures under an invented family header: no family name may be baked into the check code
    bad_fixtures(Naming("gizmo", "gizmo_", "Gizmo"))
    finish("test_driver_layers")


if __name__ == "__main__":
    main()
