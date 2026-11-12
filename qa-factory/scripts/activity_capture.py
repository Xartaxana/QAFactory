"""Explicit activity boundaries; never infer activity from prompt prose.

The session an invocation belongs to is found by session_identity.resolve: an id a person gave, the hook event,
or the PreToolUse hook's receipt (`qa-factory/state/host-receipts/`, or the spool under the home before config.json
exists) read together with the host's own variable. No other reader of this script guesses it (B-410)."""
from __future__ import annotations
import argparse, hashlib, json, re, sys, tempfile, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from event_store import atomic_json
from hooklib import project_root, read_event, state_dir
import session_identity

# The ONE set of activity types (COLLECT, CL1-4: `collect` is the packing skill's own type, else its spend reads `unclassified`, P18).
# `TYPES` stays as the same object for the readers that already import it; `dashboard_cost_groups` reads FACTORY_TYPES for its labels.
FACTORY_TYPES = {"onboarding", "doctor", "story", "environment-maintenance", "collect", "unclassified"}
TYPES = FACTORY_TYPES

def _atomic_activity(path, doc):
    for attempt in range(5):
        try:
            atomic_json(path,doc); return
        except PermissionError:
            if attempt==4: raise
            time.sleep(.02*(attempt+1))

def _now(): return datetime.now(timezone.utc).isoformat()

def _segment_id(activity_id, event_id):
    return hashlib.sha256(f"{activity_id}:{event_id}".encode()).hexdigest()[:24]

def activity_path(event, session):
    if not session or session in {".", ".."} or any(c in session for c in "/\\:"):
        raise ValueError("session identity must be a single safe component")
    root = project_root(event)
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    spool = session_identity.spool_root() / "qa-factory-activities" / identity / f"{session}.json"
    if (root / "qa-factory/config.json").is_file():
        target = state_dir(event) / "state" / "activities" / f"{session}.json"
        # Before B-410 the spool lived under the temp folder: an activity recorded there before the
        # upgrade is carried over once, when no file of the new spool is there to win (E24).
        legacy = Path(tempfile.gettempdir()) / "qa-factory-activities" / identity / f"{session}.json"
        source = spool if spool.is_file() else legacy
        if source.is_file() and not target.exists():
            atomic_json(target, json.loads(source.read_text(encoding="utf-8")))
            source.unlink()
        return target
    return spool

def load(path, session):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version":1,"session_id":session,"activities":[],"active_stack":[],"processed_events":{},
                "usage_completeness":"unknown","telemetry_note":"explicit boundaries only"}


def close_pending(event, session):
    """Called by final cost capture, before loading the attribution intervals."""
    if event.get('hook_event_name') != 'Stop':
        return
    path = activity_path(event, session)
    doc = load(path, session)
    pending = doc.get('pending_close')
    if not pending:
        return
    active = next((a for a in doc['activities'] if doc['active_stack'] and a['activity_id']==doc['active_stack'][-1]), None)
    if not active or active['type'] != pending['type'] or active.get('task') != (pending['task'] or None):
        raise ValueError('pending activity does not match active workflow')
    update(path, session, 'end', pending['type'], pending['task'],
           'stop:'+str(event.get('turn_id') or uuid.uuid4().hex), evidence_ref='host Stop after final response')
    doc = load(path, session)
    doc.pop('pending_close', None)
    _atomic_activity(path, doc)

def update(path, session, action, activity_type, task="", event_id="", timestamp="", evidence_ref=""):
    if activity_type not in TYPES: raise ValueError("invalid activity type")
    if action == "start" and not event_id and activity_type != "unclassified":
        activity_type = "unclassified"
        evidence_ref = evidence_ref or "host invocation identity unavailable"
    doc, eid, ts = load(path, session), event_id or uuid.uuid4().hex, timestamp or _now()
    processed = doc.setdefault("processed_events", {})
    event_payload = {"action":action,"type":activity_type,"task":task or None,
                     "evidence_ref":evidence_ref or None}
    if eid in processed:
        if processed[eid] != event_payload:
            raise ValueError(f"activity event {eid} was already recorded with different payload")
        return doc
    if action == "start":
        if doc["active_stack"]:
            parent = next(a for a in doc["activities"] if a["activity_id"] == doc["active_stack"][-1])
            parent["segments"][-1].update(end_event_id=eid, end_time=ts)
        aid = hashlib.sha256(f"{session}:{eid}:{activity_type}:{task}".encode()).hexdigest()[:24]
        if not any(a["activity_id"] == aid for a in doc["activities"]):
            doc["activities"].append({"activity_id":aid,"type":activity_type,"task":task or None,
                "start_event_id":eid,"start_time":ts,"end_event_id":None,"end_time":None,
                "evidence_ref":evidence_ref or None,"status":"open","segments":[{
                "segment_id":_segment_id(aid,eid),"start_event_id":eid,"start_time":ts,"end_event_id":None,"end_time":None}]})
            doc["active_stack"].append(aid)
    elif action == "end":
        if not doc["active_stack"]: return doc
        aid = doc["active_stack"].pop(); item = next(a for a in doc["activities"] if a["activity_id"] == aid)
        item.update(end_event_id=eid,end_time=ts,status="closed"); item["segments"][-1].update(end_event_id=eid,end_time=ts)
        if doc["active_stack"]:
            parent = next(a for a in doc["activities"] if a["activity_id"] == doc["active_stack"][-1])
            parent["segments"].append({"segment_id":_segment_id(parent["activity_id"],eid),
                "start_event_id":eid,"start_time":ts,"end_event_id":None,"end_time":None})
    else: raise ValueError("action must be start or end")
    processed[eid] = event_payload
    _atomic_activity(path,doc); return doc

BACKFILL_CMD = re.compile(
    r"activity_capture\.py[^\n]*?--action\s+(start|end)"
    r"(?:[^\n]*?--type\s+([\w-]+))?"
    r"(?:[^\n]*?--task\s+['\"]?([\w./-]+))?")


def backfill(transcript_path: Path, session: str, activity_type: str, task: str, event: dict | None = None):
    """Rebuild a past session's activity intervals from the explicit start/end boundaries its
    own transcript already tried to record: every one of them failed with
    "session identity missing" for exactly the reason session_identity.resolve now
    fixes going forward, so the story's cost stays attributed to "(no task)"/non-factory forever
    unless replayed. The commands and their real timestamps are still in the transcript's Bash
    tool_use blocks (`activity_capture.py --action start --type story --task T ...`) — this
    replays them through the same update() the live hooks use, so the reconstructed intervals
    have the identical shape a working session would have produced. Only the requested
    (activity_type, task) is replayed; unrelated activity types in between are skipped, which
    still yields one correctly-bounded interval for the one being recovered."""
    event = event or {}
    path = activity_path(event, session)
    replayed = 0
    for line in transcript_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
        for block in blocks:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            command = str((block.get("input") or {}).get("command", ""))
            m = BACKFILL_CMD.search(command)
            if not m:
                continue
            action, kind, found_task = m.group(1), m.group(2) or "unclassified", m.group(3) or ""
            if kind != activity_type or (task and found_task and found_task != task):
                continue
            eid = "backfill:" + str(block.get("id") or rec.get("uuid") or rec.get("requestId") or uuid.uuid4().hex)
            update(path, session, action, kind, task or found_task, eid, str(rec.get("timestamp") or ""),
                   "backfilled from transcript Bash tool_use")
            replayed += 1
    doc = load(path, session)
    recovery = doc.setdefault("recovery", {})
    recovery["backfilled_from_transcript"] = True
    recovery["backfilled_events"] = recovery.get("backfilled_events", 0) + replayed
    _atomic_activity(path, doc)
    return {"replayed": replayed, "path": str(path)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--action",choices=("start","end")); ap.add_argument("--type",choices=sorted(TYPES),default="unclassified"); ap.add_argument("--task",default=""); ap.add_argument("--session",default=""); ap.add_argument("--event-id",default=""); ap.add_argument("--timestamp",default=""); ap.add_argument("--evidence-ref",default=""); ap.add_argument("--after-response",action="store_true"); ap.add_argument("--backfill",action="store_true"); ap.add_argument("--transcript",default=""); a=ap.parse_args()
    if a.backfill:
        if not a.session or not a.transcript:
            print("ACTIVITY NOT RECORDED: --backfill requires --session and --transcript.",file=sys.stderr)
            return 1
        result=backfill(Path(a.transcript), a.session, a.type, a.task)
        print(json.dumps(result)); return 0
    event=read_event() or {}
    found=session_identity.resolve(event,a.session,"activity_capture.py")
    session=found["session_id"]
    action=a.action or event.get("activity_action")
    if not session:
        if action:
            print("ACTIVITY NOT RECORDED: "+session_identity.refusal(found,"activity_capture.py"),file=sys.stderr)
        return 0
    if action not in {"start","end"} and event.get("hook_event_name") != "Stop":
        return 0
    path=activity_path(event,session); doc=load(path,session)
    if event.get("hook_event_name") == "Stop" and not action:
        pending=doc.get("pending_close")
        if not pending: return 0
        action="end"
        kind,task=pending["type"],pending["task"]
        eid="stop:"+str(event.get("turn_id") or event.get("tool_use_id") or uuid.uuid4().hex)
        evidence="host Stop after final response"
    else:
        kind=str(event.get("activity_type") or a.type); task=str(event.get("task") or a.task)
        eid=str(event.get("event_id") or a.event_id)
        evidence=str(event.get("evidence_ref") or a.evidence_ref)
        if a.action and not eid:
            eid="invocation:"+uuid.uuid4().hex
            evidence=evidence or "explicit activity_capture CLI invocation"
    if eid in doc.get('processed_events', {}):
        update(path,session,action,kind,task,eid,str(event.get('timestamp') or a.timestamp),evidence)
        return 0
    active=next((x for x in doc["activities"] if doc["active_stack"] and x["activity_id"]==doc["active_stack"][-1]),None)
    if action=="start" and active and active["type"]==kind and active.get("task")== (task or None):
        return 0  # continuation of the same still-open workflow
    if action=="end" and active and (active["type"]!=kind or active.get("task")!=(task or None)):
        raise ValueError("activity end does not match the active workflow")
    if action=="end" and a.after_response:
        doc["pending_close"]={"type":kind,"task":task}
        _atomic_activity(path,doc); return 0
    update(path,session,action,kind,task,eid,str(event.get("timestamp") or a.timestamp),evidence)
    if action=="end":
        doc=load(path,session); doc.pop("pending_close",None); _atomic_activity(path,doc)
    return 0

if __name__=="__main__": raise SystemExit(main())
