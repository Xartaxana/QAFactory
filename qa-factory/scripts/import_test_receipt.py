"""Import a cryptographically bound external dev/CI result without executing commands.

The importer validates a normal typed RunRequest against the current checkout and the selected
profile's configured external receipt adapter, then requires an external receipt whose binding
is exactly the execution-relevant part of that request.
It emits the same immutable run-block shape as run_suite.py, so existing reducers need no
special external-evidence path. Reporter artifacts are copied to content-addressed immutable
paths. A dashboard label such as "CI green" is never a receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import shutil

from execution_request import validate_request
from hooklib import project_root, story_cli
import stand_identity as SI
from run_suite import build_run_block, block_folder, PROOF_STAMP_KEYS


class ImportError(ValueError):
    pass


BOUND_FIELDS = ("task", "revision", "dispatch_id", "profile_id", "purpose",
                "selected_instance_ids", "current_scope_instance_ids", "input_fingerprint",
                "fingerprint_files", "fingerprint_components", "runtime_required",
                "target_kind", "runtime_provenance", "instance_contracts")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def receipt_digest(receipt: dict) -> str:
    material = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return hashlib.sha256(canonical(material)).hexdigest()


def _compact(digest_value: str, prefix: str) -> str:
    """Short filesystem key; full digests in provenance detect every prefix collision."""
    return prefix + digest_value[:20]


def _binding(request: dict) -> dict:
    return {key: request.get(key) for key in BOUND_FIELDS}


def _trusted_producer(root: Path, profile_id: str) -> dict:
    config_path = root / "qa-factory" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportError(f"configured external receipt adapter is unavailable: {exc}") from exc
    matches = [p for p in config.get("profiles", []) if isinstance(p, dict)
               and p.get("profile_id") == profile_id]
    if len(matches) != 1:
        raise ImportError("request profile must resolve to exactly one configured profile")
    profile = matches[0]
    policy = (profile.get("extensions") or {}).get("external_receipts")
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        raise ImportError("selected profile does not enable external receipt import")
    trusted = {"id": policy.get("producer_id"), "system": policy.get("system"),
               "adapter_id": profile.get("adapter_id"), "adapter_version": profile.get("adapter_version")}
    if any(not isinstance(value, str) or not value for value in trusted.values()):
        raise ImportError("configured external receipt producer identity is incomplete")
    return trusted


def _time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ImportError("receipt timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ImportError("receipt timestamps must include a timezone")
    return parsed


def validate_receipt(request: dict, receipt: dict, trusted: dict) -> tuple[dict, str]:
    if receipt.get("schema_version") != 1:
        raise ImportError("external receipt schema_version must be 1")
    producer = receipt.get("producer")
    if not isinstance(producer, dict) or producer.get("kind") not in {"developer", "ci"}:
        raise ImportError("receipt requires developer/CI producer provenance")
    if not all(isinstance(producer.get(k), str) and producer[k].strip()
               for k in ("id", "system", "run_id")):
        raise ImportError("producer provenance requires id, system and run_id")
    if any(producer.get(k) != trusted.get(k)
           for k in ("id", "system", "adapter_id", "adapter_version")):
        raise ImportError("receipt producer is not the selected profile's configured external adapter")
    actual_digest = receipt_digest(receipt)
    if receipt.get("receipt_sha256") != actual_digest:
        raise ImportError("receipt_sha256 does not match immutable receipt content")
    if receipt.get("binding") != _binding(request):
        raise ImportError("receipt binding does not exactly match request scope and fingerprints")
    if receipt.get("reporter") != request.get("command", {}).get("reporter"):
        raise ImportError("receipt reporter does not match request reporter contract")
    if receipt.get("execution_status") not in {"passed", "failed"}:
        raise ImportError("external execution must have a machine result, not a claimed CI status")
    rows = receipt.get("results")
    if not isinstance(rows, list):
        raise ImportError("receipt results must be a machine-readable array")
    expected = {request["instance_contracts"][i]["report_test_id"]
                for i in request["selected_instance_ids"]}
    ids = [row.get("test_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or set(ids) != expected or len(ids) != len(set(ids)):
        raise ImportError("receipt must map exactly one reporter row to every selected instance")
    allowed = {"passed", "failed", "error", "skipped", "not_run"}
    if any(row.get("status") not in allowed for row in rows):
        raise ImportError("receipt contains an unsupported per-test status")
    statuses = [row["status"] for row in rows]
    if receipt["execution_status"] == "passed" and any(status != "passed" for status in statuses):
        raise ImportError("passed execution requires every selected reporter row to pass")
    if receipt["execution_status"] == "failed" and not any(status in {"failed", "error"} for status in statuses):
        raise ImportError("failed execution without a selected failed/error row is not product evidence")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence or any(not isinstance(x, dict) or not x.get("path") or not x.get("sha256") for x in evidence):
        raise ImportError("receipt requires local durable evidence paths and content hashes")
    if _time(receipt.get("ended_at")) < _time(receipt.get("started_at")):
        raise ImportError("receipt requires ordered execution timestamps")
    summary = {"execution_status": receipt["execution_status"], "reporter": receipt["reporter"],
               "started_at": receipt.get("started_at"), "ended_at": receipt.get("ended_at"),
               "summary_path": evidence[0]["path"], "results": rows}
    return summary, actual_digest


def _write_exclusive(path: Path, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise ImportError(f"immutable import collision at {path}")


def _safe_local(root: Path, raw: str) -> Path:
    relative = Path(str(raw or ""))
    if not raw or relative.is_absolute():
        raise ImportError("reporter evidence path must be task-relative")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ImportError("reporter evidence path cannot contain symlinks")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ImportError("missing or unsafe reporter evidence")
    return path


def _copy_evidence(source: Path, target: Path, expected: str) -> None:
    if target.parent.exists() and target.parent.is_symlink():
        raise ImportError("import evidence directory cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise ImportError("missing, unsafe or modified reporter evidence")
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ImportError("immutable reporter evidence collision")
        return
    # Do not repeat the 64-byte content hash in the temporary basename. On Windows the
    # final content-addressed target can fit MAX_PATH while ".<hash>.<pid>.tmp" crosses it.
    # The exclusive create plus finally cleanup retains the atomic/no-overwrite contract.
    temp = target.parent / f".t{os.getpid():x}"
    try:
        with source.open("rb") as inp, temp.open("xb") as out:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        if (hashlib.sha256(source.read_bytes()).hexdigest() != expected or
                hashlib.sha256(temp.read_bytes()).hexdigest() != expected):
            raise ImportError("reporter evidence changed during import")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _reject_destination_symlinks(root: Path, destination: Path) -> None:
    root = root.resolve()
    try:
        relative = destination.relative_to(root)
    except ValueError as exc:
        raise ImportError("import destination escapes work directory") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ImportError("import destination cannot contain symlinks")


def validate_import_block(task: Path, block: dict) -> list[str]:
    """Reader check for imported blocks; reducers must not trust stale external artifacts."""
    provenance = block.get("import_provenance")
    if not isinstance(provenance, dict):
        return [] if not str(block.get("attempt_id") or "").startswith("external-") else ["missing import provenance"]
    root = Path(task).resolve()
    errors = []
    receipt_ref = provenance.get("receipt_ref")
    receipt = None
    try:
        receipt_path = _safe_local(root, receipt_ref)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt_digest(receipt) != provenance.get("receipt_sha256"):
            errors.append("import receipt digest mismatch")
    except (ImportError, OSError, json.JSONDecodeError):
        errors.append("import receipt missing, unsafe or corrupt")
    refs = provenance.get("evidence")
    if not isinstance(refs, list) or not refs:
        errors.append("import reporter evidence missing")
    else:
        for ref in refs:
            try:
                path = _safe_local(root, ref.get("path") if isinstance(ref, dict) else "")
                if hashlib.sha256(path.read_bytes()).hexdigest() != ref.get("sha256"):
                    errors.append("import reporter evidence hash mismatch")
            except (ImportError, OSError):
                errors.append("import reporter evidence missing or unsafe")
    if isinstance(receipt, dict) and isinstance(refs, list) and refs:
        original_hashes = [ref.get("sha256") for ref in receipt.get("evidence", [])
                           if isinstance(ref, dict)]
        durable_hashes = [ref.get("sha256") for ref in refs if isinstance(ref, dict)]
        if (len(original_hashes) != len(receipt.get("evidence", [])) or
                durable_hashes != original_hashes):
            errors.append("durable evidence does not exactly match receipt evidence")
        attempt_id = "external-" + str(provenance.get("receipt_sha256") or "")[:20]
        binding = receipt.get("binding")
        if not isinstance(binding, dict):
            errors.append("import receipt binding is missing")
        else:
            summary = {"execution_status": receipt.get("execution_status"),
                       "reporter": receipt.get("reporter"),
                       "started_at": receipt.get("started_at"), "ended_at": receipt.get("ended_at"),
                       "summary_path": refs[0].get("path") if isinstance(refs[0], dict) else "",
                       "results": receipt.get("results")}
            expected = build_run_block(binding, summary, attempt_id)
            # the proof stamp is a fact of the moment of import, written by code (PC-5a): it is not a function of the receipt, so
            # today's pipeline.json must not re-decide it (a side that became real after the import would void a valid green); the
            # `reference_run` mark is the same kind of fact (the record read at the moment of import, W1), so it is not compared either
            skip = {"import_provenance", "reference_run", *PROOF_STAMP_KEYS}
            actual = {key: value for key, value in block.items() if key not in skip}
            expected = None if expected is None else {key: value for key, value in expected.items() if key not in skip}
            if expected is None or actual != expected:
                errors.append("import block execution payload does not match its receipt")
    return sorted(set(errors))


def import_receipt(request: dict, receipt: dict, root: Path, output: Path) -> dict:
    checked = validate_request(request, root, allow_exhausted_reuse=True)
    trusted = _trusted_producer(root, checked["profile_id"])
    summary, digest = validate_receipt(checked, receipt, trusted)
    evidence_root = Path(output).resolve().parent
    durable_refs = []
    import_dir = Path(output).resolve() / "imports" / _compact(digest, "i-")
    _reject_destination_symlinks(Path(output).resolve(), import_dir)
    import_path = import_dir / "r.json"
    block_name = f"{_compact(digest, 'x-')}.json"
    # the block lives in the folder its own mark names (a sample never in run-blocks, W1); a reuse looks in both, the mark is not re-decided
    block_path = output / "run-blocks" / block_name
    for folder in ("run-blocks", SI.REFERENCE_RUNS_DIR):
        if (output / folder / block_name).exists():
            block_path = output / folder / block_name
    if import_path.exists() and block_path.exists():
        existing_receipt = json.loads(import_path.read_text(encoding="utf-8"))
        existing_block = json.loads(block_path.read_text(encoding="utf-8"))
        if existing_receipt != receipt:
            raise ImportError("immutable import receipt collision")
        errors = validate_import_block(evidence_root, existing_block)
        if errors:
            raise ImportError("; ".join(errors))
        return {"status": "reused", "receipt_sha256": digest,
                "run_block": str(block_path), "attempt_id": existing_block.get("attempt_id")}
    for ref in receipt["evidence"]:
        source = _safe_local(evidence_root, ref["path"])
        suffix = source.suffix.lower() if source.suffix.lower() in {".xml", ".trx", ".json", ".log", ".txt"} else ".bin"
        target = import_dir / "e" / f"{_compact(ref['sha256'], 'h-')}{suffix}"
        _copy_evidence(source, target, ref["sha256"])
        durable_refs.append({"path": target.relative_to(evidence_root).as_posix(), "sha256": ref["sha256"]})
    summary["summary_path"] = durable_refs[0]["path"]
    attempt_id = "external-" + digest[:20]
    block = build_run_block(checked, summary, attempt_id)
    if block is None:
        raise ImportError("receipt purpose cannot produce a product execution block")
    block["import_provenance"] = {"receipt_sha256": digest,
                                  "receipt_ref": import_path.relative_to(evidence_root).as_posix(),
                                  "producer": receipt["producer"], "evidence": durable_refs}
    block_path = output / block_folder(block) / block_name
    _write_exclusive(import_path, receipt)
    _write_exclusive(block_path, block)
    errors = validate_import_block(evidence_root, block)
    if errors:
        raise ImportError("; ".join(errors))
    return {"status": "imported", "receipt_sha256": digest,
            "run_block": str(block_path), "attempt_id": attempt_id}


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--project-root")
    args = parser.parse_args()
    root = Path(args.project_root).resolve() if args.project_root else project_root()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    # the story must exist (CX1-18): the call's fault, nothing was written; the refusal is story_cli's (one line, exit 2)
    output = story_cli("import_test_receipt: the request's", key=request.get("task", ""), key_flag="task") / "work"
    print(json.dumps(import_receipt(request, receipt, root, output)))


if __name__ == "__main__":
    main()
