#!/usr/bin/env python3
"""story_step.py `start`, `bind` and the first `finish`: the stop markers, the judge seams, the host receipt, the probe debt settled
in `start` (B-207 P6-B), the launch answer asked once, and the S5 window record passed at completion.

Nothing here reaches the network: `judge._post` is replaced by a table transport exactly as test_judge.py does, and the judge
scripts the other packages own are not required to exist - that is the point of one of the checks.
Split off test_story_step.py (TQ1-10); the helpers are in story_step_common.py.
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
from host_dispatch import binding_names, binding_path, bound_dispatches  # noqa: E402
from story_step_common import (  # noqa: E402
    CONFIG_FIELD,
    FakeController,
    dispatch_record,
    open_story,
    seed,
    set_pipeline_block,
    sha256_of,
)


def path_bind_checks(root: Path, env: dict) -> None:
    """CX1-9: `bind` of a host agent PATH writes the names `host_dispatch.record` writes, so a follow-up
    addressed by the bare name finds the receipt as well as one addressed by the path."""
    agent = "/root/qa_scout__qa_recip"
    open_story(root, env, "QA-RECIP")
    harness.run_script("story_step.py", "start", "--task", "QA-RECIP", "--stage", "S1", "--role",
                       "qa-scout", cwd=root, env=env)
    bound = harness.run_script("story_step.py", "bind", "--task", "QA-RECIP", "--dispatch-id",
                               "S1-qa-scout-1", "--agent-id", agent, cwd=root, env=env)
    check_in("bind accepts a host agent path", f"bound S1-qa-scout-1 to agent {agent}", bound.stdout)
    path = binding_path(root, agent)
    check("and the receipt is hashed by the full path", path.is_file(), str(path))
    receipt = json.loads(path.read_text(encoding="utf-8"))
    check_eq("task_name is the last component, task_path the path itself",
             (receipt["agent_id"], receipt["task_name"], receipt["task_path"]),
             (agent, "qa_scout__qa_recip", agent))
    check_eq("so the receipt answers to the path and to the bare name",
             binding_names(receipt), {agent, "qa_scout__qa_recip"})


# --- B-207 P6-B (R13, V1): the probe debt is settled inside `start` ---------------------------------

DEBT_REL = "work/probe-debt.json"   # the carrier probe_debt.py writes: a contract, so spelled out here


def run_start(task: Path, stage: str, role: str, settle, clock=None):
    """`start` in this process, with the controller and every subprocess replaced: what is recorded is
    the ORDER of the calls, which is what the position invariant is about. `settle(args)` answers the
    probe_debt.py call with (code, output), or raises. No real probe_debt.py --settle is ever started."""
    import argparse
    import contextlib
    import io
    log = []

    class StartController:
        def __init__(self, _root, wait_seconds=0.0):
            pass

        def state(self):
            return {"dispatches": {}, "revision": 1}

        def prepare(self, options):
            log.append("prepare")
            return {"dispatch_request": {"id": options["id"], "stage": options["stage"], "role": options["role"]}}

        def apply(self, operation, _request):
            log.append("apply " + operation)

    def fake_run(script, *args):
        log.append((script,) + args if script == "probe_debt.py" else script)
        return settle(args) if script == "probe_debt.py" else (0, "")

    saved = (story_step._run, story_step.Controller, story_step._settle_clock)
    story_step._run, story_step.Controller = fake_run, StartController
    if clock is not None:
        story_step._settle_clock = clock
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            try:
                code = story_step.start(argparse.Namespace(task=task.name, stage=stage, role=role, id=None,
                                                           scope=None, purpose=None, execution_kind=""))
            except Exception as exc:   # a start that raises is a finding of the check on its exit, not a crash
                code = f"raised {type(exc).__name__}: {exc}"
    finally:
        story_step._run, story_step.Controller, story_step._settle_clock = saved
    return code, out.getvalue(), log


def names_of(log: list) -> list:
    return [entry[0] if isinstance(entry, tuple) else entry for entry in log]


def ticking(*values):
    """A clock that answers the given readings in order: the settle's duration without a real wait. The
    last reading repeats, so a call that reads the clock more often than expected fails a check on what it
    did, not with a bare IndexError."""
    readings = list(values)
    return lambda: readings.pop(0) if len(readings) > 1 else readings[0]


def probe_debt_settle_checks(root: Path) -> None:
    ticket = "QA-P"
    task = seed(root, ticket)
    debt = task / DEBT_REL
    line = f"qa-factory/artifacts/{ticket}/{DEBT_REL}"
    owed = {"outcomes": [{"instance_id": "i-1", "step": "probe", "result": "unpublished", "words": "w"}],
            "left": [{"instance_id": "i-1", "reason": "critic", "command": "probe_by_code.py --task QA-P"}],
            "info": []}

    def settle_writing(doc, exit_code=0):
        def settle(_args):
            debt.parent.mkdir(parents=True, exist_ok=True)
            # probe_debt stamps the dispatch it settled for; a fixture that names none says so on purpose
            stamped = doc if isinstance(doc, str) else json.dumps(dict({"dispatch": "S5-qa-code-critic-1"}, **doc))
            debt.write_text(stamped, encoding="utf-8")
            return exit_code, "probe debt settle: 1 step(s), 1 left for the critic, 0 info row(s)"
        return settle

    def nothing_found(_args):
        return 0, ""

    def fresh():
        if debt.exists():
            debt.unlink()

    # R13 position: after apply("dispatch"), before the brief and the prompt. The invariant: the probes
    # need a REGISTERED critic dispatch, and the critic sees what is left over.
    fresh()
    # 12.5 s of the start's budget are gone when the settle begins (readings: top of start, settle
    # begins, settle ends): the settle is handed what is LEFT of probe_debt's 90 s, never the 90 s.
    code, out, log = run_start(task, "S5", "qa-code-critic", settle_writing(owed),
                               clock=ticking(100.0, 112.5, 113.0))
    names = names_of(log)
    check_eq("settle: the critic's start goes through", code, 0)
    check_eq("settle: probe_debt --settle runs exactly once", names.count("probe_debt.py"), 1)
    check("settle: after the dispatch is registered (the probes need it: probe_by_code.py:1200)",
          names.index("apply dispatch") < names.index("probe_debt.py"), str(names))
    check("settle: before the brief is built", names.index("probe_debt.py") < names.index("brief_pack.py"),
          str(names))
    check_eq("settle: with the task, the settle flag, the dispatch it just registered and what is left of the budget",
             log[names.index("probe_debt.py")],
             ("probe_debt.py", "--task", ticket, "--settle", "--dispatch", "S5-qa-code-critic-1",
              "--budget-s", "77.5"))
    import probe_debt
    check_eq("settle: the budget it is taken from is probe_debt's own, about 90 s", probe_debt.SETTLE_BUDGET_S, 90)
    inputs = out.partition("Inputs:")[2].partition("Return your digest line only.")[0]
    check_in("settle: what is left over is an input of the prompt", line, inputs)
    check_not_in("settle: a clean settle adds no note about itself", "note: probe_debt", out)
    # the door for a window the critic cannot close is named once, on the critic's own next-step line
    check_eq("door: the critic's start names --unresolved once", out.count("--unresolved"), 1)
    check_in("door: on the line that names finish", '--digest "<digest>" (or, for a window the critic could '
             'not close: finish --unresolved <why> --reason "<words>"; or, for a critic that cannot judge because its '
             'author\'s work is defective: finish --needs-author <cases> --reason "<words>") ---', out)      # HF8-15: the second door

    # edge ii/iii: absent, or present but saying nothing, is not an input (and absent says nothing)
    fresh()
    code, out, log = run_start(task, "S5", "qa-code-critic", nothing_found)
    check_eq("edge ii: no debt file - the start goes through", code, 0)
    check_not_in("edge ii: and the prompt names none", "probe-debt.json", out)
    check_not_in("edge ii: and there is no note about it", "note: probe_debt", out)
    for label, doc in (("empty lists", {"outcomes": [], "left": [], "info": []}),
                       ("only info rows", {"outcomes": [], "left": [], "info": [{"instance_id": "i-2", "why": "x"}]}),
                       ("an empty object", {})):
        fresh()
        code, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing(doc))
        check_not_in(f"edge iii: {label} - not an input", "probe-debt.json", out)
    fresh()
    _, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing({"outcomes": owed["outcomes"], "left": []}))
    check_in("edge iii: outcomes alone are enough to be an input", line, out)
    fresh()
    _, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing({"outcomes": [], "left": owed["left"]}))
    check_in("edge iii: left alone is enough to be an input", line, out)
    for label, text in (("not JSON", "{not json"), ("a list", "[1, 2]")):
        fresh()
        code, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing(text))
        check_eq(f"edge iii: a debt file that is {label} does not stop the start", code, 0)
        check_not_in(f"edge iii: {label} - not given to the critic", line, out)
        check_in(f"edge iii: {label} - told, never taken for nothing owed", f"note: {DEBT_REL}", out)

    # a file written for ANOTHER dispatch is never given to this critic (its commands name a dispatch that
    # is not open any more): a note instead - whether the settle succeeded, failed, or was not run at all
    stale = dict(owed, dispatch="S5-qa-code-critic-0")
    for label, settle, clock in (
            ("the settle wrote nothing", lambda _a: (0, ""), None),
            ("the settle failed", lambda _a: (2, "boom"), None),
            ("the settle was not run", lambda _a: (0, ""), ticking(0.0, 95.0))):
        fresh()
        debt.parent.mkdir(parents=True, exist_ok=True)
        debt.write_text(json.dumps(stale), encoding="utf-8")
        code, out, _ = run_start(task, "S5", "qa-code-critic", settle, clock=clock)
        check_eq(f"stale: {label} - the start goes through", code, 0)
        check_not_in(f"stale: {label} - the old file is not an input", line, out.partition("Inputs:")[2]
                     .partition("Return your digest line only.")[0])
        check_in(f"stale: {label} - a note names both dispatches",
                 "was written for dispatch S5-qa-code-critic-0, not for S5-qa-code-critic-1", out)
    fresh()
    debt.parent.mkdir(parents=True, exist_ok=True)
    debt.write_text(json.dumps({k: v for k, v in owed.items()}), encoding="utf-8")   # names no dispatch
    _, out, _ = run_start(task, "S5", "qa-code-critic", nothing_found)
    check_in("stale: a file naming no dispatch is not given either", "(none named)", out)
    fresh()
    debt.parent.mkdir(parents=True, exist_ok=True)
    debt.write_text(json.dumps({"dispatch": "S5-qa-code-critic-0", "outcomes": [], "left": []}), encoding="utf-8")
    _, out, _ = run_start(task, "S5", "qa-code-critic", nothing_found)
    check_not_in("stale: an empty file of another dispatch says nothing (nothing is owed)", "was written for", out)
    # this settle's own file, stamped with this dispatch, is given
    fresh()
    _, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing(owed))
    check_in("stale: a file stamped with THIS dispatch is given", line, out)

    # P2-2 start_reports_settle_not_run_when_nothing_changed: the settle re-addressed the file and started nothing
    fresh()
    code, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing(dict(owed, unchanged_since="S5-qa-code-critic-0")))
    check_eq("start_reports_settle_not_run_when_nothing_changed: the start goes through", code, 0)
    check_in("start_reports_settle_not_run_when_nothing_changed: one note names the dispatch it stood on",
             "note: probe_debt --settle: nothing changed since S5-qa-code-critic-0, not run", out)
    check_in("...and the debt is still an input", line, out)
    reasons = sorted({str(l.get("reason")) for l in owed["left"] if l.get("reason")})
    check("F10a: the owed fixture has a reason to name", bool(reasons), str(owed["left"]))
    check_in("F10a: the note says why each item stays as it was (the reasons it was left for)",
             "(each item stays as it was left: " + ", ".join(reasons) + ")", out)
    fresh()
    _, out, _ = run_start(task, "S5", "qa-code-critic", settle_writing(owed))
    check_not_in("a settle that ran says nothing of the kind", "nothing changed since", out)

    # edge i: the settle fails - a note, and the critic still starts (P1)
    fresh()
    code, out, log = run_start(task, "S5", "qa-code-critic",
                               lambda _a: (2, "probe_debt: --dispatch 'x' is not an open S5 dispatch\nsecond line"))
    check_eq("edge i: a settle that exits non-zero does not stop the start", code, 0)
    check_in("edge i: it is one note with the exit code and the last line",
             "note: probe_debt --settle did not finish (exit 2: second line)", out)
    check_in("edge i: the note names the read-only command for the debt", "probe_debt.py --task QA-P", out)
    check_in("edge i: the prompt is still printed", "--- Agent prompt, verbatim; subagent_type: qa-code-critic ---", out)
    check("edge i: and the brief is still built after it", "brief_pack.py" in names_of(log))

    def crash(_args):
        raise OSError("python is gone")
    code, out, log = run_start(task, "S5", "qa-code-critic", crash)
    check_eq("edge i: a settle that cannot even start does not stop the start", code, 0)
    check_in("edge i: and says it did not run", "did not finish (did not run: OSError: python is gone)", out)
    check_in("edge i: the dispatch is reported", "dispatched S5-qa-code-critic-1", out)

    # edge iv: a start the mode switch refuses runs no probe - and registers nothing
    refused = seed(root, "QA-R")
    pipeline = json.loads((refused / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["run_mode"] = {"mode": "driver", "plugin_root": "x", "plugin_version": "0", "since": "t"}
    (refused / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    saved_mode = os.environ.get(story_step.RUN_MODE_ENV)
    os.environ[story_step.RUN_MODE_ENV] = "desktop"
    try:
        calls = []
        code, out, log = run_start(refused, "S5", "qa-code-critic", lambda a: (calls.append(a), (0, ""))[1])
    finally:
        if saved_mode is None:
            os.environ.pop(story_step.RUN_MODE_ENV, None)
        else:
            os.environ[story_step.RUN_MODE_ENV] = saved_mode
    check_eq("edge iv: a start refused by the mode switch exits 2", code, 2)
    check_in("edge iv: with the refusal", "mode switch", out)
    check_eq("edge iv: no probe was run", calls, [])
    check_eq("edge iv: nothing was registered or run at all", log, [])

    # edge v: only the S5 code critic settles
    for stage, role in (("S5", "qa-automator"), ("S1", "qa-scout"), ("S4", "qa-case-critic")):
        calls = []
        code, out, log = run_start(task, stage, role, lambda a: (calls.append(a), (0, ""))[1])
        check_eq(f"edge v: {stage} {role} - the start goes through", code, 0)
        check_not_in(f"edge v: {stage} {role} - no probe_debt run", "probe_debt.py", names_of(log))
        check_not_in(f"edge v: {stage} {role} - the finish line does not mention the unresolved door",
                     "--unresolved", out)
    saved_run = story_step._run
    story_step._run = lambda *_a: (_ for _ in ()).throw(AssertionError("the settle ran"))
    try:
        check_eq("edge v: the stage is checked as well as the role",
                 story_step._settle_probe_debt("QA-P", "S1", "qa-code-critic", "d", task, 0.0), ([], []))
    finally:
        story_step._run = saved_run

    # edge x: `start` SAYS that the settle was slow (over 60 s); the budget itself is kept by probe_debt
    for label, seconds, told in (("at the limit", 60, False), ("just over it", 60.1, True),
                                 ("well over it", 119.4, True), ("fast", 0.2, False)):
        fresh()
        _, out, _ = run_start(task, "S5", "qa-code-critic", nothing_found,
                              clock=ticking(10.0, 10.0, 10.0 + seconds))
        if told:
            check_in(f"edge x: {label} - the note says how long it took", f"took {seconds:.1f} s", out)
        else:
            check_not_in(f"edge x: {label} - no note", "took", out)
    _, out, _ = run_start(task, "S5", "qa-code-critic", lambda _a: (2, "boom"), clock=ticking(0.0, 0.0, 75.0))
    check_in("edge x: a slow AND failing settle says both", "did not finish (exit 2: boom)", out)
    check_in("edge x: and how long it took", "took 75.0 s", out)
    fresh()

    # V1 (critic of B-207): the budget bounds the WHOLE start. The settle gets what is left of it, at
    # the top of `start` (nothing used: all of it), and is not started at all when less than a second is
    # left - the probes then are the critic's own work, and the note says so.
    for label, used, given in (("nothing used", 0.0, "90.0"), ("one second left", 89.0, "1.0"),
                               ("a fraction used", 0.04, "90.0"), ("most of it used", 89.5, None),
                               ("exactly all of it used", 90.0, None), ("more than all of it", 240.0, None)):
        calls = []
        _, out, log = run_start(task, "S5", "qa-code-critic", lambda a: (calls.append(a), (0, ""))[1],
                                clock=ticking(50.0, 50.0 + used, 50.0 + used))
        if given is not None:
            check_eq(f"budget: {label} - the settle is given {given} s", calls[0][-2:], ("--budget-s", given))
        else:
            check_eq(f"budget: {label} - the settle is not started", calls, [])
            check_in(f"budget: {label} - and the note says how much of the budget the start had used",
                     "probe_debt --settle was not run: this start had already used", out)
            check_in(f"budget: {label} - the critic starts all the same", "dispatched S5-qa-code-critic-1", out)
    calls = []
    run_start(task, "S5", "qa-code-critic", lambda a: (calls.append(a), (0, ""))[1])
    check("budget: on the real clock the figure is a number of seconds, never above the 90",
          0 < float(calls[0][calls[0].index("--budget-s") + 1]) <= 90, str(calls))


# --- the `finish --unresolved --reason` door (the critic of B-194, before the trial run) -------------


def where_asks_for_the_launch_answer_once() -> None:
    """CX1-13 fix round (t-1126 F-2 + m-3): `where` calls `Controller.launch_answer` ONCE per invocation, also when it
    has just rebuilt the missing card (the liveness verdict - transcripts and rollouts - is read once), and returns
    the dict that call built, untouched. KILLS: `_launch_from_where` asking `launch_answer` a second time after
    `_rebuild_card` (the counters below read 2), or merging `liveness` / `evidence` into the answer itself (the
    sentinel dict comes back as another object). A desktop story, S1 `qa-scout` dispatched by a `start` whose scripts
    are stubbed, its card gone, the brief and the form on disk: the card layer has one thing to do - rebuild."""
    import argparse
    import contextlib
    import io
    import dispatch_liveness
    import launch_card
    from controller import Controller
    root = harness.temp_project("qa-step-where-once-")
    saved_run, saved_env = story_step._run, os.environ.pop(launch_card.RUN_MODE_ENV, None)
    try:
        harness.use_project(root)
        ticket = "QA-WO"
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        task = open_story(root, env, ticket)
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["run_mode"] = {"mode": "desktop"}
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        story_step._run = lambda _script, *_args: (0, "")
        with contextlib.redirect_stdout(io.StringIO()):
            code = story_step.start(argparse.Namespace(task=ticket, stage="S1", role="qa-scout", id=None, scope=None,
                                                       purpose=None, execution_kind=""))
        story_step._run = saved_run
        check_eq("start (scripts stubbed) registered the dispatch", code, 0)
        card = launch_card.card_path(task, "S1-qa-scout-1")
        card.unlink()
        (task / "work" / "briefs").mkdir(parents=True, exist_ok=True)
        (task / "work" / "briefs" / "S1-qa-scout-1.md").write_text("# Brief\n", encoding="utf-8")
        (task / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (task / "work" / "handoffs" / "S1-qa-scout-1.yaml").write_text("x: 1\n", encoding="utf-8")

        calls = {"launch_answer": 0, "liveness": 0}
        real_answer, real_state = Controller.launch_answer, dispatch_liveness.state

        def counted_answer(self, dispatch, rebuild=None):
            calls["launch_answer"] += 1
            return real_answer(self, dispatch, rebuild=rebuild)

        def counted_state(*args, **kwargs):
            calls["liveness"] += 1
            return real_state(*args, **kwargs)

        Controller.launch_answer, dispatch_liveness.state = counted_answer, counted_state
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                story_step.where(argparse.Namespace(task=ticket))
        finally:
            Controller.launch_answer, dispatch_liveness.state = real_answer, real_state
        nxt = json.loads(next(line for line in out.getvalue().splitlines() if line.startswith("next: "))[len("next: "):])
        check_eq("where rebuilt the card and answers launch", (nxt.get("action"), card.is_file()), ("launch", True))
        check_eq("`launch_answer` was asked once", calls["launch_answer"], 1)
        check_eq("and the liveness verdict (transcripts, rollouts) was taken once, rebuild or not", calls["liveness"], 1)
        check("the answer carries the verdict fields launch_answer put there", "liveness" in nxt and "evidence" in nxt, str(nxt))

        sentinel = {"action": "wait_start", "dispatch_id": "S1-qa-scout-1", "marker": object()}
        Controller.launch_answer = lambda self, dispatch, rebuild=None: (sentinel, {"state": "unknown", "evidence": []})
        try:
            controller = Controller(task)
            kept, _text = story_step._launch_from_where(ticket, task, controller,
                                                        controller._next_action_for_state(controller.state()))
        finally:
            Controller.launch_answer = real_answer
        check("`_launch_from_where` returns the dict `launch_answer` built, as it is (no second merge)", kept is sentinel)
    finally:
        story_step._run = saved_run
        if saved_env is not None:
            os.environ[launch_card.RUN_MODE_ENV] = saved_env
        harness.cleanup(root)


def diff_world_checks() -> None:
    """G1-5 fixture (spec t-527 section 4 item 8): `seed` records NO implementation source, so an S3 acceptance passes on it
    (`off_diff:absent`); `story_run_common.diff_world` is the helper for a test that needs a world `diff` with real bytes - the S3
    exit gate finds that table whole, and the same word with no table is the conductor's R0 (the refusal the bytes-less seed hit)."""
    import grounding_table as GT
    import story_run_common as SC
    root = harness.temp_project("qa-diff-world-")
    try:
        harness.use_project(root)
        task = seed(root, "QA-D1")
        check_eq("seed: no implementation source, no table -> the S3 exit gate finds nothing", GT.exit_findings(task, None, []), [])
        SC.diff_world(task)
        check_eq("diff_world: the word is diff, the diff has bytes, the table is there and clean",
                 (GT.source_state(task)[0], (task / "work" / "impl-diff.txt").stat().st_size > 0, GT.table_path(task).is_file(),
                  [f.rule for f in GT.exit_findings(task, None, [])]), ("diff", True, True, []))
        GT.table_path(task).unlink()
        check_eq("the same world with no table: R0 of the conductor (a diff and no table)",
                 [(f.rule, f.who) for f in GT.exit_findings(task, None, [])], [("R0", "conductor")])
    finally:
        harness.cleanup(root)


def main() -> None:
    diff_world_checks()
    # A script that has not landed in this build is a note, not a failure: the judge packages
    # ship one at a time and a story must run before the last of them does.
    code, out = story_step._run("judge_no_such_package.py", "--task-root", "x")
    check_eq("a missing judge script exits 0", code, 0)
    check_in("and says which one was skipped", "is not in this build", out)

    root = harness.temp_project("qa-story-step-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    try:
        harness.use_project(root)
        task = seed(root, "QA-9")

        # --- the stop markers -------------------------------------------------------
        set_pipeline_block(root, None)
        check_eq("no stop_after, no marker",
                 story_step._next(FakeController({"action": "prepare_stage", "stage": "S5"})),
                 {"action": "prepare_stage", "stage": "S5"})
        set_pipeline_block(root, "gate_A")
        gate = story_step._next(FakeController({"action": "await_gate", "gate": "A"}))
        check_eq("gate A is still presented under stop_after gate_A", gate.get("stop_after"), "gate_A")
        check_eq("and nothing after it runs",
                 story_step._next(FakeController({"action": "prepare_stage", "stage": "S5"}))["action"],
                 "stop")
        set_pipeline_block(root, "gate_B")
        check_eq("stop_after gate_B leaves S5 alone",
                 story_step._next(FakeController({"action": "prepare_stage", "stage": "S5"}))["action"],
                 "prepare_stage")
        gate_b = story_step._next(FakeController({"action": "await_gate", "gate": "B"}))
        check_eq("gate B is presented under stop_after gate_B", gate_b.get("stop_after"), "gate_B")
        check_eq("and S9 does not run after it",
                 story_step._next(FakeController({"action": "prepare_stage", "stage": "S9"}))["action"],
                 "stop")
        set_pipeline_block(root, "after_S3")
        check_not_in("an unknown marker is no marker at all",
                     "stop", json.dumps(story_step._next(
                         FakeController({"action": "prepare_stage", "stage": "S5"}))))
        set_pipeline_block(root, None)

        # --- a real dispatch, bound and finished -------------------------------------
        from controller import Controller
        harness.run_script("stage_done.py", "--task", "QA-9", "--stage", "S0", "--status", "done",
                           "--digest", "preflight green", cwd=root, env=env)
        Controller(task).apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                              "known_paths": {"root": str(task), "project_root": str(root)},
                                              "idempotency_key": "init"})
        started = harness.run_script("story_step.py", "start", "--task", "QA-9", "--stage", "S1",
                                     "--role", "qa-scout", cwd=root, env=env)
        check_in("start dispatches in one command", "dispatched S1-qa-scout-1", started.stdout)
        check_in("and names bind as the very next step", "story_step.py bind", started.stdout)
        check_in("judge off: the prompt says nothing about a judge", "Return your digest line only.",
                 started.stdout)
        check_not_in("nothing mentions a judge with provider none", "Judge:", started.stdout)
        # the handover form is part of the boundary now: written from the contract, named in
        # the prompt, and the role is told where a refusal about it goes (never to the person)
        form = task / "work" / "handoffs" / "S1-qa-scout-1.yaml"
        check("start writes the role's handover form", form.is_file(), started.stdout[-400:])
        check_in("and the prompt names it", "work/handoffs/S1-qa-scout-1.yaml", started.stdout)
        check_in("with the check that repairs what code can derive", "handoff_check.py",
                 started.stdout)
        check_in("and the way out that does not reach the person", "handoff_help.py",
                 started.stdout)
        text = form.read_text(encoding="utf-8")
        check_in("the form knows which contract it is", "contract: s1-scout-to-tester", text)
        check_in("and its header is already filled", "role: qa-scout", text)

        unknown = harness.run_script("story_step.py", "bind", "--task", "QA-9", "--dispatch-id",
                                     "S1-qa-scout-7", "--agent-id", "agent-x", cwd=root, env=env)
        check_in("bind refuses a dispatch this story does not have", "no dispatch", unknown.stdout)

        import time
        t0 = time.time()
        bound = harness.run_script("story_step.py", "bind", "--task", "QA-9", "--dispatch-id",
                                   "S1-qa-scout-1", "--agent-id", "agent-abc", cwd=root, env=env)
        t1 = time.time()
        check_in("bind records the agent", "bound S1-qa-scout-1 to agent agent-abc", bound.stdout)
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("the resume guard's own field is written",
                 pipeline["stages"]["S1"].get("agent_id"), "agent-abc")
        receipts = sorted((root / "qa-factory/state/host-dispatches").glob("*.json"))
        check_eq("and one host receipt exists for it", len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        check_eq("naming the dispatch it belongs to", receipt["dispatch_id"], "S1-qa-scout-1")
        bound_at = receipt.get("bound_at")
        check("and the moment it was launched, within the bind call",
              isinstance(bound_at, float) and t0 <= bound_at <= t1, repr((t0, bound_at, t1)))
        check_eq("with every key it had before kept, and the two names host_dispatch.record writes (DC1-11: and the list of bindings)",
                 sorted(k for k in receipt if k != "bound_at"),
                 ["agent_id", "agent_type", "bound_by", "bound_dispatches", "dispatch_id", "status", "task_id",
                  "task_name", "task_path"])      # `bound_dispatches`: host_dispatch.bound_dispatches, the one reader of the receipt's list
        check_eq("DC1-11: the list holds this one binding, read through host_dispatch.bound_dispatches",
                 [(b["task_id"], b["dispatch_id"]) for b in bound_dispatches(receipt)], [("QA-9", "S1-qa-scout-1")])
        check_eq("a bare agent id is its own task_name, and no path", (receipt["task_name"], receipt["task_path"]),
                 ("agent-abc", None))
        check_eq("and the file is still hashed by the full agent id", receipts[0], binding_path(root, "agent-abc"))
        import dispatch_liveness
        dispatch = Controller(task).state()["dispatches"]["S1-qa-scout-1"]
        check_eq("liveness can now prove the dispatch is running",
                 dispatch_liveness.state(root, "QA-9", dispatch)["state"], "alive")
        # CX1-13 (F-3 (a)): `bind` names the dispatch it binds to `stage_done`, and the controller's record names the agent
        check_eq("the dispatch record names the agent bind launched (it rode the stage transition's dispatch_id)",
                 dispatch.get("agent_id"), "agent-abc")
        check_eq("and the pipeline's stage entry holds the same id as before (`_project_pipeline` reads the dispatch)",
                 pipeline["stages"]["S1"].get("agent_id"), dispatch.get("agent_id"))
        from event_store import content_hash
        transition = [e for e in Controller(task).store.read() if e.get("type") == "stage_transition"][-1]
        identity = {key: transition["payload"][key] for key in ("task", "stage", "status", "role", "digest", "agent_id")}
        check_eq("M-3: the payload carries the dispatch id", transition["payload"].get("dispatch_id"), "S1-qa-scout-1")
        check("and the idempotency key is the one of the identity WITHOUT it (a retried bind across the upgrade finds it)",
              transition["idempotency_key"].startswith("stage:" + content_hash(identity)), transition["idempotency_key"])
        check_not_in("stage_done without --dispatch-id adds no such field to a payload",
                     "dispatch_id", json.dumps([e["payload"] for e in Controller(task).store.read()
                                                if e.get("type") == "stage_transition"][0]))

        for name in ("context-manifest.json", "context-bundle.json"):
            (task / "work" / name).write_text("{}", encoding="utf-8")
        # The form is the handover, and it is required by default: a role that ignored it
        # does not close a stage. This is what a story running under an older build meets,
        # and the refusal names both ways past it.
        refused = harness.run_script("story_step.py", "finish", "--task", "QA-9", "--dispatch-id",
                                     "S1-qa-scout-1", "--digest", "qa-scout S1 done - ok",
                                     cwd=root, env=env)
        check_eq("finish refuses an untouched handover form", refused.returncode, 3)
        check_in("naming the form", "S1-qa-scout-1.yaml", refused.stdout)
        check_in("and the way a running story passes it", "handoffs.required: false", refused.stdout)
        check_in("and the way one dispatch passes it", "--ignore-handoff", refused.stdout)
        ended = harness.run_script("story_step.py", "finish", "--task", "QA-9", "--dispatch-id",
                                   "S1-qa-scout-1", "--digest", "qa-scout S1 done - ok",
                                   "--ignore-handoff", cwd=root, env=env)
        check_in("finish accepts and closes the stage", "stage complete", ended.stdout)
        check_in("and says the judge is off", "judge: off", ended.stdout)
        check_eq("the host receipt is terminal again, so next waits for nobody",
                 json.loads(receipts[0].read_text(encoding="utf-8"))["status"], "terminal")
        check_eq("and releasing it keeps the launch time",
                 json.loads(receipts[0].read_text(encoding="utf-8")).get("bound_at"), bound_at)

        # --- release is scoped by story: dispatch ids repeat across stories -------------
        # Two stories both reach `S5-qa-automator-12`; finishing one must not mark the other's
        # receipt terminal, or `next` stops waiting for a worker that is still running.
        directory = root / "qa-factory/state/host-dispatches"
        fixtures = {"own": "QA-9", "foreign": "QA-OTHER", "no-story": None, "empty-story": ""}
        for name, owner in fixtures.items():
            (directory / f"{name}.json").write_text(json.dumps(
                {"agent_id": f"a-{name}", "agent_type": "qa-automator", "task_id": owner,
                 "dispatch_id": "S5-qa-automator-12", "status": "running",
                 "bound_by": "story_step"}, indent=2), encoding="utf-8")
        before = {name: (directory / f"{name}.json").read_bytes() for name in fixtures}
        real_binding = story_step._binding
        story_step._binding = lambda task_root: (None, root)
        try:
            story_step._release_binding(task, "S5-qa-automator-12", "QA-9")
        finally:
            story_step._binding = real_binding
        after = {name: json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
                 for name in fixtures}
        check_eq("release: this story's receipt becomes terminal", after["own"]["status"],
                 "terminal")
        check_eq("release: and says who released it", after["own"].get("terminal_source"),
                 "story_step")
        for name in ("foreign", "no-story", "empty-story"):
            check_eq(f"release: the {name} receipt of the same-named dispatch is untouched",
                     (directory / f"{name}.json").read_bytes(), before[name])
        for name in fixtures:
            (directory / f"{name}.json").unlink()

        # --- the boundary detector for config.json (B-193 R-A6) ------------------------
        check_eq("the S1 dispatch that started under an unchanged config says nothing about it",
                 [ln for ln in ended.stdout.splitlines() if "config.json" in ln], [])
        check_eq("and its record holds the hash it started with",
                 dispatch_record(task, "S1-qa-scout-1").get(CONFIG_FIELD),
                 sha256_of(root / "qa-factory/config.json"))
        path_bind_checks(root, env)

        # --- the probe debt is settled in `start` (B-207 P6-B) --------------
        probe_debt_settle_checks(root)

        # --- --complete: S8 closes on the scribe, not on the role that runs after gate B ---
        stages = story_step._stages()
        check_eq("S8's last role really is the one that runs after gate B",
                 stages["S8"]["roles"][-1], "qa-bug-reporter")

        class Args:
            not_complete = False
            complete = False
        role, last = "qa-doc-scribe", stages["S8"]["roles"][-1]
        check_eq("without the flag the scribe leaves S8 open",
                 not Args.not_complete and (Args.complete or role == last), False)
        Args.complete = True
        check_eq("with --complete the scribe closes it",
                 not Args.not_complete and (Args.complete or role == last), True)
        Args.not_complete = True
        check_eq("--not-complete still wins over it",
                 not Args.not_complete and (Args.complete or role == last), False)

        # --- guidance exists for every role of S5-S9 that has a judge file --------------
        for role in ("qa-automator", "qa-code-critic", "qa-runner", "qa-failure-analyst",
                     "qa-bug-reporter", "qa-retro-analyst"):
            check(f"{role} is told what its judge file is for", role in story_step.JUDGE_GUIDANCE)
        check("the code critic's pre-work is registered",
              "judge_code.py" in [item[0] for item in story_step.PRE_WORK["qa-code-critic"]])
        check_eq("the analyst gets the triage screen",
                 story_step.PRE_WORK["qa-failure-analyst"][0][2], "work/judge-triage.json")
        check_eq("the reporter gets the bug screen",
                 story_step.PRE_WORK["qa-bug-reporter"][0][2], "work/judge-bugs.json")

        # A generated table is code's to write, and nothing on the S8 path wrote it: the scribe
        # was told to, in two places, and when it did not the report's appendix was hand-made.
        check("the traceability table is written before the scribe, judge or no judge",
              "traceability.py" in [item[0] for item in story_step.DERIVED_BEFORE["qa-doc-scribe"]])
        notes = story_step._derive_before("QA-9", "qa-doc-scribe", root / "qa-factory/artifacts/QA-9")
        check("the derivation reports itself in the dispatch notes", bool(notes))
        check_in("and a failure to derive says whose problem it is",
                 "traceability.py", " | ".join(notes))
        check_eq("a role with nothing to derive gets no notes",
                 story_step._derive_before("QA-9", "qa-scout", root / "qa-factory/artifacts/QA-9"), [])

        # --- S5 completion passes the window record (FR-5: the controller demands it) ----
        import argparse
        wtask = root / "qa-factory/artifacts/QA-W"
        (wtask / "work" / "windows").mkdir(parents=True)
        seen = []

        class Stop(Exception):
            pass

        class WindowController:
            def __init__(self, _root, wait_seconds=0.0):
                pass

            def state(self):
                return {"dispatches": {"S5-qa-code-critic-5": {"stage": "S5", "role": "qa-code-critic"}}}

            def prepare(self, options):
                seen.append(dict(options))
                raise Stop()

        saved = {name: getattr(story_step, name) for name in
                 ("Controller", "_task_root", "_stages", "_handoff_check", "_evidence", "_role_receipts")}
        story_step.Controller = WindowController
        story_step._task_root = lambda _task: wtask
        story_step._stages = lambda: {"S5": {"roles": ["qa-automator", "qa-code-critic"]}}
        story_step._handoff_check = lambda *_a: ("green", "", "")
        story_step._evidence = lambda *_a: ["work/x.json"]
        story_step._role_receipts = lambda *_a: []

        def run_finish(window=None, complete=True):
            seen.clear()
            ns = argparse.Namespace(task="QA-W", dispatch_id="S5-qa-code-critic-5", digest="d", output=None,
                                    not_complete=not complete, complete=complete, ignore_handoff=False, window=window)
            try:
                story_step.finish(ns)
            except Stop:
                pass
            return seen[0] if seen else {}
        try:
            check("S5 complete without any record: the payload has no window",
                  "window" not in run_finish())
            record = {"window": "W1", "instances": [1, 2]}
            (wtask / "work" / "windows" / "S5-qa-code-critic-5.json").write_text(
                json.dumps(record), encoding="utf-8")
            check_eq("S5 complete without --window picks work/windows/<id>.json",
                     run_finish().get("window"), record)
            other = {"window": "W2"}
            (wtask / "work" / "other.json").write_text(json.dumps(other), encoding="utf-8")
            check_eq("--window loads the given task-relative file into the payload",
                     run_finish(window="work/other.json").get("window"), other)
            check_eq("--window accepts an absolute path",
                     run_finish(window=str(wtask / "work" / "other.json")).get("window"), other)
            (wtask / "work" / "other.json").write_text("{not json", encoding="utf-8")
            check("an unreadable --window file is no window (the controller's refusal stands)",
                  "window" not in run_finish(window="work/other.json"))
            check("a stage left open passes no window", "window" not in run_finish(complete=False))
        finally:
            for name, value in saved.items():
                setattr(story_step, name, value)
    finally:
        harness.cleanup(root)
    where_asks_for_the_launch_answer_once()
    harness.finish("test_story_step_start")


if __name__ == "__main__":
    main()
