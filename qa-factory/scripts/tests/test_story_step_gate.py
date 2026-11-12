#!/usr/bin/env python3
"""story_step.py `finish` re-reads the stage's exit gate before it accepts (GW1-8, t-1264): the gate read by data, its decision
door and the fail-open paths pinned. Split off test_story_step.py (TQ1-10); the helpers are in story_step_common.py.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_step  # noqa: E402
from story_step_common import (  # noqa: E402
    author_picture,
    author_picture_of,
    author_story,
    finish_here,
    finish_s4,
    run_decide,
    s4_story,
)


def finish_exit_gate_checks() -> None:
    """K1-K7 of GW1-8. KILLS: M1 (no reader call: K1 reads exit 0), M2 (the read after `apply`: K1's picture moves),
    M3 (the read before `_halt_gate`: K5's counter reads 1), M4 (`--ignore-handoff` skips the read: K4 reads exit 0),
    M5 (a reader raise read as `([], [])`: K7 reads exit 0), M8 (`waiver.py` named for a refused-tag-only list: K1
    reads it in stdout)."""
    import detector_verdict as DV
    import exit_gate
    root = harness.temp_project("qa-gw18-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    real_errors, real_all = exit_gate.detector_errors, exit_gate.all_errors
    calls = {"all_errors": 0}

    def counted(*args, **kw):
        calls["all_errors"] += 1
        return real_all(*args, **kw)

    def records(*found):
        # RH1-5 (52dc2dcb, N6): `all_errors` calls `detector_errors(agent, task)` - the stand-in takes the optional task too
        exit_gate.detector_errors = lambda agent, task="": list(found)
    try:
        harness.use_project(root)
        exit_gate.all_errors = counted
        art = author_story(root, "QA-G1")
        before = author_picture(art)
        host = root / "qa-factory/state/host-dispatches"
        receipt_file = host / "agent-s5-author.json"

        def bind_receipt(path: Path, task: str) -> None:
            """The receipt `story_step bind` writes for a running dispatch (F7): a refusal must leave it NON-terminal."""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"agent_id": "agent-s5-author", "agent_type": "qa-automator", "task_id": task,
                                        "dispatch_id": "s5-author", "status": "running", "bound_by": "story_step",
                                        "bound_at": 1.0}), encoding="utf-8")

        def receipt_status(path: Path):
            return json.loads(path.read_text(encoding="utf-8")).get("status")
        bind_receipt(receipt_file, "QA-G1")
        flat = ("finish", "--task", "QA-G1", "--dispatch-id", "s5-author", "--digest", "x", "--output", "author.txt")

        # K1: the REAL s5_precheck (a subprocess), no run block -> refused, nothing recorded
        refused = harness.run_script("story_step.py", *flat, cwd=root, env=env)
        check_eq("K1: a red precheck is refused with exit 3", refused.returncode, 3)
        for label, needle in (("the finding", "no run block has been written for this story yet"),
                              ("that nothing was recorded", "nothing was recorded"),
                              ("the pause door", "story_step.py pause --task QA-G1 --dispatch-id s5-author"),
                              ("the recover door", "--operation recover"),
                              ("the author's marker", "This is a repair, not a question for the person")):
            check_in(f"K1: the refusal names {label}", needle, refused.stdout)
        check_not_in("K1/M8: no word door for a list the source refused to every word", "waiver.py", refused.stdout)
        check_eq("K1/M2: the controller's revision and the dispatch are unchanged", author_picture(art), before)
        check_eq("K1/F7: and the story_step-bound host receipt of the dispatch is still `running`, not terminal",
                 receipt_status(receipt_file), "running")

        # K6: no record of the gate on this host, and a record of another key: the same words, the same exit
        state_file = root / "qa-factory/state/.exit_gate_blocks.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        check("K6: this host has no gate record at all", not state_file.exists())
        state_file.write_text(json.dumps({"some-other-key": {"status": "incomplete"}}), encoding="utf-8")
        again = harness.run_script("story_step.py", *flat, cwd=root, env=env)
        check_eq("K6: with a record of another key the verdict is the same", (again.returncode, again.stdout),
                 (refused.returncode, refused.stdout))
        state_file.unlink()

        # K4: no flag lifts it
        for label, more, code in (
                ("--ignore-handoff", ("--ignore-handoff",), 3),
                ("--complete", ("--complete",), 3),
                ("--not-complete", ("--not-complete",), 3),     # the automator's normal driver call (F6)
                ("--unresolved/--reason", ("--unresolved", "blocked_by_env", "--reason", "the stand is down"), 3),
                # S5 refuses `--unresolved` with `--not-complete` before the gate is reached (`_open_window_refusal`)
                ("--unresolved/--reason --not-complete", ("--unresolved", "blocked_by_env", "--reason", "x",
                                                          "--not-complete"), 2)):
            done = harness.run_script("story_step.py", *flat, *more, cwd=root, env=env)
            check_eq(f"K4/M4: {label} does not lift it", done.returncode, code)
            check_eq(f"K4: {label} - nothing was recorded", author_picture(art), before)
        form = art / "work/handoffs/s5-author.yaml"
        # F6 (fix round): `handoffs.required: false` is the door of an UNTOUCHED form; it must not reach past the gate. The
        # form is really initialised and left alone, and the config really says `required: false`.
        init = harness.run_script("handoff_init.py", "--task", "QA-G1", "--stage", "S5", "--role", "qa-automator",
                                  "--to", "qa-code-critic", "--dispatch", "s5-author", "--task-root", str(art),
                                  cwd=root, env=env)
        check("K4/F6: the handover form is initialised and left untouched", init.returncode == 0 and form.is_file(),
              init.stdout + init.stderr)
        owed = harness.run_script("story_step.py", *flat, cwd=root, env=env)
        check_eq("K4/F6: by default an untouched form is the form branch's refusal (exit 3, before the gate)",
                 (owed.returncode, "left its handover form untouched" in owed.stdout, "exit gate of S5" in owed.stdout),
                 (3, True, False))
        # the check above ran `--fix` on the form (code fills what it can derive), so it is no longer UNTOUCHED: start over
        form.unlink()
        again_init = harness.run_script("handoff_init.py", "--task", "QA-G1", "--stage", "S5", "--role", "qa-automator",
                                        "--to", "qa-code-critic", "--dispatch", "s5-author", "--task-root", str(art),
                                        cwd=root, env=env)
        check("K4/F6: the form is initialised again, untouched", again_init.returncode == 0 and form.is_file(),
              again_init.stdout + again_init.stderr)
        config_file = root / "qa-factory/config.json"
        config_bytes = config_file.read_bytes()
        config = json.loads(config_bytes.decode("utf-8-sig"))
        config["handoffs"] = {"required": False}
        config_file.write_text(json.dumps(config), encoding="utf-8")
        try:
            lifted = harness.run_script("story_step.py", *flat, cwd=root, env=env)
        finally:
            config_file.write_bytes(config_bytes)
        check("K4/F6: with `handoffs: {required: false}` and an untouched form the form branch is passed - and the "
              "GATE refuses (exit 3, its own words)",
              (lifted.returncode, "left its handover form untouched" in lifted.stdout,
               "exit gate of S5 still refuses" in lifted.stdout) == (3, False, True), lifted.stdout[-700:])
        check_eq("K4/F6: and nothing was recorded", author_picture(art), before)
        form.unlink()

        # K7: an unreadable verdict is never an accept (exit 2, the type named, nothing recorded)
        def raising(*_a, **_kw):
            raise RuntimeError("boom")
        for label, reader, said in (("a raise", raising, "exit gate could not be read (RuntimeError)"),
                                    ("None", lambda *_a, **_kw: None, "exit gate could not be read (unknown shape)"),
                                    ("a 1-tuple", lambda *_a, **_kw: ([],), "exit gate could not be read (unknown shape)"),
                                    ("a tuple of strings", lambda *_a, **_kw: ("a", "b"),
                                     "exit gate could not be read (unknown shape)")):
            exit_gate.all_errors = reader
            code, out = finish_here("QA-G1")
            check_eq(f"K7/M5: {label} - exit 2", code, 2)
            check_in(f"K7: {label} - names it", said, out)
            check_in(f"K7: {label} - says nothing was recorded", "nothing was recorded", out)
            check_not_in(f"K7: {label} - no word door (there is no finding to judge)", "waiver.py", out)
            check_not_in(f"K7: {label} - and no repair marker (the factory's defect, not the author's)",
                         "This is a repair", out)
            check_eq(f"K7: {label} - the controller is unchanged", author_picture(art), before)
        exit_gate.all_errors = counted

        # K3: adversarial words stay refused (the record is stood in for; the judge is the real one)
        refused_rec = DV.Record("s5_precheck.py: [run_mapping run_mapping:TC-1:x] no run block", script="s5_precheck.py",
                                words="source", refused="family")
        passable = DV.Record("s5_precheck.py: [environment remedy-missing:TC-2] the stand row has no remedy",
                             script="s5_precheck.py")
        sourced = DV.Record("s5_precheck.py: [obligations o-1] a source-judged line", script="s5_precheck.py",
                            words="source")
        pipeline_path = art / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))

        def word(stage="S5", match="remedy-missing", decision="the person said go on", **extra):
            return dict({"stage": stage, "match": match, "decision": decision, "at": "2026-10-21T12:00:00"}, **extra)
        for label, record, rows, door in (
                ("a star over a refused-tag record", refused_rec, [word(match="*")], None),
                ("a word of another stage", passable, [word(stage="S4")], "waiver.py"),
                ("a revoked word", passable, [word(revoked_at="2026-10-21T13:00:00")], "waiver.py"),
                ("a word with an empty decision", passable, [word(decision="  ")], "waiver.py"),
                ("a named word over a source-judged line", sourced, [word(match="obligations")],
                 'waiver.py --task QA-G1 --stage S5 --block "*"')):
            pipeline["stage_overrides"] = rows
            pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
            records(record)
            code, out = finish_here("QA-G1")
            check_eq(f"K3[{label}]: still refused, exit 3", code, 3)
            check_eq(f"K3[{label}]: nothing was recorded", author_picture(art), before)
            if door:
                check_in(f"K3[{label}]: the door that opens is named", door, out)
        pipeline["stage_overrides"] = []
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        records(passable, refused_rec, sourced)
        code, out = finish_here("QA-G1")
        check_eq("K3: a mixed list is refused and every door is named once",
                 (code, out.count("waiver.py"), "refused` tag" in out, 'block "*"' in out), (3, 2, True, True))
        # the whole list is shown, and past the byte ceiling the file of this very call holds it (FR-37)
        records(*[DV.Record(f"s5_precheck.py: [environment e{i}] " + "x" * 60, script="s5_precheck.py")
                  for i in range(150)])
        code, out = finish_here("QA-G1")
        listing = art / "state/findings/s5-author-finish.txt"
        check_eq("K3: 150 long records: refused", code, 3)
        check("K3: past the ceiling the whole list is in the file the text names",
              listing.is_file() and listing.read_text(encoding="utf-8").count("\n- ") == 150 and "s5-author-finish.txt" in out,
              out[-400:])
        exit_gate.detector_errors = real_errors

        # K5: a declared, undecided halt is the halt road's; the gate is not read; the text is today's
        form.parent.mkdir(parents=True, exist_ok=True)
        form.write_text("header:\n  verdict: halt\nblocked:\n  field: x\n  problem: the factory refused my run\n",
                        encoding="utf-8")
        calls["all_errors"] = 0
        code, out = finish_here("QA-G1")
        check_eq("K5/M3: an undecided halt - exit 2 and the gate is not read", (code, calls["all_errors"]), (2, 0))
        check_in("K5: the halt road's own text", "declared a halt", out)
        real_gate = story_step._finish_gate
        story_step._finish_gate = lambda *_a: (0, "", [])
        try:
            disabled = finish_here("QA-G1")
        finally:
            story_step._finish_gate = real_gate
        check_eq("K5: byte-identical to the same call with the reader disabled", (code, out), disabled)
        check_eq("K5: and nothing was recorded", author_picture(art), before)
        # (the person's DECIDED halt is in `gate_reads_by_data_checks`: S5 has no `decide` door for a halt, R15)
        form.unlink()

        # K2: the person's recorded word passes a passable line; ONE note says so
        art2 = author_story(root, "QA-G2")
        receipt_g2 = host / "agent-s5-author-g2.json"
        bind_receipt(receipt_g2, "QA-G2")
        check_eq("F7: all the refusals above left the first receipt `running`", receipt_status(receipt_file), "running")
        records(DV.Record("s5_precheck.py: [environment remedy-missing:TC-2] the stand row has no remedy",
                          script="s5_precheck.py"))
        code, out = finish_here("QA-G2")
        check_eq("K2: before the word - refused", code, 3)
        check_eq("K2/F7: and its receipt is `running`", receipt_status(receipt_g2), "running")
        check_in("K2: and the door is the waiver, by a part only that line holds",
                 'waiver.py --task QA-G2 --stage S5 --block "<a part only that line holds>"', out)
        words = root / "words-gw18.txt"
        words.write_text("go on without the remedy: the stand row is the person's to fix", encoding="utf-8")
        recorded = harness.run_script("waiver.py", "--task", "QA-G2", "--stage", "S5", "--block", "remedy-missing:TC-2",
                                      "--words-file", str(words), cwd=root, env=env)
        check_eq("K2: the door opens (the waiver records the word)", recorded.returncode, 0)
        code, out = finish_here("QA-G2")
        check_eq("K2: after the word - accepted", code, 0)
        check_in("K2: said", "accepted s5-author", out)
        notes = [line for line in out.splitlines() if "passed by the person's recorded word" in line]
        check_eq("K2: exactly one note says the pass", len(notes), 1)
        check_in("K2: and it carries the line and the person's words", "go on without the remedy", notes[0])
        check_in("K2: and the line", "remedy-missing", notes[0])
        check_eq("K2: the dispatch is accepted", author_picture_of(art2, "s5-author")[1], "accepted")
        check_eq("K2/F7 control: an accept DOES release the receipt (so a `running` one above is a real result)",
                 receipt_status(receipt_g2), "terminal")
        # the pause door the refusal names is a command the conductor can run
        art3 = author_story(root, "QA-G3")
        paused = harness.run_script("story_step.py", "pause", "--task", "QA-G3", "--dispatch-id", "s5-author",
                                    "--reason", "the precheck refuses it", "--status", "blocked", cwd=root, env=env)
        check_eq("FR-2: the author road's `pause` door opens", paused.returncode, 0)
        check_eq("FR-2: and the story is unchanged by the refusal that named it", art3.is_dir(), True)
    finally:
        exit_gate.detector_errors, exit_gate.all_errors = real_errors, real_all
        harness.cleanup(root)


def gate_reads_by_data_checks() -> None:
    """K9 (the class by data) and K10 (one reader). KILLS M7 (the membership from a literal list): the third case adds a
    `detectors` entry to an in-memory stage model, and only a read of that data reads the runner."""
    import copy
    import argparse
    import contextlib
    import io
    import detector_verdict as DV
    import exit_gate
    import stage_guard
    root = harness.temp_project("qa-gw18-data-")
    seen = []

    class Stop(Exception):
        pass

    class OneDispatch:
        def __init__(self, _root, wait_seconds=0.0):
            pass

        def state(self):
            return {"dispatches": {"d1": {"stage": self.stage, "role": self.role}}}

        def prepare(self, options):
            raise Stop()
    saved = {name: getattr(story_step, name) for name in
             ("Controller", "_task_root", "_handoff_check", "_evidence", "_role_receipts")}
    saved_all, saved_model = exit_gate.all_errors, stage_guard.stage_model
    task_root = root / "qa-factory/artifacts/QA-K9"
    task_root.mkdir(parents=True)
    story_step.Controller, story_step._task_root = OneDispatch, lambda _task: task_root
    story_step._handoff_check = lambda *_a: ("green", "", "")
    story_step._evidence, story_step._role_receipts = (lambda *_a: ["work/x.json"]), (lambda *_a: [])

    def read(role, stage):
        OneDispatch.stage, OneDispatch.role = stage, role
        seen.clear()

        def fake(agent, task, digest="", facts_text=""):
            seen.append((agent, task, digest))
            return [DV.Record(f"{agent}: a finding")], []
        exit_gate.all_errors = fake
        ns = argparse.Namespace(task="QA-K9", dispatch_id="d1", digest="d", output=None, not_complete=False,
                                complete=False, ignore_handoff=False, window=None, unresolved=None, reason=None)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = story_step.finish(ns)
        except Stop:
            code = "reached the controller"
        return code, out.getvalue()
    try:
        for role, stage in (("qa-requirements-tester", "S2"), ("qa-test-strategist", "S3"), ("qa-case-critic", "S4"),
                            ("qa-automator", "S5"), ("qa-doc-scribe", "S8")):
            code, out = read(role, stage)
            check_eq(f"K9[{role}]: the gate is read (with the story, and an empty digest) and refuses",
                     (code, seen), (3, [(role, "QA-K9", "")]))
        for role, stage in (("qa-runner", "S6"), ("qa-code-critic", "S5"), ("qa-scout", "S1")):
            code, out = read(role, stage)
            check_eq(f"K9[{role}]: a role whose stage declares no detectors is not read and nothing is added",
                     (code, seen, out), ("reached the controller", [], ""))
        # K5: a halt the person DECIDED is not refused a second time and its skip is a note (S3 closes with its strategist,
        # so `decide --close` is its door; the record is the one `decide` writes)
        (task_root / "work/handoffs").mkdir(parents=True)
        (task_root / "work/handoffs/d1.yaml").write_text("header:\n  verdict: halt\n", encoding="utf-8")
        (task_root / "state/decisions").mkdir(parents=True)
        (task_root / "state/decisions/d1.json").write_text(json.dumps(
            {"close": {"at": "2026-10-21T12:00:00", "words_ref": "state/words/w.txt"}}), encoding="utf-8")
        code, out = read("qa-test-strategist", "S3")
        check_eq("K5: a decided halt reaches the controller and the gate is not read", (code, seen),
                 ("reached the controller", []))
        decided = story_step._decision_of(task_root, "d1")
        ns = argparse.Namespace(task="QA-K9", dispatch_id="d1", digest="d")
        note = story_step._finish_gate(ns, task_root, {"role": "qa-test-strategist", "stage": "S3"}, decided)
        check_eq("K5: the skip is a note, never silent", note, (0, "", [
            "the exit gate was not re-read: the person's recorded decision (close, 2026-10-21T12:00:00) stands for this "
            "dispatch"]))
        # F1 (fix round): the decision lifts the read WITHOUT a halt too - the form is gone, the record stays
        (task_root / "work/handoffs/d1.yaml").unlink()
        code, out = read("qa-test-strategist", "S3")
        check_eq("F1: a recorded `close` and NO halt - the gate is not read", (code, seen), ("reached the controller", []))
        (task_root / "state/decisions/d1.json").write_text(json.dumps(
            {"open_work": {"at": "2026-10-21T12:05:00", "unresolved": ["R-1"], "words_ref": "state/words/w.txt"}}),
            encoding="utf-8")
        code, out = read("qa-test-strategist", "S3")
        check_eq("F1: a recorded `open_work` and NO halt - the gate is not read", (code, seen), ("reached the controller", []))
        check_eq("F1: and the skip names the decision kind",
                 story_step._finish_gate(ns, task_root, {"role": "qa-test-strategist", "stage": "S3"},
                                         story_step._decision_of(task_root, "d1"))[2],
                 ["the exit gate was not re-read: the person's recorded decision (open_work, 2026-10-21T12:05:00) stands "
                  "for this dispatch"])
        (task_root / "state/decisions/d1.json").write_text(json.dumps({"hand": {"at": "x"}}), encoding="utf-8")
        code, out = read("qa-test-strategist", "S3")
        check_eq("F1: a decision that is neither `close` nor `open_work` (a `hand` record) lifts nothing",
                 (code, seen), (3, [("qa-test-strategist", "QA-K9", "")]))
        (task_root / "state/decisions/d1.json").unlink()
        model = copy.deepcopy(stage_guard.stage_model())
        next(s for s in model["stages"] if s["id"] == "S6").setdefault("detectors", {})["qa-runner"] = ["x_detector.py"]
        stage_guard.stage_model = lambda: model
        code, out = read("qa-runner", "S6")
        check_eq("K9/M7: a `detectors` entry added to the stage data makes that role read, with no Python edit",
                 (code, [s[0] for s in seen]), (3, ["qa-runner"]))
    finally:
        exit_gate.all_errors, stage_guard.stage_model = saved_all, saved_model
        for name, value in saved.items():
            setattr(story_step, name, value)
        harness.cleanup(root)
    # K10: AR-13 - the fuse's files and the hook's receipts have ONE reader, and it is not `finish`'s module
    text = (harness.SCRIPTS / "story_step.py").read_text(encoding="utf-8")
    gate = (harness.SCRIPTS / "exit_gate.py").read_text(encoding="utf-8")
    for token in ("exit_gate_blocks", "handoff_incomplete", "gate_receipt"):
        check(f"K10: story_step.py never reads `{token}`", token not in text)
    check("K10 control: the same scan finds the fuse's file in exit_gate.py", "exit_gate_blocks" in gate)
    check("K10: the one reader `finish` calls is the driver's function", "exit_gate.all_errors(role, args.task" in text)
    # F4 / F5 (fix round): the record-class rule and the render-and-save have ONE home each, and `finish` calls them
    check_eq("F4: `word_class` is defined once, in exit_gate.py, and not in story_step.py",
             (gate.count("def word_class"), text.count("def word_class")), (1, 0))
    check("F4: story_step.py holds no second copy of the three predicates (`unmigrated`, `.words`, `.refused`)",
          not any(token in text for token in ('"unmigrated"', '"words", "gate"', '"refused", ""')))
    import inspect
    refusal_source = inspect.getsource(story_step._gate_refusal)
    check("F4: `_gate_refusal` asks `exit_gate.word_class`", "exit_gate.word_class(" in refusal_source)
    check("F5: `_gate_refusal` calls `exit_gate.render_saved` and holds no `DV.render(` or unlink of its own",
          "exit_gate.render_saved(" in refusal_source and "DV.render(" not in refusal_source
          and ".unlink(" not in refusal_source)
    check_eq("F5: the old private name stays as an alias for one release",
             exit_gate._render_saved is exit_gate.render_saved, True)
    for label, fields, expected in (
            ("a refused tag is first, over `words=source`", dict(words="source", refused="family"), "refused"),
            ("a source-judged record", dict(words="source"), "star"),
            ("an unmigrated record", dict(kind="unmigrated"), "star"),
            ("a plain finding", dict(), "named"),
            ("a defect", dict(kind="defect"), "named")):
        check_eq(f"F4: word_class - {label}", exit_gate.word_class(DV.Record("x: a finding", script="x.py", **fields)),
                 expected)


def gate_decision_door_checks() -> None:
    """GW1-8 fix round F1 (P13, FR-7, FR-9): the person's recorded `decide --open/--close` on THIS dispatch is carried
    through `finish` whatever the case files hold - T5/T5c in `open_close_checks` are the positive proof on the INVALID
    case text "the case"; this is the NEGATIVE side and the edges. KILLS the mutant «skip the gate when the decision file
    is absent» (N1 reads exit 0), and any reading of a decision of ANOTHER dispatch (N2) or of an unreadable file (N3)."""
    from controller import Controller
    root = harness.temp_project("qa-gw18-decision-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))

    def picture(art: Path) -> tuple:
        state = Controller(art).state()
        return state["revision"], state["dispatches"]["s4-critic"]["status"]
    try:
        harness.use_project(root)
        art = s4_story(root, "QA-D1")           # the case file is the invalid text "the case"
        before = picture(art)
        done = finish_s4(root, env, "QA-D1", "--complete")
        check_eq("F1/N1: the invalid S4 case and NO decision record - refused, exit 3", done.returncode, 3)
        check_in("F1/N1: by the exit gate, naming what is wrong with the case", "no YAML frontmatter", done.stdout)
        check_in("F1/N1: and saying that nothing was recorded", "nothing was recorded", done.stdout)
        check_eq("F1/N1: the controller's revision and the dispatch are unchanged", picture(art), before)
        # N2: a decision recorded for ANOTHER dispatch id lifts nothing here
        decisions = art / "state/decisions"
        decisions.mkdir(parents=True)
        (decisions / "s4-other.json").write_text(json.dumps(
            {"close": {"at": "2026-10-21T12:00:00", "words_ref": "state/words/w.txt"}}), encoding="utf-8")
        other = finish_s4(root, env, "QA-D1", "--complete")
        check_eq("F1/N2: a decision record of ANOTHER dispatch does not lift the gate - exit 3, nothing recorded",
                 (other.returncode, picture(art)), (3, before))
        # N3: this dispatch's record cannot be read -> no decision (the gate runs, the reader says so)
        (decisions / "s4-critic.json").write_text("{not json", encoding="utf-8")
        broken = finish_s4(root, env, "QA-D1", "--complete")
        check_eq("F1/N3: an unreadable decision file is no decision - the gate runs, exit 3, nothing recorded",
                 (broken.returncode, picture(art)), (3, before))
        check_in("F1/N3: and the reader says it could not read it", "could not be read", broken.stdout)
        # control: the same story shape with the decision really recorded by the door - accepted, the skip said
        for ticket, form, kind in (("QA-D2", ["--close"], "close"), ("QA-D3", ["--open", "TC-1"], "open_work")):
            art = s4_story(root, ticket)
            made = run_decide(root, env, ticket, form, text="The person decides this.", dispatch="s4-critic")
            check_eq(f"F1 control: `decide {form[0]}` records the decision", made.returncode, 0)
            done = finish_s4(root, env, ticket, "--complete")
            check_eq(f"F1 control: with `{kind}` recorded the invalid case is accepted",
                     Controller(art).state()["dispatches"]["s4-critic"]["status"], "accepted")
            check_in(f"F1 control: and the skip is said, naming the kind ({kind})",
                     f"the exit gate was not re-read: the person's recorded decision ({kind}, ", done.stdout)
    finally:
        harness.cleanup(root)


def gate_fail_open_pins() -> None:
    """GW1-8 section 4: the fail-open paths the reused gate still has, pinned so that a later change is SEEN. At `finish`
    they stay as they are (F-5 a): each is named in the handoff (F-8 a, the guess at `finish`, is closed by GW1-10)."""
    import inspect
    import exit_gate
    import s5_precheck
    root = harness.temp_project("qa-gw18-open-")
    try:
        harness.use_project(root)
        author_story(root, "QA-F1")
        real = s5_precheck.run

        def crash(*_a, **_kw):
            raise RuntimeError("the check broke")
        s5_precheck.run = crash
        try:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = s5_precheck.detector_main()
        finally:
            s5_precheck.run = real
        # RH1-5 flipped this pin: a crash inside the precheck is the third state of a detector (exit 3 and one
        # `UNREADABLE:` line), which `finish` refuses by exit 2 (test_finish_unreadable.py) - no longer a pass.
        check_eq("fail-open 1 (flipped, RH1-5): a crash inside the S5 precheck is exit 3, the third state - not a pass", code, 3)
        check_in("fail-open 1 (flipped): ...printed as the one `UNREADABLE: ` line, with the reason", "UNREADABLE: s5_precheck could not complete", out.getvalue())
        check_eq("fail-open 2: a missing witness artifact is no finding", exit_gate.witness_errors("qa-automator", "QA-NONE"), [])
        # RH1-5 (N6) added the optional `task`; GW1-10 gives it a second job: the gate NAMES that story to the detector
        # it starts (`QA_FACTORY_DETECTOR_STORY`, `exit_gate._detector_env`). The signature stays as it was.
        check_eq("fail-open 3 (flipped, GW1-10): the signature of `detector_errors` stays (agent, task); the naming itself is pinned by test_detector_named_story.py",
                 list(inspect.signature(exit_gate.detector_errors).parameters), ["agent", "task"])
        check_eq("fail-open 3: ...and `task` is optional (a bare call still works, and then the detector guesses)",
                 exit_gate.detector_errors.__defaults__, ("",))
        # The two-story behaviour (A red, B newer and clean) moved to test_detector_named_story.py, keys G1 and G2: the
        # false pass this pin used to record (F-8 a) is closed there.
    finally:
        harness.cleanup(root)


def main() -> None:
    finish_exit_gate_checks()
    gate_reads_by_data_checks()
    gate_decision_door_checks()
    gate_fail_open_pins()
    harness.finish("test_story_step_gate")


if __name__ == "__main__":
    main()
