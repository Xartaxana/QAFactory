#!/usr/bin/env python3
"""EP1-41g: the whole mobile road on a fake device, end to end. A native Android profile plus (or without) an API stand, the factory's own
code from the stand check to the evidence record, and NO production code edited for it.

WHAT IS REAL and what is a fake (t-544 section 4, FR-33). Real: readiness, `env_probe.py` and the S0 driver in a subprocess, `device_stand`,
`runtime_probe.py` (the registered probe, a subprocess), the story driver's build question, the person's word and its binding
(`stand_identity`), `manual_capture.py app` with the real `AppiumBackend` over a real TCP socket on loopback, `manual_evidence.py build`,
the evidence policy. Fake: the device tool (an `adb` that is a small program on the PATH of the test, reading a state file) and the Appium
server (`Server` below). EVERY command form, W3C path and answer here is the factory's own general knowledge, NOT read from a real tool or a
real device: a green run proves the wiring, never that a real device or driver answers this way (FR-33 stays open by name).

The two parameters of the road (P16). `shape` is `one_stand` (the device is the only stand) or `two_stands` (an API stand beside it; the story
stands on the API stand and the native profile on the device). `tests_in` is `python` or `kotlin`: the profile's command and its test file are
in that language, and the road gives the SAME answers (the language changes no answer here; what a language file's rows are is EP1-37's).
Every check below is named `[<shape>/<tests_in>]` so that a red line names the case that fell and the branch.

Mutations this file kills (each by this file alone): the `ui` evidence policy without an image (`policy ui: no image`), `build_check` asking
about `pipeline.environment` and not the stand of the profile (`two_stands ... the question is about the device stand`), a language word in
the `surfaces` table or key (`no language word`).
Run: python -B scripts/tests/test_mobile_road.py
"""
import base64
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import story_run_common as C  # noqa: E402
from harness import check, check_in, check_not_in, finish  # noqa: E402

check_eq = C.eq     # (name, got, expected, detail): the detail is printed when the line is red

MC = S.MC
import device_stand as DS  # noqa: E402
import execution_request as ER  # noqa: E402
import manual_evidence as M  # noqa: E402
import readiness as RD  # noqa: E402
import run_suite as RS  # noqa: E402
import stand_identity as SI  # noqa: E402
import surfaces as SF  # noqa: E402

CASE = S.CASES["ui"]
APP = "com.example.app"
SERIAL = "emulator-5554"
PNG = MC.PNG_SIGNATURE + b"fake-screen"
STEPS = ('launch\nclick "accessibility id=Login"\nsource home\ncapture pre_action initial\nlog tail\ncapture post_action completion\n')
LANGUAGE_WORDS = re.compile(r"python|pytest|kotlin|java|gradle|typescript|junit", re.I)
SHAPES = ("one_stand", "two_stands")
LANGUAGES = ("python", "kotlin")

# ---- the fake device tool: a program named `adb` on the PATH of this test --------------------------------------------------------

FAKE_ADB = r'''
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
state = json.loads((here / "state.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
with (here / "calls.log").open("a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\n")
out = []
if args[:1] == ["devices"]:
    out = ["List of devices attached"] + [f"{serial}\tdevice" for serial in state["devices"]] + [""]
else:
    if args[:1] == ["-s"]:
        args = args[2:]
    app = state["installs"].get(args[-1]) or state["installs"].get(args[-2] if len(args) > 1 else "")
    if args[:1] == ["logcat"]:
        out = ["I/App: started", "I/App: shown"]
    elif args[:3] == ["shell", "dumpsys", "package"]:
        out = [f"Unable to find package: {args[-1]}"] if app is None else [
            "Packages:", f"  Package [{args[-1]}]", f"    versionCode={app['code']} minSdk=24", f"    versionName={app['version']}"]
    elif args[:3] == ["shell", "pm", "path"]:
        out = [f"package:{path}" for path in (app or {}).get("paths", [])]
    elif args[:2] == ["shell", "sha256sum"]:
        out = [state["files"][args[-1]] + "  " + args[-1]]
print("\n".join(out))
'''


class FakeDevice:
    """The directory with the fake `adb`. `state` is what the device holds; `calls()` is every argv the tool was run with."""

    def __init__(self, root: Path):
        self.dir = root / "fakebin"
        self.dir.mkdir(parents=True)
        (self.dir / "fake_adb.py").write_text(FAKE_ADB, encoding="utf-8")
        launcher = f'@echo off\r\n"{sys.executable}" "{self.dir / "fake_adb.py"}" %*\r\nexit /b %ERRORLEVEL%\r\n' if os.name == "nt" else \
            f'#!/bin/sh\nexec "{sys.executable}" "{self.dir / "fake_adb.py"}" "$@"\n'
        path = self.dir / ("adb.cmd" if os.name == "nt" else "adb")
        path.write_bytes(launcher.encode("utf-8"))
        path.chmod(0o755)
        self.set(devices=[SERIAL])
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.dir) + os.pathsep + self.old_path

    def set(self, devices=None, version="1.2.3", code="42", sha="a" * 64, installed=True):
        state = {"devices": [SERIAL] if devices is None else devices,
                 "installs": {APP: {"version": version, "code": code, "paths": ["/data/app/base.apk"]}} if installed else {},
                 "files": {"/data/app/base.apk": sha}}
        (self.dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def calls(self) -> list:
        log = self.dir / "calls.log"
        return log.read_text(encoding="utf-8").splitlines() if log.is_file() else []

    def close(self) -> None:
        os.environ["PATH"] = self.old_path


# ---- the fake Appium server: W3C paths as the factory knows them (general knowledge), on a loopback socket --------------------------

class Server:
    def __init__(self):
        self.seen = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _go(self, method):
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"null") if size else None
                owner.seen.append((method, self.path))
                tail = self.path.split("/sid-1", 1)[1] if "/sid-1" in self.path else self.path
                value = None
                if (method, self.path) == ("GET", "/status"):
                    value = {"ready": True}
                elif (method, self.path) == ("POST", "/session"):
                    value = {"sessionId": "sid-1", "capabilities": {}}
                elif (method, tail) == ("POST", "/element"):
                    value = {MC.W3C_ELEMENT: "e1"} if (body or {}).get("value") == "Login" else None
                elif (method, tail) == ("GET", "/screenshot"):
                    value = base64.b64encode(PNG).decode("ascii")
                elif (method, tail) == ("GET", "/source"):
                    value = '<hierarchy><node text="Welcome" content-desc="home"/></hierarchy>'
                status = 404 if (method, tail) == ("POST", "/element") and value is None else 200
                data = json.dumps({"value": value if status == 200 else {"error": "no such element", "message": "x"}}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = lambda self: self._go("GET")        # noqa: E731
            do_POST = lambda self: self._go("POST")      # noqa: E731
            do_DELETE = lambda self: self._go("DELETE")  # noqa: E731

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.http.shutdown()
        self.http.server_close()


def alive_api():
    """An API stand that answers (the S0 check of the stand the story stands on in `two_stands`)."""
    class Alive(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Alive)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ---- the project of the road ---------------------------------------------------------------------------------------------------

def profiles(tests_in: str) -> list:
    one_test = ({"argv": ["./gradlew", "test", "--tests", "<t>"], "cwd": "."} if tests_in == "kotlin"
                else {"argv": ["python", "-m", "pytest", "<t>"], "cwd": "."})
    return [{"profile_id": "android", "capabilities": ["native"], "commands": {"one_test": one_test}},
            {"profile_id": "api", "capabilities": ["api"], "commands": {"one_test": {"argv": ["python", "-m", "pytest", "<t>"], "cwd": "."}}}]


def stands(shape: str, driver_url: str, api_url: str) -> list:
    device = {"name": "emulator", "surface": "android", "driver": {"url": driver_url}, "device": {"serial_key": "ANDROID_SERIAL"},
              "app": {"id": APP}}
    return [device] if shape == "one_stand" else [{"name": "localhost", "base_url": api_url}, device]


def test_file(root: Path, tests_in: str) -> None:
    """The project's own tests, in the language of the road. The factory reads neither on this road (EP1-37 reads them)."""
    path = (root / "app-src" / "src" / "test" / "kotlin" / "CartTest.kt") if tests_in == "kotlin" else (root / "tests" / "test_cart.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("class CartTest { fun addsToCart() {} }\n" if tests_in == "kotlin" else "def test_adds_to_cart():\n    pass\n",
                    encoding="utf-8")


def git_checkout(root: Path) -> None:
    folder = root / "app-src"
    folder.mkdir(exist_ok=True)

    def git(*args):
        subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=str(folder), capture_output=True,
                       check=True)
    git("init", "-q")
    git("commit", "--allow-empty", "-q", "-m", "one")
    git("commit", "--allow-empty", "-q", "-m", "two")


def road_config(shape: str, tests_in: str, driver_url: str, api_url: str) -> dict:
    cfg = S.config()
    cfg["profiles"] = profiles(tests_in)
    cfg["environments"] = stands(shape, driver_url, api_url)
    cfg["execution"] = {"runtime_probes": {"android": {
        "argv": ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--profile", "android", "--environment", "emulator",
                 "--checkout", "app-src"], "cwd": ".", "timeout_s": 60}}}
    cfg["implementation_repos"] = [{"repo_id": "app", "local_path": "app-src", "execution_profile_id": "android"}]
    return cfg


def make_road(shape: str, tests_in: str, server: Server, api_url: str):
    """(Task, env): the seeded project of the story driver with the evidence task of the manual scaffold laid over it."""
    root, task_root, env = C.seed(S.TICKET)
    cfg = road_config(shape, tests_in, server.url, api_url)
    scaf = S.make_task(cfg=cfg)
    try:
        shutil.copytree(scaf.task / "work", task_root / "work", dirs_exist_ok=True)
        (task_root / "state").mkdir(exist_ok=True)
        shutil.copytree(scaf.task / "state" / "case-versions", task_root / "state" / "case-versions", dirs_exist_ok=True)
        shutil.copyfile(scaf.task / "state" / "story-case-links.json", task_root / "state" / "story-case-links.json")
        shutil.copytree(scaf.project / "harness", root / "harness", dirs_exist_ok=True)
        plan_rows = scaf.plan_rows
    finally:
        S.cleanup(scaf)
    (root / "qa-factory" / "config.json").write_text(json.dumps(dict(cfg, handoffs={"required": False}), indent=2), encoding="utf-8")
    git_checkout(root)
    test_file(root, tests_in)
    t = S.Task(root, task_root, cfg, plan_rows)
    t.write_plan()
    t.state()
    return t, env


# ---- the pieces the road drives ------------------------------------------------------------------------------------------------

def quiet(call, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = call(*args, **kwargs)
    return result, out.getvalue()


def enter(t, env, words=None):
    """One entry into S6 (manual) by the driver in this process: (exit code, what it printed, started roles, the driver)."""
    state_path = t.task / "state" / "driver-state.json"
    if words is None and state_path.is_file():      # an entry with no answer is a new process with no question left open
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["asked"] = {}
        state.pop("build_question", None)
        state.pop("stand_question", None)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        (t.task / "state" / "driver-question.md").unlink(missing_ok=True)
    extra = {"answer": C.d2_answer(t.project, words)} if words is not None else {}
    driver, started, _steps, _probes = C.d2_driver(t.project, env, S.TICKET, s5=(), auto=(), manual=(CASE,), **extra)
    driver.s6_freshness = lambda cases: {"decided": False, "why": "stub", "stand": [], "run": {}, "passed": 0, "failed": 0}
    code, out = quiet(C.d2_enter, driver, "S6")
    return code, out, started, driver


def question(t) -> dict:
    return C.s0_state(t.task).get("build_question") or {}


def app(t, steps, *extra):
    path = t.task / "steps-app.txt"
    path.write_text(steps, encoding="utf-8")
    MC.BACKEND_FACTORY, MC.HTTP, MC.MONOTONIC, MC.SLEEP, MC.PROBE, MC.NOW = None, None, None, None, None, S.Clock()
    return S.run(["app", "--task-root", str(t.task), "--case", CASE, "--steps-file", str(path), *extra])


def build_pass(t, attempt: str, quote: str = ""):
    """`manual_evidence.py build --result pass`, the Thens seen on the picture after the action (or, with `quote`, quoted from the
    log the attempt kept): (exit code, stdout, stderr)."""
    with t.patched():
        if not (MC.case_root(t.task, CASE) / "request.json").exists():
            M.prepare_to_file(t.task, CASE, ["OB-7"])
        thens = json.loads((MC.case_root(t.task, CASE) / "request.json").read_text(encoding="utf-8")).get("thens") or {}
        flags = [x for n in sorted(thens, key=int) for x in (("--then-quote", f"{n}={quote}") if quote else
                                                             ("--then-seen", f"{n}=the screen after the action shows it"))]
        code, out, err = S.run(["build", "--task-root", str(t.task), "--case", CASE, "--attempt", attempt, "--result", "pass", "--actual", "x",
                                "--masked", *flags], main=M.main, command="manual_evidence.py build")
    return code, out, err


def lines(path):
    path = Path(path)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []


# ---- the road ------------------------------------------------------------------------------------------------------------------------

def s0_answers(shape: str, tests_in: str, device: FakeDevice, server: Server, pid: str) -> dict:
    """S0 as the driver runs it (a subprocess, `adb` on the PATH): the story's stand answers the check, no question is asked."""
    api, api_url = alive_api()
    cfg = {"profiles": profiles(tests_in), "environments": stands(shape, server.url, api_url)}
    if shape == "two_stands":
        cfg["environment"] = {"health_url": api_url + "/health"}
    root, task_root, env = C.s0_project("QA-1", config=cfg)
    try:
        flags = ("--env", "localhost") if shape == "two_stands" else ()
        done = C.s0_run(root, env, "QA-1", *flags)
        check_eq(f"{pid} S0 asks nothing and ends (exit 0)", done.returncode, 0, done.stdout[-1200:] + done.stderr[-400:])
        pipeline = C.s0_pipeline(task_root)
        story_stand = "localhost" if shape == "two_stands" else "emulator"
        check_eq(f"{pid} S0 confirmed the story's stand (environment_pending false)",
                 (pipeline["environment"], pipeline["environment_pending"]), (story_stand, False))
        check(f"{pid} S0 opened no question and raised no stand warning",
              not C.s0_state(task_root).get("s0_block") and not (task_root / "state" / "driver-question.md").exists()
              and not [w for w in pipeline["warnings"] if w.startswith("stand ")], str(pipeline["warnings"]))
        check_eq(f"{pid} S0 asked no conductor", C.stub_calls(root), [])
        ready = json.loads((task_root / "state" / "readiness.json").read_text(encoding="utf-8")) if (task_root / "state" / "readiness.json").is_file() \
            else json.loads((root / "qa-factory" / "state" / "readiness.json").read_text(encoding="utf-8"))
        return {"pending": pipeline["environment_pending"], "stand": pipeline["environment"], "surfaces": ready.get("surfaces")}
    finally:
        api.shutdown()
        C.harness.cleanup(root)


def readiness_answers(t, device: FakeDevice, pid: str) -> dict:
    data = RD.compute(t.cfg, t.project)
    cap = data["capabilities"]["environment"]
    check_eq(f"{pid} readiness: the device stand answers (environment ok, owner factory)", (cap["status"], cap["owner"]), ("ok", "factory"))
    check_in(f"{pid} readiness: ...and the note names the device it saw", SERIAL, cap["note"])
    shown = json.dumps(data.get("surfaces"), sort_keys=True)
    check(f"{pid} no language word in `surfaces` (the key and the table row)",
          not LANGUAGE_WORDS.search(shown) and not LANGUAGE_WORDS.search(json.dumps(SF.row_of(t.cfg["environments"][-1]), sort_keys=True)), shown)
    return {"environment": [cap["status"], cap["owner"]], "surfaces": data.get("surfaces")}


def use_plan(rows: dict) -> None:
    """The plan's rows as `gate_preflight.plan_rows_of` reads them: {case: (profile, disposition)}; the real keying of a row runs."""
    import gate_preflight

    def rows_of(task_root, dispositions):
        return [(case, {"execution_profile_id": profile, "disposition": disposition})
                for case, (profile, disposition) in rows.items() if disposition in dispositions]
    gate_preflight.plan_rows_of = rows_of


def shown(text: str) -> str:
    """A text without what differs between two projects of one road: commit ids and the answer block."""
    return re.sub(r"asked_at: \S+", "asked_at: <time>", re.sub(r"\b[0-9a-f]{7,40}\b", "<id>", text.split("\n---\nAnswer:")[0]))


def confirmations(t) -> list:
    return lines(t.task / "state" / "stand-confirmations.jsonl")


def road(shape: str, tests_in: str) -> dict:
    pid = f"[{shape}/{tests_in}]"
    server, (api, api_url) = Server(), alive_api()
    device = FakeDevice(Path(tempfile.mkdtemp(prefix="qa-mobile-road-bin-")))
    t, answers = None, {}
    try:
        answers["s0"] = s0_answers(shape, tests_in, device, server, pid)
        t, env = make_road(shape, tests_in, server, api_url)
        story_stand = "localhost" if shape == "two_stands" else "emulator"
        C.d2_pipeline(t.task, environment=story_stand, environment_pending=False)
        use_plan({CASE: ("android", "manual-agent")})
        answers["readiness"] = readiness_answers(t, device, pid)

        # the build question: about the stand of the PROFILE (the device), never the story's stand
        code, out, started, _driver = enter(t, env)
        bq = question(t)
        check_eq(f"{pid} S6 asks the build question and starts no role", (code, started), (3, []))
        check_eq(f"{pid} the question is about the device stand, for the native profile (not `pipeline.environment`)",
                 (bq.get("variant"), bq.get("environment"), bq.get("profile")), ("device_build", "emulator", "android"))
        text = (t.task / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_in(f"{pid} the question says what the device holds, the file hashed", f"The device has {APP} 1.2.3 (42) sha256:", text)
        check_eq(f"{pid} the question obeys human-questions.md", C.human_broken(text.split("\n---\nAnswer:")[0]), [])
        answers["question"] = [code, bq.get("variant"), shown(text)]
        code, out, err = app(t, STEPS)
        row = json.loads(next((t.task / "work" / "evidence" / "manual").rglob("env_blocked.json")).read_text(encoding="utf-8"))
        check_eq(f"{pid} no word yet: the capture is refused (exit 3), the stand's build, do not retry",
                 (code, row.get("cause"), row.get("do_not_retry")), (3, "build", True), err[-300:])

        # the person's word binds to (device stand, profile) and the app sees it
        code, out, started, _driver = enter(t, env, "deployed")
        rows = confirmations(t)
        check_eq(f"{pid} `deployed`: the story goes on, ONE word on the key (device stand, profile)",
                 (code, ("S6", "manual") in started, [(r["environment_id"], r["profile_id"], r["kind"]) for r in rows]),
                 (0, True, [("emulator", "android", "deployed")]), out[-400:])
        check(f"{pid} `deployed`: the word is bound to the build the probe read (an image digest, not `absent`)",
              bool(rows) and str(rows[0]["image"]).startswith("image:sha256:"), str(rows))
        code, out, err = app(t, STEPS)
        summary = json.loads(out) if out.strip().startswith("{") else {}
        attempt = summary.get("attempt", "")
        check_eq(f"{pid} app: exit 0 and every step ok", (code, [s["outcome"] for s in summary.get("steps", [])]), (0, ["ok"] * 6), err[-300:])
        folder = t.attempt_dir(CASE, attempt)
        check_eq(f"{pid} app: the stand was read as the person's word, for the native profile, at the start and at the end",
                 [(p["profile"], p["probe"]["result"]) for p in lines(folder / "probes.jsonl")],
                 [("android", "person_confirmed")] * 2)
        kinds = sorted({c["kind"] for c in lines(folder / "captures.jsonl")})
        check_eq(f"{pid} app: a picture, a state and a log are kept", kinds, ["image", "log", "state"])

        # the policy `ui` passes with a picture before and after, and does not without one
        code, out, err = build_pass(t, attempt)
        check_eq(f"{pid} policy ui: `manual_evidence build` passes on an attempt with a picture before and after", code, 0, out[-300:] + err[:900])
        code, out, err = app(t, STEPS)
        control = json.loads(out).get("attempt", "") if out.strip().startswith("{") else ""
        code, out, err = build_pass(t, control, quote="I/App: started")
        check_eq(f"{pid} policy ui: control: the same quote on an attempt that kept its pictures passes", code, 0, err[:600])
        code, out, err = app(t, STEPS)
        bare = json.loads(out).get("attempt", "") if out.strip().startswith("{") else ""
        sheet = t.attempt_dir(CASE, bare) / "captures.jsonl"
        sheet.write_text("".join(json.dumps(dict(c, kind="other") if c["kind"] == "image" else c) + "\n" for c in lines(sheet)), encoding="utf-8")
        code, out, err = build_pass(t, bare, quote="I/App: started")
        check(f"{pid} policy ui: no image, no pass (the same attempt, its pictures no longer pictures, quoted from its log, is refused)",
              code != 0 and "visual or trace evidence before and after" in err, f"{code} {err[:600]}")
        answers["app"] = [summary.get("failed"), kinds]

        # a reinstall with the SAME version voids the word: the question comes back and says so
        device.set(sha="b" * 64)
        code, out, started, _driver = enter(t, env)
        again = question(t)
        text = (t.task / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_eq(f"{pid} reinstall (same version): the word no longer holds, the question is asked again (exit 3, no role)",
                 (code, again.get("variant"), started), (3, "device_build", []))
        check_in(f"{pid} reinstall: ...and it says the earlier word was voided", "since then", text)
        check_in(f"{pid} reinstall: ...and why", SI.data()["voided"]["image"], text)
        code, out, err = app(t, STEPS)
        check_eq(f"{pid} reinstall: the capture is refused again until the person speaks (exit 3)", code, 3, err[-300:])
        answers["reinstall"] = [code, again.get("variant"), shown(text)]

        # no device: a named gap, a line and a refused capture; nobody is asked
        device.set(devices=[])
        code, out, started, driver = enter(t, env)
        check(f"{pid} no device: the check says so in a line and asks NOBODY (no question, no flag)",
              "no device is connected" in out and not question(t) and not (t.task / "state" / "driver-question.md").exists(), out[-400:])
        check_eq(f"{pid} no device: the stage is not stopped by a question (exit 0)", code, 0)
        code, out, err = app(t, STEPS)
        check_eq(f"{pid} no device: the capture is refused (exit 3) and names the device", (code, "no device is connected" in err), (3, True), err[-300:])
        newest = max((t.task / "work" / "evidence" / "manual").rglob("env_blocked.json"), key=lambda p: p.stat().st_mtime_ns)
        blocked_row = json.loads(newest.read_text(encoding="utf-8"))
        check_eq(f"{pid} no device (F-2): the door is the device's - cause `device`, do not retry, the halt sentence, never `capture again`",
                 (blocked_row.get("cause"), blocked_row.get("do_not_retry"), "the device stand is not ready" in err, "capture again" in err),
                 ("device", True, True, False), err[-400:])
        cap = RD.compute(t.cfg, t.project)["capabilities"]["environment"]
        check_eq(f"{pid} no device: readiness says `missing`, the user's to fix", (cap["status"], cap["owner"]), ("missing", "user"))
        spec = ER.registered_probe(t.cfg, "android")
        spec["cwd"] = str(t.project / spec["cwd"])
        try:
            RS.probe_runtime(spec)
            refused = ""
        except RS.ProvenanceRefused as exc:
            refused = str(exc)
        check(f"{pid} no device: `probe_runtime` refuses before any test runs, and names the device", "no device is connected" in refused, refused[-300:])
        answers["no_device"] = [code, cap["status"], bool(refused)]
        return answers
    finally:
        device.close()
        server.stop()
        api.shutdown()
        if t is not None:
            S.cleanup(t)


def ios_off_darwin() -> None:
    """An iOS stand on a host that is not macOS: the row says `host_os`, the user's to fix, and `xcrun` is never asked."""
    saved, DS.PLATFORM = DS.PLATFORM, "linux"
    root = Path(tempfile.mkdtemp(prefix="qa-mobile-road-ios-"))
    device = FakeDevice(root)
    try:
        cfg = {"profiles": profiles("kotlin"), "environments": [{"name": "tablet", "surface": "ios", "driver": {"url": "http://127.0.0.1:9"},
                                                                  "app": {"id": APP}}]}
        result = DS.probe(cfg, "tablet")
        first = result["checks"][0]
        check_eq("[ios/linux] the device check is `host_os`, owner user, cause device",
                 (first["state"], first["owner"], (result["block"] or {}).get("cause")), ("host_os", "user", "device"))
        check_in("[ios/linux] it says what host is needed", "darwin", first["line"])
        cap = RD.check_environment(cfg, root)
        check_eq("[ios/linux] readiness: `missing`, never `ok`", cap["status"], "missing")
        check_not_in("[ios/linux] the tool of the row was not run", "simctl", " ".join(device.calls()))
    finally:
        DS.PLATFORM = saved
        device.close()
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    table = (Path(SF.__file__).resolve().parent.parent / "references" / "surfaces.json").read_text(encoding="utf-8")
    check("no language word in the surfaces table", not LANGUAGE_WORDS.search(table), str(LANGUAGE_WORDS.search(table)))
    results = {shape: {language: road(shape, language) for language in LANGUAGES} for shape in SHAPES}
    for shape in SHAPES:
        python, kotlin = results[shape]["python"], results[shape]["kotlin"]
        for key in python:
            check_eq(f"[{shape}/python=kotlin] the language changes no answer of `{key}`", kotlin.get(key), python[key])
    ios_off_darwin()
    finish("test_mobile_road")


if __name__ == "__main__":
    main()


