"""Where a project keeps its test cases — discovered once, then obeyed by everything.

Onboarding always LOOKED for an existing case store (`p1-discovery.md`: a `test-cases/`
directory, files named `TC-*`, a TMS link) and the finding went into no config key, so every
case the factory wrote landed in its own per-story tree beside the project's real library —
which is what green-lantern reported. `config.cases_root` carries the finding now, and these
are the checks that the fact has one owner and one reading: contract.cases_root for the
story scripts, check_coverage for the project-wide map, and a fallback that leaves every
config written before the key existed working exactly as it did.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    SCRIPTS, check_eq, check_in, cleanup, finish, run_script, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))

CASE = """---
id: {cid}
title: A case that belongs to {task}
area: checkout
priority: P0
status: {status}
channel: auto
reuse_decision: new
updated: 2026-09-17
task: {task}
covers: [R-1]
defect_class: boundary
basis: "requirement:R-1"
plan_row: TS-1
---
Requirements: R-1
Plan row: TS-1
"""


def write_case(path: Path, cid: str, task: str, status: str = "Draft") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CASE.format(cid=cid, task=task, status=status), encoding="utf-8")


def set_key(root: Path, key: str, value) -> None:
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg[key] = value
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def main() -> None:
    root = temp_project("qa-factory-case-store-")
    use_project(root)
    import contract as C  # noqa: E402  (imported AFTER the project root is set)
    import check_coverage as CC  # noqa: E402

    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        (art / "work").mkdir(parents=True)

        # 1. No store declared: the story keeps its own cases, exactly as before this key.
        write_case(art / "work" / "test-cases" / "checkout" / "TC-001.md", "TC-001", "QA-1")
        check_eq("no cases_root: the story's own folder is the store",
                 C.cases_root(art), art / "work" / "test-cases")
        check_eq("no cases_root: the story's cases are found",
                 [p.name for p in C.case_files(art)], ["TC-001.md"])
        check_eq("no cases_root: work/ resolves the same as the story folder",
                 C.cases_root(art / "work"), C.cases_root(art))

        # 2. A declared store wins, and the story reads its own cases out of a shared one.
        store = root / "docs" / "test-cases"
        write_case(store / "checkout" / "TC-001.md", "TC-001", "QA-1", status="Automated")
        write_case(store / "checkout" / "TC-050.md", "TC-050", "QA-7")
        (store / "checkout" / "README.md").write_text("not a case\n", encoding="utf-8")
        set_key(root, "cases_root", "docs/test-cases")
        use_project(root)  # the config is read per call, but the root cache is not

        check_eq("cases_root: the declared store is the store", C.cases_root(art).resolve(), store.resolve())
        check_eq("cases_root: only this story's cases reach its index",
                 sorted(C.case_index(art)), ["TC-001"])
        check_eq("cases_root: a sibling story's case is not this story's",
                 [p.name for p in C.case_files(art)], ["TC-001.md"])
        check_eq("cases_root: the case that is read is the one in the store",
                 C.case_status(C.case_index(art)["TC-001"]["path"]), "Automated")

        # 3. The project-wide map counts the whole library — that is what it is for.
        areas = CC.collect_cases(root)
        check_eq("coverage map: both stories' cases are counted", areas["checkout"]["total"], 2)
        check_eq("coverage map: the Automated one is counted", areas["checkout"]["automated"], 1)
        check_eq("coverage map: a README in the store is not a case", len(areas), 1)

        # 4. Readiness says where the store is, and refuses one inside application code.
        data = json.loads(run_script("readiness.py", "--json",
                                     env={"CLAUDE_PROJECT_DIR": str(root)}).stdout)
        check_eq("readiness: a store that exists is ok",
                 data["capabilities"]["case_store"]["status"], "ok")
        check_in("readiness: and the note names it", "docs/test-cases",
                 data["capabilities"]["case_store"]["note"])

        # 5. An unreadable/absent store is a missing capability, not a silent empty index.
        set_key(root, "cases_root", "nowhere/at/all")
        use_project(root)
        check_eq("a cases_root that does not exist yields no cases", C.case_files(art), [])
        data = json.loads(run_script("readiness.py", "--json",
                                     env={"CLAUDE_PROJECT_DIR": str(root)}).stdout)
        check_eq("and readiness calls it missing",
                 data["capabilities"]["case_store"]["status"], "missing")
    finally:
        cleanup(root)

    finish("test_case_store")


if __name__ == "__main__":
    main()
