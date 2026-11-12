#!/usr/bin/env python3
"""Scoped TMS publication lifecycle, deliberately adapter-neutral.

This prepares and records publication receipts; it does not send any remote request. A
configured connector or an operator consumes the emitted transport payload and returns a
receipt, so a timeout is ``unknown`` until that receipt/mapping is reconciled.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
from event_store import atomic_json  # noqa: E402
from planning_contract import publication_manifest, validate_case_actions  # noqa: E402
import hooklib  # noqa: E402
from hooklib import sorted_paths  # noqa: E402


def pagination_complete(pages) -> tuple[bool, str]:
    """A scoped search is complete only when its final page explicitly closes pagination."""
    if not isinstance(pages, list) or not pages:
        return False, "no paginated search evidence"
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            return False, f"page {index + 1} is not an object"
        if page.get("error") or page.get("available") is False:
            return False, f"page {index + 1} unavailable"
        if index and page.get("cursor") != pages[index - 1].get("next_cursor"):
            return False, f"page {index + 1} does not continue the previous cursor"
        if index and any(old.get("cursor") == page.get("cursor") for old in pages[:index]):
            return False, f"page {index + 1} repeats a cursor"
        if index < len(pages) - 1 and not page.get("next_cursor"):
            return False, f"page {index + 1} ends before supplied later page"
    last = pages[-1]
    if last.get("next_cursor"):
        return False, "pagination has a next cursor"
    if last.get("complete") is not True:
        return False, "final page lacks complete=true"
    return True, "complete"


def prepare(data: dict, receipts: dict | None = None) -> dict:
    actions = data.get("actions") or []
    errors = validate_case_actions(actions)
    complete, pagination_note = pagination_complete(data.get("search_pages"))
    for action in actions:
        if action.get("case_action") == "create" and not complete:
            errors.append(f"{action.get('scenario_id')}: remote create blocked — {pagination_note}")
    if errors:
        raise ValueError("; ".join(errors))
    manifest = publication_manifest(actions, data.get("decision") or {}, data.get("remote_versions") or {})
    prior = (receipts or {}).get("receipts") or {}
    requests = []
    for request in manifest["requests"]:
        old = prior.get(request["idempotency_key"])
        request = dict(request)
        if old:
            request["status"] = "reconciliation_required" if old.get("status") == "unknown" else "recorded"
            request["receipt"] = old
        elif request["action"] == "reuse":
            request["status"] = "mapped_existing"
            request["mapping"] = request["existing_case_refs"]
        else:
            request["status"] = "ready_for_transport"
        requests.append(request)
    return {**manifest, "schema_version": 1, "search": {"complete": complete, "note": pagination_note,
                                                              "scope": data.get("search_scope")},
            "requests": requests}


def transport_payload(manifest: dict, adapter_command=None) -> dict:
    """Return an explicit handoff; never pretend an unavailable adapter completed a write."""
    ready = [request for request in manifest.get("requests") or [] if request.get("status") == "ready_for_transport"]
    return {"status": "transport_required" if ready else "nothing_to_send",
            "destination": manifest.get("destination"), "channel": manifest.get("channel"), "adapter_command": adapter_command or None,
            "requests": ready,
            "instruction": "Execute only with a configured adapter, then record a confirmed remote receipt."}


def record_receipts(path: Path, receipts: list) -> dict:
    current = C.load_json(path)
    stored = dict(current.get("receipts") or {})
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ValueError("receipt must be an object")
        key = str(receipt.get("idempotency_key") or "")
        remote_id = str(receipt.get("remote_id") or "")
        if not key or not remote_id or not receipt.get("remote_revision"):
            raise ValueError("receipt requires idempotency_key, remote_id, and remote_revision")
        existing = stored.get(key)
        if existing and existing != receipt:
            raise ValueError(f"conflicting receipt for {key}; remote outcome is unknown until reconciled")
        stored[key] = receipt
    result = {"schema_version": 1, "receipts": stored}
    atomic_json(path, result)
    return result


def prior_transport_receipts(task_root):
    """The executor proposal is also a durable transport receipt, including uncertainty."""
    root = Path(task_root)
    current = C.load_json(C.artifact_write_path(root, "tms-publication-receipts.json"))
    receipts = dict(current.get("receipts") or {})
    for path in sorted_paths(C.artifact(root, "proposals").glob("case-*.json")):
        proposal = C.load_json(path)
        key = proposal.get("publication_key")
        if not key:
            continue
        result = proposal.get("result") or {}
        if result.get("external_id") and result.get("remote_revision"):
            receipts[key] = {"idempotency_key": key, "remote_id": result["external_id"],
                             "remote_revision": result["remote_revision"]}
        elif result or proposal.get("pending"):
            receipts.setdefault(key, {"status": "unknown", "proposal": str(path),
                                      "remote_id": result.get("external_id")})
    return {"receipts": receipts}


def main() -> int:
    C.force_utf8()
    parser = argparse.ArgumentParser(description="prepare/record scoped TMS publication; never sends remote writes")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("input", type=Path)
    prep.add_argument("--task-root")      # raw strings: `type=Path` read "" as the current folder
    trans = sub.add_parser("transport")
    trans.add_argument("manifest", type=Path)
    trans.add_argument("--adapter-command")
    record = sub.add_parser("record")
    record.add_argument("receipts", type=Path, help="confirmed receipt JSON array")
    record.add_argument("--task-root", required=True)
    args = hooklib.exact_options(parser).parse_args()       # walks the three subparsers
    if getattr(args, "task_root", None) is not None:        # a GIVEN root names an existing story before anything is read
        args.task_root = hooklib.story_cli("tms_publication.py", root=args.task_root, key_flag=None)
    if args.command == "prepare":
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = prepare(data, prior_transport_receipts(args.task_root) if args.task_root else {})
        if args.task_root:
            atomic_json(C.artifact_write_path(args.task_root, "tms-publication-manifest.json"), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "transport":
        print(json.dumps(transport_payload(C.load_json(args.manifest), args.adapter_command), ensure_ascii=False, indent=2))
    else:
        rows = json.loads(args.receipts.read_text(encoding="utf-8"))
        result = record_receipts(C.artifact_write_path(args.task_root, "tms-publication-receipts.json"), rows)
        print(json.dumps({"recorded": len(result["receipts"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"tms_publication: {exc}", file=sys.stderr)
        sys.exit(2)
