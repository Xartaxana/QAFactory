#!/usr/bin/env python3
"""main block: a part of test_handoff_values.py, split by tools/test_split.py (TD-11c). The shared helpers are in handoff_values_common."""
import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as H  # noqa: E402
from handoff_values_common import DISPATCH, _doc, _form, _form5, _green_copy, _hc, _story  # noqa: E402


# ------------------------------------------------------------------- SC2-14: the output block of `main` (K11-K16)
CUT_REASON = "the assertion compares the response with itself, so it cannot fail for the right reason ok"     # 90 chars


SNAP_FLAGS = {"clean": (), "problems": (), "applied": ("--fix",), "pending": (), "cut": ("--fix", "--shorten")}


# t-443: the three TEXT cells that print the form path (problems, applied, pending) were re-recorded with `\` folded to `/` after `<PATH>`
# (see `_snapshot_text`); the first recording kept the Windows backslashes and so was red on Linux (CI job 28088990). Same lines, same exits.
# t-1765 X1 fix-2: the S2 form gained the `tried` table (B-B), so the clean cell counts one field more and the problems/applied/pending cells
# print one more problem and its four skeleton lines; the six cells below were re-recorded from the run's own text (K11 prints it on a miss).
# The etalon: recorded on the code BEFORE the output block left `main` (SC2-14), as `{kind: {mode: (exit, lines,
# sha256 of the stdout with the temp paths replaced)}}`. The contract of the output is FR-14: story_run.py and
# story_step.py parse this stdout and the last line of it.
SNAP_ETALON = {
    "clean": {"text": (0, 2, "df93812707156e18b859b5601dbfefb7ab844e966d13a4a022c162c3eeb7f6d0"),
              "json": (0, 20, "052f5b4cc7f8ce7b3f8dc1155cdb3050cf3c284a82727d7a3885926158b6d0da")},
    "problems": {"text": (1, 60, "d590f7744403ba4e42616894386fd9cc9ff7105e924a58c11488237aee865816"),
                 # SC2-38 F-2: each problem gained the key `code_fills` (one line each); re-recorded from the run's own text
                 "json": (1, 184, "c66bc0d4fca65e55bcc2757abb4cead8256cb6b719e2465e67f53df40934854f")},
    "applied": {"text": (1, 63, "a3599c6b7eae2dcea3422f7b0f8a5a0d8fe273d6a6a1f059bbaaa9f8b50daa0b"),
                "json": (1, 224, "4b60d733d11da4ed4f35daf758f0a34a7a4150e85d10df79aa9acc470db48d52")},
    "pending": {"text": (1, 63, "e0c585bd6ea0fcc7e3a165cb6d8423210e44ed890f6278b42a34c4447840dc94"),
                "json": (1, 224, "3de579178f38b77e1ed3832afc391ea44e5f3831a48a1d377fc8d8988cdc91c7")},
    # re-recorded at the X7-7 integration (35 to 58 fields) and again at t-1946 (the form gained the `rows_owed_when` block, t-1936 F4; the json cell was already at this value on c75ec3789, the text cell moved with the block)
    "cut": {"text": (0, 2, "5792448a0e31ed43067261f8fcb76b4f631886f5207be92d03df5969bd806d53"),
            "json": (0, 21, "c05e8c260567a8fa65aa560372b88db772a645369a0d398aeed5dacc2d3ceea7")},
}


def _cut_form(art: Path) -> Path:
    """An S5 critic form filled except for one `reason` of 90 characters - over its limit of 80, the sole problem."""
    form = _form5(art, "S5-qa-code-critic-1")
    doc = _doc(form)
    start = doc.nodes["scope[0].id"].line
    end = max(n.end_line for p, n in doc.nodes.items() if p.startswith("scope[0]"))
    doc.lines = doc.lines[:start] + ["  - id: test_one", "    state: approved",
                                     f"    reason: {json.dumps(CUT_REASON)}"] + doc.lines[end + 1:]
    doc = handoff.parse(doc.text())
    for path, value in (("header.verdict", "ok"), ("review.outcome", "approved"),
                        ("review.receipt_ref", "work/windows/x.json"), ("review.rounds_used", 0),
                        ("probes.runtime_provenance", "evidence/runtime-provenance-api.json"),
                        ("probes.records[0].instance", "test_one"),
                        ("probes.records[0].verdict", "intended_failure")):
        handoff.set_value(doc, path, value)
        doc = handoff.parse(doc.text())
    form.write_text(doc.text(), encoding="utf-8")
    return form


def _snap_form(kind: str, art: Path) -> Path:
    if kind == "clean":
        # spec t-1765 X1 B-B: the S2 form now carries `tried`; the fixture predates it, so the clean cell states why the table is empty
        return _green_copy(art)
    if kind == "cut":
        return _cut_form(art)
    form = _form(art)
    if kind in ("applied", "pending"):
        H.sibling_values(form).write_text("scope[0].id: R-1\n", encoding="utf-8")
    return form


def _norm(text: str, *paths: Path) -> str:
    """The stdout with every machine-bound path replaced: the story and the form, and the package (the text answers
    print the script's own path, `python "<package>/scripts/handoff_check.py" ...`, which differs on every checkout)."""
    for path in (*paths, SCRIPTS.parent):
        for needle in (json.dumps(str(path))[1:-1], str(path), path.as_posix()):
            text = text.replace(needle, "<PATH>")
    return text


def _snapshot_text(kind: str, mode: str) -> tuple:
    """`(exit, lines, sha256, normalised stdout)` of one `handoff_check.py` run: the kind of form x the output mode."""
    root = temp_project("qa-values-k11-")
    try:
        art = _story(root)
        form = _snap_form(kind, art)
        flags = list(SNAP_FLAGS[kind]) + (["--json"] if mode == "json" else [])
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", *flags)
        out = _norm(done.stdout, art, form)
        if mode == "text":      # t-443: the text prints the form path raw, so after `<PATH>` a Windows run left `\work\handoffs\x.yaml`
            out = re.sub(r"<PATH>\S*", lambda m: m.group(0).replace("\\", "/"), out)      # and a Linux run `/work/...`: one form for both
        return done.returncode, len(out.splitlines()), hashlib.sha256(out.encode("utf-8")).hexdigest(), out
    finally:
        cleanup(root)


def _snapshot(kind: str, mode: str) -> tuple:
    """`(exit, lines, sha256)` of the normalised stdout (the etalon's shape)."""
    return _snapshot_text(kind, mode)[:3]


def the_output_is_the_etalon_on_every_kind_of_run() -> None:
    """K11: SC2-14, FR-14 - for {clean, problems, values applied, values waiting, `--shorten`} x {text, `--json`} the exit
    code and the whole stdout equal what the code printed before the output block left `main`. Kills mutant 8 in part
    (an output before the write) and any edit that moves a line, a space or a key."""
    for kind in SNAP_FLAGS:
        for mode in ("text", "json"):
            got = _snapshot_text(kind, mode)
            want = SNAP_ETALON.get(kind, {}).get(mode)
            if got[:3] != want:       # a hash tells nothing: show the text that differs (re-record, see SNAP_ETALON)
                print(f"K11 {kind} / {mode}: the normalised stdout was\n{got[3]}\n--- end; if the change is intended, "
                      "re-record the three values of this cell from this text (the code BEFORE the change)")
            check_eq(f"K11: {kind} / {mode}: exit, lines, sha256 of the stdout", got[:3], want)


def the_json_keys_come_in_the_order_the_readers_were_given() -> None:
    """K12: FR-14 - the order of the keys of `--json`, and of a problem's, is the one the readers were written
    against (a reader is not told it changed). Mutant 9 reorders them."""
    root = temp_project("qa-values-k12-")
    try:
        art = _story(root)
        form = _form(art)
        code, report = _hc(art, form, "--json")
        check_eq("K12: the keys of the answer, in order", list(report),
                 ["contract", "fixed", "shortened", "judged", "filled", "fields", "untouched", "no_verdict",
                  "values_applied", "values_pending", "values_notes", "values_skeleton", "problems"])
        check_eq("K12: the keys of a problem, in order", list(report["problems"][0]),
                 ["path", "problem", "fix", "kind", "also", "code_fills"])
    finally:
        cleanup(root)
    root = temp_project("qa-values-k12b-")
    try:
        art = _story(root)
        code, report = _hc(art, _snap_form("cut", art), "--fix", "--shorten", "--json")
        check_eq("K12: the keys of a cut field, in order", list(report["shortened"][0]),
                 ["field", "kept_len", "written_len"])
    finally:
        cleanup(root)


def _main_inproc(argv: list) -> tuple:
    """`(exit, stdout)` of `handoff_check.main` called in this process - for a test that must replace `os.replace`."""
    import contextlib
    import io
    saved, sys.argv = sys.argv, ["handoff_check.py", *argv]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = H.main()
    finally:
        sys.argv = saved
    return code, buf.getvalue()


def a_failed_rename_is_a_problem_in_the_answer_not_a_lost_outcome() -> None:
    """K13: E12 - the file of values was applied but cannot be renamed: the answer carries the problem, `values_pending`
    names the file, `consumed` is gone (the line `applied N value(s)` is not printed), exit 1; the form holds the words.
    Kills mutant 8 (the answer built before the rename)."""
    root = temp_project("qa-values-k13-")
    real = H.os.replace
    try:
        art = _story(root)
        form = _form(art)
        sibling = H.sibling_values(form)
        sibling.write_text("scope[0].id: R-1\n", encoding="utf-8")

        def broken(*_a, **_k):
            raise OSError("locked by another process")

        H.os.replace = broken
        argv = ["--file", str(form), "--task-root", str(art), "--no-judge", "--fix"]
        code, out = _main_inproc(argv + ["--json"])
        report = json.loads(out)
        renamed = [p for p in report["problems"] if p["path"] == sibling.name]
        check_eq("K13: exit 1, the file still waits, the answer names it", (code, report["values_pending"], sibling.is_file()),
                 (1, sibling.name, True))
        check_eq("K13: one problem names the file and the lock", (len(renamed), "locked by another process" in renamed[0]["problem"]),
                 (1, True))
        check_eq("K13: the form holds the words", _doc(form).get("scope[0].id"), "R-1")
        code, out = _main_inproc(argv)
        check_in("K13: the text answer says it too", "could not be renamed", out)
        check_not_in("K13: and does not claim the file was consumed", "it is now", out)
    finally:
        H.os.replace = real
        cleanup(root)


def values_pending_is_empty_once_the_file_is_consumed() -> None:
    """K14: E13 - `values_pending` is the file's name while it waits and `""` once `--fix` consumed it (the
    expression moved unchanged). Kills mutant 10."""
    root = temp_project("qa-values-k14-")
    try:
        art = _story(root)
        form = _form(art)
        sibling = H.sibling_values(form)
        sibling.write_text("scope[0].id: R-1\n", encoding="utf-8")
        code, report = _hc(art, form, "--json")
        check_eq("K14: waiting - the name", report["values_pending"], sibling.name)
        code, report = _hc(art, form, "--fix", "--json")
        check_eq("K14: consumed - empty, and the file was renamed", (report["values_pending"], sibling.is_file(),
                                                                    report["values_applied"]), ("", False, 1))
    finally:
        cleanup(root)


def a_form_that_is_not_utf8_is_refused_whole_and_never_rewritten() -> None:
    """K15: S-2 (a), E15 - a form whose bytes are not UTF-8 is not read with `errors="replace"` (a `--fix` would write the
    replaced text over the role's file): one line, exit 2, the bytes the same, and the door it names works (FR-2).
    Kills mutant 11 (`errors="replace"` in `main`)."""
    root = temp_project("qa-values-k15-")
    try:
        art = _story(root)
        form = _form(art, "S2-qa-requirements-tester-2")      # NOT the default dispatch: the door must name it (F3)
        form.write_bytes(form.read_bytes() + b"\n# a role pasted this: \xff\xfe\xe9\n")
        before = form.read_bytes()
        for flags in ((), ("--fix",), ("--set", "scope[0].id=R-1"), ("--fix", "--shorten")):
            code, out = _hc(art, form, *flags)
            check_eq(f"K15: {flags}: exit 2, one line, the bytes are the same", (code, len(out.splitlines()), form.read_bytes() == before),
                     (2, 1, True))
        check_in("K15: the line says what it is", "not UTF-8", out)
        check_in("K15: and names the door, with the dispatch of this form",
                 f"handoff_init.py --task <T> --stage <S> --role <role> --dispatch {form.stem} --force", out)
        # The door AS PRINTED: its own flags, the placeholders filled, nothing else added but the story root.
        door = out.strip().split("Start it again: handoff_init.py ", 1)[1].split()
        fill = {"<T>": "QA-9", "<S>": "S2", "<role>": "qa-requirements-tester"}
        done = run_script("handoff_init.py", *[fill.get(word, word) for word in door], "--task-root", str(art))
        check_eq("K15: the printed door runs (exit 0)", done.returncode, 0)
        check_eq("K15: and it repaired THIS form, not a default -1 one",
                 (form.read_bytes() != before, (form.parent / f"{DISPATCH}.yaml").exists()), (True, False))
        code, report = _hc(art, form, "--json")
        check_eq("K15: the door works - a fresh form is read again (exit 1: unfilled, not 2)", (code, isinstance(report, dict)),
                 (1, True))
    finally:
        cleanup(root)


def the_not_utf8_answer_is_plain_text_even_with_json() -> None:
    """K16: E16 - with `--json` the same single plain line, exit 2 (as `no such file` and `no contract` answer): the
    caller parses stdout as JSON first and, when that fails, reads the LAST line as the reason (story_step.py,
    story_run.py). Kills mutant 12 (the branch writes JSON)."""
    root = temp_project("qa-values-k16-")
    try:
        art = _story(root)
        form = _form(art)
        form.write_bytes(form.read_bytes() + b"\n# \xff\n")
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", "--json")
        try:
            json.loads(done.stdout)
            parsed = True
        except ValueError:
            parsed = False
        check_eq("K16: exit 2 and stdout is not JSON", (done.returncode, parsed), (2, False))
        last = done.stdout.strip().splitlines()[-1]
        check("K16: the last line is the reason, with the form's name and the door", "not UTF-8" in last and form.name in last
              and "handoff_init.py" in last, last)
    finally:
        cleanup(root)


def the_not_utf8_door_survives_the_drivers_clip_on_a_long_path() -> None:
    """K17: F2, AR-9 - the driver keeps `splitlines()[-1][:200]` of this line (story_run.py), and the door is its tail:
    on the longest role name, a two-digit counter and a story path of 100+ characters the whole line is at most 200
    characters, so the clip cuts nothing and the door stays whole. Kills a line that prints the whole path."""
    root = temp_project("qa-values-k17-")
    try:
        deep = root.joinpath(*(["d" * 20] * 4)) / "QA-9"      # an 80-character directory chain on top of the temp root
        (deep / "work").mkdir(parents=True)
        dispatch = "S2-qa-requirements-tester-12"
        form = _form(deep, dispatch)
        form.write_bytes(form.read_bytes() + b"\n# \xff\n")
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(deep), "--no-judge")
        last = done.stdout.strip().splitlines()[-1]
        check("K17: the form path is over 100 characters", len(str(form)) > 100, str(len(str(form))))
        check_eq("K17: the line fits the driver's clip whole", (len(last) <= 200, last[:200] == last), (True, True))
        check_in("K17: and the door, with the dispatch, is its tail", f"--dispatch {dispatch} --force", last[:200])
    finally:
        cleanup(root)


# split: runner piece 1
if __name__ == "__main__":
    the_output_is_the_etalon_on_every_kind_of_run()
    the_json_keys_come_in_the_order_the_readers_were_given()
    a_failed_rename_is_a_problem_in_the_answer_not_a_lost_outcome()
    values_pending_is_empty_once_the_file_is_consumed()
    a_form_that_is_not_utf8_is_refused_whole_and_never_rewritten()
    the_not_utf8_answer_is_plain_text_even_with_json()
    the_not_utf8_door_survives_the_drivers_clip_on_a_long_path()
    finish("test_handoff_values_main_block")
