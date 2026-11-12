import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import delivery_manifest as D  # noqa: E402
import render_case_appendix as A  # noqa: E402
import check_delivery as C  # noqa: E402
import json


def main() -> None:
    failures = []
    def check(name, ok):
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            failures.append(name)
    with tempfile.TemporaryDirectory(prefix="qa-delivery-visibility-") as td:
        task = Path(td) / "QA-1"
        cases = task / "work" / "test-cases" / "checkout"
        cases.mkdir(parents=True)
        case = cases / "TC-002.md"
        case.write_text("---\nid: TC-002\nplan_row: TS-2\nbasis: requirement:R-2\nchannel: auto\nstatus: Approved\n---\n", encoding="utf-8")
        (cases / "TC-001.md").write_text("---\nid: TC-001\nplan_row: TS-1\nbasis: requirement:R-1\nchannel: manual-human\nstatus: Review\n---\n", encoding="utf-8")
        appendix = A.render(task / "work" / "test-cases")
        check("case appendix is sorted deterministically", appendix.index("TC-001") < appendix.index("TC-002"))
        check("case appendix exposes oracle, channel and review status", "requirement:R-1" in appendix and "manual-human" in appendix and "Review" in appendix)
        (task / "test-report.md").write_text("report", encoding="utf-8")
        (task / "retro.md").write_text("retro", encoding="utf-8")
        (task / "work" / "ledger.json").write_text("{}", encoding="utf-8")
        state = task / "state"
        (state / "case-versions" / "TC-001").mkdir(parents=True)
        (state / "story-case-links.json").write_text('{"TC-001":"v1"}', encoding="utf-8")
        (state / "case-versions" / "TC-001" / "v1.md").write_text("snapshot", encoding="utf-8")
        (state / "case-versions" / "TC-001" / "v1.json").write_text("{}", encoding="utf-8")
        (state / "events.jsonl").write_text("{}\n", encoding="utf-8")
        (state / "events.lock").write_text("lock", encoding="utf-8")
        evidence = task / "work" / "evidence"
        evidence.mkdir()
        (evidence / "run.log").write_text("raw", encoding="utf-8")
        paths = [row["path"] for row in D.build(task)["files"]]
        check("clean checkout includes report, retro and compact ledger", all(p in paths for p in ("test-report.md", "retro.md", "work/ledger.json")))
        check("clean checkout includes canonical case snapshot", "work/test-cases/checkout/TC-001.md" in paths)
        check("clean checkout pins story links and task-local case versions",
              all(p in paths for p in ("state/story-case-links.json",
                                       "state/case-versions/TC-001/v1.md",
                                       "state/case-versions/TC-001/v1.json")))
        check("only the exact durable event stream is included",
              "state/events.jsonl" in paths and "state/events.lock" not in paths)
        check("delivery excludes raw evidence", "work/evidence/run.log" not in paths)
        delivery = D.build(task)
        manifest_path = task / "state" / "delivery-manifest.json"
        manifest_path.parent.mkdir(exist_ok=True)
        manifest_path.write_text(json.dumps(delivery), encoding="utf-8")
        check("preliminary S8 manifest validates before the future retro requirement", not C.delivery_manifest_reasons(task))
        check("finalized delivery validates the current retro hash", not C.delivery_manifest_reasons(task, finalized=True))
        delivery["files"].append({"path": "work/evidence/run.log", "sha256": "bad"})
        manifest_path.write_text(json.dumps(delivery), encoding="utf-8")
        check("delivery manifest rejects raw evidence even with a listed hash", bool(C.delivery_manifest_reasons(task)))
    print(f"=== test_delivery_visibility: {10-len(failures)}/10 ok ===")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
