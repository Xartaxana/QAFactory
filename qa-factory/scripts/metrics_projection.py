"""Pure local metrics projection. Missing evidence is not a successful observation."""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median, mean
import hashlib
import html
import json
import re
from decimal import Decimal, InvalidOperation

from event_store import atomic_json, content_hash
import contract as C
import runtime_paths as RP
from hooklib import sorted_paths

REF = Path(__file__).resolve().parents[1] / "references"
CATALOGUE = json.loads((REF / "metrics/catalogue.json").read_text(encoding="utf-8"))
BANDS = json.loads((REF / "tokenomics-baseline.json").read_text(encoding="utf-8"))["bands"]

# A baseline is comparable only on an equal `formula_version` (metric_signals.evaluate,
# dashboard_widgets trends). The price a story costs now comes from the story's own rate base
# (owner, 30.09, P18), so the history of every metric that reads a usd figure was measured on another
# base (cmp1 priced with the 1.5x override) and must not be compared with the new points: those metrics
# start at version 2. The table is DATA: a metric id that is not in it is version 1, so a metric added
# later never inherits a bump by accident, and the version is set where the metric is built
# (`compute`), never patched afterwards. The money readers of the metrics below are the `subtotal_usd`
# readers of `compute` and `project`:
#   C02  estimated USD            the value IS the subtotal
#   C06  requests/tools/rework    `rework_usd` in its value
#   C08  tokenomics band hit      a task's `complete_cost` against the USD band
#   C09  band vs actual           the band and the median `complete_cost`, USD
#   C10  cost drift               % of the USD band
#   C11  MMRE and PRED(25)        errors of `complete_cost` against the USD band
#   C15  monetary ROI             `comparable_actual_model_usd` is its denominator
#   F08  orchestrator shares      `cost_percent` is a share of the subtotal
# Not here: C01 (tokens), C03 (a verdict that three sums of ONE request set agree), C04/C05/C07 (seconds),
# C12/C13 (sizes and drivers), C14 (hours), F09 (not computed here: it reads the receipts) and every T/A/F
# metric of a count or a rate of events.
MONEY_FORMULA_VERSION = 2
MONEY_METRICS = frozenset({"C02", "C06", "C08", "C09", "C10", "C11", "C15", "F08"})


def formula_version_of(metric_id) -> int:
    """The formula version a metric is built with: MONEY_FORMULA_VERSION for an id of MONEY_METRICS, else 1."""
    return MONEY_FORMULA_VERSION if metric_id in MONEY_METRICS else 1


def timestamp(value):
    try:
        if isinstance(value, (int,float)):
            return datetime.fromtimestamp(value,timezone.utc)
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def retry_reason_of(dispatch, parent):
    """Why this dispatch is a second attempt: its own stamp, or its parent classified now.

    The controller stamps `retry_reason` at dispatch time (0.7.15); anything older is read
    through `contract.retry_reason_for`. Creating a retry supersedes its parent in the same
    transition, so by the time a reader sees the state the parent's status says `superseded`
    and the progress rule can no longer match it. Only a checkpointed dispatch can be resumed
    at all -- the controller refuses every other status -- so `superseded` here is read as the
    `incomplete` it was (on TP1-15045 two of the ten retries read `unknown` for no other
    reason).
    """
    stamped = str((dispatch or {}).get("retry_reason") or "")
    if C.retry_reason_valid(stamped):
        return stamped
    parent = parent if isinstance(parent, dict) else {}
    if str(parent.get("status") or "") == "superseded":
        parent = dict(parent, status="incomplete")
    return C.retry_reason_for(parent, str((dispatch or {}).get("retry_words") or ""))


def read_json(path, errors):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        errors.append(f"{path}: {exc}")
        return {}


def identity(row):
    return (str(row.get("repo_id", "")), str(row.get("profile_id", "")),
            str(row.get("instance_id") or row.get("test_instance_id") or row.get("test_id") or ""),
            str(row.get("parameter_id", "")))


def mark_duplicate_executions(attempts):
    """Flag every executed attempt that re-runs an identity whose most recent conclusive
    result, under the SAME fingerprint (nothing changed), already passed — feeds A09
    ("Duplicate execution") from run-blocks (on TP1-15045, 18 launches for ~42 test
    executions, ~9 of them redundant — eight re-ran green tests untouched by repair). A
    fingerprint change or an intervening failure clears the "already-current passing" state,
    so a genuine repair re-run, or the first run after a real fix, is never flagged.
    Mutates each row in place; every row — imported or executed — gets the field, so
    compute()'s completeness gate (`all("duplicate_execution" in r for r in local)`) is
    satisfied once this has run over `data["attempts"]`."""
    state: dict = {}
    for row in sorted(attempts, key=lambda r: r.get("started_at") or ""):
        key = (row.get("task"), identity(row))
        prior = state.get(key)
        fp = row.get("fingerprint")
        row["duplicate_execution"] = bool(
            prior and prior[0] in ("pass", "passed") and fp and prior[1] == fp
            and row.get("purpose") in ("initial", "repair_verify") and row.get("origin") == "executed")
        status = row.get("status")
        if status in ("pass", "passed", "fail", "failed"):
            state[key] = (status, fp)


def compute(data, now=None):
    """Normalized inputs are immutable facts; no IO, model calls or test execution."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=data.get("window_days", 30)-1)
    metrics = {r["id"]: dict(id=r["id"], label=r["label"], value=None, unit="count",
               numerator=None, denominator=None, status="unavailable", reason="Required evidence not recorded",
               sample_size=0, evidence_refs=[], scope="project", formula_version=formula_version_of(r["id"]),
               window_start=start.isoformat(), window_end=now.isoformat()) for r in CATALOGUE}

    def put(key, value, unit="count", status="available", reason="", n=0, refs=None):
        metrics[key].update(value=value, unit=unit, status=status, reason=reason,
                            sample_size=n, evidence_refs=refs or data.get("evidence_refs", []))

    def ratio(key, numerator, denominator, **kwargs):
        put(key, 100*numerator/denominator if denominator else None, "%",
            **dict({"status":"available" if denominator else "no_data"}, **kwargs))
        metrics[key].update(numerator=numerator, denominator=denominator, sample_size=denominator)

    def window(value):
        ts = timestamp(value)
        return ts is not None and start <= ts <= now

    obligations = data.get("obligations", [])
    current = [o for o in obligations if o.get("scope") == "current_task" and o.get("approved")]
    critical = [o for o in current if o.get("priority") in {"P0", "P1"}]
    if data.get("plan_known"):
        ratio("T01", sum(bool(o.get("verified")) for o in current), len(current))
        metrics['T01']['breakdown']=dict(Counter('evidenced' if o.get('verified') else o.get('completion') or 'unverified' for o in current))
        ratio("T02", sum(bool(o.get("verified")) for o in critical), len(critical),
              reason="Unknown priorities are listed separately" if any(not o.get("priority") for o in current) else "")
        metrics['T02']['unknown_priority']=sum(not o.get('priority') for o in current)
        if metrics['T02']['unknown_priority']:
            metrics['T02'].update(status='partial',reason='Critical denominator excludes obligations with unknown priority; resolve the priority gaps')
        ratio("A06", sum(o.get("design_assessment") == "sufficient" and o.get("decision") not in {"manual-agent", "manual-human", "unresolved"} for o in critical), len(critical))
        put("T06", {"recommended_regression_not_run":sum(o.get("scope") == "recommended_regression" for o in obligations),
                    "unverified_current":sum(not o.get("verified") for o in current)}, n=len(obligations))
    rows = data.get("current_results", [])
    if data.get("results_known"):
        put("T03", dict(Counter(r.get("status", "unknown") for r in rows)), n=len(rows))
        levels = Counter(r.get("level") or "unknown" for r in rows)
        put("T04", {k:{"count":v,"percent":100*v/len(rows)} for k,v in levels.items()}, n=len(rows))
        metrics['T03']['breakdown'] = {axis:dict(Counter(str(r.get(axis) or 'unknown')+' / '+str(r.get('status','unknown')) for r in rows)) for axis in ('task','level','repo_id','owner')}
    selected = data.get("selected_automated")
    if selected is not None:
        automated_rows=data.get('automated_results',rows)
        ratio("A02", sum(r.get("status") in {"pass", "passed"} and not r.get("stale") for r in automated_rows), selected)
        if data.get("reuse_classification_complete"):
            ratio("A10", sum(bool(r.get("reused")) and not r.get("stale") for r in automated_rows), selected)
        else:
            metrics["A10"]["reason"] = ("Exact-revision scheduler receipts do not classify every "
                                         "selected automated instance as reused or newly launched")
    manual = data.get("manual_cases")
    if manual is not None:
        ratio("T05", sum(bool(r.get("evidence_complete")) for r in manual), len(manual))
        metrics['T05']['breakdown'] = dict(Counter(r.get('status','pending') for r in manual if r.get('evidence_complete')))

    attempts = [r for r in data.get("attempts", []) if r.get("purpose") in {"initial", "repair_verify", "diagnostic", "flaky_diagnostic"}
                and window(r.get("started_at"))]
    cohorts = defaultdict(list)
    for row in attempts:
        if row.get("fingerprint") and identity(row)[2]:
            cohorts[(row.get("task"), identity(row), row["fingerprint"])].append(row)
    firsts, flaky, rescued, failed_first = [], 0, 0, 0
    for group in cohorts.values():
        group = sorted(group, key=lambda r: r["started_at"])
        conclusive = [r for r in group if r.get("status") in {"pass", "passed", "fail", "failed"}]
        if not conclusive:
            continue
        first_pass = conclusive[0]["status"] in {"pass", "passed"}
        firsts.append(first_pass)
        failed_first += not first_pass
        # A common content fingerprint alone does not prove stable runtime/data isolation.
        equivalent = all(r.get("equivalence_verified") is True for r in conclusive)
        passes = [r["status"] in {"pass", "passed"} for r in conclusive]
        flaky += equivalent and any(passes) and not all(passes)
        rescued += equivalent and not first_pass and any(passes[1:])
    if data.get("attempt_history_known"):
        ratio("A01", sum(firsts), len(firsts))
        equivalence_known = all(r.get("equivalence_verified") is True for r in attempts)
        ratio("A03", flaky, len(firsts), status="available" if equivalence_known and firsts else "unavailable",
              reason="Equivalent runtime and data evidence required; no diagnostic reruns are added")
        ratio("A04", rescued, failed_first, status="available" if equivalence_known and failed_first else "no_data" if not failed_first else "unavailable")
        conclusive = [r for r in attempts if r.get("status") in {"pass", "passed", "fail", "failed"}]
        failures = [r for r in conclusive if r["status"] in {"fail", "failed"}]
        if all("red_lock_valid" in r for r in failures):
            ratio("A05", sum(not r["red_lock_valid"] for r in failures), len(conclusive))
        else:
            metrics["A05"]["reason"] = ("Validated red-lock proof bound to each failed instance and "
                                         "fingerprint is not recorded")
        local = [r for r in attempts if r.get("origin") == "executed"]
        if all("duplicate_execution" in r for r in local):
            ratio("A09", sum(r["duplicate_execution"] for r in local), len(local))
        else:
            metrics["A09"]["reason"] = ("Launch selection provenance and prior fresh-result/invalidation "
                                         "history are incomplete; duplicate status is unknown")
    jobs = [j for j in data.get("jobs", []) if window(j.get("start"))]
    durations = [(timestamp(j["end"])-timestamp(j["start"])).total_seconds() for j in jobs
                 if timestamp(j.get("end")) and timestamp(j.get("start")) and timestamp(j["end"]) >= timestamp(j["start"])]
    if data.get("attempt_history_known"):
        # jobs_by_window: one run-execution job per S5 window (the controller's own
        # dispatch.window, coverage_contract.py's own S5-acceptance key) — the launch-volume
        # half of "18 launches, ~3 windows, ~9 launches redundant" on TP1-15045.
        jobs_by_window = Counter(f"window {j['window']}" if j.get("window") is not None else "unscoped"
                                 for j in jobs)
        put("A07", {"jobs":len(jobs), "summed_execution_seconds":sum(durations),
                    "median_job_seconds":median(durations) if durations else None,
                    "unique_instances":len({identity(r) for r in attempts}),
                    "jobs_by_window":dict(jobs_by_window)},
            status="partial" if len(durations)<len(jobs) else "available", n=len(durations))
    if "health" in data:
        put("A08", data["health"], status="partial", reason="Known inspected records, not a certification of the entire suite")

    bugs = list({b['id']:b for b in data.get("bugs", [])}.values())
    if data.get("bugs_known"):
        put("T07", dict(Counter((b.get("severity", "unknown")+" / "+b.get("status", "unknown")) for b in bugs)), n=len(bugs),
            reason="Recorded bugs only; not a census of all product defects. Scope: "+str(data.get('bug_scope','local records')))
        metrics['T07']['publication']=dict(Counter('published' if b.get('published') or b.get('external_url') else 'draft_or_unknown' for b in bugs))
        weights = data.get("severity_weights") or {"blocker":8,"critical":5,"major":3,"minor":1}
        areas = Counter()
        for bug in bugs:
            if str(bug.get("severity", "")).lower() in weights:
                areas[bug.get("area") or "Unknown"] += weights[str(bug["severity"]).lower()]
        import math
        count=math.ceil(len(areas)*data.get("bugginess_report_share",.5))
        put("T08", dict(sorted(areas.items(),key=lambda item:(-item[1],item[0]))[:count]), unit="weighted bugs", n=len(bugs),
            status="partial" if any(str(b.get("severity","")).lower() not in weights for b in bugs) else "available")
        open_bugs = [b for b in bugs if b.get("status") in {"Open","Fixed","Reopened","Blocked","Intended"}]
        ages = {b["id"]:max(0,(now-timestamp(b["created_at"])).total_seconds()/86400) if timestamp(b.get('created_at')) else None for b in open_bugs}
        put("T09", dict(sorted(ages.items(),key=lambda p:-(p[1] if p[1] is not None else -1))), unit="days", status="partial" if None in ages.values() else "available", n=sum(v is not None for v in ages.values()))
        cohort = [b for b in bugs if window(b.get("created_at"))]
        if all(timestamp(b.get("created_at")) for b in bugs):
            ratio("T11", sum(b.get("status")=="Rejected" for b in cohort), len(cohort),
                  status='partial' if any(not b.get('status') for b in cohort) else 'available' if cohort else 'no_data',reason='Window-created cohort, disposition as of projection time')
        full = all(timestamp(b.get("history_complete_since")) and timestamp(b["history_complete_since"]) <= start for b in bugs)
        if full:
            closed, fixed, reopened, cycles, ttf = set(), set(), set(), {}, []
            close_transitions=0;ttf_groups=defaultdict(list);ttf_eligible=0
            for b in bugs:
                transitions = b.get("transitions", [])
                cyc = sum(t.get("to")=="Reopened" for t in transitions)
                if cyc >= 2:
                    cycles[b["id"]] = cyc
                for t in transitions:
                    if window(t.get("at")):
                        if t.get("to") in {"Closed","Verified","Rejected","Duplicate"}:
                            closed.add(b["id"]);close_transitions+=1
                        if t.get("to")=="Fixed": fixed.add(b["id"])
                        if t.get("from")=="Fixed" and t.get("to")=="Reopened": reopened.add(b["id"])
                fixes = sorted(t["at"] for t in transitions if t.get("to")=="Fixed" and timestamp(t.get("at")))
                if fixes and window(fixes[0]):ttf_eligible+=1
                if fixes and window(fixes[0]) and timestamp(b.get("created_at")) and timestamp(b["history_complete_since"]) <= timestamp(b["created_at"]):
                    duration=(timestamp(fixes[0])-timestamp(b["created_at"])).total_seconds()/86400
                    if duration>=0:
                        ttf.append(duration)
                        ttf_groups[str(b.get('priority') or 'unknown')+' / '+str(b.get('area') or 'unknown')].append(duration)
            put("T10", {"opened":len(cohort), "closed":len(closed),'close_transitions':close_transitions}, n=len(bugs))
            ratio("T12", len(reopened), len(fixed|reopened))
            put("T13", median(ttf) if ttf else None, "days", status="partial" if len(ttf)<ttf_eligible else "available" if ttf else "no_data", n=len(ttf))
            metrics['T13'].update(eligible=ttf_eligible,breakdown={k:{'median_days':median(v),'n':len(v)} for k,v in ttf_groups.items()})
            put("T14", cycles, n=len(cycles))

    if "registry" in data:
        registry=[]
        for r in data['registry']:
            created=timestamp(r.get('created')); closed=str(r.get('status','open')).lower().startswith('closed')
            age=max(0,(now-created).total_seconds()/86400) if created and not closed else None
            registry.append(dict(r,age_days=age,age_weeks=age/7 if age is not None else None))
        put("F01", {'counts':dict(Counter(('closed' if str(r.get('status','open')).lower().startswith('closed') else 'open')+' / '+str(r.get('scope') or 'DD') for r in registry)), 'items':registry}, n=len(registry))
    unique_events = {e.get("event_id") or e.get("id") or content_hash(e): e for e in data.get("events", [])}
    events = [e for e in unique_events.values() if window(e.get("timestamp") or e.get("ts") or e.get("created_at"))]
    if data.get("events_known"):
        typ = lambda e:e.get("type") or e.get("event")
        rejected = [e for e in events if typ(e) in {"rejected", "reject"}]
        accepted = [e for e in events if typ(e) in {"accepted", "accept"}]
        put("F02", {"by_role":dict(Counter(e.get("role") or e.get("agent") or e.get("payload",{}).get("role") or "unknown" for e in rejected)),
                    "by_reason":dict(Counter(e.get("reason") or e.get("payload",{}).get("reason") or "not recorded" for e in rejected)),
                    "rejected":len(rejected), "accepted":len(accepted),
                    "rate":100*len(rejected)/(len(rejected)+len(accepted)) if rejected or accepted else None}, n=len(rejected)+len(accepted))
        put("F03", {k:sum(typ(e)==k for e in events) for k in ("gate_block","unsafe_completion")}, n=len(events))
    dispatches = data.get("dispatches", [])
    if data.get("controller_known"):
        retry = [d for d in dispatches if d.get("parent_retry")]
        indexed={d.get('id'):d for d in dispatches}
        # "retry dispatches: 10 - parents (10)" was the whole of this metric on TP1-15045:
        # ten repeats, one parent id each, no cause. The parent ids named nothing a reader
        # could act on; the cause is the finding, so the value is the split by reason. A
        # dispatch written before 0.7.15 carries no `retry_reason` and is classified here from
        # its parent, so old and new stories read in one vocabulary.
        put("F05", {"retries":len(retry), "dispatches":len(dispatches),
                    "percent":100*len(retry)/len(dispatches) if dispatches else None,
                    "by_reason":dict(Counter(retry_reason_of(d, indexed.get(d["parent_retry"]))
                                             for d in retry))}, n=len(dispatches))
        put("F06", [{k:d.get(k) for k in ("task","stage","status","reason")} for d in dispatches if d.get("status") in {"blocked","paused","incomplete","halted"}], n=len(dispatches))
        put("F07", data.get("projection_issues", []), n=len(data.get("projection_issues", [])))

    sessions = data.get("sessions", [])
    if sessions:
        tokens = lambda models:sum(sum(v.get(k,0) or 0 for k in ("input","output","cache_read","cache_write_5m","cache_write_1h")) for v in models.values())
        request_sessions = [s for s in sessions if isinstance(s.get('requests'),list)]
        legacy_sessions = [s for s in sessions if not isinstance(s.get('requests'),list) and
                           (window(s.get('ended') or s.get('started')) or
                            not (s.get('ended') or s.get('started')))]
        requests = [r for s in request_sessions for r in s.get('requests',[]) if window(r.get('timestamp'))]
        req_tokens = lambda r:sum((r.get('usage') or {}).get(k,0) or 0 for k in
                                  ("input","output","cache_read","cache_write_5m","cache_write_1h"))
        total_tokens = sum(req_tokens(r) for r in requests) + sum(tokens(s.get("by_model",{})) for s in legacy_sessions)
        orch_tokens = sum(req_tokens(r) for r in requests if r.get('stream')=='orchestrator') + sum(
            tokens(s.get("orchestrator",{}).get("by_model",{})) for s in legacy_sessions)
        usage_complete = all(s.get('usage_completeness')=='complete' for s in request_sessions) and all(
            s.get('usage_status')=='actual' for s in legacy_sessions)
        coverages=[(r.get('valuation') or {}).get('pricing_coverage','none') for r in requests]
        complete_prices = all(x=='complete' for x in coverages) and all(
            s.get('pricing_coverage')=='complete' for s in legacy_sessions)
        subtotal_decimal=Decimal('0')
        for r in requests:
            try:subtotal_decimal+=Decimal(str((r.get('valuation') or {}).get('subtotal_usd','0')))
            except InvalidOperation:complete_prices=False
        for s in legacy_sessions:
            subtotal_decimal+=Decimal(str(s.get('priced_subtotal_exact_usd',s.get('priced_subtotal_usd',0)) or 0))
        subtotal=float(subtotal_decimal)
        put("C01", total_tokens,"tokens", status="available" if usage_complete else "partial",
            reason="Request timestamps define the reporting window; legacy whole-session rows are partial" if legacy_sessions else "", n=len(requests)+len(legacy_sessions))
        put("C02", subtotal,"USD",status="available" if complete_prices else "partial",
            reason="Known subtotal from pinned request valuations; missing exact prices excluded",n=len(requests)+len(legacy_sessions))
        matches = [(s.get("reconciliation") or {}).get("match") for s in legacy_sessions]
        if requests:
            request_dimensions_complete=all(r.get('request_key') and r.get('model_id') and
                r.get('activity_id') and r.get('activity_segment_id') and r.get('stream') for r in requests)
            def dimension_totals(field):
                groups=defaultdict(lambda:{'tokens':0,'usd':Decimal('0')})
                for row in requests:
                    key=row.get(field)
                    groups[key]['tokens']+=req_tokens(row)
                    groups[key]['usd']+=Decimal(str((row.get('valuation') or {}).get('subtotal_usd','0')))
                return (sum(v['tokens'] for v in groups.values()),sum((v['usd'] for v in groups.values()),Decimal('0')))
            totals=[dimension_totals(field) for field in ('model_id','activity_segment_id','stream')]
            reconciled=len(set(t[0] for t in totals))==1 and max(t[1] for t in totals)-min(t[1] for t in totals)<=Decimal('0.000001')
            matches.append(reconciled if usage_complete and complete_prices and request_dimensions_complete else None)
        put("C03", "mismatch" if False in matches else "matched" if all(m is True for m in matches) else "unknown",
            status="available" if matches and all(m is not None for m in matches) else "unavailable",n=len(requests)+len(legacy_sessions))
        whole_sessions=[s for s in sessions if window(s.get('started')) and window(s.get('ended'))]
        waits=[s.get('human_wait_s') for s in whole_sessions]
        if any(w is not None for w in waits):
            put("C04",sum(w for w in waits if w is not None),"seconds",
                status='partial' if None in waits or len(whole_sessions)<len(sessions) else 'available',reason="Capped estimate; only sessions wholly inside window")
        activity_times=defaultdict(list)
        for r in requests:
            if timestamp(r.get('timestamp')) and r.get('stream')=='orchestrator' and r.get('activity_segment_id'):
                activity_times[r['activity_segment_id']].append(timestamp(r['timestamp']))
        intervals=sum(max(0,len(stamps)-1) for stamps in activity_times.values())
        active_seconds=sum(sum(min((b-a).total_seconds(),120) for a,b in zip(sorted(stamps),sorted(stamps)[1:]))
                           for stamps in activity_times.values())
        legacy_times=[v.get("active_s") for s in legacy_sessions for v in s.get("by_activity",{}).values()]
        if requests or any(t is not None for t in legacy_times):
            put("C05",active_seconds+sum(t for t in legacy_times if t is not None),"seconds",
                status="partial" if legacy_sessions or not usage_complete else "available" if intervals else "no_data",
                reason="Adjacent main-chain request gaps capped at 120 seconds within uninterrupted activity segments",n=intervals)
        put("F08", {"token_percent":100*orch_tokens/total_tokens if total_tokens else None,
                    "cost_percent":100*float(sum((Decimal(str((r.get('valuation') or {}).get('subtotal_usd','0')))
                        for r in requests if r.get('stream')=='orchestrator'),Decimal('0')))/subtotal if complete_prices and subtotal else None})
        marathons = [a for s in sessions for a in s.get("agents",[]) if sum(v.get("requests",0) for v in a.get("by_model",{}).values())>80]
        put("F04",len(marathons),n=sum(len(s.get("agents",[])) for s in sessions))
        retry_ids={d.get('id') for d in dispatches if d.get('parent_retry') or d.get('purpose')=='repair_verify'}
        reqs=requests
        rework=[r for r in reqs if r.get('dispatch_id') in retry_ids]
        linked=bool(reqs) and all(r.get('dispatch_id') or r.get('stream')=='orchestrator' for r in reqs)
        rework_cost=sum(float(r.get('valuation',{}).get('subtotal_usd',0)) for r in rework)
        put("C06", {"requests":len(reqs)+sum(v.get("requests",0) for s in legacy_sessions for v in s.get("by_model",{}).values()),
                    "tools":dict(sum((Counter(s.get('tools',{})) for s in whole_sessions),Counter())),
                    "rework_usd":rework_cost if linked and complete_prices else None}, status="available" if linked and complete_prices else "partial", reason="Rework requires explicit dispatch-purpose attribution and complete valuation",n=len(reqs))
    first_times = data.get("time_to_first_test", [])
    if first_times: put("C07",median(first_times),"seconds",n=len(first_times))
    estimates = data.get("estimates", [])
    pairs, costs, driver_counts, revisions = [], defaultdict(list), Counter(), Counter()
    for r in estimates:
        forecast = r.get("forecast") or {}
        size = forecast.get("size_final") or forecast.get("size_initial")
        if size in BANDS and r.get("complete_cost") is not None:
            cost = r["complete_cost"]; pairs.append((cost,BANDS[size])); costs[size].append(cost)
        if r.get('completed') and forecast.get("size_initial") and forecast.get("size_final"):
            revisions[forecast["size_initial"]+" -> "+forecast["size_final"]]+=1
        if r.get('completed'):
            for driver in set(str(d) for d in r.get("drivers",[])):driver_counts[driver]+=1
    if estimates:
        ratio("C08",sum(lo<=cost<=hi for cost,(lo,hi) in pairs),len(pairs))
        completed_valid=[r for r in estimates if r.get('completed') and
                         ((r.get('forecast') or {}).get('size_final') or (r.get('forecast') or {}).get('size_initial')) in BANDS]
        metrics['C08']['excluded']={
            'missing_or_partial_price':sum(r.get('complete_cost') is None for r in completed_valid),
            'missing_final_size':sum(bool(r.get('completed')) and not (((r.get('forecast') or {}).get('size_final') or
                                  (r.get('forecast') or {}).get('size_initial')) in BANDS) for r in estimates),
            'not_completed':sum(not r.get('completed') for r in estimates)}
        metrics['C08']['provisional']=sum(bool(r.get('completed')) and r.get('complete_cost') is None for r in estimates)
        put("C09",{s:{"band":BANDS[s],"median":median(v),"n":len(v)} for s,v in costs.items()},"USD",status="available" if costs else "unavailable")
        if pairs: put("C10",100*median((cost-hi)/hi for cost,(_,hi) in pairs),"%",n=len(pairs))
        errors=[abs(cost-hi)/cost for cost,(_,hi) in pairs if cost>0]
        if errors: put("C11",{"MMRE":mean(errors),"PRED25":100*sum(e<=0.25 for e in errors)/len(errors)},n=len(errors))
        put("C12",dict(revisions),n=sum(revisions.values()))
        if driver_counts:
            total_driver_records=sum(bool(r.get('completed')) and bool(r.get('drivers')) for r in estimates)
            put("C13",{name:{"count":count,"share_percent":100*count/total_driver_records}
                       for name,count in sorted(driver_counts.items(),key=lambda item:(-item[1],item[0]))},
                n=sum(bool(r.get('completed')) and bool(r.get('drivers')) for r in estimates))
    benefit=data.get("benefit_inputs",{})
    required_benefit=('approved_by','approved_at','evidence_refs','scope','period_start','period_end')
    missing_benefit=[k for k in required_benefit if not benefit.get(k)]
    metrics['C14']['reason']='Missing benefit inputs: '+', '.join(missing_benefit+[k for k in ('case_baselines','automation_authoring_hours','maintenance_hours') if benefit.get(k) is None])
    metrics['C15']['reason']='Missing ROI inputs: '+', '.join(missing_benefit+[k for k in ('counterfactual_usd','actual_human_usd','actual_infra_usd') if benefit.get(k) is None])
    if not data.get('benefit_scope_matches'):metrics['C15']['reason']+='; comparable complete model cost for the same scope and period is unavailable'
    if benefit.get("approved_by") and benefit.get("approved_at") and benefit.get("evidence_refs"):
        eligible=data.get("benefit_executions")
        baselines={r.get("case_id"):r.get("manual_minutes") for r in benefit.get("case_baselines",[]) if r.get("evidence_ref")}
        if eligible is not None and all(baselines.get(c) is not None for c in eligible):
            avoided=sum(baselines[c] for c in eligible)/60
            effort=[benefit.get("automation_authoring_hours"),benefit.get("maintenance_hours")]
            put("C14",{"potential_hours":avoided,"net_hours":avoided-sum(effort) if all(e is not None for e in effort) else None},"hours",status="available" if all(e is not None for e in effort) else "partial")
        total=data.get("comparable_actual_model_usd")
        inputs=[benefit.get("counterfactual_usd"),benefit.get("actual_human_usd"),benefit.get("actual_infra_usd"),total]
        if all(v is not None and v>=0 for v in inputs) and data.get("benefit_scope_matches"):
            actual=sum(inputs[1:]);put("C15",100*(inputs[0]-actual)/actual if actual else None,"%",status="available" if actual else "not_applicable")
    return list(metrics.values())


def _has_factory_activity(s):
    """A session counts as factory work when `has_factory_activity` says so, or — for a file
    written before that field existed — when its own `by_activity` already shows a
    doctor/onboarding/story type (the same rule cost_capture.py itself uses to compute the
    field). `by_activity` missing entirely means no signal at all (not even the shape
    cost_capture.py has always written) — that keeps the old conservative default, True, so
    an in-flight story is never refused because an artifact lacks a field
    (test_has_factory_activity_false_excluded_from_every_metric pins exactly this for a
    session with no field and no by_activity at all). A session whose `by_activity` IS
    present but names no doctor/onboarding/story type — session 79152e1f, cwd
    merely inside the project — does not count just because `has_factory_activity` itself is
    absent. Mirrors factory_dashboard._has_factory_activity — kept as two small copies rather
    than a shared import so each dashboard/metrics module stays self-contained."""
    v = s.get('has_factory_activity')
    if v is not None:
        return bool(v)
    by_activity = s.get('by_activity')
    if not isinstance(by_activity, dict):
        return True
    return any(isinstance(a, dict) and a.get('type') in ('doctor', 'onboarding', 'story')
               for a in by_activity.values())


def project(root, tasks, bugs, sessions, journal, estimates, cfg, registry=None, health=None, write=True):
    """Adapt existing accepted artifacts, without making the renderer a new writer of facts.
    `write=False` computes and returns the same value and opens nothing for writing (a read-only
    render); the default keeps writing state/metrics.json."""
    root=Path(root); errors=[]
    # a session whose cwd merely sat inside the project (factory development, run
    # analysis) is not factory work; exclude it from every catalogue metric here. See
    # _has_factory_activity for what a missing field falls back to. The dashboard's own
    # Cost-tab summary cards keep the grand total for reconciliation — see
    # factory_dashboard.tab_cost, which filters separately and shows the excluded slice.
    sessions=[s for s in sessions if _has_factory_activity(s)]
    data={"obligations":[],"current_results":[],"automated_results":[],"attempts":[],"jobs":[],"dispatches":[],
          "projection_issues":[],"sessions":sessions,"bugs":[],"events":list(journal),
          "events_known":RP.record(root,'journal.jsonl').exists(),
          "estimates":[],"window_days":(cfg.get('metrics') or {}).get('window_days',30),
          "evidence_refs":[],"time_to_first_test":[]}
    data['severity_weights']=(cfg.get('metrics') or {}).get('severity_weights')
    data['bugginess_report_share']=(cfg.get('metrics') or {}).get('bugginess_report_share',.5)
    data['bugs_known']=(root/'qa-factory/bugs').exists()
    selected_identities=set();reuse_classified=set()
    scheduler_receipts=[]
    scheduler_dir=root/'qa-factory/state/scheduler-receipts'
    for receipt_path in sorted_paths(scheduler_dir.glob('*.json')) if scheduler_dir.exists() else []:
        receipt=read_json(receipt_path,errors)
        if isinstance(receipt,dict) and receipt.get('schema_version')==1:
            scheduler_receipts.append((receipt_path,receipt))
    for index,bug in enumerate(bugs):
        data['bugs'].append(dict(bug,id=bug.get('id') or f'unidentified-{index}',
                                created_at=bug.get('created_at') or bug.get('created')))
    bug_path=root/'qa-factory/state/bug-snapshot.json'
    snapshot=read_json(bug_path,errors)
    if snapshot:
        from bug_snapshot import validate
        try:
            validate(snapshot)
            combined={b['id']:b for b in data['bugs']}
            combined.update({b['id']:b for b in snapshot['bugs']})
            data['bugs']=list(combined.values());data['bugs_known']=True
            data['bug_scope']=snapshot['scope']
        except ValueError as exc:errors.append(str(bug_path)+': '+str(exc))
    if registry is not None:data['registry']=registry
    if health is not None:data['health']=health
    source_paths=set()
    # readiness.json is listed at both places (it moved into state/; an old-layout project has it beside the config)
    for relative in ('config.json','factory-backlog.md','state/factory-backlog.md',
                     'state/benefit-inputs.json','state/bug-snapshot.json','state/readiness.json','readiness.json'):
        candidate=root/'qa-factory'/relative
        if candidate.is_file():source_paths.add(candidate)
    for name in ('journal.jsonl','estimation-ledger.jsonl'):      # carried records: records/, or state/ before the move
        candidate=RP.record(root,name)
        if candidate.is_file():source_paths.add(candidate)
    for folder in (root/'qa-factory/bugs',root/'qa-factory/state/cost'):
        if folder.is_dir():source_paths.update(p for p in folder.rglob('*') if p.is_file() and p.suffix in {'.md','.json'})
    for task in tasks:
        path=Path(task['artifact_path']); active=not task.get('archived')
        source_paths.update(p for p in path.rglob('*') if p.is_file() and p.suffix in {'.json','.jsonl','.md'} and 'evidence' not in p.parts)
        plan=task.get('structured_plan') or {}
        plan_rows=plan.get('rows',[]) if isinstance(plan,dict) else []
        priorities={str(r.get('id')):r.get('priority') for r in plan_rows}
        pipeline=read_json(path/'pipeline.json',errors)
        approved=C.gate_approved(pipeline,'A')  # one reader of the gate field
        if plan_rows and active:data['plan_known']=True
        for ob in task.get('coverage',{}).get('obligations',[]):
            if active:data['obligations'].append(dict(ob,task=task['task'],scope=ob.get('execution_scope'),
                                                     priority=priorities.get(ob.get('plan_row')),approved=approved))
        report=task.get('report') or {}
        task_revision=report.get('source_revision')
        reused_ids=set()
        for receipt_path,receipt in scheduler_receipts:
            if not task_revision or receipt.get('source_revision')!=task_revision:continue
            for group in receipt.get('groups') or []:
                # `already_run` is the scheduler's word for a completed key that did not pass: a
                # result answered without a launch, which the same key was labelled `reused` for
                # before the run budget - it classifies (and reuses) exactly as `reused` does.
                if (isinstance(group,dict) and group.get('status') in {'reused','already_run'}
                        and group.get('task')==task['task'] and group.get('revision')==task_revision):
                    qualified=group.get('qualified_selected_ids')
                    if isinstance(qualified,list) and all(isinstance(value,str) and '::' in value for value in qualified):
                        reused_ids.update(qualified)
                        reuse_classified.update(f"{task['task']}::{value}" for value in qualified)
                        data['evidence_refs'].append(str(receipt_path))
                elif (isinstance(group,dict) and group.get('status') in {'completed','failed'}
                      and group.get('task')==task['task'] and group.get('revision')==task_revision):
                    qualified=group.get('qualified_selected_ids')
                    if isinstance(qualified,list) and all(isinstance(value,str) and '::' in value for value in qualified):
                        reuse_classified.update(f"{task['task']}::{value}" for value in qualified)
        if plan_rows and active and approved:
            manual_ids={str(c) for row in plan_rows for ob in row.get('coverage_obligations',[])
                        if ob.get('decision')=='manual-agent' for c in ob.get('planned_check_refs',[])}
            # Accepted evidence exporter is the authority, not a screenshot filename.
            exported=(task.get('manual_evidence') or {}).get('rows',[])
            validated={str(r.get('case')):r for r in exported if r.get('evidence_validated')}
            data.setdefault('manual_cases',[]).extend({'case':case,'evidence_complete':case in validated,
                'status':validated.get(case,{}).get('status','pending')} for case in sorted(manual_ids))
        if report and active:data['results_known']=True
        levels=task.get('case_levels') or {}
        manifest=task.get('manifest_entries',[])
        task_selected=set()
        for entry in manifest:
            instance_id=str(C.test_instance_id(entry) or '')
            repo_id=str(entry.get('repo_id') or entry.get('profile_id') or '') if isinstance(entry,dict) else ''
            if instance_id:task_selected.add(f'{repo_id}::{instance_id}')
        if active:selected_identities.update(f"{task['task']}::{value}" for value in task_selected)
        for row in report.get('current_results',[]):
            if active:
                repo_id=str(row.get('repo_id') or row.get('profile_id') or '')
                instance_id=str(row.get('instance_id') or row.get('test_instance_id') or row.get('test_id') or '')
                normalized=dict(row,level=row.get('level') or levels.get(row.get('case')),task=task['task'])
                if repo_id and instance_id and f'{repo_id}::{instance_id}' in reused_ids:
                    normalized['reused']=True
                data['current_results'].append(normalized)
                if f'{repo_id}::{instance_id}' in task_selected:
                    data['automated_results'].append(normalized)
        manifest_by_id={C.test_instance_id(r):r for r in manifest}
        if manifest and active:data['selected_automated']=data.get('selected_automated',0)+len(task_selected)
        state=task.get('lifecycle') or {}
        if state:
            data['controller_known']=True
            data['dispatches'].extend(dict(d,task=task['task']) for d in state.get('dispatches',{}).values())
        event_path=path/'state/events.jsonl'
        if event_path.exists():
            data['events_known']=True
            for line in event_path.read_text(encoding='utf-8').splitlines():
                if not line.strip():continue
                try:
                    event=json.loads(line)
                    # Explicit IDs prevent linked journal/controller double counting.
                    eid=event.get('id') or event.get('event_id')
                    if not eid or not any((e.get('id') or e.get('event_id'))==eid for e in data['events']):
                        event=dict(event,role=(state.get('dispatches',{}).get(event.get('payload',{}).get('id'),{}).get('role')))
                        data['events'].append(event)
                except ValueError:errors.append(str(event_path)+': corrupt event')
        if active and (task.get('projection_stale') or task.get('case_lifecycle_issues')):
            data['projection_issues'].append({'task':task['task'],'stale':task.get('projection_stale'),'issues':task.get('case_lifecycle_issues')})
        block_dir=path/'work/run-blocks'
        if block_dir.exists():data['attempt_history_known']=True
        starts=[]
        # dispatch.window is the controller's own S5-window number (coverage_contract.py's
        # witnessed_binding already trusts it for acceptance) — run-blocks carry only a
        # dispatch_id, so the window has to come from the matching dispatch record.
        dispatch_windows={k:v.get('window') for k,v in (state.get('dispatches') or {}).items() if isinstance(v,dict)}
        for bp in sorted_paths(block_dir.glob('*.json')):
            block=read_json(bp,errors)
            if not isinstance(block,dict):continue
            purpose=block.get('purpose') or (block.get('request') or {}).get('purpose')
            start=block.get('attempt_started_at');end=block.get('attempt_ended_at')
            imported=bool(block.get('import_provenance'))
            if not imported and purpose in {'initial','repair_verify','diagnostic','flaky_diagnostic'}:
                data['jobs'].append({'start':start,'end':end,'id':block.get('block_id'),
                    'window':dispatch_windows.get(block.get('dispatch_id'))})
                if timestamp(start):starts.append(timestamp(start))
            for row in block.get('results',[]):
                entry=manifest_by_id.get(str(row.get('instance_id') or row.get('test_instance_id')),{})
                cases=C.manifest_test_links(entry) if entry else []
                data['attempts'].append(dict(row,task=task['task'],started_at=start,purpose=purpose,
                    case=row.get('case') or (cases[0] if len(cases)==1 else None),
                    profile_id=row.get('profile_id') or block.get('profile_id'),
                    fingerprint=row.get('input_fingerprint') or block.get('input_fingerprint'),
                    origin='imported' if imported else 'executed'))
            data['evidence_refs'].append(str(bp))
        stages=pipeline.get('stages',{})
        s0=stages.get('S0',{}) if isinstance(stages,dict) else next((s for s in stages if s.get('id')=='S0'),{})
        beginning=timestamp(s0.get('started') or s0.get('started_at'))
        if starts and beginning and min(starts)>=beginning:data['time_to_first_test'].append((min(starts)-beginning).total_seconds())
    latest_estimates={}
    for index,record in enumerate(estimates):
        task=str(record.get('task') or f'__unidentified_{index}')
        candidate=(timestamp(record.get('ts') or record.get('updated_at') or record.get('created_at')) or datetime.min.replace(tzinfo=timezone.utc),index,record)
        if task not in latest_estimates or candidate[:2]>latest_estimates[task][:2]:latest_estimates[task]=candidate
    for _,_,record in latest_estimates.values():
        r=dict(record); task=r.get('task'); values=[s.get('by_task',{}).get(task) for s in sessions if task in s.get('by_task',{})]
        r['ts']=r.get('ts') or r.get('created_at')
        matching=next((t for t in tasks if t['task']==task),{})
        pipeline=read_json(Path(matching['artifact_path'])/'pipeline.json',errors) if matching else {}
        stages=pipeline.get('stages',{})
        s9=stages.get('S9',{}) if isinstance(stages,dict) else next((s for s in stages if s.get('id')=='S9'),{})
        r['completed']=s9.get('status')=='done'
        if any(row.get('schema_version')==1 and row.get('task')==task for row in estimates):
            from estimate_record import active_records,task_binding
            active_estimates=active_records(estimates,task)
            try:
                binding=task_binding(root,task)
                valid=len(active_estimates)==1 and active_estimates[0].get('record_id')==r.get('record_id') and r.get('retro_sha256')==binding['retro_sha256'] and r.get('task_revision')==binding['task_revision']
            except (OSError,ValueError):valid=False
            if not valid:r['completed']=False;r['exclusion_reason']='Estimate is not the unique current retro-bound revision'
        applicable=[s for s in sessions if task in s.get('by_task',{}) or any(q.get('task')==task for q in s.get('requests',[]))]
        request_capable=applicable and all(isinstance(s.get('requests'),list) for s in applicable)
        task_requests=[q for s in applicable for q in s.get('requests',[]) if q.get('task')==task]
        request_complete=request_capable and task_requests and all(s.get('usage_completeness')=='complete' for s in applicable) and all(
            (q.get('valuation') or {}).get('pricing_coverage')=='complete' for q in task_requests)
        legacy_complete=values and not request_capable and all(v.get('cost') is not None for v in values) and all(
            s.get('usage_status')=='actual' and s.get('pricing_coverage')=='complete' for s in applicable)
        if (request_complete or legacy_complete) and r['completed']:
                r['complete_cost']=(float(sum((Decimal(str((q.get('valuation') or {}).get('subtotal_usd','0')))
                                               for q in task_requests),Decimal('0'))) if request_complete
                                    else sum(v['cost'] for v in values))
        if r.get('complete_cost') is not None:
            size=(r.get('forecast') or {}).get('size_final') or (r.get('forecast') or {}).get('size_initial')
            if size in BANDS:
                lo,hi=BANDS[size]
                r['delta']=dict(r.get('delta') or {}, direction='below' if r['complete_cost']<lo else 'above' if r['complete_cost']>hi else 'within')
        data['estimates'].append(r)
    if selected_identities:
        data['reuse_classification_complete']=selected_identities.issubset(reuse_classified)
    benefit=read_json(root/'qa-factory/state/benefit-inputs.json',errors)
    if benefit:
        data['benefit_inputs']=benefit
        begin,end=timestamp(benefit.get('period_start')),timestamp(benefit.get('period_end'))
        scope=benefit.get('scope');task_set=set(scope.get('tasks',[])) if isinstance(scope,dict) else set()
        if begin and end and end>begin and task_set:
            eligible=[r for r in data['attempts'] if r['task'] in task_set and r.get('origin')=='executed'
                      and r.get('purpose')=='initial' and r.get('status') in {'pass','passed'}
                      and timestamp(r.get('started_at')) and begin<=timestamp(r['started_at'])<end]
            if all(r.get('case') for r in eligible):data['benefit_executions']=[r['case'] for r in eligible]
            applicable=[s for s in sessions if set(s.get('by_task',{})) & task_set or
                        any(r.get('task') in task_set for r in s.get('requests',[]))]
            request_rows=[r for s in applicable for r in s.get('requests',[]) if r.get('task') in task_set
                          and timestamp(r.get('timestamp')) and begin<=timestamp(r['timestamp'])<end]
            request_capable=applicable and all(isinstance(s.get('requests'),list) for s in applicable)
            complete=request_capable and all(s.get('usage_completeness')=='complete' for s in applicable) and all(
                (r.get('valuation') or {}).get('pricing_coverage')=='complete' for r in request_rows)
            if request_rows and complete:
                data['benefit_scope_matches']=True
                data['comparable_actual_model_usd']=float(sum((Decimal(str((r.get('valuation') or {}).get('subtotal_usd','0')))
                                                                for r in request_rows),Decimal('0')))
    mark_duplicate_executions(data['attempts'])
    now=datetime.now(timezone.utc)
    data['evidence_refs']=sorted(set(data['evidence_refs'])|{str(p) for p in source_paths})
    result={'schema_version':1,'generated_at':now.isoformat(),'as_of':now.isoformat(),
            'input_hash':content_hash(data),'source_manifest':[], 'metrics':compute(data,now),'errors':errors}
    result['estimates']=data['estimates']
    result['real_estimate_records']=bool(data['estimates'])
    for ref in sorted(set(data['evidence_refs'])):
        result['source_manifest'].append({'path':ref,'hash':hashlib.sha256(Path(ref).read_bytes()).hexdigest()})
    if errors:
        for m in result['metrics']:
            if m['status']=='available':m.update(status='partial',reason='Some input files could not be read; see projection errors')
    if write:atomic_json(root/'qa-factory/state/metrics.json',result)
    return result


def _display_value(value):
    if value is None:return '<span class="nd">Not recorded</span>'
    if isinstance(value,bool):return 'yes' if value else 'no'
    if isinstance(value,float):return f'{value:,.2f}'
    if isinstance(value,int):return f'{value:,}'
    if isinstance(value,dict):
        parts=[]
        for key,item in value.items():
            label=html.escape(str(key).replace('_',' '))
            if isinstance(item,(dict,list)):
                parts.append('<details><summary>'+label+' ('+str(len(item))+')</summary>'+_display_value(item)+'</details>')
            else:parts.append('<div><b>'+label+':</b> '+_display_value(item)+'</div>')
        return ''.join(parts) or '<span class="nd">No recorded items</span>'
    if isinstance(value,list):
        return '<ul>'+''.join('<li>'+_display_value(v)+'</li>' for v in value)+'</ul>' if value else '<span class="nd">No recorded items</span>'
    return html.escape(str(value))


def render(snapshot, prefixes):
    """The same catalogue powers descriptions and expanded formula text."""
    lookup={r["id"]:r for r in CATALOGUE}
    groups={"T":"Testing quality","A":"Automated-test quality","F":"Factory quality","C":"Cost and estimates"}
    source_names={'P':'accepted plan and coverage','R':'execution blocks and current results','B':'recorded bugs and status history','F':'findings and decisions registry','E':'controller and journal events','U':'recorded usage','X':'S9 estimates','H':'inspected test health',
                  'T1':'plan or gate change','T2':'execution, import, invalidation or triage','T3':'bug snapshot change','T4':'registry or readiness change','T5':'controller event','T6':'usage capture','T7':'S9 persistence'}
    out=[]
    for prefix in prefixes:
        rows=[]
        for m in snapshot["metrics"]:
            if not m["id"].startswith(prefix):continue
            meta=lookup[m["id"]]
            value=_display_value(m['value']) if m['value'] is not None else 'Unavailable' if m['status']=='unavailable' else 'No data'
            if isinstance(m['value'],(int,float)) and m['unit']!='count':value+=' '+html.escape(m['unit'])
            details={k:v for k,v in m.items() if k not in {'id','label','value','unit','numerator','denominator','status','reason','sample_size','evidence_refs','scope','formula_version','window_start','window_end'}}
            detail_html=('<details><summary>Breakdown and exclusions</summary>'+_display_value(details)+'</details>') if details else ''
            refs="".join('<li><a href="'+html.escape(Path(ref).as_uri(),quote=True)+'">'+html.escape(str(ref))+'</a></li>' for ref in m.get('evidence_refs',[])[:20])
            source_text=re.sub(r'\b(T[1-7]|[PBRFEUXH])\b',lambda match:source_names[match.group()],meta['source_update'])
            formula="<details class='formulas'><summary>Formulas</summary>"+"".join("<p>"+html.escape(str(text))+"</p>" for text in (meta['formula'],'Sources; updates: '+source_text,meta['missing']))+"<p>Reporting window (snapshot metrics use current state): "+html.escape(m['window_start'])+" to "+html.escape(m['window_end'])+"; formula v"+str(m['formula_version'])+"</p><ul>"+refs+"</ul></details>"
            rows.append("<tr id='"+m["id"]+"' data-metric='"+m["id"]+"'><td data-label='Metric'>"+html.escape(m["id"]+" "+m["label"])+"</td><td data-label='Value' style='overflow-wrap:anywhere;max-width:32em'>"+value+detail_html+"</td><td data-label='State'>"+html.escape(m["status"])+"<br>"+html.escape(m["reason"])+"</td><td data-label='Sample'>"+str(m["sample_size"])+"</td><td data-label='Definition'>"+formula+"</td></tr>")
        out.append("<section><h2>"+groups[prefix]+"</h2><p class='nd'>As of "+html.escape(snapshot["as_of"])+"; local recorded evidence only.</p><table class='metric-table'><tr><th>Metric</th><th>Value</th><th>State</th><th>n</th><th>Definition</th></tr>"+"".join(rows)+"</table></section>")
    return "".join(out)
