#!/usr/bin/env python3
"""Set aside an artifact of your own that nothing in it can be continued from.

    artifact_supersede.py --task T --path work/test-plan.json --role qa-test-strategist \\
                          --reason "the file holds 3 rows of a run that was cut off; none match the register"

TP1-13877, 28.09: a network failure cut the strategist's write of `test-plan.json` after 3
rows. The guard refused a Write over a plan that holds rows, the plan had no other door open to a
role, and the only way on was a person deleting the file by hand: a ban with no door (FR-57).
This is that door. A role that was interrupted continues its artifact by default - it keeps the
rows that parse and pass their check, repairs the stale ones (`plan_row.py`), adds the rest - and
comes here only when nothing in the file is usable.

What it does: the file moves to `<name>.superseded` (or `.superseded-2`, `-3`, the first name
that is free) and the story's `pipeline.json` gets one warning line saying what was set aside, by
whom and why; the role's next Write of the path is then its first. Nothing reads the `.superseded`
file afterwards: it is evidence, and restoring it is the role's own Write from its content.

What it does not do: judge. Whether nothing is usable is the role's call and it is written down as
the reason. It refuses a file that is not the role's (the registry `references/artifact-writers.json`
names the writer of every artifact), a directory, a path outside the story, and a reason that is
empty, longer than one line or over 200 characters - each with what to do instead (FR-1).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import artifact_sections as AS  # noqa: E402
import hooklib  # noqa: E402
from role_cli import command_from_argv, refuse, run_guarded  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

COMMAND = "artifact_supersede.py"
REASON_MAX = 200
MARK = ".superseded"


def writer_of(rel: str, registry: dict) -> str | None:
    """The registry's writer of a task-relative path: its own entry, else the directory entry it
    lies under. None when the registry does not know the path at all.

    A path under `work/` that the registry keeps at the task root is looked up there too
    (`work/test-plan.md`, which is where the plan guard watches, against the registry's
    `test-plan.md`): the guard names this command with the path it refused, and a door that answers
    "no writer" to it is the dead end FR-57 forbids."""
    for name in (rel, rel[len("work/"):] if rel.startswith("work/") else ""):
        if not name:
            continue
        entry = registry.get(name)
        if isinstance(entry, dict):
            return str(entry.get("writer") or "")
        best = ""
        for key, value in registry.items():
            if key.endswith("/") and name.startswith(key) and len(key) > len(best) and isinstance(value, dict):
                best = key
        if best:
            return str(registry[best].get("writer") or "")
    return None


def stage_of(rel: str, role: str) -> str:
    """The stage whose outputs hold the path (the one the role works in first), else `story`."""
    found = []
    names = {rel, rel[len("work/"):] if rel.startswith("work/") else rel}   # see `writer_of`
    for stage in hooklib.load_ref_json("stages.json").get("stages") or []:
        for out in stage.get("outputs") or []:
            if any(out == name or (str(out).endswith("/") and name.startswith(str(out))) for name in names):
                found.append(stage)
                break
    mine = [s for s in found if role in (s.get("roles") or [])]
    pick = (mine or found or [{}])[0]
    return str(pick.get("id") or "story")


def size_of(path: Path) -> str:
    """`N rows` for a JSON artifact that holds a list of rows, else the bytes."""
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = AS.rows_of(data)             # the one plan-row reader: a bare array, or the first of rows / items / plan
            if rows:
                return f"{len(rows)} rows"
        except (OSError, ValueError, AttributeError):
            pass
    return f"{path.stat().st_size} bytes"


def free_name(target: Path) -> Path:
    first = target.with_name(target.name + MARK)
    if not first.exists():
        return first
    number = 2
    while target.with_name(f"{target.name}{MARK}-{number}").exists():
        number += 1
    return target.with_name(f"{target.name}{MARK}-{number}")


def siblings(target: Path) -> list:
    return sorted_paths(p for p in target.parent.glob(target.name + MARK + "*") if p.is_file())


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--path", required=True, help="the artifact, relative to the task root")
    ap.add_argument("--role", required=True, help="the role that writes it, e.g. qa-test-strategist")
    ap.add_argument("--reason", required=True, help="one line, at most 200 characters: why nothing in it is usable")
    ap.add_argument("--task-root", default=None, dest="task_root")
    ns = hooklib.exact_options(ap).parse_args()
    try:        # the story first (CX1-18): both flags name ONE existing folder or this refuses, on this script's channel
        story = hooklib.story_of(COMMAND, key=ns.task, root=ns.task_root)
    except ValueError as exc:
        return refuse(COMMAND, str(exc))

    reason = str(ns.reason)
    if not reason.strip():
        return refuse(COMMAND, "--reason is empty. Say in one line why nothing in the file can be continued "
                               "(what you looked at and what it lacked): the line goes into the story's warnings "
                               "and is what a person reads about this file")
    if "\n" in reason or "\r" in reason:
        return refuse(COMMAND, "--reason has more than one line. Give one line of at most "
                               f"{REASON_MAX} characters; the long version belongs in your findings")
    if len(reason) > REASON_MAX:
        return refuse(COMMAND, f"--reason is {len(reason)} characters; the limit is {REASON_MAX}. Shorten it to "
                               "the one thing that made the file unusable")

    task_root = story.resolve()
    if ns.task_root and Path(ns.task_root).resolve() != task_root:
        # The warning is written by `stage_done.py --task`, which knows no other root than the story's
        # own: setting aside a file of one root and recording it in another would leave a story with a
        # missing artifact and no line saying why.
        return refuse(COMMAND, f"--task-root {Path(ns.task_root).resolve()} is not the task root of {ns.task}, "
                               f"which is {task_root}. Leave --task-root out, or pass that path")
    given = str(ns.path).replace("\\", "/").strip()
    # `project:x` names a file of the project, not of the story; an absolute path or `..` is judged
    # after it is resolved, by the one test below.
    target = None if given.startswith("project:") else (task_root / given).resolve()
    if target is None or not target.is_relative_to(task_root):
        return refuse(COMMAND, f"`{given}` is not inside this story's task root ({task_root}). Only an artifact of "
                               "the story can be set aside here; pass its path relative to the task root, "
                               "e.g. work/test-plan.json")
    rel = target.relative_to(task_root).as_posix()

    if target.is_dir():
        return refuse(COMMAND, f"`{rel}` is a directory. Set aside one file at a time: name the file inside "
                               "it that nothing can be continued from")
    if not target.is_file():
        older = siblings(target)
        if older:
            return refuse(COMMAND, f"`{rel}` does not exist: it was already set aside as `{older[-1].name}`. "
                                   "Your next Write of it is its first - write it now")
        return refuse(COMMAND, f"`{rel}` does not exist under {task_root}, so there is nothing to set aside. "
                               "If it was never written, write it (a first Write is never refused)")

    registry = hooklib.load_ref_json("artifact-writers.json").get("artifacts") or {}
    writer = writer_of(rel, registry)
    if writer != f"{ns.role} (the role)":
        who = (f"its writer is `{writer}`" if writer else "the registry (references/artifact-writers.json) names no "
                                                            "writer for it")
        return refuse(COMMAND, f"`{rel}` is not an artifact of {ns.role}: {who}. Only the role that writes an "
                               "artifact sets it aside. Pass that role in --role if you are it; otherwise hand the "
                               "problem to the writer, or file it in your findings")

    stage = stage_of(rel, ns.role)
    what = size_of(target)
    new = free_name(target)
    os.replace(target, new)
    warn = f"{stage}: {rel} set aside as {new.name} ({what}) by {ns.role}: {reason.strip()}"
    done = subprocess.run([sys.executable, "-B", str(HERE / "stage_done.py"), "--task", ns.task, "--warn", warn],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ))
    if done.returncode:
        os.replace(new, target)  # nothing may be set aside without the line that says so
        tail = " ".join((done.stderr or done.stdout or "").split())[-300:]
        return refuse(COMMAND, f"`{rel}` was not set aside: the story's warning could not be recorded "
                               f"(stage_done.py exit {done.returncode}: {tail}). The file is back where it was; "
                               "run this again once `pipeline.json` of the story exists")
    print(f"{rel}: set aside as {new.name} ({what})")
    print(f"your next Write of {rel} is its first")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_guarded(command_from_argv(COMMAND), main))
