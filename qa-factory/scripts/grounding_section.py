#!/usr/bin/env python3
"""One part of the grounding table, read by its id, with its line numbers.

    grounding_section.py --task T --show G-12 --show R-3 --show B-2
    grounding_section.py --task T --requirement R-3
    grounding_section.py --task T --map                      (id -> lines of every part, the text a refused whole Read carries)

The table (`work/grounding.yaml`) is far past the size a whole `Read` is allowed (a live one: 4,883 lines), and the parts of it
a window works on are a row, a requirement line, a blast area. `--show <id>` prints the lines of the element(s) that carry the
id - the bytes the file holds, not a re-emission, so what is read here is what an `Edit` can match - under a header that names
the id, the element's path and its 1-based line numbers (the number `Read offset` takes). An id is a row (`G-n`), a requirement
(`R-n`), a blast area (`B-n`), a claim (its `r`), a hunk (its id or its short `H-n`) or a risk (`K-n`, which prints the row
that holds it). `--requirement R-n` is the join: the requirement's line, the rows that name it, the claims that carry it.

Reads through the table's one reader (`planning_contract.read_grounding`) and the one function that says where each element
lies (`planning_contract.grounding_item_lines`); nothing is parsed here and NOTHING IS WRITTEN. A call whose id the table does
not have is refused whole (exit 2): the answer is never a neighbour or a part.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import artifact_sections as AS  # noqa: E402
import contract  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
from role_cli import epilog, refuse, run_guarded, command_from_argv  # noqa: E402

COMMAND = "grounding_section.py"


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else (str(value) if isinstance(value, int) and not isinstance(value, bool) else "")


def _items(data, key) -> list:
    """The list under `key`, or `[]` when there is none (an absent key, `null`, a map: nothing to catalogue)."""
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, list) else []


# What each list of the table names by: `(id fields)`; a row also owns the risks it holds (`rows[i].risks[j].id`, owner: the row).
ID_FIELDS = {"rows": ("id",), "blast_radius": ("id",), "hunks": ("id", "short"), "requirements": ("r",), "claims": ("r",)}


def _elements(data: dict) -> list:
    """`[(key, path, item)]` for each object element of each list of the table, in the order of the file (the blast areas are
    `blast_radius.areas[i]`)."""
    out = []
    for key in data:
        items = _items(data[key], "areas") if key == "blast_radius" else _items(data, key)
        prefix = "blast_radius.areas" if key == "blast_radius" else key
        out += [(key, f"{prefix}[{i}]", item) for i, item in enumerate(items) if isinstance(item, dict)]
    return out


def catalog(data: dict) -> list:
    """`[(id, path, owner path)]` for every id the table carries, in the order of the file: a row `rows[i].id`, a risk of a row
    `rows[i].risks[j].id` (owner: the row), a requirement `requirements[i].r`, a blast area `blast_radius.areas[i].id`, a claim
    `claims[i].r`, a hunk `hunks[i].id` and `hunks[i].short`. The path of an id is the element it names; the OWNER is the element
    whose lines are printed (a risk has no line of its own worth reading apart from its row)."""
    out = []
    for key, path, item in _elements(data):
        out += [(_text(item.get(field)), path, path) for field in ID_FIELDS.get(key, ())]
        if key == "rows":
            out += [(_text(risk.get("id")), f"{path}.risks[{j}]", path)
                    for j, risk in enumerate(_items(item, "risks")) if isinstance(risk, dict)]
    return [entry for entry in out if entry[0]]


def _refuse_missing(wanted: str, known: list, requirements_only: bool = False) -> int:
    """The refusal of an id the table does not have (`--requirement`: one that is not a REQUIREMENT, and then only requirements are
    listed, with `--show` as the door when the id is another part). The ids are `artifact_sections.ids_there`'s: capped, counted."""
    if requirements_only:
        listed = AS.ids_there(entry[0] for entry in known if entry[1].startswith("requirements["))
        door = f" `{wanted}` is another part of the table: `--show {wanted}` prints it." if any(e[0] == wanted for e in known) else ""
        said = f"no requirement `{wanted}` in {PC.GROUNDING_FILE}; requirements there: {listed}.{door}"
    else:
        said = f"no `{wanted}` in {PC.GROUNDING_FILE}; ids there: {AS.ids_there(entry[0] for entry in known)}."
    return refuse(COMMAND, said + " Nothing was printed. Name an id from that list, or read the file with `Read` and `offset`/`limit`")


def _block(label: str, path: str, spans: dict, doc) -> str:
    first, last = spans[path]
    return f"{label} ({path}, lines {first}-{last})\n" + "\n".join(doc.lines[first - 1:last])


def _unplaced(wanted: str, path: str) -> int:
    return refuse(COMMAND, f"`{wanted}` is in {PC.GROUNDING_FILE} ({path}) but the lines that hold it could not be established "
                           "with certainty, so none are shown. Read that part with `Grep -n` and `Read` `offset`/`limit`")


def show(doc, ids: list) -> int:
    known = catalog(doc.data)
    spans = PC.grounding_item_lines(doc)
    blocks = []
    for wanted in dict.fromkeys(ids):
        hits = [entry for entry in known if entry[0] == wanted]
        if not hits:
            return _refuse_missing(wanted, known)
        for owner in dict.fromkeys(entry[2] for entry in hits):      # one element named twice is printed once
            if owner not in spans:
                return _unplaced(wanted, owner)
            blocks.append(_block(wanted, owner, spans, doc))
    print("\n\n".join(blocks))
    return 0


def requirement(doc, wanted: str) -> int:
    known = catalog(doc.data)
    spans = PC.grounding_item_lines(doc)
    lines_of = [entry for entry in known if entry[0] == wanted and entry[1].startswith("requirements[")]
    if not lines_of:
        return _refuse_missing(wanted, known, requirements_only=True)
    rows = [(f"rows[{i}]", row) for i, row in enumerate(_items(doc.data, "rows"))
            if isinstance(row, dict) and wanted in [_text(r) for r in _items(row, "requirements")]]
    claims = [path for ident, path, _ in known if ident == wanted and path.startswith("claims[")]
    blocks = []
    for path in [entry[1] for entry in lines_of] + [p for p, _ in rows] + claims:
        if path not in spans:
            return _unplaced(wanted, path)
    for entry in lines_of:
        blocks.append(_block(wanted, entry[1], spans, doc))
    for path, row in rows:
        blocks.append(_block(_text(row.get("id")) or path, path, spans, doc))
    if not rows:
        blocks.append(f"rows naming {wanted}: none")
    for path in claims:
        blocks.append(_block(wanted, path, spans, doc))
    print("\n\n".join(blocks))
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, epilog=epilog(COMMAND), formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--task-root", default=None, dest="task_root")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--show", dest="shows", action="append", default=[], metavar="ID",
                      help="print the element(s) with this id and their line numbers; repeatable")
    what.add_argument("--requirement", default=None, metavar="R-n",
                      help="the requirement's line, the rows that name it and the claims that carry it")
    what.add_argument("--map", action="store_true", help="id -> lines of every row, requirement, area, claim and hunk, and the key ranges")
    ns = hooklib.exact_options(ap).parse_args()
    try:        # the story first (CX1-18): the key and the root name ONE existing folder, or this refuses on its own channel
        story = hooklib.story_of(COMMAND, key=ns.task, root=ns.task_root)
    except ValueError as exc:
        return refuse(COMMAND, str(exc))
    if ns.map and (text := AS.section_map_text(contract.artifact_write_path(story, "grounding.yaml"), "grounding")):
        print(text)         # the map the guard's refusal carries: one function; "" when it cannot be established with certainty
        return 0
    doc, problem = PC.read_grounding(story)
    if doc is None:
        return refuse(COMMAND, f"{problem.text.rstrip('.')}. This is for the {problem.who} to put right; nothing was printed. "
                               "Read the file with `Grep -n` and `Read` `offset`/`limit` meanwhile")
    if ns.map:
        return refuse(COMMAND, f"no map of {PC.GROUNDING_FILE} could be established with certainty (the table changed while it was "
                               "read, or a span could not be checked). Nothing was printed; read it with `Grep -n` and `Read` `offset`/`limit`")
    if ns.requirement is not None:
        return requirement(doc, ns.requirement.strip())
    return show(doc, [i.strip() for i in ns.shows])


if __name__ == "__main__":
    raise SystemExit(run_guarded(command_from_argv(COMMAND), main))
