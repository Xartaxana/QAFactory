#!/usr/bin/env python3
"""t-1937 TR3-18 (n1_frozen_calls, n1_frozen_events, n1_frozen_state_keys, n1_frozen_console): the serial road of S5 (`parallel_windows`
1) does what it did BEFORE the window scheduler (TR3-6) existed.

The frozen side is a capture of ONE stub-driven serial S5 story, taken ONCE from the tree under TR3-6 (commit d005e84c5, the merge of
tr3-15) and committed in `fixtures/s5-n1-frozen/` (`calls.json`, `events.json`, `state_keys.json`, `console.json`). The live side runs
the same story through the CURRENT code at `parallel_windows` 1 and compares. Both sides run through the one function `capture`, so the
capture cannot drift from the compare. `single_window_default_equals_n1` of `test_story_run_s5_parallel.py` proves only that a single
window is routed to the serial body; this file is the one that sees a change INSIDE that body.

The story (stand-ins as in `test_story_run_s5_parallel.World`): three windows TC-1..TC-3 in stage-scope order; TC-1's critic asks for a
MECHANICAL round, TC-2's first critic asks for a test-defect REPAIR round and its second closes, TC-3's critic closes.

Volatile fields, masked on both sides (each mask named here and nowhere else):
  - M1 the temp project root, the artifacts folder of the task and the plugin root (the checkout the test runs from, named in every
    role prompt): replaced by `<root>`, `<task>` and `<plugin>` (also with `/` and `\\` swapped);
  - M2 the cost the progress line prints (`$0.0123`): replaced by `<cost>`;
  - M3 the path separator after a masked folder (`<plugin>\\scripts/x.py` on Windows, `/` on Linux): `/` throughout;
  - M4 the line ending of a prompt (`\\r\\n` where the driver writes text on Windows): `\\n`;
  - M5 the key `noted` of the driver state is left out of `state_keys` (it holds one-time notes, written by whichever code path met them).
A difference that is not one of these is a finding: a change of the serial road. Never mask it.

Capture (a builder or a lead, once, on the pre-TR3-6 tree, never in CI):
    python -B scripts/tests/test_story_run_s5_n1_frozen.py --capture <fixtures dir>

This file is CI's (`story_run_*` is a slow-tier name): a builder never runs the compare locally (plans/builder-rules.md 7b).
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from story_run_common import stub_calls  # noqa: E402
import test_story_run_s5_parallel as P  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "s5-n1-frozen"
THREE_WINDOWS = [["TC-1"], ["TC-2"], ["TC-3"]]
ROUTES = {("TC-1",): ["mechanical"], ("TC-2",): ["test_defect", "close"]}


def mask(text: str, root, task_root) -> str:
    """M1 and M2."""
    plugin = Path(harness.SCRIPTS).resolve().parent
    for path, name in ((task_root, "<task>"), (root, "<root>"), (plugin, "<plugin>")):      # the longer path first: the task folder sits under the root
        for form in (str(path), str(path).replace("\\", "/"), str(path).replace("/", "\\")):
            text = text.replace(form, name)
    text = re.sub(r"<(?:plugin|task|root)>[^\s`'\"]*", lambda m: m.group(0).replace("\\", "/"), text)       # M3: one separator after a masked folder
    return re.sub(r"\$\d+\.\d+", "<cost>", text.replace("\r\n", "\n"))                                       # M4: one line ending; M2: the cost


def capture() -> dict:
    """One serial S5 story through a real `Driver` and real stub processes; everything a window leaves, in the order it was left."""
    ctl = {"roles": {P.AUTO: {"result": "qa-automator S5 window · ok"}, P.CRIT: {"result": "qa-code-critic S5 window · ok"}}}
    root, driver, world = P.rig(THREE_WINDOWS, parallel_windows=1, ctl=ctl)
    try:
        world.routes.update(ROUTES)
        got = P.until_closed(driver, world)
        task = world.task_root
        calls = [{"kind": c["kind"], "role": c["role"], "resume": bool(c["resume"]), "prompt": mask(c["prompt"], root, task)}
                 for c in stub_calls(root)]
        finishes = [{"role": f["role"], "scope": list(f["key"]), "args": [mask(a, root, task) for a in f["args"]],
                     "others_open": [list(k) for k in f["others_open"]], "refused": bool(f.get("refused"))} for f in world.finishes]
        return {"calls": calls,
                "events": {"world": [list(e) for e in world.events], "finishes": finishes,
                           "errors": [type(e).__name__ for e, _o in got if e], "closed": world.closed()},
                "state_keys": sorted(k for k in driver.state if k != "noted"),
                "console": [mask(o, root, task) for _e, o in got]}
    finally:
        harness.cleanup(root)


def frozen(name: str):
    path = FIXTURES / (name + ".json")
    if not path.exists():
        raise SystemExit(f"test_story_run_s5_n1_frozen: the frozen capture {path} is missing (capture it on the pre-TR3-6 tree, see the docstring)")
    return json.loads(path.read_text(encoding="utf-8"))


def first_difference(live, was) -> str:
    """Where two lists first differ, for a red line that says which call / event / line moved."""
    for i in range(max(len(live), len(was))):
        a, b = (live[i] if i < len(live) else "<absent>"), (was[i] if i < len(was) else "<absent>")
        if a != b:
            return f"first difference at #{i}: live {json.dumps(a)[:600]} | frozen {json.dumps(b)[:600]}"
    return ""


def compare(label: str, live, was) -> None:
    detail = first_difference(live, was) if isinstance(live, list) and isinstance(was, list) else ""
    harness.check(f"n1 frozen: {label}", live == was, detail or f"live {json.dumps(live)[:600]} | frozen {json.dumps(was)[:600]}")


LIVE: dict = {}


def live() -> dict:
    if not LIVE:
        LIVE.update(capture())
    return LIVE


def n1_frozen_calls():
    compare("every call of the story (kind, role, resume, prompt) equals the pre-TR3-6 capture, in order", live()["calls"], frozen("calls"))


def n1_frozen_events():
    compare("the events, finish rows (role, scope, arguments), errors and closure equal the pre-TR3-6 capture", live()["events"], frozen("events"))


def n1_frozen_state_keys():
    compare("the keys of the driver state equal the pre-TR3-6 capture", live()["state_keys"], frozen("state_keys"))


def n1_frozen_console():
    compare("the console of every entry equals the pre-TR3-6 capture (M1, M2 masked)", live()["console"], frozen("console"))


SCENARIOS = [n1_frozen_calls, n1_frozen_events, n1_frozen_state_keys, n1_frozen_console]


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--capture":
        out = Path(sys.argv[2])
        out.mkdir(parents=True, exist_ok=True)
        with contextlib.redirect_stdout(io.StringIO()):
            record = capture()
        for name in ("calls", "events", "state_keys", "console"):
            (out / (name + ".json")).write_text(json.dumps(record[name], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("captured:", {k: len(v) for k, v in record.items()})
        return
    from story_run_common import run_scenarios
    shown, held = sys.stdout, io.StringIO()
    sys.stdout = held
    try:
        run_scenarios([], SCENARIOS)
    finally:
        sys.stdout = shown
    failed = [name for ok, name in harness.RESULTS if not ok]
    if failed:      # CI shows the first lines that start with FAIL only: the whole list of this file goes first, in ONE line
        print("FAIL (the whole list of this file): " + " | ".join(failed))
    print(held.getvalue(), end="")
    harness.finish("test_story_run_s5_n1_frozen")


if __name__ == "__main__":
    main()
