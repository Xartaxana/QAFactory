"""Where a window may change, and what a story may cost.

The incident behind every case here is TP1-15045: the orchestrator stopped ONE STEP
BEFORE gate A "because this window is far past its turn budget", after three manual
compacts and 296 turns, and handed the person a restart command instead of the gate
question. The owner's decision of 21.09 is that a window changes at a stage boundary and
nowhere else — never one step before a gate.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import runtime_policy  # noqa: E402
import story_budget  # noqa: E402
import turn_budget  # noqa: E402
import window_budget  # noqa: E402


def make_project(prefix: str) -> Path:
    root = temp_dir(prefix)
    base = root / "qa-factory"
    (base / "state" / "turns").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    return base


def bind_session(base: Path, art: Path, task: str, usd, tokens: int = 100) -> None:
    """The story's ONE session `s-1`, as the price function binds it (FR-24, t-170): the driver's
    journal names it (one role row whose running total is `usd`) and its cost file carries the
    tokens. A `by_task` tag in the cost file binds nothing, so a fixture that only tagged the
    ticket counted no session and the ceiling never saw a spend."""
    (art / "state").mkdir(parents=True, exist_ok=True)
    (art / "state" / "driver-runs.jsonl").write_text(json.dumps(
        {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
         "session_id": "s-1", "num_turns": 3, "total_cost_usd": usd,
         "ts": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
    (base / "state" / "cost" / "s-1.json").write_text(json.dumps(
        {"session_id": "s-1", "by_task": {task: {"tokens": tokens}}, "agents": []}), encoding="utf-8")


def set_turns(base: Path, session: str, count: int) -> None:
    (base / "state" / "turns" / f"{session}.json").write_text(
        json.dumps({"count": count}), encoding="utf-8")


def test_window_boundaries() -> None:
    base = make_project("qa-window-boundary-")
    try:
        set_turns(base, "s-1", 10)
        check_eq("a window with room to spare says nothing at a boundary",
                 window_budget.boundary_notice("QA-1", "S1", "s-1", base), "")

        # 296 turns is what the real window reached; the default ceiling is 120.
        set_turns(base, "s-1", 296)
        notice = window_budget.boundary_notice("QA-1", "S2", "s-1", base)
        check("a spent window asks at the boundary", bool(notice))
        check_in("it names the stage that closed", "S2 closed", notice)
        check_in("and the stage that follows", "S3 next", notice)
        check_in("it offers a compact", "/compact", notice)
        check_in("or a fresh session on the same story", "/qa-factory:qa-story QA-1", notice)
        check_eq("and it is a single line", notice.count("\n"), 0)

        # The forbidden points. Gate A follows S4 in the SAME window, gate B follows S8.
        set_turns(base, "s-1", 119)
        check_eq("with budget left, closing S4 never proposes a window change",
                 window_budget.boundary_notice("QA-1", "S4", "s-1", base), "")
        set_turns(base, "s-1", 119)
        check_eq("nor does closing S8",
                 window_budget.boundary_notice("QA-1", "S8", "s-1", base), "")

        set_turns(base, "s-1", 400)
        gate_a = window_budget.boundary_notice("QA-1", "S4", "s-1", base)
        check_in("with the budget truly gone, gate A is still asked first",
                 "gate A FIRST", gate_a)
        check_in("and the window changes only after the person answers",
                 "after the person answers", gate_a)
        check_not_in("the line never tells the person to restart before the gate",
                     "stopping here", gate_a)
        gate_b = window_budget.boundary_notice("QA-1", "S8", "s-1", base)
        check_in("the same rule holds for gate B", "gate B FIRST", gate_b)

        check_eq("a closed S9 has no next stage to budget for",
                 window_budget.boundary_notice("QA-1", "S9", "s-1", base), "")
    finally:
        cleanup(base.parent)


def after_gate(base: Path, stage: str = "S4", session: str = "s-1") -> tuple:
    return window_budget.window_verdict("QA-1", stage, session, base, gate_recorded=True)


def test_window_after_a_gate() -> None:
    """HF1-8 (GW1-12): the orchestrator no longer stops unconditionally after a gate; the ONLY decider of a
    window change is `window_budget`, asked once more right after the decision is recorded. W-A1, W-A2, W-A3.
    Expectations come from the rule (`remaining >= need` fits, one short changes), not from the code."""
    base = make_project("qa-window-after-gate-")
    try:
        window = runtime_policy.DEFAULT_WINDOW_TURNS
        set_turns(base, "s-1", 10)
        window_budget.boundary_notice("QA-1", "S3", "s-1", base)
        set_turns(base, "s-1", 50)
        window_budget.boundary_notice("QA-1", "S4", "s-1", base)       # S3 cost 10, S4 cost 40
        marks_file = window_budget.marks_path("QA-1", base)
        need = window_budget.estimate(window_budget.read_marks(marks_file), "S5",
                                      runtime_policy.DEFAULT_STAGE_TURNS)
        check_eq("the measured stages average 25 turns, so S5 is estimated at 25", need, 25)
        before = marks_file.read_bytes()

        set_turns(base, "s-1", window - need)
        check_eq("W-A1 AT the limit (remaining == need) the window fits and says nothing",
                 after_gate(base), ("fits", ""))
        set_turns(base, "s-1", window - need + 1)
        verdict, line = after_gate(base)
        check_eq("W-A1 BEYOND it (remaining == need - 1) the window changes", verdict, "change")
        for needle in ("gate A is recorded", "S5 next", "first, in this window", "/compact",
                       "/qa-factory:qa-story QA-1", "only 24 of 120"):
            check_in(f"W-A1 the line carries {needle!r}", needle, line)
        check_eq("W-A1 and it is a single line", line.count("\n"), 0)
        check_eq("W-A1 boundary_notice with the flag returns the same line",
                 window_budget.boundary_notice("QA-1", "S4", "s-1", base, gate_recorded=True), line)
        check_eq("W-A2 the gate-time calls left the recorded marks byte for byte (S4's cost survives)",
                 marks_file.read_bytes(), before)

        set_turns(base, "s-1", window + 400)
        verdict, line = after_gate(base)
        check_eq("a spent window changes too, and never claims a negative remainder", verdict, "change")
        check_in("only 0 is left, not a negative number", "only 0 of 120", line)

        set_turns(base, "s-1", window - need + 1)
        verdict, line = after_gate(base, "S8")
        check_eq("W-A3 gate B recorded with the budget short changes", verdict, "change")
        for needle in ("gate B is recorded", "S9 next", "Deliver what the decision authorized first"):
            check_in(f"W-A3 the gate B line carries {needle!r}", needle, line)
        check_not_in("W-A3 and not gate A's words", "Run what the decision authorized", line)
        check_eq("W-A2 gate B's call leaves the marks alone too", marks_file.read_bytes(), before)

        # The stage-close path is the same function: the forbidden point still holds there.
        set_turns(base, "s-1", window - 10)
        check_eq("W-A5 closing S4 with budget left (but short of S5) still says nothing before the gate",
                 window_budget.boundary_notice("QA-1", "S4", "s-1", base), "")
    finally:
        cleanup(base.parent)


def test_window_verdict_is_unknown_never_fits() -> None:
    """W-A4 (AR-28, FR-41): a measure that cannot be taken is `unknown`, with no line and no exception - the
    caller continues and says nothing about the window; it is never `fits` and never a change."""
    def project(config="{}", counter="{\"count\": 10}", marks=None):
        root = temp_dir("qa-window-unknown-")
        base = root / "qa-factory"
        (base / "state" / "turns").mkdir(parents=True)
        if config is not None:
            (base / "config.json").write_text(config, encoding="utf-8")
        if counter is not None:
            (base / "state" / "turns" / "s-1.json").write_text(counter, encoding="utf-8")
        if marks is not None:
            marks_path = window_budget.marks_path("QA-1", base)
            marks_path.parent.mkdir(parents=True, exist_ok=True)
            marks_path.write_text(marks, encoding="utf-8")
        return base

    unknown = ("unknown", "")
    cases = {
        "no config.json": dict(config=None),
        "config not JSON": dict(config="{not json"),
        "empty config": dict(config=""),
        "config is a list": dict(config="[]"),
        "no counter file": dict(counter=None),
        "counter is garbage": dict(counter="garbage"),
        "counter is a word": dict(counter='{"count": "many"}'),
        "counter is a list": dict(counter="[]"),
        "counter is truncated JSON": dict(counter='{"count": 1'),
    }
    for label, kwargs in cases.items():
        base = project(**kwargs)
        try:
            check_eq(f"W-A4 {label}: unknown, no line", after_gate(base), unknown)
        finally:
            cleanup(base.parent)

    base = project(counter=None)
    try:
        check_eq("W-A4 no session resolvable (none given, no counter file to take it from)",
                 window_budget.window_verdict("QA-1", "S4", None, base, gate_recorded=True), unknown)
    finally:
        cleanup(base.parent)
    base = project()
    try:
        for stage in ("S2", "s4", "S4 ", "SX", "", "S9"):
            check_eq(f"W-A4 stage {stage!r} is not in front of a gate: unknown, never a change",
                     after_gate(base, stage), unknown)
        check_eq("W-A4 a stage that is not even a string does not raise", after_gate(base, ["S4"]), unknown)
        check_eq("W-A4 with a readable counter and config the same call is a measurement",
                 after_gate(base)[0], "fits")
    finally:
        cleanup(base.parent)

    # Values that must stay on the safe side of the window (silence -> continue), and the two that speak.
    safe = {
        "a turns block that is a string is no setting: the defaults": ('{"turns": "abc"}', 10, "fits"),
        "window 'abc' is the default": ('{"turns": {"window": "abc"}}', 10, "fits"),
        "window 0 is the default": ('{"turns": {"window": 0}}', 10, "fits"),
        "window -5 is the default, not the floor of 20": ('{"turns": {"window": -5}}', 10, "fits"),
        "window 10**12 leaves room": ('{"turns": {"window": 1000000000000}}', 10 ** 9, "fits"),
        "stage_default 0 is the default": ('{"turns": {"stage_default": 0}}', 10, "fits"),
        "stage_default 'x' is the default": ('{"turns": {"stage_default": "x"}}', 10, "fits"),
        "a negative counter is room": ("{}", -3, "fits"),
        "window 20 (the floor) with S5 estimated at 35 speaks": ('{"turns": {"window": 20}}', 0, "change"),
        "counter 10**9 is a spent window": ("{}", 10 ** 9, "change"),
    }
    for label, (config, count, want) in safe.items():
        base = project(config=config, counter=json.dumps({"count": count}))
        try:
            got = after_gate(base)
            check_eq(f"W-A4 {label}", got[0], want)
            check_eq(f"W-A4 {label}: the line is there exactly when the window changes",
                     bool(got[1]), want == "change")
        finally:
            cleanup(base.parent)
    base = project(marks="[]")
    try:
        check_eq("W-A4 a marks file that is a list is no history: the default estimate stands",
                 after_gate(base)[0], "fits")
    finally:
        cleanup(base.parent)
    check_eq("W-A4 budget(): a negative window is the default", window_budget.budget({"turns": {"window": -5}})[0],
             runtime_policy.DEFAULT_WINDOW_TURNS)
    check_eq("W-A4 budget(): a window below the floor but positive is raised to it",
             window_budget.budget({"turns": {"window": 1}})[0], 20)


def test_estimates_are_measured() -> None:
    base = make_project("qa-window-estimate-")
    try:
        set_turns(base, "s-1", 40)
        window_budget.boundary_notice("QA-1", "S1", "s-1", base)
        set_turns(base, "s-1", 80)
        window_budget.boundary_notice("QA-1", "S2", "s-1", base)
        marks = window_budget.read_marks(window_budget.marks_path("QA-1", base))
        check_eq("the first stage is charged what the window spent on it",
                 marks["stages"]["S1"], 40)
        check_eq("and the second only its own delta", marks["stages"]["S2"], 40)
        check_eq("with two 40-turn stages behind it the next one is estimated at 40",
                 window_budget.estimate(marks, "S3", runtime_policy.DEFAULT_STAGE_TURNS), 40)
        check_eq("the marks live in project state, never in the artifacts",
                 "artifacts" in str(window_budget.marks_path("QA-1", base)), False)
        check_eq("a story that was never measured falls back to the shipped default",
                 window_budget.estimate({}, "S3", runtime_policy.DEFAULT_STAGE_TURNS),
                 runtime_policy.DEFAULT_STAGE_TURNS)
    finally:
        cleanup(base.parent)


def test_boundary_notice_never_raises() -> None:
    root = temp_dir("qa-window-broken-")
    try:
        base = root / "qa-factory"
        (base / "state" / "turns").mkdir(parents=True)
        (base / "config.json").write_text("{not json at all", encoding="utf-8")
        (base / "state" / "turns" / "s-1.json").write_text("garbage", encoding="utf-8")
        check_eq("a broken config and a broken counter produce silence, not a crash",
                 window_budget.boundary_notice("QA-1", "S2", "s-1", base), "")
        check_eq("and an unwritable state directory does not either",
                 window_budget.boundary_notice("QA-1", "S2", None, root / "nowhere"), "")
    finally:
        cleanup(root)


def test_turn_notice_is_stage_aware() -> None:
    inside = turn_budget.message(270, 60, "QA-1", "S4")
    check_in("mid-stage the notice asks for the stage to be finished", "S4 is open", inside)
    check_in("and says why stopping here is the expensive move", "strands a dispatch", inside)
    check_not_in("it never invites a stop mid-stage", "close this window", inside)
    outside = turn_budget.message(270, 60, "QA-1", "")
    check_in("between stages it defers the window to the factory's own line", "WINDOW BUDGET line", outside)
    check_in("and otherwise goes on with the next stage", "otherwise go on with the next stage", outside)
    check_not_in("it never tells the orchestrator to stop between stages (HF1-8)", "and stop", outside)
    check_in("and names the resume command", "/qa-factory:qa-story QA-1", outside)
    check_not_in("neither form carries the ROLE's advice any more (one reader per notice)",
                 "hand back", inside + outside)
    check_in("and both are notices, not refusals", "not a refusal", outside)
    # K6 (SC1-6): the notice rides beside a call that RAN. The old tail said "make the same call again", and the
    # refusal footer of the block that carried it said "do NOT try the same call again" - 14 calls of run 12586.
    forms = (inside, outside, turn_budget.message(60, 60, role=True), turn_budget.message(60, 60))
    check("K6: every form says the turn budget stops no call (true on both exits)",
          all(t.endswith("not a refusal: the turn budget stops no call.") for t in forms))
    check("K6: and none says 'no call was stopped' (false after another rule's refusal) or to make the call again",
          not any("no call was stopped" in t.lower() or "make the same call again" in t.lower()
                  or "same call again" in t.lower() for t in forms))


def test_open_work_and_compact_guard() -> None:
    base = make_project("qa-window-open-")
    try:
        art = base / "artifacts" / "QA-1"
        (art / "state").mkdir(parents=True)
        (art / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "stages": {"S4": {"status": "running"}}}), encoding="utf-8")
        (art / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"S4-qa-case-critic-1": {"status": "running"}}}), encoding="utf-8")
        work = window_budget.open_work(base)
        check_eq("the open story is found", work["task"], "QA-1")
        check_eq("with the stage still running", work["stage"], "S4")
        check_eq("and the dispatch that is open",
                 work["dispatches"], ["S4-qa-case-critic-1"])

        import precompact_guard
        line = precompact_guard.boundary_line({"cwd": str(base.parent)})
        check_in("a compact mid-stage is told it is not at a boundary",
                 "NOT a stage boundary", line)
        check_in("and which dispatch is open", "S4-qa-case-critic-1", line)
        check_in("while making clear the compact still happens",
                 "compact still proceeds", line)

        (art / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "stages": {"S4": {"status": "done"}}}), encoding="utf-8")
        (art / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"S4-qa-case-critic-1": {"status": "accepted"}}}), encoding="utf-8")
        check_eq("at a real boundary the guard adds nothing",
                 precompact_guard.boundary_line({"cwd": str(base.parent)}), "")
    finally:
        cleanup(base.parent)


def test_retro_analyst_has_a_blocking_budget() -> None:
    counters = {"active_seconds": 10_000, "requests": 500, "output_tokens": 200_000}
    verdict = runtime_policy.checkpoint_due("qa-retro-analyst", counters)
    check("the retro analyst now checkpoints", verdict["checkpoint"])
    check("and its checkpoint blocks, unlike every other discovery-shaped role",
          verdict["blocking"])
    check_eq("a role with no budget of its own still falls into discovery",
             runtime_policy.checkpoint_due("qa-scout", counters)["blocking"], False)
    small = runtime_policy.checkpoint_due(
        "qa-retro-analyst", {"active_seconds": 60, "requests": 4, "output_tokens": 1500})
    check_eq("prose over a ready table fits well inside the budget",
             small["checkpoint"], False)


def test_story_budget() -> None:
    base = make_project("qa-story-budget-")
    try:
        art = base / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")

        def spend(usd):
            bind_session(base, art, "QA-1", usd, tokens=100)

        spend(99.0)
        check_eq("a project with no ceiling is never interrupted",
                 story_budget.check("QA-1", base, art)["notice"], "")

        (base / "config.json").write_text(json.dumps(
            {"budget": {"story_usd": 10, "warn_at": [0.5, 0.8]}}), encoding="utf-8")
        spend(2.0)
        check_eq("under the first mark, silence", story_budget.check("QA-1", base, art)["notice"], "")
        spend(5.5)
        first = story_budget.check("QA-1", base, art)
        check_in("the first threshold warns once", "STORY BUDGET", first["notice"])
        check_eq("and does not stop the story", first["stop"], False)
        check_eq("the same threshold is not repeated",
                 story_budget.check("QA-1", base, art)["notice"], "")
        spend(12.0)
        stop = story_budget.check("QA-1", base, art)
        check("at the ceiling the story stops and asks", stop["stop"])
        check_in("naming the call that records the person's word",
                 "--block \"story budget\"", stop["notice"])
        check_in("and never blaming the work for a ceiling the project set",
                 "not a fault of the work", stop["notice"])

        (art / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "stage_overrides": [
                {"stage": "S6", "match": "story budget", "decision": "go on, I want the run"}]}),
            encoding="utf-8")
        story_budget.marker_path("QA-1", base).unlink()
        passed = story_budget.check("QA-1", base, art)
        check_eq("a recorded decision passes the ceiling", passed["stop"], False)
        check_in("quoting the person's own words", "go on, I want the run", passed["notice"])
    finally:
        cleanup(base.parent)


def test_story_budget_percent_is_floored() -> None:
    """t-171 item 4: the notice prints the percentage FLOORED, so "100%" appears only at or over the
    limit (a story at 99.5% is not at its ceiling: the stop rule keeps them apart)."""
    for ratio, want in ((0.0, 0), (0.29, 29), (0.994, 99), (0.995, 99), (0.996, 99), (1.0, 100), (1.004, 100)):
        check_eq(f"floor_percent({ratio}) is {want}", story_budget.floor_percent(ratio), want)
    base = make_project("qa-story-budget-percent-")
    try:
        art = base / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
        (base / "config.json").write_text(json.dumps(
            {"budget": {"story_usd": 10, "warn_at": [0.5, 0.8]}}), encoding="utf-8")
        marker = story_budget.marker_path("QA-1", base)
        for usd, label in ((9.94, "99.4%"), (9.96, "99.6%")):
            marker.unlink(missing_ok=True)
            bind_session(base, art, "QA-1", usd)
            state = story_budget.check("QA-1", base, art)
            check_in(f"at {label} the notice says 99%", "is at 99% of its ceiling", state["notice"])
            check_not_in(f"at {label} it never says it is at 100%", "is at 100%", state["notice"])
            check_eq(f"at {label} the story is not stopped", state["stop"], False)
        # At and over the limit the stop line itself is printed; the "is at N%" line is reached there
        # only when the ceiling mark was already answered (a marker that holds 1.0 but not 0.8).
        for usd, label in ((10.0, "100.0%"), (10.04, "100.4%")):
            marker.unlink(missing_ok=True)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"task": "QA-1", "notified": [1.0]}), encoding="utf-8")
            bind_session(base, art, "QA-1", usd)
            state = story_budget.check("QA-1", base, art)
            check_in(f"at {label} the notice says 100%", "is at 100% of its ceiling", state["notice"])
    finally:
        cleanup(base.parent)


MODEL = "claude-sonnet-5-5"     # catalogue: output $10 per 1M tokens -> 100000 output tokens = $1.00
OVERRIDE_1_5X = {"rate_overrides": [{"model_id": MODEL, "aliases": [],
                                     "rates": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6}}]}


def bind_priced_session(base: Path, art: Path, task: str, list_usd: float, charged: float, sid: str = "s-1") -> None:
    """The story's ONE session with BOTH records: the driver's journal (the CLI charged `charged`) and a cost file whose
    request is `list_usd` at the catalogue's list price, so the price function can compare them (t-182: a fixture with
    no request ledger has no record A, and the ceiling's rate base cannot show)."""
    (art / "state").mkdir(parents=True, exist_ok=True)
    (art / "state" / "driver-runs.jsonl").write_text(json.dumps(
        {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1", "session_id": sid,
         "num_turns": 3, "total_cost_usd": charged, "ts": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
    request = {"request_key": f"anthropic:{sid}:r0:orchestrator", "provider": "anthropic", "session_id": sid,
               "request_id": "r0", "stream": "orchestrator", "model_id": MODEL, "timestamp": "2026-09-30T05:00:00+00:00",
               "activity_id": "unclassified", "task": "(no task)",
               "usage": {"requests": 1, "input": 0, "output": round(list_usd * 100000), "cache_read": 0,
                         "cache_write_5m": 0, "cache_write_1h": 0},
               "valuation": {"subtotal_usd": "999", "pricing_coverage": "complete", "missing_rate_categories": [],
                             "rate_provenance": {"kind": "legacy_project_override"}}}
    (base / "state" / "cost" / f"{sid}.json").write_text(json.dumps(
        {"session_id": sid, "has_factory_activity": True, "requests": [request], "by_task": {task: {"tokens": 7}},
         "external_calls": [], "agents": [], "by_activity": {}, "total_cost_usd": 999.0}), encoding="utf-8")


def test_ceiling_is_on_the_rate_base_of_the_price() -> None:
    """t-182 F1: the recaptured cmp1 with a 1.5x override and a cap of $20 read "at 87% ... $17.42 of $20.00. Nothing to do"
    beside a price of $26.14: the ceiling compared the CLI's list-price charge with a cap the price had outgrown. B is
    put on the price base per session (the price function's own rule), so the ceiling reads the price's rates."""
    agreeing = {"sessions": [{"session": "s1", "a_usd": 1.0, "a_price_usd": 1.5, "b_usd": 1.0, "verdict": "agrees"}]}
    figure = story_budget.ceiling_figure(agreeing)
    check_eq("T182 F1 an agreeing session at 1.5x: the ceiling's figure is B on the price base (1.0 * 1.5 / 1.0 = 1.5), not B's 1.0",
             (figure["usd"], figure["alt_usd"], figure["on_project_rates"], figure["unscaled"]), (1.5, 1.5, True, []))
    plain = story_budget.ceiling_figure({"sessions": [{"session": "s1", "a_usd": 1.0, "a_price_usd": 1.0, "b_usd": 1.0, "verdict": "agrees"}]})
    check_eq("T182 F1 control, no project rates (the price IS the list price): every figure is what it was",
             (plain["usd"], plain["alt_usd"], plain["disputed"], plain["on_project_rates"], plain["unscaled"]), (1.0, 1.0, 0, False, []))
    disputed = story_budget.ceiling_figure({"sessions": [{"session": "s1", "a_usd": 1.0, "a_price_usd": 1.5, "b_usd": 1.2, "verdict": "differs"}]})
    check_eq("T182 F1 a disputed session: B is 1.2 on the price base = 1.8, the transcripts 1.5, the gap 0.3 on ONE base",
             (disputed["usd"], disputed["alt_usd"], disputed["gap_usd"], disputed["disputed"]), (1.8, 1.5, 0.3, 1))
    zero = story_budget.ceiling_figure({"sessions": [
        {"session": "z1abcdefgh", "a_usd": 0.0, "a_price_usd": 2.0, "b_usd": 0.5, "verdict": "differs"},
        {"session": "s1", "a_usd": 1.0, "a_price_usd": 1.5, "b_usd": 1.0, "verdict": "agrees"}]})
    check_eq("T182 F1 edge (i): a session whose list price is $0 cannot be scaled: its B stands as it is (0.5) and it is NAMED; "
             "the other is scaled (1.5)", (zero["usd"], zero["unscaled"]), (2.0, ["z1abcdefgh"]))
    notes = story_budget.figure_notes(zero)
    check_in("T182 F1 edge (i): the notice says so, with the short id",
             "For 1 session (z1abcdef) it could not be put on them, because the transcripts at the catalogue's rates are $0 or "
             "unknown: the CLI's charge stands as it is for that session.", notes)
    check_in("T182 F1 the notice says the price is at the project's rates and the charge is put on them",
             "The price is at the project's own rates, and the CLI's own charge (which is at the catalogue's list rates) is put on "
             "them session by session", notes)
    check_in("T182 F1 a disputed figure says both ends are on the project rates",
             "differ, by $0.30 in all once both are on the project rates. The ceiling is compared against the CLI's charge on those "
             "rates; the transcripts would make it $1.50.", story_budget.figure_notes(disputed))
    check_eq("T182 F1 control: no project rates, nothing agreeing, nothing said", story_budget.figure_notes(plain), "")
    vendor = story_budget.ceiling_figure({"sessions": [{"session": "v1", "a_usd": None, "a_price_usd": 1.0, "b_usd": 1.5, "verdict": "one_record"}]})
    check_eq("T182 F1 edge: a model only the project's table knows (no list price): B as it stands, named", (vendor["usd"], vendor["unscaled"]), (1.5, ["v1"]))
    no_rates_zero = story_budget.ceiling_figure({"sessions": [{"session": "z1", "a_usd": 0.0, "a_price_usd": 0.0, "b_usd": 0.5, "verdict": "differs"}]})
    check_eq("T182 F1 edge: a $0 list price with NO project rates is not a project-rates finding (nothing named)",
             (no_rates_zero["usd"], no_rates_zero["on_project_rates"], no_rates_zero["unscaled"]), (0.5, False, []))
    flagged = story_budget.ceiling_figure({"rate_overrides": [MODEL], "sessions": [
        {"session": "z1", "a_usd": 0.0, "a_price_usd": 0.0, "b_usd": 0.5, "verdict": "differs"}]})
    check_eq("T182 F1 edge (i): the answer's own rate_overrides make every unscalable session a named one",
             (flagged["usd"], flagged["on_project_rates"], flagged["unscaled"]), (0.5, True, ["z1"]))


def test_story_budget_stops_at_the_prices_rates() -> None:
    def run(cap, charged, list_usd, cost_cfg):
        base = make_project("qa-story-budget-rates-")
        try:
            art = base / "artifacts" / "QA-1"
            art.mkdir(parents=True)
            (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
            config = {"budget": {"story_usd": cap, "warn_at": [0.5, 0.8]}}
            if cost_cfg:
                config["cost"] = cost_cfg
            (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
            bind_priced_session(base, art, "QA-1", list_usd, charged)
            return story_budget.check("QA-1", base, art)
        finally:
            cleanup(base.parent)

    # the recaptured shape (the records agree) at 1.5x and a cap of $1.20: the price is $1.50
    stop = run(1.2, 1.0, 1.0, OVERRIDE_1_5X)
    check_eq("T182 F1 override 1.5x, the records agree, cap $1.20: the story STOPS at $1.50 (it read $1.00 = 83% and said nothing to do)",
             (stop["stop"], stop["spend"]["usd"], stop["ratio"]), (True, 1.5, 1.25))
    check_in("T182 F1 ... and prints the price's figure", "has reached its ceiling — $1.50 of $1.20", stop["notice"])
    check_in("T182 F1 ... saying the price is at the project's rates", "The price is at the project's own rates", stop["notice"])
    check_in("T182 F1 ... and still names the call that records the person's word", "--block \"story budget\"", stop["notice"])
    control = run(1.2, 1.0, 1.0, None)
    check_eq("T182 F1 control, no project rates: $1.00 of $1.20 is 83%, a warning and not a stop, worded as before",
             (control["stop"], control["spend"]["usd"], control["ratio"]), (False, 1.0, 0.8333))
    check_in("T182 F1 control: the old sentence", "is at 83% of its ceiling — $1.00 of $1.20.", control["notice"])
    check_not_in("T182 F1 control: nothing about project rates", "project's own rates", control["notice"])
    dispute = run(1.2, 1.2, 1.0, OVERRIDE_1_5X)
    check_eq("T182 F1 override and a disputed session: B 1.2 is $1.80 on the price base, and it stops", (dispute["stop"], dispute["spend"]["usd"]), (True, 1.8))
    check_in("T182 F1 ... and the figure says both records are on one base", "once both are on the project rates", dispute["notice"])
    warn = run(2.0, 1.0, 1.0, OVERRIDE_1_5X)
    check_eq("T182 F1 a cap the price has not reached still only warns ($1.50 of $2.00 is 75%: past the 50% mark, under 80%)",
             (warn["stop"], warn["level"]), (False, 0.5))
    check_in("T182 F1 ... on the price's figure", "is at 75% of its ceiling — $1.50 of $2.00.", warn["notice"])


def test_story_budget_cli() -> None:
    base = make_project("qa-story-budget-cli-")
    try:
        art = base / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
        (base / "config.json").write_text(json.dumps({"budget": {"story_usd": 1}}), encoding="utf-8")
        bind_session(base, art, "QA-1", 5.0, tokens=10)
        import os
        from harness import run_script
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(base.parent))
        out = run_script("story_budget.py", "--task", "QA-1", cwd=base.parent, env=env)
        # An unanswered ceiling exits non-zero: a stop line printed with exit 0 is a stop
        # nobody acts on, which is how one pilot ran past its ceiling (0.7.7 review, D-F12).
        check_eq("the CLI signals the stop in its exit code", out.returncode,
                 story_budget.STOP_EXIT)
        check_in("and prints the stop line", "STORY BUDGET", out.stdout)
        (art / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "stage_overrides": [
                {"stage": "S8", "match": "story budget", "decision": "go on, I want the run"}]}),
            encoding="utf-8")
        story_budget.marker_path("QA-1", base).unlink(missing_ok=True)
        passed = run_script("story_budget.py", "--task", "QA-1", cwd=base.parent, env=env)
        check_eq("a ceiling the person passed exits clean", passed.returncode, 0)
    finally:
        cleanup(base.parent)


if __name__ == "__main__":
    test_window_boundaries()
    test_window_after_a_gate()
    test_window_verdict_is_unknown_never_fits()
    test_estimates_are_measured()
    test_boundary_notice_never_raises()
    test_turn_notice_is_stage_aware()
    test_open_work_and_compact_guard()
    test_retro_analyst_has_a_blocking_budget()
    test_story_budget()
    test_story_budget_percent_is_floored()
    test_ceiling_is_on_the_rate_base_of_the_price()
    test_story_budget_stops_at_the_prices_rates()
    test_story_budget_cli()
    finish("window and budgets")
