#!/usr/bin/env python3
"""A repair dispatch's handover form carries the accepted parent's whole-stage answers (HF9-2, batch hotfix-12586/9).

The incident (TP1-14857): a rework of S3 and of S4 got the FULL empty form, so the repair role was asked how many
requirements the register carries, how many candidates were considered, the budget - facts about the INPUTS, which the
accepted parent form already answered - and `finish` refused the untouched fields. `handoff_init.py --carry-from <parent>`
writes those answers into the new form (the paths are DATA: `repair_carries:` in handoffs/index.yaml), records each in
`derived:` with the parent as its source, and `story_step._handoff_form` passes the flag for a dispatch that has `rework_of`.

  K-B1 a primary form is byte-identical (no flag, no derived:); story_step passes the flag only for a repair with a parent form
  K-B2 S3 rework: the listed answers are carried and labelled; the role's own fields stay open; the one comment line
  K-B3 the check asks nothing of the carried fields
  K-B4 an untouched carried form still reads as untouched (filled_share == 0)
  K-B5 adversarial parents: each carries nothing for the field it breaks, and the form is still written
  K-B6 S4 designer rework; a blank field's refusal text elsewhere is unchanged
  K-B7 a rework of a rework: carried again, the direct parent is the source
  K-B8 the audit of the data: every listed path resolves to a field the contract asks of the role
  K-B9 materialize over a form already there keeps it byte for byte (a repair dispatch made before the change)
"""
import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import handoff  # noqa: E402
import handoff_check as H  # noqa: E402
import handoff_init  # noqa: E402
import story_step  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repair-carry"
S3_PARENT, S4_PARENT = "S3-qa-test-strategist-1", "S4-qa-case-designer-1"
S3, S4 = "s3-strategist-to-designer", "s4-designer-to-case-critic"
S3_ARGS = ("S3", "qa-test-strategist")
S4_ARGS = ("S4", "qa-case-designer")
SOURCE = "carried from work/handoffs/{parent}.yaml (the accepted form this dispatch reworks)"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.yaml").read_text(encoding="utf-8")


def story(root: Path) -> Path:
    art = root / "artifacts" / "QA-1"
    (art / "work" / "handoffs").mkdir(parents=True)
    return art


def form_path(art: Path, dispatch: str) -> Path:
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


def init(root: Path, art: Path, args: tuple, dispatch: str, parent: Path | None = None):
    argv = ["--task", "QA-1", "--stage", args[0], "--role", args[1], "--dispatch", dispatch, "--task-root", str(art)]
    if parent is not None:
        argv += ["--carry-from", str(parent)]
    return run_script("handoff_init.py", *argv, cwd=root)


PINNED_ROW = re.compile(r"(- path: (?P<path>[^\s<]+)\n(?:[ \t]*#[^\n]*\n)*[ \t]+version:)[^\n]*")


def pinned(art: Path, text: str) -> str:
    """The accepted parent as the factory writes it: every `version` of an input row under work/ (not a handoff form) holds the
    sha256 of the file that row names, the value `handoff_check` measures (t-1587 F3). A missing file is written first."""
    def pin(found) -> str:
        path = art / found.group("path")
        if "handoffs/" in found.group("path"):
            return found.group(0)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_text(f"content of {found.group('path')}\n", encoding="utf-8")
        return f"{found.group(1)} {handoff.sha(path)}"
    return PINNED_ROW.sub(pin, text)


def parent_file(art: Path, name: str, text: str) -> Path:
    path = form_path(art, name)
    path.write_text(pinned(art, text), encoding="utf-8")
    return path


def read(art: Path, dispatch: str):
    return handoff.parse(form_path(art, dispatch).read_text(encoding="utf-8"))


def derived_fields(doc) -> dict:
    return {str(row.get("field")): str(row.get("source")) for row in (doc.data.get("derived") or []) if isinstance(row, dict)}


S3_CARRIED = {"inputs_read[0].requirements": 11, "inputs_read[1].existing_candidates_considered": "4 of 4",
              "budget.size": "M", "budget.cap": 10, "budget.planned_rows": 4, "budget.within_cap": True,
              "budget.if_over": "nothing cut"}


# ---------------------------------------------------------------------------------------------------- K-B1
def test_primary_form_is_unchanged() -> None:
    """K-B1. KILLS: a carry that runs without `--carry-from`/rework_of (the form gains derived: or a comment); a
    story_step that passes the flag for a primary dispatch or for a parent whose form is not on disk."""
    root = temp_project()
    try:
        art = story(root)
        run = init(root, art, S3_ARGS, "S3-qa-test-strategist-2")
        text = form_path(art, "S3-qa-test-strategist-2").read_text(encoding="utf-8")
        want = handoff_init.fill_head((handoff.CONTRACTS / f"{S3}.yaml").read_text(encoding="utf-8"), task="QA-1",
                                      dispatch="S3-qa-test-strategist-2", role="qa-test-strategist", stage="S3", scope="")
        check_eq("K-B1 primary: exit 0, the form is fill_head(template) byte for byte", (run.returncode, text), (0, want))
        check_not_in("K-B1 primary: no derived: section", "derived:", text)
        check_not_in("K-B1 primary: no repair comment", "# Repair of", text)
        check_not_in("K-B1 primary: the output says nothing about a carry", "carried", run.stdout)

        # the argv story_step builds (captured): the flag only for a repair whose parent form is on disk
        seen = []

        def capture(script, *argv):
            seen.append(list(argv))
            return 0, ""

        def argv_for(record, parent_on_disk: bool, parent_name: str = "S3-qa-test-strategist-1") -> list:
            seen.clear()
            task_root = root / "artifacts" / "QA-1"
            for stale in task_root.glob("work/handoffs/*.yaml"):
                stale.unlink()
            if parent_on_disk:
                form_path(task_root, parent_name).write_text(fixture("S3-qa-test-strategist-1"), encoding="utf-8")
            with mock.patch.object(story_step, "_run", capture), \
                    mock.patch.object(story_step, "_dispatch_record", lambda _root, _id: record):
                story_step._handoff_form("QA-1", "S3", "qa-test-strategist", "S3-qa-test-strategist-2", task_root, "")
            return seen[0]

        primary = argv_for({"id": "S3-qa-test-strategist-2"}, True)
        check_not_in("K-B1 story_step: a primary dispatch gets today's argv", "--carry-from", " ".join(primary))
        check_not_in("K-B1 story_step: a record that is not readable gets today's argv", "--carry-from",
                     " ".join(argv_for(None, True)))
        repair = argv_for({"id": "S3-qa-test-strategist-2", "rework_of": "S3-qa-test-strategist-1"}, True)
        want_form = str(art / "work" / "handoffs" / "S3-qa-test-strategist-1.yaml")
        check_eq("K-B1 story_step: a repair with its parent's form on disk passes the flag with that path",
                 repair[repair.index("--carry-from") + 1] if "--carry-from" in repair else None, want_form)
        check_not_in("K-B1 story_step: a repair whose parent form is NOT on disk passes nothing", "--carry-from",
                     " ".join(argv_for({"id": "x", "rework_of": "S3-qa-test-strategist-1"}, False)))
        for odd in ("../S3-qa-test-strategist-1", "a/b", "a\\b", ""):
            check_not_in(f"K-B1 story_step: a rework_of that is a path ({odd!r}) passes nothing", "--carry-from",
                         " ".join(argv_for({"id": "x", "rework_of": odd}, True)))
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------------- K-B2..K-B4
def test_s3_rework_carries_the_parents_answers() -> None:
    """K-B2/K-B3/K-B4. KILLS: skip `record_derived` (K-B4: carried values read as the role's work); carry without the
    contract check; leave a carried field blank (K-B3: the check asks for it); carry a field of the role's own (K-B2)."""
    root = temp_project()
    try:
        art = story(root)
        parent = parent_file(art, S3_PARENT, fixture(S3_PARENT))
        run = init(root, art, S3_ARGS, "S3-qa-test-strategist-2", parent)
        child = "S3-qa-test-strategist-2"
        text = form_path(art, child).read_text(encoding="utf-8")
        doc = handoff.parse(text)
        check_eq("K-B2 exit 0 and the form is written", (run.returncode, form_path(art, child).is_file()), (0, True))
        check_in("K-B2 the output counts the carried fields", f"handoff_init: carried {len(S3_CARRIED)} field(s) from {S3_PARENT}.yaml",
                 run.stdout)
        for path, value in S3_CARRIED.items():
            check_eq(f"K-B2 {path} is the parent's answer", doc.get(path), value)
        marks = derived_fields(doc)
        check_eq("K-B2 one derived: row per carried field, no other", sorted(marks), sorted(S3_CARRIED))
        check("K-B2 every source names the parent form, story-relative", all(s == SOURCE.format(parent=S3_PARENT) for s in marks.values()),
              str(marks))
        check_not_in("K-B2 no absolute path in the form (AR-4)", str(art), text)
        for path in ("scope[0].id", "scope[0].reason", "header.verdict", "claims.no_test_was_run_in_this_stage",
                     "inputs_read[0].version", "inputs_read[1].version"):
            check(f"K-B2 {path} stays a placeholder for the role", handoff.is_placeholder(doc.get(path)), repr(doc.get(path)))
        lines = text.splitlines()
        at = next(n for n, line in enumerate(lines) if line.startswith("# Fill:"))
        check_eq("K-B2 the repair comment is the line right under `# Fill:`", lines[at + 1],
                 f"# Repair of {S3_PARENT}: the fields under derived: carry its accepted answers; fill the rows of this dispatch.")
        check_eq("K-B2 the comment is there once", text.count("# Repair of"), 1)

        # K-B3: the check asks nothing of the carried fields (the versions are measured from the files, as for any form)
        (art / "work").mkdir(exist_ok=True)
        (art / "work" / "requirements-register.md").write_text("register\n", encoding="utf-8")
        (art / "work" / "context-bundle.json").write_text("{}\n", encoding="utf-8")
        mine = handoff.parse(text)
        for path, node in list(mine.nodes.items()):
            if handoff.is_placeholder(node.value) and (path.startswith("scope[0].") or path.startswith("claims.")
                                                       or path == "header.verdict"):
                handoff.set_value(mine, path, "false" if path.startswith("claims.") else "x")
                mine = handoff.parse(mine.text())
        _doc, _fixed, problems, _judged, _derived = H.check(mine, S3, H.Artifacts(art, dispatch=child), fix=True, use_judge=False)
        bad = [p.path for p in problems if p.path.startswith("budget.") or p.path.startswith("inputs_read")]
        check_eq("K-B3 with only scope[0], header.verdict and claims filled, nothing under budget. or inputs_read is asked", bad, [])
        bare = handoff.parse(fill_only(S3, child))
        _doc, _fixed, problems, _judged, _derived = H.check(bare, S3, H.Artifacts(art, dispatch=child), fix=True, use_judge=False)
        asked = {p.path for p in problems}
        check("K-B3 control: the same check on a form WITHOUT the carry asks for the budget and the counts",
              {"budget.size", "budget.cap", "inputs_read[0].requirements"} <= asked, str(sorted(asked))[:300])

        # K-B4: untouched means untouched
        check_eq("K-B4 the carried form, untouched: filled_share is 0", H.filled_share(handoff.parse(text), S3)[0], 0)
        stripped = handoff.parse(text.split("\nderived:")[0] + "\n")
        check("K-B4 control: without the derived: rows the same values WOULD read as filled",
              H.filled_share(stripped, S3)[0] >= len(S3_CARRIED), str(H.filled_share(stripped, S3)))
    finally:
        cleanup(root)


def fill_only(contract: str, dispatch: str) -> str:
    return handoff_init.fill_head((handoff.CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8"), task="QA-1",
                                  dispatch=dispatch, role="qa-test-strategist", stage="S3", scope="")


# ---------------------------------------------------------------------------------------------------- K-B5
def test_a_parent_that_cannot_answer_carries_nothing() -> None:
    """K-B5, adversarial. Every input below must leave the field it breaks ASKED, and the form is still written, exit 0.
    KILLS: carrying a placeholder; ignoring the contract of the parent; carrying a row whose contract-written path differs
    or that the parent does not have; reading a binary file; carrying a list as if it were a scalar."""
    root = temp_project()
    try:
        art = story(root)
        base = pinned(art, fixture(S3_PARENT))
        text = fill_only(S3, "S3-qa-test-strategist-2")

        def carried_by(parent_text: str | bytes | None) -> tuple:
            path = form_path(art, "parent-x")
            if parent_text is None:
                path.unlink(missing_ok=True)
            elif isinstance(parent_text, bytes):
                path.write_bytes(parent_text)
            else:
                path.write_text(parent_text, encoding="utf-8")
            out, note = handoff_init.carry_from_parent(text, S3, path)
            return handoff.parse(out), note, out

        doc, note, out = carried_by(None)
        check_eq("K-B5 parent missing: the text is unchanged", out, text)
        check_in("K-B5 parent missing: the note names it", "carried nothing from parent-x.yaml (the parent form is missing or cannot be read)", note)
        doc, note, out = carried_by(b"\xff\xfe\x00\x81garbage\xc3\x28")
        check_eq("K-B5 garbage bytes: the text is unchanged", out, text)
        check_in("K-B5 garbage bytes: a note", "carried nothing from parent-x.yaml", note)
        doc, note, out = carried_by("this is not a form\nat all: really\n")
        check_eq("K-B5 text that is no form (no contract): unchanged", out, text)
        doc, note, out = carried_by(base.replace(f"contract: {S3}", f"contract: {S4}"))
        check_eq("K-B5 other contract: the text is unchanged", out, text)
        check_in("K-B5 other contract: the note names both", f"is of contract `{S4}`, not `{S3}`", note)

        doc, note, out = carried_by(base.replace("requirements: 11", "requirements: <how many rows the register carries>"))
        check("K-B5 a placeholder in the parent: that field stays asked", handoff.is_placeholder(doc.get("inputs_read[0].requirements")))
        check_eq("K-B5 a placeholder in the parent: the other fields are carried", doc.get("budget.size"), "M")
        check_not_in("K-B5 a placeholder in the parent: no derived row for it", "inputs_read[0].requirements", ",".join(derived_fields(doc)))

        doc, note, out = carried_by(base.replace("path: work/context-bundle.json", "path: work/another-bundle.json"))
        check("K-B5 a row with another contract-written path: not carried", handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))
        check_eq("K-B5 ... and the row that does match is", doc.get("inputs_read[0].requirements"), 11)

        one_row = base.split("  - path: work/context-bundle.json")[0] + "\nheader:" + base.split("\nheader:", 1)[1]
        doc, note, out = carried_by(one_row)
        check("K-B5 the parent has fewer rows: the missing row is asked", handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))
        check_eq("K-B5 ... the common row is carried", doc.get("inputs_read[0].requirements"), 11)

        doc, note, out = carried_by(base.replace("existing_candidates_considered: 4 of 4", "existing_candidates_considered: [1, 2]"))
        check("K-B5 a list where the form asks a count: not carried", handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))

        doc, note, out = carried_by(base.replace("if_over: nothing cut", "if_over: -"))
        check_eq("K-B5 a dash is an answer: carried as a dash", doc.get("budget.if_over"), "-")

        silent = "\n".join(line for line in base.splitlines() if not re.match(r"\s+(requirements|existing_candidates_considered):", line)
                           and not re.match(r"\s+(size|cap|planned_rows|within_cap|if_over):", line)) + "\n"
        doc, note, out = carried_by(silent)
        check_eq("K-B5 a parent that answers none of the listed fields: unchanged", out, text)
        check_in("K-B5 ... and says so", "answers none of the listed fields", note)

        # through the CLI: every broken parent still writes the form, exit 0
        for label, broken in (("missing", None), ("binary", b"\xff\xfe\x00junk")):
            carried_by(broken)
            gone = form_path(art, f"S3-qa-test-strategist-{label}")
            run = init(root, art, S3_ARGS, gone.stem, form_path(art, "parent-x"))
            check_eq(f"K-B5 CLI, parent {label}: exit 0 and the form is written", (run.returncode, gone.is_file()), (0, True))
            check_in(f"K-B5 CLI, parent {label}: the note is printed", "handoff_init: carried nothing from parent-x.yaml", run.stdout)
            check_not_in(f"K-B5 CLI, parent {label}: no derived: in the form", "derived:", gone.read_text(encoding="utf-8"))

        # a contract that lists nothing carries nothing, whatever the parent holds
        out, note = handoff_init.carry_from_parent(text, "s1-scout-to-tester", form_path(art, "parent-x"))
        check_in("K-B5 an unlisted contract: the note says so", "lists no field to carry", note)
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------------- K-B6
def test_s4_designer_rework_and_the_refusal_text_is_unchanged() -> None:
    """K-B6. KILLS: a carry that touches the second row, or the role's rows; an edit of the refusal text of a blank field."""
    root = temp_project()
    try:
        art = story(root)
        parent = parent_file(art, S4_PARENT, fixture(S4_PARENT))
        child, plain = "S4-qa-case-designer-2", "S4-qa-case-designer-3"
        init(root, art, S4_ARGS, child, parent)
        init(root, art, S4_ARGS, plain)
        doc = read(art, child)
        check_eq("K-B6 inputs_read[0].rows is the parent's 3", doc.get("inputs_read[0].rows"), 3)
        check_eq("K-B6 one derived row, for rows only", sorted(derived_fields(doc)), ["inputs_read[0].rows"])
        check("K-B6 inputs_read[1].version stays asked", handoff.is_placeholder(doc.get("inputs_read[1].version")))
        check("K-B6 inputs_read[0].version stays asked", handoff.is_placeholder(doc.get("inputs_read[0].version")))
        check("K-B6 the role's rows are open", handoff.is_placeholder(doc.get("scope[0].id")))
        check_eq("K-B6 inputs_read[1] holds only what the contract wrote", doc.get("inputs_read[1].path"), "work/requirements-register.md")

        def blank_text(dispatch: str) -> str:
            _d, _f, problems, _j, _dr = H.check(read(art, dispatch), S4, H.Artifacts(art, dispatch=dispatch), fix=False, use_judge=False)
            return next(p.text for p in problems if p.path == "review_scope.rounds_used")

        check_eq("K-B6 the refusal of a blank field elsewhere, pinned", blank_text(child), "not filled. how many repair rounds these cases have already had, of the two allowed")
        check_eq("K-B6 ... and identical on a form without the carry", blank_text(plain), blank_text(child))
        after = [p.path for p in H.check(read(art, child), S4, H.Artifacts(art, dispatch=child), fix=False, use_judge=False)[2]]
        check_not_in("K-B6 the carried rows are not among the problems", "inputs_read[0].rows", ",".join(after))
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------------- K-B7
def test_rework_of_a_rework_carries_again() -> None:
    """K-B7. KILLS: a carry that reads only a first-generation form; a source that names the grandparent."""
    root = temp_project()
    try:
        art = story(root)
        parent = parent_file(art, S3_PARENT, fixture(S3_PARENT))
        second, third = "S3-qa-test-strategist-2", "S3-qa-test-strategist-3"
        init(root, art, S3_ARGS, second, parent)
        form_path(art, second).write_text(pinned(art, form_path(art, second).read_text(encoding="utf-8")), encoding="utf-8")
        run = init(root, art, S3_ARGS, third, form_path(art, second))
        doc = read(art, third)
        check_eq("K-B7 exit 0", run.returncode, 0)
        for path, value in S3_CARRIED.items():
            check_eq(f"K-B7 {path} is carried again", doc.get(path), value)
        check("K-B7 the source is the DIRECT parent",
              all(s == SOURCE.format(parent=second) for s in derived_fields(doc).values()) and len(derived_fields(doc)) == len(S3_CARRIED),
              str(derived_fields(doc)))
        check_in("K-B7 the comment names the direct parent", f"# Repair of {second}:", form_path(art, third).read_text(encoding="utf-8"))
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------------- K-B8
SHAPE = re.compile(r"^[a-z_]+(\.[a-z_]+)*$|^[a-z_]+\[\d*\]\.[a-z_]+$")


def test_every_listed_path_is_a_field_the_role_is_asked() -> None:
    """K-B8, the audit of the data. KILLS: a listed path that no template has (it would silently carry nothing); a
    contract-owned field, a header, a scope row or a version in the list (the role's verdict, rows, or a measurement)."""
    block = handoff.index().get("repair_carries")
    check("K-B8 the block is a map", isinstance(block, dict) and bool(block), repr(block)[:200])
    known = {str(row.get("contract")) for row in handoff.index().get("handoffs", [])}
    for contract, paths in (block or {}).items():
        check(f"K-B8 {contract}: a registered contract with a file", contract in known and (handoff.CONTRACTS / f"{contract}.yaml").is_file())
        check_eq(f"K-B8 {contract}: read through the one reader", handoff.repair_carries(contract), tuple(paths))
        template = handoff.template(contract)
        generic = {re.sub(r"\[\d+\]", "[]", p) for p in template.nodes}
        for path in paths:
            check(f"K-B8 {contract}: `{path}` has the shape of a path", bool(SHAPE.match(path)))
            resolves = path in template.nodes or (path in generic)
            check(f"K-B8 {contract}: `{path}` is a field of its template", resolves)
            check(f"K-B8 {contract}: `{path}` is not contract-owned", not handoff.owned_by_contract(path))
            check(f"K-B8 {contract}: `{path}` is not a header, a scope row or a version",
                  not path.startswith("header.") and not path.startswith("scope") and not path.endswith(".version"))
        check_eq(f"K-B8 {contract}: no path twice", len(paths), len(set(paths)))
    # t-1589 F1/F2 (fail before the fix: the S6 entry and S2 `read` were listed)
    check("K-B8 no S6 contract is listed: its counts are per-dispatch", not any(str(c).startswith("s6-") for c in (block or {})))
    check("K-B8 S2 `read` is asked, not carried: it is this role's own reading",
          "inputs_read[].read" not in handoff.repair_carries("s2-tester-to-strategist"))
    check_eq("K-B8 an unlisted contract carries nothing", handoff.repair_carries("s7-analyst-to-automator"), ())
    check_eq("K-B8 an unknown contract carries nothing", handoff.repair_carries("no-such-contract"), ())
    with mock.patch.object(handoff, "index", side_effect=OSError("gone")):
        check_eq("K-B8 an unreadable index carries nothing", handoff.repair_carries(S3), ())
    with mock.patch.object(handoff, "index", return_value={"repair_carries": ["not", "a", "map"]}):
        check_eq("K-B8 a block that is not a map carries nothing", handoff.repair_carries(S3), ())
    with mock.patch.object(handoff, "index", return_value={"repair_carries": {S3: "inputs_read[].rows"}}):
        check_eq("K-B8 a contract whose value is not a list carries nothing", handoff.repair_carries(S3), ())


# ---------------------------------------------------------------------------------------------------- K-B9
def test_materialize_keeps_a_form_that_is_there() -> None:
    """K-B9 (G3): a repair dispatch whose full empty form was written before the change is kept byte for byte by
    `materialize`; a repair dispatch materialized now gets the carried form. KILLS: a materialize that rewrites the form."""
    import test_story_step_materialize as MAT
    root, env, task, _controller = MAT.accepted_s3("qa-carry-")
    try:
        parent = task / "work" / "handoffs" / f"{MAT.PARENT}.yaml"
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.write_text(pinned(task, fixture(S3_PARENT)), encoding="utf-8")
        made, _result = MAT.rework_cli(root, env, task)
        check_eq("K-B9 the rework packet is committed", made.returncode, 0)
        done = MAT.materialize(root, env)
        form = task / "work" / "handoffs" / f"{MAT.CHILD}.yaml"
        check_eq("K-B9 materialize writes the form", (done.returncode, form.is_file()), (0, True))
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        check_eq("K-B9 end to end: the child form carries the parent's requirements count", doc.get("inputs_read[0].requirements"), 11)
        check_eq("K-B9 end to end: and the budget", doc.get("budget.cap"), 10)
        check_in("K-B9 end to end: the derived row names the parent form", SOURCE.format(parent=MAT.PARENT),
                 form.read_text(encoding="utf-8"))
        before = form.read_bytes()
        again = MAT.materialize(root, env)
        check_eq("K-B9 a second materialize keeps the form byte for byte", (again.returncode, form.read_bytes()), (0, before))

        # an OLD full form (written before the change) is kept the same way, and is never carried into
        old = fill_only(S3, MAT.CHILD)
        form.write_text(old, encoding="utf-8")
        third = MAT.materialize(root, env)
        check_eq("K-B9 an old full form is kept, byte for byte", (third.returncode, form.read_text(encoding="utf-8")), (0, old))
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------------- K-B10
def test_a_row_is_carried_only_while_its_input_is_unchanged() -> None:
    """K-B10 (critic t-1587 F3). KILLS: a carry that trusts the parent row though the input changed after it (the register
    edited, the file gone, the parent's version absent or not a measurement); a second version reader; a row without a
    `version` key in its contract that is refused (S2 `handed`)."""
    root = temp_project()
    try:
        art = story(root)
        base = pinned(art, fixture(S3_PARENT))
        text = fill_only(S3, "S3-qa-test-strategist-2")
        path = form_path(art, "parent-x")

        def carried_by(parent_text: str):
            path.write_text(parent_text, encoding="utf-8")
            out, _note = handoff_init.carry_from_parent(text, S3, path)
            return handoff.parse(out)

        doc = carried_by(base)
        check_eq("K-B10 control: both inputs unchanged, both rows carried",
                 (doc.get("inputs_read[0].requirements"), doc.get("inputs_read[1].existing_candidates_considered")), (11, "4 of 4"))
        # round 3: S3 row 0's template version is `<hash or revision>` (role-written), so it is not compared; row 1 is `<hash>`
        register = art / "work" / "requirements-register.md"
        register.write_text("the register was edited after the parent was accepted\n", encoding="utf-8")
        doc = carried_by(base)
        check_eq("K-B10 row 0 (`<hash or revision>`, not measured) is carried though its input changed",
                 doc.get("inputs_read[0].requirements"), 11)
        register.write_text("content of work/requirements-register.md\n", encoding="utf-8")
        gone = art / "work" / "context-bundle.json"
        gone.write_text("the bundle was edited after the parent was accepted\n", encoding="utf-8")
        doc = carried_by(base)
        check("K-B10 `<hash>` input changed: row 1 is asked", handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))
        check_eq("K-B10 ... row 0 is still carried", doc.get("inputs_read[0].requirements"), 11)
        check_eq("K-B10 ... the budget (no row) is still carried", doc.get("budget.cap"), 10)
        gone.write_text("content of work/context-bundle.json\n", encoding="utf-8")
        saved = gone.read_bytes()
        gone.unlink()
        doc = carried_by(base)
        check("K-B10 input unmeasurable now: row 1 is asked", handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))
        check_eq("K-B10 ... row 0 is carried", doc.get("inputs_read[0].requirements"), 11)
        gone.write_bytes(saved)
        no_version = "\n".join(line for line in base.splitlines() if not re.match(r"\s+version: ", line)) + "\n"
        doc = carried_by(no_version)
        check_eq("K-B10 parent without a version: row 0 (not measured) is carried", doc.get("inputs_read[0].requirements"), 11)
        check("K-B10 parent without a version: row 1 is asked", handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))
        doc = carried_by(re.sub(r"version: [0-9a-f]{16}\b", "version: read in full", base))
        check("K-B10 parent version that is not the measurement: row 1 is asked",
              handoff.is_placeholder(doc.get("inputs_read[1].existing_candidates_considered")))

        # a row whose contract has no `version` key: carried as today
        s2 = "s2-tester-to-strategist"
        mine = handoff_init.fill_head((handoff.CONTRACTS / f"{s2}.yaml").read_text(encoding="utf-8"), task="QA-1",
                                      dispatch="S2-qa-code-reader-2", role="qa-code-reader", stage="S2", scope="")
        theirs = handoff.parse(mine)
        handoff.set_value(theirs, "inputs_read[0].handed", 7)
        path.write_text(theirs.text(), encoding="utf-8")
        out, _note = handoff_init.carry_from_parent(mine, s2, path)
        check_eq("K-B10 a row without a version key (S2 handed) is carried with no file on disk",
                 handoff.parse(out).get("inputs_read[0].handed"), 7)
    finally:
        cleanup(root)


# ---------------------------------------------------------------------------------------------------- K-B11
def test_template_text_is_never_carried() -> None:
    """K-B11 (critic t-1587 F4). KILLS: a carry of the template's own text for a path (an embedded `<...>` is not a
    placeholder to `is_placeholder`); a comparison that is a substring test (a real answer that contains it is carried)."""
    mine = handoff.parse(fill_only(S3, "S3-qa-test-strategist-2"))
    target, prompt = "budget.if_over", "nothing cut, see <the plan> for the reason"
    check("K-B11 control: the probe text is not a placeholder to the one check", not handoff.is_placeholder(prompt))
    handoff.set_value(mine, target, prompt)
    mine = handoff.parse(mine.text())

    def with_parent(value, template=None):
        parent = handoff.parse(fill_only(S3, "S3-qa-test-strategist-1"))
        handoff.set_value(parent, target, value)
        doc, carried = handoff_init.carry(handoff.parse(mine.text()), handoff.parse(parent.text()), [target], None, template)
        return doc.get(target), carried

    check_eq("K-B11 the new form's own text for that path is not carried", with_parent(prompt), (prompt, []))
    check_eq("K-B11 ... after the same whitespace strip", with_parent("  " + prompt + "  ")[1], [])
    answer = prompt + " and the owner confirmed it"
    check_eq("K-B11 a value that merely contains the template text is an answer and is carried", with_parent(answer), (answer, [target]))
    other = handoff.parse(fill_only(S3, "S3-qa-test-strategist-3"))
    handoff.set_value(other, target, "the contract template's text")
    other = handoff.parse(other.text())
    check_eq("K-B11 the contract template's text at that path is not carried either",
             with_parent("the contract template's text", other)[1], [])
    check_eq("K-B11 ... and a different text still is", with_parent("something else", other)[1], [target])


# ---------------------------------------------------------------------------------------------------- K-B12
def test_only_a_measured_version_is_compared() -> None:
    """K-B12 (round 3, run 14857). KILLS: a version comparison on a row whose contract version is a role-written revision
    (S4 plan row `<plan_revision>`): its rows count must be carried with the parent's version "2"; a `<hash>` row with a
    stale version is still asked."""
    root = temp_project()
    try:
        art = story(root)
        text = pinned(art, fixture(S4_PARENT))
        text = re.sub(r"(path: work/test-plan\.json\n(?:[ \t]*#[^\n]*\n)*[ \t]+version:)[^\n]*", r"\1 '2'", text, count=1)
        parent = form_path(art, S4_PARENT)
        parent.write_text(text, encoding="utf-8")
        check_in("K-B12 control: the plan row of the parent holds the revision, not a sha", "version: '2'", text)
        init(root, art, S4_ARGS, "S4-qa-case-designer-2", parent)
        doc = read(art, "S4-qa-case-designer-2")
        check_eq("K-B12 S4 plan row with a revision version: rows is carried", doc.get("inputs_read[0].rows"), 3)
        stale = re.sub(r"(path: work/requirements-register\.md\n(?:[ \t]*#[^\n]*\n)*[ \t]+version:)[^\n]*", r"\1 0123456789abcdef", text, count=1)
        parent.write_text(stale, encoding="utf-8")
        init(root, art, S4_ARGS, "S4-qa-case-designer-3", parent)
        check("K-B12 a `<hash>` row with a stale version is still asked (no carried field on that row)",
              handoff.is_placeholder(read(art, "S4-qa-case-designer-3").get("inputs_read[1].version")))
        out, _note = handoff_init.carry_from_parent(fill_only(S3, "S3-qa-test-strategist-2"), S3, _stale_s3(art))
        check("K-B12 S3 `<hash>` row with a stale version is asked",
              handoff.is_placeholder(handoff.parse(out).get("inputs_read[1].existing_candidates_considered")))
    finally:
        cleanup(root)


def _stale_s3(art: Path) -> Path:
    path = form_path(art, "parent-stale")
    path.write_text(re.sub(r"version: [0-9a-f]{16}\b", "version: 0123456789abcdef", pinned(art, fixture(S3_PARENT))), encoding="utf-8")
    return path


def test_the_repair_form_teaches_the_row_form_like_the_first_form() -> None:
    """K15 (HF8-7, AR-19): the form of a rework (`--carry-from`) has the same `# Fill:` line as the first form - one head
    builder - with the indexed row form of its own contract, and the repair comment is still the line right under it."""
    root = temp_project()
    try:
        art = story(root)
        parent = parent_file(art, S3_PARENT, fixture(S3_PARENT))
        init(root, art, S3_ARGS, "S3-qa-test-strategist-2", parent)
        lines = form_path(art, "S3-qa-test-strategist-2").read_text(encoding="utf-8").splitlines()
        at = next(n for n, line in enumerate(lines) if line.startswith("# Fill:"))
        primary = fill_only(S3, "S3-qa-test-strategist-2").splitlines()
        primary_at = next(n for n, line in enumerate(primary) if line.startswith("# Fill:"))
        check_in("K15 the rework's Fill line names the indexed row", 'A row of a list, one line per key: "scope[0].id": <value>, the next row "scope[1].id".',
                 lines[at])
        check_eq("K15 and it is the first form's line, byte for byte", lines[at], primary[primary_at])
        check("K15 the repair comment is still right under it", lines[at + 1].startswith("# Repair of"), lines[at + 1][:80])
        check_eq("K15 one Fill line", sum(1 for line in lines if line.startswith("# Fill:")), 1)
    finally:
        cleanup(root)


def main() -> None:
    test_primary_form_is_unchanged()
    test_the_repair_form_teaches_the_row_form_like_the_first_form()
    test_s3_rework_carries_the_parents_answers()
    test_a_parent_that_cannot_answer_carries_nothing()
    test_s4_designer_rework_and_the_refusal_text_is_unchanged()
    test_rework_of_a_rework_carries_again()
    test_every_listed_path_is_a_field_the_role_is_asked()
    test_materialize_keeps_a_form_that_is_there()
    test_a_row_is_carried_only_while_its_input_is_unchanged()
    test_template_text_is_never_carried()
    test_only_a_measured_version_is_compared()
    finish("test_repair_form_carry")


if __name__ == "__main__":
    main()
