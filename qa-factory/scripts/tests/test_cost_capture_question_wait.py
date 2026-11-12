#!/usr/bin/env python3
"""RN1-25 item 1 (t-1698 D2-C, K-C1..K-C1d): the time a question stood open to the person is a wait.

A question the host puts to the person is answered by a `tool_result` row, which `user_line_kind` calls "other",
so a 3 h 49 min question counted for nothing. `scan_file` now pairs the call (a tool named in the data row
`claude.person_question_tools`) with its result by the call's id; `human_wait` sums the spans UNCAPPED and does not
count the part of a turn gap that lies inside a span twice. The rows are SYNTHETIC and carry no text.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, run_capture, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as C  # noqa: E402
import host_adapter as HA  # noqa: E402

TOOL = "ToolAsk"          # a name the fixture's own rule uses; the shipped row is checked below, not spelled in code
ASKED, ANSWERED = "2026-10-24T05:20:48Z", "2026-10-24T09:10:04Z"
SPAN = 13756              # 09:10:04 - 05:20:48
RULE = {"flags": ["isMeta", "isCompactSummary"], "notification_prefixes": ["<task-notification>"], "question_tools": [TOOL]}
NO_TOOL_RULE = dict(RULE, question_tools=[])
USAGE = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}


def line(**kw):
    return json.dumps(kw)


def assistant(ts, call_id=None, name=TOOL, side=False, rid="r1"):
    blocks = [{"type": "tool_use", "id": call_id, "name": name, "input": {}}] if call_id else []
    return line(type="assistant", isSidechain=side, requestId=rid, uuid="a-" + ts, timestamp=ts,
                message={"model": "claude-sonnet-5", "usage": USAGE, "content": blocks})


def result(ts, call_id, side=False):
    return line(type="user", isSidechain=side, uuid="u-" + ts, timestamp=ts,
                message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": call_id, "content": ""}]})


def person(ts):
    return line(type="user", isSidechain=False, promptId="p", uuid="p-" + ts, timestamp=ts,
                message={"role": "user", "content": "x"})


WORK = temp_dir("question-wait-")


def write(name, rows):
    path = WORK / name
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def seconds(spans):
    return [round((b - a).total_seconds()) for a, b in spans]


def spans_of(path, rule):
    questions = {}
    C.scan_file(path, own_chain=False, person_rule=rule, questions=questions)
    return questions.get("spans", []), questions.get("open", {})


# --- K-C1: one question, one span of 13756 s, in the wait total, uncapped
whole = write("k1.jsonl", [person("2026-10-24T05:00:00Z"), assistant(ASKED, "q1", rid="r1"),
                           result(ANSWERED, "q1"), assistant("2026-10-24T09:10:10Z", rid="r2")])
spans, still_open = spans_of(whole, RULE)
check_eq("K-C1 one span of 13756 s", seconds(spans), [SPAN])
check_eq("K-C1 nothing left open", still_open, {})
events = C.scan_file(whole, own_chain=False, person_rule=RULE)[5]
waits: list = []
total, interactions = C.human_wait(events, [], 1800, spans, waits)
check("K-C1 human_wait_s holds the whole question (not capped at 1800)", total >= SPAN, str(total))
check_eq("K-C1 the span is listed once, as a question", [(w["kind"], w["seconds"]) for w in waits if w["kind"] == "question"], [("question", SPAN)])
check_eq("K-C1 the same events without the span count nothing for the question",
         C.human_wait(events, [], 1800), (0.0, 0))
capped = C.human_wait([], [], 1800, spans)
check_eq("K-C1 (mutant: the cap on spans) the span alone is 13756, never 1800", capped[0], float(SPAN))

# --- E-C4: a turn gap that overlaps the question is not counted twice. The person speaks 10 s after the answer; the
# gap from the last assistant row before the question to that turn is 13766 s, 13756 of them inside the span.
events2 = [(C.parse_ts("2026-10-24T05:20:40Z"), "assistant"), (C.parse_ts("2026-10-24T09:10:14Z"), "human")]
total2, _ = C.human_wait(events2, [], 1800, spans)
check_eq("E-C4 span + the 18 s of the gap outside it (8 before the call, 10 after the answer), once",
         total2, float(SPAN + 18))
total3, _ = C.human_wait(events2, [], 1800, spans + [(C.parse_ts("2026-10-24T05:25:00Z"), C.parse_ts("2026-10-24T05:30:00Z"))])
check_eq("E-C4 a second span inside the first adds nothing", total3, float(SPAN + 18))

# --- K-C1b: no tool in the rule (the row absent or unreadable) -> nothing measured
spans_b, open_b = spans_of(whole, NO_TOOL_RULE)
check_eq("K-C1b no tool named: no span", (spans_b, open_b), ([], {}))
spans_legacy, _ = spans_of(whole, False)
check_eq("K-C1b a rule that could not be read (False): no span", spans_legacy, [])
real_forms = HA.report_forms
try:
    forms, why = real_forms(host="claude")
    shipped = dict(forms)
    shipped["claude"] = {k: v for k, v in forms["claude"].items() if k != "person_question_tools"}
    HA.report_forms = lambda path=None, host=None: (shipped, "")
    check_eq("K-C1b the data row absent: the rule names no question tool", C._person_rule()["question_tools"], [])
    HA.report_forms = lambda path=None, host=None: (None, "unreadable")
    saved_err = sys.stderr
    sys.stderr = open(WORK / "stderr.txt", "w", encoding="utf-8")
    try:
        check_eq("K-C1b forms unreadable: the rule is False", C._person_rule(), False)
    finally:
        sys.stderr.close()
        sys.stderr = saved_err
finally:
    HA.report_forms = real_forms
shipped_rule = C._person_rule()
check("K-C1b the SHIPPED row names a question tool (the data row exists)", bool(shipped_rule and shipped_rule["question_tools"]), str(shipped_rule))

# --- K-C1c: a sidechain call is not a span, nor is its result
side = write("k1c.jsonl", [assistant("2026-10-24T05:20:40Z", "q1", side=True), result(ANSWERED, "q1", side=True)])
check_eq("K-C1c a tool_use in a sidechain row: no span, nothing open", spans_of(side, RULE), ([], {}))
mixed = write("k1c2.jsonl", [assistant("2026-10-24T05:20:40Z", "q1", side=True), result(ANSWERED, "q1")])
check_eq("K-C1c a main-chain result for a sidechain call: no span", spans_of(mixed, RULE), ([], {}))
other_tool = write("k1c3.jsonl", [assistant("2026-10-24T05:20:40Z", "q1", name="Read"), result(ANSWERED, "q1")])
check_eq("K-C1c a tool the row does not name: no span", spans_of(other_tool, RULE), ([], {}))

# --- E-C3: a repeated tool_result closes the question once
twice = write("ec3.jsonl", [assistant("2026-10-24T05:20:40Z", "q1"), result(ANSWERED, "q1"), result("2026-10-24T09:20:00Z", "q1")])
check_eq("E-C3 a repeated result: one span, the first one", seconds(spans_of(twice, RULE)[0]), [SPAN + 8])

# --- K-C1d: no result yet -> open; the answer in a later chunk -> exactly one span
rows = [{"request_id": "r1", "model_id": "claude-sonnet-5", "timestamp": ASKED,
         "usage": {"input": 10, "output": 5, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}}]
live = WORK / "k1d.jsonl"
live.write_text(assistant(ASKED, "q1") + "\n", encoding="utf-8")
first = C.scan_file_incremental(live, None, [], own_chain=False, person_rule=RULE)
state1 = first[-1]["state"]
check_eq("K-C1d no result yet: no span", state1["question_spans"], [])
check_eq("K-C1d the question stays open", list(state1["question_open"]), ["q1"])
with live.open("a", encoding="utf-8") as stream:
    stream.write(result(ANSWERED, "q1") + "\n")
second = C.scan_file_incremental(live, first[-1], rows, own_chain=False, person_rule=RULE)
state2 = second[-1]["state"]
check_eq("K-C1d the answer arrives in a later chunk: exactly one span", len(state2["question_spans"]), 1)
check_eq("K-C1d the span is 13756 s", seconds([(C.parse_ts(a), C.parse_ts(b)) for a, b in state2["question_spans"]]), [SPAN])
check_eq("K-C1d nothing left open", state2["question_open"], {})
third = C.scan_file_incremental(live, second[-1], rows, own_chain=False, person_rule=RULE)
check_eq("K-C1d a steady scan adds no second span", len(third[-1]["state"]["question_spans"]), 1)
# a checkpoint made under the OLD rule (no question tool) is rebuilt once: its spans are read from the start
old_rule = dict(RULE)
old_rule.pop("question_tools")
before = C.scan_file_incremental(live, None, rows, own_chain=False, person_rule=old_rule)
after = C.scan_file_incremental(live, before[-1], rows, own_chain=False, person_rule=RULE)
check_eq("E-D1 a checkpoint of the old rule is rebuilt and reads the spans", len(after[-1]["state"]["question_spans"]), 1)

# --- the whole capture: the document says what was measured
root = temp_project()
try:
    sid = "question-capture-session"
    transcript = root / "transcripts" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("\n".join([
        person("2026-10-24T05:00:00Z"),
        line(type="assistant", isSidechain=False, requestId="r1", uuid="a1", timestamp=ASKED,
             message={"model": "claude-sonnet-5", "usage": USAGE, "content": [
                 {"type": "tool_use", "id": "q1", "name": json.loads((SCRIPTS.parent / "references" / "host-report-forms.json")
                                                                      .read_text(encoding="utf-8"))["claude"]["person_question_tools"][0], "input": {}}]}),
        result(ANSWERED, "q1"),
        assistant("2026-10-24T09:10:10Z", rid="r2"),
        line(type="assistant", isSidechain=False, requestId="r3", uuid="a3", timestamp="2026-10-24T09:11:00Z",
             message={"model": "claude-sonnet-5", "usage": USAGE, "content": [
                 {"type": "tool_use", "id": "q2", "name": json.loads((SCRIPTS.parent / "references" / "host-report-forms.json")
                                                                      .read_text(encoding="utf-8"))["claude"]["person_question_tools"][0], "input": {}}]}),
    ]) + "\n", encoding="utf-8")
    done = run_capture(root, sid, transcript)
    check_eq("capture ran", done.returncode, 0)
    document = json.loads((root / "qa-factory" / "state" / "cost" / f"{sid}.json").read_text(encoding="utf-8"))
    check_eq("document: question_waits measured", document.get("question_waits"), "measured")
    check("document: human_wait_s holds the question", document.get("human_wait_s", 0) >= SPAN, str(document.get("human_wait_s")))
    check_eq("document: the question is listed in human_waits[]",
             [w["seconds"] for w in document.get("human_waits", []) if w["kind"] == "question"], [SPAN])
    check_eq("document: the unanswered question is counted open, not as a wait", document.get("open_questions"), 1)
finally:
    cleanup(root)

cleanup(WORK)
finish("test_cost_capture_question_wait")
