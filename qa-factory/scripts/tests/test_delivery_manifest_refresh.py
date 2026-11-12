"""The delivery manifest is built last, and the records the factory rewrites are named.

TP2-2553: S8 step 2 hashed `state/events.jsonl`, `work/ledger.json`, `work/ledger.md`
and `work/automation-manifest.json`, and then acceptance, the waiver and the ledger rewrote
them — by design. Gate B printed four `delivery manifest: stale hash` reasons, owner
`factory`, about a record nobody had tampered with, at `finalization-receipt: complete`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

import check_delivery as D  # noqa: E402
import contract as C  # noqa: E402
import delivery_manifest as M  # noqa: E402
import finalize_task as F  # noqa: E402


def story(events: bool = True) -> Path:
    """A minimal delivered story: the human documents, the compact ledgers, the event stream.

    `events=False` leaves the journal out, because a hand-written one is not a journal the
    `EventStore` can read and the reducer refuses to run over a corrupt one — correctly."""
    task = temp_dir("qa-delivery-refresh-") / "TP2-2553"
    (task / "work").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (task / "test-report.md").write_text("report\n", encoding="utf-8")
    (task / "work" / "ledger.json").write_text('{"delivery_ready": false}\n', encoding="utf-8")
    (task / "work" / "ledger.md").write_text("| ref |\n", encoding="utf-8")
    (task / "work" / "automation-manifest.json").write_text('{"tests": []}\n', encoding="utf-8")
    if events:
        (task / "state" / "events.jsonl").write_text('{"type": "seed"}\n', encoding="utf-8")
    return task


def prepared(task: Path) -> dict:
    doc = M.build(task)
    (task / "state" / "delivery-manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def volatile_is_named_and_not_hashed() -> None:
    task = story()
    try:
        doc = prepared(task)
        rows = {row["path"]: row for row in doc["files"]}
        for path in ("state/events.jsonl", "work/ledger.json", "work/ledger.md",
                     "work/automation-manifest.json"):
            check(f"{path} is marked volatile", rows.get(path, {}).get("volatile") is True)
        check("the hash is still recorded for it", bool(rows["work/ledger.json"].get("sha256")))
        check("a stable human document is not marked",
              "volatile" not in rows["test-report.md"])
        check_eq("a freshly built manifest has nothing to say",
                 D.delivery_manifest_reasons(task), [])

        # Exactly what happens after S8 step 2 on every story.
        with (task / "state" / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"type": "gate_decision"}\n')
        (task / "work" / "ledger.json").write_text('{"delivery_ready": true}\n', encoding="utf-8")
        check_eq("the writes the factory itself makes afterwards are not findings",
                 D.delivery_manifest_reasons(task), [])

        # And a record nobody rewrites by design still answers for its bytes.
        (task / "test-report.md").write_text("edited by hand\n", encoding="utf-8")
        check_in("a changed stable record is still a stale hash", "stale hash for test-report.md",
                 D.delivery_manifest_reasons(task))
    finally:
        cleanup(task.parent)


def a_manifest_written_before_0_7_18() -> None:
    """A story in flight carries a manifest whose rows have no `volatile` key at all; the
    canonical path list answers for it, so nothing is re-onboarded to stop being accused."""
    task = story()
    try:
        doc = prepared(task)
        doc["files"] = [{k: v for k, v in row.items() if k != "volatile"} for row in doc["files"]]
        for row in doc["files"]:
            if row["path"] == "work/ledger.json":
                row["sha256"] = "0" * 64
        (task / "state" / "delivery-manifest.json").write_text(json.dumps(doc), encoding="utf-8")
        check_eq("an old manifest's volatile row is read from the path list",
                 D.delivery_manifest_reasons(task), [])
    finally:
        cleanup(task.parent)


def the_reducer_rebuilds_it_last() -> None:
    task = story(events=False)
    try:
        prepared(task)
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "run-blocks" / "one.json").write_text(json.dumps(
            {"block_id": "b1", "attempt_started_at": "2026-09-22T10:00:00Z",
             "results": [{"case": "TC-001", "instance_id": "TC-001", "status": "passed"}]}),
            encoding="utf-8")
        summary = F.refresh(task)
        check("the reducer reports what it rebuilt", bool(summary.get("delivery_manifest")))
        doc = json.loads((task / "state" / "delivery-manifest.json").read_text(encoding="utf-8"))
        paths = {row["path"] for row in doc["files"]}
        check("the records this reduce wrote are in the manifest it rebuilt",
              {"work/run-report.json", "work/triage.json"} <= paths)
        check_eq("and the manifest is current", D.delivery_manifest_reasons(task), [])
        check("the run-report the reducer just wrote is volatile",
              next(r for r in doc["files"] if r["path"] == "work/run-report.json").get("volatile"))
    finally:
        cleanup(task.parent)

    # A story that never prepared a manifest is not given one here.
    task = story(events=False)
    try:
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "run-blocks" / "one.json").write_text(json.dumps(
            {"block_id": "b1", "results": []}), encoding="utf-8")
        F.refresh(task)
        check("no manifest is invented for a story that has none",
              not (task / "state" / "delivery-manifest.json").exists())
        check_eq("and refresh says so", M.refresh(task), None)
    finally:
        cleanup(task.parent)


def a_broken_rebuild_never_stops_the_reducer() -> None:
    """Same shape as `_stamp_cases`: the manifest is a projection, and a projection that
    cannot be built is its own finding, not a reason `run-report.json` stops being written."""
    task = story(events=False)
    try:
        prepared(task)
        # An evidence index that is not the current approved projection makes `build` raise.
        (task / "evidence").mkdir()
        (task / "evidence" / "index.json").write_text('{"rows": [{"nonsense": true}]}',
                                                      encoding="utf-8")
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "run-blocks" / "one.json").write_text(json.dumps(
            {"block_id": "b1", "results": []}), encoding="utf-8")
        summary = F.refresh(task)
        check("the run report is written anyway", (task / "work" / "run-report.json").is_file())
        check("and the failure is reported, not raised", bool(summary.get("delivery_manifest_error")))
    finally:
        cleanup(task.parent)


def the_words_are_the_contract_s() -> None:
    check("the reducer's outputs are all named volatile",
          {"work/run-report.json", "work/triage.json", "work/finalization-receipt.json"}
          <= set(C.DELIVERY_VOLATILE_PATHS))


def the_reducer_keeps_the_analysts_rows_it_can_bind() -> None:
    """t-309 over the REAL reducer (`reduce` is not replaced here): a red instance whose id carries no
    `[param]` binds the analyst's row that does, and a row of a failure that is gone is archived."""
    task = story(events=False)
    try:
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "run-blocks" / "one.json").write_text(json.dumps(
            {"block_id": "b1", "attempt_started_at": "2026-09-22T10:00:00Z",
             "results": [{"case": "TC-001", "instance_id": "test_ui", "status": "failed"},
                         {"case": "TC-002", "instance_id": "test_api", "status": "passed"}]}), encoding="utf-8")
        (task / "work" / "triage.json").write_text(json.dumps({"triage": [
            {"instance_id": "test_ui[chromium]", "verdict": "ENV_ISSUE"},
            {"instance_id": "test_api", "verdict": "APP_BUG"},
            {"instance_id": "", "case": "", "verdict": "ENV_ISSUE"}]}), encoding="utf-8")
        F.refresh(task)
        written = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        check_eq("the analyst's `[chromium]` row binds the red instance that has no suffix; the row of the green one "
                 "and the nameless row do not", [row["instance_id"] for row in written["triage"]], ["test_ui[chromium]"])
        check("a run with a failure carries no 'no product failures' reason", "reason" not in written)
        archived = [row["instance_id"] for p in (task / "state" / "migration").glob("stale-triage-*.json")
                    for row in json.loads(p.read_text(encoding="utf-8"))["rows"]]
        check_eq("the two unbound rows are archived, not lost", sorted(archived), ["", "test_api"])
    finally:
        cleanup(task.parent)
    # a run with no failure says so, and its triage is empty (the null outcome's recorded state, FR-23)
    task = story(events=False)
    try:
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "run-blocks" / "one.json").write_text(json.dumps(
            {"block_id": "b1", "attempt_started_at": "2026-09-22T10:00:00Z",
             "results": [{"case": "TC-002", "instance_id": "test_api", "status": "passed"}]}), encoding="utf-8")
        F.refresh(task)
        written = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        check_eq("no failure: empty triage with its reason", (written["triage"], written.get("reason")),
                 ([], "no product failures in reduced run blocks"))
    finally:
        cleanup(task.parent)


def main() -> None:
    the_reducer_keeps_the_analysts_rows_it_can_bind()
    volatile_is_named_and_not_hashed()
    a_manifest_written_before_0_7_18()
    the_reducer_rebuilds_it_last()
    a_broken_rebuild_never_stops_the_reducer()
    the_words_are_the_contract_s()
    finish("test_delivery_manifest_refresh")


if __name__ == "__main__":
    main()
