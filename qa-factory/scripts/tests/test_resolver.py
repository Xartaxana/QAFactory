#!/usr/bin/env python3
"""t-304 N1: ONE resolver; a story's stored absolute paths are HINTS, resolved when they are read.

cmp2 -> man1 (02.10): a story copied to another worktree kept the absolute paths `initialize` stored, and six readers
took them as locations - the config read (so `cases_root` wrote case documents into the other project), the dashboard
refresh (it wrote into the other project), the role packets of the hook and of the driver (the other project and the
frozen package of another generation), `controller.prepare`'s fallback and the dispatch record the hook prints.

What this file proves, key by key (the keys are named in the spec, docs/tasks/specs/t-304-N0N1-state-resolver.md and
the designer draft section 4):
  K1  the API and the adversarial hint battery (containment by components, 8.3 against long names, junctions, a file for
      a folder, a path over 260 characters, `project_for_task`'s order and refusals, the token round trip, the note
      printed once);
  K2  the move: a story copied next to the old copy, which stays on disk as a valid project, read from the copy by every
      reader - and the old copy's tree is not touched;
  K3  another project's stored root: ONE stderr line naming both, stdout still JSON;
  K4  absent, empty and legacy hints; a stored root that is not on this machine;
  K5  the same place changes nothing (the golden proxy: `state_paths(stored) == stored`, exactly);
  K6  FR-45: the readers write no byte of the story's state;
  K7  the sentinel: no script reads a controller state's `known_paths` for a location outside the allow-list;
  K8  a tokenised RUN packet with an absolute leftover (Q6);
  K9  the resolution is memoised per controller.json stat key (B-013), counted and never timed (FR-31);
  K10 a plugin update mid-story: the readers never refuse on generation; a RUN packet of another package still is.
"""
import contextlib
import copy
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract  # noqa: E402
import dashboard_refresh  # noqa: E402
import hooklib  # noqa: E402
import inject_context as IC  # noqa: E402
import runtime_paths  # noqa: E402
from controller import Controller  # noqa: E402

TASK = "QA-1"
ROLE = "qa-scout"
PACKAGE = harness.PLUGIN_ROOT
# the Windows-only keys say so when they cannot run, and never print a PASS for a check that did not execute
CLEAN: list = []
CWD0 = os.getcwd()
ENV0 = dict(os.environ)
# the dashboard renders a whole project per commit; the keys that are not about it keep it off
SKIP = "QA_FACTORY_SKIP_DASHBOARD_REFRESH"


def cyr(*codes) -> str:
    """Cyrillic from code points: the package is English, even its fixtures (FR-30)."""
    return "".join(chr(code) for code in codes)


def restore_process() -> None:
    os.chdir(CWD0)
    for key in set(os.environ) - set(ENV0):
        os.environ.pop(key, None)
    os.environ.update(ENV0)
    os.environ[SKIP] = "1"
    hooklib._PROJECT_ROOT_CACHE = None


def scratch() -> Path:
    # temp_dir, not temp_project: this suite builds its OWN projects (`make_project`, configs with chosen content) and its
    # unmarked folders (`none`, `lone`, `nowhere`, `alone`) model the "unknown" road on purpose (t-617 section 8.2)
    base = temp_dir("qa-resolver-").resolve()
    CLEAN.append(base)
    return base


def make_project(base: Path, name: str, cfg: dict | None = None) -> Path:
    project = (base / name).resolve()
    (project / "qa-factory" / "artifacts" / TASK).mkdir(parents=True)
    (project / "qa-factory" / "config.json").write_text(json.dumps(cfg or {}), encoding="utf-8")
    return project


def task_of(project: Path) -> Path:
    return project / "qa-factory" / "artifacts" / TASK


def init_story(task: Path, known: dict) -> Controller:
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": known,
                                    "idempotency_key": "init"})
    return controller


def spellings(path) -> list:
    text = str(path)
    return sorted({text, text.replace(chr(92), "/"), json.dumps(text)[1:-1], text.replace(chr(92), "/").lower()})


def leaks(blob: str, paths) -> list:
    """The spellings of `paths` found in `blob`: raw, forward slashes, JSON-escaped, lowercase. A spelling that is the
    start of a sibling's name (root + `r`) is not a leak: it must be followed by anything but a name character."""
    return [spelling for path in paths for spelling in spellings(path)
            if re.search(re.escape(spelling) + r"(?![\w-])", blob, flags=re.I)]


def listing(root: Path) -> list:
    out = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = Path(folder) / name
            stat = path.stat()
            out.append((path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size))
    return sorted(out)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def short_name(path) -> str | None:
    """The 8.3 spelling of an existing path, or None where the platform or the volume has none."""
    if os.name != "nt":
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(2048)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 2048):
        return None
    return buffer.value if buffer.value.lower() != str(path).lower() else None


def quiet():
    """stderr captured: the note is the subject of some keys and noise in the rest."""
    return contextlib.redirect_stderr(io.StringIO())


def reset_notes() -> None:
    runtime_paths._NOTED.clear()
    contract._CONTROLLER_ROOT_CACHE.clear()
    contract.case_config_reset()


def make_driver(project: Path, plugin_dir=None):
    """An in-process story_run Driver over `project` (the shape `story_run_common.driver_for` builds). The Driver moves
    the process into the project and rewrites CLAUDE_PROJECT_DIR; `restore_process` puts both back."""
    import story_run
    ns = types.SimpleNamespace(task=TASK, answer=None, until="end", dry_run=False, model="sonnet", plugin_dir=plugin_dir,
                               project=str(project), mr=None, branch=None, commit=None, ungrounded=False,
                               ticket_file=None, env=None, branch_suffix="", max_boundaries=10)
    with contextlib.redirect_stdout(io.StringIO()):
        return story_run.Driver(ns)


def packet_after(text: str, marker: str = "# Resolved task packet (reuse paths and completed checks)\n") -> dict:
    start = text.rindex(marker) + len(marker)
    packet, _end = json.JSONDecoder().raw_decode(text[start:])
    return packet


def run_hook(project: Path, event_extra: dict | None = None) -> tuple:
    """inject_context.main() in this process, as the PreToolUse hook of an `Agent` dispatch of the scout in `project`.
    The stage guard is not the subject: it is stood in for by a function that allows (its refusals have their own tests)."""
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
             "tool_input": {"subagent_type": ROLE, "prompt": f"Dispatch id: S0-{ROLE}-1\nTask {TASK}"}}
    event.update(event_extra or {})
    real = (IC.read_event, IC.run_stage_guard, sys.argv)
    IC.read_event, IC.run_stage_guard, sys.argv = (lambda: event), (lambda _event: None), ["inject_context.py"]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                IC.main()
            except SystemExit as stop:
                code = stop.code or 0
    finally:
        IC.read_event, IC.run_stage_guard, sys.argv = real
    return code, out.getvalue(), err.getvalue()


def hook_prompt(project: Path) -> tuple:
    code, out, err = run_hook(project)
    prompt = json.loads(out)["hookSpecificOutput"]["updatedInput"]["prompt"] if out.strip() else ""
    return code, prompt, err


# --- K1: the API and the adversarial hint battery -----------------------------------------------------------------

def k1_containment() -> None:
    base = scratch()
    root = base / "proj"
    (root / "sub").mkdir(parents=True)
    (base / "projr" / "sub").mkdir(parents=True)
    (base / "projr" / "f.txt").write_text("x", encoding="utf-8")
    check("K1 contained: a folder inside the root is inside, the root itself is inside (inclusive)",
          runtime_paths.contained(root / "sub", root) and runtime_paths.contained(root, root))
    check("K1 contained E3: a sibling whose name EXTENDS the root's (proj / projr) is NOT inside it, either way round",
          not runtime_paths.contained(base / "projr" / "sub", root) and not runtime_paths.contained(root / "sub", base / "projr"))
    check("K1 contained E3: ...and the same by text spelling, with a trailing separator on the root",
          not runtime_paths.contained(str(base / "projr") + os.sep + "sub", str(root) + os.sep)
          and runtime_paths.contained(str(root / "sub") + os.sep, str(root) + os.sep))
    check("K1 contained: a path that does not exist yet is compared as spelled (inside / outside)",
          runtime_paths.contained(root / "no" / "such" / "file", root)
          and not runtime_paths.contained(base / "no" / "such", root))
    for label, bad in (("None", None), ("a number", 5), ("a list", [str(root)]), ("bytes", str(root).encode()),
                       ("an empty string", ""), ("a blank string", "   "), ("a relative path", "proj/sub"),
                       ("a dot", "."), ("a URL", "file:///" + str(root).replace(chr(92), "/")),
                       ("a null byte", str(root) + chr(0))):
        check(f"K1 contained: {label} is not inside (False, never an exception)",
              runtime_paths.contained(bad, root) is False and runtime_paths.contained(root / "sub", bad) is False)
    if os.name == "nt":
        swapped = str(root / "sub").swapcase()
        check("K1 contained E11 (nt): a case variant and a trailing separator still count as inside",
              runtime_paths.contained(swapped, root) and runtime_paths.contained(str(root) + os.sep, root))
        other = "Z:" if not str(root).upper().startswith("Z:") else "Y:"
        check("K1 contained E11 (nt): another drive and a UNC share are not inside",
              not runtime_paths.contained(other + chr(92) + "x", root)
              and not runtime_paths.contained(chr(92) * 2 + "server" + chr(92) + "share" + chr(92) + "x", root))
        check("K1 contained (nt): a rooted path with no drive (the current drive's) is no absolute path, so not inside",
              not runtime_paths.contained(chr(92) + "x", root))
    else:
        print("skipped (not nt): the case variant, the drive and the UNC keys of K1")
    (root / "afile").write_text("x", encoding="utf-8")
    check("K1 contained: a FILE where a folder is wanted holds nothing (rejected as the root)",
          not runtime_paths.contained(root / "afile", root / "afile") and not runtime_paths.contained(root / "afile" / "x", root / "afile"))
    deep = root.joinpath(*["d" * 20 for _ in range(14)], "leaf.txt")
    check("K1 contained: a path over 260 characters is handled (inside, no exception)",
          len(str(deep)) > 260 and runtime_paths.contained(deep, root) and not runtime_paths.contained(deep, base / "projr"))


def k1_alias_and_links() -> None:
    base = scratch()
    root = base / "a-project-folder-with-a-long-name"
    deep = root / "a-second-long-folder-name" / "and-a-third-one-below-it"
    deep.mkdir(parents=True)
    short = short_name(deep)
    if short is None:
        print("skipped: no 8.3 alias (not nt, or the volume keeps no short names) - the 8.3 keys of K1 did not run")
    else:
        short_root = short_name(root)
        check("K1 8.3: the short and the long spelling of one folder are the same place (inside, both ways)",
              runtime_paths.contained(short, root) and runtime_paths.contained(deep, short_root)
              and runtime_paths._same_place(short, str(deep)) and runtime_paths._same_place(str(root), short_root),
              f"{short} / {deep}")
        sibling = base / (root.name + "-x")
        sibling.mkdir()
        check("K1 8.3: the short spelling of a SIBLING whose name extends the root's is not inside the root",
              not runtime_paths.contained(short_name(sibling), root) and not runtime_paths.contained(short_name(sibling), short_root))
        # a root spelled 8.3 holds a path spelled long, and the other way round: by the real places, not by text
        portable = runtime_paths.portable_known_paths({"plan": str(deep / "f.json")}, short_root, "C:/none")
        check("K1 8.3: a long path under an 8.3 root is made portable (E12: the real places, not the text) and resolves back long",
              portable["plan"] == "{project_root}/a-second-long-folder-name/and-a-third-one-below-it/f.json"
              and runtime_paths.resolve_known_paths(portable, str(root), "C:/none", sys.executable)["plan"] == str(deep / "f.json"), str(portable))
    outside = base / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("x", encoding="utf-8")
    (root / "real").mkdir(exist_ok=True)
    (root / "real" / "f.txt").write_text("x", encoding="utf-8")
    link = root / "link"
    made = False
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
            made = True
        except Exception:
            made = False
    else:
        try:
            os.symlink(outside, link, target_is_directory=True)
            made = True
        except OSError:
            made = False
    if not made:
        print("skipped: no junction / symlink could be made here - the link key of K1 did not run")
    else:
        check("K1 links: a junction inside the root that lands OUTSIDE it is rejected; a real folder beside it is inside",
              not runtime_paths.contained(link / "f.txt", root) and runtime_paths.contained(root / "real" / "f.txt", root))


def project_battery() -> None:
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    os.environ["CLAUDE_PROJECT_DIR"] = str(base)          # a place that is no project: candidate 2 does not rescue
    hooklib._PROJECT_ROOT_CACHE = None
    hints = [("an empty string", "", False), ("a dot", ".", False), ("a relative path", "elsewhere/proj", False),
             ("None", None, False), ("a number", 7, False), ("a list", [str(project)], False),
             ("a file:// URL", "file:///" + str(project).replace(chr(92), "/"), False),
             ("a 4 kB path", str(base) + os.sep + ("p" * 4000), True),
             ("a deeply nested path", str(base) + os.sep + os.sep.join(["n"] * 120), True),
             ("a path with Cyrillic and a space",
              str(base) + os.sep + cyr(0x43F, 0x440, 0x43E, 0x435, 0x43A, 0x442) + " " + cyr(0x43A, 0x43E, 0x43F, 0x438, 0x44F), True),
             ("this very project, spelled with a trailing separator", str(project) + os.sep, False)]
    for label, hint, noted in hints:
        reset_notes()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                got = runtime_paths.project_for_task(task, hint=hint)
            except Exception as exc:                           # noqa: BLE001 - the key is that none is raised
                got = exc
        lines = [line for line in err.getvalue().splitlines() if line.strip()]
        check(f"K1 hint battery ({label}): the project is found from the story's own place, whatever the hint says",
              got == project, repr(got))
        check(f"K1 hint battery ({label}): " + ("one note on stderr, no longer than a line a person reads" if noted
                                                else "no note (it is no path of this machine, or it is this project)"),
              (len(lines) == 1 and len(lines[0]) < 900 and lines[0].startswith("project:")) if noted else not lines,
              err.getvalue()[:300])
    reset_notes()
    # a hint that is a stored value of the state: the same battery through `state_paths`
    for label, hint, _noted in hints:
        with quiet():
            got = runtime_paths.state_paths({"project_root": hint, "root": str(task)}, task, plugin=PACKAGE)
        check(f"K1 hint battery ({label}) through state_paths: project_root is this project's own",
              got.get("project_root") == str(project) and got.get("root") == str(task), str(got)[:200])


def k1_project_for_task() -> None:
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    other = make_project(base, "other")
    os.environ["CLAUDE_PROJECT_DIR"] = str(other)           # the process works in ANOTHER project
    hooklib._PROJECT_ROOT_CACHE = None
    reset_notes()
    with quiet():
        found = runtime_paths.project_for_task(task, hint=str(other))
    check("K1 project_for_task: the nearest ancestor with a config wins over the process's project and over the hint",
          found == project, str(found))
    outside = base / "stories" / TASK
    outside.mkdir(parents=True)
    home = make_project(base, "home", {"artifact_root": str(base / "stories")})
    os.environ["CLAUDE_PROJECT_DIR"] = str(home)
    hooklib._PROJECT_ROOT_CACHE = None
    check("K1 project_for_task E4: a story outside every project is found through the process's project when its "
          "artifact_root contains it (candidate 2, no hint)", runtime_paths.project_for_task(outside) == home)
    os.environ["CLAUDE_PROJECT_DIR"] = str(base)
    hooklib._PROJECT_ROOT_CACHE = None
    check("K1 project_for_task E4: ...and through the hint when nothing else holds it (candidate 3)",
          runtime_paths.project_for_task(outside, hint=str(home)) == home)
    reset_notes()
    try:
        runtime_paths.project_for_task(outside, hint=str(other))
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K1 project_for_task E4: a hint whose artifact root does NOT contain the story is never adopted - the refusal says "
          "what was tried, what was expected and the door (`--project`)",
          "--project" in refused and str(outside) in refused and "artifact root" in refused and str(other) in refused, refused[:400])
    try:
        runtime_paths.project_for_task(outside)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K1 project_for_task: no candidate at all is a refusal with the door too (never a guess)", "--project" in refused, refused[:300])
    # a candidate whose config cannot be read is rejected, never raised (E11)
    broken = make_project(base, "broken")
    (broken / "qa-factory" / "config.json").write_text("{not json", encoding="utf-8")
    blank = make_project(base, "blank", {"artifact_root": ""})
    foreign = make_project(base, "foreign", {"artifact_root": str(project / "qa-factory" / "artifacts")})
    for label, candidate in (("broken JSON", broken), ("artifact_root: \"\"", blank),
                             ("an absolute artifact_root pointing at another copy", foreign)):
        os.environ["CLAUDE_PROJECT_DIR"] = str(base)
        hooklib._PROJECT_ROOT_CACHE = None
        try:
            runtime_paths.project_for_task(task_of(candidate))
            got = "adopted"
        except ValueError as exc:
            got = "--project" in str(exc)
        check(f"K1 project_for_task E11 ({label}): the candidate is rejected and the refusal names `--project`, nothing is raised",
              got is True, str(got))
    file_as_project = base / "a-file"
    file_as_project.write_text("x", encoding="utf-8")
    reset_notes()
    with quiet():
        found = runtime_paths.project_for_task(task, hint=str(file_as_project))
    check("K1 project_for_task: a FILE named as the hint is no project (rejected, the real one is found)", found == project)
    check("K1 project_for_task: no task folder argument at all is a refusal (ValueError), not a crash", _refused(lambda: runtime_paths.project_for_task(None)))


def _refused(call) -> bool:
    try:
        call()
    except ValueError:
        return True
    except Exception:                                      # noqa: BLE001
        return False
    return False


def k1_tokens_and_notes() -> None:
    base = scratch()
    project, plugin, task = base / "proj", base / "pkg" / "qa-factory", base / "proj" / "qa-factory" / "artifacts" / TASK
    paths = {"task_root": str(task), "plan": str(task / "work" / "test-plan.json"), "project_root": str(project),
             "plugin_root": str(plugin), "scripts_root": str(plugin / "scripts"), "python_executable": "C:/py/python.exe",
             "entrypoints": {"controller": str(plugin / "scripts" / "controller.py")},
             "repository_roots": {"backend": str(base / "elsewhere" / "repo")}, "package_version": "1.2", "n": 5}
    portable = runtime_paths.portable_known_paths(paths, project, plugin, task)
    check("K1 tokens: the longest root wins - a path under the task is `{task_root}/...`, under the project `{project_root}/...`",
          portable["plan"] == "{task_root}/work/test-plan.json" and portable["task_root"] == "{task_root}"
          and portable["project_root"] == "{project_root}" and portable["scripts_root"] == "{plugin_root}/scripts"
          and portable["entrypoints"]["controller"] == "{plugin_root}/scripts/controller.py", str(portable))
    check("K1 tokens: a path under no root, a version and a number stay as they were",
          portable["repository_roots"] == paths["repository_roots"] and portable["package_version"] == "1.2" and portable["n"] == 5)
    back = runtime_paths.resolve_known_paths(portable, project, plugin, "C:/py/python.exe", task)
    check("K1 round trip: portable followed by resolve gives the original paths back, `{task_root}` included",
          back == paths, str(back))
    check("K1 tokens: with no task a `{task_root}` stays unresolved in the pure function and a RUN packet carrying one is "
          "refused (a role never receives an unresolved token)",
          runtime_paths.resolve_known_paths(portable, project, plugin, "p")["plan"] == "{task_root}/work/test-plan.json"
          and _refused(lambda: runtime_paths.known_paths_for_dispatch(
              portable, project_root=project, plugin_root=plugin, python="p", door="the door")))
    without = runtime_paths.portable_known_paths(paths, project, plugin)
    check("K1 tokens: with no task root given the writer is t-335's (no `{task_root}` token anywhere)",
          "{task_root}" not in json.dumps(without) and without["plan"] == "{project_root}/qa-factory/artifacts/QA-1/work/test-plan.json")
    runtime_paths._NOTED.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        runtime_paths.hint_note("project", "C:/old/one", "the project this story is in", "C:/new")
        runtime_paths.hint_note("project", "C:/old/one", "the project this story is in", "C:/new")
    lines = err.getvalue().splitlines()
    check("K1 hint_note (AT): one hint prints one line however often it is met, on stderr, with both places named",
          len(lines) == 1 and "C:/old/one" in lines[0] and "C:/new" in lines[0], err.getvalue())
    with contextlib.redirect_stderr(err):
        runtime_paths.hint_note("project", "C:/old/two", "the project this story is in", "C:/new")
    check("K1 hint_note (BEYOND): a second distinct hint prints its own line", len(err.getvalue().splitlines()) == 2)
    out, err2 = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err2):
        runtime_paths.hint_note("project", "C:/old/three", "the project this story is in", "C:/new")
    check("K1 hint_note: stderr only - nothing on stdout (FR-14)", out.getvalue() == "" and "C:/old/three" in err2.getvalue())
    runtime_paths._NOTED.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        runtime_paths.hint_note("project", "C:/" + "x" * 5000, "the project this story is in", "C:/new")
    check("K1 hint_note: a 5000-character hint is cut (one line stays a line)", len(err.getvalue()) < 900, str(len(err.getvalue())))


def k1_state_paths_policy() -> None:
    """The READ policy on a hand-built stored map: re-rooting, omission with one note, copying of non-paths."""
    base = scratch()
    project = make_project(base, "proj", {"code_repos": [{"id": "backend", "path": "repos/backend"}]})
    old = make_project(base, "old")
    task, old_task = task_of(project), task_of(old)
    X = base / "pkgX" / "qa-factory"
    foreign = base / "elsewhere" / "repo"
    stored = {"task_root": str(old_task), "root": str(old_task), "project_root": str(old), "plugin_root": str(X),
              "scripts_root": str(X / "scripts"), "python_executable": "C:/gone/python.exe",
              "plan": str(old_task / "work" / "test-plan.json"), "evidence": str(old_task / "work" / "evidence" / "a.txt"),
              "rel": "work/x.json", "empty": "", "none": None, "count": 3, "version": "0.7.19",
              "nested": {"inside": str(old_task / "work" / "n.json"), "foreign": str(foreign / "f.py"), "k": [str(old / "qa-factory" / "x")]},
              "stray": str(foreign), "token": "{project_root}/qa-factory/x", "taskish": "{task_root}/work/t.json",
              "entrypoints": {"controller": str(X / "scripts" / "controller.py")}, "repository_roots": {"backend": str(foreign)},
              "package_fingerprint": "f" * 64, "package_version": "0.0.1-old"}
    reset_notes()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = runtime_paths.state_paths(stored, task, plugin=PACKAGE, python="PY")
    check("K1 state_paths: the roots are the reader's own, the stored ones are never used",
          (got["task_root"], got["root"], got["project_root"], got["plugin_root"], got["scripts_root"], got["python_executable"])
          == (str(task), str(task), str(project), str(PACKAGE), str(PACKAGE / "scripts"), "PY"), str(got)[:300])
    check("K1 state_paths: the artifact paths are the registry's for THIS task, and a path under the record's task is re-rooted",
          got["plan"] == str(task / "work" / "test-plan.json") and got["evidence"] == str(task / "work" / "evidence" / "a.txt")
          and got["nested"]["inside"] == str(task / "work" / "n.json") and got["nested"]["k"] == [str(project / "qa-factory" / "x")], str(got)[:400])
    check("K1 state_paths: tokens are resolved against the reader's roots (`{task_root}` reads the task)",
          got["token"] == str(project / "qa-factory" / "x") and got["taskish"] == str(task / "work" / "t.json"))
    check("K1 state_paths: entrypoints are the caller's package, repository roots the current config's, a stored fingerprint "
          "and version are copied and never compared",
          got["entrypoints"]["controller"] == str(PACKAGE / "scripts" / "controller.py")
          and got["repository_roots"] == {"backend": str(project / "repos" / "backend")}
          and got["package_fingerprint"] == "f" * 64 and got["package_version"] == "0.0.1-old")
    check("K1 state_paths: what is not a path (relative, empty, None, number, version) is copied",
          (got["rel"], got["empty"], got["none"], got["count"], got["version"]) == ("work/x.json", "", None, 3, "0.7.19"))
    check("K1 state_paths E7: a path of another copy's checkout / another place is LEFT OUT, never named (top level and nested)",
          "stray" not in got and "foreign" not in got["nested"] and not leaks(json.dumps(got), [old, X, foreign, old_task]), str(got)[:300])
    lines = [line for line in err.getvalue().splitlines() if line.strip()]
    left_out = [line for line in lines if line.startswith("known_paths:")]
    check("K1 state_paths Q7: ONE note on stderr names what was left out (and the one about the rejected project hint is the other line)",
          len(left_out) == 1 and "stray=" in left_out[0] and "nested.foreign=" in left_out[0]
          and len([line for line in lines if line.startswith("project:")]) == 1 and len(lines) == 2, err.getvalue()[:400])
    check("K1 state_paths: the stored key order is kept, minus the omitted keys, and nothing is added",
          list(got) == [key for key in stored if key not in ("stray",)], str(list(got)))
    check("K1 state_paths: the input is not touched (FR-45)", stored["project_root"] == str(old) and stored["stray"] == str(foreign))
    # no project: only `project_root` and what hangs on the project is left out; the rest of the packet is still given
    lone = base / "lone" / "task"
    lone.mkdir(parents=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(base)
    hooklib._PROJECT_ROOT_CACHE = None
    reset_notes()
    with quiet():
        got = runtime_paths.state_paths({"project_root": str(old), "plugin_root": str(X), "token": "{project_root}/x", "task_root": str(old_task)},
                                        lone, plugin=PACKAGE)
    check("K1 state_paths E6: with no project the project's keys are omitted (a role never gets an unresolved token), the package and task stay",
          "project_root" not in got and "token" not in got and got["plugin_root"] == str(PACKAGE) and got["task_root"] == str(lone), str(got))
    with quiet():
        got = runtime_paths.state_paths({"token": "{task_root}/x", "project_root": "{project_root}"}, None, project=project, plugin=PACKAGE)
    check("K1 state_paths E6: `{task_root}` with no task is omitted, the project given by the caller is used", got == {"project_root": str(project)}, str(got))
    check("K1 state_paths: absent, {}, a legacy list and a string are no hint - `{}` comes back, no refusal",
          all(runtime_paths.state_paths(value, task) == {} for value in (None, {}, ["a/b"], "x", 5)))
    deep = {"a": {"b": {"c": {"d": {"e": str(foreign)}}}}}
    for _ in range(40):
        deep = {"n": deep}
    big = "C:" + os.sep + "p" * 4000
    with quiet():
        got = runtime_paths.state_paths({"deep": deep, "big": big, "cyr": str(old_task / cyr(0x43F, 0x440, 0x438, 0x432, 0x435, 0x442) / "a b.txt"),
                                         "project_root": str(old)}, task, plugin=PACKAGE)
    check("K1 state_paths (nesting 45 deep, a 4 kB path, Cyrillic and a space): no crash; the deep foreign path and the 4 kB path are left out; "
          "the Cyrillic path under the record's task is re-rooted",
          "big" not in got and not json.dumps(got["deep"]).count(str(foreign).replace(chr(92), chr(92) * 2))
          and got["cyr"] == str(task / cyr(0x43F, 0x440, 0x438, 0x432, 0x435, 0x442) / "a b.txt"), str(got)[:200])


def k1_reroot_adversarial() -> None:
    """E12: re-rooting goes from advice (t-335's packets) to deciding what a role packet names. Allowed error: a path left
    absolute, which ends as omitted. Forbidden: re-rooting a path that was not under the record's root."""
    base = scratch()
    project = make_project(base, "proj")
    old = make_project(base, "old")
    task, old_task = task_of(project), task_of(old)
    sibling = base / "old-sibling" / "f.json"
    mixed = str(old / "qa-factory").replace(chr(92), "/") + chr(92) + "x" + chr(92) + "y.json"
    shouted = str(old / "qa-factory" / "z.json").upper() if os.name == "nt" else str(old / "qa-factory" / "z.json")
    stored = {"project_root": str(old), "task_root": str(old_task), "sib": str(sibling), "mixed": mixed, "shout": shouted,
              "outer": str(base / "old" / ".." / "old-sibling" / "g.json")}
    reset_notes()
    with quiet():
        got = runtime_paths.state_paths(stored, task, plugin=PACKAGE)
    check("K1 re-root E12: a record root that is a PREFIX of a sibling's name does not re-root the sibling's path (it is left out)",
          "sib" not in got, str(got))
    check("K1 re-root E12: mixed slashes in the stored path re-root under the record's project",
          got.get("mixed") == str(project / "qa-factory" / "x" / "y.json"), str(got.get("mixed")))
    if os.name == "nt":
        check("K1 re-root E12 (nt): a case variant of the record's root still re-roots", got.get("shout", "").lower() == str(project / "qa-factory" / "z.json").lower(), str(got.get("shout")))
    check("K1 re-root E12: a `..` that climbs out of the record's root into the sibling is not under the root (left out)", "outer" not in got, str(got))
    bare = {"plan": str(task / "work" / "x.json"), "elsewhere": str(old / "qa-factory" / "x")}
    with quiet():
        got = runtime_paths.state_paths(bare, task, plugin=PACKAGE)
    check("K1 re-root E12: a record with NO roots reads its registry path as this task's and leaves out a path of another copy",
          got == {"plan": str(task / "work" / "test-plan.json")}, str(got))
    inside = {"note": str(task / "work" / "n.md"), "up": str(task / "work" / ".." / "work" / "n.md"), "rel": "../x.json"}
    with quiet():
        got = runtime_paths.state_paths(inside, task, plugin=PACKAGE)
    check("K1 re-root E12: a path of this very task is kept as it is, even with a `..` that stays inside; a relative `..` value is copied",
          got == inside, str(got))


# --- t-365: the fixes after critic t-362 --------------------------------------------------------------------------

def k1_run_climb() -> None:
    """Critic F1: RUN had no climb guard. `{project_root}/../root1r/...` resolved into the sibling copy and was dispatched,
    which bypasses t-335 A-n3. READ and RUN now share ONE predicate (`_climbs_out`, one `contained` call)."""
    base = scratch()
    project = make_project(base, "root1")
    make_project(base, "root1r")
    task = task_of(project)

    def run(packet, **extra):
        return runtime_paths.known_paths_for_dispatch(packet, project_root=project, plugin_root=PACKAGE, python=sys.executable,
                                                      door="THE DOOR", task_root=extra.get("task_root", task))

    def refusal(packet):
        try:
            run(packet)
        except ValueError as exc:
            return str(exc)
        return ""

    said = refusal({"plan": "{project_root}/../root1r/qa-factory/x.json", "project_root": "{project_root}"})
    check("K1 F1 RUN: a token path that climbs out of {project_root} into a sibling copy is refused - the key, the path and where it lands "
          "are named, with the door and 'Nothing was dispatched'",
          "climbs out" in said and "plan" in said and "root1r" in said and "THE DOOR" in said and "Nothing was dispatched" in said, said[:300])
    check("K1 F1 RUN: ...also from a nested map, from {task_root} and from {plugin_root}",
          "entrypoints.controller" in refusal({"entrypoints": {"controller": "{project_root}/../root1r/c.py"}, "project_root": "{project_root}"})
          and "plan" in refusal({"plan": "{task_root}/../../../../root1r/x.json"})
          and "plan" in refusal({"plan": "{plugin_root}/../../root1r/x.json"}))
    inside = run({"plan": "{project_root}/qa-factory/../qa-factory/x.json", "tok": "{task_root}/work/../work/y.json"})
    check("K1 F1 RUN: a `..` that stays inside its root is dispatched unchanged (resolved text, no refusal)",
          inside["plan"] == str(Path(str(project), "qa-factory", "..", "qa-factory", "x.json"))
          and inside["tok"] == str(Path(str(task), "work", "..", "work", "y.json")), str(inside))
    check("K1 F1 RUN: a packet with no `..` is not touched by the guard",
          run({"plan": "{project_root}/qa-factory/x.json"})["plan"] == str(project / "qa-factory" / "x.json"))
    # one predicate: the same inputs, READ and RUN, agree
    for value in ("{project_root}/../root1r/qa-factory/x.json", "{project_root}/qa-factory/../qa-factory/x.json"):
        with quiet():
            kept = "k" in runtime_paths.state_paths({"k": value, "project_root": str(project)}, task, project=project, plugin=PACKAGE)
        check(f"K1 F1 READ and RUN agree on `{value}` (kept in a role packet exactly when dispatched)", kept == (refusal({"k": value}) == ""))
    source = (harness.SCRIPTS / "runtime_paths.py").read_text(encoding="utf-8")
    check("K1 F1: there is ONE `..` test in runtime_paths.py (a second one is a second predicate)", source.count('".." in') == 1, str(source.count('".." in')))


def k1_unc() -> None:
    """Critic F2: a UNC value or hint paid the network on every process (measured 3-7.5 s, and the hook is a new process on
    every dispatch). A different drive or share is answered from the text, before any filesystem call. The test replaces
    `os.path.realpath` with a recorder that never touches the network, and counts what reached it."""
    if os.name != "nt":
        print("skipped (not nt): the UNC key of K1 did not run")
        return
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    unc = chr(92) * 2 + "qa-nohost-t365" + chr(92) + "share"
    seen = []
    real = os.path.realpath

    def spy(path, *args, **kwargs):
        text = os.fspath(path)
        if text[:2] in (chr(92) * 2, "//"):
            seen.append(text)
            return text
        return real(path, *args, **kwargs)

    os.environ["CLAUDE_PROJECT_DIR"] = str(base)
    hooklib._PROJECT_ROOT_CACHE = None
    reset_notes()
    os.path.realpath = spy
    try:
        inside = runtime_paths.contained(unc + chr(92) + "x", project)
        over = runtime_paths.contained(project / "x", unc)
        with quiet():
            found = runtime_paths.project_for_task(task, hint=unc + chr(92) + "proj")
            got = runtime_paths.state_paths({"project_root": unc + chr(92) + "proj", "stray": chr(92) * 2 + "other-host" + chr(92) + "s" + chr(92) + "f.json"},
                                            task, plugin=PACKAGE)
        untouched = list(seen)
        same_share = runtime_paths.contained(unc + chr(92) + "a" + chr(92) + "b", unc + chr(92) + "a")
        shared = list(seen)
    finally:
        os.path.realpath = real
    check("K1 F2: a UNC value against a drive-letter root, and a drive-letter path against a UNC root, are 'not inside' - and `realpath` never saw a UNC path",
          inside is False and over is False and untouched == [], str(untouched))
    check("K1 F2: a UNC hint is not asked (the project is found from the story's own place); a UNC stray value is left out",
          found == project and "stray" not in got and got["project_root"] == str(project), str(got)[:200])
    check("K1 F2: two UNC paths of the SAME share still go through realpath (and are inside)", same_share is True and len(shared) > len(untouched), str(shared))
    other = "Z:" if not str(project).upper().startswith("Z:") else "Y:"
    check("K1 F2: the drive letter is compared folded (c: against C:), another drive is not inside",
          runtime_paths.contained(str(project / "x").lower(), str(project).upper())
          and not runtime_paths.contained(other + chr(92) + "x", project))
    restore_process()


def k1_lazy_candidates() -> None:
    """Critic twins: `hooklib.project_root` may shell out to git for up to 10 s, so it is a LAZY candidate - called only
    when the nearest folder above the story did not hold it. A monkeypatched counter, never a clock (FR-31)."""
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    home = make_project(base, "home", {"artifact_root": str(base / "stories")})
    outside = base / "stories" / TASK
    outside.mkdir(parents=True)
    calls = []
    real = hooklib.project_root
    hooklib.project_root = lambda *args, **kwargs: calls.append(1) or real(*args, **kwargs)
    os.environ["CLAUDE_PROJECT_DIR"] = str(home)
    hooklib._PROJECT_ROOT_CACHE = None
    reset_notes()
    try:
        with quiet():
            first = runtime_paths.project_for_task(task, hint=str(home))
            after_first = len(calls)
            second = runtime_paths.project_for_task(outside)
            after_second = len(calls)
            runtime_paths.state_paths({"project_root": str(home), "root": str(task)}, task, plugin=PACKAGE)
            after_state = len(calls)
            try:
                runtime_paths.project_for_task(base / "nowhere")
            except ValueError:
                pass
            after_refusal = len(calls)
    finally:
        hooklib.project_root = real
    check("K1 lazy: the nearest folder holds the story -> `hooklib.project_root` is NOT called (0 calls), also through state_paths",
          first == project and after_first == 0 and after_state == after_second, f"{first} {after_first} {after_second} {after_state}")
    check("K1 lazy: ...it is called (once) only when the earlier candidate did not hold the story", second == home and after_second == 1, str(after_second))
    check("K1 lazy: ...and once on the way to a refusal", after_refusal == after_state + 1, str(after_refusal))
    restore_process()


def k1_nested_subset() -> None:
    """Critic F5, the Lead's decision: the subset rule holds at EVERY level. A nested map carries only the names the stored map
    has there; a name that cannot be recomputed is left out AND named in the note; an empty stored map stays empty."""
    base = scratch()
    project = make_project(base, "proj", {"code_repos": [{"id": "known", "path": "repos/known"}]})
    task = task_of(project)
    X = base / "pkgX" / "qa-factory"
    stored = {"project_root": str(project), "entrypoints": {"controller": str(X / "scripts" / "controller.py")},
              "repository_roots": {"a": str(base / "elsewhere" / "a"), "known": str(base / "old" / "known")}, "extra": {}}
    reset_notes()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = runtime_paths.state_paths(stored, task, project=project, plugin=PACKAGE)
    check("K1 F5: `entrypoints` with ONE stored name comes back with that ONE name (the running package's), not nine",
          got["entrypoints"] == {"controller": str(PACKAGE / "scripts" / "controller.py")}, str(got["entrypoints"]))
    check("K1 F5: `repository_roots`: the name the config has is recomputed, the name it has not is left out",
          got["repository_roots"] == {"known": str(project / "repos" / "known")}, str(got["repository_roots"]))
    check("K1 F5: ...and the omission note names it as `repository_roots.a`", "repository_roots.a=" in err.getvalue() and "repository_roots.known" not in err.getvalue(), err.getvalue()[:300])
    check("K1 F5: a stored EMPTY nested map stays `{}`, and the order of keys is the stored order",
          got["extra"] == {} and list(got) == ["project_root", "entrypoints", "repository_roots", "extra"], str(list(got)))
    only_a = {"project_root": str(project), "repository_roots": {"a": str(base / "elsewhere" / "a")},
              "entrypoints": {"nosuch": str(X / "scripts" / "nosuch.py")}}
    reset_notes()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = runtime_paths.state_paths(only_a, task, project=project, plugin=PACKAGE)
    check("K1 F5: a stored `repository_roots {'a'}` whose `a` cannot be resolved comes back `{}` (not the config's other names), "
          "an entrypoint name the package has not is left out - both named in the note",
          got["repository_roots"] == {} and got["entrypoints"] == {} and "repository_roots.a=" in err.getvalue() and "entrypoints.nosuch=" in err.getvalue(),
          f"{got} {err.getvalue()[:300]}")
    reset_notes()
    with quiet():
        got = runtime_paths.state_paths({"project_root": str(project), "repository_roots": {}, "entrypoints": {}}, task, project=project, plugin=PACKAGE)
    check("K1 F5: empty stored `repository_roots` and `entrypoints` stay empty", got["repository_roots"] == {} and got["entrypoints"] == {}, str(got))


def k1_note_labels() -> None:
    """Critic F6: the omission note names EVERY omitted label; only values are cut (120 characters each)."""
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    foreign = base / "elsewhere"
    labels = [f"label-{index:02d}-" + "k" * 70 for index in range(12)]
    stored = {"project_root": str(project)}
    stored.update({label: str(foreign / ("v" * 300) / label) for label in labels})
    reset_notes()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = runtime_paths.state_paths(stored, task, project=project, plugin=PACKAGE)
    note = err.getvalue()
    check("K1 F6: all 12 long labels are named in the note (a label is never cut, even past 200 characters of note)",
          all(f"{label}=" in note for label in labels) and len(note) > 1000 and not [label for label in labels if label in got], f"{len(note)} {note[:200]}")
    values = re.findall(r"label-\d\d-k+=(.*?\.\.\.\(\d+ characters\))", note)
    check("K1 F6: ...and each VALUE is cut at 120 characters (with the length said)",
          len(values) == 12 and all(len(value) <= runtime_paths.VALUE_MAX + 24 for value in values), str([len(v) for v in values]))


def k1_open_token_text() -> None:
    """Critic F7: the refusal for a token with no root names the token, where it was met and what was expected (FR-1)."""
    import human_text
    base = scratch()
    project = make_project(base, "proj")
    try:
        runtime_paths.known_paths_for_dispatch({"plan": "{task_root}/work/x.json", "project_root": "{project_root}"}, project_root=project,
                                               plugin_root=PACKAGE, python=sys.executable, door="THE DOOR", task_root=None)
        said = ""
    except ValueError as exc:
        said = str(exc)
    check("K1 F7: the open-token refusal names the token, the key, the tokens this process does have, and the door",
          "{task_root}" in said and "(in plan)" in said and "{project_root}" in said and "{plugin_root}" in said and "{python}" in said
          and "absolute path" in said and "THE DOOR" in said, said[:300])
    own = said.split(" Nothing was dispatched")[0]
    # it reaches the controller's log, not a person, so it is no QUESTION: rule 5 (a how-to-answer block) is the one rule that does not
    # apply; every other rule (form-field names, plugin paths, dispatch ids, internal row ids) must hold
    rest = [problem for problem in human_text.problems(own) if problem["rule"] != "no_how_to_answer"]
    check("K1 F7: its own sentence breaks no rule of `human_text` except the question-only one (FR-1, FR-6)", rest == [], str(rest)[:300])


def k9_baseline_relabel() -> None:
    """Critic F9: the F3 system.md rows (B-207..209) and the F4 packet rows (B-242..244) name this project's own paths by design,
    so they leave with the stored form (N2), not with N1; the baseline stays valid and shrink-only (no row added or removed)."""
    import state_census as C
    data = json.loads(C.BASELINE_FILE.read_text(encoding="utf-8"))
    problem = ""
    try:
        C.validate_baseline(data, C.BASELINE_FILE)
    except C.BaselineInvalid as exc:
        problem = str(exc)
    rows = {row["id"]: row for row in data["rows"]}
    ids = ["B-207", "B-208", "B-209", "B-242", "B-243", "B-244"]
    check("K9 baseline: `validate_baseline` passes on the shipped baseline", problem == "", problem[:200])
    check("K9 baseline (F9): the six rows are relabelled `leaves_at: N2`", [rows[i]["leaves_at"] for i in ids] == ["N2"] * 6, str([rows[i]["leaves_at"] for i in ids]))
    writers = {(entry["file"], entry["inventory_row"]): entry["leaves_at"] for entry in data["file_writers"]}
    check("K9 baseline (F9): the two `file_writers` entries that map those rows say N2 too (a `--write-baseline` rebuild must give the shipped words)",
          writers[("<PROJECT>/qa-factory/artifacts/<TASK>/state/driver-tmp/<DISPATCH>.system.md", "new-9")] == "N2"
          and writers[("<STDOUT>/inject_context hook", "#1+#2")] == "N2", str(writers)[:200])
    broken = copy.deepcopy(data)
    broken["rows"][0]["leaves_at"] = "N999"
    check("K9 baseline (control): a row with a node outside the legend IS refused", _refused_with(C, broken))


def _refused_with(C, data) -> bool:
    try:
        C.validate_baseline(data, "control")
    except C.BaselineInvalid:
        return True
    return False


# --- K2 / K3 / K6: the move ---------------------------------------------------------------------------------------

def build_moved_story(base: Path, name2: str, cfg: dict | None = None) -> tuple:
    """root1 holds a story `initialize`d with story_run-shaped absolute `known_paths` (the plugin is a fake X) and a running
    scout dispatch; root2 is a byte copy of it. root1 stays on disk as a valid project (E2)."""
    root1 = make_project(base, "copy-a", dict({"cases_root": "cases"}, **(cfg or {})))
    task1 = task_of(root1)
    X = base / "pkgX7Q" / "qa-factory"
    known = runtime_paths.known_paths(task1, project=root1, plugin=X, python=sys.executable)
    os.environ[SKIP] = "1"
    controller = init_story(task1, known)
    request = controller.prepare({"stage": "S0", "role": ROLE, "id": f"S0-{ROLE}-1"})["dispatch_request"]
    controller.apply("dispatch", request)
    root2 = (base / name2).resolve()
    shutil.copytree(root1, root2)
    return root1, task1, root2, task_of(root2), X


def k2_the_move(label: str, name2: str) -> None:
    base = scratch()
    root1, task1, root2, task2, X = build_moved_story(base, name2)
    check(f"K2 {label} fixture: the copy still STORES root1 and X (the state is immutable) and root1 is a valid project on disk",
          json.loads((task2 / "state" / "controller.json").read_text(encoding="utf-8"))["known_paths"]["project_root"] == str(root1)
          and (root1 / "qa-factory" / "config.json").is_file())
    before1 = listing(root1)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root2)
    hooklib._PROJECT_ROOT_CACHE = None
    reset_notes()
    with quiet():
        located = contract._config_location(task2)
        cases = contract.cases_root(task2)
    check(f"K2a {label}: `_config_location(task2)` is root2's config, strict", located == (root2 / "qa-factory" / "config.json", root2, True), str(located))
    check(f"K2a {label}: `cases_root(task2)` is under root2 (before N1 it wrote case documents into root1)", cases == root2 / "cases", str(cases))
    os.environ.pop(SKIP, None)
    with quiet():
        receipt = dashboard_refresh.refresh_for_task(task2)
    check(f"K2b {label}: `refresh_for_task(task2)` writes root2's dashboard receipt",
          receipt.get("status") == "current" and (root2 / "qa-factory" / "state" / "dashboard-refresh.json").is_file(), str(receipt))
    check(f"K2b {label}: ...and the listing of root1/qa-factory (names, mtime_ns, sizes) is unchanged", listing(root1) == before1)
    os.environ[SKIP] = "1"
    driver = make_driver(root2)
    reset_notes()
    driver_err = io.StringIO()
    with contextlib.redirect_stderr(driver_err):
        sysfile = driver.system_file(ROLE, "dsys", [])
        driver.system_file(ROLE, "dsys-again", [])
    stale = [line for line in driver_err.getvalue().splitlines() if line.startswith("project:")]
    check(f"K2c {label} F4: the driver (it passes `project=`) says ONCE that the stored root is replaced, naming both, even though it ran twice",
          len(stale) == 1 and str(root1) in stale[0] and str(root2) in stale[0], driver_err.getvalue()[:300])
    text = sysfile.read_text(encoding="utf-8")
    packet = packet_after(text)
    check(f"K2c {label}: the driver's role packet carries root2 and the `--plugin-dir` package",
          packet["known_paths"]["project_root"] == str(root2) and packet["known_paths"]["plugin_root"] == str(PACKAGE)
          and packet["known_paths"]["task_root"] == str(task2), str(packet["known_paths"])[:300])
    check(f"K2c {label}: ...and names neither root1 nor X in any spelling (raw, forward slashes, JSON-escaped, lowercase)",
          not leaks(text, [root1, X]), str(leaks(text, [root1, X])))
    restore_process()
    os.environ[SKIP] = "1"
    reset_notes()
    code, prompt, err = hook_prompt(root2)
    hook = packet_after(prompt) if prompt else {}
    # RC1-14 part 2 N1: the packet holds ONE `known_paths` (the top-level map, the record's resolved paths laid over the state's);
    # the dispatch it prints is the whitelisted projection of the record and carries none
    check(f"K2d {label}: the hook's packet carries root2 and the hook's package, in its one `known_paths` (the dispatch projection holds none)",
          code == 0 and hook.get("known_paths", {}).get("project_root") == str(root2)
          and hook["known_paths"]["plugin_root"] == str(PACKAGE)
          and "known_paths" not in (hook.get("dispatch") or {"known_paths": 1})
          and hook["known_paths"]["task_root"] == str(task2), f"{code} {err[:200]} {str(hook)[:300]}")
    check(f"K2d {label}: ...and no spelling of root1 or X is in the whole prompt", not leaks(prompt, [root1, X]), str(leaks(prompt, [root1, X])))
    stale = [line for line in err.splitlines() if line.startswith("project:")]
    check(f"K2d {label} F4: the hook (it passes `project=`) prints ONE stale-hint line naming the stored root and the one used, on stderr",
          len(stale) == 1 and str(root1) in stale[0] and str(root2) in stale[0], err[:400])
    check(f"K2 {label}: the old copy's tree was not touched by any reader (names, mtime_ns, sizes)", listing(root1) == before1)
    restore_process()


def k2e_outside_any_project() -> None:
    base = scratch()
    home = make_project(base, "home", {"artifact_root": str(base / "stories")})
    stories = base / "stories"
    task = stories / TASK
    task.mkdir(parents=True)
    os.environ[SKIP] = "1"
    os.environ["CLAUDE_PROJECT_DIR"] = str(home)
    hooklib._PROJECT_ROOT_CACHE = None
    controller = init_story(task, {"root": str(task), "project_root": str(home)})
    os.environ["CLAUDE_PROJECT_DIR"] = str(base)              # no project of the process: only the hint can say
    hooklib._PROJECT_ROOT_CACHE = None
    packet = controller.prepare({"stage": "S0"})
    check("K2e: on a task outside any project, `prepare` works with a valid stored hint (its artifact root contains the task)",
          packet["resolved_paths"]["project_root"] == str(home), str(packet["resolved_paths"])[:200])
    wrong = make_project(base, "wrong")
    task_b = base / "stories-b" / TASK
    task_b.mkdir(parents=True)
    controller_b = init_story(task_b, {"root": str(task_b), "project_root": str(wrong)})
    try:
        controller_b.prepare({"stage": "S0"})
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K2e: ...and with the hint set to a project whose artifact root does not contain the task it REFUSES, naming `--project`",
          "--project" in refused and str(task_b) in refused, refused[:300])
    restore_process()


def k3_other_projects_root() -> None:
    base = scratch()
    root1, task1, root2, task2, X = build_moved_story(base, "copy-b")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root2))
    env[SKIP] = "1"
    proc = harness.run_script("controller.py", "--task-root", task2, "--operation", "recover", cwd=root2, env=env)
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    notes = [line for line in lines if str(root1) in line]
    parsed = True
    try:
        json.loads(proc.stdout)
    except ValueError:
        parsed = False
    check("K3: a controller CLI run from the copy exits 0 and its stdout still parses as JSON (FR-14)", proc.returncode == 0 and parsed,
          f"{proc.returncode} {proc.stderr[-300:]} {proc.stdout[:200]}")
    check("K3: ...ONE stderr line names the stored root (root1) and the one used (root2)",
          len(notes) == 1 and str(root2) in notes[0], str(lines)[:600])
    check("K3: ...and root1 / X appear nowhere in stdout", not leaks(proc.stdout, [root1, X]), str(leaks(proc.stdout, [root1, X])))
    restore_process()


# --- K4: absent and legacy hints ----------------------------------------------------------------------------------

def k4_absent_and_legacy() -> None:
    base = scratch()
    project = make_project(base, "proj", {"cases_root": "cases"})
    task = task_of(project)
    state = task / "state"
    state.mkdir(parents=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    missing = base / "gone" / "project"
    shapes = [("known_paths absent", {"revision": 1}), ("known_paths {}", {"revision": 1, "known_paths": {}}),
              ("a legacy list", {"revision": 1, "known_paths": ["a/b"]}), ("a number", {"revision": 1, "known_paths": 4}),
              ("project_root null", {"revision": 1, "known_paths": {"project_root": None}}),
              ("a stored root that is not on this machine", {"revision": 1, "known_paths": {"project_root": str(missing)}})]
    for label, content in shapes:
        (state / "controller.json").write_text(json.dumps(content), encoding="utf-8")
        reset_notes()
        err = io.StringIO()
        receipts = []
        real = dashboard_refresh.refresh_project
        dashboard_refresh.refresh_project = lambda p: receipts.append(Path(p)) or {"status": "skipped"}
        try:
            with contextlib.redirect_stderr(err):
                located = contract._config_location(task)
                cases = contract.cases_root(task)
                dashboard_refresh.refresh_for_task(task)
        except Exception as exc:                                  # noqa: BLE001
            located, cases = exc, exc
        finally:
            dashboard_refresh.refresh_project = real
        check(f"K4 ({label}): every reader works - the config is the project's, `cases_root` raises no FileNotFoundError, the refresh goes to the project",
              located == (project / "qa-factory" / "config.json", project, True) and cases == project / "cases" and receipts == [project],
              f"{located!r} {cases!r} {receipts}")
        if "not on this machine" in label:
            check("K4 (a stored root that is not on this machine): recomputed, and ONE note says so", len([l for l in err.getvalue().splitlines() if str(missing) in l]) == 1,
                  err.getvalue()[:300])
        else:
            check(f"K4 ({label}): no hint, so no note and no refusal", err.getvalue() == "", err.getvalue()[:200])
    os.environ["CLAUDE_PROJECT_DIR"] = str(base)
    hooklib._PROJECT_ROOT_CACHE = None
    other_task = base / "x" / "task"
    other_task.mkdir(parents=True)
    (other_task / "state").mkdir()
    (other_task / "state" / "controller.json").write_text(json.dumps({"known_paths": ["a"]}), encoding="utf-8")
    reset_notes()
    with quiet():
        found = contract._config_location(other_task)
    check("K4: a legacy state of a task outside any project falls to the hook layer, non-strict (as before N1), no exception",
          found[2] is False, str(found))
    restore_process()


# --- K5 / K6: the same place changes nothing, and nothing is written ---------------------------------------------

def k5_same_place() -> None:
    base = scratch()
    project = make_project(base, "proj", {"cases_root": "cases"})
    task = task_of(project)
    os.environ[SKIP] = "1"
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    driver = make_driver(project)
    stored = driver.known_paths()
    controller = init_story(task, stored)
    controller.apply("dispatch", controller.prepare({"stage": "S0", "role": ROLE, "id": f"S0-{ROLE}-1"})["dispatch_request"])
    state = json.loads((task / "state" / "controller.json").read_text(encoding="utf-8"))
    hashes = {name: sha(task / "state" / name) for name in ("events.jsonl", "controller.json")}
    tree = listing(task)
    reset_notes()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        again = runtime_paths.state_paths(state["known_paths"], task, project=project, plugin=driver.plugin, python=sys.executable)
        resolved = runtime_paths.state_paths(state["known_paths"], task, plugin=driver.plugin, python=sys.executable)
    check("K5: on an unmoved driver story `state_paths(stored) == stored` EXACTLY - keys, order, values",
          again == state["known_paths"] and list(again) == list(state["known_paths"]) and json.dumps(again) == json.dumps(state["known_paths"]),
          str(set(again.items()) ^ set(state["known_paths"].items()))[:300])
    check("K5: ...also when the reader finds the project itself (the stored root is the hint, and it is the same place)", resolved == again)
    check("K5: `_config_location` returns the tuple it returned before N1 (config, root, strict)",
          contract._config_location(task) == (project / "qa-factory" / "config.json", project, True))
    seen = []
    real = dashboard_refresh.refresh_project
    dashboard_refresh.refresh_project = lambda p: seen.append(Path(p)) or {"status": "skipped"}
    try:
        dashboard_refresh.refresh_for_task(task)
    finally:
        dashboard_refresh.refresh_project = real
    check("K5: `refresh_for_task` refreshes the same project", seen == [project], str(seen))
    check("K5: ...and no note was printed by any of them (a hint that is the same place is no news)", err.getvalue() == "", err.getvalue()[:200])
    with quiet():
        sysfile = driver.system_file(ROLE, "dsame", [])
    text = sysfile.read_text(encoding="utf-8")
    check("K5: the driver's packet `known_paths` is byte-identical to the stored map", json.dumps(packet_after(text)["known_paths"]) == json.dumps(state["known_paths"]))
    restore_process()
    os.environ[SKIP] = "1"
    code, prompt, herr = hook_prompt(project)
    hook = packet_after(prompt) if prompt else {}
    stored = [d for d in state["dispatches"].values() if d.get("role") == ROLE][-1]
    shown = hook.get("dispatch") or {}
    # E10 (one top-level map: the state's resolved paths, the record's laid over them): on the same place every key the state
    # stores keeps its stored value, and the only others are the keys the RECORD's own map adds (entrypoints, the package stamp)
    known_ok = (all(hook["known_paths"].get(k) == v for k, v in state["known_paths"].items())
                and set(hook["known_paths"]) == set(state["known_paths"]) | set(stored.get("known_paths") or {}))
    check("K5: the hook's packet `known_paths` keeps every stored value and adds only the record's own keys, and the dispatch it prints is the projection "
          "of the stored record (id, stage, role, scope as stored, kind `first`, no `known_paths`, every other key the record's own)",
          code == 0 and known_ok
          and all(shown.get(k) == stored.get(k) for k in ("id", "stage", "role", "scope")) and shown.get("kind") == "first"
          and "known_paths" not in shown and all(stored.get(k) == v for k, v in shown.items() if k != "kind"),
          f"{code} {herr[:200]} {str(hook.get('dispatch'))[:200]} known-vs-stored differ on {sorted(k for k in set(hook.get('known_paths') or {}) | set(state['known_paths']) if (hook.get('known_paths') or {}).get(k) != state['known_paths'].get(k))}")
    check("K5 F4: on the same place the hook prints no stale-hint line (the stored root IS the project)", not [line for line in herr.splitlines() if line.startswith("project:")], herr[:200])
    after = {name: sha(task / "state" / name) for name in ("events.jsonl", "controller.json")}
    check("K6 FR-45: events.jsonl and controller.json have the same sha256 before and after every reader call", after == hashes, f"{hashes} {after}")
    created = [row[0] for row in listing(task) if row not in tree]
    check("K6 FR-45: the readers created no file in the story beyond the driver's own packet file (driver-tmp/)",
          all(name.startswith("state/driver-tmp/") for name in created), str(created))
    restore_process()
    # the 8.3 spelling of the same place (iii): equal after realpath, no note
    long_base = scratch()
    long_project = make_project(long_base, "a-project-folder-with-a-long-name")
    long_task = task_of(long_project)
    short = short_name(long_project)
    if short is None:
        print("skipped: no 8.3 alias - the 8.3 key of K5 did not run")
    else:
        driver_known = runtime_paths.known_paths(long_task, project=long_project, plugin=PACKAGE, python=sys.executable)
        spelled = {key: (value.replace(str(long_project), short) if isinstance(value, str) else value) for key, value in driver_known.items()}
        reset_notes()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = runtime_paths.state_paths(spelled, long_task, plugin=PACKAGE, python=sys.executable)
        check("K5 8.3: a hint under the 8.3 spelling of the same place resolves to the stored map after normalisation (realpath of every value), with no note",
              set(got) == set(spelled) and all(os.path.realpath(got[key]) == os.path.realpath(spelled[key]) for key in got if isinstance(got[key], str)
                                               and runtime_paths._local_abs(got[key])) and err.getvalue() == "", err.getvalue()[:200])
    restore_process()


# --- K7: the sentinel ---------------------------------------------------------------------------------------------

PATH_KEYS = "project_root|plugin_root|task_root|root|scripts_root|python_executable|entrypoints|repository_roots"
# `\)?` after `or {}`: the codebase's own idiom is `(state.get("known_paths") or {}).get("project_root")` (critic F3)
DIRECT = re.compile(r"""get\(\s*["']known_paths["'][^)]*\)\s*(?:or\s*\{\}\s*)?\)?\s*(?:\.get\(\s*|\[\s*)["'](%s)["']""" % PATH_KEYS)
INDEXED = re.compile(r"""\[\s*["']known_paths["']\s*\]\s*(?:\.get\(\s*|\[\s*)["'](%s)["']""" % PATH_KEYS)
ALIAS = re.compile(r"""^\s*(\w+)\s*=\s*.*["']known_paths["']""")
# the files that own the state's own writers and validators; their reads feed `project_for_task` as hints (reader #5)
ALLOWED = {"controller.py": "the state machine: initialize/dispatch writers, validate, and prepare's hint for project_for_task",
           "runtime_paths.py": "the resolver itself"}


def sentinel_hits(name: str, text: str) -> list:
    """The lines of one script that read a controller state's `known_paths` for a location: `state.get("known_paths",
    {}).get("project_root")`, `state["known_paths"]["root"]`, or an alias (`known = ...known_paths...`) whose next 15 lines
    index a path key."""
    lines, hits = text.splitlines(), []
    for index, line in enumerate(lines):
        if DIRECT.search(line) or INDEXED.search(line):
            hits.append((name, index + 1, line.strip()))
            continue
        alias = ALIAS.match(line)
        if alias:
            var = re.escape(alias.group(1))
            use = re.compile(r"""\b%s\b(?:\.get\(\s*|\[\s*)["'](%s)["']""" % (var, PATH_KEYS))
            # `hint=stored.get("project_root")` is the ONE sanctioned reading: it is handed to `project_for_task`, which
            # adopts it only after the story's own place and its artifact root have said yes
            if any(use.search(later) and not re.search(r"\bhint\s*=", later) for later in lines[index + 1:index + 16]):
                hits.append((name, index + 1, line.strip()))
    return hits


def k7_sentinel() -> None:
    found = []
    scripts = sorted(path for path in harness.SCRIPTS.glob("*.py") if path.name not in ALLOWED)
    for path in scripts:
        found += sentinel_hits(path.name, path.read_text(encoding="utf-8"))
    check(f"K7 sentinel: no script outside the allow-list ({len(scripts)} scanned, allow-list {sorted(ALLOWED)}) reads a state's known_paths for a location",
          found == [], str(found))
    check("K7 sentinel (positive control): the direct form `state.get(\"known_paths\", {}).get(\"project_root\")` is flagged",
          sentinel_hits("fixture.py", 'raw = state.get("known_paths", {}).get("project_root")\n') != [])
    check("K7 sentinel (positive control, F3): the parenthesised-or idiom `(state.get(\"known_paths\") or {}).get(\"project_root\")` is flagged",
          sentinel_hits("fixture.py", 'raw = (state.get("known_paths") or {}).get("project_root")\n') != [])
    check("K7 sentinel (positive control): the indexed form and an alias form are flagged",
          sentinel_hits("fixture.py", 'x = state["known_paths"]["plugin_root"]\n') != []
          and sentinel_hits("fixture.py", 'known = state.get("known_paths") or {}\nuse = known.get("project_root")\n') != [])
    check("K7 sentinel (negative control): handing the stored map to the resolver, or reading a list of manifest paths, is not flagged",
          sentinel_hits("fixture.py", 'k = state_paths(state.get("known_paths", {}), task)\nm = manifest.get("known_paths") or []\n') == [])
    old_reader = (harness.SCRIPTS / "dashboard_refresh.py").read_text(encoding="utf-8").replace(
        "stored.get(\"project_root\") if isinstance(stored, dict) else None", "None").replace(
        "stored = state.get(\"known_paths\") if isinstance(state, dict) else None",
        "raw = state.get(\"known_paths\", {}).get(\"project_root\")")
    check("K7 sentinel (differential): the sentinel flags dashboard_refresh.py as it was before N1", sentinel_hits("dashboard_refresh.py", old_reader) != [])


# --- K8: Q6 -------------------------------------------------------------------------------------------------------

def k8_leftovers() -> None:
    base = scratch()
    project = make_project(base, "proj", {"code_repos": [{"id": "backend", "path": "../repos-backend"}]})
    repo = base / "repos-backend"             # a checkout BESIDE the project: under none of the packet's roots
    task = task_of(project)
    os.environ[SKIP] = "1"
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    controller = init_story(task, {"root": str(task), "project_root": str(project)})
    request = controller.prepare({"stage": "S0", "role": ROLE, "id": f"S0-{ROLE}-1"})["dispatch_request"]
    known = request["known_paths"]
    check("K8 fixture: a tokenised packet from `prepare` keeps the repository root absolute (it is under no root of ours)",
          known["project_root"] == "{project_root}" and known["repository_roots"] == {"backend": str(repo)}, str(known)[:300])
    old_machine = base / "old-machine"
    stale = copy.deepcopy(request)
    stale["known_paths"]["repository_roots"] = {"backend": str(old_machine / "testproject1")}
    stale["known_paths"]["entrypoints"]["controller"] = str(old_machine / "pkg" / "scripts" / "controller.py")
    stale["known_paths"]["scripts_root"] = str(old_machine / "pkg" / "scripts")
    controller.apply("dispatch", stale)
    kept = controller.state()["dispatches"][f"S0-{ROLE}-1"]["known_paths"]
    check("K8: repository_roots, entrypoints and scripts_root are RECOMPUTED from the current config and package, never kept stale",
          kept["repository_roots"] == {"backend": str(repo)}
          and kept["entrypoints"]["controller"] == str(PACKAGE / "scripts" / "controller.py") and kept["scripts_root"] == str(PACKAGE / "scripts"),
          str(kept)[:400])
    check("K8: ...and no stale spelling is recorded", not leaks(json.dumps(kept), [old_machine]), str(kept)[:200])
    controller.apply("checkpoint", {"id": f"S0-{ROLE}-1", "status": "paused", "reason": "x", "checkpoint": {"remaining": ["TC-1"]},
                                    "counters": {"active_seconds": 0, "requests": 0, "output_tokens": 0, "repair_cycles": 0},
                                    "idempotency_key": "cp-1"})
    events = len(controller.store.read())
    odd = dict(copy.deepcopy(request), id=f"S0-{ROLE}-2", idempotency_key="dispatch:odd", expected_revision=controller.state()["revision"])
    odd["known_paths"]["stray"] = str(old_machine / "somewhere" / "file.json")
    try:
        controller.apply("dispatch", odd)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K8: any OTHER absolute leftover that is not on this machine is refused, naming it, with the `prepare` door and 'Nothing was dispatched'",
          str(old_machine / "somewhere" / "file.json") in refused and "--operation prepare" in refused and "Nothing was dispatched" in refused, refused[:400])
    check("K8: ...and nothing was recorded", len(controller.store.read()) == events)
    odd["known_paths"]["stray"] = str(base)                    # a leftover that EXISTS here passes as it is
    odd["idempotency_key"] = "dispatch:odd-2"
    controller.apply("dispatch", odd)
    check("K8 control: an absolute leftover that IS on this machine is dispatched as it is",
          controller.state()["dispatches"][f"S0-{ROLE}-2"]["known_paths"]["stray"] == str(base))
    events = len(controller.store.read())
    climb = dict(copy.deepcopy(request), id=f"S0-{ROLE}-3", idempotency_key="dispatch:climb", expected_revision=controller.state()["revision"])
    climb["known_paths"]["stray"] = "{project_root}/../root1r/qa-factory/x.json"
    try:
        controller.apply("dispatch", climb)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K8 F1: through the controller, a token path climbing out of {project_root} is refused with the `prepare` door and records nothing",
          "climbs out" in refused and "--operation prepare" in refused and "Nothing was dispatched" in refused and len(controller.store.read()) == events, refused[:300])
    restore_process()


# --- K9: the memo -------------------------------------------------------------------------------------------------

def k9_memo() -> None:
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    os.environ[SKIP] = "1"
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    init_story(task, {"root": str(task), "project_root": str(project)})
    calls = []
    real_find, real_clock = runtime_paths.project_for_task, contract._CASE_CONFIG_CLOCK
    ticks = itertools.count(0, 10)                              # every call is past the 2 s window: counted, never timed
    runtime_paths.project_for_task = lambda *args, **kwargs: calls.append(1) or real_find(*args, **kwargs)
    contract._CASE_CONFIG_CLOCK = lambda: next(ticks)
    try:
        reset_notes()
        for _ in range(100):
            contract.case_id_forms(task)
        first = len(calls)
        state_file = task / "state" / "controller.json"
        state_file.write_text(state_file.read_text(encoding="utf-8") + " ", encoding="utf-8")       # a new stat key
        for _ in range(100):
            contract.case_id_forms(task)
    finally:
        runtime_paths.project_for_task, contract._CASE_CONFIG_CLOCK = real_find, real_clock
        contract.case_config_reset()
    check("K9 cache (B-013): `project_for_task` runs ONCE per controller.json stat key across 100 `case_id_forms` calls, and once more when the file changes",
          first == 1 and len(calls) == 2, f"{first} {len(calls)}")
    restore_process()


# --- K10: a plugin update mid-story -------------------------------------------------------------------------------

def k10_plugin_update() -> None:
    base = scratch()
    project = make_project(base, "proj")
    task = task_of(project)
    os.environ[SKIP] = "1"
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    other_package = base / "pkgOLD" / "qa-factory"
    stamp = "0123456789ab" + "f" * 52
    runtime = runtime_paths.resolve_runtime(task, project)
    orchestrator = dict(runtime, plugin_root=str(other_package), scripts_root=str(other_package / "scripts"),
                        entrypoints={name: str(other_package / "scripts" / (name + ".py")) for name in runtime["entrypoints"]},
                        package_fingerprint=stamp, package_version="0.0.1-old")
    controller = init_story(task, orchestrator)
    controller.apply("dispatch", controller.prepare({"stage": "S0", "role": ROLE, "id": f"S0-{ROLE}-1"})["dispatch_request"])
    reset_notes()
    err = io.StringIO()
    problems, read, prompt, code = [], {}, "", -1
    with contextlib.redirect_stderr(err):
        try:
            contract._config_location(task)
            contract.cases_root(task)
            dashboard_refresh.refresh_for_task(task)
            read = runtime_paths.state_paths(json.loads((task / "state" / "controller.json").read_text(encoding="utf-8"))["known_paths"], task, plugin=PACKAGE)
            driver = make_driver(project)
            driver.system_file(ROLE, "dold", [])
            restore_process()
            os.environ[SKIP] = "1"
            code, prompt, herr = hook_prompt(project)
            controller.prepare({"stage": "S0"})
        except Exception as exc:                                          # noqa: BLE001
            problems.append(f"{type(exc).__name__}: {exc}")
    check("K10: all the readers (config, refresh, state_paths, the driver's packet, the hook, prepare) read a state of ANOTHER package without a refusal",
          not problems and code == 0, str(problems)[:300])
    check("K10: ...`plugin_root` is the RUNNING package in every packet (never the stored one), the stored fingerprint is only copied",
          read["plugin_root"] == str(PACKAGE) and read["entrypoints"]["controller"] == str(PACKAGE / "scripts" / "controller.py")
          and read["package_fingerprint"] == stamp and packet_after(prompt)["known_paths"]["plugin_root"] == str(PACKAGE)
          and not leaks(prompt, [other_package]), str(read)[:200])
    old_request = dict(controller.prepare({"stage": "S0", "role": ROLE, "id": f"S0-{ROLE}-9"})["dispatch_request"])
    old_request["known_paths"] = dict(old_request["known_paths"], package_fingerprint=stamp, package_version="0.0.1-old")
    old_request["idempotency_key"] = "dispatch:old-package"
    controller.apply("checkpoint", {"id": f"S0-{ROLE}-1", "status": "paused", "reason": "x", "checkpoint": {"remaining": ["TC-1"]},
                                    "counters": {"active_seconds": 0, "requests": 0, "output_tokens": 0, "repair_cycles": 0},
                                    "idempotency_key": "cp-old"})
    old_request["expected_revision"] = controller.state()["revision"]
    try:
        controller.apply("dispatch", old_request)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("K10: a RUN packet stamped by another package is STILL refused, naming both fingerprints (the t-335 pins stand)",
          "0123456789ab" in refused and "0.0.1-old" in refused and "Nothing was dispatched" in refused, refused[:300])
    restore_process()


# --- K11: the dashboard's ancestor fallback (t-622, B-309 (d)) ---------------------------------------------------------

def k11_dashboard_fallback() -> None:
    """`refresh_for_task` asks `project_for_task` first; when no project ADMITS the story it falls back to the nearest
    marker ABOVE the story (`runtime_paths.nearest_project(task.parent)`). AT: a marker at the story itself is not taken
    (a story is not its own project); BEYOND: a marker at its parent is; a story that is the drive root has no parent."""
    base = scratch()
    os.environ["CLAUDE_PROJECT_DIR"] = str(base)                      # the process works in no project
    hooklib._PROJECT_ROOT_CACHE = None
    seen = []
    real = dashboard_refresh.refresh_project
    dashboard_refresh.refresh_project = lambda p: seen.append(Path(p)) or {"status": "skipped"}

    def story(folder: Path, marked_at: tuple) -> Path:
        task = folder / "QA-1"
        (task / "state").mkdir(parents=True)
        (task / "state" / "controller.json").write_text(json.dumps({"known_paths": {}}), encoding="utf-8")
        for where in marked_at:
            (where / "qa-factory").mkdir(parents=True, exist_ok=True)
            (where / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        return task

    def receipts(task: Path) -> tuple:
        del seen[:]
        with quiet():
            return dashboard_refresh.refresh_for_task(task), list(seen)

    try:
        holder = base / "holder"
        task = story(holder, (holder,))
        result, got = receipts(task)
        check("K11 BEYOND: a marker at the story's parent is taken (no project ADMITS the story, so the fallback finds it)",
              got == [holder.resolve()], f"{result} {got}")
        task_only = story(base / "alone", ())
        (task_only / "qa-factory").mkdir()
        (task_only / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        result, got = receipts(task_only)
        check("K11 AT: a marker only at the story itself is NOT taken - nothing is refreshed, `not_configured`",
              got == [] and result == {"status": "not_configured"}, f"{result} {got}")
        both_parent = base / "both"
        task_both = story(both_parent, (both_parent,))
        (task_both / "qa-factory").mkdir()
        (task_both / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        result, got = receipts(task_both)
        check("K11 AT+BEYOND: a marker at the story AND one above it: the one above is taken, never the story",
              got == [both_parent.resolve()], f"{result} {got}")
        result, got = receipts(story(base / "none", ()))
        check("K11 none: no marker anywhere above the story is `not_configured`", got == [] and result == {"status": "not_configured"}, f"{result} {got}")
        anchor = Path(Path.cwd().anchor)
        if (anchor / "qa-factory" / "config.json").exists() or (anchor / "state" / "controller.json").exists():
            print("skipped: K11 drive-root story - the drive root of this machine carries a marker or a controller state")
        else:
            result, got = receipts(anchor)
            check("K11 the story is the drive root: no parent, the result is `not_configured`", got == [] and result == {"status": "not_configured"},
                  f"{result} {got}")
    finally:
        dashboard_refresh.refresh_project = real
        restore_process()


def main() -> None:
    os.environ[SKIP] = "1"
    try:
        k1_containment()
        k1_alias_and_links()
        project_battery()
        k1_project_for_task()
        k1_tokens_and_notes()
        k1_state_paths_policy()
        k1_reroot_adversarial()
        k1_run_climb()
        k1_unc()
        k1_lazy_candidates()
        k1_nested_subset()
        k1_note_labels()
        k1_open_token_text()
        k9_baseline_relabel()
        k2_the_move("(an unrelated name)", "copy-b")
        k2_the_move("(root1 + r, E3)", "copy-ar")
        k2e_outside_any_project()
        k3_other_projects_root()
        k4_absent_and_legacy()
        k5_same_place()
        k7_sentinel()
        k8_leftovers()
        k9_memo()
        k10_plugin_update()
        k11_dashboard_fallback()
    finally:
        restore_process()
        for base in CLEAN:
            cleanup(base)
    finish("test_resolver")


if __name__ == "__main__":
    main()
