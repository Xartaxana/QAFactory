"""Put the empty handoff form beside the brief, with everything code already knows filled in.

`story_step start` calls this. The role receives a file whose sections, artifact paths and
allowed values are already there, and whose header, ticket and dispatch id are already
written - so the first thing it does is the work, not the form.

  handoff_init.py --task T --stage S5 --role qa-automator [--to qa-code-critic]
                  [--dispatch S5-qa-automator-1] [--scope TC-001,TC-002] [--out PATH] [--carry-from PARENT_FORM]

Nothing is invented here: the contract comes from `handoffs/index.yaml`, never from a file
name, so a handover without a contract is a gap of the factory that says so in one line
instead of a role guessing the shape of its own handover.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import handoff  # noqa: E402

try:
    import hooklib  # noqa: E402
    _HOOKLIB_FAILED = ""
except Exception as _exc:                            # pragma: no cover - a broken plugin copy
    hooklib = None
    _HOOKLIB_FAILED = f"{type(_exc).__name__}: {_exc}"


def task_root(task: str, root=None) -> Path:
    """The folder of the EXISTING story the form is written for (CX1-18): `--task-root` when given (a place; the key is
    data here and only goes into the form's head), else the folder `--task` names. A story folder is never guessed
    from the current folder and never created here (S0 creates it): a `ValueError` says why not."""
    if hooklib is None:
        raise ValueError(f"handoff_init.py cannot resolve the story: hooklib did not import ({_HOOKLIB_FAILED}), and a "
                         "story folder is never guessed from the current folder. The plugin copy is broken: update "
                         "or reinstall the plugin")
    if root is not None:
        return hooklib.story_root_at(root, "handoff_init.py --task-root")
    return hooklib.story_root(task, "handoff_init.py --task")


# `one of vocabulary.X`, then the hand-written list some contracts keep after it (` - a|b|c`, never a space inside).
VOCAB_LIST = re.compile(r"one of vocabulary\.([a-z_]+)(?: - [^\s,>]+)?")


def inline_values(text: str, role: str) -> str:
    """The form lists its own allowed values (RC1-9 (a), variant (i), the owner's word 26.10.2026): every
    `<one of vocabulary.X>` placeholder of the form becomes `<one of vocabulary.X - a|b|c>`, the words read through
    `handoff.allowed` (the one reader of a vocabulary list) - a hand-written list after the name is replaced by it, and
    the line's own comment and any tail such as `, or a dash when ...` stay. For a row's `state` the words are the
    ROLE's own (`handoff.options_for_role`, the list a refusal prints), not the whole vocabulary. A list that is empty
    or cannot be read is written as `NONE READABLE`: a blank list would read as "any word" (FR-41). Only the text of
    the form changes: the check reads the contract's template, so no verdict moves."""
    doc = handoff.parse(text)
    try:
        specs = handoff.spec_of(doc)
    except Exception:                      # an unreadable vocabulary: every list below is declared unreadable
        specs = {}
    for path, node in doc.nodes.items():
        if not isinstance(node.value, str) or not handoff.PLACEHOLDER.match(node.value.strip()):
            continue
        field = specs.get(re.sub(r"\[\d+\]", "[]", path))
        for number in range(node.line, node.end_line + 1):
            code, _comment = handoff._strip_comment(doc.lines[number])
            found = VOCAB_LIST.search(code)
            if not found:
                continue
            try:
                if path.rsplit(".", 1)[-1] == "state" and field is not None:
                    words = handoff.options_for_role(field, role)
                else:
                    words = handoff.allowed(found.group(1))
            except Exception:
                words = []
            shown = "|".join(words) if words else "NONE READABLE"
            swapped = f"{code[:found.start()]}one of vocabulary.{found.group(1)} - {shown}{code[found.end():]}"
            doc.lines[number] = swapped + doc.lines[number][len(code):]
            break
    return doc.text()


def _fill_line(dispatch: str, role: str, form: str = "", doc=None) -> str:
    """The one comment line that tells the role how the form is filled; the shell clause only for a role that has one.
    `form`: the path the form is written to, as the role is to spell it (`--out` is honoured, FR-37); with none, the
    default place of the dispatch's form. The file of the words is named by the one rule, `handoff_check.sibling_values`.
    `doc`: the parsed contract text; when it has a list of rows, the line ends with how a row is written by its index,
    on the contract's own list (`handoff_check.row_form`, the one hint; HF8-7). The addition goes AFTER the existing
    text on the same line: `carry_from_parent` finds the line by `# Fill:` and puts the repair comment right under it."""
    try:
        from host_adapter import role_has_bash
        shell = role_has_bash(role)
    except Exception:                      # a text never names a command the guard would refuse: unknown means no Bash
        shell = False
    import handoff_check
    form = form or f"work/handoffs/{dispatch}.yaml"
    values = handoff_check.sibling_values(form).as_posix()
    door = (f", or run handoff_check.py --file {form} --fix --values - (Bash)" if shell else "")
    rows = ""
    try:
        paths = handoff_check.row_form(handoff.spec_of(doc), "")[1] if doc is not None else []
    except Exception:                      # an unreadable contract: the line as it was
        paths = []
    first, later = handoff_check.row_pair(paths)
    if first:
        rows = f' A row of a list, one line per key: "{first}": <value>, the next row "{later}".'
    return (f'# Fill: write your fields as "path: value" lines to {values} in one Write{door}; '
            "a Write over this form is refused, and while that file waits an Edit here is refused too." + rows)


AUTHOR_TOKEN = handoff.AUTHOR_TOKEN
AUTHOR_NOTE = ("# inputs_read[0] names the author's form the driver handed you; change it if you reviewed another")


def fill_head(text: str, *, task: str, dispatch: str, role: str, stage: str, scope: str, form: str = "",
              author_dispatch: str = "") -> str:
    """The values code knows before the role starts. Everything else stays a placeholder. `form`: where the form is
    written, for the head line (see `_fill_line`). `author_dispatch`: the id of the author's last accepted dispatch (F1, B-2);
    when given, it replaces the token `<the author's dispatch>` and one comment line above `inputs_read:` tells the critic the
    row is its own word to change; when empty the token stays a placeholder (a guessed author never stands in a form)."""
    filled_author = bool(author_dispatch) and AUTHOR_TOKEN in text
    if filled_author:
        text = text.replace(AUTHOR_TOKEN, author_dispatch)
    text = text.replace("<TICKET>", task)
    text = text.replace("work/handoffs/<dispatch>.yaml", f"work/handoffs/{dispatch}.yaml")
    text = re.sub(r"<dispatch>", dispatch, text)
    doc = handoff.parse(text)
    for path, value in (("header.role", role), ("header.stage", stage),
                        ("header.window", scope or task), ("dispatch", dispatch)):
        if path in doc.nodes and handoff.is_placeholder(doc.get(path)):
            handoff.set_value(doc, path, value)
            doc = handoff.parse(doc.text())            # line numbers move when a value shrinks
    shape = doc                                        # the contract's lists of rows, read before the words are inlined
    doc = handoff.parse(inline_values(doc.text(), role))
    top = 0                                            # after the contract's leading comments, before its first key
    while top < len(doc.lines) and (not doc.lines[top].strip() or doc.lines[top].lstrip().startswith("#")):
        top += 1
    doc.lines.insert(top, _fill_line(dispatch, role, form, shape))
    if filled_author:
        at = next((n for n, line in enumerate(doc.lines) if re.match(r"^inputs_read:", line)), None)
        if at is not None:
            doc.lines.insert(at, AUTHOR_NOTE)
    return doc.text()


# F1 (b): the sections whose template rows are emptied in the role's copy, by contract. The contract files stay the schema.
EMPTIED = {
    "questions": ("s2-stage-critic-to-tester", "s3-stage-critic-to-strategist", "s4-case-critic-to-designer"),
    "findings": ("s2-stage-critic-to-tester", "s3-stage-critic-to-strategist", "s4-case-critic-to-designer",
                 "s5-critic-to-automator"),
}


def empty_optional_lists(text: str, contract: str) -> str:
    """The role's copy with every optional list section of `EMPTIED` for this contract that still holds only template rows
    written as `<section>: []` followed by the sample rows as comment lines (F1 (b), B-11: a reader never meets a template row as
    data). Never touched: a `REQUIRED_LISTS` section, a `null_outcome` section, a section holding any real value (a carried or
    prefilled row). Runs LAST, after the carry and the prefill. A text that cannot be read is returned as it was."""
    wanted = [name for name, contracts in EMPTIED.items() if contract in contracts]
    if not wanted:
        return text
    try:
        doc = handoff.parse(text)
        nulled = handoff.null_outcomes(contract)
        for section in wanted:
            if section in handoff.REQUIRED_LISTS or section in nulled:
                continue
            if not isinstance(doc.data.get(section), list) or not doc.data.get(section):
                continue
            if not handoff.only_template(doc.data.get(section)):
                continue
            start = next((n for n, line in enumerate(doc.lines) if re.match(r"^" + re.escape(section) + r":\s*(#.*)?$", line)), None)
            if start is None:
                continue
            end = start + 1
            while end < len(doc.lines) and (not doc.lines[end].strip() or doc.lines[end][0] in " \t-#"):
                end += 1
            while end > start + 1 and (not doc.lines[end - 1].strip() or not doc.lines[end - 1].startswith((" ", "\t", "-"))):
                end -= 1                                    # the blank and comment lines under the block belong to what follows
            sample = ["# " + line for line in doc.lines[start + 1:end]]
            doc.lines = doc.lines[:start] + [f"{section}: []"] + sample + doc.lines[end:]
            doc = handoff.parse(doc.text())
        return doc.text()
    except Exception:                                       # noqa: BLE001 - the skeleton is written as it was; the check reads the same
        return text


# A listed row field: `section[].key` (the key in every row) or `section[0].key` (in one row).
CARRY_ROW = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[(\d*)\]\.([A-Za-z_][A-Za-z0-9_]*)$")
CARRY_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
CARRYABLE = (str, int, float, bool)        # a scalar the parent wrote; a list or a map is asked again, never re-rendered


MEASURED_VERSION = "<hash>"      # the template placeholder of a version code measures (`handoff_check` derives it from the file)


def _same_row(doc, parent, section: str, index: int, listed: set) -> bool:
    """Is row `index` of `section` the same row in the parent form (HF9-2, rule 5.1)? It must exist there, and every key of
    it that the contract itself wrote (a non-placeholder value of the NEW form) and that is not a carried key must equal the
    parent's. A row whose identity cannot be shown is asked, never carried (AR-28)."""
    prefix = f"{section}[{index}]."
    if not any(path.startswith(prefix) for path in parent.nodes):
        return False
    for path, node in doc.nodes.items():
        key = path[len(prefix):]
        if not path.startswith(prefix) or "." in key or "[" in key:
            continue
        if f"{section}[].{key}" in listed or f"{prefix}{key}" in listed:
            continue
        if handoff.is_placeholder(node.value):
            continue
        theirs = parent.nodes.get(path)
        if theirs is None or str(theirs.value) != str(node.value):
            return False
    return True


def _version_current(doc, parent, section: str, index: int, root) -> bool:
    """Does the parent's row still describe the input as it is NOW (critic t-1587 F3)? Only a row whose contract has a
    `version` key whose template placeholder is the measured kind (`<hash>`, what `handoff_check.DERIVERS` measures) is
    compared; a row without a `version` key, or with another kind (`<plan_revision>`, a window id: role-written, nothing to
    measure) has nothing to compare and passes. The parent's `version` must equal what the one deriver `handoff_check` uses
    for `section[].version` measures now for the row's path; a parent version that is absent, different, or an input that
    cannot be measured now gives False: the row is asked, never carried (AR-28, AR-13)."""
    mine = doc.nodes.get(f"{section}[{index}].version")
    if mine is None or str(mine.value).strip() != MEASURED_VERSION:
        return True
    theirs = parent.nodes.get(f"{section}[{index}].version")
    path = parent.nodes.get(f"{section}[{index}].path")
    if root is None or theirs is None or path is None or handoff.is_placeholder(theirs.value):
        return False
    try:
        import handoff_check
        deriver = handoff_check.DERIVERS.get(f"{section}[].version")
        got = deriver(handoff_check.Artifacts(Path(root)), doc, {"path": str(path.value)}) if deriver else None
    except Exception:                                  # noqa: BLE001 - a measurement that fails is an unknown
        return False
    return bool(got) and got[0] not in (None, "", []) and str(got[0]) == str(theirs.value)


def _is_template_text(mine, template, target: str, value) -> bool:
    """Is `value` the template's own text for exactly this path (critic t-1587 F4)? Compared with the new form's text there and
    the contract template's, after the whitespace strip the placeholder check uses; a value that only CONTAINS it is an answer."""
    seen = str(value).strip()
    for node in (mine, template.nodes.get(target) if template is not None else None):
        if node is not None and isinstance(node.value, str) and node.value.strip() == seen:
            return True
    return False


def carry(doc, parent, paths, root=None, template=None) -> tuple:
    """`(doc, carried)`: every listed field the parent form answered is written into the new form (HF9-2). `carried` is the
    list of concrete paths written, in the order of `paths`. A field is carried only when the new form has it, the parent
    holds a scalar there that is not a placeholder (a dash IS a value) and not the template's own text for that path, and, for
    a row field, the row is the same row and its `version` still equals the input as measured now under `root`. Nothing
    else changes; every doubt leaves the field blank for the role (error direction: toward asking)."""
    listed = set(paths)
    carried = []
    for path in paths:
        row = CARRY_ROW.match(path)
        if row:
            section, index, key = row.groups()
            numbers = [int(index)] if index != "" else doc.rows(section)
            targets = [f"{section}[{n}].{key}" for n in numbers
                       if _same_row(doc, parent, section, n, listed) and _version_current(doc, parent, section, n, root)]
        elif CARRY_PLAIN.match(path):
            targets = [path]
        else:
            continue
        for target in targets:
            mine, theirs = doc.nodes.get(target), parent.nodes.get(target)
            if mine is None or theirs is None or target in carried:
                continue
            if not isinstance(theirs.value, CARRYABLE) or handoff.is_placeholder(theirs.value):
                continue
            if _is_template_text(mine, template, target, theirs.value):
                continue
            if handoff.set_value(doc, target, theirs.value):
                carried.append(target)
                doc = handoff.parse(doc.text())            # line numbers move when a value changes length
    return doc, carried


def carry_from_parent(text: str, contract: str, parent: Path) -> tuple:
    """`(text, note)`: the new form's text with the accepted parent's whole-stage answers carried into it, each recorded in
    `derived:` with the parent as its source and one comment line under `# Fill:` (HF9-2). When nothing is carried the text is
    returned unchanged and the note says why - the form is written all the same (FR-4), exit 0. A parent that is missing,
    unreadable, of another contract, or silent on every listed field carries nothing (AR-28)."""
    def nothing(why: str) -> tuple:
        return text, f"handoff_init: carried nothing from {parent.name} ({why})"

    paths = handoff.repair_carries(contract)
    if not paths:
        return nothing(f"the contract {contract} lists no field to carry")
    try:
        old = handoff.parse(parent.read_text(encoding="utf-8"))
    except (OSError, ValueError):                      # includes a file that is not text
        return nothing("the parent form is missing or cannot be read")
    except Exception:                                  # noqa: BLE001 - the parser never raises; a surprise is an unknown
        return nothing("the parent form cannot be parsed")
    if str(old.get("contract") or "") != contract:
        return nothing(f"the parent form is of contract `{old.get('contract') or 'none'}`, not `{contract}`")
    try:
        template = handoff.template(contract)
    except Exception:                                  # noqa: BLE001 - no template to compare with: the other comparison remains
        template = None
    root = parent.resolve().parent.parent.parent       # <story>/work/handoffs/<form>.yaml -> <story>
    doc, carried = carry(handoff.parse(text), old, paths, root, template)
    if not carried:
        return nothing("the parent form answers none of the listed fields in the same rows")
    import handoff_check
    source = f"carried from work/handoffs/{parent.name} (the accepted form this dispatch reworks)"
    doc = handoff_check.record_derived(doc, [{"field": path, "source": source} for path in carried])
    note = (f"# Repair of {parent.stem}: the fields under derived: carry its accepted answers; "
            "fill the rows of this dispatch.")
    at = next((n for n, line in enumerate(doc.lines) if line.startswith("# Fill:")), None)
    doc.lines.insert(len(doc.lines) if at is None else at + 1, note)
    return doc.text(), f"handoff_init: carried {len(carried)} field(s) from {parent.name}"


def prefill_rows(text: str, contract: str, ids: list) -> tuple:
    """`(text, note)`: the form with the id of each row the dispatch was sent for already in it (RN1-2): `scope[i].id` is a value
    CODE knows (the controller's dispatch record names the rows, `controller.py` `plan_rows`), so the role is not asked for it. The
    ids are split, stripped, emptied and de-duplicated with their order kept; each goes through `handoff_check.apply_values` (the ONE
    writer of a form's words, which opens a row by its index and writes a value that looks like a placeholder, `<x`, quoted) and is
    recorded under `derived:` with the dispatch record as its source. Nothing else of a row is written (`state`, `reason` stay
    placeholders: the role's own words). Error direction: UNDER-fill - a pair the writer refuses leaves that row blank and the note
    names it; an id is never guessed. With no id the text is returned unchanged and the note is empty."""
    wanted = list(dict.fromkeys(item.strip() for item in ids if isinstance(item, str) and item.strip()))
    if not wanted:
        return text, ""
    import handoff_check
    doc = handoff.parse(text)
    pairs = [(f"scope[{index}].id", value, 0, "") for index, value in enumerate(wanted)]
    doc, applied, problems, _notes = handoff_check.apply_values(doc, contract, pairs)
    refused = {problem.path for problem in problems}
    done = [path for path, _value, _line, _raw in pairs if path not in refused]
    source = "the plan rows this rework dispatch was sent for (the controller's dispatch record)"
    doc = handoff_check.record_derived(doc, [{"field": path, "source": source} for path in done])
    note = f"handoff_init: wrote {applied} row id(s) from the dispatch record"
    if refused:
        note += "; left blank: " + ", ".join(sorted(refused))
    return doc.text(), note


def _stale_values(out: Path) -> str:
    """The values file of an EARLIER attempt, moved aside before a form is written again (M-6): it was written for
    the form that is going away and is never applied to the new one. Returns the line to print, "" when no file was
    waiting. Moved to `<stem>.values.stale.yaml` (replacing the one before); when that fails the file is deleted; when
    that fails too the form is still written (a form that is not there is a form nobody checks, FR-4) and the line
    says loudly that the old words will meet it. Never raises."""
    try:
        import handoff_check
        waiting = handoff_check.sibling_values(out)
        if not waiting.is_file():
            return ""
    except Exception as exc:
        return (f"handoff_init: could not look for a values file beside {out.name} ({type(exc).__name__}: {exc}); "
                "if one is there it will be applied to this new form at the next check - remove it before the role starts")
    stale = waiting.with_name(f"{out.stem}.values.stale.yaml")
    try:
        os.replace(waiting, stale)
        return f"handoff_init: {waiting.name} belonged to the form written before; kept as {stale.name} and never applied"
    except OSError as exc:
        moved = exc
    try:
        waiting.unlink()
        return (f"handoff_init: {waiting.name} belonged to the form written before and could not be kept as {stale.name} "
                f"({type(moved).__name__}); it was deleted and never applied")
    except OSError as exc:
        return (f"handoff_init: {waiting.name} could not be moved aside ({type(exc).__name__}); it will be applied to this "
                "new form at the next check - remove it before the role starts")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--stage", required=True, help="S0..S9, or A / B for a gate")
    ap.add_argument("--role", required=True, help="the role that FILLS the form")
    ap.add_argument("--to", default="", help="the receiving role, when a stage has two contracts")
    ap.add_argument("--dispatch", default="")
    ap.add_argument("--scope", default="")
    ap.add_argument("--contract", default="", help="override the lookup (a test, a new handover)")
    ap.add_argument("--task-root", default=None)
    ap.add_argument("--out", default="")
    ap.add_argument("--force", action="store_true", help="overwrite a form that already exists")
    ap.add_argument("--carry-from", default="",
                    help="the accepted form this dispatch reworks: its whole-stage answers (`repair_carries:` of "
                         "handoffs/index.yaml) are carried into the new form and recorded under `derived:`")
    ap.add_argument("--rows", default="",
                    help="comma-separated plan row ids the dispatch was sent for (S3 rework): written as `scope[i].id` of the "
                         "form and recorded under `derived:`; nothing else of a row is written")
    ap.add_argument("--author-dispatch", default="",
                    help="a stage critic's form (S2-S4): the id of the author's last accepted dispatch; fills the token "
                         "`<the author's dispatch>` of the contract (the critic may change the row)")
    args = (hooklib.exact_options(ap) if hooklib else ap).parse_args()
    try:                                              # the story is decided first: before the contract, before `--out`
        root = task_root(args.task, args.task_root)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    contract = args.contract or handoff.contract_of(args.stage, args.role, args.to)
    if not contract:
        print(f"handoff_init: no contract for {args.role} at {args.stage}"
              + (f" -> {args.to}" if args.to else "")
              + " in handoffs/index.yaml. A handover without a contract is a gap of the "
                "factory: add the row and the file, or pass --contract to name one.")
        return 2
    try:
        text = (handoff.CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8")
    except OSError as exc:
        print(f"handoff_init: cannot read the contract `{contract}`: {exc}")
        return 2

    dispatch = args.dispatch or f"{args.stage}-{args.role}-1"
    out = Path(args.out) if args.out else root / "work" / "handoffs" / f"{dispatch}.yaml"
    if out.exists() and not args.force:
        print(f"handoff_init: {out} already exists - the role's own file is never overwritten "
              f"(pass --force only when starting the dispatch again)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    stale_line = _stale_values(out)                   # before the form is written: never a new form beside the old words
    if stale_line:
        print(stale_line)
    written = fill_head(text, task=args.task, dispatch=dispatch, role=args.role,
                        stage=args.stage, scope=args.scope,
                        form=Path(args.out).as_posix() if args.out else "",
                        author_dispatch=args.author_dispatch.strip())
    carry_note = ""
    if args.carry_from:                               # a repair dispatch: the accepted parent's whole-stage answers (HF9-2)
        written, carry_note = carry_from_parent(written, contract, Path(args.carry_from))
    # AFTER the carry: `carry` matches a row by its identity (`_same_row`: a non-placeholder value the new form already holds must
    # equal the parent's), so ids written first would only be compared, never hidden; the carry has finished before they stand.
    written, rows_note = prefill_rows(written, contract, args.rows.split(","))
    written = empty_optional_lists(written, contract)  # LAST: a carried or prefilled row has made its section non-empty by now
    out.write_text(written, encoding="utf-8")
    print(f"handoff form: {out}")
    if carry_note:
        print(carry_note)
    if rows_note:
        print(rows_note)
    print(f"contract: {contract} ({args.role} -> {args.to or 'the next role'})")
    print(f"fill it, then: handoff_check.py --file {out} --task {args.task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
