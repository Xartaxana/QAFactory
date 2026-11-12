"""Prepare and validate author-owned artifacts before an atomic handoff publication."""
import argparse
import json
import os
import tempfile
from pathlib import Path
import hooklib
import stand_identity as SI
from event_store import atomic_json, content_hash
from detector_verdict import one_of
from role_cli import RefusingParser, command_from_argv, epilog, refuse, run_guarded

NAMES = {'readiness': 'requirements-readiness.json', 'triage': 'triage.json'}
TRIAGE_ROW_IDS = ('instance_id', 'attempt_id')   # what every triage row names (AR-13: the one list; the failure analyst's card tells it)
KINDS = ('readiness', 'triage', 'case', 'bug')     # the --kind choices; a batch item holding another is told this set
# The shape of one `validate-batch --input` file. Run 12586: the requirements tester read `--help` four times and sent
# the artifact itself, then items keyed `input`/`artifact`: eight refusals that never named this form (SC1-7).
BATCH_FORM = ('a batch is {"artifacts": [{"kind": "<readiness|triage|case|bug>", "path": "<task-relative path>", '
              '"data": <the artifact object>}]}; one artifact alone is checked by validate --kind <K> --input <file>')


def _frontmatter_scalar(value):
    """Encode the subset understood by hooklib.parse_frontmatter without lossy escaping."""
    if value is None:
        return ''
    if isinstance(value, str):
        if '\n' in value or '\r' in value or value != value.strip():
            raise ValueError('frontmatter strings must be single-line without edge whitespace')
        return value
    if isinstance(value, list):
        if any(isinstance(item, (dict, list)) for item in value):
            raise ValueError('frontmatter arrays must contain scalars')
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    if isinstance(value, (bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError('frontmatter values must be scalar or scalar arrays')


def prepare(kind):
    if kind == 'readiness':
        return {'verdict': None, 'goal_summary': None, 'aspects': {},
                'register': {'total': None, 'by_source': {}}, 'open_questions': []}
    if kind == 'triage':
        return {'triage': []}
    if kind in {'bug', 'case'}:
        import validate_artifacts as V
        keys = V.BUG_REQUIRED + V.BUG_FORM_REQUIRED if kind == 'bug' else V.CASE_REQUIRED
        if kind == 'bug':
            # `confirmation` is offered here rather than added to BUG_REQUIRED: a bug filed
            # before TP1-15045 taught the rule carries none and reads as confirmed
            # (contract.bug_confirmation), and only a bug written NOW must state it.
            keys += ['source_draft', 'gate_b_decision_id', 'confirmation', 'cases', 'requirements', 'no_case_reason',
                     'red_test', 'red_test_none']
        return {'frontmatter': dict.fromkeys(keys), 'body': None}
    raise ValueError('unknown artifact kind')


def render(data):
    fm = data.get('frontmatter') or {}
    return '---\n' + '\n'.join(f'{k}: {_frontmatter_scalar(v)}' for k, v in fm.items()) + '\n---\n\n' + str(data.get('body') or '') + '\n'


def _roundtrip_frontmatter(data):
    from hooklib import parse_frontmatter
    try:
        parsed = parse_frontmatter(render(data))
        expected = {str(key): _frontmatter_scalar(value) for key, value in (data.get('frontmatter') or {}).items()}
    except (TypeError, ValueError) as exc:
        return None, [f'frontmatter renderer: {exc}']
    errors = [] if parsed == expected else ['frontmatter renderer does not round-trip through the factory parser']
    return parsed, errors


def validate(kind, data, task_root=None, not_checked=None):
    """The errors of one artifact. `task_root` (the story folder) lets the readiness verdict be checked against the
    recorded answers; without it that half is not judged - it is said, in `not_checked` (a list the caller passes
    in, filled with texts), and is never an error and never a pass."""
    import validate_artifacts as V
    from check_witness import RULES, readiness_check
    if not isinstance(data, dict):
        return ['artifact must be an object']
    errors = []
    if kind in NAMES:
        try:
            if kind == 'readiness':
                checked = readiness_check(data, task_root)
                errors.extend(checked['errors'])
                if not_checked is not None:
                    not_checked.extend(checked['not_checked'])
            else:
                errors.extend(RULES[NAMES[kind]](data))
            if kind == 'triage':
                V.check_triage_v0(Path('triage.json'), data, errors, task_root)
                if task_root is None and not_checked is not None:
                    # the evidence file of a `control` block cannot be looked for without the story folder: said, never
                    # an error and never a pass of that half (HF2-18, N1)
                    not_checked.extend(
                        f"triage row {row.get('instance_id') or row.get('test') or i}: the control experiment's evidence "
                        "file was not looked for (no task root)"
                        for i, row in enumerate(data.get('triage') or [])
                        if isinstance(row, dict) and isinstance(row.get('control'), dict)
                        and row['control'].get('evidence'))
                for i, row in enumerate(data.get('triage') or []):
                    absent = [key for key in TRIAGE_ROW_IDS if not row.get(key)]
                    if absent:
                        errors.append(f'triage[{i}]: ' + ' and '.join(TRIAGE_ROW_IDS) + ' required (missing: '
                                      + ', '.join(absent) + ')')
        except (TypeError, AttributeError, ValueError) as exc:
            errors.append('invalid artifact structure: ' + str(exc))
    elif kind in {'bug', 'case'}:
        fm, render_errors = _roundtrip_frontmatter(data)
        errors.extend(render_errors)
        fm = fm or {}
        required = V.BUG_REQUIRED if kind == 'bug' else V.CASE_REQUIRED
        errors.extend(f'frontmatter.{key}: required' for key in required if not fm.get(key))
        if not data.get('body'):
            errors.append('body: required')
        if kind == 'bug':
            source_draft = str(fm.get('source_draft') or '')
            if (not source_draft or Path(source_draft).is_absolute() or '..' in Path(source_draft).parts
                    or not fm.get('gate_b_decision_id')):
                errors.append('bug requires relative source_draft and gate_b_decision_id provenance')
            if fm.get('status') not in V.BUG_STATUS:
                errors.append('frontmatter.status must be one of ' + one_of(V.BUG_STATUS))
            if fm.get('severity') not in V.BUG_SEVERITY:
                errors.append('frontmatter.severity must be one of ' + one_of(V.BUG_SEVERITY))
            draft = None
            if source_draft and not Path(source_draft).is_absolute() and '..' not in Path(source_draft).parts:
                if task_root is not None:
                    # t-2187 N4: the draft the bug names, through the one reader (an unreadable one is `{}`: said, never a pass)
                    import bug_records as BR
                    draft = BR._draft_of(Path(task_root), source_draft)
                elif not_checked is not None:
                    not_checked.append('the manifestations of the source draft were not checked (no task root)')
            V.check_bug_form(Path('BUG-draft.md'), fm, render(data), errors, draft)
        else:
            if fm.get('status') not in V.CASE_STATUS:
                errors.append('frontmatter.status must be one of ' + one_of(V.CASE_STATUS))
            if fm.get('channel') not in V.CASE_CHANNEL:
                errors.append('frontmatter.channel must be one of ' + one_of(V.CASE_CHANNEL))
            V.check_case_form(Path('TC-draft.md'), fm, errors)
    else:
        errors.append(f"unknown artifact kind {kind!r}: one of {', '.join(sorted(KINDS))}")
    return sorted(set(errors))


def validate_batch(items, task_root=None):
    """Validate a producer handoff as one unit and fingerprint repeated repair failures. With no `task_root` what
    could not be checked is `not_checked: [{artifact, detail}]` (present only when something was left unchecked)."""
    unchecked = []
    if not isinstance(items, list) or not items:
        issues = [{'code': 'PRODUCER_BATCH', 'artifact': '', 'detail': 'nonempty artifacts array required: ' + BATCH_FORM}]
    else:
        issues = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append({'code': 'PRODUCER_BATCH', 'artifact': str(index),
                               'detail': f'artifacts[{index}] must be an object {{"kind", "path", "data"}}, not a {type(item).__name__}'})
                continue
            kind, path = item.get('kind'), item.get('path') or str(index)
            if 'data' not in item:
                # «artifact must be an object» was the same text four times for an item keyed `input`/`artifact`
                # (t-1230 section 5) and named neither key; the keys the item HAS are the fastest repair
                issues.append({'code': 'ARTIFACT_CONTRACT', 'artifact': path,
                               'detail': f'artifacts[{index}]: no "data" (keys given: {", ".join(sorted(map(str, item))) or "none"}); '
                                         '"data" holds the artifact object itself'})
                continue
            left = []
            for detail in validate(kind, item.get('data'), task_root, left):
                issues.append({'code': 'ARTIFACT_CONTRACT', 'artifact': path, 'detail': detail})
            unchecked.extend({'artifact': path, 'detail': detail} for detail in left)
    normalized = sorted((issue['code'], issue['artifact'], issue['detail']) for issue in issues)
    result = {'valid': not issues, 'errors': issues,
              'repair_fingerprint': content_hash({'producer_contract': 1, 'issues': normalized}) if issues else None}
    if unchecked:
        result['not_checked'] = unchecked
    return result


def update_verification_gap(task_root, change):
    """Create or revise one durable design gap without erasing its closure evidence."""
    root = Path(task_root).resolve()
    path = root / 'work' / 'verification-gaps.json'
    document = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {
        'schema_version': 1, 'gaps': []}
    if not isinstance(change, dict) or not change.get('id'):
        raise ValueError('verification gap change requires id')
    gaps = document.get('gaps')
    if not isinstance(gaps, list) or any(not isinstance(item, dict) for item in gaps):
        raise ValueError('verification-gaps.json has invalid gaps')
    matches = [item for item in gaps if item.get('id') == change['id']]
    if len(matches) > 1:
        raise ValueError('verification gap identity is duplicated')
    current = matches[0] if matches else None
    expected = change.get('expected_revision')
    if current is None:
        if expected not in (None, 0):
            raise ValueError('new verification gap expected_revision must be 0 or omitted')
        if change.get('status', 'open') != 'open' or not change.get('reason'):
            raise ValueError('new verification gap requires open status and reason')
        record = {'id': change['id'], 'revision': 1, 'status': 'open',
                  'reason': change['reason'], 'source_refs': change.get('source_refs') or []}
        gaps.append(record)
    else:
        if expected != current.get('revision'):
            raise ValueError('verification gap revision is stale')
        if current.get('status') == 'closed':
            raise ValueError('closed verification gap is immutable')
        status = change.get('status', 'open')
        if status not in {'open', 'closed'}:
            raise ValueError('verification gap status must be open or closed')
        record = dict(current)
        record['revision'] = current['revision'] + 1
        record['status'] = status
        if change.get('reason'):
            record['reason'] = change['reason']
        if status == 'closed':
            closed_by = change.get('closed_by')
            if (not isinstance(closed_by, dict) or not closed_by.get('ref')
                    or not closed_by.get('revision')):
                raise ValueError('closing a verification gap requires revision-bound closed_by evidence')
            record['closed_by'] = closed_by
        gaps[gaps.index(current)] = record
    document['gaps'] = gaps
    atomic_json(path, document)
    return record


def publish(root, kind, data, relative, expected_hash=None):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    allowed = target.is_relative_to(root / 'work')
    if kind == 'bug':
        allowed = allowed or target.is_relative_to(root / 'bugs')
    if not allowed or any(x in target.parts for x in SI.PROTECTED_RECEIPT_FOLDERS):
        raise ValueError('author artifact must be under task/work, outside evidence receipts')
    if kind in NAMES and target.name != NAMES[kind]:
        raise ValueError('canonical artifact filename required')
    if kind in {'bug', 'case'}:
        # A case's name is one case id in the project's own form (`config.case_id_form`, then
        # `TC-NNN`); this was `startswith('TC-')`, so a project-form case could not be published
        # through the one door that writes it (B-013, FR-17).
        if kind == 'bug':
            named = target.stem.startswith('BUG-')
        else:
            import contract as C
            named = C.is_case_id(target.stem, root)
        if target.suffix != '.md' or not named or target.stem != data.get('frontmatter', {}).get('id'):
            raise ValueError('filename must equal the frontmatter identity'
                             + ('' if kind == 'bug' else
                                ", and a case's is one case id in a form this project records "
                                f"(for this story `{C.case_id_example(root.name, root)}`)"))
    issues = validate(kind, data, root)    # publish always has the story: the verdict is checked against its answers
    if issues:
        return {'valid': False, 'errors': [{'code': 'ARTIFACT_CONTRACT', 'artifact': relative,
                'detail': e} for e in issues], 'repair_fingerprint': content_hash([relative, data, issues])}
    if target.exists():
        import hashlib
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
            # the current hash is NOT printed: --expected-hash is the proof that the file is the one the role read, and a
            # hash handed back by the refusal would make it a stamp (F6)
            raise ValueError('existing artifact requires its exact previous sha256: pass --expected-hash <sha256 of the '
                             f'bytes of {relative} you last read>')
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind in NAMES:
        atomic_json(target, data)
    else:
        fd, raw = tempfile.mkstemp(dir=target.parent, prefix='.publish-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(render(data))
            os.replace(raw, target)
        finally:
            if Path(raw).exists(): Path(raw).unlink()
    return {'valid': True, 'path': relative, 'content_hash': content_hash(data)}


def main():
    # `ArgumentParser(__doc__)` put the whole docstring where the program NAME goes, so
    # every usage line a role read started with a paragraph.
    parser = RefusingParser(command=command_from_argv('artifact_producer.py'), description=__doc__,
                            epilog=epilog('artifact_producer.py'), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('operation', choices=('prepare', 'validate', 'validate-batch', 'gap-update', 'publish'))
    parser.add_argument('--kind', choices=KINDS)
    parser.add_argument('--task-root'); parser.add_argument('--input'); parser.add_argument('--path')
    parser.add_argument('--expected-hash')
    args = hooklib.exact_options(parser).parse_args()
    if args.task_root is not None:      # a GIVEN root names an existing story before anything is read or written
        try:
            hooklib.story_of('artifact_producer.py', root=args.task_root, key_flag=None)
        except ValueError as exc:       # this script's own channel (run_guarded's refusal), never a trace (E-5)
            return refuse(f'artifact_producer.py {args.operation}', str(exc))
    if args.operation in {'publish', 'gap-update'} and not args.task_root:
        parser.error(f'--task-root is required for {args.operation}: the story folder, qa-factory/artifacts/<KEY>')
    if args.operation in {'validate', 'validate-batch', 'gap-update', 'publish'} and not args.input:
        parser.error(f'--input is required for {args.operation}: the JSON file to read'
                     + (' (' + BATCH_FORM + ')' if args.operation == 'validate-batch' else ''))
    if args.operation not in {'validate-batch', 'gap-update'} and not args.kind:
        parser.error(f'--kind is required for {args.operation}: one of {", ".join(KINDS)}')
    # publish resolved `task_root / args.path`, and with no --path that is a TypeError about
    # WindowsPath and NoneType - a role cannot act on that.
    if args.operation == 'publish' and not args.path:
        return refuse('artifact_producer.py publish', '--path is missing')
    if args.operation == 'prepare':
        result = prepare(args.kind)
    elif args.operation == 'validate-batch':
        payload = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        result = validate_batch(payload.get('artifacts') if isinstance(payload, dict) else payload, args.task_root)
    elif args.operation == 'gap-update':
        payload = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        result = update_verification_gap(args.task_root, payload)
    else:
        try:
            data = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as exc:
            return refuse(f'artifact_producer.py {args.operation}',
                          f'{args.input} is not readable JSON: {exc}')
        if args.operation == 'validate':
            unchecked = []
            errors = validate(args.kind, data, args.task_root, unchecked)
            result = {'valid': not errors, 'errors': errors}
            if unchecked:
                result['not_checked'] = unchecked
        else:
            result = publish(args.task_root, args.kind, data, args.path, args.expected_hash)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get('valid') is False else 0


if __name__ == '__main__':
    raise SystemExit(run_guarded(command_from_argv("artifact_producer.py"), main))
