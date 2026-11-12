"""Disjoint request-based story/activity and daily totals, across sessions."""
import math
from collections import defaultdict
from decimal import Decimal

from activity_capture import FACTORY_TYPES

# The activity types a group is labelled by NAME ('Doctor', 'Collect'): every factory type except a story (labelled by its task) and
# the unclassified one. Read from the one set in activity_capture, so a new type there is a new label here (COLLECT, CL1-4).
NAMED_TYPES = FACTORY_TYPES - {'story', 'unclassified'}

TOKEN_FIELDS = ('input','output','cache_read','cache_write_5m','cache_write_1h')


NOT_LAUNCHED = ' - not launched by the driver'
CARRY_PREFIX = 'carry:'  # request_id of a row cost_capture.collapse_requests folded a ledger into
UNCLASSIFIED = 'unclassified'  # the activity id of work no activity owns


def _label(kind, task):
    """The By-task label of a row (or of an activity) of type `kind` carrying `task`: the task for a story,
    the type's name for a named factory type, else the task when it is one, else 'Unclassified'. The ONE
    place of the expression: the rows and the places of a role's gap are labelled by the same function."""
    return task if kind=='story' and task and task!='(no task)' else kind.title() if kind in NAMED_TYPES else task if task and task!='(no task)' and kind not in {'doctor','onboarding'} else 'Unclassified'


def blank_row(ok=True, cost=0.0):
    """An empty By-task row, the ONE builder of the shape (`group`'s `empty`, the rows of `task_groups` and the home
    of a gap whose label no row of the ledger holds all call it). `ok` is True for a row of `group` and None for a
    row `task_groups` builds from a price (its `ok` is set from the reconciliation later); `cost` is a Decimal where
    `group` sums money, a float otherwise."""
    return dict(session_ids=set(), sessions=0, tokens=0, cost=cost, priced=False, unpriced_tokens=0, ok=ok,
                active=0, timed=False, wait=None, composition={k: 0 for k in TOKEN_FIELDS},
                composition_complete=True, incomplete_agents=set(), provisional_sessions=set(), by_session={},
                untimed_sessions=set())


def session_machine_s(doc):
    """The machine time of ONE whole session in seconds (an int), or None when it cannot be told: the ONE reader of
    a session's time for a row that holds the session whole (a driver `claude -p` session opens no factory activity,
    so its rows have no activity time). It is the sum of the per-tag `by_task[*].machine_s` the capture wrote (gaps
    between requests, each capped at 120 s, like an activity's `active_s`); a tag with one request has no gap and
    reads 0 s (the capture's own rule). Error direction: it may say unknown, it never returns a figure built from
    part of the session (FR-41): a file with no `by_task`, an entry that is not a dict, an entry with no time and
    more than one request, a bool/str/negative/NaN/inf figure, and a file the capture rebuilt with stored rows put
    back (`recapture_carried`: its `machine_s` was not recomputed over the carried rows) are all None. Known bound:
    the per-tag figures add to the session's capped-gap time within 120 s per change of marker tag in the session."""
    if not isinstance(doc, dict) or doc.get('recapture_carried'):
        return None
    by_task = doc.get('by_task')
    if not isinstance(by_task, dict) or not by_task:
        return None
    total = 0
    for entry in by_task.values():
        if not isinstance(entry, dict):
            return None
        seconds = entry.get('machine_s')
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            if not math.isfinite(seconds) or seconds < 0:
                return None
            total += seconds
        elif seconds is None:
            requests = entry.get('requests')
            if not isinstance(requests, int) or isinstance(requests, bool) or not 0 <= requests <= 1:
                return None
        else:
            return None
    return int(round(total))


def _add_session_time(tasks, label, sid, session):
    """Count the time of the whole session `sid` ONCE under `label` (only when a row of it landed there):
    its machine time, or the session named untimed (never a partial figure as the whole)."""
    if label not in tasks or sid not in tasks[label]['session_ids']:
        return
    seconds = session_machine_s(session)
    if seconds is None:
        tasks[label]['untimed_sessions'].add(sid)
    else:
        tasks[label]['active'] += seconds
        tasks[label]['timed'] = True


def gap_places(doc):
    """Where each role named in `doc['incomplete_agents']` lost its usage: {name: {'streams': [...],
    'activities': [...]}}. ONE helper for a document of this version and of an older one (AR-15):
    (1) a journal gap names its own activities in `incomplete_where` (no rows exist for it);
    (2) else the files of `agents[]` of the same role (compared by `role_name`): a file whose stream
        has rows in `requests[]` is a stream (its rows are the place), a file without rows is the activity
        it ran in;
    (3) else (an older document: no field, no file) the story activity of the session when it has exactly
        one, otherwise every activity the document has.
    A name with nowhere to go lands in 'unclassified' (a gap is never dropped, FR-41). A field that is not
    a list, or a record without a name, is read as absent; activities that are not a list are 'unknown'."""
    from hooklib import role_name
    names = [n for n in doc.get('incomplete_agents') or [] if isinstance(n, str) and n] if isinstance(doc.get('incomplete_agents'), list) else []
    where = {}
    if isinstance(doc.get('incomplete_where'), list):
        for rec in doc['incomplete_where']:
            if isinstance(rec, dict) and isinstance(rec.get('agent'), str) and rec['agent'] and rec['agent'] not in where:
                acts = rec.get('activities')
                acts = [a for a in acts if isinstance(a, str) and a] if isinstance(acts, list) else []
                where[rec['agent']] = acts or [UNCLASSIFIED]
    requests = doc.get('requests')
    with_rows = {r.get('stream') for r in requests if isinstance(r, dict)} if isinstance(requests, list) else set()
    agents = [a for a in doc.get('agents') or [] if isinstance(a, dict)] if isinstance(doc.get('agents'), list) else []
    by_activity = doc.get('by_activity') if isinstance(doc.get('by_activity'), dict) else {}
    out = {}
    for name in dict.fromkeys(names):
        if name in where:
            out[name] = {'streams': [], 'activities': list(dict.fromkeys(where[name]))}
            continue
        role = role_name(name)
        files = [a for a in agents if role and role_name(a.get('agent') or '') == role]
        if files:
            streams = [f['file'] for f in files if isinstance(f.get('file'), str) and f['file'] in with_rows]
            acts = [f.get('activity_id') for f in files
                    if not (isinstance(f.get('file'), str) and f['file'] in with_rows)]
            acts = [a if isinstance(a, str) and a else UNCLASSIFIED for a in acts]
        else:
            stories = [aid for aid, a in by_activity.items() if isinstance(a, dict) and a.get('type') == 'story']
            streams, acts = [], (stories if len(stories) == 1 else list(by_activity))
        out[name] = {'streams': list(dict.fromkeys(streams)), 'activities': list(dict.fromkeys(acts))}
        if not out[name]['streams'] and not out[name]['activities']:
            out[name]['activities'] = [UNCLASSIFIED]
    return out


def attach_rowless_gaps(by_task, sessions, holders, priced=(), task_of=None):
    """Put, ONCE per document, the roles whose gap has no request rows (`gap_places` activities) on one row
    of `by_task` per candidate activity: the row of a part that holds that activity's rows (`holders`:
    (session id, activity id) -> the final labels of the parts holding rows of it, the first one wins, so an
    activity split between a price part and the rest takes ONE label); none holds it: the price row of the
    story the activity belongs to (a task in `priced`, or the driver's binding), else 'Unclassified'. The
    caller counted the parts with `group(..., rowless_gaps=False)`; a name is on a row exactly once per
    candidate and never on none (FR-41). `sessions` are the WHOLE documents, not slices."""
    bound_tasks = task_of if isinstance(task_of, dict) else {}
    done = set()
    for session in sessions:
        sid = session.get('session_id')
        if not isinstance(sid, str) or not sid or sid in done or not isinstance(session.get('requests'), list):
            continue
        done.add(sid)
        if not session.get('incomplete_agents'):
            continue
        activities = session.get('by_activity') if isinstance(session.get('by_activity'), dict) else {}
        bound = bound_tasks.get(sid)
        for name, place in gap_places(session).items():
            labels = []
            for aid in place['activities']:
                held = (holders or {}).get((sid, aid)) or []
                if held:
                    label = held[0]
                else:
                    activity = activities.get(aid) if aid != UNCLASSIFIED else None
                    task = bound if isinstance(bound, str) and bound else (
                        activity.get('task') if isinstance(activity, dict) and activity.get('type') == 'story' else None)
                    label = task if isinstance(task, str) and task in priced else 'Unclassified'
                if label not in labels:
                    labels.append(label)
            for label in labels:
                by_task.setdefault(label, blank_row())['incomplete_agents'].add(name)


def group(sessions, task_of=None, stray_apart=True, rowless_gaps=True, held=None, whole_time=None):
    """Disjoint request-based story/activity and daily totals, across sessions.

    `task_of` (session id -> task) is the driver journal's binding: a session it names belongs
    WHOLE to that task, whatever its requests are tagged (a driver `claude -p` session opens no
    factory activity, so the capture collapses it into one "(no task)" row and the story read
    "Unclassified"). Position invariant: the binding replaces the label of EVERY row of a bound
    session, before any other rule and instead of it, so a bound session never reaches
    'Unclassified' or any other label; a session without a binding is labelled by exactly the
    code path it always had. Only a session id the cost file itself carries can be bound (never the
    `legacy-<i>` stand-in). `task_of` None or {} is the old behaviour, byte for byte.

    `stray_apart` (default view): a session that has NO binding but whose own label is a task
    some journal names is not that story's work as far as the journal knows (FR-24), so it is
    shown under "<task> - not launched by the driver". The per-task view keeps the tag.

    Each label's value also carries `by_session`: session id -> {composition, whole_session,
    partial_ledger}, the tokens by cache class of the requests of THAT session counted under THAT
    label (B-195), so a session that touched several labels is judged per pair, not whole under
    each. A session with no request ledger, or with a collapsed one (its `carry:` rows), has no
    per-label split to take: its WHOLE-session composition stands under every label it lands in
    (`whole_session` True). A ledger that is only PARTLY collapsed (some `carry:` rows among real
    ones) is treated the same way and flagged `partial_ledger`, so the two rules are never mixed
    inside one session. The return stays two values.

    A role named in `incomplete_agents` lands where its gap is (`gap_places`), not on every label of the
    session: on the rows of its own streams; a gap with no request rows (a dispatch that left no
    transcript) on the label of the activity it ran in, when `rowless_gaps` (the default view). A caller
    that splits one document into parts (`factory_dashboard.task_groups`) passes `rowless_gaps=False`
    and attaches those gaps once per document with `attach_rowless_gaps`; `held`, a dict it passes in,
    is filled with (session id, activity id) -> the labels this call put rows of it on.

    `whole_time` (session ids; None or empty = today's behaviour, byte for byte): a BOUND session whose id is in
    it is timed as a whole: its activities' `active_s` are not added, its `session_machine_s` is added once to
    its label, and a session whose time cannot be told is named in that row's `untimed_sessions` (a partial
    figure is never the whole, FR-41). A session outside `whole_time` is timed by the code path it always had;
    a session's time enters one label, once (never activity time AND session time)."""
    bound_tasks = task_of if isinstance(task_of, dict) else {}
    journaled = {t for t in bound_tasks.values() if isinstance(t, str) and t} if stray_apart else set()

    def empty():
        # `provisional_sessions`: which sessions of this task still carry provisional usage (a task whose cost cannot
        # be reconciled is a finding about the factory's own capture, and it has to name how many are still open);
        # `by_session`: the pair (this label, session), see group()'s docstring.
        return blank_row(cost=Decimal('0'))

    def whole_composition(session):
        return {k: sum((v.get(k, 0) or 0) for v in (session.get('by_model') or {}).values())
                for k in TOKEN_FIELDS}
    tasks, days = defaultdict(empty), defaultdict(empty)
    seen=set()
    for i, session in enumerate(sessions):
        sid=session.get('session_id') or f'legacy-{i}'
        real_sid=session.get('session_id')
        bound=bound_tasks.get(real_sid) if isinstance(real_sid,str) and real_sid else None
        if not (isinstance(bound,str) and bound): bound=None
        timed_whole=bool(whole_time) and bound is not None and real_sid in whole_time
        activities=session.get('by_activity') or {}
        requests=session.get('requests')
        # When a role's usage never made it into the session, the
        # session names it here rather than silently rolling an incomplete sum into a task.
        incomplete_agents=set(session.get('incomplete_agents') or [])
        activity_labels={}
        stream_labels={}

        def gap_label(aid):
            """The label an activity of this session has (the rows' own rule), for a gap with no rows."""
            if bound is not None: return bound
            activity=activities.get(aid) if aid!=UNCLASSIFIED else None
            label=_label(activity.get('type'),activity.get('task')) if isinstance(activity,dict) else 'Unclassified'
            return label+NOT_LAUNCHED if label in journaled else label
        if isinstance(requests,list):
            # `carry:` rows are what cost_capture.collapse_requests leaves: one row per stream and
            # model, no per-request split. Any of them makes the session whole-session (see above).
            carried=sum(1 for r in requests if isinstance(r,dict) and str(r.get('request_id') or '').startswith(CARRY_PREFIX))
            whole_session=carried>0
            partial_ledger=0<carried<len(requests)
            whole=whole_composition(session) if whole_session else None
            for j,row in enumerate(requests):
                identity=row.get('request_key') or (sid,j)
                if identity in seen: continue
                seen.add(identity)
                activity=activities.get(row.get('activity_id'), {})
                kind=activity.get('type')
                task=row.get('task')
                if bound is not None:
                    label=bound
                else:
                    label=_label(kind,task)
                    if label in journaled: label+=NOT_LAUNCHED
                activity_labels[row.get('activity_id')]=label
                stream_labels.setdefault(row.get('stream'),set()).add(label)
                if held is not None:
                    seen_labels=held.setdefault((sid,row.get('activity_id')),[])
                    if label not in seen_labels: seen_labels.append(label)
                usage=row.get('usage') or {}
                tokens=sum(usage.get(k,0) or 0 for k in TOKEN_FIELDS)
                valuation=row.get('valuation') or {}
                pair=tasks[label]['by_session'].setdefault(sid,dict(
                    composition=dict(whole) if whole_session else {k: 0 for k in TOKEN_FIELDS},
                    whole_session=whole_session,partial_ledger=partial_ledger))
                if not whole_session:
                    for k in TOKEN_FIELDS: pair['composition'][k]+=usage.get(k,0) or 0
                for target in (tasks[label],days[str(row.get('timestamp') or 'unknown')[:10]]):
                    target['session_ids'].add(sid)
                    target['tokens']+=tokens
                    for k in TOKEN_FIELDS: target['composition'][k]+=usage.get(k,0) or 0
                    if valuation.get('pricing_coverage') in {'partial','complete'}:
                        target['cost']+=Decimal(str(valuation.get('subtotal_usd','0')))
                        target['priced']=True
                    if valuation.get('pricing_coverage')!='complete':target['unpriced_tokens']+=tokens
                    if session.get('usage_completeness')!='complete':target['provisional_sessions'].add(sid)
                    if session.get('usage_completeness')!='complete' or valuation.get('pricing_coverage')!='complete':target['ok']=None
                    if (session.get('reconciliation') or {}).get('match') is False:target['ok']=False
            if timed_whole:
                _add_session_time(tasks,bound,sid,session)
            else:
                for aid,label in activity_labels.items():
                    duration=(activities.get(aid) or {}).get('active_s')
                    if duration is not None:
                        tasks[label]['active']+=duration;tasks[label]['timed']=True
            if incomplete_agents:
                places=gap_places(session)
                session_labels=set(activity_labels.values())
                for name in incomplete_agents:
                    place=places.get(name) or {'streams':[],'activities':[UNCLASSIFIED]}
                    labels=set()
                    for stream in place['streams']: labels|=stream_labels.get(stream,set())
                    # a stream named with no row of its own left here (a ledger folded to `carry:` rows):
                    # the labels of the whole session, as they always were
                    if place['streams'] and not labels: labels|=session_labels
                    if rowless_gaps: labels|={gap_label(aid) for aid in place['activities']}
                    for label in labels: tasks[label]['incomplete_agents'].add(name)
        else:
            fallback={'(no task)':{'tokens':sum(sum(v.get(k,0) or 0 for k in TOKEN_FIELDS) for v in (session.get('by_model') or {}).values()),'cost':session.get('priced_subtotal_usd',session.get('total_cost_usd'))}}
            by_task_map=session.get('by_task') or fallback
            # Legacy whole-session rows carry no per-task token-category split; attribute the
            # session's own composition only when it touched exactly one task, otherwise mark
            # the touched tasks' composition incomplete rather than guess a split.
            session_composition={k:sum(v.get(k,0) or 0 for v in (session.get('by_model') or {}).values()) for k in TOKEN_FIELDS}
            # A bound session lands under ONE label whatever its by_task holds, so its composition
            # is that label's own, added once (never once per by_task entry, never marked incomplete).
            single=len(by_task_map)==1 or bound is not None
            composed=False
            task_labels={}
            for task,row in by_task_map.items():
                if bound is not None:
                    label=bound
                else:
                    label='Unclassified' if task=='(no task)' else task
                    if label in journaled: label+=NOT_LAUNCHED
                target=tasks[label]
                target['by_session'].setdefault(sid,dict(composition=dict(session_composition),
                                                         whole_session=True,partial_ledger=False))
                target['session_ids'].add(sid); target['tokens']+=row.get('tokens') or 0
                if row.get('cost') is not None:
                    target['cost']+=Decimal(str(row['cost']));target['priced']=True
                else:target['unpriced_tokens']+=row.get('tokens') or 0
                target['ok']=None
                if session.get('usage_completeness')!='complete':target['provisional_sessions'].add(sid)
                if row.get('machine_s') is not None and not timed_whole:
                    target['active']+=row['machine_s'];target['timed']=True
                if single:
                    if not composed:
                        for k in TOKEN_FIELDS: target['composition'][k]+=session_composition[k]
                        composed=True
                else:
                    target['composition_complete']=False
                task_labels[task]=label
            if timed_whole:
                _add_session_time(tasks,bound,sid,session)
            # No request rows: a role lands on the label of the task its own file carries; no such
            # label (no file, or its task is not one of this session's) - every label of the session,
            # which is what a session with no finer record has always done.
            if incomplete_agents:
                from hooklib import role_name
                every=set(task_labels.values())
                for name in incomplete_agents:
                    mine={task_labels[a.get('task')] for a in session.get('agents') or []
                          if isinstance(a,dict) and role_name(a.get('agent') or '')==role_name(name) and role_name(name)
                          and a.get('task') in task_labels}
                    for label in (mine or every): tasks[label]['incomplete_agents'].add(name)
    for rows in (tasks,days):
        for value in rows.values():
            value['sessions']=len(value['session_ids']);value['cost']=float(value['cost'])
    return tasks,days


def by_agent(sessions):
    """Disjoint request-based agent totals — the SAME universe of dollars `group()` sums for
    "By task", just bucketed by agent instead of task/activity. Built from `requests[]`
    exactly like `group()`, not from the per-stream `orchestrator.cost` / `agents[].cost`
    aggregate fields: those go null the instant ONE model in that one stream is unpriced
    (`total_cost()`'s all-or-nothing rule), which silently dropped an entire dispatch's
    otherwise-known partial dollars from "By agent" while "By task" — built from individual
    request valuations — kept them. That was why the two tables disagreed even after both
    were filtered to factory-only sessions: same money, two different completeness
    rules. A session with no `requests[]` (pre-request-ledger format) falls back to the
    aggregate fields, same as before."""
    def empty():
        return dict(session_ids=set(), cost=Decimal('0'), priced=False, tokens=0,
                    unpriced_tokens=0, dispatch_turns={}, calls=set())
    agents = defaultdict(empty)
    seen = set()
    for i, session in enumerate(sessions):
        sid = session.get('session_id') or f'legacy-{i}'
        requests = session.get('requests')
        file_to_agent = {a.get('file'): a.get('agent', '?')
                         for a in session.get('agents') or [] if isinstance(a, dict) and a.get('file')}
        if isinstance(requests, list):
            for j, row in enumerate(requests):
                identity = row.get('request_key') or (sid, j)
                if identity in seen:
                    continue
                seen.add(identity)
                stream = row.get('stream') or 'orchestrator'
                label = stream if stream == 'orchestrator' else file_to_agent.get(stream, stream)
                target = agents[label]
                target['session_ids'].add(sid)
                target['calls'].add((sid, stream))
                usage = row.get('usage') or {}
                tokens = sum(usage.get(k, 0) or 0 for k in TOKEN_FIELDS)
                target['tokens'] += tokens
                valuation = row.get('valuation') or {}
                if valuation.get('pricing_coverage') in {'partial', 'complete'}:
                    target['cost'] += Decimal(str(valuation.get('subtotal_usd', '0')))
                    target['priced'] = True
                if valuation.get('pricing_coverage') != 'complete':
                    target['unpriced_tokens'] += tokens
                dt = target['dispatch_turns']
                dt[(sid, stream)] = dt.get((sid, stream), 0) + 1
        else:
            # Legacy whole-session shape (no request ledger): the old aggregate-field
            # approach is the best available — nothing finer-grained was ever recorded.
            oc = (session.get('orchestrator') or {}).get('cost')
            orch_reqs = sum(v.get('requests', 0) for v in (session.get('orchestrator') or {}).get('by_model', {}).values())
            target = agents['orchestrator']
            target['session_ids'].add(sid)
            target['calls'].add((sid, 'orchestrator'))
            target['dispatch_turns'][(sid, 'orchestrator')] = orch_reqs
            if oc is not None:
                target['cost'] += Decimal(str(oc))
                target['priced'] = True
            for a in session.get('agents') or []:
                label = a.get('agent', '?')
                target = agents[label]
                key = (sid, a.get('file') or label)
                target['session_ids'].add(sid)
                target['calls'].add(key)
                target['tokens'] += a.get('tokens') or 0
                target['dispatch_turns'][key] = sum(v.get('requests', 0) for v in (a.get('by_model') or {}).values())
                if a.get('cost') is not None:
                    target['cost'] += Decimal(str(a['cost']))
                    target['priced'] = True
    for value in agents.values():
        value['sessions'] = len(value['session_ids'])
        value['calls'] = len(value['calls'])
        turns = list(value['dispatch_turns'].values())
        value['turns'] = sum(turns)
        value['max_turns'] = max(turns) if turns else 0
        value.pop('dispatch_turns', None)
        value.pop('session_ids', None)
        value['cost'] = float(value['cost'])
    return dict(agents)
