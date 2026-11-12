"""One factual delivery projection for reports, MR summaries and the dashboard."""
import argparse
from collections import Counter
import json
import os
import re
import sys
from pathlib import Path
from event_store import atomic_json, content_hash
import hooklib
from hooklib import sorted_paths

FRAGMENT_START = '<!-- factory-summary:start -->'
FRAGMENT_END = '<!-- factory-summary:end -->'
FRAGMENT_RE = re.compile(re.escape(FRAGMENT_START) + '.*?' + re.escape(FRAGMENT_END) + r'\n*',
                         re.DOTALL)


TERMINAL_EXECUTION = {'passed', 'failed', 'pass', 'fail', 'partial'}
# `ledger.OWNER_ORDER` / `ledger.OWNER_HEADINGS` restated, because this module imports its
# siblings lazily inside functions and these two are needed at render time. They must stay
# identical: the gate-B message, the ledger and this fragment are read side by side.
OWNERS = ('product', 'environment', 'review', 'factory')
OWNER_HEADINGS = {
    'product': 'What blocks delivery on the product side',
    'environment': 'Environment blockers',
    'review': 'Review gaps',
    'factory': "Factory defects (not the product's — nothing is wanted from you)",
}


BUG_TEXT_LIMIT = 'the readable text of a bug draft could not be written'   # a key of `delivery_state_words.source_gaps`


def _state_table():
    """`delivery_state_words` of `references/report-risk-words.json`: the words of every code this summary shows a person
    (HF8-20, FR-13). Read through `report_facts._risk_words`, the one reader of that file (AR-13). `{}` when the file cannot
    be read: the render then says what it cannot say (FR-41), never a code."""
    import report_facts as RF
    table = RF._risk_words().get('delivery_state_words')
    return table if isinstance(table, dict) else {}


def state_words(state, table=None):
    """`(words, known)` of a row's state code. An exact state first, then its prefix (the part before the first colon)
    with the prose after the colon kept when it is prose (it holds a space); a code after the colon is dropped for the
    prefixes the data names, and a code the data does not hold is `known` False: its words say the factory cannot tell,
    and the code is never printed."""
    table = _state_table() if table is None else table
    unknown = str(table.get('unknown_state') or 'the factory cannot say what this row\'s state means')
    state = str(state or '').strip()
    exact = (table.get('row_states') or {}).get(state)
    if exact:
        return exact, True
    prefix, _, reason = state.partition(':')
    said = (table.get('row_prefixes') or {}).get(prefix.strip())
    reason = reason.strip()
    if not said:
        return unknown, False
    if not reason or prefix.strip() in (table.get('prefix_drops_reason') or []):
        return said, True
    if prefix.strip() == 'waived':
        # the ledger writes a waived row as `waived:<its state>` (ledger.py): the inner state is read by this same
        # function; one the data does not hold leaves the waiver alone, in words, never the record's word
        inner, inner_known = state_words(reason, table)
        return (said + ' — ' + inner if inner_known else said), True
    if ' ' in reason:
        return said + ' — ' + ' '.join(reason.split()), True
    return unknown, False


def _limit_words(text, table):
    """`(words, known)` of one limit the projection recorded: the first `source_gaps` row whose `match` the text holds."""
    for row in table.get('source_gaps') or []:
        if isinstance(row, dict) and row.get('match') and row['match'] in str(text) and row.get('words'):
            return str(row['words']), True
    return str(table.get('unknown_limit') or 'the factory cannot say what limits this summary'), False


def _bug_confirmation(task, data, source_ref, draft=False):
    """`confirmation` of one bug: the local `bugs/BUG-n.md` first (it is the source of truth),
    then the proposal or the draft that stands in for it.

    TP1-15045: two of four bugs came from red tests nobody had triaged or reproduced by
    hand, and the delivery said "4 bugs". A bug filed before 0.7.16 carries no `confirmation`
    and reads as `confirmed_by_person` — nothing already delivered changes colour here.

    Returns `(word, kinds, problems)` - `bug_records.confirmation_of`, THE reader of the step (HF8-16, AR-13): the word is never
    read from the file by this module alone. A `.md` that says `reproduced_by_factory` is checked against the draft the
    proposal names in `source_draft`. `draft=True` (the caller read a DRAFT file): a draft with no word is `unconfirmed`."""
    import contract as C
    import bug_records as BR
    data = data if isinstance(data, dict) else {}
    for candidate in (str(source_ref or ''), str(data.get('bug_file') or '')):
        if not candidate.endswith('.md'):
            continue
        for base in (task, Path(task).parent):
            path = base / candidate
            if path.is_file():
                head = C.read_text(path).split('\n## ', 1)[0]
                match = re.search(r'^\s*confirmation:\s*(.+?)\s*$', head, re.MULTILINE)
                if match:
                    return BR.confirmation_of(task, {'confirmation': match.group(1).strip().strip('"'),
                                                     'source_draft': data.get('source_draft') or ''})
    return BR.confirmation_of(task, data, draft=draft)


def _gap_records(task):
    import contract as C
    path = task / 'work/verification-gaps.json'
    if not path.exists():
        return [], []
    raw = C.load_json(path).get('gaps', [])
    errors, current, seen = [], [], set()
    if not isinstance(raw, list):
        return [], ['verification-gaps.json gaps is not an array']
    for gap in raw:
        if (not isinstance(gap, dict) or not gap.get('id') or gap.get('id') in seen
                or not isinstance(gap.get('revision'), int) or gap['revision'] < 1
                or gap.get('status') not in {'open', 'closed'} or not gap.get('reason')):
            errors.append('invalid or duplicate verification gap record')
            continue
        seen.add(gap['id'])
        if gap['status'] == 'closed' and (not isinstance(gap.get('closed_by'), dict)
                or not gap['closed_by'].get('ref') or not gap['closed_by'].get('revision')):
            errors.append(f"closed verification gap {gap['id']} has no revision-bound evidence")
            continue
        if gap['status'] == 'open':
            current.append(gap)
    return current, errors


def _manual_plan_count(task, plan):
    import contract as C
    document = C.load_json(task / 'work/test-plan.json')
    rows = document if isinstance(document, list) else document.get('rows', [])
    manual_rows = {row.get('id') or row.get('ts') for row in rows if isinstance(row, dict) and (
        row.get('disposition') == 'manual-agent' or any(
            isinstance(ob, dict) and ob.get('decision') == 'manual-agent'
            for ob in row.get('coverage_obligations') or []))}
    try:
        cases = {cid for cid, fact in C.case_index(task).items() if fact.get('plan_row') in manual_rows}
    except (OSError, ValueError):
        cases = set()
    return len(cases) if cases else None


def _comparison_readiness(task, plan_rows, controller_state):
    """Project before/after evidence separately from the current after-run outcome.

    A missing historical stand cannot turn a completed current-run result into an
    environment failure.  It leaves only the comparison unverified.
    """
    from baseline_contract import deployment_readiness
    receipts = []
    for path in sorted_paths((task / 'work' / 'baseline-receipts').glob('*.json')):
        try:
            receipt = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(receipt, dict):
            receipts.append(receipt)
    decisions = controller_state.get('decisions') or {}
    current_revision = controller_state.get('source_revision')
    approved = [decision for decision in decisions.values() if isinstance(decision, dict)
                and decision.get('gate') == 'A' and decision.get('status') == 'approved'
                and (current_revision is None or decision.get('source_revision') == current_revision)]
    expected_gate_ref = approved[-1].get('id') if approved else None
    readiness = deployment_readiness(plan_rows, receipts, task,
                                     expected_gate_ref=expected_gate_ref)
    comparison_ready = readiness.get('comparisons_ready', readiness.get('ready', True))
    gaps = []
    for gap in readiness.get('gaps') or []:
        if not isinstance(gap, dict):
            continue
        gaps.append({**gap, 'status': gap.get('status') or 'awaiting_baseline',
                     'reason': gap.get('reason') or 'before-state comparison is awaiting a baseline capture'})
    return {'comparisons_ready': bool(comparison_ready), 'gaps': gaps,
            'expected_gate_ref': expected_gate_ref}


PROOF_RED = 'probe_not_applicable_red'     # the counter key of a red test with no proof level; its words are `proof_level.red_words()`


def _is_red(row):
    """A ledger test row whose state is `failed:*` (the `waived:` wrapper taken off, as `report_facts._ledger_facts` does)."""
    import contract as C
    state = str(row.get('state') or '')
    state = state[len('waived:'):] if state.startswith('waived:') else state
    return C.ledger_state_prefix(state) == 'failed'


def _left_with_you(task):
    """The report's `## Left with you` section as it stands, from its heading to the next `## ` heading (the code-owned
    blocks inside it included), or None when `test-report.md` or the section is absent. Read by
    `report_facts.left_with_you_text`, the one reader of the section (the report's check and the MR description cannot
    list different items). Never raises: a summary does not fail over a report."""
    try:
        import report_facts
        return report_facts.left_with_you_text(task)
    except Exception:
        return None


def left_with_you_stale(task):
    """Does the recorded summary quote a "Left with you" section other than the report's now (RD1-20)? True / False, or None
    when there is nothing to compare: no `work/delivery-summary.json` yet (silent: a story that has none has nothing stale), or
    one that cannot be read (said in one `report:` line on stderr). Whitespace is not a difference. The section is read by
    `_left_with_you`, the one reader (AR-13); file times are not compared (a copy changes them). Reads only (FR-45)."""
    path = Path(task) / 'work' / 'delivery-summary.json'
    if not path.is_file():
        return None
    try:
        recorded = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(recorded, dict):
            raise ValueError('not a JSON object')
    except (OSError, ValueError) as exc:
        print(f'report: work/delivery-summary.json cannot be read ({type(exc).__name__}); whether it is stale is unknown', file=sys.stderr)
        return None
    said = lambda text: ' '.join(str(text or '').split())      # noqa: E731
    return said(recorded.get('left_with_you')) != said(_left_with_you(task))


def build(task, ledger=None):
    import contract as C
    import delivery_verdict as DV
    task = Path(task)
    controller_state = C.load_json(task / 'state/controller.json')
    ledger_path = C.artifact(task, 'ledger.json')
    ledger = ledger if ledger is not None else C.load_json(ledger_path)
    source_gaps = []
    if not ledger_path.exists() and ledger is not None:
        source_gaps.append('ledger.json is missing; outcomes are an explicit plan fallback')
    from ledger_fingerprint import snapshot as ledger_input_snapshot
    current_inputs = ledger_input_snapshot(task)
    recorded_inputs = ledger.get('source_inputs') if isinstance(ledger, dict) else None
    if not isinstance(recorded_inputs, dict) or not recorded_inputs.get('fingerprint'):
        ledger_freshness = 'unknown'
        source_gaps.append('ledger freshness is unknown: legacy ledger has no source-input fingerprint')
    elif recorded_inputs.get('fingerprint') != current_inputs['fingerprint']:
        ledger_freshness = 'stale'
        source_gaps.append('ledger is stale: plan, run report, manifest, or triage changed after generation')
    else:
        ledger_freshness = 'current'
    rows = ledger.get('rows') or []
    plan = [r for r in rows if r.get('kind') == 'plan_row' and r.get('state') != 'subtask_in_progress']
    if ledger_freshness == 'stale':
        plan = [dict(row, state='not_verified:stale_ledger_inputs',
                     detail='Previously ' + str(row.get('state')) + '; regenerate the projection')
                if str(row.get('state', '')).startswith(('passed', 'manual-agent: PASS')) else row
                for row in plan]
    if not plan:
        document = C.load_json(task / 'work/test-plan.json')
        planned_rows = document if isinstance(document, list) else document.get('rows', [])
        plan = [{'ref': row.get('id') or row.get('ts'), 'kind': 'plan_row',
                 'state': 'deferred_by_decision' if row.get('disposition') == 'skip' else
                          'not_verified:delivery projection not available',
                 'detail': 'No current ledger outcome'} for row in planned_rows]
        if not planned_rows:
            source_gaps.append('test-plan.json and current ledger plan rows are missing')
    # Baseline fields live in the approved plan, while the ledger deliberately records
    # only current after-run outcomes.  Keep these two evidence streams distinct.
    plan_document = C.load_json(task / 'work/test-plan.json')
    comparison_rows = plan_document if isinstance(plan_document, list) else plan_document.get('rows', [])
    comparison = _comparison_readiness(task, comparison_rows if isinstance(comparison_rows, list) else [],
                                       controller_state)
    counts = Counter()
    gaps = []
    for row in plan:
        state = str(row.get('state') or 'unknown')
        if state.startswith(('failed', 'manual-agent: DEFECT')):
            bucket = 'failed'
        elif state.startswith(('passed', 'manual-agent: PASS')):
            bucket = 'verified'
        elif state.startswith(('env_blocked', 'blocked_by_env')):
            bucket = 'env_blocked'
        elif state.startswith(('skipped', 'deferred')):
            bucket = 'deferred'
        else:
            bucket = 'unverified'
        counts[bucket] += 1
        if bucket not in {'verified', 'failed'}:
            gaps.append({'ref': row.get('ref'), 'state': state, 'detail': row.get('detail')})
    # Publication claims are derived only from transport receipts, never from prose.
    decisions = controller_state.get('decisions') or {}
    decisions = decisions if isinstance(decisions, dict) else {}
    gate_b = {str(decision.get('id') or key): set(decision.get('selected_drafts') or [])
              for key, decision in decisions.items() if isinstance(decision, dict)
              and decision.get('gate') == 'B' and decision.get('status') == 'approved'}
    selected = {ref for refs in gate_b.values() for ref in refs}
    bugs = []
    for path in sorted_paths((task / 'work/proposals').glob('*.json')):
        data = C.load_json(path)
        if data.get('kind') != 'bug' or not data.get('bug_file'):
            continue
        receipt = data.get('result') or {}
        source_draft = data.get('source_draft')
        decision_id = str(data.get('gate_b_decision_id') or '')
        selected_by_decision = bool(source_draft and decision_id in gate_b and source_draft in gate_b[decision_id])
        if not selected_by_decision:
            status = 'provenance_invalid'
        else:
            status = 'published' if receipt.get('external_id') and receipt.get('url') else (
                'outcome_unknown' if data.get('pending') or receipt else 'prepared')
        word, kinds, problems = _bug_confirmation(task, data, data['bug_file'])
        bugs.append({'ref': data['bug_file'], 'source_draft': data.get('source_draft'), 'state': status,
                     'gate_b_decision_id': decision_id,
                     'confirmation': word, 'reproduced_how': kinds, 'reproduction_problems': problems,
                     'external_id': receipt.get('external_id'), 'url': receipt.get('url'),
                     'receipt_ref': path.relative_to(task).as_posix()})
    known = {b['ref'] for b in bugs}
    known.update(b['source_draft'] for b in bugs if b['state'] != 'provenance_invalid' and b.get('source_draft'))
    import bug_records as BR   # the one reader of the draft folder (G1-9)
    # A draft a bug FILE names is filed (HF8-22 F-2): the markdown channel writes no proposal, so `known` above never sees it, and
    # "chosen at gate B, not filed yet" would be said about a bug that lies in bugs/. Read through `story_bugs` and `filing_of`,
    # the one reader of where a bug lies (AR-13); a story_bugs that cannot be read leaves the old reading (never a claim of filing).
    # The pairing is the record's own `paths` (a filed bug's record holds the draft it names, `story_bugs` pairs them): no second
    # reader of `source_draft` here.
    filed_by_path = {}
    try:
        for record in BR.story_bugs(task)['records']:
            if record.get('filed'):
                for recorded in record.get('paths') or []:
                    filed_by_path.setdefault(Path(recorded).resolve(), record)
    except Exception:
        filed_by_path = {}
    for path in BR.draft_paths(task):
        ref = path.relative_to(task).as_posix()
        if ref not in known:
            word, kinds, problems = _bug_confirmation(task, C.load_json(path), ref, draft=True)
            row = {'ref': ref, 'state': 'selected' if ref in selected else 'draft',
                   'confirmation': word, 'reproduced_how': kinds, 'reproduction_problems': problems}
            filed = filed_by_path.get(Path(path).resolve())
            if filed:
                tracker = BR.filing_of(task, filed)['tracker']
                row.update(state='published' if tracker.get('state') == 'sent' else 'filed',
                           external_id=tracker.get('key') or None, url=tracker.get('url') or None)
            bugs.append(row)
    # Keep exact details; only identical root keys collapse. No guessed causal association.
    reasons = ledger.get('reason_records') or [
        {'code': 'UNCLASSIFIED_DELIVERY_REASON', 'entity': str(i), 'detail': text}
        for i, text in enumerate(ledger.get('reasons') or [])]
    grouped, by_owner = {}, {}
    for reason in reasons:
        if not isinstance(reason, dict):
            source_gaps.append('ledger contains a malformed delivery reason')
            continue
        key = reason.get('caused_by') or content_hash([reason.get('code'), reason.get('entity')])
        grouped.setdefault(key, {'root_id': key, 'details': []})['details'].append(reason)
        # a delivery reason without an owner is one the reader has to attribute
        # themselves, and they attribute everything to the product. Legacy ledgers written
        # before 0.7.5 carry no owner; they read as `product`, which is the old behaviour.
        owner = str(reason.get('owner') or 'product')
        # RD1-21 (F-3): a reason whose owner the classifier could not establish is filed under `product` (the safe side) and
        # SAYS so; a record with no `owner_established` key reads as today (legacy ledgers).
        said = str(reason.get('detail') or '')
        by_owner.setdefault(owner if owner in OWNERS else 'product', []).append(
            'owner not established: ' + said if reason.get('owner_established') is False else said)
    reasons_by_owner = {owner: by_owner[owner] for owner in OWNERS if by_owner.get(owner)}
    # Only structured current gaps reach the public projection, never stale S4 prose.
    current_gaps, gap_errors = _gap_records(task)
    source_gaps.extend(gap_errors)
    report_path = C.artifact(task, 'run-report.json')
    report = C.load_json(report_path)
    if not report_path.exists():
        source_gaps.append('run-report.json is missing; executed counts are unavailable')
    # What the person runs themselves. It is a projection like every other field here — the
    # manifest's own `unresolved[]` rows, never prose — so the report, the gate-B message and
    # the MR description all quote one list (TP2-2536).
    try:
        handed = C.handed_tests(C.load_json(C.artifact(task, 'automation-manifest.json')))
    except Exception:
        handed = []
    executed = {key for key, result in C.current_instance_results(report).items()
                if not result.get('stale') and C.result_status(result) in TERMINAL_EXECUTION}
    # How sure we are the tests' checks work (D-0010/D-0012), counted from what the ledger already
    # says about each live test row — never recomputed here (FR-17). A legacy ledger carries no
    # `proof_level` on its rows and gets no counts (an empty dict), so nothing is claimed for it.
    test_rows = [r for r in rows if isinstance(r, dict) and r.get('kind') == 'test' and not r.get('dead')]
    # RD1-20: a RED test (the row's state prefix `failed`, a `waived:` wrapper taken off as `report_facts._ledger_facts` does) with
    # no level is not "not probed": its probe is not applicable, the run already failed. A red test with a level stays on it.
    proof_levels = Counter(
        PROOF_RED if str(r.get('proof_level') or 'none') == 'none' and _is_red(r) else str(r.get('proof_level') or 'none')
        for r in test_rows if 'proof_level' in r)
    # Tests the code critic could not verify (D-0013): the person's debt, never a delivery block.
    # Read from the manifest's own verdict, not from a ledger state: a row that a triage verdict
    # turned green (a fixed FLAKY) or any other state still carries the debt.
    import ledger as L
    # Of the not-required rows, why (the ledger's `proof_reason`): the line says each in the words of
    # its reason. The level id and its total stay in `proof_levels`; a ledger written before
    # `proof_reason` existed gives '' and reads with today's words.
    not_required_reasons = Counter(str(r.get('proof_reason') or '') for r in test_rows
                                   if r.get('proof_level') == L.PROOF_NOT_REQUIRED)
    from traceability import is_dead_test
    unverified =[{'ref': C.test_instance_id(t), 'test': L.test_label(t),
                   'why': ' '.join(str(t.get('sensitivity_proof_missing_reason') or '').split())}
                  for t in C.manifest_tests(C.load_json(C.artifact(task, 'automation-manifest.json')))
                  if L.is_unverified(t) and not is_dead_test(t)]
    executed_manual = {str(result.get('attempt_id')) for result in report.get('current_manual_checks', [])
                       if isinstance(result, dict) and result.get('attempt_id') and not result.get('stale')
                       and result.get('evidence_validated') and result.get('result') in {'pass', 'fail', 'inconclusive'}}
    return {'schema_version': 1, 'task': task.name, 'ledger_hash': content_hash(ledger),
            'counts': {'planned': len(plan), 'executed': len(executed) + len(executed_manual),
                'planned_manual': _manual_plan_count(task, plan), 'executed_manual': len(executed_manual),
                **{k: counts[k] for k in
                ('verified', 'failed', 'unverified', 'env_blocked', 'deferred')}},
            'gaps': gaps, 'outcomes': plan, 'bugs': bugs, 'handed_to_person': handed,
            'proof_levels': dict(proof_levels), 'not_required_reasons': dict(not_required_reasons),
            'unverified_by_critic': unverified,
            'root_causes': list(grouped.values()),
            'reasons_by_owner': reasons_by_owner, 'blocked_by': list(reasons_by_owner),
            'factory_coverage_gaps': L.factory_coverage_gaps(ledger),
            'current_design_gaps': current_gaps, 'controller_revision': controller_state.get('revision'),
            'comparisons_ready': comparison['comparisons_ready'],
            'comparison_gaps': comparison['gaps'],
            'comparison_gate_a_ref': comparison['expected_gate_ref'],
            'delivery_ready': bool(ledger.get('delivery_ready', False)) and ledger_freshness != 'stale',
            # t-305 N8: the ledger's verdict word, read by THE reader; a stale ledger speaks for nothing, so it reads `no`
            'delivery_verdict': ((DV.word_of(ledger) or 'no') if ledger_freshness != 'stale' else 'no'),
            # F9 (FR-10): ONE list. The MR description quotes the report's own "Left with you" section, whole - the
            # scribe's items and the code-owned blocks inside it - never a list of its own; None when there is no report
            # (or it has no such section) and `render` then says so in one line.
            'left_with_you': _left_with_you(task),
            'source_gaps': sorted(set(source_gaps)),
            'ledger_freshness': ledger_freshness, 'current_source_inputs': current_inputs}


def embed(text, fragment):
    """The document with exactly ONE copy of the fragment.

    On TP1-15045 the markers were inserted twice into the same report: the second writer
    appended instead of replacing, and the person read the whole verification block twice.
    Stripping every existing block before appending makes a second insert a no-op."""
    body = FRAGMENT_RE.sub('', str(text or '')).rstrip('\n')
    fragment = str(fragment or '').strip('\n')
    if not fragment:
        return body + '\n' if body else ''
    return (body + '\n\n' if body else '') + fragment + '\n'


def strip(text):
    """The document without the machine fragment — what the author actually wrote."""
    return FRAGMENT_RE.sub('', str(text or ''))


def _not_required_parts(total, reasons):
    """[(words, count)] for the not-required rows, each in the words of its reason
    (`proof_level.words_for`): an unchanged and an unmeasured row share one part, a handed row has its
    own. A reason the vocabulary has no words for, a ledger with no reasons (written before
    `proof_reason`), or reasons that do not add up to the level's total keep today's words and the
    level's total: the level id's count is the authority, and it never moves (t-134 V7)."""
    import proof_level as PL
    today = PL.not_required_words()
    grouped = {}
    for reason, n in (reasons if isinstance(reasons, dict) else {}).items():
        said = PL.words_for(reason) or today
        grouped[said] = grouped.get(said, 0) + (n if isinstance(n, int) else 0)
    if sum(grouped.values()) != total:
        return [(today, total)]
    return sorted(grouped.items(), key=lambda item: (item[0] != today, item[0]))


def proof_levels_line(counts, reasons=None):
    """'Tests by proof level: the check is live: 3; not probed (unchanged test): 1', or '' when the
    ledger carried no `proof_level` at all (legacy). The words are the vocabulary's, never
    restated here (FR-13): level ids from `verification-levels.json` first, lowest rank first,
    then the three states with no level id of their own. `reasons` is `{reason: count}` of the
    not-required rows: they are counted under the words of their reason, so a test handed to the
    person never reads "unchanged test" (FR-10: the ledger says the same)."""
    if not counts:
        return ''
    import ledger as L
    import proof_level as PL
    order = [row['id'] for row in PL.levels()] + ['none', PROOF_RED, L.PROOF_NOT_REQUIRED, L.PROOF_UNKNOWN]
    order += [key for key in counts if key not in order]      # an id the vocabulary lacks is still said
    words = {'none': PL.words(None), PROOF_RED: PL.red_words(), L.PROOF_UNKNOWN: PL.unknown_words()}
    parts = []
    for key in order:
        if not counts.get(key):
            continue
        if key == L.PROOF_NOT_REQUIRED:
            parts.extend(f"{said}: {n}" for said, n in _not_required_parts(counts[key], reasons))
        else:
            parts.append(f"{words.get(key) or PL.words(key)}: {counts[key]}")
    return 'Tests by proof level: ' + '; '.join(parts) if parts else ''


def render(summary):
    import bug_records as BR
    REPRODUCED = BR.REPRODUCED
    counts = summary['counts']
    table = _state_table()
    unsaid = []     # what this render had no words for: said once, in words, at the end (FR-41); the code is never printed
    shown = lambda key: 'unknown' if counts.get(key) is None else str(counts[key])
    keys = ('planned', 'executed', 'planned_manual', 'executed_manual', 'verified', 'failed',
            'unverified', 'env_blocked', 'deferred')
    heads = table.get('columns') or {}
    lines = [FRAGMENT_START, '## Recorded verification', '',
             '| ' + ' | '.join(str(heads.get(k) or 'Unnamed count') for k in keys) + ' |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
             '| ' + ' | '.join(shown(k) for k in keys) + ' |', '',
             'Rows and checks are different units and are not presented as a ratio. Checks run include current automated checks and manual checks whose evidence was recorded.', '']
    levels_line = proof_levels_line(summary.get('proof_levels'), summary.get('not_required_reasons'))
    if levels_line:
        lines.extend([levels_line, ''])
    for gap in summary['gaps']:
        said, known = state_words(gap.get('state'), table)
        if not known:
            unsaid.append('row')
        lines.append('- ' + str(gap['ref']) + ': ' + said.replace('\n', ' '))
    # t-305 N8 (F9, Q-N8-6, FR-10): what is left with the person is ONE list - the report's own "Left with you"
    # section, quoted whole. The two lists this fragment used to build for itself ("Run these yourself", and the
    # tests the code critic could not verify) are gone: a second list is how the MR and the report came to differ.
    left = summary.get('left_with_you')
    lines.extend(['', left.rstrip('\n') if isinstance(left, str) and left.strip() else
                  'Left with you: the report has none yet — see test-report.md'])
    import ledger as L
    unproven = summary.get('factory_coverage_gaps') or 0
    for owner, reasons in (summary.get('reasons_by_owner') or {}).items():
        lines.extend(['', OWNER_HEADINGS[owner] + ':'])
        if owner == 'factory' and unproven:
            lines.append('- ' + L.factory_coverage_line(unproven))
        lines.extend('- ' + reason.replace('\n', ' ') for reason in reasons)
    if summary.get('blocked_by') == ['factory'] and not unproven:
        lines.extend(['', 'Nothing here says the product is not ready: every reason left is a '
                      'defect of the factory itself, and it is ours to fix.'])
    lines.extend(['', 'Bug publication:'])
    # Confirmed and unconfirmed apart, always: on TP1-15045 two of the four bugs delivered
    # were red tests nobody had triaged or reproduced, and the count said four.
    groups = Counter(str(bug.get('confirmation') or 'confirmed_by_person')
                     for bug in summary['bugs'])
    unconfirmed = groups.get('unconfirmed', 0)
    reproduced = groups.get(REPRODUCED, 0)
    if summary['bugs']:
        confirmed = sum(n for name, n in groups.items() if name not in ('unconfirmed', REPRODUCED))
        parts = ([str(confirmed) + ' confirmed'] if confirmed else []) + \
                ([str(reproduced) + ' reproduced by the factory'] if reproduced else []) + \
                ([str(unconfirmed) + ' unconfirmed'] if unconfirmed else [])
        # The legend is what it was while no bug carries a reproduction record (the pins hold it); once one does,
        # "no person and no second run has reproduced it" would be false of it (HF8-16, M-2).
        history = any(bug.get('reproduced_how') or bug.get('reproduction_problems')
                      or bug.get('confirmation') == REPRODUCED for bug in summary['bugs'])
        legend = ('. An unconfirmed bug counts toward nothing.' + (
            ' A bug reproduced by the factory failed again on another run or under the analyst\'s own script; '
            'no person has confirmed it yet.' if reproduced else '') if history else
            '. An unconfirmed bug is one no person and no second run on another '
            'stand has reproduced; it counts toward nothing.')
        lines.append('Product bugs — ' + ' · '.join(parts) + legend)
    for bug in summary['bugs']:
        # Internal draft paths are not public evidence links.
        label = Path(bug['ref']).stem
        word = str(bug.get('confirmation') or '')
        # the same sentence as the report and the gate (bug_records.reproduction_words, FR-10); a bug with no step shows
        # the short mark it always had
        mark = ' — ' + BR.reproduction_words(bug) if word == REPRODUCED or (
            word == 'unconfirmed' and bug.get('reproduction_problems')) else (
            ' — unconfirmed' if word == 'unconfirmed' else '')
        bug_said = (table.get('bug_states') or {}).get(bug['state'])
        if not bug_said:
            bug_said = str(table.get('unknown_state') or 'the factory cannot say what this row\'s state means')
            unsaid.append('bug')
        lines.append('- ' + label + ': ' + bug_said + (
            ' (' + str(bug['external_id']) + ')' if bug['state'] == 'published' else '') + mark)
    if not summary['bugs']: lines.append('- No publication receipts recorded.')
    if summary.get('current_design_gaps'):
        lines.extend(['', 'Unresolved design decisions:'])
        for gap in summary['current_design_gaps']:
            lines.append('- ' + str(gap.get('id', 'unidentified')) + ': ' + str(gap.get('reason', 'unresolved')))
    if summary.get('comparison_gaps'):
        lines.extend(['', 'Before/after comparisons awaiting a before-state capture:'])
        for gap in summary['comparison_gaps']:
            lines.append('- ' + str(gap.get('case_id', 'unidentified')) + ': ' +
                         str(gap.get('reason', 'unverified comparison')))
        lines.extend(['', 'Where can the before state be checked (stand and revision), or will you perform the comparison yourself, including in production?'])
    limits = []
    for value in summary.get('source_gaps') or []:
        said, known = _limit_words(value, table)
        if not known:
            unsaid.append('limit')
        limits.append('- ' + said)
    if unsaid:
        limits.append('- ' + str(table.get('unknown_finding') or 'The factory has no words for part of this summary; '
                                 'that is its own gap, and nothing is asked of you.'))
    if limits:
        lines.extend(['', 'Limits of this summary:'] + limits)
    lines.append(FRAGMENT_END)
    return '\n'.join(lines) + '\n'


def open_items(task):
    """The gate-B "Open before the MR" lines, rendered for the MR description.

    The person may answer "open the MR anyway"; what was open at that moment then travels
    into the MR description verbatim instead of staying in a chat message nobody reopens.
    `gate_brief.open_before_mr` is imported lazily and its absence skips the section — an
    older installation must not lose its MR over a block that is new this version."""
    try:
        from gate_brief import open_before_mr
        lines = open_before_mr(Path(task))
    except Exception:
        return ''
    lines = [str(line).replace('\n', ' ').strip() for line in (lines or [])]
    # `gate_brief` already returns markdown bullets; the line travels as it was shown, so a
    # reader of the MR and the person at the gate are reading the same sentence.
    lines = [line if line.startswith('- ') else '- ' + line for line in lines if line]
    if not lines:
        return ''
    return '\n'.join(['## Open items', '',
                      'Open when this MR was authorized, in the words the gate B message used:',
                      ''] + lines) + '\n'


def write(task, ledger=None):
    """Both files under `work/`. The fragment is a machine record the MR description and the
    validator quote byte for byte; it stopped being pasted into the report because the person
    reads the report to decide, and a counts table of rows-versus-instances is not a decision
    (TP1-15045, second reading)."""
    task = Path(task)
    summary = build(task, ledger)
    # HF8-20 (AR-16): the ONE place the readable text of each bug draft is written; gate B and the report only read it.
    # A draft whose text could not be written is a limit of this summary, said in words, and the others are still written.
    import bug_records as BR
    try:
        texts_failed = any(entry['problem'] for entry in BR.write_draft_texts(task))
    except Exception:   # a summary is never lost over a text of a draft (P1)
        texts_failed = True
    if texts_failed:
        summary['source_gaps'] = sorted(set(summary['source_gaps']) | {BUG_TEXT_LIMIT})
    atomic_json(task / 'work/delivery-summary.json', summary)
    markdown = task / 'work' / 'delivery-summary.md'
    markdown.parent.mkdir(parents=True, exist_ok=True)
    temporary = markdown.with_name(markdown.name + '.tmp')
    try:
        temporary.write_text(render(summary), encoding='utf-8', newline='\n')
        os.replace(temporary, markdown)
    finally:
        temporary.unlink(missing_ok=True)
    return summary


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--task-root', required=True)
    parser.add_argument('--check-report')
    parser.add_argument('--open-items', action='store_true',
                        help='print the "Open items" block for an MR opened over open rows')
    args = hooklib.exact_options(parser).parse_args()
    task_root = hooklib.story_cli('delivery_summary.py', root=args.task_root, key_flag=None)   # before `write` creates anything
    summary = write(task_root)
    fragment = render(summary)
    if args.open_items:
        block = open_items(task_root)
        print(block, end='') if block else print(
            'nothing is open: the MR description carries no Open items section')
        return 0
    if args.check_report:
        # The fragment lives under `work/` now. A document that still carries the markers is
        # still checked where they are — a story in flight on 0.7.11 must not lose its gate
        # over a file that moved this version.
        target = Path(args.check_report)
        text = target.read_text(encoding='utf-8-sig') if target.exists() else ''
        if FRAGMENT_START not in text:
            moved = target.parent / 'work' / 'delivery-summary.md'
            text = moved.read_text(encoding='utf-8-sig') if moved.exists() else ''
        if fragment.strip() not in text:
            print('STALE_REPORT_SUMMARY: regenerate the recorded verification section')
            return 1
    else:
        print(fragment)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
