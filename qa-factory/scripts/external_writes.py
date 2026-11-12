# -*- coding: utf-8 -*-
"""Deterministic executor of external writes — the model never writes to an external
system. A role (`qa-bug-reporter`, `qa-doc-scribe`) writes its artifact to its first-class
LOCAL home first (`bugs/BUG-n.md`, `test-cases/<area>/<case id>.md`) — that file is always the
source of truth, regardless of channel — and, only when the project's channel is not
`markdown`, an additional **proposal file** under `artifacts/<TICKET>/work/proposals/*.json`.
This script reads those proposal files and performs the actual write, after the matching scoped Gate A/B decision: idempotently, only within the write scopes onboarding permitted, and never
overwriting text a human already entered on the other side.

Run (via run-py.cmd):
    external_writes.py <TICKET>                # bugs: execute; cases: preview only
    external_writes.py <TICKET> --yes           # cases: actually execute (bugs unaffected)
    external_writes.py <TICKET> --preview       # explicit preview, never executes cases
    external_writes.py --record <proposal.json> --external-id <ID> [--url <URL>]
    external_writes.py --selftest

A channel can be delivered by a shell command, by a session agent/skill (a project whose
Jira is only reachable through an assistant), or — `method: "api"` — directly, through
`adapters.ticket.direct_api` (a project with ONLY API access, no command and no
assistant, whose CREATE_ISSUES right `tracker_write.py` already proved). For the agent/skill
case no script and no subagent can dispatch one, so this script does everything except the
dispatch: it validates the proposal, enforces the scope and gate, writes a `pending` marker,
prints the payload, and exits 4 ("N proposals need the session agent"). The orchestrator
carries the message and comes back with `--record`, which stamps the result, the journal and
the bug's front matter. The direct-API case needs no courier: this script creates the issue
and adds the comment itself, authored as `adapters.ticket.direct_api.username_ref` (printed
as that variable's NAME plus the display name Jira's `/myself` returns for it — never the
token). The model is the courier for the other two; the books stay here always.

Channels come from qa-factory/config.json's `external_writes` block:
    bugs:  markdown -> no external action, the file is primary (exit 0, explicit note).
           jira     -> execute artifacts/<T>/proposals/bug-*.json (see shape below).
           any other name -> delivered when `channels.<name>` names a command, an agent, or
           `method: "api"` (direct through adapters.ticket.direct_api); otherwise exit 5 with
           the refusal that names the ways out. Never a silent 0.
    cases: markdown -> no external action.
           xray | testrail | zephyr -> preview create/update/skip per
           artifacts/<T>/proposals/case-*.json; only --yes performs it (design section 10:
           "with a preview ... and an explicit yes"). Bugs need no --yes — a bug proposal is idempotent
           by construction (an existing external_id short-circuits a re-create), so it is
           safe to run unattended right after gate B; cases go through an explicit human
           yes because syncing a whole TMS run is the bigger, harder-to-undo action.

Proposal shapes (one JSON file per external write, written by a role, never by this
script):
    bug-*.json:  {"kind": "bug", "bug_file": "bugs/BUG-n.md", "action": "create"|"comment",
                  "fields": {...}, "external_id": "<optional, required for comment>",
                  "witness": {...}}
    case-*.json: {"kind": "case", "case_file": "test-cases/<area>/<case id>.md",
                  "action": "create"|"update", "fields": {...}, "external_id": "<optional>",
                  "witness": {...}}

Write scopes (config.external_writes.write_scopes, default when the key is absent:
["create_issue", "add_comment"]): action "create" needs scope "create_issue"; "comment"
needs "add_comment"; a case "create"/"update" needs "create_case"/"update_case" — absent
from the default on purpose, so a project that only turned on bug writes at onboarding
does not silently also start writing to a TMS.

The actual mutation is a generic templated command, config.external_writes.channels.<name>
`{"method": "command", "command": ...}` — or the legacy, read-only `external_writes.commands`
(a map channel-name -> command, e.g. {"jira": "dmtools jira-write"}), still honoured for
projects onboarded with it and never written into a new config.
No command configured for a channel -> NOT_CONFIGURED per proposal, printed
by name, never a crash (design section C4: "TMS adapters are interface-only and
not_configured"). The command is invoked as `<command...> <json-payload>`; its stdout is
parsed as JSON `{"external_id": ..., "url": ...}` on a best-effort basis — the exact
per-tracker contract is an onboarding-time detail out of scope for this build ("framework
only"). `method: "api"` needs none of that translation: it POSTs `/issue` (fields from the
proposal plus `project`/`issuetype`, the project from `external_writes.bugs_project`) or
`/issue/<id>/comment` through `source_inventory.JiraClient.post_json`, one attempt, no retry
— a failure is reported per proposal with the tracker's own error text and the proposal file
is left exactly as it was, so a repaired field or a fixed token is one plain re-run away.

Every performed write is journaled (event `external_write`) and recorded back into (a) the
proposal file itself (`result: {external_id, url, at}` — this IS the idempotency marker)
and (b) the local artifact's own front matter (`external_id`, `external_url`) so a human
looking at bugs/BUG-n.md alone sees where it lives externally.

Gate B's question about an undeliverable channel has three answers, and the third one is a
decision, not a failure : when a person has recorded "keep it local", this
script prints `deferred by decision` with their own words and the `obligations.md` rows the
unsent writes leave behind — never `NOT_CONFIGURED`, which describes the factory as broken
over a choice somebody made on purpose. After a delivery it prints the issues that now exist
with their links, because the answer to a numbered list of bugs is the list of issues it
produced, not exit code 0.

Refusal: a run before gate B has a recorded decision (`pipeline.json` `gates.B.decision`)
exits 2 without touching anything — `stage_guard` rule 4 enforces the same ordering
independently, this is the belt-and-suspenders half worn by the script itself.

`log_append.py`'s closed EVENTS vocabulary does not (yet) include `external_write`, even
though `references/artifact-contract.md` names it as a valid journal event and
`log_append.py`'s own CLI enforces `choices=` on `--event`. `log_append.py` is outside
this step's write scope, so this script imports log_append's
`build_record`/`write` functions directly — the actual journal writer and journal_path
resolution stay the single implementation in log_append.py, only its CLI-level validate()
is bypassed for this one event name. A follow-up step should add "external_write" to
log_append.py's EVENTS/FIELDS and this script should then go back to shelling out to it
like every other journal writer does.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from role_cli import epilog, run_guarded  # noqa: E402
import hooklib  # noqa: E402
import local_keys  # noqa: E402
import runtime_paths as RP  # noqa: E402
from hooklib import artifacts_dir, load_config, parse_frontmatter, state_dir  # noqa: E402

ACTION_SCOPE = {"create": "create_issue", "comment": "add_comment"}
CASE_ACTION_SCOPE = {"create": "create_case", "update": "update_case", "archive": "archive_case"}
DEFAULT_WRITE_SCOPES = ["create_issue", "add_comment"]
AGENT_METHODS = ("agent", "skill")
EXIT_NEEDS_AGENT = 4
# A configured channel this build cannot deliver. Non-zero on purpose: exit 0 read as
# "the writes went out" (0.7.7 review, the silent no-op of the unknown-channel branch).
EXIT_NO_ADAPTER = 5
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- small local-file helpers (front matter round-trip, proposal read/write) --------------

def strip_frontmatter(text: str) -> dict:
    return parse_frontmatter(text) or {}


def upsert_frontmatter(path: Path, updates: dict) -> None:
    """Adds/updates only the given keys; the rest of the file (front matter and body,
    both human-owned) is left exactly as written."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    fm = parse_frontmatter(text) or {}
    m = FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text
    fm.update({k: v for k, v in updates.items() if v is not None})
    header = "\n".join(f"{k}: {v}" for k, v in fm.items())
    new_text = f"---\n{header}\n---\n\n{body.lstrip(chr(10))}"
    path.write_text(new_text, encoding="utf-8")


def load_json(path: Path):
    """(data, error) — error is '' on success."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as e:
        return None, str(e)


def write_json(path: Path, data: dict) -> None:
    from event_store import atomic_json
    atomic_json(path, data)


def list_proposals(ticket: str, prefix: str) -> list:
    root = artifacts_dir(ticket)
    found = {}
    for directory in (root / "proposals", root / "work/proposals"):
        for path in hooklib.sorted_paths(directory.glob(f"{prefix}-*.json")):
            old = found.get(path.name)
            if old and old.read_bytes() != path.read_bytes():
                raise ValueError("conflicting legacy/canonical proposal: " + path.name)
            found[path.name] = path
    return [found[name] for name in sorted(found)]


# --- gate B ----------------------------------------------------------------------------------

def gate_b_decision(ticket: str) -> str:
    pipe_path = artifacts_dir(ticket) / "pipeline.json"
    try:
        pipe = json.loads(pipe_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(((pipe.get("gates") or {}).get("B") or {}).get("decision") or "").strip()


def closed_by_run(task_root) -> str:
    """Why this run may send nothing outward, or "" when it may (t-017 D3, B-003).

    The record is `pipeline.no_trace` and nothing else: written at S0 by `story_run.py
    --no-trace` or accepted on a resume by `stage_done.py --set no_trace=true`, and read HERE by
    every reader - the gate B filing line, both rehearsal checks, this executor - so that no two
    of them can disagree about whether the run is an experiment (P8, FR-53; a comparison run
    that filed a tracker comment on a real ticket is what the rule is for). Truthy closes: a
    pipeline that cannot be read, or that has no such key, closes nothing, and the way out of a
    wrongly closed run is `stage_done.py --set no_trace=false` (FR-40)."""
    pipeline, _ = load_json(Path(task_root) / "pipeline.json")
    if isinstance(pipeline, dict) and pipeline.get("no_trace"):
        return "it is an experiment that leaves no trace"
    return ""


def publication_allowed(ticket: str, proposal: dict, channel: str = "") -> bool:
    """Exact after-A case writes; other managed writes require a scoped B decision."""
    from event_store import content_hash
    root = artifacts_dir(ticket)
    pipeline, _ = load_json(root / "pipeline.json")
    pipeline = pipeline or {}
    gates = pipeline.get("gates", {})
    import contract as C

    def approved(gate):
        # One reader of the gate field: this copy knew `deliver_with_risk` and the
        # dashboard's knew `deliver_with_risks`, and neither knew what the other did.
        return C.gate_approved(pipeline, gate)
    controller, _ = load_json(root / "state/controller.json")
    if proposal.get("action") == "archive":
        if not approved("B") or not controller:
            return False
        from case_lifecycle import prepare_archive
        decision = (controller.get("decisions") or {}).get(proposal.get("lifecycle_decision_id"), {})
        try:
            expected = prepare_archive(proposal.get("lifecycle_action") or {}, decision,
                controller.get("source_revision"), {"archive": True, "conditional_updates": True},
                proposal.get("expected_remote_revision"))["proposal"]
        except (ValueError, KeyError, TypeError):
            return False
        immutable = {k:v for k,v in proposal.items() if k not in {"pending", "result"}}
        return expected == immutable and (not channel or channel == expected["channel"])
    if proposal.get("kind") == "case" and proposal.get("publication_key"):
        if not approved("A"):
            return False
        manifest, _ = load_json(C.artifact(root, "tms-publication-manifest.json"))
        if not isinstance(manifest, dict) or (channel and manifest.get("channel", manifest.get("destination")) != channel):
            return False
        request = next((r for r in manifest.get("requests", []) if r.get("idempotency_key") == proposal["publication_key"]), {})
        decisions = list((controller or {}).get("decisions", {}).values())
        if not controller:
            decisions = [gates.get("A", {}).get("publish_cases", {})]
        if not any(d.get("action") == "publish_cases" and d.get("status") == "approved"
                   and d.get("content_hash") == manifest.get("content_hash")
                   and d.get("destination") == manifest.get("destination")
                   and d.get("channel", d.get("destination")) == manifest.get("channel", manifest.get("destination"))
                   and (not controller or d.get("source_revision") == controller.get("source_revision"))
                   for d in decisions):
            return False
        destination = manifest.get("destination")
        if proposal.get("destination", manifest.get("channel", destination)) != destination:
            return False
        if proposal.get("action") == "update":
            refs = request.get("existing_case_refs") or []
            if not any(ref.get("id") == proposal.get("external_id") and ref.get("revision") == proposal.get("expected_remote_revision") for ref in refs):
                return False
        return bool(request and request.get("action") == proposal.get("action")
                    and request.get("case_version") == proposal.get("case_version")
                    and request.get("fields_hash") == content_hash(proposal.get("fields") or {})
                    and request.get("status") == "ready_for_transport")
    if not approved("B"):
        return False
    if controller and controller.get("source_revision"):
        action = "file_bug" if proposal.get("kind") == "bug" else "publish_results"
        return any(d.get("action") == action and d.get("status") == "approved"
                   and d.get("source_revision") == controller["source_revision"]
                   and d.get("content_hash") == content_hash({k:v for k,v in proposal.items() if k not in {"pending","result"}})
                   for d in controller.get("decisions", {}).values())
    return True


# --- journal (see module docstring: log_append.py's CLI cannot take this event yet) -------

def journal_external_write(ticket: str, notes: str, fields: dict) -> None:
    try:
        import log_append
        record = log_append.build_record({
            "event": "external_write", "task": ticket, "notes": notes, "fields": fields,
        })
        log_append.write([record])
    except Exception as e:
        print(f"WARN: could not journal external_write for {ticket}: {e}", file=sys.stderr)


# --- "keep it local": the third answer of gate B ----------------------------------------------

# The words a person uses for the third option of the gate B question :
# (a) set the delivery up now · (b) file it by hand and give me the id · (c) keep it local.
# `external write` is here because it is a BLOCK text, not a decision: `s8.md` told the
# orchestrator to record the third answer as `waiver.py --block "external write"`, and then
# "just leave them in the repo for now" matched nothing and the factory attempted the write
# the person had declined. The phase now says `--block "keep it local"`; this alternative
# keeps every story recorded the old way readable.
LOCAL_ONLY_RE = re.compile(
    r"\b(keep (it |them )?local|locally|local[- ]only|no tracker|don'?t file|do not file"
    r"|not to (the )?tracker|markdown only|external write)\b", re.IGNORECASE)


def local_only_decision(ticket: str) -> dict:
    """The person's recorded "keep it local", or {}.

    TP2-2534's lesson, the other way round: a channel that cannot deliver is not an
    error of the run. When a person has said the bugs stay in the repository, the executor
    reports `deferred by decision` with their own words — `NOT_CONFIGURED` would describe the
    factory as broken over a choice somebody made deliberately.

    Read, never written here: `waiver.py` records the words, this only recognises them."""
    pipeline, _ = load_json(artifacts_dir(ticket) / "pipeline.json")
    pipeline = pipeline or {}
    import contract
    # A revoked override is no word (`contract.live_stage_overrides`, GW1-1); `gate_waivers` are read as before.
    rows = [w for w in (pipeline.get("gate_waivers") or []) if isinstance(w, dict)] \
        + contract.live_stage_overrides(pipeline)
    for row in rows:
        words = " ".join(str(row.get("decision") or "").split())
        subject = " ".join(str(row.get("requirement") or row.get("match") or "").split())
        if not words or not LOCAL_ONLY_RE.search(words + " " + subject):
            continue
        stage = str(row.get("stage") or "")
        if stage and stage not in ("S8", "S9"):
            continue  # a "keep it local" about something else entirely
        return {"words": words, "by": row.get("by") or "human",
                "at": row.get("at") or "", "subject": subject}
    return {}


def next_obligation_id(root: Path) -> int:
    """The next free OB id across the whole shared ledger (the registry rule: append only)."""
    highest = 0
    for candidate in (root / "obligations.md", root / "state" / "obligations.md"):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for found in re.findall(r"\bOB-(\d+)\b", text):
            highest = max(highest, int(found))
    return highest + 1


def obligation_rows(ticket: str, proposals: list, words: str) -> list:
    """The `obligations.md` rows an undelivered write leaves behind — one per proposal.

    Printed, not appended: the ledger has many writers and one appender per stage (the scribe
    at S8), and two processes appending to the same table is how ids collide. The rows are
    ready to paste, ids and all."""
    root = state_dir()
    number = next_obligation_id(root)
    today = now_iso()[:10]
    rows = []
    for path in proposals:
        data, _ = load_json(path)
        data = data or {}
        artifact = str(data.get("bug_file") or data.get("case_file") or path.name)
        essence = ("File this externally once a write channel exists — it is recorded only in "
                   "this repository for now")
        rows.append(f"| OB-{number} | {essence} | {ticket} | external-writes | "
                    f"a tracker channel that can write is configured | {today} | "
                    f"{artifact} (proposal {path.name}); the person's words: \"{words[:80]}\" | open |")
        number += 1
    return rows


def print_created(ticket: str) -> None:
    """After a delivery: what now exists outside the factory, with its link.

    The person answered a numbered list of bugs; the answer to that answer is the list of
    issues it produced, not exit code 0."""
    created = []
    for prefix in ("bug", "case"):
        for path in list_proposals(ticket, prefix):
            data, _ = load_json(path)
            result = (data or {}).get("result") or {}
            if not result.get("external_id"):
                continue
            artifact = str((data or {}).get("bug_file") or (data or {}).get("case_file") or path.name)
            created.append((str(result["external_id"]), str(result.get("url") or ""), artifact))
    if not created:
        return
    print(f"CREATED {len(created)} item(s) in the tracker:")
    for external_id, url, artifact in created:
        print(f"  {external_id}  {url or '(no link reported)'}  <- {artifact}")


# --- the generic command executor -----------------------------------------------------------

def command_for(ew: dict, channel: str):
    cmd = (ew.get("commands") or {}).get(channel)
    if not cmd:
        return None
    return cmd  # a string ("dmtools jira-write") or a list — build_command handles both


def channel_delivery(ew: dict, channel: str) -> dict:
    """How this channel is actually written: `command` (this script shells out) or
    `agent`/`skill` (only the orchestrator can dispatch it).

    `external_writes.commands.<channel>` — the original shape — reads as method `command`,
    so a config written before `channels` existed keeps working untouched."""
    entry = (ew.get("channels") or {}).get(channel)
    if isinstance(entry, dict):
        method = str(entry.get("method") or "").strip().lower()
        invoke_name = str(entry.get("invoke") or "").strip()
        command = entry.get("command") or command_for(ew, channel)
        if not method:
            method = "command" if command else ("agent" if invoke_name else "none")
        return {"method": method, "command": command, "invoke": invoke_name}
    command = command_for(ew, channel)
    return {"method": "command" if command else "none", "command": command, "invoke": ""}


def build_command(template, payload: dict) -> list:
    parts = template if isinstance(template, list) else str(template).split()
    return list(parts) + [json.dumps(payload, ensure_ascii=False)]


def invoke(argv: list) -> subprocess.CompletedProcess:
    cmd = list(argv)
    if os.name == "nt" and str(cmd[0]).lower().endswith((".bat", ".cmd")):
        cmd = ["cmd", "/c"] + cmd
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)


# --- the direct-API delivery: adapters.ticket.direct_api, no command, no assistant ----------
# TP2-2534's mirror image: a project with ONLY API access to its tracker had a
# proven CREATE_ISSUES right (`tracker_write.py`) and nowhere for `external_writes.py` to send
# it — `command`/`agent`/`skill` were the only two ways out, and this project has neither. The
# bug stayed a markdown proposal forever. Mirrors tracker_write.DIRECT_METHODS as a literal,
# not an import: this module has no load-time dependency on tracker_write (which itself lazily
# imports THIS module's `channel_delivery`), and the two lists are each other's selftest.
DIRECT_METHODS = ("api", "direct", "direct_api")


def direct_client(cfg: dict):
    """The same Jira client `tracker_write.py` proved the CREATE_ISSUES right with —
    `client_from_config` is the one constructor, so a config error reads identically in the
    probe and here. A separate function so a test can monkeypatch it with a fake opener."""
    from source_inventory import client_from_config
    return client_from_config((cfg.get("adapters") or {}).get("ticket") or {})


def direct_api_whoami(cfg: dict) -> str:
    """`<username_ref>: <display name>` — the credential's env-var NAME (never its value) and
    the display name Jira's own `/myself` returns for the token behind it. This is the one
    line `run()` prints before a direct-API delivery and the sentence `gate_brief.py` carries
    at gate B; best-effort, since a person is entitled to know WHO is about to file on their
    behalf even when that one extra GET fails — it then falls back to the bare variable name."""
    try:
        client = direct_client(cfg)
    except Exception:
        return ""
    ref = client.username_ref or ""
    try:
        identity = client.get_json(f"/rest/api/{client.api_version}/myself")
    except Exception:
        return ref
    display = str(identity.get("displayName") or identity.get("name")
                  or identity.get("accountId") or "").strip()
    return f"{ref}: {display}" if display else ref


def _missing_required_fields(fields: dict) -> list:
    """The createmeta required-field list `tracker_write.py`'s probe already read, checked
    against THIS bug's fields before the write is attempted — so a mandatory project field
    nobody filled is named in the failure line instead of surfacing as a bare Jira 400."""
    try:
        import tracker_write
        from hooklib import project_root
        receipt = tracker_write.load_receipt(project_root())
    except Exception:
        return []
    required = receipt.get("required_fields") or []
    have = {str(k).strip().lower() for k in (fields or {})}
    return [str(name) for name in required if str(name).strip().lower() not in have]


def direct_api_execute(cfg: dict, action: str, payload: dict) -> tuple:
    """Create an issue or add a comment through `adapters.ticket.direct_api` — the same two
    actions a `command` channel performs, minus the subprocess. Returns `(result, error)`:
    `result` is `{"external_id", "url"}` on success, `error` is the tracker's own message
    (never a secret) on failure. One attempt — `JiraClient.post_json` does not retry, and
    neither does this function; a caller that gets `error` back reports it and stops, exactly
    the "never retried blindly" rule the `command` channel already keeps."""
    try:
        client = direct_client(cfg)
    except Exception as exc:
        return {}, f"direct API is not usable: {type(exc).__name__}: {exc}"
    from source_inventory import FetchError
    version = client.api_version
    fields = dict(payload.get("fields") or {})
    if action == "create":
        try:
            from tracker_write import bug_project
            project = bug_project(cfg)
        except Exception:
            project = ""
        if not project:
            return {}, ("no bug project is named — set external_writes.bugs_project (or "
                        "adapters.ticket.project_keys)")
        missing = _missing_required_fields(fields)
        if missing:
            return {}, (f"`{project}` requires: {', '.join(missing)} — not set on this "
                        "bug's fields (run qa-doctor to re-read createmeta)")
        issuetype = fields.pop("issuetype", None) or "Bug"
        priority = fields.pop("priority", None)
        body_fields = {"project": {"key": project},
                       "issuetype": {"name": issuetype} if isinstance(issuetype, str) else issuetype}
        if priority is not None:
            body_fields["priority"] = {"name": priority} if isinstance(priority, str) else priority
        body_fields.update(fields)
        try:
            out = client.post_json(f"/rest/api/{version}/issue", {"fields": body_fields})
        except FetchError as exc:
            return {}, str(exc)
        external_id = out.get("key") or out.get("id")
        if not external_id:
            return {}, "the tracker accepted the request but returned no issue key"
        return {"external_id": external_id, "url": f"{client.base_url}/browse/{external_id}"}, ""
    if action == "comment":
        target_id = payload.get("external_id")
        if not target_id:
            return {}, "comment needs an external_id (create the bug first)"
        body = ""
        for key in ("body", "comment", "text", "message"):
            value = fields.get(key)
            if isinstance(value, str) and value.strip():
                body = value
                break
        if not body:
            return {}, "comment proposal carries no body/comment/text field to send"
        try:
            client.post_json(
                f"/rest/api/{version}/issue/{urllib.parse.quote(str(target_id))}/comment",
                {"body": body})
        except FetchError as exc:
            return {}, str(exc)
        return {"external_id": target_id, "url": f"{client.base_url}/browse/{target_id}"}, ""
    return {}, f"direct API delivery does not support action {action!r}"


# --- bugs channel ----------------------------------------------------------------------------

def unknown_channel(kind: str, channel: str) -> str:
    """A channel this build has no adapter for is a refusal, not a quiet no-op.

    It used to print "not recognized — nothing executed" and exit 0, which reads to an
    orchestrator as "the writes are done" — the gate B rehearsal had already classed the
    same channel as `person_decides` (0.7.7 review, the S8 fork inventory). The two now say
    the same thing, and a person's word still passes it: `waiver.py --stage S8 --block
    "keep it local"` turns the whole question into a recorded decision."""
    return (f"NO_ADAPTER: {kind} channel '{channel}': no adapter in this build; keep local "
            f"(set external_writes.{kind} to \"markdown\") or configure "
            f"external_writes.channels.{channel} with a command or an agent. "
            "Nothing was executed.")


def _run_command_transport(path: Path, data: dict, payload: dict, command, target_id, status: list):
    """The command transport of a proposal, the one flow both channels share (B-309 t-422; a bug's and a case's copies were
    equal statement for statement): refuse a blind retry while an earlier command is still `pending`, put the idempotency key
    on the payload, mark `pending` BEFORE the command runs (at-least-once, as above), run it, read its one JSON answer.

    Returns `(out, external_id, url)` when the transport confirmed a remote id; None when it did not - the refusal or the
    failure is already in `status` and the caller returns. `data["pending"]` is left in place on every refusal after the
    marker is written, on purpose: a re-run rejects a blind retry until a human reconciles the outcome. The caller keeps
    what is its own (a bug's and a case's result and front-matter stamp)."""
    if (data.get("pending") or {}).get("method") == "command":
        status.append(("REJECT", path.name, "unknown prior transport outcome; reconcile remote ID before retry"))
        return None
    if data.get("publication_key") or data.get("lifecycle_key"):
        payload["idempotency_key"] = data.get("publication_key") or data["lifecycle_key"]
        payload["expected_remote_revision"] = data.get("expected_remote_revision")
    data["pending"] = {"method": "command", "at": now_iso(), "payload": payload}
    write_json(path, data)
    try:
        proc = invoke(build_command(command, payload))
    except Exception as e:
        status.append(("FAIL", path.name, f"command did not start: {e}"))
        return None
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-3:]
        status.append(("FAIL", path.name, f"command exited {proc.returncode} | {' | '.join(tail)}"))
        return None
    try:
        out = json.loads((proc.stdout or "").strip() or "{}")
    except Exception:
        out = {}
    external_id = out.get("external_id") or target_id
    url = out.get("url")
    if not external_id:
        status.append(("REJECT", path.name, "transport returned no confirmed remote ID; outcome unknown"))
        return None
    return out, external_id, url


def local_key_target(data: dict, target_id, action) -> str:
    """The refusal text when a proposal would address a LOCAL key (SS1-14), or "". No tracker holds `LOCAL-n`: a comment on it, or
    a parent that is it (on a create or an update; `action` is kept for the callers), would be posted to a ticket that is somebody else's or to none. The inputs read are the
    target id and `fields.parent` (a string or an object with `key`). A local key in a DESCRIPTION is a
    mention and passes. The ONE reader is `local_keys.is_local`: a real `LOCAL-7` with no text file and no mark passes."""
    def named_local(value) -> bool:     # the guard reads the SPELLING a tracker might accept: case and spaces do not hide a key
        return isinstance(value, str) and local_keys.is_local(value.strip().upper())

    if named_local(target_id):
        return (f"external_id {target_id} is a local key: no tracker holds it; a comment goes to the bug's own tracker id")
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    parent = fields.get("parent")
    parent = parent.get("key") if isinstance(parent, dict) else parent
    if named_local(parent):
        return (f"fields.parent {parent} is a local key: no tracker holds it; a parent is a ticket of the tracker the bug "
                "is filed in")
    return ""


def refuse_local_key(status: list, path: Path, data: dict, target_id, action) -> bool:
    """Append the REJECT row when the proposal addresses a local key; True when it did (the caller returns). One helper for the
    bug path and the case path (AR-15)."""
    text = local_key_target(data, target_id, action)
    if text:
        status.append(("REJECT", path.name, text))
    return bool(text)


def process_bug_proposal(path: Path, ticket: str, ew: dict, write_scopes: set,
                         status: list, channel: str = "jira", cfg: dict | None = None,
                         author: str = "") -> None:
    data, err = load_json(path)
    if err or not isinstance(data, dict):
        status.append(("REJECT", path.name, f"unreadable proposal: {err or 'not an object'}"))
        return
    if data.get("kind") != "bug":
        status.append(("REJECT", path.name, f"kind must be 'bug', got {data.get('kind')!r}"))
        return
    action = data.get("action")
    if action not in ACTION_SCOPE:
        status.append(("REJECT", path.name, f"action must be create|comment, got {action!r}"))
        return
    scope = ACTION_SCOPE[action]
    if scope not in write_scopes:
        status.append(("REJECT", path.name,
                       f"'{action}' needs write_scope '{scope}', not permitted "
                       f"(write_scopes: {sorted(write_scopes)})"))
        return
    bug_file_rel = data.get("bug_file")
    if not bug_file_rel:
        status.append(("REJECT", path.name, "missing 'bug_file'"))
        return
    bug_path = state_dir() / bug_file_rel
    if not bug_path.exists():
        status.append(("REJECT", path.name, f"bug_file not found: {bug_file_rel}"))
        return

    if data.get("result"):
        status.append(("SKIP", path.name, "already executed (result already recorded)"))
        return

    bug_fm = strip_frontmatter(bug_path.read_text(encoding="utf-8"))
    existing_id = bug_fm.get("external_id")
    if action == "create" and existing_id:
        status.append(("SKIP", path.name, f"bug already has external_id {existing_id}"))
        data["result"] = {"external_id": existing_id, "url": bug_fm.get("external_url"),
                          "at": now_iso()}
        write_json(path, data)
        return
    target_id = data.get("external_id") or existing_id
    if action == "comment" and not target_id:
        status.append(("REJECT", path.name, "comment needs an external_id (create the bug first)"))
        return
    if refuse_local_key(status, path, data, target_id, action):
        return

    delivery = channel_delivery(ew, channel)
    payload = {"action": action, "fields": data.get("fields") or {}}
    if target_id:
        payload["external_id"] = target_id

    if delivery["method"] in AGENT_METHODS:
        if not delivery["invoke"]:
            status.append(("NOT_CONFIGURED", path.name,
                           f"channel '{channel}' is delivered by an agent but "
                           f"external_writes.channels.{channel}.invoke is empty — run qa-onboarding"))
            return
        retry = data.get("pending") or {}
        # At-least-once is the honest description of a dispatch: the marker is written BEFORE
        # anyone hands the payload over, so a run that resumes after a crash tells the agent to
        # SEARCH for the issue instead of cheerfully creating a second one.
        data["pending"] = {"at": now_iso(), "method": delivery["method"],
                           "invoke": delivery["invoke"], "payload": payload}
        write_json(path, data)
        note = (f"dispatch {delivery['method']} '{delivery['invoke']}' with the payload below, "
                "then come back with --record")
        if retry:
            note += (f" — WARNING: an attempt was already marked pending at {retry.get('at')}; "
                     "tell the agent to search for this issue first and report the existing id "
                     "rather than creating a duplicate")
        status.append(("NEEDS_AGENT", path.name, note))
        print(f"PAYLOAD [{path.name}] {json.dumps(payload, ensure_ascii=False)}")
        print(f"RECORD  [{path.name}] external_writes.py --record \"{path}\" "
              "--external-id <ID> [--url <URL>]")
        return

    if delivery["method"] in DIRECT_METHODS:
        if (data.get("pending") or {}).get("method") == "direct_api":
            status.append(("REJECT", path.name,
                           "unknown prior transport outcome; reconcile remote ID before retry"))
            return
        data["pending"] = {"method": "direct_api", "at": now_iso(), "payload": payload}
        write_json(path, data)
        out, error = direct_api_execute(cfg or {}, action, payload)
        if error:
            # `pending` is left in place on purpose (see JiraClient.post_json): a re-run
            # rejects a blind retry above until a human reconciles the outcome, exactly like
            # a failed `command` delivery.
            status.append(("FAIL", path.name, error))
            return
        external_id = out.get("external_id") or target_id
        url = out.get("url")
        if not external_id:
            status.append(("REJECT", path.name,
                           "tracker accepted the request but returned no confirmed remote ID"))
            return
        data["result"] = {"external_id": external_id, "url": url, "at": now_iso(),
                          "delivered_by": author or "direct_api"}
        data.pop("pending", None)
        write_json(path, data)
        if action == "create" and external_id:
            upsert_frontmatter(bug_path, {"external_id": external_id, "external_url": url})
        journal_external_write(ticket, f"{action} -> {bug_path.name} ({external_id or 'n/a'})",
                               {"bug_file": bug_file_rel, "action": action})
        status.append(("OK", path.name, f"performed ({action}) -> {external_id or 'n/a'}"
                                        + (f" as {author}" if author else "")))
        return

    command = delivery["command"]
    if not command:
        status.append(("NOT_CONFIGURED", path.name,
                       "no delivery configured for channel 'jira' — set "
                       "external_writes.commands.jira or external_writes.channels.jira"))
        return
    sent = _run_command_transport(path, data, payload, command, target_id, status)
    if sent is None:
        return
    out, external_id, url = sent
    data["result"] = {"external_id": external_id, "url": url, "at": now_iso(),
                      "remote_revision": out.get("remote_revision")}
    data.pop("pending", None)
    write_json(path, data)
    if action == "create" and external_id:
        upsert_frontmatter(bug_path, {"external_id": external_id, "external_url": url})
    journal_external_write(ticket, f"{action} -> {bug_path.name} ({external_id or 'n/a'})",
                           {"bug_file": bug_file_rel, "action": action})
    status.append(("OK", path.name, f"performed ({action}) -> {external_id or 'n/a'}"))


# --- cases channel ---------------------------------------------------------------------------

def process_case_proposal(path: Path, ticket: str, ew: dict, channel: str, execute: bool,
                          write_scopes: set, status: list) -> None:
    data, err = load_json(path)
    if err or not isinstance(data, dict):
        status.append(("REJECT", path.name, f"unreadable proposal: {err or 'not an object'}"))
        return
    if data.get("kind") != "case":
        status.append(("REJECT", path.name, f"kind must be 'case', got {data.get('kind')!r}"))
        return
    action = data.get("action")
    if action not in CASE_ACTION_SCOPE:
        status.append(("REJECT", path.name, f"action must be create|update, got {action!r}"))
        return
    case_file_rel = data.get("case_file")
    if not case_file_rel:
        status.append(("REJECT", path.name, "missing 'case_file'"))
        return
    case_path = state_dir() / case_file_rel
    existing_id = None
    if case_path.exists():
        existing_id = strip_frontmatter(case_path.read_text(encoding="utf-8")).get("external_id")

    if data.get("result"):
        status.append(("SKIP", path.name, "already executed (result already recorded)"))
        return
    if action == "create" and existing_id:
        status.append(("SKIP", path.name, f"case already has external_id {existing_id}"))
        if execute:
            data["result"] = {"external_id": existing_id, "url": None, "at": now_iso()}
            write_json(path, data)
        return

    if not execute:
        status.append(("PREVIEW", path.name, f"would {action} (channel={channel})"))
        return

    scope = CASE_ACTION_SCOPE[action]
    if scope not in write_scopes:
        status.append(("REJECT", path.name,
                       f"'{action}' needs write_scope '{scope}', not permitted "
                       f"(write_scopes: {sorted(write_scopes)})"))
        return
    if (data.get("publication_key") and action == "update") or action == "archive":
        capability = (ew.get("channels") or {}).get(channel, {})
        if (not capability.get("conditional_updates") or not data.get("expected_remote_revision")
                or (action == "archive" and not capability.get("archive"))):
            status.append(("REJECT", path.name, "adapter conditional update/revision required to preserve human edits"))
            return
    delivery = channel_delivery(ew, channel)
    command = delivery["command"]
    target_id = data.get("external_id") or existing_id
    if refuse_local_key(status, path, data, target_id, action):
        return
    payload = {"action": action, "fields": data.get("fields") or {},
               "destination": data.get("destination") or channel}
    if target_id:
        payload["external_id"] = target_id
    if data.get("publication_key") or data.get("lifecycle_key"):
        payload["idempotency_key"] = data.get("publication_key") or data["lifecycle_key"]
        payload["expected_remote_revision"] = data.get("expected_remote_revision")
    if delivery["method"] in AGENT_METHODS:
        if not delivery["invoke"]:
            status.append(("NOT_CONFIGURED", path.name, "case channel needs an invoke target"))
            return
        if data.get("pending"):
            status.append(("NEEDS_AGENT", path.name, "reconcile the existing pending remote case; do not create again"))
            print(f"RECONCILE [{path.name}] {json.dumps(data['pending'].get('payload', {}), ensure_ascii=False)}")
            return
        data["pending"] = {"at": now_iso(), "method": delivery["method"], "invoke": delivery["invoke"], "payload": payload}
        write_json(path, data)
        status.append(("NEEDS_AGENT", path.name, f"dispatch {delivery['invoke']} once; record confirmed ID and revision"))
        print(f"PAYLOAD [{path.name}] {json.dumps(payload, ensure_ascii=False)}")
        return
    if not command:
        status.append(("NOT_CONFIGURED", path.name, f"no transport configured for channel '{channel}'"))
        return
    sent = _run_command_transport(path, data, payload, command, target_id, status)
    if sent is None:
        return
    out, external_id, url = sent
    if data.get("lifecycle_key") and not out.get("remote_revision"):
        status.append(("REJECT", path.name, "archive remote outcome unknown; revision required"))
        return
    data["result"] = {"external_id": external_id, "url": url, "at": now_iso(),
                      "remote_revision": out.get("remote_revision")}
    data.pop("pending", None)
    write_json(path, data)
    if external_id and case_path.exists() and not data.get("publication_key") and not data.get("lifecycle_key"):
        upsert_frontmatter(case_path, {"external_id": external_id, "external_url": url})
    journal_external_write(ticket, f"{action} -> {case_path.name} ({external_id or 'n/a'})",
                           {"case_file": case_file_rel, "action": action})
    status.append(("OK", path.name, f"performed ({action}) -> {external_id or 'n/a'}"))


# --- orchestration -----------------------------------------------------------------------------

def record_result(proposal_path: Path, external_id: str, url: str, remote_revision: str = "") -> int:
    """The second half of an agent-delivered write. The orchestrator carried the message; the
    bookkeeping — idempotency marker, journal line, front-matter stamp on the local artifact —
    never leaves this script, so an agent-delivered write is accounted for exactly like a
    command-delivered one."""
    data, err = load_json(proposal_path)
    if err or not isinstance(data, dict):
        print(f"REJECT: unreadable proposal {proposal_path}: {err or 'not an object'}",
              file=sys.stderr)
        return 1
    try:
        ticket = next(parent.name for parent in proposal_path.resolve().parents
                      if (parent / "pipeline.json").is_file())
    except Exception:
        from role_cli import refuse
        return refuse("external_writes.py --record",
                      f"{proposal_path} is not inside a story: no pipeline.json in any parent, "
                      "so the ticket this proposal belongs to cannot be derived")
    if not publication_allowed(ticket, data):
        print(f"REFUSED: no current action-scoped authorization for {ticket}")
        return 2
    if data.get("result"):
        print(f"SKIP [{proposal_path.name}]: already recorded "
              f"({data['result'].get('external_id')})")
        return 0
    if not external_id:
        print("REJECT: --external-id is required — an agent that cannot name the id it "
              "created has not created anything we can account for", file=sys.stderr)
        return 1

    if (data.get("publication_key") or data.get("lifecycle_key")) and not remote_revision:
        print("REJECT: a published case receipt needs --remote-revision; reconcile unknown outcome")
        return 1
    kind = data.get("kind")
    artifact_key = "bug_file" if kind == "bug" else "case_file"
    rel = data.get(artifact_key)
    data["result"] = {"external_id": external_id, "url": url or None, "at": now_iso(),
                      "delivered_by": (data.get("pending") or {}).get("invoke") or "agent",
                      "remote_revision": remote_revision or None}
    data.pop("pending", None)
    write_json(proposal_path, data)
    if rel:
        artifact_path = state_dir() / rel
        if artifact_path.exists() and data.get("action") in ("create", "update") and not data.get("publication_key"):
            upsert_frontmatter(artifact_path, {"external_id": external_id, "external_url": url})
    journal_external_write(ticket, f"{data.get('action')} -> {rel or proposal_path.name} "
                                   f"({external_id})",
                           {artifact_key: rel, "action": data.get("action")})
    print(f"OK [{proposal_path.name}]: recorded {external_id}"
          + (f" — {url}" if url else " (no link reported)"))
    return 0


def run(ticket: str, cfg: dict, yes: bool, preview: bool, phase: str = "auto") -> int:
    # INVARIANT (t-017 D3): the closed state is read BEFORE the gate check and before any channel
    # code, so no path below - a command, the direct API, a session agent's payload - is
    # reachable in an experiment, whatever the gate says. Exit 0: nothing was asked of the
    # executor that it left undone, and "nothing is sent" is the run's complete result (FR-23).
    closed = closed_by_run(artifacts_dir(ticket))
    if closed:
        print("external writes: closed for this run (experiment) — nothing is sent")
        return 0
    pipeline, _ = load_json(artifacts_dir(ticket) / "pipeline.json")
    if not pipeline or not pipeline.get("gates"):
        print(f"REFUSED: no gate decision recorded for {ticket}")
        return 2

    ew = cfg.get("external_writes", {}) or {}
    bugs_channel = str(ew.get("bugs", "markdown") or "markdown")
    cases_channel = str(ew.get("cases", "markdown") or "markdown")
    raw_scopes = ew.get("write_scopes")
    write_scopes = set(raw_scopes) if raw_scopes is not None else set(DEFAULT_WRITE_SCOPES)

    status: list = []
    unadapted: list = []

    kept_local = local_only_decision(ticket) if bugs_channel not in ("", "markdown") else {}

    if phase == "after-a":
        print("bugs channel: deferred to Gate B")
    elif bugs_channel == "markdown":
        print("bugs channel: markdown — file is primary, nothing to execute")
    elif kept_local:
        # The third answer of the gate B question. Not a failure and not a gap in the factory:
        # a recorded choice, reported in the person's own words, with the tail written down.
        proposals = list_proposals(ticket, "bug")
        print(f'bugs channel: deferred by decision — "{kept_local["words"]}" '
              f"({kept_local.get('by') or 'human'})")
        for p in proposals:
            status.append(("DEFERRED", p.name, "deferred by decision — the bug file in this "
                                               "repository is the record"))
        rows = obligation_rows(ticket, proposals, kept_local["words"])
        if rows:
            print("OBLIGATIONS — append these rows to qa-factory/obligations.md, so an unsent "
                  "write is a debt with a trigger and never a silent drop:")
            for row in rows:
                print("  " + row)
    elif bugs_channel == "jira" or channel_delivery(ew, bugs_channel)["method"] != "none":
        bug_proposals = list_proposals(ticket, "bug")
        author = ""
        if bug_proposals and channel_delivery(ew, bugs_channel)["method"] in DIRECT_METHODS:
            # One question, once per run — never per proposal: the person is entitled to know
            # WHO is about to file on their behalf, not to be told it N times.
            author = direct_api_whoami(cfg)
            if author:
                print(f"bugs channel: direct API — writing as {author}")
        for p in bug_proposals:
            data, _ = load_json(p)
            if not publication_allowed(ticket, data or {}):
                status.append(("REJECT", p.name, "current scoped Gate B authorization required"))
                continue
            process_bug_proposal(p, ticket, ew, write_scopes, status, bugs_channel, cfg, author)
    else:
        unadapted.append(unknown_channel("bugs", bugs_channel))

    if cases_channel == "markdown":
        print("cases channel: markdown — file is primary, nothing to execute")
    elif cases_channel in ("xray", "testrail", "zephyr"):
        execute = bool(yes) and not preview
        case_proposals = list_proposals(ticket, "case")
        for p in case_proposals:
            data, _ = load_json(p)
            if phase == "after-a" and not (data or {}).get("publication_key"):
                continue
            if phase == "after-b" and (data or {}).get("publication_key"):
                continue
            if not publication_allowed(ticket, data or {}, cases_channel):
                status.append(("REJECT", p.name, "exact case publication authorization required"))
                continue
            process_case_proposal(p, ticket, ew, cases_channel, execute, write_scopes, status)
        if not execute and case_proposals:
            print("cases: preview only — pass --yes to execute")
    else:
        unadapted.append(unknown_channel("cases", cases_channel))

    for label, name, detail in status:
        print(f"{label} [{name}]: {detail}")
    print_created(ticket)

    if unadapted:
        for line in unadapted:
            print(line)
        return EXIT_NO_ADAPTER
    bad = sum(1 for s, _, _ in status if s in ("REJECT", "FAIL"))
    if bad:
        return 1
    needs_agent = sum(1 for s, _, _ in status if s == "NEEDS_AGENT")
    if needs_agent:
        print(f"{needs_agent} proposal(s) need the session agent — dispatch each payload above "
              "and record every result before this ticket's external writes are complete")
        return EXIT_NEEDS_AGENT
    return 0


# --- selftest ------------------------------------------------------------------------------------

def _use_project(root: Path) -> None:
    """Pin the throwaway project, cache and env var both (hooklib.pin_project_root): clearing
    the cache alone left the walk from cwd to answer, and from a cwd inside a real project
    that walk found the user's stories (`FileNotFoundError calls.log`, macOS 0.7.11)."""
    hooklib.pin_project_root(root)
    print(f"SELFTEST ROOT: {hooklib.project_root()}")


def selftest() -> int:
    """Mandatory scenarios (this step's done-check): the markdown no-op, the refusal
    before gate B, the idempotent skip (running twice does not double-write), and the
    write-scope refusal. A python stub stands in for the tracker CLI — no real mutation,
    argv is only written to a log file."""
    import io
    from contextlib import redirect_stdout

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="external-writes-selftest-") as td, \
            hooklib.selftest_root_restored():
        tdp = Path(td)
        proj = tdp / "project"
        (proj / "qa-factory" / "bugs").mkdir(parents=True)
        # The marker that makes this a project: hooklib resolves the root by it, and the
        # journal writer refuses a root without it rather than creating a state tree.
        (proj / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        calls_log = tdp / "calls.log"
        stub = tdp / "stub_tool.py"
        stub.write_text(
            "import sys, json\n"
            f"open({json.dumps(str(calls_log))}, 'a', encoding='utf-8').write(sys.argv[1] + chr(10))\n"
            "print(json.dumps({'external_id': 'JIRA-100', 'url': 'http://tracker.example/JIRA-100'}))\n",
            encoding="utf-8",
        )
        stub_cmd = [sys.executable, str(stub)]

        def make_ticket(ticket: str, gate_b: bool) -> None:
            art = proj / "qa-factory" / "artifacts" / ticket
            (art / "proposals").mkdir(parents=True)
            pipeline = {"ticket": ticket, "gates": ({"B": {"decision": "approve"}} if gate_b else {})}
            (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

        # --- 1. markdown no-op -------------------------------------------------------------
        make_ticket("QATF-MD", gate_b=True)
        cfg_md = {"external_writes": {"bugs": "markdown", "cases": "markdown"}}
        _use_project(proj)
        rc = run("QATF-MD", cfg_md, yes=False, preview=False)
        check("markdown: exit 0", rc == 0)
        journal_path = RP.record_new(proj, "journal.jsonl")
        check("markdown: no journal written", not journal_path.exists())

        # --- 2. refusal before gate B --------------------------------------------------------
        make_ticket("QATF-GATE", gate_b=False)
        cfg_jira = {"external_writes": {
            "bugs": "jira", "cases": "markdown",
            "write_scopes": ["create_issue", "add_comment"],
            "commands": {"jira": stub_cmd},
        }}
        rc = run("QATF-GATE", cfg_jira, yes=False, preview=False)
        check("no gate B decision: exit 2", rc == 2)
        check("no gate B decision: stub not invoked", not calls_log.exists())

        # --- 3. jira create, then idempotent skip on re-run ----------------------------------
        make_ticket("QATF-JIRA", gate_b=True)
        bug_path = proj / "qa-factory" / "bugs" / "BUG-1.md"
        bug_path.write_text("# BUG-1\n\nTags: a sixth tag is silently accepted.\n", encoding="utf-8")
        proposal_path = proj / "qa-factory" / "artifacts" / "QATF-JIRA" / "proposals" / "bug-1.json"
        write_json(proposal_path, {"kind": "bug", "bug_file": "bugs/BUG-1.md", "action": "create",
                                   "fields": {"summary": "sixth tag accepted"},
                                   "witness": {"note": "repro in run-report"}})
        rc = run("QATF-JIRA", cfg_jira, yes=False, preview=False)
        check("jira create: exit 0", rc == 0)
        check("jira create: stub invoked once", calls_log.exists()
              and len(calls_log.read_text(encoding="utf-8").splitlines()) == 1)
        bug_fm_after = strip_frontmatter(bug_path.read_text(encoding="utf-8"))
        check("jira create: bug front matter got external_id",
              bug_fm_after.get("external_id") == "JIRA-100")
        proposal_after, _ = load_json(proposal_path)
        check("jira create: proposal recorded a result",
              bool(proposal_after and proposal_after.get("result", {}).get("external_id") == "JIRA-100"))
        check("jira create: journal has an external_write event", journal_path.exists()
              and any(json.loads(line).get("event") == "external_write"
                      for line in journal_path.read_text(encoding="utf-8").splitlines()
                      if line.strip()))

        # re-run: idempotent skip, stub is not invoked a second time
        rc = run("QATF-JIRA", cfg_jira, yes=False, preview=False)
        check("jira re-run: exit 0", rc == 0)
        check("jira re-run: stub still invoked only once",
              len(calls_log.read_text(encoding="utf-8").splitlines()) == 1)

        # --- 4. write-scope refusal -----------------------------------------------------------
        make_ticket("QATF-SCOPE", gate_b=True)
        cfg_narrow = {"external_writes": {
            "bugs": "jira", "cases": "markdown",
            "write_scopes": ["add_comment"],  # create_issue NOT permitted
            "commands": {"jira": stub_cmd},
        }}
        bug_path2 = proj / "qa-factory" / "bugs" / "BUG-2.md"
        bug_path2.write_text("# BUG-2\n\nAnother bug.\n", encoding="utf-8")
        proposal_path2 = (proj / "qa-factory" / "artifacts" / "QATF-SCOPE" / "proposals"
                          / "bug-1.json")
        write_json(proposal_path2, {"kind": "bug", "bug_file": "bugs/BUG-2.md", "action": "create",
                                    "fields": {"summary": "x"}, "witness": {}})
        calls_before = len(calls_log.read_text(encoding="utf-8").splitlines())
        rc = run("QATF-SCOPE", cfg_narrow, yes=False, preview=False)
        check("write-scope refusal: exit 1", rc == 1)
        check("write-scope refusal: stub not invoked again",
              len(calls_log.read_text(encoding="utf-8").splitlines()) == calls_before)

        # --- 4b. an experiment (t-017 D3): the same approved jira bug, and nothing is sent ------
        make_ticket("QATF-NOTRACE", gate_b=True)
        art_nt = proj / "qa-factory" / "artifacts" / "QATF-NOTRACE"
        write_json(art_nt / "pipeline.json", {"ticket": "QATF-NOTRACE", "no_trace": True,
                                              "gates": {"B": {"decision": "approve"}}})
        write_json(art_nt / "proposals" / "bug-1.json",
                   {"kind": "bug", "bug_file": "bugs/BUG-2.md", "action": "create",
                    "fields": {"summary": "x"}, "witness": {}})
        calls_before = len(calls_log.read_text(encoding="utf-8").splitlines())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run("QATF-NOTRACE", cfg_jira, yes=False, preview=False)
        check("no-trace run: exit 0", rc == 0)
        check("no-trace run: says it is closed", "closed for this run" in buf.getvalue())
        check("no-trace run: stub not invoked", len(calls_log.read_text(encoding="utf-8").splitlines()) == calls_before)
        check("closed_by_run: a pipeline without the key closes nothing",
              closed_by_run(proj / "qa-factory" / "artifacts" / "QATF-JIRA") == "")
        check("closed_by_run: no pipeline at all closes nothing", closed_by_run(tdp / "absent") == "")

        # --- 5. an agent-delivered channel: the script does everything but the dispatch -------
        make_ticket("QATF-AGENT", gate_b=True)
        cfg_agent = {"external_writes": {
            "bugs": "jira", "cases": "markdown",
            "write_scopes": ["create_issue", "add_comment"],
            "channels": {"jira": {"method": "agent", "invoke": "jira-assistant"}},
        }}
        bug_path3 = proj / "qa-factory" / "bugs" / "BUG-3.md"
        bug_path3.write_text("# BUG-3\n\nA bug on a project whose Jira is an assistant.\n",
                             encoding="utf-8")
        proposal_path3 = (proj / "qa-factory" / "artifacts" / "QATF-AGENT" / "proposals"
                          / "bug-1.json")
        write_json(proposal_path3, {"kind": "bug", "bug_file": "bugs/BUG-3.md", "action": "create",
                                    "fields": {"summary": "assistant-delivered"}, "witness": {}})
        calls_before = len(calls_log.read_text(encoding="utf-8").splitlines())
        rc = run("QATF-AGENT", cfg_agent, yes=False, preview=False)
        check("agent channel: exit 4 (needs the session agent)", rc == EXIT_NEEDS_AGENT)
        check("agent channel: no command was shelled out to",
              len(calls_log.read_text(encoding="utf-8").splitlines()) == calls_before)
        pend, _ = load_json(proposal_path3)
        check("agent channel: a pending marker was written before any dispatch",
              bool(pend and pend.get("pending", {}).get("invoke") == "jira-assistant"))
        check("agent channel: nothing was recorded as a result yet",
              bool(pend) and not pend.get("result"))

        # a second run before the orchestrator came back: still pending, and it says so
        rc = run("QATF-AGENT", cfg_agent, yes=False, preview=False)
        check("agent channel re-run: still exit 4", rc == EXIT_NEEDS_AGENT)

        # --record closes the loop: result, journal, front matter — all inside the script
        jr_before = len([1 for line in (journal_path.read_text(encoding="utf-8").splitlines()
                                        if journal_path.exists() else []) if line.strip()])
        rc = record_result(proposal_path3, "TP1-7788", "http://tracker.example/TP1-7788")
        check("--record: exit 0", rc == 0)
        done, _ = load_json(proposal_path3)
        check("--record: the result is on the proposal",
              bool(done) and done.get("result", {}).get("external_id") == "TP1-7788")
        check("--record: the pending marker is gone", bool(done) and "pending" not in done)
        check("--record: the result names who delivered it",
              bool(done) and done.get("result", {}).get("delivered_by") == "jira-assistant")
        fm3 = strip_frontmatter(bug_path3.read_text(encoding="utf-8"))
        check("--record: the bug front matter was stamped",
              fm3.get("external_id") == "TP1-7788")
        jr_after = len([line for line in journal_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()])
        check("--record: one external_write event was journaled", jr_after == jr_before + 1)

        # recording twice is a no-op, exactly like a command-delivered re-run
        rc = record_result(proposal_path3, "TP1-7788", "")
        check("--record twice: exit 0 and skipped", rc == 0)
        jr_again = len([line for line in journal_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()])
        check("--record twice: no second journal line", jr_again == jr_after)

        # and the whole ticket is complete now: nothing left needing the agent
        rc = run("QATF-AGENT", cfg_agent, yes=False, preview=False)
        check("agent channel after --record: exit 0", rc == 0)

        # an agent channel with no name to dispatch is not configured, not a crash
        make_ticket("QATF-NONAME", gate_b=True)
        cfg_noname = {"external_writes": {
            "bugs": "jira", "cases": "markdown",
            "channels": {"jira": {"method": "agent", "invoke": ""}},
        }}
        # a FRESH bug file: an already-stamped one would short-circuit before the branch we test
        (proj / "qa-factory" / "bugs" / "BUG-4.md").write_text(
            "# BUG-4" + chr(10) * 2 + "Unsent." + chr(10), encoding="utf-8")
        noname_proposal = (proj / "qa-factory" / "artifacts" / "QATF-NONAME" / "proposals"
                           / "bug-1.json")
        write_json(noname_proposal, {"kind": "bug", "bug_file": "bugs/BUG-4.md",
                                     "action": "create", "fields": {}, "witness": {}})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run("QATF-NONAME", cfg_noname, yes=False, preview=False)
        out = buf.getvalue()
        check("agent channel with no invoke: exit 0, never a crash", rc == 0)
        check("agent channel with no invoke: reported NOT_CONFIGURED by name",
              "NOT_CONFIGURED" in out and "invoke is empty" in out)
        left, _ = load_json(noname_proposal)
        check("agent channel with no invoke: no pending marker was written",
              bool(left) and "pending" not in left)

        # a channel this build has no adapter for: a refusal with a way out, never a no-op
        make_ticket("QATF-NOADAPTER", gate_b=True)
        cfg_unknown = {"external_writes": {"bugs": "azure-boards", "cases": "markdown"}}
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run("QATF-NOADAPTER", cfg_unknown, yes=False, preview=False)
        out = buf.getvalue()
        check("unknown channel: exit 5, not a silent 0", rc == EXIT_NO_ADAPTER)
        check("unknown channel: named, with both ways out",
              "azure-boards" in out and "markdown" in out and "channels.azure-boards" in out)
        check("unknown channel: nothing was executed", "Nothing was executed." in out)
        cfg_configured = {"external_writes": {
            "bugs": "azure-boards", "cases": "markdown",
            "channels": {"azure-boards": {"method": "agent", "invoke": "boards-assistant"}}}}
        (proj / "qa-factory" / "bugs" / "BUG-5.md").write_text(
            "# BUG-5" + chr(10) * 2 + "Unsent." + chr(10), encoding="utf-8")
        write_json(proj / "qa-factory" / "artifacts" / "QATF-NOADAPTER" / "proposals" / "bug-1.json",
                   {"kind": "bug", "bug_file": "bugs/BUG-5.md", "action": "create",
                    "fields": {}, "witness": {}})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run("QATF-NOADAPTER", cfg_configured, yes=False, preview=False)
        check("a configured channel of any name is delivered, not refused",
              rc == EXIT_NEEDS_AGENT and "boards-assistant" in buf.getvalue())

        # --- 6. direct API: create, comment, a rejected write, and the idempotent re-run ----
        # A project with ONLY API access to its tracker — no command, no assistant.
        class _FakeDirectClient:
            def __init__(self, routes):
                self.routes = routes
                self.calls = []
                self.username_ref = "QA_JIRA_TOKEN"
                self.base_url = "https://tracker.example"
                self.api_version = "2"

            def _answer(self, verb, path, body=None):
                self.calls.append((verb, path, body))
                for fragment, payload in self.routes.items():
                    if fragment in path:
                        if isinstance(payload, Exception):
                            raise payload
                        return payload
                raise AssertionError(f"unstubbed {verb} {path}")

            def get_json(self, path):
                return self._answer("GET", path)

            def post_json(self, path, body):
                return self._answer("POST", path, body)

        from source_inventory import FetchError
        fake_client = _FakeDirectClient({
            "myself": {"displayName": "Jane Reviewer"},
            # "/comment" checked before "/issue": a comment URL
            # (.../issue/JIRA-77/comment) contains BOTH fragments, and the more specific
            # route must win or every comment would be misrouted to the create-issue reply.
            "/comment": {"id": "9"},
            "/issue": {"key": "JIRA-77"},
        })
        held_direct_client = direct_client
        globals()["direct_client"] = lambda cfg: fake_client
        try:
            make_ticket("QATF-DIRECT", gate_b=True)
            cfg_direct = {"external_writes": {
                "bugs": "jira", "cases": "markdown", "bugs_project": "QATF",
                "write_scopes": ["create_issue", "add_comment"],
                "channels": {"jira": {"method": "api"}}}}
            bug_path6 = proj / "qa-factory" / "bugs" / "BUG-6.md"
            bug_path6.write_text("# BUG-6" + chr(10) * 2 + "Filed via the tracker's own API." + chr(10),
                                 encoding="utf-8")
            proposal_path6 = (proj / "qa-factory" / "artifacts" / "QATF-DIRECT" / "proposals"
                              / "bug-1.json")
            write_json(proposal_path6, {"kind": "bug", "bug_file": "bugs/BUG-6.md",
                                        "action": "create",
                                        "fields": {"summary": "filed via direct API"},
                                        "witness": {}})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run("QATF-DIRECT", cfg_direct, yes=False, preview=False)
            out = buf.getvalue()
            check("direct API create: exit 0", rc == 0)
            check("direct API create: one POST to /issue, nothing else mutating",
                  sum(1 for verb, *_ in fake_client.calls if verb == "POST") == 1)
            check("direct API create: the whoami line names the author, once",
                  out.count("writing as QA_JIRA_TOKEN: Jane Reviewer") == 1)
            direct_after, _ = load_json(proposal_path6)
            check("direct API create: result recorded with the confirmed key",
                  bool(direct_after) and direct_after.get("result", {}).get("external_id") == "JIRA-77")
            check("direct API create: delivered_by names the author, not just 'direct_api'",
                  direct_after.get("result", {}).get("delivered_by") == "QA_JIRA_TOKEN: Jane Reviewer")
            fm6 = strip_frontmatter(bug_path6.read_text(encoding="utf-8"))
            check("direct API create: the bug's own front matter got the key",
                  fm6.get("external_id") == "JIRA-77")

            # a comment on the same bug: no second create, one POST to /comment
            write_json(proj / "qa-factory" / "artifacts" / "QATF-DIRECT" / "proposals" / "bug-2.json",
                      {"kind": "bug", "bug_file": "bugs/BUG-6.md", "action": "comment",
                       "external_id": "JIRA-77", "fields": {"body": "still reproduces"},
                       "witness": {}})
            calls_before = len(fake_client.calls)
            rc = run("QATF-DIRECT", cfg_direct, yes=False, preview=False)
            check("direct API comment: exit 0", rc == 0)
            check("direct API comment: exactly one new POST, to /comment",
                  [c for c in fake_client.calls[calls_before:] if c[0] == "POST"]
                  == [("POST", "/rest/api/2/issue/JIRA-77/comment", {"body": "still reproduces"})])

            # a rejected write: the tracker's own message reaches the report, and a blind
            # retry is refused until a human reconciles it (never silently repeated).
            make_ticket("QATF-DIRECT-FAIL", gate_b=True)
            (proj / "qa-factory" / "bugs" / "BUG-7.md").write_text(
                "# BUG-7" + chr(10) * 2 + "Rejected by the tracker." + chr(10), encoding="utf-8")
            fail_proposal = (proj / "qa-factory" / "artifacts" / "QATF-DIRECT-FAIL" / "proposals"
                             / "bug-1.json")
            write_json(fail_proposal, {"kind": "bug", "bug_file": "bugs/BUG-7.md",
                                       "action": "create", "fields": {"summary": "x"}, "witness": {}})
            fake_client.routes["/issue"] = FetchError(400, "HTTP 400: summary already taken")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run("QATF-DIRECT-FAIL", cfg_direct, yes=False, preview=False)
            out = buf.getvalue()
            check("direct API failure: exit 1, not a crash", rc == 1)
            check("direct API failure: the tracker's own message is reported",
                  "summary already taken" in out)
            check("direct API failure: the proposal file is kept, not deleted",
                  fail_proposal.exists())
            failed, _ = load_json(fail_proposal)
            check("direct API failure: no result was recorded", not (failed or {}).get("result"))
            check("direct API failure: pending is left so a re-run cannot retry blindly",
                  bool((failed or {}).get("pending")))
            calls_before2 = len(fake_client.calls)
            rc = run("QATF-DIRECT-FAIL", cfg_direct, yes=False, preview=False)
            check("direct API failure: the re-run rejects rather than retrying (no new POST)",
                  rc == 1 and not any(c[0] == "POST" for c in fake_client.calls[calls_before2:]))

            # the createmeta required-field precheck: named before any POST is attempted, off
            # the SAME cached receipt tracker_write.py's probe already left.
            import tracker_write
            tracker_write.save_receipt(proj, {"channel": "jira",
                                              "status": tracker_write.CONFIRMED,
                                              "checked_at": now_iso(), "required_fields": ["Team"]})
            make_ticket("QATF-DIRECT-REQUIRED", gate_b=True)
            (proj / "qa-factory" / "bugs" / "BUG-8.md").write_text(
                "# BUG-8" + chr(10) * 2 + "Missing a required field." + chr(10), encoding="utf-8")
            required_proposal = (proj / "qa-factory" / "artifacts" / "QATF-DIRECT-REQUIRED"
                                 / "proposals" / "bug-1.json")
            write_json(required_proposal, {"kind": "bug", "bug_file": "bugs/BUG-8.md",
                                           "action": "create", "fields": {"summary": "x"},
                                           "witness": {}})
            calls_before3 = len(fake_client.calls)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run("QATF-DIRECT-REQUIRED", cfg_direct, yes=False, preview=False)
            out = buf.getvalue()
            check("required-field precheck: exit 1", rc == 1)
            check("required-field precheck: names the field the project demands",
                  "Team" in out and "requires" in out)
            check("required-field precheck: never reaches the tracker over it",
                  not any(c[0] == "POST" for c in fake_client.calls[calls_before3:]))
        finally:
            globals()["direct_client"] = held_direct_client

    print(f"=== SELFTEST external_writes: {'PASSED' if not failures else f'FAILED ({len(failures)})'} ===")
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="External-writes executor — bugs and cases, after gate B",
        epilog=epilog("external_writes.py"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticket", nargs="?", help="the story ticket id (matches artifacts/<TICKET>/)")
    ap.add_argument("--phase", choices=("auto", "after-a", "after-b"), default="auto")
    ap.add_argument("--preview", action="store_true", help="cases: print planned writes, execute nothing")
    ap.add_argument("--yes", action="store_true", help="cases: actually execute (bugs need no flag)")
    ap.add_argument("--record", default="", help="an agent-delivered proposal whose result is known")
    ap.add_argument("--external-id", dest="external_id", default="",
                    help="--record: the id the tracker gave the created/updated item")
    ap.add_argument("--remote-revision", default="", help="confirmed case revision from the remote receipt")
    ap.add_argument("--url", default="", help="--record: the item's url, when the agent reported one")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.record:
        return run_guarded("external_writes.py --record",
                           lambda: record_result(Path(args.record), args.external_id.strip(),
                                                args.url.strip(), args.remote_revision.strip()))
    if not args.ticket:
        print("a ticket id is required (or --selftest)", file=sys.stderr)
        return 2
    try:
        return run(args.ticket, load_config(), args.yes, args.preview, args.phase)
    except Exception as e:
        print(f"external_writes: unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
