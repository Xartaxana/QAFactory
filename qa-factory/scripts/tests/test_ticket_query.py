#!/usr/bin/env python3
"""t-1685 N1-4: `ticket_adapter.py query` (a GET of the configured tracker API at a path the ROLE chose) and the refusal of a
LINK given to `peek` / `collect` where a ticket key belongs.

What is proved (the Q-keys of spec t-1685 N1-4; the fake opener is the one of test_source_inventory.py):
  * Q1  a relative path -> one GET to base_url + path, the answer saved whole, ONE stdout line with `total=37` and `issues[2]`;
  * Q2  an absolute URL on another host -> usage, the opener never called;   Q3  the tracker's own absolute URL -> accepted;
  * Q4  a path with no leading `/` -> usage;   Q5  no `direct_api` -> exit 3 naming `record-source`, no request;
  * Q6  the token value is in no output byte;   Q7  an answer of exactly QUERY_MAX_BYTES is saved, one byte more is refused
        and nothing is saved (AT and BEYOND);   Q8  404 -> the named sentence, nothing saved;   Q9  `--save` outside work/ -> usage;
  * Q10 `peek <link>` -> usage naming `peek APP-1` and `query`, the inventory byte-identical, the opener never called;
  * Q11 `peek APP-1` unchanged (positive control);   Q12 adversarial links: upper-cased scheme, a link with no key, two keys.
  * Q13 (t-1685 N2, the leftover of N1) `get`, `get --output`, `children` and `freshness` refuse a link as a key exactly as peek/collect
        do; `get APP-1` still reaches the tracker.

Mutations -> killing key (this file): `_query` accepts another host -> Q2; the summary prints the body -> Q6/Q1 (one line, no body);
the size check `>=` instead of `>` -> Q7; the link refusal dropped -> Q10; dropped from `get`/`children` -> Q13 (`get`, `children`), from `freshness` -> Q13 (`freshness`).
"""
import contextlib
import io
import json
import os
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import source_inventory as SI  # noqa: E402
import ticket_adapter as TA  # noqa: E402

BASE = "https://jira.example.test"
TOKEN = "s3cr3t-token-value"
CFG = {"adapters": {"ticket": {"kind": "jira", "direct_api": {
    "base_url": BASE, "auth_type": "basic_token", "username_ref": "QA_USER", "secret_ref": "QA_TOKEN"}}}}
CFG_NONE = {"adapters": {"ticket": {"kind": "jira"}}}
REAL = SI.client_from_config


class Response:
    def __init__(self, data, url):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.headers = {"Content-Type": "application/json"}
        self.url = url

    def read(self):
        return self.data

    def geturl(self):
        return self.url


class Tracker:
    """A fake opener: records every URL; answers by the table `answers` (url suffix -> body | status int)."""

    def __init__(self):
        self.calls, self.answers = [], {}

    def __call__(self, request, timeout=0):
        self.calls.append(request.full_url)
        for suffix, body in self.answers.items():
            if request.full_url.endswith(suffix):
                if isinstance(body, int):
                    raise urllib.error.HTTPError(request.full_url, body, "Not Found", {}, io.BytesIO(b'{"errorMessages": ["no"]}'))
                return Response(body, request.full_url)
        raise AssertionError("unexpected request " + request.full_url)


def run(argv, cfg, tracker, cwd_root):
    """`ticket_adapter.main()` in-process: (exit code, stdout, stderr). `client_from_config` builds the real client over the fake
    opener, so the same-origin rule, the auth header and the retries are the production ones."""
    def make(adapter_cfg):
        client = REAL(adapter_cfg)
        client.opener = tracker
        return client

    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["ticket_adapter.py", *argv]), mock.patch.object(TA, "load_config", lambda: cfg), \
            mock.patch.object(TA, "client_from_config", make), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = TA.main()
    return code, out.getvalue(), err.getvalue()


def main() -> None:
    root = harness.temp_project("qa-ticket-query-")
    os.environ["QA_USER"], os.environ["QA_TOKEN"] = "reader@example.test", TOKEN
    try:
        harness.use_project(root)
        work = root / "qa-factory" / "artifacts" / "APP-1" / "work"
        work.mkdir(parents=True)
        inventory = work / "source-inventory.json"
        out = str(inventory)

        # Q1 relative path: one GET, saved whole, one summary line
        t = Tracker()
        t.answers["/rest/api/2/search?jql=filter%3D1"] = {"total": 37, "issues": [{}, {}]}
        code, so, se = run(["query", "--path", "/rest/api/2/search?jql=filter%3D1", "--output", out], CFG, t, root)
        saved = work / "queries" / "tracker-query-1.json"
        check_eq("Q1 exit 0", code, 0)
        check_eq("Q1 one GET to base_url + path", t.calls, [BASE + "/rest/api/2/search?jql=filter%3D1"])
        check("Q1 the file is saved whole", saved.is_file() and json.loads(saved.read_text(encoding="utf-8")) == {"total": 37, "issues": [{}, {}]})
        check_eq("Q1 stdout is ONE line", len(so.strip().splitlines()), 1)
        check_in("Q1 ... holding total=37 and issues[2]", "total=37", so)
        check_in("Q1 ... and the list count", "issues[2]", so)
        check_in("Q1 ... and the file", "tracker-query-1.json", so)
        check_not_in("Q1 the body is not printed", '"issues"', so)
        check("Q1 the inventory is not written by query (one writer)", not inventory.exists())
        # the next call takes the next n
        code, so, se = run(["query", "--path", "/rest/api/2/search?jql=filter%3D1", "--output", out], CFG, t, root)
        check("Q1 the next call saves as n=2", code == 0 and (work / "queries" / "tracker-query-2.json").is_file())

        # Q2 another host: usage, never sent
        t = Tracker()
        code, so, se = run(["query", "--path", "https://evil.example.test/rest/api/2/search", "--output", out], CFG, t, root)
        check_eq("Q2 another host -> usage (2)", code, 2)
        check_eq("Q2 the opener is never called", t.calls, [])
        check_in("Q2 the refusal names the tracker's base url", BASE, se)
        for bad in ("file:///etc/passwd", "ftp://jira.example.test/x", "//evil.example.test/x", "", "/a b"):
            code, _so, _se = run(["query", "--path", bad, "--output", out], CFG, t, root)
            check(f"Q2 adversarial path {bad!r} is refused, nothing sent", code == 2 and t.calls == [], f"{code} {t.calls}")

        # Q3 the tracker's own absolute URL; upper-cased scheme and host are the same origin
        t = Tracker()
        t.answers["/rest/api/2/field"] = [{"id": "a"}]
        code, so, se = run(["query", "--path", BASE + "/rest/api/2/field", "--output", out, "--save", str(work / "queries" / "f.json")],
                           CFG, t, root)
        check_eq("Q3 the same-host absolute URL is accepted", (code, t.calls), (0, [BASE + "/rest/api/2/field"]))
        check_in("Q3 ... a top-level list is counted", "[1]", so)
        t = Tracker()
        t.answers["/rest/api/2/field"] = [{"id": "a"}]
        code, _so, _se = run(["query", "--path", "HTTPS://JIRA.EXAMPLE.TEST/rest/api/2/field", "--output", out], CFG, t, root)
        check_eq("Q3 (adversarial) an upper-cased scheme and host is the same origin", (code, len(t.calls)), (0, 1))

        # Q4 no leading slash
        t = Tracker()
        code, so, se = run(["query", "--path", "issues", "--output", out], CFG, t, root)
        check_eq("Q4 a path with no `/` -> usage, nothing sent", (code, t.calls), (2, []))

        # Q5 no direct_api: exit 3 naming record-source
        t = Tracker()
        code, so, se = run(["query", "--path", "/rest/api/2/field", "--output", out], CFG_NONE, t, root)
        check_eq("Q5 no direct_api -> exit 3", code, 3)
        check_in("Q5 ... the door is named", "record-source", se)
        check_eq("Q5 ... no request", t.calls, [])
        code, so, se = run(["query", "--output", out], CFG, Tracker(), root)
        check_eq("Q5 (edge) no --path -> usage", code, 2)

        # Q6 the token value is in no output byte (every path above)
        t = Tracker()
        t.answers["/rest/api/2/field"] = {"total": 1}
        code, so, se = run(["query", "--path", "/rest/api/2/field", "--output", out], CFG, t, root)
        check("Q6 the token value is in no output byte", TOKEN not in so + se and "Basic " not in so + se, so + se)

        # Q7 AT and BEYOND the size ceiling
        def padded(size: int) -> bytes:
            head = b'{"total": 1, "pad": "'
            tail = b'"}'
            return head + b"x" * (size - len(head) - len(tail)) + tail

        at, beyond = padded(TA.QUERY_MAX_BYTES), padded(TA.QUERY_MAX_BYTES + 1)
        t = Tracker()
        t.answers["/at"] = at
        code, so, se = run(["query", "--path", "/at", "--output", out, "--save", str(work / "queries" / "at.json")], CFG, t, root)
        check_eq("Q7 an answer of exactly QUERY_MAX_BYTES is saved", (code, (work / "queries" / "at.json").stat().st_size),
                 (0, TA.QUERY_MAX_BYTES))
        t.answers["/beyond"] = beyond
        code, so, se = run(["query", "--path", "/beyond", "--output", out, "--save", str(work / "queries" / "beyond.json")], CFG, t, root)
        check("Q7 one byte more is refused", code == 2 and "narrow the request" in se, f"{code} {se}")
        check("Q7 ... and nothing is saved", not (work / "queries" / "beyond.json").exists())

        # Q8 404
        t = Tracker()
        t.answers["/rest/api/2/nothing"] = 404
        before = sorted(p.name for p in (work / "queries").iterdir())
        code, so, se = run(["query", "--path", "/rest/api/2/nothing", "--output", out], CFG, t, root)
        check_eq("Q8 404 -> exit 1", code, 1)
        check_in("Q8 ... the named sentence", "the tracker answered 404 for /rest/api/2/nothing: the path or the query is wrong, "
                 "or this account cannot see it", se)
        check_eq("Q8 ... nothing saved", sorted(p.name for p in (work / "queries").iterdir()), before)

        # Q9 --save outside work/
        t = Tracker()
        t.answers["/rest/api/2/field"] = {"total": 1}
        for bad in ("../x.json", str(root / "x.json"), "raw/../../x.json"):
            code, so, se = run(["query", "--path", "/rest/api/2/field", "--output", out, "--save", bad], CFG, t, root)
            check(f"Q9 --save {bad} -> usage, nothing sent", code == 2 and t.calls == [] and not (root / "x.json").exists(), f"{code} {t.calls}")
        # Q9b (t-1692 F1): a save is written ONLY under work/queries/ - any other file of work/ (the inventory above all) is refused naming that door
        inventory.write_text('{"sources": []}\n', encoding="utf-8")
        frozen = inventory.read_bytes()
        (work / "requirements-register.md").write_text("register\n", encoding="utf-8")
        for bad in (out, str(work / "requirements-register.md"), str(work / "raw" / "x.json"), str(work / "queries" / ".." / "source-inventory.json"),
                    str(work / "queries")):
            code, so, se = run(["query", "--path", "/rest/api/2/field", "--output", out, "--save", bad], CFG, t, root)
            check(f"Q9b --save {Path(bad).name} outside work/queries/ -> usage naming the door, nothing sent",
                  code == 2 and t.calls == [] and "queries" in se, f"{code} {t.calls} {se}")
        check_eq("Q9b the inventory is byte-identical after the refused saves", inventory.read_bytes(), frozen)
        check_eq("Q9b the register is untouched", (work / "requirements-register.md").read_text(encoding="utf-8"), "register\n")
        code, so, se = run(["query", "--path", "/rest/api/2/field", "--output", out, "--save", str(work / "queries" / "sub" / "ok.json")], CFG, t, root)
        check("Q9b a file under work/queries/ is accepted (the door)", code == 0 and (work / "queries" / "sub" / "ok.json").is_file(), f"{code} {se}")
        inventory.unlink()

        # Q10 a link where a key belongs
        inventory.write_text('{"sources": []}\n', encoding="utf-8")
        frozen = inventory.read_bytes()
        link = BASE + "/projects/APP/issues/APP-1?filter=allopenissues"
        t = Tracker()
        code, so, se = run(["peek", link, "--output", out], CFG, t, root)
        check_eq("Q10 peek <link> -> usage", code, 2)
        check_in("Q10 ... names the key in it and the verb", "peek APP-1", se)
        check_in("Q10 ... and `query`", "query --path", se)
        check_eq("Q10 ... the opener is never called", t.calls, [])
        check_eq("Q10 ... the inventory is byte-identical", inventory.read_bytes(), frozen)
        code, so, se = run(["collect", link, "--output", out, "--relation", "referenced"], CFG, t, root)
        check_eq("Q10 collect <link> is refused the same way", (code, t.calls, inventory.read_bytes() == frozen), (2, [], True))

        # Q11 positive control: a real key still goes the old way
        t = Tracker()
        t.answers["/issue/APP-1"] = 404
        code, so, se = run(["peek", "APP-1", "--output", out], CFG, t, root)
        check("Q11 peek APP-1 reaches the tracker (not refused as a link)", len(t.calls) >= 1 and "is a link" not in se, f"{t.calls} {se}")

        # Q12 adversarial links
        t = Tracker()
        code, so, se = run(["peek", link.replace("https", "HTTPS").upper(), "--output", out], CFG, t, root)
        check("Q12 an upper-cased link is a link; the key is named", code == 2 and "APP-1" in se and t.calls == [], f"{code} {se}")
        code, so, se = run(["peek", BASE + "/issues/?filter=allopenissues", "--output", out], CFG, t, root)
        check("Q12 a link with no key: the refusal says so and still names `query`",
              code == 2 and "No ticket key was found" in se and "query --path" in se and t.calls == [], f"{code} {se}")
        code, so, se = run(["peek", BASE + "/browse/APP-1?linked=APP-22", "--output", out], CFG, t, root)
        check("Q12 a link with two keys names both", code == 2 and "APP-1" in se and "APP-22" in se and t.calls == [], f"{code} {se}")

        # Q13 the leftover of N1: `get`, `children` and `freshness` refuse a link given as a key exactly as peek/collect do
        t = Tracker()
        for argv in (["get", link], ["get", link, "--output", str(work / "snap.json")], ["children", link],
                     ["freshness", link, "--task-root", str(root)]):
            code, so, se = run(argv, CFG, t, root)
            check(f"Q13 {argv[0]} <link> -> usage, the key and `query` named, nothing sent",
                  code == 2 and "is a link, not a ticket key" in se and "peek APP-1" in se and "query --path" in se and t.calls == [], f"{code} {se} {t.calls}")
        check("Q13 ... and nothing was written", not (work / "snap.json").exists() and inventory.read_bytes() == frozen)
        t = Tracker()
        code, so, se = run(["get", "APP-1"], CFG, t, root)
        check("Q13 positive control: `get APP-1` still reaches the tracker, not refused as a link", len(t.calls) >= 1 and "is a link" not in se, f"{code} {se} {t.calls}")
    finally:
        harness.cleanup(root)
    harness.finish("test_ticket_query")


if __name__ == "__main__":
    main()
