#!/usr/bin/env python3
"""Build a window's automation-manifest fragment FROM the tests' own markers, and merge it once.

On TP1-13797 the automator called `manifest_put.py` 39 times and typed every fragment by
hand: instance ids, `covers`, the pinned case versions, `then_bindings`, the unresolved rows —
each one a chance to spell a case twice, lose a `covers` entry on a re-send, or (as happened)
overwrite 36 `then_bindings` rows because that key is replaced whole. The facts all live in
the test code already, so the test code carries them as pytest markers and this script
reads them with `ast` (the test module is never imported) and writes the fragment the
contract asks for, then calls `manifest_put.py` exactly once.

The marker contract (registered in the project's pytest config — see `--help`):

  @pytest.mark.qa(case="<case id>", then=[1, 2], partition="P-zero",
                  obligations=["TS-3-O1"], shape="parameterize", note="why this shape")
      on a test function, a test class (every method), a module (`pytestmark`), or on one
      `pytest.param(..., marks=pytest.mark.qa(...))` of a parametrize list. Several `qa`
      markers on one function = one instance proving several cases. `case` is required;
      `then` are the numbers of the case's Then clauses this test asserts (`then={1: "579-584"}`
      pins a clause to its own lines instead of the function's assert span); `partition` names
      the case partition the instance proves (default: the parametrize id); `obligations`
      must be obligation ids of the case's plan row. A test function without any `qa`
      marker is not the factory's business and is ignored.

  @pytest.mark.qa_unresolved(case="<case id>", reason="impossible", detail="...")
      at module level (`pytestmark = [...]`) for a case with no test at all; on a function
      with `then=[1]` for the clauses that test cannot assert, or `partition="P-x"` for a
      slice, or bare for the whole case (`handed_to_person`, `contradicts_requirement`).
      `reason` is from the closed list; `blocked_by_env` carries `remedy={...}`.
      `reason="expectation_unconfirmed"` (P20) is for a Then whose expected value nobody confirmed
      (its oracle is `unknown`): `then=[n]`, `question="<id in open_questions>"`, optionally
      `observed=<the value the test saw but did not assert>`; it writes only a `then_bindings` row.
      With no `then` but a `question`, it is a whole-case row: one binding per clause plus an
      `unresolved[]` row carrying the question (the person's debt, never a delivery hold).
      `instance_ids=["test_x[a]"]` makes the `unresolved[]` row a slice of its case: the tests it speaks about
      (any reason but `blocked_by_check`, never beside `then`); `thens=[n]` names the red Then of a
      `contradicts_requirement` row, and `field_absent={then, field, read_from, shape_ref}` (a response without the field the Then
      reads) rides on that row. The reason `blocked_by_check` is a Then behind a red assert of its own test
      (`then=[n]`, `blocking_check="<red case or test id>"`, `detail`), on the test function or `pytest.param`
      that holds it: one `then_bindings` row per instance, never an `unresolved[]` row.

What is derived, never typed: instance ids (`<function>[<param id>]`, `contract.instance_id`),
`covers`, `case_version_links` from `state/story-case-links.json`, `requirements`/`plan_row`
from the case file, `obligation_refs` with the plan's obligation hash, `assertion_ref` from
the function's assert span, `status` from the newest run block of that instance, and the
`then_bindings` merge (rows about the same case+clause or the same instance are replaced,
every other row is kept; a `blocked_by_check` or `contradicts_requirement` row a role sent by hand is kept even
then, unless this run writes the same Then of the same test). A hand-written fragment keeps working beside this.

After the write it PRINTS the row form: the fields the S5 window record and the test run demand of each row it
wrote (`window_record.REQUIRED_ROW_FIELDS`) that are still missing, as a `{"tests": [{"instance_id": ..., "<field>": null}]}`
skeleton for the role to fill and send through `manifest_put.py --fragment`. It is never part of the fragment: a `null`
in a fragment would overwrite what the role wrote.

  manifest_from_tests.py --task T --dispatch ID --file tests/test_x.py [--file data.py] [--dry-run] [--json]

Exit 0 written (or dry run); 2 a refusal about the markers, the story or the plan — the message
names the file, the line and the fix; 3 `manifest_put.py` refused the merge.
"""
import argparse
import ast
import contextlib
import copy
import hashlib
import io
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import load_config, project_root, story_root  # noqa: E402
import contract as C  # noqa: E402
import question_register as QR  # noqa: E402
from event_store import content_hash  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

EXIT_REFUSED = 2
EXIT_PUT_FAILED = 3

# The marker names are the factory's own closed variety and live in data, read by this generator
# and by diff_scope.py (a case marker edit is cosmetic there): one source (FR-13, FR-17).
MARKERS_REL = "references/case-markers.json"
MARKERS_FILE = Path(__file__).resolve().parents[1] / "references" / "case-markers.json"


class MarkersUnavailable(ValueError):
    """The case-marker names cannot be read - names the file and the way to get it back (the
    sibling of proof_level.LevelsUnavailable)."""


def load_case_markers(path=None) -> dict:
    """{"case": ..., "unresolved": ...} from `references/case-markers.json`; a missing, unreadable
    or shape-broken file is `MarkersUnavailable`, never a traceback of another kind."""
    try:
        doc = json.loads(Path(path or MARKERS_FILE).read_text(encoding="utf-8"))
        names = {"case": doc["pytest"]["case"], "unresolved": doc["pytest"]["unresolved"]}
        if not all(isinstance(v, str) and v.isidentifier() for v in names.values()):
            raise ValueError("a marker name is not an identifier")
        return names
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MarkersUnavailable(
            f"{MARKERS_REL} cannot be read ({type(exc).__name__}): it is the plugin's own list of the "
            "case marker names and is not something a project or a role edits; reinstall the plugin "
            "to bring it back") from None


try:
    _CASE_MARKERS = load_case_markers()
except MarkersUnavailable as _exc:
    if __name__ == "__main__":  # the CLI refuses with the door, not a traceback
        print(f"manifest_from_tests: {_exc}", file=sys.stderr)
        sys.exit(EXIT_REFUSED)
    raise
MARK_QA = _CASE_MARKERS["case"]
MARK_UNRESOLVED = _CASE_MARKERS["unresolved"]
# `base_checked="<file>::<function>"` (TQ1-18): where the base of a before/after comparison is asserted when the test does not
# assert it itself; the marker only carries it, `s5_precheck.check_relative_oracle` reads it from the test and judges that the
# function exists.
QA_KWARGS = ("case", "then", "partition", "obligations", "shape", "note", "base_checked")
FIELD_ABSENT_KEYS = ("then", "field", "read_from", "shape_ref")
UNRESOLVED_KWARGS = ("case", "reason", "detail", "then", "partition", "partitions", "remedy",
                     "question", "observed", "owner", "part", "instance_ids", "thens", "blocking_check", "field_absent")
# `expectation_unconfirmed` (t-227c, P20): a Then whose expected value nobody confirmed - an `unknown`
# oracle with an open question. It is the reason of a PER-THEN `then_bindings` row and, since t-269 D2, of a
# whole-case `unresolved[]` row that names its `question`. The word has ONE home (`contract.py`, in
# `UNRESOLVED_REASONS`, FR-13); this tuple is the ONE list of what a `qa_unresolved` marker accepts, and
# `stage_guard` reads it from here instead of keeping a literal copy that would drift.
EXPECTATION_UNCONFIRMED = C.EXPECTATION_UNCONFIRMED
UNRESOLVED_REASON_WORDS = tuple(C.UNRESOLVED_REASONS)
SHAPES_FALLBACK = ("reuse", "extend", "parameterize", "consolidate", "new")


def _vocabulary_shapes() -> tuple:
    """`test_shapes` of `handoffs/vocabulary.yaml` (SC1-14): the word list the S5 plan, its check and this generator all
    read, so a shape added there works here without an edit in Python (AR-1). The literal below stays as the offline
    fallback - a factory whose vocabulary file is missing or unreadable accepts what it always did - and a test asserts the
    two never diverge (the pattern of `role_digest._vocabulary_states`)."""
    try:
        import handoff
        words = handoff.vocabulary().get("test_shapes")
        return tuple(str(word) for word in words) if isinstance(words, list) and words else ()
    except Exception:
        return ()


SHAPES = _vocabulary_shapes() or SHAPES_FALLBACK
PENDING = "pending_run"
FRAGMENT_DIR = "manifest-fragments"
# What an assertion looks like in the projects this factory has met: a bare `assert`, a
# hamcrest/unittest call whose name starts with `assert`, and a `with pytest.raises(...)`.
ASSERT_CALL_PREFIXES = ("assert", "expect", "verify", "should")
RAISES_NAMES = ("raises", "warns", "deprecated_call")

# Formatted from the data, so the lines a project pastes name the markers this script reads.
_QA_LINE = f"{MARK_QA}({', '.join(QA_KWARGS)}): qa-factory case link"
_UNRESOLVED_LINE = f"{MARK_UNRESOLVED}({', '.join(UNRESOLVED_KWARGS)}): qa-factory unresolved case"
REGISTRATION_HELP = f"""
Registering the two markers so pytest does not warn (or, under --strict-markers, refuse):

  pytest.ini / setup.cfg [pytest] / tox.ini:
      markers =
          {_QA_LINE}
          {_UNRESOLVED_LINE}
  pyproject.toml [tool.pytest.ini_options]:
      markers = [
          "{_QA_LINE}",
          "{_UNRESOLVED_LINE}",
      ]
  or conftest.py:
      def pytest_configure(config):
          config.addinivalue_line("markers", "{_QA_LINE}")
          config.addinivalue_line("markers", "{_UNRESOLVED_LINE}")
"""


REFUSAL_LINES = 20      # lines of one refusal's text; the rest is counted, and `--json` lists all of them in `problems`
BOM = chr(0xFEFF)       # spelled out: no invisible character sits in this source
IMPORT_HOPS = 3        # import statements followed from a test file to the module that holds a parameter list


class Refusal(Exception):
    """A marker, a story record or the plan says something this script cannot write.

    `.problems` is the list of lines the refusal is made of - one for an ordinary refusal (its own text), all of them for the
    refusal that ends a read of the markers of a file (`_aggregate`); `--json` prints it beside `refusal` (AK4)."""

    def __init__(self, message: str = "", problems=None):
        super().__init__(message)
        self.problems = list(problems) if problems else [message]


def _aggregate(problems: list) -> Refusal:
    """ONE refusal for every marker problem found, without repeats: the problem itself when there is one (the text the script has
    always given), else one line per problem, at most `REFUSAL_LINES`, then `... and N more (--json lists all)`. Nothing is lost:
    `.problems` holds all of them (FR-1)."""
    unique = _unique(problems)
    if len(unique) == 1:
        return Refusal(unique[0], unique)
    shown = unique[:REFUSAL_LINES]
    tail = [f"... and {len(unique) - REFUSAL_LINES} more (--json lists all)"] if len(unique) > REFUSAL_LINES else []
    return Refusal("\n".join(shown + tail), unique)


# --- reading the test code ---------------------------------------------------------------------

def _literal(node, where: str):
    try:
        return ast.literal_eval(node)
    except Exception:
        raise Refusal(f"{where}: a marker argument must be a literal (a string, a number, a "
                      f"list or a dict of those), not `{ast.unparse(node)}`")


def _mark_name(node):
    """`qa` for `pytest.mark.qa(...)` / `pytest.mark.qa` / `mark.qa(...)`, else ''."""
    target = node.func if isinstance(node, ast.Call) else node
    if not isinstance(target, ast.Attribute):
        return ""
    owner = target.value
    if isinstance(owner, ast.Attribute) and owner.attr == "mark":
        return target.attr
    if isinstance(owner, ast.Name) and owner.id == "mark":
        return target.attr
    return ""


def _marker(node, where: str, problems=None):
    """(name, kwargs) of a factory marker, ('parametrize', node) for pytest's own, else None.

    A marker with something wrong is a refusal naming the first thing (the text the script has always given); with a `problems`
    list given, EVERY problem of this marker goes into it and the marker is skipped (None) - the caller reads on and refuses once
    at the end (EP1-25: three rounds of one refusal each, for one file)."""
    name = _mark_name(node)
    if name == "parametrize":
        return name, node
    if name not in (MARK_QA, MARK_UNRESOLVED):
        return None
    found: list = []
    if not isinstance(node, ast.Call):
        found.append(f"{where}: `@pytest.mark.{name}` needs its arguments — at least `case=`")
    elif node.args:
        found.append(f"{where}: `@pytest.mark.{name}(...)` takes keyword arguments only "
                     f"(`case=\"<case id>\"`, the id in the form your brief names), not positional ones")
    kwargs = {}
    if isinstance(node, ast.Call) and not found:
        allowed = QA_KWARGS if name == MARK_QA else UNRESOLVED_KWARGS
        bad = set()                     # keywords already refused: no second line about the same keyword
        for kw in node.keywords:
            if kw.arg not in allowed:
                found.append(f"{where}: `{name}` does not take `{kw.arg}` — it takes " + ", ".join(allowed))
                continue
            try:
                kwargs[kw.arg] = _literal(kw.value, where)
            except Refusal as exc:
                bad.add(kw.arg)
                found.append(str(exc))
        if "case" not in bad and not str(kwargs.get("case") or "").strip():
            found.append(f"{where}: `{name}` needs `case=\"<case id>\"`, the id in the form your brief names")
    if found:
        if problems is None:
            raise Refusal(found[0], found)
        problems.extend(found)
        return None
    kwargs["_where"] = where
    return name, kwargs


def _marks_of(nodes, where: str, problems=None) -> tuple:
    """(factory marks, parametrize nodes) out of a decorator list or a `pytestmark` value.
    `where` is `<file>:<line> <label>`; each mark is reported at its own line. With a `problems` list a malformed marker is added
    to it and left out; without, it is the refusal."""
    marks, params = [], []
    for node in nodes:
        head, _, label = where.partition(" ")
        rel = head.rsplit(":", 1)[0]
        here = f"{rel}:{getattr(node, 'lineno', 0) or head.rsplit(':', 1)[-1]} {label}".rstrip()
        found = _marker(node, here, problems)
        if not found:
            continue
        if found[0] == "parametrize":
            params.append(found[1])
        else:
            marks.append(found)
    return marks, params


class TestFile:
    """One test (or test-data) module read with `ast`.

    `scan=False` reads a module only for its names (`assignments`, the imports in `tree`): the module a parameter list is imported
    from. Its tests and markers are not the call's work - `build` would count them - so none is looked at. `root` is the project
    root the imports are resolved under (`build` sets it when the caller gave none). `problems` are the marker problems of the
    module level and of the classes, left for `build` to refuse once with the rest (EP1-25)."""

    def __init__(self, path: Path, rel: str, root=None, scan: bool = True):
        self.path, self.rel, self.root = path, rel, root
        self.problems: list = []
        self.imported: dict = {}        # resolved path -> the TestFile read for a parameter list, or the Refusal it earned
        self.imported_used: list = []   # log of the modules a parameter list was read from (a chain per list), in reading order
        raw = path.read_bytes()
        self.text = raw.decode("utf-8", errors="replace")
        if self.text.startswith(BOM):         # a BOM is not Python's business: the interpreter reads such a file
            self.text = self.text[1:]
        # The exact bytes, not the decoded text: `window_record.py` compares this sha
        # against `hashlib.sha256(path.read_bytes())` of the file it reads back.
        self.content_sha = hashlib.sha256(raw).hexdigest()
        try:
            self.tree = ast.parse(self.text, filename=str(path))
        except SyntaxError as exc:
            raise Refusal(f"{rel}:{exc.lineno}: does not parse as Python ({exc.msg})")
        except ValueError as exc:             # a NUL byte on an interpreter that raises it as ValueError, not SyntaxError
            raise Refusal(f"{rel}:1: does not parse as Python ({exc})")
        self.assignments: dict = {}
        self.module_marks: list = []
        self.functions: list = []  # (node, class node or None, class marks)
        for node in self.tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and node.value is not None:
                        self.assignments[target.id] = node.value
                        if target.id == "pytestmark":
                            values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) \
                                else [node.value]
                            if scan:
                                self.module_marks += _marks_of(values, f"{rel}:{node.lineno} pytestmark", self.problems)[0]
            elif not scan:
                continue
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                self.functions.append((node, None, []))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                cls_marks, _ = _marks_of(node.decorator_list, f"{rel}:{node.lineno} class {node.name}", self.problems)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                        self.functions.append((child, node, cls_marks))

    def where(self, node) -> str:
        return f"{self.rel}:{getattr(node, 'lineno', 0)}"


NO_READER_DOOR = "write this file's rows yourself with manifest_put.py --fragment"


class LanguageFile:
    """A test file that is not Python, read by `test_source.read_file` (EP1-37): the ONE reader of a test file by the data of
    its language (`references/detectors.json assertion_probes`). It carries what `build` asks of a `TestFile` (no tree, no
    markers) and, instead, `declarations` (the tests it found), `unread` (the calls it could not read, with their lines) and
    `why_not`. `no_entry` means the table was read and has no row for the suffix: the file is NOT read and that is said by
    name, never a refusal and never a pass (the owner's word: a language with no row is a note with a door). Any other
    `why_not` (a broken table, a reader defect) is a refusal by name: the field rule (FR-12) is on the flag, not on a phrase."""

    def __init__(self, path: Path, rel: str, root=None):
        import test_source
        self.path, self.rel, self.root = path, rel, root
        self.problems: list = []
        self.imported: dict = {}
        self.imported_used: list = []
        self.assignments: dict = {}
        self.module_marks: list = []
        self.functions: list = []
        self.tree = None
        try:
            self.content_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            self.content_sha = ""
        read = test_source.read_file(path, rel)
        self.language, self.declarations = read["language"], read["declarations"]
        self.unread, self.why_not, self.no_entry = read["unread"], read["why_not"], read["no_entry"]

    def where(self, node) -> str:
        return f"{self.rel}:{getattr(node, 'lineno', 0)}"


def _no_reader_note(tf) -> str:
    """The note of a file whose suffix has no row in the table (`tf.no_entry`): the one case that is a note, not a refusal."""
    suffix = Path(tf.rel).suffix.lower()
    return (f"{tf.rel}: no reader for {suffix or 'a file with no suffix'} in references/detectors.json assertion_probes, "
            "so nothing was read from it. The tests run by the project's command; " + NO_READER_DOOR
            + " (the row form is printed below). Its cases stay unbound until then")


def _auto_id(node, argname: str, index: int) -> str:
    """pytest's own id for a plain value: strings and numbers as they are, else `<arg><n>`."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, str):
            return value
        if value is None or isinstance(value, (bool, int, float)):
            return str(value)
    return f"{argname}{index}"


def _resolve_name(name: str, files: list, first: TestFile):
    """(value node, the file that holds it) of a module-level name: the given files first, then the module the test file imports
    it from (`_imported_list`); (None, None) when neither holds it - the caller refuses with the door `--file`."""
    for tf in [first] + [f for f in files if f is not first]:
        if name in tf.assignments:
            return tf.assignments[name], tf
    return _imported_list(name, first, first.root)


def _import_of(wanted: str, holder: TestFile):
    """(the `from ... import` node, the name it imports) that binds `wanted` in `holder` (an `as` name counts), else None. The
    first such statement in the file when there are several."""
    found = []
    for node in ast.walk(holder.tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*" and (alias.asname or alias.name) == wanted:
                    found.append((getattr(node, "lineno", 0), node, alias.name))
    if not found:
        return None
    _line, node, original = min(found, key=lambda item: item[0])
    return node, original


def _module_files(node: ast.ImportFrom, holder: TestFile, root: Path) -> list:
    """Every file of the project that the statement can mean, resolved paths, none outside the root. A relative import
    (`level > 0`) counts from the folder of the importing file; an absolute one is looked up from that folder and every folder
    above it up to the project root - the places a test runner puts on the path - and each match is a candidate."""
    root_path = root.resolve()
    here = holder.path.resolve().parent
    try:
        here.relative_to(root_path)
    except ValueError:
        return []                                    # a file outside the project has no candidates (audit A20)
    parts = (node.module or "").split(".") if node.module else []
    if node.level > 0:
        bases = [here]
        for _ in range(node.level - 1):
            bases = [bases[0].parent]
    else:
        bases, base = [], here
        while True:
            bases.append(base)
            if base == root_path or base.parent == base:
                break
            base = base.parent
    out = []
    for base in bases:
        spots = [base.joinpath(*parts[:-1], parts[-1] + ".py"), base.joinpath(*parts, "__init__.py")] if parts \
            else [base / "__init__.py"]
        for spot in spots:
            try:
                resolved = spot.resolve()
                resolved.relative_to(root_path)
            except (OSError, ValueError):
                continue
            if resolved.is_file() and resolved not in out:
                out.append(resolved)
    return out


def _read_module(path: Path, root: Path, owner: TestFile) -> TestFile:
    """The module a parameter list is imported from, read for its names only (`TestFile(scan=False)`) and kept for the rest of the
    call: a refusal it earned is kept too, so a second function meets the same words, not a second read."""
    key = str(path)
    if key not in owner.imported:
        rel = path.relative_to(root.resolve()).as_posix()
        try:
            owner.imported[key] = TestFile(path, rel, root, scan=False)
        except Refusal as exc:
            owner.imported[key] = exc
        except OSError as exc:
            owner.imported[key] = Refusal(f"{rel}: cannot be read ({type(exc).__name__}) — add the module that holds the "
                                          "list with another --file once it can be read")
    kept = owner.imported[key]
    if isinstance(kept, Refusal):
        raise kept
    return kept


def _imported_list(name: str, tf: TestFile, root, hops: int = IMPORT_HOPS):
    """(value node, holder) of `name` as the test file's own imports lead to it, (None, None) when they do not (EP1-25).

    The statement that binds `name` in `tf` names a module of the project; the module is read for its names only, and when it
    does not assign the name itself but imports it from another module the walk goes on - at most `hops` import statements from
    the test file, the last one reaching the module that holds the value. What the code cannot read is never taken for an empty
    list: a third-party package, a dynamic import, `import *`, `d.LIST`, a module that is absent or has no such name all give
    (None, None) and the caller keeps the refusal with its door, `--file <module>`. What it can read but cannot trust is a refusal
    of its own: two modules the statement can mean (pytest takes one, the code will not guess which), a chain longer than `hops`,
    a cycle, a module that does not parse. The module's tests and markers are not scanned and it is not added to the files:
    `build` adds it to `generated_from` when the rows it helped to read are written."""
    if root is None:
        return None, None
    root = Path(root)
    holder, wanted, chain, seen = tf, name, [], set()
    for hop in range(1, hops + 2):
        spec = _import_of(wanted, holder)
        if spec is None:
            return None, None
        node, original = spec
        paths = _module_files(node, holder, root)
        if not paths:
            return None, None
        if len(paths) > 1:
            rels = [p.relative_to(root.resolve()).as_posix() for p in paths]
            raise Refusal(f"`{ast.unparse(node)}` can mean {' or '.join(rels)}, and the script does not guess which one "
                          f"the test run imports — pass the one you mean with --file {rels[0]} (or --file {rels[1]})")
        if hop > hops:
            chain_text = " -> ".join(chain + [paths[0].relative_to(root.resolve()).as_posix()])
            raise Refusal(f"the parameter list `{name}` is re-exported through more than {hops} modules ({chain_text}) — "
                          "add the module that defines it with another --file")
        if (paths[0], original) in seen:
            back = paths[0].relative_to(root.resolve()).as_posix()
            raise Refusal(f"the parameter list `{name}` is imported in a circle ({' -> '.join(chain + [back])}) — "
                          "add the module that defines it with another --file")
        seen.add((paths[0], original))
        module = _read_module(paths[0], root, tf)
        chain.append(module.rel)
        if original in module.assignments:
            tf.imported_used += chain          # a log, repeats included: `build` slices what ONE function read
            return module.assignments[original], module
        holder, wanted = module, original
    return None, None


def _resolve_at(name: str, files: list, tf: TestFile, where: str):
    """`_resolve_name`, a refusal of the import walk put at the parametrize that asked."""
    try:
        return _resolve_name(name, files, tf)
    except Refusal as exc:
        raise Refusal(f"{where}: {exc}") from None


def _param_rows(call: ast.Call, tf: TestFile, files: list, func_name: str) -> list:
    """[(id, marks)] of one `@pytest.mark.parametrize(argnames, argvalues, ids=...)`."""
    where = f"{tf.where(call)} parametrize of {func_name}"
    positional = list(call.args)
    keywords = {kw.arg: kw.value for kw in call.keywords}
    names_node = positional[0] if positional else keywords.get("argnames")
    values_node = positional[1] if len(positional) > 1 else keywords.get("argvalues")
    if names_node is None or values_node is None:
        raise Refusal(f"{where}: cannot read argnames/argvalues")
    names = _literal(names_node, where)
    argnames = [n.strip() for n in names.split(",")] if isinstance(names, str) else [str(n) for n in names]
    holder = tf
    if isinstance(values_node, ast.Name):
        values_node, holder = _resolve_at(values_node.id, files, tf, where)
        if values_node is None:
            raise Refusal(f"{where}: the parameter list `{ast.unparse(positional[1] if len(positional) > 1 else keywords['argvalues'])}` "
                          "is defined in a module this call was not given — add that module "
                          "with another --file, or give explicit ids= / pytest.param(id=...)")
    if not isinstance(values_node, (ast.List, ast.Tuple)):
        carrier = f" (in {holder.rel})" if holder is not tf else ""
        raise Refusal(f"{where}: the parameter list is `{ast.unparse(values_node)[:60]}`{carrier} — only a "
                      "literal list (inline or a module-level name) can be read without importing")
    explicit_ids = None
    if "ids" in keywords:
        ids_node = keywords["ids"]
        if isinstance(ids_node, ast.Name):
            ids_node, _ = _resolve_at(ids_node.id, files, tf, where)
        if not isinstance(ids_node, (ast.List, ast.Tuple)):
            raise Refusal(f"{where}: `ids=` is not a literal list; use pytest.param(id=...) instead")
        explicit_ids = [str(_literal(e, where)) for e in ids_node.elts]
        if len(explicit_ids) != len(values_node.elts):
            raise Refusal(f"{where}: ids= has {len(explicit_ids)} entries for {len(values_node.elts)} values")
    rows = []
    for index, element in enumerate(values_node.elts):
        marks: list = []
        pid = ""
        values = element
        if isinstance(element, ast.Call) and _is_pytest_param(element):
            kws = {kw.arg: kw.value for kw in element.keywords}
            if "id" in kws:
                pid = str(_literal(kws["id"], holder.where(element)))
            if "marks" in kws:
                mnode = kws["marks"]
                mnodes = mnode.elts if isinstance(mnode, (ast.List, ast.Tuple)) else [mnode]
                marks = _marks_of(mnodes, f"{holder.where(element)} pytest.param")[0]
            values = ast.Tuple(elts=list(element.args)) if len(element.args) != 1 else element.args[0]
        if explicit_ids:
            pid = explicit_ids[index]
        if not pid:
            if len(argnames) == 1:
                pid = _auto_id(values, argnames[0], index)
            else:
                elts = values.elts if isinstance(values, (ast.Tuple, ast.List)) else [values]
                pid = "-".join(_auto_id(e, argnames[i] if i < len(argnames) else f"arg{i}", index)
                               for i, e in enumerate(elts))
        rows.append((pid, marks))
    return rows


def _is_pytest_param(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "param" and isinstance(f.value, ast.Name)
            and f.value.id == "pytest") or (isinstance(f, ast.Name) and f.id == "param")


def _instances_of(node, tf: TestFile, files: list, params: list) -> list:
    """[(param id or '', marks from pytest.param)] — the cartesian product of every
    parametrize decorator, inner-most first, joined with `-` the way pytest spells it."""
    if not params:
        return [("", [])]
    per_decorator = [_param_rows(call, tf, files, node.name) for call in reversed(params)]
    out = []
    for combo in itertools.product(*per_decorator):
        out.append(("-".join(pid for pid, _ in combo), [m for _, marks in combo for m in marks]))
    return out


def _assert_span(node) -> tuple:
    """(first, last) line of the function's assertions; the whole body when none is found."""
    lines = []
    todo = list(node.body)
    while todo:
        child = todo.pop(0)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue  # a helper defined inside the test is not the test's assertion
        todo += [c for c in ast.iter_child_nodes(child) if isinstance(c, ast.stmt)]
        hit = False
        if isinstance(child, ast.Assert):
            hit = True
        elif isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
            f = child.value.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            hit = name.lower().startswith(ASSERT_CALL_PREFIXES)
        elif isinstance(child, ast.With):
            for item in child.items:
                expr = item.context_expr
                f = expr.func if isinstance(expr, ast.Call) else None
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                hit = hit or name in RAISES_NAMES
        if hit:
            lines.append((child.lineno, getattr(child, "end_lineno", child.lineno)))
    if not lines:
        body = node.body or [node]
        return body[0].lineno, getattr(body[-1], "end_lineno", body[-1].lineno)
    return min(a for a, _ in lines), max(b for _, b in lines)


def _then_numbers(value, where: str) -> list:
    if value is None:
        return []
    items = list(value.keys()) if isinstance(value, dict) else (value if isinstance(value, (list, tuple)) else [value])
    out = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise Refusal(f"{where}: `then` lists the numbers of the case's Then clauses (`then=[1, 2]`), got {item!r}")
        out.append(item)
    return out


def _assertion_ref(rel: str, then_value, number: int, span: tuple) -> str:
    """The marker may pin a clause to its own lines (`then={1: "579-584"}`); by default every
    clause the function claims is referred to the function's assertion span."""
    if isinstance(then_value, dict):
        raw = str(then_value.get(number) or "").strip()
        if raw:
            return raw if ":" in raw else f"{rel}:{raw}"
    first, last = span
    return f"{rel}:{first}" if first == last else f"{rel}:{first}-{last}"


# --- the story's own records -----------------------------------------------------------------

class Story:
    def __init__(self, task: str, task_root: Path):
        self.task, self.root = task, task_root
        # The story's project config, read once: every scope/manifest question below compares a
        # case against a whole list, and a config stat per comparison was seconds per window (B-013).
        self.cfg = C.case_config(task_root)
        self.links = {}
        for link in C.story_case_links(task_root):
            cid = str(link.get("case_id") or "")
            if cid:
                self.links[cid] = link
        self.plan = {}
        plan_path = C.artifact(task_root, "test-plan.json")
        if plan_path.exists():
            data = C.load_json(plan_path)
            for row in data.get("rows") or []:
                if isinstance(row, dict) and row.get("id"):
                    self.plan[str(row["id"])] = row
        try:
            self.index = C.case_index(task_root)
        except Exception:
            self.index = {}
        manifest_path = C.artifact(task_root, "automation-manifest.json")
        self.manifest = C.load_json(manifest_path) if manifest_path.exists() else {}
        # A story with a side that is not `real` owes each test row a `sides` declaration (t-2181 PC-3, §2.3); the reader is
        # `contract.story_sides`, and a reality it cannot read is not real either. All sides real (the default): no row changes.
        self.non_real_side = any(side["reality"] != "real" for side in
                                 C.story_sides(C.load_json(Path(task_root) / "pipeline.json")).values())
        self._cases: dict = {}

    def bare(self, case: str) -> str:
        return C.split_case_key(case, cfg=self.cfg)[1]

    def case(self, case: str, where: str) -> dict:
        """{plan_row, requirements, version, clauses, area} of one case, or a refusal."""
        key = str(case).strip()
        if key in self._cases:
            return self._cases[key]
        bare = self.bare(key)
        entry = None
        try:
            entry = self.index.get(key) if hasattr(self.index, "get") else None
        except Exception:
            entry = None
        path = entry.get("path") if isinstance(entry, dict) else None
        if path is None:
            path = self._find_file(bare)
        link = self.links.get(bare) or {}
        if path is None and not link:
            known = ", ".join(sorted(self.links) or sorted(str(k) for k in self.index)) or "none"
            raise Refusal(f"{where}: {key} is not a case of {self.task} — neither "
                          "state/story-case-links.json nor the case store names it "
                          f"(known: {known})")
        text = C.read_text(path) if path else ""
        from s5_precheck import then_clauses
        info = {
            "plan_row": (entry or {}).get("plan_row") or (C.case_plan_row(path) if path else ""),
            "requirements": (entry or {}).get("requirements") or (C.case_requirements(path) if path else []),
            "version": str(link.get("version") or (entry or {}).get("version") or ""),
            "area": str(link.get("area") or (entry or {}).get("area") or ""),
            "clauses": [n for n, _ in then_clauses(text)],
            "path": path,
        }
        self._cases[key] = info
        return info

    def question_ids(self) -> tuple:
        """(readiness file present and readable, [question ids of `open_questions`]) - the register's
        own reader (`question_register.load`), which never raises on the story's data."""
        try:
            view = QR.load(self.root)
        except Exception:
            return False, []
        if not view.get("register_present") or view.get("problems") and not view.get("questions"):
            return False, []
        return True, [str(q.get("id")) for q in view.get("questions", []) if q.get("id")]

    def _find_file(self, bare: str):
        for base in (self.root / "work" / "test-cases", self.root / "state" / "case-versions" / bare):
            if base.exists():
                for path in sorted_paths(base.rglob(f"{bare}*.md")):
                    return path
        return None

    def obligation(self, case: str, oid: str, where: str) -> dict:
        info = self.case(case, where)
        row_id = str(info.get("plan_row") or "")
        row = self.plan.get(row_id)
        if not row_id or row is None:
            raise Refusal(f"{where}: `obligations` names {oid} for {case}, and the case's plan row "
                          f"({row_id or 'none recorded'}) is not in work/test-plan.json — an "
                          "obligation can only be checked against the row that owns it")
        found = {str(ob.get("obligation_id")): ob for ob in row.get("coverage_obligations") or []
                 if isinstance(ob, dict) and ob.get("obligation_id")}
        if oid not in found:
            raise Refusal(f"{where}: {oid} is not an obligation of {case}'s plan row {row_id} "
                          f"(it has: {', '.join(sorted(found)) or 'none'}) — name one of those, "
                          "or leave `obligations` out")
        return found[oid]

    def dispatch(self, dispatch_id: str) -> dict:
        state = C.load_json(self.root / "state" / "controller.json")
        raw = state.get("dispatches")
        rows = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        for row in rows:
            if isinstance(row, dict) and dispatch_id in {str(row.get("id")), str(row.get("dispatch_id"))}:
                return row
        raise Refusal(f"no dispatch {dispatch_id!r} in {self.task}'s controller state — the id is "
                      "the one your prompt carries (`story_step start` printed it)")

    def manifest_has(self, case: str) -> bool:
        for entry in C.manifest_tests(self.manifest):
            if any(C.case_matches(c, case, cfg=self.cfg) for c in C.manifest_test_links(entry, self.cfg)):
                return True
        return any(C.case_matches(str(u.get("case") or ""), case, cfg=self.cfg)
                   for u in C.manifest_unresolved(self.manifest))

    def existing_status(self, iid: str) -> str:
        for entry in C.manifest_tests(self.manifest):
            if iid in C.instance_id_aliases(entry, self.cfg):
                return str(entry.get("status") or "")
        return ""

    def scaffold_sides(self, entry: dict, iid: str) -> None:
        """`sides: {}` on a new row of a story with a non-real side: the empty declaration the automator then fills. A row the
        manifest already holds with a `sides` key is sent without one - a patch carrying `{}` would wipe the declared sides."""
        if not self.non_real_side:
            return
        for stored in C.manifest_tests(self.manifest):
            if iid in C.instance_id_aliases(stored, self.cfg) and "sides" in stored:
                return
        entry["sides"] = {}

    def stored_novelty(self, iid: str) -> dict:
        """The `novelty` block the manifest already holds for this instance, `{}` when there is none."""
        for entry in C.manifest_tests(self.manifest):
            if iid in C.instance_id_aliases(entry, self.cfg):
                block = entry.get("novelty")
                return block if isinstance(block, dict) else {}
        return {}

    def run_status(self, iid: str) -> str:
        """`green`/`red` from the newest run-block row of this instance, else ''."""
        from s5_precheck import run_block_rows
        verdict = ""
        for row in run_block_rows(self.root):
            rid = str(row.get("instance_id") or "")
            tid = str(row.get("test_id") or "")
            if rid != iid and not tid.endswith(C.INSTANCE_SEP + iid):
                continue
            status = C.result_status(row) if hasattr(C, "result_status") else str(row.get("status") or "")
            if status == "passed":
                verdict = "green"
            elif status == "failed":
                verdict = "red"
        return verdict


# --- building the fragment -------------------------------------------------------------------

def _unique(values) -> list:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


NOVELTY_WRITER = "manifest_from_tests.py"
# V2 (t-134, critic override): against a base that is NOT a recorded S0 base - a story in flight, a
# project without git - only a measured `new` or `changed` is stored. A test measured `unchanged` or
# `unknown` there gets no key, so today's rule reads it as unmeasured and a story that began before
# the measure existed never gains a required probe it did not have. The measurer names the kind.
NOVELTY_S0_KIND = "s0"
NOVELTY_KEPT_WITHOUT_S0 = ("new", "changed")
NOVELTY_SAME_MEASUREMENT = ("value", "basis", "base", "measured_on")   # equal -> measured_at stays


def _novelty_block(result: dict, stamp: str):
    """The stored `novelty` of one measurement (R3), or None when V2 says the row gets no key."""
    base = result["base"]
    kind, value = base["kind"], result["value"]
    if kind != NOVELTY_S0_KIND and value not in NOVELTY_KEPT_WITHOUT_S0:
        return None
    return {"value": value, "basis": result["basis"], "base": {"kind": kind, "sha": base["sha"]},
            "measured_on": dict(result["measured_on"]), "measured_by": NOVELTY_WRITER,
            "measured_at": stamp}


def _run_cwd(project: Path, rels: list, cfg: dict):
    """The one run directory the measured files share, or None. `measure_many` takes ONE cwd for the
    whole call, so when the files belong to different profiles none is forced and the measurer
    resolves each test folder itself, by the same function (its own fallback)."""
    import test_novelty
    found = {str(test_novelty.resolve_run_cwd(project, rel, cfg=cfg)[0]) for rel in rels}
    return found.pop() if len(found) == 1 else None


def _keep_stored_novelty(story: Story, keyed: list, notes: list) -> None:
    """The measurer failed: give each row the block the manifest already holds for it, unchanged.

    Why: `manifest_put.merge` drops the stored block of a row whose patch carries `generated_from`
    and no `novelty` (V2's "this run stored none"). A failed measurement is not that - it is "no
    answer" - and dropping there turned a measured `new`/`changed` into a keyless row that reads NOT
    required, the one direction the owner's rule forbids (t-187, F-A; critic of B-207). Copying the
    stored block back makes the merge a no-op for the row, `measured_at` included.

    A row the manifest holds no block for stays keyless with its `generated_from`: there is nothing
    for the merge to drop, and a first run that cannot measure has no measurement to lose.

    Only a ROW-FORM stored block is copied (`manifest_put.novelty_row_problems` finds nothing wrong:
    an object with `measured_on` and `measured_by`, no `resolved`). A block F-B would refuse - a role
    forged it into an old manifest, or it is not an object (`stored_novelty` answers `{}` for that) -
    is not copied: the copy would make `manifest_put` refuse the writer's own fragment, a loop whose
    only door is this same call. The row stays keyless and the merge drops the forged block. That
    case exists in old manifests only; cmp1's manifests carry no novelty keys, so it is empty in
    practice (t-187, owner-side decision on Q1/Q2)."""
    import manifest_put
    kept = 0
    for row, _key in keyed:
        try:
            stored = story.stored_novelty(str(row.get("instance_id") or ""))
        except Exception:
            stored = {}
        if stored and manifest_put.novelty_row_problems({"tests": [{"novelty": stored}]}):
            stored = {}
        if stored:
            row["novelty"] = copy.deepcopy(stored)
            kept += 1
    if kept:
        notes.append(f"the stored novelty of {kept} row(s) was kept as it was, not refreshed")


def _attach_novelty(story: Story, project, keyed: list, notes: list, helpers: list | None = None) -> list:
    """Write `novelty` on the rows (R3) from ONE `measure_many` call: one mirror, one git batch, one
    parse cache (V3, FR-55: a mirror per test cost 4-5 s per function). `keyed` is [(row, function
    key)]; parametrized rows of one function share one measurement and each carries its own copy.
    The measurer never raises; if it does anyway a note says so and each row carries the block the
    manifest already held for it (`_keep_stored_novelty`), or no key when it held none: the switch
    never blocks the automator (P1, P15) and never lowers what an earlier run measured.

    `helpers` are the `(rel, class chain, name)` units of `_helper_units` (TQ1-7): they ride in the SAME call (one mirror,
    one git batch; a second call per build is the cost V3 removed) and their `value`s come back as the return, in order -
    `unknown` for every unit when the call fails, `[]` when there are none."""
    helpers = list(helpers or [])
    if not keyed and not helpers:
        return []
    order: list = []
    for _row, key in keyed:
        if key not in order:
            order.append(key)
    items = [{"test_rel": rel, "function": function, "class_chain": list(chain)}
             for rel, chain, function in order]
    items += [{"test_rel": rel, "function": name, "class_chain": list(chain)} for rel, chain, name in helpers]
    try:
        project = Path(project) if project is not None else project_root()
        import test_novelty
        import test_repo_base
        results = test_novelty.measure_many(
            project, items, base_record=test_repo_base.load(story.root),
            run_cwd=_run_cwd(project, [rel for rel, _c, _f in [*order, *helpers]], story.cfg))
        if len(results) != len(items):
            raise ValueError("one answer per test was expected")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        blocks = {key: _novelty_block(result, stamp) for key, result in zip(order, results)}
        values = [str(r.get("value")) if isinstance(r, dict) else "unknown" for r in results[len(order):]]
    except Exception as exc:
        notes.append(f"novelty could not be measured ({type(exc).__name__})")
        _keep_stored_novelty(story, keyed, notes)
        return ["unknown"] * len(helpers)
    for row, key in keyed:
        if blocks[key] is not None:
            block = copy.deepcopy(blocks[key])           # the measurement of THIS call, never merged
            try:
                stored = story.stored_novelty(str(row.get("instance_id") or ""))
            except Exception:
                stored = {}
            # The same measurement as the stored one keeps its stamp: a re-run that found nothing
            # new must leave the fragment (its hash) and the manifest as they are.
            if (isinstance(stored.get("measured_at"), str)
                    and all(stored.get(k) == block[k] for k in NOVELTY_SAME_MEASUREMENT)):
                block["measured_at"] = stored["measured_at"]
            row["novelty"] = block
    return values


# --- the keys of `qa_unresolved` that name WHICH part of a case a row speaks about (HF2-12) ---------------------------

def _contradicts_requirement() -> str:
    """The reason word of a red test: ONE home, `acceptance.CONTRADICTS_REQUIREMENT` (`contract` holds no such constant).
    Imported where it is asked: `stage_guard`, a hook, imports this module for the closed reason list, and `acceptance`
    must not load with it."""
    import acceptance
    return acceptance.CONTRADICTS_REQUIREMENT


def preserved_reasons() -> tuple:
    """The `then_bindings` reasons of a row a ROLE sends by hand and the markers do not write as their own (HF2-12, C6):
    a Then behind a red check, and a Then of a case that went red by the requirement. `_merge_bindings` keeps such a
    row across a writer run (the function form of the spec's `PRESERVED_REASONS`: the second word is imported lazily)."""
    return (C.BLOCKED_BY_CHECK, _contradicts_requirement())


def _is_blocked(kwargs: dict) -> bool:
    return str(kwargs.get("reason") or "").strip() == C.BLOCKED_BY_CHECK


def _instance_ids(value, where: str) -> list:
    """`instance_ids=` of a `qa_unresolved` marker: a list of non-empty strings (one string is a list of one), in the
    order given and without repeats. Anything else - an empty list, a number, an empty element - is a refusal: a slice
    key that names nothing would turn the row into the WHOLE case's, the wider reading of what the author wrote."""
    items = [value] if isinstance(value, str) else value
    if (not isinstance(items, (list, tuple)) or not items
            or any(not isinstance(item, str) or not item.strip() for item in items)):
        raise Refusal(f"{where}: `instance_ids` lists instance ids as strings (`instance_ids=[\"test_x[a]\"]`), "
                      f"got {value!r}")
    return _unique(item.strip() for item in items)


def _slice_keys(kwargs: dict, reason: str, thens: list, where: str) -> tuple:
    """(`instance_ids`, `thens` of the red) of a `qa_unresolved` marker, [] for a key not given; a refusal when a key does
    not fit the marker's other keys. `then=[n]` is ONE Then of the test the marker sits on and writes a `then_bindings`
    row; `instance_ids` and `thens` belong to the case's own `unresolved[]` row, so they never stand beside it.
    `thens` is the red Then of a `contradicts_requirement` row, sorted and without repeats."""
    ids = _instance_ids(kwargs["instance_ids"], where) if "instance_ids" in kwargs else []
    if ids and thens:
        raise Refusal(f"{where}: `instance_ids` names the tests an unresolved[] row speaks about; a row with `then=[n]` "
                      "is one Then of the test the marker sits on - drop one of them")
    red = []
    if "thens" in kwargs:
        if reason != _contradicts_requirement():
            raise Refusal(f"{where}: `thens` belongs to reason=\"{_contradicts_requirement()}\" (the red Then of the "
                          f"case), not to {reason!r}")
        if thens:
            raise Refusal(f"{where}: `then=[n]` writes a then_bindings row for each Then this test cannot assert; "
                          f"`thens=[n]` names, on the case's {_contradicts_requirement()} row, the Then that is red - "
                          "use one of them")
        red = sorted(set(_then_numbers(kwargs["thens"], where)))
    return ids, red


def _blocked_rows(case: str, numbers: list, kwargs: dict, held, where: str) -> list:
    """The `then_bindings` rows of a `qa_unresolved` marker whose reason is `blocked_by_check` (`then=[n]`, `blocking_check=`, `detail=`):
    one per (Then, test that holds it). `held` is the instance ids of the test function or `pytest.param` the marker
    sits on, None for a module or a class. A Then behind a red check is held by a test, so a row without an instance
    is never written here (it would name nobody); the shape is the contract's own (`then_remainder_errors`)."""
    if not numbers:
        raise Refusal(f"{where}: `{C.BLOCKED_BY_CHECK}` is the reason of one Then - pass `then=[n]`")
    if held is None:
        raise Refusal(f"{where}: a Then behind a red check is held by a test - put `qa_unresolved(case=, then=[n], "
                      f"reason=\"{C.BLOCKED_BY_CHECK}\", blocking_check=, detail=)` on that test function")
    if not held:
        raise Refusal(f"{where}: the test this marker sits on carries no `{MARK_QA}` marker, so the Then it holds names no "
                      f"instance - add `{MARK_QA}(case=, then=[...])` for what it asserts")
    rows = []
    for number in numbers:
        for iid in held:
            row = {"case": case, "then": number, "instance_id": iid, "assertion_ref": None, "status": "unresolved",
                   "reason": C.BLOCKED_BY_CHECK, "blocking_check": kwargs.get("blocking_check"),
                   **({"detail": kwargs["detail"]} if kwargs.get("detail") else {})}
            problems = C.then_remainder_errors(row)
            if problems:
                raise Refusal(f"{where}: a Then behind a red check is malformed: " + "; ".join(problems)
                              + f" - write `qa_unresolved(case=, then=[n], reason=\"{C.BLOCKED_BY_CHECK}\", "
                                "blocking_check=\"<red case or test id>\", detail=<what to check once it is fixed>)`")
            rows.append(row)
    return rows


# --- introduced_helpers[]: the trail to the analogue (TQ1-7) -----------------------------------------------------------
#
# A second helper beside an existing one is the defect `s5_precheck` cannot see (it sees a textual duplicate only). The
# code COUNTS the helpers this story's history made new; whether a new one was needed is the role's: it fills the four
# role fields of each row (what it is for, where it looked, what it found, why it keeps its own). The scaffold fields
# (`file`, `name`, `novelty`) are this writer's alone; `manifest_put.BY_HELPER` merges the two writers by (file, name).

HELPER_ROLE_FIELDS = ("purpose", "searched", "similar_found", "keep")
HELPER_NEW_ENOUGH = ("new", "changed", "unknown")        # `unchanged` is somebody else's code: no row


def _units_of(tree) -> list:
    """`[(class chain, name)]` of every function and method of a module that is not a test (`test*`) and not a dunder:
    the helpers, the fixtures and the page-object methods. Nested functions are the body of their outer one."""
    out: list = []

    def walk(body, chain: tuple) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test") and not (node.name.startswith("__") and node.name.endswith("__")):
                    out.append((chain, node.name))
            elif isinstance(node, ast.ClassDef):
                walk(node.body, chain + (node.name,))

    walk(getattr(tree, "body", []), ())
    return out


def _helper_units(project, files: list, notes: list) -> list:
    """`[(rel, class chain, function name)]`: every non-test function or method of the given files and of the
    `conftest.py` chain above them (`s5_precheck._conftest_files`, the one reader of the chain). A file that is not
    Python gives no unit and a note: the code critic reads such a file whole, and the note says the count is not zero
    but not made (AR-2). The units are measured by `_attach_novelty` in the ONE `measure_many` call of the build
    (V3, FR-55) and turned into rows by `_helper_rows`."""
    project = Path(project) if project is not None else project_root()
    units: list = []                       # (rel, class chain, function name)
    seen_rel: set = set()

    def add(rel: str, tree) -> None:
        if rel in seen_rel:
            return
        seen_rel.add(rel)
        units.extend((rel, chain, name) for chain, name in _units_of(tree))

    for tf in files:
        if not tf.rel.endswith(".py"):
            notes.append(f"{tf.rel} is not a Python file: its helpers were not counted - the code critic reads it whole")
            continue
        add(tf.rel, tf.tree)
    try:
        import s5_precheck
        for tf in files:
            if not tf.rel.endswith(".py"):
                continue
            rows, chain_notes = s5_precheck._conftest_files(tf.path, project)
            notes.extend(n for n in chain_notes if n not in notes)
            for path, parsed in rows:
                shown = s5_precheck._shown(path, project)
                if not Path(shown).is_absolute():
                    add(shown, parsed.tree)
    except Exception as exc:               # the conftest chain is a help: the given files' own helpers are still counted
        notes.append(f"the conftest chain was not read for helpers ({type(exc).__name__})")
    return units


def _helper_rows(story: Story, units: list, values: list, notes: list) -> list:
    """The helper rows of this call: `{file, name, purpose, searched, similar_found, keep, novelty}` for every unit whose
    `value` (one per unit, from `test_novelty.measure_many`, the one reader of the base; its error is toward "not
    unchanged") is `new`, `changed` or `unknown`. A method is named `Class.method`. The four role fields keep what the
    manifest already holds for the row (a re-run never wipes the role's words); the scaffold is this call's.

    `unknown` (the measurer raised, no base, a function it cannot read, a value that is none of the three) is a row with
    `novelty: unknown` and a note: a false "new" is allowed, a silent pass is not (FR-59)."""
    stored = {(str(r.get("file") or ""), str(r.get("name") or "")): r
              for r in (story.manifest.get("introduced_helpers") or []) if isinstance(r, dict)} \
        if isinstance(story.manifest.get("introduced_helpers"), list) else {}
    rows: list = []
    unknown: list = []
    for (rel, chain, name), value in zip(units, values):
        value = value if value in ("new", "changed", "unchanged") else "unknown"
        if value not in HELPER_NEW_ENOUGH:
            continue
        qualified = ".".join(chain + (name,))
        kept = stored.get((rel, qualified)) or {}
        rows.append({"file": rel, "name": qualified,
                     **{field: str(kept.get(field) or "") for field in HELPER_ROLE_FIELDS}, "novelty": value})
        if value == "unknown":
            unknown.append(f"{rel}::{qualified}")
    if unknown:
        notes.append(f"{len(unknown)} helper(s) have `novelty: unknown` (not established as new or unchanged): "
                     + ", ".join(unknown[:5]) + (f" (+{len(unknown) - 5} more)" if len(unknown) > 5 else "")
                     + " - read each as possibly new")
    return rows


def build(story: Story, files: list, dispatch_id: str, project=None, prior_problems=()) -> dict:
    """The fragment, the per-case picture and the notes — pure over the parsed files, plus the one
    novelty measurement (`project` is the project root, the process's own when not given).

    Every problem with a marker is collected, from every function of every file, and refused ONCE at the end (`_aggregate`):
    a file with three wrong markers is one refusal of three lines, not three rounds (EP1-25). `prior_problems` are the ones the
    caller already met (a given file that does not parse). What is not a problem of a marker - an unknown dispatch, the story,
    nothing to write - is refused as before, at once."""
    dispatch = story.dispatch(dispatch_id)
    root = Path(project) if project is not None else project_root()
    for tf in files:
        tf.root = tf.root or root
    generated_from = _unique(tf.rel for tf in files)
    problems: list = list(prior_problems)
    keyed: list = []
    scope = [str(c) for c in (dispatch.get("scope") or dispatch.get("cases") or []) if c]
    notes: list = []
    tests: list = []
    bindings: list = []
    unresolved: list = []
    seen_ids: dict = {}
    cases_named: list = []
    whole_unresolved: list = []
    named_ids: list = []        # the instance ids `instance_ids=` markers name, checked against what exists at the end
    noted_outside: set = set()

    def links_for(cases: list, where: str) -> list:
        out = []
        for case in cases:
            info = story.case(case, where)
            if info["version"]:
                out.append({"case_id": story.bare(case), "version": info["version"]})
        return out

    def check_scope(case: str, where: str) -> None:
        if case not in cases_named:
            cases_named.append(case)
        if not scope or any(C.case_matches(s, case, cfg=story.cfg) for s in scope):
            return
        if story.manifest_has(case):
            if case not in noted_outside:  # one note per case, at its first marker
                noted_outside.add(case)
                notes.append(f"{where}: {case} is outside this dispatch's scope ({', '.join(scope)}) "
                             "and already in the manifest — its rows are re-sent as a consolidation")
            return
        raise Refusal(f"{where}: {case} is outside this dispatch's scope ({', '.join(scope)}) and "
                      "not in the manifest — a case another window owns is not this window's "
                      "to add; check the id")

    def unresolved_row(kwargs: dict, where: str, held=None) -> None:
        """One `qa_unresolved` marker. `held`: the instance ids of the test function or `pytest.param` it sits on (a
        `blocked_by_check` row names the test that holds the Then), None for a module or a class."""
        case = str(kwargs["case"]).strip()
        reason = str(kwargs.get("reason") or "").strip()
        if not reason or not (C.unresolved_reason_ok(reason) or reason in UNRESOLVED_REASON_WORDS):
            raise Refusal(f"{where}: `reason` must be one of {', '.join(UNRESOLVED_REASON_WORDS)} "
                          f"or `{C.UNRESOLVED_DECIDED_PREFIX}:<decision>` — got {reason!r}")
        info = story.case(case, where)
        check_scope(case, where)
        partitions = kwargs.get("partitions") or ([kwargs["partition"]] if kwargs.get("partition") else [])
        thens = _then_numbers(kwargs.get("then"), where)
        ids, red_thens = _slice_keys(kwargs, reason, thens, where)
        if "blocking_check" in kwargs and reason != C.BLOCKED_BY_CHECK:
            raise Refusal(f"{where}: `blocking_check` belongs to reason=\"{C.BLOCKED_BY_CHECK}\"")
        absent = kwargs.get("field_absent")
        if "field_absent" in kwargs:
            if reason != _contradicts_requirement() or thens:
                raise Refusal(f"{where}: `field_absent` belongs to the case's reason=\"{_contradicts_requirement()}\" row (no `then=`), "
                              f"not to {reason!r}")
            lacking = [k for k in FIELD_ABSENT_KEYS if not (isinstance(absent, dict) and str(absent.get(k) or "").strip())]
            if lacking:
                raise Refusal(f"{where}: `field_absent` is `{{then, field, read_from, shape_ref}}` - missing or empty: {', '.join(lacking)}")
        named_ids.extend(ids)
        sliced = C._slice_scoped({"instance_ids": ids, "partitions": partitions})
        question = str(kwargs.get("question") or "").strip()
        handed_then = reason == C.HANDED_TO_PERSON and bool(thens)
        if (kwargs.get("owner") is not None or kwargs.get("part") is not None) and not handed_then:
            raise Refusal(f"{where}: `owner` and `part` belong to a Then handed to its owner (`then=[n]`, "
                          f"`reason=\"{C.HANDED_TO_PERSON}\"`), not to {reason!r}"
                          + ("" if thens else " without `then`") + " - drop them, or write the row for one Then")
        if reason == EXPECTATION_UNCONFIRMED:
            # P20: a Then whose expected value nobody confirmed. The row is the automator's way of saying
            # "I did not assert a value I had no source for" - it needs the question that holds the gap,
            # or nobody knows what to answer, and the question has to be one the person can be asked.
            if not thens and not question:
                # D2 (t-269): a WHOLE case may carry the reason when it names the question that holds it (a case
                # none of whose Thens can be checked yet); without a question it is refused as before.
                raise Refusal(f"{where}: `{reason}` is the reason of ONE Then, or of a whole case that names its "
                              f"question - pass `then=[<the Then numbers>]`, the numbers under the case's `## Then` "
                              "whose oracle is `unknown`, or `question=\"<id in open_questions>\"` for a case none "
                              "of whose Thens can be checked yet")
            if not question:
                raise Refusal(f"{where}: `{reason}` needs `question=\"<question id>\"` - the id in "
                              "requirements-readiness.json `open_questions` that shows what the behaviour was "
                              "before and is now (the case's `then_oracles` line names it as `ref`)")
            present, known = story.question_ids()
            if not present:
                raise Refusal(f"{where}: question {question} cannot be checked - requirements-readiness.json "
                              "is missing or unreadable, and an `unknown` never travels without the question "
                              "a person can answer it through")
            if question not in known:
                raise Refusal(f"{where}: question {question!r} is not in `open_questions` of "
                              f"requirements-readiness.json (it holds: {', '.join(known) or 'none'}) - "
                              "use the id the case's `then_oracles` line names as `ref`")
        elif question or kwargs.get("observed") is not None:
            raise Refusal(f"{where}: `question` and `observed` belong to `reason=\"{EXPECTATION_UNCONFIRMED}\"` "
                          f"only - {reason!r} takes `detail`")
        remedy = kwargs.get("remedy")
        if reason == "blocked_by_env":
            problems = C.remedy_errors(remedy) if remedy is not None else ["remedy missing"]
            if problems:
                raise Refusal(f"{where}: a `blocked_by_env` row carries `remedy={{kind, where, change, "
                              f"restart?}}` — names only, never a value ({'; '.join(problems)})")
        if reason == C.BLOCKED_BY_CHECK:
            # HF2-3/HF2-12: a Then behind a red assert of its own test is a `then_bindings` row per held instance and
            # never an `unresolved[]` row (`blocked-check-row`); the shape is the contract's (`_blocked_rows`)
            for row in _blocked_rows(case, thens, kwargs, held, where):
                if row not in bindings:
                    bindings.append(row)
            return
        # A whole-case row also answers for every Then clause of the case: `s5_precheck.py`
        # reads `then_bindings` per clause and a case with clauses and no rows is
        # "bindings missing", whichever list the case sits in (the four TC-014 rows of
        # TP1-13797 were written by hand for exactly that reason). A row that names a slice of the case
        # (`partitions` or `instance_ids`) is not the whole case's and echoes nothing.
        clause_rows = thens or ([] if sliced else list(info["clauses"]))
        for number in clause_rows:
            row = {"case": case, "then": number, "instance_id": None, "assertion_ref": None,
                   "status": "unresolved", "reason": reason,
                   **({"detail": kwargs["detail"]} if kwargs.get("detail") else {})}
            if reason == EXPECTATION_UNCONFIRMED:
                # The question, and the value the test SAW without asserting it (absent when the test
                # never reached it: the ledger then says "observed: not recorded", never a guess).
                row["question"] = question
                if kwargs.get("observed") is not None:
                    row["observed"] = kwargs["observed"]
            if handed_then:
                # GW1-14: a Then the person takes. `owner`/`part` ride only on this row; its shape is the contract's
                # (`then_remainder_errors`, the check `manifest_put` and the S5 exit also run) and a refusal names
                # the marker's own file and line
                for key in ("owner", "part"):
                    if kwargs.get(key) is not None:
                        row[key] = kwargs[key]
                problems = C.then_remainder_errors(row)
                if problems:
                    raise Refusal(f"{where}: a Then handed to its owner is malformed: " + "; ".join(problems)
                                  + " - write `qa_unresolved(case=, then=[n], reason=\"handed_to_person\", owner=, "
                                    "part=, detail=<the steps or the command>)`")
            if row not in bindings:
                bindings.append(row)
        if thens:
            return
        row = {"case": case, "reason": reason}
        if kwargs.get("detail"):
            row["detail"] = str(kwargs["detail"])
        if reason == EXPECTATION_UNCONFIRMED:
            # The whole-case form (D2): the question that holds the gap travels with the row, so the ledger
            # can say "Needed: your answer to Q-n" for it, and the value the test saw when it reached one.
            row["question"] = question
            if kwargs.get("observed") is not None:
                row["observed"] = kwargs["observed"]
        if partitions:
            row["partitions"] = [str(p) for p in partitions]
        if ids:
            row["instance_ids"] = ids
        if red_thens:
            row["thens"] = red_thens
        if absent is not None:
            row["field_absent"] = {k: absent[k] for k in FIELD_ABSENT_KEYS}
        if not sliced:
            whole_unresolved.append(case)
        if remedy is not None:
            row["remedy"] = remedy
        if info["requirements"]:
            row["requirements"] = list(info["requirements"])
        if info["plan_row"]:
            row["plan_row"] = info["plan_row"]
        links = links_for([case], where)
        if links:
            row["case_version_links"] = links
        unresolved.append(row)

    def attempt(fn, *args, **kw):
        """Run one step of the read; a refusal of it is a problem of the file, kept, and the read goes on."""
        try:
            return fn(*args, **kw)
        except Refusal as exc:
            problems.extend(exc.problems)
            return None

    def read_mark(kwargs: dict, tf: TestFile, iid: str, pid: str, span: tuple, covers: list, partitions: list,
                  obligations: dict, shapes: list, note_lines: list) -> None:
        """One `qa` marker of an instance: its case, scope, partition, obligations, shape, note and the `then_bindings` rows."""
        case = str(kwargs["case"]).strip()
        mwhere = kwargs["_where"]
        story.case(case, mwhere)
        check_scope(case, mwhere)
        if case not in covers:
            covers.append(case)
        if kwargs.get("partition"):
            partitions.append(str(kwargs["partition"]))
        for oid in kwargs.get("obligations") or []:
            obligations[str(oid)] = story.obligation(case, str(oid), mwhere)
        if kwargs.get("shape"):
            if kwargs["shape"] not in SHAPES:
                raise Refusal(f"{mwhere}: `shape` is one of {', '.join(SHAPES)}, got {kwargs['shape']!r}")
            shapes.append(kwargs["shape"])
        if kwargs.get("note"):
            note_lines.append(str(kwargs["note"]))
        for number in _then_numbers(kwargs.get("then"), mwhere):
            row = {"case": case, "then": number, "instance_id": iid,
                   "assertion_ref": _assertion_ref(tf.rel, kwargs.get("then"), number, span),
                   "status": "covered"}
            if row not in bindings:
                bindings.append(row)

    def language_rows(tf: LanguageFile) -> None:
        """The rows of a file `test_source` read: one per declaration whose bare title names a case. A file with no entry in the
        table gives a note and no row; one with an entry and a part it could not read is refused as a list (the part is the
        author's to repair); a read that finds no case id is a note, never a silent zero."""
        if tf.no_entry:
            notes.append(_no_reader_note(tf))
            return
        if tf.why_not:
            problems.append(f"{tf.rel}:1: test not read: {tf.why_not} ({NO_READER_DOOR})")
            return
        for item in tf.unread:
            problems.append(f"{tf.rel}:{item['line']}: test not read: {item['why']} ({NO_READER_DOOR})")
        wrote = 0
        for decl in tf.declarations:
            where = f"{tf.rel}:{decl['line']}"
            cases = C.case_ids(decl["bare_title"], cfg=story.cfg)
            if not cases:
                continue                       # not a test the factory's business (no case id in its title)
            iid = C.instance_id(decl["bare_title"], None)
            selector = tf.rel + C.INSTANCE_SEP + C.INSTANCE_SEP.join(decl["title_path"])
            if iid in seen_ids and seen_ids[iid] != selector:
                problems.append(f"{where}: {decl['bare_title']!r} produces the instance id {iid!r} twice "
                                f"({seen_ids[iid]} and {selector}) - one id is one test; give the tests distinct titles")
                continue
            seen_ids[iid] = selector
            failed, covers = len(problems), []
            for case in cases:
                attempt(story.case, case, where)
                attempt(check_scope, case, where)
                covers.append(case)
            if len(problems) != failed:
                continue                       # a case of this title is unknown or outside the scope: the refusal names it
            entry = {"case": covers[0], "covers": covers, "case_version_links": links_for(covers, where),
                     "requirements": _unique(r for c in covers for r in story.case(c, where)["requirements"]),
                     "plan_row": story.case(covers[0], where)["plan_row"],
                     "file": tf.rel, "marker": covers[0], "test": decl["bare_title"], "selector": selector,
                     "instance_id": iid}
            if decl["generated"]:
                entry["generated"] = True
            entry["trace_binding"] = {"selector": selector, "assertion_refs": [], "test_content_sha": tf.content_sha}
            entry["status"] = story.run_status(iid) or story.existing_status(iid) or PENDING
            story.scaffold_sides(entry, iid)
            entry["shape"] = "consolidate" if len(covers) > 1 else ("parameterize" if decl["generated"] else "new")
            entry["consolidates"] = list(covers)
            tests.append(entry)
            wrote += 1
        if wrote:
            notes.append(f"{tf.rel}: Then bindings are the author's: this language has no marker")
            notes.append(f"{tf.rel}: novelty is measured for Python tests only; not measured for this file")
        elif not tf.unread:
            notes.append(f"{tf.rel}: read as {tf.language}, no test carries a case id the brief names; "
                         + NO_READER_DOOR)

    for tf in files:
        problems.extend(tf.problems)
        if isinstance(tf, LanguageFile):
            language_rows(tf)
            continue
        for name, kwargs in tf.module_marks:
            if name == MARK_UNRESOLVED:
                attempt(unresolved_row, kwargs, kwargs["_where"])
        module_qa = [k for n, k in tf.module_marks if n == MARK_QA]

        def read_function(node, cls, cls_marks):      # called at once, in this iteration of the loop below: `tf`, `module_qa` are its
            where = tf.where(node)
            own, params = _marks_of(node.decorator_list, f"{where} {node.name}", problems)
            held_here = []   # a `blocked_by_check` mark of THIS function waits for its instances, read just below
            for name, kwargs in [m for m in cls_marks + own if m[0] == MARK_UNRESOLVED]:
                if _is_blocked(kwargs) and any(kwargs is k for _n, k in own):
                    held_here.append(kwargs)
                else:
                    attempt(unresolved_row, kwargs, kwargs["_where"])
            base_qa = module_qa + [k for n, k in cls_marks if n == MARK_QA] + [k for n, k in own if n == MARK_QA]
            used_before = len(tf.imported_used)
            try:
                instances = _instances_of(node, tf, files, params)
            except Refusal as exc:
                if base_qa:
                    raise
                for kwargs in held_here:      # no instance is read, so the row has nobody to name: a refusal
                    attempt(unresolved_row, kwargs, kwargs["_where"], held=[])
                # A test nobody marked is not the factory's business, even when its parameter
                # list lives in a module this call was not given — only a marked function
                # needs its ids read.
                notes.append(f"{where} {node.name}: not marked, parameter list not read ({exc})")
                return
            rows_of_function = []
            for pid, param_marks in instances:
                qa_marks = base_qa + [k for n, k in param_marks if n == MARK_QA]
                iid = C.instance_id(node.name, pid or None)
                for name, kwargs in [m for m in param_marks if m[0] == MARK_UNRESOLVED]:
                    # a Then behind a red check is held by THIS instance, if it is a row of the manifest at all
                    attempt(unresolved_row, kwargs, kwargs["_where"], held=[iid] if qa_marks else [])
                if not qa_marks:
                    continue
                selector = tf.rel + C.INSTANCE_SEP + (cls.name + C.INSTANCE_SEP if cls else "") + node.name \
                    + (f"[{pid}]" if pid else "")
                if iid in seen_ids and seen_ids[iid] != selector:
                    problems.append(f"{where}: {node.name!r} produces the instance id {iid!r} twice "
                                    f"({seen_ids[iid]} and {selector}) — one id is one test; name the "
                                    "functions distinctly")
                    continue
                seen_ids[iid] = selector
                span = _assert_span(node)
                covers, partitions, obligations, shapes, note_lines = [], [], {}, [], []
                failed = len(problems)
                for kwargs in qa_marks:
                    attempt(read_mark, kwargs, tf, iid, pid, span, covers, partitions, obligations, shapes, note_lines)
                if len(problems) != failed:
                    continue                  # a marker of this instance is wrong: the refusal at the end names it
                if not partitions and pid:
                    partitions = [pid]
                entry = {
                    "case": covers[0], "covers": covers,
                    "case_version_links": links_for(covers, where),
                    "requirements": _unique(r for c in covers for r in story.case(c, where)["requirements"]),
                    "plan_row": story.case(covers[0], where)["plan_row"],
                    "file": tf.rel, "marker": covers[0], "test": node.name, "selector": selector,
                    "instance_id": iid,
                }
                if pid:
                    entry["parameter"] = pid
                if partitions:
                    entry["partitions"] = _unique(partitions)
                if obligations:
                    entry["obligation_ids"] = list(obligations)
                    entry["obligation_refs"] = [{"obligation_id": oid, "obligation_hash": content_hash(ob)}
                                                for oid, ob in obligations.items()]
                if shapes:
                    entry["shape"] = shapes[-1]
                if note_lines:
                    entry["fit_note"] = " ".join(note_lines)
                # Coverage v2 asks every row for `trace_binding {selector, assertion_refs,
                # test_content_sha}` and `window_record.py` refuses to publish a review
                # receipt without the sha - while this generator, the tool the automator's
                # brief names, emitted none of it. Live TP1-13797 (run 5, 27.09): the S5
                # review window was blocked on two of three windows for exactly this, and the
                # role was asked for a field its own tool could not produce. All three parts
                # are mechanical here - the selector is computed above, the assertion refs are
                # this instance's own `then_bindings` rows, the sha is the file just parsed.
                # `change_disposition` and `change_basis_ref` stay the role's: they are a
                # judgement about what changed and why, and nothing here can know it.
                entry["trace_binding"] = {
                    "selector": selector,
                    "assertion_refs": _unique(str(b.get("assertion_ref")) for b in bindings
                                              if str(b.get("instance_id") or "") == iid
                                              and b.get("assertion_ref")),
                    "test_content_sha": tf.content_sha}
                entry["status"] = story.run_status(iid) or story.existing_status(iid) or PENDING
                story.scaffold_sides(entry, iid)
                rows_of_function.append(entry)
            for kwargs in held_here:
                attempt(unresolved_row, kwargs, kwargs["_where"], held=[e["instance_id"] for e in rows_of_function])
            if rows_of_function:              # a module a parameter list was read from is a source of these rows
                generated_from.extend(rel for rel in tf.imported_used[used_before:] if rel not in generated_from)
            function_cases = _unique(c for e in rows_of_function for c in e["covers"])
            for entry in rows_of_function:
                entry.setdefault("shape", "consolidate" if len(function_cases) > 1
                                 else ("parameterize" if len(rows_of_function) > 1 else "new"))
                entry["consolidates"] = function_cases
                tests.append(entry)
                keyed.append((entry, (tf.rel, (cls.name,) if cls else (), node.name)))

        for node, cls, cls_marks in tf.functions:
            attempt(read_function, node, cls, cls_marks)

    if problems:
        raise _aggregate(problems)
    for entry in tests:                       # every row names the same sources: the files given and the modules read for them
        entry["generated_from"] = list(generated_from)

    for case in scope:
        if not any(C.case_matches(case, named, cfg=story.cfg) for named in cases_named):
            notes.append(f"{case} is in this dispatch's scope and no marker in the given files names it")

    if named_ids:
        held_ids = {e["instance_id"] for e in tests} | {alias for entry in C.manifest_tests(story.manifest)
                                                        for alias in C.instance_id_aliases(entry, story.cfg)}
        notes += [f"instance_ids names {iid}, which neither these files nor the manifest hold"
                  for iid in _unique(named_ids) if iid not in held_ids]

    units = _helper_units(project, files, notes) if (tests or unresolved or bindings or whole_unresolved) else []
    helper_values = _attach_novelty(story, project, keyed, notes, units)

    fragment = {}
    if tests:
        fragment["tests"] = tests
    if unresolved:
        fragment["unresolved"] = unresolved
    if bindings or whole_unresolved:
        fragment["then_bindings"] = _merge_bindings(story.manifest.get("then_bindings") or [], bindings,
                                                    {e["instance_id"] for e in tests}, whole_unresolved, notes)
    if not fragment and files and all(isinstance(tf, LanguageFile) for tf in files):
        # every file given was one `test_source` reads (or does not read): the notes above are the answer, there is nothing to
        # merge, and `manifest_put` is not called with an empty fragment (a language with no row is a note, never a refusal)
        return {"fragment": {}, "notes": notes, "scope": scope, "cases": _case_picture(story, cases_named, bindings, [])}
    if not fragment:
        raise Refusal("no `@pytest.mark.qa` / `@pytest.mark.qa_unresolved` marker in "
                      + ", ".join(tf.rel for tf in files) + " — nothing to write")
    # The helper rows ride in the same fragment. The key is sent when there are rows, or when the manifest already holds
    # rows of a file this call read (an empty list is how a function that is gone takes its row with it); a manifest
    # that never had the key, and a call that found no helper, leave it absent: an old manifest is not rewritten (D1-2).
    helpers = _helper_rows(story, units, helper_values, notes)
    held = story.manifest.get("introduced_helpers")
    read_files = {tf.rel for tf in files}
    if helpers or (isinstance(held, list) and any(isinstance(r, dict) and r.get("file") in read_files for r in held)):
        fragment["introduced_helpers"] = helpers
    return {"fragment": fragment, "notes": notes, "scope": scope,
            "cases": _case_picture(story, cases_named, bindings, whole_unresolved)}


def _merge_bindings(existing: list, mine: list, my_instances: set, whole_unresolved: list, notes=None) -> list:
    """Rows about a case+clause this fragment binds, about one of its instances, or about a case
    it declares wholly unresolved are replaced; every other row survives — `then_bindings` is a
    plain key to `manifest_put.py`, and the replaced-whole array is how 36 rows were lost once.

    One exception, in the other direction (HF2-12, C6): a row a role sent by hand that the markers do not write as their
    own - not covered, its reason one of `preserved_reasons()` (a Then behind a red check, a case red by the requirement)
    - survives even when it is about an instance of this fragment or a case it declares unresolved, so that re-running
    this writer on the file never takes it out of the manifest. It goes only when `mine` carries the row of the same key,
    (bare case, `then_number`, instance id): the author moved the Then before the red and bound it on that very test. A
    row of the same Then on ANOTHER test is no conflict here (`s5_precheck` judges that, per test). Their number goes
    into `notes` as one line when there are any (the role should know they stayed)."""
    cfg = C.case_config()  # once: one split per existing row, never one config stat per row (B-013)

    def key(row: dict) -> tuple:
        return (C.split_case_key(str(row.get("case") or ""), cfg=cfg)[1], C.then_number(row.get("then")),
                str(row.get("instance_id") or ""))

    claimed = {key(r)[:2] for r in mine}
    mine_keys = {key(r) for r in mine}
    gone = {C.split_case_key(c, cfg=cfg)[1] for c in whole_unresolved}
    hand_reasons = preserved_reasons()
    kept, hand = [], []
    for row in existing:
        if not isinstance(row, dict):
            continue
        case, number, iid = key(row)
        if key(row) in mine_keys:
            continue
        if str(row.get("status") or "covered") != "covered" and str(row.get("reason") or "") in hand_reasons:
            hand.append(row)
        elif (case, number) in claimed or iid in my_instances or case in gone:
            continue
        kept.append(row)
    if hand and notes is not None:
        reasons = sorted({str(r["reason"]) for r in hand})
        notes.append(f"kept {len(hand)} hand-sent then_bindings row(s) the markers do not write ({', '.join(reasons)})")
    return kept + mine


def _case_picture(story: Story, cases: list, bindings: list, whole_unresolved: list) -> dict:
    out = {}
    for case in cases:
        info = story.case(case, "summary")
        covered = sorted({int(b["then"]) for b in bindings if b["case"] == case and b["status"] == "covered"})
        unresolved = sorted({int(b["then"]) for b in bindings if b["case"] == case and b["status"] != "covered"})
        clauses = info["clauses"]
        unbound = [n for n in clauses if n not in covered and n not in unresolved]
        out[case] = {"clauses": clauses, "covered": covered, "unresolved": unresolved,
                     "unbound": [] if case in whole_unresolved else unbound,
                     "whole_case_unresolved": case in whole_unresolved}
    return out


# --- the CLI ---------------------------------------------------------------------------------

def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise Refusal(f"{path} is outside the project root {root} — the manifest names test files "
                      "relative to the project, never absolute (audit A20)")


def _files(raw: list, root: Path, problems=None) -> list:
    """The given files, read. A name that is no file is refused at once. With a `problems` list, a file that does not parse is
    added to it and left out, so `build` can refuse it with the marker problems of the other files, once; without, it is the
    refusal."""
    out = []
    for item in raw:
        path = Path(item)
        if not path.is_absolute() and not path.exists() and (root / item).exists():
            path = root / item
        if not path.is_file():
            raise Refusal(f"--file {item}: no such file")
        rel = _relative(path, root)
        if path.suffix.lower() != ".py":
            out.append(LanguageFile(path, rel, root))     # every other language: `test_source`, by the data of its entry
            continue
        try:
            out.append(TestFile(path, rel, root))
        except Refusal as exc:
            if problems is None:
                raise
            problems.extend(exc.problems)
    return out


def _summary(result: dict, fragment: dict) -> list:
    lines = []
    tests, unresolved = fragment.get("tests") or [], fragment.get("unresolved") or []
    bindings = fragment.get("then_bindings") or []
    lines.append(f"tests[] {len(tests)} · unresolved[] {len(unresolved)} · then_bindings {len(bindings)} "
                 "(merged with the rows already standing)")
    for entry in tests:
        thens = {}
        for b in bindings:
            if b.get("instance_id") == entry["instance_id"]:
                thens.setdefault(b["case"], []).append(str(b["then"]))
        said = " ".join(f"{c}:{','.join(n)}" for c, n in thens.items()) or "no Then bound"
        lines.append(f"  {entry['instance_id']} · covers {', '.join(entry['covers'])} · {entry['status']} · Then {said}")
    for row in unresolved:
        lines.append(f"  {row['case']} · unresolved · {row['reason']}"
                     + (f" · partitions {', '.join(row['partitions'])}" if row.get("partitions") else ""))
    lines.append("cases:")
    for case, pic in result["cases"].items():
        if pic["whole_case_unresolved"]:
            lines.append(f"  {case} · whole case unresolved")
            continue
        total = len(pic["clauses"])
        part = f"Then {','.join(map(str, pic['covered'])) or '-'} bound"
        if pic["unresolved"]:
            part += f" · {','.join(map(str, pic['unresolved']))} unresolved"
        if pic["unbound"]:
            part += f" · {','.join(map(str, pic['unbound']))} UNBOUND — s5_precheck.py will name them"
        lines.append(f"  {case} · {part} ({len(pic['covered']) + len(pic['unresolved'])} of {total or '?'})")
    for note in result["notes"]:
        lines.append("note: " + note)
    return lines


# --- the row form: what each `tests[]` row still lacks, printed and never sent (HF2-12, EP1-18 (a)) ------------------

def _legend_line(field: str, spec, cfg: dict, rows: list) -> str:
    """One line of what a missing field holds: the carrier's own words (`window_record.RowField.what`), the profiles that
    can own the file for `profile_id`, the marker for a field the marker writes (no slot for it in the form: a hand value
    would not carry the plan's hash)."""
    if spec.filled_by != "automator":
        return f"{spec.what}; written by the marker, not by hand: {spec.origin_door}"
    if field != "profile_id":
        return spec.what
    import execution_request as ER
    names = list(dict.fromkeys(name for entry in rows for name in ER.profiles_owning(cfg, entry.get("file"))
                               or ER.known_profile_ids(cfg)))
    return spec.what + ("; one of: " + ", ".join(names) if names else "")


def _row_form(task_root: Path, view: dict, wanted: list) -> tuple:
    """(form, lines): the fields the rows of this run still lack, for the role to fill BEFORE its first handback.

    `view` is the manifest as it stands (or will stand) after this run's fragment - read back from disk by the caller,
    or `manifest_put.merge` of the fragment: the same merge the writer's `manifest_put` runs, so a field a role already
    wrote is not asked again (`_merge_entry` keeps what a fragment does not send). `wanted` are the instance ids of the
    rows this run wrote. The predicate is `window_record.row_field_gaps` and the names are its carrier
    (`REQUIRED_ROW_FIELDS`): a field added there reaches this form with no edit here (AR-13).

    The form is `{"tests": [{"instance_id": "<id>", "<field>": null, ...}]}` - only the rows with a gap, only the fields
    the automator writes (`filled_by`); `legend` says what each field holds. It is PRINTED, never put into the fragment:
    `manifest_put._merge_entry` updates a row with every key a fragment sends, so a `null` sent from here would wipe
    a value the role wrote a moment ago. `window_record` is imported here and nowhere else: `stage_guard`, a hook, imports
    this module, and the window pulls in the acceptance and the reporters."""
    import window_record as WR
    from s5_precheck import case_plan_row, instances_of_case
    cfg, scfg = load_config(), C.case_config(task_root)
    plan, handed = C.plan_obligations(task_root), {row["case"] for row in C.handed_tests(view)}
    form, needed, asked = {"tests": [], "legend": {}}, {}, []
    for entry in C.manifest_tests(view):
        aliases = C.instance_id_aliases(entry, scfg)
        if not any(w in aliases for w in wanted):
            continue
        asked.extend(w for w in wanted if w in aliases)
        owed = []
        for case in C.manifest_test_links(entry, scfg):
            plan_row = case_plan_row(task_root, case, "", instances_of_case(view, case)) \
                if plan and case not in handed else ""
            owed += [ob for row, ob in plan if plan_row and row == plan_row]
        gaps = WR.row_field_gaps(entry, cfg, owed)
        for field, _problem in gaps:
            needed.setdefault(field, []).append(entry)
        slots = {f: None for f, _problem in gaps if WR.REQUIRED_ROW_FIELDS[f].filled_by == "automator"}
        if slots:
            form["tests"].append({"instance_id": C.test_instance_id(entry), **slots})
    form["legend"] = {f: _legend_line(f, spec, cfg, needed[f]) for f, spec in WR.REQUIRED_ROW_FIELDS.items() if f in needed}
    lines = [f"row fields not read for {w}: no such row in the manifest" for w in wanted if w not in asked]
    if not form["legend"] and wanted:
        return form, lines + ["row fields: every row of this window carries them"]
    if form["tests"]:
        task = Path(task_root).name
        lines += ["row form - each null is a field the window record or the test run will refuse the row without; fill it "
                  f"(a field left null counts as missing) and send it with `{WR.FRAGMENT_DOOR.replace('<T>', task)}` "
                  "before your handback:",
                  json.dumps({"tests": form["tests"]}, ensure_ascii=False, indent=2)]
    else:
        lines.append("row fields still missing, and not yours to fill by hand:")
    lines += [f"  `{field}`: {line}" for field, line in form["legend"].items()]
    return form, lines


def _form_after_write(task_root: Path, story: Story, fragment: dict, dry_run: bool, put_code: int, notes: list) -> tuple:
    """(form, lines) of `_row_form` for the rows this run wrote, or (None, []) with a note when they cannot be read. The
    rows are read from the manifest the write saved - one view of it, `manifest_put`'s - and on a dry run from
    `manifest_put.merge(manifest, fragment)`, the same pure merge, which is why no second merge lives here. A write that
    failed leaves no form: its rows are not in the manifest (the form is a help; it never stops the factory, P1)."""
    if put_code:
        notes.append("row form skipped: the fragment was not written")
        return None, []
    try:
        if dry_run:
            import manifest_put
            view = manifest_put.merge(copy.deepcopy(story.manifest), copy.deepcopy(fragment))[0]
            notes.append("send it after the write: these rows are not in the manifest yet")
        else:
            view = C.load_json(C.artifact(task_root, "automation-manifest.json"))
        return _row_form(task_root, view, [str(e.get("instance_id") or "") for e in fragment.get("tests") or []])
    except Exception as exc:
        notes.append(f"row form skipped: {type(exc).__name__}")
        return None, []


def collect_refusal(rels) -> None:
    """`--collect` resolves ids through a pytest collection, and a file that is not Python has none: the refusal names the file and
    the way on (the door is to run without `--collect`)."""
    other = [rel for rel in rels if not str(rel).lower().endswith(".py")]
    if other:
        raise Refusal(f"--collect applies to pytest only: {', '.join(other)} is not a Python test file, so its instance ids cannot be "
                      "resolved through pytest. Run without --collect: the ids are then read from the source and not verified "
                      "against the runner")


def _blank_row_form(task: str) -> tuple:
    """(form, lines) of the `tests[]` row form when this call wrote no row: a skeleton with one `null` for every field the
    window record or the test run demands of a row and the automator fills, and what each holds (`window_record` is the carrier
    of both, `_legend_line` words them). `form` is the shape `_row_form` returns (`{"tests": [slot], "legend": {...}}`), so
    `--json` carries what the text says is printed. PRINTED, never sent. A form that cannot be built is (None, []): it is a
    help (P1)."""
    try:
        import window_record as WR
        cfg = load_config()
        fields = {f: s for f, s in WR.REQUIRED_ROW_FIELDS.items() if s.filled_by == "automator"}
        slot = {"instance_id": "<the instance id>", **{f: None for f in fields}}
        legend = {field: _legend_line(field, spec, cfg, []) for field, spec in fields.items()}
        lines = (["row form - for a file nobody read: each null is a field the window record or the test run will refuse the row "
                  f"without; fill it and send it with `{WR.FRAGMENT_DOOR.replace('<T>', task)}`:",
                  json.dumps({"tests": [slot]}, ensure_ascii=False, indent=2)]
                 + [f"  `{field}`: {line}" for field, line in legend.items()])
        return {"tests": [slot], "legend": legend}, lines
    except Exception:
        return None, []


def resolve_through_pytest(fragment: dict, command: list, cwd: str, notes: list) -> dict:
    """Rewrite the fragment's instance ids to the ones pytest really collects (FR-16).

    The ids here are read out of the source with `ast`, and the source is not the last word on
    them: a project's own plugins rename a parameter id before pytest collects it —
    pytest-playwright prepends the browser, so `test_x[eu]` is collected as
    `test_x[chromium-eu]`. On TP1-15045 the manifest kept the author's spelling, 15 of 27 run
    rows never joined it, 16 obligations read "not proven" against a fully green execution, and
    the mismatch surfaced at S8 — after the review window was accepted and the roles released.
    `node_ids.py` exists for exactly this, and it was wired into the runner, the sandbox and the
    probe but not into the writer of the ids (FR-17).

    An id with one obvious real spelling is rewritten and the rewrite is a note. An id pytest
    does not collect at all is a refusal: writing it would repeat the run-5 defect.
    """
    import node_ids
    # `node_ids` speaks pytest's own language: a full node id, `<file>::<function>[<param>]`. The
    # manifest spells an instance without its file (`contract.instance_id`) and carries the file
    # beside it, so the ask is assembled here and the answer is spelled back the manifest's way.
    collect_refusal(str(e.get("file") or "") for e in fragment.get("tests") or [] if e.get("file"))
    asked, back = [], {}
    for entry in fragment.get("tests") or []:
        iid = str(entry.get("instance_id") or "")
        file = str(entry.get("file") or "").replace("\\", "/")
        if not iid or not file:
            continue
        node = f"{file}::{iid}"
        asked.append(node)
        back[node] = iid
    if not asked:
        return fragment
    form, table_note = node_ids.runner_form(command)   # the runner's row: one broken file does not hide the rest (AR-15)
    checked = node_ids.check_request(command, cwd, sorted(set(asked)), form=form)
    for note in ([table_note] if table_note else []) + list(checked.get("notes") or []):
        notes.append("node_ids: " + str(note))
    if checked.get("missing"):
        raise Refusal(
            "pytest does not collect " + node_ids.missing_sentence(checked["missing"])
            + ". Nothing was written. The id in the manifest has to be the id pytest collects, or "
            "the join at S6 finds nothing and the obligation reads \"not proven\" against a green "
            "run. Fix the marker or the parameter id in the test, or run without --collect and say "
            "in your handoff that the ids are unverified. " + node_ids.repair_marker())
    # Back to the manifest's spelling: the part after the last `::` is the instance id.
    resolved = {back[str(a)]: str(r).rsplit("::", 1)[-1]
                for a, r in (checked.get("resolved") or {}).items()
                if str(a) in back and str(a) != str(r)}
    if not resolved:
        return fragment
    for entry in fragment.get("tests") or []:
        iid = str(entry.get("instance_id") or "")
        if iid in resolved:
            entry["instance_id"] = resolved[iid]
    for row in fragment.get("then_bindings") or []:
        iid = str(row.get("instance_id") or "")
        if iid in resolved:
            row["instance_id"] = resolved[iid]
    for old, new in sorted(resolved.items()):
        notes.append(f"pytest collects {old} as {new} — the manifest carries the collected id "
                     "(a project plugin renames the parameter, not you)")
    return fragment


def _refused(ns, text: str, problems=None) -> int:
    """Print a refusal and give its exit code. `--json`: `refusal` stays ONE string as it was (FR-14) and `problems` lists every
    line it is made of, whole - the text of a long refusal is cut at `REFUSAL_LINES`, this list is not."""
    if ns.json:
        print(json.dumps({"ok": False, "refusal": text, "problems": list(problems or [text])}, ensure_ascii=False, indent=2))
    else:
        print(f"manifest_from_tests: {text}", file=sys.stderr)
    return EXIT_REFUSED


def main() -> int:
    C.force_utf8()
    raw = sys.argv[1:]
    command = []
    if "--" in raw:
        cut = raw.index("--")
        raw, command = raw[:cut], raw[cut + 1:]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=REGISTRATION_HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="ticket id")
    ap.add_argument("--dispatch", required=True, help="your dispatch id (S5-qa-automator-<n>)")
    ap.add_argument("--file", action="append", required=True,
                    help="a test file to read; repeat only for a parameter-list module the test file's own import does not "
                         "lead to (the script follows `from <module> import <name>` itself)")
    ap.add_argument("--dry-run", action="store_true", help="print the fragment, write nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--collect", action="store_true",
                    help="resolve every instance id through a real pytest collection before "
                         "writing it, with the test command after `--` (FR-16): a project plugin "
                         "may rename a parameter id, and the manifest must carry the id pytest "
                         "collects. Without it the ids are the source's own and the output says so.")
    ap.add_argument("--cwd", default=".", help="--collect: where to run the test command")
    ns = ap.parse_args(raw)
    if ns.collect and not command:
        ap.error("--collect needs the test command after `--`, e.g. `-- python -m pytest`")

    root = project_root()
    try:
        # the story must EXIST, a dry run too: it reads the story anyway (CX1-18; a dry run outside an onboarded
        # project now exits 3 like a write, m-7). Never a folder made here: S0 makes it.
        task_root = story_root(ns.task, "manifest_from_tests.py --task")
    except ValueError as exc:
        return _refused(ns, str(exc))
    try:
        unread: list = []     # a given file that does not parse: refused with the marker problems of the others
        files = _files(ns.file, root, unread)
        if ns.collect:
            collect_refusal(tf.rel for tf in files)
        story = Story(ns.task, task_root)
        result = build(story, files, ns.dispatch, project=root, prior_problems=unread)
    except Refusal as exc:
        return _refused(ns, str(exc), exc.problems)
    fragment = result["fragment"]
    if not fragment:
        # only files `test_source` reads (or does not read) and no row: the notes are the answer; `manifest_put` is not called
        blank_form, form_lines = _blank_row_form(ns.task)
        if ns.json:
            print(json.dumps({"ok": True, "dry_run": ns.dry_run, "fragment": {}, "fragment_path": "", "cases": result["cases"],
                              "notes": result["notes"], "scope": result["scope"],
                              "manifest_put": "not called: nothing to write", "row_form": blank_form}, ensure_ascii=False, indent=2))
        else:
            print("manifest_from_tests: nothing written - no row was read, manifest_put.py was not called")
            for note in result["notes"]:
                print("note: " + note)
            for line in form_lines:
                print(line)
        return 0
    try:
        if ns.collect:
            fragment = resolve_through_pytest(fragment, command, ns.cwd, result["notes"])
        elif fragment.get("tests"):
            # An unknown says so (FR-41): these ids are the source's, and the source is not the
            # last word on a parameter id a project's plugins rewrite.
            result["notes"].append(
                "instance ids were read from the source and NOT verified against pytest — run "
                "with `--collect -- <your test command>` to resolve them through a real "
                "collection; an id pytest does not collect joins nothing at S6")
    except Refusal as exc:
        return _refused(ns, str(exc), exc.problems)
    written, put_output, put_code = "", "", 0
    if not ns.dry_run:
        digest = content_hash(fragment)[:8]
        path = task_root / "work" / FRAGMENT_DIR / f"{ns.dispatch}-{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fragment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written = path.relative_to(task_root).as_posix()
        import event_store
        import manifest_put
        buffer = io.StringIO()
        # `main` is the command's entry, so the lifecycle wait is chosen here and handed down;
        # `manifest_put.run` itself keeps 0 for every other caller.
        with contextlib.redirect_stdout(buffer):
            put_code = manifest_put.run(ns.task, str(path),
                                        wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS)
        put_output = buffer.getvalue().strip()
    row_form, form_lines = _form_after_write(task_root, story, fragment, ns.dry_run, put_code, result["notes"])
    if ns.json:
        print(json.dumps({"ok": put_code == 0, "dry_run": ns.dry_run, "fragment": fragment,
                          "fragment_path": written, "cases": result["cases"], "notes": result["notes"],
                          "scope": result["scope"], "manifest_put": put_output, "row_form": row_form},
                         ensure_ascii=False, indent=2))
    else:
        if ns.dry_run:
            print(json.dumps(fragment, ensure_ascii=False, indent=2))
            print("manifest_from_tests: dry run — nothing written")
        else:
            print(f"manifest_from_tests: fragment {written} → manifest_put.py")
        for line in _summary(result, fragment):
            print(line)
        if put_output:
            print(put_output)
        for line in form_lines:
            print(line)
    return EXIT_PUT_FAILED if put_code else 0


if __name__ == "__main__":
    sys.exit(main())
