"""Coverage migration is explicit, idempotent, backed up and historically conservative."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import mark_project
from controller import Controller
import migrate_coverage as M


def legacy_plan(root, version=None):
    row = {"id": "TS-1", "impact": "low", "likelihood": "low", "confidence": "high",
           "risk_rationale": "legacy", "risk_source_refs": ["R-1"],
           "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1"],
           "unknowns": [], "verification_depth": "low", "required_scenarios": ["TC-1"],
           "test_level_rationale": "unit", "design_review_required": False,
           "bounded_reversible": True}
    if version is not None:
        row["schema_version"] = version
    path = root / "work/test-plan.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([row]), encoding="utf-8")
    return path


def main():
    with tempfile.TemporaryDirectory(prefix="qa-coverage-migration-") as td:
        mark_project(Path(td))      # the stories below sit in a project
        root = Path(td) / "active"; root.mkdir()
        Controller(root).apply("initialize", {"scope": ["TC-1"], "source_revision": "src",
            "known_paths": {"root": str(root)}, "coverage_contract_version": 1,
            "idempotency_key": "init"})
        path = legacy_plan(root)
        before = path.read_bytes()
        dry = M.plan(root)
        assert dry["status"] == "planned" and path.read_bytes() == before
        assert not (root / dry["backup_ref"]).exists()
        done = M.migrate(root)
        assert done["status"] == "completed"
        assert (root / done["backup_ref"]).read_bytes().strip() == before.strip()
        assert Controller(root).state()["coverage_contract_version"] == 2
        migrated = json.loads(path.read_text(encoding="utf-8"))
        obligation = migrated["rows"][0]["coverage_obligations"][0]
        assert obligation["oracle_status"] == "unresolved" and obligation["decision"] == "unresolved"
        again = M.migrate(root)
        assert again["status"] == "already_migrated" and path.read_text(encoding="utf-8") == json.dumps(migrated, ensure_ascii=False, indent=2) + "\n"

        historical = Path(td) / "historical"; historical.mkdir()
        historical_path = legacy_plan(historical)
        historical_bytes = historical_path.read_bytes()
        assert M.migrate(historical)["status"] == "historical_unchanged"
        assert historical_path.read_bytes() == historical_bytes

        unknown = Path(td) / "unknown"; unknown.mkdir()
        Controller(unknown).apply("initialize", {"scope": ["TC-1"], "source_revision": "src",
            "known_paths": {"root": str(unknown)}, "coverage_contract_version": 1,
            "idempotency_key": "init"})
        legacy_plan(unknown, 99)
        try:
            M.plan(unknown)
            failed_closed = False
        except ValueError:
            failed_closed = True
        assert failed_closed
    print("=== test_migrate_coverage: 10/10 ok ===")


if __name__ == "__main__":
    main()
