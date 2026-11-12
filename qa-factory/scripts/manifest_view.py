"""The slice of an artifact a role actually needs, instead of the file.

`automation-manifest.json` was read 32 times across one story for 806,531 characters
(TP1-14336) — by the fifth window it weighed 63 KB, and both the automator and the
critic read all of it every time, to work on two or three cases. `context-manifest.json`:
16 reads, 354,830 characters. Everything read is billed again on every remaining turn of
the dispatch that read it, so the difference between a file and a slice is the difference
between paying for what you use and paying for the whole story so far.

  manifest_view.py --task QA-1 --case TC-001 [--case TC-002]     those entries
  manifest_view.py --task QA-1 --window "TC-001,TC-004"          a window's cases
  manifest_view.py --task QA-1 --unresolved                      what is not closed
  manifest_view.py --task QA-1 --summary                         counts and verdicts only
  manifest_view.py --task QA-1 --context --rows TS-1,TS-2        S1's observables for rows
  manifest_view.py --selftest

Output is JSON, so a role can read it as data; `--summary` prints lines. Nothing here
writes, and nothing here decides — it selects.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
from hooklib import artifacts_dir  # noqa: E402


def load(task: str, name: str) -> dict:
    return C.load_json(C.artifact(artifacts_dir(task), name))


def wanted_case(entry, cases: list, cfg: dict | None = None) -> bool:
    """Is this entry one of the cases asked for, in whichever spelling either side used?

    `--case TC-001` selects it in every area; `--case speakers/TC-001` selects that area's
    case and not `speaker-detail/TC-001` (FB-2428-1). Ids are compared case-insensitively,
    the way this selection always compared them: BOTH sides are upper-cased before
    `case_matches`, so a lower-case `--case ...` still finds a project-form id.

    `cfg` is the project config resolved once by the caller (`pick_tests` / `pick_unresolved`
    hold it for the whole manifest); alone, this resolves it for the process's project."""
    cfg = C.case_config() if cfg is None else cfg
    keys = [key.upper() for key in C.manifest_test_keys(entry, cfg)]
    return any(C.case_matches(key, str(case).upper(), cfg=cfg) for case in cases for key in keys)


def pick_tests(manifest: dict, cases: list) -> list:
    cfg = C.case_config()
    return [t for t in C.manifest_tests(manifest) if not cases or wanted_case(t, cases, cfg)]


def pick_unresolved(manifest: dict, cases: list) -> list:
    cfg = C.case_config()
    return [u for u in C.manifest_unresolved(manifest) if not cases or wanted_case(u, cases, cfg)]


def pick_obligation_bindings(manifest: dict, tests: list) -> list:
    """Return only bindings evidenced by the selected tests, never the whole map."""
    instance_ids = {C.test_instance_id(test) for test in tests}
    obligation_ids = set()
    for test in tests:
        for ref in test.get("obligation_refs") or []:
            if isinstance(ref, dict) and ref.get("obligation_id"):
                obligation_ids.add(str(ref["obligation_id"]))
        for oid in test.get("obligation_ids") or []:
            if oid:
                obligation_ids.add(str(oid))
    return [binding for binding in manifest.get("obligation_bindings") or []
            if isinstance(binding, dict)
            and (bool(instance_ids & set(binding.get("instance_ids") or []))
                 or str(binding.get("obligation_id") or "") in obligation_ids)]


def summary(manifest: dict) -> list:
    tests = C.manifest_tests(manifest)
    unresolved = C.manifest_unresolved(manifest)
    verdicts: dict = {}
    for t in tests:
        verdicts[str(t.get("critic_verdict") or "not reviewed")] = \
            verdicts.get(str(t.get("critic_verdict") or "not reviewed"), 0) + 1
    lines = [f"tests: {len(tests)}", f"test instances: {len({C.test_instance_id(t) for t in tests})}",
             f"unresolved: {len(unresolved)}"]
    for verdict, n in sorted(verdicts.items()):
        lines.append(f"  {verdict}: {n}")
    for u in unresolved:
        lines.append(f"  unresolved {C.case_key(u.get('case') or '', u.get('area') or '')}: {u.get('reason')}")
    runs = manifest.get("runs") or []
    lines.append(f"runs recorded: {len(runs)}")
    return lines


def context_rows(manifest: dict, rows: list) -> dict:
    """The S1 evidence for named plan rows: the observables whose requirement is cited by
    one of them, plus the implementation entries. A role planning TS-1 and TS-2 has no use
    for the other twenty observables, and every one of them costs it turns."""
    wanted = {r.upper() for r in rows}
    obs = []
    for o in manifest.get("observables") or []:
        if not isinstance(o, dict):
            continue
        req = str(o.get("requirement") or "").upper()
        if not wanted or any(w in req for w in wanted):
            obs.append(o)
    return {
        "ticket": manifest.get("ticket"),
        "implementation": manifest.get("implementation"),
        "implementations": manifest.get("implementations"),
        "observables": obs,
        "acceptance_criteria": manifest.get("acceptance_criteria"),
    }


def selftest() -> int:
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    manifest = {
        "tests": [{"case": "TC-001", "file": "t.py", "critic_verdict": "approved", "instance_id": "i-1", "obligation_ids": ["O-1"]},
                  {"case": "TC-002", "file": "t.py", "critic_verdict": "rejected", "instance_id": "i-2", "obligation_ids": ["O-2"]},
                  {"case": "TC-003", "file": "u.py", "instance_id": "i-3"}],
        "obligation_bindings": [{"obligation_id": "O-1", "instance_ids": ["i-1"]}, {"obligation_id": "O-2", "instance_ids": ["i-2"]}, {"obligation_id": "O-x", "instance_ids": ["i-x"]}],
        "unresolved": [{"case": "TC-004", "reason": "impossible"}],
        "runs": [{"label": "witness"}, {"label": "critic-run"}],
    }
    case("one case comes back alone", [t["case"] for t in pick_tests(manifest, ["TC-002"])],
         ["TC-002"])
    case("a window comes back in order",
         [t["case"] for t in pick_tests(manifest, ["TC-003", "TC-001"])], ["TC-001", "TC-003"])
    case("no filter means every entry", len(pick_tests(manifest, [])), 3)
    case("a case nobody wrote comes back empty", pick_tests(manifest, ["TC-099"]), [])
    case("bindings follow selected instance", [b["obligation_id"] for b in pick_obligation_bindings(manifest, pick_tests(manifest, ["TC-002"]))], ["O-2"])
    case("unresolved selects too",
         [u["case"] for u in pick_unresolved(manifest, [])], ["TC-004"])
    lines = summary(manifest)
    case("the summary counts the tests", "tests: 3" in lines, True)
    case("the summary counts the unreviewed", "  not reviewed: 1" in lines, True)
    case("the summary names the unresolved reason",
         any("TC-004: impossible" in ln for ln in lines), True)

    ctx = {"ticket": "QA-1", "acceptance_criteria": ["a"], "implementation": {"source": "diff"},
           "observables": [{"requirement": "R-1 coupon", "path": "a.py", "line": 1},
                           {"requirement": "R-9 budget", "path": "b.py", "line": 2}]}
    picked = context_rows(ctx, ["R-1"])
    case("context rows select by requirement", len(picked["observables"]), 1)
    case("and keep the implementation block", picked["implementation"]["source"], "diff")

    if failures:
        print("MANIFEST_VIEW SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("MANIFEST_VIEW SELFTEST: no violations (case, window, unresolved, summary, rows)")
    return 0


def main() -> int:
    C.force_utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--case", action="append", default=[], help="repeatable")
    ap.add_argument("--window", default="", help="comma-separated case ids")
    ap.add_argument("--unresolved", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--context", action="store_true", help="read context-manifest.json instead")
    ap.add_argument("--rows", default="", help="comma-separated plan row ids (with --context)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.task:
        print("manifest_view.py: --task <TICKET> is required", file=sys.stderr)
        return 2

    if args.context:
        data = load(args.task, "context-manifest.json")
        if not data:
            print(f"manifest_view.py: no context-manifest.json for {args.task}", file=sys.stderr)
            return 1
        rows = [r.strip() for r in args.rows.split(",") if r.strip()]
        print(json.dumps(context_rows(data, rows), indent=2, ensure_ascii=False))
        return 0

    data = load(args.task, "automation-manifest.json")
    if not data:
        print(f"manifest_view.py: no automation-manifest.json for {args.task} — S5 writes it",
              file=sys.stderr)
        return 1
    cases = list(args.case) + [c.strip() for c in args.window.split(",") if c.strip()]
    if args.summary:
        print("\n".join(summary(data)))
        return 0
    out = {"unresolved": pick_unresolved(data, cases)}
    if not args.unresolved:
        tests = pick_tests(data, cases)
        out["tests"] = tests
        out["obligation_bindings"] = pick_obligation_bindings(data, tests)
        out["run_witness"] = data.get("run_witness")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
