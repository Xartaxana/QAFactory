"""Structural validation of S1 test candidates; semantic sufficiency remains a review decision."""
from pathlib import Path
import re


KINDS = {"test", "suite", "helper"}
EXECUTION_BOUNDARIES = {"unit", "component", "integration", "api", "e2e-ui", "unknown"}
_REF = re.compile(r"^(?P<path>.+):(?P<line>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?(?:#(?P<symbol>.+))?$")


def _within(root, raw):
    path = (Path(root).resolve() / str(raw)).resolve()
    if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
        raise ValueError("candidate path is missing or outside repository root")
    return path


def assess_candidate(candidate, repo_root):
    """Return facts/gaps without making absent evidence look like a schema failure.

    `valid` is structural only. `assertion_status=sufficient` means references point at
    readable test-file lines; it is deliberately not a semantic coverage verdict.
    """
    gaps, refs = [], []
    if not isinstance(candidate, dict):
        return {"valid": False, "executable": False, "assertion_status": "unknown",
                "gaps": ["candidate must be an object"], "assertion_refs": []}
    kind = candidate.get("kind", "test")
    if kind not in KINDS:
        return {"valid": False, "executable": False, "assertion_status": "unknown",
                "gaps": ["candidate kind must be test, suite, or helper"], "assertion_refs": []}
    try:
        test_file = _within(repo_root, candidate.get("path"))
    except (TypeError, ValueError):
        return {"valid": False, "executable": False, "assertion_status": "unknown",
                "gaps": ["candidate test file is unavailable"], "assertion_refs": []}
    boundary = candidate.get("execution_boundary", "unknown")
    if boundary not in EXECUTION_BOUNDARIES:
        return {"valid": False, "executable": False, "assertion_status": "unknown",
                "gaps": ["candidate execution boundary is invalid"], "assertion_refs": []}
    if boundary == "unknown":
        gaps.append("candidate execution boundary is unknown")
    selector = candidate.get("selector")
    selector_known = isinstance(selector, str) and bool(selector.strip()) and selector.strip().lower() not in {
        "unknown", "none", "n/a", "not_found", "unresolved"}
    executable = kind == "test" and selector_known
    if kind == "test" and not executable:
        gaps.append("test has no executable selector")
    if kind == "suite":
        selectors = candidate.get("expanded_selectors")
        executable = isinstance(selectors, list) and bool(selectors) and all(isinstance(s, str) and s for s in selectors)
        if not executable:
            gaps.append("suite has no expanded executable selectors")
    if kind == "helper":
        executable = False
        gaps.append("helper is not an executable test")
    lines = test_file.read_text(encoding="utf-8", errors="replace").splitlines()
    implementation_refs = set(candidate.get("implementation_refs") or [])
    for raw in candidate.get("assertion_refs") or []:
        match = _REF.match(raw) if isinstance(raw, str) else None
        if not match:
            gaps.append("assertion reference is not path:line")
            continue
        declared = (Path(repo_root).resolve() / match.group("path")).resolve()
        line, end = int(match.group("line")), int(match.group("end") or match.group("line"))
        if raw in implementation_refs:
            gaps.append("assertion reference is also labelled implementation evidence")
            continue
        if (declared != test_file or end < line or end > len(lines) or
                any(not text.strip() for text in lines[line - 1:end])):
            gaps.append("assertion reference does not resolve to a nonempty test-file line")
            continue
        refs.append(raw)
    if not refs:
        gaps.append("candidate has no resolvable assertion references")
    assertion_gaps = [gap for gap in gaps if "assertion" in gap]
    return {"valid": True, "executable": executable,
            "assertion_status": "sufficient" if refs and executable and not assertion_gaps and boundary != "unknown" else "unknown",
            "gaps": sorted(set(gaps)), "assertion_refs": refs,
            "test_file": str(test_file), "kind": kind, "execution_boundary": boundary,
            "channel": candidate.get("channel", "unknown"),
            "runtime": candidate.get("runtime", "unknown"),
            "framework": candidate.get("framework", "unknown"),
            "ownership": candidate.get("ownership", "unknown")}
