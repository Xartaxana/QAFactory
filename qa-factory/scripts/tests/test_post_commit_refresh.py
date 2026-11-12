#!/usr/bin/env python3
"""Derived views are refreshed AFTER the story writer lock is released, at every commit site.

The dashboard used to be rendered inside `EventStore.commit`'s projection, so the story lock
was held for as long as the render took and an observer could stall the lifecycle: on a legacy
story (TP2-2406) dispatch and recover kept answering "task has an active state writer".
The legacy fork moved the refresh into `apply` and `recover` only, which silently dropped it
at every other commit site. The mechanism here is the store's own `after_commit` step, so a
site cannot be forgotten: one test per site proves the refresh runs with the lock free.

Timing assertions are lower bounds plus generous ceilings (FR-31); the wait of a CLI is
overridden to a fraction of a second so no test sleeps for the real ten.
"""
import contextlib
import io
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CTRL  # noqa: E402
import dashboard_refresh  # noqa: E402
import environment_preparation as ENV  # noqa: E402
import event_store as ES  # noqa: E402
import hooklib  # noqa: E402
import stage_done  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import DerivedViewStale, EventStore, StateConflict  # noqa: E402

import test_controller_release as REL  # noqa: E402  (at_s3_rework: a running dispatch to act on)
import test_controller_rework_scope as SCOPED  # noqa: E402  (managed_task)


class Probe:
    """A `refresh_for_task` stand-in: records whether the story writer lock was free when called."""

    def __init__(self):
        self.free, self.busy = [], []

    def __call__(self, task_root):
        try:
            with EventStore(Path(task_root)).lock(wait_seconds=0):
                self.free.append(str(task_root))
        except StateConflict:
            self.busy.append(str(task_root))
        return {"status": "current"}


@contextlib.contextmanager
def probed(replacement=None):
    """Patch `dashboard_refresh.refresh_for_task` for the block; yield the probe."""
    original = dashboard_refresh.refresh_for_task
    probe = Probe()
    dashboard_refresh.refresh_for_task = replacement or probe
    try:
        yield probe
    finally:
        dashboard_refresh.refresh_for_task = original


def lock_free_at(site, probe, count=None):
    check(f"{site}: the refresh ran", bool(probe.free), f"free={probe.free} busy={probe.busy}")
    check_eq(f"{site}: and never while the story lock was held", probe.busy, [])
    if count is not None:
        check_eq(f"{site}: exactly {count} refresh(es)", len(probe.free), count)


def initialized(root):
    c = Controller(root)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                           "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    return c


def dispatch_request(identifier="d1", key=None):
    return {"id": identifier, "stage": "S0", "role": "qa-scout", "scope": ["TC-1"],
            "input_hash": "h", "budget": {}, "known_paths": {}, "idempotency_key": key or identifier}


def deny(root, dispatch_id):
    """The hook on `Agent` refused this dispatch: the one proof of 'nobody is doing it' that
    needs no host evidence, so `liveness_fixes` closes it."""
    path = root / "state" / "dispatch-denials.jsonl"
    path.write_text(json.dumps({"dispatch_id": dispatch_id}) + "\n", encoding="utf-8")


def events_of(root):
    return EventStore(root).read()


def read_json(path):
    """The file's JSON, or {} when it is absent: a missing marker is a failed check, not a crash."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return {}


# --- one test per commit site ------------------------------------------------------------

def site_apply():
    root = temp_project("qa-post-apply-")
    try:
        with probed() as probe:
            c = initialized(root)
            c.apply("dispatch", dispatch_request())
        lock_free_at("controller.apply (initialize + dispatch)", probe, count=2)
    finally:
        cleanup(root)


def site_apply_replay():
    root = temp_project("qa-post-replay-")
    try:
        c = initialized(root)
        with probed() as probe:
            c.apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                                   "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        check_eq("an idempotent replay re-runs the (idempotent) refresh: the door for a deferred one",
                 (len(probe.free), probe.busy), (1, []))
        check_eq("and adds no event", len(events_of(root)), 1)
    finally:
        cleanup(root)


def site_close_settled():
    root = temp_project("qa-post-settled-")
    try:
        c = REL.at_s3_rework(root)
        request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
        c.apply("dispatch", dict(request))
        deny(root, request["id"])
        before = len(events_of(root))
        with probed() as probe:
            fixes = Controller(root).close_settled()
        check("close_settled journalled a repair", bool(fixes) and len(events_of(root)) == before + 1)
        lock_free_at("controller.close_settled", probe, count=1)
    finally:
        cleanup(root)


def site_record_return():
    root = temp_project("qa-post-return-")
    try:
        c = REL.at_s3_rework(root)
        request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
        c.apply("dispatch", dict(request))
        with probed() as probe:
            recorded = Controller(root).record_return(request["id"], "halted: no account")
        check_eq("record_return wrote the fact", recorded, True)
        lock_free_at("controller.record_return (the render is kept, outside the lock)", probe, count=1)
    finally:
        cleanup(root)


def site_release():
    root = temp_project("qa-post-release-")
    try:
        c = REL.at_s3_rework(root)
        request = c.build_rework_request("S3", "qa-test-strategist", [], "redo the plan")
        c.apply("dispatch", dict(request))
        with probed() as probe:
            result = Controller(root).release_dispatch(request["id"], "it is dead, go on")
        check_eq("the release was recorded", result["released"], True)
        lock_free_at("controller.release_dispatch", probe)
    finally:
        cleanup(root)


def site_recover():
    # temp_project: no marker, no project, and liveness closes nothing (t-622); the story root is the project here
    root = temp_project("qa-post-recover-")
    try:
        c = initialized(root)
        with probed() as probe:
            result = Controller(root).recover()
        check_eq("recover with nothing to repair repairs nothing", result["journalled_repairs"], [])
        lock_free_at("controller.recover, nothing to recover (the documented door)", probe, count=1)

        c.apply("dispatch", dispatch_request("d-denied"))
        deny(root, "d-denied")
        before = len(events_of(root))
        with probed() as probe:
            result = Controller(root).recover()
        check("recover journalled its repair", bool(result["journalled_repairs"])
              and len(events_of(root)) > before, str(result["journalled_repairs"]))
        lock_free_at("controller.recover, with repairs: ONE refresh after the last commit", probe, count=1)
    finally:
        cleanup(root)


def stage_done_task(root):
    task = SCOPED.managed_task(root)
    hooklib._PROJECT_ROOT_CACHE = root
    initialized(task)
    return task


def run_stage_done(*args, status="running", **kwargs):
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        return stage_done.run("QA-1", "S1", status, "qa-scout", "", True, *args, **kwargs)


def site_stage_done():
    """`running` defers the render (SC1-12): 0 refreshes and the marker, on the commit AND on the recover of the same
    receipt. A non-running status (`halted`) still renders once at each, so the store's after-commit step stays proved
    at this site."""
    root = temp_project("qa-post-stage-done-")
    old = hooklib._PROJECT_ROOT_CACHE
    try:
        task = stage_done_task(root)
        marker = task / "state" / "dashboard-deferred.json"
        before = len(events_of(task))
        with probed() as probe:
            code = run_stage_done()
        check_eq("stage_done running committed a transition", (code, len(events_of(task))), (0, before + 1))
        check_eq("stage_done running commit: no refresh (deferred)", (probe.free, probe.busy), ([], []))
        check("stage_done running commit: the deferral marker names the stale view", marker.is_file())
        marker.unlink()
        with probed() as probe:
            code = run_stage_done()
        check_eq("the same receipt again recovers the existing event, adding none",
                 (code, len(events_of(task))), (0, before + 1))
        check_eq("stage_done running recover: no refresh (deferred)", (probe.free, probe.busy), ([], []))
        check("stage_done running recover: the marker is written again", marker.is_file())
        with probed() as probe:
            code = run_stage_done(status="halted")
        check_eq("stage_done halted committed a transition", (code, len(events_of(task))), (0, before + 2))
        lock_free_at("stage_done halted commit", probe, count=1)
        with probed() as probe:
            code = run_stage_done(status="halted")
        check_eq("the same halted receipt recovers the existing event, adding none",
                 (code, len(events_of(task))), (0, before + 2))
        lock_free_at("stage_done halted recover (recovered existing event)", probe, count=1)
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def site_environment_preparation():
    root = temp_project("qa-post-env-")
    try:
        initialized(root)
        jobs = ENV.EnvironmentJobs(root / "state" / "environment-jobs")
        with probed() as probe:
            jobs.transition({"idempotency_key": "env-1", "status": "prepared"}, "running")
        lock_free_at("environment_preparation._refresh_projection (the post step follows the with block)",
                     probe, count=1)
        check("the in-lock projection still ran: the environment job is in controller.json",
              any(j.get("receipt_ref", "").endswith(".json")
                  for j in json.loads((root / "state" / "controller.json").read_text(encoding="utf-8"))
                  .get("environment_jobs", [])))
        check("and the best-effort refresh left no stale marker",
              not (root / "state" / "environment-projection-stale.json").exists())
    finally:
        cleanup(root)


def manifest_put_is_not_a_site():
    """It commits a manifest-only projection and never refreshed: an EventStore built with no
    `after_commit` behaves exactly as before."""
    root = temp_project("qa-post-manifest-")
    try:
        with probed() as probe:
            store = EventStore(root)
            store.commit("manifest_patch", {"fragment": {}}, "k", project=lambda events: None)
        check_eq("a store with no after_commit refreshes nothing", (probe.free, probe.busy), ([], []))
        check_eq("and still commits", len(store.read()), 1)
    finally:
        cleanup(root)


# --- order and failure --------------------------------------------------------------------

@contextlib.contextmanager
def fresh_story(prefix):
    root = temp_project(prefix)
    try:
        yield root, initialized(root)
    finally:
        cleanup(root)


def apply_dispatch(c, refresh):
    """One dispatch applied with `refresh` standing in for the dashboard; (StateConflict text or '')."""
    with probed(refresh):
        try:
            c.apply("dispatch", dispatch_request())
        except StateConflict as exc:
            return str(exc)
    return ""


def order_after_commit_then_refresh():
    original = Controller._after_commit
    calls = []
    try:
        Controller._after_commit = lambda self, operation, request, key=None, revision=None: calls.append("after_commit")   # CX2-17 C-4 gave it key and revision
        with fresh_story("qa-post-order-") as (root, c):
            apply_dispatch(c, lambda task: calls.append("refresh") or {"status": "current"})
        check_eq("apply runs _after_commit first, then the derived-view refresh (initialize wrote "
                 "no refresh before the patch)", calls[-2:], ["after_commit", "refresh"])

        calls.clear()

        def broken(task):
            calls.append("refresh")
            raise RuntimeError("render exploded")
        with fresh_story("qa-post-order-fail-") as (root, c):
            calls.clear()
            raised = apply_dispatch(c, broken)
            check_eq("a refresh failure never skips _after_commit", calls, ["after_commit", "refresh"])
            check_in("and surfaces as the committed-event refusal", "event committed", raised)
            check_eq("and the commit stands", c.state()["dispatches"]["d1"]["status"], "running")
    finally:
        Controller._after_commit = original


def failure_after_the_commit():
    def exploded(task):
        raise RuntimeError("render exploded")
    with fresh_story("qa-post-fail-") as (root, c):
        before = len(events_of(root))
        raised = apply_dispatch(c, exploded)
        check("the commit raised the refusal", bool(raised))
        check_eq("the event is committed", len(events_of(root)), before + 1)
        check_in("the refusal says the event is committed", "event committed", raised)
        check_in("that the derived view was not refreshed", "derived view not refreshed", raised)
        check_in("that the action is not to be repeated", "do not repeat the action", raised)
        check_in("names what failed", "render exploded", raised)
        check_in("and the door, as a command the orchestrator can run", "--operation recover", raised)
        check_in("with the task it applies to", str(root), raised)
        check("no projection-stale.json: controller.json is current",
              not (root / "state" / "projection-stale.json").exists())
        state = json.loads((root / "state" / "controller.json").read_text(encoding="utf-8"))
        check_eq("controller.json is at the new revision", state["revision"], before + 1)
        deferred = read_json(root / "state" / "dashboard-deferred.json")
        check_eq("dashboard-deferred.json records it, owned by the factory", deferred.get("owner"), "factory")
        check_in("and says why", "render exploded", json.dumps(deferred))

        # The door opens: recover refreshes the view and repeats nothing.
        with probed() as probe:
            Controller(root).recover()
        lock_free_at("the recover door", probe, count=1)
        check_eq("recover added no copy of the action", len(events_of(root)), before + 1)

    # A factory-owned file is the same refusal.
    def owned(task):
        raise PermissionError(13, "locked", str(Path(task) / "state/controller.json"))
    with fresh_story("qa-post-owned-") as (root, c):
        raised = apply_dispatch(c, owned)
        check_in("a factory-owned file refuses after the commit, naming the door",
                 "derived view not refreshed", raised)
        check_in("and what it was", "controller.json", raised)
        check("without a stale-projection marker", not (root / "state" / "projection-stale.json").exists())

    # A shared telemetry file is not a refusal: the dashboard is deferred, the receipt returned.
    def shared(task):
        raise PermissionError(13, "in use", str(Path(task) / "state/telemetry/hook-9.aggregate.json"))
    with fresh_story("qa-post-shared-") as (root, c):
        with probed(shared):
            receipt = c.apply("dispatch", dispatch_request())
        check_eq("a shared telemetry file defers the dashboard and returns the receipt",
                 receipt["type"], "dispatch")
        deferred = read_json(root / "state" / "dashboard-deferred.json")
        check_in("recorded as a deferral over the telemetry file", "telemetry", deferred.get("file", ""))


def every_refresh_failure_ends_as_the_one_refusal():
    """After a committed event the caller is told ONE thing in ONE text: the event is durable, the view
    is stale, `recover` is the door (`DerivedViewStale`). `refresh_derived` had two raises outside its
    own handling - the import of `dashboard_refresh` and the marker write of the shared-file branch
    (on Windows `os.replace` onto a `dashboard-deferred.json` a reader holds open raises exactly
    there) - which reached the store's generic wrapper, whose text ("the step that follows it did
    not finish") the driver's `committed_event` row does not match: a conductor `retry` then
    repeated the committed action."""
    def shared(task):
        raise PermissionError(13, "in use", str(Path(task) / "state/telemetry/hook-9.aggregate.json"))

    real_atomic = CTRL.atomic_json

    def refuse_marker(path, payload):
        if Path(path).name == "dashboard-deferred.json":
            raise PermissionError(13, "held open by a reader", str(path))
        return real_atomic(path, payload)

    def with_import_failing(root, c):
        with patch.dict(sys.modules, {"dashboard_refresh": None}):
            return refused(c)

    def with_marker_refused(root, c):
        CTRL.atomic_json = refuse_marker
        try:
            with probed(shared):
                return refused(c)
        finally:
            CTRL.atomic_json = real_atomic

    def refused(c):
        try:
            c.apply("dispatch", dispatch_request())
        except StateConflict as exc:
            return exc
        return None

    for label, run, marker in (("the import of the dashboard fails", with_import_failing, True),
                               ("the marker of a shared-file deferral cannot be written", with_marker_refused,
                                False)):
        with fresh_story("qa-post-one-refusal-") as (root, c):
            before = len(events_of(root))
            exc = run(root, c)
            check(f"{label}: the commit raised", exc is not None)
            text = str(exc)
            check_eq(f"{label}: it is the committed-event refusal, not the store's wrapper",
                     type(exc), DerivedViewStale)
            check(f"{label}: of the committed family a caller catches by type (t-434 E2)",
                  isinstance(exc, getattr(ES, "EventCommitted", ())), type(exc).__mro__)
            # t-434 D: the refusal says the marker is recorded only when the write landed; both marker
            # writes refused (the shared-file one and the general one) -> it says nothing records it.
            on_disk = (root / "state" / "dashboard-deferred.json").exists()
            check_eq(f"{label}: the marker is on disk exactly when it is expected", on_disk, marker)
            if marker:
                check_in(f"{label}: and the refusal says where it is recorded",
                         "(recorded in state/dashboard-deferred.json)", text)
                check_eq(f"{label}: the type carries the same fact", getattr(exc, "recorded_in", None),
                         "state/dashboard-deferred.json")
            else:
                check_not_in(f"{label}: and the refusal claims no record", "recorded in", text)
                check_in(f"{label}: it says in words that nothing records the stale view",
                         "nothing on disk records that the view is stale", text)
                check_eq(f"{label}: the type carries the same fact", getattr(exc, "recorded_in", None), "")
            check_in(f"{label}: the view is not refreshed", "derived view not refreshed", text)
            check_not_in(f"{label}: and the generic third text is not used",
                         "the step that follows it did not finish", text)
            check_in(f"{label}: do not repeat", "do not repeat the action", text)
            check_in(f"{label}: the door", "--operation recover", text)
            check_eq(f"{label}: the event is in the store", len(events_of(root)), before + 1)
            with probed() as probe:
                Controller(root).recover()
            lock_free_at(f"{label}: recover refreshes the view", probe, count=1)
            check_eq(f"{label}: and repeats nothing", len(events_of(root)), before + 1)


def the_deferral_marker_goes_when_the_view_is_current():
    """`state/dashboard-deferred.json` says "could not be refreshed ... recover refreshes it".
    Once a refresh succeeds that sentence is false, and a reader of the folder (a person, the
    dashboard, a later session) would believe a view is stale that is not (FR-41). The marker
    leaves the same way `projection-stale.json` does: the success that makes it untrue removes it."""
    def exploded(task):
        raise RuntimeError("render exploded")

    def shared(task):
        raise PermissionError(13, "in use", str(Path(task) / "state/telemetry/hook-9.aggregate.json"))

    for label, failing in (("a failed refresh", exploded), ("a shared-file deferral", shared)):
        with fresh_story("qa-post-marker-") as (root, c):
            marker = root / "state" / "dashboard-deferred.json"
            check(f"{label}: no marker before anything failed", not marker.exists())
            apply_dispatch(c, failing)
            check(f"{label}: the marker is written", marker.exists())
            check_eq(f"{label}: and owned by the factory", read_json(marker).get("owner"), "factory")
            with probed() as probe:
                Controller(root).recover()
            lock_free_at(f"{label}: recover refreshes the view", probe, count=1)
            check(f"{label}: and the marker is gone with it", not marker.exists())

            # Next event, next success: a marker that is not there stays not there.
            apply_dispatch(c, failing)
            check(f"{label}: a new failure writes it again", marker.exists())
            with probed() as probe:
                c.apply("checkpoint", {"id": "d1", "status": "paused", "reason": "waiting",
                                       "checkpoint": {"remaining": ["TC-1"]}, "idempotency_key": "cp-m"})
            check(f"{label}: the next successful refresh of an ordinary event clears it too",
                  not marker.exists())
            with probed() as probe:
                Controller(root).recover()
            check(f"{label}: and a success with no marker to clear is not an error", not marker.exists())

    # Only a refresh that actually made the view current clears the marker. `refresh_for_task`
    # also returns `skipped` (QA_FACTORY_SKIP_DASHBOARD_REFRESH), `not_configured` (no
    # qa-factory/config.json above the task) and `pending` (inputs changed while rendering, or
    # another projection writer was active): in each of those the view is NOT current and the
    # marker's sentence is still true. `current` is the one success (a cached `previous` receipt
    # returned unchanged carries it too).
    for result, clears in (({"status": "current"}, True), ({"status": "skipped", "reason": "env"}, False),
                           ({"status": "not_configured"}, False),
                           ({"status": "pending", "reason": "changed while rendering"}, False),
                           ({}, False), (None, False)):
        with fresh_story("qa-post-marker-result-") as (root, c):
            marker = root / "state" / "dashboard-deferred.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"status": "deferred", "owner": "factory"}), encoding="utf-8")
            with probed(lambda task, _r=result: _r):
                c.apply("dispatch", dispatch_request())
            check_eq(f"a refresh that returned {result!r} {'clears' if clears else 'leaves'} the marker",
                     not marker.exists(), clears)

    # A marker that cannot be removed is no reason to lose the success.
    with fresh_story("qa-post-marker-stuck-") as (root, c):
        marker = root / "state" / "dashboard-deferred.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        original = Path.unlink

        def refuse(self, *args, **kwargs):
            if self.name == "dashboard-deferred.json":
                raise PermissionError(13, "held", str(self))
            return original(self, *args, **kwargs)
        Path.unlink = refuse
        try:
            with probed():
                raised = ""
                try:
                    c.apply("dispatch", dispatch_request())
                except StateConflict as exc:
                    raised = str(exc)
        finally:
            Path.unlink = original
        check_eq("an unremovable marker does not turn a successful refresh into a refusal", raised, "")


def a_failed_render_after_a_hook_return_is_not_retried():
    """SubagentStop's record_return never raises and never writes the fact twice: the return IS
    committed when the render after it fails, so it reports True and does not loop on the
    'conflict' (a retry would find the dispatch no longer running and answer False)."""
    root = temp_project("qa-post-return-fail-")
    try:
        c = REL.at_s3_rework(root)
        request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
        c.apply("dispatch", dict(request))
        calls = []

        def exploded(task):
            calls.append(1)
            raise RuntimeError("render exploded")
        with probed(exploded):
            outcome = Controller(root).record_return(request["id"], "halted")
        check_eq("record_return still reports the recorded return", outcome, True)
        check_eq("the refresh was tried once, not retried as a lock conflict", len(calls), 1)
        check_eq("and exactly one return event exists",
                 [e["type"] for e in events_of(root)].count("returned"), 1)
    finally:
        cleanup(root)


def the_post_step_sees_a_current_projection_and_commits_nothing():
    """No re-entry: by the time the step runs, controller.json carries the new revision, and the
    step itself adds no event to the journal it follows."""
    root = temp_project("qa-post-current-")
    try:
        seen = []

        def look(task_root):
            count = len(EventStore(Path(task_root)).read())
            revision = read_json(Path(task_root) / "state" / "controller.json").get("revision")
            seen.append((count, revision))
            return {"status": "current"}
        with probed(look):
            c = initialized(root)
            c.apply("dispatch", dispatch_request())
        check_eq("at each refresh controller.json is at the journal's revision",
                 seen, [(1, 1), (2, 2)])
        check_eq("and the steps added no event of their own", len(events_of(root)), 2)
    finally:
        cleanup(root)


def failure_inside_the_lock_keeps_its_contract():
    root = temp_project("qa-post-inlock-")
    try:
        c = initialized(root)
        refreshed = []
        original = Controller.project

        def broken(self, events):
            raise OSError("projection disk failure")
        Controller.project = broken
        raised, caught = "", None
        try:
            with probed(lambda task: refreshed.append(1) or {}):
                try:
                    c.apply("dispatch", dispatch_request())
                except StateConflict as exc:
                    raised, caught = str(exc), exc
        finally:
            Controller.project = original
        check_in("an in-lock failure is still 'projection stale; recover'", "projection stale", raised)
        check("t-434 E2: and of the committed family, through apply too",
              isinstance(caught, getattr(ES, "EventCommitted", ())), type(caught).__mro__)
        check("and writes projection-stale.json as today",
              (root / "state" / "projection-stale.json").exists())
        check_eq("the derived views are not refreshed over a stale projection", refreshed, [])
    finally:
        cleanup(root)


# --- who waits ----------------------------------------------------------------------------

@contextlib.contextmanager
def spied_waits():
    """Record the wait every `EventStore.lock` call was given."""
    waits = []
    original = EventStore.lock

    def spy(self, wait_seconds=0.0):
        waits.append(wait_seconds)
        return original(self, wait_seconds)
    EventStore.lock = spy
    try:
        yield waits
    finally:
        EventStore.lock = original


@contextlib.contextmanager
def lifecycle_wait(seconds):
    old = ES.LIFECYCLE_WAIT_SECONDS
    ES.LIFECYCLE_WAIT_SECONDS = seconds
    try:
        yield
    finally:
        ES.LIFECYCLE_WAIT_SECONDS = old


def hold_lock(root, release):
    acquired = threading.Event()

    def hold():
        with EventStore(root).lock():
            acquired.set()
            release.wait(10)
    holder = threading.Thread(target=hold)
    holder.start()
    check("the other writer holds the lock", acquired.wait(5))
    return holder


def a_hook_path_does_not_wait():
    root = temp_project("qa-post-hook-")
    try:
        c = REL.at_s3_rework(root)
        request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
        c.apply("dispatch", dict(request))
        with lifecycle_wait(30.0), spied_waits() as waits:
            check_eq("record_return writes the fact", Controller(root).record_return(request["id"], "x"), True)
        check("record_return (the SubagentStop hook's path) takes the lock without a wait",
              waits and set(waits) == {0.0}, str(waits))
    finally:
        cleanup(root)


def a_held_lock_fails_a_hook_at_once():
    root = temp_project("qa-post-hook-held-")
    try:
        c = REL.at_s3_rework(root)
        request = c.build_rework_request("S3", "qa-test-strategist", [], "one more pass")
        c.apply("dispatch", dict(request))
        release = threading.Event()
        holder = hold_lock(root, release)
        try:
            started = time.monotonic()
            with lifecycle_wait(30.0):
                outcome = Controller(root).record_return(request["id"], "x")
            elapsed = time.monotonic() - started
        finally:
            release.set()
            holder.join(10)
        check_eq("record_return over a held lock returns False (the fact stays in the project journal)",
                 outcome, False)
        check("after its own short retries only, never the lifecycle wait", elapsed < 8.0, f"{elapsed:.2f}s")
        check_eq("and nothing was appended", [e["type"] for e in events_of(root)].count("returned"), 0)
    finally:
        cleanup(root)


def a_cli_path_waits():
    root = temp_project("qa-post-cli-")
    argv = sys.argv
    try:
        initialized(root)
        sys.argv = ["controller.py", "--task-root", str(root), "--operation", "recover"]
        release = threading.Event()
        holder = hold_lock(root, release)
        timer = threading.Timer(0.25, release.set)
        timer.start()
        started = time.monotonic()
        out = io.StringIO()
        with lifecycle_wait(2.0), contextlib.redirect_stdout(out):
            CTRL.main()
        elapsed = time.monotonic() - started
        timer.cancel()
        holder.join(10)
        check("the controller CLI waited for the writer, then recovered", elapsed >= 0.2, f"{elapsed:.2f}s")
        check("within its bound", elapsed < 3.0, f"{elapsed:.2f}s")
        check_in("and printed the recover result", '"revision"', out.getvalue())

        # Past the bound it refuses, after at least the bound.
        release = threading.Event()
        holder = hold_lock(root, release)
        started = time.monotonic()
        refused = ""
        try:
            with lifecycle_wait(0.3), contextlib.redirect_stdout(io.StringIO()):
                try:
                    CTRL.main()
                except StateConflict as exc:
                    refused = str(exc)
            elapsed = time.monotonic() - started
        finally:
            release.set()
            holder.join(10)
        check_eq("a writer held past the bound still conflicts", refused, "task has an active state writer")
        check("after waiting at least the bound", elapsed >= 0.3, f"{elapsed:.2f}s")
        check("and not much longer", elapsed < 1.3, f"{elapsed:.2f}s")
    finally:
        sys.argv = argv
        cleanup(root)


def every_lifecycle_cli_chooses_its_wait_at_main():
    """controller, stage_done, manifest_put, story_step pass the lifecycle wait; the library
    call of the same function keeps 0, so a hook that calls it never inherits a wait."""
    root = temp_project("qa-post-wait-")
    old = hooklib._PROJECT_ROOT_CACHE
    argv = sys.argv
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}),
                                            encoding="utf-8")
        c = initialized(task)
        c.apply("dispatch", dispatch_request("d-pause"))

        # --- stage_done: the library function keeps 0, main passes the wait.
        with lifecycle_wait(0.37), spied_waits() as waits:
            run_stage_done()
        check("stage_done.run called as a library keeps the immediate default",
              waits and set(waits) == {0.0}, str(waits))
        with lifecycle_wait(0.37), spied_waits() as waits, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            stage_done.main(["--task", "QA-1", "--stage", "S2", "--status", "running",
                             "--role", "qa-requirements-tester", "--no-journal"])
        check("stage_done main passes the lifecycle wait to its commit",
              0.37 in waits, str(waits))

        # --- story_step: main chooses the wait for the controller it builds.
        import story_step
        sys.argv = ["story_step.py", "pause", "--task", "QA-1", "--dispatch-id", "d-pause",
                    "--reason", "waiting for the person"]
        with lifecycle_wait(0.37), spied_waits() as waits, contextlib.redirect_stdout(io.StringIO()):
            story_step.main()
        check("story_step main passes the lifecycle wait to the controller's commit",
              0.37 in waits, str(waits))
        check("story_step's controller commit is the only waiting lock", set(waits) <= {0.0, 0.37}, str(waits))

        # --- manifest_put: main passes it, run() called as a library does not.
        import manifest_put
        fragment = root / "fragment.json"
        fragment.write_text(json.dumps({"tests": [{"case": "TC-001", "file": "a.py",
                                                   "marker": "TC-001"}]}), encoding="utf-8")
        with lifecycle_wait(0.37), spied_waits() as waits, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            manifest_put.run("QA-1", str(fragment))
        check("manifest_put.run called as a library keeps the immediate default",
              waits and set(waits) == {0.0}, str(waits))
        fragment.write_text(json.dumps({"tests": [{"case": "TC-002", "file": "a.py",
                                                   "marker": "TC-002"}]}), encoding="utf-8")
        sys.argv = ["manifest_put.py", "--task", "QA-1", "--fragment", str(fragment)]
        with lifecycle_wait(0.37), spied_waits() as waits, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                manifest_put.main()
            except SystemExit:
                pass
        check("manifest_put main passes the lifecycle wait to its commit", 0.37 in waits, str(waits))
    finally:
        sys.argv = argv
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def role_invoked_clis_choose_their_wait_at_main():
    """manifest_from_tests and migrate_coverage are commands a role (or the driver) runs; their
    `main` passes the lifecycle wait to the commit they make, and the library function under
    each keeps 0. (manual_evidence.py commits nothing: `prepare` only reads the controller, so
    there is no commit to pass a wait to.)"""
    import os
    import migrate_coverage
    import manifest_from_tests
    import test_manifest_from_tests as TMFT
    import test_migrate_coverage as TMC
    old = hooklib._PROJECT_ROOT_CACHE
    argv = sys.argv
    cwd = Path.cwd()
    quiet = (contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()))
    root = temp_project("qa-post-wait2-")
    try:
        use_project(root)
        TMFT.seed(root)
        sys.argv = ["manifest_from_tests.py", "--task", TMFT.TICKET, "--dispatch", TMFT.DISPATCH,
                    "--file", "tests/test_coupon.py", "--file", "tests/data_coupon.py"]
        os.chdir(root)
        with lifecycle_wait(0.37), spied_waits() as waits, quiet[0], quiet[1]:
            code = manifest_from_tests.main()
        check_eq("manifest_from_tests main ran its put", code, 0)
        check("manifest_from_tests main passes the lifecycle wait to the commit it makes",
              0.37 in waits, str(waits))
    finally:
        os.chdir(cwd)
        sys.argv = argv
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)

    base = temp_project("qa-post-migrate-")
    try:
        def seeded(name):
            task = base / name
            task.mkdir()
            Controller(task).apply("initialize", {"scope": ["TC-1"], "source_revision": "src",
                                                  "known_paths": {"root": str(task)},
                                                  "coverage_contract_version": 1,
                                                  "idempotency_key": "init"})
            TMC.legacy_plan(task)
            return task
        library = seeded("library")
        with lifecycle_wait(0.37), spied_waits() as waits:
            check_eq("migrate called as a library completes", migrate_coverage.migrate(library)["status"],
                     "completed")
        check("migrate_coverage.migrate called as a library keeps the immediate default",
              waits and set(waits) == {0.0}, str(waits))
        cli = seeded("cli")
        sys.argv = ["migrate_coverage.py", str(cli), "--apply"]
        try:
            with lifecycle_wait(0.37), spied_waits() as waits, quiet[0], quiet[1]:
                migrate_coverage.main()
        finally:
            sys.argv = argv
        check("migrate_coverage main passes the lifecycle wait to its commit", 0.37 in waits, str(waits))
    finally:
        cleanup(base)


def main():
    site_apply()
    site_apply_replay()
    site_close_settled()
    site_record_return()
    site_release()
    site_recover()
    site_stage_done()
    site_environment_preparation()
    manifest_put_is_not_a_site()
    order_after_commit_then_refresh()
    failure_after_the_commit()
    every_refresh_failure_ends_as_the_one_refusal()
    the_deferral_marker_goes_when_the_view_is_current()
    a_failed_render_after_a_hook_return_is_not_retried()
    the_post_step_sees_a_current_projection_and_commits_nothing()
    failure_inside_the_lock_keeps_its_contract()
    a_hook_path_does_not_wait()
    a_held_lock_fails_a_hook_at_once()
    a_cli_path_waits()
    every_lifecycle_cli_chooses_its_wait_at_main()
    role_invoked_clis_choose_their_wait_at_main()
    finish("test_post_commit_refresh")


if __name__ == "__main__":
    main()
