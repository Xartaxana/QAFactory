"""Shared worlds and the one scenario runner for the package's slow scenario tests (TD-11 spec D, node D1).

Not a test itself (selftest.py collects only `test_*.py`). A test file that needs a driver or a controller builds its
world ONCE and takes all its checks from it (docs/TESTING.md):

    with scenario_world.world(build, *args, mode="reads" | "mutates" | "fresh", why="", **kwargs) as made:
        ...

`build(*args, **kwargs)` returns a tuple whose first item is the world root (a Path), or an object with `.root`.
`made` is a deep copy of what it returned: a scenario never changes the cached value.

  reads    the shared root itself; on exit its tree state must equal the pristine state, else ONE FAIL line (a
           `harness.check`) names the scenario and the first differing path, and the root is reset. Silent when equal.
  mutates  the shared root, reset IN PLACE on every exit (normal or by exception) from a pristine copy taken after
           the build. A reset that does not end equal to the pristine state marks the world DEAD: one note line, and
           the next entry builds it again. In a pool thread `mutates` behaves as `fresh`.
  fresh    a new build on every entry, deleted on exit; `why` (non-empty) names the meaning.

`in_process=True` (mode `mutates` only) declares that the scenario runs a driver or controller in THIS process: the
world is then shared only when the build declares `build.world_caches` (a callable that clears the path-keyed
process caches, called on every entry). Without it the entry is `fresh` and the downgrade is recorded
(`downgrade_lines`, printed once at the end of `run`). This module names no cache of the package: the data comes
from the builder.

Process state: the `os.environ` diff the build made is re-applied on EVERY entry; a builder's optional
`build.world_enter(made)` is called on every entry.

Nothing is written inside the package: every root and pristine copy lives under the temp directory and is deleted at
the end of `run` and by `atexit`. Imports: the standard library and `harness` only.
"""
import atexit
import contextlib
import copy
import hashlib
import os
import shutil
import sys
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import harness

MODES = ("reads", "mutates", "fresh")
PREFIX = "qa-world-"

_LOCK = threading.RLock()
_WORLDS: dict = {}          # key -> _World
_FRESH: set = set()         # roots of live `fresh` worlds, for atexit
_DOWNGRADES: list = []      # lines for `downgrade_lines`
_HERE = threading.local()   # the scenario the current thread is running (set by `run`)


class _World:
    def __init__(self, root: Path, container: Path, state: dict, made, env_diff: dict):
        self.root = root
        self.container = container
        self.pristine = container / "tree"
        self.state = state
        self.made = made
        self.env_diff = env_diff
        self.dead = False
        self.reset_pending = False      # a guard fired in a pool thread: the reset waits until the pool ends


def world_key(build, args, kwargs) -> tuple:
    """The identity of a world: the build OBJECT itself (functions, partials and lambdas are told apart by identity)
    plus its arguments; the kwargs enter with their VALUES (sorted by name). An unhashable build is a ValueError."""
    try:
        hash(build)
    except TypeError:
        raise ValueError(f"scenario_world: {_label(build, (), {})} is not hashable, so it cannot name a world") from None
    return (build, repr(args), repr(sorted(kwargs.items(), key=lambda item: item[0])))


def _label(build, args, kwargs) -> str:
    text = f"{getattr(build, '__module__', '?')}.{getattr(build, '__qualname__', type(build).__name__)}"
    if args:
        text += repr(args)
    if kwargs:
        text += repr(dict(sorted(kwargs.items(), key=lambda item: item[0])))
    return text


def _is_link(path) -> bool:
    """A symlink or a Windows junction (a junction is not `islink`)."""
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        return bool(isjunction(path))
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & 0x400)          # FILE_ATTRIBUTE_REPARSE_POINT


def _link_text(path) -> str:
    try:
        return "link:" + os.readlink(path)
    except OSError:
        return "link:?"


def _walk_error(error: OSError) -> None:
    raise error                          # a directory that cannot be listed is never read as an empty one


def tree_state(root) -> dict:
    """`{relative posix path: sha256 of bytes | "dir" | "link:<target>"}` over the whole tree. A symlink or junction is
    recorded by its target and never followed; an empty directory is an entry, so one a scenario creates IS a difference;
    a directory that cannot be listed raises."""
    root = Path(root)
    state: dict = {}
    for here, dirs, files in os.walk(root, onerror=_walk_error):
        base = Path(here)
        for name in list(dirs):
            path = base / name
            rel = path.relative_to(root).as_posix()
            if _is_link(path):
                state[rel] = _link_text(path)
                dirs.remove(name)
            else:
                state[rel] = "dir"
        for name in files:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if _is_link(path):
                state[rel] = _link_text(path)
            else:
                state[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def first_difference(left: dict, right: dict) -> str:
    """The first path (sorted) at which two tree states differ; empty when they are equal."""
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            return key
    return ""


def _root_of(made, build) -> Path:
    first = made[0] if isinstance(made, (tuple, list)) and made else getattr(made, "root", None)
    if not isinstance(first, Path):
        raise ValueError(f"scenario_world: {_label(build, (), {})} returned no world root: the first item of a tuple "
                         f"(or the `.root` of an object) must be a Path, got {type(first).__name__}")
    if not first.is_dir():
        raise ValueError(f"scenario_world: {_label(build, (), {})} returned a root that is not a directory: {first}")
    # The module deletes and resets this root, so it must be one the module may delete: strictly under the temp directory,
    # not a symlink or junction. A refused root is never touched.
    temp = os.path.normcase(_temp_root())
    real = os.path.normcase(os.path.realpath(first))
    try:
        inside = real != temp and os.path.commonpath([real, temp]) == temp
    except ValueError:                              # another drive
        inside = False
    if _is_link(first) or not inside:
        raise ValueError(f"scenario_world: {_label(build, (), {})} returned the root {first}, which is not a real directory "
                         f"under the temp directory ({temp}); the module deletes its roots, so it refuses it")
    return first


def _temp_root() -> str:
    return os.path.realpath(tempfile.gettempdir())


def _make(build, args, kwargs) -> _World:
    before = dict(os.environ)
    made = build(*args, **kwargs)
    after = dict(os.environ)
    diff = {key: value for key, value in after.items() if before.get(key) != value}
    diff.update({key: None for key in before if key not in after})
    root = _root_of(made, build)                    # a refused root is never deleted
    container = None
    try:
        container = Path(tempfile.mkdtemp(prefix=PREFIX))
        shutil.copytree(root, container / "tree", symlinks=True)
        return _World(root, container, tree_state(root), made, diff)
    except BaseException:
        harness.cleanup(root)
        if container is not None:
            harness.cleanup(container)
        raise


def _discard(w: _World) -> None:
    harness.cleanup(w.root)
    harness.cleanup(w.container)


def _restore(w: _World) -> None:
    """Reset the root IN PLACE from the pristine copy and re-hash. A mismatch, or ANY exception on the way (delete, copy,
    re-hash), marks the world dead: one note line, nothing is re-raised, and the next entry builds it again."""
    try:
        harness.cleanup(w.root)                  # the cwd goes back out first; read-only files are removed
        w.root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(w.pristine, w.root, symlinks=True, copy_function=shutil.copy, dirs_exist_ok=True)
        state = tree_state(w.root)
        if state == w.state:
            return
        why = f"first difference: {first_difference(state, w.state) or '(root)'}"
    except Exception as error:
        why = f"{type(error).__name__}: {error}"
    w.dead = True
    print(f"note: world {w.root} could not be restored to its pristine state ({why}); its next entry builds it again")


def _guard(w: _World, label: str, scenario: str) -> None:
    with _LOCK:
        try:
            state = tree_state(w.root)
            path = first_difference(state, w.state) or "(root)"
            if state == w.state:
                return
        except Exception as error:                  # an unreadable tree is not a known-equal one
            path = f"{type(error).__name__}: {error}"
        harness.check(f"world {label}: {scenario} left a reads world as it found it", False, f"first differing path: {path}")
        if threading.current_thread() is threading.main_thread():
            _restore(w)
        else:
            w.reset_pending = True                  # another pool thread may still be reading it: reset when the pool ends


def _reset_pending() -> None:
    with _LOCK:
        for w in list(_WORLDS.values()):
            if w.reset_pending:
                w.reset_pending = False
                _restore(w)


def _shared_world(build, args, kwargs) -> _World:
    key = world_key(build, args, kwargs)
    with _LOCK:
        w = _WORLDS.get(key)
        if w is not None and w.dead:
            _discard(w)
            del _WORLDS[key]
            w = None
        if w is None:
            w = _WORLDS[key] = _make(build, args, kwargs)
        return w


def _hand_out(w: _World, build, with_caches: bool):
    for key, value in w.env_diff.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if with_caches:
        build.world_caches()
    made = copy.deepcopy(w.made)
    enter = getattr(build, "world_enter", None)
    if callable(enter):
        enter(made)
    return made


@contextlib.contextmanager
def _fresh_world(build, args, kwargs):
    made = build(*args, **kwargs)
    root = _root_of(made, build)
    _FRESH.add(root)
    try:
        enter = getattr(build, "world_enter", None)
        if callable(enter):
            enter(made)
        yield made
    finally:
        harness.cleanup(root)
        _FRESH.discard(root)


@contextlib.contextmanager
def _open(build, args, kwargs, mode, in_process, scenario):
    label = _label(build, args, kwargs)
    shared = mode != "fresh"
    if mode == "mutates":
        if threading.current_thread() is not threading.main_thread():
            shared = False
        elif in_process and not callable(getattr(build, "world_caches", None)):
            shared = False
            line = f"fresh instead of shared: {label} -- in-process scenario without world_caches"
            with _LOCK:
                if line not in _DOWNGRADES:
                    _DOWNGRADES.append(line)
    if not shared:
        with _fresh_world(build, args, kwargs) as made:
            yield made
        return
    w = _shared_world(build, args, kwargs)
    try:
        made = _hand_out(w, build, in_process and mode == "mutates")
        yield made
    finally:
        if mode == "reads":
            _guard(w, label, scenario)
        else:
            with _LOCK:
                _restore(w)


def world(build, *args, mode, why="", in_process=False, **kwargs):
    """The context manager of the module docstring. `mode` has no default (a missing one is a TypeError); an unknown
    mode, `fresh` without `why`, or a build with no root is a ValueError naming the build."""
    label = _label(build, args, kwargs)
    if mode not in MODES:
        raise ValueError(f"scenario_world: {label}: mode must be one of {MODES}, got {mode!r}")
    if mode == "fresh" and not str(why).strip():
        raise ValueError(f"scenario_world: {label}: mode 'fresh' needs a non-empty `why` (the meaning that needs a fresh world)")
    scenario = getattr(_HERE, "scenario", None) or sys._getframe(1).f_code.co_name
    return _open(build, args, kwargs, mode, bool(in_process), scenario)


def downgrade_lines() -> list:
    """Entries that were `fresh` instead of shared because an in-process scenario had no `world_caches`."""
    with _LOCK:
        return list(_DOWNGRADES)


def owned_paths() -> list:
    """Every directory this module holds now: roots and pristine copies of shared worlds, roots of fresh ones."""
    with _LOCK:
        paths = [str(w.root) for w in _WORLDS.values()] + [str(w.container) for w in _WORLDS.values()]
        return paths + [str(root) for root in _FRESH]


def cleanup_all() -> None:
    with _LOCK:
        for w in list(_WORLDS.values()):
            _discard(w)
        _WORLDS.clear()
        for root in list(_FRESH):
            harness.cleanup(root)
        _FRESH.clear()


atexit.register(cleanup_all)


def select(side_by_side: list, in_process: list, names: list, order: str | None) -> tuple:
    """The two lists after argv selection (a name equal to a scenario's name or a prefix of it, file order) and order
    (`reverse` reverses each list; anything else is file order)."""
    def chosen(scenario) -> bool:
        return not names or any(scenario.__name__.startswith(name) for name in names)
    pool = [s for s in side_by_side if chosen(s)]
    serial = [s for s in in_process if chosen(s)]
    if order == "reverse":
        pool.reverse()
        serial.reverse()
    return pool, serial


ORDERS = ("", "normal", "reverse")


def _contained(scenario, wrap=None) -> str:
    """Run one scenario (through `wrap(scenario)` when given; the name stays the scenario's); the traceback text when it
    raised (a `sys.exit` inside it counts), empty otherwise."""
    _HERE.scenario = scenario.__name__
    try:
        (wrap(scenario) if wrap is not None else scenario)()
        return ""
    except (Exception, SystemExit):
        return traceback.format_exc()
    finally:
        _HERE.scenario = None


def _report(scenario, text: str) -> None:
    harness.check(f"{scenario.__name__} ran to its end", False, text[-1500:])


def _refuse(text: str) -> None:
    """Exit 2 with the text on stderr AND stdout (a caller that redirects stdout must not swallow the reason)."""
    print(text, file=sys.stderr, flush=True)
    print(text)
    sys.exit(2)


def run(side_by_side: list, in_process: list, *, label: str, wrap=None) -> None:
    """Run one file's scenarios: those that only start driver processes side by side, then, once every one of them is
    finished, those that build a Driver in this process, one after another (never together: a Driver changes the working
    directory, and some redirect stdout, which is process-wide - a pool thread's FAIL line printed meanwhile would be
    swallowed, FR-31). A scenario that raises becomes ONE `ran to its end` FAIL line and the next one runs; a pool
    thread's exception is reported from the MAIN thread after the pool ends. Names on argv select scenarios (equal or a
    prefix) - only the argv tokens that do not start with `-` are names, so a file with flags of its own is not refused;
    a name selecting nothing exits 2 and prints every scenario name. `QA_SCENARIO_ORDER`: unset, empty or `normal` = file
    order, `reverse` reverses each list, any other value exits 2. `wrap(scenario)` (optional) returns the callable that is
    actually run, inside the thread. A file with no scenario builds nothing. At the end every world is deleted and the
    downgrades are printed. The run never calls `harness.finish`: the FAIL lines it adds turn the exit code of the file
    only where the file itself ends with `harness.finish`."""
    names = [token for token in sys.argv[1:] if not token.startswith("-")]
    order = os.environ.get("QA_SCENARIO_ORDER")
    if order is not None and order not in ORDERS:
        _refuse(f"{label}: QA_SCENARIO_ORDER={order!r} is not known; accepted: unset, 'normal' (file order), 'reverse'")
    every = [s.__name__ for s in list(side_by_side) + list(in_process)]
    for name in names:
        if not any(known.startswith(name) for known in every):
            _refuse(f"{label}: no scenario matches {name!r}; the scenarios of this file are:\n"
                    + "\n".join(f"  {known}" for known in every))
    pool_list, serial_list = select(list(side_by_side), list(in_process), names, order)
    try:
        if pool_list:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [(s, pool.submit(_contained, s, wrap)) for s in pool_list]
                results = [(s, future.result()) for s, future in futures]
            _reset_pending()
            for scenario, text in results:
                if text:
                    _report(scenario, text)
            harness.guard_cwd("the side-by-side scenarios")
        for scenario in serial_list:
            text = _contained(scenario, wrap)
            if text:
                _report(scenario, text)
            harness.guard_cwd(scenario.__name__)
    finally:
        cleanup_all()
        with _LOCK:
            lines = list(_DOWNGRADES)
            _DOWNGRADES.clear()
        for line in lines:
            print(line)
