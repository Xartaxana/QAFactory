"""SS1-14 N2b: the launch key of a NEW story, and the local story in the driver's S0 (t-526 section 4).

Two things are proven. (1) `Driver.s0_key_form`: a `--task` that is not a key of the project's tracker is the person's question BEFORE
anything of the story is read or written, with its four answers (`no ticket`, `retry` only where `key_pattern` is read, `go on` once,
`stop`); the launch words (`--no-trace`, P8) survive the stop; an older story (a `pipeline.json` or a snapshot on disk) and a guessed
form are never asked. (2) A local story (`LOCAL-<n>`, its text in `qa-factory/local-tickets/`) is read from its text file in S0, is not
compared to a tracker, does not require the tracker route in the readiness check, has no commit prefix, tells the scout it is local,
and the scout dispatch guard (`stage_guard.rule_tracker_route`) leaves it alone while a tracker key is still refused.
Mutations (each killed by this file): the step hoisted above the `--no-trace` save (`no_trace` check), the `no ticket` branch removed
(`no ticket` check), `ticket_adapter` back in `wanted` (`wanted` check), `rule_tracker_route` without the local branch (guard check).
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    FIXTURE_TICKET,
    driver_for,
    eq as check_eq,
    rules_broken,
    run_scenarios,
    s0_answer,
    s0_pipeline,
    s0_project,
    s0_question,
    s0_run,
    s0_state,
    stub_calls,
)

sys.path.insert(0, str(harness.SCRIPTS))
import adapter_forms as AF  # noqa: E402

REFUSED = "is not a key of this project's tracker"
COMMAND = "ticket_adapter.py local-key --words-file <file>"


def set_ticket_config(root: Path, **ticket) -> None:
    """The project's `adapters.ticket`, replaced (kind `file` is what `s0_project` writes)."""
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["adapters"] = {"ticket": ticket}
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def forms_pins() -> None:
    """The gate's own inputs (t-508 N2 section 3): a false refusal costs a question, a false pass costs the story."""
    jira = {"adapters": {"ticket": {"kind": "jira"}}}
    for value, want in (("ADD-TO-CART", True), ("CART-1", False), ("LOCAL-1", False), ("PROJ-1\n", True), ("PROJ-1 ", True),
                        ("", True), ("123", True), ("proj-1", True)):
        check_eq(f"key_refused({value!r}) on jira", AF.key_refused(value, jira), want)
    github = {"adapters": {"ticket": {"kind": "github"}}}
    check_eq("github: `123` is a key", AF.key_refused("123", github), False)
    guess = {"adapters": {"ticket": {"kind": "no-such-tracker"}}}
    check_eq("a guessed form never refuses: `eng-123` (FR-59: the factory has no standing to ask)", AF.key_refused("eng-123", guess), False)


def the_question_comes_first() -> None:
    """ADD-TO-CART with `--no-trace`: the stop, nothing read or written, the experiment flag kept (P8), `go on` passes once."""
    task = "ADD-TO-CART"
    root, task_root, env = s0_project(task)
    try:
        out = s0_run(root, env, task, "--no-trace")
        check_eq("the stop is exit 3", out.returncode, 3, out.stdout[-900:] + out.stderr[-500:])
        question = s0_question(task_root)
        check_in("the question says the key is not the tracker's", REFUSED, question)
        check_in("and that nothing has been read or written", "Nothing has been read or written yet", question)
        check_in("the answer `no ticket` names the command", COMMAND, question)
        check_in("`go on` says what it costs", "cases under this name will not be recognised", question)
        check_in("`stop` is offered", "`stop`", question)
        check_in("kind `file` reads `key_pattern`: the answer is offered", "adapters.ticket.key_pattern", question)
        check_eq("the question obeys human-questions.md", rules_broken(question), [])
        state = s0_state(task_root)
        check_eq("the block is remembered", state.get("s0_block"), "key_form")
        check_eq("no_trace is kept BEFORE the stop (P8, FR-53; mutation: the step above the save)", (state.get("launch") or {}).get("no_trace"), True)
        check("no snapshot, no pipeline, no ticket read", not (task_root / "work" / "ticket-snapshot.json").exists()
              and not (task_root / "pipeline.json").exists())
        check_eq("no conductor or role was called", stub_calls(root), [])
        # `go on`, with no flag on the command line: the pass joins the story's warnings and the experiment survives
        out = s0_answer(root, env, task, "go on")
        check_eq("`go on` goes on: exit 0", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        warnings = s0_pipeline(task_root).get("warnings") or []
        check("and written down in the story's warnings (FR-4)",
              any("the ticket key form check passed by the person's word" in line for line in warnings), str(warnings))
        check("no_trace survives the stop and the answer without the flag",
              any("this run is an experiment" in line for line in warnings), str(warnings))
    finally:
        harness.cleanup(root)


def no_ticket_holds_the_question() -> None:
    task = "ADD-TO-CART"
    root, task_root, env = s0_project(task)
    try:
        check_eq("first entry stops", s0_run(root, env, task).returncode, 3)
        out = s0_answer(root, env, task, "no ticket")
        check_eq("`no ticket`: the question is held (exit 3)", out.returncode, 3, out.stdout[-900:])
        shown = s0_question(task_root)
        check_in("`no ticket` prints the command (mutation: the branch removed -> the unread-answer text instead)", COMMAND, shown)
        check_in("its own lead says nothing was started (the unread-answer lead says another thing)", "Nothing was started under this name", shown)
        check_not_in("and it is not the unread-answer lead", "is not one of the answers this question takes", shown)
        check_in("and the question itself is still there", REFUSED, shown)
        check_eq("the block is held again", s0_state(task_root).get("s0_block"), "key_form")
        check_eq("nothing was started under the name", (task_root / "pipeline.json").exists(), False)
    finally:
        harness.cleanup(root)


def key_pattern_door() -> None:
    """`retry` is offered where the pattern is read; after the person sets it the next entry passes; while it is wrong the same question returns."""
    task = "ADD-TO-CART"
    root, task_root, env = s0_project(task)
    try:
        check_eq("stops", s0_run(root, env, task).returncode, 3)
        out = s0_answer(root, env, task, "retry")
        check_eq("`retry` with the config unchanged: the same question again", (out.returncode, s0_state(task_root).get("s0_block")), (3, "key_form"))
        check_in("...with the same text", REFUSED, s0_question(task_root))
        set_ticket_config(root, kind="file", path=str(root / "tickets"), key_pattern="[A-Z]+(?:-[A-Z]+)*")
        out = s0_answer(root, env, task, "retry")
        check_eq("after the person fixed key_pattern, `retry` goes on", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        check("and the key form was not asked again", s0_state(task_root).get("s0_block") != "key_form")
    finally:
        harness.cleanup(root)


def a_jira_form_has_no_key_pattern_door() -> None:
    task = "ADD-TO-CART"
    root, task_root, env = s0_project(task)
    try:
        set_ticket_config(root, kind="jira")
        out = s0_run(root, env, task)
        check_eq("jira: the stop", out.returncode, 3, out.stdout[-600:])
        question = s0_question(task_root)
        check_in("the question is asked", REFUSED, question)
        check_not_in("`key_pattern` is not offered where it is never read (FR-2)", "key_pattern", question)
        check_not_in("nor `retry`", "`retry`", question)
    finally:
        harness.cleanup(root)


def only_a_new_story_and_a_known_form() -> None:
    # a real key: no question
    root, task_root, env = s0_project("CART-1")
    try:
        out = s0_run(root, env, "CART-1")
        check_eq("CART-1 goes through S0 with no question", out.returncode, 0, out.stdout[-900:] + out.stderr[-500:])
        check("...and the block is not the key's", s0_state(task_root).get("s0_block") != "key_form")
    finally:
        harness.cleanup(root)
    # a guess of the tracker's form: a WARN, no stop
    root, task_root, env = s0_project("ADD-TO-CART")
    try:
        set_ticket_config(root, kind="no-such-tracker")
        out = s0_run(root, env, "ADD-TO-CART")
        check("a guessed form is no stop of this block", s0_state(task_root).get("s0_block") != "key_form", out.stdout[-600:])
        check_in("the old WARN stands", "is not a ticket key of this project", out.stdout)
    finally:
        harness.cleanup(root)
    # an older story: a snapshot on disk, any name
    root, task_root, env = s0_project("ADD-TO-CART")
    try:
        (task_root / "work").mkdir(parents=True)
        (task_root / "work" / "ticket-snapshot.json").write_text(json.dumps(
            {"key": "ADD-TO-CART", "title": "T", "acceptance_criteria": ["x"], "comments": [], "provenance": {"source": "file"}}), encoding="utf-8")
        s0_run(root, env, "ADD-TO-CART")
        check("a story with a snapshot is not asked", s0_state(task_root).get("s0_block") != "key_form")
    finally:
        harness.cleanup(root)


class _Stop(Exception):
    pass


def the_local_story() -> None:
    """LOCAL-1 with its text file: every tracker door of S0 closes for it, and a tracker key keeps them."""
    import local_keys
    import stage_guard
    root, task_root, env = s0_project("PROJ-1")
    try:
        harness.use_project(root)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        key, _rel = local_keys.mint(FIXTURE_TICKET, cfg, root)
        check_eq("the text got a local key", key, "LOCAL-1")
        driver = driver_for(root, env, key)
        # the ticket file is the stored text; `how` says so
        ticket, text, how, kept = driver.s0_ticket(None)
        check_eq("how: from the ticket file (no --ticket-file given), the snapshot marked local",
                 (how, kept, (ticket.get("provenance") or {}).get("local_key")), ("from the ticket file", False, True))
        check_eq("the text file is the ticket file", driver.s0_local_file(None), str(local_keys.ticket_path(key, root)))
        check_eq("a given --ticket-file is kept", driver.s0_local_file("mine.md"), "mine.md")

        def never(*_a, **_k):
            raise AssertionError("the tracker was asked for a local story")
        driver.direct_api_usable = never
        driver.ticket_get = never
        shown = io.StringIO()
        with redirect_stdout(shown):
            got = driver.s0_compare({"key": key}, "the snapshot")
        check_eq("s0_compare: no tracker call, the text as it is", got, "the snapshot")
        check_in("and one line says why", "local story: no tracker holds this key, nothing to compare", shown.getvalue())

        # the readiness requirement: no ticket_adapter for a local story, kept for a tracker key
        seen = []

        def record(script, *args, **_kw):
            seen.append((script, args))
            if script == "readiness.py" and "--require" in args:
                names = args[args.index("--require") + 1].split(",")
                return 0, json.dumps({"capabilities": {n: {"status": "ok", "note": "", "owner": "factory"} for n in names}})
            raise _Stop()
        driver.py = record
        driver._s0_passed = []
        try:
            with redirect_stdout(io.StringIO()):
                driver.s0_rest(None, True, [], None, "", False, [])
        except _Stop:
            pass
        wanted = [a[a.index("--require") + 1] for s, a in seen if s == "readiness.py" and "--require" in a]
        check_eq("wanted: no ticket_adapter for a local story (mutation: put it back)", wanted, ["test_repo,vcs,config_schema"])

        # the git route: no prefix search for LOCAL-
        shown = io.StringIO()
        with redirect_stdout(shown):
            driver.git_route("https://git.example/group/proj/-/merge_requests/1", "sources/S/mr-1-git.md")
        check_in("git_route: LOCAL- is no commit prefix", "has no project prefix", shown.getvalue())

        # the scout's line
        lines = driver.role_lines("S1", "qa-scout")
        check("role_lines: the scout is told the story is local",
              any(l.startswith("Ticket source: local text, key made by the factory; no tracker holds it: collect LOCAL-1 --relation task")
                  and l.endswith("do not peek it") for l in lines), str(lines))

        # the dispatch guard
        import readiness
        cap = readiness.session_route("jira", "mcp_tool", "jira_get_issue")
        (root / "qa-factory" / "readiness.json").write_text(json.dumps(
            {"capabilities": {"ticket_adapter": dict(cap, status="not_configured")}}), encoding="utf-8")
        check_eq("rule_tracker_route: a local story is not refused", stage_guard.rule_tracker_route("LOCAL-1", "qa-scout", "S1", {}), None)
        check("a tracker key is refused as before (mutation: the branch for every key)",
              bool(stage_guard.rule_tracker_route("PROJ-1", "qa-scout", "S1", {})))
        check("a LOCAL-shaped key with no text file is a tracker key: refused",
              bool(stage_guard.rule_tracker_route("LOCAL-5", "qa-scout", "S1", {})))
    finally:
        harness.cleanup(root)


def a_source_after_a_closed_story() -> None:
    """t-526 section 6 item 6 (the contract GW1-40 unknown, t-551 F7): `record-source` on a local story whose S1 is completed does
    not make `source_inputs` fail, does not block the gate, and CHANGES `source_inventory_hash` (gate A, if recorded, then stops
    work with "Gate A sources changed"; that reader is controller.py, not read here). Mutation: `record_text_source` that
    leaves the inventory hash alone, or one that leaves the new text as a gap, kills one of the three checks."""
    import local_keys
    import source_inventory as SI
    import ticket_adapter as TA
    from controller import Controller
    from test_controller_state import accept_stage
    root, _task_root, _env = s0_project("PROJ-1")
    try:
        harness.use_project(root)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        key, _rel = local_keys.mint(FIXTURE_TICKET, cfg, root)
        story = root / "qa-factory" / "artifacts" / key
        work = story / "work"
        work.mkdir(parents=True, exist_ok=True)
        inventory = work / "source-inventory.json"
        snapshot = TA.read_ticket_file(local_keys.ticket_path(key, root), key, pasted=True)
        TA.write_snapshot(snapshot, work / "ticket-snapshot.json")
        SI.record_text_source(inventory, relation="task", ref=key, snapshot=snapshot, required=True)
        SI.record_source_review(inventory, "go on")
        controller = Controller(story)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(story)},
                                        "idempotency_key": "init"})
        for stage in ("S0", "S1"):
            accept_stage(controller, story, stage)
        before = controller.source_inputs()
        check_eq("S1 is completed", controller.state()["stages"]["S1"]["status"], "completed")
        SI.record_text_source(inventory, relation="normative", ref="docs/price-rules.md",
                              snapshot=SI.text_snapshot("docs/price-rules.md", "A book costs 5.\n"), required=False)
        after = controller.source_inputs()
        check_eq("a text recorded after S1: source_inputs does not raise and the gate is not blocked",
                 after["source_completeness"]["gate_blocked"], False)
        check("... and the inventory hash is another one (a recorded gate A then stops work, loudly)",
              after["source_inventory_hash"] != before["source_inventory_hash"])
    finally:
        harness.cleanup(root)


def the_skill_twin_says_the_same() -> None:
    """t-551 F3 and F4: the skill's S0 (`phases/s0.md`) is the twin of the driver's S0 (AR-19). Mutation: delete either sentence."""
    text = (harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s0.md").read_text(encoding="utf-8")
    check_in("F3: the pass by the person's word goes into warnings[]",
             "the ticket key form check passed by the person's word: <their words>", text)
    check_in("F4: a local story leaves ticket_adapter out of --require", "leave `ticket_adapter` out of `--require`", text)
    check_in("F4: and puts no tracker question", "no tracker is read", text)


def main():
    forms_pins()
    the_skill_twin_says_the_same()
    run_scenarios([the_question_comes_first, no_ticket_holds_the_question, key_pattern_door, a_jira_form_has_no_key_pattern_door,
                   only_a_new_story_and_a_known_form], [the_local_story, a_source_after_a_closed_story])
    harness.finish("S0 key form (SS1-14 N2b)")


if __name__ == "__main__":
    main()
