"""Persist already collected bug evidence; never fetch a tracker or infer transitions."""
import argparse
import json
from pathlib import Path
from event_store import atomic_json


def validate(value):
    from metrics_projection import timestamp
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('bug snapshot requires schema_version 1')
    if not value.get('scope') or not timestamp(value.get('as_of')) or not value.get('evidence_refs'):
        raise ValueError('bug snapshot requires scope, as_of and evidence_refs')
    if not isinstance(value.get('bugs'), list):
        raise ValueError('bugs must be an explicit list')
    ids=set()
    for bug in value['bugs']:
        if not isinstance(bug, dict) or not bug.get('id') or bug['id'] in ids:
            raise ValueError('each bug needs a unique canonical tracker-qualified id')
        ids.add(bug['id'])
        for field in ('created_at','history_complete_since'):
            if bug.get(field) and not timestamp(bug[field]):
                raise ValueError('invalid '+field)
        for transition in bug.get('transitions', []):
            if not timestamp(transition.get('at')) or not all(transition.get(k) for k in ('from','to','evidence_ref')):
                raise ValueError('transition needs from/to/at/evidence_ref')
    return value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--input',type=Path,required=True)
    args=ap.parse_args()
    value=validate(json.loads(args.input.read_text(encoding='utf-8-sig')))
    atomic_json(args.root/'qa-factory/state/bug-snapshot.json', value)
    from dashboard_refresh import refresh_project
    print(json.dumps(refresh_project(args.root)))


if __name__=='__main__':main()
