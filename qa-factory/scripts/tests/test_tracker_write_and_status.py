"""The right to file a bug, proved before the person picks which bugs to file — and the one
sentence that is all a person gets when nothing is being asked of them.

Two rules of 21.09.2026 are asserted here.

TP2-2534: a good run (169/169, three real product problems) whose findings never
reached Jira, because the project's channel was an assistant with read-only rights and the
factory learned it AFTER gate B. A read-only tracker is an unfinished setup of the factory in
that project, and it belongs at onboarding, at the doctor and at S0.

TP1-15045: the person was handed all eight of the code critic's findings verbatim — every
one of them addressed to the author. One sentence was the whole of what they needed.

Nothing here touches a real tracker: the HTTP layer is a fake opener that also asserts the
only verb this module is allowed to use.
"""
import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir)

sys.path.insert(0, str(SCRIPTS))

import stage_status  # noqa: E402
import tracker_write  # noqa: E402

AGENT_CONFIG = {
    "external_writes": {"bugs": "jira", "cases": "markdown",
                        "channels": {"jira": {"method": "agent",
                                              "invoke": "jira-rw-assistant-cli"}}},
    "adapters": {"ticket": {"name": "jira", "project_keys": ["TP2"],
                            "direct_api": {"base_url": "https://tracker.example",
                                           "api_version": "2", "auth_type": "bearer",
                                           "secret_ref": "QA_FAKE_TOKEN"}}},
}


def direct_config(**overrides) -> dict:
    """The same project with the tracker written through its own API instead of an assistant."""
    config = json.loads(json.dumps(AGENT_CONFIG))
    config["external_writes"]["channels"]["jira"] = {"method": "api"}
    config.update(overrides)
    return config


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def read(self):
        return self._body

    def geturl(self):
        return "https://tracker.example/"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeJira:
    """Every request the probe makes, and the only verb it is allowed to use."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.seen = []

    def __call__(self, request, timeout=None):
        self.seen.append((request.get_method(), request.full_url))
        for fragment, payload in self.routes.items():
            if fragment in request.full_url:
                if isinstance(payload, int):
                    raise urllib.error.HTTPError(request.full_url, payload, "no", {}, None)
                return _Response(payload)
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)


def with_fake_jira(routes: dict):
    """Point `tracker_write` at a JiraClient whose opener is the fake. The client is the real
    one on purpose: it is GET-only by construction, and that is half of what this proves."""
    from source_inventory import JiraClient
    fake = FakeJira(routes)
    os.environ["QA_FAKE_TOKEN"] = "not-a-real-token"
    tracker_write._client = lambda config: JiraClient(
        "https://tracker.example", "", "QA_FAKE_TOKEN", auth_type="bearer", opener=fake)
    return fake


def project(prefix: str) -> Path:
    root = temp_dir(prefix)
    (root / "qa-factory").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    return root


def test_a_token_that_may_create_is_confirmed_with_the_fields_it_will_be_asked_for() -> None:
    """The probe proves a RIGHT. Its limit — a mandatory project field can still reject the
    write — is closed in the same pass by reading `createmeta` and naming those fields now."""
    held = tracker_write._client
    root = project("qa-tracker-write-direct-")
    try:
        fake = with_fake_jira({
            "mypermissions": {"permissions": {"CREATE_ISSUES": {"havePermission": True}}},
            "createmeta": {"projects": [{"key": "TP2", "issuetypes": [
                {"name": "Bug", "fields": {
                    "summary": {"name": "Summary", "required": True},
                    "customfield_1": {"name": "Team", "required": True},
                    "priority": {"name": "Priority", "required": True, "hasDefaultValue": True},
                    "labels": {"name": "Labels", "required": False}}}]}]},
        })
        result = tracker_write.probe(direct_config(), root, force=True)
        check_eq("a token that may create issues is confirmed",
                 result["status"], tracker_write.CONFIRMED)
        check_eq("the field the project will demand is named in advance",
                 result["required_fields"], ["Team"])
        check_not_in("a field with a default is not asked for", "Priority",
                     json.dumps(result["required_fields"]))
        check("nothing but GET was ever sent",
              all(method == "GET" for method, _ in fake.seen))
        check("and the permission was asked about the bug project",
              any("projectKey=TP2" in url for _, url in fake.seen))
        check_not_in("the receipt never carries the secret's value",
                     "not-a-real-token", tracker_write.receipt_path(root).read_text(encoding="utf-8"))
        check_in("only its variable's name", "QA_FAKE_TOKEN",
                 json.dumps(tracker_write.fingerprint(direct_config())) +
                 tracker_write.receipt_path(root).read_text(encoding="utf-8"))
    finally:
        tracker_write._client = held
        cleanup(root)


def test_the_confirmed_receipt_names_the_token_owner() -> None:
    """gate B's brief and `external_writes.py`'s own report line both stay read-only /
    one-shot by contract, so the author's display name has to travel in the SAME probe that
    already proves the CREATE_ISSUES right — a fourth GET, `/myself`, added next to it."""
    held = tracker_write._client
    root = project("qa-tracker-write-author-")
    try:
        with_fake_jira({
            "mypermissions": {"permissions": {"CREATE_ISSUES": {"havePermission": True}}},
            "createmeta": {"projects": []},
            "myself": {"accountId": "abc123", "displayName": "Jane Reviewer"},
        })
        result = tracker_write.probe(direct_config(), root, force=True)
        check_eq("still confirmed", result["status"], tracker_write.CONFIRMED)
        check_eq("the token's owner is named by display name",
                 result.get("author", {}).get("display_name"), "Jane Reviewer")
        check_eq("and by its credential's variable NAME (this fixture's bearer token has none)",
                 result.get("author", {}).get("username_ref"), "")
        check_not_in("the receipt on disk never carries the secret's value",
                     "not-a-real-token", tracker_write.receipt_path(root).read_text(encoding="utf-8"))

        # /myself unreachable: the RIGHT is still proven, only the author's name is missing.
        with_fake_jira({
            "mypermissions": {"permissions": {"CREATE_ISSUES": {"havePermission": True}}},
            "createmeta": {"projects": []},
        })
        result2 = tracker_write.probe(direct_config(), root, force=True)
        check_eq("a broken /myself never turns a confirmed right into anything less",
                 result2["status"], tracker_write.CONFIRMED)
        check_eq("the display name is just left blank",
                 result2.get("author", {}).get("display_name"), "")
    finally:
        tracker_write._client = held
        cleanup(root)


def test_a_token_that_may_not_create_is_a_plain_no_before_the_gate() -> None:
    held = tracker_write._client
    root = project("qa-tracker-write-denied-")
    try:
        with_fake_jira({"mypermissions": {"permissions": {
            "CREATE_ISSUES": {"havePermission": False}}}})
        result = tracker_write.probe(direct_config(), root, force=True)
        check_eq("a denied right is `no`, not an error", result["status"], tracker_write.NO)
        check_in("and the reason says whose right it is about",
                 "may not create issues", result["reason"])
        check_in("naming the project", "TP2", result["reason"])
    finally:
        tracker_write._client = held
        cleanup(root)


def test_a_tracker_that_cannot_be_reached_is_unverified_never_denied() -> None:
    """The reachability rule of this factory: "I could not ask" is not "your access is wrong"."""
    held = tracker_write._client
    root = project("qa-tracker-write-unreachable-")
    try:
        with_fake_jira({})  # every route 404s: the question could not be asked
        result = tracker_write.probe(direct_config(), root, force=True)
        check_eq("an unaskable question leaves the answer unverified",
                 result["status"], tracker_write.UNVERIFIED)
        check_not_in("and says nothing about the person's rights",
                     "may not create", result["reason"])
    finally:
        tracker_write._client = held
        cleanup(root)


def test_an_assistant_is_asked_once_and_its_answer_is_kept() -> None:
    """No script can call a session assistant, so the evidence is one question the orchestrator
    asks — and the prompt hands over must forbid creating anything to answer it."""
    root = project("qa-tracker-write-agent-")
    try:
        result = tracker_write.probe(AGENT_CONFIG, root, force=True)
        check_eq("an assistant nobody has asked about is unverified, not broken",
                 result["status"], tracker_write.UNVERIFIED)
        check_in("the exact question is handed over", "writes: yes", result["ask"])
        check_in("about the project bugs go to", "TP2", result["ask"])
        check_in("and it forbids creating anything to answer it", "Do not create", result["ask"])
        check_in("the person is told what routes they already have",
                 "direct API token", " ".join(result["alternatives"]))

        recorded = tracker_write.record(AGENT_CONFIG, root, tracker_write.CONFIRMED,
                                        "jira-rw-assistant-cli answered: writes: yes")
        check_eq("the answer carried back is the answer", recorded["status"],
                 tracker_write.CONFIRMED)
        check_eq("and a later probe does not ask again",
                 tracker_write.probe(AGENT_CONFIG, root)["status"], tracker_write.CONFIRMED)

        changed = json.loads(json.dumps(AGENT_CONFIG))
        changed["external_writes"]["channels"]["jira"]["invoke"] = "some-other-assistant"
        check_eq("but a different assistant is a different question",
                 tracker_write.probe(changed, root, force=True)["status"],
                 tracker_write.UNVERIFIED)
    finally:
        cleanup(root)


def test_the_answer_outlives_the_cache() -> None:
    """t-232 F1 (Lead's decision after t-260): the receipt is a probe cache the doctor rewrites on every
    run, so it stays in `state/` (ignored, never moved); the PERSON'S answer is carried: `--record` also
    appends one `tracker_write_answer` line to the approvals log, and a probe with no `answered` in the
    receipt reads the latest such line. Precedence (t-272 item 4): of the receipt's own `answered` and the
    log's lines, the NEWER `at` among those about this channel setup wins (equal: the receipt); none:
    unanswered (see test_a_newer_answer_wins_over_the_receipt). Both worlds: an older project keeps that
    log under `state/`."""
    root = project("qa-tracker-write-answer-")
    log = root / "qa-factory" / "records" / "onboarding-approvals.jsonl"
    try:
        check_eq("the receipt is where it always was, in state/, and never in records/",
                 (tracker_write.receipt_path(root) == root / "qa-factory" / "state" / "integrations" / "tracker-write.json",
                  (root / "qa-factory" / "records" / "tracker-write.json").exists()), (True, False))
        check_eq("nothing recorded, nothing in the receipt: unanswered (the question is asked)",
                 (tracker_write.recorded_answer(root), "answered" in tracker_write.probe(AGENT_CONFIG, root, force=True)), (None, False))
        said = tracker_write.record(AGENT_CONFIG, root, tracker_write.CONFIRMED, "jira-rw-assistant-cli answered: writes: yes")
        lines = log.read_text(encoding="utf-8").splitlines()
        item = json.loads(lines[-1])
        check_eq("--record appends exactly one line to records/onboarding-approvals.jsonl: the kind, the channel, the answer, the time",
                 (len(lines), sorted(item), item["kind"], item["channel"], item["answered"] == said["answered"], item["at"] == said["answered"]["at"]),
                 (1, ["answered", "at", "channel", "kind"], "tracker_write_answer", "jira", True, True))
        os.unlink(tracker_write.receipt_path(root))
        again = tracker_write.probe(AGENT_CONFIG, root, where="doctor")
        check_eq("the receipt gone (a clone, a new machine): the doctor's probe still has the answer, from the log",
                 (again["status"], again.get("answered") == said["answered"]), (tracker_write.CONFIRMED, True))
        # precedence: the receipt's own `answered` first
        own = dict(said["answered"], status=tracker_write.NO, reason="the receipt says no")
        receipt = json.loads(tracker_write.receipt_path(root).read_text(encoding="utf-8"))
        receipt["answered"] = own
        tracker_write.save_receipt(root, receipt)
        check_eq("a receipt that carries its own `answered` outranks the log's line", tracker_write.probe(AGENT_CONFIG, root, where="doctor")["status"],
                 tracker_write.NO)
        receipt.pop("answered")
        tracker_write.save_receipt(root, receipt)
        check_eq("one without it falls back to the log", tracker_write.probe(AGENT_CONFIG, root, where="doctor")["status"], tracker_write.CONFIRMED)
        # the latest line wins; lines that cannot be used are skipped, never fatal
        tracker_write.record(AGENT_CONFIG, root, tracker_write.NO, "it was withdrawn")
        with open(log, "a", encoding="utf-8", newline="\n") as handle:
            handle.write("{ not json\n" + json.dumps({"kind": "other", "answered": {"status": "confirmed"}}) + "\n"
                         + json.dumps({"kind": "tracker_write_answer", "answered": "not a dict"}) + "\n")
        os.unlink(tracker_write.receipt_path(root))
        check_eq("the LATEST answer wins (confirmed, then no), an unreadable line, another kind and a malformed answer are skipped",
                 tracker_write.probe(AGENT_CONFIG, root, where="doctor")["status"], tracker_write.NO)
        changed = json.loads(json.dumps(AGENT_CONFIG))
        changed["external_writes"]["channels"]["jira"]["invoke"] = "some-other-assistant"
        os.unlink(tracker_write.receipt_path(root))
        check_eq("an answer given about another channel is not evidence about this one (the fingerprint)",
                 tracker_write.probe(changed, root, where="doctor")["status"], tracker_write.UNVERIFIED)
        # a log whose last line has no newline is never glued to the new line
        log.write_text(log.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
        count = len(log.read_text(encoding="utf-8").splitlines())
        again = tracker_write.record(AGENT_CONFIG, root, tracker_write.CONFIRMED, "again")
        after = log.read_text(encoding="utf-8").splitlines()
        check_eq("a log with no final newline: the new line starts on its own line (one line more, the last one parses and is the new answer)",
                 (len(after), json.loads(after[-1])["answered"] == again["answered"]), (count + 1, True))
    finally:
        cleanup(root)
    # both worlds: an older project keeps the log in state/ - the answer goes to THAT file, never to a second one beside it
    old = project("qa-tracker-write-answer-old-")
    try:
        legacy = old / "qa-factory" / "state" / "onboarding-approvals.jsonl"
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"schema_version": 1, "approval_ref": "earlier", "status": "approved"}\n', encoding="utf-8")
        said = tracker_write.record(AGENT_CONFIG, old, tracker_write.CONFIRMED, "answered")
        check_eq("an older project: the line is appended to state/onboarding-approvals.jsonl after the existing one; records/ is not started",
                 (len(legacy.read_text(encoding="utf-8").splitlines()), (old / "qa-factory" / "records").exists(),
                  tracker_write.recorded_answer(old) == said["answered"]), (2, False, True))
    finally:
        cleanup(old)


def test_a_newer_answer_wins_over_the_receipt() -> None:
    """t-272 item 4: the receipt's `answered` used to hide a NEWER line of the carried approvals log (the critic's example: receipt
    `confirmed` 09-23, log `no` 10-01, same fingerprint -> the probe said `confirmed`). Now the receipt and the log are ONE pool:
    among the answers about THIS channel setup the newer `at` wins; equal `at` goes to the receipt; an answer of another
    fingerprint, or with a status that is not `confirmed`/`no`, never counts; an `at` that cannot be read is the oldest."""
    fp = tracker_write.fingerprint(AGENT_CONFIG)
    other = tracker_write.fingerprint({**AGENT_CONFIG, "adapters": {"ticket": {"project_keys": ["ELSEWHERE"]}}})

    def said(status, at, fingerprint=fp):
        return {"status": status, "at": at, "fingerprint": fingerprint, "reason": f"{status} at {at}"}

    def probe(receipt, log, where="doctor", checked_at="2026-10-01T09:00:00+00:00"):
        root = project("qa-tracker-write-newer-")
        try:
            path = tracker_write.receipt_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            if receipt is not None:
                path.write_text(json.dumps({"status": receipt["status"], "channel": "jira", "checked_at": checked_at,
                                            "fingerprint": fp, "answered": receipt}), encoding="utf-8")
            approvals = root / "qa-factory" / "records" / "onboarding-approvals.jsonl"
            approvals.parent.mkdir(parents=True, exist_ok=True)
            approvals.write_text("".join(json.dumps({"kind": "tracker_write_answer", "channel": "jira", "answered": a, "at": a["at"]}) + "\n" for a in log),
                                 encoding="utf-8")
            got = tracker_write.probe(AGENT_CONFIG, root, where=where, save=False)
            return got["status"], (got.get("answered") or {}).get("at")
        finally:
            cleanup(root)
    T = {"09-23": "2026-09-23T10:00:00+00:00", "09-30": "2026-09-30T10:00:00+00:00", "10-01": "2026-10-01T10:00:00+00:00", "10-02": "2026-10-02T10:00:00+00:00"}
    check_eq("the critic's example: receipt confirmed 09-23, log no 10-01, same fingerprint -> no (the newer)",
             probe(said("confirmed", T["09-23"]), [said("no", T["10-01"])]), ("no", T["10-01"]))
    check_eq("the other way round: receipt no 09-23, log confirmed 10-01 -> confirmed",
             probe(said("no", T["09-23"]), [said("confirmed", T["10-01"])]), ("confirmed", T["10-01"]))
    check_eq("the receipt NEWER than the log keeps winning (the old precedence's own case)",
             probe(said("no", T["10-01"]), [said("confirmed", T["09-23"])]), ("no", T["10-01"]))
    check_eq("EQUAL `at`: the receipt", probe(said("confirmed", T["10-01"]), [said("no", T["10-01"])]), ("confirmed", T["10-01"]))
    check_eq("EQUAL `at` among log lines: the later line (the receipt is gone)", probe(None, [said("confirmed", T["10-01"]), said("no", T["10-01"])]), ("no", T["10-01"]))
    check_eq("a NEWER answer about another fingerprint never counts", probe(said("confirmed", T["09-23"]), [said("no", T["10-02"], other)]), ("confirmed", T["09-23"]))
    check_eq("...and with no answer about this setup at all the probe stays unverified (nothing is invented)",
             probe(said("confirmed", T["09-23"], other), [said("no", T["10-02"], other)]), ("unverified", None))
    check_eq("an `at` nobody can read is the oldest there is: it loses to any readable one, whatever its place in the log",
             probe(said("confirmed", "not a date"), [said("no", T["09-30"]), said("confirmed", "also not a date")]), ("no", T["09-30"]))
    check_eq("...and two unreadable ones tie: the receipt",
             probe(said("confirmed", "x"), [said("no", "y")]), ("confirmed", "x"))
    check_eq("a status that is neither confirmed nor no is no answer, however new",
             probe(said("confirmed", T["09-23"]), [said("maybe", T["10-02"])]), ("confirmed", T["09-23"]))
    check_eq("the newest of several log lines wins", probe(said("confirmed", T["09-23"]), [said("no", T["09-30"]), said("confirmed", T["10-02"]), said("no", T["10-01"])]),
             ("confirmed", T["10-02"]))
    fresh = tracker_write._now()
    check_eq("a story-time probe does not believe a FRESH receipt over a newer log line (the cache is not a second authority)",
             probe(said("confirmed", T["10-01"]), [said("no", T["10-02"])], where="story", checked_at=fresh), ("no", T["10-02"]))
    check_eq("...but a fresh receipt whose answer is the newest (or equal) IS used as the cache it is",
             probe(said("confirmed", T["10-02"]), [said("no", T["10-01"])], where="story", checked_at=fresh), ("confirmed", T["10-02"]))
    check_eq("the helper itself: nothing at all -> None", tracker_write.newest_answer(fp, None, []), None)


def test_a_project_that_keeps_bugs_local_is_never_nagged() -> None:
    root = project("qa-tracker-write-markdown-")
    try:
        result = tracker_write.probe({"external_writes": {"bugs": "markdown"}}, root, force=True)
        check_eq("markdown is a first-class choice, not a gap", result.get("applicable"), False)
        check_in("and the readiness row says so plainly", "not applicable",
                 tracker_write.readiness_line(result))
    finally:
        cleanup(root)


def test_a_recorded_markdown_choice_is_a_fact_not_a_warning() -> None:
    """HF8-13 (t-300; K-13.2, K-13.3). The capability row of a project that keeps its bugs in the
    repository carries remedy.kind `not_a_defect`, S0 reads that field and writes no warning, and
    the text no longer claims to know whose choice it is (FR-41): the code cannot tell a choice
    from a template default."""
    import gate_brief
    import readiness
    root = project("qa-tracker-write-choice-")
    try:
        for label, cfg in (("markdown", {"external_writes": {"bugs": "markdown"}}),
                           ("a missing key", {})):
            row = readiness.check_tracker_write(cfg, root)
            check_eq(f"{label}: the row is not a defect", row["remedy"]["kind"], "not_a_defect")
            result = tracker_write.probe(cfg, root, force=True)
            check_not_in(f"{label}: no word about a choice (M-13.3)", "choice", result["reason"])
            check_in(f"{label}: the reason states the value instead", "external_writes.bugs = ",
                     result["reason"])
            check_in(f"{label}: gate B still names where the bugs go (the carrier)",
                     "bugs stay in this repository", gate_brief.filing_line(root, cfg))
        check_in("a missing key is shown as not set, not as a value",
                 "external_writes.bugs = not set", tracker_write.probe({}, root, force=True)["reason"])
        check_in("a set value is shown as it is",
                 "external_writes.bugs = none",
                 tracker_write.probe({"external_writes": {"bugs": "none"}}, root, force=True)["reason"])
        # a channel that cannot write is still a problem: `no`, and not marked as a non-defect
        jira = tracker_write.probe({"external_writes": {"bugs": "jira"}}, root, force=True)
        check_eq("jira without a delivery is `no`", jira.get("status"), tracker_write.NO)
        check_eq("...and not a local-by-design answer", jira.get("applicable"), None)
        row = readiness.check_tracker_write({"external_writes": {"bugs": "jira"}}, root)
        check_eq("...its row is a gap, not a non-defect", row["remedy"]["kind"] != "not_a_defect", True)
    finally:
        cleanup(root)


def test_a_non_object_external_writes_is_nothing_recorded_not_a_crash() -> None:
    """Fix round 2, F12: `probe({"external_writes": "markdown"})` raised AttributeError in `channel_of` (and `validate` does not refuse
    the value), so the guard in `_answer` answered only a direct call. `channel_of`, `bug_project` and the `ew` reads take any value:
    a non-object is `{}`, so the default channel (markdown) answers and the capability is `not_a_defect`."""
    import readiness
    root = project("qa-tracker-write-nonobject-")
    try:
        for label, value in (("a string", "markdown"), ("a list", ["jira"]), ("a number", 3), ("null", None)):
            cfg = {"external_writes": value}
            check_eq(f"{label}: `channel_of` is the default channel", tracker_write.channel_of(cfg), "markdown")
            check_eq(f"{label}: `bug_project` is empty", tracker_write.bug_project(cfg), "")
            result = tracker_write.probe(cfg, root, force=True)
            check_eq(f"{label}: `probe` answers (not applicable, no tracker), it does not raise", result.get("applicable"), False)
            check_in(f"{label}: and states the value as not set", "external_writes.bugs = not set", result["reason"])
            check_eq(f"{label}: the readiness row survives and is `not_a_defect`", readiness.check_tracker_write(cfg, root)["remedy"]["kind"],
                     "not_a_defect")
    finally:
        cleanup(root)


def test_the_cache_has_one_clock_per_caller() -> None:
    """S0 re-probes after a day; the gate B rehearsal after a few hours, because a token can
    expire inside one story. Both are factory defaults and both are config keys."""
    root = project("qa-tracker-write-clock-")
    try:
        check_eq("the story's clock is a day", tracker_write.max_age_h(AGENT_CONFIG), 24.0)
        check_eq("the gate's is shorter",
                 tracker_write.max_age_h(AGENT_CONFIG, "gate_b"), 4.0)
        tuned = json.loads(json.dumps(AGENT_CONFIG))
        tuned["external_writes"]["probe"] = {"max_age_h": 2, "gate_b_max_age_h": 1}
        check_eq("a project may set its own", tracker_write.max_age_h(tuned), 2.0)
        tracker_write.probe(AGENT_CONFIG, root, force=True)
        check("the doctor always probes rather than trusting a cache",
              not tracker_write.probe(AGENT_CONFIG, root, where="doctor").get("cached"))
        check("a story reuses the fresh answer",
              tracker_write.probe(AGENT_CONFIG, root, where="story").get("cached") is True)
        check("and a rehearsal writes no receipt of its own",
              tracker_write.probe(AGENT_CONFIG, root, force=True, save=False) is not None)
    finally:
        cleanup(root)


def test_one_sentence_is_the_whole_message() -> None:
    """The owner's words: "the critic found something, it went to the author for repair — why
    does the person have to read all of that? One sentence is enough.\""""
    root = temp_dir("qa-stage-status-")
    try:
        text = stage_status.line(root, "critic_returned", findings=8, round=2, cap=2)
        check("it is one line", "\n" not in text)
        check("and a short one", len(text) <= stage_status.MAX_CHARS)
        check_in("the findings are counted", "8 findings", text)
        check_not_in("never quoted", "assert", text)
        check_in("the last round is named as the last", "Round 2 of 2 is the last one.", text)
        check_in("and the person is told they are not needed", stage_status.NOTHING, text)
        check_in("a halt names the one thing wanted, once",
                 "I need one thing from you: install the toolchain",
                 stage_status.line(root, "role_halt", role="qa-automator", stage="S5",
                                   reason="pytest cannot collect the suite",
                                   need="install the toolchain, or say run without it"))
        check_in("a repair the factory did itself is reported, not asked about",
                 stage_status.NOTHING,
                 stage_status.line(root, "state_repaired",
                                   what="the dispatch a crashed window left open"))
        try:
            stage_status.line(root, "all_good")
            check("an event nobody defined is refused", False)
        except ValueError:
            check("an event nobody defined is refused", True)
    finally:
        cleanup(root)


def test_the_sentence_is_built_from_receipts_not_from_prose() -> None:
    """The numbers come off disk, and a number that is not on disk is left out of the sentence
    rather than invented: a status line that guesses is worse than a shorter one."""
    root = temp_dir("qa-stage-status-receipts-")
    task_root = root / "TP1-15045"
    (task_root / "work").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    try:
        (task_root / "work" / "review-receipt.json").write_text(json.dumps(
            {"findings": [{"id": n} for n in range(8)]}), encoding="utf-8")
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
            {"review_receipt_ref": "work/review-receipt.json"}), encoding="utf-8")
        # d1 opened the window; d2 and d3 are the two repair rounds the critic caused. The
        # window's own first dispatch is not a round (0.7.7 review: the person was told
        # "Round 5 of 2" because every dispatch of the stage was counted).
        (task_root / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"d1": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"]},
                            "d2": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                   "purpose": "repair_verify"},
                            "d3": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                   "rework_of": "d1"},
                            "d4": {"stage": "S4", "role": "qa-case-designer"}}}),
            encoding="utf-8")
        check_eq("the count comes from the critic's own receipt",
                 stage_status.findings_count(task_root), 8)
        check_eq("the round comes from the dispatch receipts",
                 stage_status.rounds_spent(task_root, "S5", "qa-automator"), 2)
        text = stage_status.line(task_root, "critic_returned", stage="S5")
        check_in("so the sentence needs no facts from the caller", "8 findings", text)
        check_in("and still names the round", "Round 2 of 2", text)
        bare = stage_status.line(root, "critic_returned")
        check_not_in("with nothing on disk it counts nothing", "findings.", bare)
        check_in("but still says what happened", "Handed the critic's findings", bare)
        check_in("and that nobody is needed", stage_status.NOTHING, bare)
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_a_token_that_may_create_is_confirmed_with_the_fields_it_will_be_asked_for()
    test_the_confirmed_receipt_names_the_token_owner()
    test_a_token_that_may_not_create_is_a_plain_no_before_the_gate()
    test_a_tracker_that_cannot_be_reached_is_unverified_never_denied()
    test_an_assistant_is_asked_once_and_its_answer_is_kept()
    test_the_answer_outlives_the_cache()
    test_a_newer_answer_wins_over_the_receipt()
    test_a_project_that_keeps_bugs_local_is_never_nagged()
    test_a_recorded_markdown_choice_is_a_fact_not_a_warning()
    test_a_non_object_external_writes_is_nothing_recorded_not_a_crash()
    test_the_cache_has_one_clock_per_caller()
    test_one_sentence_is_the_whole_message()
    test_the_sentence_is_built_from_receipts_not_from_prose()
    finish("tracker write right and the person's one line")
