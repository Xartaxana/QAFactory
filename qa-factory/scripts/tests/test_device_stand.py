#!/usr/bin/env python3
"""EP1-41b: device_stand.py - the stand of a device surface, with fakes only (no device tool, no driver server is run).

WHERE EVERY FIXTURE'S FORM COMES FROM (t-544 section 5). Read at Darker sha aaa44653c1d108b2e4889a30d4b3de6276b47e93 (report
t-524-ep1-41a-report.md): a device row's second field is the word `device` (doctor.py:89-138, tasks.ps1 `Get-Device`); the driver's
status is `GET /status` with `value.ready` compared to true, and a session is `POST /session` with `alwaysMatch` capabilities and
`DELETE /session/<id>` (tasks.ps1:926-1063). GENERAL KNOWLEDGE, NOT READ FROM A REAL TOOL: the header line of the device list, CRLF
output, a daemon's start lines before the header, the simulator list, the package dump, a driver's error JSON, the session id's place
in the reply. A green line here proves the reading logic, never the real tool (FR-33 stays open: nothing ran on a device).
"""
import contextlib
import io
import json
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import device_stand as D  # noqa: E402
import http_client as HC  # noqa: E402
import surfaces  # noqa: E402

TABLE = surfaces.rows()
ROWS = TABLE["surfaces"]
ANDROID, IOS = ROWS["android"], ROWS["ios"]
CODE = "com.example.app"
SERIAL = "emulator-5554"


# ---- fakes --------------------------------------------------------------------------------------------------------

class Tool:
    """A fake process. `duration` is how long it would run: past the timeout it is killed (TimeoutExpired), as the real one is."""

    def __init__(self, out=b"", code=0, duration=0.0, raises=None):
        self.out, self.code, self.duration, self.raises, self.calls = out, code, duration, raises, []

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if self.raises:
            raise self.raises
        if self.duration > timeout:
            raise subprocess.TimeoutExpired(argv, timeout)
        return self.code, self.out.encode("utf-8") if isinstance(self.out, str) else self.out


def answer(status=200, body=b"", headers=None, truncated=False, unreadable=False):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    pairs = HC.Headers([("Content-Type", "application/json")] if headers is None else headers)
    verdict = HC.classify(status, pairs, body, truncated=truncated, unreadable=unreadable, expect="json")
    return HC.Answer(status, pairs, body, truncated, unreadable, None, "http://127.0.0.1:4723", 0.0, verdict)


class Net:
    """A fake `http_client.fetch`: replies in order (an answer, or an exception to raise); every call is kept."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.replies:
            raise AssertionError(f"an unexpected request: {kwargs.get('method', 'GET')} {url}")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def methods(self):
        return [kwargs.get("method", "GET") for _, kwargs in self.calls]


def fakes(tool=None, net=None, platform="linux"):
    D.RUN_TOOL, D.HTTP, D.PLATFORM, D.NOW = tool, net, platform, lambda: "2026-10-31T12:00:00"
    D.WHICH = lambda name: "/fake/" + name


def real():
    D.RUN_TOOL = D.HTTP = D.PLATFORM = D.NOW = D.WHICH = None


def stand(**over):
    row = {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:4723", "base_path": "/"},
           "device": {"serial_key": "ANDROID_SERIAL"}, "app": {"id": CODE, "activity": ".Main", "extra_capabilities": {}}}
    row.update(over)
    return row


def config(*stands):
    return {"environments": list(stands) or [stand()]}


READY = {"value": {"build": {"version": "2.0.0"}, "ready": True}}   # general knowledge; the field `value.ready` is read at Darker
ONE = "List of devices attached\nemulator-5554\tdevice\n\n"
TWO = "List of devices attached\nemulator-5554\tdevice\nR58M12345\tdevice\n\n"
EMPTY_LIST = "List of devices attached\n\n"
SESSION_OK = {"value": {"sessionId": "abc-123", "capabilities": {"platformName": "Android"}}}


def devices(text, platform="linux", row=ANDROID):
    fakes(Tool(text), platform=platform)
    return D.list_devices(row)


# ---- 1. run_tool: the process, three outcomes, the limits -----------------------------------------------------------

fakes(Tool(ONE))
D.WHICH = lambda name: None
r = D.run_tool(["adb", "devices"], 10)
check_eq("1a a tool that is not on the PATH is tool_missing, not a device answer", r["state"], "tool_missing")
fakes(Tool(ONE))
check_eq("1b exit 0 is ok and the output is read", D.run_tool(["t"], 10)["out"], ONE)
fakes(Tool("boom", code=1))
r = D.run_tool(["t"], 10)
check_eq("1c exit other than 0 is tool_error", r["state"], "tool_error")
check_in("1c' and the line says what it printed", "boom", r["line"])
fakes(Tool(raises=PermissionError("no")))
check_eq("1d the process cannot be started: tool_error", D.run_tool(["t"], 10)["state"], "tool_error")
fakes(Tool(ONE, duration=10))
check_eq("1e timeout AT the limit: the tool answered", D.run_tool(["t"], 10)["state"], "ok")
fakes(Tool(ONE, duration=10.001))
check_eq("1f timeout BEYOND the limit: timeout", D.run_tool(["t"], 10)["state"], "timeout")
fakes(Tool(b"x" * 4096))
r = D.run_tool(["t"], 10)
check("1g output of exactly the limit (4096) is whole", len(r["out"]) == 4096 and not r["cut"])
fakes(Tool(b"x" * 4097))
r = D.run_tool(["t"], 10)
check("1h output one byte over the limit is cut and marked", len(r["out"]) == 4096 and r["cut"])
fakes(Tool(b"ok \xff\xfe \xd0\x96"))
check_in("1i bytes that are not UTF-8 are replaced, never a crash", "ok", D.run_tool(["t"], 10)["out"])
real()
r = D.run_tool(["no-such-tool-device-stand-41b"], 5)
check_eq("1j REAL: a name that is not on the PATH is tool_missing", r["state"], "tool_missing")
r = D.run_tool([sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err')"], 20)
check("1k REAL: a process runs; stderr is read together with stdout", r["state"] == "ok" and "out" in r["out"] and "err" in r["out"])
r = D.run_tool([sys.executable, "-c", "raise SystemExit(3)"], 20)
check_eq("1l REAL: exit 3 is tool_error", r["state"], "tool_error")
r = D.run_tool([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)
check_eq("1m REAL: a process past the timeout is killed: timeout", r["state"], "timeout")

# ---- 2. list_devices: the outcomes -----------------------------------------------------------------------------------

r = devices(ONE)
check("2a one device", r["state"] == "devices" and r["serials"] == [SERIAL])
r = devices(TWO)
check_eq("2b two devices", r["serials"], [SERIAL, "R58M12345"])
r = devices(EMPTY_LIST)
check_eq("2c a header and no row is the one and only no_device", r["state"], "no_device")
for label, text in (("empty", ""), ("only blanks", " \n\n\t\n"), ("only a CRLF", "\r\n")):
    check_eq(f"2d empty output ({label}) is unreadable, never no_device", devices(text)["state"], "unreadable")
r = devices("error: protocol fault (couldn't read status): connection reset by peer\n")
check_eq("2e non-empty output with no header is unreadable (noise is never 'no device')", r["state"], "unreadable")
check_eq("2f CRLF device rows read as LF", devices(ONE.replace("\n", "\r\n"))["serials"], [SERIAL])
check_eq("2f' CRLF and no device is still no_device", devices(EMPTY_LIST.replace("\n", "\r\n"))["state"], "no_device")
daemon = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\n" + ONE
check_eq("2g a daemon-start line before the header: the header is still found", devices(daemon)["serials"], [SERIAL])
check_eq("2g' the same with CRLF", devices(daemon.replace("\n", "\r\n"))["serials"], [SERIAL])
check_eq("2g'' the daemon lines and no device: no_device, not noise", devices(daemon.replace(ONE, EMPTY_LIST))["state"], "no_device")
r = devices("List of devices attached\nemulator-5554\toffline\nR58M12345\tunauthorized\n\n")
check("2h only offline / unauthorized rows: no_device naming serial and state",
      r["state"] == "no_device" and "emulator-5554 is offline" in r["line"] and "R58M12345 is unauthorized" in r["line"])
r = devices("List of devices attached\nemulator-5554\toffline\nR58M12345\tdevice\n")
check("2i an offline row beside a ready one: only the ready one is a device", r["serials"] == ["R58M12345"] and len(r["others"]) == 1)
r = devices("List of devices attached\nabc123\trecovery\n")
check_eq("2j a state the table does not know, alone: unreadable (not 'no device')", r["state"], "unreadable")
r = devices("List of devices attached\nemu 5554\tdevice\n")
check_eq("2k a serial with a blank in it does not match the row form: unreadable", r["state"], "unreadable")
r = devices("List of devices attached\nemulator-5554\tdevice\nabc123\trecovery\n")
check("2l a ready device with a row of unknown form: the ready one is listed, the odd row is kept", r["serials"] == [SERIAL] and r["unknown"])
fakes(Tool("* \u0434\u0435\u043c\u043e\u043d \xff\n".encode("utf-8") + b"\xff\n" + ONE.encode()))
check_eq("2m non-ASCII and broken bytes before the header", D.list_devices(ANDROID)["serials"], [SERIAL])
pad = lambda n: "List of devices attached\nemulator-5554\tdevice\n" + "\n" * (n - len("List of devices attached\nemulator-5554\tdevice\n"))  # noqa: E731
check_eq("2n output of exactly 4096 bytes is whole", devices(pad(4096))["serials"], [SERIAL])
r = devices(pad(4097))
check_eq("2o output of 4097 bytes is cut and unreadable", r["state"], "unreadable")
check_in("2o' and the line says it was cut", "cut", r["line"])
r = devices("List of devices attached\n" + "\n" * 6000 + "emulator-5554\tdevice\n")
check("2p a header kept and the device cut away: unreadable, never no_device", r["state"] == "unreadable")
fakes(Tool(raises=subprocess.TimeoutExpired("t", 1)))
check_eq("2q a timeout of the device tool is tool_error", D.list_devices(ANDROID)["state"], "tool_error")
fakes(Tool("fail", code=1))
check_eq("2r a failing device tool is tool_error", D.list_devices(ANDROID)["state"], "tool_error")
fakes(Tool(ONE))
D.WHICH = lambda name: None
r = D.list_devices(ANDROID)
check("2s a missing device tool is tool_missing and is not 'no device'", r["state"] == "tool_missing" and "adb" in r["line"])
fakes(Tool(ONE))
D.list_devices(ANDROID)
check_eq("2t the tool's timeout is the table's tool_timeout_s", D.RUN_TOOL.calls[0][1], TABLE["tool_timeout_s"])
check_eq("2u the command is the row's argv (the program is the PATH hit)", D.RUN_TOOL.calls[0][0][1:], ["devices"])

# host_os: empty, each side
tool = Tool(ONE)
fakes(tool, platform="win32")
check_eq("2v host_os [] runs on any platform (win32)", D.list_devices(ANDROID)["state"], "devices")
fakes(tool, platform="darwin")
check_eq("2v' host_os [] runs on darwin", D.list_devices(ANDROID)["state"], "devices")
IOS_ONE = "== Devices ==\n-- iOS 17.0 --\n    iPhone 15 (0A1B2C3D-0000-1111-2222-ABCDEF012345) (Booted)\n"
tool = Tool(IOS_ONE)
fakes(tool, platform="win32")
r = D.list_devices(IOS)
check("2w host_os ['darwin'] on win32: host_os, the tool is not run", r["state"] == "host_os" and not tool.calls)
check_in("2w' the line names the host kinds and this machine", "darwin", r["line"])
fakes(tool, platform="darwin")
r = D.list_devices(IOS)
check("2x host_os ['darwin'] on darwin: read, a simulator row found", r["serials"] == ["0A1B2C3D-0000-1111-2222-ABCDEF012345"])
fakes(Tool("== Devices ==\n"), platform="darwin")
check_eq("2y simulator list with nothing booted: no_device", D.list_devices(IOS)["state"], "no_device")
fakes(Tool(ONE))
check_eq("2z host_os that is not a list: unreadable, the tool is not run", D.list_devices({**ANDROID, "host_os": "darwin"})["state"], "unreadable")
check_eq("2z' a row with no way to list devices is unreadable", D.list_devices({**ANDROID, "devices": None})["state"], "unreadable")
try:
    D.list_devices({**ANDROID, "devices": {**ANDROID["devices"], "header_re": "(["}})
    check("2z'' a broken pattern in the table is a ValueError (the factory's)", False)
except ValueError:
    check("2z'' a broken pattern in the table is a ValueError (the factory's)", True)

# ---- 3. pick_device -------------------------------------------------------------------------------------------------

def pick(text, values, st=None):
    fakes(Tool(text))
    return D.pick_device(ANDROID, st if st is not None else stand(), values)

r = pick(ONE, {})
check("3a one device, no key value: that device", r["state"] == "picked" and r["serial"] == SERIAL)
r = pick(TWO, {})
check("3b two devices and none named: ambiguous, never the first", r["state"] == "ambiguous" and r["serial"] == "")
check("3b' the line lists both and names the key", SERIAL in r["line"] and "R58M12345" in r["line"] and "ANDROID_SERIAL" in r["line"])
r = pick(TWO, {"ANDROID_SERIAL": "R58M12345"})
check("3c two devices, the second named: the second", r["state"] == "picked" and r["serial"] == "R58M12345")
r = pick(TWO, {"ANDROID_SERIAL": " R58M12345 \n"})
check_eq("3c' a value with blanks around it is the same serial", r["serial"], "R58M12345")
r = pick(ONE, {"ANDROID_SERIAL": "R58M12345"})
check("3d one device but another is named: not_connected, the one is not used", r["state"] == "not_connected" and r["serial"] == "R58M12345")
r = pick("List of devices attached\nR58M12345\toffline\nemulator-5554\tdevice\n", {"ANDROID_SERIAL": "R58M12345"})
check("3e the named device is offline: not_connected, and the line says offline", r["state"] == "not_connected" and "offline" in r["line"])
r = pick(TWO, {"ANDROID_SERIAL": ""})
check_eq("3f an empty value is no value", r["state"], "ambiguous")
r = pick(TWO, None)
check_eq("3g no environment at all: ambiguous", r["state"], "ambiguous")
r = pick(TWO, {"ANDROID_SERIAL": "R58M12345"}, st=stand(device={}))
check_eq("3h the config names no key: the value is not read, ambiguous", r["state"], "ambiguous")
check_in("3h' and the line says where to name a key", "serial_key", r["line"])
r = pick(EMPTY_LIST, {"ANDROID_SERIAL": SERIAL})
check_eq("3i no device at all: no_device", r["state"], "no_device")
r = pick("", {})
check_eq("3j empty output: unreadable, passed through", r["state"], "unreadable")

# ---- 4. driver_status ----------------------------------------------------------------------------------------------

def status(*replies, st=None):
    net = Net(*replies)
    fakes(None, net)
    return D.driver_status(st if st is not None else stand(), ANDROID), net

r, net = status(answer(200, READY))
check_eq("4a ready is true: ready", r["state"], "ready")
check_eq("4a' the address is the status path under the base path", net.calls[0][0], "http://127.0.0.1:4723/status")
kw = net.calls[0][1]
check("4a'' the table's timeout and body cap are used; the answer is expected as JSON",
      kw["timeout"] == TABLE["tool_timeout_s"] and kw["max_body"] == TABLE["drivers"]["appium"]["max_body"] and kw["expect"] == "json")
r, net = status(answer(200, READY), st=stand(driver={"url": "http://h:4723/", "base_path": "/wd/hub/"}))
check_eq("4b base_path joined once", net.calls[0][0], "http://h:4723/wd/hub/status")
r, net = status(answer(200, READY), st=stand(driver={"url": "http://h:4723"}))
check_eq("4b' no base_path in the row: the table's default", net.calls[0][0], "http://h:4723/status")
for label, body, want in (
        ("ready false", {"value": {"ready": False}}, "not_ready"),
        ("ready the STRING 'true' is not ready (truthiness is not enough)", {"value": {"ready": "true"}}, "not_ready"),
        ("ready 1 is not ready", {"value": {"ready": 1}}, "not_ready"),
        ("ready null is not ready", {"value": {"ready": None}}, "not_ready"),
        ("value null is not the server's shape", {"value": None}, "foreign"),
        ("value without ready", {"value": {"build": {}}}, "foreign"),
        ("a JSON array", [{"value": {"ready": True}}], "foreign"),
        ("ready at the wrong depth", {"ready": True}, "foreign"),
        ("a bare JSON string", "text", "foreign")):
    body_bytes = json.dumps(body).encode("utf-8")
    r, _ = status(answer(200, body_bytes))
    check_eq(f"4c {label}: {want}", r["state"], want)
r, _ = status(answer(200, b"<html><head><title>Sign in</title></head><body>proxy</body></html>", headers=[("Content-Type", "text/html")]))
check("4d a proxy page with status 200 is foreign and the line says it is a page", r["state"] == "foreign" and "page" in r["line"])
r, _ = status(answer(200, b"plain words"))
check("4e text that is not JSON is foreign", r["state"] == "foreign" and "JSON" in r["line"])
r, _ = status(answer(401, {"error": "unauthorized", "message": "no"}))
check_eq("4f 401 is foreign (not the server's status), never ready", r["state"], "foreign")
r, _ = status(answer(302, b"", headers=[("Location", "http://login.example/")]))
check_eq("4g a redirect is foreign (not followed)", r["state"], "foreign")
r, _ = status(answer(500, b"oops"))
check_eq("4h a server error is foreign", r["state"], "foreign")
r, _ = status(answer(200, json.dumps(READY).encode() + b" " * 10, truncated=True))
check_eq("4i a truncated answer is foreign even when its prefix says ready", r["state"], "foreign")
r, _ = status(answer(200, b"", unreadable=True))
check_eq("4j an unreadable body is foreign", r["state"], "foreign")
for exc in (ConnectionRefusedError("x"), TimeoutError("t"), urllib.error.URLError("dns"), OSError("net")):
    r, _ = status(exc)
    check_eq(f"4k {exc.__class__.__name__} is down", r["state"], "down")
import http.client  # noqa: E402
r, _ = status(http.client.RemoteDisconnected("closed"))
check_eq("4k' a closed connection is down", r["state"], "down")
check_in("4l the down line names the server and the address", "http://127.0.0.1:4723", status(OSError("x"))[0]["line"])
for label, url in (("missing", None), ("empty", " "), ("not http", "ftp://h"), ("with a password", "http://user:pw@h:4723"),
                   ("with a query", "http://h:4723/?token=zz"), ("a port that is not a number", "http://h:abc"), ("no host", "http://")):
    r, net = status(st=stand(driver={"url": url}))
    check(f"4m driver.url {label}: down with no request sent", r["state"] == "down" and not net.calls)
r, _ = status(st=stand(driver={"url": "http://user:pw@h:4723"}))
check_not_in("4m' the credential is never printed", r["line"], "pw")

# ---- 5. create_session / delete_session / deep_session ------------------------------------------------------------

net = Net(answer(200, SESSION_OK))
fakes(None, net)
made = D.create_session(stand(), ANDROID, SERIAL)
check("5a a session id in the reply: ok", made["state"] == "ok" and made["session_id"] == "abc-123")
url, kw = net.calls[0]
caps = json.loads(kw["data"])["capabilities"]["alwaysMatch"]
check_eq("5b POST to the session path", (kw["method"], url), ("POST", "http://127.0.0.1:4723/session"))
check("5c the minimal capabilities: platform, automation, device, the table's defaults",
      caps["platformName"] == "Android" and caps["appium:automationName"] == "UiAutomator2" and caps["appium:udid"] == SERIAL
      and caps["appium:noReset"] is True and caps["appium:newCommandTimeout"] == 300)
check("5d no app is named, so none is started", not any("appPackage" in k or "bundleId" in k for k in caps))
check_eq("5e the session timeout is the table's", kw["timeout"], TABLE["drivers"]["appium"]["session_timeout_s"])
check_in("5f the body is sent as JSON", "application/json", kw["headers"]["Content-Type"])
for label, reply in (
        ("no session id", answer(200, {"value": {}})),
        ("an empty session id", answer(200, {"value": {"sessionId": ""}})),
        ("a numeric session id", answer(200, {"value": {"sessionId": 7}})),
        ("a blank session id", answer(200, {"value": {"sessionId": "  "}})),
        ("the id at the wrong depth", answer(200, {"sessionId": "abc"})),
        ("not JSON", answer(200, b"<html>x</html>", headers=[("Content-Type", "text/html")])),
        ("a truncated reply", answer(200, json.dumps(SESSION_OK).encode(), truncated=True)),
        ("a server error", answer(500, {"value": {"error": "session not created", "message": "boom"}})),
        ("a bad request", answer(400, b""))):
    fakes(None, Net(reply))
    check_eq(f"5g {label}: session_failed", D.create_session(stand(), ANDROID, SERIAL)["state"], "session_failed")
fakes(None, Net(TimeoutError("slow")))
check_eq("5h no answer: session_failed", D.create_session(stand(), ANDROID, SERIAL)["state"], "session_failed")
fakes(None, Net(answer(500, {"value": {"error": "session not created", "message": "Could not start a session\nsecond line\nthird"}})))
said = D.create_session(stand(), ANDROID, SERIAL)["line"]
check("5i the first line of the reply is shown, the others are not", "Could not start a session" in said and "second line" not in said)
fakes(None, Net(answer(500, {"value": {"message": "x" * 500}})))
said = D.create_session(stand(), ANDROID, SERIAL)["line"]
check("5j a long first line is cut at 200 characters", "x" * 197 + "..." in said and "x" * 198 not in said)
fakes(None, Net(answer(500, {"value": {"message": "cannot reach http://user:secret@host:1/p?token=zz now"}})))
said = D.create_session(stand(), ANDROID, SERIAL)["line"]
check("5k a credential or a query in an address of the reply is not shown", "secret" not in said and "token=zz" not in said and "host" in said)
fakes(None, Net(answer(200, SESSION_OK)))
check_eq("5l a driver.url that is unusable asks for no session", D.create_session(stand(driver={"url": None}), ANDROID, SERIAL)["state"], "session_failed")

net = Net(answer(200, SESSION_OK), answer(200, {"value": None}))
fakes(None, net)
r = D.deep_session(stand(), ANDROID, SERIAL)
check_eq("5m deep: created then deleted", (r["state"], net.methods()), ("ok", ["POST", "DELETE"]))
check_eq("5m' the delete goes to the created session", net.calls[1][0], "http://127.0.0.1:4723/session/abc-123")
net = Net(answer(500, {"value": {"message": "no"}}))
fakes(None, net)
r = D.deep_session(stand(), ANDROID, SERIAL)
check_eq("5n creation failed: session_failed and NO delete is sent", (r["state"], net.methods()), ("session_failed", ["POST"]))
net = Net(answer(200, SESSION_OK), answer(404, b""))
fakes(None, net)
r = D.deep_session(stand(), ANDROID, SERIAL)
check("5o the delete fails (404): still ok, the line names the session left and the idle time (30, the deep session's own, F-11)",
      r["state"] == "ok" and "abc-123" in r["line"] and "after 30 seconds" in r["line"] and "300" not in r["line"])
deep_caps = json.loads(net.calls[0][1]["data"])["capabilities"]["alwaysMatch"]
check_eq("5o' F-11: the deep session asks for a 30 s idle limit and NO noReset; the row's own (activity, app id key) never reach the body",
         (deep_caps["appium:newCommandTimeout"], "appium:noReset" in deep_caps, sorted(set(deep_caps) & {"app_id_param", "appId", "bundleId", "appium:appActivity", "activity_capability",
                                                                                           "appium:appPackage"})), (30, False, []))
net = Net(answer(200, SESSION_OK), OSError("gone"))
fakes(None, net)
r = D.deep_session(stand(), ANDROID, SERIAL)
check("5p the delete gets no answer: ok with the same note", r["state"] == "ok" and "left on the device" in r["line"])
net = Net(answer(200, {"value": {"sessionId": "a/b c"}}), answer(200, {"value": None}))
fakes(None, net)
D.deep_session(stand(), ANDROID, SERIAL)
check_eq("5q a session id is one quoted path segment", net.calls[1][0], "http://127.0.0.1:4723/session/a%2Fb%20c")

net = Net(answer(200, SESSION_OK), answer(200, {"value": None}))
fakes(None, net)
real_driver_data, count = D.driver_data, [0]
def flaky(row):  # noqa: E306 - raises on the SECOND read, which is deep_session's own, between create and delete
    count[0] += 1
    if count[0] == 2:
        raise ValueError("table broke")
    return real_driver_data(row)
D.driver_data = flaky
try:
    D.deep_session(stand(), ANDROID, SERIAL)
    raised = False
except ValueError:
    raised = True
D.driver_data = real_driver_data
check("5r something fails after the session exists: the delete is still sent (finally)", raised and net.methods() == ["POST", "DELETE"])

# ---- 6. installed_build -----------------------------------------------------------------------------------------

DUMP = ("Packages:\n  Package [com.example.app] (1a2b3c):\n    userId=10123\n    versionCode=42 minSdk=24 targetSdk=34\n"
        "    versionName=1.2.3\n    splits=[base]\n")   # general knowledge, not read from a real tool (Darker reads versionCode only)

def build(text, code=0, **over):
    tool = Tool(text, code=code)
    fakes(tool)
    return D.installed_build({**ANDROID, **over}, SERIAL, CODE), tool

r, tool = build(DUMP)
check("6a version and code are read", r["state"] == "read" and r["version"] == "1.2.3" and r["code"] == "42")
check_eq("6a' the line is app id, version, code", r["line"], "com.example.app 1.2.3 (42)")
check_eq("6b the command carries the device and the app id", tool.calls[0][0][1:],
         ["-s", SERIAL, "shell", "dumpsys", "package", CODE])
r, _ = build(DUMP.replace("\n", "\r\n"))
check_eq("6c CRLF output reads the same", (r["version"], r["code"]), ("1.2.3", "42"))
r, _ = build(DUMP + "  Package [other]:\n    versionCode=7\n    versionName=9.9\n")
check_eq("6d several blocks: the first match", (r["version"], r["code"]), ("1.2.3", "42"))
r, _ = build("x" * 60000 + DUMP)
check("6e a long package dump is read beyond the 4096-byte device-list limit", r["state"] == "read" and r["version"] == "1.2.3")
r, _ = build("versionCode=9\n")
check_eq("6f only a code: read, the version is empty", (r["state"], r["version"], r["code"]), ("read", "", "9"))
r, _ = build("")
check_eq("6g empty output is tool_error, never 'not installed'", r["state"], "tool_error")
r, _ = build("Failure", code=1)
check_eq("6h a failing tool is tool_error", r["state"], "tool_error")
fakes(Tool(raises=subprocess.TimeoutExpired("t", 1)))
check_eq("6i a timeout is tool_error", D.installed_build(ANDROID, SERIAL, CODE)["state"], "tool_error")
fakes(Tool(DUMP, duration=10))
check_eq("6i' timeout AT the limit answers", D.installed_build(ANDROID, SERIAL, CODE)["state"], "read")
fakes(Tool(DUMP, duration=10.5))
check_eq("6i'' timeout BEYOND the limit is tool_error", D.installed_build(ANDROID, SERIAL, CODE)["state"], "tool_error")
r, _ = build("Unable to find package: com.example.app\n")
check_eq("6j an answer that names no version: not_installed", r["state"], "not_installed")
r, _ = build("x" * (TABLE["drivers"]["appium"]["max_body"] + 10))
check_eq("6k output cut at the limit with no match is tool_error, not 'not installed'", r["state"], "tool_error")
r, tool = build(DUMP, installed_build=None)
check("6l a row with no way to read it: no_method, the tool is not run", r["state"] == "no_method" and not tool.calls)
for bad in ("a; reboot", "$(id)", "", "-s", "com example"):
    fakes(Tool(DUMP))
    r = D.installed_build(ANDROID, SERIAL, bad)
    check(f"6m app id {bad!r} is no_method and reaches no shell", r["state"] == "no_method" and not D.RUN_TOOL.calls)
fakes(Tool(DUMP))
check_eq("6n no device named: no_method", D.installed_build(ANDROID, "", CODE)["state"], "no_method")

# ---- 6b. the installed file (EP1-41e): the hash that tells a rebuild with the same version ------------------------
# GENERAL KNOWLEDGE, NOT READ FROM A REAL TOOL: the patterns of `pm path` and `sha256sum` output and the several `package:` lines of a
# split install. The two command forms were read at Darker (t-524-ep1-41a-report.md row [3]); nothing ran on a device.

PATH1 = "/data/app/~~Zx9==/com.example.app-Q1==/base.apk"
PATH2 = "/data/app/~~Zx9==/com.example.app-Q1==/split_config.en.apk"
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64


class Router:
    """A fake process that answers by the command it is given: the package dump, `pm path`, `sha256sum <path>`. `duration` is per
    command kind (dump, pm, sha); `shas` maps a path to the text (or (exit code, text)) that `sha256sum` prints for it."""

    def __init__(self, pm=f"package:{PATH1}\n", shas=None, duration=None, pm_code=0):
        self.pm, self.pm_code, self.duration, self.calls = pm, pm_code, duration or {}, []
        self.shas = {PATH1: f"{SHA_A}  {PATH1}\n"} if shas is None else shas

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        kind = "pm" if "pm" in argv else "sha" if "sha256sum" in argv else "dump"
        if self.duration.get(kind, 0) > timeout:
            raise subprocess.TimeoutExpired(argv, timeout)
        if kind == "dump":
            return 0, DUMP.encode()
        if kind == "pm":
            return self.pm_code, self.pm.encode()
        said = self.shas.get(argv[-1], (1, "sha256sum: no such file"))
        code, text = said if isinstance(said, tuple) else (0, said)
        return code, text.encode()

    def kinds(self):
        return ["pm" if "pm" in c[0] else "sha" if "sha256sum" in c[0] else "dump" for c in self.calls]


def built(router, row=ANDROID):
    fakes(router)
    return D.installed_build(row, SERIAL, CODE)


ART = ANDROID["installed_build"]
check("6o the table row carries the artifact forms (data, AR-1)", isinstance(ART.get("artifact"), dict)
      and {"path_argv", "path_re", "sha_argv", "sha_re"} <= set(ART["artifact"]))
router = Router()
r = built(router)
check_eq("6p one file: read, hashed, no limitation", (r["state"], r["hashed"], r["limitation"]), ("read", True, ""))
check_eq("6p' the line a person reads carries the first 12 hex of the file", r["line"], f"com.example.app 1.2.3 (42) sha256:{SHA_A[:12]}")
check_eq("6p'' the value (what a digest is taken of) carries the whole hash", r["value"], f"com.example.app 1.2.3 (42) sha256:{SHA_A}")
check_eq("6p''' commands: the dump, then `pm path` for the app, then `sha256sum` of the path it printed (device named each time)",
         (router.kinds(), router.calls[1][0][1:], router.calls[2][0][1:]),
         (["dump", "pm", "sha"], ["-s", SERIAL, "shell", "pm", "path", CODE], ["-s", SERIAL, "shell", "sha256sum", PATH1]))
two = f"package:{PATH1}\r\npackage:{PATH2}\r\n"
router = Router(pm=two, shas={PATH1: f"{SHA_A}  {PATH1}\r\n", PATH2: f"{SHA_B}  {PATH2}\r\n"})
r = built(router)
check_eq("6q two `package:` lines hash BOTH, in the order the device printed them (CRLF reads the same)",
         (r["hashed"], r["value"], router.kinds()), (True, f"com.example.app 1.2.3 (42) sha256:{SHA_A},{SHA_B}", ["dump", "pm", "sha", "sha"]))
check_eq("6q' ...and the line shows both groups of 12", r["line"], f"com.example.app 1.2.3 (42) sha256:{SHA_A[:12]},{SHA_B[:12]}")
swapped = built(Router(pm=two, shas={PATH1: f"{SHA_B}  {PATH1}\n", PATH2: f"{SHA_A}  {PATH2}\n"}))
check("6q'' the same two hashes in the other order are another value (a split moved)", swapped["value"] != r["value"])
other = built(Router(pm=two, shas={PATH1: f"{SHA_A}  {PATH1}\n", PATH2: f"{SHA_C}  {PATH2}\n"}))
check("6q''' ONE of two files rebuilt is another value", other["value"] != r["value"] and other["hashed"])
rebuilt = built(Router(shas={PATH1: f"{SHA_B}  {PATH1}\n"}))
check_eq("6r the SAME version and code with another file: another value, another line, both read",
         (rebuilt["version"], rebuilt["code"], rebuilt["value"] != built(Router())["value"], rebuilt["line"] != built(Router())["line"]),
         ("1.2.3", "42", True, True))

LINE = "com.example.app 1.2.3 (42)"


def unhashed(label, r, calls=None):
    check_eq(f"6s {label}: the version is read, the hash is not, and the line says what is not seen",
             (r["state"], r["hashed"], r["line"], r["value"], r["limitation"]), ("read", False, LINE, LINE, D.HASH_LIMITATION))


unhashed("`pm path` fails", built(Router(pm="Error", pm_code=1)))
unhashed("`pm path` prints nothing", built(Router(pm="")))
unhashed("`pm path` prints no `package:` line", built(Router(pm="Error: Could not access the Package Manager\n")))
unhashed("`sha256sum` fails", built(Router(shas={PATH1: (1, "sha256sum: " + PATH1 + ": Permission denied")})))
unhashed("`sha256sum` is not on the device", built(Router(shas={PATH1: (127, "sh: sha256sum: not found")})))
unhashed("`sha256sum` prints nothing", built(Router(shas={PATH1: ""})))
unhashed("`sha256sum` prints a short hash (63 hex)", built(Router(shas={PATH1: "a" * 63 + "  x\n"})))
unhashed("`sha256sum` prints an upper-case hash", built(Router(shas={PATH1: "A" * 64 + "  x\n"})))
unhashed("`sha256sum` prints a message that only contains a hash later in a line", built(Router(shas={PATH1: "error: " + SHA_A + "\n"})))
unhashed("the second of two files cannot be hashed (all or none: a hash of half an install is not reported)",
         built(Router(pm=two, shas={PATH1: f"{SHA_A}  {PATH1}\n", PATH2: (1, "denied")})))
unhashed("the `artifact` block is absent from the row", built(Router(), {**ANDROID, "installed_build": {k: v for k, v in ART.items() if k != "artifact"}}))
unhashed("the `artifact` block is not a block", built(Router(), {**ANDROID, "installed_build": {**ART, "artifact": "adb"}}))
router = Router(pm="package:/data/app/x/$(reboot)/base.apk\n")
unhashed("a path with a shell word in it", built(router))
check("6s' ...and nothing was handed to a shell on the device for it", "sha" not in router.kinds())
router = Router(pm=f"package:{PATH1}\npackage:/data/app/a;reboot\n")
unhashed("one of two paths is not a plain path", built(router))
check("6s'' ...and no `sha256sum` ran for the plain one either (the check comes before any run)", "sha" not in router.kinds())
router = Router()
fakes(router)
r = D.installed_build({**ANDROID, "installed_build": {k: v for k, v in ART.items() if k != "artifact"}}, SERIAL, CODE)
check_eq("6s''' without `artifact` the tool of the hash is never run", router.kinds(), ["dump"])
for label, over in (("path_re", {"path_re": "("}), ("sha_re", {"sha_re": "["}), ("path_argv", {"path_argv": None})):
    fakes(Router())
    try:
        D.installed_build({**ANDROID, "installed_build": {**ART, "artifact": {**ART["artifact"], **over}}}, SERIAL, CODE)
        raised = False
    except ValueError as exc:
        raised = "installed_build.artifact" in str(exc) and "factory defect" in str(exc)
    check(f"6t a broken `{label}` of the table is a ValueError naming the block (the factory's defect), not a quiet 'not hashed'", raised)
# the tool timeout, AT and BEYOND, on each of the two commands of the hash
limit = TABLE["tool_timeout_s"]
for kind in ("pm", "sha"):
    r = built(Router(duration={kind: limit}))
    check_eq(f"6u the `{kind}` call AT the timeout answers: hashed", r["hashed"], True)
    r = built(Router(duration={kind: limit + 0.5}))
    unhashed(f"the `{kind}` call BEYOND the timeout", r)
r = built(Router(), {**ANDROID, "installed_build": {**ART, "artifact": {**ART["artifact"], "sha_argv": ["adb", "-s", "{device}", "shell", "sha256sum", "{path}", "{path}"]}}})
check("6v the path is filled into every place the row puts it", r["hashed"])
r, _ = build("Unable to find package: com.example.app\n")
check_eq("6w the other states carry the new fields too (not hashed, no limitation, no value)",
         (r["state"], r["hashed"], r["limitation"], r["value"]), ("not_installed", False, "", ""))

# ---- 7. probe ---------------------------------------------------------------------------------------------------

def run_probe(text=ONE, net=None, deep=False, values=None, cfg=None, name="", platform="linux"):
    tool = Tool(text)
    fakes(tool, net if net is not None else Net(answer(200, READY)), platform)
    return D.probe(cfg if cfg is not None else config(), name, deep, values if values is not None else {}), tool

r, tool = run_probe()
check("7a all well: verdict ok, no block, the session was not tried (deep false)",
      r["verdict"] == "ok" and r["block"] is None and r["deep"] is False and [c["name"] for c in r["checks"]] == ["device", "driver"])
check_eq("7a' no HTTP beyond /status without --deep (read-only)", D.HTTP.methods(), ["GET"])
check_eq("7a'' the stamp comes from the clock", r["checked_at"], "2026-10-31T12:00:00")
check("7a''' every check has the five keys", all(set(c) == {"name", "state", "line", "owner", "remedy"} for c in r["checks"]))
r, _ = run_probe(net=Net(answer(200, READY), answer(200, SESSION_OK), answer(200, {"value": None})), deep=True)
check("7b deep: three checks and the session is confirmed", r["verdict"] == "ok" and [c["name"] for c in r["checks"]] == ["device", "driver", "session"])
check_eq("7b' deep: GET, POST, DELETE", D.HTTP.methods(), ["GET", "POST", "DELETE"])
r, _ = run_probe(EMPTY_LIST, net=Net(OSError("down")), deep=True)
states = {c["name"]: c["state"] for c in r["checks"]}
check("7c no device and the server down: BOTH are reported, the session is skipped", states == {"device": "no_device", "driver": "down", "session": "skipped"})
check_eq("7c' verdict blocked and the block is the first problem", (r["verdict"], r["block"]["probe_line"]), ("blocked", r["checks"][0]["line"]))
check("7c'' the block has the EnvBlocked row's shape for a device cause",
      r["block"]["owner"] == "user" and r["block"]["do_not_retry"] is True and r["block"]["cause"] == "device" and r["block"]["remedy"])
check_eq("7c''' a skipped check is nobody's problem", [c["owner"] for c in r["checks"]], ["user", "user", ""])
check_eq("7c'''' the session is not even asked for", D.HTTP.methods(), ["GET"])
r, _ = run_probe("", net=Net(answer(200, READY)))
check("7d empty device output: unknown (the factory's), the block is owned by the factory",
      r["verdict"] == "unknown" and r["block"]["owner"] == "factory" and r["checks"][0]["state"] == "unreadable")
r, _ = run_probe(net=Net(answer(200, b"<html>login</html>", headers=[("Content-Type", "text/html")])))
check("7e a foreign page on the driver's address: unknown, factory-owned, cause device", r["verdict"] == "unknown" and r["block"]["owner"] == "factory")
r, _ = run_probe(net=Net(answer(200, {"value": {"ready": False}})))
check("7f not ready: blocked, user-owned", r["verdict"] == "blocked" and r["checks"][1]["state"] == "not_ready")
tool_missing = Tool(ONE)
fakes(tool_missing, Net(answer(200, READY)))
D.WHICH = lambda name: None
r = D.probe(config(), "", False, {})
check("7g the tool missing is told as tool_missing with the tool's name, not as no_device",
      r["checks"][0]["state"] == "tool_missing" and "adb" in r["checks"][0]["line"] and not tool_missing.calls)
r, tool = run_probe(IOS_ONE, platform="win32", cfg=config(stand(surface="ios")))
check("7h an iOS-kind row on a host that cannot ask: host_os, the tool is not run", r["checks"][0]["state"] == "host_os" and not tool.calls)
r, _ = run_probe(cfg=config(stand(device={"serial_key": "ANDROID_SERIAL"})), values={"ANDROID_SERIAL": "R58M12345"})
check_eq("7i the device named by the key is not connected: blocked", r["checks"][0]["state"], "not_connected")

# the stand itself
r, _ = run_probe(cfg=config(stand(name="web", surface=None)), name="web")
check("7j an environment with no surface is not a device stand: not_configured", r["checks"][0]["state"] == "not_configured")
r, _ = run_probe(cfg=config(stand(name="api", surface="api")), name="api")
check("7k an environment of a surface with other hands is not a device stand", r["checks"][0]["state"] == "not_configured")
r, tool = run_probe(cfg=config(stand(surface="symbian")))
check("7l a surface the table lacks: not_configured, nothing run", r["checks"][0]["state"] == "not_configured" and not tool.calls)
r, _ = run_probe(name="nope")
check("7m an environment name that is not in the config: not_configured and the line lists the names", r["checks"][0]["state"] == "not_configured" and "emulator" in r["checks"][0]["line"])
r, _ = run_probe(cfg=config(stand(name="a"), stand(name="b")))
check("7n two device stands and none named: not_configured (a stand is never guessed)", r["checks"][0]["state"] == "not_configured")
r, _ = run_probe(cfg=config(stand(name="a"), stand(name="b")), name="b")
check_eq("7n' named, it is probed", r["environment"], "b")
r, _ = run_probe(cfg={}, name="")
check("7o no environments at all: not_configured", r["checks"][0]["state"] == "not_configured")

# the table broken: the factory's fault, the web never reads this file
good = surfaces.TABLE_PATH
bad = temp_dir() / "surfaces.json"
bad.write_text("{not json", encoding="utf-8")
surfaces.TABLE_PATH = bad
r, tool = run_probe()
surfaces.TABLE_PATH = good
check("7p a broken table: unknown, factory-owned, no tool and no request", r["verdict"] == "unknown"
      and r["checks"][0]["state"] == "unreadable" and r["block"]["owner"] == "factory" and not tool.calls and not D.HTTP.calls)
cleanup(bad.parent)

# what a person reads
from human_text import problems  # noqa: E402
r, _ = run_probe(TWO, net=Net(OSError("x")))
lines = [c["line"] + " " + c["remedy"] for c in r["checks"]]
check("7q the texts a person reads pass the report form", all(not problems(t, kind="report") for t in lines), str([problems(t, kind="report") for t in lines]))
check("7r no state word is a sentence of the report", not any(re.search(r"\b(no_device|not_ready|tool_error|session_failed)\b", t) for t in lines))

# ---- 8. the command line --------------------------------------------------------------------------------------------

root = temp_dir()
(root / "qa-factory").mkdir()
(root / "qa-factory" / "config.json").write_text(json.dumps(config()), encoding="utf-8")


def cli(*args, **env):
    fakes(Tool(ONE), Net(*([answer(200, READY)] * 3)))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = D.main(list(args))
    return code, out.getvalue(), err.getvalue()


code, out, err = cli("--project-root", str(root), "--json")
check("8a --json: exit 0 and ONE JSON document on stdout", code == 0 and json.loads(out)["verdict"] == "ok" and not err)
code, out, err = cli("--project-root", str(root))
check("8b without --json: the verdict line and a line per check", code == 0 and out.startswith("device stand emulator: ok") and "  device: ok" in out)
fakes(Tool(EMPTY_LIST), Net(answer(200, READY)))
out = io.StringIO()
with contextlib.redirect_stdout(out):
    code = D.main(["--project-root", str(root)])
check("8c a problem: exit 1 and 'what to do' is printed", code == 1 and "what to do:" in out.getvalue())
code, out, err = cli("--project-root", str(root), "--environment", "nope", "--json")
check("8d a wrong environment name: exit 1, not_configured in the JSON", code == 1 and json.loads(out)["checks"][0]["state"] == "not_configured")
code, out, err = cli("--project-root", str(root), "--deep", "--json")
check("8e --deep reaches the session check", json.loads(out)["deep"] is True and [c["name"] for c in json.loads(out)["checks"]][-1] == "session")
empty = temp_dir()
code, out, err = cli("--project-root", str(empty))
check("8f no config: exit 2 and the message names what is expected", code == 2 and "Expected" in err and not out)
real()
child = run_script("device_stand.py", "--project-root", str(empty), "--json")
check("8g REAL: the script runs as a command and refuses with exit 2", child.returncode == 2 and "config.json" in child.stderr)
cleanup(root)
cleanup(empty)

# ---- 9. the registry (A-audit) ------------------------------------------------------------------------------------------

import audit_factory  # noqa: E402
check("9c device_stand is registered in CLI_SCRIPTS", "device_stand" in audit_factory.CLI_SCRIPTS)

real()
finish("test_device_stand")
