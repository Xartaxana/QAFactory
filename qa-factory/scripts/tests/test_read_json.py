"""hooklib.read_json: the package's ONE JSON file reader (B-309 e), and the error direction each caller kept.

Ten private `_read_json` copies became one reader. What differed between them was never the reading but what a file that
cannot be read means to the caller (None, {}, a default, an object only; any exception or only the ones a bad file raises).
Each caller's direction is pinned here at the edge and beyond it: absent file, empty file, invalid JSON, a BOM, a directory,
bytes that are not UTF-8, a nesting the parser gives up on, a path that is not a path.

Runnable on its own: `python -B scripts/tests/test_read_json.py`."""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hooklib  # noqa: E402
import archive_task  # noqa: E402
import exit_gate  # noqa: E402
import execution_request  # noqa: E402
import gate_preflight  # noqa: E402
import guard_app_under_test  # noqa: E402
import handoff  # noqa: E402
import retro_numbers  # noqa: E402
import s5_precheck  # noqa: E402
import sizing  # noqa: E402
import stage_done  # noqa: E402
import stage_guard  # noqa: E402
import stage_status  # noqa: E402
import stand_gaps  # noqa: E402
import story_budget  # noqa: E402
import story_run  # noqa: E402
import story_version  # noqa: E402
import tracker_write  # noqa: E402
import turn_budget  # noqa: E402
import window_budget  # noqa: E402

GOOD = '{"a": 1}'
VALUE = {"a": 1}
DEEP = "[" * 300000          # the C scanner gives up with RecursionError, which is not a ValueError
BOM = b"\xef\xbb\xbf"


def make_files(root: Path, good: str = GOOD) -> dict:
    """One file per way a path can fail the reader, plus the good one; the keys name the case."""
    files = {
        "good": root / "good.json",
        "empty": root / "empty.json",
        "invalid": root / "invalid.json",
        "bom": root / "bom.json",
        "latin1": root / "latin1.json",
        "deep": root / "deep.json",
        "list": root / "list.json",
        "null": root / "null.json",
        "dir": root / "a_directory.json",
        "missing": root / "missing.json",
    }
    files["good"].write_text(good, encoding="utf-8")
    files["empty"].write_text("", encoding="utf-8")
    files["invalid"].write_text("{not json", encoding="utf-8")
    files["bom"].write_bytes(BOM + good.encode("utf-8"))
    files["latin1"].write_bytes(b'{"a": "\xe9"}')
    files["deep"].write_text(DEEP, encoding="utf-8")
    files["list"].write_text("[1, 2]", encoding="utf-8")
    files["null"].write_text("null", encoding="utf-8")
    files["dir"].mkdir()
    return files


def test_the_reader_itself(files: dict) -> None:
    read = hooklib.read_json
    check_eq("R1 a good file is its value", read(files["good"]), VALUE)
    check_eq("R1 a str path is a path too", read(str(files["good"])), VALUE)
    check_eq("R1 a BOM is the encoding, not a parse error", read(files["bom"]), VALUE)
    check_eq("R1 a list is returned as parsed (a caller that needs an object checks the type)", read(files["list"]), [1, 2])
    check_eq("R1 a file that holds null is None, whatever the default", read(files["null"], {}), None)
    for name in ("missing", "empty", "invalid", "latin1", "dir"):
        check_eq(f"R2 {name}: None by default", read(files[name]), None)
        check_eq(f"R2 {name}: the caller's default, positionally", read(files[name], {}), {})
        check_eq(f"R2 {name}: the caller's default, by keyword", read(files[name], default=[]), [])
    # beyond: what the default error pair does NOT swallow, and what errors=Exception does
    try:
        read(files["deep"])
        got = "swallowed"
    except RecursionError:
        got = "RecursionError"
    check_eq("R3 a nesting the parser gives up on is not a bad file: the default pair lets it through", got, "RecursionError")
    check_eq("R3 ...and errors=Exception reads it as the default", read(files["deep"], {}, errors=Exception), {})
    try:
        read(None)
        got = "swallowed"
    except TypeError:
        got = "TypeError"
    check_eq("R4 a path that is not a path is a bug of the caller: the default pair lets it through", got, "TypeError")
    check_eq("R4 ...and errors=Exception reads it as the default", read(None, {}, errors=Exception), {})
    # kind=: the caller names the type it needs; a document of another type is "nothing there" (t-666 R1)
    check_eq("R5 kind=dict: an object is returned as parsed", read(files["good"], {}, kind=dict), VALUE)
    check_eq("R5 kind=dict: a BOM object too", read(files["bom"], kind=dict), VALUE)
    check_eq("R6 kind=dict: a list gives the caller's default", read(files["list"], {}, kind=dict), {})
    check_eq("R6 kind=dict: a list gives None when the caller names no default", read(files["list"], kind=dict), None)
    check_eq("R6 kind=dict: a null gives the default", read(files["null"], "d", kind=dict), "d")
    check_eq("R6 kind=list: a list is returned as parsed, an object gives the default",
             (read(files["list"], kind=list), read(files["good"], [], kind=list)), ([1, 2], []))
    check_eq("R6 kind=(dict, list): either type is returned as parsed",
             (read(files["good"], kind=(dict, list)), read(files["list"], kind=(dict, list))), (VALUE, [1, 2]))
    check_eq("R7 kind=dict does not touch the default for an absent file", read(files["missing"], {}, kind=dict), {})
    try:
        read(files["deep"], {}, kind=dict)
        got = "swallowed"
    except RecursionError:
        got = "RecursionError"
    check_eq("R7 kind does not widen errors: the default pair still lets a nesting bomb through", got, "RecursionError")
    check_eq("R7 ...and errors=Exception with kind=dict reads it as the default",
             read(files["deep"], {}, errors=Exception, kind=dict), {})


def broad_none(read, files: dict, label: str) -> None:
    """The direction of stand_gaps, gate_preflight, sizing, stage_status and tracker_write: anything wrong is the default (None)."""
    check_eq(f"{label}: a good file", read(files["good"]), VALUE)
    check_eq(f"{label}: a BOM is read", read(files["bom"]), VALUE)
    for name in ("missing", "empty", "invalid", "latin1", "dir", "deep"):
        check_eq(f"{label}: {name} is None", read(files[name]), None)
        check_eq(f"{label}: {name} is the caller's default", read(files[name], []), [])
    check_eq(f"{label}: a list is returned as parsed", read(files["list"]), [1, 2])
    check_eq(f"{label}: a path that is not a path is the default too", read(None, "d"), "d")


def test_the_callers(files: dict) -> None:
    for module in (stand_gaps, gate_preflight, sizing, stage_status, tracker_write):
        broad_none(module._read_json, files, f"C1 {module.__name__}")

    # exit_gate: an object or {} - a list or null is not a gate input
    read = exit_gate._read_json
    check_eq("C2 exit_gate: a good file", read(files["good"]), VALUE)
    check_eq("C2 exit_gate: a BOM is read", read(files["bom"]), VALUE)
    for name in ("missing", "empty", "invalid", "latin1", "dir", "deep", "list", "null"):
        check_eq(f"C2 exit_gate: {name} is {{}}", read(files[name]), {})

    # execution_request: None for a bad file, but the default error pair only (a nesting bomb is not swallowed)
    read = execution_request._read_json
    check_eq("C3 execution_request: a good file", read(files["good"]), VALUE)
    check_eq("C3 execution_request: a BOM is read", read(files["bom"]), VALUE)
    for name in ("missing", "empty", "invalid", "latin1", "dir"):
        check_eq(f"C3 execution_request: {name} is None", read(files[name]), None)
    try:
        read(files["deep"])
        got = "swallowed"
    except RecursionError:
        got = "RecursionError"
    check_eq("C3 execution_request: a nesting the parser gives up on still reaches the caller", got, "RecursionError")

    # story_run: {} unless the caller names its own default; None only when the file says null
    read = story_run._read_json
    check_eq("C4 story_run: a good file", read(files["good"]), VALUE)
    check_eq("C4 story_run: a BOM is read", read(files["bom"]), VALUE)
    for name in ("missing", "empty", "invalid", "latin1", "dir"):
        check_eq(f"C4 story_run: {name} is {{}}", read(files[name]), {})
        check_eq(f"C4 story_run: {name} is the caller's default", read(files[name], default=[]), [])
    check_eq("C4 story_run: a file that holds null is None (the file's own word)", read(files["null"]), None)
    try:
        read(files["deep"])
        got = "swallowed"
    except RecursionError:
        got = "RecursionError"
    check_eq("C4 story_run: a nesting the parser gives up on still reaches the caller", got, "RecursionError")


def test_the_copies_are_gone() -> None:
    """The class, not the instance: no module of the package keeps a body that reads JSON the way the ten copies did."""
    import inspect
    for module in (stand_gaps, gate_preflight, sizing, stage_status, tracker_write):
        check(f"G1 {module.__name__}._read_json is the shared reader with a direction, not a body of its own",
              getattr(module._read_json, "func", None) is hooklib.read_json)
    check("G2 execution_request reads through the shared reader", execution_request._read_json is hooklib.read_json)
    for module in (exit_gate, story_run):
        source = inspect.getsource(module._read_json)
        check(f"G3 {module.__name__}._read_json calls the shared reader", "read_json(" in source and "json.loads" not in source)
    check("G6 retro_numbers.read_json is the shared reader with a direction, not a body of its own",
          getattr(retro_numbers.read_json, "func", None) is hooklib.read_json)
    for module, name in ((archive_task, "read_json"), (stage_guard, "read_json"), (stage_done, "read_pipeline"),
                         (s5_precheck, "_load"), (story_budget, "read_marker"), (story_budget, "read_config"),
                         (window_budget, "read_marks"), (window_budget, "read_config"), (turn_budget, "read_count"),
                         (hooklib, "_json_or_none")):
        source = inspect.getsource(getattr(module, name))
        check(f"G7 {module.__name__}.{name} calls the shared reader",
              "read_json(" in source and "json.loads" not in source)
    check("G4 gate_preflight and stand_gaps share ONE GATE_STAGE", gate_preflight.GATE_STAGE is stand_gaps.GATE_STAGE)
    check_eq("G4 ...and it says what it said", stand_gaps.GATE_STAGE, {"A": "S5", "B": "S9"})


# --- C5: the readers that kept a body of their own (t-666 R1), case by case ----------------------------------------------
# The cases a reader that used to read `utf-8` reads as DATA since t-677 (F-2): a BOM file and a `str` path were "nothing
# there" for these readers (a BOM is a parse error in `utf-8`, and `str` has no `read_text`). A reader reads what the file
# says. The output line of every row names what it expects, so the flip is visible in a diff of two runs.
DATA_CASES = ("good", "bom", "str")
CASES = ("good", "bom", "empty", "invalid", "latin1", "deep", "list", "null", "dir", "missing", "str", "none")
PIPE = {"ticket": "QA-1", "stages": {"S1": {"status": "running"}},
        "stage_overrides": [{"stage": "S5", "match": "story budget", "decision": "go on"}]}
OBJECT_READERS = (
    ("archive_task.read_json", archive_task.read_json),
    ("stage_guard.read_json", stage_guard.read_json),
    ("stage_done.read_pipeline", stage_done.read_pipeline),
    ("s5_precheck._load", s5_precheck._load),
    ("story_budget.read_marker", story_budget.read_marker),
    ("window_budget.read_marks", window_budget.read_marks),
    ("turn_budget.read_count", turn_budget.read_count),
)


def raised(call):
    """What the call returns, or the name of the exception that escapes it."""
    try:
        return call()
    except Exception as exc:
        return f"raises {type(exc).__name__}"


def arg_for(files: dict, case: str):
    if case == "str":
        return str(files["good"])
    if case == "none":
        return None
    return files[case]


def row(label: str, case: str, got, expected) -> None:
    check_eq(f"C5 {label} | {case} | {expected!r}", got, expected)


def place(folder: Path, name: str, files: dict, case: str) -> None:
    """`folder/name` is the case: the bytes of its file, a directory, or nothing at all."""
    folder.mkdir(parents=True, exist_ok=True)
    source = files[case]
    if source.is_dir():
        (folder / name).mkdir()
    elif source.exists():
        (folder / name).write_bytes(source.read_bytes())


def c5_object_reader(label: str, read, files: dict) -> None:
    """An object or {}: a list, a null, a nesting bomb and every unreadable file are {} (E1, E2, E4, E5)."""
    for case in CASES:
        row(label, case, raised(lambda: read(arg_for(files, case))), VALUE if case in DATA_CASES else {})
    first = read(files["missing"])
    first["touched"] = True
    check_eq(f"C5 {label} | E3 a NEW {{}} per call: a caller that mutates it changes nothing next time",
             read(files["missing"]), {})


def c5_value_reader(files: dict) -> None:
    """retro_numbers.read_json(path, default=None): the value as parsed (a list, a null), the default otherwise."""
    read = retro_numbers.read_json
    for case in CASES:
        expected = VALUE if case in DATA_CASES else [1, 2] if case == "list" else None
        row("retro_numbers.read_json", case, raised(lambda: read(arg_for(files, case))), expected)
    row("retro_numbers.read_json", "missing, default given", read(files["missing"], "d"), "d")
    row("retro_numbers.read_json", "deep, default by keyword", read(files["deep"], default="d"), "d")
    row("retro_numbers.read_json", "null, default given (the file's own word)", read(files["null"], "d"), None)


def c5_root_readers(files: dict, root: Path) -> None:
    """The two `read_config(root)`: `root/config.json`, the value as parsed or {}. A root of None is a bug of the caller."""
    for module in (story_budget, window_budget):
        label = f"{module.__name__}.read_config"
        for case in CASES[:-2]:
            folder = root / f"{module.__name__}-{case}"
            place(folder, "config.json", files, case)
            expected = VALUE if case in DATA_CASES else [1, 2] if case == "list" else None if case == "null" else {}
            row(label, case, raised(lambda: module.read_config(folder)), expected)
        row(label, "root given as a str", module.read_config(str(root / f"{module.__name__}-good")), VALUE)
        # E6: this used to be {} (`Path(root)` sat inside the try). Nothing can pass None: the one caller builds a Path.
        row(label, "root is None", raised(lambda: module.read_config(None)), "raises TypeError")


def c5_kept_readers(files: dict) -> None:
    """Readers that read through their own default error pair or keep their own body: pinned so that a move is seen."""
    kept_object = story_version._read_pipeline          # stays: the module imports no package module (S3)
    for case in CASES:
        row("story_version._read_pipeline", case, raised(lambda: kept_object(arg_for(files, case))),
            VALUE if case == "good" else {})
    for label, read in (("hooklib._json_or_none", hooklib._json_or_none), ("handoff.load_json", handoff.load_json)):
        for case in CASES:
            if case == "deep":
                expected = "raises RecursionError"
            elif case in ("str", "none") and label == "handoff.load_json":
                expected = "raises AttributeError"       # it calls `path.read_text`: a str or None has none
            elif case == "none":
                expected = "raises TypeError"
            elif case in ("good", "bom", "str"):
                expected = VALUE
            elif case == "list" and label == "handoff.load_json":
                expected = [1, 2]            # the object check is `_json_or_none`'s, not `load_json`'s
            else:
                expected = None
            row(label, case, raised(lambda: read(arg_for(files, case))), expected)


def c5_inline_sites(root: Path) -> None:
    """The three sites that read inside a larger function, seen through their callers. `good` is a running story that
    carries the person's word on the ceiling; every other case is a pipeline the site cannot use."""
    (root / "pipelines").mkdir(parents=True)
    files = make_files(root / "pipelines", good=json.dumps(PIPE))
    override = PIPE["stage_overrides"][0]
    for case in CASES[:-2]:
        expected = PIPE if case in DATA_CASES else {}
        folder = root / f"guard-{case}"
        place(folder, "pipeline.json", files, case)
        real = guard_app_under_test.artifacts_dir
        guard_app_under_test.artifacts_dir = lambda ticket, event=None, folder=folder: folder
        try:
            row("guard_app_under_test._story_pipeline", case, raised(lambda: guard_app_under_test._story_pipeline({}, "QA-1")),
                expected)
        finally:
            guard_app_under_test.artifacts_dir = real

        base = root / f"window-{case}" / "qa-factory"
        place(base / "artifacts" / "QA-1", "pipeline.json", files, case)
        row("window_budget.open_work", case, raised(lambda: window_budget.open_work(base)["stage"]),
            "S1" if case in DATA_CASES else "")

        base = root / f"budget-{case}" / "qa-factory"
        troot = base / "artifacts" / "QA-1"
        (base / "state" / "cost").mkdir(parents=True)
        (troot / "state").mkdir(parents=True)
        (base / "config.json").write_text(json.dumps({"budget": {"story_usd": 10.0, "warn_at": [0.5, 0.8]}}), encoding="utf-8")
        (troot / "state" / "driver-runs.jsonl").write_text(json.dumps(
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1", "session_id": "s-1",
             "num_turns": 3, "total_cost_usd": 11.0, "ts": "2026-09-23T10:30:00+00:00"}) + "\n", encoding="utf-8")
        place(troot, "pipeline.json", files, case)
        row("story_budget.check", case, raised(lambda: story_budget.check("QA-1", base, troot)["overridden"]),
            override if case in DATA_CASES else None)
    row("guard_app_under_test._story_pipeline", "a ticket that is no path component (E6)",
        raised(lambda: guard_app_under_test._story_pipeline({}, "a/b")), {})


def c5_stage_guard_facts(root: Path) -> None:
    """S1 (critic t-670): `stage_guard.is_archived` and `story_closed` now SEE a BOM pipeline: an archived story is
    filtered out, a closed one is counted as closed. The one place where a verdict changes besides the twins' own."""
    seen = "bom" in DATA_CASES
    for name, text in (("archived", '{"archived": true}'), ("closed", '{"closed_at": "2026-10-01T10:00:00"}')):
        for kind, prefix in (("plain", b""), ("bom", BOM)):
            folder = root / f"facts-{name}-{kind}"
            (folder / "T1").mkdir(parents=True)
            (folder / "T1" / "pipeline.json").write_bytes(prefix + text.encode("utf-8"))
            facts: dict = {}
            stage_guard._collect_story_facts(folder, "", facts)
            read = kind == "plain" or seen
            if name == "archived":
                row("stage_guard._collect_story_facts", f"{kind} archived pipeline: listed as a candidate",
                    facts["pipelines"], [] if read else ["T1"])
            else:
                row("stage_guard._collect_story_facts", f"{kind} closed pipeline: counted as closed",
                    (facts["closed"], facts["pipelines"]), (["T1"], []) if read else ([], ["T1"]))
    path = root / "facts-archived-bom" / "T1" / "pipeline.json"
    row("stage_guard.is_archived", "bom archived pipeline", stage_guard.is_archived(path), seen)
    row("stage_guard.is_archived", "plain archived pipeline",
        stage_guard.is_archived(root / "facts-archived-plain" / "T1" / "pipeline.json"), True)


def test_c5_characterisation(files: dict, root: Path) -> None:
    for label, read in OBJECT_READERS:
        c5_object_reader(label, read, files)
    c5_value_reader(files)
    c5_root_readers(files, root)
    c5_kept_readers(files)
    c5_inline_sites(root)
    c5_stage_guard_facts(root)


# --- G5: the census. A function that is only "read this JSON file, else a constant" must call hooklib.read_json ------------
# The clone ratchet sees growth, never convergence (t-666 D-1): a new reader-shaped function would pass it. This is the
# detector that sees one. It is an AST walk, not a grep, over `scripts/*.py` (tests excluded).
#
# THE SHAPE (t-670 M1): a function whose body, docstring aside, is at most TWO statements, one of them a `try` whose own
# body has at most two statements and holds `json.loads(<expr>.read_text(...))` or `json.load(<expr>)`, and whose
# handlers only `return` a constant, a name or an empty literal, or `pass`. The carrier is excluded by name.
# BLIND TO: an inline read inside a longer function, a `try` of three statements or more, a reader that returns a
# computed value from its handler, `json.loads(text)` of text read some other way. It errs RED on a reader that has a
# different contract on purpose: such a reader gets a KEPT row with the reason, and that row is the door.
#
# THE DOOR (any node, S7): a new reader-shaped function either calls `hooklib.read_json` (`kind=dict` for an object) or
# adds ONE row to KEPT with its reason. A STALE row (a name that no longer has the shape, or no longer exists) is red
# too, so the allow-list never rots.
CARRIER = "hooklib.read_json"
QUEUED = "queued: findings/20261010-json-readers-outside-the-list.md"
NO_IMPORTS = "stays: the module imports no package module and a heavier import surface is argued against ({where})"
KEPT = {
    # --- stays, each with its reason (the reason is the door) ---
    "hooklib.load_ref_json": "stays: its docstring contract, a partial checkout must not jam a hook, covers the path build "
                             "ref(name) inside the try (t-666 row 1.19)",
    "story_version._read_pipeline": NO_IMPORTS.format(where="story_version.py:28-33; t-666 S3, row 1.7"),
    "handoff.load_json": NO_IMPORTS.format(where="handoff.py:23-26; t-666 S3, row 1.20"),
    "probe_by_code._read_check_record": "stays: the path build proof_level.record_read_path(...) sits inside the try, and a hostile record "
                                        "(nesting too deep: RecursionError; a path that is no path: TypeError) or one that is not an object "
                                        "reads as nothing - the probe's own error direction, one file (t-2064 P4b)",
    "probe_by_code._stored_rows": "stays: the path build record_path(ctx...) sits inside the try, and a nesting too deep (RecursionError) "
                                  "reads as no stored rows; the parsed document goes on to _rows_of_record, which owns its shape (t-2064 P4b)",
    # --- queued behind another node ---
    # --- queued: found by the census at t-677, not in the finding's list (t-666 F-3, t-670 M1) ---
    "acceptance._manifest_under": QUEUED,
    "brief_pack._load": QUEUED,
    "config_contract.package_version": QUEUED,
    "contract.load_json": QUEUED,
    "controller.Controller._pipeline": QUEUED,
    "cost_capture._read_pending": QUEUED,
    "factory_dashboard.is_archived_task": QUEUED,
    "factory_dashboard.project_config": QUEUED,
    "grammar.load_overrides": QUEUED,
    "inject_context.load_map": QUEUED,
    "judge_sources._read": QUEUED,
    "manual_capture._env_blocked_row": QUEUED,
    "onboard_apply._writer_pid": QUEUED,
    "reachability.load_receipt": QUEUED,
    "report_facts._risk_words": QUEUED,
    "role_cli.registry": QUEUED,
    "runtime_paths._config_of": QUEUED,
    "session_identity.load_rules": QUEUED,
    "source_inventory._prefix_cache": QUEUED,
    "stand_health._read": QUEUED,
    "stand_lease._read": QUEUED,
    "story_step._read_pipeline": QUEUED,
    "test_locations._config_of": QUEUED,
    "ticket_adapter._holds_inventory": QUEUED,
    "window_record._load": QUEUED,
}


def _is_json_read(node) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "json"):
        return False
    if node.func.attr == "load":
        return True
    if node.func.attr != "loads" or not node.args:
        return False
    argument = node.args[0]
    return isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute) and argument.func.attr == "read_text"


def _constant_like(value) -> bool:
    if isinstance(value, (ast.Constant, ast.Name)):
        return True
    return isinstance(value, ast.Dict) and not value.keys or isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts


def _quiet(handler) -> bool:
    return all(isinstance(s, ast.Pass) or isinstance(s, ast.Return) and (s.value is None or _constant_like(s.value))
               for s in handler.body)


def _reader_shaped(function) -> bool:
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) > 2:
        return False
    for statement in body:
        if isinstance(statement, ast.Try) and statement.handlers and len(statement.body) <= 2 \
                and any(_is_json_read(n) for part in statement.body for n in ast.walk(part)) \
                and all(_quiet(h) for h in statement.handlers):
            return True
    return False


def _functions(node, scope):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield ".".join(scope + [child.name]), child
            yield from _functions(child, scope + [child.name])
        else:
            yield from _functions(child, scope + [child.name] if isinstance(child, ast.ClassDef) else scope)


def census(folder: Path) -> tuple:
    """({"module.func": "file:line"} for every reader-shaped function in folder/*.py, the files that did not parse)."""
    found: dict = {}
    unparsed: list = []
    for path in sorted(folder.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, ValueError, OSError):
            unparsed.append(path.name)
            continue
        for name, function in _functions(tree, [path.stem]):
            if name != CARRIER and _reader_shaped(function):
                found[name] = f"{path.name}:{function.lineno}"
    return found, unparsed


def census_verdict(found: dict, kept: dict) -> tuple:
    """(offenders not in KEPT, KEPT rows that no longer match)."""
    return sorted(set(found) - set(kept)), sorted(set(kept) - set(found))


PROBE = '''import json


def read_thing(path):
    """A reader of the shape."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
'''
NEAR_MISSES = '''import json


def three_statements(path):
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return data
    except Exception:
        return {}


def handler_raises(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("unreadable") from exc


def longer_body(path):
    print("reading")
    value = 1
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def not_a_read(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""
'''
LOAD_FORM = '''import json


class Holder:
    def read(self, handle):
        try:
            return json.load(handle)
        except (OSError, ValueError):
            pass
'''


def test_the_census(scripts_dir: Path, scratch: Path) -> None:
    probe = scratch / "census_probe"
    probe.mkdir(parents=True)
    (probe / "census_probe.py").write_text(PROBE, encoding="utf-8")
    (probe / "near_misses.py").write_text(NEAR_MISSES, encoding="utf-8")
    (probe / "load_form.py").write_text(LOAD_FORM, encoding="utf-8")
    (probe / "broken.py").write_text("def (:\n", encoding="utf-8")
    found, unparsed = census(probe)
    check_eq("G5 positive control: the tmp module with the shape is flagged, and so is `json.load(<expr>)` in a method",
             sorted(found), ["census_probe.read_thing", "load_form.Holder.read"])
    check_eq("G5 controls: three statements, a raising handler, a longer body and a read that is no json.loads are not",
             sorted(set(found) & {"near_misses.three_statements", "near_misses.handler_raises",
                                  "near_misses.longer_body", "near_misses.not_a_read"}), [])
    check_eq("G5 a file that does not parse is named, not skipped in silence", unparsed, ["broken.py"])
    check_eq("G5 not in KEPT: both offenders are new", census_verdict(found, {})[0],
             ["census_probe.read_thing", "load_form.Holder.read"])
    kept = {"census_probe.read_thing": "control", "load_form.Holder.read": "control"}
    check_eq("G5 negative control: the same module listed in KEPT is not new, and not stale",
             census_verdict(found, kept), ([], []))
    check_eq("G5 a KEPT row for a function that no longer has the shape is STALE",
             census_verdict(found, dict(kept, **{"near_misses.three_statements": "control"}))[1],
             ["near_misses.three_statements"])
    check_eq("G5 a KEPT row for a function that no longer exists is STALE",
             census_verdict(found, dict(kept, **{"gone_module.gone": "control"}))[1], ["gone_module.gone"])

    real, unparsed = census(scripts_dir)
    new, stale = census_verdict(real, KEPT)
    check_eq("G5 every script parses", unparsed, [])
    check("G5 the census finds the readers it is meant to find (a census that finds nothing proves nothing)",
          len(real) >= 10, f"found {len(real)}")
    check("G5 no reader-shaped function outside KEPT: call hooklib.read_json (kind=dict for an object), or add a KEPT row "
          "with the reason", not new, "NEW: " + "; ".join(f"{n} ({real[n]})" for n in new))
    check("G5 no stale KEPT row: remove the row of a function that was re-pointed or deleted", not stale,
          "STALE: " + ", ".join(stale))
    check("G5 every KEPT row carries a reason or a queue pointer", all(str(v).strip() for v in KEPT.values()))


if __name__ == "__main__":
    root = temp_dir("qa-read-json-")
    try:
        files = make_files(root)
        test_the_reader_itself(files)
        test_the_callers(files)
        test_the_copies_are_gone()
        test_c5_characterisation(files, root / "c5")
        test_the_census(Path(__file__).resolve().parents[1], root / "g5")
    finally:
        cleanup(root)
    finish("read_json")
