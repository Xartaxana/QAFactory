"""Bounded, durable scheduler for typed QA execution requests.

The scheduler launches only ``run_suite.py --request`` children.  It never retries a job:
the runner's durable idempotency record decides whether a request launches, is reused, or
is already running.  Project-wide worker/resource leases survive coordinator failure.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import event_store
from event_store import LockBroken, LockBusy, atomic_json, hold_file_lock
from execution_request import JobStore, RequestError, request_digest, validate_request


class SchedulerError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _started(pid: int) -> str:
    if os.name == "nt" and pid > 0:
        try:
            import ctypes
            from ctypes import wintypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return ""
            creation, exit_time, kernel, user = (wintypes.FILETIME() for _ in range(4))
            try:
                if not ctypes.windll.kernel32.GetProcessTimes(
                        handle, ctypes.byref(creation), ctypes.byref(exit_time),
                        ctypes.byref(kernel), ctypes.byref(user)):
                    return ""
                value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                return f"winfiletime:{value}"
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return ""
    try:
        import run_suite
        return run_suite.process_started_at(pid)
    except Exception:
        return ""


def _same_process(pid: int, started: str) -> bool:
    if started.startswith("winfiletime:"):
        try:
            import ctypes
            from ctypes import wintypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            exit_code = wintypes.DWORD()
            try:
                alive = (ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                         and exit_code.value == 259)  # STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
            return bool(alive and _started(pid) == started)
        except (AttributeError, OSError, ValueError):
            return False
    try:
        import run_suite
        return run_suite.same_process(pid, started)
    except Exception:
        return False


class LeaseRegistry:
    """Project-level, OS-locked worker/resource registry."""

    def __init__(self, project_root: Path):
        self.path = project_root / "qa-factory" / "state" / "execution-leases.json"
        self.lock_path = self.path.with_suffix(".lock")

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("leases", []), list):
                raise ValueError("object with leases array required")
            return value
        except FileNotFoundError:
            return {"schema_version": 1, "leases": []}
        except (json.JSONDecodeError, ValueError) as exc:
            raise SchedulerError(f"corrupt execution lease registry: {exc}") from exc

    def _locked(self, purpose: str):
        return hold_file_lock(self.lock_path, event_store.SHORT_RMW_LOCK_WAIT_S, purpose=purpose, record_holder=True)

    def snapshot(self) -> dict:
        with self._locked("lease registry read"):
            return self._read()

    def acquire(self, lease: dict, worker_budget: int, capacities: dict[str, int]) -> bool:
        with self._locked("lease acquire"):
            state = self._read()
            if any(row.get("job_id") == lease["job_id"] for row in state["leases"]):
                return False
            used_workers = sum(int(row.get("workers") or 0) for row in state["leases"])
            if used_workers + lease["workers"] > worker_budget:
                return False
            used: dict[str, int] = {}
            for row in state["leases"]:
                for key, units in (row.get("resources") or {}).items():
                    used[key] = used.get(key, 0) + int(units)
            if any(used.get(key, 0) + units > capacities.get(key, 1)
                   for key, units in lease["resources"].items()):
                return False
            state["leases"].append(lease)
            state["updated_at"] = _now()
            atomic_json(self.path, state)
            return True

    def release(self, job_id: str, pid: int, started: str) -> bool:
        """Release only after the exact leased process is verified terminated."""
        if pid and not started:
            return False
        if pid and _same_process(pid, started):
            return False
        with self._locked("lease release"):
            state = self._read()
            before = len(state["leases"])
            state["leases"] = [row for row in state["leases"] if row.get("job_id") != job_id]
            if len(state["leases"]) != before:
                state["updated_at"] = _now()
                atomic_json(self.path, state)
                return True
            return False

    def recover(self) -> dict:
        """Classify leases without freeing live or unverifiable processes."""
        state = self.snapshot()
        rows = []
        for lease in state["leases"]:
            pid, started = int(lease.get("pid") or 0), str(lease.get("process_started_at") or "")
            status = "running" if pid and started and _same_process(pid, started) else "blocked_orphan"
            # Close the acquire/spawn/update race using the runner's independently durable
            # job identity.  An alive exact child is adopted; uncertainty stays blocked.
            if status == "blocked_orphan" and lease.get("task") and lease.get("idempotency_key"):
                store = JobStore(self.path.parents[1] / "artifacts" / str(lease["task"]) /
                                 "state" / "execution-jobs")
                job = store.read(str(lease["idempotency_key"]))
                if job and job.get("status") == "running" and _same_process(
                        int(job.get("runner_pid") or 0), str(job.get("runner_started_at") or "")):
                    status = "recovered_child"
            rows.append({**lease, "recovery_status": status})
        return {"schema_version": 1, "leases": rows}


def _execution(request: dict) -> dict:
    value = request.get("execution") or {}
    return value if isinstance(value, dict) else {}


def _resources(request: dict, workers: int = 1) -> tuple[dict[str, int], dict[str, int], bool]:
    requested, capacities, unknown = {}, {}, False
    for resource in _execution(request).get("resources") or []:
        if not isinstance(resource, dict) or not str(resource.get("key") or ""):
            raise SchedulerError("execution.resources entries require key")
        key = str(resource["key"])
        capacity = resource.get("capacity")
        units = resource.get("units_per_worker", 1)
        evidence = resource.get("evidence_refs")
        if not isinstance(capacity, int) or capacity < 1 or not isinstance(units, int) or units < 1:
            raise SchedulerError(f"resource {key!r} requires positive capacity and units_per_worker")
        if not evidence:
            capacity, unknown = 1, True
        capacities[key] = min(capacities.get(key, capacity), capacity)
        requested[key] = capacity if resource.get("exclusive") else units * workers
    return requested, capacities, unknown


def _workers(request: dict, allow_parallel: bool, available: int) -> tuple[int, str]:
    execution = _execution(request)
    concurrency = execution.get("concurrency") or {}
    if not allow_parallel:
        return 1, "below_threshold"
    if concurrency.get("isolation", "unknown") != "verified":
        return 1, "unknown_isolation"
    if concurrency.get("native_supported") is not True:
        return 1, "unsupported_adapter"
    template = concurrency.get("native_worker_argv_template")
    maximum = concurrency.get("verified_max_workers")
    if (not isinstance(template, list) or not template or
            not isinstance(maximum, int) or maximum < 1):
        return 1, "unsupported_adapter"
    if not any("{workers}" in str(part) for part in template):
        raise SchedulerError("native_worker_argv_template must contain {workers}")
    memory_per_worker = concurrency.get("memory_per_worker_mb")
    if memory_per_worker is not None:
        if not isinstance(memory_per_worker, int) or memory_per_worker < 1:
            raise SchedulerError("memory_per_worker_mb must be null or a positive integer")
        available_mb = _available_memory_mb()
        if available_mb is None:
            return 1, "capacity_limit"
        available = min(available, max(1, available_mb // memory_per_worker))
    workers = max(1, min(available, maximum))
    return workers, "native_parallel" if workers > 1 else "capacity_limit"


def _with_native_workers(argv: list[str], template: list[str], workers: int) -> list[str]:
    rendered = [str(part).replace("{workers}", str(workers)) for part in template]
    for start in range(max(1, len(argv) - len(rendered) + 1)):
        if argv[start:start + len(rendered)] == rendered:
            return list(argv)
    static_flags = [str(part) for part in template if "{workers}" not in str(part) and str(part).startswith("-")]
    if any(flag in argv for flag in static_flags):
        raise SchedulerError("command already contains a conflicting native worker option")
    return list(argv) + rendered


def _project_parallel_defaults(project_root: Path) -> dict:
    try:
        from config_contract import effective_config
        path = project_root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return dict((((effective_config(cfg).get("execution") or {}).get("parallel")) or {}))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"mode": "auto", "min_selected_instances": 8, "max_workers": None}


def _available_memory_mb() -> int | None:
    """Best-effort local capacity probe; unknown capacity never enables extra workers."""
    try:
        if os.name == "nt":
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_extended", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return int(status.avail_phys // (1024 * 1024))
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size // (1024 * 1024))
    except (AttributeError, OSError, ValueError):
        return None


def prepare_schedule(document: dict, project_root: Path) -> dict:
    raw_requests = document.get("requests")
    if not isinstance(raw_requests, list) or not raw_requests:
        raise SchedulerError("schedule requires a non-empty requests array")
    requests = [validate_request(item, project_root) for item in raw_requests]
    qualified_ids = [(str(_execution(req).get("repo_id") or req["command"].get("repo_id")
                          or req["profile_id"]), instance)
                     for req in requests for instance in req["selected_instance_ids"]]
    if len(qualified_ids) != len(set(qualified_ids)):
        raise SchedulerError("the same instance cannot appear in multiple scheduled requests")
    ids = [f"{repo_id}::{instance}" for repo_id, instance in qualified_ids]
    defaults = _project_parallel_defaults(project_root)
    mode = document.get("mode", defaults.get("mode", "auto"))
    if mode not in {"auto", "serial"}:
        raise SchedulerError("mode must be auto or serial")
    cpu = os.cpu_count() or 1
    explicit = document.get("max_workers", defaults.get("max_workers"))
    if explicit is not None and (not isinstance(explicit, int) or explicit < 1):
        raise SchedulerError("max_workers must be null or a positive integer")
    budget = min(explicit, cpu) if explicit is not None else cpu
    threshold = int(document.get("min_selected_instances", defaults.get("min_selected_instances", 8)))
    allow_parallel = mode == "auto" and len(set(ids)) >= threshold
    prepared = []
    for req in requests:
        workers, reason = _workers(req, allow_parallel, budget)
        resources, capacities, unknown_resource = _resources(req, workers)
        if unknown_resource and workers > 1:
            workers, reason = 1, "shared_resource"
            resources, capacities, _ = _resources(req, workers)
        command = dict(req["command"])
        template = ((_execution(req).get("concurrency") or {}).get("native_worker_argv_template") or [])
        if workers > 1:
            command_argv = _with_native_workers(list(req["resolved_argv"]), template, workers)
            req = {**req, "command": command, "resolved_argv": command_argv}
        prepared.append({"request": req, "job_id": request_digest(req)[:20], "workers": workers,
                         "resources": resources, "capacities": capacities, "reason": reason})
    prepared.sort(key=lambda row: (int((_execution(row["request"]).get("order") or 0)),
                                   row["request"]["profile_id"],
                                   row["request"]["selected_instance_ids"][0]))
    return {"requests": prepared, "worker_budget": budget, "parallel": allow_parallel,
            "source_revision": document.get("source_revision"), "selected_ids": sorted(set(ids))}


def _repo_of(req: dict) -> str:
    return str(_execution(req).get("repo_id") or req["command"].get("repo_id") or req["profile_id"])


def _group_row(req: dict, status: str, job_id, selected_ids=None, **extra) -> dict:
    """One group of a receipt. `job_id` is a job that EXISTS (the one that answered, or the one
    this group began) or None - never the digest of a request nothing began."""
    ids = list(req["selected_instance_ids"] if selected_ids is None else selected_ids)
    repo_id = _repo_of(req)
    row = {"job_id": job_id, "status": status, "task": req["task"], "revision": req["revision"],
           "repo_id": repo_id, "profile_id": req["profile_id"],
           "selection_provenance": _execution(req).get("selection"), "selected_ids": ids,
           "qualified_selected_ids": [f"{repo_id}::{value}" for value in ids]}
    row.update(extra)
    return row


def _narrow_request(req: dict, run: list, covered: dict) -> dict:
    """The request of the instances with no result: the covered ones leave the selection, their
    selectors leave the argv (a token another kept instance also uses stays), and the request
    records what was not run again and by which job."""
    selectors = (req.get("command") or {}).get("selector_args") or {}
    gone = ({t for i in covered for t in selectors.get(i, [])}
            - {t for i in run for t in selectors.get(i, [])})
    narrowed = dict(req)
    narrowed["selected_instance_ids"] = list(run)
    narrowed["command"] = dict(req["command"], selector_args={i: selectors[i] for i in run})
    narrowed["instance_contracts"] = {i: c for i, c in (req.get("instance_contracts") or {}).items()
                                      if i in set(run)}
    narrowed["resolved_argv"] = [t for t in req["resolved_argv"] if t not in gone]
    narrowed["not_run_again"] = dict(covered)
    return narrowed


def _apply_budget(pending: list, project_root: Path) -> tuple:
    """The run budget, applied when the groups are prepared (D-0018), so no child is launched to
    be told "already run": `(groups still to launch, rows of the groups it answered)`.

    A group whose every instance holds a result is not launched and is a row of its own
    (`reused` / `already_run`, with the covering job ids); a group partly covered is narrowed to
    the instances with no result and the covered ones get a row of their own; a group the budget
    refuses (the FLAKY cap) is a `run_refused` row. A key that already holds a job is left to the
    existing-key branch of the launch loop, which comes first. No data file: nothing is applied."""
    from execution_request import (load_run_budget, request_verdict, run_block_reader, running_stage,
                                   stand_reset_at)
    policy, _note = load_run_budget()
    if policy is None:
        return pending, []
    reset_at, block_of = stand_reset_at(project_root), run_block_reader(project_root)
    kept, rows = [], []
    for item in pending:
        req = item["request"]
        task_root = project_root / "qa-factory" / "artifacts" / req["task"]
        store = JobStore(task_root / "state" / "execution-jobs")
        if store.read(req["idempotency_key"]):
            kept.append(item)
            continue
        verdict = request_verdict(req, store.jobs(), policy=policy, task_root=task_root,
                                  active_stage=running_stage(task_root), reset_at=reset_at,
                                  block_of=block_of, narrow=True)
        if verdict["action"] == "proceed":
            kept.append(item)
        elif verdict["action"] == "refuse":
            rows.append(_group_row(req, "run_refused", None, error=verdict["message"]))
        else:
            answer = verdict["answer"]
            rows.append(_group_row(req, answer["status"], answer["job_id"], selected_ids=list(answer["covered"]),
                                   jobs=[j.get("job_id") for j in answer["jobs"]], covered=answer["covered"],
                                   words=answer["words"]))
            if verdict["action"] == "narrow":
                narrowed = _narrow_request(req, verdict["run"], answer["covered"])
                kept.append(dict(item, request=narrowed, job_id=request_digest(narrowed)[:20],
                                 not_run_again=answer["covered"]))
    return kept, rows


_CHILD_STATUSES = {"reused", "already_run", "run_refused"}


def _child_answer(stdout: str):
    """The answer a child printed instead of running, when it printed one: its last line, a JSON
    object whose status is `reused`, `already_run` or `run_refused`. A run's own summary has no
    such status, so it is never mistaken for one."""
    found = _last_json_object(stdout)
    return found if found and found.get("status") in _CHILD_STATUSES else None


def _last_json_object(stdout: str):
    """The child's last non-blank stdout line as a dict when it parses as a JSON object, else None. `run_suite`
    ends every outcome of the scheduled path with one such line; a line cut by the tail limit does not parse
    (the safe side)."""
    lines = [ln for ln in str(stdout or "").splitlines() if ln.strip()]
    try:
        found = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _ends_with_summary(stdout: str) -> bool:
    """M-4: anything but a JSON object as the last non-blank line (silence, a warning, a traceback) is no result."""
    return _last_json_object(stdout) is not None


# After a child's exit its pipes may stay open - a grandchild (a browser, a server) inherited them. The group
# waits this long for the end of the stream, then closes with what was read and says so (`output_error`).
PIPE_GRACE_S = 10
# What is kept of a child's stream: the tail only, so a child printing megabytes costs the coordinator none.
# The child's last stdout line is its answer (`_child_answer`), so the tail holds well more than the lines shown.
_TAIL_CHARS = 262144
_READ_CHARS = 65536


class _ChildOutput:
    """Both pipes of ONE child, read while it runs (FB-32), as two facts apart from its exit code.

    A runner that prints more than the pipe buffer blocks on its write until someone reads; a coordinator
    that called `communicate()` only after `poll()` saw the exit waited for an exit that could never come,
    holding the lease. The readers are daemon threads: a stuck child never holds the interpreter's exit. A
    reader that raises is not lost - `error` names it, and the coordinator closes the group."""

    def __init__(self, proc):
        self.error = None            # the exception type of a reader that died
        self.exit_seen_at = None     # when poll first showed the exit while a pipe was still open
        self._tails = {"stdout": "", "stderr": ""}
        self._cut = {"stdout": False, "stderr": False}
        self._threads = [threading.Thread(target=self._pump, args=(name, getattr(proc, name)), daemon=True,
                                          name=f"qa-{name}-{proc.pid}") for name in ("stdout", "stderr")]
        for thread in self._threads:
            thread.start()

    def _pump(self, name: str, stream) -> None:
        try:
            while True:
                chunk = stream.readline(_READ_CHARS)   # bounded: one 2 MiB line is read in pieces
                if not chunk:
                    return
                text = self._tails[name] + chunk
                if len(text) > _TAIL_CHARS:
                    text, self._cut[name] = text[-_TAIL_CHARS:], True
                self._tails[name] = text
        except BaseException as error:  # noqa: BLE001 - reported on the group row, never swallowed
            self.error = type(error).__name__

    def done(self) -> bool:
        return not any(thread.is_alive() for thread in self._threads)

    def text(self, name: str) -> str:
        return self._tails[name]

    def lines(self, name: str, count: int) -> list:
        """The last `count` lines of a stream; a first line the cut tore is marked with `...` in front (FR-41)."""
        rows = self._tails[name].splitlines()
        shown = rows[-count:]
        if self._cut[name] and rows and shown and shown[0] is rows[0]:
            shown[0] = "..." + shown[0]
        return shown


def _drain_child(proc) -> _ChildOutput:
    """Start reading both pipes of `proc` NOW (before the lease is written: the child must never fill a pipe
    while the coordinator holds the file lock)."""
    return _ChildOutput(proc)


def _kill_tree(proc) -> None:
    """`node_ids.kill_tree` - the one copy; imported here, not at the top, like every other use of that module
    (a half-installed tree degrades to killing the child alone)."""
    try:
        import node_ids
    except ImportError:
        proc.kill()
        return
    node_ids.kill_tree(proc)


def _settled(proc, output: _ChildOutput, grace_s: float) -> tuple:
    """(closed, exit code, output_error): is this group's story complete. A group closes when the exit code
    is known AND the streams are drained; a reader failure with a live child kills it (nobody can drain it
    now, and it would wait on a full pipe forever); a pipe held after the exit waits `grace_s` and closes."""
    code = proc.poll()
    if output.error is not None:
        if code is None:
            _kill_tree(proc)
            try:
                code = proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                code = None
        return True, code, output.error
    if code is None:
        return False, None, None
    if output.done():
        return True, code, None
    if output.exit_seen_at is None:
        output.exit_seen_at = time.monotonic()
    if time.monotonic() - output.exit_seen_at < grace_s:
        return False, code, None
    _kill_tree(proc)   # best effort: what still names the dead child (its tree, on Windows)
    return True, code, "pipe held after exit"


def _child_row(item: dict, output: _ChildOutput, code, output_error) -> dict:
    """The group row of a closed child. A reader failure is `failed` whatever the code (the output is not
    known); an answer the child printed instead of running keeps its own status; a child that
    exited 0 and printed nothing is `unknown` (M-4), never `completed`."""
    failed_read = output_error not in (None, "pipe held after exit")
    told = None if failed_read else _child_answer(output.text("stdout"))
    silent = not failed_read and not told and code == 0 and not _ends_with_summary(output.text("stdout"))
    # Exit 0 is not a result (FR-18, I4): a child whose LAST non-blank stdout line is not a JSON object gave no
    # summary and no answer (silence, a warning, a traceback), so nobody can say it ran - `unknown`, the safe side,
    # never `completed` (the metrics read only completed/failed as a run, so an unknown group classifies nothing).
    # A non-zero code stays `failed` whatever it printed.
    status = ("failed" if failed_read else told["status"] if told
              else "unknown" if silent else "completed" if code == 0 else "failed")
    answering = {}
    if told and told["status"] == "run_refused":
        answering = {"error": told.get("error")}
    elif told:
        answering = {"jobs": told.get("jobs"), "covered": told.get("covered")}
    job_id = (told.get("job_id") or None) if told else item["job_id"]
    extra = {"output_error": output_error} if output_error else {}
    if silent:
        extra["unknown_reason"] = ("the child exited 0 and printed no summary (its last non-blank stdout line is not "
                                   "a JSON object), so it is not known that the run happened")
    return _group_row(
        item["request"], status, job_id, exit_code=code, workers=item["workers"],
        resource_keys=sorted(item["resources"]), reason=item["reason"],
        stdout_tail=[] if failed_read else output.lines("stdout", 1) or [],
        stderr_tail=[] if failed_read else output.lines("stderr", 3) or [],
        **({"not_run_again": item["not_run_again"]} if item.get("not_run_again") else {}),
        **answering, **extra)


def _abandon_started_child(registry: "LeaseRegistry", proc, item: dict, output: _ChildOutput, child_started: str,
                           why: Exception, grace_s: float) -> dict:
    """The lease registry could not be locked after the child began: the child is killed and drained, the group is
    `failed` with the lock sentence, and the lease taken for it is released when that can be done (the registry may
    still be locked: then the row says `lease_released: false`, as for a child that keeps its lease)."""
    _kill_tree(proc)
    try:
        code = proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        code = proc.poll()
    deadline = time.monotonic() + grace_s
    while not output.done() and time.monotonic() < deadline:
        time.sleep(0.01)
    row = _group_row(item["request"], "failed", item["job_id"], exit_code=code, workers=item["workers"],
                     resource_keys=sorted(item["resources"]), reason=item["reason"], error=str(why),
                     stdout_tail=[], stderr_tail=[])
    try:
        released = registry.release(item["job_id"], proc.pid, child_started)
    except (LockBusy, LockBroken) as exc:
        released = False
        row["lease_error"] = str(exc)   # the helper's sentence, said on the row, not swallowed
    if not released:
        row["lease_released"] = False
    return row


def execute_schedule(document: dict, project_root: Path, run_suite_path: Path,
                     pipe_grace_s: float = PIPE_GRACE_S) -> dict:
    plan = prepare_schedule(document, project_root)
    registry = LeaseRegistry(project_root)
    state_dir = project_root / "qa-factory" / "state" / "scheduler-requests"
    state_dir.mkdir(parents=True, exist_ok=True)
    groups, answered_rows = _apply_budget(list(plan["requests"]), project_root)
    pending, active, results = groups, [], answered_rows
    while pending or active:
        launched = False
        completed = False
        for item in list(pending):
            req = item["request"]
            task_store = JobStore(project_root / "qa-factory" / "artifacts" / req["task"] / "state" / "execution-jobs")
            existing = task_store.read(req["idempotency_key"])
            if existing:
                # `reused` means a green result stands; a completed job that ended any other
                # way is `already_run` (it ran and is recorded), and only a job still in flight
                # is a `duplicate`. Labelling a red or broken run `reused` told a reader that
                # something passed (D-0018; the scheduler's own reading of it was too wide).
                done = existing.get("status") == "completed"
                results.append(_group_row(req, ("reused" if done and existing.get("execution_status") == "passed"
                                                else "already_run" if done else "duplicate"),
                                          existing.get("job_id", item["job_id"])))
                pending.remove(item)
                continue
            lease = {"job_id": item["job_id"], "idempotency_key": req["idempotency_key"],
                     "task": req["task"],
                     "workers": item["workers"], "resources": item["resources"],
                     "selected_ids": req["selected_instance_ids"], "acquired_at": _now(),
                     "pid": os.getpid(), "process_started_at": _started(os.getpid())}
            capacities = dict(item["capacities"])
            if not registry.acquire(lease, plan["worker_budget"], capacities):
                continue
            request_path = state_dir / f"{item['job_id']}.json"
            atomic_json(request_path, req)
            child_env = dict(os.environ)
            child_env["CLAUDE_PROJECT_DIR"] = str(project_root)
            proc = subprocess.Popen([sys.executable, str(run_suite_path), "--request", str(request_path)],
                                    cwd=str(project_root), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    env=child_env)
            output = _drain_child(proc)
            # Lease the child runner identity; a dead coordinator must not free a live child.
            child_started = _started(proc.pid)
            try:
                with registry._locked("lease child identity"):
                    state = registry._read()
                    for row in state["leases"]:
                        if row.get("job_id") == item["job_id"]:
                            row["pid"], row["process_started_at"] = proc.pid, child_started
                    atomic_json(registry.path, state)
            except (LockBusy, LockBroken) as exc:
                # The child is ALREADY running under a lease that still names this coordinator: never leave it
                # alive there. Kill and drain it, say why on its group row, free the lease we took, go on.
                results.append(_abandon_started_child(registry, proc, item, output, child_started, exc,
                                                      pipe_grace_s))
                pending.remove(item)
                completed = True
                continue
            active.append((proc, item, child_started, output))
            pending.remove(item)
            launched = True
            if not plan["parallel"]:
                break
        for entry in list(active):
            proc, item, child_started, output = entry
            closed, code, output_error = _settled(proc, output, pipe_grace_s)
            if not closed:
                continue
            # A child that printed an answer instead of running (`reused`, `already_run`, `run_refused`) is
            # that group's own status, with the job that answered it; only a child that ran is `completed`
            # or `failed`. The lease is released whatever happens while the row is built.
            lease_error = None
            try:
                row = _child_row(item, output, code, output_error)
            finally:
                try:
                    released = registry.release(item["job_id"], proc.pid, child_started)
                except (LockBusy, LockBroken) as exc:
                    # The registry could not be locked: the group row is kept and says so; the receipt and the
                    # other children's coordination go on (a lease never released stays until recover()).
                    released, lease_error = False, str(exc)
            if not released:
                row["lease_released"] = False   # a live or unverifiable child keeps its lease: said, not hidden
            if lease_error:
                row["lease_error"] = lease_error
            results.append(row)
            active.remove(entry)
            completed = True
        if pending and not active and not launched and not completed:
            # Capacity is held by a recovered live/unverifiable lease.  Waiting cannot
            # establish ownership and must never turn into an implicit relaunch.
            recovered = registry.recover()["leases"]
            for item in pending:
                results.append({"job_id": item["job_id"], "status": "blocked_lease",
                                "selected_ids": item["request"]["selected_instance_ids"],
                                "workers": item["workers"], "resource_keys": sorted(item["resources"]),
                                "reason": "capacity_limit", "recovery": recovered})
            pending.clear()
        if (pending or active) and not launched:
            time.sleep(0.05)
    receipt = {"schema_version": 1, "created_at": _now(), "selected_ids": plan["selected_ids"],
               "worker_budget": plan["worker_budget"], "parallel": plan["parallel"],
               "groups": results, "source_revision": plan["source_revision"]}
    receipt_path = project_root / "qa-factory" / "state" / "scheduler-receipts" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    atomic_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path.relative_to(project_root)).replace("\\", "/")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded typed execution requests")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--recover-leases", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    try:
        if args.recover_leases:
            result = LeaseRegistry(root).recover()
        elif args.schedule:
            document = json.loads(args.schedule.read_text(encoding="utf-8"))
            result = execute_schedule(document, root, Path(__file__).with_name("run_suite.py"))
        else:
            parser.error("--schedule or --recover-leases is required")
    except (OSError, json.JSONDecodeError, RequestError, SchedulerError) as exc:
        print(json.dumps({"status": "invalid_schedule", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
