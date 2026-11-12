"""bug_neighbours.py - the failures, observations, rows and drafts of a story that share a requirement, case, test file, code line or seen value.

A HINT for the failure analyst (S7) and the scribe that accepts its merges, never a verdict (spec t-2187 section 9, node N6). Code prints the
EVIDENCE: groups of two or more units that carry one equal value, and the value. It never says "merge", "same bug" or "root cause": whether
two units are one cause is the analyst's judgment, accepted by the scribe and the person at gate B (AR-29). Reads only, writes no file
(FR-45, AR-14): the table is printed, never stored.

  python -B bug_neighbours.py --task-root <task root>          the table as text lines (what the analyst reads)
  python -B bug_neighbours.py --task-root <task root> --json   the same table as ONE JSON line

The keys: `requirement` (the R ids of a case's case file, of a draft), `case` (the case a failure, row or draft names), `test_file` (the file of
the manifest test that covers the failure), `code_line` (`bug_records.normalize_location` of a draft's `defect_location` and of a
`mechanism.basis` code line: the one normaliser `same_location` uses), `seen` (the words an observation or a surprise line records, EQUAL after
whitespace squash and casefold: equality, never meaning, FR-12). A "same element" key does not exist in this version (no structured element
field is recorded). A row and a draft that name a failure are ONE unit with it, so a failure never "shares" a value with its own row.
A source that cannot be read is named in `unreadable`; the table is then not whole and says so (FR-41, FR-59), it is never read as "none".
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import hooklib  # noqa: E402

SCRIPT = "bug_neighbours.py"
KEYS = ("requirement", "case", "test_file", "code_line", "seen")
KIND_RANK = {"failure": 0, "observation": 1, "surprise": 2, "row": 3, "draft": 4}
NO_GROUP = "No two failures share a requirement, case, test file, code line or seen value."
NOTHING = "Nothing found: no failure, triage row or draft to compare."


def _squash(value) -> str:
    return " ".join(str(value or "").split())


def _texts(value) -> list:
    """The non-empty stripped strings of a string or a list of them, in order, without repeats."""
    out: list = []
    for item in value if isinstance(value, list) else [value]:
        text = item.strip() if isinstance(item, str) else ""
        if text and text not in out:
            out.append(text)
    return out


def _file(value) -> str:
    return str(value or "").replace("\\", "/").strip() if isinstance(value, str) else ""


def _read(task: Path, name: str) -> tuple:
    """`(object, why)` of `work/<name>`: `(None, "")` when the file is absent, `(None, why)` when it cannot be read whole."""
    try:
        path = C.artifact(task, name)
    except Exception as exc:  # noqa: BLE001 - any unreadable carrier is the same state
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    if not path.is_file():
        return None, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    return (data, "") if isinstance(data, dict) else (None, "not a JSON object")


def _result_rows(report: dict) -> list:
    rows = report.get("current_results")
    if not isinstance(rows, list):
        rows = list(C.current_instance_results(report).values())
    return [row for row in rows if isinstance(row, dict)]


def _tests(manifest) -> list:
    """`[{"ids", "cases", "file"}]` of the manifest's `tests[]` (a test names its cases in `covers`, an old row in `case`)."""
    items = manifest.get("tests") if isinstance(manifest, dict) else None
    out = []
    for test in items if isinstance(items, list) else []:
        if isinstance(test, dict):
            out.append({"ids": _texts([test.get("instance_id"), test.get("test_id")]),
                        "cases": _texts([*_texts(test.get("covers")), *_texts(test.get("case"))]), "file": _file(test.get("file"))})
    return out


def _location_of_basis(draft) -> list:
    """The `file:line` places of the `code_line` entries of `mechanism.basis` (`normalize_location`; an entry of another shape is skipped)."""
    mechanism = draft.get("mechanism") if isinstance(draft, dict) else None
    basis = mechanism.get("basis") if isinstance(mechanism, dict) else None
    out = []
    for entry in basis if isinstance(basis, list) else []:
        if isinstance(entry, dict) and entry.get("kind") == "code_line":
            place = BR.normalize_location(f"{entry.get('path') or ''}:{entry.get('line') or ''}")
            if place and place not in out:
                out.append(place)
    return out


def _read_sources(task: Path, unreadable: list, notes: list) -> tuple:
    """`(report, manifest, triage)`; what cannot be read goes to `unreadable`, what is merely absent to `notes`."""
    report, why = _read(task, "run-report.json")
    if why:
        unreadable.append(["work/run-report.json", why])
    manifest, why = _read(task, "automation-manifest.json")
    if why:
        unreadable.append(["work/automation-manifest.json", why])
    triage, why = _read(task, "triage.json")
    if why:
        unreadable.append(["work/triage.json", why])
    for name, data in (("run-report.json", report), ("triage.json", triage)):
        if data is None and not any(item[0] == f"work/{name}" for item in unreadable):
            notes.append(f"no work/{name}")
    return report, manifest, triage


def _requirements_of(index, cases) -> list:
    found: list = []
    for case in cases:
        try:
            meta = index.get(case) if index is not None else None
        except Exception:  # noqa: BLE001 - a case the index cannot name gives no requirement
            meta = None
        found += [r for r in (meta or {}).get("requirements") or [] if r not in found]
    return found


def _member(kind, ident, unit, cases, values) -> dict:
    return {"kind": kind, "id": ident, "case": cases[0] if cases else "", "unit": unit, "values": values}


def _failure_facts(kind, name, info, report, rows, tests) -> tuple:
    """`(what, cases, files, seen)` of one failure of the run report: the kind it shows as, its cases, its test files, its seen words."""
    names = list(info.get("names") or [name])
    files: list = []
    seen = ""
    if kind == "observation":
        parts = C.target_parts(name)
        cases = [parts[0]] if parts else []
        what = "surprise" if parts and parts[1] != "obs" else "observation"
        if parts and parts[1] in ("obs", "sur"):
            attempts = sorted(a for a in info.get("attempts") or [] if a)
            entry = C.observation_entry(report, name, attempts[0] if attempts else "")
            seen = _squash(entry.get("seen")).casefold() if isinstance(entry, dict) else ""
        return what, cases, files, seen
    if kind == "manual":
        return "failure", [name], files, seen
    cases = []
    for row in rows:
        if any(C.same_id(_squash(row.get(k)), n) for k in ("instance_id", "test_instance_id", "test_id", "test") for n in names):
            cases += [c for c in _texts(row.get("case")) if c not in cases]
    for test in tests:
        if any(C.same_id(i, n) for i in test["ids"] for n in names):
            cases += [c for c in test["cases"] if c not in cases]
            if test["file"] and test["file"] not in files:
                files.append(test["file"])
    return "failure", cases, files, seen


def _failure_members(report, manifest, index, unreadable: list) -> tuple:
    """`(members, units)` of the failures of the run report; a report that cannot be walked is named in `unreadable`."""
    tests = _tests(manifest)
    try:
        failures = C.triage_failures(report)[0] if report is not None else {}
        rows = _result_rows(report) if report is not None else []
    except Exception as exc:  # noqa: BLE001
        failures, rows = {}, []
        unreadable.append(["work/run-report.json", f"{type(exc).__name__}: {str(exc)[:120]}"])
    members: list = []
    units: list = []        # the failures: {"unit", "names", "cases", "files"}
    for (kind, name), info in failures.items():
        what, cases, files, seen = _failure_facts(kind, name, info, report, rows, tests)
        unit = f"f:{kind}:{name}"
        units.append({"unit": unit, "names": list(info.get("names") or [name]), "cases": cases, "files": files})
        members.append(_member(what, name, unit, cases, {"requirement": _requirements_of(index, cases), "case": cases, "test_file": files,
                                                         "seen": [seen] if seen else []}))
    return members, units


def _bound(units: list, names):
    return next((u for u in units if any(C.same_id(n, f) for n in names for f in u["names"])), None)


def _row_members(triage, units: list, index) -> list:
    members: list = []
    for row in C.triage_rows(triage) if triage is not None else []:
        names = C.row_names(row)
        if not names:
            continue
        found = _bound(units, names)
        cases = found["cases"] if found else _texts(row.get("case"))
        members.append(_member("row", names[0], found["unit"] if found else f"row:{names[0]}", cases,
                               {"requirement": _requirements_of(index, cases), "case": cases, "test_file": found["files"] if found else []}))
    return members


def _draft_members(task: Path, units: list, unreadable: list) -> list:
    members: list = []
    paths, bad = BR.draft_listing(task)
    unreadable += [[item.split(":")[0], item] for item in bad]
    for path in paths:
        rel = path.relative_to(task).as_posix() if path.is_relative_to(task) else path.name
        try:
            draft = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            unreadable.append([rel, f"{type(exc).__name__}: {str(exc)[:120]}"])
            continue
        if not isinstance(draft, dict):
            unreadable.append([rel, "ValueError: not a JSON object"])
            continue
        cases = BR.draft_cases(draft)
        found = _bound(units, [BR.draft_triage_key(draft)[0]])
        places = [p for p in [BR.draft_location(draft), *_location_of_basis(draft)] if p]
        members.append(_member("draft", path.name, found["unit"] if found else f"draft:{path.name}", cases,
                               {"requirement": BR.draft_requirements(draft), "case": cases, "code_line": places}))
    return members


def _groups_of(members: list) -> list:
    """The groups: two or more members of two or more units that carry one equal value, in stable order."""
    buckets: dict = {}
    for one in members:
        for key in KEYS:
            for value in one["values"].get(key) or []:
                if value:
                    got = buckets.setdefault((key, value), {})
                    got.setdefault((one["kind"], one["id"]), one)
    groups = []
    for (key, value), got in sorted(buckets.items(), key=lambda item: (KEYS.index(item[0][0]), item[0][1])):
        if len(got) >= 2 and len({one["unit"] for one in got.values()}) >= 2:
            ordered = sorted(got.values(), key=lambda one: (KIND_RANK[one["kind"]], one["id"]))
            groups.append({"key": key, "value": value, "members": [{"kind": o["kind"], "id": o["id"], "case": o["case"]} for o in ordered]})
    return groups


def neighbours(task_root) -> dict:
    """`{"groups": [{"key", "value", "members": [{"kind", "id", "case"}]}], "notes": [...], "unreadable": [[file, why]]}`.

    A group exists only with two or more members of two or more UNITS (a failure, its triage row and its draft are one unit). Pure: reads,
    writes nothing, never refuses. Order is stable: keys in `KEYS` order, values sorted, members by kind then id."""
    task = Path(task_root)
    unreadable: list = []
    notes: list = []
    report, manifest, triage = _read_sources(task, unreadable, notes)
    try:
        index = C.case_index(task)
    except Exception as exc:  # noqa: BLE001
        index = None
        unreadable.append(["the case files", f"{type(exc).__name__}: {str(exc)[:120]}"])
    members, units = _failure_members(report, manifest, index, unreadable)
    members += _row_members(triage, units, index)
    members += _draft_members(task, units, unreadable)
    if not members and not unreadable:
        notes.append(NOTHING)
    return {"groups": _groups_of(members), "notes": notes, "unreadable": unreadable}


def group_line(group: dict) -> str:
    """One line per group: `group <key> = <value>: <kind> <id> (case <case>); ...` (the case is left out inside a `case` group)."""
    shown = []
    for one in group["members"]:
        extra = f" (case {one['case']})" if one["case"] and group["key"] != "case" else ""
        shown.append(f"{one['kind']} {one['id']}{extra}")
    return f"group {group['key']} = {group['value']}: " + "; ".join(shown)


def unreadable_line(item) -> str:
    return f"unreadable: {item[0]} ({item[1]}); the table is not computed whole"


def head_line(found: dict) -> str:
    count = len(found["groups"])
    return (f"Neighbours: {count} group{'s' if count != 1 else ''} of failures, observations, rows or drafts share one value "
            "(a hint, never a verdict: whether they are one cause is your judgment)")


def lines(found: dict, limit=None) -> list:
    """The text of the table. `limit` (the brief's `brief_neighbours_max`) cuts the group lines and adds ONE line with the count left out."""
    groups = found["groups"]
    out: list = []
    if groups:
        shown = groups if limit is None else groups[:limit]
        out = [head_line(found)] + [group_line(g) for g in shown]
        if len(shown) < len(groups):
            out.append(f"[and {len(groups) - len(shown)} more: bug_neighbours.py --task-root <task root>]")
    out += [unreadable_line(item) for item in found["unreadable"]]
    if not groups:
        if found["unreadable"]:
            out.append("No group was found in what could be read.")
        else:
            out.append(NOTHING if NOTHING in found["notes"] else NO_GROUP)
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=SCRIPT, description=__doc__.split("\n\n")[0])
    parser.add_argument("--task-root", required=True, help="the story folder (holds pipeline.json and work/)")
    parser.add_argument("--json", action="store_true", help="print the table as ONE JSON line")
    return parser


def main(argv=None) -> int:
    C.force_utf8()
    args = hooklib.exact_options(_parser()).parse_args(argv)
    task = hooklib.story_cli(SCRIPT, root=args.task_root, key_flag=None)
    found = neighbours(task)
    if args.json:
        print(json.dumps(found, ensure_ascii=True), flush=True)
    else:
        for line in lines(found):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
