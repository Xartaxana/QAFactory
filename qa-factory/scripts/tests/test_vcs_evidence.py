#!/usr/bin/env python3
"""vcs_evidence.py and the person's list of sources not to read (t-172 / B-231, P8a).

A merge request the person left out BEFORE the run is refused with exit 2 and no call to the API - with
`--output` under the story's own folder (only that story's word is consulted), probe-only (no story is
known: the probe reads MR metadata too, so every story's word is consulted) and `--output` outside a story.
`collect` is replaced by a stub that records its calls, so nothing here reaches the network: a stub call is
a fetch that should not have happened (or, where the test says so, one that must).
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import vcs_evidence  # noqa: E402
import source_exclusions as SE  # noqa: E402

URL_1924 = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"
URL_1881 = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1881"
LIST = "testproject1-ui!1924 - Draft MR of an earlier factory run, not a product change\nTP1-13289 - a ticket\n"

calls: list = []


def fake_collect(url, read=None, full=True):
    calls.append((url, full))
    return {"url": url, "status": "read", "complete": full, "revision": "abc123"}


vcs_evidence.collect = fake_collect


def story(root: Path, task: str, list_text: str = "") -> Path:
    task_root = root / "qa-factory" / "artifacts" / task
    (task_root / "work").mkdir(parents=True)
    if list_text:
        entries, problems = SE.parse_bytes(list_text.encode("utf-8"), task)
        assert not problems, problems
        SE.write_record(task_root, entries, "list.txt", list_text.encode("utf-8"))
    return task_root


def run(root: Path, *argv: str) -> tuple:
    """(exit code, stdout, stderr) of one in-process `vcs_evidence.main` from the project root."""
    calls.clear()
    saved, saved_argv = os.getcwd(), sys.argv
    out, err = io.StringIO(), io.StringIO()
    os.chdir(root)
    sys.argv = ["vcs_evidence.py", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vcs_evidence.main()
    finally:
        os.chdir(saved)
        sys.argv = saved_argv
    return code, out.getvalue(), err.getvalue()


def out_arg(task: str, name: str = "mr-1924.json") -> str:
    return f"qa-factory/artifacts/{task}/work/sources/SRC-1/{name}"


root = temp_project("qa-vcs-evidence-")
harness.use_project(root)
try:
    a = story(root, "TP1-15045", LIST)
    b = story(root, "TP1-14482")            # another story: no list of its own

    # --- vcs_evidence_refuses_excluded_no_network: the story's own word, `--output` under it ----------------
    code, out, err = run(root, "--url", URL_1924, "--output", out_arg("TP1-15045"))
    check_eq("vcs_evidence_refuses_excluded_no_network: exit 2", code, 2)
    check_eq("and the API was never asked", calls, [])
    check("and no receipt was written", not (a / "work" / "sources" / "SRC-1" / "mr-1924.json").exists())
    check_in("the refusal says what was asked and why", "the person asked before the run not to read", err)
    check_in("it quotes the person's reason", "Draft MR of an earlier factory run", err)
    check_in("and names the door a role has: its handoff", "say so in your handoff", err)
    check_not_in("and never a command the role cannot run", "--revoke", err)
    shape = json.loads(out)
    check_eq("stdout stays one JSON object (FR-14) that says nothing was fetched",
             (shape["status"], shape["fetched"], shape["exclusion"]), ("excluded", False, "X1"))

    # the real command line, as a role runs it (no API: the refusal comes first)
    done = harness.run_script("vcs_evidence.py", "--url", URL_1924, "--output", out_arg("TP1-15045"), cwd=root,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
    check_eq("as a script: exit 2, JSON on stdout, the words on stderr",
             (done.returncode, json.loads(done.stdout)["status"], "not to read" in done.stderr), (2, "excluded", True))

    # the same word under a different spelling of the same request
    for label, url in (("a suffix after the number", URL_1924 + "/diffs"),
                       ("a fragment", URL_1924 + "#note_1"),
                       ("host in capitals", URL_1924.replace("git.example", "GITHOST.EXAMPLE.COM")),
                       ("an escaped underscore", URL_1924.replace("merge_requests", "merge\\_requests"))):
        code, _out, _err = run(root, "--url", url, "--output", out_arg("TP1-15045"))
        check(f"the same request with {label} is refused, and nothing is fetched", code == 2 and calls == [], str((code, calls)))

    # another request of the same story is read as always
    code, out, err = run(root, "--url", URL_1881, "--output", out_arg("TP1-15045", "mr-1881.json"))
    check_eq("another request of the story: the tool runs", (code, len(calls), calls[0][1]), (0, 1, True))
    check("and its receipt is written", (a / "work" / "sources" / "SRC-1" / "mr-1881.json").is_file())

    # the word is held only by the story that said it (`--output` names the story)
    code, _out, _err = run(root, "--url", URL_1924, "--output", out_arg("TP1-14482"))
    check_eq("a story with no list of its own reads the request", (code, len(calls)), (0, 1))

    # --- probe-only: no story is known, every story's word is consulted (C4) -----------------------------------
    code, out, err = run(root, "--url", URL_1924)
    check("probe-only: the excluded request is refused with no call", code == 2 and calls == [], str((code, calls)))
    check_in("probe-only: the refusal names the story whose word it is", "TP1-15045", err)
    check_in("probe-only: and the door that is open (write it under that story's own folder)", "--output", err)
    code, out, err = run(root, "--url", URL_1881)
    check_eq("probe-only: a request nobody left out is probed as always", (code, calls), (0, [(URL_1881, False)]))

    # --output outside any story is the same question
    elsewhere = root / "scratch" / "mr.json"
    code, _out, _err = run(root, "--url", URL_1924, "--output", str(elsewhere))
    check("--output outside a story: refused with no call, no file", code == 2 and calls == [] and not elsewhere.exists(),
          str((code, calls)))

    # the ticket word of the list is no merge request: it never matches a URL
    check("a ticket word never names a merge request link",
          not any(SE.matches(e, url=URL_1881) for e in SE.live(a) if e["target"]["kind"] == "ticket"))

    # --- a record that cannot be read --------------------------------------------------------------------------
    SE.record_path(a / "work").write_text("{not json", encoding="utf-8")
    code, _out, err = run(root, "--url", URL_1881, "--output", out_arg("TP1-15045", "mr-x.json"))
    check("an unreadable record of the asking story refuses, naming the file (never a silent read)",
          code == 2 and calls == [] and "source-exclusions.json" in err, str((code, calls, err[-300:])))
    code, _out, err = run(root, "--url", URL_1881)
    check_eq("an unreadable record of ANOTHER story is not this probe's business", (code, len(calls)), (0, 1))
finally:
    cleanup(root)

# --- no record anywhere: today's behaviour ------------------------------------------------------------------------
root = temp_project("qa-vcs-evidence-plain-")
harness.use_project(root)
try:
    plain = story(root, "TP1-15045")
    code, out, err = run(root, "--url", URL_1924, "--output", out_arg("TP1-15045"))
    check_eq("no record anywhere: the tool runs and writes its receipt as it always did",
             (code, len(calls), (plain / "work" / "sources" / "SRC-1" / "mr-1924.json").is_file()), (0, 1, True))
    check_eq("no record anywhere: stderr is silent", err, "")
    code, out, err = run(root, "--url", URL_1924)
    check_eq("no record anywhere: probe-only is probed as it always was", (code, calls), (0, [(URL_1924, False)]))
finally:
    cleanup(root)

# --- the API receipt (HF8-12, W-4): what `main` keeps of one read, and what `read_api_receipts` hands back --------------
import event_store  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

REAL_WHICH = shutil.which


@contextlib.contextmanager
def glab(present: bool):
    shutil.which = lambda name, *a, **k: ("glab" if present else None) if name == "glab" else REAL_WHICH(name, *a, **k)
    try:
        yield
    finally:
        shutil.which = REAL_WHICH


def api_result(url, **change):
    base = {"url": url, "host": "git.example", "project": "tp1-group/testproject1-ui", "iid": "1881", "status": "read",
            "required": True, "api_authenticated": True, "complete": True, "error": None}
    base.update(change)
    return base


def scripted(**change):
    vcs_evidence.collect = lambda url, read=None, full=True: api_result(url, **change)


def receipt_files(root: Path) -> list:
    folder = root / "qa-factory" / "state" / "host-receipts"
    return sorted(p.name for p in folder.glob("vcs-api-*.json")) if folder.is_dir() else []


def the_receipt(root: Path) -> dict:
    names = receipt_files(root)
    return json.loads((root / "qa-factory" / "state" / "host-receipts" / names[0]).read_text(encoding="utf-8")) if names else {}


root = temp_project("qa-vcs-receipt-")
harness.use_project(root)
try:
    st = story(root, "TP1-15045", LIST)
    out_1881 = out_arg("TP1-15045", "mr-1881.json")

    # the one read that proves the API: authenticated and read
    scripted()
    code, out, _err = run(root, "--url", URL_1881, "--output", out_1881)
    rec = the_receipt(root)
    check_eq("a read MR writes an ok receipt for its host (the project root found from --output)",
             (code, rec.get("status"), rec.get("host"), rec.get("code")),
             (0, "ok", "git.example", "read"))
    check_eq("the receipt holds exactly its named fields, each with a reader (AR-22), no result, no token, no MR content",
             sorted(rec), ["adapter", "code", "host", "observed_at", "status"])
    scripted(token="glpat-SECRET", metadata={"title": "SECRET-TITLE"}, notes=["SECRET-NOTE"])
    run(root, "--url", URL_1881, "--output", out_1881)
    text = (root / "qa-factory/state/host-receipts" / receipt_files(root)[0]).read_text(encoding="utf-8")
    check("no secret in the receipt", "SECRET" not in text and "glpat" not in text, text[:200])
    first = the_receipt(root)

    # not a proof: each one leaves the older receipt exactly as it was
    for label, change in (("failed read: no ok receipt (an authenticated user, a 404 on the MR)",
                           dict(status="unavailable", error="not_found_or_hidden")),
                          ("network error after read: ok stays", dict(status="unavailable", api_authenticated=False,
                                                                       error="network_timeout")),
                          ("a truncated diff", dict(status="unavailable", error="diff_truncated")),
                          ("rate limited", dict(status="unavailable", error="rate_limited")),
                          ("glab missing is the tool's refusal, not the host's", dict(status="unavailable",
                                                                                      api_authenticated=False,
                                                                                      error="cli_missing"))):
        scripted(**change)
        run(root, "--url", URL_1881, "--output", out_1881)
        check_eq(label, the_receipt(root), first)

    # read without api_authenticated (the shape of the older stub): no receipt of its own
    other_root = temp_project("qa-vcs-receipt-bare-")
    try:
        harness.use_project(other_root)
        vcs_evidence.collect = fake_collect
        run(other_root, "--url", URL_1881)
        check_eq("read without api_authenticated: no receipt", receipt_files(other_root), [])

        # no config.json: nothing is created, the answer is the same
        (other_root / "qa-factory" / "config.json").unlink()
        shutil.rmtree(other_root / "qa-factory" / "state")
        scripted()
        code, out, _err = run(other_root, "--url", URL_1881)
        check_eq("no config.json: nothing created, the tool answers as always",
                 (code, json.loads(out)["status"], (other_root / "qa-factory" / "state").exists()), (0, "read", False))
    finally:
        harness.use_project(root)
        cleanup(other_root)

    # a refusal after a read replaces the ok of that host
    scripted(status="unavailable", api_authenticated=False, error="unauthenticated")
    code, _out, _err = run(root, "--url", URL_1881, "--output", out_1881)
    check_eq("unauthenticated after read: denied replaces ok",
             (code, the_receipt(root).get("status"), the_receipt(root).get("code"), len(receipt_files(root))),
             (2, "denied", "unauthenticated", 1))
    scripted()
    run(root, "--url", URL_1881, "--output", out_1881)
    check_eq("the next successful read takes the denial back (the way out of `denied`)", the_receipt(root).get("status"), "ok")
    scripted(status="unavailable", api_authenticated=True, error="forbidden")
    run(root, "--url", URL_1881)
    check_eq("forbidden, probe-only (the project root from the process): denied", the_receipt(root).get("status"), "denied")

    # an excluded MR is refused before the read: no receipt, even when a read would have been ok
    for old in (root / "qa-factory/state/host-receipts").glob("vcs-api-*.json"):
        old.unlink()
    scripted()
    code, _out, _err = run(root, "--url", URL_1924, "--output", out_arg("TP1-15045"))
    check_eq("excluded MR: no receipt", (code, receipt_files(root)), (2, []))

    # the writer failing changes nothing of what the tool answers (FR-14)
    scripted()
    baseline = run(root, "--url", URL_1881)
    saved_atomic, saved_record = event_store.atomic_json, vcs_evidence.record_api_receipt
    try:
        event_store.atomic_json = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        broken_write = run(root, "--url", URL_1881)
        event_store.atomic_json = saved_atomic
        vcs_evidence.record_api_receipt = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        broken_call = run(root, "--url", URL_1881)
    finally:
        event_store.atomic_json, vcs_evidence.record_api_receipt = saved_atomic, saved_record
    strip = lambda triple: (triple[0], json.loads(triple[1]).keys(), triple[2])  # fetched_at differs by clock
    check_eq("receipt write raises: same exit and stdout shape (the write)", strip(broken_write), strip(baseline))
    check_eq("receipt write raises: same exit and stdout shape (the call)", strip(broken_call), strip(baseline))

    # the host is one host whatever its spelling: port and case
    for old in (root / "qa-factory/state/host-receipts").glob("vcs-api-*.json"):
        old.unlink()
    scripted(host="GitLab.Example.com:8443")
    run(root, "--url", URL_1881)
    check_eq("a host with a port and capitals is the lower-case hostname",
             (the_receipt(root).get("host"), receipt_files(root) == [vcs_evidence._receipt_path(root, "gitlab.example.com").name]),
             ("gitlab.example.com", True))
    check_eq("_host_key: one spelling for netloc and hostname",
             {vcs_evidence._host_key(h) for h in ("GitLab.Example.com:8443", "gitlab.example.com", "GITLAB.example.com")},
             {"gitlab.example.com"})

    # --- read_api_receipts: freshness, route, shape --------------------------------------------------------------
    seen = datetime.fromisoformat(the_receipt(root)["observed_at"])
    ttl = timedelta(seconds=vcs_evidence.RECEIPT_TTL_S)
    with glab(True):
        def fresh(now) -> int:
            got = vcs_evidence.read_api_receipts(root, now=now)
            return len(got["ok"]) + len(got["denied"])
        check_eq("age at TTL is stale, TTL-1 s fresh, a future date stale",
                 (fresh(seen + ttl - timedelta(seconds=1)), fresh(seen + ttl), fresh(seen - timedelta(seconds=1)), fresh(seen)),
                 (1, 0, 0, 1))
        got = vcs_evidence.read_api_receipts(root)
        check_eq("an ok receipt is listed under ok", (len(got["ok"]), len(got["denied"])), (1, 0))

        # another adapter in the config: the receipt was earned on another route
        config_path = root / "qa-factory" / "config.json"
        original = config_path.read_bytes()
        config = json.loads(original)
        config.setdefault("adapters", {}).setdefault("vcs", {})["method"] = "mcp_tool"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        check_eq("another adapter in the config: a receipt is not fresh", fresh(seen), 0)
        config_path.write_bytes(original)
        check_eq("the same adapter again: fresh", fresh(seen), 1)
        config_path.write_text("{not json", encoding="utf-8")
        check_eq("an unreadable config: no receipt is fresh, nothing raises", fresh(seen), 0)
        config_path.write_bytes(original)
    with glab(False):
        check_eq("glab gone: a receipt is not fresh", len(vcs_evidence.read_api_receipts(root, now=seen)["ok"]), 0)

    # a file that cannot be read, a foreign shape, a folder that is not there
    folder = root / "qa-factory" / "state" / "host-receipts"
    for name, body in (("vcs-api-aaaaaaaaaaaaaaaa.json", "{not json"), ("vcs-api-bbbbbbbbbbbbbbbb.json", "[1, 2]"),
                       ("vcs-api-cccccccccccccccc.json", json.dumps({"status": "ok", "host": 5, "observed_at": "x"})),
                       ("vcs-api-dddddddddddddddd.json", json.dumps({"status": "maybe", "host": "h", "observed_at": seen.isoformat()})),
                       ("vcs-api-eeeeeeeeeeeeeeee.json", json.dumps({"status": "ok", "host": "h", "observed_at": "2026-01-01T00:00:00"}))):
        (folder / name).write_text(body, encoding="utf-8")
    with glab(True):
        got = vcs_evidence.read_api_receipts(root, now=seen)
        check_eq("unreadable, foreign, untimed and unzoned files are skipped, the good one stays",
                 [row["host"] for row in got["ok"] + got["denied"]], ["gitlab.example.com"])
    shutil.rmtree(folder)
    with glab(True):
        check_eq("no folder: nothing, no raise", vcs_evidence.read_api_receipts(root), {"ok": [], "denied": []})

    # --- the live probe writes a refusal it established (B2) ----------------------------------------------------
    config = json.loads(original)
    config.setdefault("adapters", {}).setdefault("vcs", {})["name"] = "gitlab"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    real_run, real_api = vcs_evidence.subprocess.run, vcs_evidence.api
    import reachability  # noqa: E402
    reachability.probe = lambda host, port=443: {"host": host, "status": "reachable"}    # no socket in a test

    AUTH = {"text": "", "raise": None, "calls": []}     # what `glab auth status` answers in this section (OH3-11)

    def probe(code, remote="https://GitLab.Example.com:8443/g/p.git"):
        def fake_run(argv, *a, **k):
            if argv[:3] == ["git", "remote", "get-url"]:
                return type("R", (), {"stdout": remote + "\n", "returncode": 0})()
            if argv[:3] == ["glab", "auth", "status"]:      # never the real `glab`, and never the real network
                AUTH["calls"].append((argv, k))
                if AUTH["raise"]:
                    raise AUTH["raise"]
                return type("R", (), {"stdout": "", "stderr": AUTH["text"], "returncode": 1})()
            return real_run(argv, *a, **k)
        def fake_api(host, endpoint):
            if code:
                raise vcs_evidence.AccessError(code)
            return {"id": 1}
        vcs_evidence.subprocess.run, vcs_evidence.api = fake_run, fake_api
        try:
            return vcs_evidence.readiness(config, root)
        finally:
            vcs_evidence.subprocess.run, vcs_evidence.api = real_run, real_api

    answer = probe("unauthenticated")
    rec = the_receipt(root)
    check_eq("live denial writes denied (the host the probe asked, lower-cased, no port)",
             (answer["status"], answer.get("host"), rec.get("status"), rec.get("code"), rec.get("host")),
             ("missing", "gitlab.example.com", "denied", "unauthenticated", "gitlab.example.com"))
    shutil.rmtree(folder)
    for code_name in ("cli_missing", "rate_limited", "not_found_or_hidden", "network_timeout"):
        probe(code_name)
        check_eq(f"live {code_name}: no receipt", receipt_files(root), [])
    answer = probe(None)
    check_eq("a live ok writes nothing (only a read of a merge request proves the API) and names its host",
             (answer["status"], answer.get("host"), receipt_files(root)), ("ok", "gitlab.example.com", []))
    answer = probe("network_timeout")
    check_eq("asked and no answer: unknown, with the host the probe addressed",
             (answer["status"], answer.get("host")), ("unknown", "gitlab.example.com"))
    answer = probe("unauthenticated", remote="")
    check_eq("host_unresolved carries no host and writes no receipt",
             (answer["status"], "host" in answer, receipt_files(root)), ("unknown", False, []))

    # --- whose token is it (OH3-11) -----------------------------------------------------------------------------
    # Fixtures: the output of `glab auth status` measured on glab 1.126.0 and 1.40.0 (Linux, NO_COLOR=1, dummy tokens,
    # t-260 critic report, section 1); everything is on stderr, a token is masked.
    OK = "✓"
    F126_NONE = ("gitlab.com\n  x gitlab.com: API call failed: GET https://gitlab.com/api/vX/user: 401 {message: 401 Unauthorized}\n"
                 "  ! No token found (checked config file, keyring, and environment variables).\n   ERROR\n"
                 "  x could not authenticate to one or more of the configured GitLab instances.\n")
    F126_CONFIG = ("gitlab.com\n  x gitlab.com: API call failed: GET https://gitlab.com/api/vX/user: 401 {message: 401 Unauthorized}\n"
                   f"  {OK} Token found in configuration file (plaintext): ****\n")
    F126_ENV = (f"gitlab.com\n  {OK} Git operations for gitlab.com configured to use ssh protocol.\n"
                f"  {OK} Token found in environment variable GITLAB_TOKEN: ****\n"
                "! Token is from environment variable GITLAB_TOKEN. This takes precedence over tokens stored in config or keyring.\n")
    F140_NONE = ("gitlab.com\n  x gitlab.com: api call failed: GET https://gitlab.com/api/vX/user: 401 {message: 401 Unauthorized}\n"
                 "  x No token provided\n")
    F140_TOKEN = f"gitlab.com\n  {OK} Token: ****\n  ! Invalid token provided\n"
    VARS = ("GITLAB_TOKEN", "GITLAB_ACCESS_TOKEN", "OAUTH_TOKEN")

    @contextlib.contextmanager
    def auth(text="", env=None, raises=None):
        """`glab auth status` answers `text` (or raises), the three token variables are `env` (and only those)."""
        saved = {n: os.environ.pop(n, None) for n in VARS}
        os.environ.update(env or {})
        AUTH.update(text=text, calls=[])
        AUTH["raise"] = raises
        try:
            yield
        finally:
            for n in VARS:
                os.environ.pop(n, None)
            os.environ.update({n: v for n, v in saved.items() if v is not None})

    def case_of(code, host, text="", env=None, raises=None):
        def fake_run(argv, *a, **k):
            AUTH["calls"].append((argv, k))
            if AUTH["raise"]:
                raise AUTH["raise"]
            return type("R", (), {"stdout": "", "stderr": AUTH["text"], "returncode": 1})()
        with auth(text, env, raises):
            vcs_evidence.subprocess.run = fake_run
            try:
                return vcs_evidence._token_case(host, code)
            finally:
                vcs_evidence.subprocess.run = real_run

    def steps_of(code, host, got):
        return " | ".join(vcs_evidence.failed_readiness(code, host, got)["remedy"]["steps"])

    TOKEN = {"GITLAB_TOKEN": "glpat-SECRETMARK"}
    got = case_of("unauthenticated", "gitlab.gnome.org", F126_CONFIG, TOKEN)
    text = steps_of("unauthenticated", "gitlab.gnome.org", got)
    check_eq("401, variable set: env_overrides, names the variable and the other host",
             (got["case"], got["env"], got["others"], "`GITLAB_TOKEN`" in text, "`gitlab.gnome.org`" in text, "`gitlab.com`" in text,
              "prefers it" in text, "401" in text),
             ("env_overrides", "GITLAB_TOKEN", ["gitlab.com"], True, True, True, True, True))
    check("env_overrides has one door: out of the environment, then glab auth login; no 'put it in that variable'",
          "take the variable out of the environment" in text and "glab auth login --hostname gitlab.gnome.org" in text
          and "put it in" not in text and "refused this one" not in text, text)
    got = case_of("forbidden", "gitlab.gnome.org", F126_ENV, TOKEN)
    check_eq("403, variable set: env_overrides", (got["case"], got["env"]), ("env_overrides", "GITLAB_TOKEN"))
    check_in("403 is named as 403", "answered 403", steps_of("forbidden", "gitlab.gnome.org", got))
    got = case_of("forbidden", "gitlab.gnome.org", F126_CONFIG)
    check_eq("403, no variable: lacks_rights, `glab auth status` not called", (got["case"], AUTH["calls"]), ("lacks_rights", []))
    check_in("lacks_rights names the right and the access", "lacks `read_api`", steps_of("forbidden", "x.example", got))
    got = case_of("unauthenticated", "gitlab.com", F140_TOKEN)
    check_eq("401, host block with a token: host_token_rejected", (got["case"], got["others"]), ("host_token_rejected", []))
    got = case_of("unauthenticated", "gitlab.gnome.org", F126_CONFIG)
    text = steps_of("unauthenticated", "gitlab.gnome.org", got)
    check_eq("401, other hosts only: other_host_token, both hosts named",
             (got["case"], got["others"], "`gitlab.com`" in text, "`gitlab.gnome.org`" in text),
             ("other_host_token", ["gitlab.com"], True, True))
    for label, fixture in (("1.126.0", F126_NONE), ("1.40.0", F140_NONE)):
        got = case_of("unauthenticated", "githost.example", fixture)
        check_eq(f"401, default host with no token ({label}): no_token, not other_host_token", got["case"], "no_token")
    old_steps = vcs_evidence.failed_readiness("unauthenticated", "githost.example")
    for label, text in (("empty output", ""), ("no block at all", "some words\nnothing like a host here\n"),
                        ("a block with neither form", "gitlab.com\n  x gitlab.com: API call failed: GET https://gitlab.com/api/vX/user: 401\n"),
                        ("a localized output", "gitlab.com\n  x Kein Token gefunden\n"),
                        ("both forms in one block", "gitlab.com\n  x No token found\n  Token: ****\n")):
        got = case_of("unauthenticated", "githost.example", text)
        answer = vcs_evidence.failed_readiness("unauthenticated", "githost.example", got)
        check_eq(f"401, {label}: unknown, steps as before, no token_case key", (got["case"], answer == old_steps, "token_case" in answer),
                 ("unknown", True, False))
    got = case_of("unauthenticated", "githost.example", F126_NONE + "githost.example\n  x No token found\n")
    check_eq("a host block present but with no token and the others none: no_token", got["case"], "no_token")
    got = case_of("unauthenticated", "githost.example", "a.example\n  Token found in x\nb.example\n  x b.example: API call failed\n")
    check_eq("another host present, a third block not understood: unknown, never 'only' (F2)", got["case"], "unknown")
    got = case_of("unauthenticated", "githost.example", F126_CONFIG + "githost.example\n  x githost.example: API call failed\n")
    check_eq("the host's own block with neither form: unknown, not a guess from the others", got["case"], "unknown")

    got = case_of("unauthenticated", "githost.example", F126_NONE)
    got_timeout = AUTH["calls"][0][1].get("timeout")
    check_eq("the timeout is passed to subprocess, NO_COLOR is set, no --all",
             (got_timeout, vcs_evidence.AUTH_STATUS_TIMEOUT_S, AUTH["calls"][0][0], AUTH["calls"][0][1]["env"].get("NO_COLOR")),
             (15, 15, ["glab", "auth", "status"], "1"))
    got = case_of("unauthenticated", "githost.example", raises=vcs_evidence.subprocess.TimeoutExpired("glab", 15))
    check_eq("TimeoutExpired: unknown", got["case"], "unknown")
    got = case_of("unauthenticated", "githost.example", raises=OSError("no glab"))
    check_eq("OSError: unknown", got["case"], "unknown")
    got = case_of("unauthenticated", "githost.example", raises=TimeoutError("odd"))
    check_eq("an odd error from the process: unknown, no exception", got["case"], "unknown")
    # OH11-4 (t-428): an error `_auth_status_blocks` does not catch (it handles OSError / SubprocessError / ValueError) reaches
    # the handler of `_token_case`; TimeoutError above is an OSError and never gets there
    got = case_of("unauthenticated", "githost.example", raises=RuntimeError("not an OS error"))
    check_eq("an error outside the process family: unknown, never an exception out of _token_case", got["case"], "unknown")

    real_path = vcs_evidence.GLAB_AUTH_PATH
    try:
        for label, body in (("no data file", None), ("an unreadable file", "{not json"), ("a foreign shape", '{"token_env": 5}'),
                            ("a list", "[1]"), ("a bad pattern", json.dumps({**json.loads(real_path.read_text(encoding="utf-8")), "host_line": "(("}))):
            fake = root / "glab-auth-test.json"
            if body is not None:
                fake.write_text(body, encoding="utf-8")
            vcs_evidence.GLAB_AUTH_PATH = fake if body is not None else root / "no-such-file.json"
            got = case_of("unauthenticated", "githost.example", F126_CONFIG, TOKEN)
            answer = vcs_evidence.failed_readiness("unauthenticated", "githost.example", got)
            check_eq(f"{label}: unknown, steps as before, no exception, no process", (got["case"], answer == old_steps, AUTH["calls"]),
                     ("unknown", True, []))
    finally:
        vcs_evidence.GLAB_AUTH_PATH = real_path

    # a host is compared whole: a look-alike is another host (E13), a port and capitals are the same host
    got = case_of("unauthenticated", "githost.example",
                  "githost.example.evil\n  Token found in configuration file\nxgithost.example\n  Token found in configuration file\n")
    check_eq("githost.example.evil and xgithost.example do not count as githost.example",
             (got["case"], got["others"]), ("other_host_token", ["githost.example.evil", "xgithost.example"]))
    got = case_of("unauthenticated", "gitlab.example", "GitLab.Example:8443\n  Token found in configuration file\n")
    check_eq("GitLab.Example:8443 counts as gitlab.example", got["case"], "host_token_rejected")

    # a token never reaches the answer (E11): not from the output, not from the variable
    leaky = "gitlab.com\n  Token found in environment variable GITLAB_TOKEN: glpat-SECRETMARK\nglpat/SECRETMARK\n"
    for label, env in (("variable set", TOKEN), ("variable not set", None)):
        got = case_of("unauthenticated", "gitlab.gnome.org", leaky, env)
        check(f"a token in the output and in the variable never reaches the answer ({label})",
              "SECRETMARK" not in json.dumps(vcs_evidence.failed_readiness("unauthenticated", "gitlab.gnome.org", got))
              and "SECRETMARK" not in json.dumps(got), json.dumps(got))
    got = case_of("forbidden", "gitlab.gnome.org", F126_ENV, {"GITLAB_TOKEN": "   "})
    check_eq("a whitespace variable is not set", got["case"], "lacks_rights")
    got = case_of("forbidden", "gitlab.gnome.org", F126_ENV, {"OAUTH_TOKEN": "x"})
    check_eq("each of the three names counts", (got["case"], got["env"]), ("env_overrides", "OAUTH_TOKEN"))

    # the list of other hosts is cut at OTHER_HOSTS_SHOWN (E12)
    hosts = [f"h{i}.example" for i in range(1, 5)]
    for count, expect in ((3, ("`h1.example`, `h2.example`, `h3.example`", False)), (4, ("`h1.example`, `h2.example`, `h3.example` and 1 more", True))):
        got = case_of("unauthenticated", "mine.example", "".join(f"{h}\n  Token found in configuration file\n" for h in hosts[:count]))
        text = steps_of("unauthenticated", "mine.example", got)
        check_eq(f"{count} other hosts: " + ("all named" if count == 3 else "three named and 1 more"),
                 (expect[0] in text, "h4.example" in text), (True, False))
        check_eq(f"{count} other hosts: the suffix 'and 1 more' is " + ("absent" if count == 3 else "present"), "and 1 more" in text, expect[1])

    # the extra process runs only for a refusal the host gave (AR-12, E15)
    with auth(F126_CONFIG):
        probe(None)
        check_eq("a live ok does not start `glab auth status`", AUTH["calls"], [])
        for name in ("network_timeout", "not_found_or_hidden", "cli_missing", "rate_limited", "network_transient"):
            probe(name)
        check_eq("network_timeout, 404, cli_missing, rate_limited: `glab auth status` not called", AUTH["calls"], [])
        probe("unauthenticated")
        check_eq("a confirmed refusal starts it exactly once", len(AUTH["calls"]), 1)
    with auth(F126_CONFIG, TOKEN):
        shutil.rmtree(folder, ignore_errors=True)
        answer = probe("unauthenticated")
        rec = the_receipt(root)
        check_eq("the denied receipt keeps the code and carries no case", (sorted(rec), rec.get("code"), "case" in json.dumps(rec)),
                 (["adapter", "code", "host", "observed_at", "status"], "unauthenticated", False))
        check_eq("the answer carries the case in token_case, the host and the owner as before",
                 (answer.get("token_case"), answer["owner"], answer["status"], answer.get("host")),
                 ("env_overrides", "user", "missing", "gitlab.example.com"))
        check("a secret in the variable is not in the answer or the receipt",
              "SECRETMARK" not in json.dumps(answer) and "SECRETMARK" not in json.dumps(rec), json.dumps(answer)[:200])
        answer = probe("forbidden")
        check_eq("403 with the variable: env_overrides through the whole probe", answer.get("token_case"), "env_overrides")
    with auth(""):
        answer = probe("unauthenticated")
        check_eq("an unknown case has no token_case key and the old steps",
                 ("token_case" in answer, answer["remedy"]["steps"] == vcs_evidence.failed_readiness("unauthenticated", "gitlab.example.com")["remedy"]["steps"]),
                 (False, True))
    with auth(F126_NONE):
        answer = probe("unauthenticated", remote="https://gitlab.com/g/p.git")
        check_eq("no token on the default host: no_token through the whole probe", answer.get("token_case"), "no_token")

    # every case keeps the connector first and names read_api; blocks, need, verify stay (steps are the only change)
    for name, case in (("env_overrides", {"case": "env_overrides", "env": "GITLAB_TOKEN", "others": []}),
                       ("other_host_token", {"case": "other_host_token", "env": None, "others": ["x.example"]}),
                       ("host_token_rejected", {"case": "host_token_rejected", "env": None, "others": []}),
                       ("lacks_rights", {"case": "lacks_rights", "env": None, "others": []}),
                       ("no_token", {"case": "no_token", "env": None, "others": []})):
        code = "forbidden" if name == "lacks_rights" else "unauthenticated"
        answer = vcs_evidence.failed_readiness(code, "githost.example", case)
        r, r0 = answer["remedy"], vcs_evidence.failed_readiness(code, "githost.example")["remedy"]
        check_eq(f"{name}: the first step is the connector, read_api is named, need/blocks/verify as before",
                 ("connector" in r["steps"][0], any("read_api" in s for s in r["steps"]),
                  [r[k] for k in ("need", "blocks", "verify")] == [r0[k] for k in ("need", "blocks", "verify")], answer["token_case"]),
                 (True, True, True, name))
    check_eq("a case on a code that is no token refusal changes nothing",
             vcs_evidence.failed_readiness("network_timeout", "h.example", {"case": "no_token"}),
             vcs_evidence.failed_readiness("network_timeout", "h.example"))

    # the note says it in words, not with our label (the person reads it verbatim)
    notes = {c: vcs_evidence.failed_readiness(c, "h.example")["note"] for c in ("unauthenticated", "forbidden", "cli_missing")}
    check("the refused note says the words, not the code",
          "the host answered 401: the call was not authenticated" in notes["unauthenticated"]
          and "rejected the token" not in notes["unauthenticated"] and "the host refused the request (403)" in notes["forbidden"]
          and "`glab` is not on PATH" in notes["cli_missing"]
          and not any(c in n for c, n in notes.items()) and all(n.startswith("GitLab API access refused: ") for n in notes.values())
          and all("Git/SSH access" in n for n in notes.values()), str(notes))
    check_eq("an unconfirmed code keeps its note",
             vcs_evidence.failed_readiness("network_timeout", "h.example")["note"].startswith("GitLab API access not verified: network_timeout."), True)

    # the data file holds the forms measured on glab 1.126.0 and 1.40.0; a line with neither form is not understood
    rules = vcs_evidence._auth_rules()
    check("glab-auth.json is read through the one reader and compiles", rules is not None and rules["env"] == list(VARS), str(rules))
    parsed = {name: vcs_evidence._auth_blocks(text, rules) for name, text in
              (("126 none", F126_NONE), ("126 config", F126_CONFIG), ("126 env", F126_ENV), ("140 none", F140_NONE), ("140 token", F140_TOKEN))}
    check_eq("each form matches the 1.126.0 and 1.40.0 fixtures",
             parsed, {"126 none": [("gitlab.com", "absent")], "126 config": [("gitlab.com", "present")], "126 env": [("gitlab.com", "present")],
                      "140 none": [("gitlab.com", "absent")], "140 token": [("gitlab.com", "present")]})
    check_eq("a fixture line with neither form gives unknown (a block, no state)",
             vcs_evidence._auth_blocks("gitlab.com\n  x gitlab.com: API call failed: GET https://gitlab.com/api/vX/user: 401\n", rules),
             [("gitlab.com", None)])
    check_eq("ANSI colour and an update notice with a URL do not open a block",
             vcs_evidence._auth_blocks("\x1b[1mgitlab.com\x1b[0m\n  \x1b[31mNo token found\x1b[0m\nA new version of glab is available: https://x.example/y\n", rules),
             [("gitlab.com", "absent")])

    # the doctor's eval 12 exists with its assertions (id 12, before id 13 of OH3-5)
    evals_path = Path(harness.SCRIPTS).parent / "skills" / "qa-doctor" / "evals" / "evals.json"
    evals = json.loads(evals_path.read_text(encoding="utf-8"))["evals"]
    ids = [e["id"] for e in evals]
    twelve = next((e for e in evals if e["id"] == 12), {})
    check("evals.json parses, ids unique, id 12 has its assertions",
          len(ids) == len(set(ids)) and len(twelve.get("assertions", [])) >= 5 and "GITLAB_TOKEN" in twelve.get("prompt", ""), str(ids))
finally:
    vcs_evidence.collect = fake_collect
    cleanup(root)

finish("test_vcs_evidence")
