"""The judgment census and its shrink-only ratchet (t-1765 node A3; AR-29, FR-47).

WHAT IT DOES. It reads EVERY `scripts/*.py` of the package except `scripts/tests/` with `ast`, finds the CHECK UNITS
(a function or method that judges, refuses or hands a verdict to the model), and demands one row per unit in
`fixtures/judgment-census.json` (FR-44: read by tests only, so it is not under `references/`). A row names the unit's CLASS
(shape / xref / word-list / meaning-proxy / meaning / safety), the roles on whose path it stands, and the owner it serves
(data / judgment / intent). Whether a unit BLOCKS is COMPUTED, never labelled: a refusal site seen by the one scanner of
refusal sites (`refusal_registry.sites`), or a file on the declared blocking path (`BLOCKING_ENTRY_FILES`, or a script that
`stages.json` lists under `detectors` and not under `advice` of its stage). A BREACH is a unit that blocks and whose class is
word-list, meaning-proxy or meaning: code refusing on a role's content. Ceilings in `ratchet` only go down.

THE SCAN IS NOT DATA. `SCAN_ROOT` and `SCAN_EXCLUDE` are constants of THIS file: narrowing the scan needs an edit of the test
(a diff the critic and calibration check 41 (a) read); an edit of the census data cannot narrow it. The totals line printed at
the end carries both constants.

WHAT A UNIT IS (any one of):
  u1  the name matches UNIT_NAME_RE (`check_*`, `rule_*`, `judge*`, `judged_*`, `validate*`, `refuse*` (with an optional leading
      underscore), a bare `check` or `run` (also `_check`, `_run`), `*_check`, `*_errors`, `*_problems`; widened from the spec's
      first form after critic t-1793 F1: 99 of 102 `*_problems`, 34 of 45 `validate*`, 43 of 47 `refuse*` had no row);
  u2  the body calls the fabric's LLM judge: an attribute of the module `judge` or `judge_form` named in JUDGE_CALLS
      (also through `import judge as X` / `from judge import ask_one`);
  u3  the body holds a refusal site that `refusal_registry.sites()` sees (`deny`/`block`, `raise StateConflict|ValueError`).
Plus: a row of `stages.json` `detectors`/`advice` for a script that has no function-units, and an entry of
`refusal_registry.REGISTRY` whose (file, function) is not a unit already. Count by distinct (file, function): a stage row or a
registry entry on a function that is a unit is a `ref` on that function's row, not a second unit.

CLASS ORDER when two readings meet on one unit (E-A2): meaning > meaning-proxy > word-list > safety > xref > shape (CLASS_ORDER);
the HIGHER wins. `safety` is a guard on the application, secrets, outside writes, a person's words or git state. It outranks the
data classes, so a guard is never diluted into `shape` and its own ceiling holds it; it never outranks the judgment classes, so
a unit that both guards and judges content counts as a breach (the safe direction).

BLIND SPOTS (printed with the totals): `meaning` is a hand label, and a unit that judges meaning but is labelled `word-list`
or `shape` is invisible to `MEANING_CEILING` - the critic's question 11 and calibration check 41 (d) catch it. A unit with a
check's meaning under a neutral name, with no judge call and no refusal site, is not seen either. A subclass of `ValueError`
or `StateConflict` raised by its own name is invisible to `refusal_registry.sites` (it matches the literal names); legitimate
when the subclass is caught and never reaches a role, but a subclass chosen to keep a ratchet down is not seen - the critic's
question 11 and calibration check 41 catch it.

    python -B scripts/tests/test_judgment_census.py            # as a script (PASS/FAIL lines)
    python -B -m pytest scripts/tests/test_judgment_census.py -q -p no:cacheprovider
"""
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import refusal_registry  # noqa: E402  (the one scanner of refusal sites; no second AST walk over refusals here)
import role_load  # noqa: E402  (the one reader of the role names: agents/*.md)

CENSUS_PATH = harness.FIXTURES / "judgment-census.json"

# The scan: constants of the test, never census data (the spec's closed loophole: a narrowed sample lowering the counts).
SCAN_ROOT = "scripts"
SCAN_EXCLUDE = ("tests",)

UNIT_NAME_RE = re.compile(r"^(check_|rule_|judge|judged_|_?validate|_?refuse)|^_?(check|run)$|(_check|_errors|_problems)$")
# E-A2, the class a unit takes when two readings meet: the HIGHER (earlier) wins. A constant of this test, not census data.
CLASS_ORDER = ("meaning", "meaning-proxy", "word-list", "safety", "xref", "shape")
JUDGE_CALLS = {
    "judge": ("ask", "ask_one", "ask_many", "judged_refusal"),
    "judge_form": ("digest", "digest_errors"),      # X7-2 cut `unresolved_reason` and `normalise_unresolved` with their callers
}
# Files whose checks return a list of errors that the caller turns into a refusal; `sites()` cannot see those refusals.
# The tuple only grows (a file is removed only at the first census, with a note in the node's report).
BLOCKING_ENTRY_FILES = ("exit_gate.py", "stage_guard.py", "guard_pre_tool.py", "inject_context.py", "stage_done.py",
                        "validate_artifacts.py", "s5_precheck.py", "handoff_check.py", "judge_form.py")
# A refusal through a wrapper or an alias is invisible to `sites()`: it is visible here by name, and the file must be on
# the blocking path or the test is red.
# (`_block` is not listed: the two `_block` helpers of the package format text, they refuse nothing.)
WRAPPER_RE = re.compile(r"^_+deny$")

CLASSES = ("shape", "xref", "word-list", "meaning-proxy", "meaning", "safety")
OWNERS = ("data", "judgment", "intent")
BREACH_CLASSES = ("word-list", "meaning-proxy", "meaning")
CONDUCTOR = "conductor"
# Every top-level ceiling key the census must hold. A vanished key, or `ratchet: {}`, is red HERE: the commit gate passes a
# disappearing ceiling under `judgment: none`, so the guard against removing the guard is this test (critic t-1779 Q2).
REQUIRED_CEILING_KEYS = ("word-list", "meaning-proxy", "meaning", "safety", "breach", "blocks_overrides",
                         "blocking_per_role")
CLASS_CEILING_KEYS = ("word-list", "meaning-proxy", "meaning", "safety")
# The `meaning` ceiling is a constant of the test, not data: the census cannot raise it (as ANCHOR_FLOOR of A26). The value
# is the `meaning` count of the first census; X7-1 brings it down to 0. It only goes down, by an edit of this line.
MEANING_CEILING = 24


# --- reading the package -------------------------------------------------------------------------------------------
def roles_of(root: Path) -> list:
    """The role names: the file names of agents/*.md (the one reader, `role_load.agent_roles`), plus the conductor."""
    return role_load.agent_roles(Path(root)) + [CONDUCTOR]


def scan_files(root: Path) -> list:
    """Names (posix, relative to scripts/) of every scanned file: SCAN_ROOT/**/*.py minus SCAN_EXCLUDE."""
    base = Path(root) / SCAN_ROOT
    out = []
    for path in sorted(base.rglob("*.py")):
        rel = path.relative_to(base)
        if any(part in SCAN_EXCLUDE for part in rel.parts[:-1]):
            continue
        out.append(rel.as_posix())
    return out


def _facts(tree: ast.AST) -> tuple:
    """(functions, calls, imports) of one file from ONE walk (the machine measured 138 s for the scan with several walks)."""
    funcs, calls, imports = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)
        elif isinstance(node, ast.Call):
            calls.append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
    return funcs, calls, imports


def _judge_names(imports: list) -> tuple:
    """(module aliases {local name: module}, direct names {local name}) the file binds to the judge modules."""
    modules, direct = {}, set()
    for node in imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in JUDGE_CALLS:
                    modules[alias.asname or alias.name] = alias.name
        elif node.module in JUDGE_CALLS and not node.level:
            for alias in node.names:
                if alias.name in JUDGE_CALLS[node.module]:
                    direct.add(alias.asname or alias.name)
    for name in JUDGE_CALLS:
        modules.setdefault(name, name)
    return modules, direct


def _judge_call_lines(calls: list, modules: dict, direct: set) -> list:
    out = []
    for node in calls:
        f = node.func
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in modules
                and f.attr in JUDGE_CALLS[modules[f.value.id]]):
            out.append(node.lineno)
        elif isinstance(f, ast.Name) and f.id in direct:
            out.append(node.lineno)
    return out


def _alias_refusals(imports: list) -> set:
    """Local names bound to `deny`/`block` under another name (`from hooklib import deny as refuse`)."""
    out = set()
    for node in imports:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in refusal_registry.REFUSAL_CALLS and alias.asname and alias.asname != alias.name:
                    out.add(alias.asname)
    return out


def read_package(root: Path, files: list) -> dict:
    """{'trees': {file: ast}, 'errors': [str]}: a file that does not parse is named and makes the test red, never skipped."""
    trees, errors = {}, []
    for name in files:
        path = Path(root) / SCAN_ROOT / name
        try:
            trees[name] = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{SCAN_ROOT}/{name} does not parse ({exc.msg}, line {exc.lineno}): the census cannot read it - "
                          "repair the file; a file the scan cannot read is never skipped")
    return {"trees": trees, "errors": errors}


def stage_rows(root: Path) -> dict:
    """{'detectors': {script: [(stage, role)]}, 'advice': {script: [stage]}} from references/stages.json (absent: empty)."""
    path = Path(root) / "references" / "stages.json"
    out = {"detectors": {}, "advice": {}}
    if not path.is_file():
        return out
    data = json.loads(path.read_text(encoding="utf-8"))
    for stage in data.get("stages") or []:
        sid = str(stage.get("id"))
        for role, scripts in (stage.get("detectors") or {}).items():
            for script in scripts:
                out["detectors"].setdefault(str(script), []).append((sid, str(role)))
        for script in stage.get("advice") or []:
            out["advice"].setdefault(str(script), []).append(sid)
    return out


def blocking_detector_files(rows: dict) -> set:
    """Scripts a stage lists under `detectors` and not under that stage's `advice`: their errors become a refusal."""
    out = set()
    for script, places in rows["detectors"].items():
        for sid, _role in places:
            if sid not in rows["advice"].get(script, []):
                out.add(script)
    return out


def units_of(root: Path, files: list, registry=(), entry_files=BLOCKING_ENTRY_FILES) -> dict:
    """{(file, function): {'via': set, 'spans': [(start, end)], 'blocks': bool, 'refs': set}} plus the problems found.

    `blocks` (b1) a refusal site of `refusal_registry.sites(files=...)` sits in the unit (by the scanner's `function`, or by its
    line inside the unit's span - a nested unit is then judged on its own lines, an error toward a lone EXTRA `true`);
    (b2) the file is on the blocking path: BLOCKING_ENTRY_FILES, or a `detectors` script that is not an adviser."""
    pkg = read_package(root, files)
    trees = pkg["trees"]
    srows = stage_rows(root)
    blocking_files = set(entry_files) | blocking_detector_files(srows)
    seen = refusal_registry.sites(plugin_root=Path(root), files=sorted(trees))
    sites_by_file = {}
    for s in seen:
        sites_by_file.setdefault(s["file"], []).append(s)
    units, problems = {}, list(pkg["errors"])

    def add(file, function, via, span=None):
        u = units.setdefault((file, function), {"via": set(), "spans": [], "blocks": False, "refs": set()})
        u["via"].add(via)
        if span:
            u["spans"].append(span)

    for file, tree in trees.items():
        funcs, calls, imports = _facts(tree)
        modules, direct = _judge_names(imports)
        judge_lines = _judge_call_lines(calls, modules, direct)
        for node in funcs:
            span = (node.lineno, getattr(node, "end_lineno", node.lineno))
            if UNIT_NAME_RE.search(node.name):
                add(file, node.name, "u1", span)
            if any(span[0] <= line <= span[1] for line in judge_lines):
                add(file, node.name, "u2", span)
        for s in sites_by_file.get(file, []):
            add(file, s["function"], "u3")
        # a refusal through a wrapper or an alias: invisible to sites(); the file must stand on the blocking path
        wrappers = _alias_refusals(imports)
        hidden = [n for n in calls if isinstance(n.func, ast.Name) and (WRAPPER_RE.match(n.func.id) or n.func.id in wrappers)]
        if hidden and file not in blocking_files:
            problems.append(f"C5 {SCAN_ROOT}/{file}:{hidden[0].lineno} refuses through `{hidden[0].func.id}(...)`, which "
                            "`refusal_registry.sites()` cannot see: refusal through a wrapper is not visible: add the file "
                            "to BLOCKING_ENTRY_FILES (a deliberate edit of this test), or refuse through `deny`/`block`")
    # stages.json rows: a unit only for a script with no function-units; otherwise a ref on the functions
    for script, places in sorted(srows["detectors"].items()):
        if script not in trees:
            continue
        tokens = {f"stages.json:{sid}/{role}" for sid, role in places}
        mine = [k for k in units if k[0] == script]
        if not mine:
            add(script, "<script>", "stages")
            mine = [(script, "<script>")]
        for k in mine:
            units[k]["refs"] |= tokens
    for entry in registry:
        file, function = entry["file"], entry["function"]
        if file in trees:
            add(file, function, "a24")
            units[(file, function)]["refs"].add(f"A24:{entry['id']}")
    for (file, function), u in units.items():
        if file in blocking_files:
            u["blocks"] = True
        for s in sites_by_file.get(file, []):
            if s["function"] == function or any(a <= s["line"] <= b for a, b in u["spans"]):
                u["blocks"] = True
    return {"units": units, "problems": problems, "blocking_files": sorted(blocking_files), "sites": len(seen),
            "files": sorted(trees)}


# --- the census against the package --------------------------------------------------------------------------------
def effective_blocks(unit: dict, row: dict) -> bool:
    return bool(unit["blocks"]) and row.get("blocks_override") is not False


def higher_class(a, b):
    """The class that wins when two readings meet on one unit (E-A2): the earlier in CLASS_ORDER; an unknown class loses."""
    rank = {c: i for i, c in enumerate(CLASS_ORDER)}
    return a if rank.get(a, len(CLASS_ORDER)) <= rank.get(b, len(CLASS_ORDER)) else b


def _c1(census: dict, units: dict, probs: dict) -> dict:
    """C1: one row per unit and one unit per row, the `ref` ids. Returns {(file, function): row}."""
    rows = {}
    for row in census.get("rows") or []:
        key = (row.get("file"), row.get("function"))
        if key in rows:
            keep = higher_class(rows[key].get("class"), row.get("class"))
            probs["C1"].append(f"two rows for `{key[0]}::{key[1]}`: a unit has one row, and the higher class wins "
                               f"({' > '.join(CLASS_ORDER)}): keep the `{keep}` row, delete the other")
        rows[key] = row
    for key, u in sorted(units.items()):
        if key not in rows:
            probs["C1"].append(f"{key[0]}::{key[1]} is a check unit ({'/'.join(sorted(u['via']))}) with no row in "
                               "judgment-census.json: add a row {file, function, class, roles, owner} - the class is a "
                               "judgment about what the unit decides, never defaulted")
    for key in sorted(rows, key=str):
        if key not in units:
            probs["C1"].append(f"stale row `{key[0]}::{key[1]}`: no such check unit any more - remove the row, or move it to "
                               "the function that took its place (a row is never dropped silently)")
    for key, u in sorted(units.items()):
        row = rows.get(key)
        if row is None:
            continue
        want = {t for t in u["refs"]}
        have = {t.strip() for t in str(row.get("ref") or "").split(",") if t.strip()}
        for t in sorted(want - have):
            probs["C1"].append(f"{key[0]}::{key[1]}: `ref` lacks `{t}` - the unit is registered there already, so the row "
                               "carries the id and the registered unit is not counted twice")
    return rows


def _c2(rows: dict, units: dict, roles: list, probs: dict) -> None:
    """C2: the form of every row."""
    known_roles = set(roles)
    for key, row in sorted(rows.items(), key=lambda kv: str(kv[0])):
        name = f"{key[0]}::{key[1]}"
        if row.get("class") not in CLASSES:
            probs["C2"].append(f"{name}: class {row.get('class')!r} is not one of {list(CLASSES)}: use one of them")
        if row.get("owner") not in OWNERS:
            probs["C2"].append(f"{name}: owner {row.get('owner')!r} is not one of {list(OWNERS)}")
        rr = row.get("roles")
        if not isinstance(rr, list) or not rr:
            probs["C2"].append(f"{name}: `roles` must be a non-empty list of roles (or `conductor`) the unit stands in front of")
        else:
            for r in rr:
                if r not in known_roles:
                    probs["C2"].append(f"{name}: role {r!r} is not a file of agents/*.md and not `conductor`")
        if "blocks_override" in row:
            if row["blocks_override"] is not False:
                probs["C2"].append(f"{name}: `blocks_override` may only be false (a unit is never declared blocking by hand)")
            if not str(row.get("note") or "").strip():
                probs["C2"].append(f"{name}: `blocks_override: false` needs a one-line `note` saying why this unit does not "
                                   "refuse the work")
            elif key in units and not units[key]["blocks"]:
                probs["C2"].append(f"{name}: `blocks_override` on a unit that does not block: remove the override")


def _c3(census: dict, rows: dict, units: dict, roles: list, probs: dict) -> dict:
    """C3: the ratchet is dense and only goes down. Returns the counts the totals and C4 read."""
    known_roles = set(roles)
    counts = {c: 0 for c in CLASSES}
    breach, overrides = [], 0
    per_role = {r: 0 for r in roles}
    for key, row in rows.items():
        u = units.get(key)
        if row.get("class") in counts:
            counts[row["class"]] += 1
        if "blocks_override" in row:
            overrides += 1
        if u is not None and effective_blocks(u, row):
            if row.get("class") in BREACH_CLASSES:
                breach.append(f"{key[0]}::{key[1]}")
            for r in row.get("roles") or []:
                if r in per_role:
                    per_role[r] += 1
    ratchet = census.get("ratchet")
    if not isinstance(ratchet, dict) or not ratchet:
        probs["C3"].append("`ratchet` is missing or empty: the census holds the ceilings "
                           f"{list(REQUIRED_CEILING_KEYS)}; restore the object - a ratchet never disappears")
        ratchet = {}
    for key in REQUIRED_CEILING_KEYS:
        if key not in ratchet:
            probs["C3"].append(f"ceiling `{key}` is missing from `ratchet`: add it at the current count; a vanished ceiling "
                               "is a lifted guard")
    for key in ratchet:
        if key not in REQUIRED_CEILING_KEYS:
            probs["C3"].append(f"unknown key `ratchet.{key}`: the ceilings are {list(REQUIRED_CEILING_KEYS)}")

    def compare(label, count, ceiling, names=()):
        if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < 0:
            probs["C3"].append(f"ceiling `{label}` is {ceiling!r}: expected an integer >= 0")
        elif count > ceiling:
            probs["C3"].append(f"`{label}` is {count}, above its ceiling {ceiling}: a ratchet only shrinks - remove the "
                               f"new ones or raise nothing; the rows: {', '.join(sorted(names)[:12]) or '-'}")
        elif count < ceiling:
            probs["C3"].append(f"`{label}` is {count}, below its ceiling {ceiling}: lower the ceiling to {count} (the "
                               "ratchet is dense and only shrinks)")

    by_class = {c: [f"{k[0]}::{k[1]}" for k, r in rows.items() if r.get("class") == c] for c in CLASS_CEILING_KEYS}
    for key in CLASS_CEILING_KEYS:
        if key in ratchet:
            compare(key, counts[key], ratchet[key], by_class[key])
    if "breach" in ratchet:
        compare("breach", len(breach), ratchet["breach"], breach)
    if "blocks_overrides" in ratchet:
        compare("blocks_overrides", overrides, ratchet["blocks_overrides"],
                [f"{k[0]}::{k[1]}" for k, r in rows.items() if "blocks_override" in r])
    bpr = ratchet.get("blocking_per_role")
    if "blocking_per_role" in ratchet:
        if not isinstance(bpr, dict):
            probs["C3"].append("`blocking_per_role` must be an object {role: ceiling}")
        else:
            for r in roles:
                if r not in bpr:
                    probs["C3"].append(f"`blocking_per_role` has no key for `{r}`: add the line `{r}: 0` (or its count) - "
                                       "a role without blocking units is `0`, never a missing key")
                else:
                    compare(f"blocking_per_role.{r}", per_role[r], bpr[r])
            for r in bpr:
                if r not in known_roles:
                    probs["C3"].append(f"stale line `blocking_per_role.{r}`: no such role in agents/*.md - rename the key in "
                                       "the commit that renames the role file, or remove it")
    return {"counts": counts, "breach": breach, "overrides": overrides, "per_role": per_role, "by_class": by_class,
            "ratchet": ratchet}


def _c4(got: dict, ceiling_meaning: int, probs: dict) -> None:
    """C4: the meaning ceiling is the test's constant."""
    ratchet, counts, by_class = got["ratchet"], got["counts"], got["by_class"]
    if isinstance(ratchet.get("meaning"), int) and ratchet["meaning"] > ceiling_meaning:
        probs["C4"].append(f"`ratchet.meaning` is {ratchet['meaning']}, above MEANING_CEILING {ceiling_meaning} of this test: "
                           "the census cannot raise it - only an edit of the constant can, and a diff of the test is what "
                           "the critic reads")
    if counts["meaning"] > ceiling_meaning:
        probs["C4"].append(f"{counts['meaning']} rows are class `meaning`, above MEANING_CEILING {ceiling_meaning}: "
                           f"{', '.join(sorted(by_class['meaning'])[:12])}")


def analyse(root: Path, census: dict, roles=None, registry=None, entry_files=BLOCKING_ENTRY_FILES,
            meaning_ceiling=None) -> dict:
    """{'problems': {C1..C5: [text]}, 'totals': {...}}. Every problem names the thing, what was expected and the door."""
    root = Path(root)
    roles = list(roles if roles is not None else roles_of(root))
    registry = refusal_registry.REGISTRY if registry is None else registry
    ceiling_meaning = MEANING_CEILING if meaning_ceiling is None else meaning_ceiling
    found = units_of(root, scan_files(root), registry, entry_files)
    units = found["units"]
    probs = {k: [] for k in ("C1", "C2", "C3", "C4", "C5")}
    for text in found["problems"]:
        probs["C5" if text.startswith("C5") else "C1"].append(text)
    rows = _c1(census, units, probs)
    _c2(rows, units, roles, probs)
    got = _c3(census, rows, units, roles, probs)
    _c4(got, ceiling_meaning, probs)
    totals = {"files": len(found["files"]), "units": len(units), "counts": got["counts"], "breach": len(got["breach"]),
              "breach_rows": sorted(got["breach"]), "blocks_overrides": got["overrides"], "blocking_per_role": got["per_role"],
              "blocking_units": sum(1 for k, u in units.items() if k in rows and effective_blocks(u, rows[k])),
              "sites": found["sites"], "blocking_files": found["blocking_files"]}
    return {"problems": probs, "totals": totals}


def totals_line(t: dict) -> str:
    counts = " ".join(f"{c}={t['counts'][c]}" for c in CLASSES)
    per_role = " ".join(f"{r}={n}" for r, n in sorted(t["blocking_per_role"].items()))
    return (f"census: {t['files']} files scanned, {t['units']} units; {counts}; breach={t['breach']}; "
            f"blocks_overrides={t['blocks_overrides']}; blocking_per_role: {per_role}; "
            f"SCAN_ROOT={SCAN_ROOT!r} SCAN_EXCLUDE={SCAN_EXCLUDE!r}")


BLIND_SPOT = ("blind spot: class `meaning` is a hand label; a unit that judges meaning but is labelled `word-list` or `shape` "
              "is not seen by MEANING_CEILING - the critic's question 11 and calibration check 41 (d) catch it; "
              "a subclass of `ValueError` or `StateConflict` raised by its own name is invisible to `refusal_registry.sites` "
              "(it matches the literal names): legitimate when the subclass is caught and never reaches a role, but a subclass "
              "chosen to keep a ratchet down is not seen - the critic's question 11 and calibration check 41 catch it")


def load_census() -> dict:
    return json.loads(CENSUS_PATH.read_text(encoding="utf-8"))


# --- the tests (pytest functions, also run as a script) -------------------------------------------------------------
_REAL: dict = {}


def _real() -> dict:
    if "r" not in _REAL:                       # one scan of the package serves every check below
        _REAL["r"] = analyse(harness.PLUGIN_ROOT, load_census())
    return _REAL["r"]


def _fail_text(found: list) -> str:
    return "\n  " + "\n  ".join(found[:15]) + (f"\n  ... {len(found) - 15} more" if len(found) > 15 else "")


def test_c1_every_unit_has_a_row_and_every_row_a_unit() -> None:
    found = _real()["problems"]["C1"]
    assert not found, _fail_text(found)


def test_c2_every_row_is_well_formed() -> None:
    found = _real()["problems"]["C2"]
    assert not found, _fail_text(found)


def test_c3_the_ratchet_is_dense_and_only_shrinks() -> None:
    found = _real()["problems"]["C3"]
    assert not found, _fail_text(found)


def test_c4_the_meaning_ceiling_is_the_tests_constant() -> None:
    found = _real()["problems"]["C4"]
    assert not found, _fail_text(found)


def test_c5_no_refusal_hides_behind_a_wrapper() -> None:
    found = _real()["problems"]["C5"]
    assert not found, _fail_text(found)


def test_c6_totals_line() -> None:
    result = _real()
    t = result["totals"]
    print(totals_line(t))
    print(BLIND_SPOT)
    print("census breaches: " + (", ".join(t["breach_rows"]) or "none"))
    assert t["files"] > 0, "the scan found no file: SCAN_ROOT/SCAN_EXCLUDE select nothing"
    assert "refusal_registry" in sys.modules, "the census reads refusal sites through refusal_registry.sites()"


def test_scan_constants_are_the_specs() -> None:
    assert (SCAN_ROOT, SCAN_EXCLUDE) == ("scripts", ("tests",)), "the scan was narrowed or widened: a deliberate edit, named"
    census_text = CENSUS_PATH.read_text(encoding="utf-8")
    assert "scan_globs" not in census_text, "the census data holds no file list: the scan is a constant of the test"


# C5 negative controls: synthetic packages in a temp dir
def _package(files: dict, agents=("qa-x",), stages=None) -> Path:
    root = harness.temp_dir("qa-census-")
    scripts = root / SCAN_ROOT
    scripts.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (scripts / name).write_text(text, encoding="utf-8")
    (root / "agents").mkdir(exist_ok=True)
    for a in agents:
        (root / "agents" / f"{a}.md").write_text("# role\n", encoding="utf-8")
    if stages is not None:
        (root / "references").mkdir(exist_ok=True)
        (root / "references" / "stages.json").write_text(json.dumps(stages), encoding="utf-8")
    return root


def _census(rows=(), **ratchet) -> dict:
    base = {"word-list": 0, "meaning-proxy": 0, "meaning": 0, "safety": 0, "breach": 0, "blocks_overrides": 0,
            "blocking_per_role": {"qa-x": 0, "conductor": 0}}
    base.update(ratchet)
    return {"schema": 1, "ratchet": base, "rows": list(rows)}


def _row(file, function, cls="shape", roles=("qa-x",), owner="data", **extra) -> dict:
    return {"file": file, "function": function, "class": cls, "roles": list(roles), "owner": owner, **extra}


def _run(files: dict, census: dict, **kw) -> dict:
    root = _package(files, stages=kw.pop("stages", None))
    try:
        return analyse(root, census, registry=[], **kw)
    finally:
        harness.cleanup(root)


def _has(found: list, needle: str) -> bool:
    return any(needle in t for t in found)


NEUTRAL_DENY = "def judge_x(event):\n    deny('no')\n    return 1\n"


def test_neg_unit_with_no_row_is_c1() -> None:
    r = _run({"helpers_x.py": "def check_x(a):\n    return a\n"}, _census())
    assert _has(r["problems"]["C1"], "helpers_x.py::check_x is a check unit"), r["problems"]["C1"]
    assert "add a row" in r["problems"]["C1"][0]


def test_neg_every_check_name_family_is_a_unit_and_a_neutral_name_is_not() -> None:
    """t-1793 F1: the name forms `*_problems`, `validate*`, `refuse*`, a bare `check` / `run` are units (and the old `*_errors`
    control still is); a name outside every family, with no judge call and no refusal site, is not."""
    names = ["x_problems", "_x_problems", "validate", "validate_x", "_validate_x", "refuse", "refuse_x", "_refuse_x", "check", "run",
             "_run", "x_errors", "x_check"]
    src = "".join(f"def {n}(a):\n    return a\n\n\n" for n in names) + "def tidy(a):\n    return a\n"
    c1 = _run({"helpers_x.py": src}, _census())["problems"]["C1"]
    for n in names:
        assert _has(c1, f"helpers_x.py::{n} is a check unit (u1)"), (n, c1)
    assert not _has(c1, "helpers_x.py::tidy"), "a neutral name with no judge call and no refusal is not a unit (the blind spot)"


def test_neg_two_rows_keep_the_higher_class_and_safety_sits_between_word_list_and_xref() -> None:
    """t-1793 F3: meaning > meaning-proxy > word-list > safety > xref > shape; the C1 refusal names the row to keep."""
    assert CLASS_ORDER == ("meaning", "meaning-proxy", "word-list", "safety", "xref", "shape")
    for low, high in (("shape", "safety"), ("xref", "safety"), ("safety", "word-list"), ("safety", "meaning-proxy"),
                      ("word-list", "meaning-proxy"), ("shape", "xref")):
        assert higher_class(low, high) == higher_class(high, low) == (high if CLASS_ORDER.index(high) < CLASS_ORDER.index(low) else low)
    assert higher_class("safety", "xref") == "safety" and higher_class("safety", "word-list") == "word-list"
    src = "def check_x(a):\n    return a\n"
    for first, second, keep in (("shape", "safety", "safety"), ("safety", "word-list", "word-list"), ("xref", "safety", "safety")):
        two = _census([_row("helpers_x.py", "check_x", cls=first), _row("helpers_x.py", "check_x", cls=second)])
        c1 = _run({"helpers_x.py": src}, two)["problems"]["C1"]
        assert _has(c1, f"keep the `{keep}` row"), (first, second, c1)


def test_neg_neutral_file_with_judge_function_calling_deny_is_c1_and_blocks() -> None:
    r = _run({"helpers_x.py": NEUTRAL_DENY}, _census())
    assert _has(r["problems"]["C1"], "helpers_x.py::judge_x"), r["problems"]["C1"]
    row = _row("helpers_x.py", "judge_x", cls="word-list")
    r2 = _run({"helpers_x.py": NEUTRAL_DENY}, _census([row], **{"word-list": 1, "breach": 1,
              "blocking_per_role": {"qa-x": 1, "conductor": 0}}))
    assert r2["totals"]["blocking_units"] == 1 and r2["totals"]["breach"] == 1, r2["totals"]
    assert not any(r2["problems"][k] for k in r2["problems"]), r2["problems"]


def test_neg_neutral_function_calling_the_judge_is_c1_by_u2() -> None:
    src = "import judge\n\n\ndef opine(state):\n    return judge.ask_one(state, 'j')\n"
    r = _run({"helpers_x.py": src}, _census())
    assert _has(r["problems"]["C1"], "helpers_x.py::opine is a check unit (u2)"), r["problems"]["C1"]


def test_neg_wrapper_refusal_outside_the_blocking_path_is_red() -> None:
    src = "def _deny(m):\n    return m\n\n\ndef gate(x):\n    _deny('nope')\n"
    r = _run({"helpers_x.py": src}, _census())
    assert _has(r["problems"]["C5"], "not visible: add the file to BLOCKING_ENTRY_FILES"), r["problems"]
    alias = "from hooklib import deny as refuse\n\n\ndef gate(x):\n    refuse('nope')\n"
    r2 = _run({"helpers_x.py": alias}, _census())
    assert _has(r2["problems"]["C5"], "not visible"), r2["problems"]
    r3 = _run({"helpers_x.py": src}, _census(), entry_files=("helpers_x.py",))
    assert not r3["problems"]["C5"], "a file on the blocking path may refuse through a wrapper"


def test_neg_nested_and_module_level_refusals_are_units() -> None:
    nested = "def outer(x):\n    def inner():\n        deny('no')\n    return inner\n"
    r = _run({"helpers_x.py": nested}, _census())
    assert _has(r["problems"]["C1"], "helpers_x.py::outer"), r["problems"]["C1"]
    module = "deny('stop')\n"
    r2 = _run({"helpers_x.py": module}, _census())
    assert _has(r2["problems"]["C1"], "helpers_x.py::<module>"), r2["problems"]["C1"]


def test_neg_unparsable_file_is_named_and_red() -> None:
    r = _run({"broken_x.py": "def (:\n"}, _census())
    assert _has(r["problems"]["C1"], "broken_x.py does not parse"), r["problems"]


def test_neg_stale_row_and_two_rows() -> None:
    r = _run({"helpers_x.py": "x = 1\n"}, _census([_row("helpers_x.py", "check_gone")]))
    assert _has(r["problems"]["C1"], "stale row") and _has(r["problems"]["C1"], "remove the row"), r["problems"]
    src = "def check_x(a):\n    return a\n"
    two = _census([_row("helpers_x.py", "check_x"), _row("helpers_x.py", "check_x", cls="xref")])
    assert _has(_run({"helpers_x.py": src}, two)["problems"]["C1"], "two rows")


def test_neg_class_opinion_override_without_note_and_bad_form_are_c2() -> None:
    src = "def check_x(a):\n    return a\n"
    assert _has(_run({"helpers_x.py": src}, _census([_row("helpers_x.py", "check_x", cls="opinion")]))["problems"]["C2"],
                "not one of")
    no_note = _row("helpers_x.py", "check_x", blocks_override=False)
    assert _has(_run({"helpers_x.py": src}, _census([no_note], blocks_overrides=1))["problems"]["C2"], "needs a one-line `note`")
    true_override = _row("helpers_x.py", "check_x", blocks_override=True, note="n")
    assert _has(_run({"helpers_x.py": src}, _census([true_override], blocks_overrides=1))["problems"]["C2"], "may only be false")
    assert _has(_run({"helpers_x.py": src}, _census([_row("helpers_x.py", "check_x", roles=[])]))["problems"]["C2"], "non-empty")
    assert _has(_run({"helpers_x.py": src}, _census([_row("helpers_x.py", "check_x", owner="boss")]))["problems"]["C2"], "owner")
    assert _has(_run({"helpers_x.py": src}, _census([_row("helpers_x.py", "check_x", roles=["qa-ghost"])]))["problems"]["C2"], "qa-ghost")
    useless = _row("helpers_x.py", "check_x", blocks_override=False, note="parser")
    assert _has(_run({"helpers_x.py": src}, _census([useless], blocks_overrides=1))["problems"]["C2"], "does not block")


def test_neg_raised_ceilings_roles_and_lowered_counts_are_c3() -> None:
    src = "def check_x(a):\n    return a\n"
    rows = [_row("helpers_x.py", "check_x", cls="word-list")]
    # the count of word-list (1) is above a ceiling left at 0: the census got a word-list unit without lifting a ceiling
    r = _run({"helpers_x.py": src}, _census(rows))
    assert _has(r["problems"]["C3"], "`word-list` is 1, above its ceiling 0"), r["problems"]["C3"]
    safe = [_row("helpers_x.py", "check_x", cls="safety")]
    assert _has(_run({"helpers_x.py": src}, _census(safe))["problems"]["C3"], "`safety` is 1, above its ceiling 0")
    # a ceiling above the count: the ratchet is dense
    assert _has(_run({"helpers_x.py": src}, _census([_row("helpers_x.py", "check_x")], safety=2))["problems"]["C3"],
                "lower the ceiling to 0")
    # a role with no key
    census = _census([_row("helpers_x.py", "check_x")])
    del census["ratchet"]["blocking_per_role"]["qa-x"]
    assert _has(_run({"helpers_x.py": src}, census)["problems"]["C3"], "add the line `qa-x: 0`")
    census = _census([_row("helpers_x.py", "check_x")])
    census["ratchet"]["blocking_per_role"]["qa-old"] = 0
    assert _has(_run({"helpers_x.py": src}, census)["problems"]["C3"], "stale line `blocking_per_role.qa-old`")
    # a breach above its ceiling, a blocking role count above its ceiling
    breach_src = "def check_x(a):\n    deny('no')\n"
    breach_rows = [_row("helpers_x.py", "check_x", cls="meaning-proxy")]
    r = _run({"helpers_x.py": breach_src}, _census(breach_rows, **{"meaning-proxy": 1}))
    assert _has(r["problems"]["C3"], "`breach` is 1, above its ceiling 0"), r["problems"]["C3"]
    assert _has(r["problems"]["C3"], "`blocking_per_role.qa-x` is 1, above its ceiling 0")


def test_neg_vanished_top_level_ceiling_or_empty_ratchet_is_red() -> None:
    src = "x = 1\n"
    for key in ("word-list", "meaning-proxy", "meaning", "safety", "breach", "blocks_overrides", "blocking_per_role"):
        census = _census()
        del census["ratchet"][key]
        r = _run({"helpers_x.py": src}, census)
        assert _has(r["problems"]["C3"], f"ceiling `{key}` is missing"), (key, r["problems"]["C3"])
    empty = _census()
    empty["ratchet"] = {}
    r = _run({"helpers_x.py": src}, empty)
    assert _has(r["problems"]["C3"], "`ratchet` is missing or empty"), r["problems"]["C3"]
    gone = _census()
    del gone["ratchet"]
    assert _has(_run({"helpers_x.py": src}, gone)["problems"]["C3"], "`ratchet` is missing or empty")


def test_neg_meaning_ceiling_is_not_data() -> None:
    src = "def check_x(a):\n    return a\n"
    rows = [_row("helpers_x.py", "check_x", cls="meaning")]
    r = _run({"helpers_x.py": src}, _census(rows, meaning=1), meaning_ceiling=0)
    assert _has(r["problems"]["C4"], "above MEANING_CEILING"), r["problems"]
    # and the DATA can never lift the test's constant: a census ceiling above the constant is red on its own
    lifted = _run({"helpers_x.py": "x = 1\n"}, _census(meaning=3), meaning_ceiling=2)
    assert _has(lifted["problems"]["C4"], "`ratchet.meaning` is 3, above MEANING_CEILING 2"), lifted["problems"]
    ok = _run({"helpers_x.py": src}, _census(rows, meaning=1), meaning_ceiling=1)
    assert not ok["problems"]["C4"], ok["problems"]["C4"]


def test_neg_stage_row_counts_once() -> None:
    stages = {"stages": [{"id": "S2", "detectors": {"qa-x": ["tool_x.py", "sizing_x.py"]}, "advice": ["sizing_x.py"]}]}
    files = {"tool_x.py": "def check_x(a):\n    return a\n", "sizing_x.py": "X = 1\n"}
    r = _run(files, _census(), stages=stages)
    c1 = r["problems"]["C1"]
    assert _has(c1, "tool_x.py::check_x"), c1
    assert _has(c1, "sizing_x.py::<script>"), c1
    assert not _has(c1, "tool_x.py::<script>"), "a script with a function-unit is not a unit itself"
    rows = [_row("tool_x.py", "check_x", ref="stages.json:S2/qa-x"), _row("sizing_x.py", "<script>", ref="stages.json:S2/qa-x")]
    r2 = _run(files, _census(rows, blocking_per_role={"qa-x": 1, "conductor": 0}), stages=stages)
    assert not r2["problems"]["C1"], r2["problems"]["C1"]
    assert r2["totals"]["blocking_units"] == 1, "the adviser does not block, the detector does"


def blind_spot_names_subclass_gap() -> None:
    assert "subclass" in BLIND_SPOT, "BLIND_SPOT must name the subclass gap of refusal_registry.sites"
    assert "subclass" in load_census()["about"], "the census `about` must name the subclass gap"


TESTS = [
    test_c1_every_unit_has_a_row_and_every_row_a_unit, test_c2_every_row_is_well_formed,
    test_c3_the_ratchet_is_dense_and_only_shrinks, test_c4_the_meaning_ceiling_is_the_tests_constant,
    test_c5_no_refusal_hides_behind_a_wrapper, test_c6_totals_line, test_scan_constants_are_the_specs,
    test_neg_unit_with_no_row_is_c1, test_neg_every_check_name_family_is_a_unit_and_a_neutral_name_is_not,
    test_neg_two_rows_keep_the_higher_class_and_safety_sits_between_word_list_and_xref,
    test_neg_neutral_file_with_judge_function_calling_deny_is_c1_and_blocks,
    test_neg_neutral_function_calling_the_judge_is_c1_by_u2, test_neg_wrapper_refusal_outside_the_blocking_path_is_red,
    test_neg_nested_and_module_level_refusals_are_units, test_neg_unparsable_file_is_named_and_red,
    test_neg_stale_row_and_two_rows, test_neg_class_opinion_override_without_note_and_bad_form_are_c2,
    test_neg_raised_ceilings_roles_and_lowered_counts_are_c3, test_neg_vanished_top_level_ceiling_or_empty_ratchet_is_red,
    test_neg_meaning_ceiling_is_not_data, test_neg_stage_row_counts_once, blind_spot_names_subclass_gap,
]


def main() -> None:
    for fn in TESTS:
        try:
            fn()
            harness.check(fn.__name__, True)
        except AssertionError as exc:
            harness.check(fn.__name__, False, str(exc)[:1500])
    harness.finish("judgment_census")


if __name__ == "__main__":
    main()
