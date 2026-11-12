#!/usr/bin/env python3
"""t-2024: a walk with two actors starts (live defect S6-qa-runner-10: 'Playwright Sync API inside the asyncio loop').

The cause: each actor opened its own `sync_playwright().start()` in the server's one thread; the second is refused. The fix: one driver per
process (`manual_capture._driver_acquire`), one persistent profile per actor, the driver stopped with the last browser.
REAL chromium on a loopback site that sets a cookie per user; skipped (said, not silent) when playwright or its chromium is not installed.
Red before the fix: with `_driver_acquire` starting a driver per call, test_two_actors_start_and_keep_separate_cookies fails.

Run: python -B scripts/tests/test_walk_two_actors.py    or    python -m pytest -p no:cacheprovider scripts/tests/test_walk_two_actors.py -q
"""
import http.server
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import manual_capture as MC  # noqa: E402


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if path == "/login":
            self.send_header("Set-Cookie", f"sid={query.split('=', 1)[-1]}; Path=/")
        self.end_headers()
        cookie = self.headers.get("Cookie") or "none"
        self.wfile.write(f"<html><body><p>cookie: {cookie}</p></body></html>".encode())

    def log_message(self, *args):
        pass


def chromium_missing() -> str:
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            pw.chromium.launch(headless=True).close()
        finally:
            pw.stop()
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:80]}"
    return ""


class Rig:
    def __enter__(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.tmp = tempfile.TemporaryDirectory()
        self.hosts = {MC.host_key(self.base)}
        self.backends = {}
        return self

    def open(self, actor):
        backend = MC.PlaywrightBackend()
        self.backends[actor] = backend
        backend.open(20, self.hosts, None, 5, profile_dir=Path(self.tmp.name) / actor)
        return backend

    def sign_in(self, actor):
        self.backends[actor].goto(f"{self.base}/login?u={actor}")

    def words(self, actor):
        self.backends[actor].goto(f"{self.base}/whoami")
        return self.backends[actor].page_words()

    def __exit__(self, *exc):
        for backend in self.backends.values():
            backend.close()
        self.server.shutdown()
        try:
            self.tmp.cleanup()
        except OSError:
            pass


def test_two_actors_start_and_keep_separate_cookies():
    with Rig() as rig:
        rig.open("user")
        rig.open("admin")                       # the second start: refused before the fix
        rig.sign_in("user")
        rig.sign_in("admin")
        user, admin = rig.words("user"), rig.words("admin")
        assert "sid=user" in user and "sid=admin" not in user, user
        assert "sid=admin" in admin and "sid=user" not in admin, admin


def test_steps_alternate_between_actors():
    with Rig() as rig:
        rig.open("user")
        rig.open("admin")
        rig.sign_in("user")
        rig.sign_in("admin")
        for _ in range(2):
            assert "sid=user" in rig.words("user")
            assert "sid=admin" in rig.words("admin")


def test_close_ends_both():
    with Rig() as rig:
        first, second = rig.open("user"), rig.open("admin")
        first.close()
        assert MC._DRIVER["pw"] is not None, "the driver stops only with the last browser"
        rig.sign_in("admin")
        assert "sid=admin" in rig.words("admin")     # the second actor still works after the first closed
        second.close()
        assert MC._DRIVER["pw"] is None and MC._DRIVER["users"] == 0
        assert first._pw is None and second._pw is None


TESTS = [test_two_actors_start_and_keep_separate_cookies, test_steps_alternate_between_actors, test_close_ends_both]
_WHY = chromium_missing()

if _WHY:                                           # the marker of the recorder tests does not exist: chromium is checked here, by launching it
    try:
        import pytest
        pytestmark = pytest.mark.skip(reason=f"no chromium: {_WHY}")
    except ImportError:
        pass

if __name__ == "__main__":
    if _WHY:
        print(f"SKIP: no chromium ({_WHY})")
        # What needs no browser still runs: the one-driver-per-process seam the browser tests exercise must exist.
        assert callable(MC._driver_acquire) and {"pw", "users"} <= set(MC._DRIVER), "the one-driver seam is missing"
        print("=== test_walk_two_actors: 1/1 ok === (the browser tests are skipped above)")
        sys.exit(0)
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failed else 0)
