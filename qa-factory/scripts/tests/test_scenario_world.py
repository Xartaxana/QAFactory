"""scenario_world (TD-11 spec D, node D1): ONE table of rows, one per behaviour of the shared-world module.

Each row returns None when it holds and a text when it does not; the table loop reports every row by name. The builders here
make a small temp directory with a few files (no `seed`, no child process), so the file runs in seconds. Nothing asserts time.
"""
import contextlib
import io
import os
import shutil
import stat
import sys
import tempfile
import threading
from pathlib import Path

import harness
import scenario_world as SW

BUILT: list = []            # (tag, root) of every build the table's builders made


def tiny(tag, extra=""):
    root = Path(tempfile.mkdtemp(prefix="qa-world-t-"))
    (root / "a.txt").write_text("alpha" + extra, encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("beta", encoding="utf-8")
    BUILT.append((tag, root))
    return root, {"tag": tag}


def builds(tag) -> int:
    return sum(1 for built, _ in BUILT if built == tag)


class Boxed:
    def __init__(self, root):
        self.root = root


def boxed(tag):
    root, _ = tiny(tag)
    return Boxed(root)


def no_root(tag):
    return ("not a path", tag)


def no_root_object(tag):
    return object()


def env_build(tag):
    os.environ["QA_WORLD_T_ENV"] = tag
    return tiny(tag)


ENTERED: list = []


def entered_build(tag):
    return tiny(tag)


entered_build.world_enter = lambda made: ENTERED.append(made[0])

CLEARED: list = []


def cached_build(tag):
    return tiny(tag)


cached_build.world_caches = lambda: CLEARED.append(1)


def quiet(fn):
    """(result, printed text, results the harness tallied); the tallied lines are dropped so the file's own tally stays green."""
    before = len(harness.RESULTS)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn()
    added = list(harness.RESULTS[before:])
    del harness.RESULTS[before:]
    return result, out.getvalue(), added


@contextlib.contextmanager
def argv(*names):
    saved = sys.argv
    sys.argv = ["scenario", *names]
    try:
        yield
    finally:
        sys.argv = saved


@contextlib.contextmanager
def order(value):
    saved = os.environ.get("QA_SCENARIO_ORDER")
    if value is None:
        os.environ.pop("QA_SCENARIO_ORDER", None)
    else:
        os.environ["QA_SCENARIO_ORDER"] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("QA_SCENARIO_ORDER", None)
        else:
            os.environ["QA_SCENARIO_ORDER"] = saved


def state_of(build, *args, **kwargs):
    return SW._WORLDS[SW.world_key(build, args, kwargs)]


def raised(exception, call):
    try:
        call()
    except exception as error:
        return error
    return None


# ---------------------------------------------------------------- rows

def row_reads_shared_and_guard_silent():
    def go():
        with SW.world(tiny, "r1", mode="reads") as one:
            (one[0] / "a.txt").read_text(encoding="utf-8")
        with SW.world(tiny, "r1", mode="reads") as two:
            pass
        return one[0], two[0]
    (first, second), out, added = quiet(go)
    if builds("r1") != 1 or first != second:
        return f"expected one build and one root, got {builds('r1')} builds, roots {first} / {second}"
    return f"the guard printed on a healthy reads world: {out!r}" if out or added else None


def row_reads_that_writes_fails_and_resets():
    def scenario_writes():
        with SW.world(tiny, "r2", mode="reads") as made:
            (made[0] / "w.txt").write_text("intruder", encoding="utf-8")
        with SW.world(tiny, "r2", mode="reads") as again:
            return (again[0] / "w.txt").exists()
    survived, out, added = quiet(scenario_writes)
    if len(added) != 1 or added[0][0] is not False:
        return f"expected ONE failing tally line, got {added}"
    if "scenario_writes" not in out or "w.txt" not in out or not out.startswith("FAIL"):
        return f"the FAIL line does not name the scenario and the first differing path: {out!r}"
    return "the intruder file survived the reset" if survived else None


def row_mutates_reset_to_pristine():
    with SW.world(tiny, "m1", mode="mutates") as made:
        root = made[0]
        (root / "a.txt").write_text("changed", encoding="utf-8")
        (root / "sub" / "b.txt").unlink()
        (root / "new").mkdir()
        (root / "sub" / "c.txt").write_text("c", encoding="utf-8")
    world = state_of(tiny, "m1")
    if SW.tree_state(root) != world.state:
        return f"the root differs from the pristine state at {SW.first_difference(SW.tree_state(root), world.state)}"
    with SW.world(tiny, "m1", mode="mutates") as again:
        if again[0] != root or builds("m1") != 1:
            return "the second entry did not reuse the same root"
    return None


def row_mutates_reset_after_exception():
    def go():
        with SW.world(tiny, "m2", mode="mutates") as made:
            (made[0] / "a.txt").write_text("half done", encoding="utf-8")
            raise KeyError("scenario failed")
    error = raised(KeyError, go)
    world = state_of(tiny, "m2")
    if error is None:
        return "the scenario's exception did not propagate out of the world"
    return None if SW.tree_state(world.root) == world.state else "the root was not reset after the exception"


def row_mutates_removes_read_only_file_and_new_empty_dir():
    with SW.world(tiny, "m3", mode="mutates") as made:
        locked = made[0] / "sub" / "locked.txt"
        locked.write_text("x", encoding="utf-8")
        os.chmod(locked, stat.S_IREAD)
        (made[0] / "empty").mkdir()
        before = SW.tree_state(made[0])
        if "empty" not in before:
            return "an empty directory is not in the tree state"
    world = state_of(tiny, "m3")
    return None if SW.tree_state(world.root) == world.state else "a read-only file or an empty directory survived the reset"


def row_fresh_requires_why():
    error = raised(ValueError, lambda: SW.world(tiny, "f1", mode="fresh", why="  "))
    if error is None or "tiny" not in str(error):
        return f"fresh with an empty why must be a ValueError naming the build, got {error!r}"
    with SW.world(tiny, "f1", mode="fresh", why="first-run check") as one:
        root = one[0]
    with SW.world(tiny, "f1", mode="fresh", why="first-run check") as two:
        other = two[0]
    if root == other or builds("f1") != 2:
        return "fresh must build anew on every entry"
    return "a fresh root was not deleted on exit" if root.exists() or other.exists() else None


def row_missing_mode_is_type_error():
    return None if raised(TypeError, lambda: SW.world(tiny, "t1")) else "a missing mode must be a TypeError"


def row_unknown_mode_is_value_error():
    error = raised(ValueError, lambda: SW.world(tiny, "t2", mode="shared"))
    return None if error is not None and "tiny" in str(error) else f"an unknown mode must be a ValueError naming the build, got {error!r}"


def row_build_without_root_is_value_error():
    for build in (no_root, no_root_object):
        def go(build=build):
            with SW.world(build, "n1", mode="reads"):
                pass
        error = raised(ValueError, go)
        if error is None or build.__name__ not in str(error):
            return f"{build.__name__}: expected a ValueError naming the build, got {error!r}"
    with SW.world(boxed, "n2", mode="reads") as made:      # control: an object with `.root` is a world
        if not isinstance(made, Boxed) or not made.root.is_dir():
            return "an object with `.root` was refused"
    return None


def row_pool_thread_mutates_is_fresh_and_reads_shared():
    seen = {}

    def in_thread():
        with SW.world(tiny, "p1", mode="mutates") as made:
            seen["mutates"] = made[0]
        with SW.world(tiny, "p1", mode="reads") as made:
            seen["reads"] = made[0]
    with SW.world(tiny, "p1", mode="mutates") as main_made:
        shared = main_made[0]
    thread = threading.Thread(target=in_thread)
    thread.start()
    thread.join()
    if seen.get("mutates") in (None, shared):
        return f"mutates in a pool thread must be a fresh root, got {seen.get('mutates')} (shared {shared})"
    if seen["mutates"].exists():
        return "the pool thread's fresh root was not deleted"
    return None if seen["reads"] == shared else "reads in a pool thread must use the shared root"


def row_in_process_mutates_without_world_caches_is_fresh_and_recorded():
    with SW.world(tiny, "i1", mode="mutates", in_process=True) as one:
        first = one[0]
    with SW.world(tiny, "i1", mode="mutates", in_process=True) as two:
        second = two[0]
    if first == second or builds("i1") != 2:
        return "an in-process mutates world without world_caches must be built anew on every entry"
    lines = [line for line in SW.downgrade_lines() if "tiny('i1',)" in line]
    want = "fresh instead of shared:"
    if len(lines) != 1 or want not in lines[0] or "in-process scenario without world_caches" not in lines[0]:
        return f"expected ONE recorded downgrade line, got {lines}"
    SW._DOWNGRADES.clear()          # this row owns the record it made
    return None


def row_in_process_mutates_with_world_caches_is_shared_and_called():
    CLEARED.clear()
    with SW.world(cached_build, "i2", mode="mutates", in_process=True) as one:
        first = one[0]
    with SW.world(cached_build, "i2", mode="mutates", in_process=True) as two:
        second = two[0]
    if first != second or builds("i2") != 1:
        return "a declared-caches world must be shared"
    if len(CLEARED) != 2:
        return f"world_caches must be called on every entry, was called {len(CLEARED)} times"
    return "a declared-caches world was recorded as a downgrade" if any("cached_build" in line for line in SW.downgrade_lines()) else None


def row_env_diff_is_re_applied_on_every_entry():
    try:
        with SW.world(env_build, "e1", mode="reads"):
            pass
        os.environ.pop("QA_WORLD_T_ENV", None)
        with SW.world(env_build, "e1", mode="reads"):
            got = os.environ.get("QA_WORLD_T_ENV")
    finally:
        os.environ.pop("QA_WORLD_T_ENV", None)
    return None if got == "e1" and builds("e1") == 1 else f"the env diff was not re-applied on the second entry (got {got!r})"


def row_world_enter_is_called_on_every_entry():
    ENTERED.clear()
    for _ in range(3):
        with SW.world(entered_build, "w1", mode="mutates"):
            pass
    with SW.world(entered_build, "w2", mode="fresh", why="entered on a fresh world too"):
        pass
    return None if len(ENTERED) == 4 and builds("w1") == 1 else f"expected 4 world_enter calls and one build, got {len(ENTERED)} calls"


def row_made_is_a_deep_copy():
    with SW.world(tiny, "c1", mode="reads") as one:
        one[1]["tag"] = "changed by the scenario"
    with SW.world(tiny, "c1", mode="reads") as two:
        return None if two[1]["tag"] == "c1" else f"the scenario changed the cached tuple: {two[1]}"


def row_dead_world_after_a_failed_rehash_builds_fresh():
    def go():
        with SW.world(tiny, "d1", mode="mutates") as made:
            first = made[0]
            (state_of(tiny, "d1").pristine / "a.txt").write_text("the pristine copy was tampered with", encoding="utf-8")
        return first
    first, out, _added = quiet(go)
    if not out.startswith("note:") or str(first) not in out:
        return f"expected ONE note line naming the world, got {out!r}"
    if not state_of(tiny, "d1").dead:
        return "a failed re-hash must mark the world dead"
    with SW.world(tiny, "d1", mode="mutates") as again:
        second = again[0]
    if builds("d1") != 2 or second == first or first.exists():
        return f"the dead world must be discarded and built again (builds {builds('d1')})"
    return None if not state_of(tiny, "d1").dead else "the rebuilt world is still marked dead"


def row_kwargs_values_make_distinct_keys():
    return None if SW.world_key(tiny, ("k",), {"extra": "1"}) != SW.world_key(tiny, ("k",), {"extra": "2"}) else "two kwargs values share a key"


def make_link(link, target) -> bool:
    """A directory symlink, or on Windows (no privilege needed) a junction; False when neither can be made."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return True
    except (ImportError, AttributeError, OSError):
        return False


def drop_link(link) -> None:
    for remove in (os.rmdir, os.unlink):
        try:
            remove(link)
            return
        except OSError:
            continue


def row_symlink_is_recorded_and_not_followed():
    root = Path(tempfile.mkdtemp(prefix="qa-world-t-"))
    outside = Path(tempfile.mkdtemp(prefix="qa-world-t-"))
    try:
        (outside / "big.txt").write_text("x", encoding="utf-8")
        if not make_link(root / "link", outside):
            print("note: this machine can make neither a symlink nor a junction; the link row checked nothing")
            return None
        state = SW.tree_state(root)
        if state != {"link": "link:" + os.readlink(root / "link")}:
            return f"a symlink or junction must be one `link:<target>` entry, never followed: {state}"
    finally:
        drop_link(root / "link")
        harness.cleanup(root)
        harness.cleanup(outside)
    return None


def make_lambda(tag):
    return lambda: tiny(tag)


def row_two_builds_never_share_a_world():
    import functools
    with SW.world(functools.partial(tiny, "k1"), mode="reads") as one:
        first = one[0]
    with SW.world(functools.partial(tiny, "k2"), mode="reads") as two:
        second = two[0]
    if first == second or builds("k1") != 1 or builds("k2") != 1:
        return f"two partials shared a world: roots {first} / {second}, builds {builds('k1')}, {builds('k2')}"
    lam_a, lam_b = make_lambda("k3"), make_lambda("k4")
    with SW.world(lam_a, mode="reads") as one:
        first = one[0]
    with SW.world(lam_b, mode="reads") as two:
        second = two[0]
    with SW.world(lam_a, mode="reads") as again:
        third = again[0]
    if first == second or builds("k3") != 1 or builds("k4") != 1:
        return f"two lambdas of one function shared a world: roots {first} / {second}"
    if third != first:
        return "the same build object with equal arguments must be the same world"
    with SW.world(tiny, "k5", mode="reads") as plain:
        plain_root = plain[0]
    with SW.world(functools.partial(tiny, "k5"), mode="reads") as partial_made:
        if partial_made[0] == plain_root:
            return "a partial and the plain function it wraps shared a world"

    class Unhashable:
        __hash__ = None

        def __call__(self):
            return tiny("k6")
    error = raised(ValueError, lambda: SW.world_key(Unhashable(), (), {}))
    return None if error is not None and "Unhashable" in str(error) else f"an unhashable build must be a ValueError naming it, got {error!r}"


def row_a_reset_that_raises_marks_the_world_dead():
    real = shutil.copytree

    def refuse(*_args, **_kwargs):
        raise OSError("the disk said no")

    def go():
        try:
            with SW.world(tiny, "x1", mode="mutates"):
                shutil.copytree = refuse
                raise KeyError("the scenario's own failure")
        finally:
            shutil.copytree = real
    error, out, _added = quiet(lambda: raised(KeyError, go))
    if error is None:
        return "the scenario's own exception was lost (or the reset's exception replaced it)"
    if not out.startswith("note:") or "the disk said no" not in out:
        return f"expected ONE note line carrying the exception text, got {out!r}"
    world = state_of(tiny, "x1")
    if not world.dead:
        return "a reset that raised must mark the world dead"
    first = world.root
    with SW.world(tiny, "x1", mode="mutates") as again:
        second = again[0]
    if builds("x1") != 2 or second == first or first.exists():
        return f"the next entry must get a fresh build and the dead root must be gone (builds {builds('x1')})"
    return None if (second / "a.txt").read_text(encoding="utf-8") == "alpha" else "the fresh world is not pristine"


def row_a_root_outside_temp_is_refused_and_untouched():
    fake_temp = Path(tempfile.mkdtemp(prefix="qa-world-t-"))
    real = SW._temp_root
    held = SW.owned_paths()
    try:
        SW._temp_root = lambda: os.path.realpath(fake_temp)
        for mode, extra in (("reads", {}), ("mutates", {}), ("fresh", {"why": "outside row"})):
            tag = "o-" + mode
            error = raised(ValueError, lambda: SW.world(tiny, tag, mode=mode, **extra).__enter__())
            if error is None or "tiny" not in str(error) or str(BUILT[-1][1]) not in str(error):
                return f"{mode}: expected a ValueError naming the build and the root, got {error!r}"
            if not BUILT[-1][1].exists():
                return f"{mode}: the refused root was deleted"
        if SW.owned_paths() != held:
            return f"a refused root is held by the module: {set(SW.owned_paths()) - set(held)}"
    finally:
        SW._temp_root = real
        harness.cleanup(fake_temp)
        for tag, root in BUILT:
            if tag.startswith("o-"):
                harness.cleanup(root)
    return None


def row_a_link_root_is_refused():
    target = Path(tempfile.mkdtemp(prefix="qa-world-t-"))
    link = Path(tempfile.mkdtemp(prefix="qa-world-t-"))
    harness.cleanup(link)
    try:
        if not make_link(link, target):
            print("note: this machine can make neither a symlink nor a junction; the link-root row checked nothing")
            return None
        (target / "keep.txt").write_text("x", encoding="utf-8")
        error = raised(ValueError, lambda: SW.world(lambda: (link,), mode="reads").__enter__())
        if error is None or str(link) not in str(error):
            return f"a root that is a link must be refused naming the root, got {error!r}"
        return None if (target / "keep.txt").exists() else "the target of the refused link root was deleted"
    finally:
        drop_link(link)
        harness.cleanup(target)


def scenario_alpha_one():
    LOG.append("alpha_one")


def scenario_alpha_two():
    LOG.append("alpha_two")


def scenario_beta():
    LOG.append("beta")


def scenario_raises():
    raise RuntimeError("boom " + "x" * 3000)


LOG: list = []


def row_zero_scenarios_builds_nothing():
    count = len(BUILT)
    with argv():
        SW.run([], [], label="empty file")
    if len(BUILT) != count:
        return "a run of no scenario built a world"
    return None


def row_argv_prefix_selects_in_file_order():
    LOG.clear()
    with argv("scenario_al"), order(None):
        SW.run([], [scenario_alpha_one, scenario_alpha_two, scenario_beta], label="prefix")
    if LOG != ["alpha_one", "alpha_two"]:
        return f"a prefix must select the matching scenarios in file order, ran {LOG}"
    LOG.clear()
    with argv("scenario_beta", "scenario_alpha_two"), order(None):
        SW.run([], [scenario_alpha_one, scenario_alpha_two, scenario_beta], label="exact")
    return None if LOG == ["alpha_two", "beta"] else f"two names must select in FILE order, ran {LOG}"


def row_argv_no_match_exits_2_naming_scenarios():
    LOG.clear()

    def go():
        with argv("scenario_alpha_one", "nothing_like_it"):
            try:
                SW.run([scenario_alpha_one], [scenario_beta], label="nomatch")
            except SystemExit as stop:
                return stop.code
        return None
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code, out, _added = quiet(go)
    if code != 2:
        return f"a name selecting nothing must exit 2, got {code!r}"
    for stream, text in (("stdout", out), ("stderr", err.getvalue())):
        if "scenario_alpha_one" not in text or "scenario_beta" not in text or "nothing_like_it" not in text:
            return f"the refusal must print the name and every scenario name on {stream}, printed {text!r}"
    return f"a scenario ran before the refusal: {LOG}" if LOG else None


def row_argv_flags_are_not_names():
    LOG.clear()
    with argv("--fixtures"), order(None):
        SW.run([], [scenario_alpha_one, scenario_beta], label="flag only")
    if LOG != ["alpha_one", "beta"]:
        return f"a flag of the file's own must not select or refuse anything, ran {LOG}"
    LOG.clear()
    with argv("--capture", "scenario_beta"), order(None):
        SW.run([], [scenario_alpha_one, scenario_beta], label="flag and name")
    return None if LOG == ["beta"] else f"the name next to a flag must still select, ran {LOG}"


def row_wrap_is_applied_in_the_run_and_keeps_the_scenario_name():
    LOG.clear()

    def scenario_writer():
        with SW.world(tiny, "wr1", mode="reads") as made:
            (made[0] / "w.txt").write_text("intruder", encoding="utf-8")

    def tagged(scenario):
        def inner():
            LOG.append("wrapped:" + scenario.__name__)
            return scenario()
        return inner
    with argv(), order(None):
        _none, out, _added = quiet(lambda: SW.run([scenario_alpha_one], [scenario_beta, scenario_writer], label="wrap", wrap=tagged))
    if sorted(LOG) != sorted(["wrapped:scenario_alpha_one", "alpha_one", "wrapped:scenario_beta", "beta", "wrapped:scenario_writer"]):
        return f"wrap must be applied to every scenario, pool and main, ran {LOG}"
    if "scenario_writer" not in out or "inner" in out:
        return f"the guard's FAIL line must carry the scenario's own name, printed {out!r}"
    LOG.clear()
    with argv(), order(None):
        SW.run([], [scenario_beta], label="no wrap")
    return None if LOG == ["beta"] else f"with no wrap the scenario must run as it is, ran {LOG}"


def row_unknown_order_is_refused_and_normal_is_accepted():
    for value in ("revers", "REVERSE", " reverse"):
        LOG.clear()

        def go(value=value):
            with argv(), order(value):
                try:
                    SW.run([], [scenario_alpha_one], label="order")
                except SystemExit as stop:
                    return stop.code
            return None
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out, _added = quiet(go)
        if code != 2 or LOG:
            return f"QA_SCENARIO_ORDER={value!r} must exit 2 before any scenario runs, got {code!r}, ran {LOG}"
        if "reverse" not in err.getvalue() or "normal" not in err.getvalue() or "reverse" not in out:
            return f"the refusal must name the accepted values on stderr and stdout, got {err.getvalue()!r} / {out!r}"
    for value in ("normal", ""):
        LOG.clear()
        with argv(), order(value):
            SW.run([], [scenario_alpha_one, scenario_beta], label="normal")
        if LOG != ["alpha_one", "beta"]:
            return f"QA_SCENARIO_ORDER={value!r} must keep file order, ran {LOG}"
    return None


def scenario_exits():
    sys.exit(0)


def row_a_sys_exit_in_a_scenario_is_contained():
    LOG.clear()
    seen = []
    real = harness.check
    harness.check = lambda name, ok, detail="": seen.append((name, ok))
    try:
        with argv(), order(None):
            SW.run([], [scenario_exits, scenario_beta], label="exit")
    finally:
        harness.check = real
    if ("scenario_exits ran to its end", False) not in seen:
        return f"a sys.exit inside a scenario must be one FAIL line, got {seen}"
    return None if LOG == ["beta"] else f"the scenario after a sys.exit did not run: {LOG}"


def row_reverse_order_reverses_each_list():
    LOG.clear()
    with argv(), order("reverse"):
        SW.run([], [scenario_alpha_one, scenario_alpha_two, scenario_beta], label="reverse")
    if LOG != ["beta", "alpha_two", "alpha_one"]:
        return f"QA_SCENARIO_ORDER=reverse must reverse the in-process list, ran {LOG}"
    pool, serial = SW.select([scenario_alpha_one, scenario_alpha_two], [scenario_beta, scenario_alpha_one], [], "reverse")
    if pool != [scenario_alpha_two, scenario_alpha_one] or serial != [scenario_alpha_one, scenario_beta]:
        return "reverse must reverse the side-by-side list too"
    pool, _serial = SW.select([scenario_alpha_one, scenario_alpha_two], [], [], None)
    return None if pool == [scenario_alpha_one, scenario_alpha_two] else "unset order must keep file order"


def row_a_raising_scenario_is_contained_and_the_next_runs():
    LOG.clear()
    seen = []
    real = harness.check
    harness.check = lambda name, ok, detail="": seen.append((name, ok, detail, threading.current_thread() is threading.main_thread()))
    try:
        with argv(), order(None):
            SW.run([scenario_raises, scenario_alpha_one], [scenario_raises, scenario_beta], label="raising")
    finally:
        harness.check = real
    lines = [item for item in seen if item[0] == "scenario_raises ran to its end" and item[1] is False]
    if len(lines) != 2:
        return f"expected one FAIL line per raising scenario (pool and main), got {seen}"
    if any(len(item[2]) != 1500 or not item[2].endswith("x" * 100 + "\n") for item in lines):
        return f"the detail must be the last 1500 characters of the traceback, got lengths {[len(item[2]) for item in lines]}"
    if not all(item[3] for item in lines):
        return "a pool thread's exception must be reported from the main thread"
    return None if sorted(LOG) == ["alpha_one", "beta"] else f"the scenarios after a raising one did not run: {LOG}"


def row_cleanup_at_end_leaves_no_world_directory():
    held = []

    def scenario_reads():
        with SW.world(tiny, "z1", mode="reads"):
            held.extend(SW.owned_paths())

    def scenario_mutates():
        with SW.world(tiny, "z2", mode="mutates"):
            held.extend(SW.owned_paths())

    def scenario_fresh():
        with SW.world(tiny, "z3", mode="fresh", why="cleanup row"):
            held.extend(SW.owned_paths())
    with argv(), order(None):
        SW.run([scenario_reads], [scenario_mutates, scenario_fresh], label="cleanup")
    names = sorted({path for path in held})
    if len(names) < 5:
        return f"the scenarios held fewer directories than expected: {names}"
    left = [path for path in names if Path(path).exists()]
    if left or SW._WORLDS or SW.owned_paths():
        return f"directories left after the run: {left}, worlds {len(SW._WORLDS)}"
    leftover = [root for tag, root in BUILT if tag in ("z1", "z2", "z3") and root.exists()]
    return f"build roots left: {leftover}" if leftover else None


ROWS = [
    ("reads shared and guard silent", row_reads_shared_and_guard_silent),
    ("reads that writes: guard FAIL line and reset", row_reads_that_writes_fails_and_resets),
    ("mutates reset to pristine", row_mutates_reset_to_pristine),
    ("mutates reset after an exception", row_mutates_reset_after_exception),
    ("mutates removes a read-only file and a new empty directory", row_mutates_removes_read_only_file_and_new_empty_dir),
    ("fresh requires why", row_fresh_requires_why),
    ("missing mode is a TypeError", row_missing_mode_is_type_error),
    ("unknown mode is a ValueError", row_unknown_mode_is_value_error),
    ("build without root is a ValueError", row_build_without_root_is_value_error),
    ("pool thread: mutates is fresh, reads shared", row_pool_thread_mutates_is_fresh_and_reads_shared),
    ("in_process mutates without world_caches is fresh and recorded", row_in_process_mutates_without_world_caches_is_fresh_and_recorded),
    ("in_process mutates with world_caches is shared and called", row_in_process_mutates_with_world_caches_is_shared_and_called),
    ("env diff re-applied on every entry", row_env_diff_is_re_applied_on_every_entry),
    ("world_enter called on every entry", row_world_enter_is_called_on_every_entry),
    ("made is a deep copy", row_made_is_a_deep_copy),
    ("dead world after a failed re-hash builds fresh", row_dead_world_after_a_failed_rehash_builds_fresh),
    ("kwargs values make distinct keys", row_kwargs_values_make_distinct_keys),
    ("symlink or junction recorded and not followed", row_symlink_is_recorded_and_not_followed),
    ("two builds never share a world (partials, lambdas, unhashable)", row_two_builds_never_share_a_world),
    ("a reset that raises marks the world dead", row_a_reset_that_raises_marks_the_world_dead),
    ("a root outside the temp directory is refused and untouched", row_a_root_outside_temp_is_refused_and_untouched),
    ("a link root is refused", row_a_link_root_is_refused),
    ("zero scenarios builds nothing", row_zero_scenarios_builds_nothing),
    ("argv prefix selects in file order", row_argv_prefix_selects_in_file_order),
    ("argv no-match exits 2 naming scenarios", row_argv_no_match_exits_2_naming_scenarios),
    ("argv flags are not names", row_argv_flags_are_not_names),
    ("wrap is applied and the scenario keeps its name", row_wrap_is_applied_in_the_run_and_keeps_the_scenario_name),
    ("unknown order refused, normal accepted", row_unknown_order_is_refused_and_normal_is_accepted),
    ("a sys.exit in a scenario is contained", row_a_sys_exit_in_a_scenario_is_contained),
    ("reverse order reverses each list", row_reverse_order_reverses_each_list),
    ("a raising scenario is contained and the next runs", row_a_raising_scenario_is_contained_and_the_next_runs),
    ("cleanup at the end leaves no world directory", row_cleanup_at_end_leaves_no_world_directory),
]


def main():
    for name, row in ROWS:
        try:
            problem = row()
        except Exception as error:
            problem = f"the row raised {type(error).__name__}: {error}"
        harness.check(name, problem is None, problem or "")
    SW.cleanup_all()
    leftovers = [root for _tag, root in BUILT if root.exists()]
    harness.check("every root a builder made is gone at the end", not leftovers, f"left: {leftovers}")
    harness.finish("test_scenario_world")


if __name__ == "__main__":
    main()
