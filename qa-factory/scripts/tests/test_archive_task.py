"""archive_task.py — what the doctor is allowed to offer to put away.

`archive_task.py --selftest` (run here as a subprocess, so a broken script fails this file
too) covers the writer: the refusal on open items, `--force`, `--undo`. What this file adds
is the OFFER — which stories `--candidates` names, and why. Until 0.7.13 the only answer was
"it has stood still for --days", a guess; a story the factory knows is closed is now offered
the day it closes, because TP2-2534 spent that waiting period in every listing while
its ghost `running` stage made a live story's dispatches ambiguous (I-92).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, \
    run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import archive_task as AT  # noqa: E402


def ago(delta: timedelta) -> str:
    """`delta` before now, in the shape `last_activity` reads: UTC, seconds, +00:00. The same
    clock `archive_task.stories` uses. Fixture dates are relative to the run because the rule
    under test is an age window: a calendar date written into a fixture silently turns the
    "in flight" story into a stalled one the day the window passes (it did, 2026-10-05)."""
    return (datetime.now(timezone.utc) - delta).isoformat(timespec="seconds")


# One hour ago, not a fixed date: the closed story must be a candidate WHILE its age is under
# --days, so the check keeps proving "closed, whatever the age" on any day. With a constant
# that is 14+ days old, the age rule alone would offer it and the check would pass vacuously.
CLOSED_AT = ago(timedelta(hours=1))
YESTERDAY = ago(timedelta(days=1))
STALE = "2026-08-01T10:00:00+00:00"  # meant to be old: on any day the test runs it stays old


def pipeline(closed: bool, running: str = "", halts: list | None = None) -> dict:
    """A pipeline.json built by hand, not by the writers of Package D: this file tests the
    reader, and a reader must cope with a story written by any version that ever shipped."""
    stages = {f"S{i}": {"status": "done", "finished": CLOSED_AT if closed else STALE}
              for i in range(10)}
    if running:
        stages[running] = {"status": "running", "started": CLOSED_AT}
    data = {"stages": stages, "halts": halts or [],
            "gates": {"A": {"decision": "approve", "at": STALE}}}
    if closed:
        data["closed_at"] = CLOSED_AT
        data["gates"]["B"] = {"decision": "approve", "at": CLOSED_AT}
    return data


def main() -> None:
    p = run_script("archive_task.py", "--selftest")
    check("archive_task.py --selftest is green", p.returncode == 0,
          (p.stdout or p.stderr).strip()[-600:])

    root = temp_project("qa-factory-archive-")
    arts = root / "qa-factory" / "artifacts"

    def story(name: str, data: dict) -> None:
        (arts / name).mkdir(parents=True, exist_ok=True)
        (arts / name / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")

    try:
        use_project(root)
        # Day 0 for the closed story: its newest timestamp is `closed_at` itself, so the
        # `--days 14` rule alone would not offer it for another fortnight.
        story("CLOSED-1", pipeline(closed=True))
        story("GHOST-1", pipeline(closed=True, running="S3"))
        story("LIVE-1", {"stages": {"S5": {"status": "running", "started": YESTERDAY}},
                         "gates": {"A": {"decision": "approve", "at": YESTERDAY}}})
        rows = {r["ticket"]: r for r in AT.stories(AT.DEFAULT_DAYS)}

        check_eq("a story closed today is a candidate at --days 14",
                 rows["CLOSED-1"]["candidate"], True)
        check_eq("and the row carries closed_at so the offer can say why",
                 rows["CLOSED-1"]["closed_at"], CLOSED_AT)
        check_eq("nothing asks a person about it — it is clean",
                 rows["CLOSED-1"]["open_items"], [])
        check_eq("a closed story with a ghost running stage is a candidate too",
                 rows["GHOST-1"]["candidate"], True)
        check_in("and open_items is unchanged: the tail is still named",
                 "S3 left running", rows["GHOST-1"]["open_items"])
        check_eq("a story genuinely in flight is not offered",
                 rows["LIVE-1"]["candidate"], False)
        check_eq("and carries no closed_at", rows["LIVE-1"]["closed_at"], "")

        listing = run_script("archive_task.py", "--candidates", "--days", "14", cwd=root).stdout
        check_in("--candidates prints the closed story", "CLOSED-1", listing)
        check_in("with the date it closed", "closed " + CLOSED_AT, listing)
        check_not_in("and never the one still running", "LIVE-1", listing)

        as_json = json.loads(run_script("archive_task.py", "--candidates", "--days", "14",
                                        "--json", cwd=root).stdout)
        check_eq("--json carries the same two candidates",
                 sorted(r["ticket"] for r in as_json["candidates"]), ["CLOSED-1", "GHOST-1"])

        # Compatibility: a story onboarded on 0.7.x has no `closed_at`, and no migration
        # writes one — gate B and S8 done say the same thing.
        legacy = pipeline(closed=True)
        legacy.pop("closed_at")
        story("LEGACY-1", legacy)
        rows = {r["ticket"]: r for r in AT.stories(AT.DEFAULT_DAYS)}
        check_eq("a 0.7.x story with no closed_at is read as closed",
                 rows["LEGACY-1"]["candidate"], True)
        check_eq("and the gate B decision time stands in for closed_at",
                 rows["LEGACY-1"]["closed_at"], CLOSED_AT)

        # The window itself: `age >= days` on the NEWEST timestamp, whole days. One hour of
        # margin either side keeps 13 and 14 unambiguous at any clock reading.
        def open_story(newest: timedelta) -> dict:
            stamp = ago(newest)
            return {"stages": {"S5": {"status": "running", "started": stamp}},
                    "gates": {"A": {"decision": "approve", "at": stamp}}}

        story("EDGE-13", open_story(timedelta(days=14) - timedelta(hours=1)))
        story("EDGE-14", open_story(timedelta(days=14) + timedelta(hours=1)))
        rows = {r["ticket"]: r for r in AT.stories(AT.DEFAULT_DAYS)}
        check_eq("newest activity 13 days old (age_days 13): not a candidate yet",
                 (rows["EDGE-13"]["age_days"], rows["EDGE-13"]["candidate"]), (13, False))
        check_eq("newest activity 14 days old (age_days 14): a candidate — the rule is >=",
                 (rows["EDGE-14"]["age_days"], rows["EDGE-14"]["candidate"]), (14, True))

        # `last_activity` is the MAX over stages, gates and halts: each story below has its one
        # recent stamp in a different place and everything else a month old or older. Reading
        # the oldest (or only one source) would offer all three.
        old = ago(timedelta(days=40))
        recent = ago(timedelta(days=2))
        story("NEWEST-STAGE", {"stages": {"S1": {"status": "done", "finished": old},
                                          "S2": {"status": "running", "started": recent}},
                               "gates": {"A": {"decision": "approve", "at": old}},
                               "halts": [{"at": old, "resolved": True}]})
        story("NEWEST-GATE", {"stages": {"S1": {"status": "done", "finished": old}},
                              "gates": {"A": {"decision": "approve", "at": recent}},
                              "halts": [{"at": old, "resolved": True}]})
        story("NEWEST-HALT", {"stages": {"S1": {"status": "done", "finished": old}},
                              "gates": {"A": {"decision": "approve", "at": old}},
                              "halts": [{"at": recent, "resolved": False}]})
        rows = {r["ticket"]: r for r in AT.stories(AT.DEFAULT_DAYS)}
        check_eq("the day boundary reads the newest stamp among stages, gates and halts",
                 {t: rows[t]["candidate"] for t in ("NEWEST-STAGE", "NEWEST-GATE", "NEWEST-HALT")},
                 {"NEWEST-STAGE": False, "NEWEST-GATE": False, "NEWEST-HALT": False})
    finally:
        cleanup(root)

    held_for_code()
    finish("test_archive_task")


def held_for_code() -> None:
    """t-2181 PC-6 (§2.4): a story held for code names what it waits for instead of "parked"; a stopped story has no parked item."""
    parked = "the story never reached S9 done"
    base = pipeline(False)
    base["stages"]["S6"] = {"status": "pending"}      # reached S5, never S9: the old reading says "parked"
    base["stages"]["S9"] = {"status": "pending"}
    plain = AT.open_items(base)
    check("without a hold the story reads `parked`", any(parked in item for item in plain), str(plain))
    record = {"since": "2026-11-01T10:00:00+00:00", "sides": {"backend": {"reality": "absent"}, "ui": {"reality": "real"}}}
    items = AT.open_items(dict(base, awaiting=record))
    check_eq("an awaiting item: `awaiting code since <date> (<sides>)`, and no `parked` line",
             [item for item in items if "awaiting" in item or "parked" in item], ["awaiting code since 2026-11-01 (backend)"])
    items = AT.open_items(dict(base, awaiting=dict(record, cause="first_look_stop", held_from="S3")))
    check_in("the first-look cause is named", "held after the first look since 2026-11-01 (backend)", items)
    stopped = AT.open_items(dict(base, awaiting=dict(record, stopped={"at": "2026-11-02T09:00:00+00:00", "words": "stop"})))
    check_eq("stopped_story_has_no_parked_item: the person ended the wait, nothing is open", stopped,
             [item for item in plain if parked not in item])
    check_not_in("... and no awaiting item either", "awaiting", " ".join(stopped))
    check_eq("hold_line of a stopped story", AT.hold_line(dict(base, awaiting=dict(record, stopped={"at": "2026-11-02T09:00:00+00:00"}))),
             "stopped waiting 2026-11-02")
    check_eq("hold_line of a story that waits for nothing is empty", AT.hold_line(base), "")
    check_eq("an unreadable record (a list) holds nothing", AT.hold_line(dict(base, awaiting=["x"])), "")
    check_eq("another halt is still listed beside the hold",
             [item for item in AT.open_items(dict(base, awaiting=record, halts=[{"reason": "why", "resolved": False}])) if "halt" in item],
             ["unresolved halt: why"])


if __name__ == "__main__":
    main()
