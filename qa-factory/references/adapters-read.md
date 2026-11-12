# Adapters — reading a tracker and version control

How the factory READS a ticket system and version control. Writing to any external system
is a separate contract in `external-writes.md`, delivered to the role that proposes a write;
no role does both, so neither carries the other's half. Configuration lives in the project's
`qa-factory/config.json` under `adapters` (reachability).

## Ticket adapters

`scripts/ticket_adapter.py` is the one CLI every role uses to read a ticket — no role
calls a tracker's own API or CLI directly:

    ticket_adapter.py get <TICKET> [--json] [--ticket-file <path>] [--raw-dir <work/ticket-raw>]
                      [--output <snapshot.json>]
    ticket_adapter.py children <TICKET> [--json] [--ticket-file <path>]
    ticket_adapter.py diff --old <path> --new <path> [--json]
    ticket_adapter.py freshness <TICKET> --task-root <dir> [--ticket-file <path>] [--json]
                      [--adopt | --decline --words-file <file>]
    ticket_adapter.py --selftest

`get` returns the normalized schema below (`--json` for machine consumption; without it, a
short human-readable summary): `{key, type, status, title, description,
acceptance_criteria: [str], comments: [{author, date, text}], parent: str|None,
subtasks: [{key, status}], links: {merge_request, branch}}`; a direct tracker read adds
`attachments`, `revision`, `provenance` and `links.issue_links` / `links.remote_links`.
`--output <path>` writes the same bytes `--json` prints. `children` returns just the `subtasks` list. Exit codes: `0` success; `1` the adapter is reachable but
this ticket was not found; `3` the adapter is not configured, or normalization is not
implemented for this tracker's output shape — always with an actionable instruction on
stderr, never a crash; `5` the tracker stopped accepting the token, a redirect to another host
(single sign-on) included (one line names the variable to renew; see jira-direct-access.md); exit 5 with owner `intermediary` is the `ticket_read` question naming the protection, not a login stop.

Reading a Jira ticket is REST (`direct_api`) and nothing else: the tracker agent is a WRITE
channel only, never a data source. A tracker the factory holds no client for is read by the role through the route onboarding
recorded in `requirements_sources` and saved with `record-source`. A Jira read returns the light snapshot (the named custom
fields only; the whole answer is kept in the raw folder `--raw-dir` names), and a ticket handed
over as text (`--ticket-file`) is labelled `person_pasted`.

`config.json`'s `adapters.ticket` selects the adapter. The type key is read as `kind` or
`name` (both accepted — the shipped `templates/config.json` uses `name`):

| Adapter | Reaches | Config shape |
|---|---|---|
| `file` | a local markdown ticket file — fixtures, evals, projects with no tracker | `{"kind": "file", "path": "<dir containing <TICKET>.md>"}` |
| `jira` | Jira issues via the tracker API or a CLI | `{"kind": "jira", "direct_api": {...}}` (jira-direct-access.md) or `{"kind": "jira", "command": "<a CLI this session has> {key}"}` — a shape, not a default to copy |
| `ado` · `gitlab` · `github` | Azure DevOps work items, GitLab / GitHub issues | the same two shapes, with `kind` set to the adapter name |

### How the tracker is reached — `method`

The tracker's **name** (which system) and the **method** (how this session reaches it) are
two different facts, and the second is configuration, never inferred from a missing key:

| `method` | Extra key | Who can actually perform the read |
|---|---|---|
| `command` | `command` | `ticket_adapter.py` itself, shelling out |
| `mcp_tool` | `mcp_tool` | the orchestrator only — no role holds its session's tools (see below) |
| `agent` / `skill` | `invoke` | write channels only — a read command refuses it (see below) |
| `api` | `direct_api` | `ticket_adapter.py` itself, over the tracker's HTTP API — **the read route** |

A config written before `method` existed still works: the method is inferred from
`command` or `mcp_tool` when the key is absent. Inference is back-compat only — a project
reached through an assistant declares `method: "agent"`, it is not recognised by the
absence of a `command`.

### The read route is `adapters.ticket.direct_api`, and the role uses it itself

The role that collects sources at S1 is a subagent. It holds none of the orchestrator's
session tools, so a tracker reached through an MCP tool, an agent or a skill is reachable by
the orchestrator and by nobody else — and none of those three return attachment bytes, a
parent or a linked ticket anyway (TP1-15045: 51 lookups, none through an assistant).

So reading a Jira goes through `adapters.ticket.direct_api`, which `ticket_adapter.py` uses whatever
`method` says: `collect`, `peek`, `assess`, `inspect` and `refresh` are the role's own
commands (any other tracker: the recorded route, `collect <KEY> --relation task` recording only S0's snapshot). `method: agent|skill` is refused outright by every read command; `method: mcp_tool`
without a usable `direct_api` is rated `not_configured` by `readiness.py`, and the stage guard
refuses the S1 dispatch rather than let the role discover it empty-handed (TP2-2553:
S0's own fetch went green, S1 stalled, and 2 h 54 min went on hand-fetched tickets). The
person's word passes that refusal — `waiver.py --stage S1 --block "tracker route"` — and the
story then runs on what the configured route does reach. All three remain WRITE channels
(`external_writes.channels.<name>`).

### Freshness — a ticket moves while the story runs

A story spans two human gates. A description edited or an acceptance criterion dropped in
that window invalidates the register, the plan and the cases built on the old text — and
with any adapter, live or snapshot, nothing re-reads the ticket after S1 unless told to.

`ticket_adapter.py freshness <TICKET> --task-root <story folder>` reads the ticket now,
compares it with the story's snapshot and answers with a `severity`:

- **`requirements`** — `title`, `type`, `description` or `acceptance_criteria` moved. The
  plan was built on the old text: halt, the human decides whether S2-S3 re-run. The old
  snapshot stays and the new text waits as `work/ticket-snapshot.next.json` until
  `freshness --adopt` (the new text) or `--decline --words-file <file>` (the old text: their
  words are kept as a remark the next gate shows, and the same requirements are then
  reported as answered, not asked again, whatever else moved) after the person's answer.
- **`context`** — `status`, `comments`, `parent`, `subtasks`, `links` (issue and remote links
  included) or `attachments` moved. Say it and carry on; the snapshot is replaced.
- **`none`** — nothing moved.

The snapshot is `work/ticket-snapshot.json`: the stdout of `get <TICKET> --json` and nothing
else; on the skill path the orchestrator has `get --output` write those very bytes. It is taken once, at S0, and re-read only when the story **stood still**:
the last comparison (`checked_at` in `work/ticket-freshness.json`, else the snapshot's
`fetched_at`) is more than 6 hours old or unknown, or a new text waits unanswered. A run
proceeding normally re-reads nothing — a second fetch minutes after the first costs a
dispatch to produce a byte-identical file. On the skill path the orchestrator runs
`freshness`; the command journals `ticket_changed` itself, an unreachable tracker (exit 3) is
not a change, and the CALLER journals it as `ticket_unchecked`; a lost login (exit 5) is asked
of the person (exit 5 with owner `intermediary` is not a lost login: one line "ticket not checked: <what answered>; the story goes on with the text it was built on", journaled as `ticket_unchecked` like exit 3) and a fault of the factory (exit 4) is a finding, never `ticket_unchecked`; `diff --old <path> --new <path>` is
the same comparison on two files.

`file` is not a degraded mode: it is what `qa-story --ticket-file <path>` uses, what the
fixtures and evals run against, and the shape a ticket handed over as a file takes. The shape
is `evals/fixtures/tickets/QA-1.md`, annotated field by field in
`references/templates/ticket-snapshot.md`; `--ticket-file` reads that shape or a JSON
snapshot alike.

For `jira`/`ado`/`gitlab`/`github`: a `command` template has `{key}` replaced by the
ticket id, is run through the shell, and its stdout is parsed as JSON, then passed through
a per-adapter normalization hook. v0 ships that hook as a stub: it accepts output that *already* matches the schema above and otherwise
exits 3 with the raw JSON and the schema, asking the role to normalize it by hand rather
than guessing a tracker's real field names. When onboarding recorded an `mcp_tool` instead
of a `command` (no CLI to shell out to), the script cannot call it itself — it exits 3
naming the tool and asking the role to call it and normalize the result.

**`status: configured` means detected in THIS session** — a CLI that answers on PATH, a
connector's tools present, a named agent — never "the team said Jira". Onboarding probes
before it writes the word; `readiness.py` probes again and reports `missing` when a command
adapter's executable is gone, and `not_configured` for a tracker only the orchestrator's
session can reach. Neither is a failure; a declaration nobody verified reaching S0 as `ok`
is. A stage that needs an unconfigured adapter halts at S0 and names what to run, it does
not improvise.

## VCS

Version control (branch creation, commits, MR/PR) goes through the connector or CLI named
in onboarding (`glab`, `gh`, or an MCP tool set). Branch names, commit messages and MR
titles come from `git_conventions` in `config.json`, never from a scheme `qa-story` invents.

### The implementation cascade runs once per declared repository

The repositories are the ones `config.json` names — `code_repos[]` (each with a `name`, a
`path` and a `default_branch`) plus this one, the test repository. Nothing else is searched:
a repository nobody declared is a repository nobody can ground a story in.

Inventory all relevant MRs from both source and tested tickets, including links in comments
and attachments. Keep multiple MRs per repository in `context-manifest.implementations[]`
(`{repo, source, mr, branch, commit, diff_path}`), primary first; mirror the primary in
`implementation` for older readers. Stop redundant searches once this set is covered.
For repositories without known required MRs, search by ticket, then commits/local refs.
Authentication failure pauses that route; an authorized browser/connector may provide
equivalent complete MR evidence. A local diff alone is not equivalent.
The full collection and access contract is [scout recovery](scout-recovery.md).

Why per repository: on QA-EXAMPLE the change was a backend MR and a frontend MR. A rule
of "first hit wins, full stop" ends at the backend and leaves half the change ungrounded;
a free sweep of everything nearby is the marathon the rule was written against. Declared
repositories are the line between the two.

## Degradation

An adapter that is `not configured`, or a write that fails mid-run, never blocks the
factory's own artifacts: the local file stands on its own, and the external write is
reported as "not sent — <reason>" and becomes an `obligations.md` row, never a silent drop.

Required ticket/MR/attachment access failure blocks S1: immediately notify the orchestrator with the exact source, error and recovery action so it can notify the user. Preserve partial work. Poll timeouts and 30+ minute collection are not cancellation reasons; no duplicate scout while one is active.
