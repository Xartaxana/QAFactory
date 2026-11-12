#!/usr/bin/env python3
"""t-2277 FL-1 B: the `http` step of the walk session (fake client, fake browser, no network).

A walk is no longer UI only: `http <METHOD> <path|url> [--body-file F]` is a step of `walk_session.py step`, run by the ONE request executor
`manual_capture.http_call` (the same function `manual_capture.py http` calls once per call). A survey walk of a project with no profile that
fits a UI capture has no browser at all: each actor signs in once by the HTTP request the project records, and its steps are `http` only.
What is proved: the evidence is the screen steps' (one attempt, one JSON document per request, the quote check of `capture_cited`, the
`surprise:` lines); a request never leaves the walk's stand (two guards); a secret never reaches a file; a walk with a screen and a walk
without HTTP steps run as before.
Run: `python -B test_walk_http_step.py` (exit code = failures) or pytest.
"""
import contextlib
import json
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import test_manual_capture as T  # noqa: E402
import test_manual_capture_session as SS  # noqa: E402
import test_walk_places as P  # noqa: E402
import test_walk_session as W  # noqa: E402
import test_walk_survey_place as SV  # noqa: E402
from harness import finish  # noqa: E402

import scaffold as S  # noqa: E402

MC, WS = P.MC, P.WS
WALK = P.WALK
must, must_eq, must_in = P.must, P.must_eq, P.must_in
ITEM = "R-1"
BASE = "http://localhost:8080"
X = BASE + "/v1/x"
LOGIN = ("POST", BASE + "/v1/local-auth/login")
USER = SS.USER
PREVIEW_BASE = "https://stand.example.test/api"


def api_cfg(base=True, unknown_sign_in=False, probes=True, profiles=("api", "unit")):
    """A project with an API profile and NO profile that fits a UI capture: its survey walk has no screen."""
    cfg = SS.config(kind="harness_command", command="npx playwright test login.spec.ts") if unknown_sign_in else SS.config()
    cfg["run"] = {"parallel": False}
    cfg["profiles"] = [{"profile_id": p, "commands": {"one_test": {"argv": ["pytest", "<test-file>"], "cwd": "."}}} for p in profiles]
    cfg["execution"]["runtime_probes"] = {"api": cfg["execution"]["runtime_probes"]["api"]} if probes else {}
    if not base:
        del cfg["environments"][0]["base_url"]
    return cfg


@contextlib.contextmanager
def api_walk(routes=None, cfg=None, env=None, actors=("user",), items=(ITEM,), place="survey", start=True):
    """A walk on `cfg` with a fake HTTP client; the login of the actors answers a token unless `routes` says otherwise."""
    fake = S.FakeHttp({LOGIN: S.ok_json({"access_token": S.TOKEN}), **(routes or {})})
    with SV.survey(items=items, cfg=cfg or api_cfg(), env=env, actors=actors, start=False, place=place) as rig:
        MC.HTTP = fake
        rig.fake = fake
        try:
            if start:
                rig.walk.start()
            yield rig
        finally:
            MC.HTTP = None


def run(rig, text, item=ITEM, **fields):
    return rig.call("step", item=item, steps=text, **fields)


def attempt_of(rig, item=ITEM):
    return rig.walk.item_rec[item]["attempt"]


def sent(rig):
    """The requests the fake client got that are not the login."""
    return [c for c in rig.fake.calls if c[1] != LOGIN[1]]


def documents(rig, item=ITEM):
    """The saved request/response documents of the item's attempt, with their capture rows."""
    attempt = attempt_of(rig, item)
    return [(c, json.loads((rig.t.task / c["path"]).read_text(encoding="utf-8"))) for c in attempt._lines("captures.jsonl")
            if c["path"].endswith(".json") and "request-response" in c["path"]]


def body_file(rig, text, name="body.json"):
    path = rig.t.project / name      # outside the story folder: the files the walk wrote are searched for the secret
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path.as_posix()      # shlex reads a backslash as an escape: a path in a step is written with forward slashes


def tree(rig):
    return S.tree_text(rig.t.task)


# --- the one executor ----------------------------------------------------------------------------

def test_run_http_calls_http_call_per_call():
    t = S.make_task()
    seen = []
    real = MC.http_call

    def spy(*a, **k):
        seen.append((a[2], a[3], k["kind"]))
        return real(*a, **k)
    get_x, get_y = BASE + "/v1/x", BASE + "/v1/y"
    http = S.FakeHttp({("POST", BASE + "/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                       ("GET", get_x): S.ok_json({"id": "w1"}), ("GET", get_y): S.ok_json({"state": "on"})})
    try:
        with mock.patch.object(MC, "http_call", spy):
            code, out, err = T.http_run(t, http, "--method", "GET", "--url", get_x, "--state-url", get_y)
        must_eq("the CLI call ran", code, 0)
        must_eq("each request of the call went through `http_call`: the request, then the state", [(m, u, k) for m, u, k in seen],
                [("GET", get_x, "request_response"), ("GET", get_y, "state")])
        rows = T.jsonl(t.attempt_dir(T.API_CASE) / "captures.jsonl")
        must_eq("and left a request-response and a state capture", sorted(r["kind"] for r in rows), ["request_response", "state"])
    finally:
        S.cleanup(t)


def test_http_call_refuses_a_foreign_host_before_sending():
    with api_walk(actors=("guest",)) as rig:
        attempt = attempt_of(rig) if ITEM in rig.walk.item_rec else rig.walk._open_item(ITEM, "guest")["attempt"]
        out = MC.http_call(attempt, rig.fake, "GET", "http://evil.example.test/x", None, {}, hosts=rig.walk.http_hosts, timeout_s=5, spec_data=rig.walk.spec,
                           cfg=rig.walk.cfg, phase="supporting", proves=["request and response"], step_line="http GET http://evil.example.test/x")
        must_in("the executor itself refuses (a returned value, L-b), naming the allowed hosts", "Allowed hosts: ", out.get("refused", ""))
        must_eq("with no result and no step line", (out["result"], out["entry"]), (None, None))
        must_eq("and nothing was sent", rig.fake.calls, [])


# --- the walk's guards ----------------------------------------------------------------------------

def test_http_step_takes_no_stand_lease_inside_walk():
    taken = []      # (exit, status) of each step
    with mock.patch.object(MC, "_hold_stand", wraps=MC._hold_stand) as hold, api_walk(routes={("GET", X): S.ok_json({"ok": True})}) as rig:
        after_start = hold.call_count
        for _ in range(2):
            code, answer = run(rig, "http GET /v1/x")
            taken.append((code, answer["status"]))
        must_eq("the walk holds ONE lease, taken at the start", after_start, 1)
        must_eq("two `http` steps took none of their own", hold.call_count, after_start)
        must_eq("and both ran", taken, [(0, "done"), (0, "done")])
        must("the walk's lease is still held between the steps", f"walk:{WALK}" in P.leases(rig))


def test_http_step_writes_capture_in_walk_attempt():
    with api_walk(routes={("GET", X): S.ok_json({"id": "w1"}), ("POST", BASE + "/v1/y"): S.ok_json({"made": True}, status=201)}) as rig:
        path = body_file(rig, '{"name": "n"}')
        must_eq("a first call", run(rig, "http GET /v1/x")[0], 0)
        must_eq("a second call of the same item", run(rig, f"http POST /v1/y --body-file {path}")[0], 0)
        attempt = attempt_of(rig)
        must_eq("the item has ONE attempt, under the survey root", (attempt.name, attempt.dir.parent.name), ("a1", "survey-R-1"))
        docs = documents(rig)
        must_eq("both requests are documents of that attempt", len(docs), 2)
        must_eq("the document is the screen steps' format: request and response sides", sorted(docs[0][1]), ["request", "response"])
        must_eq("the POST's body is in the request side as sent", docs[1][1]["request"]["body"], '{"name": "n"}')
        must_eq("its status is in the response side", (docs[0][1]["response"]["status"], docs[1][1]["response"]["status"]), (200, 201))
        rows = attempt._lines("steps.jsonl")
        must_eq("steps.jsonl holds both steps as `http`, ok", [(r["command"], r["outcome"]) for r in rows], [("http", "ok")] * 2)
        run(rig, "http GET /v1/x", item="R-2")
        must_eq("another item is another attempt", attempt_of(rig, "R-2").dir.parent.name, "survey-R-2")


def test_http_step_host_outside_stand_refused():
    with api_walk(routes={("GET", X): S.ok_json({})}) as rig:
        for address in ("http://evil.example.test/x", "http://localhost:9999/x", "http://localhost:8080@evil.example.test/",
                        "ftp://localhost:8080/x"):
            code, answer = run(rig, f"http GET {address}")
            must(f"{address} is refused whole (exit 2)", code == 2 and answer["status"] == "refused", str(answer)[:300])
        code, answer = run(rig, "http GET http://evil.example.test/x")
        must_in("the refusal lists the allowed hosts (J-C1): the walk's OWN stand only (B2)", "Allowed hosts: http://localhost:5173, http://localhost:8080.", answer["text"])
        must_eq("nothing was sent and no attempt was opened", (sent(rig), rig.walk.item_rec), ([], {}))
    with api_walk(routes={}, env="preview", actors=("guest",)) as rig:
        code, answer = run(rig, f"http GET {X}")
        must_eq("a host of ANOTHER stand is refused on a walk of `preview`", code, 2)
        attempt = rig.walk._open_item(ITEM, "guest")["attempt"]
        step = {"n": 1, "word": "http", "line": f"http GET {X}", "args": ["GET", X], "url": X, "hosts": sorted(rig.walk.http_hosts)}
        entry = MC._run_http_word(rig.walk.backends["guest"], attempt, step, 5, rig.walk.cfg, rig.walk.spec, rig.walk.accounts["guest"])["entry"]
        must_eq("the second guard (`http_call`) ends the step `refused` and sends nothing", (entry["outcome"], rig.fake.calls), ("refused", []))


def test_http_step_relative_path_uses_stand_base_url():
    with api_walk(routes={("GET", X): S.ok_json({}), ("GET", PREVIEW_BASE + "/v1/x"): S.ok_json({})}) as rig:
        run(rig, "http GET /v1/x")
        must_eq("a path is joined to the base_url of the walk's stand", rig.fake.calls[-1][1], X)
        must_eq("the document records the address that was used", documents(rig)[0][1]["request"]["url"], X)
        must_eq("a full URL on the stand is itself", run(rig, "http GET " + X)[0], 0)
    with api_walk(routes={("GET", PREVIEW_BASE + "/v1/x"): S.ok_json({})}, env="preview", actors=("guest",)) as rig:
        run(rig, "http GET /v1/x")
        must_eq("on `--env preview` the base_url is that row's, path prefix kept", rig.fake.calls[-1][1], PREVIEW_BASE + "/v1/x")


def test_http_step_without_base_url_refused():
    with api_walk(cfg=api_cfg(base=False), actors=("guest",)) as rig:
        code, answer = run(rig, "http GET /v1/x")
        must_eq("a path on a stand with no base_url is refused", code, 2)
        must("and the refusal names the stand and the way on", "records no base_url" in answer["text"] and "full URL" in answer["text"], answer["text"])
        must_eq("a full URL on the frontend host still passes the check", run(rig, "http GET http://localhost:5173/health")[0], 0)


def test_http_word_outside_walk_refused():
    spec = MC.spec()
    try:
        MC.parse_steps("http GET /v1/x", spec, need_goto=False)
    except ValueError as exc:
        must("a parser with no `http_ok` refuses the word, naming the walk command and the single-request door",
             "walk_session.py step" in str(exc) and "manual_capture.py http" in str(exc), str(exc))
    else:
        raise AssertionError("`http` is a walk word")
    must_eq("with `http_ok` it parses", [s["word"] for s in MC.parse_steps("http GET /v1/x", spec, need_goto=False, http_ok=True)], ["http"])
    t = S.make_task()
    try:
        code, out, err, _b = T.ui_run(t, f"goto {T.UI}\nhttp GET /v1/x\n")
        must_eq("`manual_capture.py ui` refuses a steps file with the word (exit 2)", code, 2)
        must_in("and says where the word lives", "walk_session.py step", err)
    finally:
        S.cleanup(t)


def test_http_word_unknown_method_refused():
    with api_walk() as rig:
        code, answer = run(rig, "http FETCH /v1/x")
        must("an unknown method is refused with the list", code == 2 and "none of GET, POST" in answer["text"], answer["text"])
        must_eq("a lower-case known method is the method", run(rig, "http get /v1/x")[1]["status"], "done")


def test_http_word_missing_path_refused():
    with api_walk() as rig:
        code, answer = run(rig, "http GET")
        must("a step with no address says its shape", code == 2 and "<METHOD> <path|url>" in answer["text"], answer["text"])
        code, answer = run(rig, "http GET v1/x")
        must("an address that is neither `/path` nor a URL is refused", code == 2 and "neither a path" in answer["text"], answer["text"])


def test_http_word_body_flag_without_file_refused():
    with api_walk() as rig:
        for line in ("http POST /v1/x --body-file", "http POST /v1/x extra", "http POST /v1/x --data a.json x"):
            code, answer = run(rig, line)
            must(f"`{line}` is refused with the flag's shape", code == 2 and "--body-file <file>" in answer["text"], answer["text"])


def test_http_word_non_ascii_path_refused():
    with api_walk() as rig:
        code, answer = run(rig, "http GET /v1/caf" + chr(0xE9))
        must("a non-ASCII path is refused with the door", code == 2 and "percent-encode" in answer["text"], answer["text"])
        must_eq("the percent-encoded spelling is sent", (run(rig, "http GET /v1/caf%C3%A9")[0], rig.fake.calls[-1][1]), (0, BASE + "/v1/caf%C3%A9"))
        long_path = "/v1/" + "a" * 3000
        must_eq("a very long path is a request like any other (no limit of ours)", run(rig, "http GET " + long_path)[0], 0)


def test_http_step_body_file_unreadable_refused():
    with api_walk() as rig:
        code, answer = run(rig, f"http POST /v1/x --body-file {(rig.t.task / 'missing.json').as_posix()}")
        must("an unreadable body file refuses the call, naming it", code == 2 and "cannot be read" in answer["text"], answer["text"])
        code, answer = run(rig, f"http POST /v1/x --body-file {rig.t.task.as_posix()}")
        must_eq("a folder is no body", code, 2)
        must_eq("nothing was sent", sent(rig), [])


def test_http_step_generated_placeholder_refused():
    with api_walk() as rig:
        path = body_file(rig, '{"name": "{generated_username}", "pw": "{generated_password}"}')
        code, answer = run(rig, f"http POST /v1/x --body-file {path}")
        must("a body with a generated-value placeholder is refused: a walk creates no accounts", code == 2 and "creates no accounts" in answer["text"], answer["text"])
        code, answer = run(rig, "http GET /v1/{generated_username}")
        must_eq("a placeholder in the address is refused too", code, 2)
        must_eq("nothing was sent", sent(rig), [])


def test_http_step_secret_in_request_refused():
    with api_walk() as rig:
        path = body_file(rig, "api_key: 'abcdefghijklmnopqrstuvwx'")
        code, answer = run(rig, f"http POST /v1/x --body-file {path}")
        must("a body that matches `secret_content_patterns` is refused", code == 2 and "secret_content_patterns[1]" in answer["text"], answer["text"])
        must_eq("nothing was sent", sent(rig), [])
        must("and the secret is in no file the walk wrote", "abcdefghijklmnopqrstuvwx" not in tree(rig))


# --- the surprise lines --------------------------------------------------------------------------

def surprises(rig, item=ITEM):
    return [r for r in MC.jsonl_rows(attempt_of(rig, item).dir / "surprises.jsonl") if r.get("line") == "surprise"]


def test_http_redirect_is_status_surprise_and_not_followed():
    route = MC.HttpResult(302, [("Location", "/login?next=/v1/x"), ("Content-Type", "text/plain")], b"", 0.01)
    with api_walk(routes={("GET", X): route}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        must_eq("a 3xx is an answer, the call is done", (code, answer["status"]), (0, "done"))
        rows = surprises(rig)
        must_eq("one `status` line carries the number", [(r["kind"], r["status"], r["word"]) for r in rows], [("status", 302, "http")])
        must_in("its fact says where the redirect points, path only (no query)", "redirect to /login", rows[0]["fact"])
        must("the query is not in the fact", "next=" not in rows[0]["fact"])
        must_eq("nothing followed the redirect: ONE request", len(sent(rig)), 1)
        must_in("the answer shows the line as a screen step's", "surprise:", " ".join(answer["steps"][0]["surprise"]))
        kinds = [r["kinds_checked"] for r in MC.jsonl_rows(attempt_of(rig).dir / "surprises.jsonl") if r.get("line") == "detector"]
        must_eq("and the detector line says the step was watched, by the http kinds", kinds, [["status", "blocked_host", "text"]])


def test_http_redirect_to_foreign_host_blocked_host():
    route = MC.HttpResult(301, [("Location", "https://evil.example.test/steal?x=1")], b"", 0.01)
    with api_walk(routes={("GET", X): route}) as rig:
        run(rig, "http GET /v1/x")
        must_eq("a 3xx to a host outside the walk's stand is `status` and `blocked_host`", [r["kind"] for r in surprises(rig)], ["status", "blocked_host"])
        must_in("the host is named, not followed", "evil.example.test", surprises(rig)[1]["fact"])
        must_eq("and still ONE request", len(sent(rig)), 1)


def test_http_4xx_5xx_status_surprise():
    routes = {("GET", X): MC.HttpResult(404, [("Content-Type", "text/plain")], b"no", 0.01),
              ("GET", BASE + "/v1/z"): MC.HttpResult(503, [("Content-Type", "text/plain")], b"down", 0.01)}
    with api_walk(routes=routes) as rig:
        code, answer = run(rig, "http GET /v1/x")
        must_eq("a 404 is recorded, the call is NOT stopped (a negative step provokes it)", (code, answer["status"]), (0, "done"))
        must_eq("with its number", [(r["kind"], r["status"]) for r in surprises(rig)], [("status", 404)])
        code, answer = run(rig, "http GET /v1/z")
        must_eq("a 5xx stops the call by the default rule (`status:500-599` reads the number)", (code, answer["status"]), (1, "stopped"))
        must_eq("the stop is a surprise with the status", (answer["stopped_at"]["reason"], answer["stopped_at"]["facts"][0]["status"]), ("surprise", 503))
        code, answer = run(rig, "http GET /v1/z", stop_on=["none"])
        must_eq("`--stop-on none` lets the same 5xx through", (code, answer["status"]), (0, "done"))


def test_http_broken_json_text_surprise():
    routes = {("GET", X): MC.HttpResult(200, [("Content-Type", "application/json")], b'{"a": ', 0.01),
              ("GET", BASE + "/v1/ok"): S.ok_json({"a": 1}),
              ("GET", BASE + "/v1/page"): MC.HttpResult(200, [("Content-Type", "text/html")], b"<html", 0.01)}
    with api_walk(routes=routes) as rig:
        run(rig, "http GET /v1/x")
        must_eq("an answer that says JSON and does not parse is a `text` line", [r["kind"] for r in surprises(rig)], ["text"])
        run(rig, "http GET /v1/ok")
        run(rig, "http GET /v1/page")
        must_eq("a good JSON and an HTML page add none", len(surprises(rig)), 1)


# --- the document: cut, encoding, emptiness ---------------------------------------------------------

def plain(body, status=200, ctype="text/plain"):
    return MC.HttpResult(status, [("Content-Type", ctype)], body, 0.01)


def test_http_body_at_cap_whole():
    with api_walk(routes={("GET", X): plain(b"a" * MC.BODY_CAP)}) as rig:
        run(rig, "http GET /v1/x")
        capture, doc = documents(rig)[0]
        must_eq("a body of exactly BODY_CAP bytes is stored whole", (doc["response"]["truncated"], doc["response"]["body_bytes_stored"]), (False, MC.BODY_CAP))
        must("and the capture carries no cut limitation", "limitation" not in capture)


def test_http_body_beyond_cap_cut_with_cut_words():
    with api_walk(routes={("GET", X): plain(b"a" * (MC.BODY_CAP + 1))}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        capture, doc = documents(rig)[0]
        must_eq("one byte over the cap is cut", (doc["response"]["truncated"], doc["response"]["body_bytes_stored"]), (True, MC.BODY_CAP))
        must_in("the capture says it was cut, in the one sentence (`CUT_WORDS`)", MC.CUT_WORDS, capture["limitation"])
        must_in("and the answer carries the limitation", MC.CUT_WORDS, " ".join(answer["limitations"]))
        must_eq("the walk's second rule of cutting does not exist: the same text as `manual_capture.py http`", capture["limitation"], MC._limit_words("response"))


def test_http_binary_body_base64():
    with api_walk(routes={("GET", X): plain(b"\xff\xfe\x00\x01", ctype="application/octet-stream")}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        doc = documents(rig)[0][1]
        must_eq("a non-UTF-8 body is stored as base64 (the one rule)", (doc["response"]["body_encoding"], doc["response"]["body"]), ("base64", "//4AAQ=="))
        must_in("and the excerpt says it is not quoted", "base64", answer["last_excerpt"])


def test_http_empty_body():
    routes = {("GET", X): plain(b"", status=204, ctype="application/json"), ("POST", BASE + "/v1/y"): S.ok_json({})}
    with api_walk(routes=routes) as rig:
        code, answer = run(rig, "http GET /v1/x")
        doc = documents(rig)[0][1]
        must_eq("an empty answer is a document with an empty body", (code, doc["response"]["body"], doc["response"]["body_bytes_stored"]), (0, "", 0))
        must_eq("no excerpt and no `text` surprise for nothing to read", (answer["last_excerpt"], surprises(rig)), ("", []))
        code, answer = run(rig, f"http POST /v1/y --body-file {body_file(rig, b'')}")
        must_eq("an empty body file is a request with no body", (code, documents(rig)[1][1]["request"]["body"]), (0, ""))


# --- secrets ---------------------------------------------------------------------------------------

def test_http_secrets_redacted_and_account_hidden():
    echo = S.ok_json({"owner": USER, "note": "mine"}, headers=[("Set-Cookie", "sid=SENTINEL-COOKIE-77"), ("Authorization", "Bearer SENTINEL-AUTH-88")])
    with api_walk(routes={("GET", X): echo}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        doc = documents(rig)[0][1]
        must_eq("a header of `redact_headers` is redacted", (doc["response"]["headers"]["Set-Cookie"], doc["response"]["headers"]["Authorization"]),
                ("[redacted]", "[redacted]"))
        must("the actor's account name echoed by the answer is hidden", USER not in json.dumps(doc) and "[redacted]" in doc["response"]["body"], json.dumps(doc)[:300])
        text = tree(rig)
        must("neither the bearer token, the cookie value nor the password is in any file of the walk",
             not any(w in text for w in (S.TOKEN, "SENTINEL-COOKIE-77", "SENTINEL-AUTH-88", "pw-user")))
        must_eq("the request side carries no Authorization (the token is added below the record)", "Authorization" in doc["request"]["headers"], False)
        must_eq("yet the stand got it", rig.fake.calls[-1][2].get("Authorization"), "Bearer " + S.TOKEN)


def test_http_secret_in_response_not_saved_no_excerpt():
    leaky = plain(b"x api_key: 'abcdefghijklmnopqrstuvwxyz123456' y")
    with api_walk(routes={("GET", X): leaky}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        must_eq("the step ends refused and the call stops", (code, answer["steps"][0]["outcome"]), (1, "refused"))
        must_in("the detail says the answer was NOT saved", "NOT saved", answer["stopped_at"]["detail"])
        must_eq("no excerpt", answer["last_excerpt"], "")
        must_eq("no document was stored", documents(rig), [])
        must("and the secret is in no file", "abcdefghijklmnopqrstuvwxyz123456" not in tree(rig))


def test_http_timeout_is_step_outcome_not_surprise():
    def stalled(headers, body):
        raise MC.StepTimeout(7.5)
    with api_walk(routes={("GET", X): stalled}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        must_eq("a timeout is the outcome of the step, the call stops", (code, answer["steps"][0]["outcome"], answer["stopped_at"]["reason"]), (1, "timeout", "timeout"))
        must_eq("no `surprise` line and no document", (surprises(rig), documents(rig)), ([], []))
    slow = MC.HttpResult(200, [], b"late", 9999.0)
    with api_walk(routes={("GET", X): slow}) as rig:
        must_eq("an answer that came after the limit is a timeout too", run(rig, "http GET /v1/x")[1]["steps"][0]["outcome"], "timeout")


def test_http_excerpt_from_saved_document():
    body = "ID:" + USER + ";" + "b" * 600
    with api_walk(routes={("GET", X): plain(body.encode("utf-8"))}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        saved = documents(rig)[0][1]["response"]["body"]
        must_eq("the excerpt is the first 300 characters of the SAVED document's body", answer["last_excerpt"], saved[:300])
        must("so the account name the live answer held is hidden in it", USER not in answer["last_excerpt"] and answer["last_excerpt"].startswith("ID:[redacted]"),
             answer["last_excerpt"][:60])


def test_capture_cited_accepts_http_capture():
    with api_walk(routes={("GET", X): S.ok_json({"title": "Cart ready", "count": 3})}) as rig:
        run(rig, "http GET /v1/x")
        path = documents(rig)[0][0]["path"]
        must_eq("a fragment of the response is cited by the one quote check", WS.capture_cited(rig.t.task, WALK, ITEM, path, "Cart ready"), "")
        must_eq("with the stand named", WS.capture_cited(rig.t.task, WALK, ITEM, path, "count", stand="localhost"), "")
        why = WS.capture_cited(rig.t.task, WALK, ITEM, path, "a title nobody sent")
        must("a made-up quote is refused with a door", why != "" and "Door:" in why, why)
        must_eq("the record names the walk's profile as the HTTP one", WS.read_record(rig.t.task, WALK)["profiles"], {"http": "api"})


# --- the walk with no screen -----------------------------------------------------------------------------

def test_http_only_walk_opens_without_browser():
    with api_walk(routes={("GET", X): S.ok_json({})}) as rig:
        must_eq("no browser was made", rig.made, [])
        rec = WS.read_record(rig.t.task, WALK)
        must_eq("the walk is ready, a survey on the HTTP profile", (rec["state"], rec["place"], rec["profiles"]), ("ready", "survey", {"http": "api"}))
        must_eq("the actor is signed in by code", rec["sessions"]["user"]["signed_in"], True)
        must_eq("a step runs with no page", run(rig, "http GET /v1/x")[1]["status"], "done")
        probes = attempt_of(rig)._lines("probes.jsonl")
        must_eq("the start probe is the HTTP profile's, `http`", [(p["when"], p["profile"], p["command"]) for p in probes], [("start", "api", "http")])
        must_eq("the close ends cleanly with the end probe", (rig.call("close")[0], [p["when"] for p in attempt_of(rig)._lines("probes.jsonl")]), (0, ["start", "end"]))
        must_eq("still no browser", rig.made, [])


def test_http_only_actor_bearer_login_once():
    with api_walk(routes={("GET", X): S.ok_json({})}, actors=("user", "guest")) as rig:
        logins = [c for c in rig.fake.calls if c[1] == LOGIN[1]]
        must_eq("the named actor signed in ONCE at open (the guest never does)", len(logins), 1)
        for _ in range(3):
            run(rig, "http GET /v1/x")
        must_eq("three steps, still one login", len([c for c in rig.fake.calls if c[1] == LOGIN[1]]), 1)
        gets = [c for c in rig.fake.calls if c[0] == "GET"]
        must_eq("every request carried the token", [c[2].get("Authorization") for c in gets], ["Bearer " + S.TOKEN] * 3)
        code, answer = run(rig, "http GET /v1/x", **{"actor": "guest"})
        must_eq("a guest's request carries none", (code, rig.fake.calls[-1][2].get("Authorization")), (0, None))
    with api_walk(routes={("GET", X): S.ok_json({})}, actors=("admin",)) as rig:
        must("any account the factory has, not only `default`: the admin role signed in as ITSELF", any(SS.ADMIN in json.loads(c[3]).values()
                                                                                                         for c in rig.fake.calls if c[1] == LOGIN[1]))


def test_http_only_unknown_sign_in_opens_walk_and_fails_steps():
    with api_walk(cfg=api_cfg(unknown_sign_in=True), routes={("GET", X): S.ok_json({})}) as rig:
        rec = WS.read_record(rig.t.task, WALK)
        must_eq("the walk OPENS", rec["state"], "ready")
        session = rec["sessions"]["user"]
        must("the session says unsigned and gives the door", session["signed_in"] is False and "harness_command" in session["note"] + str(rig.walk.backends["user"].sign_in_problem), str(session))
        code, answer = run(rig, "http GET /v1/x")
        must_eq("the step ends `failed` and stops the call", (code, answer["steps"][0]["outcome"], answer["stopped_at"]["reason"]), (1, "failed", "failed"))
        must("the detail names the closed cause and the actor", answer["stopped_at"]["detail"].startswith("http_sign_in_unknown: user: "), answer["stopped_at"]["detail"])
        must_eq("and NOTHING was sent", [c for c in rig.fake.calls if c[0] == "GET"], [])
    with api_walk(routes={("GET", X): S.ok_json({})}, cfg=api_cfg(), actors=("nobody-here",)) as rig:
        must("an actor with no account opens unsigned too, its steps failing before the send",
             WS.read_record(rig.t.task, WALK)["sessions"]["nobody-here"]["signed_in"] is False
             and run(rig, "http GET /v1/x")[1]["steps"][0]["outcome"] == "failed")


def test_ui_step_in_http_only_walk_refused():
    with api_walk(routes={("GET", X): S.ok_json({})}) as rig:
        code, answer = run(rig, "goto http://localhost:5173/")
        must("a screen word in a walk with no screen is refused whole (exit 2), with the walk's own word as the door",
             code == 2 and "has no screen" in answer["text"] and "http <METHOD>" in answer["text"], answer["text"])
        code, answer = run(rig, 'http GET /v1/x\nclick "#a"')
        must_eq("a mixed call is refused whole: the request before the screen word was NOT sent", (code, [c for c in rig.fake.calls if c[0] == "GET"]), (2, []))
        for op in ("look", "final"):
            code, answer = rig.call(op, item=ITEM)
            must(f"`{op}` is refused with the same door", code == 2 and "has no screen" in answer["text"], answer["text"])


def test_no_surface_open_refused():
    with api_walk(cfg=api_cfg(probes=False, profiles=("unit", "lint")), start=False) as rig:
        try:
            rig.walk.start()
        except WS.ServerDead as dead:
            must_eq("neither a UI nor an HTTP profile: exit 2, cause `no_reachable_surface`", (dead.code, dead.cause), (2, "no_reachable_surface"))
            must_in("the refusal says what is expected", "capabilities hold `web` or `api`", dead.reason)
        else:
            raise AssertionError("a walk with no surface must not open")
        must("nothing was captured: no attempt, no request, no browser", not rig.fake.calls and not rig.made
             and not (rig.t.task / "work" / "evidence" / "manual").exists())
        must_eq("the record says dead and carries the cause", (WS.read_record(rig.t.task, WALK)["state"], WS.read_record(rig.t.task, WALK)["cause"]), ("dead", "no_reachable_surface"))
        args = WS.build_parser().parse_args(["open", "--task-root", str(rig.t.task), "--walk", "S6-nosurface", "--items", ITEM, "--actor", "guest", "--place", "survey"])

        def dead_server(argv, log):
            WS.event_store.atomic_json(WS.record_path(rig.t.task, "S6-nosurface"), {"walk": "S6-nosurface", "state": "dead", "pid": 1, "reason": "no surface",
                                                                                      "cause": "no_reachable_surface", "actors": ["guest"], "items": [ITEM]})
            return type("H", (), {"kill": lambda self: None})()
        WS.SEAMS["spawn"] = dead_server
        try:
            with contextlib.redirect_stdout(open(rig.t.task / "out.txt", "w")), contextlib.redirect_stderr(open(rig.t.task / "err.txt", "w")):
                code = WS.open_walk(args, wait_s=0.5)
        finally:
            WS.SEAMS["spawn"] = None
        must_eq("`open` ends 2 (a refused call), not 3 (a session that failed to start)", code, 2)


def test_several_ui_profiles_survey_cause():
    cfg = api_cfg(probes=False)
    cfg["profiles"] = [{"profile_id": p, "capabilities": ["web"], "commands": {"one_test": {"argv": ["pytest", "<test-file>"], "cwd": "."}}} for p in ("ui1", "ui2")]
    with api_walk(cfg=cfg, start=False) as rig:
        try:
            rig.walk.start()
        except WS.ServerDead as dead:
            must_eq("several UI profiles and no plan: the cause is `profile_not_chosen`", dead.cause, "profile_not_chosen")
        else:
            raise AssertionError("two UI profiles and no way to choose must refuse")
    with SV.survey(cfg=cfg, place="settle", items=("p1",), start=False) as rig:
        try:
            rig.walk.start()
        except WS.ServerDead as dead:
            must_eq("a place other than survey keeps the refusal it had: no new cause", dead.cause, "")
        else:
            raise AssertionError("two UI profiles and no way to choose must refuse")


# --- the fix round of t-2450 (B1, B2, F3-F6, L-a) -------------------------------------------------------------

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2ln"      # what a Keycloak / OIDC local login issues


def test_run_http_jwt_bearer_unchanged():
    t = S.make_task()
    try:
        cfg = MC.load_config(t.task)[0]
        must("the project's config carries a JWT-shaped secret pattern (else this test cannot fail)",
             any("eyJ" in str(p) for p in cfg.get("secret_content_patterns") or []), str(cfg.get("secret_content_patterns")))
        url = BASE + "/v1/workflows/w1"
        http = S.FakeHttp({LOGIN: S.ok_json({"access_token": JWT}), ("GET", url): S.ok_json({"id": "w1"})})
        code, out, err = T.http_run(t, http, "--method", "GET", "--url", url)
        must_eq("a JWT Bearer the tool itself added is not a request the role wrote: exit 0 as before", code, 0)
        must_eq("one capture", len(T.jsonl(t.attempt_dir(T.API_CASE) / "captures.jsonl")), 1)
        must_eq("and the stand got the token", http.calls[-1][2].get("Authorization"), "Bearer " + JWT)
        must("the token is in no file the call wrote", JWT not in S.tree_text(t.task))
        body = t.project / "secret-body.json"
        body.write_text("api_key: 'abcdefghijklmnopqrstuvwx'", encoding="utf-8")
        http2 = S.FakeHttp({LOGIN: S.ok_json({"access_token": JWT}), ("POST", url): S.ok_json({})})
        code, out, err = T.http_run(t, http2, "--method", "POST", "--url", url, "--body-file", body.as_posix())
        must_eq("a secret in the BODY is still refused (exit 2), nothing sent", (code, [c for c in http2.calls if c[0] == "POST"]), (2, []))
    finally:
        S.cleanup(t)


def test_http_step_no_env_other_stand_refused():
    other = "https://stand.example.test/api/v1/x"
    with api_walk(routes={("GET", other): S.ok_json({"leak": True}), ("GET", X): S.ok_json({})}) as rig:
        must_eq("no --env: the walk's stand is the first row", rig.walk.stand.get("name"), "localhost")
        code, answer = run(rig, f"http GET {other}")
        must_eq("a host of ANOTHER stand is refused on a walk with no --env", (code, answer["status"]), (2, "refused"))
        must_in("naming the walk's own hosts", "Allowed hosts: http://localhost:5173, http://localhost:8080.", answer["text"])
        must_eq("nothing was sent: no token left for another stand", [c for c in rig.fake.calls if c[0] == "GET"], [])
        attempt = rig.walk._open_item(ITEM, "user")["attempt"]
        step = {"n": 1, "word": "http", "line": f"http GET {other}", "args": ["GET", other], "url": other, "hosts": sorted(rig.walk.http_hosts)}
        out = MC._run_http_word(rig.walk.backends["user"], attempt, step, 5, rig.walk.cfg, rig.walk.spec, rig.walk.accounts["user"])
        must_eq("the second guard ends the step `refused` too, sending nothing", (out["entry"]["outcome"], [c for c in rig.fake.calls if c[0] == "GET"]), ("refused", []))
        must_eq("while the walk's own stand is reached", run(rig, "http GET /v1/x")[0], 0)


def test_http_step_final_on_screenless_walk_refused():
    with api_walk(routes={("GET", X): S.ok_json({})}) as rig:
        code, answer = run(rig, "http GET /v1/x", final=True)
        must("`step --final` with no screen is refused whole, with the walk's own door (no AttributeError)",
             code == 2 and "has no screen" in answer["text"] and "http <METHOD>" in answer["text"], str(answer)[:300])
        must_eq("nothing ran: no request, no attempt, no failed ui row", (sent(rig), rig.walk.item_rec), ([], {}))


def test_http_malformed_location_is_a_surprise_not_a_crash():
    route = MC.HttpResult(302, [("Location", "http://[::1/x")], b"", 0.01)
    with api_walk(routes={("GET", X): route}) as rig:
        code, answer = run(rig, "http GET /v1/x")
        must_eq("the step is done, the recorder did not raise", (code, answer["status"], answer["steps"][0]["outcome"]), (0, "done", "ok"))
        rows = surprises(rig)
        must_eq("a `status` line says the address does not parse", [r["kind"] for r in rows][:1], ["status"])
        must_in("in words", "does not parse", rows[0]["fact"])
        must_eq("and the document is saved", len(documents(rig)), 1)


def test_http_keeps_the_typing_run():
    must("`http` is a network-only step: it joins `steps.type.keeps_run` as fail_request / restore_request do",
         {"http", "fail_request", "restore_request"} <= set(MC.spec()["steps"]["type"]["keeps_run"]))
    with api_walk(routes={("GET", X): S.ok_json({})}) as rig:
        run(rig, "http GET /v1/x")
        attempt = attempt_of(rig)
        attempt.type_chain = {"sentinel": 1}
        run(rig, "http GET /v1/x")
        must_eq("an `http` step between two `type`s leaves the typing run as it was", attempt.type_chain, {"sentinel": 1})


def test_single_api_profile_survey_walk_is_screenless():
    with api_walk(cfg=api_cfg(profiles=("api",)), routes={("GET", X): S.ok_json({})}) as rig:
        must_eq("a survey walk whose only profile fits HTTP and not UI has no browser", (rig.walk.screenless, rig.walk.profile, rig.made), (True, "api", []))
        must_eq("its actor is signed in by the HTTP login and the step carries the Bearer", (run(rig, "http GET /v1/x")[0], rig.fake.calls[-1][2].get("Authorization")),
                (0, "Bearer " + S.TOKEN))
    with SV.survey(cfg=api_cfg(profiles=("api",)), place="settle", items=("p1",), start=False) as rig:
        rig.walk.start()
        must_eq("a place other than survey keeps its screen", rig.walk.screenless, False)


# --- a walk with a screen -----------------------------------------------------------------------------

def browser_http(self, method, url, headers, body, timeout_s):
    self.http_seen = [*getattr(self, "http_seen", []), (method, url, dict(headers))]
    return S.ok_json({"ok": True})


def test_walk_with_ui_and_http_steps_shares_attempt_probes():
    with mock.patch.object(W.WB, "http", browser_http, create=True), SV.survey() as rig:
        rec = WS.read_record(rig.t.task, WALK)
        must_eq("a project with a UI profile walks with the screen, as before", (rig.walk.screenless, rec["profiles"]), (False, {"ui": rig.walk.profile}))
        run_code, answer = rig.step(W.GO, item=ITEM)
        probes_before = len(attempt_of(rig)._lines("probes.jsonl"))
        code, answer = run(rig, "http GET " + X + "\n")
        must_eq("the `http` step ran in the browser's own context (the actor's cookies)", (code, rig.made[0].http_seen[0][:2]), (0, ("GET", X)))
        must_eq("and the factory's own client sent nothing", rig.fake.calls if hasattr(rig, "fake") else [], [])
        attempt = attempt_of(rig)
        must_eq("the screen steps and the request are ONE attempt", sorted({r["command"] for r in attempt._lines("steps.jsonl")}), ["http", "ui"])
        must_eq("the HTTP step added no probe: the attempt's probes are the walk's profile's", (len(attempt._lines("probes.jsonl")), {p["profile"] for p in attempt._lines("probes.jsonl")}),
                (probes_before, {rig.walk.profile}))
        must_eq("the request is a document of that attempt", len(documents(rig)), 1)
        must_eq("the walk's record is unchanged: `ui` profile, one attempt", (WS.read_record(rig.t.task, WALK)["profiles"], WS.read_record(rig.t.task, WALK)["attempts"]),
                ({"ui": rig.walk.profile}, {ITEM: "a1"}))
        code, answer = run(rig, "http GET http://evil.example.test/x")
        must_eq("a walk with a screen refuses a foreign host too", code, 2)


def test_s6_walk_without_http_unchanged():
    rig = W.Rig().start()
    try:
        code, answer = rig.step(W.GO, item=W.CASE)
        must_eq("an S6 case walk runs as it did", (code, answer["status"], rig.walk.screenless, rig.walk.surface), (0, "done", False, "ui"))
        rec = WS.read_record(rig.t.task, WALK)
        must_eq("its record names the UI profile", list(rec["profiles"]), ["ui"])
        rows = rig.walk.item_rec[W.CASE]["attempt"]._lines("steps.jsonl")
        must_eq("the rows are the screen's alone", {r["command"] for r in rows}, {"ui"})
        kinds = [r["kinds_checked"] for r in rig.walk.item_rec[W.CASE]["attempt"]._lines("surprises.jsonl") if r.get("line") == "detector"]
        must_eq("the detector watched the page kinds, not the http ones", kinds, [MC.spec()["surprise"]["kinds"]])
        must_eq("the browser was made as before and the start probe is `ui`", (len(rig.made), rig.walk.sink.rows[0]["command"]), (1, "ui"))
    finally:
        rig.done()


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_walk_http_step")


if __name__ == "__main__":
    main()
