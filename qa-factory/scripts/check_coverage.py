"""Coverage-map drift detector — acceptance CLI for orchestrators.

Factory law: the coverage map is a generated projection; any flow that changed
cases, statuses or red_lock ends by regenerating it. This script catches the
violation: it reconciles qa-factory/records/coverage-map.md against the actual
case frontmatter, read from the project's own case store (config.cases_root) or,
when it has none, from qa-factory/artifacts/<TICKET>/test-cases/. A mismatch ->
exit 1 (map is stale, the flow is not finished).

Usage:
    python check_coverage.py [--root <project-dir>]

--root is honoured when it IS a project (it holds qa-factory/config.json), else exit 2 naming it.
It defaults to hooklib.project_root() (env CLAUDE_PROJECT_DIR, else the project above the cwd, else
git toplevel, else cwd) when hooklib is importable, else the project above the cwd; a default that is
not a project is exit 2 too - a folder that is no project has no map to reconcile, and "OK" for it would
be a pass on something unknown (FR-59).

Called by: onboarding (after building the map), qa-story (Phase 11 acceptance),
explicit bug verification (after updating the map), release review (map freshness before
assessment), calibration.
"""
import re
import sys
import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

try:
    import console_io
    console_io.utf8_stdio()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_paths as RP  # noqa: E402 - the coverage map is a carried record (records/, or state/ in an old-layout project)
from detector_verdict import one_line  # noqa: E402 - a finding is one physical line in a detector's output
try:
    from hooklib import project_root as _project_root
except ImportError:
    def _project_root() -> Path:
        """hooklib is not importable: the project above the working directory, or the working directory
        itself when there is none (`marked_root` then refuses it)."""
        return RP.nearest_project(Path.cwd()) or Path.cwd()


def marked_root(raw: Path | None) -> tuple:
    """(project folder, "") for a root that IS a project, else (None, the refusal text).

    `raw` is `--root`, or None for the default (`_project_root()`). A folder is a project when it holds
    `qa-factory/config.json` as a file - the one marker (`runtime_paths.nearest_project`): a folder BELOW a
    project is not it, and the refusal names the project above when there is one."""
    chosen = Path(raw) if raw is not None else _project_root()
    try:
        here = chosen.resolve()
    except (OSError, ValueError):
        here = chosen
    found = RP.nearest_project(here)
    if found is not None and found == here:
        return here, ""
    above = f" The project above it is {found}: pass --root {found}." if found is not None else ""
    which = "--root" if raw is not None else "the default root (the project this process works in)"
    return None, (f"check_coverage: {which} {here} is not a factory project: it has no qa-factory/config.json, so "
                  f"there is no coverage map to reconcile and nothing was checked.{above} Expected the project "
                  "folder - run this from inside the project, or pass --root <the folder that contains "
                  "qa-factory/config.json>.")


def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.split(" #", 1)[0].strip()
        if value.lower() in ("null", "none", "~", ""):
            value = ""
        fm[key.strip()] = value
    return fm


def cases_root(root: Path) -> Path:
    from hooklib import artifact_root
    return artifact_root(root=root)


def project_cases_root(root: Path) -> Path | None:
    """The project's own case store when onboarding recorded one (config.cases_root).

    One owner for the fact (A21): contract.cases_root decides it for the story scripts,
    this reads the same key for the project-wide map."""
    try:
        import json
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = str((cfg or {}).get("cases_root") or "").strip()
    return (root / raw) if raw else None


def case_paths(root: Path) -> list:
    store = project_cases_root(root)
    if store is not None:
        return sorted(store.rglob("*.md")) if store.exists() else []
    return sorted(set(cases_root(root).glob("*/test-cases/**/*.md"))
                  | set(cases_root(root).glob("*/work/test-cases/**/*.md")))


def collect_cases(root: Path) -> dict:
    """area -> {'total': N, 'automated': N, 'max_updated': 'YYYY-MM-DD'}

    Cases live in the project's own store (config.cases_root) when it has one, else
    per-ticket: qa-factory/artifacts/<TICKET>/test-cases/**/*.md."""
    # Immutable CaseVersions never have their frontmatter rewritten after Gate A.  Derive
    # their lifecycle from the exact approved-green manifest link instead.
    import hashlib
    pinned_automated = set()
    for task in cases_root(root).glob("*"):
        try:
            import contract as C
            manifest = C.load_json(C.artifact(task, "automation-manifest.json"))
            # t-415 (B-308 b) / HF3-1 / RH1-8: the unit is the CASE, as it is for the stamp and for gate B. A pinned case counts
            # only when `case_stamp.case_hold` of ALL its live instances is empty - the ONE answer: every instance green, with
            # a GREEN run row of its own (no row, `skipped`, `partial` or a word nobody knows is not a run), approved
            # (`approved_with_fixes` included); one clean instance does not lend its pass to a held sibling (FR-18). A row of
            # `unresolved[]` for the case, under ANY spelling (`contract.case_matches`: the stamp's own matcher), keeps it out
            # (`Automated` claims the whole case), and EVERY instance must link the pinned version: this map's count equals
            # what `check_delivery._pinned_proof_reasons` demands of each test (FR-10). The imports are NOT guarded: if the join
            # cannot load, this task's `except Exception: continue` below counts nothing for it by the pinned route - the
            # refusal direction (fewer cases called automated), never a silent "no hold" that counts a case nobody ran.
            import case_stamp
            from traceability import live_tests
            cfg = C.case_config(task)   # once per story (B-013)
            runs = case_stamp.run_rows_of(task, manifest)
            live = live_tests(manifest)
            unresolved = [key for key, _ in case_stamp.unresolved_keys(manifest, cfg)]
            for pin in C.story_case_links(task):
                if not isinstance(pin, dict):
                    continue
                key = C.case_link_key(pin, cfg)
                if any(C.case_matches(key, row_key, cfg=cfg) for row_key in unresolved):
                    continue
                population = case_stamp._case_population(live, key, cfg)   # by the PIN, not a lookup in `case_holds` (a bare pin, E5-c)
                if not population or case_stamp.case_hold(population, runs):
                    continue
                if all(any(isinstance(link, dict) and str(link.get("case_id")) == str(pin.get("case_id"))
                           and str(link.get("version")) == str(pin.get("version")) for link in test.get("case_version_links") or [])
                       for test in population):
                    pinned_automated.add((str(pin.get("case_id")), pin.get("content_hash")))
        except Exception:
            continue
    areas: dict = {}
    for case in case_paths(root):
        fm = parse_frontmatter(case.read_text(encoding="utf-8", errors="replace"))
        if not fm.get("id"):
            continue  # not a case (README etc.)
        area = fm.get("area") or case.parent.name
        a = areas.setdefault(area, {"total": 0, "automated": 0, "max_updated": ""})
        a["total"] += 1
        if fm.get("status") == "Automated" or fm.get("automated_by") or (fm.get("id"), hashlib.sha256(case.read_bytes()).hexdigest()) in pinned_automated:
            a["automated"] += 1
        a["max_updated"] = max(a["max_updated"], fm.get("updated", ""))
    return areas


def parse_map(text: str) -> tuple:
    """-> (freshness_date, {area: {'total': N|None, 'automated': N|None}})"""
    fresh = None
    m = re.search(r"As-of date:\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        fresh = m.group(1)
    sections: dict = {}
    parts = re.split(r"^##\s+Area:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    # parts: [preamble, area1, body1, area2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        area, body = parts[i], parts[i + 1]
        sec = {"total": None, "automated": None}
        mt = re.search(r"\|\s*Cases created\s*\|\s*(\d+)", body)
        if mt:
            sec["total"] = int(mt.group(1))
        ma = re.search(r"\|\s*Automated\s*\|\s*(\d+)", body)
        if ma:
            sec["automated"] = int(ma.group(1))
        sections[area] = sec
    return fresh, sections


def render_map(areas: dict, as_of: str | None = None) -> str:
    """Render the canonical project-wide counter projection from case facts."""
    as_of = as_of or date.today().isoformat()
    lines = ["# Coverage map", "", f"As-of date: {as_of}", ""]
    for area, fact in sorted(areas.items()):
        lines.extend([f"## Area: {area}", "", "| Metric | Count |", "|---|---:|",
                      f"| Cases created | {fact['total']} |",
                      f"| Automated | {fact['automated']} |", ""])
    return "\n".join(lines).rstrip() + "\n"


def receipt_of(root: Path) -> Path:
    """The receipt binding the map's bytes to the case facts. It is regenerated and machine-local
    (the install table says so), so it lives in `state/` - never beside the tracked map."""
    return RP.state_file(root, "coverage-map.receipt.json")


def write_map(root: Path, areas: dict, as_of: str | None = None):
    from event_store import atomic_json
    map_path = RP.record(root, "coverage-map.md")
    text = render_map(areas, as_of)
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(text, encoding="utf-8", newline="\n")
    facts = {area: {key: value for key, value in fact.items() if key in {"total", "automated", "max_updated"}}
             for area, fact in sorted(areas.items())}
    receipt = {"schema_version": 1, "projection": "coverage-map", "as_of": as_of or date.today().isoformat(),
               "facts_hash": hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
               "map_sha256": hashlib.sha256(text.encode()).hexdigest(), "areas": facts}
    receipt_path = receipt_of(root)
    atomic_json(receipt_path, receipt)
    return map_path, receipt_path, receipt


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    root, refusal = marked_root(args.root)
    if root is None:
        print(refusal, file=sys.stderr)
        sys.exit(2)

    map_path = RP.record(root, "coverage-map.md")
    store = project_cases_root(root)
    areas = collect_cases(root) if (store or cases_root(root)).exists() else {}

    if not areas:
        where = str(store) if store else "qa-factory/artifacts/*/test-cases/"
        print(f"OK: no local cases ({where} is empty) — counter reconciliation not applicable")
        sys.exit(0)

    if args.write:
        path, receipt_path, receipt = write_map(root, areas, args.as_of)
        print(f"WROTE: {path} and {receipt_path} ({receipt['map_sha256']})")
        sys.exit(0)

    if not map_path.exists():
        print("REJECT — 1 problem(s): the map is stale:")
        print(f"- cases exist ({sum(a['total'] for a in areas.values())} total), "
              f"but {map_path} is missing — the map was never built")
        sys.exit(1)

    text = map_path.read_text(encoding="utf-8", errors="replace")
    fresh, sections = parse_map(text)
    errors, warnings = [], []
    receipt_path = receipt_of(root)
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("map_sha256") != hashlib.sha256(map_path.read_bytes()).hexdigest():
                errors.append("coverage-map receipt does not bind the current map bytes")
            current_facts = {area: {key: value for key, value in fact.items()
                                    if key in {"total", "automated", "max_updated"}}
                             for area, fact in sorted(areas.items())}
            current_hash = hashlib.sha256(json.dumps(
                current_facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if receipt.get("facts_hash") != current_hash or receipt.get("areas") != current_facts:
                errors.append("coverage-map receipt does not bind the current case facts")
        except (OSError, ValueError, AttributeError):
            errors.append("coverage-map receipt is unreadable")

    for area, fact in sorted(areas.items()):
        sec = sections.get(area)
        if sec is None:
            errors.append(f"area '{area}' ({fact['total']} cases) is missing from the map — section '## Area: {area}' not found")
            continue
        if sec["total"] is None:
            errors.append(f"area '{area}': section has no '| Cases created | N |' row — map contract violated")
        elif sec["total"] != fact["total"]:
            errors.append(f"area '{area}': map says {sec['total']} cases, disk has {fact['total']}")
        if sec["automated"] is None:
            errors.append(f"area '{area}': section has no '| Automated | N |' row — map contract violated")
        elif sec["automated"] != fact["automated"]:
            errors.append(f"area '{area}': map says {sec['automated']} automated, frontmatter says {fact['automated']}")
        if fresh and fact["max_updated"] and fact["max_updated"] > fresh:
            errors.append(f"area '{area}': a case was updated {fact['max_updated']}, the map is as of {fresh} — the map lags behind")

    if fresh is None:
        errors.append("the map has no 'As-of date: YYYY-MM-DD' line — map contract violated")

    for area in sections:
        if area not in areas:
            warnings.append(f"area '{area}' is in the map but has no cases on disk (TMS source? otherwise — garbage)")

    if warnings:
        print("WARN:\n- " + "\n- ".join(warnings))
    if errors:
        print(f"REJECT — {len(errors)} problem(s): the coverage map diverged from the facts "
              "(regenerate before finishing the flow):")
        for error in errors:
            print("- " + one_line(error))
        sys.exit(1)
    print(f"OK: coverage-map agrees with {sum(a['total'] for a in areas.values())} cases across {len(areas)} areas")
    sys.exit(0)


if __name__ == "__main__":
    main()
