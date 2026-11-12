#!/usr/bin/env python3
"""t-2147 TR3-9 C0 (w1_frozen_calls, w1_frozen_events, w1_frozen_state_keys, w1_frozen_console): the manual half of S6 at `manual.walkers` 1 (the
serial road, one lane per entry) does what it did BEFORE the S6 lane scheduler (TR3-9 C1) existed.

The frozen side is a capture of ONE stub-driven S6 manual story, taken ONCE from the tree after TR3-9 A + B + D and before any C1 or C2 byte
(the capture commit is recorded in `docs/tasks/specs/t-2147-tr3-9-walker-lanes.md`, Part C0) and committed in `fixtures/s6-w1-frozen/`
(`calls.json`, `events.json`, `state_keys.json`, `console.json`). The live side runs the same story through the CURRENT code and compares.
Both sides run through the one function `capture`, so the capture cannot drift from the compare. The tree at capture has no `manual.walkers`
reader (F6), so the road under test is the only road and the test needs no `seed()` pin: once C1 adds the reader, walkers 1 (or no key under a
pin of 1) must read as today's road, which is what this file proves.

The story: four prepared guest manual cases TC-1..TC-4 (one lane per entry: `walk_lanes` cuts guests at three, so lanes [TC-1, TC-2, TC-3] and
[TC-4]); a REAL `Driver`, real `run_manual_block`, `run_role`, `run_claude`, `walk_before` and `_launch` (one stub `claude` process per
lane); stand-ins (one place each, `World.install`): `py` (the `story_step.py` verbs start / bind / finish, `stage_done.py`, `walk_session.py
open` answers exit 3 so every lane runs on the recorder road, every other script answers 0), the controller (`FakeController`: state,
prepare, apply), `controller_state`, `stage_scope`, `manual_prepare` / `manual_policy` / `manual_order` / `manual_request_paths`, the stand and
build checks, `question_threshold`, `repair_limit_gate`, `handoff`, `system_file`. Three entries: lane 1, lane 2, then the close with no lane
left (`manual_close`).

Volatile fields, masked on both sides (each mask named here and nowhere else):
  - M1 the temp project root, the artifacts folder of the task and the plugin root (the checkout the test runs from, named in every role
    prompt): replaced by `<root>`, `<task>` and `<plugin>` (also with `/` and `\\` swapped);
  - M2 the cost the progress line prints (`$0.0123`): replaced by `<cost>`;
  - M3 the path separator after a masked folder (`<plugin>\\scripts/x.py` on Windows, `/` on Linux): `/` throughout;
  - M4 the line ending of a prompt (`\\r\\n` where the driver writes text on Windows): `\\n`;
  - M5 the key `noted` of the driver state is left out of `state_keys` (it holds one-time notes, written by whichever code path met them);
  - M6 a duration or a process id a console line prints (`12.3s`, `pid 123`): replaced by `<secs>` and `<pid>` (none appeared at capture; the
    mask is the same one a progress line would need and stays inert while no such text is printed);
  - M7 the two byte figures of the `note: brief: ... (5,480 B, 4,174 B against the ceiling)` line: replaced by `<bytes>` (they count the real brief, which
    depends on the install path length, AR-4); applied to the live console and to the fixture text at compare time, the rest of the line stays.
A difference that is not one of these is a finding: a change of the serial road. Never mask it.

Capture (a builder or a lead, once, on the tree before C1, never in CI):
    python -B scripts/tests/test_story_run_s6_w1_frozen.py --capture <fixtures dir>
Retaken on 12.11.2026 at tree 8afd343 (the owner's word, t-107): the prompt gained the input line of the story's first-look record (`work/first-look.yaml`,
`brief_pack.FIRST_LOOK_FILE`) and the brief note prints `N budget B against the ceiling` (2b1b36c); `events` and `state_keys` came out byte-equal.

This file is CI's (`story_run_*` is a slow-tier name): a builder never runs the compare in CI's place (plans/builder-rules.md 7b).
"""
import contextlib
import io
import json
import re
import sys
import threading
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from story_run_common import driver_for, seed, set_control, stub_calls  # noqa: E402
import test_story_run_s5_parallel as P  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "s6-w1-frozen"
KEY = "QA-9"
RUNNER = "qa-runner"
CASES = ["TC-1", "TC-2", "TC-3", "TC-4"]
START = ("dispatched {id} (revision 1)\n--- Agent prompt, verbatim ---\nArtifacts dir: {root}\nDispatch: {id}.\n"
         "--- the moment the Agent call returns ---\n")


class World:
    """The controller's S6 manual record as the driver reads it, kept by the fake `py` and the fake controller."""

    def __init__(self, task_root, cases):
        self.task_root, self.lock, self.cases = task_root, threading.RLock(), list(cases)
        self.dispatches, self.events, self.py_rows, self.waits = {}, [], [], []

    def done_cases(self) -> set:
        with self.lock:
            return {c for d in self.dispatches.values() if d.get("status") == "accepted" for c in d.get("manual_case_ids") or []}

    def py(self, script, *args, check=False, expect=""):
        with self.lock:
            self.py_rows.append([script] + [str(a) for a in args])
            if script == "stage_done.py":
                self.events.append(["stage_done"] + [str(a) for a in args if str(a) != str(self.task_root)])
                return 0, ""
            if script == "walk_session.py":
                self.events.append(["walk_session", str(args[0]) if args else ""])
                return 3, "walk_session open: the stand-in answers that no session can be opened"
            if script != "story_step.py" or not args:
                return 0, ""
            verb, opts = args[0], P.flags(args)
            if verb == "start":
                did = next((d for d, r in self.dispatches.items() if r["role"] == opts["--role"] and r["status"] == "running"), None)
                if did is None:
                    return 1, "story_step start: the stand-in knows no running dispatch to resume"
                self.events.append(["start", did])
                return 0, START.format(id=did, root=self.task_root)
            if verb == "finish":
                did = opts["--dispatch-id"]
                self.dispatches[did]["status"] = "accepted"
                self.events.append(["finish", did, "complete" if "--not-complete" not in args else "not-complete"])
                return 0, f"accepted {did}\nnext: {{}}"
            self.events.append([verb])
            return 0, ""

    def controller_class(self):
        world = self

        class FakeController:
            def __init__(self, task_root, wait_seconds=0.0):
                world.waits.append(wait_seconds)

            def state(self):
                with world.lock:
                    return {"dispatches": {k: dict(v) for k, v in world.dispatches.items()}}

            def prepare(self, options):
                return {"dispatch_request": {"id": options["id"], "stage": options["stage"], "role": options["role"],
                                             "scope": list(options["scope"])}}

            def apply(self, operation, request):
                assert operation == "dispatch"
                with world.lock:
                    world.dispatches[request["id"]] = dict(request, status="running")
                    world.events.append(["register", request["id"], list(request["scope"])])
        return FakeController

    def install(self, driver):
        driver.py = self.py
        driver.controller_state = lambda: self.state_of()
        driver.stage_scope = lambda stage, kind="": {"scope": list(self.cases) if kind == "manual" else []}
        driver.manual_order = lambda given: list(given)
        driver.manual_done = lambda: self.done_cases()
        driver.manual_prepare = lambda case: ([f"OB-{case}"], "", "")
        driver.manual_policy = lambda case: "api"
        driver.manual_gate_note = lambda: None
        driver.manual_request_paths = lambda block: [f"work/evidence/manual/{c}/request.json" for c in block]
        driver.stand_check, driver.build_check = (lambda *a, **k: None), (lambda *a, **k: None)
        driver.code_only = lambda stage, reason, evidence: self.events.append(["code_only", stage, reason, list(evidence)])
        driver.question_threshold = lambda *a, **k: None
        driver.repair_limit_gate = lambda *a, **k: None
        driver.handoff = lambda role, stage, dispatch, result: result["result"]
        driver.system_file = lambda role, dispatch, scope: None
        return self

    def state_of(self) -> dict:
        with self.lock:
            return {"dispatches": {k: dict(v) for k, v in self.dispatches.items()}}


def mask(text: str, root, task_root) -> str:
    """M1 to M4, M6 and M7."""
    plugin = Path(harness.SCRIPTS).resolve().parent
    for path, name in ((task_root, "<task>"), (root, "<root>"), (plugin, "<plugin>")):      # the longer path first: the task folder sits under the root
        for base in (str(path), str(Path(path).resolve())):         # the path as seeded and as the driver resolves it (8.3 and long names on Windows)
            for form in (base, base.replace("\\", "/"), base.replace("/", "\\")):
                text = text.replace(form, name)
    text = re.sub(r"<(?:plugin|task|root)>[^\s`'\"]*", lambda m: m.group(0).replace("\\", "/"), text)       # M3: one separator after a masked folder
    text = re.sub(r"\$\d+\.\d+", "<cost>", text.replace("\r\n", "\n"))                                         # M4: one line ending; M2: the cost
    text = re.sub(r"\b\d+(?:\.\d+)?s\b", "<secs>", text)                                                       # M6: a duration
    text = re.sub(r"\bpid[ =:]*\d+", "pid <pid>", text)                                                        # M6: a process id
    return mask_brief_bytes(text)


BRIEF_BYTES = re.compile(r"\(\d[\d,]* B, \d[\d,]* (?:budget )?B against the ceiling\)")      # both labels the product has printed: `N B, N B` and `N B, N budget B`


def mask_brief_bytes(text: str) -> str:
    """M7: the two byte figures of the `note: brief:` line depend on the install path (AR-4), so they are replaced by `<bytes>`; the rest of the line (the label included) stays."""
    return BRIEF_BYTES.sub(lambda m: "(<bytes> B, <bytes> " + ("budget " if "budget" in m.group(0) else "") + "B against the ceiling)", text)


def enter(driver, world):
    out, error = io.StringIO(), None
    with mock.patch("controller.Controller", world.controller_class()), contextlib.redirect_stdout(out):
        try:
            driver.stage_S6()
        except BaseException as exc:      # noqa: BLE001 - the case reads what the stage raised
            error = exc
    return error, out.getvalue()


def capture() -> dict:
    """One S6 manual story through a real `Driver` and real stub processes; everything a lane leaves, in the order it was left."""
    root, task_root, env = seed(KEY, parallel_windows=1)
    set_control(root, {"roles": {RUNNER: {"result": "qa-runner S6 manual · ok"}}})
    report = task_root / "work" / "run-report.json"
    report.write_text("{}", encoding="utf-8")                # the automated half's report: `walk_before` finalizes only when it is absent
    driver = driver_for(root, env, KEY, max_boundaries=1000)
    world = World(task_root, CASES).install(driver)
    try:
        got = []
        import test_controller_state as BASE
        for turn in range(3):                                 # lane 1, lane 2, then the close with no lane left
            if turn == 2:                                     # the consumer (the failure analyst) has judged the last runner window
                BASE.record_stage_acceptance(task_root, "S6", "S6-qa-runner-2")
            got.append(enter(driver, world))
        calls = [{"kind": c["kind"], "role": c["role"], "resume": bool(c["resume"]), "prompt": mask(c["prompt"], root, task_root)}
                 for c in stub_calls(root)]
        events = [[(mask(x, root, task_root) if isinstance(x, str) else x) for x in e] for e in world.events]
        py_rows = [[mask(x, root, task_root) for x in row] for row in world.py_rows]
        return {"calls": calls,
                "events": {"world": events, "py": py_rows, "errors": [type(e).__name__ + ": " + mask(str(e), root, task_root) for e, _o in got if e],
                           "accepted": sorted(world.done_cases())},
                "state_keys": sorted(k for k in driver.state if k != "noted"),
                "console": [mask(o, root, task_root) for _e, o in got]}
    finally:
        harness.cleanup(root)


def frozen(name: str):
    path = FIXTURES / (name + ".json")
    if not path.exists():
        raise SystemExit(f"test_story_run_s6_w1_frozen: the frozen capture {path} is missing (capture it before C1, see the docstring)")
    return json.loads(path.read_text(encoding="utf-8"))


def first_difference(live, was) -> str:
    """Where two lists first differ, for a red line that says which call / event / line moved."""
    for i in range(max(len(live), len(was))):
        a, b = (live[i] if i < len(live) else "<absent>"), (was[i] if i < len(was) else "<absent>")
        if a != b:
            return f"first difference at #{i}: live {json.dumps(a)[:600]} | frozen {json.dumps(b)[:600]}"
    return ""


def compare(key: str, label: str, live, was) -> None:
    if isinstance(live, dict) and isinstance(was, dict):
        for part in sorted(set(live) | set(was)):
            if live.get(part) != was.get(part):
                a, b = live.get(part), was.get(part)
                detail = first_difference(a, b) if isinstance(a, list) and isinstance(b, list) else f"live {json.dumps(a)[:600]} | frozen {json.dumps(b)[:600]}"
                harness.check(f"{key}: {label}", False, f"part `{part}`: {detail}")
                return
    detail = first_difference(live, was) if isinstance(live, list) and isinstance(was, list) else ""
    harness.check(f"{key}: {label}", live == was, detail or f"live {json.dumps(live)[:600]} | frozen {json.dumps(was)[:600]}")


LIVE: dict = {}


def live() -> dict:
    if not LIVE:
        LIVE.update(capture())
    return LIVE


def w1_frozen_calls():
    compare("w1_frozen_calls", "every call of the story (kind, role, resume, prompt) equals the pre-C1 capture, in order", live()["calls"], frozen("calls"))


def w1_frozen_events():
    compare("w1_frozen_events", "the events (registrations, starts, finishes, closes), script calls, errors and accepted cases equal the pre-C1 capture",
            live()["events"], frozen("events"))


def w1_frozen_state_keys():
    compare("w1_frozen_state_keys", "the keys of the driver state equal the pre-C1 capture", live()["state_keys"], frozen("state_keys"))


def w1_frozen_console():
    compare("w1_frozen_console", "the console of every entry equals the pre-C1 capture (M1, M2, M6, M7 masked)", live()["console"],
            [mask_brief_bytes(x) for x in frozen("console")])


def w1_frozen_brief_bytes_mask():
    line = "note: brief: qa-factory/artifacts/QA-9/work/briefs/S6-qa-runner-1.md ({a} B, {b} B against the ceiling)"
    one, two = line.format(a="5,480", b="4,174"), line.format(a="5,554", b="4,248")
    changed = line.format(a="5,480", b="4,174").replace("against the ceiling", "against the limit")
    held = mask_brief_bytes(one) == mask_brief_bytes(two) and "5,480" not in mask_brief_bytes(one)
    harness.check("w1_frozen_brief_bytes_mask: M7 holds for both byte variants (5,480/4,174 and 5,554/4,248)", held, mask_brief_bytes(one) + " | " + mask_brief_bytes(two))
    harness.check("w1_frozen_brief_bytes_mask: a wording change on the same line is still caught (negative control)",
                  mask_brief_bytes(changed) != mask_brief_bytes(one), mask_brief_bytes(changed))


SCENARIOS = [w1_frozen_calls, w1_frozen_events, w1_frozen_state_keys, w1_frozen_console, w1_frozen_brief_bytes_mask]


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
    if len(sys.argv) > 2 and sys.argv[1] == "--fixtures":          # the negative control reads a COPY of the fixture folder
        global FIXTURES
        FIXTURES = Path(sys.argv[2])
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
    harness.finish("test_story_run_s6_w1_frozen")


if __name__ == "__main__":
    main()
