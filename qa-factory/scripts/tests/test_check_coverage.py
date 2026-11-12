#!/usr/bin/env python3
"""t-622 (forge batch 4, F4-2): `check_coverage.py` is an acceptance gate, and a folder that is no project is not an "OK".

Before: the default root was `hooklib.project_root()`, whose last fallbacks are the git toplevel and the working directory,
so run from a folder that is no project it printed "OK: no local cases" and exited 0 - a pass on something nobody had
looked at (FR-59). Now the root must be a project (it holds `qa-factory/config.json`):
  K1  `--root` is honoured when it IS a project; a folder that is not (and a folder BELOW a project, which names the project
      above it) is exit 2, on stderr, naming the folder and the door;
  K2  the default root (`hooklib.project_root()`: env first, then the marker above the working directory) that is not a
      project is exit 2 too; one that is runs as before;
  K3  when hooklib cannot be imported the default is the project above the working directory, and none is exit 2;
  K4  the reconciliation itself is untouched: cases and no map = exit 1, `--write` then OK.
"""
import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))

CLEAN: list = []


def scratch() -> Path:
    base = temp_dir("qa-cc-").resolve()
    CLEAN.append(base)
    return base


def project(base: Path, name: str = "proj") -> Path:
    root = base / name
    (root / "qa-factory").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    return root


def env_without_project() -> dict:
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def run(*args, cwd: Path, env: dict | None = None):
    return harness.run_script("check_coverage.py", *args, cwd=cwd, env=env if env is not None else env_without_project())


def k1_root() -> None:
    base = scratch()
    root = project(base)
    (root / "sub").mkdir()
    bare = base / "not-a-project"
    bare.mkdir()
    done = run("--root", root, cwd=bare)
    check("K1 --root that IS a project, no cases: exit 0 and the OK line", done.returncode == 0 and "OK: no local cases" in done.stdout,
          f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")
    done = run("--root", bare, cwd=root)
    check("K1 --root that is NOT a project (the working directory is a project): exit 2, nothing on stdout",
          done.returncode == 2 and done.stdout == "", f"{done.returncode} {done.stdout[:200]}")
    check("K1 ...stderr names the folder, says it has no qa-factory/config.json, and names the door (--root)",
          str(bare.resolve()) in done.stderr and "qa-factory/config.json" in done.stderr and "--root" in done.stderr, done.stderr[:400])
    done = run("--root", root / "sub", cwd=bare)
    check("K1 --root BELOW a project is exit 2 too, and stderr names the project above it",
          done.returncode == 2 and str(root.resolve()) in done.stderr and f"--root {root.resolve()}" in done.stderr, f"{done.returncode} {done.stderr[:400]}")
    done = run("--root", base / "does" / "not" / "exist", cwd=root)
    check("K1 --root that does not exist: exit 2 naming it, no traceback", done.returncode == 2 and "does" in done.stderr
          and "Traceback" not in done.stderr, f"{done.returncode} {done.stderr[:300]}")
    (base / "dircfg" / "qa-factory" / "config.json").mkdir(parents=True)
    done = run("--root", base / "dircfg", cwd=root)
    check("K1 --root whose config.json is a DIRECTORY is not a project: exit 2", done.returncode == 2, f"{done.returncode} {done.stderr[:200]}")


def k2_default() -> None:
    base = scratch()
    root = project(base)
    inside = root / "qa-factory" / "artifacts"
    inside.mkdir(parents=True)
    bare = base / "not-a-project"
    bare.mkdir()
    done = run(cwd=inside)
    check("K2 default root, working directory inside a project: the project above it, exit 0",
          done.returncode == 0 and "OK" in done.stdout, f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")
    done = run(cwd=bare)
    check("K2 default root, working directory in a folder that is no project: exit 2 (it was an OK and exit 0)",
          done.returncode == 2 and done.stdout == "", f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")
    check("K2 ...stderr names the folder, says what a project is, and names both doors (run inside the project / --root)",
          str(bare.resolve()) in done.stderr and "qa-factory/config.json" in done.stderr and "--root" in done.stderr
          and "inside the project" in done.stderr, done.stderr[:400])
    env = env_without_project()
    env["CLAUDE_PROJECT_DIR"] = str(bare)
    done = run(cwd=bare, env=env)
    check("K2 default root from CLAUDE_PROJECT_DIR that is no project: exit 2", done.returncode == 2, f"{done.returncode} {done.stderr[:200]}")
    env["CLAUDE_PROJECT_DIR"] = str(root)
    done = run(cwd=bare, env=env)
    check("K2 default root from CLAUDE_PROJECT_DIR that IS a project wins over the working directory (env first): exit 0",
          done.returncode == 0 and "OK" in done.stdout, f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")


def k3_without_hooklib() -> None:
    base = scratch()
    root = project(base)
    (root / "sub").mkdir()
    bare = base / "not-a-project"
    bare.mkdir()
    saved_modules = {name: sys.modules.get(name) for name in ("hooklib", "check_coverage_nohook")}
    sys.modules["hooklib"] = None                              # `from hooklib import ...` raises ImportError
    cwd0 = os.getcwd()
    try:
        spec = importlib.util.spec_from_file_location("check_coverage_nohook", harness.SCRIPTS / "check_coverage.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        os.chdir(root / "sub")
        found = module._project_root()
        check("K3 no hooklib, working directory inside a project: the project above it", found == root.resolve(), str(found))
        os.chdir(bare)
        got, refusal = module.marked_root(None)
        check("K3 no hooklib, working directory in a folder that is no project: refused, naming the folder (never an OK)",
              got is None and str(bare.resolve()) in refusal and "--root" in refusal, f"{got} {refusal[:300]}")
        got, refusal = module.marked_root(root)
        check("K3 no hooklib, an explicit --root that is a project is honoured", got == root.resolve() and refusal == "", f"{got} {refusal}")
    finally:
        os.chdir(cwd0)
        for name, previous in saved_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def k4_reconciliation_untouched() -> None:
    base = scratch()
    root = project(base)
    case = root / "qa-factory" / "artifacts" / "T-1" / "test-cases" / "area-a" / "TC-1.md"
    case.parent.mkdir(parents=True)
    case.write_text("---\nid: TC-1\narea: area-a\nstatus: Draft\nupdated: 2026-01-01\n---\nbody\n", encoding="utf-8")
    done = run("--root", root, cwd=base)
    # C2-1 (detector_verdict contract): the whole verdict is on STDOUT, header with a count, one `- ` line per finding;
    # nothing of it on stderr (a stale map used to hide behind a WARN list on the other stream)
    done = run("--root", root, cwd=base)
    check("K4 cases and no map: exit 1, the map is stale (as before), REJECT with its count on stdout",
          done.returncode == 1 and done.stdout.startswith("REJECT — 1 problem(s): the map is stale:\n- ")
          and "REJECT" not in done.stderr, f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")
    done = run("--root", root, "--write", cwd=base)
    check("K4 --write builds the map: exit 0", done.returncode == 0 and "WROTE" in done.stdout, f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")
    done = run(cwd=root)
    check("K4 the default root (working directory = the project) then agrees with the map: exit 0",
          done.returncode == 0 and "coverage-map agrees with 1 cases" in done.stdout, f"{done.returncode} {done.stdout[:200]} {done.stderr[:200]}")
    # the second REJECT (the map diverged), with a WARN list above it: the WARN lines are context, not findings
    import detector_verdict
    map_file = root / "qa-factory" / "records" / "coverage-map.md"
    if not map_file.exists():
        map_file = root / "qa-factory" / "state" / "coverage-map.md"
    map_file.write_text(map_file.read_text(encoding="utf-8").replace("| Cases created | 1 |", "| Cases created | 7 |")
                        + "\n## Area: ghost\n\n| Cases created | 0 |\n| Automated | 0 |\n", encoding="utf-8")
    done = run(cwd=root)
    verdict = detector_verdict.parse(done.returncode, done.stdout, done.stderr)
    heads = [line for line in done.stdout.splitlines() if line.startswith("REJECT")]
    check("K4 a diverged map: exit 1, ONE REJECT header with the count of the findings, on stdout",
          done.returncode == 1 and len(heads) == 1 and "REJECT" not in done.stderr
          and heads[0].startswith(f"REJECT — {len(verdict['findings'])} problem(s): ") and len(verdict["findings"]) >= 2,
          f"{done.returncode} {done.stdout[:400]} {done.stderr[:200]}")
    check("K4 ...the WARN list above it is context: no finding of the verdict is a warning, nothing unmigrated",
          "WARN:" in done.stdout and not any("ghost" in finding for finding in verdict["findings"])
          and not verdict["unmigrated"] and not verdict["defects"], str(verdict)[:300])


def a_k4_pinned_route_follows_instance_hold() -> None:
    """HF3-1 A-K4 (AR-13, FR-59): the coverage map counts a PINNED case automated only when `case_stamp.instance_hold` of a LIVE
    instance linking that exact version is empty - green in the manifest AND a green run row of its own, approved
    (`approved_with_fixes` included). Kills: the old red-run-only route (m4: no row / skipped / partial counted), the loop over
    dead rows (critic t-1254 B1), `approved_with_fixes` outside the verdicts (m3)."""
    import json
    import case_versions as V
    import check_coverage as CC
    base = scratch()
    root = project(base)
    task = root / "qa-factory" / "artifacts" / "T-9"
    source = task / "work" / "test-cases" / "area-a" / "TC-1.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\nid: TC-1\narea: area-a\nstatus: Approved\nupdated: 2026-01-01\n---\n\n## Then\n1. it happens.\n", encoding="utf-8")
    record = V.create_version(root / "qa-factory" / "state" / "case-store", source)
    V.pin(task, record)
    link = [{"case_id": "TC-1", "version": record["version"], "content_hash": record["content_hash"]}]

    def test(name: str, **fields) -> dict:
        return dict({"instance_id": name, "status": "green", "critic_verdict": "approved", "case_version_links": link}, **fields)

    def automated(tests: list, rows) -> int:
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": tests}), encoding="utf-8")
        report = task / "work" / "run-report.json"
        if rows is None:
            report.unlink(missing_ok=True)
        else:
            report.write_text(json.dumps({"current_results": rows}), encoding="utf-8")
        return CC.collect_cases(root)["area-a"]["automated"]

    ran = lambda name, word="passed": {"instance_id": name, "status": word}   # noqa: E731
    cases = [
        ("a green manifest + a green row of its own", [test("t")], [ran("t")], 1),
        ("a green manifest + NO run report", [test("t")], None, 0),
        ("a green manifest + a report without its row", [test("t")], [ran("other")], 0),
        ("a green manifest + a red row", [test("t")], [ran("t", "failed")], 0),
        ("a green manifest + `skipped`", [test("t")], [ran("t", "skipped")], 0),
        ("a green manifest + `partial`", [test("t")], [ran("t", "partial")], 0),
        ("`approved_with_fixes` + a green row", [test("t", critic_verdict="approved_with_fixes")], [ran("t")], 1),
        ("`rejected` + a green row", [test("t", critic_verdict="rejected")], [ran("t")], 0),
        ("a manifest `red` + a green row", [test("t", status="red")], [ran("t")], 0),
        ("a live instance with a green row + a DEAD one with none (B1)",
         [test("t"), test("old", note="SUPERSEDED DUPLICATE")], [ran("t")], 1),
        ("a dead instance alone, with a green row (B1: it is no instance)",
         [test("old", note="SUPERSEDED DUPLICATE")], [ran("old")], 0),
    ]
    for label, tests, rows, want in cases:
        check(f"A-K4 pinned route: {label} -> {want}", automated(tests, rows) == want, f"{automated(tests, rows)} != {want}")


def main() -> None:
    try:
        a_k4_pinned_route_follows_instance_hold()
        k1_root()
        k2_default()
        k3_without_hooklib()
        k4_reconciliation_untouched()
    finally:
        for base in CLEAN:
            cleanup(base)
    finish("test_check_coverage")


if __name__ == "__main__":
    main()
