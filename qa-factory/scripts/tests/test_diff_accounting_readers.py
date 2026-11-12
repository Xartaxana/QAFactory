#!/usr/bin/env python3
"""The seven readers of the S2 `diff_accounting` field: a pin of each reader's meaning in BOTH worlds (G1-7, grounding/1).

World BEFORE: the S2 form still carries `diff_accounting[]`, `inputs_read[0].production_files_accounted_for` and the claim
`every_production_file_reaches_a_requirement_or_is_named_not_requirement_bearing`; code opens one row per production file.
World AFTER: G1-16 has switched the carriers (one atomic commit) and the account of the hunks lives in the S3 table.
Every pin branches on the S2 template (`"diff_accounting" in handoff.sections(S2)`) and states something in EACH branch,
so the file is green on both sides of that commit; G1-16 edits only T5's S3 half and its EG catch (t-990 L-4 Q1). A half switch (the section gone, its count,
its claim, its S1 duty or its README words left) is red in either world (`the_switch_is_whole`).

What the readers were, by the trail of G1-7: the S2 field never refused a thing except a blank count, a blank `file` of a
row, and a blank or non-boolean claim - three code refusals; the rows were a SHOW (one per file), the claim a word of the
role with no verifier. A saved S2 form with the old keys is read in both worlds with no refusal on the family's paths
(FR-40); the old key is read, never derived again once the field has left.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script)

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402

S2 = "s2-tester-to-strategist"
S1 = "s1-scout-to-tester"
FORM = "S2-qa-requirements-tester-1.yaml"
COUNT = "inputs_read[0].production_files_accounted_for"
CLAIM = "claims.every_production_file_reaches_a_requirement_or_is_named_not_requirement_bearing"
SAVED_13877 = (FIXTURES / "s2-handoff-13877" / "work" / "handoffs" / FORM).read_text(encoding="utf-8")
READERS_FIXTURE = FIXTURES / "diff-accounting-readers" / "work"
# The form as `handoff_init` wrote it before the switch: one stub row (the shape `_open_rows` copies).
STUB = ('diff_accounting:\n'
        '  - file: <repo-relative path from the diff>\n'
        '    requirements: "<the R-ids it backs, or an empty list>"\n'
        '    not_requirement_bearing: <reason, when the list is empty>\n')
K_A4_ROWS = ["src/app/webhook.py", "src/app/filters.py", "src/app/contest_service.py", "src/app/latest_report.py",
             "Docs/guide.py", "src/main/java/UserSpecs.java", "src/ABTest.java", "api/spec/openapi.py"]


def switched() -> bool:
    """True in the world AFTER: the S2 template no longer carries the section."""
    return "diff_accounting" not in handoff.sections(S2)


def in_family(path: str) -> bool:
    return path.startswith("diff_accounting") or path in (COUNT, CLAIM)


def swapped(text: str, old: str, new: str) -> str:
    """One replacement that must hit: a pin whose edit misses would pass for the wrong reason."""
    if text.count(old) != 1:
        raise AssertionError(f"the pin edits {old!r} and it is found {text.count(old)} times")
    return text.replace(old, new)


def section_of(text: str, key: str = "diff_accounting") -> str:
    """The lines of a top-level section, from `key:` to the next line that starts in column 0 (a comment included)."""
    lines, out, inside = text.split("\n"), [], False
    for line in lines:
        if not inside and re.match(rf"{key}:", line):
            inside = True
            out.append(line)
        elif inside:
            if line.strip() and not line[0].isspace():
                break
            out.append(line)
    return "\n".join(out).rstrip("\n")


class Story:
    """A throwaway story folder: `artifacts/QA-4/work/...`, the form beside the work files."""

    def __init__(self, text: str = "", work: Path | None = None):
        self.root = Path(tempfile.mkdtemp(prefix="qa-readers-"))
        self.art = self.root / "artifacts" / "QA-4"
        (self.art / "work" / "handoffs").mkdir(parents=True)
        if work is not None:
            for item in work.iterdir():
                shutil.copy2(item, self.art / "work" / item.name)
        self.form = self.art / "work" / "handoffs" / FORM
        if text:
            self.form.write_text(text, encoding="utf-8")

    def check(self, text: str | None = None, fix: bool = False) -> tuple:
        """`(report, text_after)` of `handoff_check.py --json --no-judge [--fix]` over the form."""
        if text is not None:
            self.form.write_text(text, encoding="utf-8")
        args = ["--file", self.form, "--task-root", self.art, "--json", "--no-judge"] + (["--fix"] if fix else [])
        done = run_script("handoff_check.py", *args)
        return json.loads(done.stdout), self.form.read_text(encoding="utf-8")

    def init(self) -> str:
        """The S2 form as `handoff_init` writes it TODAY, plus (in the world after) the stub a saved old form still holds."""
        run_script("handoff_init.py", "--task", "QA-4", "--stage", "S2", "--role", "qa-requirements-tester",
                   "--dispatch", "S2-qa-requirements-tester-1", "--task-root", str(self.art))
        text = self.form.read_text(encoding="utf-8")
        if switched():
            text = swapped(text, "\ncontradiction_matrix:", "\n" + STUB + "\ncontradiction_matrix:")
        return text

    def close(self) -> None:
        cleanup(self.root)


def family(report: dict) -> list:
    return [p for p in report["problems"] if in_family(p["path"])]


def paths_of(problems: list) -> list:
    return [p["path"] for p in problems]


def filled_rows(text: str) -> str:
    """The 13877 form with its four accounting rows answered: three requirements and one named not requirement-bearing."""
    out = text
    for answer in ('"R-3"', '"R-4"', '"R-1, R-4"'):
        out = out.replace('requirements: "<the R-ids it backs, or an empty list>"', f"requirements: {answer}", 1)
    out = swapped(out, 'requirements: "<the R-ids it backs, or an empty list>"\n    not_requirement_bearing: <reason, when the list is empty>',
                  'requirements: []\n    not_requirement_bearing: "generated constants, no behaviour"')
    return out


# --------------------------------------------------------------------------------------------------- T1
def a_saved_s2_form_with_diff_accounting_reads() -> None:
    """E1, E2: a saved S2 form (the real 13877 one: a count `6 of 6`, four rows of placeholders, the claim `true`) and the same
    form answered row by row are read with no refusal on the family's paths, before and after the switch (I2, FR-40)."""
    story = Story()
    try:
        report, _ = story.check(SAVED_13877)
        check_eq("T1 the saved 13877 form (placeholders, `6 of 6`, claim true): no refusal on the family's paths",
                 paths_of(family(report)), [])
        control, _ = story.check(swapped(SAVED_13877, "  verdict: ok", "  verdict: <one of vocabulary.header_verdicts>"))
        check("T1 control (same call, same form): a blank OUTSIDE the family is refused, so the call does see refusals",
              "header.verdict" in paths_of(control["problems"]), str(paths_of(control["problems"])))
        answered = filled_rows(SAVED_13877)
        report, _ = story.check(answered)
        check_eq("T1 the form with every accounting row answered: no refusal on the family's paths",
                 paths_of(family(report)), [])
        check_in("T1 the rows were really answered (the pin is not the placeholder case twice)", 'requirements: "R-3"', answered)
    finally:
        story.close()


# --------------------------------------------------------------------------------------------------- T3
def the_s2_accounting_refused_only_three_blanks() -> None:
    """The census of the S2 family's CODE refusals (M-1): a blank count, a blank `file` in a row of a filled section, and a
    blank or non-boolean claim. Everything else the field ever did was a show. After the switch the three are gone with it."""
    story = Story()
    try:
        blank_count = swapped(SAVED_13877, "production_files_accounted_for: 6 of 6", "production_files_accounted_for: <n of m>")
        blank_file = swapped(SAVED_13877, "- file: src/testproject1_tools/data_management/code_executor/default_security_policies.yaml",
                             "- file: <repo-relative path from the diff>")
        claim_line = ("every_production_file_reaches_a_requirement_or_is_named_not_requirement_bearing: true")
        blank_claim = swapped(SAVED_13877, claim_line, claim_line[:-4] + "<true|false>")
        word_claim = swapped(SAVED_13877, claim_line, claim_line[:-4] + "maybe")
        cases = (
            ("a blank count", blank_count, [COUNT], "not filled"),
            ("a blank `file` in a row of a filled section", blank_file, ["diff_accounting[1].file"], "not filled"),
            ("a blank claim", blank_claim, [CLAIM], "not filled"),
            ("a claim that is not true or false", word_claim, [CLAIM], "is not a value of this field"),
        )
        for label, text, expected_paths, words in cases:
            report, _ = story.check(text)
            got = family(report)
            if switched():
                check_eq(f"T3 after the switch, {label}: no refusal (the key is no field of the form)", paths_of(got), [])
            else:
                check_eq(f"T3 before the switch, {label}: exactly one refusal, on its own path", paths_of(got), expected_paths)
                check_in(f"T3 and it says `{words}`", words, got[0]["problem"] if got else "")
        report, _ = story.check(SAVED_13877)
        check_eq("T3 `6 of 6` beside four rows nobody answered and a claim `true`: no refusal in either world (the value was "
                 "never compared with anything: E2, E13)", paths_of(family(report)), [])
        control, _ = story.check(swapped(SAVED_13877, "  size_recorded_in_pipeline: false", "  size_recorded_in_pipeline: <true|false>"))
        check_eq("T3 control (same call over the same form): a blank claim OUTSIDE the family is refused in both worlds",
                 [p["path"] for p in control["problems"] if p["path"].startswith("claims.")], ["claims.size_recorded_in_pipeline"])
        report, _ = story.check(swapped(SAVED_13877, "production_files_accounted_for: 6 of 6", "production_files_accounted_for: 1 of 99"))
        check_eq("T3 a count that contradicts the rows (`1 of 99`) is no refusal either: nothing reads the value",
                 paths_of(family(report)), [])
    finally:
        story.close()


# --------------------------------------------------------------------------------------------------- T2
def an_exited_field_is_read_never_derived() -> None:
    """E3, E4 (B-1): the form as `handoff_init` writes it holds ONE stub row; under `--fix` code opens a row per production
    file before the switch, and after it the section is read as written - never opened again. `[]` opens nothing in either
    world (`_open_rows` copies a first row and `[]` has none), and a form with no section gets none."""
    story = Story(work=READERS_FIXTURE)
    try:
        (story.art / "work" / "context-bundle.json").write_text('{"revision": "r1"}', encoding="utf-8")
        stub_form = story.init()
        check_in("T2 the form holds the stub row (before the switch: as handoff_init wrote it)", STUB, stub_form)
        before = section_of(stub_form)
        report, text = story.check(stub_form, fix=True)
        fixed = " ".join(report["fixed"])
        check_in("T2 control (same call): --fix does derive a field of this form from the story's files, so the `nothing opened` "
                 "lines below are a reading, not a dead call", "inputs_read[1].version", fixed)
        if switched():
            check_eq("T2 after the switch: the saved section is the same bytes under --fix", section_of(text), before)
            check_not_in("T2 after the switch: nothing says rows were opened", "diff_accounting", fixed)
            check_not_in("T2 after the switch: no `derived` record names the field", "diff_accounting[].file", text)
        else:
            doc = handoff.parse(text)
            rows = [doc.get(f"diff_accounting[{i}].file") for i in doc.rows("diff_accounting")]
            check_in("T2 before the switch: code says it opened rows", "diff_accounting", fixed)
            check_eq("T2 before the switch: the first rows are the production files of the diff, in its order (K-A4)",
                     rows[:len(K_A4_ROWS)], K_A4_ROWS)
            check_not_in("T2 and no test file is a row", "tests/test_webhook.py", " ".join(map(str, rows)))
            check_in("T2 and the rows are recorded as the code's word in `derived`", "diff_accounting[].file", text)
        # both worlds: a section with a file in it is nobody's to open
        saved = SAVED_13877
        report, text = story.check(saved, fix=True)
        check_eq("T2 a saved section with files in it is the same bytes under --fix (both worlds)",
                 section_of(text), section_of(saved))
        check_not_in("T2 and code says nothing about rows (both worlds)", "diff_accounting", " ".join(report["fixed"]))
        empty = swapped(stub_form, before, "diff_accounting: []")
        report, text = story.check(empty, fix=True)
        check_eq("T2 `diff_accounting: []` opens no row (both worlds: there is no first row to copy)",
                 section_of(text), "diff_accounting: []")
        check_not_in("T2 and code says nothing (both worlds)", "diff_accounting", " ".join(report["fixed"]))
        absent = swapped(stub_form, before + "\n", "")
        report, text = story.check(absent, fix=True)
        check_not_in("T2 a form with no section gets none (E4, both worlds)", "diff_accounting:", text)
        check_not_in("T2 and code says nothing (E4, both worlds)", "diff_accounting", " ".join(report["fixed"]))
        check_eq("T2 and the absence is no refusal: no problem path starts with `diff_accounting` (E4, both worlds; by prefix, "
                 "not by family(): a fresh form's blank count and claim are refused before the switch)",
                 [p for p in paths_of(report["problems"]) if p.startswith("diff_accounting")], [])
        refused = SAVED_13877.replace("- file: src/testproject1_tools/data_management/code_executor/default_security_policies.yaml",
                                      "- file: <repo-relative path from the diff>", 1)
        control, _ = story.check(refused, fix=True)
        check_eq("T2 control (same call, same --fix): a PRESENT section with a blank `file` IS refused before the switch and "
                 "not after it, so `absent` above is a reading, not a blind call",
                 [p for p in paths_of(control["problems"]) if p.startswith("diff_accounting")],
                 [] if switched() else ["diff_accounting[1].file"])
    finally:
        story.close()


def a_form_with_only_accounting_rows_reads_by_the_current_contract() -> None:
    """E14: `filled` (the share `story_step` reads as touched / untouched) is measured against the contract of the day. A row
    answered in the accounting section counts as one filled field before the switch and as none after it (the rows are no
    field of the form any more; a saved form is never finished again). `handoff_init` itself fills two `path` fields of
    `inputs_read`, so the pin compares the share with and without the answered row."""
    story = Story()
    try:
        fresh = story.init()
        base, _ = story.check(fresh)
        again, _ = story.check(fresh)
        check_eq("E14 control: the same form measured twice has the same share (both worlds)",
                 (again["filled"], again["fields"]), (base["filled"], base["fields"]))
        rows_only = swapped(fresh, "  - file: <repo-relative path from the diff>", "  - file: src/app/webhook.py")
        report, _ = story.check(rows_only)
        check_eq("E14 one accounting row answered adds one filled field before the switch and none after it",
                 report["filled"] - base["filled"], 0 if switched() else 1)
    finally:
        story.close()


# --------------------------------------------------------------------------------------------------- T4
def the_s3_index_holds_every_file_the_s2_rows_named() -> None:
    """The successor's raw material (G1-1's index) holds every file the S2 rows named, and what the rows lost (E8-E11).
    The pins are on the INDEX, not on the old reader: it takes the `a/` side of a header and cuts a path at its first blank."""
    import diff_pass
    import handoff_check as H
    import hooklib
    found = diff_pass.index(READERS_FIXTURE)
    by_path = {f["path"]: f for f in found["files"]}
    check_eq("T4 the fixture is read in full: the index refuses nothing", found["refusals"], [])
    merge = Path(tempfile.mkdtemp(prefix="qa-readers-merge-"))
    try:
        (merge / "impl-diff.txt").write_text("diff --cc f.py\n@@@ -1,2 -1,2 +1,3 @@@\n+x\n", encoding="utf-8")
        check_eq("T4 control (same call): a combined diff IS refused, so `refuses nothing` above is a reading, not a blind call",
                 [r["kind"] for r in diff_pass.index(merge)["refusals"]], ["combined"])
    finally:
        cleanup(merge)
    text = (READERS_FIXTURE / "impl-diff.txt").read_text(encoding="utf-8")
    plain = [a for a, b in re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.M) if a == b]
    check_eq("T4 control: the plain headers of the fixture are 15 files of any kind (13 K-A4, the binary, the new module)",
             len(plain), 15)
    check_eq("T4 every plain file of the diff, tests and docs included, is in the index (E11)",
             sorted(set(plain) - set(by_path)), [])
    story = Story(work=READERS_FIXTURE)
    try:
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(story.root)
            view = H.Artifacts(story.art)
            production = H._production_files(plain, view.config, view)
            check_eq("T4 the files the recogniser keeps as production are all in the index", sorted(set(production) - set(by_path)), [])
            check_eq("T4 and they hold the eight K-A4 rows", sorted(set(K_A4_ROWS) - set(production)), [])
            old_rows = None if switched() else H._diff_files(view, None)[0]
    finally:
        story.close()
    rename = by_path.get("src/app/renamed_name.py", {})
    check_eq("T4 a pure rename sits under its NEW name (the `b/` side) with one pseudo-hunk (E9)",
             ([h.get("pseudo") for h in rename.get("hunks", [])], rename.get("old_path")), (["rename"], "src/app/old_name.py"))
    check("T4 and the pseudo-hunk carries the git header lines (the readers hash and window by it)",
          any("rename to src/app/renamed_name.py" in line for line in (rename.get("hunks") or [{}])[0].get("body", [])))
    check_eq("T4 the old name of the rename is no file of the index", "src/app/old_name.py" in by_path, False)
    check_eq("T4 a binary file carries a pseudo-hunk (E9)",
             [h.get("pseudo") for h in by_path.get("assets/logo.png", {}).get("hunks", [])], ["binary"])
    new = by_path.get("src/app/payload_limit.py", {})
    check_eq("T4 a new module is flagged new and has its hunk", (new.get("new"), len(new.get("hunks", []))), (True, 1))
    limit = by_path.get("src/app/filters.py", {}).get("hunks", [])
    check_eq("T4 a CHANGED module's limit sits in a hunk of its own: two hunks, only the second names the cap",
             ["MAX_PAGE_ITEMS" in "\n".join(h.get("body", [])) for h in limit], [False, True])
    check_eq("T4 a path with a blank is the whole path, not its first word (E10)",
             ("src/my module.py" in by_path, "src/my" in by_path), (True, False))
    work = Path(tempfile.mkdtemp(prefix="qa-readers-tab-"))
    try:
        (work / "impl-diff.txt").write_text(
            "diff --git a/src/my module.py b/src/my module.py\n--- a/src/my module.py\t\n+++ b/src/my module.py\t\n"
            "@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
        tabbed = [f["path"] for f in diff_pass.index(work)["files"]]
        check_eq("T4 and so is the path git writes with a TAB after it on the `+++` line", tabbed, ["src/my module.py"])
    finally:
        cleanup(work)
    second = by_path.get("src/other/second_repo_service.py", {})
    check_eq("T4 the second repository's diff is in the index, named by its repository (E8)",
             (second.get("diff"), second.get("repo")), ("impl-diff-second.txt", "second"))
    if switched():
        check("T4 after the switch the old reader is gone from the rows' code (nothing left that reads one diff by `a/`)",
              "diff_accounting" not in getattr(H, "ROW_DERIVERS", {}))
    else:
        check_eq("T4 before the switch the old reader misses what the index holds: the second repository's file (E8)",
                 "src/other/second_repo_service.py" in old_rows, False)
        check_eq("T4 and it names a rename by its OLD path and cuts the blank path at its first word (the loss the index fixes)",
                 ("src/app/old_name.py" in old_rows, "src/my" in old_rows), (True, True))


# --------------------------------------------------------------------------------------------------- T5
def an_unlabelled_hunk_is_refused_where_s2_was_silent() -> None:
    """Pair (b) of the spec: S2 refused nothing on a file it was shown; the successor refuses a hunk with no label. The S2
    half is pinned on the fixture diff; the S3 half calls G1-4's check (`grounding_table.check`, rule R1) on the table built
    from the same diff (G1-16 completed it with the names G1-4 shipped, t-990 L-4 Q1)."""
    import exit_gate as EG
    import grounding_table as GT
    import hooklib
    import planning_contract as PC
    # "One diff, two catches" (t-990 T5): the S2 gate catches the NEW module, the S3 table catches the CHANGED one. The S2 half
    # is the pure function; the changed module is invisible to it, which is why the S3 half below exists.
    created = EG.new_production_files((READERS_FIXTURE / "impl-diff.txt").read_text(encoding="utf-8"))
    check_in("T5 S2 gate: `exit_gate.new_production_files` holds the new module of the diff (`payload_limit.py`)",
             "src/app/payload_limit.py", created)
    check_not_in("T5 S2 gate: and not the CHANGED module with the cap (`filters.py`: only the S3 table sees it)",
                 "src/app/filters.py", created)
    story = Story(work=READERS_FIXTURE)
    try:
        form = swapped(SAVED_13877, "- file: src/testproject1_tools/data_management/code_executor/ast_security_checker.py",
                       "- file: src/app/filters.py")
        report, _ = story.check(form)
        check_eq("T5 S2 over the fixture diff, a row for `filters.py` (the module with the cap) left as a placeholder: "
                 "no refusal on the family (both worlds)", paths_of(family(report)), [])
        (story.art / "pipeline.json").write_text(json.dumps({"ticket": "QA-4", "stages": {}, "implementation_source": "diff"}),
                                                 encoding="utf-8")
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(story.root)
            table = GT.table_path(story.art)
            GT.write_yaml(table, GT.skeleton(GT.gather(story.art)))
            data = PC.read_grounding(story.art)[0].data
            cap = [h["id"] for h in data["hunks"] if h["file"] == "src/app/filters.py"][1]

            def r1() -> list:
                return [f for f in GT.check(story.art) if f.rule == "R1"]

            total = len(data["hunks"])
            check_eq("T5 S3 control (same call): the fresh skeleton has no label, so R1 counts every hunk of the diff",
                     [f.text.split(" hunks", 1)[0] for f in r1()], [f"{total} of {total}"])
            for row in data["rows"]:
                if row["hunks"] != [cap]:
                    row["label"], row["reason"] = "refactoring", "no behaviour"
            GT.write_yaml(table, data)
            found = r1()
            check_eq("T5 S3 over the same diff, every hunk labelled but the cap of `filters.py`: exactly one R1, for the role",
                     [(f.rule, f.who) for f in found], [("R1", "role")])
            check_in("T5 S3 and it names the id of the cap hunk", cap, found[0].text if found else "")
            check_eq("T5 S3 and no other hunk id", [h["id"] for h in data["hunks"] if h["id"] != cap and h["id"] in found[0].text], [])
            for row in data["rows"]:
                if row["hunks"] == [cap]:
                    row["label"], row["reason"] = "behaviour_change", "the cap is a limit the S2 rows never judged"
            GT.write_yaml(table, data)
            check_eq("T5 S3 with the label `behaviour_change` on the cap hunk, R1 is silent", [f.text for f in r1()], [])
    finally:
        story.close()


# --------------------------------------------------------------------------------------------------- T6
def texts_name_only_what_the_forms_carry() -> None:
    """FR-37, FR-11: no text names a field the form does not carry, and no form carries a field no text names. The switch is
    whole: the section, its count, its claim, the S1 duty addressed to it and the README words stand or fall together."""
    carries = not switched()
    handoffs = PLUGIN_ROOT / "handoffs"
    s2_raw = (handoffs / "s2-tester-to-strategist.yaml").read_text(encoding="utf-8")
    s1_raw = (handoffs / "s1-scout-to-tester.yaml").read_text(encoding="utf-8")
    readme = (handoffs / "README.md").read_text(encoding="utf-8")
    nodes = handoff.template(S2).nodes
    check_eq("T6 the section, its count and its claim leave the S2 form together (a half switch is red in either world)",
             (not switched(), COUNT in nodes, CLAIM in nodes), (carries, carries, carries))
    duty = " ".join(s1_raw.split("expected_of_the_receiver:", 1)[1].split("unresolved:", 1)[0].split())
    check_eq("T6(b) S1 asks S2 to account for each production file only while S2 carries the section",
             "every production file in the diff" in duty, carries)
    check("T6(b) control: the same slice of the S1 form still carries its other duties (it is the right slice)",
          "read every one of the `hunks` above" in duty, duty[:200])
    rows = {line.split("|")[1].strip(): line for line in readme.splitlines() if line.startswith("| `s") and ".yaml`" in line}
    s2_row, s3_row = rows.get("`s2-tester-to-strategist.yaml`", ""), rows.get("`s3-strategist-to-designer.yaml`", "")
    check("T6(a) control: the README has both rows (the pin reads the right lines)", bool(s2_row and s3_row), str(sorted(rows)[:4]))
    check_eq("T6(a) the README's S2 row says `diff accounting` only while S2 carries the section", "diff accounting" in s2_row, carries)
    if switched():
        check_in("T6(a) after the switch the S3 row names the table that took the account", "grounding", s3_row)
        for name, raw in (("S1", s1_raw), ("S2", s2_raw), ("README", readme)):
            check("T6 after the switch the " + name + " text names no field the form lost",
                  not re.search(r"diff_accounting|production_files_accounted_for|diff accounting", raw), name)
    else:
        check_eq("T6(a) before the switch the S3 row does not name the table yet: the S3 half is armed by the S2 switch (t-1046 "
                 "7.1), so a row rewritten while S2 still carries the section is red", "grounding" in s3_row, False)
        for word in ("diff_accounting", "production_files_accounted_for"):
            check_in(f"T6 before the switch the S2 form names `{word}`", word, s2_raw)


def main() -> None:
    a_saved_s2_form_with_diff_accounting_reads()
    an_exited_field_is_read_never_derived()
    a_form_with_only_accounting_rows_reads_by_the_current_contract()
    the_s2_accounting_refused_only_three_blanks()
    the_s3_index_holds_every_file_the_s2_rows_named()
    an_unlabelled_hunk_is_refused_where_s2_was_silent()
    texts_name_only_what_the_forms_carry()
    finish("test_diff_accounting_readers")


if __name__ == "__main__":
    main()
