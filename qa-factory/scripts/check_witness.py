"""Detector for the "witness is mandatory" mechanism — acceptance CLI for the orchestrator.

Usage (qa-story, acceptance of Phases 2a/6/8/9):
    check_witness.py <path-to-artifact.json>  (via the run-py.cmd launcher)

Checks the required evidence fields per artifact type. An empty or missing
witness/evidence -> exit 1 (the orchestrator must reject the report).
"""
import json
import re
import sys
from pathlib import Path

try:
    import console_io
    console_io.utf8_stdio()
except ImportError:
    pass

# P6 "next: lines": the single source of the dictionary is validate_artifacts.py —
# only the import lives here (no duplication of the hint text).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_artifacts import NEXT_STEPS, _story_root
from hooklib import project_root
from detector_verdict import one_line  # noqa: E402 - a finding is one physical line in a detector's output
import contract as C  # noqa: E402
import planning_contract as PC  # noqa: E402 - the one reader of the open-question owner words (`question_owners`)

# The triage matrix is the contract's own list, not a second copy: a verdict added there (NOT_EXECUTED,
# written by code at S7) was refused here as "outside the matrix" while this file kept its own tuple.
# `TEST_BUG:collection` stays out on purpose: in triage.json it is not a verdict of its own (the test
# pins that it is refused), so the contract's list minus that word is what this check accepts.
TRIAGE_MATRIX = tuple(v for v in C.TRIAGE_VERDICTS if v != "TEST_BUG:collection")


def _register_checks(d: dict) -> list:
    reg = d.get("register")
    if not isinstance(reg, dict):
        return ["register is missing — the requirements register (requirements-register.md) was not built or not reflected: "
                "register.total and register.by_source are required"]
    errs = []
    total = reg.get("total")
    by_source = reg.get("by_source") if isinstance(reg.get("by_source"), dict) else {}
    if not isinstance(total, int) or total <= 0:
        errs.append("register.total is missing or 0 — there is no story without a single requirement")
    if not by_source:
        errs.append("register.by_source is empty — the count per source (story/feature/assumption/discussion/ac/derived) is mandatory")
    mismatch = d.get("profile_mismatch")
    if isinstance(mismatch, dict) and mismatch:
        for key in ("claimed", "observed", "evidence"):
            if not str(mismatch.get(key, "")).strip():
                errs.append(f"profile_mismatch without '{key}' — a profile revision goes to the gate only with evidence (file:line from behaviour_signals)")
    non_ac = sum(int(v) for k, v in by_source.items() if k != "ac" and isinstance(v, int))
    parent = d.get("parent_feature") if isinstance(d.get("parent_feature"), dict) else {}
    if by_source and non_ac == 0 and parent.get("id") and d.get("confidence") != "low":
        errs.append("the register consists of AC only while a parent feature was found — confidence: low is required "
                    "(AC are the developer's checkpoints, not the testing boundary; the feature and the docs were not walked)")
    return errs


def _print_next_step(name: str) -> None:
    """Fail-open: a lookup/print error must not fail a witness check that already passed."""
    try:
        hint = NEXT_STEPS.get(name)
        if hint:
            print(hint)
    except Exception:
        pass

MIN_WITNESS_LEN = 30  # anything shorter is not a "verbatim run tail" but a brush-off

# A witness that NAMES a run_suite summary must point at an existing file (quiet runs, 2026-09-11;
# the FB-27 lesson: a retelling is not a witness). Paths are relative to the project root.
EVIDENCE_SUMMARY_RE = re.compile(r"qa-factory[\\/]artifacts[\\/][^\s\"']+[\\/]evidence[\\/][^\s\"']+\.json")


def _witness_errors(value, short_msg: str) -> list:
    s = str(value or "")
    if len(s) < MIN_WITNESS_LEN:
        return [short_msg]
    m = EVIDENCE_SUMMARY_RE.search(s)
    if m and not (project_root() / m.group(0).replace("\\", "/")).exists():
        return [MISSING_FILE_MSG.format(p=m.group(0))]
    return []

MISSING_FILE_MSG = 'the witness names a run_suite summary `{p}` but no such file exists — a witness is a file, not a retelling (FB-27)'

def _excused(d: dict) -> str:
    """`acceptance.run_witness_excused`, the ONE reader of "no run to witness" (B3); a failed import is "owed"."""
    try:
        import acceptance
        return acceptance.run_witness_excused(d)
    except Exception:
        return ""


def _collect_covers(row: dict, files: set) -> bool:
    """A whole collect over every file of `files`: not `partial` (a partial collect listed only the healthy files), and its `files`
    (what `run_suite.py --collect-only` records) or the files of its `scope` node ids name every one of them."""
    if not isinstance(row, dict) or row.get("kind") != "collect" or row.get("partial"):
        return False
    named = {str(f).replace("\\", "/") for f in row.get("files") or []}
    named |= {str(n).partition("::")[0].replace("\\", "/") for n in row.get("scope") or []}
    return files <= named


def _collect_row_missing(d: dict) -> list:
    """`[]` when the manifest's `runs[]` holds a WHOLE launch of `kind: collect` over the files of every pending test (what
    `run_suite.py --collect-only` records), else the one refusal naming it and its door. A pending-only manifest has no run to
    witness, so the collect is its only evidence: a partial collect or a collect of another file stands for no pending test."""
    runs = d.get("runs") if isinstance(d.get("runs"), list) else []
    files = {str(t.get("file") or "").replace("\\", "/") for t in C.manifest_tests(d)}
    if any(_collect_covers(r, files) for r in runs):
        return []
    return ["every test of this manifest is pending implementation (its side is absent), so no run_witness is owed - but the "
            "collect is: `runs[]` holds no whole (not partial) row of `kind: collect` over " + (", ".join(sorted(files)) or "its test files")
            + "; run `run_suite.py --task <TICKET> --collect-only --tests <test files> -- <test command>` and append the row it "
            "prints through manifest_put.py --fragment"]


def _readiness_form(d: dict) -> list:
    """The FORM of requirements-readiness.json: verdict word, goal, aspects, the keys of every question. Nothing here
    reads the answers file, and the rule `severity (blocker|major|minor)` stays exactly as it was.
    The verdict word is a PROPOSED list (F-3 (b)): `ready`, `blocked`, or `new: <word> -- <why>` (the form is checked here, the
    word is the stage critic's to judge). Nothing routes on a `new:` word: `readiness_rules` reads only the two."""
    return (
        [f"verdict {problem}" for problem in C.open_word_errors(d.get("verdict"), ("ready", "blocked"), "s2_verdict")]
        + ([] if len(str(d.get("goal_summary", ""))) >= MIN_WITNESS_LEN
           else [f"goal_summary missing or shorter than {MIN_WITNESS_LEN} chars — stating the goal in your own words is mandatory"])
        + ([] if isinstance(d.get("aspects"), dict) and d.get("aspects")
           else ["aspects is empty — the applicability matrix was not built"])
        + [f"aspects.{k}: status '{(v or {}).get('status') if isinstance(v, dict) else v}' outside ready|blocked|n/a"
           for k, v in (d.get("aspects") or {}).items()
           if not isinstance(v, dict) or v.get("status") not in ("ready", "blocked", "n/a")]
        + [f"aspects.{k}: n/a without a reason — silently skipping an aspect is forbidden"
           for k, v in (d.get("aspects") or {}).items()
           if isinstance(v, dict) and v.get("status") == "n/a" and not v.get("reason")]
        + [f"open_questions[{i}]: needs question, severity (blocker|major|minor) and owner_role ({'|'.join(PC.question_owners())})"
           + (f": {PC.owner_role_flaw(q.get('owner_role'))}" if q.get("owner_role") and PC.owner_role_flaw(q.get("owner_role")) else "")
           for i, q in enumerate(d.get("open_questions", []))
           if not (q.get("question") and q.get("severity") in ("blocker", "major", "minor")
                   and not PC.owner_role_flaw(q.get("owner_role")))]
    )


def _readiness_facts(d: dict) -> tuple:
    """(question rows, a blocked aspect exists): the two facts every consistency rule reads, tolerant of a shape the
    form rules refuse on their own."""
    rows = d.get("open_questions")
    rows = rows if isinstance(rows, list) else []
    aspects = d.get("aspects") if isinstance(d.get("aspects"), dict) else {}
    return rows, any(isinstance(v, dict) and v.get("status") == "blocked" for v in aspects.values())


def _row_ids(picked: list) -> str:
    """The ids of the picked (index, row) pairs; a row with no id is named by its place."""
    return ", ".join(str(r.get("id") or f"open_questions[{i}]") if isinstance(r, dict) else f"open_questions[{i}]"
                     for i, r in picked)


CONTRADICTION_BLOCKED = ("verdict 'blocked' with no open blocker question and no blocked aspect - contradiction{settled}. "
                         "Expected: verdict 'ready', or {named}a blocked aspect named")
CONTRADICTION_READY = ("open blocker questions ({ids}) or blocked aspects with verdict 'ready' - contradiction. "
                       "Expected: verdict 'blocked' while a blocker question is still open")
NOT_CHECKED_NO_ROOT = ("the verdict was not checked against the recorded answers (no --task-root): blocker questions "
                       "{ids} may be answered already; publish checks it")


def readiness_rules(d: dict, task_root) -> list:
    """The consistency of the verdict with the facts - the rules that need the answers file. A question is an OPEN
    BLOCKER by `question_register.open_blocker` (open, changed since the answer, or unreadable, and not
    `major`/`minor`) over the file's records read for the ids of THIS data (`statuses_for`: a publish checks rows that
    are not on disk yet). `blocked` needs an open blocker or a blocked aspect; `ready` needs neither. Errors only.
    A story always has a passing state: every blocker settled or kept open on the person's word -> `ready`."""
    import question_register as QR
    verdict = d.get("verdict")
    if verdict not in ("ready", "blocked"):
        return []                # also a `new: <word> -- <why>` verdict: the form passed, no rule reads the word (F-X2-3)
    rows, blocked_aspect = _readiness_facts(d)
    merged = QR.statuses_for(task_root, rows)
    opened = [(i, r) for i, (r, q) in enumerate(zip(rows, merged)) if QR.open_blocker(q)]
    if verdict == "blocked" and not opened and not blocked_aspect:
        done = [(i, r) for i, (r, q) in enumerate(zip(rows, merged))
                if isinstance(r, dict) and r.get("severity") not in QR.NOT_BLOCKING and not QR.open_blocker(q)]
        return [CONTRADICTION_BLOCKED.format(
            settled=(f": {_row_ids(done)} are answered, not needed or kept open by the person" if done else ""),
            named="" if done else "a blocker question or ")]
    if verdict == "ready" and (opened or blocked_aspect):
        return [CONTRADICTION_READY.format(ids=_row_ids(opened) or "none")]
    return []


def _readiness_rules_unrooted(d: dict) -> tuple:
    """(errors, not_checked) with NO story root. What needs no answers file is judged on the data: `ready` over a
    blocked aspect, and `blocked` with no row of a blocking severity (the rule of `open_blocker`, read on the row
    alone) and no blocked aspect. What needs the file - are the blocker rows answered already? - is ONE
    `not_checked` line and never an error, never a pass (FR-59)."""
    import question_register as QR
    verdict = d.get("verdict")
    if verdict not in ("ready", "blocked"):
        return [], []            # a `new: <word> -- <why>` verdict: no rule reads the word, the stage critic judges it (F-X2-3)
    rows, blocked_aspect = _readiness_facts(d)
    rowwise =[(i, r) for i, r in enumerate(rows) if not isinstance(r, dict) or r.get("severity") not in QR.NOT_BLOCKING]
    if verdict == "ready" and blocked_aspect:
        return [CONTRADICTION_READY.format(ids="none")], []
    if verdict == "blocked" and not rowwise and not blocked_aspect:
        return [CONTRADICTION_BLOCKED.format(settled="", named="a blocker question or ")], []
    if rowwise and (verdict == "ready" or (verdict == "blocked" and not blocked_aspect)):
        return [], [NOT_CHECKED_NO_ROOT.format(ids=_row_ids(rowwise))]
    return [], []


def readiness_check(d: dict, task_root=None) -> dict:
    """{"errors": [...], "not_checked": [...]} for requirements-readiness.json: the form, the consistency of the
    verdict with the facts (T12a/T12b) and the register block. `not_checked` is filled only with no `task_root`,
    and it is never an error: `valid` stays `not errors`."""
    errors = _readiness_form(d)
    if task_root is None:
        found, not_checked = _readiness_rules_unrooted(d)
    else:
        found, not_checked = readiness_rules(d, task_root), []
    # WP1: the requirements register is the unit of coverage. The register block is mandatory;
    # a register consisting of AC only while a parent feature was found - confidence: low (a route
    # to the gate, not a ban: a story without a feature and docs will look exactly like that).
    return {"errors": errors + found + _register_checks(d), "not_checked": not_checked}


RULES = {
    "automation-manifest.json": lambda d: (
        ([] if _excused(d) == "handed" else
         _collect_row_missing(d) if _excused(d) == "pending" else
         _witness_errors(d.get("run_witness"), f'run_witness missing or shorter than {MIN_WITNESS_LEN} chars — the path to the run_suite summary (evidence/<label>-<ts>.json) with the exit code and the totals line is mandatory'))
        + [f"tests[{i}] without case/file/status" for i, t in enumerate(d.get("tests", []))
           if not (t.get("case") and t.get("file") and t.get("status"))]
    ),
    "run-report.json": lambda d: (
        _witness_errors(d.get("witness"), 'witness missing/too short — the run_suite summary path + exit code + totals')
        + ([] if d.get("env_preflight") in ("pass", "blocked") else ["env_preflight is not pass|blocked"])
        + ([] if isinstance(d.get("totals"), dict) else ["no totals"])
        + [f"manual_checks[{i}]: result '{m.get('result')}' outside pass|fail|inconclusive"
           for i, m in enumerate(d.get("manual_checks", []))
           if m.get("result") not in ("pass", "fail", "inconclusive")]
    ),
    "triage.json": lambda d: [
        err for i, t in enumerate(d.get("triage", []))
        for err in (
            ([f"triage[{i}]: verdict '{t.get('verdict')}' outside the matrix"]
             if t.get("verdict") not in TRIAGE_MATRIX else [])
            + ([f"triage[{i}] ({t.get('verdict')}): empty evidence — a verdict without proof is invalid"]
               if not t.get("evidence") else [])
        )
    ],
    "requirements-readiness.json": lambda d: readiness_check(d)["errors"],   # no story root: see readiness_check
    "release-readiness.json": lambda d: (
        ([] if d.get("verdict") in ("go", "go-with-risks", "no-go")
         else [f"verdict '{d.get('verdict')}' outside go|go-with-risks|no-go"])
        + ([] if len(str(d.get("evidence", ""))) >= MIN_WITNESS_LEN
           else [f"evidence missing or shorter than {MIN_WITNESS_LEN} chars — the sources of every number are mandatory"])
        + ([] if isinstance(d.get("scope"), dict) and d.get("scope", {}).get("tasks")
           else ["scope.tasks is empty — an assessment without scope is invalid"])
        + ([] if isinstance(d.get("stats"), dict) else ["no stats"])
        + ([] if isinstance(d.get("rubric_trace"), list) and d.get("rubric_trace")
           else ["rubric_trace is empty — the rubric was not walked item by item"])
        + [f"blockers[{i}]: without rule/evidence" for i, b in enumerate(d.get("blockers", []))
           if not (b.get("rule") and b.get("evidence"))]
        + [f"risks[{i}]: without rule/evidence" for i, r in enumerate(d.get("risks", []))
           if not (r.get("rule") and r.get("evidence"))]
        # verdict consistency with the facts
        + (["verdict 'no-go' with empty blockers — contradiction"]
           if d.get("verdict") == "no-go" and not d.get("blockers") else [])
        + (["blockers non-empty with verdict != 'no-go' — contradiction"]
           if d.get("verdict") != "no-go" and d.get("blockers") else [])
        + (["verdict 'go' with non-empty risks — contradiction"]
           if d.get("verdict") == "go" and d.get("risks") else [])
    ),
    "code-review.md": None,  # markdown: checked for red_probe/independent_run lines
}


def check_code_review(text: str) -> list:
    errors = []
    if "independent_run" not in text:
        errors.append("code-review: no independent_run field — the independent run is not confirmed")
    if "red_probe" not in text:
        errors.append("code-review: no red_probe field — the probe is not confirmed")
    return errors


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: check_witness.py <artifact>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print("REJECT — 1 problem(s):")
        print(f"- artifact does not exist: {path}")
        sys.exit(1)
    if path.name == "code-review.md":
        errors = check_code_review(path.read_text(encoding="utf-8", errors="replace"))
    else:
        rule = RULES.get(path.name)
        if rule is None:
            print(f"OK (no rule for {path.name} — contract undefined, add it to RULES)")
            _print_next_step(path.name)
            sys.exit(0)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print("REJECT — 1 problem(s):")
            print("- " + one_line(f"broken JSON: {e}"))
            sys.exit(1)
        if path.name == "requirements-readiness.json":
            # the story root is where `work/` is held (an older layout keeps the file in the story folder itself)
            checked = readiness_check(data, _story_root(path))
            errors = checked["errors"]
        else:
            errors = rule(data)
    if errors:
        print(f"REJECT — {len(errors)} problem(s): acceptance forbidden:")
        for error in errors:
            print("- " + one_line(error))
        sys.exit(1)
    print(f"witness OK: {path.name} — the evidence contract is satisfied")
    _print_next_step(path.name)
    sys.exit(0)


if __name__ == "__main__":
    main()
