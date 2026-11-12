"""Read-only immutable source resolution before a story branch or project write."""
import argparse
import json
from pathlib import Path


def check_source_inventory(task_root, pipeline=None):
    """S1 boundary check. Explicit unavailable sources are gaps, not fabricated success."""
    task_root = Path(task_root)
    pipeline = pipeline or {}
    path = task_root / "work" / "source-inventory.json"
    required = pipeline.get("source_inventory_required") is True
    if not path.exists():
        return {"allowed": not required, "errors": (["required work/source-inventory.json is missing"]
                                                      if required else []), "gaps": []}
    try:
        from source_inventory import (load_inventory, validate_inventory, completeness, verify_inventory_files,
                                      class_kwargs, class_basis, gap_words)
        inventory = load_inventory(path)
        errors = validate_inventory(inventory)
        if not any(item.get("required") for item in inventory.get("sources", [])):
            errors.append("source inventory has no required sources")
        kinds = class_kwargs(task_root)
        # The kinds of gap the person answered about (C2-9) close their points here; a point the factory itself established
        # as out of reach (`defaulted_points`) is not in the unavailable lists below, so no error is raised and no question is
        # born from this gate: it is a line of `gaps`.
        comp = completeness(inventory, **kinds)
        verified = verify_inventory_files(task_root, inventory)
        errors.extend(verified["errors"])
        if comp["pending"]:
            errors.append("required sources remain pending: " + ", ".join(comp["pending"]))
        if comp["incomplete_materials"]:
            errors.append("source materials lack retrieval or inspection receipts: " +
                          ", ".join(comp["incomplete_materials"]))
        # An unavailable source blocks a SILENT pass, and only that. Once a person has
        # accepted it in their own words it is a recorded gap the story carries forward —
        # TP1-15045 halted a third time on gaps its owner had already accepted, because
        # this list was appended to `errors` whatever anybody had said.
        # The door belongs to whoever receives the refusal (FR-2). The exit gate hands this
        # list to the SCOUT, and `guard_pre_tool.human_word_check` refuses a role running
        # accept-gap: a role recording the person's word would be the factory excusing
        # itself. So the role is told what to hand back, and the orchestrator is told the
        # command in the same sentence - it reads the same text from `where`.
        from person_words import door
        accept = ("name it in your digest with this source id and what is missing, and the "
                  "orchestrator shows it to the person and records their words "
                  "(`" + door(f"ticket_adapter.py accept-gap --output {path} --source-id <id>") + "`, "
                  "the orchestrator's command, not a role's)")
        errors.extend(f"source unavailable and not accepted by a person: {source_id} — {accept}"
                      for source_id in comp["unavailable"])
        errors.extend(f"source material unavailable and not accepted by a person: {source_id} — {accept}"
                      for source_id in comp.get("unavailable_materials", []))
        if comp.get("review_missing"):
            errors.append("no person has reviewed the source decisions yet — show "
                          "`ticket_adapter.py review` and record the answer with `review --record`")
        by_id = {item.get("source_id"): item for item in inventory.get("sources", [])}
        gaps = []
        for source_id in comp.get("accepted_gaps", []):
            basis = class_basis(comp.get("closed_by_class"), kinds["classes"], source_id)
            gaps.append(f"accepted gap: {source_id} — {gap_words(by_id.get(source_id) or {}, comp.get('closed_by_class'), kinds['classes'])}"
                        + (f" ({basis})" if basis else ""))
        for source_id, points in (comp.get("defaulted_points") or {}).items():
            gaps.extend(f"gap by default: {source_id} — {point['name']} - {point['cause']}: {point['basis']}"
                        for point in points)
        return {"allowed": not errors, "errors": errors, "gaps": gaps,
                "awaiting_review": bool(comp.get("awaiting_review")) and verified["valid"],
                "completeness": comp, "verification": verified}
    except Exception as exc:
        return {"allowed": False, "errors": [f"source inventory cannot be read: {exc}"], "gaps": []}
import subprocess


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def _verify_source_content(root, sha, implementation_paths=None):
    declared = list(implementation_paths or [])
    for raw in declared:
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"implementation path must be repository-relative: {raw}")
    pathspec = [Path(value).as_posix() for value in declared]
    tree_cmd = ["git", "-C", str(root), "ls-tree", "-r", "-z", "--name-only", sha]
    diff_cmd = ["git", "-C", str(root), "diff", "--name-only", "-z", sha, "--"]
    if pathspec:
        tree_cmd.extend(["--", *pathspec])
        diff_cmd.extend(pathspec)
    tree_result = subprocess.run(tree_cmd, capture_output=True, timeout=30)
    diff_result = subprocess.run(diff_cmd, capture_output=True, timeout=30)
    if tree_result.returncode or diff_result.returncode:
        raise ValueError("source content comparison failed")
    source_paths = [value.decode("utf-8", "replace") for value in tree_result.stdout.split(b"\0") if value]
    mismatches = [value.decode("utf-8", "replace") for value in diff_result.stdout.split(b"\0") if value]
    missing = sorted(set(pathspec) - set(source_paths)) if pathspec else []
    mismatches = sorted(set(mismatches + missing))
    compared_count = len(pathspec) if pathspec else len(source_paths)
    bounded_paths = pathspec if pathspec and len(pathspec) <= 40 else (pathspec or source_paths)[:40]
    return {"content_verified": compared_count > 0 and not mismatches,
            "implementation_scope": "explicit_paths" if pathspec else "all_tracked",
            "implementation_path_count": compared_count,
            "implementation_paths": bounded_paths,
            "implementation_paths_truncated": compared_count > len(bounded_paths),
            "content_mismatch_count": len(mismatches),
            "content_mismatches": mismatches[:40],
            "content_mismatches_truncated": len(mismatches) > 40}


def resolve_source(root, source_ref, task, requested_branch=None, default_branch=None,
                   implementation_paths=None):
    root = Path(root).resolve()
    if not root.is_dir() or not source_ref or source_ref.startswith("-"):
        raise ValueError("existing repository and explicit source ref required")
    sha = git(root, "rev-parse", "--verify", source_ref + "^{commit}")
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "branch", "--show-current")
    dirty = git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    dirty_lines = dirty.splitlines()
    # Matching names are insufficient; the implementation must be in this tree.
    contains = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", sha, head],
                              capture_output=True, timeout=30).returncode == 0
    content = _verify_source_content(root, sha, implementation_paths)
    import re
    matches = bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(task) + r"(?![A-Za-z0-9])", branch))
    chosen = requested_branch or (branch if matches and branch != default_branch else None)
    action = ("reuse" if chosen == branch and branch and content["content_verified"]
              else "resolve_conflict" if chosen
              else "isolate_from_source" if dirty
              else "create_from_source")
    return {"repo_root": str(root), "source_ref": source_ref, "source_sha": sha,
            "head": head, "current_branch": branch, "requested_branch": requested_branch,
            "selected_branch": chosen, "implementation_present": content["content_verified"],
            "source_is_ancestor": contains, **content,
            "working_tree_status": dirty_lines[:40],
            "working_tree_status_count": len(dirty_lines),
            "working_tree_status_truncated": len(dirty_lines) > 40, "action": action,
            "qa_branch_base_sha": sha if action in {"create_from_source", "isolate_from_source"} else None,
            "write_allowed": action == "reuse",
            "ownership_action": ("create a separate worktree from source after authorization"
                                 if action == "isolate_from_source" else ""),
            "reason": ("source content differs from the working tree" if action == "resolve_conflict" and
                       content["content_mismatches"] else
                       "explicit branch/source disagreement" if action == "resolve_conflict" else ""),
            "mutated": False}


def assess_freshness(previous, current, runtime_result, current_scope, affected=None):
    """Metadata comparison never launches tests, CI, deployment or regression."""
    if runtime_result not in {"matched", "not_applicable"}:
        return {"action": "blocked", "reason": "deployment_" + ("mismatch" if runtime_result == "mismatched" else "unverified"),
                "selected": []}
    if previous == current:
        return {"action": "reuse", "selected": []}
    if current.get("requirements_revision") != previous.get("requirements_revision"):
        return {"action": "replan", "selected": [], "gate": "A"}
    selected = set(current_scope) if affected is None else set(affected) & set(current_scope)
    return {"action": "revalidate" if selected else "reuse_with_delta_reason",
            "selected": sorted(selected), "regression_recommendations": sorted(set(affected or []) - set(current_scope))}


if __name__ == "__main__":
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--source-ref", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--branch")
    ap.add_argument("--default-branch")
    ap.add_argument("--implementation-path", action="append", default=[],
                    help="repository-relative product path to compare; repeat as needed")
    a = ap.parse_args()
    # A bad `--repo` or `--source-ref` used to reach the orchestrator as a raw traceback, and
    # s0.md never says where the source ref comes from at S0 — before any revision is bound —
    # so that traceback was the FIRST thing a story saw (0.7.7 review, finding A-F12). A
    # refusal names what was wrong and what to do; it never asks the person to read Python.
    try:
        print(json.dumps(resolve_source(a.repo, a.source_ref, a.task, a.branch, a.default_branch,
                                        a.implementation_path or None), ensure_ascii=False))
    except (ValueError, OSError) as exc:
        import sys
        print(json.dumps({"error": str(exc), "owner": "factory",
                          "remedy": "--repo is an existing git repository and --source-ref a "
                                    "revision that exists in it — the commit S1 bound in "
                                    "context-manifest.implementation, or the repository's "
                                    "default branch. The controller's bootstrap "
                                    "`source_revision` is a snapshot content hash and is NOT "
                                    "a git ref (references/controller-api.md §1)"},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
