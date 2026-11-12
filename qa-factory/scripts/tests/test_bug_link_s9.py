#!/usr/bin/env python3
"""A filed bug keeps its case, and the S9 exit does not send the report back to S8 for a block of code (HF8-22, run 12586).

Keys: L1 a filed `BUG-1.md` whose front matter holds no case id still joins its case through the draft it names (`source_draft`),
and a filed bug that names no case at all is told as such, never as "bug not filed"; L2 a requirement is read from a draft only by its
structural fields (an `R-99` in the prose is no link), no draft and an empty head read the head alone; L3 `report_facts --write`
renders the appendix again, keeps every other byte and the old report, and leaves the appendix alone when the trace cannot be built;
L4 the S9 exit rebuilds a stale appendix itself and never names S8 for it, a refusal that is the scribe's still names the scribe;
L5 the refusal of a missing "Left with you" item keeps the scribe's door; L6 with no driver the S9 refusal is left where
`waiver.py --block "report check"` reads it (kind `door`, not `unknown`), the same bytes the driver writes, a close erases it, the
record of another stage is left, a record that cannot be written is one line and the refusal stands.
"""
import contextlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import report_facts as RF  # noqa: E402
import stage_done as SD  # noqa: E402
import traceability as TR  # noqa: E402
import waiver as W  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "after-checks"
TEST_ID = "tests/test_coupon.py::test_cap_rejected"
HEAD = ("---\nid: BUG-1\ntitle: Move fails\nseverity: major\nviolates: requirement:R-1\nsource_draft: work/bug-drafts/move.json\n"
        "confirmation: confirmed_by_person\n---\n\n## Actual result\nIt fails.\n")
DRAFT = {"title": "Move fails", "case": "TC-001", "requirements": ["R-1"], "actual": "see also R-99 and TC-009"}


def project() -> tuple:
    """(project root, the task folder QA-1): the `after-checks` story inside a project the hook layer is pointed at."""
    root = temp_project("qa-bug-link-")
    task = root / "qa-factory" / "artifacts" / "QA-1"
    shutil.copytree(FIXTURE, task)
    use_project(root)
    C.case_config_reset()
    return root, task


def edit(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def red(task: Path) -> None:
    """The `test_third_verdict` setup: TC-001's run row failed and the analyst's row says APP_BUG."""
    edit(task / "work" / "run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
    edit(task / "work" / "triage.json", lambda t: t["triage"].append(
        {"instance_id": TEST_ID, "attempt_id": "a1", "verdict": "APP_BUG", "evidence": "evidence/sanity-20260911-105500.json"}))


def file_bug(task: Path, head=HEAD, draft=DRAFT) -> None:
    (task / "bugs").mkdir(exist_ok=True)
    (task / "bugs" / "BUG-1.md").write_text(head, encoding="utf-8")
    drafts = task / "work" / "bug-drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    for old in drafts.glob("*.json"):
        old.unlink()
    if draft is not None:
        (drafts / "move.json").write_text(json.dumps(draft), encoding="utf-8")


def outcome(task: Path) -> dict:
    story = TR.Story(task.parents[1], task)
    key = C.test_instance_id(story.manifest["tests"][0])
    return story.instance_outcome(key, "TC-001", "R-1")


def records(task: Path) -> list:
    return TR.story_bug_records(task.parents[1], task)["records"]


def l1_the_draft_joins_the_case() -> None:
    root, task = project()
    try:
        red(task)
        check_eq("L1 control: no bug filed, the row says so", outcome(task)["basis"], "red run, triaged APP_BUG: no reason recorded; bug not filed")
        file_bug(task)
        found = records(task)
        check_eq("L1 the filed record names the draft it was filed from", [r["source_drafts"] for r in found], [["work/bug-drafts/move.json"]])
        check_eq("L1 its cases are the draft's (the head holds none)", [r["cases"] for r in found], [["TC-001"]])
        said = outcome(task)
        check_eq("L1 the row of TC-001 reads BUG-1, as the 12586 report did not", (said["result"], said["bug"]), ("bug", "BUG-1"))
        check_not_in("L1 ... and not `bug not filed`", "bug not filed", said["basis"])
        # the head's own case id and the draft's are one union, nothing lost
        file_bug(task, head=HEAD.replace("violates:", "case: TC-002\nviolates:"))
        check_eq("L1 head and draft are united, in order, with no repeat", records(task)[0]["cases"], ["TC-002", "TC-001"])
        # the draft is gone (deleted, renamed): the head alone is read, and the row tells what is true
        file_bug(task, draft=None)
        check_eq("L1 no draft: the head alone, no cases", records(task)[0]["cases"], [])
        said = outcome(task)
        check_in("L1 a filed bug that names no case is said so", "bug BUG-1 is filed but names no case", said["basis"])
        check_not_in("L1 ... never `bug not filed`", "bug not filed", said["basis"])
        check_eq("L1 ... and the word stays `blocked`: no bug is joined to this case", said["result"], "blocked")
    finally:
        cleanup(root)


def l2_requirements_are_structural() -> None:
    root, task = project()
    try:
        bare = HEAD.replace("violates: requirement:R-1\n", "")
        file_bug(task, head=bare, draft=dict(DRAFT, requirements=["R-1"], violates="requirement:R-3", triage_ref="R-4"))
        found = records(task)[0]
        check_eq("L2 the requirements come from the draft's structural fields, not its prose (`R-99` in `actual`)",
                 sorted(found["requirements"]), ["R-1", "R-3", "R-4"])
        check_not_in("L2 ... `R-99` is no link", "R-99", " ".join(found["requirements"]))
        file_bug(task, head=bare, draft={"title": "x", "case": "TC-001", "actual": "R-99 mentioned"})
        check_eq("L2 a draft with no structural field adds no requirement", records(task)[0]["requirements"], [])
        # a record with a draft only keeps the old reading (all of the draft's JSON): the bytes of that branch did not change
        (task / "bugs" / "BUG-1.md").unlink()
        file_bug(task, head=bare, draft=DRAFT)
        (task / "bugs" / "BUG-1.md").unlink()
        only = [r for r in records(task) if not r["filed"]]
        check_eq("L2 an unfiled draft is read as before: its case, and every id its JSON holds", (only[0]["cases"], sorted(only[0]["requirements"])),
                 (["TC-001"], ["R-1", "R-99"]))
        # an unreadable draft name
        file_bug(task, head=HEAD.replace("work/bug-drafts/move.json", "../outside.json"), draft=DRAFT)
        check_eq("L2 a `source_draft` that is no draft of the story adds nothing", records(task)[0]["cases"], [])
    finally:
        cleanup(root)


def report_task() -> tuple:
    """A project with the `after-checks` story whose report is written by `report_facts --write`."""
    root, task = project()
    CD.assess(task)
    written = RF.write(task)
    check("L3 setup: the report is written", written["ok"], str(written["lines"]))
    return root, task


def appendix_cut(text: str) -> tuple:
    """(the report with its appendix body cut out, the appendix body)."""
    begin, end = RF._section_span(text, "## Appendix")
    head, _nl, body = text[begin:end].partition("\n")
    return text[:begin] + head + "\n" + text[end:], body


def l3_write_renders_the_appendix() -> None:
    root, task = report_task()
    try:
        path = task / "test-report.md"
        check_eq("L3 a fresh report checks clean, the appendix included", RF.check(task), [])
        fresh = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"(\| R-3 \|.*?)\*\*deferred\*\*", r"\1**pass**", fresh, count=1), encoding="utf-8")
        stale = path.read_text(encoding="utf-8")
        stale_bytes = path.read_bytes()
        check("L3 setup: the edit changed the appendix", stale != fresh)
        found = [p for p in RF.check(task) if "appendix" in p]
        check_eq("L3 `--check` says it in ONE line", len(found), 1)
        check_in("L3 ... worded as a stale block, door `--write`", "block `appendix` differs from a fresh render of the trace", found[0])
        written = RF.write(task)
        now = path.read_text(encoding="utf-8")
        check_eq("L3 `--write` brings the appendix to the render: the report is the fresh one, byte for byte", now, fresh)
        check_eq("L3 ... and `--check` is clean", RF.check(task), [])
        check("L3 the replaced bytes are saved (history)", bool(written["history"]) and Path(written["history"]).read_bytes() == stale_bytes,
              str(written))
        check_in("L3 ... and the note says what was replaced", "replaced the appendix", " ".join(written["lines"]))
        # the neighbours: a hand edit of the appendix AND of the prose after it; only the appendix body changes
        edited = stale.replace("## Appendix", "## Appendix", 1)
        after = "## Retro proposals\n\n- kept"
        path.write_text(edited.rstrip("\n") + "\n\n" + after + "\n", encoding="utf-8")
        before_cut, _ = appendix_cut(path.read_text(encoding="utf-8"))
        RF.write(task)
        after_cut, body = appendix_cut(path.read_text(encoding="utf-8"))
        check_eq("L3 every other section and block keeps its bytes (only the appendix body moved)", after_cut, before_cut)
        check_in("L3 the prose after the appendix is still there", after, path.read_text(encoding="utf-8"))
        check_in("L3 the body is the render", TR.render(TR.build(task.parents[1], task)).strip("\n").splitlines()[-1], body)
        # idempotent: a second write changes nothing
        once = path.read_bytes()
        again = RF.write(task)
        check_eq("L3 a second `--write` changes no byte", path.read_bytes(), once)
        check_in("L3 ... and says every block already matches", "already matches a fresh render", " ".join(again["lines"]))
        check_not_in("L3 (t-436) ... and does not claim it replaced an appendix that was equal (an equal body is no change)",
                     "replaced the appendix", " ".join(again["lines"]))
        current = path.read_text(encoding="utf-8")
        check_eq("L3 (t-436) `_refresh_appendix` over an equal body returns the text as it is and an empty note",
                 RF._refresh_appendix(current, task, task.parents[1]), (current, ""))
        # a trace that cannot be built: the appendix is not touched, one line says so, `--check` still refuses
        path.write_text(stale, encoding="utf-8")
        saved = RF.T.build
        try:
            def boom(*_a):
                raise RuntimeError("the cases folder is gone")
            RF.T.build = boom
            res = RF.write(task)
            _cut, body = appendix_cut(path.read_text(encoding="utf-8"))
            check_in("L3 a trace that cannot be built leaves the hand-made appendix as it is", "**pass**", body)
            check_in("L3 ... and says so", "the appendix was not refreshed: the trace could not be built (RuntimeError", " ".join(res["lines"]))
            check_in("L3 ... `--check` is no pass", "the appendix could not be compared", " ".join(RF.check(task)))
        finally:
            RF.T.build = saved
    finally:
        cleanup(root)


def s9(task: Path) -> tuple:
    """(exit code, stdout, stderr) of `stage_done.s9_exit` over the story."""
    path = task / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = SD.s9_exit("QA-1", path, pipeline)
    return code, out.getvalue(), err.getvalue()


def l4_the_exit_rebuilds_the_appendix() -> None:
    root, task = report_task()
    try:
        path = task / "test-report.md"
        fresh = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"(\| R-3 \|.*?)\*\*deferred\*\*", r"\1**pass**", fresh, count=1), encoding="utf-8")
        code, out, err = s9(task)
        check_eq("L4 a stale appendix does not refuse S9", code, 0)
        check_in("L4 ... it is rebuilt by the exit, once, and said", "block `appendix` was stale; rebuilt now", out)
        check_not_in("L4 ... and S8 is named nowhere", "--stage S8", out + err)
        check_eq("L4 ... the report is the fresh one again", path.read_text(encoding="utf-8"), fresh)
        check("L4 ... no record of a standing refusal is left", not W.standing_path("QA-1", task).exists())
        # damaged markers: the scribe's door stays, and nothing is written over them
        path.write_text(fresh.replace("<!-- /facts:verdict -->", "", 1), encoding="utf-8")
        damaged = path.read_bytes()
        code, out, err = s9(task)
        check_eq("L4 damaged markers refuse S9", code, SD.EXIT_BAD_ARGS)
        check_in("L4 ... the door is the scribe's (S8), for a damaged marker", "--stage S8 --role qa-doc-scribe", err)
        check_in("L4 ... and the text says S8 is never reopened for a block of code, and that a recorded word passes",
                 "S8 is never reopened for one of them", err)
        check_in("L4 ... a person's recorded word passes it", "their recorded word passes it", err)
        check_eq("L4 ... nothing was written over the damaged report", path.read_bytes(), damaged)
    finally:
        cleanup(root)


def l5_the_scribes_own_item_keeps_the_scribes_door() -> None:
    root, task = report_task()
    try:
        path = task / "test-report.md"
        full = path.read_text(encoding="utf-8")
        lines = full.splitlines(keepends=True)
        path.write_text("".join(ln for ln in lines if "(R-4, TC-004)" not in ln), encoding="utf-8")
        code, _out, err = s9(task)
        check_eq("L5 a missing \"Left with you\" item refuses S9", code, SD.EXIT_BAD_ARGS)
        check_in("L5 ... naming the item", "has no item for case TC-004", err)
        check_in("L5 ... the scribe's door stays for the scribe's own items", "qa-doc-scribe", err)
        check_in("L5 ... and the record holds the problem", "has no item for case TC-004",
                 " ".join(W.read_standing("QA-1", "S9")["lines"]))
    finally:
        cleanup(root)


def l6_the_refusal_is_left_for_the_waiver() -> None:
    root, task = report_task()
    try:
        path = task / "test-report.md"
        fresh = path.read_text(encoding="utf-8")
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        kind, _lines, _row = W.block_standing("QA-1", "S9", "report check", pipeline)
        check_eq("L6 control: with no refusal recorded the block is `unknown` (the 12586 answer)", kind, "unknown")
        path.write_text(fresh.replace("<!-- /facts:verdict -->", "", 1), encoding="utf-8")
        code, _out, _err = s9(task)
        check_eq("L6 setup: the refusal stands", code, SD.EXIT_BAD_ARGS)
        record = W.standing_path("QA-1", task)
        check("L6 the refusal is recorded where the waiver reads it", record.is_file())
        data = json.loads(record.read_text(encoding="utf-8"))
        check_eq("L6 stage and door", (data["stage"], data["doors"]), ("S9", [SD.REPORT_BLOCK]))
        check("L6 the lines are the refusal's, `report check:` first", data["lines"] and all(ln.startswith("report check:") for ln in data["lines"]),
              str(data))
        kind, lines, _row = W.block_standing("QA-1", "S9", SD.REPORT_BLOCK, pipeline)
        check_eq("L6 `--block \"report check\"` is the refusal's own door, no longer `unknown`", kind, "door")
        check_eq("L6 ... and names what it passes: the lines of the record", lines, data["lines"])
        # the bytes of the record are the ones the driver writes: ONE writer
        W.write_standing("QA-1", "S9", data["lines"], data["doors"], root=task)
        check_eq("L6 the writer is deterministic: the same call, the same bytes", record.read_text(encoding="utf-8"),
                 json.dumps({"stage": "S9", "lines": data["lines"], "doors": data["doors"]}, ensure_ascii=False, indent=2))
        # another stage's record is not S9's to erase, and a close erases its own
        path.write_text(fresh, encoding="utf-8")
        W.write_standing("QA-1", "S5", ["a refusal of S5"], ["some door"], root=task)
        code, _out, _err = s9(task)
        check_eq("L6 the report is whole: S9 closes", code, 0)
        check_eq("L6 ... the record of ANOTHER stage is left", json.loads(record.read_text(encoding="utf-8"))["stage"], "S5")
        W.write_standing("QA-1", "S9", ["a refusal of S9"], [SD.REPORT_BLOCK], root=task)
        code, _out, _err = s9(task)
        check_eq("L6 S9 closes again", code, 0)
        check("L6 ... and S9's own record is erased", not record.exists())
        # a record that cannot be written is one line, the refusal stands (FR-41)
        path.write_text(fresh.replace("<!-- /facts:verdict -->", "", 1), encoding="utf-8")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.mkdir()
        code, _out, err = s9(task)
        check_eq("L6 the record cannot be written: the refusal stands", code, SD.EXIT_BAD_ARGS)
        check_in("L6 ... and one line says the record was not kept", "the record of the standing refusal could not be kept", err)
    finally:
        cleanup(root)


def l7_the_mr_text_knows_a_filed_bug() -> None:
    """F-2: the markdown channel writes no proposal, yet the MR description must not say "chosen at gate B, not filed yet" about a bug
    that lies in bugs/ (`delivery_summary.build` asks the bug reader where the draft went). Kill: the pairing removed."""
    import delivery_summary as DS
    root, task = project()
    try:
        red(task)
        file_bug(task, head=HEAD.replace("confirmation: confirmed_by_person\n", "confirmation: confirmed_by_person\ngate_b_decision_id: gateB-QA-1\n"))
        (task / "state").mkdir(exist_ok=True)
        (task / "state" / "controller.json").write_text(json.dumps({"decisions": {"gateB-QA-1": {
            "id": "gateB-QA-1", "gate": "B", "status": "approved", "selected_drafts": ["work/bug-drafts/move.json"]}}}), encoding="utf-8")

        def rows():
            return [b for b in DS.build(task)["bugs"] if b["ref"].endswith("move.json")]
        got = rows()
        check_eq("L7 a chosen draft that a bug file names reads `filed`, not `selected`", [b["state"] for b in got], ["filed"])
        text = DS.render(DS.build(task))
        check_in("L7 the MR text says it is a file in the repository", "filed as a bug file in the repository, not in the tracker", text)
        check_not_in("L7 ... and never `not filed yet` about it", "not filed yet", text)
        (task / "bugs" / "BUG-1.md").unlink()
        check_eq("L7 control: with no bug file the same draft is still `selected` (the old reading stands)", [b["state"] for b in rows()], ["selected"])
        file_bug(task, head=HEAD.replace("confirmation: confirmed_by_person\n", "confirmation: confirmed_by_person\nexternal_id: PRJ-7\n"))
        got = rows()
        check_eq("L7 a bug file that carries a tracker id reads `published` with the key", [(b["state"], b["external_id"]) for b in got],
                 [("published", "PRJ-7")])
    finally:
        cleanup(root)


def l8_the_driver_rebuilds_after_the_reporter() -> None:
    """F-2, the driver road: after the reporter filed, the report and the MR description are written again over the files as they now
    lie, BEFORE the MR order is settled, on every pass (a resume repeats it), without computing the verdict again, and never once the
    delivery left its mark. Kills: the call removed from `after_gate_B`; the call moved after `settle_mr`; the verdict recomputed."""
    from story_run_common import driver_for, seed
    import story_run
    root, task_root, env = seed("QA-1")
    try:
        d = driver_for(root, env, "QA-1")
        calls: list = []
        d.py = lambda script, *args, **kw: calls.append((script, kw.get("check"))) or (0, "")
        d.rebuild_report = lambda: calls.append(("rebuild_report", None)) or True
        check_eq("L8 no report yet: nothing is rebuilt", (d.refresh_after_reporter(), calls), (None, []))
        (task_root / "test-report.md").write_text("# report\n", encoding="utf-8")
        d.refresh_after_reporter()
        check_eq("L8 the report blocks, then the MR description (a refusal of it is a Refusal)",
                 calls, [("rebuild_report", None), ("delivery_summary.py", True)])
        calls.clear()
        d.state["delivery"] = {"action": "continue", "did": "opened"}
        d.refresh_after_reporter()
        check_eq("L8 the delivery left its mark: nothing is written over the MR that went out", calls, [])
        d.state.pop("delivery")

        def refused(script, *args, **kw):
            raise story_run.Refusal("the description could not be written")
        d.py = refused
        try:
            d.refresh_after_reporter()
            raised = None
        except story_run.Refusal as refusal:
            raised = refusal
        check("L8 a refused description is a Refusal that retries the whole S9 step", raised is not None and raised.retry == d.stage_S9, repr(raised))
        order: list = []
        d.recompute_verdict = lambda: order.append("recompute_verdict") or "yes"
        d.controller_state = lambda: {}
        d.refresh_after_reporter = lambda: order.append("refresh_after_reporter")
        d.settle_mr = lambda decision, statuses: order.append("settle_mr")
        d.after_gate_B()
        d.after_gate_B()
        check_eq("L8 after_gate_B: the verdict once per pass, the rebuild before the MR order, on every pass",
                 order, ["recompute_verdict", "refresh_after_reporter", "settle_mr"] * 2)
    finally:
        cleanup(root)


MERGED = {"title": "Quantity turns input into another number", "case": "TC-001", "cases": ["TC-001", "TC-002"], "requirements": ["R-1"],
          "manifestations": [
              {"action": "type -1", "start_state": "selected", "seen": "11", "requirement": "R-1", "case": "TC-001",
               "evidence": "e.txt", "red_test_none": "manual"},
              {"action": "type 1.5", "start_state": "erased", "seen": "1", "requirement": "R-3", "case": "TC-003",
               "evidence": "e.txt", "red_test_none": "manual"}],
          "mechanism": {"statement": "the field coerces", "status": "unverified", "why": "one start state", "basis": [],
                        "claims": [{"says": "pasting acts alike", "confirmed_by": []}]},
          "possibly_same_cause": [{"draft": "work/bug-drafts/cart.json", "why": "both turn input into another number"}]}


def l9_one_bug_many_manifestations() -> None:
    """t-2187 (5.5, 5.6): a case covered only by a manifestation joins the merged bug, `cases` is not dropped when `case` is set, an
    old draft reads as it did, and the record carries the ways, the cause and the link for the report (filed and unfiled alike)."""
    root, task = project()
    try:
        red(task)
        file_bug(task, draft=MERGED)
        found = records(task)
        check_eq("L9 one record: `case`, `cases` and the manifestations' case, in the reader's order", [r["cases"] for r in found],
                 [["TC-001", "TC-002", "TC-003"]])
        check_eq("L9 the requirements are the union (structural fields and the manifestation's)", sorted(found[0]["requirements"]), ["R-1", "R-3"])
        check_eq("L9 one line per way it shows", found[0]["manifestations"],
                 ["type -1; start: selected; seen: 11", "type 1.5; start: erased; seen: 1"])
        check_eq("L9 the cause: word, not-verified claims, standing", (found[0]["mechanism"]["status"], found[0]["mechanism"]["unverified"]),
                 ("unverified", ["pasting acts alike"]))
        check_eq("L9 the link names a draft by its stem, never a path", found[0]["possibly_same_cause"], ["cart"])
        check_eq("L9 the stem of the draft file it came from, for the report's link", found[0]["draft_names"], ["move"])
        story = TR.Story(task.parents[1], task)
        for case in ("TC-001", "TC-002", "TC-003"):
            check_eq(f"L9 `bug_for` {case} returns the merged bug (a case only a manifestation names included)", story.bug_for(case, "R-1").get("id"), "BUG-1")
        # one bug per case, as today: the first filed one answers for a case two bugs cover (5.6, unchanged)
        check_eq("L9 a case no draft names has no bug", story.bug_for("TC-009", "R-1"), {})
        # an old draft reads as today
        file_bug(task, draft=DRAFT)
        old = records(task)[0]
        check_eq("L9 an old draft: its case, no ways, no cause, no link", (old["cases"], old["manifestations"], old["mechanism"], old["possibly_same_cause"]),
                 (["TC-001"], [], {}, []))
        # unfiled: the other branch reads the same facts
        (task / "bugs" / "BUG-1.md").unlink()
        file_bug(task, head=HEAD, draft=MERGED)
        (task / "bugs" / "BUG-1.md").unlink()
        only = [r for r in records(task) if not r["filed"]]
        check_eq("L9 an unfiled merged draft: all three cases, two ways", (only[0]["cases"], len(only[0]["manifestations"])),
                 (["TC-001", "TC-002", "TC-003"], 2))
        # a draft that names no case anywhere is still read by its file name
        file_bug(task, draft={"title": "x"})
        (task / "bugs" / "BUG-1.md").unlink()
        check_eq("L9 no case in the draft: read by its file name (`move`), which is no case id, as before",
                 [r["cases"] for r in records(task) if not r["filed"]], [[]])
    finally:
        cleanup(root)


def main() -> None:
    l1_the_draft_joins_the_case()
    l2_requirements_are_structural()
    l3_write_renders_the_appendix()
    l4_the_exit_rebuilds_the_appendix()
    l5_the_scribes_own_item_keeps_the_scribes_door()
    l6_the_refusal_is_left_for_the_waiver()
    l7_the_mr_text_knows_a_filed_bug()
    l8_the_driver_rebuilds_after_the_reporter()
    l9_one_bug_many_manifestations()
    finish("bug link and S9 door")


if __name__ == "__main__":
    main()
