#!/usr/bin/env python3
"""B-231 wave A: the person's word about sources, before the run (t-172, critic overrides C1-C8).

The record and its parser (P1), the marks in the inventory (P2), the fetch doors at library level
(P3 as C4). The guard (P7) is pinned in test_guard_command_text.py.

TP1-15045 (judge run, 23.09): the scout read a draft MR of an earlier factory run, cited it as a
requirement source and as existing coverage for six criteria. The matcher below decides, from a
person's line, which sources that is - and it may only err toward "no match": a match on a source
the word does not name reads something the person said not to read.

No network: every client here is a fake that raises when it is asked for a byte of something the
person left out.
"""
import hashlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import source_exclusions as SX  # noqa: E402
import source_inventory as SI  # noqa: E402
import ticket_adapter as TA  # noqa: E402

DASH = "\u2014"
MR_1924 = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"
# The comment of TP1-15045, snapshot revision 2026-09-18T08:23:41.338+0000 (M3 of the t-172 spec).
COMMENT_15045 = ("Draft MR is intended for evaluation of QA Factory output and is not merge-ready "
                 "product test coverage " + MR_1924)
REASON_1924 = "Draft MR of an earlier factory run, not a product change"
JIRA = "https://example.org"
TMP: list = []


def tmp() -> Path:
    path = temp_dir("qa-source-exclusions-")
    TMP.append(path)
    return path


# ---- fixtures -----------------------------------------------------------------------------------

class Jira:
    """A fake Jira client. `raising=True` is the client of a story that must not fetch: any call is an
    AssertionError, which no caller catches (they catch FetchError/OSError)."""
    acceptance_criteria_fields: list = []
    api_version = "2"
    project_keys: list = []

    def __init__(self, issues=None, raising=False, base_url="https://jira.invalid"):
        self.base_url, self.issues, self.raising, self.calls = base_url, issues or {}, raising, []

    def _touch(self, what):
        self.calls.append(what)
        if self.raising:
            raise AssertionError(f"a byte of {what} was asked for, though the person left it out")

    def get_json(self, path):
        self._touch(path)
        if path.endswith("/project/ZZZ"):
            raise SI.FetchError(500, "HTTP 500", retryable=True)  # an unproven prefix
        return {"key": path.rsplit("/", 1)[-1]}

    def issue(self, key):
        self._touch("issue " + key)
        spec = self.issues[key]
        comments = [{"id": str(n), "author": {"displayName": "A"}, "body": body, "created": "x"}
                    for n, body in enumerate(spec.get("comments") or [])]
        return {"key": key, "id": "1", "fields": {
            "updated": "rev-1", "summary": "title " + key, "description": spec.get("description", ""),
            "attachment": [], "comment": {"total": len(comments), "startAt": 0, "comments": comments}}}

    def all_comments(self, key, embedded=None):
        self._touch("comments " + key)
        return list((embedded or {}).get("comments") or [])

    def get_bytes(self, url):
        self._touch("bytes " + url)
        return b"x"


def story(base=None):
    """(work dir, inventory path) of a fresh story."""
    root = base or tmp()
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    return work, work / "source-inventory.json"


def put_list(work: Path, text: str, task_key: str = "TASK-1") -> dict:
    """The orchestrator's `--load`, as a library call: parse the bytes, write the record."""
    data = text.encode("utf-8")
    entries, problems = SX.parse_bytes(data, task_key)
    assert not [p for p in problems if p.get("fatal")], problems
    return SX.write_record(work.parent, entries, "list.txt", data)


def excl(word: str, reason: str = "r") -> dict:
    """One exclusion, as the record holds it, from one line of a list."""
    entries, problems = SX.parse_list(f"{word} {DASH} {reason}\n")
    assert entries, (word, problems)
    return dict(entries[0], id="X1", origin=SX.ORIGIN_PERSON, at="2026-09-30T20:00:00Z", revoked_at=None)


def collect(client, key, output, **kw):
    record = SI.collect_jira_source(client, key, output, **kw)
    return record, SI.update_inventory(output, record)


def by_ref(inventory, key):
    return next(s for s in inventory["sources"] if s["canonical_ref"].endswith("/" + key))


def media_rows(source):
    return source["materials"]["external_media"]["items"]


def sx_cli(root: Path, *args):
    """source_exclusions.main() in this process, against the temp project `root`."""
    use_project(root)
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = SX.main([str(a) for a in args])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def ta_cli(root: Path, client, *args):
    """ticket_adapter.main() in this process with a fake client in place of the real one."""
    use_project(root)
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["adapters"] = {"ticket": {"kind": "jira", "method": "api", "direct_api": {
        "base_url": client.base_url, "auth_type": "bearer", "secret_ref": "X_TOKEN"}}}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    real, TA.client_from_config = TA.client_from_config, (lambda adapter_cfg: client)
    out, err = io.StringIO(), io.StringIO()
    saved, code = sys.argv, 0
    sys.argv = ["ticket_adapter.py", *[str(a) for a in args]]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = TA.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv, TA.client_from_config = saved, real
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def story_in_project(root: Path, ticket="TASK-1"):
    task_root = root / "qa-factory" / "artifacts" / ticket
    (task_root / "work").mkdir(parents=True, exist_ok=True)
    return task_root, task_root / "work" / "source-inventory.json"


# ---- P1: the parser -----------------------------------------------------------------------------

def parse_empty_and_comments():
    for label, text in (("empty", ""), ("blank lines", "\n\n  \n"), ("comments only", "# one\n   # two\n\n")):
        entries, problems = SX.parse_list(text)
        check_eq(f"edge 1, {label}: no exclusion and no problem (a list never excludes more than its lines name)",
                 (entries, problems), ([], []))
    root = temp_project("qa-sx-empty-")
    try:
        task_root, output = story_in_project(root)
        listing = task_root / "list.txt"
        listing.write_text("# nothing yet\n", encoding="utf-8")
        result = sx_cli(root, "--task", "TASK-1", "--load", listing)
        check_eq("edge 1: --load of an empty list exits 0", result.returncode, 0)
        check_in("edge 1: and says the list names no source", "the list names no source", result.stdout)
        record = json.loads((task_root / "work" / "source-exclusions.json").read_text(encoding="utf-8"))
        check_eq("edge 1: the record holds an empty exclusions list", record["exclusions"], [])
        item = Jira({"TASK-1": {"description": "see " + MR_1924}})
        _, inventory = collect(item, "TASK-1", output)
        check_eq("edge 1: an empty exclusions list marks nothing and adds no line",
                 (SI.marks_in(inventory), "excluded_by" in output.read_text(encoding="utf-8")), (set(), False))
        check_eq("edge 1: and the block is what it always was (pending)",
                 media_rows(by_ref(inventory, "TASK-1"))[0]["status"], "pending")
    finally:
        cleanup(root)


def parse_bom_crlf():
    data = b"\xef\xbb\xbfTP1-5 - first reason\r\n# note\r\nx/y!4 \xe2\x80\x94 second reason\r\n"
    entries, problems = SX.parse_bytes(data)
    check_eq("a BOM and CRLF: two entries, no problem", (len(entries), problems), (2, []))
    check_eq("a BOM and CRLF: the reasons carry no CR and no BOM",
             [e["reason"] for e in entries], ["first reason", "second reason"])
    check_eq("a BOM and CRLF: line numbers count every line", [e["line"] for e in entries], [1, 3])
    lf = SX.parse_bytes(data.replace(b"\r\n", b"\n"))[0]
    check_eq("LF and CRLF read the same", [(e["as_written"], e["reason"]) for e in lf],
             [(e["as_written"], e["reason"]) for e in entries])


def parse_forms():
    cases = [
        ("a key", "TP1-13797 " + DASH + " r", {"kind": "ticket", "key": "TP1-13797", "host": None}),
        ("a key in lower case", "tp1-13797 - r", {"kind": "ticket", "key": "TP1-13797", "host": None}),
        # t-267 C11: the ONE key shape of the factory (ticket_light.KEY_RE) takes an underscore as part of a
        # Jira project key. Until then this line was "unreadable" here while the collector read MY_PROJ-12 as PROJ-12.
        ("a key with an underscore (one key, C11)", "MY_PROJ-12 - r", {"kind": "ticket", "key": "MY_PROJ-12", "host": None}),
        ("a browse link", JIRA + "/browse/TP1-13797?focusedId=1 - r",
         {"kind": "ticket", "key": "TP1-13797", "host": "example.org"}),
        ("an MR link", MR_1924 + " - r",
         {"kind": "mr", "host": "git.example", "project": "tp1-group/testproject1-ui", "iid": "1924",
          "style": "merge_requests", "head_sha": None, "branch": None}),
        ("an escaped MR link", "https://git.example/tp1-group/testproject1/-/merge\\_requests/3890 - r",
         {"kind": "mr", "host": "git.example", "project": "tp1-group/testproject1", "iid": "3890",
          "style": "merge_requests", "head_sha": None, "branch": None}),
        ("the short form", "testproject1-ui!1924 - r",
         {"kind": "mr", "host": None, "project": "testproject1-ui", "iid": "1924", "style": "merge_requests",
          "head_sha": None, "branch": None}),
        ("the short form with a group", "tp1-group/testproject1-ui!1924 - r",
         {"kind": "mr", "host": None, "project": "tp1-group/testproject1-ui", "iid": "1924",
          "style": "merge_requests", "head_sha": None, "branch": None}),
        ("another link, normalised", "HTTPS://Docs.Example/Spec/?a=1#frag - r",
         {"kind": "url", "url": "https://docs.example/Spec?a=1"}),
        ("a commit", "135699AE2f00 - r", {"kind": "ref", "sha": "135699ae2f00", "branch": None}),
        ("a branch", "branch:TP1-15045-visual-workflow-diff-validation - r",
         {"kind": "ref", "sha": None, "branch": "TP1-15045-visual-workflow-diff-validation"}),
    ]
    for label, line, target in cases:
        entries, problems = SX.parse_list(line + "\n")
        check_eq(f"parse {label}", [e["target"] for e in entries], [target])
        check_eq(f"parse {label}: no problem", problems, [])
    entries, _ = SX.parse_list("testproject1-ui!1924: Draft MR\n")
    check_eq("a trailing colon on the source is stripped, the rest is the reason",
             (entries[0]["as_written"], entries[0]["reason"]), ("testproject1-ui!1924", "Draft MR"))
    for label, rest, reason in (("em dash", DASH + " the reason", "the reason"), ("hyphen", "- the reason", "the reason"),
                                ("colon", ": the reason", "the reason"), ("none", "the reason", "the reason")):
        entries, problems = SX.parse_list(f"TP1-5 {rest}\n")
        check_eq(f"a leading separator ({label}) is stripped from the reason", (entries[0]["reason"], problems),
                 (reason, []))
    whole = "a long reason, " + "word " * 60 + "- and a dash inside"
    check_eq("the reason is kept whole, clipped nowhere", SX.parse_list("TP1-5 - " + whole + "\n")[0][0]["reason"],
             whole)
    check_eq("edge 5: the URL of kind url keeps its query", SX.parse_list("https://x.example/a?v=1 - r\n")[0][0]["target"]["url"],
             "https://x.example/a?v=1")


def parse_malformed_each_kind():
    cases = [
        ("not a source", "hello there - r", "unreadable", False),
        ("a bare iid", "!4243 - r", "bare_iid", False),
        ("a commit id under 12 characters", "abcdef12345 - r", "short_sha", False),
        ("a key with a dash in the prefix", "MY-PROJ-12 - r", "unreadable", False),
        ("a key with a long s (its upper case is a plain S)", "PROſ-12 - r", "unreadable", False),
        ("a key in full-width letters", "ＰＲＯＪ-12 - r", "unreadable", False),
        ("a short form with trailing text", "testproject1-ui!1924. - r", "unreadable", False),
        ("a link with no host", "https:// - r", "unreadable", False),
        ("a branch with no name", "branch: - r", "unreadable", False),
        ("no reason", "TP1-5", "no_reason", True),
        ("no reason after a separator only", "TP1-5 " + DASH, "no_reason", True),
        ("a second source where the reason should be", "testproject1-ui!1 TP1-5", "two_sources", True),
    ]
    for label, line, code, has_entry in cases:
        text = "# header\n\n" + line + "\n"
        entries, problems = SX.parse_list(text)
        check_eq(f"malformed, {label}: nothing is applied", entries, [])
        check_eq(f"malformed, {label}: one problem of the right kind, with its line number and the line as written",
                 [(p["code"], p["line"], p["text"]) for p in problems], [(code, 3, line)])
        check_eq(f"malformed, {label}: a problem whose target read carries it (for a person's go on); the rest do not",
                 problems[0]["entry"] is not None, has_entry)
    entries, problems = SX.parse_list("x!1 " + DASH + " TP1-5 is the same thing\n")
    check_eq("C5(d): a reason that starts with a source after a separator is a reason, not a second source",
             (len(entries), problems), (1, []))
    entries, problems = SX.parse_list("x!1 defaced by a script\n")
    check_eq("a reason starting with a 7-hex-letter word is no commit id (strict for reasons)",
             (len(entries), problems), (1, []))
    for code_line in ("hello - r", "TP1-5"):
        message = SX.parse_list(code_line + "\n")[1][0]["message"]
        check_in("the problem says what to write (FR-1)", "line 1", message)
    check_in("a problem on a bare iid says how to satisfy it", "testproject1-ui!1924", SX.parse_list("!1 - r\n")[1][0]["message"])


def parse_two_targets_one_line():
    entries, problems = SX.parse_list("testproject1-ui!1924 TP1-5 - same MR\n")
    check_eq("edge 2: two sources on one line are refused, neither applied", (entries, [p["code"] for p in problems]),
             ([], ["two_sources"]))
    check_eq("edge 2: the first source is carried for a person's go on, the second is nowhere",
             problems[0]["entry"]["as_written"], "testproject1-ui!1924")


def parse_duplicate_merges_reasons():
    text = "TP1-5 - first\n\n# between\ntp1-5 - second\nx!4 - other\nhttps://h.example/a/-/merge_requests/9 - u\na!9 - s\nTP1-5 - third\n"
    entries, problems = SX.parse_list(text)
    check_eq("edge 3: the same key three times is one exclusion", problems, [])
    first = entries[0]
    check_eq("edge 3: the first line stands, every reason is kept in order (no word lost)",
             (first["line"], first["as_written"], first["reason"]), ([1, 4, 8], "TP1-5", "first | second | third"))
    check_eq("edge 3: the URL form and the short form of one MR are two exclusions", len(entries), 4)
    work, output = story()
    record = put_list(work, text)
    check_eq("edge 3: ids follow the merged order", [e["id"] for e in record["exclusions"]], ["X1", "X2", "X3", "X4"])
    match_both = [SX.matches(e, url="https://h.example/a/-/merge_requests/9") for e in record["exclusions"][2:]]
    check_eq("the two forms of one MR both match its one item", match_both, [True, True])
    _, inventory = collect(Jira({"TASK-1": {"description": "see https://h.example/a/-/merge_requests/9"}}), "TASK-1", output)
    row = media_rows(by_ref(inventory, "TASK-1"))[0]
    check_eq("one item, one mark: the first in line order is the one recorded", row["excluded_by"]["exclusion"], "X3")


def parse_ticket_itself():
    for label, line in (("the key", "TP1-13797 - r"), ("the key in lower case", "tp1-13797 - r"),
                        ("its browse link", JIRA + "/browse/TP1-13797 - r")):
        entries, problems = SX.parse_list(line + "\n", task_key="TP1-13797")
        check_eq(f"edge 4: {label} is the story's own ticket: a problem, never an exclusion (the AC carrier)",
                 (entries, [p["code"] for p in problems], problems[0]["entry"] if problems else "x"),
                 ([], ["own_ticket"], None))
    entries, problems = SX.parse_list("TP1-13289 - r\n", task_key="TP1-13797")
    check_eq("edge 4: any other ticket is fine", (len(entries), problems), (1, []))
    check_eq("with no task key known, nothing is refused as the own ticket", len(SX.parse_list("TP1-13797 - r\n")[0]), 1)


def size_at_and_beyond_64k():
    base = b"TP1-5 - r\n"
    pad = b"#" + b"x" * (65536 - len(base) - 2) + b"\n"
    at = base + pad
    check_eq("edge 17: the fixture is exactly 65,536 bytes", len(at), 65536)
    entries, problems = SX.parse_bytes(at)
    check_eq("edge 17: 65,536 bytes is a list", (len(entries), problems), (1, []))
    beyond = base + pad.replace(b"x", b"xx", 1)
    check_eq("edge 17: the fixture beyond is 65,537 bytes", len(beyond), 65537)
    entries, problems = SX.parse_bytes(beyond)
    check_eq("edge 17: 65,537 bytes is not a list: no entry, one fatal problem, the question of the right file",
             (entries, [p["code"] for p in problems], problems[0].get("fatal")), ([], ["too_large"], True))
    check_in("edge 17: the problem asks whether the right file was named", "right file", problems[0]["message"])


def utf16_refused():
    text = "TP1-5 - a reason\n"
    for label, data in (("UTF-16 with a BOM (Notepad)", text.encode("utf-16")), ("UTF-16 LE, no BOM", text.encode("utf-16-le")),
                        ("invalid UTF-8", b"TP1-5 - \xff\xfe\x80")):
        entries, problems = SX.parse_bytes(data)
        check_eq(f"{label}: nothing is guessed, one fatal problem", (entries, [p["code"] for p in problems],
                                                                    problems[0].get("fatal")), ([], ["not_utf8"], True))
    check_in("the problem says what to do", "UTF-8", SX.parse_bytes(text.encode("utf-16"))[1][0]["message"])
    root = temp_project("qa-sx-utf16-")
    try:
        task_root, _ = story_in_project(root)
        listing = task_root / "list.txt"
        listing.write_bytes(text.encode("utf-16"))
        result = sx_cli(root, "--task", "TASK-1", "--load", listing)
        check_eq("the CLI refuses a UTF-16 file with exit 2 and writes no record",
                 (result.returncode, (task_root / "work" / "source-exclusions.json").exists()), (2, False))
        listing.write_bytes(b"TP1-5 - r\n" + b"# " + b"x" * 70000)
        result = sx_cli(root, "--task", "TASK-1", "--load", listing)
        check_eq("the CLI refuses a file over 64 KiB the same way", (result.returncode, "right file" in result.stderr), (2, True))
    finally:
        cleanup(root)


# ---- P1: the matcher (section 4 and C6) ---------------------------------------------------------

def match_battery():
    jira_ref = JIRA + "/browse/TP1-13797"
    sha40 = "135699ae2" + "0" * 31
    cases = [
        # (label, word, item fields, expected) - "no match" rows first: a wrong match is the one error that matters
        ("`!19` is not iid 1924 (no prefix compare)", "testproject1-ui!19", {"url": MR_1924}, False),
        ("`ui!1924` is not project testproject1-ui (the tail needs a `/`)", "ui!1924", {"url": MR_1924}, False),
        ("`testproject1!1924` is not testproject1-ui", "testproject1!1924", {"url": MR_1924}, False),
        ("`TP1-1379` is not TP1-13797", "TP1-1379", {"canonical_ref": jira_ref}, False),
        ("`TP1-137977` is not TP1-13797", "TP1-137977", {"canonical_ref": jira_ref}, False),
        ("the same MR on another host (link word)", MR_1924, {"url": "https://gitlab.other.example/tp1-group/testproject1-ui/-/merge_requests/1924"}, False),
        ("a link word compares the FULL path: a shorter path is another project",
         "https://git.example/testproject1-ui/-/merge_requests/1924", {"url": MR_1924}, False),
        ("a link word compares the FULL path: a longer path is another project",
         MR_1924, {"url": "https://git.example/other/tp1-group/testproject1-ui/-/merge_requests/1924"}, False),
        ("a different query for kind url", "https://x.example/a?v=1", {"url": "https://x.example/a?v=2"}, False),
        ("a query against none for kind url", "https://x.example/a?v=1", {"url": "https://x.example/a"}, False),
        ("a trailing dot is another address for kind url", "https://x.example/a", {"url": "https://x.example/a."}, False),
        ("`https://evil/browse/TP1-13797` is not the jirahost instance", "https://evil.example/browse/TP1-13797",
         {"canonical_ref": jira_ref}, False),
        ("a GitHub /pull/1924 is not `testproject1-ui!1924` (the short form is GitLab only)", "testproject1-ui!1924",
         {"url": "https://github.com/tp1-group/testproject1-ui/pull/1924"}, False),
        ("an MR inside a `?next=` query is no MR", "testproject1-ui!1924",
         {"url": "https://git.example/users/sign_in?next=" + MR_1924}, False),
        ("an MR inside a `?next=` query is no MR (link word)", MR_1924,
         {"url": "https://git.example/users/sign_in?next=" + MR_1924}, False),
        ("an iid followed by a letter is no iid", "testproject1-ui!1924", {"url": MR_1924 + "abc"}, False),
        ("an iid followed by a digit is another iid", "testproject1-ui!192", {"url": MR_1924}, False),
        ("`PROJ-12` is not `MY_PROJ-12`", "PROJ-12", {"canonical_ref": JIRA + "/browse/MY_PROJ-12"}, False),
        ("a ticket word does not match a url field", "TP1-13797", {"url": jira_ref}, False),
        ("an item key with a long s is not the plain key", "PROS-12", {"canonical_ref": JIRA + "/browse/PROſ-12"}, False),
        ("a url word does not match a ticket ref", "https://x.example/a", {"canonical_ref": jira_ref}, False),
        ("a ref needs 12 hex: an 11-hex field is no match", sha40, {"sha": "135699ae200"}, False),
        ("a branch is compared exactly (case)", "branch:feature/x", {"branch": "feature/X"}, False),
        ("a branch is not a prefix match", "branch:feature/x", {"branch": "feature/x2"}, False),
        ("a ref word does not match a url field", sha40, {"url": MR_1924}, False),
        ("every keyword None", "testproject1-ui!1924", {}, False),
        # the rows that must match
        ("the escaped `merge\\_requests` of a tracker comment", "testproject1-ui!1924",
         {"url": "https://git.example/tp1-group/testproject1-ui/-/merge\\_requests/1924"}, True),
        ("the same item with `/diffs`", "testproject1-ui!1924", {"url": MR_1924 + "/diffs"}, True),
        ("the same item with `#note_1`", "testproject1-ui!1924", {"url": MR_1924 + "#note_1"}, True),
        ("the same item with a query", "testproject1-ui!1924", {"url": MR_1924 + "?diff_id=1"}, True),
        ("the same item with a trailing dot (extracted from prose)", "testproject1-ui!1924", {"url": MR_1924 + "."}, True),
        ("the same item with a trailing `**` (markdown)", "testproject1-ui!1924", {"url": MR_1924 + "**"}, True),
        ("a leading zero in the word", "testproject1-ui!01924", {"url": MR_1924}, True),
        ("the short form with its group", "tp1-group/testproject1-ui!1924", {"url": MR_1924}, True),
        ("the project in capitals (F2c)", "Testproject1-UI!1924", {"url": MR_1924}, True),
        ("the short form names a project of any group", "testproject1-ui!1924",
         {"url": "https://git.other.example/team/sub/testproject1-ui/-/merge_requests/1924"}, True),
        ("the link word, exact", MR_1924, {"url": MR_1924}, True),
        ("the link word with a host in capitals", "https://GIT.example/tp1-group/testproject1-ui/-/merge_requests/1924",
         {"url": MR_1924 + "/commits"}, True),
        ("the same MR spelled with and without the `/-/` of a GitLab path", "https://git.example/a/b/merge_requests/7",
         {"url": "https://git.example/a/b/-/merge_requests/7"}, True),
        ("a GitHub link word matches its own pull", "https://github.com/o/r/pull/12", {"url": "https://github.com/o/r/pull/12/files"}, True),
        ("the key in lower case (C6: upper-case first, then fullmatch)", "tp1-13797", {"canonical_ref": jira_ref}, True),
        ("the key, exact", "TP1-13797", {"canonical_ref": jira_ref}, True),
        ("a browse link of the same instance, host in capitals", "https://EXAMPLE.org/browse/tp1-13797?x=1",
         {"canonical_ref": jira_ref}, True),
        ("a url word with a trailing slash and a fragment", "https://x.example/a/#top", {"url": "https://X.example/a"}, True),
        ("a ref: 40 hex against an abbreviated 12-hex field", sha40, {"sha": sha40[:12]}, True),
        ("a ref: 12 hex against a full field", sha40[:12], {"sha": sha40}, True),
        ("a ref: a branch, exact", "branch:feature/x", {"branch": "feature/x"}, True),
    ]
    for label, word, fields, expected in cases:
        entries, problems = SX.parse_list(f"{word} {DASH} r\n") if word else ([], [])
        if not entries:
            check(f"match battery: `{word}` parses ({problems})", False)
            continue
        exclusion = dict(entries[0], id="X1", origin=SX.ORIGIN_PERSON, at="t", revoked_at=None)
        check_eq(f"match battery: {label}", SX.matches(exclusion, **fields), expected)
    # t-267 C11: `MY_PROJ-12` is ONE key now (the shared key shape takes the underscore), so the word is a
    # line that reads, matches its own ticket, and still never `PROJ-12`'s - the part-of-a-key bug is closed
    # on both sides.
    underscore = SX.parse_list("MY_PROJ-12 - r\n")
    check_eq("`MY_PROJ-12` is a ticket key: no problem line", [p["code"] for p in underscore[1]], [])
    word = dict(underscore[0][0], id="X1", origin=SX.ORIGIN_PERSON, at="t", revoked_at=None)
    check_eq("`MY_PROJ-12` matches its own ticket and not PROJ-12's",
             (SX.matches(word, canonical_ref=JIRA + "/browse/MY_PROJ-12"), SX.matches(word, canonical_ref=JIRA + "/browse/PROJ-12")),
             (True, False))
    # the record's own forms of the C2 fields
    mr = excl("testproject1-ui!1924")
    check_eq("C2: the target of an mr carries head_sha and branch, null until S0 resolves them",
             (mr["target"]["head_sha"], mr["target"]["branch"]), (None, None))
    check("C2: a null head_sha never matches a sha", not SX.matches(mr, sha=sha40))
    resolved = dict(mr, target=dict(mr["target"], head_sha=sha40, branch="feature/x"))
    check("C2: a resolved head_sha matches a field by prefix (12 hex or more)", SX.matches(resolved, sha=sha40[:12]))
    check("C2: and not an 11-hex prefix", not SX.matches(resolved, sha=sha40[:11]))
    check("C2: a resolved branch matches exactly", SX.matches(resolved, branch="feature/x"))
    check("C2: and not another", not SX.matches(resolved, branch="feature"))
    revoked = dict(excl("testproject1-ui!1924"), revoked_at="2026-09-30T20:00:00Z")
    check("a revoked exclusion names nothing", not SX.matches(revoked, url=MR_1924))
    check_eq("matches() on a malformed exclusion is a miss, never an error",
             [SX.matches(bad, url=MR_1924) for bad in (None, {}, {"target": None}, {"target": {"kind": "mr"}},
                                                      {"target": {"kind": "weird"}})], [False] * 5)


def record_shape():
    work, _ = story()
    data = ("# list\ntestproject1-ui!1924 " + DASH + " " + REASON_1924 + "\nTP1-13289 - parent of the precedent\n").encode("utf-8")
    entries, _ = SX.parse_bytes(data, "TASK-1")
    record = SX.write_record(work.parent, entries, "C:/list.txt", data)
    on_disk = json.loads((work / "source-exclusions.json").read_text(encoding="utf-8"))
    check_eq("the record on disk is the record returned", on_disk, record)
    check_eq("the record: schema, list file as given, hash of the bytes read",
             (record["schema_version"], record["list_file"], record["list_sha256"]),
             (1, "C:/list.txt", hashlib.sha256(data).hexdigest()))
    first = record["exclusions"][0]
    check_eq("the entry: id, origin, line, as_written, reason whole, by",
             (first["id"], first["origin"], first["line"], first["as_written"], first["reason"], first["by"]),
             ("X1", "person_before_run", 2, "testproject1-ui!1924", REASON_1924, "human"))
    check_eq("the entry: not revoked", (first["revoked_at"], first["revoked_by"], first["revoked_words"]), (None, None, None))
    check_not_in("C8: no doubts[] field (dropped)", "doubts", json.dumps(record))
    check_eq("live() is every entry that is not revoked, from the task root", [e["id"] for e in SX.live(work.parent)], ["X1", "X2"])
    check_eq("no record, no exclusions", SX.live(tmp()), [])
    check_eq("the same bytes loaded again change nothing (the record keeps its ids and its revocations)",
             SX.write_record(work.parent, entries, "C:/list.txt", data), record)
    try:
        SX.write_record(work.parent, entries[:1], "C:/other.txt", b"other bytes")
        check("a different list over a record is refused", False)
    except SX.ListRefused as exc:
        check_in("a different list over a record is refused, naming the door (--revoke)", "--revoke", str(exc))


def load_refused_after_inventory():
    root = temp_project("qa-sx-late-")
    try:
        task_root, output = story_in_project(root)
        output.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        listing = task_root / "list.txt"
        listing.write_text("TP1-5 - r\n", encoding="utf-8")
        result = sx_cli(root, "--task", "TASK-1", "--load", listing)
        check_eq("edge 8 (unit): --load after the inventory exists is refused, exit 3, nothing written",
                 (result.returncode, (task_root / "work" / "source-exclusions.json").exists()), (3, False))
        check_in("edge 8: the refusal names the source review as the door", "source review", result.stderr)
        try:
            SX.write_record(task_root, SX.parse_list("TP1-5 - r\n")[0], "l", b"x")
            check("edge 8: the library refuses too (no read-then-excluded state can arise)", False)
        except SX.ListRefused:
            check("edge 8: the library refuses too (no read-then-excluded state can arise)", True)
    finally:
        cleanup(root)


# ---- P1: the CLI --------------------------------------------------------------------------------

def cli_show_and_abbreviation():
    root = temp_project("qa-sx-cli-")
    try:
        task_root, _ = story_in_project(root)
        none = sx_cli(root, "--task", "TASK-1", "--show")
        check_eq("--show with no record: says so, exit 0", (none.returncode, "no list" in none.stdout), (0, True))
        listing = task_root / "list.txt"
        listing.write_text("testproject1-ui!1924 " + DASH + " " + REASON_1924 + "\nhello - r\n", encoding="utf-8")
        loaded = sx_cli(root, "--task", "TASK-1", "--load", listing)
        check_eq("--load: exit 0 with a problem line, the valid line applied", loaded.returncode, 0)
        check_in("--load: one console line per exclusion, the person's reason whole",
                 "Before the run you asked me not to read: testproject1-ui!1924 " + DASH + " \"" + REASON_1924 + "\"", loaded.stdout)
        check_in("--load: a line it could not read is printed as not applied, never silent", "not applied", loaded.stderr)
        shown = sx_cli(root, "--task", "TASK-1", "--show")
        check_eq("--show prints the record", json.loads(shown.stdout)["exclusions"][0]["as_written"], "testproject1-ui!1924")
        for bad in (("--show", "--load", listing), ()):
            result = sx_cli(root, "--task", "TASK-1", *bad)
            check_eq(f"exactly one of --load/--show/--revoke is required ({list(bad)})", result.returncode, 2)
        abbreviated = sx_cli(root, "--task", "TASK-1", "--rev", "X1", "--words", "w")
        check_eq("argparse takes no abbreviation: the guard's exact spelling is the whole door (`--rev` is refused)",
                 abbreviated.returncode, 2)
        # a real child process: argv parsing and exit code through a process boundary
        import os
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        child = run_script("source_exclusions.py", "--task", "TASK-1", "--show", env=env)
        check_eq("a real child: --show exits 0 and prints the record", (child.returncode, "X1" in child.stdout), (0, True))
    finally:
        cleanup(root)


def reason_and_words_are_any_utf8():
    """The reason and the revoke words are the person's own (the owner writes Russian): accepted,
    stored and shown byte for byte. Built with chr(): the test file itself stays ASCII."""
    import os
    word = "".join(chr(c) for c in (0x427, 0x435, 0x440, 0x43d, 0x43e, 0x432, 0x438, 0x43a))  # a Cyrillic word
    extra = chr(0x1F600) + chr(0x4E2D) + chr(0xE9) + chr(0x2014)  # emoji, CJK, e-acute, em dash
    reason = word + " MR " + extra + " " + word
    long_reason = (word + " ") * 40
    data = ("testproject1-ui!1924 - " + reason + "\nPROJ-7 - " + long_reason + "\n").encode("utf-8")
    entries, problems = SX.parse_bytes(data, "TASK-1")
    check_eq("utf-8 reason: parse_list accepts it whole", (problems, entries[0]["reason"]), ([], reason))
    root = temp_project("qa-sx-utf8-")
    try:
        task_root, output = story_in_project(root)
        listing = task_root / "list.txt"
        listing.write_bytes(data)
        loaded = sx_cli(root, "--task", "TASK-1", "--load", listing)
        record_bytes = (task_root / "work" / "source-exclusions.json").read_bytes()
        check_eq("utf-8 reason: --load exits 0 and prints it", (loaded.returncode, reason in loaded.stdout), (0, True))
        check_eq("utf-8 reason: the record file holds it as UTF-8, not escaped",
                 (reason.encode("utf-8") in record_bytes, b"\\u04" in record_bytes), (True, False))
        check_eq("utf-8 reason: the record round-trips", SX.read_record(task_root / "work")["exclusions"][0]["reason"], reason)
        check_in("utf-8 reason: --show prints it", reason, sx_cli(root, "--task", "TASK-1", "--show").stdout)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        child = run_script("source_exclusions.py", "--task", "TASK-1", "--show", env=env)
        check_eq("utf-8 reason: a real child process prints it too (pipe encoding)", (child.returncode, reason in child.stdout), (0, True))
        words = word + " " + extra
        done = sx_cli(root, "--task", "TASK-1", "--revoke", "X1", "--words", words)
        check_eq("utf-8 words: --revoke accepts them", done.returncode, 0)
        check_eq("utf-8 words: stored byte-equal in revoked_words", SX.read_record(task_root / "work")["exclusions"][0]["revoked_words"], words)
        _, inventory = collect(Jira({"TASK-1": {"description": "PROJ-7"}}), "TASK-1", output)
        row = next(r for r in SI.review_rows(inventory) if r["key"] == "PROJ-7")
        clipped = row["reason"][len('your word before the run: "'):-1]
        check_eq("utf-8 reason: the review table's clipped reason is at most 120 characters, the person's own words",
                 (118 <= len(clipped) <= 120, clipped.endswith("..."), long_reason.startswith(clipped[:-3])), (True, True, True))
        short = SX.read_record(task_root / "work")["exclusions"]
        check_eq("utf-8 reason: the long reason is stored whole, clipped nowhere", short[1]["reason"], long_reason.strip())
    finally:
        cleanup(root)


def revoke_cli_edges():
    root = temp_project("qa-sx-revoke-")
    try:
        task_root, output = story_in_project(root)
        work = task_root / "work"
        put_list(work, "testproject1-ui!1924 " + DASH + " " + REASON_1924 + "\nPROJ-7 - unrelated\n")
        unknown = sx_cli(root, "--task", "TASK-1", "--revoke", "X9", "--words", "read it")
        check_eq("--revoke of an id that does not exist: exit 2", unknown.returncode, 2)
        check_in("--revoke of an unknown id: the ids are listed", "X1 testproject1-ui!1924; X2 PROJ-7", unknown.stderr)
        no_words = sx_cli(root, "--task", "TASK-1", "--revoke", "X1")
        check_eq("--revoke without the person's words: exit 2, nothing changed", no_words.returncode, 2)
        before = (work / "source-exclusions.json").read_bytes()
        done = sx_cli(root, "--task", "TASK-1", "--revoke", "testproject1-ui!1924", "--words", "the recording is fine, read it")
        check_eq("--revoke by as_written: exit 0", done.returncode, 0)
        record = json.loads((work / "source-exclusions.json").read_text(encoding="utf-8"))
        first = record["exclusions"][0]
        check_eq("the entry stays with revoked_at, revoked_by and the words (the waiver precedent)",
                 (bool(first["revoked_at"]), first["revoked_by"], first["revoked_words"]),
                 (True, "human", "the recording is fine, read it"))
        check_eq("live() no longer has it", [e["id"] for e in SX.live(task_root)], ["X2"])
        after = (work / "source-exclusions.json").read_bytes()
        again = sx_cli(root, "--task", "TASK-1", "--revoke", "X1", "--words", "once more")
        check_eq("--revoke of an already revoked id: exit 0, a no-op that says so",
                 (again.returncode, "already revoked" in again.stdout), (0, True))
        check_eq("an already revoked id is left byte for byte", (work / "source-exclusions.json").read_bytes(), after)
        check("the first revoke did change the file", before != after)
        noprint = sx_cli(root, "--task", "TASK-1", "--revoke", "X2", "--words", "read it too")
        check_not_in("edge 14: S1 not completed: no door is printed (the scout's next handoff re-collects)",
                     "already completed", noprint.stdout)
    finally:
        cleanup(root)
    root = temp_project("qa-sx-revoke-late-")
    try:
        task_root, output = story_in_project(root)
        work = task_root / "work"
        put_list(work, "testproject1-ui!1924 " + DASH + " " + REASON_1924 + "\nPROJ-7 - unrelated\n")
        (task_root / "state").mkdir()
        (task_root / "state" / "controller.json").write_text(
            json.dumps({"stages": {"S1": {"status": "completed"}}}), encoding="utf-8")
        door = sx_cli(root, "--task", "TASK-1", "--revoke", "X1", "--words", "read it")
        check_eq("edge 14: S1 already completed: the revoke is recorded, exit 0, no refusal", door.returncode, 0)
        check_in("edge 14: and the door is printed, and says why it is needed", "already completed", door.stdout)
        check_in("edge 14: the door names what the exclusion's own target names (nothing was in the inventory)",
                 "testproject1-ui!1924", door.stdout)
        check_in("edge 14: the door names the late review, as a whole command", "review --output qa-factory/artifacts/TASK-1/work/"
                 "source-inventory.json --late", door.stdout)
        ticket = sx_cli(root, "--task", "TASK-1", "--revoke", "X2", "--words", "read it too")
        check_in("edge 14: for a ticket the door is a whole collect command",
                 'ticket_adapter.py" collect PROJ-7 --output qa-factory/artifacts/TASK-1/work/source-inventory.json '
                 "--relation referenced --summary", ticket.stdout)
        check_eq("edge 14: both revokes are on the record", [bool(e["revoked_at"]) for e in SX.read_record(work)["exclusions"]],
                 [True, True])
    finally:
        cleanup(root)


# ---- P2: the marks ------------------------------------------------------------------------------

def apply_mention_without_peek():
    work, output = story()
    put_list(work, "PROJ-7 " + DASH + " not this story\nzzz-3 " + DASH + " also not\n")
    client = Jira({"TASK-1": {"description": "see PROJ-7 and ZZZ-3 and OK-1"}})
    record, inventory = collect(client, "TASK-1", output)
    check_eq("the requested ticket is read as always", record["status"], "read")
    for key, how in (("PROJ-7", "a mention of a tracker project (a pending entry)"),
                     ("ZZZ-3", "a mention of an unproven prefix (an unavailable record the collector wrote)")):
        item = by_ref(inventory, key)
        check_eq(f"{how}: left out with no peek", (item["status"], item["relevance"]), ("excluded", "not_relevant"))
        check_eq(f"{how}: the reason is the person's word, in the two fields a reader looks at",
                 (item["relevance_reason"], item["exclusion_or_error"]),
                 ('left out before the run by the person\'s word: "' + ("not this story" if key == "PROJ-7" else "also not") + '"',) * 2)
        check_eq(f"{how}: excluded_by names the exclusion and its origin",
                 (item["excluded_by"]["origin"], item["assessment_ref"]), ("person_before_run", None))
    check_eq("an unmatched mention is what it always was", (by_ref(inventory, "OK-1")["status"], by_ref(inventory, "OK-1")["relevance"]),
             ("pending", "pending"))
    check_eq("no ticket of the list was asked for (only the task itself, and the projects of the prefixes)",
             [c for c in client.calls if c.startswith(("issue ", "comments ", "bytes ")) and "TASK-1" not in c], [])
    check_eq("the inventory is valid", SI.validate_inventory(inventory), [])


def apply_media_item():
    work, output = story()
    put_list(work, "testproject1-ui!1924 " + DASH + " " + REASON_1924 + "\n")
    other = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/5"
    _, inventory = collect(Jira({"TASK-1": {"description": "see " + other, "comments": [COMMENT_15045]}}), "TASK-1", output)
    rows = {row["url"]: row for row in media_rows(by_ref(inventory, "TASK-1"))}
    check_eq("a matched item is excluded, marked by the exclusion", (rows[MR_1924]["status"], rows[MR_1924]["excluded_by"]["exclusion"]),
             ("excluded", "X1"))
    check_eq("an item the list does not name is pending as always", (rows[other]["status"], "excluded_by" in rows[other]), ("pending", False))
    check_eq("the block is recomputed without the excluded item: the other one keeps it pending",
             by_ref(inventory, "TASK-1")["materials"]["external_media"]["status"], "pending")
    check_eq("the block's count is what the ticket carried", by_ref(inventory, "TASK-1")["materials"]["external_media"]["count"], 2)
    # an item that is somehow already read keeps its bytes' record
    data = json.loads(output.read_text(encoding="utf-8"))
    row = media_rows(by_ref(data, "TASK-1"))[0]
    row.pop("excluded_by", None)
    row.update(status="read", local_ref="sources/x/mr.json", content_hash="abc")
    row["url"] = MR_1924 if row["url"] != MR_1924 else row["url"]
    SI.apply_exclusion_marks(data["sources"], SX.live(work.parent))
    row = next(r for r in media_rows(by_ref(data, "TASK-1")) if r["url"] == MR_1924)
    check_eq("an excluded item that is somehow read: the mark is applied and local_ref stays (the record never lies about bytes)",
             (row["status"], row["local_ref"], row["content_hash"]), ("excluded", "sources/x/mr.json", "abc"))


def block_all_excluded_is_read():
    f = SI._media_group_status
    e, p, r, u, a = {"status": "excluded"}, {"status": "pending"}, {"status": "read"}, {"status": "unavailable"}, {"status": "partial"}
    check_eq("edge 12: every item excluded: the block is read", f([e, e]), "read")
    check_eq("edge 12: one item, excluded: read", f([e]), "read")
    check_eq("an excluded item does not hold a pending block any shorter", f([e, p]), "pending")
    check_eq("an excluded item does not make a block unavailable", f([e, u]), "unavailable")
    check_eq("an excluded item does not make a block partial", f([e, a]), "partial")
    check_eq("an excluded item beside a read one: read", f([e, r]), "read")
    check_eq("no items at all is read, as before", f([]), "read")
    check_eq("an excluded item is no more unsettled than absent (pending beside unavailable)", f([e, p, u]), f([p, u]))
    work, output = story()
    put_list(work, "testproject1-ui!1924 - r\n")
    _, inventory = collect(Jira({"TASK-1": {"comments": [COMMENT_15045]}}), "TASK-1", output)
    check_eq("edge 12 through the collector: every item excluded, the block is read although nothing was read",
             (by_ref(inventory, "TASK-1")["materials"]["external_media"]["status"],
              [r["status"] for r in media_rows(by_ref(inventory, "TASK-1"))]), ("read", ["excluded"]))


def reviewed_complete_inventory(work, output, description_or_comments):
    """A story whose task source is read, inspected and reviewed, so that `complete` is true unless a
    marked item breaks it."""
    record, inventory = collect(Jira({"TASK-1": description_or_comments}), "TASK-1", output)
    SI.record_relevance_assessment(output, record["source_id"], "relevant", "the task", record["assessment_ref"])
    SI.record_source_review(output, "agreed")
    return SI.load_inventory(output)


def completeness_unchanged_by_excluded():
    work, output = story()
    put_list(work, "testproject1-ui!1924 - r\n")
    with_item = reviewed_complete_inventory(work, output, {"comments": [COMMENT_15045]})
    work2, output2 = story()
    without_item = reviewed_complete_inventory(work2, output2, {"comments": ["nothing to see"]})
    a, b = SI.completeness(with_item), SI.completeness(without_item)
    keys = ("complete", "gate_blocked", "pending", "unavailable", "incomplete_materials", "unavailable_materials",
            "accepted_gaps", "review_missing", "unreviewed", "awaiting_review", "open_points", "closed_by_person")
    check_eq("F7: an excluded item changes no blocking list of completeness (same as a story that never had it)",
             {k: a[k] for k in keys}, {k: b[k] for k in keys})
    check_eq("F7: and the story is complete", (a["complete"], a["gate_blocked"]), (True, False))
    check_eq("F7: the excluded item is listed, informationally", a["left_out_by_word"],
             {with_item["sources"][0]["source_id"]: [MR_1924]})
    check_eq("F7: a story that left nothing out lists nothing (an empty map, not absence)", b["left_out_by_word"], {})
    with_item_closed = SI.completeness(with_item, s1_closed=True)
    check_eq("F7: and s1_closed changes nothing about it", (with_item_closed["complete"], with_item_closed["left_out_by_word"]),
             (True, a["left_out_by_word"]))
    # the gap points: an excluded item is no point, inside a block that has another reason to be partial
    item = json.loads(json.dumps(with_item["sources"][0]))
    rows = media_rows(item)
    rows.append({"url": "https://x.example/other", "status": "partial", "content_hash": "h", "local_ref": "r",
                 "error": "auth_required: half", "cause": "auth_required"})
    item["materials"]["external_media"]["status"] = SI._media_group_status(rows)
    points = SI.gap_points(item)
    check_eq("an excluded item makes no gap point even inside a partial block",
             [p["name"] for p in points if p["kind"] == "media"], ["https://x.example/other"])


def left_out_listed():
    work, output = story()
    put_list(work, "PROJ-7 - x\ntestproject1-ui!1924 - r\n")
    _, inventory = collect(Jira({"TASK-1": {"description": "PROJ-7", "comments": [COMMENT_15045]}}), "TASK-1", output)
    left = SI.completeness(inventory)["left_out_by_word"]
    task_id, proj_id = by_ref(inventory, "TASK-1")["source_id"], by_ref(inventory, "PROJ-7")["source_id"]
    check_eq("left_out_by_word: {source_id: [keys or urls]} for a ticket and for an item", left,
             {task_id: [MR_1924], proj_id: ["PROJ-7"]})


def no_file_identical():
    def run(base, with_record):
        work, output = story(base)
        if with_record == "empty":
            put_list(work, "# nothing\n")
        record = {"source_id": "SRC-a1", "canonical_ref": "https://jira.invalid/browse/APP-1", "relation": "task",
                  "relevance": "relevant", "relevance_reason": "x", "assessment_ref": None, "discovered_from": None,
                  "relation_evidence": None, "required": True, "status": "read", "revision": "r1", "content_hash": "h",
                  "snapshot_ref": "s", "fetched_at": "t", "exclusion_or_error": None, "inspection_status": "pending",
                  "inspection_ref": None, "_refresh_result": "new",
                  "materials": {"comments": {"status": "read", "count": 0},
                                "attachments": {"status": "read", "count": 0, "items": []},
                                "external_media": {"status": "pending", "count": 2, "items": [
                                    {"url": "https://git.example/tp1-group/testproject1/-/merge\\_requests/3890",
                                     "status": "pending", "content_hash": None, "local_ref": None, "error": None},
                                    {"url": MR_1924, "status": "unavailable", "content_hash": None, "local_ref": None,
                                     "error": "auth_required: sso", "cause": "auth_required"}]}},
                  "mentioned_ticket_keys": ["BUG-2"]}
        SI.update_inventory(output, record)
        return output.read_bytes()
    none = run(tmp(), None)
    empty = run(tmp(), "empty")
    check("temporal, before: with no record file the output carries no mark of the feature",
          b"excluded_by" not in none and b"left_out" not in none)
    check_eq("temporal: an empty record file gives the same bytes as no record file (hash)",
             (hashlib.sha256(empty).hexdigest(), hashlib.sha256(none).hexdigest()),
             (hashlib.sha256(none).hexdigest(),) * 2)


def corrupt_file_refuses():
    for label, text in (("not JSON", "{not json"), ("schema_version 2", json.dumps({"schema_version": 2, "exclusions": []})),
                        ("exclusions not a list", json.dumps({"schema_version": 1, "exclusions": {}})),
                        ("an entry with no target", json.dumps({"schema_version": 1, "exclusions": [{"id": "X1"}]})),
                        ("a list, not an object", "[]")):
        work, output = story()
        (work / "source-exclusions.json").write_text(text, encoding="utf-8")
        seed = {"schema_version": 1, "sources": []}
        output.write_text(json.dumps(seed), encoding="utf-8")
        before = output.read_bytes()
        record = {"source_id": "SRC-1", "canonical_ref": "https://jira.invalid/browse/APP-1", "relation": "task",
                  "relevance": "relevant", "relevance_reason": "x", "assessment_ref": None, "discovered_from": None,
                  "relation_evidence": None, "required": True, "status": "read", "revision": "r", "content_hash": "h",
                  "snapshot_ref": "s", "fetched_at": "t", "exclusion_or_error": None, "inspection_status": "read",
                  "inspection_ref": None, "materials": {}, "mentioned_ticket_keys": []}
        try:
            SI.update_inventory(output, record)
            check(f"edge 13, {label}: update_inventory refuses", False)
        except SX.ExclusionRecordError as exc:
            check_in(f"edge 13, {label}: the refusal names the file", "source-exclusions.json", str(exc))
            check_in(f"edge 13, {label}: and the fix (restore from --show, or remove the file)", "remove the file", str(exc))
            check_eq(f"edge 13, {label}: nothing was written (errs toward refusing, never toward ignoring the word)",
                     output.read_bytes(), before)
        client = Jira({"APP-1": {}}, raising=True)
        try:
            SI.collect_jira_source(client, "APP-1", output)
            check(f"edge 13, {label}: collect refuses", False)
        except SX.ExclusionRecordError:
            check_eq(f"edge 13, {label}: collect refuses before any client call", client.calls, [])
        except AssertionError as exc:
            check(f"edge 13, {label}: collect refuses before any client call", False, str(exc))


def refresh_keeps_mark():
    work, output = story()
    put_list(work, "testproject1-ui!1924 - r\n")
    client = Jira({"TASK-1": {"comments": [COMMENT_15045]}})
    record, inventory = collect(client, "TASK-1", output)
    SI.record_relevance_assessment(output, record["source_id"], "relevant", "the task", record["assessment_ref"])
    result = SI.refresh_relevant_sources(client, output)
    item = by_ref(result["inventory"], "TASK-1")
    check_eq("an exclusion survives `refresh` (the re-collect resets the item, the mark is reapplied in the same write)",
             (media_rows(item)[0]["status"], media_rows(item)[0]["excluded_by"]["exclusion"]), ("excluded", "X1"))
    check_eq("and the block stays read", item["materials"]["external_media"]["status"], "read")
    check_eq("and it is on disk", json.loads(output.read_text(encoding="utf-8"))["sources"][0]["materials"]["external_media"]["items"][0]["status"],
             "excluded")


def revoke_restores_pending():
    work, output = story()
    put_list(work, "testproject1-ui!1924 - r\nPROJ-7 - x\n")
    client = Jira({"TASK-1": {"description": "PROJ-7", "comments": [COMMENT_15045]}})
    collect(client, "TASK-1", output)
    record = SX.revoke(work.parent, "X1", "read it")
    check_eq("revoke: the item is reported restored", record["restored"], [{"source_id": by_ref(SI.load_inventory(output), "TASK-1")["source_id"], "url": MR_1924}])
    inventory = SI.load_inventory(output)
    row = media_rows(by_ref(inventory, "TASK-1"))[0]
    check_eq("edge 14: the media item goes back to pending", (row["status"], "excluded_by" in row), ("pending", False))
    check_eq("edge 14: the mark is kept as history with revoked_at", (row["excluded_by_history"][0]["exclusion"],
                                                                       bool(row["excluded_by_history"][0]["revoked_at"])), ("X1", True))
    check_eq("edge 14: the block status is recomputed (pending now)", by_ref(inventory, "TASK-1")["materials"]["external_media"]["status"],
             "pending")
    proj = by_ref(inventory, "PROJ-7")
    check_eq("the other exclusion is untouched", (proj["status"], proj["excluded_by"]["exclusion"]), ("excluded", "X2"))
    SX.revoke(work.parent, "PROJ-7", "and this one")
    proj = by_ref(SI.load_inventory(output), "PROJ-7")
    check_eq("a mentioned ticket with no snapshot goes back to pending, waiting for an assessment",
             (proj["relevance"], proj["status"], proj["relevance_reason"], "excluded_by" in proj),
             ("pending", "pending", "mentioned source requires assessment", False))
    check_eq("edge 14: a revoke in the library works whatever the stage (it only records and restores)",
             SX.revoke(work.parent, "X1", "again")["status"], "already")


def revoked_not_recreated():
    work, output = story()
    put_list(work, "testproject1-ui!1924 - r\nPROJ-7 - x\n")
    client = Jira({"TASK-1": {"description": "PROJ-7", "comments": [COMMENT_15045]}})
    record, _ = collect(client, "TASK-1", output)
    SX.revoke(work.parent, "X1", "read it")
    SX.revoke(work.parent, "X2", "and this")
    SI.record_relevance_assessment(output, record["source_id"], "relevant", "the task", record["assessment_ref"])
    result = SI.refresh_relevant_sources(client, output)
    item = by_ref(result["inventory"], "TASK-1")
    check_eq("edge 14: a re-collect after a revoke does not re-mark the item (a revoked exclusion is never re-created)",
             (media_rows(item)[0]["status"], "excluded_by" in media_rows(item)[0]), ("pending", False))
    again, inventory = collect(client, "TASK-1", output, existing_record=None)
    check_eq("edge 14: nor a mention", (by_ref(inventory, "PROJ-7")["status"], "excluded_by" in by_ref(inventory, "PROJ-7")),
             ("pending", False))
    peeked = SI.peek_jira_source(Jira({"PROJ-7": {}}), "PROJ-7", output)
    check_eq("edge 14: nor a peek after a revoke (the ticket is fetched again)", peeked["status"], "pending")


def inspect_refused():
    work, output = story()
    put_list(work, "testproject1-ui!1924 " + DASH + " " + REASON_1924 + "\n")
    _, inventory = collect(Jira({"TASK-1": {"comments": [COMMENT_15045]}}), "TASK-1", output)
    source_id = by_ref(inventory, "TASK-1")["source_id"]
    before = output.read_bytes()
    (work / "x.json").write_text("{}", encoding="utf-8")
    for status, reason, local_ref in (("read", "", "x.json"), ("unavailable", "auth_required: sso", ""), ("partial", "auth_required: half", "x.json")):
        try:
            SI.record_external_media(output, source_id, MR_1924, status, reason, local_ref)
            check(f"a receipt `{status}` for an excluded item is refused", False)
        except ValueError as exc:
            message = str(exc)
            check_in(f"a `{status}` receipt is refused, naming the url", "`" + MR_1924 + "`", message)
            check_in(f"a `{status}` refusal carries the person's reason", '("' + REASON_1924 + '")', message)
            check_in(f"a `{status}` refusal names the door the role has (its handoff) and the person's review", "handoff", message)
            check_not_in("the refusal has no --doubt sentence (C8)", "--doubt", message)
    check_eq("nothing was written", output.read_bytes(), before)
    root = temp_project("qa-sx-inspect-")
    try:
        task_root, out2 = story_in_project(root)
        put_list(task_root / "work", "testproject1-ui!1924 - r\n")
        collect(Jira({"TASK-1": {"comments": [COMMENT_15045]}}), "TASK-1", out2)
        sid = by_ref(SI.load_inventory(out2), "TASK-1")["source_id"]
        result = ta_cli(root, Jira(), "inspect", "--output", out2, "--source-id", sid, "--media-url", MR_1924,
                        "--inspection-status", "unavailable", "--reason", "auth_required: sso")
        check_eq("`inspect --media-url` refuses through the library: exit 3", result.returncode, 3)
        check_in("`inspect --media-url` says why", "the person asked before the run", result.stderr)
    finally:
        cleanup(root)


def assess_relevant_refused_notrelevant_noop():
    work, output = story()
    put_list(work, "PROJ-7 " + DASH + " " + REASON_1924 + "\n")
    _, inventory = collect(Jira({"TASK-1": {"description": "PROJ-7"}}), "TASK-1", output)
    source_id = by_ref(inventory, "PROJ-7")["source_id"]
    before = output.read_bytes()
    try:
        SI.record_relevance_assessment(output, source_id, "relevant", "the scout thinks so", "sources/x/assessment/ticket.json")
        check("`relevant` on a left-out source is refused", False)
    except ValueError as exc:
        check_in("`relevant` is refused with the person's reason", REASON_1924, str(exc))
        check_in("`relevant` is refused with the door (the handoff)", "handoff", str(exc))
        check_in("and says only the person can take it back", "Only the person", str(exc))
    check_eq("`relevant`: nothing was written", output.read_bytes(), before)
    for verdict in ("not_relevant", "unknown"):
        err = io.StringIO()
        with redirect_stderr(err):
            result = SI.record_relevance_assessment(output, source_id, verdict, "my own reason", "sources/x/assessment/ticket.json")
        check_eq(f"`{verdict}` does nothing: the inventory and the file are as they were",
                 (output.read_bytes(), by_ref(result, "PROJ-7")["relevance_reason"].startswith(SI.LEFT_OUT_PREFIX)), (before, True))
        check_in(f"`{verdict}` says it is already left out by the person's word", "already left out by the person's word", err.getvalue())


def review_row_texts():
    long_reason = "Draft MR of an earlier factory run, " + "not a product change " * 12
    work, output = story()
    put_list(work, "PROJ-7 " + DASH + " " + long_reason + "\ntestproject1-ui!1924 - r\n")
    _, inventory = collect(Jira({"TASK-1": {"description": "PROJ-7", "comments": [COMMENT_15045]}}), "TASK-1", output)
    rows = SI.review_rows(inventory)
    proj = next(r for r in rows if r["key"] == "PROJ-7")
    check_eq("the decision reads `left out by you (before the run)`", proj["decision"], "left out by you (before the run)")
    check("the reason reads `your word before the run: \"<reason clipped 120>\"`",
          proj["reason"].startswith('your word before the run: "Draft MR') and proj["reason"].endswith('..."'))
    inner = proj["reason"][len('your word before the run: "'):-1]
    check_eq("the reason is clipped to 120 characters", len(inner), 120)
    text = SI.render_review(rows)
    check_in("the table shows the decision", "left out by you (before the run)", text)
    task = next(r for r in rows if r["key"] == "TASK-1")
    check_in("a source's excluded media are listed in its open points cell",
             "external material git.example", task["left_out_media"][0])
    check_in("...with the words 'left out by your word before the run'", ": left out by your word before the run", task["left_out_media"][0])
    check_in("...inside the rendered table row of the carrier", "left out by your word before the run", text.split("| TASK-1")[1])
    check_eq("the excluded ticket sorts after the kept one", [r["decision"] for r in rows],
             ["kept", "left out by you (before the run)"])
    check_eq("an excluded source has no open point to accept", proj["points"], [])


def replay_15045_comment():
    """The M3 replay: the comment of TP1-15045 that carries the draft-MR link, a person's list that
    names it by the short form, the collector run against a fake Jira, a fetch stub for the MR's bytes."""
    root = tmp()
    work, output = story(root)
    listing = "testproject1-ui!1924 " + DASH + " " + REASON_1924 + "\n"
    record = put_list(work, listing, task_key="TP1-15045")
    mr_fetches = []

    class Jira15045(Jira):
        def get_bytes(self, url):
            mr_fetches.append(url)
            raise AssertionError("the MR's bytes were fetched")

    client = Jira15045({"TP1-15045": {"description": "h2. Acceptance Criteria\n* AC-1 the diff is coloured",
                                          "comments": [COMMENT_15045]}}, base_url=JIRA)
    _, inventory = collect(client, "TP1-15045", output)
    task = by_ref(inventory, "TP1-15045")
    item = media_rows(task)[0]
    check_eq("M3 replay: the inventory item for the MR of the comment comes out `excluded`",
             (item["url"], item["status"], item["excluded_by"]["exclusion"]), (MR_1924, "excluded", "X1"))
    check_eq("M3 replay: the fetch stub was never called", mr_fetches, [])
    check_eq("M3 replay: the task ticket itself was read", task["status"], "read")
    check_eq("M3 replay: nothing else of the comment was left out", len(media_rows(task)), 1)
    source_id = task["source_id"]
    try:
        SI.record_external_media(output, source_id, MR_1924, "read", "", "x.json")
        check("M3 replay: the scout's own receipt for it is refused", False)
    except ValueError as exc:
        check_in("M3 replay: the scout's own receipt for it is refused, with the person's reason", REASON_1924, str(exc))
    print("M3 replay: record file written (work/source-exclusions.json), quoted:")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    print("M3 replay: inventory item:")
    print(json.dumps(item, indent=2, ensure_ascii=False))


# ---- P3: the library doors ----------------------------------------------------------------------

def collect_matched_no_fetch():
    work, output = story()
    put_list(work, "PROJ-7 " + DASH + " not this story\n")
    client = Jira({"PROJ-7": {"description": "see https://x.example/y"}}, raising=True)
    try:
        record = SI.collect_jira_source(client, "PROJ-7", output, relation="normative")
    except AssertionError as exc:
        check("edge (positional): a matched ticket is not fetched, by any call", False, str(exc))
        return
    check_eq("edge (positional): a matched ticket is not fetched, by any call (a fake that raises saw none)", client.calls, [])
    check_eq("the library answers with the left-out record, with the requested relation",
             (record["status"], record["relevance"], record["relation"], record["excluded_by"]["exclusion"]),
             ("excluded", "not_relevant", "normative", "X1"))
    inventory = SI.update_inventory(output, record)
    check_eq("it is written through update_inventory", by_ref(inventory, "PROJ-7")["status"], "excluded")
    check_eq("the parent or normative ticket named in the list is excluded too (the person's word outranks the scout's default)",
             by_ref(inventory, "PROJ-7")["relation"], "normative")
    live_client = Jira({"OTHER-1": {"description": "x"}})
    other = SI.collect_jira_source(live_client, "OTHER-1", output, relation="referenced")
    check_eq("a ticket the list does not name is collected as always", (other["status"], live_client.calls != []), ("read", True))


def peek_matched_no_fetch():
    work, output = story()
    put_list(work, "PROJ-7 " + DASH + " not this story\n")
    client = Jira({}, raising=True)
    try:
        record = SI.peek_jira_source(client, "PROJ-7", output, discovered_from="SRC-a", relation_evidence="sources/a/ticket.json")
    except AssertionError as exc:
        check("a matched ticket is not peeked: no call", False, str(exc))
        return
    check_eq("a matched ticket is not peeked: no call", client.calls, [])
    check_eq("the peek answers with the left-out record, keeping who found it",
             (record["status"], record["relevance"], record["discovered_from"], record["assessment_ref"]),
             ("excluded", "not_relevant", "SRC-a", None))
    other = SI.peek_jira_source(Jira({"OTHER-1": {}}), "OTHER-1", output)
    check_eq("an unmatched ticket is peeked as always", other["status"], "pending")


def stderr_line_per_mark():
    root = temp_project("qa-sx-stderr-")
    try:
        task_root, output = story_in_project(root)
        put_list(task_root / "work", "PROJ-7 " + DASH + " not this story\nzzz-3 - x\ntestproject1-ui!1924 - r\n")
        client = Jira({"TASK-1": {"description": "PROJ-7 ZZZ-3 OK-1", "comments": [COMMENT_15045]}})
        result = ta_cli(root, client, "collect", "TASK-1", "--output", output, "--relation", "task")
        lines = [l for l in result.stderr.splitlines() if l.startswith("left out by the person's word before the run")]
        check_eq("collect exits 0", result.returncode, 0)
        check_eq("one stderr line per newly applied mark (two tickets and one item), no more",
                 sorted(l.split(" \u2014 ")[0].rsplit(": ", 1)[1] for l in lines), sorted(["PROJ-7", "ZZZ-3", MR_1924]))
        check_in("the line carries the person's reason and says nothing was fetched", '"not this story"; nothing was fetched',
                 "\n".join(lines))
        again = ta_cli(root, Jira({"TASK-1": {"description": "PROJ-7 ZZZ-3 OK-1", "comments": [COMMENT_15045]}}),
                       "collect", "TASK-1", "--output", output, "--relation", "task")
        check_not_in("a re-collect says nothing about a mark that is not new", "left out by the person's word", again.stderr)
    finally:
        cleanup(root)


def json_stdout_pure():
    root = temp_project("qa-sx-json-")
    try:
        task_root, output = story_in_project(root)
        put_list(task_root / "work", "PROJ-7 " + DASH + " not this story\n")
        client = Jira({"TASK-1": {"description": "see PROJ-7"}})
        result = ta_cli(root, client, "collect", "TASK-1", "--output", output, "--relation", "task", "--json")
        data = json.loads(result.stdout)
        check_eq("--json: stdout is pure JSON (the inventory) and the line went to stderr",
                 (result.returncode, bool(data["sources"]), "left out by the person's word" in result.stderr), (0, True, True))
        raising = Jira({}, raising=True)
        for command in (["collect", "PROJ-7", "--relation", "referenced"], ["peek", "PROJ-7"]):
            res = ta_cli(root, raising, *command, "--output", output, "--json")
            check_eq(f"{command[0]} of a left-out key with --json: exit 0, no fetch, stdout pure JSON",
                     (res.returncode, raising.calls, isinstance(json.loads(res.stdout), dict)), (0, [], True))
            check_in(f"{command[0]}: the line for the requested ticket is printed to stderr, even though the mark is not new",
                     "left out by the person's word before the run: PROJ-7 \u2014 \"not this story\"; nothing was fetched", res.stderr)
        plain = ta_cli(root, raising, "collect", "PROJ-7", "--output", output, "--relation", "referenced")
        check_eq("collect, plain: a `referenced` ticket that is left out is not sent to `assess` first (exit 0)",
                 (plain.returncode, "assess" in plain.stderr), (0, False))
    finally:
        cleanup(root)


def judge_sources_peek_excluded_no_fetch():
    import judge_sources
    work, output = story()
    (work / "sources" / "SRC-TASK" / "r1").mkdir(parents=True)
    (work / "sources" / "SRC-TASK" / "r1" / "ticket.json").write_text(json.dumps(
        {"key": "TASK-1", "type": "Story", "title": "t", "description": "d", "acceptance_criteria": "a"}), encoding="utf-8")
    pending = {"source_id": SI.stable_source_id("https://jira.invalid", "https://jira.invalid/browse/PROJ-7"),
               "canonical_ref": "https://jira.invalid/browse/PROJ-7", "relation": "referenced", "relevance": "pending",
               "relevance_reason": "mentioned source requires assessment", "assessment_ref": None, "discovered_from": "SRC-TASK",
               "relation_evidence": None, "required": True, "status": "pending", "revision": None, "content_hash": None,
               "snapshot_ref": None, "fetched_at": "t", "exclusion_or_error": None, "inspection_status": "pending",
               "inspection_ref": None, "materials": {"comments": {"status": "unknown", "count": None},
                                                     "attachments": {"status": "unknown", "count": None, "items": []}},
               "mentioned_ticket_keys": []}
    task = {"source_id": "SRC-TASK", "canonical_ref": "https://jira.invalid/browse/TASK-1", "relation": "task",
            "relevance": "relevant", "relevance_reason": "the task", "assessment_ref": "sources/SRC-TASK/r1/ticket.json",
            "discovered_from": None, "relation_evidence": None, "required": True, "status": "read", "revision": "r1",
            "content_hash": "h", "snapshot_ref": "sources/SRC-TASK/r1/ticket.json", "fetched_at": "t", "exclusion_or_error": None,
            "inspection_status": "read", "inspection_ref": None,
            "materials": {"comments": {"status": "read", "count": 0}, "attachments": {"status": "read", "count": 0, "items": []},
                          "external_media": {"status": "read", "count": 0, "items": []}}, "mentioned_ticket_keys": []}
    # An inventory written by something that did not know the list (a pending mention), and a record that
    # names it: the judge's own peek must still not fetch it.
    output.write_text(json.dumps({"schema_version": 1, "sources": [task, pending]}), encoding="utf-8")
    SX._write(work, {"schema_version": 1, "list_file": "l", "list_sha256": "x", "loaded_at": "t", "exclusions": [
        {"id": "X1", "origin": "person_before_run", "line": 1, "as_written": "PROJ-7", "reason": "not this story",
         "target": {"kind": "ticket", "key": "PROJ-7", "host": None}, "by": "human", "at": "t", "revoked_at": None,
         "revoked_by": None, "revoked_words": None}]})
    client = Jira({}, raising=True)
    saved = (judge_sources.judge.settings, judge_sources.judge.active, judge_sources._client)
    judge_sources.judge.settings = lambda path: {"provider": "typesafe", "mode": "on", "model": "m"}
    judge_sources.judge.active = lambda cfg, name: name == "source_relevant"
    judge_sources._client = lambda: client
    try:
        report = judge_sources.run(output, "TASK-1")
    finally:
        judge_sources.judge.settings, judge_sources.judge.active, judge_sources._client = saved
    check_eq("judge_sources peeks the left-out mention in code, and no fetch happens (a fake that raises saw none)",
             (client.calls, report["peeked"]), ([], 1))
    item = by_ref(SI.load_inventory(output), "PROJ-7")
    check_eq("the mention comes out excluded by the person's word, not pending", (item["status"], item["excluded_by"]["exclusion"]),
             ("excluded", "X1"))


# ---- t-193: the net beyond the inventory, on the shapes the critic measured (t-192) ---------------------------

HEAD_1924 = "135699ae2c182eccd49ba6c66f469fc1c55359f1"
HEAD_1881 = "e6532059cc2a965c0a37ba1a40cd481652d40481"
DRAFT_BRANCH = "TP1-15045-visual-workflow-diff-validation"


def shapes_story():
    """A story whose list names MR 1924 (head resolved, as S0 does) and the draft's branch: (task root, work)."""
    work, _output = story()
    put_list(work, f"testproject1-ui!1924 {DASH} {REASON_1924}\nbranch:{DRAFT_BRANCH} {DASH} the branch of that draft MR\n")
    record = SX.read_record(work)
    record["exclusions"][0]["target"]["head_sha"] = HEAD_1924
    SX._write(work, record)
    return work.parent, work


def receipt_named(task_root, name, content):
    """Does the receipt scan name `work/receipts/<name>` for this content (str or bytes)."""
    path = task_root / "work" / "receipts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    try:
        errors = [e for e in SX.manifest_problems(task_root, {}) if e.startswith("source-inventory.json: ")]
    finally:
        path.unlink()
    return any(f"work/receipts/{name} holds" in e for e in errors)


def manifest_shapes_battery():
    """B-231 fix 1: the shapes the critic measured on real artifacts of the judge run, in one table (shape, hit?).
    The matcher errs toward MISSING: a same-project mention that only holds the digits is never a hit."""
    task_root, _work = shapes_story()
    cited = lambda manifest: any(" cites " in e for e in SX.manifest_problems(task_root, manifest))
    impl = lambda **fields: {"implementations": [dict({"repo": "testproject1-ui"}, **fields)]}
    ref = lambda text: {"requirement_sources": [{"ref": text}]}
    pad = 4096 - len(MR_1924) - 1
    rows = [
        # (shape, kind of carrier, payload, expected hit)
        ("manifest: a glab `sha` that is the excluded head", "m", impl(sha=HEAD_1924), True),
        ("manifest: a glab `web_url` that is the merge request's link", "m", impl(web_url=MR_1924), True),
        ("manifest: `diff_refs.head_sha` one level down", "m", impl(diff_refs={"head_sha": HEAD_1924}), True),
        ("manifest: `diff_refs` that is not an object", "m", impl(diff_refs=HEAD_1924), False),
        ("manifest: `diff_refs.head_sha` of another merge request", "m", impl(diff_refs={"head_sha": HEAD_1881}), False),
        ("manifest: a branch as a remote lists it, `origin/<branch>`", "m", impl(branch="origin/" + DRAFT_BRANCH), True),
        ("manifest: `origin/main` is not the excluded branch", "m", impl(branch="origin/main"), False),
        ("manifest: a commit of 9 hex characters that is not a prefix of the head", "m", impl(commit="deadbeef1"), False),
        ("ref: `tp1-group/testproject1-ui!1924`", "m", ref("tp1-group/testproject1-ui!1924"), True),
        ("ref: `MR !1924 (testproject1-ui)`", "m", ref("MR !1924 (testproject1-ui)"), True),
        ("ref: the bare branch name", "m", ref(DRAFT_BRANCH), True),
        ("ref: the branch as `origin/<name>`", "m", ref("origin/" + DRAFT_BRANCH + " (draft)"), True),
        ("ref: the head, 12 hex characters, then words", "m", ref(HEAD_1924[:12] + " (the draft)"), True),
        ("ref: `!1924` with ANOTHER project's tail", "m", ref("MR !1924 (testproject1-backend)"), False),
        ("ref: `testproject1-ui!1924` inside another tail (`old-testproject1-ui`)", "m", ref("MR !1924 (old-testproject1-ui)"), False),
        ("ref: the number inside a longer number, 219245", "m", ref("MR !219245 (testproject1-ui)"), False),
        ("ref: only the project, no number", "m", ref("testproject1-ui"), False),
        ("ref: only whitespace", "m", ref("   \t "), False),
        ("prose: `MR 1924 is evaluation-only` in the constraints", "m", {"constraints": ["MR 1924 is evaluation-only"]}, False),
        ("receipt: raw glab JSON, `metadata.sha` one object down", "f", ("a.json", json.dumps({"status": "read", "metadata": {"sha": HEAD_1924}})), True),
        ("receipt: raw glab JSON, `metadata.web_url`", "f", ("b.json", json.dumps({"metadata": {"web_url": MR_1924}})), True),
        ("receipt: `diff_refs.head_sha` inside a nested object", "f", ("c.json", json.dumps({"mr": {"diff_refs": {"head_sha": HEAD_1924}}})), True),
        ("receipt: top-level `sha`", "f", ("d.json", json.dumps({"sha": HEAD_1924})), True),
        ("receipt: the head two objects down is not read", "f", ("e.json", json.dumps({"a": {"b": {"sha": HEAD_1924}}})), False),
        ("receipt: another merge request's raw answer", "f", ("f.json", json.dumps({"metadata": {"sha": HEAD_1881, "web_url": MR_1924.replace("1924", "1881")}})), False),
        ("text: the link, in a `.txt`", "f", ("g.txt", "diff of " + MR_1924 + "\n"), True),
        ("text: the full head, in a `.diff`", "f", ("h.diff", "commit " + HEAD_1924 + "\n"), True),
        ("text: `!1924` with the project's tail on the line, in a `.patch`", "f", ("i.patch", "Subject: testproject1-ui!1924 draft\n"), True),
        ("text: `MR 1924 is evaluation-only` is prose", "f", ("j.txt", "MR 1924 is evaluation-only, not product coverage\n"), False),
        ("text: `!1924` of another project", "f", ("k.txt", "testproject1-backend!1924 fixed\n"), False),
        ("text: 219245 beside the project's name", "f", ("l.txt", "testproject1-ui 219245 build\n"), False),
        ("text: the head abbreviated to 12 is no full head", "f", ("m.txt", "commit " + HEAD_1924[:12] + "\n"), False),
        ("text: a `.md` is not a receipt", "f", ("n.md", MR_1924), False),
        ("text: the link ends AT byte 4096", "f", ("o.txt", "x" * pad + "\n" + MR_1924), True),
        ("text: the link ends at byte 4097 (cut by the limit)", "f", ("p.txt", "x" * (pad + 1) + "\n" + MR_1924), False),
        ("text: not UTF-8 bytes before the link: decoded with replacement, no crash", "f", ("q.txt", b"\xff\xfe\x00\x80 " + MR_1924.encode("utf-8")), True),
        ("text: only bytes that are not UTF-8", "f", ("r.txt", bytes(range(128, 256)) * 3), False),
    ]
    check("the battery has at least 12 rows", len(rows) >= 12)
    for label, carrier, payload, expected in rows:
        got = cited(payload) if carrier == "m" else receipt_named(task_root, *payload)
        check_eq(f"shape: {label}: {'hit' if expected else 'no hit'}", got, expected)


def receipt_scan_skips_sources():
    """t-193 follow-up: everything under `work/sources/` is the ticket's own material (snapshots, comments,
    attachments) and is never a receipt; the same files elsewhere in `work/` are (positive control)."""
    task_root, work = shapes_story()
    ticket = {"url": MR_1924, "links": {"remote_links": [MR_1924]}}
    note = "see " + MR_1924 + "\n"

    def named(name_suffix=""):
        return sorted(e.split(": ", 2)[1].split(" holds ")[0] for e in SX.manifest_problems(task_root, {})
                      if e.startswith("source-inventory.json: "))

    inside = work / "sources" / "SRC-x"
    (inside / "2026-09-18").mkdir(parents=True)
    (inside / "attachments").mkdir()
    (inside / "2026-09-18" / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
    (inside / "attachments" / "note.txt").write_text(note, encoding="utf-8")
    check_eq("work/sources/: a ticket snapshot and an attachment that name the excluded MR: 0 errors", named(), [])
    # (a different stem for the upper-case name: Windows file names are case-insensitive, so `MR-1924.json`
    # and `mr-1924.json` would be one file)
    for name, content in (("mr-1924.json", json.dumps(ticket)), ("MR-7.json", json.dumps(ticket)), ("mr-1924.txt", note)):
        (inside / name).write_text(content, encoding="utf-8")
    check_eq("work/sources/: only `mr-*.json` (the vcs_evidence receipt, by name, case-sensitive) is still read: "
             "`MR-7.json` and `mr-1924.txt` are not", named(), ["work/sources/SRC-x/mr-1924.json"])
    (inside / "deeper").mkdir()
    (inside / "deeper" / "mr-1.json").write_text(json.dumps(ticket), encoding="utf-8")
    check_eq("work/sources/: `mr-*.json` at any depth", named(), ["work/sources/SRC-x/deeper/mr-1.json", "work/sources/SRC-x/mr-1924.json"])
    for extra in ("MR-7.json", "mr-1924.txt", "deeper/mr-1.json", "mr-1924.json"):
        (inside / extra).unlink()
    (work / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
    (work / "note.txt").write_text(note, encoding="utf-8")
    check_eq("the same two files at work/ root give the errors (positive control)", named(), ["work/note.txt", "work/ticket.json"])
    (work / "other").mkdir()
    (work / "other" / "mr.json").write_text(json.dumps(ticket), encoding="utf-8")
    check_in("every other work/ path is still scanned", "work/other/mr.json", named())
    # a file called `sources`, not a directory: nothing skipped, nothing raised
    root = tmp()
    work2 = root / "work"
    work2.mkdir()
    put_list(work2, f"testproject1-ui!1924 {DASH} {REASON_1924}\n")
    (work2 / "sources").write_text("not a directory", encoding="utf-8")
    (work2 / "note.txt").write_text(note, encoding="utf-8")
    check_eq("a file named work/sources: nothing skipped, nothing raised", sorted(
        e.split(": ", 2)[1].split(" holds ")[0] for e in SX.manifest_problems(root, {}) if e.startswith("source-inventory.json: ")),
        ["work/note.txt"])


def candidate_line_ref_not_matched():
    """B-231 fix 2: a genuine candidate of the same repository, whose path or selector merely holds the
    digits, is not the excluded request's; the id-like fields are."""
    task_root, _work = shapes_story()

    def errors(**fields):
        item = dict({"candidate_id": "C-UI-restore", "repo": "testproject1-ui", "revision": HEAD_1881}, **fields)
        return [e for e in SX.manifest_problems(task_root, {"existing_test_candidates": [item]}) if " cites " in e]

    genuine = {"path": "tests/e2e/1924/test_x.py", "selector": "test_x.py::test_a(:1924)"}
    check_eq("a same-repo candidate whose path holds /1924/ and whose selector holds (:1924): 0 errors", errors(**genuine), [])
    check_eq("the same candidate with ref `!1924`: 1 error", len(errors(**genuine, ref="!1924")), 1)
    check_eq("free text is never matched (title, name, why)", errors(title="MR 1924", name="1924", why="see !1924 and testproject1-ui!1924"), [])
    for field in ("candidate_id", "id", "mr", "source", "origin"):
        check_eq(f"the id-like field `{field}` is matched", len(errors(**{field: "C-UI-1924-factory" if field != "mr" else "!1924"})), 1)
    check_eq("a list of strings in an id-like field: each string is checked", len(errors(ref=["x", "!1924"])), 1)
    check_eq("a list with no such string: 0", errors(ref=["x", "!19245"]), [])
    check_eq("a number in an id-like field is a token (str())", len(errors(mr=1924)), 1)
    check_eq("another number in an id-like field is not", errors(mr=19245), [])
    check_eq("another repository's candidate with ref `!1924` is not this word's", [
        e for e in SX.manifest_problems(task_root, {"existing_test_candidates": [{"candidate_id": "C-1", "repo": "testproject1", "ref": "!1924"}]})
        if " cites " in e], [])


def revoke_after_s1_door():
    """B-231 fix 5: after S1 is completed `--revoke` prints a door a conductor can paste: whole commands, or a
    section of s1.md in words; never a `<placeholder>`. The item's own target names it when nothing was in the
    inventory."""
    inventory = "qa-factory/artifacts/TASK-1/work/source-inventory.json"
    late = f'review --output {inventory} --late'
    raw = "https://git.example/tp1-group/testproject1-ui/-/merge\\_requests/1924"
    cases = [
        ("ticket", {"kind": "ticket", "key": "PROJ-7", "host": None}, [{"source_id": "SRC-1", "key": "PROJ-7"}],
         ['ticket_adapter.py" peek PROJ-7 --output ' + inventory + " --summary`",
          'ticket_adapter.py" collect PROJ-7 --output ' + inventory + " --relation referenced --summary", late]),
        ("mr in the inventory", {"kind": "mr", "host": None, "project": "testproject1-ui", "iid": "1924", "style": "merge_requests"},
         [{"source_id": "SRC-1", "url": raw}],
         ['vcs_evidence.py" --url "' + MR_1924 + '" --output qa-factory/artifacts/TASK-1/work/sources/SRC-1/mr-1924.json',
          "inspect --output " + inventory + ' --source-id SRC-1 --media-url "' + raw + '" --inspection-status read '
          "--local-ref sources/SRC-1/mr-1924.json", late]),
        ("mr never in the inventory, a link word", {"kind": "mr", "host": "git.example", "project": "tp1-group/testproject1-ui",
                                                     "iid": "1924", "style": "merge_requests"}, [], [MR_1924, "s1.md", late]),
        ("mr never in the inventory, the short form", {"kind": "mr", "host": None, "project": "testproject1-ui", "iid": "1924",
                                                        "style": "merge_requests"}, [], ["testproject1-ui!1924", "s1.md", late]),
        ("a link that is no merge request", {"kind": "url", "url": "https://docs.example.com/spec"}, [],
         ["https://docs.example.com/spec", "s1.md", late]),
        ("a link in the inventory that is no merge request", {"kind": "url", "url": "https://docs.example.com/spec"},
         [{"source_id": "SRC-1", "url": "https://docs.example.com/spec"}], ["https://docs.example.com/spec", "s1.md", late]),
        ("a commit word", {"kind": "ref", "sha": HEAD_1924, "branch": None}, [], [HEAD_1924, "s1.md", late]),
        ("a branch word", {"kind": "ref", "sha": None, "branch": DRAFT_BRANCH}, [], ["branch:" + DRAFT_BRANCH, "s1.md", late]),
    ]
    for label, target, restored, needles in cases:
        text = SX._door({"id": "X1", "as_written": "w", "target": target}, restored, "TASK-1")
        check_not_in(f"door, {label}: no `<` placeholder", "<", text)
        check_in(f"door, {label}: it says why it is needed", "already completed", text)
        for needle in needles:
            check_in(f"door, {label}: names `{needle[:70]}`", needle, text)
    # through the command, on a story whose inventory holds the item: the commands carry its real ids
    root = temp_project("qa-sx-door-")
    try:
        task_root, output = story_in_project(root)
        work = task_root / "work"
        put_list(work, f"testproject1-ui!1924 {DASH} {REASON_1924}\n")
        collect(Jira({"TASK-1": {"comments": [COMMENT_15045]}}), "TASK-1", output)
        source_id = by_ref(SI.load_inventory(output), "TASK-1")["source_id"]
        (task_root / "state").mkdir()
        (task_root / "state" / "controller.json").write_text(json.dumps({"stages": {"S1": {"status": "completed"}}}), encoding="utf-8")
        done = sx_cli(root, "--task", "TASK-1", "--revoke", "X1", "--words", "read it")
        door = done.stdout[done.stdout.index("S1 of this story"):]
        check_eq("the command: exit 0", done.returncode, 0)
        check_not_in("the command: the printed door has no `<` placeholder", "<", door)
        check_in("the command: the fetch carries the real source id and number",
                 f"work/sources/{source_id}/mr-1924.json", door)
        check_in("the command: and the record of it names the same item", f'--source-id {source_id} --media-url "{MR_1924}"', door)
    finally:
        cleanup(root)


def main():
    try:
        parse_empty_and_comments()
        parse_bom_crlf()
        parse_forms()
        parse_malformed_each_kind()
        parse_two_targets_one_line()
        parse_duplicate_merges_reasons()
        parse_ticket_itself()
        size_at_and_beyond_64k()
        utf16_refused()
        match_battery()
        record_shape()
        load_refused_after_inventory()
        cli_show_and_abbreviation()
        reason_and_words_are_any_utf8()
        revoke_cli_edges()
        apply_mention_without_peek()
        apply_media_item()
        block_all_excluded_is_read()
        completeness_unchanged_by_excluded()
        left_out_listed()
        no_file_identical()
        corrupt_file_refuses()
        refresh_keeps_mark()
        revoke_restores_pending()
        revoked_not_recreated()
        inspect_refused()
        assess_relevant_refused_notrelevant_noop()
        review_row_texts()
        replay_15045_comment()
        collect_matched_no_fetch()
        peek_matched_no_fetch()
        stderr_line_per_mark()
        json_stdout_pure()
        judge_sources_peek_excluded_no_fetch()
        manifest_shapes_battery()
        receipt_scan_skips_sources()
        candidate_line_ref_not_matched()
        revoke_after_s1_door()
    finally:
        for path in TMP:
            cleanup(path)
    finish("test_source_exclusions")


if __name__ == "__main__":
    main()
