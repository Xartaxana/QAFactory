#!/usr/bin/env python3
"""What a role writes after its digest's path line is kept whole, never dropped (t-1685 N3-2).

On run LOCAL-1 six of ten gate blocks were digest-form refusals, and the roles' "Notes for the conductor" lines
carried two real findings that no refusal kept. `role_digest.file_notes` writes the tail, as written, to
`state/findings/<dispatch>-digest-notes.md`; the form lines are judged by `check` alone.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import exit_gate as gate  # noqa: E402
import role_digest as RD  # noqa: E402
from test_exit_gate_digest_fix import Env, TICKET, LIVE, GOOD, _record  # noqa: E402

FORM = ["qa-case-designer S4 window 1 · ok",
        "TC-005 · created · written to the plan row",
        "work/test-cases/cart/"]
TAIL = ("Notes for the conductor:\r\n"
        "- Q1 versus Q2: the register has only Q1, plan rows TS-12 and TS-13 name Q2.\r\n"
        "\r\n"
        "```\nbasis `consistency:` is outside the critic's list\n```\n")


def message(lines, tail="") -> str:
    return "\n".join(lines) + "\n" + tail


def d1_notes_are_written_byte_for_byte() -> None:
    text = message(FORM, TAIL)
    check_eq("D1: the form passes on its own lines, the notes do not change the verdict", RD.check(text, ["TC-005"]), [])
    with tempfile.TemporaryDirectory() as tmp:
        rel = RD.file_notes(tmp, "S4-qa-case-designer-2", text)
        check_eq("D1: the digest can name the task-relative path", rel, "state/findings/S4-qa-case-designer-2-digest-notes.md")
        got = (Path(tmp) / rel).read_bytes()
        check_eq("D1: the file holds the tail byte-for-byte (line endings, fence, blank line)", got, TAIL.encode("utf-8"))
    named = RD.with_notes_line(message(FORM), "state/findings/x-digest-notes.md")
    check_eq("D1: the accepted digest names the file as its last line", named.splitlines()[-1],
             "notes: state/findings/x-digest-notes.md")
    check_eq("D1: and is still in the form", RD.check(named, ["TC-005"]), [])
    check_eq("D1: no path, the digest is returned as it was", RD.with_notes_line("abc", ""), "abc")


def d2_notes_only_is_refused_with_the_form_quoted() -> None:
    text = "Notes for the conductor: Q1 versus Q2.\nwork/test-cases/cart/\nmore prose"
    errors = RD.check(text, ["TC-005"])
    check("D2: no form line, refused", bool(errors))
    check_in("D2: the refusal quotes the form (FR-1)", "one row per", RD.refusal("qa-case-designer", errors))
    with tempfile.TemporaryDirectory() as tmp:
        # no header = no form: the lines after a path are notes only of a form that parsed
        check_eq("D2: a message with no form line leaves no notes file", RD.file_notes(tmp, "S4-z-1", text), "")


def d3_a_wrong_state_is_still_refused_and_the_notes_are_still_written() -> None:
    wrong = ["qa-case-designer S4 window 1 · ok", "TC-005 · created/updated · done", "work/test-cases/cart/"]
    text = message(wrong, TAIL)
    errors = RD.check(text, ["TC-005"])
    check_in("D3: refused for the state word", "is not a state of the form", " ".join(errors))
    with tempfile.TemporaryDirectory() as tmp:
        rel = RD.file_notes(tmp, "S4-qa-case-designer-3", text)
        check("D3: and the notes are written all the same", bool(rel) and (Path(tmp) / rel).read_bytes() == TAIL.encode("utf-8"))


def d4_an_empty_tail_makes_no_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for name, tail in (("nothing", ""), ("blank lines", "\n\n  \n"), ("an empty fence", "```\n```\n")):
            rel = RD.file_notes(tmp, "S4-x-1", message(FORM, tail))
            check_eq(f"D4: {name} after the path -> no file", rel, "")
        check_eq("D4: and the folder holds nothing", sorted(p.name for p in Path(tmp).rglob("*") if p.is_file()), [])
        check_eq("D4: a dispatch id that is a path is not a file name", RD.file_notes(tmp, "../x", message(FORM, TAIL)), "")
        check_eq("D4: an empty dispatch id writes nothing", RD.file_notes(tmp, "", message(FORM, TAIL)), "")


def d5_a_row_shaped_tail_stays_a_note() -> None:
    """The existing pin (test_role_digest.py: a row-shaped line after the path is a note, never a second row) wins over
    the spec's edge line "a tail that looks like a form line is judged as one": the item still has no line of its own."""
    text = message(FORM, "TC-009 · created · afterthought\n")
    check_in("D5: the item it names still has no line of its own", "TC-009", " ".join(RD.check(text, ["TC-009"])))
    with tempfile.TemporaryDirectory() as tmp:
        rel = RD.file_notes(tmp, "S4-y-1", text)
        check_eq("D5: and the line is kept in the notes file", (Path(tmp) / rel).read_text(encoding="utf-8"),
                 "TC-009 · created · afterthought\n")


def gate_errors(env, digest) -> list:
    with contextlib.redirect_stderr(io.StringIO()):
        return gate.digest_errors("qa-automator", TICKET, digest)


def g1_the_gate_keeps_the_notes_of_a_refused_and_of_an_accepted_digest() -> None:
    notes = "Notes for the conductor: Q1 versus Q2.\n"
    rel = f"state/findings/{LIVE}-digest-notes.md"
    env = Env({LIVE: _record(LIVE)})
    try:
        errors = gate_errors(env, GOOD.replace("green", "created/updated") + "\n" + notes)
        check_eq("G1: a refused digest with notes is refused once", len(errors), 1)
        check_in("G1: the refusal text names the notes file", rel, errors[0])
        check_eq("G1: and the file holds the notes whole", (env.task / rel).read_text(encoding="utf-8"), notes)
        (env.task / rel).unlink()
        check_eq("G1: an accepted digest is no error", gate_errors(env, GOOD + "\n" + notes), [])
        check_eq("G1: its notes are written", (env.task / rel).read_text(encoding="utf-8"), notes)
        check_eq("G1: and the filed digest names them as its last line", env.filed().splitlines()[-1], "notes: " + rel)
        (env.task / rel).unlink()
        check_eq("G1: no tail -> no file, the filed digest is the digest", (gate_errors(env, GOOD), env.filed(), (env.task / rel).exists()),
                 ([], GOOD, False))
    finally:
        env.close()
    two = Env({LIVE: _record(LIVE), "S5-qa-automator-2": _record("S5-qa-automator-2")})
    try:
        errors = gate_errors(two, GOOD.replace("green", "created/updated") + "\n" + notes)
        check("G1: with two live dispatches there is no file and the refusal does not name one",
              not (two.task / "state" / "findings").exists() and "digest-notes" not in errors[0])
    finally:
        two.close()


def main() -> None:
    d1_notes_are_written_byte_for_byte()
    d2_notes_only_is_refused_with_the_form_quoted()
    d3_a_wrong_state_is_still_refused_and_the_notes_are_still_written()
    d4_an_empty_tail_makes_no_file()
    d5_a_row_shaped_tail_stays_a_note()
    g1_the_gate_keeps_the_notes_of_a_refused_and_of_an_accepted_digest()
    finish("test_role_digest_notes")


if __name__ == "__main__":
    main()
