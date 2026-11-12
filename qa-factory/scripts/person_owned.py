#!/usr/bin/env python3
"""THE one reader of `references/person-owned.json` (RN1-9, P22, FR-48, AR-17).

What only a person can know or decide is a CLASS of that file; a question to a person names one (`why_person`) and says what
the conductor read first (`checked`). The class list is data (AR-1); this module reads it, checks a token against it, builds
the one refusal sentence both roads use (the driver's `no_move.validate_options`, the interactive road's `waiver.py`), and
counts the detector's share (calibration check 38). Nothing here reads a person's or a role's wording (FR-12): a class is a
token compared to a list.

  person_owned.py --check                          the file reads (exit 0) or does not (exit 2, with the reason)
  person_owned.py --share --task-root <T> [--json] the detector's numbers for one task's artifacts
"""
import argparse
import json
import re
import sys
from pathlib import Path

import hooklib

FILE_NAME = "person-owned.json"
CHECKED_LIMIT = 300  # same as contract.PROBE_GAP_WHY_LIMIT; the `…` cut mark counts in the 300
ID_RE = re.compile(r"^[a-z][a-z_]*$")
SOURCES = ("conductor", "fallback", "code", "delivery")

CONDUCTOR_DOOR = ("settle it yourself from what the code left, or answer again with `why_person` set to one of these "
                  "and `checked` naming what you read")
WAIVER_DOOR = ("record again with `--why-person <id>`, one of these ids, or without the flag "
               "(the word is then recorded and counted unclassified)")


class PersonOwnedUnreadable(Exception):
    """`person-owned.json` is absent, broken or malformed; the message says why (one sentence)."""


def _one_line(value, limit: int) -> str:
    """Whitespace folded, at most `limit` characters, the cut marked by `…` (which counts). A local 3-line helper:
    the fold-and-cut one-liner class is queued for ONE survivor (see the handoff), `contract.py` is not this node's."""
    one = " ".join(str(value or "").split())
    return one if len(one) <= limit else one[:limit - 1] + "…"


def load(path=None) -> dict:
    """The file as a dict, or `PersonOwnedUnreadable(why)`. `path=None` is the shipped file (`hooklib.load_ref_json`)."""
    if path is None:
        data = hooklib.load_ref_json(FILE_NAME)
        if not data:
            raise PersonOwnedUnreadable(f"references/{FILE_NAME} is absent, empty or not JSON")
    else:
        data = hooklib.read_json(path, None)
        if data is None:
            raise PersonOwnedUnreadable(f"{path} is absent, empty or not JSON")
    if not isinstance(data, dict):
        raise PersonOwnedUnreadable(f"{FILE_NAME} is not a JSON object")
    classes = data.get("classes")
    if not isinstance(classes, list) or not classes:
        raise PersonOwnedUnreadable(f"{FILE_NAME}: `classes` must be a non-empty list of {{id, says}}")
    seen = []
    for row in classes:
        cid = row.get("id") if isinstance(row, dict) else None
        if not isinstance(cid, str) or not ID_RE.match(cid):
            raise PersonOwnedUnreadable(f"{FILE_NAME}: a class id must match {ID_RE.pattern} (got {cid!r})")
        if not isinstance(row.get("says"), str) or not row["says"].strip():
            raise PersonOwnedUnreadable(f"{FILE_NAME}: class `{cid}` has no `says`")
        if cid in seen:
            raise PersonOwnedUnreadable(f"{FILE_NAME}: class id `{cid}` appears twice")
        seen.append(cid)
    routes = data.get("code_routes", {})
    if not isinstance(routes, dict):
        raise PersonOwnedUnreadable(f"{FILE_NAME}: `code_routes` must be an object")
    for name, cid in routes.items():
        if cid not in seen:
            raise PersonOwnedUnreadable(f"{FILE_NAME}: code route `{name}` names `{cid}`, which is not a class id")
    return data


def class_ids() -> tuple:
    return tuple(row["id"] for row in load()["classes"])


def normalize(value) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def as_class(value) -> str:
    """THE one test "is this a class id" (m-6): the normalized id when `value` is a class of the file, else "" (also "" when the
    file cannot be read: an unread list classifies nothing, and `status()` names the defect)."""
    norm = normalize(value)
    try:
        return norm if norm in class_ids() else ""
    except PersonOwnedUnreadable:
        return ""


def class_rule(why, checked, door: str) -> str:
    """"" when `why` is a class id AND `checked` holds a non-space character; else ONE sentence: what is missing, the ids with
    what each says, then the caller's own `door` verbatim. An unreadable file gives "" (FR-59: a question a person must answer
    is never withheld by our data defect; `status()` names the defect)."""
    try:
        classes = load()["classes"]
    except PersonOwnedUnreadable:
        return ""
    missing = []
    if not as_class(why):
        missing.append("`why_person` is absent" if not normalize(why) else "`why_person` is not a class of references/person-owned.json")
    if not (isinstance(checked, str) and checked.strip()):
        missing.append("`checked` is empty")
    if not missing:
        return ""
    listing = "; ".join(f"`{row['id']}` ({row['says']})" for row in classes)
    return f"a question to a person needs a class and what you read: {' and '.join(missing)}; the classes are {listing}; {door}"


def question_rule(why, checked) -> str:
    return class_rule(why, checked, CONDUCTOR_DOOR)


def status() -> str:
    try:
        load()
    except PersonOwnedUnreadable as why:
        return f"unread: {why}"
    return "ok"


def code_route(name):
    """The class of a code route (a `story_run.KNOWN_REFUSALS` row whose action is `ask_person`); None when absent or unreadable."""
    try:
        return load().get("code_routes", {}).get(name)
    except PersonOwnedUnreadable:
        return None


def checked_text(value) -> str:
    return _one_line(value, CHECKED_LIMIT)


DRIVER_BY = "driver"   # `by` of a word the DRIVER recorded (story_run `waiver_road`); every other `by` is the interactive road


def share(task_root) -> dict:
    """The detector's numbers (calibration check 38) for one task's artifacts. Absent sources are zeros, an entry without the
    key is unclassified, and `needless` is the string "unknown": only the run review knows whether an answer lay in the
    factory's evidence (FR-41), code never prints a number for it.

    Two word counters, never mixed (B-1): `words` is the INTERACTIVE road's (the conductor in a session recording with
    `waiver.py`; check 38's ">50 % unclassified" counts this one ONLY), `driver_words` is the driver's own recordings
    (`by` = `driver`, which carry the asked question's class when it had one)."""
    from retro_numbers import read_jsonl  # lazy: retro_numbers is huge and this module is imported by waiver/no_move/story_run
    root = Path(task_root)
    rows = [r for r in read_jsonl(root / "state" / "driver-questions.jsonl") if isinstance(r, dict)]
    by_source = {name: 0 for name in SOURCES}
    by_class = {}
    classified = unread = 0
    for row in rows:
        if row.get("source") in by_source:
            by_source[row["source"]] += 1
        cid = as_class(row.get("why_person"))
        if cid:
            classified += 1
            by_class[cid] = by_class.get(cid, 0) + 1
        if str(row.get("class_check") or "").startswith("unread"):
            unread += 1
    pipeline = hooklib.read_json(root / "pipeline.json", {}, kind=dict)
    counts = {"interactive": {"classified": 0, "unclassified": 0}, "driver": {"classified": 0, "unclassified": 0}}
    for key in ("stage_overrides", "gate_waivers", "remarks"):
        entries = pipeline.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            road = "driver" if entry.get("by") == DRIVER_BY else "interactive"
            counts[road]["classified" if as_class(entry.get("why_person")) else "unclassified"] += 1
    return {"questions": len(rows), "classified": classified, "unclassified": len(rows) - classified,
            "by_source": by_source, "by_class": by_class, "class_check_unread": unread,
            "words": counts["interactive"], "driver_words": counts["driver"], "needless": "unknown"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the one reader of references/person-owned.json")
    ap.add_argument("--check", action="store_true", help="the file reads; exit 2 with the reason when it does not")
    ap.add_argument("--file", help="with --check: read this file instead of the shipped one (negative controls)")
    ap.add_argument("--share", action="store_true", help="the detector's numbers for --task-root")
    ap.add_argument("--task-root", help="the task's artifacts directory (with --share)")
    ap.add_argument("--json", action="store_true", help="with --share: JSON instead of lines")
    args = ap.parse_args(argv)
    if args.check == args.share:
        ap.error("give exactly one of --check, --share")
    if args.check:
        try:
            data = load(args.file)
        except PersonOwnedUnreadable as why:
            print(f"person-owned: {why}")
            return 2
        print(f"person-owned: ok ({len(data['classes'])} classes, {len(data.get('code_routes', {}))} code routes)")
        return 0
    if not args.task_root:
        ap.error("--share needs --task-root <path>")
    result = share(args.task_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for key, value in result.items():
            print(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
