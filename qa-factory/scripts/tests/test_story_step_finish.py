#!/usr/bin/env python3
"""story_step.py `finish`: `--unresolved <why> --reason "<words>"` (the pair goes to the controller unchanged), the doors that
refuse it, the derived pair, the committed accept that gets its tail, and the S1 pair of accepted gaps.
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
from story_step_common import (  # noqa: E402
    finish_s4,
    finish_s5,
    manifest_of,
    run_decide,
    s4_story,
    s5_window_story,
    sha256_of,
)


def unresolved_argument_checks(root: Path, env: dict) -> None:
    """Edges vi and ix: the pair goes together and not with --not-complete. Refused BEFORE anything is
    read or recorded (the controller stub below fails the test if it is ever constructed)."""
    import argparse
    import contextlib
    import io

    class Reached(Exception):
        pass

    class Untouchable:
        def __init__(self, *_a, **_kw):
            raise Reached()

    saved = (story_step.Controller, story_step._task_root)
    story_step.Controller, story_step._task_root = Untouchable, lambda _t: root

    def finish_with(**given):
        ns = argparse.Namespace(task="QA-X", dispatch_id="d", digest="d", output=None, not_complete=False,
                                complete=False, ignore_handoff=False, window=None, unresolved=None,
                                reason=None)
        vars(ns).update(given)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                return story_step.finish(ns), out.getvalue()
        except Reached:
            return "reached", out.getvalue()
    try:
        code, out = finish_with(unresolved="could_not_judge")
        check_eq("edge vi: --unresolved without --reason - exit 2", code, 2)
        check_in("edge vi: names what was given and what is missing", "--unresolved without --reason", out)
        check_in("edge vi: and the whole command that satisfies it",
                 '--unresolved <why> --reason "<words>"', out)
        code, out = finish_with(reason="the critic could not judge it")
        check_eq("edge vi: --reason without --unresolved - exit 2", code, 2)
        check_in("edge vi: names what was given and what is missing", "--reason without --unresolved", out)
        for label, pair in (("an empty word", {"unresolved": "", "reason": "r"}),
                            ("a blank reason", {"unresolved": "could_not_judge", "reason": "   "})):
            code, out = finish_with(**pair)
            check_eq(f"edge vi: {label} is no word - exit 2", code, 2)
        # edge ix is narrowed to S5 (t-721 D1): the stage is known only from the dispatch, so the call reaches the
        # controller here; the S5 refusal itself is T6 (s5_window_story, real controller), the other stages T5b.
        check_eq("edge ix (t-721 D1): --unresolved with --not-complete is no longer refused before the dispatch is read",
                 finish_with(unresolved="could_not_judge", reason="r", not_complete=True)[0], "reached")
        # a usable pair, and the old calls, get past the gate to the controller
        check_eq("the pair together reaches the controller", finish_with(unresolved="could_not_judge", reason="r")[0],
                 "reached")
        check_eq("--not-complete alone still reaches it", finish_with(not_complete=True)[0], "reached")
        check_eq("and so does a call with neither", finish_with()[0], "reached")
    finally:
        story_step.Controller, story_step._task_root = saved
    # the same through the real command line: argparse wiring and the exit code
    base = ["finish", "--task", "QA-X", "--dispatch-id", "d", "--digest", "x"]
    (root / "qa-factory" / "artifacts" / "QA-X").mkdir(parents=True, exist_ok=True)   # the story exists (CX1-18)
    lone = harness.run_script("story_step.py", *base, "--unresolved", "could_not_judge", cwd=root, env=env)
    check_eq("cli: --unresolved alone exits 2", lone.returncode, 2)
    check_in("cli: and says why", "--unresolved without --reason", lone.stdout)
    lone = harness.run_script("story_step.py", *base, "--reason", "words", cwd=root, env=env)
    check_eq("cli: --reason alone exits 2", lone.returncode, 2)
    both = harness.run_script("story_step.py", *base, "--unresolved", "x", "--reason", "y", "--not-complete",
                              cwd=root, env=env)
    check_eq("cli: the pair with --not-complete reaches the dispatch lookup (no dispatch QA-X: exit 2, its words)",
             (both.returncode, "no dispatch d in this story" in both.stdout), (2, True))


def unresolved_door_checks(root: Path, env: dict) -> None:
    """The door end to end through a real `Controller`: the exact command, the controller's acceptance,
    the pipeline state after."""
    from controller import Controller
    # A: the window cannot close (TC-2 has no instance): the controller wants `unresolved` + `reason`
    art, window = s5_window_story(root, "QA-U", handed=False)

    def picture():
        state = Controller(art).state()
        return state["revision"], state["dispatches"]["s5-critic"]["status"]
    before = picture()
    nothing = finish_s5(root, env, "QA-U")
    check_eq("edge vii: no window record - the controller's own refusal, exit 2", nothing.returncode, 2)
    check_in("edge vii: printed as it is", "S5 completion needs a window acceptance record", nothing.stdout)
    check_eq("edge vii: nothing was recorded", picture(), before)
    (art / "work/windows").mkdir(parents=True)
    (art / "work/windows/s5-critic.json").write_text(json.dumps(window), encoding="utf-8")
    silent = finish_s5(root, env, "QA-U")
    check_eq("door A: without the pair the controller refuses, exit 2", silent.returncode, 2)
    check_in("door A: in its own words", "names it in `unresolved` with a `reason`", silent.stdout)
    check_eq("door A: and records nothing", picture(), before)
    words = "TC-2 is judged by the person: the critic could not judge it from the code"
    done = finish_s5(root, env, "QA-U", "--unresolved", "could_not_judge", "--reason", words)
    check_eq("door A: --unresolved --reason - the window is accepted, exit 0", done.returncode, 0)
    check_in("door A: said so", "accepted s5-critic", done.stdout)
    record = Controller(art).state()["dispatches"]["s5-critic"]
    check_eq("door A: the dispatch is accepted", record["status"], "accepted")
    check_eq("door A: the word reached the completion unchanged", record.get("unresolved"), "could_not_judge")
    check_eq("door A: and the reason with it", record.get("reason"), words)
    check_eq("door A: the stage is complete in the controller", Controller(art).state()["stages"]["S5"]["status"],
             "completed")
    pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
    check_eq("door A: and done in pipeline.json", pipeline["stages"]["S5"]["status"], "done")
    # B: a window that hands an instance to the person: the controller reads `handed_to_person` BY NAME
    art, window = s5_window_story(root, "QA-H", handed=True)
    (art / "work/windows").mkdir(parents=True)
    (art / "work/windows/s5-critic.json").write_text(json.dumps(window), encoding="utf-8")
    before = (Controller(art).state()["revision"], Controller(art).state()["dispatches"]["s5-critic"]["status"])
    other = finish_s5(root, env, "QA-H", "--unresolved", "could_not_judge", "--reason", "some other word")
    check_eq("edge viii: another word does not say the window is handed - refused, exit 2", other.returncode, 2)
    check_in("edge viii: the controller's own refusal is printed", "this window hands", other.stdout)
    check_eq("edge viii: nothing was recorded", (Controller(art).state()["revision"],
                                                   Controller(art).state()["dispatches"]["s5-critic"]["status"]),
             before)
    handed = finish_s5(root, env, "QA-H", "--unresolved", "handed_to_person", "--reason",
                       "ios profile: the person runs TC-2 on a device")
    check_eq("edge viii: `handed_to_person` passes through unchanged and the handed road closes the window",
             handed.returncode, 0)
    record = Controller(art).state()["dispatches"]["s5-critic"]
    check_eq("edge viii: accepted, with the word the controller reads", (record["status"], record.get("unresolved")),
             ("accepted", "handed_to_person"))


def caller_pair_checks(root: Path, env: dict) -> None:
    """t-721 C2-3: T1d (form 2: the pair of the caller names the instances, `finish` appends the case with none) and T1e
    (the cut of the three parts, N1), through a real controller; the controller's own acceptance is the second witness."""
    import argparse
    import contextlib
    import io
    from controller import Controller
    caller = "handed_to_person; full list: work/windows/s5-critic.json; handed_to_person:i-1"

    def handed_story(ticket):
        art, window = s5_window_story(root, ticket, handed=True)
        (art / "work/windows").mkdir(parents=True)
        (art / "work/windows/s5-critic.json").write_text(json.dumps(window), encoding="utf-8")
        return art

    def blocked_story(ticket):
        """TC-1: its one instance blocked by the stand; TC-2: no instance, handed to the person."""
        art, window = s5_window_story(root, ticket, handed=False)
        fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load", "restart": "re-run"}
        data = manifest_of(art)
        data["unresolved"] = [{"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["i-1"], "remedy": fix,
                               "detail": "the page does not load"},
                              {"case": "TC-2", "reason": "handed_to_person", "detail": "by hand - the steps of TC-2"}]
        (art / "work/automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")
        window["instances"] = [dict(window["instances"][0], outcome="blocked_by_env", execution_fingerprint="",
                                    review={"verdict": "unverified", "input_hash": "s5-h"})]
        (art / "work/windows").mkdir(parents=True)
        (art / "work/windows/s5-critic.json").write_text(json.dumps(window), encoding="utf-8")
        return art

    def record_of(art):
        return Controller(art).state()["dispatches"]["s5-critic"]
    # T1d: the pair of the driver (as `window_gap` writes it) names the instance; the case with none comes LAST
    art = handed_story("QA-D1")
    done = finish_s5(root, env, "QA-D1", "--unresolved", "handed_to_person", "--reason", caller)
    got = record_of(art)
    check_eq("T1d (form 2): the controller accepts the window", (done.returncode, got["status"]), (0, "accepted"))
    check_eq("T1d: `handed_to_person:TC-2` is appended LAST, the caller's reason a byte-for-byte prefix",
             got.get("reason"), caller + "; handed_to_person:TC-2")
    art = handed_story("QA-D2")
    named = caller + "; handed_to_person:TC-2"
    done = finish_s5(root, env, "QA-D2", "--unresolved", "handed_to_person", "--reason", named)
    got = record_of(art)
    check_eq("T1d: TC-2 already named by the caller is not appended twice",
             (done.returncode, got.get("reason"), got["reason"].count("handed_to_person:TC-2")), (0, named, 1))
    # T1d, the second branch (L-7): a pair WITHOUT the word while the window hands INSTANCES gets no append - the
    # controller's `names_handed` refusal stays reachable
    art = handed_story("QA-D3")
    wordless = finish_s5(root, env, "QA-D3", "--unresolved", "could_not_judge", "--reason", "some other word")
    check_eq("T1d (L-7): a pair without the word, instances handed - the controller refuses, nothing recorded",
             (wordless.returncode, "this window hands" in wordless.stdout, record_of(art)["status"]), (2, True, "running"))
    seen, real = [], story_step.Controller

    class Spy(real):
        def prepare(self, options):
            seen.append(dict(options))
            return super().prepare(options)
    story_step.Controller = Spy
    try:
        ns = argparse.Namespace(task="QA-D3", dispatch_id="s5-critic", digest="d", output=["run.txt", "critic-findings.md"],
                                not_complete=False, complete=False, ignore_handoff=True, window=None,
                                unresolved="could_not_judge", reason="some other word")
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                story_step.finish(ns)
            except Exception:       # the controller's refusal is what this branch leaves reachable
                pass
    finally:
        story_step.Controller = real
    check_eq("T1d (L-7): and the reason that reached the controller is the caller's, unchanged",
             [item.get("reason") for item in seen], ["some other word"])
    # T1e: three parts over the limit - the caller's pair whole, the Q8 block before the append, the append cut with `…`
    limit = story_step.WINDOW_REASON_LIMIT
    lead = "the critic could not judge TC-1 from the code: " + "x" * (260 - len("the critic could not judge TC-1 from the code: "))
    art = blocked_story("QA-E1")
    done = finish_s5(root, env, "QA-E1", "--unresolved", "could_not_judge", "--reason", lead)
    got = record_of(art)
    reason = str(got.get("reason"))
    check_eq("T1e: three parts over the limit - the controller accepts", (done.returncode, got["status"]), (0, "accepted"))
    check("T1e: the caller's part is a byte-for-byte prefix, whole", reason.startswith(lead + "; "), reason)
    check("T1e: the Q8 block stands before the append, the append is cut from its tail and ends `…`",
          reason == lead + "; blocked_by_env: i-1; handed_to_person…", reason)
    check_eq("T1e: and the whole is at the limit, not past it", len(reason), limit)
    # T1e, the second case: the caller's reason is itself at the limit - only the uncuttable stays
    art = blocked_story("QA-E2")
    long_lead = "w" * limit
    done = finish_s5(root, env, "QA-E2", "--unresolved", "could_not_judge", "--reason", long_lead)
    got = record_of(art)
    check_eq("T1e: a caller's reason of the limit - the whole is it + `; blocked_by_env…` + `; …`, the word stands, "
             "the controller accepts", (done.returncode, got["status"], got.get("reason")),
             (0, "accepted", long_lead + "; blocked_by_env…; …"))


def open_close_checks(root: Path, env: dict) -> None:
    """t-721 C2-3: T5 (`--open` on S4), T5c (`--close`), T5d (the door touches nothing of the driver and calls nobody)."""
    from controller import Controller

    def decide_s4(ticket, form, text="Keep it open: TC-1 still lacks its negative case."):
        return run_decide(root, env, ticket, form, text=text, dispatch="s4-critic")

    def record_of(art):
        return Controller(art).state()["dispatches"]["s4-critic"]

    def decision_of(art):
        return json.loads((art / "state/decisions/s4-critic.json").read_text(encoding="utf-8"))
    # T5: the closing role finishes as the driver always passes it (complete), the person's `open` keeps S4 open
    art = s4_story(root, "QA-O1")
    done = decide_s4("QA-O1", ["--open", "TC-1"])
    check_eq("T5: decide --open on S4 exits 0", done.returncode, 0)
    fin = finish_s4(root, env, "QA-O1", "--complete")
    got = record_of(art)
    check_eq("T5: finish is accepted and S4 stays open on the named work",
             (fin.returncode, got["status"], got.get("stage_complete"), got.get("unresolved"),
              Controller(art).state()["stages"]["S4"]["status"] != "completed"), (0, "accepted", False, ["TC-1"], True))
    check_in("T5: the recorded decision outranks the driver's --complete, said as a note",
             "note: the person's recorded decision keeps S4 open: TC-1", fin.stdout)
    check_in("T5: the reason is the person's words", "TC-1 still lacks its negative case", str(got.get("reason")))
    # T5d: the door writes its own file and nothing else - no driver-state, no agent, no question to the person
    art = s4_story(root, "QA-O2")
    (art / "state").mkdir(exist_ok=True)
    driver_state = art / "state/driver-state.json"
    driver_state.write_text(json.dumps({"task": "QA-O2", "marks": [1, 2]}), encoding="utf-8")
    before = sha256_of(driver_state)
    ran = root / "claude-ran.log"
    quiet = dict(env, NO_CLAUDE_LOG=str(ran))
    first = run_decide(root, quiet, "QA-O2", ["--open", "TC-1"], text="Open it.", dispatch="s4-critic")
    file = art / "state/decisions/s4-critic.json"
    kept = file.read_bytes()
    entry = decision_of(art)
    check_eq("T5d: decide --open writes state/decisions/<D>.json with `open_work` (unresolved, words_ref), exit 0",
             (first.returncode, entry["open_work"]["unresolved"], entry["open_work"]["words_ref"].startswith("state/words/"),
              "close" in entry), (0, ["TC-1"], True, False))
    check_eq("T5d: state/driver-state.json is untouched (sha256 before = after), it has no `seam_rework`",
             (sha256_of(driver_state) == before, "seam_rework" in driver_state.read_text(encoding="utf-8")), (True, False))
    check("T5d: no agent was called (the claude stub never ran) and no question to the person came",
          not ran.exists() and "Person" not in first.stdout and "?" not in first.stdout, first.stdout)
    again = run_decide(root, quiet, "QA-O2", ["--open", "TC-1"], text="Open it.", dispatch="s4-critic")
    check_eq("T5d: a second call with the same words - the same file, the same `at`, a note",
             (again.returncode, file.read_bytes() == kept, "already recorded" in again.stdout), (0, True, True))
    # T5c: `--close` of the same D before the acceptance replaces `open_work`; `finish` closes with no pair
    closed = decide_s4("QA-O2", ["--close"], text="Close it as it is.")
    entry = decision_of(art)
    check_eq("T5d: --close on the same D before acceptance - no `open_work` in the file, a note says it replaced it",
             (closed.returncode, "open_work" in entry, "replaces the recorded open_work decision" in closed.stdout),
             (0, False, True))
    check_eq("T5c: the `close` record carries `words_ref`, which holds the words",
             (art / entry["close"]["words_ref"]).read_text(encoding="utf-8"), "Close it as it is.")
    fin = finish_s4(root, env, "QA-O2", "--not-complete")
    got = record_of(art)
    check_eq("T5c: finish is accepted with no pair (neither `unresolved` nor `reason`) and S4 completed - the person's "
             "close outranks the driver's --not-complete",
             (got["status"], got.get("stage_complete"), "unresolved" in got, "reason" in got,
              Controller(art).state()["stages"]["S4"]["status"]), ("accepted", True, False, False, "completed"))
    # the exit code is NOT part of this proof: after the controller's acceptance `stage_done.py` runs the S4 exit gate
    # (its gate rehearsal reads the plan and the case files, which this fixture does not carry) - a refusal of THAT
    check("T5c: the only refusal on the road is the exit gate's, after the acceptance (stage_done), never the controller's",
          fin.returncode in (0, 2) and (fin.returncode == 0 or "stage_done refused S4" in fin.stdout), fin.stdout[-300:])
    check_in("T5c: said as a note", "the person's recorded decision closes S4 on this work as it is", fin.stdout)
    # the refusals of the door: not the closing role, an id outside the scope, an accepted dispatch
    outside = decide_s4("QA-O2", ["--open", "TC-9"], text="x")
    check_eq("T5: an accepted dispatch takes no decision - exit 2", (outside.returncode, "is accepted" in outside.stdout),
             (2, True))
    art = s4_story(root, "QA-O3")
    other = decide_s4("QA-O3", ["--open", "TC-9"])
    check_eq("T5: an id outside the scope is refused with the scope listed, nothing recorded",
             (other.returncode, "TC-1" in other.stdout, (art / "state/decisions").exists()), (2, True, False))


def derived_pair_checks(root: Path) -> None:
    """t-219 (B5): `finish` of the S5 critic derives the `unresolved` pair from the window record's OWN gaps when
    EVERY gap is an instance the stand blocked (or the person runs), and from nothing else (t-204 F1). The record is
    read through `acceptance.validate_window` over a real manifest; what the controller would be asked is recorded
    by a stand-in. A caller's pair goes through unchanged, except that the controller needs the WORD."""
    import argparse
    import contextlib
    import io
    import re
    seen: list = []

    class Stop(Exception):
        pass

    class Recorder:
        def __init__(self, _root, wait_seconds=0.0):
            pass

        def state(self):
            return {"dispatches": {"S5-qa-code-critic-9": {"stage": "S5", "role": "qa-code-critic"}}}

        def prepare(self, options):
            seen.append(dict(options))
            raise Stop()
    task = root / "qa-factory/artifacts/QA-D"
    (task / "work/windows").mkdir(parents=True)
    fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load", "restart": "re-run"}
    (task / "work/automation-manifest.json").write_text(json.dumps({
        "tests": [{"instance_id": "test_x", "case": "TC-1", "covers": ["TC-1"]}],
        "unresolved": [{"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_x"], "remedy": fix}]}),
        encoding="utf-8")
    window = {"schema_version": 2, "input_hash": "h", "required_quality_checks": [], "quality_receipts": [],
              "author_dispatch_id": "a", "reviewer_dispatch_id": "S5-qa-code-critic-9",
              "scope_instances": {"TC-1": ["test_x"]},
              "instances": [{"schema_version": 2, "instance_id": "test_x", "input_hash": "h",
                             "outcome": "blocked_by_env", "execution_fingerprint": "",
                             "review": {"verdict": "unverified", "input_hash": "h"}, "obligation_ids": ["O-1"],
                             "obligation_hash": "oh", "assertion_id": "a", "defect_location": "d",
                             "change_disposition": "new_or_changed", "change_basis_ref": "b", "evidence_refs": []}]}
    (task / "work/windows/S5-qa-code-critic-9.json").write_text(json.dumps(window), encoding="utf-8")
    saved = {name: getattr(story_step, name) for name in
             ("Controller", "_task_root", "_stages", "_handoff_check", "_evidence", "_role_receipts", "_window_gaps")}
    story_step.Controller, story_step._task_root = Recorder, lambda _t: task
    story_step._stages = lambda: {"S5": {"roles": ["qa-automator", "qa-code-critic"]}}
    story_step._handoff_check = lambda *_a: ("green", "", "")
    story_step._evidence, story_step._role_receipts = lambda *_a: ["work/x.json"], lambda *_a: []

    def finish_options(complete=True, unresolved=None, reason=None):
        seen.clear()
        ns = argparse.Namespace(task="QA-D", dispatch_id="S5-qa-code-critic-9", digest="d", output=None,
                                not_complete=not complete, complete=complete, ignore_handoff=False, window=None,
                                unresolved=unresolved, reason=reason)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                story_step.finish(ns)
        except Stop:
            pass
        return seen[0] if seen else {}
    try:
        got = finish_options()
        check_eq("t-219 B5: every gap is a blocked instance: `unresolved` is blocked_by_env", got.get("unresolved"),
                 "blocked_by_env")
        check_eq("t-219 B5: the reason names the kind, the record's own path and the gap line",
                 got.get("reason"), "blocked_by_env; full list: work/windows/S5-qa-code-critic-9.json; "
                                    "blocked_by_env:test_x")
        check("t-219 E14: --not-complete derives nothing and passes no window",
              not {"unresolved", "reason", "window"} & set(finish_options(complete=False)))
        keep = finish_options(unresolved="could_not_judge", reason="blocked_by_env: the critic's words")
        check_eq("t-219 Q8: a caller's pair that names the word is passed through unchanged",
                 (keep.get("unresolved"), keep.get("reason")), ("could_not_judge", "blocked_by_env: the critic's words"))
        more = finish_options(unresolved="could_not_judge", reason="the critic's words")
        check_eq("t-219 Q8: one that does not gets `; blocked_by_env: <ids>` appended",
                 more.get("reason"), "the critic's words; blocked_by_env: test_x")
        # any gap of another kind: nothing is derived, whatever else the window holds (t-204 F1)
        for label, gaps in (("a product gap", ["blocked_by_env:a", "product:b"]),
                            ("a review gap", ["blocked_by_env:a", "review:b"]),
                            ("an evidence gap of a handed instance", ["blocked_by_env:a", "evidence:b",
                                                                      "handed_to_person:b"]),
                            ("a window the validation cannot read", None), ("no gap at all", [])):
            story_step._window_gaps = lambda _w, _r, found=gaps: found
            check_eq(f"t-219 E8: {label}: nothing is derived", "unresolved" in finish_options(), False)
        story_step._window_gaps = lambda _w, _r: ["blocked_by_env:a", "handed_to_person:b"]
        got = finish_options()
        check_eq("t-219 E9: blocked and handed: the word is the first kind, and both lead the reason",
                 (got.get("unresolved"), got.get("reason").startswith("blocked_by_env, handed_to_person; full list: ")),
                 ("blocked_by_env", True))
        # O3 (P20, FR-10): a blocked instance that RAN and failed says so in the derived reason, after the head
        story_step._window_gaps = saved["_window_gaps"]
        path = task / "work/windows/S5-qa-code-critic-9.json"
        head_of = "blocked_by_env; full list: work/windows/S5-qa-code-critic-9.json; "

        def with_runs(*entries):
            listed = [{"instance_id": iid, "cases": ["TC-1"], "detail": "d", "remedy": fix, "stand": "localhost",
                       "last_run": last} for iid, last in entries]
            path.write_text(json.dumps(dict(window, blocked_by_env=listed)), encoding="utf-8")
            return finish_options().get("reason")
        red = {"status": "failed", "reason": "AssertionError: boom", "block": "work/run-blocks/b.json"}
        check_eq("t-219 O3: a blocked instance that ran and failed: the `ran red` mark follows the head, the gap line last",
                 with_runs(("test_x", red)), head_of + "ran red: AssertionError: boom; blocked_by_env:test_x")
        check_eq("t-219 O3: one that never ran (last_run null) adds no mark",
                 with_runs(("test_x", None)), head_of + "blocked_by_env:test_x")
        check_eq("t-219 O3: a window with no blocked_by_env[] at all adds none either (an old record)",
                 (path.write_text(json.dumps(window), encoding="utf-8"), finish_options().get("reason"))[1],
                 head_of + "blocked_by_env:test_x")
        check_eq("t-219 O3: a failed run with an empty reason says so",
                 with_runs(("test_x", dict(red, reason=""))), head_of + "ran red: (no reason recorded)"
                 "; blocked_by_env:test_x")
        check_eq("t-219 O3: a reason over 60 characters is cut at 60 with an ellipsis",
                 with_runs(("test_x", dict(red, reason="r" * 70))), head_of + "ran red: " + "r" * 60 + "…"
                 "; blocked_by_env:test_x")
        check_eq("t-219 O3: an entry for an instance no gap names as blocked adds no mark",
                 with_runs(("test_x", None), ("test_other", red)), head_of + "blocked_by_env:test_x")

        # F2 (critic t-243): the CALLER's pair gets the same `ran red` marks, by the same helper and the same limit
        def callers(last, reason="the critic's words"):
            listed = [{"instance_id": "test_x", "cases": ["TC-1"], "detail": "d", "remedy": fix, "stand": "localhost",
                       "last_run": last}]
            path.write_text(json.dumps(dict(window, blocked_by_env=listed)), encoding="utf-8")
            return finish_options(unresolved="could_not_judge", reason=reason)
        got = callers(red)
        check_eq("t-219 F2: a caller's pair, blocked instance that ran red: the word is appended, then the mark",
                 (got.get("unresolved"), got.get("reason")),
                 ("could_not_judge", "the critic's words; blocked_by_env: test_x; ran red: AssertionError: boom"))
        check_eq("t-219 F2: a reason that names the word already still gains the mark",
                 callers(red, "blocked_by_env: the critic's words").get("reason"),
                 "blocked_by_env: the critic's words; ran red: AssertionError: boom")
        check_eq("t-219 F2: an instance that never ran adds no mark (the Q8 line alone)",
                 callers(None).get("reason"), "the critic's words; blocked_by_env: test_x")
        check_eq("t-219 F2: a failed run with an empty reason says so, like the derived road",
                 callers(dict(red, reason="")).get("reason"),
                 "the critic's words; blocked_by_env: test_x; ran red: (no reason recorded)")
        check_eq("t-219 F2: a mark the caller already quoted is not repeated",
                 callers(red, "blocked_by_env: ran red: AssertionError: boom").get("reason"),
                 "blocked_by_env: ran red: AssertionError: boom")
        check_eq("t-219 F2: a window with no blocked_by_env[] (an old record) adds none",
                 (path.write_text(json.dumps(window), encoding="utf-8"),
                  finish_options(unresolved="could_not_judge", reason="blocked_by_env: x").get("reason"))[1],
                 "blocked_by_env: x")
        # F2 + E10: the limit AT and BEYOND; the caller's words and the word are never cut, the marks are what goes
        mark_cost = len("; ran red: AssertionError: boom")
        at_limit = "blocked_by_env " + "w" * (story_step.WINDOW_REASON_LIMIT - mark_cost - len("blocked_by_env "))
        kept = callers(red, at_limit).get("reason")
        check_eq("t-219 F2/E10: base + mark of exactly 300 characters is kept whole",
                 (len(kept), kept == at_limit + "; ran red: AssertionError: boom"), (300, True))
        past = callers(red, at_limit + "w").get("reason")
        check_eq("t-219 F2/E10: 301 are cut to 300; the caller's words stand whole, the mark is what is cut",
                 (len(past), past.startswith(at_limit + "w; ran red: ")), (300, True))
        long_base = "blocked_by_env " + "w" * story_step.WINDOW_REASON_LIMIT
        check_eq("t-219 F2/E10: a caller's reason already past the limit is never cut and gains no mark - the dropped "
                 "mark is shown as the cut `…` (t-721 N1: every cut is marked)",
                 callers(red, long_base).get("reason"), long_base + "; …")
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)
    # E10: the limit AT and BEYOND; the kinds and the path survive the cut; it is story_run's own number
    shown = "work/windows/w.json"
    head = "blocked_by_env; full list: " + shown
    fixed = len(head) + len("; blocked_by_env:")
    exact = "i" * (story_step.WINDOW_REASON_LIMIT - fixed)
    _word, reason = story_step._derived_pair(["blocked_by_env:" + exact], shown)
    check_eq("t-219 E10: a reason of exactly 300 characters is kept whole", (len(reason), reason.endswith(exact)),
             (300, True))
    _word, reason = story_step._derived_pair(["blocked_by_env:" + exact + "x"], shown)
    check_eq("t-219 E10: 301 characters are cut to 300, the kinds and the path first", (len(reason), reason.startswith(head)),
             (300, True))
    # O3 + E10: the mark counts toward the 300 characters, the kinds and the path still stand first
    mark = "ran red: boom"
    fixed = len(head) + len("; ") + len(mark) + len("; blocked_by_env:")
    exact = "i" * (story_step.WINDOW_REASON_LIMIT - fixed)
    _word, reason = story_step._derived_pair(["blocked_by_env:" + exact], shown, [mark])
    check_eq("t-219 O3/E10: head + mark + gap of exactly 300 characters is kept whole",
             (len(reason), reason.endswith(exact), (head + "; " + mark + "; ") in reason), (300, True, True))
    _word, reason = story_step._derived_pair(["blocked_by_env:" + exact + "x"], shown, [mark])
    check_eq("t-219 O3/E10: 301 are cut to 300; the head and the mark stand first",
             (len(reason), reason.startswith(head + "; " + mark + "; ")), (300, True))
    _word, reason = story_step._derived_pair(["blocked_by_env:a"], "w/" + "d/" * 200 + "w.json", [mark])
    check("t-219 O3/E10: a head longer than the limit is kept whole and the mark is what goes",
          reason == "blocked_by_env; full list: w/" + "d/" * 200 + "w.json", reason[:60])
    check_eq("t-219 E10: the limit is story_run's WINDOW_REASON_LIMIT",
             int(re.search(r"WINDOW_REASON_LIMIT\s*=\s*(\d+)",
                           (harness.SCRIPTS / "story_run.py").read_text(encoding="utf-8")).group(1)),
             story_step.WINDOW_REASON_LIMIT)


def a_committed_accept_gets_its_tail_when_the_view_is_stale() -> None:
    """`finish` accepts through `controller.apply`; the event commits, THEN the derived view may fail to
    refresh and `DerivedViewStale` is raised ("event committed; derived view not refreshed ... do not
    repeat the action"). The accept is durable, so the tail is owed all the same: the receipt of the
    host is released and `stage_done --status done` runs, or the stage stays `running` and the
    binding non-terminal behind a refusal that says nothing was lost. Any OTHER exception from the
    accept means nothing committed, and the tail does not run."""
    import argparse
    import contextlib
    import io
    from event_store import DerivedViewStale

    door = "`controller.py --task-root T --operation recover` refreshes it"
    stale = DerivedViewStale("event committed; derived view not refreshed (RuntimeError: render); "
                             "do not repeat the action; " + door)
    log: list = []
    task = Path("fake-task-root")

    class AcceptingController:
        failure = None

        def __init__(self, _root, wait_seconds=0.0):
            pass

        def state(self):
            return {"dispatches": {"S7-qa-failure-analyst-1": {"stage": "S7", "role": "qa-failure-analyst"}}}

        def prepare(self, options):
            return {"accept_request": dict(options)}

        def apply(self, operation, request):
            log.append(("apply", operation))
            if AcceptingController.failure is not None:
                raise AcceptingController.failure

        def next_action(self):
            return {"action": "prepare_stage", "stage": "S8"}

        def _next_action_for_state(self, _state):
            return self.next_action()

    names = ("Controller", "_task_root", "_stages", "_run", "_post_work", "_judge_line", "config_finding",
             "_config", "_handoff_check", "_evidence", "_role_receipts", "_release_binding")
    saved = {name: getattr(story_step, name) for name in names}
    stage_done_exit = [0]
    stage_done_text = ["stage_done: refused"]

    def fake_run(script, *args):
        log.append(("run", script, args[args.index("--status") + 1] if "--status" in args else ""))
        return stage_done_exit[0], ("stage_done: S7 done" if not stage_done_exit[0]
                                    else stage_done_text[0])
    story_step.Controller = AcceptingController
    story_step._task_root = lambda _task: task
    story_step._stages = lambda: {"S7": {"roles": ["qa-failure-analyst"]}}
    story_step._run = fake_run
    story_step._post_work = lambda *_a: []
    story_step._judge_line = lambda _task: "judge: off"
    story_step.config_finding = lambda *_a: []
    story_step._config = lambda: {}
    story_step._handoff_check = lambda *_a: ("green", "", "")
    story_step._evidence = lambda *_a: ["work/x.json"]
    story_step._role_receipts = lambda *_a: []
    story_step._release_binding = lambda root, dispatch_id, task_name="": log.append(
        ("release", str(root), dispatch_id, task_name))

    def finish_with(failure, exit_code=0):
        log.clear()
        AcceptingController.failure, stage_done_exit[0] = failure, exit_code
        ns = argparse.Namespace(task="QA-S", dispatch_id="S7-qa-failure-analyst-1", digest="d", output=None,
                                not_complete=False, complete=False, ignore_handoff=False, window=None,
                                unresolved=None, reason=None)
        out, raised = io.StringIO(), None
        try:
            with contextlib.redirect_stdout(out):
                code = story_step.finish(ns)
        except Exception as exc:  # the case under test is what finish lets through
            code, raised = None, exc
        return code, out.getvalue(), raised
    try:
        code, out, raised = finish_with(None)
        check_eq("a healthy refresh: finish ends 0 with no exception", (code, raised), (0, None))
        check_eq("a healthy refresh: accept, release, stage_done, in that order",
                 [entry[0] if entry[0] != "run" else entry[:3] for entry in log],
                 ["apply", "release", ("run", "stage_done.py", "done")])
        check_not_in("a healthy refresh: no word about a stale view", "derived view", out)

        report_refusal = "report check: the report is not built"
        stage_done_text[0] = report_refusal
        code, fresh_refused, raised = finish_with(None, exit_code=4)
        check_eq("a healthy refresh and a stage_done that refuses: its exit stands", code, 4)

        # t-434 E2: EVERY member of the committed family gets the tail, each one exactly as the real store
        # raises it (the two "projection stale" texts and the generic after-commit wrapper), plus the
        # dashboard refusal of `refresh_derived` (`stale`, its text as the controller words it).
        import story_run
        phrases = ("event committed;", "event already committed;")
        members = _committed_raises_of_the_store() + [("the dashboard refusal of refresh_derived", stale)]
        check_eq("t-434: the store raised every member it is asked for", [m[1] is not None for m in members],
                 [True] * len(members))
        for label, member in members:
            check_in(f"{label}: (the member says the event is committed, as the store words it)",
                     "committed;", str(member))
            code, out, raised = finish_with(member)
            check_eq(f"{label}: finish does not raise", raised, None)
            check_eq(f"{label}: its tail ran: release, then stage_done, in that order",
                     [entry[0] if entry[0] != "run" else entry[:3] for entry in log],
                     ["apply", "release", ("run", "stage_done.py", "done")])
            check_eq(f"{label}: the release names the task, the dispatch and the folder",
                     [entry for entry in log if entry[0] == "release"],
                     [("release", str(task), "S7-qa-failure-analyst-1", "QA-S")])
            check_eq(f"{label}: it ends as a done (exit 0): the stage is closed", code, 0)
            check_in(f"{label}: and says the accept is in", "accepted S7-qa-failure-analyst-1", out)
            notes = [line for line in out.splitlines() if line.startswith("note: ") and "dashboard" in line]
            check_eq(f"{label}: ONE note says the stale view", len(notes), 1)
            note = notes[0] if notes else ""
            check_in(f"{label}: the note says the stage is recorded and closed", "S7 is recorded and closed", note)
            check_in(f"{label}: that the dashboard was not refreshed", "dashboard", note)
            check_in(f"{label}: and that recover refreshes it", "--operation recover` refreshes it", note)
            for phrase in phrases:
                check_not_in(f"{label}: no literal {phrase!r} anywhere in finish's output", phrase, out)
            check(f"{label}: the driver's committed_event row does not read the output (case a)",
                  (story_run.match_known(out) or ("",))[0] != "committed_event", story_run.match_known(out))

            code, out, raised = finish_with(member, exit_code=4)
            check_eq(f"{label} + a refusing stage_done: the refusal's exit stands", (code, raised), (4, None))
            check_in(f"{label} + a refusing stage_done: its refusal is in the output", report_refusal, out)
            check_eq(f"{label} + a refusing stage_done: the binding was released all the same",
                     [entry[0] for entry in log if entry[0] == "release"], ["release"])
            stale_notes = [line for line in out.splitlines()
                           if line.startswith("note: ") and "dashboard" in line and "--operation recover" in line]
            check_eq(f"{label} + a refusing stage_done: the stale view is still said, as ONE note with the door",
                     len(stale_notes), 1)
            check_not_in(f"{label} + a refusing stage_done: and it does not claim the stage is closed",
                         "recorded and closed", out)
            for phrase in phrases:
                check_not_in(f"{label} + a refusing stage_done: no literal {phrase!r}", phrase, out)
            # The ROUTING control (case b): the driver reads `story_step finish <id> (exit N):\n<stdout>`
            # (story_run.finish) and matches the whole text; it must route as the bare refusal does, and as
            # the same refusal does after a healthy refresh.
            driver_text = f"story_step finish S7-qa-failure-analyst-1 (exit {code}):\n{out}"
            fresh_text = f"story_step finish S7-qa-failure-analyst-1 (exit 4):\n{fresh_refused}"
            check_eq(f"{label} + a refusing stage_done: the driver routes it as the bare refusal",
                     story_run.match_known(driver_text), story_run.match_known(report_refusal))
            check_eq(f"{label} + a refusing stage_done: and as the same refusal after a fresh view",
                     story_run.match_known(driver_text), story_run.match_known(fresh_text))
        check_eq("the bare report-check refusal is the report_check row (the control's own control)",
                 story_run.match_known(report_refusal), ("report_check", "rebuild_report"))
        check_eq("and the old note's literal phrase WOULD be read as committed_event (the negative control)",
                 story_run.match_known("note: " + str(stale) + "\n" + report_refusal)[0], "committed_event")

        # Not of the family: nothing committed, and no tail runs.
        from event_store import StateConflict
        for label, failure in (("RuntimeError", RuntimeError("the accept itself failed")),
                               ("a stale expected revision", _stale_revision_conflict()),
                               ("a lock held by another writer", StateConflict("task has an active state writer"))):
            code, out, raised = finish_with(failure)
            check_eq(f"{label}: goes through unchanged", (type(raised), str(raised)),
                     (type(failure), str(failure)))
            check_eq(f"{label}: and nothing of the tail ran: no release, no stage_done",
                     [entry[0] for entry in log], ["apply"])
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)


def _committed_raises_of_the_store() -> list:
    """(label, exception) for every raise of the REAL event store that says the event is committed: a
    projection that fails on a new event, the same on a replay, an after-commit step that fails. Taken
    from the store rather than built by hand, so a member the store raises cannot be left out by a test
    that only knew the class names."""
    from event_store import EventStore

    def crash(events):
        raise OSError("projection disk failure")

    def broken():
        raise RuntimeError("render")
    root = harness.temp_dir("qa-story-step-committed-")
    found = []
    try:
        for name in ("QA-C", "QA-D"):
            (root / name).mkdir()                    # the stories exist: S0 makes a story folder, a commit never does (CX1-18)
        store = EventStore(root / "QA-C")
        for label, run in (("projection stale on a new event", lambda: store.commit("a", {}, "k1", project=crash)),
                           ("projection stale on a replay", lambda: store.commit("a", {}, "k1", project=crash)),
                           ("the after-commit step did not finish",
                            lambda: EventStore(root / "QA-D", after_commit=broken).commit("a", {}, "k2"))):
            try:
                run()
                found.append((label, None))
            except Exception as exc:  # what the store raised is the member under test
                found.append((label, exc))
    finally:
        harness.cleanup(root)
    return found


def _stale_revision_conflict():
    """The store's own refusal of a stale expected revision: a StateConflict where nothing committed."""
    from event_store import EventStore, StateConflict
    root = harness.temp_dir("qa-story-step-revision-")
    try:
        (root / "QA-R").mkdir()                      # the story exists (CX1-18)
        store = EventStore(root / "QA-R")
        store.commit("a", {}, "k1")
        try:
            store.commit("a", {}, "k2", 0)
        except StateConflict as exc:
            return exc
        return StateConflict("the store accepted a stale expected revision")
    finally:
        harness.cleanup(root)


def c29_the_s1_pair_names_what_a_kind_and_the_factory_closed() -> None:
    """T11 (C2-9, N4): the S1 pair (`unresolved` + `reason`) carries the words of a recorded KIND of gap for the source it closed, and an
    `unreachable by the factory` entry for every gap the factory's own verdict closed; a complete inventory with neither gives `{}`."""
    import json
    import shutil
    import tempfile
    task_root = Path(tempfile.mkdtemp(prefix="qa-step-c29-"))
    try:
        def source(sid, items):
            return {"source_id": sid, "canonical_ref": f"https://jira.example.invalid/browse/APP-{sid[-1]}", "relation": "referenced",
                    "relevance": "relevant", "required": True, "status": "read", "inspection_status": "read",
                    "human_review": {"words": "ok", "shown": {"relevance": "relevant"}},
                    "materials": {"comments": {"status": "read"}, "attachments": {"status": "read", "items": []},
                                  "external_media": {"status": "unavailable" if items else "read", "items": items}}}

        def write(*sources):
            (task_root / "work").mkdir(exist_ok=True)
            (task_root / "work" / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": list(sources)}),
                                                                      encoding="utf-8")
        probe = {"url": "https://git.example.com/team/sdk/-/merge_requests/510", "status": "unavailable", "cause": "host_unreachable",
                 "probe_ref": "sources/SRC-2/mr-510.json", "probe_code": "host_unreachable"}
        login = {"url": "https://share.example.com/x/doc", "status": "unavailable", "cause": "auth_required"}
        write(source("SRC-1", []))
        check_eq("T11 nothing accepted, nothing by default: no pair", story_step._s1_accepted_gaps(task_root), {})
        write(source("SRC-1", [login]), source("SRC-2", [probe]))
        (task_root / "work" / "gap-classes.json").write_text(json.dumps({"schema_version": 1, "classes": [
            {"id": "GC-1", "cause": "auth_required", "words": "skip every login wall", "at": "2026-10-16T09:00:00+00:00"}]}), encoding="utf-8")
        pair = story_step._s1_accepted_gaps(task_root)
        check_eq("T11 both sources are named", pair.get("unresolved"), ["SRC-1", "SRC-2"])
        check_in("T11 the kind's words ride in the reason, with whose answer", "SRC-1: skip every login wall (on the basis of your answer GC-1 of 2026-10-16",
                 pair.get("reason", ""))
        check_in("T11 the factory's own verdict is named as such, with its cause", "unreachable by the factory: SRC-2 - ", pair.get("reason", ""))
        check_in("T11 and the cause", "host_unreachable", pair.get("reason", ""))
        write(source("SRC-2", [probe]))
        (task_root / "work" / "gap-classes.json").unlink()
        pair = story_step._s1_accepted_gaps(task_root)
        check_eq("T11 only a gap by default: the pair is still built (for the report), without a person's words",
                 (pair.get("unresolved"), "accepted by the person" in pair.get("reason", "")), (["SRC-2"], False))
    finally:
        shutil.rmtree(task_root, ignore_errors=True)


def first_look_dispatch_never_closes_the_stage(root, env) -> None:
    """t-2277 FL-5 (B2 reader: the form/evidence/exit gate at `finish`; decision 3): the optional first-look runner dispatch is accepted by its
    own output, with `--complete` given S3 stays open (the strategist's windows and the critic close it), and S3's `roles` are unchanged."""
    import test_controller_state as BASE
    from controller import Controller
    from story_step_common import finish_here, open_story
    task = open_story(root, env, "QA-FL")
    c = Controller(task)
    for stage in ("S1", "S2"):
        BASE.accept_stage(c, task, stage)
    packet = c.prepare({"stage": "S3", "role": "qa-runner", "id": "S3-qa-runner-1", "purpose": "first_look"})
    c.apply("dispatch", packet["dispatch_request"])
    code, said = finish_here("QA-FL", dispatch="S3-qa-runner-1", output=[], complete=True)
    check("first_look_dispatch_never_closes_the_stage: with no record the finish is refused (the runner owes its own output)",
          code == 3 and "left none of the outputs" in said and "run-report" not in said, said[-300:])
    (task / "work" / "first-look.yaml").write_text("rows:\n", encoding="utf-8")
    code, said = finish_here("QA-FL", dispatch="S3-qa-runner-1", output=[], complete=True)
    state = Controller(task).state()
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8-sig"))
    check_eq("first_look_dispatch_never_closes_the_stage: with its record the dispatch is accepted", (code, state["dispatches"]["S3-qa-runner-1"]["status"]),
             (0, "accepted"))
    check("first_look_dispatch_never_closes_the_stage: and `--complete` did not complete S3",
          (pipeline.get("stages") or {}).get("S3", {}).get("status") != "done", pipeline.get("stages"))
    s3 = {s["id"]: s for s in json.loads((harness.PLUGIN_ROOT / "references" / "stages.json").read_text(encoding="utf-8"))["stages"]}["S3"]
    check_eq("first_look_dispatch_never_closes_the_stage: S3 roles are unchanged - the runner is no role of the stage",
             s3["roles"], ["qa-test-strategist", "qa-case-critic"])


def main() -> None:
    root = harness.temp_project("qa-story-step-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    try:
        harness.use_project(root)
        first_look_dispatch_never_closes_the_stage(root, env)
        unresolved_argument_checks(root, env)
        unresolved_door_checks(root, env)
        caller_pair_checks(root, env)
        open_close_checks(root, env)
        derived_pair_checks(root)
    finally:
        harness.cleanup(root)
    a_committed_accept_gets_its_tail_when_the_view_is_stale()
    c29_the_s1_pair_names_what_a_kind_and_the_factory_closed()
    harness.finish("test_story_step_finish")


if __name__ == "__main__":
    main()
