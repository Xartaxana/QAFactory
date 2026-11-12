#!/usr/bin/env python3
"""t-1957 N1a: the kept-session server `walk_session.py` - lifecycle, items, sign-in, evidence (fake backend, no browser, no network).

The server runs in-process: a `Walk` is built and started with `MC.BACKEND_FACTORY` set to a fake, requests go through `Walk.dispatch`
(the same call the TCP handler makes); `test_open_writes_state_with_token_loopback_and_birth` goes through `open_walk` and a real
loopback server thread. The step-call rules (stops, batch limits) are in test_walk_batch.py.
Negative controls: end-probe copy disabled -> test_every_item_attempt_has_start_and_end_probe fails; `stop=` not passed by the server ->
test_walk_batch.test_default_stops_on_5xx_console_url fails.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import threading
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_manual_capture as T  # noqa: E402
import test_manual_capture_session as SS  # noqa: E402
import test_manual_surprise as TS  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

import manual_evidence as ME  # noqa: E402
import walk_session as WS  # noqa: E402

MC = S.MC
CASE, CASE2 = T.UI_CASE, S.CASES["api"]
WALK = "S6-qa-runner-1"
GO = f"goto {TS.PAGE}\n"


class WB(TS.EventBrowser):
    """The event fake with a profile folder, a `look` and a sign-in that lands (or not)."""

    def open(self, timeout_s, allowed_hosts, local_storage=None, element_wait_s=None, profile_dir=None):
        super().open(timeout_s, allowed_hosts, local_storage, element_wait_s)
        self.opens = getattr(self, "opens", 0) + 1
        if profile_dir is not None:
            Path(profile_dir).mkdir(parents=True, exist_ok=True)

    def forget_failures(self):
        """The real backend's contract: every rule lifted and forgotten, what each caught handed back."""
        seen = self.drain_failures()
        self.failing = {}
        return seen

    def look(self, selector=None):
        self.looked = getattr(self, "looked", 0) + 1
        return "heading: Cart\nbutton: Pay", "aria", "", 0.05


class Rig:
    """A task with the stand's accounts and gate A's proof, the fake backends made so far, and the walk."""

    def __init__(self, items=(CASE, CASE2), actors=("user",), cfg=None, probed=("user", "admin"), kw=None, **browser):
        self.t = SS.task(cfg, probed=probed)
        self.made, self.kw, self.browser = [], kw or {}, browser
        MC.BACKEND_FACTORY = self.factory
        MC.PROBE = lambda spec: S.probe("api" if spec["argv"] == ["probe-api"] else "e2e-ui")
        MC.NOW = S.Clock()
        MC.MONOTONIC = lambda: self.made[-1].now if self.made else 0.0
        WS.SEAMS.update(clock=None, spawn=None)
        WS.OVERRIDE.clear()
        self.walk = WS.Walk(self.t.task, WALK, list(items), list(actors))

    def factory(self):
        b = WB(**{**self.browser, **self.kw.get(len(self.made), {})})
        self.made.append(b)
        return b

    def start(self):
        self.walk.start()
        return self

    def call(self, op, **fields):
        return self.walk.dispatch({"op": op, "token": self.walk.token, **fields})

    def step(self, text, item=CASE, **fields):
        return self.call("step", item=item, steps=text, **fields)

    def attempt(self, item=CASE, name="a1"):
        return MC.case_root(self.t.task, item) / name

    def done(self):
        with contextlib.suppress(Exception):
            self.walk._shutdown("dead", "test over", probe=False)
        MC.BACKEND_FACTORY = None
        WS.OVERRIDE.clear()
        S.cleanup(self.t)


def with_rig(fn):
    def wrapped(*a, **k):
        rig = Rig(*a, **k)
        try:
            fn(rig.start())
        finally:
            rig.done()
    return wrapped


def jsonl(path):
    return T.jsonl(path) if Path(path).is_file() else []


# --------------------------------------------------------------------------------------------

def test_open_writes_state_with_token_loopback_and_birth():
    rig = Rig()
    try:
        def spawn(argv, log):
            thread = threading.Thread(target=WS.main, args=(argv[3:],), daemon=True)
            thread.start()
            return thread
        WS.SEAMS["spawn"] = spawn
        args = WS.build_parser().parse_args(["open", "--task-root", str(rig.t.task), "--walk", WALK, "--items", CASE, "--actor", "user"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = WS.open_walk(args, wait_s=20)
        record = WS.read_record(rig.t.task, WALK)
        check_eq("open ends 0 and prints ONE JSON line", (code, json.loads(out.getvalue())["status"]), (0, "ready"))
        check_eq("the record is ready, signed in, with a 64-hex token and a loopback port",
                 (record["state"], record["signed_in"], len(record["token"]), record["port"] > 0), ("ready", True, 64, True))
        check("it holds the server's pid and its birth, and the parent's", record["pid"] == os.getpid() and record["started"] and record["parent_pid"], str(record))
        check("the printed line holds no token", record["token"] not in out.getvalue())
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(io.StringIO()):
            bad = WS.call(rig.t.task, WALK, {"op": "item", "item": CASE})
            closed = WS.call(rig.t.task, WALK, {"op": "close"})
        check_eq("a command reaches the server over the socket and the close ends it", (bad, closed), (0, 0))
        check_eq("the record says closed", WS.read_record(rig.t.task, WALK)["state"], "closed")
    finally:
        rig.done()


@with_rig
def test_step_runs_on_kept_page_no_reopen(rig):
    for text in (GO, 'click "#a"\n', 'click "#b"\n'):
        code, answer = rig.step(text)
        check_eq("each call ends done", (code, answer["status"]), (0, "done"))
    check_eq("the backend was made and opened once for three calls", (len(rig.made), rig.made[0].opens), (1, 1))
    check_eq("the page was visited once", [c for c in rig.made[0].calls if c[0] == "goto"], [("goto", TS.PAGE)])


@with_rig
def test_fill_keys_by_character_kept(rig):
    code, answer = rig.step(GO + 'type "#qty" 12\n')
    typed = [c for c in rig.made[0].calls if c[0] == "type"]
    check_eq("`type` went through the recorder's keyed path with the text", [(c[1], c[2]) for c in typed], [("#qty", "12")])
    check_eq("and the call is done", answer["status"], "done")


@with_rig
def test_surprise_lines_once_per_call(rig):
    rig.made[0].born[("click", "#a")] = [TS.ev("response", "GET", "/books/3", 404, rid=2)]
    rig.step(GO + 'click "#a"\n')
    rig.step('click "#b"\n')
    files = [c for c in jsonl(rig.attempt() / "captures.jsonl") if "surprises" in c["path"]]
    check_eq("one surprises file, from the call that met the line", len(files), 1)
    check_eq("the second call's list was reset", rig.walk.item_rec[CASE]["attempt"].call_surprises, [])


@with_rig
def test_look_stores_state_file(rig):
    rig.step(GO)
    code, answer = rig.call("look", item=CASE)
    caps = jsonl(rig.attempt() / "captures.jsonl")
    check_eq("look is ok", (code, answer["look"]["outcome"]), (0, "ok"))
    check("and stored a state file", any(c["kind"] == "state" and "look" in c["path"] for c in caps), str(caps))


@with_rig
def test_final_one_snapshot_one_screenshot(rig):
    rig.step(GO)
    code, answer = rig.call("final", item=CASE)
    caps = jsonl(rig.attempt() / "captures.jsonl")
    check_eq("final is ok", (code, [o["outcome"] for o in answer["final"]]), (0, ["ok", "ok"]))
    check_eq("one snapshot and one screenshot", ([c["kind"] for c in caps if "look" in c["path"]], [c["phase"] for c in caps if c["kind"] == "image"]),
             (["state"], ["post_action"]))


@with_rig
def test_look_final_refused_in_signin_window(rig):
    rig.step(GO)
    rig.walk.accounts["user"].window = True
    for op in ("look", "final"):
        code, answer = rig.call(op, item=CASE)
        check_eq(f"{op} inside the window is refused (2)", code, 2)
        check_in(f"{op}: with the screenshot rule's words", MC.NO_SHOT_IN_WINDOW, answer["text"])
    check_eq("nothing was looked at", getattr(rig.made[0], "looked", 0), 0)


@with_rig
def test_wrong_token_refused_nothing_run(rig):
    for token in ("", "x" * 64):
        code, answer = rig.walk.dispatch({"op": "step", "token": token, "item": CASE, "steps": GO})
        check_eq("a wrong token is refused (2)", code, 2)
        check_in("and the refusal names status", "status --walk", answer["text"])
    check_eq("nothing was run (only the sign-in of the open)", [c for c in rig.made[0].calls if c[0] != "login"], [])
    check("the refusal is logged", "token" in WS.record_path(rig.t.task, WALK).with_suffix(".log").read_text(encoding="utf-8"))
    code, answer = rig.call("step", item="NOT-AN-ITEM", steps=GO)
    check_eq("an item outside the walk is refused naming status", (code, "status --walk" in answer["text"]), (2, True))


def test_actor_held_refused():
    rig = Rig().start()
    try:
        req = {"op": "open", "task_root": str(rig.t.task), "walk": "S6-qa-runner-2", "items": [CASE], "actors": ["user"]}
        problems = WS.request_problems(None, req)
        check("a second live walk may not take the account", any("account user is walking in " + WALK in p for p in problems), str(problems))
        check_eq("another account is free", WS.request_problems(None, {**req, "actors": ["admin"]}), [])
        check_eq("guest is never held", WS.request_problems(None, {**req, "actors": ["guest"]}), [])
        check("an empty item list is refused", "at least one item" in WS.request_problems(None, {**req, "items": []})[0])
        check("a third actor is refused naming the limit", "at most" in " ".join(WS.request_problems(None, {**req, "actors": ["a", "b", "c"]})) or
              "1 to 2 actors" in " ".join(WS.request_problems(None, {**req, "actors": ["a", "b", "c"]})))
    finally:
        rig.done()


def test_dead_record_taken_over_fresh_profile_dir():
    rig = Rig()
    try:
        base = WS.walk_dir(rig.t.task, WALK)
        (base / "sessions" / "user-1" / "profile").mkdir(parents=True)
        WS.event_store.atomic_json(WS.record_path(rig.t.task, WALK), {"walk": WALK, "state": "ready", "pid": 999999, "started": "winfiletime:1", "actors": ["user"]})
        req = {"op": "open", "task_root": str(rig.t.task), "walk": WALK, "items": [CASE], "actors": ["user"]}
        check_eq("the orphan blocks neither the walk id nor the account", WS.request_problems(None, req), [])
        record = WS.read_record(rig.t.task, WALK)
        check_eq("its record is taken over", (record["state"], record["reason"]), ("dead", "dead (taken over)"))
        check("and its profile folder is deleted", not (base / "sessions" / "user-1").exists())
        (base / "sessions" / "user-1" / "profile").mkdir(parents=True)
        rig.walk.start()
        check_eq("a start with a folder left behind opens the next number", rig.walk.sessions["user"]["folder"].endswith("user-2"), True)
    finally:
        rig.done()


def test_profile_delete_failure_is_a_note():
    rig = Rig().start()
    try:
        with mock.patch.object(shutil, "rmtree", side_effect=OSError("locked")):
            code, answer = rig.call("close")
        check_eq("close still ends 0 and the walk is closed", (code, rig.walk.state), (0, "closed"))
        check("the failure is a note line", any("was not deleted" in n for n in answer["notes"]), str(answer["notes"]))
    finally:
        rig.done()


def test_idle_exit_releases_lease():
    import run_suite
    import stand_lease
    cfg = SS.config()
    cfg["run"] = {"parallel": False, "manual_stand_wait_s": 0}
    rig = Rig(cfg=cfg)
    try:
        with mock.patch.object(run_suite, "project_root", lambda: rig.t.project):
            rig.start()
            held = False
            try:
                with stand_lease.hold(rig.t.project, "other", "localhost", 0):
                    pass
            except stand_lease.StandBusy:
                held = True
            check("the walk holds the stand's lease while it lives", held)
            WS.SEAMS["clock"] = lambda: rig.walk.started_at + rig.walk.d["idle_s"] + 1
            why = rig.walk.watchdog()
            check_in("an idle server finds its reason", "idle", why)
            rig.walk._shutdown("dead", why, probe=False)
            with stand_lease.hold(rig.t.project, "other", "localhost", 0):
                freed = True
            check_eq("and the server releases the lease itself; state dead", (freed, rig.walk.state, WS.read_record(rig.t.task, WALK)["state"]), (True, "dead", "dead"))
            code, answer = rig.walk.dispatch({"op": "step", "token": rig.walk.token, "item": CASE, "steps": GO})
            check_eq("a later step meets 'not ready' (3)", (code, answer["status"]), (3, "not_ready"))
    finally:
        WS.SEAMS["clock"] = None
        rig.done()


def test_parent_gone_by_same_process():
    ES = WS.execution_scheduler
    rig = Rig()
    try:
        rig.walk.parent_pid, rig.walk.parent_started = os.getpid(), ES._started(os.getpid())
        check_eq("the live parent is no reason", rig.walk.watchdog(), "")
        rig.walk.parent_started = "winfiletime:1"
        check_in("the same pid with another birth is a gone parent (pids are reused)", "gone", rig.walk.watchdog())
    finally:
        rig.done()


@with_rig
def test_answer_cut_names_file(rig):
    WS.OVERRIDE["batch_answer_chars"] = 900
    lines = GO + "".join(f'click "#b{i}"\n' for i in range(12)) + 'click "#missing"\n'
    rig.made[0].missing = {"#missing"}
    code, answer = rig.step(lines)
    check_eq("the call stopped on the failed step", (code, answer["stopped_at"]["reason"]), (1, "failed"))
    check("the answer is within the limit", len(json.dumps(answer)) <= 900, str(len(json.dumps(answer))))
    check_in("it names the file that holds it whole", answer["answer_file"], answer["cut"])
    check("the stop is not what was cut", answer["stopped_at"]["step"] == 'click "#missing"' and answer["not_run_count"] == 0)
    whole = json.loads((rig.t.task / answer["answer_file"]).read_text(encoding="utf-8"))
    check_eq("the file holds every step (the goto, 12 clicks, the failed one, and the server's own `pre_action` capture, t-2016 F1)", len(whole["steps"]), 15)
    check("the extra step is the server's capture, not a role step", sum(1 for s in whole["steps"] if "capture" in json.dumps(s)) >= 1, json.dumps(whole["steps"])[:300])


def test_next_attempt_after_fallback_attempts():
    rig = Rig()
    try:
        MC.Attempt(rig.t.task, CASE, "a1", rig.t.cfg)
        rig.walk.start()
        rig.step(GO)
        check_eq("a walk opens the NEXT attempt and never rewrites a1", (rig.walk.item_rec[CASE]["attempt"].name, (rig.attempt() / "steps.jsonl").exists()), ("a2", False))
        check("the evidence is in a2", (rig.attempt(name="a2") / "steps.jsonl").is_file())
    finally:
        rig.done()


@with_rig
def test_every_item_attempt_has_start_and_end_probe(rig):
    rig.step(GO + "capture pre_action initial\n")
    rig.step(GO + "capture pre_action initial\n", item=CASE2)
    code, answer = rig.call("close")
    check_eq("close ends 0", code, 0)
    for item in (CASE, CASE2):
        folder = MC.case_root(rig.t.task, item) / "a1"
        rows = jsonl(folder / "probes.jsonl")
        check_eq(f"{item}: a start and an end probe of one profile", sorted((r["when"], r["profile"]) for r in rows), [("end", "e2e-ui"), ("start", "e2e-ui")])
        try:
            ME._attempt_files(folder, "a1", item)
            accepted = True
        except ValueError as exc:
            accepted = str(exc)
        check_eq(f"{item}: manual_evidence._attempt_files accepts the attempt", accepted, True)


@with_rig
def test_requests_seen_split_per_item(rig):
    b = rig.made[0]
    b.born[("click", "#a")] = [TS.ev("request", "GET", "/first")]
    b.born[("click", "#b")] = [TS.ev("request", "GET", "/second")]
    b.allowed = {MC.host_key(TS.API)}
    b.drain_requests = lambda: {"rows": []}
    rig.step(GO + 'click "#a"\n')
    rig.step(GO + 'click "#b"\n', item=CASE2)
    rig.call("done")
    def seen(item):
        files = list(MC.case_root(rig.t.task, item).glob("a1/*requests-seen*"))
        return files[0].read_text(encoding="utf-8").splitlines() if files else []
    check_eq("item one's file holds its own request", [x for x in seen(CASE) if "first" in x or "second" in x], [f"GET {TS.API}/first"])
    check_eq("item two's file holds only its own", [x for x in seen(CASE2) if "first" in x or "second" in x], [f"GET {TS.API}/second"])


def test_login_unknown_opens_unsigned():
    rig = Rig(probed=())
    try:
        rig.walk.start()
        s = rig.walk.sessions["user"]
        check_eq("no proof at gate A: the walk lives, unsigned", (rig.walk.state, s["state"], s["signed_in"]), ("ready", "ready", False))
        check_in("the note says it is the factory's", "factory", s["note"])
        code, answer = rig.step(GO)
        check_eq("and steps run (the door is `fill-account`)", (code, answer["status"]), (0, "done"))
        check("no sign-in was tried", not any(c[0] == "login" for c in rig.made[0].calls))
    finally:
        rig.done()


def test_user_refused_signin_is_dead():
    rig = Rig(kw={0: {"lands_at": None, "cookies_at": None, "field_gone_at": None, "urls": [S.SIGN_IN_URL]}})
    try:
        rig.walk.start()
        check_eq("the walk lives, the actor's session is dead", (rig.walk.state, rig.walk.sessions["user"]["state"]), ("ready", "dead"))
        row = json.loads((MC.case_root(rig.t.task, CASE) / "a1" / "env_blocked.json").read_text(encoding="utf-8"))
        check_eq("env_blocked.json is written per item as _session_blocked has it (owner environment, cause stand)",
                 (row["owner"], row.get("cause"), row.get("do_not_retry")), ("environment", "stand", True))
        code, answer = rig.step(GO)
        check_eq("a step as that actor meets 'not ready' (3)", (code, answer["status"]), (3, "not_ready"))
    finally:
        rig.done()


def test_reopen_keeps_items_with_verdict():
    rig = Rig().start()
    try:
        rig.step(GO)
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": [], "limitation": "the case lists no Then"})
        check_eq("a verdict that the case record accepts is stored", code, 0)
        rig.call("close")
        again = WS.Walk(rig.t.task, WALK, [CASE, CASE2], ["user"], reopened=1)
        again.start()
        code, answer = again.dispatch({"op": "step", "token": again.token, "item": CASE, "steps": GO})
        check_eq("the item with a verdict is never walked again in this dispatch", (code, "verdict on disk" in answer["text"]), (2, True))
        code, answer = again.dispatch({"op": "step", "token": again.token, "item": CASE2, "steps": GO})
        check_eq("the other item is", (code, answer["status"], WS.read_record(rig.t.task, WALK)["reopened"]), (0, "done", 1))
        again._shutdown("dead", "test over", probe=False)
    finally:
        rig.done()


def test_second_actor_context():
    rig = Rig(actors=("user", "admin")).start()
    try:
        check_eq("one backend per actor", len(rig.made), 2)
        rig.step(GO, actor="admin")
        check_eq("`--as` acts in the second actor's context", ([c for c in rig.made[1].calls if c[0] == "goto"], [c for c in rig.made[0].calls if c[0] == "goto"]), ([("goto", TS.PAGE)], []))
        code, answer = rig.step(GO, actor="nobody")
        check_eq("an actor beyond the walk's is refused naming the limit", (code, "at most" in answer["text"]), (2, True))
    finally:
        rig.done()


@with_rig
def test_step_opens_item_attempt_when_not_open(rig):
    check_eq("no attempt before the first step", MC.attempts_of(MC.case_root(rig.t.task, CASE)), [])
    rig.step(GO)
    check_eq("the step opened it, with its start probe", (MC.attempts_of(MC.case_root(rig.t.task, CASE)), [r["when"] for r in jsonl(rig.attempt() / "probes.jsonl")]),
             (["a1"], ["start"]))
    code, answer = rig.call("item", item=CASE2)
    check_eq("`item` opens one without a step", (code, answer["attempt"]), (0, "a1"))


@with_rig
def test_failure_rule_of_item_one_is_forgotten_at_the_boundary(rig):
    """TR1-2: a rule item one never lifted ends with item one; item two does not see it, item one's evidence holds its result."""
    b = rig.made[0]
    b.allowed = {MC.host_key(TS.API)}
    code, one = rig.step(GO + "fail_request **/api/x 500\n", item=CASE)
    check_eq("item one declares a failing rule", (code, b.failing["**/api/x"]["active"]), (0, True))
    b.hit("**/api/x")        # the rule catches one request AFTER item one's call ended (that call's own log says 0)
    code, two = rig.step(GO + "capture post_action second\n", item=CASE2)
    check_eq("item two's post_action capture passes (it does not see item one's rule)", (code, two["steps"][-1]["outcome"]), (0, "ok"))
    check_eq("the rule is lifted and forgotten on the backend", b.failing, {})
    logs = [p.read_text(encoding="utf-8") for p in (rig.attempt()).glob("*fail-request*")]
    check_eq("item one's evidence holds the result of the rule at the boundary (`requests failed: 1`)",
             [x for x in logs if "pattern: **/api/x" in x and "requests failed: 1" in x] != [], True)
    check_eq("item two's evidence holds none", list(rig.attempt(CASE2).glob("*fail-request*")), [])


@with_rig
def test_the_hint_and_the_surprise_line_reach_the_step_answer(rig):
    """F6: the pattern hint, and the line a restored rule that matched nothing leaves, are in the answer the walker reads (not only in steps.jsonl)."""
    rig.made[0].allowed = {MC.host_key(TS.API)}
    code, answer = rig.step(GO + "fail_request */api/cart 500\n")
    check_in("the hint is in the step answer", "does not cross `/`", json.dumps(answer["steps"][-1].get("told")))
    code, answer = rig.step("fail_request **/api/cart 500\n")
    check_eq("`**/api/cart` has no `told` in the answer", answer["steps"][-1].get("told"), None)
    code, answer = rig.step("fail_request **/api/x 500\nrestore_request **/api/x\nread #x\nread #x\n")
    check_in("the restore row carries the line", "surprise: fail_request **/api/x matched no request", json.dumps(answer["steps"][1].get("told")))
    check_in("the first `read` carries it", "matched no request", json.dumps(answer["steps"][2].get("told")))
    check_eq("the second `read` does not", answer["steps"][3].get("told"), None)


def test_open_max_shared_reaches_the_session_and_the_own_process():
    """t-2147 C1: `open --max-shared N` (int >= 1, default 1) is the session's `max_shared`, also in the spawned own process; a bad value is refused."""
    rig = Rig()
    try:
        seen = []
        parse = WS.build_parser().parse_args
        base = ["open", "--task-root", str(rig.t.task), "--walk", WALK, "--items", CASE, "--actor", "user"]
        check_eq("no flag reads 1", parse(base).max_shared, 1)
        check_eq("`--max-shared 3` reads 3", parse(base + ["--max-shared", "3"]).max_shared, 3)
        for bad in ("0", "-1", "x", "1.5"):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                try:
                    parse(base + ["--max-shared", bad])
                    code = None
                except SystemExit as exc:
                    code = exc.code
            check(f"`--max-shared {bad}` is refused", code not in (None, 0), str(code))

        def spawn(argv, log):
            seen.append(list(argv))
            return type("H", (), {"kill": lambda self: None})()
        WS.SEAMS["spawn"] = spawn
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            WS.open_walk(parse(base + ["--max-shared", "3"]), wait_s=0.2)
            WS.open_walk(parse(base), wait_s=0.2)
        check_eq("the own process is told 3", seen[0][seen[0].index("--max-shared") + 1] if "--max-shared" in seen[0] else None, "3")
        check("the default call keeps the old argv (no flag)", "--max-shared" not in seen[1], str(seen[1]))
        own = WS.Walk(rig.t.task, WALK, [CASE], ["user"], max_shared=3)
        check_eq("the session carries it; an old caller reads 1", (own.max_shared, WS.Walk(rig.t.task, WALK, [CASE], ["user"]).max_shared), (3, 1))
        served = WS.build_parser().parse_args(["serve", "--task-root", str(rig.t.task), "--walk", WALK, "--items", CASE, "--actor", "user", "--max-shared", "3"])
        check_eq("`serve` takes the flag the open passes", served.max_shared, 3)
    finally:
        rig.done()


def test_walk_record_carries_max_shared_for_a_reopen():
    """t-2239 F4: the opening record and `write_state` carry `max_shared`, so `walk_reopen` can pass it again; no flag writes 1."""
    rig = Rig()
    try:
        parse = WS.build_parser().parse_args
        base = ["open", "--task-root", str(rig.t.task), "--walk", WALK, "--items", CASE, "--actor", "user"]
        WS.SEAMS["spawn"] = lambda argv, log: type("H", (), {"kill": lambda self: None})()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            WS.open_walk(parse(base + ["--max-shared", "3"]), wait_s=0.1)
        check_eq("the opening record carries 3", WS.read_record(rig.t.task, WALK).get("max_shared"), 3)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            WS.open_walk(parse(base), wait_s=0.1)
        check_eq("no flag writes 1", WS.read_record(rig.t.task, WALK).get("max_shared"), 1)
        WS.Walk(rig.t.task, WALK, [CASE], ["user"], max_shared=3).write_state()
        check_eq("the session's own state record carries 3", WS.read_record(rig.t.task, WALK).get("max_shared"), 3)
    finally:
        rig.done()


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_walk_session")


if __name__ == "__main__":
    main()
