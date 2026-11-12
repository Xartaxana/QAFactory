#!/usr/bin/env python3
"""One field of one plan row, changed in place - or one whole row read, mapped or replaced.

    plan_row.py --task T --row TS-19 --set source_conflict=true --set oracle_unknown=true
    plan_row.py --task T --row TS-19 --show
    plan_row.py --task T --show --row TS-3 --row TS-19      (several rows, each with its line numbers)
    plan_row.py --task T --map                              (id -> lines of every row)
    plan_row.py --task T --put-row row.json                 (replace ONE whole row you wrote, after the plan check)

TP1-13797, 26.09: the gate refused a plan because TS-19 did not carry the contradiction the
register recorded. Setting two booleans cost **$16.53** — the strategist rewrote `test-plan.json`
(78 KB) and `test-plan.md` whole, four times over one session: 31 `Write` calls, 630k output
tokens, and every rewrite then sat in its context and was re-read on every later turn. The row is
a record, not prose: changing a field of it is code's work.

What this does NOT do: judgement. It refuses a field that is not in the row's schema, refuses a
row that is not in the plan, and never invents a value. The markdown table is the human's copy of
the same row — this prints the exact line to change there, and changes nothing in it, because a
table cell carries the role's own wording.

A row's bytes are found structurally (`artifact_sections.plan_row_spans`), never by looking for the
text `"id": "TS-3"`: a row whose `id` follows a nested object, or an earlier row whose nested object
carries the same `id`, was matched to the nested object and the write landed on the wrong bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import artifact_sections as AS  # noqa: E402
import hooklib  # noqa: E402
from install_paths import _atomic_write  # noqa: E402  (the byte writer: temp beside, flushed, `os.replace`)
from role_cli import (REPAIR_MARKER, command_from_argv, epilog, refuse,  # noqa: E402
                      run_guarded)

COMMAND = "plan_row.py"
TRUE, FALSE = ("true", "yes", "on", "1"), ("false", "no", "off", "0")
BOM = b"\xef\xbb\xbf"


def typed(value: str):
    """`true`/`false` are booleans, digits are numbers, everything else is the string given."""
    low = str(value).strip().lower()
    if low in TRUE:
        return True
    if low in FALSE:
        return False
    if re.fullmatch(r"-?\d+", str(value).strip()):
        return int(value)
    return value


def plan_paths(task_root: Path) -> tuple:
    return task_root / "work" / "test-plan.json", task_root / "work" / "test-plan.md"


def load_rows(text: str) -> list:
    return AS.rows_of(json.loads(text.lstrip("\ufeff")))


def row_span(text: str, row_id: str) -> tuple:
    """(start, end) of THIS row's object in the file's own bytes, so the write touches one row; (-1, -1) when no row has the id,
    when two do (the code never picks one), or when the text is not a plan.

    A full re-serialisation of the document would reformat every other row — a diff nobody asked
    for, and the thing this script exists to avoid."""
    try:
        hits = [(start, end) for rid, start, end, _, _ in AS.plan_row_spans(text) if rid == row_id]
    except ValueError:
        return (-1, -1)
    return hits[0] if len(hits) == 1 else (-1, -1)


def _style(text: str, start: int, end: int) -> tuple:
    """`(one_line, indent, newline)` of a row as the file writes it: a row on one line is written compact, a row over several in the
    indented form, nested under the leading whitespace of the line it starts on; the line ending is the file's own."""
    one_line = "\n" not in text[start:end]
    prefix = text[text.rfind("\n", 0, start) + 1:start]
    return one_line, ("" if one_line else prefix[:len(prefix) - len(prefix.lstrip())]), ("\r\n" if "\r\n" in text else "\n")


def _render(obj: dict, one_line: bool, indent: str, newline: str) -> str:
    if one_line:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(obj, ensure_ascii=False, indent=1).replace("\n", newline + indent)


def _write_plan(plan_json: Path, before: bytes, new_text: str) -> str:
    """THE write of the plan (AR-14: one writer; `--set`, `--add-row` and `--put-row` all end here). `""` when written, else why not.
    The file is read again and compared (sha256) with the bytes the caller worked from: another writer in between (the role's own
    Edit) means nothing is written. What this narrows is the window between that re-read and the replace; it does not close it.
    The bytes outside the changed row are not touched: no newline translation, a byte-order mark kept."""
    try:
        now = plan_json.read_bytes()
    except OSError as exc:
        return f"{plan_json} cannot be read again before the write ({type(exc).__name__}); nothing was written"
    if hashlib.sha256(now).hexdigest() != hashlib.sha256(before).hexdigest():
        return "the plan changed while this ran; read it again and repeat. Nothing was written"
    _atomic_write(plan_json, (BOM if before.startswith(BOM) else b"") + new_text.encode("utf-8"))
    return ""


def _row_from(given: str) -> tuple:
    """`(row object, "")` from `--add-row` / `--put-row`: the JSON itself, or a path to a file holding it; else `(None, why)`."""
    raw = given.strip()
    source = "the JSON you passed"
    if not raw.startswith("{"):
        path = Path(raw)
        if not path.is_file():
            return None, f"`{raw}` is neither a JSON object nor a file that exists"
        raw, source = path.read_text(encoding="utf-8-sig"), str(path)
    try:
        new = json.loads(raw)
    except ValueError as exc:
        return None, f"{source} is not readable JSON ({exc})"
    if not isinstance(new, dict):
        return None, f"{source} holds {type(new).__name__}, not one row object"
    if not str(new.get("id") or "").strip():
        return None, "the row carries no `id`, so nothing could address it later"
    return new, ""


def _missing_fields(rows: list, new: dict, row_id: str) -> list:
    """The fields every OTHER row carries and `new` does not."""
    others = [set(r) for r in rows if isinstance(r, dict) and str(r.get("id")) != row_id]
    return sorted(set.intersection(*others) - set(new)) if others else []


def _md_note(plan_md: Path, row_id: str) -> None:
    if not plan_md.is_file():
        return
    for line in plan_md.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", line):
            print(f"the human's copy of this row is in {plan_md.name} and still says what it "
                  f"said; if the change belongs in its words too, Edit that one line:\n  {line[:200]}")
            return


def add_row(plan_json: Path, plan_md: Path, raw: bytes, text: str, rows: list, given: str) -> int:
    """Append ONE row the role wrote, after the last row's own bytes.

    The row's content is the role's: this refuses a row that cannot be addressed later (no `id`),
    a duplicate, and a row missing fields that every existing row carries — it never fills one in.
    Building a plan of twenty rows by rewriting the file twenty times is what cost $16.53 once and
    525,812 tokens of call arguments over three runs."""
    new, why = _row_from(given)
    if new is None:
        return refuse(COMMAND, why)
    row_id = str(new.get("id") or "").strip()
    if any(isinstance(r, dict) and str(r.get("id")) == row_id for r in rows):
        return refuse(COMMAND, f"row {row_id} is already in the plan — change its fields with "
                               f"`--row {row_id} --set <field>=<value>`")
    if not rows:
        return refuse(COMMAND, f"{plan_json.name} carries no rows yet; the first write of the plan "
                               "is one Write, and every row after it comes through --add-row")
    missing = _missing_fields(rows, new, row_id)
    if missing:
        return refuse(COMMAND, f"every row of this plan carries {', '.join(missing)} and yours does "
                               "not. The values are yours to decide; add them and run this again")
    last = [str(r.get("id")) for r in rows if isinstance(r, dict)][-1]
    start, end = row_span(text, last)
    if start < 0:
        return refuse(COMMAND, f"the last row ({last}) is in the plan but its own bytes could not "
                               f"be found in {plan_json}; add your row with Edit instead")
    one_line, indent, newline = _style(text, start, end)
    problem = _write_plan(plan_json, raw, text[:end] + "," + newline + indent + _render(new, one_line, indent, newline) + text[end:])
    if problem:
        return refuse(COMMAND, problem)
    print(f"{row_id}: appended after {last} ({len(rows)} rows were there, all untouched)")
    print(f"written: {plan_json}")
    if plan_md.is_file():
        print(f"the human's copy in {plan_md.name} does not have this row yet — add its one table "
              "line with Edit, in your own words")
    print(REPAIR_MARKER + ".")
    return 0


def _row_lines(text: str, start: int, end: int) -> tuple:
    """`(header note, shown text)`: the lines of the row when it owns them (what an `Edit` matches), else just its own bytes."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end - 1)
    line_end = len(text) if line_end < 0 else line_end
    if not text[line_start:start].strip() and text[end:line_end].strip() in ("", ","):
        return "", text[line_start:line_end]
    return "; it shares its line with other bytes, so only its own bytes are shown", text[start:end]


def show_rows(plan_json: Path, text: str, ids: list) -> int:
    """Each named row as the file holds it, under `<id> (<array>[<i>], lines a-b)`. An id the plan does not have refuses the whole
    call and prints nothing; an id on two rows prints both, each under its own place."""
    container, spans = AS.plan_rows_indexed(text)
    shown = []
    for wanted in dict.fromkeys(ids):
        hits = [s for s in spans if s[1] == wanted]
        if not hits:
            return refuse(COMMAND, f"no row `{wanted}` in {plan_json.name}; ids there: {AS.ids_there(s[1] for s in spans)}. "
                                   "Nothing was printed")
        for index, rid, start, end, first, last in hits:
            note, body = _row_lines(text, start, end)
            shown.append(f"{rid} ({container}[{index}], lines {first}-{last}{note})\n{body}")
    print("\n\n".join(shown))
    return 0


def row_map(plan_json: Path) -> int:
    """`id first-last` for every row and the key ranges of the file - the text the guard's refusal carries, from the same code."""
    text = AS.section_map_text(plan_json, "plan_rows")
    if not text:
        return refuse(COMMAND, f"no map of {plan_json.name} could be established with certainty (the file is not readable "
                               "JSON, or changed while it was read, or a row's bytes could not be checked). Nothing was printed; "
                               "read it with `Grep -n` and `Read` `offset`/`limit`")
    print(text)
    return 0


def _require_v2(plan_json: Path) -> bool:
    """The controller gate's own reading (`state.get("coverage_contract_version") == 2`, `planning_contract.story_contract_mode`) of
    the story this plan belongs to (`<story>/work/test-plan.json`); no projection of the story is version 1."""
    import planning_contract as PC
    return PC.story_contract_mode(plan_json.parent.parent)[1] == 2


def _own_errors(PC, rows: list, row_id: str, require_v2: bool) -> list:
    """The errors of the row `row_id` ALONE under `validate_plan`: every one of them is the row's, an obligation's (`OB-n: ...`, named
    by the obligation, not by the row) included."""
    mine = [r for r in rows if isinstance(r, dict) and str(r.get("id")) == row_id]
    return PC.validate_plan(mine, require_v2=require_v2)


def _without(errors: list, taken: list) -> list:
    """`errors` less one occurrence of each of `taken` (a multiset difference, order kept)."""
    left, kept = list(taken), []
    for error in errors:
        if error in left:
            left.remove(error)
        else:
            kept.append(error)
    return kept


def _plan_check(before: list, after: list, row_id: str, require_v2: bool = False) -> str:
    """`""` when replacing the row leaves the plan no worse under `planning_contract.validate_plan`, else the refusal text. The row's
    own errors (`validate_plan` of the row alone) always refuse; an error elsewhere refuses only if the candidate has one the old
    plan did not have (a multiset, the old row's own errors left out); one that was there is a WARN line. `require_v2` is the
    controller gate's: the story's `coverage_contract_version` is 2."""
    import planning_contract as PC
    try:
        own = _own_errors(PC, after, row_id, require_v2)
        if own:
            return (f"row {row_id} would not pass the plan check: " + "; ".join(own[:6]) + (f" (+{len(own) - 6} more)" if len(own) > 6 else "")
                    + ". Nothing was written; fix those fields in your row and run this again")
        elsewhere = _without(PC.validate_plan(after, require_v2=require_v2), own)
        older = _without(PC.validate_plan(before, require_v2=require_v2), _own_errors(PC, before, row_id, require_v2))
    except Exception as exc:        # noqa: BLE001 - a check that cannot run is no pass
        return f"the plan check could not run on the candidate ({type(exc).__name__}); nothing was written"
    fresh = _without(elsewhere, older)
    if fresh:
        return "replacing the row would add plan errors that were not there: " + "; ".join(fresh[:6]) + ". Nothing was written"
    if elsewhere:
        print(f"WARN: the plan already had {len(elsewhere)} error(s) outside row {row_id}, not touched by this write: "
              + "; ".join(elsewhere[:3]) + (" ..." if len(elsewhere) > 3 else ""))
    return ""


def _field_changes(row_id: str, old: dict, new: dict) -> list:
    """`<id>.<field>: old -> new` for each field that differs; a field only one side has shows `(absent)`."""
    def shown(row: dict, field: str) -> str:
        return json.dumps(row[field], ensure_ascii=False) if field in row else "(absent)"
    return [f"{row_id}.{f}: {shown(old, f)} -> {shown(new, f)}" for f in dict.fromkeys([*old, *new])
            if (f in old) != (f in new) or json.dumps(old.get(f), sort_keys=True) != json.dumps(new.get(f), sort_keys=True)]


def put_row(plan_json: Path, plan_md: Path, raw: bytes, text: str, rows: list, given: str) -> int:
    """Replace ONE whole row, found by its `id`, with the row the role wrote - the plan check first, nothing written if it fails.

    The row must exist once (none: `--add-row`; two: refused, both named), keep its `id`, and carry every field the other rows
    carry. The candidate file is the old bytes with that row's bytes replaced; it must read back as the old rows with only that
    one replaced, and `validate_plan` of it must not be worse than before: no error on the row, no error elsewhere that was not
    there. An error of another row that WAS there is printed as WARN and does not stop a right row."""
    new, why = _row_from(given)
    if new is None:
        return refuse(COMMAND, why)
    row_id = str(new["id"]).strip()
    _, spans = AS.plan_rows_indexed(text)
    hits = [s for s in spans if s[1] == row_id]
    if not hits:
        return refuse(COMMAND, f"the plan carries no row `{row_id}`; to append a new row use `--add-row`. Rows: "
                               + AS.ids_there(s[1] for s in spans))
    if len(hits) > 1:
        return refuse(COMMAND, f"{len(hits)} rows carry the id `{row_id}` (" + ", ".join(f"rows[{s[0]}]: lines {s[4]}-{s[5]}" for s in hits)
                               + "); none was replaced - the code does not pick one. Make the ids unique first")
    index, _, start, end, _, _ = hits[0]
    old = rows[index]
    if new["id"] != old.get("id"):
        return refuse(COMMAND, f"the row's `id` must stay {json.dumps(old.get('id'))}; yours is {json.dumps(new['id'])}")
    missing = _missing_fields(rows, new, row_id)
    if missing:
        return refuse(COMMAND, f"every other row of this plan carries {', '.join(missing)} and yours does not. "
                               "The values are yours to decide; add them and run this again")
    body = _render(new, *_style(text, start, end))
    candidate = text[:start] + body + text[end:]
    try:
        got = load_rows(candidate)
    except ValueError:
        got = None
    if got != rows[:index] + [json.loads(body)] + rows[index + 1:]:     # the post-condition: ONE row differs, the rest read back as they were
        return refuse(COMMAND, f"the plan with row {row_id} replaced would not read back as the old plan with only that row "
                               "changed; nothing was written")
    changed = _field_changes(row_id, old, new)
    if not changed:
        print(f"{row_id}: already exactly that; nothing written")
        return 0
    problem = _plan_check(rows, got, row_id, _require_v2(plan_json)) or _write_plan(plan_json, raw, candidate)
    if problem:
        return refuse(COMMAND, problem)
    print("\n".join(changed))
    print(f"written: {plan_json} (row {row_id} only; {len(rows) - 1} other rows untouched)")
    _md_note(plan_md, row_id)
    print(REPAIR_MARKER + ".")
    return 0


def set_fields(plan_json: Path, plan_md: Path, raw: bytes, text: str, rows: list, row_id: str, sets: list) -> int:
    """`--row <id> --set FIELD=VALUE ...`: the named fields of that row, typed; every other byte of the file as it was."""
    row = next((r for r in rows if isinstance(r, dict) and str(r.get("id")) == row_id), None)
    if row is None:
        return refuse(COMMAND, f"no row `{row_id}` in {plan_json.name}; ids there: "
                               + AS.ids_there(r.get("id") for r in rows if isinstance(r, dict)) + ". Nothing was written")
    changes, unknown = {}, []
    for pair in sets:
        if "=" not in pair:
            return refuse(COMMAND, f"`{pair}` is not FIELD=VALUE")
        field, _, value = pair.partition("=")
        field = field.strip()
        if field not in row:
            unknown.append(field)
            continue
        changes[field] = typed(value)
    if unknown:
        return refuse(COMMAND, f"`{', '.join(unknown)}` is not a field of row {row_id}. Its fields: "
                               + ", ".join(sorted(row)))
    before = {field: row.get(field) for field in changes}
    if all(before[field] == value for field, value in changes.items()):
        print(f"{row_id}: already exactly that; nothing written")
        return 0
    start, end = row_span(text, row_id)
    if start < 0:
        return refuse(COMMAND, f"row {row_id} is in the plan but its own bytes could not be found "
                               f"in {plan_json} (or two rows carry that id) — the file may be formatted in a way this script "
                               "does not know; change the one field with Edit instead")
    problem = _write_plan(plan_json, raw, text[:start] + _render(dict(row, **changes), *_style(text, start, end)) + text[end:])
    if problem:
        return refuse(COMMAND, problem)
    for field, value in changes.items():
        print(f"{row_id}.{field}: {json.dumps(before[field], ensure_ascii=False)} -> "
              f"{json.dumps(value, ensure_ascii=False)}")
    print(f"written: {plan_json} (row {row_id} only; {len(rows) - 1} other rows untouched)")
    _md_note(plan_md, row_id)
    print(REPAIR_MARKER + ".")
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, epilog=epilog("plan_row.py"),
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--task-root", default=None)
    ap.add_argument("--row", dest="rows", action="append", default=[],
                    help="the plan row id, e.g. TS-19; repeatable with --show")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    metavar="FIELD=VALUE", help="one field of that row; repeatable")
    ap.add_argument("--add-row", dest="add_row", default="",
                    metavar="JSON|FILE", help="append ONE new row you wrote: the row's own JSON "
                                              "object, or a path to a file holding it")
    ap.add_argument("--put-row", dest="put_row", default="",
                    metavar="JSON|FILE", help="replace ONE whole row (found by its id) with the row you wrote, "
                                              "after the plan check; the JSON itself or a path to a file")
    ap.add_argument("--map", dest="map", action="store_true",
                    help="print id -> lines of every row, and the key ranges of the file")
    ap.add_argument("--show", action="store_true", help="print the row(s) with their line numbers and change nothing")
    ap.add_argument("--json", action="store_true")
    ns = hooklib.exact_options(ap).parse_args()
    if ns.task_root is not None:    # a GIVEN root names an existing story before the plan is read or written
        try:                        # (`--task` is a label here, not a key: L-2 F-4; the refusal is this script's own)
            hooklib.story_of(COMMAND, root=ns.task_root, key_flag=None)
        except ValueError as exc:
            return refuse(COMMAND, str(exc))
    modes = [bool(ns.add_row), bool(ns.put_row), ns.map, bool(ns.sets)]
    if sum(modes) > 1 or (ns.show and any(modes)):
        return refuse(COMMAND, "one thing per call: `--show`, `--map`, `--set`, `--add-row` or `--put-row`")
    if not any(modes[:3]) and not ns.rows:
        return refuse(COMMAND, "name the row: `--row <id>` to change or show one, `--map` for all, "
                               "`--add-row <json|file>` to append one, `--put-row <json|file>` to replace one you wrote")
    if ns.sets and len(ns.rows) != 1:
        return refuse(COMMAND, "`--set` changes one row: name exactly one `--row`")

    task_root = Path(ns.task_root) if ns.task_root is not None else Path("qa-factory/artifacts") / ns.task
    plan_json, plan_md = plan_paths(task_root)
    if not plan_json.is_file():
        return refuse(COMMAND, f"{plan_json} does not exist — S3 writes it")
    if ns.map:
        return row_map(plan_json)
    raw = plan_json.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        rows = load_rows(text)
    except UnicodeDecodeError:
        return refuse(COMMAND, f"{plan_json} is not UTF-8 text")
    except ValueError as exc:
        return refuse(COMMAND, f"{plan_json} is not readable JSON ({exc})")
    if ns.add_row:
        return add_row(plan_json, plan_md, raw, text, rows, ns.add_row)
    if ns.put_row:
        return put_row(plan_json, plan_md, raw, text, rows, ns.put_row)
    if ns.sets:
        return set_fields(plan_json, plan_md, raw, text, rows, ns.rows[0], ns.sets)
    return show_rows(plan_json, text, ns.rows)


if __name__ == "__main__":
    raise SystemExit(run_guarded(command_from_argv("plan_row.py"), main))
