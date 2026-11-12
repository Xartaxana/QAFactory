"""Build the exact compact-record allowlist for delivery and clean-checkout recovery.

Evidence (`evidence/**`, `work/evidence/**`) is never in it: git ignores both folders and the screenshots
stay with the tester (owner, 29.10.2026), so a clean checkout recovers the compact records, not the
evidence. `build` still checks the evidence index and its files, it only does not list them."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402
from artifact_registry import entries  # noqa: E402

RAW_SUFFIXES = {".log", ".xml", ".trx", ".png", ".jpg", ".jpeg", ".webm", ".zip"}


def approved_paths() -> set[str]:
    """Registry-owned delivery paths, including an exact legacy alias where declared."""
    paths = set()
    for rule in entries().values():
        if rule.get("delivery") not in (True, "compact-record"):
            continue
        paths.add(rule["path"])
        if rule.get("legacy_alias"):
            paths.add(rule["legacy_alias"])
    return paths


def _volatile() -> set:
    """The compact records the factory rewrites by design after the manifest is built."""
    import contract as C
    return set(C.DELIVERY_VOLATILE_PATHS)


def _error_text(errors, named: int = 3) -> str:
    """The first `named` export errors as one line (`case: reason`), then the count of the rest."""
    parts = []
    for item in errors[:named]:
        item = item if isinstance(item, dict) else {}
        reasons = item.get("errors")
        reasons = reasons if isinstance(reasons, list) else [reasons]
        parts.append(f"{item.get('case')}: " + ", ".join(str(r) for r in reasons))
    if len(errors) > named:
        parts.append(f"+{len(errors) - named} more")
    return "; ".join(parts)


def build(task_root: Path) -> dict:
    selected = []
    allowed = approved_paths()
    for path in task_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(task_root).as_posix()
        if path.suffix.lower() in RAW_SUFFIXES or rel.startswith(("work/evidence/", "evidence/")):
            continue    # evidence stays on the tester's machine: git ignores both folders (OH3-33)
        keep = rel in allowed or rel.startswith("work/test-cases/")
        keep = keep or rel.startswith("state/case-versions/")
        if keep:
            row = {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "bytes": path.stat().st_size}
            # A record the factory itself rewrites after this build is marked here, not
            # discovered later as tampering. On TP2-2553 the manifest was assembled at
            # S8 step 2 and then acceptance appended to `state/events.jsonl`, the waiver and
            # the ledger rewrote theirs — four "stale hash" delivery reasons about records
            # nobody touched by hand, at `finalization-receipt: complete`.
            if rel in _volatile():
                row["volatile"] = True
            selected.append(row)
    index_path = task_root / "evidence" / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        import contract as C
        from manual_evidence import export_records
        from coverage_contract import validate_manual_current
        report = C.load_json(C.artifact(task_root, "run-report.json"))
        current = [r for r in report.get("current_manual_checks", [])
                   if r.get("schema_version") == 2 and r.get("evidence_validated")
                   and not validate_manual_current(task_root, r)]
        # OH3-33: the evidence files are CHECKED here (a stale index or a changed file is still refused: a
        # corrupted manual record must not turn green because its copy no longer travels) but NOT added to
        # `files[]` - git ignores both evidence folders, and `git add` of an ignored path refuses.
        door = f"; rebuild the index and the copies: ledger.py {task_root}"
        fresh = export_records(task_root, current)
        if fresh.get("errors"):
            # A copy under evidence/ that differs from its source is not rebuilt by ledger.py (the export refuses to
            # overwrite it: "public export hash conflict"), so the door for this case removes the changed copy first.
            raise ValueError("manual public evidence export has unresolved errors: " + _error_text(fresh["errors"])
                             + "; if a copy under evidence/ differs from its source (its file name is its sha256), "
                             f"delete that changed copy, then run: ledger.py {task_root}")
        if index != fresh:
            raise ValueError("manual evidence index is not the current approved projection" + door)
        for row in index.get("rows", []):
            for ref in row.get("evidence_refs", []):
                path = (task_root / ref["path"]).resolve()
                if (not path.is_relative_to(task_root.resolve()) or not path.is_relative_to((task_root / "evidence").resolve()) or not path.is_file()
                        or hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]):
                    raise ValueError("manual evidence file missing or changed" + door)
    selected.sort(key=lambda item: item["path"])
    return {"schema_version": 1, "task_id": task_root.name, "files": selected,
            "excluded": ["evidence/**", "work/evidence/**", "*.log", "*.xml", "*.trx", "unlisted screenshots/media"]}


MANIFEST_PATH = ("state", "delivery-manifest.json")


def refresh(task_root: Path) -> dict | None:
    """Rebuild an EXISTING delivery manifest in place; `None` when the story has none.

    The manifest is a statement about the story as it stands, and S8 step 2 assembles it
    before the writes that close the story have happened: acceptance, the waiver and the
    ledger all run after it. Rebuilding it as the last act of `finalize_task.py` is what
    makes `delivery manifest: stale hash` mean tampering again instead of meaning the
    factory did its own job in its own order (TP2-2553). It creates nothing: a story
    that never prepared a manifest is not given one here.
    """
    task_root = Path(task_root)
    path = task_root.joinpath(*MANIFEST_PATH)
    if not path.is_file():
        return None
    from event_store import atomic_json
    doc = build(task_root)
    atomic_json(path, doc)
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-root", required=True)
    ap.add_argument("--output", required=True)
    args = hooklib.exact_options(ap).parse_args()
    result = build(hooklib.story_cli("delivery_manifest.py", root=args.task_root, key_flag=None))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
