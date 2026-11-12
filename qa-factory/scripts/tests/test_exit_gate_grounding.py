#!/usr/bin/env python3
"""exit_gate.grounding_errors: a new production module in the diff must back a derived requirement."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exit_gate  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" - {detail}"))
    fails += 0 if ok else 1


DIFF = ("diff --git a/src/app/filter.py b/src/app/filter.py\nnew file mode 100644\n+++ b/src/app/filter.py\n"
        "diff --git a/src/app/old.py b/src/app/old.py\nindex 1..2\n+++ b/src/app/old.py\n"
        "diff --git a/tests/test_filter.py b/tests/test_filter.py\nnew file mode 100644\n"
        "diff --git a/pyproject.toml b/pyproject.toml\nnew file mode 100644\n"
        "diff --git a/docs/x.md b/docs/x.md\nnew file mode 100644\n")
files = exit_gate.new_production_files(DIFF)
check("new production modules: the created source file only", files == ["src/app/filter.py"], str(files))
check("a changed file, a test, a config and a doc are not new modules",
      all(x not in files for x in ("src/app/old.py", "tests/test_filter.py", "pyproject.toml", "docs/x.md")))
check("no diff -> no modules", exit_gate.new_production_files("") == [])
check("another role is never judged", exit_gate.grounding_errors("qa-scout", "T-1") == [])

# ---- G1-1 census: what the S2 gate demands before and after the one production rule --------------------------------------
# The fixture is a throwaway project with ONE story (QA-G1): a register whose only `derived` row cites `filter.py`, and
# three recorded diffs (`impl-diff.txt`, `impl-diff-ui.txt`, `impl-diff-legacy.txt`: the repository-suffixed names the scout
# writes). Every file of them is NEW. The gate's answer is the list of file names it still demands a requirement for.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import cleanup, mark_project, temp_dir  # noqa: E402
import hooklib  # noqa: E402

REGISTER = ("| id | requirement | source | observable |\n|---|---|---|---|\n"
            "| R-1 | The filter rejects a payload over the limit | derived | diff:src/app/filter.py:3 |\n"
            "| R-2 | The story says the filter exists | story | ticket |\n")


def added(path: str, tab: bool = False) -> str:
    """One NEW file as git writes it (`new file mode`, the /dev/null side, one hunk); a path with a blank carries git's TAB."""
    end = "\t" if tab else ""
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null{end}\n"
            f"+++ b/{path}{end}\n@@ -0,0 +1 @@\n+x\n")


MAIN_DIFF = "".join(added(p) for p in (
    "src/app/filter.py", "src/app/limits.py", "config/settings.yaml", "test/FooTest.java", "src/__tests__/a.test.ts",
    "backend/Tests/XTests.cs", "src/app/test_mode.py", "docs/site/app.py", "docs/db/schema.sql", "docs/x.png",
    "tests/test_filter.py", "pyproject.toml", "docs/x.md", "assets/logo.png")) + added("src/my module.py", tab=True)
UI_DIFF = added("ui/src/Guard.tsx")
LEGACY_DIFF = "--- /dev/null\n+++ b/src/x.py\n@@ -0,0 +1 @@\n+x\n"      # a headerless diff: no `diff --git` line at all


def demanded(diffs: dict, register: str = REGISTER, raw: bool = False, unreadable: str = "") -> list:
    """The names `grounding_errors` still demands a requirement for, in its order ([] when it says nothing); `raw`: the
    error texts as they are. `unreadable` makes a diff of that name a FOLDER (no one can read it as a file, on any OS)."""
    root = temp_dir("qa-eg-census-").resolve()
    try:
        mark_project(root)
        work = root / "qa-factory" / "artifacts" / "QA-G1" / "work"
        work.mkdir(parents=True)
        (work / "requirements-register.md").write_text(register, encoding="utf-8")
        for name, text in diffs.items():
            (work / name).write_text(text, encoding="utf-8")
        if unreadable:
            (work / unreadable).mkdir()
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            errors = exit_gate.grounding_errors("qa-requirements-tester", "QA-G1")
    finally:
        cleanup(root)
    return errors if raw else names_of(errors)


def names_of(errors: list) -> list:
    head, tail = "the implementation adds: ", " - no `derived` row cites it."
    texts = [e for e in errors if head in e]
    return texts[0][texts[0].index(head) + len(head):texts[0].index(tail)].split(", ") if texts else []


CENSUS = {"impl-diff.txt": MAIN_DIFF, "impl-diff-ui.txt": UI_DIFF, "impl-diff-legacy.txt": LEGACY_DIFF}
# The gate on `main` (73d3e0f6), measured by running it on this fixture: new files under `/tests/` and the config/doc
# extensions are not demanded; a code file with a test-looking name, code under `docs/`, a path with a blank and a headerless
# diff are (the last two: the regex never matched them - the gate did not see them at all).
BEFORE = ["ui/src/Guard.tsx", "src/app/limits.py", "test/FooTest.java", "src/__tests__/a.test.ts", "backend/Tests/XTests.cs",
          "src/app/test_mode.py", "docs/site/app.py", "docs/db/schema.sql", "docs/x.png", "assets/logo.png"]
# After the one diff reader and the one production rule (G1-1). Every difference from BEFORE is named here, with its direction:
# - PERMITTED_REMOVALS is the CLOSED set of files that stop being demanded: a new test under a test folder and a non-code
#   file under `docs/`. Nothing else may leave the list; a code file with a test-looking name (`test_mode.py`) or under
#   `docs/` (`site/app.py`, and `db/schema.sql`: a code extension no list of code names, t-1050 F2) stays demanded - the
#   rule errs only toward an extra demand. `docs` is the document/image list, so `docs/x.png` is the one `docs/` removal.
# - ADDED are files the gate did not see at all and now does (a headerless diff, a path with a blank): an extra demand.
PERMITTED_REMOVALS = {"test/FooTest.java", "src/__tests__/a.test.ts", "backend/Tests/XTests.cs", "docs/x.png"}
ADDED = {"src/x.py", "src/my module.py"}
AFTER = ["src/x.py", "ui/src/Guard.tsx", "src/app/limits.py", "src/app/test_mode.py", "docs/site/app.py", "docs/db/schema.sql",
         "assets/logo.png", "src/my module.py"]
after_run = demanded(CENSUS)
check("census (after): the gate demands exactly the AFTER column", after_run == AFTER, str(after_run))
check("census: every file that stopped being demanded is in the CLOSED set of permitted removals (a lost production file "
      "fails here whatever the AFTER column says)", set(BEFORE) - set(after_run) <= PERMITTED_REMOVALS,
      str(sorted(set(BEFORE) - set(after_run) - PERMITTED_REMOVALS)))
check("census: the whole closed set is used (no permission nobody exercises)", set(BEFORE) - set(after_run) == PERMITTED_REMOVALS)
check("census: what is new in the list is only the named extra demands", set(after_run) - set(BEFORE) == ADDED,
      str(sorted(set(after_run) - set(BEFORE))))

# FR-59: a diff nobody can read, and a combined diff, are refusals the gate says - never a silent pass.
bad = demanded({"impl-diff.txt": added("src/app/filter.py")}, raw=True, unreadable="impl-diff-bad.txt")
check("an unreadable impl-diff*.txt is a refusal naming the file, what is expected and the door (FR-1, FR-59)",
      len(bad) == 1 and "impl-diff-bad.txt cannot be read" in bad[0] and "Expected:" in bad[0] and "Do:" in bad[0], str(bad))
merge = demanded({"impl-diff.txt": "diff --cc src/m.py\n@@@ -1,2 -1,2 +1,3 @@@\n+x\n" + added("src/app/limits.py")}, raw=True)
check("a combined diff is refused by name and the other files of the diff are still judged",
      len(merge) == 2 and "src/m.py is listed with no hunks" in merge[0] and "src/app/limits.py" in merge[1], str(merge))
check("no diff is unreadable when all are: the clean census says nothing about unreadable",
      not any("cannot be read" in text for text in demanded(CENSUS, raw=True)))


def site4_the_text_says_what_the_gate_reads() -> None:
    """G1-10 site 4/4b (carried by G1-11): the S2 demand names the glob it reads (K9), the `derived_from` the validator
    refuses next, and the claims check through `C.CLAIM_HEADING`; an unread diff ends with the door that opens (K10)."""
    import contract as C
    import validate_artifacts as VA
    k9 = "Read every hunk of work/impl-diff*.txt (Read with offset/limit, not Grep alone)"
    k10 = ("At the S2 exit the handoff is not read: re-export the diff, or name it in your digest - a person's word passes "
           "this check (FR-4).")
    # (i) a new module no `derived` row cites: the text, with the frame the G1-1 census parses intact
    texts = demanded({"impl-diff.txt": added("src/app/guard.py")}, raw=True)
    text = texts[0] if len(texts) == 1 else ""
    check("site 4 (i): one demand for the new module", len(texts) == 1, str(texts))
    check("site 4 (i): the text holds K9 (the glob the gate reads, FR-37)", k9 in text, text)
    check("site 4 (i): ...and `derived_from`, which the validator refuses next", "`derived_from`" in text, text)
    check("site 4 (i): ...and the claims check through the one carrier C.CLAIM_HEADING", f'"{C.CLAIM_HEADING}"' in text, text)
    check("site 4 (i): the frame is byte-identical (the census parses it)",
          "derives nothing from the new module(s) the implementation adds: src/app/guard.py - no `derived` row cites it." in text, text)
    check("site 4 (i): the old one-file name is gone", "work/impl-diff.txt" not in text, text)
    check("site 4 (i): the census reads the name through the frame", names_of(texts) == ["src/app/guard.py"], str(names_of(texts)))
    # (ii) round trip: what the text asks for is what both checks then accept (a register is judged by the gate AND by VA)
    register = ("---\ntask: QA-G1\ncreated: 2026-10-05\nids: [R-1]\nby_source: {story: 0, derived: 1}\nconfidence: low\n---\n\n"
                "## Register\n\n| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| R-1 | The guard rejects a payload over the limit. | derived | invariant:x | yes |  | diff:src/app/guard.py:3 | blocked-flow |\n\n"
                f"{C.CLAIM_HEADING}\n\n| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n"
                "| R-1 | absent | absent | 413 over the limit | diff:src/app/guard.py:3 | no | Q1 |\n")
    root = temp_dir("qa-eg-site4-").resolve()
    try:
        mark_project(root)
        work = root / "qa-factory" / "artifacts" / "QA-G1" / "work"
        work.mkdir(parents=True)
        (work / "requirements-register.md").write_text(register, encoding="utf-8")
        (work / "impl-diff.txt").write_text(added("src/app/guard.py"), encoding="utf-8")
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            gate = exit_gate.grounding_errors("qa-requirements-tester", "QA-G1")
        va: list = []
        VA.check_register(work / "requirements-register.md", va)
        (work / "requirements-register.md").write_text(register[:register.index(C.CLAIM_HEADING)], encoding="utf-8")
        va_no_claim: list = []
        VA.check_register(work / "requirements-register.md", va_no_claim)
    finally:
        cleanup(root)
    check("site 4 (ii): a `derived` row (invariant:x, empty ac_ref, diff: observable, no matrix row) + a seven-column claim row: "
          "the gate demands nothing", gate == [], str(gate))
    check("site 4 (ii): ...and the register validator raises no error", va == [], str(va))
    check("site 4 (ii) negative control: the same register WITHOUT the claim row is refused by the validator under the heading "
          "the text names", len(va_no_claim) == 1 and C.CLAIM_HEADING in va_no_claim[0], str(va_no_claim))
    # (iii) an unreadable diff ends with the door that works (4b), once; a combined diff gets it too
    bad = demanded({"impl-diff.txt": added("src/app/filter.py")}, raw=True, unreadable="impl-diff-bad.txt")
    check("site 4b (iii): an unreadable diff ends with K10", len(bad) == 1 and bad[0].endswith(k10), str(bad))
    check("site 4b (iii): K10 stands once (no doubled suffix)", len(bad) == 1 and bad[0].count(k10) == 1, str(bad))
    merge = demanded({"impl-diff.txt": "diff --cc src/m.py\n@@@ -1,2 -1,2 +1,3 @@@\n+x\n"}, raw=True)
    check("site 4b (iii): a combined diff's refusal ends with K10 too", len(merge) == 1 and merge[0].endswith(k10), str(merge))
    check("site 4b: a clean census carries no K10", not any(k10 in t for t in demanded(CENSUS, raw=True)))


site4_the_text_says_what_the_gate_reads()

def answered_question_run() -> dict:
    """HF2-7 K6: a story whose answers file holds Q5 (answered `a`) and Q3 (kept open until the report) while the S2 role's
    requirements-readiness.json holds only Q1 and Q3 -> what the exit gate says per role, through the function, through
    `collect_errors` (the one call) and through `scoped_errors` (which hands an error to the stage that lists the file)."""
    import json
    root = temp_dir("qa-eg-answered-").resolve()
    out = {}
    try:
        mark_project(root)
        work = root / "qa-factory" / "artifacts" / "QA-G1" / "work"
        work.mkdir(parents=True)
        rows = [{"id": qid, "question": f"question {qid}?", "severity": "major", "readings": [{"reading": "x"}, {"reading": "y"}]}
                for qid in ("Q1", "Q3")]
        (work / "requirements-readiness.json").write_text(json.dumps({"open_questions": rows}), encoding="utf-8")
        records = [{"kind": "question", "id": "Q5", "status": "answered", "reading": "a", "words": "Q5: a", "by": "person",
                    "where": "S2 stop", "at": "2026-10-26T10:00:00+00:00", "row_hash": "a" * 64},
                   {"kind": "question", "id": "Q3", "status": "deferred_to_report", "words": "Q3: until the report", "by": "person",
                    "where": "S2 stop", "at": "2026-10-26T10:00:01+00:00", "row_hash": "a" * 64}]
        (work / "question-answers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            out["tester"] = exit_gate.answered_question_errors("qa-requirements-tester", "QA-G1")
            out["scout"] = exit_gate.answered_question_errors("qa-scout", "QA-G1")
            out["unnamed"] = exit_gate.answered_question_errors("qa-requirements-tester", "NO-SUCH-STORY")
            out["collected"] = exit_gate.collect_errors("QA-G1")
            out["scoped_s2"] = exit_gate.scoped_errors("qa-requirements-tester", "QA-G1")
            out["scoped_s4"] = exit_gate.scoped_errors("qa-case-designer", "QA-G1")
            (work / "requirements-readiness.json").write_text(json.dumps({"open_questions": rows + [dict(rows[0], id="Q5")]}), encoding="utf-8")
            out["restored"] = exit_gate.answered_question_errors("qa-requirements-tester", "QA-G1")
    finally:
        cleanup(root)
    return out


T6_Q5 = ("requirements-readiness.json: Q5 has an answer recorded at S2 stop (a) but is missing from open_questions: an answered "
         "question stays in the register with its id. Expected: restore the row as it was; the factory reads its status from the answers file.")
ran = answered_question_run()
check("K6 (HF2-7): the S2 role's exit names the answered question whose row is gone, once, in the T6 words (Q3 still has its row)",
      ran["tester"] == [T6_Q5], str(ran["tester"]))
check("K6 (HF2-7): another role is never judged", ran["scout"] == [], str(ran["scout"]))
check("K6 (HF2-7): a task with no folder: nothing to read, nothing said", ran["unnamed"] == [], str(ran["unnamed"]))
check("K6 (HF2-7): collect_errors carries it (the one call)", T6_Q5 in ran["collected"], str(ran["collected"]))
check("K6 (HF2-7): scoped_errors gives it to the stage that lists requirements-readiness.json (S2) and to no other (S4)",
      T6_Q5 in ran["scoped_s2"] and T6_Q5 not in ran["scoped_s4"], str(ran["scoped_s2"]) + str(ran["scoped_s4"]))
check("K6 (HF2-7): the row restored -> the error is gone", ran["restored"] == [], str(ran["restored"]))

check("case identity: another role is never judged", exit_gate.case_identity_errors("qa-scout", "T-1") == [])
import re as _re
check("case identity: the id line is read from the front matter",
      _re.search(exit_gate.CASE_FILE_ID_RE, "---\nid: TP1-1_TC_001\ntitle: x\n---").group(1) == "TP1-1_TC_001")

print(f"\n=== test_exit_gate_grounding: {'ok' if not fails else str(fails) + ' FAILED'} ===")
sys.exit(1 if fails else 0)
