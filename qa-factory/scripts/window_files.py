#!/usr/bin/env python3
"""Who wrote a test file first? The ONE writer of `state/window-files/` (spec t-1937 F3 b, TR3-16; AR-14, AR-25).

Two S5 windows of one story that run side by side must not both write one test file: the second Write or Edit lands on
the first's half-written text. The first window to write a test file CLAIMS it here; the guard (`guard_pre_tool.
window_file_check`) refuses a later window's write to a claimed file and names the door: a new file in the same directory.

A claim is one file, `<task root>/state/window-files/<sha1 of the project-relative key>.json`, created with
`O_CREAT|O_EXCL`, so of two sessions that race exactly one wins; the loser reads the winner. Content:
`{"path", "window", "dispatch", "at"}`. `window` is the dispatch's window id, `<stage>|<cases, sorted, joined by commas>`
(`window_id` below; `story_run.Driver.window_id` calls this one: one formatter).

A claim holds until `release` (spec: "a claim holds until release"): there is NO takeover and no liveness reading. A window
that is open between its dispatches (the critic accepted, a repair round waiting for a person) still holds its files, and a
grown round (`rework --cases <W'>`, a wider scope) is the same window. So OWN is by case intersection, not by id equality: an
owner window that shares a case with the asking window is the asker's own (`same_window`), in `claim` and in `release`.
A claim file with no readable content (a crash between create and write) has an UNKNOWN owner: it is never anyone's, only
`release` clears it once it is older than EMPTY_CLAIM_AGE_S.

The way out, for a person's word or the conductor: `python window_files.py --task <task root> --release "<window id>"`
(prints how many claims it freed). The driver calls `release` at a window's close (TR3-6).

ERROR DIRECTION: it may answer "another window's" when it is not; it must never answer "yours" for a file another window
holds. Standard library only (it runs in a hook on every write; AR-12). Code reads data here (paths, ids, files); whether a
file is a test body and whether a role may write is the guard's data check (AR-29: class safety).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

SUBDIR = Path("state") / "window-files"
EMPTY_CLAIM_AGE_S = 30       # `release` clears a claim with no content only when it is older than this (a creator may be mid-write)


def window_id(stage: str, cases) -> str:
    """`<stage>|<the cases, sorted and joined by commas>`: THE window key (`story_run.Driver.window_id` returns this)."""
    return f"{stage}|" + ",".join(sorted({str(c) for c in (cases or []) if c}))


def cases_of(window: str) -> str:
    """The cases part of a window id (`S5|TC-1,TC-2` -> `TC-1,TC-2`), for a text a person reads."""
    return str(window).split("|", 1)[-1]


def same_window(a: str, b: str) -> bool:
    """Is window id `a` the same window as `b`: the same id, or ids that share a case (a grown round `TC-1,TC-3` of `TC-1`)."""
    if a == b:
        return True
    mine = {c for c in cases_of(a).split(",") if c}
    return bool(mine & {c for c in cases_of(b).split(",") if c})


def project_rel(project, raw) -> str | None:
    """`raw` (any spelling a tool call gives: relative or absolute, `..`, backslashes) as a path relative to `project`
    with forward slashes and the case the file system keeps, or None when it lies outside the project (or cannot be read).

    The normaliser is the guard's own idiom (`guard_pre_tool` config/records checks): `Path.resolve()` then
    `os.path.normcase` for the comparison; the returned text keeps the resolved case, `key_of` folds it."""
    try:
        base = Path(project).resolve()
        target = Path(raw)
        target = (target if target.is_absolute() else base / target).resolve()
        folded = os.path.normcase(str(base)) + os.sep
        if not (os.path.normcase(str(target)) + os.sep).startswith(folded) or target == base:
            return None
        return Path(os.path.relpath(str(target), str(base))).as_posix()
    except Exception:
        return None


def key_of(rel: str) -> str:
    """The claim key of a project-relative path: forward slashes, `.`/`..` collapsed, the case folded where the file system
    folds it (`os.path.normcase`: Windows lower-cases, POSIX keeps). One file, one key, whatever the spelling."""
    text = os.path.normpath(str(rel).replace("\\", "/"))
    return os.path.normcase(text).replace("\\", "/")


def _dir(task_root) -> Path:
    return Path(task_root) / SUBDIR


def _file(task_root, rel: str) -> Path:
    return _dir(task_root) / (hashlib.sha1(key_of(rel).encode("utf-8")).hexdigest() + ".json")


def read_claim(path: Path):
    """The claim record, or None when the file is absent; {} when it exists and cannot be read (an unknown owner). THE one reader of a
    claim file (AR-13): this module and the driver's `s5_release_completed` read claims through it."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) and str(data.get("window") or "").strip() else {}


_read = read_claim      # the module's own call sites keep the old private name


def _create(path: Path, data: dict) -> bool:
    """O_EXCL create + write. True when this call made the file. The directory is made here (a hook may be first)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False))
    return True


def _owner_word(held) -> str:
    return str((held or {}).get("window") or "")


def claim(task_root, rel_path: str, window: str, dispatch: str) -> str:
    """Claim `rel_path` for `window`, or learn who holds it. Returns `window` when this call made the claim or the holder is the
    same window (`same_window`); another window's id when it holds it; "" when a claim file exists and cannot be read.
    A held claim is never taken over: only `release` frees it."""
    path = _file(task_root, rel_path)
    record = {"path": key_of(rel_path), "window": window, "dispatch": dispatch,
              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        if _create(path, record):
            return window
        held = _read(path)
        for _ in range(20):                           # a winner between its create and its write: wait for the content (200 ms),
            if held != {}:                            # a crash's empty file stays unknown after that
                break
            time.sleep(0.01)
            held = _read(path)
        if held is None:                              # released between the two calls: one more try, then read it
            return window if _create(path, record) else _verdict(window, _read(path))
        return _verdict(window, held)
    except Exception:
        return ""                                    # unreadable state: nobody's claim, the guard refuses with its note


def _verdict(window: str, held) -> str:
    owner = _owner_word(held)
    return window if owner and same_window(owner, window) else owner


def owner(task_root, rel_path: str):
    """The window holding `rel_path`; None when nobody claimed it; "" when the claim file cannot be read (unknown owner)."""
    held = _read(_file(task_root, rel_path))
    return None if held is None else _owner_word(held)


def files_of(task_root, window: str) -> list:
    """The project-relative keys `window` has claimed (`same_window`, like claim and release), sorted. Unreadable claim files are not any window's."""
    out = []
    try:
        for path in _dir(task_root).glob("*.json"):
            held = _read(path)
            if held and same_window(_owner_word(held), window) and held.get("path"):
                out.append(str(held["path"]))
    except Exception:
        return []
    return sorted(out)


def release(task_root, window: str, match=None) -> int:
    """Free every claim of `window` (the window id or any window sharing a case with it: a grown round frees the claims written
    under its first id), and every claim file with no readable content that is older than EMPTY_CLAIM_AGE_S (the door out of a
    crash between create and write). Returns the number removed. Never raises.
    `match` (TR4-10) replaces the test of a readable claim: a callable of the owner's window id, True to free it; the default is
    `same_window(owner, window)`. `release_stage` is the one caller that passes it: one loop, one empty-claim rule (AR-15)."""
    if match is None:
        def match(owner_window):
            return same_window(owner_window, window)
    removed = 0
    try:
        now = time.time()
        for path in _dir(task_root).glob("*.json"):
            held = _read(path)
            if held is None:
                continue
            if held:
                gone = bool(match(_owner_word(held)))
            else:
                try:
                    gone = now - path.stat().st_mtime > EMPTY_CLAIM_AGE_S
                except OSError:
                    gone = False
            if gone:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
    except Exception:
        pass
    return removed


def window_of_stage(window, stage: str) -> bool:
    """Does the window id belong to `stage` (it starts with `<stage>|`)? A missing or non-string window is of no stage. The ONE place
    that forms the stage prefix of a window id."""
    return isinstance(window, str) and window.startswith(f"{stage}|")


def release_stage(task_root, stage: str) -> int:
    """Free every claim of every window of `stage` (a claim whose `window` starts with `<stage>|`), plus the old empty claims that
    `release` clears. The driver calls it once the stage is completed and nothing of it can still write (`story_run.Driver.
    s5_release_completed`, TR4-10). Returns the number removed. Never raises."""
    prefix = f"{stage}|"
    return release(task_root, prefix, match=lambda owner_window: window_of_stage(owner_window, stage))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Free the test-file claims of an S5 window (the way out of a refused write).")
    parser.add_argument("--task", required=True, help="the story's folder: <project>/qa-factory/artifacts/<TICKET>")
    parser.add_argument("--release", required=True, metavar="WINDOW",
                        help='the window id, e.g. "S5|TC-1,TC-2" (also frees every window sharing a case with it)')
    args = parser.parse_args(argv)
    if not Path(args.task).is_dir():
        print(f"window_files: the task folder {args.task} does not exist; no claim was touched "
              "(check the --task path).", file=sys.stderr)
        return 2
    count = release(args.task, args.release)
    print(f"released {count} claim(s) of window {args.release}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
