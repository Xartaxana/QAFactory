"""Probe or explicitly install one pinned, profile-scoped managed dependency."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class DependencyError(ValueError):
    pass


def validate_descriptor(data: dict) -> dict:
    required = ("dependency_id", "upstream_source", "exact_version_or_revision", "capability",
                "consumer", "owner", "executable", "version_argv")
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise DependencyError("missing descriptor fields: " + ", ".join(missing))
    if not isinstance(data["version_argv"], list) or not data["version_argv"]:
        raise DependencyError("version_argv must be a non-empty argv array")
    install = data.get("install_argv")
    if install is not None and (not isinstance(install, list) or not install):
        raise DependencyError("install_argv must be a non-empty argv array")
    if any(str(x).lower() in {"@latest", "latest"} or "@latest" in str(x).lower()
           for x in (install or [])):
        raise DependencyError("floating latest installs are forbidden; pin exact version/revision")
    if install and str(data["exact_version_or_revision"]) not in " ".join(map(str, install)):
        raise DependencyError("install_argv must contain the exact pinned version/revision")
    skill_install = data.get("skill_install_argv")
    if skill_install is not None and (not isinstance(skill_install, list) or not skill_install
                                      or any(not isinstance(x, str) or not x for x in skill_install)):
        raise DependencyError("skill_install_argv must be a non-empty string argv array")
    return data


def descriptor_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def probe(data: dict, cwd: Path, installation_receipt: dict | None = None) -> dict:
    executable = shutil.which(str(data["executable"]))
    if not executable:
        return {"status": "unavailable", "tool_ready": False,
                "skill_ready": False if data.get("skill_install_argv") else None,
                "owner": data["owner"], "note": "executable not found"}
    try:
        result = subprocess.run(data["version_argv"], cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "tool_ready": False,
                "skill_ready": False if data.get("skill_install_argv") else None,
                "owner": data["owner"],
                "note": f"version probe failed: {type(exc).__name__}: {exc}"}
    observed = (result.stdout or result.stderr).strip().splitlines()
    text = observed[0] if observed else ""
    exact = str(data["exact_version_or_revision"])
    exact_match = re.search(rf"(?<![0-9A-Za-z]){re.escape(exact)}(?![0-9A-Za-z])", text) is not None
    tool_ready = result.returncode == 0 and exact_match
    skill_required = bool(data.get("skill_install_argv"))
    skill_ready = None
    skill_note = None
    if skill_required:
        skill_path = data.get("skill_path")
        receipt_valid = (isinstance(installation_receipt, dict) and
                         installation_receipt.get("descriptor_sha256") == descriptor_hash(data) and
                         installation_receipt.get("skill_install_exit_code") == 0)
        if skill_path:
            resolved_skill = Path(skill_path)
            resolved_skill = resolved_skill if resolved_skill.is_absolute() else cwd / resolved_skill
            skill_ready = resolved_skill.exists()
            skill_note = None if skill_ready else "configured upstream skill path is missing"
        elif receipt_valid:
            skill_ready = True
        else:
            skill_ready = False
            skill_note = "upstream skill readiness is unknown; no discovered path or matching install receipt"
    status = ("ready" if tool_ready and (not skill_required or skill_ready) else
              "partial" if tool_ready and skill_required else "unavailable")
    response = {"status": status, "tool_ready": tool_ready, "skill_ready": skill_ready,
            "owner": data["owner"], "executable": executable,
            "observed_version": text, "expected_version": exact,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if skill_note:
        response["skill_note"] = skill_note
    return response


def install(data: dict, cwd: Path, authorization: dict | None) -> dict:
    expected = descriptor_hash(data)
    if not isinstance(authorization, dict) or authorization.get("action") != "install_dependency":
        raise DependencyError("installation requires a concrete authorization receipt")
    if authorization.get("dependency_id") != data["dependency_id"] or authorization.get("descriptor_sha256") != expected:
        raise DependencyError("authorization receipt does not match this dependency descriptor")
    if not authorization.get("authorization_source"):
        raise DependencyError("authorization receipt must name its source")
    argv = data.get("install_argv")
    if not argv:
        raise DependencyError("descriptor has no install_argv")
    cwd = cwd.resolve()
    if not cwd.is_dir():
        raise DependencyError("installation cwd must be an existing directory")
    commands = [argv]
    if data.get("skill_install_argv"):
        commands.append(data["skill_install_argv"])
    command_receipts = []
    try:
        for command in commands:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=int(data.get("install_timeout_s", 600)))
            command_receipts.append({"argv": command, "exit_code": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode != 0:
                break
    except (OSError, subprocess.TimeoutExpired) as exc:
        command_receipts.append({"argv": command, "exit_code": None,
                                 "error": f"{type(exc).__name__}: {exc}"})
        result = None
    exit_code = command_receipts[0].get("exit_code") if command_receipts else None
    skill_exit_code = (command_receipts[1].get("exit_code") if len(command_receipts) > 1 else None)
    receipt = {"install_exit_code": exit_code, "skill_install_exit_code": skill_exit_code,
               "install_argv": argv,
               "commands": command_receipts, "cwd": str(cwd),
               "descriptor_sha256": expected,
               "authorization_source": authorization["authorization_source"]}
    receipt.update(probe(data, cwd, receipt))
    if exit_code != 0 or skill_exit_code not in {None, 0} or len(command_receipts) != len(commands):
        receipt["status"] = "unavailable"
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe or install a pinned managed dependency")
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--authorization", type=Path,
                        help="JSON receipt binding approval to dependency id and descriptor hash")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        data = validate_descriptor(json.loads(args.descriptor.read_text(encoding="utf-8")))
        authorization = (json.loads(args.authorization.read_text(encoding="utf-8"))
                         if args.authorization else None)
        receipt = install(data, args.cwd, authorization) if args.install else probe(data, args.cwd)
    except (OSError, json.JSONDecodeError, DependencyError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}))
        raise SystemExit(2)
    print(json.dumps(receipt, indent=2))
    raise SystemExit(0 if receipt["status"] == "ready" else 1)


if __name__ == "__main__":
    main()
