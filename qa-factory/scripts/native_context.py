"""Deliver Codex context at SubagentStart without modifying opaque spawn messages."""
import hashlib
import json
from pathlib import Path
from event_store import EventStore, StateConflict, atomic_json
from hooklib import sorted_paths

PROBE_TASK = 'qa_factory_context_probe'
NAME_HEX = 32
# Longest project root (characters) for which the packet, written through event_store's temp
# name (`.json.<32 hex>.tmp`), stays within the Windows 259-character path limit:
# root + len('\qa-factory\state\native-context\') 33 + 32 + 1 + 32 + len('.json') 5 + len('.<32 hex>.tmp') 37 <= 259.
PACKET_ROOT_LIMIT = 119


def _folder(root):
    return Path(root)/'qa-factory/state/native-context'


def _slot(root, session, task_name=None):
    """The file of ONE launch: <32 hex of sha256(session)>-<32 hex of sha256(task_name)> when
    the launch has a name, <32 hex of sha256(session)> when it has none. The session comes
    first so that one session's packets are found by prefix. 32 hex is 128 bits, so a
    collision is practically none. The short name keeps the packet and its temp file under
    the Windows 259-character path limit for a project root up to PACKET_ROOT_LIMIT characters.
    A packet written under the old 64-hex name is still found by the same prefix and, being
    checked by the session stored inside it, is its own launch's packet, never another's."""
    name = _session_key(session) + ('-' + _digest(task_name) if task_name else '')
    return _folder(root)/(name+'.json')


def _digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:NAME_HEX]


def _session_key(session):
    return _digest(session)


def _session_packets(root, session):
    """(path, packet) of every readable packet of this host session.

    Only files with the session's prefix are opened (the folder is never emptied, and a
    delivery runs under the lock at every SubagentStart); the session stored INSIDE the
    packet is still checked. An unreadable file is skipped: one broken file must not stop
    the delivery of the others."""
    for path in sorted_paths(_folder(root).glob(_session_key(session) + '*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get('session_id') == session:
            yield path, data


def pending_path(root, session, task_name=None):
    """Where a launch's packet lives. With a task_name, its own file. Without one, the
    session-only packet, or, when there is none, the session's only packet (readers that
    know no task name, such as the doctor's tests, still find the one launch in flight)."""
    if task_name:
        return _slot(root, session, task_name)
    plain = _slot(root, session)
    if plain.is_file():
        return plain
    found = [path for path, _ in _session_packets(root, session)]
    return found[0] if len(found) == 1 else plain


def is_probe_task(name):
    """True for PROBE_TASK itself or PROBE_TASK + '__' + a non-empty suffix.

    A host refuses to reuse a consumed task name, so a second probe after a fix needs a
    fresh one; the suffix follows the same `__suffix` convention a story's task name uses.
    A single underscore, an empty suffix or another prefix is not a probe. Both
    host_adapter.native_role and diagnostic() ask this one predicate."""
    name = str(name or '')
    return name == PROBE_TASK or (name.startswith(PROBE_TASK + '__') and len(name) > len(PROBE_TASK) + 2)


def diagnostic(event):
    ti = event.get('tool_input') or {}
    raw = (event.get('_qa_host') or {}).get('input') or ti
    return ti.get('prompt') == 'QA_FACTORY_CONTEXT_PROBE' or is_probe_task(raw.get('task_name'))


def stage(root, event, role, context, ticket):
    if len(context) > 100000:
        raise ValueError('Native context exceeds 100000 characters; reduce project slices instead of silently truncating')
    session = event.get('session_id')
    if not session or not event.get('tool_use_id'):
        raise ValueError('Native context requires host session and tool call identities')
    raw = (event.get('_qa_host') or {}).get('input') or {}
    # Every launch keeps its OWN packet, keyed by (session, raw task_name). One slot per
    # session could not tell a stale packet (a failed native launch emits no SubagentStart)
    # from a live one: replacing it handed a running child another story's context, and
    # refusing it blocked every later task of the session. A pending packet under the SAME
    # key is the same launch staged twice (two unnamed launches share the session-only key)
    # and is refused; nothing under another key is read or overwritten. The check stays
    # inside the lock and ahead of the write, so two concurrent stagings cannot both pass it.
    path = _slot(root, session, raw.get('task_name'))
    with EventStore(path.parent).lock():
        if path.is_file() and json.loads(path.read_text(encoding='utf-8')).get('status') == 'pending':
            raise StateConflict('A factory launch is awaiting SubagentStart; retry after it starts, do not replace it')
        atomic_json(path, {'status':'pending', 'role':role, 'context':context,
                          'session_id':session, 'tool_use_id':event['tool_use_id'],
                          'transcript_path':event.get('transcript_path'), 'task_id':ticket,
                          'task_name':raw.get('task_name'), 'diagnostic':diagnostic(event)})


def deliver(root, event):
    from host_adapter import native_role, context_output
    session = event.get('session_id')
    if not session or not event.get('agent_id') or not _folder(root).is_dir():
        return
    with EventStore(_folder(root)).lock():
        pending = [(path, data) for path, data in _session_packets(root, session)
                   if data.get('status') == 'pending']
        if not pending:
            return
        # Which launch is this child? Its own task name when the host exposes it, else its
        # role. A packet whose task_name is known and differs from the child's is never the
        # child's; when more than one packet could be, nothing is delivered and nothing
        # changes (a child that may belong to another launch gets no one's context).
        from host_dispatch import child_identity, record
        child_name = str(child_identity(event).get('task_path') or '').rsplit('/', 1)[-1]
        role = native_role(event.get('agent_type'))
        if child_name:
            chosen = [x for x in pending if x[1].get('task_name') == child_name]
            if not chosen:  # no launch of that name: only an unnamed one, and only of this role
                chosen = [x for x in pending if not x[1].get('task_name') and x[1].get('role') == role]
        else:
            chosen = [x for x in pending if x[1].get('role') == role]
        if len(chosen) > 1:
            # Never silent: a stale packet of a failed launch would otherwise starve every
            # later launch of this role with no trace. stderr only (stdout is the context
            # channel), names only (never the context), and the child's start is not blocked.
            import sys
            names = ', '.join(str(x[1].get('task_name') or '(no task name)') for x in chosen)
            print('FACTORY CONTEXT: several factory launches of ' + str(role) + ' are waiting in this host '
                  'session (' + names + ') and the host did not say which one this child belongs to, so no '
                  'context was delivered; relaunch the role under a unique task name.', file=sys.stderr)
        if len(chosen) != 1:
            return
        path, data = chosen[0]
        record({'hook_event_name':'PostToolUse', 'tool_name':'Agent',
                'session_id':data['session_id'], 'tool_use_id':data['tool_use_id'],
                'task_id':data.get('task_id'), 'transcript_path':data.get('transcript_path'),
                'tool_input':{'subagent_type':data['role']},
                '_qa_host':{'input':{'task_name':data.get('task_name')}},
                'tool_response':{'agent_id':event['agent_id'], 'task_name':data.get('task_name')}})
        text = data.pop('context', '')
        data.update(status='delivered', agent_id=event['agent_id'])
        atomic_json(path,data)  # the record keeps identities, not up to 100 KB of context
        context_output(event,text)


def main():
    from hooklib import read_event, project_root
    event = read_event() or {}
    if event.get('hook_event_name') == 'SubagentStart':
        deliver(project_root(event),event)


if __name__ == '__main__':
    main()
