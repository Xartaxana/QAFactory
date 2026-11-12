#!/usr/bin/env python3
"""t-2181 PC-9b fix round (critic t-2513): the S1 reference window against the REAL controller, the exit gate and the stand rules.

Fast: a scratch project, no `claude`, no network, no walk server. What is proved, one test per verdict item:

  B1  a REAL `Controller` admits a qa-runner dispatch of purpose `reference_walk` with no `execution_kind` at both sites (`prepare`, `apply`);
      every other runner packet is still refused (negative controls); the purposes come from the stage rows, not from a list in the controller
  B2  the exit gate places a running S1 `reference_walk` runner on S1 and owes only `work/reference-snapshot.yaml`; a plain S6 runner still owes the run report
  B3  `stand_identity.reference_stands` answers a story with no `sides` record and no project knowledge record before `contract` is imported
  F3  C8 and the probe's skip read ONE answer (`stand_identity.reference_side`); the own stand that is also the reference: C8 refuses naming the record
      (never the same stand as the door), the probe asks (no skip)
  F5-F7  `Driver.stage_simple("S1")` on a bare driver: an unreachable reference is written as the gap-only snapshot by the driver; a second reference is
      named as a gap; the actors come from `first_look.walk_actors`; a story with no reference takes the old path
  F10 `gate_preflight.Rehearsal._probe_picks` skips a reference stand on the implicit pick only
"""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller  # noqa: E402
import exit_gate  # noqa: E402
import gate_preflight  # noqa: E402
import reference_snapshot  # noqa: E402
import runtime_probe as rp  # noqa: E402
import stand_identity as SI  # noqa: E402
import story_run as SR  # noqa: E402

SIDES = {"product": {"reality": "real", "deliverable": True, "reference": "old", "source": "person"}}
WALK = "S1-qa-runner-1"


def _real_story(root):
    """A REAL controller story in the new plan-contract mode with S0 accepted (S1 is next)."""
    import test_controller_state as BASE
    root = Path(root)
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    c = controller.Controller(root)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    BASE.accept_stage(c, root, "S0")
    return c


def test_real_controller_admits_reference_walk_runner():
    """B1: the REAL controller admits the S1 runner of purpose reference_walk with no execution_kind at both sites, in the new mode."""
    with tempfile.TemporaryDirectory() as tmp:
        real = _real_story(tmp)
        check_eq("real_controller_admits_reference_walk_runner: the story is in the new plan-contract mode (the world the defect lived in)",
                 real.state().get("plan_contract_mode"), "new")
        packet = real.prepare({"stage": "S1", "role": "qa-runner", "id": WALK, "scope": [], "purpose": "reference_walk"})
        real.apply("dispatch", dict(packet["dispatch_request"], purpose="reference_walk"))
        known = real.state()["dispatches"].get(WALK) or {}
        check("real_controller_admits_reference_walk_runner: prepare and apply registered it at S1 with the purpose",
              known.get("role") == "qa-runner" and known.get("stage") == "S1" and (known.get("request_binding") or {}).get("purpose") == "reference_walk", known)
    with tempfile.TemporaryDirectory() as tmp:
        real = _real_story(tmp)
        plain = {"stage": "S1", "role": "qa-runner", "id": "S1-qa-runner-9", "scope": []}
        for label, options in (("no purpose", plain), ("another purpose", dict(plain, purpose="initial"))):
            try:
                real.prepare(options)
                said = ""
            except ValueError as exc:
                said = str(exc)
            check_in(f"real_controller_admits_reference_walk_runner: prepare still refuses a plain runner ({label})", "requires execution_kind", said)
        request = real.prepare(dict(plain, purpose="reference_walk"))["dispatch_request"]
        for label, forged in (("no purpose", {k: v for k, v in request.items() if k != "purpose"}), ("another purpose", dict(request, purpose="initial"))):
            try:
                real.apply("dispatch", forged)
                said = ""
            except ValueError as exc:
                said = str(exc)
            check_in(f"real_controller_admits_reference_walk_runner: apply still refuses a plain runner ({label})", "requires execution_kind", said)
        new = {"plan_contract_mode": "new"}
        check("real_controller_admits_reference_walk_runner: the predicate - both optional purposes exempt, only for the new-mode runner",
              not controller.runner_kind_required(new, "qa-runner", "reference_walk") and not controller.runner_kind_required(new, "qa-runner", "first_look")
              and controller.runner_kind_required(new, "qa-runner", "initial") and controller.runner_kind_required(new, "qa-runner", None)
              and controller.runner_kind_required(new, "qa-runner", ["reference_walk"])
              and not controller.runner_kind_required({"plan_contract_mode": "legacy"}, "qa-runner", "initial")
              and not controller.runner_kind_required(new, "qa-scout", "initial"))
        with mock.patch("stage_guard.stage_model", side_effect=OSError("no stages.json")):
            check("real_controller_admits_reference_walk_runner: an unreadable row table keeps the refusal (the purposes are data, not a fallback list)",
                  controller.runner_kind_required(new, "qa-runner", "reference_walk"))


def _optional_story(tmp, dispatches):
    art = Path(tmp) / "artifacts"
    (art / "QA-1" / "state").mkdir(parents=True)
    (art / "QA-1" / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
    (art / "QA-1" / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}}), encoding="utf-8")
    return art


def test_exit_gate_places_reference_walk_runner_on_s1():
    """B2: the SubagentStop gate places a running S1 reference-walk runner on S1 and owes only the snapshot; a plain S6 runner still owes the run report."""
    walk = {"stage": "S1", "role": "qa-runner", "status": "running", "request_binding": {"purpose": "reference_walk"}}
    plain = {"stage": "S6", "role": "qa-runner", "status": "running", "request_binding": {"purpose": "manual"}}
    with tempfile.TemporaryDirectory() as tmp:
        art = _optional_story(tmp, {WALK: walk})
        with mock.patch.object(exit_gate, "artifact_root", lambda: art):
            check_eq("exit_gate_places_reference_walk_runner_on_s1: the stage is S1", exit_gate._stage_id("qa-runner", "QA-1"), "S1")
            text = " ".join(str(m) for m in exit_gate.required_outputs_errors("qa-runner", "QA-1"))
            check("exit_gate_places_reference_walk_runner_on_s1: no snapshot -> the missing output is the snapshot, never S6's report or S1's own",
                  "work/reference-snapshot.yaml" in text and "run-report" not in text and "context-manifest" not in text, text)
            (art / "QA-1" / "work").mkdir()
            (art / "QA-1" / "work" / "reference-snapshot.yaml").write_text("items: []\n", encoding="utf-8")
            check_eq("exit_gate_places_reference_walk_runner_on_s1: a snapshot written -> nothing owed",
                     exit_gate.required_outputs_errors("qa-runner", "QA-1"), [])
    with tempfile.TemporaryDirectory() as tmp:
        art = _optional_story(tmp, {"S6-qa-runner-1": plain})
        with mock.patch.object(exit_gate, "artifact_root", lambda: art):
            check_eq("exit_gate_places_reference_walk_runner_on_s1: control - a plain S6 runner stays on S6", exit_gate._stage_id("qa-runner", "QA-1"), "S6")
            check_in("exit_gate_places_reference_walk_runner_on_s1: and is still owed the run report", "work/run-report.json",
                     " ".join(str(m) for m in exit_gate.required_outputs_errors("qa-runner", "QA-1")))


def test_no_reference_story_pays_no_contract_import():
    """B3: a story with no `sides` record in a project with no knowledge record is answered before `contract` is imported (0.5 s cold)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        task = root / "qa-factory" / "artifacts" / "QA-9"
        task.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "environment": "dev"}), encoding="utf-8")
        held = sys.modules.pop("contract", None)
        try:
            got = SI.reference_stands(root, "QA-9")
            check_eq("no_reference_story_pays_no_contract_import: no reference", got, {})
            check("no_reference_story_pays_no_contract_import: and `contract` was not imported to say so", "contract" not in sys.modules)
            (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "environment": "dev", "sides": SIDES}), encoding="utf-8")
            check_eq("no_reference_story_pays_no_contract_import: control - a story WITH a sides record names its reference", SI.reference_stands(root, "QA-9"), {"old": "product"})
            check("no_reference_story_pays_no_contract_import: control - and that answer imported `contract`", "contract" in sys.modules)
            sys.modules.pop("contract", None)
            (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "environment": "dev"}), encoding="utf-8")
            record = root / "qa-factory" / "records" / "project-knowledge.json"
            record.parent.mkdir(parents=True)
            record.write_text(json.dumps({"schema_version": 1, "facts": []}), encoding="utf-8")
            SI.reference_stands(root, "QA-9")
            check("no_reference_story_pays_no_contract_import: control - a project WITH a knowledge record is asked through `contract` (the registry may name a reference)",
                  "contract" in sys.modules)
        finally:
            if held is not None:
                sys.modules["contract"] = held


def test_c8_and_probe_skip_read_one_answer():
    """F3: `reference_side` is the one answer; C8 and the probe's skip agree on it, and the own stand that is also the reference is a record to fix."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        harness.use_project(root)
        task = root / "qa-factory" / "artifacts" / "PC-1"
        task.mkdir(parents=True)

        def story(own):
            (task / "pipeline.json").write_text(json.dumps({"ticket": "PC-1", "environment": own, "sides": SIDES}), encoding="utf-8")

        def ns(env):
            return argparse.Namespace(environment=env, profile="api", container="", checkout="")
        import execution_request as ER
        story("dev")
        check_eq("c8_and_probe_skip: the reader names the side and the story's own stand", SI.reference_side(root, "PC-1", "old"), ("product", "dev"))
        check_eq("c8_and_probe_skip: the own stand is no reference", SI.reference_side(root, "PC-1", "dev"), ("", ""))
        check_eq("c8_and_probe_skip: empty arguments read nothing", (SI.reference_side(root, "PC-1", ""), SI.reference_side(root, "", "old")), (("", ""), ("", "")))
        check_eq("c8_and_probe_skip: a different own stand - C8 no longer refuses (t-2277 W1: the run goes, as a sample)",
                 ER.reference_target_problem(root, "PC-1", "old"), "")
        mark = SI.reference_run_mark(root, "PC-1", "old")
        check_eq("c8_and_probe_skip: and the one reader gives the mark - stand, side, not the story's code",
                 {k: mark.get(k) for k in ("stand", "side", "story_code")}, {"stand": "old", "side": "product", "story_code": False})
        check_eq("c8_and_probe_skip: control - the story's own stand and a story with no reference carry no mark",
                 (SI.reference_run_mark(root, "PC-1", "dev"), SI.reference_run_mark(root, "PC-1", ""), SI.reference_run_mark(root, "", "old")), ({}, {}, {}))
        check("c8_and_probe_skip: and the probe skips the reference (compares nothing)", rp.reference_skip(ns("old"), task).get("result") == "not_applicable")
        story("old")
        both = ER.reference_target_problem(root, "PC-1", "old")
        check("c8_and_probe_skip: own == reference - C8 refuses", bool(both))
        check("c8_and_probe_skip: and names the contradiction and the RECORD as the door, never the same stand `old` as the way out",
              "both as its own stand" in both and "sides.product.reference" in both and "run it on the story's own stand" not in both, both)
        check_eq("c8_and_probe_skip: and the probe does NOT skip it (it asks, the safe direction): C8 refuses and the probe asks - one rule, neither passes",
                 rp.reference_skip(ns("old"), task), {})
        check_eq("c8_and_probe_skip: and the contradiction is no sample either - no mark", SI.reference_run_mark(root, "PC-1", "old"), {})
        check_eq("c8_and_probe_skip: control - a story with no reference is refused by neither", (ER.reference_target_problem(root, "PC-1", "dev"),
                 rp.reference_skip(ns("dev"), task)), ("", {}))


def _fake_controller(log):
    class Fake:
        def __init__(self, *a, **k):
            pass

        def state(self):
            return {"dispatches": {}}

        def prepare(self, options):
            log.append(("prepare", dict(options)))
            return {"dispatch_request": {"id": options["id"], "stage": options["stage"], "role": options["role"]}}

        def apply(self, kind, request):
            log.append((kind, dict(request)))
    return Fake


class Window:
    """A bare driver over a scratch project whose story carries (or not) a reference; the recorders."""

    def __init__(self, tmp, sides=SIDES, open_result=(0, "{}"), stands=None):
        self.root = Path(tmp)
        self.task = self.root / "qa-factory" / "artifacts" / "QA-9"
        (self.task / "work").mkdir(parents=True)
        pipeline = {"ticket": "QA-9", "environment": "new"}
        if sides:
            pipeline["sides"] = sides
        (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        self.roles, self.py_calls, self.log, self.open_result = [], [], [], open_result
        d = SR.Driver.__new__(SR.Driver)
        d.task_root, d.task, d.project, d.config, d.scripts = self.task, "QA-9", self.root, {}, "SCRIPTS"
        d.plugin = harness.PLUGIN_ROOT
        d.state, d.boundary = {}, ""
        d.controller_state = lambda: {"dispatches": {}}
        d.role_lines = lambda *a, **k: []
        d.record_running = lambda *a, **k: None
        d.py = self.py
        d.run_role = self.run_role
        self.d = d

    def py(self, script, *args, **kwargs):
        self.py_calls.append((script, args))
        return self.open_result if script == "walk_session.py" and args and args[0] == "open" else (0, "")

    def run_role(self, stage, role, **kwargs):
        self.roles.append((stage, role, kwargs))
        after = kwargs.get("after")
        if after:
            after({}, {})
        return ({}, {})

    def stage(self):
        out = io.StringIO()
        with mock.patch.object(controller, "Controller", _fake_controller(self.log)), contextlib.redirect_stdout(out):
            self.d.stage_simple("S1")
        return out.getvalue()

    def brief(self):
        return " ".join(self.roles[-1][2]["extra"])

    def open_argv(self):
        return next(args for script, args in self.py_calls if script == "walk_session.py" and args[0] == "open")


def test_window_registers_with_purpose_and_walks_as_the_accounts():
    """B1 (driver side) + F4 + F7: `prepare` carries the purpose; the actors are `first_look.walk_actors`; the brief names who walks and the items shape."""
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp)
        with mock.patch("first_look.walk_actors", lambda project, cfg, stand, n: {"actors": ["default", "editor"], "left": ["viewer"], "problem": "", "accounts": [], "none": []}):
            w.stage()
        check_eq("window: prepare carries the purpose, apply carries it too", [(op, req.get("purpose")) for op, req in w.log],
                 [("prepare", "reference_walk"), ("dispatch", "reference_walk")])
        argv = w.open_argv()
        check_eq("window: the walk opens on the reference stand with the first two accounts, in the reader's order",
                 (argv[argv.index("--env") + 1], argv[argv.index("--actor") + 1], argv[argv.index("--actor2") + 1]), ("old", "default", "editor"))
        brief = w.brief()
        check_in("window: the brief says who walks", "You walk as default, editor", brief)
        check_in("window: and which account was not opened", "viewer", brief)
        check_in("window: the items shape reaches the runner before the work (AR-10)", "locators_portable", brief)
        check_in("window: the snapshot contract is named to the runner (a reader of references/artifact-contract-reference.md)",
                 "artifact-contract-reference.md", brief)
        check("window: the file the brief names exists", (harness.PLUGIN_ROOT / "references" / "artifact-contract-reference.md").is_file())
        check_not_in("window: no --replace on a first window", "--replace", brief)
        check_eq("window: the scout does not close S1, the runner's window does", [(s, r, k.get("complete")) for s, r, k in w.roles],
                 [("S1", "qa-scout", False), ("S1", "qa-runner", True)])
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp)
        w.stage()
        argv = w.open_argv()
        check("window: no account known - guest alone, and the brief says it is not signed in",
              argv[argv.index("--actor") + 1] == "guest" and "--actor2" not in argv and "not signed in" in w.brief(), str(argv))
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp)
        (w.task / "work" / "reference-snapshot.yaml").write_text("items: []\n", encoding="utf-8")
        w.stage()
        check_in("window: S1 made again over a snapshot - the put carries --replace", "--replace", w.brief())


def test_unreachable_reference_is_written_by_the_driver():
    """F5: the gap-only snapshot is the driver's own write; the runner is told it exists and writes nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, open_result=(3, json.dumps({"status": "refused", "reason": "no route to old"})))
        w.stage()
        snap = reference_snapshot.read(w.task)
        check("unreachable: the snapshot exists with no items and ONE gap line carrying the probe's words",
              snap is not None and snap["items"] == [] and snap["gaps"] == ["the old version at old could not be reached: no route to old"], str(snap))
        brief = w.brief()
        check("unreachable: the runner is told the driver wrote it - no put command, nothing to walk",
              "already written" in brief and "put --task-root" not in brief, brief)
        check("unreachable: no walk closed for a walk that never opened, no after hook", not [a for s, a in w.py_calls if a and a[0] == "close"]
              and w.roles[-1][2].get("after") is None)
        check_eq("unreachable: the runner dispatch still closes S1 (the stage has no code-close site)", w.roles[-1][2].get("complete"), True)
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, open_result=(3, "{}"))
        (w.task / "work" / "reference-snapshot.yaml").write_text("items: []\ngaps: [x]\n", encoding="utf-8")
        w.stage()
        check_in("unreachable: S1 made again - the snapshot is replaced, not refused", "could not be reached", " ".join(reference_snapshot.read(w.task)["gaps"]))


def test_second_reference_is_named_never_dropped():
    """F6: two references of one story - the first by name is walked, the other is a printed note and a gap line in the brief."""
    two = dict(SIDES, backend={"reality": "real", "deliverable": True, "reference": "old-api", "source": "person"})
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, sides=two)
        said = w.stage()
        argv = w.open_argv()
        check_eq("second_reference: the first reference by name is the one walked", argv[argv.index("--env") + 1], "old")
        line = "the reference `old-api` of the `backend` side was not walked: one reference per story"
        check_in("second_reference: a note is printed", line, said)
        check_in("second_reference: and the runner's brief carries it as a gap line", line, w.brief())
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, sides=two, open_result=(3, "{}"))
        w.stage()
        check_in("second_reference: the unreachable road writes it too", "old-api", " ".join(reference_snapshot.read(w.task)["gaps"]))


def test_no_reference_story_takes_the_old_path():
    """edge: a story with no reference runs S1 byte for byte as before - one role run, nothing registered, no walk."""
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, sides=None)
        w.stage()
        check_eq("no_reference: one role run, the scout, no `complete` forced", [(s, r, k.get("complete")) for s, r, k in w.roles], [("S1", "qa-scout", None)])
        check_eq("no_reference: nothing registered, no walk opened", (w.log, w.py_calls), ([], []))


def _rework_rig(w, sink):
    """The few members `Driver.rework` and `_act_relaunch` read, over the window rig (the controller's answers are fixed, nothing is registered)."""
    d = w.d
    d.controller = lambda op, *args, **kw: sink.append(op) or {"request": {"id": "S1-qa-scout-2", "scope": []}}
    d.stop_if_drained, d.count_launch, d.on_chain = (lambda: None), (lambda: None), (lambda: False)
    d.relaunch_reason = lambda request, action: "the person's rework"
    d.stage_acceptor = lambda stage: ""
    d.STAND_STAGES = ()
    return d


def test_rework_of_s1_re_enters_the_reference_window():
    """t-2277 batch 2b D (critic t-2513 F1): `rework S1` of a story with a reference - on the code road (`rework`) and on the relaunch road
    (`_act_relaunch`, the person's rework) - runs the scout WITHOUT closing S1, then the runner walks the old version again and `put` replaces the
    snapshot; a story with no reference, and any other stage, keeps today's run byte for byte."""
    for road in ("rework", "relaunch"):
        with tempfile.TemporaryDirectory() as tmp:
            w, sink = Window(tmp), []
            d = _rework_rig(w, sink)
            (w.task / "work" / "reference-snapshot.yaml").write_text("items: []\ngaps: [old]\n", encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(controller, "Controller", _fake_controller(w.log)), contextlib.redirect_stdout(out):
                if road == "rework":
                    d.rework("S1", "qa-scout", [], "the ticket changed", cause="ticket_changed", complete=True)
                else:
                    d._act_relaunch({"action": "relaunch", "stage": "S1", "role": "qa-scout",
                                     "dispatch_request": {"id": "S1-qa-scout-2", "stage": "S1", "role": "qa-scout", "rework_of": "S1-qa-scout-1", "scope": []}})
            check_eq(f"{road}: the scout's rework does not close S1, the runner's window does",
                     [(s, r, k.get("complete")) for s, r, k in w.roles], [("S1", "qa-scout", False), ("S1", "qa-runner", True)])
            check_eq(f"{road}: the window is dispatched with its purpose", [(op, req.get("purpose")) for op, req in w.log],
                     [("prepare", "reference_walk"), ("dispatch", "reference_walk")])
            check_in(f"{road}: the old snapshot is replaced - the put carries --replace", "--replace", w.brief())
            check_eq(f"{road}: the walk opens on the reference stand again", w.open_argv()[w.open_argv().index("--env") + 1], "old")
    for label, sides, stage, role in (("no reference", None, "S1", "qa-scout"), ("another stage", SIDES, "S2", "qa-story-analyst")):
        with tempfile.TemporaryDirectory() as tmp:
            w, sink = Window(tmp, sides=sides), []
            d = _rework_rig(w, sink)
            with mock.patch.object(controller, "Controller", _fake_controller(w.log)), contextlib.redirect_stdout(io.StringIO()):
                d.rework(stage, role, [], "the ticket changed", cause="ticket_changed", complete=True)
            check_eq(f"rework: control - {label}: one run, `complete` as the caller gave it, nothing registered, no walk",
                     ([(s, r, k.get("complete")) for s, r, k in w.roles], w.log, w.py_calls), ([(stage, role, True)], [], []))


def test_recovery_road_closes_the_window_like_the_live_road():
    """F2: the completion of an S1 runner whose record is the reference window is True on the recovery roads; every other S1 record keeps the stage's rule."""
    d = SR.Driver.__new__(SR.Driver)
    window = {"id": WALK, "stage": "S1", "role": "qa-runner", "request_binding": {"purpose": "reference_walk"}}
    check_eq("recovery: the reference window finishes complete", d.completion_for("S1", "qa-runner", window), True)
    d.stage_acceptor = lambda stage: ""
    for label, record in (("another purpose", dict(window, request_binding={"purpose": "initial"})), ("no binding", {"id": "x"})):
        check(f"recovery: control - an S1 runner record with {label} does not take that branch", d.completion_for("S1", "qa-runner", record) is not True)
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, sides=None)          # a story with no reference: the scout record keeps the stage's rule (the controller default)
        w.d.stage_acceptor = lambda stage: ""
        check("recovery: control - a scout record of the same purpose does not take it either", w.d.completion_for("S1", "qa-scout", window) is not True)


def test_scout_finish_never_closes_s1_while_the_window_is_owed():
    """t-2548 F2: `completion_for` is the ONE site - every road that finishes the S1 scout of a story with a reference (relaunch with no
    `rework_of`, `wait_existing_job` / `resume_checkpoint` over the person's words, the no-packet fallback, a saved result) leaves S1 OPEN, and
    the next `where` -> `stage_simple` skips the accepted scout and runs the window. A story with no reference: the stage's own rule, as before."""
    scout = {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout", "status": "running"}
    with tempfile.TemporaryDirectory() as tmp:
        w, sink = Window(tmp), []
        d = _rework_rig(w, sink)
        check_eq("scout_finish: with a reference the scout's completion is False, for a record and for none", (d.completion_for("S1", "qa-scout", scout),
                 d.completion_for("S1", "qa-scout", {})), (False, False))
        check_eq("scout_finish: the window's own runner still closes the stage",
                 d.completion_for("S1", "qa-runner", {"request_binding": {"purpose": "reference_walk"}}), True)
        out = io.StringIO()
        with mock.patch.object(controller, "Controller", _fake_controller(w.log)), contextlib.redirect_stdout(out):
            d._act_relaunch({"action": "relaunch", "stage": "S1", "role": "qa-scout",           # a relaunch of a failed first make: no rework_of
                             "dispatch_request": {"id": "S1-qa-scout-2", "stage": "S1", "role": "qa-scout", "scope": []}})
        check_eq("scout_finish: the relaunch (no rework_of) finishes the scout with complete=False and starts no window itself",
                 [(s, r, k.get("complete")) for s, r, k in w.roles], [("S1", "qa-scout", False)])
        w.roles.clear()
        resumed = []
        d.resume_role = lambda stage, role, dispatch, words, complete=None: resumed.append((stage, role, complete))
        d.controller_state = lambda: {"dispatches": {"S1-qa-scout-1": scout}}
        d.state["pending_words"] = {"S1-qa-scout-1": "the person's answer"}
        d._act_wait_existing_job({"action": "wait_existing_job", "dispatch_id": "S1-qa-scout-1"})
        check_eq("scout_finish: the resume of the scout (the person's words) is told not to close S1", resumed, [("S1", "qa-scout", False)])
        # the next `where` is `prepare_stage S1` -> `stage_simple`: an accepted scout is not run again, the window follows it
        d.controller_state = lambda: {"dispatches": {"S1-qa-scout-1": dict(scout, status="accepted")}}
        with mock.patch.object(controller, "Controller", _fake_controller(w.log)), contextlib.redirect_stdout(io.StringIO()):
            d.stage_simple("S1")
        check_eq("scout_finish: the next entry of S1 skips the accepted scout and runs the window, which closes S1",
                 [(s, r, k.get("complete")) for s, r, k in w.roles], [("S1", "qa-runner", True)])
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp, sides=None)
        d = _rework_rig(w, [])
        check_eq("scout_finish: control - no reference: the scout record keeps the stage's own rule (the controller default)",
                 (d.completion_for("S1", "qa-scout", scout), d.completion_for("S1", "qa-scout", {})), (None, None))
        with mock.patch.object(controller, "Controller", _fake_controller(w.log)), contextlib.redirect_stdout(io.StringIO()):
            d._act_relaunch({"action": "relaunch", "stage": "S1", "role": "qa-scout",
                             "dispatch_request": {"id": "S1-qa-scout-2", "stage": "S1", "role": "qa-scout", "scope": []}})
        check_eq("scout_finish: control - no reference: the relaunch is byte for byte as before (complete=None)",
                 [(s, r, k.get("complete")) for s, r, k in w.roles], [("S1", "qa-scout", None)])


def test_window_is_owed_to_the_scout_only():
    """t-2548 N1: the role test lives in `s1_window_owed(stage, role)`: the scout gets the window, any other role of S1 and any other stage None."""
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(tmp)
        d = w.d
        check("owed: the scout, and no role given (stage_simple), get the window", bool(d.s1_window_owed("S1", "qa-scout")) and bool(d.s1_window_owed("S1")))
        check_eq("owed: the window's own runner and another stage get None", (d.s1_window_owed("S1", "qa-runner"), d.s1_window_owed("S2", "qa-scout")), (None, None))
    with tempfile.TemporaryDirectory() as tmp:
        check_eq("owed: control - no reference story: None for the scout", Window(tmp, sides=None).d.s1_window_owed("S1", "qa-scout"), None)


def test_ticket_changed_rework_of_s1_goes_to_the_scout():
    """t-2548 B2: a `ticket_changed` rework of S1 on a story with a reference picks the AUTHOR of the stage (the scout), never the window's runner
    accepted after it: the controller is asked for a scout rework, the scout runs without closing S1 and the window follows. No reference: the
    scout alone, `complete=True`, as before."""
    scout = {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout", "status": "accepted"}
    runner = {"id": "S1-qa-runner-1", "stage": "S1", "role": "qa-runner", "status": "accepted", "request_binding": {"purpose": "reference_walk"}}
    for label, sides, dispatches, want in (
            ("reference", SIDES, {"S1-qa-scout-1": scout, "S1-qa-runner-1": runner}, [("S1", "qa-scout", False), ("S1", "qa-runner", True)]),
            ("no reference", None, {"S1-qa-scout-1": scout}, [("S1", "qa-scout", True)])):
        with tempfile.TemporaryDirectory() as tmp:
            w, sink = Window(tmp, sides=sides), []
            d = _rework_rig(w, sink)
            asked = []
            d.controller = lambda op, *args, **kw: asked.append((op, args)) or {"request": {"id": "S1-qa-scout-2", "scope": []}}
            (w.task / "state").mkdir(parents=True, exist_ok=True)
            (w.task / "state" / "controller.json").write_text("{}", encoding="utf-8")
            d.state_dir = w.task / "state"
            d.state = {"ticket_rework": {"stages": ["S1"], "words": "the ticket says more now", "before": []}}
            d.save_state = lambda: None
            d.ticket_reopen_gate_a = lambda pending: None
            d.controller_state = lambda dispatches=dispatches: {"dispatches": dispatches}
            with mock.patch.object(controller, "Controller", _fake_controller(w.log)), contextlib.redirect_stdout(io.StringIO()):
                moved = d.ticket_rework_step()
            check_eq(f"ticket_changed S1 [{label}]: the step moved", moved, True)
            check_eq(f"ticket_changed S1 [{label}]: the controller is asked to rework the scout", [args[args.index("--role") + 1] for op, args in asked if op == "rework"],
                     ["qa-scout"])
            check_eq(f"ticket_changed S1 [{label}]: the roles run", [(s, r, k.get("complete")) for s, r, k in w.roles], want)


def test_probe_picks_skips_a_reference_stand_on_the_implicit_pick_only():
    """F10: `Rehearsal._probe_picks` - the same rule as the probe: only the implicit pick skips a reference stand."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        task = root / "qa-factory" / "artifacts" / "QA-9"
        task.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "sides": SIDES}), encoding="utf-8")
        cfg = {"environments": [{"name": "dev"}, {"name": "old"}], "profiles": []}

        def picks(selected):
            fake = types.SimpleNamespace(config=cfg, _selected_environment=lambda: {"name": selected}, project_root=root, task_root=task)
            return gate_preflight.Rehearsal._probe_picks(fake, rp, "api")[0]
        check_eq("probe_picks: nothing selected - the reference stand is skipped, `dev` is the only stand left", picks(""), "dev")
        check_eq("probe_picks: a stand named is returned as named, reference or not", (picks("old"), picks("dev")), ("old", "dev"))
        bare = types.SimpleNamespace(config=cfg, _selected_environment=lambda: {"name": ""})
        check_eq("probe_picks: control - a caller with no story (no project root) reads no reference: two stands, no pick, as before",
                 gate_preflight.Rehearsal._probe_picks(bare, rp, "api")[0], "")


def main() -> None:
    test_real_controller_admits_reference_walk_runner()
    test_exit_gate_places_reference_walk_runner_on_s1()
    test_no_reference_story_pays_no_contract_import()
    test_c8_and_probe_skip_read_one_answer()
    test_window_registers_with_purpose_and_walks_as_the_accounts()
    test_unreachable_reference_is_written_by_the_driver()
    test_second_reference_is_named_never_dropped()
    test_no_reference_story_takes_the_old_path()
    test_rework_of_s1_re_enters_the_reference_window()
    test_recovery_road_closes_the_window_like_the_live_road()
    test_scout_finish_never_closes_s1_while_the_window_is_owed()
    test_window_is_owed_to_the_scout_only()
    test_ticket_changed_rework_of_s1_goes_to_the_scout()
    test_probe_picks_skips_a_reference_stand_on_the_implicit_pick_only()
    finish("test_reference_window")


if __name__ == "__main__":
    main()
