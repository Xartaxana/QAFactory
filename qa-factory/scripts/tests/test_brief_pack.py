#!/usr/bin/env python3
"""brief_pack.py, the one line it adds to story_step's prompt, the guard rule that keeps a
role out of the plugin, and the S5 window size key.

What is proved:
  * `story_step start` writes work/briefs/<ID>.md and the prompt names it in one line; a
    brief_pack failure is a printed note and the start still succeeds;
  * an S5 automator brief carries the scope, the case files with sizes, the P3/P4 commands
    with their exact argument shapes, run_suite --mine/--request/--detail, s5_precheck,
    manifest_put, the person's gate-A words and the S5 waivers, the repo map link and the
    rule; it stays under 6 KB even when the person's words alone are 10 KB, and the full
    words then live in a linked side file;
  * judge off: no judge_* command in any card;
  * the guard refuses a role's Read/Grep/Glob inside the plugin (scripts, skills, agents),
    lets references/ through, lets the orchestrator through, and lets Bash `--help` through;
  * `execution.s5_window_cases` sizes the non-UI window, the old key and default stand
    otherwise; both scripts are registered in audit_factory's CLI_SCRIPTS;
  * t-1027 (CX1-7): the brief of a role whose lifecycle slice carries "Before the first write" (today the
    automator) has a `Branch check:` line (the recorded checkout, the implementation commit, the manifest's branch
    named for what it is), in every state of the record and the manifest, right after `Scope:` and before any
    repair line, with no git call; the charter and the lifecycle text say the same words;
  * HF2-7 part 4: the brief reads the answers file through `question_register.answers_for_brief` (a line per decided
    question, the words whole or by reference, once for the same words; a breakage line only for a broken line, a line
    that is no object or an unreadable file) and a halt is open by `resolved`, as `archive_task` reads it.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import contract as C  # noqa: E402
import hooklib  # noqa: E402
import human_text  # noqa: E402
import question_register as QR  # noqa: E402
import story_step  # noqa: E402
import test_question_register as TQR  # noqa: E402  (the F-12586 register and its words, as part 1 built them)
import test_repo_base  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT

CASE = """---
id: {cid}
title: {title}
area: coupon
task: QA-9
plan_row: {row}
---

## Given
- A `coupon` created through `CouponUtils.create_coupon(limit=1)`.

## When
Call `CouponUtils.apply_coupon(order, coupon)`.

## Then
1. The `discount` is zero.
"""


def seed(root: Path, ticket: str) -> Path:
    task = root / "qa-factory/artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": ticket, "size": "S", "environment": "local", "implementation_source": "diff",
         "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    return task


def seed_story_for_s5(task: Path, root: Path, gate_words: str) -> None:
    """A story that stands before S5: digests, gate A, a warning, a waiver, cases, a manifest."""
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["stages"].update({
        "S1": {"status": "done", "digest": "qa-scout S1 QA-9 · ok · two sources · work/context-manifest.json"},
        "S2": {"status": "done", "digest": "qa-requirements-tester S2 QA-9 · ok · 3 requirements · understanding.md"},
        "S3": {"status": "done", "digest": "qa-test-strategist S3 QA-9 · ok · 2 rows · test-plan.md"},
        "S4": {"status": "done", "digest": "qa-case-critic S4 QA-9 · ok · 2 cases approved · work/test-cases/"},
    })
    pipeline["gates"] = {"A": {"gate": "A", "status": "approved", "authorization_source": gate_words}}
    pipeline["warnings"] = ["tracker_write: no - never write to Jira on this run"]
    pipeline["stage_overrides"] = [
        {"stage": "S5", "match": "vcs-1: uncommitted changes", "decision": "go on, on this branch as-is", "by": "human"},
        {"stage": "S1", "match": "source gap", "decision": "accept the gap", "by": "human"},
    ]
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    cases = task / "work/test-cases/coupon"
    cases.mkdir(parents=True, exist_ok=True)
    (cases / "TC-001.md").write_text(CASE.format(cid="TC-001", title="limit", row="TS-1"), encoding="utf-8")
    (cases / "TC-002.md").write_text(CASE.format(cid="TC-002", title="reuse", row="TS-2"), encoding="utf-8")
    (task / "test-plan.md").write_text("# plan\n\n| id |\n|---|\n| TS-1 |\n| TS-2 |\n" + "x" * 40000, encoding="utf-8")
    (task / "work/context-bundle.json").write_text("{}", encoding="utf-8")
    (task / "state").mkdir(exist_ok=True)
    (task / "state/story-case-links.json").write_text(json.dumps({"schema_version": 2, "links": []}), encoding="utf-8")
    (task / "state/controller.json").write_text(json.dumps({
        "scope": ["TC-001", "TC-002"], "revision": 3,
        "dispatches": {
            "S4-qa-case-critic-1": {"id": "S4-qa-case-critic-1", "stage": "S4", "role": "qa-case-critic",
                                    "status": "accepted", "scope": ["TC-001"], "returned_digest": "critic ok"},
            "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                                  "status": "running", "scope": ["TC-001", "TC-002"],
                                  "read_first": ["work/s5-notes.md"]},
        }}), encoding="utf-8")
    (task / "work/s5-notes.md").write_text("- the stand needs COUPON_ENV\n", encoding="utf-8")
    (task / "work/automation-manifest.json").write_text(json.dumps({
        "tests": [{"case": "TC-001", "covers": ["TC-001"], "file": "tests/coupon/test_coupon.py",
                   "instance_id": "test_limit"}], "unresolved": []}), encoding="utf-8")
    tests = root / "tests" / "coupon"
    tests.mkdir(parents=True, exist_ok=True)
    (root / "tests" / "conftest.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef coupon_session(client):\n    yield client\n", encoding="utf-8")
    (tests / "test_coupon.py").write_text("def test_limit(coupon_session):\n    assert True\n", encoding="utf-8")


def hook(root: Path, event: dict):
    """(exit code, stderr) of guard_pre_tool.py fed one PreToolUse event, as hooks.json runs it."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    payload = dict({"hook_event_name": "PreToolUse", "session_id": "brief-guard-test", "cwd": str(root)}, **event)
    proc = subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "guard_pre_tool.py")],
                          input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)
    return proc.returncode, proc.stderr


def set_config(root: Path, **blocks) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for key, value in blocks.items():
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# --- B-194: the tests changed after a red run, handed to the code critic in the head ---------------
#
# Every fixture is synthetic. A pair is a function that FAILED in attempt r1 and PASSED in attempt g1
# with another code sha in between (the detector, `s5_precheck.expectation_changes`, finds it; this
# file only reads what the brief says of it). An orphan is red in r1 and named by no test file now.

CRITIC = "S5-qa-code-critic-1"
LINE_START = "Tests changed after a red run"
UNMEASURED_START = "whether tests were changed after a red run could not be measured:"
TEST_FILE = "tests/coupon/test_coupon.py"


def fn_name(i: int) -> str:
    return f"test_case_{i:02d}"


def fn_key(name: str) -> str:
    return "test_coupon." + name


def register_critic(task: Path) -> None:
    path = task / "state/controller.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["dispatches"][CRITIC] = {"id": CRITIC, "stage": "S5", "role": "qa-code-critic",
                                   "status": "running", "scope": ["TC-001", "TC-002"]}
    path.write_text(json.dumps(state), encoding="utf-8")


def run_row(name: str, status: str, sha: str) -> dict:
    return {"instance_id": f"{name}[p]", "test_id": f"pkg.tests.test_coupon::{name}[p]",
            "status": status, "reason": "", "report_matched": True,
            "case_version_links": [{"case_id": "TC-001", "version": "cv"}], "instance_code_sha": sha}


def write_block(task: Path, name: str, attempt: str, minute: int, status: str, rows: list) -> None:
    folder = task / "work/run-blocks"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps({
        "schema_version": 2, "block_id": attempt, "attempt_id": attempt,
        "attempt_started_at": f"2026-09-30T05:{minute:02d}:00+00:00", "dispatch_id": "S5-qa-automator-1",
        "purpose": "repair_verify", "source_fingerprint": {"test_content_sha": "F"},
        "execution_status": status, "results": rows, "evidence": []}), encoding="utf-8")


def seed_changes(task: Path, changed: list, gone: list = (), judged: dict | None = None,
                 extra_tests: list = ()) -> None:
    """`changed`: functions red in r1, green in g1 on another body. `gone`: red in r1, named by no
    test file now. `judged`: {function: verdict} - the manifest carries a record with that verdict."""
    names = list(changed) + list(gone)
    write_block(task, "20260930T050000000000Z-r1.json", "r1", 0, "failed",
                [run_row(n, "failed", "old") for n in names])
    write_block(task, "20260930T051000000000Z-g1.json", "g1", 10, "passed",
                [run_row(n, "passed", "new") for n in changed])
    manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
    manifest["tests"] = [{"case": "TC-001", "covers": ["TC-001"], "file": TEST_FILE,
                          "instance_id": f"{n}[p]", "test_function": n} for n in names + list(extra_tests)]
    records = []
    for name, verdict in (judged or {}).items():
        record = {"function": fn_key(name), "red_attempt": "r1",
                  "green_attempt": None if name in gone else "g1",
                  "then_refs": [{"case": "TC-001", "then": 1}], "what_changed": "x", "reason": "y"}
        if verdict:
            record["critic_verdict"] = verdict
        records.append(record)
    manifest.pop("expectation_changes", None)  # the records of an earlier seed are not this one's
    if records:
        manifest["expectation_changes"] = records
    (task / "work/automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def critic_brief(role: str = "qa-code-critic", stage: str = "S5", dispatch: str = CRITIC) -> dict:
    return brief_pack.build("QA-9", stage, role, dispatch, write=False)


def line_of(text: str, start: str) -> str:
    return next((ln for ln in text.splitlines() if ln.startswith(start)), "")


def lines_of(text: str) -> list:
    """Every changed-test line of a brief, in the order the brief prints them."""
    return [ln for ln in text.splitlines() if ln.startswith(LINE_START)]


WORD_DECISION = "the person lets the test stand"  # the `decision` of the S5 words these tests record


def tree_hash(task: Path) -> dict:
    import hashlib
    return {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(task.rglob("*")) if p.is_file()}


def left_out_sources() -> None:
    """B-231 P5: what the person left out before the run is never handed on as material, the cap of eight is
    applied AFTER that skip, the roles that get material are told what was left out, and the ticket snapshot's
    own links that match are named as left out. `source_material` itself had no test (M7 of t-172)."""
    import source_exclusions as SE
    root = harness.temp_project("qa-brief-left-out-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        work = task / "work"
        folder = work / "sources" / "SRC-1"
        folder.mkdir(parents=True)
        reader = "qa-requirements-tester"           # one of MATERIAL_READERS

        # --- no_record_unchanged: no list, no line, the same eight
        for n in range(1, 10):
            (folder / f"mr-{n}.md").write_text(f"digest {n}", encoding="utf-8")
        before = brief_pack.source_material("QA-9", task, reader)
        check_eq("no_record_unchanged: nine files, the cap of eight, no left-out line", len(before), 8)
        check_not_in("no_record_unchanged: no word about a list", "Left out by the person", "\n".join(before))
        check_eq("no_record_unchanged: a role that gets no material gets nothing",
                 brief_pack.source_material("QA-9", task, "qa-scout"), [])

        # --- the list: testproject1-ui!1924, whose digest is the FIRST file in sort order, and a second word
        text = ("testproject1-ui!1924 - Draft MR of an earlier factory run, not a product change\n"
                "TP1-13289 - a ticket the person does not want\n")
        entries, problems = SE.parse_bytes(text.encode("utf-8"), "QA-9")
        check_eq("the fixture list parses clean", problems, [])
        SE.write_record(task, entries, "list.txt", text.encode("utf-8"))
        (folder / "mr-0.md").write_text("an excluded digest", encoding="utf-8")
        (folder / "mr-0.json").write_text("{}", encoding="utf-8")
        (work / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": [{
            "source_id": "SRC-1", "materials": {"external_media": {"status": "read", "items": [
                {"url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924", "status": "excluded",
                 "local_ref": "sources/SRC-1/mr-0.json"}]}}}]}), encoding="utf-8")
        lines = brief_pack.source_material("QA-9", task, reader)
        material = [ln for ln in lines if "collected" in ln]
        told = [ln for ln in lines if ln.startswith("- Left out by the person's word before the run")]
        check("excluded_material_not_in_brief: neither the digest nor the receipt of the excluded item is handed on",
              not any("mr-0." in ln for ln in lines), str(lines))
        check_eq("excluded_material_not_in_brief: the cap of eight is applied AFTER the skip - nine real files, eight lines, "
                 "the excluded file took no slot", [ln.split("/")[-1].split(" ")[0] for ln in material],
                 [f"mr-{n}.md" for n in range(1, 9)])
        check_eq("left_out_line_for_readers: one line per word, before the material", len(told), 2)
        check_in("left_out_line_for_readers: the word as written and the reason", 'testproject1-ui!1924 ("Draft MR of an earlier factory run',
                 told[0])
        check_in("left_out_line_for_readers: the edge-6 sentence (a requirement only through it is an open question)",
                 "name it as an open question for the person", told[0])
        check("left_out_line_for_readers: the lines come first, so a trimmed brief drops material before them",
              lines[:2] == told, str(lines[:3]))
        check_eq("left_out_line_for_readers: a role that gets no material gets no line",
                 brief_pack.source_material("QA-9", task, "qa-scout"), [])
        shutil_roles = [r for r in brief_pack.MATERIAL_READERS]
        check("left_out_line_for_readers: every role that reads material is told",
              all(len(brief_pack.source_material("QA-9", task, r)) >= 2 for r in shutil_roles), str(shutil_roles))
        (work / "sources" / "SRC-1" / "mr-1.md").unlink()
        for n in range(2, 10):
            (folder / f"mr-{n}.md").unlink()
        only = brief_pack.source_material("QA-9", task, reader)
        check_eq("with only the excluded file on disk the brief holds the left-out lines and no material", only, told)

        # --- a record that exists and cannot be read is a line, never "no list"
        SE.record_path(work).write_text("{not json", encoding="utf-8")
        broken = brief_pack.source_material("QA-9", task, reader)
        check("an unreadable record shows as a line that says so", len(broken) == 1 and "cannot be read" in broken[0], str(broken))
        SE.record_path(work).write_text(json.dumps({"schema_version": 1, "list_file": "list.txt", "exclusions": [
            dict(e, id=f"X{n}", origin="person_before_run", revoked_at=None) for n, e in enumerate(
                [{"as_written": x["as_written"], "target": x["target"], "reason": x["reason"]} for x in entries], 1)]}),
            encoding="utf-8")

        # --- the snapshot's own links (C7): the scout reads it first and its `links.merge_request` is "the ticket's MR"
        snapshot = {"key": "QA-9", "links": {
            "merge_request": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924", "branch": None,
            "issue_links": [], "remote_links": [
                {"title": "Draft MR", "url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"},
                {"title": "Real MR", "url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1881"}]}}
        (work / "ticket-snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        masks = brief_pack.snapshot_mask_lines(task)
        check_eq("snapshot: the matching link is named once (the merge_request and the remote link are the same URL)",
                 len(masks), 1)
        check_in("snapshot: with the person's words", "left out by the person's word before the run", masks[0])
        check_in("snapshot: and that it is not the ticket's merge request", "not \"the ticket's merge request\"", masks[0])
        check_not_in("snapshot: the link nobody left out is not masked", "1881", "\n".join(masks))
        built = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)
        listed = built["markdown"].splitlines()
        at = next(i for i, ln in enumerate(listed) if "work/ticket-snapshot.json" in ln and "(" in ln)
        check("snapshot: in the scout's brief the mask stands right under the snapshot's own line",
              "left out by the person's word" in listed[at + 1], "\n".join(listed[at:at + 3]))
        check_eq("snapshot: the file itself is untouched (its hash is the story's source_revision)",
                 json.loads((work / "ticket-snapshot.json").read_text(encoding="utf-8")), snapshot)
        (work / "ticket-snapshot.json").write_text(json.dumps({"key": "QA-9", "links": {
            "merge_request": "feature/qa-1", "remote_links": [{"url": "https://x.example/other"}]}}), encoding="utf-8")
        check_eq("snapshot: nothing matches, nothing is said (a bare branch name is a value like any other)",
                 brief_pack.snapshot_mask_lines(task), [])
        (work / "ticket-snapshot.json").write_text("not json", encoding="utf-8")
        check_eq("snapshot: an unreadable snapshot masks nothing and breaks nothing", brief_pack.snapshot_mask_lines(task), [])
    finally:
        harness.cleanup(root)


def reference_gap_lines() -> None:
    """t-278 (B3): what the story's text points at and nobody read is said in the scout's brief, next to the person's
    exclusions: one line per `work/ticket-references.json` row whose status is not `fetched`, `<ref> - <status>: <why>`, at
    most 20 and then `+K more`. A story whose S0 ran before the file existed is briefed as it always was (temporal)."""
    root = harness.temp_project("qa-brief-references-")
    em = chr(0x2014)
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        work = task / "work"
        (work / "ticket-snapshot.json").write_text(json.dumps({"key": "QA-9", "links": {}}), encoding="utf-8")
        check_eq("temporal: no references file, no lines", brief_pack.reference_gap_lines(task), [])
        before = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)["markdown"]
        check_not_in("temporal: nor in the brief", "ticket-references.json", before)
        file = "- work/ticket-references.json: "
        rows = [{"ref": "QA-100", "kind": "ticket", "origins": ["field:parent"], "status": "fetched"},
                {"ref": "QA-101", "kind": "ticket", "origins": ["mention:summary"], "status": "not_fetched:not read yet"},
                {"ref": "~/Projects/x/app", "kind": "local_path", "origins": ["mention:description"], "status": "not_fetched:local path mention"},
                {"ref": "!1924", "kind": "merge_request", "origins": ["mention:comment:15923998"], "status": "person"},
                {"ref": "QA-102", "kind": "ticket", "origins": []}]
        path = work / "ticket-references.json"
        path.write_text(json.dumps({"schema_version": 1, "ticket": "QA-9", "rows": rows}), encoding="utf-8")
        lines = brief_pack.reference_gap_lines(task)
        check_eq("the fetched row is not listed; the others are, one line each, `<ref> - <status>: <why>`", lines, [
            f"{file}QA-101 {em} not_fetched: not read yet",
            f"{file}~/Projects/x/app {em} not_fetched: local path mention",
            f"{file}!1924 {em} person: a merge_request named in mention:comment:15923998; no route of the factory reads it, so it is "
            "the person's to paste or to say it is not needed",
            f"{file}QA-102 {em} unknown: a ticket named in the ticket; no status was recorded for it"])
        built = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)["markdown"].splitlines()
        at = next(i for i, ln in enumerate(built) if "work/ticket-snapshot.json" in ln and "(" in ln)
        check("the scout's brief carries them right under the snapshot's own line", built[at + 1:at + 5] == lines, "\n".join(built[at:at + 6]))
        # the cap: 20 are listed whole; the 21st and later are one `+K more` line
        for total, more in ((20, 0), (21, 1), (25, 5)):
            many = [{"ref": f"QA-{200 + n}", "kind": "ticket", "origins": ["mention:description"], "status": "not_fetched:not read yet"}
                    for n in range(total)]
            path.write_text(json.dumps({"rows": many}), encoding="utf-8")
            lines = brief_pack.reference_gap_lines(task)
            check_eq(f"cap: {total} rows -> {min(total, 20)} lines" + (f" and `+{more} more`" if more else " and no `more` line"),
                     (len(lines), lines[-1].split(": ", 1)[1] if more else None), (20 + (1 if more else 0), f"+{more} more not read (all of them are in the file)" if more else None))
        # t-281 follow-up: an `unproven` row (the paste-only leg of S0) says WHY in its own `reason` field
        path.write_text(json.dumps({"rows": [{"ref": "ABC-5", "kind": "ticket", "origins": ["mention:description"],
                                              "status": "unproven", "reason": "no tracker read at S0"}]}), encoding="utf-8")
        check_eq("unproven row with a reason: the line carries the reason (positive)", brief_pack.reference_gap_lines(task),
                 [f"{file}ABC-5 {em} unproven: no tracker read at S0"])
        path.write_text(json.dumps({"rows": [{"ref": "ABC-5", "kind": "ticket", "origins": ["mention:description"], "status": "unproven"}]}), encoding="utf-8")
        check_eq("unproven row WITHOUT a reason keeps today's line (negative)", brief_pack.reference_gap_lines(task),
                 [f"{file}ABC-5 {em} unproven: a ticket named in mention:description; no status was recorded for it"])
        # t-373 F6 (B-256 c): a merge request whose repository name two attached repositories share says so, and how to settle it
        ambiguous = {"ref": "!1924", "kind": "merge_request", "origins": ["mention:comment:1"], "status": "not_fetched:not read yet",
                     "repo": "ambiguous", "matched_token": "testproject1-ui", "candidates": ["../../testproject1-ui", "../../fork/testproject1-ui"],
                     "refusal": "two repositories carry this name: ../../testproject1-ui; ../../fork/testproject1-ui; "
                                "name the repository by its path or URL"}
        path.write_text(json.dumps({"rows": [ambiguous]}), encoding="utf-8")
        check_eq("F6: an ambiguous merge request is listed with the line that names the candidates and the door",
                 brief_pack.reference_gap_lines(task),
                 [f"{file}!1924 {em} two repositories carry this name: ../../testproject1-ui; ../../fork/testproject1-ui; "
                  "name the repository by its path or URL"])
        path.write_text(json.dumps({"rows": [dict(ambiguous, repo="unknown")]}), encoding="utf-8")
        check_eq("F6 (negative): a row that is not `ambiguous` keeps its own line, `refusal` or not",
                 brief_pack.reference_gap_lines(task), [f"{file}!1924 {em} not_fetched: not read yet"])
        # negative controls: every row fetched -> nothing; a file that is not JSON, or has no rows -> nothing, and no crash
        path.write_text(json.dumps({"rows": [dict(rows[0]), dict(rows[0], ref="QA-103")]}), encoding="utf-8")
        check_eq("negative: every row `fetched` -> no line", brief_pack.reference_gap_lines(task), [])
        path.write_text("not json", encoding="utf-8")
        check_eq("negative: an unreadable file says nothing and breaks nothing", brief_pack.reference_gap_lines(task), [])
        path.write_text(json.dumps({"rows": "none"}), encoding="utf-8")
        check_eq("negative: rows that are no list -> nothing", brief_pack.reference_gap_lines(task), [])
    finally:
        harness.cleanup(root)


def reads_skipped_lines() -> None:
    """t-282 (F8, K-F8): an optional read S0 could not make (`reads_skipped` in `work/source-inventory.json`) is
    said in the scout's brief, one line per entry, so "no remote links in the ticket" is never read where "the
    remote links were not read" is the fact (FR-41). A story whose inventory has no key, an empty list or no
    inventory at all is briefed as it always was (temporal)."""
    root = harness.temp_project("qa-brief-reads-skipped-")
    em = chr(0x2014)
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        work = task / "work"
        (work / "ticket-snapshot.json").write_text(json.dumps({"key": "QA-9", "links": {}}), encoding="utf-8")
        check_eq("temporal: no inventory, no line", brief_pack.reads_skipped_lines(task), [])
        path = work / "source-inventory.json"
        path.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        check_eq("temporal: an inventory from before the key existed, no line", brief_pack.reads_skipped_lines(task), [])
        path.write_text(json.dumps({"schema_version": 1, "sources": [], "reads_skipped": []}), encoding="utf-8")
        check_eq("negative: nothing skipped (`[]`) -> no line, and none in the brief",
                 brief_pack.reads_skipped_lines(task), [])
        check_not_in("negative: ... nor in the built brief", "were not read",
                     brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)["markdown"])
        file = "- work/source-inventory.json: "
        path.write_text(json.dumps({"schema_version": 1, "sources": [], "reads_skipped": [
            {"call": "/remotelink", "status": 503, "why": "the tracker answered HTTP 503 on every attempt"}]}), encoding="utf-8")
        check_eq("a skipped /remotelink -> one line `remote links were not read: <why>`",
                 brief_pack.reads_skipped_lines(task), [f"{file}remote links were not read: the tracker answered HTTP 503 on every attempt"])
        path.write_text(json.dumps({"schema_version": 1, "sources": [], "reads_skipped": [
            {"call": "/remotelink", "status": None, "why": "network timeout on every attempt"},
            {"call": "/field", "status": 404, "why": "the tracker answered HTTP 404"}]}), encoding="utf-8")
        lines = brief_pack.reads_skipped_lines(task)
        check_eq("one line per entry, the /field one says custom fields are matched by id only", lines, [
            f"{file}remote links were not read: network timeout on every attempt",
            f"{file}the field catalogue was not read: the tracker answered HTTP 404 {em} custom fields are matched by id only"])
        built = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)["markdown"].splitlines()
        at = next(i for i, ln in enumerate(built) if "work/ticket-snapshot.json" in ln and "(" in ln)
        check("the scout's brief carries them right under the snapshot's own line", built[at + 1:at + 3] == lines, "\n".join(built[at:at + 4]))
        path.write_text(json.dumps({"reads_skipped": [{"call": "/other", "why": "x"}, "junk", {"why": "no call"}, {"call": "/remotelink"}]}),
                        encoding="utf-8")
        check_eq("an unknown call is named as it is, a malformed entry is skipped, a missing reason is said",
                 brief_pack.reads_skipped_lines(task),
                 [f"{file}/other was not read: x", f"{file}remote links were not read: no reason was recorded"])
        path.write_text(json.dumps({"reads_skipped": "none"}), encoding="utf-8")
        check_eq("negative: a key that is no list says nothing and breaks nothing", brief_pack.reads_skipped_lines(task), [])
        path.write_text("not json", encoding="utf-8")
        check_eq("negative: an unreadable inventory says nothing and breaks nothing", brief_pack.reads_skipped_lines(task), [])
    finally:
        harness.cleanup(root)


def ticket_view_lines() -> None:
    """t-267 (item 9): S0's REST read leaves `work/ticket-view.md` and `work/ticket-raw/issue.pretty.json`; the
    scout's brief names the view as the one to read and the raw as readable, not injected. A story whose S0 ran
    before the files existed is briefed as it always was (temporal), and S1's own `raw.json` is never handed on
    as collected material."""
    root = harness.temp_project("qa-brief-ticket-view-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        work = task / "work"
        (work / "ticket-snapshot.json").write_text(json.dumps({"key": "QA-9", "links": {}}), encoding="utf-8")
        before = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)["markdown"]
        check_not_in("temporal: no S0 files, no line about them", "ticket-view.md", before)
        check_not_in("temporal: ... nor about the raw", "issue.pretty.json", before)
        check_eq("temporal: the helper says nothing either", brief_pack.ticket_view_lines(task, root), [])
        (work / "ticket-view.md").write_text("QA-9 - title\n\nDESCRIPTION\nbody\n", encoding="utf-8")
        (work / "ticket-raw").mkdir()
        (work / "ticket-raw" / "issue.pretty.json").write_text('{\n  "key": "QA-9"\n}\n', encoding="utf-8")
        after = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-1", write=False)["markdown"]
        listed = after.splitlines()
        at = next(i for i, ln in enumerate(listed) if "work/ticket-snapshot.json" in ln and "(" in ln)
        view_at = next((i for i, ln in enumerate(listed) if "work/ticket-view.md" in ln), -1)
        raw_at = next((i for i, ln in enumerate(listed) if "work/ticket-raw/issue.pretty.json" in ln), -1)
        check("the brief names work/ticket-view.md as the ticket to read, right under the snapshot's line",
              view_at == at + 1 and "Read this, not the JSON" in listed[view_at], "\n".join(listed[at:at + 4]))
        check("... and work/ticket-raw/issue.pretty.json as `readable, not injected`, grep it, never whole",
              raw_at == at + 2 and "readable, not injected" in listed[raw_at] and "never read it whole" in listed[raw_at],
              "\n".join(listed[at:at + 4]))
        check_in("both lines carry the file's size, as every listed file does", "(", listed[view_at])
        # S1's own raw answer is evidence, not material
        folder = work / "sources" / "SRC-1" / "rev1"
        folder.mkdir(parents=True)
        (folder / "ticket.json").write_text("{}", encoding="utf-8")
        (folder / "raw.json").write_text('{"key": "X"}', encoding="utf-8")
        (folder / "raw-comments-1.json").write_text('{"comments": []}', encoding="utf-8")
        (folder / "mr-1.md").write_text("digest", encoding="utf-8")
        lines = brief_pack.source_material("QA-9", task, "qa-requirements-tester")
        check("S1's raw.json and raw-comments-<n>.json are never handed on as collected material, the real digest still is",
              any("mr-1.md" in ln for ln in lines) and not any("raw" in ln for ln in lines), str(lines))
        (folder / "notes-raw.json").write_text("{}", encoding="utf-8")
        later = brief_pack.source_material("QA-9", task, "qa-requirements-tester")
        check("negative control: a file with another name (notes-raw.json) IS handed on", any("notes-raw.json" in ln for ln in later), str(later))
    finally:
        harness.cleanup(root)


def expectation_lines() -> None:
    root = harness.temp_project("qa-brief-changes-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        seed_story_for_s5(task, root, "Gate A: approved.")
        register_critic(task)
        pointer = brief_pack.EXPECTATION_POINTER
        check_eq("the pointer is the one the spec names", pointer, "`s5_precheck.py --json` -> `expectation_changes`")

        # 0 pairs, no run blocks at all, then no manifest: no line and no exception (edge 7)
        base = critic_brief()["markdown"]
        check_not_in("no run blocks: no changed-test line", LINE_START, base)
        check_not_in("and no 'could not be measured' line either: a story with no blocks measured fine",
                     UNMEASURED_START, base)
        manifest_path = task / "work/automation-manifest.json"
        saved_manifest = manifest_path.read_text(encoding="utf-8")
        manifest_path.unlink()
        no_manifest = critic_brief()["markdown"]
        check("no manifest: the brief is built, with no line of either kind",
              LINE_START not in no_manifest and UNMEASURED_START not in no_manifest)
        manifest_path.write_text(saved_manifest, encoding="utf-8")

        # 1 name: the line, no 'more' tail, the pointer once, with its fields
        seed_changes(task, [fn_name(1)])
        one = critic_brief()["markdown"]
        line = line_of(one, LINE_START)
        check_in("1 pair: the line counts one", "1 to judge: " + fn_key(fn_name(1)), line)
        check_not_in("1 pair: no 'more' tail", " more - ", line)
        check_eq("1 pair: the pointer to the full list is given once", one.count(pointer), 1)
        check_in("1 pair: it says the list comes with its fields", "with its fields", line)
        check_in("and names them the code reads", "`red_evidence`", line)
        check_in("and the verdict door, with the command shape (the card has no manifest_put line for the critic)",
                 "`manifest_put.py --task QA-9 --fragment <file.json>`", line)
        check_in("naming the record it patches", "one `critic_verdict` on that record", line)
        check_not_in("a pair whose test still exists is not called gone", "gone after its red run", line)
        head_lines = one.split("\n## ")[0].splitlines()
        check_eq("the line is in the head, right after the scope line",
                 [i for i, ln in enumerate(head_lines) if ln.startswith(LINE_START)],
                 [next(i for i, ln in enumerate(head_lines) if ln.startswith("Scope:")) + 1])

        # exactly 8 names: complete list, no 'more' (edge 1, at the cap)
        seed_changes(task, [fn_name(i) for i in range(1, 9)])
        eight = critic_brief()["markdown"]
        line = line_of(eight, LINE_START)
        check_in("8 pairs: the line counts eight", "- 8 to judge: ", line)
        check("8 pairs: all eight names are printed", all(fn_key(fn_name(i)) in line for i in range(1, 9)), line)
        check_not_in("8 pairs: no 'more' tail (the list is complete)", " more - ", line)
        check_eq("8 pairs: the pointer to the full list is still given once", eight.count(pointer), 1)

        # 9 names: eight shown, one more, the pointer in the tail and only there
        seed_changes(task, [fn_name(i) for i in range(1, 10)])
        nine = critic_brief()["markdown"]
        line = line_of(nine, LINE_START)
        check_in("9 pairs: the line counts nine", "- 9 to judge: ", line)
        check("9 pairs: the first eight names are printed",
              all(fn_key(fn_name(i)) in line for i in range(1, 9)), line)
        check_not_in("9 pairs: the ninth is NOT printed", fn_key(fn_name(9)), line)
        check_in("9 pairs: 'and 1 more' with the pointer",
                 ", and 1 more - the full list: " + pointer, line)
        check_eq("9 pairs: the pointer is given once, not twice", nine.count(pointer), 1)
        seed_changes(task, [fn_name(i) for i in range(1, 13)])
        twelve = line_of(critic_brief()["markdown"], LINE_START)
        check("12 pairs: the count is the number of pairs, four are 'more'",
              "- 12 to judge: " in twelve and ", and 4 more - the full list: " in twelve, twelve)

        # an orphaned red is in the list, said in words (edge 2)
        seed_changes(task, [fn_name(1), fn_name(2)], gone=["test_gone_01"])
        line = line_of(critic_brief()["markdown"], LINE_START)
        check_in("an orphan: counted with the others", "- 3 to judge: ", line)
        check_in("and says in words that the test is gone after its red run",
                 fn_key("test_gone_01") + " (gone after its red run)", line)
        check_not_in("the ordinary pairs do not carry that phrase",
                     fn_key(fn_name(1)) + " (gone", line)

        # a pair that already carries a verdict is not work (edge 3)
        seed_changes(task, [fn_name(i) for i in range(1, 4)],
                     judged={fn_name(1): "legitimate_correction", fn_name(2): "fitted_to_code"})
        line = line_of(critic_brief()["markdown"], LINE_START)
        check_in("two of three judged: one to judge", "- 1 to judge: " + fn_key(fn_name(3)), line)
        check_in("and it says how many already carry a verdict", "2 more already carry a verdict", line)
        check_not_in("a judged pair is not listed as work", fn_key(fn_name(1)), line)
        seed_changes(task, [fn_name(1)], judged={fn_name(1): "fitted_to_code"})
        check_not_in("every pair judged: no line at all", LINE_START, critic_brief()["markdown"])
        seed_changes(task, [fn_name(1)], judged={fn_name(1): ""})
        check_in("a record with no verdict yet is still to judge", "- 1 to judge: ",
                 line_of(critic_brief()["markdown"], LINE_START))
        seed_changes(task, [fn_name(1)], judged={fn_name(1): "approved"})
        check_in("a word that is not one of the three verdicts is not a verdict",
                 "- 1 to judge: ", line_of(critic_brief()["markdown"], LINE_START))

        # F-cj: a pair the critic recorded `could_not_judge` for is listed APART, in the conductor's words:
        # it is not "to judge" again and it is not "already carries a verdict" either
        seed_changes(task, [fn_name(i) for i in range(1, 4)],
                     judged={fn_name(1): "legitimate_correction", fn_name(2): "could_not_judge"})
        got = lines_of(critic_brief()["markdown"])
        check_eq("F-cj: two lines - the pair still to judge, and the one that could not be judged", len(got), 2)
        check_in("F-cj: the count of 'to judge' is the third pair only", "- 1 to judge: " + fn_key(fn_name(3)), got[0])
        check_in("F-cj: one pair already carries a verdict (the could_not_judge one is not in that count)",
                 " 1 more already carry a verdict", got[0])
        check_eq("F-cj: the could_not_judge pair has its own line, in the one road's words",
                 got[1], f"{LINE_START} - 1 could not be judged - the conductor records the window as unresolved "
                         f"with the reason: {fn_key(fn_name(2))}.")
        seed_changes(task, [fn_name(1)], judged={fn_name(1): "could_not_judge"})
        got = lines_of(critic_brief()["markdown"])
        check_eq("F-cj: only a could_not_judge pair: only its line (no 'to judge' line, no pointer)",
                 (len(got), "to judge" in got[0], brief_pack.EXPECTATION_POINTER in got[0]), (1, False, False))

        # B1: a pair a person's word passed is listed APART, visible, never "to judge" and never dropped
        def set_words(*matches: str) -> None:
            pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
            pipeline["stage_overrides"] = [w for w in pipeline["stage_overrides"]
                                           if w.get("decision") != WORD_DECISION] + [
                {"stage": "S5", "match": m, "decision": WORD_DECISION, "by": "human"} for m in matches]
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        seed_changes(task, [fn_name(1), fn_name(2)])
        set_words("changed-after-red")
        got = lines_of(critic_brief()["markdown"])
        check_eq("B1: the stage-wide word: the pairs are not to judge; ONE line lists them, in the words of the road",
                 got, [f"{LINE_START} - 2 passed by a person's word - nothing to record: "
                       f"{fn_key(fn_name(1))}, {fn_key(fn_name(2))}. Write a `test_defect` finding if the test "
                       "was fitted to the code."])
        set_words("changed-after-red-" + fn_key(fn_name(1)) + "-r1-g1")
        got = lines_of(critic_brief()["markdown"])
        check("B1: a word for ONE pair (its own tag): the other is still to judge, the first listed apart",
              len(got) == 2 and "- 1 to judge: " + fn_key(fn_name(2)) in got[0]
              and f"- 1 passed by a person's word - nothing to record: {fn_key(fn_name(1))}." in got[1], str(got))
        check_not_in("B1: the passed pair is not in the 'to judge' line", fn_key(fn_name(1)), got[0] if got else "")
        seed_changes(task, [fn_name(1)], gone=["test_gone_01"])
        set_words("changed-after-red")
        check_in("B1: an orphaned red passed by word says it is gone, as the other line does",
                 fn_key("test_gone_01") + " (gone after its red run)", critic_brief()["markdown"])
        seed_changes(task, [fn_name(1)], judged={fn_name(1): "legitimate_correction"})
        check_eq("B1: a pair with a record and a verdict is judged, the word or not: no line at all",
                 lines_of(critic_brief()["markdown"]), [])
        seed_changes(task, [fn_name(1)], judged={fn_name(1): ""})
        got = lines_of(critic_brief()["markdown"])
        check_eq("B1: a word, then the author records a row for the pair anyway: the record stands and the pair is "
                 "judged like any recorded pair (to judge, not 'passed by word')",
                 (len(got), "- 1 to judge: " in (got[0] if got else "")), (1, True))
        seed_changes(task, [fn_name(i) for i in range(1, 10)])
        got = lines_of(critic_brief()["markdown"])
        head = got[0] if got else ""  # a missing line is a failed check below, not an IndexError
        check_eq("B1: nine pairs passed by word: one line, eight names, 'and 1 more' with the pointer, given once",
                 (len(got), "- 9 passed by a person's word" in head, head.count(fn_key(fn_name(9))),
                  ", and 1 more - the full list: " + pointer in head), (1, True, 0, True))
        set_words()
        check_eq("B1: the words taken away (revoked): the same nine are 'to judge' again",
                 [ln.split(":")[0] for ln in lines_of(critic_brief()["markdown"])],
                 [f"{LINE_START} - 9 to judge"])
        set_words("changed-after-red")
        pipeline_before = (task / "pipeline.json").read_text(encoding="utf-8")
        auto = critic_brief("qa-automator", "S5", "S5-qa-automator-1")["markdown"]
        check_not_in("B1: the automator's brief never carries the line", "passed by a person's word", auto)
        check_eq("and the brief writes nothing (the pipeline is as it was)",
                 (task / "pipeline.json").read_text(encoding="utf-8"), pipeline_before)
        set_words()

        # the pairs the check does not owe are not the critic's list (R6): another stage's dispatch
        seed_changes(task, [fn_name(1)])
        blocks = task / "work/run-blocks"
        for path in blocks.glob("*g1.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["dispatch_id"] = "S6-qa-runner-1"
            path.write_text(json.dumps(data), encoding="utf-8")
        state = json.loads((task / "state/controller.json").read_text(encoding="utf-8"))
        state["dispatches"]["S6-qa-runner-1"] = {"id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner",
                                                 "status": "accepted", "scope": ["TC-001"]}
        (task / "state/controller.json").write_text(json.dumps(state), encoding="utf-8")
        check_not_in("a pair whose green belongs to another stage is listed nowhere in this brief",
                     LINE_START, critic_brief()["markdown"])

        # the automator never gets the line, whatever the pairs (edge 1)
        register_critic(task)
        seed_changes(task, [fn_name(i) for i in range(1, 10)])
        auto = critic_brief("qa-automator", "S5", "S5-qa-automator-1")["markdown"]
        check_not_in("an automator brief with nine pairs carries no such line", LINE_START, auto)
        check_not_in("nor the unmeasured one", UNMEASURED_START, auto)
        check_not_in("nor the pointer", pointer, auto)
        runner = critic_brief("qa-runner", "S6", "S6-qa-runner-1")["markdown"]
        check("a runner brief neither", LINE_START not in runner and pointer not in runner)

        # the detector is called once per critic brief and never for another role (edge 6)
        import s5_precheck
        real, calls = s5_precheck.expectation_changes, []

        def counting(*a, **kw):
            calls.append(1)
            return real(*a, **kw)
        s5_precheck.expectation_changes = counting
        try:
            critic_brief()
            check_eq("a critic brief calls the detector once (not per case, not per pair)", len(calls), 1)
            critic_brief("qa-automator", "S5", "S5-qa-automator-1")
            critic_brief("qa-runner", "S6", "S6-qa-runner-1")
            check_eq("an automator and a runner brief call it never", len(calls), 1)
        finally:
            s5_precheck.expectation_changes = real
        before = tree_hash(task)
        critic_brief()
        check_eq("building the brief writes nothing into the story (FR-45)", tree_hash(task), before)

        # the only difference the pairs make is the one line (position: the head, after the others).
        # The HEAD is compared: it is never shrunk, while the body below it may be trimmed to make room.
        def head_of(text: str) -> str:
            # TQ1-11: the project-approach block is the one head part the ceiling cuts first (a pointer line may show or not here)
            return "\n".join(ln for ln in text.split("\n## ")[0].split("\n") if not ln.startswith("- Project approach"))
        with_pairs = head_of(critic_brief()["markdown"])
        stripped = "\n".join(ln for ln in with_pairs.split("\n") if not ln.startswith(LINE_START))
        import shutil
        shutil.rmtree(task / "work/run-blocks")
        without = head_of(critic_brief()["markdown"])
        check_eq("without the line, the head of a brief with pairs is byte for byte the head with no run blocks",
                 stripped, without)

        # the detector could not measure (edge 4): one line in words, never "none"; the brief is built
        seed_changes(task, [fn_name(1)])
        (task / "work/run-blocks" / "20260930T059900000000Z-bad.json").write_text("{not json", encoding="utf-8")
        result = critic_brief()
        text = result["markdown"]
        check_in("an unreadable run block: the unmeasured line names why",
                 UNMEASURED_START + " work/run-blocks/20260930T059900000000Z-bad.json is not a readable JSON object",
                 line_of(text, UNMEASURED_START))
        check_eq("and it is ONE line", sum(1 for ln in text.splitlines() if ln.startswith(UNMEASURED_START)), 1)
        check_in("the pair the readable blocks did give is still listed", "- 1 to judge: ", line_of(text, LINE_START))
        check_not_in("the unmeasured line never says none", "none", line_of(text, UNMEASURED_START))
        check("and the brief is built whole", result["bytes"] > 0 and "## Rule" in text)
        shutil.rmtree(task / "work/run-blocks")
        (task / "work/run-blocks").mkdir()
        (task / "work/run-blocks" / "20260930T050000000000Z-bad.json").write_text("[]", encoding="utf-8")
        alone = critic_brief()["markdown"]
        check_in("an unreadable block and no pair: only the unmeasured line",
                 UNMEASURED_START, alone)
        check_not_in("with no changed-test line", LINE_START, alone)

        def boom(*a, **kw):
            raise RuntimeError("boom")
        s5_precheck.expectation_changes = boom
        try:
            raised = critic_brief()["markdown"]
        finally:
            s5_precheck.expectation_changes = real
        check_in("a detector that raises: the line says the measurement failed and why",
                 UNMEASURED_START + " the measurement itself failed (RuntimeError: boom)", raised)
        check_in("and the brief is still built to its end", "## Rule", raised)
        s5_precheck.expectation_changes = lambda *a, **kw: {"pairs": [], "unmeasured": ["why " + "x" * 5000]}
        try:
            long_why = line_of(critic_brief()["markdown"], UNMEASURED_START)
        finally:
            s5_precheck.expectation_changes = real
        check("a 5 KB reason is clipped in the middle, the head stays bounded",
              len(long_why) <= len(UNMEASURED_START) + 1 + brief_pack.EXPECTATION_WHY_CHARS and "..." in long_why,
              str(len(long_why)))
        shutil.rmtree(task / "work/run-blocks")

        # a very long test name is clipped; the count and the pointer survive
        long_name = "test_a" + "y" * 400  # sorts before test_case_NN: it is among the eight shown
        seed_changes(task, [long_name] + [fn_name(i) for i in range(1, 9)])
        line = line_of(critic_brief()["markdown"], LINE_START)
        check_in("a 400-character name: still counted (nine pairs)", "- 9 to judge: ", line)
        check("and shown clipped to the cap, not whole",
              "y" * 400 not in line and "..." in line and len(line) < 1800, str(len(line)))
        shutil.rmtree(task / "work/run-blocks")

        # at the cap of the brief: 10 KB of the person's words force every shrink; the head keeps the line (edge 5)
        seed_story_for_s5(task, root, "Gate A: approved. " + "Keep every UI case in scope. " * 400)
        register_critic(task)
        seed_changes(task, [fn_name(i) for i in range(1, 10)])
        capped = critic_brief()
        check("10 KB of gate words: the critic's brief is still within 6 KB", capped["budget_bytes"] <= 6 * 1024,
              f"{capped['budget_bytes']} {capped['over_ceiling']} head {brief_pack.head_bytes(capped['markdown'].split(chr(10))[2:10])} "
              f"bytes {capped['bytes']}")
        check_eq("the trimming really ran: the words moved to a side file", capped["sides"]["decisions"], True)
        check_in("and the head still carries the changed-test line, with its 'more' tail",
                 ", and 1 more - the full list: " + pointer, capped["markdown"])
        check_in("and the count", "- 9 to judge: ", capped["markdown"])
    finally:
        harness.cleanup(root)


# --- t-196: the live checks the predicate requires, handed to the code critic in the head -----------
#
# Every fixture is synthetic. A row is required when `proof_level.proof_required` says so (here: a stored
# `novelty` of new or changed); it is receipted when `proof_level.reached` finds a valid receipt for the
# bytes of its test - a REAL receipt file here, not a patched answer.

PROOF_START = "Live checks the predicate requires"
CANNOT_START = "The live checks the predicate requires could not be listed: "
PROOF_TAIL = (". Each needs a receipt: run its check and record it, or leave it in work/probe-debt/S5-qa-code-critic-1.json "
              "for the conductor.")


def proof_name(i: int, word: str = "") -> str:
    return f"{TEST_FILE}::{fn_name(i)}" + (f" ({word})" if word else "")


def write_receipt(task: Path, root: Path, iid: str) -> dict:
    """A receipt `contract.sensitivity_proof_issues` accepts for the CURRENT bytes of TEST_FILE."""
    import hashlib
    sha = hashlib.sha256((root / TEST_FILE).read_bytes()).hexdigest()
    body = {"instance_id": iid, "case_version": "cv_x", "test_content_hash": sha, "source_revision": "src",
            "build_id": "build", "mutation": "real_behavior", "expected_assertion_failure": "denied",
            "actual_failure": "denied", "assertion_location": "t.py:4", "restoration_evidence": "restored",
            "failure_kind": "assertion", "immutable": True, "receipt_hash": "h-" + iid}
    path = task / "work/sensitivity-receipts" / f"{iid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    return {"path": path.relative_to(task).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def seed_proof_rows(task: Path, root: Path, n: int, receipted: tuple = (), extra: list = ()) -> None:
    """`n` rows of TC-001 with a stored novelty (odd: new, even: changed); the numbers in `receipted` carry a
    valid receipt; `extra` rows are added as they are."""
    rows = []
    for i in range(1, n + 1):
        row = {"case": "TC-001", "covers": ["TC-001"], "file": TEST_FILE, "instance_id": fn_name(i),
               "case_version_links": [{"case_id": "TC-001", "version": "cv_x"}],
               "novelty": {"value": "new" if i % 2 else "changed", "basis": "t-196 fixture"}}
        if i in receipted:
            row["sensitivity_proof"] = {"receipt_ref": write_receipt(task, root, fn_name(i))}
        rows.append(row)
    path = task / "work/automation-manifest.json"
    path.write_text(json.dumps({"tests": rows + list(extra), "unresolved": []}), encoding="utf-8")


def proof_lines() -> None:
    root = harness.temp_project("qa-brief-proof-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        seed_story_for_s5(task, root, "Gate A: approved.")
        register_critic(task)

        def mine(role: str = "qa-code-critic", stage: str = "S5", dispatch: str = CRITIC) -> list:
            return [ln for ln in critic_brief(role, stage, dispatch)["markdown"].splitlines() if ln.startswith(PROOF_START)]

        def built(n_owed: int) -> str:
            return PROOF_START + f" - {n_owed} instances (new or changed tests): "

        # 0 instances: the seed manifest has one row with no novelty and no flag - not required, no line at all
        check_eq("0 instances: no line (the charter's sentence about probe-debt covers the case)", mine(), [])
        seed_proof_rows(task, root, 0)
        check_eq("an empty tests[]: no line, and not the 'could not be listed' one either",
                 critic_brief()["markdown"].count(PROOF_START), 0)

        # 1 instance
        seed_proof_rows(task, root, 1)
        check_eq("1 instance: the line, the name with its novelty word, the tail",
                 mine(), [PROOF_START + " - 1 instance (new or changed tests): " + proof_name(1, "new") + PROOF_TAIL])

        # 8 = the cap: all named, no 'more'
        seed_proof_rows(task, root, 8)
        line = mine()[0]
        check_eq("8 instances: all eight named, no 'more' clause",
                 line, built(8) + ", ".join(proof_name(i, "new" if i % 2 else "changed") for i in range(1, 9)) + PROOF_TAIL)
        check_not_in("8 instances: nothing is cut", "more", line.split(": ", 1)[1])

        # 9 = one beyond the cap
        seed_proof_rows(task, root, 9)
        line = mine()[0]
        check_eq("9 instances: eight named, then 'and 1 more' with where the full list is",
                 line, built(9) + ", ".join(proof_name(i, "new" if i % 2 else "changed") for i in range(1, 9))
                 + ", and 1 more - the full list: work/automation-manifest.json (`novelty` per row)" + PROOF_TAIL)
        check_not_in("9 instances: the ninth is not named", fn_name(9), line)

        # 12 instances
        seed_proof_rows(task, root, 12)
        result = critic_brief()
        line = next(ln for ln in result["markdown"].splitlines() if ln.startswith(PROOF_START))
        check_in("12 instances: the count", " - 12 instances (new or changed tests): ", line)
        check_in("12 instances: four more", ", and 4 more - the full list: work/automation-manifest.json (`novelty` per row)", line)
        check_eq("12 instances: eight names", line.count(TEST_FILE + "::"), 8)
        check("12 instances: the brief stays within 6 KB", result["budget_bytes"] <= 6 * 1024, str(result["budget_bytes"]))

        # a name is the project's free text: clipped, the count and the tail survive
        long_name = "test_a" + "y" * 400
        seed_proof_rows(task, root, 2, extra=[{"case": "TC-001", "covers": ["TC-001"], "file": TEST_FILE,
                                               "instance_id": long_name, "novelty": {"value": "new", "basis": "x"}}])
        line = mine()[0]
        check("a 400-character name is clipped to the cap, not whole, and the tail is there",
              "y" * 400 not in line and "..." in line and line.endswith(PROOF_TAIL) and " - 3 instances " in line, line[:200])

        # the receipted split: required AND already receipted are counted apart, never as work
        seed_proof_rows(task, root, 4, receipted=(2, 4))
        line = mine()[0]
        check_eq("2 of 4 receipted: 2 owed, '2 already receipted', only the two owed are named", line,
                 PROOF_START + " - 2 instances (new or changed tests), 2 already receipted: "
                 + proof_name(1, "new") + ", " + proof_name(3, "new") + PROOF_TAIL)
        check_not_in("the receipted ones are not listed as work", fn_name(2), line)
        seed_proof_rows(task, root, 4, receipted=(1, 2, 3, 4))
        check_eq("every required instance receipted: nothing is owed, no line (as for the changed tests)", mine(), [])
        seed_proof_rows(task, root, 10, receipted=(1, 2))
        check_in("10 instances, 2 receipted: the cap counts the OWED ones (8): no 'more'",
                 " - 8 instances (new or changed tests), 2 already receipted: ", mine()[0])
        check_not_in("...and no 'more' clause", ", and ", mine()[0].split(": ", 1)[1])

        # other instances: a row of another case is out of scope; a legacy flag is required with no word;
        # a row that is not required is not listed
        seed_proof_rows(task, root, 1, extra=[
            {"case": "TC-009", "covers": ["TC-009"], "file": TEST_FILE, "instance_id": "test_elsewhere",
             "novelty": {"value": "new", "basis": "x"}},
            {"case": "TC-001", "covers": ["TC-001"], "file": TEST_FILE, "instance_id": "test_legacy", "new_or_changed": True},
            {"case": "TC-001", "covers": ["TC-001"], "file": TEST_FILE, "instance_id": "test_quiet"}])
        line = mine()[0]
        check_not_in("a row of a case outside the dispatch's scope is not listed", "test_elsewhere", line)
        check_not_in("a row that no layer requires is not listed", "test_quiet", line)
        check_in("a legacy flagged row is listed, with no novelty word of its own", TEST_FILE + "::test_legacy. Each needs", line)
        check_not_in("...no invented word for it", "test_legacy (", line)

        # a row the predicate raises on: listed as could not be judged, the rest still listed
        import proof_level
        real = proof_level.proof_required

        def picky(entry, manifest):
            if isinstance(entry, dict) and entry.get("instance_id") == fn_name(2):
                raise RuntimeError("boom")
            return real(entry, manifest)
        seed_proof_rows(task, root, 3)
        proof_level.proof_required = picky
        try:
            text = critic_brief()["markdown"]
        finally:
            proof_level.proof_required = real
        line = next(ln for ln in text.splitlines() if ln.startswith(PROOF_START))
        check_eq("a row that raises: its own entry says why, the others are listed", line,
                 built(3) + proof_name(1, "new") + ", " + f"{TEST_FILE}::{fn_name(2)} - could not be judged (RuntimeError: boom), "
                 + proof_name(3, "new") + PROOF_TAIL)
        check_in("and the brief is built to its end", "## Rule", text)

        # a receipt that cannot be read leaves the row owed (the error goes toward 'still to check')
        real_reached = proof_level.reached

        def broken(*a, **kw):
            raise OSError("disk")
        seed_proof_rows(task, root, 2, receipted=(1,))
        proof_level.reached = broken
        try:
            line = next(ln for ln in critic_brief()["markdown"].splitlines() if ln.startswith(PROOF_START))
        finally:
            proof_level.reached = real_reached
        check_in("reached() raising: both rows stay owed, none is counted receipted",
                 " - 2 instances (new or changed tests): ", line)
        check_not_in("...and 'already receipted' is not said", "already receipted", line)

        # the manifest: absent, unreadable, not an object, a measurement that fails - ONE line, never "none"
        manifest_path = task / "work/automation-manifest.json"
        for label, payload, why in (
                ("a manifest that is not JSON", b"{not json", "work/automation-manifest.json cannot be read (JSONDecodeError)."),
                ("an empty manifest file", b"", "work/automation-manifest.json cannot be read (JSONDecodeError)."),
                ("a manifest that is a list", b"[]", "work/automation-manifest.json is not a JSON object."),
                ("a manifest that is not UTF-8", b"\xff\xfe\x00{", "work/automation-manifest.json cannot be read (UnicodeDecodeError).")):
            manifest_path.write_bytes(payload)
            result = critic_brief()
            said = [ln for ln in result["markdown"].splitlines() if ln.startswith(CANNOT_START)]
            check_eq(f"{label}: ONE line, and it says why", said, [CANNOT_START + why])
            check(f"{label}: never 'none', no list line, and the brief is built whole",
                  "none" not in said[0] and PROOF_START + " - " not in result["markdown"] and "## Rule" in result["markdown"])
        manifest_path.unlink()
        check_eq("no manifest at all: ONE line that says it is not there",
                 [ln for ln in critic_brief()["markdown"].splitlines() if ln.startswith(CANNOT_START)],
                 [CANNOT_START + "work/automation-manifest.json is not there."])
        import contract
        real_artifact = contract.artifact

        def conflicting(art_dir, name):
            if name == "automation-manifest.json":   # only the manifest's lookup fails; other readers go on
                raise ValueError("conflicting canonical and legacy artifact: automation-manifest.json")
            return real_artifact(art_dir, name)
        contract.artifact = conflicting
        try:
            text = critic_brief()["markdown"]
        finally:
            contract.artifact = real_artifact
        check_in("a measurement that fails: ONE line with the exception",
                 CANNOT_START + "the measurement itself failed (ValueError: conflicting canonical and legacy artifact",
                 line_of(text, CANNOT_START))
        check_in("...and the brief is built to its end", "## Rule", text)

        # another role: nothing, and not a single call of the predicate
        seed_proof_rows(task, root, 9)
        calls = []

        def counting(entry, manifest):
            calls.append(1)
            return real(entry, manifest)
        proof_level.proof_required = counting
        try:
            auto = critic_brief("qa-automator", "S5", "S5-qa-automator-1")["markdown"]
            runner = critic_brief("qa-runner", "S6", "S6-qa-runner-1")["markdown"]
            check_eq("an automator and a runner brief call the predicate never", len(calls), 0)
            critic_brief()
            check_eq("a critic brief calls it once per row in scope (9), not more", len(calls), 9)
        finally:
            proof_level.proof_required = real
        for label, text in (("automator", auto), ("runner", runner)):
            check(f"{label}: neither the list line nor the could-not-list line", PROOF_START not in text and CANNOT_START not in text)
        check_eq("the function itself returns [] for every other role",
                 [brief_pack.proof_required_lines(task, role, CRITIC) for role in ("qa-automator", "qa-runner", "qa-scout", "")],
                 [[], [], [], []])

        # read-only (FR-45): building the brief writes nothing into the story
        before = tree_hash(task)
        critic_brief()
        check_eq("building the brief writes nothing into the story (FR-45)", tree_hash(task), before)

        # its place: the head, right after the changed-test line, before the first section
        seed_proof_rows(task, root, 2)
        head = critic_brief()["markdown"].split("\n## ")[0]
        check("the line stands in the head", PROOF_START in head)
    finally:
        harness.cleanup(root)


# --- t-1027 (CX1-7): the checkout the orchestrator recorded and the implementation commit, stated in the brief ----
#
# TP2-2406 S5, 17.10.2026: the automator halted twice comparing a branch NAME (the merge request's source
# branch in context-manifest) with the checkout gate A had approved, at the SAME commit. The fixture is that run
# copied as DATA, never read at test time (FR-58). Every case names the invariant it protects. The line is only
# a description of the recorded checkout (I2): no phrase tells the role to be on a branch.

HEAD40 = "c4a2f1f2844b9665d971644112cb11efcf48e468"
HEAD12 = HEAD40[:12]
RECORDED = "TP2-2406-factory-082-codex"
MR_SOURCE = "TP2-2406_session-feedback"
BASE_FILE = f"state/{test_repo_base.FILE_NAME}"
BASE_RECORD = {"schema_version": 1, "recorded_at": "2026-10-10T20:37:53+00:00", "recorded_by": "stage_done.py S0",
               "git": "ok", "why": "", "repo_prefix": "", "head": HEAD40, "branch": RECORDED, "dirty": [],
               "dirty_truncated": False, "late": False, "late_why": "", "dirty_total": 0, "dirty_kept": "all",
               "dirty_excluded": "qa-factory", "dirty_excluded_why": "", "tests_root": ".",
               "found_from": "tests_root", "other_repository": False}
IMPLEMENTATION = {"repo": "tests", "source": "diff", "mr": "!57", "branch": MR_SOURCE, "commit": HEAD40,
                  "diff_path": "work/impl-diff.txt", "source_sha": HEAD40}
LIVE_REASON = ("Mandatory branch identity conflict: context-manifest and context-bundle require "
               f"{MR_SOURCE} while the Gate-A-approved current checkout is {RECORDED} at immutable HEAD c4a2f1f2844b; "
               "no automation manifest may be fabricated")
COMPARE_COMMITS = "Compare commits, never branch names; never create or switch a branch."
MR_SENTENCE = f"`{MR_SOURCE}` in the manifest is the merge request's source branch, not a branch to switch to."
CHECKOUT = f"recorded checkout `{RECORDED}`@{HEAD12} (recorded at S0 in {BASE_FILE})"
NOTHING = ("Branch check: nothing was recorded - neither a branch at S0 nor an implementation commit; work on the "
           "checkout as it stands and say so in your digest; never create or switch a branch.")
LIFECYCLE_MARKED = "<!-- roles: qa-automator -->\n## Before the first write"


def seed_branch(task: Path, record="live", implementation="live", implementations=None) -> None:
    """The record and the manifest the S0 exit and the scout leave. `record` None: no file; a dict: that record;
    a str: written as the file's bytes. `implementation` None: the manifest has no such key."""
    base = task / BASE_FILE
    base.parent.mkdir(parents=True, exist_ok=True)
    base.unlink(missing_ok=True)
    if record == "live":
        record = BASE_RECORD
    if isinstance(record, str):
        base.write_text(record, encoding="utf-8")
    elif record is not None:
        base.write_text(json.dumps(record), encoding="utf-8")
    manifest = {}
    if implementation is not None:
        manifest["implementation"] = IMPLEMENTATION if implementation == "live" else implementation
    if implementations is not None:
        manifest["implementations"] = implementations
    (task / "work/context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def branch_line(task: Path) -> str:
    return brief_pack.branch_check_line(task)


def brief_of(role: str = "qa-automator", stage: str = "S5", dispatch: str = "S5-qa-automator-1") -> str:
    return brief_pack.build("QA-9", stage, role, dispatch, write=False)["markdown"]


def single_proof(commit: str) -> str:
    """What a single not-HEAD entry hands the role (t-039 B1): ancestry proves the change at once, its failure is
    not the halt - a squash or a commit of another repository is proved by content - and only an absent change halts."""
    return (f"HEAD must carry its change - `git merge-base --is-ancestor {commit} HEAD` exit 0 proves it at once; when it "
            "does not (a squash, a rebase, or a commit this repository does not know), prove it by content against that "
            "entry's own checkout; halt only when the change is absent")


def branch_check_lines() -> None:
    import hooklib
    root = harness.temp_project("qa-brief-branch-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        seed_story_for_s5(task, root, "Gate A: approved.")
        seed_branch(task)

        # (a) the live state: the Factory describes the checkout gate A approved and calls the manifest's name what it is
        line = branch_line(task)
        check_eq("(a) the whole line, word for word: FR-15/FR-38 - the branch and the commit are given to the role",
                 line, f"Branch check: {CHECKOUT}; the implementation commit {HEAD12} (context-manifest) is this HEAD. "
                       f"{MR_SENTENCE} {COMPARE_COMMITS}")
        check_in("(a) the recorded branch is named: the role has a carrier to compare with", f"`{RECORDED}`", line)
        check_not_in("(a) I2: the line DESCRIBES the checkout, it never asks the role to be on a branch", "be on", line)
        check_in("(a) the manifest's name is the merge request's source branch, not a branch to switch to (the 2406 halt)",
                 f"`{MR_SOURCE}` in the manifest is the merge request's source branch, not a branch to switch to", line)
        check_in("(a) the identity is the commit, never a name (FR-16)", "Compare commits, never branch names", line)
        check_not_in("(a) a sha is shown as 12 hex only: the head is never fattened", HEAD40, line)
        check_not_in("(a) the line carries no line break: it is ONE paragraph", "\n", line)
        text = brief_of()
        at = {w: text.find(w) for w in ("Scope:", "Branch check:", "Read first,")}
        check("(a) the line stands after Scope and before Read first (positional: the Factory speaks first)",
              0 <= at["Scope:"] < at["Branch check:"] < at["Read first,"], str(at))
        head_lines = text.split("\n## ")[0].splitlines()
        scope_at = next(i for i, ln in enumerate(head_lines) if ln.startswith("Scope:"))
        check("(a) and it is the very next line after Scope", head_lines[scope_at + 1].startswith("Branch check: "),
              head_lines[scope_at + 1])
        check_eq("(a) it is stated once", text.count("Branch check:"), 1)

        # (a') the repair brief quoting the previous role's halt: the Factory's own statement precedes it (E17)
        state_path = task / "state/controller.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["dispatches"]["S5-qa-automator-2"] = {
            "id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator", "status": "running",
            "scope": ["TC-001", "TC-002"], "parent_retry": "S5-qa-automator-1", "reason": LIVE_REASON}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        repair = brief_of(dispatch="S5-qa-automator-2")
        i_check, i_repair = repair.find("Branch check:"), repair.find("This is a repair dispatch")
        check("(a') the Branch check line stands BEFORE the repair line (a role's halt is never the only branch word)",
              0 <= i_check < i_repair, f"{i_check} / {i_repair}")
        check_in("(a') the repair line still quotes the previous halt, as before", "Mandatory branch identity conflict", repair)
        check("(a') the manifest's branch name appears first inside the Factory's line, not in the quoted claim",
              0 <= repair.find(MR_SOURCE) < i_repair)

        # (b) the commit is not HEAD: the role is handed the PROOF that HEAD carries its change; brief_pack decides nothing,
        # and the halt is the change being absent, never the ancestry answer (t-039 B1: a squash, another repository)
        other = "a" * 40
        seed_branch(task, implementation=dict(IMPLEMENTATION, commit=other))
        line = branch_line(task)
        check_in("(b) a commit other than HEAD: named, with its repository, and owed the proof (no git call here)",
                 f"the implementation commit {'a' * 12} (context-manifest, repository tests) is not this HEAD: "
                 f"{single_proof(other)}.", line)
        check_in("(b) ancestry proves the change at once", "proves it at once", line)
        check_in("(b) when ancestry fails the change is proved by content (a squash is not a halt)", "by content", line)
        check_in("(b) the halt is the change being absent", "halt only when the change is absent", line)
        check_not_in("(b) ancestry is never the halt condition (I1): the old words are gone", "halt when it is not", line)
        check_not_in("(b) and it is not called HEAD: the error goes toward the proof, never toward a pass (FR-59)",
                     "is this HEAD", line)
        # (b') a commit of another repository: ancestry answers 128 there, so the clause names the repository and the proof
        seed_branch(task, implementation=dict(IMPLEMENTATION, repo="app", commit="b" * 40))
        line = branch_line(task)
        check_in("(b') a foreign-repository entry: its repository is named, ancestry is only the quick proof (no false halt)",
                 f"the implementation commit {'b' * 12} (context-manifest, repository app) is not this HEAD: "
                 f"{single_proof('b' * 40)}.", line)
        check_in("(b') and the content proof is against that entry's own checkout", "against that entry's own checkout", line)
        check_not_in("(b') the old halt words survive in no form", "halt when it is not", line)
        seed_branch(task, implementation=dict(IMPLEMENTATION, commit=HEAD40.upper()))
        check_in("(b'') the same commit spelled in capitals is the same commit: HEAD (E9)",
                 "is this HEAD", branch_line(task))
        seed_branch(task, implementation=dict(IMPLEMENTATION, commit=HEAD12))
        check_in("(b''') an abbreviation is never taken for HEAD here: the role's own proof decides (E9, FR-59)",
                 f"is not this HEAD: {single_proof(HEAD12)}", branch_line(task))
        seed_branch(task, implementation=dict(IMPLEMENTATION, commit="abc"))
        check_in("(b'''') a commit that is not 40 hex is printed as given (nothing is padded)",
                 f"the implementation commit abc (context-manifest, repository tests) is not this HEAD: {single_proof('abc')}",
                 branch_line(task))
        seed_branch(task, implementation=dict(IMPLEMENTATION, commit="g" * 40))
        check_in("(b'''') nor is a 40-character string that is not hex ever HEAD", "is not this HEAD:", branch_line(task))
        long_commit = "f" * 50
        seed_branch(task, implementation=dict(IMPLEMENTATION, commit=long_commit))
        line = branch_line(task)
        check_in("(b''''') a commit longer than 12 is cut to 12 in the words, whole in the command the role runs",
                 f"the implementation commit {'f' * 12} (context-manifest, repository tests) is not this HEAD: "
                 f"{single_proof(long_commit)}", line)

        # (c) the manifest's branch is the recorded one, or empty: nothing to warn the role off (E8)
        seed_branch(task, implementation=dict(IMPLEMENTATION, branch=RECORDED))
        line = branch_line(task)
        check_in("(c) the line exists: an absent sentence below is not an absent line", "Branch check:", line)
        check_not_in("(c) a manifest branch equal to the recorded one gets no 'switch to' sentence", "not a branch to switch to", line)
        check_in("(c) and the commit rule stands", f"the implementation commit {HEAD12} (context-manifest) is this HEAD. {COMPARE_COMMITS}", line)
        seed_branch(task, implementation={k: v for k, v in IMPLEMENTATION.items() if k != "branch"})
        line = branch_line(task)
        check_in("(c) no-branch manifest: the line exists, so the absent sentence is not an absent line", "Branch check:", line)
        check_not_in("(c) a manifest with no branch gets none either", "not a branch to switch to", line)
        seed_branch(task, implementation=dict(IMPLEMENTATION, branch=""))
        line = branch_line(task)
        check_in("(c) empty-branch manifest: the line exists, so the absent sentence is not an absent line", "Branch check:", line)
        check_not_in("(c) nor an empty one", "not a branch to switch to", line)

        # (d) several entries: each commit named with its repository, the not-HEAD ones owed the check, in one sentence (E7)
        app = "b" * 40
        seed_branch(task, implementation=None, implementations=[
            dict(IMPLEMENTATION), {"repo": "app", "branch": "feature/x", "commit": app}, {"repo": "docs"}, "not an entry"])
        line = branch_line(task)
        check_in("(d) every entry is listed with its repository, a missing commit by name (FR-41), junk skipped",
                 f"the implementation commits (context-manifest): {HEAD12} (tests) is this HEAD; {'b' * 12} (app) is not "
                 "this HEAD; docs: no commit recorded. The commits that are not HEAD: HEAD must carry their change - "
                 f"`git merge-base --is-ancestor {app} HEAD` exit 0 proves it at once; when it does not (a squash, a rebase, "
                 "or a commit this repository does not know), prove it by content against each entry's own checkout; "
                 "halt only when a change is absent. ", line)
        check_eq("(d) the proof is ONE tail sentence for all the commits that are not HEAD", line.count("The commits that are not HEAD"), 1)
        check_not_in("(d) the old halt words survive in no form", "halt when", line)
        check_in("(d) every manifest branch that is not the recorded one is named as a merge request source branch",
                 f"`{MR_SOURCE}`, `feature/x` in the manifest are merge request source branches, not branches to switch to.", line)
        check_eq("(d) the whole thing is still one paragraph", line.count("\n"), 0)

        # (d') the composite forms no other case reaches (t-1064 N1): a raise in this formatting would be swallowed by
        # the whole-body try and read as "could not be built", so each is pinned whole, word for word
        proof_tail = ("it at once; when it does not (a squash, a rebase, or a commit this repository does not know), prove "
                      "it by content against each entry's own checkout; halt only when a change is absent. ")
        both = [dict(IMPLEMENTATION), {"repo": "app", "commit": app}]
        seed_branch(task, record=None, implementation=None, implementations=both)
        check_eq("(d') several entries and no record: each commit is not known to be HEAD, one tail sentence, the proof owed",
                 branch_line(task),
                 f"Branch check: no branch was recorded at S0 ({BASE_FILE} is absent or unreadable); the implementation "
                 f"commits (context-manifest): {HEAD12} (tests) is not known to be this HEAD; {'b' * 12} (app) is not known "
                 "to be this HEAD. The commits that are not known to be HEAD (HEAD is your own `git rev-parse HEAD`): HEAD "
                 f"must carry their change - `git merge-base --is-ancestor {HEAD40} HEAD` / "
                 f"`git merge-base --is-ancestor {app} HEAD` exit 0 proves {proof_tail}{MR_SENTENCE} {COMPARE_COMMITS}")
        seed_branch(task, implementation=None, implementations=[
            dict(IMPLEMENTATION, branch=""), {"repo": "app", "commit": HEAD40.upper()}])
        check_eq("(d') several entries, all HEAD (one in capitals): nothing is owed, no proof tail, no aside",
                 branch_line(task),
                 f"Branch check: {CHECKOUT}; the implementation commits (context-manifest): {HEAD12} (tests) is this HEAD; "
                 f"{HEAD12.upper()} (app) is this HEAD. {COMPARE_COMMITS}")

        # (e) a detached HEAD is said so, never shown as a branch name (E3)
        seed_branch(task, record=dict(BASE_RECORD, branch="(detached)"))
        line = branch_line(task)
        check_in("(e) a detached record: the HEAD, said detached, in the one descriptive voice of the recorded checkout (t-1064 N2)",
                 f"recorded checkout: detached at {HEAD12} (recorded at S0 in {BASE_FILE})", line)
        check_not_in("(e) I2: no imperative ('be at HEAD' asks for equality, stricter than 'carries the change')", "be at", line)
        check_not_in("(e) '(detached)' is never put between backticks as a branch", "`(detached)`", line)
        check_in("(e) the manifest's branch is still named for what it is", MR_SENTENCE, line)
        seed_branch(task, record=dict(BASE_RECORD, branch=""))
        line = branch_line(task)
        check_in("(e') a record with a HEAD and no branch name says it names none, and still gives the HEAD (same voice)",
                 f"recorded checkout: no branch, HEAD {HEAD12} (recorded at S0 in {BASE_FILE}, which names no branch)", line)
        check_not_in("(e') I2: no imperative here either", "be at", line)

        # (f) a record made late is said to be late, with the record's own reason (E4)
        seed_branch(task, record=dict(BASE_RECORD, late=True, late_why="S5 had already started"))
        check_in("(f) a late record: the lateness and its reason follow the record",
                 f"(recorded at S0 in {BASE_FILE}) (recorded late: S5 had already started);", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, late=True, late_why=""))
        check_in("(f) a late record with no reason names the gap, never an empty parenthesis",
                 "(recorded late: no reason recorded);", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, late="yes"))
        line = branch_line(task)
        check_in("(f) a string 'late': the line exists, so the absent words are not an absent line", f"recorded checkout `{RECORDED}`@", line)
        check_not_in("(f) 'late' is the boolean true only: a string is not lateness", "recorded late", line)

        # (g) no record: no branch is invented; the same proof clause, HEAD meaning the role's own `git rev-parse HEAD` (E1)
        absent = (f"Branch check: no branch was recorded at S0 ({BASE_FILE} is absent or unreadable); the implementation "
                  f"commit {HEAD12} (context-manifest, repository tests) is not known to be this HEAD (HEAD is your own "
                  f"`git rev-parse HEAD`): {single_proof(HEAD40)}. {MR_SENTENCE} {COMPARE_COMMITS}")
        seed_branch(task, record=None)
        check_eq("(g) the record is absent: said so, the commit named, the manifest's branch not a branch to switch to",
                 branch_line(task), absent)
        for label, content in (("a file that is not JSON", "{"), ("a JSON that is not an object", "[1]"),
                               ("a schema this build does not know", json.dumps(dict(BASE_RECORD, schema_version=2))),
                               ("a schema that is true, not 1", json.dumps(dict(BASE_RECORD, schema_version=True)))):
            seed_branch(task, record=content)
            check_eq(f"(g) {label}: read as absent (test_repo_base.load), never as a branch", branch_line(task), absent)

        # (h) the record says git was not usable: its reason is carried, a stray HEAD is not trusted (E2)
        seed_branch(task, record=dict(BASE_RECORD, git="absent", why="git is not on PATH", head="", branch=""))
        line = branch_line(task)
        check_in("(h) git absent: no branch was recorded, and why", "Branch check: no branch was recorded at S0 (git: absent - git is not on PATH);", line)
        check_in("(h) then the commit rule as in (g): the same proof clause, HEAD being the role's own",
                 f"is not known to be this HEAD (HEAD is your own `git rev-parse HEAD`): {single_proof(HEAD40)}", line)
        check_not_in("(h) the old halt words survive in no form", "halt when it is not", line)
        seed_branch(task, record=dict(BASE_RECORD, git="error", why="line one\nline two"))
        line = branch_line(task)
        check_not_in("(h) a record whose git is not ok is not trusted for its head: no HEAD is stated", f"@{HEAD12}", line)
        check_in("(h) a reason with a line break stays on one line", "(git: error - line one line two);", line)
        seed_branch(task, record=dict(BASE_RECORD, git="error", why=""))
        check_in("(h) no reason recorded is said", "(git: error - no reason recorded);", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, git="error", why="w" * 500))
        line = branch_line(task)
        check_in("(h) a long reason: the line exists, so the length bound is not met by an empty line", "Branch check: no branch was recorded", line)
        check("(h) a free-text reason is bounded, the head stays bounded", len(line) < 950, str(len(line)))   # ~900 clipped; 1,215 if the 500 characters were kept
        seed_branch(task, record=dict(BASE_RECORD, head=""))
        check_in("(h) git ok but no HEAD (the contract says never): treated as no record, said in those words",
                 "(git: ok, but the record names no HEAD);", branch_line(task))

        # (h') the limit of a free-text reason, AT and BEYOND (E14): 200 stays whole, 201 is cut and says so
        reason_at = "r" * 200
        seed_branch(task, record=dict(BASE_RECORD, git="error", why=reason_at))
        check_in("(h') a reason of exactly 200 characters is kept whole (AT the limit)", f"(git: error - {reason_at});", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, git="error", why="r" * 201))
        line = branch_line(task)
        shown = line.split("(git: error - ", 1)[1].split(");", 1)[0]
        check("(h') a reason of 201 characters is cut (BEYOND the limit) to at most 200, marked with '...'",
              len(shown) <= 200 and "..." in shown and shown.startswith("r") and shown.endswith("r"), f"{len(shown)}: {shown!r}")
        seed_branch(task, record=dict(BASE_RECORD, late=True, late_why=reason_at))
        check_in("(h') a late reason of exactly 200 characters is kept whole (AT the limit)", f"(recorded late: {reason_at});", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, late=True, late_why="r" * 201))
        shown = branch_line(task).split("(recorded late: ", 1)[1].split(");", 1)[0]
        check("(h') a late reason of 201 characters is cut to at most 200, marked with '...'",
              len(shown) <= 200 and "..." in shown, f"{len(shown)}: {shown!r}")

        # (i) the manifest names no commit: the recorded checkout is the whole check, the source named (E5)
        # N3 (t-1064): no commit means no change to prove, so no branch name is part of any check (I2)
        source_free = (f"Branch check: {CHECKOUT}; the manifest names no implementation commit (source diff), so there "
                       "is no commit to prove: work on the checkout as it stands and say so in your digest; "
                       "compare commits, never branch names; never create or switch a branch.")
        check_not_in("(i) I2: the recorded branch is not called the check", "whole check", source_free)
        no_commit = {k: v for k, v in IMPLEMENTATION.items() if k not in ("commit", "source_sha")}
        seed_branch(task, implementation=no_commit)
        check_eq("(i) an entry with no commit: the unknown is named, with the story's implementation source",
                 branch_line(task), source_free)
        seed_branch(task, implementation=None)
        check_eq("(i) a manifest with no implementation entry: the same", branch_line(task), source_free)
        (task / "work/context-manifest.json").write_text("{", encoding="utf-8")
        check_eq("(i) a manifest that cannot be read: the same, no exception", branch_line(task), source_free)
        (task / "work/context-manifest.json").unlink()
        check_eq("(i) no manifest file at all: the same", branch_line(task), source_free)
        seed_branch(task, implementation=None, implementations=[{"repo": "tests"}, {"repo": "app"}])
        check_eq("(i) several entries, none with a commit: the same", branch_line(task), source_free)
        pipeline_path = task / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        pipeline.pop("implementation_source")
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        check_in("(i) a story that records no implementation source says 'unknown', not an empty word",
                 "(source unknown)", branch_line(task))
        pipeline["implementation_source"] = "diff"
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")

        # (i') neither a record nor a commit: nothing is invented, the role is told to say so
        seed_branch(task, record=None, implementation=no_commit)
        check_eq("(i') no record and no commit: nothing was recorded, said so (FR-41)", branch_line(task), NOTHING)
        seed_branch(task, record=dict(BASE_RECORD, git="absent", why="x", head="", branch=""), implementation=None)
        check_eq("(i') git not usable and no commit: the same", branch_line(task), NOTHING)

        # edges of the strings printed as given (E10)
        seed_branch(task, record=dict(BASE_RECORD, branch="b" * 300))
        check_in("a branch over 200 characters is printed whole (git bounds it, we do not)", f"`{'b' * 300}`", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, branch="feature x"))
        check_in("a branch with a space is printed as given", f"recorded checkout `feature x`@{HEAD12}", branch_line(task))
        seed_branch(task, record=dict(BASE_RECORD, branch="two\nlines"))
        line = branch_line(task)
        check_in("a branch with a line break: the line exists and holds both parts on one line", "`two lines`", line)
        check_eq("a branch with a line break keeps the paragraph whole", line.count("\n"), 0)

        # the line is a courtesy: a reader that fails is named in the line, never raised, never silent (E11, I5)
        seed_branch(task)
        real_load = test_repo_base.load
        test_repo_base.load = lambda _root: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            broken = branch_line(task)
        finally:
            test_repo_base.load = real_load
        check_in("a reader that raises: the line says it could not be built and gives the commit rule (FR-41)",
                 "Branch check: the line could not be built (RuntimeError); compare the implementation commit", broken)
        check_in("and still forbids the switch", "never create or switch a branch", broken)
        test_repo_base.load = lambda _root: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            built = brief_of()
        finally:
            test_repo_base.load = real_load
        check_in("a reader that raises does not stop the brief: the brief is built with the could-not-be-built line",
                 "Branch check: the line could not be built (RuntimeError)", built)
        check_eq("and the line is back once the reader is", branch_line(task).startswith(f"Branch check: recorded checkout `{RECORDED}`"), True)

        # no git call: the record and the manifest are files; the role runs git (patched to refuse, the line is whole) (K3)
        import subprocess as sp
        real_run, real_popen = sp.run, sp.Popen
        def refuse(*_a, **_k):
            raise AssertionError("brief_pack must make no git call")
        sp.run = sp.Popen = refuse
        try:
            quiet = branch_line(task)
        finally:
            sp.run, sp.Popen = real_run, real_popen
        check_in("no git call: the line is built with every process launch refused", f"@{HEAD12}", quiet)

        # (j) the roles are read from the contract: the injection map AND the section "Before the first write" (F-3)
        check_in("(j) the automator at S5 gets the line (its lifecycle slice carries the section)", "Branch check: recorded checkout",
                 brief_of())
        check_in("(j) the automator at S7 gets it too: a repair round enters the repository", "Branch check: recorded checkout",
                 brief_of("qa-automator", "S7", "S7-qa-automator-1"))
        critic = brief_of("qa-code-critic", "S5", "S5-qa-code-critic-1")
        check_not_in("(j) the code critic is injected a lifecycle slice WITHOUT the section: no line, its head is unchanged",
                     "Branch check:", critic)
        check_not_in("(j) the case designer at S4 does not (no lifecycle slice)", "Branch check:",
                     brief_of("qa-case-designer", "S4", "S4-qa-case-designer-1"))
        check_not_in("(j) the runner at S6 does not (its slice is not the lifecycle one)", "Branch check:",
                     brief_of("qa-runner", "S6", "S6-qa-runner-1"))
        check_eq("(j) the set is derived from references/inject-map.json and the section's markers today",
                 sorted(brief_pack._lifecycle_roles()), ["qa-automator"])
        real_ref_json, real_ref = hooklib.load_ref_json, hooklib.ref

        def patched_map(change):
            def load(name):
                doc = real_ref_json(name)
                return change(json.loads(json.dumps(doc))) if name == "inject-map.json" else doc
            return load

        def drop_automator(doc):
            doc["roles"]["qa-automator"] = [p for p in doc["roles"]["qa-automator"] if not p.endswith("/execution-lifecycle.md")]
            return doc

        def add_runner(doc):
            doc["roles"]["qa-runner"].append("plugin:references/slices/qa-runner/execution-lifecycle.md")
            return doc

        def marked_for(*roles):
            """The lifecycle source with the section's marker naming `roles` too (a variant file; hooklib.ref serves it)."""
            source = real_ref("execution-lifecycle.md").read_text(encoding="utf-8").replace("\r\n", "\n")
            assert LIFECYCLE_MARKED in source
            variant = root / "lifecycle-variant.md"
            variant.write_text(source.replace(LIFECYCLE_MARKED, f"<!-- roles: qa-automator, {', '.join(roles)} -->\n## Before the first write"),
                               encoding="utf-8")
            return lambda rel: variant if rel == "execution-lifecycle.md" else real_ref(rel)

        hooklib.load_ref_json = patched_map(drop_automator)
        try:
            check_not_in("(j) a map without the lifecycle entry for the automator: no line (nothing is typed in code)",
                         "Branch check:", brief_of())
        finally:
            hooklib.load_ref_json = real_ref_json
        hooklib.load_ref_json = patched_map(add_runner)
        try:
            check_not_in("(j) a role injected a lifecycle slice whose section is NOT marked for it is not told",
                         "Branch check:", brief_of("qa-runner", "S6", "S6-qa-runner-1"))
            hooklib.ref = marked_for("qa-runner")
            check_in("(j) a role added to the map and to the section's marker is told without a code change",
                     "Branch check:", brief_of("qa-runner", "S6", "S6-qa-runner-1"))
            check_in("(j) and the automator keeps it", "Branch check:", brief_of())
        finally:
            hooklib.load_ref_json, hooklib.ref = real_ref_json, real_ref
        hooklib.ref = marked_for("qa-code-critic")
        try:
            check_in("(j) the critic marked for the section gets the line (the pin of the critic's head moves with the marker)",
                     "Branch check:", brief_of("qa-code-critic", "S5", "S5-qa-code-critic-1"))
        finally:
            hooklib.ref = real_ref
        hooklib.load_ref_json = lambda name: {}
        try:
            check_not_in("(j) an unreadable map: no line, no exception (the brief is a courtesy)", "Branch check:", brief_of())
        finally:
            hooklib.load_ref_json = real_ref_json
        hooklib.ref = lambda rel: root / "no-such-lifecycle.md" if rel == "execution-lifecycle.md" else real_ref(rel)
        try:
            check_not_in("(j) an unreadable lifecycle source: no line, no exception", "Branch check:", brief_of())
        finally:
            hooklib.ref = real_ref
        check_in("(j) the map is restored: the automator has the line again", "Branch check:", brief_of())

        # (m) I2 across the states of the record: the line describes, it never asks the role to be on a branch
        states = [dict(BASE_RECORD), dict(BASE_RECORD, branch="(detached)"), dict(BASE_RECORD, branch=""),
                  dict(BASE_RECORD, late=True, late_why="x"), None, dict(BASE_RECORD, git="error", why="x")]
        for record in states:
            for implementation in ("live", dict(IMPLEMENTATION, commit="a" * 40), None):
                seed_branch(task, record=record, implementation=implementation)
                words = branch_line(task)
                check_not_in(f"(m) I2: no state of the record or the manifest says 'be on' ({record and record.get('branch')!r})",
                             "be on", words)
                check_not_in("(m) I1: and none makes the ancestry answer or the branch name a halt", "halt when", words)
                check_not_in(f"(m) I2: and none asks the role to 'be at' a HEAD ({record and record.get('branch')!r})", "be at", words)
                check_not_in(f"(m) N1: and none is the 'could not be built' line: a raise in the formatting is seen ({record and record.get('branch')!r})",
                             "could not be built", words)
    finally:
        harness.cleanup(root)


def blast_radius_lines() -> None:
    """G1-2 (M13): the S3 brief carries ONE line about work/blast-radius.json, built by `blast_radius.ensure`, in the head."""
    import blast_radius as BR
    import grounding_table as GT
    import test_novelty as TN
    root = harness.temp_project("qa-brief-blast-")
    real_git, real_ensure, real_ceiling = TN._git, BR.ensure, brief_pack.BRIEF_MAX_BYTES
    calls = []
    TN._git = lambda cwd, args, stdin=None: (calls.append(list(args)), real_git(cwd, args, stdin))[1]
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        diff = "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n"
        (task / "work/impl-diff.txt").write_bytes(diff.encode("utf-8"))
        (task / "work/context-manifest.json").write_text(json.dumps({"implementations": [
            {"repo_id": "backend", "diff_path": "qa-factory/artifacts/QA-9/work/impl-diff.txt", "source_sha": "a" * 40}]}), encoding="utf-8")
        (task / "state").mkdir(exist_ok=True)
        (task / "state/controller.json").write_text(json.dumps({"scope": [], "dispatches": {"S3-qa-test-strategist-1": {
            "id": "S3-qa-test-strategist-1", "stage": "S3", "role": "qa-test-strategist", "status": "running", "scope": [],
            "read_first": ["work/ticket-snapshot.json"]}}}), encoding="utf-8")
        index = task / "work/blast-radius.json"

        def brief(write=True, output=None, stage="S3", role="qa-test-strategist", dispatch="S3-qa-test-strategist-1"):
            return brief_pack.build("QA-9", stage, role, dispatch, write=write, output=output)

        def the_line(text):
            found = [ln for ln in text.split("\n## ")[0].splitlines() if ln.startswith("Blast radius index")]
            return found[0] if len(found) == 1 else str(found)

        dry = brief(write=False)
        check_eq("(M13) --dry-run: the line says what is on disk, nothing was built, no file written",
                 (the_line(dry["markdown"]), index.exists(), dry["written"]), ("Blast radius index: absent - not built in this run.", False, []))
        out = brief(output=task / "work" / "side-brief.md")
        check_eq("(M13) --output: the same (the index is not built for a side file)", (the_line(out["markdown"]), index.exists()),
                 ("Blast radius index: absent - not built in this run.", False))
        text = brief()["markdown"]
        line = the_line(text)
        check_eq("(M13) the S3 brief builds the index and names the path BR wrote; before the table exists it says `Read it before labelling`",
                 (index.is_file(), line),
                 (True, "Blast radius index (code; built): qa-factory/artifacts/QA-9/work/blast-radius.json - 1 areas in 1 repositories; "
                        "unmeasured: 1 (no checkout of backend on this machine). Read it before labelling."))
        head_lines = text.split("\n## ")[0].splitlines()
        at = next(i for i, ln in enumerate(head_lines) if ln.startswith("Scope:"))
        check("(M13) the line is the very next line after Scope, and stands before Read first (the head is never shrunk)",
              head_lines[at + 1].startswith("Blast radius index") and 0 <= text.find("Blast radius index") < text.find("Read first,"), head_lines[at + 1][:80])
        check("(M13) one line, at most 300 characters, and not in the file list", len(line) <= 300 and "\n" not in line and text.count("Blast radius index") == 1, str(len(line)))
        calls.clear()
        again = the_line(brief()["markdown"])
        check_eq("(M13) a fresh file: `reused`, no git call at all", (again.split(":")[0], calls), ("Blast radius index (code; reused)", []))
        dry_fresh = the_line(brief(write=False)["markdown"])
        check_eq("(X3) --dry-run on a FRESH file whose repository has no checkout (a retry state) says `reused`, word for word the line the real brief prints (not `stale`)",
                 (dry_fresh, json.loads(index.read_text(encoding="utf-8"))["index"]["repos"][0]["state"]), (again, "no_checkout"))
        GT.table_path(task).write_bytes(b"blast_radius: {}\n")
        check_in("(M13) after the table exists the line names it", "Label the areas in qa-factory/artifacts/QA-9/work/grounding.yaml (blast_radius.areas).",
                 the_line(brief()["markdown"]))
        GT.table_path(task).unlink()
        (task / "work/impl-diff.txt").write_bytes((diff + "\n").encode("utf-8"))
        check_eq("(M13) --dry-run with changed diff bytes: `stale`, the old file untouched",
                 (the_line(brief(write=False)["markdown"]), index.is_file()), ("Blast radius index: stale - not built in this run.", True))
        check_in("(M13) the real brief with changed bytes REBUILDS (link mode: before G1-11 the brief is the only builder)", "(code; built)", the_line(brief()["markdown"]))
        s5 = brief(stage="S5", role="qa-automator", dispatch="S5-qa-automator-1")["markdown"]
        check_not_in("(M13) an S5 brief has no such line", "Blast radius index", s5)

        # the ceiling: AT the brief's own size nothing changes; one byte BEYOND, the head keeps the line and the rest gives way
        size = brief(write=False)["budget_bytes"]
        try:
            brief_pack.BRIEF_MAX_BYTES = size
            at_ceiling = brief(write=False)
            brief_pack.BRIEF_MAX_BYTES = size - 1
            beyond = brief(write=False)
        finally:
            brief_pack.BRIEF_MAX_BYTES = real_ceiling
        check_eq("(M13) AT the ceiling: the brief is the same, the line in the head", (at_ceiling["budget_bytes"], the_line(at_ceiling["markdown"]).startswith("Blast radius index (code;")), (size, True))
        check("(M13) 1 byte BEYOND: the line is still in the head, the brief shrank elsewhere",
              the_line(beyond["markdown"]).startswith("Blast radius index (code;") and beyond["markdown"] != at_ceiling["markdown"], f"{beyond['budget_bytes']} / {size}")

        # a failure is named in the line, never swallowed, and the brief is still written
        def boom(*args, **kwargs):
            raise RuntimeError("boom\nsecond line")

        BR.ensure = boom
        try:
            failed = brief()
        finally:
            BR.ensure = real_ensure
        check_eq("(M13) a failing build: named in the line (one line, the exception and its message), the brief is still written",
                 (the_line(failed["markdown"]), bool(failed["written"])),
                 ("Blast radius index: could not be built (RuntimeError: boom second line) - the driver's S3 preparation builds it.", True))

        # the story has no implementation diff: the line says so
        index.unlink()
        (task / "work/impl-diff.txt").unlink()
        pipe = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipe["implementation_source"] = "current-code"
        (task / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")
        check_eq("(M13) source current-code and no diff: `none`, the word named, no file", (the_line(brief()["markdown"]), index.exists()),
                 ("Blast radius index: none - the implementation source is current-code.", False))
    finally:
        TN._git, BR.ensure, brief_pack.BRIEF_MAX_BYTES = real_git, real_ensure, real_ceiling
        harness.cleanup(root)


def labelling_vocabulary_lines() -> None:
    """OH3-14 / HF1-6: the S3 window-1 brief carries EVERY word of `grounding_labels` and `requirement_grounding_states`, in the one line
    `handoff.grounding_vocabulary_line` builds; an unreadable vocabulary or an empty list is declared in that line, never blank, never a raise.
    (The s3.md phrases moved to design/role-rules.json.)"""
    import handoff as H
    root = harness.temp_project("qa-brief-labels-")
    real_vocabulary, real_allowed, real_ceiling = H.vocabulary, H.allowed, brief_pack.BRIEF_MAX_BYTES
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        (task / "state").mkdir(exist_ok=True)
        base = {"id": "S3-qa-test-strategist-1", "stage": "S3", "role": "qa-test-strategist", "status": "running", "scope": [],
                "read_first": ["work/ticket-snapshot.json"]}

        def register(**extra) -> None:
            (task / "state/controller.json").write_text(json.dumps({"scope": [], "dispatches": {base["id"]: dict(base, **extra)}}), encoding="utf-8")

        def brief(stage="S3", role="qa-test-strategist", dispatch="S3-qa-test-strategist-1", write=False) -> str:
            return brief_pack.build("QA-9", stage, role, dispatch, write=write)["markdown"]

        def the_line(text: str) -> list:
            return [ln for ln in text.split("\n## ")[0].splitlines() if "labels: " in ln]

        labels, states = list(H.vocabulary()["grounding_labels"]), list(H.vocabulary()["requirement_grounding_states"])
        check("(OH3-14) the vocabulary holds both lists (the control the key test needs)", len(labels) > 1 and len(states) > 1, f"{labels} / {states}")

        register(request_binding={"purpose": "s3_labelling"})
        text = brief()
        lines = the_line(text)
        check_eq("(OH3-14) the window-1 brief holds ONE `labels: ...; requirement states: ...` line, in the head (never shrunk)", len(lines), 1)
        missing = [k for k in labels + states if k not in lines[0]]
        check_eq("(OH3-14) EVERY key of grounding_labels and of requirement_grounding_states is in the brief", missing, [])
        check_in("(OH3-14) the line is the one the helper builds (the driver's dispatch text calls the same builder)", H.grounding_vocabulary_line(), lines[0])
        check_in("(OH3-14) the lists are given as words, with no file to read for them", "there is no file to read", lines[0])
        check_not_in("(OH3-14) the brief names no plugin path for the lists", "handoffs/vocabulary", text)
        written = brief(write=True)
        check_in("(OH3-14) the written brief holds the line too", H.grounding_vocabulary_line(), written)

        # AT and one byte BEYOND the ceiling: the head keeps the line
        size = len(text.encode("utf-8"))
        try:
            brief_pack.BRIEF_MAX_BYTES = size
            at_ceiling = brief()
            brief_pack.BRIEF_MAX_BYTES = size - 1
            beyond = brief()
        finally:
            brief_pack.BRIEF_MAX_BYTES = real_ceiling
        check("(OH3-14) AT the ceiling and 1 byte BEYOND it the head still holds the line",
              H.grounding_vocabulary_line() in at_ceiling and H.grounding_vocabulary_line() in beyond)

        # which dispatches get it: window 1 only; the exit window, a dispatch with no binding and another stage get none
        for name, extra in (("exit window (purpose absent)", {}), ("another purpose", {"request_binding": {"purpose": "other"}}),
                            ("a binding that is not a mapping", {"request_binding": "s3_labelling"})):
            register(**extra)
            check_eq(f"(OH3-14) {name}: no such line", the_line(brief()), [])
        register(request_binding={"purpose": "s3_labelling"})
        check_eq("(OH3-14) an S5 brief: no such line", the_line(brief(stage="S5", role="qa-automator", dispatch="S5-qa-automator-1")), [])

        # the vocabulary unreadable, or a list empty: DECLARED in the line, the brief still built
        def gone():
            raise FileNotFoundError("vocabulary.yaml")

        H.vocabulary = gone
        both_gone = the_line(brief())
        check("(OH3-14) vocabulary file missing: both lists declared NONE READABLE in the one line, the brief is built",
              len(both_gone) == 1 and both_gone[0].count("NONE READABLE") == 2 and "grounding_labels" in both_gone[0]
              and "requirement_grounding_states" in both_gone[0], str(both_gone))
        H.vocabulary = real_vocabulary
        H.allowed = lambda name: [] if name == "requirement_grounding_states" else real_allowed(name)
        one_empty = the_line(brief())
        check("(OH3-14) one list empty: it is declared, the other list's words are all there (an empty list is not a blank)",
              len(one_empty) == 1 and one_empty[0].count("NONE READABLE") == 1 and all(k in one_empty[0] for k in labels)
              and "requirement states: NONE READABLE" in one_empty[0], str(one_empty))
        H.allowed = real_allowed

    finally:
        H.vocabulary, H.allowed, brief_pack.BRIEF_MAX_BYTES = real_vocabulary, real_allowed, real_ceiling
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------
# HF2-7 part 4 (GW1-21): the brief reads the answers file, and a halt is open by `resolved`
# ------------------------------------------------------------------------------------------------

STOP_WORDS = "when the requirements were checked"      # QR.where_words("S2 stop"): what the brief says instead of the raw value
WORDS_1_ONE_LINE = "Q1: b Q2: a Q3: until the report Q4: a Q5: a"   # TQR.WORDS_1 on one line, as a shown line carries it
SAME_AS_Q1 = "the person's words: the same text as under Q1"
NO_BREAKAGE_LINE = "the recorded answers could not be read"


def p4_decisions(root, stage="S3", role="qa-test-strategist", pipeline=None, project=None, task="T-1") -> tuple:
    return brief_pack.decisions(pipeline or {}, stage, role, task, project, root)


def p4_story(base: Path, name: str, extra=()) -> Path:
    """F-12586 (Q1 major, Q2 minor, Q3 blocker, Q4 no severity, Q5 blocker) after the person's words 1 at the S2 stop."""
    root = TQR.write_story(base / name, TQR.f12586_rows() + list(extra))
    QR.record_answers(root, TQR.WORDS_1, "S2 stop", "person")
    return root


def p4_lines(base: Path) -> None:
    root = p4_story(base, "k1", [TQR.q("Q6")])      # Q6 is the question nobody answered
    want_shown = [
        f'- Q1 answered {STOP_WORDS}: reading b - "reading 1"; the person\'s words: {WORDS_1_ONE_LINE}',
        f'- Q2 answered {STOP_WORDS}: reading a - "reading 0"; {SAME_AS_Q1}',
        f"- Q3 kept open until the report ({STOP_WORDS}); do not ask it again; {SAME_AS_Q1}",
        f'- Q4 answered {STOP_WORDS}: reading a - "reading 0"; {SAME_AS_Q1}',
        f'- Q5 answered {STOP_WORDS}: reading a - "reading 0"; {SAME_AS_Q1}',
    ]
    want_minimal = ["- Q1 answered: reading b", "- Q2 answered: reading a", "- Q3 kept open until the report; do not ask it again",
                    "- Q4 answered: reading a", "- Q5 answered: reading a"]
    for stage, role in (("S3", "qa-test-strategist"), ("S4", "qa-case-designer")):
        shown, minimal, full = p4_decisions(root, stage, role)
        check_eq(f"K1 hf2-7 P4: {stage} - the brief names every decided question, in register order (T8), the open Q6 not", shown, want_shown)
        check_eq(f"K1 hf2-7 P4: {stage} - the minimal list is the id and the letter, no words", minimal, want_minimal)
        check_eq(f"K1 hf2-7 P4: {stage} - the same words are in the full file ONCE, whole (the other lines point at them)",
                 ("\n".join(full).count("Q3: until the report"), full[0].endswith("the person's words: " + TQR.WORDS_1.strip())),
                 (1, True))
    shown, _minimal, _full = p4_decisions(root)
    check_not_in("K1 hf2-7 P4: a kept-open answer is shown as kept open, not as a reading", "reading", shown[2])
    check_not_in("K1 hf2-7 P4: the raw `where` (S2 stop) never reaches the role", "S2 stop", "\n".join(shown))
    check_eq("K1 hf2-7 P4: without task_root the register is not read - today's output", p4_decisions(None), ([], [], []))
    # FR-6: the lines a role reads go through the checker of the texts a person reads
    for label, lines in (("shown", shown), ("minimal", p4_decisions(root)[1])):
        check_eq(f"FR-6 hf2-7 P4: human_text.problems on the {label} T8 lines is empty",
                 human_text.problems("\n".join(lines), kind="report"), [])
    # a decision on other bytes (the row changed after the answer) and one with no record are asked again: no line
    changed = TQR.write_story(base / "k1-changed", TQR.f12586_rows(), answers=[TQR.rec("Q1", "answered", reading="a")])
    check_eq("K1 hf2-7 P4: an answer given on other bytes is asked again, so the brief has no line for it", p4_decisions(changed), ([], [], []))
    check_eq("H1 hf2-7 P4: no register and no answers file: no T8 line and no breakage line",
             p4_decisions(base / "k1-nothing"), ([], [], []))
    # the journal copy of the same words: dropped when the question lines carry them, kept when other text rides with them
    project = base / "project"
    journal = project / "qa-factory" / "records" / "journal.jsonl"
    journal.parent.mkdir(parents=True)
    notes = ["S3 question stop: " + TQR.WORDS_1.strip(), "never write to Jira", "do not touch the stand\n" + TQR.WORDS_1.strip()]
    journal.write_text("".join(json.dumps({"event": "human_answer", "task": "T-1", "notes": n}) + "\n" for n in notes), encoding="utf-8")
    _s, _m, with_register = p4_decisions(root, project=project)
    _s, _m, journal_only = p4_decisions(None, project=project)
    check_eq("K1 hf2-7 P4: with the register, the journal copy of the words is not repeated; the two other answers stay",
             len([x for x in with_register if x.startswith("- answer")]), 2)
    check_in("K1 hf2-7 P4: ...the standing answer stays", "- answer: never write to Jira", with_register)
    check_in("K1 hf2-7 P4: ...and so does a note with other text before the words", "- answer: do not touch the stand", with_register)
    check_not_in("K1 hf2-7 P4: ...the labelled copy of the words is gone", "- answer: S3 question stop:", with_register)
    check_in("K1 hf2-7 P4: without task_root the journal copy stays (today's output)", "- answer: S3 question stop:", journal_only)


def p4_long_words(base: Path) -> None:
    root = TQR.write_story(base / "long", [TQR.q("Q1")])
    limit = brief_pack.DECISION_CHARS
    head = f'- Q1 answered {STOP_WORDS}: reading a - "reading 0"; the person\'s words: '

    def listed(words: str) -> tuple:
        (root / "work" / "question-answers.jsonl").unlink(missing_ok=True)
        QR.record(root, "Q1", "answered", words, "S2 stop", "person", TQR.row_hash_of(root, "Q1"), reading="a")
        return p4_decisions(root)

    at = "w" * (limit - len(head))
    shown, minimal, full = listed(at)
    check_eq("K3 hf2-7 P4: a line of exactly DECISION_CHARS carries the words inline", (shown, len(shown[0])), ([head + at], limit))
    shown, minimal, full = listed(at + "w")
    check_eq("K3 hf2-7 P4: one character beyond it points at the side file - no half of the words in the brief",
             shown, [f'- Q1 answered {STOP_WORDS}: reading a - "reading 0"; the person\'s words: the whole text is in <decisions>'])
    check_eq("K3 hf2-7 P4: ...the full file has them whole", full, [head + at + "w"])
    check_eq("K3 hf2-7 P4: ...and the minimal line is the id and the letter, no words", minimal, ["- Q1 answered: reading a"])
    result = brief_pack.decisions({}, "S3", "qa-test-strategist", "T-1", None, root)
    check("K3 hf2-7 P4: the pointer is what makes `build` write the side file (truncated is read from `<decisions>`)",
          any("<decisions>" in x for x in result[0]))
    # H24: beyond PERSON_WORDS_MAX the cut names the file that holds the whole text - the answers file, not the journal
    biggest = "x" * brief_pack.PERSON_WORDS_MAX
    check_eq("H24 hf2-7 P4: words of exactly PERSON_WORDS_MAX are whole", listed(biggest)[2], [head + biggest])
    cut = listed(biggest + "y")[2][0]
    check_in("H24 hf2-7 P4: one more is cut and the cut names the answers file", "[cut: 1 more characters, the whole text is in "
             "qa-factory/artifacts/long/work/question-answers.jsonl]", cut)
    check_not_in("H24 hf2-7 P4: ...and does not point at the journal, which holds the same cut", "journal.jsonl", cut)


def p4_breakage(base: Path) -> None:
    """N7: one line only when the store says it could not read (broken line, non-object line, unreadable file)."""
    def notice(root) -> tuple:
        shown, minimal, full = p4_decisions(root)
        return tuple(sum(NO_BREAKAGE_LINE in x for x in part) for part in (shown, minimal, full))

    good = lambda root: TQR.rec("Q1", "answered", reading="a", row_hash=TQR.row_hash_of(root, "Q1"))
    broken = TQR.f12586_story(base / "h2-broken")
    (broken / "work" / "question-answers.jsonl").write_text(good(broken) + "\n{ not json", encoding="utf-8")
    check_eq("K4 hf2-7 P4: a broken line -> ONE line in each of the three lists", notice(broken), (1, 1, 1))
    check_in("K4 hf2-7 P4: ...and the good record is still listed", "- Q1 answered", p4_decisions(broken)[0])
    check_eq("K4 hf2-7 P4: the breakage line comes first", NO_BREAKAGE_LINE in p4_decisions(broken)[0][0], True)
    both = TQR.f12586_story(base / "h2-both")
    (both / "work" / "question-answers.jsonl").write_text(good(both) + "\n{ not json\n[1, 2]", encoding="utf-8")
    check_eq("K4 hf2-7 P4: a broken line and a line that is no object are still ONE line", notice(both), (1, 1, 1))
    folder = TQR.f12586_story(base / "h2-dir")
    (folder / "work" / "question-answers.jsonl").mkdir()
    check_eq("K4 hf2-7 P4: an answers file that cannot be read (a folder): one line, no answers listed",
             (notice(folder), p4_decisions(folder)[0][1:]), ((1, 1, 1), []))
    applied = TQR.f12586_story(base / "h2-applied")
    (applied / "work" / "question-answers.jsonl").write_text(
        good(applied) + "\n" + json.dumps({"kind": "answers_applied", "id": "Q1", "at": "2026-10-26T10:00:00+00:00"}), encoding="utf-8")
    check_eq("K4 hf2-7 P4 (N7): a file holding only `answers_applied` and valid records prints no breakage line", notice(applied), (0, 0, 0))
    odd = TQR.f12586_story(base / "h2-odd")
    (odd / "work" / "question-answers.jsonl").write_text(
        good(odd) + "\n" + TQR.rec("Q99", "answered", reading="a") + "\n" + json.dumps({"kind": "question", "id": "Q2", "status": "zzz"}),
        encoding="utf-8")
    check_eq("K4 hf2-7 P4 (N7): an unknown id and an invalid record are no breakage either", notice(odd), (0, 0, 0))
    check_in("K4 hf2-7 P4: the line says what to do, in words a person could read", "asked again, not guessed", p4_decisions(broken)[0][0])
    check_eq("FR-6 hf2-7 P4: human_text.problems on the breakage line is empty",
             human_text.problems(p4_decisions(broken)[0][0], kind="report"), [])


def p4_halts(base: Path) -> None:
    """H10/H11: a halt is open by `resolved`, exactly as archive_task / stage_guard / retro_numbers read it."""
    import archive_task
    root = p4_story(base, "halts")

    def open_lines(pipeline, with_register=True) -> list:
        return [x for x in p4_decisions(root if with_register else None, "S4", "qa-case-designer", pipeline)[2] if x.startswith("- open halt")]

    lifted = {"stage": "S2", "reason": "2 blocking question(s)", "at": "2026-10-26T10:00:00+00:00", "resolved": True,
              "resolved_at": "2026-10-26T10:05:00+00:00"}
    check_eq("H10 hf2-7 P4: a halt with resolved True is no line - the questions are closed and the brief says so",
             (open_lines({"halts": [lifted]}), len(p4_decisions(root, "S4", "qa-case-designer", {"halts": [lifted]})[2])), ([], 5))
    check_eq("H11 hf2-7 P4: resolved False is open", open_lines({"halts": [dict(lifted, resolved=False)]}),
             ["- open halt S2: 2 blocking question(s)"])
    check_eq("H11 hf2-7 P4: no `resolved` at all is open", open_lines({"halts": [{"stage": "S2", "reason": "x"}]}), ["- open halt S2: x"])
    check_eq("H11 hf2-7 P4: only the open one of two is a line",
             open_lines({"halts": [lifted, {"stage": "S3", "reason": "y", "resolved": False}]}), ["- open halt S3: y"])
    check_eq("H11 hf2-7 P4: entries that are no objects are skipped", open_lines({"halts": ["x", None, 3]}), [])
    # the invariant: the brief and the archive never disagree about whether a halt is open
    for label, halt in (("resolved", lifted), ("unresolved", dict(lifted, resolved=False)), ("no flag", {"stage": "S2", "reason": "r"}),
                        ("an old `status: resolved` and no flag", {"stage": "S2", "reason": "r", "status": "resolved"}),
                        ("an old `status: closed` and no flag", {"stage": "S2", "reason": "r", "status": "closed"}),
                        ("resolved 0", {"stage": "S2", "reason": "r", "resolved": 0})):
        pipeline = {"halts": [halt], "stages": {}}
        check_eq(f"H11 hf2-7 P4: {label} - the brief and archive_task.open_items agree",
                 bool(open_lines(pipeline, with_register=False)), any(x.startswith("unresolved halt") for x in archive_task.open_items(pipeline)))


def p4_build(root: Path, task: Path) -> None:
    """The finding's scenario through `build`: the S2 halt lifted, the questions answered - the S4 brief has the answers and no halt."""
    pipeline_file, readiness, answers = task / "pipeline.json", task / "work" / "requirements-readiness.json", task / "work" / "question-answers.jsonl"
    saved = {p: (p.read_bytes() if p.is_file() else None) for p in (pipeline_file, readiness, answers)}
    try:
        pipeline = json.loads(saved[pipeline_file])
        pipeline["halts"] = [{"stage": "S2", "reason": "2 blocking question(s)", "at": "2026-10-26T10:00:00+00:00", "resolved": True,
                              "resolved_at": "2026-10-26T10:05:00+00:00"}]
        pipeline_file.write_text(json.dumps(pipeline), encoding="utf-8")
        TQR.write_story(task, TQR.f12586_rows())
        QR.record_answers(task, TQR.WORDS_1, "S2 stop", "person")
        built = brief_pack.build("QA-9", "S4", "qa-case-designer", "S4-qa-case-designer-1", write=False)
        brief = built["markdown"]
        check_in("K1 hf2-7 P4 (build): the S4 brief has the answered question, with the words", f'Q5 answered {STOP_WORDS}: reading a - "reading 0"', brief)
        check_in("K1 hf2-7 P4 (build): ...and the kept-open one", "Q3 kept open until the report", brief)
        check_not_in("H10 hf2-7 P4 (build): the lifted halt is not in the brief", "open halt", brief)
        # t-1765 X1 fix-3: the SD head is form, outside the budget (own cap SD_HEAD_MAX_BYTES), so the 6 KB pin is on the body.
        check("K1 hf2-7 P4 (build): the brief body is under 6 KB", built["budget_bytes"] <= 6 * 1024, str(built["budget_bytes"]))
        pipeline["halts"][0]["resolved"] = False
        pipeline_file.write_text(json.dumps(pipeline), encoding="utf-8")
        again = brief_pack.build("QA-9", "S4", "qa-case-designer", "S4-qa-case-designer-1", write=False)["markdown"]
        check_in("H11 hf2-7 P4 (build): the same halt not resolved is in the brief", "open halt S2: 2 blocking question(s)", again)
        # the brief of a story with no register is the brief it always was
        readiness.unlink()
        answers.unlink()
        check_not_in("H1 hf2-7 P4 (build): no register, no T8 line", "Q5 answered", brief_pack.build("QA-9", "S4", "qa-case-designer", "S4-qa-case-designer-1", write=False)["markdown"])
    finally:
        for path, data in saved.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)


# --- SC1-10 (t-1301): the scout's and the tester's briefs, the doors of the documents no role is injected ------------------

def sc1_10_lines() -> None:
    import hooklib
    import inject_context as I
    import context_bundle
    from unittest.mock import patch
    stage_of = {role: st["id"] for st in hooklib.load_ref_json("stages.json")["stages"] for role in st.get("roles") or []}
    root = harness.temp_project("qa-brief-sc110-")
    real_ceiling = brief_pack.BRIEF_MAX_BYTES

    def brief(role: str, name: str = "1", **kw) -> dict:
        return brief_pack.build("QA-9", stage_of[role], role, f"{stage_of[role]}-{role}-{name}", write=False, **kw)

    def line_with(text: str, needle: str) -> str:
        return next((x for x in text.splitlines() if x.startswith("- ") and needle in x), "")

    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        work = task / "work"
        strategy = root / "qa-factory" / "strategy"
        strategy.mkdir(parents=True, exist_ok=True)
        check("B-K5 precondition: the context bundle is not a SLICE_INSTEAD table entry any more (file_lines names it itself)",
              "work/context-bundle.json" not in brief_pack.SLICE_INSTEAD and brief_pack.BUNDLE_JSON == "work/context-bundle.json")

        # B-K2: the tester's diff line is the diff pass in the every-line form; with no shell it is the text of before
        (work / "impl-diff.txt").write_text("x" * 10, encoding="utf-8")
        tester = brief("qa-requirements-tester")["markdown"]
        diff_line = line_with(tester, "impl-diff.txt")
        check_in("B-K2 the tester's brief: the diff line names --files-only", "--files-only", diff_line)
        check_in("B-K2 ... and the number that makes it every changed line of every hunk", "--max-lines 100000", diff_line)
        check_not_in("B-K2 ... and no longer says 'read EVERY hunk, whole'", "read EVERY hunk, whole", diff_line)
        with patch.object(brief_pack, "role_has_bash", lambda role: False):
            plain = line_with(brief("qa-requirements-tester", "2")["markdown"], "impl-diff.txt")
        check_in("B-K2 with no shell: the text of before, word for word",
                 " - required source: read EVERY hunk, whole, in slices (Read with offset/limit, <= 400 lines each); "
                 "`Grep -n` alone is not reading it", plain)
        check_not_in("B-K2 ... and no script named to a role without Bash", "diff_pass.py", plain)

        # B-K4: the doors. The brief names the document with its size; the injection no longer delivers it.
        (strategy / "project-profile.md").write_text("PROFILE_SENTINEL " + "p" * 583, encoding="utf-8")
        (strategy / "test-strategy.md").write_text("STRATEGY_SENTINEL " + "s" * 582, encoding="utf-8")
        scout = brief("qa-scout")["markdown"]
        check_in("B-K4 the scout's brief names the project profile with its size", "- qa-factory/strategy/project-profile.md (600 B)", scout)
        absent_text = (strategy / "project-profile.md").read_bytes()
        (strategy / "project-profile.md").unlink()
        check_in("B-K4 (temporal: before the document exists) the line says it is not written yet, and is still there",
                 "- qa-factory/strategy/project-profile.md: not written yet", brief("qa-scout", "3")["markdown"])
        (strategy / "project-profile.md").write_bytes(absent_text)
        for role in ("qa-case-designer", "qa-retro-analyst"):
            check_in(f"B-K4 {role}'s brief names the test strategy with its size", "- qa-factory/strategy/test-strategy.md (600 B)",
                     brief(role)["markdown"])
        imap = I.load_map()
        for role, tail in (("qa-scout", "strategy/project-profile.md"), ("qa-case-designer", "strategy/test-strategy.md"),
                           ("qa-retro-analyst", "strategy/test-strategy.md")):
            check_eq(f"B-K4 {role}: the injection map no longer names {tail}", [e for e in imap["roles"][role] if e.endswith(tail)], [])
        for role, tail in (("qa-requirements-tester", "strategy/project-profile.md"), ("qa-test-strategist", "strategy/project-profile.md"),
                           ("qa-test-strategist", "strategy/test-strategy.md"), ("qa-runner", "strategy/project-profile.md")):
            check(f"B-K4 control: {role} is still injected {tail} (only the three entries of F3 went)",
                  any(e.endswith(tail) for e in imap["roles"][role]))
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        check("B-K4 collect_blocks: the scout's blocks do not carry the profile",
              "PROFILE_SENTINEL" not in "\n".join(I.collect_blocks("qa-scout", imap)))
        check("B-K4 control: the same call for the tester (still injected) does carry it, so the sentinel is findable",
              "PROFILE_SENTINEL" in "\n".join(I.collect_blocks("qa-requirements-tester", imap)))
        for role in ("qa-case-designer", "qa-retro-analyst"):
            check(f"B-K4 collect_blocks: {role}'s blocks do not carry the strategy",
                  "STRATEGY_SENTINEL" not in "\n".join(I.collect_blocks(role, imap)))

        # B-K4 / F1 (fix round t-1313): a project that keeps its own strategy documents (`strategy_documents[]`) gets THOSE named
        # by the door and injected by the map - one function, `config_contract.strategy_document`, decides both. Killing
        # mutation: make `brief_pack._resolve` skip the call (the brief names qa-factory/strategy/... "not written yet" again).
        import config_contract
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "test-strategy.md").write_text("OWN_DOC_MARK " + "o" * 687, encoding="utf-8")
        (root / "docs" / "faq.md").write_text("OWN_FAQ_MARK " + "f" * 287, encoding="utf-8")
        (strategy / "faq.md").write_text("CONVENTIONAL_FAQ " + "c" * 100, encoding="utf-8")

        def entries(*paths: str) -> list:
            return [{"path": p, "provenance": "pre_existing", "editable": False} for p in paths]

        try:
            set_config(root, strategy_documents=entries("docs/test-strategy.md", "docs/faq.md"))
            for role in ("qa-case-designer", "qa-retro-analyst"):
                text = brief(role, "20")["markdown"]
                check_in(f"B-K4 F1: {role}'s door names the project's own test strategy, with its size", "- docs/test-strategy.md (700 B)", text)
                check_not_in(f"B-K4 F1: {role}: ... and not the conventional path", "qa-factory/strategy/test-strategy.md", text)
            fa_text = brief("qa-failure-analyst", "20")["markdown"]
            check_in("B-K4 F1: the failure analyst's faq door (the same defect) names the project's own faq", "- docs/faq.md (300 B)", fa_text)
            for attr in [a for a in dir(hooklib) if "CACHE" in a]:
                setattr(hooklib, attr, None)
            injected = "\n".join(I.collect_blocks("qa-test-strategist", imap))
            check("B-K4 F1: the strategist is injected the SAME file the doors name (one function, both sides)",
                  "OWN_DOC_MARK" in injected and "STRATEGY_SENTINEL" not in injected)
            check_eq("B-K4 F1: the one function names that file", config_contract.strategy_document(
                hooklib.load_config(), "test-strategy.md"), "docs/test-strategy.md")
            # the edges of the resolver: every one of them keeps the conventional path
            for label, cfg in (("two entries with one basename", entries("docs/test-strategy.md", "other/test-strategy.md")),
                               ("an absolute entry", entries((root / "elsewhere" / "test-strategy.md").as_posix())),
                               ("an empty list", []), ("a list of non-objects", ["docs/test-strategy.md"]),
                               ("not a list", "docs/test-strategy.md")):
                set_config(root, strategy_documents=cfg)
                check_in(f"B-K4 F1 edge ({label}): the door keeps the conventional path", "- qa-factory/strategy/test-strategy.md (600 B)",
                         brief("qa-case-designer", "21")["markdown"])
            check("B-K4 F1 edge: no strategy_documents, an empty name, a config that is not an object -> None",
                  config_contract.strategy_document({}, "test-strategy.md") is None and
                  config_contract.strategy_document({"strategy_documents": entries("docs/x.md")}, "") is None and
                  config_contract.strategy_document(None, "test-strategy.md") is None and
                  config_contract.strategy_document(["docs/test-strategy.md"], "test-strategy.md") is None)
        finally:
            set_config(root, strategy_documents=None)
            (strategy / "faq.md").unlink()

        # B-K4: the tester's templates are named by the ABSOLUTE path of the running copy, and the files are there
        templates = [line_with(tester, f"references/templates/{name}.md") for name in ("requirements-register", "understanding")]
        for name, line in zip(("requirements-register", "understanding"), templates):
            path = line[2:].split(" (")[0]
            expect = (brief_pack.HERE.parent / "references" / "templates" / f"{name}.md").as_posix()
            check_eq(f"B-K4 the tester's brief names the {name} template by the running copy's absolute path", path, expect)
            check("B-K4 ... and the file is there (a path that cannot be read is a defect of the install)", Path(path).is_file(), path)
        check_eq("B-K4 _resolve of a plugin: name is its own display and its path (no project folder in it)",
                 brief_pack._resolve("plugin:references/x.md", task, root),
                 ((brief_pack.HERE.parent / "references/x.md").as_posix(), Path((brief_pack.HERE.parent / "references/x.md").as_posix())))
        check("B-K4 a template the install lacks is named with 'not written yet', never dropped",
              "not written yet" in brief_pack.file_lines(["plugin:references/templates/no-such-template.md"], task, root)[0])

        # B-K5: the bundle line. current view -> the view; anything else -> the JSON by ranges, byte for byte what it was.
        (work / "context-bundle.json").write_text("{}", encoding="utf-8")
        view = work / "context-bundle.lines.md"
        view.write_bytes(b"# view\n")      # bytes: write_text turns the LF into CRLF on Windows and the size line would differ
        old_line = "- work/context-bundle.json: do not read whole - `Grep -n the case's requirement ids, then Read the range`"
        view_line = ("- qa-factory/artifacts/QA-9/work/context-bundle.lines.md (7 B) - the bundle, one line per fact, source and candidate; "
                     "the JSON (work/context-bundle.json) is the record for any field the view does not show")
        for role in ("qa-requirements-tester", "qa-test-strategist"):
            with patch.object(context_bundle, "view_status", create=True, return_value="current"):
                text = brief(role, "5")["markdown"]
            check_in(f"B-K5 {role}: a current view is named, with its size", view_line, text)
            check_not_in(f"B-K5 {role}: ... and the JSON is not offered as the thing to Grep", old_line, text)
            for status in ("stale", "absent", "something-else"):
                with patch.object(context_bundle, "view_status", create=True, return_value=status):
                    text = brief(role, "6")["markdown"]
                check_in(f"B-K5 {role}: view {status} -> the line of before, byte for byte", old_line, text)
                check_not_in(f"B-K5 {role}: view {status} -> the view is not named", "context-bundle.lines.md", text)
            with patch.object(context_bundle, "view_status", create=True, side_effect=RuntimeError("boom")):
                check_in(f"B-K5 {role}: a reader that raises -> the line of before (the brief is always built)", old_line,
                         brief(role, "7")["markdown"])
        view.write_bytes(b"v" * (brief_pack.SLICE_BYTES + 1))
        with patch.object(context_bundle, "view_status", create=True, return_value="current"):
            big = line_with(brief("qa-requirements-tester", "8")["markdown"], "context-bundle.lines.md")
        check_in("B-K5 a view over the whole-read limit carries 'slice it' (the guard would close it otherwise)",
                 " - slice it: `Grep -n` first, then Read with offset/limit", big)
        view.write_bytes(b"v" * brief_pack.SLICE_BYTES)
        with patch.object(context_bundle, "view_status", create=True, return_value="current"):
            check_not_in("B-K5 ... and one at exactly the limit does not", "slice it",
                         line_with(brief("qa-requirements-tester", "9")["markdown"], "context-bundle.lines.md"))
        view.unlink()
        with patch.object(context_bundle, "view_status", create=True, return_value="current"):
            check_in("B-K5 'current' with the view file gone: the line of before (nothing to point at)", old_line,
                     brief("qa-requirements-tester", "10")["markdown"])
        check_in("B-K5 the real reader, a view that was never written: the line of before",
                 old_line, brief("qa-requirements-tester", "11")["markdown"])
        shell_lines = brief_pack.file_lines(["work/context-bundle.json"], task, root, shell=False)
        check_eq("B-K5 a role with no shell gets the same line (it names no script)", shell_lines,
                 brief_pack.file_lines(["work/context-bundle.json"], task, root, shell=True))

        # B-K5 integration (t-1308, cross-part point 1; fix round t-1313): the REAL writer (context_bundle.py) and the REAL
        # reader (view_status, view_path) together, no patch: every case above runs on a stand-in. Killing mutation: spell the
        # view's name differently in `brief_pack._bundle_view` (the brief then names a file nobody wrote, or none).
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
        (root / "change.diff").write_text("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n"
                                          "-print('a')\n+print('b')\n", encoding="utf-8")
        real_manifest = root / "real-manifest.json"
        real_manifest.write_text(json.dumps({
            "ticket": "QA-9", "implementations": [{"repo_id": "app", "source_sha": "abc", "diff_path": "change.diff"}],
            "changed_areas": ["src"], "existing_coverage": [{"test": "tests/test_a.py"}], "constraints": ["no writes"],
            "facts": [{"id": "R-1", "path": "src/a.py", "line": 7, "source": "diff", "requirement": "REQ-1", "value": "v", "note": "n"}],
            "known_paths": ["src/a.py"], "unresolved_facts": []}), encoding="utf-8")
        real_json = work / "context-bundle.json"
        real_view = work / "context-bundle.lines.md"
        real_view.unlink(missing_ok=True)
        built = harness.run_script("context_bundle.py", "--manifest", real_manifest, "--output", real_json, "--root", root, cwd=root)
        check("B-K5 integration: the real writer exits 0 and writes the JSON and the view",
              built.returncode == 0 and real_json.is_file() and real_view.is_file(), (built.stdout or "") + (built.stderr or ""))
        n = real_view.stat().st_size
        real_size = f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"
        for role in ("qa-requirements-tester", "qa-test-strategist"):
            text = brief(role, "30")["markdown"]
            check_in(f"B-K5 integration {role}: the brief names the view the writer wrote, with its size",
                     f"- qa-factory/artifacts/QA-9/work/context-bundle.lines.md ({real_size}) - the bundle, one line per fact", text)
            check_not_in(f"B-K5 integration {role}: ... and not the JSON by ranges", old_line, text)
        real_json.write_text(real_json.read_text(encoding="utf-8") + " ", encoding="utf-8")       # ONE byte
        for role in ("qa-requirements-tester", "qa-test-strategist"):
            text = brief(role, "31")["markdown"]
            check_in(f"B-K5 integration {role}: one byte of the JSON changed -> the line of before", old_line, text)
            check_not_in(f"B-K5 integration {role}: ... and the stale view is not named", "context-bundle.lines.md", text)
        stale = harness.run_script("context_bundle.py", "--validate", real_json, cwd=root)
        check("B-K5 integration: --validate says the view is stale", stale.returncode == 0 and
              json.loads(stale.stdout).get("view") == "stale", (stale.stdout or "") + (stale.stderr or ""))

        # B-K7: a door is never trimmed away. BRIEF_MAX_BYTES = 1 cannot be met: every line that is not a door goes, the
        # doors stay and the brief goes out over the ceiling (it never refuses).
        door_names = {role: [n for n in brief_pack.ROLE_FILES[role] if n.startswith(("project:", "plugin:"))]
                      for role in ("qa-scout", "qa-requirements-tester", "qa-case-designer", "qa-retro-analyst")}
        check_eq("B-K7 the doors of the four roles are the F3 documents and the two templates (and the scout's readiness)",
                 door_names, {"qa-scout": ["project:readiness.json", "project:strategy/project-profile.md"],
                              "qa-requirements-tester": ["plugin:references/templates/requirements-register.md",
                                                         "plugin:references/templates/understanding.md"],
                              "qa-case-designer": ["project:strategy/test-strategy.md"],
                              "qa-retro-analyst": ["project:strategy/test-strategy.md"]})
        try:
            for role, names in door_names.items():
                brief_pack.BRIEF_MAX_BYTES = real_ceiling
                whole = brief(role, "12")
                doors = brief_pack.file_lines(names, task, root, True)
                others = [x for x in whole["files"] if x not in doors]
                check(f"B-K7 {role} (control): the full brief holds the doors and at least one line that is not a door",
                      all(d in whole["files"] for d in doors) and bool(others), str(whole["files"]))
                # AT the ceiling: the full size is kept whole; ONE byte below it, exactly the LAST non-door line goes
                brief_pack.BRIEF_MAX_BYTES = whole["budget_bytes"]
                at = brief(role, "13")
                check_eq(f"B-K7 {role}: AT the brief's own budget nothing is trimmed", at["files"], whole["files"])
                brief_pack.BRIEF_MAX_BYTES = whole["budget_bytes"] - 1
                below = brief(role, "14")
                # N4: a trimmed file is SAID (`## Not in the brief`), and that line costs bytes, so one byte below may take more than
                # one line; what holds is that the lines taken are the TAIL of the non-door lines, in order, and that the brief names them.
                gone = [x for x in whole["files"] if x not in below["files"]]
                check_eq(f"B-K7 {role}: one byte below, only the tail of the non-door lines went (at least the last one)",
                         (bool(gone), gone == others[-len(gone):] if gone else False), (True, True))
                check("B-K7 " + role + ": ... and the brief says so under `## Not in the brief`",
                      f"- {len(gone)} input file(s) - read " in below["markdown"] and "-files.md" in below["markdown"])
                brief_pack.BRIEF_MAX_BYTES = 1
                squeezed = brief(role, "15")
                check_eq(f"B-K7 {role}: an unmeetable ceiling leaves exactly the doors, in order, and the brief is built",
                         squeezed["files"], doors)
                check(f"B-K7 {role}: ... larger than the ceiling (a door is not lost to keep a number)", squeezed["bytes"] > 1)
                for door in doors:
                    check_in(f"B-K7 {role}: the door line is in the text itself", door, squeezed["markdown"])
        finally:
            brief_pack.BRIEF_MAX_BYTES = real_ceiling

        # B-K9 (spec t-1765 X1, B-D, "moved"): what the old role files said about files that are not injected is now done by the
        # brief itself - it names each door with its path, and a file that is there with its size - and by the card and the
        # `--save` help. Keys at the new carriers; a wrong key is reported absent.
        for role in ("qa-scout", "qa-requirements-tester", "qa-case-designer"):
            built = brief(role, "17")
            doors = brief_pack.file_lines(door_names[role], task, root, True)
            check(f"B-K9 moved {role}: the brief names every door it does not inject, in its file lines",
                  bool(doors) and all(d in built["files"] for d in doors), str(built["files"]))
            check(f"B-K9 moved {role}: ... a door that exists carries its size",
                  any(re.search(r" \(\d+(\.\d)? (B|KB)\)", d) for d in doors), str(doors))
        tester_brief = brief("qa-requirements-tester", "18")["markdown"]
        check_in("B-K9 moved tester: the card carries the flag of the number (`--max-lines 100000`)", "--max-lines 100000", tester_brief)
        check_not_in("B-K9 moved control: a wrong flag value is not on the card", "--max-lines 99999", tester_brief)
    finally:
        harness.cleanup(root)


def oh3_34_p1_areas_section() -> None:
    """OH3-34 (K4, K5): the S4 brief of the case designer and the case critic has `## P1 areas`: one line per area with the ids of the
    requirements sizing matched to it; ONE line when none matched; "sizing not recorded" when work/sizing.json is absent. Other stages
    and roles have no such section."""
    root = harness.temp_project("qa-brief-p1-areas-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")
        sizing = task / "work" / "sizing.json"

        def brief(role="qa-case-designer", stage="S4") -> str:
            return brief_pack.build("QA-9", stage, role, f"{stage}-{role}-1", write=False)["markdown"]

        check_in("K5 oh3-34: no sizing.json -> 'sizing not recorded'", "## P1 areas\n\n- sizing not recorded", brief())
        def areas(state="areas", read=True, named=(), no_surface=()):
            return {"state": state, "register_read": read, "named": list(named), "no_surface": list(no_surface)}

        def record(requirements, **kw) -> None:
            sizing.write_text(json.dumps({"requirements": requirements, "areas": areas(**kw)}), encoding="utf-8")

        record([{"r": "R-1", "area_match": "budgets and spend tracking"}, {"r": "R-2", "area_match": None},
                {"r": "R-3", "area_match": "budgets and spend tracking"}, {"r": "R-4", "area_match": "workflow execution"}],
               named=["budgets and spend tracking", "workflow execution"])
        for role in ("qa-case-designer", "qa-case-critic"):
            text = brief(role)
            check_in(f"K4 oh3-34: {role}: the section names the area with its requirement ids",
                     "## P1 areas\n\n- budgets and spend tracking: R-1, R-3\n- workflow execution: R-4\n", text)
            check_not_in(f"K4 oh3-34: {role}: a requirement outside every area is not listed", "R-2", text.split("## P1 areas")[1].split("## Commands")[0])
        none = [{"r": "R-1", "area_match": None}]
        record(none, named=["a/b.py"])
        check_in("K5 oh3-34: an area named a path, the register was read, nothing matched: ONE line",
                 "## P1 areas\n\n- no requirement of this story falls in a P1 area\n", brief())
        # B-2 (FR-41, AR-28): that line is a fact only when code checked something; the other states say what is unknown
        record(none, named=["a/b.py"], no_surface=["checkout flow"])
        text = brief()
        check_in("B-2 oh3-34: an area with no path is listed for the designer's own judgment",
                 "- checkout flow: names no path, so code could not place requirements in it", text)
        check_in("B-2 oh3-34: ... and the 'none falls' line says it is about the areas that name a path", "falls in a P1 area that names a path", text)
        record(none, no_surface=["checkout flow", "payments"])
        text = brief()
        check_not_in("B-2 oh3-34: every area names no path -> the 'no requirement falls' line is NOT printed (nothing was checked)", "no requirement of this story falls", text)
        check_in("B-2 oh3-34: ... each area is listed", "- payments: names no path", text)
        record(none, state="no_file")
        text = brief()
        check_not_in("B-2 oh3-34: no P1 areas at all -> no 'no requirement falls' line", "no requirement of this story falls", text)
        check_in("B-2 oh3-34: ... the line says code placed none, with the strategy's state", "the strategy names no P1 areas (state: no_file), so code placed none", text)
        record([], read=False, named=["a/b.py"])
        text = brief()
        check_not_in("B-2 oh3-34: register refused -> no 'no requirement falls' line", "no requirement of this story falls", text)
        check_in("B-2 oh3-34: ... the unread register is said", "the register was not read", text)
        sizing.write_text(json.dumps({"requirements": none}), encoding="utf-8")
        check_in("B-2 oh3-34: a sizing.json from before the areas record is 'not recorded', never a negative", "- sizing not recorded", brief())
        sizing.write_text("{broken", encoding="utf-8")
        check_in("K5 oh3-34: a broken sizing.json is 'not recorded', never a crash", "- sizing not recorded", brief())
        sizing.write_text(json.dumps({"requirements": [{"r": "R-1", "area_match": "x area"}]}), encoding="utf-8")
        check_not_in("oh3-34: another role at S4 has no section", "## P1 areas", brief("qa-test-strategist"))
        check_not_in("oh3-34: the same role at another stage has no section", "## P1 areas", brief("qa-case-designer", "S5"))
    finally:
        harness.cleanup(root)


def form_bytes() -> int:
    """F11 (t-1701 D5-C): the bytes of `## Your final message` in the S5 automator fixture's brief (two scope ids). The section
    is a door like the card and is never trimmed, so the fixture's 6 KB pins below hold for the brief as it was PLUS this
    section: each re-pin adds it to the ceiling or to the size bound, never raises either by a constant."""
    lines = brief_pack.digest_template_lines("qa-automator", "S5", "S5-qa-automator-1", {"scope": ["TC-001", "TC-002"]})
    return len("\n".join(lines).encode("utf-8")) + 1


FIXED_SCRIPTS = "/builds/dev1/yml-text-factory/ai-packages/qa-factory/scripts"     # the CI checkout's scripts folder


def approach_scenario(task: Path, root: Path) -> None:
    """TQ1-11 fix 2 (B-1), all on the REAL `approach_forms` (no patch): the S5 automator brief of the pinned fixture."""
    config = root / "qa-factory/config.json"
    original = config.read_bytes()

    def build(ceiling=None, write=False, scripts=None):
        # t-1765 X1 fix-4 (K6): the S5 card prints `python "<scripts folder>/<script>"`; the pins below sit a few bytes under 6 KB, so the
        # folder is a FIXED string (the length of a CI checkout path) - the scenario tests the cut order, not the machine it runs on.
        real, real_scripts = brief_pack.BRIEF_MAX_BYTES, brief_pack.SCRIPTS
        brief_pack.BRIEF_MAX_BYTES = ceiling or real      # N4: the REAL ceiling; the digest template is outside the budget (F-4)
        brief_pack.SCRIPTS = scripts or FIXED_SCRIPTS
        try:
            return brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1", write=write)
        finally:
            brief_pack.BRIEF_MAX_BYTES, brief_pack.SCRIPTS = real, real_scripts

    def words(text: str, label: str) -> None:
        check_in(f"{label}: the gate A word is inline", "gate A (approved): Gate A: approved.", text)
        check_in(f"{label}: `## The person's words` is there", "## The person's words that concern you", text)
        check_in(f"{label}: the Branch check line stays", f"Branch check: {CHECKOUT}", text)

    try:
        seed_story_for_s5(task, root, "Gate A: approved. Proceed to S5 as it stands; no split.")
        # K-nothing: a project with nothing recorded gets ONE line <= 200 B, never the 559 B block
        forms = brief_pack.approach_forms("qa-automator", root, task)
        one = forms[2]
        check_eq("nothing recorded -> ONE line", len(one), 1)
        check("nothing recorded: the line says so and where it is recorded", "nothing recorded" in one[0] and "onboarding topic 3" in one[0])
        for level in (2, 1, 0):
            for line in forms[level]:
                check(f"every form <= {brief_pack.APPROACH_SHORT_BYTES} B (level {level}): {len(line.encode('utf-8'))} B",
                      len(line.encode("utf-8")) <= brief_pack.APPROACH_SHORT_BYTES)
        check_eq("AT the limit: a 200 B line passes the predicate", len(("x" * 200).encode("utf-8")) <= brief_pack.APPROACH_SHORT_BYTES, True)
        check_eq("BEYOND it (control): a 201 B line fails the predicate", len(("x" * 201).encode("utf-8")) <= brief_pack.APPROACH_SHORT_BYTES, False)
        # the real brief at the normal ceiling: nothing recorded costs one short line (digests inline, map as before)
        nothing = build(write=True)
        check("nothing recorded: the brief is under 6 KB", nothing["budget_bytes"] <= 6 * 1024)
        words(nothing["markdown"], "K6 nothing recorded")
        check_in("K6 ... and the standing warning and the S5 waiver, inline", "standing: tracker_write: no", nothing["markdown"])
        check_in("K6 ... the S5 waiver", 'S5 block "vcs-1: uncommitted changes" -> go on', nothing["markdown"])
        # K6 fix-4: the card is checkout-path independent. The scenario's own build pins the folder; a build that does NOT pin it
        # (the negative control) prints the running copy's path and differs.
        for running in ("/s", "/" + "x" * 150):               # the running copy at a short and at a long checkout path
            was = brief_pack.SCRIPTS
            brief_pack.SCRIPTS = running
            try:
                at_path = build(write=True)["markdown"]
            finally:
                brief_pack.SCRIPTS = was
            check_eq(f"K6 path independence: the scenario build at a {len(running)}-char running path is the same brief", at_path, nothing["markdown"])
        real_scripts = brief_pack.SCRIPTS
        brief_pack.SCRIPTS = "/" + "x" * 150
        try:
            unpinned = brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1", write=True)["markdown"]
        finally:
            brief_pack.SCRIPTS = real_scripts
        check("K6 negative control: an unpinned build at a 150-char folder prints that folder in its card, the pinned brief does not", f'python "/{"x" * 150}/<script>"' in unpinned and "x" * 150 not in nothing["markdown"])
        # a project that recorded its approach
        cfg = json.loads(original.decode("utf-8"))
        cfg["test_data"] = {"accounts_by_role": "created per test through the admin API", "seeds": "factories in tests/factories.py",
                            "generators": "unknown", "pii_and_masking": ["x"], "cleanup_owner": "the suite", "shared_records": []}
        config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        full = build(ceiling=64 * 1024)
        check_in("recorded approach, roomy ceiling: the full block", "- test data: qa-factory/config.json `test_data`", full["markdown"])
        # K-priority: the ceiling cuts the approach BEFORE the person's words, level by level
        step = build(ceiling=full["budget_bytes"] - 1)
        check_not_in("approach cut first: one byte short of the full brief, the full block is gone", "- test data:", step["markdown"])
        check_in("... to its one-line form", "Project approach (cut for room)", step["markdown"])
        words(step["markdown"], "approach cut first (one line)")
        check_in("... and the person's words stay whole inline (the standing warning)", "standing: tracker_write: no", step["markdown"])
        normal = build(write=True)
        check("recorded approach at the 6 KB ceiling: under it", normal["budget_bytes"] <= 6 * 1024)
        check_not_in("approach cut before the person's words at the ceiling: no full block at 6 KB", "- test data:", normal["markdown"])
        words(normal["markdown"], "K6 approach cut before the person's words at 6 KB")
        check_in("K6 ... the standing warning inline", "standing: tracker_write: no", normal["markdown"])
        check_in("K6 ... the S5 waiver inline", 'S5 block "vcs-1: uncommitted changes" -> go on', normal["markdown"])
        for ceiling, label in ((1, "1-byte"), (2 * 1024, "2 KB")):
            tight = build(ceiling=ceiling)
            check_not_in(f"{label} ceiling: the approach block is cut, never the words", "- test data:", tight["markdown"])
            check_in(f"{label} ceiling: the person's words or their pointer are in the brief", "## The person's words that concern you", tight["markdown"])
            check("... a words line is there: the gate A word or the pointer to the decisions file",
                  "gate A (approved): Gate A:" in tight["markdown"] or "S5-qa-automator-1-decisions.md" in tight["markdown"])
        # overflow with a recorded approach: the shortened gate A line is still produced
        seed_story_for_s5(task, root, "Gate A: approved. " + "Keep every UI case in scope. " * 400)
        over = build(write=True)
        check("overflow, approach recorded: under 6 KB", over["budget_bytes"] <= 6 * 1024)
        # The approach block never changes what happens to the words: the same overflow brief of a project with NOTHING recorded
        # (its block is the first thing cut too) shows the same words state - whatever the card of the day costs.
        config.write_bytes(original)
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        bare = build(write=True)
        for needle in ("gate A (approved): Gate A: approved.", "S5-qa-automator-1-decisions.md", f"Branch check: {CHECKOUT}"):
            check_eq(f"overflow: {needle[:30]!r} is there with the approach recorded exactly when it is there without", needle in over["markdown"],
                     needle in bare["markdown"])
        check_in("overflow with a recorded approach: the Branch check line stays", f"Branch check: {CHECKOUT}", over["markdown"])
        check_eq("... the decisions side file holds the words", over["sides"]["decisions"], True)
        check_in("... whole", "Keep every UI case in scope. " * 400,
                 (task / "work/briefs/S5-qa-automator-1-decisions.md").read_text(encoding="utf-8"))
    finally:
        config.write_bytes(original)
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)


def not_established_label() -> None:
    """OH1-11 (F-3 R-b): a `vcs_api` / `host_hooks` / `base_slice` warning whose status is `unknown` reaches the role labelled
    `not established:` (the scribe names it in the report); any other warning stays `standing:`."""
    unknown = "host_hooks: unknown (live guard evidence incomplete; role-context delivery not yet verified)"
    base_slice = "base_slice: unknown x3 (docs/superpowers/a.md): repo unresolved"
    ordinary = "tracker_write: no"
    missing = "vcs_api: missing - unknown token"
    shown, minimal, full = brief_pack.decisions({"warnings": [unknown, base_slice, ordinary, missing]}, "S5", "qa-automator", "QA-9", None)
    check_eq("an unknown probe line is labelled `not established:`, every other warning `standing:` (shown)",
             [l for l in shown if "established" in l or "standing" in l],
             [f"- not established: {unknown}", f"- not established: {base_slice}", f"- standing: {ordinary}", f"- standing: {missing}"])
    check_eq("...and the whole record carries the same labels", [l for l in full if l.startswith("- not established") or l.startswith("- standing")],
             [f"- not established: {unknown}", f"- not established: {base_slice}", f"- standing: {ordinary}", f"- standing: {missing}"])
    check_in("...the minimal form too", f"- not established: {unknown}"[:40], " ".join(minimal))


# t-747 (item 4): the margins of the S5 fixture's two ceiling pins, rebuilt to the baseline of the 0.10.9 batch tree.
# Measured on this fixture (the smallest BRIEF_MAX_BYTES at which each holds; a bisection of `brief_pack.build`):
#   - digests stay inline (no side file), approach block already dropped by the ladder: 6367 B, i.e. 223 B over the 6144 B ceiling;
#   - the gate A line is still shortened rather than pointer-only, overflow words: 6269 B, i.e. 125 B over the ceiling.
# Growth since the pins were written, per node: RH2-9 the ahead card (+~190 B, t-735 handoff); OH1-11's brief label and the rest
# of the overshoot are not split per node (no per-node measurement was taken). The fixture has no filler to shrink that absorbs it
# (the overflow brief has its digests in the side file already; its remaining lines are the card and the head, product text), so
# the scenario sits AT its own measured ceiling: one byte short of it the same pin must fail (the BEYOND control).
# t-755 item 3: re-measured on the merged tree the same way: 6168 B / 6070 B. The brief now carries TQ1-27's `Plan case budget:` line (growth), and t-755 item 1 cut the automator card by 199 B (shrink); the net is the fall from 6367 / 6269 (the gate pin is measured at its later point in the test, where the decisions side file exists).
# The real 6 KB checks stay as they were; the product code and the card/label texts are not touched.
# t-777 (CI red round 5, finding PC2-1): the ceilings are NOT pinned. The brief prints the task root, so its size depends on the
# length of the path the test runs under (a long Windows temp path vs CI's short /builds/... root), and a byte constant measured
# on one machine does not tip the BEYOND control on another. Each scenario finds its ceiling AT RUNTIME by bisecting
# `brief_pack.build` in its own state (`s5_ceiling`), then asserts AT it and one byte BEYOND (short of) it.


def s5_build_at(ceiling: int) -> dict:
    real = brief_pack.BRIEF_MAX_BYTES
    brief_pack.BRIEF_MAX_BYTES = ceiling
    try:
        return brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1", write=False)
    finally:
        brief_pack.BRIEF_MAX_BYTES = real


def s5_ceiling(holds) -> int:
    """The smallest BRIEF_MAX_BYTES at which `holds(build_result)` is true; `holds` must be monotone in the ceiling."""
    lo, hi = 512, 65536
    assert holds(s5_build_at(hi)) and not holds(s5_build_at(lo)), "the scenario does not tip inside 512..65536 bytes"
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if holds(s5_build_at(mid)):
            hi = mid
        else:
            lo = mid
    return hi


def n4_scenario(task: Path, root: Path) -> None:
    """RC1-14 N4 (t-1757, W1-W9; t-1755 B2): the person's words first and never pushed out, the digest template last and outside
    the budget, every trim said in `## Not in the brief`. All on the real `build` of the S5 automator fixture at the REAL ceiling
    (a re-pin of BRIEF_MAX_BYTES is only the AT / one-byte-beyond bisect, on `budget_bytes`)."""
    pipeline_path, config = task / "pipeline.json", root / "qa-factory/config.json"
    state_before, config_before = pipeline_path.read_bytes(), config.read_bytes()
    original = b""      # the pipeline this scenario seeds (below); `state_before` is put back at the end
    real = brief_pack.BRIEF_MAX_BYTES

    def build(ceiling=None, write=False, output=None):
        brief_pack.BRIEF_MAX_BYTES = ceiling or real
        try:
            return brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1", write=write, output=output)
        finally:
            brief_pack.BRIEF_MAX_BYTES = real

    def words(count: int) -> None:
        doc = json.loads(original.decode("utf-8"))
        doc["warnings"] = [f"standing {i}: " + "w" * 380 for i in range(count)] + list(doc.get("warnings") or [])
        pipeline_path.write_text(json.dumps(doc), encoding="utf-8")

    try:
        seed_story_for_s5(task, root, "Gate A: approved. Proceed to S5 as it stands; no split.")
        seed_branch(task)
        original = pipeline_path.read_bytes()
        cfg = json.loads(config_before.decode("utf-8"))
        cfg["test_data"] = {"accounts_by_role": "created per test through the admin API", "seeds": "factories in tests/factories.py",
                            "generators": "unknown", "pii_and_masking": ["x"], "cleanup_owner": "the suite", "shared_records": []}
        config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        roomy = build(ceiling=64 * 1024)
        text = roomy["markdown"]
        # W3: the words are the first `## ` section after the head
        check_eq("N4 W3: the words heading is the first `## ` after the head",
                 [ln for ln in text.splitlines() if ln.startswith("## ")][0], "## The person's words that concern you")
        check_eq("N4 W3: ... the rule is the one before the last, the template is last",
                 [ln for ln in text.splitlines() if ln.startswith("## ")][-2:], ["## Rule", "## Your final message"])
        check("N4 W3: ... and the repository map sits after the card and right before the rule",
              text.index("## Commands") < text.index("## Repository map of the window") < text.index("## Rule"))
        check_eq("N4: a roomy brief trims nothing and carries no `Not in the brief` section", (roomy["omitted"], "## Not in the brief" in text), ([], False))
        # W4: AT the budget nothing is trimmed; ONE byte beyond exactly one rung is taken and its line is there
        size = roomy["budget_bytes"]
        at = build(ceiling=size)
        check_eq("N4 W4 AT the ceiling: the brief is the roomy one, nothing omitted", (at["markdown"], at["omitted"]), (text, []))
        one = build(ceiling=size - 1)
        check_eq("N4 W4 ONE byte beyond: exactly one line is omitted, the approach block (the first to give)",
                 [o.split(" - read ")[0] for o in one["omitted"]], ["- the project approach in full"])
        check("N4 W4 ... the section names it and the brief fits", "## Not in the brief" in one["markdown"]
              and one["budget_bytes"] <= size - 1, str(one["budget_bytes"]))
        check_eq("N4 W4 ... and the words are exactly where they were (whole, inline)",
                 [ln for ln in one["markdown"].splitlines() if ln.startswith("- gate A")],
                 [ln for ln in text.splitlines() if ln.startswith("- gate A")])
        # W9: the digests moved - the heading stays, never empty, and the line points at `Not in the brief`
        moved = build(ceiling=real)
        after = moved["markdown"].split("## What earlier roles produced\n\n", 1)[1].splitlines()[0]
        check_eq("N4 W9 the digests heading is never empty: it carries the side-file line", after, "- in the side file, see Not in the brief")
        check("N4 W9 ... and `Not in the brief` names the digests side file",
              any(o.startswith("- the digests of earlier roles - read ") and o.endswith("S5-qa-automator-1-digests.md") for o in moved["omitted"]),
              str(moved["omitted"]))
        # W2 / E17: no template (patched to []) -> the templated brief minus the section, plus the R5 line
        real_form = brief_pack.digest_template_lines
        brief_pack.digest_template_lines = lambda *a, **k: []
        try:
            bare = build(ceiling=64 * 1024)
        finally:
            brief_pack.digest_template_lines = real_form
        stem = text.split("\n\n## Your final message")[0]
        check_eq("N4 W2: with no template the brief is the templated one minus the section plus the R5 line",
                 bare["markdown"], stem + "\n\n" + brief_pack.NO_FORM_LINE + "\n")
        check_in("N4 W2: ... the R5 line points at the digest shape of the rules", "`## Your handover`", bare["markdown"])
        check_eq("N4 W2: ... and the budget is the whole text (no form to leave out) minus the SD head, which is form too (X7-1)",
                 brief_pack.measured_bytes(bare["markdown"]) - bare["budget_bytes"], brief_pack.head_bytes(bare["markdown"].split("\n")[2:10]))  # GM3: the budget counts the plugin root as a token
        # W5: the trimmed files are in `<ID>-files.md`, one `Not in the brief` line names it; --output writes no side file
        tight = build(ceiling=1, write=True)
        side_files = task / "work/briefs/S5-qa-automator-1-files.md"
        gone = [ln for ln in roomy["files"] if ln not in tight["files"]]
        body = side_files.read_text(encoding="utf-8") if side_files.is_file() else ""
        check("N4 W5: the side file holds EVERY trimmed line", bool(gone) and all(ln in body for ln in gone), f"{len(gone)} trimmed")
        check_eq("N4 W5: ... and ONE line of `Not in the brief` names it",
                 len([o for o in tight["omitted"] if o.endswith("S5-qa-automator-1-files.md")]), 1)
        side_files.unlink()
        build(ceiling=1, write=True, output=task / "work/out-brief.md")
        check("N4 W5: `--output` writes no side file", not side_files.exists())
        # W7: no level-0 line (a pointer instead of the words) in any brief this scenario builds
        for label, got in (("roomy", roomy), ("one byte beyond", one), ("real ceiling", moved), ("squeezed to 1 byte", tight)):
            check_not_in(f"N4 W7 {label}: no pointer-only words line (level 0 is gone)", "recorded decision(s):", got["markdown"])
        # the empty repository map: nothing to omit, so no line says it was omitted
        real_map = brief_pack.repo_map_for
        brief_pack.repo_map_for = lambda *a, **k: {"path": "qa-factory/x-map.md", "written": False, "doc": {"empty": True}, "markdown": "# map\n\n"}
        try:
            empty_map = build(ceiling=1)
        finally:
            brief_pack.repo_map_for = real_map
        check_not_in("N4 an empty repository map: no `the repository map head` line", "the repository map head", "\n".join(empty_map["omitted"]))
        # W6: 24 KB of the person's words: level 1 (a line each, no pointer-only line), the brief goes over and SAYS it
        words(60)
        battery = build(write=True)
        lines = battery["markdown"].splitlines()
        check_eq("N4 W6: the brief is over its ceiling and `over_ceiling` names the words", "words at level 1" in battery["over_ceiling"], True)
        kept = [ln for ln in lines if ln.startswith("- standing: standing ")]
        check_eq("N4 W6: ... all 60 warnings keep their line", len(kept), 60)
        check("N4 W6: ... each words text cut at the level-1 limit (DECISION_CHARS_MIN)",
              all(len(ln) <= len("- standing: ") + brief_pack.DECISION_CHARS_MIN for ln in kept), str(max(len(ln) for ln in kept)))
        check_in("N4 W6: ... the S5 waiver keeps its own line (PC2-6 K1: the person's waiver is not traded for a count line)",
                 'S5 block "vcs-1: uncommitted changes" -> go on', battery["markdown"])
        check_in("N4 W6: ... the over line is the first line of `Not in the brief` and names the words (PC2-6)",
                 f"- the brief stays over its {brief_pack.BRIEF_MAX_BYTES} B budget after every cut (words at level 1",
                 battery["markdown"].split("## Not in the brief\n\n", 1)[1].splitlines()[0])
        check_not_in("N4 W6: ... and no pointer-only line", "recorded decision(s):", battery["markdown"])
        check_in("N4 W6: `Not in the brief` names the decisions side file", "- every decision in full - read qa-factory/artifacts/QA-9/work/briefs/S5-qa-automator-1-decisions.md",
                 battery["markdown"])
        check_in("N4 W6: ... and that file carries the last warning whole", "standing 59: " + "w" * 380,
                 (task / "work/briefs/S5-qa-automator-1-decisions.md").read_text(encoding="utf-8"))
        check("N4 W6: the words come BEFORE the template and the template is still last",
              battery["markdown"].index("## The person's words") < battery["markdown"].index("## Your final message")
              and battery["markdown"].rstrip().endswith("```"))
        # W8: over the guard's whole-read limit the FIRST line after the title says to read by range
        words(150)
        huge = build()
        top = huge["markdown"].splitlines()
        check("N4 W8: the brief passes 30 000 B", huge["bytes"] > brief_pack.SLICE_BYTES, str(huge["bytes"]))
        check_eq("N4 W8: the line after the title is the by-range note, with the brief's own size",
                 top[2], f"This brief is {huge['bytes']} B, over the 30 KB whole-read limit: read it by range (offset/limit), the person's words first")
        check_eq("N4 W8: ... `over_ceiling` names both reasons", huge["over_ceiling"], ["words at level 1", "over SLICE_BYTES"])
        check_not_in("N4 W8 (control): a brief under the limit has no such line", "whole-read limit", battery["markdown"])
        # the real-ceiling proof of AR-24: the gate A word is in the brief in every build above
        for label, got in (("battery", battery), ("huge", huge), ("squeezed", tight)):
            check_in(f"N4 {label}: the gate A word is whole in the brief", "gate A (approved): Gate A: approved. Proceed to S5 as it stands; no split.", got["markdown"])
    finally:
        pipeline_path.write_bytes(state_before)
        config.write_bytes(config_before)
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        brief_pack.BRIEF_MAX_BYTES = real


# --- t-2181 PC-8: the sides of the story and the assumptions in the S5 briefs --------------------------------------------

PC8_AUTHOR = "S5-qa-automator-1"
PC8_BIND = "S5-qa-automator-2"
PC8_CRITIC = "S5-qa-code-critic-1"
PC8_SIDES = {"backend": {"reality": "absent", "deliverable": True, "settles_by": "", "source": "registry"},
             "ui": {"reality": "real", "deliverable": True, "settles_by": "", "source": "launch"}}
PC8_FIELDS = ("tests[].sides", "then_bindings[].about", "provisional[]", "tests[].provisional")


def pc8_story(root: Path, sides=None, provisional=None, pending=None, tests=None, pipeline_extra=None) -> Path:
    """A story before S5 with a `bind` automator dispatch beside the ordinary one and a bind critic dispatch (the critic still gets no
    bind list); `sides` is the `pipeline.sides` record (None: no record), `provisional` the manifest's rows, `pending` the
    `pending_implementation` rows, `tests` more `tests[]` rows, `pipeline_extra` more pipeline keys."""
    task = seed(root, "QA-9")
    seed_story_for_s5(task, root, "Gate A: approved.")
    seed_branch(task)
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    if sides is not None:
        pipeline["sides"] = sides
    pipeline.update(pipeline_extra or {})
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    state_path = task / "state/controller.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["dispatches"][PC8_BIND] = {"id": PC8_BIND, "stage": "S5", "role": "qa-automator", "status": "running",
                                     "scope": ["TC-001", "TC-002"], "request_binding": {"purpose": "bind"}}
    state["dispatches"][PC8_CRITIC] = {"id": PC8_CRITIC, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                       "scope": ["TC-001", "TC-002"], "request_binding": {"purpose": "bind"}}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    manifest_path = task / "work/automation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tests"] = list(manifest.get("tests") or []) + list(tests or [])
    if provisional is not None:
        manifest["provisional"] = provisional
    if pending is not None:
        manifest["unresolved"] = pending
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return task


def pc8_head(text: str) -> str:
    return text.split("\n## ")[0]


def s5_brief_names_side_fields_only_for_non_real_side() -> None:
    root = harness.temp_project("qa-brief-pc8a-")
    try:
        harness.use_project(root)
        pc8_story(root)
        # all-real, no record, no rows: the brief is byte-identical to what it was (the helpers are the only addition)
        text = brief_of(dispatch=PC8_AUTHOR)
        for field in PC8_FIELDS:
            check_not_in(f"(PC-8) an all-real story's S5 brief does not name {field}", field, text)
        check_not_in("(PC-8) ... nor the side lines", "Sides of this story", text)
        real_side, real_prov = brief_pack.side_lines, brief_pack.provisional_lines
        brief_pack.side_lines, brief_pack.provisional_lines = (lambda *a, **k: []), (lambda *a, **k: [])
        try:
            without = brief_of(dispatch=PC8_AUTHOR)
        finally:
            brief_pack.side_lines, brief_pack.provisional_lines = real_side, real_prov
        check_eq("(PC-8) the all-real brief is byte-identical to the brief built without the PC-8 block", text, without)
        check_eq("(PC-8) side_lines of a pipeline with no record is []", brief_pack.side_lines({"id": "QA-9"}), [])
        check_eq("(PC-8) ... and of a pipeline that could not be read", brief_pack.side_lines({}), [])
        # F5: an unreadable or unknown record is ONE line, never the reader's all-real default, never silence
        unknown = {"sides_unknown": {"why": "the registry is down"}}
        for label, pipe in (("a sides record that is a list", {"sides": ["backend"]}), ("sides: null", {"sides": None}),
                            ("sides_unknown with no record", unknown)):
            got = brief_pack.side_lines(pipe)
            check_eq(f"(PC-8 F5) {label}: exactly one line", len(got), 1)
            check_in(f"(PC-8 F5) {label}: it says no side counts as real", "no side counts as real", got[0])
        check_in("(PC-8 F5) the why of the unknown is carried", "the registry is down", brief_pack.side_lines(unknown)[0])
        both = brief_pack.side_lines({"sides": {"backend": {"reality": "real", "source": "launch"}}, "sides_unknown": "late word"})
        check_eq("(PC-8 F5) a readable record beside an unknown: the unknown line, then the header and the side",
                 [both[0][:23], len(both)], ["The project's record of", 3])
        probes = ({"sides": []}, {"id": "x"}, {"sides": {"a": {"reality": "real"}}}, {"sides": {"a": {"reality": "absent"}}}, unknown)
        check_eq("(PC-8 F5) one rule with the proof stamp: the brief has lines exactly when the stamp is not empty",
                 [bool(brief_pack.side_lines(p)) for p in probes], [bool(__import__("run_suite").proof_stamp(p)) for p in probes])
        # F8: the header is true for a substituted side
        sub = "\n".join(brief_pack.side_lines({"sides": {"backend": {"reality": "substituted", "source": "launch"}}}))
        check_in("(PC-8 F8) a substituted side is said to run against its substitute", "a substituted side runs only against its substitute", sub)
        check_not_in("(PC-8 F8) the old header that said no non-real side can run", "a side that is not real cannot be run against", sub)
    finally:
        harness.cleanup(root)

    # F5 through the brief: an unknown record names the fields to fill and the one line, in both roles' heads
    root = harness.temp_project("qa-brief-pc8u-")
    try:
        harness.use_project(root)
        pc8_story(root, pipeline_extra={"sides_unknown": {"why": "no record was kept"}})
        for role, did in (("qa-automator", PC8_AUTHOR), ("qa-code-critic", PC8_CRITIC)):
            head = pc8_head(brief_of(role=role, dispatch=did))
            check_in(f"(PC-8 F5) the {role} brief says the record could not be read", "no side counts as real", head)
        check_in("(PC-8 F5) the automator is told the fields too", "tests[].sides", pc8_head(brief_of(dispatch=PC8_AUTHOR)))
    finally:
        harness.cleanup(root)

    root = harness.temp_project("qa-brief-pc8b-")
    try:
        harness.use_project(root)
        pc8_story(root, sides=PC8_SIDES)
        text = brief_of(dispatch=PC8_AUTHOR)
        head = pc8_head(text)
        for field in PC8_FIELDS:
            check_in(f"(PC-8) a story with a non-real side names {field} in the head", field, head)
        check_in("(PC-8) the kinds come from the data file", "placeholder_locator", head)
        check_in("(PC-8) the reality words come from the data file", "real | absent | substituted", head)
        check_in("(PC-8) the marker the project's home carries is named", "qa-provisional: P-n", head)
        check_in("(PC-8) a placeholder is never an expected value", "never a Then's expected value", head)
        check_not_in("(PC-8) an ordinary window lists no bind round", "Bind round", text)
        # F6: the kinds come through the ONE reader, and an unreadable file is said
        import contract
        real_kinds = contract.provisional_kinds
        try:
            contract.provisional_kinds = lambda: ["only_kind"]
            via_reader = pc8_head(brief_of(dispatch=PC8_AUTHOR))
            contract.provisional_kinds = lambda: None
            unread = pc8_head(brief_of(dispatch=PC8_AUTHOR))
        finally:
            contract.provisional_kinds = real_kinds
        check_in("(PC-8 F6) the brief names the kinds the reader returns", "kind: only_kind)", via_reader)
        check_in("(PC-8 F6) an unreadable kinds file is said, not read as no kinds", "the kinds file could not be read", unread)
        check("(PC-8 F6) the reader returns the file's kinds", "placeholder_locator" in (real_kinds() or []), str(real_kinds()))
    finally:
        harness.cleanup(root)

    # a story whose sides are all real again but whose manifest already holds a provisional row still names the fields
    pc8_story_rows = [{"id": "P-1", "kind": "placeholder_locator", "status": "settled_matched", "settles_on": "backend"}]
    root = harness.temp_project("qa-brief-pc8c-")
    try:
        harness.use_project(root)
        pc8_story(root, sides={"product": {"reality": "real", "deliverable": True, "settles_by": "", "source": "arrival"}},
                  provisional=pc8_story_rows)
        text = brief_of(dispatch=PC8_AUTHOR)
        for field in PC8_FIELDS:
            check_in(f"(PC-8) provisional rows on an all-real record still name {field}", field, pc8_head(text))
        check_in("(PC-8) a record that exists is listed even when every side is real again", "- product: real", text)
        check_not_in("(PC-8) a launch- or arrival-sourced side carries no knowledge marker", "[knowledge:", text)
        # the helper at its bound: more sides than it shows
        many = {f"s{i}": {"reality": "absent", "source": "launch"} for i in range(brief_pack.SIDES_SHOWN + 2)}
        got = brief_pack.side_lines({"sides": many})
        check_eq("(PC-8) AT the bound: header + SIDES_SHOWN sides + one `+N more` line", len(got), brief_pack.SIDES_SHOWN + 2)
        check_in("(PC-8) BEYOND the bound the rest is counted, not cut in silence", "+2 more sides", got[-1])
        at = brief_pack.side_lines({"sides": dict(list(many.items())[:brief_pack.SIDES_SHOWN])})
        check_eq("(PC-8) exactly SIDES_SHOWN sides: no `+N more` line", len(at), brief_pack.SIDES_SHOWN + 1)
        check_in("(PC-8) a side of unknown reality reads as not real", "unknown (not read as real)",
                 "\n".join(brief_pack.side_lines({"sides": {"x": {"source": "launch"}}})))
        check_in("(PC-8) bind is a word of the controller's own closed set", brief_pack.BIND_PURPOSE,
                 __import__("controller").PURPOSES)
    finally:
        harness.cleanup(root)


def bind_brief_lists_only_open_rows_and_pending_instances() -> None:
    rows = [{"id": "P-1", "kind": "placeholder_locator", "status": "open", "what": "the basket button selector", "settles_on": "backend",
             "home": {"file": "tests/pages/basket.py", "line_hint": 3}},
            {"id": "P-2", "kind": "assumed_contract", "status": "settled_matched", "what": "SETTLED-WORDS", "settles_on": "backend"},
            {"id": "P-3", "kind": "side_substitute", "status": "retracted", "what": "RETRACTED-WORDS", "settles_on": "backend"},
            # F2 (a) as changed by the owner's word W3 (11.11.2026): kept by decision stays kept, also on a side that is real now (F8)
            {"id": "P-4", "kind": "side_substitute", "status": "kept_by_decision", "what": "KEPT-WORDS", "settles_on": "backend"},
            # F2 (b): open, but its side is still absent: it waits, it is counted, it is not listed
            {"id": "P-5", "kind": "assumed_contract", "status": "open", "what": "WAIT-WORDS", "settles_on": "payments"},
            # F3 (a): a row whose only dependent is a case of another window is not this dispatch's
            {"id": "P-6", "kind": "placeholder_locator", "status": "open", "what": "OTHER-WINDOW-WORDS", "settles_on": "backend",
             "dependents": [{"case": "TC-009"}]},
            {"id": "P-7", "kind": "placeholder_locator", "status": "open", "what": "IN-WINDOW-WORDS", "settles_on": "backend",
             "dependents": [{"case": "TC-002"}]}]
    pending = [{"case": "TC-001", "reason": "pending_implementation", "instance_ids": ["test_limit", "test_wait"], "question": "Q-1"},
               {"case": "TC-002", "area": "cart", "reason": "pending_implementation", "instance_ids": ["test_cart_run"], "question": "Q-2"},
               {"case": "TC-002", "area": "pay", "reason": "pending_implementation", "instance_ids": ["test_only_wait"], "question": "Q-4"},
               {"case": "TC-009", "reason": "pending_implementation", "instance_ids": ["test_other"], "question": "Q-3"}]
    tests = [{"case": "TC-001", "instance_id": "test_limit", "file": "t.py", "sides": {"backend": "absent"}},
             {"case": "TC-001", "instance_id": "test_wait", "file": "t.py", "sides": {"payments": "absent"}},
             {"case": "TC-002", "area": "cart", "instance_id": "test_cart_run", "file": "t.py", "sides": {"backend": "absent"}},
             {"case": "TC-002", "area": "pay", "instance_id": "test_only_wait", "file": "t.py", "sides": {"payments": "absent"}},
             {"case": "TC-009", "instance_id": "test_other", "file": "t.py", "sides": {"backend": "absent"}}]
    record = {"backend": {"reality": "real", "deliverable": True, "settles_by": "", "source": "arrival"},
              "payments": {"reality": "absent", "deliverable": True, "settles_by": "", "source": "launch"}}
    root = harness.temp_project("qa-brief-pc8d-")
    try:
        harness.use_project(root)
        pc8_story(root, sides=record, provisional=rows, pending=pending, tests=tests)
        text = brief_of(dispatch=PC8_BIND)
        head = pc8_head(text)
        check_in("(PC-8) the bind brief says what the round is", "Bind round - the code arrived", head)
        check_in("(PC-8 F7) the bind procedure is in the brief, not the charter", "`settled_matched`, edited `settled_edited`", head)
        check_in("(PC-8) the open row is listed with its kind, side, words and home",
                 "- open P-1 (placeholder_locator) on backend: the basket button selector - home tests/pages/basket.py", head)
        for gone in ("P-2", "P-3", "SETTLED-WORDS", "RETRACTED-WORDS"):
            check_not_in(f"(PC-8) the bind brief lists no settled or retracted row ({gone})", gone, text)
        check_not_in("(PC-8 F2, F8: owner word W3 11.11.2026) a kept row whose side is real now STAYS kept - the bind brief does not tell the role to reopen it",
                     "KEPT-WORDS", text)
        check_not_in("(F8) ... and says no `back to open`", "back to open", head)
        check_not_in("(PC-8 F2) an open row on a side still absent is not listed as yours", "WAIT-WORDS", text)
        check_in("(PC-8 F2) ... it is counted as waiting", "- 1 open row(s) still waiting for payments (not real yet): leave them", head)
        check_not_in("(PC-8 F3) a row of another window's case is not listed", "OTHER-WINDOW-WORDS", text)
        check_in("(PC-8 F3) a row whose dependent is in the window is", "IN-WINDOW-WORDS", head)
        check_in("(PC-8 F2) an instance whose side is real now is told to run", "- pending row TC-001: run test_limit;", head)
        check_in("(PC-8 F2) ... and the one an absent side still excuses waits", "still waiting for an absent side: test_wait", head)
        check_not_in("(PC-8 F2) ... never under run", "run test_limit, test_wait", head)
        check_in("(PC-8 F3) the retract key of a row is its case key, with the area", 'retracted_unresolved: ["cart/TC-002"]', head)
        check_in("(PC-8 F3) ... and a row with no area keeps the bare id", 'retracted_unresolved: ["TC-001"]', head)
        check_in("(PC-8 F2) a row whose instances all wait is left alone", "- pending row pay/TC-002: leave it; still waiting for an absent side: test_only_wait", head)
        check_not_in("(PC-8 F3) a pending row of another window's case is not listed", "test_other", text)
        # a dispatch with no readable scope reads the whole story (the exit check's rule): the other window's row is listed again
        state_path = root / "qa-factory/artifacts/QA-9/state/controller.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["dispatches"][PC8_BIND]["scope"] = []
        state_path.write_text(json.dumps(state), encoding="utf-8")
        whole = pc8_head(brief_of(dispatch=PC8_BIND))
        check_in("(PC-8 F3) no scope: the whole story's rows", "OTHER-WINDOW-WORDS", whole)
        check_in("(PC-8 F3) ... and its pending rows", "test_other", whole)
        state["dispatches"][PC8_BIND]["scope"] = ["TC-001", "TC-002"]
        state_path.write_text(json.dumps(state), encoding="utf-8")
        ordinary = brief_of(dispatch=PC8_AUTHOR)
        check_not_in("(PC-8) an ordinary window does not list the open row", "P-1", ordinary)
        check_not_in("(PC-8) ... nor the pending row", "pending row", ordinary)
        critic = brief_of(role="qa-code-critic", dispatch=PC8_CRITIC)
        check_not_in("(PC-8) the code critic's brief carries no bind list, even on a bind dispatch", "Bind round", critic)
        # F9: a bind round that fails to list says so; an ordinary window that fails loses only the reminder
        real_bind, real_assume = brief_pack._bind_lines, brief_pack._assumption_lines
        try:
            def boom(*a, **k):
                raise TypeError("probe")
            brief_pack._bind_lines = boom
            failed = pc8_head(brief_of(dispatch=PC8_BIND))
            brief_pack._assumption_lines = boom
            ordinary_failed = brief_of(dispatch=PC8_AUTHOR)
        finally:
            brief_pack._bind_lines, brief_pack._assumption_lines = real_bind, real_assume
        check_in("(PC-8 F9) a failed bind listing is said, with the exception type", "The rows could not be listed (TypeError)", failed)
        check_in("(PC-8 F9) ... under the bind head", "Bind round - the code arrived", failed)
        check_not_in("(PC-8 F9) an ordinary window that fails is silent about it", "could not be listed", ordinary_failed)
        # AT the bound and BEYOND it
        many = [dict(rows[0], id=f"P-{i}") for i in range(1, brief_pack.PROVISIONAL_SHOWN + 3)]
        pc8_story_path = root / "qa-factory/artifacts/QA-9/work/automation-manifest.json"
        manifest = json.loads(pc8_story_path.read_text(encoding="utf-8"))
        manifest["provisional"] = many[:brief_pack.PROVISIONAL_SHOWN]
        pc8_story_path.write_text(json.dumps(manifest), encoding="utf-8")
        at = pc8_head(brief_of(dispatch=PC8_BIND))
        check_eq("(PC-8) AT the bound every open row is listed", at.count("- open P-"), brief_pack.PROVISIONAL_SHOWN)
        check_not_in("(PC-8) AT the bound there is no `+N more`", "more rows to settle", at)
        manifest["provisional"] = many
        pc8_story_path.write_text(json.dumps(manifest), encoding="utf-8")
        beyond = pc8_head(brief_of(dispatch=PC8_BIND))
        check_eq("(PC-8) BEYOND the bound only SHOWN rows are listed", beyond.count("- open P-"), brief_pack.PROVISIONAL_SHOWN)
        check_in("(PC-8) ... and the rest is counted", "+2 more rows to settle", beyond)
        # empty outcomes are said
        manifest["provisional"] = []
        manifest["unresolved"] = []
        pc8_story_path.write_text(json.dumps(manifest), encoding="utf-8")
        empty = pc8_head(brief_of(dispatch=PC8_BIND))
        check_in("(PC-8) no open row is a declared outcome", "- no open provisional row", empty)
        check_in("(PC-8) no pending instance is a declared outcome", "- no pending instance", empty)
        pc8_story_path.write_text("{not json", encoding="utf-8")
        broken = pc8_head(brief_of(dispatch=PC8_BIND))
        check_in("(PC-8) an unreadable manifest is named, not read as empty", "could not be listed: work/automation-manifest.json cannot be read", broken)
        pc8_story_path.unlink()
        gone_manifest = pc8_head(brief_of(dispatch=PC8_BIND))
        check_in("(PC-8) an absent manifest is named", "work/automation-manifest.json is not there", gone_manifest)
    finally:
        harness.cleanup(root)


def sides_lines_marked_and_given_to_code_critic() -> None:
    root = harness.temp_project("qa-brief-pc8e-")
    try:
        harness.use_project(root)
        pc8_story(root, sides=PC8_SIDES)
        author = brief_of(dispatch=PC8_AUTHOR)
        critic = brief_of(role="qa-code-critic", dispatch=PC8_CRITIC)
        lines = brief_pack.side_lines(json.loads((root / "qa-factory/artifacts/QA-9/pipeline.json").read_text(encoding="utf-8")))
        check("(PC-8) the helper returned the header and both sides", len(lines) == 3, str(lines))
        for who, text in (("automator", author), ("code critic", critic)):
            head = pc8_head(text)
            check("(PC-8) the " + who + "'s head holds the helper's lines whole, in order, together",
                  "\n".join(lines) in head, "\n".join(lines))
        check_eq("(PC-8 F1) a registry side whose row has no registry_key gets no marker (no key is invented)",
                 [ln for ln in lines if "[knowledge:" in ln], [])
        check_not_in("(PC-8) a launch-sourced side carries none", "- ui: real [", "\n".join(lines))
        check_not_in("(PC-8) the critic is handed no fields to fill", "tests[].provisional", pc8_head(critic))
        # F1: the marker carries the registry key the sides reader returns (PC-1b adds the field to `story_sides`; a synthetic row stands in)
        import contract
        real_reader = contract.story_sides
        rows = {"backend": {"reality": "absent", "deliverable": True, "settles_by": "", "reference": None, "source": "registry",
                            "registry_key": "product.sides"},
                "ui": {"reality": "real", "deliverable": True, "settles_by": "", "reference": None, "source": "launch",
                       "registry_key": "product.ui"},
                "cart": {"reality": "absent", "deliverable": True, "settles_by": "", "reference": None, "source": "person",
                         "registry_key": "product.cart"}}
        try:
            contract.story_sides = lambda *a, **k: rows
            keyed = brief_pack.side_lines({"sides": PC8_SIDES})
        finally:
            contract.story_sides = real_reader
        check_eq("(PC-8 F1) only the registry-sourced side carries the marker, with its registry key",
                 [ln for ln in keyed if "[knowledge:" in ln], ["- backend: absent [knowledge:product.sides]"])
        # no mark without a registry source, whatever the other attributes
        plain = brief_pack.side_lines({"sides": {"backend": {"reality": "absent", "source": "person"}}})
        check_not_in("(PC-8) a person-sourced side carries no marker", "[knowledge:", "\n".join(plain))
        # an all-real story's critic brief is as it was
        brief_pack_lines = brief_pack.side_lines({"id": "QA-9"})
        check_eq("(PC-8) no record and all real: the critic gets no side line", brief_pack_lines, [])
    finally:
        harness.cleanup(root)


def pc8_scenarios() -> None:
    s5_brief_names_side_fields_only_for_non_real_side()
    bind_brief_lists_only_open_rows_and_pending_instances()
    sides_lines_marked_and_given_to_code_critic()


def main() -> None:
    not_established_label()
    root = harness.temp_project("qa-brief-pack-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")

        # --- story_step start writes the brief and names it -------------------------------
        from controller import Controller
        harness.run_script("stage_done.py", "--task", "QA-9", "--stage", "S0", "--status", "done",
                           "--digest", "preflight green", cwd=root, env=env)
        Controller(task).apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                              "known_paths": {"root": str(task), "project_root": str(root)},
                                              "idempotency_key": "init"})
        started = harness.run_script("story_step.py", "start", "--task", "QA-9", "--stage", "S1",
                                     "--role", "qa-scout", cwd=root, env=env)
        check_in("start still dispatches", "dispatched S1-qa-scout-1", started.stdout)
        brief_path = task / "work/briefs/S1-qa-scout-1.md"
        check("and the brief exists", brief_path.is_file())
        check_in("the prompt names it in one line",
                 "Read qa-factory/artifacts/QA-9/work/briefs/S1-qa-scout-1.md first; it names the files and the commands.",
                 started.stdout)
        check_in("and the note says how big it is", "brief: qa-factory/artifacts/QA-9/work/briefs/S1-qa-scout-1.md",
                 started.stdout)
        scout = brief_path.read_text(encoding="utf-8")
        # t-1765 X1 fix-3: the SD head (7 lines + blank after the title) is form, outside the body budget; the pin is on the body.
        sd_lines = scout.split("\n")[2:9] + [""]
        check("the S1 brief body is under 6 KB", len(scout.encode("utf-8")) - brief_pack.head_bytes(sd_lines) <= 6 * 1024)
        check("the S1 SD head is within its own cap", brief_pack.head_bytes(sd_lines[:-1]) <= brief_pack.SD_HEAD_MAX_BYTES)
        check_in("the scout's card names the ticket adapter", "ticket_adapter.py get|children|diff", scout)
        check_in("and the diff pass instead of the diff", "diff_pass.py --diff", scout)
        check_in("the S1 brief lists the stage's input with its size", "qa-factory/artifacts/QA-9/pipeline.json (", scout)
        check_in("with no person's words yet, it says so", "none recorded", scout)
        # t-1687 N1-5: the S1 rule does not forbid the scout's own job (a search); only S1 changes
        check_in("and ends with the S1 rule: the repositories are the scout's to search",
                 "Read what is named above with `offset`/`limit`; the application and test repositories are yours to search, "
                 "as your procedure says; never the plugin - the card above is what it would tell you", scout)
        check_not_in("the S1 rule no longer bans the search", "Do not search:", scout)
        # N1-4 B-S1 card: both new tracker lines stand in the scout's card
        check_in("B-S1 card: the scout's card names `query`", "ticket_adapter.py query --path <API path with its query> --output ", scout)
        check_in("B-S1 card: ... and `record-source`", "ticket_adapter.py record-source --output ", scout)
        s2_brief = brief_pack.build("QA-9", "S2", "qa-requirements-tester", "S2-qa-requirements-tester-1", write=False)["markdown"]
        check_in("N1-5 pin: an S2 brief still ends with the old rule", "Do not search: read what is named above", s2_brief)
        check_not_in("N1-5 pin: ... and never with the S1 text", "are yours to search, as your procedure says", s2_brief)
        check_not_in("judge off: no judge command in the card", "judge_", scout)

        # B-008: the scout's brief lists the snapshot the way the driver now writes it. Before
        # the snapshot exists the path is named and said not to be written; after `get
        # --output` it is listed with its size. (The driver wrote `.md` for months while this
        # list asked for `.json`: the scout never got the file.)
        check_in("before the snapshot: the scout is told the exact path and that nothing wrote it",
                 "work/ticket-snapshot.json: not written yet", scout)
        ticket_md = harness.PLUGIN_ROOT / "evals" / "fixtures" / "tickets" / "QA-1.md"
        wrote = harness.run_script("ticket_adapter.py", "get", "QA-9", "--json", "--ticket-file", str(ticket_md),
                                   "--output", str(task / "work" / "ticket-snapshot.json"), cwd=root, env=env)
        check_eq("get --output writes the snapshot the brief lists", wrote.returncode, 0)
        with_snapshot = brief_pack.build("QA-9", "S1", "qa-scout", "S1-qa-scout-8")["markdown"]
        check_in("after the snapshot: the brief lists it with its size",
                 "qa-factory/artifacts/QA-9/work/ticket-snapshot.json (", with_snapshot)
        check_not_in("and no longer says it is not written", "ticket-snapshot.json: not written yet", with_snapshot)
        check_not_in("and the brief never names a Markdown snapshot", "ticket-snapshot.md", with_snapshot)
        (task / "work" / "ticket-snapshot.json").unlink(missing_ok=True)

        # a brief_pack failure is a note, never a refusal of the start
        real_run = story_step._run
        story_step._run = lambda script, *a: (1, "brief_pack: boom") if script == "brief_pack.py" else real_run(script, *a)
        try:
            rel, note = story_step._brief("QA-9", "S1", "qa-scout", "S1-qa-scout-9", task)
        finally:
            story_step._run = real_run
        check_eq("no brief path when brief_pack failed", rel, "")
        check_in("and the note names the failure", "brief_pack: no brief for S1-qa-scout-9 (brief_pack: boom)", note)
        prompt = story_step._prompt("QA-9", story_step._stages()["S1"], "qa-scout", "S1-qa-scout-9", [], "")
        check_not_in("the prompt then carries no brief line", "Read qa-factory/artifacts/QA-9/work/briefs", prompt)

        # --- the S5 automator brief ---------------------------------------------------------
        seed_story_for_s5(task, root, "Gate A: approved. Proceed to S5 as it stands; no split.")
        seed_branch(task)   # CX1-7 (k): the real run's record and manifest, so the 6 KB checks below carry the Branch check line
        # N4 (RC1-14, t-1755 B2): the F11 re-pin is gone. The section `## Your final message` is outside the budget (F-4), so this
        # fixture is built at the REAL ceiling and its `budget_bytes` is the number the 6 KB bound reads.
        real_ceiling = brief_pack.BRIEF_MAX_BYTES
        result = brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1")
        text = result["markdown"]
        check_in("F11: the S5 brief carries the digest template of its scope", "TC-002 · <state> ·", text)
        check_in("(k) the S5 brief carries the Branch check line", f"Branch check: {CHECKOUT}", text)
        check("(k) the S5 brief is under 6 KB (budget, the section outside it) WITH the Branch check line (the head is never shrunk)",
              result["budget_bytes"] <= 6 * 1024, str(result["budget_bytes"]))
        check("the S5 brief is under 6 KB (budget)", result["budget_bytes"] <= 6 * 1024)
        # X7-1: the automator is a charter, so its brief opens with the seven SD header lines: form outside the body budget too
        sd_head = brief_pack.head_bytes(text.split("\n")[2:10])
        check_eq("N4 W1: the section and the SD head are outside the budget: bytes - budget_bytes is exactly their size",
                 brief_pack.measured_bytes(text) - result["budget_bytes"], form_bytes() + sd_head)  # GM3: the budget counts the plugin root as a token
        check_in("it names the scope", "Scope: TC-001, TC-002", text)
        check_in("and the read_first pointer", "Read first, before anything else: work/s5-notes.md", text)
        # Source: finding 20261102 item 1 (PC2-1), "the 6144-byte brief boundary". The S5 pins below judge the LADDER at a ceiling they
        # set themselves (s5_build_at overwrites BRIEF_MAX_BYTES and restores it in its `finally`); this check pins the VALUE.
        check_eq("the brief ceiling is the 6144 B of the requirement", brief_pack.BRIEF_MAX_BYTES, 6144)
        digests_ceiling = s5_ceiling(lambda r: r["sides"]["digests"] is False)
        at_digests = s5_build_at(digests_ceiling)
        check_in("earlier digests are inline (AT their measured ceiling)", "- S4 done: qa-case-critic S4 QA-9", at_digests["markdown"])
        check_eq("the digests needed no side file (AT their measured ceiling)", at_digests["sides"]["digests"], False)
        short_by_one = s5_build_at(digests_ceiling - 1)       # BEYOND control: one byte short, the digests give way
        check_eq("BEYOND (control): one byte short, the digests moved to the side file", short_by_one["sides"]["digests"], True)
        check_not_in("BEYOND (control): and are not inline", "- S4 done: qa-case-critic S4 QA-9", short_by_one["markdown"])
        check_not_in("another stage's dispatch is not listed as this stage's", "S4-qa-case-critic-1", text)
        check_in("the case files are listed with sizes", "work/test-cases/coupon/TC-001.md (", text)
        check_in("a large input is sliced to the plan rows of the cases",
                 "test-plan.md (39.1 KB) - only the rows TS-1, TS-2", text)
        check_in("the bundle is named as a slice, not a file", "work/context-bundle.json: do not read whole", text)
        check_in("the P3 command has the exact shape",
                 "manifest_from_tests.py --task QA-9 --dispatch S5-qa-automator-1 --file <test file> [--file ...] [--dry-run] [--json]", text)
        check_in("with the marker it reads", '@pytest.mark.qa(case="<case id>", then=[1, 2], partition="tc003-zero-matches", obligations=["TS-3-O1"])', text)
        check_in("run_suite --mine is there", "run_suite.py --mine <case id>[,<case id>]", text)
        check_in("with its answer shape", "{exit_code, execution_status, totals{passed,failures,errors,skipped}, failed[], error_head, summary_path}", text)
        # t-043 E7: --again repeats no result any more, so the card no longer offers it; the answers of the run budget are said
        check_not_in("run budget: the card does not offer --again", "--again", text)
        check_in("run budget: `reused`/`already_run` mean nothing ran, read the summary",
                 "status `reused`/`already_run` means nothing ran: read the summary", text)
        check_in("run budget: the stand door of a `version cannot be observed` answer is in the card",
                 "stand_health.py --probe --env <name>", text)
        check_in("--request too", "run_suite.py --request <work/requests/x.json>", text)
        check_in("and --detail", "run_suite.py --detail <test substring> --request <request.json>", text)
        check_in("s5_precheck with the dispatch", "s5_precheck.py --task-root <task root> --dispatch S5-qa-automator-1 [--json]", text)
        check_in("manifest_put as the fragment door", "manifest_put.py --task QA-9 --fragment <file.json>", text)
        check_in("the precheck rules are said ahead", "## The rules code will apply to your handoff", text)
        check_in("including the contradiction route", "contradicts_requirement", text)
        check_in("the gate A words reach the automator", "gate A (approved): Gate A: approved. Proceed to S5", text)
        check_in("and the standing warning", "standing: tracker_write: no", text)
        check_in("and the S5 waiver", 'S5 block "vcs-1: uncommitted changes" -> go on', text)
        check_not_in("but not another stage's waiver inline", 'S1 block "source gap"', text)
        check_in("the repo map is linked", "full map: qa-factory/artifacts/QA-9/work/briefs/repo-map-", text)
        map_files = sorted((task / "work/briefs").glob("repo-map-*.md"))
        check_eq("and written beside the brief", len(map_files), 1)
        # CX1-7 (F-4): the Branch check line costs the fixture brief ~0.4 KB, and at the 6 KB ceiling the map's head is
        # the first thing to give (build's attempts: the head is never shrunk) - so "inlined while there is room" is
        # read from a brief built with a 7 KB ceiling, and the 6 KB brief above is the proof that the line is what stays
        # while the map stays one link away.
        check_not_in("(F-4) at 6 KB the map's head yielded to the line, the link to the map stayed", "## Existing tests of the area", text)
        real_ceiling = brief_pack.BRIEF_MAX_BYTES
        brief_pack.BRIEF_MAX_BYTES = 7 * 1024      # N4: the real 7 KB budget; the section is outside it
        try:
            roomy = brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1", write=False)["markdown"]
        finally:
            brief_pack.BRIEF_MAX_BYTES = real_ceiling
        check_in("its head is inlined while there is room", "## Existing tests of the area", roomy)
        check_in("naming the window's test file", "tests/coupon/test_coupon.py", roomy)
        check_in("the map itself knows the fixture", "coupon_session(client)", map_files[0].read_text(encoding="utf-8") if map_files else "")
        check("the brief file was written", (task / "work/briefs/S5-qa-automator-1.md").is_file())
        check_eq("the words did: one waiver of another stage lives only there", result["sides"]["decisions"], True)
        check_in("and it is there", 'S1 block "source gap" -> accept the gap',
                 (task / "work/briefs/S5-qa-automator-1-decisions.md").read_text(encoding="utf-8"))
        # The brief names the running copy's own absolute path, in forward slashes (B-014 step 0: a
        # `${CLAUDE_PLUGIN_ROOT}` in a brief was text nobody expanded). The old key looked for
        # str(PLUGIN) as absent: on Windows that has backslashes the brief never writes, so it was
        # vacuous there, and on Linux (CI, B-301) it found the very path the product writes on purpose.
        check_in("scripts are named by the running copy's own absolute path, in forward slashes",
                 f'python "{(PLUGIN / "scripts").resolve().as_posix()}/<script>"', text)
        check_not_in("and never by an unexpanded plugin variable", "CLAUDE_PLUGIN_ROOT", text)
        check_not_in("judge off: no judge command for the automator either", "judge_run", text)
        # PC2-6 B6 (pop priority): the first line to go is "critic findings: none yet", while the case files are still listed
        none_yet_ceiling = s5_ceiling(lambda r: "critic findings: none yet" in r["markdown"])
        popped_one = s5_build_at(none_yet_ceiling - 1)
        check("PC2-6 B6: one byte short of keeping it, the none-yet line is gone and the case files are still listed",
              "critic findings: none yet" not in popped_one["markdown"] and "work/test-cases/coupon/TC-001.md (" in popped_one["markdown"])
        # PC2-6 O-d: words that are all short (no S1 waiver) keep level 2, the S5 waiver inline, and the files are popped from it
        pipeline_file = task / "pipeline.json"
        pipeline_kept = pipeline_file.read_bytes()
        short_doc = json.loads(pipeline_kept.decode("utf-8"))
        short_doc["stage_overrides"] = [o for o in short_doc["stage_overrides"] if o["stage"] != "S1"]
        pipeline_file.write_text(json.dumps(short_doc), encoding="utf-8")
        try:
            short_words = s5_build_at(1)
        finally:
            pipeline_file.write_bytes(pipeline_kept)
        check("PC2-6 O-d: all-short words stay at level 2 (no side-file pointer, the S5 waiver inline) while the files are popped",
              "- every decision in full - read" not in short_words["markdown"]
              and 'S5 block "vcs-1: uncommitted changes" -> go on' in short_words["markdown"] and any("input file(s)" in o for o in short_words["omitted"]))

        # --- overflow: the person's words move to a side file, the brief stays under 6 KB -----
        seed_story_for_s5(task, root, "Gate A: approved. " + "Keep every UI case in scope. " * 400)
        result = brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1")
        check("10 KB of gate words do not push the brief over 6 KB", result["budget_bytes"] <= 6 * 1024, str(result["budget_bytes"]))
        check_in("(E14) BEYOND the ceiling the words give way, the Branch check line stays whole (I6)",
                 f"Branch check: {CHECKOUT}; the implementation commit {HEAD12} (context-manifest) is this HEAD.", result["markdown"])
        check_eq("the words are in a side file the moment one is shortened", result["sides"]["decisions"], True)
        side = task / "work/briefs/S5-qa-automator-1-decisions.md"
        check("which exists", side.is_file())
        check_in("and carries them whole", "Keep every UI case in scope. " * 400, side.read_text(encoding="utf-8") if side.is_file() else "")
        # N4 (F-3): level 0 (a pointer only) no longer exists. The measured tip is level 2 -> level 1, where `## Not in the brief`
        # gains "every decision in full - read <side file>"; the gate line stays inline on BOTH sides of it, only shorter.
        gate_ceiling = s5_ceiling(lambda r: "- every decision in full - read" not in r["markdown"])
        at_gate = s5_build_at(gate_ceiling)
        check_in("while the brief keeps the gate line (AT its measured ceiling)", "gate A (approved): Gate A: approved.", at_gate["markdown"])
        below = s5_build_at(gate_ceiling - 1)
        check_in("BEYOND (control): one byte short, the gate line is STILL inline, at level 1", "gate A (approved): Gate A: approved.", below["markdown"])
        check_in("BEYOND (control): ... and `Not in the brief` names the side file", "- every decision in full - read qa-factory/artifacts/QA-9/work/briefs/S5-qa-automator-1-decisions.md", below["markdown"])
        check_not_in("BEYOND (control): ... and no pointer-only line (level 0 is gone)", "recorded decision(s):", below["markdown"])
        check_in("and links the full list", "S5-qa-automator-1-decisions.md", result["markdown"])

        # --- TQ1-11 fix 2 (B-1): the project-approach block never displaces the person's words (FR-8, AR-24) -----
        approach_scenario(task, root)
        # --- RC1-14 N4: the words first, never pushed out; the template last and outside the budget -----
        n4_scenario(task, root)

        # --- F-cmp2-12 / FR-8: a person's answer reaches the side file WHOLE ---------------------
        journal_file = root / "qa-factory" / "records" / "journal.jsonl"
        journal_before = journal_file.read_bytes() if journal_file.is_file() else None
        journal_file.parent.mkdir(parents=True, exist_ok=True)
        vocabulary = "\r\n".join(f"field_{n} = one of a | b | c (for planned/observed rows)" for n in range(40))
        vocabulary = vocabulary[:2000].rstrip()  # the journal reader strips the ends of an answer
        lead = "S3 remark kept for the gate: "
        huge = "w" * 25000
        rows = [{"event": "human_answer", "task": "QA-9", "notes": "S3 remark kept for the gate: " + vocabulary},
                {"event": "human_answer", "task": "QA-9", "notes": "S3 remark kept for the gate: " + huge}]
        journal_file.write_text((journal_before or b"").decode("utf-8")
                                + "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        try:
            brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-1")
            side_text = side.read_text(encoding="utf-8")
            check_eq("the 2,000-character answer is in the side file whole (read back with LF line ends)",
                     vocabulary.replace("\r\n", "\n") in side_text, True)
            _s, _m, whole = brief_pack.decisions({}, "S5", "qa-automator", "QA-9", root)
            check_not_in("the lines handed to the side file carry no CR", "\r", "\n".join(whole))
            check_eq("person_words_whole turns CRLF into LF", brief_pack.person_words_whole("a\r\nb"), "a\nb")
            check_eq("and leaves a text of exactly the limit alone",
                     brief_pack.person_words_whole("x" * 20000), "x" * 20000)
            check_in("one character beyond it is cut, with the pointer", "[cut: 1 more characters, the whole text is in ",
                     brief_pack.person_words_whole("x" * 20001))
            # the answer is the journal note as a whole: its lead words count toward the 20,000
            check_in("the 25,000-character answer is cut at 20,000 of the note, no further",
                     lead + "w" * (20000 - len(lead)) + f" [cut: {5000 + len(lead)} more characters", side_text)
            check_not_in("and not a character beyond the 20,000", "w" * (20001 - len(lead)), side_text)
            check_in("the cut names the file that holds the whole text",
                     "the whole text is in qa-factory/records/journal.jsonl]", side_text)
        finally:
            if journal_before is None:
                journal_file.unlink()
            else:
                journal_file.write_bytes(journal_before)

        # --- the critic's card ---------------------------------------------------------------
        critic = brief_pack.build("QA-9", "S5", "qa-code-critic", "S5-qa-code-critic-1", write=False)["markdown"]
        check_in("the P4 command has the exact shape (B-373 c: any language, --at, --release-copy)",
                 'probe_by_code.py --task QA-9 --dispatch S5-qa-code-critic-1 --test "<file>::<test name>" --instance <IID> [--oracle <file>::<function>] [--at <line>] [--release-copy <file>] [--json]',
                 critic)
        check_in("the card says what <test name> is for pytest and for another language",
                 "<test name> is [Class::]<func>[<param>] for pytest, the method or title in any other language with an "
                 "`assertion_probes` entry", critic)
        check_in("the verdicts of the probe include incomplete",
                 "{verdict intended_failure|no_failure|wrong_location|incomplete,", critic)
        check_in("incomplete and a data-gap or unresolved-copy refusal are tooling, never a verdict on the test",
                 "`incomplete`, and a refusal that names a factory data gap or a killed probe's unresolved copy, is "
                 "`tooling` (say so in your digest), never a verdict on the test", critic)
        check_in("--release-copy is named with the one condition under which it may be used",
                 "`--release-copy <file>` alone drops that copy, only after the test's author has settled the file", critic)
        check_in("and the critic reads the window's test file", "tests/coupon/test_coupon.py (", critic)
        check_in("probe_by_code is the default probe of every new/changed test",
                 "the default probe, every check of every new/changed test, one call per instance: with no --at it walks every check, and each check needs an entry in "
                 "work/probe-models/S5-qa-code-critic-1.json", critic)
        check_in("t-2064 P7: a plan of more than 3 rows runs in the background; plan_unfinished continues it; the receipt needs every owed check",
                 "a plan of more than 3 rows runs in the background; `plan_unfinished`: the same call continues it; "
                 "the live receipt is written only when every owed check is proved", critic)
        check_not_in("t-2064 P7: no `--mutation invert|expected` and no first-assert wording on the card",
                     "[--mutation invert|expected]", critic)
        check_in("red_sandbox is the critic's probe only on doubt, with the reason in the findings",
                 "red_sandbox.py --probe --request <mutations.json> --task-root", critic)
        check_in("and the line says when: only when you doubt", "only when you doubt the check looks at the product", critic)
        check_not_in("nothing calls probe_by_code the only probe any more", "the ONLY probe", critic)
        check_in("run budget: a repeat of a probe is answered already_probed", "a repeat on the same bytes and entries is answered already_probed", critic)
        check_in("t-2064 P7: red_sandbox proves the one check it names, named by a `product` entry, the others stay owed",
                 "it proves the one check it names, you name it with a `product` entry in the model file, the others stay owed", critic)
        check_in("run budget: the critic has the stand door too", "stand_health.py --probe --env <name>", critic)
        check_in("two mutations of one file are one combined replacement (B-314), said to the critic",
                 "ONE combined replacement (B-314)", critic)
        check_in("a red probe's incomplete|not_executed is a tooling finding, never a verdict on the test, said to the critic",
                 "incomplete|not_executed is `tooling`, never a verdict on the test", critic)
        check("write=False wrote no critic brief", not (task / "work/briefs/S5-qa-code-critic-1.md").exists())

        # --- the CLI ---------------------------------------------------------------------------
        cli = harness.run_script("brief_pack.py", "--task", "QA-9", "--stage", "S6", "--role", "qa-runner",
                                 "--dispatch", "S6-qa-runner-1", "--json", cwd=root, env=env)
        check_eq("the CLI exits 0", cli.returncode, 0)
        doc = json.loads(cli.stdout)
        check_in("the runner's card names finalize_task with its positional argument",
                 "finalize_task.py <task root>", doc["markdown"])
        check_not_in("run budget: the runner's --mine offers no --again", "--again", doc["markdown"])
        check_in("run budget: the runner has the stand door", "stand_health.py --probe --env <name>", doc["markdown"])
        check("the runner brief was written", (task / "work/briefs/S6-qa-runner-1.md").is_file())
        dry = harness.run_script("brief_pack.py", "--task", "QA-9", "--stage", "S7", "--role", "qa-failure-analyst",
                                 "--dispatch", "S7-qa-failure-analyst-1", "--dry-run", cwd=root, env=env)
        check_in("--dry-run says so", "not written", dry.stdout)
        # the analyst's line: the FLAKY limit is contract.FLAKY_MIN_RERUNS, quoted, never typed (t-043 E4/E7)
        analyst = brief_pack.build("QA-9", "S7", "qa-failure-analyst", "S7-qa-failure-analyst-1", write=False)["markdown"]
        check_in("run budget: the analyst's FLAKY line quotes the contract's number",
                 f"each isolated rerun of that ONE test is its own `purpose: flaky_diagnostic` request, up to {C.FLAKY_MIN_RERUNS} per test and code bytes",
                 analyst)
        check_in("run budget: and says the next one is refused", "the next one is refused", analyst)
        check_in("run budget: the analyst has the stand door", "stand_health.py --probe --env <name>", analyst)
        check("and writes nothing", not (task / "work/briefs/S7-qa-failure-analyst-1.md").exists())

        # --- the guard: a role reads the brief, not the plugin --------------------------------
        role = {"agent_id": "a301712c46df18269", "agent_type": "qa-factory:qa-automator"}
        script = str(PLUGIN / "scripts" / "run_suite.py")
        code, text = hook(root, dict(role, tool_name="Read", tool_input={"file_path": script}))
        check_eq("a role's Read of a plugin script is refused", code, 2)
        check_in("with the hint about the brief", "the brief carries the commands", text.lower())
        check_in("and that --help is allowed", "--help` is allowed", text)
        small = str(PLUGIN / "scripts" / "repo_map.py")  # under the 30 KB whole-read limit a dispatch imposes on everyone
        code, _ = hook(root, {"tool_name": "Read", "tool_input": {"file_path": small}})
        check_eq("the orchestrator's Read of a plugin script passes", code, 0)
        code, text = hook(root, dict(role, tool_name="Read", tool_input={"file_path": small}))
        check_eq("a role's Read of that same small script is refused", code, 2)
        check_in("by this rule and not the size limit", "inside the plugin is refused for a role", text)
        code, _ = hook(root, dict(role, tool_name="Read",
                                  tool_input={"file_path": str(PLUGIN / "references" / "common-rules.md")}))
        check_eq("references/ stay readable for a role", code, 0)
        code, _ = hook(root, dict(role, tool_name="Read",
                                  tool_input={"file_path": str(PLUGIN / "references" / "templates" / "config.json")}))
        check_eq("templates too", code, 0)
        # The DIRECTORY, not a file in it: `"references".startswith("references/")` is False, so
        # the guard refused the one place it documents as readable, and the measured runs show
        # six of the scout's and the strategist's refusals were exactly this call.
        code, text = hook(root, dict(role, tool_name="Grep",
                                     tool_input={"pattern": "risk", "path": str(PLUGIN / "references")}))
        check_eq("a role's Grep over references/ itself passes", code, 0)
        code, _ = hook(root, dict(role, tool_name="Glob",
                                  tool_input={"pattern": "**/*.md", "path": str(PLUGIN / "references")}))
        check_eq("and a Glob over it", code, 0)
        code, _ = hook(root, dict(role, tool_name="Read", tool_input={"file_path": str(
            PLUGIN / "references" / "slices" / "qa-runner" / "vocabularies.md")}))
        check_eq("and its own slice", code, 0)
        code, _ = hook(root, dict(role, tool_name="Grep", tool_input={"pattern": "mine", "path": str(PLUGIN / "scripts")}))
        check_eq("a role's Grep over the plugin's scripts is refused", code, 2)
        code, _ = hook(root, dict(role, tool_name="Glob", tool_input={"pattern": "**/*.md", "path": str(PLUGIN / "skills")}))
        check_eq("a role's Glob over the plugin's skills is refused", code, 2)
        code, _ = hook(root, dict(role, tool_name="Grep", tool_input={"pattern": "coupon", "path": str(root / "tests")}))
        check_eq("a role's Grep over the project passes", code, 0)
        code, _ = hook(root, dict(role, tool_name="Grep", tool_input={"pattern": "coupon"}))
        check_eq("a role's Grep with no path (the project cwd) passes", code, 0)
        code, _ = hook(root, dict(role, tool_name="Bash", tool_input={"command": f'python "{script}" --help'}))
        check_eq("a role's `--help` through Bash passes", code, 0)
        code, _ = hook(root, {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": str(PLUGIN / "scripts")}})
        check_eq("the orchestrator's Grep over the plugin passes", code, 0)
        # The Git Bash spelling (`/c/...`) exists only for a path with a drive letter; on a POSIX host the same line builds
        # `//x/...`, which is not that spelling (the CI image failed here, 28.10), so the key runs where the spelling exists.
        if len(str(PLUGIN)) > 1 and str(PLUGIN)[1] == ":":
            posix = "/" + str(PLUGIN).replace("\\", "/").replace(":", "", 1).lower() + "/agents/qa-automator.md"
            code, _ = hook(root, dict(role, tool_name="Read", tool_input={"file_path": posix}))
            check_eq("a Git Bash spelling of a plugin path is still the plugin", code, 2)
        else:
            print("INFO: the Git Bash spelling of a plugin path is a Windows drive-path case; not run on a POSIX path")

        p4_build(root, task)

        # --- the S5 window size ------------------------------------------------------------
        check_eq("no key: today's default", Controller(task)._s5_window_cases(), 4)
        set_config(root, dispatch={"api_window_cases": 3, "ui_window_cases": 2})
        check_eq("the old dispatch key still counts", Controller(task)._s5_window_cases(), 3)
        set_config(root, execution={"s5_window_cases": 8})
        check_eq("execution.s5_window_cases overrides it", Controller(task)._s5_window_cases(), 8)
        set_config(root, execution={"s5_window_cases": True})
        check_eq("a bool is not a size", Controller(task)._s5_window_cases(), 3)
        set_config(root, execution={"s5_window_cases": None})
        check_eq("null is the shipped null", Controller(task)._s5_window_cases(), 3)
        template = json.loads((PLUGIN / "references/templates/config.json").read_text(encoding="utf-8"))
        check("the template carries the key", "s5_window_cases" in template["execution"])
        check("and a note for it", "s5_window_cases" in template.get("execution_s5_window_note", ""))
        from controller import split_windows
        windows = split_windows([f"TC-{i}" for i in range(1, 10)], lambda c: False, 2, 8)
        check_eq("eight non-UI cases make one window, the ninth a second", [len(w["scope"]) for w in windows], [8, 1])

        import audit_factory
        check("brief_pack is a registered CLI script", "brief_pack" in audit_factory.CLI_SCRIPTS)
        check("repo_map is a registered CLI script", "repo_map" in audit_factory.CLI_SCRIPTS)
        wiring = json.loads((PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))
        matchers = [e.get("matcher") for e in wiring["hooks"]["PreToolUse"]]
        check("Grep and Glob reach the guard", "Grep|Glob" in matchers)
    finally:
        harness.cleanup(root)
    # --- the person's earlier answers of this story reach every later brief --------------------
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="qa-factory-brief-answers-"))
    try:
        journal = tmp / "qa-factory" / "records" / "journal.jsonl"
        journal.parent.mkdir(parents=True)
        rows = ['{"event": "human_answer", "task": "T-1", "notes": "never write to Jira"}',
                '{"event": "human_answer", "task": "T-2", "notes": "other story"}',
                '{"event": "delegated", "task": "T-1", "notes": "not an answer"}',
                '{"event": "human_answer", "task": "T-1", "notes": "never write to Jira"}']
        journal.write_text(chr(10).join(rows) + chr(10), encoding="utf-8")
        check_eq("answers_of: this story's human answers, deduplicated, oldest first",
                 brief_pack.answers_of("T-1", tmp), ["never write to Jira"])
        check_eq("answers_of: no journal -> no answers", brief_pack.answers_of("T-1", tmp / "none"), [])
        shown, minimal, full = brief_pack.decisions({}, "S3", "qa-test-strategist", "T-1", tmp)
        check("decisions: the answer is among the person's words", any("never write to Jira" in x for x in full))
        check("decisions: the answer is shown, not only in the full file", any("never write to Jira" in x for x in shown))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the implementation diff is a required source, never a place to skim -------------------
    tmp = Path(tempfile.mkdtemp(prefix="qa-factory-brief-diff-"))
    try:
        (tmp / "impl-diff.txt").write_text("x" * 10, encoding="utf-8")
        (tmp / "big.txt").write_text("x" * (brief_pack.SLICE_BYTES + 1), encoding="utf-8")
        lines = brief_pack.file_lines(["impl-diff.txt", "big.txt"], tmp, tmp)
        # SC1-10: a role WITH a shell reads the diff through diff_pass (every changed line of every hunk); the text "read
        # EVERY hunk, whole, in slices" stays for a role without one (it is never named a script)
        check("impl-diff (a role with a shell): the diff pass, every changed line of every hunk",
              any("impl-diff.txt" in x and "--files-only" in x and "--max-lines 100000" in x for x in lines), str(lines))
        lines_plain = brief_pack.file_lines(["impl-diff.txt", "big.txt"], tmp, tmp, shell=False)
        check("impl-diff (no shell): read every hunk, whole", any("impl-diff.txt" in x and "EVERY hunk" in x for x in lines_plain),
              str(lines_plain))
        check("another big file: slice it", any("big.txt" in x and "slice it" in x for x in lines), str(lines))

        # FR-15: a declared input that is not there yet is still named. It used to be dropped,
        # and the role then hunted for it: 129 of run 5's 644 reads missed, the same file tried
        # at two levels (`test-plan.md` 8 times, `work/test-plan.md` 5).
        absent = brief_pack.file_lines(["work/requirements-register.md", "work/test-cases/"], tmp, tmp)
        check("an input nothing has written yet is named, not dropped",
              any("work/requirements-register.md" in x and "not written yet" in x for x in absent), str(absent))
        check("and so is a stage folder that does not exist yet",
              any("work/test-cases/" in x and "not written yet" in x for x in absent), str(absent))
        (tmp / "work").mkdir()
        (tmp / "work" / "requirements-register.md").write_text("# register", encoding="utf-8")
        there = brief_pack.file_lines(["work/requirements-register.md"], tmp, tmp)
        check("once it exists the line is the file, not a promise",
              any("work/requirements-register.md" in x and "not written yet" not in x for x in there), str(there))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    left_out_sources()
    ticket_view_lines()
    reference_gap_lines()
    reads_skipped_lines()
    expectation_lines()
    proof_lines()
    branch_check_lines()
    blast_radius_lines()
    labelling_vocabulary_lines()
    sc1_10_lines()
    oh3_34_p1_areas_section()
    pc8_scenarios()

    base =Path(tempfile.mkdtemp(prefix="qa-factory-brief-p4-"))
    try:
        p4_lines(base)
        p4_long_words(base)
        p4_breakage(base)
        p4_halts(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    harness.finish("test_brief_pack")


if __name__ == "__main__":
    main()
