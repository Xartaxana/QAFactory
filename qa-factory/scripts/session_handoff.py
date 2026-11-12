"""Durable, host-neutral orchestrator handoff contracts.

This module deliberately does not create a model session.  Hosts which support a fresh
context call their documented adapter and return its acknowledgement; unsupported hosts
receive a truthful manual-continuation packet instead of a pretend child session.
"""
import json
from pathlib import Path
from event_store import content_hash
from hooklib import sorted_paths

WINDOW_REQUEST_LIMIT = 40
WINDOW_CONTEXT_PERCENT = 70


def rollover_status(window_counters, context_percent=None):
    """Return a non-blocking rollover request; story counters are never reset here."""
    window_counters = window_counters or {}
    requests = window_counters.get("model_requests")
    reasons = []
    if isinstance(requests, (int, float)) and requests >= WINDOW_REQUEST_LIMIT:
        reasons.append("model_requests")
    if isinstance(context_percent, (int, float)) and context_percent >= WINDOW_CONTEXT_PERCENT:
        reasons.append("context_percent")
    return {"rollover_pending": bool(reasons), "reasons": reasons,
            "telemetry_unknown": ["context_percent"] if context_percent is None else [],
            "window_model_requests": requests}


def can_takeover(state, task_root=None):
    """A normal handoff only happens after all factory work is settled and accepted."""
    running = [d["id"] for d in state.get("dispatches", {}).values() if d.get("status") == "running"]
    jobs = list(state.get("running_jobs") or [])
    unknown_writes = list(state.get("unknown_external_writes") or [])
    if task_root:
        root = Path(task_root) / "state"
        for path in sorted_paths((root / "environment-jobs").glob("*.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8-sig"))
                from environment_preparation import environment_job_status
                if not isinstance(item, dict) or not item.get("idempotency_key"):
                    raise ValueError("missing environment job identity")
                status = environment_job_status(path.parent, item["idempotency_key"])
                if status.get("status") == "absent":
                    raise ValueError("environment job path does not match its identity")
            except (OSError, ValueError, TypeError):
                status = {"status": "unknown", "settled": False}
            if not status.get("settled"):
                jobs.append({"path": "environment-jobs/" + path.name, **status})
        for directory, sink in ((root / "execution-jobs", jobs), (root / "external-writes", unknown_writes)):
            for path in sorted_paths(directory.glob("*.json")) if directory.is_dir() else []:
                try:
                    item = json.loads(path.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    sink.append({"path": path.name, "status": "unknown"}); continue
                if item.get("status") in {"running", "pending", "unknown", "writing"}:
                    sink.append({"path": path.name, "status": item.get("status")})
        proposals = Path(task_root) / "work" / "proposals"
        for path in sorted_paths(proposals.glob("*.json")) if proposals.is_dir() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                unknown_writes.append({"path": str(path.relative_to(Path(task_root))), "status": "unknown"}); continue
            result = item.get("result")
            # A proposal is a draft until delivery writes `pending`; completed delivery is
            # identified by its durable external id and URL, not by an invented status field.
            if isinstance(result, dict) and result.get("external_id") and result.get("url"):
                continue
            pending = item.get("pending")
            if isinstance(pending, dict) and pending:
                unknown_writes.append({"path": str(path.relative_to(Path(task_root))), "status": "pending"})
            elif result:
                unknown_writes.append({"path": str(path.relative_to(Path(task_root))), "status": "partial_result"})
    return {"ready": not (running or jobs or unknown_writes), "running_dispatches": running,
            "running_jobs": jobs, "unknown_external_writes": unknown_writes}


def continuation_packet(state, *, reason=None, page=0, page_size=50):
    """Small index packet; artifact bytes and transcript remain durable files, not copied text."""
    next_action = state.get("next_action") or {}
    decisions = list(state.get("decisions", {}).values())
    remaining = [{"id": d.get("id"), "checkpoint": d.get("checkpoint"), "reason": d.get("reason")}
                 for d in state.get("dispatches", {}).values() if d.get("status") in {"blocked", "paused", "incomplete"}]
    start = max(0, int(page)) * max(1, int(page_size)); end = start + max(1, int(page_size))
    packet = {"schema_version": 1, "task_id": state.get("task_id"), "revision": state.get("revision"),
              "source_revision": state.get("source_revision"), "scope": state.get("scope", []),
              "next_action": next_action, "reason": reason,
              "decisions": [{"id": d.get("id"), "gate": d.get("gate"), "status": d.get("status"),
                             "source_revision": d.get("source_revision"), "scope": d.get("scope"),
                             "authorization_source": d.get("authorization_source"), "action": d.get("action"),
                             "selected_drafts": d.get("selected_drafts", []), "reason": d.get("reason"),
                             "input_revision": d.get("input_revision"), "decision_ref": "state/controller.json"}
                            for d in decisions[start:end]],
              "pages": {"decision_page": int(page), "page_size": int(page_size), "decision_count": len(decisions),
                        "remaining_count": len(remaining)},
              "blockers": [d.get("reason") for d in state.get("dispatches", {}).values()
                           if d.get("status") in {"blocked", "incomplete"}],
              "running_jobs": state.get("running_jobs", []),
              "remaining": remaining[start:end],
              "cumulative_counters": state.get("cumulative_counters", {}),
              "artifact_index": state.get("artifact_index", [])}
    packet["packet_hash"] = content_hash(packet)
    return packet


def _generation_increases(new_lease, lease):
    """Whether the new lease's generation is above the held one. A lease or a generation that
    cannot be compared is no increase: the chain below evaluates every check, so a value that
    would have crashed this one must be a refusal of its own, not an error that hides the
    problems found before it."""
    try:
        return new_lease.get("generation", 0) > lease.get("generation", 0)
    except (AttributeError, TypeError):
        return False


def validate_takeover(lease, request, state, task_root=None):
    """Refuse a takeover with EVERY problem the request has, or return True.

    The checks do not depend on one another (K1, cmp3): a stale revision, work still running,
    an unsupported capability, an unverified acknowledgement, a foreign owner and a lease that
    does not advance can all hold at once, and the old first-failure raise cost one round per
    problem. They are collected and refused whole, in this order, in the combined form
    `detector_verdict.compound` writes (one problem is its own sentence, unchanged). The one
    dependency: a request that is not an object cannot be read by the checks that read it, so
    those did not run - and the refusal says so (FR-59), it never reads as a pass. The class
    is `ValueError` throughout, as it always was."""
    problems = []
    shaped = isinstance(request, dict)
    if not shaped or request.get("_expected_revision", request.get("expected_revision")) != state.get("revision"):
        problems.append("takeover requires current expected_revision")
    if not can_takeover(state, task_root)["ready"]:
        problems.append("takeover blocked until running work/jobs/writes are reconciled")
    if not shaped:
        problems[-1] += (" (the capability, acknowledgement, owner and lease checks did not run: "
                         "they read the request as an object)")
    else:
        capability = request.get("host_capability")
        if not isinstance(capability, str) or capability not in {"fresh_orchestrator_context", "manual_continuation"}:
            problems.append("unsupported handoff capability")
        if capability == "fresh_orchestrator_context":
            ack = request.get("host_ack")
            ack = ack if isinstance(ack, dict) else {}
            if not request.get("new_session_id") or ack.get("session_id") != request.get("new_session_id") or ack.get("fresh_context") is not True:
                problems.append("fresh handoff requires verified host acknowledgement")
        if lease and request.get("owner_session_id") != lease.get("owner_session_id"):
            problems.append("takeover owner does not hold current lease")
        if lease and not _generation_increases(request.get("lease", {}), lease):
            problems.append("takeover lease generation must increase")
    if problems:
        from detector_verdict import compound
        raise ValueError(compound(problems))
    return True
