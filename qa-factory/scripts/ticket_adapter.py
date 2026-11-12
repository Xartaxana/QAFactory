"""One CLI, several ticket sources — normalizes any tracker into the same schema so every
downstream role (qa-scout first) treats a ticket identically regardless of where it lives.

Run (via run-py.cmd):
    ticket_adapter.py get <TICKET> [--json] [--ticket-file <path>] [--raw-dir <work/ticket-raw>] [--output <snapshot.json>]
    ticket_adapter.py children <TICKET> [--json] [--ticket-file <path>]
    ticket_adapter.py diff --old <path> --new <path> [--json]
    ticket_adapter.py freshness <TICKET> --task-root <root> [--ticket-file <path>] [--json]
                      [--adopt | --decline --words-file <file>]
    ticket_adapter.py collect <TICKET> --output <work/source-inventory.json> [--json | --summary]
    ticket_adapter.py --migrate-method --config <path/to/config.json> [--dry-run] [--json]
    ticket_adapter.py --selftest

`--ticket-file <path>` reads THAT file as the ticket and ignores `adapters.ticket`
entirely - the flag qa-story documents, for a ticket that lives as a file in the repository
or was handed over as one. The file is either the markdown shape below or the JSON that
`get --json` prints (the story's own snapshot, `work/ticket-snapshot.json`); `diff` reads both.
ONE reader reads it (`parse_ticket_json`, `read_ticket_file`): a stderr line after the JSON and a key the schema
names but the file lacks are accepted (the key gets the markdown parser's default), and a file that is not UTF-8
text is the PERSON's (exit 1, owner `person`, the path named).

`get --output <path>` writes exactly the bytes `--json` prints (`snapshot_bytes`: UTF-8, LF on every platform),
atomically, and only after a successful read - a failed read leaves no file and touches none. That is the skill
path's writer of the story's ticket snapshot (`work/ticket-snapshot.json`) and the one `freshness` replaces it
with. Nothing else writes it - a caller that joined the adapter's stdout and stderr into a file once produced a
snapshot that was not JSON, and the scout never received it.

`review --record`, `accept-gap` and `freshness --decline` record a person's words. They come from
a file, `--words-file <path>` (UTF-8, as given; `<story folder>/state/words/<name>.txt`), through
`person_words.read`: a command line cannot carry a multi-line text through cmd.exe whole
(TP2-2406, M30), and inline `--words` that arrive through `run-py.cmd` are refused. All
three store the words stripped at the ends, by either route. `--decline` keeps them as a remark
in `pipeline.json` (`waiver.apply_remark`, the shape `waiver.py --remark` writes), which is where
the next gate reads them: "continue on the old text, as a known gap" is a decision with words,
and the gate must be able to say so. `freshness --adopt` takes no words.

`diff` compares two such files field by field and reports `severity`:
`requirements` (title/type/description/acceptance_criteria moved - the plan was built on
the old text), `context` (status/comments/parent/subtasks/links/attachments), or `none`.
Whether a ticket changed is a question for code, not for a role's memory of what it read.

`freshness` is the one command both host paths use to ask "did the ticket move since the
snapshot?": it reads the ticket now, compares it with the baseline (`work/ticket-snapshot.json`,
else the readable `.md` of a story that predates it), prints the verdict and settles the
files - see `freshness_check`. With `--ticket-file` (a story the person pasted) "now" is that file, read as the
person's text (`pasted=True`) and never the tracker: the person's text is the story's requirement, and setting it
against the tracker's is the S0 comparison's job, not this command's. When it replaces the baseline (`--adopt`, or a
`context` change) `work/ticket-view.md` is re-rendered from the new baseline (`source_inventory.ticket_view_text`) when
the story has that file; `work/ticket-references.json` has no renderer that works from a snapshot dict, so when it
exists ONE line on stderr names it as stale (`settle_role_files`).

Normalized schema (the return value of `get`, and what a command-template adapter must
normalize its raw output into):
    {"key": str, "type": str, "status": str, "title": str, "description": str,
     "acceptance_criteria": [str], "comments": [{"author", "date", "text"}],
     "parent": str|None, "subtasks": [{"key", "status"}],
     "links": {"merge_request": str|None, "branch": str|None}}

Adapter is read from the project's qa-factory/config.json, `adapters.ticket`:
  - {"kind"|"name": "file", "path": "<dir containing <TICKET>.md>"} — a local markdown
    ticket file (evals/fixtures/tickets/QA-1.md is the reference shape: YAML front matter
    with key/type/status/parent/merge_request, a "# Title" heading, a description
    paragraph, a "## Acceptance criteria" numbered list, a "## Comments" list of
    "- **author** (date): text" lines). Accepts both `kind` and `name` as the adapter-type
    key (references/adapters-read.md's shipped template uses `name`; this task's own done-check
    uses `kind`).
  - {"kind"|"name": "jira"|"ado"|"gitlab"|"github", "command": "<cli template with {key}>"}
    — the template is run with {key} replaced by the ticket id, stdout is parsed as JSON,
    then passed through a per-adapter normalization hook. The hook is a stub in this build
    (v0 is "framework only" per the build plan): it accepts output that ALREADY matches the
    schema above and otherwise refuses rather than guess field names.
  - {"kind"|"name": "jira"|"ado"|"gitlab"|"github", "mcp_tool": "<tool name>"} — no CLI to
    shell out to; the script cannot call an MCP tool itself, so it prints the instruction
    and exits 3 so the ROLE calls the tool and does the normalization.
  - {"kind"|"name": "jira"|..., "method": "agent"|"skill", "invoke": "<name>"} — a read
    route ONLY when `adapters.ticket.direct_api` is also recorded and usable (`method`
    picks the WRITE channel, `direct_api` picks the read route, independently of each
    other). Without a usable `direct_api`, every read command exits 3 naming
    `adapters.ticket.direct_api` and the onboarding command. An agent or skill is still a
    WRITE channel (`external_writes.channels.<name>`), which this script does not touch.
  - {"kind"|"name": "jira"|..., "method": "api", "direct_api": {...}} — the explicit label
    for the case above, written by `--migrate-method` once a config's `direct_api` is
    usable; reads the same way.
  - missing / empty `adapters.ticket` — exit 3, "run qa-onboarding".

`method` is explicit when present (`command | mcp_tool | agent | skill | api`) and inferred
from the key that is set otherwise, so configs written before the key existed keep working.
The access method is configuration, never a guess from the absence of another field. A
usable `direct_api` always wins the READ route over `method`, whatever `method` says.

Reading a Jira ticket is REST and nothing else (D-06: a tracker agent is not a data source; it is a
WRITE channel only). `get --raw-dir work/ticket-raw` (S0) reads the issue with every field and leaves
the whole answer beside the light snapshot it prints: the raw folder (`issue.json`, `issue.pretty.json`,
`field.json`, `remotelink.json`, `comments-<n>.json`), `work/ticket-view.md` (the line view a role
reads), `work/ticket-references.json` and, seeded in `work/source-inventory.json`, what S1 reuses so
it asks `/field` and the known projects nothing again. Without `--raw-dir` the same read prints the
snapshot and writes nothing.

A ticket the person handed over (`--ticket-file`) is parsed by the SAME parser as the REST description
(`ticket_light.acceptance_criteria`, markup `markdown`; the headings of references/jira-fields.json plus the
project's `direct_api.acceptance_headings`): any list marker (`-`, `*`, `+`, `1.`) is an item, a line that
starts with `# ` is a heading, and a heading-less text has no criteria. A text with any `h2.`-style line is
WIKI (`provenance.markup`; the rest is `markdown`): there `# ` is a list item. The title is the first `# ` line
(wiki: the header's `title:`, else the first line that is no heading, no item and not blank); a text with none
takes its first non-empty line (cut at 200 characters), says so in `provenance.title_from` (`first_line`) and
the driver asks the person once. Only the title line leaves the description: text above it stays. With `--raw-dir` and no tracker
read, the person's text (title and body) is scanned for references and `work/ticket-references.json` is
written in the parent of the raw folder: ticket rows `unproven` ("no tracker read at S0"), the null result as
an empty list.

Sections of a pasted text (the `## Comments` of the markdown shape and its Jira wiki twin `h2. Comments`): a text is read
in the markup `detect_markup` found for it (any `hN.` line makes it wiki) and in that markup only - in a wiki text `h2. `
starts a section and `##` is a nested list item; in a markdown text `## ` does and `h2.` cannot occur. A
`{code}` / `{noformat}` block is never cut into sections. `h1.` / `h3.` and `###` are not section headings (`h2.` / `##` is
the only level either way). A comment line is `- **author** (date): text` or, in wiki, `* *author* (date): text`.

Exit codes - three owners of a failed read: 0 success. 1 the adapter is reachable but the ticket was not found
(404 with the login proven fine), or the file the person named is missing, empty or not UTF-8 text (owner `person`: theirs to supply).
3 the TRACKER's: not
configured, not answering, a 5xx after the retries, normalization not implemented - always with an actionable
instruction, never a crash; a recorded `direct_api` that lacks keys is the exception in the object, not in the code:
exit 3 with owner `config` (the project's own setting to complete: the sentence names the missing
`adapters.ticket.direct_api.<key>` and `/qa-factory:qa-onboarding`; the driver puts it as the `ticket_read` question
with that sentence verbatim) - and so are the other settings of the project that no retry mends (no
`adapters.ticket`, an unknown adapter kind, an `auth_type` the client cannot send): exit 3, owner `config`, never
`tracker`. (The read route that is an agent or a skill, `require_direct_read`, is the same kind of fault and still says
`tracker`: the driver's `ticket_read` question has its own text for it, pinned by test_story_run_s0 K5, that the
`config` branch would replace - t-331 left it for the driver's next batch.) 4 the FACTORY's own fault: a data table (jira-fields.json, reference-kinds.json) or a
config key of the light form is missing or malformed, or an unexpected exception. 5 AUTH: the tracker stopped
accepting the token (a 401/403, a login page or a CAPTCHA that a re-read of something already read confirms):
ONE line on stderr names the environment variable to renew, nothing after that point was attempted or written
as "not found" - the code the driver turns into `InfraStop:auth` (story_run.EXIT_INFRA). A token (or user name)
environment variable that is not set in the shell is the same exit: the line names the VARIABLE, never a value, and
no request is made (t-287 item 3).

Under `--json`, `get`, `children`, `diff`, `freshness`, `collect`, `peek`, `refresh` and `probe` print on every REFUSAL exit (1, 3, 4, 5)
ONE JSON object on stdout and nothing else (stderr keeps the human sentence). Exit 2 - usage, a missing or unknown
argument - is the caller's malformed call, not a refusal of a read: it prints the usage line on stderr and no object
(`OWNERS` has no word for a call made wrong, and argparse's own exit 2 could not carry one): `{"ok": false, "owner": "tracker"|"factory"|
"auth"|"config"|"person", "status": <HTTP code or null>, "retry_at": <ISO time or null>, "message": "<one sentence>",
"file": "<path or key>"}` - `file` for the factory's and the person's owner only. The driver reads `retry_at` from it and the owner
decides the move: a question for the tracker's, a refusal naming the file for the factory's, a stop for auth, the
project's setting to complete for config's, the person's own file to supply for person's. The object is built by
`error_object` and nowhere else; `OWNERS` is the one list of the owner words.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib  # noqa: E402
import person_words  # noqa: E402
import runtime_paths as RP  # noqa: E402
import waiver  # noqa: E402
from event_store import atomic_json  # noqa: E402
from hooklib import PLUGIN_ROOT, load_config, parse_frontmatter, project_root  # noqa: E402
from source_inventory import (AuthLost, FetchError, MissingCredential, canonical_ticket, client_from_config,
                              collect_jira_source, conflicting_task_source, jira_ticket,
                              probe_jira_direct, record_attachment_inspection, record_external_media,
                              record_relevance_assessment, refresh_relevant_sources,
                              update_inventory, load_inventory, peek_jira_source,
                              apply_gap_acceptance, record_late_review, record_source_review,
                              render_review, review_rows, sources_with_open_gaps, VALID_RELATIONS,
                              marks_in)  # noqa: E402
import adapter_forms as AF  # noqa: E402
import local_keys  # noqa: E402
import source_exclusions  # noqa: E402
import source_inventory as SI  # noqa: E402
import ticket_light as TL  # noqa: E402

SCHEMA_KEYS = (
    "key", "type", "status", "title", "description", "acceptance_criteria",
    "comments", "parent", "subtasks", "links",
)
COMMAND_ADAPTERS = ("jira", "ado", "gitlab", "github")
# "api": the explicit label for "read through adapters.ticket.direct_api", written by
# --migrate-method once a config's direct_api is usable. It was never a distinct method before
# 0.7.9 — a full direct_api recorded next to method: "agent" was read the same as no direct_api
# at all, because nothing checked for it before refusing. `agent`/`skill` remain valid for
# WRITES (external_writes.channels.<name> is a separate config tree from adapters.ticket).
ACCESS_METHODS = ("command", "mcp_tool", "agent", "skill", "api")
# Which normalized fields make a change a REQUIREMENTS change: the plan, the register and
# the cases were built on these. The rest is context a gate can absorb by reading it.
REQUIREMENT_FIELDS = ("title", "type", "description", "acceptance_criteria")
# `attachments` and the `links.issue_links` / `links.remote_links` lists are CONTEXT: a person
# reads them at a gate, but the plan was not built on them (stage_compare.py s0 counts them).
CONTEXT_FIELDS = ("status", "comments", "parent", "subtasks", "links", "attachments")
# The plain words for a field, for a text a person reads (references/human-questions.md: no
# schema field name in the body). The schema is fixed in this file, so the words live beside it.
FIELD_WORDS = {
    "title": "the title", "type": "the issue type", "description": "the description",
    "acceptance_criteria": "the acceptance criteria", "status": "the status",
    "comments": "the comments", "parent": "the parent", "subtasks": "the subtasks",
    "links": "the links", "attachments": "the attachments",
}
SNAPSHOT_NAME = "ticket-snapshot.json"
NEXT_SNAPSHOT_NAME = "ticket-snapshot.next.json"
LEGACY_SNAPSHOT_NAME = "ticket-snapshot.md"
FRESHNESS_NAME = "ticket-freshness.json"
# The stage the `ticket_changed` question is asked at (story_run.ticket_freshness): a decline's
# words are kept as a remark of that stage.
DECLINE_STAGE = "S0"
# A baseline older than this is re-read. One rule, checkable by code (s0.md, freshness).
STALE_AFTER_HOURS = 6
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2
EXIT_NOT_CONFIGURED = 3
# The infrastructure code of the driver (story_run.EXIT_INFRA = 5, test_infra_failure_conductor_tracker.py K10): a lost
# login is not a question for the person about the ticket, it is a stop with the door named.
EXIT_AUTH_LOST = 5
# The factory's OWN fault (t-281 F3): a data table or a config key of the light form is broken, or something
# nobody foresaw was raised. Not the tracker's (3) and not the login's (5): the driver REPORTS it and names the
# file, it never puts it to the person as a choice (FR-3).
EXIT_FACTORY_FAULT = 4
OWNER_OF_CODE = {EXIT_NOT_FOUND: "tracker", EXIT_NOT_CONFIGURED: "tracker",
                 EXIT_FACTORY_FAULT: "factory", EXIT_AUTH_LOST: "auth"}
# Every owner word an error object can carry (the carrier is this tuple: the object's `owner` is one of them, the
# driver's reader of the object must know the same words). `OWNER_OF_CODE` is only the default of a code that names
# none: a refusal that knows better says so (`fail(..., owner=...)`).
#   `intermediary` (B-408): something between this machine and the tracker - a firewall, a proxy, a protection
#   service - answered instead, or the answer could not be read; the token was NOT judged. Exit 5 like a lost login
#   (nothing after it was tried), but the driver puts it to the person as the `ticket_read` question naming the check.
OWNERS = ("tracker", "factory", "auth", "config", "person", "intermediary")
# The auth types `source_inventory.JiraClient._headers` can send. Named here only to say them in a refusal;
# the client stays the judge (`refuse_unsupported_auth_type` asks it), and a test keeps the two lists equal.
DIRECT_API_AUTH_TYPES = ("basic_token", "bearer")
TITLE_LIMIT = 200          # characters of a title taken from the first line of a paste (F2)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
TITLE_RE = re.compile(r"^#\s+\S")
COMMENT_RE = re.compile(
    r"^\s*-\s*\*\*(?P<author>[^*]+)\*\*\s*\((?P<date>[^)]+)\)\s*:\s*(?P<text>.+?)\s*$"
)
# The Jira wiki twin of a comment line: `* *Dave* (2026-10-01): text` (a bullet `*` / `-` / `#`, the author in wiki bold
# `*x*`). `**x**` (markdown bold) does not match it: `[^*]+` stops at the second star.
WIKI_COMMENT_RE = re.compile(
    r"^\s*[*\-#]+\s+\*(?P<author>[^*]+)\*\s*\((?P<date>[^)]+)\)\s*:\s*(?P<text>\S.*)$"
)
# A section heading of a pasted text, in its two forms: the markdown `## Comments` and the Jira wiki `h2. Comments`.
# One level each (`###` and `h3.` stay inside their section). `[ \t]+\S`: a heading with words, on one line.
MARKDOWN_SECTION_RE = re.compile(r"^##[ \t]+(\S.*?)\s*$")
WIKI_SECTION_RE = re.compile(r"^h2\.[ \t]+(\S.*?)\s*$")
# `{code}` / `{code:java}` / `{noformat}`: a block whose lines are never headings. A marker on a line toggles the block
# (`{code}x{code}` on one line opens and closes it).
CODE_MARK_RE = re.compile(r"\{(code|noformat)(?::[^}\n]*)?\}")


class Fail(SystemExit):
    """What `fail()` raises: still a SystemExit (every `except SystemExit` and every test that catches one
    works as before), carrying what the `--json` error object needs: the sentence, the owner (None = by the
    code, `OWNER_OF_CODE`) and, for the factory's, the file or key."""

    def __init__(self, code: int, message: str, owner: str | None = None, file: str | None = None):
        super().__init__(code)
        self.message, self.owner, self.file = message, owner, file


def fail(code: int, message: str, owner: str | None = None, file: str | None = None):
    print(message, file=sys.stderr)
    raise Fail(code, message, owner, file)


def one_sentence(text) -> str:
    return " ".join(str(text or "").split())


def error_object(owner: str, message: str, *, status=None, retry_at=None, file=None) -> dict:
    """The ONE JSON object every verb prints on stdout under `--json` on any non-zero exit (F3, FR-14): the keys
    `ok`, `owner` (one of `OWNERS`), `status`, `retry_at`, `message`, and `file` for the factory's and the person's
    owner (the file that is missing or empty: ours to restore, theirs to supply - the driver names the person's in its
    question's answer block, t-335 B-n4). No other place builds it, so the shape cannot differ from one verb to the
    next."""
    obj = {"ok": False, "owner": owner, "status": status, "retry_at": retry_at, "message": one_sentence(message)}
    if owner in ("factory", "person"):
        obj["file"] = file
    return obj


def refuse_exit(exc: SystemExit, emit=None) -> int:
    """A verb's `except SystemExit`: the code it exits with, and - under `--json`, on a non-zero code - the error
    object (owner: the one the refusal named, else the code's own, `OWNER_OF_CODE`). Before this every verb but
    `get`/`children` returned the bare code and the caller had no object to read (FR-14)."""
    code = int(exc.code or 0)
    if code and emit:
        emit(error_object(getattr(exc, "owner", None) or OWNER_OF_CODE.get(code, "tracker"),
                          getattr(exc, "message", "") or f"ticket_adapter exited {code}",
                          file=getattr(exc, "file", None)))
    return code


_NAMED_SOURCE_RE = re.compile(r"[\w.-]+\.json|direct_api\.\w+|adapters\.ticket\.\w+")


def named_source(message: str) -> str | None:
    """The file or config key a TableError names, read from the sentence the table loaders raise (they name
    it first, `<file>: ...` / `<key> must be ...`); None when the sentence names none."""
    found = _NAMED_SOURCE_RE.search(str(message or ""))
    return found.group(0) if found else None


def refuse_auth(exc: AuthLost, emit=None) -> int:
    """A lost login: ONE line (what was refused, which environment variable to renew, that nothing
    later was tried or written as "not found"), and the code the driver reads as an infrastructure
    stop. Never the `ticket_read` question for a lost login: the person did nothing wrong with the ticket."""
    print(f"ticket_adapter: {exc}", file=sys.stderr)
    if emit:
        # B-408: the owner is the exception's own `cause` - `auth` for a lost login, `intermediary` for an answer the
        # tracker is not shown to have written (`source_inventory.Intercepted`). The code stays 5 for both.
        emit(error_object(getattr(exc, "cause", "auth"), str(exc), status=getattr(exc, "status", None)))
    return EXIT_AUTH_LOST


def refuse_table(exc: Exception, emit=None) -> int:
    """The light form's data (jira-fields.json, reference-kinds.json) or a config key of it is missing,
    empty or malformed: the message names the file or key and how to restore it (ticket_light FR-1). The
    factory's own fault, exit 4: the driver reports it and names the file, it is not a question about the
    network."""
    print(f"ticket_adapter: refused - {exc}", file=sys.stderr)
    if emit:
        emit(error_object("factory", f"refused - {exc}", file=named_source(str(exc))))
    return EXIT_FACTORY_FAULT


def refuse_unexpected(what: str, exc: Exception, emit=None) -> int:
    """The catch-all of every verb: something nobody foresaw was raised. The factory's own fault, exit 4, the
    sentence on stderr and, under --json, the error object (owner factory, no file to name). `what` leads the
    sentence (`unexpected error`, `collect unavailable`, ...)."""
    message = f"{what}: {exc}"
    print(f"ticket_adapter: {message}", file=sys.stderr)
    if emit:
        emit(error_object("factory", message))
    return EXIT_FACTORY_FAULT


def refuse_fetch(exc: FetchError, ticket: str, emit=None) -> int:
    """A read the tracker answered with an error. 404 is "not found" (exit 1: reachable, no such
    ticket - or one this token may not see; a lost login never gets here, it raised AuthLost); anything
    else is exit 3 with the reason and, when the tracker asked for a later retry, the time."""
    if exc.status == 404 and not SI._foreign(exc):      # B-408 F3: a 404 page the tracker is not shown to have written says nothing about the key
        message = (f"{ticket} was not found (HTTP 404): the key does not exist, or this token "
                   "may not see it - check the key, ask for access, or hand the ticket over as text "
                   "(--ticket-file).")
        print(f"ticket_adapter: {message}", file=sys.stderr)
        if emit:
            emit(error_object("tracker", message, status=404))
        return EXIT_NOT_FOUND
    later = f"; the tracker asked to be tried again at {exc.retry_at}" if exc.retry_at else ""
    message = (f"the tracker could not be read for {ticket} ({exc.reason}){later} - retry, "
               "or hand the ticket over as text (--ticket-file).")
    print(f"ticket_adapter: {message}", file=sys.stderr)
    if emit:
        emit(error_object("tracker", message, status=exc.status, retry_at=exc.retry_at))
    return EXIT_NOT_CONFIGURED


def _left_out_ticket(output: Path, client, key: str) -> bool:
    """Does a live exclusion of this story name this ticket? (The fetch itself is refused inside
    `collect_jira_source` / `peek_jira_source`; the commands ask only to skip their own guards.)"""
    return source_exclusions.first_match(source_exclusions.live_in(output.parent),
                                         canonical_ref=canonical_ticket(client.base_url, key)) is not None


def _say_marks(output: Path, before: dict, after: dict, requested_id: str | None = None) -> None:
    """One stderr line per mark this write newly made, plus the requested ticket when it is left out
    (said whether or not the mark is new: the caller asked for it and got nothing). stdout stays
    whatever the command printed - `--json` output is still pure JSON."""
    live = source_exclusions.live_in(output.parent)
    now = marks_in(after)
    new = (now - marks_in(before)) | {mark for mark in now if mark[0] == requested_id and mark[1] is None}
    by_source = {item.get("source_id"): item for item in after.get("sources", [])}
    for source_id, url, exclusion_id in sorted(new, key=lambda mark: (str(mark[0]), str(mark[1]))):
        what = url or str((by_source.get(source_id) or {}).get("canonical_ref") or source_id).rsplit("/browse/", 1)[-1]
        print(source_exclusions.left_out_line(what, source_exclusions.reason_of(live, exclusion_id)),
              file=sys.stderr)


# --- markdown ticket parsing (the 'file' adapter) -----------------------------------------

def strip_frontmatter(text: str) -> tuple[dict, str]:
    fm = parse_frontmatter(text) or {}
    m = FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text
    return fm, body


WIKI_HEADING_RE = re.compile(r"^h[1-6]\.\s")


def detect_markup(body: str) -> str:
    """`wiki` when any line is a wiki heading (`h2. Acceptance Criteria`), else `markdown` (t-287 item 1). A wiki text
    puts its numbered items on `# ` lines, so one `h2.` line anywhere changes what `# ` means for the whole text: it is
    a list item, never the title. A text that is both (an `h2.` line and a `# ` title) is wiki - the `# ` line is an
    item; the title then comes from the header's `title:` or from the first plain line."""
    return "wiki" if any(WIKI_HEADING_RE.match(line) for line in TL.split_lines(body)) else "markdown"


def _is_title_candidate_wiki(line: str) -> bool:
    """A wiki line that can be the title: not blank, not a heading, not a list item."""
    text = line.strip()
    return bool(text) and not WIKI_HEADING_RE.match(text) and not TL._ITEM_WIKI.match(line)


def _outside_code(lines: list) -> list:
    """The indexes of the lines that START outside a `{code}` / `{noformat}` block. A block is closed by its own
    marker (`{code}` by `{code}`); one that never closes keeps the rest of the text inside it - the scan reads
    fewer headings, never invents one."""
    open_name, outside = None, []
    for index, line in enumerate(lines):
        if open_name is None:
            outside.append(index)
        for mark in CODE_MARK_RE.finditer(line):
            if open_name is None:
                open_name = mark.group(1)
            elif mark.group(1) == open_name:
                open_name = None
    return outside


def scan_sections(text: str, markup: str | None = None) -> SimpleNamespace:
    """The sections of a pasted text, read in the form the text IS in: `.lines`, `.heads` (`[(line index, lowercase
    name)]`), `.form` (`markdown` for `## `, `wiki` for `h2. `, None when the text has no section heading of its own
    form) and `.sections` ({name: its text, stripped}).

    The form is `markup` - what `detect_markup` found for the whole text (None: found here, from `text`) - and nothing
    else (t-335 B1): in a wiki text only `h2. ` starts a section, because there `##` is a NESTED LIST ITEM (a Jira
    paste with `# step` / `## sub-step` above its first `h2.` is no markdown text); in a markdown text only `## `
    does. The old rule - the first heading of either form fixes the form - read such a paste as markdown, found no
    comments, and reported a "both headings" limitation that was false. A section runs from its heading to the next
    heading of the same form, outside a `{code}` / `{noformat}` block; a repeated name keeps the later section, as it
    always did."""
    lines = TL.split_lines(text)
    markup = markup or detect_markup(text)
    pattern = WIKI_SECTION_RE if markup == "wiki" else MARKDOWN_SECTION_RE
    heads = []
    for index in _outside_code(lines):
        match = pattern.match(lines[index])
        if match:
            name = (TL._heading_text(lines[index], "wiki") or "") if markup == "wiki" else match.group(1).strip().lower()
            heads.append((index, name))
    sections = {}
    for position, (index, name) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        sections[name] = "\n".join(lines[index + 1:end]).strip()
    return SimpleNamespace(lines=lines, heads=heads, form=markup if heads else None, sections=sections)


def split_body(body: str, first_line_title: bool = False, markup: str = "markdown",
               front_title: str = "") -> tuple[str, str, dict, str | None]:
    """(title, description, sections, title_from) — sections keyed by lowercase heading text (`## ` or `h2. `, one
    form per text, see `scan_sections`); the
    description is the WHOLE text minus the title LINE (sections included, and whatever stands above the title),
    the sections are a parsed view.

    markdown (the default): the title is the first `# ` line. wiki (`markup`, see `detect_markup`): `# ` is a list
    item; the title is the header's `title:` (`front_title`) when there is one, else - for a text the person handed
    over - the first line that is neither a heading, nor a list item, nor blank. `first_line_title` (a text the
    person handed over): when no title was found by those rules the first non-empty line is the title, cut at
    TITLE_LIMIT characters, and `title_from` says `first_line` (F2: a ticket copied from a browser has no title
    line, and the driver asks the person once). Only the title LINE leaves the description (t-287 item 1: text
    above a `# ` title stays, P4); a line cut at the limit stays whole at its place, and a title from the header
    consumes no line."""
    # ticket_light.split_lines, not str.splitlines (C7): that also cuts at U+2028, U+0085 and form
    # feed, and a title or a comment holding one would be split in the middle.
    lines = TL.split_lines(body)
    title, consumed, title_from = (front_title or "").strip() if markup == "wiki" else "", None, None
    if not title and markup == "markdown":
        for i, line in enumerate(lines):
            if TITLE_RE.match(line):
                title, consumed = line.lstrip("#").strip(), i
                break
    if not title and first_line_title:
        if markup == "wiki":
            for i, line in enumerate(lines):
                if _is_title_candidate_wiki(line):
                    first = line.strip()
                    title, title_from = first[:TITLE_LIMIT], "first_line"
                    consumed = i if len(first) <= TITLE_LIMIT else None
                    break
        if not title:
            for i, line in enumerate(lines):
                if line.strip():
                    first = line.strip()
                    title, title_from = first[:TITLE_LIMIT], "first_line"
                    consumed = i if len(first) <= TITLE_LIMIT else None
                    break
    rest = "\n".join(line for i, line in enumerate(lines) if i != consumed)
    # Every section stays in the description, verbatim (t-281 follow-up, loss at the entrance): only the front
    # matter and the title line are consumed. Criteria and comments are PARSED from the text, never cut out of it.
    description = rest.strip()
    return title, description, scan_sections(rest, markup).sections, title_from


def merge_headings(base, extra) -> list:
    """The table's acceptance headings plus the project's own that the table does not already hold
    (case-insensitive) - the merge `source_inventory.light_snapshot` makes for the REST description."""
    heads = list(base)
    heads += [h for h in extra if h.strip().casefold() not in {x.casefold() for x in heads}]
    return heads


def acceptance_headings_for(cfg: dict | None = None, table: dict | None = None) -> list:
    """The headings a ticket's criteria are looked for under: references/jira-fields.json
    `acceptance_headings` plus the config's `adapters.ticket.direct_api.acceptance_headings` - the same
    list, from the same two sources, the REST route uses. The config key's shape is checked by
    `source_inventory._extra_headings` (a wrong shape is a TableError naming the key). A table that cannot be
    read is a TableError naming the file."""
    table = table or TL.load_fields_table()
    direct = (((cfg or {}).get("adapters") or {}).get("ticket") or {}).get("direct_api")
    extra = (direct or {}).get("acceptance_headings") if isinstance(direct, dict) else None
    holder = SimpleNamespace(acceptance_headings=extra if extra is not None else [])
    return merge_headings(table["acceptance_headings"], SI._extra_headings(holder))


def _comment_match(line: str):
    """The match of one comment line in either form - markdown `- **author** (date): text`, Jira wiki
    `* *author* (date): text` - or None. ONE definition: `parse_comments` reads the comments with it and
    `without_comments_section` drops exactly the lines it parses (t-335 B-n1)."""
    return COMMENT_RE.match(line) or WIKI_COMMENT_RE.match(line)


def parse_comments(text: str) -> list:
    out = []
    for line in TL.split_lines(text):
        m = _comment_match(line)
        if m:
            out.append({
                "author": m.group("author").strip(),
                "date": m.group("date").strip(),
                "text": m.group("text").strip(),
            })
    return out


def parse_inline_list(raw: str) -> list:
    """'a, b, c' or '[a, b, c]' -> ['a', 'b', 'c']; '' -> []."""
    raw = (raw or "").strip()
    if not raw:
        return []
    raw = raw.strip("[]")
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_subtasks(raw: str) -> list:
    """'QA-2:open, QA-3:done' -> [{"key": "QA-2", "status": "open"}, ...] — the file
    adapter's own convention (not pinned elsewhere); a bare key with no ':' gets
    status 'unknown' rather than being dropped."""
    out = []
    for item in parse_inline_list(raw):
        key, _, status = item.partition(":")
        out.append({"key": key.strip(), "status": status.strip() or "unknown"})
    return out


def parse_ticket_markdown(text: str, ticket: str, source: str = "file", headings: list | None = None) -> dict:
    """The file-adapter shape -> the normalized schema. One parser, three callers: the
    `file` adapter, `--ticket-file`, and `diff`; a snapshot written by the orchestrator is
    read by exactly the same code that reads a fixture.

    `provenance.source` is set by the CALLER, from the route taken (C13): `file` for the file adapter,
    `person_pasted` for a ticket the person handed over - never from a `source:` line inside the text,
    which is whatever the text's author wrote (the old tracker-agent template wrote `agent` there).

    The acceptance criteria are `ticket_light.acceptance_criteria(markup="markdown")` over the WHOLE text after
    the front matter - the ONE parser of a description (t-281 F1, FR-17): the same headings, the same end of the
    section, any list marker. The first line may be consumed as the title and still takes part in that scan (a
    text that opens with the heading itself gives both). `headings` None = the table's own (a caller that reads a
    project's config passes the merged list, `acceptance_headings_for`)."""
    fm, body = strip_frontmatter(text)
    markup = detect_markup(body)
    title, description, sections, title_from = split_body(body, first_line_title=source == "person_pasted",
                                                          markup=markup, front_title=str(fm.get("title") or ""))
    criteria = []
    if body.strip():
        table = TL.load_fields_table()
        criteria = TL.acceptance_criteria(
            body, headings=headings if headings is not None else acceptance_headings_for(table=table),
            section_names=table["section_names"], markup=markup)
    # `markup` says how this text was read (t-287 item 1): a snapshot written before it has no such key and is read
    # as markdown - the only reading there was.
    provenance = {"source": source, "fetched_at": fm.get("fetched_at") or None, "markup": markup}
    if title_from:
        provenance["title_from"] = title_from
    return {
        "key": fm.get("key") or ticket,
        "type": fm.get("type") or "",
        "status": fm.get("status") or "",
        "title": title or ticket,
        "description": description,
        "acceptance_criteria": criteria,
        "comments": parse_comments(sections.get("comments", "")),
        "parent": fm.get("parent") or None,
        "subtasks": parse_subtasks(fm.get("subtasks", "")),
        "links": {
            "merge_request": fm.get("merge_request") or None,
            "branch": fm.get("branch") or None,
        },
        # Not part of SCHEMA_KEYS (the passthrough normalizer's contract is untouched): where
        # this text came from. Provenance travels with the artifact rather than inside a prompt.
        "provenance": provenance,
    }


def parse_ticket_json(text: str, ticket: str) -> dict | None:
    """A snapshot in the form `get <T> --json` prints -> the normalized schema, or None when
    the text is not one.

    The story's one snapshot is that command's stdout, byte for byte (`work/ticket-snapshot.json`,
    FR-49: the scout's brief reads that name and the diff reads the same file). `raw_decode`
    rather than `loads`: snapshots written before the driver kept stderr out of the file carry a
    warning line after the object, and a story in flight must still read its own snapshot. A key
    the schema names and the file lacks gets the markdown parser's default - the same absence
    means the same thing whichever form the ticket arrived in - and a key it does not name
    (attachments, revision, the direct API's link lists) is kept, not dropped."""
    text = str(text or "").lstrip(chr(0xFEFF)).lstrip()   # a BOM, built from its code point
    if not text.startswith("{"):
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    defaults = parse_ticket_markdown("", ticket)
    merged = dict(data)
    for key in SCHEMA_KEYS:
        if key not in merged:
            merged[key] = defaults[key]
    return merged


def snapshot_text(obj) -> str:
    """The ONE text of a ticket document: what `get --json` prints, what `get --output` and `freshness` write
    as the story's snapshot (L3, t-428). One function, so a dict has one form wherever it is written."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def snapshot_bytes(obj) -> bytes:
    """`snapshot_text` as UTF-8, LF on every platform: the bytes of the snapshot file. The Windows text layer
    (`atomic_json`, `print`) writes CRLF, so nothing that holds a snapshot goes through it."""
    return snapshot_text(obj).encode("utf-8")


def write_stdout(data: bytes) -> None:
    """Exactly `data` on stdout. Through the binary layer when the stream has one (a real process: UTF-8 and LF on
    Windows too, instead of CRLF in the console's code page, which cannot hold every character of a title); a
    stream without one (a test's StringIO) gets the decoded text."""
    stream = sys.stdout
    binary = getattr(stream, "buffer", None)
    if binary is None:
        stream.write(data.decode("utf-8"))
        return
    stream.flush()
    binary.write(data)
    binary.flush()


def read_ticket_file(path: Path, ticket: str = "", pasted: bool = False) -> dict:
    """The ticket a file holds, in either form: the file-adapter's markdown, or the JSON that
    `get --json` prints (what the driver's snapshot is). `pasted`: the file is a ticket the person
    handed over (`--ticket-file`), so a markdown text is labelled `person_pasted`; a JSON snapshot keeps
    whatever label it was written with (`fetched`, or the older `jira_direct_api` / `agent` / `file`:
    read as is, never rewritten). The ONE reader of a ticket file: a file that is not UTF-8 text is the
    person's (owner `person`, exit 1), never read with replacement characters."""
    if not path.exists():
        # The person's own file (the one they named, or the ticket file their project keeps): theirs to supply, not
        # the tracker's to answer for - owner `person`, the same exit 1 as before.
        fail(EXIT_NOT_FOUND, f"ticket file not found: {path}", owner="person", file=str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        fail(EXIT_NOT_FOUND, f"ticket file {path} is not UTF-8 text ({exc.reason} at byte {exc.start}): expected the "
             "ticket as UTF-8 text. Save the file as UTF-8 and read it again.", owner="person", file=str(path))
    parsed = parse_ticket_json(text, ticket or path.stem)
    if parsed is None:
        if pasted and not text.strip():
            # An empty text is no ticket: the title would be the key and nothing else would be there. (Until t-281
            # the driver caught it at the title; the driver no longer refuses a title-less text, it asks.)
            fail(EXIT_NOT_FOUND, f"ticket file {path} is empty: expected the ticket as text - the title on a line that "
                 "starts with `# ` (or on the first line), then the description. Put the ticket text in the file "
                 "and read it again.", owner="person", file=str(path))
        parsed = parse_ticket_markdown(text, ticket or path.stem, source="person_pasted" if pasted else "file",
                                       headings=acceptance_headings_for(load_config()))
    if isinstance(parsed.get("provenance"), dict):
        parsed["provenance"].pop("local_key", None)      # the mark has ONE writer: the branch below (a pasted copy never carries it)
    if ticket and local_keys.is_local(ticket):
        # THE writer of the mark (SS1-14): the snapshot of a local story says so, and `is_local` reads it back.
        provenance = parsed.get("provenance") if isinstance(parsed.get("provenance"), dict) else {}
        parsed["provenance"] = dict(provenance, local_key=True)
    return parsed


def write_snapshot(ticket_obj: dict, path: Path) -> None:
    """The ticket dict `get` prints, as `snapshot_bytes`, atomically (`source_inventory._atomic_write`: the file is
    replaced whole or not at all, so a reader never meets half a snapshot, and the bytes are the same on every
    platform - `atomic_json` opens in text mode and would write CRLF on Windows)."""
    try:
        SI._atomic_write(Path(path), snapshot_bytes(ticket_obj))
    except OSError as exc:
        fail(EXIT_NOT_CONFIGURED, f"ticket_adapter: cannot write the snapshot {path}: {exc}")


def get_file(ticket: str, adapter_cfg: dict) -> dict:
    raw_path = str(adapter_cfg.get("path") or "").strip()
    if not raw_path:
        fail(EXIT_NOT_CONFIGURED,
             "adapters.ticket (kind=file) needs a 'path' — the directory holding "
             "<TICKET>.md. Run qa-onboarding, or set adapters.ticket.path in "
             "qa-factory/config.json.")
    base = Path(raw_path)
    if not base.is_absolute():
        base = project_root() / base
    return read_ticket_file(base / f"{ticket}.md", ticket)


# --- command-template adapters (jira / ado / gitlab / github) -----------------------------

def _normalize_passthrough(raw) -> dict | None:
    """The v0 normalization hook: accepts output that already matches the schema, refuses
    to guess a tracker's real field names otherwise (build plan C4: adapters beyond 'file'
    are framework/interface only)."""
    if isinstance(raw, dict) and all(k in raw for k in SCHEMA_KEYS):
        return raw
    return None


NORMALIZERS = {name: _normalize_passthrough for name in COMMAND_ADAPTERS}


def resolve_method(adapter_cfg: dict) -> str:
    """`method` when the project declared one, otherwise inferred from the key that is set.

    Inference is back-compat for configs written before the key existed - never a way to
    discover an access method. A project reached through an agent says so; it is not
    recognized by the absence of a `command`, which is how a genuinely-MCP project would end
    up in the agent branch."""
    declared = str(adapter_cfg.get("method") or "").strip().lower()
    if declared:
        return declared
    if str(adapter_cfg.get("command") or "").strip():
        return "command"
    if str(adapter_cfg.get("mcp_tool") or "").strip():
        return "mcp_tool"
    return ""


def snapshot_hint(ticket: str) -> str:
    """Where the story's one ticket snapshot lives. Nothing calls this today; it names the file
    the driver writes and the brief reads, so a caller added later cannot invent another."""
    return f"qa-factory/artifacts/{ticket}/work/ticket-snapshot.json"


def has_usable_direct_api(adapter_cfg: dict) -> bool:
    """True when adapters.ticket.direct_api carries enough to actually read through it.

    Delegates to client_from_config's own validation instead of re-checking the field list
    here, so "usable" never drifts from what get_ticket/collect/peek/refresh really require.
    Public since t-281 F10: the driver asks it, and a driver calling a private name breaks on a rename."""
    if not isinstance(adapter_cfg.get("direct_api"), dict):
        return False
    try:
        client_from_config(adapter_cfg)
        return True
    except Exception:
        return False


_has_usable_direct_api = has_usable_direct_api      # the old name, kept for one release


def reads_by_role(cfg) -> bool:
    """SS1-15: does the ROLE read this project's tracker itself, by the route onboarding recorded, because the factory holds
    no client for it? The ONE reader of that question (AR-13); pure, no network. A Jira with a usable `direct_api` is read by
    the client whatever else is recorded (False); a Jira without one is read by the role only when a route is recorded
    (`source_inventory.tracker_route`), else False: today's refusal naming the missing fields stays, a broken setting never
    silently loses the comments and the parent. Any other tracker (an empty kind and `file` included) is True.
    Error direction: a false False is a refusal with a door; a false True while `direct_api` is usable is forbidden."""
    if AF.ticket_kind(cfg) != "jira":
        return True
    if has_usable_direct_api(AF.ticket_entry(cfg)):
        return False
    return SI.tracker_route(cfg) is not None


def direct_api_not_usable_message(adapter_cfg: dict) -> str:
    """The one sentence for a recorded `direct_api` that `client_from_config` refuses (t-287 item 2): which
    `adapters.ticket.direct_api.<key>` is missing - by name, from the same rule `client_from_config` applies - and
    the door, `/qa-factory:qa-onboarding`. A template stub (`{"custom_fields": [], "acceptance_headings": []}`, what
    an old config migrated to the light form carries) names `base_url`, `auth_type` and `secret_ref`, and
    `username_ref` as the one `basic_token` needs. When every key is there and the client still refuses (a key of the
    wrong shape), the sentence quotes the client's own reason instead."""
    direct = adapter_cfg.get("direct_api") if isinstance(adapter_cfg.get("direct_api"), dict) else {}
    present = lambda key: bool(str(direct.get(key) or "").strip())
    auth_type = str(direct.get("auth_type") or "").strip()
    names = [key for key in ("base_url", "auth_type", "secret_ref") if not present(key)]
    if not present("username_ref") and auth_type in ("", "basic_token"):
        names.append("username_ref" if auth_type else "username_ref (when auth_type is basic_token)")
    if names:
        what = "is not complete: it lacks " + ", ".join(f"adapters.ticket.direct_api.{name}" for name in names)
    else:
        try:
            client_from_config(adapter_cfg)
            what = "could not be used"
        except Exception as exc:        # noqa: BLE001 - the client's own reason is the sentence
            what = f"is not usable: {exc}"
    return (f"the tracker's direct API (adapters.ticket.direct_api in qa-factory/config.json) {what} - run "
            "/qa-factory:qa-onboarding to record it.")


# The owner's decision of 21.09.2026. Reading a tracker through a session agent looked
# like a seam and was a dead end: the adapter answered "the ORCHESTRATOR fetches the ticket
# once" to EVERY key, and S1 needs the parent, the normative sources and every mentioned key
# — which the scout, whose charter forbids it the Agent tool, can never fetch. Attachments
# never arrive through an assistant at all. Meanwhile onboarding asks for the direct API
# token regardless. So reading is `direct_api` and nothing else; an agent or skill stays a
# perfectly good WRITE channel, where it only has to carry one message out.
#
# (test-harness, TP1-15045 run on 0.7.8): `method` picks the WRITE channel, not
# whether direct_api is usable — those are two separate questions this function used to
# conflate. A config with method: "agent" AND a fully recorded direct_api was refused with
# "record direct_api", though it already was: the scout lost the parent and every linked
# ticket. Reading now goes through direct_api whenever it is usable, whatever `method` says.
def require_direct_read(adapter_cfg: dict, operation: str) -> None:
    method = resolve_method(adapter_cfg)
    if method not in ("agent", "skill"):
        return
    if has_usable_direct_api(adapter_cfg):
        return
    invoke = str(adapter_cfg.get("invoke") or "").strip() or "<unnamed>"
    fail(EXIT_NOT_CONFIGURED,
         f"`{operation}` cannot read this tracker: adapters.ticket.method is '{method}' "
         f"('{invoke}'), and reading through a session agent or skill is no longer supported. "
         "It returns no attachment bytes, and the scout — which has no Agent tool — cannot "
         "reach the parent, the normative sources or a mentioned key through it, so S1 loses "
         "sources without ever saying so. Record `adapters.ticket.direct_api` (the base url "
         "and the API token onboarding already asks for) with `/qa-factory:qa-onboarding`. "
         "An agent or skill remains a valid WRITE channel "
         "(`external_writes.channels.<name>`); only reading changed.")


def get_via_command(kind: str, ticket: str, adapter_cfg: dict) -> dict:
    command = str(adapter_cfg.get("command") or "").strip()
    mcp_tool = str(adapter_cfg.get("mcp_tool") or "").strip()
    method = resolve_method(adapter_cfg)

    if method and method not in ACCESS_METHODS:
        fail(EXIT_NOT_CONFIGURED,
             f"adapters.ticket.method is '{method}' — supported: {', '.join(ACCESS_METHODS)}. "
             "Run qa-onboarding.")

    require_direct_read(adapter_cfg, "get")

    if not command and mcp_tool:
        fail(EXIT_NOT_CONFIGURED,
             f"adapters.ticket.{kind} names an MCP tool, not a CLI command — use MCP tool "
             f"'{mcp_tool}' yourself and normalize its result to this schema: "
             f"{{{', '.join(SCHEMA_KEYS)}}}")
    if not command:
        fail(EXIT_NOT_CONFIGURED,
             f"adapters.ticket.{kind} has neither 'command' nor 'mcp_tool' configured — "
             "run qa-onboarding, or set one in qa-factory/config.json.")
    cmd = command.replace("{key}", ticket)
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    except Exception as e:
        fail(EXIT_NOT_CONFIGURED, f"adapters.ticket.{kind} command failed to start: {e}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        fail(EXIT_NOT_CONFIGURED,
             f"adapters.ticket.{kind} command exited {proc.returncode}: {detail}")
    raw_out = (proc.stdout or "").strip()
    if not raw_out:
        fail(EXIT_NOT_CONFIGURED, f"adapters.ticket.{kind} command produced no output")
    try:
        data = json.loads(raw_out)
    except Exception:
        fail(EXIT_NOT_CONFIGURED,
             f"adapters.ticket.{kind} command output is not JSON — normalize it to this "
             f"schema yourself: {{{', '.join(SCHEMA_KEYS)}}}")
        return {}  # unreachable, keeps type checkers happy
    normalized = NORMALIZERS[kind](data)
    if normalized is None:
        fail(EXIT_NOT_CONFIGURED,
             f"adapters.ticket.{kind} normalization is not implemented for this output "
             f"shape — normalize the raw JSON to this schema yourself: "
             f"{{{', '.join(SCHEMA_KEYS)}}}\nraw output: {json.dumps(data)[:500]}")
    return normalized


# --- diff: did the ticket move under the plan? ------------------------------------------

def _comment_key(c: dict) -> tuple:
    return (str(c.get("author", "")), str(c.get("date", "")), str(c.get("text", "")))


def _canon(value):
    """The comparison form: strings stripped and CRLF turned into LF, all the way down. Only
    the comparison sees it - a stored file is never rewritten. A Markdown file saved on
    Windows and the same text from the API differ in exactly this, and that is not a change."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").strip()
    if isinstance(value, list):
        return [_canon(item) for item in value]
    if isinstance(value, dict):
        return {key: _canon(item) for key, item in value.items()}
    return value


def _attachment_id(item) -> str:
    """An attachment is identified by what the tracker calls it, never by every field it has
    (a size or a URL can differ between two reads of the same file)."""
    if isinstance(item, dict):
        return str(item.get("id") or item.get("filename") or item.get("name")
                   or json.dumps(item, sort_keys=True))
    return str(item)


def _attachment_label(item) -> str:
    if isinstance(item, dict):
        return str(item.get("filename") or item.get("name") or item.get("id") or "")
    return str(item)


def _revision_of(ticket: dict):
    return ticket.get("revision") or None


def _fetched_at_of(ticket: dict):
    provenance = ticket.get("provenance")
    return (provenance.get("fetched_at") if isinstance(provenance, dict) else None) or None


def without_comments_section(description):
    """A pasted description holds its `## Comments` (or `h2. Comments`) section whole (nothing is cut at the entrance),
    and the comments are ALSO the `comments` field. `diff` compares the description without that section, so a new
    comment alone is `context` as before and is not read twice as a requirements change. The section is found by the
    ONE reader of sections (`scan_sections`: one form per text, `{code}` blocks never cut), the same one that
    parses the comments - so a text whose comments were read is a text whose comments are left out here. Only the lines
    that PARSED as comments (`_comment_match`), the heading and the blank lines of the section leave: a line in it that
    is no comment is the description's, and a change of it is a requirements change, not a context one (t-335 B-n1:
    the whole section used to go, and words pasted under `## Comments` that no comment parser reads vanished from the
    comparison). A text with no such section comes back as it was (line endings included), stripped."""
    if not isinstance(description, str):
        return description
    scan = scan_sections(description)
    drop = set()
    for position, (index, name) in enumerate(scan.heads):
        if name == "comments":
            end = scan.heads[position + 1][0] if position + 1 < len(scan.heads) else len(scan.lines)
            drop.add(index)
            drop.update(i for i in range(index + 1, end) if not scan.lines[i].strip() or _comment_match(scan.lines[i]))
    if not drop:
        return description.strip()
    return "\n".join(line for index, line in enumerate(scan.lines) if index not in drop).strip()


def diff_tickets(old_path: Path, new_path: Path) -> dict:
    """Field-by-field comparison of two ticket files, with a severity a stage can branch on.

    A story spans two human gates and hours or days between them; a description edited or an
    acceptance criterion dropped in that window invalidates the register, the plan and the
    cases that were built on the old text. `requirements` is that case. `context` (a new
    comment, a status move, an MR link appearing) is worth showing a human, not worth
    re-planning. Neither is a judgement a role should be making from memory."""
    for side, path in (("old", old_path), ("new", new_path)):
        if not path.exists():
            # Both files are the FACTORY's own snapshots (`get --json` writes them; the person handed over no file
            # here), so a missing one is a defect on our side, owner `factory` naming the file - never `person`,
            # which is what `read_ticket_file` says of a file the person named (t-335 B-n2, FR-3).
            fail(EXIT_NOT_FOUND, f"diff: the {side} ticket snapshot was not found: {path}. The factory writes it "
                 "(`ticket_adapter.py get <TICKET> --json`, saved as work/ticket-snapshot.json at S0); read the "
                 "ticket again to make it, then repeat the comparison.", owner="factory", file=str(path))
    result = diff_objects(read_ticket_file(old_path), read_ticket_file(new_path))
    result.update({"old": str(old_path), "new": str(new_path)})
    return result


def diff_objects(old_ticket: dict, new_ticket: dict) -> dict:
    """The comparison itself, on two normalized tickets (also what `freshness` runs in memory).

    Two formats meet here - Markdown and JSON - and the JSON carries keys the Markdown cannot
    (issue_links, remote_links, attachments). A key only one side has is listed as
    `not_comparable` and is never counted as a change: calling it one would report "the ticket
    moved" for every story whose snapshot and re-read came by different routes."""
    old, new = _canon(old_ticket), _canon(new_ticket)
    changed, detail = [], {}
    for field in REQUIREMENT_FIELDS + CONTEXT_FIELDS:
        if field == "links":
            # ONE links rule. A markdown snapshot knows two link keys; the direct API's JSON also carries the issue
            # and remote link lists. Comparing the two forms key for key reported a link change that was only one
            # side not having the list, so a key only one side has is listed (`not_comparable`) and never counted;
            # of the keys both sides carry, a moved value is the change.
            a, b = old.get("links") or {}, new.get("links") or {}
            only_one_side = sorted(set(a) ^ set(b))
            moved = [key for key in sorted(set(a) & set(b)) if a[key] != b[key]]
            if only_one_side:
                detail["links"] = {"not_comparable": only_one_side}
            if moved:
                changed.append("links")
                detail["links"] = dict(detail.get("links") or {},
                                       old={key: a[key] for key in moved},
                                       new={key: b[key] for key in moved})
            continue
        if field == "attachments":
            if ("attachments" in old) != ("attachments" in new):
                detail["attachments"] = {"not_comparable": True}
                continue
            if "attachments" not in old:
                continue
            a, b = old["attachments"] or [], new["attachments"] or []
            old_ids = {_attachment_id(x) for x in a}
            new_ids = {_attachment_id(x) for x in b}
            added = [_attachment_label(x) for x in b if _attachment_id(x) not in old_ids]
            removed = [_attachment_label(x) for x in a if _attachment_id(x) not in new_ids]
            if added or removed:
                changed.append(field)
                detail[field] = {"added": added, "removed": removed}
            continue
        a, b = old.get(field), new.get(field)
        if field == "description":
            a, b = without_comments_section(a), without_comments_section(b)
        if a == b:
            continue
        changed.append(field)
        if field == "acceptance_criteria":
            detail[field] = {"added": [x for x in b if x not in a],
                             "removed": [x for x in a if x not in b]}
        elif field == "comments":
            old_keys = {_comment_key(c) for c in a}
            new_keys = {_comment_key(c) for c in b}
            detail[field] = {"added": [c for c in b if _comment_key(c) not in old_keys],
                             "removed": [c for c in a if _comment_key(c) not in new_keys]}
        elif isinstance(a, str) and isinstance(b, str):
            detail[field] = {"old_chars": len(a), "new_chars": len(b)}
        else:
            detail[field] = {"old": a, "new": b}
    severity = ("requirements" if any(f in REQUIREMENT_FIELDS for f in changed)
                else "context" if changed else "none")
    # FR-41: a revision or a time nobody recorded is `null`, not a guess.
    return {"changed": changed, "severity": severity, "detail": detail,
            "old_revision": _revision_of(old_ticket), "new_revision": _revision_of(new_ticket),
            "old_fetched_at": _fetched_at_of(old_ticket), "new_fetched_at": _fetched_at_of(new_ticket)}


def print_diff(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if not result["changed"]:
        print("TICKET UNCHANGED")
        _print_not_comparable(result)
        return
    print(f"TICKET CHANGED ({result['severity']}): " + ", ".join(result["changed"]))
    for field in result["changed"]:
        info = result["detail"].get(field) or {}
        if "added" in info:
            print(f"  {field}: +{len(info['added'])} -{len(info['removed'])}")
            for item in info["added"]:
                text = item if isinstance(item, str) else item.get("text", "")
                print(f"    + {str(text)[:120]}")
        elif "old_chars" in info:
            print(f"  {field}: {info['old_chars']} -> {info['new_chars']} chars")
        else:
            print(f"  {field}: {info.get('old')!r} -> {info.get('new')!r}")
    _print_not_comparable(result)


def _print_not_comparable(result: dict) -> None:
    detail = result.get("detail") or {}
    names = [f"links.{key}" for key in (detail.get("links") or {}).get("not_comparable", [])]
    if (detail.get("attachments") or {}).get("not_comparable"):
        names.append("attachments")
    if names:
        print("  not comparable (only one side has them): " + ", ".join(names))


# --- freshness: did the ticket move since the snapshot? ----------------------------------------
# One command for both host paths, and no `.prev` copy: the older of the two tickets is the
# baseline file the story already keeps, the newer one is read now and held in memory. The old
# paragraph asked the orchestrator to write a `.prev` file nothing ever wrote (B-042).

def parse_time(value) -> datetime | None:
    """An ISO-8601 time as an aware datetime, or None when it is absent or unreadable. A time
    with no zone is read as UTC, `Z` as UTC, and `+0000` (Jira's own spelling) as `+00:00`."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def baseline_is_stale(fetched_at, now: datetime | None = None, hours: float = STALE_AFTER_HOURS) -> bool:
    """True when the baseline is OLDER than `hours` - exactly `hours` is not older. A baseline
    with no readable `fetched_at` counts as older: an unknown age is not a fresh one (FR-41)."""
    when = parse_time(fetched_at)
    if when is None:
        return True
    return (now or datetime.now(timezone.utc)) - when > timedelta(hours=hours)


def snapshot_paths(task_root: Path) -> tuple:
    """(baseline .json, waiting .next.json, old .md) under the task root's `work/`."""
    work = Path(task_root) / "work"
    return work / SNAPSHOT_NAME, work / NEXT_SNAPSHOT_NAME, work / LEGACY_SNAPSHOT_NAME


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def freshness_path(task_root: Path) -> Path:
    return Path(task_root) / "work" / FRESHNESS_NAME


def read_freshness(task_root: Path) -> tuple:
    """(record, problem). The record beside the snapshot: when the tracker was last compared and
    which change a person declined. An absent record is {} with no problem (a story in flight, the
    first run after this existed); an unreadable one is {} WITH a problem - never a failure."""
    path = freshness_path(task_root)
    if not path.is_file():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return {}, f"{path} is unreadable ({exc}); read as absent and rewritten by the next check"
    if not isinstance(data, dict):
        return {}, f"{path} is not a JSON object; read as absent and rewritten by the next check"
    return data, ""


def write_freshness(task_root: Path, record: dict) -> None:
    """Written by this command and by nothing else, atomically."""
    try:
        atomic_json(freshness_path(task_root), record)
    except OSError as exc:
        fail(EXIT_NOT_CONFIGURED, f"ticket_adapter: cannot write {freshness_path(task_root)}: {exc}")


# A check time this far ahead of the clock is not "just now": it reads as unknown, so the check is due
# (`check_is_due`, B-364 R14). Sixty seconds is the clock skew between two machines that share a project;
# it is not variety across projects, so it is a constant here and not a setting.
FUTURE_SLACK_SECONDS = 60


def stamp_is_ahead(value, now: datetime) -> bool:
    """True when `value` is a readable time more than FUTURE_SLACK_SECONDS after `now`: a stamp that cannot be the
    past is unknown (FR-41), never "just now". Exactly at the slack it is still read by time. An unreadable or absent
    value is not "ahead" - the callers already read that as unknown on their own."""
    when = parse_time(value)
    return when is not None and when - now > timedelta(seconds=FUTURE_SLACK_SECONDS)


def check_is_due(task_root: Path, now: datetime | None = None) -> bool:
    """The one trigger: is the last comparison older than 6 hours?

    Measured from the record's `checked_at`, falling back to the baseline's `fetched_at`, then to
    "older" (an unknown age is not a fresh one). `checked_at` exists because a `none` result must
    not rewrite the baseline - it has to stay what `get --json` printed - and without a stamp of
    its own every resume after 6 hours would fetch again.

    One exception, whatever `checked_at` says: a new snapshot WAITING in `.next.json` that the
    person has not declined is a question nobody has answered. `freshness` stamps `checked_at`
    before the caller asks it, so a crash in between would otherwise leave the story on the old
    text for 6 hours; it stays due until the person answers (adopt removes the file, decline
    records the mark). "Declined" means the mark's hash is the hash of THIS waiting text
    (`content_hash`, or `legacy_content_hash` for a mark an older run wrote): a mark for text X
    with a waiting text Y is a question about Y nobody has asked (B-364 R14), and an unreadable
    `.next.json` is unknown, which is due.

    Both new cases err toward "due" and only that way: this function was an advice for a skill
    (a prose rule) and is now the trigger of a code path (`story_run.Driver.ticket_freshness`),
    where a wrongly "not due" is a story that runs on a text nobody looked at and a wrongly "due"
    is one extra look. A stamp more than FUTURE_SLACK_SECONDS after `now` (a clock that was
    wrong when it was written) reads as unknown, not as fresh: exactly at the slack it is still
    read by time."""
    record, _ = read_freshness(task_root)
    _, nxt, _ = snapshot_paths(task_root)
    moment = now or datetime.now(timezone.utc)
    if nxt.is_file():
        waiting, _why = read_stored_snapshot(nxt)
        marked = (record.get("declined") or {}).get("hash")
        if waiting is None or not marked or marked not in (content_hash(waiting), legacy_content_hash(waiting)):
            return True
    if parse_time(record.get("checked_at")) is not None:
        measured = record.get("checked_at")
    else:
        baseline = find_baseline(task_root)
        measured = ((baseline["ticket"] or {}).get("provenance") or {}).get("fetched_at")
    return stamp_is_ahead(measured, moment) or baseline_is_stale(measured, moment)


def content_hash(ticket: dict) -> str:
    """The identity of the text a person was asked about: the REQUIREMENT fields only (title, type,
    description, acceptance criteria), strings canonical, keys sorted.

    Not the whole ticket: this hash is what a declined change is remembered by (FR-7), and a label,
    a status move or the tracker's own `revision` is not a change to what the story was built on.
    With the whole ticket in it, a decline lasted until the next relabel and the same question came
    back, the waiting file rewritten and a second `ticket_changed` journaled. A requirement field
    moves it; nothing else does."""
    canon = _canon(ticket)
    body = {field: canon.get(field) for field in REQUIREMENT_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def legacy_content_hash(ticket: dict) -> str:
    """What `content_hash` was before it covered the requirement fields only: the whole normalized
    ticket without `provenance`. A decline an older run recorded holds this value; it is still
    read (stories in flight), and nothing writes it any more."""
    body = {key: value for key, value in _canon(ticket).items() if key != "provenance"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def find_baseline(task_root: Path, ticket: str = "") -> dict:
    """The baseline the story's later reads are compared with.

    `work/ticket-snapshot.json` when it exists; else the readable `work/ticket-snapshot.md` of a
    story that predates it (JSON inside, or Markdown); else none. When both exist the `.json`
    wins and `ignored` names the other, so a caller can say which file it used (FR-25).
    Returns {"path", "ticket", "ignored", "problem"}: `problem` is set when the `.json` exists
    and cannot be read - it is not replaced behind anyone's back."""
    snap, _, legacy = snapshot_paths(task_root)
    found = {"path": None, "ticket": None, "ignored": [], "problem": ""}
    if snap.is_file():
        found["ticket"], why = read_stored_snapshot(snap, ticket)
        if found["ticket"] is not None:
            found["path"] = snap
        else:
            found["problem"] = (f"{why} - the baseline {snap} is not replaced; remove it to take a new baseline from "
                                "the ticket as it stands (that discards what the story was built on)")
        if legacy.is_file():
            found["ignored"].append(legacy)
        return found
    if legacy.is_file():
        found["ticket"], _why = read_stored_snapshot(legacy, ticket)
        if found["ticket"] is not None:
            found["path"] = legacy
        else:
            found["ignored"].append(legacy)  # unreadable: not a baseline, not touched
    return found


def read_stored_snapshot(path: Path, ticket: str = "") -> tuple:
    """(ticket, why) of a snapshot file the factory keeps (the baseline, the legacy `.md`, `.next.json`): the ticket,
    or None and the sentence when it cannot be read - never an exit, so a caller that only PROBES a file can say what
    is wrong and go on. The reading is `parse_ticket_json` / `parse_ticket_markdown`, the ONE reader's own, plus the
    one refusal the file reader does not make: a text that STARTS like JSON and cannot be decoded is unreadable, never
    handed to the markdown parser (it would read an empty ticket and call that a success)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path}: {exc}"
    parsed = parse_ticket_json(text, ticket)
    if parsed is not None:
        return parsed, ""
    if text.lstrip(chr(0xFEFF)).lstrip().startswith("{"):
        return None, (f"{path}: the text starts like JSON but is not a JSON object that can be decoded. A snapshot is "
                      "written by `ticket_adapter.py get <TICKET> --output <path>` and never by copying a "
                      "terminal's output (that mixes in stderr)")
    return parse_ticket_markdown(text, ticket or path.stem, source="file",
                                 headings=acceptance_headings_for(load_config())), ""


def fetch_ticket(ticket: str, ticket_file: str = "") -> dict:
    """The ticket as it stands now. With `ticket_file` (a story the person pasted): that file, read as the person's
    text (`pasted=True`, the semantics S0 reads it with) - and NEVER the tracker: the person's text is the story's
    requirement and comparing it with the tracker is the S0 comparison's job (FR-25, L1). Otherwise the configured
    adapter. A failure is `fail()` with the exit code `get` gives (1 not found, 3 not configured)."""
    if ticket_file:
        return read_ticket_file(Path(ticket_file), ticket, pasted=True)
    if local_keys.is_local(ticket):      # a local story's text is its file, never a tracker's answer (SS1-14)
        return read_ticket_file(local_keys.ticket_path(ticket), ticket, pasted=True)
    return get_ticket(ticket, load_config())


def journal_ticket_changed(ticket: str, severity: str, changed: list) -> str:
    """The `ticket_changed` event, through the journal's single writer (log_append). Returns
    "" when it landed, the reason when it did not: a ticket check never fails for a journal."""
    try:
        import log_append
        record = log_append.build_record({"event": "ticket_changed", "task": ticket,
                                          "notes": f"{severity}: {', '.join(changed)}"})
        problems = log_append.validate(record)
        if problems:
            return "; ".join(problems)
        # log_append.write prints its own "OK: ..." line; stdout is this command's contract.
        with contextlib.redirect_stdout(io.StringIO()):
            log_append.write([record])
        return ""
    except SystemExit as exc:
        return f"the journal writer exited {exc.code}"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _waits_with_this_text(nxt: Path, new: dict) -> bool:
    """True when `.next.json` holds a snapshot with the same REQUIREMENTS as `new` (the same
    `content_hash`). An absent or unreadable file waits with nothing."""
    if not nxt.is_file():
        return False
    waiting, _why = read_stored_snapshot(nxt)
    return waiting is not None and content_hash(waiting) == content_hash(new)


def freshness_check(ticket: str, task_root: Path, ticket_file: str = "") -> dict:
    """Read the ticket now, compare it with the baseline, settle the files, say what happened.

    result = baseline_written | none | context | requirements. Only the severity decides:
      * no baseline  -> the ticket as read becomes the baseline (nothing to compare, nothing journaled);
      * none         -> nothing is written;
      * context      -> the baseline is replaced by the new snapshot (a person reads it, nothing is
                        re-planned), and `ticket_changed` is journaled;
      * requirements -> the baseline is KEPT - the plan was built on it - and the new snapshot waits
                        as `ticket-snapshot.next.json` until `--adopt` after the person's answer;
                        `ticket_changed` is journaled.
    A waiting snapshot that a later check settles (none, context) is removed, so `--adopt` can
    never adopt text older than the last look. A failed fetch exits with the code `get` gives and
    touches nothing - the record's `checked_at` included: a failed look is not a look.

    Every successful check stamps `work/ticket-freshness.json` (`checked_at`, `result`): the
    6-hour trigger is measured from it, because a `none` result leaves the baseline alone. After
    `--decline` the record also holds the hash of the declined REQUIREMENT fields; a later fetch
    whose requirements are those is `requirements` with `already_answered: true` - not written
    again, not journaled, not put to the person again (FR-7), whatever a label or a status did
    meanwhile. Any other outcome clears the mark."""
    snap, nxt, _ = snapshot_paths(task_root)
    found = find_baseline(task_root, ticket)
    if found["problem"]:
        fail(EXIT_NOT_CONFIGURED, found["problem"])
    record, problem = read_freshness(task_root)
    if problem:
        print(f"ticket_adapter: {problem}", file=sys.stderr)
    if not ticket_file and local_keys.is_local(ticket) and not local_keys.ticket_path(ticket).is_file():
        # Marked local, its text file gone: the key is nobody else's text. Never ask a tracker for it (a real project may
        # own a `LOCAL-1`); the snapshot stands and nothing is written, not even a look (stdout is the result's).
        print("local story: its text file is not here; the snapshot stands", file=sys.stderr)
        return {"result": "none", "severity": None, "changed": [], "detail": {}, "revisions": {}, "baseline": str(found["path"] or snap),
                "next": None, "journaled": None, "ignored": [str(p) for p in found["ignored"]]}
    new = fetch_ticket(ticket, ticket_file)
    ignored = [str(p) for p in found["ignored"]]
    stamp = {"checked_at": now_iso()}
    if found["ticket"] is None:
        write_snapshot(new, snap)
        nxt.unlink(missing_ok=True)
        write_freshness(task_root, dict(stamp, result="baseline_written"))
        return {"result": "baseline_written", "severity": None, "changed": [], "detail": {},
                "revisions": {"old_revision": None, "new_revision": _revision_of(new),
                              "old_fetched_at": None, "new_fetched_at": _fetched_at_of(new)},
                "baseline": str(snap), "next": None, "journaled": None, "ignored": ignored}
    verdict = diff_objects(found["ticket"], new)
    severity = verdict["severity"]
    waiting, journaled, extra = None, None, {}
    declined = record.get("declined") if isinstance(record.get("declined"), dict) else {}
    if severity == "requirements" and declined.get("hash") in (content_hash(new), legacy_content_hash(new)):
        # The person has answered this very text: it is reported, never asked again.
        if not nxt.is_file():
            write_snapshot(new, nxt)
        waiting = str(nxt)
        stamp["declined"] = declined
        extra = {"already_answered": True, "declined_at": declined.get("at")}
    elif severity == "requirements" and _waits_with_this_text(nxt, new):
        # The same text again, with nobody having answered: the file is not rewritten and nothing is
        # journaled a second time. The driver is protected by `state.asked`; the skill path resumes
        # and calls this again with nothing between, and put the same `ticket_changed` line twice.
        waiting = str(nxt)
        extra = {"still_waiting": True}
    elif severity == "requirements":
        write_snapshot(new, nxt)
        waiting = str(nxt)
    else:
        if severity == "context":
            write_snapshot(new, snap)
        nxt.unlink(missing_ok=True)
    if severity in ("context", "requirements") and not extra:
        why_not = journal_ticket_changed(ticket, severity, verdict["changed"])
        journaled = not why_not
        if why_not:
            print(f"ticket_adapter: the ticket_changed event was not journaled ({why_not})",
                  file=sys.stderr)
    write_freshness(task_root, dict(stamp, result=severity))
    return dict({"result": severity, "severity": severity, "changed": verdict["changed"],
                 "detail": verdict["detail"],
                 "revisions": {key: verdict[key] for key in ("old_revision", "new_revision",
                                                             "old_fetched_at", "new_fetched_at")},
                 "baseline": str(found["path"] if severity != "context" else snap),
                 "next": waiting, "journaled": journaled, "ignored": ignored}, **extra)


def freshness_adopt(ticket: str, task_root: Path) -> dict:
    """After the person's answer: the snapshot that waited as `.next.json` becomes the
    baseline, and a declined mark is cleared (the new text is the story's now). With nothing
    waiting it refuses (exit 2) and says so - never a silent success."""
    snap, nxt, _ = snapshot_paths(task_root)
    if not nxt.is_file():
        fail(EXIT_USAGE, f"nothing to adopt: {nxt} does not exist. A new snapshot waits there only "
                         "after `freshness` found a change to the requirements and no later check "
                         "settled it; run `freshness` again to look at the ticket now.")
    adopted, why = read_stored_snapshot(nxt, ticket)
    if adopted is None:
        fail(EXIT_NOT_CONFIGURED, f"{why} - nothing was adopted and the baseline is unchanged; run `freshness` again "
                                  "to read the ticket now.")
    old = find_baseline(task_root, ticket)["ticket"]
    moved = diff_objects(old, adopted)["changed"] if old else []
    write_snapshot(adopted, snap)
    nxt.unlink()
    record, _ = read_freshness(task_root)
    if record.get("declined") is not None:
        write_freshness(task_root, {k: v for k, v in record.items() if k != "declined"})
    return {"result": "adopted", "severity": None, "changed": [], "detail": {},
            "revisions": {"old_revision": None, "new_revision": _revision_of(adopted),
                          "old_fetched_at": None, "new_fetched_at": _fetched_at_of(adopted)},
            "baseline": str(snap), "next": None, "journaled": _journal_decision(ticket, "adopted", moved),
            "ignored": []}


def _journal_decision(ticket: str, word: str, changed: list) -> bool:
    """`ticket_changed` with notes `adopted: <fields>` or `declined: <fields>`: which of the two
    moves ran is visible in the journal, beside the `requirements: <fields>` line that asked."""
    why_not = journal_ticket_changed(ticket, word, changed)
    if why_not:
        print(f"ticket_adapter: the {word} decision was not journaled ({why_not})", file=sys.stderr)
    return not why_not


def journal_human_answer(ticket: str, stage: str, text: str) -> None:
    """The `human_answer` line `waiver.py --remark` writes beside the remark, in its words: the
    person's answer is in the journal as well as in `pipeline.json`. Never a failure: the remark
    is on disk already, and a journal that cannot be written is said on stderr."""
    try:
        import log_append
        record = log_append.build_record({"event": "human_answer", "task": ticket,
                                          "notes": f"{stage} remark kept for the gate: {text}"})
        problems = log_append.validate(record)
        if problems:
            raise ValueError("; ".join(problems))
        with contextlib.redirect_stdout(io.StringIO()):
            log_append.write([record])
    except (Exception, SystemExit) as exc:
        print(f"ticket_adapter: the decline's words were kept in pipeline.json but not journaled ({exc})",
              file=sys.stderr)


def keep_decline_words(ticket: str, task_root: Path, words: str) -> None:
    """The person's words about continuing on the old text, kept where the next gate reads them.

    "Continue on the old text, with that stated as a known gap" is a decision, and nothing read the
    mark `--decline` left (a hash): the gate could not say the story ran on a text the tracker had
    left behind (FR-8, FR-9). So the words become a `remarks[]` entry of `pipeline.json` - built by
    `waiver.apply_remark`, the function `waiver.py --remark` uses, so the shape is one (FR-17) -
    and `gate_brief` shows it as "remark kept, not re-asked". The stage is the one the
    `ticket_changed` question is asked at (S0). A story with no `pipeline.json` has no gate to carry
    the words to: refused (exit 2), nothing recorded, because a decline whose words went nowhere is
    the silent pass FR-4 forbids."""
    path = Path(task_root) / "pipeline.json"
    try:
        pipeline = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pipeline = None
    if not isinstance(pipeline, dict) or not pipeline:
        fail(EXIT_USAGE, f"ticket_adapter: no readable pipeline.json at {path}: the words of a decline are "
                         "kept there as a remark for the next gate, so a decline belongs to a story that "
                         "exists. Nothing was recorded; run it again from the story's folder "
                         "(--task-root qa-factory/artifacts/<TICKET>).")
    waiver.apply_remark(pipeline, DECLINE_STAGE, words.strip(), now_iso(), "human")
    try:
        atomic_json(path, pipeline)
    except OSError as exc:
        fail(EXIT_NOT_CONFIGURED, f"ticket_adapter: cannot write {path}: {exc}. Nothing was recorded.")
    journal_human_answer(ticket, DECLINE_STAGE, words.strip())


def freshness_decline(ticket: str, task_root: Path, words: str) -> dict:
    """After the person chose to continue on the old text: keep their words (`keep_decline_words`)
    and remember WHICH new text they declined (the content hash of the waiting snapshot's
    requirement fields, and when), so the same change is not put to them again. The baseline and
    the waiting file stay as they are; a different change to the requirements later is a new
    question. With nothing waiting it refuses (exit 2) and says so; so it does with no words (the
    caller resolves them first, `main`). Nothing is recorded by a refusal."""
    snap, nxt, _ = snapshot_paths(task_root)
    if not nxt.is_file():
        fail(EXIT_USAGE, f"nothing waits: {nxt} does not exist, so there is no new text to decline. "
                         "Run `freshness` to look at the ticket now; a change to the requirements "
                         "leaves its text there.")
    waiting, why = read_stored_snapshot(nxt, ticket)
    if waiting is None:
        fail(EXIT_NOT_CONFIGURED, f"{why} - nothing was declined and nothing was recorded; run `freshness` again "
                                  "to read the ticket now.")
    record, _ = read_freshness(task_root)
    old = find_baseline(task_root, ticket)["ticket"]
    moved = diff_objects(old, waiting)["changed"] if old else []
    keep_decline_words(ticket, task_root, words)
    # The mark also carries what gate B says about the gap, written by code from this record and
    # not read from anybody's wording: when the declined text was read, which REQUIREMENT fields
    # moved, and the person's words (gate_brief.open_before_mr). An older mark has none of these
    # and gets no such line.
    mark = {"hash": content_hash(waiting), "at": now_iso(), "fetched_at": _fetched_at_of(waiting),
            "changed": [field for field in moved if field in REQUIREMENT_FIELDS], "words": words.strip()}
    write_freshness(task_root, dict(record, declined=mark))
    return {"result": "declined", "severity": None, "changed": [], "detail": {},
            "revisions": {"old_revision": None, "new_revision": _revision_of(waiting),
                          "old_fetched_at": None, "new_fetched_at": _fetched_at_of(waiting)},
            "baseline": str(snap), "next": str(nxt), "ignored": [], "declined": mark,
            "journaled": _journal_decision(ticket, "declined", moved)}


def print_freshness(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    kind = result["result"]
    if kind == "baseline_written":
        print(f"baseline written: {result['baseline']}")
    elif kind == "adopted":
        print(f"adopted: {result['baseline']} now holds the new text")
    elif kind == "declined":
        print(f"declined: the text in {result['next']} is remembered as answered; "
              "the baseline is unchanged")
    elif kind == "none":
        print("TICKET UNCHANGED")
    else:
        print_diff(dict(result, old="", new=""), False)
        if result.get("already_answered"):
            print(f"this new text was declined on {result.get('declined_at')}; not asked again")
        elif result.get("still_waiting"):
            print(f"this new text already waits in {result['next']}, unanswered; nothing was "
                  "written or journaled again")
        elif kind == "requirements":
            print(f"the new text waits in {result['next']}; the baseline is unchanged until "
                  "`freshness <TICKET> --task-root <root> --adopt` (or `--decline --words-file <file>`)")


def settle_role_files(result: dict, task_root: Path) -> None:
    """After `--adopt` or a `context` replace the baseline is a new text, and the files a role reads beside it are
    older than it. `work/ticket-view.md` is re-rendered from the new baseline through upstream's own renderer
    (`source_inventory.ticket_view_text`, atomically) when the story HAS that file - a story that never had one gets
    none created, and `ticket-raw/` and `source-inventory.json` are not touched. `work/ticket-references.json` has no
    renderer that works from a snapshot dict alone (`build_references` needs a tracker client and the story's known
    prefixes), so when it exists ONE line on stderr (stdout is the result's, FR-14) names it as stale and says where
    the current text is (FR-41: an unknown is never reported as a fact). Both only for the two results that replace
    the baseline."""
    if result.get("result") not in ("adopted", "context"):
        return
    work = Path(task_root) / "work"
    view, references = work / "ticket-view.md", work / "ticket-references.json"
    if view.is_file():
        current, why = read_stored_snapshot(work / SNAPSHOT_NAME)
        try:
            if current is None:
                raise ValueError(why)
            SI._atomic_write(view, SI.ticket_view_text(current).encode("utf-8"))
        except (OSError, ValueError) as exc:
            print(f"ticket_adapter: the snapshot was replaced, but {view} could not be written again ({exc}) and "
                  f"still holds the text it replaced - read {work / SNAPSHOT_NAME} for the current text.",
                  file=sys.stderr)
    if references.is_file():
        print(f"ticket_adapter: the snapshot was replaced, but {references} still holds the references of the "
              f"text it replaced - read {work / SNAPSHOT_NAME} for the current text, not that file.", file=sys.stderr)


# --- dispatch -------------------------------------------------------------------------------

def resolve_adapter(cfg: dict) -> tuple[str, dict]:
    adapter_cfg = ((cfg.get("adapters") or {}).get("ticket")) or {}
    return AF.ticket_kind(cfg), adapter_cfg   # the one reader of the tracker kind (B-405)


def references_context(cfg: dict) -> dict:
    """What `ticket_light.references` needs from the project's config to tie a merge request to a
    repository and to tell a link on a known host from one the person must look at: the repositories
    (`implementation_repos[]` with `repo_id`, `local_path`, `remote_identity`; else `code_repos[]`
    read as `{repo_id: name, local_path: path}`) and every known host - the tracker's own is added by
    the reader, then `remote_identity` / `url` / `remote` of the repositories and `base_url` of the
    environments."""
    repos = [dict(r) for r in cfg.get("implementation_repos") or [] if isinstance(r, dict) and r.get("repo_id")]
    if not repos:
        repos = [{"repo_id": r.get("name"), "local_path": r.get("path"), **{k: r[k] for k in ("remote_identity",) if r.get(k)}}
                 for r in cfg.get("code_repos") or [] if isinstance(r, dict) and r.get("name")]
    hosts = []
    for entry in list(cfg.get("implementation_repos") or []) + list(cfg.get("code_repos") or []):
        if isinstance(entry, dict):
            hosts += [entry[k] for k in ("remote_identity", "url", "remote") if isinstance(entry.get(k), str) and entry[k]]
    hosts += [env["base_url"] for env in cfg.get("environments") or []
              if isinstance(env, dict) and isinstance(env.get("base_url"), str) and env["base_url"]]
    return {"repos": repos, "known_hosts": hosts}


UNPROVEN_REASON = "no tracker read at S0"


def paste_texts(path: Path, ticket_obj: dict) -> dict:
    """The person's own text, by origin, for the reference scan: the title line (`mention:summary`) and the
    whole body after the front matter (`mention:description` - criteria and comments included, so nothing the
    person wrote escapes the scan). A JSON snapshot handed over as the file has no body: its fields are
    scanned instead."""
    text = path.read_text(encoding="utf-8")
    if parse_ticket_json(text, "") is None:
        return {"mention:summary": str(ticket_obj.get("title") or ""), "mention:description": strip_frontmatter(text)[1]}
    texts = {"mention:summary": str(ticket_obj.get("title") or ""),
             "mention:description": "\n".join([str(ticket_obj.get("description") or "")]
                                              + [str(item) for item in ticket_obj.get("acceptance_criteria") or []])}
    for number, comment in enumerate(ticket_obj.get("comments") or [], 1):
        texts[f"mention:comment:{number}"] = str((comment or {}).get("text") or "")
    return texts


def write_paste_references(path: Path, ticket_obj: dict, cfg: dict, key: str, work: Path) -> None:
    """The paste-only leg of S0 (t-281 F4): no tracker was read, so the references of the story's text come
    from the PERSON's text - `ticket_light.references`, the scan the REST route runs - and
    `work/ticket-references.json` is written with `written_by: [S0]`. A ticket row is `unproven` ("no tracker
    read at S0": S1 `collect` probes it as any other row once the tracker answers); the rest keep the statuses
    the scan gives. No reference at all is still written, as an empty list (FR-23: the null outcome is a
    result). A tracker read that comes after this call and succeeds rewrites the whole file from the
    tracker's text, so the person's text is never scanned into a second set of rows."""
    kinds = TL.load_reference_kinds()
    _kind, adapter_cfg = resolve_adapter(cfg)
    try:
        form = AF.key_form(cfg)    # the project's key shape; a table that cannot be read is the factory's fault, exit 4
    except AF.FormsTableError as exc:
        raise TL.TableError(str(exc)) from None
    direct = adapter_cfg.get("direct_api") if isinstance(adapter_cfg.get("direct_api"), dict) else {}
    context = references_context(cfg)
    hosts = list(context["known_hosts"]) + ([direct["base_url"]] if direct.get("base_url") else [])
    def prefix_set(value) -> set:
        """A prefix is a prefixed form's fact: a prefix-less one (bare numbers) has none to probe or to tag."""
        found = AF.prefix_of(value, form)
        return {found.upper()} if found else set()

    known = prefix_set(key)
    configured = adapter_cfg.get("project_keys")
    if form.prefixed:
        known |= {str(p).strip().upper() for p in (configured if isinstance(configured, list) else []) if str(p).strip()}
    seeded = []
    parent = str(ticket_obj.get("parent") or "").split()
    if parent and form.strict.fullmatch(parent[0]):
        known |= prefix_set(parent[0])
        seeded.append({"ref": parent[0], "origins": ["field:parent"]})
    rows = TL.references(paste_texts(path, ticket_obj), known_prefixes=known,
                         not_tracker_prefixes=SI.not_tracker_prefixes(), reference_kinds=kinds,
                         known_hosts=hosts, repos=context["repos"], seeded=seeded, own_key=key, key_form=form)
    for row in rows:
        if row.get("kind") == "ticket":
            row["status"], row["reason"] = "unproven", UNPROVEN_REASON
    document = {"schema_version": 1, "ticket": key, "written_by": ["S0"], "provenance": {"source": "person_pasted"},
                "scanned": ["summary", "description"], "rows": rows}
    SI._atomic_write(work / "ticket-references.json",
                     json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")


def traced_client(adapter_cfg: dict, ticket: str, cfg: dict | None = None):
    """The direct client for one command: every REST call it makes is a `command` span in
    `qa-factory/state/telemetry/command-<pid>.jsonl` (the file run_suite.py's spans use; fail-silent), and
    the project's repositories and hosts are on it for the references."""
    client = client_from_config(adapter_cfg)
    try:
        client.telemetry_path = project_root() / "qa-factory" / "state" / "telemetry" / f"command-{os.getpid()}.jsonl"
        client.telemetry_task = ticket
    except Exception:  # noqa: BLE001 - telemetry never fails a read
        pass
    client.references_context = references_context(cfg if cfg is not None else load_config())
    return client


def refuse_unsupported_auth_type(client) -> None:
    """The recorded `direct_api.auth_type` is one the client cannot send: the PROJECT's setting to complete (exit 3,
    owner `config`), asked of the client itself before any request - `JiraClient._headers` is the judge of what it
    can send, so this list cannot drift from it. Reached through the read, that refusal came out as a FetchError and
    read as "the tracker could not be read ... retry": a sentence about the network for a fault no retry mends. A
    missing credential variable is NOT this refusal (the client checks the type first, then the credentials; the
    read turns the missing variable into `AuthLost`, the login's exit)."""
    probe = getattr(client, "_headers", None)
    if not callable(probe):
        return
    try:
        probe()
    except MissingCredential:
        return
    except FetchError as exc:
        fail(EXIT_NOT_CONFIGURED,
             f"the tracker's direct API setting adapters.ticket.direct_api.auth_type is "
             f"'{getattr(client, 'auth_type', '')}', which this factory cannot send ({exc.reason}) - set it to one of "
             f"{', '.join(DIRECT_API_AUTH_TYPES)} in qa-factory/config.json, or run /qa-factory:qa-onboarding to "
             "record it. Nothing was requested.", owner="config")


def get_ticket(ticket: str, cfg: dict, raw_dir: Path | None = None, say=None) -> dict:
    kind, adapter_cfg = resolve_adapter(cfg)
    if not kind:
        fail(EXIT_NOT_CONFIGURED,
             "no ticket adapter configured (adapters.ticket in qa-factory/config.json) — "
             "run qa-onboarding.", owner="config")
    if kind == "file":
        return get_file(ticket, adapter_cfg)
    require_direct_read(adapter_cfg, "get")
    if kind in COMMAND_ADAPTERS:
        if kind == "jira" and adapter_cfg.get("direct_api"):
            if not has_usable_direct_api(adapter_cfg):
                # t-287 item 2: a recorded but unusable `direct_api` (the template's stub on an old config) is
                # the PROJECT's setting to complete, not the factory's fault and not the network: exit 3, owner
                # `config`, and the sentence names the missing keys and the onboarding door.
                fail(EXIT_NOT_CONFIGURED, direct_api_not_usable_message(adapter_cfg), owner="config")
            client = traced_client(adapter_cfg, ticket, cfg)
            refuse_unsupported_auth_type(client)
            return jira_ticket(client, ticket, raw_dir, say=say, context=client.references_context)
        return get_via_command(kind, ticket, adapter_cfg)
    fail(EXIT_NOT_CONFIGURED,
         f"unknown ticket adapter '{kind}' — supported: file, {', '.join(COMMAND_ADAPTERS)}", owner="config")
    return {}  # unreachable


# --- method migration (onboarding meeting an old config) --------------------------

def migrate_method(path: Path) -> tuple[dict, dict]:
    """Rewrite adapters.ticket.method to "api" once direct_api makes an "agent"/"skill"
    method stale for READING (require_direct_read now reads through direct_api regardless
    of method, but a config still saying "agent" documents a read route that no longer
    matches what happens — onboarding calls this the moment it meets one, so the config
    tells the truth again). Never touches a config with no usable direct_api, or one whose
    method already says something else: this is a one-way label fix, not a config writer.

    Returns (new_cfg, result); result = {"path", "old_method", "new_method", "changed"}."""
    cfg = json.loads(path.read_text(encoding="utf-8"))
    adapter_cfg = dict(((cfg.get("adapters") or {}).get("ticket")) or {})
    old_method = str(adapter_cfg.get("method") or "").strip().lower()
    result = {"path": str(path), "old_method": old_method or None,
              "new_method": old_method or None, "changed": False}
    if old_method in ("agent", "skill") and has_usable_direct_api(adapter_cfg):
        adapter_cfg["method"] = "api"
        adapters = dict(cfg.get("adapters") or {})
        adapters["ticket"] = adapter_cfg
        cfg["adapters"] = adapters
        result["new_method"] = "api"
        result["changed"] = True
    return cfg, result


def print_result(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
        return
    if isinstance(obj, list):
        if not obj:
            print("(no subtasks)")
        for row in obj:
            print(f"{row.get('key', '?')}\t{row.get('status', '?')}")
        return
    print(f"{obj.get('key')}\t{obj.get('type')}\t{obj.get('status')}\t{obj.get('title')}")
    print(f"AC: {len(obj.get('acceptance_criteria', []))}  "
          f"comments: {len(obj.get('comments', []))}  "
          f"subtasks: {len(obj.get('subtasks', []))}")


# --- selftest ---------------------------------------------------------------------------------

def selftest() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    fixtures_dir = PLUGIN_ROOT / "evals" / "fixtures" / "tickets"
    obj = get_file("QA-1", {"path": str(fixtures_dir)})

    check("schema keys present", all(k in obj for k in SCHEMA_KEYS))
    check("key == QA-1", obj.get("key") == "QA-1")
    check("type == Story", obj.get("type") == "Story")
    check("status == 'In Review'", obj.get("status") == "In Review")
    check("title non-empty", bool(obj.get("title")))
    check("description non-empty", bool(obj.get("description")))
    check("5 acceptance criteria", len(obj.get("acceptance_criteria", [])) == 5)
    check("2 comments", len(obj.get("comments", [])) == 2)
    comments = obj.get("comments", [])
    if len(comments) == 2:
        check("comment 1 author == po", comments[0].get("author") == "po")
        check("comment 1 date == 2026-09-10", comments[0].get("date") == "2026-09-10")
        check("comment 2 author == dev", comments[1].get("author") == "dev")
    check("links.merge_request == feature/qa-1",
          obj.get("links", {}).get("merge_request") == "feature/qa-1")
    check("subtasks is a list", isinstance(obj.get("subtasks"), list))

    check("provenance defaults to file", obj.get("provenance", {}).get("source") == "file")

    # --ticket-file reads a path directly, with no adapter config in play at all.
    direct = read_ticket_file(fixtures_dir / "QA-1.md", "QA-1")
    check("--ticket-file parse equals the file adapter's", direct == obj)

    # diff: the same file has not moved; an edited acceptance criterion is a REQUIREMENTS move.
    same = diff_tickets(fixtures_dir / "QA-1.md", fixtures_dir / "QA-1.md")
    check("diff of a file with itself: severity none", same["severity"] == "none")
    check("diff of a file with itself: nothing changed", same["changed"] == [])

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        text = (fixtures_dir / "QA-1.md").read_text(encoding="utf-8")
        edited = Path(tmp) / "QA-1.md"
        edited.write_text(text.replace("at most 5 tags", "at most 7 tags")
                          + "\n- **po** (2026-09-13): one more thought.\n", encoding="utf-8")
        moved = diff_tickets(fixtures_dir / "QA-1.md", edited)
        check("diff: an edited AC is a requirements move", moved["severity"] == "requirements")
        check("diff: acceptance_criteria is named", "acceptance_criteria" in moved["changed"])
        check("diff: the new comment is reported as added",
              len(moved["detail"].get("comments", {}).get("added", [])) == 1)

        comment_only = Path(tmp) / "QA-2.md"
        comment_only.write_text(text + "\n- **po** (2026-09-13): one more thought.\n",
                                encoding="utf-8")
        ctx = diff_tickets(fixtures_dir / "QA-1.md", comment_only)
        check("diff: a new comment alone is context, not requirements",
              ctx["severity"] == "context")

        # The story's snapshot is the JSON `get --json` prints (FR-49): read by --ticket-file and
        # by diff, with or without the stderr line older snapshots carry after the object. It is
        # written by `write_snapshot` (the ONE format, `snapshot_bytes`: UTF-8, LF everywhere).
        snap = Path(tmp) / "snap" / SNAPSHOT_NAME
        write_snapshot(obj, snap)
        check("snapshot: the file holds exactly snapshot_bytes, with no CR",
              snap.read_bytes() == snapshot_bytes(obj) and b"\r" not in snap.read_bytes())
        check("a JSON snapshot reads as the same ticket", read_ticket_file(snap, "QA-1") == obj)
        check("snapshot: Markdown against its own JSON is none (formats compare)",
              diff_tickets(fixtures_dir / "QA-1.md", snap)["severity"] == "none")
        inside_md = Path(tmp) / "in-flight.md"
        inside_md.write_text(snap.read_text(encoding="utf-8"), encoding="utf-8")
        check("snapshot: JSON inside a .md is read as JSON", read_ticket_file(inside_md, "QA-1") == obj)
        check("freshness: a baseline exactly 6 h old is not stale",
              not baseline_is_stale("2026-09-20T06:00:00+00:00",
                                    datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)))
        check("freshness: one with no fetched_at counts as older", baseline_is_stale(None))
        tail = Path(tmp) / "ticket-snapshot-tail.json"
        tail.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\nWARN: a stderr line\n",
                        encoding="utf-8")
        check("a JSON snapshot with a stderr tail reads the same (legacy files)",
              read_ticket_file(tail, "QA-1") == obj)
        thin = Path(tmp) / "thin.json"
        thin.write_text(json.dumps({"key": "QA-1", "title": "T", "extra": 1}), encoding="utf-8")
        got = read_ticket_file(thin, "QA-1")
        check("a JSON snapshot missing schema keys gets the markdown parser's defaults",
              got["acceptance_criteria"] == [] and got["comments"] == [] and got["parent"] is None
              and got["links"] == {"merge_request": None, "branch": None})
        check("and a key the schema does not name is kept", got.get("extra") == 1)
        check("diff of a JSON snapshot with itself: nothing changed",
              diff_tickets(snap, snap)["severity"] == "none")
        check("diff of a JSON snapshot with its stderr-tail twin: nothing changed",
              diff_tickets(snap, tail)["severity"] == "none")
        api = dict(obj, links={"merge_request": "feature/qa-1", "branch": None,
                               "issue_links": [], "remote_links": []})
        api_snap = Path(tmp) / "api.json"
        api_snap.write_text(json.dumps(api), encoding="utf-8")
        check("markdown against direct-API JSON: the extra link lists are not a link change",
              "links" not in diff_tickets(fixtures_dir / "QA-1.md", api_snap)["changed"])
        moved_link = Path(tmp) / "moved-link.json"
        moved_link.write_text(json.dumps(dict(api, links=dict(api["links"], merge_request="other"))),
                              encoding="utf-8")
        check("but a moved merge request still is one",
              "links" in diff_tickets(fixtures_dir / "QA-1.md", moved_link)["changed"])
    check("snapshot_hint names the JSON snapshot",
          snapshot_hint("QA-1") == "qa-factory/artifacts/QA-1/work/ticket-snapshot.json")

    # not-configured path never crashes: empty config -> SystemExit(3), not a traceback.
    try:
        get_ticket("QA-1", {})
        check("empty config exits (did not return)", False)
    except SystemExit as e:
        check("empty config -> exit 3", e.code == EXIT_NOT_CONFIGURED)

    # a tracker reached through a session agent: refused for READING, with the route
    # that does work. Not a hint to fetch it by hand: that route lost S1 its sources.
    from contextlib import redirect_stderr

    def agent_failure(adapter_cfg: dict) -> str:
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                get_ticket("QA-1", {"adapters": {"ticket": adapter_cfg}})
        except SystemExit as e:
            check("agent method -> exit 3", e.code == EXIT_NOT_CONFIGURED)
            return err.getvalue()
        check("agent method exits (did not return)", False)
        return ""

    msg = agent_failure({"name": "jira", "method": "agent", "invoke": "jira-assistant"})
    check("agent read: names the agent it refuses", "jira-assistant" in msg)
    check("agent read: names direct_api as the read route", "direct_api" in msg)
    check("agent read: names the onboarding command", "qa-onboarding" in msg)
    check("agent read: keeps the write channel open", "external_writes" in msg)
    check("agent read: no longer sends anyone to hand-write a snapshot",
          "ticket-snapshot" not in msg)

    msg = agent_failure({"name": "jira", "method": "skill", "invoke": "jira-skill"})
    check("skill read is refused the same way", "direct_api" in msg)

    msg = agent_failure({"name": "jira", "method": "agent"})
    check("agent read with no invoke still names direct_api", "direct_api" in msg)

    msg = agent_failure({"name": "jira", "method": "carrier-pigeon"})
    check("an unknown method is refused by name", "carrier-pigeon" in msg)

    ok = not failures
    print(f"=== SELFTEST ticket_adapter: {'PASSED' if ok else f'FAILED ({len(failures)})'} ===")
    return 0 if ok else 1



def _holds_inventory(path: Path) -> bool:
    """True when the file is a source inventory (sources array) - a probe receipt must not
    replace it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get("sources"), list)


def _s1_closed(task_root: Path) -> bool:
    """Is S1 of the story closed: `pipeline.json` `stages.S1.status == "done"` (the controller's projection). No file: not
    closed. A file that cannot be read: closed - the safe side of t-114 G3 (a closed S1 is never blocked again)."""
    path = task_root / "pipeline.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return ((data.get("stages") or {}).get("S1") or {}).get("status") == "done"
    except (OSError, ValueError, AttributeError):
        return True


def _accept_gap_kind(args, words: str) -> int:
    """`accept-gap --cause <c>[,<c>]` / `--revoke GC-n` (C2-9): the person's word about a whole KIND of gap, kept in
    `work/gap-classes.json` - NOT in the inventory, so the inventory's bytes and the hash Gate A bound do not change. The one
    door; the role has no path to it (guard_pre_tool refuses `accept-gap` to a role)."""
    from source_inventory import (completeness, gap_points, load_inventory, live_gap_classes, record_gap_class,
                                  revoke_gap_class)
    forms = ("usage: ticket_adapter.py accept-gap --output <inventory> --cause <cause>[,<cause>...] --words-file <file> "
             "[--shown-text \"<the question line>\"]  |  accept-gap --output <inventory> --revoke GC-n --words-file <file>"
             " - --cause and --revoke stand alone: not with --source-id, --point, --all-unavailable (nor with each other)")
    if (not args.output or (args.cause is not None) == (args.revoke is not None)
            or args.source_id or args.point is not None or args.all_unavailable):
        print(forms, file=sys.stderr)
        return 2
    output = Path(args.output)
    task_root = output.parent.parent
    try:
        if args.revoke is not None:
            row, problem = revoke_gap_class(output, args.revoke.strip(), words, _s1_closed(task_root))
            if problem:
                print(f"ticket_adapter: gap acceptance rejected: {problem}", file=sys.stderr)
                return 2 if "cannot be taken back" in problem else EXIT_NOT_CONFIGURED
            print(f"taken back: {row['id']} {row['cause']} - later gaps of that cause are asked again")
            return 0
        causes = [value.strip() for value in args.cause.split(",") if value.strip()]
        written, already, problem = record_gap_class(output, causes, words, args.shown_text, task_root.name)
        if problem:
            print(f"ticket_adapter: gap acceptance rejected: {problem}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        inventory = load_inventory(output)
        rows, class_problem = live_gap_classes(task_root)
        closed = completeness(inventory, classes=rows, class_problem=class_problem)["closed_by_class"]
        names = {item.get("source_id"): {point["id"]: (point["name"] or point["text"]) for point in gap_points(item)}
                 for item in inventory.get("sources", [])}
        for row in written:
            hit = [names.get(sid, {}).get(pid, pid) for sid, points in closed.items() for pid, gc in points.items()
                   if gc == row["id"]]
            print(f"class recorded: {row['id']} {row['cause']} - closes {len(hit)} open point(s) now"
                  + (": " + "; ".join(hit) if hit else ""))
        for row in already:
            print(f"already recorded: {row['id']} {row['cause']} - the earlier words stand")
        return 0
    except Exception as e:
        print(f"ticket_adapter: gap acceptance rejected: {e}", file=sys.stderr)
        return EXIT_NOT_CONFIGURED


def _ready_line(command, args, form) -> str:
    """`ready: ticket_adapter.py <command> <values>` - the call this refusal repairs, filled with what the CALL gave.

    `form` is `[(flag, dest, placeholder)]` (flag "" is a positional); a value the call gave is printed as given, a
    missing one is its placeholder, which says what goes there and where it comes from. Nothing is derived from another
    value: a ticket from `peek` is a mention, not the story, so the inventory path is never built from its key (FR-59,
    SC1-7 E2). A switch (`--json`) is printed when the call set it. Run 12586: 'usage:' alone cost the scout a `--help`
    read and a retry per command."""
    parts = ["ready: ticket_adapter.py", command]
    for flag, dest, placeholder in form:
        value = getattr(args, dest, None)
        if value is True:
            parts.append(flag)
        elif value:
            parts += ([flag] if flag else []) + [f'"{value}"' if any(c.isspace() for c in str(value)) else str(value)]
        elif placeholder:
            parts += ([flag] if flag else []) + [placeholder]
    return " ".join(parts)


SUMMARY_COMMANDS = ("collect", "peek", "assess", "inspect")
SUMMARY_ALSO = ("record-source",)     # SS1-14: takes --summary too; named after the four so the sentence the tests pin stays whole
SUMMARY_FIELDS = ("source_id", "canonical_ref", "relation", "status", "relevance", "assessment_ref", "snapshot_ref",
                  "inspection_status")


def _summary_path(output: str) -> str:
    """`output` as the summary line shows it: from the project's root when it is absolute and inside a project
    (`runtime_paths.nearest_project`, the one marker walk), else exactly as given. Never raises: the allowed error
    is the text as given."""
    try:
        if not os.path.isabs(output):
            return output
        project = RP.nearest_project(output)
        return Path(output).resolve().relative_to(project).as_posix() if project is not None else output
    except (OSError, ValueError, RuntimeError, TypeError):
        return output


def print_summary(record: dict | None, inventory: dict, output: str) -> None:
    """`--summary` (SC1-10): ONE line of compact JSON instead of the record or the whole inventory - the changed
    source's `SUMMARY_FIELDS` (a field the record lacks is null, a record the inventory lacks is null) and the
    inventory's path, byte size and counts. The file stays the record: the line names it and its size, so what the
    line leaves out has a door. `--json` and the plain line keep their shapes (FR-14). `path` is the caller's own
    `--output` text, echoed as given - except an ABSOLUTE one that lies inside a project, which is shown from the
    project's root, forward slashes (AR-4: a line a role keeps in its context carries no machine's folder). An absolute
    path with no project marker above it stays as given: it is the one path the caller can follow."""
    sources = [item for item in (inventory or {}).get("sources") or [] if isinstance(item, dict)]
    by_status: dict = {}
    for item in sources:
        word = "null" if item.get("status") is None else str(item["status"])
        by_status[word] = by_status.get(word, 0) + 1
    try:
        size = Path(output).stat().st_size
    except OSError:
        size = None
    print(json.dumps({"record": ({name: record.get(name) for name in SUMMARY_FIELDS} if record is not None else None),
                      "inventory": {"path": _summary_path(output), "bytes": size, "source_count": len(sources), "by_status": by_status}},
                     ensure_ascii=False, separators=(",", ":")))


def _source_of(inventory: dict, source_id: str):
    return next((item for item in (inventory or {}).get("sources") or [] if isinstance(item, dict)
                 and item.get("source_id") == source_id), None)


_OUT = ("--output", "output", "<the story's work/source-inventory.json - your brief names it>")
_TICKET = ("", "ticket", "<TICKET>")
_ID = ("--source-id", "source_id", "<source id>")
_COLLECT_FORM = [_TICKET, _OUT, ("--relation", "relation", "<one of: " + ", ".join(sorted(VALID_RELATIONS))
                                  + " - what this ticket is to the story>")]


TEXT_RELATIONS = ("subject", "parent", "normative", "referenced")    # what `record-source` may call a text: never `task`
_URL_RE = re.compile(r"^(?!file:)[A-Za-z][A-Za-z0-9+.-]+://", re.IGNORECASE)    # two letters or more: `C://` is a drive; no file:


def _only_text_sources_in(output: Path) -> bool:
    """Does the inventory at `output` hold only texts the factory recorded? An absent or unreadable file: False (the tracker
    requirement stays as it was)."""
    try:
        return output.is_file() and SI.only_text_sources(load_inventory(output))
    except (OSError, ValueError):
        return False


def _refuse_local(key: str, emit=None) -> int:
    """`peek`, or `collect` of a relation other than `task`, on a local key: no tracker holds it (exit 3, owner config)."""
    try:
        fail(EXIT_NOT_CONFIGURED, f"{key} is a local key: no tracker holds it. Its text is "
             f"{'/'.join(local_keys.TEXT_DIR)}/{key}.md; keys and links named in it are read as usual", owner="config")
    except SystemExit as exc:
        return refuse_exit(exc, emit)
    return EXIT_NOT_CONFIGURED


def _collect_local(args, emit=None) -> int:
    """`collect <LOCAL-n> --relation task`: the story's own text is recorded as its task source - no client, no read route, no
    network. The snapshot is the one `get --output` wrote beside the inventory, else the text file read as the person's
    text, so the snapshot and the inventory never disagree about the text."""
    key = args.ticket
    if args.relation != "task":
        return _refuse_local(key, emit)
    try:
        output = Path(args.output)
        stored = output.parent / SNAPSHOT_NAME
        if stored.is_file():
            snapshot, why = read_stored_snapshot(stored, key)
            if snapshot is None:
                fail(EXIT_NOT_CONFIGURED, f"ticket_adapter: the snapshot of {key} cannot be read: {why}", owner="config")
        elif local_keys.ticket_path(key).is_file():
            snapshot = read_ticket_file(local_keys.ticket_path(key), key, pasted=True)
        else:
            fail(EXIT_NOT_CONFIGURED, f"{key} is a local key and its text is not here: "
                 f"{'/'.join(local_keys.TEXT_DIR)}/{key}.md", owner="config")
        return _record_task_source(args, key, snapshot)
    except SystemExit as exc:
        return refuse_exit(exc, emit)
    except Exception as exc:  # noqa: BLE001
        return refuse_unexpected("collect unavailable", exc, emit)


def _record_task_source(args, key: str, snapshot: dict) -> int:
    """The snapshot of `key` becomes the story's task source (`record_text_source`, required): the one writer a local key and
    a tracker the role reads share, so the two cannot differ. A refusal is `fail()` (the caller turns it into the exit)."""
    output = Path(args.output)
    try:
        record = SI.record_text_source(output, relation="task", ref=key, snapshot=snapshot, required=True)
    except ValueError as exc:
        fail(EXIT_NOT_CONFIGURED, str(exc), owner="config")
    if args.summary:
        print_summary(record, load_inventory(output), args.output)
    else:
        print_result(load_inventory(output) if args.json else record, args.json)
    return 0


def _collect_by_role(args, emit=None) -> int:
    """`collect <KEY> --relation task` where the ROLE reads the tracker (`reads_by_role`): the task is the snapshot S0 made
    beside the inventory, recorded as the task source. No client, no read route, no network, nothing run (AR-2). The
    snapshot must be THIS key's: one story has one task source and a snapshot of another key never becomes it. Any other
    relation is read by the role's own route and recorded with `record-source`: the CALLER sends it to `_refuse_by_role`
    (the refusal says so, FR-2); this function is reached with `--relation task` only."""
    key = args.ticket
    try:
        stored = Path(args.output).parent / SNAPSHOT_NAME
        if not stored.is_file():
            fail(EXIT_NOT_CONFIGURED, f"S0 holds no text of {key}: run story_run.py, or give the text with --ticket-file",
                 owner="config")
        snapshot, why = read_stored_snapshot(stored, key)
        if snapshot is None:
            fail(EXIT_NOT_CONFIGURED, f"ticket_adapter: the snapshot of {key} cannot be read: {why}", owner="config")
        held = str(snapshot.get("key") or "").strip()
        if held.lower() != key.strip().lower():
            fail(EXIT_NOT_CONFIGURED, f"work/{SNAPSHOT_NAME} holds {held or 'no key'}, not {key}: one story has "
                 "one task source", owner="config")
        return _record_task_source(args, key, snapshot)
    except SystemExit as exc:
        return refuse_exit(exc, emit)
    except Exception as exc:  # noqa: BLE001
        return refuse_unexpected("collect unavailable", exc, emit)


def _refuse_by_role(key: str, output, emit=None) -> int:
    """`peek`, or `collect` of a relation other than `task`, where the ROLE reads the tracker: the factory holds no client, the
    text is read by the project's recorded route and saved with `record-source` (exit 3, owner config; the door is named)."""
    try:
        fail(EXIT_NOT_CONFIGURED, f"{key}: this project's tracker is read by its recorded route, not here (your dispatch names "
             f"it). Read it, save the text under work/raw/, then: ticket_adapter.py record-source --output {output} --ref {key} "
             f"--file <file> --relation {'|'.join(TEXT_RELATIONS)}", owner="config")
    except SystemExit as exc:      # `fail` always raises: this is the only way out
        return refuse_exit(exc, emit)


def _local_key(args, words, emit=None) -> int:
    """`local-key --words-file F`: the story's text is stored, the key is printed. Offline: no config is needed."""
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 - the key is made even where nothing is configured
        cfg = {}
    try:
        key, relative = local_keys.mint(words, cfg)
    except local_keys.MintRefused as exc:
        print(f"ticket_adapter: {exc}", file=sys.stderr)
        if exc.code == EXIT_FACTORY_FAULT and emit:
            emit(error_object("factory", str(exc), file=AF.TABLE_NAME))
        return exc.code
    except OSError as exc:
        return refuse_unexpected("local key unavailable", exc, emit)
    if args.json:
        print(json.dumps({"key": key, "ticket_file": relative}, ensure_ascii=False))
    else:
        print(f"key: {key}\nticket_file: {relative}")
    return 0


def _record_source(args, emit=None) -> int:
    """`record-source --output I --ref R --file P --relation <subject|parent|normative|referenced>`: a text a role READ (a page,
    a document, a file in the repository) becomes a source of the inventory, so it reaches the bundle and the manifest from
    there. Every edge is a refusal that says what was expected (the inventory is untouched by any of them)."""
    form = [_OUT, ("--ref", "ref", "<where the text came from: a path relative to the project, or a URL>"),
            ("--file", "file", "<the file holding the text you read>"),
            ("--relation", "relation", "<one of: " + ", ".join(TEXT_RELATIONS) + ">")]
    if not all((args.output, args.ref.strip(), args.file, args.relation)):
        print("usage: ticket_adapter.py record-source --output <work/source-inventory.json> --ref <locator> --file <text file> "
              "--relation subject|parent|normative|referenced", file=sys.stderr)
        print(_ready_line("record-source", args, form), file=sys.stderr)
        return EXIT_USAGE
    if args.relation not in TEXT_RELATIONS:
        print(f"ticket_adapter: a text is recorded as one of {', '.join(TEXT_RELATIONS)}, not `{args.relation}`: the story has "
              "one task source and `collect` writes it", file=sys.stderr)
        return EXIT_USAGE
    ref = args.ref.strip()
    if ref.lower().startswith("file:") or (not _URL_RE.match(ref) and not SI._safe_rel(ref)):     # file: names THIS machine (AR-4)
        print("ticket_adapter: give the locator relative to the project (a path with no drive and no `..`), or a URL",
              file=sys.stderr)
        return EXIT_USAGE
    from config_contract import SECRET_QUERY_RE
    if SECRET_QUERY_RE.search(ref) or (_URL_RE.match(ref) and urllib.parse.urlsplit(ref).password):
        print("ticket_adapter: the locator holds a credential-like field (token=, secret=, password=, key=); the value is not "
              "shown and nothing was recorded: record the locator without it", file=sys.stderr)
        return EXIT_USAGE
    # FR-36, AR-24: a source the person left out before the run is not recorded by the role route either; the door is the handoff
    left_out = source_exclusions.first_ref_match(source_exclusions.live_in(Path(args.output).parent), ref)
    if left_out:
        print("ticket_adapter: " + source_exclusions.refusal_text(ref, source_exclusions.reason_of(
            [left_out], left_out.get("id")) or "no reason given"), file=sys.stderr)
        return EXIT_USAGE
    path = Path(args.file)
    try:
        data = path.read_bytes() if path.is_file() else b""
    except OSError:
        data = b""
    if not data.strip():
        print(f"ticket_adapter: {args.file}: nothing to record: expected the text you read, saved as a UTF-8 file",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("NUL byte")
    except ValueError:
        try:
            fail(EXIT_NOT_CONFIGURED, f"{args.file} is not text: record the gap in your manifest with the reason", owner="config")
        except SystemExit as exc:
            return refuse_exit(exc, emit)
    try:
        record = SI.record_text_source(Path(args.output), relation=args.relation, ref=ref,
                                       snapshot=SI.text_snapshot(ref, text), required=False)
        if args.summary:
            print_summary(record, load_inventory(Path(args.output)), args.output)
        else:
            print_result(load_inventory(Path(args.output)) if args.json else record, args.json)
        return 0
    except ValueError as exc:      # the call's fault, not the factory's (FR-46): the inventory is untouched
        print(f"ticket_adapter: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        return refuse_unexpected("record-source unavailable", exc, emit)


QUERY_MAX_BYTES = 5_000_000      # the most a `query` answer may hold; one byte more is refused and nothing is saved
QUERY_SUMMARY_KEYS = 12          # top-level keys the one summary line shows


def _link_refusal(args, cfg=None, emit=None):
    """`peek`/`collect` given a LINK where a ticket key belongs (a filter, a board, a search page): refused BEFORE any request,
    the inventory untouched, exit 2 (the call's fault, FR-46). The sentence names the keys the adapter's own key form finds in the
    link and the two doors: `peek <KEY>` and `query` (FR-1, FR-2). None for anything that is not a link."""
    value = str(args.ticket or "").strip()
    if not _URL_RE.match(value):
        return None
    try:
        cfg = cfg if cfg is not None else load_config()
    except Exception:  # noqa: BLE001 - an unreadable config is the default key form
        cfg = {}
    if not AF.key_refused(value, cfg):
        return None
    try:
        found = AF.keys_in(value, cfg)
    except Exception:  # noqa: BLE001 - the keys are a courtesy; the refusal stands without them
        found = []
    inside = (f"A ticket key inside it ({', '.join(found)}) is read with `peek {found[0]} --output <inventory>`; "
              if found else "No ticket key was found inside it; ")
    print(f"ticket_adapter: {value} is a link, not a ticket key. {inside}the page itself (a filter, a board, a search) is read "
          "with `query --path <API path> --output <inventory>` and recorded with `record-source`. Nothing was requested and the "
          "inventory was not touched.", file=sys.stderr)
    if emit:
        emit(error_object("person", f"{value} is a link, not a ticket key", file=None))
    return EXIT_USAGE


def _query_path(raw: str, base_url: str):
    """`(request path or URL, "")` for a `--path` the client may send, else `("", why)`: a path begins with `/` (relative to the
    tracker's `base_url`) or is an absolute http(s) URL whose scheme, host and port are the `base_url`'s (the same-origin rule
    the client itself keeps, `JiraClient._origin`). Anything else - another host, `file:`, a bare word, an empty value, a
    control character - is refused with no request."""
    value = str(raw or "").strip()
    if not value or any(ch.isspace() or ord(ch) < 32 for ch in value):
        return "", "expected a GET path beginning with `/`, with no spaces (encode them as %20)"
    if value.startswith("/") and not value.startswith("//"):
        return value, ""
    if _URL_RE.match(value):
        have, want = urllib.parse.urlsplit(value), urllib.parse.urlsplit(base_url)
        if (have.scheme.lower(), have.hostname, have.port) == (want.scheme.lower(), want.hostname, want.port):
            return urllib.parse.urlunsplit((have.scheme.lower(),) + tuple(have[1:])), ""
        return "", f"that address is not the tracker's own ({base_url}); `query` reads only the configured tracker"
    return "", f"expected a path beginning with `/` or an address on {base_url}"


def _query_summary(status: int, size: int, where, body) -> str:
    """ONE line (FR-14): the status, the size, the file, then the first top-level keys as `key=value` for a scalar and `key[n]`
    for a list - never the body, a header or a credential."""
    parts = []
    if isinstance(body, dict):
        for key, value in list(body.items())[:QUERY_SUMMARY_KEYS]:
            if isinstance(value, list):
                parts.append(f"{key}[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}{{{len(value)}}}")
            else:
                text = " ".join(str(value).split())
                parts.append(f"{key}={text[:60] + '...' if len(text) > 60 else text}")
    elif isinstance(body, list):
        parts.append(f"[{len(body)}]")
    return f"query: {status}, {size} bytes -> {where}" + (f"; {', '.join(parts)}" if parts else "")


def _query(args, emit=None) -> int:
    """`query --path <API path> --output <work/source-inventory.json> [--save <file>]`: ONE GET of the configured tracker's API at
    a path the ROLE chose (a filter's search, a project's issues), the answer kept whole in a file under work/, one summary line
    on stdout. Code holds the host, the auth, the GET and the trace; the request is the role's (AR-2, AR-5, AR-6). The inventory
    is NOT written: `record-source` records what the role used, so it keeps one writer (AR-14)."""
    form = [("--path", "path", "<API path with its query, beginning with />"), _OUT, ("--save", "save", None)]
    if not args.output or not args.path:
        print("usage: ticket_adapter.py query --path <API path with its query> --output <work/source-inventory.json> "
              "[--save <file>]", file=sys.stderr)
        print(_ready_line("query", args, form), file=sys.stderr)
        return EXIT_USAGE
    try:
        cfg = load_config()
        _kind, adapter_cfg = resolve_adapter(cfg)
        try:
            client = traced_client(adapter_cfg, "query", cfg)
        except ValueError:      # `client_from_config`: no `direct_api` the factory can read (the project's setting, exit 3)
            door = (f" ({direct_api_not_usable_message(adapter_cfg)})" if isinstance(adapter_cfg.get("direct_api"), dict) else "")
            fail(EXIT_NOT_CONFIGURED, f"this project's tracker has no API the factory reads{door}: read the page by the recorded "
                 "route or the browser, save the text under work/raw/, then record it: ticket_adapter.py record-source "
                 f"--output {args.output} --ref <url> --file <file> --relation {'|'.join(TEXT_RELATIONS)}", owner="config")
        request, why = _query_path(args.path, client.base_url)
        if why:
            print(f"ticket_adapter: --path {args.path!r}: {why}. Nothing was requested.", file=sys.stderr)
            return EXIT_USAGE
        work = Path(args.output).resolve().parent
        queries = work / "queries"          # the ONE door a query answer is written through: never the inventory, never another artifact (AR-14)
        if args.save:
            if ".." in Path(args.save).parts or Path(args.save).resolve() == queries or not _inside(Path(args.save).resolve(), queries):
                print(f"ticket_adapter: --save {args.save}: a query answer is kept only under {queries} (no `..`, no other file of the "
                      "story's work/: the inventory and the artifacts have their own writers); give a file there, or leave --save out. "
                      "Nothing was requested.", file=sys.stderr)
                return EXIT_USAGE
            target = Path(args.save).resolve()
        else:
            n = 1
            while (queries / f"tracker-query-{n}.json").exists():
                n += 1
            target = queries / f"tracker-query-{n}.json"
        refuse_unsupported_auth_type(client)
        body, raw = client.get_json_with_raw(request)
        if len(raw) > QUERY_MAX_BYTES:
            print(f"ticket_adapter: the answer is {len(raw)} bytes, over the {QUERY_MAX_BYTES} a query keeps; nothing was saved: "
                  "narrow the request (fields=, maxResults=).", file=sys.stderr)
            return EXIT_USAGE
        SI._atomic_write(target, raw)
        print(_query_summary(200, len(raw), target.relative_to(work.parent).as_posix() if _inside(target, work.parent) else target,
                             body))
        return 0
    except SystemExit as exc:
        return refuse_exit(exc, emit)
    except AuthLost as exc:
        return refuse_auth(exc, emit)
    except FetchError as exc:
        if exc.status == 404 and not SI._foreign(exc):
            message = (f"the tracker answered 404 for {args.path}: the path or the query is wrong, or this account cannot see it")
            print(f"ticket_adapter: {message}.", file=sys.stderr)
            if emit:
                emit(error_object("tracker", message, status=404))
            return EXIT_NOT_FOUND
        return refuse_fetch(exc, args.path, emit)
    except TL.TableError as exc:
        return refuse_table(exc, emit)
    except Exception as exc:  # noqa: BLE001
        return refuse_unexpected("query unavailable", exc, emit)


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def _key_form_refusal(args, emit=None):
    """`get --output` for a story that has no `pipeline.json` beside it and no file at `--output` yet (a NEW story): the key
    must be one the project's tracker has, unless the person's words let the name stand (`--key-form-word`). The twin of the
    driver's S0 key check (AR-15, AR-19): the same `AF.key_refused`. An older story passes untouched. The refusal is exit 3."""
    output = Path(args.output)
    if args.key_form_word or (output.parent.parent / "pipeline.json").is_file() or output.exists():
        return None
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 - an unreadable config is the tracker's form, the default
        cfg = {}
    if not AF.key_refused(args.ticket, cfg):
        return None
    try:
        fail(EXIT_NOT_CONFIGURED,
             f"{args.ticket} is not a key of this project's tracker: {AF.describe_key_form(cfg)}. If there is no ticket: "
             "ticket_adapter.py local-key --words-file <file>. To go on under this name: add --key-form-word --words-file "
             "<file> with the person's words", owner="config")
    except SystemExit as exc:
        return refuse_exit(exc, emit)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ticket adapter — normalizes any configured tracker")
    ap.add_argument("command", nargs="?", choices=["get", "children", "diff", "freshness", "collect",
                                                    "inspect", "assess", "probe", "refresh",
                                                    "peek", "review", "accept-gap", "receipts",
                                                    "local-key", "record-source", "query"])
    ap.add_argument("ticket", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true",
                    help="collect, peek, assess, inspect: print ONE line - the changed record's key fields and the "
                         "inventory's path, size and counts - instead of the record or the whole inventory; stronger "
                         "than --json")
    ap.add_argument("--ticket-file", dest="ticket_file", default="",
                    help="read THIS file as the ticket, ignoring adapters.ticket entirely")
    ap.add_argument("--raw-dir", dest="raw_dir", default="",
                    help="get (REST): keep every response of the read here, whole (the S0 folder, "
                         "work/ticket-raw), and write ticket-view.md, ticket-references.json and the "
                         "inventory seeds next to it, in its parent")
    ap.add_argument("--old", default="", help="diff: the earlier ticket file")
    ap.add_argument("--new", default="", help="diff: the later ticket file")
    ap.add_argument("--output", default="",
                    help="collect: canonical source-inventory.json path; get: write exactly the bytes "
                         "--json prints (UTF-8, LF) there, atomically, after a successful read - the "
                         "story's snapshot JSON")
    ap.add_argument("--task-root", dest="task_root", default=None,
                    help="freshness: the story's folder (qa-factory/artifacts/<TICKET>)")
    ap.add_argument("--adopt", action="store_true",
                    help="freshness: after the person's answer, make the waiting "
                         "ticket-snapshot.next.json the baseline")
    ap.add_argument("--decline", action="store_true",
                    help="freshness: after the person chose to continue on the old text, keep their "
                         "words (--words-file, required) as a remark for the next gate and remember "
                         "that the waiting text was declined so it is not asked again")
    ap.add_argument("--relation", default=None,
                    choices=["task", "subject", "parent", "normative", "referenced"],
                    help="collect: mandatory, no default — one story has one task source")
    ap.add_argument("--discovered-from", default=None)
    ap.add_argument("--relation-evidence", default=None)
    ap.add_argument("--source-id", default="")
    ap.add_argument("--ref", default="",
                    help="record-source: where the text came from, relative to the project (a path) or a URL")
    ap.add_argument("--file", default="", help="record-source: the file holding the text a role read (UTF-8)")
    ap.add_argument("--path", default="",
                    help="query: a GET path of the configured tracker API, with its query string, chosen by you; "
                         "relative to its base_url")
    ap.add_argument("--save", default="",
                    help="query: where the answer goes - ONLY a file under the story's work/queries/; default "
                         "work/queries/tracker-query-<n>.json beside --output, the next n")
    ap.add_argument("--key-form-word", dest="key_form_word", action="store_true",
                    help="get --output: go on under a key the project's tracker does not have, on the person's words "
                         "(--words-file); kept in the snapshot's provenance")
    ap.add_argument("--attachment-id", default="")
    ap.add_argument("--inspection-status", choices=["read", "partial", "unavailable"])
    ap.add_argument("--provenance", choices=["fetched", "browser", "person_pasted"], default="fetched",
                    help="which route produced the file: the factory fetched it, an authorized "
                         "browser did, or the person read it themselves and pasted the text")
    ap.add_argument("--evidence-ref", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--relevance", choices=["relevant", "not_relevant", "unknown"])
    ap.add_argument("--assessment-ref", default="")
    ap.add_argument("--media-url", default="")
    ap.add_argument("--local-ref", default="")
    ap.add_argument("--words", default=None,
                    help="review --record / accept-gap: what the person said, verbatim - one line "
                         "typed by code; their own words go in a file (--words-file)")
    ap.add_argument("--words-file", dest="words_file", default=None,
                    help="review --record / accept-gap / freshness --decline: a file holding the person's own words as "
                         "they were given (UTF-8; <story folder>/state/words/<name>.txt), instead "
                         "of --words. A multi-line text, or one with quotes, goes here; inline "
                         "words cannot cross the cmd launcher whole")
    ap.add_argument("--record", action="store_true",
                    help="review: store the person's answer instead of printing the table")
    ap.add_argument("--pending-only", action="store_true",
                    help="review: only the sources the person has not seen yet")
    ap.add_argument("--late", action="store_true",
                    help="review: mark currently unreviewed sources shown at gate A — no words,"
                         " not recorded as the person's answer")
    ap.add_argument("--expand-not-found", action="store_true",
                    help="review: print every not-found (404) row instead of the collapsed one")
    ap.add_argument("--all-unavailable", action="store_true",
                    help="accept-gap: every open GAP point (an unavailable source or material) of "
                         "every source that has one - never the factory's own unfinished work")
    ap.add_argument("--point", default=None,
                    help="accept-gap: the point id(s) to accept, comma-separated, of exactly one "
                         "--source-id (ids are in the refusal and in `review --json` under points)")
    ap.add_argument("--shown-text", dest="shown_text", default="",
                    help="accept-gap --point: the sentence the person was shown; required for a point "
                         "of the factory's own work (source:not_inspected, an attachment not inspected)")
    ap.add_argument("--cause", default=None,
                    help="accept-gap: the person's word about a whole KIND of gap - the cause(s), comma-separated, as "
                         "`inspect --reason` names them (host_unreachable, no_tool, too_large, ...; source_unavailable for "
                         "a source that could not be read). Covers every later gap of that cause in this story")
    ap.add_argument("--revoke", default=None,
                    help="accept-gap: take back a kind recorded with --cause (GC-n), with the person's words; refused "
                         "once S1 of the story is closed")
    ap.add_argument("--probe-ref", dest="probe_ref", default="",
                    help="inspect --inspection-status unavailable: the work-relative path of the vcs_evidence receipt that "
                         "answered for this address (the code carrier of a host_unreachable verdict)")
    ap.add_argument("--migrate-method", dest="migrate_method", action="store_true",
                    help="rewrite adapters.ticket.method to 'api' when direct_api makes an "
                         "agent/skill method stale for reading; use --config, "
                         "--dry-run, --json")
    ap.add_argument("--config", default="", help="--migrate-method: path to config.json")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="--migrate-method: print what would change, write nothing")
    ap.add_argument("--selftest", action="store_true")
    args = hooklib.exact_options(ap).parse_args()
    if args.summary and args.command not in SUMMARY_COMMANDS + SUMMARY_ALSO:     # a flag a verb does not honour is not ignored (FR-4)
        print("ticket_adapter.py: --summary applies to " + ", ".join(SUMMARY_COMMANDS[:-1]) + " and " + SUMMARY_COMMANDS[-1]
              + " (and " + ", ".join(SUMMARY_ALSO) + ")", file=sys.stderr)
        return EXIT_USAGE
    if args.key_form_word and not (args.command == "get" and args.output):    # nor is this one (FR-4)
        print("ticket_adapter.py: --key-form-word applies to `get --output` (with --words-file, the person's words)",
              file=sys.stderr)
        return EXIT_USAGE
    if args.task_root is not None:      # a GIVEN root (freshness) names an existing story; `get --output` is S0 and creates it
        hooklib.story_cli("ticket_adapter.py", root=args.task_root, key_flag=None)
    # Under --json a failure is ONE object on stdout and nothing else (F3, FR-14): the driver reads the owner and
    # `retry_at` from it instead of matching the sentence on stderr, which keeps the human words.
    emit = (lambda obj: print(json.dumps(obj, ensure_ascii=False))) if args.json else None

    if args.selftest:
        return selftest()

    # The person's words are resolved ONCE, here, before any inventory is read or written: a refusal
    # (both options, a missing or unreadable file, a text that is not UTF-8, inline words that came
    # through the cmd launcher, which cuts a command line at its first line break) leaves the
    # inventory untouched. Both commands below strip what they store, whichever route it came by.
    # With neither option the value stays "" - the commands' own "--words is empty" refusal, as before.
    words = ""
    if (args.command in ("accept-gap", "local-key") or (args.command == "review" and args.record)
            or (args.command == "get" and args.key_form_word)):
        try:
            words = person_words.read(args.words, args.words_file, "--words")
        except person_words.WordsRefused as exc:
            ap.error(str(exc))
        words = "" if words is None else words
    if args.command == "freshness" and args.decline:
        # Same reader, same place (FR-17). The decision to go on with the old text is the person's,
        # and it is not a decision without their words: no words, no mark, no remark, no event.
        try:
            words = person_words.read(args.words, args.words_file, "--words")
        except person_words.WordsRefused as exc:
            ap.error(str(exc))
        if words is None or not words.strip():
            ap.error("freshness --decline records the person's own words about going on with the old "
                     "text, and none were given. Write them to a file exactly as they were given "
                     "(<story folder>/state/words/<name>.txt) and pass `--words-file <file>`; nothing "
                     "was recorded.")

    if args.migrate_method:
        if not args.config:
            print("usage: ticket_adapter.py --migrate-method --config <path> [--dry-run] [--json]",
                  file=sys.stderr)
            print(_ready_line("--migrate-method", args, [("--config", "config", "<the project's config.json>"),
                                                          ("--dry-run", "dry_run", None), ("--json", "json", None)]),
                  file=sys.stderr)
            return 2
        path = Path(args.config)
        if not path.exists():
            print(f"ticket_adapter: --migrate-method: no such file: {path}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        try:
            cfg, result = migrate_method(path)
        except Exception as e:
            print(f"ticket_adapter: --migrate-method failed: {e}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        if result["changed"] and not args.dry_run:
            path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif result["changed"]:
            verb = "would rewrite" if args.dry_run else "rewrote"
            print(f"{verb} adapters.ticket.method: {result['old_method']} -> api ({path})")
        else:
            print(f"no change: adapters.ticket.method is {result['old_method'] or 'unset'} "
                  f"({path})")
        return 0

    if args.command == "diff":
        if not args.old or not args.new:
            print("usage: ticket_adapter.py diff --old <path> --new <path> [--json]",
                  file=sys.stderr)
            print(_ready_line("diff", args, [("--old", "old", "<the earlier ticket file>"),
                                              ("--new", "new", "<the later ticket file>"), ("--json", "json", None)]),
                  file=sys.stderr)
            return 2
        try:
            print_diff(diff_tickets(Path(args.old), Path(args.new)), args.json)
            return 0
        except SystemExit as e:
            return refuse_exit(e, emit)
        except TL.TableError as e:
            return refuse_table(e, emit)
        except Exception as e:
            return refuse_unexpected("unexpected error", e, emit)

    if args.command == "freshness":
        if not args.ticket or not args.task_root:
            print("usage: ticket_adapter.py freshness <TICKET> --task-root <qa-factory/artifacts/TICKET> "
                  "[--ticket-file <path>] [--json] [--adopt | --decline --words-file <file>]",
                  file=sys.stderr)
            print(_ready_line("freshness", args, [_TICKET, ("--task-root", "task_root", "<the story's folder>"),
                                                   ("--ticket-file", "ticket_file", None), ("--json", "json", None),
                                                   ("--adopt", "adopt", None), ("--decline", "decline", None),
                                                   ("--words-file", "words_file",
                                                    "<the file holding the person's own words>" if args.decline else None)]),
                  file=sys.stderr)
            return EXIT_USAGE
        refused = _link_refusal(args, emit=emit)      # a link is not a key: refused before any request (FR-1, FR-2)
        if refused:
            return refused
        if args.adopt and args.decline:
            print("ticket_adapter: --adopt and --decline are two different answers; give one",
                  file=sys.stderr)
            return EXIT_USAGE
        if args.adopt and (args.words is not None or args.words_file is not None):
            # A person's words given to a command that keeps none are dropped in silence (FR-8).
            print("ticket_adapter: --adopt takes no words: adoption is the factory's own move; a "
                  "person's words about the change go with --decline, or as a remark through "
                  "waiver.py --remark", file=sys.stderr)
            return EXIT_USAGE
        try:
            task_root = Path(args.task_root)
            result = (freshness_adopt(args.ticket, task_root) if args.adopt
                      else freshness_decline(args.ticket, task_root, words) if args.decline
                      else freshness_check(args.ticket, task_root, args.ticket_file))
            print_freshness(result, args.json)
            settle_role_files(result, task_root)
            return 0
        except SystemExit as e:
            return refuse_exit(e, emit)
        except AuthLost as e:
            return refuse_auth(e, emit)
        except TL.TableError as e:
            return refuse_table(e, emit)
        except FetchError as e:
            return refuse_fetch(e, args.ticket, emit)
        except Exception as e:  # never a crash: the factory's own fault, exit 4, named - not "the tracker is unreachable"
            return refuse_unexpected("unexpected error", e, emit)

    if args.command == "local-key":
        return _local_key(args, words, emit)

    if args.command == "record-source":
        return _record_source(args, emit)

    if args.command == "query":
        return _query(args, emit)

    if args.command == "collect":
        if not args.ticket or not args.output:
            print("usage: ticket_adapter.py collect <TICKET> --output <work/source-inventory.json> "
                  "--relation task|subject|parent|normative|referenced", file=sys.stderr)
            print(_ready_line("collect", args, _COLLECT_FORM), file=sys.stderr)
            return 2
        if not args.relation:
            print("usage: ticket_adapter.py collect <TICKET> --output <path> --relation "
                  "task|subject|parent|normative|referenced — no default, name what this "
                  "ticket is to the story (allowed: " + ", ".join(sorted(VALID_RELATIONS)) + ")",
                  file=sys.stderr)
            print(_ready_line("collect", args, _COLLECT_FORM), file=sys.stderr)
            return 2
        refused = _link_refusal(args, emit=emit)      # a link is not a key: refused before any request (FR-1, FR-2)
        if refused:
            return refused
        if local_keys.is_local(args.ticket):      # no tracker holds it: no client, no direct-read requirement (SS1-14)
            return _collect_local(args, emit)
        try:
            cfg = load_config()
            _kind, adapter_cfg = resolve_adapter(cfg)
            if reads_by_role(cfg):      # SS1-15: no client for this tracker; BEFORE the direct-read requirement, which a role's route never meets
                return _collect_by_role(args, emit) if args.relation == "task" else _refuse_by_role(args.ticket, args.output, emit)
            require_direct_read(adapter_cfg, "collect")
            output = Path(args.output)
            existing_inventory = (json.loads(output.read_text(encoding="utf-8"))
                                  if output.exists() else {"sources": []})
            client = traced_client(adapter_cfg, args.ticket, cfg)
            # One story has one task source: TP1-15045 collected both its parent
            # and its normative predecessor with the default `--relation task`, and S2's
            # register then had two "the task" sources.
            other_task = conflicting_task_source(existing_inventory.get("sources", []), args.relation,
                                                 canonical_ticket(client.base_url, args.ticket))
            if other_task:
                fail(EXIT_NOT_CONFIGURED,
                     f"a task-relation source already exists ({other_task.get('canonical_ref')}); "
                     "one story has one task source — use --relation "
                     + ", ".join(sorted(VALID_RELATIONS - {"task"})) + " for this ticket")
            existing = next((item for item in existing_inventory.get("sources", [])
                             if item.get("canonical_ref") ==
                             canonical_ticket(client.base_url, args.ticket)), None)
            # Comments, attachments and the tickets a source names are fetched only for a
            # source judged relevant. A mentioned ticket is looked at first (`peek`) and
            # assessed; an unrelated one never costs a download or an inspection. A ticket the
            # person left out before the run skips this guard: the library answers it (no fetch, the
            # left-out record) and the command says so instead of sending the role to `assess`.
            left_out = _left_out_ticket(output, client, args.ticket)
            if (args.relation == "referenced" and not left_out
                    and (existing or {}).get("relevance") != "relevant"):
                fail(EXIT_NOT_CONFIGURED,
                     f"{args.ticket} is a mentioned ticket that is not assessed as relevant — "
                     "run `peek` and `assess --relevance relevant` first; full collection is "
                     "for relevant sources only")
            before = existing_inventory
            record = collect_jira_source(client, args.ticket, output,
                                         relation=args.relation,
                                         discovered_from=args.discovered_from,
                                         relation_evidence=args.relation_evidence,
                                         existing_record=existing)
            result = update_inventory(output, record)
            _say_marks(output, before, result, record["source_id"] if left_out else None)
            if args.summary:
                print_summary(record, result, args.output)
            else:
                print_result(result if args.json else record, args.json)
            return 0 if record["status"] in ("read", "excluded") else EXIT_NOT_CONFIGURED
        except SystemExit as e:
            return refuse_exit(e, emit)
        except AuthLost as e:
            return refuse_auth(e, emit)
        except TL.TableError as e:
            return refuse_table(e, emit)
        except Exception as e:
            return refuse_unexpected("collect unavailable", e, emit)

    if args.command == "peek":
        if not args.ticket or not args.output:
            print("usage: ticket_adapter.py peek <TICKET> --output <work/source-inventory.json>",
                  file=sys.stderr)
            print(_ready_line("peek", args, [_TICKET, _OUT]), file=sys.stderr)
            return 2
        refused = _link_refusal(args, emit=emit)      # a link is not a key: refused before any request (FR-1, FR-2)
        if refused:
            return refused
        if local_keys.is_local(args.ticket):
            return _refuse_local(args.ticket, emit)
        try:
            cfg = load_config()
            _kind, adapter_cfg = resolve_adapter(cfg)
            if reads_by_role(cfg):
                return _refuse_by_role(args.ticket, args.output, emit)
            require_direct_read(adapter_cfg, "peek")
            output = Path(args.output)
            client = traced_client(adapter_cfg, args.ticket, cfg)
            inventory = (json.loads(output.read_text(encoding="utf-8"))
                         if output.exists() else {"sources": []})
            existing = next((item for item in inventory.get("sources", [])
                             if item.get("canonical_ref") ==
                             canonical_ticket(client.base_url, args.ticket)), None)
            left_out = _left_out_ticket(output, client, args.ticket)
            if existing and existing.get("relevance") != "pending" and not left_out:
                if args.summary:
                    print_summary(existing, inventory, args.output)
                else:
                    print(f"{args.ticket}\talready assessed: {existing.get('relevance')}")
                return 0
            record = peek_jira_source(client, args.ticket, output,
                                      discovered_from=(existing or {}).get("discovered_from") or args.discovered_from,
                                      relation_evidence=(existing or {}).get("relation_evidence") or args.relation_evidence)
            result = update_inventory(output, record)
            _say_marks(output, inventory, result, record["source_id"] if left_out else None)
            if args.summary:
                print_summary(record, result, args.output)
            else:
                print_result(record, args.json)
            return 0 if record["status"] != "unavailable" else EXIT_NOT_CONFIGURED
        except SystemExit as e:
            return refuse_exit(e, emit)
        except AuthLost as e:
            return refuse_auth(e, emit)
        except TL.TableError as e:
            return refuse_table(e, emit)
        except Exception as e:
            return refuse_unexpected("peek unavailable", e, emit)

    if args.command == "review":
        if not args.output:
            print("usage: ticket_adapter.py review --output <inventory> [--pending-only] [--json] "
                  "[--expand-not-found]  |  review --record --words-file <file>  |  "
                  "review --late  (mark newly found sources shown at gate A, no words)",
                  file=sys.stderr)
            print(_ready_line("review", args, [_OUT, ("--pending-only", "pending_only", None), ("--json", "json", None),
                                                ("--record", "record", None), ("--late", "late", None),
                                                ("--words-file", "words_file", None)]), file=sys.stderr)
            return 2
        try:
            output = Path(args.output)
            if args.record:
                # Deliberately BEFORE the read-route guard: a person's recorded word is never
                # refused for a configuration defect of the factory's own.
                record_source_review(output, words)
                print("source review recorded")
                return 0
            if not _only_text_sources_in(output):      # a project with no tracker still closes S1 (SS1-14)
                require_direct_read(resolve_adapter(load_config())[1], "review")
            if args.late:
                _, marked = record_late_review(output)
                print(("marked " + ", ".join(marked) + " shown at gate A") if marked else
                      "no unreviewed source to mark")
                return 0
            rows = review_rows(load_inventory(output), only_unreviewed=args.pending_only)
            if args.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            else:
                print(render_review(rows, expand_not_found=args.expand_not_found))
            return 0
        except Exception as e:
            print(f"ticket_adapter: review rejected: {e}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED

    if args.command == "accept-gap" and (args.cause is not None or args.revoke is not None):
        return _accept_gap_kind(args, words)

    if args.command == "accept-gap":
        if not args.output or not (args.source_id or args.all_unavailable):
            print("usage: ticket_adapter.py accept-gap --output <inventory> "
                  "(--source-id <id>[,<id>...] | --all-unavailable | --cause <cause>[,<cause>...]) --words-file <file> "
                  "[--point <point-id>[,<point-id>...]] [--shown-text \"<the sentence the person was shown>\"]"
                  " - --point takes exactly one --source-id; without it every open gap of the source is "
                  "accepted, never the factory's own unfinished work; --shown-text is required for such a "
                  "point (source:not_inspected and the like)",
                  file=sys.stderr)
            print(_ready_line("accept-gap", args, [_OUT, _ID if not args.all_unavailable else ("--all-unavailable", "all_unavailable", None),
                                                    ("--words-file", "words_file", "<the file holding the person's own words>"),
                                                    ("--point", "point", None),
                                                    ("--shown-text", "shown_text", "<the sentence the person was shown>"
                                                     if args.point is not None else None)]), file=sys.stderr)
            return 2
        try:
            output = Path(args.output)
            ids = (sources_with_open_gaps(load_inventory(output)) if args.all_unavailable
                   else [value.strip() for value in args.source_id.split(",") if value.strip()])
            points = None
            if args.point is not None:
                if args.all_unavailable or len(ids) != 1:
                    raise ValueError("--point names points of ONE source: use it with exactly one "
                                     "--source-id, and not with --all-unavailable (which accepts every "
                                     "open gap, never the factory's own work)")
                # An empty piece ("a,,b", a trailing comma, an empty value) is kept, so the refusal
                # can name it instead of the command quietly accepting less than was asked.
                points = [value.strip() for value in args.point.split(",")]
            if not ids:
                print("no open source gap to accept")
                return 0
            # `words`: what `person_words.read` resolved above (a file's text or the inline value, one reader),
            # never `args.words` raw - with `--words-file` that is None and the acceptance would be refused empty.
            inventory, report = apply_gap_acceptance(output, ids, words, points=points,
                                                     shown_text=args.shown_text or None)
            by_id = {item.get("source_id"): item for item in inventory.get("sources", [])}

            def ticket(sid):
                return str((by_id.get(sid) or {}).get("canonical_ref") or sid).rsplit("/browse/", 1)[-1]

            already_by_id = report.get("already_accepted") or {}
            for sid, accepted in report["accepted"].items():
                already = already_by_id.get(sid) or []
                already_ids = {point["id"] for point in already}
                new = [point for point in accepted if point["id"] not in already_ids]
                if new:
                    print(f"accepted: {ticket(sid)}: " + "; ".join(point["text"] for point in new))
                if already:
                    print(f"already accepted: {ticket(sid)}: " + "; ".join(point["text"] for point in already))
            for sid, gone in report["no_longer_open"].items():
                print(f"not recorded, no longer open: {ticket(sid)}: " + ", ".join(gone))
            for owned in report["factory_owned"]:
                print(f"factory-owned: {ticket(owned['source_id'])}: {owned['text']} - the factory's own "
                      "work, passed on the person's word; file it as a factory finding: "
                      "project_decisions.py --root <project> add-finding --essence \"<what passed>\" "
                      "--scope <local-urgent|local-calibration|upstream-candidate> --witness \"<the sentence the person was shown>\" "
                      "--idempotency-key <a key of your own>")
            if report["shown_text_unused"]:
                print("note: --shown-text was not stored - no point of the factory's own work was accepted")
            if not report["accepted"] and not report["no_longer_open"]:
                print("no open source gap to accept")
            return 0
        except Exception as e:
            print(f"ticket_adapter: gap acceptance rejected: {e}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED

    if args.command == "refresh":
        if not args.output:
            print("usage: ticket_adapter.py refresh --output <work/source-inventory.json> --json",
                  file=sys.stderr)
            print(_ready_line("refresh", args, [_OUT, ("--json", "json", None)]), file=sys.stderr)
            return 2
        if _only_text_sources_in(Path(args.output)):
            # Every source is a text the factory recorded: there is nothing a tracker could refresh (SS1-14)
            print(json.dumps([], indent=2) if args.json else "")
            return 0
        try:
            cfg = load_config()
            kind, adapter_cfg = resolve_adapter(cfg)
            require_direct_read(adapter_cfg, "refresh")
            if kind != "jira":
                fail(EXIT_NOT_CONFIGURED, "source refresh requires a Jira ticket adapter")
            result = refresh_relevant_sources(traced_client(adapter_cfg, args.ticket or "refresh", cfg),
                                              Path(args.output))
            print(json.dumps(result["results"], indent=2, ensure_ascii=False) if args.json else
                  "\n".join(f"{row['source_id']}\t{row['result']}" for row in result["results"]))
            return 0
        except SystemExit as e:
            return refuse_exit(e, emit)
        except AuthLost as e:
            return refuse_auth(e, emit)
        except TL.TableError as e:
            return refuse_table(e, emit)
        except Exception as e:
            return refuse_unexpected("refresh unavailable", e, emit)

    if args.command == "inspect":
        if not all((args.output, args.source_id, args.inspection_status)):
            print("usage: ticket_adapter.py inspect --output <inventory> --source-id <id> "
                  "(--attachment-id <id> --evidence-ref <path> | --media-url <url> "
                  "[--local-ref <path>]) --inspection-status read|partial|unavailable "
                  "[--provenance fetched|browser|person_pasted] [--probe-ref <vcs_evidence receipt>]", file=sys.stderr)
            media = [("--media-url", "media_url", None), ("--local-ref", "local_ref", None)] if args.media_url else [
                ("--attachment-id", "attachment_id", "<attachment id>"), ("--evidence-ref", "evidence_ref", "<path of the evidence you wrote>")]
            print(_ready_line("inspect", args, [_OUT, _ID, *media, ("--inspection-status", "inspection_status",
                                                                     "<one of: read, partial, unavailable>")]), file=sys.stderr)
            return 2
        try:
            if args.media_url:
                inventory = record_external_media(Path(args.output), args.source_id, args.media_url,
                                                  args.inspection_status, args.reason, args.local_ref,
                                                  args.provenance, args.probe_ref)
            elif args.attachment_id and args.evidence_ref:
                inventory = record_attachment_inspection(Path(args.output), args.source_id,
                                                         args.attachment_id, args.inspection_status,
                                                         args.evidence_ref, args.reason)
            else:
                raise ValueError("choose attachment-id plus evidence-ref, or media-url")
            if args.summary:
                print_summary(_source_of(inventory, args.source_id), inventory, args.output)
            else:
                print_result(inventory, args.json)
            return 0
        except Exception as e:
            print(f"ticket_adapter: inspection receipt rejected: {e}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED

    if args.command == "probe":
        if not args.output:
            print("usage: ticket_adapter.py probe --output <receipt.json> [TICKET]", file=sys.stderr)
            print(_ready_line("probe", args, [("--output", "output", "<the receipt file to write>"), ("", "ticket", None)]),
                  file=sys.stderr)
            return 2
        try:
            cfg = load_config()
            kind, adapter_cfg = resolve_adapter(cfg)
            if kind != "jira":
                fail(EXIT_NOT_CONFIGURED, "direct probe requires a Jira ticket adapter")
            receipt_path = Path(args.output)
            if _holds_inventory(receipt_path):
                # TP1-13797, driver run: the scout passed the inventory path as the probe's
                # --output and the receipt replaced four sources and the person's review words.
                receipt_path = receipt_path.with_name("ticket-probe.json")
                print(f"ticket_adapter: probe --output names the source inventory; the receipt "
                      f"goes to {receipt_path} instead", file=sys.stderr)
            receipt = probe_jira_direct(traced_client(adapter_cfg, args.ticket or "probe", cfg), receipt_path,
                                        args.ticket)
            print(json.dumps(receipt, indent=2, ensure_ascii=False) if args.json else
                  f"jira_direct_read\t{receipt['status']}\t{receipt['checked_at']}")
            return 0 if receipt["status"] == "available" else EXIT_NOT_CONFIGURED
        except SystemExit as e:
            return refuse_exit(e, emit)
        except AuthLost as e:
            # t-287 item 3: a token variable that is not set in this shell is raised by the read itself now (it is
            # no longer a FetchError the probe books as `unavailable`): the same one line and exit 5 as every verb
            return refuse_auth(e, emit)
        except Exception as e:
            return refuse_unexpected("direct probe unavailable", e, emit)

    if args.command == "receipts":
        # t-721 3.5: the receipt that a source's snapshot lies on disk is a fact of the code, not a role's write. One
        # idempotent door for a story that was running before the writer stamped it; the writer does it for new ones.
        if not args.output:
            print("usage: ticket_adapter.py receipts --output <work/source-inventory.json>", file=sys.stderr)
            print(_ready_line("receipts", args, [_OUT]), file=sys.stderr)
            return 2
        try:
            stamped, left = SI.stamp_snapshot_receipts(Path(args.output))
            print(f"receipts: {stamped} source(s) stamped from their snapshot on disk; {left} left as they are")
            return 0
        except Exception as e:
            print(f"ticket_adapter: receipts rejected: {e}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED

    if args.command == "assess":
        if not all((args.output, args.source_id, args.relevance, args.reason,
                    args.assessment_ref)):
            print("usage: ticket_adapter.py assess --output <inventory> --source-id <id> "
                  "--relevance relevant|not_relevant|unknown --reason <reason> "
                  "--assessment-ref <task-relative-path>", file=sys.stderr)
            print(_ready_line("assess", args, [_OUT, _ID, ("--relevance", "relevance", "<one of: relevant, not_relevant, unknown>"),
                                                ("--reason", "reason", "<why, in a sentence>"),
                                                ("--assessment-ref", "assessment_ref", "<task-relative path of your assessment>")]),
                  file=sys.stderr)
            return 2
        try:
            inventory = record_relevance_assessment(Path(args.output), args.source_id,
                                                    args.relevance, args.reason,
                                                    args.assessment_ref)
            if args.summary:
                print_summary(_source_of(inventory, args.source_id), inventory, args.output)
            else:
                print_result(inventory, args.json)
            return 0
        except Exception as e:
            print(f"ticket_adapter: relevance assessment rejected: {e}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED

    if not args.command or not args.ticket:
        print("usage: ticket_adapter.py get|children <TICKET> [--json] [--ticket-file <path>] "
              "[--raw-dir <work/ticket-raw>] [--output <snapshot.json> (get only)]  |  "
              "diff --old <path> --new <path> [--json]  |  "
              "freshness <TICKET> --task-root <root> [--ticket-file <path>] [--json] "
              "[--adopt | --decline --words-file <file>]  (or --selftest)", file=sys.stderr)
        # an unknown command word is never guessed: with none given the choice is the placeholder
        print(_ready_line(args.command or "<get|children>", args, [_TICKET, ("--json", "json", None),
                                                                     ("--ticket-file", "ticket_file", None)]), file=sys.stderr)
        return 2

    if args.command == "children" and args.output:
        print("ticket_adapter: `children --output` is not supported - a snapshot is the whole "
              "ticket. Use `get <TICKET> --output <path>` to write it.", file=sys.stderr)
        return EXIT_USAGE

    refused = _link_refusal(args, emit=emit)      # `get` / `children` too: a link is not a key, refused before any request (FR-1, FR-2)
    if refused:
        return refused
    ticket_file = args.ticket_file
    if not ticket_file and local_keys.is_local(args.ticket):
        # A local story (SS1-14): its text is the file the factory stored, read as the person's text, never the tracker's
        ticket_file = str(local_keys.ticket_path(args.ticket))
    if args.command == "get" and args.output:
        refused = _key_form_refusal(args, emit)
        if refused is not None:
            return refused
    try:
        if ticket_file:
            # The person handed this over: `person_pasted`, set here from the route (C13).
            ticket_obj = read_ticket_file(Path(ticket_file), args.ticket, pasted=True)
            if args.raw_dir and args.command == "get":
                write_paste_references(Path(ticket_file), ticket_obj, load_config(), args.ticket,
                                       Path(args.raw_dir).parent)
        else:
            cfg = load_config()
            ticket_obj = get_ticket(args.ticket, cfg, Path(args.raw_dir) if args.raw_dir else None,
                                    say=lambda line: print(line, file=sys.stderr))
        if args.command == "get":
            # After a successful read and before anything is printed: a failing read has
            # exited above, so the file is neither created nor touched by one.
            if args.key_form_word:      # the person's words that let this name stand, kept with the text they let in
                ticket_obj["provenance"] = dict(ticket_obj.get("provenance") or {}, key_form_word=words)
            if args.output:
                write_snapshot(ticket_obj, Path(args.output))
            if args.json:
                # The snapshot is the one document whose stdout is written as a file: `snapshot_bytes`, the very
                # bytes `get --output` and `freshness` write (L3), UTF-8 with LF everywhere.
                write_stdout(snapshot_bytes(ticket_obj))
            else:
                print_result(ticket_obj, False)
        else:
            print_result(ticket_obj.get("subtasks", []), args.json)
        return 0
    except SystemExit as e:
        return refuse_exit(e, emit)
    except AuthLost as e:
        return refuse_auth(e, emit)
    except TL.TableError as e:
        return refuse_table(e, emit)
    except FetchError as e:
        return refuse_fetch(e, args.ticket, emit)
    except Exception as e:  # never a crash: the factory's own fault, exit 4, named
        return refuse_unexpected("unexpected error", e, emit)


if __name__ == "__main__":
    sys.exit(main())
