"""Observed hook receipts are separate from installation, trust and live acceptance."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
from event_store import atomic_json
from hooklib import sorted_paths


def host_of_event(event):
    """Which host fired this hook, by its own signals — never by assumption.

    `host: 'codex' if observed else 'unverified'` used to be hardcoded, so a Claude Code
    session with a directory full of receipts was reported as a Codex host, and the doctor
    skipped the live hook probe as "Codex-only". The probe is host-agnostic: it reacts to
    PreToolUse/PostToolUse, which the Claude Code manifest (hooks/hooks.json) also declares."""
    from host_adapter import is_codex
    if is_codex(event):
        return 'codex'
    event = event or {}
    if event.get('hook_event_name') and (event.get('session_id') or event.get('transcript_path')):
        return 'claude-code'
    return 'unspecified'


def record(root, event, script, code):
    # Recorded on EVERY host. While this returned early for anything but Codex, a Claude Code
    # session could never accumulate the evidence its own readiness check asks for, and
    # host_hooks stayed `unknown` there permanently no matter how well the hooks worked.
    receipt = {'host': host_of_event(event), 'script': script, 'hook': event.get('hook_event_name'),
               'session_id': event.get('session_id'), 'turn_id': event.get('turn_id'),
               'agent_id': event.get('agent_id'), 'tool_name': event.get('tool_name'),
               'exit_code': code, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'source': 'hook_event', 'plugin_root': str(Path(__file__).resolve().parents[1])}
    receipt['script_hash'] = hashlib.sha256((Path(__file__).parent / script).read_bytes()).hexdigest()
    key = hashlib.sha256((str(receipt['session_id']) + script + str(receipt['hook'])).encode()).hexdigest()
    atomic_json(Path(root) / 'qa-factory/state/host-receipts' / (key+'.json'), receipt)


def detect_host(observed):
    """The host the receipts on disk actually came from, as evidence — not as a label.

    No receipts is `unverified`; receipts from more than one host is `mixed`, which is a real
    state (the same project opened from two tools) and not an error to hide."""
    hosts = {str(entry.get('host') or 'unspecified') for entry in observed.values()}
    if not hosts:
        return 'unverified'
    if len(hosts) == 1:
        return hosts.pop()
    return 'mixed:' + ','.join(sorted(hosts))


def hooks_proved(result):
    """Are the host hooks proved, from one `inspect` answer? The ONE statement of the condition (HF8-12, W-5): the readiness
    capability `host_hooks` and the gate's `_proved_warnings` both ask it.

    True when `story_ready` (guard and delivery both probed), or when the live guard is `verified` and a REAL role dispatch
    was handed its packet (`role_context`) on a host other than Codex. On Codex `story_ready` is the spawn gate
    (worker_lifecycle.py), so a receipt there never says `ok` while the gate would still refuse: the unknown stays, with its
    door (E9). An answer that is not a dict, or that lacks a part, is not proof."""
    if not isinstance(result, dict):
        return False
    if result.get('story_ready') is True:
        return True
    probe, role = result.get('guard_probe'), result.get('role_context')
    return (isinstance(probe, dict) and probe.get('status') == 'verified'
            and isinstance(role, dict) and isinstance(role.get('host'), str) and role['host'] != 'codex')


def inspect(root):
    expected = {'guard_pre_tool.py','inject_context.py','validate_artifacts.py','exit_gate.py',
                'subagent_journal.py','cost_capture.py','precompact_guard.py','postcompact_reload.py','host_dispatch.py','native_context.py'}
    observed, stale = {}, []
    for path in sorted_paths((Path(root) / 'qa-factory/state/host-receipts').glob('*.json')):
        try:
            r=json.loads(path.read_text(encoding='utf-8'))
            script=Path(__file__).parent / r['script']
            if r.get('script_hash') != hashlib.sha256(script.read_bytes()).hexdigest():
                stale.append(r['script']); continue
            observed[r['script']]={'hook':r['hook'],'exit_code':r['exit_code'],'observed_at':r['observed_at'],
                                   'host':r.get('host') or 'unspecified','evidence':str(path)}
        except (ValueError, OSError, KeyError, TypeError):   # TypeError: a receipt file that is JSON but not an object (E26)
            continue
    from host_probe import inspect as inspect_probe, role_context as read_role_context, unmet_text
    walked = {}
    probe = inspect_probe(root, walked=walked)
    role_context = read_role_context(root, walked.get('fingerprint'))   # the bytes the probe was judged on, not a second walk
    mechanisms = {name: {'invocation': 'observed' if name in observed else 'unverified',
                         'behavior': 'unverified', 'evidence': observed.get(name)} for name in sorted(expected)}
    mechanisms['guard_pre_tool.py']['behavior'] = probe['status']
    # A hook being invoked does not prove that its context reached the worker.
    injection_ready = probe.get('injection') == 'verified'
    mechanisms['inject_context.py']['behavior'] = probe.get('injection', 'unverified')
    story_ready = probe['status'] == 'verified' and injection_ready
    if story_ready:
        note = 'Live guard and role-context delivery verified; other mechanisms retain their separate evidence status.'
    elif probe['status'] == 'verified' and role_context and role_context.get('host') != 'codex':
        # A real dispatch of a role was handed its packet (HF8-12, W-5). This is a statement about the story's own
        # dispatches, not a change of `injection` or `story_ready`; on Codex `story_ready` is the spawn gate
        # (worker_lifecycle.py), so there the door below stays.
        note = (f"Live allow/deny guard verified; role-context delivery seen in a real dispatch of "
                f"{role_context.get('agent_type') or 'a role'} at {role_context.get('observed_at')}.")
        if probe.get('injection_detail'):
            note = probe['injection_detail'] + '. ' + note
    elif probe['status'] == 'verified':
        note = ('Live allow/deny guard verified; role-context delivery not yet verified. '
                'Dispatch the read-only qa_factory_context_probe diagnostic now (a re-probe after a consumed '
                'name: qa_factory_context_probe__<suffix>), then run host_probe.py --check. '
                'The diagnostic does not require injection to be verified in advance.')
        if probe.get('injection_detail'):
            # A child that answered but not with the whole challenge is told first: it is not "no answer".
            note = probe['injection_detail'] + '. ' + note
    else:
        note = ('Live guard evidence is incomplete, not proof that hooks are disabled. '
                'Run host_probe.py --prepare, execute its allow/deny commands as separate native tools, then --check. '
                'Script smoke and invocation receipts alone do not certify live behavior.'
                + (unmet_text(probe.get('missing')) or ' The reason is not established.'))
    return {'status':'observed_complete' if expected.issubset(observed) else 'observed_partial' if observed else 'unverified', 'shipped_adapter':'codex-native-v1',
            'observed':observed,'missing':sorted(expected-set(observed)), 'stale':sorted(set(stale)),
            'mechanisms': mechanisms, 'guard_probe': probe, 'story_ready': story_ready, 'role_context': role_context,
            'installation': 'present', 'registration': 'declared_in_manifest',
            'enabled': 'unknown', 'host': detect_host(observed),
            'hook_trust':'not_inferred', 'live_parity':'essential_verified' if story_ready else 'not_certified',
            'note': note}
