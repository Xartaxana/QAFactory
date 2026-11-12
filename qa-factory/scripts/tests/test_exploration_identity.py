#!/usr/bin/env python3
"""XT1-2: the identity of an exploration (qa-explore) in the guards.

One predicate (`stage_guard.exploration_named`) says a dispatch or a stop belongs to an exploration; `resolve_ticket`,
`check_dispatch`, `host_dispatch.record`, `exit_gate._identity` / `main` and `subagent_journal` read it. The invariants:
a story dispatch is never taken for an exploration (the label is read first, `$QA_FACTORY_TASK=explore:` only at step 5, never over
a story the event names); an exploration is never judged by a story's rules, on the way in or at its stop; a table that cannot be
read never lets a story dispatch pass; `import exploration` stays light (AR-12).
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_project  # noqa: E402

import exit_gate  # noqa: E402
import exploration as X  # noqa: E402
import host_dispatch  # noqa: E402
import hooklib  # noqa: E402
import project_inventory  # noqa: E402
import readiness  # noqa: E402
import stage_guard as SG  # noqa: E402
import subagent_journal  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
STORY, STORY2 = "XPANBFLFA-44", "XPANBFLFA-45"
SLUG = "add-to-cart"
LABEL = X.table()["label"]
GOOD = {"status": "ok", "owner": "factory", "note": "fine"}
os.environ.pop("QA_FACTORY_TASK", None)


def project(stories=(STORY,), explore=True) -> Path:
    """A project with the given stories (a pipeline.json each) and, when asked, the exploration `add-to-cart` made by the real `frame`."""
    root = temp_project("qa-xt12-")
    for name in stories:
        folder = root / "qa-factory" / "artifacts" / name
        folder.mkdir(parents=True)
        (folder / "pipeline.json").write_text(json.dumps({"ticket": name, "stages": {}}), encoding="utf-8")
    if explore:
        saved = (readiness.check_jira_direct, project_inventory.build_inventory)
        readiness.check_jira_direct = lambda cfg, r: dict(GOOD)
        project_inventory.build_inventory = lambda cfg, r, selected=None: {"repositories": []}
        try:
            X.frame(root, "Add to Cart", [], [], None, "sess-a")
        finally:
            readiness.check_jira_direct, project_inventory.build_inventory = saved
    return use(root)


def use(root: Path) -> Path:
    """Make `root` THE project of the hooks under test (the environment variable and the per-process cache of the project root)."""
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    hooklib._PROJECT_ROOT_CACHE = None
    return root


def dispatch(root, prompt="", role="qa-scout", description="explore", **more) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "cwd": str(root), "session_id": "s-1",
             "tool_input": {"subagent_type": role, "description": description, "prompt": prompt}}
    event.update(more)
    return event


def named_dispatch(root, task_name) -> dict:
    """A desktop dispatch: the story is named only by the `task_name` argument (step 3 of `resolve_ticket`)."""
    event = dispatch(root, "x")
    event["tool_input"]["task_name"] = task_name
    return event


def label(slug=SLUG) -> str:
    return f"{LABEL} {slug}\nStep: E1\nFeature: \"Add to Cart\"\n"


def verdict(event) -> tuple:
    """(exit code, the refusal text printed, if any) of `check_dispatch`."""
    SG.LAST_DENIAL.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = SG.check_dispatch(event)
    return code, SG.LAST_DENIAL.get("message", "")


def ticket_of(event) -> str:
    return SG.resolve_ticket(event)[0]


def transcript(root, text, name="child.jsonl") -> str:
    path = root / name
    path.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n"
                    + json.dumps({"type": "assistant", "message": {"content": "ok"}}) + "\n", encoding="utf-8")
    return str(path)


def stop(root, agent="qa-scout", opening=None, name="child.jsonl", **more) -> dict:
    """A SubagentStop. `name` is the child's transcript file: two events built before either is read need two names (one name is
    ONE file, and the later write is what both events then read)."""
    event = {"hook_event_name": "SubagentStop", "agent_type": agent, "cwd": str(root), "session_id": "s-1", "agent_id": "a-1"}
    if opening is not None:
        event["agent_transcript_path"] = transcript(root, opening, name)
    event.update(more)
    return event


def labels_and_import() -> None:
    root = project()
    try:
        brief = X.brief(root, SLUG, "E1")
        check_eq("brief_label_parsed: the label line `brief` writes is read back as the slug", X.labels_in(brief), [SLUG])
        check_eq("label_inside_text_not_read: a label inside a sentence is no label",
                 X.labels_in(f"see {LABEL} {SLUG} results\nand {LABEL} {SLUG} more words\n"), [])
        check_eq("labels_in: repeats collapse, order is kept", X.labels_in(f"{LABEL} b\n{LABEL} a\n{LABEL} b\n"), ["b", "a"])
        check_eq("env_slug: the prefix is the table's", (X.env_slug(X.task_id("a")), X.env_slug("a"), X.env_slug(X.table()["env_prefix"])), ("a", "", ""))
        check_eq("opening_prompt: the FIRST user row, '' for an absent file", (X.opening_prompt(transcript(root, "hello")), X.opening_prompt(root / "nope")), ("hello", ""))
    finally:
        cleanup(root)
    code = ("import sys; sys.path.insert(0, %r); import exploration; print('controller' in sys.modules, 'no_move' in sys.modules)" % str(SCRIPTS))
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True).stdout.strip()
    check_eq("import_light: `import exploration` loads neither controller nor no_move", out, "False False")


def resolution() -> None:
    root = project()
    try:
        check_eq("label_beats_sole_story: one story running + a label -> no story", ticket_of(dispatch(root, label())), "")
        facts = SG.resolve_ticket(dispatch(root, label()))[1]
        check_eq("label_beats_sole_story: ... and the exploration is named", facts.get("exploration"), SLUG)
        check_eq("label_beats_ticket_text: a story key in the text does not win over the label",
                 SG.resolve_ticket(dispatch(root, label() + f"Feature: fix {STORY} cart\n"))[1].get("exploration"), SLUG)
        check_eq("label_beats_ticket_text: ... the ticket is empty", ticket_of(dispatch(root, label() + f"see {STORY}\n")), "")
        check_eq("label_beats_ticket_text: the description in front of the prompt does not hide the label",
                 SG.resolve_ticket(dispatch(root, label(), description=f"explore {STORY} work"))[1].get("exploration"), SLUG)
        check_eq("explicit_explore_id: `task_id: explore:<slug>` is the exploration",
                 SG.resolve_ticket(dispatch(root, "no label here", task_id=X.task_id(SLUG)))[1].get("exploration"), SLUG)
        check_eq("label_and_story_id_no_story: a label plus a story task_id is no story (the `both` case)", ticket_of(dispatch(root, label(), task_id=STORY)), "")
        os.environ["QA_FACTORY_TASK"] = X.task_id(SLUG)
        try:
            check_eq("env_beats_guess: env explore:<slug>, one story, nothing named -> exploration",
                     SG.resolve_ticket(dispatch(root, "plain words"))[1].get("exploration"), SLUG)
            check_eq("env_does_not_override_named_story: an explicit story id wins over the variable",
                     ticket_of(dispatch(root, "plain words", task_id=STORY)), STORY)
            check_eq("env_does_not_override_named_story: a story key in the text wins over the variable",
                     ticket_of(dispatch(root, f"work on {STORY}")), STORY)
            check_eq("label_beats_env: another label wins over the variable and is no refusal",
                     SG.resolve_ticket(dispatch(root, label("other-one")))[1].get("exploration_problem"), "missing")
            check_eq("label_beats_env: the same label is the exploration", SG.resolve_ticket(dispatch(root, label()))[1].get("exploration"), SLUG)
            os.environ["QA_FACTORY_TASK"] = X.task_id("no-such")
            check_eq("env_missing: an env exploration with no explore.json is a problem, never a story",
                     SG.resolve_ticket(dispatch(root, "plain words"))[1].get("exploration_problem"), "missing")
        finally:
            os.environ.pop("QA_FACTORY_TASK", None)
    finally:
        cleanup(root)


def story_answers() -> list:
    """The answers of steps 1-5 of `resolve_ticket` on six fixtures; the same list before the change and with an unreadable table."""
    out = []
    root = project((STORY, STORY2), explore=False)
    try:
        out.append(ticket_of(dispatch(root, "x", task_id=STORY2)))                         # 1 explicit
        out.append(ticket_of(dispatch(root, "x", task_id="NOPE-1")))                       # 1 explicit, no such story
        out.append(ticket_of(dispatch(root, f"work on {STORY}")))                          # 2 key in the text
        out.append(ticket_of(dispatch(root, "plain words")))                               # ambiguous: two stories
        out.append(ticket_of(named_dispatch(root, "qa_scout__xpanbflfa_45")))   # 3 desktop task_name
        os.environ["QA_FACTORY_TASK"] = STORY2
        try:
            out.append(ticket_of(dispatch(root, "plain words")))                           # 5 variable
        finally:
            os.environ.pop("QA_FACTORY_TASK", None)
    finally:
        cleanup(root)
    root = project((STORY,), explore=False)
    try:
        out.append(ticket_of(dispatch(root, "plain words")))                               # 4 the sole story
    finally:
        cleanup(root)
    return out


def unchanged_and_unreadable() -> None:
    expected = [STORY2, "", STORY, "", STORY2, STORY2, STORY]
    check_eq("no_label_unchanged: six fixtures of steps 1-5 answer as they did before", story_answers(), expected)
    saved = X.table

    def broken():
        raise X.ExplorationRefused("exploration table references/exploration.json is unreadable (test)")
    X.table = broken
    root = project((STORY, STORY2), explore=False)
    try:
        check_eq("table_unreadable_story_path_unchanged: the same six fixtures answer the same", story_answers(), expected)
        use(root)
        ev = dispatch(root, "plain words", session_id="s-unreadable-" + uuid.uuid4().hex)   # the once-flag is per session, outside the project
        for _ in range(3):
            SG.resolve_ticket(ev)
        seen = sum(p.read_text(encoding="utf-8", errors="replace").count("exploration_table_unreadable")
                   for p in root.rglob("*") if p.is_file() and p.suffix in (".jsonl", ".json", ".log"))
        check_eq("table_unreadable_story_path_unchanged: the signal is written once", seen, 1)
        code, text = verdict(dispatch(root, f"Ticket: {STORY}\n", task_id=STORY))
        check("table_unreadable_story_path_unchanged: a story dispatch is still checked (not ALLOWed by a crash)",
              code != 0 or SG.LAST_DENIAL.get("ticket") == STORY, f"{code} {text}")
        code, text = verdict(dispatch(root, label()))
        check("table_unreadable_story_path_unchanged: an exploration label then meets the identity refusal, not a pass",
              code == 2 and "task identity is missing or ambiguous" in text, f"{code} {text}")
    finally:
        X.table = saved
        cleanup(root)


def verdicts() -> None:
    root = project((STORY, STORY2))
    try:
        for role in ("qa-scout", "qa-requirements-tester"):
            check_eq(f"exploration_role_allowed: {role} with a label in a project with stories", verdict(dispatch(root, label(), role=role))[0], 0)
        code, text = verdict(dispatch(root, label(), role="qa-automator"))
        check("exploration_wrong_role_refused: a role with no exploration step", code == 2 and text.startswith("exploration identity: this role has no exploration step")
              and "qa-scout (E1, E2)" in text and "qa-requirements-tester (E3)" in text, text)
        code, text = verdict(dispatch(root, "plain words"))
        check("ticketless_still_refused: no label, two stories -> the old identity refusal", code == 2 and text.startswith("task identity is missing or ambiguous"), text)
        code, text = verdict(dispatch(root, label() + label("other-one")))
        check("two_labels_refused: two names", code == 2 and text.startswith("exploration identity: two explorations named (add-to-cart, other-one)"), text)
        code, text = verdict(dispatch(root, label("Not A Slug")))
        check("label_not_slug_refused: a name that is no slug is not read as a label line", code == 2 and "task identity" in text, text)
        code, text = verdict(dispatch(root, f"{LABEL} Bad_Name\n"))
        check("label_not_slug_refused: one word that is no slug", code == 2 and text.startswith("exploration identity: not an exploration name (Bad_Name)"), text)
        code, text = verdict(dispatch(root, label("never-framed")))
        check("label_without_explore_json_refused: names the door `explore_step.py frame`",
              code == 2 and text.startswith("exploration identity: no exploration `never-framed`") and "explore_step.py frame" in text, text)
        code, text = verdict(dispatch(root, label(), task_id=STORY))
        check("label_and_story_id_refused: a label and a story task_id", code == 2 and text.startswith("exploration identity: the dispatch names both a story"), text)
        code, text = verdict(dispatch(root, label() + f"Ticket: {STORY}\n"))
        check("label_and_ticket_line_refused: a label and a `Ticket:` line of an existing story",
              code == 2 and text.startswith("exploration identity: the dispatch names both a story"), text)
        code, _ = verdict(dispatch(root, "Ticket: NOPE-9\n" + label()))
        check_eq("label_and_ticket_line_refused: a `Ticket:` line of a story that does not exist is no story", code, 0)
    finally:
        cleanup(root)
    root = project((STORY,))
    try:
        check_eq("inject_no_story_packet: a label with one story open resolves NO story (no controller read, no receipt refusal)",
                 SG.requested_ticket(dispatch(root, label())), "")
    finally:
        cleanup(root)


def command_text_names_no_exploration() -> None:
    """t-734 B-1: a label line inside a Bash command is no dispatch word. One story at S5; `git stash` is denied with and without it."""
    root = project((STORY,))
    try:
        (root / "qa-factory" / "artifacts" / STORY / "pipeline.json").write_text(json.dumps({"ticket": STORY, "stages": {"S5": {"status": "running"}}}), encoding="utf-8")

        def cmd(text, tool="Bash"):
            return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(root), "session_id": "s-1", "tool_input": {"command": text}}

        def deny(text, tool="Bash"):
            SG.LAST_DENIAL.clear()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = SG.check_command(cmd(text, tool))
            return code, STORY in SG.LAST_DENIAL.get("message", "")
        plain = deny("git stash")
        check_eq("bash_label_line_not_read: `git stash` with one story at S5 is denied with the story", plain, (2, True))
        for name, line in (("an existing exploration", label()), ("a missing one", label("zzz")), ("two", label() + label("other-one"))):
            check_eq(f"bash_label_line_not_read: the same command plus a label line naming {name} is denied the same",
                     deny("git stash\n: <<'N'\n" + line + "N"), plain)
        check_eq("bash_label_line_not_read: PowerShell too", deny("git stash\n" + label(), "PowerShell"), plain)
        check_eq("bash_label_line_not_read: a commit message with the label line still resolves to the story",
                 ticket_of(cmd('git commit -m "fix cart\n' + label("zzz") + '"')), STORY)
        # t-772 (the t-741 pair, each guard alone): the label KEYS and the dispatch TEST are two defences, each pinned by its own event.
        # (i) a DISPATCH whose tool_input carries a `command` field with a label line: never read from `command` (kills `command`
        # in _LABEL_TEXT_KEYS, which the Bash events above never reach because route A is not read for them);
        # (ii) a Bash/PowerShell event whose `description`/`prompt` carries a label line: no dispatch, no exploration (kills
        # `is_dispatch = True`, which the command-only events above never reach because `command` is not a label key).
        via_command = dispatch(root, "x")
        via_command["tool_input"]["command"] = label()
        check_eq("dispatch_command_field_not_read: an Agent dispatch with a label line in `command` resolves to the story, no exploration",
                 (ticket_of(via_command), SG.resolve_ticket(via_command)[1].get("exploration"), SG.exploration_named(via_command, {})),
                 (STORY, None, ("", "")))
        for tool in ("Bash", "PowerShell"):
            for field in ("description", "prompt"):
                shell = cmd("echo hi", tool)
                shell["tool_input"][field] = label()
                check_eq(f"shell_{field}_label_not_read: a {tool} event with a label line in `{field}` is no exploration",
                         (ticket_of(shell), SG.resolve_ticket(shell)[1].get("exploration"), SG.exploration_named(shell, {})),
                         (STORY, None, ("", "")))
        check_eq("explicit_id_on_non_dispatch_stays: route B (an `explore:` id) is still read on any event",
                 SG.resolve_ticket(dict(cmd("echo hi"), task_id=X.task_id(SLUG)))[1].get("exploration"), SLUG)
    finally:
        cleanup(root)


def receipt() -> None:
    root = project((STORY,))
    try:
        event = dispatch(root, label(), tool_response={"task_path": "/root/explore-1", "task_name": "explore-1"}, tool_use_id="tu-1")
        host_dispatch.record(event)
        path = host_dispatch.binding_path(root, "/root/explore-1")
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        check_eq("receipt_carries_exploration: the receipt FILE exists and names the exploration", data.get("task_id"), X.task_id(SLUG))
    finally:
        cleanup(root)


def stops() -> None:
    root = project((STORY,))
    opening = f"You are qa-scout.\n{label()}"
    boom = []

    def failing(*a, **k):
        boom.append(1)
        raise AssertionError("a story check judged an exploration stop")
    saved = (exit_gate.awaiting_source_review, exit_gate.all_errors, exit_gate._record, exit_gate.read_event)
    exit_gate.awaiting_source_review = exit_gate.all_errors = exit_gate._record = failing

    def run(event):
        exit_gate.read_event = lambda: event
        try:
            exit_gate.main()
        except SystemExit as exc:
            return exc.code
        return "returned"
    try:
        (root / "qa-factory" / "artifacts" / STORY / "pipeline.json").write_text(json.dumps({"ticket": STORY, "stages": {"S1": {"status": "running"}}}), encoding="utf-8")
        check_eq("stop_not_judged_by_story: S1 running + the child's own opening carries the label -> exit 0, no story check",
                 (run(stop(root, opening=opening)), boom), (0, []))
        (root / "qa-factory" / "artifacts" / STORY / "pipeline.json").write_text(json.dumps({"ticket": STORY, "stages": {"S5": {"status": "running"}}}), encoding="utf-8")
        check_eq("stop_not_judged_s5_only: the only story is at S5, nothing at S1/S2", (run(stop(root, opening=opening)), boom), (0, []))
        check_eq("stop_tester_not_judged_by_story: the E3 role", (run(stop(root, agent="qa-requirements-tester", opening=opening.replace("qa-scout", "qa-requirements-tester"))), boom), (0, []))
        check_eq("stop_codex_receipt: an event whose task_id `enrich` made explore:<slug>", (run(stop(root, task_id=X.task_id(SLUG))), boom), (0, []))
        key, scope = exit_gate._identity(stop(root, opening=opening), "qa-scout")
        check_eq("journal_line_carries_exploration: `_identity` says task explore:<slug> (the journal reads the same)", scope["task"], X.task_id(SLUG))
        # the stops that are NOT explorations go the old way
        for name, event, agent in (
                ("stop_parent_transcript_ignored", stop(root, transcript_path=transcript(root, opening, "parent.jsonl")), "qa-scout"),
                ("stop_story_role_unchanged", stop(root, agent="qa-automator", opening=opening, name="automator.jsonl"), "qa-automator"),
                ("stop_no_proof", stop(root), "qa-scout"),
                ("stop_other_exploration_missing", stop(root, opening=opening.replace(SLUG, "never-framed"), name="missing.jsonl"), "qa-scout")):
            key, scope = exit_gate._identity(event, agent)
            check(f"{name}: the old path, no exploration identity", not scope["task"].startswith(X.table()["env_prefix"]) and "exploration" not in scope, str(scope))
        # a role the exploration table does not list is never an exploration, whatever its opening prompt carries (the role test of
        # route C); the explorer beside it, same opening, is one: the pair pins the test, not the label
        foreign = stop(root, agent="qa-automator", opening=opening, name="foreign.jsonl")
        explorer = stop(root, agent="qa-scout", opening=opening, name="explorer.jsonl")
        check_eq("stop_non_explorer_role_not_an_exploration: qa-automator + a label in its opening -> nothing named; qa-scout -> the slug",
                 (SG.exploration_named(foreign, {}), SG.exploration_named(explorer, {})), (("", ""), (SLUG, "")))
        for rid in ("gone", "Bad_Name"):
            ev = stop(root, task_id=X.task_id(rid), session_id="s-rej-" + uuid.uuid4().hex)   # the once-flag is per session, outside the project
            check_eq(f"stop_rejected_explore_id_not_judged: explore:{rid} -> exit 0, no story check", (run(ev), boom), (0, []))
            key, scope = exit_gate._identity(ev, "qa-scout")
            check(f"stop_rejected_explore_id_not_judged: explore:{rid} is no story and says why", scope.get("exploration_rejected") and "exploration" not in scope, str(scope))
        texts = "".join(p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*.jsonl"))
        check("stop_rejected_explore_id_not_judged: one signal per id names what could not be established and the door",
              texts.count("exploration_stop_unproven") == 2 and "explore_step.py frame" in texts, str(texts.count("exploration_stop_unproven")))
        # subagent_journal: the line of an exploration stop
        saved_journal = subagent_journal.read_event
        subagent_journal.read_event = lambda: stop(root, opening=opening)
        try:
            try:
                subagent_journal.main()
            except SystemExit:
                pass
        finally:
            subagent_journal.read_event = saved_journal
        lines = [json.loads(line) for p in root.rglob("*.jsonl") for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
                 if '"subagent_stop"' in line]
        check("journal_line_carries_exploration: subagent_stop is journaled with task explore:<slug> and no return_owner",
              len(lines) == 1 and lines[0]["task"] == X.task_id(SLUG) and "return_owner" not in lines[0], str(lines))
        check_eq("journal_line_carries_exploration: no controller dispatch is resolved for it",
                 subagent_journal._story_dispatch(stop(root), {"task": X.task_id(SLUG), "dispatch": "a-1"}), "")
    finally:
        exit_gate.awaiting_source_review, exit_gate.all_errors, exit_gate._record, exit_gate.read_event = saved
        cleanup(root)


def main() -> None:
    labels_and_import()
    resolution()
    unchanged_and_unreadable()
    verdicts()
    command_text_names_no_exploration()
    receipt()
    stops()
    finish("test_exploration_identity")


if __name__ == "__main__":
    main()
