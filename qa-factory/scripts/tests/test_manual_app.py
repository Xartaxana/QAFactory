#!/usr/bin/env python3
"""EP1-41d: `manual_capture.py app` - the hands on a device stand, and `AppiumBackend` under it.

WHAT IS REAL and what is a fake. Real: the factory's own code (the steps parser, the step loop, the secret scan, the hashes, the
attempt files, `device_stand`, `http_client.fetch`, a real TCP socket on loopback). Fake: the driver server (`Driver` below, a small
HTTP server that answers the W3C paths the backend asks), the device tool (`device_stand.RUN_TOOL`) and the build probe. EVERY W3C path,
body and answer in this file is the factory's own general knowledge of the protocol, NOT read from a real driver: a green run here
proves the wiring, never a real server or a real device (t-544 section 4, FR-33). Nothing here starts a process or reaches a network
beyond 127.0.0.1.
"""
import base64
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

MC = S.MC
import device_stand as DS  # noqa: E402
import surfaces as SF  # noqa: E402

CASE = S.CASES["ui"]
PNG = MC.PNG_SIGNATURE + b"fake-screen"
DEVICES = b"List of devices attached\nemulator-5554\tdevice\n"


class Driver:
    """A fake W3C driver server on loopback. `elements` maps (strategy, value) to a reference; `fail[(METHOD, tail)] = (status, body)`
    answers that request with it instead; `raw[(METHOD, tail)] = bytes` answers with those exact bytes. `seen` lists (METHOD, path, body)."""

    def __init__(self):
        self.ready, self.seen, self.fail, self.raw = True, [], {}, {}
        self.elements = {("accessibility id", "Login"): "e1", ("id", "user"): "e2", ("xpath", "//a[@x='y']"): "e3"}
        self.texts, self.attrs, self.source = {}, {}, '<hierarchy><node text="Welcome" content-desc="home"/></hierarchy>'
        driver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _go(self, method):
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"null") if size else None
                status, payload = driver.handle(method, self.path, body)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = lambda self: self._go("GET")        # noqa: E731
            do_POST = lambda self: self._go("POST")      # noqa: E731
            do_DELETE = lambda self: self._go("DELETE")  # noqa: E731

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def handle(self, method, path, body):
        self.seen.append((method, path, body))
        tail = path.split("/sid-1", 1)[1] if "/sid-1" in path else ("" if path == "/session" else path)
        key = (method, tail if path != "/status" else "/status")
        if key in self.raw:
            return 200, self.raw[key]
        if key in self.fail:
            return self.fail[key]
        if path == "/status":
            return 200, {"value": {"ready": self.ready}}
        if (method, path) == ("POST", "/session"):
            return 200, {"value": {"sessionId": "sid-1", "capabilities": {}}}
        if tail == "" and method == "DELETE":
            return 200, {"value": None}
        if (method, tail) == ("POST", "/element"):
            ref = self.elements.get((body["using"], body["value"]))
            if ref is None:
                return 404, {"value": {"error": "no such element", "message": "An element could not be located", "stacktrace": ""}}
            return 200, {"value": {MC.W3C_ELEMENT: ref}}
        if method == "GET" and tail.endswith("/text"):
            return 200, {"value": self.texts.get(tail.split("/")[2], "hello")}
        if method == "GET" and "/attribute/" in tail:
            return 200, {"value": self.attrs.get(tail.rsplit("/", 1)[1])}
        if method == "GET" and tail.endswith("/rect"):
            return 200, {"value": {"x": 10, "y": 20, "width": 100, "height": 40}}
        if (method, tail) == ("GET", "/screenshot"):
            return 200, {"value": base64.b64encode(PNG).decode("ascii")}
        if (method, tail) == ("GET", "/source"):
            return 200, {"value": self.source}
        return 200, {"value": None}

    def paths(self):
        return [(m, p.split("/sid-1", 1)[1] if "/sid-1" in p else p) for m, p, _ in self.seen]


def adb(argv, timeout):
    return 0, (DEVICES if "devices" in argv else b"I/App: started\nI/App: shown\n")


def config(url, **env):
    cfg = S.config()
    cfg["profiles"] = [
        {"profile_id": "e2e-ui", "capabilities": ["web"], "commands": {"one_test": {"argv": ["poetry", "run", "pytest", "<t>"], "cwd": "."}}},
        {"profile_id": "android", "capabilities": ["native"], "commands": {"one_test": {"argv": ["./gradlew", "test"], "cwd": "."}}}]
    cfg["execution"]["runtime_probes"]["android"] = {"argv": ["probe-android"], "cwd": ".", "timeout_s": 5}
    cfg["environments"] = [*cfg["environments"], {"name": "emulator", "surface": "android", "driver": {"url": url},
                                                  "app": {"id": "com.example.app"}, **env}]
    return cfg


def setup(driver=None, cfg=None, tool=adb):
    driver = driver or Driver()
    t = S.make_task(cfg=cfg or config(driver.url))
    MC.BACKEND_FACTORY, MC.HTTP, MC.MONOTONIC, MC.SLEEP = None, None, None, None
    MC.PROBE = lambda spec: S.probe("android")
    MC.NOW = S.Clock()
    DS.RUN_TOOL, DS.WHICH, DS.HTTP, DS.PLATFORM = tool, (lambda name: name), None, None
    return t, driver


def app(t, steps, *extra, case=CASE):
    path = t.task / "steps-app.txt"
    path.write_text(steps, encoding="utf-8")
    return S.run(["app", "--task-root", str(t.task), "--case", case, "--steps-file", str(path), *extra])


def lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(path).is_file() else []


class FakeApp:
    """A scripted backend for the step loop (the sign-in window); a click of `id=submit` ends the sign-in screen."""

    def __init__(self, signing=True):
        self.signing, self.calls = signing, []

    def open(self, timeout_s, hosts, local_storage=None, element_wait_s=None):
        self.calls.append(("open",))

    def close(self):
        self.calls.append(("close",))

    def click(self, sel):
        self.calls.append(("click", sel))
        if sel == "id=boom":
            raise MC.StepFailed("no element matched id=boom", by="the driver")
        self.signing = self.signing and sel != "id=submit"
        return 0.1

    def fill(self, sel, text):
        self.calls.append(("fill", sel, text))
        return 0.1

    def screenshot(self, path):
        Path(path).write_bytes(PNG)
        return 0.1

    def source(self):
        self.calls.append(("source",))
        return "<hierarchy/>", 0.1

    def page_words(self, mode=None):
        return "Sign in" if self.signing else "Home"

    def current_url(self):
        return "app://sign-in" if self.signing else "app://screen"

    def drain_failures(self):
        return {}


# ---- the whole road over the fake driver ---------------------------------------------------------------------------------
t, drv = setup()
try:
    steps = ('launch\nclick "accessibility id=Login"\nfill id=user hello\nread id=user text\nread id=user attr=password\n'
             "back\nsource home\nlog tail\ncapture pre_action start\nwait 10\ndrag id=user 5 -7\ncapture post_action done\n")
    drv.attrs = {}
    code, out, err = app(t, steps)
    folder = t.attempt_dir(CASE)
    summary = json.loads(out) if out.strip() else {}
    check_eq("road: exit 0 and every step ok", (code, [s["outcome"] for s in summary.get("steps", [])]), (0, ["ok"] * 12))
    captures = lines(folder / "captures.jsonl")
    kinds = sorted({(c["kind"], Path(c["path"]).suffix) for c in captures})
    check_eq("road: a picture, a state (xml) and logs are registered", kinds, [("image", ".png"), ("log", ".log"), ("log", ".txt"), ("state", ".xml")])
    check("road: every stored file says the network of the device is not confined (not promised, FR-41)",
          all("not confined to the stand" in c.get("limitation", "") for c in captures), str(captures))
    check("road: a screenshot file is a PNG and its hash is over the stored bytes",
          all((t.task / c["path"]).read_bytes().startswith(MC.PNG_SIGNATURE) and S.sha(t.task / c["path"]) == c["content_hash"]
              for c in captures if c["kind"] == "image"))
    check_eq("road: the step lines carry the command `app`", {s["command"] for s in lines(folder / "steps.jsonl")}, {"app"})
    check_eq("road: the probe is of the native profile", {p["profile"] for p in lines(folder / "probes.jsonl")}, {"android"})
    session = next(b for m, p, b in drv.seen if (m, p) == ("POST", "/session"))["capabilities"]["alwaysMatch"]
    check_eq("road: the session names the app, the device and the table's defaults",
             (session["appium:appPackage"], session["appium:udid"], session["appium:noReset"]), ("com.example.app", "emulator-5554", True))
    check_eq("road: the session is deleted at the end", drv.paths()[-1], ("DELETE", ""))
    sent = [b for m, p, b in drv.seen if (m, p.split("/sid-1")[-1]) == ("POST", "/element")]
    check("road: a strategy with a space reaches the driver as written", {"using": "accessibility id", "value": "Login"} in sent, str(sent))
    app(t, "click \"xpath=//a[@x='y']\"\n")
    check_eq("selector: cut at the FIRST `=`, the value keeps its own", [b for m, p, b in drv.seen if (m, p.split("/sid-1")[-1]) == ("POST", "/element")][-1],
             {"using": "xpath", "value": "//a[@x='y']"})
    check_in("road: the log is the row's tool, run for the picked device", "I/App: started", (t.task / next(
        c["path"] for c in captures if c["path"].endswith(".log"))).read_text(encoding="utf-8"))
    check_eq("road: the xml source is stored whole and cited from a .xml", (t.task / next(c["path"] for c in captures if c["path"].endswith(".xml"))).read_text(
        encoding="utf-8"), drv.source)
    check("road: `launch` asks the driver to bring the app to the front", ("POST", "/appium/device/activate_app") in drv.paths())
    launched = [b for m, p, b in drv.seen if p.endswith("/appium/device/activate_app")]
    check_eq("road (F-1): the body of `launch` carries ONE app id key, the row's (Appium 2 refuses `appId` and `bundleId` together)",
             launched[0], {"appId": "com.example.app"})
    check_eq("road (F-1): the iOS row names `bundleId`, the Android row `appId`: data of the row, not of the code",
             (SF.rows()["surfaces"]["android"]["session"]["app_id_param"], SF.rows()["surfaces"]["ios"]["session"]["app_id_param"]), ("appId", "bundleId"))
    check("road (F-10): no activity is named, so none is asked for", "appium:appActivity" not in session)
    order = [p for _, p in drv.paths()]
    check("road: the step order in the driver is the file's (fill, then back)", order.index("/back") > next(
        i for i, p in enumerate(order) if p.endswith("/value")), str(order))
    # an absent attribute is the marker, an empty one is empty
    drv.attrs = {"empty": ""}
    code, out, err = app(t, "read id=user attr=gone\nread id=user attr=empty\n")
    reads = [(c["path"], (t.task / c["path"]).read_text(encoding="utf-8")) for c in lines(t.attempt_dir(CASE, "a3") / "captures.jsonl")]
    check_eq("read: absent reads as the data's marker, empty as empty", [v for _, v in reads], ["<absent>", ""])
    # the backend's own url word
    stand, row = SF.stand_for(t.cfg), SF.row_of(SF.stand_for(t.cfg))
    be = MC.AppiumBackend(stand, row, sign_in="id=user")
    be.open(30, (), None, 3)
    check_eq("sign-in window: `app://sign-in` while the recorded selector is found", be.current_url(), "app://sign-in")
    be.sign_in = "id=nothere"
    check_eq("sign-in window: `app://screen` once it is gone", be.current_url(), "app://screen")
    be.sign_in = ""
    check_eq("sign-in window: no recipe, never the sign-in word", be.current_url(), "app://screen")
    drv.fail[("POST", "/element")] = (200, {"value": {"error": "unknown error", "message": "x"}})
    be.sign_in = "id=user"
    check_eq("sign-in window: a driver that errors leaves the window open (empty word, less screen)", be.current_url(), "")
    be.close()
    check_eq("close: the session is deleted once and a second close sends nothing", [p for p in drv.paths()].count(("DELETE", "")), 4)
    be.close()
finally:
    drv.stop()
    S.cleanup(t)

# ---- the refusals before any attempt (exit 2) ------------------------------------------------------------------------------
t, drv = setup()
try:
    before = lambda: sorted(p.name for p in (t.task / "work" / "evidence" / "manual").glob("*")) if (t.task / "work" / "evidence").exists() else []  # noqa: E731
    cases = {
        "a web step": ("goto http://localhost:5173\nlaunch\n", "there is no such step on this surface"),
        "type": ("type id=user abc\n", "there is no such step on this surface"),
        "fail_request": ("fail_request **/x 500\n", "there is no such step on this surface"),
        "a css selector": ("click button.primary\n", "strategy of: accessibility id, id, xpath, -android uiautomator"),
        "an empty value": ("click id=\n", "a value and a strategy"),
        "style read": ("read id=user style=color\n", "no such read on this surface"),
        "a text without a word": ("\n# only a comment\n", "holds no steps"),
        "fill-account words": ("fill-account id=user default who\n", "`user` (the account's name) or `secret`"),
    }
    for label, (steps, said) in cases.items():
        code, out, err = app(t, steps)
        check(f"refusal: {label} is exit 2 and says {said!r}", code == 2 and said in err, f"{code} {err[:300]}")
    check_eq("refusal: none of them opened an attempt or a session", (before(), drv.paths()), ([], []))
    code, out, err = app(t, "launch\n", "--as", "default")
    check("refusal: `--as` names the door (`fill-account`)", code == 2 and "fill-account" in err and "no sign-in by code" in err, err[:300])
    code, out, err = app(t, "fill id=user \"password = 'abcdefghijklmnop1234'\"\n")
    check("refusal: a secret in the steps file is refused by index", code == 2 and "secret_content_patterns[1]" in err and "abcdefgh" not in err, err[:300])
    check_eq("refusal: still nothing opened", (before(), drv.paths()), ([], []))
    # the browser's file without `goto` stays refused
    ui = t.task / "ui.txt"
    ui.write_text("click button\n", encoding="utf-8")
    MC.BACKEND_FACTORY = lambda: S.FakeBrowser()
    code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", CASE, "--steps-file", str(ui)])
    check("`ui` without goto stays refused", code == 2 and "needs a `goto <url>` step" in err, err[:300])
    # no device stand / two stands / an empty app id
    for label, cfg in {
            "no stand": {**config(drv.url), "environments": [config(drv.url)["environments"][0]]},
            "empty app id": config(drv.url, app={"id": " "}),
    }.items():
        t2, _ = setup(drv, cfg)
        code, out, err = app(t2, "launch\n")
        check(f"refusal: {label} is exit 2 with a door", code == 2 and ("onboarding" in err or "app.id" in err), err[:300])
        S.cleanup(t2)
    two = config(drv.url)
    two["environments"].append({**two["environments"][-1], "name": "other", "surface": "ios"})
    t2, _ = setup(drv, two)
    code, out, err = app(t2, "launch\n")
    check("two driver stands without --surface: exit 2 and the list, the surface is never guessed",
          code == 2 and "several device stands fit (emulator, other)" in err and drv.paths() == [], err[:300])
    code, out, err = app(t2, "launch\n", "--surface", "android")
    check_eq("two driver stands with --surface: the named one runs", code, 0)
    S.cleanup(t2)
finally:
    drv.stop()
    S.cleanup(t)

# ---- the project's profile for an `app` capture ------------------------------------------------------------------------------
cfg = config("http://127.0.0.1:1")
check_eq("mixed project: `app` is the native profile", MC.capture_profile(cfg, "/x", CASE, "app"), "android")
check_eq("mixed project: `ui` is the web profile", MC.capture_profile(cfg, "/x", CASE, "ui"), "e2e-ui")
check_eq("mixed project: --profile still wins", MC.capture_profile(cfg, "/x", CASE, "app", "e2e-ui"), "e2e-ui")

# ---- a device that is not ready: exit 3, a record of why, no session, not told as a login ---------------------------------------
def blocked(label, prepare, said, owner="user", tool=adb):
    t, drv = setup(tool=tool)
    try:
        prepare(drv)
        code, out, err = app(t, "launch\ncapture pre_action a\n")
        row = json.loads((t.attempt_dir(CASE) / "env_blocked.json").read_text(encoding="utf-8"))
        check(f"blocked ({label}): exit 3, cause device, do_not_retry, owner {owner}",
              code == 3 and row.get("cause") == "device" and row.get("do_not_retry") is True and row["owner"] == owner, f"{code} {row}")
        check_in(f"blocked ({label}): the line says why", said, row["probe_line"])
        check(f"blocked ({label}): the sentence is the device's, never a login", "device stand is not ready" in err
              and "login by code" not in err and "test account" not in err, err[:300])
        check_eq(f"blocked ({label}): no capture was written", lines(t.attempt_dir(CASE) / "captures.jsonl"), [])
        check(f"blocked ({label}): no session was deleted that was never made", ("DELETE", "") not in drv.paths())
        return t, drv, err
    finally:
        drv.stop()
        S.cleanup(t)


blocked("no device", lambda d: None, "no device is connected", tool=lambda argv, to: (0, b"List of devices attached\n"))
blocked("only an offline one", lambda d: None, "emulator-5554 is offline",
        tool=lambda argv, to: (0, b"List of devices attached\nemulator-5554\toffline\n"))
blocked("empty output is the factory's", lambda d: None, "printed nothing", owner="factory", tool=lambda argv, to: (0, b""))
blocked("two devices and none named", lambda d: None, "none is named by",
        tool=lambda argv, to: (0, b"List of devices attached\na1\tdevice\nb2\tdevice\n"))
blocked("server not ready", lambda d: setattr(d, "ready", False), "not ready")
blocked("the session does not start", lambda d: d.fail.__setitem__(("POST", ""), (500, {"value": {"error": "session not created",
                                                                                        "message": "no such device"}})), "session did not start")
t, drv = setup()
try:
    row_t = t.attempt_dir(CASE, "a1")
    row_t.mkdir(parents=True)
    (row_t / "env_blocked.json").write_text(json.dumps({"id": CASE, "probe_line": "x", "remedy": "y", "owner": "user", "do_not_retry": True,
                                                        "cause": "device"}), encoding="utf-8")
    code, out, err = app(t, "launch\n", "--attempt", "a1")
    check("--attempt on a device-blocked attempt: the device words, not the login's",
          code == 2 and "device stand is not ready" in err and "test account" not in err, err[:400])
finally:
    drv.stop()
    S.cleanup(t)

# ---- a step that fails: the driver's words last, the session still deleted -------------------------------------------------------
t, drv = setup()
try:
    drv.fail[("POST", "/element/e2/click")] = (400, {"value": {"error": "element not interactable", "message": "covered by a dialog"}})
    code, out, err = app(t, "click id=user\ncapture pre_action never\n")
    summary = json.loads(out)
    check_eq("failed step: exit 1, the run stops there", (code, [s["outcome"] for s in summary["steps"]]), (1, ["failed"]))
    check("failed step: the driver's own words are last, the surface is not called a browser",
          summary["failed"]["detail"].endswith("the driver said: covered by a dialog") and "Playwright" not in summary["failed"]["detail"],
          summary["failed"]["detail"])
    check_eq("failed step: its screenshot is the evidence and it is a PNG",
             [Path(c["path"]).suffix for c in lines(t.attempt_dir(CASE) / "captures.jsonl")], [".png"])
    check_eq("failed step: the session is deleted", drv.paths()[-1], ("DELETE", ""))
finally:
    drv.stop()
    S.cleanup(t)

t, drv = setup()
try:
    drv.fail[("POST", "/element/e2/click")] = (404, {"value": {"error": "invalid session id", "message": "gone"}})
    code, out, err = app(t, "click id=user\n")
    detail = json.loads(out)["failed"]["detail"]
    check("session gone: a failed step that says the session is gone and to capture again", code == 1 and "session is gone" in detail
          and "new attempt" in detail, detail)
finally:
    drv.stop()
    S.cleanup(t)

# an element that never comes: polled to the element wait (a fake clock), then the server's words last
t, drv = setup(cfg=None)
try:
    clock = {"now": 0.0}
    MC.MONOTONIC = lambda: clock["now"]
    MC.SLEEP = lambda s: clock.__setitem__("now", clock["now"] + s)
    cfg2 = config(drv.url)
    cfg2["manual_capture"] = {"element_wait_s": 2}
    (t.project / "qa-factory" / "config.json").write_text(json.dumps(cfg2), encoding="utf-8")
    code, out, err = app(t, "click id=nothere\n")
    detail = json.loads(out)["failed"]["detail"]
    polls = [1 for m, p in drv.paths() if (m, p) == ("POST", "/element")]
    check("missing element: failed after the element wait, the server's words last", code == 1 and detail.startswith(
        "no element matched id=nothere within 2 s") and detail.endswith("the driver said: An element could not be located"), detail)
    check_eq("missing element: it was looked for every half second (5 tries in 2 s)", len(polls), 5)
finally:
    MC.MONOTONIC = MC.SLEEP = None
    drv.stop()
    S.cleanup(t)

# ---- the snapshot limit, AT and BEYOND, over a real socket and the real http_client ---------------------------------------------
data = json.loads(SF.TABLE_PATH.read_text(encoding="utf-8"))
check("data: the snapshot limit is larger than the stored body cap, so a stored file is cut by BODY_CAP, not by the wire",
      data["drivers"]["appium"]["snapshot_max_body"] > MC.BODY_CAP)
for label, delta, ok in (("AT the limit", 0, True), ("BEYOND the limit (+1 byte)", 1, False)):
    t, drv = setup()
    small = Path(tempfile.mkdtemp(prefix="qa-surfaces-")) / "surfaces.json"
    try:
        envelope = len(json.dumps({"value": ""}).encode("utf-8"))
        limit = 300
        drv.raw[("GET", "/source")] = json.dumps({"value": "x" * (limit - envelope + delta)}).encode("utf-8")
        data["drivers"]["appium"]["snapshot_max_body"] = limit
        small.write_text(json.dumps(data), encoding="utf-8")
        held = SF.TABLE_PATH
        SF.TABLE_PATH = small
        try:
            code, out, err = app(t, "source big\ncapture pre_action after\n")
        finally:
            SF.TABLE_PATH = held
        summary = json.loads(out)
        files = lines(t.attempt_dir(CASE) / "captures.jsonl")
        if ok:
            check_eq(f"snapshot {label}: the source is stored whole", (code, [Path(c["path"]).suffix for c in files]), (0, [".xml", ".png"]))
        else:
            check(f"snapshot {label}: a failed step that names the limit, and no file is kept",
                  code == 1 and f"larger than the limit {limit}; nothing was kept" in summary["failed"]["detail"]
                  and [Path(c["path"]).suffix for c in files] == [".png"], f"{code} {summary['failed']}")
    finally:
        drv.stop()
        S.cleanup(t)

# a screenshot that is not a picture is never registered
for label, value in (("not base64", "!!not base64!!"), ("base64 of something that is no PNG", base64.b64encode(b"hello").decode("ascii")),
                     ("empty", "")):
    t, drv = setup()
    try:
        drv.raw[("GET", "/screenshot")] = json.dumps({"value": value}).encode("utf-8")
        code, out, err = app(t, "capture pre_action a\n")
        check(f"screenshot {label}: the step fails and no empty or false image is registered",
              code == 1 and "not a base64 PNG" in json.loads(out)["failed"]["detail"]
              and lines(t.attempt_dir(CASE) / "captures.jsonl") == [] and not list(t.attempt_dir(CASE).glob("*.png")), out[:300])
    finally:
        drv.stop()
        S.cleanup(t)

# answers that are not W3C: no `value`, an empty session id, HTML
t, drv = setup()
try:
    drv.raw[("GET", "/source")] = b'{"nothing": 1}'
    code, out, err = app(t, "source a\n")
    check("an answer without `value` is a failed step", code == 1 and "not a W3C answer" in json.loads(out)["failed"]["detail"], out[:200])
finally:
    drv.stop()
    S.cleanup(t)
t, drv = setup()
try:
    drv.fail[("POST", "")] = (200, {"value": {"sessionId": "", "capabilities": {}}})
    code, out, err = app(t, "launch\n")
    check("an empty session id is a session that did not start (exit 3)", code == 3 and "session did not start" in err + out, err[:200])
finally:
    drv.stop()
    S.cleanup(t)

# a session that cannot be deleted stays said
t, drv = setup()
try:
    drv.fail[("DELETE", "")] = (500, {"value": {"error": "unknown error", "message": "busy"}})
    code, out, err = app(t, "launch\n")
    check("a session left behind is a limitation of the attempt", code == 0 and any("could not be deleted" in x for x in json.loads(out)["limitations"]), out[:300])
finally:
    drv.stop()
    S.cleanup(t)

# ---- secrets on the screen -----------------------------------------------------------------------------------------------------
drv = Driver()
signing = config(drv.url)
signing["manual_capture"] = {"login": {"app": {"sign_in_selector": "id=signin"}}}      # no such element on the fake: the window closes
t, drv = setup(drv, signing)
try:
    drv.source = f'<hierarchy><node text="{S.USER}"/><node text="token {S.PASSWORD}"/></hierarchy>'
    steps = "fill-account id=user default user\nsource shown\n"
    MC.PROBE = lambda spec: S.probe("android")
    code, out, err = app(t, steps)
    stored = S.tree_text(t.attempt_dir(CASE))
    check("secret: the account on a screen is replaced in the stored source, never kept", S.PASSWORD not in stored and S.USER not in stored
          and "[redacted]" in stored and code == 0, f"{code} {err[:200]}")
    drv.source = '<hierarchy><node text="api_key = \'abcdefghijklmnop1234\'"/></hierarchy>'
    code, out, err = app(t, "source shown\n")
    row = json.loads(out)["failed"]
    check("secret: a pattern match on the screen is a refusal that names the index only", row["outcome"] == "refused"
          and "secret_content_patterns[1]" in row["detail"] and "abcdefgh" not in S.tree_text(t.attempt_dir(CASE, "a2")), str(row))
finally:
    drv.stop()
    S.cleanup(t)

# ---- the activity of the app (F-10) ----------------------------------------------------------------------------------------------------
drv = Driver()
with_activity = config(drv.url)
with_activity["environments"][-1]["app"]["activity"] = ".MainActivity"
t, drv = setup(drv, with_activity)
try:
    code, out, err = app(t, "launch\n")
    session = next(b for m, p, b in drv.seen if (m, p) == ("POST", "/session"))["capabilities"]["alwaysMatch"]
    check_eq("activity (F-10): `app.activity` reaches the session under the row's capability name, and the row's key names never do",
             (code, session.get("appium:appActivity"), "activity_capability" in session, "app_id_param" in session), (0, ".MainActivity", False, False))
finally:
    drv.stop()
    S.cleanup(t)

# words of a screen: the attributes, entities refused up front, a broken tree is no text
check_eq("page_words: the attributes that carry words", MC.AppiumBackend.words_of('<a text="One" label="Two"><b content-desc="Three" id="x"/></a>'), "One Two Three")
check_eq("page_words: an entity declaration reads nothing", MC.AppiumBackend.words_of('<!DOCTYPE a [<!ENTITY e "boom">]><a text="&e;"/>'), "")
check_eq("page_words: a broken tree reads nothing", MC.AppiumBackend.words_of("<a text='x'"), "")
check_eq("page_words: cut at the page text limit", len(MC.AppiumBackend.words_of('<a text="' + "w" * (MC.PAGE_TEXT_CHARS + 5) + '"/>')), MC.PAGE_TEXT_CHARS)

# ---- the sign-in window, over a scripted backend --------------------------------------------------------------------------------
def window(recipe, steps):
    cfg = config("http://127.0.0.1:1")
    if recipe is not None:
        cfg["manual_capture"] = {"login": {"app": recipe}}
    t = S.make_task(cfg=cfg)
    MC.BACKEND_FACTORY = lambda: FakeApp()
    MC.PROBE, MC.NOW = (lambda spec: S.probe("android")), S.Clock()
    try:
        code, out, err = app(t, steps)
        shown = json.loads(out) if out.strip() else {}
        shown["_pngs"] = [p.name for p in t.task.rglob("*.png")]        # read before the folder goes
        return code, shown, err, t
    finally:
        S.cleanup(t)


typed = "fill-account id=user default user\nfill-account id=pw default secret\n"
code, summary, err, _ = window({"sign_in_selector": "id=signin"}, typed + "capture pre_action early\n")
row = summary["failed"]
check("window: a capture while the sign-in screen is up is refused, with the way out named", code == 1 and row["outcome"] == "refused"
      and "sign-in window" in row["detail"] and "capture after the sign-in screen is gone" in row["detail"], str(row))
check_eq("window: nothing of the sign-in screen was saved", [s.get("screenshot") for s in summary["steps"]], [None, None, None])
code, summary, err, t3 = window({"sign_in_selector": "id=signin"}, typed + "click id=boom\n")
check("window: a failed step inside it keeps no screenshot of the sign-in screen and says why", code == 1 and summary["failed"]["detail"].startswith(
    "no element matched id=boom") and MC.NO_SHOT_IN_WINDOW in summary["failed"]["detail"] and summary["_pngs"] == [], str(summary))
code, summary, err, _ = window({"sign_in_selector": "id=signin"}, typed + "source early\n")
row = summary["failed"]
check("window (F-15): a `source` while the sign-in screen is up is refused with the same door, and nothing is stored", code == 1
      and row["outcome"] == "refused" and "a source inside the sign-in window" in row["detail"]
      and "capture after the sign-in screen is gone" in row["detail"], str(row))
code, summary, err, _ = window({"sign_in_selector": "id=signin"}, typed + "click id=submit\nsource later\n")
check_eq("window (F-15): once the sign-in screen is gone the `source` is stored", (code, [s["outcome"] for s in summary["steps"]]), (0, ["ok"] * 4))
code, summary, err, _ = window({"sign_in_selector": "id=signin"}, typed + "click id=submit\ncapture pre_action later\n")
check_eq("window: once the sign-in screen is gone the capture is taken", (code, [s["outcome"] for s in summary["steps"]]), (0, ["ok"] * 4))
code, summary, err, _ = window(None, typed + "click id=submit\ncapture pre_action later\n")
row = summary["failed"]
check("window: no recipe, the window never closes and the door names the key", code == 1 and row["outcome"] == "refused"
      and "manual_capture.login.app.sign_in_selector" in row["detail"] and "login.ui" not in row["detail"], str(row))
code, summary, err, _ = window({"sign_in_selector": "button.primary"}, "launch\n")
check("window: a recipe selector with no strategy is refused (exit 2), before a session", code == 2 and "sign_in_selector" in err, err[:300])

# ---- the 40th and the 41st step (the same limit as `ui`) ---------------------------------------------------------------------------
t, drv = setup()
try:
    code, out, err = app(t, "back\n" * (MC.OBSERVE_MAX_STEPS + 1))
    summary = json.loads(out)
    check_eq("steps: the 40th is observed, the 41st only has its outcome", ("screenshot" in summary["steps"][39], "screenshot" in summary["steps"][40]), (True, False))
    check_in("steps: the stop is said in the limitations", f"observation stopped after {MC.OBSERVE_MAX_STEPS} steps", summary["limitations"])
finally:
    drv.stop()
    S.cleanup(t)

# the log of a surface that keeps none; a tool that is gone; a log over the body cap
t, drv = setup()
try:
    rows = json.loads(SF.TABLE_PATH.read_text(encoding="utf-8"))
    rows["surfaces"]["android"]["log"] = None
    nolog = Path(tempfile.mkdtemp(prefix="qa-surfaces-")) / "surfaces.json"
    nolog.write_text(json.dumps(rows), encoding="utf-8")
    held = SF.TABLE_PATH
    SF.TABLE_PATH = nolog
    try:
        code, out, err = app(t, "log tail\n")
    finally:
        SF.TABLE_PATH = held
    check("log: a row with no log refuses the step and says so", code == 1 and json.loads(out)["steps"][0]["outcome"] == "refused"
          and "keeps no log" in json.loads(out)["failed"]["detail"], out[:300])
finally:
    drv.stop()
    S.cleanup(t)
for label, tool, wide in (("a log over the body cap is cut with its limitation", lambda a, to: (0, DEVICES if "devices" in a else b"x" * (MC.BODY_CAP + 7)), True),
                          ("a log of exactly the body cap is whole", lambda a, to: (0, DEVICES if "devices" in a else b"x" * MC.BODY_CAP), False)):
    t, drv = setup(tool=tool)
    try:
        code, out, err = app(t, "log tail\n")
        entry = lines(t.attempt_dir(CASE) / "captures.jsonl")[0]
        size = (t.task / entry["path"]).stat().st_size
        check(f"log: {label}", code == 0 and size == MC.BODY_CAP and ("body cut at" in entry.get("limitation", "")) == wide, f"{size} {entry}")
    finally:
        drv.stop()
        S.cleanup(t)

finish("test_manual_app")
