# External writes — proposing, never performing

How a proposed change reaches a tracker or a test-management system, and the contract that
keeps every role from writing to one directly — enforced since 0.3.0 by the PreToolUse
guard, which refuses a tracker write verb from any role's shell and names the proposal path
in its message. Reads are untouched. Reading a tracker is a separate document,
`adapters-read.md`. Configuration lives in the project's `qa-factory/config.json` under
`external_writes` (which channels are permitted to actually write) and `adapters`
(reachability).

## TMS adapters

`markdown` (the default) keeps cases and results as files: cases in `config.cases_root`
when the project keeps a case store, else with the story under
`qa-factory/artifacts/<TICKET>/work/test-cases/`. Nothing to configure. `xray`, `testrail` and `zephyr` go through the configured connector after Gate A for exact approved case descriptions; results follow
a separate Gate B action decision. Both use a preview and durable receipts.

Before a non-markdown TMS publication is handed to that executor, the controller prepares
the Gate-A-scoped, adapter-neutral manifest with `scripts/tms_publication.py prepare`. It
checks the approved case-content hash, full relevant pagination, remote revisions, and
idempotency receipts; `transport` emits a handoff only. This preparation does not write to
the TMS. Put each request idempotency key into proposal `publication_key`, copy `case_version`
and exact approved `fields`. `external_writes.py` validates those against the manifest
and recorded Gate A before invoking the configured adapter; bugs still require Gate B.

## Channels are chosen at onboarding, not guessed by a role

Two settings in `config.json`, set once at onboarding and read by every role that would
otherwise need to know which system to write to:

- `external_writes.bugs`: `markdown | jira` — where a found bug goes.
- `external_writes.cases`: `markdown | xray | testrail | zephyr` — where cases and results
  go.

No role knows the word "Jira" or "Xray" in its own logic; it knows "the bugs channel" and
"the cases channel", and reads the configured value.

## The write contract — proposal file, then a deterministic executor

**The model never writes to an external system.** Not a comment, not a status transition, not a
"just this once" update. What happens instead, always:

1. A role (`qa-bug-reporter`, `qa-doc-scribe`) writes the artifact to its **first-class
   local home** — a bug always gets `qa-factory/bugs/BUG-n.md` regardless of channel, and a
   case always gets `<area>/<case id>.md` in the store above. The local file is the source of
   truth; nothing overwrites it.
2. When the configured channel is not `markdown`, the same role additionally writes a
   **proposal file** under `artifacts/<TICKET>/work/proposals/`:
   - `bug-*.json`: `{"kind": "bug", "bug_file": "bugs/BUG-n.md", "action": "create"|
     "comment", "fields": {...}, "external_id": "<optional, required for comment>",
     "witness": {...}}`.
   - `case-*.json`: `{"kind": "case", "case_file": "test-cases/<area>/<case id>.md",
     "action": "create"|"update", "fields": {...}, "external_id": "<optional>",
     "witness": {...}}`.
3. After Gate A authorizes exact case publication, or Gate B authorizes another action, `scripts/external_writes.py <TICKET>` — a
   deterministic script, not a model — reads the proposals and performs the writes:
   idempotently (a proposal with a `result`, or a `create` whose target already has an
   `external_id`, is skipped), only within `config.external_writes.write_scopes` (default
   `["create_issue", "add_comment"]`; cases need `create_case`/`update_case`, absent from
   the default on purpose), and never overwriting text a human entered on the other side —
   the actions are `create` (once) and `comment`/`update` (append), never an in-place
   overwrite. Each performed write is journaled (`event: external_write`) and its
   `{external_id, url, at}` recorded into the proposal and the local artifact's front matter.
   How a channel is delivered is looked up in `config.external_writes`:
   `channels.<channel> = {"method": "command"|"agent"|"skill"|"api", "invoke": "<name>"}`,
   the one shape a new config is written with. `commands.<channel>` is **legacy, read-only**:
   the executor still honours a project onboarded with it (as method `command`), and
   `p4-generate.md` never writes it into a new config. A channel with none of these reports
   `NOT_CONFIGURED` per proposal and touches nothing.
   - Bugs execute only after the scoped Gate B action is approved. Cases default to `--preview` (prints `create`/`update`/`skip` per proposal,
     executes nothing); only `--yes` performs the write.

The executor validates the exact action independently of stage order. Gate A permits only
its approved case descriptions (`--phase after-a --yes`); Gate B permits its approved
results/bugs (`--phase after-b --yes`). A bare gate decision never authorizes another action.
The general delivery guard still protects MR delivery after Gate B.

### Agent-delivered channels — the courier, not the clerk

A tracker reachable only through a session agent cannot be shelled out to, and
`qa-bug-reporter` cannot dispatch one (`disallowedTools: Agent, Task`). The proposal file
**is** the bug reporter's hand-off; the orchestrator is the only courier available. For such
a channel `external_writes.py` does everything except the dispatch — validates the proposal,
enforces the scope and the gate, writes a `pending` marker, prints the payload, exits **4**
— and then:

1. the orchestrator dispatches the named agent once per proposal with that payload;
2. it comes back with `external_writes.py --record <proposal> --external-id <ID> [--url
   <URL>] [--remote-revision <REVISION>]`, which writes the `result`, clears `pending`, stamps the local artifact's front
   matter and journals `external_write`.

Every book stays inside the script, so an agent-delivered write is accounted for exactly
like a command-delivered one. The marker is written **before** the dispatch: a run
that resumes after a crash tells the agent to search for the issue and report its id rather
than create a second one. `--record` without an `--external-id` is refused — an agent that
cannot name what it created has created nothing we can account for.

### Direct-API channels — no command, no courier

`method: "api"` (also spelled `"direct"`/`"direct_api"`) is for a project with ONLY API
access to its tracker: `adapters.ticket.direct_api` and nothing else, no shell command and
no assistant that can create issues. `external_writes.py` needs neither a courier nor a
translator here — it POSTs the issue and the comment itself, through
`source_inventory.JiraClient.post_json`, after the same Gate B authorization every bug write
needs. The project comes from `external_writes.bugs_project`; a field the project's own
`createmeta` demands and the bug's fields do not set is named and refused BEFORE any request
is sent (`tracker_write.py`'s probe already read that list). One attempt, no retry: a
rejected write is reported per proposal with the tracker's own error text, the proposal file
is kept exactly as it was, and a re-run refuses to retry blindly until the outcome is
reconciled — the same rule a failed `command` delivery already keeps.

The author of a direct-API write is the token's owner, `adapters.ticket.direct_api.username_ref`
— never a role, never "the factory". `external_writes.py` prints one line naming it
before the first write of a run (`writing as <username_ref>: <display name>`) and
`gate_brief.py`'s Gate B brief carries one sentence, "bugs and comments will be written to
`<channel>` as `<display name>`", read off the same cached probe receipt
(`tracker_write.py`'s `/myself`) rather than a fresh call — a brief that opened a network
connection would not be a brief. Only the credential's env-var NAME and Jira's own display
name for it are ever printed; the token's value never is.

## Degradation

An adapter that is `not configured`, or a write that fails mid-run, never blocks the
factory's own artifacts: the local file stands on its own, and the external write is
reported as "not sent — <reason>" and becomes an `obligations.md` row, never a silent drop.

## Exact publication authorization and uncertainty

For controller-managed tasks record a `publish_cases` decision with the manifest content
hash and destination in addition to Gate A approval. Legacy pipeline imports store this
same record as `gates.A.publish_cases`; a bare plan approval is not enough for remote writes.
Bug/results actions at B similarly bind their proposal content hash. Case proposal fields
must equal the approved publication_fields; updates carry expected_remote_revision and
require an adapter declaring conditional_updates support. A timeout or missing remote ID
leaves a pending receipt and blocks blind retry. TMS preparation reads these receipts:
unknown revision/outcome requires reconciliation, not a new create.

For after-A publication, first run `tms_publication.py prepare <input.json> --task-root
<TASK_ROOT>` with the reviewed actions, complete paginated search evidence, current remote
versions and exact publication decision. Each `ready_for_transport` request becomes a case
proposal carrying `publication_key` from `idempotency_key`, action, case_version, exact
fields, resolved authoring case_file (never an immutable task snapshot), and existing remote
ID/revision for updates. Publication receipts and remote mappings do not mutate approved
CaseVersion bytes. `mapped_existing`
is a local reuse mapping only: never send it as create/update. No TMS adapter means an
explicit pending obligation; local case approval remains valid.

An agent-delivered after-A case receipt requires `--remote-revision` as well as its remote
ID. Publication mappings stay in the receipt; this action never stamps approved case text
or immutable snapshots. Unknown remote revision remains a reconciliation task.

Separate transport `channel` (for example `xray`) from concrete `destination` (project/suite).
Bind both in the publication decision and repeat destination in each proposal. The executor
passes it to the adapter. Update targets and expected remote revisions must match the
approved existing_case_refs exactly. Case channels support the same command/agent/skill
transport contract; a pending agent write emits reconciliation instructions, not a new create.
