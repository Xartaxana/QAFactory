"""The launcher's Python entry: resolve the script, run it in THIS interpreter, as a script.

hooks/run-py.cmd passes its RAW argument tail here (`%*` on Windows, "$@" on POSIX) instead of
rebuilding it. The Windows half used to rebuild the list one argument at a time, and batch splits
an unquoted `--set key=value` into two arguments before any loop runs, drops everything after an
empty argument, and cannot carry a quote; the same launcher put `scripts/` in front of an
ABSOLUTE script path (`...\\hooks\\..\\scripts\\C:\\...`). TP2-2406, defect M7.

    python run_py_entry.py <script> [args...]

Resolution (one rule, one place):
  * an absolute path that EXISTS is used as given. Absolute means `/...`, `\\...`, `X:/...` or
    `X:\\...` on every platform, so a Windows path is not mistaken for a relative name on POSIX
    and a rooted name is never joined under scripts/ (a join would drop the prefix);
  * every other value is `<this directory>/<value>`, subdirectories kept (`tests/x.py`);
  * a bare name is NEVER looked up relative to the current directory: a project file named like a
    hook must not be the one that runs;
  * an absolute path that does not exist exits 2 with `run-py.cmd: script not found: <path as
    given>`; a relative name that does not exist exits 2 with the path it was looked up at.
A missing first argument exits 1 with the launcher's own message.

The target is compiled and exec'd in a fresh module that replaces `sys.modules["__main__"]`
(see run_as_main), with `sys.argv = [script, *rest]` and the script's directory first on
`sys.path`, which is what running the file directly does. No subprocess is added; stdin, stdout
and stderr are the process's own and are not wrapped, but stdout and stderr are reconfigured
to UTF-8 (console_io, B-413; nothing is put into the environment, and a missing console_io.py
is skipped); a SystemExit leaves this module unchanged,
so the interpreter applies its own rules to it (an int is the exit code, None is 0, a string is
printed to stderr with exit 1).

THE MARKER. The cmd half of the launcher starts this process with QA_FACTORY_LAUNCHER=cmd. It is
read once, at import, into `VIA_CMD` and REMOVED from `os.environ` right there, so a child process
the target starts never inherits it. A script that must know whether its arguments crossed the
cmd route (cmd.exe cuts an argument at a newline before the launcher runs, so inline multi-line
text cannot arrive whole) reads it:

    import run_py_entry
    if run_py_entry.VIA_CMD: ...

This works when the script is run through the launcher: the entry registers itself as
`sys.modules["run_py_entry"]`, so the import returns this very module even for a target outside
scripts/. Run directly (`python scripts/x.py`), the import finds this file next to the script and
VIA_CMD is False, unless the variable was set by hand.

THE INTERPRETER CACHE. A call that reached this process by the launcher's search (not by
QA_FACTORY_PYTHON and not by the cached path) arrives with QA_FACTORY_PYCACHE naming
`%LOCALAPPDATA%\\qa-factory\\python-path.txt`; `_remember_interpreter` then writes this
interpreter there, so later calls skip the search. Base interpreters only, silently, atomically.
"""
import os
import sys

PROG = "run-py.cmd"
MARKER = "QA_FACTORY_LAUNCHER"
VIA_CMD = os.environ.pop(MARKER, "") == "cmd"
# The interpreter cache (SC1-5a). The cmd half names the file to fill in QA_FACTORY_PYCACHE only
# on a call that found its interpreter by search; like the marker it is removed here, so a child
# of the target never inherits it and a stale value in a caller's shell is cleared by the launcher.
CACHE_ENV = "QA_FACTORY_PYCACHE"
CACHE_TARGET = os.environ.pop(CACHE_ENV, "")


def is_absolute(value: str) -> bool:
    """`/x`, `\\x`, `C:/x`, `C:\\x` - on any platform. `C:x` (drive-relative) is not absolute."""
    if value[:1] in ("/", "\\"):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in ("/", "\\") and value[0].isascii() \
        and value[0].isalpha()


def resolve(value: str) -> tuple[str, bool]:
    """(path, was_absolute). Plain concatenation, never os.path.join: join drops the left side
    whenever the right side looks rooted, which is exactly the prefix defect this replaces."""
    if is_absolute(value):
        return value, True
    return os.path.dirname(os.path.abspath(__file__)) + os.sep + value, False


def script_dir(script: str) -> str:
    """The directory the interpreter itself would put first on sys.path for this script."""
    resolve_links = os.path.realpath if os.name != "nt" else os.path.abspath
    return os.path.dirname(resolve_links(script))


def run_as_main(script: str) -> None:
    """Execute the file the way `python script.py` does: a fresh module that REPLACES
    sys.modules["__main__"] (a script run directly replaces it too), `__name__ == "__main__"`,
    `__file__` the script path. The module has to be the one registered, not just a dict handed
    to exec: a dataclass looks its module up in sys.modules, and pickle resolves a top-level
    function through `__main__`. The source is compiled from BYTES, so a BOM or a PEP 263 coding
    line is honoured exactly as the interpreter honours it. runpy is not used: runpy.run_path
    imports pkgutil (about 95 ms with its dependencies on the measured machine) on every launch."""
    module = type(sys)("__main__")
    module.__file__ = script
    with open(script, "rb") as handle:
        code = compile(handle.read(), script, "exec", dont_inherit=True)
    sys.modules["__main__"] = module
    exec(code, module.__dict__)


def _remember_interpreter(target: str) -> bool:
    """Write this interpreter's path into the launcher's cache file `target`; True if written.

    The one writer of the cache (AR-14). It writes only when everything holds: the call came
    through the cmd half, the launcher named a file, this is a BASE interpreter (a venv path,
    cached user-wide, would turn every hook of every project off the day the venv's base goes,
    B-4), and the path is an existing ASCII file (the code page `set /p` reads the file in is
    unknown in a hook context, and a wrong reading would search again on every call). The file
    holds the path alone, without a line break, written to `<target>.<pid>.tmp` and moved with
    os.replace, so a reader sees the old file or the new one whole and parallel first calls
    cannot collide. NOTHING is printed (a hook's stdout is a contract, FR-14); any failure,
    a replace refused because another call is reading the file included, is swallowed: a cache
    that was not written is today's behaviour, one more search."""
    exe = sys.executable or ""
    if not (VIA_CMD and target and exe and sys.prefix == sys.base_prefix and exe.isascii()
            and os.path.isfile(exe)):
        return False
    tmp = f"{target}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, "w", encoding="ascii", newline="") as handle:
            handle.write(exe)
        os.replace(tmp, target)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def main(argv: list) -> int:
    if not argv or not argv[0]:
        print(f"{PROG}: missing script name", file=sys.stderr)
        return 1
    script, absolute = resolve(argv[0])
    if not os.path.isfile(script):
        print(f"{PROG}: script not found: {script}", file=sys.stderr)
        here = os.path.dirname(os.path.abspath(__file__))
        if absolute:
            print(f"  expected an existing file; a name that is not an absolute path is looked "
                  f"up under {here}", file=sys.stderr)
        else:
            print(f"  expected a file under {here}; pass an absolute path to run a script "
                  "from somewhere else", file=sys.stderr)
        return 2
    sys.argv = [script, *argv[1:]]
    here = os.path.dirname(os.path.abspath(__file__))
    target_dir = script_dir(script)
    if sys.path and os.path.normcase(sys.path[0]) == os.path.normcase(here):
        sys.path[0] = target_dir
    else:
        sys.path.insert(0, target_dir)
    run_as_main(script)
    return 0


if __name__ == "__main__":
    # The target imports this module by name; as __main__ it would otherwise be imported twice,
    # the second time with a VIA_CMD that has already been consumed.
    sys.modules["run_py_entry"] = sys.modules["__main__"]
    # The target runs in this process, so its streams are set here, once, before it prints
    # (B-413). Guarded: a layout that lost console_io.py must still launch the hook.
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    # After the stream setup, not before it: test_console_encoding pins the setup as the block's
    # first statement after the sys.modules line. Before main, so the cache is written by the
    # interpreter that is about to run the target and never by one that did not start.
    _remember_interpreter(CACHE_TARGET)
    sys.exit(main(sys.argv[1:]))
