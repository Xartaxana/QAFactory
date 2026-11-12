"""The missed tail of a session (B-228, piece Q2 of the true-price spec) and the recapture rules.

Root cause this guards: on the cmp1 run the Stop capture of 16 of 35 sessions landed BEFORE the
session's last requests were written, and nothing ever flagged such a file: `_stale_reason` knew
only an old format and a late activity backfill. Those 16 cost files read $0.775 below the CLI's
own charge. The tail rule: a file is stale when, past the byte offset its checkpoint recorded, the
main transcript or a subagent file holds an `assistant` record that carries usage. "Size exceeds
the offset" is NOT the rule: Claude Code appends `stop_hook_summary`, `last-prompt`, `cost-state`
and `attachment` lines after every Stop capture, which would flag all 35 sessions.

Also pinned here: a recapture is a NEW capture (every request valued afresh, pins replaced), a
recapture prints nothing but its JSON (the metric-signals notice honours the skip flag), a live
transcript is skipped with its reason, and a session whose transcript is gone is `not_recomputed`
with its file kept.

t-165 attempt 2 (the critic's verdict on the first): (B1) no recapture ever lowers the usage or the
money a file records - a stream whose file is gone or shorter than its checkpoint keeps its rows,
and the unattended pass leaves such a file untouched and says so; (F2) a checkpoint with no integer
offset falls back to file time against `generated`, an unknown `generated` reads as behind; (F3) an
unreadable cost file is reported, not dropped; (F4) a recapture that wrote nothing is not
"recomputed"; (F5, the root cause of B-228) the Stop capture waits LOCK_WAIT_S for the session lock,
breaks a lock its owner record shows dead or hung, and otherwise leaves a `<session>.pending` marker
that `recapture_stale` answers - it never gives up silently. Every recapture call below goes through
`recap` / `stale_pass`, which assert that no session's recorded usage or money fell.

Run: python -B ai-packages/qa-factory/scripts/tests/test_cost_capture_tail.py
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import temp_project, temp_dir, cleanup, use_project, check, check_eq, check_in, finish, SCRIPTS

HOUR_AGO = time.time() - 3600
TASK = "TP1-TAIL"
PIN = {"subtotal_usd": "999", "pricing_coverage": "complete", "missing_rate_categories": [],
       "rate_provenance": {"kind": "legacy_project_override", "revision": "old"},
       "tariff_confirmation": "unconfirmed"}


def row(**kw):
    return json.dumps(kw, ensure_ascii=False)


def assistant(rid, ts="2026-09-20T19:00:00Z", usage=True, sidechain=False, model="claude-sonnet-5",
              tokens=1000, output=50):
    message = {"model": model, "content": []}
    if usage:
        message["usage"] = {"input_tokens": tokens, "output_tokens": output, "cache_read_input_tokens": 0,
                            "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                               "ephemeral_1h_input_tokens": 0}}
    return row(type="assistant", isSidechain=sidechain, requestId=rid, uuid="u-" + rid,
               timestamp=ts, message=message)


NOISE = [row(type="system", subtype="stop_hook_summary", timestamp="2026-09-20T19:00:01Z"),
         row(type="last-prompt", lastPrompt="x"),
         row(type="cost-state", costState={"usd": 1}),
         row(type="attachment", attachment={"type": "hook_success"})]


def append(path, *lines):
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def age(*paths, seconds=3600):
    stamp = time.time() - seconds
    for path in paths:
        os.utime(path, (stamp, stamp))


def cost_path(root, sid):
    return root / "qa-factory" / "state" / "cost" / f"{sid}.json"


def load(root, sid):
    return json.loads(cost_path(root, sid).read_text(encoding="utf-8"))


def seed_and_capture(root, transcript, sid):
    """A real capture of `transcript`: an old-format seed file, then `recapture_session` writes the
    file the way a Stop hook would. Returns the new document."""
    out = cost_path(root, sid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"session_id": sid, "transcript": str(transcript),
                               "generated": "2026-09-20T19:05:00+00:00", "total_cost_usd": None,
                               "by_task": {}, "requests": []}), encoding="utf-8")
    outcome = C.recapture_session(root, sid)
    check_eq(f"fixture {sid}: the seed capture is recomputed", outcome["status"], "recomputed")
    return load(root, sid)


def stale(root, sid, doc=None):
    doc = doc if doc is not None else load(root, sid)
    return C._stale_reason(doc, root / "qa-factory" / "state" / "activities" / f"{sid}.json")


def main_offset(doc):
    return next(iter(doc["scan_checkpoints"].values()))["offset"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def usage_tokens(doc):
    return C._rows_usage([r for r in doc.get("requests") or [] if isinstance(r, dict)])[0]


def total_at_read(doc):
    """What a reader sees: the stored usage re-priced by the current rule (pins do not count)."""
    return C.revalue_document(doc, {}, None)["total_cost_usd"] or 0.0


def snapshot(root):
    out = {}
    for path in sorted((root / "qa-factory" / "state" / "cost").glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(doc, dict):
            out[path.stem] = (usage_tokens(doc), total_at_read(doc))
    return out


def no_loss(label, before, after):
    """INVARIANT: no recapture ever lowers a session's recorded usage, and with it the money."""
    fell = {sid: (before[sid], after[sid]) for sid in before
            if sid in after and (after[sid][0] < before[sid][0] or after[sid][1] < before[sid][1] - 1e-9)}
    check(f"INVARIANT ({label}): total_after >= total_before, and the usage too, for every session",
          not fell, str(fell))


def stale_pass(root, label, explicit=False):
    before = snapshot(root)
    results = {r["session_id"]: r for r in C.recapture_stale(root, explicit=explicit)}
    no_loss(label, before, snapshot(root))
    return results


def recap(root, sid, label):
    before = snapshot(root)
    outcome = C.recapture_session(root, sid)
    no_loss(label, before, snapshot(root))
    return outcome


def python_run(script, *args, env=None):
    return subprocess.Popen([sys.executable, "-B", str(script), *[str(a) for a in args]],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", env=env)


def wait_for(path, seconds=60.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if Path(path).exists():
            return True
        time.sleep(0.05)
    return False


HOLDER = '''
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import cost_capture as C
lock_root, ready, hold, owner_pid, owner_age = Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4]), sys.argv[5], float(sys.argv[6])
with C._capture_lock(lock_root):
    owner = C._owner_path(lock_root)
    info = json.loads(owner.read_text(encoding="utf-8"))
    if owner_pid != "self":
        info["pid"] = int(owner_pid)
    info["at"] = time.time() - owner_age
    owner.write_text(json.dumps(info), encoding="utf-8")
    ready.write_text("ready", encoding="utf-8")
    time.sleep(hold)
'''

RACER = '''
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import cost_capture as C
lock_root, log, go, ready, wait_s, hold, tag, sid, transcript, cwd = sys.argv[2:12]
C.LOCK_WAIT_S = float(wait_s)
def fake_capture(event):
    with open(log, "a", encoding="utf-8") as stream:
        stream.write("start " + tag + "\\n")
    time.sleep(float(hold))
    with open(log, "a", encoding="utf-8") as stream:
        stream.write("end " + tag + "\\n")
    return "captured"
C._run_capture = fake_capture
Path(ready).write_text("ready", encoding="utf-8")
end = time.monotonic() + 60
while not Path(go).exists() and time.monotonic() < end:
    time.sleep(0.01)
print(C._capture_with_wait({"session_id": sid, "transcript_path": transcript, "cwd": cwd},
                           sid, Path(lock_root), False))
'''


def main() -> None:
    root = temp_project()
    use_project(root)
    work = temp_dir(prefix="qa-tail-")
    saved_flag = os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH")
    try:
        # ---------------------------------------------------------------- R3 / P1: the tail rule
        t1 = work / "s-main.jsonl"
        t1.write_text(assistant("r1") + "\n", encoding="utf-8")
        doc = seed_and_capture(root, t1, "s-main")
        check_eq("R3: a file captured from a complete transcript is current", stale(root, "s-main"), (False, ""))

        append(t1, *NOISE)
        check("P1 fixture: the transcript is now LARGER than the checkpoint offset (the noise is real)",
              t1.stat().st_size > main_offset(doc), f"size {t1.stat().st_size}, offset {main_offset(doc)}")
        check_eq("P1 (critic fixture): a tail of only stop_hook_summary / last-prompt / cost-state / "
                 "attachment lines is NOT stale, although size exceeds the offset",
                 stale(root, "s-main"), (False, ""))

        append(t1, assistant("r-err", usage=False, model="<synthetic>"))
        check_eq("edge: an assistant record WITHOUT usage (an error record) in the tail is not stale",
                 stale(root, "s-main"), (False, ""))
        append(t1, row(type="assistant", requestId="r-empty", message={"model": "m", "usage": {}, "content": []}))
        check_eq("edge: an assistant record with an EMPTY usage object is not stale either",
                 stale(root, "s-main"), (False, ""))
        append(t1, row(type="user", message={"role": "user", "content": "usage: {}"},
                       usage={"input_tokens": 5}))
        check_eq("edge: a non-assistant record that mentions usage is not stale",
                 stale(root, "s-main"), (False, ""))

        with t1.open("ab") as stream:
            stream.write(assistant("r-partial").encode("utf-8"))      # complete JSON, no newline yet
        check_eq("edge: a last line with no newline is an incomplete record and never counts "
                 "(the capture leaves it for the next scan)", stale(root, "s-main"), (False, ""))
        with t1.open("ab") as stream:
            stream.write(b"\n")

        is_stale, reason = stale(root, "s-main")
        check("R3: a tail with an assistant record that carries usage IS stale", is_stale, reason)
        check_in("R3: the reason is 'transcript grew after this capture'", "transcript grew after this capture", reason)

        # --------------------------------------- offset beyond the end, missing checkpoint file
        t2 = work / "s-trunc.jsonl"
        t2.write_text(assistant("r1") + "\n" + assistant("r2") + "\n", encoding="utf-8")
        doc2 = seed_and_capture(root, t2, "s-trunc")
        t2.write_text(assistant("r9") + "\n", encoding="utf-8")
        check("edge: the transcript is now shorter than the recorded offset",
              t2.stat().st_size < main_offset(doc2))
        try:
            is_stale, reason = stale(root, "s-trunc")
        except Exception as exc:
            is_stale, reason = None, repr(exc)
        check("edge: an offset beyond the file size is stale and never an exception", is_stale is True, reason)
        check_in("edge: and the reason says the checkpoint is past the end", "past the end", reason)

        t3 = work / "s-sub.jsonl"
        t3.write_text(assistant("m1") + "\n", encoding="utf-8")
        sub_dir = work / "s-sub" / "subagents"
        sub_dir.mkdir(parents=True)
        a1 = sub_dir / "agent-1.jsonl"
        a1.write_text(assistant("a1", sidechain=True) + "\n", encoding="utf-8")
        doc3 = seed_and_capture(root, t3, "s-sub")
        check_eq("R3 fixture: a session with a subagent file is captured current", stale(root, "s-sub"), (False, ""))
        check("R3 fixture: the subagent file has its own checkpoint",
              len(doc3["scan_checkpoints"]) == 2, list(doc3["scan_checkpoints"]))

        # ------------------------------------------------------------ subagent growth
        append(a1, *NOISE)
        check_eq("R3 subagent: noise lines in a subagent file are not stale", stale(root, "s-sub"), (False, ""))
        append(a1, assistant("a2", sidechain=True))
        is_stale, reason = stale(root, "s-sub")
        check("R3 subagent (mutation b): a usage record appended to a SUBAGENT file makes the file stale",
              is_stale, reason)
        check_in("R3 subagent: the reason names the subagent file", "agent-1.jsonl", reason)
        check_eq("R3 subagent control: the main transcript alone did not change",
                 (t3.stat().st_size == main_offset(doc3)), True)

        a2 = sub_dir / "agent-2.jsonl"
        doc3b = json.loads(json.dumps(doc3))
        a2.write_text(assistant("b1", sidechain=True) + "\n", encoding="utf-8")
        is_stale, reason = stale(root, "s-sub", doc3b)
        check("R3 subagent: a subagent file with NO checkpoint is stale", is_stale, reason)
        check_in("R3 subagent: the reason names the file with no checkpoint", "agent-2.jsonl has no checkpoint", reason)
        age(t3, a1, a2)

        # ------------------------------------------------------------ B1 (E9): a gone stream keeps its money
        big = 1_000_000                       # 1M input tokens of claude-sonnet-5 = $2, no output
        tg = work / "s-gone-sub.jsonl"
        tg.write_text(assistant("m1", tokens=big, output=0) + "\n", encoding="utf-8")
        gsub = work / "s-gone-sub" / "subagents"
        gsub.mkdir(parents=True)
        ga = gsub / "agent-1.jsonl"
        ga.write_text(assistant("a1", sidechain=True, tokens=big, output=0) + "\n", encoding="utf-8")
        seed_and_capture(root, tg, "s-gone-sub")
        check_eq("B1 fixture: $2 main + $2 subagent, recorded", total_at_read(load(root, "s-gone-sub")), 4.0)
        ga.unlink()
        age(tg)
        is_stale, reason = stale(root, "s-gone-sub")
        check("B1: a checkpoint naming a file that no longer exists is still FLAGGED stale", is_stale, reason)
        check_in("B1: the reason names the missing file", "agent-1.jsonl", reason)
        check_in("B1 (FR-1, FR-57): the reason names the door a person can use",
                 "--recapture --session s-gone-sub", reason)
        bytes_before = sha(cost_path(root, "s-gone-sub"))
        results = stale_pass(root, "B1 unattended pass")
        skipped = results.get("s-gone-sub", {})
        check_eq("B1 (mutation a): the unattended pass SKIPS a file whose only finding is a gone stream",
                 skipped.get("status"), "skipped")
        check_in("B1: the skip carries the reason", "no longer exists", skipped.get("reason", ""))
        check_eq("B1: a skipped file is left byte for byte as it was", sha(cost_path(root, "s-gone-sub")), bytes_before)
        check_eq("B1 (probe of the critic): $2 main + $2 subagent, subagent file deleted -> still 4.0, not 2.0",
                 total_at_read(load(root, "s-gone-sub")), 4.0)
        outcome = recap(root, "s-gone-sub", "B1 door (explicit recapture)")
        after = load(root, "s-gone-sub")
        check_eq("B1 door: `--recapture --session` recomputes it", outcome["status"], "recomputed")
        check_eq("B1 door: and the money of the gone stream is kept (4.0)", total_at_read(after), 4.0)
        check_eq("B1 door: the stored total field agrees", after["total_cost_usd"], 4.0)
        check("B1 door: the gone stream's request row is still in the file",
              any(r.get("stream") == "agent-1.jsonl" for r in after["requests"]),
              str([r.get("stream") for r in after["requests"]]))
        check("B1 door: its agents[] entry is still in the file",
              any(a.get("file") == "agent-1.jsonl" for a in after["agents"]), str(after["agents"]))
        check_in("B1 door: the file says what was kept and why", "agent-1.jsonl",
                 json.dumps(after.get("recapture_carried")))
        check("B1 door: the recaptured file no longer names the missing path",
              all(not k.endswith("agent-1.jsonl") for k in after["scan_checkpoints"]))
        check_eq("B1 door: nor is it stale any more", stale(root, "s-gone-sub"), (False, ""))
        check_eq("B1 door: the session figures add up (by_model = orchestrator + the kept agent)",
                 (after["by_model"]["claude-sonnet-5"]["input"], after["reconciliation"]["session_total"]),
                 (2 * big, 4.0))

        # edge: a subagent file gone AND the main transcript grown -> the tail IS recaptured, rows kept
        tm = work / "s-gone-grown.jsonl"
        tm.write_text(assistant("m1", tokens=big, output=0) + "\n", encoding="utf-8")
        msub = work / "s-gone-grown" / "subagents"
        msub.mkdir(parents=True)
        ma = msub / "agent-1.jsonl"
        ma.write_text(assistant("a1", sidechain=True, tokens=big, output=0) + "\n", encoding="utf-8")
        seed_and_capture(root, tm, "s-gone-grown")
        ma.unlink()
        append(tm, assistant("m2", tokens=big, output=0))
        age(tm)
        is_stale, reason = stale(root, "s-gone-grown")
        check_in("edge (gone + grown): the reason is the growth, not the gone file",
                 "transcript grew after this capture", reason)
        results = stale_pass(root, "edge gone + grown")
        check_eq("edge (gone + grown): the main tail IS recaptured", results.get("s-gone-grown", {}).get("status"),
                 "recomputed")
        grown = load(root, "s-gone-grown")
        check_eq("edge (gone + grown): the tail is in and the gone stream's rows are kept: total only grows",
                 total_at_read(grown), 6.0)
        check_eq("edge (gone + grown): a collapsed ledger - one carry row per stream: the main's (2 requests) "
                 "and the kept subagent's", sorted((r["stream"], r["usage"]["requests"]) for r in grown["requests"]),
                 [("agent-1.jsonl", 1), ("orchestrator", 2)])
        check_eq("edge (gone + grown): current afterwards", stale(root, "s-gone-grown"), (False, ""))

        # edge: the MAIN transcript shorter than its checkpoint (truncated) keeps its rows the same way
        tt = work / "s-trunc-money.jsonl"
        tt.write_text(assistant("r1", tokens=big, output=0) + "\n" + assistant("r2", tokens=big, output=0) + "\n",
                      encoding="utf-8")
        seed_and_capture(root, tt, "s-trunc-money")
        tt.write_text(assistant("r1", tokens=big, output=0) + "\n", encoding="utf-8")
        age(tt)
        bytes_before = sha(cost_path(root, "s-trunc-money"))
        results = stale_pass(root, "B1 truncated main, unattended")
        check_eq("B1 truncated main: the unattended pass skips it", results.get("s-trunc-money", {}).get("status"),
                 "skipped")
        check_in("B1 truncated main: the reason says the checkpoint is past the end", "past the end",
                 results.get("s-trunc-money", {}).get("reason", ""))
        check_eq("B1 truncated main: the file is left byte for byte as it was",
                 sha(cost_path(root, "s-trunc-money")), bytes_before)
        outcome = recap(root, "s-trunc-money", "B1 truncated main, door")
        check_eq("B1 truncated main: the door recomputes it", outcome["status"], "recomputed")
        check_eq("B1 truncated main: and the money stays 4.0 (the request the file lost is kept)",
                 total_at_read(load(root, "s-trunc-money")), 4.0)
        check_eq("B1 truncated main: both requests are still counted (a collapsed ledger: one carry row of 2)",
                 C._rows_usage(load(root, "s-trunc-money")["requests"])[1], 2)

        # the same three cases on a STORY session: per-request rows, by_task and by_activity to keep right
        def story(sid):
            activities = root / "qa-factory" / "state" / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            path = activities / f"{sid}.json"
            path.write_text(json.dumps({
                "schema_version": 1, "session_id": sid,
                "activities": [{"activity_id": "act1", "type": "story", "task": TASK, "start_event_id": "e1",
                                "start_time": "2026-09-20T18:59:00Z", "end_event_id": None, "end_time": None,
                                "status": "open", "segments": [{"segment_id": "seg1", "start_event_id": "e1",
                                    "start_time": "2026-09-20T18:59:00Z", "end_event_id": None, "end_time": None}]}],
                "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown"}),
                encoding="utf-8")
            age(path)

        sm = work / "st-main.jsonl"
        sm.write_text(assistant("m1", tokens=big, output=0) + "\n", encoding="utf-8")
        ssub = work / "st-main" / "subagents"
        ssub.mkdir(parents=True)
        sa = ssub / "agent-1.jsonl"
        sa.write_text(assistant("a1", sidechain=True, tokens=big, output=0) + "\n", encoding="utf-8")
        story("st-main")
        seeded = seed_and_capture(root, sm, "st-main")
        check_eq("B1 story fixture: a story session keeps per-request rows, $4.0",
                 (seeded["has_factory_activity"], len(seeded["requests"]), total_at_read(seeded)), (True, 2, 4.0))
        check_eq("B1 story fixture: the subagent's task entry is in by_task with its 2 requests' worth of tokens",
                 seeded["by_task"][TASK]["requests"], 2)
        sa.unlink()
        age(sm)
        bytes_before = sha(cost_path(root, "st-main"))
        results = stale_pass(root, "B1 story, unattended")
        check_eq("B1 story (mutation a): the unattended pass skips a story session with a gone stream",
                 results.get("st-main", {}).get("status"), "skipped")
        check_eq("B1 story: byte for byte as it was", sha(cost_path(root, "st-main")), bytes_before)
        append(sm, assistant("m2", tokens=big, output=0))
        age(sm)
        results = stale_pass(root, "B1 story, gone + grown")
        check_eq("edge (gone + grown, story): the main tail IS recaptured", results.get("st-main", {}).get("status"),
                 "recomputed")
        grown = load(root, "st-main")
        check_eq("edge (gone + grown, story): $6.0, three per-request rows, the kept subagent row among them",
                 (total_at_read(grown), sorted(r["stream"] for r in grown["requests"])),
                 (6.0, ["agent-1.jsonl", "orchestrator", "orchestrator"]))
        check_eq("edge (gone + grown, story): by_task counts all three requests, and its cost is 6.0",
                 (grown["by_task"][TASK]["requests"], grown["by_task"][TASK]["cost"]), (3, 6.0))
        check_eq("edge (gone + grown, story): agents[] still lists the gone subagent, priced $2",
                 [(a["file"], a["cost"]) for a in grown["agents"]], [("agent-1.jsonl", 2.0)])
        check_eq("edge (gone + grown, story): orchestrator $4 + agent $2 = session total",
                 (grown["orchestrator"]["cost"], grown["reconciliation"]["orchestrator_plus_agents"],
                  grown["reconciliation"]["session_total"]), (4.0, 6.0, 6.0))
        check_eq("edge (gone + grown, story): no tail finding is left", C._tail_findings(grown, C.parse_ts(grown["generated"])),
                 ("", ""))

        stt = work / "st-trunc.jsonl"
        stt.write_text(assistant("r1", tokens=big, output=0) + "\n" + assistant("r2", tokens=big, output=0) + "\n",
                       encoding="utf-8")
        story("st-trunc")
        seed_and_capture(root, stt, "st-trunc")
        stt.write_text(assistant("r1", tokens=big, output=0) + "\n", encoding="utf-8")
        age(stt)
        check_eq("B1 story truncated main: the unattended pass skips it",
                 stale_pass(root, "B1 story truncated, unattended").get("st-trunc", {}).get("status"), "skipped")
        outcome = recap(root, "st-trunc", "B1 story truncated, door")
        truncated = load(root, "st-trunc")
        check_eq("B1 story truncated main: the door keeps both request rows and the $4.0",
                 (outcome["status"], sorted(r["request_id"] for r in truncated["requests"]), total_at_read(truncated),
                  truncated["by_task"][TASK]["requests"]), ("recomputed", ["r1", "r2"], 4.0, 2))
        check_in("B1 story truncated main: the file says which stream's rows were kept", "orchestrator",
                 json.dumps(truncated.get("recapture_carried")))
        # a SECOND recapture (the truncated transcript then gains a request): the kept rows stay kept
        # - the checkpoint now sits at the end of the shorter file, so only `recapture_carried` names them
        append(stt, assistant("r3", tokens=big, output=0))
        age(stt)
        results = stale_pass(root, "B1 story truncated, then grown")
        again = load(root, "st-trunc")
        check_eq("B1 story truncated main, second recapture (mutation g): the rows the first one kept stay, "
                 "and the new tail is recorded ($6.0)",
                 (results.get("st-trunc", {}).get("status"), sorted(r["request_id"] for r in again["requests"]),
                  total_at_read(again), again["by_task"][TASK]["requests"]), ("recomputed", ["r1", "r2", "r3"], 6.0, 3))
        append(tt, assistant("r3", tokens=big, output=0))
        age(tt)
        results = stale_pass(root, "B1 collapsed truncated, then grown")
        check_eq("B1 collapsed truncated main, second recapture: recomputed, and the total does not fall (the "
                 "INVARIANT above); a collapsed ledger compares the stream's usage whole",
                 (results.get("s-trunc-money", {}).get("status"),
                  total_at_read(load(root, "s-trunc-money")) >= 4.0), ("recomputed", True))

        # ------------------------------------------------------------ no checkpoints at all
        t4 = work / "s-nocp.jsonl"
        t4.write_text(assistant("r1") + "\n", encoding="utf-8")
        doc4 = seed_and_capture(root, t4, "s-nocp")
        bare = {k: v for k, v in doc4.items() if k != "scan_checkpoints"}
        old_generated = dict(bare, generated="2020-01-01T00:00:00+00:00")
        new_generated = dict(bare, generated="2099-01-01T00:00:00+00:00")
        check("R3: no checkpoints at all -> falls back to transcript mtime > generated: stale",
              stale(root, "s-nocp", old_generated)[0] is True)
        check_eq("R3: no checkpoints, transcript older than the capture: current",
                 stale(root, "s-nocp", new_generated), (False, ""))
        check_eq("R3: no checkpoints and no `generated` at all: an unknown age reads as stale",
                 stale(root, "s-nocp", {k: v for k, v in bare.items() if k != "generated"})[0], True)

        # ---------------------------------------- F2: a checkpoint with no integer offset (Codex)
        main_key = next(iter(doc4["scan_checkpoints"]))
        receipt = {main_key: {"adapter": "codex-response-usage-v1"}}
        codex_old = dict(doc4, scan_checkpoints=receipt, generated="2020-01-01T00:00:00+00:00")
        is_stale, reason = stale(root, "s-nocp", codex_old)
        check("F2 (mutation b): a receipt with no offset whose file was written after `generated` is stale",
              is_stale, reason)
        check_in("F2: the reason names the file and says what was compared", "s-nocp.jsonl has no byte offset", reason)
        check_eq("F2 control: the same receipt with `generated` AFTER the file's last write is current",
                 stale(root, "s-nocp", dict(doc4, scan_checkpoints=receipt, generated="2099-01-01T00:00:00+00:00")),
                 (False, ""))
        check("F2 edge: a receipt and NO `generated`: an unknown age reads as stale (the safe direction)",
              stale(root, "s-nocp", {k: v for k, v in dict(doc4, scan_checkpoints=receipt).items()
                                     if k != "generated"})[0] is True)
        for label, odd in (("a boolean", True), ("a negative number", -5), ("a string", "12"), ("null", None)):
            check(f"F2 edge: an offset that is {label} is no integer offset: judged by file time",
                  stale(root, "s-nocp", dict(codex_old, scan_checkpoints={main_key: {"offset": odd}}))[0] is True)
        check_eq("F2 edge: a real integer offset is NOT judged by file time (Claude transcripts gain noise lines)",
                 stale(root, "s-nocp", dict(doc4, generated="2020-01-01T00:00:00+00:00"))[0], False)

        # ------------------------------------------------------------ recapture_stale: live, repair
        t5 = work / "s-live.jsonl"
        t5.write_text(assistant("r1") + "\n", encoding="utf-8")
        seed_and_capture(root, t5, "s-live")
        before = load(root, "s-live")["total_cost_usd"]
        append(t5, assistant("r2"))            # the transcript was just written: it is live
        bytes_before = hashlib.sha256(cost_path(root, "s-live").read_bytes()).hexdigest()
        results = stale_pass(root, "R3 live")
        live = results.get("s-live", {})
        check_eq("R3 live (mutation c): a tail-stale transcript written seconds ago is skipped, not recaptured",
                 live.get("status"), "skipped")
        check_in("R3 live: the skip says the transcript is still live", "still live", live.get("reason", ""))
        check_in("R3 live: the skip carries the stale reason too (never dropped)",
                 "transcript grew after this capture", live.get("stale_reason", ""))
        check_eq("R3 live: a skipped file is left byte for byte as it was",
                 hashlib.sha256(cost_path(root, "s-live").read_bytes()).hexdigest(), bytes_before)

        age(t5)                                # the session is over: the same file is repaired
        results = stale_pass(root, "R3 repair")
        check_eq("R3 repair: once the transcript is not live the pass recomputes the file",
                 results.get("s-live", {}).get("status"), "recomputed")
        check_in("R3 repair: the result carries the stale reason", "transcript grew after this capture",
                 results.get("s-live", {}).get("stale_reason", ""))
        repaired = load(root, "s-live")
        check("R3 repair: the repaired file holds the missed request (two requests, money grew)",
              repaired["total_cost_usd"] > before and
              sum(r["usage"]["requests"] for r in repaired["requests"]) == 2,
              f"{before} -> {repaired['total_cost_usd']}")
        check_eq("R3 repair: and it is current afterwards", stale(root, "s-live"), (False, ""))
        t6 = work / "s-live2.jsonl"
        t6.write_text(assistant("r1") + "\n", encoding="utf-8")
        seed_and_capture(root, t6, "s-live2")
        append(t6, assistant("r2"))
        explicit = stale_pass(root, "R3 explicit", explicit=True)
        check_eq("R3: the CLI pass (explicit) has no live window: a person is waiting for the result",
                 explicit.get("s-live2", {}).get("status"), "recomputed")

        # ------------------------------------------------------------ E9: the transcript is gone
        stored = {"session_id": "s-gone", "transcript": str(work / "no-such-transcript.jsonl"),
                  "generated": "2026-09-20T19:05:00+00:00", "total_cost_usd": 3.14,
                  "requests": [{"request_key": "k", "request_id": "r1", "stream": "orchestrator",
                                "model_id": "claude-sonnet-5-5", "provider": "anthropic",
                                "timestamp": "2026-09-20T19:00:00Z",
                                "usage": {"requests": 1, "input": 1_000_000, "output": 0, "cache_read": 0,
                                          "cache_write_5m": 0, "cache_write_1h": 0},
                                "valuation": dict(PIN)}]}
        cost_path(root, "s-gone").write_text(json.dumps(stored), encoding="utf-8")
        try:
            results = stale_pass(root, "E9 gone transcript")
            raised = ""
        except Exception as exc:
            results, raised = {}, repr(exc)
        check_eq("E9 (mutation d): a session whose transcript is gone does not raise", raised, "")
        gone = results.get("s-gone", {})
        check_eq("E9: recapture reports it as not_recomputed", gone.get("status"), "not_recomputed")
        check_in("E9: with the reason", "transcript file no longer present", gone.get("reason", ""))
        kept = load(root, "s-gone")
        check_eq("E9: the cost file keeps its money and its rows (only a status marker is added)",
                 {k: v for k, v in kept.items() if k != "recapture_status"}, stored)
        check_eq("E9: its stored usage still re-prices at read (1M input at the catalogue's 2 per M)",
                 C.revalue_document(kept, {}, None)["total_cost_usd"], 2.0)
        current_gone = dict(stored, has_factory_activity=False)
        check_eq("E9: a current-format file whose transcript is gone is not flagged at all (no evidence)",
                 C._stale_reason(current_gone, work / "none.json"), (False, ""))

        # ------------------------------------------------------------ F3: an unreadable file is reported
        bad, listed = cost_path(root, "s-bad"), cost_path(root, "s-list")
        bad.write_bytes(b"{not json")
        listed.write_text("[1, 2]", encoding="utf-8")
        bad_hash, listed_hash = sha(bad), sha(listed)
        results = stale_pass(root, "F3 unreadable files")
        for sid, what in (("s-bad", "broken JSON"), ("s-list", "a JSON array, not an object")):
            report = results.get(sid, {})
            check_eq(f"F3 (mutation c): an unreadable cost file ({what}) is REPORTED, never dropped",
                     report.get("status"), "skipped")
            check_in(f"F3: the report says the file could not be read ({what})", "could not be read",
                     report.get("reason", ""))
        check_eq("F3: and both files are left byte for byte as they were",
                 (sha(bad), sha(listed)), (bad_hash, listed_hash))
        bad.unlink()
        listed.unlink()

        # ------------------------------------------------------------ F4: a capture that wrote nothing
        tv = work / "s-vanish.jsonl"
        tv.write_text(assistant("v1", tokens=big, output=0) + "\n", encoding="utf-8")
        seed_and_capture(root, tv, "s-vanish")
        before_doc = load(root, "s-vanish")
        real_capture = C._capture

        def vanish(event):
            tv.unlink()                        # the transcript is gone by the time the capture reads it
            return real_capture(event)

        C._capture = vanish
        snap = snapshot(root)
        try:
            outcome = C.recapture_session(root, "s-vanish")
        finally:
            C._capture = real_capture
        no_loss("F4 transcript vanished mid-recapture", snap, snapshot(root))
        check_eq("F4: a capture that exited on a missing transcript mid-way is not_recomputed, not recomputed",
                 outcome.get("status"), "not_recomputed")
        check_in("F4: with the reason (FR-41: an unknown is not reported as a fact)", "disappeared",
                 outcome.get("reason", ""))
        kept = load(root, "s-vanish")
        check_eq("F4: the money is kept ($2)", total_at_read(kept), 2.0)
        check_eq("F4: and the file is as it was - capture_key and checkpoints included (only a status added)",
                 {k: v for k, v in kept.items() if k != "recapture_status"}, before_doc)

        # ------------------------------------------------------------ F5: the lock, and the marker
        check("F5(a): the wait is a named constant of about 8 s (the old one was 20 x 50 ms = 1 s)",
              5.0 <= C.LOCK_WAIT_S <= 10.0, str(C.LOCK_WAIT_S))
        check("F5(b): the age limit is a named constant of about 120 s", 60.0 <= C.LOCK_STALE_S <= 300.0,
              str(C.LOCK_STALE_S))
        scripts_dir = str(SCRIPTS)
        holder_py, racer_py, exit_py = work / "lockholder.py", work / "lockracer.py", work / "exit0.py"
        holder_py.write_text(HOLDER, encoding="utf-8")
        racer_py.write_text(RACER, encoding="utf-8")
        exit_py.write_text("pass\n", encoding="utf-8")
        cost_dir = root / "qa-factory" / "state" / "cost"
        lock_dir = cost_dir / ".writers"
        tl = work / "s-lock.jsonl"
        tl.write_text(assistant("l1", tokens=big, output=0) + "\n", encoding="utf-8")
        age(tl)
        calls = []
        real_run, real_wait = C._run_capture, C.LOCK_WAIT_S
        C._run_capture = lambda event: calls.append(event["session_id"]) or "captured"

        def holder(sid, hold, owner_pid="self", owner_age=0.0):
            ready = work / f"ready-{sid}"
            proc = python_run(holder_py, scripts_dir, lock_dir / sid, ready, hold, owner_pid, owner_age)
            check(f"F5 fixture: a separate process holds the lock of {sid}", wait_for(ready), "holder did not start")
            return proc

        def attempt(sid, **kw):
            err = io.StringIO()
            started = time.monotonic()
            with contextlib.redirect_stderr(err):
                outcome = C._capture_with_wait({"session_id": sid, "transcript_path": str(tl), "cwd": str(root)},
                                               sid, lock_dir / sid, **kw)
            return outcome, time.monotonic() - started, err.getvalue()

        def end(proc):
            proc.kill()
            proc.communicate()

        # HF2-9: a Stop-form `_capture_with_wait` now renders once after every outcome (the mocked `_run_capture`
        # included), and this block, its racer subprocesses and its main() subprocess are about the LOCK, not the render:
        # the one switch silences the render for all of them (the environment is inherited by the subprocesses).
        os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
        try:
            C.LOCK_WAIT_S = 30.0
            proc = holder("s-l1", 2.0)
            outcome, took, err = attempt("s-l1")
            proc.communicate()
            check_eq("F5(a): a capture that finds the lock held waits (polling) and then captures - no loss",
                     (outcome, calls), ("captured", ["s-l1"]))
            check("F5(a): it really waited for the other process (longer than one poll)", took > 0.2, f"{took:.2f}")
            check("F5(a): no marker was left by a capture that got the lock",
                  not C._pending_path(cost_dir, "s-l1").exists())
            check("F5(a): the owner record is removed once the lock is released",
                  not C._owner_path(lock_dir / "s-l1").exists())

            C.LOCK_WAIT_S = 0.6
            proc = holder("s-l2", 60.0)
            owner_pid = json.loads(C._owner_path(lock_dir / "s-l2").read_text(encoding="utf-8"))["pid"]
            check("F5(b) control: the owner record names a LIVE process that is not this one",
                  C._pid_alive(owner_pid) and owner_pid != os.getpid(), str(owner_pid))
            outcome, took, err = attempt("s-l2")
            marker = C._read_pending(C._pending_path(cost_dir, "s-l2")) or {}
            check_eq("F5(b) (mutation e): a lock held by a LIVE process younger than the age limit is NOT broken "
                     "- the capture waited the whole wait and did not run", (outcome, calls), ("deferred", ["s-l1"]))
            check("F5(b): ... and it waited for the whole wait before it stopped", took >= 0.5, f"{took:.2f}")
            check("F5(b) (mutation e): the record of a live, young holder is NOT dropped",
                  C._owner_path(lock_dir / "s-l2").exists() and "dropped" not in err, err)
            check_eq("F5(c) (mutation d): when the lock cannot be taken the capture does NOT return silently: "
                     "the marker exists, with the reason and the time",
                     (bool(marker), "still held" in marker.get("reason", ""), bool(C.parse_ts(marker.get("at")))),
                     (True, True, True))
            check("F5(c): ... and a line on stderr says so (stdout stays clean, FR-14)",
                  "did not run" in err and "marker" in err, err)
            check_in("F5(c): `_stale_reason` reads the marker: the session is stale, with the time",
                     "a capture gave up on the lock at " + marker.get("at", "?"),
                     C._stale_reason({"has_factory_activity": False}, work / "none.json", marker)[1])
            check_eq("F5(c) edge: a debounced capture (asynchronous, a sample) tries once, silently, and leaves "
                     "the marker as it was", (attempt("s-l2", debounced=True)[0], C._read_pending(
                         C._pending_path(cost_dir, "s-l2")) == marker), ("deferred", True))
            end(proc)

            # F1: a stale OWNER RECORD is dropped and the lock retried; a capture NEVER runs without the lock
            C.LOCK_WAIT_S = 0.8
            ran = len(calls)
            proc = holder("s-l3", 60.0, owner_age=C.LOCK_STALE_S + 100)
            outcome, took, err = attempt("s-l3")
            gone_record = not C._owner_path(lock_dir / "s-l3").exists()
            end(proc)
            check_eq("F5(b) (mutation e): a LIVE holder older than the age limit: its record is dropped, the "
                     "lock is still waited for and the capture does NOT run without it - marker, no capture",
                     (outcome, len(calls) - ran, C._pending_path(cost_dir, "s-l3").exists()), ("deferred", 0, True))
            check_in("F5(b): a printed line says the stale record was dropped and why", "over the 120 s limit", err)
            check("F5(b): the stale owner record is gone", gone_record)
            check("F5(b): ... and no line claims the lock was broken", "broken" not in err, err)

            dead = python_run(exit_py)
            dead.communicate()
            check("F5(b) fixture: that process id is really gone", not C._pid_alive(dead.pid))
            ran = len(calls)
            proc = holder("s-l4", 60.0, owner_pid=str(dead.pid))
            outcome, took, err = attempt("s-l4")
            gone_record = not C._owner_path(lock_dir / "s-l4").exists()
            end(proc)
            check_eq("F5(b) (mutation i): a busy lock whose owner RECORD names a dead process has a stale record "
                     "and a live holder: the record is dropped, the capture does NOT run without the lock",
                     (outcome, len(calls) - ran, C._pending_path(cost_dir, "s-l4").exists()), ("deferred", 0, True))
            check_in("F5(b): ... with a printed line that says the owner is gone", "is gone", err)
            check("F5(b): ... the stale record is dropped and nothing says 'broken'", gone_record and "broken" not in err)
            # a holder KILLED while holding: the OS frees the lock, its record stays, the next capture just runs
            proc = holder("s-l6", 60.0)
            end(proc)
            ran = len(calls)
            outcome, took, err = attempt("s-l6")
            check_eq("F5(b) edge: a killed holder leaves a record and a free lock: the next capture takes the "
                     "lock and runs", (outcome, len(calls) - ran, "broken" in err), ("captured", 1, False))
            check_eq("F5(b) edge: an unusable pid (bool, zero, text) is never read as gone - no drop on a guess",
                     [C._pid_alive(x) for x in (True, 0, -3, "x", None)], [True] * 5)
            check_eq("F5(b) edge: this very process is alive", C._pid_alive(os.getpid()), True)

            # a PermissionError while TAKING the lock (seen in the race run on Windows: two processes on a lock
            # file that does not exist yet) is a busy lock - waited for - not a crash that loses the capture
            class Flaky:
                failures = 0

                def __init__(self, root):
                    self.root = root

                @contextlib.contextmanager
                def lock(self):
                    if Flaky.failures > 0:
                        Flaky.failures -= 1
                        raise PermissionError(13, "Permission denied")
                    yield

            real_store = C.EventStore
            C.EventStore = Flaky
            try:
                Flaky.failures = 2
                outcome, took, err = attempt("s-perm")
                check_eq("F5 edge: a PermissionError while taking the lock file is waited out, then the capture runs",
                         (outcome, calls[-1], Flaky.failures), ("captured", "s-perm", 0))
                Flaky.failures = 10 ** 6
                C.LOCK_WAIT_S = 0.3
                outcome, took, err = attempt("s-perm2")
                check_eq("F5 edge: ... and one that never clears leaves the marker (no crash, no silent return)",
                         (outcome, C._pending_path(cost_dir, "s-perm2").exists()), ("deferred", True))
            finally:
                C.EventStore = real_store
                C.LOCK_WAIT_S = 30.0
                C._pending_path(cost_dir, "s-perm2").unlink(missing_ok=True)

            # two captures racing on the lock, two processes (barrier: both ask at the same moment)
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")

            def race(sid, wait_s, hold_s):
                log, go = work / f"race-{sid}.log", work / f"go-{sid}"
                procs = []
                for tag in ("A", "B"):
                    ready = work / f"ready-{sid}-{tag}"
                    procs.append((ready, python_run(racer_py, scripts_dir, lock_dir / sid, log, go, ready, wait_s,
                                                    hold_s, tag, sid, tl, root, env=env)))
                for ready, _proc in procs:
                    wait_for(ready)
                go.write_text("go", encoding="utf-8")
                outs = []
                for _ready, p in procs:
                    out, errs = p.communicate(timeout=180)
                    outs.append(out.strip() + (" | " + errs.strip() if p.returncode else ""))
                return (log.read_text(encoding="utf-8").splitlines() if log.exists() else []), outs

            lines, outs = race("s-r1", 60, 1.0)
            check("F5 race, both patient: the two captures never overlap (start, end, start, end) and both run",
                  len(lines) == 4 and lines[0].startswith("start") and lines[1] == "end" + lines[0][5:]
                  and lines[2].startswith("start") and lines[3] == "end" + lines[2][5:] and lines[0] != lines[2],
                  str(lines))
            check_eq("F5 race, both patient: neither gave up, no marker", (sorted(outs),
                     C._pending_path(cost_dir, "s-r1").exists()), (["captured", "captured"], False))
            lines, outs = race("s-r2", 0.1, 4.0)
            check_eq("F5 race, one impatient: exactly one writes (one start, one end)",
                     (len(lines), sorted(outs)), (2, ["captured", "deferred"]))
            check("F5 race, one impatient: the loser did not return silently - it left the marker",
                  C._pending_path(cost_dir, "s-r2").exists())

            # F1 (the critic's race_dead probe): a holder KILLED while two captures wait. The OS frees the lock
            # when the holder dies; its owner record is stale. Breaking the lock on that record ran both
            # captures at once in 9 of 12 runs. Now: N = 12 runs, no two write windows overlap, every capture
            # runs, nothing says "broken".
            overlaps = broken = not_captured = 0
            shapes = []
            for i in range(12):
                sid = f"s-d{i}"
                log, go = work / f"race-{sid}.log", work / f"go-{sid}"
                holder_proc = holder(sid, 60.0)
                racers = []
                for tag in ("A", "B"):
                    ready = work / f"ready-{sid}-{tag}"
                    racers.append((ready, python_run(racer_py, scripts_dir, lock_dir / sid, log, go, ready, 20, 0.6,
                                                     tag, sid, tl, root, env=env)))
                for ready, _proc in racers:
                    wait_for(ready)
                go.write_text("go", encoding="utf-8")
                time.sleep(0.5)
                end(holder_proc)
                outs = [p.communicate(timeout=180) for _ready, p in racers]
                words = log.read_text(encoding="utf-8").split() if log.exists() else []
                seq = [words[j] + words[j + 1] for j in range(0, len(words) - 1, 2)]
                shapes.append(seq)
                overlaps += seq[:2] in (["startA", "startB"], ["startB", "startA"])
                broken += sum("broken" in e for _o, e in outs)
                not_captured += sum(o.strip() != "captured" for o, _e in outs)
            check_eq("F1: killed holder + two waiting captures, N=12: no overlap of the two write windows, "
                     "both capture, no 'broken' line (mutation i)", (overlaps, broken, not_captured, len(shapes)),
                     (0, 0, 0, 12))
            check("F1: every run wrote start/end pairs one after the other",
                  all(len(s) == 4 and s[0].startswith("start") and s[1] == "end" + s[0][5:] for s in shapes),
                  str(shapes[:3]))

            # main() itself: the Stop hook process, lock held by another process for longer than the wait
            C.LOCK_WAIT_S = real_wait
            proc = holder("s-l5", 120.0)
            started = time.monotonic()
            done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")], input=json.dumps(
                {"hook_event_name": "Stop", "session_id": "s-l5", "transcript_path": str(tl), "cwd": str(root)}),
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root), env=env,
                timeout=300)
            took = time.monotonic() - started
            end(proc)
            check_eq("F5 main(): exit 0 (telemetry never stops the pipeline), stdout empty, marker left",
                     (done.returncode, done.stdout, C._pending_path(cost_dir, "s-l5").exists()), (0, "", True))
            check_in("F5 main(): the line on stderr says the capture did not run", "did not run", done.stderr)
            check("F5 main(): it waited about LOCK_WAIT_S, not 1 s", took >= real_wait - 0.5, f"{took:.1f}")
        finally:
            C._run_capture, C.LOCK_WAIT_S = real_run, real_wait
            if saved_flag is None:
                os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
            else:
                os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = saved_flag
            for sid in ("s-l2", "s-l3", "s-l4", "s-l5", "s-r2"):
                C._pending_path(cost_dir, sid).unlink(missing_ok=True)

        # ---- the marker is answered by the next recapture, and only by a capture that started after it
        tk = work / "s-marker.jsonl"
        tk.write_text(assistant("k1", tokens=big, output=0) + "\n", encoding="utf-8")
        age(tk)
        event_k = {"hook_event_name": "Stop", "session_id": "s-marker", "transcript_path": str(tk),
                   "cwd": str(root), "usage_complete": True}
        C._leave_pending(event_k, "s-marker", tk, "test: the lock was held")
        results = stale_pass(root, "marker, no cost file yet")
        check_eq("F5(c): a marker with NO cost file yet (the session's first capture gave up) is recaptured",
                 results.get("s-marker", {}).get("status"), "recomputed")
        check_in("F5(c): the result carries the marker as the reason", "a capture gave up on the lock at",
                 results.get("s-marker", {}).get("stale_reason", ""))
        check_eq("F5(c): the tail is recorded ($2) and the marker is removed by the successful capture",
                 (total_at_read(load(root, "s-marker")), C._pending_path(cost_dir, "s-marker").exists()), (2.0, False))
        check_eq("F5(c): a second pass finds nothing to do for it", "s-marker" in stale_pass(root, "marker second pass"),
                 False)
        C._leave_pending(event_k, "s-marker", tk, "test: a second give-up, the file is current")
        is_stale, reason = C._stale_reason(load(root, "s-marker"), work / "none.json",
                                           C._read_pending(C._pending_path(cost_dir, "s-marker")))
        check("F5(c): a marker makes even a current file stale", is_stale, reason)
        os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
        try:
            C._capture(event_k)                                  # the ordinary Stop capture: nothing changed
        except SystemExit:
            pass
        check("F5(c): a capture that finds the file current (nothing changed) answers the marker too",
              not C._pending_path(cost_dir, "s-marker").exists())
        C._leave_pending(event_k, "s-marker2", tk, "x")
        C._clear_pending(cost_dir, "s-marker2", started=time.time() - 100)
        check("F5(c) edge: a marker written AFTER a capture began survives it (that capture may not have read the tail)",
              C._pending_path(cost_dir, "s-marker2").exists())
        C._clear_pending(cost_dir, "s-marker2", started=time.time() + 1)
        check("F5(c) edge: a marker older than the capture's start is removed",
              not C._pending_path(cost_dir, "s-marker2").exists())
        C._pending_path(cost_dir, "s-marker3").write_text("{broken", encoding="utf-8")
        C._clear_pending(cost_dir, "s-marker3", started=time.time())
        check("F5(c) edge: an unreadable marker is cleared by a successful capture, not kept forever",
              not C._pending_path(cost_dir, "s-marker3").exists())

        # a marker on a session that already has a cost file with a gone stream: the carry persists
        C._leave_pending({"session_id": "s-gone-sub", "transcript_path": str(tg), "cwd": str(root)},
                         "s-gone-sub", tg, "test")
        results = stale_pass(root, "marker on a file with a gone stream")
        check_eq("F5(c) + B1: a marker on a file with a gone stream is recaptured, and the gone stream's money "
                 "still stays (4.0)", (results.get("s-gone-sub", {}).get("status"),
                                       total_at_read(load(root, "s-gone-sub")),
                                       C._pending_path(cost_dir, "s-gone-sub").exists()), ("recomputed", 4.0, False))

        # edge: a marker for a session whose transcript is gone
        gone_t = work / "s-marker-gone.jsonl"
        C._leave_pending({"session_id": "s-marker-gone", "transcript_path": str(gone_t), "cwd": str(root)},
                         "s-marker-gone", gone_t, "test")
        results = stale_pass(root, "marker, transcript gone")
        check_eq("F5(c) edge: a marker whose transcript is gone is skipped, with the reason, and the marker is kept "
                 "(a person can see it)", (results.get("s-marker-gone", {}).get("status"),
                                           "no longer present" in results.get("s-marker-gone", {}).get("reason", ""),
                                           C._pending_path(cost_dir, "s-marker-gone").exists(),
                                           cost_path(root, "s-marker-gone").exists()), ("skipped", True, True, False))
        C._pending_path(cost_dir, "s-marker-gone").unlink()

        # F3 (FR-40, FR-41): the same, but the session HAS a cost file. The file must say it could not be
        # recomputed (the dashboard's stale-files alert reads that), its money untouched; the explicit door
        # records it again and clears the marker.
        tw = work / "s-marker-gone2.jsonl"
        tw.write_text(assistant("w1", tokens=big, output=0) + "\n", encoding="utf-8")
        seed_and_capture(root, tw, "s-marker-gone2")
        original = load(root, "s-marker-gone2")
        tw.unlink()
        C._leave_pending({"session_id": "s-marker-gone2", "transcript_path": str(tw), "cwd": str(root)},
                         "s-marker-gone2", tw, "test")
        results = stale_pass(root, "F3 marker + gone transcript + cost file")
        after = load(root, "s-marker-gone2")
        check_eq("F3: the unattended pass reports skipped and the marker stays",
                 (results.get("s-marker-gone2", {}).get("status"), C._pending_path(cost_dir, "s-marker-gone2").exists()),
                 ("skipped", True))
        check_eq("F3: the cost file now says `recapture_status.status == not_recomputed` (the alert can list it)",
                 after.get("recapture_status", {}).get("status"), "not_recomputed")
        check_in("F3: with the reason", "transcript file no longer present", after["recapture_status"]["reason"])
        check_eq("F3: the money and every other field are untouched",
                 {k: v for k, v in after.items() if k != "recapture_status"}, original)
        marked_hash = sha(cost_path(root, "s-marker-gone2"))
        stale_pass(root, "F3 second pass")
        check_eq("F3: a second pass writes nothing (no churn on every dashboard build)",
                 sha(cost_path(root, "s-marker-gone2")), marked_hash)
        outcome = recap(root, "s-marker-gone2", "F3 explicit door")
        check_eq("F3: the explicit door (`--recapture --session`) answers not_recomputed and CLEARS the marker "
                 "after recording", (outcome["status"], C._pending_path(cost_dir, "s-marker-gone2").exists(),
                                     load(root, "s-marker-gone2")["recapture_status"]["status"]),
                 ("not_recomputed", False, "not_recomputed"))
        check_eq("F3: and the money is still there (2.0)", total_at_read(load(root, "s-marker-gone2")), 2.0)
        C._leave_pending({"session_id": "s-marker-gone", "transcript_path": str(gone_t), "cwd": str(root)},
                         "s-marker-gone", gone_t, "test")
        outcome = recap(root, "s-marker-gone", "F3 explicit door, no cost file")
        check_eq("F3 edge: the explicit door with NO cost file has nowhere to record, so it keeps the marker",
                 (outcome["status"], C._pending_path(cost_dir, "s-marker-gone").exists()), ("not_recomputed", True))
        C._pending_path(cost_dir, "s-marker-gone").unlink()

        # F5: a transcript rewritten IN PLACE to at least its checkpoint size is neither gone nor past the end
        rw = work / "st-rewrite.jsonl"
        rw.write_text(assistant("m1", tokens=big, output=0) + "\n", encoding="utf-8")
        story("st-rewrite")
        seed_and_capture(root, rw, "st-rewrite")
        append(rw, assistant("m2", tokens=big, output=0))
        age(rw)
        check_eq("F5 fixture: the tail is recaptured, $4.0",
                 (stale_pass(root, "F5 fixture").get("st-rewrite", {}).get("status"),
                  total_at_read(load(root, "st-rewrite"))), ("recomputed", 4.0))
        offset = main_offset(load(root, "st-rewrite"))
        rw.write_text(row(type="system", subtype="x", pad="z" * (offset + 50)) + "\n"
                      + assistant("m3", tokens=big, output=0) + "\n", encoding="utf-8")
        age(rw)
        kind, _why = C._stale_kind(load(root, "st-rewrite"), root / "qa-factory" / "state" / "activities" / "x.json")
        check_eq("F5 fixture: the rewritten file is larger than its checkpoint and holds an unread request: "
                 "kind 'stale', not 'lost'", kind, "stale")
        results = stale_pass(root, "F5 rewrite in place")
        rewritten = load(root, "st-rewrite")
        check_eq("F5 (mutation j): the unattended recapture of a rewritten transcript keeps every earlier "
                 "request the rebuild lacks, and records the new one: $6.0 (was 4.0 -> 2.0)",
                 (results.get("st-rewrite", {}).get("status"), sorted(r["request_id"] for r in rewritten["requests"]),
                  total_at_read(rewritten)), ("recomputed", ["m1", "m2", "m3"], 6.0))
        check_eq("F5: and by_task counts all three", rewritten["by_task"][TASK]["requests"], 3)
        rc = work / "s-rewrite-coll.jsonl"
        rc.write_text(assistant("m1", tokens=big, output=0) + "\n", encoding="utf-8")
        seed_and_capture(root, rc, "s-rewrite-coll")
        append(rc, assistant("m2", tokens=big, output=0))
        age(rc)
        stale_pass(root, "F5 collapsed fixture")
        offset = main_offset(load(root, "s-rewrite-coll"))
        rc.write_text(row(type="system", subtype="x", pad="z" * (offset + 50)) + "\n"
                      + assistant("m3", tokens=big, output=0) + "\n", encoding="utf-8")
        age(rc)
        stale_pass(root, "F5 collapsed rewrite")
        check("F5: a collapsed ledger rewritten in place does not fall either (the stream with more usage "
              "wins whole)", total_at_read(load(root, "s-rewrite-coll")) >= 4.0)

        # ------------------------------------------------------------ Q1 (c): a recapture values afresh
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["cost"] = dict(cfg.get("cost") or {}, model_prices={"claude-sonnet": {
            "input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6}})
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        activities = root / "qa-factory" / "state" / "activities"
        activities.mkdir(parents=True, exist_ok=True)
        (activities / "s-pin.json").write_text(json.dumps({
            "schema_version": 1, "session_id": "s-pin",
            "activities": [{"activity_id": "act1", "type": "story", "task": TASK, "start_event_id": "e1",
                            "start_time": "2026-09-20T18:59:00Z", "end_event_id": None, "end_time": None,
                            "status": "open", "segments": [{"segment_id": "seg1", "start_event_id": "e1",
                                "start_time": "2026-09-20T18:59:00Z", "end_event_id": None, "end_time": None}]}],
            "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown"}), encoding="utf-8")
        t7 = work / "s-pin.jsonl"
        t7.write_text(assistant("r1") + "\n", encoding="utf-8")
        age(t7)
        first = seed_and_capture(root, t7, "s-pin")
        check_eq("Q1c fixture: a story session keeps its per-request ledger", first["has_factory_activity"], True)
        fresh_value = first["requests"][0]["valuation"]["subtotal_usd"]
        check_eq("Q1c fixture: catalogue figure for 1000 input + 50 output of claude-sonnet-5 (2 and 10 per M)",
                 fresh_value, "0.0025")
        pinned = json.loads(json.dumps(first))
        pinned["requests"][0]["valuation"] = dict(PIN)
        pinned["capture_key"] = "forced-by-the-test"
        cost_path(root, "s-pin").write_text(json.dumps(pinned), encoding="utf-8")
        os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
        event = {"hook_event_name": "Stop", "session_id": "s-pin", "transcript_path": str(t7),
                 "cwd": str(root), "usage_complete": True}
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                C._capture(event)
            except SystemExit:
                pass
        check_eq("Q1c control: an INCREMENTAL capture still keeps the valuation a request was first given "
                 "(history stays pinned)", load(root, "s-pin")["requests"][0]["valuation"]["subtotal_usd"], "999")
        outcome = recap(root, "s-pin", "Q1c recapture")
        check_eq("Q1c fixture: the recapture ran", outcome["status"], "recomputed")
        recaptured = load(root, "s-pin")
        check_eq("Q1c (mutation g): a RECAPTURE values every request afresh - the pinned 999 is replaced",
                 recaptured["requests"][0]["valuation"]["subtotal_usd"], fresh_value)
        check_eq("Q1c: and the provenance is the catalogue's, not the legacy family table's",
                 recaptured["requests"][0]["valuation"]["rate_provenance"]["kind"], "bundled_exact")
        check_eq("Q1c: the session total agrees with the fresh valuation", recaptured["total_cost_usd"], 0.0025)

        # ------------------------------------------------ recapture honours the metric-signals skip flag
        state = root / "qa-factory" / "state"
        (state / "metric-signals.json").write_text(json.dumps({"signals": [{
            "id": "sig-1", "status": "open", "evaluation": "evaluated", "title": "a pending signal",
            "current": 1, "baseline": 0, "sample_size": 3, "next_action": "look at it"}]}), encoding="utf-8")
        import dashboard_refresh
        real_refresh = dashboard_refresh.refresh_project
        dashboard_refresh.refresh_project = lambda project: {"status": "skipped"}
        try:
            os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
            buffer = io.StringIO()
            snap = snapshot(root)
            with contextlib.redirect_stdout(buffer):
                C.recapture_session(root, "s-pin")
            no_loss("skip-flag recapture", snap, snapshot(root))
            check_eq("skip flag: a recapture prints no metric-signals notice", buffer.getvalue(), "")
            forced = load(root, "s-pin")
            forced["capture_key"] = "forced-again"
            cost_path(root, "s-pin").write_text(json.dumps(forced), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                try:
                    if C._capture(event):    # flag NOT set: an ordinary Stop capture
                        C._after_capture(event)
                except SystemExit:
                    pass
            check_in("skip flag control: the same pending signal IS printed by an ordinary capture",
                     "Recorded metric signals", buffer.getvalue())
            os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
            forced["capture_key"] = "forced-third"
            cost_path(root, "s-pin").write_text(json.dumps(forced), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                try:
                    if C._capture(event):
                        C._after_capture(event)
                except SystemExit:
                    pass
            check_eq("skip flag: a capture that holds the flag prints no notice", buffer.getvalue(), "")
        finally:
            dashboard_refresh.refresh_project = real_refresh
            os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)

        age(t7)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py"), "--recapture",
                               "--session", "s-pin", "--root", str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=300)
        try:
            printed = json.loads(done.stdout)
        except ValueError:
            printed = None
        check("skip flag / FR-14: `--recapture --session` prints only its JSON result (a pending signal exists)",
              isinstance(printed, list) and printed and printed[0].get("status") == "recomputed",
              (done.stdout[:300] + done.stderr[:300]))
    finally:
        if saved_flag is None:
            os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
        else:
            os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = saved_flag
        cleanup(work)
        cleanup(root)
    finish("test_cost_capture_tail")


if __name__ == "__main__":
    main()
