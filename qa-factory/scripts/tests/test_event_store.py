"""Crash, corruption and idempotency seams, without project side effects."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
import event_store
from event_store import DerivedViewStale, EventStore, StateConflict, atomic_json
from controller import Controller


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        mark_project(Path(self.temp.name))          # the stories below live in a project (the controller tests in this class need one)
        self.root = Path(self.temp.name) / "QA-1"
        self.root.mkdir()                           # a story's journal is written into a folder that EXISTS (S0 makes it; CX1-18)
        self.store = EventStore(self.root)

    def story(self, name):
        """A second story folder beside QA-1: the folder exists before its journal is written."""
        folder = self.root.parent / name
        folder.mkdir(exist_ok=True)
        return folder

    def test_validate_before_write(self):
        def invalid(events, payload):
            raise ValueError("missing evidence")
        with self.assertRaises(ValueError):
            self.store.commit("accept", {}, "k", validate=invalid)
        self.assertFalse(self.store.log.exists())

    def test_idempotency_and_cas(self):
        first = self.store.commit("a", {"x": 1}, "k", 0)
        self.assertEqual(first, self.store.commit("a", {"x": 1}, "k", 0))
        with self.assertRaises(StateConflict):
            self.store.commit("a", {"x": 2}, "k")
        with self.assertRaises(StateConflict):
            self.store.commit("a", {}, "new", 0)
        self.assertEqual(len(self.store.read()), 1)

    def test_projection_crash_is_recoverable(self):
        def crash(events):
            raise OSError("projection disk failure")
        with self.assertRaises(StateConflict):
            self.store.commit("a", {}, "k", project=crash)
        self.assertEqual(len(self.store.read()), 1)
        projected = []
        self.store.recover(projected.extend)
        self.assertEqual(len(projected), 1)
        self.assertFalse((self.store.state / "projection-stale.json").exists())

    def test_retry_rebuild_clears_stale_without_duplicate_event(self):
        def crash(events):
            raise OSError("projection unavailable")
        with self.assertRaises(StateConflict):
            self.store.commit("a", {}, "k", project=crash)
        self.store.commit("a", {}, "k", project=lambda events: None)
        self.assertEqual(len(self.store.read()), 1)
        self.assertFalse((self.store.state / "projection-stale.json").exists())
        with self.assertRaises(StateConflict):
            self.store.commit("a", {}, "k", project=crash)
        self.assertTrue((self.store.state / "projection-stale.json").exists())

    def test_torn_tail_not_middle_corruption(self):
        self.store.commit("a", {}, "k")
        with self.store.log.open("ab") as f:
            f.write(b'{"partial":')
        with self.assertRaises(StateConflict):
            self.store.read()
        self.assertEqual(self.store.recover(lambda events: None), 1)
        self.assertEqual(len(list(self.store.state.glob("recovery-*.bin"))), 1)
        self.store.log.write_bytes(self.store.log.read_bytes().replace(b'"type": "a"', b'"type": "b"'))
        with self.assertRaises(StateConflict):
            self.store.commit("a", {}, "next")

    def test_task_lock_is_scoped(self):
        with self.store.lock():
            # The default is an immediate refusal: every existing caller depends on it.
            with self.assertRaises(StateConflict):
                self.store.commit("a", {}, "k")
            with self.assertRaises(StateConflict):
                with EventStore(self.root).lock(wait_seconds=0):
                    pass
            EventStore(self.story("QA-2")).commit("a", {}, "other")

    # --- bounded lock wait (M8) -------------------------------------------------------
    # Timing assertions are lower bounds plus generous ceilings (wait + 1 s): FR-31.

    def _hold_lock(self, release):
        """Hold the task lock on another handle until `release` is set; return the thread."""
        acquired = threading.Event()

        def hold():
            with EventStore(self.root).lock():
                acquired.set()
                release.wait(5)
        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(acquired.wait(5))
        self.addCleanup(holder.join, 5)
        self.addCleanup(release.set)
        return holder

    def test_writer_waits_for_an_inflight_projection_lock(self):
        release = threading.Event()
        holder = self._hold_lock(release)
        timer = threading.Timer(0.15, release.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        self.store.commit("a", {}, "waited", wait_seconds=1.0)
        elapsed = time.monotonic() - started
        holder.join(5)
        self.assertFalse(holder.is_alive())
        self.assertGreaterEqual(elapsed, 0.10)
        self.assertLess(elapsed, 2.0)
        self.assertEqual(len(self.store.read()), 1)

    def test_recover_waits_for_the_lock_when_asked(self):
        self.store.commit("a", {}, "k")
        release = threading.Event()
        holder = self._hold_lock(release)
        with self.assertRaises(StateConflict):
            self.store.recover(lambda events: None)
        timer = threading.Timer(0.15, release.set)
        timer.start()
        self.addCleanup(timer.cancel)
        self.assertEqual(self.store.recover(lambda events: None, wait_seconds=1.0), 1)
        holder.join(5)
        self.assertFalse(holder.is_alive())

    def test_lock_held_past_the_wait_conflicts_and_touches_nothing(self):
        self.store.commit("a", {}, "k")
        release = threading.Event()
        self._hold_lock(release)
        lock_file = self.store.state / "events.lock"
        size_before = lock_file.stat().st_size
        log_before = self.store.log.read_bytes()
        started = time.monotonic()
        with self.assertRaises(StateConflict) as caught:
            self.store.commit("a", {}, "late", wait_seconds=0.2)
        elapsed = time.monotonic() - started
        self.assertEqual(str(caught.exception), "task has an active state writer")
        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 1.2)
        self.assertTrue(lock_file.exists())
        self.assertEqual(lock_file.stat().st_size, size_before)
        self.assertEqual(self.store.log.read_bytes(), log_before)
        self.assertEqual(len(self.store.read()), 1)

    def test_zero_negative_and_none_wait_are_immediate(self):
        release = threading.Event()
        self._hold_lock(release)
        for wait in (0, 0.0, -5, -0.001, None):
            started = time.monotonic()
            with self.assertRaises(StateConflict, msg=repr(wait)):
                with self.store.lock(wait_seconds=wait):
                    pass
            self.assertLess(time.monotonic() - started, 1.0, repr(wait))
        started = time.monotonic()
        with self.assertRaises(StateConflict):
            self.store.commit("a", {}, "k", wait_seconds=-1)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_non_finite_wait_is_a_value_error_and_writes_nothing(self):
        for wait in (float("inf"), float("-inf"), float("nan")):
            with self.assertRaises(ValueError, msg=repr(wait)):
                with self.store.lock(wait_seconds=wait):
                    pass
            with self.assertRaises(ValueError, msg=repr(wait)):
                self.store.commit("a", {}, "k", wait_seconds=wait)
        self.assertFalse(self.store.log.exists())
        # A refused value must not leave the lock taken.
        with self.store.lock():
            pass

    def test_a_bool_is_not_a_wait(self):
        """`True` is 1.0 and `False` is 0.0 to `float()`: a flag that reached a wait parameter by
        mistake used to become a second of waiting, or none, without a word."""
        for wait in (True, False):
            with self.assertRaises(ValueError, msg=repr(wait)) as raised:
                with self.store.lock(wait_seconds=wait):
                    pass
            self.assertIn("seconds", str(raised.exception))
            with self.assertRaises(ValueError, msg=repr(wait)):
                self.store.commit("a", {}, "k", wait_seconds=wait)
            with self.assertRaises(ValueError, msg=repr(wait)):
                EventStore(self.root, wait_seconds=wait)
        self.assertFalse(self.store.log.exists())
        with self.store.lock():  # a refused value leaves no lock taken
            pass

    def test_commit_keeps_its_positional_parameters(self):
        calls = []
        event = self.store.commit("a", {"x": 1}, "k", 0, lambda events, payload: calls.append("v"),
                                  lambda events: calls.append("p"))
        self.assertEqual(calls, ["v", "p"])
        self.assertEqual(event["sequence"], 1)

    # --- projection replace retry (M8) ------------------------------------------------

    def _failing_replace(self, failures, winerror=5, attempts=None, only=None):
        """An os.replace that fails `failures` times with a PermissionError, then really replaces."""
        real_replace = os.replace
        attempts = attempts if attempts is not None else []

        def transient(source, destination):
            if only is not None and Path(destination).name != only:
                return real_replace(source, destination)
            attempts.append((source, destination))
            if len(attempts) <= failures:
                error = PermissionError(winerror, "Access is denied", str(destination))
                error.winerror = winerror
                raise error
            return real_replace(source, destination)
        return transient

    def test_windows_projection_replace_retries_a_brief_reader_race(self):
        target = self.root / "pipeline.json"
        attempts = []
        replace = self._failing_replace(2, attempts=attempts)
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", replace), patch("event_store.time.sleep"):
            atomic_json(target, {"projection": "current"})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"projection": "current"})
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_replace_retry_backoff_is_linear(self):
        target = self.root / "pipeline.json"
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", self._failing_replace(3)), \
                patch("event_store.time.sleep") as sleep:
            atomic_json(target, {"a": 1})
        delays = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(len(delays), 3)
        for got, want in zip(delays, (0.025, 0.05, 0.075)):
            self.assertAlmostEqual(got, want, places=6)

    def test_replace_succeeds_at_the_attempt_limit(self):
        target = self.root / "pipeline.json"
        attempts = []
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", self._failing_replace(7, attempts=attempts)), \
                patch("event_store.time.sleep"):
            atomic_json(target, {"projection": "late"})
        self.assertEqual(len(attempts), 8)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"projection": "late"})
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_replace_beyond_the_limit_reraises_and_leaves_no_tmp(self):
        target = self.root / "pipeline.json"
        attempts = []
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", self._failing_replace(8, attempts=attempts)), \
                patch("event_store.time.sleep"):
            with self.assertRaises(PermissionError) as caught:
                atomic_json(target, {"projection": "never"})
        self.assertEqual(len(attempts), 8)
        self.assertEqual(caught.exception.winerror, 5)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_other_permission_errors_are_not_retried(self):
        target = self.root / "pipeline.json"
        attempts = []
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", self._failing_replace(99, winerror=13, attempts=attempts)), \
                patch("event_store.time.sleep") as sleep:
            with self.assertRaises(PermissionError):
                atomic_json(target, {"a": 1})
        self.assertEqual(len(attempts), 1)
        sleep.assert_not_called()
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_sharing_violation_32_is_retried(self):
        target = self.root / "pipeline.json"
        attempts = []
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", self._failing_replace(1, winerror=32, attempts=attempts)), \
                patch("event_store.time.sleep"):
            atomic_json(target, {"a": 1})
        self.assertEqual(len(attempts), 2)

    def test_non_windows_replace_is_attempted_once(self):
        target = self.root / "pipeline.json"
        attempts = []
        with patch("event_store._is_windows", return_value=False), \
                patch("event_store.os.replace", self._failing_replace(99, attempts=attempts)), \
                patch("event_store.time.sleep") as sleep:
            with self.assertRaises(PermissionError):
                atomic_json(target, {"a": 1})
        self.assertEqual(len(attempts), 1)
        sleep.assert_not_called()
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_a_non_permission_failure_is_not_retried_and_leaves_no_tmp(self):
        target = self.root / "pipeline.json"
        calls = []

        def broken(source, destination):
            calls.append(1)
            raise OSError(28, "No space left on device")
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", broken), patch("event_store.time.sleep"):
            with self.assertRaises(OSError):
                atomic_json(target, {"a": 1})
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_a_brief_race_inside_a_projection_does_not_make_it_stale(self):
        attempts = []
        replace = self._failing_replace(2, attempts=attempts, only="pipeline.json")

        def project(events):
            atomic_json(self.store.state / "pipeline.json", {"revision": len(events)})
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", replace), patch("event_store.time.sleep"):
            event = self.store.commit("a", {}, "k", project=project)
        self.assertEqual(event["sequence"], 1)
        self.assertEqual(len(attempts), 3)
        self.assertFalse((self.store.state / "projection-stale.json").exists())

    def test_a_race_that_survives_the_retries_still_reads_as_committed_stale(self):
        replace = self._failing_replace(99, only="pipeline.json")

        def project(events):
            atomic_json(self.store.state / "pipeline.json", {"revision": len(events)})
        with patch("event_store._is_windows", return_value=True), \
                patch("event_store.os.replace", replace), patch("event_store.time.sleep"):
            with self.assertRaises(StateConflict) as caught:
                self.store.commit("a", {}, "k", project=project)
        self.assertIn("event committed; projection stale; recover, do not repeat action",
                      str(caught.exception))
        self.assertEqual(len(self.store.read()), 1)
        stale = json.loads((self.store.state / "projection-stale.json").read_text(encoding="utf-8"))
        self.assertEqual(stale["revision"], 1)
        self.assertEqual(self.store.recover(project), 1)
        self.assertFalse((self.store.state / "projection-stale.json").exists())

    # --- the after-commit step (M3) -----------------------------------------------------
    # One mechanism for every commit site: `after_commit` runs once the writer lock is free.

    def _store_with(self, step, **options):
        return EventStore(self.root, after_commit=step, **options)

    def _lock_is_free(self):
        try:
            with EventStore(self.root).lock(wait_seconds=0):
                return True
        except StateConflict:
            return False

    def test_after_commit_runs_after_the_lock_is_released_on_commit_and_recover(self):
        seen = []
        store = self._store_with(lambda: seen.append(self._lock_is_free()))
        store.commit("a", {}, "k", project=lambda events: seen.append("project"))
        self.assertEqual(seen, ["project", True])
        seen.clear()
        self.assertEqual(store.recover(lambda events: seen.append("project")), 1)
        self.assertEqual(seen, ["project", True])

    def test_after_commit_runs_on_a_replay_and_on_a_recover_with_nothing_to_do(self):
        seen = []
        store = self._store_with(lambda: seen.append("after"))
        first = store.commit("a", {"x": 1}, "k")
        self.assertEqual(store.commit("a", {"x": 1}, "k"), first)
        self.assertEqual(seen, ["after", "after"])
        self.assertEqual(len(store.read()), 1)
        seen.clear()
        empty = EventStore(self.story("QA-empty"), after_commit=lambda: seen.append("after"))
        self.assertEqual(empty.recover(lambda events: None), 0)
        self.assertEqual(seen, ["after"])

    def test_a_store_without_after_commit_behaves_as_before(self):
        store = EventStore(self.root)
        self.assertIsNone(store.after_commit)
        self.assertEqual(store.commit("a", {}, "k")["sequence"], 1)
        self.assertEqual(store.recover(lambda events: None), 1)

    def test_a_failing_projection_runs_no_after_commit(self):
        seen = []
        store = self._store_with(lambda: seen.append("after"))

        def crash(events):
            raise OSError("projection disk failure")
        with self.assertRaises(StateConflict) as caught:
            store.commit("a", {}, "k", project=crash)
        self.assertIn("projection stale", str(caught.exception))
        self.assertEqual(seen, [])
        self.assertTrue((self.store.state / "projection-stale.json").exists())

    def test_a_failing_after_commit_leaves_the_commit_and_names_what_happened(self):
        def broken():
            raise RuntimeError("view exploded")
        store = self._store_with(broken)
        with self.assertRaises(StateConflict) as caught:
            store.commit("a", {}, "k", project=lambda events: None)
        self.assertIsInstance(caught.exception, DerivedViewStale)
        for part in ("event committed", "do not repeat the action", "view exploded"):
            self.assertIn(part, str(caught.exception))
        self.assertEqual(len(store.read()), 1)
        self.assertFalse((self.store.state / "projection-stale.json").exists())
        self.assertTrue(self._lock_is_free())

    # --- "committed, but what follows did not finish" is ONE type (t-434 E2, FR-12) --------
    # `story_step finish` runs a committed accept's tail by the TYPE of the refusal; a raise
    # that says "event committed" but is a plain StateConflict skipped the tail.

    def _committed_raises(self):
        """(label, exception) for every raise of the store that says the event is committed."""
        def crash(events):
            raise OSError("projection disk failure")

        def broken():
            raise RuntimeError("view exploded")
        found = []
        for label, run in (
                ("projection fails on a new event",
                 lambda: self.store.commit("a", {}, "k1", project=crash)),
                ("projection fails on a replay of a committed event",
                 lambda: self.store.commit("a", {}, "k1", project=crash)),
                ("the after-commit step fails",
                 lambda: EventStore(self.story("QA-after"), after_commit=broken)
                 .commit("a", {}, "k2"))):
            try:
                run()
                found.append((label, None))
            except Exception as exc:  # what each raise IS is the case under test
                found.append((label, exc))
        return found

    def test_every_committed_raise_is_of_the_committed_family(self):
        family = getattr(event_store, "EventCommitted", None)
        self.assertIsNotNone(family, "event_store has no EventCommitted type")
        raised = self._committed_raises()
        texts = [str(exc) for _label, exc in raised]
        self.assertTrue(texts[0].startswith("event committed; projection stale"), texts[0])
        self.assertTrue(texts[1].startswith("event already committed; projection stale"), texts[1])
        self.assertTrue(texts[2].startswith("event committed; the step that follows"), texts[2])
        for label, exc in raised:
            with self.subTest(label):
                self.assertIsInstance(exc, family)
                self.assertIsInstance(exc, StateConflict, "still a StateConflict for older callers")
        self.assertIsInstance(raised[0][1], event_store.ProjectionStale)
        self.assertIsInstance(raised[1][1], event_store.ProjectionStale)
        self.assertEqual(raised[0][1].recorded_in, "state/projection-stale.json")
        self.assertIsInstance(raised[2][1], DerivedViewStale)
        self.assertEqual(raised[2][1].recorded_in, "", "the generic wrapper wrote no marker")
        self.assertEqual(len(self.store.read()), 1, "the projection failures committed one event")

    def test_a_marker_that_cannot_be_written_still_leaves_projection_stale(self):
        """t-434 (critic re-check, spot 3): the projection fails AND the write of its marker fails. A bare
        OSError used to escape a committed event, so `finish` did not see the family and skipped the tail."""
        family = getattr(event_store, "EventCommitted", None)
        self.assertIsNotNone(family, "event_store has no EventCommitted type")
        real = event_store.atomic_json

        def crash(events):
            raise OSError("projection disk failure")
        for label, failure in (("PermissionError", PermissionError(13, "held open by a reader")),
                               ("OSError", OSError(28, "No space left on device"))):
            for replay in (False, True):
                with self.subTest(label, replay=replay):
                    root = self.story(f"QA-marker-{label}-{replay}")
                    store = EventStore(root)
                    if replay:
                        store.commit("a", {}, "k")

                    def refuse(path, value, _failure=failure):
                        if Path(path).name == "projection-stale.json":
                            raise _failure
                        return real(path, value)
                    with patch("event_store.atomic_json", refuse):
                        with self.assertRaises(Exception) as caught:
                            store.commit("a", {}, "k", project=crash)
                    exc = caught.exception
                    self.assertIsInstance(exc, event_store.ProjectionStale, repr(exc))
                    self.assertEqual(exc.recorded_in, "")
                    self.assertIn("nothing on disk records", exc.stale_view)
                    self.assertNotIn("recorded in", str(exc))
                    self.assertTrue(str(exc).startswith("event already committed;" if replay else "event committed;"))
                    self.assertEqual(len(store.read()), 1, "the event is in the log")
                    self.assertFalse((root / "state" / "projection-stale.json").exists())
        # the marker landing: the text is today's, and the type names the file
        with self.assertRaises(family) as caught:
            self.store.commit("a", {}, "k1", project=crash)
        self.assertEqual(caught.exception.recorded_in, "state/projection-stale.json")
        self.assertEqual(str(caught.exception), "event committed; projection stale; recover, do not repeat action")
        self.assertNotIn("nothing on disk", caught.exception.stale_view)

    def test_a_base_exception_in_the_marker_write_is_not_swallowed(self):
        def crash(events):
            raise OSError("projection disk failure")

        def interrupt(path, value):
            raise KeyboardInterrupt()
        with patch("event_store.atomic_json", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.commit("a", {}, "k", project=crash)

    def test_a_conflict_where_nothing_committed_is_not_of_the_family(self):
        family = getattr(event_store, "EventCommitted", None)
        self.assertIsNotNone(family, "event_store has no EventCommitted type")
        self.store.commit("a", {"x": 1}, "k")
        for label, run in (("a stale expected revision", lambda: self.store.commit("a", {}, "new", 0)),
                           ("an idempotency key reused", lambda: self.store.commit("a", {"x": 2}, "k"))):
            with self.subTest(label):
                with self.assertRaises(StateConflict) as caught:
                    run()
                self.assertNotIsInstance(caught.exception, family)
        self.assertNotIsInstance(StateConflict("task has an active state writer"), family)

    def test_an_idempotency_refusal_names_key_fields_and_both_sides(self):
        """CX1-14 (TP2-2406 S3-3): the refusal of a reused key is an `IdempotencyKeyReused` that carries the key and
        the differing fields, names both values (cut at 200 characters), starts with the old sentence and spells no door.
        KILLS: raise the bare `StateConflict` again (the type, `.key` and `.fields` go)."""
        self.store.commit("dispatch", {"id": "d1", "input_hash": "a", "scope": ["TC-1"], "known_paths": {"x": 1, "y": 2}},
                          "dispatch:d1")
        with self.assertRaises(event_store.IdempotencyKeyReused) as caught:
            self.store.commit("dispatch", {"id": "d1", "input_hash": "b", "scope": [], "reason": "why",
                                           "known_paths": {"x": 1, "y": 3}}, "dispatch:d1")
        exc, text = caught.exception, str(caught.exception)
        self.assertIsInstance(exc, StateConflict)
        self.assertEqual((exc.key, sorted(exc.fields)), ("dispatch:d1", ["input_hash", "known_paths", "reason", "scope"]))
        self.assertTrue(text.startswith("idempotency key reused with different inputs"))
        for needle in ("key 'dispatch:d1' already holds a dispatch request that differs in", 'input_hash: committed="a" | now="b"',
                       'scope: committed=["TC-1"] | now=[]', 'reason: committed=<absent> | now="why"',
                       "known_paths: differs in keys ['y']"):
            self.assertIn(needle, text)
        self.assertNotIn("story_step", text)
        self.assertNotIn("materialize", text)
        with self.assertRaises(event_store.IdempotencyKeyReused) as other:
            self.store.commit("decision", {"id": "d1", "input_hash": "a", "scope": ["TC-1"],
                                           "known_paths": {"x": 1, "y": 2}}, "dispatch:d1")
        self.assertIn("type: committed=dispatch | now=decision", str(other.exception))
        # a value AT 200 characters is whole, at 201 it ends in the cut mark; a value that is not JSON is shown, not a TypeError
        self.store.commit("note", {"v": "x" * 198}, "n")       # json.dumps adds the two quotes: 200 characters shown
        for width, whole in ((198, True), (199, False)):
            with self.subTest(width=width):
                with self.assertRaises(event_store.IdempotencyKeyReused) as cut:
                    self.store.commit("note", {"v": "y" * width}, "n")
                shown = str(cut.exception).split("now=")[1]
                self.assertEqual(shown, '"' + "y" * width + '"' if whole else '"' + "y" * 199 + "…")
        with self.assertRaises(event_store.IdempotencyKeyReused) as odd:
            self.store.commit("note", {"v": Path("some-dir")}, "n")
        self.assertIn('now="some-dir"', str(odd.exception))

    def test_a_refusal_raised_by_the_step_is_passed_on_untouched(self):
        def refuses():
            raise DerivedViewStale("my own door, named by the caller")
        store = self._store_with(refuses)
        with self.assertRaises(DerivedViewStale) as caught:
            store.commit("a", {}, "k")
        self.assertEqual(str(caught.exception), "my own door, named by the caller")

    def test_a_deferred_block_runs_the_step_once_after_the_last_commit(self):
        seen = []
        store = self._store_with(lambda: seen.append(len(store.read())))
        with store.deferred_after_commit():
            store.commit("a", {}, "k1")
            store.commit("a", {}, "k2")
            store.recover(lambda events: None)
            self.assertEqual(seen, [])
        self.assertEqual(seen, [2])

    def test_a_deferred_block_without_a_commit_runs_nothing(self):
        seen = []
        store = self._store_with(lambda: seen.append(1))
        with store.deferred_after_commit():
            pass
        self.assertEqual(seen, [])

    def test_a_deferred_block_runs_in_order_and_surfaces_a_failure_of_the_step(self):
        order = []

        def broken():
            order.append("step")
            raise RuntimeError("view exploded")
        store = self._store_with(broken)
        with self.assertRaises(DerivedViewStale):
            with store.deferred_after_commit():
                store.commit("a", {}, "k")
                order.append("caller work")
        self.assertEqual(order, ["caller work", "step"])
        self.assertEqual(len(store.read()), 1)

    def test_a_deferred_block_that_raises_still_runs_the_step_and_keeps_the_error(self):
        seen = []

        def broken():
            seen.append("step")
            raise RuntimeError("view exploded")
        store = self._store_with(broken)
        with self.assertRaises(KeyError):
            with store.deferred_after_commit():
                store.commit("a", {}, "k")
                raise KeyError("the caller's own failure")
        self.assertEqual(seen, ["step"])

    def test_deferred_blocks_nest(self):
        seen = []
        store = self._store_with(lambda: seen.append(1))
        with store.deferred_after_commit():
            with store.deferred_after_commit():
                store.commit("a", {}, "k")
            self.assertEqual(seen, [])
        self.assertEqual(seen, [1])

    def test_the_stores_default_wait_applies_to_commit_and_recover_but_not_to_lock(self):
        release = threading.Event()
        holder = self._hold_lock(release)
        store = EventStore(self.root, wait_seconds=0.3)
        started = time.monotonic()
        with self.assertRaises(StateConflict):
            store.commit("a", {}, "late")
        self.assertGreaterEqual(time.monotonic() - started, 0.3)
        self.assertLess(time.monotonic() - started, 1.3)
        started = time.monotonic()
        with self.assertRaises(StateConflict):
            store.recover(lambda events: None)
        self.assertGreaterEqual(time.monotonic() - started, 0.3)
        started = time.monotonic()
        with self.assertRaises(StateConflict):
            with store.lock():
                pass
        self.assertLess(time.monotonic() - started, 1.0)
        # An explicit value on the call wins over the store's default.
        started = time.monotonic()
        with self.assertRaises(StateConflict):
            store.commit("a", {}, "late", wait_seconds=0)
        self.assertLess(time.monotonic() - started, 1.0)
        release.set()
        holder.join(5)
        self.assertEqual(store.commit("a", {}, "after")["sequence"], 1)

    def test_a_store_defaults_to_no_wait_and_refuses_a_non_finite_one(self):
        self.assertEqual(EventStore(self.root).wait_seconds, 0.0)
        with self.assertRaises(ValueError):
            EventStore(self.root, wait_seconds=float("inf"))

    def test_the_default_stale_marker_is_unchanged_for_every_existing_caller(self):
        """t-040: the marker name became a store keyword. Every caller that names none (the controller, the
        hooks, story_step, stage_done) must keep writing and clearing exactly `projection-stale.json`."""
        self.assertEqual(event_store.STALE_MARKER, "projection-stale.json")
        self.assertEqual(self.store.stale_marker, "projection-stale.json")

        def crash(events):
            raise OSError("projection disk failure")
        with self.assertRaises(event_store.ProjectionStale) as caught:
            self.store.commit("a", {}, "k", project=crash)
        self.assertEqual(sorted(p.name for p in self.store.state.glob("*stale*")), ["projection-stale.json"])
        self.assertEqual(caught.exception.recorded_in, "state/projection-stale.json")
        self.store.recover(lambda events: None)
        self.assertEqual(list(self.store.state.glob("*stale*")), [])

    def test_a_store_with_its_own_stale_marker_writes_and_clears_only_that_one(self):
        """t-040, TP2-2406 S5-4: the manifest's projection shared the controller's marker, so the
        controller's `recover` erased the manifest's only trace without rebuilding the manifest."""
        own = EventStore(self.root, stale_marker="own-projection-stale.json")
        self.store.state.mkdir(parents=True, exist_ok=True)
        (self.store.state / "projection-stale.json").write_text('{"revision": 0}', encoding="utf-8")

        def crash(events):
            raise OSError("projection disk failure")
        with self.assertRaises(event_store.ProjectionStale) as caught:
            own.commit("a", {}, "k", project=crash)
        self.assertEqual(caught.exception.recorded_in, "state/own-projection-stale.json")
        self.assertEqual(sorted(p.name for p in own.state.glob("*stale*")),
                         ["own-projection-stale.json", "projection-stale.json"])
        self.assertEqual(json.loads((own.state / "projection-stale.json").read_text(encoding="utf-8")),
                         {"revision": 0}, "the other projection's marker is not overwritten")
        self.store.recover(lambda events: None)  # what the controller's recover does
        self.assertTrue((own.state / "own-projection-stale.json").exists(),
                        "a recover of another projection must not erase this one's trace")
        self.assertFalse((own.state / "projection-stale.json").exists())
        own.commit("a", {}, "k", project=lambda events: None)  # the reuse path re-projects
        self.assertFalse((own.state / "own-projection-stale.json").exists(), "a replay clears its own marker")
        with self.assertRaises(event_store.ProjectionStale):
            own.commit("a", {}, "k", project=crash)
        own.recover(lambda events: None)
        self.assertEqual(list(own.state.glob("*stale*")), [], "its own recover clears its own marker")

    def test_a_marker_that_cannot_be_written_names_the_stores_own_file(self):
        real = event_store.atomic_json

        def refuse(path, value):
            if Path(path).name == "own-projection-stale.json":
                raise OSError(28, "No space left on device")
            return real(path, value)

        def crash(events):
            raise OSError("projection disk failure")
        own = EventStore(self.root, stale_marker="own-projection-stale.json")
        with patch("event_store.atomic_json", refuse):
            with self.assertRaises(event_store.ProjectionStale) as caught:
                own.commit("a", {}, "k", project=crash)
        self.assertEqual(caught.exception.recorded_in, "")
        self.assertIn("state/own-projection-stale.json could not be written", str(caught.exception))
        self.assertNotIn("state/projection-stale.json", str(caught.exception))

    def test_a_stale_marker_is_a_plain_file_name(self):
        """A marker is unlinked and written under state/: a path, an empty name or a dot would reach
        outside it or name the directory itself."""
        for bad in ("", ".", "..", "sub/marker.json", "../marker.json", None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    EventStore(self.root, stale_marker=bad)

    def test_controller_rejects_early_stage_and_hard_budget_retry(self):
        c = Controller(self.root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "sha1",
                               "known_paths": {"root": str(self.root)}, "idempotency_key": "init"})
        d = {"id": "d1", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
             "input_hash": "h", "known_paths": {}, "budget": {}, "idempotency_key": "d1"}
        with self.assertRaises(StateConflict):
            c.apply("dispatch", d)
        d["stage"] = "S0"
        c.apply("dispatch", d)
        c.apply("checkpoint", {"id": "d1", "status": "blocked", "reason": "INFRA/BUDGET_EXHAUSTED",
                               "checkpoint": {"remaining": ["TC-1"]}, "idempotency_key": "cp"})
        self.assertEqual(c.state()["stages"]["S0"]["status"], "blocked")
        d.update(id="d2", parent_retry="d1", checkpoint={"remaining": ["TC-1"]}, idempotency_key="d2")
        with self.assertRaises(StateConflict):
            c.apply("dispatch", d)


if __name__ == "__main__":
    unittest.main()
