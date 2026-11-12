#!/usr/bin/env python3
"""C3-8/9 part A: a check that computes a LIST shows the whole list in one turn, or a counted preview whose "+K more"
names where the rest is (FR-1, FR-15). One section per census site of `docs/tasks/specs/t-860-c3-8-9-first-of-n.md`.

Every converted site gets: ONE item (the text as before), EXACTLY the old slice (every item, no tail: NEGATIVE control
for the count), the old slice + 1 (every item, or the tail with a place that exists), and, where the site has a
ceiling, a list past it (the tail names a file that this call wrote). Sites that STAY are an explicit exception list
below, each with its reason; the pin on the old slice expressions is scoped to the converted sites, with a positive control.
"""
import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import critic_rollcall as CR  # noqa: E402
import detector_verdict as DV  # noqa: E402
import exit_gate as EG  # noqa: E402
import manifest_put as MP  # noqa: E402
import onboard_apply as OA  # noqa: E402
import planning_contract as PC  # noqa: E402
import readiness as RDY  # noqa: E402
import report_facts as RF  # noqa: E402
import role_digest as RD  # noqa: E402
import stage_guard as SG  # noqa: E402

COUNT_TAIL = re.compile(r"\+\d+ more|and \d+ more")


def tail_free(name: str, text: str) -> None:
    check(f"{name}: no count is printed (the NEGATIVE control: a count appears only with a cut)", not COUNT_TAIL.search(text), text[-200:])


def all_shown(name: str, items: list, text: str) -> None:
    missing = [item for item in items if item not in text]
    check(f"{name}: every one of {len(items)} items is in the text", not missing, f"missing {missing[:3]} in {text[:300]}")


# --- #1 readiness: the stand problems (env_probe layer1), bounded by construction ------------------------------

def site_readiness() -> None:
    root = temp_project("qa-wls-ready-")
    held = RDY.subprocess.run, RDY.config_fails_own_probe
    try:
        use_project(root)
        RDY.config_fails_own_probe = lambda env, root_: None
        for n in (1, 2, 3):
            items = [f"stand problem {i}" for i in range(1, n + 1)]
            payload = json.dumps({"layer1": items, "login": {"status": "ok"}})
            RDY.subprocess.run = lambda *a, _p=payload, **k: subprocess.CompletedProcess(a, 0, _p, "")
            got = RDY.check_environment({"environment": {"base_url_key": "BASE_URL"}}, root)
            text = json.dumps(got)
            all_shown(f"readiness {n} stand problem(s)", items, text)
            tail_free(f"readiness {n}", text)
            if n == 1:
                check_in("readiness one problem: the text as before (`env_probe: <problem>`)", "env_probe: stand problem 1", text)
        long_item = "z" * 300
        RDY.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"layer1": [long_item, "second"]}), "")
        text = json.dumps(RDY.check_environment({"environment": {"base_url_key": "BASE_URL"}}, root))
        check_in("readiness (stays): each problem is still cut to 200 characters, the list is not", "z" * 200 + "; second", text)
        check_not_in("...and 201 characters of one problem are not shown", "z" * 201, text)
    finally:
        RDY.subprocess.run, RDY.config_fails_own_probe = held
        cleanup(root)


# --- #4 role_digest: every error of the handoff form ----------------------------------------------------------

def site_role_digest() -> None:
    for n in (1, 5, 6, 12):
        errors = [f"row {i} is not in the form" for i in range(1, n + 1)]
        text = RD.refusal("qa-scout", errors)
        all_shown(f"role_digest {n} error(s)", errors, text)
        if n <= 5:
            tail_free(f"role_digest {n}", text)
        else:
            check_not_in(f"role_digest {n}: the old `(+K more)` is gone", "more)", text)
    check_eq("role_digest: ONE error is the same sentence as before",
             RD.refusal("qa-scout", ["a"]).split("What does not fit: ")[1].split(". ")[0], "a")


# --- #5 stage_guard: the compound deny -------------------------------------------------------------------------

def dispatch_deny(done: list, gate=None, role: str = "qa-automator", unresolved=None, calls=None) -> str:
    """`<code>|<the deny's message>` of one dispatch of `role` (S5 by default; qa-runner is S6). `unresolved` is the
    `unresolved[]` of an automation-manifest.json written for the story (None: no manifest file); `calls`, a list,
    receives one entry per call of the manifest rule."""
    root = temp_project("qa-wls-guard-")
    task = "QA-1"
    task_root = root / "qa-factory" / "artifacts" / task
    (task_root / "state").mkdir(parents=True, exist_ok=True)
    held = SG.rule_manifest

    def counted(*args, **kwargs):
        calls.append(args[1])
        return held(*args, **kwargs)
    try:
        with hooklib.selftest_root_restored(), contextlib.redirect_stderr(io.StringIO()):
            use_project(root)
            pipeline = {"ticket": task, "stages": {s: {"status": "done"} for s in done}}
            if gate:
                pipeline["gates"] = {"A": gate}
            (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            if unresolved is not None:
                (task_root / "automation-manifest.json").write_text(
                    json.dumps({"tests": [], "unresolved": unresolved}), encoding="utf-8")
            if calls is not None:
                SG.rule_manifest = counted
            code = SG.check_dispatch({"tool_name": "Agent", "cwd": str(root),
                                      "tool_input": {"subagent_type": role, "task_id": task}})
            return str(code) + "|" + SG.LAST_DENIAL["message"]
    finally:
        SG.rule_manifest = held
        cleanup(root)


def site_stage_guard() -> None:
    one = dispatch_deny(["S0", "S1", "S2", "S3", "S4"])
    code, message = one.split("|", 1)
    check_eq("stage_guard ONE reason: denied, and the sentence is `<ticket>: <reason>` as before",
             (code, message.startswith("QA-1: stage S5 is past gate A"), "problems - the request" in message), ("2", True, False))
    two = dispatch_deny(["S0", "S1", "S2", "S3"])
    code, message = two.split("|", 1)
    items = DV.split_items(message)
    check_eq("stage_guard TWO reasons: the head stands FIRST on a line and COMPOUND_HEAD_RE matches it (I3)",
             (code, message.splitlines()[0], bool(DV.COMPOUND_HEAD_RE.search(message)), len(items or [])),
             ("2", "QA-1:", True, 2))
    check("...each reason is whole, with its own waiver command (the first reason is no longer the only one)",
          items is not None and "required stages are not done" in items[0] and "gate A is not approved" in items[1], str(items))
    import story_run
    lines = story_run.Driver.refusal_lines(SimpleNamespace(findings=[], text="STAGE GUARD: " + message))
    check_eq("I3: the driver's refusal lines of that deny are 2 parts, each cut of its waiver hint",
             (len(lines), any("Your word passes" in line for line in lines)), (2, False))
    check_in("...and the parts are the two reasons", "gate A is not approved", lines[1])
    site_stage_guard_manifest()


def site_stage_guard_manifest() -> None:
    """S6-S8: the manifest rule is one more item of the combined deny (F-2), read once (F-3), and shows every open case
    (F-4); S1-S5 never carry it."""
    approved = {"status": "approved"}
    done5 = ["S0", "S1", "S2", "S3", "S4"]
    rows = lambda n: [{"case": f"TC-{i:03d}", "reason": "because"} for i in range(1, n + 1)]   # noqa: E731
    calls: list = []
    both = dispatch_deny(done5, approved, "qa-runner", rows(1), calls)
    code, message = both.split("|", 1)
    items = DV.split_items(message)
    check_eq("stage_guard S6 order block + open manifest: ONE refusal, the head FIRST on a line, TWO items (F-2)",
             (code, message.splitlines()[0], bool(DV.COMPOUND_HEAD_RE.search(message)), len(items or [])), ("2", "QA-1:", True, 2))
    check("...the first item is the order reason, the second the manifest's (it comes last)",
          items is not None and "required stages are not done: S5=pending" in items[0]
          and "dispatching qa-runner (S6) is blocked" in items[1] and "TC-001 (because)" in items[1], str(items))
    check_eq("...the manifest rule was read ONCE for that dispatch (F-3)", len(calls), 1)
    calls = []
    pure = dispatch_deny(done5, approved, "qa-runner", [], calls)
    pipeline = {"ticket": "QA-1", "stages": {s: {"status": "done"} for s in done5}, "gates": {"A": approved}}
    expected = "2|QA-1: " + SG.dispatch_errors(pipeline, "S6", journal=False)[0]
    check_eq("stage_guard S6 order block, NO open case: no manifest item, the old one-reason text byte for byte (I2)",
             pure, expected)
    check_eq("...the manifest rule was read once here as well", len(calls), 1)
    calls = []
    none = dispatch_deny(done5)
    ahead = dispatch_deny(done5, None, "qa-automator", rows(3), calls)
    code, message = ahead.split("|", 1)
    check_eq("stage_guard S5 (NEGATIVE control): an open manifest is not in an S1-S5 deny, and the rule is never read",
             ("automation-manifest" in message, "problems - the request" in message, calls), (False, False, []))
    check_eq("...the same deny without any manifest file", ahead, none)
    for n in (1, 5, 6, 12):
        calls = []
        code, message = dispatch_deny(done5 + ["S5"], approved, "qa-runner", rows(n), calls).split("|", 1)
        check_eq(f"stage_guard S6, manifest rule alone, {n} open case(s): one sentence (no head), read once",
                 (code, message.startswith("QA-1: dispatching qa-runner (S6) is blocked"), "problems - the request" in message, len(calls)),
                 ("2", True, False, 1))
        all_shown(f"stage_guard manifest rule {n} open case(s) (the old slice showed 5)", [f"TC-{i:03d} (because)" for i in range(1, n + 1)], message)
        tail_free(f"stage_guard manifest rule {n}", message)
        if n == 1:
            check_in("...one case: the text as before", "vocabulary: TC-001 (because). Give each a reason (", message)


# --- #6 manifest_put: problems of a refused fragment ------------------------------------------------------------

def stderr_of(task: str, fragment: dict) -> tuple:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = MP.run(task, json.dumps(fragment))
    return code, err.getvalue()


def site_manifest_put() -> None:
    root = temp_project("qa-wls-mput-")
    task = "QA-1"
    task_root = root / "qa-factory" / "artifacts" / task
    (task_root / "work").mkdir(parents=True)
    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            novelty = lambda n: {"tests": [{"instance_id": f"i{i}", "novelty": "x"} for i in range(1, n + 1)]}   # noqa: E731
            expect = lambda n: {"expectation_changes": ["x"] * n}                                                 # noqa: E731
            for label, make, noun_re in (("novelty", novelty, r"the `novelty` of i(\d+) is not an object"),
                                         ("expectation", expect, r"expectation_changes\[(\d+)\] is not an object")):
                for n in (1, 6, 7, 12):
                    code, text = stderr_of(task, make(n))
                    shown = re.findall(noun_re, text)
                    check_eq(f"manifest_put {label} {n} problem(s): refused, and all {n} are named", (code, len(shown)), (3, n))
                    if n <= 6:
                        tail_free(f"manifest_put {label} {n}", text)
                    check_not_in(f"manifest_put {label} {n}: no file is written below the ceiling",
                                 "the whole list:", text)
                code, text = stderr_of(task, make(200))
                path = task_root / "state" / "findings" / f"manifest-put-{label}.txt"
                said = re.search(r"the whole list: (\S+\.txt)\)", text)
                check_eq(f"manifest_put {label} 200 problems: the tail names the file this call wrote, and it holds all 200",
                         (path.is_file(), bool(said) and Path(said.group(1)).samefile(path),
                          path.read_text(encoding="utf-8").count("\n- ") if path.is_file() else -1), (True, True, 200))
                check_in(f"manifest_put {label} 200: the count of what is left", "(+", text)
                check_in("...and the repair marker still ends the sentence", "re-run", text) if label == "novelty" else None
    finally:
        cleanup(root)
    keys = [((f"f{i}",), "r", "g") for i in range(1, 8)]
    check_eq("manifest_put._listed ONE key: the key text as before", MP._listed(keys[:1]), MP._key_text(keys[0]))
    six = MP._listed(keys[:6])
    check_eq("manifest_put._listed exactly 6: every key, no tail", (COUNT_TAIL.search(six), six.count("functions [")), (None, 6))
    check_eq("manifest_put._listed: the keys are told apart by `; ` (a key's own text holds commas)",
             six.split("; "), [MP._key_text(k) for k in keys[:6]])
    seven = MP._listed(keys)
    check_in("manifest_put._listed 7: the tail names the place of the 7th", " and 1 more (the manifest's expectation_changes[])", seven)
    check_eq("manifest_put._listed none: said in words", MP._listed([]), "the manifest holds no expectation_changes[] record yet")


# --- #8 report_facts: the reasons a record is invalid --------------------------------------------------------

def site_report_facts() -> None:
    row = {"schema_version": 2, "case": "TC-001", "attempt_id": "a1", "evidence_validated": False}
    for n in (1, 2, 5):
        errors = [f"reason {i}" for i in range(1, n + 1)]
        text = RF._invalid_words(dict(row, evidence_errors=errors), [])
        all_shown(f"report_facts {n} reason(s)", errors, text)
        tail_free(f"report_facts {n}", text)
    check_eq("report_facts ONE reason: the text as before",
             RF._invalid_words(dict(row, evidence_errors=["evidence hash mismatch"]), []), "evidence invalid: evidence hash mismatch")
    check_eq("report_facts two reasons are joined by `; `",
             RF._invalid_words(dict(row, evidence_errors=["a", "b"]), []), "evidence invalid: a; b")
    check_eq("report_facts none recorded: said in words",
             RF._invalid_words(dict(row, evidence_errors=[]), []), "evidence invalid: no reason was recorded")
    # the neighbour (:743): a case with SEVERAL invalid records says why for each, once
    import test_report_facts as TRF
    task = TRF.manual_story()
    try:
        raw = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))["manual_checks"]
        rows = json.loads(json.dumps(raw))
        rows[0].update(result="inconclusive", evidence_validated=False, evidence_errors=["evidence hash mismatch"])
        TRF.write(task / "work" / "run-report.json", dict(TRF.RUN_REPORT, current_manual_checks=rows, manual_checks=raw))
        one = TRF.case_line(TRF.block_of(task), "TC-001")
        check_in("report_facts case, ONE invalid record: not checked, its reason as before",
                 "not checked: runner said pass; evidence invalid: evidence hash mismatch", one)
        second = json.loads(json.dumps(rows[0]))
        second.update(attempt_id="a2", evidence_errors=["capture is empty"], result="fail")
        TRF.write(task / "work" / "run-report.json", dict(TRF.RUN_REPORT, current_manual_checks=rows + [second], manual_checks=raw))
        two = TRF.case_line(TRF.block_of(task), "TC-001")
        check("report_facts case, TWO invalid records: both reasons are told (it used to be the first only)",
              "evidence hash mismatch" in two and "capture is empty" in two, two)
        check_in("...and the records are told apart by ` | ` (one record's own text holds `; `, F-8)",
                 "runner said pass; evidence invalid: evidence hash mismatch | evidence invalid: capture is empty", two)
    finally:
        cleanup(task.parents[2])


# --- #11 exit_gate: case identity ----------------------------------------------------------------------------

def site_case_identity() -> None:
    import contract as C
    ticket = "TP1-9"
    for n in (1, 6, 7, 9):
        root = temp_project("qa-wls-cid-")
        try:
            with hooklib.selftest_root_restored():
                use_project(root)
                cases = C.artifact(EG.artifact_root() / ticket, "test-cases")
                cases.mkdir(parents=True)
                for i in range(1, n + 1):
                    (cases / f"stray_{i:02d}.md").write_text(f"---\nid: not-a-case-{i:02d}\n---\nx\n", encoding="utf-8")
                errors = EG.case_identity_errors("qa-case-designer", ticket)
                text = " ".join(errors)
                shown = re.findall(r"-> `([^`]+)\.md` with `id:", text)
                check_eq(f"case identity {n} stray file(s): ONE record, and every file has its NEW name", (len(errors), len(shown)), (1, n))
                check_not_in(f"case identity {n}: the old `(+K more)` is gone (a file past the sixth lost its repair)", "more)", text)
                if n == 1:
                    check_in("case identity one file: head unchanged (I4)", "case identity: a case file's `id` is its file name", text)
        finally:
            cleanup(root)


# --- #15 / #16 planning_contract, #17 critic_rollcall: ids inside one finding ------------------------------

def site_named_ids() -> None:
    import test_question_branches as TQB
    for n in (1, 8, 9):
        questions = [TQB.register(f"Q{i}") for i in range(1, n + 1)]
        row = TQB.row("TS-1", question_refs=["Q99"])
        got = PC.variant_errors([row], questions, [])
        text = " ".join(e["message"] for e in got)
        ids = [f"Q{i}" for i in range(1, min(n, 8) + 1)]
        all_shown(f"planning_contract.variant_errors {n} register id(s) (up to the limit 8)", ids, text)
        if n <= 8:
            tail_free(f"planning_contract.variant_errors {n}", text)
        else:
            check_in("planning_contract.variant_errors 9 ids: the tail counts the ninth and names where it is",
                     "and 1 more (the plan's questions)", text)
    check_in("planning_contract.variant_errors NO register: the word `none` as before", "the register's ids are none",
             " ".join(e["message"] for e in PC.variant_errors([TQB.row("TS-1", question_refs=["Q99"])], [], [])))
    ifa = {"a": {"disposition": "automate"}, "b": {}, "not_needed": {}}
    for n in (1, 6, 7):
        plan = [TQB.row(f"TS-{i}", disposition="manual-agent", question_refs=["Q5"], if_answered={"Q5": ifa}) for i in range(1, n + 1)]
        root, task = TQB.gate_a_story("qa-wls-", plan, [TQB.register("Q5")], {})
        try:
            lines = "\n".join(PC.apply_gate_answers(task, "Both of these are fine as they stand, go on."))
        finally:
            cleanup(root)
        names = [f"TS-{i}" for i in range(1, min(n, 6) + 1)]
        all_shown(f"planning_contract.apply_gate_answers {n} row(s) (up to the limit 6)", names, lines)
        if n <= 6:
            tail_free(f"planning_contract.apply_gate_answers {n}", lines)
        else:
            check_in("planning_contract.apply_gate_answers 7 rows: the tail counts the seventh and names where", "and 1 more (the test plan)", lines)
    head = "# Critic findings\n\nVerdict: approve_with_concerns (1 concern, 0 fail), confidence: medium.\n\n## Roll-call\n\n| TS | case | note |\n|---|---|---|\n"
    for n in (1, 8, 9):
        ids = [f"TC-{i:03d}" for i in range(1, n + 1)]
        text = " ".join(CR.findings_errors(Path("critic-findings.md"), head + "".join(f"| TS-{i} | {c} | found |\n" for i, c in enumerate(ids, 1))))
        all_shown(f"critic_rollcall {n} unstated row(s) (up to the limit 8)", ids[:8], text)
        if n <= 8:
            tail_free(f"critic_rollcall {n}", text)
        else:
            check_in("critic_rollcall 9 rows: the tail counts the ninth and names where", "and 1 more (the roll-call table)", text)
    check_in("critic_rollcall: the `n of total` sentence is unchanged", "whether 9 of 9 rows were read", text)


# --- #22 planning_contract._manual_agent_pass: the person-facing line (FR-6, walk B) ---------------------------

def site_manual_agent_line() -> None:
    import coverage_contract as CCON
    import human_text
    import test_question_branches as TQB
    held = CCON.validate_obligations
    try:
        CCON.validate_obligations = lambda _works: ["the first break", "the second break"]
        obligation = dict(TQB.obligation("OB-X"))
        root, task = TQB.gate_a_story("qa-wls-ma-", [TQB.manual_row("TS-5", [obligation], level="api")], [TQB.register("Q1")], {}, ticket="QA-9")
        try:
            lines = PC.apply_gate_answers(task, "go on")
        finally:
            cleanup(root)
    finally:
        CCON.validate_obligations = held
    line = next((ln for ln in lines if "would stop passing its own check" in ln), "")
    check_in("manual-agent pass, 2 problems: both are named, with the count", "(2 problem(s): the first break; the second break)", line)
    check_eq("FR-6 walk B: that line, with 2 problems, breaks no rule of human-questions.md (a non-empty answer is a STOP and a question)",
             human_text.problems(line, kind="report"), [])


# --- #9 onboard_apply: no group of the listing is cut -----------------------------------------------------------

def plan_view(**over) -> dict:
    base = {"blocked": None, "nothing_to_do": False, "manifest": {"status": "ok", "reason": "", "newer": False}, "retire": [], "write": [],
            "regenerate": [], "changed_since_install": [], "not_ours_kept": [], "locks": [], "live_locks": [], "unknown": [],
            "refused": [], "tracking": {}, "set_aside": None, "proposal": {}, "install_exists": True, "date": "2026-10-01"}
    base.update(over)
    return base


def retire_row(i: int, mode: str) -> dict:
    return {"rel_path": f"qa-factory/state/file-{i:03d}.json", "retire_mode": mode, "requires": [],
            "summary": {"bytes": 10, "mtime": "2026-10-01T00:00:00", "first_line": "x"}}


def group_lines(text: str, heading: str) -> list:
    block = text.split(heading)[1].split("\n\n")[0].splitlines()[1:]
    return [ln for ln in block if ln.startswith("  - ") or ln.startswith("    ")]


# (caller of the old `_cap`, verdict, what the person sees): the approval groups are whole (FR-8/FR-9); the informational
# groups are whole too because the proposal file (`--out`) holds none of them, so there is no place to point at (FR-15).
ONBOARD_GROUPS = (
    ("config change (applied)", "approval", "Will be written:", lambda n: dict(
        write=[{"rel_path": OA.CONFIG_REL, "action": "update"}],
        proposal={"removed": [{"path": f"/s{i}", "reason": "gone"} for i in range(n)]})),
    ("files moved", "approval", "Will be moved", lambda n: dict(
        write=[{"rel_path": f"qa-factory/records/m{i}.json", "action": "move", "source": f"qa-factory/state/m{i}.json"} for i in range(n)])),
    ("files deleted", "approval", "Will be deleted", lambda n: dict(retire=[retire_row(i, "delete") for i in range(n)])),
    ("files set aside", "approval", "Will be set aside", lambda n: dict(retire=[retire_row(i, "move") for i in range(n)])),
    ("git removals (tracked in state)", "approval", "Tracked inside the ignored folder", lambda n: dict(
        tracking={"tracked_in_state": [f"qa-factory/state/t{i}.json" for i in range(n)], "tracked_changes": [], "line": ""})),
    ("git removals (tracked, now ignored)", "approval", "Generated files your repository still tracks", lambda n: dict(
        tracking={"tracked_in_state": [], "tracked_ignored": [f"qa-factory/artifacts/T-1/evidence/g{i}.png" for i in range(n)],
                  "tracked_changes": [], "line": ""})),
    ("git removals (tracked changes)", "approval", "A tracked deletion or move", lambda n: dict(
        tracking={"tracked_in_state": [], "tracked_changes": [{"rel_path": f"qa-factory/state/c{i}.json", "what": "deleted"} for i in range(n)], "line": ""})),
    ("kept: changed since install", "informational", "Kept: changed since", lambda n: dict(
        changed_since_install=[{"rel_path": f"qa-factory/k{i}.md"} for i in range(n)])),
    ("kept: two copies", "informational", "Kept, two different copies", lambda n: dict(
        changed_since_install=[{"rel_path": f"qa-factory/k{i}.md", "duplicate_of": f"qa-factory/o{i}.md"} for i in range(n)])),
    ("kept, not touched", "informational", "Kept, not touched:", lambda n: dict(
        not_ours_kept=[{"rel_path": f"qa-factory/n{i}.md", "reason": "not_ours"} for i in range(n)])),
    ("kept, could not be checked", "informational", "Kept, could not be checked:", lambda n: dict(
        unknown=[{"rel_path": f"qa-factory/u{i}.md", "reason": "unreadable"} for i in range(n)])),
    ("not touched, and why", "informational", "Not touched, and why:", lambda n: dict(
        refused=[{"rel_path": f"qa-factory/r{i}.md", "reason": "a link"} for i in range(n)])),
    ("lock files left alone", "informational", "Lock files left alone", lambda n: dict(
        locks=[{"rel_path": f"qa-factory/state/l{i}.lock", "action": "listed", "class": "carried", "kind": "file"} for i in range(n)])),
    ("held right now", "informational", "Held right now", lambda n: dict(
        live_locks=[{"rel_path": f"qa-factory/state/h{i}.lock", "holder": "s1"} for i in range(n)])),
)


def site_onboard_apply() -> None:
    check_eq("onboard_apply: 13 callers of the old cap and the OH3-33 group, each with a verdict here", len(ONBOARD_GROUPS), 14)
    for name, verdict, heading, make in ONBOARD_GROUPS:
        for n in (1, 10, 20, 21, 25):
            text = OA.render(plan_view(**make(n)))
            shown = group_lines(text, heading)
            extra = 1 if name.startswith("config") else 0           # the bullet of the configuration file itself
            check_eq(f"onboard_apply [{verdict}] {name}: {n} item(s) in, {n} lines out", len(shown) - extra, n)
            if n <= 20:
                tail_free(f"onboard_apply {name} {n}", text)
            else:
                check_not_in(f"onboard_apply {name} {n}: the old `+K more (...)` line is gone", " more (", text)
    deleted = group_lines(OA.render(plan_view(retire=[retire_row(i, "delete") for i in range(10)])), "Will be deleted")
    check_eq("onboard_apply: a list of 10 deletions shows 10 (the person's decision whole)", len(deleted), 10)
    check_eq("onboard_apply: the cap is gone from the module", (hasattr(OA, "_cap"), hasattr(OA, "LISTING_CAP")), (False, False))
    added = OA._config_lines({"added": [{"path": f"/k{i}"} for i in range(12)], "answers_legacy": {f"n{i}": 1 for i in range(9)}})
    check_eq("onboard_apply: the added settings and the kept notes are named whole (12 and 9), not 6 and 4 with a count",
             (len(added[0].split(": ")[1].split(", ")), added[1].count("n8"), COUNT_TAIL.search(" ".join(added))), (12, 1, None))


# --- C4-5 remainder (class K1): a record with two independent defects is refused for both, once ----------------

def refusal_of(call) -> str:
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return ""


def site_k1_remainder() -> None:
    import tempfile
    import case_versions as CV
    import record_schema as RS
    head = "2 problems - the request is refused whole, every one is listed:"
    person = {"type": "object", "required": ["name", "age", "tags"],
              "properties": {"name": {"type": "string", "minLength": 2},
                             "age": {"type": "integer", "minimum": 0},
                             "tags": {"type": "array", "items": {"type": "string"}}}}
    # record_schema.validate: ONE problem is its own sentence (unchanged); two are one combined refusal in the walk's order
    check_eq("record_schema one problem: the sentence as before",
             refusal_of(lambda: RS.validate(person, {"name": "Ann", "age": -1, "tags": []})), "$.age: below minimum")
    two = refusal_of(lambda: RS.validate(person, {"name": "A", "age": -1, "tags": []}))
    check_eq("record_schema two independent defects in two properties: both named, in the walk's order, one refusal",
             two, f"{head}\n1) $.name: too short\n2) $.age: below minimum")
    three = refusal_of(lambda: RS.validate(person, {"age": "old", "tags": ["a", 5, None]}))
    check_eq("record_schema a missing key + a wrong type + two bad array items: all four, required before properties before items",
             three, "4 problems - the request is refused whole, every one is listed:\n1) $: missing name\n2) $.age: expected integer"
                    "\n3) $.tags[1]: expected string\n4) $.tags[2]: expected string")
    check_eq("record_schema a wrong type stands alone at its own place (no check runs on a value that is not that type)",
             refusal_of(lambda: RS.validate(person, "text")), "$: expected object")
    check_eq("record_schema a valid record: no refusal", refusal_of(lambda: RS.validate(person, {"name": "Ann", "age": 1, "tags": []})), "")
    check_in("record_schema an unsupported keyword still raises on the spot (the schema's defect, not the record's)",
             "unsupported schema keywords", refusal_of(lambda: RS.validate({"type": "object", "pattern": "x", "required": ["a"]}, {})))
    check_eq("record_schema.validate_record on a real kind: two defects of a Decision in one refusal (same class, ValueError)",
             len(DV.split_items(refusal_of(lambda: RS.validate_record("Decision", {}))) or []) >= 2, True)

    # case_versions.validate_batch: files that cannot be read, then collisions among the ones that can
    def case(path: Path, cid: str, body: str = "x", area: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        front = f"id: {cid}\n" + (f"area: {area}\n" if area else "")
        path.write_text(f"---\n{front}---\nPlan row: TS-1\n# {body}\n" if cid else f"# {body}\n", encoding="utf-8")
        return path
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        good = case(root / "a" / "TC-001.md", "TC-001")
        wrong = case(root / "b" / "TC-002.md", "TC-009")
        bare = case(root / "c" / "TC-003.md", "")
        twin_a = case(root / "d" / "TC-004.md", "TC-004", "left", area="billing")
        twin_b = case(root / "e" / "TC-004.md", "TC-004", "right", area="billing")
        mismatch = f"case identity mismatch: {wrong} declares TC-009 but filename names TC-002"
        check_eq("case_versions one unreadable file: the sentence as before",
                 refusal_of(lambda: CV.validate_batch([good, wrong])), mismatch)
        check_eq("case_versions one file with no frontmatter id: its sentence as before",
                 refusal_of(lambda: CV.validate_batch([good, bare])), f"case file has no frontmatter id: {bare}")
        check_eq("case_versions two unreadable files: both named, in the order of the batch, one refusal",
                 refusal_of(lambda: CV.validate_batch([good, wrong, bare])),
                 f"{head}\n1) {mismatch}\n2) case file has no frontmatter id: {bare}")
        mixed = refusal_of(lambda: CV.validate_batch([wrong, twin_a, twin_b]))
        items = DV.split_items(mixed) or []
        check("case_versions an unreadable file + a collision of two others: both, the file first then the collision",
              len(items) == 2 and items[0] == mismatch and items[1].startswith("case identity collision billing/TC-004"), mixed)
        check_eq("case_versions one collision: the sentence as before",
                 refusal_of(lambda: CV.validate_batch([twin_a, twin_b])).split(":")[0], "case identity collision billing/TC-004")
        check_eq("case_versions an empty batch: nothing to refuse, no candidates", CV.validate_batch([]), [])
        check_eq("case_versions a clean batch: the candidates, in order",
                 [c["key"] for c in CV.validate_batch([good, twin_a])], ["a/TC-001", "billing/TC-004"])

    # manual_evidence.validate_record STAYS (census verdict M): the planned-policy mismatch is told alone, and a non-object too
    import manual_evidence as ME
    check_eq("manual_evidence.validate_record (stays, fork to the Lead): a policy mismatch is still the one sentence",
             ME.validate_record({"evidence_policy": "ui"}, Path("."), "api"), ["evidence_policy does not match the planned obligation"])
    check_eq("manual_evidence.validate_record: a non-object is the one sentence", ME.validate_record("x", Path(".")),
             ["manual evidence record must be an object"])


# --- the scope pin: the old slice expressions at the converted sites ------------------------------------------

# Part A's converted sites, each with the expression it must no longer hold. (File, regex, the census row.)
GONE = (
    ("role_digest.py", r"errors\[:5\]", "#4"),
    # (`rule_tracker_route` keeps its own `blocking[0]`: it filters ONE raw message, not a list)
    ("stage_guard.py", r"deny\(f\"\{ticket\}: \{blocking\[0\]\}\"\)", "#5"),
    ("stage_guard.py", r"open_items\[:5\]", "#5 neighbour: the manifest rule's own text, one item of the compound deny"),
    ("manifest_put.py", r"problems\[:6\]", "#6"),
    ("manifest_put.py", r"keys\[:LISTED_KEYS\]", "#6 _listed"),
    ("report_facts.py", r"errors\[0\]", "#8"),
    ("report_facts.py", r"next\(r for r in group if not _row_valid", "#8 neighbour :743"),
    ("exit_gate.py", r"listed\[:6\]", "#11"),
    ("onboard_apply.py", r"_cap\(|LISTING_CAP|added\[:6\]|legacy\[:4\]", "#9"),
    ("planning_contract.py", r"list\(known\)\[:8\]|rows_on\[:6\]", "#15, #16"),
    ("critic_rollcall.py", r"\[\"unstated\"\]\[:8\]", "#17"),
)
# The sites that STAY, each with its reason (the verdict «stays» of the census, F2): a slice of ONE item's text, not of a list.
STAYS = (
    ("readiness.py", r"str\(item\)\[:200\]", "#1: each stand problem is cut to 200 characters as before (the length of one line); "
                                             "the LIST of problems is whole through DV.joined"),
)
# #2 `story_step` `filled[:3]`/`[:2]`, #13 `gate_brief` `[:5]` and #14 `s5_precheck` `[:6]` are Part B's files: pinned in their tests.


def source_of(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def scan(source: str, pattern: str) -> bool:
    return re.search(pattern, source) is not None


def site_scope_pin() -> None:
    check("scope pin POSITIVE control: the scanner finds a slice in a known sample", scan("x = errors[:5]", r"errors\[:5\]"))
    for name, pattern, reason in STAYS:
        check(f"stays {reason.split(':')[0]}: the expression is still there (so the exception list is not stale)", scan(source_of(name), pattern))
    for name, pattern, row in GONE:
        check(f"{name} ({row}): no old slice expression is left", not scan(source_of(name), pattern), pattern)
    # every Part-A call of `named` names the place of the rest: the optional `where` is only the migration seam of
    # `gate_preflight.named_ids`' text (t-874 standing question 1)
    import ast
    named_calls = []
    for name in ("manifest_put.py", "planning_contract.py", "critic_rollcall.py"):
        for node in ast.walk(ast.parse(source_of(name))):
            func = getattr(node, "func", None)
            if isinstance(node, ast.Call) and ((isinstance(func, ast.Attribute) and func.attr == "named")
                                               or (isinstance(func, ast.Name) and func.id in ("named", "named_ids"))):
                named_calls.append((name, node.lineno, any(k.arg == "where" for k in node.keywords)))
    check("scope pin: the scanner finds the named() calls of Part A (POSITIVE control)", len(named_calls) == 5, str(named_calls))   # 5: a fifth Part-A site (planning_contract) joined in release 0.10.8; it names `where` too
    check("every named() call of Part A passes `where`", all(ok for _n, _l, ok in named_calls), str([c for c in named_calls if not c[2]]))
    check("every converted file imports the one carrier (`detector_verdict`)",
          all(scan(source_of(name), r"detector_verdict") for name in ("readiness.py", "role_digest.py", "stage_guard.py", "manifest_put.py",
                                                                      "report_facts.py", "planning_contract.py", "critic_rollcall.py", "exit_gate.py")))


def main() -> None:
    site_readiness()
    site_role_digest()
    site_stage_guard()
    site_manifest_put()
    site_report_facts()
    site_case_identity()
    site_named_ids()
    site_manual_agent_line()
    site_onboard_apply()
    site_k1_remainder()
    site_scope_pin()
    finish("test_whole_list_sites")


if __name__ == "__main__":
    main()
