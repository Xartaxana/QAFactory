"""The guard as the host really calls it: one process per tool event, the event on stdin.

Two defects of session 57cf578c (TP1-15045, 0.7.6; 127 of 1668 tool calls refused by the
factory's own hooks):

one turn counter per SESSION. A role shares its `session_id` with the orchestrator
and with every role before it, so a fresh role heard on its first minute "930 tool calls,
hand back": 43 interruptions in 16 dispatches, and critic-4 obeyed at 71 calls of its own
(one more critic dispatch, $5.48, 58 min). The host sends `agent_id` on a tool event fired
inside a subagent call — the hook receipts of that session carry `acb310e4e528a3eaa`, the id
of the transcript `subagents/agent-acb310e4e528a3eaa.jsonl` — and that is the key now.

raw run logs refused by extension. 12 reads were refused, among them a 1.2 KB log
whose only content was pytest's `ERROR: not found: ...` (exit 4) and 238-byte junit files,
so no role could see why nothing had run. The rule is about weight; it now weighs.

Most calls below run `logs_check` and the handover rules through `_blocked()`, and `budget_notice` through
`_noticed()`, in this process — the assertions are about the DECISION those functions make, and guard_pre_tool.py imports the
same `turn_budget`/config-reading code either way. A subprocess per call cost this file ~15 s
for ~25 launches of guard_pre_tool.py; two stay real `hook()` children (marked CLI CONTRACT
below), proving the actual host invocation itself: a real process exits 2 with the refusal on
stderr, and the turn-counter file it writes is the one a role's next call reads.

SC1-2 part B2 (the keys K-B6 .. K-B17 below): a role without Bash fills its handover form in ONE Write of
`<dispatch>.values.yaml`; the guard proves that file against the form before it lands, refuses an Edit of a form
whose values file waits (the file would be applied over it), and keeps `.values.applied/.stale.yaml` for code.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (  # noqa: E402
    SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))
import guard_pre_tool as G  # noqa: E402

SESSION = "57cf578c-0000-4000-8000-budgettest01"


def _payload(root: Path, event: dict) -> dict:
    """The PreToolUse payload every helper below feeds the guard: the host's three base fields, then `event`."""
    return dict({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(root)}, **event)


def hook_run(root: Path, event: dict, via_telemetry: bool = False):
    """The whole process result of guard_pre_tool.py fed one PreToolUse event, as hooks.json runs it — a REAL
    subprocess; `via_telemetry` runs it the way the Write/Bash hook lines do (`telemetry_hook.py guard_pre_tool.py`)."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    payload = _payload(root, event)
    argv = [sys.executable, "-B"] + ([str(SCRIPTS / "telemetry_hook.py"), "guard_pre_tool.py"] if via_telemetry
                                      else [str(SCRIPTS / "guard_pre_tool.py")])
    return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)


def hook(root: Path, event: dict):
    """(exit code, stderr) of guard_pre_tool.py fed one PreToolUse event — see `hook_run`. Kept for the calls
    marked CLI CONTRACT below."""
    proc = hook_run(root, event)
    return proc.returncode, proc.stderr


def noticed(root: Path, event: dict) -> str:
    """The TURN BUDGET text ONE call leaves for the guard's exit (`budget_notice` in this process, no subprocess),
    "" when it has none. The notice never exits (SC1-6): there is no code to return, only text."""
    payload = _payload(root, event)
    return G._noticed(G.budget_notice, payload, G.load_config(payload)) or ""


def seed_counter(root: Path, count: int, event: dict | None = None, session: str = SESSION) -> Path:
    """Write the counter the next call counts on (one call short of the mark, `soft` 5): the fifth call of a
    window or a dispatch without four subprocess launches to get there."""
    import turn_budget
    path = turn_budget.counter_path(session, dict({"session_id": session, "cwd": str(root)}, **(event or {})))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"scheme": turn_budget.SCHEME, "count": count, "started": "2026-10-27T00:00:00+00:00",
                                "notified": 0}), encoding="utf-8")
    return path


def call(root: Path, fn, event: dict) -> tuple[int, str]:
    """(exit code, stderr) of ONE guard rule function that REFUSES (`logs_check`, `handoff_write_check`, ...)
    against a PreToolUse-shaped event, in this process — same payload shape and config
    resolution as `hook()`, no subprocess. A rule that only records a notice (`budget_notice`) goes
    through `noticed()`. `use_project(root)` must already have pinned this
    root (once per test, not once per call — the root does not change within a test here)."""
    payload = _payload(root, event)
    cfg = G.load_config(payload)
    text = G._blocked(fn, payload, cfg)
    return (2 if text else 0), (text or "")


def configure(root: Path, **blocks) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(blocks)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def open_dispatch(root: Path) -> None:
    """A running dispatch puts the orchestrator's own calls in the guard's scope."""
    state = root / "qa-factory" / "artifacts" / "QA-1" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "controller.json").write_text(json.dumps(
        {"dispatches": {"S5-qa-automator-1": {"role": "qa-automator", "status": "running"}}}),
        encoding="utf-8")


def test_counter_is_per_dispatch() -> None:
    root = temp_project("qa-guard-budget-")
    try:
        use_project(root)
        configure(root, turns={"soft": 5, "repeat": 5, "window": 120, "stage_default": 35})
        open_dispatch(root)
        grep = {"tool_name": "Grep", "tool_input": {"pattern": "x"}}
        automator = dict(grep, agent_id="a301712c46df18269", agent_type="qa-factory:qa-automator")
        critic = dict(grep, agent_id="a3bb0091b2c125ccd", agent_type="qa-factory:qa-code-critic")

        # the orchestrator's window, up to and over its own mark
        texts = [noticed(root, grep) for _ in range(3)]
        check_eq("the orchestrator's first three calls say nothing", texts, [""] * 3)
        turns = root / "qa-factory" / "state" / "turns"
        # CLI CONTRACT, kept as a real child: the real host invocation, start to finish — a
        # subprocess that exits 0 here still runs the same turn_budget code and writes the
        # same counter file a role's next call (in-process or not) reads.
        proc = hook_run(root, grep)
        check_eq("the orchestrator's fourth call (the real host invocation) passes too", proc.returncode, 0)
        check_eq("and says nothing on stdout", proc.stdout, "")
        window_after_real_child = json.loads((turns / f"{SESSION}.json").read_text(encoding="utf-8"))
        check_eq("the real child's call persisted the counter file at 4",
                 window_after_real_child.get("count"), 4)

        # K1: the fifth call is NOT stopped - the call runs and the notice rides beside it
        text = noticed(root, grep)
        check_in("K1: its fifth carries a notice about the window", "this window has made 5 tool calls", text)
        check_not_in("that carries none of a role's advice", "hand back", text)
        check_not_in("and no 'If you are' fork for the reader to resolve", "If you are", text)
        check_eq("K1: the counter reads 5", json.loads((turns / f"{SESSION}.json").read_text(encoding="utf-8")).get("count"), 5)
        check_eq("K1: the sixth call says nothing (the next notice is a `repeat` away)", noticed(root, grep), "")

        # a role starts from nothing, in the same session
        texts = [noticed(root, automator) for _ in range(4)]
        check_eq("a role's first four calls say nothing although the session has spent five", texts, [""] * 4)
        text = noticed(root, automator)
        check_in("K1: the role's OWN fifth call is told", "this agent has made 5 tool calls", text)
        check_in("and the role's advice", "hand back your digest", text)
        for foreign in ("stage_done", "qa-story", "this window has made", "ORCHESTRATOR"):
            check_not_in(f"and nothing of the orchestrator's ({foreign})", foreign, text)
        check_in("still a notice, not a refusal", "not a refusal", text)
        check_in("and says what is true on both exits: the turn budget stops no call",
                 "not a refusal: the turn budget stops no call.", text)
        check_not_in("F1: and never 'no call was stopped' (false after another rule's refusal)", "no call was stopped", text)
        check_not_in("K6: and never says to make the call again (the old footer contradicted the hook's own TRAPPED line)",
                     "same call again", text)
        check_eq("the sixth call of the role says nothing", noticed(root, automator), "")

        # the next dispatch is another counter
        check_eq("the next role's first call is call 1", noticed(root, critic), "")

        window = json.loads((turns / f"{SESSION}.json").read_text(encoding="utf-8"))
        check_eq("role calls were never counted into the window (its own six: 3 + the real child + the fifth + the sixth)",
                 window.get("count"), 6)
        per_dispatch = sorted(p.name for p in (turns / "dispatches").glob("*.json"))
        check_eq("one counter file per dispatch, keyed by the host's agent_id",
                 per_dispatch, ["a301712c46df18269.json", "a3bb0091b2c125ccd.json"])
        check_eq("and none of them where window_budget.live_session() looks for 'this window'",
                 sorted(p.name for p in turns.glob("*.json")), [f"{SESSION}.json"])

        import window_budget
        check_eq("live_session() still answers with the orchestrator's session while roles work",
                 window_budget.live_session(root / "qa-factory"), SESSION)
    finally:
        cleanup(root)


def flushed(event: dict, text: str, code: int) -> tuple[str, str, str]:
    """(stdout, stderr, what is left in `_NOTICE`) after `_flush_notice(event, code)` had `text` pending."""
    import contextlib
    import io
    G._NOTICE = text
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        G._flush_notice(event, code)
    return out.getvalue(), err.getvalue(), G._NOTICE


ROLE = {"agent_id": "a301712c46df18269", "agent_type": "qa-factory:qa-automator"}
SCOUT = {"agent_id": "a9f00000000000001", "agent_type": "qa-factory:qa-scout"}


def notice_world(prefix: str) -> tuple[Path, dict, dict]:
    """A project at `soft` 5 with one dispatch open (so the orchestrator's calls are in the guard's scope), a small
    file and a file over the raw-log line. Returns (root, a Read of the small file, a Read of the big one)."""
    root = temp_project(prefix)
    use_project(root)
    # The boundary is declared, as onboarding leaves it (same as K-B14): the guard says ONCE per session, on stderr, that an
    # EMPTY protected_app_paths leaves P-00 unenforced, and the marker of that is in the OS temp dir - a fresh machine
    # prints it on the first call, which the "stderr is empty" rows below are not about.
    configure(root, turns={"soft": 5, "repeat": 5, "window": 120, "stage_default": 35}, protected_app_paths=["src"])
    (root / "src").mkdir(exist_ok=True)
    open_dispatch(root)
    small = root / "app" / "small.txt"
    small.parent.mkdir(parents=True, exist_ok=True)
    small.write_text("one line\n", encoding="utf-8")
    big = root / "app" / "big.txt"
    big.write_text("x" * 35000, encoding="utf-8")
    return (root, {"tool_name": "Read", "tool_input": {"file_path": str(small)}},
            {"tool_name": "Read", "tool_input": {"file_path": str(big)}})


def count_of(root: Path, event: dict | None = None) -> int:
    import turn_budget
    path = turn_budget.counter_path(SESSION, dict({"session_id": SESSION, "cwd": str(root)}, **(event or {})))
    return json.loads(path.read_text(encoding="utf-8")).get("count")


def test_notice_exit_0_stdout_is_one_json_object() -> None:
    """SC1-6 (t-1309). The notice used to be `block()`: 14 calls of run 12586 were thrown away and repeated, each a
    request over a 200-480K-token context. It now travels in the PreToolUse `additionalContext` (E-1: reaches the model
    on claude 2.1.310), the call runs, and a refusal by another rule keeps its own words and door."""
    root, read_small, _ = notice_world("qa-guard-notice-k2-")
    try:
        # K2, CLI CONTRACT, the Read form (no telemetry_hook): code 0, stdout is exactly one JSON object
        seed_counter(root, 4)
        proc = hook_run(root, read_small)
        check_eq("K2: the fifth Read exits 0 - the call is not stopped", proc.returncode, 0)
        check_eq("K2: stderr is empty", proc.stderr, "")
        body = json.loads(proc.stdout)
        check_eq("K2: stdout is ONE object with only hookSpecificOutput", sorted(body), ["hookSpecificOutput"])
        out = body["hookSpecificOutput"]
        check_eq("K2: it names the PreToolUse event and carries the text, nothing else (no permissionDecision)",
                 sorted(out), ["additionalContext", "hookEventName"])
        check_eq("K2: the event is PreToolUse", out["hookEventName"], "PreToolUse")
        check_in("K2: the text is the window's notice", "this window has made 5", out["additionalContext"])
        check_not_in("K2: no verdict anywhere in stdout", "permissionDecision", proc.stdout)
        check_eq("K2: the counter reads 5", count_of(root), 5)

        # K2, the Write form, through telemetry_hook (as the Write|Edit PreToolUse line runs it)
        seed_counter(root, 4)
        target = root / "app" / "notes.txt"
        proc = hook_run(root, {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "x"}},
                        via_telemetry=True)
        check_eq("K2: the fifth Write through telemetry_hook exits 0", proc.returncode, 0)
        check_eq("K2: stderr is empty there too", proc.stderr, "")
        body = json.loads(proc.stdout)
        check_eq("K2: and stdout is one PreToolUse additionalContext object",
                 (sorted(body), body["hookSpecificOutput"]["hookEventName"], sorted(body["hookSpecificOutput"])),
                 (["hookSpecificOutput"], "PreToolUse", ["additionalContext", "hookEventName"]))
        check_in("K2: with the notice", "this window has made 5", body["hookSpecificOutput"]["additionalContext"])
    finally:
        cleanup(root)


def test_notice_after_another_rules_refusal() -> None:
    """K3 (and F1 of the t-1318 review): another rule refuses the same call - its refusal stays whole, the notice
    follows it, marked, and says nothing about the call having run."""
    root, _, read_big = notice_world("qa-guard-notice-k3-")
    try:
        seed_counter(root, 4, ROLE)
        proc = hook_run(root, dict(ROLE, **read_big))
        check_eq("K3: a refusal by another rule is still exit 2", proc.returncode, 2)
        err = proc.stderr
        marks = [err.find("PRE-TOOL GUARD: reading"), err.find("If you cannot do what this names"),
                 err.find("(Not part of the refusal above.)"), err.find("this agent has made 5")]
        check("K3: stderr holds the refusal, its TRAPPED line, the marker, then the notice - in that order",
              all(m >= 0 for m in marks) and marks == sorted(marks), f"offsets {marks} in:\n{err[:900]}")
        check_eq("K3: stdout is empty (a refusal carries no notice JSON)", proc.stdout, "")
        after = err[marks[2]:] if marks[2] >= 0 else err
        check_not_in("F1: after the marker the notice never says 'no call was stopped' - this call WAS stopped, by the "
                     "other rule", "no call was stopped", after)
        check_in("F1: and it says what is true here too: the turn budget stops no call",
                 "not a refusal: the turn budget stops no call.", after)
    finally:
        cleanup(root)


def test_notice_counts_every_call_and_reaches_the_scout() -> None:
    """K4: an early exit of the Read branch is still a counted call. K5: the scout is told the same way."""
    root, read_small, _ = notice_world("qa-guard-notice-k4-")
    try:
        seed_counter(root, 1, ROLE)
        proc = hook_run(root, dict(ROLE, **read_small))
        check_eq("K4: a Read that leaves the guard early passes", proc.returncode, 0)
        check_eq("K4: and was counted once (1 -> 2)", count_of(root, ROLE), 2)

        seed_counter(root, 4, SCOUT)
        proc = hook_run(root, dict(SCOUT, **read_small))
        check_eq("K5: the scout's fifth call exits 0", proc.returncode, 0)
        check_in("K5: and its notice carries the discovery suffix",
                 "Discovery milestone only; continue required collection.",
                 json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])
        check_eq("K5: nothing on stderr (the old channel the host never showed the model)", proc.stderr, "")
    finally:
        cleanup(root)


def test_flush_notice_exit_paths() -> None:
    """The exit paths of `_flush_notice`, in this process (no project needed: the text is handed over directly)."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Read"}
    out_text, err_text, left = flushed(event, "TURN BUDGET: x", 0)
    check_eq("flush 0: the JSON on stdout, nothing on stderr, nothing left pending",
             (json.loads(out_text)["hookSpecificOutput"]["additionalContext"], err_text, left), ("TURN BUDGET: x", "", ""))
    out_text, err_text, left = flushed(event, "TURN BUDGET: x", 2)
    check_eq("flush 2: stderr only, marked, stdout empty", (out_text, err_text, left),
             ("", "(Not part of the refusal above.) TURN BUDGET: x\n", ""))
    out_text, err_text, left = flushed(event, "TURN BUDGET: x", 1)
    check_eq("flush 1 (the guard itself failed): stderr, unmarked, stdout empty", (out_text, err_text, left),
             ("", "TURN BUDGET: x\n", ""))
    check_eq("flush with nothing pending prints nothing", flushed(event, "", 0), ("", "", ""))
    out_text, _, _ = flushed({"tool_name": "Read"}, "TURN BUDGET: x", 0)
    check_eq("a Claude event that names no hook event still gets the PreToolUse shape (this script is PreToolUse only)",
             json.loads(out_text)["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    # K2-codex: the same event with a Codex marker goes the package's own Codex channel
    import contextlib
    import io
    import host_adapter
    codex = {"hook_event_name": "PreToolUse", "tool_name": "Read", "turn_id": "turn-1"}
    out_text, err_text, _ = flushed(codex, "TURN BUDGET: x", 0)
    via_context = io.StringIO()
    with contextlib.redirect_stdout(via_context):
        host_adapter.context_output(codex, "TURN BUDGET: x")
    check_eq("K2-codex: the output is exactly context_output's", (out_text, err_text), (via_context.getvalue(), ""))
    check_in("K2-codex: and it is the additionalContext JSON", '"additionalContext"', out_text)


def test_notice_output_adapter() -> None:
    """`host_adapter.notice_output`: an event it has no channel for goes to context_output, an empty text prints nothing."""
    import contextlib
    import io
    import host_adapter
    stop = io.StringIO()
    with contextlib.redirect_stdout(stop):
        host_adapter.notice_output({"hook_event_name": "Stop"}, "plain")
        host_adapter.notice_output({"hook_event_name": "PostToolUse"}, "")
    check_eq("an event with no additionalContext channel gets the package's bare text; empty text prints nothing",
             stop.getvalue(), "plain\n")
    post = io.StringIO()
    with contextlib.redirect_stdout(post):
        host_adapter.notice_output({"hook_event_name": "PostToolUse"}, "after — the call\nline two")
    check_in("F5: the helper keeps non-ASCII as it is (ensure_ascii=False), not as a \\u escape", "after — the call",
             post.getvalue())
    check_eq("PostToolUse: the same object with its own event name, text whole (dash and newline)",
             json.loads(post.getvalue()),
             {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "after — the call\nline two"}})


def test_the_notice_is_scoped_to_factory_work() -> None:
    """K7: a session that is not in factory work is neither counted nor told (the scope rule is unchanged)."""
    root = temp_project("qa-guard-notice-scope-")
    try:
        use_project(root)
        configure(root, turns={"soft": 5, "repeat": 5})
        grep = {"tool_name": "Grep", "tool_input": {"pattern": "x"}, "session_id": "s-outside"}
        texts = [noticed(root, grep) for _ in range(6)]
        check_eq("K7: no open dispatch, no agent fields - six calls say nothing", texts, [""] * 6)
        check("K7: and left no counter behind", not (root / "qa-factory" / "state" / "turns").exists())
    finally:
        cleanup(root)


def test_old_counter_files_break_nothing() -> None:
    root = temp_project("qa-guard-budget-old-")
    try:
        use_project(root)
        configure(root, turns={"soft": 5, "repeat": 5})
        open_dispatch(root)
        turns = root / "qa-factory" / "state" / "turns"
        turns.mkdir(parents=True, exist_ok=True)
        # the real file of the run: orchestrator + every role, counted together
        (turns / f"{SESSION}.json").write_text(
            '{"count": 1323, "started": "2026-09-21T09:12:33+00:00", "notified": 1320}',
            encoding="utf-8")
        grep = {"tool_name": "Grep", "tool_input": {"pattern": "x"}}
        check_eq("a pre-0.7.8 session-wide counter does not speak on the first call", noticed(root, grep), "")
        data = json.loads((turns / f"{SESSION}.json").read_text(encoding="utf-8"))
        check_eq("the window's count starts again instead of announcing 1325", data.get("count"), 1)

        (turns / f"{SESSION}.json").write_text("not json", encoding="utf-8")
        check_eq("a counter that is not JSON says nothing and breaks nothing", noticed(root, grep), "")

        # the signature postcompact_reload.py and stage_done.py call
        import turn_budget
        import hooklib
        old = hooklib._PROJECT_ROOT_CACHE
        hooklib._PROJECT_ROOT_CACHE = root
        try:
            turn_budget.reset(SESSION, None, "stage_closed")
            turn_budget.reset(SESSION, {"hook_event_name": "SessionStart", "source": "compact",
                                        "session_id": SESSION}, "compact")
            after = json.loads((turns / f"{SESSION}.json").read_text(encoding="utf-8"))
            check_eq("reset(session, payload, reason) still zeroes the window",
                     (after.get("count"), after.get("reset_reason")), (0, "compact"))
            turn_budget.reset("never-counted", None, "stage_closed")
            check("a reset for a session that never counted creates nothing",
                  not (turns / "never-counted.json").exists())
        finally:
            hooklib._PROJECT_ROOT_CACHE = old
    finally:
        cleanup(root)


def test_logs_are_weighed_not_named() -> None:
    root = temp_project("qa-guard-rawlog-")
    try:
        use_project(root)
        rel = "qa-factory/artifacts/QA-1/evidence/runs/913daa58987420a149f2"
        runs = root / rel
        runs.mkdir(parents=True)
        small = runs / "initial-913daa58-20260921-210206.log"   # the real one weighed 1.2 KB
        small.write_text("ERROR: not found: tests/ui/test_wf.py::test_x[buffer-R3-vs-selected-R1]\n"
                         "(no match in any of [<Module test_wf.py>])\n" * 8, encoding="utf-8")
        junit = runs / "red_probe-071bcb79-20260921-225810.junit.xml"  # 238 bytes in the run
        junit.write_text("<testsuites>" + " " * 214 + "</testsuites>", encoding="utf-8")
        heavy = runs / "repair_verify-2593b25c-20260921-175359.junit.xml"  # 16,106 in the run
        heavy.write_text("x" * 16106, encoding="utf-8")
        role = {"agent_id": "aae5cc5556ffb1926", "agent_type": "qa-factory:qa-automator"}

        def read(path):
            return dict(role, tool_name="Read", tool_input={"file_path": str(path)})

        def shell(command, tool="Bash"):
            return dict(role, tool_name=tool, tool_input={"command": command})

        check_eq("Read of a small evidence log passes", call(root, G.logs_check, read(small)), (0, ""))
        check_eq("Read of a small junit file passes", call(root, G.logs_check, read(junit))[0], 0)
        # CLI CONTRACT, kept as a real child: the same decision, through the real host
        # invocation — a genuine subprocess exit 2 with the refusal text on stderr.
        code, text = hook(root, read(heavy))
        check_eq("Read of a heavy one is refused", code, 2)
        check_in("the refusal says how heavy", "16,106 bytes", text)
        check_in("and where the line is", "8,192 bytes", text)
        check_in("route 1: the summary's error_head", "error_head", text)
        check_in("route 2: --detail by request, which works under a dispatch",
                 "run_suite.py --request <request file> --detail <test>", text)
        check_eq("a log that is not there is the tool's to report",
                 call(root, G.logs_check, read(runs / "initial-gone.log"))[0], 0)

        check_eq("the shell spelling of a small log passes", call(root, G.logs_check, shell(f"cat {rel}/{small.name}"))[0], 0)
        check_eq("and wc over a small pair (refused in the run)",
                 call(root, G.logs_check, shell(f"wc -l {rel}/{small.name} {rel}/{junit.name} 2>&1"))[0], 0)
        check_eq("the shell spelling of a heavy log is refused",
                 call(root, G.logs_check, shell(f"tail -50 {rel}/{heavy.name}"))[0], 2)
        check_eq("PowerShell too", call(root, G.logs_check, shell(f"Get-Content {rel}/{heavy.name}", "PowerShell"))[0], 2)
        parse = (f"cd {root.as_posix()}; python - <<'E'\nimport xml.etree.ElementTree as ET\n"
                 f"root = ET.parse(\"{rel}/{{name}}\").getroot()\nE")
        check_eq("a python one-liner over a small junit passes (refused in the run)",
                 call(root, G.logs_check, shell(parse.format(name=junit.name)))[0], 0)
        check_eq("the same over the heavy one is refused",
                 call(root, G.logs_check, shell(parse.format(name=heavy.name)))[0], 2)
        check_eq("a wildcard is weighed whole", call(root, G.logs_check, shell(f"cat {rel}/*.junit.xml"))[0], 2)
        check_eq("a shell read of a missing log is not blocked",
                 call(root, G.logs_check, shell(f"cat {rel}/initial-gone.log"))[0], 0)

        configure(root, guards={"raw_log_free_bytes": 100})
        check_eq("guards.raw_log_free_bytes lowers the line", call(root, G.logs_check, read(small))[0], 2)
        configure(root, guards={"raw_log_free_bytes": 0})
        check_eq("0 frees nothing (the behaviour before 0.7.8)", call(root, G.logs_check, read(junit))[0], 2)
        check_eq("though a missing file still is not blocked", call(root, G.logs_check, read(runs / "gone.log"))[0], 0)
        configure(root, guards={"raw_log_free_bytes": 32768})
        check_eq("and it raises the line", call(root, G.logs_check, read(heavy))[0], 0)
    finally:
        cleanup(root)


def test_the_handover_form_is_not_rewritten_whole():
    """K-B6: a form is filled through its values file, not rewritten. TP1-13797, 26.09: one run wrote handover
    forms with `Write` 18 times against 14 `--set` calls, and a form runs to 90 fields; SC1-2: the refusal's FIRST
    door is now `<dispatch>.values.yaml` (one Write), no longer a `--set` per field."""
    root = temp_project("qa-guard-handoff-")
    try:
        use_project(root)
        form = root / "qa-factory" / "artifacts" / "QA-9" / "work" / "handoffs" / "S5-qa-code-critic-1.yaml"
        form.parent.mkdir(parents=True, exist_ok=True)
        write = {"tool_name": "Write", "tool_input": {"file_path": str(form), "content": "header:"}}
        code, text = call(root, G.handoff_write_check, write)
        check_eq("the skeleton's own first write is not a rewrite", code, 0)
        form.write_text("header:\n  role: qa-code-critic\n", encoding="utf-8")
        code, text = call(root, G.handoff_write_check, write)
        sibling = form.with_name("S5-qa-code-critic-1.values.yaml").as_posix()
        check_eq("K-B6: a Write over an existing form is refused", code, 2)
        check_in("K-B6: and it names the values file first, whole path", f"  Write {sibling}\n", text)
        check_in("K-B6: a caller that names no role (both doors) also gets the one-call command", "--fix --values - <<'EOF'", text)
        check_not_in("K-B6: `--set` is not advertised any more", "--set", text)
        check_in("K-B6: Edit is still named for one line", "  Edit   (one field's own lines", text)
        check("K-B6: the file door stands before the Edit door", text.index(f"Write {sibling}") < text.index("  Edit   ("))
        nobash = dict(write, agent_id="a1", agent_type="qa-factory:qa-case-critic")
        code, text = call(root, G.handoff_write_check, nobash)
        check_eq("K-B6: a role without Bash is refused the same", code, 2)
        check_in("K-B6: and sees the file door", f"  Write {sibling}\n", text)
        for banned in ("python \"", "<<'EOF'", "--values -", "handoff_check.py"):
            check_not_in(f"K-B6: no {banned!r} for a role that has no Bash (FR-2)", banned, text)
        withbash = dict(write, agent_id="a2", agent_type="qa-factory:qa-code-critic")
        check_in("K-B6: a role with Bash also gets the one-call command",
                 "--fix --values - <<'EOF'", call(root, G.handoff_write_check, withbash)[1])
        edit = {"tool_name": "Edit", "tool_input": {"file_path": str(form), "old_string": "a", "new_string": "b"}}
        check_eq("Edit stays allowed while no values file waits: it changes one line",
                 call(root, G.handoff_write_check, edit)[0], 0)
        other = {"tool_name": "Write", "tool_input": {"file_path": str(root / "notes.yaml"), "content": "x"}}
        check_eq("a yaml that is not a handover form is none of this rule's business",
                 call(root, G.handoff_write_check, other)[0], 0)
        helped = form.with_name("S5-qa-code-critic-1.help.yaml")
        helped.write_text("x: 1\n", encoding="utf-8")
        check_eq("the conductor's .help file is still a form-like file: a Write over it is refused as before",
                 call(root, G.handoff_write_check, {"tool_name": "Write", "tool_input": {"file_path": str(helped), "content": "y: 2"}})[0], 2)
    finally:
        cleanup(root)


# ---------------------------------------------------------------------- SC1-2 B2: the values file's door
S4 = "s4-case-critic-to-designer"
DISPATCH = "S4-qa-case-critic-1"
NOBASH = {"agent_id": "a1", "agent_type": "qa-factory:qa-case-critic"}        # tools: Read, Grep, Glob, Write, Edit
WITHBASH = {"agent_id": "a2", "agent_type": "qa-factory:qa-code-critic"}      # tools: ... Bash ...


def s4_values(omit=(), **replace) -> str:
    """Every field the case critic fills in a one-row, no-finding-needed review, as `path: value` lines. Not given:
    `review.findings_file` and `scope[0].case_version` (code derives them from files this story does not have), and
    `review.rollcall` (code derives it, part C) and the claim about it (code measures it, part C)."""
    lines = {
        "inputs_read[0].path": "work/handoffs/S3-qa-case-designer-1.yaml", "inputs_read[0].version": "abc123",
        "header.window": "TC-1", "header.verdict": "ok", "review.outcome": "approved", "review.rounds_used": "1",
        "review.rubric_covered": '"oracle, preconditions"', "scope[0].id": "TC-1", "scope[0].state": "approved",
        "scope[0].reason": "fine", "findings[0].id": "F-1", "findings[0].case": "TC-1",
        "findings[0].problem": "the Then names no value", "findings[0].expected": "the Then states the status code",
        "findings[0].fix": "add the status code", "findings[0].dimension": "oracle", "findings[0].blocking": "false",
        "findings[0].replacement.new": "Then the status is 200",
        "stage_acceptance.failure_class": "spec", "stage_acceptance.quote": '"the Then names no value (work/cases/TC-1.md#then)"',
        "questions[0].question": '"Is a 200 the only status the case may expect?"', "questions[0].read": '["work/cases/TC-1.md#then"]',
        "questions[0].recommendation": '"go on with 200 meanwhile"', "questions[0].options[0].reading": '"only 200"',
        "questions[0].options[0].if_chosen": '"the Then states 200"', "questions[0].options[1].reading": '"200 or 204"',
        "questions[0].options[1].if_chosen": '"the Then states both codes"', "questions[0].severity": "minor",
        "questions[0].owner_role": "qa-case-designer",
        "claims.every_case_of_the_review_scope_has_a_row": "true", "claims.every_finding_names_expected_and_check": "true",
        "claims.no_case_outside_the_review_scope_was_reviewed": "true",
    }
    lines.update(replace)
    return "".join(f"{path}: {value}\n" for path, value in lines.items() if path not in omit)


def handoff_form(root: Path, dispatch: str = DISPATCH, stage: str = "S4", role: str = "qa-case-critic",
                 to: str = "qa-case-designer") -> Path:
    """A fresh form, started the way the factory starts it (`handoff_init.py`), in the story QA-9 of this project."""
    art = root / "qa-factory" / "artifacts" / "QA-9"
    (art / "work").mkdir(parents=True, exist_ok=True)
    done = run_script("handoff_init.py", "--task", "QA-9", "--stage", stage, "--role", role, "--to", to,
                      "--dispatch", dispatch, "--task-root", str(art))
    check_eq(f"scaffold: handoff_init made {dispatch}", done.returncode, 0)
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


def values_write(form: Path, content: str, who: dict | None = None, suffix: str = ".values.yaml") -> dict:
    target = form.with_name(form.name[:-len(".yaml")] + suffix)
    return dict(who or NOBASH, tool_name="Write", tool_input={"file_path": str(target), "content": content})


def test_a_values_write_that_leaves_the_form_not_ready_is_refused_with_one_block():
    """K-B7: a role without Bash cannot run `handoff_check`; its ONE Write of the values file is answered in the same
    turn, with the lines that passed (M-4) and the line to fix, and with no command it cannot run (FR-2)."""
    root = temp_project("qa-guard-b7-")
    try:
        use_project(root)
        form = handoff_form(root)
        sibling = form.with_name(f"{DISPATCH}.values.yaml")
        code, text = call(root, G.handoff_write_check, values_write(form, s4_values(**{"header.verdict": "contradiction"})))
        check_eq("K-B7: a word outside the list is refused", code, 2)
        check_in("K-B7: it says nothing was written", "nothing was written", text)
        check_in("K-B7: the good line the role sent comes back verbatim (M-4)", "\nheader.window: TC-1\n", text)
        check_in("K-B7: and a second one, from the other end of the file", "\nclaims.no_case_outside_the_review_scope_was_reviewed: true\n", text)
        import handoff
        check_in("K-B7: the line to fix carries the allowed words (the vocabulary's own list)",
                 "\nheader.verdict: <" + "|".join(handoff.allowed("header_verdicts")) + ">", text)
        check_not_in("K-B7: the wrong word is not echoed back as a value", "header.verdict: contradiction", text)
        check_in("K-B7: the door says to rewrite the file whole, whole path", f"Rewrite {sibling.as_posix()} WHOLE", text)
        for banned in ("python", "<<'EOF'", "--values -", "--set", "handoff_help.py"):
            check_not_in(f"K-B7: nothing a role without Bash cannot run ({banned!r})", banned, text)
        check_in("K-B7: what it cannot fill goes to blocked in the same file", "fill blocked.field and blocked.problem in the same values file", text)
        check("K-B7: the guard wrote nothing", not sibling.exists())
        # a line that does not parse: nothing is applied, every line that did parse comes back
        code, text = call(root, G.handoff_write_check, values_write(form, "header.window: TC-1\nthis line has no colon\nheader.verdict: ok\n"))
        check_eq("K-B7: a text that does not parse is refused too", code, 2)
        check_in("K-B7: with the line number", "line 2", text)
        check_in("K-B7: and the good lines back", "\nheader.verdict: ok\n", text)
        # a role with Bash is told the same, through the same function: the command and the file door
        code, text = call(root, G.handoff_write_check, values_write(form, s4_values(**{"header.verdict": "contradiction"}), WITHBASH))
        check_eq("K-B7: the block is the same for a role that has Bash", code, 2)
        # (the form says qa-case-critic, so the doors follow the FORM's role, not the caller's)
        check_in("K-B7: and it is the one function's text", "handoff_check: s4-case-critic-to-designer is not ready", text)
    finally:
        cleanup(root)


def test_the_guards_refusals_teach_the_indexed_row_form():
    """K10/K16 (HF8-7, AR-18, FR-2): the guard's block is `refusal_text` over `values_report`, which now carries the contract
    to the parser: a values file with `scope.1.id: TC-2` is refused with `"scope[1].id"`, the role's own line first and
    once. A Write over the form, and a Write of the trace file, name the indexed form too, and the registry's `call`
    line (`PRE-TOOL GUARD: ...`) is untouched."""
    root = temp_project("qa-guard-hf87-")
    try:
        use_project(root)
        form = handoff_form(root)
        code, text = call(root, G.handoff_write_check, values_write(form, "scope[0].state: approve\nscope.1.id: TC-2\n"))
        check_eq("K10: refused", code, 2)
        check_in("K10: with the indexed form", '"scope[1].id": <', text)
        check_eq("K10: the role's line is there once", text.count("\nscope[0].state: approve\n"), 1)
        check("K10: and first among the skeleton lines", text.index("\nscope[0].state: approve\n") < text.index('\n"scope[1].id": <'), "")
        code, text = call(root, G.handoff_write_check, values_write(form, "x", suffix=".yaml"))
        check_eq("K16: a Write over the form is refused", code, 2)
        check_in("K16: and it names the indexed form", '"<list>[0].<field>": value', text)
        check_in("K16: the registry's call line stays", "PRE-TOOL GUARD: the handover form is filled through its values file", text)
        code, text = call(root, G.handoff_write_check, values_write(form, "x", suffix=".values.applied.yaml"))
        check_eq("K16: a Write of the trace is refused", code, 2)
        check_in("K16: and names the indexed form", '"<list>[0].<field>": value', text)
    finally:
        cleanup(root)


def test_a_green_values_write_lands():
    """K-B8: M-9 - the guard asks for nothing only code can fill. `review.findings_file` and `scope[0].case_version`
    are blank here (their sources are not on disk) and a role without Bash cannot produce them; refusing the file
    for them would lock the role (FR-2, FR-11). `finish` fills them or refuses them with its own reason."""
    import handoff
    import handoff_check as H
    root = temp_project("qa-guard-b8-")
    try:
        use_project(root)
        form = handoff_form(root)
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        handoff.set_value(doc, "review.findings_file", "<fill>")
        form.write_text(doc.text(), encoding="utf-8")
        text = s4_values()
        control = H.parse_values(text)
        merged = H.apply_values(handoff.parse(form.read_text(encoding="utf-8")), S4, control[0])[0]
        raw = H.check(merged, S4, H.Artifacts(form.parent.parent.parent, dispatch=form.stem), fix=True, use_judge=False)[2]
        blank = sorted(p.path for p in raw if p.kind == "blank")
        check_in("K-B8: the control - check(fix=True) alone WOULD refuse the file for review.findings_file", "review.findings_file", blank)
        check_in("K-B8: and for scope[0].case_version", "scope[0].case_version", blank)
        code, out = call(root, G.handoff_write_check, values_write(form, text))
        check_eq("K-B8: the green file lands (exit 0)", (code, out), (0, ""))
        check_eq("K-B8: and the form was not touched by the guard", handoff.parse(form.read_text(encoding="utf-8")).text(), doc.text())
    finally:
        cleanup(root)


def test_a_values_file_that_fills_blocked_problem_lands_even_with_other_fields_open():
    """K-B9: FR-57 - a role that cannot fill a field says so in `blocked`; the file that says it is never a dead end,
    whatever else is wrong in it. The control: the same file without those two lines is refused."""
    root = temp_project("qa-guard-b9-")
    try:
        use_project(root)
        form = handoff_form(root)
        bad = s4_values(**{"header.verdict": "contradiction"})
        check_eq("K-B9: control - the file with a bad word is refused", call(root, G.handoff_write_check, values_write(form, bad))[0], 2)
        door = bad + "blocked.field: review.outcome\nblocked.problem: the findings file cannot be read: permission denied\n"
        check_eq("K-B9: with blocked.problem filled it lands", call(root, G.handoff_write_check, values_write(form, door)), (0, ""))
        # the door is ONE shape: a file that does not parse is still refused, with its good lines back (the role rewrites it)
        broken = door + "this line has no colon\n"
        code, text = call(root, G.handoff_write_check, values_write(form, broken))
        check_eq("K-B9: a file that does not parse is refused even with the door in it", code, 2)
        check_in("K-B9: and the door line comes back with the good ones", "\nblocked.problem: the findings file cannot be read: permission denied\n", text)
    finally:
        cleanup(root)


def test_a_placeholder_blocked_problem_does_not_open_that_door():
    """K-B10: `blocked.problem: <...>` (the template's own text), an empty value, or a quoted nothing says nothing:
    FR-59 - an unknown is not a pass."""
    root = temp_project("qa-guard-b10-")
    try:
        use_project(root)
        form = handoff_form(root)
        bad = s4_values(**{"header.verdict": "contradiction"})
        for shown, line in (("the template placeholder", "blocked.problem: <what the role tried and what refused it, verbatim>"),
                            ("a quoted nothing", 'blocked.problem: ""'), ("<fill>", "blocked.problem: <fill>")):
            code, text = call(root, G.handoff_write_check, values_write(form, bad + "blocked.field: review.outcome\n" + line + "\n"))
            check_eq(f"K-B10: {shown} does not open the door", code, 2)
    finally:
        cleanup(root)


def test_only_the_exact_values_yaml_suffix_is_exempt():
    """K-B11: MB2 - the exemption is for `<stem>.values.yaml` and nothing that merely contains `.values`: a form-like
    `x.values.yml` that exists is still a Write over a form, and `x.values.yaml.bak` is not a handover file at all."""
    root = temp_project("qa-guard-b11-")
    try:
        use_project(root)
        form = handoff_form(root)
        bad = s4_values(**{"header.verdict": "contradiction"})
        code, text = call(root, G.handoff_write_check, values_write(form, bad, suffix=".values.yml"))
        check_eq("K-B11: a values.yml that does not exist is not checked as a values file (the first write of a form-like file)", (code, text), (0, ""))
        form.with_name(f"{DISPATCH}.values.yml").write_text("x: 1\n", encoding="utf-8")
        code, text = call(root, G.handoff_write_check, values_write(form, bad, suffix=".values.yml"))
        check_eq("K-B11: a values.yml that exists is a Write over a form-like file: refused", code, 2)
        check_in("K-B11: by the rewrite rule", "filled through its values file, not rewritten", text)
        check_not_in("K-B11: not by the values check", "leave the form not ready", text)
        check_eq("K-B11: `.values.yaml.bak` is not a handover file: not checked", call(
            root, G.handoff_write_check, values_write(form, bad, suffix=".values.yaml.bak"))[0], 0)
        check_eq("K-B11: and `.values.yaml` itself IS checked", call(root, G.handoff_write_check, values_write(form, bad))[0], 2)
    finally:
        cleanup(root)


def test_the_guard_never_asks_the_judge():
    """K-B12: MB6 - a word beside the list is one `--fix` would send to the judge; the guard cannot (it is a hook, it
    costs a model call per Write) and refuses it instead. The judge is stubbed to blow up: a call would be swallowed
    by the guard's fail-open and the Write would land - so the refusal itself proves it was not asked."""
    import handoff_check as H

    class NoJudge:
        asked = 0

        @staticmethod
        def active():
            return True

        @staticmethod
        def ask(*_a, **_k):
            NoJudge.asked += 1
            raise AssertionError("the guard must not ask the judge")

    root = temp_project("qa-guard-b12-")
    try:
        use_project(root)
        form = handoff_form(root)
        saved = H.judge
        H.judge = NoJudge
        try:
            code, text = call(root, G.handoff_write_check, values_write(form, s4_values(**{"header.verdict": "contradiction"})))
        finally:
            H.judge = saved
        check_eq("K-B12: the judge was not asked", NoJudge.asked, 0)
        check_eq("K-B12: and the word is refused", code, 2)
    finally:
        cleanup(root)


def test_no_form_beside_the_values_file_the_write_lands():
    """K-B13: E-noform - nothing could apply a values file with no form beside it, and `finish` of the real dispatch
    refuses the form that is not there; the guard does not lock a write it cannot check (AR-28: the transition checks)."""
    root = temp_project("qa-guard-b13-")
    try:
        use_project(root)
        art = root / "qa-factory" / "artifacts" / "QA-9" / "work" / "handoffs"
        art.mkdir(parents=True)
        event = dict(NOBASH, tool_name="Write", tool_input={"file_path": str(art / "S4-nothing-1.values.yaml"), "content": "header.verdict: nonsense\n"})
        check_eq("K-B13: the write lands", call(root, G.handoff_write_check, event), (0, ""))
    finally:
        cleanup(root)


def test_the_guard_passes_a_values_write_through_the_whole_chain():
    """K-B14: P5 - the exemption lifts the form-rewrite rule only. Through the REAL hook (every rule of `main`, in the
    order they run): a green file of a role without Bash lands, a file not ready is refused by THIS check, and a values
    file outside any story is still stopped by the rules that always stop it."""
    root = temp_project("qa-guard-b14-")
    try:
        use_project(root)
        # The boundary is declared, as onboarding leaves it: the guard says once per session that an EMPTY
        # protected_app_paths leaves P-00 unenforced (guard_app_under_test.check), and that line is not what this
        # row is about. The first call of a fresh machine prints it (the marker is in the OS temp dir).
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["protected_app_paths"] = ["src"]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (root / "src").mkdir()
        form = handoff_form(root)
        open_dispatch(root)
        code, text = hook(root, values_write(form, s4_values()))
        check_eq("K-B14: a green file passes the whole chain (the real host invocation)", (code, text.strip()), (0, ""))
        code, text = hook(root, values_write(form, s4_values(**{"header.verdict": "contradiction"})))
        check_eq("K-B14: a file not ready is refused by the chain", code, 2)
        check_in("K-B14: by the values check", "these handover values leave the form not ready", text)
    finally:
        cleanup(root)


def test_an_edit_of_a_form_whose_values_file_waits_is_refused():
    """K-B15: M-5 - the waiting file is applied over the form at the next check, so an Edit of the same field would
    be lost. The Edit is refused with the door (put the field into the file); a role with Bash may apply first."""
    import handoff_check as H
    from host_adapter import mutation_events
    root = temp_project("qa-guard-b15-")
    try:
        use_project(root)
        form = handoff_form(root)
        sibling = form.with_name(f"{DISPATCH}.values.yaml")
        edit = dict(NOBASH, tool_name="Edit", tool_input={"file_path": str(form), "old_string": "header:", "new_string": "header:"})
        check_eq("K-B15: control - with no values file waiting, the Edit passes", call(root, G.handoff_write_check, edit), (0, ""))
        sibling.write_text("header.window: TC-1\n", encoding="utf-8")
        check_eq("K-B15: the guard's sibling name is the one handoff_check.sibling_values gives", sibling, H.sibling_values(form))
        code, text = call(root, G.handoff_write_check, edit)
        check_eq("K-B15: with a values file waiting, the Edit is refused", code, 2)
        check_in("K-B15: it names the waiting file by name and whole path", f"{DISPATCH}.values.yaml is waiting to be applied to this form", text)
        check_in("K-B15: the whole path", sibling.as_posix(), text)
        check_in("K-B15: and says why", "an Edit here would be lost", text)
        check_in("K-B15: and the door - put the field into the file", "rewrite it whole, with the field added", text)
        for banned in ("python", "--fix"):
            check_not_in(f"K-B15: a role without Bash is shown no {banned!r} (FR-2)", banned, text)
        code, text = call(root, G.handoff_write_check, dict(edit, **WITHBASH))
        check_eq("K-B15: a role with Bash is refused the same", code, 2)
        check_in("K-B15: and may apply the file first", f"--file {form.as_posix()} --fix, then Edit", text)
        # the values file itself, and the conductor's .help file, are not the form
        own = dict(edit, tool_input={"file_path": str(sibling), "old_string": "a", "new_string": "b"})
        check_eq("K-B15: an Edit of the values file itself is not checked (E20)", call(root, G.handoff_write_check, own), (0, ""))
        # Codex: Update File is an Edit, Add File is a Write
        patch = "*** Begin Patch\n*** Update File: {p}\n@@\n-a\n+b\n*** End Patch"
        event = {"tool_name": "apply_patch", "cwd": str(root), "tool_input": {"command": patch.format(p=form)}}
        refused = [call(root, G.handoff_write_check, operation) for operation in mutation_events(event)]
        check_eq("K-B15: Codex apply_patch Update File of the form is refused the same", [code for code, _ in refused], [2])
        add = "*** Begin Patch\n*** Add File: {p}\n+header.verdict: nonsense\n*** End Patch"
        event = {"tool_name": "apply_patch", "cwd": str(root), "tool_input": {"command": add.format(p=sibling)}}
        refused = [call(root, G.handoff_write_check, operation) for operation in mutation_events(event)]
        check_eq("K-B15: and Add File of the values file is a Write: checked, refused", [code for code, _ in refused], [2])
        check_in("K-B15: by the values check", "leave the form not ready", refused[0][1])
    finally:
        cleanup(root)


def test_the_applied_and_stale_names_are_codes():
    """K-B17: MB10 - `.values.applied.yaml` and `.values.stale.yaml` are traces code leaves; a role that writes one
    is told the file it means, whether the name exists or not (it has no legitimate writer among the roles)."""
    root = temp_project("qa-guard-b17-")
    try:
        use_project(root)
        form = handoff_form(root)
        sibling = form.with_name(f"{DISPATCH}.values.yaml")
        for suffix in (".values.applied.yaml", ".values.stale.yaml"):
            event = values_write(form, "header.window: TC-1\n", suffix=suffix)
            code, text = call(root, G.handoff_write_check, event)
            check_eq(f"K-B17: a Write of {suffix} (no such file yet) is refused", code, 2)
            check_in(f"K-B17: {suffix}: it is code's", "is written by code", text)
            check_in(f"K-B17: {suffix}: and names the file the role means", sibling.as_posix(), text)
            Path(event["tool_input"]["file_path"]).write_text("header.window: TC-1\n", encoding="utf-8")
            check_eq(f"K-B17: and when {suffix} exists", call(root, G.handoff_write_check, event)[0], 2)
        applied = form.with_name(f"{DISPATCH}.values.applied.yaml")
        check_eq("K-B17: an Edit of a trace is none of this rule's business", call(
            root, G.handoff_write_check, dict(NOBASH, tool_name="Edit", tool_input={"file_path": str(applied), "old_string": "a", "new_string": "b"})), (0, ""))
    finally:
        cleanup(root)


def test_the_guard_parses_once_reads_the_form_once_and_prints_the_one_functions_text():
    """K2/K3 (SC2-13, AR-13, AR-15, AR-18): one values write is ONE parse, one application per pair and ONE read of the
    form - whether the file is refused or lands through the door - and the block is, byte for byte, the text
    `refusal_text` builds over what `values_report` returned."""
    import handoff_check as H
    root = temp_project("qa-guard-sc213-")
    try:
        use_project(root)
        form = handoff_form(root)
        bad = s4_values(**{"header.verdict": "contradiction"})
        door = bad + "blocked.field: review.outcome\nblocked.problem: the findings file cannot be read: permission denied\n"
        real_parse, real_apply, real_read = H.parse_values, H.apply_values, Path.read_text
        seen = {"parse": 0, "apply": 0, "read": 0}
        current = {"text": ""}

        def parse(*a, **k):
            if a and a[0] == current["text"]:                  # the ROLE's text; `_placeholder` parses its own hints
                seen["parse"] += 1
            return real_parse(*a, **k)

        def apply(*a, **k):
            seen["apply"] += 1
            return real_apply(*a, **k)

        def read(self, *a, **k):
            if Path(self).resolve() == form.resolve():
                seen["read"] += 1
            return real_read(self, *a, **k)

        for shown, text, code_expected in (("refused", bad, 2), ("through the door", door, 0)):
            for key in seen:
                seen[key] = 0
            current["text"] = text
            H.parse_values, H.apply_values, Path.read_text = parse, apply, read
            try:
                code, _out = call(root, G.handoff_write_check, values_write(form, text))
            finally:
                H.parse_values, H.apply_values, Path.read_text = real_parse, real_apply, real_read
            pairs = len(real_parse(text)[0])
            check_eq(f"K2: {shown}: the verdict is as before", code, code_expected)
            check_eq(f"K2: {shown}: parse_values once", seen["parse"], 1)
            check(f"K2: {shown}: apply_values once per pair, no more ({seen['apply']} of {pairs})", seen["apply"] == pairs, "")
            check_eq(f"K2: {shown}: the form is read once", seen["read"], 1)
        code, text = call(root, G.handoff_write_check, values_write(form, bad))
        report = H.values_report(form, bad)
        direct = ("PRE-TOOL GUARD: these handover values leave the form not ready; nothing was written.\n"
                  + H.refusal_text(form, report.contract, report.problems, report.role, kept=report.kept))
        import hooklib
        check_eq("K3: the block is the one function's text, byte for byte (and the guard's own closing line)", text,
                 (direct + "\n" + hooklib.TRAPPED).strip())
    finally:
        cleanup(root)


def test_the_guard_never_raises_on_what_a_role_can_write():
    """K-bat (SC2-13, E1-E10; P1: the guard is a help, `--fix` checks again): magnitude (10 000 lines, 200 000 brackets),
    nesting, encoding (BOM + CRLF, an escaped non-ASCII key, a form that is not UTF-8), empty and broken input, a form
    with no `contract:` line (E6) and a `check` that throws (E10): the answer is 0 or 2, never a trace."""
    import handoff_check as H
    root = temp_project("qa-guard-bat-")
    try:
        use_project(root)
        form = handoff_form(root)
        escaped = f"scope[0].{chr(0x438)}{chr(0x434)}: x\n"      # by code point: the package carries no Cyrillic (FR-30)
        inputs = {
            "ten thousand good lines": "header.window: TC-1\n" * 10000,
            "ten thousand bad lines": "".join(f"bad line {n}\n" for n in range(10000)),
            "deep brackets": "scope: " + "[" * 200000,
            "deep closed": "scope: " + "[" * 200000 + "]" * 200000,
            "json depth": "[" * 200000,
            "BOM and CRLF": "﻿header.verdict: ok\r\nheader.window: TC-1\r\n",
            "an escaped non-ASCII key": escaped,
            "empty": "",
            "comments": "# only\n# comments\n",
            "not a mapping": '{"scope": [{"id": "x"}]}',
        }
        for shown, text in inputs.items():
            code, out = call(root, G.handoff_write_check, values_write(form, text))
            check(f"K-bat: {shown}: 0 or 2, no trace ({code})", code in (0, 2), out[-200:])
        # E6: a form that names no contract - `apply_values` cannot read one; the guard lets the write through
        original = form.read_text(encoding="utf-8")
        form.write_text("\n".join(line for line in original.splitlines() if not line.startswith("contract:")) + "\n", encoding="utf-8")
        check_eq("K-bat: E6 a form with no contract passes (P1)", call(root, G.handoff_write_check, values_write(form, "header.verdict: contradiction\n"))[0], 0)
        check_eq("K-bat: E6 and an unparseable text on it passes too", call(root, G.handoff_write_check, values_write(form, "no colon\n"))[0], 0)
        # E9: bytes that are not UTF-8 in the form are read with replacement; nothing on disk changes
        form.write_bytes(original.encode("utf-8") + b"\n# \xff\xfe not utf-8\n")
        before = form.read_bytes()
        code, _out = call(root, G.handoff_write_check, values_write(form, "header.verdict: contradiction\n"))
        check("K-bat: E9 a form with stray bytes: 0 or 2", code in (0, 2), str(code))
        check_eq("K-bat: E9 and the guard rewrote nothing", form.read_bytes(), before)
        # E10: `check` throws
        form.write_text(original, encoding="utf-8")
        real = H.check

        def boom(*_a, **_k):
            raise RuntimeError("check blew up")

        H.check = boom
        try:
            check_eq("K-bat: E10 a check that throws passes (P1)", call(root, G.handoff_write_check, values_write(form, "header.verdict: contradiction\n"))[0], 0)
        finally:
            H.check = real
    finally:
        cleanup(root)


def main() -> None:
    test_the_guard_parses_once_reads_the_form_once_and_prints_the_one_functions_text()
    test_the_guard_never_raises_on_what_a_role_can_write()
    test_the_handover_form_is_not_rewritten_whole()
    test_a_values_write_that_leaves_the_form_not_ready_is_refused_with_one_block()
    test_the_guards_refusals_teach_the_indexed_row_form()
    test_a_green_values_write_lands()
    test_a_values_file_that_fills_blocked_problem_lands_even_with_other_fields_open()
    test_a_placeholder_blocked_problem_does_not_open_that_door()
    test_only_the_exact_values_yaml_suffix_is_exempt()
    test_the_guard_never_asks_the_judge()
    test_no_form_beside_the_values_file_the_write_lands()
    test_the_guard_passes_a_values_write_through_the_whole_chain()
    test_an_edit_of_a_form_whose_values_file_waits_is_refused()
    test_the_applied_and_stale_names_are_codes()
    test_counter_is_per_dispatch()
    test_notice_exit_0_stdout_is_one_json_object()
    test_notice_after_another_rules_refusal()
    test_notice_counts_every_call_and_reaches_the_scout()
    test_flush_notice_exit_paths()
    test_notice_output_adapter()
    test_the_notice_is_scoped_to_factory_work()
    test_old_counter_files_break_nothing()
    test_logs_are_weighed_not_named()
    finish("guard: per-dispatch turn counter, raw logs by weight, the handover values file's door")


if __name__ == "__main__":
    main()
