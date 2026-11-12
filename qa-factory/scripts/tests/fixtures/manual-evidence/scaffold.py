"""Scaffolding shared by test_manual_capture.py and test_manual_evidence.py (not a test itself).

A task on disk shaped like cmp2's TP1-15045 - real files for the register, the readiness file, the
pinned cases and the plan (rows TS-7, TS-12, TS-15 copied from the live plan beside this file), a fake
controller that answers `state()` the way the real one does, a fake browser and a fake HTTP backend. Nothing
here launches a browser, starts a process or touches the network.
"""
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent.parent
sys.path.insert(0, str(TESTS))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import manual_capture as MC  # noqa: E402
import controller as _controller  # noqa: E402
from role_cli import run_guarded  # noqa: E402
import http_client as _http_client  # noqa: E402

# The recorded request holds the factory's User-Agent (`qa-factory/<installed version>`), so a capture's bytes - and the
# content_hash the web pin keeps - changed with every release. The fake world fixes the version, as it fixes the clock;
# `test_http_client.py` tests the real reader and resets this cache itself. (t-1668)
_http_client._ua_cache = "qa-factory/0.10.6"

# The real selection of the current gate A, taken before any test replaces the class: a FakeController that
# re-implemented it would only prove the fake.
_REAL_CURRENT_GATE_A = _controller.Controller._current_gate_a

TICKET = "TP1-15045"
USER = "qa-user@example.test"
PASSWORD = "SENTINEL-PW-4f9c1b7e"        # a test value of a test .env: it must never reach any output
TOKEN = "SENTINEL-TOKEN-91ad03c2"
SOURCE = "src-1"
CASES = {"ui": "TP1-15045_TC_007", "api": "TP1-15045_TC_012", "impl": "TP1-15045_TC_015"}
CLAIMS = ("\n## Behaviour claims\n\n"
          "| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n"
          "| R-17 | 400 | base:b9c0c4e:workflow.py:989 | 403 | diff:+w.py:158 | yes | Q7 |\n")
R7_R14 = ("| R-7 | Zoom, fit-view and drag-to-pan respond in the visual diff. | ac | — | yes | AC-7 | "
          "diff:testproject1-ui:src/pages/workflows/editor/DiffCanvasControls.tsx:103 | degraded |\n"
          "| R-14 | POST validate writes nothing. | ac | — | yes | AC-14 | "
          "diff:testproject1-backend:src/testproject1/service/guardrail/guardrail_service.py:284 | data-loss |\n")


def probe(profile="e2e-ui", result="matched", identity="build-1"):
    return {"profile_id": profile, "timestamp": "2026-10-01T10:00:00+00:00", "environment_id": "localhost",
            "expected_source_revision": SOURCE, "observed_runtime_identity": identity,
            "evidence_refs": [f"probe/{profile}"], "result": result,
            "provenance": {"technical_verification": True, "source_linkage": "exact",
                           "deployed_source_revision": SOURCE}}


def config(**over):
    cfg = {
        "case_id_form": "{ticket}_TC_{nnn}",
        "environment": {"env_file": "harness/.env", "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"]},
        "environments": [
            {"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173",
             "measured": {"e2e_page_load_s": {"value": 70, "command": "measured by hand", "at": "2026-10-01"}}},
            {"name": "preview", "base_url": "https://stand.example.test/api", "frontend_url": "https://stand.example.test/"}],
        "secret_content_patterns": [
            "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
            "(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|password)\\s*[=:]\\s*['\"][A-Za-z0-9+/_\\-]{16,}['\"]",
            "(?i)aws_secret_access_key",
            "eyJ[A-Za-z0-9_-]{10,}\\.eyJ[A-Za-z0-9_-]{10,}\\."],
        "execution": {"runtime_probes": {
            "e2e-ui": {"argv": ["probe-ui"], "cwd": ".", "timeout_s": 5},
            "api": {"argv": ["probe-api"], "cwd": ".", "timeout_s": 5}}},
        "profiles": [{"profile_id": "e2e-ui", "commands": {
            "one_test": {"argv": ["poetry", "run", "pytest", "<test-file>"], "cwd": "."}}}],
    }
    cfg.update(over)
    return cfg


class Clock:
    """A clock that moves one second per call: attempt timestamps are ordered and never equal."""

    def __init__(self):
        self.moment = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.moment += timedelta(seconds=1)
        return self.moment


SIGN_IN_URL = "http://localhost:5173/auth/sign-in"
HOME_URL = "http://localhost:5173/"
SESSION_COOKIE = "testproject1_access_token"


class FakeBrowser:
    """The backend `manual_capture.PlaywrightBackend` stands in for; scripted, no browser.

    The login half (t-292): after `login` the page is looked at once per POLL (`current_url()` starts a poll; the
    other primitives answer for that poll) and a clock moves only when the loop `pause`s - tests put
    `fake.monotonic` into `MC.MONOTONIC`, so a 100 s limit costs no time. Defaults: lands at poll 0 on `HOME_URL`
    with the session cookie and the sign-in field gone, so every older check keeps its meaning.
      lands_at      the first poll that has the landing URL, the cookie and the field gone (default 0)
      urls          the URL of poll 0, 1, ... (the last one repeats); overrides what `lands_at` makes
      cookies_at    the first poll with the session cookie (None: never)
      field_gone_at the first poll with the username field not visible (None: never)
      words         what `page_words()` says
      errors_at     the polls whose `cookie_names` / `field_visible` raise StepFailed
      login_error   raised by `login` itself (a failure BEFORE the submit)
    `calls` is what the steps and the login did (never the polls); `events` is everything, in order."""

    def __init__(self, elapsed=None, missing=(), reads=None, *, lands_at=0, urls=None, cookies_at="lands_at",
                 field_gone_at="lands_at", words="Welcome to Test Project 1 Please, sign in to continue.", errors_at=(),
                 login_error=None, cookie=SESSION_COOKIE):
        self.elapsed, self.missing, self.reads = dict(elapsed or {}), set(missing), dict(reads or {})
        self.calls, self.events, self.opened, self.closed, self.shots, self.credentials_seen = [], [], None, False, 0, None
        self.urls = list(urls) if urls is not None else [SIGN_IN_URL] * lands_at + [HOME_URL]
        self.cookies_at = lands_at if cookies_at == "lands_at" else cookies_at
        self.field_gone_at = lands_at if field_gone_at == "lands_at" else field_gone_at
        self.words, self.errors_at, self.login_error, self.cookie = words, set(errors_at), login_error, cookie
        self.polls, self.now = 0, 0.0
        self.allowed, self.failing, self.on_call = set(), {}, {}

    def _call(self, *entry):
        self.calls.append(entry)
        self.events.append(entry)
        for glob, method, url in self.on_call.get(entry, ()):      # a call of the page that sends a request (EP1-30)
            self.hit(glob, method, url)

    def _t(self, word, arg=""):
        return self.elapsed.get(f"{word}:{arg}", self.elapsed.get(word, 0.2))

    def monotonic(self):
        return self.now

    def open(self, timeout_s, allowed_hosts, local_storage=None, element_wait_s=None):
        self.opened = (timeout_s, sorted(allowed_hosts), local_storage, element_wait_s)
        self.allowed = set(allowed_hosts)

    # --- a failing dependency (EP1-30): the record the real backend keeps; `on_call[(word, arg...)] = [(glob, method, url)]`
    # sends requests when that step runs, `hit` sends one by hand
    def allowed_hosts(self):
        return set(self.allowed)

    def hit(self, glob, method="GET", url="http://localhost:5173/api/x"):
        record = self.failing.get(glob)
        if record and record["active"]:
            record["hits"] += 1
            if len(record["rows"]) < 50:
                record["rows"].append({"method": method, "url": url})

    def fail_request(self, glob, how):
        self._call("fail_request", glob, how)
        self.failing[glob] = {"how": str(how), "hits": 0, "rows": [], "active": True}
        return self._t("fail_request", glob)

    def restore_request(self, glob):
        self._call("restore_request", glob)
        record = self.failing.get(glob)
        if not record or not record["active"]:
            raise MC.StepFailed(f"no failing request is active for {glob}")
        record["active"] = False
        return self._t("restore_request", glob)

    def drain_failures(self):
        return {g: {**r, "rows": list(r["rows"])} for g, r in self.failing.items()}

    def login(self, recipe, credentials, frontend_url):
        self.credentials_seen = (credentials.username, credentials.password)
        self._call("login", frontend_url)
        if self.login_error is not None:
            raise self.login_error
        return 0.1

    # --- what the landing loop looks at (one poll = one `current_url`) -------------------------------------------
    def current_url(self):
        poll = self.polls
        self.polls += 1
        url = self.urls[min(poll, len(self.urls) - 1)]
        self.events.append(("poll", poll, url))
        return url

    def _poll(self):
        return self.polls - 1

    def cookie_names(self):
        if self._poll() in self.errors_at:
            raise MC.StepFailed("Execution context was destroyed, most likely because of a navigation")
        return {self.cookie} if self.cookies_at is not None and self._poll() >= self.cookies_at else set()

    def field_visible(self, row):
        if self._poll() in self.errors_at:
            raise MC.StepFailed("Execution context was destroyed, most likely because of a navigation")
        return not (self.field_gone_at is not None and self._poll() >= self.field_gone_at)

    def page_words(self):
        self.events.append(("words",))
        return self.words

    def pause(self, seconds):
        # Real time always passes, even for a pause of nothing (a microsecond here); and a loop that never ends on this
        # fake - its clock moves only by pauses - fails loudly instead of hanging the run.
        self.pauses = getattr(self, "pauses", 0) + 1
        assert self.pauses < 100_000, "the landing loop never ended: its deadline is not reached"
        self.now += max(seconds, 1e-6)
        self.events.append(("pause", seconds))

    def goto(self, url):
        self._call("goto", url)
        return self._t("goto", url)

    def click(self, selector):
        self._call("click", selector)
        if selector in self.missing:
            raise MC.StepFailed(f"no element matches {selector}")
        return self._t("click", selector)

    def fill(self, selector, text):
        self._call("fill", selector, text)
        return self._t("fill", selector)

    def type_chars(self, selector, text, delay_ms, settle_ms=0, continued=False):
        """(rows, seconds, focus_s): the field keeps every character and its focus unless `typed[selector]` scripts the rows;
        the time of the whole step is `elapsed["type"]`, of the focus alone `elapsed["focus"]` (EP1-29)."""
        self._call("type", selector, text, delay_ms, settle_ms)
        if selector in self.missing:
            raise MC.StepFailed(f"no element matches {selector}")
        rows = getattr(self, "typed", {}).get(selector)
        if rows is None:
            rows = [{"n": i, "value": text[:i], "focus": True} for i in range(1, len(text) + 1)]
            rows.append({"n": "settled", "value": text, "focus": True})
        return rows, self._t("type", selector), self._t("focus", selector)

    def press_key(self, selector, key, continued=False):
        self._call("press", selector, key)
        if selector in self.missing:
            raise MC.StepFailed(f"no element matches {selector}")
        row = getattr(self, "pressed", {}).get((selector, key)) or {"n": key, "value": "", "focus": True, "focused_before": True}
        return row, self._t("press", selector), self._t("focus", selector)

    def paste_text(self, selector, text, continued=False):
        self._call("paste", selector, text)
        if selector in self.missing:
            raise MC.StepFailed(f"no element matches {selector}")
        row = getattr(self, "pasted", {}).get(selector) or {"n": "paste", "value": text, "focus": True, "focused_before": True}
        return row, self._t("paste", selector), self._t("focus", selector)

    def drag(self, selector, dx, dy):
        self._call("drag", selector, dx, dy)
        if selector in self.missing:
            raise MC.StepFailed(f"no element matches {selector}")
        return self._t("drag", selector)

    def wait_ms(self, ms):
        self._call("wait_ms", ms)
        return ms / 1000

    def wait_selector(self, selector):
        self._call("wait_selector", selector)
        return self._t("wait", selector)

    def read(self, selector, mode):
        self._call("read", selector, mode)
        if selector in self.missing:
            raise MC.StepFailed(f"no element matches {selector}")
        return self.reads.get((selector, mode), self.reads.get(selector, "value")), self._t("read", selector)

    def screenshot(self, path):
        self._call("screenshot", Path(path).name)
        Path(path).write_bytes(b"\x89PNG-fake-" + str(self.shots).encode())
        self.shots += 1
        return self._t("screenshot")

    def close(self):
        self.closed = True
        self.events.append(("close",))


class FakeHttp:
    """`routes`: {(METHOD, url): HttpResult | callable(headers, body) -> HttpResult}."""

    def __init__(self, routes=None):
        self.routes, self.calls = dict(routes or {}), []

    def request(self, method, url, headers, body, timeout_s):
        self.calls.append((method, url, dict(headers), body, timeout_s))
        route = self.routes.get((method, url))
        if route is None:
            return MC.HttpResult(404, [("Content-Type", "text/plain")], b"no route", 0.01)
        return route(headers, body) if callable(route) else route


def ok_json(obj, status=200, headers=(), elapsed=0.05):
    return MC.HttpResult(status, [("Content-Type", "application/json"), *headers],
                         json.dumps(obj, ensure_ascii=False).encode("utf-8"), elapsed)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeController:
    """What `Controller(task)` answers in `prepare` and `build`: `state()`, the content check, and the REAL
    `_current_gate_a` (so two approved records choose the way the controller chooses)."""
    STATE = {}

    def __init__(self, task_root):
        self.task_root = task_root

    def state(self):
        return json.loads(json.dumps(FakeController.STATE))

    def _validate_gate_a_content_current(self, state):
        return None

    def _current_gate_a(self, state):
        return _REAL_CURRENT_GATE_A(self, state)


class Task:
    def __init__(self, project: Path, task: Path, cfg: dict, plan_rows: list):
        self.project, self.task, self.cfg, self.plan_rows = project, task, cfg, plan_rows

    def write_plan(self, rows=None):
        rows = self.plan_rows if rows is None else rows
        (self.task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")

    def row(self, row_id):
        return next(r for r in self.plan_rows if r["id"] == row_id)

    def state(self, *, gate_ids=("gateA-1",), scope=None, dispatch_status="running"):
        decisions = {gid: {"id": gid, "gate": "A", "status": "approved", "source_revision": SOURCE} for gid in gate_ids}
        FakeController.STATE = {
            "revision": 7, "source_revision": SOURCE, "decisions": decisions,
            "dispatches": {"S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "status": dispatch_status,
                                              "scope": list(scope if scope is not None else CASES.values())}}}

    def patched(self):
        """`with task.patched():` - the controller is the fake for the duration."""
        return mock.patch("controller.Controller", FakeController)

    def attempt_dir(self, case, attempt="a1"):
        return MC.case_root(self.task, case) / attempt


def make_task(*, claims=False, cfg=None, manual=("ui",), readiness=True):
    """A task folder under a fresh temp project. `manual` names the cases (keys of CASES) the plan makes
    executable by hand: ui -> TS-7 (OB-7 manual-agent, policy ui), api -> TS-12 (disposition and decision
    manual-agent, policy api), impl -> TS-15 (the implementation-only one: R-19, resolved/new)."""
    project = Path(tempfile.mkdtemp(prefix="qa-manual-capture-")).resolve()   # resolved: Windows temp is an 8.3 short path
    task = project / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    config_data = cfg if cfg is not None else config()
    (project / "qa-factory" / "config.json").write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    (project / "harness").mkdir()
    (project / "harness" / ".env").write_text(
        f"PROJECT_NAME=x\nAUTH_USERNAME={USER}\nAUTH_PASSWORD={PASSWORD}\n", encoding="utf-8")
    oracle = harness.FIXTURES / "oracle-provenance"
    register = (oracle / "requirements-register.md").read_text(encoding="utf-8")
    register = register.replace("| R-13 |", R7_R14 + "| R-13 |", 1)
    if claims:
        register += CLAIMS
    (task / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
    if readiness:
        shutil.copyfile(oracle / "requirements-readiness.json", task / "work" / "requirements-readiness.json")
    rows = json.loads((HERE / "test-plan-rows.json").read_text(encoding="utf-8"))["rows"]
    for row in rows:
        ob = row["coverage_obligations"][0]
        if row["id"] == "TS-7" and "ui" in manual:
            ob["decision"] = "manual-agent"
        if row["id"] == "TS-12" and "api" in manual:
            row.update(disposition="manual-agent", evidence_policy="api")
            ob.update(decision="manual-agent", evidence_policy="api")
        if row["id"] == "TS-15" and "impl" in manual:
            row.update(disposition="manual-agent", evidence_policy="api")
            ob.update(decision="manual-agent", evidence_policy="api")
    links = []
    sources = {CASES["ui"]: HERE / "TP1-15045_TC_007.md", CASES["api"]: HERE / "TP1-15045_TC_012.md",
               CASES["impl"]: oracle / "TP1-15045_TC_015.md"}
    for case, source in sources.items():
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        version = "cv_" + digest[:20]
        pinned = task / "state" / "case-versions" / case / f"{version}.md"
        pinned.parent.mkdir(parents=True, exist_ok=True)
        pinned.write_bytes(data)
        links.append({"case_id": case, "version": version, "area": "workflow-visual-diff",
                      "path": pinned.relative_to(task).as_posix(), "content_hash": digest})
    (task / "state" / "story-case-links.json").write_text(json.dumps({"links": links}), encoding="utf-8")
    scaffold = Task(project, task, config_data, rows)
    scaffold.write_plan()
    scaffold.state()
    return scaffold


def cleanup(scaffold):
    harness.cleanup(scaffold.project)


def run(argv, main=None, command=None):
    """(exit code, stdout, stderr) of `manual_capture.main(argv)` as a role's call would end."""
    out, err = io.StringIO(), io.StringIO()
    entry = main or MC.main
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = run_guarded(command or f"manual_capture.py {argv[0]}", lambda: entry(argv), stream=err)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def tree_text(root: Path) -> str:
    """Every byte under `root` that is text, joined: where a leaked secret would show."""
    parts = []
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            parts.append(path.read_bytes().decode("utf-8", "replace"))
    return "\n".join(parts)
