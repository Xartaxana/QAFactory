"""Before/after evidence belongs to a current case, never implicit regression."""
from pathlib import Path
import hashlib
import json
import os


def validate_baseline_request(request):
    phase = request.get("evidence_phase", "verification")
    errors = []
    if phase not in {"baseline", "verification"}:
        return ["evidence_phase must be baseline or verification"]
    if phase == "baseline":
        contract = request.get("baseline_contract") or {}
        for key in ("case_id", "case_version", "baseline_revision", "verification_revision",
                    "fixture_identity", "gate_a_decision_ref", "reason"):
            if not isinstance(contract.get(key), str) or not contract[key]:
                errors.append("baseline_contract requires " + key)
        if contract.get("execution_scope") != "current_task":
            errors.append("baseline must belong to approved current_task scope")
        expected = (request.get("runtime_provenance") or {}).get("expected_source_revision")
        if expected != contract.get("baseline_revision"):
            errors.append("baseline runtime must match the approved before revision")
        if not contract.get("capture_steps") or not contract.get("comparison_assertions"):
            errors.append("baseline requires capture_steps and comparison_assertions")
        refs = contract.get("capture_artifact_refs")
        if (not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref
                or Path(ref).is_absolute() or ".." in Path(ref).parts for ref in refs)):
            errors.append("baseline requires task-relative capture_artifact_refs")
    return errors


def build_baseline_fields(approved_row, gate_a_decision_ref, runtime_provenance):
    """Derive the baseline-only portion of a typed request from Gate-A-approved data.

    The caller still supplies command, selection, fingerprints, and idempotency through the
    normal RunRequest builder. This helper cannot create a deployment or a product verdict.
    """
    row = approved_row if isinstance(approved_row, dict) else {}
    contract = {"case_id": row.get("case_id") or row.get("id"), "case_version": row.get("case_version"),
                "baseline_revision": row.get("baseline_revision"),
                "verification_revision": row.get("verification_revision"),
                "fixture_identity": row.get("fixture_identity"),
                "gate_a_decision_ref": gate_a_decision_ref, "reason": row.get("baseline_reason"),
                "execution_scope": row.get("execution_scope"), "capture_steps": row.get("capture_steps"),
                "comparison_assertions": row.get("comparison_assertions"),
                "capture_artifact_refs": row.get("capture_artifact_refs")}
    result = {"evidence_phase": "baseline", "baseline_contract": contract,
              "runtime_provenance": runtime_provenance}
    errors = validate_baseline_request(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def validate_managed_gate(request, project_root):
    """Reject a forged Gate-A identifier when this task has controller state.

    Pre-onboarding/legacy projects have no managed state and retain request compatibility.
    """
    if request.get("evidence_phase") != "baseline":
        return []
    try:
        from hooklib import artifact_root
        task = str(request.get("task") or "")
        state_path = artifact_root(root=Path(project_root)) / task / "state" / "controller.json"
        if not state_path.is_file():
            return []
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        if (state_path.parent / "events.jsonl").is_file():
            from controller import Controller
            controller = Controller(state_path.parent.parent)
            state = controller.state()
            controller._validate_gate_a_content_current(state)
            document = controller._plan_document()
            rows = document.get("rows", []) if isinstance(document, dict) else document
            case_id = request.get("baseline_contract", {}).get("case_id")
            matches = [row for row in rows if (row.get("case_id") or row.get("id")) == case_id
                       and row.get("baseline_required")]
            if len(matches) != 1:
                return ["baseline case has no unique approved baseline contract"]
            expected = build_baseline_fields(matches[0], controller._current_gate_a(state)["id"],
                                             request.get("runtime_provenance") or {})
            if expected["baseline_contract"] != request.get("baseline_contract"):
                return ["baseline fields differ from the current approved plan"]
        wanted = request.get("baseline_contract", {}).get("gate_a_decision_ref")
        decisions = state.get("decisions", {})
        matched = next((decision for decision in decisions.values() if isinstance(decision, dict)
                        and decision.get("id") == wanted and decision.get("gate") == "A"
                        and decision.get("status") == "approved"), None)
        if not matched:
            return ["baseline Gate A reference is not the task's current approved decision"]
        case = request.get("baseline_contract", {}).get("case_id")
        if matched.get("scope") and case not in matched["scope"]:
            return ["baseline case is outside the approved Gate A scope"]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ["managed baseline Gate A state is unreadable"]
    return []


def _hash_ref(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("baseline evidence must be an existing task-relative file")
    return {"path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def baseline_receipt(task_root, request, summary, summary_path):
    """Build a non-verdict receipt from one pre-deployment runner attempt."""
    root = Path(task_root).resolve()
    if request.get("evidence_phase") != "baseline":
        raise ValueError("only baseline requests can produce a baseline receipt")
    errors = validate_baseline_request(request)
    if errors:
        raise ValueError("; ".join(errors))
    contract = request["baseline_contract"]
    summary_ref = _hash_ref(root, summary_path)
    captured_refs, capture_error = [], ""
    for raw in contract["capture_artifact_refs"]:
        try:
            ref = _hash_ref(root, root / raw)
            if ref["path"] == summary_ref["path"]:
                raise ValueError("summary is not a before-state capture artifact")
            if (root / raw).stat().st_size == 0:
                raise ValueError("before-state capture artifact is empty")
            captured_refs.append(ref)
        except (OSError, ValueError) as exc:
            capture_error = str(exc)
            break
    # Command success only says the capture command completed; it does not prove the new
    # requirement. A receipt is captured only when it also has actual old-state bytes.
    captured = summary.get("execution_status") == "passed" and bool(captured_refs) and not capture_error
    return {"schema_version": 1, "evidence_phase": "baseline", "status": "captured" if captured else "inconclusive",
            "case_id": contract["case_id"], "case_version": contract["case_version"],
            "baseline_revision": contract["baseline_revision"],
            "verification_revision": contract["verification_revision"],
            "fixture_identity": contract["fixture_identity"],
            "gate_a_decision_ref": contract["gate_a_decision_ref"], "reason": contract["reason"],
            "capture_steps": contract["capture_steps"], "comparison_assertions": contract["comparison_assertions"],
            "source_revision": request.get("runtime_provenance", {}).get("expected_source_revision"),
            "runtime_identity": request.get("runtime_provenance", {}).get("observed_runtime_identity"),
            "request_digest": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
            "attempt_id": request.get("idempotency_key"), "captured_at": summary.get("ended_at"),
            "execution_status": summary.get("execution_status"), "summary_ref": summary_ref,
            "evidence_refs": captured_refs,
            "gap": "" if captured else capture_error or "baseline capture did not complete successfully"}


def write_baseline_receipt(task_root, request, summary, summary_path):
    """Persist an idempotent, immutable baseline receipt outside product run blocks."""
    root = Path(task_root).resolve()
    if not root.is_dir():                  # a receipt goes UNDER a story folder; S0 makes the folder, never this step
        from hooklib import StoryRootError
        raise StoryRootError(f"the baseline receipt is written under the story folder {root}, which does not exist, so "
                             "nothing was written (S0 creates a story folder; this step never does). Pass the folder "
                             "of a story that exists")
    receipt = baseline_receipt(root, request, summary, summary_path)
    directory = root / "work" / "baseline-receipts"
    (root / "work").mkdir(exist_ok=True)
    directory.mkdir(exist_ok=True)
    name = hashlib.sha256(receipt["request_digest"].encode()).hexdigest() + ".json"
    path = directory / name
    text = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("baseline receipt identity conflict")
        return path
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def deployment_readiness(rows, receipts, task_root, expected_gate_ref=None):
    """Report baseline evidence gaps without blocking current-version execution.

    ``ready`` is retained for callers of the old baseline gate, but is always true:
    this function grants neither deployment authorization nor runtime readiness.
    ``comparisons_ready`` only means before evidence is available, not that the
    before/after assertions have passed.
    """
    root = Path(task_root).resolve()
    gaps = []
    for row in rows:
        if not row.get("baseline_required") or row.get("execution_scope", "current_task") != "current_task":
            continue
        case = row.get("case_id") or row.get("id")
        candidates = [r for r in receipts if r.get("evidence_phase") == "baseline"
                      and r.get("case_id") == case and r.get("case_version") == row.get("case_version")
                      and r.get("baseline_revision") == row.get("baseline_revision")
                      and r.get("verification_revision") == row.get("verification_revision")
                      and r.get("fixture_identity") == row.get("fixture_identity")
                      and r.get("gate_a_decision_ref")
                      and (not expected_gate_ref or r.get("gate_a_decision_ref") == expected_gate_ref)
                      and (not row.get("gate_a_decision_ref") or
                           r.get("gate_a_decision_ref") == row.get("gate_a_decision_ref"))
                      and r.get("comparison_assertions") == row.get("comparison_assertions")
                      and r.get("status") == "captured"]
        valid = False
        for receipt in candidates:
            refs = receipt.get("evidence_refs") or []
            if not refs:
                continue
            try:
                valid = receipt.get("source_revision") == row.get("baseline_revision") and all(
                            isinstance(ref, dict) and isinstance(ref.get("path"), str)
                            and (root / ref["path"]).resolve().is_relative_to(root)
                            and hashlib.sha256((root / ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
                            for ref in refs)
            except (OSError, KeyError, TypeError):
                valid = False
            if valid:
                break
        if not valid:
            gaps.append({"case_id": case, "case_version": row.get("case_version"),
                         "status": "awaiting_baseline", "blocks_execution": False,
                         "reason": "baseline evidence missing, stale or incomparable"})
    return {"ready": True, "comparisons_ready": not gaps, "gaps": gaps,
            "deployment_authorized": False,
            "next_action": "execute_current_checks_then_offer_baseline_sources" if gaps else "execute_current_checks"}
