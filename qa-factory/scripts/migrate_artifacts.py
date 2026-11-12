"""Explicit, resumable migration of legacy machine artifacts. No conflict guessing.

`--if-older` is the resume-time entry point: a story continued on a plugin
newer than the one that last wrote it (normal for the pilot, not a special case) carries
artifacts spelled the way that older build wrote them. This runs every migration that
applies exactly once — comparing `story_version` against the installed build, moving legacy
flat files (as `--apply` always has), canonicalizing `automation-manifest.json` instance
ids that still carry the 0.7.7 `<case>::<function>` prefix (`contract.instance_id_aliases`),
retracting case-shaped ghost rows and the older-still function-selector rows once real
per-instance coverage exists, renaming `OB-n` obligation ids to the ones the plan names
(`contract.legacy_obligation_map`) — then stamps the story with the installed version so a second
run is a no-op. An artifact this cannot migrate is reported with a reason and never blocks the
rest or raises into the caller.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
import hooklib
from artifact_registry import entries, canonical
from event_store import EventStore, atomic_json
import contract as C
import story_version


def plan(task_root):
    root = Path(task_root).resolve()
    actions, conflicts = [], []
    for name, rule in entries().items():
        if not rule.get("legacy_alias"):
            continue
        old, target = root / rule["legacy_alias"], canonical(root, name)
        if not old.is_file():
            continue
        digest = hashlib.sha256(old.read_bytes()).hexdigest()
        if target.exists() and target.read_bytes() != old.read_bytes():
            conflicts.append(name)
        else:
            actions.append({"name": name, "source": str(old), "target": str(target), "sha256": digest})
    return {"task_id": root.name, "actions": actions, "conflicts": conflicts}


def migrate(root):
    root = Path(root).resolve()
    store = EventStore(root)
    with store.lock():
        report = plan(root)
        if report["conflicts"]:
            raise ValueError("migration conflict: " + ", ".join(report["conflicts"]))
        intent = root / "state/migration-intent.json"
        atomic_json(intent, dict(report, status="planned"))
        for action in report["actions"]:
            old, target = Path(action["source"]), Path(action["target"])
            if hashlib.sha256(old.read_bytes()).hexdigest() != action["sha256"]:
                raise ValueError("legacy artifact changed during migration")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                archive = root / "state/migration" / action["name"]
                archive.parent.mkdir(parents=True, exist_ok=True)
                if archive.exists() and archive.read_bytes() != old.read_bytes():
                    raise ValueError("migration archive conflict")
                old.replace(archive)
            else:
                old.replace(target)
        atomic_json(intent, dict(report, status="completed"))
    return report


# --- --if-older: version-aware, run-once migration --------------------------

def _find_project_root(task_root: Path):
    """The nearest ancestor carrying `qa-factory/config.json` — the same marker
    `hooklib._nearest_project` walks up to, duplicated here (not imported: hooklib is another
    package's file) because this script has never depended on the project layout, only on the
    exact task root it is given, and `manifest_put.py` needs a real project root to resolve
    its own paths through."""
    for candidate in (Path(task_root), *Path(task_root).parents):
        if (candidate / "qa-factory" / "config.json").is_file():
            return candidate
    return None


def _manifest_put_py() -> str:
    return str(Path(__file__).resolve().parent / "manifest_put.py")


def _run_manifest_put(root: Path, task_id: str, project_root: Path, fragment: dict) -> tuple:
    """One `manifest_put` call. -> (ok, reason). `manifest_put` is the artifact's own writer
    (handles the lock, the revision, `contract.instance_id_aliases`) — every migration here
    feeds it a fragment instead of re-implementing any of its merge."""
    fragment_path = root / "state" / f"migration-fragment-{uuid.uuid4().hex[:8]}.json"
    fragment_path.parent.mkdir(parents=True, exist_ok=True)
    fragment_path.write_text(json.dumps(fragment, ensure_ascii=False), encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-B", _manifest_put_py(), "--task", task_id,
             "--fragment", str(fragment_path)],
            cwd=str(project_root), capture_output=True, text=True, timeout=60)
    finally:
        fragment_path.unlink(missing_ok=True)
    from manifest_put import outcome
    kind, move = outcome(proc.returncode, task_id)
    if kind == "committed":
        return True, ""
    said = (proc.stderr or proc.stdout or "manifest_put failed").strip()
    if kind == "stale":     # exit 4: the fragment IS in the journal, only the manifest's projection failed: replay it
        return False, f"committed, the manifest's projection is stale - run `{move}`: {said}"[:300]
    return False, said[:300]


def _read_manifest(root: Path) -> dict:
    manifest_path = C.artifact(root, "automation-manifest.json")
    if not manifest_path.is_file():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _fix_legacy_spellings(root: Path, task_id: str, project_root: Path, manifest: dict) -> dict:
    """Canonicalize every `tests[]` row still spelled `<case>::<function>`, in ONE
    `manifest_put` call for the whole manifest — not one call per row.

    `manifest_put` refuses a fragment where two rows collide on one bare id
    (`_refuse_colliding_ids`, two files sharing a function name), and that guard only ever
    sees the rows of ONE fragment at once. Calling it once per row would defeat it: two old
    rows that legitimately collide on their new bare spelling would each be sent alone, the
    second patch would silently match the row the first one just renamed (same alias, wrong
    file), and a real ambiguity manifest_put exists to catch would become a silent corruption
    instead of a refusal. One fragment keeps that guard intact; a refusal here leaves the
    whole manifest reported under `left`, not each row separately.
    """
    patches, spellings = [], []
    for entry in manifest.get("tests") or []:
        if not isinstance(entry, dict):
            continue
        current = C.test_instance_id(entry)
        if C.INSTANCE_SEP not in current:
            continue  # already the current spelling — nothing to do
        bare = current.split(C.INSTANCE_SEP, 1)[-1]
        patch = {"instance_id": bare}
        if entry.get("file"):
            patch["file"] = entry["file"]
        patches.append(patch)
        spellings.append(f"{current} -> {bare}")
    if not patches:
        return {"changed": [], "left": []}
    ok, reason = _run_manifest_put(root, task_id, project_root, {"tests": patches})
    if not ok:
        return {"changed": [], "left": [{"artifact": "automation-manifest.json", "reason": reason}]}
    return {"changed": [f"tests[] spelling canonicalized: {len(patches)} ("
                        + ", ".join(spellings) + ")"], "left": []}


def _is_case_shaped_id(value: str, cfg: dict | None = None) -> bool:
    """True for `TC-012` / `speakers/TC-012` (or the project's own form, `config.case_id_form`) —
    a case id, not a function-derived instance id. `cfg` is the project config a loop resolved once."""
    text = str(value or "").strip()
    if not text or C.INSTANCE_SEP in text:
        return False
    return C.is_case_id(text.rsplit("/", 1)[-1], cfg=C.case_config() if cfg is None else cfg)


def _retract_case_ghosts(root: Path, task_id: str, project_root: Path, manifest: dict) -> dict:
    """Retract a `tests[]` row whose `instance_id` IS a case id (`"TC-012"`, no function) —
    a 0.7.6 window's placeholder, written before per-instance rows existed. `manifest_test_keys`
    / `contract.instance_id_aliases` never see it: its identity shares no alias with the real
    per-instance row that proves the same case today, so `_retract_aliases` cannot collapse it
    (seen on the live TP1-15045 manifest). Only retracted when some OTHER,
    non-ghost row already covers the same case — otherwise the case would lose its only proof,
    so the ghost is left exactly as it stands and reported under `left`.

    manifest_put exposes no direct "delete this row" verb, so this uses the two mechanisms it
    already has and already tests: a row not matched by any incoming identity, and whose every
    covered case moved to `unresolved[]`, is dropped (`_moved_out`); a `tests[]` patch matched
    by identity is never dropped, whatever `unresolved[]` says in the same fragment (`if match`
    is checked first). One call resends every real covering row (protecting it) alongside an
    `unresolved[]` entry per retracted case (dropping the unmatched ghost); because the new
    `unresolved[]` rows are added by THIS same fragment, clearing them needs a second call that
    resends the same covering rows with no `unresolved[]` at all — that is when
    `drop_from_unresolved` removes them, leaving no residue.
    """
    tests = [e for e in manifest.get("tests") or [] if isinstance(e, dict)]
    # The story's project config and every real row's case keys, each computed once: ghosts x
    # real rows x keys was three config stats per comparison (B-013 performance).
    cfg = C.case_config(root)
    ghosts, real_rows = [], []
    for entry in tests:
        (ghosts if _is_case_shaped_id(C.test_instance_id(entry), cfg) else real_rows).append(entry)
    if not ghosts:
        return {"changed": [], "left": []}
    real_keys = [(r, C.manifest_test_keys(r, cfg)) for r in real_rows]

    retract, left = [], []
    for ghost in ghosts:
        case_id = str(ghost.get("case") or C.test_instance_id(ghost)).strip()
        case_key = C.case_key(case_id, str(ghost.get("area") or "").strip(), cfg=cfg)
        covering = [r for r, keys in real_keys
                   if any(C.case_matches(case_key, key, cfg=cfg) for key in keys)]
        if covering:
            retract.append((case_key, covering))
        else:
            left.append({"artifact": f"tests[]:{case_key}",
                         "reason": "case-shaped ghost row with no real per-instance row "
                                   "covering it — left as it stands, not retracted"})
    if not retract:
        return {"changed": [], "left": left}

    protect = {}
    for _, covering in retract:
        for row in covering:
            protect.setdefault(C.test_instance_id(row), row)
    resend = list(protect.values())
    unresolved = [{"case": case_key} for case_key, _ in retract]

    ok, reason = _run_manifest_put(root, task_id, project_root,
                                   {"tests": resend, "unresolved": unresolved})
    if not ok:
        return {"changed": [], "left": left + [{"artifact": "automation-manifest.json",
                "reason": f"ghost retraction: {reason}"}]}
    # Second call: no `unresolved[]` this time, so the whole-case rows the first call added are
    # cleared by `drop_from_unresolved` (the real rows are green and cover them) instead of
    # standing as a false "not proven" record for a case the manifest has always had evidence for.
    ok2, reason2 = _run_manifest_put(root, task_id, project_root, {"tests": resend})
    if not ok2:
        left.append({"artifact": "automation-manifest.json",
                     "reason": f"ghost retraction left a stray unresolved[] row: {reason2}"})
    changed = [f"tests[] ghost retracted: {case_key} (covered by "
              + ", ".join(sorted(C.test_instance_id(r) for r in covering)) + ")"
              for case_key, covering in retract]
    return {"changed": changed, "left": left}


_LEGACY_SELECTOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\[\]]+\])?$")


def _is_legacy_selector_row(entry: dict) -> bool:
    """True for the very oldest `tests[]` shape — written before per-instance rows existed at
    all: no `instance_id`, a `case`, and a bare function-level `selector`
    (`test_x[valid|missing-assistant]`, partitions joined by `|`; or just `test_x` with none) —
    never the `::`-joined node id a real per-instance row's own `selector` field carries.
    `_fix_legacy_spellings` never sees this row (no `::` to canonicalize) and
    `_retract_case_ghosts` never sees it either (its derived identity is the function name, not
    a case id) — left on the live TP1-15045 manifest as the TC-012 row, retracted by hand
    (revision 44) because nothing migrated it.
    """
    if not isinstance(entry, dict):
        return False
    if str(entry.get("instance_id") or entry.get("test_instance_id") or "").strip():
        return False
    if not str(entry.get("case") or "").strip():
        return False
    selector = str(entry.get("selector") or "").strip()
    return bool(selector) and bool(_LEGACY_SELECTOR_RE.fullmatch(selector))


def _retract_legacy_selector_rows(root: Path, task_id: str, project_root: Path,
                                  manifest: dict) -> dict:
    """Retract a `tests[]` row of the oldest shape (`_is_legacy_selector_row`) when a real
    per-instance row already proves the same case with the same test function — same two
    `manifest_put` mechanisms `_retract_case_ghosts` uses: one call resends every covering row
    (protecting it) alongside an `unresolved[]` entry per retracted case (dropping the row
    nothing matches), a second call resends the same covering rows with no `unresolved[]` so
    `drop_from_unresolved` clears what the first call added. Left standing, and reported, when
    no per-instance row of that function covers the case — the row is not guessed away."""
    tests = [e for e in manifest.get("tests") or [] if isinstance(e, dict)]
    legacy, real_rows = [], []
    for entry in tests:
        (legacy if _is_legacy_selector_row(entry) else real_rows).append(entry)
    if not legacy:
        return {"changed": [], "left": []}

    cfg = C.case_config(root)  # once, with each real row's keys: B-013 performance
    real_keys = [(r, C.manifest_test_keys(r, cfg)) for r in real_rows]
    retract, left = [], []
    for row in legacy:
        case_id = str(row.get("case") or "").strip()
        case_key = C.case_key(case_id, str(row.get("area") or "").strip(), cfg=cfg)
        function = C.function_name(row.get("selector"))
        covering = [r for r, keys in real_keys
                   if C.function_name(C.test_instance_id(r)) == function
                   and any(C.case_matches(case_key, key, cfg=cfg) for key in keys)]
        if covering:
            retract.append((case_key, function, covering))
        else:
            left.append({"artifact": f"tests[]:{case_key}::{function}",
                         "reason": "legacy function-level selector row with no per-instance "
                                   "row of the same function covering the same case — left "
                                   "as it stands, not retracted"})
    if not retract:
        return {"changed": [], "left": left}

    protect = {}
    for _, _, covering in retract:
        for row in covering:
            protect.setdefault(C.test_instance_id(row), row)
    resend = list(protect.values())
    unresolved = [{"case": case_key} for case_key, _, _ in retract]

    ok, reason = _run_manifest_put(root, task_id, project_root,
                                   {"tests": resend, "unresolved": unresolved})
    if not ok:
        return {"changed": [], "left": left + [{"artifact": "automation-manifest.json",
                "reason": f"legacy selector retraction: {reason}"}]}
    # Second call: no `unresolved[]` this time, so the whole-case rows the first call added are
    # cleared by `drop_from_unresolved` (the real rows are green and cover them) instead of
    # standing as a false "not proven" record for a case the manifest has always had evidence for.
    ok2, reason2 = _run_manifest_put(root, task_id, project_root, {"tests": resend})
    if not ok2:
        left.append({"artifact": "automation-manifest.json",
                     "reason": f"legacy selector retraction left a stray unresolved[] row: {reason2}"})
    changed = [f"tests[] legacy selector row retracted: {case_key} ({function}, covered by "
              + ", ".join(sorted(C.test_instance_id(r) for r in covering)) + ")"
              for case_key, function, covering in retract]
    return {"changed": changed, "left": left}


def _legacy_obligation_patches(manifest: dict, mapping: dict) -> tuple:
    """(`tests[]` patches, spellings changed, ids left) for `OB-n` inside `tests[]` rows.

    An instance cites its obligations twice — `obligation_refs[{obligation_id, obligation_hash}]`
    and the `obligation_ids[]` that must agree with them (`controller` enforces both). Renaming
    only `obligation_bindings[]` would leave the instance rows still spelling `OB-n`, and the
    contradiction is a harder refusal than the one being repaired."""
    patches, spellings, left = [], [], []
    for entry in manifest.get("tests") or []:
        if not isinstance(entry, dict):
            continue
        refs = [r for r in entry.get("obligation_refs") or [] if isinstance(r, dict)]
        ids = [str(i) for i in entry.get("obligation_ids") or [] if i]
        legacy = ({str(r.get("obligation_id") or "") for r in refs} | set(ids))
        legacy = {i for i in legacy if C.LEGACY_OBLIGATION_RE.match(i)}
        if not legacy:
            continue
        unmapped = sorted(i for i in legacy if i not in mapping)
        if unmapped:
            left.append({"artifact": f"tests[]:{C.test_instance_id(entry)}",
                         "reason": f"cites {', '.join(unmapped)}, which is beyond the plan's "
                                   "obligation count — left as it stands, never guessed"})
            continue
        patch = {"instance_id": C.test_instance_id(entry)}
        if entry.get("file"):
            patch["file"] = entry["file"]
        if refs:
            patch["obligation_refs"] = [dict(r, obligation_id=mapping.get(
                str(r.get("obligation_id") or ""), r.get("obligation_id"))) for r in refs]
        if ids:
            patch["obligation_ids"] = [mapping.get(i, i) for i in ids]
        patches.append(patch)
        spellings.append(f"{C.test_instance_id(entry)}: " + ", ".join(
            f"{i} -> {mapping[i]}" for i in sorted(legacy)))
    return patches, spellings, left


def _rename_legacy_obligations(root: Path, task_id: str, project_root: Path,
                               manifest: dict) -> dict:
    """Rename `OB-n` to the n-th obligation the plan names, by position
    (`contract.legacy_obligation_map`).

    TP2-2553: the plan spelled `TS-1-O1..TS-3-O3` and every binding the automator wrote
    spelled `OB-1..OB-9`. `coverage_projection` joins by exact equality, so the story reached
    delivery with `unique_instances: 0` and nine coverage gaps over twelve green instances.
    Position is the only reading under which those ids name anything: the automator wrote them
    in plan order, one per obligation. An `OB-n` past the plan's count names nothing, and an
    `OB-n` whose plan id already carries a binding of its own would have to be merged with it —
    both are reported under `left` and left exactly as they stand.

    One `manifest_put` call carries the whole rename: the renamed bindings, the old spellings in
    `retracted_obligations` (so the map is not left holding both), and the `tests[]` patches
    that re-cite the same ids. `manifest_put` accepts it because the new ids are the plan's by
    construction — it refuses precisely the spelling this pass removes."""
    mapping = C.legacy_obligation_map(root)
    bindings = [b for b in manifest.get("obligation_bindings") or [] if isinstance(b, dict)]
    if not bindings:
        return {"changed": [], "left": []}
    existing = {str(b.get("obligation_id") or "") for b in bindings}
    renamed, retract, changed, left = [], [], [], []
    for binding in bindings:
        old = str(binding.get("obligation_id") or "")
        if not C.LEGACY_OBLIGATION_RE.match(old):
            continue
        new = mapping.get(old)
        if not new:
            left.append({"artifact": f"obligation_bindings[]:{old}",
                         "reason": "no obligation at that position in the plan "
                                   f"({len(mapping)} named) — left as it stands, never guessed"})
            continue
        if new in existing:
            left.append({"artifact": f"obligation_bindings[]:{old}",
                         "reason": f"{new} already carries a binding of its own; merging the "
                                   "two is a person's decision — left as it stands"})
            continue
        renamed.append(dict(binding, obligation_id=new))
        retract.append(old)
        changed.append(f"{old} -> {new}")
    patches, spellings, cited_left = _legacy_obligation_patches(manifest, {
        old: new for old, new in zip(retract, [b["obligation_id"] for b in renamed])})
    left.extend(cited_left)
    if not renamed:
        return {"changed": [], "left": left}

    fragment = {"obligation_bindings": renamed, "retracted_obligations": retract}
    if patches:
        fragment["tests"] = patches
    ok, reason = _run_manifest_put(root, task_id, project_root, fragment)
    if not ok:
        return {"changed": [], "left": left + [{"artifact": "automation-manifest.json",
                "reason": f"obligation rename: {reason}"}]}
    note = "obligation_bindings[] renamed to the plan's ids: " + ", ".join(changed)
    if spellings:
        note += " | instances re-cited: " + "; ".join(spellings)
    return {"changed": [note], "left": left}


def _migrate_instance_ids(root: Path, task_id: str, project_root: Path) -> dict:
    """Every `automation-manifest.json` fix that depends on the plugin's current identity
    rules, each pass seeing what the one before it left: legacy `<case>::<function>` spellings
    canonicalized, then case-shaped ghost rows retracted, then the oldest function-selector
    rows retracted against whatever real coverage remains, then the `OB-n` obligation ids of
    TP2-2553 renamed to the ids the plan actually names — last, so it renames only the
    rows the retractions left standing."""
    try:
        manifest = _read_manifest(root)
    except Exception as exc:
        return {"changed": [], "left": [{"artifact": "automation-manifest.json",
                 "reason": f"unreadable: {type(exc).__name__}: {exc}"}]}
    if not manifest:
        return {"changed": [], "left": []}

    spellings = _fix_legacy_spellings(root, task_id, project_root, manifest)
    try:
        manifest = _read_manifest(root)  # spellings may have changed identities; re-read
    except Exception as exc:
        spellings["left"].append({"artifact": "automation-manifest.json",
                                  "reason": f"unreadable after spelling fix: {type(exc).__name__}: {exc}"})
        return spellings
    ghosts = _retract_case_ghosts(root, task_id, project_root, manifest)
    try:
        manifest = _read_manifest(root)  # ghost retraction may have changed rows; re-read
    except Exception as exc:
        return {"changed": spellings["changed"] + ghosts["changed"],
                "left": spellings["left"] + ghosts["left"] + [{"artifact": "automation-manifest.json",
                        "reason": f"unreadable after ghost retraction: {type(exc).__name__}: {exc}"}]}
    legacy_selectors = _retract_legacy_selector_rows(root, task_id, project_root, manifest)
    try:
        manifest = _read_manifest(root)  # the retraction may have dropped rows; re-read
    except Exception as exc:
        return {"changed": spellings["changed"] + ghosts["changed"] + legacy_selectors["changed"],
                "left": spellings["left"] + ghosts["left"] + legacy_selectors["left"]
                + [{"artifact": "automation-manifest.json",
                    "reason": f"unreadable after selector retraction: {type(exc).__name__}: {exc}"}]}
    obligations = _rename_legacy_obligations(root, task_id, project_root, manifest)
    return {"changed": spellings["changed"] + ghosts["changed"] + legacy_selectors["changed"]
            + obligations["changed"],
            "left": spellings["left"] + ghosts["left"] + legacy_selectors["left"]
            + obligations["left"]}


def _journal_migration(task_id: str, report: dict) -> None:
    """Best-effort, one line for the whole run — a migration that ran must not be lost because
    the journal could not be written (same shape as `archive_task.journal`)."""
    changed, left = report.get("changed") or [], report.get("left") or []
    notes = f"{report.get('from') or '(unrecorded)'} -> {report.get('to')}: " + (
        "; ".join(changed) if changed else "nothing to migrate")
    if left:
        notes += " | left: " + "; ".join(f"{x['artifact']} ({x['reason'][:80]})" for x in left)
    try:
        from log_append import build_record, write
        write([build_record({"event": "artifacts_migrated", "task": task_id, "notes": notes[:2000]})])
    except Exception:
        pass


def run_if_older(task_root) -> dict:
    """Run every migration that applies, exactly once per plugin upgrade, then stamp the
    story with the installed version so a second run this same version is a cheap no-op."""
    root = Path(task_root).resolve()
    task_id = root.name
    versions = story_version.check(root)
    if not versions["older"]:
        return {"task_id": task_id, "ran": False, **versions}

    changed, left = [], []
    try:
        flat = migrate(root)
        if flat.get("actions"):
            changed.append(f"legacy files relocated: {len(flat['actions'])}")
    except Exception as exc:
        left.append({"artifact": "legacy files", "reason": f"{type(exc).__name__}: {exc}"})

    project_root = _find_project_root(root)
    if project_root is None:
        left.append({"artifact": "automation-manifest.json",
                     "reason": "no qa-factory/config.json found above the task root"})
    else:
        try:
            instance_ids = _migrate_instance_ids(root, task_id, project_root)
        except Exception as exc:
            instance_ids = {"changed": [], "left": [{"artifact": "automation-manifest.json",
                            "reason": f"{type(exc).__name__}: {exc}"}]}
        changed.extend(instance_ids["changed"])
        left.extend(instance_ids["left"])

    try:
        story_version.record(root, versions["installed"])
    except Exception:
        pass  # migrations already applied are not undone by a version-stamp failure
    report = {"task_id": task_id, "ran": True, "from": versions["recorded"],
              "to": versions["installed"], "changed": changed, "left": left}
    _journal_migration(task_id, report)
    return report


def main():
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("task_root", nargs="?", default=None)
    parser.add_argument("--task-root", dest="task_root_flag", default=None,
                        help="alternative to the positional argument")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--if-older", action="store_true",
                        help="run every migration that applies only when the story's "
                             "recorded plugin_version is older than the installed one")
    args = hooklib.exact_options(parser).parse_args()
    root = args.task_root_flag or args.task_root
    if not root:
        parser.error("a task root is required: positional, or --task-root")
    hooklib.story_cli("migrate_artifacts.py", root=root, key_flag=None)      # an existing story, before anything is planned
    if args.if_older:
        print(json.dumps(run_if_older(root)))
        return
    print(json.dumps(migrate(root) if args.apply else plan(root)))


if __name__ == "__main__":
    main()
