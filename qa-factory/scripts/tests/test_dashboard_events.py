"""Live projections expose approved cases before automation and exact paused state."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory_dashboard as D
from dashboard_refresh import refresh_project


class DashboardTests(unittest.TestCase):
    def test_gate_a_cases_without_manifest_and_pause_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            qf=root / "qa-factory"
            task=qf / "artifacts/QA-1"
            (task / "work/test-cases").mkdir(parents=True)
            (task / "state").mkdir()
            (qf / "config.json").write_text("{}")
            (task / "pipeline.json").write_text(json.dumps({"gates":{"A":{"decision":"approved"}}}))
            (task / "work/test-cases/TC-001.md").write_text("# TC-001\nRequirements: R-1\n")
            (task / "state/controller.json").write_text(json.dumps({"revision":17,"dispatches":{"d1":{"id":"d1","stage":"S5","status":"blocked","reason":"INFRA/BUDGET_EXHAUSTED"}},"next_action":{"action":"resume_checkpoint"}}))
            (task / "state/execution-jobs").mkdir()
            (task / "state/execution-jobs/job.json").write_text(json.dumps({"job_id":"job-17","status":"running","request":{"purpose":"factory_behavior"}}))
            (task / "state/environment-jobs").mkdir()
            (task / "state/environment-jobs/job.json").write_text(json.dumps({"job_id":"env-17","status":"ready",
                "phase":"complete","current_step":"provenance","elapsed_seconds":12.5,"steps":[{
                    "stdout_log":"state/environment-jobs/logs/env-17/probe.stdout.log",
                    "stderr_log":"state/environment-jobs/logs/env-17/probe.stderr.log"}]}))
            tasks=D.parse_taskruns(root)
            self.assertIn("TC-001",tasks[0]["planned_cases"])
            self.assertTrue(tasks[0]["planned_only"])
            receipt=refresh_project(root)
            html=(qf / "state/factory-dashboard.html").read_text(encoding="utf-8")
            self.assertIn("INFRA/BUDGET_EXHAUSTED",html)
            self.assertIn("resume_checkpoint",html)
            self.assertIn("Task lifecycle",html)
            # "Execution jobs" was removed with the 15045 rework: a job row says the runner
            # was asked to run something, never what it proved.
            self.assertNotIn("Execution jobs",html)
            self.assertIn("Environment preparation jobs",html)
            self.assertIn("env-17",html)
            self.assertIn("exit status does not establish environment, test, or product readiness",html)
            self.assertEqual(receipt["status"],"current")
            stamp=(qf / "state/factory-dashboard.html").stat().st_mtime_ns
            refresh_project(root)
            self.assertEqual(stamp,(qf / "state/factory-dashboard.html").stat().st_mtime_ns)

    def test_partial_price_is_not_a_whole_task_cost(self):
        self.assertEqual(D.task_cost_totals([{"by_task":{"T":{"cost":2}}},{"by_task":{"T":{"cost":None}}}]),{})

    def test_external_unknown_names_consumer_and_is_not_zero(self):
        html=D.tab_cost([{"by_model":{},"orchestrator":{"by_model":{}},"external_calls":[{
            "external_call_id":"x","consumer_agent":"jira-assistant",
            "invocation_method":"testproject1 assistants chat","task":"T","usage_status":"pending"}]}], {})
        self.assertIn("External cost unknown: jira-assistant via testproject1 assistants chat", html)
        self.assertIn("Total is incomplete", html)
        self.assertIn("unknown</td>", html)

    def test_latency_telemetry_is_not_rendered(self):
        # 43 of 76 run blocks on TP1-15045 recorded an end before their start and no
        # dispatch carried a window, so every number the block printed was noise.
        self.assertFalse(hasattr(D, "telemetry_section"))
        self.assertNotIn("Latency telemetry", D.tab_cost([{"by_model":{},"orchestrator":{"by_model":{}}}], {}))


if __name__ == "__main__":
    unittest.main()
