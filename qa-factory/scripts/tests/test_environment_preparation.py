"""Provider-neutral environment preparation acceptance checks."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from environment_preparation import (EnvironmentJobs, environment_job_status,
                                     execute_environment, plan_environment,
                                     reconcile_environment)


def runtime(revision="new", dependencies="d1", mounted=True, verified=False):
    return {"source_revision": revision, "provenance_verified": verified,
            "observed_at": "2026-09-19T10:00:00Z", "evidence_refs": [f"runtime/{revision}.json"],
            "compatibility": {
        "dependencies": dependencies, "runtime": "python-3.12", "base_image": "base@sha",
        "build_args": "args", "platform": "linux/amd64", "source_mounts": ["src"] if mounted else [],
        "startup_command": ["serve"]}}


def step(name, code=0, layer=None, timeout=5):
    output = name
    if layer == "provenance":
        output = json.dumps({"profile_id": "web", "timestamp": "2026-09-19T10:01:00Z",
            "environment_id": "qa", "expected_source_revision": "new",
            "observed_runtime_identity": "build-new", "evidence_refs": ["probe/runtime.json"],
            "result": "matched", "provenance": {"technical_verification": True,
                "source_linkage": "exact", "deployed_source_revision": "new"}})
    value = {"name": name, "argv": [sys.executable, "-c", f"import sys; print({output!r}); sys.exit({code})"],
             "timeout_seconds": timeout}
    if layer:
        value["layer"] = layer
    return value


def request(root, *, failure=False, current=None, target=None):
    probes = [step(layer, layer=layer) for layer in
              ("process", "base_health", "dependency_path", "authentication", "provenance")]
    target_runtime = target or runtime("new")
    probes[-1]["expected_source_revision"] = target_runtime["source_revision"]
    probes[-1]["environment_id"] = "qa"
    return {"idempotency_key": "env-1", "environment_id": "qa",
            "authorization": {"ref": "gate-a-1", "environment_id": "qa",
                              "target_source_revision": target_runtime["source_revision"]},
            "observed_runtime": current or runtime("old"),
            "target_runtime": target_runtime, "topology": {"status": "compatible"},
            "actions": {"verify": [], "reload": [step("reload", 7 if failure else 0)],
                        "apply": [step("apply")], "rebuild": [step("rebuild")]},
            "probes": probes, "probe_batch_timeout_seconds": 20}


class PlanningTests(unittest.TestCase):
    def test_mounted_source_and_same_build_avoids_rebuild(self):
        plan = plan_environment(request(Path(".")))
        self.assertEqual(plan["action"], "reload")
        self.assertTrue(plan["build_compatible"])

    def test_changed_dependency_rebuilds(self):
        req = request(Path("."), target=runtime("new", dependencies="d2"))
        self.assertEqual(plan_environment(req)["action"], "rebuild")

    def test_already_deployed_only_verifies_and_never_rolls_back(self):
        req = request(Path("."), current=runtime("new", verified=True))
        plan = plan_environment(req)
        self.assertEqual(plan["action"], "verify")
        self.assertEqual(plan["commands"], [])
        self.assertFalse(plan["automatic_rollback"])

    def test_bad_topology_blocks_without_generic_repair(self):
        req = request(Path(".")); req["topology"] = {"status": "incompatible", "reason": "proxy target is local"}
        self.assertEqual(plan_environment(req)["status"], "blocked")

    def test_plan_exposes_full_observation_fingerprints(self):
        plan = plan_environment(request(Path(".")))
        self.assertEqual(len(plan["observed_fingerprint"]), 64)
        self.assertNotEqual(plan["observed_fingerprint"], plan["target_fingerprint"])

    def test_unknown_compatibility_never_selects_rebuild(self):
        req = request(Path(".")); req["observed_runtime"]["compatibility"]["dependencies"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unknown compatibility facts"):
            plan_environment(req)


class ExecutionTests(unittest.TestCase):
    def test_inline_shell_pipeline_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td)); req["actions"]["reload"] = [{"name": "bad",
                "argv": ["bash", "-c", "build | tail"], "timeout_seconds": 5}]
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "blocked")
            self.assertIn("shell command wrappers", job["blocker"])

    def test_invalid_request_does_not_leave_prepared_job(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td)); req["actions"]["reload"] = [{"name": "bad", "argv": []}]
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "blocked")

    def test_corrupt_prior_job_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "corrupt.json").write_text("{")
            with self.assertRaisesRegex(ValueError, "cannot prove environment is unowned"):
                execute_environment(request(Path(td)), Path(td), poll_seconds=.01)

    def test_nonzero_action_stops_before_probes_and_preserves_logs(self):
        with tempfile.TemporaryDirectory() as td:
            job = execute_environment(request(Path(td), failure=True), Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(len(job["steps"]), 1)
            self.assertEqual(job["steps"][0]["exit_code"], 7)
            self.assertIn("reload", Path(job["steps"][0]["stdout_log"]).read_text())

    def test_all_probe_layers_must_pass(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td)); req["probes"][2] = step("dependency_path", 4, "dependency_path")
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["steps"][-1]["layer"], "dependency_path")
            self.assertFalse(any(row.get("layer") == "authentication" for row in job["steps"]))

    def test_resume_observes_live_identity_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); req = request(Path(td)); plan = plan_environment(req)
            _, job = store.claim(req, plan)
            job = store.transition(job, "running", runner_pid=42, runner_started_at="birth")
            seen = store.observe("env-1", lambda pid, birth: (pid, birth) == (42, "birth"))
            self.assertEqual(seen["action"], "observe")
            self.assertEqual(len(seen["job"]["transitions"]), 2)

    def test_unknown_outcome_blocks_instead_of_relaunch(self):
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); req = request(Path(td)); _, job = store.claim(req, plan_environment(req))
            job = store.transition(job, "running", runner_pid=42, runner_started_at="birth")
            seen = store.observe("env-1", lambda _pid, _birth: False)
            self.assertEqual(seen["job"]["status"], "blocked")
            self.assertIn("do not relaunch", seen["job"]["blocker"])
            status = environment_job_status(Path(td), "env-1", lambda _pid, _birth: False)
            self.assertTrue(status["uncertain_process"])
            self.assertFalse(status["settled"])

    def test_status_is_read_only_and_reports_identity(self):
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); req = request(Path(td)); _, job = store.claim(req, plan_environment(req))
            store.transition(job, "running", phase="action", runner_pid=7, runner_started_at="born")
            status = environment_job_status(Path(td), "env-1", lambda pid, birth: (pid, birth) == (7, "born"))
            self.assertTrue(status["active"])
            self.assertTrue(status["identity_live"])
            self.assertFalse(status["settled"])

    def test_hanging_probe_is_bounded_and_owned(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td))
            req["probes"][0] = {"name": "process", "layer": "process",
                "argv": [sys.executable, "-c", "import time; time.sleep(10)"],
                "timeout_seconds": .15}
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "failed")
            self.assertTrue(job["steps"][-1]["timed_out"])
            self.assertLess(job["steps"][-1]["elapsed_seconds"], 2)

    def test_provenance_probe_must_bind_exact_target(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td)); req["probes"][-1]["expected_source_revision"] = "other"
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "blocked")
            self.assertEqual(job["steps"], [])

    def test_different_key_cannot_duplicate_live_environment(self):
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); first = request(Path(td)); _, job = store.claim(first, plan_environment(first))
            store.transition(job, "running", runner_pid=7, runner_started_at="born")
            second = request(Path(td)); second["idempotency_key"] = "env-2"
            returned = execute_environment(second, Path(td), poll_seconds=.01)
            self.assertEqual(returned["idempotency_key"], "env-1")

    def test_uncertain_blocked_job_still_owns_environment(self):
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); first = request(Path(td)); _, job = store.claim(first, plan_environment(first))
            store.transition(job, "running", runner_pid=7, runner_started_at="born")
            store.observe("env-1", lambda _pid, _birth: False)
            second = request(Path(td)); second["idempotency_key"] = "env-2"
            returned = execute_environment(second, Path(td), poll_seconds=.01)
            self.assertEqual(returned["idempotency_key"], "env-1")
            self.assertTrue(returned["uncertain_process"])

    def test_duplicate_probe_layer_blocks_before_action(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td)); req["probes"].append(step("process-2", layer="process"))
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "blocked")
            self.assertEqual(job["steps"], [])

    def test_zero_exit_with_wrong_provenance_receipt_fails(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td))
            wrong = {"profile_id": "web", "timestamp": "2026-09-19T10:01:00Z",
                "environment_id": "qa", "expected_source_revision": "newsha",
                "observed_runtime_identity": "old", "evidence_refs": ["probe/old.json"],
                "result": "matched", "provenance": {"technical_verification": True,
                    "source_linkage": "exact", "deployed_source_revision": "oldsha"}}
            req["probes"][-1]["argv"] = [sys.executable, "-c", f"print({json.dumps(wrong)!r})"]
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "failed")
            self.assertFalse(job["steps"][-1]["provenance_validation"]["valid"])

    def test_timed_out_mutation_requires_bounded_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            req = request(Path(td)); req["actions"]["reload"] = [{"name": "slow",
                "argv": [sys.executable, "-c", "import time; time.sleep(10)"],
                "timeout_seconds": .1}]
            job = execute_environment(req, Path(td), poll_seconds=.01)
            self.assertEqual(job["status"], "blocked")
            self.assertTrue(job["uncertain_process"])
            receipt = json.dumps({"outcome_known": True, "operation_running": False,
                                  "environment_id": "qa"})
            probe = {"argv": [sys.executable, "-c", f"print({receipt!r})"],
                     "timeout_seconds": 2}
            reconciled = reconcile_environment(Path(td), "env-1", probe,
                                               process_owned=lambda _pid, _birth: False)
            self.assertEqual(reconciled["status"], "failed")
            self.assertFalse(reconciled["uncertain_process"])
            self.assertEqual(len(reconciled["steps"][-1]["receipt_digest"]), 64)

    def test_live_coordinator_prevents_false_unknown_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); req = request(Path(td)); _, job = store.claim(req, plan_environment(req))
            job = store.transition(job, "prepared", coordinator_pid=11,
                                   coordinator_started_at="coordinator")
            observed = store.observe("env-1", lambda pid, birth: (pid, birth) == (11, "coordinator"))
            self.assertEqual(observed["action"], "observe")

    def test_claim_honours_the_event_store_wait_constant(self):
        """TR4-2 C F2: the claim reads `event_store.SHORT_RMW_LOCK_WAIT_S` at call time, so one patch of that attribute
        shortens it (a claim lock held by another process refuses with the helper's sentence after 0.2 s, not 10 s)."""
        import time
        import event_store
        with tempfile.TemporaryDirectory() as td:
            store = EnvironmentJobs(Path(td)); req = request(Path(td))
            holder = event_store.take_file_lock(store.directory / "claims.lock", 0, purpose="test holder",
                                                record_holder=True)
            saved = event_store.SHORT_RMW_LOCK_WAIT_S
            event_store.SHORT_RMW_LOCK_WAIT_S = 0.2
            started = time.monotonic()
            try:
                with self.assertRaises(event_store.LockBusy) as raised:
                    store.claim(req, plan_environment(req))
            finally:
                event_store.SHORT_RMW_LOCK_WAIT_S = saved
                holder.release()
            self.assertLess(time.monotonic() - started, 5)
            self.assertIn("claims.lock", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
