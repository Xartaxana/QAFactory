"""Counts the tool calls of one host agent and says so out loud when they add up.

Turn economy is the one rule in `common-rules.md` that nothing enforced. Its own text
carried the measurement — one phase in a single continuous dispatch cost ~22.6M tokens over
146 turns, the same work split into three fresh windows ~9.7M — and roles read it and ran
140, 126, 117, 109 and 105 turns anyway on TP1-14336. They could not have done better:
a role has no way to know how many turns it has spent. Nobody counts.

Why a notice and not a refusal. Cost inside one window grows as the square of its turns, so
the useful moment to speak is the middle, not the end; and a hard cap applied to the wrong
reader would strand a run rather than shorten it. The budget states the number beside the
call, which runs, and lets the work continue.

One counter per host AGENT, and one for the orchestrator. The agent, not the dispatch: an agent the
orchestrator continues with SendMessage keeps its context and is billed for it whichever dispatch it is on
(run 14857: four `S6-qa-runner-N` dispatches ran in one agent, and each was told "this dispatch has made N").
The notice says so, and how many dispatches the receipt `story_step bind` keeps ties to the agent
(`bound_count`, read only when a notice is due); the host cannot cut the count at a dispatch, because the
boundary is visible to code only at `bind`, which comes after the dispatch returned. A tool event fired inside a subagent
call carries the host's `agent_id` (and `agent_type`); the orchestrator's own calls carry
neither. That was checked, not assumed: the hook receipts of session 57cf578c
(TP1-15045) hold `agent_id: acb310e4e528a3eaa` on a role's tool event — the very id of
that role's transcript, `subagents/agent-acb310e4e528a3eaa.jsonl`. Until 0.7.8 the counter
was keyed by `session_id` alone, which a role SHARES with the orchestrator and with every
role before it: in that session a fresh role was told on its first minute "930 tool calls,
hand back" — 43 such interruptions over 16 dispatches, each about somebody else's calls —
and critic-4 obeyed at 71 calls of its own, which cost one more critic dispatch ($5.48,
58 min). So a role's notice counts its own dispatch and carries only the role's advice; the
orchestrator's counts its window — role calls no longer inflate it — and carries only the
orchestrator's.

Called by guard_pre_tool.py on every event it sees. State is disposable — delete the
directory and every counter starts again:
  `<project>/qa-factory/state/turns/<session>.json`            the orchestrator's window
  `<project>/qa-factory/state/turns/dispatches/<agent>.json`   one host agent (the folder keeps its name)
The dispatch counters sit one directory down on purpose: `window_budget.live_session()`
takes the newest `turns/*.json` for "this window", and a role working in the background
must never win that race.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import state_dir  # noqa: E402

DEFAULT_SOFT = 60
DEFAULT_REPEAT = 30
# Written into every counter this version creates. A `<session>.json` without it was counted
# by the session-wide scheme (the orchestrator's calls PLUS every role's — 1323 on
# TP1-15045), so it is not a number about this window, and the count starts again
# instead of being announced as one.
SCHEME = 2
DISPATCH_DIR = "dispatches"
DISPATCH_KEEP_S = 3 * 24 * 3600
EXPENSIVE_TOOLS = ("Bash", "PowerShell", "Read", "Write", "Edit", "Agent", "Task", "Grep", "Glob")


def budget(cfg: dict) -> tuple:
    """(soft, repeat) from config.turns, with the shipped defaults."""
    block = (cfg or {}).get("turns") or {}
    try:
        soft = int(block.get("soft") or DEFAULT_SOFT)
    except Exception:
        soft = DEFAULT_SOFT
    try:
        repeat = int(block.get("repeat") or DEFAULT_REPEAT)
    except Exception:
        repeat = DEFAULT_REPEAT
    return max(soft, 5), max(repeat, 5)


def _safe(value) -> str:
    return "".join(c for c in str(value or "") if c.isalnum() or c in "-_")[:64]


def dispatch_key(event: dict | None) -> str:
    """The key of the host agent this event belongs to, "" for the orchestrator.

    `agent_id` is the host's own id of one subagent run: unique per agent, and unchanged
    when the orchestrator continues the same agent with SendMessage - which is right, it is
    the same context being billed, so one agent that took several dispatches is ONE counter
    (the notice says how many dispatches it spans: `bound_count`). A host that names the role (`agent_type`) but sends no
    id still gets a counter apart from the orchestrator's, shared by that role within the
    session: coarser, but never again the whole session's total."""
    event = event or {}
    agent = _safe(event.get("agent_id"))
    if agent:
        return agent
    role = _safe(str(event.get("agent_type") or event.get("agent_name") or "").strip())
    if role:
        return f"{_safe(event.get('session_id')) or 'unknown'}--{role}"
    return ""


def counter_path(session: str, event: dict | None = None) -> Path:
    """The counter this event counts into: its dispatch's when the event carries one, the
    session's (the orchestrator's window) otherwise — and for every caller that has no
    event at all (`stage_done.py`, `window_budget.py`, a test)."""
    turns = state_dir(event) / "state" / "turns"
    key = dispatch_key(event)
    if key:
        return turns / DISPATCH_DIR / f"{key}.json"
    return turns / f"{_safe(session) or 'unknown'}.json"


def read_count(path: Path) -> dict:
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def due(count: int, soft: int, repeat: int) -> bool:
    """True on the call that crosses the soft line, and every `repeat` calls after it."""
    return count >= soft and (count - soft) % repeat == 0


def reset(session: str, event: dict | None = None, reason: str = "") -> None:
    """Zero this session's counter at a real window boundary.

    Claude Code keeps ONE session id across a `/compact` and across the orchestrator being
    re-invoked with `/qa-factory:qa-story` in the same window, so a counter keyed only by
    `session_id` (as this file always was) keeps climbing as if nothing had changed. On
    TP1-15045 one counter survived a compact and two fresh `/qa-story` starts —
    `{"count": 94, "started": "...00:30:17", "notified": 90}` — and the stale total came
    back on the very next qualifying tool call as a notice worded "this dispatch has made
    90 tool calls", handed to the orchestrator as a hook denial on the SECOND call of a
    stage it had only just re-opened (one wasted turn re-issuing the identical call).

    Called from two real boundaries, neither owned by this file: `postcompact_reload.py`
    (this package, `SessionStart` with `source: compact`) and `stage_done.py` right after it
    closes a stage. A reset that cannot be written costs one stale
    notice later, never a block now.

    Both boundaries are the orchestrator's, so this zeroes the WINDOW counter. A dispatch
    counter is never reset — its dispatch simply ends, and the next one has a new
    `agent_id` — so the boundary only sweeps the ones nobody has touched for days."""
    path = counter_path(session, event)
    data = {"count": 0, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notified": 0, "scheme": SCHEME}
    if reason:
        data["reset_reason"] = reason
    try:
        if path.exists():  # else nothing counted yet; and a hook never creates qa-factory/
            path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    _sweep_dispatch_counters(state_dir(event) / "state" / "turns" / DISPATCH_DIR)


def _sweep_dispatch_counters(folder: Path) -> None:
    """Deletes dispatch counters older than DISPATCH_KEEP_S. A role of a live window is
    never that old, and losing one would only restart a count."""
    try:
        import time
        limit = time.time() - DISPATCH_KEEP_S
        for stale in folder.glob("*.json"):
            try:
                if stale.stat().st_mtime < limit:
                    stale.unlink()
            except Exception:
                continue
    except Exception:
        pass


def open_stage(event: dict | None = None) -> tuple:
    """(task, stage) of a stage that is `running` right now, ("", "") if none.

    Only consulted when a notice is already due, so the hot path never pays for it."""
    try:
        import window_budget
        work = window_budget.open_work(state_dir(event))
        return str(work.get("task") or ""), str(work.get("stage") or "")
    except Exception:
        return "", ""


def bound_count(event: dict | None) -> tuple:
    """(number of dispatches the host agent of this event has been bound to, the latest one), (0, "") when that
    is not known. DC1-11: the counter is the AGENT's (an agent continued with SendMessage carries one context
    through several dispatches, run 14857: `S6-qa-runner-1..4` in one agent), and the notice says how many
    dispatches that count spans, from the receipt `story_step bind` keeps (`host_dispatch.bound_dispatches`).

    The number may be too LOW, never too high (FR-41: an unknown is not printed as a fact): it is read only when
    the receipt `enrich` found for the event answers to the event's own `agent_id` (`binding_names`) - a
    receipt found by `session_id` (the driver's) belongs to somebody else's dispatches - and whatever fails
    in it is 0. Called only when a notice is due, never on the hot path."""
    try:
        import host_dispatch
        agent, path = (event or {}).get("agent_id"), (event or {}).get("host_binding")
        if not agent or not path:
            return 0, ""
        receipt = hooklib.read_json(path, {}, kind=dict, errors=Exception)
        if agent not in host_dispatch.binding_names(receipt):
            return 0, ""
        held = host_dispatch.bound_dispatches(receipt)
        if not held:
            return 0, ""
        scalar = receipt.get("dispatch_id")  # the LAST binding, whatever the order of first bindings
        return len(held), (scalar if isinstance(scalar, str) and scalar else held[-1]["dispatch_id"])
    except Exception:
        return 0, ""


def message(count: int, soft: int, task: str = "", stage: str = "", role: bool = False, scope: str = "agent",
            dispatches: int = 0, latest: str = "") -> str:
    """The notice for ONE reader. Both readers used to get one text with two "If you are
    ..." paragraphs over a number that belonged to neither, and each could take the other's
    advice — a role told to close the window, an orchestrator told to hand back a digest.

    A role's notice names what its number counts (DC1-11): the AGENT's calls whichever dispatch they
    belonged to - it used to say "this dispatch has made N", and on run 14857 four dispatches of one agent
    were each told so at 60, 90 and 120. `scope` "agent" is a counter keyed by the host's `agent_id`;
    `dispatches` >= 2 (the receipt's count, 0 when unknown) adds how many it spans and the latest. `scope`
    "role" is the counter of a host that sends no id: every dispatch of that role in the session."""
    why = (f"(the budget's first mark is {soft}). Context is charged again on every call, "
           f"so the cost of a window grows as the square of its turns — 146 turns in one "
           f"window measured 22.6M tokens against 9.7M for the same work in three.\n")
    # 14 calls of run 12586 were thrown away by a block whose refusal footer said "do not retry" while this tail said
    # to repeat the call - opposite orders in one breath. The tail now says only what is true on BOTH exits: the notice
    # rides beside a call that ran, or follows ANOTHER rule's refusal on stderr, and a call may have been stopped by
    # that rule - so it does not say "no call was stopped", it says what the budget itself does.
    tail = "\nThis is a notice, not a refusal: the turn budget stops no call."
    if role:
        if scope != "agent":
            head = (f"TURN BUDGET: this role has made {count} tool calls in this session — every dispatch of "
                    f"this role, the host names no agent ")
        elif dispatches >= 2:
            head = (f"TURN BUDGET: this agent has made {count} tool calls across {dispatches} dispatches "
                    f"(latest {latest}) — your own; the count is this agent's context, not the current "
                    f"dispatch alone ")
        else:
            head = (f"TURN BUDGET: this agent has made {count} tool calls — your own, counted from your "
                    f"first one, whichever dispatch they belonged to ")
        return (f"{head}{why}"
                f"Finish the artifact you are on, write what you know into it, and hand back "
                f"your digest. An unfinished item belongs in the artifact (`unresolved[]`, an "
                f"open question, a `[DEFERRED: ...]` line), not in another twenty turns."
                f"{tail}")
    # Mid-stage the honest advice is the opposite of "stop": a window that ends inside a
    # stage leaves a dispatch open and makes the next one re-read it. On TP1-15045 this
    # notice fired at 270 turns with S4 open, and the orchestrator stopped one step before
    # gate A. The window question belongs to the boundary — window_budget.boundary_notice()
    # asks it there, once the state is on disk.
    advice = (
        f"{stage} is open — finish it and close it with `stage_done.py`. The window "
        f"question is asked at that boundary, not here: stopping mid-stage strands a "
        f"dispatch and pays for the same context twice."
        if stage else
        f"The window is changed only when the factory says so: a WINDOW BUDGET line from "
        f"`stage_done.py` at a stage boundary, or the `window` line of a gate-decision "
        f"answer (it names `/compact` and `/qa-factory:qa-story {task or '<TICKET>'}`). "
        f"Follow that line when there is one; otherwise go on with the next stage. "
        f"pipeline.json and the journal already hold everything a fresh window needs.")
    return (f"TURN BUDGET: this window has made {count} tool calls — the orchestrator's own; "
            f"a role's calls are counted in its dispatch {why}"
            f"{advice}{tail}")


def check(event: dict, cfg: dict) -> str:
    """'' to allow, or the notice to print. Counts first, so the call that gets the notice
    is counted too and the repeat interval does not drift."""
    tool = (event or {}).get("tool_name") or ""
    if tool not in EXPENSIVE_TOOLS:
        return ""
    session = str((event or {}).get("session_id") or "")
    if not session and not dispatch_key(event):
        return ""
    path = counter_path(session, event)
    if not (state_dir(event) / "config.json").is_file():
        return ""  # not an onboarded project — nothing to budget
    data = read_count(path)
    if data.get("scheme") != SCHEME:
        data = {}  # a pre-0.7.8 session-wide total (see SCHEME), or not a counter at all
    try:
        count = int(data.get("count") or 0) + 1
    except Exception:
        count = 1
    soft, repeat = budget(cfg)
    data["scheme"] = SCHEME
    data["count"] = count
    data.setdefault("started", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        return ""  # a counter that cannot be written never blocks work
    try:
        last = int(data.get("notified") or 0)
    except Exception:
        last = 0
    if due(count, soft, repeat) and count != last:
        data["notified"] = count
        try:
            path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
        if dispatch_key(event):
            if _safe(event.get("agent_id")):
                number, latest = bound_count(event)  # only here: no extra read on the hot path
                return message(count, soft, role=True, dispatches=number, latest=latest)
            return message(count, soft, role=True, scope="role")
        task, stage = open_stage(event)
        return message(count, soft, task, stage)
    return ""


def selftest() -> int:
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("defaults", budget({}), (DEFAULT_SOFT, DEFAULT_REPEAT))
    case("config overrides", budget({"turns": {"soft": 40, "repeat": 10}}), (40, 10))
    case("a budget below the floor is raised to it",
         budget({"turns": {"soft": 1, "repeat": 1}}), (5, 5))
    case("an unset repeat takes the default",
         budget({"turns": {"soft": 10, "repeat": 0}}), (10, DEFAULT_REPEAT))
    case("nothing before the soft mark", due(59, 60, 30), False)
    case("the notice fires on the soft mark", due(60, 60, 30), True)
    case("and not on the next call", due(61, 60, 30), False)
    case("it repeats one interval later", due(90, 60, 30), True)
    case("and again", due(120, 60, 30), True)
    role_text = message(60, 60, role=True)
    case("a role's notice speaks of its agent, whichever dispatch the calls belonged to",
         ("this agent has made 60 tool calls" in role_text, "whichever dispatch they belonged to" in role_text),
         (True, True))
    many = message(90, 60, role=True, dispatches=4, latest="S6-qa-runner-4")
    case("an agent bound to several dispatches is told how many and the latest (DC1-11)",
         "across 4 dispatches (latest S6-qa-runner-4)" in many and "not the current dispatch alone" in many, True)
    case("one dispatch, or none known, keeps the plain agent form",
         (message(60, 60, role=True, dispatches=1, latest="D1") == role_text,
          message(60, 60, role=True, dispatches=0) == role_text), (True, True))
    by_role = message(60, 60, role=True, scope="role")
    case("a host that sends no agent id counts per role in the session, and does not say 'dispatch' of the count",
         ("this role has made 60 tool calls in this session" in by_role, "the host names no agent" in by_role,
          "this agent" in by_role), (True, True, False))
    case("every role form ends the same way and carries the role's advice only",
         all(t.endswith("the turn budget stops no call.") and "hand back your digest" in t
             and not any(w in t for w in ("stage_done", "this window has", "qa-story"))
             for t in (role_text, many, by_role)), True)
    case("and carries the role's advice", "hand back your digest" in role_text, True)
    case("and none of the orchestrator's",
         any(w in role_text for w in ("stage_done", "this window has", "qa-story", "ORCHESTRATOR")),
         False)
    case("and is a notice too", "not a refusal" in role_text, True)
    case("and says the budget stops no call, never to make the call again, and not 'no call was stopped' "
         "(false after another rule's refusal: the hook's footer says the opposite)",
         (role_text.endswith("not a refusal: the turn budget stops no call."),
          any("make the same call again" in t.lower() or "no call was stopped" in t.lower()
              for t in (role_text, message(60, 60), message(60, 60, "QA-1"), message(60, 60, "QA-1", "S4")))),
         (True, False))
    case("the orchestrator's notice carries none of the role's advice",
         any(w in message(60, 60, "QA-1", stage) for stage in ("", "S4")
             for w in ("hand back", "unresolved[]", "If you are")), False)
    case("and says it is not a refusal", "not a refusal" in message(60, 60), True)
    case("it speaks of the window, never 'this dispatch' "
         "(the orchestrator has no dispatch of its own)",
         "this window has made" in message(60, 60), True)
    case("and 'this dispatch has made' is gone from the opening line of every form",
         any("this dispatch has made" in t for t in (message(60, 60), role_text, many, by_role)), False)
    case("outside a stage it defers the window to the factory's own line and goes on",
         ("WINDOW BUDGET line" in message(60, 60, "QA-1"))
         and ("otherwise go on with the next stage" in message(60, 60, "QA-1")), True)
    case("and never tells the orchestrator to stop between stages",
         "and stop" in message(60, 60, "QA-1"), False)
    case("and names the story to resume with",
         "/qa-factory:qa-story QA-1" in message(60, 60, "QA-1"), True)
    inside = message(60, 60, "QA-1", "S4")
    case("inside a stage it asks for the stage to be finished, not stopped",
         ("S4 is open" in inside) and ("stopping mid-stage" in inside), True)
    case("and it never invites a stop mid-stage",
         "close this window" in inside, False)

    import tempfile
    import hooklib
    with tempfile.TemporaryDirectory(prefix="qa-turns-") as td:
        proj = Path(td)
        (proj / "qa-factory").mkdir()
        (proj / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        old = hooklib._PROJECT_ROOT_CACHE
        hooklib._PROJECT_ROOT_CACHE = proj
        print(f"SELFTEST ROOT: {hooklib.project_root()}")  # a hijacked root reads as line one
        try:
            ev = {"tool_name": "Bash", "session_id": "s-1", "tool_input": {"command": "ls"}}
            cfg = {"turns": {"soft": 5, "repeat": 5}}
            seen = [bool(check(ev, cfg)) for _ in range(11)]
            case("the notice lands on the soft mark and then every interval",
                 seen, [False] * 4 + [True] + [False] * 4 + [True, False])
            case("a tool the budget does not count is free",
                 check({"tool_name": "TodoWrite", "session_id": "s-1"}, cfg), "")
            case("another session counts separately",
                 bool(check({"tool_name": "Bash", "session_id": "s-2"}, cfg)), False)
            case("an event with no session is not counted",
                 check({"tool_name": "Bash"}, cfg), "")

            # a compact/restart boundary resets the counter, so a window that never
            # touched 90 calls does not inherit a stale "notified: 90" from an earlier one.
            grown = read_count(counter_path("s-1"))
            case("before reset: the session carries a real count",
                 grown.get("count", 0) > 0, True)
            reset("s-1", ev, "compact")
            after_reset = read_count(counter_path("s-1"))
            case("reset: the count goes back to zero", after_reset.get("count"), 0)
            case("reset: the notified mark goes back to zero", after_reset.get("notified"), 0)
            case("reset: the reason is recorded", after_reset.get("reset_reason"), "compact")
            case("reset: the very next call after a reset is not treated as already due",
                 bool(check(ev, cfg)), False)
            case("another session's counter is untouched by this reset",
                 read_count(counter_path("s-2")).get("count", 0) > 0, True)

            # One counter per dispatch (TP1-15045: a session-wide total of 930 was
            # announced to a role on its first minute). Same session, three readers.
            orch = {"tool_name": "Bash", "session_id": "s-9"}
            role_a = dict(orch, agent_id="a301712c46df18269", agent_type="qa-factory:qa-automator")
            role_b = dict(orch, agent_id="a3bb0091b2c125ccd", agent_type="qa-factory:qa-code-critic")
            for _ in range(4):
                check(orch, cfg)
            for _ in range(4):
                check(role_a, cfg)
            case("a role's first call is call 1, whatever the session has spent",
                 read_count(counter_path("s-9", role_b)).get("count", 0), 0)
            case("a role's counter is its own file, below the session's",
                 counter_path("s-9", role_a).parent.name, DISPATCH_DIR)
            case("and the session counter is where it always was",
                 counter_path("s-9", orch), counter_path("s-9"))
            fifth = check(role_a, cfg)
            case("the role's notice comes on ITS fifth call", "this agent has made 5" in fifth, True)
            case("the next role starts from nothing", [bool(check(role_b, cfg)) for _ in range(4)],
                 [False] * 4)
            case("role calls never counted into the orchestrator's window",
                 read_count(counter_path("s-9")).get("count"), 4)
            window = check(orch, cfg)
            case("the orchestrator's notice is about its window", "this window has made 5" in window, True)
            case("a host that names the role but sends no id still counts it apart",
                 (check(dict(orch, agent_type="qa-scout"), cfg),
                  counter_path("s-9", dict(orch, agent_type="qa-scout")).name),
                 ("", "s-9--qa-scout.json"))
            reset("s-9", None, "stage_closed")
            case("a stage boundary zeroes the window", read_count(counter_path("s-9")).get("count"), 0)
            case("and leaves a running dispatch's count alone",
                 read_count(counter_path("s-9", role_a)).get("count"), 5)
            import os as _os
            import time as _time
            old_file = counter_path("s-9", role_b)
            long_ago = _time.time() - DISPATCH_KEEP_S - 3600
            _os.utime(old_file, (long_ago, long_ago))
            reset("s-9", None, "stage_closed")
            case("a dispatch counter untouched for days is swept at a boundary",
                 (old_file.exists(), counter_path("s-9", role_a).exists()), (False, True))

            # A counter written before 0.7.8 is a session-wide total: real file of the run.
            legacy = counter_path("s-legacy")
            legacy.write_text('{"count": 1323, "started": "2026-09-21T09:12:33+00:00", '
                              '"notified": 1320}', encoding="utf-8")
            case("an old session-wide counter is not announced as this window's",
                 check(dict(orch, session_id="s-legacy"), cfg), "")
            case("it starts again instead", read_count(legacy).get("count"), 1)
            legacy.write_text("garbage", encoding="utf-8")
            case("and a counter that is not JSON breaks nothing",
                 check(dict(orch, session_id="s-legacy"), cfg), "")
            legacy.write_text('{"scheme": 2, "count": "many", "notified": []}', encoding="utf-8")
            case("nor one with values of the wrong type",
                 check(dict(orch, session_id="s-legacy"), cfg), "")
        finally:
            hooklib._PROJECT_ROOT_CACHE = old

    with tempfile.TemporaryDirectory(prefix="qa-turns-none-") as td:
        old = hooklib._PROJECT_ROOT_CACHE
        hooklib._PROJECT_ROOT_CACHE = Path(td)
        try:
            case("a project that was never onboarded is not budgeted",
                 check({"tool_name": "Bash", "session_id": "s-3"}, {"turns": {"soft": 5}}), "")
        finally:
            hooklib._PROJECT_ROOT_CACHE = old

    if failures:
        print("TURN_BUDGET SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("TURN_BUDGET SELFTEST: no violations (budget, intervals, per-dispatch and per-window counting)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__.strip().splitlines()[0])
