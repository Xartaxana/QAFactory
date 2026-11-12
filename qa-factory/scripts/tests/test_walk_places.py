#!/usr/bin/env python3
"""t-1991 U0: the S7 lanes of the walk session (`settle`, `control`) - roots, per-request stand lease, lifetime (fake backend, no browser, no network).

`walk_session.py open --place case|settle|control`: `case` is N1a unchanged (root = the case root, the lease held for the session's life,
`idle_s` applies); `settle` opens its attempts under the case root of `settle-<item>` (the root of `manual_capture.py http|ui --case
settle-<item>` too); `control` under `evidence/control-<item>/` (the folder `contract.triage_control_problems` reads `control.evidence` in).
For the two S7 lanes the stand lease is taken per request and `idle_s` does not apply.
Negative control: the lease held for the session's life (the `place == "case"` branch of `Walk._start` made unconditional) ->
test_suite_run_not_blocked_by_settle_session fails.
Run: `python -B test_walk_places.py` (exit code = failures) or pytest.
"""
import contextlib
import hashlib
import io
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_manual_capture_session as SS  # noqa: E402
import test_walk_session as W  # noqa: E402
from harness import check, finish  # noqa: E402

import contract  # noqa: E402
import run_suite  # noqa: E402
import stand_lease  # noqa: E402

MC, WS = S.MC, W.WS
WALK, GO = W.WALK, W.GO
ENV = "localhost"


def must(name, ok, detail=""):
    """check + a failure under pytest too (the harness `check` only records)."""
    check(name, ok, detail)
    assert ok, f"{name}: {detail}"


def must_eq(name, got, expected):
    must(name, got == expected, f"expected {expected!r}, got {got!r}")


def must_in(name, needle, haystack):
    must(name, needle in str(haystack), f"{needle!r} not in {str(haystack)[:300]!r}")


def leased_cfg():
    cfg = SS.config()
    cfg["run"] = {"parallel": False}
    return cfg


@contextlib.contextmanager
def lane(place, items=("p1",), cfg=None, start=True):
    """A rig whose walk is `place`; the stand lease file is the temp project's."""
    rig = W.Rig(items=items, cfg=cfg)
    rig.walk = WS.Walk(rig.t.task, WALK, list(items), ["user"], place=place)
    try:
        with mock.patch.object(run_suite, "project_root", lambda: rig.t.project):
            if start:
                rig.walk.start()
            yield rig
    finally:
        WS.SEAMS["clock"] = None
        rig.done()


def leases(rig):
    return {h["job"] for r in stand_lease.status(rig.t.project)["leases"] for h in r.get("holders") or []}


def free(rig):
    """True when another job can take the stand at once (wait 0)."""
    try:
        with stand_lease.hold(rig.t.project, "other", ENV, 0):
            return True
    except stand_lease.StandBusy:
        return False


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------------------------

def test_case_root_unchanged():
    with lane("case", items=(W.CASE,)) as rig:
        code, answer = rig.step(GO, item=W.CASE)
        must_eq("a case-lane step is done", (code, answer["status"]), (0, "done"))
        must_eq("its attempt is under the case root, as in N1a", rig.walk.item_rec[W.CASE]["attempt"].dir, MC.case_root(rig.t.task, W.CASE) / "a1")
        must("and nothing is created under a settle- or control- root", not (rig.t.task / "evidence").exists()
             and not list((rig.t.task / "work" / "evidence" / "manual").glob("settle-*")))
        must_eq("the record names the lane", WS.read_record(rig.t.task, WALK)["place"], "case")


def test_case_lane_lease_unchanged():
    with lane("case", items=(W.CASE,), cfg=leased_cfg()) as rig:
        must("the case lane holds the lease for its life, between requests too", f"walk:{WALK}" in leases(rig) and not free(rig))
        rig.step(GO, item=W.CASE)
        must("...and after a request", f"walk:{WALK}" in leases(rig))
        must_eq("idle_s is 900 and applies", rig.walk.d["idle_s"], 900)
        WS.SEAMS["clock"] = lambda: rig.walk.started_at + 901
        rig.walk.last_request = rig.walk.started_at
        must_in("an idle case session ends", "idle", rig.walk.watchdog())
        rig.walk._shutdown("dead", "test", probe=False)
        must("and its end frees the stand", free(rig))


def test_settle_root_is_case_root_settle():
    with lane("settle") as rig:
        root = MC.case_root(rig.t.task, "settle-p1")
        must("the root does not exist before the first item", not root.exists())
        code, answer = rig.call("item", item="p1")
        must_eq("`item` opens a1", (code, answer["attempt"]), (0, "a1"))
        must_eq("under work/evidence/manual/settle-p1/", answer["dir"], "work/evidence/manual/settle-p1/a1")
        code, answer = rig.step(GO, item="p1")
        must_eq("a step runs in it", (code, answer["status"]), (0, "done"))
        must("the evidence is there and nothing sits under the bare item id",
             (root / "a1" / "steps.jsonl").is_file() and not MC.case_root(rig.t.task, "p1").exists())
        must_eq("the attempt's case is the settle case", rig.walk.item_rec["p1"]["attempt"].case, "settle-p1")


def test_settle_root_shared_with_http_capture():
    with lane("settle", start=False) as rig:
        # what `manual_capture.py http --case settle-p1` leaves: an attempt of the same root
        earlier = MC.Attempt(rig.t.task, "settle-p1", "a1", rig.t.cfg)
        mark = earlier.dir / "http-capture.txt"
        mark.write_text("the earlier capture", encoding="utf-8")
        before = digest(mark)
        rig.walk.start()
        must_eq("the walk's root is the capture's root", rig.walk.item_root("p1"), MC.case_root(rig.t.task, "settle-p1"))
        code, answer = rig.step(GO, item="p1")
        must_eq("the walk's attempt is the NEXT one of that root", (code, rig.walk.item_rec["p1"]["attempt"].name), (0, "a2"))
        must("the earlier attempt is not rewritten", digest(mark) == before and not (earlier.dir / "steps.jsonl").exists())


def test_control_root_passes_triage_control_problems():
    with lane("control", items=("c1",)) as rig:
        code, answer = rig.step(GO, item="c1")
        must_eq("a control step is done", (code, answer["status"]), (0, "done"))
        attempt = rig.walk.item_rec["c1"]["attempt"]
        must_eq("its attempt is evidence/control-c1/a1", attempt.dir, rig.t.task / "evidence" / "control-c1" / "a1")
        must("no manual case folder of that name was made", not (rig.t.task / "work" / "evidence" / "manual" / "control-c1").exists())
        rel = (attempt.dir / "steps.jsonl").relative_to(rig.t.task).as_posix()
        row = {"verdict": "ASSERT_STRICTER", "control": {"result": "effect_without_change", "action": "a", "without": "w", "observed": "o", "evidence": rel}}
        must_eq("triage_control_problems accepts a file of the attempt as control.evidence", contract.triage_control_problems(row, rig.t.task), [])
        other = {**row, "control": {**row["control"], "evidence": "work/evidence/manual/control-c1/a1/steps.jsonl"}}
        must("and the same file under work/ is not under evidence/ (the control)", bool(contract.triage_control_problems(other, rig.t.task)))
        must("no evidence/control-*.json file exists: the directory only", not list((rig.t.task / "evidence").glob("control-*.json")))


def test_item_id_escape_refused():
    with lane("settle", start=False) as rig:
        for place in ("settle", "control"):
            for bad in ("a/b", "..", "a..b", "C:x", "C:\\x", "a__b", "../x", "x y"):
                problems = WS.request_problems(None, {"op": "open", "task_root": str(rig.t.task), "walk": WALK, "items": [bad], "actors": ["user"], "place": place})
                must(f"{place}: item {bad!r} is refused naming the plain id", bool(problems) and "[A-Za-z0-9._-]+" in " ".join(problems), str(problems))
            good = WS.request_problems(None, {"op": "open", "task_root": str(rig.t.task), "walk": WALK, "items": ["p1", "TC-1.2_x"], "actors": ["user"], "place": place})
            must_eq(f"{place}: plain ids pass", good, [])
        must("nothing was created by the refusals", not (rig.t.task / "evidence").exists())
        try:
            WS._refuse(["x"])
        except ValueError:
            pass
        else:
            must("the refusal goes through _refuse", False)


def test_unknown_place_refused():
    with lane("settle", start=False) as rig:
        problems = WS.request_problems(None, {"op": "open", "task_root": str(rig.t.task), "walk": WALK, "items": ["p1"], "actors": ["user"], "place": "explore"})
        text = " ".join(problems)
        must("the door lists the three places", all(p in text for p in ("case", "settle", "control")), text)
        args = WS.build_parser().parse_args(["open", "--task-root", str(rig.t.task), "--walk", WALK, "--items", "p1", "--actor", "user", "--place", "explore"])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = WS.open_walk(args, wait_s=1)
        must_eq("`open --place explore` ends 2 (refused), nothing started", code, 2)
        must_in("and says which places exist", "settle", out.getvalue() + err.getvalue())


def test_next_attempt_on_reopen():
    with lane("settle") as rig:
        rig.step(GO, item="p1")
        steps = rig.walk.item_rec["p1"]["attempt"].dir / "steps.jsonl"
        before = digest(steps)
        rig.walk._shutdown("closed", "test", probe=False)
        rig.walk = WS.Walk(rig.t.task, WALK, ["p1"], ["user"], place="settle", reopened=1)
        rig.walk.start()
        rig.step(GO, item="p1")
        must_eq("a reopened lane walks the NEXT attempt", rig.walk.item_rec["p1"]["attempt"].name, "a2")
        must("and a1 is byte for byte what it was", digest(steps) == before)


def test_suite_run_not_blocked_by_settle_session():
    with lane("settle", cfg=leased_cfg()) as rig:
        must("a settle session holds no lease once started", f"walk:{WALK}" not in leases(rig) and free(rig))
        seen = []
        real = rig.walk._do
        rig.walk._do = lambda op, req: (seen.append(leases(rig)), real(op, req))[1]
        code, answer = rig.step(GO, item="p1")
        must_eq("a step runs", (code, answer["status"]), (0, "done"))
        must(f"the lease walk:{WALK} is held WHILE the request runs", seen and f"walk:{WALK}" in seen[0], str(seen))
        must("and released after it", f"walk:{WALK}" not in leases(rig))
        with stand_lease.hold(rig.t.project, "other", ENV, 0):          # the analyst's own run_suite, between two steps
            pass
        code, answer = rig.step(GO, item="p1")
        must_eq("a lease taken by another job between two steps succeeds, and the next step runs", (code, answer["status"]), (0, "done"))


def test_step_waits_then_stand_busy():
    clock = [0.0]
    holder = {"on": False, "release_at": 0.0}

    def sleep(seconds):
        clock[0] += seconds
        if holder["on"] and clock[0] >= holder["release_at"]:
            stand_lease._release(rig.t.project, "other", ENV)
            holder["on"] = False

    with lane("settle", cfg=leased_cfg()) as rig, mock.patch.object(stand_lease, "_monotonic", lambda: clock[0]), mock.patch.object(stand_lease, "_sleep", sleep):
        must_eq("the wait is data: 60 s", rig.walk.d["request_lease_wait_s"], 60)

        def take(release_at):
            clock[0] = 0.0
            must_eq("the other job holds the stand", stand_lease._try_acquire(rig.t.project, "other", ENV)[0], "acquired")
            holder.update(on=True, release_at=release_at)

        take(60.0)
        code, answer = rig.step(GO, item="p1")
        must_eq("freed at 60 s: the step waited and ran", (code, answer["status"], clock[0] >= 55), (0, "done", True))
        take(61.0)
        with contextlib.redirect_stdout(io.StringIO()):        # the lease helper prints its own stand_busy line
            code, answer = rig.step(GO, item="p1")
        must_eq("held past 60 s: exit 3 stand_busy", (code, answer["status"]), (3, "stand_busy"))
        must_eq("naming the holder", answer["holder"]["job_id"], "other")
        must_in("and the door", "call again when your own run has ended", answer["door"])
        must_eq("the session stays ready", rig.walk.state, "ready")
        stand_lease._release(rig.t.project, "other", ENV)
        holder["on"] = False
        code, answer = rig.step(GO, item="p1")
        must_eq("and walks on once the stand is free", (code, answer["status"]), (0, "done"))


def test_close_under_a_held_lease_still_closes():
    """t-2027 F4: `close` is a lease op; held past the wait it used to answer stand_busy and leave the session ready for up to max_s."""
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    with lane("settle", cfg=leased_cfg()) as rig, mock.patch.object(stand_lease, "_monotonic", lambda: clock[0]), mock.patch.object(stand_lease, "_sleep", sleep):
        must_eq("a step runs first", rig.step(GO, item="p1")[1]["status"], "done")
        must_eq("the other job holds the stand", stand_lease._try_acquire(rig.t.project, "other", ENV)[0], "acquired")
        with contextlib.redirect_stdout(io.StringIO()):
            code, answer = rig.call("close")
        must_eq("close under a held lease: closed, not stand_busy", (code, answer["status"], rig.walk.state), (0, "ok", "closed"))
        must_in("and the answer says the end probe was not taken", "end probe", answer["notes"])
        stand_lease._release(rig.t.project, "other", ENV)


def test_open_under_a_held_stand_says_the_cause():
    """t-2027 F11: the driver classes a failed open by `cause` in the answer and the record, never by a word in the reason text."""
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    with lane("settle", cfg=leased_cfg(), start=False) as rig, mock.patch.object(stand_lease, "_monotonic", lambda: clock[0]), mock.patch.object(stand_lease, "_sleep", sleep):
        must_eq("the other job holds the stand", stand_lease._try_acquire(rig.t.project, "other", ENV)[0], "acquired")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rig.walk.start()
        except WS.ServerDead as dead:
            must_eq("the exception carries the cause", dead.cause, "stand_busy")
        else:
            raise AssertionError("a held stand must stop the start")
        must_eq("and the record does", WS.read_record(rig.t.task, WALK).get("cause"), "stand_busy")
        stand_lease._release(rig.t.project, "other", ENV)


def test_settle_lane_takes_a_new_id_and_times_its_own_place():
    """t-2027 F8: a settle lane accepts any plain id (the role's own `new-<slug>`), a case lane still refuses one; the timing line names the lane."""
    with lane("settle") as rig:
        code, answer = rig.step(GO, item="new-late")
        must_eq("a step on an id the session was not opened with runs", (code, answer["status"]), (0, "done"))
        code, answer = rig.step(GO, item="bad__id")
        must_eq("an id that is no plain id is still refused", code, 2)
        must("the item is in the record", "new-late" in WS.read_record(rig.t.task, WALK)["items"], str(WS.read_record(rig.t.task, WALK)))
        must_eq("close", rig.call("close")[0], 0)
        lines = [r for r in MC.jsonl_rows(rig.t.task / "work" / "walks" / WALK / "timing.jsonl")]
        must_eq("the timing line names the lane, not `case`", sorted((r["item"], r["place"]) for r in lines), [("new-late", "settle")])
    with lane("case", items=(W.CASE,)) as rig:
        code, answer = rig.step(GO, item="new-late")
        must_eq("a case lane refuses an item it was not opened with", code, 2)


def test_settle_session_not_idle_killed():
    with lane("settle") as rig, lane("case", items=(W.CASE,)) as case_rig:
        for one in (rig, case_rig):
            WS.SEAMS["clock"] = lambda one=one: one.walk.started_at + one.walk.d["idle_s"] + 1
            one.walk.last_request = one.walk.started_at
        must_eq("a settle session idle past idle_s is still fine", rig.walk.watchdog(), "")
        WS.SEAMS["clock"] = lambda: rig.walk.started_at + rig.walk.d["idle_s"] + 1
        code, answer = rig.step(GO, item="p1")
        must_eq("and it answers a request after that", (code, rig.walk.state), (0, "ready"))
        WS.SEAMS["clock"] = lambda: case_rig.walk.started_at + case_rig.walk.d["idle_s"] + 1
        case_rig.walk.last_request = case_rig.walk.started_at
        must_in("while a case session is ended by idle_s", "idle", case_rig.walk.watchdog())
        WS.SEAMS["clock"] = lambda: rig.walk.started_at + rig.walk.d["max_s"] + 1
        rig.walk.last_request = rig.walk.started_at + rig.walk.d["max_s"]
        must_in("max_s still ends a settle session", "open for more than", rig.walk.watchdog())


def test_settle_session_dies_with_parent():
    with lane("settle") as rig:
        ES = WS.execution_scheduler
        rig.walk.parent_pid, rig.walk.parent_started = WS.os.getpid(), ES._started(WS.os.getpid())
        must_eq("the live parent is no reason", rig.walk.watchdog(), "")
        rig.walk.parent_started = "winfiletime:1"
        why = rig.walk.watchdog()
        must_in("a gone parent ends a settle session", "gone", why)
        rig.walk._shutdown("dead", why, probe=False)
        code, answer = rig.step(GO, item="p1")
        must_eq("the record says dead and a later step meets not_ready", (WS.read_record(rig.t.task, WALK)["state"], code, answer["status"]), ("dead", 3, "not_ready"))


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_walk_places")


if __name__ == "__main__":
    main()
