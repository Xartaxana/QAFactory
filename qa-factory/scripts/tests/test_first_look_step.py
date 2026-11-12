#!/usr/bin/env python3
"""t-2277 FL-5: the driver's first look before S3 - `Driver.first_look_step` and `Driver._first_look_answer`, the `first_look.dead`
question, and the exit gate's window-1 filter.

Fast: the methods are called on a bare `Driver` (no loop, no `claude`, no network). `py` is a fake that drives the REAL `first_look.py`
functions (begin / end / put --null) and records the `walk_session.py` calls; the controller's registration and `run_role` are
recorders; the files (register, manifest, pipeline, record) are real, in a scratch folder. One test per item of the FL-5 block; the names
are the spec's. Run: `python -B test_first_look_step.py` (exit code = failures) or pytest.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller  # noqa: E402
import exit_gate  # noqa: E402
import first_look as FL  # noqa: E402
import grounding_table as GT  # noqa: E402
import story_run as SR  # noqa: E402

STAND, HEAD_A, HEAD_B = "dev", "a" * 40, "b" * 40
WALK = "S3-qa-runner-1"


class FakeController:
    """What `first_look_step` uses of `controller.Controller`: `prepare` and `apply("dispatch", request)`."""
    log: list = []

    def __init__(self, *a, **k):
        pass

    def prepare(self, options):
        return {"dispatch_request": {"id": options["id"], "stage": options["stage"], "role": options["role"]}}

    def apply(self, kind, request):
        FakeController.log.append((kind, dict(request)))


class Rig:
    """A story folder, a bare driver and the recorders."""

    def __init__(self, tmp, ids=("R-1", "R-2", "R-3", "R-4"), cfg=None, open_result=(0, "{}"), writes=None, accepted=True):
        self.root = Path(tmp)
        self.task = self.root / "QA-1"
        (self.task / "work").mkdir(parents=True)
        rows = "".join(f"| {r} | The stand shows {r}. | task |\n" for r in ids)
        (self.task / "work" / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n" + rows, encoding="utf-8")
        self.set_heads(HEAD_A)
        self.set_pipeline({"ticket": "QA-1", "environment": STAND, "environment_pending": False})
        self.calls, self.dispatches = [], {}
        self.open_result, self.writes, self.accepted = open_result, writes, accepted
        FakeController.log = []
        d = SR.Driver.__new__(SR.Driver)
        d.task_root, d.task, d.project, d.config = self.task, "QA-1", self.root, cfg if cfg is not None else {}
        d.state, d.boundary, d._price_notes = {}, "", None
        d.file_defect = lambda *a, **k: None
        d.pipeline = lambda: json.loads((self.task / "pipeline.json").read_text(encoding="utf-8"))
        d.controller_state = lambda: {"dispatches": self.dispatches}
        d.role_lines = lambda *a, **k: []
        d.py, d.record_running, d.run_role = self.py, self.record_running, self.run_role
        self.d = d

    def set_heads(self, sha):
        entries = [{"repo_id": "product", "source_sha": sha, "diff_path": "work/impl-diff-product.txt"}]
        (self.task / "work" / "context-manifest.json").write_text(json.dumps({"implementations": entries}), encoding="utf-8")

    def set_pipeline(self, pipeline):
        (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    def py(self, script, *args, **kw):
        a = list(args)
        self.calls.append((script, tuple(a)))
        opt = lambda flag: a[a.index(flag) + 1] if flag in a else ""      # noqa: E731
        if script == "first_look.py":
            if a[0] == "begin":
                FL.begin(self.task, opt("--dispatch"), opt("--env"))
                return 0, "{}"
            if a[0] == "end":
                done = FL.end(self.task, opt("--outcome"))
                return (0 if done["ok"] else 1), done["problem"]
            if a[0] == "put":
                done = FL.put(self.task, "", opt("--null"))
                return (0 if done["written"] else 1), " | ".join(done["problems"])
        if script == "walk_session.py" and a[0] == "open":
            record = self.task / "state" / "walks" / f"{opt('--walk')}.json"
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps({"walk": opt("--walk"), "state": "opening"}), encoding="utf-8")
            return self.open_result
        return 0, ""

    def record_running(self, *a, **k):
        self.calls.append(("record_running", a))

    def run_role(self, stage, role, **kw):
        self.calls.append(("run_role", {"stage": stage, "role": role, **kw}))
        walk = kw["rework"]["id"]
        self.dispatches.setdefault(walk, {"stage": "S3", "role": "qa-runner", "status": "running"})
        if self.writes:
            heads, reg = FL.current_keys(self.task)
            GT.write_yaml(FL._record_path(self.task), {
                "walked_at": "2026-11-11T00:00:00+00:00", "walk": walk, "stand": STAND, "stand_build": self.writes.get("build", "not_established"),
                "source_head": json.loads(heads), "register_hash": reg, "gaps": [],
                "rows": [{"req": r, "status": s, "why": f"the stand said {s} for {r}", **({"blocked_by": "product"} if s in ("missing", "unreachable") else {})}
                         for r, s in self.writes["rows"].items()]})
            FL.end(self.task, "written")
        self.dispatches[walk]["status"] = "accepted" if self.accepted else "blocked"
        if kw.get("after"):
            kw["after"](walk, {})
        return "digest", {}

    def register(self):
        """What the fake controller recorded joins the dispatch map the driver reads back."""
        for _kind, request in FakeController.log:
            self.dispatches.setdefault(request["id"], {"stage": request["stage"], "role": request["role"], "status": "running"})

    def step(self, real_controller=None):
        """`first_look_step` with the fake controller in place (or the REAL one given); `(raised Person | None, printed text)`."""
        real, out, raised = controller.Controller, io.StringIO(), None
        controller.Controller = FakeController if real_controller is None else (lambda *a, **k: real_controller)
        try:
            original = FakeController.apply

            def apply(me, kind, request):
                original(me, kind, request)
                self.dispatches.setdefault(request["id"], {"stage": request["stage"], "role": request["role"], "status": "running"})
            FakeController.apply = apply
            with contextlib.redirect_stdout(out):
                try:
                    SR.Driver.first_look_step(self.d)
                except SR.Person as person:
                    raised = person
        finally:
            controller.Controller, FakeController.apply = real, original
        return raised, out.getvalue()

    def names(self):
        return [c[0] if isinstance(c[0], str) else "?" for c in self.calls]

    def argv(self, script, first):
        return next(list(args) for s, args in self.calls if s == script and args and args[0] == first)

    def runs(self):
        return [c[1] for c in self.calls if c[0] == "run_role"]


def env_cfg(root):
    (Path(root) / ".env").write_text("AUTH_USERNAME=u1\nAUTH_PASSWORD=p1\n", encoding="utf-8")
    return {"environment": {"env_file": ".env"}}


GOOD = {"rows": {"R-1": "confirms", "R-2": "confirms", "R-3": "confirms", "R-4": "missing"}}
DEAD = {"rows": {"R-1": "confirms", "R-2": "missing", "R-3": "unreachable", "R-4": "missing"}}


def test_not_due_writes_null_and_runs_s3():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.set_pipeline({"ticket": "QA-1", "environment": "", "environment_pending": False})
        raised, said = r.step()
        check("not_due_writes_null_and_runs_s3: no dispatch, no walk, no question",
              raised is None and not r.runs() and not any(c[0] == "walk_session.py" for c in r.calls), r.calls)
        got = FL.read(r.task)
        check_eq("not_due_writes_null_and_runs_s3: the null record names the reason", got["null"], "no_stand")
        check_in("not_due_writes_null_and_runs_s3: one line says it", "no stand", said)


def test_walk_opened_with_survey_env_items_guest():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=GOOD)
        raised, _ = r.step()
        argv = r.argv("walk_session.py", "open")
        check("walk_opened_with_survey_env_items_guest: survey place, the story's stand, the register's items, guest only",
              argv[argv.index("--place") + 1] == "survey" and argv[argv.index("--env") + 1] == STAND
              and argv[argv.index("--items") + 1] == "R-1,R-2,R-3,R-4" and argv[argv.index("--actor") + 1] == "guest"
              and "--actor2" not in argv, argv)
        names = r.names()
        order = [names.index("first_look.py"), names.index("walk_session.py"), names.index("record_running"), names.index("run_role")]
        check("walk_opened_with_survey_env_items_guest: begin, open, record running, role - in that order", order == sorted(order), names)
        begin = r.argv("first_look.py", "begin")
        check("walk_opened_with_survey_env_items_guest: begin names the walk id and the stand",
              begin[begin.index("--dispatch") + 1] == WALK and begin[begin.index("--env") + 1] == STAND, begin)
        check_eq("walk_opened_with_survey_env_items_guest: the dispatch is a qa-runner of S3 with purpose first_look",
                 [(k, q["stage"], q["role"], q["purpose"]) for k, q in FakeController.log], [("dispatch", "S3", "qa-runner", "first_look")])
        run = r.runs()[0]
        check("walk_opened_with_survey_env_items_guest: the role runs under the walk id, closes no stage, closes the walk after",
              run["rework"]["id"] == WALK and run["complete"] is False and callable(run["after"]), run)
        check("walk_opened_with_survey_env_items_guest: the walk is closed after the role", ("walk_session.py", ("close", "--task-root", str(r.task), "--walk", WALK)) in r.calls)
        check("walk_opened_with_survey_env_items_guest: a good share asks nothing", raised is None)


def test_http_only_walk_adds_default_actor_when_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, cfg=env_cfg(tmp), writes=GOOD)
        r.step()
        argv = r.argv("walk_session.py", "open")
        check_eq("http_only_walk_adds_default_actor_when_recorded: the recorded default account first, guest in the slot left over (J-18)",
                 (argv[argv.index("--actor") + 1], argv[argv.index("--actor2") + 1] if "--actor2" in argv else ""), ("default", "guest"))


def test_http_only_walk_guest_only_without_default():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, cfg={"environment": {"env_file": "missing.env"}}, writes=GOOD)
        r.step()
        argv = r.argv("walk_session.py", "open")
        check("http_only_walk_guest_only_without_default: no readable default account, guest alone, the walk still opens",
              argv[argv.index("--actor") + 1] == "guest" and "--actor2" not in argv, argv)


def test_no_surface_writes_null_no_question():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, open_result=(2, json.dumps({"status": "not_started", "cause": "no_reachable_surface"})))
        raised, _ = r.step()
        check("no_surface_writes_null_no_question: no role, no question", raised is None and not r.runs() and not FakeController.log)
        check_eq("no_surface_writes_null_no_question: the null reason is the declared one", FL.read(r.task)["null"], "no_reachable_surface")
        check_eq("no_surface_writes_null_no_question: the attempt is settled (a refused cause is not retried), not open_failed",
                 FL.read_attempt(r.task)["outcome"], "nothing_written")
        for _ in range(3):
            r.step()
        opens = sum(1 for c in r.calls if c[0] == "walk_session.py" and c[1][0] == "open")
        check_eq("no_surface_writes_null_no_question: later entries do not open again and keep the specific reason (m3)",
                 (opens, FL.read(r.task)["null"]), (1, "no_reachable_surface"))


def test_http_only_story_walks():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, cfg={"profiles": [{"profile_id": "api", "capabilities": ["api"]}]}, writes=GOOD)
        raised, _ = r.step()
        check("http_only_story_walks: a story with no screen profile is walked, not skipped",
              len(r.runs()) == 1 and FL.read(r.task)["null"] == "" and raised is None, r.calls)


def test_walk_open_failure_writes_null_no_role():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, open_result=(3, "the walk session did not start: x"))
        raised, _ = r.step()
        check("walk_open_failure_writes_null_no_role: exit 3 - no role, no question, nothing registered", raised is None and not r.runs() and not FakeController.log)
        check_eq("walk_open_failure_writes_null_no_role: walk_not_opened", FL.read(r.task)["null"], "walk_not_opened")
        check("walk_open_failure_writes_null_no_role: the dead walk record is removed", not (r.task / "state" / "walks" / f"{WALK}.json").exists())
        r2 = Rig(str(Path(tmp) / "b"), open_result=(3, json.dumps({"status": "not_started", "cause": "profile_not_chosen"})))
        r2.step()
        check_eq("walk_open_failure_writes_null_no_role: a refused profile is named by its cause word", FL.read(r2.task)["null"], "profile_not_chosen")


def test_open_failed_retried_once_on_relaunch():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, open_result=(3, "no"))
        opens = lambda: sum(1 for c in r.calls if c[0] == "walk_session.py" and c[1][0] == "open")      # noqa: E731
        r.step()
        r.step()
        check_eq("open_failed_retried_once_on_relaunch: the second entry opens again on the same heads", opens(), 2)
        r.step()
        check_eq("open_failed_retried_once_on_relaunch: the third does not", opens(), 2)
        check_eq("open_failed_retried_once_on_relaunch: and says walk_not_opened", FL.read(r.task)["null"], "walk_not_opened")


def test_nothing_written_not_redispatched_on_reentry():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=None)
        r.step()
        check_eq("nothing_written_not_redispatched_on_reentry: the role left no record, the attempt ends nothing_written",
                 FL.read_attempt(r.task)["outcome"], "nothing_written")
        r.step()
        r.step()
        check_eq("nothing_written_not_redispatched_on_reentry: no second dispatch on these heads", len(r.runs()), 1)
        check_eq("nothing_written_not_redispatched_on_reentry: one registration", len(FakeController.log), 1)


def test_below_floor_asks_once():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=DEAD)
        raised, _ = r.step()
        check("below_floor_asks_once: a share under the floor raises the closed question once", raised is not None and raised.kind == "first_look_dead"
              and raised.stage == "S3", raised)
        text = str(raised.text)
        check_in("below_floor_asks_once: it shows the share and the floor", "1 of 4", text)
        for word in ("confirms 1", "contradicts 0", "missing 2", "unreachable 1"):
            check_in(f"below_floor_asks_once: the count by every status ({word})", word, text)
        check_in("below_floor_asks_once: both answers are priced", "`continue`", text)
        check_in("below_floor_asks_once: stop is an answer", "`stop`", text)
        check_eq("below_floor_asks_once: one dispatch only", len(r.runs()), 1)
        again, _ = r.step()
        check("below_floor_asks_once: a second entry asks the same question again and dispatches nothing", again is not None and len(r.runs()) == 1)


def test_continued_on_same_head_not_reasked():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=DEAD)
        r.step()
        heads, reg = FL.current_keys(r.task)
        r.set_pipeline({"ticket": "QA-1", "environment": STAND, "environment_pending": False,
                        "first_look_continue": {"source_head": heads, "register_hash": reg}})
        raised, _ = r.step()
        check("continued_on_same_head_not_reasked: a `continue` for these heads and this register is not asked again", raised is None)
        r.set_heads(HEAD_B)
        raised, _ = r.step()
        check("continued_on_same_head_not_reasked: a new head walks again (and asks again when it shows little)", len(r.runs()) == 2)


class AnswerRig:
    def __init__(self, rig):
        self.rig, self.said = rig, []
        d = rig.d
        d.answer_row = lambda *a, **k: self.said.append(("answer_row", a))
        d.answer_file = lambda: "state/words/driver-first-look.txt"
        d.controller = lambda op, *args, input_data=None: self.said.append(("controller", op, args)) or {}
        d.unread = lambda *a, **k: self.said.append(("unread", a))
        d.held_question = lambda *a, **k: SR.Person("x", "held", "S3")
        d._act_await_implementation = self.await_

    def await_(self, action):
        self.said.append(("await", dict(action)))
        raise SR.Stop(SR.EXIT_DONE, "waiting")


def test_continue_passes_current_keys_then_s3():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        a = AnswerRig(r)
        token = SR.Driver._first_look_answer(r.d, "continue\nthe stand is old, go on", "", "S3")
        heads, reg = FL.current_keys(r.task)
        check("continue_passes_current_keys_then_s3: the token is taken", token is True)
        check_eq("continue_passes_current_keys_then_s3: first_look_continue with the words file and the keys of now",
                 [s for s in a.said if s[0] == "controller"],
                 [("controller", "first_look_continue", ("--words-file", str(r.task / "state/words/driver-first-look.txt"), "--source-head", heads,
                                                         "--register-hash", reg))])
        check("continue_passes_current_keys_then_s3: the register hash is 64 hex", len(reg) == 64)
        events = []
        r.d.first_look_step = lambda: events.append("first_look_step")
        r.d.s3_prepare = lambda: events.append("s3_prepare")
        r.d.stages = lambda: {"S3": {"roles": ["qa-test-strategist"]}}
        r.d.stage_acceptor = lambda s: ""
        r.d.s3_window_completion = lambda rec: None
        r.d.role_lines = lambda *a, **k: []
        r.d.run_role = lambda *a, **k: events.append("run_role")
        SR.Driver.stage_S3(r.d)
        check_eq("continue_passes_current_keys_then_s3: then S3 goes on to its preparation and the strategist", events,
                 ["first_look_step", "s3_prepare", "run_role"])


def test_stop_records_await_first_look_stop_held_from_s3():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        a = AnswerRig(r)
        token = SR.Driver._first_look_answer(r.d, "stop", "", "S3")
        check("stop_records_await_first_look_stop_held_from_s3: the token is taken and the run goes on to its next `where`", token is True)
        check_eq("stop_records_await_first_look_stop_held_from_s3: the hold has the cause and the stage",
                 [s[1] for s in a.said if s[0] == "await"], [{"action": "await_implementation", "cause": "first_look_stop", "held_from": "S3"}])
        check("stop_records_await_first_look_stop_held_from_s3: no continue is recorded", not any(s[0] == "controller" for s in a.said))
        other = SR.Driver._first_look_answer(r.d, "wait, the build is old", "q", "S3")
        check("stop_records_await_first_look_stop_held_from_s3: other words are not read by code (the conductor, once)",
              other is False and any(s[0] == "unread" for s in a.said))


def test_question_names_stand_build_not_established():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes={**DEAD, "build": "not_established"})
        raised, _ = r.step()
        check_in("question_names_stand_build_not_established: the old-build line is there", "only because the build there is old", str(raised.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes={**DEAD, "build": "confirmed"})
        raised, _ = r.step()
        check_not_in("question_names_stand_build_not_established: a confirmed build does not say it", "only because the build there is old", str(raised.text))


def test_call_sits_before_s3_prepare():
    import inspect
    source = inspect.getsource(SR.Driver.stage_S3)
    first = source.index("self.first_look_step()")
    check("call_sits_before_s3_prepare: the call is in stage_S3 before every preparation and every role run",
          0 < first < source.index("self.s3_prepare()") and first < source.index("self.run_role(") and source.count("self.first_look_step()") == 1)


def test_s3_window_one_ignores_runner_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        art = Path(tmp)
        (art / "state").mkdir()
        strategist = {"stage": "S3", "role": "qa-test-strategist", "status": "accepted", "request_binding": {"purpose": "s3_labelling"}}
        runner = {"stage": "S3", "role": "qa-runner", "status": "accepted", "request_binding": {"purpose": "first_look"}}

        def judged(dispatches):
            (art / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
            return exit_gate._s3_window_one(art)
        check("s3_window_one_ignores_runner_dispatch: control - window 1 alone is window 1", judged({"S3-qa-test-strategist-1": strategist}) is True)
        check("s3_window_one_ignores_runner_dispatch: a runner dispatch after window 1 does not hide it",
              judged({"S3-qa-test-strategist-1": strategist, "S3-qa-runner-1": runner}) is True)
        check("s3_window_one_ignores_runner_dispatch: the runner alone is not window 1", judged({"S3-qa-runner-1": runner}) is False)
        check("s3_window_one_ignores_runner_dispatch: unreadable stays False (the plan is owed)", judged(["not a mapping"]) is False)


def _controller_story(root):
    """A REAL controller story in the new plan-contract mode through S2 (the first look runs before S3)."""
    import test_controller_state as BASE
    root = Path(root)
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    c = controller.Controller(root)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(3):
        BASE.accept_stage(c, root, f"S{number}")
    return c


def test_real_controller_registers_first_look_runner():
    """B1: the REAL controller admits a qa-runner dispatch of purpose first_look with no execution_kind, in the new mode, at both sites."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=GOOD)
        real = _controller_story(r.task)
        check_eq("real_controller_registers_first_look_runner: the story is in the new plan-contract mode (the world the defect lived in)",
                 real.state().get("plan_contract_mode"), "new")
        raised, _ = r.step(real_controller=real)
        known = real.state()["dispatches"].get(WALK) or {}
        check("real_controller_registers_first_look_runner: prepare and apply through the real controller registered the dispatch",
              known.get("role") == "qa-runner" and known.get("stage") == "S3" and (known.get("request_binding") or {}).get("purpose") == "first_look", known)
        check_eq("real_controller_registers_first_look_runner: so the walk ran, was not given up, and no null record was written",
                 (len(r.runs()), FL.read(r.task)["null"]), (1, ""))
    # the negative controls: every other runner dispatch is refused as today, at BOTH sites
    with tempfile.TemporaryDirectory() as tmp:
        real = _controller_story(tmp)
        plain = {"stage": "S3", "role": "qa-runner", "id": "S3-qa-runner-9"}
        for label, options in (("no purpose", plain), ("another purpose", dict(plain, purpose="initial"))):
            try:
                real.prepare(options)
                said = ""
            except ValueError as exc:
                said = str(exc)
            check_in(f"real_controller_registers_first_look_runner: prepare still refuses a plain runner ({label})", "requires execution_kind", said)
        request = real.prepare(dict(plain, purpose="first_look"))["dispatch_request"]
        for label, forged in (("no purpose", {k: v for k, v in request.items() if k != "purpose"}), ("another purpose", dict(request, purpose="initial"))):
            try:
                real.apply("dispatch", forged)
                said = ""
            except ValueError as exc:
                said = str(exc)
            check_in(f"real_controller_registers_first_look_runner: apply still refuses a plain runner ({label})", "requires execution_kind", said)
        check("real_controller_registers_first_look_runner: the predicate - first_look exempt, only for the new-mode runner",
              controller.runner_kind_required({"plan_contract_mode": "new"}, "qa-runner", "initial")
              and controller.runner_kind_required({"plan_contract_mode": "new"}, "qa-runner", "")
              and not controller.runner_kind_required({"plan_contract_mode": "new"}, "qa-runner", "first_look")
              and not controller.runner_kind_required({"plan_contract_mode": "legacy"}, "qa-runner", "initial")
              and not controller.runner_kind_required({"plan_contract_mode": "new"}, "qa-case-critic", "")
              and not controller.runner_kind_required(None, "qa-runner", ""))


def test_unaccepted_dispatch_keeps_attempt_and_goes_to_s3():
    """B3 (a): a dispatch that is not accepted keeps the attempt `put` wrote, asks nothing, and the next entry asks nothing either."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=DEAD, accepted=False)
        raised, said = r.step()
        check("unaccepted_dispatch_keeps_attempt_and_goes_to_s3: a record under an unaccepted dispatch asks nothing (S3 at once)", raised is None, raised)
        check_eq("unaccepted_dispatch_keeps_attempt_and_goes_to_s3: the attempt stays written, never overwritten to nothing_written",
                 FL.read_attempt(r.task)["outcome"], "written")
        check_in("unaccepted_dispatch_keeps_attempt_and_goes_to_s3: one gap line says it", "not accepted", said)
        again, _ = r.step()
        check("unaccepted_dispatch_keeps_attempt_and_goes_to_s3: a later entry asks nothing and dispatches nothing", again is None and len(r.runs()) == 1)
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=None, accepted=False)
        r.step()
        check_eq("unaccepted_dispatch_keeps_attempt_and_goes_to_s3: a runner that wrote nothing ends nothing_written (no state left walking)",
                 FL.read_attempt(r.task)["outcome"], "nothing_written")
        # control: the same DEAD record under an ACCEPTED dispatch does ask
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=DEAD, accepted=True)
        raised, _ = r.step()
        check("unaccepted_dispatch_keeps_attempt_and_goes_to_s3: control - accepted, it asks", raised is not None and raised.kind == "first_look_dead")


def test_dead_question_asked_once_per_walk():
    """B3 (b): an answer (any words) marks the walk asked; a later S3 entry does not ask again; a NEW walk (new head) may."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=DEAD)
        raised, _ = r.step()
        check("dead_question_asked_once_per_walk: asked", raised is not None)
        check("dead_question_asked_once_per_walk: raising the question marks nothing (a question nobody answered comes back after a restart)",
              not FL.asked(r.task))
        AnswerRig(r)
        SR.Driver._first_look_answer(r.d, "wait, the build is old", "q", "S3")      # free words: the conductor's, once
        check("dead_question_asked_once_per_walk: an answer, even free words, marks the walk asked", FL.asked(r.task))
        again, _ = r.step()
        check("dead_question_asked_once_per_walk: the next S3 entry does not ask again and walks nothing", again is None and len(r.runs()) == 1)
        r.set_heads(HEAD_B)
        later, _ = r.step()
        check("dead_question_asked_once_per_walk: a new head is a new walk and may ask (FR-7: a new boundary)",
              later is not None and len(r.runs()) == 2 and not FL.asked(r.task))


def test_take_answer_routes_first_look_dead():
    """Decision 1: `take_answer` itself sends the answer of kind first_look_dead to `_first_look_answer` (continue, stop, free words)."""
    def drive(words):
        with tempfile.TemporaryDirectory() as tmp:
            r = Rig(tmp)
            a = AnswerRig(r)
            d = r.d
            d.state = {"asked": {"kind": "first_look_dead", "stage": "S3", "dispatch": ""}}
            d.state_dir = r.task / "state"
            d.state_dir.mkdir(exist_ok=True)
            d.take_stand_gap_answers = lambda *x, **k: {}
            d.take_exploratory_answers = lambda *x, **k: None
            d._file_words = lambda *x, **k: None
            d.save_state, d.dry = (lambda: None), True       # a dry driver writes nothing of its own state
            path = r.task / "words.txt"
            path.write_text(words, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                SR.Driver.take_answer(d, path)
            return a.said, FL.asked(r.task), FL.current_keys(r.task)
    said, _asked, (heads, reg) = drive("continue\nthe stand is old")
    sent = [s for s in said if s[0] == "controller"]
    check("take_answer_routes_first_look_dead: `continue` reaches first_look_continue with the keys of now",
          len(sent) == 1 and sent[0][1] == "first_look_continue" and sent[0][2][2:] == ("--source-head", heads, "--register-hash", reg), sent)
    said, _, _ = drive("stop")
    check_eq("take_answer_routes_first_look_dead: `stop` reaches the await of cause first_look_stop held from S3",
             [s[1] for s in said if s[0] == "await"], [{"action": "await_implementation", "cause": "first_look_stop", "held_from": "S3"}])
    said, asked, _ = drive("please wait for the right build")
    check("take_answer_routes_first_look_dead: free words go to the conductor once (unread), no token is executed",
          any(s[0] == "unread" for s in said) and not any(s[0] in ("controller", "await") for s in said))


def test_actors_accounts_first_guest_fills_a_free_slot():
    """J-18 (decision 2): accounts first up to max_actors, guest takes a slot left over; more accounts than slots -> the registry's order."""
    from unittest import mock
    import manual_capture
    import project_knowledge as PK

    def element(role, account=True):
        return {"role": role, "account": account, "sign_in": "account"}

    def actors(default, roles, none=()):
        roster = {"elements": [element(n) for n in roles] + [element(n, False) for n in none], "problem": ""}
        with mock.patch.object(manual_capture, "read_login", lambda cfg, root: ({"user": "u"} if default else None)), \
                mock.patch.object(PK, "roster", lambda *a, **k: roster):
            return FL.walk_actors("p", {}, STAND, 2)
    check_eq("actors: no account -> guest alone", actors(False, [])["actors"], ["guest"])
    check_eq("actors: one account -> account and guest", actors(True, [])["actors"], ["default", "guest"])
    check_eq("actors: one roster account, no default -> account and guest", actors(False, ["editor"])["actors"], ["editor", "guest"])
    two = actors(True, ["editor"])
    check_eq("actors: two accounts -> both, guest dropped (an account is never dropped for guest)", two["actors"], ["default", "editor"])
    many = actors(True, ["admin", "editor", "viewer"], none=["auditor"])
    check_eq("actors: more accounts than slots -> the first two in the sources' own order, the rest named as left",
             (many["actors"], many["left"], many["none"]), (["default", "admin"], ["editor", "viewer"], ["auditor"]))
    check("actors: the walk never has more than max_actors", all(len(x["actors"]) <= 2 for x in (two, many)))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, writes=GOOD)
        with mock.patch.object(manual_capture, "read_login", lambda cfg, root: {"user": "u"}), \
                mock.patch.object(PK, "roster", lambda *a, **k: {"elements": [element("admin"), element("editor")], "problem": ""}):
            _, said = r.step()
        argv = r.argv("walk_session.py", "open")
        check_eq("actors: the driver opens the first two accounts in order", (argv[argv.index("--actor") + 1], argv[argv.index("--actor2") + 1]),
                 ("default", "admin"))
        check_in("actors: and says which account was not opened", "accounts not opened (the walk holds 2): editor", said)


def test_specific_null_is_kept_over_walk_not_opened():
    """m3: a specific null (profile_not_chosen: exit 3 with its cause, retried once) is not overwritten by walk_not_opened on entry 3+."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, open_result=(3, json.dumps({"status": "not_started", "cause": "profile_not_chosen"})))
        for _ in range(4):
            r.step()
        check_eq("specific_null_is_kept_over_walk_not_opened: after the retry is spent the reason is still the specific one",
                 FL.read(r.task)["null"], "profile_not_chosen")


def _optional_story(tmp, dispatches):
    """A story folder `QA-1` with a controller.json holding `dispatches`; `exit_gate.artifact_root` points at it."""
    art = Path(tmp) / "artifacts"
    (art / "QA-1" / "state").mkdir(parents=True)
    (art / "QA-1" / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
    (art / "QA-1" / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}}), encoding="utf-8")
    return art


def test_exit_gate_judges_first_look_runner_by_its_own_output():
    """B2 (reader 1): the SubagentStop gate places a running first-look runner on S3 and judges it by `work/first-look.yaml` - not by S6's
    run report, nor by S3's plan files; a plain runner and an ambiguous stop keep today's placement."""
    from unittest import mock
    look = {"stage": "S3", "role": "qa-runner", "status": "running", "request_binding": {"purpose": "first_look"}}
    plain = {"stage": "S6", "role": "qa-runner", "status": "running", "request_binding": {"purpose": "manual"}}
    with tempfile.TemporaryDirectory() as tmp:
        art = _optional_story(tmp, {WALK: look})
        with mock.patch.object(exit_gate, "artifact_root", lambda: art):
            check_eq("exit_gate_judges_first_look_runner: the stage is S3", exit_gate._stage_id("qa-runner", "QA-1"), "S3")
            missing = exit_gate.required_outputs_errors("qa-runner", "QA-1")
            text = " ".join(str(m) for m in missing)
            check("exit_gate_judges_first_look_runner: no record -> the missing output is the first look's own",
                  "work/first-look.yaml" in text and "run-report" not in text and "test-plan" not in text, text)
            (art / "QA-1" / "work").mkdir()
            (art / "QA-1" / "work" / "first-look.yaml").write_text("rows:\n", encoding="utf-8")
            check_eq("exit_gate_judges_first_look_runner: a record written -> nothing owed (not S3's plan, not S6's report)",
                     exit_gate.required_outputs_errors("qa-runner", "QA-1"), [])
    with tempfile.TemporaryDirectory() as tmp:
        art = _optional_story(tmp, {"S6-qa-runner-1": plain})
        with mock.patch.object(exit_gate, "artifact_root", lambda: art):
            check_eq("exit_gate_judges_first_look_runner: control - a plain S6 runner stays on S6", exit_gate._stage_id("qa-runner", "QA-1"), "S6")
            check_in("exit_gate_judges_first_look_runner: and is still owed the run report",
                     "work/run-report.json", " ".join(str(m) for m in exit_gate.required_outputs_errors("qa-runner", "QA-1")))
    with tempfile.TemporaryDirectory() as tmp:
        art = _optional_story(tmp, {WALK: look, "S3-qa-runner-2": dict(look)})
        with mock.patch.object(exit_gate, "artifact_root", lambda: art):
            check_eq("exit_gate_judges_first_look_runner: two running runners - not established as an optional one (AR-28), S6 as before",
                     exit_gate._stage_id("qa-runner", "QA-1"), "S6")
            with exit_gate.holding_dispatch(WALK):
                check_eq("exit_gate_judges_first_look_runner: a held dispatch names the one", exit_gate._stage_id("qa-runner", "QA-1"), "S3")


def s3_readers_with_first_look_dispatch_present():
    """B2 (readers in story_run): with a first-look runner record among the S3 dispatches - even the newest - `s3_window`, `s3_author_done`
    and `stage_S3` itself read the STRATEGIST's records only: the plan's window and the critic's route are what they would be without it."""
    runner = {"stage": "S3", "role": "qa-runner", "status": "accepted", "request_binding": {"purpose": "first_look"}}
    w1 = {"stage": "S3", "role": "qa-test-strategist", "status": "accepted", "request_binding": {"purpose": "s3_labelling"}}
    w2 = {"stage": "S3", "role": "qa-test-strategist", "status": "accepted"}
    d = SR.Driver.__new__(SR.Driver)

    def at(dispatches):
        d.controller_state = lambda: {"dispatches": dispatches}
        return d.s3_window(), d.s3_author_done()
    check_eq("s3_readers: window 1 accepted, the runner newest -> between the windows, plan not written",
             at({"S3-qa-test-strategist-1": w1, "S3-qa-runner-2": runner}), ("between", False))
    check_eq("s3_readers: window 2 accepted, the runner newest -> the author is done", at({"a": w1, "b": w2, "S3-qa-runner-2": runner}), ("w1", True))
    check_eq("s3_readers: the runner alone -> no strategist work at all", at({"S3-qa-runner-1": runner}), ("w1", False))
    check_eq("s3_readers: control - nothing at all", at({}), ("w1", False))
    gone = dict(w2, status="superseded")
    check_eq("s3_readers: pin - a set-aside newest strategist record does not count (window 1 accepted stays the newest)",
             at({"a": w1, "b": gone}), ("between", False))
    check_eq("s3_readers: pin - only a set-aside window 1 -> nothing counts", at({"a": dict(w1, status="released_by_person")}), ("w1", False))
    check_eq("s3_readers: pin - a runner record changes nothing next to set-aside ones",
             at({"a": w1, "b": gone, "S3-qa-runner-2": runner}), ("between", False))
    calls = []
    d.stages = lambda: {"S3": {"roles": ["qa-test-strategist", "qa-case-critic"]}}
    d.stage_acceptor = lambda stage: "qa-case-critic"
    d.first_look_step = lambda: None
    d.stage_critic_route = lambda stage, role: calls.append(("critic_route", stage, role))
    d.run_role = lambda *a, **k: calls.append(("run_role", a))
    d.controller_state = lambda: {"dispatches": {"a": w1, "b": w2, "S3-qa-runner-2": runner}}
    SR.Driver.stage_S3(d)
    check_eq("s3_readers: stage_S3 goes to the critic's route over the author's accepted exit window, not back to the strategist",
             calls, [("critic_route", "S3", "qa-test-strategist")])


def test_s3_readers_ignore_first_look_dispatch():
    s3_readers_with_first_look_dispatch_present()


def test_strategist_records_reader_is_the_one_filter():
    """m2 / B2 (reader 2): the strategist's records are one reader - the runner's record is none of them, a set-aside record does not count."""
    records = {"S3-qa-runner-1": {"stage": "S3", "role": "qa-runner", "status": "accepted"},
               "S3-qa-test-strategist-1": {"stage": "S3", "role": "qa-test-strategist", "status": "superseded"},
               "S3-qa-test-strategist-2": {"stage": "S3", "role": "qa-test-strategist", "status": "accepted"}}
    check_eq("strategist_records_reader: only the counting strategist record", list(exit_gate.s3_strategist_records(records)), ["S3-qa-test-strategist-2"])
    check_eq("strategist_records_reader: a non-mapping is no records", exit_gate.s3_strategist_records(["x"]), {})


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_first_look_step")


if __name__ == "__main__":
    main()
