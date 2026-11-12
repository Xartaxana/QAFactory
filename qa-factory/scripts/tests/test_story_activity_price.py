"""N-1 (TP1-14857): the story price after a story stop nested over a doctor activity.

A story pushed over a doctor and popped at the host Stop used to leave the doctor a NEW open segment
that swallowed every later turn of the story. Keys K-1..K-9 of the spec t-1366: the capture removes such
windows (`cost_capture.attribution_activities`), the gap between two story entries of one task is the
task's (`sticky_activity_binding`), and `task_price` names money that may still be the story's but is
bound to another activity (`_open_parent_rows`, status incomplete, never added to the price).
Every capture scenario writes the activity file with the REAL writer (`activity_capture.update`) and
runs `cost_capture.py` as the Stop hook does."""
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity_capture as AC
import cost_capture as CC
import task_price as TP
from harness import temp_project, cleanup, check, check_eq, check_in, check_not_in, finish, run_capture

S, T = "n1-session-aaaa-bbbb", "TP1-14857"
DAY = "2026-10-26T"
USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
NL = chr(10)
A_EVENTS = [("start", "doctor", "", "e-d", "15:43:19"), ("start", "story", T, "e-s1", "15:56:29"),
            ("end", "story", T, "stop:turn-1", "16:31:40"), ("start", "story", T, "e-s2", "18:57:40"),
            ("end", "story", T, "stop:turn-2", "21:40:57")]
A_MAIN = ["15:50:00", "16:00:00", "17:00:00", "19:00:00", "22:00:00", "23:30:00"]


def build(root, events, main_times, sub_first=None):
    act_dir = root / "qa-factory" / "state" / "activities"
    act_dir.mkdir(parents=True, exist_ok=True)
    path = act_dir / (S + ".json")
    for action, typ, task, eid, hhmm in events:
        if action == "start-noop":   # `main` treats a start of the type/task already on top as a continuation: no write
            continue
        AC.update(path, S, action, typ, task, eid, DAY + hhmm + "Z",
                  "host Stop after final response" if eid.startswith("stop:") else "explicit")
    tr = root / "transcripts"
    tr.mkdir(exist_ok=True)
    main_path = tr / (S + ".jsonl")
    main_path.write_text(NL.join(json.dumps(dict(
        type="assistant", isSidechain=False, requestId="req-" + t, uuid="u-" + t, timestamp=DAY + t + "Z",
        message={"model": "claude-sonnet-5", "usage": USAGE, "content": []})) for t in main_times) + NL,
        encoding="utf-8")
    if sub_first:
        sd = tr / S / "subagents"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "agent-sub1.jsonl").write_text(NL.join([
            json.dumps(dict(type="user", isSidechain=True, uuid="s0", timestamp=DAY + sub_first + "Z",
                            message={"role": "user", "content": "role prompt, no ticket line"})),
            json.dumps(dict(type="assistant", isSidechain=True, requestId="req-sub", uuid="s1",
                            timestamp=DAY + sub_first + "Z",
                            message={"model": "claude-sonnet-5", "usage": USAGE, "content": []}))]) + NL,
            encoding="utf-8")
        (sd / "agent-sub1.meta.json").write_text(json.dumps({"agentType": "qa-factory:qa-runner"}), encoding="utf-8")
    old = time.time() - CC.RECAPTURE_LIVE_WINDOW_S - 3600
    for p in tr.rglob("*.jsonl"):
        os.utime(p, (old, old))
    return main_path


def capture(root, main_path):
    r = run_capture(root, S, main_path)
    check("cost_capture.py exits 0", r.returncode == 0, r.stderr[-400:])
    return json.loads((root / "qa-factory" / "state" / "cost" / (S + ".json")).read_text(encoding="utf-8"))


def scenario(events, main_times, sub_first=None):
    root = temp_project()
    try:
        return capture(root, build(root, events, main_times, sub_first))
    finally:
        cleanup(root)


def hhmm(row):
    return (row["timestamp"] or "")[11:19]


def kind_of(doc, row):
    a = doc["by_activity"].get(row["activity_id"], {})
    return a.get("type"), a.get("task")


def priced(doc):
    """request rows at the catalogue's list rates, with their exact subtotal."""
    rows = CC.revalue_document(doc, {}, CC.load_catalogue())["requests"]
    return [(r, Decimal(str(r["valuation"]["subtotal_usd"]))) for r in rows]


def price(doc, cfg=None, task=T):
    return TP.task_price(None, task, sessions={S: doc}, driver=({}, {}), cfg=cfg or {})


def story_sum(doc, pick=None):
    pick = pick or (lambda r: kind_of(doc, r) == ("story", T))
    return sum((m for r, m in priced(doc) if pick(r)), Decimal(0))


def k1():
    doc = scenario(A_EVENTS, A_MAIN, "22:30:00")
    rows = doc["requests"]
    late = [r for r in rows if hhmm(r) >= "16:00:00"]
    check_eq("K-1 six story rows from 16:00 (5 orchestrator + 1 subagent)", len(late), 6)
    check("K-1 every row from 16:00 on, the subagent's included, is bound to a story activity of the task",
          all(kind_of(doc, r) == ("story", T) for r in late), str([(hhmm(r), kind_of(doc, r)) for r in late]))
    check("K-1 the 15:50 row is the doctor's", [kind_of(doc, r)[0] for r in rows if hhmm(r) == "15:50:00"] == ["doctor"])
    ans = price(doc)
    want = story_sum(doc)
    check_eq("K-1 low == high == the exact list-price sum of the story rows",
             (Decimal(str(ans["price_low_usd"])), Decimal(str(ans["price_high_usd"]))), (want, want))
    check("K-1 the status is not incomplete", ans["status"] != "incomplete", ans["status"])
    check("K-1 no activity carries stop_resumed_segments",
          not any("stop_resumed_segments" in a for a in doc["by_activity"].values()))
    check_eq("K-1 the marker is written", doc["attribution_provenance"].get("stop_resumed_parent"), "excluded")
    total = sum((m for _r, m in priced(doc)), Decimal(0))
    others = sum((m for r, m in priced(doc) if kind_of(doc, r) != ("story", T)), Decimal(0))
    check_eq("K-1 partition: story + other activities == the session total", want + others, total)
    return doc


def k2():
    ev = [e if e[3] != "stop:turn-1" else ("end", "story", T, "e-ret", "16:31:40") for e in A_EVENTS]
    doc = scenario(ev, A_MAIN, "22:30:00")
    mid = [r for r in doc["requests"] if hhmm(r) == "17:00:00"]
    check("K-2 a request between a nested return and the next start is the doctor's",
          [kind_of(doc, r)[0] for r in mid] == ["doctor"], str([kind_of(doc, r) for r in mid]))


def seg(sid, start_eid, end_eid, st="2026-10-26T10:00:00Z", en="2026-10-26T10:10:00Z"):
    return {"segment_id": sid, "start_event_id": start_eid, "start_time": st, "end_event_id": end_eid, "end_time": en}


def k3_k4_units():
    story = {"activity_id": "s1", "type": "story", "task": T, "end_event_id": "stop:t1", "segments": [
        seg("sg1", "e-s1", "stop:t1")]}
    doctor = {"activity_id": "d1", "type": "doctor", "task": None, "end_event_id": "stop:t2", "segments": [
        seg("dg1", "e-d", "e-s1"), seg("dg2", "stop:t1", "stop:t2")]}
    before = copy.deepcopy([story, doctor])
    out, kept = CC.attribution_activities([story, doctor])
    check_eq("K-3 a window closed by the parent's OWN end is kept", [s["segment_id"] for s in out[1]["segments"]], ["dg1", "dg2"])
    check_eq("K-3 and listed", kept, {"d1": ["dg2"]})
    check_eq("K-3 the input is not mutated", [story, doctor], before)
    doctor_open = dict(doctor, end_event_id=None, segments=[seg("dg1", "e-d", "e-s1"), seg("dg2", "stop:t1", None, en=None)])
    out, kept = CC.attribution_activities([story, doctor_open])
    check_eq("K-3 an open window is removed", [s["segment_id"] for s in out[1]["segments"]], ["dg1"])
    check_eq("K-3 and not listed", kept, {})
    other = dict(doctor, segments=[seg("dg1", "e-d", "e-s1"), seg("dg2", "stop:t1", "e-s2")])
    out, kept = CC.attribution_activities([story, other])
    check_eq("K-3 a window closed by another start is removed", [s["segment_id"] for s in out[1]["segments"]], ["dg1"])
    # K-4 (E4): a story parent is never cut
    parent_story = {"activity_id": "s0", "type": "story", "task": "OTHER", "end_event_id": None, "segments": [
        seg("pg1", "e-p", "e-s1"), seg("pg2", "stop:t1", None, en=None)]}
    out, kept = CC.attribution_activities([parent_story, story])
    check_eq("K-4 the parent story's resumed segment is kept, not listed",
             ([s["segment_id"] for s in out[0]["segments"]], kept), (["pg1", "pg2"], {}))
    # K-4 (E6): a gap between two different tasks is nobody's; a gap between two entries of one task is the task's
    a = {"activity_id": "a", "type": "story", "task": "A", "segments": [seg("a1", "x", "y", en="2026-10-26T10:10:00Z")]}
    b = {"activity_id": "b", "type": "story", "task": "B", "segments": [seg("b1", "x", "y", st="2026-10-26T10:30:00Z", en="2026-10-26T10:40:00Z")]}
    gap = datetime(2026, 10, 26, 10, 20, tzinfo=timezone.utc)
    check_eq("K-4 a gap between two DIFFERENT tasks is nobody's", CC.sticky_activity_binding([a, b], gap),
             ("unclassified", "unclassified"))
    b_same = dict(b, task="A")
    check_eq("K-4 a gap between two entries of the SAME task is the task's", CC.sticky_activity_binding([a, b_same], gap), ("a", "a1"))
    d = {"activity_id": "d", "type": "doctor", "task": "A", "segments": [seg("d1", "x", "y", en="2026-10-26T10:10:00Z")]}
    check_eq("K-4 a gap after a doctor segment stays nobody's", CC.sticky_activity_binding([d, b_same], gap),
             ("unclassified", "unclassified"))
    for task in (None, ""):
        an = dict(a, task=task)
        bn = dict(b, task=task)
        check_eq(f"K-4 an anonymous story (task {task!r}) never claims a gap", CC.sticky_activity_binding([an, bn], gap),
                 ("unclassified", "unclassified"))
    check_eq("K-4 a story with a task and a next story with no task: not merged",
             CC.sticky_activity_binding([a, dict(b, task=None)], gap), ("unclassified", "unclassified"))


def k3b():
    ev = A_EVENTS + [("start-noop", "doctor", "", "e-d2", "23:40:00"), ("end", "doctor", "", "stop:turn-3", "23:50:00")]
    doc = scenario(ev, A_MAIN + ["23:45:00"], "22:30:00")
    rows = {hhmm(r): kind_of(doc, r) for r in doc["requests"]}
    check("K-3b rows 16:00-19:00 are the story's", all(rows[t] == ("story", T) for t in ("16:00:00", "17:00:00", "19:00:00")), str(rows))
    check("K-3b rows 22:00, 22:30 (subagent), 23:30, 23:45 are the doctor's",
          all(rows[t][0] == "doctor" for t in ("22:00:00", "22:30:00", "23:30:00", "23:45:00")), str(rows))
    doctor = next(a for a in doc["by_activity"].values() if a["type"] == "doctor")
    seg_ids = {r["activity_segment_id"] for r in doc["requests"] if hhmm(r) in ("22:00:00", "22:30:00", "23:30:00", "23:45:00")}
    check_eq("K-3b by_activity[doctor].stop_resumed_segments holds the window's segment", set(doctor.get("stop_resumed_segments") or []), seg_ids)
    ans = price(doc)
    check_eq("K-3b status incomplete", ans["status"], "incomplete")
    check_in("K-3b the finding names the window, without claiming who opened it", "window opened while this story ran", ans["finding"])
    check_in("K-3b grammar: n requests ... are bound", "requests of session", ans["finding"])
    check_in("K-3b grammar: plural verb", ", are bound to a doctor window", ans["finding"])
    check_not_in("K-3b no recapture door", "--recapture", ans["finding"])
    want = story_sum(doc)
    check_eq("K-3b the price is the story rows only", Decimal(str(ans["price_low_usd"])), want)
    check_eq("K-3b the price is a point", ans["price_low_usd"], ans["price_high_usd"])


def k9_doc():
    ev = [("start", "doctor", "", "e-d", "15:43:19"), ("start", "story", T, "e-s1", "15:56:29"),
          ("end", "story", T, "e-ret", "16:31:40")]
    return scenario(ev, ["15:50:00", "16:00:00", "17:00:00", "19:00:00"])


def k9_k5_k6(doc_a):
    doc = k9_doc()
    rows = {hhmm(r): kind_of(doc, r) for r in doc["requests"]}
    check("K-9 rows 17:00 and 19:00 are the doctor's (nothing removed)", rows["17:00:00"][0] == rows["19:00:00"][0] == "doctor", str(rows))
    ans = price(doc)
    check_eq("K-9 status incomplete", ans["status"], "incomplete")
    check_in("K-9 never closed", "never closed", ans["finding"])
    check_in("K-9 ended without stopping (conditional)", "Either this story ended without stopping", ans["finding"])
    check_in("K-9 grammar: plural verb", ", are bound to a doctor activity that was never closed and are not in this price", ans["finding"])
    check_not_in("K-9 no recapture door where it opens nothing", "--recapture", ans["finding"])
    check_not_in("K-9 no kept-window wording", "window opened while this story ran", ans["finding"])
    # K-5: the same file as a 0.10.2 capture (no marker)
    old = copy.deepcopy(doc)
    del old["attribution_provenance"]["stop_resumed_parent"]
    a5 = price(old)
    check_eq("K-5 status incomplete", a5["status"], "incomplete")
    for needle in ("never closed", S[:8], "captured before 0.10.3", f"--recapture --session {S}"):
        check_in(f"K-5 the finding holds {needle!r}", needle, a5["finding"])
    check_eq("K-5 the price is the story rows only", Decimal(str(a5["price_low_usd"])), story_sum(old))
    check("K-5 the money is not added: the price is below the whole session's",
          Decimal(str(a5["price_low_usd"])) < story_sum(old, lambda r: True))
    over = {"rate_overrides": [{"model_id": "claude-sonnet-5", "aliases": [], "rates": {
        "input": 40, "output": 200, "cache_read": 4, "cache_write_5m": 50, "cache_write_1h": 80}}]}
    check_in("K-5 with project rates the sentence says so (_money_words)", "at the project's own rates",
             price(old, over)["finding"])
    # K-6: the doctor's rows only before the story's first row
    a6 = price(doc_a)
    check_not_in("K-6 a doctor before the story is not named (never closed)", "never closed", a6["finding"])
    check_not_in("K-6 a doctor before the story is not named (window)", "window opened while this story ran", a6["finding"])


def x1_x2():
    """The critic's two scenarios (t-1377): another task's story must not be told a cause that is not its own."""
    other = "TP1-OTHER"
    x1 = scenario([("start", "story", other, "e-b", "14:00:00"), ("end", "story", other, "stop:t0", "14:30:00"),
                   ("start", "doctor", "", "e-d", "15:00:00"), ("start", "story", T, "e-a", "15:10:00"),
                   ("end", "story", T, "stop:t1", "15:30:00"), ("end", "doctor", "", "stop:t2", "16:00:00")],
                  ["14:10:00", "14:45:00", "15:05:00", "15:20:00", "15:45:00", "16:30:00"])
    f1 = price(x1, task=other)["finding"]
    check_not_in("X1 task B (stopped before the doctor) is not told the story stopped at the window's start",
                 "began when the story stopped", f1)
    x2 = scenario([("start", "story", other, "e-b", "14:00:00"), ("end", "story", other, "stop:t0", "14:30:00"),
                   ("start", "doctor", "", "e-d", "15:00:00")], ["14:10:00", "15:05:00", "15:20:00"])
    a2 = price(x2, task=other)
    check_eq("X2 task B: the price is incomplete", a2["status"], "incomplete")
    check_not_in("X2 task B, which did stop, is never told it ended without stopping",
                 "The story ended without stopping", a2["finding"])
    check_in("X2 the cause is conditional", "Either this story ended without stopping", a2["finding"])


def k7_k8():
    t0 = "2026-10-26T12:00:00+00:00"

    def doc_of(extra):
        rows = [{"activity_id": "st", "timestamp": t0}] + [dict({"activity_id": "dr"}, **e) for e in extra]
        return {"requests": rows, "by_activity": {"st": {"type": "story", "task": T, "status": "closed"},
                                                    "dr": {"type": "doctor", "status": "open"}}}
    got = lambda e: TP._open_parent_rows(doc_of([e]), {0})[0]   # noqa: E731
    check_eq("K-7 a row AT the first story row's time is not counted", got({"timestamp": t0}), [])
    check_eq("K-7 a row 1 s after is counted", got({"timestamp": "2026-10-26T12:00:01+00:00"}), [1])
    check_eq("K-7 a row with no timestamp is counted", got({"timestamp": None}), [1])
    check_eq("K-7 a naive time equal to the story's (read as UTC) is not counted", got({"timestamp": "2026-10-26T12:00:00"}), [])
    check_eq("K-7 a row BEFORE is not counted", got({"timestamp": "2026-10-26T11:59:59+00:00"}), [])
    check_eq("K-7 no story rows -> nothing", TP._open_parent_rows(doc_of([{"timestamp": None}]), set()), ([], []))
    # K-8 crooked inputs
    for bad in (None, "x", 5):
        check_eq(f"K-8 attribution_activities({bad!r})", CC.attribution_activities(bad), ([], {}))
    check_eq("K-8 a tuple is not a list", CC.attribution_activities(("x",)), ([], {}))
    weird = ["x", {"type": "doctor"}, {"type": "doctor", "segments": "no"}]
    story = {"activity_id": "s", "type": "story", "task": T, "end_event_id": "stop:1", "segments": []}
    before = copy.deepcopy(weird + [story])
    out, kept = CC.attribution_activities(weird + [story])
    check_eq("K-8 non-dict / no segments list pass through unchanged", out[:3], before[:3])
    check_eq("K-8 the input is unchanged", weird + [story], before)
    p = {"activity_id": "p", "type": "doctor", "end_event_id": None, "segments": [
        {"segment_id": "n1", "start_event_id": None}, {"segment_id": "n2", "start_event_id": "stop:1", "end_event_id": None},
        {"segment_id": "n3", "start_event_id": "stop:1", "end_event_id": "e-x"}, "junk"]}
    story5 = dict(story, end_event_id=5)
    out, kept = CC.attribution_activities([p, story5])
    check_eq("K-8 a story with a non-string end marks nothing", [s if isinstance(s, str) else s["segment_id"] for s in out[0]["segments"]],
             ["n1", "n2", "n3", "junk"])
    out, kept = CC.attribution_activities([p, story])
    check_eq("K-8 None/None segment is removed (open), a start None is kept, nothing listed",
             ([s if isinstance(s, str) else s["segment_id"] for s in out[0]["segments"]], kept), (["n1", "junk"], {}))
    bad_doc = doc_of([{"timestamp": "2026-10-26T13:00:00+00:00"}])
    bad_doc["by_activity"]["dr"] = {"type": "doctor", "status": "closed", "stop_resumed_segments": "x"}
    bad_doc["requests"][1]["activity_segment_id"] = "x"
    check_eq("K-8 stop_resumed_segments that is not a list reads as absent", TP._open_parent_rows(bad_doc, {0}), ([], []))


def main():
    doc_a = k1()
    k2()
    k3_k4_units()
    k3b()
    k9_k5_k6(doc_a)
    x1_x2()
    k7_k8()
    finish("test_story_activity_price")


if __name__ == "__main__":
    main()
