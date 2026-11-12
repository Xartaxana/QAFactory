#!/usr/bin/env python3
"""TR2-6 (B-4): the one command a role or the conductor writes a form field with, `handoff_check.py --set`.

  * a `--set` of the word the field already reads prints `nothing changed` and leaves the form byte for byte (FR-41);
  * a `--set` of a name that is not a field is exit 1 and names it (FR-1);
  * a real change prints no such line;
  * the command line `references/conductor.md` gives the conductor is taken from the text, filled in and RUN (FR-2):
    `handoff.py fill`, a library with no command line, is named nowhere.

Run on its own: `python -B scripts/tests/test_handoff_set_says_so.py`.
"""
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project)

DISPATCH = "S2-qa-requirements-tester-1"


def _form(root: Path) -> tuple:
    art = root / "artifacts" / "QA-9"
    (art / "work").mkdir(parents=True)
    run_script("handoff_init.py", "--task", "QA-9", "--stage", "S2", "--role", "qa-requirements-tester",
               "--to", "qa-test-strategist", "--dispatch", DISPATCH, "--task-root", str(art))
    return art, art / "work" / "handoffs" / f"{DISPATCH}.yaml"


def _set(art: Path, form: Path, assignment: str):
    done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", "--set", assignment)
    return done.returncode, done.stdout


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def a_set_that_changes_nothing_says_so_and_a_non_field_is_refused() -> None:
    root = temp_project("qa-set-says-so-")
    try:
        art, form = _form(root)
        _set(art, form, "scope[0].reason=because")
        before = _sha(form)
        code, out = _set(art, form, "scope[0].reason=because")
        check_in("TR2-6: the same word says `nothing changed`",
                 "nothing changed: `scope[0].reason` already reads because", out)
        check_eq("TR2-6: the form is untouched", _sha(form), before)
        code, out = _set(art, form, "scope[0].reason=another")
        check_not_in("TR2-6: a real change says nothing of the kind", "nothing changed", out)
        check_in("TR2-6: and it is written", "another", form.read_text(encoding="utf-8"))
        code, out = _set(art, form, "no_such_field=x")
        check_eq("TR2-6: a name that is not a field is exit 1", code, 1)
        check_in("TR2-6: the refusal names it", "`no_such_field` is not a field of", out)
    finally:
        cleanup(root)


def a_placeholder_is_written_and_never_called_unchanged() -> None:
    """Position invariant: `nothing changed` is said only for a word the field can hold; a placeholder typed with
    `--set` is a write as it always was (K-A23), even when the line already reads it."""
    root = temp_project("qa-set-placeholder-")
    try:
        art, form = _form(root)
        _set(art, form, "header.verdict=<one of the above>")
        code, out = _set(art, form, "header.verdict=<one of the above>")
        check_not_in("TR2-6: a placeholder is not `nothing changed`", "nothing changed", out)
        check_eq("TR2-6: and the line holds it", "<one of the above>" in form.read_text(encoding="utf-8"), True)
        _set(art, form, "header.verdict=ok")
        code, out = _set(art, form, "header.verdict=ok")
        check_in("TR2-6: a real word still says it (control)", "nothing changed: `header.verdict` already reads ok", out)
    finally:
        cleanup(root)


def the_command_the_conductor_is_told_exists_and_runs() -> None:
    text = (PLUGIN_ROOT / "references" / "conductor.md").read_text(encoding="utf-8")
    check_not_in("TR2-6: the dead command is gone from conductor.md", "handoff.py fill", text)
    found = re.search(r'`handoff_check\.py --file <form> --set <F>="<word>"`', text)
    check("TR2-6: conductor.md names `handoff_check.py --file <form> --set <F>=\"<word>\"`", bool(found))
    root = temp_project("qa-set-conductor-")
    try:
        art, form = _form(root)
        code, out = _set(art, form, 'scope[0].reason="a word"')
        check_in("TR2-6: the named command runs and writes the word", "a word", form.read_text(encoding="utf-8"))
        check("TR2-6: it ran as a command, not a traceback", "Traceback" not in out)
    finally:
        cleanup(root)


if __name__ == "__main__":
    a_set_that_changes_nothing_says_so_and_a_non_field_is_refused()
    a_placeholder_is_written_and_never_called_unchanged()
    the_command_the_conductor_is_told_exists_and_runs()
    finish("test_handoff_set_says_so")
