#!/usr/bin/env python3
"""R6 (t-1508 section 5.6): the triage names the Thens a red stops - `blocked_thens` / `blocking_check` - and ONE reader
turns them into the same `blocked_by_check` rows the manifest's own rows are, with no second bug draft.

Keys K-R6-1..6, 11, 12 and the seam K-R6-S of the spec (written before the run); K-R6-7..10 (the pairing of drafts) are in
`test_bug_records.py`. The data is the fixture of run 12586 (`fixtures/run-12586-red-then/`): TC-002 red at Then 1,
TC-003 red at Then 2, Thens 3 and 4 of TC-003 waiting for TC-002's fix; its report also holds the history rows of the
diagnostic attempt `a5ba38...` (K-R6-1: they are not product rows).
"""
import copy
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import ledger as L  # noqa: E402
import validate_artifacts as V  # noqa: E402

FIXTURE = FIXTURES / "run-12586-red-then"
IID2 = "test_put_project_change_moves_ms_teams_integration"
IID3 = "test_put_project_change_into_project_with_ms_teams_is_rejected"
ATTEMPT = "a96f5e653377735139aa"
EVIDENCE = "evidence/diagnostic-tc003-then3-4.json"
BLOCKED = (C.BLOCKED_BY_CHECK,)


def fresh() -> Path:
    root = temp_dir("qa-triage-blocked-") / "TP1-12586"
    shutil.copytree(FIXTURE, root)
    return root


def read(root: Path, name: str) -> dict:
    return json.loads((root / "work" / name).read_text(encoding="utf-8"))


def write(root: Path, name: str, data: dict) -> None:
    (root / "work" / name).write_text(json.dumps(data, indent=1), encoding="utf-8")


def tc3(root: Path, **fields) -> dict:
    """Write the triage with the fields on TC-003's row; return the row."""
    triage = read(root, "triage.json")
    row = next(r for r in triage["triage"] if r["case"] == "TC-003")
    row.update(fields)
    write(root, "triage.json", triage)
    return row


def waiting(*thens, blocker="TC-002") -> dict:
    return {"blocking_check": "TC-002",
            "blocked_thens": [{"then": n, "blocking_check": blocker, "detail": f"check Then {n} once {blocker} is fixed"}
                              for n in thens]}


def both(root: Path):
    return read(root, "triage.json"), read(root, "run-report.json"), read(root, "automation-manifest.json")


def main() -> None:
    root = fresh()
    try:
        # K-R6-1: the fixture's triage as it is (history rows of the diagnostic attempt in the report) -> nothing new
        triage, report, manifest = both(root)
        check_eq("K-R6-1: no triage field -> no Then behind a check, with or without the triage",
                 (C.then_remainders(manifest, None, BLOCKED, triage, report), C.then_remainders(manifest, None, BLOCKED)), ([], []))
        check_eq("K-R6-1: ... and no 'Left with you' record of that kind", CD.blocked_records(root), [])
        check_eq("K-R6-1: ... and no triage reason about the new fields",
                 [r for r in CD.triage_reasons(root) if "blocked" in r or "diagnostic" in r or "blocking_check" in r], [])
        check_eq("K-R6-1: the helper of the Then numbers reads the case file", C.case_then_numbers(root, "TC-003"), [1, 2, 3, 4])
        check_eq("K-R6-1: ... an unknown case has none", C.case_then_numbers(root, "TC-404"), [])

        # K-R6-2: Thens 3 and 4 of TC-003 wait for TC-002
        tc3(root, **waiting(3, 4))
        triage, report, manifest = both(root)
        rows = C.then_remainders(manifest, None, BLOCKED, triage, report)
        check_eq("K-R6-2: two rows, Thens 3 and 4, reason blocked_by_check, the blocker TC-002, no owner",
                 [(r["case"], r["then"], r["reason"], r["blocking_check"], r["owner"], r["instance_id"]) for r in rows],
                 [("TC-003", n, "blocked_by_check", "TC-002", "", IID3) for n in (3, 4)])
        records = CD.blocked_records(root)
        check_eq("K-R6-2: the 'Left with you' records: kind, case, Then, blocker",
                 [(r["kind"], r["case"], r["then"], r["blocking_check"]) for r in records],
                 [("blocked_by_check", "TC-003", n, "TC-002") for n in (3, 4)])
        check("K-R6-2: `how` names TC-002", all("TC-002" in r["how"] for r in records), str([r["how"] for r in records]))
        check_eq("K-R6-2: the fields are well formed -> no problem from either reader",
                 (C.triage_blocked_problems(read(root, "triage.json")["triage"][1], root, triage["triage"], report),
                  [r for r in CD.triage_reasons(root) if "blocked" in r or "blocking_check" in r]), ([], []))
        errors: list = []
        V.check_triage_v0(Path("triage.json"), triage, errors, root)
        check_eq("K-R6-2: the validator takes the row", errors, [])
        check_eq("K-R6-2: the fixture's own report has the row's red as a failure",
                 sorted(k[1] for k in C.triage_failures(report)[0]), sorted([IID2, IID3]))

        # K-R6-3: the same Then in the manifest and in the triage -> one row
        both_ways = copy.deepcopy(manifest)
        both_ways["then_bindings"] = [b for b in both_ways["then_bindings"] if not (b["case"] == "TC-003" and b["then"] == 3)]
        both_ways["then_bindings"].append({"case": "TC-003", "then": 3, "instance_id": IID3, "status": "unresolved",
                                           "reason": "blocked_by_check", "blocking_check": "TC-002", "detail": "from the manifest"})
        rows = C.then_remainders(both_ways, None, BLOCKED, triage, report)
        check_eq("K-R6-3: Then 3 in both -> listed once (the manifest's row first), Then 4 from the triage",
                 [(r["then"], r["detail"]) for r in rows], [(3, "from the manifest"), (4, "check Then 4 once TC-002 is fixed")])

        # K-R6-4: Then 2 is the row's own red Then -> a problem (the validator and the delivery check)
        tc3(root, **waiting(2, 3))
        triage, report, manifest = both(root)
        row = triage["triage"][1]
        problems = C.triage_blocked_problems(row, root, triage["triage"], report)
        check("K-R6-4: Then 2 ran and failed -> named", any("Then 2 of TC-003 ran and failed" in p for p in problems), str(problems))
        check_eq("K-R6-4: only that one problem", len(problems), 1)
        errors = []
        V.check_triage_v0(Path("triage.json"), triage, errors, root)
        check("K-R6-4: the validator says so, with the row's name", any("ran and failed" in e and IID3 in e for e in errors), str(errors))
        check("K-R6-4: the delivery check says so (a `triage:` reason -> no)",
              any(r.startswith("triage:") and "ran and failed" in r for r in CD.triage_reasons(root)))
        # ... a Then that is not a Then of the case, an unknown case file, a blocker that is the case itself
        tc3(root, **waiting(9))
        triage, report, _m = both(root)
        check("K-R6-4: Then 9 is not a Then of TC-003", any("not a Then of TC-003" in p for p in
              C.triage_blocked_problems(triage["triage"][1], root, triage["triage"], report)))
        tc3(root, **waiting(3, blocker="TC-003"))
        triage, report, _m = both(root)
        check("K-R6-4: a Then waiting for its own case", any("own case" in p for p in
              C.triage_blocked_problems(triage["triage"][1], root, triage["triage"], report)))
        check_eq("K-R6-4: ... a form error is named by the one shape check (no whitespace in the blocker)",
                 any("blocking_check" in p for p in C.triage_blocked_problems(
                     {"case": "TC-003", "blocked_thens": [{"then": 3, "blocking_check": "TC 002", "detail": "x"}]})), True)
        check_eq("K-R6-4: not a list -> a problem; an empty list or no field -> none",
                 (bool(C.triage_blocked_problems({"case": "TC-003", "blocked_thens": "3"})),
                  C.triage_blocked_problems({"case": "TC-003", "blocked_thens": []}),
                  C.triage_blocked_problems({"case": "TC-003"}), C.triage_blocked_problems("junk")), (True, [], [], []))
        check("K-R6-4: no case on the row -> a problem, not a pass", bool(C.triage_blocked_problems(
            {"blocked_thens": [{"then": 3, "blocking_check": "TC-002", "detail": "x"}]})))
        unreadable_case = fresh()
        for held in unreadable_case.rglob("TC-003.md"):      # every copy: the fixture holds a nested one under controller/ that the lookup finds next
            held.unlink()
        check("K-R6-4: the case file cannot be read -> a problem (the unknown is not a pass)", any(
            "not found" in p for p in C.triage_blocked_problems(
                {"case": "TC-003", "blocked_thens": [{"then": 3, "blocking_check": "TC-002", "detail": "x"}]}, unreadable_case)))
        cleanup(unreadable_case.parent)

        # F5 (t-1556): `reorder` is judged by the validator too - the ONE reader, `contract.triage_reorder_problems`
        base_row = {"instance_id": IID3, "test": IID3, "case": "TC-003", "verdict": "APP_BUG"}
        for label, extra, bad in (("reorder: true without blocked_thens", {"reorder": True}, True),
                                  ("reorder: true with an empty blocked_thens", {"reorder": True, "blocked_thens": []}, True),
                                  ("reorder: \"yes\" (not the boolean true)", {"reorder": "yes", **waiting(3)}, True),
                                  ("reorder: true with blocked_thens", {"reorder": True, **waiting(3)}, False),
                                  ("no reorder key", {}, False)):
            triage, report, _m = both(root)
            others = [r for r in triage["triage"] if r.get("case") != "TC-003"]
            errors = []
            V.check_triage_v0(Path("triage.json"), {"triage": others + [dict(base_row, **extra)]}, errors, root)
            named = [e for e in errors if "reorder" in e]
            check_eq(f"F5: the validator on {label}: {'a `reorder` error' if bad else 'no `reorder` error'}", bool(named), bad)
            check_eq("F5: ...the same verdict as the one reader the S7 round asks", bool(C.triage_reorder_problems(
                dict(base_row, **extra))), bad)

        # K-R6-5: the blocker is not red in this run -> a `triage:` reason; the Then is not shown as waiting for it
        tc3(root, **waiting(3, 4, blocker="TC-009"))
        triage, report, manifest = both(root)
        reasons = [r for r in CD.triage_reasons(root) if "TC-009" in r]
        check("K-R6-5: a blocker nothing red answers for -> ONE `triage:` reason (-> no)", len(reasons) == 1 and all(
            r.startswith("triage:") and "no triage row of the current run is red for it" in r for r in reasons), str(reasons))
        check_eq("K-R6-5: ... and the Thens are not shown as waiting for it", C.then_remainders(manifest, None, BLOCKED, triage, report), [])
        # the TC-002 row is the blocker: when its row is not bound to the current failure it is not red either
        tc3(root, **waiting(3, 4))
        triage, report, manifest = both(root)
        triage["triage"][0]["attempt_id"] = "old-attempt"
        check("K-R6-5: the blocker's row belongs to another attempt -> not red now",
              any("no triage row of the current run is red" in p
                  for p in C.triage_blocked_problems(triage["triage"][1], root, triage["triage"], report)))

        # K-R6-6: a row of another attempt is not read
        tc3(root, attempt_id="a-not-this-run", **waiting(3, 4))
        triage, report, manifest = both(root)
        check_eq("K-R6-6: the row names another attempt -> its Thens are not this run's",
                 C.then_remainders(manifest, None, BLOCKED, triage, report), [])
        check_eq("K-R6-6: ... and no 'Left with you' record", CD.blocked_records(root), [])
        tc3(root, attempt_id=ATTEMPT)

        # K-R6-11: the manifest keeps `blocked_by_check` for Then 2 of TC-003, which ran and failed
        stale = copy.deepcopy(manifest)
        stale["then_bindings"] = [b for b in stale["then_bindings"] if not (b["case"] == "TC-003" and b["then"] == 2)]
        stale["then_bindings"].append({"case": "TC-003", "then": 2, "instance_id": IID3, "status": "unresolved",
                                       "reason": "blocked_by_check", "blocking_check": "TC-002", "detail": "behind TC-002"})
        check_eq("K-R6-11: without the report the manifest's row is a remainder as it was",
                 [r["then"] for r in C.then_remainders(stale, None, BLOCKED)], [2])
        triage, report, _m = both(root)
        check_eq("K-R6-11: with the triage and the report the row of the executed red Then is left out",
                 [r["then"] for r in C.then_remainders(stale, None, BLOCKED, triage, report)], [3, 4])
        write(root, "automation-manifest.json", stale)
        reasons = [r for r in CD.triage_reasons(root) if "behind a check, but it ran and failed" in r]
        check("K-R6-11: the delivery check names it as a factory record (a `triage:` reason)",
              len(reasons) == 1 and "Then 2 of TC-003" in reasons[0], str(reasons))
        check_eq("K-R6-11: ... and 'Left with you' does not show it beside the failure",
                 sorted(r["then"] for r in CD.blocked_records(root)), [3, 4])
        write(root, "automation-manifest.json", manifest)

        # K-R6-12: a `diagnostic` block -> the evidence path reaches the line
        (root / "evidence").mkdir(exist_ok=True)
        (root / EVIDENCE).write_text('{"status": "passed"}\n', encoding="utf-8")
        block = {"evidence": EVIDENCE, "observed": "without the red assert Thens 3 and 4 held",
                 "thens": [{"then": 3, "outcome": "held"}, {"then": 4, "outcome": "red"}]}
        tc3(root, diagnostic=block, **waiting(3, 4))
        records = CD.blocked_records(root)
        check("K-R6-12: the evidence path is in the line of Then 3 (held)",
              f"showed Then 3 held ({EVIDENCE})" in records[0]["how"], records[0]["how"])
        check("K-R6-12: ... and Then 4 (red)", f"showed Then 4 red ({EVIDENCE})" in records[1]["how"], records[1]["how"])
        tc3(root, diagnostic={"evidence": EVIDENCE, "observed": "x"}, **waiting(3))
        check_in("K-R6-12: a block naming no outcome for the Then still gives the path", f"was made ({EVIDENCE})",
                 CD.blocked_records(root)[0]["how"])
        check_eq("K-R6-12: no block -> no words (the ledger sentence is what it was)", L.diagnostic_words({"then": 3}), "")
        tc3(root, diagnostic={"evidence": "evidence/not-a-diagnostic.json", "observed": "x"}, **waiting(3))
        check("K-R6-12: a malformed block is a `triage:` reason", any(
            r.startswith("triage:") and "diagnostic" in r for r in CD.triage_reasons(root)), str(CD.triage_reasons(root)))

        # K-R6-S (seam): the triage by the new 2c + a draft of TC-002 only -> the claim is green, the line is TC-002's
        tc3(root, **waiting(3, 4))
        for name in sorted((root / "work" / "bug-drafts").glob("*.json")):
            draft = json.loads(name.read_text(encoding="utf-8"))
            if draft.get("case") == "TC-003":
                name.unlink()
            else:
                draft["cases"] = ["TC-002", "TC-003"]
                draft["triage_ref"] = {"instance_id": IID2, "attempt_id": ATTEMPT}
                name.write_text(json.dumps(draft), encoding="utf-8")
        import handoff_check as HC

        class Art:
            def __init__(self, base: Path):
                self.root = base

            def exists(self, rel: str) -> bool:
                return (self.root / rel).exists()

        ok, why = HC._claim_bug_has_a_draft(Art(root))
        check("K-R6-S: the claim `no_bug_reaches_the_gate_without_a_draft...` is green", ok is True, why)
        words = [r["how"] for r in CD.blocked_records(root)]
        check_eq("K-R6-S: 'Left with you' names TC-003 Thens 3 and 4 behind TC-002",
                 [(r["case"], r["then"], r["blocking_check"]) for r in CD.blocked_records(root)],
                 [("TC-003", 3, "TC-002"), ("TC-003", 4, "TC-002")])
        check("K-R6-S: ... in the author's words", all("TC-002" in w for w in words), str(words))
        # the same triage with the draft of TC-003 left in place -> the claim refuses (duplicate)
        (root / "work" / "bug-drafts" / "dup.json").write_text(json.dumps(
            {"title": "dup", "case": "TC-003", "triage_ref": {"instance_id": IID3, "attempt_id": ATTEMPT}}), encoding="utf-8")
        ok, why = HC._claim_bug_has_a_draft(Art(root))
        check("K-R6-S: a second draft on the blocked row -> the claim refuses with the duplicate named",
              ok is False and "duplicates" in why, why)
    finally:
        cleanup(root.parent)
    finish("test_triage_blocked")


if __name__ == "__main__":
    main()
