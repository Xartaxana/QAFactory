#!/usr/bin/env python3
"""FB-9 (TP1-14857, spec t-1361, node SC3-7): `story_step.py start` registers a manual runner block the way the driver does.

  collector     K-S1..K-S4, K-S6, K-R11: `manual_block_problems` lists every problem; `manual_blocks`; the head number
  membership    K-M1..K-M5: the plan's manual half, checked by the controller on every road (one sentence per cause)
  skill road    K-R1..K-R10, K-P1, K-P2, K-T1..K-T3, K-B1..K-B4: `start` in-process, the real controller, `_run` and the
                file writers stubbed; refusal keys once through the CLI (`harness.run_script`)
  card          K-D1: the S6 card and `start --help` name the rule (negative control inside)

Each check names the ONE mutation that kills it in its docstring. The story is built the way
`test_story_run_s6.t289_real_story` builds it: S0..S5 accepted, gate A, TC-1 `automate`, TC-2.. `manual-agent`.
"""
import contextlib
import io
import json
import os
import re
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller as CT  # noqa: E402
import detector_verdict  # noqa: E402
import manual_evidence  # noqa: E402
import story_progress  # noqa: E402
import story_step  # noqa: E402
from controller import (MANUAL_BLOCK_CASES, SCOPE_SHOWN, manual_block_problems, manual_blocks,  # noqa: E402
                        manual_done_cases, validate_manual_runner_block)
from event_store import StateConflict  # noqa: E402

import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row fixture)
import test_controller_state as BASE  # noqa: E402  (accept_stage / seed_plan / bind_gate_a fixtures)
import test_fixes_13797 as F  # noqa: E402  (`runner`: dispatch + accept of a qa-runner packet)
import test_story_step as STEP  # noqa: E402  (open_story: a CLI-ready story)

PREFIX = "manual runner block must name 1..5 unique in-scope cases:"
TASK = "QA-9"
NON_ASCII = chr(0x442)        # a Cyrillic letter, spelled as a code point (FR-30: no Cyrillic byte in the package)


# --- fixtures ---------------------------------------------------------------------------------------------
def real_story(root, dispositions):
    """A story in the NEW plan-contract mode through gate A and S5; case i is `TC-i`, its plan row `TS-i` is disposed
    `dispositions[i - 1]`. Returns the real controller. `pipeline.json` has NO `run_mode` (the stamp is observable)."""
    cases = [f"TC-{i}" for i in range(1, len(dispositions) + 1)]
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    c = CT.Controller(root)
    c.apply("initialize", {"scope": cases, "source_revision": "src-1", "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    BASE.seed_plan(root, [SCOPED.plan_row(i, d) for i, d in enumerate(dispositions, 1)])
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": case, "version": f"cv_{i}"} for i, case in enumerate(cases, 1)]}), encoding="utf-8")
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
                "source_revision": "src-1", "scope": cases, "input_revision": "src-1", "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))
    BASE.accept_stage(c, root, "S5")
    pipeline = root / "pipeline.json"
    data = json.loads(pipeline.read_text(encoding="utf-8-sig")) if pipeline.is_file() else {"ticket": TASK, "stages": {}}
    data.pop("run_mode", None)
    pipeline.write_text(json.dumps(data), encoding="utf-8")
    return c


MIXED_7 = ["automate"] + ["manual-agent"] * 6          # TC-1 automated, TC-2..TC-7 manual (a block of five and one more)


def args_for(scope, kind="manual", **more):
    return types.SimpleNamespace(**dict(dict(task=TASK, stage="S6", role="qa-runner", id=None, scope=scope, purpose=None,
                                            execution_kind=kind, wait_seconds=0.0), **more))


def start(root, ctl, scope, kind="manual", prepare=None, **more):
    """`story_step.start` in-process against the real controller; every other side effect stubbed. Returns (code, text, seen)."""
    seen = {"prepared": [], "scope": [], "revision_at_prepare": []}

    def fake_prepare(task_root, case):
        seen["prepared"].append(case)
        seen["revision_at_prepare"].append(ctl.state()["revision"])
        return prepare(case) if prepare else ([f"OB-{case}"], "", "")

    def fake_files(task, stage, role, did, task_root, scope_arg, notes):
        seen["scope"].append(scope_arg)
        return "CARD\n", None

    out = io.StringIO()
    with contextlib.ExitStack() as stack:
        for name, value in (("_task_root", lambda task: root), ("_run", lambda *a, **k: (0, "")),
                            ("_pre_work", lambda *a, **k: []), ("_derive_before", lambda *a, **k: []),
                            ("_settle_probe_debt", lambda *a, **k: ("", [])), ("_s5_plan_init", lambda *a, **k: []),
                            ("_write_dispatch_files", fake_files), ("config_fingerprint", lambda: "fp"),
                            ("Controller", lambda task_root, wait_seconds=0.0: ctl)):
            stack.enter_context(mock.patch.object(story_step, name, value))
        if prepare is not False:
            stack.enter_context(mock.patch.object(manual_evidence, "prepare_for_block", fake_prepare))
        stack.enter_context(contextlib.redirect_stdout(out))
        code = story_step.start(args_for(scope, kind, **more))
    return code, out.getvalue(), seen


def door_scope(text):
    found = re.search(r"--execution-kind manual --scope (\S+)", text)
    return found.group(1) if found else None


def accept(ctl, root, did, kind, scope, complete=False):
    return F.runner(ctl, root, did, kind, scope, complete)


# --- the collector and the pure functions -----------------------------------------------------------------
def the_collector_lists_every_problem():
    """K-S1. KILLS: `problems[:1]` / an early return in `manual_block_problems`; positions counted from 0."""
    ids = ["TC-1", "TC-1", 3, "x", None, "y"]
    problems = manual_block_problems(["TC-1"], ids)
    check_eq("K-S1: the count", len(problems), 4)
    check_in("K-S1: the size problem", "it names 6 cases, at most 5: split the block", problems)
    check_in("K-S1: positions are 1-based", "entries that are not case ids at position(s) 3, 5", problems)
    check_in("K-S1: the repeat", "named more than once: TC-1", problems)
    check_in("K-S1: the outsiders", "not in the dispatch scope: x, y", problems)
    try:
        validate_manual_runner_block(["TC-1"], ids)
        text = ""
    except StateConflict as exc:
        text = str(exc)
    items = detector_verdict.split_items(text)
    check_eq("K-S1: the refusal is ONE compound answer of those items (`split_items`)", len(items or []), 4)
    check_eq("K-S1: its first line is the prefix", text.splitlines()[0], PREFIX)
    check_eq("K-S1: a non-list stops at ONE problem", manual_block_problems(["TC-1"], "TC-1"),
             ["manual_case_ids is not a list of case ids (it is str)"])
    check_eq("K-S1: an empty block", manual_block_problems(["TC-1"], []), ["it names no case"])


def the_collector_accepts_exactly_what_today_accepts():
    """K-S2, literal verdicts (X3). KILLS: the >5 check removed, the duplicates check removed, a (6) that is not `_subset_of`'s."""
    table = (
        (["TC-1"], ["TC-1"], True), (["TC-1", 5], ["TC-1"], True), ({"TC-1"}, ["TC-1"], True),
        (["TC-1", "TC-2", "TC-3", "TC-4", "TC-5"], ["TC-1", "TC-2", "TC-3", "TC-4", "TC-5"], True),
        (["TC-1"], None, False), (["TC-1"], "TC-1", False), (["TC-1"], [], False),
        ([f"TC-{i}" for i in range(6)], [f"TC-{i}" for i in range(6)], False),
        (["TC-1"], ["TC-1", "TC-1"], False), (["TC-1"], ["TC-1", ""], False), (["TC-1"], ["TC-1", 3], False),
        (["TC-1"], [["TC-1"]], False), (5, ["TC-1"], False), ([["TC-1"]], ["TC-1"], False), (None, ["TC-1"], False),
        (["TC-2"], ["TC-1"], False))
    for scope, ids, accepted in table:
        check_eq(f"K-S2: scope {scope!r}, ids {ids!r} -> {'accepted' if accepted else 'refused'}",
                 not manual_block_problems(scope, ids), accepted)
    five, six = [f"TC-{i}" for i in range(5)], [f"TC-{i}" for i in range(6)]
    check_eq("K-S2: AT the limit nothing is said about size", [p for p in manual_block_problems(five, five) if "split" in p], [])
    check_in("K-S2: BEYOND it the split is said", "split the block", manual_block_problems(six, six))


def the_split_and_the_head_number():
    """K-S3, K-S4. KILLS: `manual_blocks` returning `cases[:size]`; a head literal that drifts from the constant."""
    names = [f"TC-{i}" for i in range(11)]
    check_eq("K-S3: 5 is one block", manual_blocks(names[:5]), [names[:5]])
    check_eq("K-S3: 6 is 5 + 1", manual_blocks(names[:6]), [names[:5], names[5:6]])
    check_eq("K-S3: 11 is 5 + 5 + 1", manual_blocks(names), [names[:5], names[5:10], names[10:]])
    check_eq("K-S3: nothing is nothing", manual_blocks([]), [])
    check_eq("K-S3: a size of 2 keeps the order", manual_blocks(names[:5], 2), [names[:2], names[2:4], names[4:5]])
    try:
        manual_blocks(names, 0)
        check("K-S3: size 0 is a ValueError", False)
    except ValueError:
        check("K-S3: size 0 is a ValueError", True)
    check_eq("K-S4: the head literal says the constant", f"1..{MANUAL_BLOCK_CASES} unique" in PREFIX, True)
    source = Path(CT.__file__).read_text(encoding="utf-8")
    check_in("K-S4: and the controller's raise carries that very literal", f'prefix="{PREFIX}"', source)


def the_done_set_counts_accepted_manual_only():
    """K-S6. KILLS: `manual_done_cases` ignoring the kind or the status."""
    state = {"dispatches": {
        "a": {"stage": "S6", "status": "accepted", "execution_kind": "manual", "manual_case_ids": ["TC-2", "TC-3"]},
        "b": {"stage": "S6", "status": "accepted", "execution_kind": "automation", "scope": ["TC-1"], "manual_case_ids": ["TC-9"]},
        "c": {"stage": "S6", "status": "running", "execution_kind": "manual", "manual_case_ids": ["TC-4"]},
        "d": {"stage": "S5", "status": "accepted", "execution_kind": "manual", "manual_case_ids": ["TC-5"]}}}
    check_eq("K-S6: only the accepted manual S6 record", manual_done_cases(state), {"TC-2", "TC-3"})
    check_eq("K-S6: no state, no cases", manual_done_cases({}), set())


def a_list_is_named_at_and_beyond_the_shown_limit():
    """K-R11 (E15). KILLS: the `named` limit 19 / 21 (the tail at 20 or none at 21)."""
    for count, tail in ((SCOPE_SHOWN, False), (SCOPE_SHOWN + 1, True)):
        ids = [f"A{i}" for i in range(count)] * 2
        text = "\n".join(manual_block_problems([], ids))
        named = [p for p in manual_block_problems([], ids) if p.startswith("named more than once")][0]
        check_eq(f"K-R11: {count} repeated ids -> {'a tail' if tail else 'the whole list'}", "and 1 more" in named, tail)
        check_in(f"K-R11: {count} -> the first is named", "A0", text)


# --- the membership (controller road) ---------------------------------------------------------------------
def membership_is_split_by_cause_and_every_road_meets_it():
    """K-M1..K-M5. KILLS: automate and handed joined in one sentence (M22); the check removed from `Controller.validate` (M15)
    or `prepare`; the S6 gate removed; the skip when the scope is not derived removed."""
    root = temp_dir("qa-fb9-member-")
    try:
        c = real_story(root, MIXED_7)
        c._handed_cases = lambda: {"TC-3": "profile-x"}
        got = c._half_membership_problems("S6", c.state(), ["TC-1", "TC-3", "TC-99", "TC-2"], "manual")
        check_eq("K-M1: three causes, three sentences", len(got), 3)
        check_in("K-M1: automate names the automated half as its door", "disposed automate in the plan: TC-1", got[0])
        check_in("K-M1: ...and the plan road", "--execution-kind automation", got[0])
        check_in("K-M1: ...and the disposition change", "S3 rework, then gate A", got[0])
        check_in("K-M1: a manual-agent case the person took over is said so", "handed to the person by their recorded word: TC-3", got[1])
        check_not_in("K-M1: ...and never called 'not a manual-agent case'", "TC-3", got[2])
        check_in("K-M1: an id outside the plan has the stage-scope door", "not a manual-agent case of the approved plan: TC-99", got[2])
        check_in("K-M1: ...with its door", "--operation stage-scope", got[2])
        check_eq("K-M1 control: a manual-agent case is fine", c._half_membership_problems("S6", c.state(), ["TC-2"], "manual"), [])
        c._handed_cases = lambda: {}
        # K-M3: a hand-built request (the 14857 bypass) is refused on the controller's own road
        try:
            c.prepare({"stage": "S6", "role": "qa-runner", "id": "hb", "scope": ["TC-1"], "execution_kind": "manual",
                       "manual_case_ids": ["TC-1"]})
            check("K-M3: prepare refuses a manual block over an automated case", False)
        except StateConflict as exc:
            check_in("K-M3: prepare refuses a manual block over an automated case", "disposed automate in the plan: TC-1", str(exc))
        request = c.prepare({"stage": "S6", "role": "qa-runner", "id": "hb", "scope": ["TC-1"],
                             "execution_kind": "automation"})["dispatch_request"]
        request.update(execution_kind="manual", manual_case_ids=["TC-1"])
        try:
            c.apply("dispatch", request)
            check("K-M3: apply refuses the same hand-built packet", False)
        except StateConflict as exc:
            check_in("K-M3: apply refuses the same hand-built packet", "disposed automate in the plan: TC-1", str(exc))
        check_not_in("K-M3: and nothing was registered", "hb", c.state()["dispatches"])
        # K-M4: a stale block (a plan re-disposition) does not survive a CONTINUATION: a manual block is dispatched and paused,
        # the plan then re-disposes TC-4, and the retry packet the controller itself builds (`_retry_packet`) is refused.
        block = c.prepare({"stage": "S6", "role": "qa-runner", "id": "blk", "scope": ["TC-4", "TC-5"],
                           "execution_kind": "manual", "manual_case_ids": ["TC-4", "TC-5"]})["dispatch_request"]
        c.apply("dispatch", dict(block))
        c.apply("checkpoint", {"id": "blk", "status": "paused", "reason": "waiting on the stand",
                               "checkpoint": {"remaining": ["TC-4", "TC-5"]}, "idempotency_key": "cp-blk"})
        retry = CT.Controller._retry_packet(c.state(), c.state()["dispatches"]["blk"])
        check_eq("K-M4: the retry packet is a continuation that carries the stale block",
                 (bool(retry.get("parent_retry")), retry.get("manual_case_ids")), (True, ["TC-4", "TC-5"]))
        real = c._case_rows

        def redisposed(state):
            mapping, dispositions, basis = real(state)
            return mapping, dict(dispositions, **{"TS-4": "automate"}), basis
        c._case_rows = redisposed
        try:
            c.apply("dispatch", dict(retry))
            check("K-M4: after TC-4 was re-disposed automate, the retry of its manual block is refused", False)
        except StateConflict as exc:
            check_in("K-M4: after TC-4 was re-disposed automate, the retry of its manual block is refused",
                     "disposed automate in the plan: TC-4", str(exc))
        c._case_rows = real
        check_eq("K-M4 control: with the plan as it was, the same retry is accepted",
                 c.apply("dispatch", dict(retry)) is not None, True)
        # K-M2: an underived scope is a DECLARED skip
        with mock.patch.object(c, "stage_scope", lambda *a, **k: {"derived": False, "scope": [], "reason": "no dispositions"}):
            check_eq("K-M2: not derived -> no membership sentence", c._half_membership_problems("S6", c.state(), ["TC-1", "TC-99"], "manual"), [])
        # K-M5: only S6 has a manual half
        check_eq("K-M5: an S5 qa-runner block meets R1 only", c._half_membership_problems("S5", c.state(), ["TC-1"], "manual"), [])
        check_eq("K-M5: ...and a non-list is not read", c._half_membership_problems("S6", c.state(), "TC-1", "manual"), [])
    finally:
        cleanup(root)


# --- the skill road ---------------------------------------------------------------------------------------
def pipeline_bytes(root):
    return (root / "pipeline.json").read_bytes()


def five_registers_with_the_drivers_fields():
    """K-R1, K-T1, K-P1, K-T3, K-B4. KILLS: `manual_case_ids` not set (M4); `purpose` not set (M9); prepare skipped (M20);
    the raw `args.scope` handed to the form (M24)."""
    root, twin_root = temp_dir("qa-fb9-five-"), temp_dir("qa-fb9-twin-")
    try:
        c = real_story(root, MIXED_7)
        block = ["TC-2", "TC-3", "TC-4", "TC-5", "TC-6"]
        before_revision = c.state()["revision"]
        code, text, seen = start(root, c, ",".join(block))
        record = c.state()["dispatches"]["S6-qa-runner-1"]
        check_eq("K-R1: AT the limit, 5 cases: exit 0", code, 0)
        check_eq("K-R1: execution_kind, manual_case_ids, scope, purpose as the driver registers them",
                 (record.get("execution_kind"), record.get("manual_case_ids"), record.get("scope"), record.get("purpose")),
                 ("manual", block, block, "manual"))
        check_eq("K-P1: every case was prepared, in block order", seen["prepared"], block)
        check_eq("K-P1: ...BEFORE the dispatch event (the revision did not move)",
                 set(seen["revision_at_prepare"]), {before_revision})
        check_eq("K-B4: the form got the cleaned block", seen["scope"], [",".join(block)])
        check_eq("K-T3: progress reads the block as a manual block", story_progress._is_manual(record), True)
        # K-T1: the driver's own registration (`Driver.run_manual_block`, in-process) gives the same fields
        d = real_story(twin_root, MIXED_7)
        packet = d.prepare({"stage": "S6", "role": "qa-runner", "id": "S6-qa-runner-1", "scope": block,
                            "execution_kind": "manual", "manual_case_ids": list(block)})
        d.apply("dispatch", dict(packet["dispatch_request"], execution_kind="manual", manual_case_ids=list(block), purpose="manual"))
        twin = d.state()["dispatches"]["S6-qa-runner-1"]
        fields = ("execution_kind", "manual_case_ids", "scope", "purpose", "stage", "role")
        check_eq("K-T1: the skill road's record equals the driver's, field by field",
                 {k: record.get(k) for k in fields}, {k: twin.get(k) for k in fields})
        # spaces: the form header holds the stripped ids
        c2 = real_story(temp_dir("qa-fb9-space-"), MIXED_7)
        code, text, seen = start(c2.store.root, c2, " TC-2 , TC-3 ")
        check_eq("K-B4: `' TC-2 , TC-3 '` is dispatched stripped", (code, seen["scope"]), (0, ["TC-2,TC-3"]))
        cleanup(c2.store.root)
    finally:
        cleanup(root)
        cleanup(twin_root)


def six_is_refused_and_nothing_is_written():
    """K-R2, K-R2b, K-S5, K-B1. KILLS: the pre-check after `stamp_run_mode` (M5); the door from the raw block (M6); a refusal text
    that is not the controller's."""
    root = temp_dir("qa-fb9-six-")
    try:
        c = real_story(root, MIXED_7)
        before, revision = pipeline_bytes(root), c.state()["revision"]
        block = ["TC-2", "TC-3", "TC-4", "TC-5", "TC-6", "TC-7"]
        code, text, seen = start(root, c, ",".join(block))
        check_eq("K-R2: BEYOND the limit, exit 2", code, 2)
        check_in("K-R2: the controller's prefix", PREFIX, text)
        check_in("K-R2: the size problem, with the split", "it names 6 cases, at most 5: split the block", text)
        check_eq("K-R2: the door is the first lane (three guest cases)", door_scope(text), "TC-2,TC-3,TC-4")
        check_in("K-R2: and the rest is counted", "then 1 more block(s) of at most 3 case(s) for: TC-5, TC-6, TC-7", text)
        check_in("K-R2: --not-complete is said (X6)", "except the last S6 dispatch of the stage (manual or automation)", text)
        check_eq("K-R2: pipeline.json is byte-identical (no run_mode stamped)", pipeline_bytes(root), before)
        check_not_in("K-R2: ...and carries no run_mode", "run_mode", pipeline_bytes(root).decode("utf-8"))
        check_eq("K-R2: no event", c.state()["revision"], revision)
        check_eq("K-R2: no case prepared, no form written", (seen["prepared"], seen["scope"]), ([], []))
        # K-R2b: the printed door, run as the next start, is NOT refused again (E6, E7)
        dirty = "TC-2,TC-2,TC-3,TC-4,TC-5,TC-6,TC-99"
        code, text, seen = start(root, c, dirty)
        check_eq("K-R2b: duplicates + beyond + unknown: exit 2", code, 2)
        body = text.split("story_step: refused - ", 1)[1].split("\ndoor:", 1)[0]
        ids = [s.strip() for s in dirty.split(",")]
        extra = c._half_membership_problems("S6", c.state(), ids, "manual")
        try:
            validate_manual_runner_block(ids, ids, extra=extra)
            expected = ""
        except StateConflict as exc:
            expected = str(exc)
        check_eq("K-S5: the skill road's text IS the controller's", body.rstrip("\n"), expected)
        check_eq("K-R2b: three problems in one answer", len(detector_verdict.split_items(body) or []), 3)
        check_eq("K-R2b: the door is the first window of the cleaned block (deduped, TC-99 gone)", door_scope(text), "TC-2,TC-3,TC-4")
        check_in("K-R2b: ...and the cleaned rest is counted", "then 1 more block(s) of at most 3 case(s) for: TC-5, TC-6", text)
        code, _, _ = start(root, c, door_scope(text))
        check_eq("K-R2b: and running the door is accepted", code, 0)
        accept(c, root, "S6-qa-runner-1", "manual", ["TC-2", "TC-3", "TC-4"])
        code, text, _ = start(root, c, "TC-7,TC-7")
        check_in("K-R2b: E6, a repeat is named", "named more than once: TC-7", text)
        check_eq("K-R2b: ...and the door is the one case", door_scope(text), "TC-7")
    finally:
        cleanup(root)


def no_scope_prints_the_next_block():
    """K-R3, K-R4, K-R5. KILLS: the no-scope door ignoring the accepted blocks (M7); the not-derived branch printing ids (M8)."""
    root = temp_dir("qa-fb9-door-")
    try:
        c = real_story(root, MIXED_7)
        before, revision = pipeline_bytes(root), c.state()["revision"]
        for label, scope in (("no --scope", None), ("an empty one", ""), ("a comma", ","), ("commas and blanks", " , ,")):
            code, text, seen = start(root, c, scope)
            check_eq(f"K-R3: {label}: exit 2 with the next block", (code, door_scope(text)), (2, "TC-2,TC-3,TC-4"))
        check_in("K-R3: the refusal says what it wants", "a manual runner block names its cases (1..5 of them) with --scope", text)
        check_in("K-R3: and the rest", "then 1 more block(s) of at most 3 case(s) for: TC-5, TC-6, TC-7", text)
        check_eq("K-R3: nothing written", (pipeline_bytes(root), c.state()["revision"]), (before, revision))
        start(root, c, "TC-2")
        accept(c, root, "S6-qa-runner-1", "manual", ["TC-2"])
        code, text, _ = start(root, c, None)
        check_eq("K-R3: an accepted window is not offered again", (code, door_scope(text)), (2, "TC-3,TC-4,TC-5"))
        check_in("K-R3: ...and the tail counts one less", "then 1 more block(s) of at most 3 case(s) for: TC-6, TC-7", text)
        # a story in flight: a block of four (the old ceiling is still lawful) is accepted whole, and is not offered again
        start(root, c, "TC-3,TC-4,TC-5,TC-6")
        accept(c, root, "S6-qa-runner-2", "manual", ["TC-3", "TC-4", "TC-5", "TC-6"])
        code, text, _ = start(root, c, None)
        check_eq("K-R3: the rest after a block of four", (code, door_scope(text)), (2, "TC-7"))
        check_not_in("K-R3: ...and no 'more block' tail", "more block(s)", text)
        start(root, c, "TC-7")
        accept(c, root, "S6-qa-runner-3", "manual", ["TC-7"])
        code, text, _ = start(root, c, None)
        check_eq("K-R5: every manual-agent case in an accepted block: exit 2", code, 2)
        check_in("K-R5: the null outcome is named", "no manual-agent case is left for a block: nothing was dispatched", text)
        check_in("K-R5: ...with what covers them", "covered by TC-2, TC-3, TC-4, TC-5, TC-6, TC-7", text)
        check_eq("K-R5: no ids to run", door_scope(text), None)
        # K-R4: the scope could not be derived: no guess
        with mock.patch.object(c, "stage_scope", lambda *a, **k: {"derived": False, "scope": [], "reason": "plan rows declare no disposition"}):
            code, text, _ = start(root, c, None)
            check_eq("K-R4: no scope and nothing derived: exit 2, no ids", (code, door_scope(text)), (2, None))
            check_in("K-R4: the door says to name the cases, and why not derived",
                     "door: name the block's cases with --scope (1..5 ids); the stage scope could not be derived: plan rows declare no disposition", text)
    finally:
        cleanup(root)


def a_refused_case_leaves_the_block_and_the_door_is_cleaned():
    """K-P2 (E22-E24). KILLS: a block silently shrunk (dispatched without the refused case); the door built from the raw block."""
    root = temp_dir("qa-fb9-prep-")
    try:
        c = real_story(root, MIXED_7)
        revision = c.state()["revision"]
        refuse_3 = lambda case: ([], "no executable obligation - put the stand's account in the settings", "") if case == "TC-3" else ([f"OB-{case}"], "", "")  # noqa: E731
        code, text, seen = start(root, c, "TC-2,TC-3,TC-4", prepare=refuse_3)
        check_eq("K-P2: one of three refused: the start is refused", code, 2)
        check_in("K-P2: the case and its reason", "TC-3: not checked by hand - no executable obligation", text)
        check_eq("K-P2: the door is the other two, in one lane", door_scope(text), "TC-2,TC-4")
        check_not_in("K-P2: ...and no tail", "more block(s)", text)
        check_eq("K-P2: nothing was dispatched, nothing stamped", (c.state()["revision"], seen["scope"]), (revision, []))
        code, text, seen = start(root, c, "TC-2,TC-3", prepare=lambda case: ([], f"refused {case}", ""))
        check_in("K-P2: every case refused is a named outcome", "no case of this block can be checked by hand", text)
        check_in("K-P2: ...each with its line", "TC-2: not checked by hand - refused TC-2", text)
        check_eq("K-P2: ...and the door is the derived rest, minus the refused (E24 converges)", door_scope(text), "TC-4,TC-5,TC-6")
        check_eq("K-P2: still nothing dispatched", c.state()["revision"], revision)
        # the real function on the fixture writes request.json for every case, and the driver's method is the same function
        import story_run
        for case in ("TC-2", "TC-3"):
            got = manual_evidence.prepare_for_block(root, case)
            twin = story_run.Driver.manual_prepare(types.SimpleNamespace(task_root=root), case)
            check_eq(f"K-P1: {case}: the driver's manual_prepare returns the shared function's tuple", twin, got)
            check_eq(f"K-P1: {case}: request.json is written (a request or a refusal)", manual_evidence.request_path(root, case).is_file(), True)
    finally:
        cleanup(root)


def the_two_halves_are_told_apart_before_the_stamp():
    """K-R8, K-R10. KILLS: R6 removed (M14) or placed after the stamp; the block rule applied to automation (M11)."""
    root = temp_dir("qa-fb9-kind-")
    try:
        c = real_story(root, MIXED_7)
        before, revision = pipeline_bytes(root), c.state()["revision"]
        code, text, seen = start(root, c, None, kind=None)
        check_eq("K-R8: an S6 qa-runner packet with no kind (new mode): exit 2", code, 2)
        check_in("K-R8: it says which half", "an S6 qa-runner packet says which half it runs", text)
        check_in("K-R8: both doors", "door: --execution-kind automation (the automated half), or --execution-kind manual --scope <1..5 ids>", text)
        check_eq("K-R8: pipeline.json and the log untouched", (pipeline_bytes(root), c.state()["revision"]), (before, revision))
        # RH1-10 (DC1-15): the automation half is unbounded in SIZE, but it names automated cases only, so seven AUTOMATE cases
        root_k = temp_dir("qa-fb9-seven-")
        try:
            ck = real_story(root_k, ["automate"] * 7)
            code, text, seen = start(root_k, ck, "TC-1,TC-2,TC-3,TC-4,TC-5,TC-6,TC-7", kind="automation")
            record = ck.state()["dispatches"]["S6-qa-runner-1"]
            check_eq("K-R10: the automation half takes seven cases, unbounded", (code, record.get("execution_kind")), (0, "automation"))
            check_eq("K-R10: ...with no block and no prepare", (record.get("manual_case_ids"), seen["prepared"]), (None, []))
            check_in("K-R10 control: the stamp IS written by a start that goes through (M5's observable)", "run_mode", pipeline_bytes(root_k).decode("utf-8"))
        finally:
            cleanup(root_k)
        # S-1 (F5): `--scope` items are stripped for EVERY start, not only the manual block; the form gets the cleaned join
        root_s = temp_dir("qa-fb9-strip-")
        try:
            cs = real_story(root_s, ["automate"] * 3)
            code, text, seen = start(root_s, cs, " TC-1, TC-2 ,,", kind="automation")
            check_eq("S-1: an automation scope is stripped (record and form)",
                     (code, cs.state()["dispatches"]["S6-qa-runner-1"].get("scope"), seen["scope"]), (0, ["TC-1", "TC-2"], ["TC-1,TC-2"]))
        finally:
            cleanup(root_s)
        # another role is not touched (E18)
        check_eq("E18: a non-runner role meets no block rule",
                 story_step._manual_block_check(args_for("a,a,a,a,a,a,a", role="qa-case-critic", stage="S4"), c, c.state()), (None, [], 0))
    finally:
        cleanup(root)


def the_legacy_mode_records_the_fields_and_keeps_the_bound():
    """K-R9 (E14). KILLS: the `setdefault` of the fields removed (M10); the block rule skipped on a legacy story."""
    applied = []

    class Legacy:
        store = types.SimpleNamespace(root=Path("."))

        def state(self):
            return {"plan_contract_mode": "legacy", "dispatches": {}, "revision": 3}

        def stage_scope(self, *a, **k):
            return {"derived": False, "scope": [], "reason": "legacy"}

        def _half_membership_problems(self, *a, **k):
            raise AssertionError("the membership check is a new-mode check")

        def prepare(self, options):      # a legacy `prepare` copies neither field
            return {"dispatch_request": {"id": options["id"], "stage": "S6", "role": "qa-runner", "scope": options["scope"]}}

        def apply(self, op, request):
            applied.append(request)

    root = temp_dir("qa-fb9-legacy-")
    try:
        (root / "pipeline.json").write_text(json.dumps({"ticket": TASK, "stages": {}}), encoding="utf-8")
        code, text, _ = start(root, Legacy(), "TC-1,TC-2,TC-3,TC-4,TC-5,TC-6")
        check_eq("K-R9: six on a legacy story: the second NEW refusal, with its door", code, 2)
        check_in("K-R9: ...the block rule", "it names 6 cases, at most 5: split the block", text)
        check_eq("K-R9: ...and nothing applied", applied, [])
        code, text, _ = start(root, Legacy(), "TC-1,TC-2")
        check_eq("K-R9: three-or-fewer registers", code, 0)
        check_eq("K-R9: the fields land by setdefault", [(r.get("execution_kind"), r.get("manual_case_ids"), r.get("purpose")) for r in applied],
                 [("manual", ["TC-1", "TC-2"], "manual")])
    finally:
        cleanup(root)


def the_battery():
    """K-B1..K-B3. KILLS: a length limit introduced; an UnicodeEncodeError on a non-ASCII id; the count not named."""
    root = temp_dir("qa-fb9-battery-")
    try:
        c = real_story(root, MIXED_7)
        many = ",".join(f"X{i}" for i in range(1000))
        before, revision = pipeline_bytes(root), c.state()["revision"]
        code, text, seen = start(root, c, many)
        check_eq("K-B1: 1,000 ids none in the plan: exit 2, ONE refusal", (code, text.count("story_step: refused - ")), (2, 1))
        check_in("K-B1: the count of the block", "it names 1000 cases, at most 5: split the block", text)
        check_in("K-B1: the list is cut at 20 and the count is named", "and 980 more", text)
        check_eq("K-B1: the cleaned block is empty: the door is the DERIVED next window", door_scope(text), "TC-2,TC-3,TC-4")
        check_eq("K-B1: nothing written", (pipeline_bytes(root), c.state()["revision"], seen["prepared"]), (before, revision, []))
        code, text, _ = start(root, c, f"TC-{NON_ASCII}")
        check_eq("K-B2: a non-ASCII id is a refusal, not a crash", code, 2)
        check_in("K-B2: ...named as outside the plan", f"not a manual-agent case of the approved plan: TC-{NON_ASCII}", text)
        long_id = "T" * 4096
        code, text, _ = start(root, c, long_id)
        check_eq("K-B3: an id of 4,096 chars is outside the plan, no length limit", code, 2)
        check_in("K-B3: ...named whole", long_id, text)
    finally:
        cleanup(root)


def the_cli_refuses_with_the_same_words():
    """The refusal keys once through the real script (`harness.run_script`). KILLS: an exception read for R6 after the writes;
    a non-ASCII id that crashes the print."""
    root = harness.temp_project("qa-fb9-cli-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        harness.use_project(root)
        task = STEP.open_story(root, env, "QA-C")
        pipeline = task / "pipeline.json"
        before = pipeline.read_bytes()
        done = harness.run_script("story_step.py", "start", "--task", "QA-C", "--stage", "S6", "--role", "qa-runner", cwd=root, env=env)
        check_eq("CLI: an S6 runner with no kind: exit 2", done.returncode, 2)
        check_in("CLI: ...saying which half", "an S6 qa-runner packet says which half it runs", done.stdout)
        check_eq("CLI: ...and pipeline.json is byte-identical", pipeline.read_bytes(), before)
        done = harness.run_script("story_step.py", "start", "--task", "QA-C", "--stage", "S6", "--role", "qa-runner",
                                  "--execution-kind", "manual", "--scope", "TC-1,TC-2,TC-3,TC-4,TC-5,TC-6", cwd=root, env=env)
        check_eq("CLI: six cases: exit 2", done.returncode, 2)
        check_in("CLI: ...the block rule", "unique in-scope cases:", done.stdout)
        check_eq("CLI: ...pipeline.json byte-identical", pipeline.read_bytes(), before)
        done = harness.run_script("story_step.py", "start", "--task", "QA-C", "--stage", "S6", "--role", "qa-runner",
                                  "--execution-kind", "manual", "--scope", f"TC-{NON_ASCII},TC-1,TC-1", cwd=root, env=env)
        check_eq("CLI: a non-ASCII id, a repeat: exit 2 and no traceback", (done.returncode, "Traceback" in done.stderr), (2, False))
        check_in("CLI: ...the repeat is named", "named more than once: TC-1", done.stdout)
    finally:
        cleanup(root)


# --- RH1-10 (DC1-15): the automation half meets the same membership check ---------------------------------
def rh110_the_automation_half_is_checked_before_anything_is_written():
    """B-K12 (written first, it reproduces DC1-15), B-K13, B-K14, B-E2, B-E3, B-E7. KILLS: `_manual_block_check` returning
    `(None, [], 0)` for the automation half (B-K12); the check skipped when `--scope` is absent being turned into a refusal (B-K13);
    the check run for a legacy story (see `the_legacy_mode_records_the_fields_and_keeps_the_bound`)."""
    root = temp_dir("qa-rh110-start-")
    try:
        c = real_story(root, MIXED_7)         # TC-1 automate, TC-2..TC-7 manual-agent
        before, revision = pipeline_bytes(root), c.state()["revision"]
        code, text, seen = start(root, c, "TC-2", kind="automation")
        check_eq("B-K12: an automation start over a manual-agent case: exit 2", code, 2)
        check_in("B-K12: ...cause 1 names the case", "disposed manual-agent in the plan: TC-2", text)
        check_in("B-K12: ...and the real manual command as its door", "--execution-kind manual --scope <1..5 ids>", text)
        check_eq("B-K12: NOTHING written: pipeline.json byte-identical, no event, no form, no case prepared",
                 (pipeline_bytes(root) == before, c.state()["revision"], seen["scope"], seen["prepared"]), (True, revision, [], []))
        check_not_in("B-K12: ...no run_mode stamp", "run_mode", pipeline_bytes(root).decode("utf-8"))
        check_not_in("B-K12: ...no S6 dispatch record", "S6-qa-runner-1", c.state()["dispatches"])
        check_in("B-K12: the refusal ends with a door the refused party can use (the derived automated start)",
                 "start --task QA-9 --stage S6 --role qa-runner --execution-kind automation", text.split("\ndoor:", 1)[1])
        # B-E2: both halves in one scope -> only the manual-agent case is named
        code, text, _ = start(root, c, "TC-1,TC-2", kind="automation")
        check_eq("B-E2: a mixed scope is refused", code, 2)
        check_in("B-E2: ...naming the manual-agent case", "disposed manual-agent in the plan: TC-2", text)
        check_not_in("B-E2: ...and not the automated one", "TC-1", text.split("\ndoor:", 1)[0])
        check_eq("B-E2: ...nothing written", (pipeline_bytes(root) == before, c.state()["revision"]), (True, revision))
        # B-K13: no --scope -> derived by the controller, not checked twice here
        check_eq("B-K13: `_manual_block_check` with no --scope says nothing",
                 story_step._manual_block_check(args_for(None, "automation"), c, c.state()), (None, [], 0))
        code, text, seen = start(root, c, None, kind="automation")
        record = c.state()["dispatches"]["S6-qa-runner-1"]
        check_eq("B-K13: an automation start with no --scope is dispatched on the derived scope",
                 (code, record.get("execution_kind"), record.get("scope")), (0, "automation", ["TC-1"]))
        check_eq("B-K13: ...and the block is not a manual one", (record.get("manual_case_ids"), seen["prepared"]), (None, []))
    finally:
        cleanup(root)
    root = temp_dir("qa-rh110-start-ok-")
    try:
        c = real_story(root, MIXED_7)
        code, text, seen = start(root, c, " TC-1 ,, ", kind="automation")
        record = c.state()["dispatches"]["S6-qa-runner-1"]
        check_eq("B-K14: an automation start over the automate case is dispatched (stripped, B-E7)",
                 (code, record.get("execution_kind"), record.get("scope"), seen["scope"]), (0, "automation", ["TC-1"], ["TC-1"]))
        check_eq("B-K14: ...with no manual block", record.get("manual_case_ids"), None)
    finally:
        cleanup(root)
    # B-E3: a case in neither half is cause 3, with the stage-scope door
    root = temp_dir("qa-rh110-start-neither-")
    try:
        c = real_story(root, ["automate", "manual-human", "manual-agent"])
        revision = c.state()["revision"]
        code, text, seen = start(root, c, "TC-1,TC-2", kind="automation")
        check_eq("B-E3: a manual-human case on the automation half: exit 2", code, 2)
        check_in("B-E3: ...cause 3", "not an automated case of the approved plan: TC-2", text)
        check_in("B-E3: ...with the stage-scope door and the kind", "`controller.py --operation stage-scope` with `execution_kind: automation`", text)
        check_eq("B-E3: ...nothing written", (c.state()["revision"], seen["scope"]), (revision, []))
    finally:
        cleanup(root)
    # B-E7: a malformed scope never raises; duplicates are judged once
    root = temp_dir("qa-rh110-start-malformed-")
    try:
        c = real_story(root, MIXED_7)
        state = c.state()
        check_eq("B-E7: a non-list is not read (the caller's check speaks)",
                 [c._half_membership_problems("S6", state, "TC-2", "automation"), c._half_membership_problems("S6", state, None, "automation")],
                 [[], []])
        got = c._half_membership_problems("S6", state, ["TC-2", "TC-2", 5, "", None, "TC-1"], "automation")
        check_eq("B-E7: non-str and empty members are skipped, a duplicate is judged once: ONE sentence naming TC-2 once",
                 (len(got), got[0].count("TC-2") if got else 0), (1, 1))
        # legacy mode: the automation half meets no membership check (builder-rules 9)
        legacy = dict(state, plan_contract_mode="legacy")
        check_eq("B-E7 control: `_manual_block_check` of a legacy story's automation start reads nothing",
                 story_step._manual_block_check(args_for("TC-2", "automation"), c, legacy), (None, [], 0))
    finally:
        cleanup(root)


# --- the card ---------------------------------------------------------------------------------------------
AUTOMATION_LINE = ('python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" start --task <TICKET> --stage S6 --role qa-runner '
                   '--execution-kind automation')
MANUAL_LINE = ('python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" start --task <TICKET> --stage S6 --role qa-runner '
               '--execution-kind manual --scope <manual-agent case id(s) from the door>')


def card_names_the_rule(text: str) -> bool:
    """The keys code reads (spec K-D1): both `start` lines twice (the card and "Boundary and judge"). The door sentence and the
    not-complete rule are rows of design/role-rules.json."""
    return text.count(AUTOMATION_LINE) == 2 and text.count(MANUAL_LINE) == 2


def the_card_and_the_help_name_the_rule():
    """K-D1. KILLS: the card line removed, the `Scope:` line kept as it was, `--help` without the number."""
    card = (harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s6.md").read_text(encoding="utf-8")
    check_eq("K-D1: the card and the boundary section name both halves", card_names_the_rule(card), True)
    old = ("Scope: from `--operation stage-scope` with the block's `execution_kind` (`manual` or `automation`), never typed.\n"
           "python \"${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py\" start --task <TICKET> --stage S6 --role qa-runner --scope <the block's ids>\n")
    check_eq("K-D1 negative control: today's card line fails the same check", card_names_the_rule(old), False)
    done = harness.run_script("story_step.py", "start", "--help")
    check_in(f"K-D1: `start --help` carries 1..{MANUAL_BLOCK_CASES}", f"1..{MANUAL_BLOCK_CASES}", done.stdout)


def the_driver_reads_the_shared_functions():
    """K-T2. KILLS: an inline slice or a second obligation mapping coming back in the driver (M16)."""
    import inspect
    import story_run
    Driver = story_run.Driver

    def shared(plan_src, gate_src, done_src, prepare_src, whole):
        return ("walk_lanes(" in plan_src and "manual_blocks(" in gate_src and "manual_done_cases(" in done_src
                and "prepare_for_block(" in prepare_src and "i:i + size" not in whole and "_case_obligation_mapping(" not in whole)
    whole = harness.driver_text()
    check_eq("K-T2: the driver calls the shared split, done set and prepare; no inline copy is left",
             shared(inspect.getsource(Driver.manual_plan), inspect.getsource(Driver.stand_login_gate),
                    inspect.getsource(Driver.manual_done), inspect.getsource(Driver.manual_prepare), whole), True)
    old = "plan['blocks'] = [left[i:i + size] for i in range(0, len(left), size)]"
    check_eq("K-T2 negative control: today's inline slice line fails the check",
             shared("walk_lanes(", "manual_blocks(", "manual_done_cases(", "prepare_for_block(", old), False)


def f5_unprepared_case_stays_in_block():
    """F5(c) (t-1936 N5, B-15, the owner's word 05.11: the factory never stands). KILLS: a 2-tuple unpack (`_, why = ...`) in the
    block check; `why` set for a walkable case; the walkable case dropped from the block; a story-owned refusal let through."""
    with temp_dir() as root:
        ctl = real_story(root, MIXED_7)
        scope = "TC-2,TC-3"

        def prepare(case):          # TC-2: the factory failed to prepare it; TC-3 is prepared
            return (["OB-TC-2"], "", "the plan gives TC-2's check an evidence rule that is not one word") if case == "TC-2" \
                else ([f"OB-{case}"], "", "")
        code, text, seen = start(root, ctl, scope, prepare=prepare)
        check_eq("test_unprepared_case_stays_in_block: the start is accepted (exit 0)", code, 0)
        check_eq("test_unprepared_case_stays_in_block: both cases were prepared and the block keeps both", seen["scope"], [scope])
        check_not_in("test_unprepared_case_stays_in_block: nothing is refused", "refused", text)

        def prepare_refused(case):  # TC-3: a refusal the STORY owns (P20, scope, an unpinned case)
            return (["OB-TC-2"], "", "x") if case == "TC-2" else ([], "expectation unconfirmed - Q7", "")
        code, text, seen = start(root, ctl, scope, prepare=prepare_refused)
        check_eq("test_scope_refused_case_still_refused: the start is refused (exit 2)", code, 2)
        check_in("test_scope_refused_case_still_refused: the refused case is named, with the owner's words",
                 "TC-3: not checked by hand - expectation unconfirmed - Q7", text)
        check_not_in("test_scope_refused_case_still_refused: the unprepared case is not among the refused", "TC-2: not checked", text)
        check_eq("test_scope_refused_case_still_refused: nothing was registered", seen["scope"], [])


def f5_arm_b_fixture_end_to_end():
    """F5 DoD: arm B's TS-14/15/16 (a RECORD as `evidence_policy`) passes (a) as refused-by-shape at the S3 exit, and (c) as an
    unprepared walk through the real block check, the real request writer and the real record writer; the one case whose
    expectation nobody confirmed (P20) is still refused beside them."""
    import json as _json
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
    import scaffold as S
    import coverage_contract as CC
    arm_b = _json.loads((Path(__file__).resolve().parent / "fixtures" / "manual-evidence" / "arm-b-dict-policies.json")
                        .read_text(encoding="utf-8"))
    t = S.make_task(manual=("ui", "api", "impl"))
    try:
        for index, row_id in enumerate(("TS-7", "TS-12", "TS-15")):
            policy = arm_b[sorted(arm_b)[index]]
            row = t.row(row_id)
            row["evidence_policy"] = policy
            for ob in row["coverage_obligations"]:
                ob["evidence_policy"] = policy
        # (a) the S3 exit refuses each by shape, naming the obligation and the five words
        errors = CC.validate_obligations(t.plan_rows)
        shape = [e for e in errors if CC.POLICY_SHAPE_ERROR in e]
        check_eq("(a) the plan exit refuses all three dict policies by shape, one error each",
                 sorted(e.split(":")[0] for e in shape), ["OB-12", "OB-15", "OB-7"])
        check_in("(a) ... with the allowed values in the field", "api|cli|no_write|static|ui", shape[0])
        check_in("(a) ... and where the evidence kinds go", "completion_condition", shape[0])
        check_eq("(a) negative control: the same plan with one-word policies has no such error",
                 [e for e in CC.validate_obligations(S.make_task(manual=("ui", "api", "impl")).plan_rows) if CC.POLICY_SHAPE_ERROR in e], [])
        t.write_plan()
        # (c) an old plan reached S6: the block check keeps the walkable cases, refuses the story's own
        ui, api, impl = (S.CASES[k] for k in ("ui", "api", "impl"))
        with t.patched(), mock.patch.object(story_step, "_task_root", lambda task: t.task):
            block, lines, code = story_step._manual_block_check(args_for(f"{ui},{api}"), None, {})
            check_eq("(c) arm B's dict-policy cases TC_007, TC_012 stay in the block (exit 0)", (block, lines, code), ([ui, api], [], 0))
            stub = types.SimpleNamespace(stage_scope=lambda *a, **k: {"derived": False, "reason": "not needed by this test"})
            block, lines, code = story_step._manual_block_check(args_for(f"{ui},{impl}"), stub, {})
            check_eq("(c) the case whose expectation nobody confirmed is still refused (exit 2)", (block, code), (None, 2))
            check_in("(c) ... and named", f"{impl}: not checked by hand - expectation unconfirmed", "\n".join(lines))
            check_not_in("(c) ... while the walkable one is not", f"{ui}: not checked by hand", "\n".join(lines))
            import manual_evidence as ME
            reason = ME.unprepared_request(t.task, ui)["reason"]
            record = {"schema_version": 2, "case": ui, "obligation_ids": ["OB-7"], "unprepared": {"reason": reason},
                      "observations": [], "finding": "work/evidence/manual/x/finding.md", "dispatch_id": "S6-qa-runner-1",
                      "attempt_started_at": "2026-10-01T10:00:00+00:00", "attempt_ended_at": "2026-10-01T10:05:00+00:00",
                      "source_revision": S.SOURCE}
            path = ME.write_block(t.task, [record], declared=True)
            check("(c) the unprepared record is written (no result)", path.is_file() and "result" not in
                  _json.loads(path.read_text(encoding="utf-8"))["manual_checks"][0])
            try:
                ME.write_block(t.task, [dict(record, result="pass")], declared=True)
                check("(c) negative control: the same record with a result is refused", False)
            except ValueError as exc:
                check_in("(c) negative control: the same record with a result is refused", "records no result", str(exc))
    finally:
        S.cleanup(t)


def main():
    f5_unprepared_case_stays_in_block()
    f5_arm_b_fixture_end_to_end()
    the_collector_lists_every_problem()
    the_collector_accepts_exactly_what_today_accepts()
    the_split_and_the_head_number()
    the_done_set_counts_accepted_manual_only()
    a_list_is_named_at_and_beyond_the_shown_limit()
    membership_is_split_by_cause_and_every_road_meets_it()
    five_registers_with_the_drivers_fields()
    six_is_refused_and_nothing_is_written()
    no_scope_prints_the_next_block()
    a_refused_case_leaves_the_block_and_the_door_is_cleaned()
    the_two_halves_are_told_apart_before_the_stamp()
    the_legacy_mode_records_the_fields_and_keeps_the_bound()
    rh110_the_automation_half_is_checked_before_anything_is_written()
    the_battery()
    the_cli_refuses_with_the_same_words()
    the_card_and_the_help_name_the_rule()
    the_driver_reads_the_shared_functions()
    finish("test_story_step_manual_block")


if __name__ == "__main__":
    main()
