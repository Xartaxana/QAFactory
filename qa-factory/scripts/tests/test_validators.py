"""validate_artifacts.py — one good and one bad case for every C0 rule.

Every case runs against a real temp project (CLAUDE_PROJECT_DIR pointed at it, the good
fixture installed as QA-1 and the bad one as QA-2), because the validator dispatches on the
path shape `<project>/qa-factory/artifacts/<TICKET>/...` — a rule proven on a loose file
would not prove the hook.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BAD, GOOD, TEST_CODE, check, check_eq, check_in, check_not_in, cleanup, finish, install_artifacts,
    run_script, temp_project, use_project,
)

ROOT = temp_project("qa-factory-validators-")
use_project(ROOT)
# t-227: the cmp2 case ids (`TP1-15045_TC_015`) are this project's form, beside the default `TC-001`.
_cfg_path = ROOT / "qa-factory" / "config.json"
_cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
_cfg["case_id_form"] = "{ticket}_TC_{nnn}"
_cfg_path.write_text(json.dumps(_cfg, indent=2), encoding="utf-8")
OP = Path(__file__).resolve().parent / "fixtures" / "oracle-provenance"  # the cmp2 artifacts, verbatim

import validate_artifacts as V  # noqa: E402  (imported AFTER the project root is set)
import contract as C  # noqa: E402

C_ARTIFACT = C.artifact

Q1 = install_artifacts(ROOT, GOOD, "QA-1")
Q2 = install_artifacts(ROOT, BAD, "QA-2")
Q3 = install_artifacts(ROOT, GOOD, "QA-3")  # scratch: one good artifact mutated per case
(ROOT / "tests").mkdir(exist_ok=True)
shutil.copy(GOOD / "work" / "test-cases" / "checkout" / "TC-001.md", ROOT / "tests" / "_case_ref.md")
(ROOT / "tests" / "test_coupon.py").write_text(
    (TEST_CODE / "good_test.py").read_text(encoding="utf-8"), encoding="utf-8")
(ROOT / "tests" / "test_cart_banner.py").write_text(
    (TEST_CODE / "good_test.py").read_text(encoding="utf-8"), encoding="utf-8")


FRENCH = "Nous avons termin" + chr(233) + " S8 hier."   # a sentence naming S8 in another language, kept ASCII in the source


def errors_for(path: Path) -> list:
    return V.collect_errors(Path(path))


def ok(name: str, path: Path) -> None:
    found = errors_for(path)
    check(f"GOOD {name}", not found, "\n".join(found))


def rejects(name: str, path: Path, needle: str) -> None:
    found = errors_for(path)
    check_in(f"BAD  {name}", needle, found)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rel(name: str) -> str:
    """Where an artifact lives inside a story folder: the four human documents at the top,
    everything the roles exchange under work/."""
    return name if (GOOD / name).exists() else f"work/{name}"


def variant(name: str, old: str, new: str) -> Path:
    """The good artifact `name` with one substring swapped, written into the scratch ticket
    under its canonical filename (the validator dispatches on the name, so a renamed copy
    would prove nothing). Siblings in QA-3 stay good, so only the swap is under test."""
    name = rel(name)
    text = (GOOD / name).read_text(encoding="utf-8")
    assert old in text, f"fixture drift: {old!r} not in {name}"
    return write(Q3 / name, text.replace(old, new, 1))


def restore(name: str) -> None:
    name = rel(name)
    (Q3 / name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(GOOD / name, Q3 / name)


def main() -> None:
    try:
        # --- rule: understanding brief -------------------------------------------------------------
        ok("understanding lists every register requirement", Q1 / "understanding.md")
        rejects("understanding omitting a requirement",
                variant("understanding.md",
                        "- R-2 — the cart total after a coupon matches the recalculated value, read from the order\n",
                        ""),
                "appear in no 'What we verify'")
        rejects("understanding over 40 lines",
                write(Q3 / "understanding.md", (GOOD / "understanding.md").read_text(encoding="utf-8")
                      + "\n" + "\n".join(f"- filler line {i}" for i in range(40))),
                "> 40")
        rejects("understanding missing a section",
                variant("understanding.md", "## What else the change may touch", "## Extras"),
                "## What else the change may touch' is missing")
        restore("understanding.md")

        # --- rule: test report ------------------------------------------------------------
        ok("test-report quoting the generated ledger", Q1 / "test-report.md")
        rejects("test-report with a hand-written ledger", Q2 / "test-report.md",
                "section 1 is not the table ledger.py generated")
        rejects("test-report contradicting delivery_ready", Q2 / "test-report.md",
                "while ledger.json says")
        # K-C1 (B-407 C, F-8, FR-12): the stage-done refusal became a note on the PRESENCE of a stage id. The
        # report that says "S8 is complete" while pipeline.json has S8 pending is no longer an error, and a
        # sentence in another language is noted the same way (no phrase list over the author's words).
        check_not_in("K-C1: a report calling a pending stage complete is no longer an ERROR", "calls S8 complete",
                     " | ".join(errors_for(Q2 / "test-report.md")))
        check_eq("K-C1: ... it is ONE note naming the file, the stage and its status, and leaving the judgment to the author",
                 V.collect_notes(Q2 / "test-report.md"),
                 ["test-report.md names S8 while pipeline.json has it 'pending': if a sentence calls it finished, "
                  "correct it; whether it does is yours to judge."])
        # a story-shaped fixture: Q2's pipeline holds S7 running, S8 and S9 pending, everything before done
        report_at = Q2 / "test-report.md"
        notes_of = lambda text: V.stage_notes(report_at, text)  # noqa: E731
        check_eq("K-C1 (E-C1): a French sentence naming S8 is noted - the trigger is the id, not the wording",
                 notes_of(FRENCH),
                 ["test-report.md names S8 while pipeline.json has it 'pending': if a sentence calls it finished, "
                  "correct it; whether it does is yours to judge."])
        check_eq("K-C1 (E-C1): a sentence that never says finished is noted too (presence, not meaning)",
                 len(notes_of("S9 will follow.")), 1)
        check_eq("K-C1 (E-C3): a RUNNING stage is never named (the report is written during it)",
                 notes_of("S7 is complete."), [])
        check_eq("K-C1 (E-C3): a DONE stage is never named", notes_of("S5 is done, S0 finished, S6 complete."), [])
        check_eq("K-C1: one line per stage, in the order the report names them, deduplicated",
                 [n.split()[2] for n in notes_of("S9 S8 S9 S8, S7 S9")], ["S9", "S8"])
        check_eq("K-C1: a token that merely contains a stage id is not one (S10, AS8, S8x, S_8)",
                 notes_of("S10 AS8 S8x s8 S_8"), [])
        check_eq("K-C1: ... and a report with no stage id has no note", notes_of("Everything is fine."), [])
        halted = json.loads((GOOD / "pipeline.json").read_text(encoding="utf-8"))
        write(Q3 / "pipeline.json", json.dumps({**halted, "stages": {k: v for k, v in halted["stages"].items() if k != "S8"}}))
        check_eq("K-C1: a stage pipeline.json does not hold is never named", V.stage_notes(Q3 / "test-report.md", "S8"), [])
        halted["stages"]["S6"]["status"] = "halted"
        write(Q3 / "pipeline.json", json.dumps(halted))
        check_eq("K-C1: a HALTED stage is named, with its status",
                 V.stage_notes(Q3 / "test-report.md", "S6 finished")[0].split("has it ")[1][:8], "'halted'")
        restore("pipeline.json")
        write(Q3 / "pipeline.json", "{ not json")
        check_eq("K-C1: a pipeline.json that cannot be read says nothing (its own file refuses it) and never raises",
                 V.stage_notes(Q3 / "test-report.md", "S8"), [])
        restore("pipeline.json")
        # the same note reaches the person at both places the spec names: `--check --verbose` and the valid-write hint
        import os
        import subprocess
        proc_env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        pending = json.loads((GOOD / "pipeline.json").read_text(encoding="utf-8"))
        pending["stages"]["S8"]["status"] = "pending"
        write(Q3 / "pipeline.json", json.dumps(pending))
        said = variant("test-report.md", "## Run this yourself", FRENCH + "\n\n## Run this yourself")
        check_eq("K-C1: the report with that sentence passes validation (a note is not an error)", errors_for(said), [])
        quiet = run_script("validate_artifacts.py", "--check", said, env=proc_env)
        loud = run_script("validate_artifacts.py", "--check", said, "--verbose", env=proc_env)
        check_eq("K-C1: `--check` passes and prints no note", (quiet.returncode, "note:" in quiet.stdout), (0, False))
        check_in("K-C1: `--check --verbose` prints it", "note: test-report.md names S8 while pipeline.json has it 'pending'",
                 loud.stdout)
        hook = subprocess.run([sys.executable, "-B", str(Path(V.__file__))], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=proc_env, timeout=300,
                              input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(said)},
                                                "cwd": str(ROOT)}))
        check_in("K-C1: the valid-write hint carries it (the hook exits 0)",
                 "note: test-report.md names S8 while pipeline.json has it 'pending'", hook.stdout)
        check_eq("K-C1: ... and the write is not blocked", hook.returncode, 0)
        pending["stages"]["S8"]["status"] = "running"
        write(Q3 / "pipeline.json", json.dumps(pending))
        check_eq("K-C1 (E-C3): the same report written while S8 RUNS carries no note", V.collect_notes(said), [])
        # E-C2: what a person reads first stays code-checked - the head still refuses on a contradiction
        wrong = said.read_text(encoding="utf-8").replace("`delivery_ready: yes`", "`delivery_ready: no`", 1)
        rejects("K-C1 (E-C2): the delivery_ready head is still REFUSED when it contradicts ledger.json",
                write(Q3 / "test-report.md", wrong), "while ledger.json says")
        restore("pipeline.json")
        restore("test-report.md")
        rejects("test-report over its size cap",
                write(Q3 / "test-report.md",
                      (GOOD / "test-report.md").read_text(encoding="utf-8") + "x" * 7000),
                "> 6144")
        rejects("test-report putting our own tests above the product's problems",
                variant("test-report.md", "## Product problems", "## Our tests and the factory (moved up)"),
                "is missing")
        restore("test-report.md")

        # --- rule: plan dispositions, observables, oracles, anti-patterns --------------------
        ok("test-plan with closed-list dispositions and sourced observables", Q1 / "test-plan.md")
        rejects("a disposition outside the closed list",
                variant("test-plan.md", "`automate` - coverage gap", "`maybe` - we will see"),
                "outside ['automate'")
        rejects("a disposition with no reason",
                variant("test-plan.md",
                        "`automate` - coverage gap on the API contract, deterministic", "`automate`"),
                "with no reason")
        rejects("an observable with no source",
                variant("test-plan.md", "| diff:src/app.py:12 |", "| src/app.py:12 |"),
                "names no source")
        rejects("an oracle outside the grammar",
                variant("test-plan.md", "| requirement:R-1 |", "| because I said so |"),
                "is not from ['requirement:'")
        # The level is what the board groups the pyramid by; before 0.3.0 it was read from
        # nothing and inferred from the substring "ui" in a test name (TP2-2290).
        rejects("a level outside the closed list",
                variant("test-plan.md", "| new | api |", "| new | backend |"),
                "outside ['unit', 'component'")
        rejects("`automate` with no level",
                variant("test-plan.md", "| new | api |", "| new |  |"),
                "with no level")
        ok("a component level is accepted",
           variant("test-plan.md", "| new | api |", "| new | component |"))
        restore("test-plan.md")
        rejects("`automate` on a visibility-only row", Q2 / "test-plan.md",
                "`automate` on a low-value row")
        rejects("new behaviour with a history: oracle", Q2 / "test-plan.md",
                "new behaviour with oracle `history:`")
        rejects("new behaviour observed on current-code", Q2 / "test-plan.md",
                "new behaviour observed on `current-code`")
        restore("test-plan.md")

        # --- rule: manifest completeness and self_fixes --------------------------------------
        ok("a complete automation manifest", Q1 / "work" / "automation-manifest.json")
        manifest = json.loads((GOOD / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        hollow = dict(manifest, tests=[], unresolved=[])
        rejects("an `automate` case in neither tests[] nor unresolved[]",
                write(Q3 / "work" / "automation-manifest.json", json.dumps(hollow)),
                "is in neither tests[] nor unresolved[]")
        bad_reason = dict(manifest, unresolved=[{"case": "TC-009", "reason": "too hard"}])
        rejects("an unresolved reason outside the closed list",
                write(Q3 / "work" / "automation-manifest.json", json.dumps(bad_reason)),
                "unresolved with reason 'too hard'")
        # t-271 D2: `expectation_unconfirmed` is in the contract's closed list, so a whole-case row carrying it is no
        # "outside the closed list" refusal; the reason's own reader (`check_manifest_v0`) accepts it.
        accepted = dict(manifest, unresolved=[{"case": "TC-009", "reason": "expectation_unconfirmed", "question": "Q7"}])
        check_not_in("D2: check_manifest_v0 accepts a whole-case `expectation_unconfirmed` row (the reason is the contract's word)",
                     "unresolved with reason", errors_for(write(Q3 / "work" / "automation-manifest.json", json.dumps(accepted))))
        rejects("a self-fix that dropped a Then line", Q2 / "work" / "automation-manifest.json",
                "dropped the Then line")
        restore("automation-manifest.json")
        ok("a self-fix that kept every Then line", Q1 / "work" / "automation-manifest.json")

        # --- rule: execution_status ----------------------------------------------------------
        ok("a run report with a status from the vocabulary", Q1 / "work" / "run-report.json")
        report = json.loads((GOOD / "work" / "run-report.json").read_text(encoding="utf-8"))
        rejects("an invented execution_status",
                write(Q3 / "work" / "run-report.json", json.dumps(dict(report, execution_status="mostly_fine"))),
                "outside ['passed'")
        rejects("a blocked preflight with a non-blocked status",
                write(Q3 / "work" / "run-report.json", json.dumps(dict(report, env_preflight="blocked"))),
                "one field, one source")
        # --- rule: every results[] row has a name, a status, and a reason for a skip ------------
        # TP2-2290: nine rows reached the board with none of the three. Both field
        # spellings are accepted (`test`/`result` from the contract, `test_id`/`status` from
        # run_suite.py) — what is refused is a row that says nothing.
        base = {"execution_status": "passed", "env_preflight": "pass", "witness": "w",
                "head": "abc1234", "stage": "feature"}

        # These rows are about the SHAPE of a row, so they live in a story folder with no
        # manifest and no plan: with siblings present the coverage rule below would (rightly)
        # object that a two-line synthetic report names none of the story's cases.
        bare = ROOT / "qa-factory" / "artifacts" / "QA-4" / "work"
        bare.mkdir(parents=True, exist_ok=True)

        def report_with(rows, totals=None):
            """A minimal report around `rows`; totals follow the rows unless overridden."""
            if totals is None:
                counted = [str(r.get("status") or r.get("result") or "") for r in rows]
                totals = {"tests": len(rows),
                          "passed": sum(1 for c in counted if c == "passed"),
                          "failures": sum(1 for c in counted if c in ("failed", "fail")),
                          "errors": sum(1 for c in counted if c == "error"),
                          "skipped": sum(1 for c in counted if c == "skipped")}
            return write(bare / "run-report.json",
                         json.dumps(dict(base, results=rows, totals=totals)))

        ok("a row in the run_suite spelling",
           report_with([{"test_id": "t::a", "status": "passed"}]))
        ok("a row in the contract spelling",
           report_with([{"test": "t::a", "result": "passed"}]))
        rejects("a row with no status at all", report_with([{"test_id": "t::a"}]), "has no status")
        rejects("a row nobody can name",
                report_with([{"status": "passed"}]), "neither test_id nor case")
        rejects("an invented row status",
                report_with([{"test_id": "t::a", "status": "mostly_ok"}]), "outside")
        rejects("a skip with no reason",
                report_with([{"test_id": "t::a", "status": "skipped"}]), "skipped with no reason")
        ok("a skip that says why",
           report_with([{"test_id": "t::a", "status": "skipped", "reason": "pending implementation"}]))
        # TP1-14501: three cases chained into one test arrived as one row with
        # case "TC-001/TC-002/TC-003". ledger.py matches a case id by equality, so all
        # three reached the ledger as `not_executed` next to a green run.
        ok("one case per row",
           report_with([{"test_id": "t::a", "status": "passed", "case": "TC-001"}]))
        rejects("three cases in one row's case cell",
                report_with([{"test_id": "t::a", "status": "passed",
                              "case": "TC-001/TC-002/TC-003"}]),
                "names 3 cases")
        rejects("two cases separated by a comma",
                report_with([{"test_id": "t::a", "status": "passed", "case": "TC-001, TC-002"}]),
                "one row per case")
        rejects("totals say two skips and results[] lists one",
                report_with([{"test_id": "t::a", "status": "skipped", "reason": "pending"}],
                            {"tests": 2, "passed": 0, "failures": 0, "errors": 0, "skipped": 2}),
                "results[] lists")
        restore("run-report.json")

        # --- rule: the report accounts for every case S5 automated -------------------------------
        # TP2-2386: the first run-report left out the cases already verified at S5, the
        # hole surfaced two stages later in check_traceability, and fixing it cost a second
        # runner dispatch. Completeness is checkable at write time, inside the runner's own turn.
        ok("a report that names every automated and manual-agent case",
           Q1 / "work" / "run-report.json")
        full = json.loads((GOOD / "work" / "run-report.json").read_text(encoding="utf-8"))
        rejects("an automated case missing from every lane",
                write(Q3 / "work" / "run-report.json", json.dumps(dict(full, results=[]))),
                "TC-001 is automated at S5 but appears in no lane")
        rejects("a manual-agent case missing from every lane",
                write(Q3 / "work" / "run-report.json", json.dumps(dict(full, manual_checks=[]))),
                "TC-002")
        ok("a case that went to skipped instead of a result",
           write(Q3 / "work" / "run-report.json",
                 json.dumps(dict(full, results=[],
                                 skipped=[{"case": "TC-001", "reason": "pending implementation"}]))))
        ok("a case recorded as impossible",
           write(Q3 / "work" / "run-report.json",
                 json.dumps(dict(full, results=[],
                                 impossible=[{"case": "TC-001", "reason": "no delete endpoint"}]))))
        restore("run-report.json")

        # --- t-290: S6 runs in two halves; after the AUTOMATION half the manual rows cannot have a lane yet ---
        # The refusal for every manual-agent row was unsatisfiable at the end of the first half (live S6
        # rehearsal, 02.10: two conductor sessions spent on `finish --not-complete`). The carrier of the half is
        # the one running S6 qa-runner dispatch's `execution_kind` in state/controller.json.
        Q4 = install_artifacts(ROOT, GOOD, "QA-290")   # its own story: a second manual-agent row, a controller state
        write(Q4 / "test-plan.md", (GOOD / "test-plan.md").read_text(encoding="utf-8").replace(
            "`skip` - cosmetic", "`manual-agent` - cosmetic"))
        write(Q4 / "work" / "test-cases" / "checkout" / "TC-003.md",
              (GOOD / "work" / "test-cases" / "checkout" / "TC-002.md").read_text(encoding="utf-8")
              .replace("id: TC-002", "id: TC-003").replace("Plan row: TS-2", "Plan row: TS-3"))
        report4 = Q4 / "work" / "run-report.json"
        no_manual = dict(full, manual_checks=[])

        def half(kind, report, dispatches=None):
            """(errors, notes) of the run-report coverage check with a controller state of one running S6
            qa-runner dispatch of `kind` (None: no kind on it; "absent": no controller.json at all)."""
            state = Q4 / "state" / "controller.json"
            if kind == "absent":
                state.unlink(missing_ok=True)
            else:
                rec = {"stage": "S6", "role": "qa-runner", "status": "running"}
                if kind:
                    rec["execution_kind"] = kind
                write(state, json.dumps({"dispatches": {"S6-qa-runner-1": rec} if dispatches is None else dispatches}))
            write(report4, json.dumps(report))
            errs, notes = [], []
            V.check_phase_json(report4, errs, notes)
            return errs, notes

        errs, notes = half("automation", no_manual)
        check_eq("K-SKIP: the automation half with manual rows pending - no error", errs, [])
        check_eq("K-SKIP: ... and ONE note naming the rows", notes,
                 ["run-report.json: 2 manual-agent rows wait for the manual half: TS-2, TS-3"])
        errs, notes = half("manual", no_manual)
        check("K-MAN: the manual half keeps the refusal for every row without a lane",
              len(errs) == 2 and "TC-002 is `manual-agent` in the plan (TS-2) but appears in no lane" in errs[0]
              and "TC-003" in errs[1] and notes == [], "\n".join(errs + notes))
        errs, notes = half("automation", no_manual, dispatches={})
        check("K-MAN: no running dispatch (a close) keeps the refusal", len(errs) == 2 and notes == [], "\n".join(errs))
        errs, notes = half("automation", no_manual, dispatches={
            "S6-qa-runner-1": {"stage": "S6", "role": "qa-runner", "status": "accepted", "execution_kind": "automation"}})
        check("K-MAN: an accepted automation dispatch is not the one being accepted", len(errs) == 2 and notes == [])
        errs, notes = half("automation", no_manual, dispatches={
            "a": {"stage": "S6", "role": "qa-runner", "status": "running", "execution_kind": "automation"},
            "b": {"stage": "S6", "role": "qa-runner", "status": "running", "execution_kind": "automation"}})
        check("K-MAN: two running runner dispatches - the half is unknown, the refusal stands",
              len(errs) == 2 and notes == [])
        errs, notes = half("automation", no_manual, dispatches={
            "S5-x": {"stage": "S5", "role": "qa-runner", "status": "running", "execution_kind": "automation"}})
        check("K-MAN: a running dispatch of another stage is not the S6 half", len(errs) == 2 and notes == [])
        errs, notes = half(None, no_manual)
        check("K-LEG: a dispatch with no execution_kind (legacy story) - today's refusal, no note",
              len(errs) == 2 and notes == [], "\n".join(errs + notes))
        errs, notes = half("absent", no_manual)
        check("K-LEG: no controller.json at all - today's refusal, no note", len(errs) == 2 and notes == [])
        errs, notes = half("automation", no_manual, dispatches="not a dispatch table")
        check("K-LEG: a controller.json whose dispatches are no table - today's refusal, no note",
              len(errs) == 2 and notes == [])
        errs, notes = half("automation", dict(full, manual_checks=[full["manual_checks"][0]]))
        check_eq("K-MIX: rows with a lane are not listed, the others are (edge 4)", (errs, notes),
                 ([], ["run-report.json: 1 manual-agent rows wait for the manual half: TS-3"]))
        errs, notes = half("automation", dict(full, results=[], manual_checks=[]))
        check("K-MIX: an AUTOMATED case with no lane still refuses in the automation half - exactly one error",
              len(errs) == 1 and "TC-001 is automated at S5 but appears in no lane" in errs[0], "\n".join(errs))
        check_eq("K-MIX: ... and the manual rows are still one note", notes,
                 ["run-report.json: 2 manual-agent rows wait for the manual half: TS-2, TS-3"])
        errs, notes = half("automation", dict(full, manual_checks=[full["manual_checks"][0],
                                                                    dict(full["manual_checks"][0], case="TC-003")]))
        check_eq("K-SKIP control: every row has a lane - no error, no note", (errs, notes), ([], []))

        # --- t-290 follow-up: the manual half goes block by block; a block is asked only for its own cases ---
        Q5 = install_artifacts(ROOT, GOOD, "QA-291")   # four manual-agent rows: TS-2 .. TS-5
        plan5 = (GOOD / "test-plan.md").read_text(encoding="utf-8").replace("`skip` - cosmetic", "`manual-agent` - cosmetic")
        for n in (3, 4, 5):
            if n > 3:
                plan5 = plan5.replace("\n\n## Recommended regression",
                                      f"\n| TS-{n} | extra manual row {n} | R-2 | contract @ total | money | P0 | diff:src/app.py:20 "
                                      f"| requirement:R-2 | `manual-agent` - one-off check | — | api | state verification |"
                                      "\n\n## Recommended regression", 1)
            write(Q5 / "work" / "test-cases" / "checkout" / f"TC-00{n}.md",
                  (GOOD / "work" / "test-cases" / "checkout" / "TC-002.md").read_text(encoding="utf-8")
                  .replace("id: TC-002", f"id: TC-00{n}").replace("Plan row: TS-2", f"Plan row: TS-{n}"))
        write(Q5 / "test-plan.md", plan5)
        report5 = Q5 / "work" / "run-report.json"
        write(report5, json.dumps(no_manual))

        def block5(dispatches):
            write(Q5 / "state" / "controller.json", json.dumps({"dispatches": dispatches}))
            errs, notes = [], []
            V.check_phase_json(report5, errs, notes)
            return errs, notes

        def runner(kind, status="running", cases=None):
            rec = {"stage": "S6", "role": "qa-runner", "status": status, "execution_kind": kind}
            if cases is not None:
                rec["manual_case_ids"] = cases
            return rec

        errs, notes = block5({"S6-qa-runner-2": runner("manual", cases=["TC-002", "TC-003"])})
        check("K-MAN2: a block of 2 of 4 manual rows - its own 2 without a lane are refused",
              len(errs) == 2 and "TC-002 is `manual-agent`" in errs[0] and "TC-003 is `manual-agent`" in errs[1],
              "\n".join(errs))
        check_eq("K-MAN2: ... and the 2 outside it are ONE note", notes,
                 ["run-report.json: 2 manual-agent rows wait for a later block or the close: TS-4, TS-5"])
        write(report5, json.dumps(dict(no_manual, manual_checks=[
            dict(full["manual_checks"][0], case="TC-002"), dict(full["manual_checks"][0], case="TC-003")])))
        errs, notes = block5({"S6-qa-runner-2": runner("manual", cases=["TC-002", "TC-003"])})
        check_eq("K-MAN2: the block delivered its own cases - no error, the other rows are the note",
                 (errs, notes), ([], ["run-report.json: 2 manual-agent rows wait for a later block or the close: TS-4, TS-5"]))
        errs, notes = block5({"S6-qa-runner-2": runner("manual", cases=["TC-002", "TC-003"]),
                              "S6-qa-runner-3": runner("manual", status="accepted", cases=["TC-004"])})
        check("K-MAN2: an accepted block beside the running one changes nothing", len(errs) == 0 and len(notes) == 1)
        errs, notes = block5({"S6-qa-runner-2": runner("manual")})
        check("K-MAN: a manual dispatch naming no cases cannot be scoped - every row refused, no note",
              len(errs) == 2 and notes == [], "\n".join(errs))
        errs, notes = block5({"S6-qa-runner-2": runner("manual", cases=["TC-004"])})
        check("K-MAN: a manual dispatch whose own row has no lane is refused",
              any("TC-004 is `manual-agent`" in e for e in errs) and len(errs) == 1, "\n".join(errs))
        write(report5, json.dumps(dict(full, results=[], manual_checks=[full["manual_checks"][0]])))
        errs, notes = block5({"S6-qa-runner-2": runner("manual", cases=["TC-002"])})
        check("K-MAN2: an AUTOMATED case with no lane still refuses in a manual block (exactly one error)",
              len(errs) == 1 and "TC-001 is automated at S5" in errs[0], "\n".join(errs))
        write(report5, json.dumps(no_manual))
        errs, notes = block5({"S6-qa-runner-2": runner("manual", status="accepted", cases=["TC-002"])})
        check("K-CLOSE: no running dispatch - every manual-agent row is refused as today",
              len(errs) == 4 and notes == [], "\n".join(errs))
        errs, notes = block5({})
        check("K-CLOSE: no dispatches at all - the same", len(errs) == 4 and notes == [])

        # --- rule: the TC marker exists in the test file, not only in the manifest ---------------
        # TP2-2386: five tests were written, run and only then rejected for a missing
        # marker — metadata, checked after the expensive part. The file is right there.
        ok("a manifest whose marker is in the test file", Q1 / "work" / "automation-manifest.json")
        rejects("a marker no test file carries",
                variant("automation-manifest.json", '"marker": "TC-001"', '"marker": "TC-404"'),
                "does not contain it")
        restore("automation-manifest.json")

        # --- rule: related[] is what the ticket named, with a source ----------------------------
        manifest = json.loads((GOOD / "work" / "context-manifest.json").read_text(encoding="utf-8"))

        def manifest_with(related):
            return write(Q3 / "work" / "context-manifest.json",
                         json.dumps(dict(manifest, related=related)))

        ok("a related ticket with a kind and a source",
           manifest_with([{"key": "QA-7", "kind": "blocker", "source": "a comment"}]))
        rejects("a related ticket with no source",
                manifest_with([{"key": "QA-7", "kind": "blocker"}]), "has no 'source'")
        rejects("an invented related kind",
                manifest_with([{"key": "QA-7", "kind": "sibling", "source": "the epic"}]), "outside")

        # --- rule: a code review has three answers, and the middle one carries notes ------------
        # QA-EXAMPLE: a missing ticket marker could only be said as `rejected`, and
        # `rejected` means a full second round -- rubric, detectors, arch-check, re-run.
        man = json.loads(C_ARTIFACT(Q3, "automation-manifest.json").read_text(encoding="utf-8"))             if C_ARTIFACT(Q3, "automation-manifest.json").exists() else {}
        if man.get("tests"):
            def manifest_verdict(verdict, notes=None):
                tests = [dict(man["tests"][0])]
                tests[0]["critic_verdict"] = verdict
                if notes is not None:
                    tests[0]["fix_notes"] = notes
                return write(C_ARTIFACT(Q3, "automation-manifest.json"),
                             json.dumps(dict(man, tests=tests)))

            ok("approved needs no notes", manifest_verdict("approved"))
            ok("approved_with_fixes carries its notes",
               manifest_verdict("approved_with_fixes", ["add the @case marker to the docstring"]))
            rejects("approved_with_fixes with no notes",
                    manifest_verdict("approved_with_fixes", []), "no fix_notes")
            rejects("notes beside a rejection",
                    manifest_verdict("rejected", ["tidy the name"]), "belong to approved_with_fixes")
            rejects("an invented verdict", manifest_verdict("looks_fine"), "outside")
            # D-0013 / FR-35: "the critic could not verify it" is its own word, in the vocabulary;
            # the vocabulary is exact, so a differently-cased spelling is still an invented verdict.
            ok("unverified is a verdict of its own", manifest_verdict("unverified"))
            rejects("a capitalised unverified is not the vocabulary's", manifest_verdict("Unverified"), "outside")
            restore("automation-manifest.json")

        # --- rule: S2 builds on S1's evidence, and says so when it did not ---------------------
        # QA-EXAMPLE: the requirements tester re-read the implementation although the
        # manifest carried 24 grounded observables, and left no trace of the gap.
        reg_path = C_ARTIFACT(Q3, "requirements-register.md")
        reg_text = reg_path.read_text(encoding="utf-8") if reg_path.exists() else ""
        if reg_text:
            man = json.loads((Q3 / "work" / "context-manifest.json").read_text(encoding="utf-8"))
            known = [o.get("path") for o in man.get("observables") or [] if o.get("path")]
            if known:
                unknown_row = reg_text.replace(f"diff:{known[0]}", "diff:src/never/seen.py:9", 1)
                changed = unknown_row != reg_text
                if changed:
                    rejects("a register observable the manifest never recorded",
                            write(reg_path, unknown_row), "never recorded")
                    named = unknown_row.replace(
                        "## Contradiction matrix",
                        "manifest_gap: src/never/seen.py - needed the guard's condition, "
                        "the manifest stopped at the router\n\n## Contradiction matrix", 1)
                    ok("the same path, named as a manifest_gap", write(reg_path, named))
                    restore("requirements-register.md")

        # --- rule: one implementations[] entry per repository -----------------------------------
        # QA-EXAMPLE was split across a backend MR and a frontend MR, and a single
        # `implementation` object can hold only one of them.
        def manifest_impl(rows, top=None):
            data = dict(manifest, implementations=rows)
            if top is not None:
                data["implementation"] = top
            return write(Q3 / "work" / "context-manifest.json", json.dumps(data))

        backend = {"repo": "testproject1", "source": "diff", "mr": "!4214",
                   "diff_path": "work/impl-diff-testproject1.txt"}
        frontend = {"repo": "testproject1-ui", "source": "diff", "mr": "!1881",
                    "diff_path": "work/impl-diff-testproject1-ui.txt"}
        ok("two repositories, one entry each", manifest_impl([backend, frontend], backend))
        rejects("an entry with no repo",
                manifest_impl([dict(backend, repo=""), frontend], backend), "has no 'repo'")
        rejects("the same repository twice",
                manifest_impl([backend, dict(frontend, repo="testproject1")], backend), "twice")
        rejects("an invented implementation source",
                manifest_impl([dict(backend, source="guessed")], dict(backend, source="guessed")),
                "outside")
        rejects("the summary disagreeing with the first entry",
                manifest_impl([backend, frontend], dict(backend, source="current-code")),
                "disagrees with implementations[0]")
        restore("context-manifest.json")

        # --- rule: FLAKY evidence ---------------------------------------------------------------
        ok("a triage with no failures to explain", Q1 / "work" / "triage.json")
        rejects("a FLAKY verdict with no re-runs", Q2 / "work" / "triage.json", "FLAKY with reruns=None")
        rejects("a FLAKY verdict with no mechanism", Q2 / "work" / "triage.json", "FLAKY without a mechanism")
        rejects("a FLAKY verdict with no fix_result", Q2 / "work" / "triage.json", "FLAKY with no fix_result")
        ok("a FLAKY verdict with all three",
           write(Q3 / "work" / "triage.json", json.dumps({"triage": [{
               "test": "tests/test_coupon.py::test_cap_rejected", "verdict": "FLAKY",
               "evidence": "evidence/reruns.json", "mechanism": "timing", "reruns": 5,
               "fix_rounds": 1, "fix_result": "fixed"}]})))
        rejects("a verdict outside the matrix",
                write(Q3 / "work" / "triage.json", json.dumps({"triage": [{
                    "test": "t", "verdict": "PROBABLY_FINE", "evidence": "e"}]})),
                "outside ['APP_BUG'")
        restore("triage.json")

        # --- rule: register observables ---------------------------------------------------------
        ok("a register whose observables name their source", Q1 / "work" / "requirements-register.md")
        rejects("a register observable with no source",
                variant("requirements-register.md", "| diff:src/app.py:12 |", "| src/app.py:12 |"),
                "observable 'src/app.py:12' names no source")
        restore("requirements-register.md")

        # --- rule: test-code detectors ------------------------------------------------------------
        tests_dir = ROOT / "tests"
        ok("a test that asserts through an independent channel",
           write(tests_dir / "test_good.py", (TEST_CODE / "good_test.py").read_text(encoding="utf-8")))
        # X7-2: `check_test_code` is cut - a retry marker, a broad status set and a skip marker in test code are the code critic's
        # to judge (the rubric, CRR 2, 3, 8), not a refusal on write. Each of these files used to be refused; none is now.
        for name, fixture in (("test_retry.py", "bad_retry_test.py"), ("test_broad.py", "bad_broad_status_test.py"),
                              ("test_skip.py", "bad_skip_test.py")):
            ok(f"X7-2: {fixture} is no longer refused on write (the markers are the critic's to judge)",
               write(tests_dir / name, (TEST_CODE / fixture).read_text(encoding="utf-8")))
        ok("a broad status line that names its open question",
           write(tests_dir / "test_broad_door.py", (TEST_CODE / "broad_status_door_test.py").read_text(encoding="utf-8")))
        ok("a red_lock file may carry xfail — it declares itself",
           write(tests_dir / "test_red_lock.py", (TEST_CODE / "red_lock_test.py").read_text(encoding="utf-8")))
        outside = ROOT / "docs"
        outside.mkdir(exist_ok=True)
        ok("a file outside tests_root is not test code",
           write(outside / "test_notes.py", (TEST_CODE / "bad_retry_test.py").read_text(encoding="utf-8")))

        # --- K-C5 / K-C7 (B-407 C, C3): "is this test code" is the ONE recognizer (`test_files`, consumer test_code) --
        qa = ROOT / "qa"
        skip_text = (TEST_CODE / "bad_skip_test.py").read_text(encoding="utf-8")
        qa_cfg = {"tests_root": "qa"}

        def code_errors(rel_path: str, text: str = skip_text, cfg: dict = qa_cfg) -> list:
            return V.collect_errors(write(ROOT / rel_path, text), cfg)

        check_eq("K-C5: with tests_root `qa`, a name that is a test (qa/test_login.py) is test code, and its skip is no longer refused (X7-2)",
                 (V.is_test_code(qa / "test_login.py", qa_cfg), code_errors("qa/test_login.py")), (True, []))
        check_eq("K-C5 (F-3): qa/helpers/latest.py is NOT test code (`test` inside `latest` no longer counts) - nothing runs on it",
                 code_errors("qa/helpers/latest.py"), [])
        check_eq("K-C5: ... is_test_code says so directly", V.is_test_code(qa / "helpers" / "latest.py", qa_cfg), False)
        check_eq("K-C5: qa/tests/LoginTest.java is test code (a CamelCase test class, folder `tests`)",
                 V.is_test_code(write(qa / "tests" / "LoginTest.java", "class LoginTest {}\n"), qa_cfg), True)
        check_eq("K-C5: qa/tests/helpers/latest.py IS test code (the folder `tests`)",
                 V.is_test_code(write(qa / "tests" / "helpers" / "latest.py", skip_text), qa_cfg), True)
        check_eq("K-C5: a CamelCase test class outside any test folder is test code by its name (qa/LoginTests.cs)",
                 V.is_test_code(write(qa / "LoginTests.cs", "public void T() {}\n"), qa_cfg), True)
        check_eq("K-C5: a file that is not code at all is never test code (qa/tests/notes.txt is not read as a test)",
                 V.is_test_code(write(qa / "tests" / "notes.txt", skip_text), qa_cfg), False)
        check_eq("K-C5: a test file outside tests_root is not test code (docs/test_notes.py)",
                 V.is_test_code(ROOT / "docs" / "test_notes.py", qa_cfg), False)
        check_eq("K-C5: no tests_root in the config - nothing is test code", V.is_test_code(qa / "test_login.py", {}), False)
        # K-C7 - the Lead's decision on the t-557 F6, named so the critic can contest it (FR-18/FR-58): a bare
        # conftest.py holds fixtures, not tests, and a `pytest.skip(` in a fixture is an environment gate.
        check_eq("K-C7: a bare conftest.py under tests_root is NOT test code (it holds fixtures)",
                 code_errors("qa/conftest.py"), [])
        check_eq("K-C7: ... and qa/tests/conftest.py is test code by its FOLDER (the decision names the bare file only)",
                 V.is_test_code(write(qa / "tests" / "conftest.py", skip_text), qa_cfg), True)
        # E-5 (cut by X7-2): the skip markers of Jest/Mocha, NUnit/MSTest and Go were refused here; none is - the code critic reads them.
        check_eq("X7-2: a skip in a test file of another language is no longer refused on write",
                 [code_errors(rel, text) for rel, text in (("qa/tests/login.spec.ts", "it.skip('logs in', () => {});\n"),
                                                           ("qa/tests/LoginTests.cs", "[Test]\n[Ignore]\npublic void Logs_in() {}\n"),
                                                           ("qa/tests/login_test.go", "func TestLogin(t *testing.T) {\n\tt.Skip(\"no stand\")\n}\n"))],
                 [[], [], []])
        # K-C8 (critic t-562 F1, FR-59): the usual names cannot be read -> the extension FLOOR decides, never "no detectors"
        import test_locations as TL
        real_markers = TL.markers
        TL.markers = lambda: ({}, "missing, unreadable or empty")
        try:
            del V.ORACLE_NOTES[:]
            check_eq("K-C8: ... a file under tests_root with a floor extension is test code", V.is_test_code(qa / "test_login.py", qa_cfg), True)
            check_eq("K-C8: qa/README.md (not in the floor) is not test code", V.is_test_code(write(qa / "README.md", skip_text), qa_cfg), False)
            check_eq("K-C8: ... and exactly ONE note names the unreadable markers and the floor", len(V.ORACLE_NOTES), 1)
            check_in("K-C8: ... naming the file and the floor", "test-path-markers.json could not be read", V.ORACLE_NOTES[0])
            check_in("K-C8: ... and an extension of the floor", ".java", V.ORACLE_NOTES[0])
        finally:
            TL.markers = real_markers
            del V.ORACLE_NOTES[:]

        # --- K-C2 (B-407 C, E-C4/E-C7): a self-fix may only OVER-refuse; the assert lines are ONE table ----------------
        ADV = ["Assert.Equal(200, r.Status);", "assertEquals(a, b);", "x.Should().Be(3);", "expect(page).toHaveURL(u)",
               "require.NoError(t, err)", "assert r.status_code == 200"]
        scratch = ROOT / "scratch-detectors"
        scratch.mkdir(exist_ok=True)
        shipped_doc = json.loads(V.AD.DETECTORS_FILE.read_text(encoding="utf-8"))
        bare_doc = {k: v for k, v in shipped_doc.items() if k not in ("assert_lines", "assertion_probes")}
        worlds = {   # name -> file text, or None for the shipped table (key present)
            "key present": None,
            "key dropped, an older copy of the references (no assertion_probes either)": json.dumps(bare_doc),
            "key dropped, assertion_probes there": json.dumps({k: v for k, v in shipped_doc.items() if k != "assert_lines"}),
            "key malformed (a pattern that does not compile)": json.dumps(dict(shipped_doc, assert_lines=["(?i)assert", "[open"])),
            "key empty": json.dumps(dict(shipped_doc, assert_lines=[])),
            "key not a list": json.dumps(dict(shipped_doc, assert_lines="assert")),
            "file not JSON": "{ not json",
        }

        def self_fix_errors(before: str, after: str, world: str | None) -> list:
            data = {"self_fixes": [{"test": "t", "what": "w", "why_test_defect": "y", "evidence": "e",
                                    "before": before, "after": after}]}
            errs, old = [], os.environ.get(V.AD.ENV_FILE)
            try:
                if world is None:
                    os.environ.pop(V.AD.ENV_FILE, None)
                else:
                    os.environ[V.AD.ENV_FILE] = world
                V.check_self_fixes(Path("automation-manifest.json"), data, errs)
            finally:
                if old is None:
                    os.environ.pop(V.AD.ENV_FILE, None)
                else:
                    os.environ[V.AD.ENV_FILE] = old
            return errs

        for label, text in worlds.items():
            where = None
            if text is not None:
                where = str(write(scratch / "detectors.json", text))
            del V.ORACLE_NOTES[:]
            refused = [line for line in ADV if any("dropped the Then line" in e
                                                   for e in self_fix_errors(line + "\nx = 1", "x = 1", where))]
            check_eq(f"K-C2 [{label}]: every adversarial assertion line dropped from `after` is refused", refused, ADV)
            del V.ORACLE_NOTES[:]
            self_fix_errors("assert a == 1", "x = 1", where)
            if text is None:
                check_eq(f"K-C2 [{label}]: the shipped table says nothing", V.ORACLE_NOTES, [])
            else:
                check_eq(f"K-C2 [{label}]: the floor is used and ONE ORACLE_NOTES line names the problem", len(V.ORACLE_NOTES), 1)
                check_in(f"K-C2 [{label}]: ... naming the key's file", "detectors.json", V.ORACLE_NOTES[0])
            check_eq(f"K-C2 control [{label}]: a dropped line that asserts nothing is not refused",
                     self_fix_errors("x = compute()\nassert a == 1", "assert a == 1", where), [])
            check_eq(f"K-C2 control [{label}]: an assertion that is kept is not refused",
                     self_fix_errors("expect(page).toHaveURL(u)\nx = 1", "expect(page).toHaveURL(u)", where), [])
        del V.ORACLE_NOTES[:]
        check_eq("K-C2: a file that cannot be found is the same unreadable world (the floor, never no check)",
                 len(self_fix_errors("assertEquals(a, b)", "x = 1", str(scratch / "nowhere.json"))), 1)
        del V.ORACLE_NOTES[:]
        V.check_self_fixes(Path("automation-manifest.json"), {"self_fixes": []}, [])
        check_eq("K-C2: a manifest with no self_fixes reads no table and says nothing", V.ORACLE_NOTES, [])
        # the shipped table is a SUPERSET of the old `ASSERT_LINE_RE` (today's lines stay caught)
        import re as _re
        old_rx = _re.compile(r"\b(assert|expect\(|should|assertThat|verify\(|assert_that)\b")
        shipped_rx = V.assert_line_regexes(Path("m.json"))
        samples = ["assert x == 1", "    expect(a)", "r.should be_ok", "assertThat(a).isTrue()", "verify(mock)", "assert_that(x, y)",
                   "x.should.equal(3)", "self.assert_that(a)", "should_be(1)", "ok = verify(a)"]
        check_eq("K-C2: every sample line the old regex caught is caught by the shipped table",
                 [s for s in samples if old_rx.search(s) and not any(rx.search(s) for rx in shipped_rx)], [])
        check("K-C2: ... and the old regex caught most of them (the samples are not vacuous)",
              sum(1 for s in samples if old_rx.search(s)) >= 6)
        check("K-C2: the heads of `assertion_probes` are in the union (Assert.NotEqual, assertNotNull)",
              all(any(rx.search(s) for rx in shipped_rx) for s in ("Assert.NotEqual(a, b)", "assertNotNull(x)")))
        # E-C7: the ONE reader. The shipped key and the code floor are the same six patterns (one source of truth to
        # keep in step), the accessor loads the document itself, and its three refusals are the module's typed ones.
        check_eq("E-C7: the floor in assertion_detectors.py is exactly the shipped `assert_lines`",
                 list(V.AD.ASSERT_LINE_FLOOR), V.AD.assert_line_patterns())
        check_eq("E-C7: six patterns", len(V.AD.assert_line_patterns()), 6)
        for label, text, kind in (("a file that is not JSON", "{ not json", "unreadable"),
                                  ("a document with no `assert_lines`", json.dumps(bare_doc), "absent"),
                                  ("a malformed key", json.dumps(dict(shipped_doc, assert_lines=["[open"])), "malformed"),
                                  ("an empty list", json.dumps(dict(shipped_doc, assert_lines=[])), "malformed"),
                                  ("a list holding a non-string", json.dumps(dict(shipped_doc, assert_lines=["a", 3])), "malformed")):
            try:
                V.AD.assert_line_patterns(write(scratch / "own.json", text))
                got = "no error"
            except V.AD.DetectorsError as exc:
                got = exc.kind
            check_eq(f"E-C7: {label} is the typed refusal `{kind}`, never a shorter list", got, kind)
        try:
            V.AD.shape_patterns("sleep", scratch / "nowhere.json")
            got = "no error"
        except V.AD.DetectorsError as exc:
            got = exc.kind
        check_eq("E-C7: a file that does not exist is `unreadable`", got, "unreadable")
        check_eq("E-C7: the accessor reads another key the same way (`sleep` holds today's three first)",
                 V.AD.shape_patterns("sleep")[:3], ["time\\.sleep\\(", "Thread\\.sleep", "sleep\\(\\d"])
        try:
            V.AD.assertion_heads(shipped_doc)
            got = "no error"
        except ValueError:
            got = "refused"
        check_eq("E-C7 (t-551 F6): assertion_heads refuses the raw document - check_self_fixes calls it with no argument", got, "refused")

        # --- rule: pipeline.json, the file stage_guard reads on every dispatch ----------------------
        ok("a pipeline with stages from the model", Q1 / "pipeline.json")
        pipeline = json.loads((GOOD / "pipeline.json").read_text(encoding="utf-8"))
        rejects("a stage status outside the four",
                write(Q3 / "pipeline.json", json.dumps(
                    {**pipeline, "stages": {**pipeline["stages"], "S4": {"status": "nearly"}}})),
                "outside ['pending'")
        rejects("a stage the model does not know",
                write(Q3 / "pipeline.json", json.dumps(
                    {**pipeline, "stages": {**pipeline["stages"], "S12": {"status": "done"}}})),
                "not in references/stages.json")
        rejects("a pipeline with no gates block",
                write(Q3 / "pipeline.json", json.dumps(
                    {k: v for k, v in pipeline.items() if k != "gates"})),
                "required key 'gates' is missing")
        restore("pipeline.json")

        # --- rule: config schema_version -----------------------------------------------------------
        cfg_path = ROOT / "qa-factory" / "config.json"
        ok("config.json with the required schema_version", cfg_path)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        rejects("config.json with a stale schema_version",
                write(cfg_path, json.dumps(dict(cfg, schema_version=0))), "this plugin requires 1")
        write(cfg_path, json.dumps(cfg))

        # Reused developer tests need no comment-only TC marker edits.
        import hashlib
        trace_path = Q3 / "work" / "automation-manifest.json"
        original_trace = trace_path.read_bytes()
        trace_data = json.loads(original_trace)
        reused = trace_data["tests"][0]
        reused.pop("marker", None)
        reused["case_version_links"] = [{"case_id": "TC-001", "case_version": "v1"}]
        reused["trace_binding"] = {"selector": "tests/test_coupon.py::test_coupon",
                                   "assertion_refs": ["tests/test_coupon.py:10"],
                                   "test_content_sha": hashlib.sha256((ROOT / reused["file"]).read_bytes()).hexdigest()}
        write(trace_path, json.dumps(trace_data))
        check("reuse sidecar trace accepted without marker",
              not any("trace_binding" in e or "content-bound test trace" in e for e in errors_for(trace_path)))
        reused["trace_binding"]["test_content_sha"] = "0" * 64
        rejects("stale reused test hash", write(trace_path, json.dumps(trace_data)), "invalid content-bound test trace")
        trace_path.write_bytes(original_trace)

        # --- rule: case preconditions — shape only, and only when declared ---------------------
        # TP1-15045: "needs guardrail data", "a non-owner account" were prose in a Given,
        # and the stand answered in S5. The field is optional: the good fixture has none.
        case_name = "work/test-cases/checkout/TC-001.md"
        ok("a case with no preconditions (every case written before 0.7.8)", Q1 / case_name)
        flag = ('{"id": "PC-1", "kind": "feature_flag", "what": "coupons are enabled", "partitions": '
                '["P-cap"], "check": {"http": {"path": "/v1/config", "json_path": "features.coupons", '
                '"equals": true}}}')
        ok("preconditions as one line of JSON",
           variant(case_name, "basis: requirement:R-1\n",
                   "basis: requirement:R-1\npreconditions: [" + flag + ', {"id": "PC-2", "kind": '
                   '"account", "what": "a second account", "check": {"env": "SECOND_USER"}}, {"id": '
                   '"PC-3", "kind": "data", "what": "an expired coupon exists", "check": {"none": '
                   '"no API lists coupons"}}]\n'))
        rejects("preconditions written as a nested block the flat parser would drop",
                variant(case_name, "basis: requirement:R-1\n",
                        "basis: requirement:R-1\npreconditions:\n  - id: PC-1\n"),
                "one line of JSON")
        rejects("a precondition kind outside the closed list",
                variant(case_name, "basis: requirement:R-1\n",
                        "basis: requirement:R-1\npreconditions: ["
                        + flag.replace("feature_flag", "toggle") + "]\n"),
                "kind `toggle` outside")
        rejects("an http check that names a host instead of a path",
                variant(case_name, "basis: requirement:R-1\n",
                        "basis: requirement:R-1\npreconditions: ["
                        + flag.replace('"/v1/config"', '"http://elsewhere.invalid/v1/config"') + "]\n"),
                "never a full URL")
        rejects("an env check carrying a value instead of a name",
                variant(case_name, "basis: requirement:R-1\n",
                        'basis: requirement:R-1\npreconditions: [{"id": "PC-1", "kind": "env", "what": '
                        '"the second account", "check": {"env": "SECOND_USER=bob"}}]\n'),
                "NAME of one variable")
        restore(case_name)

        # --- t-227 (P20): where an expected value comes from; a requirement that exists only in the diff ---
        # TP1-15045 (cmp2), TC_015: Then 2 said `403`, read off the diff and labelled "the pre-refactor
        # contract"; Then 4 had no literal and no source; R-17/R-19 were derived from the diff alone and
        # reached the plan as requirements. Every fixture is the cmp2 artifact, verbatim (`OP`); the cutoff
        # `2026-10-02` is applied by editing the date, so the verbatim files themselves are LEGACY.
        story = ROOT / "qa-factory" / "artifacts" / "TP1-15045"
        reg_path = story / "work" / "requirements-register.md"
        ready_path = story / "work" / "requirements-readiness.json"
        answers_path = story / "work" / "question-answers.jsonl"
        tc_path = story / "work" / "test-cases" / "workflow-visual-diff" / "TP1-15045_TC_015.md"
        plan_path = story / "test-plan.md"
        NEW = "2026-10-02"
        REGISTER_TEXT = (OP / "requirements-register.md").read_text(encoding="utf-8")
        TC_TEXT = (OP / "TP1-15045_TC_015.md").read_text(encoding="utf-8")
        assert "created: 2026-10-01" in REGISTER_TEXT and "updated: 2026-10-01" in TC_TEXT

        def edit_row(text, section, rid, col=None, value=None) -> str:
            """The register text with one cell of one row of `section` replaced (`col` is the cell's
            index), or the whole row dropped when `col` is None. Fixture drift fails loudly."""
            out, inside, hit = [], False, False
            for line in text.split("\n"):
                if line.startswith("## "):
                    inside = line.startswith(section)
                if inside and line.startswith(f"| {rid} |"):
                    hit = True
                    if col is None:
                        continue
                    cells = line.strip().strip("|").split("|")
                    cells[col] = f" {value} "
                    line = "|" + "|".join(cells) + "|"
                out.append(line)
            assert hit, f"fixture drift: {rid} not under {section}"
            return "\n".join(out)

        def q7_hash() -> str:
            """The `row_hash` `QR.record` stores with an answer to Q7: the row as the person was shown it. t-271 F5: a
            record that stores none (the hand-written lines these fixtures used to write) confirms nothing."""
            import question_register as QR
            rows = json.loads((OP / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]
            return QR._hash(next(q for q in rows if q["id"] == "Q7"))

        def register(created="2026-10-01", claims="", edits=(), readiness=True, answered=False) -> Path:
            text = REGISTER_TEXT.replace("created: 2026-10-01", f"created: {created}")
            for edit in edits:
                text = edit_row(text, *edit)
            write(reg_path, text + claims)
            if readiness:
                write(ready_path, (OP / "requirements-readiness.json").read_text(encoding="utf-8"))
            elif ready_path.exists():
                ready_path.unlink()
            if answered:
                write(answers_path, json.dumps({"kind": "question", "id": "Q7", "status": "answered", "reading": "a",
                                                "words": "Q7: a", "by": "driver", "where": "gate A",
                                                "at": "2026-10-02T09:00:00+00:00", "row_hash": q7_hash()}) + "\n")
            elif answers_path.exists():
                answers_path.unlink()
            return reg_path

        def tc015(updated=NEW, oracles=None, question_thens=None, basis=None, raw_oracles=None, raise_questions=None) -> Path:
            text = TC_TEXT.replace("updated: 2026-10-01", f"updated: {updated}")
            if basis is not None:
                text = text.replace('basis: "requirement:R-19"', f"basis: {basis}")
            extra = ""
            if raw_oracles is not None:
                extra += f"then_oracles: {raw_oracles}\n"
            elif oracles is not None:
                extra += f"then_oracles: {json.dumps(oracles)}\n"
            if question_thens is not None:
                extra += f"question_thens: {json.dumps(question_thens)}\n"
            if raise_questions is not None:
                extra += "raise_questions: " + (raise_questions if isinstance(raise_questions, str) else json.dumps(raise_questions)) + "\n"
            return write(tc_path, text.replace("plan_row: TS-15\n", extra + "plan_row: TS-15\n", 1))

        CLAIMS = (
            "\n## Behaviour claims\n\n"
            "| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n"
            "| R-16 | absent | absent | 404 for an unknown workflow | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:581 | unknown | Q7 |\n"
            "| R-17 | 400 | base:b9c0c4e:workflow.py:989 | 403 | diff:+testproject1-backend:src/testproject1/rest_api/routers/workflow.py:158 | yes | Q7 |\n"
            "| R-18 | unknown | unknown | dry_run creates no assignment | diff:testproject1-backend:src/testproject1/service/guardrail/guardrail_service.py:181 | unknown | Q7 |\n"
            "| R-19 | unknown | unknown | 400 | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:532 | unknown | Q7 |\n")
        ORACLES = [{"then": 1, "source": "ac", "ref": "R-13"},
                   {"then": 2, "source": "precedent", "ref": "base:b9c0c4e:src/testproject1/rest_api/routers/workflow.py:989"},
                   {"then": 3, "source": "requirement", "ref": "R-13"},       # G1-0: the new word beside the older `ac` of Then 1
                   {"then": 4, "source": "unknown", "ref": "Q7"}]
        QTHENS = [{"question": "Q7", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": ""}, "not_needed": ""}]
        CONSISTENCY = '"consistency:PUT and validate run one pre-persist pipeline"'

        # K1 — the case.
        register()
        ok("K1 control: the verbatim TC_015 (updated 2026-10-01) is a legacy case, never refused", tc015(updated="2026-10-01"))
        found = errors_for(tc015(updated="2026-10-01", raw_oracles="not json at all"))
        check("a legacy case carrying a broken then_oracles is silent too", not any("then_oracles" in e for e in found), str(found))
        found = errors_for(tc015())
        check_in("K1: no then_oracles on a new case is refused, naming every Then", "Then 1, 2, 3, 4", [e for e in found if "then_oracles" in e])
        check_in("K1: and the refusal names the form and the words", "ac | spec | precedent | person | unknown", found)
        check_in("C12: the case basis `requirement:R-19` names an implementation-only R and is refused", "basis 'requirement:R-19' names R-19", found)
        rejects("K1: ac -> R-19 is refused: R-19 is implementation-only, a code-derived R never passes as an AC",
                tc015(basis=CONSISTENCY, oracles=[dict(ORACLES[0], ref="R-19")] + ORACLES[1:], question_thens=QTHENS),
                "R-19 is implementation-only")
        ok("K1: Then 4 unknown/Q7 (Q7 shows before/now, question_thens names it) with the others sourced is accepted",
           tc015(basis=CONSISTENCY, oracles=ORACLES, question_thens=QTHENS))
        rejects("K1: an unknown Then with no question_thens is refused",
                tc015(basis=CONSISTENCY, oracles=ORACLES), "`unknown` needs an entry for this Then in `question_thens`")
        rejects("K1: question_thens for ANOTHER question does not open this Then",
                tc015(basis=CONSISTENCY, oracles=ORACLES, question_thens=[dict(QTHENS[0], question="Q1")]),
                "`unknown` needs an entry for this Then in `question_thens` for Q7")
        rejects("K1: ac:R-13 while question_thens gives readings for the same Then: settled or open, never both",
                tc015(basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "ac", "ref": "R-13"}], question_thens=QTHENS),
                "settled or open, never both")
        ok("C8: ac:R-13 on a Then with NO literal is valid - parity is a relation, read live",
           tc015(basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "ac", "ref": "R-13"}]))
        rejects("K1: unknown naming a question that is not in open_questions", tc015(
            basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "unknown", "ref": "Q99"}],
            question_thens=[dict(QTHENS[0], question="Q99")]), "Q99 is not in `open_questions`")
        rejects("K1: unknown naming Q1, which shows no before/now", tc015(
            basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "unknown", "ref": "Q1"}],
            question_thens=[dict(QTHENS[0], question="Q1")]), "question Q1 does not show before/now")
        register(readiness=False)
        rejects("K1: unknown with requirements-readiness.json missing (an unknown never travels without a door)",
                tc015(basis=CONSISTENCY, oracles=ORACLES, question_thens=QTHENS), "is missing or unreadable")
        register()
        rejects("K1: `person` naming a question nobody answered yet", tc015(
            basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "person", "ref": "Q7"}]),
            "not answered yet: write `unknown`")
        rejects("edge: source `code` is not a word", tc015(
            basis=CONSISTENCY, oracles=[dict(ORACLES[0], source="code", ref="R-13")] + ORACLES[1:], question_thens=QTHENS),
            "`code` is never an oracle")
        rejects("edge: a precedent is the BASE revision's line, not an R", tc015(
            basis=CONSISTENCY, oracles=[ORACLES[0], dict(ORACLES[1], ref="R-13")] + ORACLES[2:], question_thens=QTHENS),
            "`precedent` needs the BASE revision's behaviour")
        rejects("edge: a Then number not under ## Then", tc015(
            basis=CONSISTENCY, oracles=ORACLES + [{"then": 9, "source": "ac", "ref": "R-13"}], question_thens=QTHENS),
            "Then 9, which is not an item under `## Then`")
        rejects("edge: a Then named twice", tc015(
            basis=CONSISTENCY, oracles=ORACLES + [{"then": 1, "source": "ac", "ref": "R-1"}], question_thens=QTHENS),
            "names Then 1 twice")
        rejects("edge: a Then with no entry", tc015(basis=CONSISTENCY, oracles=ORACLES[:3], question_thens=None),
                "no entry for Then 4")
        rejects("edge: an empty value reads as nothing, the question_thens wording",
                tc015(basis=CONSISTENCY, raw_oracles="", question_thens=QTHENS), "must be ONE line of JSON")
        rejects("edge: broken JSON", tc015(basis=CONSISTENCY, raw_oracles="[{\"then\": 1,"), "must be ONE line of JSON")
        rejects("edge: a non-list", tc015(basis=CONSISTENCY, raw_oracles='{"then": 1}'), "the value is not a list")
        rejects("edge: an ac ref that is not an R", tc015(
            basis=CONSISTENCY, oracles=[dict(ORACLES[0], ref="AC-13")] + ORACLES[1:], question_thens=QTHENS),
            "needs a register requirement as ref")
        rejects("edge: an ac ref the register does not have", tc015(
            basis=CONSISTENCY, oracles=[dict(ORACLES[0], ref="R-77")] + ORACLES[1:], question_thens=QTHENS),
            "R-77 is not in the register")
        # the adversarial input of §1: R-13 does not say 403, yet {ac, R-13} passes - that is the case critic's
        check("adversarial: Then 403 with {ac, R-13} where R-13 has no 403 passes CODE (the case critic judges the text)",
              not any("then_oracles" in e or "Then 2" in e for e in errors_for(tc015(
                  basis=CONSISTENCY, oracles=[ORACLES[0], dict(ORACLES[1], source="ac", ref="R-13")] + ORACLES[2:],
                  question_thens=QTHENS))))
        # C6/F5: once the claim's question is answered the claim is CONFIRMED and R-19 stops being implementation-only
        register(claims=CLAIMS, answered=True)
        ok("a confirmed behaviour claim: ac -> R-19 and basis requirement:R-19 are accepted (the person said which side is expected)",
           tc015(basis='"requirement:R-19"', oracles=[dict(ORACLES[0], ref="R-19")] + ORACLES[1:], question_thens=QTHENS))
        ok("and the answered question is `person`, not `unknown`: question_thens beside it is a conflict, none beside it is fine",
           tc015(basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "person", "ref": "Q7"}]))
        register(claims=CLAIMS)
        rejects("the same claim, unanswered: ac -> R-19 is refused again",
                tc015(basis=CONSISTENCY, oracles=[dict(ORACLES[0], ref="R-19")] + ORACLES[1:], question_thens=QTHENS),
                "R-19 is implementation-only")

        # t-256 O1 (the P20 leak after an answer): ONLY reading `a` confirms the claim. `b` says the code is
        # WRONG and own wording says nothing: neither may make `ac:R-19` legal again.
        def answered_as(reading, **more) -> None:
            write(answers_path, json.dumps(dict({"kind": "question", "id": "Q7", "status": "answered", "reading": reading,
                                                 "words": "Q7: " + (reading or "my own words"), "by": "driver",
                                                 "where": "gate A", "at": "2026-10-02T09:00:00+00:00",
                                                 "row_hash": q7_hash()}, **more)) + "\n")
        R19_AC = [dict(ORACLES[0], ref="R-19")] + ORACLES[1:]
        for label, reading in (("b: a regression", "b"), ("the person's own wording (no letter)", "")):
            register(claims=CLAIMS)
            answered_as(reading)
            rejects(f"O1: Q7 answered {label}: ac -> R-19 is STILL refused", tc015(basis=CONSISTENCY, oracles=R19_AC,
                                                                                    question_thens=QTHENS), "R-19 is implementation-only")
        register(claims=CLAIMS)
        answered_as("b")
        ok("O1: ...and the person's answer b is the oracle: `person`/Q7 on the same Then is accepted",
           tc015(basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "person", "ref": "Q7"}]))
        register(claims=CLAIMS)
        answered_as("a")
        ok("O1 control: answered a confirms the claim (the person said the behaviour now is expected)",
           tc015(basis='"requirement:R-19"', oracles=R19_AC, question_thens=QTHENS))
        register(claims=CLAIMS)
        answered_as("a", row_hash="0" * 64)
        rejects("O1: answered a on a text that changed since (the stored hash is not the row's today): unconfirmed again",
                tc015(basis=CONSISTENCY, oracles=R19_AC, question_thens=QTHENS), "R-19 is implementation-only")
        register(claims=CLAIMS)

        # t-256 O4: the designer has no Bash - an `unknown` Then with the ref `raise` and ONE `raise_questions` line;
        # the pair is legal only as a pair, and the S4 exit raises it.
        RAISE_ORACLES = ORACLES[:3] + [{"then": 4, "source": "unknown", "ref": "raise"}]
        # HF4-7 (N7-1): a question being raised is a before/now one: its texts are keyed `now` / `before`, not by letter
        RAISE_QTHENS = [dict(QTHENS[0], question="raise", readings={"now": "the PUT answers 2xx", "before": "the PUT is rejected"})]
        RAISE_Q = [{"then": 4, "question": "Which status code must PUT return for a body that breaks two checks at once?",
                    "source_says": [{"quote": "returns the same results and error codes as before", "where": "register R-19"}],
                    "severity": "major", "owner_role": "po_ba",
                    "before": {"value": "unknown", "where": "the base revision is not in the hunk"},
                    "now": {"value": "400", "where": "observed by the S5 run"}}]
        register(created=NEW, claims=CLAIMS)
        ok("O4: `unknown` with ref `raise`, its raise_questions entry and its question_thens entry is accepted",
           tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS, raise_questions=RAISE_Q))
        rejects("O4: a `raise` with NO raise_questions entry is refused, naming the Then",
                tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS),
                "Then 4 is `unknown` with the ref `raise` but raise_questions has no entry for it")
        rejects("O4: ...and the refusal carries the form", tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS),
                'raise_questions: [{"then": 4, "question"')
        rejects("O4: a raise_questions entry for a Then whose oracle is NOT `raise` is refused",
                tc015(basis=CONSISTENCY, oracles=ORACLES, question_thens=QTHENS, raise_questions=[dict(RAISE_Q[0], then=3)]),
                "raise_questions has an entry for Then 3, whose oracle in then_oracles is not")
        rejects("O4: an entry for a Then number that is not under ## Then",
                tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS, raise_questions=RAISE_Q + [dict(RAISE_Q[0], then=9)]),
                "raise_questions names Then 9, which is not an item under `## Then`")
        rejects("O4: the same Then twice", tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS,
                                                 raise_questions=RAISE_Q + RAISE_Q), "raise_questions names Then 4 twice")
        rejects("O4: an entry the raise would refuse (no `now`) is refused at write time, so the designer learns it then",
                tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS,
                      raise_questions=[{k: v for k, v in RAISE_Q[0].items() if k != "now"}]), "raise_questions needs `now` as an object")
        rejects("O4: broken JSON reads as nothing", tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS,
                                                          raise_questions='[{"then": 4,'), "`raise_questions` must be ONE line of JSON")
        rejects("O4: `raise` still needs its question_thens entry (what the Then says under each reading)",
                tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, raise_questions=RAISE_Q),
                "`unknown` needs an entry for this Then in `question_thens` for raise")
        rejects("O4: `person` with the ref `raise` is no way round it (it names a question nobody raised)",
                tc015(basis=CONSISTENCY, oracles=ORACLES[:3] + [{"then": 4, "source": "person", "ref": "raise"}], raise_questions=RAISE_Q),
                "raise is not in `open_questions`")
        register(created=NEW, claims=CLAIMS, readiness=False)
        ok("O4: with the readiness file not there yet the `raise` is still accepted (the S4 exit raises it into the file S2 wrote)",
           tc015(basis=CONSISTENCY, oracles=RAISE_ORACLES, question_thens=RAISE_QTHENS, raise_questions=RAISE_Q))
        register(created=NEW, claims=CLAIMS)

        # t-256 O5 (the temporal gap): a register written BEFORE requirements-readiness.json had its claims' question
        # ids unchecked on write (the file was not there); the S2 exit is the first moment both exist.
        import exit_gate
        Q99 = CLAIMS.replace("| yes | Q7 |", "| yes | Q99 |")

        def at_the_s2_exit() -> list:
            return [e for e in exit_gate.collect_errors("TP1-15045") if e.startswith("requirements-register.md")]
        register(created=NEW, claims=Q99, readiness=False)
        check_eq("O5: written before the readiness file, the register passes on write (nothing to check the id against)",
                 [e for e in errors_for(reg_path) if "Q99" in e], [])
        write(ready_path, (OP / "requirements-readiness.json").read_text(encoding="utf-8"))
        found = at_the_s2_exit()
        check_in("O5: the S2 exit refuses it, naming the claim and the missing question id",
                 "R-17: behaviour claim — question Q99 is not in `open_questions`", found)
        register(created=NEW, claims=CLAIMS)
        check_eq("O5: written after the readiness file (the ids resolve): the exit is unchanged", at_the_s2_exit(), [])
        register(created="2026-10-01", claims=Q99)
        check_eq("O5 control: a legacy register (created before the cutoff) is never refused at the exit", at_the_s2_exit(), [])

        # K2 — the register.
        register()
        ok("K2 control: the verbatim register (created 2026-10-01) is legacy, never refused", reg_path)
        found = errors_for(register(created=NEW))
        for rid in ("R-16", "R-17", "R-18", "R-19"):
            check_in(f"K2: {rid} is implementation-only and has no behaviour claim", f"{rid} is implementation-only and has no behaviour claim", found)
        for rid in ("R-1", "R-13", "R-27"):
            check_not_in(f"K2 control: {rid} is never named a claim", f"{rid} is implementation-only", found)
        check_in("K2: the refusal names the section and its columns", "R | before | before_ref | now | now_ref | differs | question", found)
        found = errors_for(register(created=NEW, edits=[("## Register", "R-17", 5, "AC-17")]))
        check_not_in("C11: a derived row WITH an ac_ref is not a claim", "R-17 is implementation-only", found)
        found = errors_for(register(created=NEW, edits=[("## Contradiction matrix", "R-17", 2, "ok:TP1-14482 AC9")]))
        check_not_in("C11: a derived row with a matrix cell that is not silent is not a claim", "R-17 is implementation-only", found)
        found = errors_for(register(created=NEW, edits=[("## Register", "R-17", 6, "current-code:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:613")]))
        check_not_in("C11: a derived row whose observable is not `diff:` is not a claim", "R-17 is implementation-only", found)
        found = errors_for(register(created=NEW, edits=[("## Register", "R-17", 5, "-")]))
        check_in("C10: an ac_ref written as a dash counts as empty - the row is still a claim", "R-17 is implementation-only", found)
        found = errors_for(register(created=NEW, edits=[("## Contradiction matrix", "R-17")]))
        check_in("C10: an R with NO matrix row counts as all-silent - still a claim", "R-17 is implementation-only", found)
        ok("K2: before unknown / 400 base:<rev>:workflow.py:<n>, now 403 diff:+...:158, differs yes, Q7 - accepted",
           register(created=NEW, claims=CLAIMS))
        ok("K2 edge: a new surface (before absent) is still a claim with a question, grouped on one question for four rows",
           register(created=NEW, claims=CLAIMS))
        bad_row = CLAIMS.replace("| yes | Q7 |", "| yes |  |")
        rejects("K2: `differs: yes` with no question is refused", register(created=NEW, claims=bad_row),
                "`differs: yes` with no `question`")
        rejects("K2: a claim whose `differs` is not yes still needs its question (the invariant, not only the yes case)",
                register(created=NEW, claims=CLAIMS.replace("| unknown | Q7 |", "| unknown |  |", 1)),
                "never reaches the plan without its question")

        # G1-3: the register's `delta` column (LAST) and the claims' `origin` column (LAST), both read by their header.
        def add_column(text, section, header, cells) -> str:
            """`text` with one more last column in the table under `section`: `header`, then `cells[row id]` ('' default)."""
            out, inside = [], False
            for line in text.split("\n"):
                if line.startswith("## "):
                    inside = line.startswith(section)
                if inside and line.startswith("|"):
                    if line.startswith("| R |"):
                        line = f"{line.rstrip()} {header} |"
                    elif line.startswith("|---"):
                        line = f"{line.rstrip()}---|"
                    else:
                        line = f"{line.rstrip()} {cells.get(line.split('|')[1].strip(), '')} |"
                out.append(line)
            return "\n".join(out)

        def register_with(delta=None, header="delta", origin=None, created=NEW, edits=()) -> Path:
            """The fixture register with a `delta` column (`delta`: {R: word}; default `new`) and/or an `origin` column on the claims."""
            text = REGISTER_TEXT.replace("created: 2026-10-01", f"created: {created}")
            for edit in edits:
                text = edit_row(text, *edit)
            claims = CLAIMS
            if origin is not None:
                claims = add_column("\n".join(CLAIMS.split("\n")), "## Behaviour claims", "origin", origin)
            if delta is not None:
                text = add_column(text, "## Register", header, {r: "new" for r in ("R-1", "R-13", "R-16", "R-17", "R-18", "R-19", "R-27")} | delta)
            write(reg_path, text + claims)
            write(ready_path, (OP / "requirements-readiness.json").read_text(encoding="utf-8"))
            return reg_path

        def delta_errors(path) -> list:
            return [e for e in errors_for(path) if ": delta " in e]

        check_eq("G1-3: a register with no delta column has no delta error", delta_errors(register_with()), [])
        check_eq("G1-3: a register whose delta column is all `new` has none", delta_errors(register_with(delta={})), [])
        check_eq("G1-3: `changed` and `unchanged` with a non-diff observable are fine",
                 delta_errors(register_with(delta={"R-1": "changed", "R-27": "unchanged"},
                                            edits=[("## Register", "R-27", 6, "current-code:a/b.py:3")])), [])
        for word in ("New", "same", "n/a", "", "unchanged_unevidenced", "CHANGED"):
            found = delta_errors(register_with(delta={"R-13": word}))
            check_in(f"G1-3: delta {word!r} is refused, naming the row and the three words",
                     f"R-13: delta '{word}' is none of new | changed | unchanged", found)
        found = delta_errors(register_with(delta={"R-16": "unchanged"}))
        check_in("G1-3: `unchanged` with a `diff:` observable is refused as a contradiction", "R-16: delta unchanged with observable 'diff:", found)
        check_in("G1-3: ...and the text says `current-code:` does not take the row out of the count",
                 "writing `current-code:` keeps the row in the coverage count", found)
        check_eq("G1-3: a project's own ninth column (not called delta) is not read as one", delta_errors(register_with(delta={"R-13": "xyz"}, header="note")), [])
        check_in("G1-3: a legacy register (created before the cutoff) that HAS the column is checked too",
                 "R-13: delta 'same'", delta_errors(register_with(delta={"R-13": "same"}, created="2026-10-01")))

        def origin_errors(path) -> list:
            return [e for e in errors_for(path) if "`origin`" in e]

        every = {"R-16": "", "R-17": "S3-grounding", "R-18": "", "R-19": ""}
        check_eq("G1-3: empty and S3-grounding origins are accepted", origin_errors(register_with(origin=every)), [])
        check_eq("G1-3: a claims table with no origin column has no origin error", origin_errors(register_with()), [])
        found = origin_errors(register_with(origin=dict(every, **{"R-19": "S2"})))
        check_in("G1-3: another origin is refused with the fragment", "R-19: behaviour claim — `origin` 'S2' is none of: empty (written at S2) | S3-grounding", found)
        found = origin_errors(register_with(origin=dict(every, **{"R-16": "diff"})))
        check_in("G1-3: the origin of ANY row is judged (not only the implementation-only R of the loop below)",
                 "R-16: behaviour claim — `origin` 'diff'", found)
        check_eq("G1-3: a register older than the cutoff: its claims' origin is not judged (the date of S2)",
                 origin_errors(register_with(origin=dict(every, **{"R-19": "S2"}), created="2026-10-01")), [])
        found = " ".join(e for e in errors_for(register(created=NEW)) if "has no behaviour claim" in e)
        check_in("G1-3: the missing-claim refusal lists the S2 columns", "R | before | before_ref | now | now_ref | differs | question):", found)
        check_not_in("G1-3: ...and does NOT ask S2 for `origin`", "origin", found)
        rejects("K2: a question id not in open_questions is refused",
                register(created=NEW, claims=CLAIMS.replace("| yes | Q7 |", "| yes | Q99 |")), "question Q99 is not in `open_questions`")
        rejects("K2: a question that shows no before/now is refused",
                register(created=NEW, claims=CLAIMS.replace("| yes | Q7 |", "| yes | Q1 |")), "question Q1 does not show before/now")
        rejects("K2: an unknown differs word is refused", register(created=NEW, claims=CLAIMS.replace("| yes |", "| maybe |")),
                "`differs` 'maybe'")
        rejects("K2: a before_ref outside the forms is refused",
                register(created=NEW, claims=CLAIMS.replace("base:b9c0c4e:workflow.py:989", "from memory")), "`before_ref` 'from memory'")
        rejects("K2: a claim with no `now` is refused",
                register(created=NEW, claims=CLAIMS.replace("| 403 | diff:+testproject1-backend:src/testproject1/rest_api/routers/workflow.py:158 |", "|  |  |")),
                "`now` and `now_ref` are both required")
        rejects("K2: a claim twice", register(created=NEW, claims=CLAIMS + CLAIMS.strip().split("\n")[4] + "\n"),
                "appears twice")
        ok("K2 edge (temporal): the register written BEFORE the readiness file - its shape is checked, the ids wait",
           register(created=NEW, claims=CLAIMS, readiness=False))
        rejects("K2 edge (temporal): and a shape error is still refused with no readiness file",
                register(created=NEW, claims=bad_row, readiness=False), "`differs: yes` with no `question`")

        # t-271 F1 (the date gate): the dated oracle rules switch on `created` / `updated`. A date nobody can read is
        # REFUSED by name - before, it read as "before the cutoff" and every dated check was off with no word.
        for label, value in (("empty", ""), ("no date at all", "yesterday"), ("an impossible date", "2026-13-45"),
                             ("in the day-first form", "02.10.2026"), ("without separators", "20261002")):
            rejects(f"F1: a register whose `created` is {label} is refused, naming the field and the form",
                    register(created=value, claims=CLAIMS), "must be an ISO date, YYYY-MM-DD")
            check_in("F1: ... and says which field it is", "`created` is", errors_for(reg_path))
            rejects(f"F1: a case whose `updated` is {label} is refused too",
                    tc015(updated=value, basis=CONSISTENCY, oracles=ORACLES, question_thens=QTHENS), "`updated` is")
        register(created=NEW, claims=CLAIMS)
        found = errors_for(write(reg_path, REGISTER_TEXT.replace("created: 2026-10-01\n", "") + CLAIMS))
        check_eq("F1: a register with NO `created` line is refused once, by the existing required-field rule (not said twice)",
                 [e for e in found if "created" in e], ["requirements-register.md: required field 'created' is missing"])
        for date in ("2026-10-02", "2026-10-02T09:00:00Z", "2026-12-31"):
            check_eq(f"F1 control: a readable date on or after the cutoff ({date}) is the rule's own business, not a date error",
                     [e for e in errors_for(register(created=date, claims=CLAIMS)) if "ISO date" in e], [])
        ok("F1 control: the cmp2 shape (created 2026-10-01, before the cutoff) stays readable - checks off, no date error",
           register(created="2026-10-01"))
        V.ORACLE_NOTES.clear()
        errors_for(register(created="2026-10-01"))
        check_eq("F1: a legacy date is said in one note line (printed with `--verbose`)", V.ORACLE_NOTES,
                 ["requirements-register.md: `created` 2026-10-01 is before 2026-10-02: the oracle checks (then_oracles, "
                  "behaviour claims) are off for this file"])
        V.ORACLE_NOTES.clear()
        errors_for(register(created=NEW, claims=CLAIMS))
        check_eq("F1 control: a dated file adds no note", V.ORACLE_NOTES, [])
        # the S2 exit re-run reads the same date the same way
        register(created="yesterday", claims=Q99)
        write(ready_path, (OP / "requirements-readiness.json").read_text(encoding="utf-8"))
        check_in("F1: the S2 exit refuses an unreadable `created` by name (before: it skipped the re-check silently)",
                 "requirements-register.md: FORM", [e[:34] for e in at_the_s2_exit()])
        check_in("F1: ... naming the form", "must be an ISO date", " ".join(at_the_s2_exit()))
        register(created="2026-10-01", claims=Q99)
        check_eq("F1 control: the S2 exit leaves a legacy register alone", at_the_s2_exit(), [])
        # the CLI: `--check <file> --verbose` prints the note, plain `--check` does not
        import os
        proc_env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT))
        quiet = run_script("validate_artifacts.py", "--check", register(created="2026-10-01"), env=proc_env)
        loud = run_script("validate_artifacts.py", "--check", reg_path, "--verbose", env=proc_env)
        check_eq("F1: `--check` on a legacy register prints no note", ("note:" in quiet.stdout, quiet.returncode), (False, 0))
        check_in("F1: `--check --verbose` prints it, in one line", "note: requirements-register.md: `created` 2026-10-01 is before 2026-10-02",
                 loud.stdout)

        # C12 — the plan's `oracle` field may not name an implementation-only R either.
        register(created=NEW)
        plan_text = (GOOD / "test-plan.md").read_text(encoding="utf-8").replace("task: QA-1", "task: TP1-15045")
        new_plan = plan_text.replace("created: 2026-09-11", f"created: {NEW}").replace("| R-1 |", "| R-19 |").replace(
            "| requirement:R-1 |", "| requirement:R-19 |")
        rejects("C12: a plan oracle `requirement:R-19` names an implementation-only R", write(plan_path, new_plan),
                "oracle 'requirement:R-19' names R-19, which is implementation-only")
        found = errors_for(write(plan_path, plan_text.replace("created: 2026-09-11", f"created: {NEW}").replace("| R-1 |", "| R-13 |").replace(
            "| requirement:R-1 |", "| requirement:R-13 |")))
        check_not_in("C12 control: R-13 (an AC) is a fine oracle", "implementation-only", found)
        found = errors_for(write(plan_path, plan_text.replace("| R-1 |", "| R-19 |").replace("| requirement:R-1 |", "| requirement:R-19 |")))
        check_not_in("C12: a plan created before the cutoff is never refused", "implementation-only", found)
        # t-271 F1 on the plan: its dated check runs only beside a register; an unreadable or missing `created` there is
        # refused by name instead of switching the check off.
        register(created=NEW)
        base_plan = plan_text.replace("| R-1 |", "| R-19 |").replace("| requirement:R-1 |", "| requirement:R-19 |")
        for label, text in (("no date at all", base_plan.replace("created: 2026-09-11", "created: yesterday")),
                            ("empty", base_plan.replace("created: 2026-09-11", "created:")),
                            ("missing", base_plan.replace("created: 2026-09-11\n", ""))):
            rejects(f"F1: a plan whose `created` is {label} (a register stands beside it) is refused, naming the field",
                    write(plan_path, text), "`created` is")
        reg_path.unlink()
        found = errors_for(write(plan_path, base_plan.replace("created: 2026-09-11", "created: yesterday")))
        check_not_in("F1 control: with NO register beside it the plan's date check never runs, so nothing is said", "ISO date", found)
        # G2-10 fix round (F-7): `check_register` and `check_plan_v0` CALL the cell-count check - a row with a cell beyond the header is
        # refused in a file created on or after the cutoff and only noted in an older one (the call is what these rows kill)
        def stray(text, first):
            lines = text.split("\n")
            at = next(i for i, l in enumerate(lines) if l.startswith(first))
            lines[at] = lines[at].rstrip() + " stray |"
            return "\n".join(lines)
        late = "2026-11-05"
        text = stray(REGISTER_TEXT.replace("created: 2026-10-01", f"created: {late}"), "| R-1 |")
        rejects("G2-10: a register created after the cutoff with a cell beyond its header is refused (check_register calls the count)",
                write(reg_path, text), "R-1: the register row holds")
        check_not_in("G2-10 control: the same row in a register created before the cutoff is not refused",
                     "the register row holds", errors_for(write(reg_path, stray(REGISTER_TEXT, "| R-1 |"))))
        plan_text = (GOOD / "test-plan.md").read_text(encoding="utf-8").replace("task: QA-1", "task: TP1-15045")
        rejects("G2-10: a plan created after the cutoff with a cell beyond its header is refused (check_plan_v0 calls the count)",
                write(plan_path, stray(plan_text.replace("created: 2026-09-11", f"created: {late}"), "| TS-")), "the plan row holds")
        check_not_in("G2-10 control: the same row in a plan created before the cutoff is not refused",
                     "the plan row holds", errors_for(write(plan_path, stray(plan_text, "| TS-"))))
        # G2-12 fix round (F-4): a requirement whose only source is the current code owes a `## Behaviour claims` row too, by the register's
        # own `created` (on or after UNCONFIRMED_SOURCE_CUTOFF, or unreadable: the new reading; older: only the diff-only class owes one)
        def with_code_row(created):
            lines = REGISTER_TEXT.replace("created: 2026-10-01", f"created: {created}").split("\n")
            at = next(i for i, l in enumerate(lines) if l.startswith("| R-1 |"))
            lines.insert(at + 1, "| R-90 | the list keeps its order | derived | test:orders_spec | yes | - | current-code:app/list.py:7 | blocked-flow |")
            return "\n".join(lines)
        owes = "R-90 is implementation-only and has no behaviour claim"
        rejects("G2-12: a register created after the cutoff, a `current-code:` row and no claims row: refused (S2 does not close with nobody to ask)",
                write(reg_path, with_code_row(late)), owes)
        check_eq("G2-12: ... a `created` nobody can read reads the new way in the owing list (the form check refuses such a file earlier)",
                 ("R-90" in C.claim_required_requirements(with_code_row("yesterday")), "R-90" in C.claim_required_requirements(with_code_row("2026-10-30"))),
                 (True, False))
        check_not_in("G2-12: ... a register created before the cutoff keeps the narrower reading", owes, errors_for(write(reg_path, with_code_row("2026-10-30"))))
        check_not_in("G2-12: ... and a claims row for it ends the refusal", owes, errors_for(write(reg_path, with_code_row(late) + CLAIMS.split("| R-16 |")[0]
                                                    + "| R-90 | unknown | unknown | the list keeps its order | current-code:app/list.py:7 | unknown | Q7 |\n")))
        check_eq("G2-12: the owing list is the diff-only class plus the code-sourced one, in register order, no duplicate",
                 C.claim_required_requirements(with_code_row(late)).count("R-90"), 1)
        for leftover in (plan_path, reg_path, ready_path, answers_path, tc_path):
            if leftover.exists():
                leftover.unlink()

        # --- every message is short enough to act on --------------------------------------------
        long_ones = []
        for path, _ in ((Q2 / "test-plan.md", None), (Q2 / "work" / "triage.json", None),
                        (Q2 / "results-brief.md", None), (Q2 / "work" / "automation-manifest.json", None)):
            for message in errors_for(path):
                if len(message.splitlines()) > 2:
                    long_ones.append(message[:100])
        check("every rejection message is at most two lines", not long_ones, str(long_ones))

        # --- a v0 plan never falls through to the legacy plan checker ------------------------------
        import contract as Cc
        check_eq("the v0 plan is recognized as v0", Cc.plan_is_v0(Q1 / "test-plan.md"), True)
        check_eq("the validator's observable list matches contract.py",
                 tuple(V.OBSERVABLE_SOURCES_V0), Cc.OBSERVABLE_SOURCES)

        # --- G1-13 (M17): the full register check is as clean after a projected claim as before it ------------
        import claim_projector as CPJ
        fx = Path(__file__).resolve().parent / "fixtures" / "claim-projector"
        import tempfile
        story = Path(tempfile.mkdtemp(prefix="qa-claims-validators-")) / "T-1"
        try:
            (story / "work").mkdir(parents=True)
            for name in ("requirements-register.md", "requirements-readiness.json", "context-manifest.json", "grounding.yaml"):
                (story / "work" / name).write_bytes((fx / name).read_bytes())
            before, after = [], []
            V.check_register(story / "work" / "requirements-register.md", before)
            moved = CPJ.project(story)
            V.check_register(story / "work" / "requirements-register.md", after)
            check_eq("M17: the dated fixture is clean before; a claim was projected; the full check_register errors are the same after",
                     (before, [str(p) for p in moved.problems], moved.projected, after), ([], [], ["R-28"], []))
        finally:
            shutil.rmtree(story.parent, ignore_errors=True)
    finally:
        cleanup(ROOT)

    finish("test_validators")


if __name__ == "__main__":
    main()
