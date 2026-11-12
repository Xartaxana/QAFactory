# -*- coding: utf-8 -*-
"""Code-level suite runner — pytest mechanics without LLM turns (operator decision 2026-09-02, FB-24).

Lesson of a live task: the runner burned 661 turns / $53 ($47 of it context cache-rebill), a large
share on line-by-line plumbing around launching suites and parsing their output. Launching and
collecting results is pure mechanics: this script does it, leaving the agent ONE turn per run and
a ready-made summary.

Usage (via the run-py.cmd launcher, from inside the project):
  run-py.cmd run_suite.py --mine TC-001[,TC-002]          # a role's ordinary "run my test"
  run-py.cmd run_suite.py --request request.json          # every other typed run, every stage
  run-py.cmd run_suite.py --schedule schedule.json        # at or above the parallel threshold
  run-py.cmd run_suite.py --request request.json --detail TEST   # why it failed; runs nothing
  run-py.cmd run_suite.py --template request|schedule     # the skeleton to fill in; runs nothing
  run-py.cmd run_suite.py --task TASK-ID --label sanity [--timeout 1800] [-- <command>]
  run-py.cmd run_suite.py --task TASK-ID --label sanity --wait [--wait-max 570]
  run-py.cmd run_suite.py --selftest

`--task/--label` is a standalone user interface. A factory role inside an open dispatch uses
`--mine`, which builds the typed request itself from the controller's open dispatch and the
manifest and runs it; `--request`/`--schedule` carry everything that is not the ordinary run,
and `--template` is how their shape is learned without guessing.

One run per window: `--mine CASE[,CASE]` runs every instance of the named cases in ONE pytest
call. A call that leaves a test of the same file and the same dispatch scope with no evidence
at all is answered `{"status": "run_the_window_first"}` with that one command, exit 2, nothing
launched — unless `--purpose repair_verify` (only what a repair touched). What makes evidence
stale is measured per test function, not per file (`instance_content_sha`), and a comment, a
docstring line or a blank line is not an edit (`instance_code_sha`). The run budget
(references/run-budget.json): a test that already holds a result over the same bytes, on the
same stand and version, is answered `reused` (green) or `already_run` (red), exit 0, and NOT
launched; a call answered in part runs only the rest. `--again` repeats no result - a person's
word does (waiver.py, block "already run on these bytes").

Around a run (0.7.8, all three degrade to "feature absent" when their module is missing):
  - node ids of a pytest request are checked against ONE real collect before launch
    (`node_ids.py`; the collect `--mine` took while it built the request is not repeated): a respelled
    id is corrected with a note, a missing one stops the launch with `{"status": "node_id_mismatch"}`
    and exit 2. An unreadable or timed-out collect leaves the ids to the run, whose pytest `not found`
    (exit 4) is answered in the summary as `blocked: node_id_mismatch`, `execution_status:
    not_executed` - never passed or failed. An explicit `--node-id` without `[...]` is not collected;
  - on a stand that is not parallel (`run.parallel: false`) the run holds the stand lease
    (`stand_lease.py`); a stand still busy after the wait is `{"status": "stand_busy"}`, exit 3;
  - the finished summary goes to `stand_health.py`; what it notices is `stand_signal`.

Default command: poetry run pytest. Everything after `--` is the run command verbatim.
What a run does:
  1) environment: HEADLESS=1 (strategy rule 6, FB-13) — unless overridden;
  2) drops a marker qa-factory/artifacts/<task>/evidence/<label>-<ts>.running (pid, start, command);
  3) runs the command with a timeout and STREAMS its output line by line into <label>-<ts>.log —
     the log grows during the run instead of appearing at the end (the CLR-4 lesson; stdout and
     stderr are merged in chronological order);
  4) reads a machine-readable report: for pytest it adds --junitxml itself; for any other
     framework the project's command writes one (JUnit XML or .NET TRX) and config.json's
     run.reporter/run.report_path say which and where. Parsed into totals, failures/errors
     by name with the first reason line, skips with aggregated reasons. No report -> the
     summary carries parse_gap saying so out loud, because a run nobody can read is recorded
     as not_executed however green its log looks. The format of an UNTYPED run is chosen by
     `reporter_choice`: explicit, run.reporter, then report-cures.json (`command_formats`, then
     the command's cure row, which the summary names as `reporter_inferred_from`; an inferred
     format that reads no tests adds a parse_gap too);
  5) teardown hygiene (FB-13): kills orphaned ms-playwright processes older than 10 minutes
     (those only, the user's Chrome is untouched; best-effort, never fails the run);
  6) prints a compact JSON summary, stores it next to the log (<label>-<ts>.json) and removes
     the .running marker.

--wait mode (measured on Phase 8 of 09.09: five suites of 20–41 minutes each, while the Bash tool
caps a call at 10 minutes — the runner waited in `sleep 600` chunks and could notice a suite's
end up to 10 minutes late). --wait is a blocking wait for an ALREADY RUNNING run with the same
label: it finds the fresh .running marker, checks every --poll seconds and returns as soon as
the summary lands. One --wait call = one agent turn, but the end of the run is noticed within
--poll seconds rather than ten minutes.
  exit 0 — the run finished, the summary is printed (its own exit_code is inside the JSON);
  exit 3 — still running: a status with elapsed time and the log tail is printed, call --wait again;
  exit 2 — nothing to wait for: neither a marker nor a summary with that label;
  exit 4 — the run died without a summary (no process, no .json ever appeared): the marker is
           removed, the log stays on disk — read it, do not blindly relaunch.
The --wait-max default of 570 s is 30 s under the tool's cap so the call returns on its own.

The script does NOT judge (verdicts belong to the Phase 9 triage) and does NOT retry on its own:
the retry policy stays in the command (pytest-rerunfailures). Run exit code = the command's (timeout → 124).

Quiet mode and targeted diagnostics (2026-09-11, after STLC MR !136 + the 14336 measurement: direct pytest
calls of the automator and the critic put ~160K characters into their contexts against ~20K through
run_suite for the runner):
  - pytest gets -q by default (a shorter log, the same summary); --verbose keeps it off;
  - --detail <test>: the failure text of ONE test from the already recorded report (JUnit XML or
    .NET TRX, the one the run's summary names) of the latest run with this label (message +
    traceback, clipped head and tail by --max-chars) — no re-run and no reading of the raw log.
    exit 0 — found, 2 — no such test/report (the failed names are printed; no report at all is
    `no_report`, with `no_junitxml` kept as the same answer for older readers).
    Reachable under an open dispatch in both spellings, and neither launches anything:
    `--task T --label L --detail TEST` and `--request FILE --detail TEST` (the label is that
    request's last recorded run; a request already written for the NEXT run finds the
    previous one by its instances, so no fresh idempotency key is spent on reading).
  - a run in which nothing ran (pytest exit 2-5, or no test collected) names its cause in the
    summary as `error_head`: the ERROR / `E   ` / usage / import lines of the log.
  - every role (automator, critic, hardening, analyst) runs tests only this way; a direct pytest in
    Bash is caught by guard_pre_tool.
"""
import argparse
import contextlib
import copy
import glob as globlib
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import artifacts_dir, project_root, load_config, story_root, StoryRootError, read_json
from execution_request import (JobStore, ProvenanceRefused, RequestError, is_pytest_command, probe_record,
                               pytest_timeout_setting, validate_request)
from execution_fingerprint import verify_files
from profile_contract import ACCEPTS, acceptable_provenance
from role_cli import REPAIR_MARKER
import reporters
import report_cures
import launch_check
import node_ids as _node_ids  # bound at import: probe_runtime's bounded launcher (the "no collector" branch imports node_ids lazily)
import project_env # EP1-35: checked_launch, the one resolver of a launch's head (a `.cmd` wrapper's unsafe argument is refused)

WAIT_MAX_DEFAULT = 570  # the Bash tool caps a call at 600 s; we return before it does
POLL_DEFAULT = 10


# How many PASSED rows are listed by name before the list is cut to a count. Everything not
# passed is always listed in full: a green test nobody needs to name is noise, a skipped one
# with no name is the defect this cap exists to avoid re-creating.
RESULT_ROWS_CAP = 500


def parse_junitxml(path: Path) -> dict:
    """Totals, failures by name, skip reasons — and one `results[]` row per test.

    `results[]` is the part that was missing until 0.3.0. This function returned skip reasons
    as a Counter keyed by the reason TEXT, so a skipped test had no name anywhere in the
    output; the role writing `run-report.json` then had nothing to paste, and TP2-2290
    reached the dashboard as nine rows with no case, no status and no reason — printed as
    "?" and labelled `regression`, which is a fact nobody recorded. The names are right here
    in the XML; reading them is free.

    The ROWS come from `reporters.read_rows` (the one reader of a report, shared with red_sandbox
    and probe_by_code); this function keeps what is run_suite's own: the totals, which are the
    report's counters and not a count of rows, the clipping of the reason text, the skip-reason
    tally and the cap on passed rows. A testcase inside nested suites is ONE row: this function
    used to list it once per ancestor suite.

    Totals and rows answer one question, so a report cannot state a total its rows do not add up
    to: the report's counters stand as written while their `tests` agree with the number of rows
    (every flat report, as before); when they do not - nested suites whose ancestors count a
    testcase again, a testcase outside any suite, a counter that lies - the counts are the rows'
    own, by status. `time_s` is the suites' time as written either way (rows carry none)."""
    root = ET.parse(path).getroot()
    rows = reporters.read_rows(path, "junit-xml")
    suites = root.iter("testsuite") if root.tag == "testsuites" else [root]
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time_s": 0.0}
    for su in suites:
        totals["tests"] += int(su.get("tests") or 0)
        totals["failures"] += int(su.get("failures") or 0)
        totals["errors"] += int(su.get("errors") or 0)
        totals["skipped"] += int(su.get("skipped") or 0)
        totals["time_s"] += float(su.get("time") or 0)
    if totals["tests"] != len(rows):
        by_status = Counter(row["status"] for row in rows)
        totals.update(tests=len(rows), failures=by_status["failed"], errors=by_status["error"],
                      skipped=by_status["skipped"])
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    totals["time_s"] = round(totals["time_s"], 1)
    failed, skip_reasons, results = [], Counter(), []
    for row in rows:
        reason = ""
        # The first <failure> and the first <error> of a testcase, failure first; the later of
        # the two is the row's reason (error outranks failure), as it always was.
        for kind in ("failure", "error"):
            problem = next((p for p in row["problems"] if p["kind"] == kind), None)
            if problem is not None:
                why = _first_line(problem["message"] or problem["text"])
                failed.append({"test": row["test_id"], "kind": kind, "why": why})
                reason = why
        if row["status"] == "skipped":
            skipped = next((p for p in row["problems"] if p["kind"] == "skipped"), None)
            reason = ((skipped or {}).get("message") or "")[:160] or "(no reason)"
            skip_reasons[reason[:80]] += 1
        results.append({"test_id": row["test_id"], "status": row["status"], "reason": reason})
    results, passed_seen = _cap_passed_rows(results)
    out = {"totals": totals, "failed": failed, "results": results,
           "skip_reasons": dict(skip_reasons.most_common(12))}
    if passed_seen > RESULT_ROWS_CAP:
        out["results_note"] = _passed_rows_note(passed_seen)
    return out


def _first_line(text: str) -> str:
    """The first line of a message or a stack, 160 characters at most — the `why` of a failed row."""
    lines = (text or "").strip().splitlines()
    return lines[0][:160] if lines else ""


def _cap_passed_rows(results: list) -> tuple:
    """(rows to list, how many passed rows the report had). Only PASSED rows past the cap are
    dropped: a failed, error, skipped or not_run row is always listed, because a failure
    that fell off the end of a list is a failure nobody was told about. `parse_trx` capped every
    row at 500 and lost the failures of a large .NET suite, while parse_junitxml already
    capped passed rows only; the two now share this one rule."""
    listed, passed_seen = [], 0
    for row in results:
        if row["status"] == "passed":
            passed_seen += 1
            if passed_seen > RESULT_ROWS_CAP:
                continue
        listed.append(row)
    return listed, passed_seen


def _passed_rows_note(passed_seen: int) -> str:
    return (f"{passed_seen - RESULT_ROWS_CAP} passed rows beyond the "
            f"{RESULT_ROWS_CAP}-row cap are counted in totals, not listed")


REPORTERS = ("pytest", "junit-xml", "trx", "none")


def parse_trx(path: Path) -> dict:
    """The same summary shape, read from a .NET TRX file.

    `dotnet test` writes TRX by default and JUnit only when asked. Both carry the totals and
    the per-test outcomes; what the factory could read until now was neither, so a .NET run
    of `Passed: 10, Failed: 0, Total: 10` was recorded as `not_executed`, and a genuine test
    failure was indistinguishable from a broken MSBuild — both were `broken_run`. Downstream
    roles then rebuilt the results by hand out of the raw log.

    The rows come from `reporters.read_rows`, which maps every outcome to the vocabulary every
    consumer compares against: a result with NO outcome is `not_run` (it used to be reported as
    `passed`: an unknown reported as a fact, FR-41), `Timeout` / `Aborted` are `error`. The
    totals are the report's own `Counters`. Only PASSED rows are capped, as in the JUnit reader."""
    root = ET.parse(path).getroot()
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time_s": 0.0}
    for node in root.iter():
        if node.tag.rpartition("}")[2] == "Counters":
            totals["tests"] = int(node.get("total") or 0)
            totals["failures"] = int(node.get("failed") or 0)
            totals["errors"] = int(node.get("error") or 0)
            totals["skipped"] = int(node.get("notExecuted") or 0) + int(node.get("inconclusive") or 0)
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    failed, results = [], []
    for row in reporters.read_rows(path, "trx"):
        # The reason is the first line of the row's own message (a skip's reason, a failure's text).
        why = next((_first_line(p["message"]) for p in row["problems"] if p["message"]), "")
        if row["status"] in ("failed", "error"):
            failed.append({"test": row["test_id"], "kind": row["status"], "why": why})
        results.append({"test_id": row["test_id"], "status": row["status"], "reason": why})
    results, passed_seen = _cap_passed_rows(results)
    out = {"totals": totals, "failed": failed, "results": results, "skip_reasons": {}}
    if passed_seen > RESULT_ROWS_CAP:
        out["results_note"] = _passed_rows_note(passed_seen)
    return out


# What a cure row may say its command writes (the vocabulary the table's own note gives). `pytest` is not one:
# the runner equips pytest itself, so a row naming it would switch the pytest path on for a command that is not.
INFERRED_KINDS = ("junit-xml", "trx")


def _command_formats(table: dict) -> list:
    """The usable entries of `command_formats` in references/report-cures.json: `{"kind": <a reporter>,
    "contains": [words]}`, in file order. A table without the key (a file older than the key), a key that is
    not a list, and an entry of another shape contribute nothing and never raise: this table only chooses a
    reader for a report, and the choice must not stop a run. An entry holding an empty word is dropped whole,
    because the empty word is in every command line."""
    entries = table.get("command_formats")
    if not isinstance(entries, list):
        return []
    return [e for e in entries
            if isinstance(e, dict) and e.get("kind") in REPORTERS and isinstance(e.get("contains"), list)
            and all(isinstance(w, str) and w for w in e["contains"])]


def reporter_choice(cmd: list, cfg: dict, explicit: str) -> tuple:
    """(the report this run will produce, the cure row it was inferred from or ''). In order:
    1. the explicit choice (a typed run passes its request's reporter here, so inference only ever reaches
       an untyped run: a request's declared reporter is never overridden);
    2. the project's `run.reporter` (the profile's recorded kind is a typed run's reporter, so it arrives as 1);
    2b. a pytest-shaped command (`is_pytest_command`, the one gate of the pytest path) is pytest, whatever the table
       says or fails to say;
    3. `command_formats` of report-cures.json, a substring table checked in file order: pytest, then trx,
       then junit-xml. The ORDER is the invariant: it runs before the rows of step 4, so `dotnet test` stays
       junit-xml and never becomes the dotnet row's trx, and a pytest command whose path says `karma` stays pytest;
    4. the cure row of the command (`report_cures.row_for`) when it names the format it writes: the second
       element is that row's id, and run() says it in the summary (`reporter_inferred_from`);
    5. none.
    A table that cannot be read gives none for a command that is not pytest-shaped; step 5 is the same none."""
    if explicit:
        return explicit, ""
    declared = str(((cfg or {}).get("run") or {}).get("reporter") or "").strip()
    if declared in REPORTERS:
        return declared, ""
    if is_pytest_command(cmd):
        # The pytest path is decided by this one predicate, never by data (amendment 6): no table entry, row or
        # reordering of the table can hand a pytest-shaped command (`py.test tests/karma`) to another reader, and
        # a table that is missing, old or unreadable leaves it pytest.
        return "pytest", ""
    try:
        table = report_cures.load()
    except report_cures.CureTableUnreadable:
        return "none", ""
    text = " ".join(str(c) for c in cmd).lower()
    for entry in _command_formats(table):
        if any(word.lower() in text for word in entry["contains"]):
            return entry["kind"], ""
    row = report_cures.row_for(cmd, table["rows"])
    if row and row.get("reporter_kind") in INFERRED_KINDS:
        return row["reporter_kind"], str(row.get("id") or "unnamed")
    return "none", ""


def resolve_reporter(cmd: list, cfg: dict, explicit: str) -> str:
    """Which machine-readable report this run will produce: `reporter_choice` without the row it came from."""
    return reporter_choice(cmd, cfg, explicit)[0]


def report_path(cfg: dict) -> Path | None:
    raw = str(((cfg or {}).get("run") or {}).get("report_path") or "").strip()
    return (project_root() / raw) if raw else None


# The exact cure for "this command writes no report the factory can read", per framework. The
# words live in ONE data file, references/report-cures.json, read through ONE module
# (report_cures.py, a leaf: no gate, no runner in its imports) by three callers: this runner,
# when it happens in the middle of a run, the gate A rehearsal's card (it calls this function),
# and the onboarding probe, which proves the reporter on one existing test BEFORE the person
# is asked. On TP2-2553 Karma ran with progress/kjhtml/coverage and no
# `karma-junit-reporter` in the project's dependencies; the cure was already written here and
# was read for the first time inside S5, on the first real run, and a window went on it.
def report_cure(argv) -> str:
    """The change that makes THIS command write a report the factory can read, or '' when the
    framework needs none (pytest), when the command names no framework we know a flag for, and
    when the words table cannot be read.

    The invariant behind that last case: a run's outcome never depends on the cure words. They
    only decorate a message about a run that already went wrong, so a missing or broken table
    gives '' here (the probe, whose whole subject is the table, says it could not be read) and
    never an exception in the runner."""
    try:
        return report_cures.cure_words(argv)
    except report_cures.CureTableUnreadable:
        return ""


def no_report_words(argv, reporter: str) -> str:
    """The `parse_gap` of a run that left no report to read. The cure is the command's own row's words
    (`report_cure`: the one home, report-cures.json), and the generic sentence when no row names the
    command or the table cannot be read. The opening phrase is a contract: a summary carrying a `parse_gap`
    is doubt, never a precedent (execution_request reads its presence)."""
    cure = (report_cure(argv) or "Make the command write a JUnit XML or TRX report").rstrip(" .;")
    return (f"this command produces no report the factory can read (reporter: {reporter}). "
            "A run with no report is recorded as not_executed however green its log is, and a "
            f"failed test cannot be told from a broken launcher. {cure}, and set run.reporter "
            "and run.report_path in qa-factory/config.json so it is read every time.")


def inferred_read_words(reporter: str, row_id: str) -> str:
    """The `parse_gap` of a run whose report format was GUESSED from a cure row and whose report then read as
    nothing (zero tests, or unreadable): the guess may be the wrong format, and a wrong reader reports exactly this."""
    return (f"the report format `{reporter}` was inferred from the cure row `{row_id}` and reading it found no "
            "tests: set run.reporter in qa-factory/config.json to the format this command writes")


def teardown_playwright() -> str:
    """Global process scans are forbidden; a request may clean only recorded ownership."""
    return "teardown: no owned external sessions recorded"


def pid_alive(pid: int) -> bool:
    """Best-effort: if the check fails, assume alive (waiting beats declaring a death)."""
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                               capture_output=True, text=True, timeout=15)
            return True if r.returncode != 0 else str(pid) in (r.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return True


def process_started_at(pid: int) -> str:
    """Best-effort PID birth identity; an empty value is never treated as proof of death."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ""
            try:
                created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
                if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                                ctypes.byref(kernel), ctypes.byref(user)):
                    return ""
                ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
                unix_100ns = ticks - 116444736000000000
                seconds, remainder = divmod(unix_100ns, 10_000_000)
                return datetime.fromtimestamp(seconds, timezone.utc).replace(
                    microsecond=remainder // 10).isoformat()
            finally:
                kernel32.CloseHandle(handle)
        return datetime.fromtimestamp(Path(f"/proc/{int(pid)}").stat().st_ctime,
                                      timezone.utc).isoformat()
    except Exception:
        return ""


def same_process(pid: int, expected_started_at: str) -> bool:
    observed = process_started_at(pid)
    if not (pid > 0 and expected_started_at and observed):
        return False
    if observed == expected_started_at:
        return True
    try:
        # Older Windows receipts used .NET's seven fractional digits and Z; the native
        # API preserves the same identity at Python datetime's microsecond precision.
        return datetime.fromisoformat(observed.replace("Z", "+00:00")) == datetime.fromisoformat(
            expected_started_at.replace("Z", "+00:00"))
    except ValueError:
        return False


# The per-instance body hashes a run block row carries beside the file-level fingerprint.
INSTANCE_SHA_KEYS = ("instance_content_sha", "instance_content_scope", "instance_code_sha")


def selection_line(block, block_path="") -> str:
    """The ONE console line of a run whose report holds fewer of the selected tests than were selected (RN1-21, N1-2); "" when
    it holds them all, or the run selected none (a whole-suite run is not called short), or the run is inconclusive (its rows are
    forced `not_run` by a changed runtime or input, so a short count would blame selectors that are right; the rows carry that cause).
    It names no runner: the role reads the `selector_args` of the unmatched instances (FR-1; the reader of
    `report_scope.selection_count`, AR-22)."""
    if (block or {}).get("execution_status") == "inconclusive":
        return ""
    count = ((block or {}).get("report_scope") or {}).get("selection_count")
    if not isinstance(count, dict):
        return ""
    selected, matched, rows = (int(count.get(k) or 0) for k in ("selected", "matched", "report_rows"))
    if selected < 1 or matched >= selected:
        return ""
    return (f"selection: {matched} of {selected} selected tests are in the report ({rows} report rows); a runner that keeps "
            "one value of a repeated option runs one of them, and a pattern the runner matches against more than the title "
            "may match none - check the selector_args of the unmatched instances "
            f"(run block {block_path}, report_scope.unmatched_report_rows)")


def build_run_block(request: dict, summary: dict, attempt_id: str) -> dict | None:
    """Map reporter identities to selected instances exactly; never infer by order/name fragments."""
    if request.get("purpose") == "red_probe" or request.get("evidence_phase") == "baseline":
        return None
    selected = request.get("selected_instance_ids") or []
    if not selected:
        return None
    rows = summary.get("results") if isinstance(summary.get("results"), list) else []
    by_test: dict[str, list[dict]] = {}
    for row in rows:
        if isinstance(row, dict):
            by_test.setdefault(str(row.get("test_id") or ""), []).append(row)
    results = []
    contracts = request.get("instance_contracts") or {}
    repo_id = str((request.get("execution") or {}).get("repo_id") or
                  (request.get("command") or {}).get("repo_id") or "")
    runtime = request.get("runtime_provenance") or {}
    data_seed = (request.get("execution") or {}).get("data_seed_contract") or {}
    equivalence_verified = bool(
        runtime.get("result") == "matched" and runtime.get("evidence_refs") and
        data_seed.get("result") == "matched" and data_seed.get("evidence_refs"))
    timeout_block = summary.get("timeout") if isinstance(summary.get("timeout"), dict) else {}
    timed_out = set(timeout_block.get("tests") or []) if timeout_block.get("how") in PROJECT_TIMEOUT_HOWS else set()
    # EP1-37: a contract with a `file` (a selection built from a file) is matched by the ONE matcher, `red_sandbox.selection_rows`;
    # a contract without one keeps every line below it byte for byte. `claims`: the selected instances each report
    # row was matched to - one row that two different selected instances claim is nobody's (the error goes to `not_run`).
    from red_sandbox import selection_rows
    report_rows = [r for r in rows if isinstance(r, dict)]
    by_file: dict[str, list] = {}
    claims: dict[int, set] = {}
    for instance_id in selected:
        own = contracts.get(instance_id)
        if isinstance(own, dict) and own.get("file"):
            by_file[instance_id] = selection_rows(report_rows, own)
            for hit in by_file[instance_id]:
                claims.setdefault(id(hit), set()).add(instance_id)
    for instance_id in selected:
        contract = contracts.get(instance_id) or {}
        report_id = str(contract.get("report_test_id") or "")
        matches = by_test.get(report_id, [])
        reason_code = ""
        if instance_id in by_file:
            if summary.get("execution_status") == "inconclusive":
                status, matched = "not_run", False
                reason = (summary.get("runtime_change_error") or summary.get("input_change_error") or
                          "execution evidence is inconclusive")
            else:
                status, reason, matched, reason_code = _file_verdict(by_file[instance_id], contract, report_rows, claims)
        else:
            if not matches and report_id:
                # No collect (execution_request._spell_as_collected returns the rows as typed) leaves a predicted id
                # without the parameter a plugin adds (`f` for the reported `f[chromium]`): the one matcher of the
                # probe (HF4-12), limited to rows of the same module/class so a neighbour file's `f[...]` is no match.
                from red_sandbox import matching_rows
                head = report_id.rpartition("::")[0]
                matches = matching_rows([r for r in rows if isinstance(r, dict)
                                         and str(r.get("test_id") or "").rpartition("::")[0] == head], report_id)
            if summary.get("execution_status") == "inconclusive":
                status = "not_run"
                reason = (summary.get("runtime_change_error") or summary.get("input_change_error") or
                          "execution evidence is inconclusive")
                matched = False
            elif len(matches) == 1:
                source = matches[0]
                status, reason = source.get("status", "not_run"), source.get("reason", "")
                matched = True
            else:
                status = "not_run"
                reason = ("report row missing" if not matches else
                          "report identity is ambiguous; multiple rows matched")
                matched = False
        if report_id in timed_out and summary.get("execution_status") != "inconclusive":
            # RH2-9: the project's timeout killed THIS test; the code replaces `_file_verdict`'s (m-4) and says whose limit it was
            reason_code = PROJECT_TIMEOUT_CODE
            if timeout_block.get("how") == "hard_kill":
                reason = timeout_block.get("sentence") or reason
        row = {"instance_id": instance_id, "test_id": report_id,
               "case_version_links": contract.get("case_version_links") or [],
               "obligation_ids": contract.get("obligation_ids") or [],
               "parameters": contract.get("parameters") or {},
               "status": status, "reason": reason, "report_matched": matched,
               "attempt_id": attempt_id, "purpose": request.get("purpose"),
               "repo_id": repo_id, "profile_id": request.get("profile_id"),
               "equivalence_verified": equivalence_verified,
               "input_fingerprint": request.get("input_fingerprint"),
               "source_fingerprint": request.get("fingerprint_components")}
        if reason_code:
            row["reason_code"] = reason_code    # a FIELD, not a phrase (FR-12): the console line and the summary count it
        # What THIS test was over these bytes, beside the whole-file fingerprint of the run:
        # an edit to a neighbour in the same file no longer makes this row's evidence stale.
        if contract.get("instance_content_sha"):
            row["instance_content_sha"] = str(contract["instance_content_sha"])
            row["instance_content_scope"] = str(contract.get("instance_content_scope") or "function")
        # The same bytes with comments, docstrings and blank lines taken out. It rides on the row
        # so a later step can tell a cosmetic edit from a changed test without reading the job
        # record. A contract with none (an old request) gives a row with no key, never "".
        if contract.get("instance_code_sha"):
            row["instance_code_sha"] = str(contract["instance_code_sha"])
        results.append(row)
    # RN1-21 (N1-2): how many selected tests the report holds. A short count is SAID (the console line, `selection_line`), never
    # judged, and no row is coded for it: the rows keep `not_run` and the code they already have (E7). An ambiguous row is in the
    # report, so "short" would be a false cause (critic t-1748 F1); a run that is inconclusive says its own cause per row.
    matched_count = sum(1 for r in results if r.get("report_matched"))
    block = {"schema_version": 2, "block_id": attempt_id, "attempt_id": attempt_id,
            "attempt_started_at": summary.get("started_at"),
            "attempt_ended_at": summary.get("ended_at"),
            "dispatch_id": request.get("dispatch_id"), "profile_id": request.get("profile_id"),
            "repo_id": repo_id, "equivalence_verified": equivalence_verified,
            "data_seed_contract": data_seed or None,
            "selection_provenance": (request.get("execution") or {}).get("selection"),
            "purpose": request.get("purpose"), "input_fingerprint": request.get("input_fingerprint"),
            "source_fingerprint": request.get("fingerprint_components"),
            "runtime_provenance": request.get("runtime_provenance"),
            "execution_status": summary.get("execution_status"), "results": results,
            "evidence": [{"summary": summary.get("summary_path", ""),
                          "reporter": summary.get("reporter", "none"),
                          "report_path": (summary.get("report_evidence") or {}).get("path", ""),
                          "report_sha256": (summary.get("report_evidence") or {}).get("sha256", "")}],
            "reporter_mapping": {"mode": "exact", "source_attempt_id": attempt_id,
                                 "raw_report_hash": (summary.get("report_hash") or
                                                     (summary.get("report_evidence") or {}).get("sha256")),
                                 "reparsed": bool(summary.get("reparsed"))},
            "report_scope": {"selected": selected,
                             "selection_count": {"selected": len(selected), "matched": matched_count,
                                                 "report_rows": len(report_rows)},
                             "unmatched_report_rows": sorted(set(by_test) -
                                {str((contracts.get(i) or {}).get("report_test_id") or "") for i in selected}
                                - {str(r.get("test_id") or "") for found in by_file.values() for r in found})}}
    # t-2181 PC-5a (B2): the sides this execution met, copied by CODE from the story's record at the moment of the run (S13: only
    # a story that has a `pipeline.sides` record, a non-real side or `sides_unknown` is stamped; any other block stays as it was)
    block.update(proof_stamp(request.get("task")))
    # t-2277 W1 (owner 11.11.2026): a run whose target is the story's reference stand is a SAMPLE - the one field of the mark, written where the
    # run record is written (never read back from the story at a later moment). {} (no key) for every other run, an older block included.
    mark = reference_mark_of(request)
    if mark:
        block["reference_run"] = mark
    return block


def reference_mark_of(request) -> dict:
    """The `reference_run` mark of a request (`stand_identity.reference_run_mark` of its task and its probe's `environment_id`, the stand
    the launch trusts), {} when it has none, the request names no story or stand, or anything cannot be read. Never raises."""
    try:
        provenance = request.get("runtime_provenance") if isinstance(request, dict) else None
        task = str(request.get("task") or "").strip() if isinstance(request, dict) else ""
        stand = str(provenance.get("environment_id") or "").strip() if isinstance(provenance, dict) else ""
        if not (task and stand):
            return {}
        import stand_identity as SI
        return SI.reference_run_mark(project_root(), task, stand)
    except Exception:
        return {}


PROOF_STAMP_KEYS = ("sides_met", "sides_unknown")   # the keys of the proof stamp: the one list of them (writers, reparse, import re-check)


def story_pipeline(path) -> tuple[dict, str]:
    """(pipeline, why) of one story's `pipeline.json`, read through `hooklib.read_json` (BOM-safe, the reader `acceptance` and
    `side_realities` use). `why` is "" when the record can be used. An ABSENT file is ({}, "") - the story has no record. A file
    that is present but not a JSON object, or a `sides` that is present and not a non-empty object, is `why` words: the story's
    sides are UNKNOWN, never the reader's default (AR-28, FR-59)."""
    path = Path(path)
    if not path.exists():
        return {}, ""
    pipeline = read_json(path, None, kind=dict)
    if pipeline is None:
        return {}, "the story's pipeline.json could not be read"
    if "sides" in pipeline and not (isinstance(pipeline["sides"], dict) and pipeline["sides"]):
        return pipeline, "pipeline.sides is not a side record"
    return pipeline, ""


def proof_stamp(task_or_pipeline) -> dict:
    """The proof stamp of an execution block (t-2181 PC-5a, B2, AR-14/AR-21/AR-22): {} or {"sides_met": {side: reality},
    ["sides_unknown": why]}, read through `contract.story_sides` (the one reader, AR-13) from the story's `pipeline.json`
    (`task_or_pipeline`: the story id, a story root `Path`, or the parsed pipeline). ONE function for both writers, the run block
    here and `manual_evidence.write_block` (kept here rather than beside `story_sides` in contract.py: that file is another
    node's, a later move). S13: {} unless the story has a `pipeline.sides` record, a side that is not `real` or
    `pipeline.sides_unknown`. Error direction (AR-28): no pipeline.json at all is {} (no record exists to copy); a file that is
    present and unreadable, or a `sides` that is not a side record, stamps `sides_unknown` and no `sides_met` (the reader's
    default side is all-real, a guess); a reality the record does not name is copied as "" (unknown, never real)."""
    import contract as C
    pipeline, why = task_or_pipeline, ""
    if not isinstance(pipeline, dict):
        if not task_or_pipeline:
            return {}
        try:
            path = (Path(task_or_pipeline) if isinstance(task_or_pipeline, Path) else artifacts_dir(str(task_or_pipeline))) / "pipeline.json"
        except ValueError:
            return {}
        pipeline, why = story_pipeline(path)
    elif "sides" in pipeline and not (isinstance(pipeline["sides"], dict) and pipeline["sides"]):
        why = "pipeline.sides is not a side record"
    unknown = pipeline.get("sides_unknown")
    if why:
        return {"sides_unknown": str((unknown.get("why") or unknown.get("at") or why) if isinstance(unknown, dict) else (unknown or why))}
    if not pipeline:
        return {}
    sides = C.story_sides(pipeline)
    if not (pipeline.get("sides") or unknown or any(side["reality"] != "real" for side in sides.values())):
        return {}
    # the reader's default side (no record) is all-real: beside an unknown it is a guess, so it is not copied as `sides_met`
    stamp = {} if (unknown and not pipeline.get("sides")) else {"sides_met": {name: side["reality"] for name, side in sides.items()}}
    if unknown:
        stamp["sides_unknown"] = str(unknown.get("why") or unknown.get("at") or "unknown") if isinstance(unknown, dict) else str(unknown)
    return stamp


NEAREST_NOTE = "nearest"


def _file_verdict(found: list, contract: dict, report_rows: list, claims: dict) -> tuple:
    """(status, reason, report_matched, reason_code) of a contract with a `file` over the report rows `selection_rows` found for
    it (EP1-37, B-5). Every row is judged, not the first: one green row never closes a red one. No row is `id_not_in_report` with
    the nearest name when one is close enough; rows of different files, or a row another selected instance also claims, are
    ambiguous (`not_run`; `claims` is keyed by selected instance); every red wins over green; `skipped` and `passed` together, no red, is `skipped` and names the
    skipped rows. `reporters.STATUSES` is not widened: `not_run` already has its moves."""
    from red_sandbox import classnames_differ, nearest_row, _report_parts
    if not found:
        near = nearest_row(report_rows, contract)
        return "not_run", "id not in report" + (f"; {NEAREST_NOTE}: {near}" if near else ""), False, "id_not_in_report"
    if classnames_differ(found) or any(len(claims.get(id(r), ())) > 1 for r in found):
        return "not_run", "report identity is ambiguous; multiple rows matched", False, ""
    states = [str(r.get("status") or "not_run") for r in found]

    def first(kind: str) -> str:
        row = next(r for r in found if r.get("status") == kind)
        why = str(row.get("reason") or "")
        return f"{_report_parts(row)[1]}: {why}" if why else _report_parts(row)[1]
    for kind in ("failed", "error"):
        if kind in states:
            return kind, first(kind), True, ""
    if all(s == "passed" for s in states):
        return "passed", "", True, ""
    if all(s == "skipped" for s in states):
        return "skipped", "", True, ""
    if set(states) <= {"passed", "skipped"}:
        skipped = [_report_parts(r)[1] for r in found if r.get("status") == "skipped"]
        return "skipped", f"{len(skipped)} of {len(found)} rows skipped: {', '.join(skipped)}", True, ""
    return "not_run", "a matched report row has no result", True, ""


def block_folder(block: dict) -> str:
    """The folder under `work/` a run block lives in: a sample (`reference_run`, t-2277 W1) goes to `work/reference-runs`, never into the
    folder every evidence reader reads (AR-13, AR-15). The one choice, used by every writer of a run block (run, reparse, import)."""
    import stand_identity as SI
    return SI.REFERENCE_RUNS_DIR if isinstance(block, dict) and block.get("reference_run") else "run-blocks"


def write_run_block(task: str, block: dict) -> Path:
    folder = block_folder(block)
    directory = story_root(task, "run_suite") / "work" / folder      # under a story that EXISTS (CX1-18)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{stamp}-{block['attempt_id']}.json"
    payload = json.dumps(block, ensure_ascii=False, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except FileExistsError as exc:
        raise RuntimeError("immutable run block already exists") from exc
    return path


def reparse_run_block(task_root: Path, block_path: Path, mapping: dict) -> Path:
    """Reparse immutable reporter bytes with a corrected exact map; never launch tests."""
    task_root, block_path = Path(task_root).resolve(), Path(block_path).resolve()
    if not block_path.is_relative_to(task_root) or not block_path.is_file():
        raise RequestError("reparse block must be an existing task-local run block")
    old = json.loads(block_path.read_text(encoding="utf-8"))
    old_block_id = str(old.get("block_id") or old.get("id") or "")
    if not old_block_id:
        raise RequestError("reparse requires a canonical immutable block_id")
    evidence = next((row for row in old.get("evidence") or []
                     if isinstance(row, dict) and row.get("reporter") in {"trx", "junit-xml", "pytest"}), None)
    if not evidence:
        raise RequestError("run block has no machine reporter evidence")
    raw = Path(str(evidence.get("report_path") or ""))
    report = (task_root / raw).resolve() if not raw.is_absolute() else raw
    if (raw.is_absolute() or not report.is_relative_to(task_root) or not report.is_file() or
            hashlib.sha256(report.read_bytes()).hexdigest() != evidence.get("report_sha256")):
        raise RequestError("raw reporter evidence is missing, unsafe or changed")
    contracts = mapping.get("instance_contracts") if isinstance(mapping, dict) else None
    if not isinstance(contracts, dict):
        raise RequestError("mapping requires instance_contracts")
    selected = [str(row.get("instance_id") or "") for row in old.get("results") or [] if row.get("instance_id")]
    if set(contracts) != set(selected):
        raise RequestError("mapping must cover exactly the prior selected instances")
    report_ids = [str((contracts.get(i) or {}).get("report_test_id") or "") for i in selected]
    if any(not value for value in report_ids) or len(set(report_ids)) != len(report_ids):
        raise RequestError("mapping reporter IDs must be non-empty and unique")
    reporter = evidence["reporter"]
    parsed = parse_trx(report) if reporter == "trx" else parse_junitxml(report)
    parsed.update({"execution_status": execution_status({"exit_code": 1 if parsed.get("failed") else 0, **parsed}),
                   "reporter": reporter, "report_hash": evidence["report_sha256"],
                   "report_evidence": {"path": raw.as_posix(), "sha256": evidence["report_sha256"]},
                   "reparsed": True,
                   # The attempt is the same attempt: its clock comes from the block being
                   # reparsed. Without it finalize_task cannot order this attempt against a later
                   # one on the same instance and marks the instance `ambiguous_attempt_order`
                   # for good (TP1-13797 judge-on, FB-9).
                   "started_at": old.get("attempt_started_at"), "ended_at": old.get("attempt_ended_at")})
    old_rows = {str(row.get("instance_id")): row for row in old.get("results") or [] if isinstance(row, dict)}
    for instance, contract in contracts.items():
        prior = old_rows.get(instance, {})
        contract.setdefault("parameters", prior.get("parameters") or {})
        contract.setdefault("case_version_links", prior.get("case_version_links") or [])
        contract.setdefault("obligation_ids", prior.get("obligation_ids") or [])
        # What the test was over THIS attempt's bytes is a fact of the prior row, not of the
        # mapping: a reparse re-reads the same raw report of the same attempt, and a sha the
        # mapping brings describes whatever file the role has now. So the mapping's values are
        # taken out and the prior row's put back; a prior row without them (a block written
        # before they existed) leaves the reparse row without them, nothing is invented.
        for key in INSTANCE_SHA_KEYS:
            contract.pop(key, None)
            if prior.get(key):
                contract[key] = prior[key]
    request ={"purpose": old.get("purpose"), "selected_instance_ids": selected,
               "dispatch_id": old.get("dispatch_id"), "profile_id": old.get("profile_id"),
               "input_fingerprint": old.get("input_fingerprint"),
               "fingerprint_components": old.get("source_fingerprint") or {},
               "runtime_provenance": old.get("runtime_provenance") or {},
               "execution": {"repo_id": old.get("repo_id")}, "instance_contracts": contracts}
    attempt = str(old.get("attempt_id") or old.get("block_id") or "")
    block = build_run_block(request, parsed, attempt)
    material = json.dumps(contracts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    block["block_id"] = attempt + "-reparse-" + hashlib.sha256(material).hexdigest()[:12]
    block["supersedes_block_id"] = old_block_id
    # PC-5a: a reparse re-reads the same attempt, so the stamp is the superseded block's, never today's record of the story
    for key in PROOF_STAMP_KEYS:
        if key in old:
            block[key] = old[key]
    block["reparse_of"] = block_path.relative_to(task_root).as_posix()
    # t-2277 W1: a reparse of a sample is a sample, and a reparse of a plain block stays plain - the mark and the folder are the superseded
    # block's, never today's record of the story (build_run_block above read today's record, so its answer is dropped when the old block had none)
    if old.get("reference_run"):
        block["reference_run"] = old["reference_run"]
    else:
        block.pop("reference_run", None)
    directory = task_root / "work" / block_folder(block)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (block["block_id"] + ".json")
    payload = json.dumps(block, ensure_ascii=False, indent=2) + "\n"
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except FileExistsError:
        if target.read_text(encoding="utf-8") != payload:
            raise RequestError("reparse projection collision")
    return target


SCHEDULE_MERGE_KEYS = ("profile_id", "purpose", "dispatch_id", "task", "revision",
                       "input_fingerprint", "freshness")


def _batch_identity(request: dict) -> str:
    """Two scheduled requests are the SAME launch when everything but their instance
    selection agrees: same profile, purpose, dispatch, revision and resolved command."""
    command = request.get("command") or {}
    identity = {key: request.get(key) for key in SCHEDULE_MERGE_KEYS}
    identity["command"] = {k: v for k, v in command.items() if k != "selector_args"}
    identity["execution"] = request.get("execution")
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str)


def merge_schedule(document: dict) -> tuple[dict, list]:
    """One batch naming an instance twice is MERGED, not refused. Returns (document, notes).

    This is also what makes "one request per GROUP of instances" cheap to write: a
    role may emit a request per case and get one launch, because the cases an instance
    covers are the manifest's business and the launch's identity is the command.

    the scheduler refused "the same instance cannot appear in multiple scheduled
    requests", which killed the only batched `--schedule` of TP1-15045 and pushed the
    automator back to eleven single-instance runs. Naming the same test twice in one batch is
    not a contradiction — it is a person writing a list. Requests that differ in anything but
    their selection stay separate, and the refusal still stands for those: running one test
    twice under two different commands IS a contradiction.
    """
    requests = document.get("requests")
    if not isinstance(requests, list) or len(requests) < 2:
        return document, []
    merged: dict = {}
    order: list = []
    notes: list = []
    for request in requests:
        if not isinstance(request, dict):
            return document, []  # not ours to repair; the scheduler names the real problem
        key = _batch_identity(request)
        if key not in merged:
            merged[key] = dict(request)
            order.append(key)
            continue
        target = merged[key]
        selected = list(target.get("selected_instance_ids") or [])
        added = [i for i in (request.get("selected_instance_ids") or []) if i not in selected]
        repeated = [i for i in (request.get("selected_instance_ids") or []) if i in selected]
        target["selected_instance_ids"] = selected + added
        for field in ("current_scope_instance_ids", "report_test_ids"):
            values = list(target.get(field) or [])
            values += [v for v in (request.get(field) or []) if v not in values]
            if values:
                target[field] = values
        contracts = dict(target.get("instance_contracts") or {})
        contracts.update(request.get("instance_contracts") or {})
        if contracts:
            target["instance_contracts"] = contracts
        selectors = dict((target.get("command") or {}).get("selector_args") or {})
        selectors.update(((request.get("command") or {}).get("selector_args") or {}))
        if selectors:
            target["command"] = dict(target.get("command") or {}, selector_args=selectors)
        if repeated:
            notes.append("merged repeated instances into one request: " + ", ".join(sorted(set(repeated))))
    if len(order) == len(requests):
        return document, []
    notes.insert(0, f"merged {len(requests)} scheduled requests into {len(order)}")
    return dict(document, requests=[merged[key] for key in order]), notes


def hold_dashboard(reason: str) -> None:
    """Freeze every dashboard refresh for the rest of this process AND its children.

    the red probe hashes the author's tree and re-checks it afterwards, while
    `refresh_dashboard()` rewrites the git-tracked `qa-factory/state/factory-dashboard.html`,
    whose `Generated <time>` stamp changes every minute — so the probe failed with
    "main-tree bytes changed during probe" and blamed the author. The flag lives in the
    environment, not in a parameter, because the processes that redraw it are children.
    """
    os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
    os.environ.setdefault("QA_FACTORY_SKIP_DASHBOARD_REASON", reason)


def refresh_dashboard() -> None:
    if os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH") == "1":
        return
    try:
        from factory_dashboard import main as dashboard_main
        dashboard_main([])
    except Exception:
        pass


def probe_runtime(spec: dict) -> dict:
    """Run the profile's probe and return its provenance record - the ONE strict reader of the run path, the
    post-run probe, `--mine`, the red probe (`probe_by_code`) and the manual capture (t-300 N2, FR-17). It takes what
    `profile_contract.acceptable_provenance(record, ACCEPTS)` takes: `matched`; a build the PERSON confirmed
    (`person_confirmed`, bound to what it was given for - never read as `matched`, so equivalence stays unverified and
    the fingerprint differs); and `not_applicable` with `reason_code: no_changed_file` (the story changes no file of
    this profile's checkout, so there is no stand to identify - on ANY stand kind, t-279 K-NA). Anything else raises a
    `ProvenanceRefused` that carries the record and says what the probe said, what was expected and the door; an
    `unknown` is refused even when it names an image (a digest says which image runs, not that it holds this story's
    code: the person's word at the build question is what lets such a stand through)."""
    result = _node_ids.run_captured(spec["argv"], spec["cwd"], None, spec["timeout_s"])
    value = probe_record(result)
    if acceptable_provenance(value, ACCEPTS):
        return value
    raise ProvenanceRefused(value)


def _identity_unread(record) -> bool:
    """A probe record whose identity is the person's word and nothing read (`person-confirmed:<at>`: docker gave no
    digest, runtime_probe.confirm_record)."""
    return isinstance(record, dict) and str(record.get("observed_runtime_identity") or "").startswith("person-confirmed:")


def kill_tree(proc) -> None:
    """Kill the process TOGETHER with its descendants. On Windows proc.kill() takes only the direct
    child (poetry) while pytest underneath keeps running and holds the stand - the FB-7 field
    lesson (09.09: the timeout fired, the run had to be finished off by hand). POSIX: the process
    group, Windows: taskkill /T."""
    try:
        if os.name == 'nt':
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=30)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()  # finish off the direct child in case taskkill/killpg did not
    except Exception:
        pass


def evidence_dir(task: str) -> Path:
    ev = story_root(task, "run_suite") / "evidence"      # a project never onboarded exits 3; a story not there is a refusal
    ev.mkdir(exist_ok=True)
    return ev


def _refuse_phantom_story(task: str) -> None:
    """The `--task` flows that read or write a story's evidence (`--detail`, `--wait`, the untyped run) end a story that
    is not there as ONE refusal on the command's channel, exit 2, before `evidence_dir` raises (CX1-18)."""
    try:
        story_root(task, "run_suite --task")
    except StoryRootError as exc:
        print(json.dumps({"status": "invalid_request", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


def log_tail(path: Path, n: int = 8) -> list:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-n:]
    except Exception:
        return []


QUIET_FLAGS = {"-q", "-qq", "--quiet", "-v", "-vv", "-vvv", "--verbose"}


def _clip(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    half = max(200, max_chars // 2)
    return text[:half] + f"\n... [{len(text) - 2 * half} chars cut — the full text is in the junitxml] ...\n" + text[-half:]


ERROR_HEAD_PREFIXES = ("ERROR", "E   ", "usage:", "ImportError", "ModuleNotFoundError")
ERROR_HEAD_MAX_LINES = 25
ERROR_HEAD_MAX_BYTES = 2500


def exit_reading(argv, exit_code) -> dict:
    """What this run's exit code means, as the summary fields `exit_means_not_executed` and
    `exit_note`. The runner's row in `references/launch-causes.json` (`launch_check.runner_row`)
    says which exit codes of that runner mean "no test was executed": True when the row lists
    the code, False when the row states its codes and does not list it. None when there is no
    fact (no row, a row without `not_executed_exits`, or data that could not be read): the
    reader then applies the legacy rule, and `exit_note` says which of those it was. The runner
    never owns 124 (timeout) or 127 (launch failure): those are None with a note. A broken
    table changes no verdict silently."""
    if exit_code in launch_check.RUNNER_OWN_EXITS:  # run_suite's own codes: never a runner's fact
        return {"exit_means_not_executed": None,
                "exit_note": f"run_suite's own code {exit_code} (timeout / launch failure), not a runner fact"}
    row, problem = launch_check.runner_row(argv)
    if row is not None and "not_executed_exits" in row:
        return {"exit_means_not_executed": exit_code in row["not_executed_exits"]}
    if problem:
        why = problem
    elif row is not None:
        why = f"the runner row `{row['tool']}` states no `not_executed_exits`"
    else:
        why = f"no runner row recognises `{_program_of(argv)}`"
    return {"exit_means_not_executed": None,
            "exit_note": f"{why}; exit codes "
                         f"{', '.join(str(c) for c in launch_check._LEGACY_NOT_EXECUTED)} are read as "
                         "\"nothing ran\" by the legacy rule"}


def nothing_ran(summary: dict) -> bool:
    """True when the command ended without executing a test: an exit the runner's row says means
    "not executed" (`exit_means_not_executed`; with no such fact, the legacy exits 2-5), a report
    with zero tests, or no report at all behind a failed (not timed out) command."""
    code = summary.get("exit_code")
    stated = summary.get("exit_means_not_executed")
    if stated is True or (not isinstance(stated, bool) and code in launch_check._LEGACY_NOT_EXECUTED):
        return True
    totals = summary.get("totals")
    if isinstance(totals, dict):
        return not totals.get("tests")
    return code not in (0, 124, None)


def error_head(log_text: str) -> list:
    """The lines of a log that say why nothing ran, capped at 25 lines / 2500 bytes.

    TP1-15045, exit 4: `ERROR: not found: ...::test_x[buffer-R3-vs-selected-R1]` sat in a
    1.2 KB log that the raw-log guard kept every role from reading, while the summary said
    only `broken_run`. Two critic dispatches were spent on "a tooling blocker" whose whole
    explanation was one line the runner had already captured."""
    head, size = [], 0
    for line in (log_text or "").splitlines():
        if not line.startswith(ERROR_HEAD_PREFIXES):
            continue
        line = line.rstrip()
        cost = len(line.encode("utf-8", errors="replace")) + 1
        if size + cost > ERROR_HEAD_MAX_BYTES:
            room = ERROR_HEAD_MAX_BYTES - size - 1
            if room > 40:
                head.append(line.encode("utf-8", errors="replace")[:room].decode("utf-8", errors="ignore"))
            break
        head.append(line)
        size += cost
        if len(head) >= ERROR_HEAD_MAX_LINES:
            break
    return head


NOT_FOUND_LINE = "ERROR: not found: "


def ids_pytest_did_not_find(argv, exit_code, log_text: str, request: dict) -> list:
    """The node ids of a TYPED pytest run that pytest itself reports as `ERROR: not found: <id>` (exit 4), spelled
    as the request spelled them. [] for every other run: not typed, not pytest, any other exit, a file that is not
    there (a different line, a build refusal), or the person's switch `execution.verify_node_ids: false`, which
    keeps switching every `node_id_mismatch` off, the run's included (P13). pytest stops at the first id it does
    not find, so the list is what the log shows, not every missing id."""
    if not request or exit_code != 4 or not is_pytest_command(argv):
        return []
    if _setting(load_config(), "execution", "verify_node_ids", True) is False:
        return []
    shown = [line[len(NOT_FOUND_LINE):].strip().replace("\\", "/") for line in (log_text or "").splitlines()
             if line.startswith(NOT_FOUND_LINE)]
    selectors = (request.get("command") or {}).get("selector_args") or {}
    tokens = [token for instance in request.get("selected_instance_ids") or [] for token in selectors.get(instance) or []
              if "::" in token]
    found = []
    for text in shown:
        # pytest prints the id as it resolved it (often absolute); the request's spelling is what the role can fix
        asked = next((token for token in tokens
                      if text == token.replace("\\", "/") or text.endswith("/" + token.replace("\\", "/"))
                      or token.replace("\\", "/").endswith("/" + text)), text)
        if asked not in found:
            found.append(asked)
    return found


def _recorded(ev: Path, label: str, suffix: str) -> list:
    """Files of one label, oldest first, in both layouts: `evidence/<label>-<ts><suffix>` of a
    standalone run and `evidence/runs/<job>/<label>-<ts><suffix>` of a typed one. The label a
    summary prints for a typed run lives only under `runs/`, which is why `--detail` with it
    answered `no_junitxml` for a report that was on disk."""
    pattern = globlib.escape(label) + "-*" + suffix
    found = list(ev.glob(pattern)) + list(ev.glob("runs/*/" + pattern))
    return sorted(found, key=lambda p: p.stat().st_mtime)


def resolve_detail_target(args) -> None:
    """`--request FILE --detail TEST`: task and label of that request's last recorded run.

    Reads the file as it is — no validation, no runtime probe, no job is begun: a question
    about a finished run must not be answered with "your request is invalid", and must never
    become a launch because its idempotency key happened to be new."""
    try:
        raw = json.loads(args.request.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("the request is not a JSON object")
        task = str(args.task or raw.get("task") or "")
        store = JobStore(artifacts_dir(task) / "state" / "execution-jobs")
        job = store.last_run_of(raw)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid_request", "error": f"{type(exc).__name__}: {exc}",
                          "hint": "--detail needs a readable request, or --task and --label"},
                         ensure_ascii=False))
        sys.exit(2)
    if args.label:
        args.task = task
        return
    if not job:
        print(json.dumps({"status": "no_recorded_run", "task": task,
                          "hint": "no finished run of this request, or of any of its instances, "
                                  "is recorded — run it first (without --detail)"}, ensure_ascii=False))
        sys.exit(2)
    args.task = task
    args.label = f"{job['request'].get('purpose')}-{job['job_id']}"


def _stored_report(ev: Path, label: str) -> tuple:
    """(report path, reporter, note) of the latest run of `label`, whatever wrote it; the path is
    None when no report copy is stored.

    A run keeps its report beside its log as `<label>-<ts>.junit.xml` (pytest, junit-xml) or
    `<label>-<ts>.trx`, and its summary names the reporter. The summary decides which copy is
    read when a label has both; a summary with no reporter field (one written before the field
    existed) or one whose reporter has no stored copy falls back to the newest copy and its
    extension, and says so in `note` — an inferred reporter is not reported as a recorded one."""
    junit, trx = _recorded(ev, label, ".junit.xml"), _recorded(ev, label, ".trx")
    if not junit and not trx:
        return None, "", ""
    declared, why = "", "no summary of this label is recorded"
    summaries = _recorded(ev, label, ".json")
    if summaries:
        try:
            declared = str(json.loads(summaries[-1].read_text(encoding="utf-8")).get("reporter") or "")
        except (OSError, ValueError, AttributeError):
            declared = ""
        why = "the summary carries no reporter field"
    stored = {"pytest": junit, "junit-xml": junit, "trx": trx}.get(declared)
    if stored:
        return stored[-1], declared, ""
    newest = max(junit + trx, key=lambda p: p.stat().st_mtime)
    reporter = "trx" if newest.name.endswith(".trx") else "junit-xml"
    if declared:
        why = f"the summary names reporter `{declared}`, which has no stored report here"
    return newest, reporter, f"reporter inferred from the stored file ({reporter}): {why}"


def _junit_system_out(path: Path) -> list:
    """The <system-out> text of every testcase, in document order — the one thing of a JUnit
    testcase that a row does not carry, kept for `--detail`'s `system_out_tail`. Aligned with
    `reporters.read_rows`, which gives one row per testcase in the same order."""
    return [((tc.find("system-out").text if tc.find("system-out") is not None else "") or "").strip()
            for tc in ET.parse(path).getroot().iter("testcase")]


def detail(args) -> None:
    """--detail <test>: the failure text of ONE test from the recorded report (JUnit or TRX) —
    no re-run. The rows come from `reporters.read_rows` with the reporter the run's summary
    records, so a .NET run's failure is as reachable as a pytest one."""
    ev = evidence_dir(args.task)
    report, reporter, note = _stored_report(ev, args.label)
    if report is None:
        hint = ("no recorded report (junit-xml or trx) with this label — the run did not happen, "
                "wrote no report the factory reads, or ended before any test ran")
        # `status` and the `no_junitxml` key keep their old spelling: consumers and stories in
        # flight read them; `no_report` is the same fact under its own name.
        answer = {"status": "no_junitxml", "label": args.label, "hint": hint,
                  "no_report": hint, "no_junitxml": hint}
        summaries = _recorded(ev, args.label, ".json")
        if summaries:
            # Nothing ran, so there is no test to show — the cause is what was asked for.
            try:
                last = json.loads(summaries[-1].read_text(encoding="utf-8"))
                answer.update({k: last[k] for k in ("exit_code", "execution_status", "error_head",
                                                    "launch_error", "log_tail", "log") if k in last})
            except (OSError, ValueError):
                pass
        print(json.dumps(answer, ensure_ascii=False))
        sys.exit(2)
    is_trx = reporter == "trx"
    suffix = ".trx" if is_trx else ".junit.xml"
    key = "trx" if is_trx else "junitxml"
    shown = str(report.relative_to(project_root()))
    log = report.with_name(report.name[:-len(suffix)] + ".log")
    try:
        rows = reporters.read_rows(report, reporter)
        tails = [] if is_trx else _junit_system_out(report)
    except (OSError, ET.ParseError) as exc:
        print(json.dumps({"status": "report_unreadable", key: shown, "error": f"{type(exc).__name__}: {exc}",
                          "hint": "the stored report could not be read as XML (see `error`): run "
                                  "the test again through run_suite.py to write a fresh report; if "
                                  "it happens again, file a finding with this answer"}, ensure_ascii=False))
        sys.exit(2)
    if len(tails) != len(rows):
        tails = [""] * len(rows)
    needle = args.detail.lower()
    hits, failed_names = [], []
    for row, tail in zip(rows, tails):
        name = row["test_id"]
        # The first failure and the first error of a testcase, failure first: JUnit's two nodes.
        found = [next((p for p in row["problems"] if p["kind"] == kind), None) for kind in ("failure", "error")]
        found = [p for p in found if p is not None]
        failed_row = bool(found) or row["status"] in ("failed", "error")
        if failed_row:
            failed_names.append(name)
        if needle not in name.lower():
            continue
        for problem in found:
            hits.append({"test": name, "kind": problem["kind"], "message": problem["message"][:400],
                         "text": _clip(problem["text"], args.max_chars)})
        if failed_row and not found:
            # A TRX result can fail with no ErrorInfo at all: the row is still the answer, with
            # nothing to quote — not "no failure recorded".
            hits.append({"test": name, "kind": "failure" if row["status"] == "failed" else "error",
                         "message": "", "text": ""})
        if hits and tail and hits[-1]["test"] == name and "system_out_tail" not in hits[-1]:
            hits[-1]["system_out_tail"] = tail[-1500:]
    extra = {"reporter": reporter} if is_trx else {}
    if note:
        extra["reporter_note"] = note
    if not hits:
        print(json.dumps({"status": "not_found", "test": args.detail, key: shown, **extra,
                          "failed": failed_names[:40],
                          "hint": "no failure/error recorded for a test matching this substring — pick a name from `failed`"},
                         ensure_ascii=False))
        sys.exit(2)
    print(json.dumps({"status": "ok", key: shown, **extra,
                      "log": str(log.relative_to(project_root())) if log.exists() else None,
                      "matches": hits[:3], "more_matches": max(0, len(hits) - 3)}, ensure_ascii=False))
    sys.exit(0)


# --- the project's own per-test timeout (RH2-9) ------------------------------------------------------------------
# A test the PROJECT's timeout plugin kills is the test's red, never a verdict on the stand (run 14857: a kill read as
# "the stand never indexed", 28 minutes of a person's time). The runner's own lines live in the `collect_forms` row of
# `launch-causes.json` (AR-1, `launch_check.runner_row`); this code names no runner text.
PROJECT_TIMEOUT_CODE = launch_check.PROJECT_TIMEOUT_CODE    # the `reason_code` of an instance a project timeout killed
PROJECT_TIMEOUT_HOWS = launch_check.PROJECT_TIMEOUT_HOWS    # blocks that are the project's limit (`run_killed` is ours)
_TRACEBACK_FRAME = re.compile(r'File "(?P<path>[^"]+)", line \d+, in (?P<name>\S+)')   # Python's own traceback form


def _frame_names(test_id: str, frames: list) -> bool:
    """Does a traceback frame (`(file path, function)` pairs) name the test `test_id` (`<module>[.<Class>]::<function>[<param>]`)?
    The function name must be equal and the frame's file stem one of the dotted parts of the module path."""
    classname, _, title = str(test_id).rpartition("::")
    function = title.partition("[")[0]
    parts = classname.split(".")
    return any(name == function and Path(path.replace("\\", "/")).stem in parts for path, name in frames)


def _hard_kill_tests(request: dict, log_text: str, kill_end: int) -> tuple:
    """`(tests, test_basis)` of a hard kill: the ONE selected instance (`only_selected`); among several, the one whose
    function and file a traceback frame after the kill banner names, when exactly one does (`stack_frame`); else none
    (`not_established`). The killed test is named only when proven (FR-41)."""
    selected = request.get("selected_instance_ids") or []
    contracts = request.get("instance_contracts") or {}
    ids = {i: str((contracts.get(i) or {}).get("report_test_id") or "") for i in selected}
    if len(selected) == 1:
        only = ids[selected[0]]
        return ([only], "only_selected") if only else ([], "not_established")
    frames = [(m.group("path"), m.group("name")) for m in _TRACEBACK_FRAME.finditer(log_text[kill_end:])]
    hits = [t for t in dict.fromkeys(i for i in ids.values() if i) if _frame_names(t, frames)]
    return (hits, "stack_frame") if len(hits) == 1 else ([], "not_established")


def _hard_kill_limit(row: dict, log_text: str, argv, cwd) -> tuple:
    """`(limit_s, limit_from)` of a hard kill: the run's own header line, else the project's setting
    (`execution_request.pytest_timeout_setting`, the one reader), else `(None, "not established: <why>")`."""
    header = row.get("timeout_header_line")
    hit = re.search(header, log_text, re.M) if header else None
    if hit:
        return float(hit.group("limit")), "the run's header"
    setting = pytest_timeout_setting(cwd, argv, project_root()) if row.get("tool") == "pytest" else None
    if setting and setting["state"] == "configured":
        return setting["limit_s"], setting["source"]
    return None, "not established: " + ((setting or {}).get("why") or "no reader for this runner")


def _timeout_sentence(block: dict) -> str:
    """The sentence a role reads for a timeout block."""
    if block["how"] == "run_killed":
        return (f"run_suite's own --timeout ({block['limit_s']:g} s) killed this run: the factory's run limit, not the project's "
                "per-test timeout and not a verdict on the stand.")
    tests = block["tests"]
    who = "a test of this run" if not tests else tests[0] + (f" (+{len(tests) - 1} more)" if len(tests) > 1 else "")
    limit = (f"{block['limit_s']:g} s, {block['limit_from']}" if block["limit_s"] is not None
             else f"limit {block['limit_from']}")
    return (f"{who} was killed by the project's per-test timeout ({limit}): it ran longer than the project allows. "
            "This is the test's limit, not a verdict on the stand.")


def _timeout_block(how: str, tests: list, basis: str, limit_s, limit_from: str, source: str = "project") -> dict:
    block = {"source": source, "how": how, "limit_s": limit_s, "limit_from": limit_from,
             "tests": tests, "test_basis": basis}
    block["sentence"] = _timeout_sentence(block)
    return block


def _timeout_outcome(argv, log_text, summary, request, cwd, killed_by_run_suite, run_timeout_s) -> tuple:
    if killed_by_run_suite:
        return _timeout_block("run_killed", [], "not_established", run_timeout_s, "run_suite --timeout", "run_suite"), ""
    row, problem = launch_check.runner_row(argv)
    if row is None:
        return None, (f"the runner's timeout lines could not be read ({problem}): no timeout fact was drawn" if problem else "")
    kill, message = row.get("timeout_kill_line"), row.get("timeout_failure_message")
    if not isinstance(summary.get("totals"), dict):
        hit = re.search(kill, log_text, re.M) if kill else None
        if hit is None:
            return None, ""
        tests, basis = _hard_kill_tests(request, log_text, hit.end())
        limit_s, limit_from = _hard_kill_limit(row, log_text, argv, cwd)
        return _timeout_block("hard_kill", tests, basis, limit_s, limit_from), ""
    rows = [f for f in summary.get("failed") or []
            if message and isinstance(f, dict) and re.match(message, str(f.get("why") or ""), re.M)]
    if not rows:
        return None, ""
    limit = float(re.match(message, str(rows[0]["why"]), re.M).group("limit"))
    return _timeout_block("failed_in_report", list(dict.fromkeys(str(f["test"]) for f in rows)),
                          "report_message", limit, "the report's message"), ""


def timeout_outcome(argv, log_text, summary, request, cwd, killed_by_run_suite=False, run_timeout_s=None) -> tuple:
    """`(block, note)`: the project's per-test timeout fact of ONE run, or `(None, note)`. Pure; never raises.
    `block` = `{source, how, limit_s, limit_from, tests, test_basis, sentence}`, `how` one of `hard_kill` (the runner's
    timeout plugin killed the process: its banner is in the log and NO report was parsed), `failed_in_report` (the plugin
    failed a test and the run went on: the report row's message), `run_killed` (run_suite's OWN --timeout killed it:
    `killed_by_run_suite` is passed by `run`, an exit code 124 alone is not proof - the project's command may exit 124).
    No block and an empty note is an answer (no timeout, or a runner with no timeout lines in its row); a note says
    the runner table or the reading failed, and no fact was drawn."""
    try:
        return _timeout_outcome(argv, log_text, summary, request, cwd, killed_by_run_suite, run_timeout_s)
    except Exception as exc:  # a reader's defect never changes a verdict and never fails a run
        return None, f"the timeout reading failed ({type(exc).__name__}): no timeout fact was drawn"


def execution_status(summary: dict) -> str:
    """The run's own status, from its own evidence — never typed by a role (design section 4).
    Closed vocabulary: passed · failed · env_blocked · not_executed · broken_run · timeout.
    `env_blocked` is not decidable here: only the runner knows the preflight verdict, and it
    sets that field in run-report.json. What run_suite can prove, it proves. A `hard_kill` timeout block (the
    project's timeout plugin killed the process, no report written) is `timeout`, never `broken_run`; a
    `failed_in_report` block leaves the status as computed (one timed-out test among results is a triaged red)."""
    if summary.get("exit_code") == 124 or (summary.get("timeout") or {}).get("how") == "hard_kill":
        return "timeout"
    totals = summary.get("totals")
    if not isinstance(totals, dict):
        # No junit to parse: a non-zero exit means the command itself broke (collection error,
        # missing interpreter), a zero exit means it ran and produced nothing to report.
        return "broken_run" if summary.get("exit_code") else "not_executed"
    def _n(key: str) -> int:
        v = totals.get(key, 0)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    if _n("errors"):
        return "broken_run"
    if _n("failures"):
        return "failed"
    if _n("tests") == 0:
        return "not_executed"
    return "passed"


UNTYPED_STORY_RUN = """run_suite: this story is inside stage {stage}, so a `--label` run is refused.
  Why: only a typed run (--request, or --schedule above the batch threshold) writes an
  immutable block to work/run-blocks/. Without that block the run leaves no durable evidence,
  and S6 cannot report tests that really did execute.
  What happened once already (TP2-2520): 19 automated cases ran green with critic
  approval and matching hashes, every block was missing, and the run report could not show any
  of it. The tests were fine; the evidence was gone.
  Do this instead: `run_suite.py --mine <CASE>` — it builds the typed request of your open
  dispatch and runs it; `--request <file>` is for a run that is not the ordinary one.
  Reading a finished run is never refused: `--detail <test>` and `--wait` pass as they are.
  Outside a story dispatch --label is still the right call and nothing changes."""


def active_story_stage(task: str) -> str:
    """The stage a story is currently working in, or "" when this is not a story run at all.

    Kept deliberately narrow: only a stage that is actually running counts. An ad-hoc run in a
    repository that happens to contain a finished story is not a story run."""
    try:
        from hooklib import artifacts_dir
        data = json.loads((artifacts_dir(task) / "pipeline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return ""
    if not isinstance(data, dict):
        return ""
    for name, entry in (data.get("stages") or {}).items():
        if isinstance(entry, dict) and entry.get("status") == "running":
            return str(name)
    return ""


def refuse_untyped_story_run(task: str, ap) -> None:
    """Silent degradation is more expensive than a refusal.

    The instruction to use a typed request already existed; it was followed by a role that
    reached for the simpler flag, and nothing objected until the evidence was needed and gone.
    An instruction that can be quietly skipped is a suggestion — this is the same rule stated
    where it cannot be."""
    stage = active_story_stage(task)
    if stage:
        ap.error(UNTYPED_STORY_RUN.format(stage=stage))


def stamp_first_run(task: str) -> None:
    """The moment this story first executed a test, written once into pipeline.json.

    "A small task takes four hours" is a claim about the hour before the first test runs,
    and nothing measured it — the first real execution is the automator's witness run at S5,
    an hour of preparation in. A number nobody records is a number nobody argues about; the
    retro reads this one."""
    try:
        from hooklib import artifacts_dir
        path = artifacts_dir(task) / "pipeline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("first_test_run_at"):
            return
        data["first_test_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass  # a run is never blocked by its own bookkeeping


# --- The stand and the node ids (0.7.8). Each helper imports its module inside the call and
# treats ImportError as "this install does not have the feature": a half-updated plugin must
# run tests the way 0.7.7 did, never crash on the way to them.

def _setting(cfg: dict, section: str, key: str, default):
    """One key of the project's effective config, with the default the template documents."""
    try:
        from config_contract import effective_config
        cfg = effective_config(cfg or {})
    except Exception:
        cfg = cfg or {}
    value = (cfg.get(section) or {}).get(key) if isinstance(cfg.get(section), dict) else None
    return default if value is None else value


def stand_is_serial(cfg: dict) -> bool:
    """True when the project says its stand takes one run at a time: `run.parallel: false`
    (what onboarding writes — "localhost has one account"), or the scheduler's own
    `execution.parallel.mode: serial`. A project that says nothing is left alone."""
    if _setting(cfg, "run", "parallel", None) is False:
        return True
    parallel = _setting(cfg, "execution", "parallel", {})
    return isinstance(parallel, dict) and parallel.get("mode") == "serial"


@contextlib.contextmanager
def hold_stand(cfg: dict, job_id: str, environment: str, wait_s: int | None, mode: str = "exclusive", max_shared: int = 1):
    """The stand lease around one launch; yields the lease record, or None when not needed.

    TP1-15045: `run.parallel` was false "precisely because localhost has one account",
    and nothing enforced it — a critic's five-way batch and an automator's single run met
    on the stand, and the `Locator.fill` timeouts that followed were triaged as test
    defects. A stand that stays busy is said so in one JSON line and nothing is launched:
    exit 3, the same "not now, call again" a `--wait` that is still running answers with.

    `mode` is `exclusive` (the default: a suite, a capture) or `walk` (a manual walker, which shares the stand with up to
    `max_shared` other walkers and with no suite); the caller gives both, this function reads no project fact for them."""
    if not stand_is_serial(cfg):
        yield None
        return
    try:
        import stand_lease
    except ImportError:
        yield None
        return
    if wait_s is None:
        configured = _setting(cfg, "run", "stand_wait_s", 1800)
        wait_s = int(configured) if isinstance(configured, (int, float)) and not isinstance(configured, bool) else 1800
    try:
        if mode == "exclusive":     # the suites' call, unchanged
            manager = stand_lease.hold(project_root(), job_id, environment, max(0, int(wait_s)))
        else:
            manager = stand_lease.hold(project_root(), job_id, environment, max(0, int(wait_s)), mode=mode, max_shared=max_shared)
        lease = manager.__enter__()
    except stand_lease.StandBusy as busy:
        print(json.dumps({"status": "stand_busy", "holder": getattr(busy, "holder", {}) or {},
                          "waited_s": getattr(busy, "waited_s", None), "environment": environment,
                          "hint": str(busy)}, ensure_ascii=False, default=str))
        sys.exit(3)
    except Exception as exc:  # the lease is the factory's own bookkeeping: never the run's problem
        print(f"STAND LEASE (note, not a block): unavailable, the run goes on unprotected — "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        yield None
        return
    try:
        yield lease if isinstance(lease, dict) else {}
    finally:
        manager.__exit__(*sys.exc_info())


def observe_stand(task: str, summary: dict) -> dict | None:
    """What `stand_health` makes of this run together with the ones before it, or None."""
    try:
        import stand_health
        signal = stand_health.observe(project_root(), task, summary)
        return signal if isinstance(signal, dict) and signal else None
    except Exception:  # ImportError included: a missing or broken observer never fails a run
        return None


def attach_diagnosis(task: str, summary: dict) -> None:
    """What the judge makes of a run that did not simply pass: `summary["diagnosis"]`.

    `execution_status` can only prove what the exit code says, so `ModuleNotFoundError:
    pydantic`, a test id spelled by a plugin and an account that is not on the stand all
    reach the automator as `broken_run` (TP1-15045: repair rounds on tests that were
    never the problem). The judge reads the same error head and names the culprit; only in
    `judge.mode: on` may it turn a `broken_run`/`failed` into `env_blocked`, and the proven
    value is kept in `execution_status_raw`. With `judge.provider: none` - the default -
    nothing here is reached and the summary is byte for byte what it was."""
    try:
        import judge_run
        judge_run.attach(summary, project_root=project_root(), task=task)
    except Exception:  # ImportError included: a judge is never the reason a run fails
        return


NODE_ID_BLOCK = "node_id_mismatch"


def _collect_argv(argv: list) -> list:
    """The request's command without its report plumbing — what a collect may be run with."""
    out = []
    for token in argv:
        if token == "{report_path}":
            if out and out[-1].startswith("--junit"):
                out.pop()
            continue
        if "{report_path}" in token:
            continue
        out.append(token)
    return out


def refuse_missing_executor(profile_id: str, tool: str, cases: list, stage: str = "S5") -> None:
    """The launcher of this run does not exist in this session: print the same three-option
    question the gate rehearsal asks, and exit 3 without launching anything.

    The tool can disappear after gate A — a profile added at S5, a machine that changed, a
    wrapper that stopped resolving. A silent handover then would be the factory deciding for
    the person; a `broken_run` summary would be the factory calling its own missing binary a
    failed test (TP2-2536, decision of 22.09.2026)."""
    try:
        from gate_preflight import executor_options, executor_question
        statement, options = executor_question(tool, profile_id, list(cases), stage)
    except Exception:  # the rehearsal module is not installed in this build
        statement = (f"`{tool}` is not available to me in this session, and these tests run "
                     "through it")
        options, executor_options = "", lambda count: []
    print(json.dumps({"status": "executor_unavailable", "profile": profile_id, "tool": tool,
                      "cases": [str(c) for c in cases], "stage": stage,
                      "question": (statement + ". " + options).strip(),
                      "options": executor_options(len(cases)),
                      "launched": False}, ensure_ascii=False))
    sys.exit(3)


def executor_gap(request: dict, cfg: dict) -> dict | None:
    """`{"profile", "tool", "cases"}` when this request's launcher provably does not resolve
    here, else None. Degrades to None whenever it cannot tell — an unresolvable wrapper is
    not a missing tool, and a run refused on a guess costs more than the run."""
    try:
        from gate_preflight import executor_probe
    except Exception:
        return None
    command = request.get("command") or {}
    profile_id = str(request.get("profile_id") or "")
    profile = next((p for p in (cfg.get("profiles") or [])
                    if isinstance(p, dict) and str(p.get("profile_id")) == profile_id), {})
    try:
        probe = executor_probe(_collect_argv(list(command.get("argv") or [])),
                               Path(str(command.get("cwd") or ".")), profile)
    except Exception:
        return None
    if probe.get("status") != "missing":
        return None
    # The cases this run was about, the way the request itself records them; an instance id
    # is not a case id, so nothing is reverse-engineered out of one.
    cases = [str(c) for c in ((request.get("built_by") or {}).get("cases") or []) if c]
    return {"profile": profile_id or "the selected profile", "tool": probe.get("tool") or "",
            "cases": cases}


def _not_verified(reason: str) -> dict:
    return {"notes": [f"node ids were not verified: {reason}"], "resolved": {}}


def _program_of(argv) -> str:
    return Path(str(argv[0])).name if argv else ""


def _runner_without_node_ids(argv) -> str:
    """Why a launch that is not pytest had its ids run as written: its runner row (the table in
    `references/launch-causes.json`, through `launch_check.runner_row`) has no node-id checker
    this version can run, or there is no row, or the table could not be read."""
    row, problem = launch_check.runner_row(argv)
    tail = f"`{_program_of(argv)}` ran the ids as written"
    if problem:
        return f"the runner table could not be read ({problem}); {tail}"
    if row is not None and row.get("node_ids"):
        return (f"the runner row `{row['tool']}` names the node-id checker `{row['node_ids']}`, "
                f"which this version does not run for this command; {tail}")
    data, _note = launch_check.load_data()
    checkers = sorted({r["node_ids"] for r in (data or {}).get("collect_forms", []) if r.get("node_ids")})
    return ("the factory lists collected tests only for runners with a node-id checker "
            f"({', '.join(checkers) or 'none'}); {tail}")


def _asked_files(tokens) -> set:
    """The test files the node ids name, spelled with forward slashes (the key a collect is remembered under)."""
    return {str(token).partition("::")[0].replace("\\", "/") for token in tokens}


def _collect_that_covered(mined: dict, asked: list):
    """The newest collect `--mine` took while it built this request that listed every file `asked` names, or None.
    Not a loose match: a collect over other files says nothing about these ids (AR-28)."""
    files = _asked_files(asked)
    return next((got for got in reversed(mined.get("collects") or []) if files <= got["files"]), None)


BROKEN_SHOWN = 10  # broken files named in a note; the rest is counted ("+K more"), the record keeps them all


def collect_files(argv, cwd, files, cfg, notes=None):
    """The ONE collect over `files` of S5 (RH1-3, AR-15; was `mine.collect_once`, and the sandbox kept a copy of it):
    the ids of `node_ids.collect` with the runner's row of `references/launch-causes.json` (`launch_check.runner_row`)
    handed over, so one file that fails to import no longer hides the rest. A list when nothing broke; otherwise the
    `node_ids.CollectError` of the outcome (`partial` carries the healthy ids and the broken files). A table that cannot
    be read is `form=None` - the collect stays all-or-nothing, never gains a flag from the code - and `notes` (a list,
    when the caller keeps one) says so."""
    import node_ids  # ImportError is the builder's "collect unavailable"
    timeout = int(_setting(cfg, "execution", "node_id_collect_timeout_s", 180))
    argv = _collect_argv(argv)
    form, problem = launch_check.runner_row(argv)
    if problem:
        form = None
        said = launch_check.table_note(problem)
        if notes is not None and said not in notes:
            notes.append(said)
    return node_ids.collect(argv, cwd, timeout, files=list(files), form=form)


def _checked_by_the_first_collect(mined: dict, asked: list, node_ids) -> dict | None:
    """`check_request`'s answer, made WITHOUT a second collect (HF2-10): the ids are matched, by the one
    `node_ids.match`, against the list of the collect the build already took; a collect that raised is "not
    verified" with the same words `check_request` uses; no collect at all - an explicit `--node-id` is the run's
    to check - is "not verified" too, never "verified". Invariant: a missing answer is never read as "found".
    A PARTIAL collect (RH1-3: it went on past files that failed to import) is matched by `match_partial`: the ids of
    the healthy files are checked, an id of a file that did not collect is "not verified" - never `missing` - and its
    note names the broken files; only a `missing` id refuses."""
    got = _collect_that_covered(mined, asked)
    if got is None:
        return {"resolved": {}, "missing": [], "notes": [
            "node ids were not verified: " + str(mined.get("unasked") or "no collect answered for them")]}
    exc = got["error"]
    if getattr(exc, "kind", "") == "partial" and hasattr(node_ids, "match_partial"):
        checked = node_ids.match_partial(asked, exc.ids, exc.broken)
        checked["notes"] = [node_ids.broken_sentence(exc.broken, BROKEN_SHOWN)] + list(checked.get("notes") or [])
        checked["broken"] = list(exc.broken)
        return checked
    if got["error"] is not None:
        exc = got["error"]
        return {"resolved": {}, "missing": [],
                "notes": ["node ids were not verified: " + str(getattr(exc, "message", "") or f"{type(exc).__name__}: {exc}")],
                "collect_error": getattr(exc, "head", "") or ""}
    checked = node_ids.match(asked, got["ids"])
    if mined.get("notes") and isinstance(checked, dict):  # e.g. the runner table could not be read (E3-12)
        checked["notes"] = list(checked.get("notes") or []) + [n for n in mined["notes"] if n not in (checked.get("notes") or [])]
    return checked


def _record_collect_gaps(request: dict, mined, asked: list, checked) -> str:
    """Keep the broken files of the collect this check read in the story's history (`collect_gaps.record`, the one
    writer), so the report can name them. A collect that answered with nothing broken erases the earlier row of this
    profile; a collect that did not answer (a timeout, an unreadable output) leaves the record as it was: nothing was
    learned. Returns "" or the reason it was not kept (a note, never a refusal)."""
    broken = checked.get("broken") if isinstance(checked, dict) else None
    if broken is None and mined is not None:
        got = _collect_that_covered(mined, asked)
        if got is not None and got["error"] is None:
            broken = []
    if broken is None:
        return ""
    try:
        import collect_gaps
        import node_ids
        # The owner by what the request names (F4, AR-27): a broken path that IS one of the test files this S5 request asks
        # to run is the story's own test file; a folder (its conftest) or a file the request does not name is the project's.
        named = _asked_files(asked)
        broken = [dict(b, owner="story" if any(node_ids.same_file(f, b.get("path", "")) for f in named) else "project")
                  for b in broken]
        return collect_gaps.record(artifacts_dir(request["task"]), "s5_collect", str(request.get("profile_id") or ""),
                                   broken)
    except Exception as exc:  # the record is the factory's own; its defect must not stop a run
        return f"collect-gaps.json was not kept ({type(exc).__name__}: {exc})"[:300]


def verify_node_ids(request: dict, cfg: dict, *, mined: dict | None = None) -> dict | None:
    """Check the pytest node ids of a request against a real collect, BEFORE a job is begun.

    `mined` is what `--mine` kept of its own build in this process (`mine`): the collects it took. With it NO
    second collect runs - the ids are matched against the list of the first one, and an unreadable, timed-out
    or absent collect is "node ids were not verified" (the run then checks them: pytest's `not found`, exit 4,
    is answered by `run` as `node_id_mismatch`). Without it (a request file written by hand, B-E14) the check
    collects for itself, as it always did.

    Returns None when there is nothing to check, else `{"notes": [...], "resolved": {asked:
    real}}`; prints `node_id_mismatch` and exits 2 when an id does not exist. TP1-15045:
    `test_x[buffer-R3-vs-selected-R1]` is collected as `test_x[chromium-buffer-R3-vs-
    selected-R1]` under pytest-playwright; the run exited 4 in a second and cost two critic
    dispatches. The browser prefix is the framework's bookkeeping, so the factory fixes it
    and says so; a test that is not there at all is said before an idempotency key is spent.

    Where the check does not happen although the request asks for tests by selector (a runner with
    no node-id checker, the switch `execution.verify_node_ids: false`, no `node_ids` module), the
    notes say "node ids were not verified" and why; a whole-suite request asks for no id and
    gets none. `is_pytest_command` alone gates the pytest path: the runner table only words the
    note of a launch that is not pytest, so an unreadable table never switches the check off.
    No note stops a launch; only a pytest id that is not collected refuses (exit 2)."""
    from execution_request import is_pytest_command, person_passed
    command = request.get("command") or {}
    selectors = command.get("selector_args") or {}
    selected = [token for instance in request.get("selected_instance_ids") or []
                for token in selectors.get(instance) or []]
    pytest = is_pytest_command(command.get("argv"))
    asked = [token for token in selected if "::" in token]
    if not selected or (pytest and not asked):
        return None
    if _setting(cfg, "execution", "verify_node_ids", True) is False:
        return _not_verified("`execution.verify_node_ids` is false in qa-factory/config.json")
    if not pytest:
        return _not_verified(_runner_without_node_ids(command.get("argv")))
    try:
        import node_ids
    except ImportError as exc:
        return _not_verified(f"the node_ids module could not be imported ({exc})")
    timeout = _setting(cfg, "execution", "node_id_collect_timeout_s", 180)
    table_note = ""
    try:
        if mined is not None:
            checked = _checked_by_the_first_collect(mined, asked, node_ids)
        else:
            argv = _collect_argv(list(command["argv"]))
            limit = int(timeout) if isinstance(timeout, (int, float)) else 180
            form, problem = launch_check.runner_row(argv)
            if problem:   # a table that cannot be read: the check stays all-or-nothing, and says so (E3-12)
                table_note = launch_check.table_note(problem)
            # one collect: `node_ids` ships in this package, so there is no older interface to fall back to (I4)
            checked = node_ids.check_request(argv, command["cwd"], asked, limit, form=form)
    except Exception as exc:  # the check is the factory's own; its defect must not stop a run
        return {"notes": [f"node ids were not verified: {type(exc).__name__}: {exc}"], "resolved": {}}
    if not isinstance(checked, dict):
        return None
    notes = [str(n) for n in checked.get("notes") or []]
    if table_note and table_note not in notes:
        notes.append(table_note)
    kept = _record_collect_gaps(request, mined, asked, checked)
    if kept:
        notes.append(kept)
    if checked.get("collect_error"):
        notes.append("collect failed: " + str(checked["collect_error"])[:400])
    missing = checked.get("missing") or []
    if missing:
        task_root = artifacts_dir(request["task"])
        word = person_passed(task_root, active_story_stage(request["task"]), NODE_ID_BLOCK)
        if not word:
            sentence = ""
            try:
                sentence = node_ids.missing_sentence(missing)
            except Exception:
                pass
            print(json.dumps({
                "status": NODE_ID_BLOCK, "missing": missing, "notes": notes,
                "hint": (sentence + ". " if sentence else "") +
                        "Nothing was launched and no idempotency key was spent. Take the spelling "
                        "from `nearest`, correct it where it is recorded (the manifest entry, or "
                        "your request), and run again. A person's word launches it as asked: "
                        f"the orchestrator records it for block \"{NODE_ID_BLOCK}\". "
                        # How a project's plugins spell a parameter id is our bookkeeping, and
                        # the real spelling is in `nearest` — so this is a repair, and the
                        # marker is what a driver routes on (P4b).
                        f"{REPAIR_MARKER}."},
                ensure_ascii=False))
            sys.exit(2)
        notes.append(f"{len(missing)} node id(s) were not collected; launched as asked on a "
                     f"person's word: {word}")
    resolved = {str(a): str(r) for a, r in (checked.get("resolved") or {}).items() if str(a) != str(r)}
    return {"notes": notes, "resolved": resolved}


def _same_probe_spec(built: dict, wanted: dict) -> bool:
    """Whether two runtime-probe specs run the same command in the same directory (a relative `cwd` is the
    project root's, as the builder spells it)."""
    def where(spec: dict) -> str:
        cwd = Path(str(spec.get("cwd") or "."))
        return os.path.normcase(os.path.normpath(str(cwd if cwd.is_absolute() else project_root() / cwd)))
    return ([str(a) for a in built.get("argv") or []] == [str(a) for a in wanted.get("argv") or []]
            and where(built) == where(wanted))


def _observed_while_building(args, request: dict) -> dict | None:
    """The stand reading `--mine` took while it built THIS request, or None. None when the request was not built
    here (a file), when the build did not observe the stand (`runtime_observed: false`; a red probe copies without
    looking), or when what it read was another probe than the request's: the caller then reads the stand itself.
    Invariant: a stand nobody looked at is never reported as the same stand (FR-41, B-150, B-E11)."""
    mined = getattr(args, "mine_memo", None)
    spec = request.get("runtime_probe")
    if not mined or request.get("runtime_observed") is False or not isinstance(spec, dict):
        return None
    return next((record for built, record in reversed(mined["probes"]) if _same_probe_spec(built, spec)), None)


def apply_resolved_ids(request: dict, resolved: dict) -> dict:
    """The request as it is actually launched: real node ids in the argv, and the reporter
    row of every instance whose test was respelled following it. A copy — the job's digest
    is taken over what the role asked for, so a repeat of the same request stays a repeat."""
    if not resolved:
        return request
    from execution_request import node_report_id
    patched = copy.deepcopy(request)
    patched["resolved_argv"] = [resolved.get(token, token) for token in request["resolved_argv"]]
    selectors = (patched.get("command") or {}).get("selector_args") or {}
    for instance, tokens in selectors.items():
        selectors[instance] = [resolved.get(token, token) for token in tokens]
    contracts = patched.get("instance_contracts") or {}
    run_cwd = str((request.get("command") or {}).get("cwd") or "")
    if run_cwd and not Path(run_cwd).is_absolute():
        run_cwd = str(project_root() / run_cwd)
    for asked, real in resolved.items():
        old_name, new_name = asked.split("::")[-1], real.split("::")[-1]
        for instance, tokens in ((request.get("command") or {}).get("selector_args") or {}).items():
            contract = contracts.get(instance)
            if asked not in tokens or not isinstance(contract, dict):
                continue
            report_id = str(contract.get("report_test_id") or "")
            # `asked` and `real` are both spelled from the cwd (the caller's path); the old
            # cwd-relative spelling of `asked` is still recognised as one this run wrote.
            if report_id in (node_report_id(asked, run_cwd), node_report_id(asked)):
                contract["report_test_id"] = node_report_id(real, run_cwd)
            elif old_name != new_name and report_id.endswith(old_name):
                contract["report_test_id"] = report_id[:-len(old_name)] + new_name
    patched["node_id_resolution"] = resolved
    return patched


# Where the time of one call goes (EP1-23, B1; the find "a --mine call costs two minutes for 5-13 s of tests" could only
# be an estimate, FR-28). A phase that did not happen is `None` (JSON null), never 0: "did not happen" must not read as
# "instant" (FR-41). Zero is a measured phase that was fast. The anchor of a call that built no request (`--request`) is
# the import of this module, i.e. the start of the process.
_PROCESS_T0 = time.monotonic()
PHASE_KEYS = ("build_s", "stand_probe_s", "collect_s", "before_launch_s", "pytest_s", "after_s")


@contextlib.contextmanager
def _phase(clock: dict, name: str):
    """Add the time of this block to `clock[name]`. Measuring never stops the run (P1): a clock that cannot be written
    loses the number, not the call."""
    began = time.monotonic()
    try:
        yield
    finally:
        try:
            clock[name] = clock.get(name, 0.0) + (time.monotonic() - began)
        except Exception:
            pass


def _round_phase(value) -> float | None:
    return None if value is None else round(max(0.0, float(value)), 1)


def _build_phases(clock: dict | None, now: float) -> dict:
    """`build_s`, `stand_probe_s`, `collect_s` of a `--mine` build. `build_s` is the build WITHOUT its collects and
    stand probes, so the six phases partition the call and a reader can add them. `clock` is None for a call that built
    no request: all three are None."""
    if not clock or "t_zero" not in clock:
        return {"build_s": None, "stand_probe_s": None, "collect_s": None}
    ended = clock.get("build_end", now)
    spent = clock.get("collect_s"), clock.get("stand_probe_s")
    return {"build_s": _round_phase(ended - clock["t_zero"] - sum(s or 0.0 for s in spent)),
            "stand_probe_s": _round_phase(spent[1]), "collect_s": _round_phase(spent[0])}


def _phases_s(args, launched_at, exited_at, written_at) -> dict:
    """The `phases_s` field of a run summary. `launched_at` is when the command was started (or when it failed to
    start), `exited_at` when it ended - None when it never ran: then `pytest_s` and `after_s` are None. `after_s` ends
    where the summary is written: the dashboard refreshes and the run block written AFTER it are not in the field (they
    are in `total_s` of the PHASES line)."""
    clock = getattr(args, "phase_clock", None)
    phases = _build_phases(clock, launched_at)
    anchor = clock.get("build_end") if clock and "build_end" in clock else _PROCESS_T0
    phases["before_launch_s"] = _round_phase(launched_at - anchor)
    phases["pytest_s"] = None if exited_at is None else _round_phase(exited_at - launched_at)
    phases["after_s"] = None if exited_at is None else _round_phase(written_at - exited_at)
    return {key: phases[key] for key in PHASE_KEYS}


def _phases_line(phases: dict, total_s: float | None = None) -> str:
    """One stderr line (never stdout: that stays one JSON document, FR-14). A phase that did not happen is left out of
    the line - its absence is the word; the field in the summary says `null`."""
    parts = [f"{key}={phases[key]}" for key in PHASE_KEYS if phases.get(key) is not None]
    if total_s is not None:
        parts.append(f"total_s={round(max(0.0, total_s), 1)}")
    return "PHASES: " + " ".join(parts)


def _say_phases(phases_of, total_of=None) -> None:
    """Print the PHASES line; whatever goes wrong, the call goes on (measuring is not the run's business)."""
    try:
        print(_phases_line(phases_of(), total_of() if total_of else None), file=sys.stderr)
    except Exception as exc:
        print(f"PHASES (note): not measured: {type(exc).__name__}: {exc}", file=sys.stderr)


def _clock_zero(args) -> float:
    """Where `total_s` counts from: the start of the build of a `--mine` call, the start of the process otherwise."""
    clock = getattr(args, "phase_clock", None)
    return clock["t_zero"] if clock and "t_zero" in clock else _PROCESS_T0


def _say_mine_phases(clock: dict) -> None:
    """The PHASES line of a `--mine` call that launched nothing (answered `reused`/`already_run`, or refused)."""
    def total():
        return time.monotonic() - clock["t_zero"]
    _say_phases(lambda: {key: None for key in PHASE_KEYS} | _build_phases(clock, time.monotonic()), total)


def mine(args) -> Path:
    """`--mine CASE[,CASE…]`: build the typed request of the open dispatch, write it under
    work/requests/, and hand its path to the ordinary `--request` flow."""
    clock = {"t_zero": time.monotonic()}      # before the import: the module's load belongs to the build
    args.phase_clock = clock
    from execution_request import MineRefusal, WindowFirst, build_mine_request, write_mine_request

    # What this build learned is kept for the `--request` flow that follows in THIS process (HF2-10, F-B4): the
    # collects (answer or failure) and the stand readings. Scope: this one request - never carried to another
    # build, another window or another process, because a stand and a test list are only true for the moment they
    # were read (FR-41, B-150).
    mined = {"collects": [], "probes": [], "notes": [],
             "unasked": ("--node-id is checked by the run itself" if args.node_id
                         else "no collect answered while the request was built")}

    def collect(argv, cwd, files):
        """`collect_files`, remembered: the same question twice in one build gets the first answer back - a list, or
        the failure, raised again (a PARTIAL collect included: its ids and broken files stay on the error, for
        `_checked_by_the_first_collect`) - so a timed-out collect is never waited for a second time."""
        key = (tuple(str(a) for a in argv), str(cwd), tuple(sorted(str(f) for f in files)))
        known = next((got for got in mined["collects"] if got["key"] == key), None)
        if known is None:
            known = {"key": key, "files": _asked_files(files), "ids": None, "error": None}
            mined["collects"].append(known)
            try:
                with _phase(clock, "collect_s"):
                    known["ids"] = list(collect_files(argv, cwd, files, load_config(), mined["notes"]))
            except Exception as exc:
                known["error"] = exc
        if known["error"] is not None:
            raise known["error"]
        return list(known["ids"])

    def probe(spec):
        """`probe_runtime`, remembered: the reading the build takes of the stand is the one the run is launched on."""
        with _phase(clock, "stand_probe_s"):
            record = probe_runtime(spec)
        mined["probes"].append((dict(spec), record))
        return record

    cases = [c for chunk in args.mine for c in str(chunk).split(",")]
    try:
        request, notes, reusable, verified = build_mine_request(
            project_root(), cases, cfg=load_config(), task=args.task or "",
            dispatch_id=args.dispatch or "", purpose=args.purpose or "", profile_id=args.profile or "",
            cwd=args.cwd_override or "", sandbox_root=getattr(args, "sandbox_root", "") or "",
            node_ids=args.node_id or None, again=args.again,
            reason=args.reason or "", probe=probe, collect=collect)
        clock["build_end"] = time.monotonic()
        if reusable:
            # Answered, not launched: `reused` (every instance holds a green result over these
            # bytes) or `already_run` (one holds a red one), exit 0, and nothing is written -
            # no request file, no job, no key (D-0018).
            for note in notes:
                print(f"MINE (note): {note}", file=sys.stderr)
            print_not_launched(reusable["status"], reusable["jobs"][-1], brief=True, answer=reusable)
            _say_mine_phases(clock)
            sys.exit(0)
        # One collect per run: the builder has just spelled every id from a real collect (`verified`), or, when
        # it did not find them all, the check reads the list of that same collect (`mined`) - never a second one.
        args.node_ids_verified = bool(verified)
        args.mine_memo = mined
        path = write_mine_request(project_root(), request)
        clock["build_end"] = time.monotonic()
    except WindowFirst as exc:
        # Not a refusal of the test: a cheaper way to ask for the same evidence. Nothing was
        # launched, so no idempotency key is spent and the named command is free to run.
        print(json.dumps({**exc.payload, "error": str(exc)}, ensure_ascii=False))
        _say_mine_phases(clock)
        sys.exit(2)
    except MineRefusal as exc:
        print(json.dumps({"status": "mine_refused", "error": str(exc)}, ensure_ascii=False))
        _say_mine_phases(clock)
        sys.exit(2)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # Not the role's doing and not the person's: the builder could not read what the
        # factory itself wrote. Said as that, with the way around it.
        print(json.dumps({"status": "mine_unavailable", "error": f"{type(exc).__name__}: {exc}",
                          "hint": "the factory could not build this request from its own state; "
                                  "report it in your digest and run through --template request"},
                         ensure_ascii=False))
        _say_mine_phases(clock)
        sys.exit(2)
    try:
        shown = str(path.relative_to(project_root()))
    except ValueError:
        shown = str(path)
    print(f"MINE: {shown} — dispatch {request['dispatch_id']}, {request['purpose']}, "
          f"{len(request['selected_instance_ids'])} instance(s)", file=sys.stderr)
    for note in notes:
        print(f"MINE (note): {note}", file=sys.stderr)
    return path


def run(args) -> None:
    cmd = args.cmd or ["poetry", "run", "pytest"]
    stamp_first_run(args.task)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    ev = evidence_dir(args.task)
    if getattr(args, "job_id", ""):
        ev = ev / "runs" / args.job_id
        ev.mkdir(parents=True, exist_ok=True)
    log_path = ev / f"{args.label}-{ts}.log"
    xml_path = ev / f"{args.label}-{ts}.junit.xml"
    marker = ev / f"{args.label}-{ts}.running"
    cfg = load_config()
    reporter, inferred_from = reporter_choice(cmd, cfg, getattr(args, "reporter", "") or "")
    is_pytest = reporter == "pytest"
    if is_pytest and not any(str(c).startswith("--junitxml") for c in cmd):
        cmd = list(cmd) + [f"--junitxml={xml_path}"]
    quiet = False
    if is_pytest and not args.verbose and not any(str(c) in QUIET_FLAGS for c in cmd):
        cmd = list(cmd) + ["-q"]  # quiet by default (2026-09-11): the log is shorter, the summary is the same
    # Live logging off by default (2026-09-15, TP1-13958): with the project's own
    # `log_cli = true`, `-q` still produced 50-64 KB logs — every INFO line of every
    # request. That payload is what poisons an agent's context when the log is read, and
    # what bloats the repository when evidence is committed. Failure diagnosis does not
    # depend on it: the totals come from the junitxml, and `--detail` reads message and
    # traceback from there too. `--verbose` restores the full stream, and an explicit
    # --log-cli-level in the command always wins.
    if is_pytest and not args.verbose and not any("--log-cli-level" in str(c) for c in cmd):
        cmd = list(cmd) + ["--log-cli-level=WARNING"]
    if getattr(args, "tests", None):
        cmd = list(cmd) + list(args.tests)  # rerun of the failed tests only (S7), never the whole suite
        quiet = True

    env = dict(os.environ)
    env.setdefault("HEADLESS", "1")  # strategy rule 6; an explicit environment override is respected
    # EP1-22: the variables the COMMAND sets (a runner that names its report by a variable) win over the process environment,
    # and come AFTER the HEADLESS default: the command as written is the command as executed. Values hold the run's own file.
    env.update(getattr(args, "command_env", None) or {})
    started = datetime.now()

    # The log is streamed: a waiter (--wait) and a human see progress, and if the process is
    # killed everything it managed to print stays on disk (the "sanity killed at 87%" lesson —
    # previously all of it was lost).
    launched_at = time.monotonic()
    killed_by_run_suite = False  # RH2-9: exit 124 alone is not proof (the project's own command may exit 124)
    with log_path.open("w", encoding="utf-8") as lf:
        try:
            # EP1-35: the head is resolved on the environment's PATH and a `.cmd` wrapper's unsafe argument refused
            # (`CmdUnsafe` is an OSError: the `broken_run` branch below). `cmd` stays the profile's argv in the record.
            launch = project_env.checked_launch(cmd, env)
            proc = subprocess.Popen(launch, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    env=env, cwd=str(getattr(args, "cwd", None) or project_root()),
                                    start_new_session=(os.name != 'nt'))
        except FileNotFoundError:
            # Not a broken run: nothing ran. The binary this command starts with does not
            # exist in this session, which is a question for the person with three answers —
            # not a test result and not a silent handover (TP2-2536).
            lf.write(project_env.head_not_found(cmd[0]) + "; nothing was launched\n")
            refuse_missing_executor(str(getattr(args, "profile_id", "") or "this run's command"),
                                    str(cmd[0]), list(getattr(args, "mine", None) or []),
                                    active_story_stage(args.task) or "S5")
        except (OSError, ValueError) as exc:
            summary = {"task": args.task, "label": args.label, "command": cmd,
                       "exit_code": 127, "execution_status": "broken_run",
                       "launch_error": f"{type(exc).__name__}: {exc}",
                       "log": str(log_path.relative_to(project_root()))}
            lf.write(summary["launch_error"] + "\n")
            # Nothing ran: `pytest_s` and `after_s` are null, the rest is as measured. Never a reason to lose the summary.
            try:
                summary["phases_s"] = _phases_s(args, launched_at, None, time.monotonic())
            except Exception as exc:
                print(f"PHASES (note): not measured: {type(exc).__name__}: {exc}", file=sys.stderr)
            summary_path = ev / f"{args.label}-{ts}.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            if getattr(args, "job_store", None) and getattr(args, "job", None):
                args.job_store.update(args.job, status="failed_to_launch", execution_status="broken_run",
                                      summary=str(summary_path), launch_error=summary["launch_error"])
                refresh_dashboard()
            if summary.get("phases_s"):
                _say_phases(lambda: summary["phases_s"], lambda: time.monotonic() - _clock_zero(args))
            print(json.dumps(summary, ensure_ascii=False))
            sys.exit(127)
        # pid is run_suite's OWN, not the child command's: run_suite writes the summary and stays
        # alive until it lands. The child pid dies earlier (tests done, junit/teardown in progress) —
        # a waiter keyed on it would declare the run dead seconds before the summary (caught by test).
        marker.write_text(json.dumps({"pid": os.getpid(), "pid_started_at": process_started_at(os.getpid()),
                                      "child_pid": proc.pid, "child_started_at": process_started_at(proc.pid),
                                      "started": started.isoformat(timespec="seconds"),
                                      "command": cmd, "timeout_s": args.timeout, "log": log_path.name},
                                     ensure_ascii=False), encoding="utf-8")
        if getattr(args, "job_store", None) and getattr(args, "job", None):
            args.job = args.job_store.update(
                args.job, status="running", runner_pid=os.getpid(),
                runner_started_at=process_started_at(os.getpid()), child_pid=proc.pid,
                child_started_at=process_started_at(proc.pid))
            refresh_dashboard()

        def pump():
            for line in proc.stdout:
                lf.write(line)
                lf.flush()
        t = threading.Thread(target=pump, daemon=True)
        t.start()
        try:
            exit_code = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            exit_code = 124
            killed_by_run_suite = True
            t.join(timeout=5)
            lf.write(f"\n--- TIMEOUT {args.timeout}s: process killed, log kept (the 'sanity killed at 87%' lesson) ---\n")
        t.join(timeout=30)
        exited_at = time.monotonic()

    out = log_path.read_text(encoding="utf-8", errors="replace")
    summary = {
        "task": args.task, "label": args.label, "command": cmd, "exit_code": exit_code,
        "duration_s": round((datetime.now() - started).total_seconds(), 1),
        "log": str(log_path.relative_to(project_root())),
        "headless": env.get("HEADLESS"), "quiet": quiet,
        # `started` is naive LOCAL time; stamping it as UTC put every run's start hours away
        # from its end on a machine that is not on UTC (00:49 -> 22:49 on a +02:00 one).
        "started_at": started.astimezone(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }
    summary["reporter"] = reporter
    if inferred_from:
        summary["reporter_inferred_from"] = inferred_from  # a guess from the command's cure row, said out loud
    external = None
    if reporter in ("junit-xml", "trx") and not xml_path.exists():
        # The project's own command wrote the report; the factory reads it where config says,
        # and keeps a copy beside the log so the evidence is self-contained.
        declared = (Path(args.external_report_path) if getattr(args, "external_report_path", "")
                    else report_path(cfg))
        if declared is not None and declared.exists():
            if declared.stat().st_mtime < started.timestamp():
                summary["report_error"] = "stale report rejected: report predates this run"
            else:
                external = ev / f"{args.label}-{ts}{'.junit.xml' if reporter == 'junit-xml' else '.trx'}"
                try:
                    external.write_bytes(declared.read_bytes())
                except Exception:
                    external = declared
    source = xml_path if xml_path.exists() else external
    if source is not None and Path(source).exists():
        try:
            summary.update(parse_trx(Path(source)) if reporter == "trx"
                           else parse_junitxml(Path(source)))
            key = "trx" if reporter == "trx" else "junitxml"
            summary[key] = str(Path(source).relative_to(project_root()))
            summary["report_hash"] = hashlib.sha256(Path(source).read_bytes()).hexdigest()
            task_root = artifacts_dir(args.task).resolve()
            resolved_source = Path(source).resolve()
            if resolved_source.is_relative_to(task_root):
                summary["report_evidence"] = {
                    "path": resolved_source.relative_to(task_root).as_posix(),
                    "sha256": summary["report_hash"],
                }
            else:
                summary["report_evidence_error"] = True
                summary["report_error"] = "reporter evidence could not be copied into the task evidence directory"
        except Exception as e:
            summary["report_error"] = f"{type(e).__name__}: {e}"  # the raw log is kept anyway
        if inferred_from and not (summary.get("totals") or {}).get("tests"):
            # A guessed format that reads nothing is said, never silent (E-B-report-1): a wrong reader gives
            # exactly this, and the status logic below would call it not_executed without saying why. A parse
            # that raised leaves no totals, so it is covered; a parse that found tests and failed LATER (the
            # evidence copy) did read the report, and is not called a misread.
            summary["parse_gap"] = inferred_read_words(reporter, inferred_from)
    else:
        # Layer 1 honesty: no report — no parsed totals; the last screen of the log helps.
        summary["no_junitxml"] = "nothing to parse — read the raw log"
        summary["log_tail"] = out.strip().splitlines()[-15:]
        if reporter != "pytest":
            summary["parse_gap"] = no_report_words(cmd, reporter)
    if summary.get("parse_gap"):
        print("RUN REPORT GAP: " + summary["parse_gap"], file=sys.stderr)
    timeout_block, timeout_note = timeout_outcome(
        cmd, out, summary, (getattr(args, "job", None) or {}).get("request") or {},
        getattr(args, "cwd", None) or project_root(), killed_by_run_suite, args.timeout)
    if timeout_block:
        summary["timeout"] = timeout_block
        if timeout_block["how"] == "hard_kill" and "no_junitxml" in summary:
            summary["no_junitxml"] = ("nothing to parse - the project's per-test timeout killed the run before the report "
                                      "was written (see `timeout`)")
    if timeout_note:
        summary["timeout_note"] = timeout_note
    summary["teardown"] = teardown_playwright()
    summary["execution_status"] = execution_status(summary)
    if summary.get("report_evidence_error"):
        summary["execution_status"] = "inconclusive"
    summary.update(exit_reading(cmd, exit_code))  # before nothing_ran, which reads it
    if nothing_ran(summary):
        head = error_head(out)
        if head:
            summary["error_head"] = head
    typed = (getattr(args, "job", None) or {}).get("request") or {}
    if typed:
        summary["purpose"] = typed.get("purpose")
        summary["dispatch_id"] = typed.get("dispatch_id")
        summary["environment"] = str((typed.get("runtime_provenance") or {}).get("environment_id") or "")
        if typed.get("not_run_again"):  # a `--mine` call answered in part: what it did not run again
            summary["not_run_again"] = typed["not_run_again"]
    lease = getattr(args, "stand_lease", None)
    if isinstance(lease, dict):
        summary["stand_waited_s"] = lease.get("waited_s", 0)
        extra = {k: lease[k] for k in ("queued_behind", "took_over", "lease_error", "environment")
                 if lease.get(k)}
        if extra:
            summary["stand_lease"] = extra
    if getattr(args, "node_id_notes", None):
        summary["node_id_notes"] = list(args.node_id_notes)
    absent = ids_pytest_did_not_find(cmd, exit_code, out, typed)
    if absent:
        # The ids were not proven before the launch (an unreadable collect, or an `--node-id` that is never
        # collected), and pytest has now said it does not have them: the same `node_id_mismatch` the pre-launch
        # check gives, in the ordinary summary (exit 4 stays). Nothing was executed - never passed or failed.
        summary.update(blocked=NODE_ID_BLOCK, execution_status="not_executed",
                       missing=[{"asked": asked, "nearest": []} for asked in absent],
                       hint=(f"pytest did not find {', '.join(absent)}: nothing was executed, so this is neither a pass "
                             "nor a failure of the test. The id was not proven before the launch, so no nearest id is named: take "
                             "the right id from the test source, correct it where it is recorded (the manifest entry, "
                             f"or your request) and run again. {REPAIR_MARKER}."))

    if getattr(args, "job", None):
        try:
            verify_files(args.job["request"].get("fingerprint_files"))
        except ValueError as exc:
            summary["execution_status"] = "inconclusive"
            summary["input_change_error"] = str(exc)
        request = args.job["request"]
        if request.get("runtime_required", True):
            try:
                after = probe_runtime(request["runtime_probe"])
                before = request.get("runtime_probe_before") or request["runtime_provenance"]
                summary["runtime_probe_before"] = before
                summary["runtime_probe_after"] = after
                if (after.get("observed_runtime_identity") != before.get("observed_runtime_identity") or
                        after.get("expected_source_revision") != before.get("expected_source_revision")):
                    summary["execution_status"] = "inconclusive"
                    summary["runtime_change_error"] = "runtime identity/source changed during execution"
                elif _identity_unread(before) and _identity_unread(after):
                    # t-300 N2 E7: without docker both identities are `person-confirmed:<at>` - the compare can only see a
                    # NEW confirmation, never a redeploy under the same word. Said, so a run never claims "the same
                    # stand" for a stand nobody could read (FR-41).
                    summary["runtime_identity_unread"] = True
            except (OSError, subprocess.TimeoutExpired, RequestError) as exc:
                summary["execution_status"] = "inconclusive"
                summary["runtime_change_error"] = f"post-run runtime probe unavailable: {exc}"

    attach_diagnosis(args.task, summary)  # after every status this run can prove for itself
    summary_path = ev / f"{args.label}-{ts}.json"
    summary["summary_path"] = str(summary_path.relative_to(project_root()))
    signal = observe_stand(args.task, summary)
    if signal:
        summary["stand_signal"] = signal
    # Measured last, so `after_s` covers everything between the pytest exit and this write; the dashboard refreshes and the
    # run block that follow the write are not in the field (they are in `total_s` of the PHASES line). A failure to
    # measure drops the field and says so on stderr: the run is not the measurer's to stop.
    try:
        summary["phases_s"] = _phases_s(args, launched_at, exited_at, time.monotonic())
    except Exception as exc:
        print(f"PHASES (note): not measured: {type(exc).__name__}: {exc}", file=sys.stderr)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if signal:
        # Its own line, and on stderr like RUN REPORT GAP: stdout stays one JSON document,
        # which is what the scheduler and every role parse.
        print("STAND SIGNAL: " + str(signal.get("sentence") or signal.get("reason") or "stand_suspect"),
              file=sys.stderr)
    if getattr(args, "job_store", None) and getattr(args, "job", None):
        request = args.job["request"]
        baseline_path = None
        if request.get("evidence_phase") == "baseline":
            from baseline_contract import write_baseline_receipt
            baseline_path = write_baseline_receipt(artifacts_dir(args.task), request, summary, summary_path)
        block = build_run_block(request, summary, args.job["job_id"])
        unmatched = [r for r in (block or {}).get("results") or [] if r.get("reason_code") == "id_not_in_report"]
        if unmatched:
            # the reader of `reason_code` (AR-22): the count is its own number in the summary, apart from `not_run`, and the console
            # says it on stderr (stdout stays one JSON document). A name may hold a non-ASCII separator: the stream is set to utf-8.
            summary["id_not_in_report"] = len(unmatched)
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            import console_io                     # the one place that sets a stream (K5): no reconfigure loop of its own
            console_io.utf8_stdio()
            print(f"{len(unmatched)} selected test(s) have no row in the report (id_not_in_report); see the block's rows",
                  file=sys.stderr)
        block_path = write_run_block(args.task, block) if block else None
        short = selection_line(block, block_path.relative_to(project_root()).as_posix() if block_path else "")
        if short:
            import console_io
            console_io.utf8_stdio()
            print(short, file=sys.stderr)
        args.job_store.update(args.job, status="completed", execution_status=summary["execution_status"],
                              freshness=args.job["request"].get("freshness", "unknown"),
                              summary=str(summary_path.relative_to(project_root())),
                              run_block=(str(block_path.relative_to(project_root())) if block_path else None),
                              baseline_receipt=(str(baseline_path.relative_to(project_root())) if baseline_path else None))
        refresh_dashboard()
    marker.unlink(missing_ok=True)  # the summary is on disk — the marker is no longer needed
    if summary.get("phases_s"):
        _say_phases(lambda: summary["phases_s"], lambda: time.monotonic() - _clock_zero(args))
    print(json.dumps(summary, ensure_ascii=False))
    sys.exit(exit_code)


def wait(args) -> None:
    ev = evidence_dir(args.task)
    markers = sorted(ev.glob(f"{args.label}-*.running"), key=lambda p: p.stat().st_mtime)
    if not markers:
        done = sorted(ev.glob(f"{args.label}-*.json"), key=lambda p: p.stat().st_mtime)
        if done:
            print(json.dumps(json.loads(done[-1].read_text(encoding="utf-8")), ensure_ascii=False))  # already finished — the summary is on disk
            sys.exit(0)
        print(json.dumps({"status": "nothing_to_wait", "label": args.label,
                          "hint": "neither a .running marker nor a .json summary with this label — the run was never started"},
                         ensure_ascii=False))
        sys.exit(2)

    marker = markers[-1]
    stamp = marker.name[len(args.label) + 1:-len(".running")]
    summary_path = ev / f"{args.label}-{stamp}.json"
    log_path = ev / f"{args.label}-{stamp}.log"
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        info = {}
    pid = int(info.get("pid") or 0)
    started = info.get("started")

    deadline = time.time() + args.wait_max
    while True:
        if summary_path.exists():
            print(json.dumps(json.loads(summary_path.read_text(encoding="utf-8")), ensure_ascii=False))
            sys.exit(0)
        if pid and not same_process(pid, str(info.get("pid_started_at") or "")):
            # The process is gone and there is no summary: killed from outside, the interpreter
            # crashed, the machine went down. The marker is removed so the next --wait does not
            # wait for the dead; the log stays as evidence.
            marker.unlink(missing_ok=True)
            print(json.dumps({"status": "died", "label": args.label, "stamp": stamp, "pid": pid,
                              "started": started, "log": str(log_path.relative_to(project_root())),
                              "log_tail": log_tail(log_path),
                              "hint": "the process ended without a summary — read the log, do not blindly relaunch"},
                             ensure_ascii=False))
            sys.exit(4)
        if time.time() >= deadline:
            break
        time.sleep(min(args.poll, max(1, deadline - time.time())))

    elapsed = None
    try:
        elapsed = round((datetime.now() - datetime.fromisoformat(started)).total_seconds(), 0)
    except Exception:
        pass
    print(json.dumps({"status": "running", "label": args.label, "stamp": stamp, "pid": pid,
                      "started": started, "elapsed_s": elapsed, "timeout_s": info.get("timeout_s"),
                      "log": str(log_path.relative_to(project_root())),
                      "log_lines": sum(1 for _ in log_path.open(encoding="utf-8", errors="replace")) if log_path.exists() else 0,
                      "log_tail": log_tail(log_path),
                      "hint": f"still running — call --wait again (this call waited {args.wait_max} s)"},
                     ensure_ascii=False))
    sys.exit(3)


# Every field `execution_request.validate_request` requires, with the one line that says
# where its value comes from. S5/S6/S7 run only through typed requests, and until 0.7.7 the
# shape lived in `execution_request.py` and in `record-schemas.json`, which no role is
# injected with: the roles brute-forced it against validator errors (stage_guard counted 42
# guard refusals over six S5 windows on TP1-15045). A skeleton costs one call.
REQUEST_TEMPLATE_FIELDS = [
    ("task", "the ticket id", "<TICKET>"),
    ("revision", "state.revision from the controller prepare packet", "<revision>"),
    ("dispatch_id", "the id of YOUR open dispatch, from the prepare packet", "<dispatch id>"),
    ("profile_id", "the execution profile in qa-factory/config.json", "<profile id>"),
    ("purpose", "initial | repair_verify | red_probe | diagnostic | flaky_diagnostic | "
                "build | collect | manual | quality", "initial"),
    ("reason", "one sentence: why this run has to happen now", "<why this run>"),
    ("idempotency_key", "unique per attempt; a repeat of the same key returns the same job",
     "<dispatch id>:<purpose>:1"),
    ("input_fingerprint", "execution_fingerprint.py over the actual files", "<fingerprint>"),
    ("fingerprint_components", "immutable identities, all three required",
     {"source_sha": "<source sha>", "test_content_sha": "<test bytes sha>",
      "config_sha": "<config sha>"}),
    ("fingerprint_files", "optional: the files the fingerprint was taken over", []),
    ("freshness", "literally 'fresh'; unknown or stale evidence cannot match", "fresh"),
    ("remaining_budget", "what is left of this story's run budget; a behavioral run needs > 0",
     1),
    ("selected_instance_ids", "the instances THIS run executes (contract.instance_id) — one "
                              "request per GROUP of the window, not one per case",
     ["<function>[<param>]"]),
    ("current_scope_instance_ids", "every instance of the approved stage scope; selected "
                                   "must be a subset", ["<function>[<param>]"]),
    ("runtime_required", "false only for a verified local_source profile", True),
    ("target_kind", "local_source when runtime_required is false", "<target kind>"),
    ("runtime_provenance", "the environment identity you verified before the run",
     {"profile_id": "<profile id>", "timestamp": "<ISO-8601 UTC>",
      "environment_id": "<environment>", "expected_source_revision": "<source sha>",
      "observed_runtime_identity": "<what the stand actually runs>", "result": "matched",
      "evidence_refs": ["<task-relative evidence path>"],
      "provenance": {"technical_verification": True, "source_linkage": "exact",
                     "deployed_source_revision": "<source sha>"}}),
    ("runtime_probe", "read-only command re-run after execution; identical output required",
     {"argv": ["<probe command>"], "cwd": "<cwd>", "timeout_s": 30}),
    ("command", "the one scoped command; reporter and report_path make the evidence readable; "
                "{report_path} may sit inside a token. Optional command.selector_join, when the "
                "runner takes ONE selection option for many tests: "
                '{"option": "--filter", "separator": "|"} (each instance\'s selector_args must then '
                "be [option, value]; without it the selector_args are repeated per instance). A runner that "
                'names its report by a variable takes it in command.env instead: {"<VARIABLE>": "{report_path}"} '
                "(the value is exactly {report_path}; the placeholder sits in ONE place, argv or env)",
     {"argv": ["<runner>", "{report_path}"], "cwd": "<cwd>", "reporter": "junit-xml",
      "report_path": "{report_path}", "scope": "selected", "repo_id": "<repository>",
      "selector_contract_verified": True,
      "selector_args": {"<function>[<param>]": ["<framework selector>"]}}),
    ("instance_contracts", "the exact reporter row each instance maps to; a missing or "
                           "ambiguous row is not_run, never a guessed match",
     {"<function>[<param>]": {"report_test_id": "<reporter id>", "parameters": {}}}),
    ("execution", "reporter must match command.reporter; selection says why this run happened",
     {"schema_version": 1, "reporter": {"format": "junit-xml", "path_template": "{report_path}"},
      "selection": {"reason": "missing_fresh_evidence",
                    "evidence_refs": ["<task-relative evidence path>"]}}),
]

SCHEDULE_TEMPLATE_FIELDS = [
    ("requests", "two or more complete RunRequests (--template request)", ["<RunRequest>"]),
    ("mode", "auto | serial", "auto"),
    ("min_selected_instances", "the parallel threshold; below it, send --request instead", 8),
    ("max_workers", "optional positive cap", 4),
    ("source_revision", "the pinned source sha every request shares", "<source sha>"),
]


def template(kind: str) -> tuple:
    """(skeleton, legend). The skeleton is valid JSON to fill in; the legend is one line per
    field, so `--template request > request.json` leaves a file worth editing."""
    fields = SCHEDULE_TEMPLATE_FIELDS if kind == "schedule" else REQUEST_TEMPLATE_FIELDS
    name = "schedule" if kind == "schedule" else "RunRequest"
    legend = [f"# {name} — every field below is required unless its line says otherwise.",
              "# Replace every <angle-bracket> placeholder; a value you cannot source is a",
              "# gap for your digest, never a plausible invention."]
    legend += [f"#   {key}: {why}" for key, why, _value in fields]
    return {key: value for key, _why, value in fields}, legend


def selftest() -> int:
    """Pure-mechanics smoke test: no pytest is launched. Exercises the parts every run
    depends on — junitxml parsing, output clipping, the evidence dir under the (possibly
    synthetic) project root — so a broken import or a bad root split fails loudly here
    instead of on the runner's first real dispatch."""
    import tempfile

    failures: list[str] = []

    def case(name: str, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("_clip: short text is untouched", _clip("short", 100), "short")
    case("_clip: long text is shortened", len(_clip("x" * 5000, 200)) < 5000, True)

    missing = executor_gap({"profile_id": "tests-e2e-ios", "built_by": {"cases": ["TC-001"]},
                            "command": {"argv": ["maestro-not-installed-anywhere"], "cwd": "."}}, {})
    case("a launcher that is not on PATH stops the run before a job is begun",
         (missing or {}).get("tool"), "maestro-not-installed-anywhere")
    case("a launcher that resolves is never a refusal",
         executor_gap({"profile_id": "p", "command": {"argv": [sys.executable], "cwd": "."}}, {}), None)

    with tempfile.TemporaryDirectory(prefix="run-suite-selftest-") as td:
        xml_path = Path(td) / "sample.junit.xml"
        xml_path.write_text(
            '<testsuite tests="3" failures="1" errors="0" skipped="1" time="0.4">'
            '<testcase classname="pkg.mod" name="test_ok"/>'
            '<testcase classname="pkg.mod" name="test_bad">'
            '<failure message="boom">traceback here</failure>'
            '</testcase>'
            '<testcase classname="pkg.mod" name="test_later">'
            '<skipped message="pending implementation"/>'
            '</testcase>'
            '</testsuite>',
            encoding="utf-8",
        )
        summary = parse_junitxml(xml_path)
        case("parse_junitxml: totals.tests", summary["totals"]["tests"], 3)
        case("parse_junitxml: totals.failures", summary["totals"]["failures"], 1)
        case("parse_junitxml: totals.passed", summary["totals"]["passed"], 1)
        case("parse_junitxml: one failed test recorded", len(summary["failed"]), 1)
        rows = {r["test_id"]: r for r in summary["results"]}
        case("results: one row per test", len(summary["results"]), 3)
        case("results: the passed test is named",
             rows.get("pkg.mod::test_ok", {}).get("status"), "passed")
        case("results: the failed test carries its reason",
             rows.get("pkg.mod::test_bad", {}).get("reason"), "boom")
        # The TP2-2290 defect in one line: a skipped test must arrive with its NAME
        # and its REASON, or the dashboard has nothing to show but a question mark.
        case("results: the skipped test is named",
             rows.get("pkg.mod::test_later", {}).get("status"), "skipped")
        case("results: the skip reason travels with the row",
             rows.get("pkg.mod::test_later", {}).get("reason"), "pending implementation")
        case("execution_status: a run with a failure is failed",
             execution_status({"exit_code": 1, **summary}), "failed")

    for name, summ, expected in (
        ("all green", {"exit_code": 0, "totals": {"tests": 3, "failures": 0, "errors": 0, "skipped": 0}}, "passed"),
        ("collection error", {"exit_code": 2, "totals": {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}}, "broken_run"),
        ("nothing collected", {"exit_code": 0, "totals": {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}}, "not_executed"),
        ("timeout", {"exit_code": 124}, "timeout"),
        ("no junit, non-zero exit", {"exit_code": 3}, "broken_run"),
        ("timeout: hard kill", {"exit_code": 1, "timeout": {"how": "hard_kill"}}, "timeout"),
        ("failed_in_report keeps failed", {"exit_code": 1, "totals": {"tests": 2, "failures": 1},
                                           "timeout": {"how": "failed_in_report"}}, "failed"),
    ):
        case(f"execution_status: {name}", execution_status(summ), expected)

    # A .NET run the factory could not read at all until now: "Passed: 10, Failed: 0,
    # Total: 10" in the log, `not_executed` in the record, and a real failure indistinguishable
    # from a broken MSBuild.
    with tempfile.TemporaryDirectory(prefix="run-suite-trx-") as td:
        trx = Path(td) / "results.trx"
        trx.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">'
            '<Results>'
            '<UnitTestResult testName="Cart.CapRejected" outcome="Passed"/>'
            '<UnitTestResult testName="Cart.CapAccepted" outcome="Failed">'
            '<Output><ErrorInfo><Message>expected 200 but was 500</Message></ErrorInfo></Output>'
            '</UnitTestResult>'
            '<UnitTestResult testName="Cart.Later" outcome="NotExecuted"/>'
            '</Results>'
            '<ResultSummary outcome="Failed">'
            '<Counters total="3" executed="2" passed="1" failed="1" error="0" notExecuted="1"/>'
            '</ResultSummary></TestRun>',
            encoding="utf-8")
        trx_summary = parse_trx(trx)
        case("parse_trx: totals.tests", trx_summary["totals"]["tests"], 3)
        case("parse_trx: totals.failures", trx_summary["totals"]["failures"], 1)
        case("parse_trx: totals.passed", trx_summary["totals"]["passed"], 1)
        case("parse_trx: the failed test is named",
             trx_summary["failed"][0]["test"], "Cart.CapAccepted")
        case("parse_trx: with its first message line",
             trx_summary["failed"][0]["why"], "expected 200 but was 500")
        case("parse_trx: a green .NET run reads as passed",
             execution_status({"exit_code": 0, **parse_trx(trx), "totals":
                               {"tests": 10, "failures": 0, "errors": 0, "skipped": 0}}), "passed")
        case("parse_trx: a .NET failure is `failed`, not `broken_run`",
             execution_status({"exit_code": 1, **trx_summary}), "failed")
        # An unknown is not a pass, and a failure past the cap is still listed: a result with no
        # outcome is `not_run`, and only PASSED rows are cut at the cap (it used to cut every row).
        capped = Path(td) / "capped.trx"
        capped.write_text(
            '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>'
            + "".join(f'<UnitTestResult testName="Cart.Ok{i}" outcome="Passed"/>'
                      for i in range(RESULT_ROWS_CAP + 1))
            + '<UnitTestResult testName="Cart.NoOutcome"/>'
            '<UnitTestResult testName="Cart.Late" outcome="Failed"/>'
            '</Results></TestRun>', encoding="utf-8")
        capped_summary = parse_trx(capped)
        capped_rows = {r["test_id"]: r["status"] for r in capped_summary["results"]}
        case("parse_trx: a result with no outcome is not_run, not passed",
             capped_rows.get("Cart.NoOutcome"), "not_run")
        case("parse_trx: a failed row past the cap is listed", capped_rows.get("Cart.Late"), "failed")
        case("parse_trx: the cap note counts the passed rows left out",
             "1 passed rows beyond" in capped_summary.get("results_note", ""), True)

    for name, cmd_in, cfg_in, explicit, expected in (
        ("pytest is inferred", ["poetry", "run", "pytest"], {}, "", "pytest"),
        ("dotnet test asks for a report", ["dotnet", "test"], {}, "", "junit-xml"),
        ("a trx logger is trx", ["dotnet", "test", "--logger", "trx;LogFileName=r.trx"], {}, "", "trx"),
        ("ng test is junit", ["ng", "test", "--reporters", "junit"], {}, "", "junit-xml"),
        ("the project's declaration wins", ["make", "test"], {"run": {"reporter": "junit-xml"}}, "", "junit-xml"),
        ("an explicit flag wins over the config", ["make", "test"], {"run": {"reporter": "junit-xml"}}, "trx", "trx"),
        ("a command that says nothing produces nothing", ["make", "test"], {}, "", "none"),
    ):
        case(f"resolve_reporter: {name}", resolve_reporter(cmd_in, cfg_in, explicit), expected)
    case("reporter_choice: a command only its cure row knows is inferred, and the row is named",
         reporter_choice(["ng", "e2e"], {}, ""), ("junit-xml", "karma"))
    case("reporter_choice: a command_formats hit is not an inference (dotnet test stays junit-xml)",
         reporter_choice(["dotnet", "test"], {}, ""), ("junit-xml", ""))

    case("report_cure: karma is told the reporter AND the package it needs",
         "karma-junit-reporter" in report_cure(["npx", "karma", "start", "karma.conf.js"]), True)
    case("report_cure: pytest needs nothing — the runner equips it",
         report_cure(["poetry", "run", "pytest", "-q"]), "")

    case("pid_alive: current process is alive", pid_alive(os.getpid()), True)

    # 0.7.8: the cause of a run in which nothing ran, and the two switches around a launch.
    case("error_head: the usage error of an exit-4 run is kept, the noise is not",
         error_head("collected 0 items\nERROR: not found: t.py::test_x[buffer-R3]\nnoise\nE   boom\n"),
         ["ERROR: not found: t.py::test_x[buffer-R3]", "E   boom"])
    case("nothing_ran: pytest exit 4", nothing_ran({"exit_code": 4}), True)
    case("nothing_ran: a red run ran", nothing_ran({"exit_code": 1, "totals": {"tests": 3}}), False)
    case("nothing_ran: a runner row that does not list the exit: the totals decide",
         nothing_ran({"exit_code": 4, "exit_means_not_executed": False, "totals": {"tests": 3}}), False)
    case("exit_reading: the pytest row lists exit 4", exit_reading(["pytest"], 4), {"exit_means_not_executed": True})
    case("exit_reading: no row means no fact", exit_reading(["dotnet", "test"], 4)["exit_means_not_executed"], None)
    case("stand_is_serial: run.parallel false", stand_is_serial({"run": {"parallel": False}}), True)
    case("stand_is_serial: a project that says nothing is left alone", stand_is_serial({}), False)
    case("_collect_argv: the report flag does not reach a collect",
         _collect_argv(["pytest", "--junitxml", "{report_path}", "-x"]), ["pytest", "-x"])

    # A throwaway project, marker and all: evidence belongs to a project, and since the
    # root is resolved by that marker, a selftest run from anywhere else must NOT create
    # one. Before this the case ran in whatever repository happened to be the git top
    # level and quietly built a qa-factory/ tree there.
    import hooklib
    with tempfile.TemporaryDirectory(prefix="run-suite-project-") as proj, \
            hooklib.selftest_root_restored():
        (Path(proj) / "qa-factory").mkdir()
        (Path(proj) / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        # Pin it, cache and env var both: clearing the cache only asked cwd again, and from a
        # cwd inside a real project the answer was that project (`evidence_dir: inside the
        # project the marker named` on the macOS 0.7.11 install).
        hooklib.pin_project_root(proj)
        print(f"SELFTEST ROOT: {hooklib.project_root()}")
        (Path(proj) / "qa-factory" / "artifacts" / "_selftest").mkdir(parents=True)   # the story: S0 makes it, never evidence_dir
        ev = evidence_dir("_selftest")
        case("evidence_dir: created under the project's artifacts", ev.exists(), True)
        case("evidence_dir: inside the project the marker named",
             str(ev).startswith(str(Path(proj).resolve())) or str(ev).startswith(proj), True)

    if failures:
        print(f"RUN_SUITE SELFTEST: VIOLATIONS ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RUN_SUITE SELFTEST: no violations (junit/trx parsing, reporters, clipping, evidence dir)")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    ap = argparse.ArgumentParser(description="Code-level suite runner (one call = one run)")
    ap.add_argument("--request", type=Path, help="typed RunRequest JSON (preferred)")
    ap.add_argument("--schedule", type=Path, help="bounded schedule JSON containing typed requests")
    ap.add_argument("--recover", metavar="IDEMPOTENCY_KEY",
                    help="inspect one durable typed job; never relaunch it")
    ap.add_argument("--reparse-block", type=Path,
                    help="reparse one immutable run block with --mapping; never launches tests")
    ap.add_argument("--mapping", type=Path, help="exact instance_contracts JSON for --reparse-block")
    ap.add_argument("--template", choices=("request", "schedule"),
                    help="print a complete skeleton to fill in (JSON on stdout, one legend "
                         "line per field on stderr); runs nothing")
    ap.add_argument("--task", help="task id — the evidence directory")
    ap.add_argument("--label", help="run name: sanity/impact/full/...")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds; timeout → exit 124, log kept")
    ap.add_argument("--wait", action="store_true",
                    help="do not run; wait for an already running run with this label (see the header: exit 0/2/3/4)")
    ap.add_argument("--wait-max", dest="wait_max", type=int, default=WAIT_MAX_DEFAULT,
                    help=f"seconds to wait per --wait call (default {WAIT_MAX_DEFAULT} — under the tool's 600 s cap)")
    ap.add_argument("--poll", type=int, default=POLL_DEFAULT, help="seconds between checks in --wait")
    ap.add_argument("--verbose", action="store_true", help="do not add -q to a pytest command")
    ap.add_argument("--reporter", choices=REPORTERS, default="",
                    help="which machine-readable report this command produces (default: config.run.reporter, else inferred from the command)")
    ap.add_argument("--tests", nargs="+", metavar="TEST_ID",
                    help="run only these test ids (pytest node ids or the framework's selector), appended to the command")
    ap.add_argument("--detail", metavar="TEST", help="do not run; print the failure text of ONE test (substring of classname::name) from the latest report (JUnit XML or TRX) with this label")
    ap.add_argument("--max-chars", dest="max_chars", type=int, default=6000, help="clip the failure text for --detail (head + tail)")
    ap.add_argument("--mine", nargs="+", metavar="CASE",
                    help="run the tests of these cases (comma or space separated) for the OPEN dispatch: "
                         "the typed request is built from controller.json and the manifest, written "
                         "under work/requests/ and run; no request JSON is written by hand")
    ap.add_argument("--purpose", choices=("initial", "repair_verify", "red_probe"), default="",
                    help="--mine: default is initial for a first run of the instances, repair_verify afterwards")
    ap.add_argument("--dispatch", default="", help="--mine: the dispatch id, only when several are open")
    ap.add_argument("--profile", default="", help="--mine: the execution profile, only when it cannot be told from the test path")
    ap.add_argument("--cwd", dest="cwd_override", default="",
                    help="--mine: run inside this directory, taken as given")
    ap.add_argument("--sandbox-root", dest="sandbox_root", default="",
                    help="--mine: the root of a clone (the red-probe sandbox); the run directory is "
                         "worked out inside it from the profile, so its subdirectory is kept")
    ap.add_argument("--node-id", dest="node_id", action="append", metavar="NODE_ID",
                    help="--mine with ONE case: the test(s) to run when the manifest does not name them yet. "
                         "An id without [...] in an existing file is not collected: the run itself answers "
                         "`node_id_mismatch` when pytest does not find it")
    ap.add_argument("--collect-only", dest="collect_only", action="store_true",
                    help="run NOTHING: take one collect of the files the --tests ids name (the test command after `--`) and print "
                         "the `runs[]` row `kind: collect` (`partial: true` when a file failed to import) - the evidence of a "
                         "test that is written but cannot run yet; a collect is never a run witness")
    ap.add_argument("--again", action="store_true",
                    help="--mine: run again even though a green run over the same bytes is recorded")
    ap.add_argument("--reason", default="", help="--mine: one sentence recorded as the run's reason")
    ap.add_argument("--stand-wait", dest="stand_wait", type=int, default=None,
                    help="seconds to wait for a busy non-parallel stand (default: config run.stand_wait_s, 1800)")
    ap.add_argument("cmd", nargs="*", help="command after -- (default: poetry run pytest)")
    args = ap.parse_args()
    if args.mine and (args.request or args.schedule):
        ap.error("--mine builds its own request; do not combine it with --request/--schedule")
    if args.template:
        skeleton, legend = template(args.template)
        print("\n".join(legend), file=sys.stderr)
        print(json.dumps(skeleton, ensure_ascii=False, indent=2))
        sys.exit(0)
    if args.reparse_block:
        if not args.task or not args.mapping:
            ap.error("--reparse-block requires --task and --mapping")
        try:
            mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
            output = reparse_run_block(artifacts_dir(args.task), args.reparse_block, mapping)
        except (OSError, json.JSONDecodeError, RequestError) as exc:
            print(json.dumps({"status": "invalid_reparse", "error": str(exc)}), file=sys.stderr)
            sys.exit(2)
        from finalize_task import refresh
        refresh(artifacts_dir(args.task))
        print(json.dumps({"status": "reparsed", "run_block": str(output),
                          "attempt_id_preserved": True}, ensure_ascii=False))
        sys.exit(0)
    if args.schedule:
        from execution_scheduler import execute_schedule
        notes: list = []
        try:
            document = json.loads(args.schedule.read_text(encoding="utf-8"))
            document, notes = merge_schedule(document)
            if any(str((r or {}).get("purpose")) == "red_probe"
                   for r in document.get("requests") or [] if isinstance(r, dict)):
                hold_dashboard("red probe in this batch")
            receipt = execute_schedule(document, project_root(), Path(__file__).resolve())
        except Exception as exc:
            print(json.dumps({"status": "invalid_schedule", "error": str(exc),
                              "notes": notes}, ensure_ascii=False), file=sys.stderr)
            sys.exit(2)
        print(json.dumps(dict(receipt, notes=notes) if notes else receipt, ensure_ascii=False))
        sys.exit(0 if all(row.get("status") in {"completed", "reused", "already_run", "duplicate"}
                          and row.get("exit_code", 0) == 0 for row in receipt["groups"]) else 1)
    if args.recover:
        if not args.task:
            ap.error("--recover requires --task")
        store = JobStore(artifacts_dir(args.task) / "state" / "execution-jobs")
        try:
            recovered = store.recover(args.recover, same_process)
        except RequestError as exc:
            print(json.dumps({"status": "invalid_recovery", "error": str(exc)}), file=sys.stderr)
            sys.exit(2)
        refresh_dashboard()
        print(json.dumps({**recovered["job"], "job_status": recovered["job"].get("status"),
                          "status": recovered["action"]}, ensure_ascii=False))
        sys.exit(0 if recovered["action"] in {"reused", "complete", "running"} else 4)
    # --detail reads a finished run and launches nothing, so it is answered before anything
    # that validates, begins a job or refuses a label. On TP1-15045 both spellings
    # failed an automator inside its dispatch: `--task --label --detail` was refused as an
    # untyped story run, and `--request FILE --detail` printed the duplicate job record and
    # exited before `detail()` — so the role went for the raw log, which the guard blocks.
    if args.detail:
        if args.mine and not args.label:
            resolve_mine_detail(args)
        elif args.request:
            resolve_detail_target(args)
        if not args.task or not args.label:
            ap.error("--detail needs --task and --label, or --request FILE, or --mine CASE")
        _refuse_phantom_story(args.task)
        detail(args)
    if args.collect_only:
        if not args.task or not args.tests or not args.cmd:
            ap.error("--collect-only needs --task, --tests <node ids> and the test command after `--`")
        _refuse_phantom_story(args.task)
        sys.exit(collect_only(args))
    if args.mine:
        args.request = mine(args)
    cfg = load_config()
    if args.request:
        try:
            raw_request = json.loads(args.request.read_text(encoding="utf-8"))
            if str(raw_request.get("purpose")) == "red_probe":
                hold_dashboard("red probe compares the author's tree byte for byte")
            raw_task = str(raw_request.get("task") or "")
            # the request's task is the story it runs for: a story that is not there is refused HERE, before a store
            # is named and long before a job is begun - a key from outside must never make a folder (CX1-18, E-7)
            task_root = story_root(raw_task, "run_suite.py --request: the request's task")
            # C8 (t-2181 PC-9b, t-2277 W1): a request aimed at a reference stand GOES - its block is written as a sample (`reference_run`). What
            # is still refused at entry is the record's contradiction (the story's own stand named as a reference too) - after the story is
            # known to exist, before a store, a key, a probe, a budget answer or a stand lease: nothing is left behind. Exit 2 as the budget's refusal.
            from execution_request import reference_target_problem
            _reference = reference_target_problem(project_root(), raw_task,
                                                  (raw_request.get("runtime_provenance") or {}).get("environment_id")
                                                  if isinstance(raw_request.get("runtime_provenance"), dict) else "")
            if _reference:
                print(json.dumps({"status": "run_refused", "error": _reference}, ensure_ascii=False))
                sys.exit(2)
            store = JobStore(task_root / "state" / "execution-jobs")
            existing = store.read(str(raw_request.get("idempotency_key") or ""))
            request = validate_request(raw_request, project_root(), allow_exhausted_reuse=bool(existing))
            if request.get("runtime_required", True):
                # `--mine` has just looked at this very stand while it built the request: that reading is the
                # one before the launch (HF2-10, B-K5); only a request nobody observed here - a file written by
                # hand, a red probe that copies, an unobserved stand - is looked at now (B-E11, B-E14).
                observed = _observed_while_building(args, request) or probe_runtime(request["runtime_probe"])
                expected = request["runtime_provenance"]
                # What moved is NAMED (t-300 N2 S2a, FR-1): a request built on one stand reading and launched on
                # another is refused before anything ran, and the person reading the refusal can tell a redeploy
                # (the identity) from another story's probe (the profile) from a moved checkout (the revision).
                moved = [name for name, was, now in (
                    ("profile_id", request["profile_id"], observed.get("profile_id")),
                    ("observed_runtime_identity", expected.get("observed_runtime_identity"),
                     observed.get("observed_runtime_identity")),
                    ("expected_source_revision", expected.get("expected_source_revision"),
                     observed.get("expected_source_revision"))) if was != now]
                if moved:
                    raise RequestError("runtime probe does not match requested profile/source/runtime: "
                                       + ", ".join(moved) + " moved since the request was built")
                request["runtime_probe_before"] = observed
            if existing:
                # A key that already holds a run is answered from it - never for a request made
                # while the stand's version was not observed: `reused` would say "the same stand"
                # of a stand nobody looked at (FR-41). A `--mine` request takes a key of its own.
                from execution_request import load_run_budget as _load_budget, say as _say_budget
                _policy = _load_budget()[0]
                if _policy is not None and request.get("runtime_observed") is False:
                    print(json.dumps({"status": "run_refused", "error": _say_budget(
                        _policy, "unobserved_repeat", environment=str(
                            (request.get("runtime_provenance") or {}).get("environment_id") or "<environment>"))},
                        ensure_ascii=False))
                    sys.exit(2)
                action, job = store.begin(request)  # duplicate / reused: nothing is launched
                if action != "launch":
                    print_not_launched(action, job, brief=bool(args.mine))
                    sys.exit(0)
        except (OSError, json.JSONDecodeError, RequestError, StoryRootError) as exc:
            print(json.dumps({"status": "invalid_request", "error": str(exc)}), file=sys.stderr)
            sys.exit(2)
        # The run budget (D-0017/D-0018/D-0019) is asked after the existing-key branch above
        # (a repeat of the very same request is that branch's, unchanged) and before any key or
        # stand lease is taken: an answered or refused request leaves nothing behind. What
        # `--mine` builds was answered while it was built, so only a typed request is asked here.
        from execution_request import (is_pytest_command, load_run_budget, request_verdict, run_block_reader,
                                       say, stand_reset_at, strip_rerun_flags)
        policy, budget_note = load_run_budget()
        if policy is None and not args.mine:
            print(f"RUN BUDGET (note): {budget_note}", file=sys.stderr)
        if policy is not None and not args.mine:
            verdict = request_verdict(
                request, store.jobs(), policy=policy, task_root=task_root,
                active_stage=active_story_stage(raw_task), reset_at=stand_reset_at(project_root()),
                block_of=run_block_reader(project_root()))
            for note in verdict["notes"]:
                print(f"RUN BUDGET (note): {note}", file=sys.stderr)
            if verdict["action"] == "answer":
                answered = verdict["answer"]
                print_not_launched(answered["status"], answered["jobs"][-1], brief=True, answer=answered)
                sys.exit(0)
            if verdict["action"] == "refuse":
                print(json.dumps({"status": "run_refused", "error": verdict["message"]}, ensure_ascii=False))
                sys.exit(2)
        # Every check here comes BEFORE the job is begun: a run that is not launched must not
        # leave a claimed idempotency key behind, or the corrected retry is a "duplicate".
        gap = executor_gap(request, cfg)
        if gap:
            refuse_missing_executor(gap["profile"], gap["tool"], gap["cases"],
                                    active_story_stage(str(request.get("task") or "")) or "S5")
        checked = None if getattr(args, "node_ids_verified", False) else verify_node_ids(
            request, cfg, mined=getattr(args, "mine_memo", None))
        for note in (checked or {}).get("notes") or []:
            print(f"NODE IDS (note): {note}", file=sys.stderr)
        launched = apply_resolved_ids(request, (checked or {}).get("resolved") or {})
        for asked, real in ((checked or {}).get("resolved") or {}).items():
            print(f"NODE IDS (note): {asked} is collected as {real}; ran the real id", file=sys.stderr)
        args.node_id_notes = ((checked or {}).get("notes") or []) + [
            f"{asked} -> {real}" for asked, real in ((checked or {}).get("resolved") or {}).items()]
        environment = str((request.get("runtime_provenance") or {}).get("environment_id") or "")
        from execution_request import request_digest
        with hold_stand(cfg, request_digest(request)[:20], environment, args.stand_wait) as lease:
            args.stand_lease = lease
            try:
                action, job = store.begin(request)
            except RequestError as exc:
                print(json.dumps({"status": "invalid_request", "error": str(exc)}), file=sys.stderr)
                sys.exit(2)
            if action != "launch":
                print_not_launched(action, job, brief=bool(args.mine))
                sys.exit(0)
            if launched is not request:
                job = dict(job, request=launched)
            args.task = request["task"]
            args.label = f"{request['purpose']}-{job['job_id']}"
            suffix = ".trx" if request["command"]["reporter"] == "trx" else ".junit.xml"
            unique_report = (evidence_dir(args.task) / "runs" / job["job_id"] / ("report" + suffix)).resolve()
            unique_report.parent.mkdir(parents=True, exist_ok=True)
            launch_argv = launched["resolved_argv"]
            if (policy is not None and request["purpose"] in policy["strip_reruns_purposes"]
                    and is_pytest_command(launch_argv)):
                # A probe must fail once and a flake series counts isolated runs: the project's
                # own `--reruns N` would make each launch up to N+1 executions (measured on
                # TP1-13797: every red probe ran the mutated test three times).
                launch_argv, removed = strip_rerun_flags(launch_argv, set(policy["rerun_flags"]),
                                                         set(policy.get("rerun_flags_regex") or []))
                if removed:
                    print("RUN BUDGET (note): " + say(policy, "reruns_removed", flags=", ".join(removed),
                                                      purpose=request["purpose"]), file=sys.stderr)
            # the placeholder is replaced INSIDE its token (`trx;LogFileName={report_path}` as well as a bare
            # `{report_path}`), the way the gate's reporter probe does (gate_preflight): S5 and the probe agree on what
            # a proven command is (t-300 N2 F1-b220, FR-17)
            args.cmd = [part.replace("{report_path}", str(unique_report)) for part in launch_argv]
            # the SAME file the summary reads below (`unique_report`); the values were checked by `validate_request`
            args.command_env = {name: value.replace("{report_path}", str(unique_report))
                                for name, value in (request["command"].get("env") or {}).items()}
            args.cwd = request["command"]["cwd"]
            args.reporter = request["command"]["reporter"]
            args.external_report_path = str(unique_report) if request["command"].get("report_path") else ""
            args.job_id, args.job_store, args.job = job["job_id"], store, job
            args.job = store.update(job, status="launching")
            refresh_dashboard()
            launch(args)
    if not args.task or not args.label:
        ap.error("--task and --label are required unless --request or --mine is used")
    _refuse_phantom_story(args.task)
    if args.wait:
        wait(args)  # reads a run that is already going; launches nothing and refuses nothing
    refuse_untyped_story_run(args.task, ap)
    with hold_stand(cfg, f"{args.label}-{os.getpid()}", "", args.stand_wait) as lease:
        args.stand_lease = lease
        launch(args)


def collect_only(args) -> int:
    """`--collect-only` (t-2181 PC-4, B6): one collect over the files of `--tests`, through `collect_files` (the ONE collect of S5,
    AR-15), and the `runs[]` row of it: `kind: collect`, `scope` the node ids collected, `partial: true` when some file failed to
    import (its healthy ids are listed, the broken files named). It launches no test, writes no run block, no job and no
    evidence summary: a collect proves that a written test is collectable, never that it passed - `check_witness` takes it as the
    evidence of a manifest whose every test is pending, and never as `run_witness`. Exit 0 with a row; 2 when nothing could be
    collected (a collect that listed no id is no evidence)."""
    files = sorted({str(t).partition("::")[0].replace("\\", "/") for t in args.tests})
    notes: list = []
    row = {"label": args.label or "collect", "kind": "collect", "files": files,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        ids = list(collect_files(args.cmd, args.cwd_override or str(project_root()), files, load_config(), notes))
    except Exception as exc:
        # A `node_ids.CollectError` of kind `partial` carries the healthy ids and the broken files (RH1-3); any other kind, and
        # any other failure, is a collect that gave nothing to stand on - never a pass (FR-59).
        if getattr(exc, "kind", "") != "partial" or not list(getattr(exc, "ids", []) or []):
            print(json.dumps({"status": "collect_failed", "error": str(getattr(exc, "message", "") or exc),
                              "hint": "fix what the collect names (an import error, a missing file), then run --collect-only again"},
                             ensure_ascii=False), file=sys.stderr)
            return 2
        ids = list(exc.ids)
        row["partial"] = True
        row["broken"] = [b.get("path", "") if isinstance(b, dict) else str(b) for b in exc.broken]
    if not ids:
        print(json.dumps({"status": "collect_failed", "error": "the collect listed no test id over " + ", ".join(files)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    row["scope"] = ids
    print(json.dumps({"status": "collected_partial" if row.get("partial") else "collected", "runs_row": row, "notes": notes,
                      "hint": "append the row with `manifest_put.py --task <TICKET> --fragment` as {\"runs\": [<runs_row>]}; "
                              "it is a collect, not a run: it never stands for run_witness"}, ensure_ascii=False))
    return 0


def launch(args) -> None:
    from telemetry_capture import Span
    telemetry_path = project_root() / "qa-factory/state/telemetry" / f"command-{os.getpid()}.jsonl"
    with Span(telemetry_path, span_kind="command", source="plugin:run_suite.py",
              task=args.task, reason_code="managed_test_run"):
        run(args)


def print_not_launched(action: str, job: dict, brief: bool = False, answer: dict | None = None) -> None:
    """A duplicate, reused or already-run job. `--request` keeps its full record (callers read
    it); `--mine` gets what a role needs: what happened to that run and where its summary is.
    `answer` is the budget's (`execution_request.budget_answer`): the covering jobs by id, which
    instance each one answers, and the words - `reused` and `already_run` both exit 0, so the
    role reads a status, not an error (D-0018)."""
    if not brief:
        print(json.dumps({**job, "job_status": job.get("status"), "status": action}, ensure_ascii=False))
        return
    shape = {"status": action, "job_id": job.get("job_id"), "job_status": job.get("status"),
             "execution_status": job.get("execution_status"), "summary": job.get("summary"),
             "idempotency_key": job.get("idempotency_key")}
    if answer:
        shape["jobs"] = [j.get("job_id") for j in answer.get("jobs") or []]
        shape["covered"] = answer.get("covered") or {}
        if answer.get("words"):
            shape["words"] = answer["words"]
    if (answer or {}).get("hint"):
        shape["hint"] = answer["hint"]
    elif action in {"reused", "already_run"}:
        # No budget words: the run budget is not enforced (no data file), and `--again` still
        # says "once more" - or the key of a finished run was asked again outside a `--mine`
        # answer, where a person's word is the door.
        from execution_request import load_run_budget
        enforced = load_run_budget()[0] is not None
        what = ("a green run of exactly these tests over their own unchanged bytes is already recorded"
                if action == "reused" else
                "this very run finished without passing and is recorded; it is not run again")
        shape["hint"] = what + " - read its summary; " + (
            "a person's word passes a repeat" if enforced else "`--again` runs it once more")
    else:
        shape["hint"] = ("this very run is recorded and not finished, or was begun by another process — "
                         "`--recover <idempotency_key> --task <task>` says which")
    print(json.dumps(shape, ensure_ascii=False))


def resolve_mine_detail(args) -> None:
    """`--mine CASE --detail TEST`: the last recorded run of these cases; builds nothing."""
    from execution_request import MineRefusal, find_active_dispatch
    from hooklib import artifact_root
    cases = {c.strip() for chunk in args.mine for c in str(chunk).split(",") if c.strip()}
    try:
        task = args.task or find_active_dispatch(artifact_root(), "", args.dispatch or "", cases)[0]
    except MineRefusal as exc:
        print(json.dumps({"status": "mine_refused", "error": str(exc),
                          "hint": "outside a dispatch name the story: --task TICKET --mine CASE --detail TEST"},
                         ensure_ascii=False))
        sys.exit(2)
    for job in reversed(JobStore(artifacts_dir(task) / "state" / "execution-jobs").jobs()):
        old = job["request"]
        named = set((old.get("built_by") or {}).get("cases") or []) | set(old.get("selected_instance_ids") or [])
        for contract in (old.get("instance_contracts") or {}).values():
            for link in (contract or {}).get("case_version_links") or []:
                if isinstance(link, dict):
                    named.add(str(link.get("case_id") or ""))
        if job.get("summary") and named & cases:
            args.task, args.label = task, f"{old.get('purpose')}-{job['job_id']}"
            return
    print(json.dumps({"status": "no_recorded_run", "task": task, "cases": sorted(cases),
                      "hint": "no finished run of these cases is recorded — run them first: --mine CASE"},
                     ensure_ascii=False))
    sys.exit(2)


if __name__ == "__main__":
    main()
