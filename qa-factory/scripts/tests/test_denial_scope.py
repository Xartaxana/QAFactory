#!/usr/bin/env python3
"""A refusal belongs to ONE dispatch, and a launch after it outweighs it.

Wave 5 made the spawn guard trust the controller's status: a dispatch recorded as
`never_started` frees a replacement spawn of its role. So what closes a running dispatch as
`never_started` became what lets a SECOND automator start beside a live one.

`_denied` used to treat a denial record that names NO dispatch - the Codex desktop host's
prompt is opaque, so `inject_context.dispatch_id_of` answers None there - as the refusal of
ANY running dispatch of the same role and stage, with no time bound; and `liveness_fixes`
closed a denied dispatch without asking whether it was alive. The critic's probe: a fresh host
receipt naming S5-qa-automator-1 plus a denial of 2026-01-01 with `dispatch_id: null` ->
`dispatch_liveness.state` says `alive`, `next` answers `relaunch`, the status becomes
`never_started`. The same held for a denial that was followed by a successful retry.

Everything runs on a fixed clock (FR-31): the dispatch starts at START, `liveness_fixes` is
asked at NOW, file times are set with os.utime, nothing sleeps. Only the end-to-end probe
uses the real clock, because `next` and `recover` take none - its times are relative to it.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, s5_apply, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import dispatch_liveness as DL  # noqa: E402
import worker_lifecycle  # noqa: E402
from controller import Controller, NEVER_STARTED, STALE_AFTER_CLOSURE  # noqa: E402

import test_controller_rework as REWORK  # noqa: E402  (at_s5: a running S5 automator, no agent)
import test_dispatch_liveness as LIFE  # noqa: E402  (transcript / fake_hooklib fixtures)
import test_story_closed as CLOSED  # noqa: E402  (closed_story / GHOST)

D1 = REWORK.AUTOMATOR                    # S5-qa-automator-1
D2 = "S5-qa-automator-2"
START = 1_800_000_000.0                  # the epoch second the receipt of D1 was journalled
NOW = START + 5000.0                     # late enough that a receipt of START is stale (600 s)
LINE = "the dispatch hook refused the Agent call (state/dispatch-denials.jsonl)"


def iso(epoch):
    """The shape `inject_context.note_denial` writes: UTC, whole seconds, explicit offset."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def denial(when=None, dispatch_id=None, **extra):
    record = {"stage": "S5", "role": "qa-automator", "dispatch_id": dispatch_id,
              "reason": "stage guard refused S5"}
    if when is not None:
        record["at"] = iso(when)
    record.update(extra)
    return record


def write_denials(root, *records, raw=()):
    path = root / "state" / "dispatch-denials.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + "".join(l + "\n" for l in raw),
                    encoding="utf-8")


def controller_at(root, starts):
    """The story's controller with the dispatch start times FIXED: the real ones are the moment
    the test ran, and a boundary at 60 s needs a clock it can stand on."""
    class Fixed(Controller):
        def _dispatch_starts(self):
            return dict(starts)
    return Fixed(root)


def receipt(root, name="r1", file_age=5000, **fields):
    """A host receipt of the automator of this story naming D1, written `file_age` s before NOW.
    The default is old on purpose: with no `bound_at` the file time is all a receipt has, and a
    stale one leaves the liveness verdict at `unknown`, so what a test shows is the denial rule's
    own veto and not the liveness one. A field set to None is dropped."""
    record = {"agent_id": name, "agent_type": "qa-automator", "task_id": root.name,
              "dispatch_id": D1, "status": "running"}
    record.update(fields)
    record = {key: value for key, value in record.items() if value is not None}
    path = root / "qa-factory" / "state" / "host-dispatches" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, (NOW - file_age, NOW - file_age))
    return path


def story(prefix, starts=None):
    root = temp_project(prefix)
    LIFE.without_hooklib()
    REWORK.at_s5(root)
    return root, controller_at(root, {D1: START} if starts is None else starts)


def closed_ids(controller, now=NOW):
    return [fix["dispatch_id"] for fix in controller.liveness_fixes(now=now)]


# --- the control: today's behaviour, unchanged ------------------------------------------------

def a_denial_with_nothing_after_it_still_closes_the_dispatch():
    root, ctl = story("qa-denial-control-")
    try:
        write_denials(root, denial(START + 60, dispatch_id=D1))
        fixes = ctl.liveness_fixes(now=NOW)
        check_eq("a named denial, nothing after it: closed", [f["dispatch_id"] for f in fixes], [D1])
        check_eq("as never_started", fixes[0]["kind"], NEVER_STARTED)
        check_eq("with today's evidence line, word for word", fixes[0]["reason"],
                 f"recover: {D1} was recorded as running but its role never launched — {LINE}")
        check_eq("never_started_fixes sees it too", len(ctl.never_started_fixes()), 1)
        write_denials(root, denial(START + 60, dispatch_id="S5-qa-automator-9"))
        check_eq("a denial that names ANOTHER dispatch is not this one's", closed_ids(ctl), [])
    finally:
        cleanup(root)


def the_files_edges_are_as_they_were():
    root, ctl = story("qa-denial-file-")
    try:
        check_eq("no denials file: nothing closed", closed_ids(ctl), [])
        write_denials(root)
        check_eq("an empty file: nothing closed", closed_ids(ctl), [])
        write_denials(root, raw=["{broken", "[1, 2]", '"text"', "null", "42", "", "   "])
        check_eq("broken lines and lines that are not objects: nothing closed", closed_ids(ctl), [])
        write_denials(root, denial(START + 60, dispatch_id=D1), raw=["{broken", "[1]", "null"])
        check_eq("and they do not hide a real record beside them", closed_ids(ctl), [D1])
        # A named record needs no time at all: test_post_commit_refresh writes exactly this.
        write_denials(root, {"dispatch_id": D1})
        check_eq("a named record with no time still closes it", closed_ids(ctl), [D1])
    finally:
        cleanup(root)


# --- item 1: which denial belongs to a dispatch ------------------------------------------------

def an_unnamed_denial_belongs_to_a_dispatch_by_role_stage_and_time():
    root, ctl = story("qa-denial-unnamed-")
    try:
        for offset, counts in ((-61, False), (-60, True), (-1, True), (0, True), (5, True),
                               (4000, True)):
            write_denials(root, denial(START + offset))
            check_eq(f"an unnamed denial {offset:+d} s from the start "
                     f"{'counts' if counts else 'does not count'}", closed_ids(ctl),
                     [D1] if counts else [])
        write_denials(root, denial(START + 5))
        check_eq("it closes as never_started on today's line",
                 [(f["kind"], f["reason"].split(" — ")[-1]) for f in ctl.liveness_fixes(now=NOW)],
                 [(NEVER_STARTED, LINE)])
        write_denials(root, denial(START + 5, role="qa-case-critic"))
        check_eq("another role's denial is not this dispatch's", closed_ids(ctl), [])
        write_denials(root, denial(START + 5, stage="S4"))
        check_eq("another stage's denial is not this dispatch's", closed_ids(ctl), [])
        write_denials(root, denial(START + 5, role=None, stage=None))
        check_eq("a denial with no role and no stage is nobody's", closed_ids(ctl), [])
    finally:
        cleanup(root)


def an_unnamed_denial_without_a_usable_time_does_not_count():
    root, ctl = story("qa-denial-badtime-")
    try:
        good = START + 5
        for label, extra in (("a missing time", {}), ("a null time", {"at": None}),
                             ("an empty time", {"at": ""}), ("a word", {"at": "yesterday"}),
                             ("true", {"at": True}), ("false", {"at": False}),
                             ("an epoch integer", {"at": int(good)}),
                             ("an epoch float", {"at": good}),
                             ("a date with no time", {"at": "2027-01-15"}),
                             ("a time with no offset", {"at": "2027-01-15T10:00:00"}),
                             ("an impossible date", {"at": "2027-13-45T00:00:00+00:00"}),
                             ("a list", {"at": ["2027-01-15T10:00:00+00:00"]}),
                             ("an object", {"at": {}})):
            write_denials(root, denial(None, **extra))
            check_eq(f"an unnamed denial with {label} does not count", closed_ids(ctl), [])
        write_denials(root, denial(good))
        check_eq("control: the same record with the writer's own time counts", closed_ids(ctl), [D1])
        write_denials(root, denial(None, dispatch_id=D1, at="yesterday"))
        check_eq("a NAMED record needs no usable time", closed_ids(ctl), [D1])
    finally:
        cleanup(root)


def an_unknown_start_means_an_unnamed_denial_does_not_count():
    root, ctl = story("qa-denial-nostart-", starts={})
    try:
        write_denials(root, denial(START + 5))
        check_eq("no start for the dispatch: an unnamed denial does not count", closed_ids(ctl), [])
        write_denials(root, denial(START + 5, dispatch_id=D1))
        check_eq("a named one still does", closed_ids(ctl), [D1])
    finally:
        cleanup(root)


def an_unnamed_denial_belongs_to_the_latest_dispatch_started_before_it():
    root, _ = story("qa-denial-next-")
    try:
        first = Controller(root)
        first.release_dispatch(D1, "the person says nobody works on it")
        s5_apply(first, {"id": D2, "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                 "input_hash": "s5-input", "budget": {},
                                 "known_paths": {"root": str(root)}, "idempotency_key": "d2"})
        ctl = controller_at(root, {D1: START, D2: START + 500})
        dispatches = ctl.state()["dispatches"]

        def owners(when, **extra):
            write_denials(root, denial(when, **extra))
            return [name for name in (D1, D2)
                    if ctl._denied(dispatches[name], now=NOW)]

        check_eq("a denial between the two starts is the first one's", owners(START + 100), [D1])
        check_eq("a denial after the second started is the second one's ONLY", owners(START + 700), [D2])
        check_eq("a denial 10 s before the second started is still the first one's, and not both",
                 owners(START + 490), [D1])
        check_eq("a denial 30 s before the FIRST started (skew) is the first one's, not both",
                 owners(START - 30), [D1])
        check_eq("a denial 61 s before the first started is nobody's", owners(START - 61), [])
        check_eq("a named denial is its own dispatch's whatever the times",
                 owners(START + 700, dispatch_id=D1), [D1])
    finally:
        cleanup(root)


# --- item 2: a launch after the refusal outweighs it -----------------------------------------

def a_receipt_of_this_dispatch_after_the_refusal_outweighs_it():
    root, ctl = story("qa-denial-receipt-")
    try:
        denied_at = START + 60
        for label, fields, expect_closed in (
                ("no receipt", None, True),
                ("a receipt written LATER than the refusal", {"bound_at": START + 120}, False),
                ("a receipt written EARLIER than the refusal", {"bound_at": START + 10}, True),
                ("a receipt written in the same second as the refusal", {"bound_at": denied_at}, False),
                ("a receipt with no bound_at (written before wave 5)", {}, False),
                ("a receipt whose bound_at is a word", {"bound_at": "soon"}, False),
                ("a receipt whose bound_at is true", {"bound_at": True}, False),
                ("a receipt whose bound_at is zero", {"bound_at": 0}, False),
                ("a TERMINAL receipt, later", {"bound_at": START + 120, "status": "terminal"}, True),
                ("a receipt of ANOTHER story, later", {"bound_at": START + 120, "task_id": "OTHER-1"}, True),
                ("a receipt naming ANOTHER dispatch, later",
                 {"bound_at": START + 120, "dispatch_id": "S5-qa-automator-7"}, True)):
            write_denials(root, denial(denied_at, dispatch_id=D1))
            for old in (root / "qa-factory" / "state" / "host-dispatches").glob("*.json"):
                old.unlink()
            if fields is not None:
                receipt(root, **fields)
            check_eq(f"named denial + {label}: " + ("closed" if expect_closed else "not closed"),
                     closed_ids(ctl), [D1] if expect_closed else [])
        write_denials(root, denial(denied_at))
        for label, fields, expect_closed in (
                ("an UNNAMED denial + a later receipt", {"bound_at": START + 120}, False),
                ("an UNNAMED denial + an earlier receipt", {"bound_at": START + 10}, True)):
            for old in (root / "qa-factory" / "state" / "host-dispatches").glob("*.json"):
                old.unlink()
            receipt(root, **fields)
            check_eq(f"{label}: " + ("closed" if expect_closed else "not closed"),
                     closed_ids(ctl), [D1] if expect_closed else [])
    finally:
        cleanup(root)


def a_denial_with_no_time_is_not_proved_older_than_a_receipt():
    root, ctl = story("qa-denial-notime-")
    try:
        write_denials(root, {"dispatch_id": D1})
        receipt(root, bound_at=START + 10)
        check_eq("a named denial that carries no time cannot show the receipt came first: not closed",
                 closed_ids(ctl), [])
    finally:
        cleanup(root)


def a_dispatch_liveness_calls_alive_is_never_closed_by_a_denial():
    root, ctl = story("qa-denial-alive-")
    try:
        write_denials(root, denial(START + 60, dispatch_id=D1))
        check_eq("control: with nothing alive the named denial closes it", closed_ids(ctl), [D1])

        fresh = LIFE.transcript(root, "mine", D1, ticket=root.name)
        os.utime(fresh, (NOW - 10, NOW - 10))
        LIFE.fake_hooklib([fresh])
        check_eq("a fresh transcript of this dispatch and no receipt: the denial closes nothing",
                 closed_ids(ctl), [])
        write_denials(root, denial(START + 60))
        check_eq("nor does an unnamed one", closed_ids(ctl), [])
        LIFE.without_hooklib()

        # ALIVE through the receipt alone: written BEFORE the refusal (so rule (a) cannot veto)
        # and young enough that liveness calls it alive.
        write_denials(root, denial(NOW - 50, dispatch_id=D1))
        receipt(root, bound_at=NOW - 100)
        check_eq("the liveness verdict itself is alive", DL.state(
            root, root.name, {"id": D1, "role": "qa-automator", "stage": "S5", "started_at": START},
            now=NOW)["state"], DL.ALIVE)
        check_eq("a fresh receipt written before the refusal: the dispatch is alive, not closed",
                 closed_ids(ctl), [])
    finally:
        LIFE.without_hooklib()
        cleanup(root)


def a_liveness_check_that_raises_is_a_veto_not_a_precondition():
    root, ctl = story("qa-denial-raises-")
    original = DL.state

    def broken(*args, **kwargs):
        raise RuntimeError("the helper is not installed")

    try:
        DL.state = broken
        write_denials(root, denial(START + 60, dispatch_id=D1))
        check_eq("a denial that belongs to the dispatch still closes it", closed_ids(ctl), [D1])
        receipt(root, bound_at=START + 120)
        check_eq("EXCEPT when a receipt after the refusal already vetoed it", closed_ids(ctl), [])
        write_denials(root)
        check_eq("and with no denial a raising check closes nothing, as before", closed_ids(ctl), [])
    finally:
        DL.state = original
        cleanup(root)


# --- item 3: the second caller of _denied -----------------------------------------------------

def the_closure_repair_asks_the_same_question():
    root = temp_project("qa-denial-closure-")
    try:
        LIFE.without_hooklib()
        controller = CLOSED.closed_story(root)
        CLOSED.stray(controller, CLOSED.GHOST)      # C1-6a: `dispatch` refuses work on a closed story; the tail is written past it
        denials = root / "state" / "dispatch-denials.jsonl"

        def settled():
            found = [f for f in Controller(root).closure_repairs()
                     if f["kind"] == STALE_AFTER_CLOSURE and f.get("dispatch_id") == CLOSED.GHOST]
            return [f["settled_as"] for f in found]

        def ghost_receipt():
            path = root / "qa-factory" / "state" / "host-dispatches" / "ghost.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"agent_id": "g", "agent_type": "qa-worker", "task_id": root.name,
                                        "dispatch_id": CLOSED.GHOST, "status": "running",
                                        "bound_at": time.time()}), encoding="utf-8")

        check_eq("no denial: the tail is superseded", settled(), ["superseded"])
        denials.parent.mkdir(parents=True, exist_ok=True)
        denials.write_text(json.dumps({"stage": "S3", "role": "qa-worker", "dispatch_id": CLOSED.GHOST,
                                       "at": iso(time.time())}) + "\n", encoding="utf-8")
        check_eq("a denial that belongs to it, nothing after: settled as never_started as today",
                 settled(), [NEVER_STARTED])
        ghost_receipt()
        check_eq("the same denial and a receipt written after it: the dispatch is alive, so superseded",
                 settled(), ["superseded"])
        (root / "qa-factory" / "state" / "host-dispatches" / "ghost.json").unlink()
        denials.write_text(json.dumps({"stage": "S3", "role": "qa-worker", "dispatch_id": None,
                                       "at": "2026-01-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
        check_eq("the probe's old unnamed denial no longer belongs to it: superseded, not never_started",
                 settled(), ["superseded"])
    finally:
        cleanup(root)


# --- the probe, end to end, and the spawn guard it feeds --------------------------------------

def layout(prefix, ticket="TP1-9001"):
    """A project with the story where the controller and the spawn guard both look for it:
    <project>/qa-factory/artifacts/<ticket>/. Without it `binding_is_active` cannot find the
    story's controller.json and answers True for a reason that has nothing to do with the fix."""
    project = temp_project(prefix)
    art = project / "qa-factory" / "artifacts" / ticket
    art.mkdir(parents=True)
    controller = REWORK.at_s5(art)
    # The gate-A fixture drops a config.json of its own INSIDE the story, which would make the
    # story its own project: the controller would then look for receipts under the story and
    # the spawn guard under the project, and the two would never see the same file.
    (art / "qa-factory" / "config.json").unlink()
    check_eq("the controller's project is the project, where a real story lives",
             controller._project_root(), project.resolve())
    return project, art, controller


def host_receipt(project, ticket, **fields):
    record = {"agent_id": "a1", "agent_type": "qa-automator", "task_id": ticket, "dispatch_id": D1,
              "status": "running"}
    record.update(fields)
    path = project / "qa-factory" / "state" / "host-dispatches" / "one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def the_probe_launches_no_second_automator():
    LIFE.without_hooklib()
    project, art, controller = layout("qa-denial-probe-")
    try:
        write_denials(art, {"at": "2026-01-01T00:00:00+00:00", "stage": "S5", "role": "qa-automator",
                            "dispatch_id": None, "reason": "stage guard refused S5"})
        host_receipt(project, art.name, bound_at=time.time())
        started = Controller(art)._dispatch_starts()[D1]
        check_eq("the critic's probe: liveness says the dispatch is alive", DL.state(
            project, art.name, {"id": D1, "role": "qa-automator", "stage": "S5",
                                "started_at": started})["state"], DL.ALIVE)
        check_eq("so the controller closes nothing", Controller(art).never_started_fixes(), [])
        action = Controller(art).next_action()
        check("and `next` does not answer relaunch", action["action"] != "relaunch", action["action"])
        check_eq("it keeps waiting for the live agent", (action["action"], action.get("liveness")),
                 ("wait_existing_job", DL.ALIVE))
        check_eq("the status stays running", Controller(art).state()["dispatches"][D1]["status"],
                 "running")
        check_eq("recover repairs nothing", Controller(art).recover()["journalled_repairs"], [])
        binding = DL.host_bindings(project)[0]
        check("the story's controller.json is where the spawn guard looks for it",
              (art / "state" / "controller.json").is_file())
        check_eq("so the spawn guard still sees an ACTIVE worker: no second automator",
                 worker_lifecycle.binding_is_active(project, binding), True)
    finally:
        cleanup(project)


def a_refusal_with_nothing_after_it_still_frees_the_spawn():
    LIFE.without_hooklib()
    project, art, controller = layout("qa-denial-probe-control-")
    try:
        now = time.time()
        write_denials(art, {"at": iso(now - 1000), "stage": "S5", "role": "qa-automator",
                            "dispatch_id": D1, "reason": "stage guard refused S5"})
        host_receipt(project, art.name, bound_at=now - 5000)     # an earlier launch, long silent
        binding = DL.host_bindings(project)[0]
        check_eq("control: before recover the receipt is an active one",
                 worker_lifecycle.binding_is_active(project, binding), True)
        action = Controller(art).next_action()
        check_eq("a denial with a stale launch before it: next closes the dispatch and relaunches",
                 action["action"], "relaunch")
        check_eq("as never_started", Controller(art).state()["dispatches"][D1]["status"], NEVER_STARTED)
        check_eq("and only then the spawn guard lets a replacement through",
                 worker_lifecycle.binding_is_active(project, binding), False)
    finally:
        cleanup(project)


def main():
    a_denial_with_nothing_after_it_still_closes_the_dispatch()
    the_files_edges_are_as_they_were()
    an_unnamed_denial_belongs_to_a_dispatch_by_role_stage_and_time()
    an_unnamed_denial_without_a_usable_time_does_not_count()
    an_unknown_start_means_an_unnamed_denial_does_not_count()
    an_unnamed_denial_belongs_to_the_latest_dispatch_started_before_it()
    a_receipt_of_this_dispatch_after_the_refusal_outweighs_it()
    a_denial_with_no_time_is_not_proved_older_than_a_receipt()
    a_dispatch_liveness_calls_alive_is_never_closed_by_a_denial()
    a_liveness_check_that_raises_is_a_veto_not_a_precondition()
    the_closure_repair_asks_the_same_question()
    the_probe_launches_no_second_automator()
    a_refusal_with_nothing_after_it_still_frees_the_spawn()
    finish("test_denial_scope")


if __name__ == "__main__":
    main()
