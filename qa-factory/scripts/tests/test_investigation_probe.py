#!/usr/bin/env python3
"""P2 M3: `investigation_probe.py http | record` - the bounded, read-only probe of the S7 investigation pass.

Everything is in-process with fakes: the stand is a `FakeHttp`, the controller's state is a dict, and the modules that land
later (`investigation`, `exploratory_findings`, `controller.s7_part_of`, `controller.lineage_root`) are FAKES installed for
the duration of one world (`World`). Absence is CONSTRUCTED (an attribute hidden, a function left out), never read from the
tree, so the keys stay true after the integration lands. The fake `budget_problems` returns what the test sets and never
re-implements M2's rule. The clock is `investigation_probe.NOW`, stepped by the test. No socket, no subprocess.

Keys (spec t-095 section G): K-M3-1 / 1b / 1c, 2 / 2b, 3, 4, 5, 6 / 6b, 7 (+7c), 7b, 8 / 8b, 20u, K-T1, K-B0, K-DMG / K-STATE /
K-PIPE, K-SEC (+ K-F5: a sent request whose answer is not saved is counted), K-REF / K-ADV.
The census rows of `test_task_root_parsers.py` (investigation_probe) are that file's.
"""
import contextlib
import json
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish  # noqa: E402

import controller as CT  # noqa: E402
import exploratory_findings as EFREAL  # noqa: E402       # the fake register's `chains` are the real derivation
import investigation_probe as IP  # noqa: E402

REAL_LINEAGE_ROOT = CT.lineage_root          # the landed survivor: the probe's pass key is computed by IT, not by a fake

MC = S.MC
LOCAL = "http://localhost:8080"
GET = f"{LOCAL}/v1/workflows/w1"
LOGIN = f"{LOCAL}/v1/local-auth/login"
D = "S7-analyst-1"
T0 = datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc)
LETTERS = "ABCDEFGH"
SECRET_WORD = "aws_secret_access_key"             # matches a secret_content_patterns entry of scaffold.config()
CYRILLIC_E = chr(0x415)
BUDGET = PLUGIN_ROOT / "references" / "investigation-budget.json"


def running(**over):
    return dict({"id": D, "stage": "S7", "purpose": "investigation", "status": "running"}, **over)


def default_targets():
    return {"unresolved": [{"id": f"case-{c}", "carrier": "work/test-plan.json", "evidence": []} for c in LETTERS],
            "resolved": [("case-R", "triage verdict APP_BUG with evidence")]}


class Stand(S.FakeHttp):
    """The stand: the login route is set, every read-only call is answered, anything else is a 404 (and is recorded)."""

    def __init__(self, routes=None):
        super().__init__({("POST", LOGIN): S.ok_json({"access_token": S.TOKEN}), **(routes or {})})

    def request(self, method, url, headers, body, timeout_s):
        if (method, url) not in self.routes and method in ("GET", "HEAD", "OPTIONS"):
            self.calls.append((method, url, dict(headers), body, timeout_s))
            return S.ok_json({"seen": url})
        return super().request(method, url, headers, body, timeout_s)

    def probes(self):
        return [c for c in self.calls if c[1] != LOGIN]


class Register:
    """The fake findings register: `read` and `append` with the chain rule of the real one (one linear chain per target)."""

    def __init__(self, lines=None):
        self.lines, self.calls = list(lines or []), []

    def read(self, task):
        active = {}
        for line in self.lines:
            key = line["origin"]["target"]
            if line["op"] == "withdraw":
                active.pop(key, None)
            else:
                active[key] = line
        return {"lines": list(self.lines), "unreadable": [], "active": active}

    def append(self, task, line, *, by):
        self.calls.append((json.loads(json.dumps(line)), by))
        key = line["origin"]["target"]
        current = self.read(task)["active"].get(key)
        if line["op"] == "add" and any(x["origin"]["target"] == key for x in self.lines):
            raise ValueError(f"target {key} already has a line; use correct")
        if line["op"] == "correct" and (current is None or current["id"] != line["corrects"]["id"]):
            raise ValueError("not an active line")
        stored = dict(line, id=f"EX-{len(self.lines) + 1}")
        self.lines.append(stored)
        return stored["id"]


class Clock:
    def __init__(self):
        self.moment = T0

    def __call__(self):
        return self.moment

    def at(self, minutes=0, seconds=0):
        self.moment = T0 + timedelta(minutes=minutes, seconds=seconds)


def s7_part_of(record):
    return "investigation" if isinstance(record, dict) and record.get("purpose") == "investigation" else "other"


class World:
    """One story folder with every fake installed. `hide` names the functions that are NOT installed."""

    def __init__(self, *, dispatches=None, targets=None, pipeline=None, cfg=None, budget=None, hide=(), routes=None,
                 problems=(), register_lines=None, budget_path=None):
        self.t = S.make_task(cfg=cfg)
        self.task = self.t.task
        self.dispatches = dispatches if dispatches is not None else {D: running()}
        self.targets = targets if targets is not None else default_targets()
        self.problems, self.seen, self.state_error = list(problems), [], None
        self.stand, self.clock, self.register = Stand(routes), Clock(), Register(register_lines)
        (self.task / "pipeline.json").write_text(json.dumps(pipeline if pipeline is not None else
                                                             {"gates": {"A": {"status": "approved"}}}), encoding="utf-8")
        self.budget_path = budget_path
        if budget is not None:
            self.budget_path = self.t.project / "budget-copy.json"
            self.budget_path.write_text(json.dumps(budget), encoding="utf-8")
        self.hide, self.stack = set(hide), contextlib.ExitStack()

    def __enter__(self):
        world = self

        class Ctl:
            def __init__(self, task_root):
                pass

            def state(self):
                if world.state_error:
                    raise world.state_error
                return json.loads(json.dumps({"dispatches": world.dispatches}))

        def budget_problems(budget):
            world.seen.append(budget)
            return list(world.problems)

        def pass_members(state):
            return [d for d in state["dispatches"].values()
                    if d.get("stage") == "S7" and s7_part_of(d) == "investigation" and d.get("status") not in CT.DISCOUNTED]

        def unresolved_targets(task, budget):
            return json.loads(json.dumps(world.targets))

        inv = types.ModuleType("investigation")
        ex = types.ModuleType("exploratory_findings")
        for module, name, function in ((inv, "budget_problems", budget_problems), (inv, "pass_members", pass_members),
                                       (inv, "unresolved_targets", unresolved_targets),
                                       (ex, "read", self.register.read), (ex, "append", self.register.append),
                                       (ex, "chains_of", EFREAL.chains_of)):
            if f"{module.__name__}.{name}" not in self.hide:
                setattr(module, name, function)
        push = self.stack.enter_context
        push(mock.patch("controller.Controller", Ctl))
        for name, function in (("s7_part_of", s7_part_of), ("lineage_root", REAL_LINEAGE_ROOT)):
            push(mock.patch.object(CT, name, None if f"controller.{name}" in self.hide else function, create=True))
        push(mock.patch.dict(sys.modules, {"investigation": inv, "exploratory_findings": ex}))
        push(mock.patch.object(MC, "HTTP", self.stand))
        push(mock.patch.object(IP, "NOW", self.clock))
        if self.budget_path is not None:
            push(mock.patch.object(IP, "BUDGET_PATH", self.budget_path))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        S.cleanup(self.t)

    # --- calls
    def run(self, argv, command):
        return S.run(argv, main=IP.main, command=command)

    def http(self, target="case-A", *, url=GET, method="GET", dispatch=D, extra=(), root=None):
        return self.run(["http", "--task-root", str(root or self.task), "--dispatch", dispatch, "--target", target,
                         "--method", method, "--url", url, *extra], "investigation_probe.py http")

    def record(self, target="case-A", status="unverified", *, kind="observation", extra=(), dispatch=D,
               statement="the list answers 200 with one item", why="the stand answered; no expectation to compare"):
        return self.run(["record", "--task-root", str(self.task), "--dispatch", dispatch, "--target", target, "--kind", kind,
                         "--statement", statement, "--why-not-a-bug", why, "--status", status, *extra],
                        "investigation_probe.py record")

    # --- looking
    def pass_folder(self, root=D):
        return self.task / "work" / "evidence" / "investigation" / root

    def lines(self, root=D):
        path = self.pass_folder(root) / "captures.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []

    def captures(self, root=D):
        return [x for x in self.lines(root) if "n" in x]

    def files(self, root=D):
        folder = self.pass_folder(root)
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*-request-response.json")) if folder.is_dir() else []

    def write_captures(self, lines, root=D, raw=None):
        folder = self.pass_folder(root)
        folder.mkdir(parents=True, exist_ok=True)
        text = raw if raw is not None else "".join(json.dumps(x) + "\n" for x in lines)
        (folder / "captures.jsonl").write_text(text, encoding="utf-8")


def snap(root):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size) for p in Path(root).rglob("*") if p.is_file())


def out_of(res):
    return json.loads(res[1]) if res[1].strip() else None


def refused(label, res, command="http", needle=None, writes=None):
    """A refusal as a role reads it: exit 2, stdout empty, the command's own prefix, the way out, no traceback."""
    code, out, err = res
    check(f"{label}: exit 2, stdout empty, `investigation_probe.py {command}: ` prefix, the way out, no traceback",
          code == 2 and out == "" and err.startswith(f"investigation_probe.py {command}: ") and "if you cannot" in err
          and "Traceback" not in err, f"rc {code}: {err[:200]!r}")
    if needle:
        check_in(f"{label}: names {needle!r}", needle, err)


def not_written(label, w, before, calls=0):
    check(f"{label}: nothing sent, nothing written", snap(w.task) == before and len(w.stand.calls) == calls,
          f"{len(w.stand.calls)} call(s)")


def probe_n(w, count, *, targets=None, clock=None):
    """`count` successful probes spread over the targets (three each at most)."""
    targets = targets or [f"case-{c}" for c in LETTERS]
    codes = []
    for i in range(count):
        if clock:
            clock(w.clock, i)
        codes.append(w.http(targets[i // 3])[0])
    return codes


# --------------------------------------------------------------------------------------------------------------------

def k_methods():
    with World() as w:
        for method in ("GET", "HEAD", "OPTIONS", "get"):
            before = len(w.captures())
            res = w.http(f"case-{LETTERS[before]}", method=method)
            check(f"K-M3-1: --method {method} exits 0 and leaves one capture line", res[0] == 0 and len(w.captures()) == before + 1,
                  res[2][:200])
        check("K-M3-1: `get` was sent as GET", w.stand.probes()[-1][0] == "GET")
        for method in ("POST", "PUT", "PATCH", "DELETE", "TRACE", "", " GET", "G" + CYRILLIC_E + "T", "post"):
            before, calls = snap(w.task), len(w.stand.calls)
            res = w.http("case-E", method=method)
            refused(f"K-M3-1: --method {method!r}", res, needle="read-only")
            check(f"K-M3-1: --method {method!r}: no line, no call", snap(w.task) == before and len(w.stand.calls) == calls)
    with World(budget={"schema_version": 1, "methods": ["GET", "POST"], "probes_per_dispatch": 12,
                       "reproductions_per_target": 3, "timebox_minutes": 20, "resolving_verdicts": []}) as w:
        res = w.http("case-A", method="POST")
        check("K-M3-1 control: a budget copy that lists POST lets POST through (the key reads the file)",
              res[0] == 0 and ("POST", GET) in [c[:2] for c in w.stand.calls], res[2][:200])


def k_login():
    with World() as w:
        res = w.http("case-A", method="POST", url=LOGIN)
        refused("K-M3-1b: --method POST to the login path", res)
        check("K-M3-1b: and the stand saw nothing", w.stand.calls == [])
        res = w.http("case-A")
        calls = [c[:2] for c in w.stand.calls]
        check_eq("K-M3-1b: a GET with login: the recipe's POST to the login path, then the GET", calls, [("POST", LOGIN), ("GET", GET)])
        check_eq("K-M3-1b: the GET carried the token the login gave", w.stand.calls[1][2]["Authorization"], "Bearer " + S.TOKEN)
        check_eq("K-M3-1b: the login is not a probe: one capture line, used p = 1", (len(w.captures()), out_of(res)["used"]["p"]), (1, 1))
        saved = json.loads((w.task / w.captures()[0]["path"]).read_text(encoding="utf-8"))
        check_eq("K-M3-1b: the token is stored as [redacted]", saved["request"]["headers"]["Authorization"], "[redacted]")
        text = S.tree_text(w.task)
        check("K-M3-1b: neither the password nor the token is anywhere under the story", S.PASSWORD not in text and S.TOKEN not in text)
        w.stand.calls.clear()
        w.http("case-B", extra=["--header", "Authorization: Bearer role-own"])
        check_eq("K-M3-1b: an Authorization header of the role skips the login (no POST at all)",
                 [c[0] for c in w.stand.calls], ["GET"])
    with World(cfg=S.config(manual_capture={"login": {"http": None}})) as w:
        w.http("case-A")
        check_eq("K-M3-1b control: manual_capture.login.http null -> no login POST", [c[0] for c in w.stand.calls], ["GET"])


def k_login_source():
    """EP1-31: the probe signs in by what the project RECORDED. A sign-in the factory does not know sends 0 requests (not even
    the GET: the refusal is the probe's own), `none` signs in by nothing, `local_login` goes to the recorded address."""
    environment = S.config()["environment"]

    def with_access(access, **over):
        return S.config(environment={**environment, "access": access}, **over)

    for kind in ("harness_command", "bearer_env", "oidc_password", "frobnicate"):
        with World(cfg=with_access({"kind": kind, "command": "x"})) as w:
            before = snap(w.task)
            res = w.http("case-A")
            refused(f"EP1-31 {kind} with no recipe", res, needle="nothing was sent")
            check_in(f"EP1-31 {kind}: the refusal names the kind", f"environment.access.kind {kind}", res[2])
            check_in(f"EP1-31 {kind}: and says no probe was sent", "no probe was sent", res[2])
            not_written(f"EP1-31 {kind}", w, before)
            check(f"EP1-31 {kind}: no credential in the refusal", S.PASSWORD not in res[2] and S.TOKEN not in res[2])
    with World(cfg=with_access({"kind": "harness_command", "command": "x"},
                               manual_capture={"login": {"http": {"path": "/v1/local-auth/login", "token_field": "access_token"}}})) as w:
        res = w.http("case-A")
        check_eq("EP1-31 harness_command + the project's own recipe: the recipe's POST, then the GET",
                 (res[0], [c[:2] for c in w.stand.calls]), (0, [("POST", LOGIN), ("GET", GET)]))
    with World(cfg=with_access({"kind": "harness_command", "command": "x"})) as w:
        w.http("case-B", extra=["--header", "Authorization: Bearer role-own"])
        check_eq("EP1-31 a role's own Authorization needs no login: no refusal, one GET", [c[0] for c in w.stand.calls], ["GET"])
    with World(cfg=with_access({"kind": "none"})) as w:
        res = w.http("case-A")
        check_eq("EP1-31 access none: no sign-in request at all, the GET goes", (res[0], [c[0] for c in w.stand.calls]), (0, ["GET"]))
        check("EP1-31 access none: no Authorization header was made up", "Authorization" not in w.stand.calls[0][2])
    other = f"{LOCAL}/v1/other/token"
    with World(cfg=with_access({"kind": "local_login", "url": "/v1/other/token"}),
               routes={("POST", other): S.ok_json({"data": {"token": S.TOKEN}})}) as w:
        res = w.http("case-A")
        check_eq("EP1-31 local_login with a url: the POST goes to the recorded address, never the default path",
                 (res[0], [c[:2] for c in w.stand.calls]), (0, [("POST", other), ("GET", GET)]))
        check_eq("EP1-31 ... and the token under data.token is read", w.stand.calls[1][2]["Authorization"], "Bearer " + S.TOKEN)
    keyed = f"{LOCAL}/v1/keyed/login"
    with World(cfg=with_access({"kind": "local_login", "url": "LOGIN_URL_KEY"}),
               routes={("POST", keyed): S.ok_json({"access_token": S.TOKEN})}) as w:
        env_file = w.t.project / "harness" / ".env"
        env_file.write_text(env_file.read_text(encoding="utf-8") + f"LOGIN_URL_KEY={keyed}\n", encoding="utf-8")
        res = w.http("case-A")
        check_eq("EP1-31 local_login whose url is a KEY NAME: the env file's value is the address",
                 (res[0], [c[:2] for c in w.stand.calls]), (0, [("POST", keyed), ("GET", GET)]))
    with World(cfg=with_access({"kind": "local_login", "url": "NO_SUCH_KEY"})) as w:
        before = snap(w.task)
        refused("EP1-31 local_login whose url is a key the env file does not hold", w.http("case-A"), needle="nothing was sent")
        not_written("EP1-31 local_login key empty", w, before)


def k_shipped_budget():
    data = json.loads(BUDGET.read_text(encoding="utf-8"))
    check_eq("K-M3-1c: the shipped budget lists exactly the read-only methods", data["methods"], ["GET", "HEAD", "OPTIONS"])
    check_eq("K-M3-1c: P, R, T and the schema version", (data["probes_per_dispatch"], data["reproductions_per_target"],
                                                          data["timebox_minutes"], data["schema_version"]), (12, 3, 20, 1))
    check("K-M3-1c: NOT_EXECUTED and ENV_ISSUE do not resolve a target",
          not {"NOT_EXECUTED", "ENV_ISSUE"} & set(data["resolving_verdicts"]) and "APP_BUG" in data["resolving_verdicts"])
    check("K-M3-1c: a note is there (the shape of the other references)", isinstance(data.get("note"), str) and data["note"])


def k_probe_cap():
    with World() as w:
        codes = probe_n(w, 12)
        check_eq("K-M3-2: probes 1..12 are allowed", codes, [0] * 12)
        before = snap(w.task)
        res = w.http("case-E")
        refused("K-M3-2: the 13th probe", res, needle="12 probes in this investigation")
        not_written("K-M3-2: the 13th probe", w, before, calls=len(w.stand.calls))
        check_in("K-M3-2: the refusal points to `record` and to gate B", "more needs the person's word at gate B", res[2])
        check_eq("K-M3-2: the file holds the header and 12 captures", (len(w.lines()), len(w.captures())), (13, 12))
    with World(budget={"schema_version": 1, "methods": ["GET"], "probes_per_dispatch": 13, "reproductions_per_target": 3,
                       "timebox_minutes": 20, "resolving_verdicts": []}) as w:
        codes = probe_n(w, 13)
        check_eq("K-M3-2b: a budget copy with P = 13 lets the 13th through (the cap is read from the file)", codes, [0] * 13)
    with World() as w:
        res = w.http("case-A")
        used = out_of(res)
        check_eq("K-M3-2: the first answer reports used and left", (used["used"], used["left"]),
                 ({"p": 1, "r": 1}, {"p": 11, "r": 2, "seconds": 1200}))


def k_target_cap():
    with World() as w:
        order = ["case-A", "case-B", "case-B", "case-A", "case-A"]
        codes = [w.http(t)[0] for t in order]
        check_eq("K-M3-3: A, B, B, A, A are allowed (R counts the target's captures only, not every target's)", codes, [0] * 5)
        before = snap(w.task)
        res = w.http("case-A")
        refused("K-M3-3: the 4th probe of A", res, needle="3 probes for target case-A")
        not_written("K-M3-3: the 4th probe of A", w, before, calls=len(w.stand.calls))
        check("K-M3-3: another target (C) is still allowed after A is full", w.http("case-C")[0] == 0)


def k_timebox():
    with World() as w:
        w.clock.at(0)
        check("K-M3-4 control: the first probe at +0:00 is allowed", w.http("case-A")[0] == 0)
        w.clock.at(19, 59)
        check("K-M3-4: started_at + 19:59 is allowed", w.http("case-B")[0] == 0)
        w.clock.at(20, 0)
        before = snap(w.task)
        res = w.http("case-C")
        refused("K-M3-4: started_at + 20:00", res, needle="20-minute timebox")
        not_written("K-M3-4: started_at + 20:00", w, before, calls=len(w.stand.calls))
        headers = [x for x in w.lines() if "started_at" in x and "n" not in x]
        check_eq("K-M3-4: exactly one header, first in the file, with the first probe's moment",
                 (len(headers), w.lines()[0], len(w.captures())), (1, {"started_at": T0.isoformat(timespec="seconds")}, 2))
    with World() as w:
        w.clock.at(0)
        w.http("case-A")
        w.clock.at(19, 59)
        res = w.http("case-B")
        check_eq("K-M3-4: a probe started at T-1 s is kept and counted; its answer reports 0 s... left",
                 (res[0], out_of(res)["left"]["seconds"]), (0, 1))


def k_first_reached():
    small = {"schema_version": 1, "methods": ["GET"], "probes_per_dispatch": 3, "reproductions_per_target": 3,
             "timebox_minutes": 20, "resolving_verdicts": []}
    with World(budget=small) as w:
        for minute, target in ((0, "case-A"), (1, "case-B"), (5, "case-C")):
            w.clock.at(minute)
            w.http(target)
        w.clock.at(21)
        res = w.http("case-D")
        refused("K-M3-5: P reached at +5 and T at +20, called at +21", res, needle="3 probes in this investigation")
        check_not_in("K-M3-5: and the timebox is not named (it came later)", "timebox", res[2])
    with World(budget=small) as w:
        w.clock.at(0)
        w.http("case-A")
        w.clock.at(21)
        res = w.http("case-B")
        refused("K-M3-5: T alone", res, needle="20-minute timebox")
    with World(budget=dict(small, reproductions_per_target=2)) as w:
        for minute, target in ((0, "case-A"), (1, "case-A"), (2, "case-B")):
            w.clock.at(minute)
            w.http(target)
        w.clock.at(3)
        res = w.http("case-A")
        refused("K-M3-5: R reached at +1 and P at +2: the EARLIER one is named, not the first in a fixed order", res,
                needle="2 probes for target case-A")


def k_host_and_gate():
    cases = (("a foreign host", "http://evil.example.test/v1/x", "not on a configured stand"),
             ("userinfo in the URL", "http://user:pw@localhost:8080/v1/x", "not on a configured stand"),
             ("a port mismatch", "http://localhost:9999/v1/x", "not on a configured stand"),
             ("a scheme mismatch", "https://localhost:8080/v1/x", "not on a configured stand"))
    with World() as w:
        for label, url, needle in cases:
            before = snap(w.task)
            refused(f"K-M3-6: {label}", w.http("case-A", url=url), needle=needle)
            not_written(f"K-M3-6: {label}", w, before)
    with World(cfg=S.config(environments=[])) as w:
        refused("K-M3-6: cfg.environments = []", w.http("case-A"), needle="no environments[]")
        check("K-M3-6: and nothing was sent", w.stand.calls == [])
    with World(pipeline={"gates": {"B": {"status": "approved"}}}) as w:
        before = snap(w.task)
        refused("K-M3-6b: gate B approved", w.http("case-A"), needle="gate B is answered")
        not_written("K-M3-6b: gate B approved", w, before)
        refused("K-M3-6b: gate B approved, record too", w.record("case-A"), command="record", needle="gate B is answered")
    with World(pipeline={"gates": {"B": {"decision": "declined"}}}) as w:
        refused("K-M3-6b: a declined gate B is an answer", w.http("case-A"), needle="gate B is answered")
    with World(pipeline={"gates": {"A": {"status": "approved"}}}) as w:
        check("K-M3-6b control: gate A only approved -> allowed", w.http("case-A")[0] == 0)


def three_captures(w, target="case-A"):
    return [w.http(target)[0] for _ in range(3)]


def k_record():
    with World(register_lines=[]) as w:
        check_eq("K-M3-7: three probes of A", three_captures(w), [0, 0, 0])
        before = snap(w.task)
        res = w.record("case-A", "reproduced", extra=["--reproduced-by", "1,2"])
        refused("K-M3-7: reproduced with 2 of 3", res, command="record", needle="needs 3 of 3 captures reproducing it; you named 2 of 3")
        check_in("K-M3-7: and it names the status that fits", "record `--status unverified` (2 of 3)", res[2])
        check("K-M3-7: nothing appended, nothing written", w.register.calls == [] and snap(w.task) == before)
        res = w.record("case-A", "reproduced", extra=["--reproduced-by", "001,2,3,3"])
        check_eq("K-M3-7: reproduced with 3 of 3 (001 = 1, a duplicate collapses) is accepted", res[0], 0)
        line, by = w.register.calls[0]
        shown = out_of(res)
        check_eq("K-M3-7: ONE append, by the dispatch, op add, the counts taken from the captures",
                 (len(w.register.calls), by, line["op"], line["probe"]["runs"], line["probe"]["reproduced"]), (1, D, "add", 3, 3))
        check_eq("K-M3-7: stdout", (shown["ok"], shown["target"], shown["verification_status"], shown["runs"], shown["reproduced"],
                                    shown["of"]), (True, "case-A", "reproduced", 3, 3, 3))
        check_eq("K-M3-7c: probe shape: method api, environment from the last capture's URL, safe_to_break null",
                 (line["probe"]["method"], line["probe"]["environment"], line["probe"]["safe_to_break"]), ("api", "localhost", None))
        check_eq("K-M3-7c: evidence_refs are X's three capture files with their hashes",
                 [(r["path"], r["sha256"]) for r in line["evidence_refs"]],
                 [(c["path"], S.sha(w.task / c["path"])) for c in w.captures()])
        check_eq("K-M3-7c: origin, evidence_kind is the register's to set, oracle default for an observation",
                 (line["origin"], "evidence_kind" in line, line["oracle_status"]), ({"dispatch": D, "target": "case-A"}, False, "none"))
        check_eq("K-M3-7c: title defaults to the statement", line["title"], line["statement"])
        for forbidden in ("severity", "priority", "bug", "triage_ref", "confirmation", "impact", "investigated"):
            check_not_in(f"K-M3-7c: the line never carries `{forbidden}`", forbidden, json.dumps(line).replace("not_a_bug", ""))

    with World(register_lines=[]) as w:
        w.http("case-A")
        refused("K-M3-7: not_reproduced with 0 runs (case-B)", w.record("case-B", "not_reproduced"), command="record",
                needle="at least one capture")
        refused("K-M3-7: environment_event with 0 runs", w.record("case-B", "environment_event"), command="record",
                needle="at least one capture")
        refused("K-M3-7: a capture number of ANOTHER target", w.record("case-B", "unverified", extra=["--reproduced-by", "1"]),
                command="record", needle="capture 1 is not a saved capture of case-B")
        refused("K-M3-7: a number that does not exist", w.record("case-A", "unverified", extra=["--reproduced-by", "7"]),
                command="record", needle="capture 7 is not a saved capture of case-A")
        for flag in ("--runs", "--reproduced"):
            res = w.record("case-A", "reproduced", extra=[flag, "3"])
            refused(f"K-M3-7: typed {flag} 3", res, command="record", needle="counts come from the captures of this investigation")
        refused("K-M3-7: --reproduced-by \"1,,x\"", w.record("case-A", "unverified", extra=["--reproduced-by", "1,,x"]),
                command="record", needle="is not a capture number")
        check("K-M3-7: no refusal above appended anything", w.register.calls == [])
        res = w.record("case-A", "not_reproduced")
        check_eq("K-M3-7: not_reproduced with 1 run and none reproducing it is accepted", res[0], 0)
        res = w.record("case-A", "environment_event", extra=["--oracle-status", "documented_text_only"])
        check_eq("K-M3-7: environment_event with a run is accepted; a second record of the target is a CORRECTION",
                 (res[0], w.register.calls[-1][0]["op"], w.register.calls[-1][0]["oracle_status"]), (0, "correct", "documented_text_only"))
        res = w.record("case-B", "unverified")
        check_eq("K-M3-7 control: unverified with 0 runs is accepted (F-6: the target's carrier is the evidence)",
                 (res[0], w.register.calls[-1][0]["evidence_refs"][0]["path"], w.register.calls[-1][0]["probe"]["runs"]),
                 (0, "work/test-plan.json", 0))
        res = w.record("case-C", "unverified", kind="unresolved_question",
                       extra=["--question", "which value?", "--owner-role", "owner", "--title", "t", "--refs", "R-1, TC-2,"])
        line = w.register.calls[-1][0]
        check_eq("K-M3-7c: unresolved_question defaults to owner_question; refs are split; question and owner pass through",
                 (res[0], line["oracle_status"], line["refs"], line["question"], line["owner_role"], line["title"]),
                 (0, "owner_question", ["R-1", "TC-2"], "which value?", "owner", "t"))
        w.register.calls.clear()
        res = w.record("case-D", "unverified", statement="x" * 300)
        check_eq("K-M3-7c: a title made from the statement is cut at 120 characters", len(w.register.calls[0][0]["title"]), 120)
        w.targets = {"unresolved": [], "resolved": [("case-A", "recorded by a role"), ("case-R", "triage verdict APP_BUG")]}
        refused("K-M3-7: a resolved target with no capture", w.record("case-R", "unverified"), command="record",
                needle="case-R is resolved: triage verdict APP_BUG")
        check("K-M3-7: a resolved target with a capture of its own may still be corrected",
              w.record("case-A", "unverified")[0] == 0)
        refused("K-M3-7: a name that is no target at all", w.record("case-Z", "unverified"), command="record", needle="is not a target")
    with World(register_lines=[]) as w:
        w.targets = {"unresolved": [{"id": "case-A", "carrier": "work/nothing-here.json", "evidence": ["work/also-missing"]}],
                     "resolved": []}
        refused("K-M3-7: 0 captures and a carrier that is not a file", w.record("case-A", "unverified"), command="record",
                needle="no capture and no carrier file")


def code_line(target="case-A"):
    return {"id": "EX-1", "op": "add", "origin": {"dispatch": "code", "target": target}, "verification_status": "unverified",
            "recorded_by": "code:investigation.project"}


def k_record_chain():
    with World(register_lines=[code_line()]) as w:
        w.http("case-A")
        res = w.record("case-A", "not_reproduced")
        line, _ = w.register.calls[0]
        check_eq("K-M3-7b: a code `unverified` active line -> ONE append, op correct, corrects.id is that line, the reason is the status",
                 (res[0], len(w.register.calls), line["op"], line["corrects"]), (0, 1, "correct", {"id": "EX-1", "reason": "not_reproduced"}))
        check_eq("K-M3-7b: and the chain still has one active line", list(w.register.read(w.task)["active"]), ["case-A"])
    with World(register_lines=[]) as w:
        w.http("case-B")
        w.record("case-B", "unverified")
        check_eq("K-M3-7b control: no chain -> op add", w.register.calls[0][0]["op"], "add")
    withdrawn = [code_line(), {"id": "EX-2", "op": "withdraw", "origin": {"dispatch": "code", "target": "case-A"}}]
    with World(register_lines=withdrawn) as w:
        w.http("case-A")
        res = w.record("case-A", "unverified")
        refused("K-M3-7b: a withdrawn chain", res, command="record", needle="case-A was withdrawn by EX-2")
        check("K-M3-7b: and nothing was appended", w.register.calls == [])


def k_dispatch_and_chain():
    cases = (("D accepted", {D: running(status="accepted")}),
             ("D in stage S5", {D: running(stage="S5")}),
             ("D with another purpose", {D: running(purpose="triage")}),
             ("D unknown", {"other": running(id="other")}),
             ("D blocked", {D: running(status="blocked")}))
    for label, dispatches in cases:
        with World(dispatches=dispatches) as w:
            before = snap(w.task)
            refused(f"K-M3-8: {label}", w.http("case-A"), needle="not a running S7 investigation")
            not_written(f"K-M3-8: {label}", w, before)
            refused(f"K-M3-8: {label} (record)", w.record("case-A"), command="record", needle="not a running S7 investigation")
    other = {D: running(), "S7-analyst-9": running(id="S7-analyst-9")}
    with World(dispatches=other) as w:
        before = snap(w.task)
        refused("K-M3-8b: a running member of ANOTHER root", w.http("case-A"), needle="a second investigation in one S7 chain is not run")
        not_written("K-M3-8b: a running member of ANOTHER root", w, before)
        refused("K-M3-8b: (record)", w.record("case-A"), command="record", needle="a second investigation in one S7 chain")
    for status in ("superseded", "stale", "never_started", "released_by_person"):
        with World(dispatches={D: running(), "S7-analyst-9": running(id="S7-analyst-9", status=status)}) as w:
            check(f"K-M3-8b control: a `{status}` member of another root is not a member -> allowed", w.http("case-A")[0] == 0)
    with World(dispatches={D: running(), "S7-analyst-9": running(id="S7-analyst-9", status="returned_unaccepted")}) as w:
        refused("K-M3-8b: a `returned_unaccepted` member of another root still blocks a second pass", w.http("case-A"),
                needle="a second investigation")


def k_lineage():
    small = {"schema_version": 1, "methods": ["GET"], "probes_per_dispatch": 3, "reproductions_per_target": 3,
             "timebox_minutes": 20, "resolving_verdicts": []}
    d2, d3 = "S7-analyst-2", "S7-analyst-3"
    with World(budget=small, dispatches={D: running()}) as w:
        w.http("case-A")
        w.http("case-B")
        w.dispatches = {D: running(status="returned_unaccepted"), d2: running(id=d2, parent_retry=D)}
        res = w.http("case-C", dispatch=d2)
        check_eq("K-M3-20u: a retry (parent_retry) continues the parent's pass: the 3rd probe is allowed and counted p = 3",
                 (res[0], out_of(res)["used"]["p"]), (0, 3))
        w.dispatches = {D: running(status="returned_unaccepted"), d2: running(id=d2, parent_retry=D, status="blocked"),
                        d3: running(id=d3, relaunch_of=d2)}
        before = snap(w.task)
        res = w.http("case-D", dispatch=d3)
        refused("K-M3-20u: a relaunch (relaunch_of) of the retry: the 4th probe over the chain is refused", res,
                needle="3 probes in this investigation")
        not_written("K-M3-20u: the relaunch", w, before, calls=len(w.stand.calls))
        check_eq("K-M3-20u: one file, keyed by the chain's root", (sorted(p.name for p in
                                                                          (w.task / "work" / "evidence" / "investigation").iterdir()),
                                                                   len(w.captures(D)), len(w.lines(D))), ([D], 3, 4))
        check_eq("K-M3-20u: the numbers run across the retry", [c["n"] for c in w.captures(D)], [1, 2, 3])
        check_eq("K-M3-20u: and each capture names the dispatch that made it", [c["dispatch"] for c in w.captures(D)], [D, D, d2])


def hidden_world(names, **kw):
    return World(hide=names, **kw)


def k_absent():
    chain = list(IP.CHAIN_NAMES)
    register = list(IP.REGISTER_NAMES)
    with World() as w:
        check("K-T1 control: everything present -> exit 0", w.http("case-A")[0] == 0)
    with hidden_world({"investigation.budget_problems"}) as w:
        before = snap(w.task)
        res = w.http("case-A")
        refused("K-T1 (i): investigation.budget_problems absent", res, needle="investigation.budget_problems")
        not_written("K-T1 (i)", w, before)
        refused("K-T1 (i): record", w.record("case-A"), command="record", needle="investigation.budget_problems")
    for name in chain:
        with hidden_world({name}) as w:
            before = snap(w.task)
            res = w.http("case-A")
            refused(f"K-T1 (ii): {name} absent", res, needle=f"`{name}`")
            not_written(f"K-T1 (ii): {name} absent", w, before)
            check_not_in(f"K-T1 (ii): {name} absent: only the missing one is named", "budget_problems", res[2])
    with hidden_world(set(chain)) as w:
        res = w.http("case-A")
        positions = [res[2].find(f"`{n}`") for n in chain]
        check("K-T1 (ii): all four absent -> ONE line naming all, in the fixed order",
              res[0] == 2 and -1 not in positions and positions == sorted(positions) and res[2].count("is not installed") == 1,
              f"{positions}")
    with hidden_world(set(chain + register)) as w:
        res = w.record("case-A")
        positions = [res[2].find(f"`{n}`") for n in chain + register]
        check("K-T1 (ii): record, all seven absent -> ONE line naming all seven, in the fixed order",
              res[0] == 2 and -1 not in positions and positions == sorted(positions), f"{positions}")
    for name in register:
        with hidden_world({name}) as w:
            w.http("case-A")
            before = snap(w.task)
            res = w.record("case-A")
            refused(f"K-T1 (ii): {name} absent", res, command="record", needle="the findings register is not installed")
            check_in(f"K-T1 (ii): {name} absent: and it is named", f"`{name}`", res[2])
            check(f"K-T1 (ii): {name} absent: nothing written", snap(w.task) == before)
    with hidden_world({"exploratory_findings.read", "exploratory_findings.append"}) as w:
        check("K-T1: `http` does not need the register: it works while the register is absent", w.http("case-A")[0] == 0)
    with World() as w:
        with mock.patch.dict(sys.modules, {"investigation": None}):
            before = snap(w.task)
            refused("K-T1: the investigation module cannot be imported at all", w.http("case-A"), needle="investigation.budget_problems")
            not_written("K-T1: the module is gone", w, before)


def k_budget_rule():
    with World(problems=["x"]) as w:
        before = snap(w.task)
        res = w.http("case-A")
        refused("K-B0: budget_problems returns [\"x\"] -> http", res, needle="investigation-budget.json: x")
        not_written("K-B0: http", w, before)
        res = w.record("case-A")
        refused("K-B0: record", res, command="record", needle="investigation-budget.json: x")
        check("K-B0: record wrote nothing", w.register.calls == [] and snap(w.task) == before)
    with World(problems=["x", "y"]) as w:
        res = w.http("case-A")
        check_in("K-B0: every problem is printed", "x; y", res[2])
    with World(problems=[]) as w:
        check("K-B0 control: [] with the shipped file -> the call proceeds", w.http("case-A")[0] == 0)
        check_eq("K-B0: the rule is asked with the budget the file holds",
                 w.seen[0], json.loads(BUDGET.read_text(encoding="utf-8")))
    with World(budget_path=Path(tempfile.gettempdir()) / "qa-no-such-budget-4f1c.json") as w:
        res = w.http("case-A")
        check_eq("K-B0: the budget file ABSENT -> the rule is still asked, with None (what it answers is M2's)", w.seen, [None])
    with World(budget_path=Path(tempfile.gettempdir()) / "qa-no-such-budget-4f1c.json", problems=["cannot be read"]) as w:
        refused("K-B0: and its answer refuses the call", w.http("case-A"), needle="cannot be read")
        check("K-B0: nothing was sent", w.stand.calls == [])


def k_damage_state_pipeline():
    with World(register_lines=[]) as w:
        w.http("case-A")
        clean = (w.pass_folder() / "captures.jsonl").read_text(encoding="utf-8")
        check("K-DMG control: a clean file -> the next probe passes", w.http("case-B")[0] == 0)
        for label, junk in (("not JSON", "not json\n"), ("a JSON list", "[1, 2]\n"),
                            ("a capture with a text n", json.dumps({"n": "3", "target": "case-A"}) + "\n"),
                            ("a capture with no target", json.dumps({"n": 9}) + "\n"),
                            ("a capture with a bool n", json.dumps({"n": True, "target": "case-A"}) + "\n"),
                            ("a path that leaves the pass", json.dumps({"n": 9, "target": "case-A", "path": "../../x"}) + "\n"),
                            ("a header with a bad date", json.dumps({"started_at": "yesterday"}) + "\n")):
            w.write_captures(None, raw=clean + junk)
            before, calls = snap(w.task), len(w.stand.calls)
            refused(f"K-DMG: {label} -> http", w.http("case-C"), needle="damaged line")
            not_written(f"K-DMG: {label}", w, before, calls=calls)
        w.write_captures(None, raw=clean + "not json\n")
        refused("K-DMG: a damaged line -> record not_reproduced", w.record("case-A", "not_reproduced"), command="record",
                needle="a hidden line could be a reproduction")
        check("K-DMG: ... but unverified is accepted", w.record("case-A", "unverified")[0] == 0)
        w.write_captures(None, raw=clean)
        check("K-DMG control: the clean file -> not_reproduced is accepted", w.record("case-A", "not_reproduced")[0] == 0)
        w.write_captures(None, raw=clean.split("\n", 1)[1])
        refused("K-DMG: captures but no header (the clock is unknown) -> http", w.http("case-C"), needle="damaged line")
        w.write_captures(None, raw="\n\n" + clean)
        check("K-DMG: blank lines are no line", w.http("case-C")[0] == 0)
        (w.pass_folder() / "captures.jsonl").write_bytes(b"\xff\xfe\x00")
        refused("K-DMG: a file that is not UTF-8", w.http("case-C"), needle="cannot be read")
    with World() as w:
        w.state_error = RuntimeError("store broken")
        before = snap(w.task)
        refused("K-STATE: state() raises", w.http("case-A"), needle="the controller's state cannot be read (RuntimeError)")
        not_written("K-STATE", w, before)
        refused("K-STATE: record", w.record("case-A"), command="record", needle="the controller's state cannot be read")
    with World() as w:
        (w.task / "pipeline.json").write_text("{not json", encoding="utf-8")
        before = snap(w.task)
        refused("K-PIPE: a corrupt pipeline.json", w.http("case-A"), needle="pipeline.json cannot be read")
        not_written("K-PIPE", w, before)
        (w.task / "pipeline.json").unlink()
        refused("K-PIPE: an absent pipeline.json", w.http("case-A"), needle="pipeline.json cannot be read")
        (w.task / "pipeline.json").write_text("[]", encoding="utf-8")
        refused("K-PIPE: a pipeline that is not an object", w.http("case-A"), needle="pipeline.json cannot be read")
    with World() as w:
        w.targets = {"unresolved": "none"}
        refused("K-STATE: an answer of unresolved_targets nobody can read", w.http("case-A"), needle="targets cannot be read")


def k_secrets_and_unsaved():
    with World() as w:
        before = snap(w.task)
        refused("K-SEC: a secret in the URL", w.http("case-A", url=f"{GET}?x={SECRET_WORD}"), needle="secret_content_patterns[")
        refused("K-SEC: a secret in a header", w.http("case-A", extra=["--header", f"X-Note: {SECRET_WORD}"]),
                needle="nothing was sent or saved")
        not_written("K-SEC: a secret in the request", w, before)
    body = MC.HttpResult(200, [("Content-Type", "text/plain")], f"{SECRET_WORD}=abc".encode(), 0.01)
    with World(routes={("GET", GET): body}) as w:
        res = w.http("case-A")
        line = w.captures()[0]
        check_eq("K-SEC: a secret in the RESPONSE -> exit 1, outcome withheld_secret, no file", (res[0], out_of(res)["ok"], out_of(res)["outcome"], w.files()),
                 (1, False, "withheld_secret", []))
        check("K-SEC: the sent request is COUNTED (P bounds what the stand receives); the line is not citable",
              out_of(res)["used"]["p"] == 1 and line["outcome"] == "withheld_secret" and line["path"] is None
              and line["sha256"] is None and line["status"] is None)
        check("K-SEC: the secret is nowhere under the story", SECRET_WORD not in S.tree_text(w.task))
        w.stand.routes[("GET", GET)] = S.ok_json({"fine": True})
        res = w.http("case-A")
        check_eq("K-SEC control: a clean body is saved (n continues after the withheld one)",
                 (res[0], out_of(res)["capture"]["n"], len(w.files())), (0, 2, 1))
        w.register.lines = []
        res = w.record("case-A", "not_reproduced")
        check_eq("K-F5: runs counts the saved captures only (the withheld one is no evidence)",
                 (res[0], w.register.calls[-1][0]["probe"]["runs"], len(w.register.calls[-1][0]["evidence_refs"])), (0, 1, 1))
        refused("K-F5: a withheld probe's number cannot be cited", w.record("case-A", "unverified", extra=["--reproduced-by", "1"]),
                command="record", needle="capture 1 is not a saved capture")

    def stalls(headers, body):
        raise MC.StepTimeout(181)

    def fails(headers, body):
        raise MC.StepFailed("the stand did not answer")

    slow = MC.HttpResult(200, [], b"{}", 9999.0)
    for label, route, word in (("StepTimeout", stalls, "timeout"), ("StepFailed", fails, "no_answer"),
                               ("an answer later than the limit", slow, "timeout"),
                               ("a body that never came", MC.HttpResult(200, [], b"", 0.1, unreadable=True), "timeout")):
        with World(routes={("GET", GET): route}) as w:
            res = w.http("case-A")
            check_eq(f"K-F5: {label} -> exit 1, outcome {word}, counted, nothing saved",
                     (res[0], out_of(res)["outcome"], out_of(res)["used"]["p"], w.files(), len(w.captures())), (1, word, 1, [], 1))
    with World(routes={("POST", LOGIN): S.ok_json({"detail": "no"}, status=401)}) as w:
        before = snap(w.task)
        res = w.http("case-A")
        refused("K-F5: a login that gives no token -> its words, no probe sent", res, needle="did not give a token")
        not_written("K-F5: the failed login is not counted (login POST uncounted)", w, before, calls=len(w.stand.calls))
        check("K-F5: only login POSTs were made", all(c[0] == "POST" for c in w.stand.calls))
    truncated = MC.HttpResult(200, [], b"a" * (MC.BODY_CAP + 5), 0.1)
    with World(routes={("GET", GET): truncated}) as w:
        res = w.http("case-A")
        saved = json.loads((w.task / w.captures()[0]["path"]).read_text(encoding="utf-8"))
        check_eq("body over 2 MB: cut by `_side`, the limit text in the file", (res[0], saved["response"]["truncated"],
                                                                                 "response body cut" in saved["limit"]), (0, True, True))


def k_request_checks():
    with World() as w:
        before = snap(w.task)
        for label, extra in (("a Host header", ["--header", "Host: evil.example.test"]),
                             ("a host header in other case", ["--header", "hOsT: evil.example.test"]),
                             ("a CR in a value", ["--header", "X-A: a\rb"]), ("a LF in a value", ["--header", "X-A: a\nb"]),
                             ("a NUL in a value", ["--header", "X-A: a\x00b"]), ("a NUL in a name", ["--header", "X\x00A: b"]),
                             ("no colon", ["--header", "nocolon"]), ("an empty name", ["--header", ": value"]),
                             ("a name with a space", ["--header", "Bad Name: v"]), ("a phase that is none", ["--phase", "later"])):
            refused(f"K-ADV: {label}", w.http("case-A", extra=extra), needle=None)
        refused("K-ADV: a CR in the URL", w.http("case-A", url=GET + "\r\nHost: x"))
        not_written("K-ADV: the header and URL refusals", w, before)
        w.http("case-A", extra=["--header", "User-Agent: role/1", "--header", "X-Trace: t1", "--phase", "pre_action"])
        sent = w.stand.probes()[-1][2]
        saved = json.loads((w.task / w.captures()[0]["path"]).read_text(encoding="utf-8"))
        check_eq("a role's own User-Agent wins and its headers travel", (sent["User-Agent"], sent["X-Trace"]), ("role/1", "t1"))
        check_eq("the capture file: schema, dispatch, root, target, n, phase, limit",
                 (saved["schema_version"], saved["dispatch"], saved["root"], saved["target"], saved["n"], saved["phase"], saved["limit"]),
                 (1, D, D, "case-A", 1, "pre_action", None))
        check_eq("the capture file: the request side is redacted and keeps method and url",
                 (saved["request"]["method"], saved["request"]["url"], saved["request"]["headers"]["Authorization"]),
                 ("GET", GET, "[redacted]"))
        w.http("case-B")
        check("the default User-Agent is the factory's", w.stand.probes()[-1][2]["User-Agent"].startswith("qa-factory/"))
        check_eq("the file sits at <root>/<target>/NNN-request-response.json", w.files(),
                 ["case-A/001-request-response.json", "case-B/002-request-response.json"])
        check_eq("the capture line: sha256 is the file's, the path is task-relative",
                 (w.captures()[0]["sha256"], w.captures()[0]["path"]),
                 (S.sha(w.task / w.captures()[0]["path"]), "work/evidence/investigation/S7-analyst-1/case-A/001-request-response.json"))
        stray = w.pass_folder() / "case-A" / "007-request-response.json"
        stray.write_text("{}", encoding="utf-8")
        w.http("case-C")
        check_eq("a file left in the folder by a killed probe is never reused: the numbering goes past it", w.captures()[-1]["n"], 8)
        (w.pass_folder() / "captures.jsonl").write_bytes((w.pass_folder() / "captures.jsonl").read_bytes().rstrip(b"\n"))
        w.write_captures(None, raw=(w.pass_folder() / "captures.jsonl").read_text(encoding="utf-8").rstrip("\n"))
        res = w.http("case-D")
        text = (w.pass_folder() / "captures.jsonl").read_text(encoding="utf-8")
        check("a torn tail (no final newline) gets one before the next line: no two records on one line",
              res[0] == 0 and text.endswith("\n") and all(json.loads(x) for x in text.splitlines()), text[-200:])


def k_refusal_battery():
    with World(register_lines=[]) as w:
        w.http("case-A")
        before = snap(w.task)
        calls = len(w.stand.calls)
        cases = [("an empty --method", "http", w.http("case-A", method="")),
                 ("an empty --target", "http", w.http("")),
                 ("an empty --dispatch", "http", w.http("case-A", dispatch="")),
                 ("an empty --url", "http", w.http("case-A", url="")),
                 ("a Cyrillic E in --target", "http", w.http("case-" + CYRILLIC_E)),
                 ("a homoglyph --method", "http", w.http("case-A", method="G" + CYRILLIC_E + "T")),
                 ("a target with a path step", "http", w.http("../case-A")),
                 ("a target with a slash", "http", w.http("case-A/..")),
                 ("an unknown --dispatch", "http", w.http("case-A", dispatch="nope")),
                 ("an empty --target (record)", "record", w.record("")),
                 ("--reproduced-by with a huge number", "record", w.record("case-A", "unverified", extra=["--reproduced-by", "9" * 5000])),
                 ("--reproduced-by 10 000 numbers", "record", w.record("case-A", "unverified",
                                                                      extra=["--reproduced-by", ",".join(str(i) for i in range(10000))])),
                 ("an empty --dispatch (record)", "record", w.record("case-A", dispatch=""))]
        for label, command, res in cases:
            refused(f"K-ADV: {label}", res, command=command)
        check("K-ADV: none of them sent, wrote or appended anything", snap(w.task) == before and len(w.stand.calls) == calls
              and w.register.calls == [])
        res = w.run(["http", "--task-r", str(w.task), "--dispatch", D, "--target", "case-A", "--method", "GET", "--url", GET],
                    "investigation_probe.py http")
        check("K-ADV: the abbreviation --task-r is not --task-root (exact_options)",
              res[0] == 2 and res[1] == "" and "investigation_probe.py" in res[2] and "required" in res[2] + "unrecognized",
              res[2][:200])
        phantom = w.task.parent / "TP3-404"
        res = w.http("case-A", root=phantom)
        refused("K-ADV: a phantom --task-root", res, needle="names no story")
        check("K-ADV: and nothing was created for it", not phantom.exists() and snap(w.task) == before)
        res = w.run(["http"], "investigation_probe.py http")
        check("K-ADV: no arguments -> a refusal with the usage, exit 2", res[0] == 2 and res[1] == "")
        res = w.run([], "investigation_probe.py")
        check("K-ADV: no subcommand -> exit 2", res[0] == 2 and res[1] == "")
        res = w.run(["delete", "--task-root", str(w.task)], "investigation_probe.py")
        check("K-ADV: an unknown subcommand -> exit 2", res[0] == 2 and res[1] == "")
        res = w.record("case-A", "bogus")
        check("K-ADV: a status outside the four -> exit 2 (never `investigated`)", res[0] == 2 and res[1] == "")
        res = w.record("case-A", "investigated")
        check("K-ADV: the word `investigated` is no status", res[0] == 2 and w.register.calls == [])
    with World() as w:
        big = LOCAL + "/" + "a" * 10000
        res = w.http("case-A", url=big)
        check("K-ADV: a 10 000-character URL on the stand is answered, never a traceback", res[0] in (0, 2) and "Traceback" not in res[2])
        res = w.http("case-B", url="http://localhost:8080" + "/" + "b" * 10000 + "@evil.example.test")
        check("K-ADV: a 10 000-character URL that leaves the stand is refused", res[0] in (0, 2) and "Traceback" not in res[2])
        res = w.http("case-C", extra=[x for i in range(200) for x in ("--header", f"X-H{i}: v{i}")])
        check("K-ADV: 200 headers are sent and answered, never a traceback", res[0] == 0 and "Traceback" not in res[2], res[2][:200])
        check_eq("K-ADV: all 200 reached the stand", sum(1 for k in w.stand.probes()[-1][2] if k.startswith("X-H")), 200)


def k_fix1():
    """The fix round of t-109: m3 (cite the capture-time hash), m4 (capture_lines), m5 (the shared appender), m6 (override
    headers), m11 (the real lineage_root on the critic's scenario)."""
    # m11: the critic's scenario - D names a missing parent_retry and a real relaunch_of P; the survivor walks to P, a fake
    # that stopped at the first truthy key would key the pass by D
    with World(dispatches={D: running(parent_retry="gone", relaunch_of="P"),
                           "P": {"id": "P", "stage": "S7", "purpose": "other", "status": "returned_unaccepted"}}) as w:
        check_eq("m11 the real lineage_root: the pass is keyed by P, the first key whose value IS a record",
                 (w.http("case-A")[0], sorted(p.name for p in (w.task / "work" / "evidence" / "investigation").iterdir())),
                 (0, ["P"]))
    # m3: `record` cites the hash written into captures.jsonl at capture time, not the file's bytes now
    with World(register_lines=[]) as w:
        w.http("case-A")
        capture = w.captures()[0]
        recorded = capture["sha256"]
        (w.task / capture["path"]).write_text("edited after the probe", encoding="utf-8")
        res = w.record("case-A", "unverified")
        line = w.register.calls[0][0] if w.register.calls else {"evidence_refs": []}
        check_eq("m3 a capture edited after the probe: record cites the capture-time sha256 (append's judge then refuses it as stale)",
                 (res[0], [r["sha256"] for r in line["evidence_refs"]]), (0, [recorded]))
        check("m3 and that is not the hash of the file now", S.sha(w.task / capture["path"]) != recorded)
    with World(register_lines=[]) as w:
        w.http("case-A")
        lines = w.lines()
        lines[1]["sha256"] = None
        w.write_captures(lines)
        before = snap(w.task)
        res = w.record("case-A", "unverified")
        refused("m3 a capture line with no sha256 is not cited (no silent re-hash)", res, command="record",
                needle="has no sha256 in captures.jsonl")
        check("m3 and nothing is appended", w.register.calls == [] and snap(w.task) == before)
    # m6: the method-override family is refused before anything is sent, in any case
    with World() as w:
        before = snap(w.task)
        for name in ("X-HTTP-Method-Override", "x-http-method", "X-METHOD-OVERRIDE"):
            res = w.http("case-A", extra=["--header", f"{name}: DELETE"])
            refused(f"m6 {name}", res, needle="a read-only probe carries no method override")
            check_in(f"m6 {name}: the refusal names the header", name, res[2])
        check("m6 nothing sent (not even the login), nothing written", len(w.stand.calls) == 0 and snap(w.task) == before)
        check_eq("m6 control: an ordinary header still travels", w.http("case-A", extra=["--header", "X-Trace: t"])[0], 0)
    # m4: the one reader of the probes made
    with World() as w:
        check_eq("m4 capture_lines: no pass at all is []", IP.capture_lines(w.task), [])
        w.http("case-A")
        w.http("case-B")
        check_eq("m4 capture_lines: the captures of the pass, the header is not one", [c["n"] for c in IP.capture_lines(w.task)], [1, 2])
        w.write_captures(None, raw=(w.pass_folder() / "captures.jsonl").read_text(encoding="utf-8") + "{not json}\n")
        try:
            IP.capture_lines(w.task)
            failed = ""
        except ValueError as exc:
            failed = str(exc)
        check_in("m4 capture_lines: a damaged line is a ValueError naming it, never a count", "damaged line", failed)


def main():
    for step in (k_methods, k_login, k_login_source, k_shipped_budget, k_probe_cap, k_target_cap, k_timebox, k_first_reached, k_host_and_gate,
                 k_record, k_record_chain, k_dispatch_and_chain, k_lineage, k_absent, k_budget_rule, k_damage_state_pipeline,
                 k_secrets_and_unsaved, k_request_checks, k_refusal_battery, k_fix1):
        step()
    finish("test_investigation_probe")


if __name__ == "__main__":
    main()
