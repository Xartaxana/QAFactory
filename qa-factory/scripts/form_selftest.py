"""Self-test of the form rules of validate_artifacts.py.

    python form_selftest.py

The valid samples (which are also the reference form of the register, plan, case, bug, charter,
PTR and ledger) pass; every expected forgery is caught with the expected wording.

Root note: this test runs against a SYNTHETIC project, never the real project_root() — the
plugin's own selftest must not create or touch a qa-factory/ directory in whatever repo it
happens to run from. A fresh temp directory stands in as the project (CLAUDE_PROJECT_DIR is
set to it for every validate_artifacts.py subprocess call); the artifacts are created in its
qa-factory/artifacts/_selftest/ (needed for register resolution) and the whole temp directory
is removed at the end. Invoked by selftest.py --selftest-scripts and install_smoke.py.

`import form_selftest` does nothing by itself — no temp directory, no subprocess: the fixture
is built lazily by `build_fixture()`, and each artifact kind is its own `case_*(fx)` function
so `scripts/tests/test_form_selftest.py` can run a handful of them in-process without paying
for the whole ~24-case, ~15-20 s script (the CLI contract — `python form_selftest.py` exits
non-zero on a forgery it fails to catch — is still proven by running the script itself, in
--selftest-scripts and install_smoke.py)."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOOK = Path(__file__).resolve().parent / "validate_artifacts.py"
TASK = "_selftest"


def build_fixture() -> SimpleNamespace:
    """A synthetic project (qa-factory/artifacts/_selftest/ seeded with a PASSING register and
    plan) plus a scratch dir for cases/bugs/charters — built fresh on every call, never at
    import. Seeding the baseline here, not in case_register()/case_plan(), lets any one
    case_*(fx) group run on its own (a case/bug/charter/report/nfr/ledger case validates
    against the register and plan already on disk)."""
    proj = Path(tempfile.mkdtemp(prefix="form-selftest-project-"))
    art = proj / "qa-factory" / "artifacts" / TASK
    state = proj / "qa-factory" / "state"
    tmp = Path(tempfile.mkdtemp(prefix="form-"))
    art.mkdir(parents=True, exist_ok=True)
    (art / "requirements-register.md").write_text(REGISTER_OK, encoding="utf-8")
    (art / "test-plan.md").write_text(PLAN_OK, encoding="utf-8")
    return SimpleNamespace(proj=proj, art=art, state=state, tmp=tmp)


def cleanup_fixture(fx: SimpleNamespace) -> None:
    shutil.rmtree(fx.proj, ignore_errors=True)  # the whole synthetic project, artifacts + state
    shutil.rmtree(fx.tmp, ignore_errors=True)


def run(proj: Path, path: Path) -> tuple[int, str]:
    ev = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), capture_output=True,
                       text=True, encoding="utf-8", cwd=str(proj), env=env)
    return r.returncode, (r.stdout + r.stderr)


def case(results: list, proj: Path, name: str, path: Path, content: str, expect_ok: bool,
         must_contain: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    rc, out = run(proj, path)
    ok = (rc == 0) if expect_ok else (rc != 0 and must_contain in out)
    results.append((ok, name, rc, out.strip().splitlines()[:6]))


REGISTER_OK = """---
task: _selftest
created: 2026-09-07
ids: [R-1, R-2, R-3, R-4, R-5, R-6]
by_source: {story: 1, feature: 1, ac: 1, derived: 3}
derived_walked: [aspect, seam, bug]
seams_touched: [subscription×invoice]
confidence: high
---
## Register
| R | Requirement | source | derived_from | verifiable | ac_ref |
|---|---|---|---|---|---|
| R-1 | The user can cancel the subscription from settings | story | — | yes | AC-1 |
| R-2 | Access is kept until the end of the paid period | feature | — | yes | — |
| R-3 | The cancel button is visible only to the owner | ac | — | yes | AC-2 |
| R-4 | After cancellation the nightly invoice job does not issue an invoice | derived | seam:subscription×invoice | yes | — |
| R-5 | A repeated cancellation does not create a second event | derived | aspect:asynchrony | yes | — |
| R-6 | The subscription list keeps its order and composition (parity) | derived | baseline:settings/subscriptions | yes | — |

## Contradiction matrix
| R | parent feature | seam neighbors | area cases | open bugs |
|---|---|---|---|---|
| R-1 | ok:feature-doc.md#goal | silent | ok:TC-012 | n/a:no bugs |
| R-2 | contradicts:"team seats are released immediately" (feature §3) | silent | silent | silent |
"""

REGISTER_BAD = REGISTER_OK.replace("| derived | seam:subscription×invoice |", "| derived | — |").replace(
    "| ok:feature-doc.md#goal |", "| ok: |").replace("ok:TC-012", "ok")

PLAN_OK = """---
task: _selftest
created: 2026-09-07
complexity: S
scenarios_total: 4
smoke: 1
by_defect_class: {state: 1, seam: 1, concurrency: 1}
by_priority: {P0: 2, P1: 1, P3: 1}
requirements_total: 6
na_requirements: [R-3, R-6]
channels: {auto: 3, manual_agent: 1, manual_human: 0}
open_questions: 1
---
## Goal and depth
...
## Scenarios
| TS | R | What can go wrong | Impact | Priority | Experiment | Distinguishing observation | Basis | Level | Channel |
|---|---|---|---|---|---|---|---|---|---|
| TS-1 | R-1 | smoke | none | P3 | POST /cancel | GET /subscription → status=cancelled | requirement:R-1 | API | auto |
| TS-2 | R-2 | state @ subscription.end_date | money | P0 | cancel, then re-read the period | GET /subscription in a new session → end_date unchanged | requirement:R-2 | API | auto |
| TS-3 | R-4 | seam @ invoice-job | money | P0 | cancel, run the job | SELECT invoices WHERE user → 0 new | requirement:R-4 | integration | auto |
| TS-4 | R-5 | concurrency @ cancel handler | blocked-flow | P1 | two POST /cancel in parallel | events table → 1 row | requirement:R-5 | API | manual-agent |

## Seam scenarios
| seam | row |
|---|---|
| subscription×invoice | TS-3 |
"""

PLAN_BAD_PRIO = PLAN_OK.replace("| money | P0 | cancel, then", "| money | P2 | cancel, then")
PLAN_BAD_OBS = PLAN_OK.replace("| GET /subscription in a new session → end_date unchanged |", "| — |")
PLAN_BAD_ORPHAN = PLAN_OK.replace("na_requirements: [R-3, R-6]", "na_requirements: []")
PLAN_PARITY_OK = PLAN_OK.replace("task: _selftest\n", "task: _selftest\nprofile: parity\n").replace(
    "| requirement:R-2 | API |", "| history:baseline/subscriptions.json@abc123 | API |").replace(
    "| requirement:R-4 | integration |", "| history:baseline/invoices.json@abc123 | integration |").replace(
    "| requirement:R-5 | API |", "| invariant:one-cancel-event | API |")
PLAN_PARITY_BAD = PLAN_OK.replace("task: _selftest\n", "task: _selftest\nprofile: parity\n")

CASE_NEW_OK = """---
id: TC-901
title: Cancellation does not change end_date
area: billing
feature: subscription
task: _selftest
priority: P0
status: Draft
channel: auto
covers: [R-2]
defect_class: state
basis: requirement:R-2
reuse_decision: new
updated: 2026-09-08
---
## Scenario
"""
CASE_NEW_BAD = CASE_NEW_OK.replace("covers: [R-2]", "covers: [R-9]").replace("defect_class: state", "defect_class: vibes")
CASE_OLD_OK = """---
id: TC-902
title: old case
area: billing
priority: P1
status: Draft
channel: auto
covers_ac: [AC-1]
reuse_decision: new
updated: 2026-08-01
---
"""

BUG_NEW_OK = """---
id: BUG-901
title: cancel shifts end_date to today
severity: blocker
status: Open
area: billing
found_by: TC-901
violates: requirement:R-2
impact: money
plan_row: TS-2
created: 2026-09-08
---
## Initial state
active subscription, build abc123
## Reproduction steps
1. POST /cancel
## Expected result
end_date unchanged (requirement:R-2, TS-2)
## Actual result
end_date = today
## User impact
The user loses paid days: money
## Evidence
...
"""
BUG_NEW_BAD = BUG_NEW_OK.replace("severity: blocker", "severity: minor").replace("violates: requirement:R-2", "violates: AC-2").replace("## Initial state\nactive subscription, build abc123\n", "")
BUG_OLD_OK = """---
id: BUG-902
title: old bug
severity: minor
status: Open
area: billing
found_by: TC-1
violates: AC-1
created: 2026-08-01
---
"""

CHARTER_OK = """---
id: CH-901
title: subscription cancellation under perturbations
status: Done
trigger: cadence
timebox: 90
created: 2026-09-08
plan_review: PASS:2026-09-08T10:00:00Z
executed_at: 2026-09-08T12:00:00Z
executed_by: exploratory-tester
seams: [subscription×invoice]
hypotheses: [H-1, H-2]
mission_leftover: ["H-2 not probed: ran out of time"]
---
## Hypotheses
| H | Claim | Oracle | Refuting observation | Binding |
|---|---|---|---|---|
| H-1 | a second tab sells an add-on after cancellation | requirement:R-2 | in tab B after reload the add-on is unavailable | seam:subscription×invoice |
| H-2 | back+resubmit produces two events | invariant:one-cancel-event | events table → 1 row | perturbation:interruptions×billing |

## Findings
| H | Finding | Status | Reproduction | Follow-up |
|---|---|---|---|---|
| H-1 | the add-on is sold | probed-confirmed | 2/2 | bug |
| H-2 | — | not-probed | — | leftover |
"""
CHARTER_BAD = CHARTER_OK.replace("| probed-confirmed |", "| ok |").replace("seams: [subscription×invoice]", "seams: []")

PTR_OK = """# _selftest — test report

**The change.** Cancelling a subscription from settings, and the nightly invoice job that
must not bill a cancelled one.

**Verdict: ready to ship.** Of 6 requirements, 4 are proven by tests, 1 waits for a manual
check, 1 is deferred by design.

`delivery_ready: yes`

Notation: R-n - a requirement (understanding.md); TC-n - a test case (test-plan.md);
TS-n - a plan row; BUG-n - a bug file in `qa-factory/bugs/`.

## Proven - 3 green tests

Billing - `tests/api/test_cancel.py`:
- R-1 the owner can cancel from settings (TC-001) - reviewed by the code critic, the check is live
- R-2 access is kept until the end of the paid period (TC-002) - green, review not recorded

## Product bugs - 0

None found.

## Left with you

1. **The cancel button for a non-owner (R-3, TC-003).** To check: a member who does not own
   the subscription sees no cancel control in settings. There is no test: the stand carries
   one account. How: check by hand on preview, or say "accept the risk".

## Not proven, and what it costs

- **R-5** - the nightly invoice job never ran on this stand; a cancelled subscription may
  still be billed.
- **R-6** - deferred by design: the parity row awaits the baseline capture.

## Factory defects - nothing is wanted from you

Nothing this run: every check reached a terminal state by itself.

## Size

Forecast: **S**.
Fact: **S** - 6 requirements, 3 plan rows. No re-estimation during the story.

## Where to look

- understanding.md - what we verify and why
- test-plan.md - the plan rows, the gate A questions, the case texts
- retro.md - time per stage
- the appendix below - every requirement, case and test with its result

## Appendix - traceability

| R | What we verify | TC | Result | Basis |
|:--|:--|:--|:--|:--|
| R-1 | the owner can cancel from settings | TC-001 | **pass** | critic review, the check is live |
| R-2 | access lasts to the end of the period | TC-002 | **pass** | review not recorded |
| R-3 | a non-owner sees no cancel control | TC-003 | **wait** | one account on the stand |
| R-4 | a repeated cancellation makes no second event | TC-004 | **pass** | review not recorded |
| R-5 | the nightly job does not bill a cancelled plan | TC-005 | **not run** | the job never ran |
| R-6 | the subscription list keeps its order | - | **deferred** | the parity row awaits a baseline |
"""
PTR_BAD = PTR_OK.replace(
    "| R-5 | the nightly job does not bill a cancelled plan | TC-005 | **not run** | the job never ran |\n", "")

NFR_OK = json.dumps({
    "type": "accessibility", "mode": "assess", "task": "_selftest",
    "matrix": [
        {"clause": "WCAG 2.2 SC 2.4.7 Focus Visible", "status": "applicable", "result": "meets", "evidence": "focus screenshots, 6 controls, indicator contrast 4.1:1"},
        {"clause": "WCAG 2.2 SC 2.1.2 No Keyboard Trap", "status": "applicable", "result": "violates", "evidence": "cancel modal: Tab does not leave, Esc does not close (evidence/a11y/trap.png)"},
        {"clause": "WCAG 2.2 SC 1.2.2 Captions", "status": "n/a", "n_a_reason": "no video in the radius"},
        {"clause": "WCAG 2.2 SC 4.1.3 Status Messages", "status": "applicable", "result": "not-measured"}],
    "positive_control": {"what": "axe on an img without alt on the test page", "result": "detected"},
    "findings": [{"id": "F-1", "clause": "WCAG 2.2 SC 2.1.2", "observed": "focus trap", "impact": "blocked-flow", "confidence": 9, "evidence": "evidence/a11y/trap.png"}],
    "verdict": [{"plan_row": "TS-4", "requirement": "R-5", "result": "violates", "confidence": "high"}],
    "limitations": ["a live screen reader is unavailable: SC 4.1.3 not measured"],
    "confidence": "high", "witness": "axe-core 4.10 run 2026-09-08T10:00Z, 3 pages"}, ensure_ascii=False)
NFR_BAD = NFR_OK.replace('"result": "detected"', '"result": "not-detected"').replace('"limitations": ["a live screen reader is unavailable: SC 4.1.3 not measured"]', '"limitations": []')
LEDGER_OK = json.dumps({"ts": "2026-09-08", "bug": "BUG-903", "stage_should_have_caught": "plan",
                        "missing_element": "seam:promo×cancel", "action": "seam-map += promo×cancel",
                        "witness": "bugs/BUG-903.md"}, ensure_ascii=False) + "\n"
LEDGER_BAD = json.dumps({"ts": "2026-09-08", "bug": "BUG-904", "stage_should_have_caught": "unknown",
                         "missing_element": "", "action": "-", "witness": "x"}, ensure_ascii=False) + "\n"

def case_register(fx: SimpleNamespace) -> list:
    results: list = []
    case(results, fx.proj, "register ok", fx.art / "requirements-register.md", REGISTER_OK, True)
    case(results, fx.proj, "register bad: derived without derived_from, ok without ref",
         fx.art / "requirements-register.md", REGISTER_BAD, False, "derived without derived_from")
    (fx.art / "requirements-register.md").write_text(REGISTER_OK, encoding="utf-8")  # restore
    return results


def case_plan(fx: SimpleNamespace) -> list:
    # The register's `profile: parity` check was dropped in C0: refactor-parity testing and the
    # "before" snapshot are v1 (A4 decision), and the shipped v0 register template carries
    # neither `profile` nor `seams_touched`. The plan-side parity check stays on the legacy
    # plan path.
    results: list = []
    case(results, fx.proj, "plan ok", fx.art / "test-plan.md", PLAN_OK, True)
    case(results, fx.proj, "plan bad: priority not derived from impact", fx.art / "test-plan.md",
         PLAN_BAD_PRIO, False, "does not match the one derived")
    case(results, fx.proj, "plan bad: empty observation", fx.art / "test-plan.md",
         PLAN_BAD_OBS, False, "distinguishing observation")
    case(results, fx.proj, "plan bad: R without a row and without N/A", fx.art / "test-plan.md",
         PLAN_BAD_ORPHAN, False, "without a plan row")
    case(results, fx.proj, "plan parity ok (history:/invariant: bases)", fx.art / "test-plan.md",
         PLAN_PARITY_OK, True)
    case(results, fx.proj, "plan parity bad: requirement: bases instead of history:",
         fx.art / "test-plan.md", PLAN_PARITY_BAD, False, "profile parity")
    (fx.art / "test-plan.md").write_text(PLAN_OK, encoding="utf-8")  # restore
    return results


def case_case(fx: SimpleNamespace) -> list:
    results: list = []
    tc_dir = fx.tmp / "test-cases" / "billing"
    case(results, fx.proj, "case new ok", tc_dir / "TC-901.md", CASE_NEW_OK, True)
    case(results, fx.proj, "case new bad: R-9 not in the register, class outside the list",
         tc_dir / "TC-901.md", CASE_NEW_BAD, False, "not in the register")
    case(results, fx.proj, "case old ok (covers_ac, before cutoff)", tc_dir / "TC-902.md",
         CASE_OLD_OK, True)
    return results


def case_bug(fx: SimpleNamespace) -> list:
    results: list = []
    bug_dir = fx.tmp / "bugs"
    case(results, fx.proj, "bug new ok", bug_dir / "BUG-901.md", BUG_NEW_OK, True)
    case(results, fx.proj, "bug new bad: severity != impact, violates is not an oracle, no section",
         bug_dir / "BUG-901.md", BUG_NEW_BAD, False, "is not one of the oracle kinds")  # X7-5: S8 validators are shape-only; the fixture is refused for its oracle kind and the missing section
    case(results, fx.proj, "bug old ok (before cutoff)", bug_dir / "BUG-902.md", BUG_OLD_OK, True)
    return results


def case_charter(fx: SimpleNamespace) -> list:
    results: list = []
    ch_dir = fx.tmp / "exploratory-charters"
    case(results, fx.proj, "charter ok", ch_dir / "CH-901.md", CHARTER_OK, True)
    case(results, fx.proj, "charter bad: status ok, seams empty", ch_dir / "CH-901.md",
         CHARTER_BAD, False, "self-verdict")
    return results


def case_report(fx: SimpleNamespace) -> list:
    results: list = []
    case(results, fx.proj, "test report ok", fx.art / "test-report.md", PTR_OK, True)
    case(results, fx.proj, "test report bad: R-5 in no row of the appendix",
         fx.art / "test-report.md", PTR_BAD, False, "in no row of the appendix")
    case(results, fx.proj, "test report bad: a left-with-you item with no way to do it",
         fx.art / "test-report.md",
         PTR_OK.replace('How: check by hand on preview, or say "accept the risk".', "It matters."),
         False, "neither \"Needed:\" nor \"How:\"")
    case(results, fx.proj, "test report bad: a decision id with no words", fx.art / "test-report.md",
         PTR_OK.replace("the stand carries\n   one account", "decision S5-160 applies"),
         False, "with no decision text beside it")
    (fx.art / "test-report.md").write_text(PTR_OK, encoding="utf-8")  # restore
    return results


def case_nfr(fx: SimpleNamespace) -> list:
    results: list = []
    case(results, fx.proj, "nfr report ok", fx.art / "nfr-accessibility.json", NFR_OK, True)
    case(results, fx.proj,
         "nfr report bad: control not-detected with high, not-measured without limitations",
         fx.art / "nfr-accessibility.json", NFR_BAD, False, "positive_control not-detected")
    return results


def case_ledger(fx: SimpleNamespace) -> list:
    results: list = []
    case(results, fx.proj, "escape ledger ok", fx.state / "escape-ledger.jsonl", LEDGER_OK, True)
    case(results, fx.proj, "escape ledger bad: unknown without reason",
         fx.state / "escape-ledger.jsonl", LEDGER_BAD, False, "without reason")
    return results


# Order matches the register/plan built by the pre-0.7.19 script, so the printed transcript of
# a full `python form_selftest.py` run reads the same as before this file gained a main().
CASE_GROUPS = (case_register, case_plan, case_case, case_bug, case_charter, case_report,
               case_nfr, case_ledger)


def main() -> int:
    fx = build_fixture()
    results: list = []
    try:
        for group in CASE_GROUPS:
            results.extend(group(fx))
    finally:
        cleanup_fixture(fx)

    bad = 0
    for ok, name, rc, tail in results:
        print(("PASS" if ok else "FAIL"), f"[{name}] exit={rc}")
        if not ok:
            bad += 1
            for t in tail:
                print("     ", t)
    print(f"\n{len(results) - bad}/{len(results)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
