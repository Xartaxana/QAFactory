"""Event-driven metric history and explicit, versioned signal policy. No timer."""
from datetime import datetime, timezone
from pathlib import Path
import json
from event_store import atomic_json, content_hash
from metrics_projection import timestamp
from dashboard_cost_groups import group as group_cost, TOKEN_FIELDS

# a ten-request session should not raise a cache alarm; ignore anything this small.
MIN_HOT_CACHE_TOKENS = 200_000
DEFAULT_HOT_CACHE_MIN_PERCENT = 90
CACHE_DENOM_FIELDS = ('cache_read', 'cache_write_5m', 'cache_write_1h', 'input')


def hot_cache_share(composition):
    """Percent of the requests that could have ridden a warm prefix that actually did:
    cache_read / (cache_read + cache_write_5m + cache_write_1h + input). output is excluded,
    it is never served from cache. None when there is nothing to take a share of."""
    denom = sum(composition.get(k, 0) or 0 for k in CACHE_DENOM_FIELDS)
    if not denom:
        return None
    return 100 * (composition.get('cache_read', 0) or 0) / denom


def number(metric, field=None):
    value = metric.get('value')
    for part in (field or '').split('.'):
        if part:
            value = value.get(part) if isinstance(value, dict) else None
    return value if type(value) in (int, float) else None


def evaluate(snapshot, history, previous, policy):
    """Pure transition function. Missing observations never resolve an alert."""
    metrics = {m['id']: m for m in snapshot['metrics']}
    old = {s['id']: s for s in previous.get('signals', [])}
    signals, evaluations = [], []
    rules = policy.get('rules', [])
    if rules and not policy.get('version'):
        raise ValueError('metrics.signal_policy requires an explicit version')
    for rule in rules:
        required = ('id', 'metric', 'direction', 'threshold', 'recovery_threshold', 'min_sample', 'recovery_samples', 'mode')
        if any(k not in rule for k in required) or rule['direction'] not in ('above', 'below') or rule['mode'] not in ('absolute', 'trend'):
            raise ValueError('Incomplete metric signal rule: ' + str(rule.get('id')))
        if rule['recovery_samples'] < 1 or rule['min_sample'] < 1:
            raise ValueError('Signal sample requirements must be positive')
        above = rule['direction'] == 'above'
        if (above and rule['recovery_threshold'] > rule['threshold']) or (not above and rule['recovery_threshold'] < rule['threshold']):
            raise ValueError('Recovery threshold must be on the healthy side of the trigger')
        sid = str(policy['version']) + ':' + rule['id']
        metric = metrics.get(rule['metric'], {})
        value = number(metric, rule.get('field'))
        baseline = None
        reason = ''
        if metric.get('status') != 'available' or value is None or metric.get('sample_size', 0) < rule['min_sample']:
            reason = 'Metric unavailable, incomplete or below minimum sample'
        if not reason and rule['mode'] == 'trend':
            # Compare complete non-overlapping cohorts, never two almost-identical rolling windows.
            candidates = [m for item in history for m in item.get('metrics', [])
                          if m['id'] == metric['id'] and m.get('status') == 'available'
                          and m.get('scope') == metric.get('scope') and m.get('formula_version') == metric.get('formula_version')
                          and m.get('sample_size', 0) >= rule['min_sample']
                          and timestamp(m.get('window_end')) and timestamp(metric.get('window_start'))
                          and timestamp(m['window_end']) <= timestamp(metric['window_start'])
                          and timestamp(m.get('window_start'))
                          and abs((timestamp(m['window_end'])-timestamp(m['window_start'])).total_seconds()
                                  -(timestamp(metric['window_end'])-timestamp(metric['window_start'])).total_seconds()) < 86400]
            baseline = candidates[-1] if candidates else None
            if baseline is None or number(baseline, rule.get('field')) is None:
                reason = 'No complete, comparable non-overlapping baseline window'
        observation = value - number(baseline, rule.get('field')) if baseline and not reason else value
        prior = old.get(sid)
        if reason:
            evaluations.append({'id': sid, 'status': 'not_evaluated', 'reason': reason})
            if prior:
                signals.append(dict(prior, evaluation='not_evaluated', reason=reason))
            continue
        breach = observation >= rule['threshold'] if above else observation <= rule['threshold']
        recovered = observation <= rule['recovery_threshold'] if above else observation >= rule['recovery_threshold']
        evaluations.append({'id': sid, 'status': 'evaluated', 'value': observation})
        if not breach and not prior:
            continue
        signal = dict(prior or {}, id=sid, rule_version=policy['version'], metric=metric['id'],
                      scope=metric.get('scope'), severity=rule.get('severity', 'warning'),
                      title=rule.get('title', metric['label']), current=value,
                      baseline=number(baseline, rule.get('field')) if baseline else None,
                      sample_size=metric['sample_size'], baseline_sample=baseline.get('sample_size') if baseline else None,
                      window_start=metric['window_start'], window_end=metric['window_end'],
                      threshold=rule['threshold'], direction=rule['direction'], mode=rule['mode'],
                      evidence_refs=metric.get('evidence_refs', []), source_revision=snapshot['input_hash'],
                      owner=rule.get('owner', 'orchestrator'), next_action=rule.get('next_action', 'Review the evidence'),
                      evaluation='evaluated', evaluated_at=snapshot['as_of'], reason='')
        signal['observation_revision'] = content_hash([value, metric['sample_size'], metric['window_start'], metric.get('formula_version'), signal['baseline'], signal['baseline_sample']])
        fresh = not prior or prior.get('observation_revision') != signal['observation_revision']
        if breach:
            acknowledged = prior and prior.get('acknowledged_at') and prior.get('status') == 'verifying'
            worsening = prior and (value > prior.get('current', value) if above else value < prior.get('current', value))
            signal.update(status='verifying' if acknowledged and not worsening else 'active', recovery_count=0)
        elif prior and prior.get('status') != 'resolved':
            count = prior.get('recovery_count', 0) + (1 if recovered and fresh else 0)
            if not recovered:
                count = 0
            signal.update(status='resolved' if count >= rule['recovery_samples'] else 'verifying', recovery_count=count)
        signal.setdefault('first_seen', snapshot['as_of'])
        if fresh and (not prior or prior.get('status') != signal.get('status') or prior.get('current') != value):
            signal['changed_at'] = snapshot['as_of']
        signals.append(signal)
    # Changing a policy cannot silently erase an outstanding warning.
    known = {s['id'] for s in signals} | {e['id'] for e in evaluations}
    signals.extend(dict(s, evaluation='not_evaluated', reason='Rule retired or policy version changed')
                   for sid, s in old.items() if sid not in known and s.get('status') != 'resolved')
    return {'schema_version': 1, 'evaluated_at': snapshot['as_of'], 'source_revision': snapshot['input_hash'],
            'policy_version': policy.get('version'), 'signals': signals, 'evaluations': evaluations,
            'status': 'evaluated' if rules else 'no_configured_rules'}


def _hot_cache_signals(snapshot, previous, sessions, cfg, task_of=None):
    """Built-in rule, in the same terms as legacy-estimate-v1: a synthetic per-scope metric
    fed through the same evaluate()/lifecycle machinery, so the warning surfaces through the
    shared signals_html banner rather than a separate ad-hoc branch. ONE signal per task label
    (story or non-story) as group_cost groups it, listing the label's cold sessions, so a story
    with many cold sessions is one warning, not one per session. Its value is the LOWEST share
    among the label's own share and each of its sessions — a story average alone would let one
    cold session hide in it. `task_of` is the driver journal's session -> task binding, the same
    one every other section groups by (dashboard_cost_groups.group): a session the journal names
    is listed under its journal's task, not under "Unclassified". A session that touched several
    labels is judged under each by that pair's own requests (B-195); the token minimum applies to
    the pair. An old `story-Unclassified` signal whose sessions all moved to a task is resolved
    here (`_resolve_moved_unclassified`)."""
    threshold = float((cfg.get('metrics') or {}).get('hot_cache_min_percent', DEFAULT_HOT_CACHE_MIN_PERCENT))
    signals, evaluations = [], []

    def evaluate_label(label, v):
        composition = v.get('composition') or {}
        label_tokens = sum(composition.get(k, 0) or 0 for k in TOKEN_FIELDS)
        # An incomplete composition (legacy rows split over several tasks) is not a share to trust.
        own = hot_cache_share(composition) if v.get('composition_complete', True) else None
        qualifying, eligible, partial = [], 0, []
        for sid in sorted(v.get('session_ids') or ()):
            # B-195: a session is judged under this label by the requests it has under THIS label
            # (its pair), and the token minimum applies to the pair. A session with no request
            # ledger carries its whole composition (group() says so in `whole_session`).
            pair = (v.get('by_session') or {}).get(sid)
            if pair is None:
                continue
            comp = pair.get('composition') or {}
            tokens = sum(comp.get(k, 0) or 0 for k in TOKEN_FIELDS)
            if tokens < MIN_HOT_CACHE_TOKENS:
                continue
            eligible += 1
            if pair.get('partial_ledger'):
                partial.append(sid)
            share = hot_cache_share(comp)
            if share is not None:
                qualifying.append((share, tokens, sid))
        candidates = [q[0] for q in qualifying]
        if own is not None and label_tokens >= MIN_HOT_CACHE_TOKENS:
            candidates.append(own)
        value = min(candidates) if candidates else None
        # <= like evaluate()'s own breach test, so a session sitting exactly on the threshold is listed.
        cold = sorted((q for q in qualifying if q[0] <= threshold), key=lambda q: (q[0], q[2]))
        listed = [{'session_id': sid, 'share': round(share, 1), 'tokens': tokens} for share, tokens, sid in cold]
        title = f'Hot cache share below {threshold:g}% - {label}'
        if listed:
            title += f': {len(listed)} of {eligible} sessions'
        metric = {'id': 'C-hot-cache', 'label': 'Hot cache share', 'value': value,
                  'status': 'available' if value is not None else 'unavailable',
                  # A legacy by_task row can carry tokens=None while its session is large; the sample
                  # must never be smaller than a candidate that qualified (or than the label's composition).
                  'sample_size': max(v.get('tokens') or 0, label_tokens, max((q[1] for q in qualifying), default=0)),
                  'scope': f'story {label}',
                  'window_start': snapshot['as_of'], 'window_end': snapshot['as_of']}
        rid = 'story-' + label
        # min_sample 1: the MIN_HOT_CACHE_TOKENS gate is applied above, per candidate, because a
        # qualifying session can be larger than its label's own token count.
        rule = {'id': rid, 'metric': 'C-hot-cache', 'direction': 'below', 'threshold': threshold,
                'recovery_threshold': threshold, 'min_sample': 1, 'recovery_samples': 1,
                'mode': 'absolute', 'title': title,
                'next_action': 'Review state/cost for this story: confirm prompt prefixes stay '
                               'stable so more of the context is served warm (cache_read) instead of rewritten (cache_write).'}
        # `current` is stored rounded for display; evaluate() must compare against the exact value
        # (a rounded-up prior would read as "worsening" and knock an acknowledged signal back to active).
        prior = [dict(s, current=s['current_raw']) if 'current_raw' in s else s
                 for s in previous.get('signals', []) if s['id'] == 'hot-cache-v1:' + rid]
        part = evaluate(dict(snapshot, metrics=[metric]), [], {'signals': prior},
                        {'version': 'hot-cache-v1', 'rules': [rule]})
        for sig in part['signals']:
            raw = sig.get('current')
            if type(raw) in (int, float):
                sig['current_raw'] = raw
                sig['current'] = round(raw, 1)
            if sig.get('evaluation') == 'evaluated':
                sig['sessions'] = listed
                sig['scope_share'] = round(own, 1) if own is not None else None
                # Never mix the two rules inside one session: say which ones were judged whole.
                if partial:
                    sig['note'] = ('Judged on the whole session, not on this label\'s own requests '
                                   '(the session\'s request ledger is only partly collapsed): '
                                   + ', '.join(partial))
                else:
                    sig.pop('note', None)
        signals.extend(part['signals']); evaluations.extend(part['evaluations'])

    tasks, _ = group_cost(sessions, task_of)
    for label, v in tasks.items():
        evaluate_label(label, v)
    _resolve_moved_unclassified(signals, previous, tasks, sessions, snapshot)
    return signals, evaluations


UNCLASSIFIED_SIGNAL = 'hot-cache-v1:story-Unclassified'


def _pair_evaluated(pair):
    """True when a (label, session) pair was actually judged: it reaches the token minimum and
    has a share to take."""
    comp = (pair or {}).get('composition') or {}
    return (sum(comp.get(k, 0) or 0 for k in TOKEN_FIELDS) >= MIN_HOT_CACHE_TOKENS
            and hot_cache_share(comp) is not None)


def _moved_to(prior, tasks, sessions):
    """The labels the sessions an old `story-Unclassified` signal lists have moved to, sorted; None
    unless EVERY listed session moved. Allowed error: not resolving (the signal stays as it was);
    forbidden: resolving over a session nobody observed. So a listed session counts only when it
    has a cost file in THIS refresh (a real `session_id`, never a `legacy-<i>` stand-in), no
    longer appears under Unclassified, and its pair under a new label was evaluated; a session
    that is only bound to a task in the journal but has no cost file is a missing observation."""
    listed = prior.get('sessions')
    if not isinstance(listed, list) or not listed:
        return None
    present = {s['session_id'] for s in sessions
               if isinstance(s, dict) and isinstance(s.get('session_id'), str) and s['session_id']}
    still = (tasks.get('Unclassified') or {}).get('session_ids') or ()
    moved = set()
    for entry in listed:
        sid = entry.get('session_id') if isinstance(entry, dict) else None
        if not isinstance(sid, str) or sid not in present or sid in still:
            return None
        labels = [label for label, v in tasks.items()
                  if label != 'Unclassified' and sid in (v.get('session_ids') or ())
                  and _pair_evaluated((v.get('by_session') or {}).get(sid))]
        if not labels:
            return None
        moved.update(labels)
    return sorted(moved)


def _resolve_moved_unclassified(signals, previous, tasks, sessions, snapshot):
    """R16: an old `hot-cache-v1:story-Unclassified` signal whose sessions have all moved to a task
    is RESOLVED with the reason "sessions moved to <tasks>". When the Unclassified label is itself
    evaluated this refresh (other sessions still sit under it), its own lifecycle governs and this
    does nothing. A signal it cannot resolve is left exactly as it was."""
    if any(s['id'] == UNCLASSIFIED_SIGNAL and s.get('evaluation') == 'evaluated' for s in signals):
        return
    for prior in previous.get('signals', []):
        if prior.get('id') != UNCLASSIFIED_SIGNAL or prior.get('status') == 'resolved':
            continue
        moved = _moved_to(prior, tasks, sessions)
        if not moved:
            continue
        signals[:] = [s for s in signals if s['id'] != UNCLASSIFIED_SIGNAL]
        signals.append(dict(prior, status='resolved', evaluation='evaluated',
                            reason='sessions moved to ' + ', '.join(moved),
                            evaluated_at=snapshot['as_of'], changed_at=snapshot['as_of']))
        return


def _dedupe_signals(signals):
    """Each signal id once. The generic evaluate() does not know the built-in hot-cache rule, so
    it re-appended every prior hot-cache signal as not_evaluated next to the freshly evaluated
    one (the dashboard showed each warning twice, 7 of 28 ids on a real receipt). An evaluated
    entry wins over a not_evaluated one; among equals the first wins; first-appearance order holds."""
    chosen, order = {}, []
    for s in signals:
        sid = s['id']
        if sid not in chosen:
            chosen[sid] = s
            order.append(sid)
        elif chosen[sid].get('evaluation') == 'not_evaluated' and s.get('evaluation') != 'not_evaluated':
            chosen[sid] = s
    return [chosen[sid] for sid in order]


def refresh(root, snapshot, cfg, sessions=None, task_of=None):
    state = Path(root) / 'qa-factory/state'
    def read(name, default):
        path = state / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    history = read('metrics-history.json', {'snapshots': []})
    previous = read('metric-signals.json', {})
    # Receipts already on disk may carry an id twice; keep the evaluated copy so first_seen,
    # status and recovery_count survive, and the receipt written below heals in this refresh.
    # Per-session hot-cache signals are replaced by the per-story signal, which lists the same
    # sessions; drop them here, before anything can re-append them as not_evaluated.
    previous = dict(previous, signals=_dedupe_signals(
        [s for s in previous.get('signals', []) if not s['id'].startswith('hot-cache-v1:session-')]))
    policy = (cfg.get('metrics') or {}).get('signal_policy') or {}
    custom_previous = dict(previous, signals=[s for s in previous.get('signals', []) if not s['id'].startswith('legacy-estimate-v1:')])
    receipt = evaluate(snapshot, history['snapshots'], custom_previous, policy)
    hc_signals, hc_evaluations = _hot_cache_signals(snapshot, previous, sessions or [], cfg, task_of)
    receipt['signals'].extend(hc_signals)
    receipt['evaluations'].extend(hc_evaluations)
    # Preserve the existing three-consecutive-precedent rule, with the same lifecycle.
    # Missing prices do not become an in-range observation.
    # CD1-5 (C8b): the cohort is a size AND a unit. The size letter counts the register's rows (`requirements`, a record with no
    # `size_unit`) or the functions (OH3-15); a change of unit is never read as drift. The rows cohort keeps its ids; the functions
    # cohort has ids of its own and exists only once a functions record does (no record: nothing to evaluate).
    from retro_numbers import record_unit      # lazy: the ONE reader of a record's unit
    for unit in ('requirements','functions'):
      for size in ('XS','S','M','L','XL'):
        cohort = sorted([r for r in snapshot.get('estimates', []) if r.get('completed') and record_unit(r.get('forecast')) == unit and
                         ((r.get('forecast') or {}).get('size_final') or (r.get('forecast') or {}).get('size_initial')) == size],
                        key=lambda r:str(r.get('ts') or ''))
        if unit == 'functions' and not cohort:
            continue
        tail = cohort[-3:]
        complete = len(tail)==3 and all(r.get('complete_cost') is not None and (r.get('delta') or {}).get('direction') in {'above','below','within'} for r in tail)
        for direction in ('above','below'):
            rid = size+('-functions' if unit == 'functions' else '')+'-'+direction
            sid = 'legacy-estimate-v1:'+rid
            source = next(m for m in snapshot['metrics'] if m['id']=='C08')
            metric = dict(source, value=sum((r.get('delta') or {}).get('direction')==direction for r in tail),
                          status='available' if complete else 'unavailable', sample_size=len(cohort))
            rule = {'id':rid,'metric':'C08','direction':'above','threshold':3,'recovery_threshold':0,
                    'min_sample':3,'recovery_samples':1,'mode':'absolute',
                    'title':f'{size}{" on the function count" if unit == "functions" else ""}: three consecutive completed tasks {direction} the estimate range',
                    'next_action':'Review the recorded precedents and calibrate the estimate scale'}
            part = evaluate(dict(snapshot,metrics=[metric]), [],
                            {'signals':[s for s in previous.get('signals',[]) if s['id']==sid]},
                            {'version':'legacy-estimate-v1','rules':[rule]})
            receipt['signals'].extend(part['signals'])
            receipt['evaluations'].extend(part['evaluations'])
    receipt['signals'] = _dedupe_signals(receipt['signals'])
    # One point per UTC day; rerenders replace it, never manufacture new samples.
    day = snapshot['as_of'][:10]
    point = {k: snapshot[k] for k in ('as_of', 'input_hash', 'metrics')}
    history['snapshots'] = [s for s in history['snapshots'] if s['as_of'][:10] != day] + [point]
    atomic_json(state / 'metrics-history.json', history)
    atomic_json(state / 'metric-signals.json', receipt)
    return receipt, history['snapshots']


def context(root):
    path = Path(root) / 'qa-factory/state/metric-signals.json'
    if not path.exists():
        return ''
    receipt = json.loads(path.read_text(encoding='utf-8'))
    pending = [s for s in receipt.get('signals', []) if s.get('status') != 'resolved']
    if not pending:
        return ''
    return 'Recorded metric signals (explain actionable changes in the next user-facing result):\n' + '\n'.join(
        f"{s['id']} [{s['status']}; {s.get('evaluation')}]: {s['title']}; current={s.get('current')}; "
        f"baseline={s.get('baseline')}; n={s.get('sample_size')}; {s.get('next_action')}" for s in pending)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Record an explicit human decision; acknowledgement never resolves a metric warning')
    parser.add_argument('--root',required=True)
    parser.add_argument('--ack',required=True,help='Signal id from metric-signals.json')
    parser.add_argument('--decision-ref',required=True,help='Reference to the explicit human decision')
    args=parser.parse_args()
    path=Path(args.root)/'qa-factory/state/metric-signals.json'
    receipt=json.loads(path.read_text(encoding='utf-8'))
    signal=next(s for s in receipt['signals'] if s['id']==args.ack)
    if signal['status']=='resolved':raise ValueError('Signal is already resolved')
    signal.update(status='verifying',acknowledged_at=datetime.now(timezone.utc).isoformat(),decision_ref=args.decision_ref)
    atomic_json(path,receipt)
    from factory_dashboard import main
    main(['--root',args.root])
