"""Provider-neutral planning and durable execution for environment preparation.

Adapters discover topology and supply argv.  This module decides the minimum action,
captures commands without a shell, and makes an ambiguous job observable rather than
repeatable.  It deliberately contains no Docker, Kubernetes, Vite, or cloud rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import event_store
from event_store import atomic_json, hold_file_lock
from execution_scheduler import _same_process, _started
from profile_contract import validate_runtime_provenance
from hooklib import sorted_paths


class PreparationError(ValueError):
    pass


TERMINAL = {"failed", "ready", "blocked"}
REQUIRED_PROBES = {"process", "base_health", "dependency_path", "authentication", "provenance"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _facts(runtime: dict) -> dict:
    value = runtime.get("compatibility")
    if not isinstance(value, dict):
        raise PreparationError("runtime compatibility facts are required")
    required = {"dependencies", "runtime", "base_image", "build_args", "platform",
                "source_mounts", "startup_command"}
    def known(item: object) -> bool:
        if item is None or (isinstance(item, str) and item.strip().lower() in {"", "unknown"}):
            return False
        if isinstance(item, (list, tuple)):
            return all(known(part) for part in item)
        if isinstance(item, dict):
            return all(known(part) for part in item.values())
        return True
    missing = sorted(key for key in required if not known(value.get(key)))
    if missing:
        raise PreparationError("unknown compatibility facts: " + ", ".join(missing))
    return value


def _observation(runtime: dict, label: str) -> None:
    """When a runtime was observed and by what evidence: the part of its identity every record carries,
    existing or verified-absent alike."""
    if not isinstance(runtime.get("observed_at"), str) or not runtime["observed_at"]:
        raise PreparationError(f"{label} observed_at is required")
    refs = runtime.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref for ref in refs):
        raise PreparationError(f"{label} evidence_refs are required")


def _runtime_identity(runtime: dict, label: str) -> None:
    if (not isinstance(runtime.get("source_revision"), str) or
            runtime["source_revision"].strip().lower() in {"", "unknown"}):
        raise PreparationError(f"{label} source_revision is required")
    _observation(runtime, label)


def _verified_absence(observed: dict, environment_id: str) -> None:
    """The evidence a `create` rests on, bound to THIS environment (I2): the adapter looked, found no
    resources, and said so with a time and references. Anything less is a refusal, never a quiet
    fall-through to an unknown existing runtime."""
    if (observed.get("environment_id") != environment_id or observed.get("absence_verified") is not True
            or observed.get("resources") != []):
        raise PreparationError("create requires environment-bound verified absence evidence: environment_id equal "
                               "to the request's, absence_verified true and resources []")
    _observation(observed, "observed_runtime (verified absence)")


def _plan_create(request: dict, observed: dict, target: dict, environment_id: str) -> dict:
    """The `create` plan of a verified-absent environment: absence evidence for THIS environment, a complete
    target, an authorization that names `create: true` for this environment and revision, and the adapter's
    own `actions.create`. A missing authorization or action blocks; it never borrows another action."""
    _verified_absence(observed, environment_id)
    _facts(target)
    authorization = request.get("authorization") or {}
    if (authorization.get("create") is not True or not authorization.get("ref") or
            authorization.get("environment_id") != environment_id or
            authorization.get("target_source_revision") != target["source_revision"]):
        return {"status": "blocked", "action": "create",
                "reason": "create authorization must be explicit (create: true) and bind environment and target revision"}
    commands = (request.get("actions") or {}).get("create")
    if not isinstance(commands, list) or not commands:
        return {"status": "blocked", "action": "create", "reason": "adapter has no create action"}
    return {"status": "prepared", "action": "create", "commands": commands,
            "reason": "explicitly authorized new environment with verified absence",
            "build_compatible": False, "source_mounted": False, "automatic_rollback": False,
            "observed_fingerprint": _digest(observed), "target_fingerprint": _digest(target)}


def plan_environment(request: dict) -> dict:
    """Return the minimum authorized action from observed and selected runtime facts.

    ``actions`` maps verify/reload/apply/rebuild/create to adapter command arrays.  Topology is an
    adapter-produced result: this code consumes its verdict but never invents a repair.  ``create``
    is planned only for an observed runtime that is exactly ``state: absent`` with verified,
    environment-bound absence evidence, and an authorization that says ``create: true`` (FB-23).
    """
    observed, target = request.get("observed_runtime"), request.get("target_runtime")
    if not isinstance(observed, dict) or not isinstance(target, dict):
        raise PreparationError("observed_runtime and target_runtime objects are required")
    # A stand that does not exist yet has no deployed revision to identify. Only a VERIFIED absence
    # (checked below) skips the identity rule; an unknown EXISTING runtime is still refused here.
    absent = observed.get("state") == "absent"
    if not absent:
        _runtime_identity(observed, "observed_runtime")
    _runtime_identity(target, "target_runtime")
    environment_id = request.get("environment_id")
    if not isinstance(environment_id, str) or not environment_id:
        raise PreparationError("environment_id is required")
    topology = request.get("topology") or {}
    if topology.get("status") != "compatible":
        return {"status": "blocked", "action": None,
                "reason": topology.get("reason") or "selected-revision topology is unresolved"}
    if absent:
        # After the topology check (an incompatible topology blocks before `create`) and before
        # `_facts(observed)` (a runtime that does not exist has no compatibility facts).
        return _plan_create(request, observed, target, environment_id)
    current, wanted = _facts(observed), _facts(target)
    same_build = all(current[key] == wanted[key] for key in
                     ("dependencies", "runtime", "base_image", "build_args", "platform"))
    same_startup = current["startup_command"] == wanted["startup_command"]
    same_mount_configuration = current["source_mounts"] == wanted["source_mounts"]
    source_mounted = bool(current["source_mounts"] and wanted["source_mounts"] and
                          same_mount_configuration)
    deployed = (observed.get("source_revision") == target.get("source_revision") and
                observed.get("provenance_verified") is True and same_build and same_startup and
                same_mount_configuration)
    if deployed:
        action, reason = "verify", "approved revision is already serving"
    elif same_build and same_startup and source_mounted:
        action, reason = "reload", "compatible runtime consumes mounted source"
    elif same_build:
        action, reason = "apply", "build inputs are compatible"
    else:
        action, reason = "rebuild", "one or more build compatibility facts changed"
    if action != "verify":
        authorization = request.get("authorization") or {}
        if (not authorization.get("ref") or authorization.get("environment_id") != environment_id or
                authorization.get("target_source_revision") != target["source_revision"]):
            return {"status": "blocked", "action": action,
                    "reason": "mutation authorization must bind environment and target revision"}
    actions = request.get("actions") or {}
    commands = actions.get(action)
    if action == "verify" and commands:
        return {"status": "blocked", "action": action,
                "reason": "verify runs readiness probes only; preparation commands require authorization"}
    if not isinstance(commands, list) or (action != "verify" and not commands):
        return {"status": "blocked", "action": action, "reason": f"adapter has no {action} action"}
    return {"status": "prepared", "action": action, "reason": reason,
            "commands": commands, "build_compatible": same_build,
            "source_mounted": source_mounted, "automatic_rollback": False,
            "observed_fingerprint": _digest(observed), "target_fingerprint": _digest(target)}


def _validate_step(step: dict, probe: bool = False) -> dict:
    if not isinstance(step, dict) or not isinstance(step.get("argv"), list) or not step["argv"]:
        raise PreparationError("each command requires a non-empty argv array")
    if not all(isinstance(part, str) and part for part in step["argv"]):
        raise PreparationError("argv entries must be non-empty strings")
    executable = Path(step["argv"][0]).stem.lower()
    shell_flags = {"-c", "/c", "-command", "-encodedcommand"}
    if executable in {"sh", "bash", "zsh", "cmd", "powershell", "pwsh"} and any(
            part.lower() in shell_flags for part in step["argv"][1:]):
        raise PreparationError("inline shell command wrappers are forbidden; use adapter argv or a script")
    timeout = step.get("timeout_seconds")
    if probe and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise PreparationError("each probe requires a positive timeout_seconds")
    if not probe and timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise PreparationError("action timeout_seconds must be positive when supplied")
    if probe and step.get("layer") not in REQUIRED_PROBES:
        raise PreparationError("probe layer is invalid")
    codes = step.get("expected_exit_codes", [0])
    if not isinstance(codes, list) or not codes or not all(isinstance(code, int) for code in codes):
        raise PreparationError("expected_exit_codes must be a non-empty integer array")
    return {**step, "expected_exit_codes": codes}


class EnvironmentJobs:
    """One durable record per idempotency key, claimed atomically."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.directory / (_digest(key) + ".json")

    def read(self, key: str) -> dict | None:
        try:
            value = json.loads(self.path(key).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            raise PreparationError(f"corrupt environment job: {exc}") from exc
        return value

    def write(self, job: dict) -> None:
        atomic_json(self.path(job["idempotency_key"]), job)

    def _refresh_projection(self) -> None:
        """Best-effort refresh for the standard <task>/state/environment-jobs location."""
        if self.directory.name != "environment-jobs" or self.directory.parent.name != "state":
            return
        task_root = self.directory.parent.parent
        if not (task_root / "state" / "controller.json").is_file():
            return
        try:
            from controller import Controller
            from event_store import LIFECYCLE_WAIT_SECONDS
            controller = Controller(task_root, wait_seconds=LIFECYCLE_WAIT_SECONDS)
            with controller.store.lock(LIFECYCLE_WAIT_SECONDS):   # waits for a sibling window's commit; busy after 10 s: the marker below
                controller.project(controller.store.read())
            (task_root / "state" / "environment-projection-stale.json").unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            atomic_json(task_root / "state" / "environment-projection-stale.json",
                        {"updated_at": _now(), "error": str(exc)})
            return
        # The projection is current. The dashboard is a view derived from it and is refreshed
        # AFTER the story lock is released (it used to be rendered inside the `with` above, for
        # as long as the render took). This site commits nothing, so the store's own step does
        # not run for it and it is called here. Best-effort like the rest of this method: on a
        # failure `refresh_derived` has already left state/dashboard-deferred.json, and the
        # projection above is not stale, so no environment-projection-stale marker is written.
        try:
            controller.refresh_derived()
        except (OSError, ValueError):
            return

    def transition(self, job: dict, status: str, **changes) -> dict:
        if status not in {"prepared", "running", "stalled", "failed", "ready", "blocked"}:
            raise PreparationError("invalid environment job status")
        old, old_phase = job.get("status"), job.get("phase")
        job = {**job, **changes, "status": status, "updated_at": _now()}
        if old != status:
            job["transitions"] = [*(job.get("transitions") or []),
                                  {"from": old, "to": status, "at": job["updated_at"]}]
        self.write(job)
        if old != status or old_phase != job.get("phase"):
            self._refresh_projection()
        return job

    def claim(self, request: dict, plan: dict) -> tuple[str, dict]:
        """Atomically suppress the same key and every live/unknown job for the environment."""
        with hold_file_lock(self.directory / "claims.lock", event_store.SHORT_RMW_LOCK_WAIT_S,
                            purpose="environment claim", record_holder=True):
            return self._claim_locked(request, plan)

    def _claim_locked(self, request: dict, plan: dict) -> tuple[str, dict]:
        key = request.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise PreparationError("idempotency_key is required")
        digest = _digest(request)
        existing = self.read(key)
        if existing:
            if existing.get("request_digest") != digest:
                raise PreparationError("idempotency_key was used for different preparation inputs")
            return "existing", existing
        environment_id = request["environment_id"]
        for candidate in sorted_paths(self.directory.glob("*.json")):
            try:
                other = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PreparationError(f"cannot prove environment is unowned: {candidate.name}: {exc}") from exc
            owns_environment = (other.get("status") not in TERMINAL or
                                bool(other.get("uncertain_process")))
            if other.get("environment_id") == environment_id and owns_environment:
                return "resource_existing", other
        job = {"schema_version": 1, "job_id": digest[:20], "idempotency_key": key,
               "coordinator_pid": os.getpid(), "coordinator_started_at": _started(os.getpid()),
               "request_digest": digest, "status": "prepared", "phase": "planning",
               "environment_id": environment_id, "action": plan.get("action"),
               "observed_fingerprint": plan.get("observed_fingerprint"),
               "target_fingerprint": plan.get("target_fingerprint"),
               "observation_evidence_refs": request["observed_runtime"].get("evidence_refs", []),
               "target_evidence_refs": request["target_runtime"].get("evidence_refs", []),
               "created_at": _now(), "transitions": [
                   {"from": None, "to": "prepared", "at": _now()}], "steps": []}
        path = self.path(key)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            existing = self.read(key)
            if existing is None or existing.get("request_digest") != digest:
                raise PreparationError("concurrent environment job claim conflict")
            return "existing", existing
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(job, stream, indent=2)
            stream.write("\n")
        self._refresh_projection()
        return "launch", job

    def observe(self, key: str, process_owned: Callable[[int, str], bool] = _same_process) -> dict:
        job = self.read(key)
        if not job:
            raise PreparationError("unknown environment job")
        if job["status"] in TERMINAL:
            return {"action": "reused", "job": job}
        identities = ((job.get("coordinator_pid"), job.get("coordinator_started_at")),
                      (job.get("runner_pid"), job.get("runner_started_at")))
        if any(pid and started and process_owned(int(pid), str(started)) for pid, started in identities):
            return {"action": "observe", "job": job}
        job = self.transition(job, "blocked", phase="recovery",
                              blocker="job outcome is unknown; do not relaunch", uncertain_process=True)
        return {"action": "blocked", "job": job}


def _run_step(store: EnvironmentJobs, job: dict, step: dict, index: int, log_dir: Path,
              overall_deadline: float | None, poll_seconds: float,
              popen_factory=subprocess.Popen) -> tuple[dict, bool]:
    step = _validate_step(step, probe=step.get("kind") == "probe")
    name = str(step.get("name") or f"step-{index + 1}")
    stdout_path, stderr_path = log_dir / f"{index + 1:02d}-{name}.stdout.log", log_dir / f"{index + 1:02d}-{name}.stderr.log"
    started_clock = time.monotonic()
    started_at = _now()
    declared_timeout = step.get("timeout_seconds")
    timeout = float(declared_timeout) if declared_timeout is not None else None
    if overall_deadline is not None:
        remaining = max(0.0, overall_deadline - started_clock)
        timeout = min(timeout, remaining) if timeout is not None else remaining
    if timeout is not None and timeout <= 0:
        return store.transition(job, "blocked", phase="probes", blocker="readiness batch deadline exceeded"), False
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc = popen_factory(step["argv"], cwd=step.get("cwd"), env=step.get("env"), shell=False,
                             stdout=stdout, stderr=stderr)
        birth = _started(proc.pid)
        job = store.transition(job, "running", phase=step.get("kind", "action"), runner_pid=proc.pid,
                               runner_started_at=birth, current_step=name)
        stalled = False
        quiet_limit = float(step.get("stall_after_seconds") or
                            ((timeout + 1) if timeout is not None else 300))
        last_sizes, last_progress = (-1, -1), started_clock
        timed_out = False
        while proc.poll() is None:
            now = time.monotonic()
            sizes = (stdout_path.stat().st_size, stderr_path.stat().st_size)
            if sizes != last_sizes:
                last_sizes, last_progress = sizes, now
                if stalled:
                    job = store.transition(job, "running", last_progress_at=_now())
                    stalled = False
            elif now - last_progress >= quiet_limit and not stalled:
                job = store.transition(job, "stalled", last_progress_at=_now(),
                                       stall_advisory="no output progress; operation remains owned")
                stalled = True
            if timeout is not None and now - started_clock >= timeout:
                proc.kill()
                timed_out = True
                break
            remaining_sleep = (max(0.01, timeout - (now - started_clock))
                               if timeout is not None else poll_seconds)
            time.sleep(min(poll_seconds, remaining_sleep))
        code = proc.wait()
    record = {"name": name, "kind": step.get("kind", "action"), "layer": step.get("layer"),
              "command_id": _digest({"argv": step["argv"], "cwd": step.get("cwd")}),
              "argv": step["argv"], "pid": proc.pid, "process_started_at": birth,
              "started_at": started_at, "ended_at": _now(),
              "elapsed_seconds": round(time.monotonic() - started_clock, 3),
              "exit_code": code, "timed_out": timed_out,
              "stdout_log": str(stdout_path), "stderr_log": str(stderr_path)}
    provenance_ok = True
    if step.get("layer") == "provenance" and not timed_out and code in step["expected_exit_codes"]:
        try:
            receipt = json.loads(stdout_path.read_text(encoding="utf-8"))
            checked = validate_runtime_provenance(receipt)
            provenance_ok = bool(checked["valid"] and checked["result"] == "matched" and
                                 receipt.get("expected_source_revision") ==
                                 step.get("expected_source_revision") and
                                 receipt.get("environment_id") == step.get("environment_id"))
            record["provenance_validation"] = {"valid": provenance_ok,
                                                "result": checked["result"],
                                                "errors": checked["errors"]}
        except (OSError, json.JSONDecodeError, TypeError):
            provenance_ok = False
            record["provenance_validation"] = {"valid": False, "result": "unknown",
                                                "errors": ["stdout is not a provenance receipt"]}
    job["steps"] = [*(job.get("steps") or []), record]
    job["runner_pid"], job["runner_started_at"] = None, None
    store.write(job)
    return job, (not timed_out and code in step["expected_exit_codes"] and provenance_ok)


def read_environment_job(directory: Path, idempotency_key: str) -> dict | None:
    """Read the durable job for controller/dashboard projection without changing it."""
    return EnvironmentJobs(directory).read(idempotency_key)


def environment_job_status(directory: Path, idempotency_key: str,
                           process_owned: Callable[[int, str], bool] = _same_process) -> dict:
    """Return a compact handoff status; this never launches or retries work."""
    job = EnvironmentJobs(directory).read(idempotency_key)
    if not job:
        return {"status": "absent", "active": False, "settled": True}
    active = job.get("status") in {"running", "stalled"}
    identities = ((job.get("coordinator_pid"), job.get("coordinator_started_at")),
                  (job.get("runner_pid"), job.get("runner_started_at")))
    identity_live = any(pid and started and process_owned(int(pid), str(started))
                        for pid, started in identities)
    uncertain = bool(job.get("uncertain_process"))
    return {"job_id": job.get("job_id"), "status": job.get("status"), "phase": job.get("phase"),
            "action": job.get("action"), "active": active, "identity_live": identity_live,
            "uncertain_process": uncertain,
            "settled": job.get("status") in TERMINAL and not uncertain,
            "current_step": job.get("current_step"),
            "updated_at": job.get("updated_at"), "last_step": (job.get("steps") or [None])[-1]}


def execute_environment(request: dict, directory: Path, *, poll_seconds: float = 0.1,
                        popen_factory=subprocess.Popen) -> dict:
    """Plan and synchronously execute one durable environment job.

    Existing jobs are only observed/reused.  A caller that loses this call must invoke
    :meth:`EnvironmentJobs.observe`; it must not call execute again with a new key.
    """
    plan = plan_environment(request)
    store = EnvironmentJobs(directory)
    action, job = store.claim(request, plan)
    if action == "existing":
        return store.observe(request["idempotency_key"])["job"]
    if action == "resource_existing":
        return job
    if plan["status"] == "blocked":
        return store.transition(job, "blocked", phase="planning", blocker=plan["reason"])
    job = store.transition(job, "prepared", phase="planning", coordinator_pid=os.getpid(),
                           coordinator_started_at=_started(os.getpid()))
    probes = request.get("probes") or []
    layers = {probe.get("layer") for probe in probes if isinstance(probe, dict)}
    if len(probes) != len(REQUIRED_PROBES) or layers != REQUIRED_PROBES:
        return store.transition(job, "blocked", phase="planning",
                                blocker="readiness probes must declare exactly one each: " +
                                ", ".join(sorted(REQUIRED_PROBES)), coordinator_pid=None,
                                coordinator_started_at=None)
    provenance = next((probe for probe in probes if probe.get("layer") == "provenance"), {})
    if (provenance.get("expected_source_revision") != request["target_runtime"].get("source_revision") or
            provenance.get("environment_id") != request.get("environment_id")):
        return store.transition(job, "blocked", phase="planning",
                                blocker="provenance probe must bind the exact environment and target revision",
                                coordinator_pid=None, coordinator_started_at=None)
    try:
        commands = [_validate_step(step) for step in plan["commands"]]
        probes = [_validate_step({**step, "kind": "probe"}, probe=True) for step in probes]
    except PreparationError as exc:
        return store.transition(job, "blocked", phase="planning", blocker=str(exc),
                                coordinator_pid=None, coordinator_started_at=None)
    batch = request.get("probe_batch_timeout_seconds")
    if not isinstance(batch, (int, float)) or batch <= 0:
        return store.transition(job, "blocked", phase="planning",
                                blocker="positive probe_batch_timeout_seconds is required",
                                coordinator_pid=None, coordinator_started_at=None)
    log_dir = Path(directory) / "logs" / job["job_id"]
    log_dir.mkdir(parents=True, exist_ok=True)
    for index, step in enumerate(commands):
        job, ok = _run_step(store, job, step, index, log_dir, None, poll_seconds, popen_factory)
        if not ok:
            if job["steps"][-1]["timed_out"]:
                return store.transition(job, "blocked", phase="reconciliation",
                                        blocker="timed-out mutation outcome is unknown; reconcile before reuse",
                                        uncertain_process=True, coordinator_pid=None,
                                        coordinator_started_at=None)
            return store.transition(job, "failed", phase="action",
                                    failure=f"{job['steps'][-1]['name']} failed",
                                    coordinator_pid=None, coordinator_started_at=None)
    deadline = time.monotonic() + float(batch)
    for offset, step in enumerate(probes, len(commands)):
        job, ok = _run_step(store, job, step, offset, log_dir, deadline, poll_seconds, popen_factory)
        if not ok:
            status = "blocked" if job.get("status") == "blocked" else "failed"
            return store.transition(job, status, phase="probes",
                                    failure=f"{job.get('current_step')} did not meet its declared result",
                                    coordinator_pid=None, coordinator_started_at=None)
    return store.transition(job, "ready", phase="complete", completed_at=_now(),
                            coordinator_pid=None, coordinator_started_at=None)


def reconcile_environment(directory: Path, idempotency_key: str, probe: dict,
                          *, process_owned: Callable[[int, str], bool] = _same_process,
                          popen_factory=subprocess.Popen) -> dict:
    """Run one bounded read-only reconciliation probe for an uncertain operation."""
    store = EnvironmentJobs(directory)
    job = store.read(idempotency_key)
    if not job or not job.get("uncertain_process"):
        raise PreparationError("reconciliation requires an uncertain environment job")
    identities = ((job.get("coordinator_pid"), job.get("coordinator_started_at")),
                  (job.get("runner_pid"), job.get("runner_started_at")))
    if any(pid and started and process_owned(int(pid), str(started)) for pid, started in identities):
        raise PreparationError("cannot reconcile while the coordinator or child process is live")
    step = _validate_step(probe)
    if not isinstance(step.get("timeout_seconds"), (int, float)) or step["timeout_seconds"] <= 0:
        raise PreparationError("reconciliation probe requires a positive timeout_seconds")
    log_dir = Path(directory) / "logs" / job["job_id"]
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(len(job.get("steps") or []) + 1)
    stdout_path = log_dir / f"{stamp}-reconcile.stdout.log"
    stderr_path = log_dir / f"{stamp}-reconcile.stderr.log"
    started_at, clock = _now(), time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc = popen_factory(step["argv"], cwd=step.get("cwd"), env=step.get("env"), shell=False,
                             stdout=stdout, stderr=stderr)
        birth = _started(proc.pid)
        job = store.transition(job, "blocked", phase="reconciliation", runner_pid=proc.pid,
                               runner_started_at=birth)
        try:
            code = proc.wait(timeout=float(step["timeout_seconds"]))
            timed_out = False
        except subprocess.TimeoutExpired:
            proc.kill()
            code, timed_out = proc.wait(), True
    receipt, valid = None, False
    if not timed_out and code in step["expected_exit_codes"]:
        try:
            receipt = json.loads(stdout_path.read_text(encoding="utf-8"))
            valid = bool(receipt.get("outcome_known") is True and
                         receipt.get("operation_running") is False and
                         receipt.get("environment_id") == job.get("environment_id"))
        except (OSError, json.JSONDecodeError, AttributeError):
            valid = False
    record = {"name": "reconcile", "kind": "reconciliation", "argv": step["argv"],
              "command_id": _digest({"argv": step["argv"], "cwd": step.get("cwd")}),
              "pid": proc.pid, "process_started_at": birth, "started_at": started_at,
              "ended_at": _now(), "elapsed_seconds": round(time.monotonic() - clock, 3),
              "exit_code": code, "timed_out": timed_out, "stdout_log": str(stdout_path),
              "stderr_log": str(stderr_path), "receipt_digest": _digest(receipt) if receipt else None,
              "valid": valid}
    job["steps"] = [*(job.get("steps") or []), record]
    if valid:
        return store.transition(job, "failed", phase="reconciled", uncertain_process=False,
                                runner_pid=None, runner_started_at=None,
                                failure="prior job lacks a verified success receipt; environment ownership reconciled")
    return store.transition(job, "blocked", phase="reconciliation", uncertain_process=True,
                            runner_pid=None, runner_started_at=None,
                            blocker="reconciliation did not establish a stopped known outcome")


def main() -> None:
    parser = argparse.ArgumentParser(description="plan, start, or observe environment preparation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start"):
        item = sub.add_parser(name)
        item.add_argument("--request", required=True, type=Path)
        if name == "start":
            item.add_argument("--jobs", required=True, type=Path)
    status = sub.add_parser("status")
    status.add_argument("--jobs", required=True, type=Path)
    status.add_argument("--key", required=True)
    # `observe` is the door the module's own docstring names for a caller that lost the
    # execute call ("it must not call execute again with a new key") and the only way an
    # orphaned job stops being a job somebody is waiting for. It had no CLI, so the one
    # caller that meets it - `story_run` on the controller's `observe_environment_job` -
    # could only read `status` and had no move at all (FR-5, FR-42).
    observe = sub.add_parser("observe")
    observe.add_argument("--jobs", required=True, type=Path)
    observe.add_argument("--key", required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--jobs", required=True, type=Path)
    reconcile.add_argument("--key", required=True)
    reconcile.add_argument("--probe", required=True, type=Path)
    args = parser.parse_args()
    if args.command in {"plan", "start"}:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        value = (plan_environment(request) if args.command == "plan" else
                 execute_environment(request, args.jobs))
    elif args.command == "status":
        value = environment_job_status(args.jobs, args.key)
    elif args.command == "observe":
        result = EnvironmentJobs(args.jobs).observe(args.key)
        job = result.get("job") or {}
        # One JSON object on stdout and nothing else: its caller parses it (FR-14). The
        # status is lifted to the top level so the exit-code rule below reads the same
        # field for every subcommand.
        value = {"action": result.get("action"), "status": job.get("status"),
                 "settled": bool(job.get("status") in TERMINAL and not job.get("uncertain_process")),
                 "uncertain_process": bool(job.get("uncertain_process")),
                 "job": job}
    else:
        probe = json.loads(args.probe.read_text(encoding="utf-8"))
        value = reconcile_environment(args.jobs, args.key, probe)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    if value.get("status") in {"failed", "blocked"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
