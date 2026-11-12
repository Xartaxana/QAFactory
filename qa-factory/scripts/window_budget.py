"""Asks for a window change at a stage boundary, and never one step before a gate.

On TP1-15045 the orchestrator stopped ONE STEP BEFORE gate A — "I'm stopping here
because this window is far past its turn budget, and the gate brief should be built in a
fresh one" — after three manual compacts and 296 turns. The person got a restart command
where the gate question belonged. The 0.4.0 rule said the window ends at a gate; the window
ended just short of one, because nothing measured the remaining budget until it was already
gone (`turn_budget.py` notifies after the fact, at 60 turns and every 30 after).

The owner's decision (21.09): ask for `/compact` or a new session ONLY on a stage boundary.
So this module is predictive, not retrospective. `boundary_notice()` is called by
`stage_done.py` right after a stage is recorded `done`, when the state is already on disk
and no dispatch is open — the one moment a window may legitimately change. It answers a
single question: will what is left of this window cover the NEXT stage? If yes it says
nothing at all; if no it says the one line, naming the stage that closed, the stage that
follows and what to do.

Two points are forbidden outright, because a gate follows the stage in the SAME window:
after S4 (gate A) and after S8 (gate B). There the notice is silence, or — when the budget
is truly gone — a line that puts the gate question first and the window change immediately
after the person's answer. Closing S4 and asking gate A must always fit, which is why the
gate brief is built by code (`gate_brief.py`) and not out of the orchestrator's context.

The second moment is right after a gate decision is recorded (HF1-8): the orchestrator no
longer stops unconditionally there, so `window_verdict(..., gate_recorded=True)` asks the same
question once more over the next stage (S5 after gate A, S9 after gate B) and the controller's
gate-decision answer carries the verdict. It is read-only on the marks. The words the person gave
are recorded before it runs, and what the decision authorized runs before any window change.

Per-stage turn costs are measured, not guessed: each boundary records the delta of
`state/turns/<session>.json` since the previous boundary into
`state/window/<task>.json` — project state, never an artifact, and disposable. With no
history yet the estimate falls back to `runtime_policy.DEFAULT_STAGE_TURNS`.

Everything here is fail-silent: a budget that cannot be computed returns "" and the story
goes on. A counter has never been allowed to stand between a person and their work.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import load_ref_json, state_dir  # noqa: E402

# Gate A is asked in the window that closed S4, gate B in the one that closed S8 (the
# 0.4.0 wording predates gate A moving after S4). Those two boundaries are not window
# boundaries, whatever the budget says.
GATE_AFTER = {"S4": "A", "S8": "B"}
FALLBACK_ORDER = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")


def stage_order() -> tuple:
    """Stage ids in pipeline order, from the shipped table; the constant is the fallback."""
    stages = (load_ref_json("stages.json") or {}).get("stages")
    ids = tuple(str(s.get("id")) for s in stages if isinstance(s, dict) and s.get("id")) \
        if isinstance(stages, list) else ()
    return ids or FALLBACK_ORDER


def next_stage(stage: str) -> str:
    order = stage_order()
    try:
        return order[order.index(str(stage)) + 1]
    except (ValueError, IndexError):
        return ""


def budget(cfg: dict) -> tuple:
    """(window, stage_default) turns from config.turns, with the shipped defaults.

    Read the way `turn_budget.budget()` reads the same block: an absent or unusable value
    is the default, and a value below the floor is raised to it rather than refused — a
    misconfigured budget must not be able to silence or to spam the notice."""
    import runtime_policy
    block = (cfg or {}).get("turns") or {}
    try:
        window = int(block.get("window") or runtime_policy.DEFAULT_WINDOW_TURNS)
    except Exception:
        window = runtime_policy.DEFAULT_WINDOW_TURNS
    if window <= 0:
        # A negative window is no setting at all; raised to the floor it would make every gate say
        # "change the window" over a typo (HF1-8, the safe direction is silence).
        window = runtime_policy.DEFAULT_WINDOW_TURNS
    try:
        per_stage = int(block.get("stage_default") or runtime_policy.DEFAULT_STAGE_TURNS)
    except Exception:
        per_stage = runtime_policy.DEFAULT_STAGE_TURNS
    return max(window, 20), max(per_stage, 5)


def read_config(root: Path) -> dict:
    """The project's config from THIS state directory, not from the cached project root —
    a test and a hook must read the same file the caller named. `root` is always a Path: its one caller,
    `boundary_notice`, builds `base` itself, so `Path(root)` no longer needs a guard of its own (t-666 R1, E6)."""
    return hooklib.read_json(Path(root) / "config.json", {}, errors=Exception)


def safe_name(value: str) -> str:
    return "".join(c for c in str(value) if c.isalnum() or c in "-_")[:64] or "unknown"


def marks_path(task: str, root: Path | None = None) -> Path:
    base = Path(root) if root is not None else state_dir()
    return base / "state" / "window" / f"{safe_name(task)}.json"


def read_marks(path: Path) -> dict:
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def live_session(root: Path | None = None) -> str:
    """The session whose turn counter moved last — this window.

    `boundary_notice()` has a fixed signature with no session in it, and the turn counters
    are the only per-window state there is. The newest `state/turns/*.json` is the window
    making the call: every expensive tool call of it rewrites that file."""
    base = Path(root) if root is not None else state_dir()
    try:
        files = [p for p in (base / "state" / "turns").glob("*.json") if p.is_file()]
    except Exception:
        return ""
    if not files:
        return ""
    return max(files, key=lambda p: p.stat().st_mtime).stem


def read_counter(session: str, root: Path | None = None) -> int | None:
    """The window's turn count, or None when the counter cannot be read (absent, not JSON, not a number).

    `None` and `0` are different facts: a counter that was reset reads 0, a counter that is broken
    reads nothing. The after-gate verdict must tell them apart (FR-41, AR-28)."""
    try:
        base = Path(root) if root is not None else state_dir()
        data = json.loads((base / "state" / "turns" / f"{safe_name(session)}.json")
                          .read_text(encoding="utf-8"))
        return int(data.get("count") or 0)
    except Exception:
        return None


def turn_count(session: str, root: Path | None = None) -> int:
    count = read_counter(session, root)
    return 0 if count is None else count


def record_boundary(task: str, stage: str, session: str, count: int,
                    root: Path | None = None) -> dict:
    """Charge this window's turns since the previous boundary to the stage that just closed.

    A story that spans windows starts each window's mark at zero, so a stage that straddled
    a compact is charged only what THIS window spent on it. That under-counts such a stage
    and never over-counts it: an estimate that is too small delays the notice by one stage,
    an estimate that is too large would ask the person to change windows for nothing."""
    path = marks_path(task, root)
    data = read_marks(path)
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    marks = data.get("marks") if isinstance(data.get("marks"), dict) else {}
    try:
        previous = int(marks.get(session) or 0)
    except Exception:
        previous = 0
    spent = count - previous
    if spent > 0:
        stages[str(stage)] = spent
    marks[session] = count
    data.update(task=str(task), stages=stages, marks=marks,
                updated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass  # a mark that cannot be written costs an estimate, never a story
    return data


def estimate(marks: dict, stage: str, per_stage: int) -> int:
    """What the next stage is likely to cost this window, in turns.

    Preference order: what THIS story paid for that same stage in an earlier window, then
    what its stages have averaged, then the shipped default. Measured beats assumed — the
    stages of one story in one repository cost far more alike than any global number."""
    stages = marks.get("stages") if isinstance(marks.get("stages"), dict) else {}
    values = [int(v) for v in stages.values() if isinstance(v, (int, float)) and v > 0]
    own = stages.get(str(stage))
    if isinstance(own, (int, float)) and own > 0:
        return int(own)
    if values:
        return max(1, round(sum(values) / len(values)))
    return per_stage


def resume_hint(task: str) -> str:
    return f"/qa-factory:qa-story {task}"


def _after_gate(task: str, stage: str, sid: str, base: Path) -> tuple:
    """The verdict right after a gate decision is recorded: ONE comparison, `remaining >= need`, the
    same as at a stage close, but over the marks as they stand (read-only: the gate's own turns must
    never overwrite the cost S4 / S8 recorded) and without the forbidden-point branch (the gate has
    been asked, the person has answered)."""
    gate = GATE_AFTER.get(str(stage))
    if not gate:
        return "unknown", ""  # a caller error is never a window change
    cfg = hooklib.read_json(base / "config.json", None, kind=dict, errors=Exception)
    count = read_counter(sid, base)
    if cfg is None or count is None:
        return "unknown", ""  # a config or a counter that cannot be read is not a measurement
    nxt = next_stage(stage)
    if not nxt:
        return "fits", ""
    window, per_stage = budget(cfg)
    remaining = window - count
    need = estimate(read_marks(marks_path(task, base)), nxt, per_stage)
    if remaining >= need:
        return "fits", ""
    first = ("Run what the decision authorized first, in this window;" if gate == "A"
             else "Deliver what the decision authorized first, in this window;")
    return "change", (f"WINDOW BUDGET: gate {gate} is recorded, {nxt} next (about {need} turns) and "
                      f"only {max(remaining, 0)} of {window} are left in this window. {first} then "
                      f"change the window: run `/compact`, or continue in a new session with "
                      f"`{resume_hint(task)}`. State is on disk; nothing is re-run.")


def window_verdict(task: str, stage: str, session: str | None = None,
                   root: Path | None = None, *, gate_recorded: bool = False) -> tuple:
    """`(verdict, line)`: the ONE decision whether this window ends, with verdict `fits`, `change`
    or `unknown` and `line` the sentence for a `change` ("" otherwise).

    `unknown` is a measure that could not be taken (no config, no session, a broken counter, an
    exception): the caller continues and says nothing about the window - never "fits", never "a
    fresh window is needed" (FR-41). Without `gate_recorded` this is the stage-close question
    (`boundary_notice` returns its line); with it, `stage` is the stage in front of the gate
    just recorded (S4 for gate A, S8 for gate B) and the question is the same one asked once more
    over the next stage, with the marks left untouched."""
    try:
        base = Path(root) if root is not None else state_dir()
        if not (base / "config.json").is_file():
            return "unknown", ""  # not an onboarded project — nothing to budget
        sid = session or live_session(base)
        if not sid:
            return "unknown", ""
        if gate_recorded:
            return _after_gate(task, stage, sid, base)
        count = turn_count(sid, base)
        marks = record_boundary(task, stage, sid, count, base)
        nxt = next_stage(stage)
        if not nxt:
            return "fits", ""  # S9 closed: the story ends here, the window ends with it
        window, per_stage = budget(read_config(base))
        remaining = window - count
        need = estimate(marks, nxt, per_stage)
        if remaining >= need:
            return "fits", ""
        gate = GATE_AFTER.get(str(stage))
        if gate:
            # Forbidden point: the gate is asked in THIS window. Saying anything about a
            # window change before the question is exactly what stranded TP1-15045.
            if remaining > 0:
                return "fits", ""
            return "change", (
                f"WINDOW BUDGET: {stage} is closed and this window is spent "
                f"({count} of {window} turns) - ask gate {gate} FIRST, in this window; "
                f"`gate_brief.py --task {task} --gate {gate}` builds the brief by code, "
                f"so it fits. Change the window (`/compact`, or a new session with "
                f"`{resume_hint(task)}`) right after the person answers, never before.")
        return "change", (
            f"WINDOW BUDGET: {stage} closed, {nxt} next (about {need} turns) and only "
            f"{max(remaining, 0)} of {window} are left in this window. This is a stage "
            f"boundary - the one safe place to change windows: run `/compact`, or "
            f"continue in a new session with `{resume_hint(task)}`. State is on disk; "
            f"nothing is re-run.")
    except Exception:
        return "unknown", ""  # a budget that cannot be computed never stands in the way


def boundary_notice(task: str, stage: str, session: str | None = None,
                    root: Path | None = None, *, gate_recorded: bool = False) -> str:
    """"" when there is nothing to say, or the ONE line asking for a window change.

    Called by `stage_done.py` right after a stage is recorded `done`. The extra arguments
    exist for tests and for a caller that already knows its session; the two positional
    ones are the contract and never change. `gate_recorded` is `window_verdict`'s."""
    return window_verdict(task, stage, session, root, gate_recorded=gate_recorded)[1]


def open_work(root: Path | None = None) -> dict:
    """{task, stage, dispatches[]} of the story with a stage `running` or a dispatch open.

    Shared by `turn_budget.py` (so its notice knows it is mid-stage) and
    `precompact_guard.py` (so a compact that is not at a boundary says so). Cheap: two
    JSON reads of the most recently touched story, no controller replay."""
    empty = {"task": "", "stage": "", "dispatches": []}
    try:
        base = Path(root) if root is not None else state_dir()
        from hooklib import artifact_root
        try:
            roots = artifact_root(root=base.parent)
        except Exception:
            roots = base / "artifacts"
        pipelines = [p for p in roots.glob("*/pipeline.json") if p.is_file()]
        pipelines.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in pipelines[:12]:
            pipeline = hooklib.read_json(path, errors=Exception)    # None for anything unreadable
            if not isinstance(pipeline, dict) or pipeline.get("archived"):
                continue
            stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
            running = [sid for sid, entry in stages.items()
                       if isinstance(entry, dict) and entry.get("status") == "running"]
            dispatches = []
            try:
                state = json.loads((path.parent / "state" / "controller.json")
                                   .read_text(encoding="utf-8"))
                dispatches = sorted(did for did, d in (state.get("dispatches") or {}).items()
                                    if isinstance(d, dict) and d.get("status") == "running")
            except Exception:
                dispatches = []
            if running or dispatches:
                return {"task": str(pipeline.get("ticket") or path.parent.name),
                        "stage": sorted(running)[0] if running else "",
                        "dispatches": dispatches}
        return empty
    except Exception:
        return empty


def selftest() -> int:
    import tempfile
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("the stage after S3 is S4", next_stage("S3"), "S4")
    case("nothing follows S9", next_stage("S9"), "")
    case("an unknown stage has no successor", next_stage("SX"), "")
    import runtime_policy
    case("defaults", budget({}),
         (runtime_policy.DEFAULT_WINDOW_TURNS, runtime_policy.DEFAULT_STAGE_TURNS))
    case("config overrides", budget({"turns": {"window": 200, "stage_default": 50}}), (200, 50))
    case("a budget below the floor is raised to it",
         budget({"turns": {"window": 1, "stage_default": 1}}), (20, 5))
    case("a measured stage beats the default",
         estimate({"stages": {"S5": 70, "S1": 10}}, "S5", 35), 70)
    case("with no record of that stage the story's own average is used",
         estimate({"stages": {"S1": 10, "S2": 20}}, "S5", 35), 15)
    case("with no history at all the default stands", estimate({}, "S5", 35), 35)

    with tempfile.TemporaryDirectory(prefix="qa-window-") as td:
        base = Path(td) / "qa-factory"
        (base / "state" / "turns").mkdir(parents=True)
        (base / "config.json").write_text("{}", encoding="utf-8")

        def set_turns(session, count):
            (base / "state" / "turns" / f"{session}.json").write_text(
                json.dumps({"count": count}), encoding="utf-8")

        set_turns("s-1", 20)
        case("plenty of budget left says nothing",
             boundary_notice("QA-1", "S1", "s-1", base), "")
        (base / "config.json").write_text(json.dumps({"turns": {"window": 25}}), encoding="utf-8")
        case("the project's own window setting is what decides",
             bool(boundary_notice("QA-1", "S1", "s-1", base)), True)
        (base / "config.json").write_text("{}", encoding="utf-8")
        set_turns("s-1", 100)
        notice = boundary_notice("QA-1", "S2", "s-1", base)
        case("a boundary with the budget nearly gone speaks", bool(notice), True)
        case("and names the stage that closed and the one that follows",
             ("S2 closed" in notice) and ("S3 next" in notice), True)
        case("and offers both ways out",
             ("/compact" in notice) and ("/qa-factory:qa-story QA-1" in notice), True)
        case("it is one line", "\n" in notice, False)
        set_turns("s-1", 119)
        case("after S4 a window change is never suggested while any budget remains",
             boundary_notice("QA-1", "S4", "s-1", base), "")
        set_turns("s-1", 130)
        gate_line = boundary_notice("QA-1", "S4", "s-1", base)
        case("with the budget truly gone after S4 the gate question comes first",
             ("gate A FIRST" in gate_line) and ("after the person answers" in gate_line), True)
        set_turns("s-1", 200)
        case("the same holds after S8",
             "gate B FIRST" in boundary_notice("QA-1", "S8", "s-1", base), True)
        case("nothing follows a closed S9",
             boundary_notice("QA-1", "S9", "s-1", base), "")
        marks = read_marks(marks_path("QA-1", base))
        case("stage costs are measured, not guessed",
             marks["stages"]["S1"] > 0 and marks["stages"]["S2"] > 0, True)
        case("and they live in project state, not in the artifacts",
             "artifacts" in str(marks_path("QA-1", base)), False)
        # Right after a gate: the same comparison, over the next stage, marks untouched.
        marks_before = marks_path("QA-1", base).read_bytes()
        need_s5 = estimate(read_marks(marks_path("QA-1", base)), "S5", runtime_policy.DEFAULT_STAGE_TURNS)
        set_turns("s-1", runtime_policy.DEFAULT_WINDOW_TURNS - need_s5)
        case("after gate A with exactly the room S5 needs the window fits",
             window_verdict("QA-1", "S4", "s-1", base, gate_recorded=True), ("fits", ""))
        set_turns("s-1", runtime_policy.DEFAULT_WINDOW_TURNS - need_s5 + 1)
        verdict, line = window_verdict("QA-1", "S4", "s-1", base, gate_recorded=True)
        case("one turn short, the window changes", verdict, "change")
        case("and the line says the gate is recorded and S5 is next",
             ("gate A is recorded" in line) and ("S5 next" in line), True)
        case("the gate-time call leaves the recorded marks alone",
             marks_path("QA-1", base).read_bytes(), marks_before)
        case("a stage that is not in front of a gate is a caller error, never a change",
             window_verdict("QA-1", "S2", "s-1", base, gate_recorded=True), ("unknown", ""))

    with tempfile.TemporaryDirectory(prefix="qa-window-none-") as td:
        base = Path(td) / "qa-factory"
        (base / "state").mkdir(parents=True)
        case("a project that was never onboarded is not budgeted",
             boundary_notice("QA-1", "S2", "s-1", base), "")

    with tempfile.TemporaryDirectory(prefix="qa-window-open-") as td:
        base = Path(td) / "qa-factory"
        art = base / "artifacts" / "QA-1"
        (art / "state").mkdir(parents=True)
        (base / "config.json").write_text("{}", encoding="utf-8")
        (art / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "stages": {"S3": {"status": "running"}}}), encoding="utf-8")
        (art / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"S3-qa-test-strategist-1": {"status": "running"},
                            "S1-qa-scout-1": {"status": "accepted"}}}), encoding="utf-8")
        work = open_work(base)
        case("open work names the story", work["task"], "QA-1")
        case("and the stage still running", work["stage"], "S3")
        case("and only the dispatch that is open",
             work["dispatches"], ["S3-qa-test-strategist-1"])

    if failures:
        print("WINDOW_BUDGET SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("WINDOW_BUDGET SELFTEST: no violations (order, thresholds, forbidden points, marks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--task", default="")
    ap.add_argument("--stage", default="", help="the stage that was just recorded done")
    ap.add_argument("--open-work", action="store_true",
                    help="print the story with a stage running or a dispatch open")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.open_work:
        print(json.dumps(open_work(), ensure_ascii=False))
        return 0
    if not args.task or not args.stage:
        print("window_budget.py: --task and --stage are required", file=sys.stderr)
        return 2
    notice = boundary_notice(args.task, args.stage)
    if notice:
        print(notice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
