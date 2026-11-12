"""V06-V10: command metadata, thresholds, leases, and parallel reduction."""
import json
import os
import sys
import tempfile
from pathlib import Path

from harness import check, check_eq, check_in, finish

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution_fingerprint import file_hash  # noqa: E402
from execution_scheduler import (LeaseRegistry, SchedulerError, execute_schedule,
                                 prepare_schedule)  # noqa: E402
from profile_contract import resolve_level, resolve_profile_command  # noqa: E402


ROOT = Path(tempfile.mkdtemp(prefix="qa-scheduler-"))


def request(instance: str, key: str, resource=None) -> dict:
    execution = {
        "schema_version": 1,
        "reporter": {"format": "junit-xml", "path_template": "{report_path}"},
        "concurrency": {"native_supported": False, "native_worker_argv_template": None,
                        "verified_max_workers": None, "memory_per_worker_mb": None,
                        "isolation": "verified", "evidence_refs": ["decision:parallel"]},
        "resources": [resource] if resource else [],
    }
    return {
        "task": "SCHED-1", "revision": "r1", "dispatch_id": "d1", "profile_id": "p",
        "purpose": "initial", "selected_instance_ids": [instance],
        "current_scope_instance_ids": [instance], "input_fingerprint": "inputs",
        "fingerprint_files": [{"path": str(ROOT / "test.py"),
                               "sha256": file_hash(ROOT / "test.py"), "kind": "test_files"}],
        "fingerprint_components": {"source_sha": "a" * 40, "test_content_sha": "b" * 64,
                                   "config_sha": "c" * 64},
        "runtime_provenance": {"profile_id": "p", "timestamp": "2026-09-18T00:00:00Z",
                               "environment_id": "local", "expected_source_revision": "r1",
                               "evidence_refs": [], "provenance": {}, "result": "not_applicable"},
        "runtime_required": False, "target_kind": "local_source",
        "instance_contracts": {instance: {"report_test_id": f"x::{instance}", "parameters": {}}},
        "reason": "approved current instance", "remaining_budget": 10,
        "idempotency_key": key, "freshness": "fresh", "execution": execution,
        "command": {"argv": [sys.executable, str(ROOT / "test.py"), "{report_path}"],
                    "cwd": ".", "scope": "selected", "reporter": "junit-xml",
                    "report_path": "{report_path}", "selector_contract_verified": True,
                    "selector_args": {instance: [instance]}},
    }


def test_lease_lock_held_past_the_wait_propagates_the_helper_exception_naming_the_holder():
    """TR4-2 C: a registry lock held past the wait is the helper's LockBusy, whole (no SchedulerError conversion), for all
    three registry calls; the wait is the module constant, shortened here so nothing waits 10 s."""
    import event_store as EV
    from event_store import LockBusy, take_file_lock
    root = Path(tempfile.mkdtemp(prefix="qa-scheduler-lock-"))
    registry = LeaseRegistry(root)
    holder = take_file_lock(registry.lock_path, 0, purpose="test holder", record_holder=True)
    saved = EV.SHORT_RMW_LOCK_WAIT_S
    EV.SHORT_RMW_LOCK_WAIT_S = 0.2
    try:
        calls = (lambda: registry.snapshot(),
                 lambda: registry.acquire({"job_id": "j", "workers": 1, "resources": {}}, 1, {}),
                 lambda: registry.release("j", 0, ""))
        for call in calls:
            try:
                call()
                raised = None
            except LockBusy as exc:
                raised = exc
            assert raised is not None, "a held registry lock must refuse, not run unlocked"
            assert "held by process %d" % os.getpid() in str(raised).lower(), str(raised)
            assert raised.path == registry.lock_path and raised.holder.get("pid") == os.getpid()
    finally:
        EV.SHORT_RMW_LOCK_WAIT_S = saved
        holder.release()
    assert registry.snapshot() == {"schema_version": 1, "leases": []}, "free again after the holder let go"


def main() -> None:
    test_lease_lock_held_past_the_wait_propagates_the_helper_exception_naming_the_holder()
    check("a held lease lock is the helper's LockBusy naming the holder (snapshot, acquire, release)", True)
    (ROOT / "qa-factory" / "state").mkdir(parents=True)
    (ROOT / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    (ROOT / "test.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "ids=sys.argv[2:]\n"
        "rows=''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in ids)\n"
        "Path(sys.argv[1]).write_text(f'<testsuite tests=\"{len(ids)}\" failures=\"0\" errors=\"0\" skipped=\"0\">{rows}</testsuite>')\n",
        encoding="utf-8")
    for count, expected in ((7, False), (8, True), (9, True)):
        plan = prepare_schedule({"requests": [request(f"i-{i}", f"k-{count}-{i}")
                                               for i in range(count)], "max_workers": 4}, ROOT)
        check_eq(f"auto parallel threshold {count}", plan["parallel"], expected)
        check(f"worker budget bounded at {count}", plan["worker_budget"] <= 4)

    shared = {"key": "account", "capacity": 1, "units_per_worker": 1,
              "exclusive": False, "evidence_refs": ["account-contract"]}
    plan = prepare_schedule({"requests": [request("a", "a", shared), request("b", "b", shared)]
                             + [request(f"x-{i}", f"x-{i}") for i in range(6)],
                             "max_workers": 4}, ROOT)
    account_group = next(row for row in plan["requests"] if "account" in row["capacities"])
    check_eq("shared account has capacity one", account_group["capacities"]["account"], 1)
    try:
        prepare_schedule({"requests": [request("same", "one"), request("same", "two")]}, ROOT)
        duplicate_refused = False
    except SchedulerError:
        duplicate_refused = True
    check("duplicate instance is refused before launch", duplicate_refused)
    cross_repo = [request("same", "repo-a"), request("same", "repo-b")]
    cross_repo[0]["execution"]["repo_id"] = "repo-a"
    cross_repo[1]["execution"]["repo_id"] = "repo-b"
    check_eq("identical test IDs in different repositories stay distinct",
             len(prepare_schedule({"requests": cross_repo}, ROOT)["selected_ids"]), 2)

    profile = {"extensions": {"execution": {"level_rules": [
        {"repo_id": "r", "patterns": ["tests/**"], "level": "api"},
        {"repo_id": "r", "patterns": ["tests/api/**"], "level": "integration"}]}}}
    first = resolve_level(profile, "r", "tests/api/test_x.py")
    profile["extensions"]["execution"]["level_rules"].reverse()
    second = resolve_level(profile, "r", "tests/api/test_x.py")
    check_eq("overlapping level rules are order-independent ambiguous", first, second)
    check_eq("ambiguous level remains unknown", first["level"], "unknown")
    command_profile = {"commands": {"component": {"repo_id": "frontend",
        "framework_adapter": "junit", "kind": "test", "scope": "selected",
        "cwd": "ui", "argv": ["npm", "test", "--output", "{report_path}"],
        "reporter": {"format": "junit-xml", "path_template": "{report_path}"},
        "selectors": {"test_id": "--test={selector}"}}}}
    (ROOT / "frontend" / "ui").mkdir(parents=True)
    resolved_command = resolve_profile_command(command_profile, "component",
                                               {"frontend": ROOT / "frontend"},
                                               ROOT / "evidence" / "job.xml")
    check("per-command cwd/reporter resolves without pytest flags",
          Path(resolved_command["cwd"]).parts[-2:] == ("frontend", "ui")   # not "frontend\\ui": that is only Windows's spelling (B-301 c)
          and resolved_command["reporter"]["format"] == "junit-xml"
          and not any("pytest" in arg or "--junitxml" in arg for arg in resolved_command["argv"]))

    # Two real scheduler children demonstrate placement rather than helper arithmetic.
    fake_runner = ROOT / "fake_run_suite.py"
    fake_runner.write_text(
        "import json,sys,time\nfrom pathlib import Path\n"
        "r=json.loads(Path(sys.argv[2]).read_text()); key=r['idempotency_key']\n"
        "start=time.time(); time.sleep(0.35); end=time.time()\n"
        "p=Path.cwd()/'traces'; p.mkdir(exist_ok=True); (p/(key+'.json')).write_text(json.dumps({'start':start,'end':end}))\n",
        encoding="utf-8")
    parallel_requests = [request("p-a", "parallel-a"), request("p-b", "parallel-b")]
    execute_schedule({"requests": parallel_requests, "min_selected_instances": 2, "max_workers": 2},
                     ROOT, fake_runner)
    parallel_times = [json.loads((ROOT / "traces" / f"parallel-{name}.json").read_text())
                      for name in ("a", "b")]
    check("two independent subprocess groups overlap within worker capacity",
          max(row["start"] for row in parallel_times) < min(row["end"] for row in parallel_times))

    serial_resource = {"key": "shared-account", "capacity": 1, "units_per_worker": 1,
                       "exclusive": False, "evidence_refs": ["fixture:shared"]}
    shared_requests = [request("s-a", "shared-a", serial_resource),
                       request("s-b", "shared-b", serial_resource)]
    execute_schedule({"requests": shared_requests, "min_selected_instances": 2, "max_workers": 2},
                     ROOT, fake_runner)
    shared_times = [json.loads((ROOT / "traces" / f"shared-{name}.json").read_text())
                    for name in ("a", "b")]
    check("shared capacity one serializes subprocess groups",
          max(row["start"] for row in shared_times) >= min(row["end"] for row in shared_times))

    # TR4-2 C, the run-loop site: the registry cannot be locked AFTER the child began. The child is killed, the group is
    # `failed` with the helper's sentence, and the lease taken for it is released (never a live child under a lease).
    import event_store
    import execution_scheduler as ES
    slow_runner = ROOT / "slow_run_suite.py"
    slow_runner.write_text("import time\nfrom pathlib import Path\nPath('slow-started').write_text('1')\ntime.sleep(60)\n",
                           encoding="utf-8")
    real_locked = ES.LeaseRegistry._locked

    def refusing(self, purpose):
        if purpose == "lease child identity":
            raise event_store.LockBusy(self.lock_path, 0.2, {"pid": 4242, "since": "2026-11-10T00:00:00"})
        return real_locked(self, purpose)
    ES.LeaseRegistry._locked = refusing
    try:
        receipt = execute_schedule({"requests": [request("lk-a", "lock-lost-a")], "min_selected_instances": 2},
                                   ROOT, slow_runner, pipe_grace_s=2.0)
    finally:
        ES.LeaseRegistry._locked = real_locked
    lost = receipt["groups"][0]
    check("TR4-2 C: a registry lock lost after the child began fails the group with the holder sentence",
          lost["status"] == "failed" and "held by process 4242" in lost["error"].lower())
    check("TR4-2 C: the killed child's lease is released and the group is not marked as keeping it",
          "lease_released" not in lost and "lease_error" not in lost and LeaseRegistry(ROOT).snapshot()["leases"] == [])

    # F1 (t-2196): the registry cannot be locked at the NORMAL close of a group. `execute_schedule` returns normally,
    # the group row is kept with `lease_released: false` and the helper's sentence in `lease_error`.
    def refusing_release(self, purpose):
        if purpose == "lease release":
            raise event_store.LockBusy(self.lock_path, 0.2, {"pid": 4343, "since": "2026-11-10T00:00:00"})
        return real_locked(self, purpose)
    ES.LeaseRegistry._locked = refusing_release
    try:
        receipt = execute_schedule({"requests": [request("lr-a", "lock-release-a")], "min_selected_instances": 2},
                                   ROOT, fake_runner)
    finally:
        ES.LeaseRegistry._locked = real_locked
    kept = receipt["groups"][0]
    check("F1: a lock lost at the normal close keeps the group row, with `lease_released: false` and the sentence",
          kept.get("lease_released") is False and "held by process 4343" in kept.get("lease_error", "").lower())
    check("F1: and the receipt is returned (execute_schedule did not raise)", receipt["groups"] and kept["status"] in ("unknown", "completed"))
    event_store.atomic_json(LeaseRegistry(ROOT).path, {"schema_version": 1, "leases": []})   # the leaked lease stays until recover(); cleared for the later checks

    config = json.loads((ROOT / "qa-factory" / "config.json").read_text())
    config["execution"] = {"parallel": {"mode": "serial", "min_selected_instances": 2,
                                         "max_workers": 1}}
    (ROOT / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    configured = prepare_schedule({"requests": [request(f"c-{i}", f"c-{i}") for i in range(8)]}, ROOT)
    check("effective config serial default feeds scheduler", not configured["parallel"]
          and configured["worker_budget"] == 1)
    config["execution"]["parallel"] = {"mode": "auto", "min_selected_instances": 8,
                                        "max_workers": None}
    (ROOT / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")

    # The label of a key that already exists (D-0018): `reused` says a green result stands, so a
    # completed job that ended any other way is `already_run`, and only one still in flight is a
    # `duplicate`. Nothing is launched in any of the three.
    from execution_request import JobStore
    for key, state, outcome, label in (("done-red", "completed", "failed", "already_run"),
                                       ("done-green", "completed", "passed", "reused"),
                                       ("done-broken", "completed", "broken_run", "already_run"),
                                       ("in-flight", "running", None, "duplicate")):
        req = request(f"label-{key}", key)
        JobStore(ROOT / "qa-factory" / "artifacts" / req["task"] / "state" / "execution-jobs").write(
            {"job_id": key, "idempotency_key": key, "request_digest": "x", "status": state,
             "execution_status": outcome, "request": req})
        receipt = execute_schedule({"requests": [req], "min_selected_instances": 2}, ROOT, fake_runner)
        check_eq(f"an existing {key} key is labelled {label}", receipt["groups"][0]["status"], label)
    check("and none of them launched anything", not (ROOT / "traces" / "done-red.json").exists())

    # --- the run budget is applied when the groups are PREPARED (D-0018): a group whose every
    # instance holds a result is not launched, a partly covered one is narrowed, and a child that
    # printed an answer instead of running is that answer's status - never `completed`/`failed`,
    # never the digest of a job nobody began.
    task_dir = ROOT / "qa-factory" / "artifacts" / "SCHED-1"
    job_store = JobStore(task_dir / "state" / "execution-jobs")

    def old_job(instance, job_id, outcome="passed", day="01", rows=None):
        req = request(instance, f"old-{job_id}")
        job = {"job_id": job_id, "idempotency_key": req["idempotency_key"], "request_digest": "x",
               "status": "completed", "execution_status": outcome, "freshness": "fresh",
               "created_at": f"2026-09-{day}T00:00:00+00:00", "updated_at": f"2026-09-{day}T00:00:00+00:00",
               "request": req}
        if rows:
            block = task_dir / "work" / "run-blocks" / f"{job_id}.json"
            block.parent.mkdir(parents=True, exist_ok=True)
            block.write_text(json.dumps({"results": rows}), encoding="utf-8")
            job["run_block"] = f"qa-factory/artifacts/SCHED-1/work/run-blocks/{job_id}.json"
        job_store.write(job)

    spy = ROOT / "spy_runner.py"
    spy.write_text("import shutil,sys\nfrom pathlib import Path\nPath('spy').mkdir(exist_ok=True)\n"
                   "shutil.copy(sys.argv[2], Path('spy') / Path(sys.argv[2]).name)\n", encoding="utf-8")

    old_job("cov-a", "JOB-A")
    receipt = execute_schedule({"requests": [request("cov-a", "new-a")]}, ROOT, spy)
    group = receipt["groups"][0]
    check_eq("B4: a fully covered group is `reused`, with the job that answered it",
             (group["status"], group["job_id"], group["selected_ids"], group["jobs"]),
             ("reused", "JOB-A", ["cov-a"], ["JOB-A"]))
    check("B4: nothing was launched for it (no child, no request file)",
          not (ROOT / "spy").exists() or not list((ROOT / "spy").glob("*.json")))
    for day, job_id in (("01", "JOB-R1"), ("02", "JOB-R2")):
        old_job("cov-r", job_id, "failed", day, [{"instance_id": "cov-r", "status": "failed", "report_matched": True}])
    group = execute_schedule({"requests": [request("cov-r", "new-r")]}, ROOT, spy)["groups"][0]
    check_eq("B4: a red that has had its repeat is `already_run`, by a real job",
             (group["status"], group["job_id"]), ("already_run", "JOB-R2"))

    old_job("cov-b", "JOB-B")
    both = request("cov-b", "new-b")
    both["selected_instance_ids"] = ["cov-b", "run-b"]
    both["current_scope_instance_ids"] = ["cov-b", "run-b"]
    both["command"]["selector_args"]["run-b"] = ["run-b"]
    both["instance_contracts"]["run-b"] = {"report_test_id": "x::run-b", "parameters": {}}
    receipt = execute_schedule({"requests": [both]}, ROOT, spy)
    by_status = {row["status"]: row for row in receipt["groups"]}
    check_eq("B4: a partly covered group is two rows: the covered ones answered, the rest launched",
             sorted(by_status), ["reused", "unknown"])   # the spy child prints nothing: `unknown`, not `completed` (M-4)
    check_eq("B4: the covered instance is recorded with its job id",
             (by_status["reused"]["selected_ids"], by_status["reused"]["job_id"]), (["cov-b"], "JOB-B"))
    launched = by_status["unknown"]
    check_eq("B4: the launched group is narrowed to the instance with no result",
             (launched["selected_ids"], launched["not_run_again"]), (["run-b"], {"cov-b": "JOB-B"}))
    seen = json.loads((ROOT / "spy" / f"{launched['job_id']}.json").read_text(encoding="utf-8"))
    check_eq("B4: and so is the request the child ran",
             (seen["selected_instance_ids"], sorted(seen["command"]["selector_args"]),
              "cov-b" in seen["resolved_argv"], "run-b" in seen["resolved_argv"],
              sorted(seen["instance_contracts"])), (["run-b"], ["run-b"], False, True, ["run-b"]))

    def child(name, body):
        path = ROOT / name
        path.write_text("import json,sys\n" + body, encoding="utf-8")
        return path

    said = execute_schedule({"requests": [request("kid-a", "kid-a")]}, ROOT, child(
        "child_reused.py", "print(json.dumps({'status': 'reused', 'job_id': 'REAL-1', 'jobs': ['REAL-1'],"
                           " 'covered': {'kid-a': 'REAL-1'}}))\n"))["groups"][0]
    check_eq("B4: a child that answered `reused` is a `reused` group with ITS job id",
             (said["status"], said["job_id"], said["covered"]), ("reused", "REAL-1", {"kid-a": "REAL-1"}))
    said = execute_schedule({"requests": [request("kid-b", "kid-b")]}, ROOT, child(
        "child_already.py", "print(json.dumps({'status': 'already_run', 'job_id': 'REAL-2'}))\n"))["groups"][0]
    check_eq("B4: `already_run` likewise", (said["status"], said["job_id"]), ("already_run", "REAL-2"))
    said = execute_schedule({"requests": [request("kid-c", "kid-c")]}, ROOT, child(
        "child_refused.py", "print(json.dumps({'status': 'run_refused', 'error': 'four reruns'}))\nsys.exit(2)\n"))["groups"][0]
    check_eq("B4: a refusing child is `run_refused`, with its words and no job id",
             (said["status"], said["job_id"], said["error"], said["exit_code"]), ("run_refused", None, "four reruns", 2))
    said = execute_schedule({"requests": [request("kid-d", "kid-d")]}, ROOT, fake_runner)["groups"][0]
    check_eq("M-4: a child that exited 0 and printed NOTHING is `unknown`, never `completed`, under the digest of the job it began",
             (said["status"], bool(said["job_id"]), said["exit_code"]), ("unknown", True, 0))
    check_in("M-4: ...and the row says why", "printed no summary", said.get("unknown_reason", ""))
    said = execute_schedule({"requests": [request("kid-e", "kid-e")]}, ROOT, child(
        "child_summary.py", "print(json.dumps({'status': 'ok', 'results': []}))\n"))["groups"][0]
    check_eq("M-4 control: a child that exited 0 and printed a summary is `completed`",
             (said["status"], "unknown_reason" in said), ("completed", False))
    said = execute_schedule({"requests": [request("kid-f", "kid-f")]}, ROOT, child(
        "child_silent_red.py", "sys.exit(3)\n"))["groups"][0]
    check_eq("M-4: a silent child with a non-zero code stays `failed`, with its code",
             (said["status"], said["exit_code"], "unknown_reason" in said), ("failed", 3, False))
    said = execute_schedule({"requests": [request("kid-g", "kid-g")]}, ROOT, child(
        "child_blank.py", "print('   ')\nprint()\n"))["groups"][0]
    check_eq("M-4: blank lines are silence too (nothing a reader could take for a summary)", said["status"], "unknown")
    said = execute_schedule({"requests": [request("kid-h", "kid-h")]}, ROOT, child(
        "child_noise.py", "print('a warning nobody asked for')\nprint('and another')\n"))["groups"][0]
    check_eq("M-4 (t-1057 F1): noise only and exit 0 is `unknown`, never `completed`",
             (said["status"], said["exit_code"], "printed no summary" in said.get("unknown_reason", "")),
             ("unknown", 0, True))
    said = execute_schedule({"requests": [request("kid-i", "kid-i")]}, ROOT, child(
        "child_noise_then_summary.py",
        "print('a warning nobody asked for')\nprint(json.dumps({'status': 'ok', 'results': []}))\nprint()\n"))["groups"][0]
    check_eq("M-4 control: noise, then a JSON summary as the last non-blank line, is `completed`",
             (said["status"], "unknown_reason" in said), ("completed", False))
    said = execute_schedule({"requests": [request("kid-j", "kid-j")]}, ROOT, child(
        "child_traceback.py",
        "print(json.dumps({'status': 'ok'}))\nprint('Traceback (most recent call last):')\n"
        "print('ValueError: nobody caught this')\n"))["groups"][0]
    check_eq("M-4: a traceback after the summary with exit 0 is `unknown` (the LAST line decides)",
             said["status"], "unknown")
    said = execute_schedule({"requests": [request("kid-k", "kid-k")]}, ROOT, child(
        "child_traceback_only.py",
        "print('Traceback (most recent call last):')\nprint('ValueError: nobody caught this')\n"))["groups"][0]
    check_eq("M-4: a traceback and exit 0 is `unknown`", said["status"], "unknown")

    registry = LeaseRegistry(ROOT)
    lease = {"job_id": "live", "workers": 1, "resources": {}, "pid": os.getpid(),
             "process_started_at": __import__("execution_scheduler")._started(os.getpid())}
    check("live lease acquired", registry.acquire(lease, 1, {}))
    check("live child lease is not released", not registry.release("live", os.getpid(),
                                                                   lease["process_started_at"]))
    check_eq("recovery retains live lease", registry.recover()["leases"][0]["recovery_status"], "running")
    finish("test_execution_scheduler")


if __name__ == "__main__":
    main()
