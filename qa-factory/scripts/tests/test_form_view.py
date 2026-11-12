#!/usr/bin/env python3
"""A role's waiting values file is seen by every reader of its form (SC1-2 part D, B-1): `handoff_check.form_view`.

The failure behind every key: a role without Bash writes its words to `<dispatch>.values.yaml`, and the form on disk
shows the template's placeholders until the next WRITING `handoff_check` applies the file. Every reader that looked at
the raw form in between - the halt reader of `finish` and of the driver, the digest assembler, the conductor's help,
the repair route - missed a halt, a `blocked` or a critic's findings the role HAD said (the TP2-2406 S3-3 class:
a halt that `finish` recorded as an acceptance). Each test says the one behaviour it pins and what it protects; the keys
are the names K-D* of the spec (t-1243, section 3 part D).
"""
import codecs
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as H  # noqa: E402
import repair_route  # noqa: E402
import story_step  # noqa: E402

S3 = "S3-qa-test-strategist-1"
S5 = "S5-qa-code-critic-1"
S1 = "S1-qa-scout-1"


# ------------------------------------------------------------------------------------------------ scaffolding
def _story(root: Path) -> Path:
    art = root / "artifacts" / "QA-9"
    (art / "work").mkdir(parents=True)
    return art


def _init(art: Path, stage: str, role: str, to: str, dispatch: str) -> Path:
    run_script("handoff_init.py", "--task", "QA-9", "--stage", stage, "--role", role, "--to", to,
               "--dispatch", dispatch, "--task-root", str(art))
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


def _s3(art: Path) -> Path:
    return _init(art, "S3", "qa-test-strategist", "qa-case-designer", S3)


def _s5(art: Path) -> Path:
    return _init(art, "S5", "qa-code-critic", "qa-automator", S5)


def _s1(art: Path) -> Path:
    return _init(art, "S1", "qa-scout", "qa-requirements-tester", S1)


def _neighbor(form: Path, text: str) -> Path:
    path = H.sibling_values(form)
    path.write_text(text, encoding="utf-8")
    return path


def _rel(art: Path, form: Path) -> str:
    return str(form.relative_to(art)).replace("\\", "/")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set(form: Path, path: str, word: str) -> None:
    """The form on disk says `path: word` itself (what a role with Bash, or an `Edit`, wrote there)."""
    text = form.read_text(encoding="utf-8")
    doc = handoff.parse(text)
    handoff.set_value(doc, path, word)
    form.write_text(doc.text(), encoding="utf-8")


HALT_VALUES = ("header.verdict: halt\nblocked.field: scope[0].state\n"
               "blocked.problem: the stand is down and the plan cannot be proved\n")


# ---------------------------------------------------------------------------------------------------- the keys
def a_halt_written_only_in_the_values_file_is_heard() -> None:
    """K-D1: the strategist's `header.verdict: halt` lives only in `<dispatch>.values.yaml`. `finish`'s halt gate names
    the form and the driver's early read (`_declared_halt`) is true; without the file neither is. KILLS: a halt reader
    that reads the raw form."""
    root = temp_project("qa-view-d1-")
    try:
        art = _story(root)
        form = _s3(art)
        rel = _rel(art, form)
        args = SimpleNamespace(dispatch_id=S3, digest="", task="QA-9")
        dispatch = {"role": "qa-test-strategist", "stage": "S3"}
        refusal, _note = story_step._halt_gate(args, art, dispatch, {})
        check_eq("K-D1 control: no waiting file - no refusal", refusal, "")
        check_eq("K-D1 control: no waiting file - the driver hears no halt", story_step._declared_halt(art, rel, ""), "")
        _neighbor(form, HALT_VALUES)
        check_in("K-D1: the form on disk still shows the placeholder", "<one of vocabulary.header_verdicts",
                 form.read_text(encoding="utf-8"))
        refusal, _note = story_step._halt_gate(args, art, dispatch, {})
        check_in("K-D1: finish's halt gate refuses and names the form", "declared a halt in the handover form", refusal)
        check_eq("K-D1: the driver's early halt (story_run `_declared_halt(task_root, form_rel, \"\")`) is true",
                 story_step._declared_halt(art, rel, ""), "the handover form (header.verdict: halt)")
        check_eq("K-D1: and the structured half says the word", story_step._form_halt_word(art, rel), "halt")
    finally:
        cleanup(root)


def the_later_word_wins_in_the_view() -> None:
    """K-D2: the form says `halt`, the file says `ok` -> `ok`, no halt (the later word of the role; C13). The form says
    `ok`, the file says `halt` -> `halt`. KILLS: a view that lets the form's word win over the file's."""
    root = temp_project("qa-view-d2-")
    try:
        art = _story(root)
        form = _s3(art)
        rel = _rel(art, form)
        _set(form, "header.verdict", "halt")
        _neighbor(form, "header.verdict: ok\n")
        check_eq("K-D2: form halt + file ok - the view says ok", H.form_view(form).get("header.verdict"), "ok")
        check_eq("K-D2: and no halt is heard", story_step._form_halt_word(art, rel), "")
        _set(form, "header.verdict", "ok")
        _neighbor(form, "header.verdict: halt\n")
        check_eq("K-D2: form ok + file halt - the view says halt", H.form_view(form).get("header.verdict"), "halt")
        check_eq("K-D2: and the halt is heard", story_step._form_halt_word(art, rel), "halt")
        _neighbor(form, 'header.verdict: "Halt "\n')
        check_eq("K-D2: `\"Halt \"` is heard as before (strip/lower)", story_step._form_halt_word(art, rel), "Halt")
    finally:
        cleanup(root)


def the_view_is_what_fix_writes() -> None:
    """K-D3: for every path of the file, the view's value equals the value in the form AFTER `--fix` applied the file
    (read back from disk). KILLS: a second applier - a view that differs from what the next writing run records."""
    root = temp_project("qa-view-d3-")
    try:
        art = _story(root)
        form = _s3(art)
        text = HALT_VALUES + "blocked.tried: [ran the stand check, asked the conductor]\n"      # a list among the words
        path = form.parent / f"{S3}.values.yaml"
        path.write_bytes(("﻿" + text.replace("\n", "\r\n")).encode("utf-8"))         # BOM and CRLF, the unhandy bytes
        pairs, bad = H.parse_values(path.read_bytes().decode("utf-8-sig"))
        check_eq("K-D3: the file parses (BOM and CRLF are accepted)", (len(pairs), bad), (4, []))
        view = H.form_view(form)
        seen = {name: view.get(name) for name, _v, _n, _r in pairs}
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", "--fix")
        check("K-D3: --fix ran and consumed the file", not path.exists() and "applied 4 value(s)" in done.stdout, done.stdout[-400:])
        after = handoff.parse(form.read_text(encoding="utf-8"))
        for name, _v, _n, _r in pairs:
            check_eq(f"K-D3: `{name}` in the view == in the form after --fix", seen[name], after.get(name))
        check_eq("K-D3: the halt is among them", seen["header.verdict"], "halt")
    finally:
        cleanup(root)


def a_form_with_a_bom_is_read_by_fix_as_the_view_reads_it() -> None:
    """K-D3b (Q-5): a form that begins with a BOM (a tool of the person's saved it so) is read by `handoff_check --fix` as
    `form_view` reads it: the BOM is no part of the first line. KILLS: `main` reading the form strictly as utf-8, under which
    the view says one thing and the next writing run records another."""
    root = temp_project("qa-view-d3b-")
    try:
        art = _story(root)
        form = _s3(art)
        rows = form.read_text(encoding="utf-8").splitlines(keepends=True)
        first = [row for row in rows if row.startswith("contract:")]
        check_eq("K-D3b scaffold: the form names its contract on one line", len(first), 1)
        # the BOM sits before `contract:` itself: a strict read makes the key `<BOM>contract` and the form names no contract
        form.write_bytes(codecs.BOM_UTF8 + "".join(first + [row for row in rows if row not in first]).encode("utf-8"))
        _neighbor(form, HALT_VALUES)
        view = H.form_view(form)
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", "--fix", "--json")
        check("K-D3b: --fix reads the BOM form (it names its contract)", done.stdout.startswith("{"), done.stdout[-300:])
        report = json.loads(done.stdout) if done.stdout.startswith("{") else {}
        check_eq("K-D3b: --fix applies the file of a BOM form", report.get("values_applied"), 3)
        after = handoff.parse(form.read_text(encoding="utf-8-sig"))
        for name in ("header.verdict", "blocked.field", "blocked.problem", "contract", "header.role"):
            check_eq(f"K-D3b: `{name}` in the view == in the BOM form after --fix", view.get(name), after.get(name))
        check_eq("K-D3b: the halt is among them", after.get("header.verdict"), "halt")
    finally:
        cleanup(root)


def a_values_file_that_does_not_parse_leaves_the_raw_form_and_fix_refuses_it() -> None:
    """K-D4: one broken line beside `header.verdict: halt` -> the view is the RAW form (nothing of the file is applied),
    the halt is not heard from it, and `--fix` refuses the form with the line's number and leaves the file in place -
    so `finish` does not pass the form over a file nobody could read. KILLS: a view that applies a file with problems."""
    root = temp_project("qa-view-d4-")
    try:
        art = _story(root)
        form = _s3(art)
        raw = form.read_text(encoding="utf-8")
        path = _neighbor(form, "header.verdict: halt\nthis line is not a path value pair\n")
        check_eq("K-D4: the view is the raw form", H.form_view(form).text(), handoff.parse(raw).text())
        check_eq("K-D4: so nothing is heard from the unparsed file", story_step._form_halt_word(art, _rel(art, form)), "")
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", "--fix", "--json")
        report = json.loads(done.stdout)
        named = [p["path"] for p in report["problems"] if p["path"].startswith(path.name)]
        check_eq("K-D4: --fix refuses with the parse problem, by file and line", named, [f"{path.name} line 2"])
        check_eq("K-D4: exit 1", done.returncode, 1)
        check("K-D4: the file stays where it is (nothing was consumed)", path.is_file() and not
              path.with_name(f"{form.stem}.values.applied.yaml").exists())
        check_eq("K-D4: and the form was not changed by the unparsed file", form.read_text(encoding="utf-8"), raw)
        _neighbor(form, "")
        check_eq("K-D4 edge: an empty file is the raw form", H.form_view(form).text(), handoff.parse(raw).text())
        _neighbor(form, "# only a comment\n")
        check_eq("K-D4 edge: a file of comments is the raw form", H.form_view(form).text(), handoff.parse(raw).text())
        path.write_bytes(b"header.verdict: halt\n\xff\xfe broken bytes \x80\n")
        check_eq("K-D4 edge: bytes that are not UTF-8 are the raw form (--fix refuses them the same way)",
                 H.form_view(form).text(), handoff.parse(raw).text())
    finally:
        cleanup(root)


def a_failure_on_the_values_side_never_hides_the_form() -> None:
    """K-D5: the applier raising gives the raw form, and the halt the RAW form carries is still heard (the file says
    `ok`; had the view failed closed the halt would vanish). KILLS: a view that lets a values-side exception through, or
    returns less than the raw form."""
    root = temp_project("qa-view-d5-")
    try:
        art = _story(root)
        form = _s3(art)
        rel = _rel(art, form)
        _set(form, "header.verdict", "halt")
        _neighbor(form, "header.verdict: ok\n")
        raw = handoff.parse(form.read_text(encoding="utf-8")).text()
        with mock.patch.object(H, "apply_values", side_effect=RuntimeError("the applier broke")):
            check_eq("K-D5: the applier raises - the view is the raw form", H.form_view(form).text(), raw)
            check_eq("K-D5: and the halt of the raw form is heard", story_step._form_halt_word(art, rel), "halt")
        with mock.patch.object(H, "parse_values", side_effect=ValueError("the reader broke")):
            check_eq("K-D5: the values reader raises - the raw form", H.form_view(form).text(), raw)
        form.write_text(raw.replace("contract: s3-strategist-to-designer", "contract: no-such-contract"), encoding="utf-8")
        check_eq("K-D5: a contract nobody can read - the raw form",
                 H.form_view(form).get("header.verdict"), "halt")
        form.write_text(raw.replace("contract: s3-strategist-to-designer\n", ""), encoding="utf-8")
        check_eq("K-D5: a form that names no contract - the raw form", H.form_view(form).get("header.verdict"), "halt")
    finally:
        cleanup(root)


def an_import_that_fails_still_reads_the_raw_halt() -> None:
    """K-D5b: `handoff_check` cannot be imported -> `_form_halt_word` reads the raw form the old way. A halt is never
    'not there' because an import failed (E10). KILLS: a reader whose only path is the view."""
    root = temp_project("qa-view-d5b-")
    try:
        art = _story(root)
        form = _s3(art)
        rel = _rel(art, form)
        _set(form, "header.verdict", "halt")
        with mock.patch.dict(sys.modules, {"handoff_check": None}):
            check_eq("K-D5b: the import fails - the halt of the raw form is read", story_step._form_halt_word(art, rel), "halt")
    finally:
        cleanup(root)


def form_view_writes_nothing() -> None:
    """K-D6: the form and the waiting file are byte-identical after any number of views, the file is not renamed and
    the directory holds the same names. KILLS: a view that applies to disk (`--fix`, `os.replace`)."""
    root = temp_project("qa-view-d6-")
    try:
        art = _story(root)
        form = _s3(art)
        path = _neighbor(form, HALT_VALUES)
        names = sorted(p.name for p in form.parent.iterdir())
        before = (_sha(form), _sha(path))
        for _ in range(2):
            H.form_view(form)
            story_step._form_halt_word(art, _rel(art, form))
        check_eq("K-D6: the hashes of the form and the file are unchanged", (_sha(form), _sha(path)), before)
        check_eq("K-D6: the directory holds the same names (no .values.applied.yaml)",
                 sorted(p.name for p in form.parent.iterdir()), names)
        check_not_in("K-D6: no applied trace", ".values.applied.yaml", "\n".join(names))
    finally:
        cleanup(root)


def the_repair_route_reads_the_critics_pending_findings() -> None:
    """K-D7: the code critic's findings sit only in its values file -> `repair_route.findings(read_form(F))` names them;
    with no form the reader says None. KILLS: `read_form` reading the raw form (the route would close a window the
    critic sent back)."""
    root = temp_project("qa-view-d7-")
    try:
        art = _story(root)
        form = _s5(art)
        check_eq("K-D7 control: no waiting file - no finding", repair_route.findings(repair_route.read_form(form)), [])
        _neighbor(form, "findings[0].id: F-7\nfindings[0].problem: the assertion never fires\n"
                        "findings[0].cause: test_defect\nfindings[0].blocking: true\n")
        found = repair_route.findings(repair_route.read_form(form))
        check_eq("K-D7: the pending finding is read", [(f["id"], f["cause"], f["blocking"]) for f in found],
                 [("F-7", "test_defect", True)])
        check_eq("K-D7: no form - None", repair_route.read_form(art / "work" / "handoffs" / "nowhere.yaml"), None)
    finally:
        cleanup(root)


def the_conductors_help_reads_blocked_from_the_values_file() -> None:
    """K-D8: `blocked` is empty in the form and written in the file -> the help request carries the file's field and
    problem (exit 0; no judge is configured in a temp root). KILLS: `handoff_help.main` reading the raw form."""
    root = temp_project("qa-view-d8-")
    try:
        art = _story(root)
        form = _s3(art)
        _neighbor(form, "blocked.field: scope[0].state\nblocked.problem: the stand answers 503\n")
        done = run_script("handoff_help.py", "--file", str(form), "--json")
        check_eq("K-D8: exit 0", done.returncode, 0)
        request = json.loads(done.stdout)["request"]
        check_eq("K-D8: the field is the file's", request["field"], "scope[0].state")
        check_eq("K-D8: so is the problem", request["problem"], "the stand answers 503")
        _neighbor(form, "﻿")
        (form.parent / f"{S3}.help.yaml").unlink(missing_ok=True)
        done = run_script("handoff_help.py", "--file", str(form), "--json")
        check("K-D8 control: no words anywhere - the old refusal (exit 2)", done.returncode == 2, done.stdout[-300:])
    finally:
        cleanup(root)


def the_digest_is_assembled_from_the_view() -> None:
    """K-D9: the scout's header verdict and one row are only in its values file -> `assemble_digest` builds the digest
    (the reason is NOT 'the form's header is not filled'); without the file it says so. KILLS: `assemble_digest` reading
    the raw form."""
    import story_run
    root = temp_project("qa-view-d9-")
    try:
        art = _story(root)
        form = _s1(art)
        (art / "work" / "context-bundle.json").write_text("{}", encoding="utf-8")
        driver = object.__new__(story_run.Driver)
        driver.task_root, driver.project = art, root
        message = {"result": "scouted the sources"}
        digest, why = driver.assemble_digest("qa-scout", "S1", S1, message)
        check_eq("K-D9 control: no waiting file - nothing is assembled", digest, "")
        check_in("K-D9 control: because the header is not filled", "the form's header is not filled", why)
        _neighbor(form, "header.verdict: ok\nscope[0].id: SRC-1\nscope[0].state: found\nscope[0].reason: the task itself\n")
        digest, why = driver.assemble_digest("qa-scout", "S1", S1, message)
        check_not_in("K-D9: the reason is not the unfilled header", "header is not filled", why)
        check_eq("K-D9: the digest is the role's own words from the file",
                 digest, "qa-scout S1 QA-9 · ok\nSRC-1 · found · the task itself\nwork/context-bundle.json\nassembled_by: code")
    finally:
        cleanup(root)


def _conductor_driver(root: Path, art: Path, prompts: list):
    """A `Driver` with only what `conductor` and `written_outputs` touch; every prompt the conductor is given lands in `prompts`."""
    import story_run
    driver = object.__new__(story_run.Driver)
    driver.task_root, driver.project, driver.plugin = art, root, PLUGIN_ROOT
    driver.boundary, driver.conductor_calls, driver.model, driver.task = f"S3:{S3}", {}, "sonnet", "QA-9"
    driver.flags = SimpleNamespace(branch_suffix="")
    driver.step = lambda *args: "where: S3"
    driver.stand_remedy = lambda: "none"
    driver.journal_conductor = lambda **kw: None

    def run_claude(kind, prompt, **kw):
        prompts.append(prompt)
        return {"result": '{"action": "stop"}', "session_id": "s", "total_cost_usd": 0, "num_turns": 1}
    driver.run_claude = run_claude
    return driver


def the_conductor_is_shown_the_waiting_values_file() -> None:
    """K-D10 (F9 a): the files of the boundary `conductor` shows, and the outputs `written_outputs` lists, include
    `<dispatch>.values.yaml` when it exists. KILLS: a conductor that decides a halt without the words it is about."""
    root = temp_project("qa-view-d10-")
    try:
        art = _story(root)
        form = _s3(art)
        _neighbor(form, HALT_VALUES)
        prompts = []
        driver = _conductor_driver(root, art, prompts)
        driver.conductor("the strategist halted")
        check_in("K-D10: the conductor is shown the waiting values file (its path and its words)",
                 f"{S3}.values.yaml ---", prompts[0])
        check_in("K-D10: with the words the role said", "the stand is down and the plan cannot be proved", prompts[0])
        outputs = driver.written_outputs("qa-test-strategist", "S3", S3)
        check_in("K-D10: written_outputs lists the waiting file", f"work/handoffs/{S3}.values.yaml (", outputs)
        H.sibling_values(form).unlink()
        check_not_in("K-D10 control: no file - not listed", ".values.yaml", driver.written_outputs("qa-test-strategist", "S3", S3))
    finally:
        cleanup(root)


def the_form_stays_in_the_conductors_window_when_the_refusal_brings_files() -> None:
    """K-D10b (D-1): the window is CONDUCTOR_FILES long and the boundary's files (help, form, values) come BEFORE the files
    the refusal brings: with 0, 1 or 2 files of its own, with or without a help file, the FORM is in view. KILLS: the refusal's
    files first, or the order (help, values, form): either fills the window and the form is the file left out."""
    root = temp_project("qa-view-d10b-")
    try:
        art = _story(root)
        form = _s3(art)
        _neighbor(form, HALT_VALUES)
        own = []
        for number in (1, 2):
            own.append(art / "work" / f"refusal-file-{number}.txt")
            own[-1].write_text(f"what the refusal names, {number}\n", encoding="utf-8")
        helpfile = H.sibling_help(form)
        check_eq("K-D10b the help file is named by the one helper", helpfile.name, f"{S3}.help.yaml")
        helpfile.write_text("help: the conductor's help\n", encoding="utf-8")
        shown = {"form": f"{S3}.yaml ---", "values": f"{S3}.values.yaml ---", "help": f"{S3}.help.yaml ---",
                 "file 1": "refusal-file-1.txt ---", "file 2": "refusal-file-2.txt ---"}
        for label, files, with_help, expect_in, expect_out in (
                ("no file of its own", [], True, ("help", "form", "values"), ()),
                ("one file of its own", own[:1], True, ("help", "form", "values"), ("file 1",)),
                ("two files of its own and a help", own, True, ("help", "form", "values"), ("file 1", "file 2")),
                ("two files of its own, no help", own, False, ("form", "values", "file 1"), ("help", "file 2"))):
            if not with_help and helpfile.exists():
                helpfile.unlink()
            prompts = []
            _conductor_driver(root, art, prompts).conductor("the strategist halted", files=files)
            for key in expect_in:
                check_in(f"K-D10b {label}: the {key} is in the window", shown[key], prompts[0])
            for key in expect_out:
                check_not_in(f"K-D10b {label}: the {key} gave way", shown[key], prompts[0])
    finally:
        cleanup(root)


def the_name_of_the_waiting_file_is_the_one_rule() -> None:
    """K-D10c (Q-1): `conductor` and `written_outputs` name the waiting words' file by `handoff_check.sibling_values`, not
    by a spelling of their own. KILLS: an f-string `<dispatch>.values.yaml` in `story_run`: when the rule gives another
    name, the f-string copy looks for a file that is not the one `--fix` reads."""
    root = temp_project("qa-view-d10c-")
    try:
        art = _story(root)
        form = _s3(art)
        other = form.with_name(f"{S3}.words.yaml")
        other.write_text("header.verdict: halt\nblocked.problem: words of the other name\n", encoding="utf-8")
        prompts = []
        driver = _conductor_driver(root, art, prompts)
        with mock.patch.object(H, "sibling_values", lambda path: Path(path).with_name(f"{Path(path).stem}.words.yaml")):
            driver.conductor("the strategist halted")
            outputs = driver.written_outputs("qa-test-strategist", "S3", S3)
        check_in("K-D10c: the conductor is shown the file the rule names", f"{S3}.words.yaml ---", prompts[0])
        check_in("K-D10c: written_outputs lists the file the rule names", f"work/handoffs/{S3}.words.yaml (", outputs)
    finally:
        cleanup(root)


if __name__ == "__main__":
    a_halt_written_only_in_the_values_file_is_heard()
    the_later_word_wins_in_the_view()
    the_view_is_what_fix_writes()
    a_form_with_a_bom_is_read_by_fix_as_the_view_reads_it()
    a_values_file_that_does_not_parse_leaves_the_raw_form_and_fix_refuses_it()
    a_failure_on_the_values_side_never_hides_the_form()
    an_import_that_fails_still_reads_the_raw_halt()
    form_view_writes_nothing()
    the_repair_route_reads_the_critics_pending_findings()
    the_conductors_help_reads_blocked_from_the_values_file()
    the_digest_is_assembled_from_the_view()
    the_conductor_is_shown_the_waiting_values_file()
    the_form_stays_in_the_conductors_window_when_the_refusal_brings_files()
    the_name_of_the_waiting_file_is_the_one_rule()
    finish("test_form_view")
