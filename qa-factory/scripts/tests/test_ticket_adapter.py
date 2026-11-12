"""ticket_adapter.py — the file adapter against the QA-1 fixture, plus the command-template
adapters' exit-3 "never a crash, always an instruction" contract.

Most cases call ticket_adapter.main() in this process (`cli()`, the test_readiness.py `cli()`
shape): 28 child processes cost ~14 s for one file. Three stay real children, each marked CLI
CONTRACT below — `--selftest` (the script's own built-in contract), the first `get QA-1
--json` (argv parsing and a JSON-only stdout through a real process boundary), and the
`adapters.ticket` unset path (a bare `sys.exit(3)` from `fail()`, proven as a real process
exit code rather than a Python return value)."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    FIXTURES, PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, driver_sources, finish, run_script,
    temp_dir, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))
import ticket_adapter as TA  # noqa: E402
import run_py_entry  # noqa: E402
import runtime_paths as RP  # noqa: E402
import source_inventory as SI  # noqa: E402
import ticket_light as TL  # noqa: E402

FIXTURE_TICKETS = PLUGIN_ROOT / "evals" / "fixtures" / "tickets"


def run_adapter(root: Path, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return run_script("ticket_adapter.py", *args, env=env)


def cli(root: Path, *args) -> SimpleNamespace:
    """ticket_adapter.py's own main(), in this process — same argv, same exit code, same
    streams. `use_project()` sets CLAUDE_PROJECT_DIR AND clears hooklib's cached project root
    (ticket_adapter resolves it through hooklib.project_root(), which caches per process), so
    each call sees the root this call names, never a root a previous call cached."""
    use_project(root)
    out, err = io.StringIO(), io.StringIO()
    saved_argv, code = sys.argv, 0
    sys.argv = ["ticket_adapter.py", *[str(a) for a in args]]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = TA.main()
    except SystemExit as exc:
        code = 0 if exc.code is None else (exc.code if isinstance(exc.code, int) else 1)
    finally:
        sys.argv = saved_argv
    return SimpleNamespace(returncode=code if isinstance(code, int) else 0,
                           stdout=out.getvalue(), stderr=err.getvalue())


def write_config(root: Path, adapters_ticket: dict) -> None:
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["adapters"] = {"ticket": adapters_ticket}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")


# ---- t-267: the ticket by REST, in a light form: the command's own face (K4, K9, K8b exit, K12 exit) -------
FIX = FIXTURES / "ticket-15045"
KEY = "TP1-15045"
BASE = "https://jira.example.test"
RAW = (FIX / "raw-issue.json").read_bytes()
FIELDS = (FIX / "field.json").read_bytes()
DIRECT_API = {"base_url": BASE, "api_version": "2", "auth_type": "basic_token",
              "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN",
              "acceptance_criteria_fields": [], "custom_fields": ["customfield_20001"]}


def kline(label: str, text: str) -> None:
    print(f"{label}: {text}")


class Resp:
    def __init__(self, data, url):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.headers = {"Content-Type": "application/json"}
        self.url = url

    def read(self):
        return self.data

    def geturl(self):
        return self.url


class Transport:
    """A fake Jira, as in test_source_inventory: the first route whose text is in the URL answers (bytes or a
    dict = 200, an int = that status, a function of the request); every request is logged."""

    def __init__(self, routes):
        self.routes, self.log = list(routes), []

    def __call__(self, request, timeout=0):
        url = request.full_url
        self.log.append(url)
        for needle, answer in self.routes:
            if needle in url:
                if callable(answer):
                    answer = answer(request)
                if isinstance(answer, int):
                    raise urllib.error.HTTPError(url, answer, "status", {}, None)
                return Resp(answer, url)
        raise AssertionError("unexpected request: " + url)

    def count(self, needle: str) -> int:
        return sum(1 for url in self.log if needle in url)


def story_routes(extra=()):
    return Transport([*extra,
                      ("/issue/TP1-15045/remotelink", b"[]"),
                      ("/issue/TP1-15045?fields=*all", RAW),
                      ("/rest/api/2/field", FIELDS)])


def rest_config(root: Path, **ticket) -> None:
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["adapters"] = {"ticket": {"kind": "jira", "method": "api", "direct_api": dict(DIRECT_API), **ticket}}
    cfg["implementation_repos"] = [
        {"repo_id": "testproject1-backend", "local_path": "../../testproject1", "remote_identity": "git@gi.example.test:org-cdme/testproject1.git"},
        {"repo_id": "testproject1-ui", "local_path": "../../testproject1-ui", "remote_identity": "git@gi.example.test:org-cdme/testproject1-ui.git"}]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")


def with_transport(transport):
    """The adapter's own client constructor, wrapped: same config reading, a fake wire."""
    real = TA.client_from_config

    def patched(adapter_cfg):
        client = real(adapter_cfg)
        client.opener, client.sleeper = transport, (lambda seconds: None)
        return client

    TA.client_from_config = patched
    return real


def k4_problems(snapshot: dict, raw: bytes) -> list:
    """The K4 rule on a REST snapshot: source fetched, fields_requested "*all", bytes == len(raw), the hash of
    the raw bytes, and a fetched_at."""
    prov = snapshot.get("provenance") or {}
    problems = []
    if prov.get("source") != "fetched":
        problems.append("provenance.source is not `fetched`")
    if prov.get("fields_requested") != "*all":
        problems.append("provenance.fields_requested is not `*all`")
    if prov.get("bytes") != len(raw):
        problems.append("provenance.bytes is not the length of the raw response")
    if prov.get("sha256") != hashlib.sha256(raw).hexdigest():
        problems.append("provenance.sha256 is not the hash of the raw response")
    if not prov.get("fetched_at"):
        problems.append("provenance.fetched_at is absent")
    return problems


def rest_route() -> None:
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-rest-")
    real = TA.client_from_config
    try:
        rest_config(root)
        work = root / "qa-factory" / "artifacts" / KEY / "work"
        # --- K4: the REST read, provenance by code ---
        t = story_routes()
        with_transport(t)
        p = cli(root, "get", KEY, "--json", "--raw-dir", str(work / "ticket-raw"))
        check_eq("K4: get --json --raw-dir reads the ticket by REST: exit 0", p.returncode, 0)
        data = json.loads(p.stdout)
        check_eq("FR-14: stdout is the snapshot and nothing else (the notes went to stderr)", data["key"], KEY)
        raw = (work / "ticket-raw" / "issue.json").read_bytes()
        check_eq("K4: the request on the wire asks for every field", t.count("/issue/TP1-15045?fields=*all"), 1)
        check_eq("K4: provenance on REST holds, whole", k4_problems(data, raw), [])
        broken = json.loads(p.stdout)
        del broken["provenance"]["fetched_at"]
        check_in("K4 negative: a snapshot with fetched_at absent fails", "fetched_at is absent", k4_problems(broken, raw))
        wrong = json.loads(p.stdout)
        wrong["provenance"]["bytes"] += 1
        check_in("K4 negative: bytes != len(raw) fails", "bytes is not", k4_problems(wrong, raw))
        check_eq("get: 15 criteria, 1 comment, the parent, 2 attachments (light form)",
                 (len(data["acceptance_criteria"]), len(data["comments"]), data["parent"], len(data["attachments"])),
                 (15, 1, "TP1-14482", 2))
        check("get: the noise is gone from the light form (no `self`, no `avatarUrls`, no `emailAddress`)",
              not any(word in p.stdout for word in ('"self"', "avatarUrls", "emailAddress", "iconUrl")))
        check("get: the unnamed custom fields are not in it, the named one is",
              "customfield_20002" not in p.stdout and "customfield_20001" in p.stdout)
        check_eq("the work folder holds the view, the references, the seeded inventory and the raw folder",
                 sorted(path.name for path in work.iterdir()), ["source-inventory.json", "ticket-raw", "ticket-references.json", "ticket-view.md"])
        span_file = next((root / "qa-factory" / "state" / "telemetry").glob("command-*.jsonl"))
        spans = [json.loads(line) for line in span_file.read_text(encoding="utf-8").splitlines()]
        ends = [s for s in spans if s["phase"] == "end"]
        check_eq("K10 (the command): each of the 3 REST calls is a command span with bytes, for the ticket",
                 (len(ends), all(s.get("bytes") and s["task"] == KEY and s["span_kind"] == "command" for s in ends)), (3, True))
        # without --raw-dir the same read prints and writes nothing
        for path in list(work.iterdir()):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        p = cli(root, "get", KEY, "--json")
        check_eq("get without --raw-dir: exit 0, and nothing is written", (p.returncode, list(work.iterdir())), (0, []))
        # --- the paste: person_pasted, set by the route, never by the text ---
        paste = root / "paste.md"
        paste.write_text("---\nkey: QA-1\nsource: agent\nfetched_at: 2026-09-01T10:00:00Z\n---\n# T\n\nbody\n\n"
                         "## Acceptance criteria\n\n1. one\n", encoding="utf-8")
        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(paste))
        check_eq("K4: on a paste the provenance is `person_pasted` (the text's own `source: agent` is not believed)",
                 json.loads(p.stdout)["provenance"]["source"], "person_pasted")
        # old labels still read, as they were written (temporal): a snapshot of the route before D-06
        for label in ("jira_direct_api", "file", "agent"):
            old = root / f"old-{label}.json"
            old.write_text(json.dumps({"key": "QA-1", "title": "T", "provenance": {"source": label, "fetched_at": "2026-09-01T10:00:00Z"}}), encoding="utf-8")
            p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(old))
            check_eq(f"K4 (temporal): an old snapshot labelled `{label}` is read as it is, its label kept",
                     json.loads(p.stdout)["provenance"]["source"], label)
        kline("K4", f"fetched: source fetched, fields_requested *all, bytes {len(raw)} == len(issue.json), sha256 matches, fetched_at set; "
                    f"paste -> person_pasted; negative: fetched_at removed -> {k4_problems(broken, raw)}")
        # --- a 404 on the story: exit 1 (the driver's question), a lost login is not that ---
        with_transport(Transport([("/issue/TP1-15045", 404), ("/myself", {"accountId": "x"})]))
        p = cli(root, "get", KEY, "--json")
        check_eq("get: a 404 is exit 1 (reachable, not found), with a line that names the way on",
                 (p.returncode, "was not found" in p.stderr and "--ticket-file" in p.stderr), (1, True))
        # --- K12: an empty whitelist is a refusal naming the file ---
        bad = root / "jira-fields.json"
        bad.write_text(json.dumps(dict(TL.load_fields_table(), standard=[])), encoding="utf-8")
        saved, t = TL.FIELDS_TABLE_PATH, story_routes()
        with_transport(t)
        TL.FIELDS_TABLE_PATH = bad
        try:
            p = cli(root, "get", KEY, "--json")
        finally:
            TL.FIELDS_TABLE_PATH = saved
        check_eq("K12 / t-281 F3: an empty whitelist -> exit 4 (the factory's own fault), the line names the file, no request was made",
                 (p.returncode, "jira-fields.json" in p.stderr and "refused" in p.stderr, t.log), (4, True, []))
        # --- K8b at the command: a lost login is exit 5 with ONE line, never a question or a row ---
        inventory = work / "source-inventory.json"
        issue = {"id": "1", "key": "APP-1", "fields": {"summary": "s", "updated": "u", "description": "d",
                                                          "attachment": [{"id": "9", "filename": "a.png", "mimeType": "image/png", "size": 3,
                                                                          "content": BASE + "/file/9"}],
                                                          "comment": {"total": 0, "comments": []}}}
        t = Transport([("fields=updated", 401), ("/issue/APP-1?fields=*all", issue), ("/file/9", 401)])
        with_transport(t)
        p = cli(root, "collect", "APP-1", "--output", str(inventory), "--relation", "task", "--json")
        lines = [line for line in p.stderr.splitlines() if line.strip()]
        check_eq("K8b (command): a 401 mid-collect -> exit 5 (the driver's InfraStop:auth code)", p.returncode, 5)
        check_eq("K8b (command): ONE stderr line, and it names QA_JIRA_API_TOKEN", (len(lines), "QA_JIRA_API_TOKEN" in p.stderr), (1, True))
        saved_inventory = json.loads(inventory.read_text(encoding="utf-8"))
        check_eq("K8b (command): no unavailable row, the stop point is in the inventory",
                 ([s for s in saved_inventory["sources"] if s["status"] == "unavailable"], saved_inventory["auth_stop"]["stopped_at"]),
                 ([], "attachment a.png of APP-1"))
        # t-331 (B-256 b, FR-14): the stop is ALSO ONE error object on stdout under --json - the caller that parses
        # stdout gets the owner, not an empty string; still no half-written record, still no `unavailable` row.
        obj = one_json_object(p.stdout)
        check_eq("K8b (command): stdout is the ONE auth error object and nothing else (no half-written JSON)",
                 obj and (obj["ok"], obj["owner"], "QA_JIRA_API_TOKEN" in obj["message"]), (False, "auth", True))
        # --- K9: the attachment policy, at the command, through the config key ---
        def attachments_issue():
            def entry(number, name, mime, size):
                return {"id": str(number), "filename": name, "mimeType": mime, "size": size, "content": f"{BASE}/file/{number}"}
            return {"id": "1", "key": "APP-2", "fields": {"summary": "s", "updated": "u", "description": "d", "comment": {"total": 0, "comments": []},
                                                            "attachment": [entry(1, "at-limit.png", "image/png", 5 * 1024 * 1024),
                                                                           entry(2, "over-limit.png", "image/png", 5 * 1024 * 1024 + 1),
                                                                           entry(3, "demo.mp4", "video/mp4", 5),
                                                                           entry(4, "sneaky.mp4", "application/octet-stream", 5),
                                                                           entry(5, "tool.exe", "application/x-msdownload", 5),
                                                                           entry(6, "spec.pdf", "application/pdf", 5),
                                                                           entry(7, "big.pdf", "application/pdf", 10 * 1024 * 1024 + 1)]}}

        sizes = {1: 5 * 1024 * 1024, 2: 5 * 1024 * 1024 + 1, 3: 5, 4: 5, 5: 5, 6: 5, 7: 10 * 1024 * 1024 + 1}
        routes = [("/issue/APP-2?fields=*all", attachments_issue())] + [
            (f"/file/{n}", (lambda size: (lambda request: b"x" * size))(size)) for n, size in sizes.items()]

        def collect_receipts(policy_config):
            rest_config(root, **policy_config)
            t = Transport(routes)
            with_transport(t)
            target = root / ("inventory-" + ("off" if policy_config.get("attachments") else "default") + ".json")
            p = cli(root, "collect", "APP-2", "--output", str(target), "--relation", "task", "--json")
            record = next(s for s in json.loads(target.read_text(encoding="utf-8"))["sources"] if s["canonical_ref"].endswith("/APP-2"))
            return p, t, {r["filename"]: r for r in record["materials"]["attachments"]["items"]}, record

        p, t, receipts, record = collect_receipts({})
        check_eq("K9: collect exits 0 under the default policy", p.returncode, 0)
        check_eq("K9: AT the limit (5 MB image) -> downloaded", receipts["at-limit.png"]["status"], "read")
        check_eq("K9: limit + 1 byte -> skipped_by_policy:size", (receipts["over-limit.png"]["status"], receipts["over-limit.png"]["reason"]),
                 ("skipped_by_policy", "skipped_by_policy:size"))
        check_eq("K9: .mp4 never - by its mime type and by its suffix alone",
                 (receipts["demo.mp4"]["reason"], receipts["sneaky.mp4"]["reason"]), ("skipped_by_policy:never", "skipped_by_policy:never"))
        # t-278 (D1 flip): an executable is `never` (it was `type`), by its media type and by its suffix; a text-like
        # file is allowed under the limit, and an octet-stream file is decided by its suffix.
        check_eq("K9: an executable -> not downloaded, listed as `never` (the D1 flip: it was `type`)",
                 receipts["tool.exe"]["reason"], "skipped_by_policy:never")
        policy = SI.attachment_policy_for(SimpleNamespace(attachment_config={}))
        limit = 10 * 1024 * 1024
        verdicts = {name: SI.attachment_verdict(policy, name, mime, size) for name, mime, size in (
            ("data.json", "application/json", 5), ("notes.txt", "text/plain", 5), ("trace.har", "application/octet-stream", 5),
            ("run.log", "application/octet-stream", limit), ("run-big.log", "application/octet-stream", limit + 1),
            ("conf.yaml", "application/x-yaml", 5), ("setup.sh", "application/octet-stream", 5),
            ("a.dll", "application/octet-stream", 5), ("run.ps1", "text/plain", 5), ("tool.msi", "application/x-msi", 5),
            ("pack.zip", "application/octet-stream", 5), ("odd.xyz", "application/x-unknown", 5))}
        check_eq("K9 (D1): text-like types are allowed under the limit; octet-stream is decided by its suffix; only executables, "
                 "archives and video are never; a type no rule names is `type`; one byte over the limit is `size`",
                 verdicts, {"data.json": None, "notes.txt": None, "trace.har": None, "run.log": None, "run-big.log": "size",
                            "conf.yaml": None, "setup.sh": "never", "a.dll": "never", "run.ps1": "never", "tool.msi": "never",
                            "pack.zip": "never", "odd.xyz": "type"})
        # S6.01e DE-1 (m55, m56): a null media type is judged as `empty_mime_as`; never_suffixes still comes first.
        null_verdicts = {name: SI.attachment_verdict(policy, name, mime, size) for name, mime, size in (
            ("plan.md", None, 5), ("a.png", None, 5), ("odd.bin", None, 5), ("blank.bin", "   ", 5), ("nosize.bin", None, None),
            ("setup.sh", None, 5), ("A.EXE", None, 5), ("pack.zip", None, 5), ("odd.xyz", "application/x-unknown", 5),
            (None, None, 5), ("big.bin", None, limit + 1))}
        check_eq("DE-1: null/blank type -> downloaded (plan.md, a.png, odd.bin, a null name, size null); setup.sh, A.EXE, pack.zip "
                 "with null -> never; a named unknown type stays `type`; over the limit -> size",
                 null_verdicts, {"plan.md": None, "a.png": None, "odd.bin": None, "blank.bin": None, "nosize.bin": None,
                                 "setup.sh": "never", "A.EXE": "never", "pack.zip": "never", "odd.xyz": "type",
                                 None: None, "big.bin": "size"})
        # SC2-41 K9-real: the six real attachments of TP1-10937 (names, media types and sizes as the inventory holds them,
        # a null type as None; carrier: fixtures/investigation-14857/.../work/source-inventory.json) are all downloaded under the shipped policy
        real_10937 = (("2026-03-11_10h40_43.png", "image/png", 8533), ("plan.md", None, 6023), ("screenshot-1.png", "image/png", 93414),
                      ("screenshot-2.png", "image/png", 10330), ("screenshot-3.png", "image/png", 83997), ("spec.md", None, 5814))
        check_eq("K9-real: every real attachment of TP1-10937 is downloaded under the shipped policy (verdict None for all six)",
                 [SI.attachment_verdict(policy, name, mime, size) for name, mime, size in real_10937], [None] * 6)
        project_policy = SI.attachment_policy_for(SimpleNamespace(attachment_config={"rules": [{"class": "image", "mime_prefixes": ["image/"], "max_bytes": 5}]}))
        check_eq("DE-1: a project policy whose rules name no octet-stream: a null type is `type` (safe), not a download",
                 SI.attachment_verdict(project_policy, "odd.bin", None, 5), "type")
        no_key = dict(policy)
        no_key.pop("empty_mime_as")
        check_eq("DE-1: a policy with no empty_mime_as key leaves a null type as `type`", SI.attachment_verdict(no_key, "plan.md", None, 5), "type")
        # S601e-size-none (t-428): an unknown size cannot be judged, so the file is downloaded - and `int(None)` must never be reached
        limited = {"rules": [{"mime_prefixes": ["image/"], "max_bytes": 10}]}
        check_eq("K9: an unknown size (None) under a limit is downloaded, not an exception",
                 [SI.attachment_verdict(limited, "a.png", "image/png", size) for size in (None, 10, 11)], [None, None, "size"])
        check_eq("K9: an allowed type -> downloaded; a document over ITS limit -> size",
                 (receipts["spec.pdf"]["status"], receipts["big.pdf"]["reason"]), ("read", "skipped_by_policy:size"))
        check_eq("K9: the skipped ones were never requested", sorted(n for n in sizes if t.count(f"/file/{n}")), [1, 6])
        check("K9: a skip is settled-but-listed: it blocks nothing and makes no gap point (only downloads await inspection)",
              all(point["name"] in ("at-limit.png", "spec.pdf") for point in SI.gap_points(record) if point["kind"] == "attachment")
              and record["materials"]["attachments"]["status"] == "read")
        default_downloaded = sorted(f for f, r in receipts.items() if r["status"] == "read")
        p, t, receipts_off, record_off = collect_receipts({"attachments": {"policy": "off"}})
        check_eq("K9 negative: policy off -> every attachment is downloaded, as before D-06",
                 (sorted(f for f, r in receipts_off.items() if r["status"] == "read") == sorted(receipts_off), len(t.log) - 1), (True, 7))
        kline("K9", f"default policy: downloaded {default_downloaded}; skipped "
                    f"{ {f: r['reason'] for f, r in receipts.items() if r['status'] != 'read'} }; policy off: all 7 downloaded")
    finally:
        TA.client_from_config = real
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def attachment_blobs() -> None:
    """S6.01e DE-2 (m57), DE-3: the name of a stored blob, and a receipt of an unchanged revision."""
    root = temp_project("qa-factory-ticket-blobs-")
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "me@example.test", "tok"
    real = TA.client_from_config
    try:
        def entry(number, name, mime):
            return {"id": str(number), "filename": name, "mimeType": mime, "size": 5, "content": f"{BASE}/file/{number}"}
        issue = {"id": "1", "key": "APP-3", "fields": {"summary": "s", "updated": "u", "description": "d",
                                                         "comment": {"total": 0, "comments": []},
                                                         "attachment": [entry(1, "report.PDF", "application/octet-stream"),
                                                                        entry(2, "noext", "application/pdf"),
                                                                        entry(3, "a.png", "image/png"),
                                                                        entry(4, "copy.pdf", "application/pdf"),
                                                                        entry(5, "plan.md", None)]}}
        contents = {1: b"%PDF-", 2: b"%PDF-", 3: b"\x89PNG\r", 4: b"%PDF-", 5: b"# pla"}
        rest_config(root)
        with_transport(Transport([("/issue/APP-3?fields=*all", issue)] +
                                 [(f"/file/{n}", (lambda data: (lambda request: data))(data)) for n, data in contents.items()]))
        target = root / "inventory.json"

        def collect():
            p = cli(root, "collect", "APP-3", "--output", str(target), "--relation", "task", "--json")
            record = next(s for s in json.loads(target.read_text(encoding="utf-8"))["sources"] if s["canonical_ref"].endswith("/APP-3"))
            return p, {r["attachment_id"]: r for r in record["materials"]["attachments"]["items"]}

        p, items = collect()
        digest_pdf, digest_png, digest_md = (hashlib.sha256(contents[n]).hexdigest() for n in (1, 3, 5))
        check_eq("DE-2: collect exits 0", p.returncode, 0)
        check_eq("DE-2: a PDF by its NAME (report.PDF, mime octet-stream) and by its TYPE (no .pdf in the name) -> blobs/<digest>.pdf; "
                 "the same content under two names is one hash and one path",
                 (items["1"]["local_ref"], items["2"]["local_ref"], items["4"]["local_ref"]), (f"blobs/{digest_pdf}.pdf",) * 3)
        check_eq("DE-2: an image and a null-typed plan.md keep the bare blobs/<digest>; the hash is over the content",
                 (items["3"]["local_ref"], items["5"]["local_ref"], items["1"]["content_hash"]),
                 (f"blobs/{digest_png}", f"blobs/{digest_md}", digest_pdf))
        check("DE-2: the files exist at local_ref and plan.md (null type) was downloaded",
              all((target.parent / r["local_ref"]).is_file() for r in items.values()) and items["5"]["status"] == "read")
        # DE-3: the same revision, a receipt from before 1e (a bare blob) is reused as it is, checked by hash.
        old_ref = f"blobs/{digest_pdf}"
        (target.parent / old_ref).write_bytes(contents[1])
        data = json.loads(target.read_text(encoding="utf-8"))
        for source in data["sources"]:
            for receipt in source.get("materials", {}).get("attachments", {}).get("items", []):
                if receipt["attachment_id"] == "1":
                    receipt["local_ref"] = old_ref
        target.write_text(json.dumps(data), encoding="utf-8")
        p, again = collect()
        check_eq("DE-3: same revision: the old receipt keeps its bare path and is not renamed",
                 (p.returncode, again["1"]["local_ref"], again["1"]["status"], (target.parent / old_ref).is_file()), (0, old_ref, "read", True))
        (target.parent / old_ref).write_bytes(b"tampered")
        p, again = collect()
        check_eq("DE-3 negative: a stored blob whose hash no longer matches is not reused: it is fetched again under the new name",
                 (again["1"]["local_ref"], again["1"]["status"]), (f"blobs/{digest_pdf}.pdf", "read"))
    finally:
        TA.client_from_config = real
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def one_json_object(stdout: str):
    """The stdout of a failed `get --json` read the way the driver reads it: ONE line, one JSON object, nothing else."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    return json.loads(lines[0]) if len(lines) == 1 else None


def paste_route() -> None:
    """t-281 F1, F2, F4: a ticket the person pastes is parsed by the SAME parser as the REST description
    (`ticket_light.acceptance_criteria`, markup markdown), a text with no `# ` line takes its first line as the
    title and says so, and the paste-only read leaves `work/ticket-references.json`."""
    root = temp_project("qa-factory-ticket-paste-")
    try:
        rest_config(root)
        raw_issue = json.loads(RAW.decode("utf-8"))
        description, title = raw_issue["fields"]["description"], raw_issue["fields"]["summary"]
        counter = [0]

        def get_paste(text, *extra, name=None):
            counter[0] += 1
            path = root / (name or f"paste-{counter[0]}.md")
            path.write_bytes(text.encode("utf-8"))        # bytes: the CRLFs of the real description stay as they are
            return cli(root, "get", KEY, "--json", "--ticket-file", str(path), *extra), path

        # --- K-F1: the real 15045 description, pasted under a title line ---
        p, _ = get_paste("# " + title + "\n\n" + description)
        snap = json.loads(p.stdout)
        ac = snap["acceptance_criteria"]
        check_eq("K-F1: the 15045 description pasted under a `# ` title: exit 0 and 15 criteria", (p.returncode, len(ac)), (0, 15))
        check_eq("K-F1: item 1 and item 15 are verbatim", (ac[0], ac[14]),
                 ("Visual revision diff opens from workflow version history.",
                  "Existing workflow versioning/text diff behavior is not regressed."))
        check("K-F1 negative control: no glue of `QA Factory evaluation goals` into item 15 and no `Verify` line becomes a criterion",
              not any("QA Factory evaluation goals" in item or "Verify" in item for item in ac))
        table = TL.load_fields_table()
        check_eq("K-F1: ONE parser - the paste reads exactly what ticket_light reads from the same description (REST markup)",
                 ac, TL.acceptance_criteria(description, headings=table["acceptance_headings"], section_names=table["section_names"], markup="wiki"))
        check_eq("K-F1: the title is the `# ` line, and `title_from` is absent (no first-line fallback)",
                 (snap["title"], "title_from" in snap["provenance"], snap["provenance"]["source"]), (title, False, "person_pasted"))
        # --- K-F1b: every list marker is an item; `# ` is a heading in a markdown paste (C2) ---
        head = "# T\n\n## Acceptance criteria\n\n"
        for label, body in (("`- `", "- a\n- b\n"), ("`* `", "* a\n* b\n"), ("`+ `", "+ a\n+ b\n"), ("`1. `", "1. a\n2. b\n")):
            p, _ = get_paste(head + body)
            check_eq(f"K-F1b: {label} items under `## Acceptance criteria` -> 2 criteria", json.loads(p.stdout)["acceptance_criteria"], ["a", "b"])
        p, _ = get_paste(head + "# a\n# b\n")
        check_eq("K-F1b / C2: in a MARKDOWN paste `# a` is a heading, not an item: the section ends there and has 0 criteria",
                 json.loads(p.stdout)["acceptance_criteria"], [])
        p, _ = get_paste("# T\n\n## Acceptance criteria\n\n- a\ncontinued here\n- b\n\n## Comments\n\n- **po** (2026-09-10): hi\n")
        got = json.loads(p.stdout)
        check_eq("K-F1b: a continuation line joins its item; `## Comments` ends the section and is still read",
                 (got["acceptance_criteria"], len(got["comments"])), (["a continued here", "b"], 1))
        # --- K-F1n: the negative control - a text with no criteria heading has none ---
        p, _ = get_paste("# T\n\nJust a story.\n\n- a\n- b\n\n1. c\n")
        check_eq("K-F1n: a heading-less paste has 0 criteria (bullets alone are not criteria)", json.loads(p.stdout)["acceptance_criteria"], [])
        # --- the headings are the table's plus the project's own (the REST merge rule) ---
        text = "# T\n\nThings to verify\n\n- x\n- y\n"
        p, _ = get_paste(text)
        check_eq("K-F1 headings: a name only the project knows is not one before the config says so", json.loads(p.stdout)["acceptance_criteria"], [])
        write_config(root, {"kind": "jira", "method": "api", "direct_api": dict(DIRECT_API, acceptance_headings=["Things to verify"])})
        p, _ = get_paste(text)
        check_eq("K-F1 headings: `direct_api.acceptance_headings` adds a name to the table's", json.loads(p.stdout)["acceptance_criteria"], ["x", "y"])
        p, _ = get_paste(head + "- a\n")
        check_eq("K-F1 headings: and the table's own names still work beside it", json.loads(p.stdout)["acceptance_criteria"], ["a"])
        write_config(root, {"kind": "jira", "method": "api", "direct_api": dict(DIRECT_API, acceptance_headings="Things to verify")})
        p, _ = get_paste(text)
        obj = one_json_object(p.stdout)
        check_eq("K-F1 headings: a wrong-shaped config key is the factory's fault (exit 4) and the object names the key",
                 (p.returncode, obj and obj["owner"], obj and obj["file"]), (4, "factory", "direct_api.acceptance_headings"))
        rest_config(root)
        # --- an EMPTY paste: refused before any snapshot (the driver no longer refuses a title-less text) ---
        for label, text in (("0 bytes", ""), ("white space only", "  \n\t \n")):
            p, _ = get_paste(text)
            obj = one_json_object(p.stdout)
            check_eq(f"empty paste ({label}): exit 1, and under --json ONE error object on stdout, nothing else",
                     (p.returncode, obj and (obj["ok"], obj["owner"], obj["status"]), "is empty" in p.stderr), (1, (False, "person", None), True))
            check_in(f"empty paste ({label}): the sentence says what was expected", "expected the ticket as text", obj["message"])
        p, path = get_paste("")
        p = cli(root, "get", KEY, "--ticket-file", str(path))
        check_eq("empty paste without --json: the same exit, the sentence on stderr, stdout empty", (p.returncode, p.stdout, "is empty" in p.stderr), (1, "", True))
        # --- K-F2 (adapter half): a text with no `# ` line ---
        p, _ = get_paste("Items can carry tags\n\nAs a warehouse operator I want tags.\n")
        snap = json.loads(p.stdout)
        check_eq("K-F2: no `# ` line: the snapshot is returned, the title is the first line, `title_from` says so, the line is not repeated in the description",
                 (p.returncode, snap["title"], snap["provenance"]["title_from"], snap["description"]),
                 (0, "Items can carry tags", "first_line", "As a warehouse operator I want tags."))
        p, _ = get_paste("\n\n   Padded title line   \nbody\n")
        check_eq("K-F2: blank lines before the first line are skipped and the line is trimmed", json.loads(p.stdout)["title"], "Padded title line")
        p, _ = get_paste("x" * 200 + "\nbody\n")
        snap = json.loads(p.stdout)
        check_eq("K-F2 at the limit: a 200-character first line is the whole title and is consumed", (len(snap["title"]), snap["description"]), (200, "body"))
        p, _ = get_paste("y" * 201 + "\nbody\n")
        snap = json.loads(p.stdout)
        check_eq("K-F2 beyond the limit: a 201-character line is cut at 200 in the title and stays WHOLE at the top of the description (nothing lost)",
                 (len(snap["title"]), snap["description"].startswith("y" * 201), "body" in snap["description"]), (200, True, True))
        p, _ = get_paste("intro line\n# The real title\nbody\n")
        snap = json.loads(p.stdout)
        check_eq("K-F2: a `# ` line anywhere is the title (as before), and then there is no `title_from`",
                 (snap["title"], "title_from" in snap["provenance"]), ("The real title", False))
        # the conflicting pair (F2 vs F1): the first line is the title AND takes part in the criteria scan
        p, _ = get_paste("Acceptance criteria\n\n- one\n- two\n")
        snap = json.loads(p.stdout)
        check_eq("F2 + F1: a paste whose first line IS the criteria heading gives that title AND those criteria",
                 (snap["title"], snap["provenance"]["title_from"], snap["acceptance_criteria"]), ("Acceptance criteria", "first_line", ["one", "two"]))
        # a snapshot of the file adapter keeps today's rule: the key when there is no title (no first-line fallback off the paste route)
        file_snap = TA.get_file("QA-1", {"path": str(FIXTURE_TICKETS)})
        check_eq("the file adapter (not a paste) is untouched: its `# ` title, no `title_from`", (file_snap["title"], "title_from" in file_snap["provenance"]),
                 (file_snap["title"], False))

        # --- loss at the entrance: every section stays in the description, verbatim; criteria and comments are PARSED from it ---
        p, _ = get_paste("---\nkey: QA-9\n---\n# T\n\nIntro.\n\n## Implementation\n\nMR !5 in testproject1, see QA-77.\n\n"
                         "## Acceptance criteria\n\n- a\n- b\n\n## Comments\n\n- **po** (2026-09-10): hi\n")
        snap = json.loads(p.stdout)
        check_eq("entrance: the front matter and the title line are consumed; every `## ` section stays in the description",
                 ("key:" in snap["description"], "# T" in snap["description"], snap["description"].startswith("Intro."),
                  all(part in snap["description"] for part in ("## Implementation", "MR !5 in testproject1, see QA-77.", "## Acceptance criteria", "- a\n- b", "## Comments", "- **po** (2026-09-10): hi"))),
                 (False, False, True, True))
        check_eq("entrance: and the criteria and the comments are still parsed from it", (snap["acceptance_criteria"], [c["text"] for c in snap["comments"]]), (["a", "b"], ["hi"]))
        work_i = root / "qa-factory" / "artifacts" / KEY / "work-implementation"
        _, _ = get_paste("# T\n\n## Implementation\n\nMR !5 in testproject1, see QA-77.\n", "--raw-dir", str(work_i / "ticket-raw"))
        refs = json.loads((work_i / "ticket-references.json").read_text(encoding="utf-8"))["rows"]
        check_eq("entrance: the reference scan sees the line in the `## Implementation` section (the MR is tied to its repo, the key is a row)",
                 (sorted(r["ref"] for r in refs if r["kind"] == "ticket"), [r.get("repo_id") for r in refs if r["kind"] == "merge_request"]), (["QA-77"], ["testproject1-backend"]))
        p, _ = get_paste("# " + title + "\n\n" + description)
        snap = json.loads(p.stdout)
        check_eq("entrance: the 15045 paste still gives 15 criteria, and its description holds the criteria section whole",
                 (len(snap["acceptance_criteria"]), "What needs to be tested" in snap["description"], "1. Visual revision diff opens from workflow version history." in snap["description"],
                  "QA Factory evaluation goals" in snap["description"]), (15, True, True, True))
        # --- K-F4 (adapter half): the paste-only leg writes the references of the PERSON's text ---
        work = root / "qa-factory" / "artifacts" / KEY / "work"
        p, path = get_paste("# " + title + "\n\n" + description, "--raw-dir", str(work / "ticket-raw"), name="p15045.md")
        document = json.loads((work / "ticket-references.json").read_text(encoding="utf-8"))
        rows = document["rows"]
        tickets = [r for r in rows if r["kind"] == "ticket"]
        check_eq("K-F4: the paste-only read exits 0 and writes ticket-references.json with written_by [S0]",
                 (p.returncode, document["written_by"], document["ticket"]), (0, ["S0"], KEY))
        check_eq("K-F4: ticket rows: one row per key, every one `unproven` with the reason `no tracker read at S0`",
                 (sorted(r["ref"] for r in tickets), {(r["status"], r["reason"]) for r in tickets}),
                 (["TP1-14482"], {("unproven", "no tracker read at S0")}))
        check_eq("K-F4: the key is named by the title and the description: both origins on ONE row",
                 sorted(tickets[0]["origins"]), ["mention:description", "mention:summary"])
        check_eq("K-F4: the merge requests are tied to their repositories by the project's own repos",
                 sorted((r["ref"], r.get("repo_id")) for r in rows if r["kind"] == "merge_request"),
                 [("!1881", "testproject1-ui"), ("!4214", "testproject1-backend")])
        check_eq("K-F4: the two local paths are listed, not fetched",
                 sorted(r["ref"] for r in rows if r["kind"] == "local_path"),
                 ["~/Projects/testproject1-dev/testproject1", "~/Projects/testproject1-dev/testproject1-ui"])
        check("K-F4: nothing else is written by the paste-only read (no raw folder: no tracker was read)", not (work / "ticket-raw").exists())
        # FR-23: no reference in the text is still a recorded result - an empty list
        for stale in work.iterdir():
            stale.unlink()
        p, _ = get_paste("# A title\n\nNothing here points anywhere.\n", "--raw-dir", str(work / "ticket-raw"))
        document = json.loads((work / "ticket-references.json").read_text(encoding="utf-8"))
        check_eq("K-F4 / FR-23: a paste with no references still writes the file, with an empty list", (p.returncode, document["rows"], document["written_by"]), (0, [], ["S0"]))
        (work / "ticket-references.json").unlink()
        p, _ = get_paste("# " + title + "\n\n" + description)
        check("K-F4: without --raw-dir the paste read writes nothing", not (work / "ticket-references.json").exists())
        kline("K-F1/K-F2/K-F4", "pasted 15045 -> 15 criteria (item 1 / 15 verbatim, no glue); bullets -> 2; heading-less -> 0; no-title -> first_line; "
                                "paste-only references: 1 ticket row unproven, 2 MRs tied, 2 local paths; empty list written when nothing is referenced")
    finally:
        cleanup(root)


def owners_of_a_failed_read() -> None:
    """t-281 F3: the exit codes of `get` say WHOSE fault a failed read is (3 the tracker's, 4 the factory's, 5 the login's)
    and, under --json, ONE error object on stdout says it again for a machine."""
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-owners-")
    real = TA.client_from_config
    try:
        rest_config(root)

        def slow(request):
            raise urllib.error.HTTPError(request.full_url, 429, "slow", {"Retry-After": "20"}, None)

        def boom(request):
            raise RuntimeError("boom")

        issue = "/issue/TP1-15045?fields=*all"
        # 5xx after the retries: the tracker's, exit 3, the status in the object
        with_transport(Transport([(issue, 503)]))
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("K-F3: 503 after the retries -> exit 3, ONE object: owner tracker, status 503, no retry_at",
                 (p.returncode, obj and (obj["ok"], obj["owner"], obj["status"], obj["retry_at"]), "file" in (obj or {})), (3, (False, "tracker", 503, None), False))
        check_in("K-F3: the sentence in the object is the one on stderr (one sentence, no newline)", "the tracker could not be read for", obj["message"])
        check_eq("K-F3: stderr keeps the human sentence", "the tracker could not be read for" in p.stderr, True)
        # a retry the tracker asked for later: the TIME is in the object
        with_transport(Transport([(issue, slow)]))
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("K-F3: Retry-After 20 -> exit 3, the object carries status 429 and retry_at as an ISO time",
                 (p.returncode, obj["owner"], obj["status"], isinstance(obj["retry_at"], str) and obj["retry_at"].endswith("Z") and "T" in obj["retry_at"]),
                 (3, "tracker", 429, True))
        check_in("K-F3: and the same time is in the stderr sentence", obj["retry_at"], p.stderr)
        # a 404 with the login proven fine: exit 1 (as before), the tracker's owner
        with_transport(Transport([(issue, 404), ("/myself", {"accountId": "x"})]))
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("K-F3: 404 with the login fine -> exit 1, object owner tracker, status 404", (p.returncode, obj["owner"], obj["status"]), (1, "tracker", 404))
        # a lost login: exit 5, owner auth
        with_transport(Transport([(issue, 401), ("/myself", 401)]))
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("K-F3: a lost login -> exit 5 (as built), object owner auth, naming the token variable",
                 (p.returncode, obj and obj["owner"], obj and "QA_JIRA_API_TOKEN" in obj["message"], p.stderr.count("\n")), (5, "auth", True, 1))
        # an unexpected exception: the factory's, exit 4, no file to name
        with_transport(Transport([(issue, boom)]))
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("K-F3: an unexpected exception -> exit 4, owner factory, `file` present and null", (p.returncode, obj["owner"], obj["file"], obj["message"]),
                 (4, "factory", None, "unexpected error: boom"))
        # the catch-alls of the other verbs are the same fault, through the same helper (t-281 follow-up): exit 4, the object
        everything = Transport([("/", boom)])
        with_transport(everything)
        inventory = root / "inv.json"
        broken_inventory = root / "broken-inv.json"
        broken_inventory.write_text("not json", encoding="utf-8")
        for verb, args in (("collect", ("collect", "APP-1", "--output", str(inventory), "--relation", "task")),
                           ("peek", ("peek", "APP-1", "--output", str(inventory))),
                           ("refresh", ("refresh", "--output", str(broken_inventory))),
                           ("probe", ("probe", "--output", str(root / "receipt.json"), "APP-1"))):
            p = cli(root, *args, "--json")
            obj = one_json_object(p.stdout)
            check_eq(f"K-F3 analog: an unexpected exception in `{verb}` -> exit 4, ONE object: owner factory, stderr keeps the sentence",
                     (p.returncode, obj and (obj["ok"], obj["owner"]), "unavailable" in p.stderr or "unexpected" in p.stderr), (4, (False, "factory"), True))
            plain = cli(root, *args)
            check_eq(f"K-F3 analog: `{verb}` without --json: the same exit, stdout empty", (plain.returncode, plain.stdout), (4, ""))
        # a corrupted jira-fields.json (a COPY under the test's tmp dir, never the real file) -> exit 4, the file named
        bad = root / "jira-fields.json"
        bad.write_text(json.dumps(dict(TL.load_fields_table(), standard=[])), encoding="utf-8")
        saved, t = TL.FIELDS_TABLE_PATH, story_routes()
        with_transport(t)
        TL.FIELDS_TABLE_PATH = bad
        try:
            p = cli(root, "get", KEY, "--json")
            plain = cli(root, "get", KEY)
        finally:
            TL.FIELDS_TABLE_PATH = saved
        obj = one_json_object(p.stdout)
        check_eq("K-F3: a corrupted jira-fields.json -> exit 4, owner factory, the object names the file, no request was made",
                 (p.returncode, obj["owner"], obj["file"], obj["status"], t.log), (4, "factory", "jira-fields.json", None, []))
        check_eq("K-F3: a call WITHOUT --json keeps today's behaviour: the sentence on stderr, stdout empty, the same exit",
                 (plain.returncode, plain.stdout, "jira-fields.json" in plain.stderr), (4, "", True))
        check("K-F3: the real table was not touched", TL.FIELDS_TABLE_PATH == saved and TL.load_fields_table()["standard"])
        # a missing table file (copy that does not exist)
        TL.FIELDS_TABLE_PATH = root / "no-such-table.json"
        try:
            p = cli(root, "get", KEY, "--json")
        finally:
            TL.FIELDS_TABLE_PATH = saved
        obj = one_json_object(p.stdout)
        check_eq("K-F3: a missing table -> exit 4, the file is named", (p.returncode, obj["owner"], obj["file"]), (4, "factory", "no-such-table.json"))
        # exit 3 stays for a project with no way to read set up (the driver asks the person, `ticket_read`)
        write_config(root, {"kind": "jira", "mcp_tool": "jira_get_issue"})
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("K-F3: not set up -> exit 3, owner tracker (the person's question), one object", (p.returncode, obj["owner"]), (3, "tracker"))
        kline("K-F3", "503 -> 3/tracker/503; Retry-After 20 -> 3/retry_at ISO; 404 -> 1; 401 -> 5/auth; exception -> 4/factory; "
                      "corrupted jira-fields.json copy -> 4/factory/file jira-fields.json; stdout is ONE object, stderr keeps the sentence")
    finally:
        TA.client_from_config = real
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def t287_paste_markup_and_title() -> None:
    """t-287 item 1: the description is the body minus the TITLE LINE only (text above the title stays); a text with any
    `h2.`-style line is WIKI (`# ` is a list item, the title is the header's `title:` or the first plain line); the
    reading is recorded as `provenance.markup`; a snapshot written before the key existed is read as it is."""
    root = temp_project("qa-factory-ticket-t287-paste-")
    try:
        rest_config(root)
        raw_issue = json.loads(RAW.decode("utf-8"))
        description, title = raw_issue["fields"]["description"], raw_issue["fields"]["summary"]
        counter = [0]

        def paste(text, *extra):
            counter[0] += 1
            path = root / f"t287-{counter[0]}.md"
            path.write_bytes(text.encode("utf-8"))
            p = cli(root, "get", KEY, "--json", "--ticket-file", str(path), *extra)
            return p, (json.loads(p.stdout) if p.returncode == 0 else None)

        # --- the critic's markdown probe: the sentence above the `# ` title stays in the description ---
        p, snap = paste("Copied from the browser tab, nothing else changed.\n# T\n\n## Acceptance criteria\n\n1. one\n")
        check_eq("item 1 (markdown probe): the sentence ABOVE the `# ` title is in the description, the title line is not, AC 1, markup markdown",
                 (p.returncode, snap["title"], snap["description"].startswith("Copied from the browser tab"), "# T" in snap["description"],
                  snap["acceptance_criteria"], snap["provenance"]["markup"]), (0, "T", True, False, ["one"], "markdown"))
        check_eq("item 1 (markdown): no `title_from` when a `# ` line gave the title", "title_from" in snap["provenance"], False)
        # --- the wiki probe: `h2. Acceptance Criteria` and `# ` items ---
        wiki = "Items can carry tags\n\nAs a warehouse operator I want tags.\n\nh2. Acceptance Criteria\n# one\n# two\n"
        p, snap = paste(wiki)
        check_eq("item 1 (wiki probe): 2 criteria, and the `# ` items are not the title: the first plain line is, and it leaves the description",
                 (p.returncode, snap["acceptance_criteria"], snap["title"], snap["provenance"]["markup"], snap["provenance"].get("title_from"),
                  snap["description"]),
                 (0, ["one", "two"], "Items can carry tags", "wiki", "first_line",
                  "As a warehouse operator I want tags.\n\nh2. Acceptance Criteria\n# one\n# two"))
        # the header's `title:` is the title and consumes no line
        p, snap = paste("---\ntitle: Tagged items\n---\nh2. Acceptance Criteria\n# one\n# two\n")
        check_eq("item 1 (wiki): the header's `title:` is the title, no `title_from`, the whole body is the description",
                 (snap["title"], "title_from" in snap["provenance"], snap["acceptance_criteria"], snap["description"].startswith("h2. Acceptance Criteria")),
                 ("Tagged items", False, ["one", "two"], True))
        # the conflicting pair: BOTH an `h2.` line and a `# ` line -> wiki wins, the `# ` line is an item, never the title
        p, snap = paste("Plain first line\n# Looks like a markdown title\n\nh2. Acceptance Criteria\n# a\n# b\n")
        check_eq("item 1 (both): `h2.` and a `# ` line -> WIKI wins: the `# ` line is a list item (it stays in the description), the title is the first plain line",
                 (snap["provenance"]["markup"], snap["title"], "# Looks like a markdown title" in snap["description"], snap["acceptance_criteria"]),
                 ("wiki", "Plain first line", True, ["a", "b"]))
        p, snap = paste("# Only a `# ` line\n\nh2. Acceptance Criteria\n# a\n# b\n")
        check_eq("item 1 (both, no plain line at all): the first non-empty line is taken as the title (asked once) - AC is still read the wiki way",
                 (snap["provenance"]["markup"], snap["provenance"].get("title_from"), snap["acceptance_criteria"]), ("wiki", "first_line", ["a", "b"]))
        # the boundary of the detector: h6. is a heading, h7. and `h2.Title` (no space) are not
        check_eq("item 1 (boundary): `h6. x` makes it wiki",
                 (TA.detect_markup("h6. x"), TA.detect_markup("x\nh6. y\n")), ("wiki", "wiki"))
        check_eq("item 1 (beyond the boundary): `h7. x`, `h2.x`, an indented `h2. x` and `h2.` inside a line are markdown",
                 [TA.detect_markup(t) for t in ("h7. x", "h2.x", "  h2. x", "see h2. x", "# T\n")], ["markdown"] * 5)
        # CRLF and a long list
        p, snap = paste("Title line\r\n\r\nh2. Acceptance Criteria\r\n# a\r\n# b\r\n")
        check_eq("item 1 (CRLF wiki): the same reading", (snap["title"], snap["acceptance_criteria"]), ("Title line", ["a", "b"]))
        p, snap = paste("Big\n\nh2. Acceptance Criteria\n" + "".join(f"# item {n}\n" for n in range(3000)))
        check_eq("item 1 (magnitude): 3000 wiki items -> 3000 criteria, the first and the last verbatim",
                 (len(snap["acceptance_criteria"]), snap["acceptance_criteria"][0], snap["acceptance_criteria"][-1]), (3000, "item 0", "item 2999"))
        # an empty body after the title: description "" and the no-criteria path (the driver's question)
        p, snap = paste("# T\n")
        check_eq("item 1 (empty body after the title): exit 0, description \"\", no criteria (the driver asks the person)",
                 (p.returncode, snap["title"], snap["description"], snap["acceptance_criteria"]), (0, "T", "", []))
        # the 15045 markdown paste is unchanged: 15 criteria, read as markdown
        p, snap = paste("# " + title + "\n\n" + description)
        check_eq("item 1: the 15045 markdown paste is unchanged: 15 criteria, markup markdown, its title",
                 (len(snap["acceptance_criteria"]), snap["provenance"]["markup"], snap["title"]), (15, "markdown", title))
        # --- temporal (K11 style): a snapshot written BEFORE `markup` existed is read as it is, nothing is added ---
        old = root / "old-snapshot.json"
        old_doc = {"key": KEY, "title": "T", "description": "d", "acceptance_criteria": ["x"],
                   "provenance": {"source": "person_pasted", "fetched_at": None}}
        old.write_text(json.dumps(old_doc), encoding="utf-8")
        p = cli(root, "get", KEY, "--json", "--ticket-file", str(old))
        got = json.loads(p.stdout)
        check_eq("item 1 (temporal): an older snapshot with no `markup` is read unchanged - its provenance is exactly what it was, its criteria are its own",
                 (got["provenance"], got["acceptance_criteria"]), (old_doc["provenance"], ["x"]))
        p = cli(root, "diff", "--old", str(old), "--new", str(old), "--json")
        check_eq("item 1 (temporal): and diff of it against itself is none", json.loads(p.stdout)["severity"], "none")
    finally:
        cleanup(root)


def t287_unusable_direct_api_and_missing_token() -> None:
    """t-287 items 2, 3, 5 and 7 at the command."""
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-t287-config-")
    real = TA.client_from_config
    try:
        # --- item 2: a recorded direct_api that is not usable is the PROJECT's setting: exit 3, owner `config` ---
        stub = {"custom_fields": [], "acceptance_headings": []}
        write_config(root, {"kind": "jira", "method": "api", "direct_api": stub})
        t = story_routes()
        with_transport(t)
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        message = (obj or {}).get("message", "")
        check_eq("item 2: the template stub -> exit 3, ONE object, owner `config`, no file named, no request made",
                 (p.returncode, obj and (obj["ok"], obj["owner"]), "file" in (obj or {}), t.log), (3, (False, "config"), False, []))
        check_eq("item 2: the sentence names every missing key by its full name",
                 [f"adapters.ticket.direct_api.{key}" in message for key in ("base_url", "auth_type", "secret_ref", "username_ref")], [True] * 4)
        check_eq("item 2: and the door, and no flag a person would have to read as jargon",
                 ("/qa-factory:qa-onboarding" in message, "--" in message), (True, False))
        check_eq("item 2: stderr keeps the same sentence, once", (p.stderr.count("\n"), message in " ".join(p.stderr.split())), (1, True))
        # only what is missing is named
        write_config(root, {"kind": "jira", "method": "api", "direct_api": {"base_url": BASE, "auth_type": "bearer"}})
        obj = one_json_object(cli(root, "get", KEY, "--json").stdout)
        named = [key for key in ("base_url", "auth_type", "secret_ref", "username_ref") if f"direct_api.{key}" in obj["message"]]
        check_eq("item 2: a bearer config with no secret names `secret_ref` only (username_ref is for basic_token)", (obj["owner"], named), ("config", ["secret_ref"]))
        write_config(root, {"kind": "jira", "method": "api", "direct_api": {"base_url": BASE, "auth_type": "basic_token", "secret_ref": "QA_JIRA_API_TOKEN"}})
        obj = one_json_object(cli(root, "get", KEY, "--json").stdout)
        named = [key for key in ("base_url", "auth_type", "secret_ref", "username_ref") if f"direct_api.{key}" in obj["message"]]
        check_eq("item 2: a basic_token config with no user reference names `username_ref` only", (obj["owner"], named), ("config", ["username_ref"]))
        # every key there, a wrong shape: the client's own reason is quoted, and no key is claimed missing
        write_config(root, {"kind": "jira", "method": "api", "direct_api": dict(DIRECT_API, acceptance_criteria_fields="customfield_1")})
        obj = one_json_object(cli(root, "get", KEY, "--json").stdout)
        check_eq("item 2: a wrong-shaped optional key -> still `config`, the sentence quotes the reason, it does not claim a key is missing",
                 (obj["owner"], "must be a string array" in obj["message"], "lacks" in obj["message"]), ("config", True, False))
        # `direct_api: {}` keeps today's path (the tracker's: nothing to read through)
        write_config(root, {"kind": "jira", "direct_api": {}})
        obj = one_json_object(cli(root, "get", KEY, "--json").stdout)
        check_eq("item 2: `direct_api: {}` keeps today's path: exit 3, owner tracker, the command-template sentence",
                 (obj["owner"], "neither 'command' nor 'mcp_tool'" in obj["message"]), ("tracker", True))
        # a usable config is unchanged
        rest_config(root)
        t = story_routes()
        with_transport(t)
        p = cli(root, "get", KEY, "--json")
        check_eq("item 2 (positive control): a usable direct_api reads as before", (p.returncode, json.loads(p.stdout)["key"], len(t.log) > 0), (0, KEY, True))

        # --- item 3: a token variable the shell lacks is the LOGIN's (exit 5), names the variable, no request ---
        del os.environ["QA_JIRA_API_TOKEN"]
        t = story_routes()
        with_transport(t)
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        message = (obj or {}).get("message", "")
        check_eq("item 3: the token variable unset -> exit 5, owner auth, ONE object, and not one request was made",
                 (p.returncode, obj and obj["owner"], t.log), (5, "auth", []))
        check_eq("item 3: the object names the VARIABLE and not the (set) user's value; no network or VPN sentence",
                 ("QA_JIRA_API_TOKEN" in message, "reader@example.invalid" in p.stdout + p.stderr, "network" in message.lower() or "vpn" in message.lower()),
                 (True, False, False))
        check_eq("item 3: stderr is ONE line and names the variable", (p.stderr.count("\n"), "QA_JIRA_API_TOKEN" in p.stderr), (1, True))
        os.environ["QA_JIRA_API_TOKEN"] = "test-only-token"
        os.environ.pop("QA_JIRA_EMAIL")
        t = story_routes()
        with_transport(t)
        p = cli(root, "get", KEY, "--json")
        obj = one_json_object(p.stdout)
        check_eq("item 3: the USER variable unset (the token set) -> the same exit and owner, naming that variable, never the token's value",
                 (p.returncode, obj["owner"], "QA_JIRA_EMAIL" in obj["message"], "test-only-token" in p.stdout + p.stderr, t.log), (5, "auth", True, False, []))
        del os.environ["QA_JIRA_API_TOKEN"]
        t = story_routes()
        with_transport(t)
        obj = one_json_object(cli(root, "get", KEY, "--json").stdout)
        check_eq("item 3: both unset -> both named, once each", (obj["message"].count("QA_JIRA_EMAIL"), obj["message"].count("QA_JIRA_API_TOKEN")), (1, 1))
        inventory = root / "inv-missing.json"
        for verb, args in (("collect", ("collect", KEY, "--output", str(inventory), "--relation", "task")),
                           ("peek", ("peek", KEY, "--output", str(inventory))),
                           ("probe", ("probe", "--output", str(root / "receipt.json"), KEY))):
            t = story_routes()
            with_transport(t)
            p = cli(root, *args, "--json")
            obj = one_json_object(p.stdout)
            # every verb prints the ONE stderr line, exits 5 and (t-331, FR-14) the ONE auth object under --json
            check_eq(f"item 3 (same class): `{verb}` with the token variable unset -> exit 5, the variable named on stderr, no request",
                     (p.returncode, "QA_JIRA_API_TOKEN" in p.stderr, t.log), (5, True, []))
            check_eq(f"item 3 (same class): `{verb}` prints the auth object", obj and obj["owner"], "auth")
        os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
        t = story_routes()
        with_transport(t)
        p = cli(root, "get", KEY, "--json")
        check_eq("item 3 (positive control): the same call with both variables set reads the ticket", (p.returncode, len(t.log) > 0), (0, True))

        # --- item 5: `## comments` in any case is the comments section: a new comment alone is `context` ---
        base = (FIXTURE_TICKETS / "QA-1.md").read_text(encoding="utf-8")
        check("item 5 setup: the fixture has a `## Comments` section", "## Comments" in base)
        old_text = base.replace("## Comments", "## comments")
        old, new = root / "lower-old.md", root / "lower-new.md"
        old.write_text(old_text, encoding="utf-8")
        new.write_text(old_text + "\n- **po** (2026-09-13): one more thought.\n", encoding="utf-8")
        p = cli(root, "diff", "--old", str(old), "--new", str(new), "--json")
        result = json.loads(p.stdout)
        check_eq("item 5: a new comment under `## comments` is severity `context`, not a requirements change",
                 (result["severity"], result["changed"]), ("context", ["comments"]))
        for spelling in ("## COMMENTS", "## Comments"):
            old.write_text(base.replace("## Comments", spelling), encoding="utf-8")
            new.write_text(base.replace("## Comments", spelling) + "\n- **po** (2026-09-13): one more thought.\n", encoding="utf-8")
            check_eq(f"item 5: {spelling} reads the same", json.loads(cli(root, "diff", "--old", str(old), "--new", str(new), "--json").stdout)["severity"], "context")
        new.write_text(old_text.replace("at most 5 tags", "at most 7 tags") + "\n- **po** (2026-09-13): one more thought.\n", encoding="utf-8")
        old.write_text(old_text, encoding="utf-8")
        check_eq("item 5 (negative control): an edited criterion beside the comment is still `requirements`",
                 json.loads(cli(root, "diff", "--old", str(old), "--new", str(new), "--json").stdout)["severity"], "requirements")

        # --- item 7: the `diff` catch-all is the factory's own fault, exit 4, like the other verbs ---
        saved = TA.diff_tickets

        def boom(*_args):
            raise RuntimeError("boom")

        TA.diff_tickets = boom
        try:
            p = cli(root, "diff", "--old", str(old), "--new", str(new), "--json")
            plain = cli(root, "diff", "--old", str(old), "--new", str(new))
        finally:
            TA.diff_tickets = saved
        obj = one_json_object(p.stdout)
        check_eq("item 7: an unexpected exception in `diff` -> exit 4, ONE object: owner factory, `file` present and null, the sentence",
                 (p.returncode, obj and (obj["ok"], obj["owner"], obj["file"], obj["message"])), (4, (False, "factory", None, "unexpected error: boom")))
        check_eq("item 7: without --json: exit 4, the sentence on stderr, stdout empty", (plain.returncode, plain.stdout, "unexpected error: boom" in plain.stderr), (4, "", True))
        check_eq("item 7 (positive control): the real diff still works", cli(root, "diff", "--old", str(old), "--new", str(old), "--json").returncode, 0)
    finally:
        TA.client_from_config = real
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def public_name_of_the_usable_check() -> None:
    """t-281 F10: the driver calls the public name; the private one stays for one release, as the same function."""
    check("F10: has_usable_direct_api is public and the old private name is the same function", TA._has_usable_direct_api is TA.has_usable_direct_api)
    check_eq("F10: it answers True for a complete direct_api and False for none", (TA.has_usable_direct_api({"direct_api": dict(DIRECT_API)}), TA.has_usable_direct_api({})), (True, False))
    check_eq("F10: and False for an incomplete one", TA.has_usable_direct_api({"direct_api": {"base_url": BASE}}), False)


# ---- t-331 (B-256 a, b): the wiki twin of the comments section, the owners of a failed read, one error object ----------

WIKI_TICKET = ("Tagged items\n\n"
               "h2. Description\nAs a warehouse operator I want tags.\n\n"
               "{code}\nh2. Comments\n- **ghost** (2026-01-01): inside a code block\n{code}\n\n"
               "h2. Acceptance Criteria\n* one\n* two\n\n"
               "h3. Notes\n* a note\n\n"
               "h2. Comments\n- **po** (2026-09-12): first\n- **dev** (2026-09-13): second\n")
WIKI_COMMENTS = [{"author": "po", "date": "2026-09-12", "text": "first"},
                 {"author": "dev", "date": "2026-09-13", "text": "second"}]
NEW_COMMENT = "- **qa** (2026-09-14): third\n"
ERROR_KEYS = {"ok", "owner", "status", "retry_at", "message"}


def error_shape(label: str, obj, owner: str) -> None:
    """FR-14: the object a failed `--json` call prints is the ONE shape - the same five keys, `file` only for the
    factory and the person (t-335 B-n4: the file that is missing, ours to restore or theirs to supply), the owner one
    of `TA.OWNERS` - whichever verb printed it."""
    keys = set(obj) if isinstance(obj, dict) else None
    want = ERROR_KEYS | ({"file"} if owner in ("factory", "person") else set())
    check_eq(f"t-331 {label}: ONE object, ok false, owner {owner}, keys {sorted(want)}",
             (keys, obj and obj["ok"], obj and obj["owner"]), (want, False, owner))
    check(f"t-331 {label}: the owner is one of TA.OWNERS", bool(obj) and obj["owner"] in TA.OWNERS)


def t331_wiki_sections() -> None:
    root = temp_project("qa-factory-ticket-t331-wiki-")
    try:
        rest_config(root)
        counter = [0]

        def write(text):
            counter[0] += 1
            path = root / f"t331-{counter[0]}.md"
            path.write_bytes(text.encode("utf-8"))
            return path

        def get(text):
            p = cli(root, "get", KEY, "--json", "--ticket-file", str(write(text)))
            return p, (json.loads(p.stdout) if p.returncode == 0 else None)

        def severity(old_text, new_text):
            # the same file name on both sides: a text with no `title:` takes the file's stem as its title (the
            # story's two snapshots are one name in two places), so two names would be a `title` change of their own
            (root / "old").mkdir(exist_ok=True)
            (root / "new").mkdir(exist_ok=True)
            old_path, new_path = root / "old" / "ticket.md", root / "new" / "ticket.md"
            old_path.write_bytes(old_text.encode("utf-8"))
            new_path.write_bytes(new_text.encode("utf-8"))
            p = cli(root, "diff", "--old", str(old_path), "--new", str(new_path), "--json")
            return json.loads(p.stdout)

        markdown = (WIKI_TICKET.replace("h2. ", "## ").replace("h3. ", "### ").replace("\n* ", "\n- ")
                    .replace("Tagged items", "# Tagged items", 1))
        p, wiki = get(WIKI_TICKET)
        p2, md = get(markdown)
        check_eq("t-331 (a): `h2. Comments` is the comments section: the two comments are read (it was [])",
                 (p.returncode, wiki["comments"]), (0, WIKI_COMMENTS))
        check_eq("t-331 (a) control: the markdown twin reads the same comments", (p2.returncode, md["comments"]), (0, WIKI_COMMENTS))
        check_eq("t-331 (a): read as wiki, and the criteria of the wiki are still read (`h3.` ends them)",
                 (wiki["provenance"]["markup"], wiki["acceptance_criteria"]), ("wiki", ["one", "two"]))
        check_eq("t-331 (a): a text read in ONE form carries no `limitations` key", ("limitations" in wiki["provenance"], "limitations" in md["provenance"]), (False, False))
        # {code}: a heading-looking line inside a block is never a section, and is not cut out of the description
        check("t-331 (a): `{code}` is never split: the ghost comment inside the block is no comment, and the block stays in the description",
              all(c["author"] != "ghost" for c in wiki["comments"]) and "inside a code block" in TA.without_comments_section(wiki["description"]))
        check_eq("t-331 (a): and the real comments are what the description loses",
                 ("first" in TA.without_comments_section(wiki["description"]), "Acceptance Criteria" in TA.without_comments_section(wiki["description"])),
                 (False, True))
        for label, text in (("a one-line pair", "x\n\nh2. Comments\n{code}h2. Hidden{code} - **a** (d): b\n"),
                            ("a `{noformat}` block", "x\n\nh2. Comments\n{noformat}\nh2. Hidden\n{noformat}\n- **a** (d): b\n"),
                            ("a block that never closes", "x\n\nh2. Comments\n- **a** (d): b\n{code}\nh2. Hidden\n- **z** (d): not read\n")):
            names = [h[1] for h in TA.scan_sections(text).heads]
            check_eq(f"t-331 (a) {{code}} edge ({label}): `Hidden` is no section", "hidden" in names, False)
        # diff: a comment alone is `context` in the wiki form as in the markdown one (it diffed as `requirements`)
        for label, base, new in (("wiki", WIKI_TICKET, WIKI_TICKET + NEW_COMMENT), ("markdown", markdown, markdown + NEW_COMMENT)):
            moved = severity(base, new)
            check_eq(f"t-331 (a) diff {label}: a new comment alone -> context, `comments` only, one added",
                     (moved["severity"], moved["changed"], len(moved["detail"].get("comments", {}).get("added", []))),
                     ("context", ["comments"], 1))
        edited = severity(WIKI_TICKET, WIKI_TICKET.replace("* two", "* two, and more") + NEW_COMMENT)
        check_eq("t-331 (a) diff wiki (negative control): an edited criterion beside the comment is still `requirements`",
                 (edited["severity"], "acceptance_criteria" in edited["changed"]), ("requirements", True))
        # zero comments: `h2. Comments` with nothing under it -> [] and no diff against the text without the section
        bare = WIKI_TICKET[:WIKI_TICKET.index("h2. Comments\n- **po**")]
        empty = bare + "h2. Comments\n"
        p, snap = get(empty)
        check_eq("t-331 (a): an `h2. Comments` with zero comments -> []", (p.returncode, snap["comments"]), (0, []))
        same = severity(bare, empty)
        check_eq("t-331 (a): and it is no diff against the same text without the section", (same["severity"], same["changed"]), ("none", []))
        # t-335 B1 (critic t-334): the text is read in the markup `detect_markup` found, and in that one only. The old
        # rule ("the first heading of either form fixes the form") read a Jira wiki paste whose nested list `## sub-step`
        # stands before the first `h2.` as MARKDOWN: comments [], a false "both headings" limitation on stderr and in
        # provenance, and an added comment diffed as `requirements`.
        nested = ("Tagged items\n\n# step one\n## sub-step a\n## sub-step b\n# step two\n\n"
                  "h2. Description\nAs a warehouse operator I want tags.\n\n"
                  "h2. Acceptance Criteria\n* one\n* two\n\n"
                  "h2. Comments\n* *po* (2026-09-12): first\n* *dev* (2026-09-13): second\n")
        p, snap = get(nested)
        check_eq("t-335 B1: a wiki paste with a nested `##` list before its first `h2.` -> the comments are found (it was [])",
                 (p.returncode, [c["text"] for c in snap["comments"]], snap["provenance"]["markup"]), (0, ["first", "second"], "wiki"))
        check_eq("t-335 B1: ...with NO limitation, in provenance or on stderr (it printed a false 'both headings' note)",
                 ("limitations" in snap["provenance"], "note:" in p.stderr, "both" in p.stderr), (False, False, False))
        moved = severity(nested, nested + "* *qa* (2026-09-14): third\n")
        check_eq("t-335 B1: ...and an added comment diffs as `context`, comments only, one added (it was `requirements`)",
                 (moved["severity"], moved["changed"], len(moved["detail"].get("comments", {}).get("added", []))), ("context", ["comments"], 1))
        check_eq("t-335 B1: scan_sections reads the nested paste in wiki, only `h2.` are its heads",
                 (TA.scan_sections(nested).form, [name for _i, name in TA.scan_sections(nested).heads]),
                 ("wiki", ["description", "acceptance criteria", "comments"]))
        # the other form's headings are plain text of the section they stand in, never a boundary - in BOTH directions
        mixed_md = "T\n\n## Comments\n- **po** (d): a\n\nh2. Notes\n- **dev** (d): b\n"
        p, snap = get(mixed_md)
        check_eq("t-335 B1: a text with any `h2.` line is wiki: a `## Comments` there is a nested item, not a section, and "
                 "nothing is said about it (the detector's own rule, `detect_markup`)",
                 (snap["provenance"]["markup"], [c["text"] for c in snap["comments"]], "limitations" in snap["provenance"], "note:" in p.stderr),
                 ("wiki", [], False, False))
        mixed_wiki = "T\n\nh2. Comments\n- **po** (d): a\n\n## Notes\n- **dev** (d): b\n"
        p, snap = get(mixed_wiki)
        check_eq("t-335 B1: `h2. Comments` then a `## Notes` item: the `##` line is no boundary, so BOTH comment lines are read",
                 ([c["text"] for c in snap["comments"]], "limitations" in snap["provenance"]), (["a", "b"], False))
        check_eq("t-335 B1: markdown reads `##` only: `h2.` cannot occur there (a text with one is wiki), `###` and `h1.` are nothing",
                 (TA.scan_sections("## Comments\n- **a** (d): b").form, TA.scan_sections("## Comments\n- **a** (d): b", "markdown").heads,
                  TA.scan_sections("h2. Comments\n- **a** (d): b", "markdown").heads, TA.scan_sections("## Comments\n- **a** (d): b", "wiki").heads),
                 ("markdown", [(0, "comments")], [], []))
        check_eq("t-335 B1 edge: `{code}` / `{noformat}` stay unsplit in the nested paste too (a ghost `h2.` inside a block)",
                 [name for _i, name in TA.scan_sections("# a\n## b\nh2. Comments\n{code}\nh2. Ghost\n{code}\n").heads], ["comments"])
        check_eq("t-335 B1 edge: a text with no heading of either form -> no sections, no form, as today",
                 (TA.scan_sections("plain\n\nlines").form, TA.scan_sections("plain\n\nlines").heads,
                  TA.scan_sections("plain\n\nlines").sections, TA.scan_sections("").sections), (None, [], {}, {}))
        # B-n1: the wiki comment line form, and diff drops ONLY the lines that parsed as comments
        check_eq("t-335 B-n1: a wiki comment line `* *author* (date): text` is a comment (also `#` and `-` bullets)",
                 TA.parse_comments("* *Dave* (2026-10-01): hi\n# *Eve* (2026-10-02): yo\n- *Fay* (d): ok\n"),
                 [{"author": "Dave", "date": "2026-10-01", "text": "hi"}, {"author": "Eve", "date": "2026-10-02", "text": "yo"},
                  {"author": "Fay", "date": "d", "text": "ok"}])
        check_eq("t-335 B-n1: ...and `**bold**` (the markdown form under a `*` bullet) and a line with no text are not",
                 TA.parse_comments("* **Dave** (d): markdown bold\n* *Dave* (d):\n* *Dave* (d):   \n* plain item\n"), [])
        only = "x\n\nh2. Comments\n* *Dave* (2026-10-01): hi\n"
        check_eq("t-335 B-n1: diff of a wiki-form comment line -> context (it was `none`: the comment was read as nothing and the "
                 "section dropped whole)", (lambda m: (m["severity"], m["changed"]))(severity("x\n\nh2. Comments\n", only)),
                 ("context", ["comments"]))
        kept = TA.without_comments_section("x\n\nh2. Comments\n* *Dave* (d): hi\n\nsome pasted requirement line\n- **a** (d): b\n")
        check_eq("t-335 B-n1: a Comments section with an unparsed line keeps that line as description for `diff`",
                 kept, "x\n\nsome pasted requirement line")
        moved = severity("x\n\nh2. Comments\n* *Dave* (d): hi\n", "x\n\nh2. Comments\n* *Dave* (d): hi\nan acceptance criterion pasted here\n")
        check_eq("t-335 B-n1: ...so a change of that line is a `requirements` change, not lost", moved["severity"], "requirements")
        check_eq("t-335 B-n1 control: a section of comment lines only still leaves nothing (the old behaviour for those)",
                 TA.without_comments_section("x\n\nh2. Comments\n* *Dave* (d): hi\n\n- **a** (d): b\n"), "x")
        check_eq("t-331 (a): `h1.`, `h3.` and `###` are not section headings",
                 [TA.scan_sections(t).heads for t in ("h3. Comments\n- **a** (d): b", "### Comments\n- **a** (d): b", "h1. Comments")], [[], [], []])
        check_eq("t-331 (a): `h2. *Comments*:` (bold, colon) is the same section by the same reader the criteria use",
                 [name for _i, name in TA.scan_sections("h2. *Comments*:\n- **a** (d): b").heads], ["comments"])
        check_eq("t-331 (a) edge: no heading at all -> no sections, the text comes back stripped (t-335: and no `limitation` is made any more)",
                 (TA.scan_sections("just text").heads, hasattr(TA.scan_sections("just text"), "limitation"), TA.without_comments_section("  just text \n")), ([], False, "just text"))
        check_eq("t-331 (a) edge: CRLF and a magnitude (4000 comments) read the same",
                 (len(TA.parse_comments(TA.scan_sections("h2. Comments\r\n" + "".join(f"- **a** (d): c{n}\r\n" for n in range(4000))).sections["comments"])),
                  TA.scan_sections("h2. Comments\r\n- **a** (d): b\r\n").sections), (4000, {"comments": "- **a** (d): b"}))
        # the number the person-vs-tracker comparison reads: with the comments read, a wiki paste and the tracker agree
        p, wiki = get(WIKI_TICKET)
        rest ={"title": wiki["title"], "parent": wiki["parent"], "acceptance_criteria": wiki["acceptance_criteria"],
                "comments": [dict(c, id=str(n)) for n, c in enumerate(WIKI_COMMENTS)]}
        compared = TL.compare_person_vs_rest(wiki, rest)
        check_eq("t-331 (a): compare_person_vs_rest on a wiki paste and the tracker's twin: the comment count agrees (2 = 2)",
                 [d for d in compared["disagreements"] if d["field"] == "comments"], [])
    finally:
        cleanup(root)


def t331_owners_and_error_objects() -> None:
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-t331-owners-")
    real_client, saved_table = TA.client_from_config, TL.FIELDS_TABLE_PATH
    saved_lib = {name: getattr(TA, name) for name in ("collect_jira_source", "peek_jira_source", "refresh_relevant_sources",
                                                        "probe_jira_direct")}
    try:
        # --- the project's own settings are `config`, never `tracker` (and say nothing of a retry) ---
        # (the agent / skill read route, `require_direct_read`, is NOT here: it keeps owner `tracker` until the driver's
        # K5 text for it moves - see the report; test_story_run_s0 K5 pins that question's words)
        for label, adapter in (("no adapter", {}), ("an unknown kind", {"kind": "carrier-pigeon"})):
            write_config(root, adapter)
            p = cli(root, "get", KEY, "--json")
            obj = one_json_object(p.stdout)
            error_shape(f"{label} (get)", obj, "config")
            check_eq(f"t-331 (b) {label}: exit 3 as before, the sentence on stderr, and no `retry` in it",
                     (p.returncode, " ".join(p.stderr.split()) == obj["message"], "retry" in obj["message"].lower()), (3, True, False))
        write_config(root, {})
        error_shape("no adapter (children)", one_json_object(cli(root, "children", KEY, "--json").stdout), "config")
        # unsupported auth_type: refused before any request, owner config, the sentence names the key, the value, the allowed
        for auth_type, env_set in (("digest", True), ("digest", False)):
            if not env_set:
                os.environ.pop("QA_JIRA_API_TOKEN")
            rest_config(root)
            cfg_path = root / "qa-factory" / "config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["adapters"]["ticket"]["direct_api"]["auth_type"] = auth_type
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            t = story_routes()
            with_transport(t)
            p = cli(root, "get", KEY, "--json")
            obj = one_json_object(p.stdout)
            error_shape(f"an unsupported auth_type, token variable {'set' if env_set else 'NOT set'}", obj, "config")
            check_eq("t-331 (b): exit 3, no request, the key + the value + the allowed types + the door are named, no `retry`",
                     (p.returncode, t.log, "adapters.ticket.direct_api.auth_type" in obj["message"], "'digest'" in obj["message"],
                      "basic_token, bearer" in obj["message"], "/qa-factory:qa-onboarding" in obj["message"], "retry" in obj["message"].lower()),
                     (3, [], True, True, True, True, False))
        os.environ["QA_JIRA_API_TOKEN"] = "test-only-token"
        # the list in the sentence is the client's own: each named type is accepted by the client, the next one is not
        for auth_type in TA.DIRECT_API_AUTH_TYPES:
            client = SI.JiraClient(BASE, "QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN", auth_type=auth_type)
            try:
                TA.refuse_unsupported_auth_type(client)
                accepted = True
            except SystemExit:
                accepted = False
            check_eq(f"t-331 (b): `{auth_type}` is a type the client sends (TA.DIRECT_API_AUTH_TYPES = its own)", accepted, True)
        try:
            with redirect_stderr(io.StringIO()):
                TA.refuse_unsupported_auth_type(SI.JiraClient(BASE, "QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN", auth_type="digest"))
            refused = ""
        except TA.Fail as exc:
            refused = exc.owner
        check_eq("t-331 (b): a type outside the list is refused as `config`", refused, "config")
        rest_config(root)
        t = story_routes()
        with_transport(t)
        check_eq("t-331 (b) positive control: a usable direct_api still reads the ticket", cli(root, "get", KEY, "--json").returncode, 0)

        # --- the person's own file: missing or empty -> `person`, exit 1 as before, one object ---
        missing = root / "no-such-paste.md"
        p = cli(root, "get", KEY, "--json", "--ticket-file", str(missing))
        obj = one_json_object(p.stdout)
        error_shape("a missing paste file (get)", obj, "person")
        check_eq("t-331 (b): exit 1, the path named in the sentence and (t-335 B-n4) in `file`, which the person's owner carries too",
                 (p.returncode, str(missing) in obj["message"], obj.get("file") == str(missing)), (1, True, True))
        p = cli(root, "diff", "--old", str(missing), "--new", str(missing), "--json")
        error_shape("a missing file (diff, SystemExit)", one_json_object(p.stdout), "factory")
        check_eq("t-335 B-n2: diff on a missing snapshot: owner `factory` (the factory writes those files), the file named, "
                 "never `person`", (one_json_object(p.stdout)["owner"], one_json_object(p.stdout)["file"]), ("factory", str(missing)))
        check_eq("t-331 (b): diff on a missing file: exit 1, stdout holds the object and nothing else", (p.returncode, bool(one_json_object(p.stdout))), (1, True))
        for side, args in (("old", ("--old", str(missing), "--new", str(root / "t331-ok-new.md"))),
                           ("new", ("--old", str(root / "t331-ok-new.md"), "--new", str(missing)))):
            (root / "t331-ok-new.md").write_text("# T\n\nbody\n", encoding="utf-8")
            both = one_json_object(cli(root, "diff", *args, "--json").stdout)
            check_in(f"t-335 B-n2: diff with only the {side} side missing says which one", f"the {side} ticket snapshot", both["message"])
        plain = cli(root, "diff", "--old", str(missing), "--new", str(missing))
        check_eq("t-331 (b): without --json: the same exit, the sentence on stderr, stdout empty", (plain.returncode, plain.stdout, "not found" in plain.stderr), (1, "", True))
        usage = cli(root, "diff", "--old", str(missing), "--json")
        check_eq("t-335 B-n3: a usage error (exit 2) under --json prints no object: the docstring says so (usage is not a refusal)",
                 (usage.returncode, usage.stdout.strip(), "usage:" in usage.stderr), (2, "", True))
        check_in("t-335 B-n3: ...the module's own text names the exit codes 1, 3, 4, 5 and says usage prints none",
                 "Exit 2 - usage", TA.__doc__)

        # --- FR-14: every verb, every kind of failure, ONE shape ---
        paste = root / "t331-ok.md"
        paste.write_text("# T\n\nbody\n", encoding="utf-8")
        bad = root / "jira-fields.json"
        bad.write_text(json.dumps(dict(TL.load_fields_table(), standard=[])), encoding="utf-8")
        TL.FIELDS_TABLE_PATH = bad
        try:
            p = cli(root, "diff", "--old", str(paste), "--new", str(paste), "--json")
        finally:
            TL.FIELDS_TABLE_PATH = saved_table
        obj = one_json_object(p.stdout)
        error_shape("a corrupted table (diff, TableError)", obj, "factory")
        check_eq("t-331 (b): diff on a corrupted table: exit 4, the file named", (p.returncode, obj["file"]), (4, "jira-fields.json"))
        inventory = root / "inv.json"
        verbs = (("collect", ("collect", KEY, "--output", str(inventory), "--relation", "task"), "collect_jira_source"),
                 ("peek", ("peek", KEY, "--output", str(inventory)), "peek_jira_source"),
                 ("refresh", ("refresh", "--output", str(inventory)), "refresh_relevant_sources"),
                 ("probe", ("probe", "--output", str(root / "receipt.json"), KEY), "probe_jira_direct"))

        def raises(exc):
            def _raise(*_a, **_k):
                raise exc
            return _raise

        lost = SI.AuthLost("the tracker no longer accepts QA_JIRA_API_TOKEN", status=401, door="QA_JIRA_API_TOKEN")
        broken = TL.TableError("jira-fields.json cannot be read: expected the table at the package")
        # B-408 (AK6): an answer the tracker is not shown to have written is exit 5 as well, with its own owner word
        blocked = SI.Intercepted("the tracker could not be read while reading the ticket: HTTP 403, an HTML page; the token was not judged",
                                 status=403, door="QA_JIRA_API_TOKEN")
        for verb, args, name in verbs:
            for what, exc, owner, code in (("a lost login", lost, "auth", 5), ("a corrupted table", broken, "factory", 4),
                                           ("an intercepted answer", blocked, "intermediary", 5)):
                setattr(TA, name, raises(exc))
                p = cli(root, *args, "--json")
                obj = one_json_object(p.stdout)
                error_shape(f"{what} ({verb})", obj, owner)
                check_eq(f"t-331 (b) {verb}, {what}: exit {code} as before, stderr keeps the sentence", (p.returncode, p.stderr.strip() != ""), (code, True))
                plain = cli(root, *args)
                check_eq(f"t-331 (b) {verb}, {what}: WITHOUT --json: the same exit, stdout empty", (plain.returncode, plain.stdout), (code, ""))
            setattr(TA, name, saved_lib[name])
        # a refusal raised by `fail()` inside a verb ("requires a Jira ticket adapter") is the same object. Its OWNER is
        # not pinned here: it still carries the exit code's default (`tracker`), a config fault the class sweep of this
        # task left queued (report) - only the shape is the contract of this test.
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})
        for verb, args in (("collect", ("collect", KEY, "--output", str(inventory), "--relation", "task")),
                           ("peek", ("peek", KEY, "--output", str(inventory))), ("refresh", ("refresh", "--output", str(inventory)))):
            obj = one_json_object(cli(root, *args, "--json").stdout)
            error_shape(f"a non-Jira adapter ({verb}, SystemExit)", obj, (obj or {}).get("owner"))
    finally:
        TA.client_from_config, TL.FIELDS_TABLE_PATH = real_client, saved_table
        for name, value in saved_lib.items():
            setattr(TA, name, value)
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def a_foreign_404_is_never_not_found() -> None:
    """B-408 (critic t-524 F3): a 404 whose answer the tracker is not shown to have written (a protection layer's page, on a
    ticket whose prefix is not in `project_keys`, so the auth gate never saw it) must not be booked as "the key does not
    exist"; it is the exit-3 "could not be read". A plain 404 stays exit 1."""
    import http_client
    page = b"<html><head><title>Attention Required! | Cloudflare</title></head></html>"
    pairs = [("Server", "cloudflare"), ("CF-RAY", "8a1b"), ("Content-Type", "text/html")]
    answer = http_client.Answer(404, http_client.Headers(pairs), page, False, False, None, "https://jira.example.test/x", 0.0,
                                http_client.classify(404, pairs, page, service="jira"))
    seen = []
    for label, exc, want_code, want_owner in (
            ("a foreign 404 page", SI.FetchError(404, "HTTP 404: an HTML page", answer=answer), TA.EXIT_NOT_CONFIGURED, "tracker"),
            ("a 404 with no answer read (control: today's reading)", SI.FetchError(404, "HTTP 404"), TA.EXIT_NOT_FOUND, "tracker"),
            ("the tracker's own empty 404 (control)", SI.FetchError(404, "HTTP 404", answer=http_client.Answer(
                404, http_client.Headers(), b"", False, False, None, "u", 0.0, http_client.classify(404, [], b"", service="jira"))),
             TA.EXIT_NOT_FOUND, "tracker")):
        with redirect_stderr(io.StringIO()):
            code = TA.refuse_fetch(exc, "APP-7", seen.append)
        check_eq(f"B-408 F3: {label} -> exit {want_code}", code, want_code)
        check_eq(f"B-408 F3: {label} -> the object's owner", seen[-1]["owner"], want_owner)
        check_eq(f"B-408 F3: {label} says 'does not exist' only when it IS a not-found",
                 "does not exist" in seen[-1]["message"], want_code == TA.EXIT_NOT_FOUND)


def main() -> None:
    # --- built-in selftest -----------------------------------------------------------------
    # CLI CONTRACT, kept as a real child: --selftest is the script's own promise, proven only
    # by actually running the script.
    p = run_script("ticket_adapter.py", "--selftest")
    check_eq("--selftest: exit 0", p.returncode, 0)
    check_in("--selftest: reports PASSED", "PASSED", p.stdout)

    # --- file adapter via a project config (the done-check's own invocation) ---------------
    root = temp_project("qa-factory-ticket-adapter-")
    try:
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})

        # CLI CONTRACT, kept as a real child: argv parsing and a JSON-only stdout, through a
        # real process boundary — cli() below proves the same decision, not the same process.
        p = run_adapter(root, "get", "QA-1", "--json")
        check_eq("get QA-1 --json: exit 0", p.returncode, 0)
        data = json.loads(p.stdout)
        check_eq("get: key", data.get("key"), "QA-1")
        check_eq("get: type", data.get("type"), "Story")
        check_eq("get: status", data.get("status"), "In Review")
        check_eq("get: 5 acceptance criteria", len(data.get("acceptance_criteria", [])), 5)
        check_eq("get: 2 comments", len(data.get("comments", [])), 2)
        check_eq("get: links.merge_request", data.get("links", {}).get("merge_request"), "feature/qa-1")
        for key in ("key", "type", "status", "title", "description", "acceptance_criteria",
                    "comments", "parent", "subtasks", "links"):
            check(f"get: schema key '{key}' present", key in data)

        p = cli(root, "children", "QA-1", "--json")
        check_eq("children QA-1: exit 0", p.returncode, 0)
        children = json.loads(p.stdout)
        check_eq("children: QA-1 has no subtasks in the fixture", children, [])

        # a ticket that does not exist on disk -> exit 1, not a crash
        p = cli(root, "get", "QA-999", "--json")
        check_eq("get QA-999 (missing file): exit 1", p.returncode, 1)
        check_in("get QA-999: names the missing path", "not found", p.stderr)

        # 'name' key (the shipped template's own spelling) works too, not just 'kind'
        write_config(root, {"name": "file", "path": str(FIXTURE_TICKETS)})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("get via 'name' key: exit 0", p.returncode, 0)
    finally:
        cleanup(root)

    # --- command-template adapters: mcp_tool-only -> exit 3 with an instruction -------------
    root = temp_project("qa-factory-ticket-adapter-mcp-")
    try:
        write_config(root, {"kind": "jira", "mcp_tool": "jira_get_issue"})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("mcp_tool only: exit 3", p.returncode, 3)
        check_in("mcp_tool only: names the tool", "jira_get_issue", p.stderr)
        check_in("mcp_tool only: tells the role to normalize", "normalize", p.stderr)
    finally:
        cleanup(root)

    # --- command-template adapters: non-JSON output -> exit 3, never a crash ----------------
    root = temp_project("qa-factory-ticket-adapter-badcmd-")
    try:
        echo_cmd = f"{sys.executable} -c \"print('not json')\""
        write_config(root, {"kind": "jira", "command": echo_cmd})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("non-JSON command output: exit 3", p.returncode, 3)
        check_in("non-JSON command output: says so", "not JSON", p.stderr)
    finally:
        cleanup(root)

    # --- no adapter configured at all -> exit 3 ----------------------------------------------
    root = temp_project("qa-factory-ticket-adapter-none-")
    try:
        # CLI CONTRACT, kept as a real child: fail() calls sys.exit(3) directly — this proves
        # it as a real process exit code, not the int a Python-level return would give cli().
        p = run_adapter(root, "get", "QA-1", "--json")
        check_eq("unconfigured: exit 3", p.returncode, 3)
        check_in("unconfigured: points at onboarding", "onboarding", p.stderr)
    finally:
        cleanup(root)

    # --- --ticket-file: the flag every doc promised and nothing implemented ------------------
    root = temp_project("qa-factory-ticket-adapter-file-flag-")
    try:
        # a config pointing somewhere useless: --ticket-file must ignore it entirely
        write_config(root, {"kind": "file", "path": "no/such/dir"})
        snapshot = FIXTURE_TICKETS / "QA-1.md"

        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(snapshot))
        check_eq("--ticket-file: exit 0 despite a broken adapter path", p.returncode, 0)
        data = json.loads(p.stdout)
        check_eq("--ticket-file: parsed the named file", data.get("key"), "QA-1")
        check_eq("--ticket-file: 5 acceptance criteria", len(data.get("acceptance_criteria", [])), 5)

        p = cli(root, "children", "QA-1", "--json", "--ticket-file", str(snapshot))
        check_eq("--ticket-file works for children too", p.returncode, 0)

        p = cli(root, "get", "QA-1", "--ticket-file", str(root / "nope.md"))
        check_eq("--ticket-file on a missing file: exit 1", p.returncode, 1)
        check_in("--ticket-file on a missing file: names it", "not found", p.stderr)
    finally:
        cleanup(root)

    # --- diff: whether the ticket moved is a question for code -------------------------------
    root = temp_project("qa-factory-ticket-adapter-diff-")
    try:
        original = FIXTURE_TICKETS / "QA-1.md"
        text = original.read_text(encoding="utf-8")
        moved = root / "moved.md"
        moved.write_text(text.replace("at most 5 tags", "at most 9 tags"), encoding="utf-8")
        commented = root / "commented.md"
        commented.write_text(text + chr(10) + "- **po** (2026-09-14): and one more.", encoding="utf-8")

        p = cli(root, "diff", "--old", str(original), "--new", str(original), "--json")
        check_eq("diff: unchanged exits 0", p.returncode, 0)
        check_eq("diff: unchanged severity none", json.loads(p.stdout)["severity"], "none")

        p = cli(root, "diff", "--old", str(original), "--new", str(moved), "--json")
        result = json.loads(p.stdout)
        check_eq("diff: an edited AC is severity requirements", result["severity"], "requirements")
        check("diff: names the field that moved", "acceptance_criteria" in result["changed"])

        p = cli(root, "diff", "--old", str(original), "--new", str(commented), "--json")
        check_eq("diff: a new comment alone is severity context",
                 json.loads(p.stdout)["severity"], "context")

        p = cli(root, "diff", "--old", str(original))
        check_eq("diff without --new: a usage error, not a crash", p.returncode, 2)
    finally:
        cleanup(root)

    # --- one snapshot, in the form `get --json` prints (t-017 D1, item d) ---------------------
    # The driver writes `work/ticket-snapshot.json` and nothing else; `diff` and `--ticket-file`
    # must read that file, with or without the stderr tail that older snapshots carry, and the
    # two forms of one ticket (markdown by hand, JSON from the direct API) must not differ by
    # the link lists only one of them can hold.
    root = temp_project("qa-factory-ticket-adapter-json-")
    try:
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})
        first = cli(root, "get", "QA-1", "--json")
        check_eq("json snapshot: the file adapter prints JSON", first.returncode, 0)
        snap_a = root / "ticket-snapshot.json"
        snap_a.write_bytes(first.stdout.encode("utf-8"))
        snap_b = root / "ticket-snapshot.prev.json"
        moved = json.loads(first.stdout)
        moved["acceptance_criteria"] = moved["acceptance_criteria"][:-1]
        snap_b.write_text(json.dumps(moved, indent=2), encoding="utf-8")

        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(snap_a))
        check_eq("--ticket-file reads a JSON snapshot: exit 0", p.returncode, 0)
        check_eq("and prints the same ticket back", json.loads(p.stdout), json.loads(first.stdout))

        p = cli(root, "diff", "--old", str(snap_a), "--new", str(snap_a), "--json")
        check_eq("diff of two JSON snapshots, unchanged: severity none",
                 json.loads(p.stdout)["severity"], "none")
        p = cli(root, "diff", "--old", str(snap_a), "--new", str(snap_b), "--json")
        result = json.loads(p.stdout)
        check_eq("diff of two JSON snapshots, one AC dropped: requirements", result["severity"], "requirements")
        check_eq("and it names the dropped criterion", len(result["detail"]["acceptance_criteria"]["removed"]), 1)

        tail = root / "legacy-with-stderr.json"
        tail.write_text(first.stdout + "\nWARN: readiness could not probe vcs\n", encoding="utf-8")
        p = cli(root, "diff", "--old", str(snap_a), "--new", str(tail), "--json")
        check_eq("diff against a snapshot with a stderr tail: severity none",
                 json.loads(p.stdout)["severity"], "none")

        api = json.loads(first.stdout)
        api["links"] = {"merge_request": "feature/qa-1", "branch": None,
                        "issue_links": [], "remote_links": []}
        api_snap = root / "direct-api.json"
        api_snap.write_text(json.dumps(api), encoding="utf-8")
        p = cli(root, "diff", "--old", str(FIXTURE_TICKETS / "QA-1.md"), "--new", str(api_snap), "--json")
        result = json.loads(p.stdout)
        check("markdown against direct-API JSON: no false link change",
              "links" not in result["changed"], str(result["changed"]))
        check_eq("and the same ticket is severity none", result["severity"], "none")
        same_keys = json.loads(first.stdout)
        same_keys["links"]["merge_request"] = "feature/other"
        moved_snap = root / "moved-link.json"
        moved_snap.write_text(json.dumps(same_keys), encoding="utf-8")
        p = cli(root, "diff", "--old", str(snap_a), "--new", str(moved_snap), "--json")
        check("with the same link keys the whole object is compared",
              "links" in json.loads(p.stdout)["changed"])
    finally:
        cleanup(root)

    # --- an agent-reached tracker: no longer a READ route at all ------------------------------
    # The owner's decision of 21.09: an assistant answers one question per dispatch, carries no
    # attachment bytes, and the scout has no Agent tool — so S1 lost sources without saying so.
    # The refusal must send the project to the direct API, never back to a hand-written snapshot.
    root = temp_project("qa-factory-ticket-adapter-agent-")
    try:
        write_config(root, {"name": "jira", "method": "agent", "invoke": "jira-assistant",
                            "status": "configured"})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("agent method: exit 3", p.returncode, 3)
        check_in("agent method: names the agent it refuses", "jira-assistant", p.stderr)
        check_in("agent method: names direct_api as the only read route",
                 "adapters.ticket.direct_api", p.stderr)
        check_in("agent method: names the onboarding command", "qa-onboarding", p.stderr)
        check_in("agent method: keeps the write channel open", "external_writes", p.stderr)
        check("agent method: sends nobody to hand-write a snapshot",
              "ticket-snapshot" not in p.stderr and "--ticket-file" not in p.stderr,
              p.stderr.strip()[:200])

        write_config(root, {"name": "jira", "method": "agent", "status": "configured"})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("agent method with no invoke: exit 3", p.returncode, 3)
        check_in("agent method with no invoke: names the empty key", "<unnamed>", p.stderr)
        check_in("agent method with no invoke: still names direct_api",
                 "adapters.ticket.direct_api", p.stderr)

        # back-compat: a config with only mcp_tool still takes the mcp_tool branch
        write_config(root, {"kind": "jira", "mcp_tool": "jira_get_issue"})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("mcp_tool with no method: still the mcp_tool branch", p.returncode, 3)
        check_in("mcp_tool with no method: still names the tool", "jira_get_issue", p.stderr)
    finally:
        cleanup(root)

    # --- method "agent"/"skill" is a WRITE-channel label; a usable direct_api still --
    # --- reads, whatever method says (test-harness, TP1-15045 on 0.7.8: a full ---------
    # --- direct_api next to method: "agent" was refused as if direct_api were unset) -------
    root = temp_project("qa-factory-ticket-adapter-i71-")
    old_env = {k: os.environ.pop(k, None) for k in ("QAF_I71_USER", "QAF_I71_SECRET")}
    try:
        direct_api = {"base_url": "https://jira.example.invalid", "auth_type": "basic_token",
                      "username_ref": "QAF_I71_USER", "secret_ref": "QAF_I71_SECRET"}
        write_config(root, {"name": "jira", "method": "agent", "invoke": "jira-assistant",
                            "status": "configured", "direct_api": direct_api})
        p = cli(root, "get", "QA-1", "--json")
        # No credentials in this session's environment: still fails, but PAST the read-route
        # guard — the failure is a missing credential, never "record direct_api" again. Since t-287 item 3 that is
        # the LOGIN's exit (5, owner auth) naming the variables, not the tracker's (3).
        check_eq("agent + usable direct_api: no longer refused at the read-route guard (the credential is the login's: exit 5)",
                 p.returncode, 5)
        check("agent + usable direct_api: fails on the credential - it names the variables - not the route",
              "QAF_I71_SECRET" in p.stderr and "QAF_I71_USER" in p.stderr, p.stderr)
        check("agent + usable direct_api: does not repeat the old refusal",
              "no longer supported" not in p.stderr, p.stderr.strip()[:200])

        # method "skill" behaves the same way.
        write_config(root, {"name": "jira", "method": "skill", "invoke": "jira-skill",
                            "status": "configured", "direct_api": direct_api})
        p = cli(root, "get", "QA-1", "--json")
        check("skill + usable direct_api: also reaches the credential check (names the variable)",
              "QAF_I71_SECRET" in p.stderr, p.stderr)

        # an incomplete direct_api (no secret_ref) still refuses at the read-route guard —
        # "usable" means client_from_config would actually accept it.
        write_config(root, {"name": "jira", "method": "agent", "invoke": "jira-assistant",
                            "status": "configured",
                            "direct_api": {"base_url": "https://jira.example.invalid"}})
        p = cli(root, "get", "QA-1", "--json")
        check_eq("agent + incomplete direct_api: still refused", p.returncode, 3)
        check_in("agent + incomplete direct_api: still names direct_api as the fix",
                 "adapters.ticket.direct_api", p.stderr)
    finally:
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v
        cleanup(root)

    # --- --migrate-method: onboarding's one-way fix for an old agent+direct_api config -----
    root = temp_project("qa-factory-ticket-adapter-migrate-")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["adapters"] = {"ticket": {"name": "jira", "method": "agent", "invoke": "jira-assistant",
                                      "status": "configured",
                                      "direct_api": {"base_url": "https://jira.example.invalid",
                                                     "auth_type": "basic_token",
                                                     "username_ref": "QAF_I71_USER",
                                                     "secret_ref": "QAF_I71_SECRET"}}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        # --dry-run: reports the change, writes nothing.
        p = cli(root, "--migrate-method", "--config", str(cfg_path), "--dry-run", "--json")
        check_eq("migrate --dry-run: exit 0", p.returncode, 0)
        result = json.loads(p.stdout)
        check_eq("migrate --dry-run: reports changed", result["changed"], True)
        check_eq("migrate --dry-run: old_method agent", result["old_method"], "agent")
        check_eq("migrate --dry-run: new_method api", result["new_method"], "api")
        on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
        check_eq("migrate --dry-run: method on disk is unchanged",
                 on_disk["adapters"]["ticket"]["method"], "agent")

        # without --dry-run: actually rewrites, and get_ticket now reaches the credential
        # check on the first try (no read-route refusal in between).
        p = cli(root, "--migrate-method", "--config", str(cfg_path), "--json")
        check_eq("migrate: exit 0", p.returncode, 0)
        on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
        check_eq("migrate: method rewritten to api on disk",
                 on_disk["adapters"]["ticket"]["method"], "api")
        check_eq("migrate: invoke is left alone (still a write channel elsewhere)",
                 on_disk["adapters"]["ticket"]["invoke"], "jira-assistant")

        # idempotent: running it again on the migrated config changes nothing.
        p = cli(root, "--migrate-method", "--config", str(cfg_path), "--json")
        result = json.loads(p.stdout)
        check_eq("migrate: re-running on an already-migrated config is a no-op",
                 result["changed"], False)
        check_eq("migrate: re-running reports the current method", result["old_method"], "api")

        # a config with no usable direct_api is left alone too.
        cfg["adapters"] = {"ticket": {"name": "jira", "method": "agent", "invoke": "jira-assistant"}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        p = cli(root, "--migrate-method", "--config", str(cfg_path), "--json")
        result = json.loads(p.stdout)
        check_eq("migrate: no direct_api at all -> no change", result["changed"], False)
        check_eq("migrate: method stays agent", result["old_method"], "agent")
    finally:
        cleanup(root)

    # --- probe never replaces the source inventory (F8, TP1-13797 driver run) ----------
    sys.path.insert(0, str(SCRIPTS))
    import ticket_adapter as ta
    root = temp_project("qa-factory-ticket-probe-")
    try:
        inv = root / "source-inventory.json"
        inv.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        check("probe guard: an inventory file is recognised", ta._holds_inventory(inv))
        check("probe guard: a missing file is not an inventory",
              not ta._holds_inventory(root / "none.json"))
        (root / "receipt.json").write_text('{"capability": "jira_direct_read"}', encoding="utf-8")
        check("probe guard: a probe receipt is not an inventory",
              not ta._holds_inventory(root / "receipt.json"))
    finally:
        cleanup(root)

    rest_route()
    attachment_blobs()
    paste_route()
    owners_of_a_failed_read()
    t287_paste_markup_and_title()
    t287_unusable_direct_api_and_missing_token()
    public_name_of_the_usable_check()
    t331_wiki_sections()
    t331_owners_and_error_objects()
    a_foreign_404_is_never_not_found()
    part_snapshot_file()
    part_normalized_input()
    part_diff_formats()
    part_freshness()
    part_freshness_views()
    part_freshness_refusals()
    part_freshness_pasted()
    part_stale_rule()
    part_freshness_record()
    part_words_file()
    part_gap_kinds()
    part_summary()
    finish("test_ticket_adapter")


# --- the snapshot: JSON is the one canonical form (B-008, B-042) -----------------------------
# TP1-13797: the driver joined the stdout AND stderr of `get --json` into
# `work/ticket-snapshot.md` (invalid JSON the moment the adapter wrote a warning) while the
# scout's brief reads `work/ticket-snapshot.json`: the scout never got the snapshot. The file is
# now written by the adapter itself, from the dict it prints, so no caller has a stream to join.

def load(path: Path):
    """The JSON in a file, or None when there is no such file (a missing file is a red check,
    not a crash that hides every check after it)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rb(path: Path) -> bytes:
    return path.read_bytes() if path.is_file() else b"<no such file>"


def journal_lines(root: Path) -> list:
    # `RP.record`: the journal lives in `records/` since the layout moved it from `state/`, and the one answer for a
    # reader is the function the writer (log_append) uses too.
    path = RP.record(root, "journal.jsonl")
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rich_ticket(key: str = "QA-7") -> dict:
    """What a direct tracker read returns: the schema plus the context fields the Markdown form
    cannot carry (stage_compare.py s0 counts issue_links, remote_links, attachments, status)."""
    return {"key": key, "type": "Story", "status": "In Review",
            "title": "Checkout café coupon",
            "description": "Apply a coupon at checkout.\n\nA second paragraph.",
            "acceptance_criteria": ["A coupon takes 10% off", "An expired coupon is refused"],
            "comments": [{"author": "po", "date": "2026-09-10", "text": "Keep it simple."}],
            "parent": "QA-1", "subtasks": [{"key": "QA-8", "status": "Open"}],
            "links": {"merge_request": "https://git.example.invalid/x/-/merge_requests/5",
                      "branch": None,
                      "issue_links": [{"relation": "blocks", "key": "QA-3", "summary": "Cart",
                                       "status": "Open"}],
                      "remote_links": [{"title": "Spec", "url": "https://wiki.example.invalid/spec"}]},
            "attachments": [{"id": "10001", "filename": "mock.png", "size": 12}],
            "revision": "2026-09-14T10:00:00.000+0000",
            "provenance": {"source": "jira_direct_api", "fetched_at": "2026-09-14T10:22:00+00:00"}}


def put_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def part_snapshot_file() -> None:
    root = temp_project("qa-factory-ticket-adapter-output-")
    try:
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})
        fixture = FIXTURE_TICKETS / "QA-1.md"
        snap = root / "work" / "deep" / "ticket-snapshot.json"

        plain = cli(root, "get", "QA-1", "--json", "--ticket-file", str(fixture))
        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(fixture), "--output", str(snap))
        check_eq("get --output: exit 0", p.returncode, 0)
        check("get --output: creates the file and its parent directories", snap.is_file())
        check_eq("get --output: stdout is exactly what --json prints without it (FR-14)",
                 p.stdout, plain.stdout)
        check_eq("get --output: the file is the dict --json prints, key for key",
                 load(snap), json.loads(p.stdout))
        text = snap.read_text(encoding="utf-8") if snap.is_file() else ""
        check("get --output: UTF-8 JSON with indent=2", text.startswith("{\n  \""))
        # L3: ONE format function. The file is `snapshot_bytes` of the dict `--json` prints - UTF-8, LF, a final
        # newline - on every platform (the text layer of `atomic_json` would write CRLF on Windows).
        check_eq("get --output: the file's bytes are exactly snapshot_bytes of the printed dict",
                 rb(snap), TA.snapshot_bytes(json.loads(p.stdout)))
        check("get --output: no CR in the file, and it ends with one LF",
              b"\r" not in rb(snap) and rb(snap).endswith(b"}\n") and not rb(snap).endswith(b"\n\n"))
        check_eq("get --json: what is printed is that very text (snapshot_text)", p.stdout,
                 TA.snapshot_text(json.loads(p.stdout)))
        # A text file written through the wrong channel is the defect this closes: the file
        # parses as ONE JSON document and nothing else.
        check("get --output: no stream noise after the document", text.rstrip().endswith("}"))

        # CLI CONTRACT, kept as a real child: stdout and `--output` are the same BYTES through a real process
        # boundary - UTF-8 and LF, on Windows too (a text-mode stdout would write CRLF and the console's code page).
        # `run_script` decodes with universal newlines, so it could not see a CR; this reads the raw bytes.
        cafe = root / "cafe.md"
        cafe.write_text("# Café coupon\n\nA body.\n", encoding="utf-8")
        child_out = root / "work" / "child.json"
        child_env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "ticket_adapter.py"), "get", "QA-9", "--json",
                               "--ticket-file", str(cafe), "--output", str(child_out)],
                              capture_output=True, env=child_env, timeout=120)
        check_eq("a real child: get --json --output exits 0", done.returncode, 0)
        check_eq("a real child: stdout bytes are the file's bytes", done.stdout, rb(child_out))
        check("a real child: no CR anywhere, and the non-ASCII title is UTF-8",
              b"\r" not in done.stdout and "Café coupon".encode("utf-8") in done.stdout)

        p = cli(root, "diff", "--old", str(snap), "--new", str(snap), "--json")
        check_eq("diff of the snapshot against itself: exit 0", p.returncode, 0)
        check_eq("diff of the snapshot against itself: severity none",
                 json.loads(p.stdout)["severity"] if p.stdout.strip() else None, "none")

        # The file equals the printed dict INCLUDING the fields stage_compare.py s0 counts: this
        # is the mechanical stand-in for that comparison (its reference tree is not here).
        rich = rich_ticket()
        real_get = TA.get_ticket
        # (ticket, cfg, raw_dir, say=...): `main` passes the raw folder and the note sink of the REST read
        TA.get_ticket = lambda ticket, cfg, *args, **kwargs: dict(rich)
        try:
            out = root / "work" / "rich.json"
            p = cli(root, "get", "QA-7", "--json", "--output", str(out))
        finally:
            TA.get_ticket = real_get
        check_eq("rich read: exit 0", p.returncode, 0)
        printed, written = json.loads(p.stdout), load(out)
        check_eq("rich read: the file equals the printed dict", written, printed)
        for key in ("revision", "attachments", "status", "provenance"):
            check(f"rich read: `{key}` is in the file", written is not None and key in written)
        for key in ("issue_links", "remote_links", "merge_request"):
            check(f"rich read: links.{key} is in the file",
                  written is not None and key in (written.get("links") or {}))
        check_eq("rich read: the counts a reference comparison reads survive",
                 (len((written or {}).get("attachments") or []),
                  len(((written or {}).get("links") or {}).get("issue_links") or []),
                  len(((written or {}).get("links") or {}).get("remote_links") or []),
                  (written or {}).get("status")),
                 (1, 1, 1, "In Review"))
        check("rich read: non-ASCII text is kept as text, not escaped",
              out.is_file() and "café" in out.read_text(encoding="utf-8"))

        # Nothing is invented: a source with no revision and no provenance gets neither.
        bare = {k: v for k, v in rich.items() if k not in ("revision", "provenance", "attachments")}
        TA.get_ticket = lambda ticket, cfg, *args, **kwargs: dict(bare)
        try:
            out2 = root / "work" / "bare.json"
            cli(root, "get", "QA-7", "--json", "--output", str(out2))
        finally:
            TA.get_ticket = real_get
        written = load(out2) or {}
        check("bare read: no revision is made up", "revision" not in written and out2.is_file())
        check("bare read: no provenance is made up", "provenance" not in written)

        # A failing read creates nothing and touches nothing.
        missing = root / "work" / "never.json"
        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(root / "nope.md"),
                "--output", str(missing))
        check_eq("a missing ticket: exit 1", p.returncode, 1)
        check("a missing ticket: no file is created", not missing.exists())
        keep = root / "work" / "keep.json"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text('{"sentinel": 1}', encoding="utf-8")
        before = keep.read_bytes()
        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(root / "nope.md"),
                "--output", str(keep))
        check_eq("a failed read over an existing file: exit 1", p.returncode, 1)
        check_eq("a failed read leaves the existing file byte for byte", keep.read_bytes(), before)
        write_config(root, {})
        p = cli(root, "get", "QA-1", "--json", "--output", str(keep))
        check_eq("an unconfigured adapter: exit 3", p.returncode, 3)
        check_eq("an unconfigured adapter leaves the existing file byte for byte",
                 keep.read_bytes(), before)

        # `children` has no snapshot: refused, and it writes nothing.
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})
        kids = root / "work" / "kids.json"
        p = cli(root, "children", "QA-1", "--json", "--output", str(kids))
        check_eq("children --output is a usage error: exit 2", p.returncode, 2)
        check("children --output writes nothing", not kids.exists())
        check_in("children --output says what to use instead", "get", p.stderr)

        # The bare usage line names every verb of the ticket file and every flag the code accepts (FR-37: the text
        # is the code's own), and no flag it does not (the `.prev` copy nothing ever wrote).
        bare = cli(root, "get")
        check_eq("get without a ticket: a usage error, exit 2", bare.returncode, 2)
        for word in ("get", "children", "diff", "freshness", "--json", "--ticket-file", "--raw-dir", "--output",
                     "--old", "--new", "--task-root", "--adopt", "--decline", "--words-file"):
            check_in(f"the bare usage line names {word}", word, bare.stderr)
        check_not_in("and it names no flag the code does not accept", "--prev", bare.stderr)
    finally:
        cleanup(root)


def part_normalized_input() -> None:
    root = temp_project("qa-factory-ticket-adapter-json-in-")
    try:
        base = {"key": "QA-13", "type": "Bug", "status": "Ready for Review",
                "title": "Inverted threshold", "description": "h2. Summary\n\nIt is inverted."}

        def get(name: str, text: str, ticket: str = "QA-13"):
            path = root / name
            path.write_text(text, encoding="utf-8")
            return cli(root, "get", ticket, "--json", "--ticket-file", str(path))

        # Stories in flight hold JSON inside a `.md` file (TP1-13877): detected by CONTENT.
        p = get("QA-13.md", json.dumps(dict(base, acceptance_criteria=["one"], comments=[],
                                            parent=None, subtasks=[], links={}), indent=2))
        check_eq("JSON stored in a .md file: exit 0", p.returncode, 0)
        data = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
        check_eq("JSON stored in a .md file: read as JSON, not as Markdown",
                 (data.get("title"), data.get("status"), data.get("acceptance_criteria")),
                 ("Inverted threshold", "Ready for Review", ["one"]))

        p = get("bom.md", "\ufeff\n  \n" + json.dumps(base))
        check_eq("a BOM and blank lines before the brace: exit 0", p.returncode, 0)
        # FR-29: the BOM is written as an escape in the sources, never as the invisible character.
        bom_sources = {source: (SCRIPTS / source).read_text(encoding="utf-8") for source in ("ticket_adapter.py", "tests/test_ticket_adapter.py")}
        bom_sources.update({f"{path.name} (driver set)": text for path, text in driver_sources()})
        for source, text in bom_sources.items():
            check_eq(f"no literal U+FEFF inside {source}", chr(0xFEFF) in text, False)

        # ONE reader of a ticket file (t-428, 0.8.1's `parse_ticket_json` / `read_ticket_file`): a key the schema
        # names and the file lacks is accepted with the markdown parser's default - links included, which is the
        # markdown shape's two keys - and what the file does not carry is not made up.
        p = get("minimal.json", json.dumps(base))
        data = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
        check_eq("missing list/dict keys get the reader's defaults",
                 (data.get("acceptance_criteria"), data.get("comments"), data.get("subtasks"),
                  data.get("links"), data.get("parent")),
                 ([], [], [], {"merge_request": None, "branch": None}, None))
        check("a missing revision or provenance is not made up",
              "revision" not in data and "provenance" not in data)

        defaults = {"key": "QA-13", "type": "", "status": "", "title": "QA-13", "description": ""}
        for field in ("key", "title", "type", "status", "description"):
            partial = {k: v for k, v in base.items() if k != field}
            p = get(f"no-{field}.json", json.dumps(partial))
            data = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
            check_eq(f"a missing `{field}` is accepted: exit 0 (no strict refusal)", p.returncode, 0)
            check_eq(f"a missing `{field}` takes the default, the other four keep what the file says",
                     {k: data.get(k) for k in defaults},
                     dict({k: base[k] for k in defaults}, **{field: defaults[field]}))

        # Today's stdout+stderr file: JSON, then a line of stderr. It reads the same as the JSON alone (a story in
        # flight must read its own snapshot), through the same reader as everything else.
        noisy = json.dumps(base, indent=2) + "\nWARN: jira cache is stale\n"
        p = get("noisy.md", noisy)
        check_eq("a stdout+stderr file reads: exit 0", p.returncode, 0)
        check_eq("and it is the same ticket as the JSON alone",
                 json.loads(p.stdout) if p.stdout.strip().startswith("{") else None,
                 json.loads(get("clean.md", json.dumps(base, indent=2)).stdout))

        # The deleted strict reader is gone, the one reader is there (positive control for the same lookup).
        check("the one reader is there", hasattr(TA, "parse_ticket_json") and hasattr(TA, "read_ticket_file"))
        check("the strict reader and its refusal class are gone",
              not any(hasattr(TA, name) for name in ("TicketFileError", "normalize_ticket_json", "parse_ticket_text")))
        check_eq("a JSON value that is not an object is not a ticket", TA.parse_ticket_json("[1, 2]", "QA-13"), None)
        check("and an object is one", TA.parse_ticket_json('{"key": "QA-13"}', "QA-13") is not None)

        # A person's file that is not UTF-8 text is theirs to fix: owner `person`, exit 1, the path named - never
        # read with replacement characters, never a crash.
        bad = root / "latin1.md"
        bad.write_bytes("# Café\n\nbody\n".encode("latin-1"))
        p = cli(root, "get", "QA-13", "--json", "--ticket-file", str(bad))
        failure = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
        check_eq("a non-UTF-8 file: exit 1", p.returncode, 1)
        check_eq("a non-UTF-8 file: the owner is the person, and the object names the file",
                 (failure.get("owner"), failure.get("file")), ("person", str(bad)))
        check_in("a non-UTF-8 file: the sentence says what is expected and names the path", "UTF-8 text", p.stderr)
        check_in("a non-UTF-8 file: the path is named", str(bad), p.stderr)

        # Markdown input is unchanged.
        p = cli(root, "get", "QA-1", "--json", "--ticket-file", str(FIXTURE_TICKETS / "QA-1.md"))
        check_eq("Markdown input is unchanged", json.loads(p.stdout)["title"], "Items can carry tags")
    finally:
        cleanup(root)


def part_diff_formats() -> None:
    root = temp_project("qa-factory-ticket-adapter-diff-formats-")
    try:
        fixture = FIXTURE_TICKETS / "QA-1.md"
        md = TA.parse_ticket_markdown(fixture.read_text(encoding="utf-8"), "QA-1")

        def side(name: str, **changes) -> Path:
            data = json.loads(json.dumps(md))
            data.update(changes)
            return put_json(root / name, data)

        def diff(old: Path, new: Path) -> dict:
            p = cli(root, "diff", "--old", str(old), "--new", str(new), "--json")
            check_eq(f"diff {old.name} {new.name}: exit 0", p.returncode, 0)
            return json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}

        # The same ticket, once as Markdown and once as the JSON a direct read writes. The JSON
        # has context keys the Markdown form cannot carry; they are not comparable, not changes.
        extra_links = dict(md["links"], issue_links=[{"relation": "blocks", "key": "QA-3"}],
                           remote_links=[])
        as_json = side("same.json", links=extra_links, attachments=[{"id": "1", "filename": "a.png"}],
                       revision="r1")
        result = diff(fixture, as_json)
        check_eq("Markdown vs JSON of the same ticket: severity none", result.get("severity"), "none")
        check_eq("Markdown vs JSON of the same ticket: nothing changed", result.get("changed"), [])
        check_eq("the link keys only one side has are listed, not counted",
                 ((result.get("detail") or {}).get("links") or {}).get("not_comparable"),
                 ["issue_links", "remote_links"])
        check("an attachments list only one side has is listed, not counted",
              ((result.get("detail") or {}).get("attachments") or {}).get("not_comparable") is True)

        # Text is compared after strip() and CRLF -> LF; the stored files stay as they are.
        padded = side("padded.json", description=md["description"].replace("\n", "\r\n") + "  \r\n",
                      title="  " + md["title"] + "\t")
        before = padded.read_bytes()
        check_eq("CRLF and padding are not a change", diff(side("plain.json"), padded).get("severity"),
                 "none")
        check_eq("and the stored file is not rewritten", padded.read_bytes(), before)

        base = side("base.json")
        removed = side("ac-removed.json", acceptance_criteria=md["acceptance_criteria"][:-1])
        result = diff(base, removed)
        check_eq("an acceptance criterion removed: requirements", result.get("severity"), "requirements")
        check_eq("and the criterion is named as removed",
                 len(((result.get("detail") or {}).get("acceptance_criteria") or {}).get("removed", [])), 1)
        added = side("comment-added.json", comments=md["comments"] + [
            {"author": "qa", "date": "2026-09-14", "text": "one more"}])
        check_eq("a comment added: context", diff(base, added).get("severity"), "context")
        status = side("status.json", status="Done")
        check_eq("a status move: context", diff(base, status).get("severity"), "context")

        with_att = side("att1.json", attachments=[{"id": "1", "filename": "a.png"}])
        more_att = side("att2.json", attachments=[{"id": "1", "filename": "a.png"},
                                                   {"id": "2", "filename": "b.png"}])
        result = diff(with_att, more_att)
        check_eq("an attachment added: context, not requirements", result.get("severity"), "context")
        check("and attachments is the field named", "attachments" in (result.get("changed") or []))
        same_att = side("att3.json", attachments=[{"id": "1", "filename": "a.png", "size": 99}])
        check_eq("an attachment's own metadata is not a new attachment", diff(with_att, same_att).get("severity"),
                 "none")

        l1 = side("links1.json", links=dict(md["links"], issue_links=[{"relation": "blocks", "key": "QA-3"}]))
        l2 = side("links2.json", links=dict(md["links"], issue_links=[{"relation": "blocks", "key": "QA-4"}]))
        check_eq("an issue link that moved: context", diff(l1, l2).get("severity"), "context")
        r1 = side("remote1.json", links=dict(md["links"], remote_links=[]))
        r2 = side("remote2.json", links=dict(md["links"], remote_links=[{"title": "t", "url": "u"}]))
        check_eq("a remote link added: context", diff(r1, r2).get("severity"), "context")

        # FR-41: revisions and times are printed when there are some, `null` when there are none.
        rev_a = side("rev-a.json", revision="r1", provenance={"source": "x", "fetched_at": "2026-09-14T10:00:00+00:00"})
        rev_b = side("rev-b.json", revision="r2", provenance={"source": "x", "fetched_at": "2026-09-14T18:00:00+00:00"})
        result = diff(rev_a, rev_b)
        check_eq("revisions and times are reported",
                 [result.get(k) for k in ("old_revision", "new_revision", "old_fetched_at", "new_fetched_at")],
                 ["r1", "r2", "2026-09-14T10:00:00+00:00", "2026-09-14T18:00:00+00:00"])
        result = diff(fixture, fixture)
        check_eq("with none recorded they are null, not invented",
                 [result.get(k, "absent") for k in ("old_revision", "new_revision", "old_fetched_at",
                                                    "new_fetched_at")], [None, None, None, None])
    finally:
        cleanup(root)


def part_freshness() -> None:
    root = temp_project("qa-factory-ticket-adapter-fresh-")
    try:
        write_config(root, {"kind": "file", "path": "no/such/dir"})
        task_root = root / "qa-factory" / "artifacts" / "QA-7"
        task_root.mkdir(parents=True)        # `freshness --task-root` reads an EXISTING story (CX1-18); `get --output` creates it
        work = task_root / "work"
        base, nxt = work / "ticket-snapshot.json", work / "ticket-snapshot.next.json"
        legacy = work / "ticket-snapshot.md"
        today = put_json(root / "now.json", rich_ticket())

        def fresh(*args, ticket_file: Path | None = today):
            argv = ["freshness", "QA-7", "--task-root", str(task_root), "--json", *args]
            if ticket_file is not None:
                argv += ["--ticket-file", str(ticket_file)]
            p = cli(root, *argv)
            parsed = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
            return p, parsed

        # No baseline: it is written and said so; nothing is journaled (nothing changed).
        p, got = fresh()
        check_eq("no baseline: exit 0", p.returncode, 0)
        check_eq("no baseline: `baseline_written`", got.get("result"), "baseline_written")
        check_eq("no baseline: the baseline is the ticket as read", load(base), rich_ticket())
        check("no baseline: no .next file", not nxt.exists())
        check_eq("no baseline: no ticket_changed event", [e for e in journal_lines(root)
                                                          if e.get("event") == "ticket_changed"], [])

        # Nothing moved: silence in the journal, the baseline untouched.
        before = rb(base)
        p, got = fresh()
        check_eq("same ticket: severity none", got.get("severity"), "none")
        check_eq("same ticket: nothing changed", got.get("changed"), [])
        check_eq("same ticket: the baseline is untouched", rb(base), before)
        check_eq("same ticket: no ticket_changed event", [e for e in journal_lines(root)
                                                          if e.get("event") == "ticket_changed"], [])
        check("the result carries the revisions block",
              set((got.get("revisions") or {})) >= {"old_revision", "new_revision", "old_fetched_at",
                                                    "new_fetched_at"}, str(got.get("revisions")))

        # A comment: context. The baseline is replaced, one event is journaled.
        moved = rich_ticket()
        moved["comments"] = moved["comments"] + [{"author": "qa", "date": "2026-09-14", "text": "hello"}]
        moved["provenance"] = {"source": "jira_direct_api", "fetched_at": "2026-09-15T10:00:00+00:00"}
        put_json(root / "ctx.json", moved)
        p, got = fresh(ticket_file=root / "ctx.json")
        check_eq("a comment: severity context", got.get("severity"), "context")
        check_eq("a comment: the field is named", got.get("changed"), ["comments"])
        check_eq("a comment: the baseline is replaced by the new snapshot", load(base), moved)
        check("a comment: no .next file", not nxt.exists())
        # L2: a story that never had the role-facing files gets none created and no line about them.
        check("a replace in a story with no view and no references creates neither",
              not (work / "ticket-view.md").exists() and not (work / "ticket-references.json").exists())
        check("and says nothing about them", "ticket-view.md" not in p.stderr and "ticket-references.json" not in p.stderr)
        check("and stdout is still the one JSON object", p.stdout.strip().startswith("{"))
        events = [e for e in journal_lines(root) if e.get("event") == "ticket_changed"]
        check_eq("a comment: one ticket_changed event", len(events), 1)
        check_in("the event names severity and fields", "context: comments", (events or [{}])[0].get("notes", ""))
        check_eq("the event names the task", (events or [{}])[0].get("task"), "QA-7")

        # A requirement: the baseline is KEPT, the new snapshot waits beside it.
        newer = json.loads(json.dumps(moved))
        newer["acceptance_criteria"] = newer["acceptance_criteria"][:1]
        newer["provenance"] = {"source": "jira_direct_api", "fetched_at": "2026-09-16T10:00:00+00:00"}
        put_json(root / "req.json", newer)
        kept = rb(base)
        p, got = fresh(ticket_file=root / "req.json")
        check_eq("an AC removed: severity requirements", got.get("severity"), "requirements")
        check_eq("an AC removed: the baseline is kept byte for byte", rb(base), kept)
        check_eq("an AC removed: the new snapshot waits as ticket-snapshot.next.json", load(nxt), newer)
        check_not_in("a waiting change replaces nothing, so it says nothing about stale files", "ticket-view.md", p.stderr)
        events = [e for e in journal_lines(root) if e.get("event") == "ticket_changed"]
        check_eq("an AC removed: a second ticket_changed event", len(events), 2)
        check_in("an AC removed: it says requirements", "requirements: acceptance_criteria",
                 events[-1].get("notes", "") if events else "")

        # --adopt: after the person's answer, the waiting snapshot is the baseline.
        p, got = fresh("--adopt", ticket_file=None)
        check_eq("--adopt: exit 0", p.returncode, 0)
        check_eq("--adopt: the baseline is now the new snapshot", load(base), newer)
        check("--adopt: the waiting file is gone", not nxt.exists())
        check_eq("--adopt writes the snapshot's bytes, LF, the one format (L3)", rb(base), TA.snapshot_bytes(newer))
        p, got = fresh("--adopt", ticket_file=None)
        check_eq("--adopt with nothing to adopt: exit 2", p.returncode, 2)
        check_in("--adopt with nothing to adopt: says so", "nothing to adopt", p.stderr)
        check_eq("--adopt with nothing to adopt: the baseline is untouched", load(base), newer)
        # A waiting file that cannot be decoded is never adopted (the one reader would otherwise read it as text).
        nxt.write_text("{ broken", encoding="utf-8")
        kept = rb(base)
        p, got = fresh("--adopt", ticket_file=None)
        check_eq("--adopt of an unreadable waiting file: exit 3", p.returncode, 3)
        check_eq("--adopt of an unreadable waiting file: nothing adopted, the file stays",
                 (rb(base), rb(nxt)), (kept, b"{ broken"))
        check_in("--adopt of an unreadable waiting file: names the file", "ticket-snapshot.next.json", p.stderr)
        nxt.unlink()

        # A snapshot waiting for an answer must not outlive a later check that settles it.
        put_json(nxt, newer)
        p, got = fresh(ticket_file=root / "req.json")
        check_eq("the ticket matches the baseline again: none", got.get("severity"), "none")
        check("a stale waiting snapshot is removed, so --adopt can never adopt old text", not nxt.exists())

        # A failing fetch: the exit code of `get`, the baseline untouched.
        kept = rb(base)
        p, got = fresh(ticket_file=root / "nope.json")
        check_eq("a missing ticket: the exit code of get (1)", p.returncode, 1)
        check_eq("a failed fetch leaves the baseline untouched", rb(base), kept)
        write_config(root, {})
        p, got = fresh(ticket_file=None)
        check_eq("an unconfigured adapter: the exit code of get (3)", p.returncode, 3)
        check_eq("and the baseline is untouched", rb(base), kept)

        # A story in flight: only the old `.md` (JSON inside) exists. It is the baseline; it is
        # never rewritten; the first replacement goes to `.json`, which then wins.
        base.unlink(missing_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps(rich_ticket(), indent=2), encoding="utf-8")
        old_bytes = legacy.read_bytes()
        p, got = fresh()
        check_eq("an old .md baseline is read: same ticket is none", got.get("severity"), "none")
        check("and no .json is written for a none", not base.exists())
        p, got = fresh(ticket_file=root / "ctx.json")
        check_eq("an old .md baseline: a comment is context", got.get("severity"), "context")
        check_eq("the replacement is written as .json", load(base), moved)
        check_eq("the old .md is left untouched", legacy.read_bytes(), old_bytes)
        p, got = fresh(ticket_file=root / "ctx.json")
        check_eq("with both files the .json is the baseline", got.get("severity"), "none")
        # Today's stdout+stderr file (JSON, then a stderr line) is a readable baseline: the one reader accepts the tail.
        base.unlink(missing_ok=True)
        legacy.write_text(json.dumps(rich_ticket(), indent=2) + "\nWARN: noise\n", encoding="utf-8")
        p, got = fresh()
        check_eq("a .md with a stderr tail is the baseline: the same ticket is none", got.get("severity"), "none")
        check("and no .json is written for a none", not base.exists())
        # A .md that starts like JSON and cannot be decoded is not a baseline.
        legacy.write_text("{ broken", encoding="utf-8")
        p, got = fresh()
        check_eq("an unreadable .md is no baseline: a new one is written", got.get("result"), "baseline_written")
        check("and it is .json", base.is_file())
        check_eq("and the unreadable .md is left as it was", rb(legacy), b"{ broken")
        # An unreadable .json baseline is refused, never overwritten behind anyone's back.
        base.write_text("{ broken", encoding="utf-8")
        p, got = fresh()
        check_eq("an unreadable .json baseline: exit 3", p.returncode, 3)
        check_eq("and it is not overwritten", rb(base), b"{ broken")
        check_in("and the message names the file", "ticket-snapshot.json", p.stderr)
        base.write_bytes(b"\xff\xfe\x00 not utf-8")
        p, got = fresh()
        check_eq("a .json baseline that is not UTF-8: exit 3, not overwritten", (p.returncode, rb(base)),
                 (3, b"\xff\xfe\x00 not utf-8"))

        # --task-root is required.
        p = cli(root, "freshness", "QA-7", "--json")
        check_eq("freshness without --task-root: a usage error", p.returncode, 2)

        # CLI CONTRACT, kept as a real child: stdout is ONE JSON document through a real process
        # boundary (FR-14), the journal line lands through the real writer, nothing else on stdout.
        base.unlink(missing_ok=True)
        legacy.unlink(missing_ok=True)
        before = len(journal_lines(root))
        p = run_adapter(root, "freshness", "QA-7", "--task-root", str(task_root), "--json",
                        "--ticket-file", str(today))
        check_eq("a real child: baseline written, exit 0", (p.returncode, p.stdout.strip()[:1]), (0, "{"))
        check_eq("a real child: stdout parses whole", json.loads(p.stdout).get("result"), "baseline_written")
        put_json(root / "child-ctx.json", dict(rich_ticket(), status="Done"))
        p = run_adapter(root, "freshness", "QA-7", "--task-root", str(task_root), "--json",
                        "--ticket-file", str(root / "child-ctx.json"))
        check_eq("a real child: a status move is context", json.loads(p.stdout).get("severity"), "context")
        check_eq("a real child: the writer's own OK line is not on stdout", "OK:" in p.stdout, False)
        check_eq("a real child: one event reached the journal", len(journal_lines(root)) - before, 1)
    finally:
        cleanup(root)


def part_freshness_refusals() -> None:
    """critic t-448 C1: `freshness` ends through the SAME handler chain `get` uses, so a failed read carries the owner
    `get` gives it (1 the person's, 3 the tracker's or the project's setting, 4 the factory's, 5 the login's) and,
    under --json, ONE error object on stdout. The exit 3 the skill reads as "tracker unreachable, informed pass" stays
    for what `get` gives 3 for; a lost login, a broken table and a bug never read as that."""
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-fresh-refusals-")
    real, saved_table = TA.client_from_config, TL.FIELDS_TABLE_PATH
    counter = [0]
    try:
        rest_config(root)
        issue = "/issue/TP1-15045?fields=*all"

        def boom(request):
            raise RuntimeError("boom")

        def run(*extra, ticket_file=None):
            counter[0] += 1
            task_root = root / "qa-factory" / "artifacts" / f"story-{counter[0]}"
            task_root.mkdir(parents=True)    # `freshness --task-root` reads an EXISTING story (CX1-18)
            argv = ["freshness", KEY, "--task-root", str(task_root), *extra]
            if ticket_file is not None:
                argv += ["--ticket-file", str(ticket_file)]
            p = cli(root, *argv)
            return p, one_json_object(p.stdout), (task_root / "work" / "ticket-snapshot.json").exists()

        # the tracker's: a 5xx after the retries is exit 3, owner tracker (the skill's informed pass), nothing written
        with_transport(Transport([(issue, 503)]))
        p, obj, written = run("--json")
        check_eq("freshness: a 503 stays exit 3, ONE object, owner tracker, no baseline written",
                 (p.returncode, obj and (obj["ok"], obj["owner"], obj["status"]), written), (3, (False, "tracker", 503), False))
        # a 404 with the login fine: exit 1, the tracker's
        with_transport(Transport([(issue, 404), ("/myself", {"accountId": "x"})]))
        p, obj, written = run("--json")
        check_eq("freshness: a 404 with the login fine -> exit 1, owner tracker, status 404",
                 (p.returncode, obj and (obj["owner"], obj["status"]), written), (1, ("tracker", 404), False))
        # the login's: exit 5, owner auth, naming the token variable
        with_transport(Transport([(issue, 401), ("/myself", 401)]))
        p, obj, written = run("--json")
        check_eq("freshness: a lost login -> exit 5, ONE object, owner auth, the token variable named",
                 (p.returncode, obj and obj["owner"], obj and "QA_JIRA_API_TOKEN" in obj["message"], written),
                 (5, "auth", True, False))
        check_eq("freshness: and the human sentence stays on stderr", "QA_JIRA_API_TOKEN" in p.stderr, True)
        plain, _, _ = run()
        check_eq("freshness without --json: the same exit 5, stdout empty", (plain.returncode, plain.stdout), (5, ""))
        # the factory's: an unexpected exception is exit 4, never the tracker's 3
        with_transport(Transport([(issue, boom)]))
        p, obj, written = run("--json")
        check_eq("freshness: an unexpected exception -> exit 4, owner factory, the sentence in the object",
                 (p.returncode, obj and (obj["owner"], obj["message"]), written),
                 (4, ("factory", "unexpected error: boom"), False))
        # a corrupted data table (a copy): exit 4, the file named, no request made
        bad = root / "jira-fields.json"
        bad.write_text(json.dumps(dict(TL.load_fields_table(), standard=[])), encoding="utf-8")
        t = story_routes()
        with_transport(t)
        TL.FIELDS_TABLE_PATH = bad
        try:
            p, obj, written = run("--json")
        finally:
            TL.FIELDS_TABLE_PATH = saved_table
        check_eq("freshness: a corrupted jira-fields.json -> exit 4, owner factory, the file named, no request",
                 (p.returncode, obj and (obj["owner"], obj["file"]), written, t.log),
                 (4, ("factory", "jira-fields.json"), False, []))
        # a fail() refusal: the code it carries and the object, with the person as the owner of their own file
        p, obj, written = run("--json", ticket_file=root / "nope.json")
        check_eq("freshness: a missing ticket file -> exit 1, ONE object: owner person, the file named",
                 (p.returncode, obj and (obj["owner"], obj["file"]), written),
                 (1, ("person", str(root / "nope.json")), False))
        write_config(root, {})
        p, obj, written = run("--json")
        check_eq("freshness: no adapter configured -> exit 3, ONE object, owner config",
                 (p.returncode, obj and obj["owner"], written), (3, "config", False))
        check_eq("freshness: a refusal prints no snapshot beside the object", "\"key\"" in p.stdout, False)
    finally:
        TA.client_from_config, TL.FIELDS_TABLE_PATH = real, saved_table
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def part_freshness_views() -> None:
    """L2 (t-428): when `--adopt` or a `context` replace makes a new baseline, a story that HAS `work/ticket-view.md`
    gets it re-rendered from that baseline (upstream's `ticket_view_text`), atomically; `ticket-raw/` and
    `source-inventory.json` are not touched; `ticket-references.json` has no snapshot-only renderer, so it is named
    as stale in ONE stderr line, and only when it exists. Nothing is created for a story that never had the files."""
    root = temp_project("qa-factory-ticket-adapter-views-")
    try:
        write_config(root, {"kind": "file", "path": "no/such/dir"})
        task_root = root / "qa-factory" / "artifacts" / "QA-7"
        task_root.mkdir(parents=True)        # `freshness --task-root` reads an EXISTING story (CX1-18)
        work = task_root / "work"
        view, refs = work / "ticket-view.md", work / "ticket-references.json"
        base, nxt = work / "ticket-snapshot.json", work / "ticket-snapshot.next.json"
        first = put_json(root / "first.json", rich_ticket())

        def fresh(*args, ticket_file=None):
            argv = ["freshness", "QA-7", "--task-root", str(task_root), "--json", *args]
            if ticket_file is not None:
                argv += ["--ticket-file", str(ticket_file)]
            return cli(root, *argv)

        fresh(ticket_file=first)
        old_view = "QA-7 - the text the story began on\n"
        view.write_text(old_view, encoding="utf-8")
        refs.write_text('{"rows": []}', encoding="utf-8")
        inventory = work / "source-inventory.json"
        inventory.write_text('{"sources": []}', encoding="utf-8")
        raw = work / "ticket-raw" / "issue.json"
        raw.parent.mkdir()
        raw.write_bytes(b"{}")
        before = {path: rb(path) for path in (refs, inventory, raw)}

        moved = rich_ticket()
        moved["comments"] = moved["comments"] + [{"author": "qa", "date": "2026-09-14", "text": "a new comment"}]
        p = fresh(ticket_file=put_json(root / "ctx.json", moved))
        check_eq("context replace: the baseline is the new text", (p.returncode, load(base)), (0, moved))
        check_eq("context replace: the view is the renderer's text of the new baseline",
                 rb(view), SI.ticket_view_text(moved).encode("utf-8"))
        check_in("context replace: and it holds the new comment", "a new comment", view.read_text(encoding="utf-8"))
        lines = [line for line in p.stderr.splitlines() if "ticket-references.json" in line]
        check_eq("context replace: ONE stderr line names the references as stale, not the view",
                 (len(lines), "ticket-view.md" in (lines or [""])[0]), (1, False))
        check_in("context replace: and says where the current text is", "ticket-snapshot.json", (lines or [""])[0])
        check_eq("context replace: references, inventory and the raw folder are untouched",
                 {path: rb(path) for path in before}, before)
        check("context replace: stdout is still the one JSON object", p.stdout.strip().startswith("{"))

        newer = json.loads(json.dumps(moved))
        newer["acceptance_criteria"] = newer["acceptance_criteria"][:1]
        fresh(ticket_file=put_json(root / "req.json", newer))
        check_eq("a waiting change replaces nothing: the view is as it was", rb(view), SI.ticket_view_text(moved).encode("utf-8"))
        p = fresh("--adopt")
        check_eq("--adopt: the view is re-rendered from the adopted text", rb(view),
                 SI.ticket_view_text(newer).encode("utf-8"))
        check_eq("--adopt: one line about the references, none about the view",
                 (sum("ticket-references.json" in line for line in p.stderr.splitlines()), "ticket-view.md" in p.stderr),
                 (1, False))
        check_eq("--adopt: references, inventory and raw folder untouched", {path: rb(path) for path in before}, before)

        # without the files nothing is created and nothing is said
        view.unlink()
        refs.unlink()
        moved2 = json.loads(json.dumps(newer))
        moved2["status"] = "Done"
        p = fresh(ticket_file=put_json(root / "ctx2.json", moved2))
        check_eq("no files: a context replace creates neither and says nothing about them",
                 (view.exists(), refs.exists(), "ticket-view.md" in p.stderr or "ticket-references.json" in p.stderr),
                 (False, False, False))
        nxt.unlink(missing_ok=True)
    finally:
        cleanup(root)


def part_freshness_pasted() -> None:
    """L1 (t-428): `freshness --ticket-file` on a story the person pasted re-reads THAT file, as the person's text
    (`pasted=True`, the semantics S0 reads it with), and never calls the tracker: the person's text is the story's
    requirement, and setting it against the tracker's is the S0 comparison's job (FR-25). The positive control is the
    same command without `--ticket-file`, which does read the tracker (the fake transport's log says so)."""
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-fresh-paste-")
    real = TA.client_from_config
    try:
        rest_config(root)
        task_root = root / "qa-factory" / "artifacts" / KEY
        task_root.mkdir(parents=True)        # `freshness --task-root` reads an EXISTING story (CX1-18)
        base, nxt = task_root / "work" / "ticket-snapshot.json", task_root / "work" / "ticket-snapshot.next.json"
        paste = root / "paste.md"
        text = "# Coupon at checkout\n\nApply a coupon.\n\n## Acceptance criteria\n\n- A coupon takes 10% off\n"
        paste.write_text(text, encoding="utf-8")
        argv = ["freshness", KEY, "--task-root", str(task_root), "--json"]

        def fresh_paste():
            p = cli(root, *argv, "--ticket-file", str(paste))
            return p, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else {})

        nothing = Transport([])                     # any request raises: the paste leg must make none
        with_transport(nothing)
        p, got = fresh_paste()
        check_eq("pasted story: no baseline yet, so it is written", (p.returncode, got.get("result")),
                 (0, "baseline_written"))
        snap = load(base) or {}
        check_eq("pasted story: the baseline is the person's text, labelled person_pasted",
                 ((snap.get("provenance") or {}).get("source"), snap.get("title"), len(snap.get("acceptance_criteria") or [])),
                 ("person_pasted", "Coupon at checkout", 1))
        check_eq("pasted story: the baseline's bytes are snapshot_bytes (the one format)", rb(base),
                 TA.snapshot_bytes(snap))
        p, got = fresh_paste()
        check_eq("pasted story: the same file again is none", (p.returncode, got.get("severity")), (0, "none"))
        paste.write_text(text + "- An expired coupon is refused\n", encoding="utf-8")
        p, got = fresh_paste()
        check_eq("pasted story: a criterion added to the file is a requirements change that waits",
                 (got.get("severity"), nxt.is_file()), ("requirements", True))
        check_eq("pasted story: no request reached the tracker, on any of the three runs", nothing.log, [])

        # positive control: the same command without --ticket-file reads the tracker, once
        rest_task = root / "rest-story"
        rest_task.mkdir()
        rest = story_routes()
        with_transport(rest)
        p = cli(root, "freshness", KEY, "--task-root", str(rest_task), "--json")
        got = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
        check_eq("control: without --ticket-file the tracker is read", (p.returncode, got.get("result")),
                 (0, "baseline_written"))
        check_eq("control: with exactly one request for the issue", rest.count("/issue/TP1-15045?fields=*all"), 1)
        fetched = load(rest_task / "work" / "ticket-snapshot.json") or {}
        check_eq("control: and the baseline is the tracker's text, labelled fetched",
                 (fetched.get("provenance") or {}).get("source"), "fetched")
    finally:
        TA.client_from_config = real
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def part_stale_rule() -> None:
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

    def at(delta: timedelta) -> str:
        return (now - delta).isoformat(timespec="seconds")

    check_eq("older than 6 h: stale", TA.baseline_is_stale(at(timedelta(hours=6, seconds=1)), now), True)
    check_eq("exactly 6 h: not older, no check", TA.baseline_is_stale(at(timedelta(hours=6)), now), False)
    check_eq("5 h 59 min: no check", TA.baseline_is_stale(at(timedelta(hours=5, minutes=59)), now), False)
    check_eq("a Z suffix is read as UTC", TA.baseline_is_stale("2026-09-20T05:59:59Z", now), True)
    check_eq("no fetched_at counts as older (an unknown is not fresh)", TA.baseline_is_stale(None, now), True)
    check_eq("an empty fetched_at counts as older", TA.baseline_is_stale("", now), True)
    check_eq("an unreadable fetched_at counts as older", TA.baseline_is_stale("yesterday-ish", now), True)
    check_eq("a time with no zone is read as UTC", TA.baseline_is_stale("2026-09-20T11:00:00", now), False)


# --- the freshness record: when the tracker was last compared, and what a person declined -------
# A `none` result writes nothing to the baseline (it must stay what `get --json` printed), so
# without a record of its own every resume after 6 h would fetch again; and "continue on the old
# text" left the baseline old, so the same change was put to the person on every run (FR-7).

def part_freshness_record() -> None:
    from datetime import datetime, timedelta, timezone
    import log_append
    root = temp_project("qa-factory-ticket-adapter-record-")
    try:
        write_config(root, {"kind": "file", "path": "no/such/dir"})
        task_root = root / "qa-factory" / "artifacts" / "QA-7"
        task_root.mkdir(parents=True)        # `freshness --task-root` reads an EXISTING story (CX1-18)
        work = task_root / "work"
        base, nxt, rec =work / "ticket-snapshot.json", work / "ticket-snapshot.next.json", work / "ticket-freshness.json"
        today = put_json(root / "now.json", rich_ticket())
        iso = lambda when: when.isoformat(timespec="seconds")  # noqa: E731

        def fresh(*args, ticket_file: Path | None = today):
            argv = ["freshness", "QA-7", "--task-root", str(task_root), "--json", *args]
            if ticket_file is not None:
                argv += ["--ticket-file", str(ticket_file)]
            p = cli(root, *argv)
            return p, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else {})

        def changed_events() -> list:
            return [e for e in journal_lines(root) if e.get("event") == "ticket_changed"]

        def near_now(value) -> bool:
            when = TA.parse_time(value)
            return when is not None and abs((datetime.now(timezone.utc) - when).total_seconds()) < 120

        # The first check writes the record beside the baseline.
        p, got = fresh()
        record = load(rec) or {}
        check("a first check creates the record", rec.is_file())
        check("the record carries when the tracker was last compared", near_now(record.get("checked_at")),
              str(record))
        check_eq("and the result of that check", record.get("result"), "baseline_written")

        # `none` stamps the record and never rewrites the baseline.
        put_json(rec, {"checked_at": "2026-01-01T00:00:00+00:00", "result": "none"})
        kept = rb(base)
        p, got = fresh()
        record = load(rec) or {}
        check_eq("none: the answer", got.get("severity"), "none")
        check("none: checked_at is stamped now", near_now(record.get("checked_at")), str(record))
        check_eq("none: the baseline is not rewritten", rb(base), kept)

        # The 6 h trigger is measured from checked_at, then from the baseline's fetched_at.
        now = datetime.now(timezone.utc).replace(microsecond=0)   # stamps are whole seconds
        old_baseline = rich_ticket()          # fetched_at 2026-09-14: long ago

        def due(checked_at) -> bool:
            if checked_at is None:
                rec.unlink(missing_ok=True)
            else:
                put_json(rec, {"checked_at": checked_at, "result": "none"})
            return TA.check_is_due(task_root, now)
        put_json(base, old_baseline)
        check_eq("a check 1 h ago: not due, though the snapshot is old", due(iso(now - timedelta(hours=1))), False)
        check_eq("a check exactly 6 h ago: not older, not due", due(iso(now - timedelta(hours=6))), False)
        check_eq("a check 6 h and a second ago: due", due(iso(now - timedelta(hours=6, seconds=1))), True)
        check_eq("no record: the baseline's fetched_at decides (old: due)", due(None), True)
        put_json(base, dict(old_baseline, provenance={"source": "x", "fetched_at": iso(now - timedelta(hours=1))}))
        check_eq("no record: a fresh baseline is not due", due(None), False)
        put_json(base, dict(old_baseline, provenance={}))
        check_eq("no record and no fetched_at: older, due", due(None), True)
        rec.write_text("{ not json", encoding="utf-8")
        record_now, problem = TA.read_freshness(task_root)
        check_eq("an unreadable record reads as absent", record_now, {})
        check("and says so", bool(problem), str(problem))
        check_eq("an unreadable record falls back to the baseline: due", TA.check_is_due(task_root, now), True)

        # A crash after `freshness` wrote `.next.json` and stamped `checked_at`, before the question
        # was asked, must not leave the story on the old text for 6 hours: a snapshot that waits
        # with no declined mark is a question nobody answered, so the check is due.
        put_json(base, dict(old_baseline, provenance={"source": "x", "fetched_at": iso(now - timedelta(hours=1))}))
        put_json(nxt, dict(old_baseline, description="Edited in the tracker."))
        put_json(rec, {"checked_at": iso(now - timedelta(minutes=5)), "result": "requirements"})
        check_eq("a waiting snapshot with no declined mark: due, though checked 5 minutes ago",
                 TA.check_is_due(task_root, now), True)
        # The mark a decline writes is the hash of the WAITING text, read the way the adapter reads it (B-364 R14), so the
        # pin computes it through `read_stored_snapshot` and not from the raw fixture dict.
        waiting_hash = TA.content_hash(TA.read_stored_snapshot(nxt)[0])
        put_json(rec, {"checked_at": iso(now - timedelta(minutes=5)), "result": "requirements",
                       "declined": {"hash": waiting_hash, "at": iso(now - timedelta(minutes=4))}})
        check_eq("a waiting snapshot the person declined: the 6 hour rule again, not due",
                 TA.check_is_due(task_root, now), False)
        put_json(rec, {"checked_at": iso(now - timedelta(minutes=5)), "result": "requirements",
                       "declined": {"hash": TA.legacy_content_hash(TA.read_stored_snapshot(nxt)[0]),
                                    "at": iso(now - timedelta(minutes=4))}})
        check_eq("a decline an older run marked (the legacy hash) of this waiting text: not due",
                 TA.check_is_due(task_root, now), False)
        put_json(rec, {"checked_at": iso(now - timedelta(minutes=5)), "result": "requirements",
                       "declined": {"hash": "a" * 64, "at": iso(now - timedelta(minutes=4))}})
        check_eq("R14: a mark for text X with a waiting text Y is a question nobody asked about Y: due",
                 TA.check_is_due(task_root, now), True)
        put_json(rec, {"checked_at": iso(now - timedelta(hours=7)), "result": "requirements",
                       "declined": {"hash": waiting_hash, "at": iso(now - timedelta(hours=7))}})
        check_eq("a declined waiting snapshot after 6 hours: due", TA.check_is_due(task_root, now), True)
        put_json(rec, {"checked_at": iso(now - timedelta(minutes=5)), "result": "requirements",
                       "declined": {"hash": waiting_hash, "at": iso(now - timedelta(minutes=4))}})
        nxt.write_text("{ not json at all", encoding="utf-8")
        check_eq("R14: an unreadable .next.json is unknown, not declined: due, though the mark matched the old file",
                 TA.check_is_due(task_root, now), True)
        nxt.unlink()
        put_json(rec, {"checked_at": iso(now - timedelta(minutes=5)), "result": "none"})
        check_eq("nothing waiting and checked 5 minutes ago: not due", TA.check_is_due(task_root, now), False)
        # R14, the clock: a check time ahead of `now` reads as unknown. At the slack exactly it is read by time.
        check_eq("a check stamped 60 s ahead of the clock: at the slack, read by time, not due",
                 due(iso(now + timedelta(seconds=TA.FUTURE_SLACK_SECONDS))), False)
        check_eq("a check stamped 61 s ahead of the clock: unknown, due",
                 due(iso(now + timedelta(seconds=TA.FUTURE_SLACK_SECONDS + 1))), True)
        check_eq("a check stamped a day ahead (a clock that was wrong): due", due(iso(now + timedelta(days=1))), True)
        for spelling, text in (("Z", (now + timedelta(seconds=61)).strftime("%Y-%m-%dT%H:%M:%SZ")),
                               ("+0000", (now + timedelta(seconds=61)).strftime("%Y-%m-%dT%H:%M:%S+0000")),
                               ("no zone", (now + timedelta(seconds=61)).strftime("%Y-%m-%dT%H:%M:%S"))):
            check_eq(f"a check 61 s ahead, spelled with {spelling}: due", due(text), True)
        put_json(base, dict(old_baseline, provenance={"source": "x", "fetched_at": iso(now + timedelta(seconds=61))}))
        check_eq("no record, a baseline fetched 61 s ahead of the clock: due", due(None), True)
        put_json(base, dict(old_baseline, provenance={"source": "x", "fetched_at": iso(now + timedelta(seconds=60))}))
        check_eq("no record, a baseline fetched 60 s ahead of the clock: by time, not due", due(None), False)
        put_json(base, old_baseline)

        # A failed check does not advance the stamp.
        put_json(rec, {"checked_at": "2026-01-01T00:00:00+00:00", "result": "none"})
        before = rb(rec)
        p, got = fresh(ticket_file=root / "nope.json")
        check_eq("a failed check: the exit code of get", p.returncode, 1)
        check_eq("a failed check does not stamp the record", rb(rec), before)

        # An unreadable record never fails a check: it is absent, said in one line, then rewritten.
        rec.write_text("{ not json", encoding="utf-8")
        put_json(base, rich_ticket())
        p, got = fresh()
        check_eq("an unreadable record: the check still runs", (p.returncode, got.get("severity")), (0, "none"))
        check_in("an unreadable record: one line says so", "ticket-freshness.json", p.stderr)
        check("an unreadable record: a good one is written", near_now((load(rec) or {}).get("checked_at")))

        # --- a requirements change the person declined is not asked again --------------------
        put_json(base, rich_ticket())
        rec.unlink(missing_ok=True)
        newer = rich_ticket()
        newer["acceptance_criteria"] = newer["acceptance_criteria"][:1]
        newer["provenance"] = {"source": "jira_direct_api", "fetched_at": "2026-09-16T10:00:00+00:00"}
        req = put_json(root / "req.json", newer)
        p, got = fresh(ticket_file=req)
        check_eq("a change to the requirements waits", (got.get("severity"), nxt.is_file()), ("requirements", True))
        check_eq("and is not yet an answered one", got.get("already_answered"), None)
        asked = len(changed_events())
        # The skill path resumes and asks again with nothing between: the same waiting text is
        # reported as still waiting, written once and journaled once.
        written, content = nxt.stat().st_mtime_ns, rb(nxt)
        for resume in (1, 2):
            p, got = fresh(ticket_file=req)
            check_eq(f"resume {resume} with the same waiting text: still waiting",
                     (got.get("severity"), got.get("still_waiting"), got.get("already_answered")),
                     ("requirements", True, None))
            check_eq(f"resume {resume}: the waiting file is not rewritten",
                     (nxt.stat().st_mtime_ns, rb(nxt)), (written, content))
            check_eq(f"resume {resume}: `ticket_changed` is not journaled again", len(changed_events()), asked)
        check_eq("the check is still stamped", bool((load(rec) or {}).get("checked_at")), True)
        # `--decline` records the person's words (FR-8, FR-9): the story goes on on the old text as a
        # KNOWN gap only if something carries that to the next gate. The words come from a file, like
        # every other command that records a person's words (`--words-file`, M30).
        pipeline_path = task_root / "pipeline.json"
        put_json(pipeline_path, {"ticket": "QA-7", "stages": {}})
        say = root / "said.txt"
        said = "Keep the old text.\n\nThe new acceptance criterion is out of scope: " + chr(0xE9) + "\n"
        say.write_bytes(said.encode("utf-8"))
        # no words: refused, naming the file option, nothing recorded (no mark, no remark, no event)
        pipeline_before, record_before = rb(pipeline_path), rb(rec)
        p, got = fresh("--decline", ticket_file=None)
        check_eq("--decline without words: refused with exit 2", p.returncode, 2)
        check_in("--decline without words: the door names the file option", "--words-file", p.stderr)
        check_eq("--decline without words: no pipeline.json change", rb(pipeline_path), pipeline_before)
        check_eq("--decline without words: no declined mark", rb(rec), record_before)
        check_eq("--decline without words: nothing journaled", len(changed_events()), asked)
        p, got = fresh("--decline", "--words-file", str(root / "no-such.txt"), ticket_file=None)
        check_eq("--decline with a missing words file: refused with exit 2", p.returncode, 2)
        check_in("and the reader's refusal names what is wanted", "no such file", p.stderr)
        check_eq("and records nothing", (rb(pipeline_path), rb(rec)), (pipeline_before, record_before))
        p, got = fresh("--decline", "--words", "typed", "--words-file", str(say), ticket_file=None)
        check_eq("--decline with both options: refused with exit 2", p.returncode, 2)
        check_eq("and records nothing", (rb(pipeline_path), rb(rec)), (pipeline_before, record_before))
        # a story with no pipeline.json has no gate to carry the words to: refused, nothing recorded
        pipeline_path.rename(root / "pipeline.parked.json")
        p, got = fresh("--decline", "--words-file", str(say), ticket_file=None)
        check_eq("--decline in a story with no pipeline.json: refused with exit 2", p.returncode, 2)
        check_in("and says where the words would be kept", "pipeline.json", p.stderr)
        check_eq("and records no declined mark", rb(rec), record_before)
        (root / "pipeline.parked.json").rename(pipeline_path)
        p, got = fresh("--decline", "--words-file", str(say), ticket_file=None)
        check_eq("--decline: exit 0", p.returncode, 0)
        remarks = (load(pipeline_path) or {}).get("remarks") or []
        check_eq("--decline keeps the person's words as a remark, in the shape waiver.py --remark writes",
                 (len(remarks), sorted(remarks[0]) if remarks else None),
                 (1, ["at", "by", "stage", "text"]))
        check_eq("the remark's words are the file's text, stripped at the ends",
                 (remarks or [{}])[0].get("text"), said.strip())
        check_eq("the remark names the stage the question was asked at",
                 ((remarks or [{}])[0].get("stage"), (remarks or [{}])[0].get("by")), ("S0", "human"))
        import gate_brief
        shown = "\n".join(gate_brief.open_before_mr(task_root))
        # Gate B names the GAP, built by code from the record (no wording read): when the declined
        # text was read, which requirement fields moved, the person's words.
        gap_mark = (load(rec) or {}).get("declined") or {}
        check_eq("the declined mark carries the requirement fields that moved and when the text was read",
                 (gap_mark.get("changed"), gap_mark.get("fetched_at")),
                 (["acceptance_criteria"], "2026-09-16T10:00:00+00:00"))
        check_in("gate B names the gap, the date and the fields in plain words, and the person's words",
                 "- Ticket requirements changed on 2026-09-16T10:00:00+00:00 (the acceptance criteria); "
                 "the person kept the old text: \"Keep the old text. The new acceptance criterion is out of scope",
                 shown)
        check_in("and the remark line is still there", "remark kept, not re-asked (S0)", shown)
        check_in("the next gate shows the remark, not re-asked", "remark kept, not re-asked (S0): Keep the old text.", shown)
        check_eq("gate_brief reads the same words back", [r["text"] for r in gate_brief.remarks(task_root)],
                 [" ".join(said.split())])
        heard = [e for e in journal_lines(root) if e.get("event") == "human_answer"]
        check_eq("--decline journals the answer as `human_answer`, as waiver.py --remark does", len(heard), 1)
        check_in("and the journal line carries the words", "Keep the old text.",
                 (heard or [{}])[0].get("notes", ""))
        check_eq("--decline: the answer", got.get("result"), "declined")
        mark = (load(rec) or {}).get("declined") or {}
        check("--decline records the content hash of the waiting snapshot",
              isinstance(mark.get("hash"), str) and len(mark.get("hash", "")) == 64, str(mark))
        check("--decline records when", near_now(mark.get("at")), str(mark))
        check("--decline keeps the waiting snapshot and the baseline",
              nxt.is_file() and load(base) == rich_ticket())
        notes = [e.get("notes", "") for e in changed_events()]
        check_eq("--decline is visible in the journal", len(notes) - asked, 1)
        check_in("and says what the person chose", "declined: acceptance_criteria", notes[-1] if notes else "")
        # the same words again are harmless (apply_remark drops an identical repeat)
        p, got = fresh("--decline", "--words-file", str(say), ticket_file=None)
        check_eq("declining twice with the same words keeps one remark",
                 len((load(pipeline_path) or {}).get("remarks") or []), 1)
        asked = len(changed_events())

        # The same new text again - even read at another moment - is the declined change.
        again = dict(newer, provenance={"source": "jira_direct_api", "fetched_at": "2026-09-17T10:00:00+00:00"})
        waiting = rb(nxt)
        p, got = fresh(ticket_file=put_json(root / "req-again.json", again))
        check_eq("the declined change again: still requirements", got.get("severity"), "requirements")
        check_eq("the declined change again: marked as answered", got.get("already_answered"), True)
        check("the declined change again: says when it was answered", near_now(got.get("declined_at")),
              str(got.get("declined_at")))
        check_eq("the declined change again: the waiting snapshot is untouched", rb(nxt), waiting)
        check_eq("the declined change again: not journaled as a new change", len(changed_events()), asked)
        check_eq("the declined change again: the baseline still holds the old text", load(base), rich_ticket())

        # A relabel and a status move are not a new change to the REQUIREMENTS: the hash of the
        # declined text covers the requirement fields only (FR-7). It used to cover the whole ticket,
        # so a `revision` or a label moved it and the same question came back after every edit.
        check_eq("the hash covers the requirement fields only",
                 TA.content_hash(newer) == TA.content_hash(dict(newer, status="Done", labels=["x"],
                                                                revision="2026-09-18T10:00:00.000+0000",
                                                                comments=[], parent=None, attachments=[],
                                                                links={})), True)
        check_eq("and a requirement field moves it",
                 TA.content_hash(newer) == TA.content_hash(dict(newer, description="changed")), False)
        mark_hash = ((load(rec) or {}).get("declined") or {}).get("hash")
        relabelled = dict(newer, status="Done", labels=["needs-triage"], revision="2026-09-18T10:00:00.000+0000",
                          provenance={"source": "jira_direct_api", "fetched_at": "2026-09-18T10:00:00+00:00"})
        waiting = rb(nxt)
        p, got = fresh(ticket_file=put_json(root / "req-relabel.json", relabelled))
        check_eq("a relabel and a status move after a decline: still the declined text",
                 (got.get("severity"), got.get("already_answered")), ("requirements", True))
        check_eq("a relabel after a decline: the declined mark is kept",
                 ((load(rec) or {}).get("declined") or {}).get("hash"), mark_hash)
        check_eq("a relabel after a decline: not journaled", len(changed_events()), asked)
        check_eq("a relabel after a decline: the waiting snapshot is not rewritten", rb(nxt), waiting)
        # A decline recorded before this change holds the hash of the WHOLE ticket: still read.
        put_json(rec, {"checked_at": "2026-09-18T10:00:00+00:00", "result": "requirements",
                       "declined": {"hash": TA.legacy_content_hash(newer), "at": "2026-09-16T10:00:00+00:00"}})
        p, got = fresh(ticket_file=req)
        check_eq("a decline recorded by an older run (the whole-ticket hash) is still read",
                 (got.get("severity"), got.get("already_answered")), ("requirements", True))
        check_eq("and an older decline still records nothing new", len(changed_events()), asked)
        put_json(rec, {"checked_at": "2026-09-18T10:00:00+00:00", "result": "requirements",
                       "declined": {"hash": mark_hash, "at": "2026-09-16T10:00:00+00:00"}})

        # A DIFFERENT fetch is a new change: it halts as usual, replaces the waiting file, clears the mark.
        other = dict(newer, description="Apply a coupon, but only once per order.")
        p, got = fresh(ticket_file=put_json(root / "req-other.json", other))
        check_eq("a different new text is a new change", (got.get("severity"), got.get("already_answered")),
                 ("requirements", None))
        check_eq("a new change replaces the waiting snapshot", load(nxt), other)
        check_eq("a new change clears the declined mark", (load(rec) or {}).get("declined"), None)
        check_eq("a new change is journaled", len(changed_events()), asked + 1)
        # ... and the description changing AFTER a decline is asked again, even beside a relabel
        put_json(rec, {"checked_at": "2026-09-18T10:00:00+00:00", "result": "requirements",
                       "declined": {"hash": mark_hash, "at": "2026-09-16T10:00:00+00:00"}})
        put_json(nxt, newer)
        asked = len(changed_events())
        p, got = fresh(ticket_file=put_json(root / "req-edit.json", dict(relabelled, description="Edited after the answer.")))
        check_eq("the description changed after a decline: asked again", (got.get("severity"), got.get("already_answered")),
                 ("requirements", None))
        check_eq("and journaled as a new change", len(changed_events()), asked + 1)

        # --decline with nothing waiting names that nothing waits; --adopt clears the mark.
        nxt.unlink()
        p, got = fresh("--decline", "--words-file", str(say), ticket_file=None)
        check_eq("--decline with nothing waiting: exit 2", p.returncode, 2)
        check_in("--decline with nothing waiting: says nothing waits", "nothing waits", p.stderr)
        p, got = fresh(ticket_file=req)
        p, got = fresh("--decline", "--words-file", str(say), ticket_file=None)
        check("declined again", bool(((load(rec) or {}).get("declined") or {}).get("hash")))
        # --adopt takes no words: a person's words handed to it are refused, never dropped in silence
        waiting_before, mark_before = rb(nxt), rb(rec)
        for tail in (("--words-file", str(say)), ("--words", "typed")):
            p, got = fresh("--adopt", *tail, ticket_file=None)
            check_eq(f"--adopt {tail[0]}: refused with exit 2", p.returncode, 2)
            check_in(f"--adopt {tail[0]}: says adoption takes no words and where the words go",
                     "--adopt takes no words", p.stderr)
            check_in(f"--adopt {tail[0]}: names --decline and waiver.py --remark", "--decline, or as a remark "
                     "through waiver.py --remark", p.stderr)
            check_eq(f"--adopt {tail[0]}: nothing adopted, nothing recorded",
                     (nxt.is_file(), rb(nxt), rb(rec)), (True, waiting_before, mark_before))
        before_adopt = len(changed_events())
        p, got = fresh("--adopt", ticket_file=None)
        check_eq("--adopt after a decline: exit 0", p.returncode, 0)
        notes = [e.get("notes", "") for e in changed_events()]
        check_eq("--adopt is visible in the journal", len(notes) - before_adopt, 1)
        check_in("and says what the person chose", "adopted: acceptance_criteria", notes[-1] if notes else "")
        check_eq("--adopt clears the declined mark", (load(rec) or {}).get("declined"), None)
        check_not_in("no decline recorded: gate B has no gap line", "Ticket requirements changed",
                     "\n".join(gate_brief.open_before_mr(task_root)))
        put_json(rec, {"checked_at": "2026-09-18T10:00:00+00:00", "result": "requirements",
                       "declined": {"hash": "a" * 64, "at": "2026-09-16T10:00:00+00:00"}})
        check_not_in("a decline recorded by an older run (no fields) gets no gap line either",
                     "Ticket requirements changed", "\n".join(gate_brief.open_before_mr(task_root)))
        check_eq("--adopt makes the waiting text the baseline", load(base), newer)
    finally:
        cleanup(root)

    # An unreachable tracker is not a ticket change: the journal has a word of its own for it.
    ok = log_append.build_record({"event": "ticket_unchecked", "task": "QA-7", "notes": "tracker unreachable"})
    check_eq("log_append knows `ticket_unchecked`", log_append.validate(ok), [])
    check("and requires its reason",
          bool(log_append.validate(log_append.build_record({"event": "ticket_unchecked", "task": "QA-7"}))))


# --- a person's words from a file: `--words-file` (legacy-2406 wave 3, node W3-W2, M30) -----------
# TP2-2406, gate B: a three-paragraph answer ending "local only, do not publish" reached the
# record as its first paragraph, because cmd.exe stops reading a command line at the first line
# break. `review --record` and `accept-gap` took a person's words only inline, so on the shell path
# they were cut the same way, silently. Both now read them through `person_words.read`, once, at
# argument handling: a refusal leaves the inventory byte for byte as it was.

WORDS = ('Go on without the spec.\n\nOnly "do not publish" the gap to Jira.\nKeep it local '
         + chr(0xE9) + chr(0x4E2D) + '\n')
NEGATIVE = '"do not publish"'
WORDS_FLAG = "--words-file"
# The third item is what the command's stdout BEGINS with: `accept-gap` reports per point since 0.8.1
# (`accepted: <ticket>: <point text>`; the ticket is the inventory row's `canonical_ref` tail, APP-2 below).
FORMS = {"review --record": (["review", "--record"], "human_review", "source review recorded"),
         "accept-gap": (["accept-gap", "--source-id", "SRC-gap"], "gap_acceptance", "accepted: APP-2: ")}


def gap_source() -> dict:
    """One required source the tracker refused: it has a gap to accept and no review yet."""
    return {"source_id": "SRC-gap", "canonical_ref": "https://jira/browse/APP-2", "relation": "referenced",
            "relevance": "unknown", "relevance_reason": "403 during assessment", "assessment_ref": None,
            "discovered_from": "SRC-task", "relation_evidence": "work/source.txt", "required": True,
            "status": "unavailable", "revision": None, "content_hash": None, "snapshot_ref": None,
            "fetched_at": "2026-09-19T00:00:00Z", "exclusion_or_error": "HTTP 403",
            "materials": {"comments": {"status": "unknown", "count": None},
                          "attachments": {"status": "unknown", "count": None, "items": []}}}


def part_words_file() -> None:
    root = temp_project("qa-factory-ticket-adapter-words-")
    work = root / "words-files"
    work.mkdir()
    counter = [0]
    try:
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})

        def words_at(name: str, data: bytes) -> str:
            (work / name).write_bytes(data)
            return str(work / name)

        def inventory() -> Path:
            counter[0] += 1
            return put_json(root / "qa-factory" / "artifacts" / "QA-7" / "work" / f"inventory-{counter[0]}.json",
                            {"schema_version": 1, "sources": [gap_source()]})

        def stored(path: Path, key: str):
            return ((load(path) or {}).get("sources") or [{}])[0].get(key, {}).get("words")

        for name, (base, key, said) in FORMS.items():
            def run(path: Path, *tail):
                return cli(root, *base, "--output", str(path), *tail)

            # a multi-line text with a quoted phrase and non-ASCII characters, recorded whole
            inv = inventory()
            done = run(inv, WORDS_FLAG, words_at("w.txt", WORDS.encode("utf-8")))
            check_eq(f"{name}: --words-file records, exit 0", (done.returncode, done.stdout.startswith(said)), (0, True))
            check_eq(f"{name}: the stored words are the file's text (the inventory strips its ends, as it "
                     f"does for inline words)", stored(inv, key), WORDS.strip())
            check_in(f"{name}: the negative instruction is in the record", NEGATIVE, stored(inv, key) or "")
            check_eq(f"{name}: the file is left as it was", (work / "w.txt").read_bytes(), WORDS.encode("utf-8"))
            crlf = "line one\r\n\r\nline " + chr(0xE9) + "\r\n"
            inv = inventory()
            run(inv, WORDS_FLAG, words_at("crlf.txt", b"\xef\xbb\xbf" + crlf.encode("utf-8")))
            check_eq(f"{name}: a BOM goes, CRLF stays", stored(inv, key), crlf.strip())
            big = ("0123456789abcdef" * 64 + "\n") * 100
            inv = inventory()
            run(inv, WORDS_FLAG, words_at("big.txt", big.encode("utf-8")))
            check(f"{name}: 100 KB comes back whole", stored(inv, key) == big.strip(),
                  f"stored {len(stored(inv, key) or '')} of {len(big.strip())} characters")

            # the inline route by plain python: the same output, the same stored words
            inv = inventory()
            done = run(inv, "--words", WORDS)
            check_eq(f"{name}: inline words by plain python behave as before",
                     (done.returncode, done.stdout.startswith(said)), (0, True))
            check_eq(f"{name}: and store what the file route stores", stored(inv, key), WORDS.strip())

            # every refusal exits 2 and the inventory is byte for byte what it was
            refusals = (("both options", ("--words", "typed", WORDS_FLAG, words_at("w.txt", WORDS.encode("utf-8"))), WORDS_FLAG),
                        ("a missing file", (WORDS_FLAG, str(work / "nope.txt")), "no such file"),
                        ("a directory", (WORDS_FLAG, str(work)), "directory"),
                        ("UTF-16", (WORDS_FLAG, words_at("u16.txt", WORDS.encode("utf-16"))), "UTF-8"),
                        ("invalid UTF-8", (WORDS_FLAG, words_at("bad.txt", b"fine so far \xff\xfe\xfa")), "UTF-8"),
                        ("a NUL byte", (WORDS_FLAG, words_at("nul.txt", b"abc\x00def")), "UTF-8"))
            for label, tail, expect in refusals:
                inv = inventory()
                before = rb(inv)
                done = run(inv, *tail)
                check_eq(f"{name}: {label} is refused with exit 2", done.returncode, 2)
                check_in(f"{name}: {label} names what is wanted", expect, done.stderr)
                check_eq(f"{name}: {label} records nothing", rb(inv), before)
            # an empty file: the reader's own refusal (the previous node); nothing is recorded either way
            inv = inventory()
            before = rb(inv)
            done = run(inv, WORDS_FLAG, words_at("empty.txt", b""))
            check(f"{name}: an empty file is refused", done.returncode != 0, f"{done.returncode} {done.stdout}")
            check_eq(f"{name}: an empty file records nothing", rb(inv), before)

            # neither option: today's refusal for missing words, unchanged
            inv = inventory()
            before = rb(inv)
            done = run(inv)
            check_eq(f"{name}: no words at all is still exit 3", done.returncode, 3)
            check_in(f"{name}: and still says --words is empty", "--words is empty", done.stderr)
            check_eq(f"{name}: and records nothing", rb(inv), before)

            # inline words that came through the cmd launcher are cut at the first line break: refused
            saved = run_py_entry.VIA_CMD
            run_py_entry.VIA_CMD = True
            try:
                inv = inventory()
                before = rb(inv)
                done = run(inv, "--words", "go on without it")
                check_eq(f"{name}: inline words through the cmd launcher are refused", done.returncode, 2)
                check_in(f"{name}: naming the file option", WORDS_FLAG, done.stderr)
                check_eq(f"{name}: and nothing is recorded", rb(inv), before)
                done = run(inv, WORDS_FLAG, words_at("w.txt", WORDS.encode("utf-8")))
                check_eq(f"{name}: the file form still records through the cmd launcher", done.returncode, 0)
                check_eq(f"{name}: byte-equal to the file", stored(inv, key), WORDS.strip())
            finally:
                run_py_entry.VIA_CMD = saved

        helped = cli(root, "--help")
        check_in("`--help` names the file form", WORDS_FLAG, helped.stdout)
        check_in("and the neither-given usage line of accept-gap names it", WORDS_FLAG,
                 cli(root, "accept-gap").stderr)
        check_in("and the one of review names it", WORDS_FLAG, cli(root, "review").stderr)

        # the real launcher (Windows): the one-line inline form is refused, the file form records
        if os.name == "nt":
            launcher = PLUGIN_ROOT / "hooks" / "run-py.cmd"
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QA_FACTORY_PYTHON=sys.executable,
                       CLAUDE_PROJECT_DIR=str(root))
            env.pop("QA_FACTORY_LAUNCHER", None)

            def launch(path: Path, tail: str):
                proc = subprocess.run(f'"{launcher}" ticket_adapter.py review --record --output "{path}" {tail}',
                                      shell=True, capture_output=True, cwd=str(work), env=env, timeout=300)
                return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

            inv = inventory()
            before = rb(inv)
            code, out, err = launch(inv, '--words "Go on without it."')
            check("review --record: inline words through the real cmd launcher are refused", code != 0,
                  f"{code} {out} {err}")
            check_in("review --record: the launcher's refusal names the file option", WORDS_FLAG, err)
            check_eq("review --record: nothing was recorded", rb(inv), before)
            code, out, err = launch(inv, f'{WORDS_FLAG} "{words_at("w.txt", WORDS.encode("utf-8"))}"')
            check("review --record: the file form records through the real cmd launcher", code == 0,
                  f"{code} {out} {err}")
            check_eq("review --record: byte-equal to the file", stored(inv, "human_review"), WORDS.strip())
        else:
            print("SKIPPED: not Windows (the real cmd launcher was not run)")
    finally:
        cleanup(root)


# --- C2-9 (D-0043): the person's word about a whole KIND of gap, and the code carrier of a host_unreachable verdict ---------

MR_URL = "https://git.example.com/team/sdk/-/merge_requests/510"
SHARE_URL = "https://share.example.com/sites/x/video.mp4"


def media_source(urls=(SHARE_URL,)) -> dict:
    """A read source with external media the collector has not given yet."""
    return {"source_id": "SRC-m", "canonical_ref": "https://jira/browse/APP-3", "relation": "referenced",
            "relevance": "relevant", "relevance_reason": "linked", "assessment_ref": None,
            "discovered_from": "SRC-task", "relation_evidence": "work/source.txt", "required": True,
            "status": "read", "revision": "1", "content_hash": None, "snapshot_ref": None,
            "inspection_status": "read", "fetched_at": "2026-09-19T00:00:00Z", "exclusion_or_error": None,
            "materials": {"comments": {"status": "read", "count": 0},
                          "attachments": {"status": "read", "count": 0, "items": []},
                          "external_media": {"status": "unavailable",
                                             "items": [{"url": url, "status": "pending"} for url in urls]}}}


def part_gap_kinds() -> None:
    """T6 (N2) the door `accept-gap --cause` / `--revoke`; T20 `inspect --probe-ref`."""
    root = temp_project("qa-factory-ticket-adapter-kinds-")
    try:
        write_config(root, {"kind": "file", "path": str(FIXTURE_TICKETS)})
        task = root / "qa-factory" / "artifacts" / "QA-7"
        inv = put_json(task / "work" / "inv.json", {"schema_version": 1, "sources": [gap_source(), media_source()]})
        (task / "state" / "words").mkdir(parents=True)
        words = task / "state" / "words" / "w.txt"
        words.write_text("go on without everything we cannot open, " + chr(0xE9) + "\n", encoding="utf-8")
        classes = task / "work" / "gap-classes.json"

        def run(*tail):
            return cli(root, "accept-gap", "--output", str(inv), *tail)

        before = rb(inv)
        done = run("--cause", "host_unreachable,source_unavailable", "--words-file", str(words), "--shown-text", "SharePoint")
        check_eq("T6 --cause records two kinds, exit 0", done.returncode, 0)
        check_in("T6 it prints the kind and how many points it closes", "class recorded: GC-1 host_unreachable - closes 0 open point(s) now", done.stdout)
        check_in("T6 the source kind closes the unavailable source", "class recorded: GC-2 source_unavailable - closes 1 open point(s) now", done.stdout)
        check_eq("T6 the inventory's bytes did not change (I6)", rb(inv), before)
        rows = load(classes)["classes"]
        check_eq("T6 two rows, the person's words whole", [(r["id"], r["cause"], r["words"].strip(), r["revoked_at"]) for r in rows],
                 [("GC-1", "host_unreachable", "go on without everything we cannot open, " + chr(0xE9), None),
                  ("GC-2", "source_unavailable", "go on without everything we cannot open, " + chr(0xE9), None)])
        again = run("--cause", "host_unreachable", "--words-file", str(words))
        check_in("T6 a repeat is `already recorded`, the earlier words stand", "already recorded: GC-1 host_unreachable", again.stdout)
        check_eq("T6 and writes no third row", len(load(classes)["classes"]), 2)
        bogus = run("--cause", "bogus", "--words-file", str(words))
        check_eq("T6 an unknown cause is refused with the list", (bogus.returncode != 0, "no_tool" in bogus.stderr), (True, True))
        for label, tail in (("--point", ("--source-id", "SRC-gap", "--point", "source:unavailable")),
                            ("--source-id", ("--source-id", "SRC-gap")), ("--all-unavailable", ("--all-unavailable",)),
                            ("--revoke", ("--revoke", "GC-1"))):
            mixed = run("--cause", "no_tool", "--words-file", str(words), *tail)
            check_eq(f"T6 --cause with {label} is a usage refusal", (mixed.returncode, "usage:" in mixed.stderr), (2, True))
        check_eq("T6 and none of them wrote", len(load(classes)["classes"]), 2)
        unknown = run("--revoke", "GC-9", "--words-file", str(words))
        check_in("T6 revoking an unknown id lists the live ones", "GC-1", unknown.stderr)
        taken = run("--revoke", "GC-1", "--words-file", str(words))
        check_eq("T6 --revoke before S1 closes: the row stays, stamped", (taken.returncode, bool(load(classes)["classes"][0]["revoked_at"])), (0, True))
        check_in("T6 a second revoke of it is refused with the live ones", "GC-2", run("--revoke", "GC-1", "--words-file", str(words)).stderr)
        put_json(task / "pipeline.json", {"stages": {"S1": {"status": "done"}}})
        frozen = rb(classes)
        late = run("--revoke", "GC-2", "--words-file", str(words))
        check_eq("T6 --revoke after S1 is closed: exit 2", late.returncode, 2)
        check_in("T6 with the door, rework_stage", "rework_stage", late.stderr)
        check_eq("T6 and the file is not changed", rb(classes), frozen)
        (task / "pipeline.json").write_text("{broken", encoding="utf-8")
        check_eq("T6 an unreadable pipeline.json counts as closed (the safe side of G3)", run("--revoke", "GC-2", "--words-file", str(words)).returncode, 2)
        check_eq("T6 --cause after S1 stays allowed and moves no inventory byte",
                 (run("--cause", "no_tool", "--words-file", str(words)).returncode, rb(inv)), (0, before))
        classes.write_text("{broken", encoding="utf-8")
        broken = run("--cause", "transient", "--words-file", str(words))
        check_eq("T6 an unreadable record is not written over", (broken.returncode != 0, classes.read_text(encoding="utf-8")), (True, "{broken"))

        # T20 `inspect --probe-ref`
        snapshot = task / "work" / "snap.json"
        snapshot.write_text("{}", encoding="utf-8")
        source = dict(media_source((MR_URL, SHARE_URL)), snapshot_ref="snap.json",
                      content_hash=hashlib.sha256(b"{}").hexdigest())
        inv2 = put_json(task / "work" / "inv2.json", {"schema_version": 1, "sources": [source]})
        receipt =task / "work" / "sources" / "SRC-m" / "mr-510.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"url": MR_URL, "error": "host_unreachable", "status": "unavailable"}), encoding="utf-8")
        rel = "sources/SRC-m/mr-510.json"

        def inspect(url, reason, *tail):
            return cli(root, "inspect", "--output", str(inv2), "--source-id", "SRC-m", "--media-url", url,
                       "--inspection-status", "unavailable", "--reason", reason, *tail)

        before2 = rb(inv2)
        for label, ref in (("a path with ..", "../work/sources/SRC-m/mr-510.json"), ("an absolute path", str(receipt)),
                           ("a missing file", "sources/SRC-m/none.json")):
            check_eq(f"T20 --probe-ref {label} is refused", (inspect(MR_URL, "host_unreachable: no route", "--probe-ref", ref).returncode != 0, rb(inv2)),
                     (True, before2))
        receipt2 = task / "work" / "sources" / "SRC-m" / "mr-511.json"
        receipt2.write_text(json.dumps({"url": MR_URL + "1", "error": "host_unreachable"}), encoding="utf-8")
        other = inspect(MR_URL, "host_unreachable: no route", "--probe-ref", "sources/SRC-m/mr-511.json")
        check_eq("T20 a receipt of another address is refused", (other.returncode != 0, "another address" in other.stderr), (True, True))
        wrong = inspect(MR_URL, "transient: timeout", "--probe-ref", rel)
        check_eq("T20 a cause that is not the receipt's code is refused", (wrong.returncode != 0, "host_unreachable" in wrong.stderr, rb(inv2)), (True, True, before2))
        receipt.write_text(json.dumps({"url": MR_URL, "error": "brand_new_code"}), encoding="utf-8")
        check_in("T20 a code the table does not know is refused", "does not know", inspect(MR_URL, "host_unreachable: x", "--probe-ref", rel).stderr)
        receipt.write_text(json.dumps({"url": MR_URL, "error": "host_unreachable", "status": "unavailable"}), encoding="utf-8")
        done = inspect(MR_URL, "host_unreachable: no route to host", "--probe-ref", rel)
        check_eq("T20 the right carrier is recorded", done.returncode, 0)
        row = load(inv2)["sources"][0]["materials"]["external_media"]["items"][0]
        check_eq("T20 the row carries the carrier", (row["probe_ref"], row["probe_code"], row["cause"], len(row["probe_sha256"])),
                 (rel, "host_unreachable", "host_unreachable", 64))
        shutil.copy(inv2, task / "work" / "source-inventory.json")
        check_eq("T20 and the integrity check passes while the receipt is as recorded", SI.verify_inventory_files(task)["valid"], True)
        receipt.write_text(json.dumps({"url": MR_URL, "error": "host_unreachable", "status": "changed"}), encoding="utf-8")
        changed = SI.verify_inventory_files(task)
        check_eq("T20 a changed receipt is an integrity error, not a silent default", (changed["valid"], any("probe receipt" in e for e in changed["errors"])), (False, True))
        refused = inspect(SHARE_URL, "no_tool: no browser", "--probe-ref", rel)
        check_eq("T20 --probe-ref with a cause the receipt does not give is refused", refused.returncode != 0, True)
    finally:
        cleanup(root)


# --- SC1-10 (B-K6): `--summary` - the scout's S1 commands print ONE line, the file stays the record -------------------------

def summary_line(label: str, p) -> dict:
    """The stdout of a `--summary` call: exactly one line, one JSON object with the two keys of the contract."""
    lines = p.stdout.splitlines()
    check_eq(f"B-K6 {label}: exit 0, ONE stdout line", (p.returncode, len(lines)), (0, 1))
    obj = json.loads(lines[0]) if len(lines) == 1 else {}
    check_eq(f"B-K6 {label}: the keys are `record` and `inventory`", sorted(obj), ["inventory", "record"])
    return obj


def part_summary() -> None:
    old_env = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
    root = temp_project("qa-factory-ticket-summary-")
    real = TA.client_from_config
    try:
        rest_config(root)
        work = root / "qa-factory" / "artifacts" / "APP-1" / "work"
        inv = work / "source-inventory.json"
        pending = dict(media_source(), source_id="SRC-p", canonical_ref=BASE + "/browse/APP-4", relevance="pending",
                       status="pending", inspection_status="pending", assessment_ref=None)
        put_json(inv, {"schema_version": 1, "sources": [gap_source(), media_source(), pending]})
        (work / "sources" / "SRC-m").mkdir(parents=True)
        (work / "sources" / "SRC-m" / "video.txt").write_text("what the video shows", encoding="utf-8")
        text = lambda: inv.read_text(encoding="utf-8")          # noqa: E731
        counts = {"unavailable": 1, "read": 1, "pending": 1}

        # assess: the record is the source the call changed; the inventory is counts, path and size, never the sources
        args = ("assess", "--output", str(inv), "--source-id", "SRC-p", "--relevance", "relevant", "--reason", "the story's own spec",
                "--assessment-ref", "sources/SRC-p/assessment/ticket.json")
        p = cli(root, *args, "--summary")
        obj = summary_line("assess", p)
        check_eq("B-K6 assess: the record is the assessed source, in the eight fields",
                 obj["record"], {"source_id": "SRC-p", "canonical_ref": BASE + "/browse/APP-4", "relation": "referenced",
                                 "status": "pending", "relevance": "relevant", "assessment_ref": "sources/SRC-p/assessment/ticket.json",
                                 "snapshot_ref": None, "inspection_status": "pending"})
        # SC1-10 B2 (B1's question 3): the test passes an ABSOLUTE --output inside the project, and the line shows it from the
        # project's root (the brief gives the scout a project-relative path, so for the scout the two are the same text)
        check_eq("B-K6 assess: the inventory is the path from the project's root, its size on disk, the count and the words",
                 obj["inventory"], {"path": "qa-factory/artifacts/APP-1/work/source-inventory.json", "bytes": inv.stat().st_size,
                                    "source_count": 3, "by_status": counts})
        check_not_in("B-K6 assess: ... and the line holds no folder of this machine", str(root), p.stdout)
        check("B-K6 assess: the line is shorter than the inventory file it stands for", len(p.stdout) < len(text()))
        check("B-K6 assess: no source of the inventory is repeated in the line", "SRC-gap" not in p.stdout and "APP-2" not in p.stdout)
        check_eq("B-K6 `--summary --json` is the same line (--summary is the stronger)", cli(root, *args, "--summary", "--json").stdout, p.stdout)
        plain = cli(root, *args)
        check_eq("B-K6 assess without the flag: the plain output of before, exit 0",
                 (plain.returncode, plain.stdout.startswith("{"), '"inventory"' in plain.stdout), (0, False, False))
        as_json = cli(root, *args, "--json")
        check_eq("B-K6 (FR-14 pin) assess --json: the whole inventory, as before", [s["source_id"] for s in json.loads(as_json.stdout)["sources"]],
                 ["SRC-gap", "SRC-m", "SRC-p"])

        # inspect: the record is the source the receipt belongs to
        p = cli(root, "inspect", "--output", str(inv), "--source-id", "SRC-m", "--media-url", SHARE_URL, "--inspection-status", "read",
                "--local-ref", "sources/SRC-m/video.txt", "--summary")
        obj = summary_line("inspect", p)
        check_eq("B-K6 inspect: the record is SRC-m", (obj["record"]["source_id"], obj["record"]["inspection_status"], obj["inventory"]["source_count"]),
                 ("SRC-m", "read", 3))
        check_eq("B-K6 inspect: the size is the file's size after the write", obj["inventory"]["bytes"], inv.stat().st_size)
        bad = cli(root, "inspect", "--output", str(inv), "--source-id", "SRC-m", "--media-url", SHARE_URL + "x", "--inspection-status", "read",
                  "--local-ref", "sources/SRC-m/video.txt", "--summary")
        check_eq("B-K6 inspect refused: the exit code (3) and the sentence on stderr are those of before, stdout is empty",
                 (bad.returncode, bad.stdout, "inspection receipt rejected" in bad.stderr), (3, "", True))

        # peek -> assess with the ref the line gave -> peek again (the early "already assessed" exit): the same contract on both paths
        issue = {"id": "6", "key": "APP-6", "fields": {"summary": "s", "updated": "u", "description": "d", "comment": {"total": 0, "comments": []},
                                                         "attachment": []}}
        t = Transport([("/issue/APP-6/remotelink", b"[]"), ("/issue/APP-6?fields=*all", issue), ("/rest/api/2/field", FIELDS)])
        with_transport(t)
        p = cli(root, "peek", "APP-6", "--output", str(inv), "--summary")
        obj = summary_line("peek", p)
        record = obj["record"]
        check_eq("B-K6 peek: a new source, pending, and the count grew", (record["status"], record["relevance"], obj["inventory"]["source_count"]),
                 ("pending", "pending", 4))
        check("B-K6 peek: the line carries the assessment_ref the next `assess` needs (not empty)", bool(record["assessment_ref"]))
        check_eq("B-K6 peek: the word counts follow the file", obj["inventory"]["by_status"], dict(counts, pending=2))
        check("B-K6 peek: the line is shorter than the file", len(p.stdout) < len(text()))
        p = cli(root, "assess", "--output", str(inv), "--source-id", record["source_id"], "--relevance", "relevant", "--reason", "named by the spec",
                "--assessment-ref", record["assessment_ref"], "--summary")
        check_eq("B-K6 assess with the ref from the peek line: accepted", (p.returncode, json.loads(p.stdout)["record"]["relevance"]), (0, "relevant"))
        requests = len(t.log)
        p = cli(root, "peek", "APP-6", "--output", str(inv), "--summary")
        obj = summary_line("peek of an assessed source", p)
        check_eq("B-K6 peek of an already assessed source: the summary of the existing record, nothing fetched",
                 (obj["record"]["source_id"], obj["record"]["relevance"], obj["inventory"]["source_count"], len(t.log) == requests),
                 (record["source_id"], "relevant", 4, True))
        old_line = cli(root, "peek", "APP-6", "--output", str(inv))
        check_eq("B-K6 peek of an assessed source without the flag: the line of before", old_line.stdout, "APP-6\talready assessed: relevant\n")

        # collect: the record the collector built; --json keeps the whole inventory (FR-14), the plain form its record line
        subject = {"id": "7", "key": "APP-7", "fields": {"summary": "s", "updated": "u", "description": "d", "comment": {"total": 0, "comments": []},
                                                           "attachment": []}}
        t = Transport([("/issue/APP-7/remotelink", b"[]"), ("/issue/APP-7?fields=*all", subject), ("/rest/api/2/field", FIELDS)])
        with_transport(t)
        p = cli(root, "collect", "APP-7", "--output", str(inv), "--relation", "subject", "--summary")
        obj = summary_line("collect", p)
        check_eq("B-K6 collect: the record is the collected source, read; the inventory has five", (obj["record"]["relation"], obj["record"]["status"],
                                                                                              obj["inventory"]["source_count"]), ("subject", "read", 5))
        check("B-K6 collect: the snapshot_ref is in the line (the role reads the file it names)", bool(obj["record"]["snapshot_ref"]))
        check("B-K6 collect: the line is shorter than the file", len(p.stdout) < len(text()))
        jt = Transport([("/issue/APP-8/remotelink", b"[]"), ("/issue/APP-8?fields=*all", dict(subject, key="APP-8", id="8")), ("/rest/api/2/field", FIELDS)])
        with_transport(jt)
        p = cli(root, "collect", "APP-8", "--output", str(inv), "--relation", "subject", "--json")
        check_eq("B-K6 (FR-14 pin) collect --json without --summary: the old shape, `sources` is a list of six",
                 (p.returncode, isinstance(json.loads(p.stdout)["sources"], list), len(json.loads(p.stdout)["sources"])), (0, True, 6))
        both = Transport([("/issue/APP-9/remotelink", b"[]"), ("/issue/APP-9?fields=*all", dict(subject, key="APP-9", id="9")), ("/rest/api/2/field", FIELDS)])
        with_transport(both)
        p = cli(root, "collect", "APP-9", "--output", str(inv), "--relation", "subject", "--json", "--summary")
        check_eq("B-K6 collect --json --summary: the summary line", (p.returncode, sorted(json.loads(p.stdout))), (0, ["inventory", "record"]))

        # a refusal keeps its exit code and its stderr; a stdout summary is a success line only
        story = root / "qa-factory" / "artifacts" / "APP-5" / "work" / "source-inventory.json"
        with_att = dict(issue, key="APP-5", id="5", fields=dict(issue["fields"], attachment=[
            {"id": "9", "filename": "a.png", "mimeType": "image/png", "size": 3, "content": BASE + "/file/9"}]))
        lost = Transport([("fields=updated", 401), ("/issue/APP-5?fields=*all", with_att), ("/file/9", 401)])
        with_transport(lost)
        p = cli(root, "collect", "APP-5", "--output", str(story), "--relation", "task", "--summary")
        check_eq("B-K6 a lost login under --summary: exit 5 as before, no summary line", (p.returncode, p.stdout, "QA_JIRA_API_TOKEN" in p.stderr),
                 (5, "", True))

        # the flag belongs to four commands; any other is a usage refusal that names them, and does nothing
        before = rb(inv)
        for command in (("get", "QA-1"), ("children", "QA-1"), ("review", "--output", str(inv)), ("probe", "--output", str(root / "r.json")),
                        ("refresh", "--output", str(inv)), ("accept-gap", "--output", str(inv), "--all-unavailable"), ("receipts", "--output", str(inv)),
                        ("freshness", "QA-1")):
            p = cli(root, *command, "--summary")
            check_eq(f"B-K6 `{command[0]} --summary`: exit 2, the four commands named, stdout empty",
                     (p.returncode, p.stdout, "applies to collect, peek, assess and inspect" in p.stderr), (2, "", True))
        p = cli(root, "--migrate-method", "--config", str(root / "qa-factory" / "config.json"), "--summary")
        check_eq("B-K6 a flag with no command at all (--migrate-method) is refused too", (p.returncode, "applies to collect" in p.stderr), (2, True))
        check_eq("B-K6 and none of them wrote", rb(inv), before)
        check_eq("B-K6 (control) the same `get` without the flag still reads", cli(root, "get", "QA-1", "--json", "--ticket-file",
                                                                                   str(FIXTURE_TICKETS / "QA-1.md")).returncode, 0)

        # print_summary, its edges: an absent record, an absent field, an absent status, an absent file, non-ASCII, an empty inventory
        def printed(record, inventory, output):
            out = io.StringIO()
            with redirect_stdout(out):
                TA.print_summary(record, inventory, output)
            return out.getvalue()

        none_line = printed(None, {"sources": [{"source_id": "A", "status": "read"}, {"source_id": "B"}, {"source_id": "C", "status": "read"}]},
                            str(root / "no-such.json"))
        check_eq("B-K6 edge: no record -> null; a source without a status is counted under `null`; no file -> bytes null; the line is compact",
                 json.loads(none_line), {"record": None, "inventory": {"path": "no-such.json", "bytes": None, "source_count": 3,
                                                                       "by_status": {"read": 2, "null": 1}}})
        # SC1-10 B2: the path the line shows - from the project's root when absolute and inside one, else exactly as given
        outside = temp_dir("qa-ticket-summary-outside-")
        try:
            stray = str(outside / "inv.json")
            for label, given, shown in (
                    ("a relative --output is echoed as given", "qa-factory/artifacts/APP-1/work/source-inventory.json",
                     "qa-factory/artifacts/APP-1/work/source-inventory.json"),
                    ("a relative path with a dot segment is echoed as given", "./work/inv.json", "./work/inv.json"),
                    ("an absolute path in the project root itself", str(root / "inv.json"), "inv.json"),
                    ("an absolute path with `..` segments that stays inside the project", str(root / "qa-factory" / ".." / "inv.json"), "inv.json"),
                    ("an absolute path with NO project marker above it stays as given (the only path the caller can follow)", stray, stray)):
                check_eq(f"B-K6 path: {label}", json.loads(printed(None, {}, given))["inventory"]["path"], shown)
            check_eq("B-K6 path: `_summary_path` never raises on a value that is no path (None, empty, a NUL)",
                     [TA._summary_path(value) for value in (None, "", "a\0b")], [None, "", "a\0b"])
        finally:
            cleanup(outside)
        check_eq("B-K6 edge: compact, one line", (none_line.count("\n"), ", " in none_line, '": ' in none_line), (1, False, False))
        sparse = json.loads(printed({"source_id": "S"}, {"sources": []}, str(inv)))
        check_eq("B-K6 edge: a field the record lacks is null; an empty inventory is zero and no words",
                 (sparse["record"], sparse["inventory"]["source_count"], sparse["inventory"]["by_status"]),
                 ({"source_id": "S", "canonical_ref": None, "relation": None, "status": None, "relevance": None, "assessment_ref": None,
                   "snapshot_ref": None, "inspection_status": None}, 0, {}))
        check_eq("B-K6 edge: an empty record is a record of nulls, not an absent one", json.loads(printed({}, {}, str(inv)))["record"]["source_id"], None)
        check_in("B-K6 edge: text is written as it is (no \\u escapes)", chr(0xE9),
                 printed({"source_id": "S", "canonical_ref": "caf" + chr(0xE9)}, {"sources": []}, str(inv)))
        check_eq("B-K6 edge: _source_of finds by id, and an absent id is None", (TA._source_of({"sources": [{"source_id": "A"}]}, "A"),
                                                                             TA._source_of({"sources": [{"source_id": "A"}]}, "Z"),
                                                                             TA._source_of({}, "A")), ({"source_id": "A"}, None, None))
    finally:
        TA.client_from_config = real
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


if __name__ == "__main__":
    main()
