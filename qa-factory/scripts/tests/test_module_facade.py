"""module_facade.py -- the forwarding facade a cut script keeps its old meaning through.

ONE table of rows, each row named in its PASS/FAIL lines. The rows build their own tiny part modules
and facades in a temp directory (no real package script is imported but module_facade and
run_py_entry), so a red line names the facade behaviour that broke:

    python -B scripts/tests/test_module_facade.py
    python -B -m pytest scripts/tests/test_module_facade.py -q -p no:cacheprovider

The three failure classes of a naive facade (plan critic X1) are the rows `patch_part_only_name` (a part
that is patched and then loses its function), `builtin_open_through_the_facade` (a builtin a part only
reads), and `facade_own_main_from_import` (a free name of the facade's own code)."""
import importlib
import importlib.machinery
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
from harness import check, finish  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import module_facade  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="qa-factory-facade-"))
sys.path.insert(0, str(TMP))
_made: list = []


def write(prefix: str, key: str, source: str) -> str:
    """Write module `<prefix>_<key>` into the temp directory; `%p%` in the source is the prefix."""
    name = f"{prefix}_{key}"
    (TMP / f"{name}.py").write_text(source.replace("%p%", prefix + "_"), encoding="utf-8")
    return name


def load(prefix: str, key: str):
    name = f"{prefix}_{key}"
    _made.append(name)
    importlib.invalidate_caches()      # a file written a moment ago is invisible to a cached directory listing
    return importlib.import_module(name)


def world(prefix: str, a: str, b: str | None = None, facade_body: str = "", parts: str | None = None,
          install: bool = True):
    """Part a, optional part b (may `from %p%a import ...`), a facade over them. Returns (facade, a, b)."""
    write(prefix, "a", a)
    if b is not None:
        write(prefix, "b", b)
    listed = parts if parts is not None else ("%p%a, %p%b" if b is not None else "%p%a")
    imports = "import %p%a\n" + ("import %p%b\n" if b is not None else "")
    tail = "import module_facade\n" + (f"module_facade.install(__name__, [{listed}])\n" if install else "")
    write(prefix, "facade", f'"""facade of {prefix}"""\n{imports}{facade_body}\n{tail}')
    facade = load(prefix, "facade")
    return facade, sys.modules[f"{prefix}_a"], sys.modules.get(f"{prefix}_b")


PART_A = (
    "X = 1\n"
    "CACHE = None\n"
    "def helper():\n    return 'real'\n"
    "def get():\n    return X\n"
    "def use():\n    return helper()\n"
    "def fill():\n    global CACHE\n    CACHE = 'v'\n"
    "def reader(path):\n    with open(path) as handle:\n        return handle.read()\n"
    "__all__ = ['X']\n"
)
PART_B = "from %p%a import X, helper\ndef getb():\n    return X\ndef useb():\n    return helper()\n"


class FakeFile:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return "FAKE"


# --- the rows ------------------------------------------------------------------------------------------

def row_live_read(ck):
    f, a, _ = world("lr", PART_A)
    ck("a part global reads through the facade", f.X == 1 and f.get() == 1)
    a.X = 4
    ck("documented limit: a direct write into a part bypasses the facade, the mirrored copy is stale", f.X == 1)


def row_read_after_global_rebind(ck):
    f, a, _ = world("rg", PART_A)
    ck("before the rebind", f.CACHE is None)
    f.fill()
    ck("after the part rebinds through `global`", f.CACHE == "v")


def row_unknown_name(ck):
    f, _, _ = world("un", PART_A)
    try:
        f.nowhere
        ck("unknown name raises", False)
    except AttributeError as err:
        ck("unknown name: AttributeError with the facade's name", "un_facade" in str(err) and "nowhere" in str(err),
           str(err))
    ck("hasattr is False", not hasattr(f, "nowhere"))
    ck("a part's __all__ is not forwarded", not hasattr(f, "__all__"))


def row_chained_getattr(ck):
    body = ("def __getattr__(name):\n    if name == 'LATE':\n        return 7\n"
            "    raise AttributeError('chained: ' + name)\n")
    f, _, _ = world("cg", PART_A, facade_body=body)
    ck("the pre-existing __getattr__ answers a name no part binds", f.LATE == 7)
    ck("the parts answer first", f.X == 1)
    try:
        f.nowhere
        ck("an unknown name still raises through the chain", False)
    except AttributeError as err:
        ck("an unknown name still raises through the chain", "chained: nowhere" in str(err), str(err))


def row_assign_seen_by_defining_part(ck):
    f, a, _ = world("as", PART_A)
    f.X = 5
    ck("the defining part's own function sees the assignment", f.get() == 5 and a.get() == 5)
    ck("the facade's mirror of the name holds the new value", vars(f)["X"] == 5)


def row_assign_seen_by_second_part(ck):
    f, a, b = world("sb", PART_A, PART_B)
    f.X = 9
    ck("the part that did `from a import X` sees it", b.getb() == 9)
    ck("the first part sees it too", a.get() == 9)


def row_patch_part_only_name(ck):
    f, a, b = world("pp", PART_A, PART_B)
    original = a.helper
    with mock.patch.object(f, "helper", lambda: "fake"):
        ck("inside the block the part's own call is patched", f.use() == "fake")
        ck("inside the block the second part's call is patched", b.useb() == "fake")
    ck("after the block the part's function works again", f.use() == "real" and b.useb() == "real")
    ck("after the block every part has its ORIGINAL object", a.helper is original and b.helper is original)
    ck("the facade's mirror is back to the original too", vars(f)["helper"] is original)


def row_patch_twice_in_a_row(ck):
    f, a, b = world("p2", PART_A, PART_B)
    original = a.helper
    for turn in ("first", "second"):
        with mock.patch.object(f, "helper", lambda: turn):
            ck(f"{turn} patch is seen", f.use() == turn and b.useb() == turn)
        ck(f"{turn} patch is undone", f.use() == "real" and a.helper is original and b.helper is original)
    with mock.patch.object(f, "helper", lambda: "outer"):
        with mock.patch.object(f, "helper", lambda: "inner"):
            ck("nested: inner seen", f.use() == "inner")
        ck("nested: outer back after the inner block", f.use() == "outer")
    ck("nested: original back after both", f.use() == "real" and b.useb() == "real")


def row_patch_create_on_absent_name(ck):
    f, a, b = world("pc", PART_A, PART_B)
    with mock.patch.object(f, "ghost", 1, create=True):
        ck("inside the block the name reads", f.ghost == 1)
    ck("no trace: not readable", not hasattr(f, "ghost"))
    ck("no trace: in no dict", all("ghost" not in vars(m) for m in (f, a, b)))
    ck("no trace: not in dir", "ghost" not in dir(f))


def row_builtin_open_through_the_facade(ck):
    f, a, _ = world("bo", PART_A)
    sample = TMP / "bo_sample.txt"
    sample.write_text("REAL", encoding="utf-8")
    f.open = lambda *args, **kwargs: FakeFile()
    ck("a bare open( inside a part calls the fake", f.reader(str(sample)) == "FAKE")
    del f.open
    ck("del restores the builtin for the part", f.reader(str(sample)) == "REAL" and "open" not in vars(a))
    with mock.patch.object(f, "open", lambda *args, **kwargs: FakeFile(), create=True):
        ck("patch.object(create=True) on the builtin is seen", f.reader(str(sample)) == "FAKE")
    ck("patch.object(create=True) leaves the builtin and no binding", f.reader(str(sample)) == "REAL"
       and "open" not in vars(a) and "open" not in vars(f))


def row_facade_own_main_from_import(ck):
    body = "from %p%a import X\ndef main():\n    return X\n"
    f, a, _ = world("fm", PART_A, facade_body=body)
    ck("the facade's own main reads the from-imported name", f.main() == 1)
    f.X = 3
    ck("a write reaches the facade's own binding", f.main() == 3)
    ck("a write reaches the part", f.get() == 3 and a.X == 3)
    with mock.patch.object(f, "X", 8):
        ck("patch.object on a facade-bound name: seen by main and by the part", f.main() == 8 and f.get() == 8)
    ck("patch.object on a facade-bound name: undone everywhere", f.main() == 3 and f.get() == 3)


def _entry_world():
    write("en", "a", "X = 1\ndef get():\n    return X\n")
    path = TMP / "en_facade.py"
    path.write_text(
        '"""entry facade"""\n'
        f"import sys\nsys.path.insert(0, {str(SCRIPTS)!r})\nsys.path.insert(0, {str(TMP)!r})\n"
        "import en_a\nfrom en_a import X\nimport module_facade\n"
        "module_facade.install(__name__, [en_a])\n"
        "def main():\n    print('facade-ok', X, sys.modules[__name__].get(), __name__)\n"
        "if __name__ == '__main__':\n    main()\n", encoding="utf-8")
    return path


def row_facade_run_as_main(ck):
    path = _entry_world()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for label, argv in (("directly", [sys.executable, "-B", str(path)]),
                        ("through run_py_entry.py", [sys.executable, "-B", str(SCRIPTS / "run_py_entry.py"), str(path)])):
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        ck(f"as __main__ {label}: exit 0", p.returncode == 0, p.stderr[-400:])
        ck(f"as __main__ {label}: prints the expected line", p.stdout.strip() == "facade-ok 1 1 __main__", p.stdout)


def row_from_import_is_a_copy(ck):
    f, _, _ = world("fc", PART_A)
    write("fc", "single", "X = 1\n")
    single = load("fc", "single")
    got_facade, got_single = {}, {}
    exec("from fc_facade import X", got_facade)
    exec("from fc_single import X", got_single)
    f.X = 99
    single.X = 99
    ck("a single module: the earlier `from` copy is not reached", got_single["X"] == 1)
    ck("the facade: the same", got_facade["X"] == 1)
    ck("a fresh read through the facade is current", f.X == 99)


def row_dir_contents(ck):
    f, a, b = world("dr", PART_A, PART_B)
    names = dir(f)
    expected = {k for m in (f, a, b) for k in vars(m) if k != "__all__"}
    ck("dir has no duplicates and is sorted", names == sorted(set(names)))
    ck("dir is the facade's names plus every part's", set(names) == expected)
    ck("dir holds a part-only name", "getb" in names and "reader" in names)


def row_install_twice_refused(ck):
    f, a, _ = world("it", PART_A)
    try:
        module_facade.install("it_facade", [a])
        ck("a second install is refused", False)
    except ValueError as err:
        ck("a second install is refused, naming the facade", "it_facade" in str(err), str(err))
    ck("the first install still works", f.X == 1)


def row_bad_part_refused(ck):
    f, a, _ = world("bp", PART_A, install=False)
    cls_before = type(f)
    cases = [("a name that is not imported", ["bp_never_imported"], "bp_never_imported"),
             ("the facade itself", [a, f], "bp_facade"),
             ("the facade itself by name", ["bp_facade"], "bp_facade"),
             ("a non-module object", [object()], "not an imported module"),
             ("a part given twice", [a, a], "twice")]
    for label, parts, needle in cases:
        try:
            module_facade.install("bp_facade", parts)
            ck(f"refused: {label}", False)
        except ValueError as err:
            ck(f"refused: {label}", needle in str(err), str(err))
    try:
        module_facade.install("bp_missing_module", [a])
        ck("refused: an unimported facade name", False)
    except ValueError as err:
        ck("refused: an unimported facade name", "bp_missing_module" in str(err), str(err))
    ck("a refused install leaves the module untouched", type(f) is cls_before)
    module_facade.install("bp_facade", ["bp_a"])
    ck("parts may be given by module name", f.X == 1)


def row_module_identity_kept(ck):
    f, a, _ = world("mi", PART_A, install=False)
    before = (f.__name__, f.__file__, f.__doc__, f.__spec__, dict(vars(f)))
    module_facade.install("mi_facade", [a])
    ck("the module object is the one in sys.modules", sys.modules["mi_facade"] is f)
    ck("__name__, __file__, __doc__, __spec__ are untouched",
       (f.__name__, f.__file__, f.__doc__, f.__spec__) == before[:4])
    ck("the facade's own bindings are untouched, the parts' names are mirrored in",
       all(vars(f).get(k) is v for k, v in before[4].items()) and vars(f)["get"] is a.get)


LOG_A = "LOG = 'a-log'\ndef la():\n    return LOG\n"
LOG_B = "LOG = 'b-log'\ndef lb():\n    return LOG\n"
READER_B = "def peekb():\n    return helper\ndef attr_only(o):\n    return o.CACHE\n"


def row_two_parts_different_objects(ck):
    f, a, b = world("td", LOG_A, LOG_B)
    with mock.patch.object(f, "LOG", "fake"):
        ck("both parts see the patch", f.la() == "fake" and f.lb() == "fake")
    ck("each part has ITS OWN original back", a.LOG == "a-log" and b.LOG == "b-log")
    ck("the facade's mirror is the first part's original", vars(f)["LOG"] == "a-log")


def row_read_only_part_gets_no_binding(ck):
    f, a, b = world("ro", PART_A, READER_B)
    original = a.helper
    with mock.patch.object(f, "helper", lambda: "fake"):
        ck("inside the block the part that only reads the name sees the patch", b.peekb()() == "fake")
    ck("after the block that part has no binding", "helper" not in vars(b))
    ck("after the block the owner has its original", a.helper is original and vars(f)["helper"] is original)
    f.CACHE = "plain"
    ck("a plain write gives no binding to a part that mentions the name only as an attribute",
       "CACHE" not in vars(b) and a.CACHE == "plain")


def row_global_cache_read_live_with_earlier_part(ck):
    f, a, b = world("gc", PART_A, "def peek(o):\n    return o.CACHE\n", parts="%p%b, %p%a")
    f.CACHE = None
    f.fill()
    ck("the cache the owner refilled through `global` is read live", f.CACHE == "v")
    ck("the part ordered first holds no copy", "CACHE" not in vars(b))
    ck("a global-rebound name is not mirrored", "CACHE" not in vars(f))
    with mock.patch.object(f, "CACHE", "patched"):
        ck("a patch of the forwarded name is seen", f.CACHE == "patched")
    ck("the forwarded name is back after the patch", a.CACHE == "v" and f.CACHE == "v")


def row_create_true_on_existing_name(ck):
    f, a, b = world("ce", PART_A, PART_B)
    original = a.helper
    with mock.patch.object(f, "helper", lambda: "fake", create=True):
        ck("inside the block both parts see the patch", f.use() == "fake" and b.useb() == "fake")
    ck("after the block the name is NOT lost", f.use() == "real" and b.useb() == "real")
    ck("after the block every part has its original", a.helper is original and b.helper is original)


def row_builtin_named_part_binding(ck):
    f, a, _ = world("bn", "def format(x):\n    return 'part-format'\ndef fmt():\n    return format(1)\n")
    original = a.format
    with mock.patch.object(f, "format", lambda x: "fake"):
        ck("inside the block the part's own call is patched", f.fmt() == "fake")
    ck("after the block the part's binding is back", a.format is original and f.fmt() == "part-format")


def row_reader_thread_during_patch(ck):
    f, a, b = world("rt", PART_A, PART_B)
    stop = threading.Event()
    errors: list = []

    def reader():
        while not stop.is_set():
            try:
                f.X, f.helper, b.useb()
            except (AttributeError, NameError) as err:
                errors.append(repr(err))
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    for turn in range(2000):
        with mock.patch.object(f, "helper", lambda: "fake"):
            pass
        with mock.patch.object(f, "X", turn):
            pass
    stop.set()
    thread.join(10)
    ck("a reader never sees a name absent while patches enter and exit", not errors, errors[:1])
    ck("the names are back", f.use() == "real" and f.X == 1)


def row_refused_global_rebound_copy(ck):
    for key, facade_body, part_b in (("fa", "from %p%a import CACHE\n", None),
                                     ("pb", "", "from %p%a import CACHE\n")):
        f, a, b = world(key, PART_A, part_b, facade_body=facade_body, install=False)
        before = dict(vars(f))
        listed = [a] if b is None else [a, b]
        try:
            module_facade.install(f"{key}_facade", listed)
            ck(f"refused: a copy in the {'facade' if b is None else 'second part'}", False)
        except ValueError as err:
            needle = f"{key}_facade" if b is None else f"{key}_b"
            ck(f"refused: a copy in the {'facade' if b is None else 'second part'}, naming the name and both places",
               "CACHE" in str(err) and f"{key}_a" in str(err) and needle in str(err), str(err))
        ck("a refused install leaves a plain module with its dict unchanged",
           type(f) is types.ModuleType and dict(vars(f)) == before)


def row_builtin_patch_reaches_facade_code(ck):
    body = "def size(x):\n    return len(x)\n"
    f, _, b = world("fb", "X = 1\n", "def sizeb(x):\n    return len(x)\n", facade_body=body)
    ck("control: both real", f.size([1, 2]) == 2 and b.sizeb([1, 2]) == 2)
    with mock.patch.object(f, "len", lambda x: "fake", create=True):
        ck("a patch reaches the facade's own code and the part that also reads it",
           f.size([1]) == "fake" and b.sizeb([1]) == "fake")
    ck("after the patch both are real and no binding is left",
       f.size([1, 2]) == 2 and b.sizeb([1, 2]) == 2 and "len" not in vars(f) and "len" not in vars(b))
    f.len = lambda x: "set"
    ck("an assignment reaches both", f.size([1]) == "set" and b.sizeb([1]) == "set")
    del f.len
    ck("the delete undoes both", f.size([1, 2]) == 2 and "len" not in vars(f) and "len" not in vars(b))


def row_del_then_restore_two_objects(ck):
    f, a, b = world("dd", LOG_A, LOG_B)
    saved = getattr(f, "LOG")                 # the monkeypatch.delattr shape: read, delete, ..., set it back
    delattr(f, "LOG")
    ck("deleted from every place", not hasattr(f, "LOG") and "LOG" not in vars(a) and "LOG" not in vars(b))
    setattr(f, "LOG", saved)
    ck("each part has ITS OWN object back", a.LOG == "a-log" and b.LOG == "b-log" and vars(f)["LOG"] == "a-log")
    try:
        del f.nowhere
        ck("a delete of a name bound nowhere raises", False)
    except AttributeError:
        ck("a delete of a name bound nowhere raises", True)


def row_reentrant_write(ck):
    f, _, _ = world("rw", PART_A)
    box = {"facade": f}

    class Noisy:
        def __del__(self):
            box["facade"].later = 1

    f.slot = Noisy()
    thread = threading.Thread(target=lambda: setattr(f, "slot", 2), daemon=True)
    thread.start()
    thread.join(5)
    ck("a write whose replaced value writes through the facade finishes", not thread.is_alive())
    ck("both writes landed", f.slot == 2 and f.later == 1)


def row_empty_parts(ck):
    f, _, _ = world("ep", PART_A, install=False)
    module_facade.install("ep_facade", [])
    ck("no parts: the facade still reads and writes its own names", f.ep_a is sys.modules["ep_a"])
    f.own = 1
    ck("no parts: a new name lands in the facade", f.own == 1 and not hasattr(f, "nowhere"))


LIVE_PART = (
    "import functools\n"
    "DATA = 1\n"
    "def deco(fn):\n    @functools.wraps(fn)\n    def wrapper(*a):\n        return fn(*a)\n    return wrapper\n"
    "@deco\ndef decorated():\n    return deco_only_name\n"
    "def outer():\n    def inner():\n        return nested_name\n    return [x for x in range(3) if comp_name]\n"
    "class K:\n    attr = 1\n"
    "    @classmethod\n    def cm(cls):\n        return cm_name\n"
    "    @staticmethod\n    def sm():\n        return sm_name\n"
    "    @property\n    def prop(self):\n        return prop_name\n"
    "    def meth(self):\n        global rebound_name\n        rebound_name = 1\n        return meth_name\n"
    "PARTIAL = functools.partial(decorated)\n"
    "TABLE = {'k': lambda: table_name}\n"
)


dis_scan = module_facade._scan_dis        # the one copy of the reference: the module's own fallback


def state_of(facade):
    return type(facade).__module_facade_state__


def row_recorded_set_equals_loader_set(ck):
    """The recorded set built from the code the import already made equals the one from the loader's module code,
    but for what only the module-level code reads while it runs (class-body decorators, dunders)."""
    f, a, _ = world("rs", LIVE_PART)
    loader_code = compile((TMP / "rs_a.py").read_text(encoding="utf-8"), "rs_a.py", "exec")
    access, _ = dis_scan(loader_code)
    old = (set(vars(a)) | access) - module_facade._MACHINERY
    new = set(state_of(f).recorded[0])
    import_time_only = {"__module__", "__qualname__", "classmethod", "staticmethod", "property"}
    ck("every loader-code name is recorded but the import-time-only ones", old - new <= import_time_only, sorted(old - new))
    ck("nothing is recorded that the loader code does not show", not (new - old), sorted(new - old))
    ck("names read only inside a nested function, a comprehension, a classmethod, a staticmethod, a property, "
       "a decorated function, a lambda in a container are recorded",
       {"nested_name", "comp_name", "cm_name", "sm_name", "prop_name", "meth_name", "deco_only_name",
        "table_name"} <= new, sorted(new))
    ck("a `global` store inside a method is seen: the name is recorded", "rebound_name" in new)
    ck("no part is left unreachable", state_of(f).skipped == {"rs_a": []}, state_of(f).skipped)
    with mock.patch.object(f, "table_name", 5, create=True):
        ck("a patch of a name only a lambda in a table reads is written into that part", vars(a).get("table_name") == 5)
    ck("and leaves no trace after", "table_name" not in vars(a) and not hasattr(f, "table_name"))


def row_no_second_compile(ck):
    """The loader is not asked for the part's code at install."""
    asked: list = []
    original = importlib.machinery.SourceFileLoader.get_code

    def counting(self, name):
        asked.append(name)
        return original(self, name)

    with mock.patch.object(importlib.machinery.SourceFileLoader, "get_code", counting):
        write("nc", "a", "X = 1\ndef get():\n    return X\n")
        write("nc", "g", PART_A)
        write("nc", "facade", "import nc_a\nimport module_facade\nmodule_facade.install(__name__, [nc_a])\n")
        f = load("nc", "facade")
        load("nc", "g")
        loaded = list(asked)
        ck("the import itself asked the loader (control: the counter works)", "nc_a" in loaded and "nc_facade" in loaded)
        asked.clear()
        sys.modules["nc_again"] = types.ModuleType("nc_again")
        module_facade.install("nc_again", [sys.modules["nc_a"]])
        ck("install of a part with no `global` line asks the loader for nothing", asked == [], asked)
        sys.modules["nc_again2"] = types.ModuleType("nc_again2")
        module_facade.install("nc_again2", [sys.modules["nc_g"]])
        ck("a part with a `global` line is read through the loader, that part only", asked == ["nc_g"], asked)
    ck("the facade works", f.X == 1 and f.get() == 1)
    sys.modules.pop("nc_again", None)
    sys.modules.pop("nc_again2", None)


def row_constants_only_part(ck):
    f, a, _ = world("co", "X = 1\nNAME = 'x'\n")
    ck("a part with no functions: the recorded set is its dict keys",
       state_of(f).recorded[0] == frozenset(set(vars(a)) - module_facade._MACHINERY), sorted(state_of(f).recorded[0]))
    f.X = 2
    ck("a write reaches it and reads back", a.X == 2 and f.X == 2 and f.NAME == "x")
    ck("nothing is skipped", state_of(f).skipped == {"co_a": []})


def row_callable_object_skipped(ck):
    source = ("class C:\n    def __call__(self):\n        return call_name\n"
              "obj = C()\ndef f():\n    return f_name\n")
    f, a, _ = world("sk", source)
    ck("the callable object is listed, the function is not", state_of(f).skipped == {"sk_a": ["obj"]}, state_of(f).skipped)
    ck("the class method of that object is still reached through its class", "call_name" in state_of(f).recorded[0])
    ck("the function's names are recorded", "f_name" in state_of(f).recorded[0])


def row_scan_equals_dis(ck):
    long_source = "\n".join(f"v{i} = g{i}" for i in range(300)) + "\ndef big():\n" + "\n".join(
        f"    global s{i}\n    s{i} = g{i}" for i in range(300)) + "\n    del s0\n    return [o.attr for o in ()]\n"
    for label, code in (("a code with 300 globals (EXTENDED_ARG)", compile(long_source, "long.py", "exec")),
                        ("the fixture part", compile(LIVE_PART, "live.py", "exec")),
                        ("module_facade itself", compile(Path(module_facade.__file__).read_text(encoding="utf-8"),
                                                          "module_facade.py", "exec")),
                        ("this test file", compile(Path(__file__).read_text(encoding="utf-8"), "t.py", "exec"))):
        got, expected = module_facade._scan_fast(code), dis_scan(code)     # the raw road itself, not masked by a fallback
        ck(f"the fast scan equals dis on {label}: accesses", got[0] == expected[0], sorted(got[0] ^ expected[0])[:5])
        ck(f"the fast scan equals dis on {label}: rebinds", got[1] == expected[1], sorted(got[1] ^ expected[1])[:5])
        ck(f"_scan equals dis on {label}", module_facade._scan(code) == expected)
    ck("a name only used as an attribute is not recorded", "attr" not in module_facade._scan(
        compile(long_source, "long.py", "exec"))[0])


def row_fast_scan_active(ck):
    """Red on the day a Python breaks the raw road: the process would silently run the slow `dis` road."""
    module_facade._scan(compile("x = y\n", "t.py", "exec"))
    ck("on this Python the fast scan is active", module_facade._fast_ok is True, module_facade._fast_ok)
    ck("the probe itself agrees", module_facade._fast_agrees())
    with mock.patch.object(module_facade, "_scan_fast", lambda code: 1 / 0), \
            mock.patch.object(module_facade, "_fast_ok", None):
        code = compile("a = b\n", "t.py", "exec")
        got = module_facade._scan(code)
        ck("a failing fast road turns the process to dis", module_facade._fast_ok is False and got == dis_scan(code))


def row_loose_global_refused(ck):
    """The shape the live walk cannot reach: a function held only as an attribute of a module-level instance."""
    part = ("CACHE = None\nclass Reg:\n    pass\ninst = Reg()\n"
            "def _f():\n    global CACHE\n    CACHE = 1\ninst.fn = _f\ndel _f\n")
    f, a, b = world("lg", part, "from %p%a import CACHE\n", install=False)
    ck("control: the walk alone does not reach the function", "_f" not in vars(a)
       and not any(c.co_name == "_f" for c in module_facade._live_codes(a)[0]))
    try:
        module_facade.install("lg_facade", [a, b])
        ck("refused: a `global` rebinding in code the dict does not reach", False)
    except ValueError as err:
        ck("refused: a `global` rebinding in code the dict does not reach, naming the name",
           "CACHE" in str(err) and "lg_a" in str(err), str(err))


def row_global_in_method_refused(ck):
    """The M2 refusal reaches a `global` rebinding inside a method and inside a nested function."""
    part = "CACHE = None\nclass K:\n    def fill(self):\n        def deep():\n            global CACHE\n            CACHE = 1\n        deep()\n"
    for key, facade_body, other in (("gm", "from %p%a import CACHE\n", None), ("gn", "", "from %p%a import CACHE\n")):
        f, a, b = world(key, part, other, facade_body=facade_body, install=False)
        try:
            module_facade.install(f"{key}_facade", [a] if b is None else [a, b])
            ck(f"refused ({key})", False)
        except ValueError as err:
            ck(f"refused ({key}): the copy is named", "CACHE" in str(err), str(err))


ROWS = [
    ("recorded set equals the loader-code set", row_recorded_set_equals_loader_set),
    ("install compiles nothing a second time", row_no_second_compile),
    ("a part of constants only", row_constants_only_part),
    ("a callable object is skipped, not an error", row_callable_object_skipped),
    ("the fast scan equals dis", row_scan_equals_dis),
    ("fast scan is active", row_fast_scan_active),
    ("global in unreachable code is refused", row_loose_global_refused),
    ("global in a method or nested function is refused", row_global_in_method_refused),
    ("live read of a part global", row_live_read),
    ("read after a part rebinds through global", row_read_after_global_rebind),
    ("unknown name", row_unknown_name),
    ("chained pre-existing __getattr__", row_chained_getattr),
    ("assign seen by the defining part", row_assign_seen_by_defining_part),
    ("assign seen by a second part (from-import)", row_assign_seen_by_second_part),
    ("patch_part_only_name", row_patch_part_only_name),
    ("patch twice in a row", row_patch_twice_in_a_row),
    ("patch create=True on an absent name", row_patch_create_on_absent_name),
    ("builtin_open_through_the_facade", row_builtin_open_through_the_facade),
    ("facade_own_main_from_import", row_facade_own_main_from_import),
    ("facade run as __main__", row_facade_run_as_main),
    ("from facade import x is a copy", row_from_import_is_a_copy),
    ("dir contents", row_dir_contents),
    ("install twice refused", row_install_twice_refused),
    ("bad part refused", row_bad_part_refused),
    ("module identity kept", row_module_identity_kept),
    ("two parts, different objects, restored per place", row_two_parts_different_objects),
    ("a part that only reads a name gets no binding", row_read_only_part_gets_no_binding),
    ("global cache read live, earlier part mentions it", row_global_cache_read_live_with_earlier_part),
    ("create=True on an existing part name", row_create_true_on_existing_name),
    ("builtin-named part binding patched", row_builtin_named_part_binding),
    ("reader thread during patch enter/exit", row_reader_thread_during_patch),
    ("global-rebound copy refused at install", row_refused_global_rebound_copy),
    ("builtin patch reaches facade code", row_builtin_patch_reaches_facade_code),
    ("del then restore of two objects", row_del_then_restore_two_objects),
    ("re-entrant write finishes", row_reentrant_write),
    ("empty parts", row_empty_parts),
]


def run_table() -> None:
    for name, row in ROWS:
        def ck(label, ok, detail=""):
            return check(f"{name}: {label}", ok, str(detail))
        try:
            row(ck)
        except Exception:
            check(f"{name}: row raised", False, traceback.format_exc()[-600:])


def cleanup_all() -> None:
    for name in _made:
        sys.modules.pop(name, None)
    sys.modules.pop("en_a", None)
    harness.cleanup(TMP)


def test_module_facade_table():
    run_table()
    try:
        failed = [name for ok, name in harness.RESULTS if not ok]
        assert not failed, failed
    finally:
        cleanup_all()


def main() -> None:
    try:
        run_table()
    finally:
        cleanup_all()
    finish("test_module_facade")


if __name__ == "__main__":
    main()
