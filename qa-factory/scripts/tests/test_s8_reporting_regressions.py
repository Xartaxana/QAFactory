"""S8 reporting regressions ported from the 0.7.19 run (TP2-2406) and made story-safe: a diagnostic run is
retained but is neither a product row nor a join-failed ghost (FB-43); a manual failure is answered only by a triage
row of its own attempt (CD2); the exit gate validates this story's bugs and leaves another story's alone (FB-45) -
and judges ONLY a story something named: a stop nobody named gets the full audit with a header line.

Expectations come from the requirement (the story's own bug is never skipped), not from the code (FR-58). Each
function names the mutation of the change it kills in "Kills:"."""
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as D  # noqa: E402
import contract as C  # noqa: E402
import exit_gate as E  # noqa: E402
import finalize_task as F  # noqa: E402
import hooklib  # noqa: E402
import host_adapter  # noqa: E402
import host_dispatch  # noqa: E402


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def diagnostics_retained_but_not_product_or_join_failure() -> None:
    """Kills: `diagnostic` / `flaky_diagnostic` removed from `product_result_rows` (killed here); the join filter of
    `finalize_task.reduce` removed (the ghost); the block's purpose laid OVER the row's own; the join filter widened
    to `product_result_rows` (a red-probe row then leaves the join)."""
    root = temp_dir("qa-s8-diag-")
    try:
        task = root / "QA-1"
        write_json(task / "work" / "automation-manifest.json",
                   {"tests": [{"instance_id": "real", "covers": ["TC-1"]}]})
        block = {"block_id": "diag", "purpose": "diagnostic", "attempt_started_at": "2026-10-08T01:00:00Z",
                 "results": [{"instance_id": "preflight", "status": "passed"}]}
        path = task / "work" / "run-blocks" / "diag.json"
        write_json(path, block)
        report, _ = F.reduce(task)
        check_eq("FB-43: the diagnostic row is retained in the report", len(report["results"]), 1)
        check_eq("but it is no product row", C.product_result_rows(report), [])
        check_eq("and no join-failed ghost", report.get("factory_findings") or [], [])
        for purpose in ("flaky_diagnostic", "Diagnostic"):
            write_json(path, dict(block, purpose=purpose))
            report, _ = F.reduce(task)
            check_eq(f"purpose {purpose!r}: no product row, no ghost",
                     (C.product_result_rows(report), report.get("factory_findings") or []), ([], []))
        write_json(path, dict(block, purpose="initial",
                              results=[{"instance_id": "preflight", "status": "passed", "purpose": "diagnostic"}]))
        report, _ = F.reduce(task)
        check_eq("a row's OWN purpose outranks its block's: a diagnostic row inside an `initial` block stays one",
                 (C.product_result_rows(report), report.get("factory_findings") or []), ([], []))
        write_json(path, dict(block, purpose="execution"))
        report, _ = F.reduce(task)
        check("the same row as a product run still fails the manifest join", bool(report.get("factory_findings")),
              str(report.get("factory_findings")))
        write_json(path, dict(block, purpose="red_probe"))
        report, _ = F.reduce(task)
        check("a red-probe row is no product row, but it is joined exactly as before (only diagnostics leave the join)",
              C.product_result_rows(report) == [] and bool(report.get("factory_findings")),
              str((C.product_result_rows(report), report.get("factory_findings"))))
    finally:
        cleanup(root)


def manual_triage_requires_exact_attempt() -> None:
    """Kills: the manual early `return True` (any attempt answers) restored in `_attempt_fits`; `add("manual", ...)` carrying "" again."""
    root = temp_dir("qa-s8-manual-triage-")
    try:
        task = root / "QA-1"
        write_json(task / "work" / "run-report.json",
                   {"current_results": [],
                    "current_manual_checks": [{"case": "TC-070", "attempt_id": "a1", "result": "fail"}]})
        row = {"test": "manual::TC-070::OB-1", "instance_id": "TC-070", "attempt_id": "a1", "verdict": "APP_BUG"}
        write_json(task / "work" / "triage.json", {"triage": [row]})
        check_eq("CD2: a row of the manual record's own attempt answers it", D.triage_reasons(task), [])
        write_json(task / "work" / "triage.json", {"triage": [dict(row, attempt_id="other")]})
        reasons = D.triage_reasons(task)
        check("a row of another attempt does not", any("TC-070" in r and "no verdict" in r for r in reasons), str(reasons))
        write_json(task / "work" / "triage.json", {"triage": [dict(row, attempt_id="")]})
        check_eq("a row naming no attempt still answers the current one", D.triage_reasons(task), [])
        write_json(task / "work" / "run-report.json",
                   {"current_results": [],
                    "current_manual_checks": [{"case": "TC-070", "attempt_id": "a1", "result": "fail"},
                                              {"case": "TC-070", "attempt_id": "a2", "result": "fail"}]})
        for attempt, answers in (("a1", True), ("a2", True), ("a3", False)):
            write_json(task / "work" / "triage.json", {"triage": [dict(row, attempt_id=attempt)]})
            check_eq(f"two current records of one case (a1, a2) share one failure: a row of {attempt} "
                     f"{'answers' if answers else 'does not answer'} it", D.triage_reasons(task) == [], answers)
    finally:
        cleanup(root)


def _bug_file(path: Path, n: int, task: str = "", gate: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: BUG-{n}", "title: t"] + ([f"task: {task}"] if task else []) \
        + ([f"gate_b_decision_id: {gate}"] if gate else []) + ["---", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def exit_bug_validation_is_story_scoped() -> None:
    """The audit skips only a bug POSITIVELY another existing story's; the rest is checked (FB-45, FR-59).
    Kills: `owner_of` replaced by the old `owner != task` rule (BUG-13); the skip on `unknown` (any row below);
    a join per bug (the counter)."""
    root = temp_dir("qa-s8-exit-bugs-")
    try:
        arts = root / "artifacts"
        for ticket in ("TP2-2406", "TP2-2530"):
            write_json(arts / ticket / "pipeline.json", {"ticket": ticket})
        rows = [(1, "TP2-2530", ""), (2, "TP2-2406", ""), (3, "", ""), (4, "", "gateB-TP2-2530"),
                (5, "", "gateB-TP2-2406"), (6, "", "B"), (13, "tp2-2406", "")]
        for n, owner, gate in rows:
            _bug_file(root / "bugs" / f"BUG-{n}.md", n, owner, gate)
        seen: list = []
        calls: list = []
        real_join = E.BR.story_bugs
        with patch.object(E, "state_dir", return_value=root), patch.object(E, "artifact_root", return_value=arts), \
                patch.object(E.va, "check_bug", side_effect=lambda p, e: seen.append(p.name)), \
                patch.object(E.BR, "story_bugs", side_effect=lambda *a, **k: calls.append(1) or real_join(*a, **k)):
            E.bug_audit_errors("TP2-2406")
            check_eq("FB-45: another story's bugs (by task, by gate id) are left alone; this story's, an unowned, a "
                     "ticket-less one and a lower-case spelling of this story's ticket are checked",
                     sorted(seen), ["BUG-13.md", "BUG-2.md", "BUG-3.md", "BUG-5.md", "BUG-6.md"])
            check_eq("one join for the whole audit, not one per bug", len(calls), 1)
            seen.clear()
            E.bug_audit_errors("")
            check_eq("a full audit (no task) checks every bug", len(seen), len(rows))
            seen.clear()
            E.bug_audit_errors("TP2-9999")
            check_eq("an explicit task with no story on disk skips nothing (F-4)", len(seen), len(rows))
    finally:
        cleanup(root)


def _foreign_bug(n: int, severity: str, plan_row: str, oracle: str, case: str, obligation: str,
                 ticket: str, created: str, found_ticket: str) -> str:
    """BUG-1..3 of the live TP2-2406 Codex Desktop project, as filed: no `area`, no
    `impact`, a lower-case `status`."""
    return (f"---\nid: BUG-{n}\ntitle: A bug of story {ticket}\nseverity: {severity}\nstatus: open\n"
            f"found_by: \"qa-bug-reporter ({found_ticket}-S8-qa-bug-reporter), filing qa-failure-analyst's S7 draft\"\n"
            f"plan_row: {plan_row}\nviolates: \"{oracle}\"\nrelated_case: {case}\n"
            f"related_obligation: {obligation}\ntask: {ticket}\ncreated: {created}\n---\n")


STORY = "TP2-2406"
CLOSED_STORIES = ("TP2-2530", "TP2-2534")
FOREIGN_BUGS = ("BUG-1.md", "BUG-2.md", "BUG-3.md")
# A Codex Desktop SubagentStop: no task field, an agent type that maps to no stage.
DESKTOP_STOP = {"hook_event_name": "SubagentStop", "agent_type": "default", "session_id": "codex-1"}


@contextmanager
def _desktop_project(prefix: str):
    """A temp project the hook layer points at; the process environment and hooklib's cache come back."""
    saved = {k: os.environ.get(k) for k in ("CLAUDE_PROJECT_DIR", "QA_FACTORY_TASK")}
    saved_cache = hooklib._PROJECT_ROOT_CACHE
    root = temp_project(prefix)
    try:
        use_project(root)
        os.environ.pop("QA_FACTORY_TASK", None)
        yield root / "qa-factory"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        hooklib._PROJECT_ROOT_CACHE = saved_cache
        cleanup(root)


def _story(home: Path, ticket: str, state: str) -> None:
    """`running` (a stage in flight), `open` (S4 accepted, rework pending: open, not running) or
    `closed` (S8 done and a gate B decision - `hooklib.story_closed`)."""
    stages = {"running": {"S2": {"status": "running"}}, "open": {"S4": {"status": "done"}},
              "closed": {"S8": {"status": "done"}}}[state]
    pipeline = {"ticket": ticket, "stages": stages}
    if state == "closed":
        pipeline["gates"] = {"B": {"decision": "approved"}}
    write_json(home / "artifacts" / ticket / "pipeline.json", pipeline)


def _write_bugs(home: Path, own: str = "invalid") -> None:
    """BUG-1..3 filed by other stories, as the live project holds them; BUG-4 is this story's own,
    `invalid` (no area/found_by/...) or `valid` (every required key, filed before the form cutoff)."""
    bugs = home / "bugs"
    bugs.mkdir(parents=True, exist_ok=True)
    rows = ((1, "major", "TS-9", "requirement:R-7", "TC-063", "OB-TS9-1", CLOSED_STORIES[0], "2026-09-20"),
            (2, "minor", "TS-10", "requirement:R-8", "TC-064", "OB-TS10-1", CLOSED_STORIES[0], "2026-09-20"),
            (3, "major", "TS-13", "requirement:R-12", "TC-076", "TS-13-OB1", CLOSED_STORIES[1], "2026-09-21"))
    for n, *rest in rows:
        (bugs / f"BUG-{n}.md").write_text(_foreign_bug(n, *rest, found_ticket=rest[5]), encoding="utf-8")
    body = ("---\nid: BUG-4\ntitle: A bug of this story\nseverity: minor\nstatus: Open\narea: api\n"
            f"found_by: qa-bug-reporter\nviolates: \"requirement:R-1\"\ncreated: 2026-01-01\ntask: {STORY}\n---\n"
            if own == "valid" else f"---\nid: BUG-4\ntitle: A bug of this story\ntask: {STORY}\n---\n")
    (bugs / "BUG-4.md").write_text(body, encoding="utf-8")


def _live_shape(home: Path) -> None:
    """The live TP2-2406 project: 2406 running, 2530 and 2534 closed, BUG-1..4."""
    _story(home, STORY, "running")
    for ticket in CLOSED_STORIES:
        _story(home, ticket, "closed")
    _write_bugs(home)


def _names(errors: list) -> str:
    return " | ".join(errors)


def _foreign_named(errors: list) -> list:
    return [n for n in FOREIGN_BUGS if any(e.startswith(n) for e in errors)]


def _full_audit(label: str, errors: list) -> None:
    check(f"{label}: the audit is full - every bug is named, this story's own too",
          all(any(e.startswith(n) for e in errors) for n in FOREIGN_BUGS + ("BUG-4.md",)), _names(errors))


def exit_gate_a_stop_nobody_named_gets_the_full_audit_with_a_header() -> None:
    """A guess is not a name: whatever `resolve_ticket` guesses (the only running story, the only open one, a story
    that runs while another is open), a taskless stop of a role with no stage stays `unknown-task`.
    Kills: `_named_ticket` returning the resolver's answer unchecked; the third source removed from `_identity`
    for the named cases (the other functions)."""
    def disk(kind: str, home: Path) -> None:
        if kind == "live shape (2406 running, two closed)":
            _live_shape(home)
        elif kind == "2406 open not running, 2556 running":
            _story(home, STORY, "open")
            _story(home, "TP2-2556", "running")
            _story(home, CLOSED_STORIES[0], "closed")
            _write_bugs(home)
        elif kind == "2406 the only open story, closed ones beside it":
            _story(home, STORY, "open")
            _story(home, CLOSED_STORIES[0], "closed")
            _write_bugs(home)
        else:
            _live_shape(home)
            _story(home, CLOSED_STORIES[0], "running")

    for kind in ("live shape (2406 running, two closed)", "2406 open not running, 2556 running",
                 "2406 the only open story, closed ones beside it", "two running"):
        with _desktop_project("qa-s8-exit-unnamed-") as home:
            disk(kind, home)
            _, scope = E._identity(DESKTOP_STOP, "default")
            check_eq(f"{kind}: nothing named a story", scope["task"], "unknown-task")
            errors = E.scoped_errors("default", scope["task"], scope.get("identity_facts", ""))
            _full_audit(kind, errors)
            check(f"{kind}: and the list opens with the header that says so",
                  errors[0].startswith("this stop names no story (task unknown-task)") and "BUG-" not in errors[0].split("\n")[0]
                  and "$QA_FACTORY_TASK" in errors[0] and "story_step bind" in errors[0] and "artifact root:" in errors[0],
                  errors[0][:300])
            check(f"{kind}: the header is the first line of the whole list, once",
                  sum(e.startswith("this stop names no story") for e in errors) == 1)
    with _desktop_project("qa-s8-exit-header-alone-") as home:
        _live_shape(home)
        for n in (1, 2, 3):
            (home / "bugs" / f"BUG-{n}.md").unlink()
        _write_bugs_valid = home / "bugs" / "BUG-4.md"
        _write_bugs_valid.write_text("---\nid: BUG-4\ntitle: t\nseverity: minor\nstatus: Open\narea: api\n"
                                     "found_by: qa-bug-reporter\nviolates: \"requirement:R-1\"\ncreated: 2026-01-01\n---\n",
                                     encoding="utf-8")
        check_eq("a header never stands alone: a full audit with no finding is empty",
                 E.bug_audit_errors("unknown-task"), [])


def exit_gate_fingerprint_follows_the_resolved_story() -> None:
    """The fingerprint scans the resolved story's folder, not the whole artifact root.
    Kills: `scan_root` of `_identity` made the artifact root (a file of 2530 then changes it)."""
    stop = dict(DESKTOP_STOP, tool_input={"task_name": "default__tp2_2406_s4"})
    with _desktop_project("qa-s8-exit-fingerprint-") as home:
        _live_shape(home)
        _, before = E._identity(stop, "default")
        check_eq("(the task name names the story)", before["task"], STORY)
        write_json(home / "artifacts" / CLOSED_STORIES[0] / "work" / "note.json", {"n": 1})
        _, other = E._identity(stop, "default")
        check_eq("a file another story writes does not change this story's fingerprint",
                 other["input_fingerprint"], before["input_fingerprint"])
        write_json(home / "artifacts" / STORY / "work" / "note.json", {"n": 1})
        _, own = E._identity(stop, "default")
        check("a file this story writes does", own["input_fingerprint"] != before["input_fingerprint"])


def exit_gate_task_sources_keep_their_order() -> None:
    """An explicit task wins as written; a role with a stage takes its stage's ticket before the fallback; a resolver
    that raises or a probe leave the task unknown.
    Kills: the fallback made unconditional (`if True:`); `except Exception` narrowed in `_identity`."""
    with _desktop_project("qa-s8-exit-order-") as home:
        _live_shape(home)
        _, scope = E._identity(dict(DESKTOP_STOP, task_id=CLOSED_STORIES[0]), "default")
        check_eq("an explicit task on the event wins over the fallback", scope["task"], CLOSED_STORIES[0])
        _, scope = E._identity(dict(DESKTOP_STOP, task="TP2-9999"), "default")   # no pipeline.json
        check_eq("and wins as the event wrote it, even when nothing on disk matches", scope["task"], "TP2-9999")
        with patch.object(E, "_ticket_for_stage", return_value=CLOSED_STORIES[1]):
            _, scope = E._identity(dict(DESKTOP_STOP, tool_input={"task_name": "default__tp2_2406_s4"}),
                                   "qa-scout")
        check_eq("a role with a stage takes its stage's ticket before the fallback", scope["task"], CLOSED_STORIES[1])
        with patch.object(E.SG, "resolve_ticket", side_effect=RuntimeError("unreadable root")):
            _, scope = E._identity(DESKTOP_STOP, "default")
        check_eq("a resolver that raises leaves the task unknown, never an exception", scope["task"], "unknown-task")
        probe = dict(DESKTOP_STOP, tool_input={"prompt": "QA_FACTORY_CONTEXT_PROBE"})
        _, scope = E._identity(probe, "default")
        check_eq("a diagnostic probe resolves no story", scope["task"], "unknown-task")


def exit_gate_only_what_names_a_story_names_it() -> None:
    """The desktop task name's slug, `$QA_FACTORY_TASK` and ONE story id in the text name a story; two ids in the text
    name none, though one of the two is running (edge 5).
    Kills: the `slug_matches == [ticket]` clause, the `env_task == ticket` clause, or the exactly-one rule of
    `_named_ticket` removed (`ticket in named`: the guess among two named stories passes)."""
    with _desktop_project("qa-s8-exit-named-") as home:
        _story(home, STORY, "open")
        _story(home, "TP2-2556", "running")
        for ticket in CLOSED_STORIES:
            _story(home, ticket, "closed")
        _write_bugs(home)
        event = dict(DESKTOP_STOP, tool_input={"task_name": "default__tp2_2406_s4"})
        _, scope = E._identity(event, "default")
        check_eq("a task name naming one story resolves it though another story is the one running", scope["task"], STORY)
        errors = E.scoped_errors("default", scope["task"])
        check("so only its own bug is audited, with no header",
              not _foreign_named(errors) and any(e.startswith("BUG-4.md") for e in errors)
              and not any(e.startswith("this stop names no story") for e in errors), _names(errors))
        os.environ["QA_FACTORY_TASK"] = STORY
        _, scope = E._identity(DESKTOP_STOP, "default")
        check_eq("the environment word resolves a story that does not run", scope["task"], STORY)
        os.environ.pop("QA_FACTORY_TASK")
        one = dict(DESKTOP_STOP, tool_input={"prompt": f"Ticket: {STORY}\nwork on {STORY}"})
        _, scope = E._identity(one, "default")
        check_eq("one story id in the dispatch text names it", scope["task"], STORY)
        two = dict(DESKTOP_STOP, tool_input={"prompt": f"Ticket: {STORY}\nsee also TP2-2556"})
        _, scope = E._identity(two, "default")
        check_eq("two existing stories in the text name none, though one of them runs", scope["task"], "unknown-task")


def exit_gate_a_role_with_no_stage_reads_only_the_bug_audit() -> None:
    """A stage-less agent (Codex Desktop's "default") with a known task reads the scoped bug audit only: one broken
    upstream manifest must not block every later role (the 2026-09-11 class).
    Kills: `scoped_errors` of a stage-less agent returning `collect_errors(task)` again; the stage-role narrowing
    applied to every role (the second half)."""
    with _desktop_project("qa-s8-exit-stageless-") as home:
        _live_shape(home)
        write_json(home / "artifacts" / STORY / "work" / "context-manifest.json", {})
        _write_bugs(home, own="valid")
        errors = E.scoped_errors("default", STORY)
        check_eq("a broken manifest and a valid own bug: nothing blocks a role with no stage", errors, [])
        _write_bugs(home, own="invalid")
        errors = E.scoped_errors("default", STORY)
        check("with an invalid own bug it is named, the manifest still is not",
              any(e.startswith("BUG-4.md") for e in errors) and not _foreign_named(errors)
              and not any(e.startswith("context-manifest.json") for e in errors), _names(errors))
        errors = E.scoped_errors("qa-scout", STORY)
        check("a role WITH a stage is unchanged: the scout is still blocked by its own broken manifest",
              any(e.startswith("context-manifest.json") for e in errors), _names(errors))


STALE_OPEN = "TP2-2534"
CHILD = "01a13518-0714-7000-8000-000000000001"
PARENT = "01a1350f-0000-7000-8000-000000000002"
S4_PATH = "/root/qa_case_designer__tp2_2406_2"
S3_PATH = "/root/qa_test_strategist__tp2_2406_2"
# (label, agent path, role, dispatch id) - the two children of TP2-2406 that stopped as unknown-task.
STORY_STEP_CHILDREN = (("S4", S4_PATH, "qa-case-designer", "S4-qa-case-designer-2"),
                       ("S3", S3_PATH, "qa-test-strategist", "S3-qa-test-strategist-2"))


def _s4_disk(home: Path) -> None:
    """The live disk when S4 stopped (13.10): 2406 at `S4: pending`, a SECOND open story whose S8 was left `running`,
    a closed one - so the resolver's guess is refused and only the binding can name the story."""
    write_json(home / "artifacts" / STORY / "pipeline.json", {"ticket": STORY, "stages": {"S4": {"status": "pending"}}})
    write_json(home / "artifacts" / STALE_OPEN / "pipeline.json", {"ticket": STALE_OPEN, "stages": {"S8": {"status": "running"}}})
    _story(home, CLOSED_STORIES[0], "closed")
    _write_bugs(home)


def _bind_story_step(home: Path, path: str, role: str, dispatch: str, **extra) -> Path:
    """The record `story_step bind` writes: agent_id = the agent PATH, `bound_by` story_step, no `parent_session_id`."""
    record = host_dispatch.binding_path(home.parent, path)
    write_json(record, dict({"agent_id": path, "agent_type": role, "task_id": STORY, "dispatch_id": dispatch,
                             "status": "running", "bound_by": "story_step", "bound_at": 1.0}, **extra))
    return record


def _desktop_stop(home: Path, path: str, transcript: str = "both", thread: str = CHILD) -> dict:
    """The SubagentStop the Codex Desktop host sends for a child: the parent's session id, the child's thread as
    `agent_id`, a type that maps to no stage, and the child's rollout whose first row is `session_meta`."""
    rollout = home.parent / f"rollout-2026-10-13T12-04-00-{thread}.jsonl"
    meta = {"id": thread, "agent_path": path, "parent_thread_id": PARENT,
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": PARENT, "agent_path": path}}}}
    rollout.write_text(json.dumps({"type": "session_meta", "payload": meta}) + "\n"
                       + json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}) + "\n", encoding="utf-8")
    event = {"hook_event_name": "SubagentStop", "session_id": PARENT, "turn_id": "t-1", "agent_id": thread,
             "agent_type": "default", "cwd": str(home.parent)}
    if transcript in ("both", "transcript"):
        event["transcript_path"] = str(rollout)
    if transcript in ("both", "agent"):
        event["agent_transcript_path"] = str(rollout)
    return event


def _enriched(event: dict) -> dict:
    """What `hooklib.read_event` does with a stdin event: `normalize` then `enrich`."""
    return host_dispatch.enrich(host_adapter.normalize(event))


def story_step_binding_names_the_story_on_a_desktop_stop() -> None:
    """TP2-2406 S3 (12.10) and S4 (13.10): `story_step bind` records the dispatch under the child's agent path
    with no session id; the child's SubagentStop resolves its story through that record, so the exit gate audits this
    story's bugs and not the project's. Kills: the `bound_by == 'story_step'` clause of `enrich` removed."""
    for label, path, role, dispatch in STORY_STEP_CHILDREN:
        with _desktop_project("qa-s8-binding-" + label.lower() + "-") as home:
            _s4_disk(home)
            record = _bind_story_step(home, path, role, dispatch)
            event = _enriched(_desktop_stop(home, path))
            check_eq(f"{label}: the story comes from the factory's own binding of the child's path",
                     event.get("task_id"), STORY)
            check_eq(f"{label}: and so do the dispatch id and the role",
                     (event.get("dispatch_id"), event.get("agent_type")), (dispatch, role))
            check(f"{label}: the event names the binding it came from",
                  bool(event.get("host_binding")) and os.path.samefile(event["host_binding"], record),
                  str(event.get("host_binding")))
            _, scope = E._identity(event, event["agent_type"])
            check_eq(f"{label}: the exit gate runs as this story, not unknown-task", scope["task"], STORY)
            errors = E.bug_audit_errors(scope["task"])
            check(f"{label}: so another story's bugs do not block this exit (they name stories that exist)",
                  not _foreign_named(errors), _names(errors))
            check(f"{label}: while this story's own invalid bug is named", any(e.startswith("BUG-4.md") for e in errors),
                  _names(errors))


def story_step_binding_is_read_never_rewritten() -> None:
    """`host_dispatch.record` skips a SubagentStop receipt whose path is not in `agent_id`/`task_path`, so a story_step
    record must keep the PATH in `agent_id`: the child's stop never marks it terminal, only `story_step finish` does.
    Kills: the story_step case stamping `agent_id` with the thread id and writing the file back."""
    with _desktop_project("qa-s8-binding-keep-") as home:
        _s4_disk(home)
        record = _bind_story_step(home, S4_PATH, "qa-case-designer", "S4-qa-case-designer-2")
        before = record.read_bytes()
        event = _enriched(_desktop_stop(home, S4_PATH))
        check_eq("the binding bytes are the same after enrich", record.read_bytes(), before)
        check_eq("agent_id is still the path", json.loads(record.read_text(encoding="utf-8"))["agent_id"], S4_PATH)
        host_dispatch.record(dict(event, _exit_gate_released=True))
        after = json.loads(record.read_text(encoding="utf-8"))
        check_eq("the stop of a released child does not mark a story_step record terminal",
                 (after["status"], after.get("terminal_source")), ("running", None))
        check_eq("and does not touch it at all", record.read_bytes(), before)


def story_step_binding_absent_or_elsewhere_keeps_the_gate_closed() -> None:
    """No new guess: without a record for the child's EXACT path, with no rollout, on a host that is not Codex, with a
    FINISHED (terminal) record, or with a record that is no JSON object, the task stays unknown-task and the audit
    names every bug. Kills: a lookup that falls back to another path, the parent session or the resolver's guess;
    the terminal filter removed; `read_json` back to `json.loads` (a broken record raises out of `enrich`)."""
    def unknown(label: str, event: dict) -> None:
        event = _enriched(event)
        check(f"{label}: no task and no binding on the event", "task_id" not in event and "host_binding" not in event,
              str({k: event.get(k) for k in ("task_id", "host_binding")}))
        _, scope = E._identity(event, "default")
        check_eq(label + ": the gate runs as unknown-task", scope["task"], "unknown-task")
        errors = E.bug_audit_errors(scope["task"])
        check(label + ": and the audit names the foreign bugs", len(_foreign_named(errors)) == len(FOREIGN_BUGS), _names(errors))

    with _desktop_project("qa-s8-binding-none-") as home:
        _s4_disk(home)
        unknown("no binding record", _desktop_stop(home, S4_PATH))
        _bind_story_step(home, "/root/qa_case_designer__tp2_9999", "qa-case-designer", "S4-qa-case-designer-1")
        unknown("a story_step record of ANOTHER path", _desktop_stop(home, S4_PATH))
        record = _bind_story_step(home, S4_PATH, "qa-case-designer", "S4-qa-case-designer-2")
        unknown("no agent_transcript_path and no transcript_path", _desktop_stop(home, S4_PATH, transcript="none"))
        claude = dict(_desktop_stop(home, S4_PATH, transcript="agent"), transcript_path=str(home.parent / "claude.jsonl"))
        claude.pop("turn_id")
        check_eq("not Codex (no turn_id, a Claude transcript): the child's metadata is never read",
                 host_dispatch.child_identity(claude), {})
        unknown("not Codex", claude)
        _bind_story_step(home, S4_PATH, "qa-case-designer", "S4-qa-case-designer-2", status="terminal")
        unknown("a FINISHED story_step record of the same path (a later launch is not that dispatch)",
                _desktop_stop(home, S4_PATH))
        for label, body in (("0 bytes", b""), ("broken JSON", b"{not json"), ("a JSON list", b"[]"), ("null", b"null")):
            record.write_bytes(body)
            unknown(f"a record of {label}", _desktop_stop(home, S4_PATH))
        record.write_text(json.dumps({"agent_id": S4_PATH, "bound_by": "story_step", "status": "running",
                                      "task_id": [STORY], "agent_type": "qa-case-designer"}), encoding="utf-8")
        event = _enriched(_desktop_stop(home, S4_PATH))
        check_eq("a task_id that is not a string is not copied onto the event", (event.get("task_id"), event.get("agent_type")),
                 (None, "qa-case-designer"))


def story_step_clause_keeps_the_session_rule_of_spawn_records() -> None:
    """A record `host_dispatch.record` wrote at spawn carries `parent_session_id`, and that field stays load-bearing: a
    different session is refused, a missing one is refused, the same one is accepted and the record is stamped with the
    thread id as before. A story_step record with a DIFFERENT session id is refused too; with the SAME one it is
    accepted and never written. Kills: the story_step clause widened to any `bound_by` or to a spawn record with no
    session id; demanding the field absent (a matching session id then falls to the stamping branch)."""
    spawn = {"agent_id": S4_PATH, "agent_type": "qa-case-designer", "task_id": STORY, "task_path": S4_PATH,
             "status": "running", "host": "codex", "dispatch_id": "S4-qa-case-designer-2"}

    def stop_with(home: Path, record: dict) -> dict:
        write_json(host_dispatch.binding_path(home.parent, S4_PATH), record)
        return _enriched(_desktop_stop(home, S4_PATH))

    with _desktop_project("qa-s8-binding-spawn-") as home:
        _s4_disk(home)
        for record, label in ((dict(spawn, parent_session_id="01a1350f-other"), "a spawn record of another session"),
                              (dict(spawn), "a spawn record with no session id"),
                              (dict(spawn, parent_session_id="01a1350f-other", bound_by="story_step"),
                               "a story_step record of another session")):
            event = stop_with(home, record)
            _, scope = E._identity(event, "default")
            check(label + " is refused", "host_binding" not in event and scope["task"] == "unknown-task",
                  str((event.get("host_binding"), scope["task"])))
        kept = host_dispatch.binding_path(home.parent, S4_PATH)
        write_json(kept, dict(spawn, parent_session_id=PARENT, bound_by="story_step"))
        before = kept.read_bytes()
        event = _enriched(_desktop_stop(home, S4_PATH))
        check_eq("a story_step record of the same session names the story", event.get("task_id"), STORY)
        check_eq("and its bytes are unchanged", kept.read_bytes(), before)
        host_dispatch.record(dict(event, _exit_gate_released=True))
        check_eq("and the stop of a released child leaves it running",
                 (json.loads(kept.read_text(encoding="utf-8"))["status"], kept.read_bytes()), ("running", before))
        event = stop_with(home, dict(spawn, parent_session_id=PARENT))
        stamped = json.loads(host_dispatch.binding_path(home.parent, S4_PATH).read_text(encoding="utf-8"))
        check_eq("a spawn record of the same session is accepted", event.get("task_id"), STORY)
        check_eq("and stamped with the thread id as before", stamped["agent_id"], CHILD)


def codex_form_of_the_child_is_read_only_on_codex() -> None:
    """Edge 9 (the form of CX1-1): a normalized Codex event keeps its child's metadata readable; a raw Claude event
    that SENDS `_qa_host: {"codex": true}` is reset by `normalize`, and a Claude transcript is never read as a
    rollout. Kills: `normalize` trusting a sent `_qa_host`; `child_identity` reading without `is_codex`."""
    with _desktop_project("qa-s8-form-") as home:
        _s4_disk(home)
        codex = host_adapter.normalize(_desktop_stop(home, S4_PATH))
        check_eq("a Codex event: the child's agent path is read from its rollout",
                 host_dispatch.child_identity(codex).get("task_path"), S4_PATH)
        claude = dict(_desktop_stop(home, S4_PATH, transcript="agent"), transcript_path=str(home.parent / "claude.jsonl"))
        claude.pop("turn_id")
        claude["_qa_host"] = {"codex": True}
        check_eq("a Claude event that sends `_qa_host: codex`: nothing is read", host_dispatch.child_identity(
            host_adapter.normalize(claude)), {})


def exit_gate_header_prints_what_the_identity_decision_read() -> None:
    """t-1020 M-1 (critic t-1002): the header of an unnamed audit prints the facts THE DECISION read - the ids it found
    in the dispatch text and the desktop task name - not a second read made without the stop's event (which always said
    'none', FR-41). Zero ids read: the line says 'none' truthfully; no facts at all: the header says none reached it.
    Kills: `_unnamed_header` reading `SG.resolve_ticket({})` again instead of the facts of `_named_ticket`."""
    with _desktop_project("qa-s8-header-facts-") as home:
        _story(home, STORY, "open")
        _story(home, "TP2-2556", "running")
        _write_bugs(home)
        two = dict(DESKTOP_STOP, tool_input={"prompt": f"Ticket: {STORY}\nsee also TP2-2556",
                                             "task_name": "default__tp2_2406_x"})
        _, scope = E._identity(two, "default")
        check_eq("(edge 5: two ids in the text name none)", scope["task"], "unknown-task")
        header = E.scoped_errors("default", scope["task"], scope.get("identity_facts", ""))[0]
        line = next((ln for ln in header.splitlines() if "ids named by the dispatch text" in ln), "")
        check("the header prints BOTH ids the decision read", STORY in line and "TP2-2556" in line, header[-500:])
        check("and the desktop task name it read", "desktop task_name: default__tp2_2406_x" in header, header[-500:])
        _, scope = E._identity(DESKTOP_STOP, "default")
        header = E.scoped_errors("default", scope["task"], scope.get("identity_facts", ""))[0]
        check("a stop that named no id: the line says 'none' because that is what was read",
              "ids named by the dispatch text: none" in header and "desktop task_name: none" in header, header[-500:])
        header = E.bug_audit_errors("unknown-task")[0]
        check("an audit given no facts says so, and prints no 'none' it did not read",
              "no identity facts reached this audit" in header and "ids named by" not in header, header[-300:])


def exit_gate_a_failed_join_checks_every_bug() -> None:
    """t-1020 M-3 (critic t-1002; spec edge 12 'join raised -> checked'): when the join of the story's bugs fails, the
    audit skips nothing. The bug below is T's by the join only (its gate id is T's decision `B7`, a ticket-less id) while
    its `task` names the existing story S: with the join it is `unknown` (a conflict), and with a failed join it must
    not turn `other` and vanish. Before: `joined = {}` made it `other` and the audit answered `[]`.
    Kills: `{}` passed as the failed join in `bug_audit_errors`; `owner_of` trusting a non-mapping join."""
    with _desktop_project("qa-s8-failed-join-") as home:
        _story(home, "T", "running")
        write_json(home / "artifacts" / "T" / "pipeline.json",
                   {"ticket": "T", "stages": {"S2": {"status": "running"}},
                    "gates": {"B": {"id": "B7", "gate": "B", "decision": "approved"}}})
        _story(home, "S", "open")
        task_copy = home / "artifacts" / "T" / "bugs" / "BUG-1.md"
        task_copy.parent.mkdir(parents=True, exist_ok=True)
        task_copy.write_text("---\nid: BUG-1\ntitle: t\ngate_b_decision_id: B7\n---\n", encoding="utf-8")
        project_copy = home / "bugs" / "BUG-1.md"
        project_copy.parent.mkdir(parents=True, exist_ok=True)
        project_copy.write_text("---\nid: BUG-1\ntitle: t\ntask: S\ngate_b_decision_id: B7\n---\n", encoding="utf-8")
        task_root = home / "artifacts" / "T"
        ok = E.bug_audit_errors("T")
        check("(control) with the join read, the conflicting bug is unknown and is checked",
              E.BR.owner_of(project_copy, task_root) == "unknown" and len(ok) > 0 and all(e.startswith("BUG-1.md") for e in ok),
              str(ok)[:300])
        for label, patched in (("a join that raises", {"side_effect": RuntimeError("controller.json")}),
                               ("a join that answers None", {"return_value": None}),
                               ("a join that answers a list", {"return_value": []})):
            noted: list = []   # RH1-5 H17: the note goes through `_gate_note` (a hook_signal), not stdout nobody reads
            with patch.object(E.BR, "story_bugs", **patched), patch.object(E, "_gate_note", lambda note, task="": noted.append(note)):
                failed = E.bug_audit_errors("T")
            check_eq(f"{label}: the bug is kept, the same findings as with the join (never [])", failed, ok)
            check(f"{label}: and the reason is named", any("the join of T's bugs could not be read" in n for n in noted),
                  str(noted))
        check_eq("owner_of with NO_JOIN: unknown, though the front matter names the existing story S",
                 E.BR.owner_of(project_copy, task_root, E.BR.NO_JOIN), "unknown")
        check_eq("owner_of with a join that is not a mapping: unknown", E.BR.owner_of(project_copy, task_root, []), "unknown")
        check_eq("(unchanged) a bug that S owns by its id and the join does not know stays `other` with the join read",
                 E.BR.owner_of(_owned(home, "BUG-2", "S"), task_root, {"records": []}), "other")


def _owned(home: Path, name: str, task: str) -> Path:
    path = home / "bugs" / f"{name}.md"
    path.write_text(f"---\nid: {name}\ntitle: t\ntask: {task}\n---\n", encoding="utf-8")
    return path


def enrich_never_raises_on_an_odd_rollout_or_an_unwritable_stamp() -> None:
    """t-1020 M-2 (critic t-1002; spec L-2 F-4 'no raise in enrich'). Before: a rollout row that is JSON but no object
    (a list, a string, a `payload` list) raised AttributeError out of `child_identity`, the spawn record's stamp raised
    OSError out of `atomic_json`; `hooklib.read_event` turned either into None, `exit_gate.main` got `{}` and left with
    exit 0 - a SILENT PASS for every stop. Now the record stays unwritten (or unread) and the stop is judged: a rollout
    that cannot be read names no story (unknown-task, the full audit); an unwritable stamp still names the story.
    Kills: the `except Exception` around `child_identity(event)` in `enrich`; the `except OSError` around the stamp."""
    odd_rows = (("a JSON list", "[1]"), ("a JSON string", '"x"'), ("an empty line", ""),
                ("a payload that is a list", json.dumps({"type": "session_meta", "payload": [1]})))
    with _desktop_project("qa-s8-enrich-odd-") as home:
        _s4_disk(home)
        _bind_story_step(home, S4_PATH, "qa-case-designer", "S4-qa-case-designer-2")
        for label, row in odd_rows:
            stop = _desktop_stop(home, S4_PATH)
            Path(stop["agent_transcript_path"]).write_text(row + "\n", encoding="utf-8")
            try:
                event = _enriched(stop)
            except Exception as exc:
                check(f"a rollout row that is {label}: enrich does not raise", False, f"{type(exc).__name__}: {exc}")
                continue
            _, scope = E._identity(event, "default")
            check(f"a rollout row that is {label}: no raise, no binding, the gate runs as unknown-task with the full audit",
                  "host_binding" not in event and scope["task"] == "unknown-task"
                  and len(_foreign_named(E.bug_audit_errors(scope["task"]))) == len(FOREIGN_BUGS),
                  str(event.get("host_binding")) + " " + scope["task"])
    spawn = {"agent_id": S4_PATH, "agent_type": "qa-case-designer", "task_id": STORY, "task_path": S4_PATH,
             "status": "running", "host": "codex", "dispatch_id": "S4-qa-case-designer-2", "parent_session_id": PARENT}
    with _desktop_project("qa-s8-enrich-stamp-") as home:
        _s4_disk(home)
        record = host_dispatch.binding_path(home.parent, S4_PATH)
        write_json(record, spawn)
        before = record.read_bytes()
        with patch.object(host_dispatch, "atomic_json", side_effect=PermissionError("read-only directory")):
            try:
                event = _enriched(_desktop_stop(home, S4_PATH))
            except Exception as exc:
                check("an unwritable stamp: enrich does not raise", False, f"{type(exc).__name__}: {exc}")
                return
        check("an unwritable stamp: the record still names the story, and stays as it was",
              event.get("task_id") == STORY and record.read_bytes() == before, str(event.get("task_id")))


def s8_writes_the_summary_after_the_report_and_check_does_not_judge_it() -> None:
    """RD1-20: `stage_S8` writes the delivery summary again right after the report rebuild (the summary quotes the report's
    "Left with you" section, which the scribe and the rebuild just changed); `report_facts.check` stays pure and does not compare
    the summary (its callers write the report before the summary, so a refusal there would be false every time).
    Kills: the `delivery_summary.py` run removed from `stage_S8`, or placed before `rebuild_report()`; a stale-summary problem
    added to `report_facts.check`."""
    import inspect
    import report_facts as RF
    import story_run
    source = inspect.getsource(story_run.Driver.stage_S8)
    rebuild, summary = source.rfind("self.rebuild_report()"), source.find('self.py("delivery_summary.py", "--task-root"')
    check("stage_S8 runs delivery_summary.py with --task-root", summary >= 0)
    check("and after the last report rebuild, not before it", summary > rebuild >= 0, f"{rebuild} / {summary}")
    root = temp_project("qa-s8-summary-")
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        (task / "test-report.md").write_text("# T-1\n\n## Left with you\n\n- one\n", encoding="utf-8")
        use_project(root)
        counts = []
        for left in ("## Left with you\n\n- one\n", "## Left with you\n\n- an older list\n"):
            write_json(task / "work" / "delivery-summary.json", {"left_with_you": left})
            notes = []
            counts.append([p for p in RF.check(task, notes) if "summary" in p.lower()])
        check_eq("report_facts.check names no problem about the summary, fresh or stale", counts, [[], []])
    finally:
        cleanup(root)


def main() -> None:
    s8_writes_the_summary_after_the_report_and_check_does_not_judge_it()
    diagnostics_retained_but_not_product_or_join_failure()
    manual_triage_requires_exact_attempt()
    exit_bug_validation_is_story_scoped()
    exit_gate_a_stop_nobody_named_gets_the_full_audit_with_a_header()
    exit_gate_fingerprint_follows_the_resolved_story()
    exit_gate_task_sources_keep_their_order()
    exit_gate_only_what_names_a_story_names_it()
    exit_gate_a_role_with_no_stage_reads_only_the_bug_audit()
    story_step_binding_names_the_story_on_a_desktop_stop()
    story_step_binding_is_read_never_rewritten()
    story_step_binding_absent_or_elsewhere_keeps_the_gate_closed()
    story_step_clause_keeps_the_session_rule_of_spawn_records()
    codex_form_of_the_child_is_read_only_on_codex()
    exit_gate_header_prints_what_the_identity_decision_read()
    exit_gate_a_failed_join_checks_every_bug()
    enrich_never_raises_on_an_odd_rollout_or_an_unwritable_stamp()
    finish("test_s8_reporting_regressions")


if __name__ == "__main__":
    main()
