#!/usr/bin/env python3
"""t-1765 X3 (F-X3-4, F-X3-5): the log of the requests a page sent (`requests-seen.txt`) and the stand lease of every capture call.

R1 a stand request is logged without its query, a foreign host is not   R2 a repeat is one line `xN`   R3 the ceiling `max_logged`
R4 a line that matches a secret pattern is counted, not kept   R5 zero requests: the file says so + a limitation (never silence)
R6 a backend that cannot list requests (a device) writes no file and says so; an older backend is left alone
L1 a `ui` call holds the lease (job `manual:<case>:<attempt>`, the stand's name) and releases it
L2 a held stand: `stand_busy`, exit 3, nothing opened, no attempt folder   L3 a lease that cannot be used: a stderr note, the call goes on
L4 `http` and the shared cycle of `app` hold it too; released on an exception
Mutations -> killing key: query kept in the log -> R1; no `xN` -> R2; no ceiling -> R3; no log at zero -> R5; the lease without
`StandBusy` -> L2; the lease not released on an exception -> L4.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_manual_capture as T  # noqa: E402  (its fixtures; main() runs only under __main__)
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

import stand_lease  # noqa: E402

S, MC = T.S, T.MC
STEPS = f"goto {T.UI}\ncapture post_action completion\n"
API = "http://localhost:5173/api"
FOREIGN = "https://cdn.example.test/lib.js"


class SeenBrowser(S.FakeBrowser):
    """The fake with the one thing the real backend gained: the list of requests its page sent."""

    def __init__(self, seen=(), **kw):
        super().__init__(**kw)
        self.seen = list(seen)

    def drain_requests(self):
        return {"rows": [{"method": m, "url": u} for m, u in self.seen], "count": len(self.seen)}


class Device(S.FakeBrowser):
    def drain_requests(self):
        return None


def log_of(t):
    """(text lines of requests-seen.txt | None, the summary)."""
    files = list(t.attempt_dir(T.UI_CASE).glob("*requests-seen*"))
    return (files[0].read_text(encoding="utf-8").splitlines() if files else None)


def run(t, browser, steps=STEPS):
    code, out, err, _ = T.ui_run(t, steps=steps, browser=browser)
    return code, json.loads(out) if out.strip() else {}, err


def r_log():
    t = S.make_task()
    try:
        browser = SeenBrowser([("GET", f"{API}/orders?token=abc&page=2"), ("GET", f"{API}/products/7"), ("POST", f"{API}/basket"),
                               ("GET", FOREIGN)])
        code, summary, err = run(t, browser)
        lines = log_of(t)
        check_eq("R1 the call ends ok", code, 0)
        check_eq("R1 three stand requests, no query, no foreign host", lines,
                 [f"GET {API}/orders", f"GET {API}/products/7", f"POST {API}/basket"])
        check("R1 the file is in the summary's captures as a log", any(c["kind"] == "log" and "requests-seen" in c["path"]
                                                                       for c in summary["captures"]))
        check_eq("R1 a page that sent requests adds no limitation", summary["limitations"], [])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        run(t, SeenBrowser([("GET", f"{API}/x"), ("GET", f"{API}/x?a=1"), ("GET", f"{API}/x"), ("PUT", f"{API}/x")]))
        check_eq("R2 a repeated pair (the query is not part of it) is one line with its count", log_of(t),
                 [f"GET {API}/x x3", f"PUT {API}/x"])
    finally:
        S.cleanup(t)
    top = MC.spec()["requests_seen"]["max_logged"]
    for count, label in ((top, "AT the ceiling"), (top + 1, "BEYOND the ceiling"), (top + 7, "7 beyond")):
        t = S.make_task()
        try:
            run(t, SeenBrowser([("GET", f"{API}/p{i:03d}") for i in range(count)]))
            lines = log_of(t)
            check_eq(f"R3 {label} ({count} pairs): lines kept", len([x for x in lines if x.startswith("GET")]), top)
            check_eq(f"R3 {label}: the cut is named", [x for x in lines if "more" in x], [] if count == top else [f"... and {count - top} more"])
        finally:
            S.cleanup(t)
    t = S.make_task()
    try:
        run(t, SeenBrowser([("GET", f"{API}/ok"), ("GET", f"{API}/aws_secret_access_key")]))
        lines = log_of(t)
        check_eq("R4 a secret-looking address is counted, not kept", lines,
                 [f"GET {API}/ok", "1 request line(s) not stored: they match secret_content_patterns"])
        check_not_in("R4 ... and nowhere in the attempt", "aws_secret_access_key", "\n".join(
            p.read_text(encoding="utf-8", errors="replace") for p in t.attempt_dir(T.UI_CASE).glob("*.txt")))
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        code, summary, err = run(t, SeenBrowser([("GET", FOREIGN)]))
        check_eq("R5 no request to a stand host: the file is written and says zero", log_of(t), ["requests seen: 0"])
        check("R5 ... and the attempt says zero is not 'none sent'", any("zero here is not" in x for x in summary["limitations"]),
              str(summary["limitations"]))
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        # R7 (F5): every pair withheld as secret-like -> the log does NOT say zero, it says how many there were
        run(t, SeenBrowser([("GET", f"{API}/aws_secret_access_key")]))
        check_eq("R7 all pairs withheld: no `requests seen: 0`, the count and the withheld line", log_of(t),
                 ["requests seen: 1 pair(s), none listed below", "1 request line(s) not stored: they match secret_content_patterns"])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        # R7 (F5): max_logged 0 with pairs seen -> the same; the cut is named
        real_spec = MC.spec

        def no_room():
            data = real_spec()
            data["requests_seen"]["max_logged"] = 0
            return data
        with patch.object(MC, "spec", no_room):
            run(t, SeenBrowser([("GET", f"{API}/a"), ("GET", f"{API}/b")]))
        check_eq("R7 max_logged 0: two pairs seen, none listed, the cut named", log_of(t),
                 ["requests seen: 2 pair(s), none listed below", "... and 2 more"])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        code, summary, err = run(t, Device())
        check_eq("R6 a backend that cannot list requests writes no file", log_of(t), None)
        check("R6 ... and the attempt says the log is a gap", any("not logged" in x for x in summary["limitations"]),
              str(summary["limitations"]))
        code, summary, err = run(t, S.FakeBrowser())
        check_eq("R6 control: an older backend with no `drain_requests` is left alone (no limitation)", summary["limitations"], [])
    finally:
        S.cleanup(t)


class Recorder:
    """stand_lease.hold with a record of how it was called and what the lease file held while the call ran."""

    def __init__(self, project):
        self.calls, self.during, self.project = [], [], project
        self.real = stand_lease.hold

    def __call__(self, project_root, job_id, environment="", wait_s=1800, poll_s=5):
        self.calls.append((job_id, environment))
        return self.real(project_root, job_id, environment, wait_s, poll_s)

    def leases(self):
        path = stand_lease._paths(self.project)[0]
        return sorted(json.loads(path.read_text(encoding="utf-8"))["leases"]) if path.is_file() else []


class Watching(S.FakeBrowser):
    """Reads the lease file while the call is inside its steps."""

    def __init__(self, rec, **kw):
        super().__init__(**kw)
        self.rec = rec

    def goto(self, url):
        self.rec.during.append(self.rec.leases())
        return super().goto(url)


SERIAL = {"parallel": False}      # the stand takes one run at a time (what onboarding writes): `run_suite.hold_stand` leases only then
HERE_ROOT = {"root": None}        # `run_suite.hold_stand` asks hooklib for the project root (the cwd's); a test project is not the cwd


def stand_task(run=SERIAL, **kw):
    t = S.make_task(cfg=S.config(run=run), **kw)
    HERE_ROOT["root"] = t.project
    return t


def l_lease():
    t = stand_task()
    try:
        rec = Recorder(t.project)
        with patch.object(stand_lease, "hold", rec):
            code, summary, err = run(t, Watching(rec))
        check_eq("L1 the call ends ok", code, 0)
        check_eq("L1 hold was asked once, for the job `manual:<case>:<attempt>` on the stand's name", rec.calls,
                 [(f"manual:{T.UI_CASE}:a1", "localhost")])
        check_eq("L1 the lease file held the stand while the steps ran", rec.during, [["localhost"]])
        check_eq("L1 and holds nothing after the call", rec.leases(), [])
    finally:
        S.cleanup(t)
    # L2: another job holds the stand; the wait is 0 (run.manual_stand_wait_s), so the call answers at once
    t = stand_task({**SERIAL, "manual_stand_wait_s": 0})
    try:
        browser = S.FakeBrowser()
        with stand_lease.hold(t.project, "other-job", "localhost", 0):
            code, out, err, _ = T.ui_run(t, steps=STEPS, browser=browser)
        answer = json.loads(out)
        check_eq("L2 a held stand: exit 3", code, 3)
        check_eq("L2 ... one JSON object that says stand_busy and who holds it", (answer["status"], answer["holder"]["job_id"]),
                 ("stand_busy", "other-job"))
        check_eq("L2 ... nothing was opened", browser.opened, None)
        check("L2 ... and no attempt folder was made", not t.attempt_dir(T.UI_CASE).exists())
        code, out, err, _ = T.ui_run(t, steps=STEPS, browser=S.FakeBrowser())
        check_eq("L2 control: the stand free again, the same call runs (exit 0)", code, 0)
    finally:
        S.cleanup(t)
    # L2b: ONE printer of the answer (AR-18): the manual capture has no second text of `stand_busy`
    check_eq("L2 manual_capture.py carries no printer of the stand_busy answer (a dict with the key `status`)",
             'json.dumps({"status": "stand_busy"' in Path(MC.__file__).read_text(encoding="utf-8"), False)
    check_eq("L2 the wait of a role's call is short and from data (default 120 s), a project's key wins",
             (MC._manual_stand_wait_s({}), MC._manual_stand_wait_s({"run": {"manual_stand_wait_s": 7}}),
              MC._manual_stand_wait_s({"run": {"manual_stand_wait_s": "x"}})), (120, 7, 120))
    # L3: a lease that cannot be used is the factory's bookkeeping, not the call's problem. The REAL shape: `stand_lease.hold` does not
    # raise for lock or disk trouble, it yields `lease_error`; here the lease file is a directory, so the write fails for real
    t = stand_task()
    try:
        broken =stand_lease._paths(t.project)[0]
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.mkdir()
        code, summary, err = run(t, S.FakeBrowser())
        check_eq("L3 the call goes on (exit 0)", code, 0)
        check_in("L3 stderr carries the note", "STAND LEASE (note, not a block)", err)
        check_in("L3 ... and names the lease file", broken.name, err)
        check_eq("L3 ... once", err.count("STAND LEASE (note, not a block)"), 1)
    finally:
        S.cleanup(t)
    # L3b: the other shape - `hold` raising - is noted once, by the shared helper
    t = stand_task()
    try:
        with patch.object(stand_lease, "hold", side_effect=OSError("disk gone")):
            code, summary, err = run(t, S.FakeBrowser())
        check_eq("L3b a raising hold: the call goes on (exit 0)", code, 0)
        check_eq("L3b ... one note", err.count("STAND LEASE (note, not a block)"), 1)
    finally:
        S.cleanup(t)


def l_http_and_cycle():
    t = stand_task(manual=("api",))
    try:
        get = f"{T.LOCAL}/v1/workflows/w1"
        http = S.FakeHttp({("POST", f"{T.LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                           ("GET", get): S.ok_json({"id": "w1"})})
        rec = Recorder(t.project)
        with patch.object(stand_lease, "hold", rec):
            code, out, err = T.http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action")
        check_eq("L4 http: the call ends ok", code, 0)
        check_eq("L4 http: it holds the lease of the stand", [c[1] for c in rec.calls], ["localhost"])
        check_eq("L4 http: and releases it", rec.leases(), [])
    finally:
        S.cleanup(t)
    t = stand_task({**SERIAL, "manual_stand_wait_s": 0}, manual=("api",))
    try:
        http = S.FakeHttp({})
        with stand_lease.hold(t.project, "other-job", "localhost", 0):
            code, out, err = T.http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action")
        check_eq("L4 http: a held stand answers stand_busy, exit 3", (code, json.loads(out)["status"]), (3, "stand_busy"))
        check_eq("L4 http: ... and nothing was sent", http.calls, [])
    finally:
        S.cleanup(t)
    # the cycle `ui` and `app` share: lease held for the whole cycle, released when the session raises
    t = stand_task()
    try:
        for command in ("ui", "app"):
            rec = Recorder(t.project)
            attempt = MC.Attempt(t.task, T.UI_CASE, f"a{40 if command == 'ui' else 41}", t.cfg)
            args = SimpleNamespace(case=T.UI_CASE)
            stand = {"name": "localhost"}

            def boom(backend):
                raise RuntimeError("the session broke")
            with patch.object(stand_lease, "hold", rec), patch.object(MC, "stand_probe", lambda *a, **k: None):
                try:
                    MC._session_cycle(attempt, S.FakeBrowser(), args, "e2e-ui", t.cfg, t.project, stand, command, boom)
                    raised = False
                except RuntimeError:
                    raised = True
            check_eq(f"L4 {command}: the cycle held the lease, for its attempt", rec.calls, [(f"manual:{T.UI_CASE}:{attempt.name}", "localhost")])
            check_eq(f"L4 {command}: the exception passes through ...", raised, True)
            check_eq(f"L4 {command}: ... and the lease is released", rec.leases(), [])
    finally:
        S.cleanup(t)


def main():
    r_log()
    import run_suite
    with patch.object(run_suite, "project_root", lambda: HERE_ROOT["root"]):
        l_lease()
        l_http_and_cycle()
    finish("test_manual_requests_seen")


if __name__ == "__main__":
    main()
