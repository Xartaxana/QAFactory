#!/usr/bin/env python3
"""The launch card: a dispatch nobody launched is told to be launched, and the text to launch it
with survives the exec cell that lost it (CX1-13, t-613, TP2-2406).

On Codex Desktop the Agent call to start a role was the stdout of `story_step.py start`, printed at the
very end of a command that runs 34-112 s, while the orchestrator's exec cell yields after ~30 s. The
output was lost three times, `next` answered `wait_existing_job` / `unknown` for work nobody had begun,
and S2 never ran. What is proved here (each check names the ONE mutation that kills it; every one is
killed by this file alone):

  (a) the yield: `start` prints `dispatched` and the card's path, flushed, BEFORE its first slow step,
      and prints `dispatched` once
  (b) a real `start`: the card file is the printed block byte for byte, written after brief and form,
      in a project whose path holds a space and a non-ASCII word (E4)
  (c) `next`: `launch` with every field, and the state is byte-identical afterwards
  (d) any evidence of a launch forbids it - agent id, receipt of any status (a context-probe one too),
      return mark, denial row, an unreadable receipt or denial file (an unknown is never a launch)
  (d2) only the verdict `unknown` can launch: alive / returned / abandoned / never_started / a verdict
      that could not be taken keep the old answer; no project config keeps it too
  (e) no card: `wait_start` (with the person's door; `materialize` is named only for a packet no `start` registered,
      CX1-14, and these stories are `start`'s), and `where` rebuilds it from the brief and the form - writing
      nothing else; the rebuilt card is the card a REAL `start` wrote
  (f) the driver's stories, a process with the run-mode variable, no stamp, a stamp that is a string
  (g) the card of dispatch -2 never answers dispatch -3
  (h) the pure reader the driver uses (`_next_action_for_state`) is unchanged
  (i) a bound dispatch on an accepted stage has no agent id on its record: the receipt alone decides
"""
import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, s5_apply, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import dispatch_liveness  # noqa: E402
import launch_card  # noqa: E402
import person_words  # noqa: E402
import story_step  # noqa: E402
from controller import Controller  # noqa: E402

import test_controller_rework as REWORK  # noqa: E402  (host_receipt fixture)
import test_controller_rework_scope as SCOPED  # noqa: E402  (gate_a_task fixture)
import test_dispatch_liveness as LIFE  # noqa: E402  (without_hooklib: a host with no transcripts)
import test_story_step as STEP  # noqa: E402  (open_story: a project with a story past S0)
import test_s5_process as S5P  # noqa: E402  (dispatch: a window of S5 on the earlier form)

DISPATCH = "S5-qa-automator-1"
ABSENT = object()
OLD = 1.0            # a receipt time long past: the receipt is NOT `alive`, so only the evidence rule stops `launch`


@contextlib.contextmanager
def run_mode_env(value=None):
    """The driver's variable as this process sees it: unset (None) or set to `value`."""
    saved = os.environ.get(launch_card.RUN_MODE_ENV)
    if value is None:
        os.environ.pop(launch_card.RUN_MODE_ENV, None)
    else:
        os.environ[launch_card.RUN_MODE_ENV] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(launch_card.RUN_MODE_ENV, None)
        else:
            os.environ[launch_card.RUN_MODE_ENV] = saved


def stamp(root, run_mode):
    """Put `run_mode` into pipeline.json as it stands (ABSENT removes the key)."""
    path = root / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    if run_mode is ABSENT:
        pipeline.pop("run_mode", None)
    else:
        pipeline["run_mode"] = run_mode
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def dispatch_request(identifier, **extra):
    return dict({"id": identifier, "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                 "input_hash": "s5-input", "budget": {}, "known_paths": {},
                 "idempotency_key": "dispatch:" + identifier}, **extra)


def s5_story(root, run_mode=None, card=True, **record):
    """The shape the story was stuck in: a desktop story, S5 dispatched, no agent, no receipt - and the card
    on disk (`card=False`: not yet). No transcript inventory, as on the Codex host."""
    run_mode = {"mode": "desktop"} if run_mode is None else run_mode
    controller = SCOPED.gate_a_task(root)
    stamp(root, run_mode)
    s5_apply(controller, dict(dispatch_request(DISPATCH, **record),
                                      known_paths={"root": str(root)}))
    if card:
        launch_card.write(root, DISPATCH, "card text\n")
    LIFE.without_hooklib()
    return controller


def denial(root, identifier=DISPATCH, line=None):
    path = root / "state" / "dispatch-denials.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = line if line is not None else json.dumps({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage": "S5",
        "role": "qa-automator", "dispatch_id": identifier, "reason": "stage guard refused S5"})
    with path.open("a", encoding="utf-8") as stream:
        stream.write(row + "\n")


def receipt(root, status="running", **fields):
    REWORK.host_receipt(root, **dict({"agent_id": "a1", "agent_type": "qa-automator", "task_id": root.name,
                                      "dispatch_id": DISPATCH, "status": status, "bound_at": OLD}, **fields))


def answer(root):
    """What `next` says for the story at `root` (the controller closes what it can prove dead first)."""
    return Controller(root).next_action()


def snapshot(root):
    """Every file under `root`: path -> sha256 - what `where` and `next` must not change."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@contextlib.contextmanager
def verdict_is(state):
    """`dispatch_liveness.state` answers `state` (None: it raises) for the whole block - the host's proof, set by hand."""
    saved = dispatch_liveness.state

    def fake(*_args, **_kwargs):
        if state is None:
            raise RuntimeError("the liveness reader failed")
        return {"state": state, "evidence": ["set by the test"]}

    dispatch_liveness.state = fake
    try:
        yield
    finally:
        dispatch_liveness.state = saved


# --- (a) the 30-second yield ------------------------------------------------------------------

def start_stubbed(root, ticket, runner, stage="S1", role="qa-scout"):
    """`start` in this process on a real project, every subprocess replaced by `runner` (no dashboard
    refresh, no brief_pack): what is recorded is WHEN the output left, relative to the slow steps."""
    out = []

    class Out:
        def write(self, text):
            out.append(("write", text))
            return len(text)

        def flush(self):
            out.append(("flush", ""))

    def stub(script, *args):
        out.append(("run", script))
        return runner(script, *args)

    saved = story_step._run
    story_step._run = stub
    try:
        with contextlib.redirect_stdout(Out()):
            code = story_step.start(argparse.Namespace(task=ticket, stage=stage, role=role, id=None,
                                                       scope=None, purpose=None, execution_kind=""))
    finally:
        story_step._run = saved
    return code, out


def start_prints_the_card_path_before_its_slow_steps():
    """KILLS: delete `sys.stdout.flush()` after the two lines in `story_step.start`, or move the
    `dispatched` print back below the brief and the form (the order that lost the card), or print the
    `dispatched` line twice (the old final line returned)."""
    root = harness.temp_project("qa-launch-yield-")
    try:
        harness.use_project(root)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        env.pop(launch_card.RUN_MODE_ENV, None)
        with run_mode_env(None):
            task = STEP.open_story(root, env, "QA-Y")

            def slow(script, *args):
                time.sleep(0.05)     # the dashboard refresh, the brief, the form: each takes its time
                return 0, ""

            code, out = start_stubbed(root, "QA-Y", slow)
        check_eq("the stubbed start succeeds", code, 0)
        first_run = next(i for i, (kind, _) in enumerate(out) if kind == "run")
        early = out[:first_run]
        early_text = "".join(text for kind, text in early if kind == "write")
        card = launch_card.card_rel("QA-Y", "S1-qa-scout-1")
        check_in("the dispatch id is written before the first slow step", "dispatched S1-qa-scout-1 (revision",
                 early_text)
        check_in("and the card's path, with the door if the output ends there", "launch card: " + card,
                 early_text)
        check_in("which names the command to run", "story_step.py where --task QA-Y", early_text)
        last_write = max((i for i, (kind, _) in enumerate(early) if kind == "write"), default=-1)
        check("and both were FLUSHED before the first slow step (a buffer is the same loss)",
              any(kind == "flush" for kind, _ in early[last_write + 1:]))
        written = "".join(text for kind, text in out if kind == "write")
        block = (task / "work" / "briefs" / "S1-qa-scout-1.launch.md").read_text(encoding="utf-8")
        check("the card block is the LAST output", written.endswith(block))
        check_eq("exactly one dispatched line, not two", written.count("dispatched S1-qa-scout-1"), 1)
        check_not_in("the early lines are not part of the card", "launch card:", block)
    finally:
        cleanup(root)


def a_refused_apply_prints_no_id_and_no_card_path():
    """KILLS: print the two lines before `controller.apply("dispatch", ...)` returns (I1: a printed id has a record)."""
    root = harness.temp_project("qa-launch-refused-")
    try:
        harness.use_project(root)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        with run_mode_env(None):
            STEP.open_story(root, env, "QA-X")
            saved = Controller.apply

            def refuse(self, operation, request, *args, **kwargs):
                if operation == "dispatch":
                    raise ValueError("refused by the test")
                return saved(self, operation, request, *args, **kwargs)

            Controller.apply = refuse
            try:
                try:
                    code, out = start_stubbed(root, "QA-X", lambda *_a: (0, ""))
                except ValueError as exc:
                    code, out = str(exc), []
            finally:
                Controller.apply = saved
        check_eq("the refusal reaches the caller", code, "refused by the test")
        check_eq("and nothing was printed - no id, no card path", out, [])
    finally:
        cleanup(root)


# --- (b) a real start --------------------------------------------------------------------------

def start_writes_the_card_last_and_prints_the_same_bytes():
    """KILLS: call `launch_card.write` before `_handoff_form` in `story_step.start` (the card would
    predate the form), or print a text other than the one written (two renderings). The project path holds a
    space and a non-ASCII word (E4): the printed card path is relative and the file is there."""
    word = "".join(chr(code) for code in (0x43f, 0x440, 0x43e, 0x435, 0x43a, 0x442))     # a non-ASCII word, no literal in the package
    root = harness.temp_project(f"qa-launch-real {word} 1-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONIOENCODING="utf-8")
        env.pop(launch_card.RUN_MODE_ENV, None)
        harness.use_project(root)
        task = STEP.open_story(root, env, "QA-R")
        started = harness.run_script("story_step.py", "start", "--task", "QA-R", "--stage", "S1",
                                     "--role", "qa-scout", cwd=root, env=env)
        check_eq("start exits 0", started.returncode, 0)
        card = task / "work" / "briefs" / "S1-qa-scout-1.launch.md"
        brief = task / "work" / "briefs" / "S1-qa-scout-1.md"
        form = task / "work" / "handoffs" / "S1-qa-scout-1.yaml"
        check("the card file exists", card.is_file(), started.stdout[-300:])
        check("beside a brief and a handover form that exist", brief.is_file() and form.is_file(),
              f"brief {brief.is_file()} form {form.is_file()}")
        printed = started.stdout[started.stdout.index("--- Agent prompt, verbatim"):]
        check_eq("the card is the printed block, byte for byte", card.read_bytes().decode("utf-8"), printed)
        check("written after the brief and after the form (the card proves those steps are over)",
              card.stat().st_mtime_ns >= brief.stat().st_mtime_ns
              and card.stat().st_mtime_ns >= form.stat().st_mtime_ns)
        lines = started.stdout.splitlines()
        check("and `dispatched` comes before everything else", lines[0].startswith("dispatched S1-qa-scout-1 ("),
              lines[0])
        path_line = next(line for line in lines if line.startswith("launch card: "))
        printed_rel = path_line[len("launch card: "):].split(" (")[0]
        check_eq("the printed path is the project-relative path", printed_rel, launch_card.card_rel("QA-R", "S1-qa-scout-1"))
        check("and the file is there under it", (root / printed_rel).is_file())
        check_in("the prompt in the card names the brief and the form", "work/handoffs/S1-qa-scout-1.yaml", printed)
        check_in("with the bind line", "story_step.py bind --task QA-R --dispatch-id S1-qa-scout-1 --agent-id <id>",
                 printed)
    finally:
        cleanup(root)


def a_card_that_cannot_be_written_is_a_note_and_the_block_is_printed():
    """KILLS: let an OSError of `launch_card.write` escape `start` (E3), or drop the note."""
    root = harness.temp_project("qa-launch-nowrite-")
    saved = launch_card.write
    try:
        harness.use_project(root)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        with run_mode_env(None):
            STEP.open_story(root, env, "QA-E")

            def broken(*_args):
                raise PermissionError("read-only folder")

            launch_card.write = broken
            code, out = start_stubbed(root, "QA-E", lambda *_a: (0, ""))
        text = "".join(t for kind, t in out if kind == "write")
        check_eq("start still exits 0", code, 0)
        check_in("the failure is a note that says the block below is the card", "the block below is the launch card", text)
        check_in("and the block is printed", "--- Agent prompt, verbatim", text)
    finally:
        launch_card.write = saved
        cleanup(root)


# --- (c) next says `launch` ------------------------------------------------------------------------

def next_launches_what_nothing_shows_launched():
    """KILLS: remove the `launch` substitution in `Controller.next_action` (it answers wait_existing_job
    again), or have `launch_action` write anything (the state check below)."""
    root = temp_dir("qa-launch-next-")
    try:
        s5_story(root)
        before = json.dumps(Controller(root).state(), sort_keys=True)
        files = snapshot(root)
        with run_mode_env(None):
            action = answer(root)
        check_eq("a running dispatch no record shows launched, on a desktop story: launch",
                 action.get("action"), "launch")
        check_eq("with the id", action.get("dispatch_id"), DISPATCH)
        check_eq("the stage and the role", (action.get("stage"), action.get("role")), ("S5", "qa-automator"))
        check_eq("the subagent type the Agent call takes", action.get("subagent_type"), "qa-automator")
        check_eq("the card's project-relative path", action.get("card"), launch_card.card_rel(root.name, DISPATCH))
        check_eq("the exact bind command", action.get("bind"),
                 f"story_step.py bind --task {root.name} --dispatch-id {DISPATCH} --agent-id <id>")
        check_in("a reason that says why", "the host never launched it", action.get("reason", ""))
        check_eq("the liveness verdict is kept", action.get("liveness"), "unknown")
        check_in("and its evidence", "no subagent transcript", action.get("evidence"))
        check_not_in("a launch has no release door of its own", "release", json.dumps(sorted(action)))
        check_eq("the state is byte-identical afterwards (next reads)",
                 json.dumps(Controller(root).state(), sort_keys=True), before)
        check_eq("and no file changed", snapshot(root), files)
    finally:
        cleanup(root)


# --- (d) any evidence of a launch forbids it ---------------------------------------------------------

def any_evidence_of_a_launch_forbids_it():
    """KILLS (one each): in `launch_card.launch_evidence`, drop the `agent_id` clause, drop the receipt
    clause (a receipt of ANY status), drop the `returned_*` clause, make an unreadable receipt count as
    nothing; in `Controller._denial_evidence`, return nothing (the denial clause)."""
    root = temp_dir("qa-launch-agent-")
    try:
        s5_story(root, agent_id="a-7")
        with run_mode_env(None):
            action = answer(root)
        check_eq("an agent id on the record: still wait_existing_job", action.get("action"), "wait_existing_job")
        check_eq("not alive on any proof, so the evidence rule is what held it", action.get("liveness"), "unknown")
    finally:
        cleanup(root)
    for status in ("running", "terminal"):
        root = temp_dir(f"qa-launch-receipt-{status}-")
        try:
            s5_story(root)
            receipt(root, status=status)
            with run_mode_env(None):
                action = answer(root)
                check(f"a {status} receipt names the dispatch: never launch",
                      action.get("action") not in ("launch", "wait_start"), json.dumps(action)[:300])
                if status == "running":
                    check_eq("a running one with no proof it works: wait_existing_job, as before",
                             (action.get("action"), action.get("liveness")), ("wait_existing_job", "unknown"))
                found = launch_card.launch_evidence(root, root.name, Controller(root).state()["dispatches"][DISPATCH])
            check_in(f"the {status} receipt is named in the evidence", "a host receipt names this dispatch", found)
        finally:
            cleanup(root)
    root = temp_dir("qa-launch-marks-")
    try:
        s5_story(root)
        record = Controller(root).state()["dispatches"][DISPATCH]
        with run_mode_env(None):
            check("the record as it is: a launch", launch_card.launch_action(root, root.name, root, record))
            for key in ("returned_at", "returned_digest", "agent_id"):
                check_eq(f"{key} on the record: not a launch",
                         launch_card.launch_action(root, root.name, root, dict(record, **{key: "x"})), None)
            check_eq("a record that is not running: not a launch",
                     launch_card.launch_action(root, root.name, root, dict(record, status="accepted")), None)
            denial(root)
            controller = Controller(root)
            owed = controller._denial_evidence(record, controller._dispatch_starts())
            check_in("a denial row names it, in the controller's words", "refused the Agent call", owed)
            check_eq("so it is not a launch", launch_card.launch_action(root, root.name, root, record,
                                                                       extra_evidence=owed), None)
            check_eq("and the controller's answer for the record is none either",
                     controller.launch_answer(record)[0], None)
    finally:
        cleanup(root)
    root = temp_dir("qa-launch-denial-")
    try:
        s5_story(root)
        denial(root)
        with run_mode_env(None):
            action = answer(root)
        check("a denial row: next repairs, it never launches", action.get("action") in ("relaunch",),
              json.dumps(action)[:300])
    finally:
        cleanup(root)
    # a broken LINE no reader can attribute to anybody, and a row of another dispatch: no exception, no evidence
    root = temp_dir("qa-launch-broken-denial-")
    try:
        s5_story(root)
        denial(root, line="{this line is not json")
        denial(root, identifier="S5-qa-automator-9")
        with run_mode_env(None):
            check_eq("a broken line and another dispatch's row: no exception, no evidence, a launch",
                     answer(root).get("action"), "launch")
    finally:
        cleanup(root)
    # a denial FILE that cannot be read is evidence of its own
    root = temp_dir("qa-launch-unreadable-denials-")
    try:
        s5_story(root)
        controller = Controller(root)
        record = controller.state()["dispatches"][DISPATCH]
        saved = Controller._denial_times

        def unreadable(self, *_args):
            raise PermissionError("denied")

        Controller._denial_times = unreadable
        try:
            with run_mode_env(None):
                owed = controller._denial_evidence(record, controller._dispatch_starts())
                check_eq("and the controller's answer is no launch", controller.launch_answer(record)[0], None)
        finally:
            Controller._denial_times = saved
        check_in("an unreadable denial file is named, never taken for none", "could not read", " ".join(owed))
    finally:
        cleanup(root)
    root = temp_dir("qa-launch-broken-receipt-")
    try:
        s5_story(root)
        record = Controller(root).state()["dispatches"][DISPATCH]
        directory = root / "qa-factory" / "state" / "host-dispatches"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "garbage.json").write_text("{not json at all", encoding="utf-8")
        (directory / "list.json").write_text("[1, 2]", encoding="utf-8")
        with run_mode_env(None):
            found = launch_card.launch_evidence(root, root.name, record)
            check_in("a receipt file that is not JSON is evidence of its own", "could not be read as a receipt", found)
            check_in("and so is one that is not an object", "is not a JSON object", found)
            check_eq("so it is not a launch", launch_card.launch_action(root, root.name, root, record), None)
            check_eq("and next waits, as before", answer(root).get("action"), "wait_existing_job")
    finally:
        cleanup(root)
    root = temp_dir("qa-launch-other-receipt-")
    try:
        s5_story(root)
        receipt(root, task_id="OTHER-1")
        with run_mode_env(None):
            check_eq("a receipt of another story is not evidence", answer(root).get("action"), "launch")
        receipt(root, dispatch_id="S5-qa-automator-9")
        with run_mode_env(None):
            check_eq("nor is one of another dispatch", answer(root).get("action"), "launch")
        receipt(root, task_id="", dispatch_id=None)
        with run_mode_env(None):
            check_eq("a receipt with no task_id is of no story: neither evidence nor guard input",
                     answer(root).get("action"), "launch")
    finally:
        cleanup(root)


def a_context_probe_receipt_of_the_story_and_role_is_evidence():
    """KILLS: filter `factory_diagnostic: context_probe` receipts out of `_receipt_evidence` (the safe side is to
    wait: a probe that ran is a role that may have run)."""
    root = temp_dir("qa-launch-probe-")
    try:
        s5_story(root)
        with run_mode_env(None):
            receipt(root, status="running", dispatch_id=None, factory_diagnostic="context_probe")
            check_eq("a context-probe receipt of this story and role: wait, never launch",
                     answer(root).get("action"), "wait_existing_job")
    finally:
        cleanup(root)


# --- (d2) only `unknown` can launch ---------------------------------------------------------------------

def a_dispatch_the_host_proves_alive_still_waits():
    """KILLS: in `Controller.launch_answer`, ask `launch_action` whatever the verdict says (the proof of
    work must win over the absence of a receipt), here and through `story_step.where`."""
    root = temp_dir("qa-launch-alive-")
    try:
        s5_story(root)
        LIFE.fake_hooklib([LIFE.transcript(root, "auto", DISPATCH, ticket=root.name, age=5)])
        with run_mode_env(None):
            action = answer(root)
            check_eq("a fresh transcript and no receipt: wait_existing_job", action.get("action"), "wait_existing_job")
            check_eq("because it is alive", action.get("liveness"), "alive")
            controller = Controller(root)
            read_only = controller._next_action_for_state(controller.state())
            kept, card = story_step._launch_from_where(root.name, root, controller, read_only)
        check_eq("`where` keeps the wait too", kept.get("action"), "wait_existing_job")
        check_eq("and prints no card", card, "")
    finally:
        LIFE.without_hooklib()
        cleanup(root)


def returned_abandoned_and_unproved_keep_the_wait():
    """KILLS: offer `launch` at any verdict but `unknown` (`!= alive`), or offer it when the verdict could not be
    taken: `returned` / `abandoned` / `never_started` are settled by the repair, and a launch there could double an
    agent. The reader sees the clean evidence below (no receipt, no mark, no denial)."""
    root = temp_dir("qa-launch-verdicts-")
    try:
        controller = s5_story(root)
        record = controller.state()["dispatches"][DISPATCH]
        with run_mode_env(None):
            with verdict_is("unknown"):
                check_eq("control, verdict unknown: launch", (controller.launch_answer(record)[0] or {}).get("action"), "launch")
            for state in ("alive", "returned", "abandoned", "never_started"):
                with verdict_is(state):
                    launch, verdict = controller.launch_answer(record)
                    kept, card = story_step._launch_from_where(root.name, root, controller,
                                                               controller._next_action_for_state(controller.state()))
                check_eq(f"verdict {state}: no launch from the controller", (launch, verdict.get("state")), (None, state))
                check_eq(f"verdict {state}: and none from `where`, no card printed", (kept.get("action"), card),
                         ("wait_existing_job", ""))
            with verdict_is(None):
                launch, verdict = controller.launch_answer(record)
            check_eq("a verdict that could not be taken (the reader raised): the old answer, never a launch",
                     (launch, verdict.get("state")), (None, "unknown"))
    finally:
        cleanup(root)


def a_reader_that_cannot_run_is_named_in_the_evidence():
    """CX1-13 fix round (t-1126 m-1, FR-59). KILLS: leave the evidence list empty when `dispatch_liveness.state` raises
    (or when `launch_card.launch_action` does): the conductor then reads `evidence: []` as "nothing is in the way",
    which is not what happened. The refusal of the launch stays; a reader that returns normally with no evidence keeps
    the empty list (control: the name is only added for an exception)."""
    root = temp_dir("qa-launch-named-")
    try:
        controller = s5_story(root)
        record = controller.state()["dispatches"][DISPATCH]
        with run_mode_env(None):
            with verdict_is(None):
                launch, verdict = controller.launch_answer(record)
                said = Controller(root).next_action()
            text = " ".join(verdict.get("evidence") or [])
            check_eq("the liveness reader raised: no launch, the verdict unknown", (launch, verdict.get("state")), (None, "unknown"))
            check("and the evidence is not empty", bool(verdict.get("evidence")), repr(verdict))
            check_in("it names the exception type", "RuntimeError", text)
            check_in("and its message", "the liveness reader failed", text)
            check_eq("`next` is the old wait, and carries the same words", (said.get("action"), said.get("liveness")),
                     ("wait_existing_job", "unknown"))
            check_in("`next` names the exception too", "RuntimeError: the liveness reader failed", " ".join(said.get("evidence") or []))
            saved = dispatch_liveness.state
            dispatch_liveness.state = lambda *_args, **_kwargs: {"state": "unknown", "evidence": []}
            try:
                launch, verdict = controller.launch_answer(record)
            finally:
                dispatch_liveness.state = saved
            check_eq("control: a reader that returns normally with no evidence - launch, and the evidence list stays empty",
                     (launch.get("action"), launch.get("evidence"), verdict.get("evidence")), ("launch", [], []))
            saved = launch_card.launch_action

            def broken(*_args, **_kwargs):
                raise ValueError("the receipts folder is odd")

            launch_card.launch_action = broken
            try:
                with verdict_is("unknown"):
                    launch, verdict = controller.launch_answer(record)
            finally:
                launch_card.launch_action = saved
            check_eq("the card layer raised: no launch", launch, None)
            check_in("and the evidence names that exception", "ValueError: the receipts folder is odd",
                     " ".join(verdict.get("evidence") or []))
    finally:
        cleanup(root)


def next_and_where_take_the_one_dict_launch_answer_builds():
    """CX1-13 fix round (t-1126 F-2, FR-10). KILLS: merge `liveness` / `evidence` (or any key) again in
    `Controller.next_action` or in `story_step._launch_from_where`: the dict they return must be the very object
    `Controller.launch_answer` built - one builder, so the two cannot answer differently. Also: with no card,
    `next` and `where` give the same `wait_start` (the card layer decides, not a second dict)."""
    root = temp_dir("qa-launch-onedict-")
    try:
        controller = s5_story(root)
        read_only = controller._next_action_for_state(controller.state())
        sentinel = {"action": "wait_start", "dispatch_id": DISPATCH, "marker": object()}
        saved = Controller.launch_answer
        Controller.launch_answer = lambda self, dispatch, rebuild=None: (sentinel, {"state": "unknown", "evidence": []})
        try:
            with run_mode_env(None):
                kept, _card = story_step._launch_from_where(root.name, root, controller, read_only)
                said = Controller(root).next_action()
        finally:
            Controller.launch_answer = saved
        check("`where` returns the dict `launch_answer` built, untouched", kept is sentinel)
        check("and so does `next`", said is sentinel)
        with run_mode_env(None):
            check_eq("with the card on disk, `next` and `where` give the same launch", answer(root), where_answers(root)[0])
        cardless = temp_dir("qa-launch-onedict-nocard-")
        try:
            s5_story(cardless, card=False)
            with run_mode_env(None):
                said = answer(cardless)
                kept, shown = where_answers(cardless)
            check_eq("no card (and no brief to rebuild it from): `next` says wait_start", said.get("action"), "wait_start")
            check_eq("`where` says the same, with the same keys, and prints no card", (sorted(kept), shown),
                     (sorted(said), ""))
            check_eq("and the same words (the age is read from the clock, twice)",
                     {k: v for k, v in kept.items() if k != "age_s"}, {k: v for k, v in said.items() if k != "age_s"})
        finally:
            cleanup(cardless)
    finally:
        cleanup(root)


def no_project_config_gives_the_old_answer():
    """KILLS: let `project is None` reach `launch_action` (the answer changes), or lose the evidence line of `main`."""
    root = temp_dir("qa-launch-noconfig-")
    try:
        controller = s5_story(root)
        (root / "qa-factory" / "config.json").unlink()
        with run_mode_env(None):
            action = answer(root)
            record = controller.state()["dispatches"][DISPATCH]
        check_eq("no qa-factory/config.json: wait_existing_job, as on main", action.get("action"), "wait_existing_job")
        check_eq("liveness unknown", action.get("liveness"), "unknown")
        check_in("with the sentence that the host's records cannot be located", "no qa-factory/config.json at or above",
                 " ".join(action.get("evidence") or []))
        check_eq("the pure card reader answers None for no project, no exception",
                 launch_card.launch_action(None, root.name, root, record), None)
    finally:
        cleanup(root)


# --- (e) the card is not there yet: wait_start, and where rebuilds it ------------------------------------

def where(root, ticket, env):
    done = harness.run_script("story_step.py", "where", "--task", ticket, cwd=root, env=env)
    lines = done.stdout.splitlines()
    nxt = next(line for line in lines if line.startswith("next: "))
    return json.loads(nxt[len("next: "):]), done.stdout


def stubbed_story(root, ticket):
    """A project whose story `start` (stubbed: no brief, no form) dispatched S1 qa-scout - and then died
    before the card: the dispatch is on record, the card is gone (the exec cell yielded). Returns
    (task, env, dispatch id, card path, brief path)."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop(launch_card.RUN_MODE_ENV, None)
    harness.use_project(root)
    identifier = "S1-qa-scout-1"
    with run_mode_env(None):
        task = STEP.open_story(root, env, ticket)
        code, _ = start_stubbed(root, ticket, lambda script, *args: (0, ""))
    check_eq(f"{ticket}: start (stubbed) registered the dispatch", code, 0)
    card = task / "work" / "briefs" / f"{identifier}.launch.md"
    card.unlink()
    return task, env, identifier, card, task / "work" / "briefs" / f"{identifier}.md"


def no_card_waits_and_where_rebuilds_it_from_the_brief():
    """KILLS: have `launch_action` answer `launch` with no card on disk; have `next` write the card;
    drop the rebuild in `story_step.where`; rebuild without the brief as proof; leave the form or the
    brief out of the rebuilt prompt; name `materialize` (a door that does not exist yet) in the reason."""
    root = harness.temp_project("qa-launch-where-")
    try:
        ticket = "QA-W"
        task, env, identifier, card, brief = stubbed_story(root, ticket)
        with run_mode_env(None):
            nothing = Controller(task).next_action()
        check_eq("no card, no brief: wait_start", nothing.get("action"), "wait_start")
        check_eq("it says which dispatch", nothing.get("dispatch_id"), identifier)
        check_eq("and how long ago it was recorded, in seconds", isinstance(nothing.get("age_s"), float), True)
        check_eq("with the door to ask again", nothing.get("rebuild"), f"story_step.py where --task {ticket}")
        check_in("and the person's door out", "--operation release --dispatch " + identifier, nothing.get("release", ""))
        check_eq("the door's bytes are the one `wait_existing_job` carries (one writer)", nothing.get("release"),
                 person_words.door(f"controller.py --task-root {task} --operation release --dispatch {identifier}"))
        check_not_in("the reason names no door that does not exist (FR-2)", "materialize", nothing.get("reason", ""))
        check_in("it says the person's word frees it", "release", nothing.get("reason", ""))
        check_not_in("no threshold, no verdict about the age", "stuck", json.dumps(nothing))
        tree = snapshot(root)
        answered, text = where(root, ticket, env)
        check_eq("where, with no brief either: still wait_start", answered.get("action"), "wait_start")
        check_eq("and it wrote nothing", snapshot(root), tree)
        brief.write_text("# Brief\n", encoding="utf-8")
        (task / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (task / "work" / "handoffs" / f"{identifier}.yaml").write_text("x: 1\n", encoding="utf-8")
        tree = snapshot(root)
        with run_mode_env(None):
            check_eq("next says wait_start (it never writes the card)", Controller(task).next_action().get("action"),
                     "wait_start")
        check_eq("and wrote nothing", snapshot(root), tree)
        answered, text = where(root, ticket, env)
        check_eq("where rebuilds the card and answers launch", answered.get("action"), "launch")
        check_eq("with the card's path", answered.get("card"), launch_card.card_rel(ticket, identifier))
        check_eq("the only new file is the card", sorted(set(snapshot(root)) - set(tree)),
                 [str(card.relative_to(root))])
        check_eq("and no other file changed", {k: v for k, v in snapshot(root).items() if k in tree}, tree)
        rebuilt = card.read_text(encoding="utf-8")
        check_in("the prompt of the rebuilt card names the brief", f"work/briefs/{identifier}.md", rebuilt)
        check_in("and the form", f"work/handoffs/{identifier}.yaml", rebuilt)
        check_in("`where` prints the card under the answer", rebuilt, text)
        card.unlink()
        REWORK.host_receipt(root, agent_id="a1", agent_type="qa-scout", task_id=ticket,
                            dispatch_id=identifier, status="running", bound_at=OLD)
        answered, text = where(root, ticket, env)
        check_eq("a receipt: where keeps the wait", answered.get("action"), "wait_existing_job")
        check("and writes no card", not card.exists())
    finally:
        cleanup(root)


def the_card_waits_for_the_form_when_the_registry_owes_one():
    """KILLS: in `story_step._rebuild_card`, rebuild from the brief alone (drop the form requirement), or
    return no reason of its own (the person is then told the wrong thing about the wait)."""
    root = harness.temp_project("qa-launch-form-")
    try:
        ticket = "QA-F"
        task, env, identifier, card, brief = stubbed_story(root, ticket)
        brief.write_text("# Brief\n", encoding="utf-8")
        tree = snapshot(root)
        answered, text = where(root, ticket, env)
        check_eq("brief there, form not, and S1 qa-scout has a contract: wait_start", answered.get("action"),
                 "wait_start")
        check_in("the reason says start is still writing the handover form", "still writing the handover form",
                 answered.get("reason", ""))
        check_not_in("and names no door that does not exist", "materialize", answered.get("reason", ""))
        check_eq("with the door to ask again and the person's door out",
                 (answered.get("rebuild"), "--operation release" in answered.get("release", "")),
                 (f"story_step.py where --task {ticket}", True))
        check_eq("where wrote nothing", snapshot(root), tree)
        check_not_in("and printed no card", "--- Agent prompt", text)
        (task / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (task / "work" / "handoffs" / f"{identifier}.yaml").write_text("x: 1\n", encoding="utf-8")
        answered, _ = where(root, ticket, env)
        check_eq("with the form on disk: launch", answered.get("action"), "launch")
        check("and the card exists", card.is_file())
    finally:
        cleanup(root)


def no_contract_for_the_pair_the_brief_alone_launches():
    """KILLS: in `story_step._rebuild_card`, require the form whether or not the registry has a contract
    for the pair (a role with no contract never gets a form: the card would never be rebuilt); or take an
    unreadable registry for `no contract` (an unknown must wait: FR-59)."""
    import handoff
    root = harness.temp_project("qa-launch-nocontract-")
    saved = handoff.contract_of
    try:
        ticket = "QA-N"
        task, env, identifier, card, brief = stubbed_story(root, ticket)
        brief.write_text("# Brief\n", encoding="utf-8")

        def rebuild_with(contract_of):
            handoff.contract_of = contract_of
            with run_mode_env(None):
                controller = Controller(task)
                read_only = controller._next_action_for_state(controller.state())
                return story_step._launch_from_where(ticket, task, controller, read_only)

        def unreadable(*_args):
            raise OSError("handoffs/index.yaml is not there")

        kept, printed = rebuild_with(unreadable)
        check_eq("a registry that cannot be read owes the form: wait_start", kept.get("action"), "wait_start")
        check("and no card was written", not card.exists() and printed == "")
        kept, printed = rebuild_with(lambda *_args: "")
        check_eq("no contract for the pair: the brief alone suffices - launch", kept.get("action"), "launch")
        text = card.read_text(encoding="utf-8")
        check_not_in("the card names no form (there is none)", "work/handoffs/", text)
        check_in("but names the brief", f"work/briefs/{identifier}.md", text)
        check_eq("and it is the card printed", printed, text)
    finally:
        handoff.contract_of = saved
        cleanup(root)


def real_start(root, env, ticket):
    """A real `start` (a subprocess, every script real) of S1 qa-scout; returns the card's path."""
    started = harness.run_script("story_step.py", "start", "--task", ticket, "--stage", "S1", "--role", "qa-scout",
                                 cwd=root, env=env)
    check_eq(f"{ticket}: a real start exits 0", started.returncode, 0)
    return root / "qa-factory" / "artifacts" / ticket / "work" / "briefs" / "S1-qa-scout-1.launch.md"


def a_rebuilt_card_is_the_card_start_wrote():
    """KILLS: give `story_step._rebuild_card` an extras formula of its own - the PRE_WORK outputs on disk
    with no `judge.active()` gate - instead of `_prompt_inputs` (the judge-off case below fails); or have
    `_prompt_inputs` drop the outputs while the judge is on (the judge-on case fails). The oracle is the
    card a REAL `start` wrote, never the `_prompt` formula (FR-58)."""
    for judge_on in (False, True):
        root = harness.temp_project("qa-launch-rebuild-")
        try:
            ticket = "QA-J1" if judge_on else "QA-J0"
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
            env.pop(launch_card.RUN_MODE_ENV, None)
            harness.use_project(root)
            if judge_on:
                path = root / "qa-factory" / "config.json"
                cfg = json.loads(path.read_text(encoding="utf-8"))
                cfg["judge"] = {"provider": "typesafe", "mode": "shadow"}
                path.write_text(json.dumps(cfg), encoding="utf-8")
            task = STEP.open_story(root, env, ticket)
            (task / "work" / "judge-sources.json").write_text("{}", encoding="utf-8")
            card = real_start(root, env, ticket)
            written = card.read_bytes()
            check_eq(f"judge {'on' if judge_on else 'off'}: start gives the role the judge's file only when the judge is on",
                     f"qa-factory/artifacts/{ticket}/work/judge-sources.json" in written.decode("utf-8"), judge_on)
            card.unlink()
            answered, text = where(root, ticket, env)
            check_eq("the card is gone: where answers launch", answered.get("action"), "launch")
            check_eq("and the rebuilt card is byte for byte the card start wrote", card.read_bytes(), written)
            check_in("which `where` prints under the answer", written.decode("utf-8"), text)
        finally:
            cleanup(root)


def the_rebuilt_s5_critic_card_carries_the_probe_debt():
    """KILLS: leave `_debt_input` out of `_prompt_inputs` (or out of the rebuild): the card start wrote for
    the S5 code critic names `work/probe-debt.json`, the rebuilt one does not. `start` runs in this process
    with its scripts stubbed to write what they write (the debt file, the brief, the form)."""
    root = temp_dir("qa-launch-debt-")
    saved = story_step._task_root
    try:
        harness.use_project(root)
        S5P.dispatch(SCOPED.gate_a_task(root), root, "S5-qa-automator-1", scope=("TC-1",))      # SC1-14 B1b: the critic follows an author window (the earlier form), not a first window
        story_step._task_root = lambda _ticket: root
        identifier, ticket = "S5-qa-code-critic-1", root.name
        debt = "work/probe-debt.json"

        def scripts(script, *_args):
            targets = {"probe_debt.py": (debt, json.dumps({"dispatch": identifier, "outcomes": [],
                                                           "left": [{"instance_id": "i-1"}]})),
                       "brief_pack.py": (f"work/briefs/{identifier}.md", "# Brief\n"),
                       "handoff_init.py": (f"work/handoffs/{identifier}.yaml", "x: 1\n")}
            if script in targets:
                path = root / targets[script][0]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(targets[script][1], encoding="utf-8")
            return 0, ""

        with run_mode_env(None):
            code, _ = start_stubbed(root, ticket, scripts, stage="S5", role="qa-code-critic")
        check_eq("the critic's start (scripts stubbed) succeeds", code, 0)
        card = launch_card.card_path(root, identifier)
        written = card.read_bytes()
        check_in("start gave the critic the debt file", f"qa-factory/artifacts/{ticket}/{debt}", written.decode("utf-8"))
        card.unlink()
        LIFE.without_hooklib()
        with run_mode_env(None):
            controller = Controller(root)
            kept, printed = story_step._launch_from_where(ticket, root, controller,
                                                          controller._next_action_for_state(controller.state()))
        check_eq("the card is gone: launch", kept.get("action"), "launch")
        check_eq("and the rebuilt card is byte for byte the card start wrote", card.read_bytes(), written)
        check_eq("printed under the answer", printed, written.decode("utf-8"))
        # the formula in one place: a judge output left on disk is no input while the judge is off
        (root / "work" / "judge-code.json").write_text("{}", encoding="utf-8")
        check_not_in("a judge file left from an earlier run is no input of a judge that is off", "judge-code.json",
                     "\n".join(story_step._prompt_inputs(ticket, "S5", "qa-code-critic", root, identifier)))
    finally:
        story_step._task_root = saved
        cleanup(root)


# --- (e2) the carriers the first round missed: an unnamed denial, an unbound receipt ------------------------

def where_answers(root, controller=None):
    """What `where` asks the card layer for a story at `root` (the read-only reader, then `launch_card`)."""
    controller = controller or Controller(root)
    read_only = controller._next_action_for_state(controller.state())
    return story_step._launch_from_where(root.name, root, controller, read_only)


def an_unnamed_codex_denial_row_forbids_launch_in_next_and_where():
    """KILLS: make `Controller._denial_evidence` return nothing, or read only the rows that name the
    dispatch (the Codex desktop host writes `dispatch_id: null`, attributed by role, stage and time)."""
    root = temp_dir("qa-launch-unnamed-")
    try:
        s5_story(root)
        with run_mode_env(None):
            check_eq("control, no denial: next launches", answer(root).get("action"), "launch")
            check_eq("control, no denial: where launches", where_answers(root)[0].get("action"), "launch")
            elsewhere = json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage": "S5",
                                    "role": "qa-case-critic", "dispatch_id": None, "reason": "another role"})
            long_ago = json.dumps({"at": "2020-01-01T00:00:00+00:00", "stage": "S5", "role": "qa-automator",
                                   "dispatch_id": None, "reason": "years before this dispatch"})
            for line in (elsewhere, long_ago):
                denial(root, line=line)
            check_eq("control: a row of another role, and one from before the dispatch, are not this one's",
                     (answer(root).get("action"), where_answers(root)[0].get("action")), ("launch", "launch"))
            denial(root, identifier=None)
            kept, card = where_answers(root)
            check_eq("where: the wait stays, as the read-only reader gave it", kept.get("action"), "wait_existing_job")
            check_eq("and no card is printed", card, "")
            action = answer(root)
        check("next: never launch (the controller repairs a refused dispatch)",
              action.get("action") not in ("launch", "wait_start"), json.dumps(action)[:200])
    finally:
        cleanup(root)


def an_unbound_running_receipt_forbids_launch():
    """KILLS: in `launch_card._receipt_evidence`, ignore a receipt that names no dispatch (the writer leaves
    the id empty unless exactly one dispatch of the role runs), or count it for any role or any story."""
    root = temp_dir("qa-launch-unbound-")
    try:
        s5_story(root)
        with run_mode_env(None):
            receipt(root, status="running", dispatch_id=None, agent_type="qa-case-critic")
            check_eq("control: an unbound receipt of ANOTHER role is no evidence", answer(root).get("action"), "launch")
            receipt(root, status="running", dispatch_id=None, task_id="OTHER-1")
            check_eq("control: nor one of another story", answer(root).get("action"), "launch")
            receipt(root, status="running", dispatch_id=None)
            check_eq("next: a running receipt of this story and role that names no dispatch - wait",
                     answer(root).get("action"), "wait_existing_job")
            kept, card = where_answers(root)
            check_eq("where: the same", (kept.get("action"), card), ("wait_existing_job", ""))
            found = launch_card.launch_evidence(root, root.name, Controller(root).state()["dispatches"][DISPATCH])
        check_in("the evidence line names the receipt", "agent a1", " ".join(found))
    finally:
        cleanup(root)


def an_unbound_terminal_receipt_is_evidence_unless_proven_older():
    """KILLS: treat a terminal unbound receipt as never evidence (the in-window case fails); treat it as
    always evidence (the proven-older case fails); or give it a time rule of its own in place of
    `dispatch_liveness._may_be_this_dispatch` (the 60 s edge below fails)."""
    root = temp_dir("qa-launch-unbound-terminal-")
    try:
        s5_story(root)
        began = Controller(root)._dispatch_starts()[DISPATCH]
        skew = 60.0      # dispatch_liveness._CLOCK_SKEW_S: the writer's clock may trail this reader's by this much
        with run_mode_env(None):
            for label, bound, launches in (("bound just now, inside the window", time.time(), False),
                                           ("bound a minute before the dispatch, inside the skew", began - skew + 1, False),
                                           ("bound with no usable time", "yesterday", False),
                                           ("bound long before the dispatch: proven older", began - skew - 1, True),
                                           ("bound in 1970", OLD, True)):
                receipt(root, status="terminal", dispatch_id=None, bound_at=bound)
                nxt, wherever = answer(root).get("action"), where_answers(root)[0].get("action")
                if launches:
                    check_eq(f"{label}: next launches (it is another dispatch's receipt)", nxt, "launch")
                    check_eq(f"{label}: where launches", wherever, "launch")
                else:
                    check(f"{label}: never a launch, in next or in where",
                          nxt not in ("launch", "wait_start") and wherever not in ("launch", "wait_start"),
                          f"next {nxt} where {wherever}")
            receipt(root, status="terminal", dispatch_id=None, bound_at=time.time())
            found = launch_card.launch_evidence(root, root.name, Controller(root).state()["dispatches"][DISPATCH])
        check_in("a terminal one counts, and the line names the receipt", "terminal host receipt", " ".join(found))
        check_in("(its agent)", "agent a1", " ".join(found))
    finally:
        cleanup(root)


# --- (f) the driver's stories, and stories that cannot be told apart, are untouched ---------------------

WAIT_KEYS = ["action", "cancel_allowed", "dispatch_id", "evidence", "liveness", "reason", "release"]


def other_modes_get_the_old_answer():
    """KILLS: in `launch_card.desktop_story`, drop the environment test; or accept any stamp; or take a
    string `run_mode` for an object (it raises); or answer `launch` for a story with no stamp."""
    cases = [("a story stamped driver", {"mode": "driver"}, None),
             ("a story with no stamp", ABSENT, None),
             ("a run_mode that is a string, not an object", "desktop", None),
             ("a run_mode with no mode", {"since": "2026-10-12"}, None),
             ("a desktop story continued by a process with the variable set", {"mode": "desktop"}, "driver"),
             ("a desktop story, the variable set to `desktop` (the old rule: any value is not this process's own)",
              {"mode": "desktop"}, "desktop")]
    for name, run_mode, variable in cases:
        root = temp_dir("qa-launch-mode-")
        try:
            s5_story(root, run_mode=run_mode)
            with run_mode_env(variable):
                action = answer(root)
            check_eq(f"{name}: wait_existing_job, as before", action.get("action"), "wait_existing_job")
            check_eq(f"{name}: the shape is unchanged", sorted(action), WAIT_KEYS)
        finally:
            cleanup(root)
    root = temp_dir("qa-launch-mode-ok-")
    try:
        s5_story(root)
        with run_mode_env(None):
            check_eq("the control: the same fixture, desktop and no variable, launches", answer(root).get("action"),
                     "launch")
        (root / "pipeline.json").write_text("{not json", encoding="utf-8")
        with run_mode_env(None):
            check_eq("a pipeline.json that cannot be read: the old answer, no exception", answer(root).get("action"),
                     "wait_existing_job")
    finally:
        cleanup(root)
    check_eq("one definition of the variable's name", story_step.RUN_MODE_ENV, launch_card.RUN_MODE_ENV)


def a_record_without_its_parts_gets_no_launch_and_no_exception():
    """KILLS: remove the `stage`/`role`/`id` guard in `launch_card.launch_action`."""
    root = temp_dir("qa-launch-parts-")
    try:
        s5_story(root)
        record = Controller(root).state()["dispatches"][DISPATCH]
        with run_mode_env(None):
            for missing in ("stage", "role", "id"):
                partial = {k: v for k, v in record.items() if k != missing}
                check_eq(f"a dispatch with no {missing}: None", launch_card.launch_action(root, root.name, root, partial),
                         None)
            check_eq("a record that is not an object: None", launch_card.launch_action(root, root.name, root, "S5"), None)
            check_eq("so is None", launch_card.launch_action(root, root.name, root, None), None)
            check_eq("the whole record: a launch", launch_card.launch_action(root, root.name, root, record)["action"],
                     "launch")
        launch_card.card_path(root, DISPATCH).unlink()
        with run_mode_env(None):
            now = 1_800_000_000.0
            check_eq("an age the record states", launch_card.launch_action(
                root, root.name, root, dict(record, started_at=now - 30), now=now)["age_s"], 30.0)
            check_eq("a record with no start time: null", launch_card.launch_action(
                root, root.name, root, dict(record), now=now)["age_s"], None)
            check_eq("a start time ahead of the clock: null", launch_card.launch_action(
                root, root.name, root, dict(record, started_at=now + 500), now=now)["age_s"], None)
    finally:
        cleanup(root)


# --- (g) the card of one dispatch never answers another -------------------------------------------------

def the_card_of_dispatch_2_never_answers_dispatch_3():
    """KILLS: in `launch_card.CARD_REL`, drop `{dispatch_id}` (one card file per story or per role)."""
    root = temp_dir("qa-launch-two-")
    try:
        controller = s5_story(root)
        with run_mode_env(None):
            denial(root, DISPATCH)
            second = answer(root)
            check_eq("the first dispatch was never started: next relaunches", second.get("action"), "relaunch")
            s5_apply(controller, dict(second["dispatch_request"], known_paths={"root": str(root)}))
            id2 = second["dispatch_request"]["id"]
            launch_card.write(root, id2, "card of the second\n")
            check_eq("the second has its card", (answer(root)["action"], answer(root)["dispatch_id"]), ("launch", id2))
            denial(root, id2)
            third = answer(root)
            check_eq("and it too never started", third.get("action"), "relaunch")
            s5_apply(controller, dict(third["dispatch_request"], known_paths={"root": str(root)}))
            id3 = third["dispatch_request"]["id"]
            check("the stage has three dispatches of one role", (id2, id3) == ("S5-qa-automator-2", "S5-qa-automator-3"),
                  f"{id2} {id3}")
            check("the card of -2 is still on disk", launch_card.card_path(root, id2).is_file())
            waiting = answer(root)
            check_eq("-3 has no card: wait_start, naming -3", (waiting.get("action"), waiting.get("dispatch_id")),
                     ("wait_start", id3))
            launch_card.write(root, id3, "card of the third\n")
            ready = answer(root)
            check_eq("with its own card: launch", (ready.get("action"), ready.get("dispatch_id")), ("launch", id3))
            check_eq("and the path of its own card", ready.get("card"), launch_card.card_rel(root.name, id3))
    finally:
        cleanup(root)


# --- (h) the driver's reader --------------------------------------------------------------------------------

def the_pure_reader_is_unchanged():
    """KILLS: put the launch substitution into `Controller._next_action_for_state` (the reader the driver
    and `where` start from) instead of `next_action`."""
    root = temp_dir("qa-launch-pure-")
    try:
        controller = s5_story(root)
        with run_mode_env(None):
            action = controller._next_action_for_state(controller.state())
            check_eq("on a desktop story with a card on disk", action.get("action"), "wait_existing_job")
            check_eq("with exactly the keys it always had", sorted(action),
                     ["action", "cancel_allowed", "dispatch_id", "reason"])
            check_eq("and `next` is the one that launches", controller.next_action().get("action"), "launch")
    finally:
        cleanup(root)


# --- (i) a bound dispatch on an accepted stage -----------------------------------------------------------------

def a_dispatch_on_an_accepted_stage_is_judged_by_its_receipt_alone():
    """M-2 (L-2): a dispatch on a stage the controller already accepted (the rework of an accepted stage, the reporter
    after gate B) gets NO stage transition from `bind` (`stage_done` refuses it), so no `agent_id` reaches its record;
    the host receipt is its only evidence: none and verdict `unknown` -> launch, a receipt -> wait_existing_job.
    KILLS: have `launch_answer` take the missing `agent_id` of such a record for proof of no launch (the receipt
    case below then launches a running agent)."""
    root = temp_dir("qa-launch-accepted-")
    try:
        controller = SCOPED.gate_a_task(root)
        stamp(root, {"mode": "desktop"})
        identifier = "S1-qa-scout-9"
        s5_apply(controller, dict(dispatch_request(identifier, stage="S1", role="qa-scout"),
                                          known_paths={"root": str(root)}))
        launch_card.write(root, identifier, "card text\n")
        LIFE.without_hooklib()
        state = controller.state()
        check_eq("the stage stays accepted under the new dispatch", state["stages"]["S1"]["status"], "completed")
        check("and the record names no agent", not state["dispatches"][identifier].get("agent_id"))
        with run_mode_env(None):
            check_eq("no receipt, verdict unknown: launch", answer(root).get("action"), "launch")
            REWORK.host_receipt(root, agent_id="a1", agent_type="qa-scout", task_id=root.name,
                                dispatch_id=identifier, status="running", bound_at=OLD)
            check_eq("a receipt names it: the wait, though the record has no agent id",
                     answer(root).get("action"), "wait_existing_job")
    finally:
        cleanup(root)


# --- the card text itself ----------------------------------------------------------------------------------

def the_card_text_is_the_block_start_always_printed():
    """KILLS: change a line of `launch_card.render` (the bind line, the finish line, the S5 critic's door)."""
    text = launch_card.render("T-1", "qa-scout", "S1-qa-scout-1", "PROMPT", "")
    check_eq("the block, line by line", text.splitlines(), [
        "--- Agent prompt, verbatim; subagent_type: qa-scout ---", "PROMPT",
        "--- the moment the Agent call returns an id: on Claude the plugin's hook binds it; by hand only on Codex "
        "or when the guard or `where` says unbound: story_step.py bind --task T-1 --dispatch-id S1-qa-scout-1 "
        "--agent-id <id> ---",
        '--- after the digest: story_step.py finish --task T-1 --dispatch-id S1-qa-scout-1 --digest "<digest>" ---'])
    check("it ends in one newline", text.endswith("---\n") and not text.endswith("\n\n"))
    # F-3: the card does not order the manual bind on Claude, and keeps the prefix `story_run.parse_prompt` ends the prompt on
    bind_line = text.splitlines()[2]
    check("the bind line keeps the prefix story_run reads", bind_line.startswith("--- the moment the Agent call returns"), bind_line)
    check_in("the bind line says the plugin's hook binds it on Claude", "on Claude the plugin's hook binds it", bind_line)
    door = story_step._finish_door("S5", "qa-code-critic")
    check_in("the S5 critic's finish line carries its extra door", "finish --unresolved <why> --reason",
             launch_card.render("T-1", "qa-code-critic", "d", "p", door))
    check_eq("another role's does not", story_step._finish_door("S5", "qa-automator"), "")
    root = temp_dir("qa-launch-write-")
    try:
        path = launch_card.write(root / "deeper", "d-1", text)
        check_eq("write creates the folder and keeps the bytes", path.read_bytes(), text.encode("utf-8"))
        check_eq("and leaves no temporary file behind", [p.name for p in path.parent.iterdir()], ["d-1.launch.md"])
        launch_card.write(root / "deeper", "d-1", "second\n")
        check_eq("a second write replaces it whole", path.read_text(encoding="utf-8"), "second\n")
    finally:
        cleanup(root)


def main():
    start_prints_the_card_path_before_its_slow_steps()
    a_refused_apply_prints_no_id_and_no_card_path()
    start_writes_the_card_last_and_prints_the_same_bytes()
    a_card_that_cannot_be_written_is_a_note_and_the_block_is_printed()
    next_launches_what_nothing_shows_launched()
    any_evidence_of_a_launch_forbids_it()
    a_context_probe_receipt_of_the_story_and_role_is_evidence()
    a_dispatch_the_host_proves_alive_still_waits()
    returned_abandoned_and_unproved_keep_the_wait()
    a_reader_that_cannot_run_is_named_in_the_evidence()
    next_and_where_take_the_one_dict_launch_answer_builds()
    no_project_config_gives_the_old_answer()
    no_card_waits_and_where_rebuilds_it_from_the_brief()
    the_card_waits_for_the_form_when_the_registry_owes_one()
    no_contract_for_the_pair_the_brief_alone_launches()
    a_rebuilt_card_is_the_card_start_wrote()
    the_rebuilt_s5_critic_card_carries_the_probe_debt()
    an_unnamed_codex_denial_row_forbids_launch_in_next_and_where()
    an_unbound_running_receipt_forbids_launch()
    an_unbound_terminal_receipt_is_evidence_unless_proven_older()
    other_modes_get_the_old_answer()
    a_record_without_its_parts_gets_no_launch_and_no_exception()
    the_card_of_dispatch_2_never_answers_dispatch_3()
    the_pure_reader_is_unchanged()
    a_dispatch_on_an_accepted_stage_is_judged_by_its_receipt_alone()
    the_card_text_is_the_block_start_always_printed()
    harness.finish("test_launch_card")


if __name__ == "__main__":
    main()
