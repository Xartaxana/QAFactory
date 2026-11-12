"""Build a bounded, revision-aware S1 handoff for S2 and later delta reviews."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from record_schema import validate_record
from role_cli import RefusingParser, command_from_argv, epilog, run_guarded


LIMITS = {"batches_per_repo": 12, "batches_per_stage": 24,
          "active_seconds": 900, "output_tokens": 12000}
LOOKUP_REASONS = {"missing_evidence", "contradiction", "source_changed"}
SOURCE_RELATIONS = {"task", "subject", "technical", "clarification", "parent", "normative", "referenced"}
SOURCE_STATUSES = {"read", "unavailable", "conflicting", "pending", "excluded"}
SEARCH_STATUSES = {"complete", "partial", "unavailable"}
TEST_ORIGINS = {"existing", "added_in_change", "unknown"}
# What the manifest field means, for the refusal that names it; a field with no entry is named without one (a hint, not a
# list of the fields: those come from the schema)
SOURCE_FIELD_HINTS = {"source_sha": "the commit the diff was read at"}


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def bounded_diff(path: Path, max_lines: int = 160) -> dict:
    if not path.is_file():
        return {"path": str(path), "status": "missing", "lines": []}
    lines, total = [], 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            total += 1
            if len(lines) < max_lines and (line.startswith(("diff --git", "+++ ", "--- ", "@@", "+", "-"))):
                lines.append(line.rstrip()[:500])
    return {"path": str(path), "status": "bounded", "total_lines": total,
            "shown_lines": len(lines), "truncated": total > len(lines), "lines": lines}


def _manifest_source_problems(manifest: dict) -> list[str]:
    """The problems of the manifest's `implementations[]` (or its one `implementation`) as the MANIFEST names them.

    The bundle's `source_revisions` is a copy of those records, so the schema refuses them at the bundle's path
    (`$.source_revisions[0]: missing source_sha`) - a path in a file the role never edits (R13, run 12586). The fields come
    from that same schema (`record_schema`, AR-13), never a second list here. Neither field given is ONE problem naming
    `implementations` (E8, the Lead's decision: not the bundle's `$.source_revisions: too short`)."""
    from record_schema import _problems, schemas
    rule = schemas()["ContextBundle"]["properties"]["source_revisions"]["items"]
    if isinstance(manifest.get("implementations"), list) and manifest["implementations"]:
        records = [(f"context-manifest.json implementations[{i}]", item) for i, item in enumerate(manifest["implementations"])]
    elif manifest.get("implementation") is not None and not manifest.get("implementations"):
        records = [("context-manifest.json implementation", manifest["implementation"])]
    elif manifest.get("implementations"):
        return []       # a value that is not a list: the bundle schema's own refusal of `source_revisions` stands
    else:
        # Neither field (S7-3, the Lead's decision E8): the bundle's `$.source_revisions: too short` is a path in a file the
        # role never edits, so the manifest's own field is named, with the fields a record carries (from the schema).
        return ["context-manifest.json implementations: missing - one record per repository the change was read in, each with "
                + ", ".join(rule.get("required", []))]
    problems = []
    for label, item in records:
        if not isinstance(item, dict):
            problems.append(f"{label}: expected object")
            continue
        for key in rule.get("required", []):
            if key not in item:
                problems.append(f"{label}.{key}: missing" + (f" - {SOURCE_FIELD_HINTS[key]}" if key in SOURCE_FIELD_HINTS else ""))
        for key, sub in rule.get("properties", {}).items():
            if key in item:
                problems += [text.replace("$", f"{label}.{key}", 1) for text in _problems(sub, item[key], "$")]
    return problems


def build(manifest: dict, root: Path, previous: dict | None = None,
          max_diff_lines: int = 160) -> dict:
    source_problems = _manifest_source_problems(manifest)
    if source_problems:
        from detector_verdict import compound
        raise ValueError(compound(source_problems))
    implementations = manifest.get("implementations") or []
    if not implementations and isinstance(manifest.get("implementation"), dict):
        implementations = [manifest["implementation"]]
    unresolved = [item if isinstance(item, dict) else {"id": str(item), "reason": "missing_evidence"}
                  for item in (manifest.get("unresolved_facts") or [])]
    known = []
    stale = []
    for item in manifest.get("known_paths") or []:
        entry = dict(item) if isinstance(item, dict) else {"path": str(item)}
        p = Path(entry.get("path") or "")
        p = p if p.is_absolute() else root / p
        if p.is_file():
            actual = digest_file(p)
            entry.update({"path": str(p), "sha256": actual, "status": "current"})
            if entry.get("expected_sha256") and entry["expected_sha256"] != actual:
                entry["status"] = "stale"
                stale.append(str(p))
        else:
            entry.update({"path": str(p), "status": "missing"})
            stale.append(str(p))
        known.append(entry)
    diffs = []
    for impl in implementations:
        raw = impl.get("diff_path") if isinstance(impl, dict) else None
        if raw:
            p = Path(raw)
            diffs.append(bounded_diff(p if p.is_absolute() else root / p, max_diff_lines))
    source_ready = bool(implementations) and all(
        isinstance(i, dict) and i.get("source_sha") and (i.get("repo_id") or i.get("local_path"))
        for i in implementations)
    changed_ready = bool(manifest.get("changed_areas") or diffs)
    coverage = manifest.get("existing_coverage")
    coverage_ready = bool(coverage) or manifest.get("coverage_status") == "not_found"
    constraints_ready = "constraints" in manifest
    complete = source_ready and changed_ready and coverage_ready and constraints_ready and not unresolved and not stale
    previous_facts = (previous or {}).get("facts") or []
    raw_facts = list(manifest.get("facts") or manifest.get("observables") or [])
    facts = []
    for index, item in enumerate(raw_facts, 1):
        fact = dict(item) if isinstance(item, dict) else {"id": f"fact-{index}", "value": str(item)}
        fact.setdefault("id", fact.get("requirement") or f"fact-{index}")
        fact.setdefault("source_refs", [fact["path"]] if fact.get("path") else ["context-manifest"])
        facts.append(fact)
    previous_ids = {str(f.get("id") or f.get("requirement") or "") for f in previous_facts if isinstance(f, dict)}
    current_ids = {str(f.get("id") or f.get("requirement") or "") for f in facts if isinstance(f, dict)}
    v2_discovery = any(key in manifest for key in
                       ("requirement_sources", "coverage_search", "existing_test_candidates"))
    result = {
        "schema_version": 2 if v2_discovery else 1,
        "task_id": manifest.get("task_id") or manifest.get("ticket"),
        "source_revisions": implementations,
        "facts": facts,
        "changed_files": manifest.get("changed_files") or [],
        "diff_summaries": diffs,
        "existing_case_test_candidates": manifest.get("existing_coverage") or manifest.get("existing_tests") or [],
        "constraints": manifest.get("constraints") or [],
        "unresolved_facts": unresolved,
        "known_paths": known,
        "stale_paths": stale,
        "grounding_complete": complete,
        "grounding_gaps": [name for name, ok in (("source_revision", source_ready),
                            ("changed_areas", changed_ready), ("existing_coverage", coverage_ready),
                            ("constraints", constraints_ready)) if not ok] +
                           (["unresolved_facts"] if unresolved else []) + (["stale_paths"] if stale else []),
        "delta": {"added_or_changed_ids": sorted(key for key in current_ids if
                      next((f for f in facts if str(f.get("id")) == key), None) !=
                      next((f for f in previous_facts if str(f.get("id")) == key), None)),
                  "removed_ids": sorted(previous_ids - current_ids)},
        "limits": dict(LIMITS),
    }
    if v2_discovery:
        result.update({
            "requirement_sources": manifest.get("requirement_sources") or [],
            "coverage_search": manifest.get("coverage_search") or [],
            "existing_test_candidates": manifest.get("existing_test_candidates") or [],
        })
    if v2_discovery:
        result.pop("existing_case_test_candidates", None)
        from candidate_evidence import assess_candidate
        repo_roots = {str(i.get("repo_id")): i.get("local_path") for i in implementations if isinstance(i, dict)}
        assessed = []
        for candidate in result["existing_test_candidates"]:
            candidate = dict(candidate)
            repo_root = repo_roots.get(str(candidate.get("repo")))
            candidate["candidate_evidence"] = (assess_candidate(candidate, repo_root) if repo_root else
                {"valid": False, "executable": False, "assertion_status": "unknown",
                 "gaps": ["repository root unavailable for assertion verification"]})
            candidate["provenance"] = {"repo": candidate.get("repo"), "revision": candidate.get("revision"),
                                       "collection_ref": candidate.get("collection_ref"),
                                       "source": "context-manifest"}
            assessment = candidate["candidate_evidence"]
            if assessment.get("test_file"):
                assessment["file_sha256"] = digest_file(Path(assessment["test_file"]))
            assessed.append(candidate)
        result["existing_test_candidates"] = assessed
    inventory_path = root / "work" / "source-inventory.json"
    if inventory_path.is_file():
        from source_inventory import load_inventory, validate_inventory, completeness
        inventory = load_inventory(inventory_path)
        errors = validate_inventory(inventory)
        if errors:
            raise ValueError("source inventory invalid: " + "; ".join(errors))
        summary = completeness(inventory)
        result["source_inventory_ref"] = {"path": "work/source-inventory.json",
                                           "sha256": digest_file(inventory_path)}
        result["source_completeness"] = summary
        if not summary["complete"]:
            result["grounding_complete"] = False
            result["grounding_gaps"].append("source_inventory_incomplete")
        # Canonical source facts live in the inventory, not a second editable list.
        result["requirement_sources"] = [{"source_id": item["source_id"], "relation": item["relation"],
            "ref": item["canonical_ref"], "revision": item.get("revision") or "unknown",
            "status": item["status"], "evidence_ref": ("work/" + item["snapshot_ref"]) if item.get("snapshot_ref") else "work/source-inventory.json",
            "relevance": item.get("relevance"), "materials": item.get("materials", {})}
            for item in inventory.get("sources", [])]
    result["fact_pages"] = [{"offset": offset, "count": min(500, len(facts) - offset)}
                            for offset in range(0, len(facts), 500)]
    validate_bundle(result)
    return result


def validate_bundle(bundle: dict) -> dict:
    validate_record("ContextBundle", bundle)
    if any(len(item.get("lines", [])) > 160 for item in bundle["diff_summaries"]):
        raise ValueError("ContextBundle diff summary exceeds 160 lines")
    expected_complete = not bundle["grounding_gaps"]
    if bundle["grounding_complete"] != expected_complete:
        raise ValueError("ContextBundle grounding_complete disagrees with computed gaps")
    if bundle.get("schema_version") == 2:
        _validate_v2_discovery(bundle)
    return bundle


# The ONE carrier of the v2 discovery fields (AR-13): the fields each record owes, in the order a refusal names them, and the
# rule of each. A rule is "string" (non-empty), "list" (of non-empty strings) or a closed set; a field with no rule
# (`selector`) is only required. The scout's ahead card names these fields before the work (test_context_bundle pins it).
V2_REQUIRED = {
    "requirement_sources": ("source_id", "relation", "ref", "revision", "status", "evidence_ref"),
    "coverage_search": ("repo", "revision", "changed_area", "searched_paths", "status", "reason"),
    "existing_test_candidates": ("candidate_id", "repo", "revision", "path", "selector", "parameter_ids", "level",
                                 "assertion_refs", "candidate_requirement_refs", "origin", "result_candidate_refs"),
}
V2_RULES = {
    "requirement_sources": {"source_id": "string", "relation": SOURCE_RELATIONS, "ref": "string", "revision": "string",
                            "status": SOURCE_STATUSES, "evidence_ref": "string"},
    "coverage_search": {"repo": "string", "revision": "string", "changed_area": "string", "searched_paths": "list",
                        "status": SEARCH_STATUSES, "reason": "string"},
    "existing_test_candidates": {"candidate_id": "string", "repo": "string", "revision": "string", "path": "string",
                                 "level": "string", "parameter_ids": "list", "assertion_refs": "list",
                                 "candidate_requirement_refs": "list", "origin": TEST_ORIGINS,
                                 "result_candidate_refs": "list"},
}
V2_UNIQUE = {"requirement_sources": "source_id", "existing_test_candidates": "candidate_id"}
NOT_FOUND_HINT = " - nothing found is the manifest's top-level coverage_status: not_found"


def _closed(allowed: set) -> str:
    """A closed list as a refusal prints it: the same order every time, nothing but its own words (FR-1)."""
    from detector_verdict import one_of
    return one_of(allowed)


def _one_of(value: object, allowed: set) -> bool:
    """A string inside the closed list; any other value (a list, a number) is refused, not raised on."""
    return isinstance(value, str) and value in allowed


def _validate_v2_discovery(bundle: dict) -> None:
    """Strictly validate optional v2 discovery records without changing v1 compatibility.

    Every problem of every section is collected and raised ONCE (a role fixes the whole record set in one turn); a section
    that is missing or not a list is one problem, and the other sections are still checked."""
    from detector_verdict import compound
    problems = [f"ContextBundle v2 requires {key} array" for key in V2_REQUIRED
                if key not in bundle or not isinstance(bundle[key], list)]
    problems += v2_discovery_problems(bundle)
    if problems:
        raise ValueError(compound(problems))


def _rule_problem(loc: str, field: str, value: object, rule, section: str) -> str | None:
    """The problem one present field has under its rule, or None. `loc` is `section[i]`."""
    if rule == "string":
        return None if isinstance(value, str) and value else f"{loc}.{field} must be a non-empty string"
    if rule == "list":
        ok = isinstance(value, list) and all(isinstance(item, str) and item for item in value)
        return None if ok else f"{loc}.{field} must be a list of non-empty strings"
    if _one_of(value, rule):
        return None
    hint = NOT_FOUND_HINT if (section, field, value) == ("coverage_search", "status", "not_found") else ""
    return f"{loc}.{field} must be one of {_closed(rule)}{hint}"


def v2_discovery_problems(record: dict, sections: tuple = tuple(V2_REQUIRED)) -> list[str]:
    """Every problem of the named v2 discovery sections of `record`, in record order, each with its position.

    Per section in `sections` order, per record in list order: not an object -> `<section>[i] must be an object` (no field
    check on it); else ONE `missing required fields` line naming every absent field in V2_REQUIRED order, then the rule of
    each present field in that order, then the duplicate check (only on an id that passed its string rule; every later
    duplicate names the FIRST index holding it). A section that is absent or not a list is skipped: the caller says so
    (bundle: `requires <key> array`; manifest hook: `must be an array or absent`). Returns a list; never raises."""
    problems = []
    for section in sections:
        items = record.get(section)
        if not isinstance(items, list):
            continue
        first_seen = {}
        for index, item in enumerate(items):
            loc = f"{section}[{index}]"
            if not isinstance(item, dict):
                problems.append(f"{loc} must be an object")
                continue
            problems += _record_problems(section, index, item, first_seen)
    return problems


def _record_problems(section: str, index: int, item: dict, first_seen: dict) -> list[str]:
    """The problems of ONE object record of `section` (the per-record half of `v2_discovery_problems`); `first_seen` maps an
    id to the first index holding it and is filled here."""
    loc = f"{section}[{index}]"
    problems = []
    missing = [field for field in V2_REQUIRED[section] if field not in item]
    if missing:
        problems.append(f"{loc}: missing required fields: {', '.join(missing)}")
    for field in V2_REQUIRED[section]:
        rule = V2_RULES[section].get(field)
        if field in item and rule is not None:
            problem = _rule_problem(loc, field, item[field], rule, section)
            if problem:
                problems.append(problem)
    key = V2_UNIQUE.get(section)
    if key and isinstance(item.get(key), str) and item[key]:
        if item[key] in first_seen:
            problems.append(f"{loc}.{key} '{item[key]}' duplicates {section}[{first_seen[item[key]]}]")
        else:
            first_seen[item[key]] = index
    return problems


def validate_lookup(reason: str, fact_id: str) -> None:
    if reason not in LOOKUP_REASONS or not fact_id:
        raise ValueError("post-grounding lookup requires lookup_reason and fact/requirement ID")


# --- the line view (SC1-9 A2) -------------------------------------------------------------------------------
# A role that reads the bundle pays for its JSON shape (indent, quotes, 160 diff lines per file); one line per item is
# what Grep -n and a partial Read can use. The JSON stays the record: the view is generated from it, names every key it
# does not print (AR-21), and carries the sha256 of the JSON bytes it describes, so a reader can tell a stale view.

VIEW_SUFFIX = ".lines.md"
VIEW_HEADER_KEYS = ("task_id", "schema_version", "grounding_complete", "grounding_gaps")
# (view heading, bundle key, what the heading says after its name); a section line is one item
VIEW_SECTIONS = (
    ("facts", "facts", " (id | path:line | source | requirement | value | note)"),
    ("requirement_sources", "requirement_sources",
     " (source_id | relation | ref | revision | status | evidence_ref | relevance | materials: kind=count, ...)"),
    ("source_revisions", "source_revisions", " (repo_id | source_sha | local_path | diff_path)"),
    ("changed_files", "changed_files", ""),
    ("diffs", "diff_summaries", " (path | status | total_lines | truncated) - the changed lines are not repeated here: "
                                "they are in the diff file at that path"),
    ("existing_test_candidates", "existing_test_candidates",
     " (candidate_id | repo | path | selector | level | origin | assertion_refs)"),
    ("existing_case_test_candidates", "existing_case_test_candidates", " (one item per line, its JSON compact)"),
    ("coverage_search", "coverage_search", " (repo | changed_area | status | searched_paths | reason)"),
    ("constraints", "constraints", ""),
    ("unresolved_facts", "unresolved_facts", " (id | reason)"),
    ("known_paths", "known_paths", " (path | status)"),
    ("stale_paths", "stale_paths", ""),
    ("delta", "delta", " (added_or_changed ids | removed ids)"),
    ("limits", "limits", " (key=value, ...)"),
)

# The keys of one ITEM each section prints (by bundle key): the one owner of "what a line shows". `_section_lines` prints
# these columns and `_unseen_item_keys` names every other key an item carries, computed from the bundle itself - so a
# field added to the record tomorrow is named in the view's "not shown here" line with no change here (AR-21, F3).
ITEM_COLUMNS = {
    "facts": ("id", "path", "line", "source", "requirement", "value", "note"),
    "requirement_sources": ("source_id", "relation", "ref", "revision", "status", "evidence_ref", "relevance"),
    "source_revisions": ("repo_id", "source_sha", "local_path", "diff_path"),
    "diff_summaries": ("path", "status", "total_lines", "truncated"),
    "existing_test_candidates": ("candidate_id", "repo", "path", "selector", "level", "origin", "assertion_refs"),
    "coverage_search": ("repo", "changed_area", "status", "searched_paths", "reason"),
    "unresolved_facts": ("id", "reason"),
    "known_paths": ("path", "status"),
}
# Printed, but only in part: the key is shown as counts (`kind=count`); its bodies are the fixed text below.
ITEM_SHOWN_IN_PART = {"requirement_sources": ("materials",)}
VIEW_NOT_SHOWN = "also not shown: requirement_sources material bodies; the diff lines"
_HASH_LINE = re.compile(r"json_sha256: ([0-9A-Fa-f]{64})(?![0-9A-Fa-f])")
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def view_path(output: Path) -> Path:
    """`<output stem>.lines.md` next to the JSON: the one place the view lives (AR-14)."""
    output = Path(output)
    return output.with_name(output.stem + VIEW_SUFFIX)


def _show_path(value, project: Path | None, pointer: str):
    """A PATH field as the view prints it (AR-4: no machine fact in a file the factory writes).

    Not a string or empty, or not absolute: as is. Absolute and the project known: relative to it, forward slashes (a
    neighbour is `../testproject1/...`). Absolute and no project, another drive, or a spelling this host cannot relativise:
    a pointer to the JSON field, which keeps the path. The allowed error is a pointer; the forbidden one is an absolute
    path in the view. Only the path FIELDS go through here: a value that happens to start with `/` is a fact, not a path."""
    if not isinstance(value, str) or not value:
        return value
    drive = _DRIVE.match(value) is not None
    if not (os.path.isabs(value) or drive or value.startswith(("/", "\\"))):
        return value
    pointed = f"(absolute path: see the JSON at {pointer})"
    if project is None:
        return pointed
    if os.name == "nt":
        foreign = not os.path.splitdrive(value)[0]          # `/x` with no drive: which drive is a guess
    else:
        foreign = drive or value.startswith("\\")           # `C:\x` on a host with no drives
    if foreign:
        return pointed
    try:
        return os.path.relpath(value, project).replace(os.sep, "/")
    except ValueError:                                       # another drive
        return pointed


def _esc(text: str) -> str:
    """One cell: `\\` first, then the separator, a line break as the two characters `\\n`, a CR dropped."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", "\\n")


def _cell(value) -> str:
    """Any JSON value as one escaped cell: a string as is, a list of strings joined, the rest compact JSON; null is empty."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        text = ", ".join(value)
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return _esc(text)


def _row(item, keys: tuple, project: Path | None, pointer: str, path_keys: tuple = ()) -> str:
    """One item as one line; an item that is not an object is one cell of compact JSON (nothing is dropped)."""
    if not isinstance(item, dict):
        return _cell(item)
    cells = []
    for key in keys:
        value = item.get(key)
        if key in path_keys:
            value = _show_path(value, project, f"{pointer}/{key}")
        cells.append(_cell(value))
    return " | ".join(cells)


def _materials(value) -> str:
    """`kind=count` per material kind; a count the record does not hold is `unknown` (FR-41), a material that is not an
    object is printed as its compact JSON, never dropped. The bodies (items, statuses) stay in the JSON."""
    if not isinstance(value, dict):
        return _cell(value)
    parts = []
    for kind, body in value.items():
        if isinstance(body, dict):
            count = body.get("count")
            parts.append(f"{kind}={count if isinstance(count, int) and not isinstance(count, bool) else 'unknown'}")
        else:
            parts.append(f"{kind}={json.dumps(body, ensure_ascii=False, separators=(',', ':'))}")
    return _esc(", ".join(parts))


def _fact_line(fact, project: Path | None, pointer: str) -> str:
    if not isinstance(fact, dict):
        return _cell(fact)
    place = _show_path(fact.get("path"), project, f"{pointer}/path")
    line = fact.get("line")
    place = (_cell(place) + (":" + _cell(line) if line not in (None, "") else ""))
    return " | ".join([_cell(fact.get("id")), place, _cell(fact.get("source")), _cell(fact.get("requirement")),
                       _cell(fact.get("value")), _cell(fact.get("note"))])


def _section_lines(key: str, items, project: Path | None) -> list:
    """The lines of one section; the caller has already settled "absent" and "empty"."""
    base = f"/{key}"
    if key == "facts":
        return [_fact_line(item, project, f"{base}/{i}") for i, item in enumerate(items)]
    if key == "requirement_sources":
        rows = []
        for item in items:
            row = _row(item, ITEM_COLUMNS[key], None, "")
            rows.append(row + " | " + (_materials(item.get("materials")) if isinstance(item, dict) else ""))
        return rows
    if key == "source_revisions":
        return [_row(item, ITEM_COLUMNS[key], project, f"{base}/{i}", ("local_path", "diff_path"))
                for i, item in enumerate(items)]
    if key == "diff_summaries":
        return [_row(item, ITEM_COLUMNS[key], project, f"{base}/{i}", ("path",)) for i, item in enumerate(items)]
    if key == "existing_test_candidates":
        return [_row(item, ITEM_COLUMNS[key], None, "") for item in items]
    if key == "existing_case_test_candidates":
        return [_esc(json.dumps(item, ensure_ascii=False, separators=(",", ":"))) for item in items]
    if key == "coverage_search":
        return [_row(item, ITEM_COLUMNS[key], None, "") for item in items]
    if key == "unresolved_facts":
        return [_row(item, ITEM_COLUMNS[key], None, "") for item in items]
    if key == "known_paths":
        return [_row(item, ITEM_COLUMNS[key], project, f"{base}/{i}", ("path",)) for i, item in enumerate(items)]
    if key in ("changed_files", "stale_paths"):
        return [_cell(_show_path(item, project, f"{base}/{i}")) for i, item in enumerate(items)]
    return [_cell(item) for item in items]                   # constraints: a string, or an object as compact JSON


def _unseen_item_keys(bundle: dict) -> list:
    """`<section>: k1, k2` for every section whose items carry a key the view's columns do not print (sorted; none when
    every item is fully shown). Computed from the bundle, like the top-level `hidden` list - never a fixed list."""
    out = []
    for key, columns in ITEM_COLUMNS.items():
        items = bundle.get(key)
        if not isinstance(items, list):
            continue
        extra = ({name for item in items if isinstance(item, dict) for name in item}
                 - set(columns) - set(ITEM_SHOWN_IN_PART.get(key, ())))
        if extra:
            out.append(f"{key}: {', '.join(sorted(extra))}")
    return out


def render_lines(bundle: dict, json_sha256: str, project: Path | None, json_name: str) -> str:
    """The line view of a bundle: the whole text, ending in a newline. Pure: the caller writes it."""
    gaps = bundle.get("grounding_gaps")
    shown = {name for _heading, name, _cols in VIEW_SECTIONS} | set(VIEW_HEADER_KEYS)
    hidden = sorted(set(bundle) - shown)
    unseen = _unseen_item_keys(bundle)
    complete = bundle.get("grounding_complete")
    out = [f"# context-bundle view - generated by context_bundle.py from {json_name}; the JSON is the record: read it "
           "for any field not shown here",
           " | ".join([f"json_sha256: {json_sha256}", f"task: {_cell(bundle.get('task_id'))}",
                       f"schema: {_cell(bundle.get('schema_version'))}",
                       f"grounding_complete: {json.dumps(complete) if isinstance(complete, bool) else _cell(complete)}",
                       "gaps: " + (_cell(gaps) if gaps else "none")]),
           f"not shown here (read them in the JSON): {', '.join(hidden) if hidden else 'none'}; "
           + (f"per item: {'; '.join(unseen)}; " if unseen else "") + VIEW_NOT_SHOWN]
    for heading, key, columns in VIEW_SECTIONS:
        out.append(f"## {heading}{columns}")
        if key not in bundle:
            out.append("(not in this bundle)")
            continue
        items = bundle[key]
        if key == "delta":
            delta = items if isinstance(items, dict) else {}
            sides = [", ".join(str(x) for x in (delta.get(name) or [])) for name in ("added_or_changed_ids", "removed_ids")]
            out.append(" | ".join(_esc(side) if side else "(none)" for side in sides))
        elif key == "limits":
            out.append(_esc(", ".join(f"{k}={json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                                      for k, v in items.items())) if isinstance(items, dict) and items else "(none)")
        elif not items:
            out.append("(none)")
        else:
            out.extend(_section_lines(key, items if isinstance(items, list) else [items], project))
    return "\n".join(out) + "\n"


def view_status(json_path: Path) -> str:
    """`current` / `stale` / `absent`: does the view next to this JSON describe the JSON's bytes as they are now.

    The ONE reader of the view (AR-13). It errs only toward `stale` / `absent`, where the reader is sent to the JSON, never
    toward `current`: no JSON, no view file, a view that is not a regular readable file, empty, or has no `json_sha256`
    on its second line is `absent`; a sha that is not the JSON's own (another file, a changed byte, upper case) is `stale`.
    Never raises."""
    try:
        json_path = Path(json_path)
        if not json_path.is_file():
            return "absent"
        view = view_path(json_path)
        if not view.is_file():
            return "absent"
        with view.open("rb") as stream:
            stream.readline()
            second = stream.readline(65536).decode("utf-8", errors="replace")
        found = _HASH_LINE.match(second)
        if not found:
            return "absent"
        return "current" if found.group(1) == digest_file(json_path) else "stale"
    except Exception:           # the status is advice for a brief, and any doubt is "go to the JSON"
        return "absent"


def write_view(out: Path, bundle: dict, errors: list | None = None) -> str | None:
    """Write the line view next to the JSON `out` (already written); return its path from the project root, or None.

    The sha is of the file's bytes AFTER the write: `write_text` turns `\\n` into CRLF on Windows, and a hash of the text
    in memory would make the view stale for ever there. The view is written to a temporary file in the same folder and
    swapped in, so an old view is replaced whole, never appended to, and never half written. A failure returns None
    (the reason goes to `errors` when a list is given): the JSON is complete without the view."""
    tmp = None
    try:
        out = Path(out)
        sha = digest_file(out)
        try:
            from runtime_paths import nearest_project
            project = nearest_project(out)
        except Exception:       # no project found is a legal state, the view then points at the JSON
            project = None
        target = view_path(out)
        tmp = target.with_name(target.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(render_lines(bundle, sha, project, out.name))
        os.replace(tmp, target)
        tmp = None
        if project is None:
            return target.name
        return os.path.relpath(target.resolve(), project).replace(os.sep, "/")
    except Exception as exc:    # the view is an aid, the JSON is the record
        if errors is not None:
            errors.append(f"{type(exc).__name__}: {exc}")
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return None


def main() -> None:
    ap = RefusingParser(command=command_from_argv("context_bundle.py"), description=__doc__,
                        epilog=epilog("context_bundle.py"), formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--manifest")
    ap.add_argument("--output")
    ap.add_argument("--validate", help="validate an existing context-bundle.json")
    ap.add_argument("--previous")
    ap.add_argument("--page", type=int, help="Read a zero-based 500-fact page with --validate; full stored bundle is retained")
    ap.add_argument("--root", default=".")
    ap.add_argument("--max-diff-lines", type=int, default=160)
    args = ap.parse_args()
    if args.validate:
        bundle = validate_bundle(json.loads(Path(args.validate).read_text(encoding="utf-8")))
        if args.page is not None:
            if args.page < 0: ap.error("page must be nonnegative")
            print(json.dumps({"facts": bundle["facts"][args.page*500:(args.page+1)*500],
                              "total": len(bundle["facts"]), "page": args.page}))
        else:
            # `view` is advice for the brief that names the bundle (current / stale / absent); nothing is written here
            print(json.dumps({"valid": True, "path": args.validate, "view": view_status(Path(args.validate))}))
        return
    if not args.manifest or not args.output:
        # the ready command carries what the call gave; the other path is a placeholder that says where it comes from
        ap.error("--manifest and --output are required unless --validate is used. Ready: context_bundle.py --manifest "
                 f"{args.manifest or '<the story work/context-manifest.json you wrote>'} --output "
                 f"{args.output or '<the story work/context-bundle.json>'}")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    result = build(manifest, Path(args.root).resolve(), previous, max(1, args.max_diff_lines))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    why = []
    view = write_view(out, result, why)
    if view is None:
        # ASCII only: this script configures no console stream of its own (test_console_encoding)
        print((f"context_bundle.py: the line view was not written ({why[0] if why else 'unknown reason'}); the JSON at {out} "
               "is complete - read it with Grep -n").encode("ascii", "backslashreplace").decode("ascii"), file=sys.stderr)
    print(json.dumps({"grounding_complete": result["grounding_complete"],
                      "gaps": result["grounding_gaps"], "output": str(out), "view": view}))


if __name__ == "__main__":
    raise SystemExit(run_guarded(command_from_argv("context_bundle.py"), main))
