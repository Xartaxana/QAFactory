"""test_place_session.py - every S7 triage dispatch gets the place lines and the walk session in `run_role` (spec t-1991, node U3b).

Run: python -B -m pytest -p no:cacheprovider scripts/tests/test_place_session.py -q      or      python -B scripts/tests/test_place_session.py

The Driver is stubbed the way test_place_driver.py does it (`Driver.__new__`, the few attributes `run_role` / `resume_role` read); `py` records the
`walk_session.py` calls and answers as the test says, `run_claude` records the prompt and raises a marker (no role runs, no stand, no browser).
Fast. Mutation -> killing test (named, run once in the node's report):
  the `finally` of `run_role` without `s7_settle_close` -> test_session_closed_when_role_crashes
Also here (the owed items of the node): `verdict` on a settle/control item is refused with the door `place_answers.py write`; a lifted
code-reading draft at gate B falls to the reproduction words.
"""
import atexit
import contextlib
import inspect
import io
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness  # noqa: E402

import gate_brief  # noqa: E402
import place_answers as PA  # noqa: E402
import story_run  # noqa: E402
import story_step  # noqa: E402
import test_place_answers as TPA  # noqa: E402
import walk_session as WS  # noqa: E402
import test_walk_places as WP  # noqa: E402

D = "S7-qa-failure-analyst-1"
INV = "S7-qa-failure-analyst-2"
TEXTS = json.loads(PA.DATA_PATH.read_text(encoding="utf-8"))["gap_reasons"]


class Stop(Exception):
    """Raised by the stubbed `run_claude` / `handoff`: the role 'crashed' or the test has seen what it needed."""


def record(dispatch, binding=None):
    row = {"id": dispatch, "stage": "S7", "role": "qa-failure-analyst", "status": "running"}
    if binding:
        row["request_binding"] = {"purpose": binding}
    return row


class Rig:
    """A Driver with what `run_role` / `resume_role` read. `answers` maps a walk_session.py subcommand to its (exit, text)."""

    def __init__(self, dispatches, answers=None, saved=None, dispatch=D):
        self.task = TPA.story()
        self.calls, self.prompts, self.dispatch = [], [], dispatch
        d = self.d = story_run.Driver.__new__(story_run.Driver)
        d.task_root, d.task, d.plugin, d.scripts = self.task, self.task.name, harness.PLUGIN_ROOT, harness.PLUGIN_ROOT / "scripts"
        d.state_dir = self.task / "state"
        d.state = {"sessions": {dispatch: "sid"}, "pending_words": {}}
        d.controller_state = lambda: {"dispatches": dict(dispatches)}
        d.pipeline = lambda: {}
        d.stages = lambda: {"S7": {}}
        d.progress_line = lambda: None
        d.save_state = lambda: None
        d.system_file = lambda role, dispatch, scope: None
        d.walk_reopen = lambda dispatch, reopen=True: ([], "")
        d.record_running = lambda *a, **k: None
        d.retire_infra_result = lambda *a, **k: False
        d.step = lambda *a: f"dispatched {dispatch} (revision 1)\n--- Agent prompt, verbatim\nPROMPT of {dispatch}\n--- the moment the Agent call returns"
        d.handoff = lambda *a, **k: (_ for _ in ()).throw(Stop("handoff"))
        answers = answers or {}

        def py(script, *argv):
            self.calls.append((script, argv))
            return answers.get(argv[0] if script == "walk_session.py" else script, (0, '{"status": "ready"}'))
        d.py = py

        def run_claude(kind, prompt, **kw):
            self.prompts.append(prompt)
            raise Stop("role crashed")
        d.run_claude = run_claude
        if saved:
            (self.task / "state" / "driver-runs").mkdir(parents=True, exist_ok=True)
            (self.task / "state" / "driver-runs" / f"{dispatch}.json").write_text(json.dumps(saved), encoding="utf-8")

    def walk_calls(self, name):
        return [argv for script, argv in self.calls if script == "walk_session.py" and argv[0] == name]

    def run(self, call):
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                call()
        except Stop as stop:
            return str(stop), out.getvalue()
        return "", out.getvalue()


def fresh(rig, role="qa-failure-analyst", stage="S7", purpose=""):
    return rig.run(lambda: rig.d.run_role(stage, role, purpose=purpose, extra=["EXTRA LINE"]))


def patched_rework():
    """The rework branch writes brief, form and card through story_step: replaced for the test (restore with the returned callable)."""
    saved = (story_step._write_dispatch_files, story_step._project_rel, story_step._prompt)
    story_step._write_dispatch_files = lambda *a, **k: None
    story_step._project_rel = lambda *a, **k: "brief"
    story_step._prompt = lambda *a, **k: f"REWORK PROMPT of {a[3]}"

    def restore():
        story_step._write_dispatch_files, story_step._project_rel, story_step._prompt = saved
    return restore


# --- the lines ----------------------------------------------------------------------------------------------------------------------

def test_lines_for_fresh_and_rework_dispatches():
    rig = Rig({D: record(D)})
    fresh(rig)
    prompt = rig.prompts[0]
    assert "Places to settle (2):" in prompt and f"The walk session `{D}` is open" in prompt, prompt[:300]
    assert prompt.index("Places to settle") < prompt.index("EXTRA LINE"), "E3b.1: the lines go before `extra`"
    assert prompt.index("PROMPT of") < prompt.index("Places to settle")
    restore = patched_rework()                       # a seam / scribe-reject rework: the same lines from the same site
    try:
        rework = Rig({D: record(D)})
        rework.run(lambda: rework.d.run_role("S7", "qa-failure-analyst", rework={"id": D, "scope": [], "reason": "the scribe sent it back"},
                                             extra=["EXTRA LINE"]))
    finally:
        restore()
    again = rework.prompts[0]
    assert again.startswith("REWORK PROMPT") and "Places to settle (2):" in again and f"The walk session `{D}` is open" in again, again[:300]
    assert len(rework.walk_calls("open")) == 1


def test_no_lines_no_session_for_investigation():
    rig = Rig({INV: record(INV, "investigation")}, dispatch=INV)
    fresh(rig, purpose="investigation")
    assert rig.walk_calls("open") == [] and rig.walk_calls("close") == [], rig.calls
    assert "Places to settle" not in rig.prompts[0] and "walk session" not in rig.prompts[0], rig.prompts[0]
    by_record = Rig({INV: record(INV, "investigation")}, dispatch=INV)       # the purpose is read from the record too (a rework has none)
    fresh(by_record)
    assert by_record.walk_calls("open") == [] and "Places to settle" not in by_record.prompts[0]
    other = Rig({D: record(D)})                                                # another role, or another stage: nothing either
    fresh(other, role="qa-code-critic")
    assert other.walk_calls("open") == [] and "Places to settle" not in other.prompts[0]
    # an unreadable kind answers on the investigation's side (the invariant: an investigation never gets either)
    broken = Rig({D: record(D)})
    broken.d.controller_state = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    _, printed = fresh(broken)
    assert broken.walk_calls("open") == [] and "boom" in printed


# --- the session --------------------------------------------------------------------------------------------------------------------

def test_session_opened_only_when_role_runs():
    saved = {"result": "done", "session_id": "sid", "is_error": False}
    reused = Rig({D: record(D)}, saved=saved)
    reused.run(lambda: reused.d.run_role("S7", "qa-failure-analyst"))         # a saved result: the role does not run again
    assert reused.prompts == [] and reused.walk_calls("open") == [] and reused.walk_calls("close") == [], reused.calls
    runs = Rig({D: record(D)})
    fresh(runs)
    opened = runs.walk_calls("open")
    assert len(opened) == 1 and opened[0][:2] == ("open", "--task-root"), runs.calls
    argv = list(opened[0])
    for flag, value in (("--walk", D), ("--place", "settle"), ("--items", "req-R-1,req-R-2")):     # the place ids of the dispatch
        assert argv[argv.index(flag) + 1] == value, (flag, argv)
    assert runs.d.state["s7_walk"][D] == {"state": "closed", "items": ["req-R-1", "req-R-2"]}                  # opened ready, closed with the dispatch
    assert len(runs.walk_calls("close")) == 1


def test_session_closed_when_role_crashes():
    rig = Rig({D: record(D)})
    why, _ = fresh(rig)
    assert why == "role crashed" and len(rig.walk_calls("open")) == 1
    assert len(rig.walk_calls("close")) == 1, rig.calls                       # E3b.2: the `finally` closed it
    assert [a[0] for s, a in rig.calls if s == "walk_session.py"] == ["open", "close"]
    refused = Rig({D: record(D)})                                              # a Refusal is the same
    refused.d.run_claude = lambda *a, **k: (_ for _ in ()).throw(story_run.Refusal("refused", dispatch=D))
    try:
        refused.d.run_role("S7", "qa-failure-analyst")
    except story_run.Refusal:
        pass
    assert len(refused.walk_calls("close")) == 1


def test_session_failure_recorded_for_gap_reason():
    down = Rig({D: record(D)}, answers={"open": (3, '{"status": "not_started", "cause": "stand_busy", "reason": "the stand is held by another run: stand_busy"}')})
    _, printed = fresh(down)
    assert down.d.state["s7_walk"][D]["failed"] == "stand" and "stand_busy" in down.d.state["s7_walk"][D]["why"]
    assert down.d.s7_gap_reason() == TEXTS[1]                                  # text 2: the stand could not be reached
    assert down.walk_calls("close") == [], "a session that never opened is not closed"
    line = next(x for x in down.prompts[0].splitlines() if x.startswith("no walk session: "))
    assert "stand_busy" in line and "manual_capture.py ui|http --case settle-<place>" in line and "answer `impossible` with that why" in line
    assert "S7: " in printed and "no walk session" in printed
    # t-2027 F11: the class is read from the answer's `cause`, never from a word in the text ("understand", a path holding "stand")
    word = Rig({D: record(D)}, answers={"open": (3, '{"status": "not_started", "cause": "", "reason": "cannot understand the layout of /stand/x"}')})
    fresh(word)
    assert word.d.state["s7_walk"][D]["failed"] == "session" and word.d.s7_gap_reason() == TEXTS[2], word.d.state["s7_walk"][D]
    sick = Rig({D: record(D)}, answers={"open": (2, "walker absent")})
    fresh(sick)
    assert sick.d.state["s7_walk"][D]["failed"] == "session" and sick.d.s7_gap_reason() == TEXTS[2]
    raised = Rig({D: record(D)})
    raised.d.py = lambda *a: (_ for _ in ()).throw(OSError("no python"))
    fresh(raised)                                                              # P1: the role still runs
    assert raised.d.state["s7_walk"][D]["failed"] == "session" and raised.prompts


def test_unreadable_place_list_opens_no_session():
    rig = Rig({D: record(D)})
    original = PA.places
    PA.places = lambda root: {"places": [], "unreadable": [("register", "no Requirement column")]}
    try:
        fresh(rig)
    finally:
        PA.places = original
    assert rig.walk_calls("open") == [] and rig.d.state["s7_walk"][D]["failed"] == "session", rig.d.state
    assert "could not be listed whole" in rig.d.state["s7_walk"][D]["why"] and rig.d.s7_gap_reason() == TEXTS[2]


def test_step_on_a_place_id_gives_a_capture_the_answer_accepts():
    with WP.lane("settle", items=("new-walked",)) as rig:          # the lane the driver opens, items = place ids (a `new-` place needs no register)
        assert rig.step(WP.GO, item="new-walked")[0] == 0
        code, answer = rig.call("look", item="new-walked")
        capture = answer["look"]["captures"][0]
        assert code == 0 and "/settle-new-walked/a1/" in capture, capture
        record = TPA.ans("new-walked", "not_a_bug", None, quote="heading: Cart", why="the cart page shows the cart")
        record["seen"]["capture"] = capture
        (rig.t.task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "stages": {}}), encoding="utf-8")
        out = PA.write(rig.t.task, D, "new-walked", record)
        assert PA.settled_answer(rig.t.task, "new-walked")[1] == "settled", out
        refused = TPA.ans("new-free", "not_a_bug", None, quote="heading: Cart", why="x")      # the old `free` item: a capture under settle-free is no capture of the place
        refused["seen"]["capture"] = capture
        try:
            PA.write(rig.t.task, D, "new-free", refused)
        except Exception as exc:
            assert "capture" in str(exc).lower(), exc
        else:
            raise AssertionError("a capture of another place must be refused")


def test_dead_session_reopen_door():
    rig = Rig({D: record(D)})
    fresh(rig)
    text = "\n".join(rig.prompts)
    assert "If a call says it ended" in text, text
    for words in (f"walk_session.py\" open --task-root qa-factory/artifacts/{rig.task.name}/ --walk {D} --place settle --items req-R-1,req-R-2",
                  "answer `impossible` with why 'the walk session could not be opened'", "manual_capture.py\" ui|http", "settle-<place id>"):
        assert words in text, words
    assert "walk_session.py open" in json.loads((harness.PLUGIN_ROOT / "references" / "role-commands.json").read_text(encoding="utf-8"))["commands"]


def test_resume_reopens_session():
    dead = Rig({D: record(D)})
    why, _ = dead.run(lambda: dead.d.resume_role("S7", "qa-failure-analyst", D, "go on"))
    assert why == "role crashed"
    assert len(dead.walk_calls("open")) == 1 and len(dead.walk_calls("close")) == 1, dead.calls     # E3b.5, and closed with the resume
    assert dead.calls.index(("walk_session.py", dead.walk_calls("open")[0])) < dead.calls.index(("walk_session.py", dead.walk_calls("close")[0]))
    assert f"The walk session `{D}` is open" in dead.prompts[0] and dead.prompts[0].startswith("The person answered")
    alive = Rig({D: record(D)})
    (alive.task / "state" / "walks").mkdir(parents=True)
    (alive.task / "state" / "walks" / f"{D}.json").write_text(json.dumps({"state": "ready", "pid": 1, "items": ["free"]}), encoding="utf-8")
    saved, WS.alive = WS.alive, lambda record: True
    try:
        alive.run(lambda: alive.d.resume_role("S7", "qa-failure-analyst", D, "go on"))
    finally:
        WS.alive = saved
    assert alive.walk_calls("open") == [] and len(alive.walk_calls("close")) == 1, alive.calls     # a live server is left alone
    inv = Rig({INV: record(INV, "investigation")}, dispatch=INV)
    inv.run(lambda: inv.d.resume_role("S7", "qa-failure-analyst", INV, "go on"))
    assert inv.walk_calls("open") == [] and "walk session" not in inv.prompts[0]                 # E3b.6


def settle_record(rig, state="closed", place="settle"):
    """The record a settle session leaves: the walk path, place ids as items (t-2027 F1: the walker's hook must not read it as a case lane)."""
    walks = rig.task / "state" / "walks"
    walks.mkdir(parents=True, exist_ok=True)
    (walks / f"{rig.dispatch}.json").write_text(json.dumps({"walk": rig.dispatch, "state": state, "pid": 0, "actors": ["guest"],
                                                            "items": ["req-R-1", "req-R-2"], "place": place}), encoding="utf-8")


def real_hook(rig):
    """The rig stubs `walk_reopen`; here the REAL one runs (t-2027 F1: the stub hid the defect), and `walk_after` records its lanes."""
    del rig.d.walk_reopen
    rig.after_lanes = []
    rig.d.walk_after = lambda lane, dispatch, result: rig.after_lanes.append(lane)
    return rig


def case_opens(rig):
    return [argv for argv in rig.walk_calls("open") if "--place" not in argv]


def test_settle_record_is_no_case_walk_on_any_road():
    # road 1: a resume. Only the settle session opens (with --place), never a case lane over the place ids
    resumed = real_hook(Rig({D: record(D)}))
    settle_record(resumed)
    resumed.run(lambda: resumed.d.resume_role("S7", "qa-failure-analyst", D, "go on"))
    assert case_opens(resumed) == [] and resumed.after_lanes == [], (resumed.calls, resumed.after_lanes)
    assert len(resumed.walk_calls("open")) == 1 and "--place" in resumed.walk_calls("open")[0]
    # road 2: run_role continuation (no saved result, a record on disk)
    again = real_hook(Rig({D: record(D)}))
    settle_record(again)
    fresh(again)
    assert case_opens(again) == [] and again.after_lanes == [], (again.calls, again.after_lanes)
    # road 3: a saved result stands - no role runs and walk_after is not built over place ids
    saved = {"result": "done", "session_id": "sid", "is_error": False}
    done = real_hook(Rig({D: record(D)}, saved=saved))
    settle_record(done)
    done.run(lambda: done.d.run_role("S7", "qa-failure-analyst"))
    assert done.walk_calls("open") == [] and done.after_lanes == [], (done.calls, done.after_lanes)
    # a control record is no case walk either; a case record still is one
    control = real_hook(Rig({D: record(D)}))
    settle_record(control, place="control")
    assert control.d.walk_reopen(D, reopen=False) == ([], "")
    case = real_hook(Rig({D: record(D)}))
    settle_record(case, place="case")
    assert case.d.walk_reopen(D, reopen=False)[0] == ["req-R-1", "req-R-2"]


def test_failed_open_leaves_the_place_in_its_record():
    task = TPA.story()
    args = type("A", (), {"task_root": str(task), "walk": D, "items": "p1", "actor": "guest", "actor2": "", "parent_pid": 1, "place": "settle"})()
    seams = dict(WS.SEAMS)
    WS.SEAMS["spawn"] = lambda argv, log: None
    try:
        WS.open_walk(args, wait_s=0)
    finally:
        WS.SEAMS.clear()
        WS.SEAMS.update(seams)
    assert WS.read_record(task, D).get("place") == "settle", WS.read_record(task, D)


def test_odd_place_id_does_not_lose_the_session():
    """t-2027 F9: one id the lane cannot carry (`draft-a__b`, `case-TC/6`) opens no fewer places; the line names it with the capture road."""
    original = PA.places
    PA.places = lambda root: {"places": [{"id": "req-R-1"}, {"id": "draft-a__b"}, {"id": "case-TC/6"}, {"id": "req-R-2"}], "unreadable": []}
    try:
        rig = Rig({D: record(D)})
        fresh(rig)
    finally:
        PA.places = original
    argv = list(rig.walk_calls("open")[0])
    assert argv[argv.index("--items") + 1] == "req-R-1,req-R-2", argv
    assert rig.d.state["s7_walk"][D]["items"] == ["req-R-1", "req-R-2"] and rig.d.state["s7_walk"][D]["skipped"] == ["draft-a__b", "case-TC/6"]
    line = next(x for x in rig.prompts[0].splitlines() if x.startswith("Places the session cannot carry"))
    assert "draft-a__b" in line and "case-TC/6" in line and "manual_capture.py" in line, line


def test_session_line_carries_the_driver_pid_and_the_step_flags():
    """t-2027 F6/F7: the reopen door survives the role's shell (`--parent-pid <driver>`); the step words reach the analyst."""
    rig = Rig({D: record(D)})
    fresh(rig)
    text = "\n".join(rig.prompts)
    assert f"--parent-pid {story_run.os.getpid()}" in text, text
    assert "--line" in text and "--steps-file" in text, text
    assert "--items free" not in json.dumps(story_run.Driver.s7_settle_session.__doc__) and "--items free" not in text


def test_walk_card_rows_for_the_analyst():
    """t-2027 F5/F7: the Commands card gives the analyst the session's step words and no stale `--items free`."""
    rows = json.loads((harness.PLUGIN_ROOT / "references" / "role-commands.json").read_text(encoding="utf-8"))["commands"]
    for name in ("step", "look", "final", "status"):
        assert "qa-failure-analyst" in rows[f"walk_session.py {name}"]["roles"], name
    for name in ("verdict", "item", "done"):
        assert "qa-failure-analyst" not in rows[f"walk_session.py {name}"]["roles"], name
    assert "--items free" not in rows["walk_session.py open"]["input"]


def test_saved_result_retired_once_in_run_role():
    """t-2027 F12: the retire-infra block ran twice (merge residue)."""
    saved = {"result": "done", "session_id": "sid", "is_error": False}
    rig = Rig({D: record(D)}, saved=saved)
    seen = []
    rig.d.retire_infra_result = lambda *a, **k: seen.append(1) or False
    rig.run(lambda: rig.d.run_role("S7", "qa-failure-analyst"))
    assert len(seen) == 1, seen


def test_one_site_for_place_lines():
    assert "s7_place_lines" not in inspect.getsource(story_run.Driver.stage_S7), "U3b removed U3a's append from stage_S7"
    source = Path(story_run.__file__).read_text(encoding="utf-8")
    sites = re.findall(r"self\.s7_place_lines\(", source)
    assert len(sites) == 1 and "self.s7_place_lines(" in inspect.getsource(story_run.Driver.run_role), len(sites)


def test_one_site_for_neighbour_lines():
    """t-2187 N6: the neighbourhood hint has ONE call, in `run_role`, inside the S7 triage branch beside the place lines (an investigation and
    every other dispatch get none)."""
    assert "s7_neighbour_lines" not in inspect.getsource(story_run.Driver.stage_S7)
    source = Path(story_run.__file__).read_text(encoding="utf-8")
    sites = re.findall(r"self\.s7_neighbour_lines\(", source)
    body = inspect.getsource(story_run.Driver.run_role)
    assert len(sites) == 1 and "self.s7_neighbour_lines(" in body, len(sites)
    branch = body[body.index("        if triage:\n"):body.index("lines += list(extra)")]
    assert "self.s7_place_lines(" in branch and "self.s7_neighbour_lines(" in branch, branch


# --- the owed items -----------------------------------------------------------------------------------------------------------------

def test_verdict_refused_on_settle_and_control():
    task = TPA.story()
    for place in ("settle", "control"):
        walk = WS.Walk(task, "W1", ["p1"], ["guest"], place=place)
        code, answer = walk.op_verdict({"item": "p1", "verdict": {"thens": []}})
        assert code == 2 and answer["status"] == "refused", (place, code, answer)
        assert "place_answers.py write" in answer["problems"][0] and f"a {place} walk has no verdict" in answer["problems"][0]
    assert list((task / "work").glob("walks/*")) == [], "a refused verdict writes nothing"


def test_lifted_draft_falls_to_reproduction_words():
    base = harness.temp_project()
    TPA.ROOTS.append(base)
    task = base / "artifacts" / "LOCAL-1"
    drafts = task / "work" / "bug-drafts"
    drafts.mkdir(parents=True)
    for name, confirmation in (("cr-open.json", "unconfirmed"), ("cr-lifted.json", "reproduced_by_factory")):
        (drafts / name).write_text(json.dumps({
            "title": f"Candidate {name}", "impact": "money", "violates": "requirement:R-24", "evidence": "code-reading",
            "oracle": {"question": "Q7", "quote": "the price shown when added is kept"},
            "fact": {"id": "fact 1", "path": "src/lib/services/cartService.ts", "line": 103, "note": "total uses the DB price"},
            "check_state": "not_executed", "manual_steps": ["do it"], "confirmation": confirmation}), encoding="utf-8")
    import bug_records as BR
    real = BR.confirmation_of          # the word is computed from the reproduction on disk; a lifted draft is one whose walk the factory built
    BR.confirmation_of = lambda root, data, *facts, **kw: ("reproduced_by_factory", ["walk"], []) if "lifted" in data.get("title", "") else real(root, data, *facts, **kw)   # a draft reader passes `draft=True`
    try:
        text = gate_brief.render_gate_b("LOCAL-1", task)
    finally:
        BR.confirmation_of = real
    heads = [line for line in text.splitlines() if re.match(r"\d+\. \*\*Candidate", line)]
    assert len(heads) == 2, text
    lifted = next(h for h in heads if "cr-lifted" in h)
    opened = next(h for h in heads if "cr-open" in h)
    assert "by reading the code, not proven by a run" in opened, opened
    assert "by reading the code" not in lifted, lifted                         # the mark is for a draft nobody has run
    assert BR.reproduction_words({"confirmation": "reproduced_by_factory", "reproduced_how": ["walk"]}) in lifted, lifted
    assert text.count("the code: src/lib/services/cartService.ts:103") == 2     # the oracle and code line stays on both


def survey_record(rig, state="dead", stand="old", **extra):
    """The record of an optional dispatch's survey walk (S1 reference window, S3 first look): the stand it walked is named in it."""
    walks = rig.task / "state" / "walks"
    walks.mkdir(parents=True, exist_ok=True)
    body = {"walk": rig.dispatch, "state": state, "pid": 0, "actors": ["guest"], "items": ["free"], "place": "survey", "stand": stand, **extra}
    (walks / f"{rig.dispatch}.json").write_text(json.dumps({k: v for k, v in body.items() if v is not None}), encoding="utf-8")


def test_survey_record_reopens_on_its_stand_and_builds_no_case_lane():
    """t-2277 batch 2b D (critic t-2513 F2): a resumed role of a survey walk gets its session back on the stand of the record, with the actors
    and the place, and no case lane (no items come back); `reopen=False` opens nothing; a record with no stand opens on no guess."""
    rig = real_hook(Rig({D: record(D)}))
    survey_record(rig, actors=["acct", "guest"])
    items, words = rig.d.walk_reopen(D)
    assert items == [], items                                           # a survey walk is no case walk: nothing for `walk_after` to build
    opens = rig.walk_calls("open")
    assert len(opens) == 1, rig.calls
    argv = opens[0]
    assert argv[argv.index("--place") + 1] == "survey" and argv[argv.index("--env") + 1] == "old", argv
    assert argv[argv.index("--walk") + 1] == D and argv[argv.index("--actor") + 1] == "acct" and argv[argv.index("--actor2") + 1] == "guest", argv
    assert argv[argv.index("--items") + 1] == "free", argv
    assert "reopened on `old`" in words and "already captured is kept" in words, words
    quiet = real_hook(Rig({D: record(D)}))
    survey_record(quiet)
    assert quiet.d.walk_reopen(D, reopen=False) == ([], "") and quiet.walk_calls("open") == [], quiet.calls          # a saved result stands: no browser
    nostand = real_hook(Rig({D: record(D)}))
    survey_record(nostand, stand="")
    items, words = nostand.d.walk_reopen(D)
    assert items == [] and nostand.walk_calls("open") == [] and "names no stand" in words and "say what you did not walk" in words, words
    failed = real_hook(Rig({D: record(D)}, answers={"open": (3, "the stand did not answer")}))
    survey_record(failed)
    items, words = failed.d.walk_reopen(D)
    assert items == [] and "could not be reopened (the stand did not answer)" in words, words
    other = real_hook(Rig({D: record(D)}))
    settle_record(other, place="control")
    assert other.d.walk_reopen(D) == ([], "") and other.walk_calls("open") == [], other.calls                          # a control record: as before


def test_survey_session_words_reach_a_resumed_role():
    """The words of the reopened survey session are in the resume prompt (`resume_role`), though no lane is built."""
    rig = real_hook(Rig({D: record(D)}))
    survey_record(rig, state="dead")
    rig.run(lambda: rig.d.resume_role("S7", "qa-failure-analyst", D, "go on"))
    assert rig.prompts and "Your walk session was reopened on `old`" in rig.prompts[0], rig.prompts


def test_never_started_survey_record_is_not_reopened():
    """t-2548 B1: `open_walk` stamps a walk that never reached `ready` `did not start: ...` (with a stand when the server got that far). The
    failed S1 window says "walk nothing" already (FR-10); no road reopens that record or tells the role it was reopened - not `walk_reopen`,
    not `run_role` (after=None), not `resume_role`. A record that DID run and died is still reopened (control)."""
    for stand in ("old", ""):
        rig = real_hook(Rig({D: record(D)}))
        survey_record(rig, state="dead", stand=stand, reason="did not start: no route to old")
        assert rig.d.walk_reopen(D) == ([], "") and rig.walk_calls("open") == [], (stand, rig.calls)
    fresh_rig = real_hook(Rig({D: record(D)}))
    survey_record(fresh_rig, reason="did not start: no route to old")
    fresh_rig.run(lambda: fresh_rig.d.run_role("S1", "qa-runner", extra=["Reference window: walk nothing, write nothing"]))
    prompt = fresh_rig.prompts[0]
    assert fresh_rig.walk_calls("open") == [] and fresh_rig.walk_calls("close") == [], fresh_rig.calls
    assert "walk nothing, write nothing" in prompt and "reopened" not in prompt and "commands will be refused" not in prompt, prompt
    resumed = real_hook(Rig({D: record(D)}))
    survey_record(resumed, reason="did not start: no route to old")
    resumed.run(lambda: resumed.d.resume_role("S1", "qa-runner", D, "go on"))
    assert resumed.walk_calls("open") == [] and "reopened" not in resumed.prompts[0], (resumed.calls, resumed.prompts)
    control = real_hook(Rig({D: record(D)}))
    survey_record(control, state="dead", reason="idle for 900 s")
    assert "reopened on `old`" in control.d.walk_reopen(D)[1] and len(control.walk_calls("open")) == 1, control.calls


def test_reopened_survey_session_is_closed_when_the_role_ends():
    """t-2548 F1 (AR-25): a survey session the driver reopened is closed in the `finally` of `run_role` and of `resume_role` (the role here
    crashes: it is closed all the same); a dispatch whose session was not reopened here (a saved result stands, a never-started record, no
    record) gets no close - the lease is let go only where this driver took it."""
    runs = (("run_role", lambda r: r.d.run_role("S1", "qa-runner")), ("resume_role", lambda r: r.d.resume_role("S1", "qa-runner", D, "go on")))
    for name, call in runs:
        rig = real_hook(Rig({D: record(D)}))
        survey_record(rig, state="dead")
        rig.run(lambda: call(rig))
        closes = rig.walk_calls("close")
        assert len(rig.walk_calls("open")) == 1 and len(closes) == 1, (name, rig.calls)
        assert closes[0][closes[0].index("--walk") + 1] == D and rig.calls.index(("walk_session.py", closes[0])) > rig.calls.index(
            ("walk_session.py", rig.walk_calls("open")[0])), (name, rig.calls)
    saved = {"result": "done", "session_id": "sid", "is_error": False}
    stands = real_hook(Rig({D: record(D)}, saved=saved))
    survey_record(stands, state="dead")
    stands.run(lambda: stands.d.run_role("S1", "qa-runner"))
    assert stands.walk_calls("open") == [] and stands.walk_calls("close") == [], stands.calls          # a saved result: no role ran, nothing opened
    never = real_hook(Rig({D: record(D)}))
    never.run(lambda: never.d.resume_role("S1", "qa-runner", D, "go on"))
    assert never.walk_calls("close") == [], never.calls                                              # no record: not a walk
    failed = real_hook(Rig({D: record(D)}, answers={"open": (3, "the stand did not answer")}))
    survey_record(failed, state="dead")
    failed.run(lambda: failed.d.resume_role("S1", "qa-runner", D, "go on"))
    assert failed.walk_calls("close") == [], failed.calls                                            # the open failed: there is no session to close


def test_the_two_reopens_share_one_body():
    """t-2548 F4: `walk_reopen` (case lane) and `_survey_reopen` build no `open` call of their own - both go through `_walk_reopen_open`."""
    for fn in (story_run.Driver.walk_reopen, story_run.Driver._survey_reopen):
        source = inspect.getsource(fn)
        assert "_walk_reopen_open(" in source and '"open"' not in source and "WS.alive" not in source, fn.__name__
    body = inspect.getsource(story_run.Driver._walk_reopen_open)
    assert body.count('"open"') == 1 and "WS.alive" in body


def main() -> int:
    tests =[(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn) and fn.__module__ == __name__]
    failed = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print(f"PASS {name}")
            except Exception:                                                 # noqa: BLE001
                failed += 1
                print(f"FAIL {name}\n{traceback.format_exc()}")
    finally:
        TPA._cleanup_all()
    print(f"test_place_session: {len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


atexit.register(TPA._cleanup_all)

if __name__ == "__main__":
    sys.exit(main())
