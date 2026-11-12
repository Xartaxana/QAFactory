#!/usr/bin/env python3
"""`stage_done` writes the shared journal AFTER the story's history lock is released (B-318), and the one
retrying replace is public (B-333 part 1).

The `project` closure of a stage transition used to call `log_append.write` while the history store's lock was held:
a second lock (`.journal-writer`) taken inside the first, and a re-read of the journal for the same
`source_event_id` that `log_append.write` already dedupes on under its own lock. Now the closure projects the
pipeline and the controller and nothing else; `_append_journal` runs after `commit` / `recover` returned.

K1  the append runs with the history lock FREE, and exactly one journal line carries the event id.
K2  negative control: the same probe inside the projection finds the lock HELD.
K3  replaying the transition adds no second line; no `source_event_id") == event_id` scan is left in stage_done.
K4  `replace_file` retries WinError 32 on Windows, and raises WinError 2 at once.
E1  an append that fails after the commit is a stderr line; the event stays committed.
E3  no `journal_record` (--no-journal): no append at all.
F6  a failed manifest projection is not healed, and not hidden, by `controller.py --operation recover`
    (B-333 part 2, measured).
"""
import contextlib
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import event_store as ES  # noqa: E402
import hooklib  # noqa: E402
import log_append  # noqa: E402
import runtime_paths as RP  # noqa: E402
import stage_done  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import EventStore, StateConflict  # noqa: E402

import test_controller_rework_scope as SCOPED  # noqa: E402  (managed_task)

STAGE_DONE_SOURCE = (SCRIPTS / "stage_done.py").read_text(encoding="utf-8")


def story(prefix):
    root = temp_project(prefix)
    task = SCOPED.managed_task(root)
    hooklib._PROJECT_ROOT_CACHE = root
    Controller(task).apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                                          "known_paths": {"root": str(task)}, "idempotency_key": "init"})
    return root, task


def journal_lines(root):
    path = RP.configured(root, hooklib.load_config().get("journal_path"), "journal.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_stage_done(no_journal=False):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stage_done.run("QA-1", "S1", "running", "qa-scout", "", no_journal)
    return code, out.getvalue(), err.getvalue()


def lock_probe(task, seen):
    """A wrapper that records whether the story's history lock is free when it is called."""
    def probe(*_args, **_kwargs):
        try:
            with EventStore(task).lock(wait_seconds=0):
                seen.append("free")
        except StateConflict:
            seen.append("held")
    return probe


def case_k1_k2_k3():
    old = hooklib._PROJECT_ROOT_CACHE
    root, task = story("qa-lock-order-")
    try:
        seen = []
        real_write = log_append.write

        def probed_write(records):
            lock_probe(task, seen)()
            return real_write(records)
        with patch.object(log_append, "write", probed_write):
            code, _out, err = run_stage_done()
        lines = journal_lines(root)
        check_eq("K1: the transition committed", code, 0)
        check_eq("K1: the append ran once, with the history lock FREE", seen, ["free"])
        event = EventStore(task).read()[-1]
        check_eq("K1: one journal line carries the event id",
                 [r.get("source_event_id") for r in lines], [event["event_id"]])

        # K2: the same probe placed inside the projection (the old position of the append) finds the lock held.
        held = []
        real_project = Controller.project

        def probed_project(self, events):
            lock_probe(task, held)()
            return real_project(self, events)
        with patch.object(Controller, "project", probed_project):
            Controller(task).recover()
        check_eq("K2: CONTROL - a probe inside the projection finds the history lock HELD", held, ["held"])

        # K3: replaying the same transition recovers the event and adds no second line.
        before = len(EventStore(task).read())
        code, out, _err = run_stage_done()
        check_eq("K3: the same receipt again recovers the existing event, adding none",
                 (code, len(EventStore(task).read())), (0, before))
        check_in("K3: and says so", "recovered existing event", out)
        check_eq("K3: still one journal line for the event", len(journal_lines(root)), 1)
        check("K3: no `source_event_id\") == event_id` scan is left in stage_done.py",
              'get("source_event_id") == event_id' not in STAGE_DONE_SOURCE
              and "source_event_id\") ==" not in STAGE_DONE_SOURCE)
        check("K3: the closure does not call log_append.write (it is `_append_journal`'s)",
              STAGE_DONE_SOURCE.count("log_append.write(") == 2, str(STAGE_DONE_SOURCE.count("log_append.write(")))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def case_e1_e2_e3():
    old = hooklib._PROJECT_ROOT_CACHE
    root, task = story("qa-lock-order-fail-")
    try:
        def exploding(records):
            raise OSError("journal disk full")
        with patch.object(log_append, "write", exploding):
            code, _out, err = run_stage_done()
        check_eq("E1: an append that fails after the commit does not fail the stage", code, 0)
        check_in("E1: it is said on stderr, with the way to write it", "journal line was not written", err)
        check_in("E1: with the cause", "journal disk full", err)
        events = EventStore(task).read()
        check_eq("E1: the event stays committed", [e["type"] for e in events].count("stage_transition"), 1)
        check_eq("E1: and no journal line exists yet", journal_lines(root), [])
        # E2 (residual, stated): the line is missing until the same transition is replayed; never two lines.
        code, _out, _err = run_stage_done()
        check_eq("E2: the replay writes the missing line", (code, len(journal_lines(root))), (0, 1))
        run_stage_done()
        check_eq("E2: and a second replay never writes a second one", len(journal_lines(root)), 1)
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)

    root, task = story("qa-lock-order-nojournal-")
    try:
        calls = []
        with patch.object(log_append, "write", lambda records: calls.append(records)):
            code, _out, _err = run_stage_done(no_journal=True)
        check_eq("E3: no journal_record, no append", (code, calls), (0, []))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def case_k4_replace_file():
    root = temp_project("qa-replace-file-")
    try:
        src, dst = Path(root) / "a.tmp", Path(root) / "a.json"
        src.write_text("new", encoding="utf-8")
        dst.write_text("old", encoding="utf-8")
        real = ES.os.replace
        calls = []

        def flaky(a, b, winerror=32, failures=1):
            calls.append(1)
            if len(calls) <= failures:
                exc = PermissionError(13, "sharing violation")
                exc.winerror = winerror
                raise exc
            return real(a, b)
        with patch.object(ES, "_is_windows", lambda: True), patch.object(ES.time, "sleep", lambda s: None), \
                patch.object(ES.os, "replace", flaky):
            ES.replace_file(src, dst)
        check_eq("K4: a first WinError 32 is retried and the replace succeeds",
                 (len(calls), dst.read_text(encoding="utf-8")), (2, "new"))

        src.write_text("newer", encoding="utf-8")
        calls.clear()
        raised = None
        with patch.object(ES, "_is_windows", lambda: True), patch.object(ES.time, "sleep", lambda s: None), \
                patch.object(ES.os, "replace", lambda a, b: flaky(a, b, winerror=2, failures=99)):
            try:
                ES.replace_file(src, dst)
            except PermissionError as exc:
                raised = exc
        check("K4: WinError 2 is raised at once, one attempt", raised is not None and len(calls) == 1,
              f"raised={raised!r} attempts={len(calls)}")
        calls.clear()
        with patch.object(ES, "_is_windows", lambda: False), patch.object(ES.time, "sleep", lambda s: None), \
                patch.object(ES.os, "replace", lambda a, b: flaky(a, b, failures=99)):
            try:
                ES.replace_file(src, dst)
            except PermissionError:
                pass
        check_eq("K4: CONTROL - off Windows, even WinError 32 is raised at once", len(calls), 1)
        check("K4: `_publish` goes through `replace_file`", "replace_file(tmp, path)" in
              (SCRIPTS / "event_store.py").read_text(encoding="utf-8"))
    finally:
        cleanup(root)


def case_f6_manifest_projection_and_controller_recover():
    """B-333 part (2), measured: a manifest projection that failed after its commit is not rebuilt by
    `controller.py --operation recover` (it projects the controller's state), and the controller's recover must not
    erase the manifest's own marker, so the stale manifest stays visible until `manifest_put.py --recover`."""
    import manifest_put as MP
    old = hooklib._PROJECT_ROOT_CACHE
    root = temp_project("qa-lock-order-manifest-")
    try:
        hooklib._PROJECT_ROOT_CACHE = root
        task = root / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}),
                                            encoding="utf-8")
        Controller(task).apply("initialize", {"scope": ["TC-1"], "source_revision": "r",
                                              "known_paths": {"root": str(task)}, "idempotency_key": "init"})
        manifest = task / "work" / "automation-manifest.json"
        marker = task / "state" / MP.MANIFEST_STALE_MARKER
        fragment = json.dumps({"tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001"}]})
        with patch.object(MP, "_write_projection", side_effect=OSError("manifest disk failure")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = MP.run("QA-1", fragment)
        check_eq("F6: the manifest commit is stale (exit EXIT_COMMITTED_STALE) and its marker is written",
                 (code, marker.exists(), manifest.exists()), (MP.EXIT_COMMITTED_STALE, True, False))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            Controller(task).recover()
        check("F6: controller recover does not claim the manifest current: its marker stands and the projection "
              "is still missing", marker.exists() and not manifest.exists(),
              f"marker={marker.exists()} manifest={manifest.exists()}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = MP.recover("QA-1")
        check_eq("F6: manifest_put --recover is the door: the projection is rebuilt and the marker goes",
                 (code, marker.exists(), manifest.exists()), (0, False, True))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def main():
    case_k1_k2_k3()
    case_e1_e2_e3()
    case_k4_replace_file()
    case_f6_manifest_projection_and_controller_recover()
    finish("test_stage_done_lock_order")


if __name__ == "__main__":
    main()
