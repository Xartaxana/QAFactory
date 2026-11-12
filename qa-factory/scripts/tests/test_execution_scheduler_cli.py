"""Supported run_suite scheduler path and durable reuse integration."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_execution_scheduler as fixture  # noqa: E402
from execution_scheduler import execute_schedule  # noqa: E402


def main() -> int:
    fixture.ROOT.joinpath("qa-factory/state").mkdir(parents=True, exist_ok=True)
    fixture.ROOT.joinpath("qa-factory/config.json").write_text("{}", encoding="utf-8")
    fixture.ROOT.joinpath("test.py").write_text(
        "from pathlib import Path\nimport sys\nids=sys.argv[2:]\n"
        "rows=''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in ids)\n"
        "Path(sys.argv[1]).write_text(f'<testsuite tests=\"{len(ids)}\" failures=\"0\" errors=\"0\" skipped=\"0\">{rows}</testsuite>')\n",
        encoding="utf-8")
    request = fixture.request("launched", "launch-once")
    # the request's story must exist: `run_suite.py --request` refuses a task that names no story folder (CX1-18)
    fixture.ROOT.joinpath("qa-factory", "artifacts", request["task"]).mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).resolve().parents[1] / "run_suite.py"
    first = execute_schedule({"requests": [request], "source_revision": "r1"}, fixture.ROOT, runner)
    second = execute_schedule({"requests": [request], "source_revision": "r1"}, fixture.ROOT, runner)
    ok = first["groups"][0]["status"] == "completed" and second["groups"][0]["status"] == "reused"
    print(("PASS" if ok else "FAIL") + " run_suite schedule launches once and durably reuses")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
