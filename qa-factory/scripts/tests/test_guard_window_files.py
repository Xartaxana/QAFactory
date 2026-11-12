#!/usr/bin/env python3
"""TR3-16 (spec t-1937 F3 b, B2; AR-9, AR-10, AR-14, AR-25): first-write ownership of a test file by an S5 window.

`window_files` is the one writer of `state/window-files/`; `guard_pre_tool.window_file_check` reads it on every Write, Edit
and NotebookEdit of a session that carries a dispatch name. ERROR DIRECTION under test: the guard may refuse needlessly (a new
file is always possible), it never lets two LIVE windows write one test file.

Keys (the spec's twelve): write_to_other_running_window_file_refused_with_door, own_file_allowed, rework_of_same_window_allowed,
new_file_in_same_directory_allowed, no_name_no_check, critic_role_no_claim, support_file_not_claimed, race_one_wins,
released_claim_free, empty_claim_refused_with_door, path_spellings_same_claim, arm_b_overlap_shape_second_goes_to_new_file;
plus the edges: a path outside the project, a plan dispatch, NotebookEdit, an unknown name; and the t-2084 round (F1, F2, F8):
open_window_claim_holds, grown_round_keeps_its_file, release_frees_older_id, n1_claims_nothing, fuse_names_state_not_guard,
unreadable_controller_is_said (a claim holds until release: no takeover, own by case intersection).
"""
import contextlib
import io
import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import dispatch_identity as DI  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
import window_files as WF  # noqa: E402

TICKET = "QA-WF1"
A1, A2, A3, C1 = "S5-qa-automator-1", "S5-qa-automator-2", "S5-qa-automator-3", "S5-qa-code-critic-1"
W1, W2 = "S5|TC-1", "S5|TC-2"
ENVS = (PC.DETECTOR_DISPATCH_ENV, DI.DRIVER_RUN_ENV)


def rec(ident, scope, status="running", role="qa-automator", stage="S5", **extra):
    return {"id": ident, "stage": stage, "role": role, "status": status, "scope": scope, **extra}


class Story:
    """A throwaway project with one story whose controller holds `dispatches`."""

    def __init__(self, dispatches):
        self.root = temp_project("qa-window-files-")
        use_project(self.root)
        self.task = self.root / "qa-factory" / "artifacts" / TICKET
        (self.task / "state").mkdir(parents=True)
        self.set(dispatches)
        (self.root / "tests" / "api").mkdir(parents=True, exist_ok=True)
        self.cfg = json.loads((self.root / "qa-factory" / "config.json").read_text(encoding="utf-8"))

    def set(self, dispatches):
        (self.task / "state" / "controller.json").write_text(
            json.dumps({"dispatches": {d["id"]: d for d in dispatches}, "stages": {}}), encoding="utf-8")

    def event(self, rel, tool="Write", absolute=True):
        path = str(self.root / rel) if absolute else rel
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        return {"tool_name": tool, "tool_input": {key: path, "content": "x"}, "cwd": str(self.root)}

    def verdict(self, name, rel, tool="Write", absolute=True):
        """The guard's refusal text for a session named `name` writing `rel`, or None."""
        saved = {k: os.environ.get(k) for k in ENVS}
        os.environ.pop(PC.DETECTOR_DISPATCH_ENV, None)
        if name:
            os.environ[DI.DRIVER_RUN_ENV] = name
        else:
            os.environ.pop(DI.DRIVER_RUN_ENV, None)
        try:
            return G._blocked(G.window_file_check, self.event(rel, tool, absolute), self.cfg)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def claimed(self, rel):
        return WF.owner(self.task, rel)


TEST_FILE = "tests/api/test_orders.py"


def two_windows():
    return Story([rec(A1, ["TC-1"]), rec(A2, ["TC-2"])])


def main():
    # 1 + 2: the first window claims and passes (own file), the second is refused with the door
    s = two_windows()
    try:
        check_eq("own_file_allowed: the first writer of a new test file claims it and passes", s.verdict(A1, TEST_FILE), None)
        check_eq("and the claim is its window's", s.claimed(TEST_FILE), W1)
        check_eq("own_file_allowed: its second write passes", s.verdict(A1, TEST_FILE, tool="Edit"), None)
        text = s.verdict(A2, TEST_FILE)
        check("write_to_other_running_window_file_refused_with_door: refused", bool(text), str(text))
        check_in("the refusal names the owner's cases", "belongs to window TC-1 until that window closes", text or "")
        check_in("and the door: a new file in the same directory", "Put your test in a new file in the same directory: tests/api.", text or "")
        check_in("and P17 stays the role's", "Where a test lives stays your choice (P17); a test in a new file is judged the same.", text or "")
        check_eq("the refusal did not move the claim", s.claimed(TEST_FILE), W1)
        # 4: the door opens
        check_eq("new_file_in_same_directory_allowed: the second window writes a new file there", s.verdict(A2, "tests/api/test_orders_edge.py"), None)
        check_eq("and claims it", s.claimed("tests/api/test_orders_edge.py"), W2)
        check_eq("NotebookEdit is the same branch (refused)", bool(s.verdict(A2, TEST_FILE, tool="NotebookEdit")), True)
        check_eq("an Edit is the same branch (refused)", bool(s.verdict(A2, TEST_FILE, tool="Edit")), True)
        # 12: the arm B shape: both windows meet on one existing file, the second goes to a new one
        check_eq("arm_b_overlap_shape_second_goes_to_new_file: the first window's file stays its own", s.verdict(A1, TEST_FILE), None)
        refused = s.verdict(A2, "tests/api/test_orders.py")
        check("arm_b_overlap_shape: the second window is turned back", bool(refused))
        check_eq("arm_b_overlap_shape: and its new file passes", s.verdict(A2, "tests/api/test_orders_w2.py"), None)
        check_eq("arm_b_overlap_shape: the files of window 2 are exactly its own", WF.files_of(s.task, W2),
                 ["tests/api/test_orders_edge.py", "tests/api/test_orders_w2.py"])
        # 5: no name
        check_eq("no_name_no_check: a session with no dispatch name writes the claimed file", s.verdict("", TEST_FILE), None)
        check_eq("an unknown name (no story holds it) writes", s.verdict("S5-qa-automator-9", TEST_FILE), None)
        # 6: the critic
        s.set([rec(A1, ["TC-1"]), rec(A2, ["TC-2"]), rec(C1, ["TC-2"], role="qa-code-critic")])
        before = sorted(p.name for p in (s.task / "state" / "window-files").glob("*.json"))
        check_eq("critic_role_no_claim: a code critic is not refused", s.verdict(C1, TEST_FILE), None)
        check_eq("and claims nothing", sorted(p.name for p in (s.task / "state" / "window-files").glob("*.json")), before)
        # 7: support files
        check_eq("support_file_not_claimed: a page object passes", s.verdict(A2, "tests/api/helpers/page.py"), None)
        check_eq("and a fixture/config passes", s.verdict(A2, "tests/api/conftest_data.json"), None)
        check_eq("and nothing of them is claimed", [f for f in WF.files_of(s.task, W2) if "helpers" in f or "conftest" in f], [])
        # outside the project
        outside = Path(s.root).parent / "elsewhere" / "test_x.py"
        saved = os.environ.get(DI.DRIVER_RUN_ENV)
        os.environ[DI.DRIVER_RUN_ENV] = A2
        try:
            ev = {"tool_name": "Write", "tool_input": {"file_path": str(outside)}, "cwd": str(s.root)}
            check_eq("a path outside the project returns", G._blocked(G.window_file_check, ev, s.cfg), None)
        finally:
            if saved is None:
                os.environ.pop(DI.DRIVER_RUN_ENV, None)
            else:
                os.environ[DI.DRIVER_RUN_ENV] = saved
    finally:
        cleanup(s.root)

    # 3: rework of the same window, and a closed window's claim
    s = Story([rec(A1, ["TC-1"], status="accepted"), rec(A3, ["TC-1"])])
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        check_eq("rework_of_same_window_allowed: a new dispatch of the same window writes the file its first dispatch claimed",
                 s.verdict(A3, TEST_FILE), None)
    finally:
        cleanup(s.root)
    # F1: a claim holds until release, whatever the owner's dispatches say (the critic accepted, the repair round waits)
    s = Story([rec(A1, ["TC-1"], status="accepted"), rec(A2, ["TC-2"])])
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        text = s.verdict(A2, TEST_FILE)
        check("open_window_claim_holds: window 1 has no running dispatch, window 2 is still refused", bool(text), str(text))
        check_eq("open_window_claim_holds: and the claim stays window 1's", s.claimed(TEST_FILE), W1)
        s.set([rec(A1, ["TC-1"], status="accepted"), rec(A3, ["TC-1"]), rec(A2, ["TC-2"])])
        check_eq("open_window_claim_holds: window 1's repair round (a new dispatch) writes its own file", s.verdict(A3, TEST_FILE), None)
        check_eq("open_window_claim_holds: window 2 is refused all the same", bool(s.verdict(A2, TEST_FILE)), True)
    finally:
        cleanup(s.root)
    s = Story([rec(A1, ["TC-1"], status="accepted"), rec(A3, ["TC-1", "TC-3"]), rec(A2, ["TC-2"])])
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        check_eq("grown_round_keeps_its_file: the grown round (TC-1,TC-3) writes the file window TC-1 claimed", s.verdict(A3, TEST_FILE), None)
        check_eq("grown_round_keeps_its_file: the claim is not moved", s.claimed(TEST_FILE), W1)
        check_eq("grown_round_keeps_its_file: another window is still refused", bool(s.verdict(A2, TEST_FILE)), True)
        check_eq("WF.same_window: a shared case is the same window, disjoint cases are not",
                 [WF.same_window("S5|TC-1", "S5|TC-1,TC-3"), WF.same_window("S5|TC-1", "S5|TC-2"), WF.same_window("S5|", "S5|TC-1")],
                 [True, False, False])
        check_eq("N4: files_of owns by shared case like claim and release (the grown id lists the first id's claim)",
                 WF.files_of(s.task, "S5|TC-1,TC-3"), [TEST_FILE])
        check_eq("N4: a disjoint window lists nothing of it", WF.files_of(s.task, "S5|TC-9"), [])
        check_eq("release_frees_older_id: releasing the grown id frees the claim written under the first id",
                 WF.release(s.task, "S5|TC-1,TC-3"), 1)
        check_eq("release_frees_older_id: and the file is free for window 2", s.verdict(A2, TEST_FILE), None)
        check_eq("release_frees_older_id: a window with disjoint cases frees nothing of window 2's", WF.release(s.task, "S5|TC-9"), 0)
    finally:
        cleanup(s.root)
    # TR4-10 Q1: a completed S5 frees every claim of the stage; a later rework's automator is not refused by the old window's file
    s = Story([rec(A1, ["TC-1"], status="accepted"), rec(A2, ["TC-2"], status="accepted"), rec(A3, ["TC-1"])])
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        WF.claim(s.task, "tests/api/test_other.py", W2, A2)
        WF.claim(s.task, "tests/ui/test_s6.py", "S6|TC-9", "S6-x-1")
        s.set([rec(A1, ["TC-1"], status="accepted"), rec(A2, ["TC-2"], status="accepted"), rec(A3, ["TC-2"])])
        check_in("released_stage_claim_no_longer_refuses: before the release the rework automator is refused",
                 "belongs to window TC-1 until that window closes", s.verdict(A3, TEST_FILE) or "")
        check_eq("released_stage_claim_no_longer_refuses: release_stage frees both S5 claims and not the S6 one", WF.release_stage(s.task, "S5"), 2)
        check_eq("released_stage_claim_no_longer_refuses: the S6 claim stays", WF.owner(s.task, "tests/ui/test_s6.py"), "S6|TC-9")
        check_eq("released_stage_claim_no_longer_refuses: the later automator writes the old file, no refusal", s.verdict(A3, TEST_FILE), None)
        check_eq("released_stage_claim_no_longer_refuses: and the claim is now its window's", s.claimed(TEST_FILE), W2)
        empty = WF._file(s.task, "tests/api/test_crash.py")
        empty.write_text("", encoding="utf-8")
        check_eq("release_stage keeps release's empty-claim rule: the new claim goes, a young empty claim stays", [WF.release_stage(s.task, "S5"), empty.is_file()], [1, True])
        os.utime(empty, (time.time() - 3600, time.time() - 3600))
        check_eq("... and an old empty one goes", [WF.release_stage(s.task, "S5"), empty.is_file()], [1, False])
    finally:
        cleanup(s.root)
    # the conductor's command: the way out the refusal names
    s = two_windows()
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        text = s.verdict(A2, TEST_FILE) or ""
        check_in("the refusal names the conductor's exact command: the story's folder", "--task ", text)
        check_in("and the story, quoted in forward-slash form (F7)", f'artifacts/{TICKET}" --release', text)
        check_not_in("and no native backslash in the printed command (Git Bash eats it)", "\\", text[text.index("--task"):])
        words = shlex.split(text[text.index("--task"):])
        check_eq("F7: a POSIX split of the printed command gives the task folder whole", Path(words[1]).resolve(), s.task.resolve())
        spaced = Path(s.root) / "dir with space" / "qa-factory" / "artifacts" / TICKET
        shown = G._window_refusal(WF, spaced, TEST_FILE, W1, 1)
        words = shlex.split(shown[shown.index("--task"):])
        check_eq("F7: a task root with a space survives the POSIX split as ONE word", words[1], spaced.as_posix())
        check_eq("F7: and the window follows as its own word", words[3], W1)
        check_in("and the window to release", f'--release "{W1}"', text)
        check_in("and the script it runs", "scripts/window_files.py", text)
        check_eq("the command frees the claim (exit 0)", WF.main(["--task", str(s.task), "--release", W1]), 0)
        check_eq("and the file is free for window 2", s.verdict(A2, TEST_FILE), None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = WF.main(["--task", str(s.root / "no-such-story"), "--release", W1])
        check("F7: a --task folder that does not exist exits non-zero", code != 0, str(code))
        check_in("F7: and the sentence names the folder", "no-such-story does not exist", err.getvalue())
        check_not_in("F7: and it does not claim a release", "released", err.getvalue())
    finally:
        cleanup(s.root)
    # N=1: no second window to meet; nothing is claimed, the old road
    s = two_windows()
    try:
        solo = dict(s.cfg, dispatch=dict(s.cfg.get("dispatch") or {}, parallel_windows=1))
        WF.claim(s.task, TEST_FILE, W1, A1)
        saved = os.environ.get(DI.DRIVER_RUN_ENV)
        os.environ[DI.DRIVER_RUN_ENV] = A2
        try:
            got = G._blocked(G.window_file_check, s.event(TEST_FILE), solo)
            got_new = G._blocked(G.window_file_check, s.event("tests/api/test_fresh.py"), solo)
        finally:
            if saved is None:
                os.environ.pop(DI.DRIVER_RUN_ENV, None)
            else:
                os.environ[DI.DRIVER_RUN_ENV] = saved
        check_eq("n1_claims_nothing: with parallel_windows 1 a write of a claimed file passes", got, None)
        check_eq("n1_claims_nothing: and a new test file is not claimed", [got_new, s.claimed("tests/api/test_fresh.py")], [None, None])
        check_eq("n1_claims_nothing: the default (3) still refuses", bool(s.verdict(A2, TEST_FILE)), True)
    finally:
        cleanup(s.root)
    s = Story([rec(A2, ["TC-2"], request_binding={"purpose": "s5_plan"}), rec(A1, ["TC-1"])])
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        check_eq("a plan dispatch has no window and is not checked", s.verdict(A2, TEST_FILE), None)
    finally:
        cleanup(s.root)

    # 8: the race
    s = two_windows()
    try:
        results, barrier = [], threading.Barrier(8)

        def racer(i):
            barrier.wait()
            results.append((f"S5|R{i}", WF.claim(s.task, TEST_FILE, f"S5|R{i}", f"D{i}")))

        threads = [threading.Thread(target=racer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [w for w, got in results if got == w]
        check_eq("race_one_wins: exactly one of eight racers owns the file", len(winners), 1)
        check_eq("race_one_wins: and the other seven were told who", {got for _w, got in results}, {winners[0]})

        # 9: release
        check_eq("released_claim_free: release frees the winner's claim (count)", WF.release(s.task, winners[0]), 1)
        check_eq("released_claim_free: nobody holds it", WF.owner(s.task, TEST_FILE), None)
        check_eq("released_claim_free: another window claims it", WF.claim(s.task, TEST_FILE, W2, A2), W2)
        check_eq("files_of lists the claim by its key", WF.files_of(s.task, W2), [TEST_FILE])
    finally:
        cleanup(s.root)

    # 10: an empty claim after a crash
    s = two_windows()
    try:
        claim_file = WF._file(s.task, TEST_FILE)
        claim_file.parent.mkdir(parents=True, exist_ok=True)
        claim_file.write_text("", encoding="utf-8")
        text = s.verdict(A2, TEST_FILE)
        check("empty_claim_refused_with_door: refused", bool(text), str(text))
        check_in("the same door", "Put your test in a new file in the same directory: tests/api.", text or "")
        check_in("and a note that the owner is unknown", "cannot be read, so its owner is unknown", text or "")
        check_eq("the owner reads as unknown, not as nobody", WF.owner(s.task, TEST_FILE), "")
        check_eq("a young empty claim survives release (a creator may be mid-write)", WF.release(s.task, W2), 0)
        old = time.time() - 3600
        os.utime(claim_file, (old, old))
        check_eq("release clears an old empty claim", WF.release(s.task, W2), 1)
        check_eq("and the file is free", s.verdict(A2, TEST_FILE), None)
    finally:
        cleanup(s.root)

    # 11: path spellings
    s = two_windows()
    try:
        check_eq("path_spellings_same_claim: window 1 claims the file", s.verdict(A1, TEST_FILE), None)
        spellings = ["tests/api/../api/test_orders.py", "tests\\api\\test_orders.py", "./tests/api/test_orders.py",
                     "tests//api/test_orders.py"]
        if os.name == "nt":
            spellings += ["TESTS/API/Test_Orders.py", "tests\\API\\..\\api\\TEST_orders.PY"]
        for spelling in spellings:
            refused = s.verdict(A2, spelling, absolute=False)
            check(f"path_spellings_same_claim: {spelling!r} is the same claim", bool(refused), str(refused))
        check_eq("path_spellings_same_claim: one claim file for all of them", len(list((s.task / "state" / "window-files").glob("*.json"))), 1)
        check_eq("key_of folds the spelling", WF.key_of("tests\\api\\..\\api/test_orders.py"), WF.key_of("tests/api/test_orders.py"))
        check_eq("project_rel: a path outside is None", WF.project_rel(s.root, str(s.root.parent / "x" / "test_y.py")), None)
        check_eq("project_rel: the root itself is None", WF.project_rel(s.root, str(s.root)), None)
        check_eq("project_rel: `..` out of the project is None", WF.project_rel(s.root, "../test_y.py"), None)
    finally:
        cleanup(s.root)

    # F2: a second refusal on another file is the story's state, never a guard fault, and nothing stops
    s = two_windows()
    try:
        for name in ("test_a.py", "test_b.py"):
            WF.claim(s.task, f"tests/api/{name}", W1, A1)
        first = s.verdict(A2, "tests/api/test_a.py") or ""
        again = s.verdict(A2, "tests/api/test_a.py", tool="Edit") or ""
        check_not_in("fuse_names_state_not_guard: a Write then an Edit of ONE file is one call, no second-refusal text", "in a row", again)
        second = s.verdict(A2, "tests/api/test_b.py") or ""
        check_in("fuse_names_state_not_guard: refusal 2 on another file says it is the second", "This is refusal 2 in a row", second)
        check_in("fuse_names_state_not_guard: it names the story's state and the move", "Put every test of yours that needs a claimed file into a new file", second)
        for phrase in ("defect is in the guard", "Owner: the FACTORY", "story is stopped", "qa-doctor", "THIS IS REFUSAL"):
            check_not_in(f"fuse_names_state_not_guard: no {phrase!r}", phrase, second)
        check_in("fuse_names_state_not_guard: it says nothing is stopped", "Nothing is stopped", second)
        check_eq("fuse_names_state_not_guard: no backlog row is written", list(s.root.rglob("factory-backlog.md")), [])
        check_in("the first refusal carries no second-refusal text", "belongs to window TC-1", first)
        check_not_in("the first refusal carries no second-refusal text (state)", "in a row", first)
    finally:
        cleanup(s.root)

    # F8: a controller that cannot be read is said, not a silent pass
    s = two_windows()
    try:
        WF.claim(s.task, TEST_FILE, W1, A1)
        (s.task / "state" / "controller.json").write_text('{"dispatches": {', encoding="utf-8")
        err = io.StringIO()
        saved = os.environ.get(DI.DRIVER_RUN_ENV)
        os.environ[DI.DRIVER_RUN_ENV] = A2
        got = None
        hooklib.drain_notices()
        try:
            with contextlib.redirect_stderr(err):
                G.window_file_check(s.event(TEST_FILE), s.cfg)       # a SystemExit here would be a refusal
        except SystemExit as exc:
            got = exc.code
        finally:
            if saved is None:
                os.environ.pop(DI.DRIVER_RUN_ENV, None)
            else:
                os.environ[DI.DRIVER_RUN_ENV] = saved
        check_eq("unreadable_controller_is_said: the write passes (a refusal would dead-end the door)", got, None)
        queued = hooklib.drain_notices()
        check_eq("unreadable_controller_is_said: exactly one notice is queued, for the person (a journal signal)",
                 [reader for _text, reader in queued], ["person"])
        check_in("unreadable_controller_is_said: the notice names the story", f"story {TICKET} could not be read", queued[0][0] if queued else "")
        check_eq("unreadable_controller_is_said: nothing goes to stderr (nobody reads it)", err.getvalue(), "")
    finally:
        cleanup(s.root)

    finish("test_guard_window_files")


if __name__ == "__main__":
    main()
