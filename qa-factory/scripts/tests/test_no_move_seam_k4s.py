#!/usr/bin/env python3
"""k4s: a part of test_no_move_seam.py, split by tools/test_split.py (TD-11c). The shared helpers are in no_move_seam_common."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
import story_run_common  # noqa: E402
del story_run_common  # split: imported for its sys.path effect
import no_move as NM  # noqa: E402
import story_run  # noqa: E402
from no_move_seam_common import _site_ok, answer, raised, rig, seam_asked, take, verdict  # noqa: E402


# --- t-764 (C1-5d2, EL12 on the REAL data): ONE block, at the end of the file ---------------------------------------------------------------------

def el12_the_exit_limit_questions_own_doors_are_no_moves_word() -> None:
    """EL12: the doors of the question that really is raised (`exit.resume_limit` of question-prices.json, read directly; the seam's offer is pinned to it in test_story_run_exit_limit.py EL1) are
    read through the seam's door check as the Driver passes them (`site_doors`: every answer that is not a standing token). `fresh`, not
    `restart`: `restart` is the token of the move `release_and_restart`, and a site door that is a move's word is refused (G7)."""
    normalize, spec = story_run.Driver.s0_normalize, NM.data()
    answers = [row["answer"] for row in NM.load_question_prices()["exit.resume_limit"]]
    check_eq("EL12 (data): the question's answers, read from the data itself, in order", answers, ["round", "fresh", "go on", "stop"])
    doors = tuple(t for t in answers if t not in NM.TOKEN_MOVES)
    check_eq("EL12 (data): its site doors are round and fresh (go on and stop are standing tokens)", doors, ("round", "fresh"))
    check("EL12 (data): and the seam accepts them as doors - none is a move's word", _site_ok(doors, spec, normalize))
    renamed = tuple("restart" if t == "fresh" else t for t in doors)
    check("EL12 negative control: the same door check refuses `fresh` renamed `restart`", not _site_ok(renamed, spec, normalize))


# --- t-835 (C2-5s, class K4): the driver's record of the standing refusal: ONE block at the end of the file ----------------------------------------------------

CTRL_BODY = ("the qa-code-critic window is not receipted: no review receipt for TC-1; no window record for TC-2: the probe receipt cannot be read. "
             "These are the review's own receipts, not the person's to produce. If a person accepts the window without them: "
             "`waiver.py --task QA-9 --stage S5 --block \"not receipted\" --words-file <file>`.")


CTRL_REFUSAL = "story_step finish S5-qa-code-critic-1 (exit 3):\n" + CTRL_BODY


def k4s_rig(answers=None):
    root, task_root, driver = rig(answers=answers)
    return root, task_root, driver, task_root / "state" / "standing-refusal.json"


def k4s_fresh(driver, state):
    """`raised` on a fresh boundary: the per-boundary cap of conductor calls is not under test here."""
    driver.conductor_calls = {}
    return raised(driver, state)


def k4s_record(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def k4s_state(lines, **extra):
    return dict({"why": "refusal", "kind": "refusal", "call": False, "stage": "S5", "dispatch": "", "lead": "The step was refused.",
                 "text": CTRL_REFUSAL, "lines": lines}, **extra)


def k4s_lines_are_the_readers() -> None:
    """q1 (t-782): `refusal_lines` is the C2-1 reader (`DV.refusal_text` transport, `DV.split_items`) then `waiver.refusal_parts` - no second stripper."""
    import waiver
    lines = story_run.Driver.refusal_lines(story_run.Refusal(CTRL_REFUSAL))
    check_eq("K4s: the controller's joined problems come out apart, the header of the driver cut, the first one whole", lines[0],
             "the qa-code-critic window is not receipted: no review receipt for TC-1")
    check("K4s (negative pin, finding 9): the door in backticks is in no line - 'waiver.py --task' is nowhere", all("waiver.py --task" not in l for l in lines), str(lines))
    head = "2 problems - the request is refused whole, every one is listed:"
    check_eq("K4s: a combined refusal is read by its head (C2-1), the number cut", story_run.Driver.refusal_lines(
        story_run.Refusal("story_step: refused - " + head + "\n1) alpha\n2) beta")), ["alpha", "beta"])
    check_eq("K4s: ...the JSON transport of `--operation decision` is taken off first", story_run.Driver.refusal_lines(
        story_run.Refusal(json.dumps({"error": head + "\n1) alpha\n2) beta"}))), ["alpha", "beta"])
    check_eq("K4s: ...an item that goes on over several lines stays ONE item", story_run.Driver.refusal_lines(
        story_run.Refusal(head + "\n1) alpha\n   with more\n2) beta")), ["alpha\n   with more", "beta"])
    check_eq("K4s: the raiser's own findings win; `items` win over them", (story_run.Driver.refusal_lines(story_run.Refusal("x\ny", findings=["f1; f2"])),
             story_run.Driver.refusal_lines(story_run.Refusal("x\ny", findings=["f1"]), items=["i1"])), (["f1", "f2"], ["i1"]))
    check_eq("K4s edge: one line of text has no 'below the first line': the text whole", story_run.Driver.refusal_lines(story_run.Refusal("just this")), ["just this"])
    check_eq("K4s edge: all door in backticks normalises to nothing and is returned as it is (never empty, exit_limit needs a line)",
             story_run.Driver.refusal_lines(None, items=["`waiver.py --task QA-1`"]), ["`waiver.py --task QA-1`"])
    check_eq("K4s: the same normalisation as the writer's (one builder)", story_run.Driver.refusal_lines(None, items=[CTRL_BODY]), waiver.refusal_parts([CTRL_BODY]))


def k4s_the_writer() -> None:
    import waiver
    root, task_root, driver, path = k4s_rig()
    lines = story_run.Driver.refusal_lines(story_run.Refusal(CTRL_REFUSAL))
    check_eq("K4s: the record is where the reader reads it", path.resolve(), waiver.standing_path("QA-9").resolve())
    _, person = raised(driver, k4s_state(lines))
    check("K4s: the seam raised its Person", person is not None)
    record = k4s_record(path)
    check_eq("K4s: a seam entry with `lines` writes the record: stage, lines, doors - exactly those", (sorted(record), record["stage"], record["lines"], record["doors"]),
             (["doors", "lines", "stage"], "S5", lines, ["not receipted"]))
    check("K4s (axis 8): the record carries no absolute path", str(root) not in path.read_text(encoding="utf-8"))
    check("K4s: a Person raised - the record LIVES with the open question (it is not erased)", path.is_file())
    raised(driver, k4s_state(["a different problem"], stage="S5", text="no door here"))
    check_eq("K4s: a second refusal REPLACES the record (never merged); no door line: doors []", k4s_record(path), {"stage": "S5", "lines": ["a different problem"], "doors": []})
    raised(driver, k4s_state(["another stage's problem"], stage="S6"))
    check_eq("K4s: ...also when it is another stage's", (k4s_record(path)["stage"], k4s_record(path)["lines"]), ("S6", ["another stage's problem"]))
    many = [f"problem {n}" for n in range(1, 26)]
    raised(driver, k4s_state(many))
    check_eq("K4s edge: a list of 25 is recorded WHOLE (the ceiling 20 is the listing's, not the record's)", len(k4s_record(path)["lines"]), 25)
    driver._in_no_move = True
    raised(driver, k4s_state(["from inside the seam"]))
    driver._in_no_move = False
    check_eq("K4s: a call from INSIDE the seam never rewrites the outer one's record", k4s_record(path)["lines"], many)
    for why, extra in (("unread_answer", {}), ("chosen", {"token": "go on", "move": "go_on_as_is"}), ("by_hand", {}), ("stop", {})):
        raised(driver, {"why": why, "kind": "conductor", "stage": "S5", "dispatch": "", "text": "t", "call": False, **extra})
        check_eq(f"K4s: why={why} carries no `lines` and leaves the record as it was", k4s_record(path)["lines"], many)
    raised(driver, k4s_state([]))
    check_eq("K4s edge: an empty `lines` is not written (the old record is the old refusal's, untouched)", k4s_record(path)["lines"], many)
    driver.dry = True
    raised(driver, k4s_state(["dry"]))
    check_eq("K4s: a dry run writes nothing ...", k4s_record(path)["lines"], many)
    driver.drop_standing()
    check("K4s: ... and erases nothing", path.is_file())
    driver.dry = False
    pipeline = task_root / "pipeline.json"
    base = json.loads(pipeline.read_text(encoding="utf-8"))
    pipeline.write_text(json.dumps(dict(base, stages={"S4": {"status": "done"}, "S5": {"status": "running"}})), encoding="utf-8")
    raised(driver, k4s_state(["funnel"], stage=""))
    check_eq("K4s: with no stage (`funnel`) the ONE running stage of pipeline.json is the record's", (k4s_record(path)["stage"], k4s_record(path)["lines"]), ("S5", ["funnel"]))
    pipeline.write_text(json.dumps(dict(base, stages={"S5": {"status": "running"}, "S6": {"status": "running"}})), encoding="utf-8")
    raised(driver, k4s_state(["two running"], stage=""))
    check("K4s edge: two running stages - the stage is unknown: no record, and the old one goes (FR-59)", not path.is_file())
    raised(driver, k4s_state(["no running"], stage="where"))
    check("K4s edge: a stage that is no stage id - no record", not path.is_file())


def k4s_the_erasers() -> None:
    root, task_root, driver, path = k4s_rig([{"action": "continue", "did": "moved"}, {"action": "retry", "did": "again"}])
    stand = lambda: path.write_text(json.dumps({"stage": "S5", "lines": ["x"], "doors": []}), encoding="utf-8")   # noqa: E731
    stand()
    result, _ = raised(driver, k4s_state(["y"], call=True))
    check_eq("K4s E1: the conductor `continue` returns", result, "continue")
    check("K4s E1: ... and the record is erased", not path.is_file())
    stand()
    result, _ = raised(driver, k4s_state(["y"], call=True))
    check_eq("K4s E1: `retry` too", (result, path.is_file()), ("retry", False))
    stand()
    driver.guarded(lambda: None, {"stage": "S5"})
    check("K4s E2: a step that went through erases the record (it does not outlive its stage)", not path.is_file())
    stand()
    calls = []
    driver.handle_refusal = lambda refusal, **k: "retry"
    driver.guarded(lambda: (_ for _ in ()).throw(story_run.Refusal("again", retry=lambda: calls.append(1))), {"stage": "S5"})
    check_eq("K4s E2: a retried step that went through erases it too", (calls, path.is_file()), ([1], False))
    stand()
    seam_asked(driver)
    check("K4s: ask() leaves the record (the question about the refusal is open)", path.is_file())
    check("K4s E3: the answer closes the question and erases the record", take(driver, answer(task_root, "a.txt", b"retry")) is None and not path.is_file())
    stand()
    driver.state["asked"] = {}
    driver.reconcile_question()
    check("K4s E4: no question open at start - the record a crash left is erased", not path.is_file())
    stand()
    seam_asked(driver)
    driver.reconcile_question()
    check("K4s E4: ... a question that IS open keeps it", path.is_file())
    stand()
    driver.dry = True
    driver.guarded(lambda: None, {"stage": "S5"})
    check("K4s: dry run - no eraser acts", path.is_file())


def k4s_the_go_on_note() -> None:
    import waiver
    root, task_root, driver, path = k4s_rig([verdict(), verdict(), verdict()])
    chosen = {"why": "chosen", "kind": "conductor", "stage": "S5", "dispatch": "", "token": "go on", "move": "go_on_as_is", "text": "t", "words_file": "", "block": ""}
    k4s_fresh(driver, chosen)
    check_in("K4s 3.4: with no record the note says so and names the door", "No refusal is recorded as standing here; if their words pass nothing, keep them with --remark.", driver.calls[-1]["text"])
    path.write_text(json.dumps({"stage": "S5", "lines": ["first problem", "second problem"], "doors": []}), encoding="utf-8")
    k4s_fresh(driver, chosen)
    note = driver.calls[-1]["text"]
    check_in("K4s 3.4: the record's lines are the closed list, numbered", "  1. first problem\n  2. second problem", note)
    check_in("K4s 3.4: ... one --block per line, the line whole; the writer refuses any other", "one waiver.py --block per line, the line whole", note)
    check_in("K4s 3.4: ... and says waiver.py refuses a block in none of them", "waiver.py refuses a block that is in none of them.", note)
    path.write_text(json.dumps({"stage": "S5", "lines": [f"problem {n}" for n in range(1, 22)], "doors": []}), encoding="utf-8")
    k4s_fresh(driver, chosen)
    note = driver.calls[-1]["text"]
    check_in("K4s 3.4 edge: 21 lines - the 20th whole, the ceiling named with the file", "  20. problem 20\n  (+1 more: " + str(waiver.standing_path("QA-9")) + ")", note)
    check_not_in("K4s 3.4 edge: ... and the 21st is not listed", "  21. problem 21", note)
    k4s_fresh(driver, dict(chosen, stage="S6"))
    check_in("K4s 3.4 edge: a record of ANOTHER stage is no record here", "No refusal is recorded as standing here", driver.calls[-1]["text"])
    k4s_fresh(driver, dict(chosen, move="person_does", token="retry"))
    check_not_in("K4s 3.4: the list belongs to `go on` only", "has these lines", driver.calls[-1]["text"])


def k4s_wr7_live_and_the_cross_node_pins() -> None:
    """WR7 end to end with the driver as the writer (§L-7, the dormant branch gone), and the two cross-node pins of t-778/t-782."""
    import waiver
    root, task_root, driver, path = k4s_rig()
    stage_overrides = lambda: json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")).get("stage_overrides") or []   # noqa: E731
    run = lambda block: harness.run_script("waiver.py", "--task", "QA-9", "--stage", "S5", "--block", block, "--decision", "go on", cwd=root,   # noqa: E731
                                           env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    done = run("some block the driver never saw")
    check_eq("K4s WR7 (before): no record - the writer records, 'not verified', never 'block lifted'", (done.returncode, len(stage_overrides()), "not verified" in done.stdout, "block lifted" in done.stdout), (0, 1, True, False))
    lines = story_run.Driver.refusal_lines(story_run.Refusal(CTRL_REFUSAL))
    raised(driver, k4s_state(lines))
    refused = run("window_record.py --review-receipt")
    check_eq("K4s WR7 (live): the driver's record is there - a block in none of its lines is REFUSED, nothing written", (refused.returncode, len(stage_overrides())), (waiver.EXIT_BAD_ARGS, 1))
    check_in("K4s WR7 (live): ... with the record's first line listed whole after the guard's (the closed options)", ". " + lines[0], refused.stderr)
    held = run("not receipted")
    check_eq("K4s WR7 (live): the door the refusal printed is recorded on its own door", (held.returncode, len(stage_overrides())), (0, 2))
    check_not_in("K4s WR7 (live): ... and not called lifted", "block lifted", held.stdout)
    part = run("no review receipt for TC-1")
    check_eq("K4s WR7 (live): a part only one line holds is recorded against the record", (part.returncode, "recorded against the refusal standing at S5" in part.stdout), (0, True))
    # cross-node pin 1 (t-778): d2's exit-limit `go on` writes one waiver row per line that REACHED the seam - raw handoff lines, whole
    whole = "case identity: a case file's `id` is its file name - 2 file(s) break that: bad.md -> `TC-2.md` with `id: TC-2`; other.md -> `TC-3.md` with `id: TC-3`. Way on: write each case again. A person's word passes this check"
    second = "journal: entry 4 has no `ts`"
    dispatch = "S5-qa-code-critic-1"
    caller_lines = story_run.Driver.refusal_lines(None, items=[whole, second])      # normalised once, by the caller (t-842 F3)
    raised_by_seam = lambda: driver.exit_limit("S5", "qa-code-critic", dispatch, caller_lines, sid="", why="handoff")   # noqa: E731
    try:
        raised_by_seam()
    except story_run.Person:
        pass
    check_eq("K4s cross-node: the exit-limit seam writes the record from the same lines (one builder)", k4s_record(path)["lines"], waiver.refusal_parts([whole, second]))
    before = len(stage_overrides())
    (task_root / "state" / "words").mkdir(parents=True, exist_ok=True)
    (task_root / "state" / "words" / "w.txt").write_text("go on", encoding="utf-8")
    driver._exit_go_on(driver.exit_record(dispatch), "S5", dispatch, "state/words/w.txt", "go on")
    check_eq("K4s cross-node (t-778 Q8): d2's `go on` rows are written against the record - one per line the caller handed the seam (here the "
             "3 parts of `refusal_lines`), every one passes it (no held question)", len(stage_overrides()) - before, len(caller_lines))
    # cross-node pin 2 (t-782 Q7): the seam's own `go on` WITH asked.block is an own-form constant - never judged against the record
    seam_asked(driver, options=(("go on", "go_on_as_is"), ("stop", "stop_here")), block=waiver.STAND_NOT_CONFIRMED_BLOCK)
    before = len(stage_overrides())
    check("K4s cross-node (t-782 Q7): `go on` with asked.block passes while the record of the stage holds other lines",
          take(driver, answer(task_root, "g.txt", b"go on")) is None and len(stage_overrides()) == before + 1)


def k4s_fix_round() -> None:
    """The fix round of t-835 (critic t-842, Lead's §L-8): F1 the window case, F2 the key, F3 the lines `exit_limit` is given."""
    import waiver
    # F1: the record carries the REAL line of the window's set, not the comparison form (`<dispatch>` for an id)
    root, task_root, driver, path = k4s_rig()
    line = "S5-qa-code-critic-1 has no review receipt for case TC-3"
    refusal = story_run.Refusal("story_step finish S5-qa-code-critic-1 (exit 3):\n" + line, dispatch="S5-qa-code-critic-1", window_findings=[line])
    driver.window_round_gate(refusal, "S5")                                   # round 1 goes to the conductor: no record
    check("K4s F1: round 1 (the conductor's) writes no record", not path.is_file())
    try:
        driver.window_round_gate(refusal, "S5")                               # the same set again: the person is asked
        raised_here = None
    except story_run.Person as person:
        raised_here = person
    check("K4s F1: the same set a second time raises the person's question", raised_here is not None)
    record = k4s_record(path)
    check_eq("K4s F1: the record carries the real line, the id in it (not `<dispatch> has no ...`)", record["lines"], [line])
    check("K4s F1 (negative control): the comparison form is a different string - the bug would have recorded it", story_run.finding_lines([line]) != [line])
    done = harness.run_script("waiver.py", "--task", "QA-9", "--stage", "S5", "--block", line, "--decision", "go on", cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    check_eq("K4s F1: the writer ACCEPTS the real line (carrier), nothing refused", (done.returncode, "recorded against the refusal standing at S5" in done.stdout), (0, True))
    check_eq("K4s F1: the reader clears exactly that line", waiver._reads(record["lines"], "S5", line), [line])
    # F2: the key of a finding set tells two problems that differ only in a final span apart (the same function as the record's)
    two = [story_run.Driver.refusal_lines(story_run.Refusal("head:\nno test is bound to case `TC-" + n + "`")) for n in ("3", "7")]
    check("K4s F2: two refusals differing only in their final `TC-n` span have two keys", story_run.finding_key(two[0]) != story_run.finding_key(two[1]), str(two))
    # F3: `exit_limit` records the lines it is GIVEN (normalised once, by the caller); an empty list is a Person, not an AttributeError
    root, task_root, driver, path = k4s_rig()
    for label, given in (("[]", []), ("None", None)):
        try:
            driver.exit_limit("S5", "qa-code-critic", "S5-qa-code-critic-1", given, sid="", why="handoff")
            outcome = "returned"
        except story_run.Person:
            outcome = "Person"
        except Exception as exc:                                              # noqa: BLE001 - the pin names the wrong kind of failure
            outcome = type(exc).__name__
        check_eq(f"K4s F3: exit_limit(..., {label}) raises the person's question (the generic text), nothing else", outcome, "Person")
        check("K4s F3: ... and writes no record (no lines)", not path.is_file())
    raw = "x `waiver.py --a`"
    try:
        driver.exit_limit("S5", "qa-code-critic", "S5-qa-code-critic-1", [raw], sid="", why="handoff")
    except story_run.Person:
        pass
    check_eq("K4s F3: exit_limit does not normalise a second time - the record is the line it was given", k4s_record(path)["lines"], [raw])
    inputs = ["missing `a` `b`", "problem one. If a person accepts it: `waiver.py --task QA-9 --block \"x\"`.", "1) alpha; beta"]
    once = story_run.Driver.refusal_lines(None, items=inputs)
    check_eq("K4s F3: the caller's normalisation is idempotent (``missing `a` `b` `` among the inputs)", story_run.Driver.refusal_lines(None, items=once), once)
    check_eq("K4s F3: refusal_lines(None, items=[]) is no lines, the refusal is not read", story_run.Driver.refusal_lines(None, items=[]), [])


def k4s_run() -> None:
    for scenario in (
        k4s_lines_are_the_readers,
        k4s_the_writer,
        k4s_the_erasers,
        k4s_the_go_on_note,
        k4s_wr7_live_and_the_cross_node_pins,
        k4s_fix_round,
    ):
        scenario()


# split: runner piece 1
if __name__ == "__main__":
    k4s_run()                                                       # t-835: one block at the end, so the merge with another node is clean
    el12_the_exit_limit_questions_own_doors_are_no_moves_word()     # t-764: one block at the end, so the merge with another node is clean
    harness.finish("no_move seam_k4s")
