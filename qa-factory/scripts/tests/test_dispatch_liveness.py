#!/usr/bin/env python3
"""Proof of life for a dispatch, and the two ways 0.7.6 got it wrong.

The rule it replaces closed a dispatch when the host had recorded no launch. The Claude Code
host records no launch for anything, so on TP1-15045 every genuinely running dispatch
matched it until its role stopped — one `next` during a 24-minute automator window would have
closed a live job. And TP2-2523 was the opposite: the role started, refused, stopped,
and the dispatch stayed `running` for two days because nothing wrote its return down.

`hooklib.subagent_meta` / `story_subagent_transcripts` belong to another package and may not
be installed yet; every test here supplies its own, and one runs with neither.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import dispatch_liveness as LIVE  # noqa: E402
import hooklib  # noqa: E402

TICKET = "TP1-15045"
DISPATCH = {"id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator"}
HOST_ID = "a672cd1077d7968c3"      # a Claude host agent id, what the stop hook writes when the event had no dispatch_id


def project(root):
    (root / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    return root


def transcript(root, name, dispatch_id, role="qa-automator", ticket=TICKET, age=0.0):
    """A subagent transcript of the shape the Claude host leaves behind."""
    path = root / "subagents" / f"agent-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    first = {"type": "user", "message": {"role": "user", "content":
             f"You are {role}. Ticket: {ticket}\nDispatch id: {dispatch_id}\n"}}
    path.write_text(json.dumps(first) + "\n" + json.dumps({"type": "assistant"}) + "\n",
                    encoding="utf-8")
    when = time.time() - age
    import os
    os.utime(path, (when, when))
    return path


def fake_hooklib(paths):
    """Stand in for the two hooklib helpers with a parser of the same contract."""
    def story_subagent_transcripts(project_root):
        return list(paths)

    def subagent_meta(path):
        text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[0]
        head = json.loads(text)["message"]["content"]
        def field(name):
            for line in head.splitlines():
                if line.startswith(name + ":"):
                    return line.split(":", 1)[1].strip()
            return None
        stat = Path(path).stat()
        return {"role": (head.split(".")[0].replace("You are ", "") or None),
                "ticket": field("Ticket"), "dispatch_id": field("Dispatch id"),
                "first_at": stat.st_mtime, "last_at": stat.st_mtime}

    hooklib.story_subagent_transcripts = story_subagent_transcripts
    hooklib.subagent_meta = subagent_meta


def without_hooklib():
    for name in ("story_subagent_transcripts", "subagent_meta"):
        if hasattr(hooklib, name):
            delattr(hooklib, name)


# A fixed clock: every receipt test passes `now=NOW` and sets file times relative to it, so nothing
# here waits and nothing depends on how busy the machine is (FR-31).
NOW = 1_800_000_000.0


def receipt(root, name="one", file_age=0, **fields):
    """One host receipt of the role of DISPATCH for this story, its file time `file_age` s before NOW.

    A field set to `None` is written as null; to leave a field out entirely, pass `_drop=[...]`.
    """
    drop = fields.pop("_drop", [])
    record = {"agent_id": name, "agent_type": "qa-automator", "task_id": TICKET,
              "dispatch_id": DISPATCH["id"], "status": "running"}
    record.update(fields)
    for key in drop:
        record.pop(key, None)
    path = root / "qa-factory" / "state" / "host-dispatches" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, (NOW - file_age, NOW - file_age))
    return path


def verdict_at(root, began=NOW - 900, ticket=TICKET, **dispatch):
    return LIVE.state(root, ticket, dict(DISPATCH, started_at=began, **dispatch), now=NOW)


def scene(prefix, with_inventory=False):
    """A project with no transcript helper, or with one that only knows another role's transcript."""
    root = temp_dir(prefix)
    project(root)
    if with_inventory:
        fake_hooklib([transcript(root, "other", "S4-qa-case-critic-1", role="qa-case-critic")])
    else:
        without_hooklib()
    return root


def a_host_that_proves_nothing_closes_nothing():
    root = temp_dir("qa-live-silent-")
    try:
        without_hooklib()
        verdict = LIVE.state(project(root), TICKET, dict(DISPATCH, started_at=time.time() - 9000))
        check_eq("with no transcripts and no receipts the answer is unknown",
                 verdict["state"], LIVE.UNKNOWN)
        check_in("and it says why it cannot tell", "no subagent transcript", verdict["evidence"])
    finally:
        without_hooklib()
        cleanup(root)


def a_working_agent_is_alive():
    root = temp_dir("qa-live-alive-")
    try:
        project(root)
        fake_hooklib([transcript(root, "one", DISPATCH["id"], age=12)])
        verdict = LIVE.state(root, TICKET, dict(DISPATCH, started_at=time.time() - 900))
        check_eq("a transcript written seconds ago is an agent at work",
                 verdict["state"], LIVE.ALIVE)
        check_in("and the evidence is the file itself", "agent-one.jsonl", verdict["evidence"])
    finally:
        without_hooklib()
        cleanup(root)


def a_silent_agent_is_abandoned():
    root = temp_dir("qa-live-abandoned-")
    try:
        project(root)
        fake_hooklib([transcript(root, "one", DISPATCH["id"], age=4000)])
        verdict = LIVE.state(root, TICKET, dict(DISPATCH, started_at=time.time() - 5000))
        check_eq("an hour of silence is not a long thought", verdict["state"], LIVE.ABANDONED)
        check_in("and the answer says how long", "silent for", verdict["evidence"])
    finally:
        without_hooklib()
        cleanup(root)


def a_launch_that_never_happened():
    root = temp_dir("qa-live-never-")
    try:
        project(root)
        # The story's other roles have transcripts; this dispatch has none.
        fake_hooklib([transcript(root, "other", "S4-qa-case-critic-1", role="qa-case-critic", age=30)])
        verdict = LIVE.state(root, TICKET, dict(DISPATCH, started_at=time.time() - 600))
        check_eq("no transcript ten minutes after the receipt is a launch that never happened",
                 verdict["state"], LIVE.NEVER_STARTED)
        fresh = LIVE.state(root, TICKET, dict(DISPATCH, started_at=time.time() - 20))
        check_eq("twenty seconds after the receipt it is simply too soon to tell",
                 fresh["state"], LIVE.UNKNOWN)
        check_in("and the answer says so", "too soon", fresh["evidence"])
    finally:
        without_hooklib()
        cleanup(root)


def a_role_that_stopped_is_a_return():
    """TP2-2523, reduced to its evidence: a `subagent_stop` after the dispatch."""
    root = temp_dir("qa-live-returned-")
    try:
        project(root)
        began = time.time() - 600
        journal = root / "qa-factory" / "records" / "journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({
            "event": "subagent_stop", "agent": "qa-factory:qa-test-strategist", "task": TICKET,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(began + 60))}) + "\n",
            encoding="utf-8")
        without_hooklib()
        dispatch = {"id": "S3-qa-test-strategist-2", "stage": "S3", "role": "qa-test-strategist",
                    "started_at": began}
        verdict = LIVE.state(root, TICKET, dispatch)
        check_eq("a journalled stop of that role is a recorded return", verdict["state"], LIVE.RETURNED)
        check_in("named with the agent the journal named", "qa-test-strategist", verdict["evidence"])
        earlier = LIVE.state(root, TICKET, dict(dispatch, started_at=began + 600))
        check_eq("a stop from before this dispatch started proves nothing about it",
                 earlier["state"], LIVE.UNKNOWN)
    finally:
        without_hooklib()
        cleanup(root)


def the_host_receipts_still_count():
    root = temp_dir("qa-live-receipt-")
    try:
        project(root)
        without_hooklib()
        path = receipt(root, "one")
        began = NOW - 900
        check_eq("a live host binding is a working agent",
                 LIVE.state(root, TICKET, dict(DISPATCH, started_at=began), now=NOW)["state"],
                 LIVE.ALIVE)
        receipt(root, "one", bound_at=NOW - LIVE.DEFAULT_ABANDONED_AFTER_S - 1)
        stale = LIVE.state(root, TICKET, dict(DISPATCH, started_at=began), now=NOW)
        check_eq("a launch receipt older than the window is no longer a working agent, and no more "
                 "a dead one: the person is asked", stale["state"], LIVE.UNKNOWN)
        check_in("and the answer says a receipt proves no activity", "not proof", stale["evidence"])
        path.write_text(json.dumps({"agent_id": "a1", "agent_type": "qa-automator",
                                    "task_id": TICKET, "dispatch_id": DISPATCH["id"],
                                    "status": "terminal"}), encoding="utf-8")
        check_eq("a terminal one is the host saying the worker returned",
                 LIVE.state(root, TICKET, dict(DISPATCH, started_at=began), now=NOW)["state"],
                 LIVE.RETURNED)
    finally:
        without_hooklib()
        cleanup(root)


def a_stale_prior_receipt_names_another_dispatch():
    """TP2-2406: -19 stayed `running` after a terminal usage failure and -20 never launched.
    A receipt that names another dispatch is evidence about that dispatch only."""
    began = NOW - 900
    root = scene("qa-live-prior-inv-", with_inventory=True)
    try:
        receipt(root, "prior", dispatch_id="S5-qa-automator-19",
                bound_at=NOW - LIVE.DEFAULT_ABANDONED_AFTER_S - 1)
        replacement = dict(DISPATCH, id="S5-qa-automator-20", started_at=began)
        verdict = LIVE.state(root, TICKET, replacement, now=NOW)
        check_eq("with a transcript inventory a stale receipt of another dispatch does not hide a "
                 "launch that never happened", verdict["state"], LIVE.NEVER_STARTED)
        check_in("and the proof is the missing transcript", "no subagent transcript names this dispatch",
                 verdict["evidence"])
        receipt(root, "prior", dispatch_id="S5-qa-automator-19", bound_at=NOW - 30)
        check_eq("a FRESH receipt of another dispatch is just as foreign",
                 LIVE.state(root, TICKET, replacement, now=NOW)["state"], LIVE.NEVER_STARTED)
    finally:
        without_hooklib()
        cleanup(root)
    root = scene("qa-live-prior-bare-")
    try:
        receipt(root, "prior", dispatch_id="S5-qa-automator-19",
                bound_at=NOW - LIVE.DEFAULT_ABANDONED_AFTER_S - 1)
        verdict = LIVE.state(root, TICKET, dict(DISPATCH, id="S5-qa-automator-20", started_at=began), now=NOW)
        check_eq("with no inventory the replacement is not closed either", verdict["state"], LIVE.UNKNOWN)
        check_not_in("and it does not blame a receipt that is about another dispatch",
                     "names this story and role", verdict["evidence"])
        check_in("it says what this host cannot see", "no subagent transcript", verdict["evidence"])
    finally:
        without_hooklib()
        cleanup(root)


def a_receipt_is_good_for_the_window_and_no_longer():
    for label, kwargs, config in (
            ("recorded launch time", lambda age: {"bound_at": NOW - age}, None),
            ("file time (a receipt written before bound_at existed)",
             lambda age: {"file_age": age}, None),
            ("a configured window", lambda age: {"bound_at": NOW - age}, 60)):
        root = scene("qa-live-window-")
        try:
            if config:
                (root / "qa-factory" / "config.json").write_text(
                    json.dumps({"dispatch": {"abandoned_after_s": config}}), encoding="utf-8")
            edge = config or int(LIVE.DEFAULT_ABANDONED_AFTER_S)
            receipt(root, **kwargs(edge))
            at = verdict_at(root)
            check_eq(f"{label}: a receipt exactly at the window is a working agent", at["state"], LIVE.ALIVE)
            receipt(root, **kwargs(edge + 1))
            beyond = verdict_at(root)
            check_eq(f"{label}: one second beyond it nobody can tell", beyond["state"], LIVE.UNKNOWN)
            check_in(f"{label}: the answer says a receipt is not proof", "not proof", beyond["evidence"])
            if "file time" in label:
                check_in(f"{label}: ALIVE names its source", "file time", at["evidence"])
                check_in(f"{label}: UNKNOWN names its source", "file time", beyond["evidence"])
            else:
                check_in(f"{label}: ALIVE names its source", "recorded", at["evidence"])
                check_in(f"{label}: UNKNOWN names the age", f"{edge + 1}s", beyond["evidence"])
        finally:
            cleanup(root)


def a_recorded_time_outranks_the_file_time():
    root = scene("qa-live-recorded-")
    try:
        receipt(root, bound_at=NOW - 30, file_age=5000)
        check_eq("a rewritten (old) file does not age a receipt whose launch is recorded as recent",
                 verdict_at(root)["state"], LIVE.ALIVE)
        receipt(root, bound_at=NOW - 5000, file_age=0)
        check_eq("and a freshly rewritten file does not make an old launch recent",
                 verdict_at(root)["state"], LIVE.UNKNOWN)
    finally:
        cleanup(root)


def an_unusable_recorded_time_counts_as_absent():
    for bad in ("600", True, False, float("nan"), float("inf"), float("-inf"), -1, 0, None,
                [NOW], 10 ** 400):
        root = scene("qa-live-invalid-")
        try:
            receipt(root, bound_at=bad, file_age=0)
            alive = verdict_at(root)
            check_eq(f"bound_at {str(bad)[:12]!r} is ignored: the file time answers", alive["state"], LIVE.ALIVE)
            check_in(f"bound_at {str(bad)[:12]!r}: and says so", "file time", alive["evidence"])
            receipt(root, bound_at=bad, file_age=601)
            check_eq(f"bound_at {str(bad)[:12]!r}: a stale file time is not rescued by it",
                     verdict_at(root)["state"], LIVE.UNKNOWN)
        finally:
            cleanup(root)
    root = scene("qa-live-own-key-")
    try:
        receipt(root, _file_mtime=NOW - 5000)
        check_eq("a time written into the receipt under the reader's own key is overwritten by the file's",
                 verdict_at(root)["state"], LIVE.ALIVE)
    finally:
        cleanup(root)


def a_clock_ahead_is_skew_up_to_a_minute():
    root = scene("qa-live-ahead-")
    try:
        for ahead in (30, 60):
            receipt(root, bound_at=NOW + ahead)
            check_eq(f"a launch {ahead}s ahead of the clock is skew, age 0", verdict_at(root)["state"], LIVE.ALIVE)
        receipt(root, bound_at=NOW + 61)
        far = verdict_at(root)
        check_eq("61 seconds ahead is a time nobody can trust", far["state"], LIVE.UNKNOWN)
        check_in("and the answer says it is ahead", "ahead", far["evidence"])
        receipt(root, file_age=-61)
        check_eq("the same for a file time", verdict_at(root)["state"], LIVE.UNKNOWN)
        check_in("with the same word", "ahead", verdict_at(root)["evidence"])
        receipt(root, bound_at=NOW + 61, file_age=0)
        check_eq("an untrustworthy recorded time is not replaced by a better-looking file time",
                 verdict_at(root)["state"], LIVE.UNKNOWN)
    finally:
        cleanup(root)


def a_receipt_with_no_time_at_all_is_unknown():
    root = scene("qa-live-timeless-")
    try:
        path = receipt(root)
        original = LIVE.host_bindings

        def stripped(project_root):
            records = original(project_root)
            for record in records:
                record["_file_mtime"] = None
            return records

        LIVE.host_bindings = stripped
        try:
            verdict = verdict_at(root)
        finally:
            LIVE.host_bindings = original
        check_eq("a receipt whose time nobody knows is not a working agent", verdict["state"], LIVE.UNKNOWN)
        check_in("and the answer says the time is unknown", "unknown time", verdict["evidence"])
        check_in("and that a receipt is not proof", "not proof", verdict["evidence"])
        check("the receipt file is untouched", path.is_file())
    finally:
        cleanup(root)


def host_bindings_carry_the_file_time():
    root = scene("qa-live-bindings-")
    try:
        receipt(root, "one", file_age=123)
        receipt(root, "probe", factory_diagnostic="context_probe")
        records = LIVE.host_bindings(root)
        check_eq("a diagnostic probe is still not a receipt", [r.get("agent_id") for r in records], ["one"])
        check_eq("each record carries the time its file was last written", records[0].get("_file_mtime"),
                 NOW - 123)
    finally:
        cleanup(root)


def several_receipts_of_one_dispatch():
    root = scene("qa-live-several-")
    try:
        receipt(root, "done", status="terminal", bound_at=NOW - 3000)
        receipt(root, "again", bound_at=NOW - 3000)
        stale = verdict_at(root)
        check_eq("a terminal receipt does not outvote a stale one that is not terminal",
                 stale["state"], LIVE.UNKNOWN)
        receipt(root, "again", bound_at=NOW - 20)
        check_eq("a terminal receipt next to a fresh one that is not terminal still waits",
                 verdict_at(root)["state"], LIVE.ALIVE)
        receipt(root, "again", status="terminal", bound_at=NOW - 20)
        check_eq("and when every receipt of the dispatch is terminal it returned",
                 verdict_at(root)["state"], LIVE.RETURNED)
    finally:
        cleanup(root)


def both_hosts_answer_a_stale_receipt_the_same_way():
    for with_inventory in (False, True):
        root = scene("qa-live-hosts-", with_inventory=with_inventory)
        try:
            receipt(root, bound_at=NOW - 5000)
            verdict = verdict_at(root)
            name = "with" if with_inventory else "without"
            check_eq(f"{name} a transcript inventory a stale receipt of this dispatch is unknown",
                     verdict["state"], LIVE.UNKNOWN)
            check_in(f"{name} an inventory: and says so", "not proof", verdict["evidence"])
        finally:
            without_hooklib()
            cleanup(root)


def a_receipt_never_outranks_better_evidence_and_never_closes():
    root = scene("qa-live-order-")
    try:
        receipt(root, bound_at=NOW - 5000)
        fresh = transcript(root, "mine", DISPATCH["id"])
        os.utime(fresh, (NOW - 12, NOW - 12))
        fake_hooklib([fresh])
        check_eq("a transcript written seconds ago wins over a stale receipt",
                 verdict_at(root)["state"], LIVE.ALIVE)
        check_in("with the transcript as its evidence", "agent-mine.jsonl", verdict_at(root)["evidence"])
        without_hooklib()
        runs = root / "qa-factory" / "artifacts" / TICKET / "state"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / "driver-runs.jsonl").write_text(json.dumps(
            {"dispatch": DISPATCH["id"], "exit_code": 0,
             "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - 100))}) + "\n", encoding="utf-8")
        receipt(root, bound_at=NOW - 20)
        check_eq("a driver row with an exit code wins over a fresh receipt",
                 verdict_at(root)["state"], LIVE.RETURNED)
        (runs / "driver-runs.jsonl").unlink()
        journal = root / "qa-factory" / "state" / "journal.jsonl"
        journal.write_text(json.dumps({
            "event": "subagent_stop", "agent": "qa-factory:qa-automator", "task": TICKET,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - 300))}) + "\n", encoding="utf-8")
        check_eq("a journalled stop of the role does not close a dispatch whose receipt is fresh",
                 verdict_at(root)["state"], LIVE.ALIVE)
        receipt(root, bound_at=NOW - 5000)
        stale = verdict_at(root)
        check_eq("nor one whose receipt is stale: age can turn ALIVE into unknown, never into a closure",
                 stale["state"], LIVE.UNKNOWN)
        # Both kinds of evidence at once: the dispatch's OWN transcript has been silent past the
        # window and its receipt is stale. Silence alone is `abandoned`; a matching receipt of the
        # same dispatch turns it into a question, because a receipt has no heartbeat and the
        # silence may be the one place the host does not write (a Codex child).
        journal.unlink()
        silent = transcript(root, "mine", DISPATCH["id"])
        os.utime(silent, (NOW - 700, NOW - 700))
        fake_hooklib([silent])
        both = verdict_at(root)
        check_eq("a silent own transcript plus a stale matching receipt is unknown, never abandoned",
                 both["state"], LIVE.UNKNOWN)
        check_in("with the silence in the evidence", "has been silent for 700s", both["evidence"])
        check_in("and the stale receipt, said not to be proof", "not proof its agent is still working",
                 both["evidence"])
        (root / "qa-factory" / "state" / "host-dispatches" / "one.json").unlink()
        check_eq("control: the same silence with no receipt is abandoned",
                 verdict_at(root)["state"], LIVE.ABANDONED)
    finally:
        without_hooklib()
        cleanup(root)


def an_unbound_receipt_counts_only_if_it_may_be_this_dispatch():
    began = NOW - 900
    for label, extra, drop in (("an empty dispatch id", {"dispatch_id": ""}, []),
                               ("a null dispatch id", {"dispatch_id": None}, []),
                               ("no dispatch id", {}, ["dispatch_id"])):
        root = scene("qa-live-unbound-", with_inventory=True)
        try:
            receipt(root, _drop=drop, bound_at=began - 59, **extra)
            check_eq(f"{label}: a receipt written just before this dispatch may be it",
                     verdict_at(root, began)["state"], LIVE.UNKNOWN)
            receipt(root, _drop=drop, bound_at=began - 60, **extra)
            check_eq(f"{label}: exactly 60 s before is still skew, not proof", verdict_at(root, began)["state"],
                     LIVE.UNKNOWN)
            receipt(root, _drop=drop, bound_at=began + 100, **extra)
            check_eq(f"{label}: one written after it began may be it", verdict_at(root, began)["state"],
                     LIVE.UNKNOWN)
            receipt(root, _drop=drop, bound_at=began - 61, **extra)
            gone = verdict_at(root, began)
            check_eq(f"{label}: one recorded 61 s before this dispatch is an earlier attempt's: no "
                     "transcript for this one after the window means it never launched",
                     gone["state"], LIVE.NEVER_STARTED)
            check_in(f"{label}: on the existing proof", "no subagent transcript names this dispatch",
                     gone["evidence"])
            check_eq(f"{label}: began unknown, the unbound receipt counts",
                     verdict_at(root, None)["state"], LIVE.UNKNOWN)
        finally:
            without_hooklib()
            cleanup(root)
    root = scene("qa-live-unbound-more-", with_inventory=True)
    try:
        receipt(root, "before", dispatch_id="", bound_at=began - 5000)
        receipt(root, "after", dispatch_id="", bound_at=began + 5)
        check_eq("two unbound receipts, one before and one after: the later one may be it",
                 verdict_at(root, began)["state"], LIVE.UNKNOWN)
        check_in("and the answer names the receipt as undated for this dispatch", "names no dispatch",
                 verdict_at(root, began)["evidence"])
        (root / "qa-factory" / "state" / "host-dispatches" / "after.json").unlink()
        receipt(root, "after", dispatch_id="", file_age=0)
        check_eq("a receipt with only a file time is never proven older, the file time is the last write",
                 verdict_at(root, began)["state"], LIVE.UNKNOWN)
        (root / "qa-factory" / "state" / "host-dispatches" / "after.json").unlink()
        receipt(root, "after", dispatch_id="", bound_at="long ago", file_age=99999)
        check_eq("an invalid recorded time proves nothing about order either",
                 verdict_at(root, began)["state"], LIVE.UNKNOWN)
        (root / "qa-factory" / "state" / "host-dispatches" / "after.json").unlink()
        (root / "qa-factory" / "state" / "host-dispatches" / "before.json").unlink()
        receipt(root, "stranger", agent_type="qa-case-critic", dispatch_id="", bound_at=began + 5)
        check_eq("an unbound receipt of another role is not this role's", verdict_at(root, began)["state"],
                 LIVE.NEVER_STARTED)
        receipt(root, "stranger", dispatch_id="", bound_at=began + 5, task_id="TP2-OTHER")
        check_eq("nor one of another story", verdict_at(root, began)["state"], LIVE.NEVER_STARTED)
    finally:
        without_hooklib()
        cleanup(root)
    root = scene("qa-live-unbound-bare-")
    try:
        receipt(root, dispatch_id="", bound_at=began - 61)
        verdict = verdict_at(root, began)
        check_eq("with no inventory an earlier attempt's receipt leaves the replacement unknown",
                 verdict["state"], LIVE.UNKNOWN)
        check_in("with the host's own limit as the reason", "no subagent transcript", verdict["evidence"])
    finally:
        without_hooklib()
        cleanup(root)


def a_binding_of_another_story_proves_nothing_here():
    """Dispatch ids are unique per story, not per project: two stories both reach
    `S5-qa-automator-12`. A receipt is evidence for this dispatch only when it names this story."""
    root = temp_dir("qa-live-foreign-")
    try:
        project(root)
        without_hooklib()
        path = root / "qa-factory" / "state" / "host-dispatches" / "one.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        began = time.time() - 900

        def binding(**fields):
            record = {"agent_id": "foreign", "agent_type": "qa-automator",
                      "task_id": "TP2-OTHER", "dispatch_id": DISPATCH["id"],
                      "status": "terminal"}
            record.update(fields)
            path.write_text(json.dumps(record), encoding="utf-8")
            return LIVE.state(root, TICKET, dict(DISPATCH, started_at=began))["state"]

        check_eq("a same-named dispatch from another story cannot close this one",
                 binding(), LIVE.UNKNOWN)
        check_eq("a same-named running dispatch from another story does not keep this one alive",
                 binding(status="running"), LIVE.UNKNOWN)
        check_eq("a receipt with no story named proves nothing about this one (absent)",
                 binding(task_id=None, status="terminal"), LIVE.UNKNOWN)
        check_eq("a receipt with an empty story proves nothing about this one",
                 binding(task_id="", status="running"), LIVE.UNKNOWN)
        check_eq("this story's own terminal receipt still closes it",
                 binding(task_id=TICKET, status="terminal"), LIVE.RETURNED)
        check_eq("and its own running receipt still keeps it alive",
                 binding(task_id=TICKET, status="running"), LIVE.ALIVE)
    finally:
        without_hooklib()
        cleanup(root)


def the_thresholds_are_a_project_setting():
    root = temp_dir("qa-live-config-")
    try:
        project(root)
        check_eq("a project that says nothing gets the shipped defaults",
                 LIVE.thresholds(root),
                 {"abandoned_after_s": LIVE.DEFAULT_ABANDONED_AFTER_S,
                  "never_started_after_s": LIVE.DEFAULT_NEVER_STARTED_AFTER_S,
                  "native_completion_grace_s": LIVE.NATIVE_COMPLETION_GRACE_S})
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"dispatch": {"abandoned_after_s": 60, "never_started_after_s": 0}}),
            encoding="utf-8")
        tuned = LIVE.thresholds(root)
        check_eq("a project that tunes one gets it", tuned["abandoned_after_s"], 60.0)
        check_eq("and a nonsense value falls back instead of closing everything at once",
                 tuned["never_started_after_s"], LIVE.DEFAULT_NEVER_STARTED_AFTER_S)
        fake_hooklib([transcript(root, "one", DISPATCH["id"], age=120)])
        check_eq("two minutes of silence is abandonment under that project's setting",
                 LIVE.state(root, TICKET, dict(DISPATCH, started_at=time.time() - 300))["state"],
                 LIVE.ABANDONED)
    finally:
        without_hooklib()
        cleanup(root)


def a_broken_helper_never_decides_anything():
    root = temp_dir("qa-live-broken-")
    try:
        project(root)

        def explode(*args, **kwargs):
            raise RuntimeError("cost files are half-written")

        hooklib.story_subagent_transcripts = explode
        hooklib.subagent_meta = explode
        check_eq("a helper that raises leaves the verdict unknown, never a closure",
                 LIVE.state(root, TICKET, dict(DISPATCH, started_at=time.time() - 9000))["state"],
                 LIVE.UNKNOWN)
    finally:
        without_hooklib()
        cleanup(root)


def a_codex_session_end_is_a_return():
    """The driver's own end row, as the Codex host writes it (SMOKE-1, 10.10: `host`, `usage`, a thread id as the
    session, no cost): the strongest proof this factory has that the role stopped, read the same as a Claude
    row. The `launched` row before it carries no exit code and proves nothing; the `in_flight` entry with a
    live pid, written by the same driver, proves the role at work until that end row exists."""
    root = temp_dir("qa-live-codex-end-")
    try:
        project(root)
        without_hooklib()
        state_dir = root / "qa-factory" / "artifacts" / TICKET / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        began = NOW - 900
        iso = lambda when: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(when))  # noqa: E731
        launched = {"ts": iso(began), "kind": "launched", "call": "role", "role": "qa-scout",
                    "dispatch_id": "S1-qa-scout-1", "stage": "S1", "started_at": iso(began),
                    "model": "host-default", "retry": 0, "host": "codex"}
        ended = {"ts": iso(began + 462), "kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1",
                 "stage": "S1", "session_id": "01a12611-aa9e-78d3-8c05-54de60d216f0", "num_turns": 17,
                 "total_cost_usd": None, "duration_ms": 462357, "resumed": False, "exit_code": 0,
                 "is_error": False, "model": "host-default", "host": "codex", "subtype": "success",
                 "infra": None, "infra_rule": None, "retry": 0,
                 "usage": {"input_tokens": 720821, "cached_input_tokens": 666368,
                           "cache_write_input_tokens": 0, "output_tokens": 5011}}
        rows = state_dir / "driver-runs.jsonl"
        dispatch = {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout", "started_at": began}

        rows.write_text(json.dumps(launched) + "\n", encoding="utf-8")
        verdict = LIVE.state(root, TICKET, dispatch, now=NOW)
        check_eq("a launched row (no exit code) is no return", verdict["state"], LIVE.UNKNOWN)
        check_eq("and the driver recorded no end", LIVE.driver_session_end(root, TICKET, "S1-qa-scout-1"), None)

        rows.write_text(json.dumps(launched) + "\n" + json.dumps(ended) + "\n", encoding="utf-8")
        verdict = LIVE.state(root, TICKET, dispatch, now=NOW)
        check_eq("the Codex driver's end row is a recorded return", verdict["state"], LIVE.RETURNED)
        check_eq("at the moment the row was written", verdict["last_at"], began + 462)
        check_in("named with the row and the exit code", "(exit 0) in state/driver-runs.jsonl",
                 " ".join(verdict["evidence"]))
        check_eq("the row is read by its dispatch", LIVE.driver_session_end(root, TICKET, "S1-qa-scout-1"),
                 (began + 462, 0))
        check_eq("and another dispatch's question finds nothing",
                 LIVE.driver_session_end(root, TICKET, "S1-qa-scout-2"), None)

        # while the role runs: the driver's in_flight entry (the pid of `codex exec`), the end row not yet written
        rows.write_text(json.dumps(launched) + "\n", encoding="utf-8")
        entry = {"dispatch_id": "S1-qa-scout-1", "pid": os.getpid(), "started_at": iso(began)}
        (state_dir / "driver-state.json").write_text(json.dumps(
            {"sessions": {}, "in_flight": {"S1-qa-scout-1": entry}}), encoding="utf-8")
        verdict = LIVE.state(root, TICKET, dispatch, now=NOW)
        check_eq("a live pid in the driver's own entry proves the role at work", verdict["state"], LIVE.ALIVE)
        check_in("and says which process", f"process {os.getpid()} for this dispatch is running",
                 " ".join(verdict["evidence"]))
    finally:
        without_hooklib()
        cleanup(root)


# --- t-009/t-971: the host's own `task_complete` for a story_step-bound native worker (TP2-2406 S4) --------

NATIVE = "/root/qa_case_designer__tp2_2406_3"
BOUND = NOW - 500          # young: the receipt itself would keep the dispatch alive
DONE = BOUND + 100         # a completion 400 s before NOW: past the 300 s grace window of a clean task_complete
GRACE = LIVE.NATIVE_COMPLETION_GRACE_S


def iso_at(epoch, naive=False):
    text = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch))
    return text if naive else text + ".000Z"


def native_receipt(root, agent=NATIVE, bound_at=BOUND, **fields):
    """The receipt `story_step.bind` writes (story_step.py: bound_by/bound_at), under the hash of the agent path."""
    import hashlib
    record = {"agent_id": agent, "agent_type": "qa-automator", "task_id": TICKET,
              "dispatch_id": DISPATCH["id"], "status": "running", "bound_by": "story_step", "bound_at": bound_at}
    record.update(fields)
    record = {key: value for key, value in record.items() if value is not None}
    path = root / "qa-factory" / "state" / "host-dispatches" / (hashlib.sha256(agent.encode()).hexdigest() + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def cost_record(root, thread, transcript_path):
    folder = root / "qa-factory" / "state" / "cost"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{thread}.json").write_text(json.dumps({"session_id": thread, "transcript": str(transcript_path)}),
                                           encoding="utf-8")


def native_rollout(root, thread, first_at, last_at, last="task_complete", agent=NATIVE, completed_at="same",
                   cost="transcript", digest_bytes=None, tail="clean", times="iso"):
    """A Codex child rollout (row 1 session_meta, a response_item, the last row) and its cost record.

    `last`: "task_complete", "turn_aborted" (another event_msg), "response_item" or "function_call".
    `cost`: "transcript" (names the rollout), "no-field", "missing-file" (names a file that is not there), "none".
    `tail`: "clean" (whole rows, a blank line at the end), "cut" (a half-written row after them), "garbage" (a whole
    line that is not JSON). `times`: "iso" (a zone), "naive" (no zone), "number" (20261013).
    """
    path = root / "codex" / f"rollout-{thread}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = {"iso": iso_at, "naive": lambda e: iso_at(e, naive=True), "number": lambda e: 20261013}[times]
    rows = [{"timestamp": stamp(first_at), "type": "session_meta",
             "payload": {"id": thread, "agent_path": agent, "parent_thread_id": "p-1"}},
            {"timestamp": stamp(first_at + 5), "type": "response_item", "payload": {"type": "message"}}]
    if last == "task_complete":
        done = last_at if completed_at == "same" else completed_at
        payload = {"type": "task_complete", "turn_id": "t-1",
                   "last_agent_message": "digest " * 4000 if digest_bytes is None else "d" * digest_bytes}
        if done is not None:
            payload["completed_at"] = done
        rows.append({"timestamp": stamp(last_at), "type": "event_msg", "payload": payload})
    elif last == "turn_aborted":
        rows.append({"timestamp": stamp(last_at), "type": "event_msg", "payload": {"type": "turn_aborted"}})
    else:
        rows.append({"timestamp": stamp(last_at), "type": last, "payload": {"type": "message"}})
    text = "\n".join(json.dumps(row) for row in rows) + "\n"
    text += {"clean": "\n", "cut": '{"timestamp": "' + iso_at(last_at + 1), "garbage": "not json at all\n"}[tail]
    path.write_text(text, encoding="utf-8")
    if cost != "none":
        record = {"session_id": thread}
        if cost != "no-field":
            record["transcript"] = str(path if cost == "transcript" else root / "codex" / "gone.jsonl")
        folder = root / "qa-factory" / "state" / "cost"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{thread}.json").write_text(json.dumps(record), encoding="utf-8")
    return path


def drop_rollout(root, thread):
    (root / "qa-factory" / "state" / "cost" / f"{thread}.json").unlink(missing_ok=True)


def clear_receipts(root):
    for found in (root / "qa-factory" / "state" / "host-dispatches").glob("*.json"):
        found.unlink()


def native_scene(prefix, **receipt_fields):
    root = scene(prefix)
    return root, native_receipt(root, **receipt_fields)


def says_returned(verdict):
    return "ends with task_complete" in " ".join(verdict["evidence"])


def a_completed_unaccepted_worker_is_a_return():
    """K1, the live S4 shape: rollout first row 40 s before `bound_at`, last row task_complete after it (older than the
    grace window), the receipt young and non-terminal. The host's own record decides; the receipt and the work are
    left alone."""
    root, receipt_file = native_scene("qa-live-native-done-")
    try:
        rollout = native_rollout(root, "t-done", BOUND - 40, DONE)
        before = receipt_file.read_bytes()
        verdict = verdict_at(root)
        check_eq("a young story_step receipt whose rollout ended with task_complete is a return",
                 verdict["state"], LIVE.RETURNED)
        check_eq("at the moment the host recorded", verdict["last_at"], DONE)
        check_in("the evidence names the rollout file", str(rollout), verdict["evidence"])
        check_in("and the host's own task_complete", "ends with task_complete", verdict["evidence"])
        check_in("and says the work is not accepted", "the work is not accepted", verdict["evidence"])
        check_eq("the receipt file is byte for byte as it was", receipt_file.read_bytes(), before)
        check_eq("and still says running, with no terminal_source made up",
                 [json.loads(before).get("status"), "terminal_source" in json.loads(before)], ["running", False])
        check("the controller's alive-check (`state(...)['state'] == ALIVE`) answers no", verdict["state"] != LIVE.ALIVE)
        no_time = native_rollout(root, "t-done", BOUND - 40, DONE, completed_at=None)
        check_eq("a task_complete row with no completed_at is still a return, judged by the row's own time",
                 [verdict_at(root)["state"], verdict_at(root)["last_at"]], [LIVE.RETURNED, DONE])
        check_in("still the same rollout", str(no_time), verdict_at(root)["evidence"])
        check_eq("a 200 KB last row (several read steps) is read whole",
                 [native_rollout(root, "t-done", BOUND - 40, DONE, digest_bytes=200_000).stat().st_size > 3 * 65536,
                  verdict_at(root)["state"]], [True, LIVE.RETURNED])
    finally:
        cleanup(root)


def a_working_native_worker_is_alive():
    """K2: a rollout still being written is ALIVE; written long ago and unfinished, today's receipt answers."""
    root, receipt_file = native_scene("qa-live-native-run-")
    try:
        rollout = native_rollout(root, "t-run", BOUND - 40, NOW - 10, last="response_item")
        verdict = verdict_at(root)
        check_eq("a rollout last written 10 s ago, not completed, is a worker at work", verdict["state"], LIVE.ALIVE)
        check_in("with the rollout as the evidence", str(rollout), verdict["evidence"])
        check_in("and 'has not completed'", "has not completed", verdict["evidence"])
        check_eq("rolled back to its last write", verdict["last_at"], NOW - 10)
        native_receipt(root, bound_at=NOW - 400)
        native_rollout(root, "t-run", NOW - 700, NOW - 601, last="response_item")
        silent = verdict_at(root)
        check_eq("silent past the window and young receipt: today's answer, alive by the receipt",
                 silent["state"], LIVE.ALIVE)
        check_in("which says the receipt", "host receipt of this dispatch was written", silent["evidence"])
        check_not_in("and not the rollout", "has not completed", silent["evidence"])
        native_receipt(root, bound_at=NOW - 5000)
        native_rollout(root, "t-run", NOW - 5000, NOW - 4900, last="response_item")
        old = verdict_at(root)
        check_eq("silent past the window and old receipt: unknown (silence is not death)", old["state"], LIVE.UNKNOWN)
        check_in("with the release text", "only a person's release closes it", old["evidence"])
    finally:
        cleanup(root)


def the_completion_has_a_grace_window():
    """B-3: the SubagentStop group (exit_gate, subagent_journal, cost_capture) may still send the worker back after
    its `task_complete`; a completion younger than `dispatch.native_completion_grace_s` is alive, AT the limit
    included, and a return only beyond it. The number is data (FR-13): the project's config moves it."""
    root, _receipt_file = native_scene("qa-live-native-grace-")
    try:
        check_eq("the default grace window is 300 s, in thresholds()",
                 [GRACE, LIVE.thresholds(root)["native_completion_grace_s"]], [300.0, 300.0])
        native_rollout(root, "t-g", BOUND - 40, NOW - 300)
        at = verdict_at(root)
        check_eq("a completion exactly 300 s old is still alive", at["state"], LIVE.ALIVE)
        check_in("said as 'still completing'", "its stop hooks may still send it back", at["evidence"])
        check_not_in("and not as the rollout still being written", "has not completed", at["evidence"])
        check_eq("last_at is the completion", at["last_at"], NOW - 300)
        native_rollout(root, "t-g", BOUND - 40, NOW - 301)
        beyond = verdict_at(root)
        check_eq("301 s old is a return", beyond["state"], LIVE.RETURNED)
        check_in("with the host's completion as the evidence", "ends with task_complete", beyond["evidence"])
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"dispatch": {"native_completion_grace_s": 120}}), encoding="utf-8")
        native_rollout(root, "t-g", BOUND - 40, NOW - 120)
        check_eq("a configured grace of 120 s: 120 s old is alive", verdict_at(root)["state"], LIVE.ALIVE)
        native_rollout(root, "t-g", BOUND - 40, NOW - 121)
        check_eq("and 121 s old is a return", verdict_at(root)["state"], LIVE.RETURNED)
        for bad in (0, -5, "300", True, None):
            (root / "qa-factory" / "config.json").write_text(
                json.dumps({"dispatch": {"native_completion_grace_s": bad}}), encoding="utf-8")
            check_eq(f"an unusable configured value ({bad!r}) is the default",
                     LIVE.thresholds(root)["native_completion_grace_s"], 300.0)
    finally:
        cleanup(root)


def an_ambiguous_rollout_is_not_a_return():
    """K3 (b)-(f): everything that is not the host's clean task_complete for THIS launch of THIS path."""
    root, receipt_file = native_scene("qa-live-native-ambiguous-")
    try:
        # (b) an earlier launch under the same path: first_at an hour before bound_at
        native_rollout(root, "t-earlier", BOUND - 3600, BOUND - 3000)
        earlier = verdict_at(root)
        check_eq("(b) a completed rollout of an earlier launch is ignored: today's alive-by-receipt",
                 earlier["state"], LIVE.ALIVE)
        check_not_in("(b) and is not quoted", "rollout-t-earlier", earlier["evidence"])
        check_eq("(b) the boundary: a start 300 s before bound_at is still this launch",
                 [native_rollout(root, "t-earlier", BOUND - 300, BOUND + 10) and verdict_at(root)["state"]],
                 [LIVE.RETURNED])
        check_eq("(b) and 301 s before is not",
                 [native_rollout(root, "t-earlier", BOUND - 301, BOUND + 10) and verdict_at(root)["state"]],
                 [LIVE.ALIVE])
        drop_rollout(root, "t-earlier")
        # (c) a cancel is not a return
        native_rollout(root, "t-abort", NOW - 700, NOW - 650, last="turn_aborted")
        aborted = verdict_at(root)
        check_eq("(c) a rollout that ends with turn_aborted is not a return (young receipt: alive by the receipt)",
                 aborted["state"], LIVE.ALIVE)
        check_not_in("(c) nor quoted as the host's completion", "ends with task_complete", aborted["evidence"])
        check_not_in("(c) nor as the rollout at work", "has not completed", aborted["evidence"])
        native_receipt(root, bound_at=NOW - 5000)
        native_rollout(root, "t-abort", NOW - 5000, NOW - 4900, last="turn_aborted")
        check_eq("(c) and with an old receipt it is unknown", verdict_at(root)["state"], LIVE.UNKNOWN)
        native_rollout(root, "t-abort", NOW - 20, NOW - 10, last="turn_aborted")
        young_abort = verdict_at(root)
        check_eq("edge 8 (A7): an abort written 10 s ago under an OLD receipt is unknown - not alive, not returned",
                 young_abort["state"], LIVE.UNKNOWN)
        native_rollout(root, "t-abort", NOW - 5000, NOW - 4900, last="function_call")
        check_eq("(c) a last row that is a call, long ago, is not a return either", verdict_at(root)["state"], LIVE.UNKNOWN)
        native_receipt(root)
        drop_rollout(root, "t-abort")
        # (d) a rollout for another path, completed
        native_rollout(root, "t-other", BOUND - 40, DONE, agent=NATIVE[:-1] + "2")
        check_eq("(d) a completed rollout of another path is ignored", verdict_at(root)["state"], LIVE.ALIVE)
        drop_rollout(root, "t-other")
        native_rollout(root, "t-longer", BOUND - 40, DONE, agent=NATIVE + "0")
        check_eq("(d) the match is exact: a completed rollout of a path that only BEGINS with the receipt's is ignored",
                 verdict_at(root)["state"], LIVE.ALIVE)
        drop_rollout(root, "t-longer")
        # (e) no cost file / no transcript field / transcript missing on disk
        for cost in ("none", "no-field", "missing-file"):
            native_rollout(root, "t-lost", BOUND - 40, DONE, cost=cost)
            check_eq(f"(e) cost record: {cost} - today's answer", verdict_at(root)["state"], LIVE.ALIVE)
        drop_rollout(root, "t-lost")
        broken = native_rollout(root, "t-broken", BOUND - 40, DONE)
        broken.write_text("{not json\n", encoding="utf-8")
        check_eq("(e) an unreadable first row is no evidence", verdict_at(root)["state"], LIVE.ALIVE)
        rows = native_rollout(root, "t-broken", BOUND - 40, DONE)
        rows.write_text(rows.read_text(encoding="utf-8").replace('"session_meta"', '"turn_context"'), encoding="utf-8")
        check_eq("(e) a first row that is not session_meta is no evidence", verdict_at(root)["state"], LIVE.ALIVE)
        drop_rollout(root, "t-broken")
        # (f) a receipt not bound by story_step, the same fields: unchanged behaviour
        native_rollout(root, "t-done", BOUND - 40, DONE)
        clear_receipts(root)
        native_receipt(root, bound_by=None)
        check_eq("(f) a spawn-time receipt (no bound_by story_step) is untouched: alive by its age",
                 verdict_at(root)["state"], LIVE.ALIVE)
        native_receipt(root, bound_by="host_dispatch")
        check_eq("(f) so is one bound by another writer", verdict_at(root)["state"], LIVE.ALIVE)
        clear_receipts(root)
        native_receipt(root, agent="not-a-path", bound_at=BOUND)
        native_rollout(root, "t-done", BOUND - 40, DONE, agent="not-a-path")
        check_eq("(f) and one whose agent_id is not a path", verdict_at(root)["state"], LIVE.ALIVE)
        clear_receipts(root)
        silent = native_receipt(root, bound_at=None)
        os.utime(silent, (NOW, NOW))       # no bound_at: the file time is the only time the receipt has
        check_eq("(f) a story_step receipt with no usable bound_at cannot say which launch: today's answer",
                 verdict_at(root)["state"], LIVE.ALIVE)
    finally:
        cleanup(root)


def a_terminal_receipt_with_a_completed_rollout_keeps_its_own_path():
    """K4: the receipt is already terminal - the `bound` RETURNED path of today, no rollout read, no exception."""
    root, _receipt_file = native_scene("qa-live-native-terminal-", status="terminal")
    try:
        native_rollout(root, "t-done", BOUND - 40, DONE)
        verdict = verdict_at(root)
        check_eq("a terminal receipt is a return as before", verdict["state"], LIVE.RETURNED)
        check_eq("with its own single line of evidence",
                 verdict["evidence"], ["the host dispatch receipt for this dispatch is terminal"])
    finally:
        cleanup(root)


def the_rollout_reader_reads_ends_only():
    root = scene("qa-live-native-reader-")
    try:
        check_eq("no cost folder: nothing", LIVE.native_rollouts(root), [])
        native_rollout(root, "t-big", BOUND - 40, DONE)
        rows = LIVE.native_rollouts(root)
        check_eq("one rollout", len(rows), 1)
        check_eq("with its agent path", rows[0]["agent_path"], NATIVE)
        check_eq("no parent thread: nothing reads one", "parent_thread_id" in rows[0], False)
        check_eq("its first and last time", [rows[0]["first_at"], rows[0]["last_at"]], [BOUND - 40, DONE])
        check_eq("its last row type, completion and tail", [rows[0]["last_type"], rows[0]["completed_at"], rows[0]["broken"]],
                 ["task_complete", DONE, False])
        native_rollout(root, "t-run", BOUND - 40, BOUND + 10, last="response_item")
        check_eq("a non-event last row reports its own type",
                 sorted(r["last_type"] for r in LIVE.native_rollouts(root)), ["response_item", "task_complete"])
        empty = root / "codex" / "rollout-t-empty.jsonl"
        empty.write_text("", encoding="utf-8")
        cost_record(root, "t-empty", empty)
        check_eq("an empty rollout file is skipped", len(LIVE.native_rollouts(root)), 2)
    finally:
        cleanup(root)


def a_time_nobody_can_place_is_no_evidence():
    """Edge 9 (A2): a row time with no zone reads as local here and UTC there, a bare number parses as a date; both
    decide nothing. The rollout stays a candidate (it cannot be ruled out) and can only hold a verdict back."""
    root, _receipt_file = native_scene("qa-live-native-naive-")
    try:
        for kind in ("naive", "number"):
            native_rollout(root, "t-naive", BOUND - 40, DONE, times=kind)
            rows = LIVE.native_rollouts(root)
            check_eq(f"{kind} times: the reader lists the rollout with no usable time",
                     [(r["first_at"], r["last_at"]) for r in rows], [(None, None)])
            verdict = verdict_at(root)
            check_eq(f"{kind} times: a completed rollout frees nothing - today's alive-by-receipt",
                     verdict["state"], LIVE.ALIVE)
            check_not_in(f"{kind} times: and is not quoted", "ends with task_complete", verdict["evidence"])
        native_rollout(root, "t-done", BOUND - 40, DONE)
        native_rollout(root, "t-naive", BOUND - 40, DONE, times="naive")
        check_eq("a good completion beside a rollout nobody can date is not a return (it may be this launch's)",
                 verdict_at(root)["state"], LIVE.ALIVE)
        check_not_in("...and says so by the receipt", "ends with task_complete", verdict_at(root)["evidence"])
    finally:
        cleanup(root)


def two_receipts_of_one_dispatch_are_read_together():
    """F-1: a running second receipt of the dispatch is never read as returned because the first one is."""
    other = NATIVE[:-1] + "2"
    root, _receipt_file = native_scene("qa-live-native-two-")
    try:
        native_rollout(root, "t-a", BOUND - 40, DONE)
        native_receipt(root, agent=other, bound_by=None)
        spawn_time = verdict_at(root)
        check_eq("story_step receipt returned + a spawn-time receipt of the dispatch: the age branch, alive",
                 spawn_time["state"], LIVE.ALIVE)
        check_in("by the young receipt", "host receipt of this dispatch was written", spawn_time["evidence"])
        check_not_in("not by the other receipt's completion", "ends with task_complete", spawn_time["evidence"])
        native_receipt(root, agent=other)
        silent = verdict_at(root)
        check_eq("returned + a story_step receipt with no rollout at all: the age branch as well",
                 silent["state"], LIVE.ALIVE)
        check_not_in("and no completion quoted", "ends with task_complete", silent["evidence"])
        drop_rollout(root, "t-a")
        for finished, running in ((NATIVE, other), (other, NATIVE)):      # both orders of the receipts
            native_rollout(root, "t-done", BOUND - 40, DONE, agent=finished)
            working = native_rollout(root, "t-run", BOUND - 40, NOW - 10, last="response_item", agent=running)
            alive = verdict_at(root)
            check_eq(f"one receipt returned, the other's rollout still being written ({running[-1]}): alive",
                     alive["state"], LIVE.ALIVE)
            check_in("by the working rollout", str(working), alive["evidence"])
        native_rollout(root, "t-run", BOUND - 40, DONE + 50, agent=NATIVE)
        both = verdict_at(root)
        check_eq("both receipts natively returned: returned", both["state"], LIVE.RETURNED)
        check_eq("at the later completion", both["last_at"], DONE + 50)
        check_in("both rollouts are the evidence", "rollout-t-run.jsonl", both["evidence"])
        check_in("the first too", "rollout-t-done.jsonl", both["evidence"])
    finally:
        cleanup(root)


def every_rollout_of_one_path_is_asked():
    """B-1 (L-2): a path can have several rollouts inside the window - a respawn, a resume. RETURNED needs EVERY
    candidate to be a settled completion; one still written, aborted or cut mid-row holds it back."""
    root, _receipt_file = native_scene("qa-live-native-many-")
    try:
        native_rollout(root, "t-new", BOUND + 60, DONE)
        working = native_rollout(root, "t-old", BOUND - 40, NOW - 5, last="response_item")
        mixed = verdict_at(root)
        check_eq("the newest rollout completed, an older one written 5 s ago: alive, not returned", mixed["state"], LIVE.ALIVE)
        check_in("by the older rollout", str(working), mixed["evidence"])
        native_rollout(root, "t-old", BOUND - 40, BOUND + 50)
        both = verdict_at(root)
        check_eq("both completed: returned", both["state"], LIVE.RETURNED)
        check_eq("at the later completion", both["last_at"], DONE)
        check_in("with both rollouts quoted", "rollout-t-old.jsonl", both["evidence"])
        check_in("...and the other", "rollout-t-new.jsonl", both["evidence"])
        native_receipt(root, bound_at=NOW - 5000)
        native_rollout(root, "t-new", NOW - 4990, NOW - 4900)
        native_rollout(root, "t-old", NOW - 4990, NOW - 4950, last="turn_aborted")
        held = verdict_at(root)
        check_eq("a completed rollout and an aborted sibling of the path: unknown, never returned", held["state"], LIVE.UNKNOWN)
        check_not_in("...and no completion is quoted", "ends with task_complete", held["evidence"])
    finally:
        cleanup(root)


def a_tail_being_written_holds_the_return_back():
    """F-1 (L-3): a rollout whose last line is cut mid-row (or garbage) is never a clean completion and blocks a
    return; it is alive only while the last WHOLE row is inside the grace window, so it can never be alive for ever."""
    root, _receipt_file = native_scene("qa-live-native-cut-")
    try:
        native_rollout(root, "t-done", BOUND - 40, DONE)
        cut = native_rollout(root, "t-cut", BOUND - 40, NOW - 10, last="response_item", tail="cut")
        written = verdict_at(root)
        check_eq("a sibling cut mid-row, its last whole row 10 s ago: alive", written["state"], LIVE.ALIVE)
        check_in("said as a row being written", "its last row is still being written", written["evidence"])
        check_in("by that rollout", str(cut), written["evidence"])
        native_receipt(root, bound_at=NOW - 5000)
        native_rollout(root, "t-done", NOW - 4990, NOW - 4900)
        native_rollout(root, "t-cut", NOW - 4990, NOW - 400, last="response_item", tail="cut")
        stale = verdict_at(root)
        check_eq("its last whole row 400 s ago (past the 300 s grace window, inside 600): not alive, and it still blocks "
                 "the return - unknown", stale["state"], LIVE.UNKNOWN)
        native_rollout(root, "t-cut", NOW - 4990, NOW - 4900, last="response_item", tail="cut")
        check_eq("a stale cut tail does not hold the dispatch alive either", verdict_at(root)["state"], LIVE.UNKNOWN)
        native_rollout(root, "t-cut", NOW - 4990, NOW - 400, last="response_item", tail="garbage")
        check_eq("a whole line that is not JSON blocks the return the same way", verdict_at(root)["state"], LIVE.UNKNOWN)
        drop_rollout(root, "t-done")
        native_receipt(root)
        lone = native_rollout(root, "t-cut", BOUND - 40, DONE, tail="cut")
        after = verdict_at(root)
        check_eq("a task_complete followed by a half-written row (the worker resumed) is not a return",
                 after["state"], LIVE.ALIVE)
        check_not_in("...the receipt answers", "ends with task_complete", after["evidence"])
        check_eq("the cut tail is listed as broken, its time the last whole row's",
                 [(r["broken"], r["last_at"], r["last_type"]) for r in LIVE.native_rollouts(root)],
                 [(True, DONE, "task_complete")])
        check("the cut file is the one read", lone.is_file())
    finally:
        cleanup(root)


def a_compressed_rollout_is_no_evidence_and_says_so():
    """L-2: all 107 rollouts on the owner's machine are `.jsonl.zst` and no decoder exists here. Such a rollout is
    never a candidate and never a return; the verdict says it could not be read (path-free, FR-41)."""
    root, _receipt_file = native_scene("qa-live-native-zst-")
    try:
        packed = root / "codex" / "rollout-t-z.jsonl.zst"
        packed.parent.mkdir(parents=True, exist_ok=True)
        packed.write_bytes(b"\x28\xb5\x2f\xfd" + bytes(range(1, 120)))
        cost_record(root, "t-z", packed)
        reasons = []
        check_eq("the reader skips it", LIVE.native_rollouts(root, reasons), [])
        check_eq("and names why", reasons, ["compressed (.zst), no decoder"])
        young = verdict_at(root)
        check_eq("a young receipt: alive by the receipt", young["state"], LIVE.ALIVE)
        check_in("the evidence says a rollout could not be read", "rollout unreadable: compressed (.zst), no decoder",
                 young["evidence"])
        check_not_in("without the path", "rollout-t-z", young["evidence"])
        native_receipt(root, bound_at=NOW - 5000)
        old = verdict_at(root)
        check_eq("an old receipt: unknown, never returned", old["state"], LIVE.UNKNOWN)
        check_in("with the same line", "rollout unreadable: compressed (.zst), no decoder", old["evidence"])
        native_receipt(root)
        native_rollout(root, "t-done", BOUND - 40, DONE)
        check_eq("a readable completed rollout beside it still decides", verdict_at(root)["state"], LIVE.RETURNED)
        garbage = root / "codex" / "rollout-t-bytes.jsonl"
        garbage.write_bytes(b"\xff\xfe\x00 not text\n")
        cost_record(root, "t-bytes", garbage)
        reasons = []
        LIVE.native_rollouts(root, reasons)
        check_eq("a file that is not text is named by its error", sorted(reasons),
                 ["compressed (.zst), no decoder", "could not be read (UnicodeDecodeError)"])
    finally:
        cleanup(root)


def a_file_that_is_not_a_rollout_is_never_tail_read():
    """t-1001 m-1 (spec A4): the first row and `agent_path` come first, the tail only for a file that matches. A Claude
    transcript (or the orchestrator's own rollout) in a cost record has its tail read by nobody, and a tail that cannot
    be read is not reported as "rollout unreadable" about a file nobody knows to be a rollout (FR-41)."""
    root, _receipt_file = native_scene("qa-live-native-notrollout-")
    real = LIVE._tail
    tails = []

    def failing_tail(path, *args, **kwargs):
        tails.append(Path(path).name)
        raise OSError("tail cannot be read")

    try:
        claude = root / "claude" / "session.jsonl"
        claude.parent.mkdir(parents=True, exist_ok=True)
        claude.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n" + "x" * 200000 + "\n",
                          encoding="utf-8")
        cost_record(root, "t-claude", claude)
        orchestrator = root / "claude" / "orchestrator.jsonl"
        orchestrator.write_text(json.dumps({"type": "session_meta", "payload": {"id": "o-1"}}) + "\n", encoding="utf-8")
        cost_record(root, "t-orch", orchestrator)           # a session_meta with NO agent_path: not a child rollout
        cost_record(root, "t-dir", root / "claude")          # a directory
        (root / "qa-factory" / "state" / "cost" / "t-none.json").write_text(json.dumps({"session_id": "t-none"}),
                                                                           encoding="utf-8")   # no transcript at all
        (root / "qa-factory" / "state" / "cost" / "t-list.json").write_text("[1, 2]", encoding="utf-8")
        LIVE._tail = failing_tail
        reasons = []
        check_eq("none of them is a rollout", LIVE.native_rollouts(root, reasons), [])
        check_eq("no tail of a non-rollout was read", tails, [])
        check_eq("and none is reported as an unreadable rollout", reasons, [])
        check_not_in("the verdict says nothing of an unreadable rollout", "rollout unreadable",
                     " ".join(verdict_at(root)["evidence"]))
        real_rollout = native_rollout(root, "t-real", BOUND - 40, DONE)
        reasons = []
        check_eq("a real rollout whose tail cannot be read is skipped", LIVE.native_rollouts(root, reasons), [])
        check_eq("its tail was asked for, once", tails, [real_rollout.name])
        check_eq("and it IS reported, by its error class", reasons, ["could not be read (OSError)"])
        check_in("in the verdict too", "rollout unreadable: could not be read (OSError)",
                 " ".join(verdict_at(root)["evidence"]))
    finally:
        LIVE._tail = real
        cleanup(root)


def an_untrusted_clock_neither_frees_nor_holds():
    """Edges 4, 5, 18: a last row more than the clock skew ahead of now is no evidence either way; a `completed_at`
    further ahead than the grace window (or in milliseconds) is not read - the row's own time stands."""
    root, _receipt_file = native_scene("qa-live-native-future-")
    try:
        native_rollout(root, "t-fut", BOUND - 40, NOW + 120, last="response_item")
        ahead = verdict_at(root)
        check_eq("an unfinished rollout dated 120 s ahead: the receipt branch decides (young: alive)",
                 ahead["state"], LIVE.ALIVE)
        check_not_in("not by the rollout", "has not completed", ahead["evidence"])
        native_receipt(root, bound_at=NOW - 5000)
        native_rollout(root, "t-fut", NOW - 5000, NOW + 120, last="response_item")
        check_eq("and with an old receipt it is unknown, not held alive until the clock catches up",
                 verdict_at(root)["state"], LIVE.UNKNOWN)
        native_receipt(root)
        native_rollout(root, "t-fut", BOUND - 40, NOW + 120)
        done = verdict_at(root)
        check_eq("a task_complete dated 120 s ahead frees nothing either", done["state"], LIVE.ALIVE)
        check_not_in("and is not quoted", "ends with task_complete", done["evidence"])
        check_eq("the boundary: dated exactly the skew ahead is still read (alive by the rollout)",
                 [native_rollout(root, "t-fut", BOUND - 40, NOW + 60, last="response_item")
                  and "has not completed" in " ".join(verdict_at(root)["evidence"])], [True])
        check_eq("and 61 s ahead is not",
                 [native_rollout(root, "t-fut", BOUND - 40, NOW + 61, last="response_item")
                  and "has not completed" in " ".join(verdict_at(root)["evidence"])], [False])
        native_rollout(root, "t-fut", BOUND - 40, DONE, completed_at=NOW + 300)
        soon = verdict_at(root)
        check_eq("a completed_at exactly the grace window ahead is read: the worker is still completing",
                 [soon["state"], soon["last_at"]], [LIVE.ALIVE, NOW + 300])
        native_rollout(root, "t-fut", BOUND - 40, DONE, completed_at=NOW + 301)
        check_eq("301 s ahead is not read: the row's own time (400 s ago) decides - a return",
                 [verdict_at(root)["state"], verdict_at(root)["last_at"]], [LIVE.RETURNED, DONE])
        native_rollout(root, "t-fut", BOUND - 40, DONE, completed_at=int(NOW * 1000))
        check_eq("a completed_at in milliseconds is not read either",
                 [verdict_at(root)["state"], verdict_at(root)["last_at"]], [LIVE.RETURNED, DONE])
    finally:
        cleanup(root)


def a_completion_before_bind_never_frees_this_launch():
    """B-2 (L-2): the receipt is keyed by the path, so a respawn rewrites it with a new `bound_at`; a rollout that
    ENDED before the receipt was written is an earlier launch. No skew in the freeing direction."""
    root, _receipt_file = native_scene("qa-live-native-before-bind-")
    try:
        native_rollout(root, "t-prev", BOUND - 200, BOUND - 30)
        before = verdict_at(root)
        check_eq("a completion 30 s before bind (the start inside the 300 s window) frees nothing",
                 before["state"], LIVE.ALIVE)
        check_not_in("and is not quoted", "ends with task_complete", before["evidence"])
        check_eq("the boundary: a completion AT bound_at is this launch's",
                 [native_rollout(root, "t-prev", BOUND - 200, BOUND) and verdict_at(root)["state"]], [LIVE.RETURNED])
        check_eq("and one second before is not",
                 [native_rollout(root, "t-prev", BOUND - 200, BOUND - 1) and verdict_at(root)["state"]], [LIVE.ALIVE])
        check_eq("`completed_at` is the completion when present: an old one under a late last row is not this launch's",
                 [native_rollout(root, "t-prev", BOUND - 200, BOUND + 10, completed_at=BOUND - 200)
                  and verdict_at(root)["state"]], [LIVE.ALIVE])
        check_eq("with no `completed_at` the last row's time decides",
                 [native_rollout(root, "t-prev", BOUND - 200, BOUND - 100, completed_at=None)
                  and verdict_at(root)["state"]], [LIVE.ALIVE])
        native_rollout(root, "t-prev", BOUND - 200, BOUND - 30)
        native_rollout(root, "t-now", BOUND + 10, DONE)
        check_eq("an earlier launch's completion beside this launch's own does not matter (this one decides)",
                 verdict_at(root)["state"], LIVE.RETURNED)
    finally:
        cleanup(root)


def the_last_row_is_read_to_the_byte():
    """Edge 1: a line break before the last line within the last `_LAST_ROW_CAP_BYTES` bytes - the row is read; one
    byte further - no evidence (never a guess). Tested by bytes, with the cap patched small."""
    root, _receipt_file = native_scene("qa-live-native-cap-")
    real = LIVE._LAST_ROW_CAP_BYTES
    try:
        LIVE._LAST_ROW_CAP_BYTES = cap = 4096

        def last_row(pad):
            return json.dumps({"timestamp": iso_at(DONE), "type": "event_msg", "payload": {
                "type": "task_complete", "completed_at": DONE, "last_agent_message": "d" * pad}})

        head = [{"timestamp": iso_at(BOUND - 40), "type": "session_meta",
                 "payload": {"id": "t-cap", "agent_path": NATIVE}},
                {"timestamp": iso_at(BOUND - 35), "type": "response_item", "payload": {"type": "message"}}]
        path = root / "codex" / "rollout-t-cap.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        cost_record(root, "t-cap", path)
        results = {}
        for extra in (0, 1):
            pad = cap - 2 - len(last_row(0)) + extra            # line break + row + final line break = cap + extra
            path.write_bytes(("\n".join(json.dumps(r) for r in head) + "\n" + last_row(pad) + "\n").encode("utf-8"))  # bytes: no CRLF
            results[extra] = (LIVE._tail(path) is not None, [(r["broken"], r["last_type"]) for r in LIVE.native_rollouts(root)],
                              verdict_at(root)["state"], says_returned(verdict_at(root)))
        check_eq("AT the cap (the line break is the first byte of the last cap bytes): the row is read, a return",
                 results[0], (True, [(False, "task_complete")], LIVE.RETURNED, True))
        check_eq("one byte BEYOND: no evidence - the rollout is broken, today's alive-by-receipt",
                 results[1], (False, [(True, None)], LIVE.ALIVE, False))
    finally:
        LIVE._LAST_ROW_CAP_BYTES = real
        cleanup(root)


def a_fresh_transcript_still_answers_first():
    """Edge 11 (P4 position): the native call stands after a fresh transcript of the dispatch and the driver's end
    row - a role at work is never declared returned."""
    root = scene("qa-live-native-position-")
    clock = time.time()
    try:
        native_receipt(root, bound_at=clock - 500)
        native_rollout(root, "t-done", clock - 540, clock - 400)
        fake_hooklib([transcript(root, "one", DISPATCH["id"], age=12)])
        verdict = LIVE.state(root, TICKET, dict(DISPATCH, started_at=clock - 900))
        check_eq("a transcript written 12 s ago answers alive before the rollout is read", verdict["state"], LIVE.ALIVE)
        check_in("by the transcript", "agent-one.jsonl was written", verdict["evidence"])
        check_not_in("not by the rollout", "task_complete", verdict["evidence"])
        without_hooklib()
        check_eq("without the transcript the same scene is the rollout's return",
                 LIVE.state(root, TICKET, dict(DISPATCH, started_at=clock - 900))["state"], LIVE.RETURNED)
    finally:
        without_hooklib()
        cleanup(root)


def a_failing_native_reader_leaves_todays_answer():
    """A9: the helper is a veto helper - when it fails it proves nothing, so the receipt branch answers."""
    root, _receipt_file = native_scene("qa-live-native-raises-")
    real = LIVE.native_stop
    try:
        native_rollout(root, "t-done", BOUND - 40, DONE)
        check_eq("(control) the same scene returns", verdict_at(root)["state"], LIVE.RETURNED)

        def boom(*_args, **_kwargs):
            raise RuntimeError("boom")
        LIVE.native_stop = boom
        broken = verdict_at(root)
        check_eq("a reader that raises: today's answer, alive by the receipt", broken["state"], LIVE.ALIVE)
        check_in("which says the receipt", "host receipt of this dispatch was written", broken["evidence"])
    finally:
        LIVE.native_stop = real
        cleanup(root)


# --- OH3-16 (HF1-7): the host's acknowledged handback of a story_step-bound Claude Code worker -----------------------

from datetime import datetime, timezone  # noqa: E402

import host_adapter as HA  # noqa: E402
import runtime_paths as RP  # noqa: E402

REAL_HOOKLIB = (hooklib.story_subagent_transcripts, hooklib.subagent_meta)   # earlier tests delete or fake these two
FORMS = json.loads((SCRIPTS.parent / "references" / "host-report-forms.json").read_text(encoding="utf-8"))
HANDBACK = FORMS["claude"]["handback_tool"]
ACK_OK = '{"success":true,"message":"Report delivered to your caller."}'
CLAUDE = "a5b4b2e19d35048ea"       # a Claude receipt's agent_id: the transcript stem's id, not a path
ACK = NOW - 650                    # past the grace window and past abandoned_after_s: the control (no handback) is UNKNOWN


def real_hooklib():
    hooklib.story_subagent_transcripts, hooklib.subagent_meta = REAL_HOOKLIB


def r_prompt(at, dispatch=DISPATCH["id"], ticket=TICKET, role="qa-automator"):
    return {"type": "user", "timestamp": iso_at(at), "_at": at,
            "message": {"role": "user", "content": f"You are {role}. Ticket: {ticket}. Dispatch: {dispatch}.\n"}}   # the real form of `story_step._prompt`


def r_text(at, text="working"):
    return {"type": "assistant", "timestamp": iso_at(at), "_at": at,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def r_call(at, use_id="toolu_1", name=HANDBACK, payload=None):
    return {"type": "assistant", "timestamp": iso_at(at), "_at": at, "_h": True, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": name, "input": {"message": "report"} if payload is None else payload}]}}


def r_ack(at, use_id="toolu_1", body=ACK_OK, error=None, stamped="iso", content="list"):
    block = {"type": "tool_result", "tool_use_id": use_id,
             "content": [{"type": "text", "text": body}] if content == "list" else body}
    if error is not None:
        block["is_error"] = error
    row = {"type": "user", "_at": at, "_h": True, "message": {"role": "user", "content": [block]}}
    if stamped:
        row["timestamp"] = iso_at(at, naive=stamped == "naive")
    return row


def handback(at, use_id="toolu_1", name=HANDBACK, payload=None, **ack):
    """The two rows of a handback: the call, then the host's acknowledgement 1 s later (the call is `at - 1`)."""
    return [r_call(at - 1, use_id=use_id, name=name, payload=payload), r_ack(at, use_id=use_id, **ack)]


def control_of(rows):
    """The same rows with the handback replaced by plain assistant text (the control of every battery letter)."""
    return [r_text(row["_at"]) if row.get("_h") else row for row in rows]


def claude_scene(prefix, rows, agent=CLAUDE, bound_at=None, meta="done", stops=(), tail="", receipt=None, name=None,
                 thread="sess", grace=None):
    """A Claude-shaped project: `state/cost/<s>.json` -> `<s>.jsonl` -> `<s>/subagents/agent-<id>.jsonl` (+ its
    `.meta.json`), a story_step receipt with a bare agent id, and the journal's stop lines as the hook writes them."""
    root = scene(prefix)
    real_hooklib()
    if grace is not None:
        (root / "qa-factory" / "config.json").write_text(json.dumps({"dispatch": {"native_completion_grace_s": grace}}),
                                                         encoding="utf-8")
    stem = name or agent
    path = root / "sessions" / thread / "subagents" / f"agent-{stem}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("".join(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}) + "\n" for row in rows)
                      + tail).encode("utf-8"))
    cost_record(root, thread, root / "sessions" / f"{thread}.jsonl")
    side = path.with_name(f"agent-{stem}.meta.json")
    if meta == "dir":
        side.mkdir()
    elif meta is not None:
        side.write_text({"done": '{"agentType": "critic", "finished": true}', "false": '{"finished": false}', "empty": "",
                         "nokey": '{"agentType": "critic"}', "string": '{"finished": "false"}', "null": '{"finished": null}',
                         "garbage": "{not json"}[meta], encoding="utf-8")
    acks = [row["_at"] for row in rows if row.get("_h") and row.get("message", {}).get("role") == "user"]
    bound = (acks[-1] if acks else NOW - 700) - 100 if bound_at is None else bound_at
    receipt_file = native_receipt(root, agent=agent, bound_at=bound, **(receipt or {}))
    for status, at, extra in stops:
        journal = RP.record(root, "journal.jsonl")
        journal.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds"), "event": "subagent_stop",
                "agent": "qa-factory:qa-automator", "task": TICKET, "dispatch": DISPATCH["id"], "status": status,
                "dispatch_receipt": receipt_file.name, "return_owner": "story_step"}
        line.update(extra)
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(line) + "\n")
    return root, receipt_file, path


def incident_rows(ack=ACK, **kw):
    return [r_prompt(ack - 3000), r_text(ack - 2000), *handback(ack, **kw)]


def answer(root, **dispatch):
    return verdict_at(root, **dispatch)["state"]


def with_forms(content):
    """Point the one reader at a forms file holding `content` (None: no such file); returns the restore function."""
    saved = HA.REPORT_FORMS_FILE
    holder = temp_dir("qa-live-forms-")
    target = holder / "forms.json"
    if content == "dir":
        target.mkdir()
    elif content is not None:
        target.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    HA.REPORT_FORMS_FILE = target

    def restore():
        HA.REPORT_FORMS_FILE = saved
        cleanup(holder)
    return restore


def the_incident_is_a_return():
    """K-L1: a critic handed back at T (the call, the host's acknowledgement), meta `finished: true`, its stop hook wrote
    `completed` at T+3 naming the receipt: RETURNED at T+81 and at T+650; the receipt is left alone. K-L8: the same
    scene with the receipt terminal (the hook's `record` marked it) and non-terminal."""
    for age in (81, 650):
        at = NOW - age
        root, receipt_file, path = claude_scene("qa-live-claude-incident-", incident_rows(at), stops=[("completed", at + 3, {})])
        try:
            before = receipt_file.read_bytes()
            verdict = verdict_at(root)
            evidence = " ".join(verdict["evidence"])
            check_eq(f"K-L1: handed back {age}s ago, the stop hook let it go: RETURNED", verdict["state"], LIVE.RETURNED)
            check_eq(f"K-L1: at the moment of the acknowledgement ({age}s)", verdict["last_at"], at)
            check(f"K-L1: the evidence names the transcript, the acknowledgement's time and that nothing is accepted ({age}s)",
                  str(path) in evidence and LIVE._iso(at) in evidence and "not accepted" in evidence)
            check_in(f"K-L1: and the sidecar's flag as an extra line ({age}s)", "finished: true", verdict["evidence"])
            check_eq(f"K-L1: the receipt is byte for byte as it was, still running ({age}s)",
                     (receipt_file.read_bytes() == before, json.loads(before)["status"]), (True, "running"))
            terminal = json.loads(before)
            terminal.update(status="terminal", terminal_source="SubagentStop")
            receipt_file.write_text(json.dumps(terminal), encoding="utf-8")
            after = verdict_at(root)["state"]
            plain_root, _r, _p = claude_scene("qa-live-claude-incident-plain-", control_of(incident_rows(at)),
                                              stops=[("completed", at + 3, {})])
            try:
                receipt_file_plain = next((plain_root / "qa-factory/state/host-dispatches").glob("*.json"))
                plain = json.loads(receipt_file_plain.read_text(encoding="utf-8"))
                plain.update(status="terminal")
                receipt_file_plain.write_text(json.dumps(plain), encoding="utf-8")
                check_eq(f"K-L8: the same scene with the receipt terminal answers as it always did, with or without the handback ({age}s)",
                         after, answer(plain_root))
            finally:
                cleanup(plain_root)
            if age == 650:
                check_eq("K-L8: past the freshness window both receipts say RETURNED", after, LIVE.RETURNED)
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)


def the_hooks_window():
    """K-L2: with no stop line the grace window holds a handback back AT the grace, and frees it one second beyond.
    K-L3: a stop line AT ack - 1.0 s closes the window, ack - 1.01 s does not. K-L4: an `incomplete` stop at or after the
    acknowledgement vetoes, even past the grace window."""
    grace = LIVE.NATIVE_COMPLETION_GRACE_S
    for beyond, expect in ((0, LIVE.ALIVE), (1, LIVE.RETURNED)):
        at = NOW - grace - beyond
        root, _r, _p = claude_scene("qa-live-claude-grace-", incident_rows(at), meta=None)
        try:
            check_eq(f"K-L2: no stop line, handed back {int(grace) + beyond}s ago", answer(root), expect)
            claude = LIVE.claude_stop(root, LIVE.host_bindings(root)[0], NOW, LIVE.thresholds(root))
            check_eq(f"K-L2: claude_stop says the same ({int(grace) + beyond}s)", (claude or {}).get("state"), expect)
            if beyond == 0:
                check_in("K-L2: and says the stop hooks may still send it back", "may still send it back", claude["evidence"])
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)
    at = NOW - 100
    for label, when, expect in (("AT ack - 1.0 s", at - 1.0, LIVE.RETURNED), ("BEYOND, ack - 1.01 s", at - 1.01, LIVE.ALIVE),
                                ("at the ack", at, LIVE.RETURNED)):
        root, _r, _p = claude_scene("qa-live-claude-tolerance-", incident_rows(at), stops=[("completed", when, {})])
        try:
            claude = LIVE.claude_stop(root, LIVE.host_bindings(root)[0], NOW, LIVE.thresholds(root))
            check_eq(f"K-L3: a released stop line {label}", (claude or {}).get("state"), expect)
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)
    for label, status in (("incomplete", "incomplete"), ("an unnamed status", "")):
        root, _r, _p = claude_scene("qa-live-claude-veto-", incident_rows(ACK), stops=[("completed", ACK + 2, {}), (status, ACK + 3, {})])
        try:
            check(f"K-L4: a stop line {label} at the acknowledgement vetoes, even past the grace window",
                  LIVE.claude_stop(root, LIVE.host_bindings(root)[0], NOW, LIVE.thresholds(root)) is None
                  and answer(root) != LIVE.RETURNED)
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)


def the_battery():
    """K-L5 (a)-(u): 21 inputs, none of which may give RETURNED, each against its control (the same scene with the
    handback rows replaced by plain assistant text) - the answer equals the control's."""
    results = {}

    def run(letter, label, rows, expect=None, **scene_kw):
        root, _r, _p = claude_scene("qa-live-claude-battery-", rows, **scene_kw)
        try:
            ctl_root, _r2, _p2 = claude_scene("qa-live-claude-control-", control_of(rows), **{
                k: v for k, v in scene_kw.items() if k not in ("stops",)})
            try:
                want = answer(ctl_root) if expect is None else expect
            finally:
                real_hooklib()
                cleanup(ctl_root)
            got = answer(root)
            results.setdefault(letter, []).append((label, got != LIVE.RETURNED and got == want, f"{got!r} want {want!r}"))
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)

    base = lambda **kw: incident_rows(ACK, **kw)  # noqa: E731
    run("a", "a call, no acknowledgement", [r_prompt(ACK - 3000), r_text(ACK - 2000), r_call(ACK, use_id="toolu_9")])
    run("b", "success false", base(body='{"success":false}'))
    run("c", "is_error true", base(error=True))
    run("d", "not JSON", base(body="Report delivered to your caller."))
    run("e", "success is the word true", base(body='{"success":"true"}'))
    run("f", "an acknowledgement of another tool's call", [r_prompt(ACK - 3000), r_call(ACK - 1, use_id="toolu_9", name="Read"),
                                                       r_ack(ACK, use_id="toolu_9", body='{"success":true}')])
    # t-075 (survivor t060-M3): the call row carries the RIGHT name but ANOTHER call's id; the acknowledgement answers
    # `toolu_9`. Two tool_use rows in the same window - an earlier handback call `toolu_9` and the row before the
    # acknowledgement `toolu_8` - so only the id equality tells the row that made the call from a row of the same name.
    run("f", "an acknowledgement naming another call's id, the row before it a handback call of this name",
        [r_prompt(ACK - 3000), r_call(ACK - 3, use_id="toolu_9"), r_call(ACK - 1, use_id="toolu_8"),
         r_ack(ACK, use_id="toolu_9")])
    run("f", "the same with only ONE tool_use row: the acknowledgement's id is nobody's",
        [r_prompt(ACK - 3000), r_call(ACK - 1, use_id="toolu_8"), r_ack(ACK, use_id="toolu_9")])
    for name in (HANDBACK.lower(), HANDBACK + " ", "mcp__x__" + HANDBACK):
        run("g", f"the tool named {name!r}", base(name=name))
    run("h", "finished false, a released stop", base(), meta="false", stops=[("completed", ACK + 3, {})])
    run("i", "finished true, the last row plain text", [r_prompt(ACK - 3000), r_text(ACK)])
    run("j", "rows after the last acknowledgement", base() + [r_text(NOW - 5), r_text(NOW - 3)], expect=LIVE.ALIVE)
    root, _r, path = claude_scene("qa-live-claude-battery-", base(), tail='{"type": "assistant", "timestamp": "')
    try:
        ctl_root, _r2, _p2 = claude_scene("qa-live-claude-control-", control_of(base()), tail='{"type": "assistant", "timestamp": "')
        want = answer(ctl_root)
        real_hooklib()
        cleanup(ctl_root)
        results.setdefault("k", []).append(("cut mid-row after the acknowledgement", answer(root) == want != LIVE.RETURNED, ""))
    finally:
        real_hooklib()
        without_hooklib()
        cleanup(root)
    for label, stamped in (("no timestamp", None), ("a zone-less one", "naive")):
        run("l", label, [r_prompt(ACK - 3000), r_call(ACK - 1), r_ack(ACK, stamped=stamped)])
    run("l", "ahead of the clock by two minutes", [r_prompt(ACK - 3000), r_call(NOW + 119), r_ack(NOW + 120)], expect=None)
    run("m", "a role-and-ticket-only transcript with a perfect handback (another agent, another dispatch)",
        [r_prompt(ACK - 3000, dispatch="S5-qa-automator-1"), *handback(ACK)], name="zzz-other")
    run("o", "a worker re-dispatched: the receipt of -2, the acknowledgement older than its bound_at, the prompt names -1",
        [r_prompt(ACK - 3000, dispatch="S5-qa-automator-1"), *handback(ACK)], bound_at=ACK + 100)
    real_hooklib()
    for label, content in (("forms file absent", None), ("forms file unreadable", "dir"), ("{}", "{}"),
                           ("handback_tool a list", {"claude": dict(FORMS["claude"], handback_tool=[HANDBACK])}),
                           ("no handback_ack", {"claude": {k: v for k, v in FORMS["claude"].items() if k != "handback_ack"}})):
        restore = with_forms(content)
        root, _r, _p = claude_scene("qa-live-claude-battery-", base())
        try:
            verdict = verdict_at(root)
            results.setdefault("p", []).append((label, verdict["state"] == LIVE.UNKNOWN and "host report forms" in " ".join(
                verdict["evidence"]), f"{verdict['state']} {verdict['evidence']}"))
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)
            restore()
    for label, extra in (("another task", {"task": "OTHER-1"}), ("another dispatch", {"dispatch": "S5-qa-automator-9",
                                                                                   "dispatch_receipt": "other.json"}),
                         ("no receipt, no dispatch", {"dispatch": "", "dispatch_receipt": ""})):
        run("q", f"a released stop line of {label}", base(), expect=LIVE.ALIVE, grace=900, stops=[("completed", ACK + 2, extra)])
    run("r", "a released stop line BEFORE the acknowledgement (240 s)", base(), expect=LIVE.ALIVE, grace=900,
        stops=[("completed", ACK - 240, {})])
    run("s", "an incomplete stop at the acknowledgement", base(), stops=[("incomplete", ACK + 1, {})])
    # (t) a Codex rollout that did not complete, and a Codex receipt beside a returned Claude one
    root, _r, _p = claude_scene("qa-live-claude-battery-", base())
    try:
        native_receipt(root, agent=NATIVE, bound_at=ACK - 100)
        native_rollout(root, "t-run", ACK - 140, NOW - 5, last="response_item")
        results.setdefault("t", []).append(("a Codex rollout still being written beside a handed-back Claude one",
                                            answer(root) == LIVE.ALIVE, answer(root)))
        drop_rollout(root, "t-run")
        results["t"].append(("a Codex receipt with no rollout beside a handed-back Claude one",
                             answer(root) != LIVE.RETURNED, answer(root)))
    finally:
        real_hooklib()
        without_hooklib()
        cleanup(root)
    # (u) any helper raising
    root, _r, _p = claude_scene("qa-live-claude-battery-", base())
    real_vote, real_votes = LIVE._claude_vote, LIVE._claude_votes
    try:
        check_eq("(control) the scene returns", answer(root), LIVE.RETURNED)

        def boom(*_a, **_k):
            raise RuntimeError("boom")
        for helper in ("_claude_vote", "_claude_votes", "_stop_records", "_tail"):
            saved = getattr(LIVE, helper)
            setattr(LIVE, helper, boom)
            try:
                got = answer(root)
                results.setdefault("u", []).append((f"{helper} raising", got != LIVE.RETURNED, got))
            finally:
                setattr(LIVE, helper, saved)
    finally:
        LIVE._claude_vote, LIVE._claude_votes = real_vote, real_votes
        real_hooklib()
        without_hooklib()
        cleanup(root)
    # (n) needs its own second transcript: written fresh, naming the dispatch
    root, _r, _p = claude_scene("qa-live-claude-battery-", base())
    try:
        second = root / "sessions" / "sess" / "subagents" / "agent-second.jsonl"
        second.write_text(json.dumps({k: v for k, v in r_prompt(NOW - 60).items() if not k.startswith("_")}) + "\n"
                          + json.dumps({k: v for k, v in r_text(NOW - 5).items() if not k.startswith("_")}) + "\n", encoding="utf-8")
        results["n"] = [("a second transcript of the dispatch still being written: ALIVE", answer(root) == LIVE.ALIVE, answer(root)),
                        ("and claude_stop alone does not call the dispatch returned (every transcript votes)",
                         LIVE.claude_stop(root, LIVE.host_bindings(root)[0], NOW, LIVE.thresholds(root)) is None, "")]
    finally:
        real_hooklib()
        without_hooklib()
        cleanup(root)
    # the control of (n) and (j) is ALIVE (fresh rows): the letter's answer is not RETURNED either way
    for letter, kind in zip("abcdefghijklmnopqrstu", range(21)):
        rows = results.get(letter, [])
        check(f"K-L5({letter}) {rows[0][0] if len(rows) == 1 else str(len(rows)) + ' variants'}: not RETURNED, as its control",
              bool(rows) and all(ok for _label, ok, _why in rows),
              "; ".join(f"{label}: {why}" for label, ok, why in rows if not ok))


def an_ack_line_without_a_line_break_is_still_being_written():
    """t-075 (survivor t060-M4). `_tail` says whether the last line was followed by a line break; a line without one is
    still being written (the rule `codex_usage.scan` applies) and `_claude_vote` reads nothing from it - even when it is
    already COMPLETE JSON, which the cut-mid-row case K-L5(k) does not reach (a parse refuses that one anyway). The same
    bytes with the break are the acknowledgement: RETURNED. A line cut mid-row stays unread either way."""
    call_rows = [r_prompt(ACK - 3000), r_text(ACK - 2000), r_call(ACK - 1)]
    ack_line = json.dumps({k: v for k, v in r_ack(ACK).items() if not k.startswith("_")})
    outcomes = {}
    for label, tail in (("whole and broken off", ack_line), ("whole with its break", ack_line + "\n"),
                        ("cut mid-row", ack_line[:-12])):
        root, _r, path = claude_scene("qa-live-claude-linebreak-", call_rows, tail=tail)
        try:
            outcomes[label] = (answer(root), LIVE._tail(path)[2])
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)
    ctl_root, _r, _p = claude_scene("qa-live-claude-linebreak-ctl-", control_of(call_rows), tail=ack_line)
    try:
        want = answer(ctl_root)
    finally:
        real_hooklib()
        without_hooklib()
        cleanup(ctl_root)
    check_eq("K-L5(j2): a complete ack line with no line break is not read (the answer is the control's, not RETURNED)",
             (outcomes["whole and broken off"][0] == want, outcomes["whole and broken off"][0] != LIVE.RETURNED), (True, True))
    check_eq("K-L5(j2): `_tail` says it is not whole", outcomes["whole and broken off"][1], False)
    check_eq("K-L5(j2) twin: the same bytes WITH the line break are the host's acknowledgement - RETURNED",
             (outcomes["whole with its break"][0], outcomes["whole with its break"][1]), (LIVE.RETURNED, True))
    check_eq("K-L5(j2) twin: a line cut mid-row is not read (and not whole)",
             (outcomes["cut mid-row"][0] == want, outcomes["cut mid-row"][1]), (True, False))


def a_mixed_verdict_set_is_none_by_the_rule_not_by_a_swallowed_error():
    """t-075 (survivors t060-M11a / M11b). `all(...)` -> `any(...)` in `_native_verdict` and in `claude_stop` was green as
    typed: with one RETURNED verdict and one None the `any` branch then fails inside `max(...)` over the None, and the
    `except Exception` around it (`claude_stop`'s own, `_state`'s around `_native_verdict`) turned that into the very
    answer the rule gives. The outcome alone cannot tell the two apart, so the key asserts BOTH: the outcome is None AND no
    `max(...)` over the set raised on the way (`dispatch_liveness.max` is a recorder over the builtin; the rule gives its
    answer before any `max` is asked of a set holding a non-RETURNED member)."""
    import builtins
    raised = []

    def spy(*args, **kwargs):
        try:
            return builtins.max(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - recorded, then raised again exactly as the builtin did
            raised.append(repr(exc))
            raise
    check("(setup) the module has no `max` of its own to shadow", not hasattr(LIVE, "max"))
    base_rows = incident_rows(ACK)
    limits = None
    # _native_verdict: a handed-back Claude receipt and a Codex receipt the host says nothing about (no rollout)
    root, _r, _p = claude_scene("qa-live-claude-mixed-native-", base_rows)
    try:
        native_receipt(root, agent=NATIVE, bound_at=ACK - 100)
        limits = LIVE.thresholds(root)
        waiting = LIVE.host_bindings(root)
        check_eq("(setup) two non-terminal receipts of the dispatch", len(waiting), 2)
        check_eq("(control) the Claude receipt alone is RETURNED", LIVE.host_verdict(root, next(
            b for b in waiting if LIVE._claude_receipt(b)), NOW, limits)["state"], LIVE.RETURNED)
        LIVE.max = spy
        try:
            try:
                got, _notes = LIVE._native_verdict(root, waiting, NOW, limits)
                error = None
            except Exception as exc:  # noqa: BLE001 - reported by the check below
                got, error = "raised", repr(exc)
        finally:
            del LIVE.max
        check_eq("t060-M11a: one RETURNED and one nothing: the outcome is None, and no error was taken on the way",
                 (got, error, raised), (None, None, []))
        check("t060-M11a: and the dispatch is not RETURNED either", answer(root) != LIVE.RETURNED)
    finally:
        real_hooklib()
        without_hooklib()
        cleanup(root)
    # claude_stop: one transcript handed back (RETURNED) and a second one of the dispatch that is silent and handed nothing back
    root, _r, _p = claude_scene("qa-live-claude-mixed-stop-", base_rows)
    try:
        second = root / "sessions" / "sess" / "subagents" / "agent-second.jsonl"
        second.write_text("".join(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}) + "\n"
                                  for row in (r_prompt(ACK - 3000), r_text(ACK - 2000))), encoding="utf-8")
        receipt = LIVE.host_bindings(root)[0]
        votes = [vote["state"] for _meta, vote in LIVE._claude_votes(root, receipt, NOW, LIVE.thresholds(root), {})]
        check_eq("(setup) two transcripts vote: one RETURNED, one nothing", sorted(map(str, votes)),
                 sorted(map(str, [LIVE.RETURNED, None])))
        raised.clear()
        LIVE.max = spy
        try:
            got = LIVE.claude_stop(root, receipt, NOW, LIVE.thresholds(root))
        finally:
            del LIVE.max
        check_eq("t060-M11b: one RETURNED vote and one nothing: claude_stop is None, and no error was taken on the way",
                 (got, raised), (None, []))
        check("t060-M11b: and the dispatch is not RETURNED either", answer(root) != LIVE.RETURNED)
    finally:
        real_hooklib()
        without_hooklib()
        cleanup(root)


def an_empty_report_is_still_a_return():
    """K-L6 (F5): a handback with empty fields, acknowledged: RETURNED - the host recorded it; RETURNED is not acceptance."""
    for payload in ({}, {"message": ""}):
        root, _r, _p = claude_scene("qa-live-claude-empty-", [r_prompt(ACK - 3000), r_call(ACK - 1, payload=payload), r_ack(ACK)])
        try:
            check_eq(f"K-L6: an acknowledged handback with the fields {payload!r}", answer(root), LIVE.RETURNED)
        finally:
            real_hooklib()
            without_hooklib()
            cleanup(root)


def two_routes_to_the_transcript():
    """K-L7: a transcript answers to the receipt by its file's id in `binding_names` OR by a first prompt naming the
    dispatch and ticket; the foreground road (bound AFTER the handback) is returned through the prompt anchor."""
    rows = incident_rows(ACK)
    root, _r, _p = claude_scene("qa-live-claude-routes-", rows, agent="misspelled-id", name=CLAUDE, bound_at=ACK + 100)
    try:
        check_eq("K-L7: a misspelled id in the receipt still finds the transcript through the dispatch id in its prompt",
                 answer(root), LIVE.RETURNED)
    finally:
        real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    nameless = [r_prompt(ACK - 3000, dispatch="none-named"), *handback(ACK)]
    nameless[0]["message"]["content"] = "You are a critic.\n"
    root, _r, _p = claude_scene("qa-live-claude-routes-", nameless)
    try:
        check_eq("K-L7: the name route: the file's id is the receipt's agent_id, the acknowledgement is at or after bound_at",
                 answer(root), LIVE.RETURNED)
    finally:
        real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    root, _r, _p = claude_scene("qa-live-claude-routes-", rows, agent="other", receipt={"task_name": CLAUDE}, name=CLAUDE)
    try:
        check_eq("K-L7: `binding_names` reads task_name too (the one reader of receipt names)", answer(root), LIVE.RETURNED)
    finally:
        real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    root, _r, _p = claude_scene("qa-live-claude-routes-", rows, bound_at=ACK + 100)
    try:
        check_eq("K-L7(b): bound AFTER the handback, the prompt names the dispatch: RETURNED (the foreground road)",
                 answer(root), LIVE.RETURNED)
    finally:
        real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    root, _r, _p = claude_scene("qa-live-claude-routes-", [r_prompt(ACK - 3000, dispatch="S5-qa-automator-1"), *handback(ACK)],
                                bound_at=ACK + 100)
    try:
        check("K-L7(b): the same agent resumed for -2 (the prompt names -1), bound after the handback: not RETURNED",
              answer(root) != LIVE.RETURNED)
    finally:
        real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
def journal_and_sidecar_cases():
    """K-L11 journal absent/unreadable; K-L12 sidecar absent, unreadable, empty, no key, non-boolean; K-L13 the cap."""
    for label, make in (("absent", None), ("a directory", "dir"), ("garbage lines", "garbage")):
        for age, expect in ((100, LIVE.ALIVE), (650, LIVE.RETURNED)):
            root, _r, _p = claude_scene("qa-live-claude-journal-", incident_rows(NOW - age), meta=None)
            try:
                journal = RP.record(root, "journal.jsonl")
                journal.parent.mkdir(parents=True, exist_ok=True)
                if make == "dir":
                    journal.mkdir()
                elif make:
                    journal.write_bytes(b"\xff\xfe not json\n{\n")
                check_eq(f"K-L11: journal {label}, handed back {age}s ago: the grace window decides alone", answer(root), expect)
            finally:
                real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    for meta in (None, "dir", "empty", "nokey", "string", "null", "garbage"):
        root, _r, _p = claude_scene("qa-live-claude-meta-", incident_rows(ACK), meta=meta)
        try:
            verdict = verdict_at(root)
            check(f"K-L12: sidecar {meta or 'absent'}: no veto, no evidence line", verdict["state"] == LIVE.RETURNED
                  and "finished: true" not in " ".join(verdict["evidence"]), str(verdict))
        finally:
            real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    saved, cap = LIVE._LAST_ROW_CAP_BYTES, 4096
    try:
        LIVE._LAST_ROW_CAP_BYTES = cap
        for extra, expect in ((0, LIVE.RETURNED), (1, LIVE.UNKNOWN)):
            ack_row = json.dumps({k: v for k, v in r_ack(ACK).items() if not k.startswith("_")})
            pad = cap - 3 - len(ack_row) - len(json.dumps({k: v for k, v in r_call(ACK - 1, payload={"message": ""}).items()
                                                           if not k.startswith("_")})) + extra
            rows = [r_prompt(ACK - 3000), r_call(ACK - 1, payload={"message": "d" * pad}), r_ack(ACK)]
            root, _r, path = claude_scene("qa-live-claude-cap-", rows)
            try:
                check_eq(f"K-L13: the call row + the acknowledgement fill the cap exactly +{extra}", answer(root), expect)
            finally:
                real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    finally:
        LIVE._LAST_ROW_CAP_BYTES = saved


def nothing_else_changes():
    """K-L14: a Claude dispatch with no receipt keeps today's answers; the Codex completion event comes from the forms
    through the one reader (F6): with the forms file gone a completed rollout is no return, and it says so."""
    for label, rows, expect in (("handed back and silent", incident_rows(ACK), LIVE.ABANDONED),
                                ("still being written", [r_prompt(NOW - 60), r_text(NOW - 5)], LIVE.ALIVE)):
        real_hooklib()
        root = scene("qa-live-claude-noreceipt-")
        real_hooklib()
        path = root / "sessions" / "sess" / "subagents" / f"agent-{CLAUDE}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}) + "\n" for row in rows),
                        encoding="utf-8")
        cost_record(root, "sess", root / "sessions" / "sess.jsonl")
        try:
            check_eq(f"K-L14: no receipt, {label}: today's answer", answer(root), expect)
        finally:
            real_hooklib(); without_hooklib(); cleanup(root)  # noqa: E702
    for content, label in ((None, "absent"), ({"claude": FORMS["claude"]}, "without a codex row")):
        restore = with_forms(content)
        root, _receipt_file = native_scene("qa-live-native-noforms-")
        try:
            native_rollout(root, "t-done", BOUND - 40, DONE)
            verdict = verdict_at(root)
            check_eq(f"F6: forms {label}: a completed rollout is no return (today's receipt branch answers)", verdict["state"], LIVE.ALIVE)
            check_in(f"F6: forms {label}: and the evidence says the forms could not be read", "host report forms", verdict["evidence"])
        finally:
            restore()
            without_hooklib()
            cleanup(root)


def a_stop_counts_only_for_its_own_dispatch():
    """TR4-12 (1): two dispatches of one role; a stop that names the SIBLING leaves the asked one unanswered
    (UNKNOWN, as with no stop), a stop that names the asked one is its return, a stop naming no dispatch keeps
    today's answer and the evidence says it was read by role."""
    def answer_for(stop_dispatch, host_receipt=False):
        # host_receipt: the host's receipt of the role names no dispatch and carries the host id HOST, and an old
        # transcript of the role exists (so the answer reaches the journal's stop rows, not the receipt branch)
        began = time.time() - (6000 if host_receipt else 600)
        asked = {"id": "S3-qa-test-strategist-2", "stage": "S3", "role": "qa-test-strategist", "started_at": began}
        root = temp_dir("qa-live-sibling-")
        try:
            project(root)
            journal = root / "qa-factory" / "records" / "journal.jsonl"
            journal.parent.mkdir(parents=True, exist_ok=True)
            row = {"event": "subagent_stop", "agent": "qa-factory:qa-test-strategist", "task": TICKET,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(began + 60))}
            if stop_dispatch is not None:
                row["dispatch"] = stop_dispatch
            journal.write_text(json.dumps(row) + "\n", encoding="utf-8")
            if host_receipt:
                receipt(root, name=HOST_ID, agent_type="qa-test-strategist", dispatch_id="")
                fake_hooklib([transcript(root, "old", "S3-qa-test-strategist-1", role="qa-test-strategist", age=5000)])
            else:
                without_hooklib()
            return LIVE.state(root, TICKET, asked)
        finally:
            without_hooklib()
            cleanup(root)

    from exit_gate import UNKNOWN_DISPATCH

    check_eq("a sibling of the same role stopped: the asked dispatch is not closed by it",
             answer_for("S3-qa-test-strategist-1")["state"], LIVE.UNKNOWN)
    check_eq("the asked dispatch's own stop is its return", answer_for("S3-qa-test-strategist-2")["state"], LIVE.RETURNED)
    nameless = answer_for(None)
    check_eq("a stop row without an id keeps today's answer", nameless["state"], LIVE.RETURNED)
    check_in("and says it was read by role", "names no dispatch", nameless["evidence"])
    sentinel = answer_for(UNKNOWN_DISPATCH)
    check_eq("F-1: a stop carrying the gate's sentinel names no dispatch: today's answer", sentinel["state"], LIVE.RETURNED)
    check_in("F-1: and says it was read by role", "names no dispatch", sentinel["evidence"])
    own = answer_for(HOST_ID, host_receipt=True)
    check_eq("F-1: a stop carrying this dispatch's own host id (a receipt name) is its return", own["state"], LIVE.RETURNED)
    check_not_in("F-1: and it is not read as nameless", "names no dispatch", own["evidence"])
    sibling = answer_for("a-sibling-host-id", host_receipt=True)
    check_eq("F-1: a stop carrying a sibling's host id does not close it", sibling["state"], LIVE.ABANDONED)
    check_eq("F-1: the sentinel is the gate's one name", UNKNOWN_DISPATCH, "unknown-dispatch")


def main():
    a_stop_counts_only_for_its_own_dispatch()
    a_host_that_proves_nothing_closes_nothing()
    a_working_agent_is_alive()
    a_silent_agent_is_abandoned()
    a_launch_that_never_happened()
    a_role_that_stopped_is_a_return()
    the_host_receipts_still_count()
    a_stale_prior_receipt_names_another_dispatch()
    a_receipt_is_good_for_the_window_and_no_longer()
    a_recorded_time_outranks_the_file_time()
    an_unusable_recorded_time_counts_as_absent()
    a_clock_ahead_is_skew_up_to_a_minute()
    a_receipt_with_no_time_at_all_is_unknown()
    host_bindings_carry_the_file_time()
    several_receipts_of_one_dispatch()
    both_hosts_answer_a_stale_receipt_the_same_way()
    a_receipt_never_outranks_better_evidence_and_never_closes()
    an_unbound_receipt_counts_only_if_it_may_be_this_dispatch()
    a_binding_of_another_story_proves_nothing_here()
    the_thresholds_are_a_project_setting()
    a_broken_helper_never_decides_anything()
    a_codex_session_end_is_a_return()
    a_completed_unaccepted_worker_is_a_return()
    a_working_native_worker_is_alive()
    the_completion_has_a_grace_window()
    an_ambiguous_rollout_is_not_a_return()
    a_terminal_receipt_with_a_completed_rollout_keeps_its_own_path()
    the_rollout_reader_reads_ends_only()
    a_time_nobody_can_place_is_no_evidence()
    two_receipts_of_one_dispatch_are_read_together()
    every_rollout_of_one_path_is_asked()
    a_tail_being_written_holds_the_return_back()
    a_compressed_rollout_is_no_evidence_and_says_so()
    a_file_that_is_not_a_rollout_is_never_tail_read()
    an_untrusted_clock_neither_frees_nor_holds()
    a_completion_before_bind_never_frees_this_launch()
    the_last_row_is_read_to_the_byte()
    a_fresh_transcript_still_answers_first()
    a_failing_native_reader_leaves_todays_answer()
    the_incident_is_a_return()
    the_hooks_window()
    the_battery()
    an_ack_line_without_a_line_break_is_still_being_written()
    a_mixed_verdict_set_is_none_by_the_rule_not_by_a_swallowed_error()
    an_empty_report_is_still_a_return()
    two_routes_to_the_transcript()
    journal_and_sidecar_cases()
    nothing_else_changes()
    finish("test_dispatch_liveness")


if __name__ == "__main__":
    main()
