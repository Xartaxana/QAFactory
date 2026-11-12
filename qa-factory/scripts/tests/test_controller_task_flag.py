#!/usr/bin/env python3
"""`controller.py --task <KEY>` is a key, never an abbreviation of `--task-root` (CX1-10).

On a Codex run `--task TP2-2406` was read by argparse as the abbreviation of `--task-root`
(the docstring went in as `prog`, and abbreviations were on), the value became a RELATIVE root, and
the controller created `<cwd>/TP2-2406/state/` - a phantom story folder whose `recover` then
wrote a projection of "S0, revision 0" that looked like a success. The battery B1..B26 drives the
real command line over a temp project and pins: the flag pair, the exact key -> folder rule
(`hooklib.story_root`), the refusals that leave no byte behind, and the one phrase the driver reads.
"""
import hashlib
import json
import os
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
from controller import Controller  # noqa: E402

PHRASE = "initialize task before work"


def snapshot(*roots):
    """(relative path, size, sha256) of every file under `roots`: "nothing was written" is this being equal."""
    seen = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            data = path.read_bytes() if path.is_file() else None
            seen[(str(root), path.relative_to(root).as_posix())] = (
                None if data is None else (len(data), hashlib.sha256(data).hexdigest()))
    return seen


def make_project():
    """A project with an initialized story TP3-1 and TP3-2, a story whose S0 closed (pipeline.json) and that has no
    journal yet. Returns (project, artifacts, env)."""
    project = temp_project("qa-task-flag-")
    artifacts = project / "qa-factory" / "artifacts"
    story = artifacts / "TP3-1"
    story.mkdir(parents=True)
    Controller(story).apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                           "known_paths": {"root": str(story)}, "idempotency_key": "init"})
    second = artifacts / "TP3-2"
    second.mkdir()
    (second / "pipeline.json").write_text(json.dumps({"task_id": "TP3-2"}), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    return project, artifacts, env


def cli(project, env, *args):
    return run_script("controller.py", *args, cwd=project, env=env)


def answer_of(result):
    """The JSON a command printed, or `{}` when it printed none (a refused call): the row then reads FAIL and the
    battery goes on, so a mutation shows every row it breaks and not the first traceback."""
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {}


def error_text(stderr):
    """The `error` of a refusal as the driver reads it; the raw text when the refusal is not the JSON object."""
    try:
        return json.loads(stderr)["error"]
    except (ValueError, KeyError, TypeError):
        return stderr


def refused(name, result, *needles, code=2):
    check_eq(f"{name}: exit {code}", result.returncode, code)
    check_eq(f"{name}: nothing on stdout", result.stdout, "")
    for needle in needles:
        check_in(f"{name}: says {needle!r}", needle, result.stderr)
    return result.stderr


def untouched(name, project, env, *args, needles=(), code=2):
    """Run, expect a refusal, and prove the project tree and the cwd are byte for byte what they were."""
    before = snapshot(project)
    result = cli(project, env, *args)
    refused(name, result, *needles, code=code)
    check(f"{name}: no byte written", snapshot(project) == before)
    return result


def the_key_is_a_key_and_the_pair_is_exclusive():
    project, artifacts, env = make_project()
    try:
        # B1, B4: `--task KEY` is the same story as `--task-root <folder>`, in both spellings of the flag
        by_root = cli(project, env, "--task-root", artifacts / "TP3-1", "--operation", "next")
        by_key = cli(project, env, "--task", "TP3-1", "--operation", "next")
        by_eq = cli(project, env, "--task=TP3-1", "--operation", "next")
        check_eq("B1: --task TP3-1 answers", by_key.returncode, 0)
        check_eq("B1: and says what --task-root says", by_key.stdout, by_root.stdout)
        check_eq("B4: --task=TP3-1 is the same call", by_eq.stdout, by_root.stdout)
        # B2, M1: an abbreviation of a flag is nobody's flag; the one that would have been read as --task-root
        # (`--task-r` has no other candidate) must not reach a root
        untouched("B2: --tas", project, env, "--tas", "TP3-1", "--operation", "next",
                  needles=("one of the arguments --task --task-root is required",))
        check_not_in("B2: the phantom folder is not there", "TP3-1", str(sorted(p.name for p in project.iterdir())))
        untouched("B2: --task-r (a prefix of one flag only)", project, env, "--task-r", artifacts / "TP3-1",
                  "--operation", "next", needles=("one of the arguments --task --task-root is required",))
        # B3: nor next to a good root
        untouched("B3: --task-root plus --tas", project, env, "--task-root", artifacts / "TP3-1", "--tas", "X",
                  "--operation", "next", needles=("unrecognized arguments: --tas X",))
        # B12: both flags -> a refusal naming both, in either order
        for order, line in ((("--task", "TP3-1", "--task-root", artifacts / "TP3-1"),
                             "argument --task-root: not allowed with argument --task"),
                            (("--task-root", artifacts / "TP3-1", "--task", "TP3-1"),
                             "argument --task: not allowed with argument --task-root")):
            untouched(f"B12: {order[0]} first", project, env, *order, "--operation", "next", needles=(line,))
        # B13: the prefix of another flag is no flag either
        untouched("B13: --op", project, env, "--task", "TP3-1", "--op", "next",
                  needles=("the following arguments are required: --operation",))
        untouched("B13: --words-f", project, env, "--task", "TP3-1", "--operation", "next", "--words-f", "F",
                  needles=("unrecognized arguments: --words-f F",))
    finally:
        cleanup(project)


def argparse_speaks_for_itself():
    project, artifacts, env = make_project()
    try:
        # B23, M2: the description is the docstring and `prog` is the command; a refusal does not open with the docstring
        helped = cli(project, env, "--help")
        check_eq("B23: --help exits 0", helped.returncode, 0)
        check_in("B23: --help describes the command by its docstring", "Task-scoped lifecycle API", helped.stdout)
        check_in("B23: and shows the pair", "(--task KEY | --task-root PATH)", helped.stdout)
        failed = cli(project, env, "--operation", "next")
        first = failed.stderr.splitlines()[0] if failed.stderr else ""
        check("B23: a refusal opens with `usage: controller.py`", first.startswith("usage: controller.py"), first)
        check_not_in("B23: and never with the docstring", "Task-scoped lifecycle API", failed.stderr)
        check_in("B23: the pair is required", "one of the arguments --task --task-root is required", failed.stderr)
    finally:
        cleanup(project)


def a_key_must_name_a_story_folder_exactly():
    project, artifacts, env = make_project()
    try:
        # B5: an empty root is not the cwd
        for value in ("", "  "):
            untouched(f"B5: --task-root {value!r}", project, env, "--task-root", value, "--operation", "next",
                      needles=("--task-root requires the story's folder",))
        # B6: a key is ONE component
        for value in ("", "  ", "a/b", "a\\b", "..", ".", "C:x"):
            untouched(f"B6: --task {value!r}", project, env, "--task", value, "--operation", "next",
                      needles=("requires a story's ticket key", "ticket key"))
        # B7: a space inside is another name; no story, no hint
        stderr = untouched("B7: --task 'TP3 1'", project, env, "--task", "TP3 1", "--operation", "next",
                           needles=("names no story",)).stderr
        check_not_in("B7: and no folder to point at", "exists: the key is matched exactly", stderr)
        # B8, B9: a near miss is refused and the real folder is named - never guessed
        for key in ("TP3-1 ", "TP3-1.", "tp3-1", "Tp3-1 ."):
            stderr = untouched(f"B8/B9: --task {key!r}", project, env, "--task", key, "--operation", "next",
                               needles=("names no story",)).stderr
            check_in(f"B8/B9: {key!r} names the real folder", "A folder 'TP3-1' exists: the key is matched exactly",
                     stderr)
        # B10: a Cyrillic homoglyph is a different name, and the JSON shows which character it is
        stderr = untouched("B10: --task with a Cyrillic E", project, env, "--task", chr(0x415) + "PM-1", "--operation",
                           "next", needles=("names no story",)).stderr
        check_in("B10: the character is visible in the error", "\\u0415PM-1", stderr)
        # a FILE of that name is no story, and is not pointed at as one
        (artifacts / "TP3-F").write_text("x", encoding="utf-8")
        stderr = untouched("a file named like the key", project, env, "--task", "TP3-F", "--operation", "next",
                           needles=("names no story",)).stderr
        check_not_in("a file is not 'a folder that exists'", "A folder", stderr)
        # B11, M5: an unknown key is refused for every operation, and nothing is created for it
        for operation in ("recover", "next", "prepare"):
            untouched(f"B11: TP3-404 {operation}", project, env, "--task", "TP3-404", "--operation", operation,
                      needles=("names no story", "TP3-404"))
        check("B11: no TP3-404 anywhere under the project",
              not any(p.name == "TP3-404" for p in project.rglob("*")))
        # R2 never carries the phrase the driver turns into `initialize` (F-12), unless the key itself says it
        stderr = untouched("R2 vs the driver", project, env, "--task", "TP3-404", "--operation", "recover").stderr
        check_not_in("R2 does not say the driver's phrase", PHRASE, stderr)
    finally:
        cleanup(project)


def a_name_over_the_limit_is_a_refusal_not_a_trace():
    """B25, B26 (magnitude): Python 3.12 `Path.is_dir()` re-raises ENAMETOOLONG on Linux; the CLI printed
    `[Errno 36] File name too long` instead of the refusal. Windows hides it, docker shows it."""
    project, artifacts, env = make_project()
    try:
        for size in (255, 256, 300, 5000):
            stderr = untouched(f"B25: --task of {size} characters", project, env, "--task", "k" * size,
                               "--operation", "next", needles=("names no story",)).stderr
            check_not_in(f"B25: {size} characters: not an OS error", "Errno", stderr)
        for size in (255, 300):
            stderr = untouched(f"B26: --task-root with a {size}-character component", project, env, "--task-root",
                               "nowhere/" + "k" * size, "--operation", "next", needles=("is not a folder",)).stderr
            check_not_in(f"B26: {size} characters: not an OS error", "Errno", stderr)
    finally:
        cleanup(project)


def a_relative_root_is_the_doctors_form_and_a_missing_one_is_refused():
    project, artifacts, env = make_project()
    try:
        # B14: the doctor's repair.md spells the root relative to the project, from the project
        relative = cli(project, env, "--task-root", "qa-factory/artifacts/TP3-1", "--operation", "next")
        absolute = cli(project, env, "--task-root", artifacts / "TP3-1", "--operation", "next")
        check_eq("B14: a relative --task-root works", relative.returncode, 0)
        check_eq("B14: and is the story the absolute form names", relative.stdout, absolute.stdout)
        # B15: a root that is not there is refused with where it looked, and nothing is made
        stderr = untouched("B15: --task-root nowhere/TP3-1", project, env, "--task-root", "nowhere/TP3-1",
                           "--operation", "next", needles=("is not a folder", "never created here")).stderr
        check_in("B15: the refusal gives the absolute path", os.path.abspath(project / "nowhere" / "TP3-1"),
                 stderr.replace("\\\\", "\\"))
        check("B15: no folder appeared", not (project / "nowhere").exists())
        # --task-root naming a FILE
        (project / "afile").write_text("x", encoding="utf-8")
        untouched("--task-root naming a file", project, env, "--task-root", "afile", "--operation", "next",
                  needles=("is not a folder",))
        # B21: a project that has no artifact root on disk at all
    finally:
        cleanup(project)
    bare = temp_project("qa-task-flag-bare-")
    try:
        bare_env = dict(os.environ, CLAUDE_PROJECT_DIR=str(bare))
        assert not (bare / "qa-factory" / "artifacts").exists()
        untouched("B21: no artifact root on disk", bare, bare_env, "--task", "TP3-1", "--operation", "next",
                  needles=("names no story",))
        check("B21: and none was made", not (bare / "qa-factory" / "artifacts").exists())
    finally:
        cleanup(bare)


def a_folder_without_a_journal_is_refused_except_for_the_two_that_may_act():
    project, artifacts, env = make_project()
    try:
        # B16, M4: a story whose S0 closed and has no journal: refused, with the phrase the driver reads
        for operation in ("recover", "next", "stage-scope", "gate-preflight"):
            stderr = untouched(f"B16: TP3-2 {operation}", project, env, "--task", "TP3-2", "--operation",
                               operation, needles=(PHRASE, "nothing was written")).stderr
        check("B16: no state/ appeared in the folder", not (artifacts / "TP3-2" / "state").exists())
        # the same through --task-root
        untouched("B16: --task-root form", project, env, "--task-root", artifacts / "TP3-2", "--operation",
                  "recover", needles=(PHRASE,))
        # B17, M7: prepare is documented BEFORE initialize and only reads: allowed, writes nothing
        before = snapshot(project)
        prepared = cli(project, env, "--task", "TP3-2", "--operation", "prepare")
        check_eq("B17: prepare on TP3-2 runs", prepared.returncode, 0)
        check_eq("B17: and offers S0", answer_of(prepared).get("next_action", {}).get("stage"), "S0")
        check("B17: and wrote nothing", snapshot(project) == before)
        # edge (e): prepare runs before S0 wrote the pipeline.json, on a folder that exists under the exact key
        (artifacts / "TP3-3").mkdir()
        before = snapshot(project)
        early = cli(project, env, "--task", "TP3-3", "--operation", "prepare")
        check_eq("(e): prepare on a folder with neither journal nor pipeline.json", early.returncode, 0)
        check("(e): and wrote nothing", snapshot(project) == before)
        # a folder with NEITHER file is no story: the phrase would send the driver to an `initialize` that is refused
        for operation in ("recover", "next", "initialize"):
            stderr = untouched(f"(d): TP3-3 {operation}", project, env, "--task", "TP3-3", "--operation", operation,
                               "--input", "none.json", needles=("is not a story folder", "pipeline.json")).stderr
            check_not_in(f"(d): TP3-3 {operation}: the driver's phrase is not used", PHRASE, stderr)
        # B18: initialize needs a folder with the pipeline.json S0 writes first, and never makes the folder
        request = project / "init.json"
        request.write_text(json.dumps({"scope": [], "source_revision": "src-2", "known_paths": {"root": "x"},
                                       "idempotency_key": "init"}), encoding="utf-8")
        untouched("B18: initialize of an unknown key", project, env, "--task", "TP3-404", "--operation",
                  "initialize", "--input", request, needles=("names no story",))
        untouched("B18: initialize on the project root", project, env, "--task-root", ".", "--operation",
                  "initialize", "--input", request, needles=("is not a story folder",))
        untouched("B18: initialize on the artifact root", project, env, "--task-root", "qa-factory/artifacts",
                  "--operation", "initialize", "--input", request, needles=("is not a story folder",))
        done = cli(project, env, "--task", "TP3-2", "--operation", "initialize", "--input", request)
        check_eq("B18: initialize of TP3-2 (S0 closed) goes through", done.returncode, 0)
        check("B18: and the journal exists", (artifacts / "TP3-2" / "state" / "events.jsonl").is_file())
        # with the journal there, the refusal is gone for every operation
        after = cli(project, env, "--task", "TP3-2", "--operation", "next")
        check_eq("B18: TP3-2 now answers `next`", after.returncode, 0)
    finally:
        cleanup(project)


def a_journal_that_is_empty_or_torn_is_recovers_door():
    """B19: the journal is a FILE; its size is not asked, `recover` is the door of a broken one."""
    project, artifacts, env = make_project()
    try:
        for name, content in (("TP3-4", b""), ("TP3-5", b'{"type": "initialize", "seq')):
            story = artifacts / name
            (story / "state").mkdir(parents=True)
            (story / "state" / "events.jsonl").write_bytes(content)
            result = cli(project, env, "--task", name, "--operation", "recover")
            check_not_in(f"B19: {name} ({len(content)} bytes) is not refused for having no journal", PHRASE,
                         result.stderr)
            check_not_in(f"B19: {name} is not called a non-story", "is not a story folder", result.stderr)
    finally:
        cleanup(project)


def every_problem_comes_in_one_refusal():
    project, artifacts, env = make_project()
    try:
        # B20, K1: an unknown operation and an unknown key are one refusal with both
        stderr = untouched("B20: unknown operation and unknown key", project, env, "--task", "TP3-404",
                           "--operation", "teleport",
                           needles=("2 problems", "must be one of", "gate-decision", "names no story")).stderr
        check_not_in("B20: the driver's phrase is not in it", PHRASE, stderr)
        # an unknown operation alone keeps its text (test_controller_rework_repair_binding pins it through --task-root too)
        untouched("unknown operation alone", project, env, "--task", "TP3-1", "--operation", "teleport",
                  needles=("must be one of", "gate-decision"))
        # B22: outside any project `--task` has no folder to look in (exit 3, the contract of every writer);
        # `--task-root` never needed one
        outside = temp_dir("qa-task-flag-outside-")
        try:
            plain = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
            lost = run_script("controller.py", "--task", "TP3-1", "--operation", "next", cwd=outside, env=plain)
            check_eq("B22: --task outside a project exits 3", lost.returncode, hooklib.EXIT_NO_PROJECT)
            check_in("B22: with the shared text", "no qa-factory/config.json", lost.stderr)
            found = run_script("controller.py", "--task-root", artifacts / "TP3-1", "--operation", "next",
                               cwd=outside, env=plain)
            check_eq("B22: --task-root outside a project still works", found.returncode, 0)
        finally:
            cleanup(outside)
    finally:
        cleanup(project)


def the_driver_reads_the_journal_refusal_and_not_the_key_refusal():
    """B24, M6, I4: `story_run.KNOWN_REFUSALS` turns «initialize task before work» into `initialize`."""
    import story_run
    project, artifacts, env = make_project()
    try:
        journal = cli(project, env, "--task", "TP3-2", "--operation", "recover").stderr
        key = cli(project, env, "--task", "TP3-404", "--operation", "recover").stderr
        (artifacts / "TP3-3").mkdir()  # a folder that holds NEITHER pipeline.json NOR a journal: R3n, not R2
        folder = cli(project, env, "--task", "TP3-3", "--operation", "recover").stderr
        check_in("B24: the neither-file folder is refused as «not a story folder» (not as an unknown key)",
                 "is not a story folder", folder)
        check_in("B24: the unknown key is refused as «names no story»", "names no story", key)
        check_eq("B24: no journal on a story root -> the driver initializes",
                 story_run.match_known(error_text(journal)), ("uninitialized", "initialize"))
        for name, text in (("an unknown key", key), ("a folder with neither file", folder)):
            known = story_run.match_known(error_text(text))
            check(f"B24: {name} is not `uninitialized`", known is None or known[0] != "uninitialized", str(known))
    finally:
        cleanup(project)


def story_root_is_exact_when_the_file_system_is_not():
    """F-5, M3 (visible in docker): emulate NTFS - `is_dir` true for any spelling that differs in case, a
    trailing space or a trailing dot - and the key must still be matched letter for letter."""
    project, artifacts, env = make_project()
    real_is_dir = Path.is_dir

    def ntfs_is_dir(self):
        try:
            names = os.listdir(self.parent)
        except OSError:
            return False
        alias = self.name.rstrip(" .").lower()
        return real_is_dir(self) or any(n.rstrip(" .").lower() == alias and real_is_dir(self.parent / n)
                                        for n in names)

    old_env = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        use_project(project)
        check("the stub IS blind to case and trailing blanks", ntfs_is_dir(artifacts / "tp3-1")
              and ntfs_is_dir(artifacts / "TP3-1 ") and ntfs_is_dir(artifacts / "TP3-1."))
        with mock.patch.object(Path, "is_dir", ntfs_is_dir):
            check_eq("the exact key is the folder", hooklib.story_root("TP3-1", "t"), artifacts.resolve() / "TP3-1")
            for key in ("tp3-1", "TP3-1 ", "TP3-1.", "TP3-1 .", "Tp3-1"):
                try:
                    hooklib.story_root(key, "t")
                    got = "accepted"
                except ValueError as exc:
                    got = str(exc)
                check_in(f"{key!r} is refused, though the stub says it is a folder", "names no story", got)
                check_in(f"{key!r}: with the real folder named", "A folder 'TP3-1' exists", got)
        # an error of the stat is "not a folder", not a trace
        def failing(self):
            raise OSError(36, "File name too long")
        with mock.patch.object(Path, "is_dir", failing):
            try:
                hooklib.story_root("TP3-1", "t")
                got = "accepted"
            except ValueError as exc:
                got = str(exc)
            check_in("a failing stat of the listed folder is a refusal", "names no story", got)
        # a refusal opens with the caller's name, carries its door, and names no door the caller lacks
        try:
            hooklib.story_root("TP3-404", "mytool", "Try the other way.")
        except ValueError as exc:
            check("the caller's name opens the refusal", str(exc).startswith("mytool "), str(exc))
            check("its own door closes it", str(exc).endswith("Try the other way."), str(exc))
            check_not_in("and --task-root is not offered by the shared rule", "--task-root", str(exc))
    finally:
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(project)


def the_is_dir_rule_is_written_once():
    """t-946 F-3: «`is_dir`, an OSError is "no"» is `hooklib.is_dir_or_no`; the controller calls it and carries no twin
    (a function of `controller.py` that stats a folder inside a try over OSError is a second copy of the rule)."""
    import ast
    import controller

    def twins(path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        found = []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                stats = isinstance(node, ast.Try) and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                                                          and c.func.attr == "is_dir" for c in ast.walk(node))
                catches = isinstance(node, ast.Try) and any(isinstance(h.type, ast.Name) and h.type.id == "OSError"
                                                            for h in node.handlers)
                if stats and catches:
                    found.append(fn.name)
        return sorted(set(found))

    check_eq("the controller names hooklib's path rule, not its own", controller.story_root_at, hooklib.story_root_at)
    check_eq("controller.py has no function that wraps `is_dir` in an OSError catch", twins(controller.__file__), [])
    # positive control of the scanner: it finds the one in hooklib (and the guarded stat of story_root is no longer inline)
    check_eq("the scanner finds the rule where it lives", twins(hooklib.__file__), ["is_dir_or_no"])
    check_eq("an error of the stat is read as 'no'", hooklib.is_dir_or_no("k" * 5000), False)


def windows_names_that_no_listing_shows():
    """B8 (NTFS only): the 8.3 short name of a long folder is a name `is_dir` accepts and the listing does not."""
    if os.name != "nt":
        check("B8: 8.3 names exist on NTFS only - nothing to pin here", True)
        return
    import ctypes
    project, artifacts, env = make_project()
    try:
        long_name = artifacts / "TP2-2406"
        long_name.mkdir()
        buffer = ctypes.create_unicode_buffer(300)
        ctypes.windll.kernel32.GetShortPathNameW(str(long_name), buffer, 300)
        short = Path(buffer.value).name
        if short.lower() == long_name.name.lower():
            check("B8: this volume makes no 8.3 names - nothing to pin", True)
            return
        check("B8: the short name is a folder to the file system", (artifacts / short).is_dir())
        stderr = untouched("B8: the 8.3 name of a story", project, env, "--task", short, "--operation", "prepare",
                           needles=("names no story",)).stderr
        check_not_in("B8: and the driver's phrase is not in it", PHRASE, stderr)
    finally:
        cleanup(project)


BATTERIES = (the_key_is_a_key_and_the_pair_is_exclusive, argparse_speaks_for_itself,
             a_key_must_name_a_story_folder_exactly, a_name_over_the_limit_is_a_refusal_not_a_trace,
             a_relative_root_is_the_doctors_form_and_a_missing_one_is_refused,
             a_folder_without_a_journal_is_refused_except_for_the_two_that_may_act,
             a_journal_that_is_empty_or_torn_is_recovers_door, every_problem_comes_in_one_refusal,
             the_driver_reads_the_journal_refusal_and_not_the_key_refusal,
             story_root_is_exact_when_the_file_system_is_not, the_is_dir_rule_is_written_once,
             windows_names_that_no_listing_shows)


def main():
    """Every battery runs: one that stops on an exception is a FAIL row with the exception's first line, counted with
    the rest, so a mutation of the command shows the whole picture and not the first traceback."""
    for battery in BATTERIES:
        try:
            battery()
        except Exception as exc:  # noqa: BLE001 - a traceback is a failed row here, never the end of the run
            lines = (str(exc).splitlines() or [""])
            check(f"{battery.__name__}: ran to the end", False, f"{type(exc).__name__}: {lines[0]}")
    finish("test_controller_task_flag")


if __name__ == "__main__":
    main()
