#!/usr/bin/env python3
"""Publication lifecycle seams: seven scenarios, complete search, retry and human edits."""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_store import content_hash  # noqa: E402
import tms_publication as T  # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if not ok else ""))
    FAILS += not ok


def action(identifier, mode, choice, refs=None):
    return {"scenario_id": identifier, "execution_mode": mode, "case_action": choice,
            "existing_case_refs": refs or [], "rationale": "content compared; title alone was not used",
            "search_scope": "payments suite", "search_snapshot_revision": "snapshot-7",
            "search_completeness": "complete", "proposed_case_version": "case-v2",
            "automation_action": "reuse" if mode == "automated" else "not_applicable"}


def main() -> int:
    actions = [action("a1", "automated", "reuse", [{"id": "TMS-1", "revision": "r1"}]),
               action("a2", "automated", "create"), action("a3", "automated", "create"),
               # This manual scenario deliberately has an existing ID despite a different title.
               action("m1-different-title", "agent-manual", "reuse", [{"id": "TMS-2", "revision": "r4"}]),
               action("m2", "agent-manual", "update", [{"id": "TMS-3", "revision": "r2"}]),
               action("m3", "agent-manual", "create"), action("m4", "agent-manual", "create")]
    decision = {"action": "publish_cases", "status": "approved", "content_hash": content_hash(actions),
                "destination": "payments/smoke", "authorization_source": "gate-A revision 9"}
    data = {"actions": actions, "decision": decision, "remote_versions": {"TMS-1": "r1", "TMS-2": "r4", "TMS-3": "r2"},
            "search_scope": "payments suite", "search_pages": [{"items": [1], "next_cursor": "p2"}, {"cursor": "p2", "items": [2], "complete": True}]}
    manifest = T.prepare(data)
    check("all seven scenarios remain in authorized manifest", len(manifest["requests"]) == 7)
    check("only explicit creates are new TMS cases", sum(r["action"] == "create" for r in manifest["requests"]) == 4)
    check("manual existing case retains its remote ID", any(r["scenario_id"] == "m1-different-title" and r["existing_case_refs"][0]["id"] == "TMS-2" for r in manifest["requests"]))
    check("transport stays explicit without an adapter", T.transport_payload(manifest)["status"] == "transport_required")
    check("reuse mappings never reach a write transport", len(T.transport_payload(manifest)["requests"]) == 5 and all(r["action"] != "reuse" for r in T.transport_payload(manifest)["requests"]))
    broken = copy.deepcopy(data)
    broken["search_pages"][1]["cursor"] = "wrong-page"
    try:
        T.prepare(broken)
        rejected = False
    except ValueError:
        rejected = True
    check("disconnected pagination blocks create", rejected)
    bad = copy.deepcopy(data)
    bad["search_pages"] = [{"items": [], "next_cursor": "still-more"}]
    try:
        T.prepare(bad)
        incomplete = False
    except ValueError:
        incomplete = True
    check("incomplete pagination cannot create", incomplete)
    changed = copy.deepcopy(data)
    changed["remote_versions"]["TMS-3"] = "human-edit-r3"
    try:
        T.prepare(changed)
        conflict = False
    except ValueError:
        conflict = True
    check("human remote edit becomes conflict", conflict)
    with tempfile.TemporaryDirectory(prefix="qa-tms-") as td:
        receipt_path = Path(td) / "receipts.json"
        first = manifest["requests"][0]
        receipt = {"idempotency_key": first["idempotency_key"], "remote_id": "TMS-1", "remote_revision": "r1"}
        T.record_receipts(receipt_path, [receipt])
        retry = T.prepare(data, __import__("json").loads(receipt_path.read_text(encoding="utf-8")))
        retried = next(row for row in retry["requests"] if row["idempotency_key"] == first["idempotency_key"])
        check("retry reuses recorded mapping instead of creating", retried["status"] == "recorded")
    print(f"=== test_tms_publication: {9 - FAILS}/9 ok ===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
