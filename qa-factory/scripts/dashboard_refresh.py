"""Coalesced code-only dashboard projection. Never invokes a model or test runner."""
import contextlib
import io
import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from event_store import EventStore, StateConflict, atomic_json, content_hash
from hooklib import sorted_paths


def refresh_project(project):
    # The ONE chokepoint every dashboard-refresh path goes through: cost_capture.py's
    # PostToolUse/Stop hook used to call this unconditionally and bypass run_suite.py's own
    # QA_FACTORY_SKIP_DASHBOARD_REFRESH check, so a red probe still triggered a full
    # factory_dashboard.py render — and rewrote the tracked factory-dashboard.html's
    # timestamp bytes — on every capture during the probe. Checking the flag here, once,
    # covers every caller (cost_capture, validate_artifacts, project_decisions,
    # environment_preparation, controller.refresh_for_task, bug_snapshot) without asking each
    # of them to remember it.
    if os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH") == "1":
        return {"status": "skipped", "reason": "QA_FACTORY_SKIP_DASHBOARD_REFRESH=1"}
    project = Path(project).resolve()
    if not (project / "qa-factory/config.json").is_file():
        return {"status": "not_configured"}
    from hooklib import artifact_root
    cfg = json.loads((project / "qa-factory/config.json").read_text(encoding="utf-8-sig"))
    roots = [project / "qa-factory", artifact_root(root=project)]
    if cfg.get("cases_root"):
        roots.append((project / cfg["cases_root"]).resolve())
    output = project / "qa-factory/state/dashboard-refresh.json"
    def signature_now():
        inputs, seen = [], set()
        for root in roots:
            if root.exists():
                for path in sorted_paths(root.rglob("*")):
                    # `seen` answers "the same FILE reached through two overlapping roots": the filesystem's
                    # own equality (folded on Windows), not a name lookup, so the key is `normcase` (t-911)
                    key = os.path.normcase(str(path))
                    if not path.is_file() or key in seen or path == output or path.name in {"metrics.json", "dashboard-dirty.json", "metrics-history.json", "metric-signals.json"} or path.suffix not in (".json", ".md", ".jsonl"):
                        continue
                    if any(p in path.parts for p in ("evidence", ".dashboard-writer", "config-migrations")) or path.name == "events.lock":
                        continue
                    seen.add(key)
                    inputs.append((str(path), hashlib.sha256(path.read_bytes()).hexdigest()))
        return content_hash([inputs, datetime.now(timezone.utc).date().isoformat()])
    signature = signature_now()
    try:
        previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    except ValueError:
        previous = {}
    if previous.get("input_hash") == signature and previous.get("status") == "current" and (output.parent / "factory-dashboard.html").exists():
        return previous
    dirty = output.with_name('dashboard-dirty.json')
    atomic_json(dirty, {'input_hash':signature})
    try:
        import factory_dashboard
        with EventStore(project / "qa-factory/state/.dashboard-writer").lock():
            for _ in range(3):
                signature = signature_now()
                with contextlib.redirect_stdout(io.StringIO()):
                    factory_dashboard.main(["--root", str(project)])
                if signature_now() == signature:
                    receipt = {"status":"current", "input_hash":signature, "generated_at":datetime.now(timezone.utc).isoformat()}
                    atomic_json(output, receipt)
                    # Leave a concurrent dirty marker harmlessly present: input hashes,
                    # not marker deletion, decide whether another render is required.
                    return receipt
            receipt = {'status':'pending','input_hash':signature,'reason':'Inputs changed during rendering; refresh on the next lifecycle event or doctor'}
            atomic_json(output, receipt)
            return receipt
    except StateConflict:
        return {'status':'pending','reason':'Another projection writer is active; change coalesced','input_hash':signature}
    except Exception as exc:
        atomic_json(output, {"status": "stale", "error": str(exc), "input_hash": signature})
        raise


def refresh_for_task(task_root):
    task = Path(task_root).resolve()
    controller = task / "state/controller.json"
    if controller.exists():
        state = json.loads(controller.read_text(encoding="utf-8"))
        stored = state.get("known_paths") if isinstance(state, dict) else None
        # t-304 N1 (reader #2): the project_root the state stored at `initialize` is only a HINT. A story copied to
        # another worktree kept the old root, and refreshing "the stored project" rendered the dashboard of - and wrote
        # into - the OTHER project (the old copy is still on disk). `project_for_task` finds the project the story is in
        # and adopts the hint only when that project's artifact root contains the story.
        from runtime_paths import project_for_task
        try:
            project = project_for_task(task, hint=stored.get("project_root") if isinstance(stored, dict) else None)
        except ValueError:
            project = None          # no project holds the story: the ancestor walk below, then `not_configured`
        if project is not None:
            return refresh_project(project)
    # the fallback starts ABOVE the task (a marker at the task itself is not taken); a drive-root task has no parent
    from runtime_paths import nearest_project
    ancestor = None if task.parent == task else nearest_project(task.parent)
    if ancestor is not None:
        return refresh_project(ancestor)
    return {"status": "not_configured"}
