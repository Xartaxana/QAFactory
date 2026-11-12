"""Managed dependencies stay pinned, scoped, and inert without authorization."""
import sys
from pathlib import Path

from harness import check, check_eq, finish

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from managed_dependency import (DependencyError, descriptor_hash, install, probe,
                                validate_descriptor)  # noqa: E402


def descriptor() -> dict:
    return {"dependency_id": "python-runtime", "upstream_source": "python.org",
            "exact_version_or_revision": f"{sys.version_info.major}.{sys.version_info.minor}",
            "capability": "api", "consumer": "runner", "owner": "project",
            "executable": sys.executable, "version_argv": [sys.executable, "--version"],
            "install_argv": [sys.executable, "-c", "print('would install pinned dependency 3.12')",
                             f"{sys.version_info.major}.{sys.version_info.minor}"],
            "skill_install_argv": [sys.executable, "-c", "print('skill installed')"]}


def main() -> None:
    data = validate_descriptor(descriptor())
    check_eq("existing CLI without required upstream skill is partial", probe(data, Path.cwd())["status"],
             "partial")
    check_eq("missing upstream skill is explicitly not ready", probe(data, Path.cwd())["skill_ready"], False)
    cli_only = {k: v for k, v in data.items() if k != "skill_install_argv"}
    check_eq("CLI-only descriptor remains ready", probe(cli_only, Path.cwd())["status"], "ready")
    absent = {**data, "executable": "qa-no-such-managed-tool",
              "version_argv": ["qa-no-such-managed-tool", "--version"]}
    check_eq("missing selected dependency is unavailable", probe(absent, Path.cwd())["status"], "unavailable")
    try:
        install(data, Path.cwd(), None)
        denied = False
    except DependencyError as exc:
        denied = "authorization" in str(exc)
    check("install never runs without explicit authorization", denied)
    wrong_receipt = {"action": "install_dependency", "dependency_id": data["dependency_id"],
                     "descriptor_sha256": "wrong", "authorization_source": "gate:p3"}
    try:
        install(data, Path.cwd(), wrong_receipt)
        bound_denied = False
    except DependencyError as exc:
        bound_denied = "does not match" in str(exc)
    check("authorization is bound to exact descriptor hash", bound_denied)
    check("descriptor hash is deterministic", len(descriptor_hash(data)) == 64)
    try:
        validate_descriptor({**data, "install_argv": ["tool", "@latest"]})
        floating_denied = False
    except DependencyError as exc:
        floating_denied = "pin exact" in str(exc)
    check("floating latest dependency is rejected", floating_denied)
    try:
        validate_descriptor({**data, "owner": ""})
        owner_denied = False
    except DependencyError as exc:
        owner_denied = "owner" in str(exc)
    check("managed dependency requires an owner", owner_denied)
    receipt = install(data, Path.cwd(), {"action": "install_dependency",
        "dependency_id": data["dependency_id"], "descriptor_sha256": descriptor_hash(data),
        "authorization_source": "test-explicit"})
    check_eq("authorized install provisions package and upstream skill", len(receipt["commands"]), 2)
    check_eq("matching install receipt proves upstream skill provisioning", receipt["skill_ready"], True)
    wrong_version = {**data, "exact_version_or_revision": f"{sys.version_info.major}.{sys.version_info.minor}0"}
    check_eq("version matching rejects numeric prefix collisions", probe(wrong_version, Path.cwd())["status"],
             "unavailable")
    finish("test_managed_dependency")


if __name__ == "__main__":
    main()
