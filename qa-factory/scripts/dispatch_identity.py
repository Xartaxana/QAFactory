#!/usr/bin/env python3
"""Which dispatch is this? The ONE reader (spec t-1937 B1, TR3-13; AR-13, AR-15, AR-28).

Before parallel S5 windows a story had one running dispatch of a role, so "the running dispatch of this role on this stage"
was a count (`live[0] if len(live) == 1 else None`) and every site of the S5 exit copied it. With two windows running the count
answers "none" at best and, at a site that treats none as "every case", judges one window by the other's work. A session
that was started as dispatch `D` carries `D` in its environment (`QA_FACTORY_DRIVER_RUN`, set by the driver for the child;
hooks and the child's own tools inherit it - measured in TR3-13 Step 0), and the exit gate names the finisher to its
detectors (`QA_FACTORY_DETECTOR_DISPATCH`). This module reads both.

ERROR DIRECTION (a function that picks whose work a gate judges): it may answer None; it must never answer another window's
dispatch. A name that is found but does not fit (closed, another role, another stage) is None - NOT the count rule. Only a name
this story's records do not hold (another story's id, a stale word) falls to the count rule, which at two or more is None.

Code reads data here: ids, statuses, roles, stages. Whether the dispatch is the right one to judge is the caller's gate.
"""
from __future__ import annotations

import os

DRIVER_RUN_ENV = "QA_FACTORY_DRIVER_RUN"      # the driver sets it for a child it starts (`story_run`, B-250): the child's dispatch id
DETECTOR_DISPATCH_ENV = "QA_FACTORY_DETECTOR_DISPATCH"   # the exit gate names the finisher to its detectors (`exit_gate._detector_env`); the literal lives HERE so `named()` imports nothing (AR-12)
RUNNING = "running"


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def named() -> str:
    """The dispatch id this process was told it works for, or "": `QA_FACTORY_DETECTOR_DISPATCH` first (the gate names the
    finisher), then `QA_FACTORY_DRIVER_RUN`; stripped; a blank word is unset."""
    return _clean(os.environ.get(DETECTOR_DISPATCH_ENV)) or _clean(os.environ.get(DRIVER_RUN_ENV))


def records(dispatches) -> list:
    """`dispatches` (a mapping id -> record, or a list of records) as a list of record copies, each with its `id` filled
    (the record's `id`, else `dispatch_id`, else the mapping key). Non-dict rows, a non-collection and None read as nothing."""
    rows = []
    if isinstance(dispatches, dict):
        for key, record in dispatches.items():
            if isinstance(record, dict):
                rows.append(dict(record, id=_clean(record.get("id")) or _clean(record.get("dispatch_id")) or str(key)))
    elif isinstance(dispatches, (list, tuple)):
        for record in dispatches:
            if isinstance(record, dict):
                ident = _clean(record.get("id")) or _clean(record.get("dispatch_id"))
                rows.append(dict(record, id=ident))
    return rows


def held(dispatches, name: str | None = None) -> list:
    """The records of `dispatches` whose id is `name` (default `named()`); [] when there is no name or this story holds none.
    The ONE spelling of "does this story hold the name?" (AR-13): `own`, the guard's owner check and the typed-runner check
    read it; a change of the duplicate rule (two records of one id) lands here. Never raises."""
    try:
        word = _clean(name) or named()
        return [r for r in records(dispatches) if r["id"] == word] if word else []
    except Exception:
        return []


def _fits(record: dict, role: str, stage: str, statuses) -> bool:
    return (record.get("status") in statuses
            and (not role or str(record.get("role") or "") == role)
            and (not stage or str(record.get("stage") or "") == stage))


def own(dispatches, role: str = "", stage: str = "", statuses=(RUNNING,), name: str | None = None) -> dict | None:
    """The record of the dispatch this process works for, or None.

    With a name (`named()`, or `name=` when the caller holds one; a blank `name` is "no name"): the record with that id; it is
    the answer when its status is in `statuses` and its role/stage match when asked; found and not fitting: None (never the
    count rule). A name no record holds: the count rule. No name: the count rule, exactly the one every site had:
    `live[0] if len(live) == 1 else None`, `live` being the records that fit. Never raises on awkward input."""
    try:
        rows = records(dispatches)
        found = held(rows, name)
        if found:
            return found[0] if len(found) == 1 and _fits(found[0], role, stage, statuses) else None
        live = [r for r in rows if _fits(r, role, stage, statuses)]
        return live[0] if len(live) == 1 else None
    except Exception:
        return None
