"""audit_factory.py — a good and a bad case for the rules the plugin model rewrote.

A1  liveness: a script is live when hooks.json names it, when a referenced hook imports it
    (one process per event is the design), or when it is a declared CLI tool.
A11 schema sync: the validator's required keys are judged against references/artifact-contract*.md,
    the contract document, not against the writer role's prose.
A13 deferred decisions: a DD row must carry the question it deferred — a row with an empty
    `asked` cell is a question the interview skipped, filed where it looks accounted for;
    and a required fact empty in config.json with no DD row was never asked at all.
A22 role start load: everything one role reads before its first useful action (charter, project CLAUDE.md,
    injection, packet, launch card, brief, form), summed by role_load.py in tokens — the injection measured on the
    generated role slices the map delivers, which A9 keeps fresh. The threshold is the owner's number and prints info
    while provisional; the per-role shrink-only ratchet is red; A25 and the two byte caps are gone.
A21 one owner per fact: test-strategy.md and framework-rules.md reach disjoint roles and
    must not restate each other — a shared section heading is one fact with two owners.
A17 detector re-run: with a project the exit code is the verdict; with no project the detector
    must refuse (exit 2 naming config.json) - INFO; a pass or any other refusal is a violation.
A20 portable paths: a declared path field holding an absolute path, or a home directory in
    a command or a generated document, fails — those files are committed and read elsewhere.
A14 definition drift: reads release_fingerprint.compare() only - `no` is the one "no violations";
    `yes` (files named, 10 at most) and `unknown` (its why) are INFO lines, never a pass.

Runnable on its own: `python scripts/tests/test_audit_rules.py`.
"""
import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, driver_sources, finish, temp_dir,
    temp_project, use_project,
)

B = chr(92)
BSLASH2 = B + B  # a UNC prefix, spelled so no escape survives a copy
NL = chr(10)
ROOT = temp_project("qa-factory-audit-")
use_project(ROOT)

import audit_factory as A  # noqa: E402  (imported AFTER the project root is set)
import validate_artifacts as V  # noqa: E402

SR = A.DRIVER_ENTRY  # the driver's file name in a baseline row (the literal itself stays in driver_root and test_a27_planted_copy, L8)


def fake_plugin(tmp: Path, scripts: dict, referenced: list) -> Path:
    """A synthetic plugin root: scripts/<name>.py with the given bodies, and a hooks.json
    whose PreToolUse entry runs each `referenced` script the way run-py.cmd does."""
    root = tmp / "plugin"
    (root / "scripts").mkdir(parents=True)
    (root / "hooks").mkdir(parents=True)
    for name, body in scripts.items():
        (root / "scripts" / name).write_text(body, encoding="utf-8")
    (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Write", "hooks": [
            {"type": "command", "command": '"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" ' + r}
            for r in referenced]}]}}), encoding="utf-8")
    return root


# --- A1 -------------------------------------------------------------------------------------

def test_a1() -> None:
    found = A.a1_findings(PLUGIN_ROOT)
    check(f"GOOD A1: the shipped plugin has no dead script ({len(found)} found)", not found,
          "\n".join(found))
    # The regression this rule was rewritten for: library modules of guard_pre_tool.py.
    check_not_in("GOOD A1: guard_secrets.py is live by import, not reported",
                 "guard_secrets", found or ["-"])
    check_not_in("GOOD A1: guard_app_under_test.py is live by import, not reported",
                 "guard_app_under_test", found or ["-"])

    tmp = temp_project("qa-factory-audit-a1-")
    try:
        root = fake_plugin(tmp, {
            "entry_hook.py": "import sys\nimport lib_mod\nimport deep_mod_user\n",
            "lib_mod.py": "X = 1\n",
            "deep_mod_user.py": "from deep_mod import Y\n",
            "deep_mod.py": "Y = 2\n",
            "dead_guard.py": "X = 1\n",
            "orphan.py": "X = 1\n",
        }, ["entry_hook.py"])
        saved = A.HOOK_SCRIPTS
        A.HOOK_SCRIPTS = ["entry_hook.py", "lib_mod.py", "dead_guard.py"]
        try:
            found = A.a1_findings(root)
        finally:
            A.HOOK_SCRIPTS = saved
        check_in("BAD  A1: an unreferenced hook-shaped script is still a dead hook",
                 "dead_guard.py", found)
        check_in("BAD  A1: the dead-hook wording names hooks.json", "dead hook", found)
        check_in("BAD  A1: a script nothing reaches is dead code", "orphan.py", found)
        check_not_in("BAD  A1: a module imported by a referenced hook is live", "lib_mod.py", found)
        check_not_in("BAD  A1: liveness is transitive (import of an import)", "deep_mod.py", found)
        check_not_in("BAD  A1: the referenced hook itself is live", "entry_hook.py", found)
    finally:
        cleanup(tmp)

    tmp = temp_project("qa-factory-audit-a1b-")
    try:
        root = fake_plugin(tmp, {"entry_hook.py": "X = 1\n"}, ["ghost_hook.py"])
        saved = A.HOOK_SCRIPTS
        A.HOOK_SCRIPTS = ["entry_hook.py"]
        try:
            found = A.a1_findings(root)
        finally:
            A.HOOK_SCRIPTS = saved
        check_in("BAD  A1: hooks.json naming a script that is not on disk", "ghost_hook.py", found)
    finally:
        cleanup(tmp)


# --- A11 ------------------------------------------------------------------------------------

def test_a11() -> None:
    found = A.a11_findings(PLUGIN_ROOT)
    check(f"GOOD A11: every required key is documented by the contract ({len(found)} found)",
          not found, "\n".join(found))

    sections = A._contract_sections(PLUGIN_ROOT)
    check("GOOD A11: the contract documents context-manifest.json",
          "context-manifest.json" in sections)
    check("GOOD A11: acceptance_criteria is documented (the scout collects AC)",
          "acceptance_criteria" in sections.get("context-manifest.json", ("", ""))[1])
    check("GOOD A11: env_preflight is documented (run_suite.py writes it)",
          "env_preflight" in sections.get("run-report.json", ("", ""))[1])
    for gone in ("classification.json", "baseline-report.json", "actual-complexity.json"):
        check(f"GOOD A11: {gone} is not a v0 schema any more", gone not in V.PHASE_JSON_KEYS)

    found = A.a11_findings(PLUGIN_ROOT,
                           schemas={"run-report.json": ["env_preflight", "totally_made_up_key"]},
                           writers={"run-report.json": "qa-runner.md"})
    check_in("BAD  A11: a required key the contract does not document", "totally_made_up_key", found)

    found = A.a11_findings(PLUGIN_ROOT,
                           schemas={"classification.json": ["task"]},
                           writers={"classification.json": "qa-requirements-tester.md"})
    check_in("BAD  A11: a schema for an artifact the contract does not have at all",
             "no artifact-contract*.md section documents this file", found)

    found = A.a11_findings(PLUGIN_ROOT, schemas={"triage.json": ["triage"]}, writers={})
    check_in("BAD  A11: a schema with no writer", "schema without an owner", found)

    found = A.a11_findings(PLUGIN_ROOT, schemas={"triage.json": ["triage"]},
                           writers={"triage.json": "qa-nobody.md"})
    check_in("BAD  A11: a writer role that does not exist", "not found in agents/", found)


# --- A14 ------------------------------------------------------------------------------------

def test_a14() -> None:
    """A14 reads `release_fingerprint.compare()` and nothing else (collect/2 CL2-1; AR-13): the verdict is patched per case, so
    what is asserted is how each of the three words and each `why` is SAID, never what the tree holds."""
    import contextlib
    import io
    import release_fingerprint as RF
    saved_compare, saved_read, saved_findings = RF.compare, RF._read_release, list(A.FINDINGS)

    def answer(**fields) -> dict:
        base = {"package_modified": "unknown", "why": "", "recipe": RF.RECIPE_ID, "release_version": "9.9.9",
                "running_version": "9.9.9", "changed": [], "added": [], "removed": [], "unreadable": [], "litter": [],
                "install": "cache"}
        return dict(base, **fields)

    def run(result=None) -> str:
        """The text A14 prints for a patched verdict (None: the real compare), and the findings it recorded."""
        RF.compare = saved_compare if result is None else (lambda root=None: result)
        A.FINDINGS.clear()
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                A.a14_definition_drift()
        finally:
            RF.compare = saved_compare
        return out.getvalue()

    def names(prefix: str, count: int) -> list:
        return [f"scripts/{prefix}{i:02d}.py" for i in range(1, count + 1)]

    try:
        # A14 never opens the release file itself: the survivor's reader raises if A14 reaches it.
        def forbidden(*args, **kwargs):
            raise AssertionError("A14 read the release file itself")
        RF._read_release = forbidden

        text = run(answer(package_modified="no", why="match"))
        check_in("GOOD A14: `no` is the one 'no violations'", "A14 definition drift: no violations", text)
        check_eq("GOOD A14: ...and records nothing", A.FINDINGS, [])

        for why in RF.WHY_TEXT:
            text = run(answer(why=why, install="frozen"))
            check_in(f"GOOD A14: unknown ({why}) says so, with the install kind", f"unknown ({why}, install frozen)", text)
            check_in(f"GOOD A14: unknown ({why}) carries the survivor's own words", RF.WHY_TEXT[why][0], text)
            check_not_in(f"BAD  A14: unknown ({why}) is never 'no violations'", "no violations", text)
            check_eq(f"GOOD A14: unknown ({why}) is INFO, not a finding", A.FINDINGS, [])
        text = run(answer(why="package_unreadable", unreadable=["scripts/a.py", "agents/b.md"]))
        check_in("GOOD A14: the unreadable files of an unknown are named", "unreadable: scripts/a.py, agents/b.md", text)
        check_not_in("GOOD A14: no unreadable files, no 'unreadable:' line",
                     "unreadable:", run(answer(why="no_release_file")))

        text = run(answer(package_modified="yes", why="differs", changed=["scripts/a.py"], removed=["agents/b.md"]))
        check_in("GOOD A14: `yes` says so with both versions' words", "package_modified: yes (release 9.9.9, install cache)", text)
        check_in("GOOD A14: ...and names the changed file", "changed: scripts/a.py", text)
        check_in("GOOD A14: ...and the removed one", "removed: agents/b.md", text)
        check_not_in("GOOD A14: ...and no line for an empty list", "added:", text)
        check_not_in("BAD  A14: `yes` is never 'no violations'", "no violations", text)
        check_eq("GOOD A14: `yes` is INFO (a person's own edit is not a factory fault), no finding", A.FINDINGS, [])

        for field in ("changed", "unreadable"):
            fields = dict(package_modified="yes", why="differs") if field == "changed" else dict(why="package_unreadable")
            ten, eleven = names("n", 10), names("n", 11)
            text = run(answer(**{**fields, field: ten}))
            check_in(f"GOOD A14: 10 names of `{field}` are all shown", ", ".join(ten), text)
            check_not_in("GOOD A14: ...with no '+k more'", "more)", text)
            text = run(answer(**{**fields, field: eleven}))
            check_in(f"GOOD A14: 11 names of `{field}`: the first 10 are shown", ", ".join(ten), text)
            check_in("GOOD A14: ...and the cut says how much it hid", "(+1 more)", text)
            check_not_in("GOOD A14: ...and the 11th is not shown", eleven[-1], text)

        RF._read_release = saved_read
        if not (Path(PLUGIN_ROOT) / RF.RELEASE_FILE_REL).exists():
            text = run()
            check_in("GOOD A14: the real tree, no release file: INFO unknown (no_release_file)",
                     "unknown (no_release_file, install frozen)", text)
            check_eq("GOOD A14: ...never a finding", A.FINDINGS, [])
        else:
            run()
            check_eq("GOOD A14: the real tree, with a release file, records no finding", A.FINDINGS, [])
    finally:
        RF.compare, RF._read_release = saved_compare, saved_read
        A.FINDINGS.clear()
        A.FINDINGS.extend(saved_findings)


# --- A17 ------------------------------------------------------------------------------------

def test_a17_detector_rerun() -> None:
    """A17 re-runs check_coverage.py. With a project the exit code is the verdict; with no project
    the detector must REFUSE (exit 2 naming config.json) - a pass there is a pass on an unknown
    (FR-59). The subprocess is stubbed: only the branching of A17 is under test."""
    import contextlib
    import io
    import subprocess
    from types import SimpleNamespace

    saved_run, saved_root, saved_findings = subprocess.run, A.project_root, list(A.FINDINGS)
    refusal = "check_coverage: the default root X is not a factory project: it has no qa-factory/config.json"

    def run_a17(root, code, out="", err=""):
        A.FINDINGS.clear()
        A.project_root = lambda: root
        subprocess.run = lambda *a, **k: SimpleNamespace(returncode=code, stdout=out, stderr=err)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            A.a17_detector_rerun()
        return list(A.FINDINGS), buf.getvalue()

    with_project = temp_project("qa-factory-audit-a17p-")
    no_project = temp_dir("qa-factory-audit-a17n-")
    try:
        found, out = run_a17(with_project, 0)
        check_eq("GOOD A17: project + exit 0 is clean", found, [])
        check_in("GOOD A17: project + exit 0 prints no violations", "no violations", out)

        found, _ = run_a17(with_project, 1, err="map is stale")
        check_in("BAD  A17: project + exit 1 is still a violation", "real exit 1", found)

        found, out = run_a17(no_project, 2, err=refusal)
        check_eq("GOOD A17: no project + the expected refusal is no violation", found, [])
        check_in("GOOD A17: the expected refusal is printed as INFO", "A17 detector re-run: INFO", out)
        check_in("GOOD A17: the INFO names the way out", "onboarded project", out)

        found, _ = run_a17(no_project, 0)
        check_in("BAD  A17: no project + exit 0 is a violation naming FR-59", "FR-59", found)

        found, _ = run_a17(no_project, 2, err="check_coverage: something else broke")
        check_in("BAD  A17: no project + exit 2 with another text is a violation", "real exit 2", found)

        found, _ = run_a17(no_project, 1, err=refusal)
        check_in("BAD  A17: no project + exit 1 is a violation", "real exit 1", found)

        found, _ = run_a17(None, 0)
        check_in("BAD  A17: no project root at all is 're-run failed', not a crash", "re-run failed", found)
    finally:
        subprocess.run, A.project_root = saved_run, saved_root
        A.FINDINGS.clear()
        A.FINDINGS.extend(saved_findings)
        cleanup(with_project)
        cleanup(no_project)


def test_a13_asked_column() -> None:
    """A deferral records a question that was asked. A DD row with no question on record is
    the onboarding defect (a skipped topic filed as a deferral), not a bookkeeping nit."""
    tmp = temp_project("qa-factory-audit-a13-")
    try:
        backlog = tmp / "qa-factory" / "state" / "factory-backlog.md"
        backlog.parent.mkdir(parents=True, exist_ok=True)

        head = ("# Findings about the factory itself\n\n"
                "## Findings about the factory\n\n"
                "| id | essence | scope | witness/details | created | status | decision |\n"
                "|---|---|---|---|---|---|---|\n"
                "| FB-1 | something | local-calibration | journal | 2026-09-01 | open | - |\n\n"
                "## Deferred decisions (onboarding/gates)\n\n")
        cols = ("| id | essence + where the marker is | asked | ripeness trigger | created | "
                "status | decision with witness |\n|---|---|---|---|---|---|---|\n")
        good = ("| DD-1 | App repo paths unknown, marker in `project-profile.md` | batch 1: "
                "where are the application repositories checked out locally? | a checkout "
                "appears | 2026-09-14 | open | - |\n")

        backlog.write_text(head + cols + good, encoding="utf-8")
        check_eq("GOOD A13: a row carrying its question is accepted",
                 A.deferred_rows_without_a_question(backlog), [])

        bad = ("| DD-2 | Stand address unknown, marker in `config.json` | - | a stand "
               "appears | 2026-09-14 | open | - |\n")
        backlog.write_text(head + cols + good + bad, encoding="utf-8")
        found = A.deferred_rows_without_a_question(backlog)
        check_eq("BAD  A13: exactly the row with no question is reported", len(found), 1)
        check_in("BAD  A13: the finding names the row", "DD-2", found)

        # The findings table above carries no `asked` column and must not be read as this one.
        backlog.write_text(head + cols, encoding="utf-8")
        check_eq("A13: a table with no DD rows is not a violation",
                 A.deferred_rows_without_a_question(backlog), [])

        stale = ("| id | essence + where the marker is | ripeness trigger | created | status | "
                 "decision with witness |\n|---|---|---|---|---|---|\n"
                 "| DD-1 | something deferred | a stand appears | 2026-09-14 | open | - |\n")
        backlog.write_text(head + stale, encoding="utf-8")
        found = A.deferred_rows_without_a_question(backlog)
        check_eq("BAD  A13: a backlog predating the `asked` column is reported once",
                 len(found), 1)
        check_in("BAD  A13: and it names the column to add", "asked", found)

        check_eq("A13: no backlog file at all is not this check's violation",
                 A.deferred_rows_without_a_question(tmp / "qa-factory" / "state" / "nope.md"), [])

        # The mirror: a required fact left empty with nothing on record that it was ever asked.
        backlog.write_text(head + cols, encoding="utf-8")
        profile = tmp / "qa-factory" / "strategy" / "project-profile.md"
        check_eq("A13: a config that was never onboarded is not judged by its answers",
                 A.required_facts_without_a_deferral({"adapters": {}}, backlog, profile), [])
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text("# Project profile" + chr(10), encoding="utf-8")
        answered = {"code_repos": [{"name": "app", "path": "../app"}],
                    "protected_app_paths": [],
                    "environments": [{"name": "local", "base_url": "http://localhost:8000"}],
                    "test_data": {"accounts_by_role": "unknown", "seeds": "factories",
                                  "pii_and_masking": "no real data", "cleanup_owner": "the suite",
                                  "shared_records": []},
                    "adapters": {"ticket": {"name": "jira"}}}
        check_eq("GOOD A13: every required fact answered is no violation",
                 A.required_facts_without_a_deferral(answered, backlog, profile), [])

        # `unknown` is an ANSWER: a project that was asked and had nothing to say is not
        # the same as a project nobody asked, and only the second is a finding.
        only_unknowns = dict(answered)
        only_unknowns["test_data"] = {k: "unknown" for k in
                                      ("accounts_by_role", "seeds", "generators",
                                       "pii_and_masking", "cleanup_owner")}
        check_eq("GOOD A13: test data answered 'unknown' everywhere is still answered",
                 A.required_facts_without_a_deferral(only_unknowns, backlog, profile), [])

        empty = {"code_repos": [], "protected_app_paths": [], "environments": [],
                 "environment": {}, "test_data": {"accounts_by_role": "", "seeds": "",
                                                  "shared_records": []},
                 "adapters": {"ticket": {"name": ""}}}
        found = A.required_facts_without_a_deferral(empty, backlog, profile)
        check_eq("BAD  A13: four required facts empty with no deferral are four violations",
                 len(found), 4)
        check_in("BAD  A13: the test-data topic is named", "topic 3", found)
        check_in("BAD  A13: the finding names the topic", "topic 1", found)

        deferred = ("| DD-1 | No local application checkout \u2014 marker in `project-profile.md` | "
                    "batch 1: where are the application repositories checked out? | a checkout "
                    "appears | 2026-09-14 | open | - |\n")
        backlog.write_text(head + cols + deferred, encoding="utf-8")
        found = A.required_facts_without_a_deferral(empty, backlog, profile)
        check_eq("GOOD A13: a fact that was asked and deferred is not reported", len(found), 3)
        check_not_in("GOOD A13: and it is the app-repo one that dropped out", "topic 1", found)
    finally:
        cleanup(tmp)


# The DD table as the template writes it, for the marker-pairing cases below.
DD_HEAD = "## Deferred decisions (onboarding/gates)" + NL + NL
DD_COLS = ("| id | essence + where the marker is | asked | ripeness trigger | created | status | "
           "decision with witness |" + NL + "|---|---|---|---|---|---|---|" + NL)


def dd_row(dd_id: str, essence: str, status: str = "open") -> str:
    return f"| {dd_id} | {essence} | batch 1: the question as put | a stand appears | 2026-09-14 | {status} | - |" + NL


def run_a13_markers(markers: list, backlog_text=None, backlog_as_dir: bool = False) -> list:
    """A13 over a throw-away project: every text of `markers` as a `[DEFERRED: ...]` marker in
    strategy/test-strategy.md (a `None` entry is written BARE, `[DEFERRED:]`), `backlog_text` as
    qa-factory/factory-backlog.md (None: no file; `backlog_as_dir`: a directory stands there,
    which cannot be read). Returns A13's findings."""
    import contextlib
    import io
    tmp = temp_dir("qa-factory-audit-a13m-")
    saved_root, saved_state, saved_findings = A.project_root, A.state_dir, list(A.FINDINGS)
    try:
        (tmp / "qa-factory" / "strategy").mkdir(parents=True)
        (tmp / "qa-factory" / "strategy" / "test-strategy.md").write_text(
            "# S" + NL + NL + "".join(("[DEFERRED:]" if m is None else f"[DEFERRED: {m}]") + NL for m in markers),
            encoding="utf-8")
        if backlog_as_dir:
            (tmp / "qa-factory" / "factory-backlog.md").mkdir()
        elif backlog_text is not None:
            (tmp / "qa-factory" / "factory-backlog.md").write_text(backlog_text, encoding="utf-8")
        A.project_root, A.state_dir = (lambda: tmp), (lambda: tmp / "qa-factory")
        A.FINDINGS.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            A.a13_deferred_decisions()
        return list(A.FINDINGS)
    finally:
        A.project_root, A.state_dir = saved_root, saved_state
        A.FINDINGS.clear()
        A.FINDINGS.extend(saved_findings)
        cleanup(tmp)


def test_a13_marker_pairing() -> None:
    """OH2-1: a marker is paired by the essence CELL of an OPEN row, never by the backlog's prose."""
    essence = "risk areas not named"
    row = dd_row("DD-1", f"{essence}: strategy/test-strategy.md (Risk and impact scale)")
    check_eq("GOOD A13 K1-1: a marker with an open row holding its essence is no violation",
             run_a13_markers([essence], DD_HEAD + DD_COLS + row), [])
    check_eq("GOOD A13 K1-1: the marker phrased MID-cell, in other case and spacing, still pairs",
             run_a13_markers(["Risk  AREAS" + chr(9) + "not named"],
                             DD_HEAD + DD_COLS + dd_row("DD-4", "Stand unknown; the Risk areas not named, marker in x")), [])
    spaced = dd_row("DD-5", "Stand unknown; the risk  areas" + chr(9) + "not   named, marker in x")
    check_eq("GOOD A13 K1-1: the CELL side is whitespace-collapsed too (a doubled space, a tab, a run of three)",
             run_a13_markers([essence], DD_HEAD + DD_COLS + spaced), [])
    check_eq("GOOD A13 K1-1: two open rows holding it pair it (row duplicates are A16's)",
             run_a13_markers([essence], DD_HEAD + DD_COLS + row + dd_row("DD-2", essence)), [])
    prose = ("Such a hole (risk areas not named) must stay visible." + NL + NL)
    found = run_a13_markers([essence], DD_HEAD + prose + DD_COLS)
    check("BAD  A13 K1-2: the template's prose holding the essence on one line pairs nothing",
          len(found) == 1 and "no DD row's essence cell holds it" in found[0], str(found))
    found = run_a13_markers([essence], DD_HEAD + DD_COLS + dd_row("DD-1", essence, "closed"))
    check("BAD  A13 K1-3: the matching row is closed: a violation naming DD-1 and 'closed'",
          len(found) == 1 and "DD-1 is closed" in found[0], str(found))
    base = "alpha-bravo-charlie-delta-echo-foxtrot-golf-hotel"
    check_eq("GOOD A13 K1-4: AT the cut - an essence of exactly 40 characters pairs",
             run_a13_markers([base[:40]], DD_HEAD + DD_COLS + dd_row("DD-1", base[:40])), [])
    check_eq("GOOD A13 K1-4: BEYOND the cut - 41 characters, the row holds the first 40: pairs",
             run_a13_markers([base[:41]], DD_HEAD + DD_COLS + dd_row("DD-1", base[:40])), [])
    found = run_a13_markers([base[:41]], DD_HEAD + DD_COLS + dd_row("DD-1", base[:39] + "#"))
    check("BAD  A13 K1-4: a row that differs at the 40th character does not pair", len(found) == 1, str(found))
    found = run_a13_markers(["  "], DD_HEAD + DD_COLS + row)
    check("BAD  A13 K1-5: a marker with no essence is a violation, not a skip",
          len(found) == 1 and "no essence" in found[0], str(found))
    found = run_a13_markers([None], DD_HEAD + DD_COLS + row)
    check("BAD  A13 K1-5: a BARE `[DEFERRED:]` is a violation too, named by its file, not invisible",
          len(found) == 1 and "no essence" in found[0] and "test-strategy.md" in found[0], str(found))
    found = run_a13_markers([essence, None], DD_HEAD + DD_COLS + row)
    check("BAD  A13 K1-5: a bare marker beside a paired one: exactly the bare one is reported",
          len(found) == 1 and "no essence" in found[0], str(found))
    no_status = ("| id | essence + where the marker is | asked | ripeness trigger | created | decision with witness |"
                 + NL + "|---|---|---|---|---|---|" + NL
                 + f"| DD-1 | {essence} | batch 1: q | a stand appears | 2026-09-14 | - |" + NL)
    found = run_a13_markers([essence], DD_HEAD + no_status)
    check("BAD  A13 K1-6: a table with no `status` column cannot say which row is open - named, not 'open'",
          len(found) == 1 and "`status` column" in found[0], str(found))
    found = run_a13_markers([essence], "## Deferred decisions" + NL + NL + DD_COLS + row)
    check("BAD  A13 K1-7: a legacy heading is named, with the template's heading as the expected one",
          len(found) == 1 and "## Deferred decisions (onboarding/gates)" in found[0] and "heading" in found[0], str(found))
    escaped = dd_row("DD-1", "Stand " + B + "| unknown: " + essence)
    check_eq("GOOD A13 K1-8: an escaped pipe in the cell does not shift the essence out of its column",
             run_a13_markers([essence], DD_HEAD + DD_COLS + escaped), [])


def test_a13_source_shape() -> None:
    """A-F2 / A-F5: A13's functions stay within 60 lines, and the module header describes the
    pairing the code does (by cell), not the retired one (by backlog text)."""
    import ast
    tree = ast.parse(Path(A.__file__).read_text(encoding="utf-8"))
    sizes = {n.name: n.end_lineno - n.lineno + 1 for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name.startswith("a13_")}
    long = {name: size for name, size in sizes.items() if size > 60}
    check("GOOD A13 A-F2: every a13_* function is at most 60 lines", len(sizes) >= 5 and not long, str((sizes, long)))
    header = A.__doc__ or ""
    check("GOOD A13 A-F5: the header names the cell the pairing reads", "`essence + where the marker is` cell" in header)
    check("BAD  A13 A-F5: and no longer says the pairing is by the backlog's text",
          "occur in the text of" not in header and "first ~40 chars" not in header)


def test_a13_marker_pairing_without_a_backlog() -> None:
    """K1-9/K1-10: no backlog, an unreadable one, and no marker at all."""
    found = run_a13_markers(["one hole", "another hole"])
    check("BAD  A13 K1-9: no backlog file: each marker is reported", len(found) == 2 and "does not" in found[0], str(found))
    check_eq("GOOD A13 K1-9: no marker and no backlog is no violation", run_a13_markers([]), [])
    found = run_a13_markers(["one hole"], backlog_as_dir=True)
    check("BAD  A13 K1-10: a backlog that cannot be read is reported with the marker, never passed",
          len(found) == 1 and "cannot be read" in found[0], str(found))
    check("BAD  A13 K1-10: and that line names its door: what to do and what to re-run (FR-1, FR-2)",
          "make the file readable and re-run the audit" in found[0], str(found))
    check("BAD  A13 K1-10: and with no marker it is one line of its own",
          len(run_a13_markers([], backlog_as_dir=True)) == 1)


# --- A20 ------------------------------------------------------------------------------------

def test_a20_portable_paths() -> None:
    portable = {
        "app_root": "..", "tests_root": ".", "journal_path": "qa-factory/records/journal.jsonl",
        "code_repos": [{"name": "ui", "path": "../testproject1-ui", "default_branch": "main"}],
        "protected_app_paths": ["testproject1/src", "testproject1-ui/src"],
        "environment": {"env_file": ".env.qa"},
        "environments": [{"name": "qa", "env_file": ".env.qa"}],
        "test_command_templates": {"quiet": "pytest -q", "one_test": "pytest <test-id>"},
        # A command may legitimately name a system path — the softer rule must not fire on it.
        "pre_commit_commands": ["docker run -v /var/run/docker.sock:/var/run/docker.sock lint"],
    }
    check_eq("GOOD A20: a config written in relative paths is clean",
             A.non_portable_config_paths(portable), [])

    # The field report (QAF-15): onboarding wrote the path the tester's terminal showed.
    field = dict(portable, app_root="/Users/Test_User_3/Projects")
    found = A.non_portable_config_paths(field)
    check_eq("BAD  A20: an absolute app_root is exactly one violation", len(found), 1)
    check_in("BAD  A20: the finding quotes the value", "/Users/Test_User_3/Projects", found)
    check_in("BAD  A20: and says what to write instead", "relative to the project root", found)

    every = dict(portable,
                 tests_root="C:" + B + "work" + B + "tests",
                 code_repos=[{"name": "ui", "path": "~/Projects/ui"}],
                 protected_app_paths=[BSLASH2 + "server" + BSLASH2 + "share" + BSLASH2 + "src"],
                 environments=[{"name": "qa", "env_file": "/home/qauser/.env"}],
                 test_command_templates={"quiet": "/Users/qauser/venv/bin/pytest -q"})
    found = A.non_portable_config_paths(every)
    check_eq("BAD  A20: every shape of machine-local path is caught (drive, ~, UNC, /home, cmd)",
             len(found), 5)

    # B-415 (D-0030, K12): the project's test locations are paths relative to app_root, so A20 reads them too
    check_eq("GOOD A20: a relative test location is clean",
             A.non_portable_config_paths(dict(portable, test_locations=["src/**/__tests__/", "src/legacy/checks"])), [])
    for label, entries in (("a drive path", ["C:/x/tests/"]), ("a home path", ["/home/a/tests/"])):
        found = A.non_portable_config_paths(dict(portable, test_locations=entries))
        check_eq(f"BAD  A20: {label} in test_locations is exactly one violation", len(found), 1)
        check_in(f"BAD  A20: {label}: the finding names the field", "test_locations[0]", found)
    check_eq("A20: a test_locations that is not a list does not crash the rule (the guard warns about it)",
             A.non_portable_config_paths(dict(portable, test_locations="src/tests/")), [])

    # t-238 W5: `execution.runtime_probes` is scanned too, element by element. The writer's own
    # output (the portable head, a relative checkout, the container's /app) must be clean, or the
    # rule would flag every entry the factory writes.
    head = ["{python}", "{plugin_root}/scripts/runtime_probe.py"]
    tail = ["--profile", "api", "--environment", "localhost", "--container", "api-c",
            "--checkout", "../../testproject1", "--app-root", "/app"]

    def probes_of(argv, cwd=".", profile="api"):
        entry = {"argv": argv, "timeout_s": 120}
        if cwd is not None:
            entry["cwd"] = cwd
        return dict(portable, execution={"runtime_probes": {profile: entry}})
    check_eq("GOOD A20: the entry the writer produces is clean (/app is a container path)",
             A.non_portable_config_paths(probes_of(head + tail)), [])
    check_eq("GOOD A20: `cwd` absent is clean too", A.non_portable_config_paths(probes_of(head + tail, cwd=None)), [])
    check_eq("GOOD A20: --app-root=<path> is a container path as well",
             A.non_portable_config_paths(probes_of(head + tail[:-2] + ["--app-root=/srv/app"])), [])
    legacy = [r"C:" + B + "Python312" + B + "python.exe",
              r"C:" + B + "Temp" + B + "pkg" + B + "scripts" + B + "runtime_probe.py"] + tail
    found = A.non_portable_config_paths(probes_of(legacy))
    check_eq("BAD  A20: an old entry with this machine's python and plugin path is ONE violation", len(found), 1)
    check_in("BAD  A20: it names the profile and the first element", "execution.runtime_probes.api: argv[0]", found)
    check_in("BAD  A20: and the second", "argv[1]", found)
    check_in("BAD  A20: and the fix is the factory's own writer, with --force",
             "runtime_probe.py --suggest --write --force --profile api", found)
    check_not_in("BAD  A20: the container path of the same argv is NOT named", "argv[11]", found)
    one = A.non_portable_config_paths(probes_of(head + tail[:7] + ["C:" + B + "work" + B + "testproject1"] + tail[8:]))
    check_eq("BAD  A20: ONE machine-local element in an otherwise portable list flags the entry", len(one), 1)
    check_in("BAD  A20: and that element is the one named", "argv[9]", one)
    check_not_in("BAD  A20: and no other", "argv[0]", one)
    script = A.non_portable_config_paths(probes_of(["python", "/opt/tools/probe.py", "--profile", "api"], profile="*"))
    check_eq("BAD  A20: a project script given by absolute path is flagged too (and left as written)", len(script), 1)
    check_in("BAD  A20: with the project's own fix, not the factory writer's", "relative to the project root", script)
    check_not_in("BAD  A20: not the writer's --force", "--force", script)
    check_in("BAD  A20: an absolute cwd is named", "cwd = \"/srv/app\"",
             A.non_portable_config_paths(probes_of(head + tail, cwd="/srv/app")))
    check_in("BAD  A20: an option value that is a path is judged by its path", "argv[8]",
             A.non_portable_config_paths(probes_of(head + tail[:6] + ["--checkout=/home/x/testproject1"] + tail[8:])))
    for odd in ({"execution": {"runtime_probes": None}}, {"execution": {"runtime_probes": []}},
                {"execution": "x"}, {"execution": {"runtime_probes": {"api": "x", "ui": {"argv": "python"}}}}):
        check_eq(f"A20: a runtime_probes of another shape is no crash and no violation ({odd})",
                 A.non_portable_config_paths(dict(portable, **odd)), [])

    tmp = temp_project("qa-factory-audit-a20-")
    try:
        strategy = tmp / "qa-factory" / "strategy"
        strategy.mkdir(parents=True)
        clean = strategy / "project-profile.md"
        clean.write_text("Application repositories: `../testproject1`, `../testproject1-ui`." + chr(10),
                         encoding="utf-8")
        check_eq("GOOD A20: a profile naming relative paths is clean",
                 A.personal_paths_in_docs([clean]), [])

        dirty = strategy / "aspect-profile.md"
        dirty.write_text("# Aspects" + chr(10)
                         + "The UI checkout resolves to /Users/Test_User_3/Projects/ui."
                         + chr(10), encoding="utf-8")
        found = A.personal_paths_in_docs([dirty])
        check_eq("BAD  A20: a home path pasted into a generated document is a violation",
                 len(found), 1)
        check_in("BAD  A20: the document finding carries the line number", "aspect-profile.md:2",
                 found)
        check_eq("A20: a document that does not exist is not a violation",
                 A.personal_paths_in_docs([strategy / "nope.md"]), [])
    finally:
        cleanup(tmp)


# --- A21 ------------------------------------------------------------------------------------

def test_a21_one_owner_per_fact() -> None:
    tmp = temp_project("qa-factory-audit-a21-")
    try:
        strategy = tmp / "qa-factory" / "strategy"
        strategy.mkdir(parents=True)
        plan = strategy / "test-strategy.md"
        code = strategy / "framework-rules.md"

        # The split by verb: what a plan is decided with vs what code is written against.
        plan.write_text(NL.join(["# Test strategy", "## Scope", "x", "## Test layers", "x",
                                 "## Case ids", "x", "## Definition of done", "x"]) + NL,
                        encoding="utf-8")
        code.write_text(NL.join(["# Framework rules", "## Layers and idioms", "x",
                                 "## Case ids in code", "x", "## Run commands", "x",
                                 "## Traps", "x"]) + NL, encoding="utf-8")
        check_eq("GOOD A21: two documents split by verb share no section",
                 A.duplicated_sections(plan, code), [])

        check_eq("A21: a file that does not exist yet is not this rule's violation",
                 A.duplicated_sections(plan, strategy / "nope.md"), [])

        # The pilot's shape: the same four sections in both, with the parenthetical that used
        # to make them look like different headings.
        plan.write_text(NL.join([
            "# Test strategy", "## Scope", "x", "## Run commands", "x",
            "## Team conventions (declared by humans)", "x",
            "## Confirmed conventions (inferred from the code, confirmed by the team)", "x",
            "## Case-id convention", "x"]) + NL, encoding="utf-8")
        code.write_text(NL.join([
            "# Framework rules", "## Layers and idioms", "x", "## Case-id convention", "x",
            "## Run commands", "x", "## Team conventions (declared by humans)", "x",
            "## Confirmed conventions", "x", "## Traps", "x"]) + NL, encoding="utf-8")
        found = A.duplicated_sections(plan, code)
        check_eq("BAD  A21: the pilot's four shared sections are four violations",
                 len(found), 4)
        check_in("BAD  A21: a heading differing only by its parenthetical still counts",
                 "Confirmed conventions", found)
        check_in("BAD  A21: and the finding says where to fix the generator",
                 "p4-generate.md", found)
    finally:
        cleanup(tmp)


# --- A22 ------------------------------------------------------------------------------------

def test_a22_injection_weight() -> None:
    """What a role pays before it acts (A22 role start load, RC1-14). The shipped map must be under every bound, and the
    rule must actually fire - a bound nothing can trip is a comment."""
    import role_load as RL
    names = RL.role_names()
    common = RL.common_list_bytes()
    check("A22: the shipped map has a start load for every role", len(names) >= 12, str(sorted(names)))
    loads = {r: RL.static_load(r) for r in names}
    cfg = RL.settings()
    check("A22: every role has a shrink-only ratchet row, and is within it",
          all(r in cfg["ratchet_tokens"] and loads[r]["tokens"] <= cfg["ratchet_tokens"][r] for r in names),
          "; ".join(f"{r}: {loads[r]['tokens']:,} vs {cfg['ratchet_tokens'].get(r)}" for r in names))
    # A shrink-only ratchet is tight or it holds nothing: a row more than `ratchet_slack_tokens` (ONE key of
    # role-load.json) above the measure is a raise nobody named - a row to lower.
    slack = cfg["ratchet_slack_tokens"]
    measured = {r: loads[r]["tokens"] for r in names}
    loose = RL.ratchet_excess(measured, cfg["ratchet_tokens"], slack)
    check(f"A22-K8: no ratchet row sits more than {slack:,} tokens above the measured start load (lower it)",
          not loose, str(loose))
    # K8 AT / BEYOND on the same function: a row at measured + slack passes, one token more is an unnamed raise.
    base = {"qa-a": 10000}
    check_eq("A22-K8 AT: a row at measured + slack is no excess", RL.ratchet_excess(base, {"qa-a": 10000 + slack}, slack), {})
    check_eq("A22-K8 BEYOND: a row at measured + slack + 1 is the unnamed raise, naming how far",
             RL.ratchet_excess(base, {"qa-a": 10000 + slack + 1}, slack), {"qa-a": slack + 1})
    check_eq("A22-K8: a role with no row is named (None), not passed", RL.ratchet_excess(base, {}, slack), {"qa-a": None})
    check(f"A22: the common list is under its cap ({common:,} <= {A.INJECT_COMMON_CAP_BYTES:,})",
          common is not None and common <= A.INJECT_COMMON_CAP_BYTES)
    check("A22: every role carries the common layer",
          all(next(l["bytes"] for l in loads[r]["layers"] if l["name"] == "injection_common") == common for r in names), str(common))
    # A-K1 (SC1-9): the rules are each role's own slice, so `common` is the manifesto alone; both caps are
    # RATCHETS pinned by equality to the measured value rounded up to 250 - a raise is a decision that edits this
    # literal and is named in the verdict (AR-20), not a quiet edit of the constant.
    import contract_slices as CS
    import json as _j
    imap = _j.loads((A.PLUGIN_ROOT / "references" / "inject-map.json").read_text(encoding="utf-8"))
    check_eq("A-K1: `common` does not hold common-rules.md (it is each role's slice)",
             [e for e in imap["common"] if "common-rules" in e], [])
    check_eq("A-K1: COMMON_LAYER_CAP_BYTES is pinned (measured 10,734 B, rounded up to 250)", A.COMMON_LAYER_CAP_BYTES, 10750)
    check_eq("A-K1: INJECT_COMMON_CAP_BYTES is pinned (measured 5,925 B with the X7-0 craft section)", A.INJECT_COMMON_CAP_BYTES, 5925)
    check("A-K1: both caps are under the old 18,000", A.COMMON_LAYER_CAP_BYTES <= 18000 and A.INJECT_COMMON_CAP_BYTES <= 18000)
    layer = CS.common_layer(A.PLUGIN_ROOT)
    check_eq("A-K1: the shipped layer is measured whole", layer["errors"], [])
    check(f"A-K1: the layer every role is handed alike is under its cap ({layer['shared']:,} <= {A.COMMON_LAYER_CAP_BYTES:,})",
          layer["shared"] <= A.COMMON_LAYER_CAP_BYTES)
    check_eq("A-K1: the shipped tree is A22-clean", A._a22_findings(A.PLUGIN_ROOT, require_settings=True)[0], [])
    # The automator was the tightest role (1,006 B under the old 42,000 B cap before SC1-9); the owner's decision (R-F1 a)
    # took a rule off its layer to give it the room, and its rule stays off.
    automator = (A.PLUGIN_ROOT / "references" / "slices" / "qa-automator" / "common-rules.md").read_text(encoding="utf-8")
    check_not_in("A-K1: the automator is not handed `No writes to external systems` (the guard's refusal carries it whole)",
                 "No writes to external systems", automator)
    # The split by reader is what keeps it there: no role is handed the whole JSON contract.
    import json as _json
    data = _json.loads((A.PLUGIN_ROOT / "references" / "inject-map.json").read_text(encoding="utf-8"))
    whole = [r for r, items in data["roles"].items()
             if any(str(i).endswith("artifact-contract-json.md") for i in items)]
    check_eq("A22: no role is injected the whole JSON contract any more", whole, [])
    # Since 0.7.7 the map delivers generated role slices, and A22 must weigh the file that is
    # actually delivered — weighing the source would hide every saving and every regression.
    from content_size import content_bytes
    scout_slice = A.PLUGIN_ROOT / "references" / "slices" / "qa-scout" / "common-rules.md"
    source = A.PLUGIN_ROOT / "references" / "common-rules.md"
    check("A22: a role slice weighs less than the subject it is cut from",
          scout_slice.exists() and content_bytes(scout_slice) < content_bytes(source),
          f"{scout_slice.name}: {content_bytes(scout_slice) if scout_slice.exists() else 'missing'}")
    # A bound nothing can trip is a comment; a threshold with no headroom is a tax on every later edit.
    tight = sorted(loads.values(), key=lambda ld: ld["tokens"])[-1]
    check(f"A22: the heaviest role keeps real headroom under the threshold ({tight['threshold_tokens'] - tight['tokens']:,} tokens free)",
          tight["threshold_tokens"] - tight["tokens"] >= 2000, f"{tight['role']}: {tight['tokens']:,}")
    _a22_controls()
    _a22_start_load_controls()


def _a22_controls() -> None:
    """BAD control and the cap's AT / BEYOND, on synthetic trees (A-K1, A-K9)."""
    import contract_slices as CS
    source = ("# Rules\n\nLead.\n\n<!-- roles: all -->\n## All\n\nshared line.\n\n"
              "<!-- roles: qa-a -->\n## Only A\n\nA only body here.\n\n<!-- roles: qa-b -->\n## Only B\n\nB only.\n")
    tmp = temp_dir("qa-factory-a22-layer-")
    try:
        def tree(name: str, common: list, roles: dict) -> Path:
            root = tmp / name
            (root / "references").mkdir(parents=True)
            (root / "references" / "m.md").write_text("m" * 99 + NL, encoding="utf-8", newline=NL)
            (root / "references" / "common-rules.md").write_text(source, encoding="utf-8", newline=NL)
            (root / "references" / "inject-map.json").write_text(
                json.dumps({"common": common, "roles": roles}), encoding="utf-8", newline=NL)
            return root

        # AT and BEYOND the shared cap: the tree's shared layer is 137 B (the same known answer as test_contract_slices A-K9).
        slices = {r: [f"plugin:references/slices/{r}/common-rules.md"] for r in ("qa-a", "qa-b")}
        root = tree("good", ["plugin:references/m.md"], slices)
        CS.write(root)
        check_eq("A-K9: the tree's shared layer is the known 137 B", CS.common_layer(root)["shared"], 137)
        check_eq("A-K9 AT: a cap equal to the shared layer is no error", A._a22_findings(root, 100, 137)[0], [])
        beyond = A._a22_findings(root, 100, 136)[0]
        check("A-K9 BEYOND: one byte over the cap is an A22 error naming the fix and the raise rule",
              len(beyond) == 1 and "contract_slices.py --write" in beyond[0] and "raise of the cap" in beyond[0], str(beyond))
        check_eq("A-K9 AT: a list cap equal to the list is no error", A._a22_findings(root, 100, 137)[0], [])
        check("A-K9 BEYOND: a list one byte over its cap is an error",
              any("common injection is 100 bytes (cap 99" in e for e in A._a22_findings(root, 99, 137)[0]))
        # BAD: common-rules.md back in `common` (the whole file, to every role) is an A22 error that names the way out.
        back = tree("back", ["plugin:references/m.md", "plugin:references/common-rules.md"], {"qa-a": []})
        real = (A.PLUGIN_ROOT / "references" / "common-rules.md").read_text(encoding="utf-8")
        (back / "references" / "common-rules.md").write_text(real, encoding="utf-8", newline=NL)
        bad = A._a22_findings(back)[0]
        check("BAD A22: the whole rules file in `common` is an error naming contract_slices.py --write",
              any("contract_slices.py --write" in e and "common injection" in e for e in bad), str(bad))
        # AR-28: a layer that cannot be measured is an error, not a pass.
        (root / "references" / "common-rules.md").unlink()
        gone = A._a22_findings(root, 100, 137)[0]
        check("A22: an unreadable source is 'not measured', an error", any("not measured" in e for e in gone), str(gone))
    finally:
        cleanup(tmp)


# --- A9 -------------------------------------------------------------------------------------

def test_a9_slice_freshness() -> None:
    """A9 now also answers for the generated slices: the map may name only slices that exist
    and match their source today, because nothing renders one at runtime."""
    import contract_slices
    check_eq("A9: the shipped slices are present and fresh",
             contract_slices.findings(A.PLUGIN_ROOT), [])
    tmp = temp_dir("qa-factory-a9-slices-")
    try:
        root = tmp / "plugin"
        (root / "references").mkdir(parents=True)
        (root / "references" / "subject.md").write_text(
            "# S\n\nlead\n\n## One <!-- roles: qa-runner -->\n\nbody\n", encoding="utf-8")
        (root / "references" / "inject-map.json").write_text(json.dumps({"common": [], "roles": {
            "qa-runner": ["plugin:references/slices/qa-runner/subject.md"]}}), encoding="utf-8")
        check_in("BAD A9: a slice the map names but nothing generated is a violation",
                 "missing", contract_slices.findings(root))
    finally:
        cleanup(tmp)

# --- A22: the per-role start load (the former A25 weight is a layer sum of the same measure) ----

def test_a25_removed() -> None:
    """A22-K4: the dispatch budget A25 and its byte caps are gone, and the shipped tree prints no A25 line (RC1-14)."""
    import contextlib
    import io
    import role_load as RL
    check("A22-K4: A25 is not a factory-owned check any more", "A25" not in A.FACTORY_OWNED)
    check("A22-K4: the byte-sum producers are gone (their readers sit on role_load)",
          not any(hasattr(A, n) for n in ("a25_dispatch_budget", "_dispatch_weight", "_inject_weight",
                                           "INJECT_CAP_BYTES", "DISPATCH_CAP_BYTES")))
    buffer = io.StringIO()
    before = len(A.FINDINGS)
    with contextlib.redirect_stdout(buffer):
        A.a22_role_start_load()
    out = buffer.getvalue()
    check("A22-K4: the shipped tree has no A25 report line at all", "A25" not in out, out[:300])
    check("A22-K4: A22 names itself the role start load, with the heaviest roles and what is estimated",
          "A22 role start load: no violations" in out and "heaviest roles" in out and "estimated:" in out, out[:600])
    check("A22-K4: the shipped tree adds no finding", len(A.FINDINGS) == before)
    check("A22-K4: the three heaviest roles are named with tokens free",
          len(re.findall(r"~[\d,]+ tokens \([\d,-]+ free\)", out)) == 3, out[:600])
    check("A22: the module that sums is the one the retro reads (AR-13)",
          RL.static_load("qa-scout")["total_bytes"] > 0)


def _a22_start_load_controls() -> None:
    """A22-K1..K3, K6, K7 on synthetic trees: the provisional threshold is info, the confirmed one is red, AT and BEYOND it,
    an unreadable settings file is an error, an absent one in a synthetic tree is an info line, the ratchet is red always."""
    import contract_slices as CS
    import role_load as RL
    source = ("# Rules\n\nLead.\n\n<!-- roles: all -->\n## All\n\nshared line.\n")
    tmp = temp_dir("qa-factory-a22-load-")
    try:
        def tree(name: str, charters: dict, settings: dict | None) -> Path:
            root = tmp / name
            (root / "references").mkdir(parents=True)
            (root / "agents").mkdir()
            (root / "references" / "m.md").write_text("m" * 99 + NL, encoding="utf-8", newline=NL)
            (root / "references" / "common-rules.md").write_text(source, encoding="utf-8", newline=NL)
            for role, size in charters.items():
                (root / "agents" / f"{role}.md").write_text("c" * size, encoding="utf-8", newline=NL)
            (root / "references" / "inject-map.json").write_text(json.dumps({
                "common": ["plugin:references/m.md"],
                "roles": {r: [f"plugin:references/slices/{r}/common-rules.md"] for r in charters}}), encoding="utf-8", newline=NL)
            CS.write(root)
            if settings is not None:
                (root / "references" / "role-load.json").write_text(json.dumps(settings), encoding="utf-8", newline=NL)
            return root

        def settings(threshold: int, ratchets: dict, confirmed=None) -> dict:
            return {"note": "t", "threshold_tokens": threshold, "threshold_confirmed_by": confirmed, "bytes_per_token": 4,
                    "host_base_tokens": None, "allowances": {"packet": 5400, "launch": 2000},
                    "control_tolerance_percent": 15, "ratchet_tokens": ratchets, "ratchet_slack_tokens": 1000}

        root = tree("t", {"qa-a": 20000, "qa-b": 10}, settings(10 ** 6, {}))
        tok = {r: RL.static_load(r, plugin_root=root)["tokens"] for r in ("qa-a", "qa-b")}
        wide = {r: t + 100 for r, t in tok.items()}
        write = lambda s: (root / "references" / "role-load.json").write_text(json.dumps(s), encoding="utf-8", newline=NL)

        # K1: provisional - one token over the threshold is an info line and NO error.
        write(settings(tok["qa-a"] - 1, wide))
        errors, info = A._a22_findings(root)
        check_eq("A22-K1: a role over a PROVISIONAL threshold is not an error", errors, [])
        check("A22-K1: ... it is an info line naming the role, the kind and the threshold",
              any(i.startswith("A22 (info, threshold provisional): qa-a (first) starts with ~") and "(threshold " in i for i in info), str(info))
        check("A22-K1: ... and the lighter role prints nothing of the kind", not any("qa-b (first) starts" in i for i in info), str(info))
        # K2: confirmed - the same role is an error naming the heaviest layer and the file the owner edits.
        write(settings(tok["qa-a"] - 1, wide, "owner, 02.11.2026"))
        errors, _info = A._a22_findings(root)
        check("A22-K2: a CONFIRMED threshold turns the same role red, naming the heaviest layer and role-load.json",
              len(errors) == 1 and "qa-a (first) starts with" in errors[0] and "charter 20,000 B is the heaviest" in errors[0]
              and "role-load.json" in errors[0] and "contract_slices.py --write" in errors[0], str(errors))
        # K3: AT the threshold - no line; one token BEYOND - a line.
        write(settings(tok["qa-a"], wide, "owner, 02.11.2026"))
        errors, info = A._a22_findings(root)
        check_eq("A22-K3 AT: a role exactly at the threshold gives no error", errors, [])
        check("A22-K3 AT: ... and no 'starts with' line", not any("starts with" in i for i in info), str(info))
        # K6: E6 - an unreadable settings file is an error; an absent one is one info line in a synthetic tree (B-4).
        (root / "references" / "role-load.json").write_text("{not json", encoding="utf-8")
        errors, _info = A._a22_findings(root)
        check("A22-K6: an unreadable role-load.json is an error saying the check did not run",
              any("role-load.json could not be read" in e and "did not run" in e for e in errors), str(errors))
        absent = tree("absent", {"qa-a": 10}, None)
        errors, info = A._a22_findings(absent, 100, 137)
        check_eq("A22-K6: a synthetic tree with no role-load.json is not an error (A-K9 stays green)", errors, [])
        check("A22-K6: ... it says 'role-load.json absent: static layers only'", any("role-load.json absent: static layers only" in i for i in info), str(info))
        errors, _info = A._a22_findings(absent, 100, 137, require_settings=True)
        check("A22-K6: ... but the tree that MUST have the file (the shipped one) is told it is missing",
              any("role-load.json could not be read" in e for e in errors), str(errors))
        # K7: the ratchet is red whatever the threshold says; a role with no row is told so.
        write(settings(10 ** 6, {"qa-a": tok["qa-a"] - 1, "qa-b": tok["qa-b"]}))
        errors, _info = A._a22_findings(root)
        check("A22-K7: a role over its shrink-only ratchet is an error with a PROVISIONAL threshold",
              len(errors) == 1 and "qa-a (first) starts with" in errors[0] and "shrink-only ratchet" in errors[0], str(errors))
        write(settings(10 ** 6, {"qa-a": tok["qa-a"]}))
        errors, _info = A._a22_findings(root)
        check("A22-K7: AT its ratchet there is no error, and a role with no ratchet row is one",
              len(errors) == 1 and "qa-b has no row in `ratchet_tokens`" in errors[0], str(errors))
    finally:
        cleanup(tmp)


def test_a2_write_right_is_a_field() -> None:
    """A2 and A2b ask "does this role write files" of a field, not of the contract's wording.

    Both used to run a verb list over the prose (`write the file|append to|save to file|…`), so a
    contract phrased around another verb lost the check that it was granted `Write` — FR-12, in
    the audit that exists to catch classes like that. The two fields that already say it: the
    artifact registry ("one artifact, one writer") and the role's own `## Outputs` section.
    """
    agents = A.PLUGIN_ROOT / "agents"
    scout = agents / "qa-scout.md"
    why = A.role_writes(scout, scout.read_text(encoding="utf-8"))
    check_in("A2: the registry is what says the scout writes", "artifact-writers.json", why)
    critic = agents / "qa-case-critic.md"
    why = A.role_writes(critic, critic.read_text(encoding="utf-8"))
    # t-078: the registry now names both critics' findings files (the guard reads them from it),
    # so the critic is a registry role; the `## Outputs` branch is exercised on a nameless role below.
    check_in("A2: the registry names the case critic as the writer of its findings",
             "work/test-cases/critic-findings.md", why)
    # the message lists the first three keys in sort order: the S5 critic holds four since TR3-15 (its notes row), the old single file sorts last
    check_in("and the S5 critic likewise", "work/test-code/critic-findings-*.md",
             A.role_writes(agents / "qa-code-critic.md",
                           (agents / "qa-code-critic.md").read_text(encoding="utf-8")))

    # The mutation: prose that used to decide, and a section that names no file.
    prose_only = ("---" + NL + "tools: Read, Write" + NL + "---" + NL
                  + "## Procedure" + NL + "Write the file when you are done, and append a line."
                  + NL + "## Outputs" + NL + "Update your review fields through `manifest_put.py`."
                  + NL)
    check_eq("A2: a write verb in the prose no longer makes a role a writer",
             A.role_writes(Path("agents/qa-nobody.md"), prose_only), "")
    with_path = prose_only.replace("through `manifest_put.py`.",
                                   "in `qa-factory/artifacts/<TICKET>/work/notes.md`.")
    check_in("A2: a path in Outputs does", "work/notes.md",
             A.role_writes(Path("agents/qa-nobody.md"), with_path))


# --- A27: a state without a move outside the seam (conductor/1 C1-8) -----------------------------------------------------------------------
# A synthetic driver is a FAKE scripts/ file written by `driver_root` (the one writer of its name, so L8 counts it once). Each case is a
# method body; `run` swaps the baseline for the case's own rows and puts the module constants back.

A27_HEAD = NL.join([
    "class Refusal(Exception):", "    pass", "", "class Person(Exception):", "    def __init__(self, kind, text, *a, **k):", "        pass", "",
    "class Stop(Exception):", "    def __init__(self, code, reason):", "        pass", "",
    "class InfraStop(Stop):", "    def __init__(self, kind, message):", "        pass", "", ""])


def driver_root(tmp: Path, body: str, others: dict | None = None, raw: bytes | None = None) -> Path:
    root = fake_plugin(tmp, dict(others or {}), [])
    text = A27_HEAD + "class Driver:" + NL + NL.join(("    " + ln) if ln else ln for ln in body.split(NL))
    (root / "scripts" / "story_run.py").write_bytes(text.encode("utf-8") if raw is None else raw)
    return root


def run(body: str, others: dict | None = None, rows: dict | None = None, raw: bytes | None = None, cap: int | None = None):
    """(scan, census) of a synthetic driver whose baseline is exactly `rows` (default: empty) and whose cap is the sum (or `cap`)."""
    tmp = temp_dir("qa-factory-a27-")
    saved = (A.NO_MOVE_BASELINE, A.NO_MOVE_BASELINE_MAX)
    A.NO_MOVE_BASELINE = dict(rows or {})
    A.NO_MOVE_BASELINE_MAX = sum(A.NO_MOVE_BASELINE.values()) if cap is None else cap
    try:
        root = driver_root(tmp, body, others, raw)
        scan = A.a27_scan(root)
        return scan, A.a27_census(root, scan)
    finally:
        A.NO_MOVE_BASELINE, A.NO_MOVE_BASELINE_MAX = saved
        cleanup(tmp)


def m(*lines: str) -> str:
    return NL.join(["def m(self):", *("    " + x for x in lines)]) + NL


def news(scan) -> list:
    return [(s.qual, s.disc) for s in scan.sites if s.verdict == "NEW"]


def view(scan) -> list:
    return [(s.qual, s.cls, s.disc, s.verdict) for s in scan.sites]


def everything(scan) -> str:
    return " | ".join(scan.problems + scan.news)


def good(label: str, body: str, **kw) -> None:
    scan, _ = run(body, **kw)
    check(f"GOOD A27: {label}", not scan.news and not scan.problems, everything(scan))


def bad(label: str, body: str, expect: list, **kw) -> None:
    scan, _ = run(body, **kw)
    check_eq(f"BAD  A27: {label}", news(scan), expect)


def prob(label: str, body: str, needle: str, **kw) -> None:
    scan, _ = run(body, **kw)
    check_in(f"BAD  A27: {label}", needle, everything(scan))


TOTALS_LINE = re.compile(r"^A27 totals: P-built \d+ S-built \d+ seam \d+ builder-built \d+ builder-calls \d+ U \d+ delegated \d+ "
                         r"py-wrappers \d+ doors \d+ counted \d+ baseline \d+ new \d+ stale \d+$")


def test_a27_live() -> None:
    scan = A.a27_scan(PLUGIN_ROOT)
    found = A.a27_findings(PLUGIN_ROOT, scan)
    check(f"GOOD A27: the shipped driver has no site outside the baseline ({len(found)} findings)", not found, "\n".join(found[:5]))
    counted = sum(1 for s in scan.sites if s.verdict in ("baseline", "NEW", "counted"))
    check_eq("GOOD A27: the census counts exactly the baseline rows' sum", counted, sum(A.NO_MOVE_BASELINE.values()))
    check_eq("GOOD A27: the cap equals the sum of the rows", A.NO_MOVE_BASELINE_MAX, sum(A.NO_MOVE_BASELINE.values()))
    seam = {(s.qual, s.cls) for s in scan.sites if s.verdict == "seam"}
    check("GOOD A27: [seam] positive control - Driver._person_of (P) and Driver.no_move_legacy (P and S) are labelled",
          {("Driver._person_of", "P"), ("Driver.no_move_legacy", "P"), ("Driver.no_move_legacy", "S")} <= seam, str(seam))
    check("GOOD A27: the census ends with the pinned totals line (FR-14)",
          bool(TOTALS_LINE.match(A.a27_census(PLUGIN_ROOT, scan).splitlines()[-1])))
    check("GOOD A27: the blind spots B1-B8 are printed under the header, B3 gone (C1-7b F9 closed it: the rule counts the site)",
          all(f"B{n}:" in A.a27_census(PLUGIN_ROOT, scan) for n in (1, 2, 4, 5, 6, 7, 8)) and "B3:" not in A.a27_census(PLUGIN_ROOT, scan))


PLANTED = NL.join([
    "", "class DriverPlanted:",
    "    def planted_person(self):", "        raise Person('planted', 'x')", "",
    "    def planted_builder(self):", "        raise self.held_question('x')", "",
    "    def planted_py(self):", "        self.py('log_append.py', '--event', 'x')", "",
    "    def planted_door(self):", "        self.py('stage_done.py')  # remains: planted, the result is never needed", ""])


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "scripts").glob("*.py")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


def person_home() -> str:
    """The file of the driver set that DEFINES `class Person`, found by search over the ONE reader (harness.driver_sources), never by
    name: A27 binds the driver classes only in a module whose body defines them, so a planted site goes there."""
    homes = [p.name for p, text in driver_sources() if re.search(r"^class Person\b", text, re.MULTILINE)]
    check_eq("A27 planted copy: exactly one file of the driver set defines `class Person` (the plant target)", len(homes), 1)
    return homes[0] if homes else ""


def test_a27_planted_copy() -> None:
    tmp = temp_dir("qa-factory-a27-planted-")
    try:
        dst = tmp / "plugin" / "scripts"
        dst.mkdir(parents=True)
        home = person_home()
        for path in sorted((PLUGIN_ROOT / "scripts").glob("*.py")):
            if path.name != A.DRIVER_ENTRY and not fnmatch.fnmatch(path.name, "driver_*.py"):
                continue          # the scan reads the driver set only (F3): the other 200 scripts would only be copied
            text = path.read_text(encoding="utf-8")
            if path.name == home:
                text += PLANTED
            (dst / path.name).write_text(text, encoding="utf-8")
        check_in("A27 planted copy: the entry file of the driver set is in the copy", "story_run.py", " ".join(sorted(p.name for p in dst.glob("*.py"))))
        root = tmp / "plugin"
        before = tree_hash(root)
        scan = A.a27_scan(root)
        found = A.a27_findings(root, scan)
        check_eq("GOOD A27: a copy of the live scripts with 3 planted sites gives exactly 3 findings", len(found), 3)
        for needle in ("Driver.planted_person P Person:planted", "Driver.planted_builder P builder:held_question",
                       "Driver.planted_py U log_append.py"):
            check_in(f"BAD  A27: the planted site is found - {needle}", needle, " | ".join(found))
        check_not_in("GOOD A27: the planted door is not a finding", "planted_door", " | ".join(found))
        census = A.a27_census(root, scan)
        check_in("GOOD A27: the planted door is listed with its reason", "[door: planted, the result is never needed]", census)
        check_eq("GOOD A27 (FR-45): the scan and the census wrote nothing - the tree hash is equal", tree_hash(root), before)
    finally:
        cleanup(tmp)


BUILDER = ("def b(self):", "    p = Person('k', 't')", "    return p")


PLANTED_B3 = NL.join([
    "", "class DriverPlantedB3:",
    "    def planted_print_only(self):", "        code, out = self.py('log_append.py', '--event', 'x')", "        if code:", "            print('failed')", "",
    "    def planted_acts(self):", "        code, out = self.py('log_append.py', '--event', 'x')", "        if code:", "            raise Refusal('x')", ""])


def test_a27_b3_planted_copy() -> None:
    """K15 (C1-7b, F9): a copy of the live driver with a planted `if code: print(...)`-only branch gives exactly ONE finding, `[NEW]`; the
    twin that raises on the exit is not one. The copy is read, never the live tree (FR-45)."""
    tmp = temp_dir("qa-factory-a27-b3-")
    try:
        dst = tmp / "plugin" / "scripts"
        dst.mkdir(parents=True)
        home = person_home()
        for path in sorted((PLUGIN_ROOT / "scripts").glob("*.py")):
            if path.name != A.DRIVER_ENTRY and not fnmatch.fnmatch(path.name, "driver_*.py"):
                continue
            text = path.read_text(encoding="utf-8")
            (dst / path.name).write_text(text + (PLANTED_B3 if path.name == home else ""), encoding="utf-8")
        check_in("K15 planted copy: the entry file of the driver set is in the copy", "story_run.py", " ".join(sorted(p.name for p in dst.glob("*.py"))))
        root = tmp / "plugin"
        scan = A.a27_scan(root)
        found = A.a27_findings(root, scan)
        check_eq("K15: the planted print-only branch is the ONE finding", len(found), 1)
        check_in("K15: ...and it is a [NEW] U site of the planted function", "[NEW]", " | ".join(found))
        check_in("K15: ...named by its function and script", "Driver.planted_print_only U log_append.py", " | ".join(found))
        check_not_in("K15: the twin that acts on the exit is not a finding", "planted_acts", " | ".join(found))
    finally:
        cleanup(tmp)


def test_a27_builders() -> None:
    held = NL.join(["def held_question(self, lead) -> Person:", "    return Person('q', lead)", ""]) + m("raise self.held_question('x')")
    scan, _ = run(held)
    check_eq("BAD  A27: a new `raise self.held_question(..)` is a P site at its caller; its own Person is [builder]", view(scan),
             [("Driver.held_question", "P", "Person:q", "builder"), ("Driver.m", "P", "builder:held_question", "NEW")])
    two = NL.join([*BUILDER, "def a(self):", "    return self.b()", ""]) + m("raise self.a()")
    scan, _ = run(two)
    check_eq("BAD  A27: an UNANNOTATED two-hop chain is counted at its caller; a and b themselves are not", view(scan),
             [("Driver.b", "P", "Person:k", "builder"), ("Driver.a", "P", "builder:b", "builder"), ("Driver.m", "P", "builder:a", "NEW")])
    three = NL.join([*BUILDER, "def a(self):", "    return self.b()", "def c(self):", "    return self.a()", ""]) + m("raise self.c()")
    bad("BEYOND: a three-hop chain is counted too", three, [("Driver.m", "builder:c")])
    good("a builder call inside the `again=` lambda of self.unread is the seam's",
         NL.join(BUILDER) + NL + m("self.unread('k', 's', 'd', 't', again=lambda said: self.b())"))
    bad("`x = self.b(); raise x` is counted at the call", NL.join(BUILDER) + NL + m("x = self.b()", "raise x"), [("Driver.m", "builder:b")])
    good("a builder nobody calls adds nothing", NL.join(BUILDER) + NL)


def test_a27_u_rule() -> None:
    U = [("Driver.m", "x.py")]
    bad("a statement `self.py(...)` drops the result", m("self.py('x.py')"), U)
    good("`check=True` on a continuation line", m("self.py('x.py',", "        '--a', check=True)"))
    bad("`check=flag` is not literal", m("self.py('x.py', check=flag)"), U)
    good("`code, out = ...` read by `if code:` two lines later", m("code, out = self.py('x.py')", "out = 1", "if code:", "    pass"))
    bad("re-bound before the read: the first run is dropped", m("code, out = self.py('a.py')", "code, out = self.py('b.py')", "if code:", "    pass"),
        [("Driver.m", "a.py")])
    good("AT: read on the statement just before the re-binding", m("code, out = self.py('a.py')", "if code:", "    pass",
                                                                   "code, out = self.py('b.py')", "if code:", "    pass"))
    bad("a read only inside print(f...) is not a read", m("code, out = self.py('x.py')", "print(f'x {code}')"), U)
    bad("the IfExp-in-print shape (SR 10565)", m("code, out = self.py('x.py')", "print('a' if not code else out)"), U)
    # C1-7b (F9): this pin FLIPPED. `if code: print(...)` looked at the exit and did nothing with it: the site is counted (B3 is closed).
    bad("F9: `if code: print(...)` alone is NOT a read (B3 closed)", m("code, out = self.py('x.py')", "if code:", "    print('failed')"), U)
    bad("F9: ... with an `else: print(...)` too", m("code, out = self.py('x.py')", "if code:", "    print('failed')", "else:", "    print('ok')"), U)
    good("F9 control: the same branch that also RAISES acts on the exit", m("code, out = self.py('x.py')", "if code:", "    print('failed')", "    raise Refusal('x')"))
    good("F9 control: ... or returns, or continues", m("code, out = self.py('x.py')", "if code:", "    print('failed')", "    return"))
    good("F9 control: an `elif` chain is not print-only", m("code, out = self.py('x.py')", "if code:", "    print('failed')", "elif out:", "    pass"))
    bad("F9: a compound test of print-only branch is still no read", m("code, out = self.py('x.py')", "if code and out:", "    print('failed')"), U)
    good("F9 control: the exit read ANYWHERE else in the window still reads it", m("code, out = self.py('x.py')", "if code:", "    print('failed')", "if code:", "    pass"))
    scan, census = run(m("code, out = self.py('x.py')", "if code:", "    print('failed')"))
    check("F9: B3 is no longer a printed blind spot", "B3:" not in census and len(scan.news) == 1, census)
    bad("`if self.py(..)[0]:` is a Subscript position (fail-closed)", m("if self.py('x.py')[0]:", "    pass"), U)
    bad("a walrus", m("if (r := self.py('x.py')):", "    pass"), U)
    bad("`self.x = self.py(..)`", m("self.x = self.py('x.py')"), U)
    scan, _ = run(m("put = lambda f: self.py('x.py', f)"))
    check("GOOD A27: a lambda body is [delegated]: printed, totalled, not a finding", not scan.news and scan.totals["delegated"] == 1, str(scan.totals))
    scan, _ = run(NL.join(["def note(self):", "    return self.py('log_append.py')", ""]) + m("self.note()"))
    check_eq("BAD  A27: a py-wrapper's own call is [delegated] and its dropped caller is the U site", view(scan),
             [("Driver.note", "U", "log_append.py", "delegated"), ("Driver.m", "U", "?", "NEW")])
    check_eq("A27: ... and the wrapper is counted", scan.totals["py-wrappers"], 1)
    overwritten = NL.join(["def w(self):", "    code, out = self.py('a.py')", "    code, out = self.py('b.py')", "    return code, out", ""]) + m("self.w()")
    scan, _ = run(overwritten)
    check_eq("BAD  A27 (FX-1): a result overwritten before the `return` is NOT delegated - a.py is U; b.py is the wrapper's; the caller is U",
             view(scan), [("Driver.w", "U", "a.py", "NEW"), ("Driver.w", "U", "b.py", "delegated"), ("Driver.m", "U", "?", "NEW")])
    atwin = NL.join(["def w(self):", "    code, out = self.py('a.py')", "    if code:", "        return code, out",
                     "    code, out = self.py('b.py')", "    return code, out", ""]) + m("self.w()")
    scan, _ = run(atwin)
    check_eq("GOOD A27 (FX-1, AT): a `return` just before the re-binding is inside the window - both runs are the wrapper's",
             view(scan), [("Driver.w", "U", "a.py", "delegated"), ("Driver.w", "U", "b.py", "delegated"), ("Driver.m", "U", "?", "NEW")])
    unrelated = NL.join(["def w(self):", "    code, out = self.py('a.py')", "    n = 1", "    return code, out", ""]) + m("self.w()")
    scan, _ = run(unrelated)
    check_eq("GOOD A27 (FX-1): re-binding an unrelated name does not close the window - still a wrapper", scan.totals["py-wrappers"], 1)
    branch = NL.join(["def w(self, flag):", "    code, out = self.py('a.py')", "    if flag:", "        out = 1", "    return code, out", ""]) + m("self.w(1)")
    scan, _ = run(branch)
    check_eq("A27 (FX-1, edge): a re-binding in an `if` branch closes the window too - not a wrapper (see the hand-back)",
             scan.totals["py-wrappers"], 0)
    good("a function that decides on `code` and returns only `out` is a reader, not a wrapper",
         m("code, out = self.py('x.py')", "if code:", "    raise Refusal('x')", "return out"))
    bad("F11: a statement `self.py_stdout(..)`", m("self.py_stdout('x.py')"), [("Driver.m", "py_stdout:x.py")])
    good("F11: `code, out, err = self.py_stdout(..)` + `if code:`", m("code, out, err = self.py_stdout('x.py')", "if code:", "    pass"))


def test_a27_binding() -> None:
    other = lambda *lines: {"driver_a.py": NL.join(lines) + NL}  # noqa: E731
    bad("an alias import `from story_run import Person as P` in a driver_*.py mixin", m("pass"),
        [("f", "Person:k")], others=other("from story_run import Person as P", "def f():", "    raise P('k', 't')"))
    bad("`import story_run as X` + `X.Person(` in a mixin", m("pass"),
        [("f", "Person:k")], others=other("import story_run as X", "def f():", "    raise X.Person('k', 't')"))
    bad("`from story_run import *` + `Person(` in a mixin", m("pass"),
        [("f", "Person:k")], others=other("from story_run import *", "def f():", "    raise Person('k', 't')"))
    outside = {"mod_a.py": NL.join(["from story_run import Person", "def f():", "    raise Person('k', 't')", ""]), "zz.py": "def (:" + NL}
    good("F3: a module OUTSIDE the driver set (the entry file and driver_*.py) is not parsed - a bound Person there and an unparsable file are no finding",
         m("pass"), others=outside)
    mixin = {"driver_x.py": NL.join(["from story_run import Person", "class DriverX:", "    def m(self):", "        raise Person('k', 't')", "    def u(self):", "        self.py('y.py')", ""])}
    bad("a driver_x.py mixin site is keyed Driver.<m> (a script run there is scanned: the glob)", m("pass"),
        [("Driver.m", "Person:k"), ("Driver.u", "y.py")], others=mixin)
    row = {("driver_x.py", "Driver.m", "P", "Person:k"): 1, ("driver_x.py", "Driver.u", "U", "y.py"): 1}
    good("the same site with its row moved to the mixin", m("pass"), others=mixin, rows=row)
    prob("moved without the row: renamed or moved? move the row", m("pass"), "move the row", others=mixin,
         rows={(SR, "Driver.m", "P", "Person:k"): 1})
    bad("a construction in a lambda default argument", m("f = lambda p=Person('k', 't'): p"), [("Driver.m", "Person:k")])


def test_a27_seam() -> None:
    good("a Person in the seam member `no_move`", NL.join(["def no_move(self, state):", "    raise Person('k', 't')", ""]))
    good("a Person in an `again=` lambda of self.unread", m("self.unread('k', 's', 'd', 't', again=lambda said: Person('k', said))"))
    good("a Person under the \"site_fallback\" key of the state of self.no_move",
         m("self.no_move({'why': 'x', 'site_fallback': lambda said: Person('k', said)})"))
    good("a Person under the \"site_fallback\" key of `state=` (keyword) of self.no_move",
         m("self.no_move(state={'why': 'x', 'site_fallback': lambda said: Person('k', said)})"))
    fb = "{'site_fallback': lambda said: Person('k', said)}"
    bad("FX-2: the \"site_fallback\" dict in another keyword of self.no_move counts", m("self.no_move({'why': 'x'}, extra=" + fb + ")"),
        [("Driver.m", "Person:k")])
    bad("FX-2: ... in the second positional argument (`moves`) of self.no_move counts", m("self.no_move({'why': 'x'}, " + fb + ")"),
        [("Driver.m", "Person:k")])
    bad("FX-2: ... in any argument of self.unread counts (it has no `state`)", m("self.unread('k', 's', 'd', 't', words=" + fb + ")"),
        [("Driver.m", "Person:k")])
    bad("FX-2: ... as the FIRST positional argument of self.unread counts (the state slot is no_move's, not unread's)",
        m("self.unread(" + fb + ", 's', 'd', 't')"), [("Driver.m", "Person:k")])
    bad("FX-2: ... under `state=` of self.unread counts", m("self.unread('k', 's', 'd', 't', state=" + fb + ")"), [("Driver.m", "Person:k")])
    bad("FX-2: ... nested one level inside the state dict counts", m("self.no_move({'a': " + fb + "})"), [("Driver.m", "Person:k")])
    bad("a Person in a `key=` lambda of self.unread counts (the keyword name is exact)",
        m("self.unread('k', 's', 'd', 't', key=lambda said: Person('k', said))"), [("Driver.m", "Person:k")])
    prob("`self.fallback_person` referenced from a site (integrity)", m("return self.fallback_person({})"), "seam's own")
    nested = m("def inner():", "    raise Person('k', 't')", "inner()")
    good("a nested def keys to its method: the method's row covers it", nested, rows={(SR, "Driver.m", "P", "Person:k"): 1})
    scan, _ = run(nested, rows={(SR, "inner", "P", "Person:k"): 1})
    check("BAD  A27: a row keyed by the nested name does not cover it (new + stale)", bool(scan.news) and any("stale" in p for p in scan.problems))


def test_a27_i_one() -> None:
    prob("`self.conductor(..)` in a non-member", m("self.conductor('x')"), "I-one")
    prob("an alias `f = self.conductor`", m("f = self.conductor"), "I-one")
    prob("`run_claude(\"conductor\")` outside the two sites", m("self.run_claude('conductor', 'p')"), "outside Driver.conductor and Driver.delivery")
    prob("`run_claude(kind=\"conductor\")` outside them", m("self.run_claude(kind='conductor', prompt='p')"), "outside Driver.conductor and Driver.delivery")
    prob("`run_claude(k, ..)` with a non-literal kind", m("self.run_claude(k, 'p')"), "cannot tell whether this is a conductor call")
    good("`run_claude(\"role\", ..)`", m("self.run_claude('role', 'p')"))
    good("the three documented sites", NL.join(["def conductor(self, r):", "    return self.run_claude('conductor', r)",
                                                "def delivery(self, d):", "    return self.run_claude('conductor', d)",
                                                "def _ask_conductor(self, t, s):", "    return self.conductor(t)", ""]))


def test_a27_doors() -> None:
    P = 'raise Person("k", "t")'
    for label, lines in (("on the statement's first line", [P + "  # remains: safe because x"]),
                         ("on the comment-only line directly above", ["# remains: safe because x", P]),
                         ("a 3-line raise with the door on its first line", ['raise Person("k",  # remains: because', '             "t",', '             "s")']),
                         ("AT: a one-letter reason", [P + "  # remains: x"])):
        good(f"a door {label}", m(*lines))
    bad("the door on the third line of a statement is an orphan and the site counts", m('raise Person("k",', '             "t",', '             "s")  # remains: because'),
        [("Driver.m", "Person:k")])
    prob("... named as an orphan", m('raise Person("k",', '             "t",', '             "s")  # remains: because'), "touches no counted site")
    for reason in ("", "   ", " —", " 123"):
        scan, _ = run(m(P + "  # remains:" + reason))
        check(f"BAD  A27: a door with no letter ({reason.strip() or 'empty'}) is no door: the site counts", bool(scan.news) and "no reason" in everything(scan))
    bad("a door above a blank line", m("# remains: because", "", P), [("Driver.m", "Person:k")])
    bad("a door above another comment line", m("# remains: because", "# another", P), [("Driver.m", "Person:k")])
    prob("an orphan door with no site", m("x = 1  # remains: because"), "touches no counted site")
    prob("a door on a seam site", NL.join(["def no_move(self, state):", "    " + P + "  # remains: because", ""]), "touches no counted site")
    for text in ("# Remains: r", "# see remains: r"):
        scan, _ = run(m(text, P))
        check(f"BAD  A27: `{text}` is no door: the site counts, no orphan", len(scan.news) == 1 and not scan.problems, everything(scan))
    scan, _ = run(m("x = '# remains: r'", P))
    check("BAD  A27: a `# remains:` inside a string is no door", len(scan.news) == 1 and not scan.problems, everything(scan))
    scan, _ = run(m("a, b = Person('k', 't'), Person('j', 't')  # remains: because"))
    check("BAD  A27: one door over a statement with two sites covers neither", len(scan.news) == 2 and "one door, 2 sites" in everything(scan))
    scan, _ = run(m("# remains: upper", P + "  # remains: lower"))
    check("BAD  A27: two doors for one site: the upper wins, the lower is an orphan",
          [s.reason for s in scan.sites if s.verdict == "door"] == ["upper"] and "touches no counted site" in everything(scan))
    prob("a doored site still in the baseline makes its row stale", m(P + "  # remains: because"), "stale row",
         rows={(SR, "Driver.m", "P", "Person:k"): 1})


def test_a27_baseline() -> None:
    key = (SR, "Driver.m", "P", "Person:k")
    one, two = m('raise Person("k", "t")'), m('raise Person("k", "t")', 'raise Person("k", "t")')
    good("a row AT its count", one, rows={key: 1})
    scan, _ = run(two, rows={key: 1})
    check("BAD  A27: BEYOND (+1) names the new line and the three doors",
          len(scan.news) == 1 and all(w in scan.news[0] for w in ("no_move", "check=True", "# remains:")), everything(scan))
    prob("BELOW (-1): a stale row", m("pass"), "stale row", rows={key: 1})
    good("the cap AT the sum", one, rows={key: 1}, cap=1)
    prob("the sum above the cap", one, "NO_MOVE_BASELINE_MAX", rows={key: 1}, cap=0)
    prob("the cap above the sum: stale cap", one, "stale cap", rows={key: 1}, cap=2)
    swap = m("self.py('stage_done.py')")
    scan, _ = run(swap, rows={(SR, "Driver.m", "U", "log_append.py"): 1})
    check("BAD  A27: SWAP of two shapes in one function: both the new and the stale finding", bool(scan.news) and "stale row" in everything(scan))
    scan, census = run(m("self.py('log_append.py', '--event', 'b')"), rows={(SR, "Driver.m", "U", "log_append.py"): 1})
    check("GOOD A27: a swap INSIDE one key stays green, and B7 says so", not scan.news and not scan.problems and "B7:" in census)


def test_a27_battery() -> None:
    tmp = temp_dir("qa-factory-a27-battery-")
    try:
        check_in("BAD  A27: no driver file: the driver is missing", "the driver is missing", " ".join(A.a27_scan(fake_plugin(tmp, {"x.py": "X = 1" + NL}, [])).problems))
    finally:
        cleanup(tmp)
    tmp = temp_dir("qa-factory-a27-battery-")
    try:
        check_in("BAD  A27: a scripts/ with no .py: the driver is missing", "the driver is missing", " ".join(A.a27_scan(fake_plugin(tmp, {}, [])).problems))
    finally:
        cleanup(tmp)
    prob("a 0-byte driver defines no Driver class", "", "defines no `Driver` class", raw=b"")
    prob("a non-UTF-8 driver is not read with errors=replace", "", "cannot scan", raw=bytes([255, 254, 0, 1]))
    prob("a driver with a syntax error", "", "cannot scan", raw=b"def (:" + NL.encode())
    prob("a second module of the driver set that does not parse names the file", m("pass"), "cannot scan driver_zz.py", others={"driver_zz.py": "def (:" + NL})
    scan, _ = run(m("f = " + "lambda: " * 50 + "1"))
    check("GOOD A27: AT 50-deep nested lambdas are scanned with no crash", not scan.problems, everything(scan))
    prob("BEYOND the parser's limit: cannot scan, never a traceback", m("x = " + "(" * 1000 + "1" + ")" * 1000), "cannot scan")
    pad = "# " + "x" * 900
    big = NL.join(f"def m{n}(self):{NL}    {pad}{NL}    self.py('x.py')" for n in range(1000))
    scan, census = run(big)
    check("GOOD A27: a 1 MB driver: the census prints whole (site lines == records)",
          len(big) > 900_000 and sum(1 for ln in census.splitlines() if ln.endswith("[NEW]")) == len(scan.sites) == 1000)


try:
    test_a1()
    test_a2_write_right_is_a_field()
    test_a11()
    test_a13_asked_column()
    test_a13_marker_pairing()
    test_a13_source_shape()
    test_a13_marker_pairing_without_a_backlog()
    test_a14()
    test_a17_detector_rerun()
    test_a20_portable_paths()
    test_a21_one_owner_per_fact()
    test_a22_injection_weight()
    test_a25_removed()
    test_a9_slice_freshness()
    test_a27_live()
    test_a27_planted_copy()
    test_a27_b3_planted_copy()
    test_a27_builders()
    test_a27_u_rule()
    test_a27_binding()
    test_a27_seam()
    test_a27_i_one()
    test_a27_doors()
    test_a27_baseline()
    test_a27_battery()
finally:
    cleanup(ROOT)

finish("audit rules (A1/A9/A11/A13/A14/A17/A20/A21/A22/A27)")
