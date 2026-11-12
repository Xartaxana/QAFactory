#!/usr/bin/env python3
"""Which findings file belongs to this critic dispatch? The ONE resolver (t-2098/t-2106, TR3-5; AR-13, AR-14, AR-19).

The code critic of a window writes `work/test-code/critic-findings-<its dispatch>.md`, one file per dispatch, so that two windows
never share a findings file. Every reader of "the critic's findings of this dispatch" asks here: the brief (`brief_pack`), the form
deriver (`handoff_check`), the author round (`story_run`), the finish evidence (`story_step`), the ledger's remarks pointer
(`ledger`) and the status line (`stage_status`). The S4 case critic's files (`work/test-cases/**/critic-findings*.md`) have their
own reader here, `s4_files`; the two stages never read each other's files.

The one legitimate fallback is the single file of a story started before findings went one per dispatch (`critic-findings.md` in
the S5 folder) - and only while the story has ONE window: when the S5 code critics review two or more different scopes, the old
name could be a neighbour window's file, so it answers nothing (t-2106 X1).

ERROR DIRECTION: the answer may be "" (no file); it must never be another window's file. Code reads data here: names, presence,
scopes of the controller's records.
"""
from __future__ import annotations

import json
from pathlib import Path

import hooklib

S5_FOLDER = "work/test-code"
S4_FOLDER = "work/test-cases"
OLD_NAME = "critic-findings.md"
GLOB = "critic-findings*.md"
S4_PATTERN = f"{S4_FOLDER}/**/{GLOB}"      # the same files as `s4_files(root)`, as a pattern for a caller that takes the newest by mtime


def per_dispatch(dispatch) -> str:
    """The task-relative path of the findings file of `dispatch`, whether or not it exists; "" for a blank id."""
    ident = str(dispatch or "").strip()
    return f"{S5_FOLDER}/critic-findings-{ident}.md" if ident else ""


def old_file() -> str:
    """The task-relative path of the one findings file of a story from before one file per dispatch."""
    return f"{S5_FOLDER}/{OLD_NAME}"


def one_window(root) -> bool:
    """True when the story's S5 code critics review at most one scope (a story from before windows, or a single window), so the old
    single file can only be that window's. A record file that is absent holds no critics (True); one that cannot be read is
    unknown (False: the old name then answers nothing). Never raises."""
    path = Path(root) / "state" / "controller.json"
    if not path.is_file():
        return True
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        records = doc.get("dispatches") if isinstance(doc, dict) else None
        rows = list(records.values()) if isinstance(records, dict) else list(records or [])
        scopes = {tuple(sorted(str(c) for c in (r.get("scope") or [])))
                  for r in rows if isinstance(r, dict) and r.get("stage") == "S5" and r.get("role") == "qa-code-critic"}
        return len(scopes) <= 1
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def resolve(root, dispatch, allow_old: bool = True) -> str:
    """The task-relative findings file of `dispatch` when it exists, else (`allow_old`, one window only) the old single file when it
    exists, else "". A blank dispatch skips the first step. Never raises."""
    try:
        base = Path(root)
        own = per_dispatch(dispatch)
        if own and (base / own).is_file():
            return own
        if allow_old and (base / old_file()).is_file() and one_window(base):
            return old_file()
    except OSError:
        return ""
    return ""


def all_files(root) -> list:
    """Every S5 findings file of a story (per-dispatch and old), name order, as paths. For a reader that searches the files BY
    CONTENT for a case (the ledger's pointer), where the case, not the dispatch, picks the window. Never raises."""
    try:
        return hooklib.sorted_paths([p for p in (Path(root) / S5_FOLDER).glob(GLOB) if p.is_file()])
    except OSError:
        return []


def s4_files(root, nested: bool = True) -> list:
    """The S4 case critic's findings files under `work/test-cases/` (`nested`: the area folders too), name order, as paths. Never an
    S5 file. Never raises."""
    folder = Path(root) / S4_FOLDER
    try:
        found = folder.rglob(GLOB) if nested else folder.glob(GLOB)
        return hooklib.sorted_paths([p for p in found if p.is_file()])
    except OSError:
        return []
