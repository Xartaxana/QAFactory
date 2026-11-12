"""The per-scenario clock's hook (TD-11 D0). Python imports a module named `sitecustomize` found on PYTHONPATH at
startup; `scenario_clock.py run` puts this folder there and names a sink folder in QA_SCENARIO_CLOCK_SINK.

Acts ONLY in a process whose sys.argv[0] is a `scripts/tests/test_*.py` file, whose parent is the `scenario_clock.py run`
process (QA_SCENARIO_CLOCK_PARENT) and only while the sink variable is set; anywhere else (a child that inherits
PYTHONPATH, the interpreter of another tool) it does nothing at all. A test started through `run_py_entry.py` or one that
loads harness by path is not seen (no check rows although the `file` row exists): `run` never starts a test that way.
It observes and never changes a return value, an exception or the output of the test:
  - `harness.check*` reporting (the module-level `check` is wrapped, so check_eq / check_in are seen through it);
  - `subprocess.Popen` start and wait (NOT `subprocess.run`: a test may patch `subprocess.run`, and that patch must apply
    and restore untouched);
  - `tempfile.mkdtemp`, through `sys.addaudithook` (a scratch directory: NOT a world build);
  - each call of a function named in QA_SCENARIO_CLOCK_BUILDERS (a `build` row: start, seconds, scope), through
    `sys.monitoring` - the builder seconds are measured, never derived from gaps between other events.
One JSON-lines file per test file: `<sink>/<test file stem>.jsonl`; events `file`, `check`, `child`, `tempdir`, `build`, and
`clock_error` when the clock itself failed (the test still runs on). Seconds are `time.monotonic()`.
A sitecustomize that already exists later on sys.path is imported after ours, as the driver golden's does; when the
golden's hook loads this one first, this one does not chain back (no recursion in either order).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SINK_VAR = "QA_SCENARIO_CLOCK_SINK"
_PARENT_VAR = "QA_SCENARIO_CLOCK_PARENT"      # the pid of `scenario_clock.py run`: the only parent whose child is recorded
_BUILDERS_VAR = "QA_SCENARIO_CLOCK_BUILDERS"  # comma-separated builder function names (data of `run --builders`)
_IN_PROCESS = "_qa_scenario_clock_installed"


def _is_test_process() -> bool:
    try:
        argv0 = os.path.abspath(sys.argv[0])
    except Exception:
        return False
    parts = argv0.replace("\\", "/").split("/")
    name = parts[-1]
    return (len(parts) >= 3 and name.startswith("test_") and name.endswith(".py")
            and parts[-2] == "tests" and parts[-3] == "scripts")


def _install() -> None:
    import atexit
    import importlib.abc
    import importlib.machinery
    import json
    import subprocess
    import threading
    import time

    argv0 = os.path.abspath(sys.argv[0])
    tests_dir = os.path.normcase(os.path.dirname(argv0))
    stem = os.path.basename(argv0)[:-3]
    sink_dir = os.environ[_SINK_VAR]
    os.makedirs(sink_dir, exist_ok=True)
    handle = open(os.path.join(sink_dir, stem + ".jsonl"), "a", encoding="utf-8", buffering=1)
    lock = threading.Lock()
    monotonic = time.monotonic
    start = monotonic()
    state = {"exit": 0, "seen": False}      # "seen": the exit code came from harness.finish or the excepthook
    name_cache = {}

    def write(row):
        line = json.dumps(row, ensure_ascii=True)
        with lock:
            handle.write(line + "\n")
            handle.flush()

    def safe_write(row):
        try:
            write(row)
        except Exception as exc:                  # the clock never fails the test
            try:
                write({"event": "clock_error", "error": "%s: %s" % (type(exc).__name__, exc)})
            except Exception:
                pass

    def in_tests(filename):
        hit = name_cache.get(filename)
        if hit is None:
            try:
                folder = os.path.normcase(os.path.dirname(os.path.abspath(filename)))
            except Exception:
                folder = ""
            base = os.path.basename(filename)
            hit = name_cache[filename] = (folder == tests_dir and base not in ("harness.py", "scenario_clock.py"))
        return hit

    def scope():
        names = []
        frame = sys._getframe(2)
        while frame is not None:
            code = frame.f_code
            if in_tests(code.co_filename):
                name = code.co_name
                if not name.startswith("<") or name == "<module>":
                    names.append(name)
            frame = frame.f_back
        names.reverse()
        return names

    def script_of(args):
        if isinstance(args, (str, bytes, os.PathLike)):
            items = os.fsdecode(args).split()
        else:
            items = [os.fsdecode(a) for a in args]
        if not items:
            return ""
        for item in items:
            base = os.path.basename(item.replace("\\", "/"))
            if base.endswith(".py"):
                return base
        base = os.path.basename(items[0].replace("\\", "/"))
        return base[:-4] if base.lower().endswith(".exe") else base

    # --- harness.check* and harness.finish -----------------------------------------------------------------
    def wrap_harness(module):
        real_check = module.check
        real_finish = module.finish

        def check(*args, **kwargs):
            result = real_check(*args, **kwargs)
            try:
                name = args[0] if args else kwargs.get("name", "")
                ok = args[1] if len(args) > 1 else kwargs.get("ok", False)
                safe_write({"event": "check", "t": monotonic(), "name": str(name), "ok": bool(ok), "scope": scope()})
            except Exception as exc:
                safe_write({"event": "clock_error", "error": "check: %s: %s" % (type(exc).__name__, exc)})
            return result

        def finish(*args, **kwargs):
            try:
                return real_finish(*args, **kwargs)
            except SystemExit as exc:
                code = exc.code
                state["seen"] = True
                state["exit"] = 0 if code is None else (code if isinstance(code, int) else 1)
                raise

        check.__wrapped__ = real_check
        finish.__wrapped__ = real_finish
        module.check = check
        module.finish = finish

    class _HarnessFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "harness":
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or spec.loader is None or not spec.origin:
                return None
            if os.path.normcase(os.path.dirname(os.path.abspath(spec.origin))) != tests_dir:
                return None
            sys.meta_path[:] = [f for f in sys.meta_path if f is not self]
            loader = spec.loader
            real_exec = loader.exec_module

            def exec_module(module):
                real_exec(module)
                try:
                    wrap_harness(module)
                except Exception as exc:
                    safe_write({"event": "clock_error", "error": "harness: %s: %s" % (type(exc).__name__, exc)})

            loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _HarnessFinder())

    # --- subprocess.Popen start and wait ---------------------------------------------------------------------
    popen = subprocess.Popen
    real_init, real_wait, real_poll = popen.__init__, popen.wait, popen.poll

    def child_done(proc):
        mark = proc.__dict__.pop("_qa_clock", None)
        if mark is not None:
            safe_write({"event": "child", "t": mark[0], "seconds": monotonic() - mark[0], "script": mark[1],
                        "scope": mark[2]})

    def init(self, *args, **kwargs):
        t0 = monotonic()
        real_init(self, *args, **kwargs)
        try:
            given = args[0] if args else kwargs.get("args", "")
            self.__dict__["_qa_clock"] = (t0, script_of(given), scope())
        except Exception as exc:
            safe_write({"event": "clock_error", "error": "child: %s: %s" % (type(exc).__name__, exc)})

    def wait(self, *args, **kwargs):
        result = real_wait(self, *args, **kwargs)
        child_done(self)
        return result

    def poll(self):
        result = real_poll(self)
        if result is not None:
            child_done(self)
        return result

    popen.__init__, popen.wait, popen.poll = init, wait, poll

    # --- tempfile.mkdtemp ------------------------------------------------------------------------------------
    def audit(event, args):
        if event == "tempfile.mkdtemp":
            try:
                safe_write({"event": "tempdir", "t": monotonic(), "name": os.path.basename(str(args[0])),
                            "scope": scope()})
            except Exception:
                pass

    sys.addaudithook(audit)

    # --- builders: each call timed DIRECTLY (enter and exit), through sys.monitoring (Python 3.12+) -----------------
    # Cost: one callback per distinct code object (it answers DISABLE, so that location never fires again) and, for a
    # function whose name is a builder, two callbacks per call plus one scope walk. No behaviour changes: the callbacks
    # never raise, and return values and exceptions pass through untouched. A generator builder is not timed.
    def install_builders(names):
        mon = getattr(sys, "monitoring", None)
        if mon is None:
            safe_write({"event": "clock_error", "error": "builders: sys.monitoring needs Python 3.12, builder seconds "
                                                          "are not measured"})
            return
        tool = 3
        try:
            mon.use_tool_id(tool, "qa-scenario-clock")
        except Exception as exc:
            safe_write({"event": "clock_error", "error": "builders: %s: %s" % (type(exc).__name__, exc)})
            return
        events = mon.events
        local = threading.local()
        wanted = {}

        def is_builder(code):
            # keyed by id (hashing a code object walks its whole body); the entry keeps the code alive, so the id is stable
            hit = wanted.get(id(code))
            if hit is None:
                hit = wanted[id(code)] = (code, code.co_name in names and in_tests(code.co_filename))
            return hit[1]

        def on_start(code, offset):
            if not is_builder(code):
                return mon.DISABLE
            try:
                stack = local.__dict__.setdefault("stack", [])
                stack.append((code, monotonic(), scope(), bool(stack)))
            except Exception as exc:
                safe_write({"event": "clock_error", "error": "build: %s: %s" % (type(exc).__name__, exc)})
            return None

        def done(code):
            try:
                end = monotonic()
                stack = local.__dict__.get("stack") or []
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index][0] is code:
                        _, t0, scope_at, nested = stack.pop(index)
                        safe_write({"event": "build", "t": t0, "seconds": end - t0, "name": code.co_name,
                                    "scope": scope_at, "nested": nested})
                        return
            except Exception as exc:
                safe_write({"event": "clock_error", "error": "build: %s: %s" % (type(exc).__name__, exc)})

        def on_return(code, offset, retval):
            if not is_builder(code):
                return mon.DISABLE
            done(code)
            return None

        def on_unwind(code, offset, exception):
            if is_builder(code):
                done(code)
            return None

        for event, function in ((events.PY_START, on_start), (events.PY_RETURN, on_return),
                                (events.PY_UNWIND, on_unwind)):
            mon.register_callback(tool, event, function)
        mon.set_events(tool, events.PY_START | events.PY_RETURN | events.PY_UNWIND)

    builder_names = {n.strip() for n in os.environ.get(_BUILDERS_VAR, "").split(",") if n.strip()}
    if builder_names:
        install_builders(builder_names)

    # --- the end: the `file` row, and an uncaught exception counts as exit 1 ---------------------------------
    previous_hook = sys.excepthook

    def excepthook(kind, value, tb):
        state["exit"] = 1
        state["seen"] = True
        previous_hook(kind, value, tb)

    sys.excepthook = excepthook

    def at_end():
        try:
            write({"event": "file", "file": os.path.basename(argv0), "start": start, "end": monotonic(),
                   "exit": state["exit"], "exit_seen": state["seen"], "python": sys.version.split()[0],
                   "sha": os.environ.get("QA_SCENARIO_CLOCK_SHA", "unknown")})
        except Exception:
            pass

    atexit.register(at_end)


def _is_direct_child() -> bool:
    """True only in the process `scenario_clock.py run` itself started: a test file that launches another
    scripts/tests/test_*.py as a child (with any environment) is not recorded a second time."""
    return os.environ.get(_PARENT_VAR) == str(os.getppid())


if (os.environ.get(_SINK_VAR) and not getattr(sys, _IN_PROCESS, False) and _is_test_process()
        and _is_direct_child()):
    try:
        setattr(sys, _IN_PROCESS, True)     # in THIS process: a second execution of this file (a chain) installs nothing
        _install()
    except Exception as _exc:               # a clock that did not load says so if it can, and the test runs on
        try:
            with open(os.path.join(os.environ[_SINK_VAR], "clock-error.txt"), "a", encoding="utf-8") as _h:
                _h.write("%s: %s\n" % (type(_exc).__name__, _exc))
        except Exception:
            pass

# The chain to the next sitecustomize. `sitecustomize_shadowed` already in sys.modules means another hook (the driver
# golden's) is loading US from ITS chain loop: it loads the next one itself, so this file stops here, and the pair
# works in either PYTHONPATH order (each file runs at most twice and the second run only returns).
if "sitecustomize_shadowed" not in sys.modules:
    for _entry in sys.path:
        _candidate = os.path.join(_entry or ".", "sitecustomize.py")
        if os.path.isfile(_candidate) and os.path.abspath(os.path.dirname(_candidate)) != _HERE:
            import importlib.util as _util
            _spec = _util.spec_from_file_location("sitecustomize_shadowed", _candidate)
            _module = _util.module_from_spec(_spec)
            sys.modules["sitecustomize_shadowed"] = _module
            _spec.loader.exec_module(_module)
            break
