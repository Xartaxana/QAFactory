"""The ticket-key form and the delivery forms are facts about the PROJECT'S tracker and version-control
host, so they are data (FR-13): `references/adapter-forms.json`, read by this one module.

What was scattered before (B-405, B-406): the Jira key shape written six times in three variants
(`ticket_light`, `case_forms`, `stage_guard`, `story_run`, `factory_dashboard`, `handoff_check`) and the
delivery commands as one literal tuple of two spellings in `stage_guard`. A project on GitHub or GitLab
issues has bare numeric ids, a project on Bitbucket opens its pull requests with its own program, and the
gate that stops a delivery before the verdict knew neither.

What a caller asks here:
  key_form(cfg)           the key shape in force for this project (a `KeyForm`), and where it came from
  is_key / keys_in        one value is a key / the keys a text names, in order, once each
  labelled_keys           the keys behind the `Ticket: <key>` line only - the one mention that NAMES a story
  delivery_forms(cfg)     every delivery command in force, each with its source
  segment_matches         does one shell segment (a list of tokens) run a delivery command

Defaults that keep today's behaviour: no config, tracker kind `jira` or `file` -> the Jira form;
every host's delivery commands are ALWAYS recognised, and a project's own
(`adapters.vcs.delivery_commands`) only widen the gate, never narrow it.

A table that cannot be read raises `FormsTableError` naming the file and the door (restore it from the
plugin package). A GATE or a text reader passes `floor=True` and gets the declared floor instead (FR-59:
never fewer forms than before the data existed, and the damage is named in `problems`); the loud readers
(readiness, the paste route of `ticket_adapter`) let the error through.

Stdlib only, and imports no factory module: it must stay importable from a hook and from `case_forms`.
"""
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TABLE_NAME = "adapter-forms.json"
TABLE_PATH = PLUGIN_ROOT / "references" / TABLE_NAME

# The declared floor (F6): what the gates use ONLY when the table cannot be read. A subset of the data
# (a test holds that), so a damaged table never narrows recognition below what the data names for Jira,
# `glab` and `gh`. The backslash of the regexes is written doubled, never typed through a heredoc (FR-29).
FLOOR_KEY = "[A-Z][A-Z0-9_]+-\\d+"
FLOOR_LABEL = "(?<![A-Za-z0-9_])Ticket:[ \\t]*#?({key})(?![A-Za-z0-9_-])"
FLOOR_EXAMPLE = "PROJ-123"
FLOOR_DELIVERY = ("glab mr create", "gh pr create")
FLOOR_SAYS = ("the built-in floor: the Jira key shape and "      # one sentence for every text that names the floor
              + " and ".join(f"`{command}`" for command in FLOOR_DELIVERY))
KEY_PATTERN_EXAMPLE = "[A-Z]{2,6}-[0-9]+"   # what a message offers as an example of `adapters.ticket.key_pattern`

KEY_SLOT = "({key})"          # where a mention template takes the key pattern
MIN_CONFIG_WORDS = 2          # a configured delivery command: the program and at least one subcommand word
_QUOTES = frozenset("\"'`" + chr(92))
# A form that reads ANY bare run of 1..12 digits carries no project prefix (`\d+`, `\d{4,}`, `[0-9]{5}`): its keys
# are numbers, and a number in running text is no key unless a mention (`#N`, `Ticket: N`) says so (edge 6).
_PROBES = tuple("123456789012"[:length] for length in range(1, 13))
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_KEYED_HEAD = re.compile(r"[^\\/]*=")   # a word whose first path component holds `=`: no program name (head_program)
FLOOR_MENTION = ("echo", "printf", "grep", "git commit")   # used only when the table cannot be read

# What `problems` entries are called, so a caller reads the kind of a note and never its wording.
TABLE_UNREADABLE = "forms_table_unreadable"
KEY_PATTERN_UNREADABLE = "key_pattern_unreadable"
KEY_PATTERN_IGNORED = "key_pattern_ignored"
TRACKER_KIND_GUESSED = "tracker_kind_guessed"
DELIVERY_ENTRY_INVALID = "delivery_entry_invalid"


class FormsTableError(ValueError):
    """references/adapter-forms.json is missing, malformed or holds a value no reader can use. The message
    names the file, what was expected and how to restore it (FR-1)."""


class Problem(NamedTuple):
    code: str
    text: str


@dataclass(frozen=True)
class Table:
    stamp: tuple
    kinds: dict          # tracker kind -> {"key", "example", "mentions": tuple}
    mentions: dict       # prefix-less mentions: {"hash", "label"}
    fallback: str
    aliases: dict        # program name -> host kind
    vcs: dict            # host kind -> tuple of delivery commands
    mention_commands: tuple   # commands whose quoted arguments are text, never a command (echo, grep, git commit)
    list_heads: tuple = ()    # words that open a list of words, not a command (`for x in $(a) $(b)`): read only by `releases`
    text_receivers: tuple = ()      # commands that only STORE or count what a heredoc hands them (`cat`, `tee`): OH3-22, read by the stage guard
    script_runners: tuple = ()      # launchers of a script FILE besides the python family (`run-py`): a script run is text-safe (OH3-22)
    script_plain_flags: tuple = ()  # flags of a python launcher that change nothing about which file runs (`-B`, `-u`): OH3-22
    local: dict | None = None       # `ticket.local` {key, example}: the key of a story no tracker holds (SS1-14); None when the table has none


@dataclass(frozen=True)
class KeyForm:
    kind: str                 # the tracker kind as the project wrote it (the fallback kind when it wrote none)
    source: str               # where the form comes from, as one clause a person can read
    pattern: str              # the bare key regex: no group, never matches the empty text
    story_pattern: str        # what a STORY may be named: `pattern`, or `(?:pattern|<local key>)` when `pattern` does not take the local example
    prefixed: bool            # keys carry a project prefix (`PROJ-123`); False for bare numbers
    strict: re.Pattern        # ^(?:pattern)$
    link_key: re.Pattern      # the key as a whole word in running text; group 1 is the key
    mentions: tuple           # prefix-less forms: every way a key is written in text (each with group 1)
    label: re.Pattern         # the `Ticket: <key>` mention; group 1 is the key
    example: str
    problems: tuple           # Problem rows: what was ignored or guessed, never silent


# ---------------------------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------------------------

def _refuse(what: str) -> FormsTableError:
    return FormsTableError(f"{TABLE_NAME}: {what}; restore references/{TABLE_NAME} from the plugin package "
                           f"(until then the gates use {FLOOR_SAYS})")


def _pattern_problem(pattern) -> str:
    """Why this is not a bare key pattern, or "" when it is: text, compiles, no capture group (the readers
    wrap it in their own), and does not match the empty text (it would make every position a key)."""
    if not isinstance(pattern, str) or not pattern.strip():
        return "is not text"
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"does not compile ({exc})"
    if compiled.groups:
        return "has a capture group - write it bare, use (?:...) for grouping"
    if compiled.search("") is not None:
        return "matches the empty text, so every position would be a key"
    return ""


def _with_key(template: str, pattern: str):
    return re.compile(template.replace(KEY_SLOT, "(" + pattern + ")", 1))


def _check_mention(template, pattern: str, where: str) -> str:
    if not isinstance(template, str) or template.count(KEY_SLOT) != 1:
        raise _refuse(f"{where} must be a regex text with exactly one {KEY_SLOT} group")
    try:
        compiled = _with_key(template, pattern)
    except re.error as exc:
        raise _refuse(f"{where} does not compile ({exc})") from None
    if compiled.groups != 1:
        raise _refuse(f"{where} must hold exactly one capture group, the key ({compiled.groups} found)")
    return template


def _check_kinds(ticket: dict) -> dict:
    kinds_raw = ticket.get("kinds")
    if not isinstance(kinds_raw, dict) or not kinds_raw:
        raise _refuse("`ticket.kinds` must be a non-empty object of tracker kinds")
    kinds = {}
    for kind, row in kinds_raw.items():
        where = f"`ticket.kinds.{kind}`"
        if not isinstance(kind, str) or not kind or kind != kind.strip().lower():
            raise _refuse(f"{where}: a kind is a non-empty lower-case word")
        if not isinstance(row, dict):
            raise _refuse(f"{where} must be an object {{key, example, mentions?}}")
        reason = _pattern_problem(row.get("key"))
        if reason:
            raise _refuse(f"{where}.key {reason}")
        if not isinstance(row.get("example"), str) or not row["example"].strip():
            raise _refuse(f"{where}.example must be the text a person would write")
        extra = row.get("mentions", [])
        if not isinstance(extra, list):
            raise _refuse(f"{where}.mentions must be a list")
        kinds[kind] = {"key": row["key"], "example": row["example"],
                       "mentions": tuple(_check_mention(m, row["key"], f"{where}.mentions[{i}]")
                                         for i, m in enumerate(extra))}
    return kinds


def _check_forms(forms, where: str) -> tuple:
    if not isinstance(forms, list) or not forms:
        raise _refuse(f"{where} must be a non-empty list of commands")
    out = []
    for item in forms:
        if not isinstance(item, str) or not item.split() or any(c in _QUOTES for c in item):
            raise _refuse(f"{where} holds {item!r}: a command is plain words, no quote or escape character")
        out.append(" ".join(item.split()))
    return tuple(out)


def _check_table(data, stamp: tuple) -> Table:
    if not isinstance(data, dict):
        raise _refuse(f"it must be a JSON object, got {type(data).__name__}")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        raise _refuse(f"`schema_version` must be 1, got {data.get('schema_version')!r}")
    ticket, vcs = data.get("ticket"), data.get("vcs")
    if not isinstance(ticket, dict) or not isinstance(vcs, dict):
        raise _refuse("`ticket` and `vcs` must be objects")
    kinds = _check_kinds(ticket)
    mentions_raw = ticket.get("prefixless_mentions")
    if not isinstance(mentions_raw, dict):
        raise _refuse("`ticket.prefixless_mentions` must be an object {hash, label}")
    mentions = {name: _check_mention(mentions_raw.get(name), "\\d+", f"`ticket.prefixless_mentions.{name}`")
                for name in ("hash", "label")}
    fallback = ticket.get("fallback_kind")
    if fallback not in kinds:
        raise _refuse(f"`ticket.fallback_kind` {fallback!r} must be one of the kinds: {', '.join(kinds)}")
    hosts_raw = vcs.get("kinds")
    if not isinstance(hosts_raw, dict) or not hosts_raw:
        raise _refuse("`vcs.kinds` must be a non-empty object of host kinds")
    hosts = {host: _check_forms((row or {}).get("delivery_commands") if isinstance(row, dict) else None,
                                f"`vcs.kinds.{host}.delivery_commands`") for host, row in hosts_raw.items()}
    aliases = vcs.get("aliases")
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) or v not in hosts
                                            for k, v in aliases.items()):
        raise _refuse("`vcs.aliases` must map a program name to one of the host kinds")
    said = vcs.get("mention_commands")
    if not isinstance(said, list) or not said or any(
            not isinstance(item, str) or not 0 < len(item.split()) <= 2 or any(c in _QUOTES for c in item)
            for item in said):
        raise _refuse("`vcs.mention_commands` must be a non-empty list of commands of one or two plain words")
    # CX2-27, OH3-22: these lists are optional - an absent key reads as none (today's reading, the side of refusal: no head
    # releases a substitution, no receiver takes a body out of the guard's reading)
    heads, receivers, runners = (_plain_words(vcs, key, True) for key in ("list_heads", "text_receivers", "script_runners"))
    flags = _plain_words(vcs, "script_plain_flags", False)   # flags keep their case: `-s` and `-S` are two flags
    return Table(stamp, kinds, mentions, fallback, dict(aliases), hosts,
                 tuple(tuple(item.lower().split()) for item in said), heads, receivers, runners, flags,
                 _check_local(ticket))


def _check_local(ticket: dict):
    """`ticket.local` {key, example} (SS1-14), checked by the rules of a kind's `key`; absent reads as none (a local key
    is then never recognised: today's reading). Not a kind: a project's tracker is never `local`."""
    row = ticket.get("local")
    if row is None:
        return None
    if not isinstance(row, dict):
        raise _refuse("`ticket.local` must be an object {key, example}")
    reason = _pattern_problem(row.get("key"))
    if reason:
        raise _refuse(f"`ticket.local`.key {reason}")
    example = row.get("example")
    if not isinstance(example, str) or re.fullmatch(row["key"], example, re.ASCII) is None:
        raise _refuse("`ticket.local`.example must be one key of that form, the text a person would write")
    return {"key": row["key"], "example": example}


def _plain_words(vcs: dict, key: str, lower: bool) -> tuple:
    """`vcs.<key>`: an optional list of single plain words (no blank, no quote or escape character), as a tuple."""
    items = vcs.get(key, [])
    if not isinstance(items, list) or any(not isinstance(item, str) or len(item.split()) != 1 or any(c in _QUOTES for c in item)
                                          for item in items):
        raise _refuse(f"`vcs.{key}` must be a list of single plain words")
    return tuple(item.lower() if lower else item for item in items)


_TABLE_CACHE: tuple | None = None   # (stamp, Table)


def load_table(path=None) -> Table:
    """The validated table, cached per process by the file's stat (a rewrite is seen, a thousand calls cost
    one stat each). Raises `FormsTableError` naming the file and the restore door."""
    global _TABLE_CACHE
    path = path or TABLE_PATH
    try:
        info = os.stat(path)    # the hot path of a hook: one stat, no Path object built
        stamp = (os.fspath(path), info.st_mtime_ns, info.st_size)
        if _TABLE_CACHE is not None and _TABLE_CACHE[0] == stamp:
            return _TABLE_CACHE[1]
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise _refuse(f"it cannot be read ({exc.__class__.__name__}); expected the table at {path}") from None
    except ValueError as exc:
        raise _refuse(f"it is not valid JSON ({exc})") from None
    table = _check_table(data, stamp)
    _TABLE_CACHE = (stamp, table)
    return table


def _damage(exc: Exception) -> Problem:
    return Problem(TABLE_UNREADABLE, str(exc))


# ---------------------------------------------------------------------------------------------
# The ticket key
# ---------------------------------------------------------------------------------------------

def _entry(cfg, section: str) -> dict:
    adapters = cfg.get("adapters") if isinstance(cfg, dict) else None
    row = adapters.get(section) if isinstance(adapters, dict) else None
    return row if isinstance(row, dict) else {}


def ticket_entry(cfg) -> dict:
    """The `adapters.ticket` row of a config, `{}` when it is absent or not an object: the ONE lookup of it (t-586 F-11)."""
    return _entry(cfg, "ticket")


def ticket_kind(cfg) -> str:
    """The tracker kind the project names (`adapters.ticket.kind`, else `.name`), lower-cased; "" when it
    names none. The ONE reader of it: `ticket_adapter.resolve_adapter` asks here."""
    row = _entry(cfg, "ticket")
    return str(row.get("kind") or row.get("name") or "").strip().lower()


def _story_pattern(pattern: str, local) -> str:
    """What a story may be named: the tracker's `pattern` when it already takes the local example whole (Jira), else
    `(?:pattern|<local key>)` (GitHub's bare numbers), built from the table's `ticket.local`, never a literal (AR-1)."""
    if not local or re.fullmatch(pattern, local["example"]):
        return pattern
    return "(?:" + pattern + "|" + local["key"] + ")"


def _form(kind: str, source: str, pattern: str, example: str, extra: tuple, problems: tuple,
          mentions: dict, local=None) -> KeyForm:
    prefixed = not any(re.fullmatch(pattern, probe) for probe in _PROBES)   # by the TRACKER's pattern: GitHub's bare numbers stay no key in text
    story = _story_pattern(pattern, local)
    label = _with_key(mentions["label"], story)
    found = () if prefixed else (_with_key(mentions["hash"], story), label) + tuple(
        _with_key(template, story) for template in extra)
    return KeyForm(kind=kind, source=source, pattern=pattern, story_pattern=story, prefixed=prefixed,
                   strict=re.compile("^(?:" + story + ")$"),
                   link_key=re.compile("(?<![A-Za-z0-9_])(" + story + ")(?![A-Za-z0-9])"),
                   mentions=found, label=label, example=example, problems=problems)


def _floor_form(exc: Exception) -> KeyForm:
    return _form("jira", "the built-in floor (the table cannot be read)", FLOOR_KEY, FLOOR_EXAMPLE, (),
                 (_damage(exc),), {"label": FLOOR_LABEL, "hash": ""})


def _pattern_is_read(kind: str, known) -> bool:
    """THE rule: `adapters.ticket.key_pattern` is read for kind `file` and for a kind the table does not know (`known` is None);
    on a kind with its own form it is ignored. `_project_pattern` and `key_pattern_honoured` both ask here."""
    return known is None or kind == "file"


def _project_pattern(row: dict, kind: str, known) -> tuple:
    """(pattern or None, problems): `adapters.ticket.key_pattern` - read for `file` and for a kind the
    table does not know; on a kind the table knows it is ignored, with a note (one form per kind)."""
    word = row.get("key_pattern")
    if word is None or (isinstance(word, str) and not word.strip()):
        return None, ()
    reason = _pattern_problem(word)
    if reason:
        return None, (Problem(KEY_PATTERN_UNREADABLE,
                              f"adapters.ticket.key_pattern {word!r} {reason}; it is ignored. Expected a bare "
                              f"regex for one ticket key, for example {KEY_PATTERN_EXAMPLE}"),)
    if not _pattern_is_read(kind, known):
        return None, (Problem(KEY_PATTERN_IGNORED,
                              f"adapters.ticket.key_pattern is ignored: tracker kind `{kind}` has its own key "
                              f"form in references/{TABLE_NAME}, one form per kind"),)
    return word, ()


_FORM_CACHE: dict = {}


def key_form(cfg=None, floor: bool = False) -> KeyForm:
    """The ticket key shape in force: the tracker kind's own form from the table; `file` and a kind the table
    does not know may bring `adapters.ticket.key_pattern`; no kind at all is the table's fallback kind. An
    unknown kind with no usable pattern is the fallback form AND a note that it is a guess. Cached by the
    project's three words (kind, name, pattern); `floor=True` answers the declared floor when the table cannot
    be read (the damage is in `problems`) instead of raising."""
    try:
        table = load_table()
    except FormsTableError as exc:
        if not floor:
            raise
        return _floor_form(exc)
    row = _entry(cfg, "ticket")
    stamp = (table.stamp, repr((row.get("kind"), row.get("name"), row.get("key_pattern"))))
    found = _FORM_CACHE.get(stamp)
    if found is None:
        if len(_FORM_CACHE) >= 256:
            _FORM_CACHE.clear()
        found = _FORM_CACHE[stamp] = _build(table, row, ticket_kind(cfg))
    return found


def _build(table: Table, row: dict, kind: str) -> KeyForm:
    known = table.kinds.get(kind)
    custom, problems = _project_pattern(row, kind, known)
    if custom is not None:
        return _form(kind or table.fallback, "adapters.ticket.key_pattern", custom, "",
                     known["mentions"] if known else (), problems, table.mentions, table.local)
    if known is None:
        base = table.kinds[table.fallback]
        if not kind:
            source = f"the default (adapters.ticket names no tracker kind: the {table.fallback} form)"
        else:
            source = (f"a guess: tracker kind `{kind}` is not in references/{TABLE_NAME}, so the "
                      f"{table.fallback} form is assumed")
            problems += (Problem(TRACKER_KIND_GUESSED,
                                 f"tracker kind `{kind}` is not in references/{TABLE_NAME}: the {table.fallback} "
                                 "key form is a guess; set adapters.ticket.key_pattern to the shape of one key"),)
        return _form(kind or table.fallback, source, base["key"], base["example"], base["mentions"], problems,
                     table.mentions, table.local)
    return _form(kind, f"tracker kind `{kind}` in references/{TABLE_NAME}", known["key"], known["example"],
                 known["mentions"], problems, table.mentions, table.local)


def describe_key_form(cfg=None) -> str:
    """One clause for a person: what a key looks like here and where that comes from."""
    form = key_form(cfg, floor=True)
    shape = f"like {form.example} " if form.example else ""
    return f"a ticket key {shape}(pattern {form.pattern}; from {form.source})"


def _text(value) -> str:
    return value if isinstance(value, str) else str(value or "")


def is_key(value, cfg=None) -> bool:
    """Is the WHOLE value one ticket key? Not a string -> False; a trailing newline or a space is not part
    of a key (`fullmatch`, not `match`)."""
    return isinstance(value, str) and key_form(cfg, floor=True).strict.fullmatch(value) is not None


def key_pattern_honoured(cfg=None) -> bool:
    """Would `adapters.ticket.key_pattern` be READ for this project (kind `file`, a kind the table does not know, or no
    kind named)? False on a kind with its own form, and when the table cannot be read (then no pattern is read at all).
    Both this and `_project_pattern` ask `_pattern_is_read`; a question that offers to set the pattern asks here first."""
    try:
        table = load_table()
    except FormsTableError:
        return False
    kind = ticket_kind(cfg)
    return _pattern_is_read(kind, table.kinds.get(kind))


def form_is_guess(cfg=None) -> bool:
    """Is the key form of this project a guess (a tracker kind the table does not know and no usable key_pattern)?"""
    return any(p.code == TRACKER_KIND_GUESSED for p in key_form(cfg, floor=True).problems)


def key_refused(key, cfg=None) -> bool:
    """Is this value NOT a key of the project's tracker, on a form the factory KNOWS? A guessed form never refuses
    (a false refusal costs a question, but a guess has no standing to ask it). The ONE gate of a launch key: the driver
    at S0 and `ticket_adapter get --output` ask here (AR-15, AR-19)."""
    return not is_key(key, cfg) and not form_is_guess(cfg)


def is_local_form(key) -> bool:
    """Does the value LOOK like a local key (`ticket.local`, e.g. LOCAL-1)? The shape only, `fullmatch`, ASCII digits: a
    value is a local STORY only when `local_keys.is_local` also finds its text. No table, no `local` row, not text: False."""
    if not isinstance(key, str):
        return False
    try:
        local = load_table().local
    except FormsTableError:
        return False
    return bool(local) and re.fullmatch(local["key"], key, re.ASCII) is not None


def _unique_in_order(hits) -> list:
    return list(dict.fromkeys(key for _start, key in sorted(hits)))


def form_keys(text, form: KeyForm) -> list:
    """Every ticket key a text names under `form`, in order, each once. A prefixed form reads whole-word
    keys; a prefix-less one reads only its mentions (`#123`, `Ticket: 123`, ...) - a bare number in running
    text is never a key."""
    subject = _text(text)
    if form.prefixed:
        return list(dict.fromkeys(m.group(1) for m in form.link_key.finditer(subject)))
    return _unique_in_order((m.start(), m.group(1)) for rx in form.mentions for m in rx.finditer(subject))


def keys_in(text, cfg=None) -> list:
    """`form_keys` for the project's form (`floor=True`: a damaged table reads the declared floor)."""
    return form_keys(text, key_form(cfg, floor=True))


def labelled_keys(text, cfg=None) -> list:
    """The keys behind the `Ticket: <key>` mention only, in order, each once, under every form: the line the
    factory writes into every dispatch, and the only mention that NAMES a story."""
    return list(dict.fromkeys(m.group(1) for m in key_form(cfg, floor=True).label.finditer(_text(text))))


def prefix_of(key, form: KeyForm):
    """The project prefix of a key (`PROJ` of `PROJ-123`), or None: a prefix-less form has none."""
    if not form.prefixed or not isinstance(key, str) or "-" not in key:
        return None
    return key.rsplit("-", 1)[0]


# ---------------------------------------------------------------------------------------------
# The delivery commands
# ---------------------------------------------------------------------------------------------

def vcs_kind(cfg) -> str:
    """The host kind the project names (`adapters.vcs.name`, else `.kind`), through the table's aliases
    (`glab` is gitlab, `gh` is github); "" when it names none. A name the table does not know stays as written."""
    row = _entry(cfg, "vcs")
    name = str(row.get("name") or row.get("kind") or "").strip().lower()
    try:
        return load_table().aliases.get(name, name)
    except FormsTableError:
        return name


def _entry_problem(item) -> str:
    if not isinstance(item, str):
        return "is not text"
    if len(item.split()) < MIN_CONFIG_WORDS:
        return ("is fewer than two words - write the program and its subcommand (for example `bb pr create`); "
                "one word would gate every use of that program")
    if any(c in _QUOTES for c in item):
        return "holds a quote or escape character - write the words plain"
    return ""


def _configured(cfg) -> tuple:
    """(valid entries, Problem rows) of `adapters.vcs.delivery_commands`: text is one entry, a list is many,
    absent and [] are none. An invalid entry is ignored and named, never the reason a valid one is dropped."""
    raw = _entry(cfg, "vcs").get("delivery_commands")
    if raw is None:
        return (), ()
    items = raw if isinstance(raw, list) else [raw]
    good, bad = [], []
    for item in items:
        reason = _entry_problem(item)
        if reason:
            bad.append(Problem(DELIVERY_ENTRY_INVALID, f"adapters.vcs.delivery_commands entry {item!r} {reason}; "
                                                       "it is ignored"))
        else:
            good.append(" ".join(item.split()))
    return tuple(good), tuple(bad)


_DELIVERY_CACHE: dict = {}


def delivery_forms(cfg=None, floor: bool = False) -> tuple:
    """Every delivery command in force as (command, source): all of the table's, whatever the project's
    host is, then the project's own. Config widens, never narrows. `floor=True` answers the declared floor
    for the table's part when the table cannot be read."""
    try:
        table = load_table()
    except FormsTableError:
        if not floor:
            raise
        table = None
    key = (table.stamp if table else None, repr(_entry(cfg, "vcs").get("delivery_commands")))
    found = _DELIVERY_CACHE.get(key)
    if found is None:
        if len(_DELIVERY_CACHE) >= 256:
            _DELIVERY_CACHE.clear()
        found = _DELIVERY_CACHE[key] = _delivery_forms_of(table, cfg)
    return found


def _delivery_forms_of(table, cfg) -> tuple:
    if table is not None:
        base = [(form, f"references/{TABLE_NAME} ({host})") for host, forms in table.vcs.items() for form in forms]
    else:
        base = [(form, f"the built-in floor (references/{TABLE_NAME} cannot be read)") for form in FLOOR_DELIVERY]
    base += [(form, "adapters.vcs.delivery_commands") for form in _configured(cfg)[0]]
    seen: dict = {}
    for form, source in base:
        seen.setdefault(form, source)
    return tuple(seen.items())


def delivery_problems(cfg=None) -> list:
    """Problem rows of the delivery side: an unreadable table, and every invalid configured entry."""
    out = []
    try:
        load_table()
    except FormsTableError as exc:
        out.append(_damage(exc))
    return out + list(_configured(cfg)[1])


@lru_cache(maxsize=512)
def prefilter_words(form: str) -> tuple:
    """The lower-cased words of a command: all of them must occur in a text for the command to be in it
    (cached: a gate asks it for every form on every call)."""
    return tuple(word.lower() for word in form.split())


_SUBSTITUTION_MARKS = ("$", "`", "(")   # a variable, a substitution, a backtick pair, a PowerShell group


def could_be_in(form: str, squeezed: str, raw: str | None = None) -> bool:
    """The cheap gate before tokenizing: every word of the command occurs in `squeezed` (the text lower-cased with its
    quote and escape characters taken out) OR in `raw` (the text as written, lower-cased: a substitution in the text
    may build a word - `gh pr cre$(true)ate` has `create` in neither view - so a text with any mark is admitted whole).
    A text with a mark (`$` variable or substitution, a backtick, a PowerShell `(`) may name the program through it
    (`$tool pr create`, `$(echo gh) pr create`, `` `printf g; printf h` pr create ``), so there the program word may
    be absent. The error direction is True: a false admit costs one walk."""
    words = prefilter_words(form)
    seen = squeezed if raw is None else raw   # the quote-stripped view has lost the backtick
    if len(words) > 1 and any(mark in seen for mark in _SUBSTITUTION_MARKS):
        words = words[1:]
    return all(word in squeezed for word in words) or (raw is not None and ("$(" in raw or "`" in raw))


def _option(text: str) -> bool:
    return len(text) > 1 and text.startswith("-")


STEPS = [0]   # (token, word) cells the matcher visited: a test bounds it, so the cost is O(tokens x words)


def _words_follow_from(words: list, tokens: list, clean=None, is_wild=None) -> list:
    """`ok[pos]`: do `words` follow in `tokens[pos:]` in order, with OPTIONS between them? An option is skipped
    with the one value it may take (`--repo x/y`, `-R x/y`); any other word in between means another
    subcommand (`gh pr list create` is no delivery). The walk is a machine whose state is (words matched,
    a value pending), so it is computed ONCE for every start, right to left - not once per start by
    scanning ahead, which cost O(tokens^2) on `gh --x gh --x ... pr list`. `clean` and `is_wild` are the caller's
    reading of a word (see `segment_matches`)."""
    count, size = len(words), len(tokens)
    after = [[False, False] for _ in range(count)]        # past the last token nothing completes
    ok = [False] * (size + 1)
    for pos in range(size - 1, -1, -1):
        text, quoted = tokens[pos]
        option = not quoted and _option(text)
        keeps = "=" not in text
        wild = not quoted and bool(is_wild and is_wild(text))
        glued = clean(text) if clean and not quoted else ""   # a wild word with literal text stands for a word only if that text can be part of it (OH3-22)
        here = []
        held = _held_words(text) if wild else ()
        for wanted in range(count):
            if wild and _can_be_part(glued, words[wanted]):
                # an unquoted substitution may stand for any ONE word of the form, or for none (CX1-20 B-1, NM-4); one that
                # WRITES all the words still wanted (`$(echo pr create)`) stands for them all: the role wrote the form (CX2-27)
                fits = wanted + 1 == count or after[wanted + 1][0] or all(word in held for word in words[wanted:])
                here.append([fits or after[wanted][0]] * 2)
            elif not quoted and (text == words[wanted] or glued == words[wanted]):
                done = wanted + 1 == count or after[wanted + 1][0]
                here.append([done, done])
            elif option:
                here.append([after[wanted][keeps]] * 2)
            else:
                here.append([False, after[wanted][0]])
        STEPS[0] += count
        after = here
        ok[pos] = after[0][0]
    return ok


def _push_option_in(word: str, tokens: list) -> bool:
    """A one-word form is a push option (`git push -o merge_request.create`): a token that is the word or
    ends in `=<word>`. Inside quotes only as the value of an option, so `echo "merge_request.create"` is a
    mention."""
    for at, (text, quoted) in enumerate(tokens):
        if text == word or text.endswith("=" + word):
            if not quoted or (at and _option(tokens[at - 1][0])):
                return True
    return False


def _can_be_part(literal: str, word: str) -> bool:
    """Can the literal text of a wild word (its substitutions deleted) be PART of `word` - its characters in order, case
    ignored? An empty literal can (`$(x)`); `g` can be part of `gh`, `foo,` cannot be part of `mr` (OH3-22: `def log(a):
    foo(b), create_mr()` is no `glab mr create` for the walker's PowerShell groups). Cost O(len(word))."""
    chars = iter(word.lower())
    return all(char in chars for char in literal.lower())


def _may_start(text, program: str, name=None, clean=None) -> bool:
    """May this wild word (an unquoted substitution in it) BE the program `program`? The literal text it holds, with a path
    and an executable suffix off, must be part of the program (`GH$(x)`, `/usr/bin/$(x)`, `C:\\t\\$(x).exe`, `$(x).exe`
    stand for `gh`; `log(a):` does not stand for `glab`); an assignment (`FOO=$(f)`) is no start. A bare suffix reads as empty."""
    if _ASSIGNMENT.match(text):
        return False
    raw = getattr(text, "clean", None)   # the walker's Word keeps the text with its substitutions deleted and its backslashes
    literal = raw if isinstance(raw, str) else (clean(text) if clean else "")
    literal = (name(literal) if name else literal).lower()
    literal = "".join(char for char in literal if char not in "\"'`")
    return literal.startswith(".") or _can_be_part(literal, program)


def _held_words(text: str) -> set:
    """The blank-delimited words a wild word WRITES in its raw text, with `$(`, `)` and the backtick blank: `$(echo pr
    create)` holds echo, pr, create (a plain blank split alone gives `create)`)."""
    return set(text.replace("$(", " ").replace(")", " ").replace("`", " ").split())


def _last_literal(words: list, tokens: list, clean=None, is_wild=None) -> int:
    """The index of the LAST token that is a literal form word (a word of `words`, the form after its program), or -1: an
    unquoted token equal to one, or equal to one once its substitutions, quotes and escapes are deleted, or a wild word
    whose RAW text holds one blank-delimited (`$(echo pr create)` holds `pr` and `create` once `$(`, `)` and the backtick
    are blank). One right-to-left scan: the cost of a start's verdict is a comparison with this index (CX2-27)."""
    wanted = set(words)
    for at in range(len(tokens) - 1, -1, -1):
        text, quoted = tokens[at]
        if quoted:
            continue
        if text in wanted or (clean is not None and clean(text) in wanted):
            return at
        if is_wild and is_wild(text) and wanted.intersection(_held_words(text)):
            return at
    return -1


def segment_matches(form: str, tokens: list, name=None, clean=None, is_wild=None, *, released: bool = False) -> bool:
    """Does one shell segment run this delivery command? `tokens` are (text, came_from_a_quoted_run) pairs,
    as the shell tokenizer cuts them, so the whole command in ONE quoted argument (`echo "glab mr create"`)
    is a mention and never a match. The program may stand anywhere in the segment (`sudo gh pr create`,
    `env X=1 glab mr create`), its words follow it in order with whitespace runs and options between them
    (`glab  mr create`, `glab --repo x/y mr create`).

    The caller supplies how a word is READ - this module imports no factory module, so the walker's views arrive as
    arguments (CX1-20 F-4: the ONE cleaner and the ONE wild test are `hooklib.cleaned_word` and `hooklib.is_wild`, not a
    copy here): `name` normalises a program token (basename, no executable suffix); `clean` gives a word with its
    substitutions, quotes and escapes deleted (`cre$(true)ate` -> `create`), and a word that equals a form word that way
    matches it; `is_wild` says a word holds an unquoted substitution and may stand for any ONE word of the form (or for
    none; in program position for the program and the words after it, `` `echo gh pr` create ``). Without them a word
    is what it is written as: no substitution is read.

    What counts as EVIDENCE of the form (CX2-27; the error direction stays toward refusal): a start that is NAMED (the program
    by its name, or once cleaned) always counts. A `$var` start (`$gh pr create`) counts only when a literal form word
    stands after it (`_last_literal`): `$a $(f)` holds no sign of a delivery, and `_wildcard` itself is not narrowed.
    A start with an unquoted substitution counts as it did - one substitution may stand for a word of the form - unless
    `released` (the CALLER's reading of the segment's head: a mention command, a `$var`, a list head; `releases`) and no
    literal form word stands after it: a head that is no command of its own leaves pure substitutions as arguments, text
    to the shell. Any other head keeps today's reading (`git $(a) $(b) commit`, `$(a) $(b)`)."""
    words = form.split()
    if not words:
        return False
    if len(words) == 1:
        return _push_option_in(words[0], tokens)
    program = words[0].lower()
    starts, last = [], None
    for at, (text, quoted) in enumerate(tokens):
        if quoted:
            continue
        if (name(text) if name else text).lower() == program or (clean is not None and clean(text) == program):
            starts.append(at)
        elif _wildcard(text, is_wild):
            if is_wild and is_wild(text):
                if not _may_start(text, program, name, clean):
                    continue   # its own literal text cannot be part of the program (OH3-22)
                if not released:
                    starts.append(at)
                    continue
            last = _last_literal(words[1:], tokens, clean, is_wild) if last is None else last
            if last > at:
                starts.append(at)
    if not starts:
        return False
    follows = _words_follow_from(words[1:], tokens, clean, is_wild)
    if any(follows[at + 1] for at in starts):
        return True
    # a substitution in program position may stand for the program AND the words after it (`` `echo gh pr` create ``)
    wild = [at for at in starts if is_wild and is_wild(tokens[at][0])]
    for k in range(2, len(words)) if wild else ():
        reach = _words_follow_from(words[k:], tokens, clean, is_wild)
        if any(reach[at + 1] for at in wild):
            return True
    return False


def program_written(form: str, tokens: list, name=None, clean=None) -> bool:
    """Is the form's program (its first word) written in the segment, by its name or once its substitutions, quotes and
    escapes are deleted - and not left to a substitution that may stand for it?"""
    words = form.split()
    program = words[0].lower() if words else ""
    return any(not quoted and ((name(text) if name else text).lower() == program
                               or (clean is not None and clean(text) == program)) for text, quoted in tokens)


def written_form(form: str, tokens: list, name=None, clean=None) -> str:
    """The delivery command as the ROLE wrote it, for a refusal that names it (FR-1; CX1-20 Q-5). `segment_matches` lets a
    substitution stand for a word of the form, so a form it fits is not always what the role typed (`gh $(x) create`
    fits `glab mr create` with the substitution as the program). The form itself when the segment holds its words with no
    substitution in the place of any; the program and an ellipsis (`gh ...`) when the program is written and a
    substitution fills a later slot; the segment's own first words when the program itself is a substitution."""
    if segment_matches(form, tokens, name, clean):   # no word is read as wild: a plain match
        return form
    if program_written(form, tokens, name, clean):
        return form.split()[0] + " ..."
    shown = [str(text) for text, _quoted in tokens[:4]]
    return " ".join(shown) + (" ..." if len(tokens) > 4 else "")


def _wildcard(text, is_wild=None) -> bool:
    """A word in program position that may BE the program: `$gh pr create`, `${tool} pr create` (a variable), and a word
    with an unquoted substitution - `$(echo gh) pr create`, a backtick pair, a PowerShell `(...)` group (CX1-20 B-1; the
    walker marks it, the caller's `is_wild`). It counts as the program when the form's words follow it (errs toward
    refusing; `gh=gh; $gh pr create` is no way past the gate)."""
    return bool(is_wild and is_wild(text)) or (len(text) > 1 and text.startswith("$") and text[1] != "(")


def mention_commands() -> tuple:
    """`vcs.mention_commands` as tuples of words (the declared floor when the table cannot be read)."""
    try:
        return load_table().mention_commands
    except FormsTableError:
        return tuple(tuple(item.split()) for item in FLOOR_MENTION)


def mention_command(tokens: list, name=None, said: tuple | None = None) -> bool:
    """Is this segment a command whose quoted arguments are TEXT (`vcs.mention_commands`: echo, grep, git commit)?
    The head is the first token that is no `NAME=value` assignment; a two-word entry (`git commit`) also names the
    first non-option word after it. The quoted arguments of any other command are read as commands again.
    `said` is `mention_commands()` when a caller asks for many segments."""
    said = mention_commands() if said is None else said
    head = head_at(tokens)
    if head is None:
        return False
    program = head_program(tokens[head][0], name)
    # the subcommand is one of the first two non-option words (`git -C app commit`, `git --no-pager log`: an option
    # may or may not take the word after it, and this cannot tell which)
    subs = [text.lower() for text, quoted in tokens[head + 1:] if quoted or not _option(text)][:2]
    return any(entry[0] == program and (len(entry) == 1 or entry[1] in subs) for entry in said)


def head_at(tokens: list):
    """The index of a segment's head: the first token that is quoted or no `NAME=value` assignment, or None."""
    return next((at for at, (text, quoted) in enumerate(tokens) if quoted or not _ASSIGNMENT.match(text)), None)


def head_program(text: str, name=None) -> str:
    """The program a head word names, lower-case: `name(text)` (a basename), or EMPTY when the first path component of the
    word holds `=` (`a.b=/x/python`, `-x=/bin/cat`: no assignment, and no program the guard can know - a basename would
    read `python`, a launcher or receiver, and release a body refused before). `./a=b/python` and `C:\\a=b\\python` stay
    programs: their first component holds no `=`. The one reader of a head word's program (AR-13)."""
    if _KEYED_HEAD.match(text):
        return ""
    return (name(text) if name else text).lower()


def list_heads() -> tuple:
    """`vcs.list_heads` as lower-case words (empty when the table cannot be read: a damaged table releases nothing, so
    it never narrows what the gate refuses)."""
    return _table_words("list_heads")


def _table_words(field: str) -> tuple:
    """One optional word list of the table; EMPTY when the table cannot be read (OH3-22: a damaged table never widens what
    the guard reads as text - nothing comes out of a command and it is read raw, as before the data existed)."""
    try:
        return getattr(load_table(), field)
    except FormsTableError:
        return ()


def text_receivers() -> tuple:
    """`vcs.text_receivers`: the commands that only store or count what a heredoc hands them (lower-case words)."""
    return _table_words("text_receivers")


def script_runners() -> tuple:
    """`vcs.script_runners`: launchers of a script file that are not in `launch-causes.json` `launchers` (lower-case)."""
    return _table_words("script_runners")


def script_plain_flags() -> tuple:
    """`vcs.script_plain_flags`: flags a script launcher takes that leave the launched file as the next word (`-B`)."""
    return _table_words("script_plain_flags")


def releases(tokens: list, name=None, said: tuple | None = None, heads: tuple | None = None, is_wild=None) -> bool:
    """Is the segment's head a word whose substitution ARGUMENTS are text and not a command (CX2-27, Rule H of
    `segment_matches`)? A mention command (`echo $(a) $(b)`), a `$var` (`$a $(f) $(g)`: a bare variable is no program the
    guard can know) or a list head (`for f in $(a) $(b)`: `vcs.list_heads`). Any other head - a named program, a
    substitution, a group - releases nothing. `said` and `heads` are `mention_commands()` and `list_heads()` when a caller
    asks for many segments."""
    head = head_at(tokens)
    if head is None:
        return False
    text, quoted = tokens[head]
    if not quoted and len(text) > 1 and text.startswith("$") and text[1] != "(" and not (is_wild and is_wild(text)):
        return True
    heads = list_heads() if heads is None else heads
    program = head_program(text, name)
    return mention_command(tokens, name, said) or (not quoted and program in heads)
