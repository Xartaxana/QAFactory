"""Code-only copies and bounded JSON edits for non-authoritative work artifacts."""
import argparse
import copy
import json
import sys
from pathlib import Path
import hooklib
import stand_identity as SI
from event_store import atomic_json, content_hash


def work_path(root, raw):
    root = Path(root).resolve()
    path = (root / raw).resolve()
    if not path.is_relative_to(root / 'work') or path.suffix != '.json':
        raise ValueError('artifact must be a task-local work JSON document')
    if path.name in {'source-inventory.json'} or any(p in path.parts for p in
            SI.PROTECTED_RECEIPT_FOLDERS):
        raise ValueError('use the dedicated evidence producer for this artifact')
    return path


def patch_document(root, request):
    """Compare-and-swap dotted object keys; no evaluation and no partial mutation."""
    if len(json.dumps(request, ensure_ascii=False).encode('utf-8')) > 8192:
        raise ValueError('split the patch into independently reviewable chunks of at most 8 KiB')
    path = work_path(root, request['path'])
    original = json.loads(path.read_text(encoding='utf-8-sig'))
    if content_hash(original) != request.get('expected_hash'):
        raise ValueError('artifact changed; read its current hash before patching')
    result = copy.deepcopy(original)
    for item in request.get('changes', []):
        keys = item['keys']
        if not keys or not all(isinstance(k, str) and k for k in keys):
            raise ValueError('keys must be a nonempty object-key path')
        node = result
        for key in keys[:-1]:
            node = node[key]
        if not isinstance(node, dict):
            raise ValueError('patch target must be an object')
        node[keys[-1]] = item['value']
    atomic_json(path, result)
    return {'path': request['path'], 'content_hash': content_hash(result)}


def skeleton(root, request):
    """Copy selected known records without regenerating their text through an LLM."""
    root = Path(root).resolve()
    source = (root / request['source']).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError('source must be an existing task-local document')
    target = work_path(root, request['path'])
    if target.exists():
        raise ValueError('skeleton never overwrites existing work; use a versioned patch')
    document = json.loads(source.read_text(encoding='utf-8-sig'))
    selected = {key: document[key] for key in request['copy_keys']}
    value = {'schema_version': 1, 'status': 'draft',
             'source_ref': request['source'], 'source_hash': content_hash(document),
             'copied': selected, 'semantic_decisions': {}}
    atomic_json(target, value)
    return {'path': request['path'], 'content_hash': content_hash(value)}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--task-root', required=True)
    parser.add_argument('--operation', choices=('skeleton', 'patch'), required=True)
    parser.add_argument('--input', required=True)
    args = hooklib.exact_options(parser).parse_args()
    root = hooklib.story_cli('artifact_packet.py', root=args.task_root, key_flag=None)    # the story first: before --input is read
    try:
        request = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        result = (skeleton if args.operation == 'skeleton' else patch_document)(root, request)
    except (ValueError, KeyError, OSError) as exc:      # a bad request is the caller's fault: a refusal, not a trace
        print(json.dumps({'error': f'artifact_packet.py: {type(exc).__name__}: {exc}'}), file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
