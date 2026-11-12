"""HF7-4 (t-1518 DP-4): the turn that starts an activity is the activity's, the person is told from the rest of the
`user` rows by DATA, and a folder under `qa-factory/state/` is never a task.

Three readers of one transcript meet here (AR-13, AR-15): `task_from_path` (which task a Write belongs to),
`user_line_kind` (whose turn a `user` row is: the person's, a background task's, or neither) and
`start_turn_activities` (the activity list in which an activity's first segment also owns the turn that started it).
The fixture is SYNTHETIC (see its README.txt): the rules are pinned, the numbers of a real stand are not.

Keys: K1 state folders are not tasks; K2/K5 a chat turn that starts a story is the story's and `human_wait` follows
the same list; K3 an onboarding turn is onboarding's, a chat after its closure is nobody's, no row says "onboarding"
as a task; K4 the edges of `start_turn_activities`; K6 a checkpoint of another reader or another rule is rebuilt;
K7 the classifier and the wait time; K8 the host row's shape and the unreadable-forms side.
"""
import contextlib
import copy
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
import host_adapter as HA
from harness import temp_project, cleanup, check, check_eq, finish

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-start-turn"
MONEY_KEYS = {"cost", "subtotal_usd", "total_cost_usd", "priced_subtotal_usd", "priced_subtotal_exact_usd"}
DOLLAR_DIGIT = re.compile(r"\$\s?\d")
PERSONAL_PATH = re.compile(r"C:\\Users\\|/Users/|/home/", re.IGNORECASE)
CHAT, ONBOARDING = "synthetic-start-turn-chat", "synthetic-start-turn-onboarding"


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def segment(start, end=None, sid=None):
    return {"segment_id": sid or f"seg-{start}", "start_time": start, "end_time": end}


def activity(aid, kind, *segments, task=None):
    return {"activity_id": aid, "type": kind, "task": task, "segments": list(segments)}


def starts(result):
    """{activity id: [start_time of each segment]} of an activity list."""
    return {a["activity_id"]: [s["start_time"] for s in a["segments"]] for a in result}


def money_findings(root: Path):
    """What a fixture directory carries that it must not: a money field with a non-zero value, `$` + digit, a personal path."""
    found = []

    def walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in MONEY_KEYS and item not in (None, 0, "0", 0.0):
                    found.append(f"{where}: {key}={item!r}")
                walk(item, where)
        elif isinstance(value, list):
            for item in value:
                walk(item, where)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if DOLLAR_DIGIT.search(text):
            found.append(f"{path.name}: dollar + digit")
        if PERSONAL_PATH.search(text):
            found.append(f"{path.name}: personal path")
        if path.suffix == ".json":
            walk(json.loads(text), path.name)
        if path.suffix == ".jsonl":
            for line in text.splitlines():
                walk(json.loads(line), path.name)
    return found


def fixture_clean():
    check_eq("the fixture carries no money and no personal path", money_findings(FIXTURE), [])
    work = Path(tempfile.mkdtemp(prefix="qa-start-turn-control-"))
    try:
        for source in FIXTURE.iterdir():
            (work / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (work / "README.txt").write_text("it cost $1.00 in " + "C:" + chr(92) + "Users" + chr(92) + "someone", encoding="utf-8")
        row = json.loads((work / "onboarding.jsonl").read_text(encoding="utf-8").splitlines()[1])
        row["message"]["usage"]["subtotal_usd"] = "1"
        (work / "onboarding.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        found = money_findings(work)
        check("negative control: a `$1.00`, a personal path and a non-zero money field are all found",
              any("dollar" in f for f in found) and any("personal" in f for f in found)
              and any("subtotal_usd" in f for f in found), str(found))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def k1_state_is_not_a_task():
    state_folders = ["onboarding", "words", "retired", "probe-copies", "config-reverts", "created-accounts",
                     "reporter-unread", "integrations", "activities", "host-dispatches", "TP1-1"]
    for name in state_folders:
        check_eq(f"K1: a Write under qa-factory/state/{name}/ is no task",
                 C.task_from_path(f"project/qa-factory/state/{name}/x.json"), None)
    check_eq("K1: the same with backslashes", C.task_from_path("project\\qa-factory\\state\\onboarding\\notes.md"), None)
    check_eq("K1: a file straight under state/ is no task", C.task_from_path("project/qa-factory/state/journal.jsonl"), None)
    check_eq("K1 control: a task folder under artifacts/ is the task",
             C.task_from_path("project/qa-factory/artifacts/TP1-12586/work/x.md"), "TP1-12586")
    check_eq("K1 control: the same with backslashes",
             C.task_from_path("project\\qa-factory\\artifacts\\TP1-12586\\work\\x.md"), "TP1-12586")
    check_eq("K1: a factory folder under artifacts/ is skipped to the task under it",
             C.task_from_path("project/qa-factory/artifacts/cost/TP1-1/x.json"), "TP1-1")
    check_eq("K1: a file under artifacts/ with a dot is no task", C.task_from_path("project/qa-factory/artifacts/x.json"), None)
    check_eq("K1: NOT_A_TASK did not grow", C.NOT_A_TASK, {"cost", "surface", "audit", "releases", "requirements"})
    check_eq("K1: no path, no task", C.task_from_path(""), None)
    # the stand's shape: the Write is no marker, so the scan names no task
    markers = C.scan_file(FIXTURE / "onboarding.jsonl", person_rule=C._person_rule())[2]
    check_eq("K1: a Write into state/onboarding/ in a transcript leaves no task marker", markers, [])


def k7_user_line_kinds():
    rule = C._person_rule()
    check("K7: the shipped rule is read", isinstance(rule, dict) and rule["flags"] and rule["notification_prefixes"])

    def row(content, **extra):
        return dict({"type": "user", "isSidechain": False, "message": {"role": "user", "content": content}}, **extra)
    table = [
        ("the person's text", row("hello"), "person"),
        ("a text block of a list", row([{"type": "text", "text": "hello"}]), "person"),
        ("the first text block decides, an image before it is skipped", row([{"type": "image"}, {"type": "text", "text": "hi"}]), "person"),
        ("a tool result", row([{"type": "tool_result", "tool_use_id": "t", "content": "x"}], promptId="p"), "other"),
        ("a tool result next to a text", row([{"type": "text", "text": "hi"}, {"type": "tool_result"}]), "other"),
        ("isMeta", row("hello", isMeta=True), "other"),
        ("isCompactSummary", row("hello", isCompactSummary=True), "other"),
        ("a notification", row("<task-notification>done</task-notification>"), "notification"),
        ("a notification after blanks", row("  \n<task-notification>done"), "notification"),
        ("a notification in a text block", row([{"type": "text", "text": "<task-notification>x"}]), "notification"),
        ("a command row is the person's", row("<command-message>skill</command-message>"), "person"),
        ("a command's isMeta row is not", row("<command-name>x</command-name>", isMeta=True), "other"),
        ("an empty text", row(""), "other"),
        ("a blank text", row("   \n"), "other"),
        ("a list with no text", row([{"type": "image"}]), "other"),
        ("an empty list", row([]), "other"),
        ("a dict as content", row({"text": "hello"}), "other"),
        ("a number as content", row(7), "other"),
        ("no content", {"type": "user", "isSidechain": False, "message": {}}, "other"),
        ("no message", {"type": "user", "isSidechain": False}, "other"),
        ("a message that is not an object", {"type": "user", "message": "hello"}, "other"),
        ("a role's own row (isSidechain)", row("hello", isSidechain=True), None),
        ("an assistant row", {"type": "assistant", "message": {"content": "x"}}, None),
        ("a row that is not an object", "hello", None),
        ("None", None, None),
    ]
    for label, record, expected in table:
        check_eq(f"K7: {label} -> {expected}", C.user_line_kind(record, rule), expected)
    # the fixture, row by row, through the scan
    events = C.scan_file(FIXTURE / "user-forms.jsonl", person_rule=rule)[5]
    check_eq("K7: the scan keeps the person's two rows and the one notification, and nothing else",
             [(ts.strftime("%H:%M:%S"), kind) for ts, kind in events if kind != "assistant"],
             [("08:00:00", "human"), ("08:00:16", "notification"), ("08:00:18", "human")])
    wait, interactions = C.human_wait(events, [], 1800)
    check_eq("K7: the wait is the one answer after the assistant's row (13 s), not the notification's or the meta rows",
             (wait, interactions), (13.0, 1))
    legacy = C.scan_file(FIXTURE / "user-forms.jsonl", person_rule=False)[5]
    check_eq("K7: with the rule unreadable the old predicate stands: every `user` row with a promptId is a human event",
             [kind for _ts, kind in legacy if kind != "assistant"], ["human"] * 6)
    check("K7: the wait is then NOT the right one (this is the reading the rule replaces)",
          C.human_wait(legacy, [], 1800) != (13.0, 1))
    # human_wait: a notification is neither an answer nor a starting point; other kinds are skipped too
    base = at("2026-10-01T08:00:00Z")
    stamp = lambda s: datetime(2026, 10, 1, 8, 0, s, tzinfo=timezone.utc)
    mixed = [(stamp(0), "assistant"), (stamp(10), "notification"), (stamp(20), "human"), (stamp(25), "other")]
    check_eq("K7: human_wait counts only the human event (20 s), the notification before it changes nothing",
             C.human_wait(mixed, [], 1800), (20.0, 1))
    check_eq("K7: human_wait at the cap and beyond it", (C.human_wait(mixed, [], 20), C.human_wait(mixed, [], 19)),
             ((20.0, 1), (19.0, 1)))
    check_eq("K7: human_wait of no events", C.human_wait([], [], 1800), (0.0, 0))
    check_eq("K7: a human event before any assistant row is no wait", C.human_wait([(base, "human")], [], 1800), (0.0, 0))


def k4_edges():
    openers = [(at("2026-10-01T09:00:00Z"), "human"), (at("2026-10-01T09:30:00Z"), "human")]
    one = [activity("a", "story", segment("2026-10-01T09:31:00Z"), task="T")]
    check_eq("K4: the start moves to the LAST opener at or before it, not the first",
             starts(C.start_turn_activities(one, openers)), {"a": [at("2026-10-01T09:30:00Z").isoformat()]})
    check_eq("K4: an opener AT the start moves nothing", starts(C.start_turn_activities(
        one, [(at("2026-10-01T09:31:00Z"), "human")])), {"a": ["2026-10-01T09:31:00Z"]})
    check_eq("K4: an opener AFTER the start is not used", starts(C.start_turn_activities(
        one, [(at("2026-10-01T09:32:00Z"), "human")])), {"a": ["2026-10-01T09:31:00Z"]})
    check_eq("K4: no opener at all (Codex, a driver's `claude -p`): unchanged", starts(C.start_turn_activities(
        one, [(at("2026-10-01T09:30:00Z"), "assistant")])), {"a": ["2026-10-01T09:31:00Z"]})
    check_eq("K4: a notification opens a turn too (F-16 (a))", starts(C.start_turn_activities(
        one, [(at("2026-10-01T09:00:00Z"), "human"), (at("2026-10-01T09:30:30Z"), "notification")])),
        {"a": [at("2026-10-01T09:30:30Z").isoformat()]})
    check_eq("K4: no events", starts(C.start_turn_activities(one, [])), {"a": ["2026-10-01T09:31:00Z"]})
    check_eq("K4: events that are not pairs are skipped", starts(C.start_turn_activities(
        one, [None, 7, ("x",), ("not a time", "human"), (at("2026-10-01T09:30:00Z"), "human")])),
        {"a": [at("2026-10-01T09:30:00Z").isoformat()]})
    # a nested start: the parent's segment is closed AT the child's start (activity_capture), the child is not widened
    nested = [activity("onb", "onboarding", segment("2026-10-01T10:00:00Z", "2026-10-01T12:24:10Z", "o1"),
                       segment("2026-10-01T12:30:00Z", None, "o2")),
              activity("doc", "doctor", segment("2026-10-01T12:24:10Z", "2026-10-01T12:30:00Z", "d1"))]
    events = [(at("2026-10-01T09:59:00Z"), "human"), (at("2026-10-01T12:23:50Z"), "human")]
    moved = starts(C.start_turn_activities(nested, events))
    check_eq("K4: a nested start is bounded by the end of the parent's segment: the doctor does not move",
             moved["doc"], ["2026-10-01T12:24:10Z"])
    check_eq("K4: the parent moves to its own opener and ONLY its first segment moves",
             moved["onb"], [at("2026-10-01T09:59:00Z").isoformat(), "2026-10-01T12:30:00Z"])
    # a nested start whose parent segment is still OPEN (a hand-made file): bounded too
    open_parent = [activity("p", "onboarding", segment("2026-10-01T10:00:00Z", None, "p1")),
                   activity("c", "doctor", segment("2026-10-01T10:10:00Z", None, "c1"))]
    check_eq("K4: an open segment of another activity that began before the start is a boundary", starts(
        C.start_turn_activities(open_parent, [(at("2026-10-01T10:05:00Z"), "human")]))["c"], ["2026-10-01T10:10:00Z"])
    # two activities started in one turn: the second is not widened over the first
    two = [activity("a", "story", segment("2026-10-01T10:00:00Z", "2026-10-01T10:00:05Z"), task="A"),
           activity("b", "story", segment("2026-10-01T10:00:05Z", None), task="B")]
    got = starts(C.start_turn_activities(two, [(at("2026-10-01T09:59:50Z"), "human")]))
    check_eq("K4: two starts in one turn: the first takes the turn, the second is not widened",
             got, {"a": [at("2026-10-01T09:59:50Z").isoformat()], "b": ["2026-10-01T10:00:05Z"]})
    gap = [activity("a", "story", segment("2026-10-01T10:00:00Z", "2026-10-01T10:00:03Z"), task="A"),
           activity("b", "story", segment("2026-10-01T10:00:05Z", None), task="B")]
    got = starts(C.start_turn_activities(gap, [(at("2026-10-01T09:59:50Z"), "human")]))
    check_eq("K4: a gap after the first's end is the second's, never over the first's own segment",
             got["b"], [at("2026-10-01T10:00:03Z").isoformat()])
    # a turn that started nothing, a start in the next turn: only the starting turn is the activity's
    check_eq("K4: the turn that started no activity stays where it was", starts(C.start_turn_activities(
        [activity("a", "story", segment("2026-10-01T09:11:00Z"))], openers[:1] + [(at("2026-10-01T09:10:00Z"), "human")])),
        {"a": [at("2026-10-01T09:10:00Z").isoformat()]})
    # a segment boundary of ANOTHER activity ended before the opener: the opener is the later bound
    ended = [activity("x", "doctor", segment("2026-10-01T09:00:00Z", "2026-10-01T09:05:00Z")),
             activity("y", "story", segment("2026-10-01T09:20:00Z"), task="Y")]
    check_eq("K4: an earlier segment's end below the opener does not pull the start earlier than the opener", starts(
        C.start_turn_activities(ended, [(at("2026-10-01T09:10:00Z"), "human")]))["y"], [at("2026-10-01T09:10:00Z").isoformat()])
    check_eq("K4: an opener inside the earlier segment is bounded by that segment's end", starts(
        C.start_turn_activities(ended, [(at("2026-10-01T09:02:00Z"), "human")]))["y"], [at("2026-10-01T09:05:00Z").isoformat()])
    # resumed segments are as recorded; the first is the EARLIEST by time, not by position
    resumed = [activity("s", "story", segment("2026-10-01T11:00:00Z", None, "s2"), segment("2026-10-01T10:00:00Z", "2026-10-01T10:30:00Z", "s1"), task="S")]
    got = C.start_turn_activities(resumed, [(at("2026-10-01T09:50:00Z"), "human"), (at("2026-10-01T10:45:00Z"), "human")])
    check_eq("K4: only the earliest segment moves, whichever place it holds in the list",
             [(s["segment_id"], s["start_time"]) for s in got[0]["segments"]],
             [("s2", "2026-10-01T11:00:00Z"), ("s1", at("2026-10-01T09:50:00Z").isoformat())])
    # unreadable data changes nothing and never raises
    odd = [activity("a", "story", segment("not a time")), activity("b", "story", {"segment_id": "x", "start_time": None}),
           {"activity_id": "c", "type": "story", "segments": "nope"}, {"activity_id": "d", "type": "story"},
           "text", None, activity("e", "unclassified", segment("2026-10-01T09:31:00Z")),
           activity("f", "story", segment("2026-10-01T09:31:00Z", "not a time"))]
    before = copy.deepcopy(odd)
    got = C.start_turn_activities(odd, openers)
    check_eq("K4: unreadable times, odd shapes and an `unclassified` activity are passed through whole",
             [x for i, x in enumerate(got) if i != 7], [x for i, x in enumerate(odd) if i != 7])
    check_eq("K4: the input is never mutated", odd, before)
    check_eq("K4: not a list -> returned as it came", (C.start_turn_activities(None, openers), C.start_turn_activities("x", openers)), (None, "x"))
    check_eq("K4: an empty list", C.start_turn_activities([], openers), [])
    # a naive time against an aware one cannot be ordered: nothing moves, nothing raises
    naive = [(datetime(2026, 10, 1, 9, 30), "human")]
    check_eq("K4: a naive opener against an aware start moves nothing", starts(C.start_turn_activities(one, naive)),
             {"a": ["2026-10-01T09:31:00Z"]})
    result = C.start_turn_activities(one, openers)
    check("K4: the answer is a new list; the activity that did not move is the same object",
          result is not one and C.start_turn_activities(one, [])[0] is one[0])
    check("K4: the moved activity is a copy, the input's segment is untouched", one[0]["segments"][0]["start_time"] == "2026-10-01T09:31:00Z"
          and result[0] is not one[0])


def run_in_project(root: Path, session: str, fixture: str, binding=None, transcript_text=None):
    """The Stop hook's capture on a temp project: the fixture transcript and activities in place, `_capture` in-process
    (the unreadable-forms test needs to move the forms file, which a child process would not see). The cost document.
    `binding` (a dict) is a child dispatch's host binding file; `transcript_text` replaces the fixture transcript's bytes."""
    transcript = root / "transcripts" / f"{session}.jsonl"
    transcript.parent.mkdir(exist_ok=True)
    if transcript_text is None:
        shutil.copy(FIXTURE / f"{fixture}.jsonl", transcript)
    else:
        transcript.write_text(transcript_text, encoding="utf-8")
    activities = root / "qa-factory" / "state" / "activities"
    activities.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE / f"{fixture}.activities.json", activities / f"{session}.json")
    event = {"hook_event_name": "Stop", "session_id": session, "transcript_path": str(transcript), "cwd": str(root)}
    if binding is not None:
        bound = root / "transcripts" / f"{session}.binding.json"
        bound.write_text(json.dumps(binding), encoding="utf-8")
        event["host_binding"] = str(bound)
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        C._capture(event)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
    return json.loads((root / "qa-factory" / "state" / "cost" / f"{session}.json").read_text(encoding="utf-8"))


def owners(doc):
    return {r["request_id"]: (r["activity_id"], r["task"]) for r in doc["requests"] if r.get("stream") == "orchestrator"}


def tokens_by_activity(doc):
    return {aid: v["tokens"] for aid, v in doc["by_activity"].items()}


def k2_k5_chat_turn_is_the_stories(root):
    doc = run_in_project(root, CHAT, "chat-story")
    got = owners(doc)
    for rid in ("rA3", "rA4", "rA5", "rA6", "rA7"):
        check_eq(f"K2: {rid} (the turn that started the story, and after it) is the story's", got[rid], ("act-story", "SYN-1"))
    for rid in ("rA1", "rA2"):
        check_eq(f"K2: {rid} (a turn that started nothing) stays Unclassified", got[rid][0], "unclassified")
    check_eq("K2: Unclassified holds the first turn only (110 + 120 tokens), the second turn is not in it",
             tokens_by_activity(doc).get("unclassified"), 110 + 120)
    check_eq("K5: the sum by activity is the sum of the transcript (110+120 + 1200): a turn is moved, never created",
             sum(tokens_by_activity(doc).values()), 1430)
    check_eq("K5: the story's tokens: 220 + 230 + 240 + 250 + 260", tokens_by_activity(doc)["act-story"], 1200)
    check_eq("K5: the wait before the story's turn is no wait inside the story: only the 09:12 answer counts (60 s, 1)",
             (doc["human_wait_s"], doc["interactions"]), (60, 1))
    check_eq("K5: the story's active time is read from the moved segment: gaps 5 + 15 + 35 + 65 s between its five requests",
             doc["by_activity"]["act-story"]["active_s"], 120)


def k3_onboarding_turn_and_closure(root):
    doc = run_in_project(root, ONBOARDING, "onboarding")
    got = owners(doc)
    for rid in ("rB1", "rB2", "rB3", "rB4"):
        check_eq(f"K3: {rid} (before and after the onboarding start) is the onboarding's", got[rid][0], "act-onboarding")
    for rid in ("rB5", "rB6"):
        check_eq(f"K3: {rid} (a chat after the closure) is Unclassified", got[rid][0], "unclassified")
    check_eq("K3: no row names a task 'onboarding'", [r["request_id"] for r in doc["requests"] if r.get("task") == "onboarding"], [])
    check_eq("K3: and by_task has no such task", "onboarding" in doc["by_task"], False)
    check_eq("K3: the Write into state/onboarding/ opened no task: the rows carry '(no task)'",
             {t for _a, t in got.values()}, {"(no task)"})


def k6_checkpoints():
    path = FIXTURE / "onboarding.jsonl"
    rule = C._person_rule()
    first = C.scan_file_incremental(path, None, [], person_rule=rule)
    checkpoint = first[-1]
    check_eq("K6: a checkpoint keeps the fingerprint of the rule it was made with", checkpoint["person_forms"], C.content_hash(rule))
    legacy = C.scan_file_incremental(path, None, [], person_rule=False)[-1]
    check_eq("K6: a scan with no readable rule is marked as such", legacy["person_forms"], C.PERSON_FORMS_LEGACY)

    def stale(**changes):
        made = copy.deepcopy(checkpoint)
        made["state"]["markers"] = [["2026-10-01T10:41:00+00:00", "onboarding"]]
        made["state"]["events"].append(["2026-10-01T10:41:30+00:00", "human"])
        made.update(changes)
        return made
    # the cost file's requests[] for the stream first read (the H1 guard re-reads a checkpoint that read usage but has no rows)
    rows = [{"request_id": rid, "model_id": model, "timestamp": ts.isoformat() if ts else None,
             "usage": {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                       "cache_read": u.get("cache_read_input_tokens", 0),
                       "cache_write_5m": (u.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0),
                       "cache_write_1h": (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0)}}
            for rid, (model, u, ts) in first[0].items()]
    steady = C.scan_file_incremental(path, stale(), rows, person_rule=rule)
    check_eq("K6 control: a checkpoint of THIS reader and rule is continued (the planted marker and event stay)",
             (len(steady[2]), len(steady[5]) - len(first[5])), (1, 1))
    old_reader = C.scan_file_incremental(path, stale(reader="sentinel-old"), [], person_rule=rule)
    check_eq("K6: a checkpoint of another reader is rebuilt: the old 'onboarding' tag is gone", old_reader[2], [])
    other_rule = C.scan_file_incremental(path, stale(person_forms="another-rule"), [], person_rule=rule)
    check_eq("K6: a checkpoint made with another rule is rebuilt: the planted event is gone",
             len(other_rule[5]), len(first[5]))
    no_field = stale()
    no_field.pop("person_forms")
    check_eq("K6: a checkpoint from before the field is rebuilt once", len(C.scan_file_incremental(path, no_field, [], person_rule=rule)[5]),
             len(first[5]))
    check_eq("K6: a checkpoint made under the old predicate is rebuilt when the rule is readable again",
             len(C.scan_file_incremental(path, stale(person_forms=C.PERSON_FORMS_LEGACY), [], person_rule=rule)[5]), len(first[5]))
    check_eq("K6: and the other way round (readable then unreadable)",
             len(C.scan_file_incremental(path, stale(), [], person_rule=False)[5]), len(first[5]))


def k8_forms_row_and_unreadable_forms(root):
    forms, why = HA.report_forms(host="claude")
    check("K8: the shipped file gives the claude set, row included", forms is not None and why == "")
    shipped = json.loads(HA.REPORT_FORMS_FILE.read_text(encoding="utf-8"))
    row = shipped["claude"]["not_a_person_turn"]
    check_eq("K8: the shipped row", row, {"flags": ["isMeta", "isCompactSummary"], "notification_prefixes": ["<task-notification>"]})
    work = Path(tempfile.mkdtemp(prefix="qa-start-turn-forms-"))
    try:
        def variant(name, value):
            data = copy.deepcopy(shipped)
            if value is KeyError:
                data["claude"].pop("not_a_person_turn", None)
            else:
                data["claude"]["not_a_person_turn"] = value
            path = work / f"{name}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return path
        bad = {"missing": KeyError, "a list": ["isMeta"], "a string": "isMeta", "no flags": {"notification_prefixes": ["<x>"]},
               "no prefixes": {"flags": ["isMeta"]}, "flags empty": {"flags": [], "notification_prefixes": ["<x>"]},
               "prefixes empty": {"flags": ["isMeta"], "notification_prefixes": []},
               "flags a string": {"flags": "isMeta", "notification_prefixes": ["<x>"]},
               "a blank flag": {"flags": ["  "], "notification_prefixes": ["<x>"]},
               "a number in prefixes": {"flags": ["isMeta"], "notification_prefixes": [7]}}
        for label, value in bad.items():
            got, reason = HA.report_forms(variant(label.replace(" ", "-"), value), host="claude")
            check(f"K8: the row {label}: no claude forms, the reason names it", got is None and "claude.not_a_person_turn" in reason, reason)
            still, _ = HA.report_forms(variant("c-" + label.replace(" ", "-"), value), host="codex")
            check(f"K8: the row {label}: the codex rows still read", still is not None)
        good, _ = HA.report_forms(variant("two", {"flags": ["isMeta"], "notification_prefixes": ["<a>", "<b>"]}), host="claude")
        check("K8: a row with several prefixes is accepted", good is not None)
        # unreadable forms: the one reader says no, the capture takes the old predicate, no transfer, ONE line on stderr
        saved = HA.REPORT_FORMS_FILE
        HA.REPORT_FORMS_FILE = variant("unreadable", ["isMeta"])
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rule = C._person_rule()
            lines = [x for x in err.getvalue().splitlines() if x.strip()]
            check_eq("K8: unreadable forms: the rule is False", rule, False)
            check("K8: and ONE stderr line names the row", len(lines) == 1 and "claude.not_a_person_turn" in lines[0], err.getvalue())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                doc = run_in_project(root, CHAT + "-legacy", "chat-story")
            lines = [x for x in err.getvalue().splitlines() if x.strip() and "not_a_person_turn" in x]
            check_eq("K8: a whole capture with unreadable forms writes ONE such line (not one per file)", len(lines), 1)
            got = owners(doc)
            check_eq("K8: no turn is moved into the story (rA3 is before its start: Unclassified)", got["rA3"][0], "unclassified")
            # t-427 (canon part A, survivor 8): under the old predicate a tool result with a promptId (09:10:08) is an opener, so a
            # transfer with an unreadable rule would pull rA4 (09:10:10) and rA5 (09:10:25) into the story; rA3 (09:10:05) is
            # before that opener and could not tell the two apart
            check_eq("K8: rA4 and rA5 (after the old predicate's opener, before the story's start) are not moved either",
                     (got["rA4"][0], got["rA5"][0]), ("unclassified", "unclassified"))
            check_eq("K8: the story keeps what it had (rA6, rA7)", (got["rA6"][0], got["rA7"][0]), ("act-story", "act-story"))
            check("K8: the wait is the old predicate's: the tool results with a promptId are answers, so it is larger",
                  doc["human_wait_s"] > 60, str(doc["human_wait_s"]))
        finally:
            HA.REPORT_FORMS_FILE = saved
    finally:
        shutil.rmtree(work, ignore_errors=True)


def codex_rollout() -> str:
    """A synthetic Codex rollout: a user message at 09:10:00 (an opener, if anyone counted it) and two requests at 09:10:10 and
    09:10:20, both before the story starts at 09:10:30 (the activities file of `chat-story`)."""
    rows = [
        {"type": "session_meta", "timestamp": "2026-10-01T09:00:00Z", "payload": {"id": "cx-1", "cli_version": "synthetic"}},
        {"type": "turn_context", "timestamp": "2026-10-01T09:00:01Z", "payload": {"model": "synthetic-model", "turn_id": "t1"}},
        {"type": "response_item", "timestamp": "2026-10-01T09:10:00Z", "payload": {"type": "message", "role": "user"}},
    ]
    for n, ts in ((1, "09:10:10"), (2, "09:10:20")):
        rows.append({"type": "token_usage_record", "timestamp": f"2026-10-01T{ts}Z", "payload": {
            "thread_id": "cx-1", "response_id": f"cx-r{n}", "turn_id": "t1", "model": "synthetic-model",
            "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10, "reasoning_output_tokens": 0}}})
    return "".join(json.dumps(row) + "\n" for row in rows)


def k9_transfer_guards(root):
    """t-427 (canon part A, survivor 8): the two other guards of the call to `start_turn_activities` in `_capture`. Control first: the
    same chat transcript with no binding moves the turn (rA4 is the story's), so a no-transfer below is the guard's, not the fixture's."""
    control = owners(run_in_project(root, CHAT + "-k9-control", "chat-story"))
    check_eq("K9 control: with no binding the turn that started the story is the story's (rA3, rA4)",
             (control["rA3"][0], control["rA4"][0]), ("act-story", "act-story"))
    story = json.loads((FIXTURE / "chat-story.activities.json").read_text(encoding="utf-8"))["activities"][0]
    child = run_in_project(root, CHAT + "-k9-child", "chat-story", binding={"activity": story})
    got = owners(child)
    check_eq("K9: a child dispatch (its activity is inherited) is not moved back to the turn that started the parent's story",
             (got["rA3"][0], got["rA4"][0], got["rA5"][0]), ("unclassified", "unclassified", "unclassified"))
    check_eq("K9: ... and the inherited activity still owns what is inside its segment (rA6)", got["rA6"][0], "act-story")
    codex = run_in_project(root, "k9-codex", "chat-story", transcript_text=codex_rollout())
    rows = {r["request_id"]: r.get("activity_id") for r in codex["requests"]}
    check_eq("K9 control: the rollout was read (its 220 tokens are in the document, folded into a carry row when no activity owns them)",
             sum(v["tokens"] for v in codex["by_activity"].values()), 220)
    check_eq("K9: a Codex rollout's user message is not an opener: its requests stay Unclassified", sorted(set(rows.values())), ["unclassified"])


def main() -> None:
    fixture_clean()
    k1_state_is_not_a_task()
    k7_user_line_kinds()
    k4_edges()
    k6_checkpoints()
    # ONE project for every capture below: `hooklib.project_root` caches the first root it finds for the process
    root = temp_project()
    try:
        k2_k5_chat_turn_is_the_stories(root)
        k3_onboarding_turn_and_closure(root)
        k8_forms_row_and_unreadable_forms(root)
        k9_transfer_guards(root)
    finally:
        cleanup(root)
    finish("test_cost_capture_start_turn")


if __name__ == "__main__":
    main()
