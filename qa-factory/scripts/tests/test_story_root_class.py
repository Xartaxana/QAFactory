#!/usr/bin/env python3
"""The story-root drivers of `hooklib` (CX1-18, part A0): the leaf and the four functions that ask it.

`is_story_folder` is the ONE rule "this folder is a story"; `story_root` (a key), `story_root_at` (a path),
`story_of` (a pair of flags) and `story_cli` (a script's `main`) decide through it, and `exact_options` turns the
abbreviations of a parser off (an abbreviated `--task` once became a relative `--task-root`, CX1-10). This file
pins the drivers only: every unfriendly input of the spec's table (3.0) with the positive same-form input beside
it, the texts R0, R1, R2, R1', R2', R-both, the exit and the channel of `story_cli`, and the walk of `exact_options`
over subparsers. The callers are parts A and B and pin themselves.

Rows that exist only where the file system allows them say so in their own row when the volume cannot: the folder
`TP3-1 ` (a trailing blank) is an ordinary name on Linux and, on NTFS, one that only the extended-length prefix
`\\\\?\\` can create; an 8.3 short name is an NTFS one; a detour `nowhere/../TP3-1` is the same folder on Windows
(which reads `..` lexically) and a refusal on Linux (the kernel reads it through `nowhere`).
"""
import contextlib
import argparse
import io
import json
import os
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import role_cli  # noqa: E402

PHRASE = "initialize task before work"
CYRILLIC_E = chr(0x415)          # looks like the Latin E of TP3-1
NUL = chr(0)
TEXTS = []                       # every refusal text seen: none may carry the driver's phrase (t-933 L-2 F-12)


@contextlib.contextmanager
def a_project():
    """A project with the stories TP3-1 and TP3-2; the hook layer points at it, the cwd and the env come back after."""
    project = temp_project("qa-story-root-")
    artifacts = project / "qa-factory" / "artifacts"
    (artifacts / "TP3-1").mkdir(parents=True)
    (artifacts / "TP3-2").mkdir()
    old_env, old_cwd = os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()
    try:
        use_project(project)
        yield project, artifacts
    finally:
        os.chdir(old_cwd)
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(project)


def tree(root):
    """(relative path, size) of everything under `root`: "nothing was written" is this being equal."""
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size if p.is_file() else -1)
                  for p in Path(root).rglob("*"))


def outcome(fn, *args, **kwargs):
    """('ok', value) or ('refused', text): a StoryRootError is the refusal; any other exception is a FAIL row of main()."""
    try:
        return "ok", fn(*args, **kwargs)
    except hooklib.StoryRootError as exc:
        TEXTS.append(str(exc))
        return "refused", str(exc)


def refused(name, fn, *args, needles=(), **kwargs):
    kind, got = outcome(fn, *args, **kwargs)
    check(f"{name}: refused", kind == "refused", f"got {got!r}")
    for needle in needles:
        check_in(f"{name}: says {needle!r}", needle, got if kind == "refused" else "")
    return got if kind == "refused" else ""


def accepted(name, fn, *args, **kwargs):
    kind, got = outcome(fn, *args, **kwargs)
    check(f"{name}: accepted (the positive control)", kind == "ok", f"refused: {got}")
    return got if kind == "ok" else None


def a_link(link, target):
    """A symlink, or on Windows without the right a junction, `link` -> `target`; False when neither can be made."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return made.returncode == 0
    return False


def the_leaf_says_yes_only_to_an_exact_folder():
    with a_project() as (project, artifacts):
        (artifacts / "a-file").write_text("not a folder", encoding="utf-8")
        check_eq("TP3-1 is a story (the positive control)", hooklib.is_story_folder(artifacts, "TP3-1"), True)
        check_eq("a parent given as text is the same question", hooklib.is_story_folder(str(artifacts), "TP3-1"), True)
        # the table 3.0: every one of these stays on the safe side
        unfriendly = {
            "a case-different spelling": "tp3-1", "a leading blank": " TP3-1", "a trailing blank": "TP3-1 ",
            "a trailing tab": "TP3-1\t", "a trailing dot": "TP3-1.", "the name of a FILE": "a-file",
            "an absent name": "TP3-404", "empty": "", "blank": "  ", "dot": ".", "dot dot": "..",
            "a slash": "a/b", "a backslash": "a" + chr(92) + "b", "a drive colon": "C:x", "a colon": "TP3:1",
            "a NUL": "TP3-1" + NUL, "a Cyrillic homoglyph": CYRILLIC_E + "PM-1",
            "255 characters (AT the file system's limit, not in the listing)": "k" * 255,
            "300 characters (BEYOND it)": "k" * 300, "None": None, "a number": 1, "bytes": b"TP3-1"}
        for what, name in unfriendly.items():
            check_eq(f"{what} is not a story", hooklib.is_story_folder(artifacts, name), False)
        # the parent can be wrong too, and nothing becomes the cwd
        for what, parent in (("None", None), ("empty", ""), ("blank", "  "), ("absent", artifacts / "nowhere"),
                             ("a file", artifacts / "a-file")):
            check_eq(f"a parent that is {what} answers False", hooklib.is_story_folder(parent, "TP3-1"), False)
        # an 8.3 short name or a trailing blank is a folder to an NTFS stat, never to the listing
        if os.name == "nt":
            import ctypes
            (artifacts / "TP2-2406").mkdir()
            buffer = ctypes.create_unicode_buffer(300)
            ctypes.windll.kernel32.GetShortPathNameW(str(artifacts / "TP2-2406"), buffer, 300)
            short = Path(buffer.value).name
            if short.lower() == "tp2-2406":
                check("the volume makes no 8.3 names - nothing to pin", True)
            else:
                check("the short name is a folder to the file system", (artifacts / short).is_dir())
                check_eq("the 8.3 short name is not a story", hooklib.is_story_folder(artifacts, short), False)
                check_eq("the long name is (the positive control)",
                         hooklib.is_story_folder(artifacts, "TP2-2406"), True)
            # NTFS holds 'TP3-1 ' when it is created through the extended-length prefix (the Win32 layer strips the
            # blank otherwise); once it exists, a plain stat of 'TP3-1 ' answers for 'TP3-1' - the strip check of the
            # leaf is load-bearing on Windows too (M-A1, critic t-1145 F-4)
            blank = "\\\\?\\" + str(artifacts) + "\\TP3-1 "
            try:
                os.mkdir(blank)
            except OSError as exc:
                check(f"this volume refuses the folder 'TP3-1 ' even through the extended-length prefix ({exc}) - "
                      "nothing to pin on Windows, the docker run pins M-A1", True)
            else:
                try:
                    check("the folder 'TP3-1 ' is really there", "TP3-1 " in os.listdir(artifacts))
                    check("to a plain stat it is a folder (the alias that makes the strip check load-bearing)",
                          (artifacts / "TP3-1 ").is_dir())
                    check_eq("the folder 'TP3-1 ' (a trailing blank) is not a story", hooklib.is_story_folder(artifacts, "TP3-1 "), False)
                    check_eq("and 'TP3-1' still is", hooklib.is_story_folder(artifacts, "TP3-1"), True)
                    check_in("story_root refuses the key with the blank and names the real folder",
                             "A folder 'TP3-1' exists: the key is matched exactly.",
                             refused("a key with a trailing blank", hooklib.story_root, "TP3-1 ", "t"))
                finally:
                    os.rmdir(blank)
                check("and it is gone again", "TP3-1 " not in os.listdir(artifacts))
        else:
            (artifacts / "TP3-1 ").mkdir()
            check("the folder 'TP3-1 ' is really there", "TP3-1 " in os.listdir(artifacts))
            check_eq("the folder 'TP3-1 ' (a trailing blank) is not a story", hooklib.is_story_folder(artifacts, "TP3-1 "), False)
            check_eq("and 'TP3-1' still is", hooklib.is_story_folder(artifacts, "TP3-1"), True)
        # a name at the limit that EXISTS is a story: the limit is the file system's, not ours (AT)
        try:
            (artifacts / ("k" * 255)).mkdir()
            check_eq("a real 255-character folder is a story (AT)", hooklib.is_story_folder(artifacts, "k" * 255), True)
        except OSError:
            check("this volume cannot hold a 255-character folder under this path - nothing to pin", True)
        # a link or a junction with the EXACT name is a story; the target is not looked at
        outside = temp_dir("qa-story-root-target-")
        try:
            if a_link(artifacts / "TP3-L", outside):
                check_eq("a link with the exact name is a story", hooklib.is_story_folder(artifacts, "TP3-L"), True)
                check_eq("its case-different spelling is not", hooklib.is_story_folder(artifacts, "tp3-l"), False)
                if os.name == "nt":
                    os.rmdir(artifacts / "TP3-L")
                else:
                    os.unlink(artifacts / "TP3-L")
            else:
                check("this account can make neither a symlink nor a junction - nothing to pin", True)
        finally:
            cleanup(outside)
        # a failing listing or stat is "no", not an exception; from here on only questions are asked
        before = tree(project)
        with mock.patch("os.listdir", side_effect=PermissionError(13, "denied")):
            check_eq("a listing that fails answers False", hooklib.is_story_folder(artifacts, "TP3-1"), False)
        with mock.patch.object(Path, "is_dir", side_effect=OSError(36, "File name too long")):
            check_eq("a stat that fails answers False", hooklib.is_story_folder(artifacts, "TP3-1"), False)
        check_eq("with both back, TP3-1 is a story again", hooklib.is_story_folder(artifacts, "TP3-1"), True)
        # the file system that does not tell case or a trailing blank apart (NTFS, emulated)
        real_is_dir = Path.is_dir

        def ntfs_is_dir(self):
            try:
                names = os.listdir(self.parent)
            except OSError:
                return False
            alias = self.name.rstrip(" .").lower()
            return real_is_dir(self) or any(n.rstrip(" .").lower() == alias for n in names)

        with mock.patch.object(Path, "is_dir", ntfs_is_dir):
            for name in ("tp3-1", "TP3-1.", "Tp3-1"):
                check_eq(f"{name!r} is a folder to the stub and still not a story", hooklib.is_story_folder(artifacts, name), False)
            check_eq("TP3-1 is one", hooklib.is_story_folder(artifacts, "TP3-1"), True)
        check_eq("asking created nothing", tree(project), before)


def story_root_decides_through_the_leaf_and_keeps_its_texts():
    with a_project() as (project, artifacts):
        path = artifacts.resolve() / "TP3-1"
        check_eq("the key of a story gives its folder", accepted("TP3-1", hooklib.story_root, "TP3-1", "t"), path)
        with mock.patch.object(hooklib, "is_story_folder", return_value=False) as leaf:
            refused("the leaf says no, so the key is refused though the folder is there", hooklib.story_root, "TP3-1", "t",
                    needles=("names no story",))
            check_eq("and it asked the leaf, of the artifact root, for the exact key", leaf.call_args.args,
                     (path.parent, "TP3-1"))
        with mock.patch.object(hooklib, "is_story_folder", return_value=True):
            check_eq("the leaf says yes: the folder it names", hooklib.story_root("TP3-404", "t"),
                     path.parent / "TP3-404")
        # R2 byte for byte, and the near miss: the decision moved to the leaf, the listing hint stayed
        got = refused("R2", hooklib.story_root, "TP3-404", "t", "Try --task-root.")
        check_eq("R2 is the text of CX1-10", got,
                 f"t 'TP3-404' names no story: {path.parent / 'TP3-404'} is not a folder of this project, and a story "
                 f"folder is never created here (S0 creates it). Pass the key of a story that exists. Try --task-root.")
        got = refused("a key with a different case", hooklib.story_root, "tp3-1", "t")
        check_in("names the real folder", "A folder 'TP3-1' exists: the key is matched exactly.", got)
        got = refused("R1", hooklib.story_root, "", "t")
        check_eq("R1 is the text of CX1-10", got, "t requires a story's ticket key, the name of one folder under the "
                 "artifact root, e.g. TP2-2406 (got '').")
        check("the refusal is a ValueError too (the pins of CX1-10 read it so)",
              issubclass(hooklib.StoryRootError, ValueError))


def a_path_is_a_story_when_its_last_component_is():
    with a_project() as (project, artifacts):
        story = artifacts / "TP3-1"
        (artifacts / "a-file").write_text("x", encoding="utf-8")
        before = tree(project)
        # P5, the doctor's relative form: returned as given, decided against the cwd
        os.chdir(project)
        relative = os.path.join("qa-factory", "artifacts", "TP3-1")
        got = accepted("P5 a relative path", hooklib.story_root_at, relative, "t")
        check_eq("P5: and it comes back as it was given, relative", got, Path(relative))
        check("P5: not made absolute", got is not None and not got.is_absolute())
        refused("P5 control: a relative path that is absent", hooklib.story_root_at,
                os.path.join("qa-factory", "artifacts", "TP3-404"), "t", needles=("names no story",))
        # P6: absent, with the absolute path in the text
        nowhere = os.path.join("nowhere", "TP3-404")
        got = refused("P6 a relative path that is absent", hooklib.story_root_at, nowhere, "t",
                      needles=("names no story", f"(resolved: {os.path.abspath(nowhere)})", "S0 creates it"))
        check_eq("P6: R2' is the whole text", got, f"t {nowhere!r} (resolved: {os.path.abspath(nowhere)}) names no story: "
                 "it is not a folder, and a story folder is never created here (S0 creates it). Pass the folder of a "
                 "story that exists.")
        check("P6: nothing was created", not Path("nowhere").exists())
        # P7: a file
        refused("P7 a file", hooklib.story_root_at, artifacts / "a-file", "t", needles=("it is not a folder",))
        # P8: empty is never the current folder
        os.chdir(story)
        for empty in ("", "  ", None, "\t"):
            refused(f"P8 {empty!r} while standing in a story", hooklib.story_root_at, empty, "t",
                    needles=("an empty value would be the current folder, so nothing was read or written",))
        check_eq("P8 control: '.' there is the explicit word for that folder", accepted(
            "'.' in a story", hooklib.story_root_at, ".", "t"), Path("."))
        os.chdir(artifacts.anchor)
        got = refused("'.' at the root of the file system (no name)", hooklib.story_root_at, ".", "t",
                      needles=("names no story",))
        os.chdir(project)
        # the root of a drive or of the file system: the name is empty
        refused("an anchor", hooklib.story_root_at, artifacts.anchor, "t", needles=("names no story",))
        # a trailing slash, a detour, spaces, the lengths
        accepted("a trailing slash", hooklib.story_root_at, str(story) + os.sep, "t")
        # a detour through `..` (critic t-1145 F-1): the form as GIVEN must reach the folder the decision looked at
        real_detour = str(artifacts / ".." / "artifacts" / "TP3-1")
        check_eq("a detour through a REAL folder reaches the same story: accepted, as given (the positive control)",
                 accepted("artifacts/../artifacts/TP3-1", hooklib.story_root_at, real_detour, "t"), Path(real_detour))
        absent_detour = str(artifacts / "nowhere" / ".." / "TP3-1")
        if os.name == "nt":
            check_eq("Windows reads .. lexically: a detour through an absent folder is the same story",
                     accepted("nowhere/../TP3-1 (Windows)", hooklib.story_root_at, absent_detour, "t"), Path(absent_detour))
        else:
            got = refused("nowhere/../TP3-1: the kernel cannot open it", hooklib.story_root_at, absent_detour, "t",
                          needles=("names no story", "the path reaches another folder, or none, through `..`"))
            check("and the refusal is not the plain 'not a folder'", "it is not a folder" not in got, got)
            outside = temp_dir("qa-story-root-detour-")
            try:
                (outside / "x").mkdir()
                if a_link(artifacts / "lnk", outside / "x"):
                    link_detour = str(artifacts / "lnk" / ".." / "TP3-1")
                    refused("lnk/../TP3-1, the other folder is absent", hooklib.story_root_at, link_detour, "t",
                            needles=("the path reaches another folder, or none, through `..`",))
                    (outside / "TP3-1").mkdir()
                    refused("lnk/../TP3-1, the other folder exists: another story, not this one", hooklib.story_root_at,
                            link_detour, "t", needles=("the path reaches another folder, or none, through `..`",))
                    os.symlink(artifacts, artifacts / "lnk2", target_is_directory=True)
                    same_detour = str(artifacts / "lnk2" / ".." / "TP3-1")
                    # lnk2 -> artifacts, so lnk2/.. is the parent of artifacts: also another folder
                    refused("lnk2/../TP3-1 leads out of the artifact root", hooklib.story_root_at, same_detour, "t")
                    os.unlink(artifacts / "lnk2")
                    os.symlink(story, artifacts / "lnk3", target_is_directory=True)
                    same_detour = str(artifacts / "lnk3" / ".." / "TP3-1")
                    # lnk3 -> artifacts/TP3-1, whose parent is artifacts: the detour lands on the same story
                    check_eq("lnk3/../TP3-1: a symlink whose detour comes back to the same story is accepted (control)",
                             accepted("lnk3/../TP3-1", hooklib.story_root_at, same_detour, "t"), Path(same_detour))
                    os.unlink(artifacts / "lnk3")
                    os.unlink(artifacts / "lnk")
                else:
                    check("this account cannot make a symlink - nothing to pin on the link detour", True)
            finally:
                cleanup(outside)
        # the samefile line is what keeps the detour honest: its failure, or its "different", is a refusal anywhere
        with mock.patch("os.path.samefile", side_effect=OSError(2, "gone")):
            refused("samefile raises OSError: no", hooklib.story_root_at, real_detour, "t",
                    needles=("the path reaches another folder, or none, through `..`",))
        with mock.patch("os.path.samefile", return_value=False):
            refused("samefile says different: no", hooklib.story_root_at, real_detour, "t",
                    needles=("the path reaches another folder, or none, through `..`",))
        with mock.patch("os.path.samefile", return_value=True):
            accepted("samefile says same: yes (the control of the two rows above)", hooklib.story_root_at, real_detour, "t")
        spaced = temp_dir("qa story root ") / "a b" / "TP3-1"
        spaced.mkdir(parents=True)
        try:
            check_eq("P4 a path with spaces, outside any project (the project is not required)",
                     accepted("P4", hooklib.story_root_at, spaced, "t"), spaced)
        finally:
            cleanup(spaced.parents[1])
        check_eq("m-1 scope: a folder that is not under the artifact root passes (the absent folder is what is promised)",
                 accepted("the artifact root itself", hooklib.story_root_at, artifacts, "t"), artifacts)
        refused("300 characters (BEYOND)", hooklib.story_root_at, artifacts / ("k" * 300), "t", needles=("names no story",))
        refused("255 characters (AT, absent)", hooklib.story_root_at, artifacts / ("k" * 255), "t", needles=("names no story",))
        # encoding in a PARENT component (critic t-1145 F-2): a refusal, never a ValueError out of the listing
        refused("a NUL in a parent folder", hooklib.story_root_at, "a" + NUL + "b/TP3-1", "t", needles=("names no story",))
        refused("a NUL in the name", hooklib.story_root_at, str(artifacts) + os.sep + "TP3-1" + NUL, "t",
                needles=("names no story",))
        refused("the control: an ordinary absent parent", hooklib.story_root_at, "a b/TP3-1", "t",
                needles=("names no story",))
        check_eq("the listing helper reads a NUL, a wildcard-like name and None (never the current folder) as 'nothing'",
                 [hooklib._listing("a" + NUL + "b"), hooklib._listing(artifacts / "a*b"), hooklib._listing(None)],
                 [[], [], []])
        check_in("and a real folder as its names (the control)", "TP3-1", hooklib._listing(artifacts))
        # the aliases: refused, with the real folder named (the NTFS stat would have said yes)
        got = refused("a case-different spelling", hooklib.story_root_at, artifacts / "tp3-1", "t")
        check_in("and the real folder is named", "A folder 'TP3-1' exists: the name is matched exactly.", got)
        got = refused("a trailing blank (abspath drops it on Windows; the lexical name must not)", hooklib.story_root_at,
                      str(story) + " ", "t")
        check_in("and the real folder is named too", "A folder 'TP3-1' exists", got)
        refused("a trailing dot", hooklib.story_root_at, str(story) + ".", "t", needles=("names no story",))
        check_eq("the door of the caller closes the refusal", refused(
            "door", hooklib.story_root_at, "", "t", "Pass --task instead.")[-len("Pass --task instead."):],
                 "Pass --task instead.")
        check_eq("none of this wrote a byte", tree(project), before)


def r1_prime_names_the_projects_own_artifact_root():
    """m-3: the example folder is built from the configured artifact root, not from a literal."""
    with a_project() as (project, artifacts):
        got = refused("R1' in a project", hooklib.story_root_at, "", "t")
        check_in("the example is this project's artifact root", str(artifacts.resolve() / "<KEY>"), got)
        config = project / "qa-factory" / "config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["artifact_root"] = "stories"
        config.write_text(json.dumps(cfg), encoding="utf-8")
        hooklib._PROJECT_ROOT_CACHE = None
        got = refused("R1' with a configured artifact root", hooklib.story_root_at, "", "t")
        check_in("the example follows the configuration", str(project.resolve() / "stories" / "<KEY>"), got)
    plain = temp_dir("qa-story-root-plain-")
    old_env, old_cwd = os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()
    try:
        os.environ["CLAUDE_PROJECT_DIR"] = str(plain)
        hooklib._PROJECT_ROOT_CACHE = None
        os.chdir(plain)
        got = refused("R1' outside a project", hooklib.story_root_at, "", "t")
        check_in("the placeholder stands where no root is known", "<artifact root>/<KEY>", got)
        (plain / "S-1").mkdir()
        accepted("a story outside a project is legal for a path", hooklib.story_root_at, plain / "S-1", "t")
    finally:
        os.chdir(old_cwd)
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(plain)


def the_pair_of_flags_is_one_story_or_one_refusal():
    with a_project() as (project, artifacts):
        one, two = artifacts / "TP3-1", artifacts / "TP3-2"
        before = tree(project)
        # R0: neither flag, the door names the flags THIS script has
        got = refused("R0", hooklib.story_of, "sizing.py", needles=(
            "sizing.py requires the story: --task <KEY> (the name of its folder under the artifact root) or "
            "--task-root <the story's folder>; neither was given, so nothing was read or written.",))
        got = refused("R0 of a script with only a path flag", hooklib.story_of, "case_stamp.py", key_flag=None)
        check("R0: no --task door for a script that has none", "--task <KEY>" not in got, got)
        check_in("R0: it names its own flag", "--task-root <the story's folder>", got)
        # a script whose story-folder flag has another name (--root of report_facts is the PROJECT, not a folder flag)
        got = refused("R0 with the flags of another script", hooklib.story_of, "x.py",
                      key_flag="--task", root_flag="--story-dir", door="Ask the owner.")
        check_in("R0: the renamed flag", "--story-dir <the story's folder>", got)
        check_not_in("R0: and not the default one", "--task-root", got)
        check("R0: the door closes it", got.endswith("Ask the owner."), got)
        # a GIVEN empty value is not R0 (F-6): the key refusal / the path refusal, naming the script's flag
        got = refused("an empty key", hooklib.story_of, "stage_status.py", key="", needles=(
            "stage_status.py --task requires a story's ticket key",))
        check_not_in("an empty key is not R0", "neither was given", got)
        got = refused("an empty path", hooklib.story_of, "case_stamp.py", root="", key_flag=None, needles=(
            "case_stamp.py --task-root requires the story's folder", "an empty value would be the current folder"))
        check_not_in("an empty path is not R0", "neither was given", got)
        # both given empty (L-3, the builder's question): ONE refusal with R1 and R1', the key first - never R0
        for pair in (("", ""), ("", "  "), ("  ", "")):
            got = refused(f"both empty {pair!r}", hooklib.story_of, "x.py", key=pair[0], root=pair[1], door="Try again.")
            check(f"both empty {pair!r}: ONE refusal, the key first",
                  0 <= got.find("x.py --task requires a story's ticket key") < got.find("x.py --task-root requires the story's folder"),
                  got)
            check_not_in(f"both empty {pair!r}: not R0", "neither was given", got)
            check_eq(f"both empty {pair!r}: the door once, at the end", (got.count("Try again."), got.endswith("Try again.")),
                     (1, True))
        # only one flag
        check_eq("only a key", accepted("key", hooklib.story_of, "x.py", key="TP3-1"), one.resolve())
        check_eq("only a path, as given", accepted("path", hooklib.story_of, "x.py", root=str(two)), Path(str(two)))
        got = refused("only a phantom key", hooklib.story_of, "x.py", key="TP3-404", needles=("x.py --task 'TP3-404' names no story",))
        got = refused("only a phantom path", hooklib.story_of, "x.py", root=artifacts / "TP3-404",
                      needles=("x.py --task-root ", "names no story"))
        # F-8: both flags
        around = str(artifacts / ".." / "artifacts" / "TP3-1")
        check_eq("P9 both, one folder (spelled another way): the path as given",
                 accepted("same", hooklib.story_of, "x.py", key="TP3-1", root=around), Path(around))
        got = refused("P9 both, different folders", hooklib.story_of, "x.py", key="TP3-1", root=two, needles=(
            "x.py got --task 'TP3-1' and --task-root ", "they name different folders", str(one.resolve()),
            str(two), "pass one of them"))
        got = refused("both, the key is the phantom", hooklib.story_of, "x.py", key="TP3-404", root=one)
        check("both: one sentence when one is good", got.count("names no story") == 1, got)
        got = refused("both, the path is the phantom", hooklib.story_of, "x.py", key="TP3-1", root=artifacts / "TP3-404")
        check("both: one sentence when one is good (the other way)", got.count("names no story") == 1, got)
        got = refused("both phantoms", hooklib.story_of, "x.py", key="TP3-404", root=artifacts / "TP3-405", door="Ask S0.")
        check("both phantoms: ONE refusal carrying both sentences", got.count("names no story") == 2, got)
        check("both phantoms: the key first", 0 <= got.find("x.py --task 'TP3-404'") < got.find("x.py --task-root "), got)
        check_eq("both phantoms: the door once, at the end (F-6)", (got.count("Ask S0."), got.endswith("Ask S0.")), (1, True))
        got = refused("one phantom with a door", hooklib.story_of, "x.py", key="TP3-404", door="Ask S0.")
        check_eq("one phantom: the door once, at the end (the control of the row above)",
                 (got.count("Ask S0."), got.endswith("Ask S0.")), (1, True))
        got = refused("renamed flags reach the text", hooklib.story_of, "x.py", root=artifacts / "TP3-404",
                      root_flag="--story-dir")
        check_in("the flag of the script", "x.py --story-dir ", got)
        # a value for a flag the script declares absent is the caller's defect, a TypeError, never a text with 'None' (F-6)
        for what, kwargs in (("a key", dict(key="TP3-404", key_flag=None)), ("a path", dict(root=str(one), root_flag=None))):
            try:
                hooklib.story_of("x.py", **kwargs)
                raised = None
            except TypeError as exc:
                raised = str(exc)
            check(f"{what} for a flag declared absent: a TypeError", raised is not None)
            check_not_in(f"{what} for a flag declared absent: no 'x.py None' text", "x.py None", raised or "")
        check_eq("the control: the same value with its flag declared works",
                 accepted("key with its flag", hooklib.story_of, "x.py", key="TP3-1"), one.resolve())
        check_eq("nothing was written", tree(project), before)


def a_given_project_is_where_the_key_resolves():
    """critic t-1145 F-3 / L-2 F-7: `--root` / `--project-root` of report_facts, traceability, judge_results, sizing name the
    PROJECT; the key resolves under it, through the same leaf. `project=None` is this process's project, as before."""
    with a_project() as (project, artifacts):
        other = temp_project("qa-story-root-other-")
        try:
            (other / "qa-factory" / "artifacts" / "TP3-9").mkdir(parents=True)
            elsewhere = other / "qa-factory" / "artifacts" / "TP3-9"
            before = (tree(project),)
            check_eq("project=None: as before, the story of THIS project",
                     accepted("TP3-1, no project", hooklib.story_root, "TP3-1", "t"), artifacts.resolve() / "TP3-1")
            refused("project=None: a story that lives only in the other project is a phantom here (the control)",
                    hooklib.story_root, "TP3-9", "t", needles=("names no story",))
            check_eq("project=other: the key resolves under it",
                     accepted("TP3-9 under the other project", hooklib.story_root, "TP3-9", "t", project=other),
                     elsewhere.resolve())
            check_eq("project given as text is the same", accepted("as text", hooklib.story_root, "TP3-9", "t",
                                                                     project=str(other)), elsewhere.resolve())
            got = refused("project=other: a story of THIS project is a phantom there", hooklib.story_root, "TP3-1", "t",
                          project=other, needles=("names no story", str(other.resolve())))
            check_not_in("and the text does not name this project's folder", str(artifacts.resolve()), got)
            # the artifact root of the OTHER project is read from ITS config
            config = other / "qa-factory" / "config.json"
            cfg = json.loads(config.read_text(encoding="utf-8"))
            cfg["artifact_root"] = "stories"
            config.write_text(json.dumps(cfg), encoding="utf-8")
            (other / "stories" / "TP3-7").mkdir(parents=True)
            check_eq("the configured artifact root of the given project",
                     accepted("TP3-7", hooklib.story_root, "TP3-7", "t", project=other),
                     (other / "stories" / "TP3-7").resolve())
            del cfg["artifact_root"]                # back to the default root for the rows below
            config.write_text(json.dumps(cfg), encoding="utf-8")
            settled = tree(other)
            # a project that is not one, or none at all, is a refusal - never the current folder, never the exit of
            # require_project (the caller's own word named it)
            os.chdir(project)
            for what, bad in (("empty", ""), ("blank", "  "), ("a folder without the marker", artifacts),
                              ("an absent folder", other / "nowhere")):
                refused(f"project {what}", hooklib.story_root, "TP3-1", "t", "Pass --root.", project=bad,
                        needles=("is not an onboarded project", "nothing was read or written"))
            check_eq("the door of the caller closes it", refused("door", hooklib.story_root, "TP3-1", "t", "Pass --root.",
                                                                 project="")[-len("Pass --root."):], "Pass --root.")
            check_eq("a bad key is R1 before the project is looked at", refused("bad key", hooklib.story_root, "", "t",
                                                                                 project=other)[:20], "t requires a story's")
            # story_of and story_cli forward it to the key; a path names its own folder
            check_eq("story_of: the key under the given project",
                     accepted("story_of", hooklib.story_of, "x.py", key="TP3-9", project=other), elsewhere.resolve())
            check_eq("story_of: the key AND a path of that project: one story, the path as given",
                     accepted("both", hooklib.story_of, "x.py", key="TP3-9", root=str(elsewhere), project=other),
                     Path(str(elsewhere)))
            refused("story_of: the key AND the path of THIS project: two stories", hooklib.story_of, "x.py", key="TP3-9",
                    root=str(artifacts / "TP3-1"), project=other, needles=("they name different folders",))
            check_eq("story_of: a path alone ignores the project",
                     accepted("path alone", hooklib.story_of, "x.py", root=str(artifacts / "TP3-1"), project=other),
                     Path(str(artifacts / "TP3-1")))
            check_eq("story_cli (exit=False): forwarded",
                     accepted("story_cli", hooklib.story_cli, "x.py", key="TP3-9", project=other, exit=False),
                     elsewhere.resolve())
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    hooklib.story_cli("x.py", key="TP3-1", project=other)
                code = None
            except SystemExit as exc:
                code = exc.code
            check_eq("story_cli: a story of the wrong project exits 2 on the guard's channel", code, 2)
            check_in("with the refusal as JSON", "names no story", json.loads(err.getvalue())["error"])
            check_eq("nothing was written in this project", tree(project), before[0])
            check_eq("nothing was written in the given project", tree(other), settled)
        finally:
            cleanup(other)


def story_cli_turns_a_listing_error_into_its_refusal():
    """critic t-1145 F-2: a NUL in a parent folder name was a traceback (rc=1) out of the second listing; it is the
    refusal on the channel of the form, as an absent parent is."""
    with a_project() as (project, artifacts):
        nul_root = "a" + NUL + "b" + os.sep + "TP3-1"
        for what, root in (("a NUL in a parent folder", nul_root), ("the control: an ordinary absent parent", "a b/TP3-1")):
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    hooklib.story_cli("x.py", root=root)
                code = None
            except SystemExit as exc:
                code = exc.code
            except Exception as exc:  # noqa: BLE001 - the defect being pinned: a traceback
                code = f"{type(exc).__name__}: {exc}"
            check_eq(f"story_cli ({what}): exit 2", code, 2)
            check_in(f"story_cli ({what}): the refusal is the error", "names no story", err.getvalue())
        refused("story_of (a NUL in a parent folder): a StoryRootError", hooklib.story_of, "x.py", root=nul_root,
                needles=("names no story",))


def no_refusal_carries_the_phrase_the_driver_reads():
    """t-933 L-2 F-12: `story_run` reads «initialize task before work» as `uninitialized`; no text of these drivers has it."""
    check("the batteries above produced refusal texts to read", len(TEXTS) > 20, str(len(TEXTS)))
    for text in TEXTS:
        check_not_in("no text carries the driver's phrase", PHRASE, text)


def the_cli_form_refuses_on_stderr_and_the_guarded_form_raises():
    driver_dir = temp_dir("qa-story-root-driver-")
    script = driver_dir / "story_cli_probe.py"
    script.write_text("import json, sys\n"
                      f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
                      "import hooklib\n"
                      "print(hooklib.story_cli('probe.py', **json.loads(sys.argv[1])))\n", encoding="utf-8")

    def run(cwd, env_dir, **kwargs):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(env_dir), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-B", str(script), json.dumps(kwargs)], capture_output=True, text=True,
                              encoding="utf-8", cwd=str(cwd), env=env, timeout=120)

    try:
        with a_project() as (project, artifacts):
            before = tree(project)
            good = run(project, project, root=str(artifacts / "TP3-1"))
            check_eq("the positive control: a story, exit 0", good.returncode, 0)
            check_eq("the positive control: the folder on stdout", good.stdout.strip(), str(artifacts / "TP3-1"))
            bad = run(project, project, root=str(artifacts / "TP3-404"))
            check_eq("a phantom path: exit 2", bad.returncode, 2)
            check_eq("a phantom path: nothing on stdout", bad.stdout, "")
            check_eq("a phantom path: ONE line on stderr", len(bad.stderr.splitlines()), 1)
            payload = json.loads(bad.stderr)
            check_eq("the line is the object {error}", list(payload), ["error"])
            check_in("and the error is the refusal", "probe.py --task-root ", payload["error"])
            check_in("it names no story", "names no story", payload["error"])
            # a homoglyph is visible: ensure_ascii escapes it
            lookalike = run(project, project, key=CYRILLIC_E + "PM-1")
            check_eq("a Cyrillic E in the key: exit 2", lookalike.returncode, 2)
            check_in("and the escape is on stderr, not the glyph", chr(92) + "u0415PM-1", lookalike.stderr)
            check_not_in("the glyph itself is not", CYRILLIC_E, lookalike.stderr)
            empty = run(project, project)
            check_eq("neither flag: exit 2 (R0)", empty.returncode, 2)
            check_in("neither flag: R0 is the error", "neither was given", json.loads(empty.stderr)["error"])
            check_eq("none of the refusals wrote a byte", tree(project), before)
            check_eq("the key form too: a story, exit 0", run(project, project, key="TP3-2").returncode, 0)
        plain = temp_dir("qa-story-root-plain-")
        try:
            nowhere = run(plain, plain, key="TP3-1")
            check_eq("a key outside a project keeps the shared exit 3", nowhere.returncode, hooklib.EXIT_NO_PROJECT)
            check_in("and its text", "refusing to create one", nowhere.stderr)
            check_eq("a path outside a project needs none", run(plain, plain, root=str(plain)).returncode, 0)
        finally:
            cleanup(plain)
    finally:
        cleanup(driver_dir)
    # the guarded form: the StoryRootError reaches run_guarded, which prints it in the registered command's shape
    with a_project() as (project, artifacts):
        stream = io.StringIO()
        code = role_cli.run_guarded("plan_row.py", lambda: hooklib.story_cli(
            "plan_row.py", root=str(artifacts / "TP3-404"), exit=False), stream)
        check_eq("under run_guarded the refusal is the guard's: its exit", code, role_cli.EXIT_REFUSED)
        check_in("under run_guarded: its first line", "plan_row.py: plan_row.py --task-root ", stream.getvalue())
        check_in("under run_guarded: the registered shape follows", "what to write:", stream.getvalue())
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                hooklib.story_cli("plan_row.py", root=str(artifacts / "TP3-404"))
            exited = None
        except SystemExit as exc:
            exited = exc.code
        check_eq("the default form exits itself with 2", exited, 2)
        check_eq("and prints no stdout", out.getvalue(), "")
        check_eq("one JSON line on stderr", list(json.loads(err.getvalue())), ["error"])
        raised = None
        try:
            hooklib.story_cli("plan_row.py", root=str(artifacts / "TP3-404"), exit=False)
        except hooklib.StoryRootError as exc:
            raised = exc
        check("exit=False re-raises the StoryRootError", raised is not None)
        check_eq("the guarded control: a story passes both forms", (
            hooklib.story_cli("p", root=str(artifacts / "TP3-1"), exit=False),
            hooklib.story_cli("p", root=str(artifacts / "TP3-1"))), (Path(str(artifacts / "TP3-1")),) * 2)


def exact_options_turns_abbreviations_off_everywhere_it_can_see():
    def parser():
        ap = argparse.ArgumentParser(prog="demo.py")
        ap.add_argument("--task-root")
        subs = ap.add_subparsers(dest="command")
        record = subs.add_parser("record")
        record.add_argument("--task-root")
        http = subs.add_parser("http")
        http.add_argument("--task-root")
        deeper = http.add_subparsers(dest="mode").add_parser("deep")
        deeper.add_argument("--task-root")
        return ap, subs

    def parse(ap, *argv):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                return ap.parse_args(list(argv)), 0
        except SystemExit as exc:
            return None, exc.code

    ap, subs = parser()
    for argv in (("--task-r", "X"), ("record", "--task-r", "X"), ("http", "--task-r", "X"),
                 ("http", "deep", "--task-r", "X")):
        got, _ = parse(ap, *argv)
        check(f"before the call {' '.join(argv)!r} is read as --task-root (the control: the abbreviation lives)",
              got is not None and got.task_root == "X")
    check("the helper returns the parser it was given", hooklib.exact_options(ap) is ap)
    for argv in (("--task-r", "X"), ("--task", "X"), ("record", "--task-r", "X"), ("http", "--task-r", "X"),
                 ("http", "deep", "--task-r", "X"), ("record", "--task", "X")):
        got, code = parse(ap, *argv)
        check_eq(f"after the call {' '.join(argv)!r} is refused by argparse", (got, code), (None, 2))
    for argv in (("--task-root", "X"), ("--task-root=X",), ("record", "--task-root", "X"),
                 ("http", "--task-root=X"), ("http", "deep", "--task-root", "X")):
        got, _ = parse(ap, *argv)
        check(f"after the call the exact {' '.join(argv)!r} still parses", got is not None and got.task_root == "X")
    # the boundary: a subparser added AFTER the call is not seen - the call form `exact_options(ap).parse_args(argv)`
    # keeps the call last in the expression, so no subparser can come after it
    late = subs.add_parser("late")
    late.add_argument("--task-root")
    got, _ = parse(ap, "late", "--task-r", "X")
    check("a subparser added after the call keeps abbreviations (out of scope, pinned by the call form)",
          got is not None and got.task_root == "X")
    ap2, _ = parser()
    got, _ = parse(hooklib.exact_options(ap2), "record", "--task-r", "X")
    check_eq("the call form exact_options(ap).parse_args(...) refuses in the subparser", got, None)


# ---- CX1-18 part A-rest: the resolvers (class 1), the creators (class 2) and the hooks (class 5) -----------------------

import ast  # noqa: E402
from harness import run_script  # noqa: E402

PHANTOM = "TP3-404"                      # a key that names no story folder anywhere below
NO_TRACEBACK = "Traceback"


def cli(name, *args, project):
    """One script run as a child in the project (CLAUDE_PROJECT_DIR is set by `a_project`)."""
    return run_script(name, *args, cwd=project)


def refused_cli(name, done, project, before, *, needles=("names no story",), code=2):
    """A child that refused: the exit code, the needles in its words, no traceback, not a byte written in the project."""
    check_eq(f"{name}: exit {code}", done.returncode, code)
    words = done.stdout + done.stderr
    for needle in needles:
        check_in(f"{name}: says {needle!r}", needle, words)
    check_not_in(f"{name}: no traceback", NO_TRACEBACK, words)
    check_eq(f"{name}: nothing was written in the project", tree(project), before)
    return words


def the_resolvers_of_class_1_say_yes_no_phantom_and_refuse_an_abbreviation():
    """Class 1 (3.1): the wrappers answer through the driver. Each: the story (yes), a phantom (no, nothing written),
    an abbreviation of the flag (refused by `exact_options`), where the script has the flag pair."""
    with a_project() as (project, artifacts):
        before = tree(project)
        # -- stand_gaps: the pair of flags, `story_cli` (the plain script, no channel of its own)
        yes = cli("stand_gaps.py", "--task-root", artifacts / "TP3-1", "--json", project=project)
        check_eq("stand_gaps --task-root <story>: exit 0 (the positive control)", yes.returncode, 0)
        check_eq("stand_gaps --task TP3-1: the same story", cli("stand_gaps.py", "--task", "TP3-1", "--json",
                                                              project=project).returncode, 0)
        words = refused_cli("stand_gaps --task-root <phantom>", cli("stand_gaps.py", "--task-root",
                            artifacts / PHANTOM, "--json", project=project), project, before)
        check_eq("stand_gaps: the refusal is the one JSON line {error} on stderr", list(json.loads(words)), ["error"])
        refused_cli("stand_gaps --task <phantom>", cli("stand_gaps.py", "--task", PHANTOM, "--json", project=project),
                    project, before)
        refused_cli("stand_gaps neither flag", cli("stand_gaps.py", "--json", project=project), project, before,
                    needles=("neither was given",))
        refused_cli("stand_gaps --task-root ''", cli("stand_gaps.py", "--task-root", "", "--json", project=project),
                    project, before, needles=("empty",))
        refused_cli("stand_gaps --task-r (abbreviation)", cli("stand_gaps.py", "--task-r", artifacts / "TP3-1", "--json",
                    project=project), project, before, needles=("unrecognized arguments",))
        refused_cli("stand_gaps --tas (abbreviation)", cli("stand_gaps.py", "--tas", "TP3-1", "--json", project=project),
                    project, before, needles=("unrecognized arguments",))
        refused_cli("stand_gaps two different stories", cli("stand_gaps.py", "--task", "TP3-1", "--task-root",
                    artifacts / "TP3-2", "--json", project=project), project, before, needles=("different folders",))
        check_eq("stand_gaps the same story by both flags: exit 0", cli("stand_gaps.py", "--task", "TP3-1", "--task-root",
                 artifacts / "TP3-1", "--json", project=project).returncode, 0)
        # -- sizing: the pair, and the hook's zero-argument entry stays
        refused_cli("sizing --task <phantom>", cli("sizing.py", "--task", PHANTOM, project=project), project, before)
        refused_cli("sizing --task-root <phantom>", cli("sizing.py", "--task-root", artifacts / PHANTOM, project=project),
                    project, before)
        refused_cli("sizing --task-r (abbreviation)", cli("sizing.py", "--task-r", artifacts / "TP3-1", project=project),
                    project, before, needles=("unrecognized arguments",))
        done = cli("sizing.py", "--task", "TP3-1", project=project)
        check_eq("sizing --task <story>: exit 0 and the sizing is written (the positive control)",
                 (done.returncode, (artifacts / "TP3-1" / "work" / "sizing.json").is_file()), (0, True), )
        # -- handoff_init: the key is DATA with a --task-root; the story is decided before the contract
        form = ["--stage", "S5", "--role", "qa-automator"]
        refused_cli("handoff_init --task <phantom>", cli("handoff_init.py", "--task", PHANTOM, *form, project=project),
                    project, tree(project))
        refused_cli("handoff_init --task-root <phantom>", cli("handoff_init.py", "--task", PHANTOM, *form, "--task-root",
                    artifacts / PHANTOM, project=project), project, tree(project))
        refused_cli("handoff_init --task-root '' (empty)", cli("handoff_init.py", "--task", "TP3-1", *form, "--task-root",
                    "", project=project), project, tree(project), needles=("empty",))
        refused_cli("handoff_init --task-r (abbreviation)", cli("handoff_init.py", "--task", "TP3-1", *form, "--task-r",
                    artifacts / "TP3-1", project=project), project, tree(project), needles=("unrecognized arguments",))
        refused_cli("handoff_init --out under a phantom: the story is decided FIRST", cli("handoff_init.py", "--task",
                    PHANTOM, *form, "--out", project / "x" / "form.yaml", project=project), project, tree(project))
        done = cli("handoff_init.py", "--task", "TP3-1", *form, project=project)
        check_eq("handoff_init --task <story>: exit 0 and the form is under the story (the positive control)",
                 (done.returncode, (artifacts / "TP3-1" / "work" / "handoffs" / "S5-qa-automator-1.yaml").is_file()),
                 (0, True))
        import handoff_init
        with mock.patch.object(handoff_init, "hooklib", None), mock.patch.object(handoff_init, "_HOOKLIB_FAILED",
                                                                                   "ImportError: gone"):
            kind, text = outcome_value(handoff_init.task_root, "TP3-1")
            check("handoff_init without hooklib: a refusal, not the current folder", kind == "refused", text)
            check_in("...that names the cause and a door", "ImportError: gone", text)
            check_in("...the door is the plugin copy, not a folder it cannot use", "reinstall the plugin", text)
        # -- the four key wrappers, called as functions: the story, an alias of it, a phantom
        import bug_records
        import source_exclusions
        import stand_identity
        import story_step
        for what, call in (("story_step._task_root", story_step._task_root),
                           ("source_exclusions._task_root", source_exclusions._task_root),
                           ("stand_identity._task_root", stand_identity._task_root)):
            check(f"{what}: the story (the positive control)", same_folder(call("TP3-1"), artifacts / "TP3-1"))
            for shown, key in (("a phantom", PHANTOM), ("an alias of a story", "tp3-1" if os.name == "nt" else "TP3-1 ")):
                kind, text = outcome_value(call, key)
                check(f"{what}: {shown} is refused", kind == "refused", text)
                check_in(f"{what}: {shown} names no story", "names no story", text)
        kind, text = outcome_value(stand_identity._task_root, PHANTOM)
        check_in("stand_identity: the refusal is a RegistryError that says nothing was recorded", "Nothing was recorded.", text)
        (artifacts / "TP3-1" / "pipeline.json").write_text("{}", encoding="utf-8")
        check_eq("bug_records._story_exists: a story with pipeline.json (the positive control)",
                 bug_records._story_exists(artifacts, "TP3-1"), True)
        check_eq("...a folder without pipeline.json is no story (its own, stricter test)",
                 bug_records._story_exists(artifacts, "TP3-2"), False)
        check_eq("...a phantom", bug_records._story_exists(artifacts, PHANTOM), False)
        check_eq("...an alias", bug_records._story_exists(artifacts, "tp3-1" if os.name == "nt" else "TP3-1 "), False)
        # -- source_exclusions and question_register: the parser literal became exact_options
        refused_cli("source_exclusions --sho (abbreviation of --show)", cli("source_exclusions.py", "--task", "TP3-1",
                    "--sho", project=project), project, tree(project), needles=("unrecognized arguments",))
        refused_cli("source_exclusions --task <phantom> --show", cli("source_exclusions.py", "--task", PHANTOM, "--show",
                    project=project), project, tree(project))
        check_eq("source_exclusions --task <story> --show: exit 0 (the positive control)",
                 cli("source_exclusions.py", "--task", "TP3-1", "--show", project=project).returncode, 0)
        refused_cli("question_register --sho (abbreviation)", cli("question_register.py", "--task", "TP3-1", "--sho",
                    project=project), project, tree(project), needles=("unrecognized arguments",))
        refused_cli("question_register --task <phantom> --show", cli("question_register.py", "--task", PHANTOM, "--show",
                    project=project), project, tree(project))


def same_folder(left, right):
    """The same folder whichever spelling (an 8.3 short temp name, a long one) the two paths wear."""
    return Path(left).resolve() == Path(right).resolve()


def outcome_value(fn, *args, **kwargs):
    """('ok', value) or ('refused', text) for ANY refusal of the family (a RegistryError wraps the driver's text)."""
    try:
        return "ok", fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - what is asked is only "did it refuse, and in what words"
        TEXTS.append(str(exc))
        return "refused", str(exc)


def the_helpers_below_the_root_create_only_under_one_that_exists():
    """Class 2 helpers (3.2): `EventStore` commit/recover, `JobStore`, `write_baseline_receipt`: R-lock, lazy, R-under."""
    import baseline_contract
    import execution_request as ER
    import event_store
    with a_project() as (project, artifacts):
        before = tree(project)
        ghost = artifacts / PHANTOM
        store = event_store.EventStore(ghost)
        for what, call in (("commit", lambda: store.commit("a", {}, "k")), ("recover", lambda: store.recover(lambda ev: None))):
            kind, text = outcome(call)
            check(f"EventStore.{what} into a phantom story: refused with the typed error", kind == "refused", text)
            check_in(f"EventStore.{what}: R-lock says nothing was written", "does not exist, so nothing was written", text)
            check_in(f"EventStore.{what}: ...and where the folder comes from", "created by S0", text)
        check_eq("no folder was made by either", tree(project), before)
        story = event_store.EventStore(artifacts / "TP3-1")
        check_eq("the positive control: commit into a story writes the event", story.commit("a", {}, "k")["sequence"], 1)
        # the five project mutexes use lock() on a folder the call brings into being: that must keep working
        mutex = project / "qa-factory" / "state" / ".dashboard-writer"
        with event_store.EventStore(mutex).lock():
            pass
        check("lock() on an absent generic folder still creates state/events.lock (the dashboard mutex)",
              (mutex / "state" / "events.lock").is_file())
        # JobStore: names a folder, creates nothing on a read
        jobs_dir = ghost / "state" / "execution-jobs"
        before = tree(project)
        reader = ER.JobStore(jobs_dir)
        check_eq("JobStore(<phantom>).jobs() is []", reader.jobs(), [])
        check_eq("JobStore(<phantom>).read(key) is None", reader.read("k"), None)
        try:
            reader.recover("k", lambda pid, at: False)
            check("JobStore(<phantom>).recover(unknown key) raises RequestError", False)
        except ER.RequestError as exc:
            check_eq("JobStore(<phantom>).recover(unknown key): the old text", str(exc), "unknown execution job")
        check_eq("none of the reads made a folder", tree(project), before)
        writer = ER.JobStore(artifacts / "TP3-1" / "state" / "execution-jobs")
        check("the constructor made no folder", not writer.directory.exists())
        action, job = writer.begin({"idempotency_key": "k1", "task": "TP3-1"})
        check_eq("the first begin launches (the positive control)", action, "launch")
        check("...and made the folder under the story", writer.directory.is_dir())
        before = tree(project)
        # baseline receipt
        kind, text = outcome(baseline_contract.write_baseline_receipt, ghost, {}, {}, ghost / "s.json")
        check("write_baseline_receipt(<phantom>): R-under", kind == "refused" and "which does not exist" in text, text)
        check_eq("...and nothing was made", tree(project), before)


def the_creators_refuse_a_story_that_is_not_there_and_write_under_one_that_is():
    """One row per U-site class (3.2): the creator under a missing root refuses and writes nothing; under a root that
    exists the same creator writes. Every refusal is a line, never a traceback (plan review F-2)."""
    with a_project() as (project, artifacts):
        before = tree(project)
        request = project / "request.json"
        request.write_text(json.dumps({"task": PHANTOM, "idempotency_key": "k", "purpose": "ordinary"}), encoding="utf-8")
        receipt = project / "receipt.json"
        receipt.write_text("{}", encoding="utf-8")
        fragment = project / "fragment.json"
        fragment.write_text(json.dumps({"note": "x", "tests": []}), encoding="utf-8")
        before = tree(project)
        for name, args in (
                ("run_suite --request (E-7: the key comes from outside)", ("run_suite.py", "--request", request)),
                ("run_suite --task --label --detail", ("run_suite.py", "--task", PHANTOM, "--label", "x", "--detail", "t")),
                ("retro_numbers --write-retro", ("retro_numbers.py", "--task", PHANTOM, "--write-retro")),
                ("repo_map", ("repo_map.py", "--task", PHANTOM, "--cases", "TC-1")),
                ("manifest_put", ("manifest_put.py", "--task", PHANTOM, "--fragment", fragment)),
                ("manifest_from_tests", ("manifest_from_tests.py", "--task", PHANTOM, "--dispatch", "d", "--file", "t.py")),
                ("manifest_from_tests --dry-run", ("manifest_from_tests.py", "--task", PHANTOM, "--dispatch", "d",
                                                    "--file", "t.py", "--dry-run")),
                ("import_test_receipt", ("import_test_receipt.py", "--request", request, "--receipt", receipt)),
                ("brief_pack", ("brief_pack.py", "--task", PHANTOM, "--stage", "S5", "--role", "qa-automator",
                                "--dispatch", "d")),
                ("probe_by_code", ("probe_by_code.py", "--task", PHANTOM, "--dispatch", "d", "--test", "t.py::t",
                                   "--instance", "i", "--mutation", "invert"))):
            done = cli(*map(str, args), project=project)
            words = done.stdout + done.stderr
            check(f"{name}: refused (a non-zero exit)", done.returncode != 0, f"rc {done.returncode}: {words[-200:]}")
            check_in(f"{name}: says the story is not there", PHANTOM, words)
            check_not_in(f"{name}: no traceback", NO_TRACEBACK, words)
            check_eq(f"{name}: not a byte written in the project", tree(project), before)
        check_in("run_suite --request: R2 with the request's task named", "the request's task", cli(
            "run_suite.py", "--request", request, project=project).stderr)
        # under a story that exists the same creators write
        (artifacts / "TP3-1" / "pipeline.json").write_text("{}", encoding="utf-8")
        import retro_numbers
        written = retro_numbers.write_retro("TP3-1", feedback="fine")
        check("retro_numbers.write_retro: the story is there, the retro is written", written["retro"].is_file())
        kind, text = outcome_value(retro_numbers.write_retro, "TP3-1", None, artifacts / PHANTOM)
        check("retro_numbers.write_retro(<given phantom root>): R-under", kind == "refused" and "does not exist" in text, text)
        import run_suite
        check("run_suite.evidence_dir(<story>) makes evidence/ under it (the positive control)",
              same_folder(run_suite.evidence_dir("TP3-1"), artifacts / "TP3-1" / "evidence")
              and (artifacts / "TP3-1" / "evidence").is_dir())
        kind, text = outcome(run_suite.evidence_dir, PHANTOM)
        check("run_suite.evidence_dir(<phantom>) is refused", kind == "refused", text)
        kind, text = outcome(run_suite.write_run_block, PHANTOM, {"attempt_id": "a"})
        check("run_suite.write_run_block(<phantom>) is refused", kind == "refused", text)
        check_eq("...and no folder", (artifacts / PHANTOM).exists(), False)


def the_hooks_never_make_a_story_folder():
    """Class 5 (3.5, E-8): a hook asks the leaf and never raises; a denial for a phantom ticket is kept in the project's list."""
    import exit_gate
    import inject_context
    import execution_request as ER
    with a_project() as (project, artifacts):
        check_eq("exit_gate._findings_path(<phantom>) is None (the story is unknown)",
                 exit_gate._findings_path("qa-scout", PHANTOM), None)
        check("exit_gate._findings_path(<story>) is a path under it (the positive control)",
              same_folder(exit_gate._findings_path("qa-scout", "TP3-1"),
                          artifacts / "TP3-1" / "state" / "findings" / "exit-gate-qa-scout.txt"))
        before = tree(project)
        inject_context.note_denial({}, PHANTOM, "S5", "qa-automator", "denied for a test")
        listed = project / "qa-factory" / "state" / "dispatch-denials.jsonl"
        check("note_denial(<phantom ticket>): the denial is in the project's list, not lost", listed.is_file()
              and "denied for a test" in listed.read_text(encoding="utf-8") and PHANTOM in listed.read_text(encoding="utf-8"))
        check_eq("...and no folder was made", (artifacts / PHANTOM).exists(), False)
        check_eq("...nothing else changed", [p for p, _ in tree(project) if p not in dict(before)],
                 ["qa-factory/state/dispatch-denials.jsonl"])
        inject_context.note_denial({}, "TP3-1", "S5", "qa-automator", "denied for a story")
        story_list = artifacts / "TP3-1" / "state" / "dispatch-denials.jsonl"
        check("note_denial(<story>): the denial is in the story's own list (the positive control)", story_list.is_file())
        kind, text = outcome_value(ER.build_mine_request, project, ["TC-1"], task=PHANTOM, evidence_only=True)
        check("build_mine_request(evidence_only, <phantom>): a MineRefusal", kind == "refused" and "names no story folder" in text, text)
        check_eq("...and no folder", (artifacts / PHANTOM).exists(), False)


def s0_still_creates_the_story_folder():
    """I7 / M-A11: the S0 road (`ticket_adapter.write_snapshot` -> `source_inventory._atomic_write`) makes the folder; a
    guard added there would end the pipeline before it starts."""
    import ticket_adapter
    with a_project() as (project, artifacts):
        new = artifacts / "TP3-NEW"
        check("TP3-NEW does not exist yet", not new.exists())
        try:
            ticket_adapter.write_snapshot({"key": "TP3-NEW", "fields": {}}, new / "work" / "ticket-snapshot.json")
        except SystemExit as exc:         # the adapter ends the process on a write it cannot make: a failed row, not an abort
            check("S0's snapshot write did not end the process", False, f"exit {exc.code}")
        check("S0's snapshot write CREATES the story folder", (new / "work" / "ticket-snapshot.json").is_file())
        check_eq("...and the leaf now says it is a story", hooklib.is_story_folder(artifacts, "TP3-NEW"), True)


RESOLVERS = {            # (file, function) -> the class-1 resolvers; each decides through the driver, none lists on its own
    ("story_step.py", "_task_root"), ("source_exclusions.py", "_task_root"), ("stand_identity.py", "_task_root"),
    ("stand_gaps.py", "resolve_task_root"), ("handoff_init.py", "task_root"), ("bug_records.py", "_story_exists"),
    ("sizing.py", "main"), ("inject_context.py", "note_denial"), ("exit_gate.py", "_findings_path"),
    ("controller.py", "_cli_story_root")}
DRIVERS = {"story_root", "story_root_at", "story_of", "story_cli", "is_story_folder"}


def resolver_offenders(source, wanted):
    """The (file, function) pairs of `wanted` whose function does not call a driver or calls `artifacts_dir` directly."""
    tree_ = ast.parse(source)
    found = {}
    for node in ast.walk(tree_):
        if isinstance(node, ast.FunctionDef):
            calls = {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""))
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            found[node.name] = calls
    return sorted(name for name in wanted if name not in found or not (found[name] & DRIVERS) or "artifacts_dir" in found[name])


def every_story_resolver_calls_the_one_rule():
    """The class detector (3.6, A): the resolvers are the functions above; a new one that lists a folder on its own
    is a second rule (axis 8). The positive control is a temporary COPY of a file with the call taken out."""
    per_file = {}
    for file, function in sorted(RESOLVERS):
        per_file.setdefault(file, set()).add(function)
    for file, functions in per_file.items():
        source = (SCRIPTS / file).read_text(encoding="utf-8")
        check_eq(f"{file}: {sorted(functions)} call a driver and not artifacts_dir (the tree is green)",
                 resolver_offenders(source, functions), [])
        mutant = source
        for driver in DRIVERS:
            mutant = mutant.replace(driver + "(", "artifacts_dir(")
        check_eq(f"{file}: the positive control - the same file with the drivers swapped for artifacts_dir is red",
                 resolver_offenders(mutant, functions), sorted(functions))
    # A2 (t-1230): the story_root result IS the root `run_suite --request` uses - one computation, no artifacts_dir(raw_task)
    suite_tree = ast.parse((SCRIPTS / "run_suite.py").read_text(encoding="utf-8"))
    kept_root = [n for n in ast.walk(suite_tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                 and getattr(n.value.func, "id", "") == "story_root" and n.value.args
                 and getattr(n.value.args[0], "id", "") == "raw_task"]
    recomputed = [n for n in ast.walk(suite_tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "artifacts_dir"
                  and n.args and getattr(n.args[0], "id", "") == "raw_task"]
    check("run_suite --request: story_root(raw_task) is assigned and used as the root", len(kept_root) == 1, len(kept_root))
    check_eq("run_suite --request: artifacts_dir(raw_task) is not computed again", len(recomputed), 0)
    # [converted by B] the --task-root branch of the controller is on story_root_at once B is merged: RED on a tree
    # without B (the branch is still taken as given there), GREEN on the merged tree. The row is the AFTER state.
    controller_source = (SCRIPTS / "controller.py").read_text(encoding="utf-8")
    controller_calls = set()
    for node in ast.walk(ast.parse(controller_source)):
        if isinstance(node, ast.FunctionDef) and node.name == "_cli_story_root":
            controller_calls |= {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""))
                                 for c in ast.walk(node) if isinstance(c, ast.Call)}
    check("controller._cli_story_root: the --task-root branch decides through story_root_at "
          "[converted by B]", "story_root_at" in controller_calls, sorted(controller_calls & DRIVERS))


BATTERIES = (the_resolvers_of_class_1_say_yes_no_phantom_and_refuse_an_abbreviation,
             the_helpers_below_the_root_create_only_under_one_that_exists,
             the_creators_refuse_a_story_that_is_not_there_and_write_under_one_that_is,
             the_hooks_never_make_a_story_folder, s0_still_creates_the_story_folder,
             every_story_resolver_calls_the_one_rule,
             the_leaf_says_yes_only_to_an_exact_folder, story_root_decides_through_the_leaf_and_keeps_its_texts,
             a_path_is_a_story_when_its_last_component_is, r1_prime_names_the_projects_own_artifact_root,
             the_pair_of_flags_is_one_story_or_one_refusal, a_given_project_is_where_the_key_resolves,
             story_cli_turns_a_listing_error_into_its_refusal, the_cli_form_refuses_on_stderr_and_the_guarded_form_raises,
             exact_options_turns_abbreviations_off_everywhere_it_can_see, no_refusal_carries_the_phrase_the_driver_reads)


def main():
    """Every battery runs: one that stops on an exception is a FAIL row with the exception's first line, counted with
    the rest, so a mutation shows every row it breaks and not the first traceback."""
    for battery in BATTERIES:
        try:
            battery()
        except Exception as exc:  # noqa: BLE001 - a traceback is a failed row here, never the end of the run
            lines = (str(exc).splitlines() or [""])
            check(f"{battery.__name__}: ran to the end", False, f"{type(exc).__name__}: {lines[0]}")
    finish("test_story_root_class")


if __name__ == "__main__":
    main()
