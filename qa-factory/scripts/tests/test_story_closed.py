#!/usr/bin/env python3
"""A finished story is closed, and a tail on it is a contradiction (TP2-2534, I-92).

2534 went S1-S8, gates A and B, twelve automated cases, MR !55 merged, suite 173/173 — and
its `pipeline.json` still held a stage `running` with the controller answering `await_gate
A`. `recover` repaired nothing: by its own rules an open dispatch on a running stage is work
in progress, and the host could prove nothing about it either way. What no reader could see
is that the story was over, so there was no work left for that tail to be part of. It then
made the stage guard's "single running story" fallback ambiguous, and every desktop dispatch
of the LIVE story was refused for two days (I-90).

Everything here asks one question in the four places it is asked: does the factory know this
story is finished — when it writes the fact, when it refuses to leave a tail behind, when a
person goes back to a closed story, and when `recover` is asked to settle one.
"""
import contextlib
import copy
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import grammar as G  # noqa: E402
import planning_contract  # noqa: E402
import report_facts as RF  # noqa: E402
import stage_done  # noqa: E402
import stage_guard  # noqa: E402
from controller import Controller, STALE_AFTER_CLOSURE  # noqa: E402
from hooklib import story_closed  # noqa: E402

import test_controller_state as BASE  # noqa: E402
import test_report_facts as TR  # noqa: E402

GHOST = "S3-stray-1"


def closed_story(root):
    """A story that really is finished: S0-S8 accepted, gate A exact, gate B delivered."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(controller, root, f"S{number}")
    controller.apply("decision", BASE.bind_gate_a(root, {
        "id": "A", "gate": "A", "action": "approve", "status": "approved",
        "authorization_source": "human", "source_revision": "src-1", "scope": ["TC-1"],
        "input_revision": "src-1", "idempotency_key": "A"}))
    for number in range(5, 9):
        BASE.accept_stage(controller, root, f"S{number}")
    controller.apply("decision", {"id": "B", "gate": "B", "action": "deliver", "status": "approved",
                                  "authorization_source": "human", "source_revision": "src-1",
                                  "scope": ["TC-1"], "input_revision": "src-1",
                                  "selected_drafts": [], "idempotency_key": "B"})
    return controller


def pipeline_of(root):
    return json.loads((root / "pipeline.json").read_text(encoding="utf-8"))


def packet(identifier, stage="S3", role="qa-worker", **extra):
    return dict({"id": identifier, "stage": stage, "role": role, "scope": ["TC-1"], "input_hash": "stray",
                 "budget": {}, "known_paths": {}}, **extra)


def stray(controller, identifier, **extra):
    """A dispatch on a CLOSED story the way 2534 got one: past the validator (which refuses it now), into the journal."""
    controller.store.commit("dispatch", packet(identifier, **extra), "stray:" + identifier, None, None, controller.project)


def never_started(controller, identifier, **extra):
    """`stray`, then the liveness repair that records it as a dispatch that never reached an agent."""
    stray(controller, identifier, **extra)
    controller.store.commit("state_repair", {"fixes": [{"kind": "never_started", "dispatch_id": identifier,
                                                        "stage": extra.get("stage", "S3"), "reason": "the hook refused the call"}],
                                             "reason": "test"}, "repair:" + identifier, None, None, controller.project)


def refused(call):
    """`(class name, text)` of the refusal `call` raises, or None when it passes."""
    try:
        call()
    except Exception as exc:                 # noqa: BLE001 - the class is what the test reads
        return type(exc).__name__, str(exc)
    return None


# --- the one reading of "closed" ---------------------------------------------------------

def the_rule_is_read_in_one_place():
    done = {"status": "done", "finished": "2026-09-20T10:00:00+00:00"}
    open_story = {"stages": {"S8": done}, "gates": {"A": {"decision": "approved"}}}
    check_eq("a story whose gate B nobody answered is open", story_closed(open_story), "")
    closed = {"stages": {"S8": done},
              "gates": {"B": {"decision": "deliver", "at": "2026-09-20T11:00:00+00:00"}}}
    check_eq("gate B decided and S8 done is closed, with the decision's own time",
             story_closed(closed), "2026-09-20T11:00:00+00:00")
    # One field, two vocabularies — the lesson of TP1-15045. The controller writes
    # `status`, the orchestrator used to write `decision`, and `contract.gate_answered` is
    # the one reader that knows both spellings.
    check("a controller-written gate B (status, no decision word) closes the story too",
          bool(story_closed({"stages": {"S8": done},
                             "gates": {"B": {"status": "approved", "at": "T"}}})))
    check_eq("a declined gate B still finishes the story — a decline is an answer",
             bool(story_closed({"stages": {"S8": done}, "gates": {"B": {"decision": "declined"}}})),
             True)
    ghost = dict(closed, stages=dict(closed["stages"], S3={"status": "running"}))
    check("a `running` stage does NOT reopen a closed story — that is the whole point",
          bool(story_closed(ghost)))
    reopened = dict(closed, closed_at="2026-09-20T11:00:00+00:00",
                    reopened_at="2026-09-21T09:00:00+00:00", reopened_by_words="one more look")
    check_eq("only a person's recorded word reopens it", story_closed(reopened), "")
    check_eq("a story with no pipeline at all is not closed", story_closed(None), "")


# --- the writers -------------------------------------------------------------------------

def the_writers_stamp_the_closure():
    root = temp_dir("qa-2534-closed-")
    try:
        controller = closed_story(root)
        pipeline = pipeline_of(root)
        check("the controller's projection stamps closed_at", bool(pipeline.get("closed_at")),
              json.dumps({k: pipeline.get(k) for k in ("closed_at", "closed_by")}))
        check_eq("and says what closed it", pipeline.get("closed_by"), "gate B + S8 done")
        first = pipeline["closed_at"]
        Controller(root).recover()
        check_eq("a story closes once: a re-projection never restamps it",
                 pipeline_of(root).get("closed_at"), first)
        action = controller.next_action()
        check_eq("a delivered story's next action is `closed`, never a gate it already passed",
                 action["action"], "closed")
        check_eq("carrying the time it closed", action["closed_at"], first)
        check("and the retro, the one stage that still runs on a closed story",
              action.get("retro_pending") and action.get("stage") == "S9")
    finally:
        cleanup(root)


def stage_done_stamps_an_unmanaged_story():
    """A story from 0.7.x, closed by `stage_done` alone: the same two facts, no controller."""
    project = temp_project("qa-2534-legacy-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "TP2-2534"
        task.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({
            "ticket": "TP2-2534", "stages": {f"S{n}": {"status": "done"} for n in range(9)},
            "gates": {"A": {"decision": "approved"}, "B": {"decision": "deliver"}}}), encoding="utf-8")
        code = stage_done.run("TP2-2534", "S9", "running", "qa-retro-analyst", "", True)
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("the first write after gate B and S8 goes through", code, 0)
        check("and stamps closed_at with no controller in sight — a 0.7.x story needs no "
              "migration, only a reader", bool(pipeline.get("closed_at")),
              json.dumps(pipeline.get("closed_at")))
        return project, task
    except Exception:
        cleanup(project)
        raise


def s9_refuses_to_leave_a_tail(project, task):
    """S9 is the last thing a story does, so a stage still `running` is a tail forever."""
    try:
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stages"]["S3"] = {"status": "running", "role": "qa-test-strategist"}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        # An older-contract report: the S9 report check prints that it is not checked and passes, so
        # this test stays about the tail. (With no report at all the tail is refused first, below.)
        (task / "test-report.md").write_text("# report\n\n## Check coverage\n\nold contract\n", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = stage_done.run("TP2-2534", "S9", "done", "qa-retro-analyst", "retro", True)
        check_eq("S9 done is refused while another stage is running", code, stage_done.EXIT_BAD_ARGS)
        check_in("the refusal names the stage", "S3 is still running", stderr.getvalue())
        check_in("and the one command that settles it", "--operation recover", stderr.getvalue())
        check_in("and the way a person's word passes it", "waiver.py", stderr.getvalue())
        # The standing rule of this factory: a person's recorded word passes any block.
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S9", "match": "still running",
                                        "decision": "the MR is merged, close it"}]
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = stage_done.run("TP2-2534", "S9", "done", "qa-retro-analyst", "retro", True)
        check_eq("and the person's recorded word closes it anyway", code, 0)
        check_in("saying whose decision it was", "on the person's word", stderr.getvalue())
    finally:
        cleanup(project)


# --- the S9 exit checks the report (B-211, P9a) ------------------------------------------------
#
# TP1-13797's report said "No product bug is recorded" beside a BUG-1 in the story's folder. The S9
# exit now runs `report_facts.check` (pure, FR-45). What it refuses is what the rebuild cannot settle
# by itself, and every refusal names its door and the person's word; what the rebuild can settle (a stale
# block) is printed and the story goes on. The fixtures are test_report_facts.py's own.

def run_s9(ticket, status="done", role="", no_journal=True):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stage_done.run(ticket, "S9", status, role, "retro", no_journal)
    return code, out.getvalue(), err.getvalue()


def marked_story():
    """T-1 with every source and a report that was converted and checks clean."""
    task = TR.story()
    TR.legacy_report(task)
    written = RF.write(task)
    check("the fixture report is written and checks clean", written["ok"] and RF.check(task) == [],
          str(written["lines"]))
    return task


def pipeline_at(task):
    return json.loads((task / "pipeline.json").read_text(encoding="utf-8"))


def edit_report(task, old, new):
    path = task / "test-report.md"
    text = path.read_text(encoding="utf-8")
    check(f"the report holds `{old[:30]}` to edit", old in text)
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")


def refusal_lines(err):
    return [ln for ln in err.splitlines() if ln.startswith("  - ")]


def every_refusal_names_its_door(label, err):
    lines = refusal_lines(err)
    check(f"{label}: there is at least one refusal line", bool(lines), err[:300])
    check(f"{label}: every line names a door it can use (the rebuild or the scribe's rework)",
          all("report_facts.py --task" in ln or "story_step.py start --task" in ln for ln in lines), "\n".join(lines))
    check_in(f"{label}: the rebuild is named", "`report_facts.py --task T-1 --write`", err)
    check_in(f"{label}: the scribe's rework is named", "`story_step.py start --task T-1 --stage S8 --role qa-doc-scribe`", err)
    check_in(f"{label}: the person's word is named, by stage and block",
             "waiver.py --task T-1 --stage S9 --block \"report check\" --decision", err)
    check_in(f"{label}: it is not put to the person", "do not put it to the person as a question", err)


def s9_with_no_report_goes_to_the_scribe():
    task = TR.story()
    root = task.parents[2]
    try:
        journal = root / "qa-factory" / "records" / "journal.jsonl"
        for status in ("done", "skipped"):
            code, out, err = run_s9("T-1", status, "qa-retro-analyst", False)
            check_eq(f"[{status}] no test-report.md: S9 is refused", code, stage_done.EXIT_BAD_ARGS)
            check_in(f"[{status}] what is wrong", "does not exist", err)
            check_in(f"[{status}] the door is S8's scribe", "S8's scribe writes it", err)
            every_refusal_names_its_door(f"[{status}] no report", err)
            check_eq(f"[{status}] a refused report never reaches the journal", journal.exists(), False)
            check_eq(f"[{status}] and S9 is not recorded", "S9" in (pipeline_at(task).get("stages") or {}), False)
        # the positional invariant: a running tail is refused FIRST, for the tail
        pipeline = pipeline_at(task)
        pipeline["stages"] = {"S3": {"status": "running", "role": "qa-test-strategist"}}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("a running tail and no report: refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("for the tail, first", "S3 is still running", err)
        check_not_in("and the report is not the question yet", "report check", err)
        pipeline["stage_overrides"] = [{"stage": "S9", "match": "still running", "decision": "it is merged"}]
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("the tail passed by the person's word: the report is refused next", code, stage_done.EXIT_BAD_ARGS)
        check_in("with the report's own refusal", "does not exist", err)
    finally:
        cleanup(root)


def s9_passes_a_report_that_checks_clean():
    task = marked_story()
    root = task.parents[2]
    try:
        journal = root / "qa-factory" / "records" / "journal.jsonl"
        code, out, err = run_s9("T-1", "done", "qa-retro-analyst", False)
        check_eq("a report that matches the facts: S9 closes", code, 0)
        check_eq("and S9 is recorded", pipeline_at(task)["stages"]["S9"]["status"], "done")
        check_eq("the journal is written (the control of the refusals' 'no journal')", journal.is_file(), True)
        check_not_in("nothing was refused", "report check", err)
    finally:
        cleanup(root)


def s9_passes_a_legacy_report_and_says_so():
    task = TR.story()
    root = task.parents[2]
    try:
        for label, write_report in (("older-contract", lambda: (task / "test-report.md").write_text(
                                        "# report\n\n## Check coverage\n\nold\n", encoding="utf-8")),
                                    ("unmarked", lambda: TR.legacy_report(task))):
            write_report()
            for status in ("done", "skipped"):
                (task / "pipeline.json").write_text(json.dumps(pipeline_at(task) | {"stages": {}}), encoding="utf-8")
                code, out, err = run_s9("T-1", status)
                check_eq(f"[{label}/{status}] a legacy report is not refused", code, 0)
                check_in(f"[{label}/{status}] and the pass says why", G.LEGACY_FACTS_LINE, out)
                check_eq(f"[{label}/{status}] the line is the grammar's own", G.LEGACY_FACTS_LINE,
                         "legacy report: facts not checked")
    finally:
        cleanup(root)


def s9_refuses_what_the_rebuild_cannot_settle():
    # (a) damaged markers
    task = marked_story()
    root = task.parents[2]
    try:
        edit_report(task, "<!-- /facts:size -->\n", "")
        for status in ("done", "skipped"):
            code, out, err = run_s9("T-1", status)
            check_eq(f"[markers/{status}] damaged markers refuse S9", code, stage_done.EXIT_BAD_ARGS)
            check_in(f"[markers/{status}] naming the expected marker", "<!-- /facts:size -->", err)
            every_refusal_names_its_door(f"[markers/{status}]", err)
        check_eq("a refused S9 is not recorded", "S9" in (pipeline_at(task).get("stages") or {}), False)
        # the person's word passes it, and the pass is filed as a factory finding (FR-4)
        pipeline = pipeline_at(task)
        pipeline["stage_overrides"] = [{"stage": "S9", "match": "still running", "decision": "a different block"}]
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("a word about ANOTHER block does not pass it", code, stage_done.EXIT_BAD_ARGS)
        pipeline["stage_overrides"] = [{"stage": "S9", "match": "report check", "decision": "close it, I read the report"}]
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("the person's recorded word passes the refusal", code, 0)
        check_in("and the pass is printed, with whose word it was", "on the person's word: close it, I read the report", err)
        filed = pipeline_at(task).get("warnings") or []
        check("and filed as a factory finding in their words",
              any("passed by the person's word" in w and "close it, I read the report" in w for w in filed), str(filed))
    finally:
        cleanup(root)

    # (b) gate B has words, the report has no gate B block
    task = marked_story()
    root = task.parents[2]
    try:
        pipeline = pipeline_at(task)
        pipeline["gates"]["B"] = {"authorization_source": TR.GATE_B}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("[gate B] words without the block refuse S9", code, stage_done.EXIT_BAD_ARGS)
        check_in("[gate B] what is wrong", "gate B has recorded words but the report has no `gate-b` block", err)
        every_refusal_names_its_door("[gate B]", err)
        RF.write(task)
        code, out, err = run_s9("T-1")
        check_eq("[gate B] after the rebuild S9 closes", code, 0)
    finally:
        cleanup(root)

    # (c) a "Not proven" item missing a part, at the boundary and beyond it
    for label, item, refused in (("empty right side", "- **R-2** — cause :", True),
                                 ("no separator", "- **R-2** — nobody waited", True),
                                 ("no cause", "- **R-2** : risk", True),
                                 ("whole item", "- **R-2** — cause : risk", False)):
        task = marked_story()
        root = task.parents[2]
        try:
            path = task / "test-report.md"
            text = path.read_text(encoding="utf-8")
            broken = re.sub(r"\n- \*\*R-2\*\* .*", "\n" + item, text, count=1)
            check(f"[not proven: {label}] the item was found", broken != text)
            path.write_text(broken, encoding="utf-8", newline="")
            code, out, err = run_s9("T-1")
            if refused:
                check_eq(f"[not proven: {label}] refused", code, stage_done.EXIT_BAD_ARGS)
                check_in(f"[not proven: {label}] naming the missing part", "lacks its requirement, its cause or its risk", err)
                every_refusal_names_its_door(f"[not proven: {label}]", err)
            else:
                check_eq(f"[not proven: {label}] `R-n — cause : risk` passes the form check", code, 0)
                check_not_in(f"[not proven: {label}] nothing refused", "lacks its requirement", err)
                check_in(f"[not proven: {label}] its block is stale (the hand edit): rebuilt now and said, not refused",
                         "report: block `not-proven` was stale; rebuilt now by `report_facts.py --task T-1 --write`", out)
        finally:
            cleanup(root)

    # (d) a "Left with you" item that is only the factory's own bookkeeping
    root = TR.temp_project("qa-s9-lift-")
    task = root / "qa-factory" / "artifacts" / "T-2"
    work = task / "work"
    try:
        TR.write(task / "test-plan.md", TR.LIFT_PLAN)
        TR.write(work / "test-cases" / "lift" / "TC-101.md", TR.lift_case("TC-101", "R-101", "TS-101"))
        TR.write(work / "test-cases" / "lift" / "TC-102.md", TR.lift_case("TC-102", "R-102", "TS-102"))
        TR.write(work / "run-report.json", TR.LIFT_RUN)
        TR.write(work / "automation-manifest.json", {"tests": [], "unresolved": []})
        TR.write(work / "requirements-register.md", TR.REGISTER.replace("R-1 ", "R-101 ").replace("R-2 ", "R-102 "))
        TR.write(task / "pipeline.json", {"ticket": "T-2", "gates": {}})
        # t-305 N8 (F10, FR-57): an item is taken out / refused as bookkeeping only when the ledger SAYS its case is closed;
        # with no ledger row for the case it stays owed (the error is toward keeping), so this story has a ledger that closes TC-101
        TR.write(work / "ledger.json", {"ticket": "T-2", "delivery_ready": True, "delivery_verdict": "yes", "reasons": [],
                                        "reason_records": [], "left_items": [],
                                        "rows": [{"ref": "TS-101", "kind": "plan_row", "state": "passed_green", "detail": "TC-101"}]})
        TR.use_project(root)
        body = "\n".join(["# T-2 — test report", "", "## Left with you", "", TR.FACTORY_ITEM, TR.PRODUCT_ITEM, ""])
        TR.write(task / "test-report.md", "<!-- facts:size -->\n## Size\n\nx\n<!-- /facts:size -->\n\n" + body)
        code, out, err = run_s9("T-2")
        check_eq("[left with you] an item that is only the factory's bookkeeping refuses S9", code, stage_done.EXIT_BAD_ARGS)
        check_in("[left with you] naming the item", "The first (R-101, TC-101)", err)
        check_in("[left with you] and why", "only the factory's own bookkeeping as its refs", err)
        check_in("[left with you] the door is the rebuild, which takes it out", "run `report_facts.py --task T-2 --write`", err)
        check_in("[left with you] and the person's word", "waiver.py --task T-2 --stage S9 --block \"report check\"", err)
    finally:
        cleanup(root)


def s9_rebuilds_a_stale_block_and_goes_on():
    """t-202 F4: the skill road has no driver to run the rebuild, so a stale block, and nothing else, is
    rebuilt BY the S9 exit - once - and S9 closes. The exit writes the report (and its history) and nothing
    else: `pipeline.json` is not an input of the write."""
    task = marked_story()
    root = task.parents[2]
    real_write = RF.write
    calls: list = []

    def counting_write(*a, **k):
        calls.append(a)
        return real_write(*a, **k)
    try:
        # the size is recorded already, so the exit's own size step writes nothing into pipeline.json
        pipeline = pipeline_at(task) | {"size": "M", "size_initial": "M", "size_final": "M"}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        report = task / "test-report.md"
        fresh = report.read_bytes()
        edit_report(task, "Open questions — 2", "Open questions — 9")
        found = RF.check(task)
        stale = [ln for ln in found if stage_done.STALE_MARK in ln]
        check_eq("the marker is the one report_facts.check prints for a really stale block", len(stale), 1)
        named = stage_done.STALE_NAME_RE.search(stale[0]) if stale else None
        check_eq("and the block name is read from it", named.group(1) if named else "", "open-questions")
        # t-2113: the loop below runs S9 on a pipeline with no stages, and the `regression` block reads the stages now, so the fresh
        # render to compare with is the one made on THAT pipeline (before, the two renders were the same bytes)
        (task / "pipeline.json").write_text(json.dumps(pipeline_at(task) | {"stages": {}}), encoding="utf-8")
        real_write(task)
        fresh = report.read_bytes()
        edit_report(task, "Open questions — 2", "Open questions — 9")
        RF.write = counting_write
        for status in ("done", "skipped"):
            if status == "skipped":
                edit_report(task, "Open questions — 2", "Open questions — 9")
            pipeline = pipeline_at(task) | {"stages": {}}
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            del calls[:]
            code, out, err = run_s9("T-1", status)
            check_eq(f"[{status}] a stale block alone is not a refusal", code, 0)
            check_eq(f"[{status}] the exit ran the rebuild once", len(calls), 1)
            check_in(f"[{status}] one line says which block was rebuilt, and how",
                     "report: block `open-questions` was stale; rebuilt now by `report_facts.py --task T-1 --write`", out)
            check_eq(f"[{status}] and it is exactly one such line", out.count("was stale; rebuilt now"), 1)
            check_not_in(f"[{status}] nothing refused", "report check", err)
            check_eq(f"[{status}] the report is the fresh render again, byte for byte", report.read_bytes(), fresh)
            check_eq(f"[{status}] and checks clean", RF.check(task), [])
            check_eq(f"[{status}] S9 is recorded", (pipeline_at(task)["stages"].get("S9") or {}).get("status"),
                     "done" if status == "done" else "skipped")
            after = pipeline_at(task)
            own = ("stages", "closed_at", "closed_by", "warnings", "halts")   # what any S9 record stamps
            check_eq(f"[{status}] pipeline.json is untouched but for S9's own record",
                     {k: v for k, v in after.items() if k not in own},
                     {k: v for k, v in pipeline.items() if k not in own})
            check_eq(f"[{status}] and the rebuild filed no finding", (after.get("warnings") or [], after.get("halts") or []), ([], []))
            check_eq(f"[{status}] the stages hold S9 and nothing else new", sorted(after["stages"]), ["S9"])
        check("the old bytes are in report-history (nothing is deleted)",
              any((task / "state" / "report-history").iterdir()))
        # control: a report that checks clean is not written at all (the exit rebuilds only a stale block)
        del calls[:]
        before = report.read_bytes()
        code, out, err = run_s9("T-1")
        check_eq("control: a clean report: the rebuild does not run", (code, len(calls), report.read_bytes() == before), (0, 0, True))
        check_not_in("control: and nothing is said about a rebuild", "rebuilt now", out)
        # a stale block beside a refusal the rebuild cannot settle: only the refusal stops, nothing is
        # written, and the stale block is still said with why it was left
        edit_report(task, "Open questions — 2", "Open questions — 9")
        text = report.read_text(encoding="utf-8")
        broken = re.sub(r"\n- \*\*R-2\*\* .*", "\n- **R-2** — nobody waited", text, count=1)
        check("the Not proven item was found", broken != text)
        report.write_text(broken, encoding="utf-8", newline="")
        del calls[:]
        held = report.read_bytes()
        code, out, err = run_s9("T-1")
        check_eq("a stale block and an item with a missing part: refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("for the item", "lacks its requirement, its cause or its risk", err)
        check_not_in("not for the stale block", "differs from a fresh render", err)
        check_eq("and the exit wrote nothing", (len(calls), report.read_bytes() == held), (0, True))
        check_in("the stale block is still said, with why it was left",
                 "report: block `open-questions` is stale; it was not rebuilt", out)
        # a stale block beside damaged markers: the check names the markers only; nothing is written either
        edit_report(task, "<!-- /facts:size -->\n", "")
        del calls[:]
        damaged = report.read_bytes()
        code, out, err = run_s9("T-1")
        check_eq("a stale block and damaged markers: refused", code, stage_done.EXIT_BAD_ARGS)
        check_eq("and the exit wrote nothing", (len(calls), report.read_bytes() == damaged), (0, True))
    finally:
        RF.write = real_write
        cleanup(root)


def s9_goes_on_when_the_rebuild_cannot_run():
    """F4: a write that refuses or raises is the stale note plus the write's own line, and S9 closes."""
    real_write = RF.write
    try:
        for label, behave, said in (
                ("refused", lambda *a, **k: {"ok": False, "lines": ["test-report.md: refused for the test", "door: the scribe"], "history": ""},
                 ["report: block `open-questions` is stale; the rebuild could not run:", "test-report.md: refused for the test", "door: the scribe"]),
                ("raising", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
                 ["report: block `open-questions` is stale; the rebuild could not run: RuntimeError: boom"])):
            task = marked_story()
            root = task.parents[2]
            try:
                edit_report(task, "Open questions — 2", "Open questions — 9")
                stale_bytes = (task / "test-report.md").read_bytes()
                RF.write = behave
                code, out, err = run_s9("T-1")
                check_eq(f"[{label}] a stale block is never a refusal: S9 closes", code, 0)
                for line in said:
                    check_in(f"[{label}] the exit says: {line[:50]}", line, out)
                if label == "raising":
                    check_in(f"[{label}] and names the door by hand", "report_facts.py --task T-1 --write", out)
                check_not_in(f"[{label}] nothing refused", "report check", err)
                check_eq(f"[{label}] S9 is recorded", (pipeline_at(task).get("stages") or {}).get("S9", {}).get("status"), "done")
                check_eq(f"[{label}] the report is as it was (the write did nothing)", (task / "test-report.md").read_bytes(), stale_bytes)
            finally:
                RF.write = real_write
                cleanup(root)
    finally:
        RF.write = real_write


def s9_never_refuses_for_its_own_crash():
    task = marked_story()
    root = task.parents[2]
    real = RF.check
    try:
        def boom(*_a, **_k):
            raise RuntimeError("boom")
        RF.check = boom
        code, out, err = run_s9("T-1")
        check_eq("an exception inside the check does not refuse S9", code, 0)
        check_in("it is said out loud", "report check could not run: RuntimeError: boom", out)
        check_eq("and S9 is recorded", ((pipeline_at(task).get("stages") or {}).get("S9") or {}).get("status"), "done")
        filed = pipeline_at(task).get("warnings") or []
        check("and filed as a factory finding through the warn mechanism",
              any("S9 report check could not run: RuntimeError: boom" in w for w in filed), str(filed))
        check_in("the filing is printed", "warnings[] +=", out)
    finally:
        RF.check = real
        cleanup(root)


# --- the size at the S9 exit (R-210.3) ---------------------------------------------------------

def s9_records_the_size_the_story_never_got():
    task = marked_story()
    root = task.parents[2]
    try:
        pipeline = pipeline_at(task)
        check_eq("the fixture story holds no size", pipeline.get("size"), None)
        code, out, err = run_s9("T-1")
        check_eq("S9 closes", code, 0)
        after = pipeline_at(task)
        check_eq("the size of work/sizing.json is recorded", after.get("size"), "M")
        check_eq("with both ends of it", (after.get("size_initial"), after.get("size_final")), ("M", "M"))
        check_in("and the same `pipeline.json:` line apply_facts prints is printed", 'pipeline.json: size = "M"; size_initial', out)
        # a size already there is never overwritten
        after["size"], after["size_initial"], after["size_final"], after["stages"] = "XL", "XL", "XL", {}
        (task / "pipeline.json").write_text(json.dumps(after), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("a recorded size is left as it is", pipeline_at(task).get("size"), "XL")
        check_not_in("and nothing is printed about it", "size not recorded", out)
        # no sizing.json: nothing written, one line
        (task / "work" / "sizing.json").unlink()
        after["size"], after["size_initial"], after["size_final"], after["stages"] = None, None, None, {}
        (task / "pipeline.json").write_text(json.dumps(after), encoding="utf-8")
        code, out, err = run_s9("T-1")
        check_eq("no sizing.json: S9 still closes", code, 0)
        check_eq("nothing is written", pipeline_at(task).get("size"), None)
        check_eq("and the one line is printed", out.count("size not recorded: no work/sizing.json"), 1)
    finally:
        cleanup(root)


# --- the S3 exit reports the plan's question branches (open questions, R1 / R7) ---------------------

def s3_exit_reports_question_branches_and_never_refuses():
    """`stage_done --stage S3 --status done` runs `planning_contract.variant_errors` over the plan and PRINTS
    what the strategist can repair. It never refuses (the S4 rehearsal does, as today: a second stop on one
    fact is a duplicate, FR-7), it writes into the story only the derived package of its findings (SC1-1), and a story with
    no branch field says nothing (E-9)."""
    project = temp_project("qa-s3-branches-")
    saved_kinds = None
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "T-3"
        work = task / "work"
        work.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "T-3", "stages": {}, "gates": {}}), encoding="utf-8")
        register = {"open_questions": [{"id": "Q1", "question": "Which reading?",
                                        "readings": [{"reading": "one"}, {"reading": "two"}]}]}
        (work / "requirements-readiness.json").write_text(json.dumps(register), encoding="utf-8")
        plan = work / "test-plan.json"
        counter = [0]

        def close_s3(status="done"):
            counter[0] += 1
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = stage_done.run("T-3", "S3", status, "qa-test-strategist", f"plan v{counter[0]}", True)
            return code, out.getvalue(), err.getvalue()

        def s3_lines(out):
            # BOTH heads: the old `S3: ` (the "not checked" lines keep it) and the remark head. A filter that knew only the old
            # head made the keys (c), (d) and (g) pass whatever the new head printed (M9).
            return [ln for ln in out.splitlines() if ln.startswith(("S3: ", stage_done.S3_REMARK_PREFIX))]

        def package_text(out):
            """The text of the package the remark line names (project-relative), or ''."""
            found = re.search(r"(qa-factory/artifacts/T-3/state/findings/s3-remarks-[0-9a-f]{12}\.md)", out)
            return (project / found.group(1)).read_text(encoding="utf-8") if found else ""

        # (a0) RN1-2 (t-693 verdict, t-717 fix: "every strategist branch kind in `S3_EXIT_KINDS` is REFUSED at the S3 exit by
        # `planning_contract.detector_main`, not reported here"): an unresolved ref is now the DETECTOR's refusal, so the remark
        # round prints nothing for it. Every kind that is left (`missing_reading_text`, `case_unreadable`, `row_owes_case`) is
        # the designer's and cannot arise at S3, where no case exists. The SC1-1 remark mechanism (head, package, door) is
        # still the code the not-checked lines and any future remark kind run through, so (a)-(g) below keep pinning it with
        # the two kind tuples emptied for the scenario (restored in `finally`) - a pin of the mechanism, not of a live kind.
        plan.write_text(json.dumps([{"id": "TS-1", "question_refs": ["Q9"]}]), encoding="utf-8")
        code, out, err = close_s3()
        check_eq("S3 exit (RN1-2): an unresolved ref is the detector's refusal, not a remark - the remark round prints nothing",
                 (code, s3_lines(out)), (0, []))
        saved_kinds = (planning_contract.S3_EXIT_KINDS, planning_contract.S3_WARN_KINDS)
        planning_contract.S3_EXIT_KINDS = planning_contract.S3_WARN_KINDS = ()
        # (a) a ref that resolves nowhere: one line, the strategist's door, and the stage still closes
        plan.write_text(json.dumps([{"id": "TS-1", "question_refs": ["Q9"]}]), encoding="utf-8")
        before = plan.read_bytes()
        code, out, err = close_s3()
        check_eq("S3 exit: a branch problem is NOT a refusal - the stage closes", code, 0)
        check_eq("...and it is recorded", ((pipeline_at(task).get("stages") or {}).get("S3") or {}).get("status"), "done")
        lines = s3_lines(out)
        check_eq("S3 exit: exactly one line is printed", len(lines), 1)
        check_in("S3 exit: it counts the findings and says whose they are (the remark head, SC1-1)",
                 "S3 remarks: 1 question-branch finding(s) the strategist can repair on TS-1", lines[0] if lines else "")
        check_in("S3 exit: it names the row and the ref - in the package the line names, whole",
                 "- TS-1: `Q9` is not a question id of the register", package_text(out))
        check_in("S3 exit: and the strategist's door, on that row",
                 "--operation rework --stage S3 --role qa-test-strategist --rows TS-1 --reason", out)
        check_not_in("S3 exit: nothing on stderr about it (it is no refusal)", "question-branch", err)
        check_eq("S3 exit: the plan is not touched", plan.read_bytes(), before)
        # E11: the validator writes into the plan and the register nothing; its one new file is the derived package
        shutil.rmtree(task / "state" / "findings")
        files_before = {p for p in task.rglob("*") if p.is_file()}
        stage_done.s3_branch_line(task)
        check_eq("S3 exit: the only file it writes is the package, state/findings/s3-remarks-*.md (E11)",
                 sorted(p.relative_to(task).as_posix()[:len("state/findings/s3-remarks-")]
                        for p in {p for p in task.rglob("*") if p.is_file()} - files_before),
                 ["state/findings/s3-remarks-"])
        # (b) two problems, two rows: the count is the number of findings
        plan.write_text(json.dumps([{"id": "TS-1", "question_refs": ["Q9"]}, {"id": "TS-2", "question_refs": ["Q8"]}]),
                        encoding="utf-8")
        code, out, err = close_s3()
        check_in("S3 exit: two findings are counted as two", "S3 remarks: 2 question-branch finding(s)", out)
        check_in("S3 exit: and both rows are in the door, a comma list a shell passes as one argument", "--rows TS-1,TS-2 --reason", out)
        check_not_in("S3 exit: the old spelled-out door is gone", "--rows TS-1, TS-2", out)
        check_in("S3 exit: both findings are in the package", "- TS-2: `Q8` is not a question id of the register", package_text(out))
        # (c) the same branch, resolved: nothing is printed
        # (the row has no `if_answered`: a `missing_branch` finding, which the REAL kinds leave to the detector - so the real tuples
        # are back for this one check, and the emptied ones after it)
        planning_contract.S3_EXIT_KINDS, planning_contract.S3_WARN_KINDS = saved_kinds
        plan.write_text(json.dumps([{"id": "TS-1", "question_refs": ["Q1"]}]), encoding="utf-8")
        code, out, err = close_s3()
        check_eq("S3 exit: a plan whose branches hold prints nothing", (code, s3_lines(out)), (0, []))
        planning_contract.S3_EXIT_KINDS = planning_contract.S3_WARN_KINDS = ()
        # (d) E-9: a story with no question_refs anywhere says nothing - even with no register file at all
        plan.write_text(json.dumps([{"id": "TS-1", "level": "api", "disposition": "automate"}]), encoding="utf-8")
        (work / "requirements-readiness.json").unlink()
        code, out, err = close_s3()
        check_eq("S3 exit: a story from before the contract (no branch field) prints nothing, register or not",
                 (code, s3_lines(out)), (0, []))
        # (e) branches but no register: one line, no exception
        plan.write_text(json.dumps([{"id": "TS-1", "question_refs": ["Q1"]}]), encoding="utf-8")
        code, out, err = close_s3()
        check_eq("S3 exit: branches and no register: one line", (code, len(s3_lines(out))), (0, 1))
        check_in("S3 exit: it says the register could not be read",
                 "S3 remarks: question branches not checked: the register's questions could not be read", out)
        # (f) no plan at all, and a plan that is not JSON: one line each, the stage closes
        plan.unlink()
        code, out, err = close_s3()
        check_eq("S3 exit: no plan: one line, no exception", (code, len(s3_lines(out))), (0, 1))
        check_in("S3 exit: it names the file", "the story has no work/test-plan.json", out)
        # (run() itself is not used for a plan that is not JSON: the dashboard refresh that follows the stage
        # commit raises on it in coverage_contract.plan_rows, which is not this block - the line is read directly)
        plan.write_text("{not json", encoding="utf-8")
        said = stage_done.s3_branch_line(task)
        check_eq("S3 exit: a plan that is not JSON: one line, no exception", said.count("\n"), 0)
        check_in("S3 exit: it names the failure", "S3 remarks: question branches not checked (JSONDecodeError", said)
        plan.write_bytes(b"\xff\xfe\x00broken")
        check_in("S3 exit: bytes that are no text at all: still one line", "S3 remarks: question branches not checked (",
                 stage_done.s3_branch_line(task))
        plan.write_text("[]", encoding="utf-8")
        code, out, err = close_s3()
        check_eq("S3 exit: an empty plan says nothing", (code, s3_lines(out)), (0, []))
        # (g) only the S3 exit: a running S3, and the same plan at S2, print nothing
        plan.write_text(json.dumps([{"id": "TS-1", "question_refs": ["Q9"]}]), encoding="utf-8")
        code, out, err = close_s3("running")
        check_eq("S3 running: nothing is checked", s3_lines(out), [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            stage_done.run("T-3", "S2", "done", "qa-requirements-tester", "understanding", True)
        check_eq("S2 done: nothing is checked", s3_lines(out.getvalue()), [])
    finally:
        if saved_kinds:
            planning_contract.S3_EXIT_KINDS, planning_contract.S3_WARN_KINDS = saved_kinds
        cleanup(project)


# --- the 2534 reproduction ---------------------------------------------------------------

def recover_settles_the_tail_of_a_closed_story():
    root = temp_dir("qa-2534-tail-")
    try:
        controller = closed_story(root)
        # The tail itself: a stray dispatch of a stage the story had already accepted, and
        # the `running` that every reader of the file saw for two days beside it.
        # (C1-6a: `dispatch` now REFUSES this on a closed story, so the tail is written the way 2534 got it - past the
        # validator, straight into the journal.)
        stray(controller, GHOST)
        pipeline = pipeline_of(root)
        pipeline["stages"]["S3"]["status"] = "running"
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check("the shape 2534 was found in: a finished story with a running stage",
              stage_guard._has_running_stage(root / "pipeline.json"))
        check_eq("and a controller waiting on a job nobody was doing",
                 Controller(root).next_action()["action"], "wait_existing_job")

        result = Controller(root).recover()
        fixes = [f for f in result["journalled_repairs"] if f["kind"] == STALE_AFTER_CLOSURE]
        check_eq("recover journals the tail as a repair, not as nothing", len(fixes), 1)
        check_eq("naming the dispatch it settled", fixes[0]["dispatch_id"], GHOST)
        check_eq("and the closure that makes it stale",
                 fixes[0]["closed_at"], pipeline_of(root)["closed_at"])
        check_in("and why, in the reason a person reads",
                 "after the story closed", fixes[0]["reason"])
        state = Controller(root).state()
        check_eq("the dispatch stops being work anybody waits for",
                 state["dispatches"][GHOST]["status"], "superseded")
        check_eq("the accepted stage keeps its decision", state["stages"]["S3"]["status"],
                 "completed")
        check("no stage is running any more — the guard's fallback is unambiguous again",
              not stage_guard._has_running_stage(root / "pipeline.json"))
        check_eq("and the story says what it is", result["next_action"]["action"], "closed")

        again = Controller(root).recover()
        check_eq("recover is idempotent: a settled tail is not settled twice",
                 [f for f in again["journalled_repairs"] if f["kind"] == STALE_AFTER_CLOSURE], [])
        check_eq("and the answer does not drift", again["next_action"]["action"], "closed")
    finally:
        cleanup(root)


# --- going back to a closed story --------------------------------------------------------

def reopening_is_a_persons_word():
    root = temp_dir("qa-2534-reopen-")
    try:
        controller = closed_story(root)
        try:
            controller.build_rework_request("S3", "qa-worker", [], "")
            refusal = ""
        except ValueError as exc:
            refusal = str(exc)
        check_in("rework of a closed story without words is refused", "--reason", refusal)
        check_in("and the refusal says what the words are for", "REOPENS", refusal)

        request = controller.build_rework_request("S3", "qa-worker", [],
                                                  "the plan missed the retry path")
        check("the request carries the reopening", bool(request.get("reopened_at")))
        controller.apply("dispatch", dict(request))
        pipeline = pipeline_of(root)
        check_eq("pipeline.json records the person's own words",
                 pipeline.get("reopened_by_words"), "the plan missed the retry path")
        check("beside the time they reopened it", bool(pipeline.get("reopened_at")))
        check_eq("the closure it already had is not rewritten",
                 pipeline.get("closed_by"), "gate B + S8 done")
        check("a reopened story is open again for every reader",
              not story_closed(pipeline))
        check_eq("so recover has no tail to settle on it",
                 Controller(root).closure_repairs(), [])
    finally:
        cleanup(root)


def a_release_on_a_closed_story_is_recorded_too():
    """The other operation that carries a person's words, and the same rule under it."""
    root = temp_dir("qa-2534-release-")
    try:
        controller = closed_story(root)
        stray(controller, GHOST)
        released = controller.release_dispatch(GHOST, "nobody is doing this, drop it")
        check_eq("a release on a closed story records the reopening the same way",
                 pipeline_of(root).get("reopened_by_words"), "nobody is doing this, drop it")
        check("and the release itself still does what it always did",
              released["released"] and released["status"] == "released_by_person")
        check("the story is open again, so nothing settles its stages behind the person",
              not story_closed(pipeline_of(root)))
    finally:
        cleanup(root)


# --- B-331 (C1-6a, t-1151): work that never started on a closed story -----------------------

WORDS = "run the runner again, please - the hook refused it"


def a_dispatch_on_a_closed_story_needs_a_persons_word():
    """M1 (d) as code on every road: the skill path can dispatch a packet by hand, so the dispatch check refuses work on a
    closed story. Error direction: starting work on a closed story is the forbidden error; the retro and a person's
    reopening (the stamp AND the words, making the story open by the one reading) pass."""
    root = temp_dir("qa-c16a-dispatch-")
    try:
        controller = closed_story(root)
        bare = refused(lambda: controller.apply("dispatch", dict(packet("S3-x-0"), idempotency_key="k0")))
        check("with no work held back, the refusal does not name reopen_story (it would be refused: nothing is held)",
              bare is not None and "reopen_story" not in bare[1] and "--operation rework" in bare[1], bare)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="S6-qa-runner-1")
        revision = controller.state()["revision"]
        plain = refused(lambda: controller.apply("dispatch", dict(packet("S3-x-1"), idempotency_key="k1")))
        check_eq("a plain dispatch on a closed story is refused (StateConflict)", plain and plain[0], "StateConflict")
        check_in("and, with work held back, the refusal names the door for work that never started", "reopen_story", plain[1])
        check_in("and the door for new work", "--operation rework", plain[1])
        check_eq("nothing was written", controller.state()["revision"], revision)
        early = refused(lambda: controller.apply("dispatch", dict(packet("S3-x-2"), idempotency_key="k2",
                                                                  reopened_at="2000-01-01T00:00:00+00:00",
                                                                  reopen_words="the plan missed it")))
        check("a stamp EARLIER than closed_at opens nothing: refused (the dispatch would land with the story still closed)",
              early is not None, early)
        wordless = refused(lambda: controller.apply("dispatch", dict(packet("S3-x-3"), idempotency_key="k3",
                                                                     reopened_at="2099-01-01T00:00:00+00:00")))
        check("a stamp with NO words is no person's word: refused", wordless is not None, wordless)
        check_eq("still nothing written", controller.state()["revision"], revision)
        retro = refused(lambda: controller.apply("dispatch", dict(packet("S9-x-1", stage="S9", role="qa-retro"),
                                                                  idempotency_key="k4")))
        check("the retro (S9) needs no word: it passes the closure test", retro is None, retro)
    finally:
        cleanup(root)


def reopen_story_starts_only_what_the_word_covered():
    root = temp_dir("qa-c16a-reopen-")
    try:
        controller = closed_story(root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="S6-qa-runner-1")
        never_started(controller, "S5-qa-automator-9", stage="S5", role="qa-automator", rework_of="S5-qa-automator-1")
        nxt = controller.next_action()
        check_eq("a closed story with two never-started reworks: `closed`, both held, nothing relaunched",
                 (nxt["action"], [h["dispatch_id"] for h in nxt["held"]]),
                 ("closed", ["S6-qa-runner-9", "S5-qa-automator-9"]))
        revision = controller.state()["revision"]
        for label, ids, words in (("empty words", "S6-qa-runner-9", "  "), ("an unknown id", "S6-nope-1", WORDS),
                                  ("no id", "", WORDS), ("a dispatch the story does not hold back (accepted)", "dS5", WORDS)):
            bad = refused(lambda: controller.reopen_story(ids, words))
            check(f"reopen_story refuses {label}", bad is not None, bad)
        check_eq("and wrote nothing", controller.state()["revision"], revision)
        got = controller.reopen_story("S6-qa-runner-9", WORDS)
        check("reopen_story on the one dispatch the word covers", got["reopened"] and got["left_held"] == ["S5-qa-automator-9"], got)
        pipeline = pipeline_of(root)
        check_eq("the reopening is stamped through the one writer: the person's words beside reopened_at",
                 pipeline.get("reopened_by_words"), WORDS)
        check("and the story is open again for every reader", not story_closed(pipeline))
        after = controller.next_action()
        check_eq("`next` relaunches the covered dispatch, with its packet", (after["action"], after.get("closed_dispatch_id")),
                 ("relaunch", "S6-qa-runner-9"))
        again = controller.reopen_story("S6-qa-runner-9", WORDS)
        check("the same word twice records nothing twice (a retry after a transport doubt)", again.get("already_recorded"), again)
        left = refused(lambda: controller.apply("dispatch", dict(packet("S5-qa-automator-10", stage="S5", role="qa-automator",
                                                                         relaunch_of="S5-qa-automator-9"),
                                                                  idempotency_key="k-left")))
        check("the held dispatch the word did NOT name is not relaunched, by any road (a word covers only what it named)",
              left is not None and "left out" in left[1], left)
        check("B1: and the refusal names the doors that OPEN for it (`reopen_story`, `leave_unlaunched`), not one that never does",
              left is not None and "--operation reopen_story --dispatch S5-qa-automator-9 --words-file" in left[1]
              and "--operation leave_unlaunched --dispatch S5-qa-automator-9 --words-file" in left[1]
              and "closed again" not in left[1], left)
        controller.apply("dispatch", dict(after["dispatch_request"]))
        check_eq("the covered packet lands (the story is open by the person's word) and the role runs",
                 controller.state()["dispatches"][after["dispatch_request"]["id"]]["status"], "running")
    finally:
        cleanup(root)


def accept_dispatch(controller, root, identifier):
    """The work a person's word started is done: the dispatch that landed is accepted, its stage complete."""
    evidence = root / f"{identifier}.txt"
    evidence.write_text(identifier, encoding="utf-8")
    controller.apply("accept", {"id": identifier, "status": "accepted", "stage_complete": True,
                                "evidence_refs": [{"path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                                "idempotency_key": "accept-" + identifier})


def a_partial_reopen_keeps_a_door_for_the_work_it_left():
    """B1 (critic t-1182): `closed.held` is the list of dispatches never started while the story is closed, and it shrinks ONLY
    through `reopen_story` or `leave_unlaunched` (AR-20). A PARTIAL reopen opens the story for the named dispatches; the ones
    it did not name stay `held` on the open story, both doors accept them, and `next` asks about them again when the covered
    work is done - it does not answer `prepare_stage S9`. Before, the story closed once: nothing asked again, both ops refused
    'story not closed', and the relaunch refusal named a door that never opens (FR-2, FR-57)."""
    root = temp_dir("qa-c16a-partial-")
    try:
        controller = closed_story(root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="dS6")
        never_started(controller, "S5-qa-automator-9", stage="S5", role="qa-automator", rework_of="dS5")
        revision = controller.state()["revision"]
        # a reopen naming nothing / a dispatch that is not held: refused, and the refusal names what IS held
        for label, ids in (("no id", ""), ("a dispatch that is not held (accepted)", "dS3")):
            bad = refused(lambda: controller.reopen_story(ids, WORDS))
            check(f"reopen_story refuses {label}, naming the held ids",
                  bad is not None and "S5-qa-automator-9" in bad[1] and "S6-qa-runner-9" in bad[1], bad)
        check_eq("and wrote nothing", controller.state()["revision"], revision)
        got = controller.reopen_story("S6-qa-runner-9", WORDS)
        check_eq("the partial reopen records what it left out", got["left_held"], ["S5-qa-automator-9"])
        after = controller.next_action()
        check_eq("the covered work is relaunched first", (after["action"], after.get("closed_dispatch_id")),
                 ("relaunch", "S6-qa-runner-9"))
        check("... and the story is open for every reader while the left-out work stays held",
              not story_closed(pipeline_of(root)) and [d["id"] for d in controller.held_work()] == ["S5-qa-automator-9"],
              [d["id"] for d in controller.held_work()])
        controller.apply("dispatch", dict(after["dispatch_request"]))
        accept_dispatch(controller, root, after["dispatch_request"]["id"])
        asked = controller.next_action()
        check_eq("B1: the covered work is done and the left-out work is ASKED about again (not `prepare_stage S9`)",
                 (asked["action"], [h["dispatch_id"] for h in asked.get("held") or []]), ("closed", ["S5-qa-automator-9"]))
        refusal = refused(lambda: controller.apply("dispatch", dict(packet("S5-qa-automator-10", stage="S5", role="qa-automator",
                                                                           relaunch_of="S5-qa-automator-9"),
                                                                    idempotency_key="k-left-2")))
        check("B1: a relaunch of it is still refused ... and the refusal's doors are live ones, never 'once the story is closed again'",
              refusal is not None and "closed again" not in refusal[1] and "leave_unlaunched" in refusal[1]
              and "reopen_story" in refusal[1], refusal)
        # both doors accept it on the open story. `reopen_story` for it later = the full reopen as before; `leave_unlaunched` = history.
        wrong = refused(lambda: controller.reopen_story("S6-qa-runner-9", WORDS + " again"))
        check("a reopen naming the work already covered (no longer held) is refused, naming what is held",
              wrong is not None and "S5-qa-automator-9" in wrong[1], wrong)
        left = controller.leave_unlaunched("S5-qa-automator-9", WORDS)
        check("B1: leave_unlaunched accepts the left-out work on the open story", left["left"], left)
        state = controller.state()
        check_eq("... the dispatch is history with the person's words and its stage is done by the person's leaving",
                 (state["dispatches"]["S5-qa-automator-9"]["status"], state["stages"]["S5"].get("left_by_person")), ("superseded", WORDS))
        done = controller.next_action()
        check("and nothing is held any more: `next` goes on with the story", done["action"] != "closed" and "held" not in done, done)
    finally:
        cleanup(root)
    root = temp_dir("qa-c16a-partial-run-")
    try:
        controller = closed_story(root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="dS6")
        never_started(controller, "S5-qa-automator-9", stage="S5", role="qa-automator", rework_of="dS5")
        controller.reopen_story("S6-qa-runner-9", WORDS)
        first = controller.next_action()["dispatch_request"]
        controller.apply("dispatch", dict(first))
        accept_dispatch(controller, root, first["id"])
        again = controller.reopen_story("S5-qa-automator-9", WORDS + " - and the automator too")
        check_eq("the second word, on the story that is open, covers the rest and leaves nothing out", again["left_held"], [])
        second = controller.next_action()
        check_eq("and `next` relaunches it", (second["action"], second.get("closed_dispatch_id")), ("relaunch", "S5-qa-automator-9"))
        controller.apply("dispatch", dict(second["dispatch_request"]))
        check_eq("the packet lands", controller.state()["dispatches"][second["dispatch_request"]["id"]]["status"], "running")
    finally:
        cleanup(root)
    # reopen naming ALL held = the full reopen as before
    root = temp_dir("qa-c16a-full-")
    try:
        controller = closed_story(root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="dS6")
        never_started(controller, "S5-qa-automator-9", stage="S5", role="qa-automator", rework_of="dS5")
        full = controller.reopen_story("S6-qa-runner-9,S5-qa-automator-9", WORDS)
        check_eq("a reopen that names ALL the held work leaves nothing out", full["left_held"], [])
        check("and nothing is held on the open story", controller.held_work() == [], controller.held_work())
    finally:
        cleanup(root)


def a_released_dispatch_is_not_relaunched_by_a_reopen_for_other_work():
    """The B1 sibling: a RELEASED dispatch is not in `held` (Q1), but it is a relaunch candidate, so a person's `reopen_story` for
    other work must record it as left out - otherwise it was relaunched without being asked, once the covered work was done."""
    root = temp_dir("qa-c16a-released-")
    try:
        controller = closed_story(root)
        stray(controller, "S5-qa-automator-4", stage="S5", role="qa-automator")
        controller.store.commit("release", {"dispatch_id": "S5-qa-automator-4", "words": "nobody", "reason": "x"},
                                "rel:b1", None, None, controller.project)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="dS6")
        check_eq("setup: the released dispatch is not held, the never-started rework is",
                 [h["dispatch_id"] for h in controller.next_action()["held"]], ["S6-qa-runner-9"])
        # A released dispatch is a relaunch candidate only on a stage that is still open; every stage of this fixture story is
        # completed, so the call is made on the state with S5 lowered (the journal and the replay are the real ones).
        real_state = controller.state

        def with_s5_open():
            state = copy.deepcopy(real_state())
            state["stages"]["S5"] = {"status": "pending"}
            return state
        controller.state = with_s5_open
        try:
            got = controller.reopen_story("S6-qa-runner-9", WORDS)
        finally:
            del controller.state
        check_eq("the reopen records the released dispatch as left out", got["left_held"], ["S5-qa-automator-4"])
        check_eq("and the replay keeps it", controller.state()["reopen_left_held"], ["S5-qa-automator-4"])
        refusal = refused(lambda: controller.apply("dispatch", dict(packet("S5-qa-automator-5", stage="S5", role="qa-automator",
                                                                          relaunch_of="S5-qa-automator-4"), idempotency_key="k-rel")))
        check("a relaunch packet of it is refused, and the text names no door that does not open (a release asks for nothing)",
              refusal is not None and "reopen_story --dispatch" not in refusal[1] and "--operation next" in refusal[1], refusal)
    finally:
        cleanup(root)


def a_hand_stamped_packet_cannot_reach_held_work():
    """FB2 (critic t-1182): a dispatch carrying its own `reopened_at` and words passes the closure test only when it is
    REWORK-shaped (`rework_of` names an accepted dispatch of the same stage and role, no `relaunch_of`) - the shape
    `build_rework_request` builds. The invariant of that position: held work stays reachable only through `reopen_story`."""
    root = temp_dir("qa-c16a-forged-")
    try:
        controller = closed_story(root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="dS6")
        revision = controller.state()["revision"]
        stamp = dict(reopened_at="2099-01-01T00:00:00+00:00", reopen_words="ok")
        plain = refused(lambda: controller.apply("dispatch", dict(packet("S6-qa-worker-10", stage="S6", role="qa-worker"),
                                                                  idempotency_key="f1", **stamp)))
        check("a plain packet carrying its OWN stamp and words is refused", plain is not None and plain[0] == "StateConflict", plain)
        relaunch = refused(lambda: controller.apply("dispatch", dict(packet("S6-qa-worker-11", stage="S6", role="qa-worker",
                                                                            relaunch_of="S6-qa-runner-9"),
                                                                     idempotency_key="f2", **stamp)))
        check("a relaunch of held work carrying its OWN stamp and words is refused: held work goes through reopen_story",
              relaunch is not None and relaunch[0] == "StateConflict", relaunch)
        both = refused(lambda: controller.apply("dispatch", dict(packet("S6-qa-worker-12", stage="S6", role="qa-worker",
                                                                       rework_of="dS6", relaunch_of="S6-qa-runner-9"),
                                                                idempotency_key="f3", **stamp)))
        check("... and a packet that is rework-shaped AND a relaunch is a relaunch: refused", both is not None, both)
        wrong_role = refused(lambda: controller.apply("dispatch", dict(packet("S6-qa-worker-13", stage="S6", role="qa-worker",
                                                                             rework_of="dS5"), idempotency_key="f4", **stamp)))
        check("a `rework_of` naming an accepted dispatch of ANOTHER stage is not rework-shaped: refused", wrong_role is not None, wrong_role)
        check_eq("nothing was written by the refusals", controller.state()["revision"], revision)
        rework = refused(lambda: controller.apply("dispatch", dict(packet("S6-qa-worker-14", stage="S6", role="qa-worker",
                                                                         rework_of="dS6"), idempotency_key="f5", **stamp)))
        check("positive control: the rework-shaped packet with its stamp and words passes (what `rework` builds)", rework is None, rework)
    finally:
        cleanup(root)


def leave_unlaunched_ends_the_work_for_good():
    root = temp_dir("qa-c16a-leave-")
    try:
        controller = closed_story(root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="S6-qa-runner-1")
        stray(controller, "S5-qa-automator-9", stage="S5", role="qa-automator")            # RUNNING on a closed story
        controller.store.commit("release", {"dispatch_id": "S5-qa-automator-9", "words": "nobody", "reason": "x"},
                                "rel:1", None, None, controller.project)                  # ... then RELEASED
        stray(controller, "S9-qa-retro-9", stage="S9", role="qa-retro")
        controller.store.commit("state_repair", {"fixes": [{"kind": "never_started", "dispatch_id": "S9-qa-retro-9", "stage": "S9",
                                                            "reason": "r"}], "reason": "t"}, "repair:s9", None, None, controller.project)
        revision = controller.state()["revision"]
        for label, ids, words in (("empty words", "S6-qa-runner-9", ""), ("an unknown id", "S6-nope-1", WORDS),
                                  ("a RELEASED dispatch", "S5-qa-automator-9", WORDS), ("the retro (S9)", "S9-qa-retro-9", WORDS),
                                  ("a dispatch that is not never_started (accepted)", "dS3", WORDS)):
            bad = refused(lambda: controller.leave_unlaunched(ids, words))
            check(f"leave_unlaunched refuses {label}", bad is not None, bad)
        check_eq("and wrote nothing", controller.state()["revision"], revision)
        got = controller.leave_unlaunched("S6-qa-runner-9", WORDS)
        check("leave_unlaunched on a never-started dispatch of a closed story", got["left"], got)
        state = controller.state()
        check_eq("the dispatch is history, with the person's words", (state["dispatches"]["S6-qa-runner-9"]["status"],
                                                                      state["dispatches"]["S6-qa-runner-9"]["left_by_person"]),
                 ("superseded", WORDS))
        after = controller.next_action()
        check_eq("nothing is held for it any more; the only move left is the retro's own relaunch (S9 is never held)",
                 ("held" in after, after.get("closed_dispatch_id")), (False, "S9-qa-retro-9"))
        check("it stays closed: leaving is not a reopening", story_closed(pipeline_of(root)))
        again = controller.leave_unlaunched("S6-qa-runner-9", WORDS)
        check("the same word twice is the same answer", again["left"], again)
        # a later reopen by another road never relaunches what was left
        controller.store.commit("release", {"dispatch_id": "S9-qa-retro-9", "words": "go", "reason": "g",
                                            "reopened_at": "2099-01-01T00:00:00+00:00", "reopen_words": "go"},
                                "rel:2", None, None, controller.project)
        check("a later reopen does not relaunch the dispatch that was left",
              controller.next_action().get("closed_dispatch_id") != "S6-qa-runner-9", controller.next_action())
        open_story = refused(lambda: controller.leave_unlaunched("S6-qa-runner-9", WORDS + " again"))
        check("on a story that is open again the op refuses (nothing is held back)", open_story is not None, open_story)
    finally:
        cleanup(root)


def a_left_stage_is_completed_not_pending():
    """A2: the stage of the dispatch a person left is completed (`completed_by: person_left`), so a later reopen never
    prepares it again. Replayed from the journal, a stage that was pending (the dispatch never started) is what is lowered."""
    import controller as C
    base = [{"type": "initialize", "sequence": 1, "payload": {"scope": ["TC-1"], "source_revision": "s", "known_paths": {}}},
            {"type": "dispatch", "sequence": 2, "payload": packet("S6-qa-runner-1", stage="S6", role="qa-runner")},
            {"type": "state_repair", "sequence": 3, "payload": {"fixes": [{
                "kind": "never_started", "dispatch_id": "S6-qa-runner-1", "stage": "S6", "reason": "r"}]}}]
    before = C.projection(base)
    check_eq("setup: the never-started dispatch leaves its stage pending", before["stages"]["S6"]["status"], "pending")
    after = C.projection(base + [{"type": "leave_unlaunched", "sequence": 4,
                                  "payload": {"dispatch_ids": ["S6-qa-runner-1"], "words": WORDS}}])
    check_eq("after `leave` the stage is completed by the person's leaving",
             (after["stages"]["S6"]["status"], after["stages"]["S6"]["completed_by"], after["stages"]["S6"]["left_by_person"]),
             ("completed", "person_left", WORDS))
    check_eq("and the dispatch is superseded", after["dispatches"]["S6-qa-runner-1"]["status"], "superseded")


def the_driver_asks_about_held_work_and_carries_out_the_answer():
    """C1-6a (driver): `_act_closed` raises the `closed.held` question (priced, three tokens) when `next` lists held work, and
    each token has its executor (FR-9). A finished story with nothing held says so and promises nothing (A8)."""
    import types
    import story_run
    from harness import remember_cwd, use_project
    task = "QA-C16A"
    project = temp_project("qa-c16a-driver-")
    try:
        use_project(project)
        task_root = project / "qa-factory" / "artifacts" / task
        task_root.mkdir(parents=True)
        controller = closed_story(task_root)
        never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="S6-qa-runner-1",
                      reason="the hook refused the call")
        remember_cwd()
        ns = types.SimpleNamespace(task=task, answer=None, until="end", dry_run=False, model="sonnet", plugin_dir=None,
                                   project=str(project), mr=None, branch=None, commit=None, ungrounded=False, ticket_file=None,
                                   env=None, branch_suffix="", max_boundaries=10)
        driver = story_run.Driver(ns)
        action = Controller(task_root).next_action()
        asked = refused(lambda: driver._act_closed(action))
        check("held work on a closed story: the driver ASKS (a Person), it does not relaunch", asked is not None and asked[0] == "Person", asked)
        try:
            driver._act_closed(action)
        except story_run.Person as person:
            text = str(person)
            check_eq("kind and stage", (person.kind, person.stage), ("closed_held", "S6"))
            for needle in ("never started", "reopens the story with your words", "`run again`", "`leave`", "`stop`",
                           "also when you finish it yourself", "the report already written is not rebuilt by this"):
                check_in(f"the question says: {needle}", needle, text)
            check_eq("three price lines under each of the three options", text.count("the factory:"), 3)
            check_not_in("no command and no script in a text a person reads (J3)", "controller.py", text)
            import human_text
            # (`no_how_to_answer` is the block `ask()` appends under the text; this reads the text before it)
            check_eq("the text obeys references/human-questions.md (FR-6): no rule it breaks",
                     [p["rule"] for p in human_text.problems(text, offered=list(person.priced))
                      if p["rule"] != "no_how_to_answer"], [])
            check_eq("the question names exactly the set the answer will cover", driver.state["closed_held"],
                     {"dispatch_ids": ["S6-qa-runner-9"]})
        # FB4 (ii): the stage is named by the driver's one `stage_place` - a stage with no name in stages.json is `stage S99`,
        # never "the  stage (S99)" with a double space
        named_set = driver.state.get("closed_held")
        for reopened, opening in ((False, "is finished"), (True, "was reopened for other work")):
            odd = str(driver.closed_held_person([{"dispatch_id": "S99-qa-x-1", "stage": "S99", "role": "qa-x", "reason": ""}],
                                                reopened=reopened))
            check("a held piece of a stage that has no name reads `stage S99, qa-x` (reopened=%s)" % reopened,
                  "stage S99, qa-x" in odd and "the  stage" not in odd and opening in odd, odd[:300])
        driver.state["closed_held"] = named_set
        # free words: the seam reads them first - the controller is untouched, nothing is dispatched
        revision = Controller(task_root).state()["revision"]
        calls = []
        driver.unread = lambda *a, **k: calls.append((a, k)) or "continue"
        driver._answer = {"text": "do whatever you think best", "rel": None}
        got = driver._take_closed_held_answer("do whatever you think best", "q", "S6")
        check_eq("free words go to the seam with `run again` / `leave` as its doors, and nothing is taken as a token",
                 (got, len(calls), calls[0][1]["doors"]), (False, 1, ("run again", "leave")))
        check_eq("the controller is untouched by free words", Controller(task_root).state()["revision"], revision)
        # leave: the dispatch is history with the person's words; the second entry asks nothing (FR-7); a story with nothing held
        driver._answer = {"text": "leave\nI will do it myself", "rel": None, "kind": "closed_held", "stage": "S6", "dispatch": "",
                          "question_sha": "q", "words": "leave\nI will do it myself"}
        driver.state["closed_held"] = {"dispatch_ids": ["S6-qa-runner-9"]}
        check("`leave` is a token", driver._take_closed_held_answer("leave\nI will do it myself", "q", "S6") is True)
        rows = [json.loads(line) for line in (driver.state_dir / "driver-answers.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("A6: the audit row holds the TOKEN as a typed field, and the file that holds the whole answer",
                 (rows[-1]["token"], bool(rows[-1]["words_file"])), ("leave", True))
        after = Controller(task_root).state()["dispatches"]["S6-qa-runner-9"]
        check_eq("the dispatch is superseded with the whole answer as the words", (after["status"], "I will do it myself" in after["left_by_person"]),
                 ("superseded", True))
        again = Controller(task_root).next_action()
        check_eq("FR-7: the second entry has nothing to ask", ("held" in again, again["action"]), (False, "closed"))
        stop = refused(lambda: driver._act_closed({key: value for key, value in again.items()
                                                   if key not in ("retro_pending", "stage")}))     # the retro is not this test's subject
        check_eq("A8: the finished story says it is finished and promises nothing",
                 (stop[0], "the story is finished; nothing is pending." in stop[1], "rework" in stop[1]), ("Stop", True, False))
        # run again on a new held dispatch: the story is reopened by the person's words, and `next` relaunches it
        never_started(controller, "S5-qa-automator-9", stage="S5", role="qa-automator", rework_of="S5-qa-automator-1")
        question = Controller(task_root).next_action()
        check_eq("a new held dispatch asks a CHANGED question", [h["dispatch_id"] for h in question["held"]], ["S5-qa-automator-9"])
        refused(lambda: driver._act_closed(question))
        driver._answer = {"text": "run again\nplease, the runner is fixed", "rel": None}
        check("`run again` is a token", driver._take_closed_held_answer("run again\nplease, the runner is fixed", "q", "S5") is True)
        relaunch = Controller(task_root).next_action()
        check_eq("the story is open by the person's word and `next` relaunches the covered dispatch",
                 (relaunch["action"], relaunch.get("closed_dispatch_id")), ("relaunch", "S5-qa-automator-9"))
        check_in("the person's whole answer is stamped on the story", "the runner is fixed", pipeline_of(task_root).get("reopened_by_words", ""))
    finally:
        cleanup(project)


def main() -> None:
    a_dispatch_on_a_closed_story_needs_a_persons_word()
    the_driver_asks_about_held_work_and_carries_out_the_answer()
    reopen_story_starts_only_what_the_word_covered()
    a_partial_reopen_keeps_a_door_for_the_work_it_left()
    a_released_dispatch_is_not_relaunched_by_a_reopen_for_other_work()
    a_hand_stamped_packet_cannot_reach_held_work()
    leave_unlaunched_ends_the_work_for_good()
    a_left_stage_is_completed_not_pending()
    the_rule_is_read_in_one_place()
    the_writers_stamp_the_closure()
    project, task = stage_done_stamps_an_unmanaged_story()
    s9_refuses_to_leave_a_tail(project, task)
    s9_with_no_report_goes_to_the_scribe()
    s9_passes_a_report_that_checks_clean()
    s9_passes_a_legacy_report_and_says_so()
    s9_refuses_what_the_rebuild_cannot_settle()
    s9_rebuilds_a_stale_block_and_goes_on()
    s9_goes_on_when_the_rebuild_cannot_run()
    s9_never_refuses_for_its_own_crash()
    s9_records_the_size_the_story_never_got()
    s3_exit_reports_question_branches_and_never_refuses()
    recover_settles_the_tail_of_a_closed_story()
    reopening_is_a_persons_word()
    a_release_on_a_closed_story_is_recorded_too()
    finish("test_story_closed")


if __name__ == "__main__":
    main()
