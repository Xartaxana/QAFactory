#!/usr/bin/env python3
"""RN1-2 item 4: an S3 rework form arrives with the ids of the plan rows it was sent for.

The controller's dispatch record names the rows (`plan_rows`); the id of a row is a value code knows, so the strategist is not asked
for it - and the form is no longer refused as "no rows" before any state is written. K-4.1 .. K-4.6 of the spec, as amended.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import handoff  # noqa: E402
import handoff_init  # noqa: E402
import story_step  # noqa: E402

CONTRACT = "s3-strategist-to-designer"
TEXT = (handoff.CONTRACTS / f"{CONTRACT}.yaml").read_text(encoding="utf-8")


def ids_of(text: str) -> list:
    doc = handoff.parse(text)
    out, n = [], 0
    while f"scope[{n}].id" in doc.nodes:
        out.append(doc.get(f"scope[{n}].id"))
        n += 1
    return out


def test_k41_the_ids_arrive_and_are_recorded() -> None:
    written, note = handoff_init.prefill_rows(TEXT, CONTRACT, ["TS-2", "TS-5"])
    check_eq("K-4.1: scope[0].id and scope[1].id are the rows of the dispatch", ids_of(written), ["TS-2", "TS-5"])
    doc = handoff.parse(written)
    derived = [str(row.get("field")) for row in (doc.data.get("derived") or [])]
    check_eq("K-4.1: both are listed under derived:", derived, ["scope[0].id", "scope[1].id"])
    check_in("K-4.1: ...with the dispatch record as their source", "dispatch record", str((doc.data.get("derived") or [{}])[0].get("source")))
    check("K-4.1: nothing else of a row is written: state and reason stay placeholders",
          handoff.is_placeholder(doc.get("scope[0].state")) and handoff.is_placeholder(doc.get("scope[0].reason")),
          str(doc.get("scope[0].state")))
    check_in("K-4.1: the note says how many were written", "wrote 2 row id(s)", note)


def test_k42_no_ids_no_change() -> None:
    for label, ids in (("no ids", []), ("an empty string", [""]), ("blanks", ["  ", ""])):
        written, note = handoff_init.prefill_rows(TEXT, CONTRACT, ids)
        check_eq(f"K-4.2: {label}: the form is byte-identical to the one written without the option", (written, note), (TEXT, ""))
    written, _ = handoff_init.prefill_rows(TEXT, CONTRACT, "--rows ''".split(","))
    check("K-4.2: ...and a junk word is just an id (never a crash)", ids_of(written) == ["--rows ''"])


def test_k43_duplicates_and_order() -> None:
    written, _ = handoff_init.prefill_rows(TEXT, CONTRACT, ["TS-2", " TS-2 ", "TS-9", "TS-2"])
    check_eq("K-4.3: TS-2,TS-2 is one row, the order of first sight is kept", ids_of(written), ["TS-2", "TS-9"])


def test_k44_the_carry_and_the_ids_meet() -> None:
    """RN1-2 m-6: `repair_carries` for this contract lists `inputs_read[]` / `budget.*` and no `scope[]` key, so the order of the carry and
    the prefill is not observable on `scope`; what the form must hold is BOTH - the carried scalars and the ids."""
    base = temp_dir("qa-rn12-carry-")
    try:
        parent = base / "work" / "handoffs" / "S3-qa-test-strategist-1.yaml"
        parent.parent.mkdir(parents=True)
        doc = handoff.parse(TEXT.replace("<TICKET>", "T-1"))
        handoff.set_value(doc, "budget.size", "7")
        handoff.set_value(doc, "inputs_read[0].requirements", "12")
        parent.write_text(doc.text(), encoding="utf-8")
        carried, note = handoff_init.carry_from_parent(TEXT, CONTRACT, parent)
        check_in("K-4.4: the carry carried something", "carried", note)
        written, _ = handoff_init.prefill_rows(carried, CONTRACT, ["TS-2", "TS-5"])
        after = handoff.parse(written)
        check_eq("K-4.4: carried scalars AND prefilled ids stand in one form", (str(after.get("budget.size")), ids_of(written)), ("7", ["TS-2", "TS-5"]))
    finally:
        cleanup(base)


def test_k45_awkward_ids_read_back_equal() -> None:
    written, _ = handoff_init.prefill_rows(TEXT, CONTRACT, ["TS:1", "#9", "<x"])
    check_eq("K-4.5: an id with `:`, one starting with `#` and one starting with `<` are values and read back equal",
             ids_of(written), ["TS:1", "#9", "<x"])
    many, _ = handoff_init.prefill_rows(TEXT, CONTRACT, [f"TS-{n}" for n in range(200)])
    check_eq("K-4.5: 200 ids: no cap", len(ids_of(many)), 200)


def test_k46_story_step_passes_rows_for_an_s3_rework_only() -> None:
    held_run, held_record = story_step._run, story_step._dispatch_record
    seen = []
    story_step._run = lambda *argv: seen.append(list(argv)) or (1, "stopped")
    root = Path("/nowhere")
    try:
        for label, stage, record, want in (
                ("an S3 rework with plan rows", "S3", {"rework_of": "S3-x-1", "plan_rows": ["TS-2", "TS-5"]}, ["--rows", "TS-2,TS-5"]),
                ("an S3 primary dispatch", "S3", {"plan_rows": ["TS-2"]}, None),
                ("an S4 rework", "S4", {"rework_of": "S4-x-1", "plan_rows": ["TS-2"]}, None),
                ("an S3 rework with no plan rows", "S3", {"rework_of": "S3-x-1", "plan_rows": []}, None),
                ("an S3 rework with the key absent", "S3", {"rework_of": "S3-x-1"}, None)):
            seen.clear()
            story_step._dispatch_record = lambda *_a, _r=record: _r
            story_step._handoff_form("T-1", stage, "qa-test-strategist", "S3-qa-test-strategist-2", root, "")
            argv = seen[0] if seen else []
            got = argv[argv.index("--rows"):argv.index("--rows") + 2] if "--rows" in argv else None
            check_eq(f"K-4.6: {label}: the argv {'carries ' + ' '.join(want) if want else 'has no --rows'}", got, want)
    finally:
        story_step._run, story_step._dispatch_record = held_run, held_record


def main() -> None:
    test_k41_the_ids_arrive_and_are_recorded()
    test_k42_no_ids_no_change()
    test_k43_duplicates_and_order()
    test_k44_the_carry_and_the_ids_meet()
    test_k45_awkward_ids_read_back_equal()
    test_k46_story_step_passes_rows_for_an_s3_rework_only()
    finish("test_handoff_rows_prefill")


if __name__ == "__main__":
    main()
