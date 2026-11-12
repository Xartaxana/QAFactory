"""RD1-20: a delivery summary older than the report it quotes does not leave the factory (S9 refreshes it once).

`delivery_summary.left_with_you_stale` compares the summary's recorded `left_with_you` with what the report's section reads
now (the ONE reader, `_left_with_you`); `stage_done._s9_report_exit` rewrites the summary once when they differ. The check
`report_facts.check` is NOT given this comparison: its callers write the report before the summary, so a refusal there
would be false every time (RD1-20 edges).

Kills: the comparison always False (the summary stays stale); the comparison always True (a rewrite on every S9);
whitespace compared as a difference; a missing or unreadable summary read as stale (a None must stay silent or say a
`report:` line); the rewrite removed from the S9 exit; a failing write turning S9 into a refusal."""
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import delivery_summary as S  # noqa: E402
import stage_done as SD  # noqa: E402

REPORT = "# T-1\n\n## Verdict\n\nx\n\n## Left with you\n\n- **TC-1** — run it yourself\n\n## Not proven\n\nnone\n"
SECTION = "## Left with you\n\n- **TC-1** — run it yourself\n"


def task_with(report=REPORT, summary=None, raw=None) -> Path:
    root = temp_dir("qa-s9-refresh-")
    task = root / "T-1"
    (task / "work").mkdir(parents=True)
    if report is not None:
        (task / "test-report.md").write_text(report, encoding="utf-8")
    if summary is not None:
        (task / "work" / "delivery-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if raw is not None:
        (task / "work" / "delivery-summary.json").write_text(raw, encoding="utf-8")
    return task


def stale_comparison() -> None:
    cases = [
        ("the summary quotes the section as it stands: not stale", dict(summary={"left_with_you": SECTION}), False),
        ("whitespace is not a difference", dict(summary={"left_with_you": SECTION.replace(" ", "  ").replace("\n\n", "\n \n")}), False),
        ("an older section: stale", dict(summary={"left_with_you": "## Left with you\n\n- none yet\n"}), True),
        ("a summary that quotes nothing while the report has the section: stale", dict(summary={"left_with_you": None}), True),
        ("no summary yet: unknown, silent (null-outcomes)", dict(), None),
        ("a summary that cannot be read: unknown", dict(raw="{not json"), None),
        ("a summary that is not an object: unknown", dict(raw="[1]"), None),
        ("no report and a summary quoting nothing: not stale", dict(report=None, summary={"left_with_you": None}), False),
    ]
    for label, kwargs, expected in cases:
        task = task_with(**kwargs)
        try:
            err = StringIO()
            with redirect_stderr(err):
                got = S.left_with_you_stale(task)
            check_eq(label, got, expected)
            if kwargs.get("raw") is not None:
                check_in("the unreadable one says so in a `report:` line", "report:", err.getvalue())
        finally:
            cleanup(task.parent)


def exit_rewrites_once() -> None:
    """The S9 exit over a stale summary: rewritten once, one printed line; a failing write is a printed line and S9 closes."""
    calls = []
    real_write, real_size, real_problems = S.write, SD.save_size, SD.report_problems
    clean = {"refusals": [], "notes": [], "stale": [], "crash": ""}
    try:
        SD.save_size = lambda *args, **kw: None
        SD.report_problems = lambda task, art: dict(clean)
        S.write = lambda art, *a, **kw: calls.append(Path(art)) or {}
        task = task_with(summary={"left_with_you": "## Left with you\n\n- none yet\n"})
        out = StringIO()
        with redirect_stdout(out):
            code, blocking = SD._s9_report_exit("T-1", task / "pipeline.json", {})
        check_eq("a stale summary: S9 closes", (code, blocking), (0, []))
        check_eq("and the summary was written once, for this task", calls, [task])
        check_in("with one printed line", "delivery summary", out.getvalue())
        cleanup(task.parent)

        calls.clear()
        task = task_with(summary={"left_with_you": SECTION})
        out = StringIO()
        with redirect_stdout(out):
            code, _ = SD._s9_report_exit("T-1", task / "pipeline.json", {})
        check_eq("the control: a summary that agrees is not written again", (code, calls), (0, []))
        check_not_in("and says nothing", "delivery summary", out.getvalue())
        cleanup(task.parent)

        task = task_with()
        out = StringIO()
        with redirect_stdout(out):
            code, _ = SD._s9_report_exit("T-1", task / "pipeline.json", {})
        check_eq("no summary at all: not written, S9 closes", (code, calls), (0, []))
        cleanup(task.parent)

        def failing(art, *a, **kw):
            raise OSError("disk full")
        S.write = failing
        task = task_with(summary={"left_with_you": "## Left with you\n\n- none yet\n"})
        out = StringIO()
        with redirect_stdout(out):
            code, blocking = SD._s9_report_exit("T-1", task / "pipeline.json", {})
        check_eq("a write that fails: S9 still closes", (code, blocking), (0, []))
        check_in("and the line says it", "could not be rewritten", out.getvalue())
        cleanup(task.parent)
    finally:
        S.write, SD.save_size, SD.report_problems = real_write, real_size, real_problems


def main() -> None:
    stale_comparison()
    exit_rewrites_once()
    finish("test_s9_summary_refresh")


if __name__ == "__main__":
    main()
