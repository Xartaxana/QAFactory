"""The spellings of a machine fact, and the one exit filter of the collect archive (CL1-1, t-973, t-987).

Two jobs, one module. (a) It is the ONE generator of the spellings of a path (`path_variants`, `machine_table`): the test-side
census `scripts/tests/state_census.py` imports it, the redactor uses it, so a spelling is learned once. A change to a spelling
(`path_variants`, `machine_table`) means: run `scripts/tests/test_state_portability.py`, it measures the census over them.
(b) It is the exit filter every byte of the collect archive passes (`compile_redactor` -> `Redactor`): file contents, text
excerpts, manifest strings, archive member names.

Error direction. The census measurer used to be advice (a missed spelling was a debt row); here a miss is a LEAK. Redacting too
much is allowed (a whole line lost, a word that is not a secret replaced); a secret, a name, a machine name, an e-mail, a known
host or an absolute path in the output is the defect. Whatever cannot be read is `skipped` with a reason, never emitted raw and
never a crash; whatever the redactor will NOT search for (too short, absent) is a named row of `Redactor.gaps` carrying a KIND and
a LENGTH, never the value. The closed variety (patterns, header names, tokens, limits, kept hosts) is data:
`references/collect-redaction.json`; the guard's secret patterns are imported from `guard_secrets`, not copied.

Functions over strings and bytes, except the ones that read: `load_rules` and `known_hosts` (the rules file), `secret_values`
(the env_file) and `machine_identities` (the environment, git, the host). `hooklib`, `guard_secrets`,
`http_client`, `reachability`, `env_probe` and `project_inventory` are imported lazily inside the functions that need them, so
`import machine_facts` from the census pulls no hooklib (no stdio reconfiguration). `main()` prints the rules file's sha256 and
the shape of this machine's table (counts, never values); it is also what keeps the module live for audit A1 until the collector
imports it.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import tempfile
import urllib.parse
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = PACKAGE_ROOT / "references" / "collect-redaction.json"
MIN_NAME_CHARS = 3          # a spelling or a name shorter than this matches by chance (was `len(text) >= 3` in the census)
MIN_HOST_CHARS = 6          # a machine name shorter than this matches by chance (was `len(host) >= 6` in the census)
CATEGORIES = ("path", "user", "secret", "host", "email")
REQUIRED_KEYS = ("schema", "note", "limits", "json_suffixes", "jsonl_suffixes", "tokens", "secret_patterns", "secret_key_names",
                 "header_names", "email_regex", "url_regex", "scp_regex", "credential_url_regex", "bare_host_port_regex",
                 "ipv4_regex", "residual_path_starts", "path_stop_chars", "private_ip_ranges", "home_roots", "hosts_kept",
                 "generic_accounts", "name_separators", "assigned_value_twin")
LIMIT_KEYS = ("min_secret_value_chars", "parse_max_bytes", "text_max_bytes", "max_json_depth", "unescape_rounds",
              "percent_rounds", "excerpt_lines", "excerpt_line_chars")
_JSON_ESC = {0x2028: "\\u2028", 0x2029: "\\u2029", 0x85: "\\u0085"}      # a `splitlines()` reader must still see one record
_PATH_MASK = chr(0xE000)       # stands for an emitted token while a path run is measured: a path character, never a stop
_PCT = re.compile(r"%[0-9A-Fa-f]{2}")
_ESC = re.compile(r"\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|([\\/\"nrtbf]))")
_ESC_CHAR = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}     # `\n` etc.: a name glued to the letter is a name after a line break
_PAIR = re.compile(r"\\u(d[89ab][0-9a-f]{2})\\u(d[c-f][0-9a-f]{2})", re.I)
_NAME_SPLIT = re.compile(r"[ _.\-+\\]+")


# --- spellings of a path (moved from state_census; behaviour identical for the default arguments) ----------------------

def short83(path: str):
    """The Windows 8.3 spelling of an EXISTING path, or None (no such volume feature, or the path is not there)."""
    if os.name != "nt" or not path:
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 32768)
        return buf.value if 0 < n < 32768 else None
    except Exception:
        return None


def path_variants(path: str, *, short=short83) -> dict:
    """Every spelling of one path worth looking for -> its label: as given and resolved (`raw`), with forward slashes
    (`forward`), with doubled backslashes (`json_escaped`), as a slug (`slug`: every non-alphanumeric character a dash, the way
    Claude names a project folder), and the Windows 8.3 form of each (`short83`). `short` is a seam for the tests (a docker
    image has no 8.3 names)."""
    if not path:
        return {}
    bases = {str(path): "raw"}
    try:
        bases.setdefault(os.path.realpath(path), "raw")
    except OSError:
        pass
    for base in list(bases):
        alias = short(base)
        if alias:
            bases.setdefault(alias, "short83")
    out: dict = {}
    for base, label in bases.items():
        stripped = base.rstrip("\\/") or base
        for text, spelled in ((stripped, label), (stripped.replace("\\", "/"), "short83" if label == "short83" else "forward"),
                              (stripped.replace("\\", "\\\\"), "short83" if label == "short83" else "json_escaped"),
                              (re.sub(r"[^A-Za-z0-9]", "-", stripped), "slug")):
            if len(text) >= MIN_NAME_CHARS:
                out.setdefault(text, spelled)
    return out


def alternation(variants: dict, guard: str = "", lead: str = ""):
    """The regex of one path's spellings. A SLUG spelling that opens with a dash (the slug of an absolute POSIX path: `/root` is
    `-root`) is a fact only as a folder name, i.e. right after a path separator (`projects/-root-x`, `projects\\-root-x`):
    anywhere else the dash is a command-line flag (`--root`, `-root`, `--tmp`), not a home. A raw path (`/root`, `C:\\a-root`)
    keeps its own guard and is found wherever it stands. The rule is the same for every row built here (home, interpreters,
    temp folder)."""
    def join(texts):
        return "|".join(re.escape(v) for v in sorted(texts, key=len, reverse=True))
    flaglike = [v for v, label in variants.items() if label == "slug" and v.startswith("-")]
    plain = [v for v in variants if v not in flaglike]
    branches = []
    if plain:
        branches.append(join(plain))
    if flaglike:
        branches.append(r"(?<=[/\\])(?:" + join(flaglike) + ")")
    return re.compile(lead + "(?:" + "|".join(branches) + ")" + guard, re.I)


class MachineTable(NamedTuple):
    """`rows`: (fact, kind, regex, variants) as the census detector builds them; `host`: the machine name, or "" when it is
    shorter than MIN_HOST_CHARS (a short one matches by chance)."""
    rows: list
    host: str


def machine_table(*, home="", tmp="", pythons=(), host="", guard_all=False, short=short83) -> MachineTable:
    """The replacement rows of this machine: the home folder always guarded (a short home, root's `/root`, must not match inside
    an ordinary word), the interpreters and the temp folder UNguarded unless `guard_all` (the census keeps them so; the redactor
    guards every row)."""
    guard, lead = r"(?![A-Za-z0-9])", r"(?<![A-Za-z0-9])"
    open_guard = (guard, lead) if guard_all else ("", "")
    rows = []
    for fact, path, edge in (("home", home, (guard, lead)),) + tuple(("python", exe, open_guard) for exe in pythons) \
            + (("tmp", tmp, open_guard),):
        variants = path_variants(path, short=short)
        if variants:
            rows.append((fact, "path", alternation(variants, guard=edge[0], lead=edge[1]), variants))
    name = host if len(host or "") >= MIN_HOST_CHARS else ""
    if name:
        rows.append(("host", "host", re.compile(re.escape(name), re.I), {name}))
    return MachineTable(rows, name)


# --- the rules file ----------------------------------------------------------------------------------------------------

class RulesUnreadable(Exception):
    """The redaction rules file is absent, not JSON, of another schema, or lacks a key: packing without it would send
    unredacted data, so the collector refuses (t-962 section 6). `.path` and `.why` name the file and the cause."""

    def __init__(self, path, why: str):
        self.path, self.why = str(path), why
        super().__init__(f"the redaction rules {path} cannot be read ({why}); reinstall the plugin: packing without them "
                         "would send unredacted data")


class PatternUnusable(Exception):
    """A pattern of the project's config `secret_content_patterns` does not compile (F-7): the guard crashes on it at every
    write, so it rarely survives; the archive waits until it is fixed (FR-59 safe default). `.index` is its 1-based number."""

    def __init__(self, index: int, why: str):
        self.index, self.why = index, why
        super().__init__(f"pattern {index} of secret_content_patterns does not compile ({why}); fix or remove pattern {index} "
                         "in qa-factory/config.json secret_content_patterns, then collect again")


def load_rules(path=RULES_FILE) -> dict:
    p = Path(path)
    if not p.is_file():
        raise RulesUnreadable(p, "the file is absent")
    import hooklib
    nothing = object()
    data = hooklib.read_json(p, nothing, errors=Exception)
    if data is nothing:
        raise RulesUnreadable(p, "not valid JSON")
    if not isinstance(data, dict):
        raise RulesUnreadable(p, "not a JSON object")
    if data.get("schema") != 1:
        raise RulesUnreadable(p, f"schema is {data.get('schema')!r}, this reader takes 1")
    missing = [key for key in REQUIRED_KEYS if key not in data]
    missing += [f"limits.{key}" for key in LIMIT_KEYS if key not in (data.get("limits") or {})]
    if missing:
        raise RulesUnreadable(p, f"{missing[0]} missing")
    return data


def rules_sha256(path=RULES_FILE) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rx(pattern: str, flags: int = 0, label: str = ""):
    try:
        return re.compile(pattern, flags)
    except (re.error, TypeError) as exc:
        raise RulesUnreadable(RULES_FILE, f"{label or 'a pattern'} does not compile ({exc})") from exc


# --- hosts and URLs ----------------------------------------------------------------------------------------------------

def host_token(host: str) -> str:
    return "host-" + hashlib.sha256(host.lower().encode()).hexdigest()[:8]


def scrub_url(url: str, *, kept=(), redacted: str = "<redacted>") -> str:
    """`http_client.safe_url` (userinfo, query and fragment dropped), then the host -> `host_token` unless kept. A URL the
    safe form cannot print (a bad port) is `redacted`: the safe side."""
    import http_client
    safe = http_client.safe_url(url)
    if safe in ("(unprintable url)", "(no url)"):
        return redacted
    parts = urllib.parse.urlsplit(safe)
    host = (parts.hostname or "").lower()
    if not host or host in {k.lower() for k in kept}:
        return safe
    port = f":{parts.port}" if parts.port else ""
    return urllib.parse.urlunsplit((parts.scheme, host_token(host) + port, parts.path, "", ""))


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _strings(value)


def known_hosts(config: dict, remotes=(), extra=(), rules: dict | None = None) -> list:
    """Every URL host, scp host and bare `host:port` in any string of `config` and in `remotes`, lower-cased and sorted, plus
    `extra`. The parsing of a candidate is `reachability.host_of` (the package's one host reader); `reachability.declared_hosts`
    keys are a subset of this (a config string it reads is a string of `config`). No git, no network; it reads the rules file
    (unless `rules` is given) and imports `reachability`."""
    import reachability
    rules = rules or load_rules()
    url, scp = _rx(rules["url_regex"], re.I, "url_regex"), _rx(rules["scp_regex"], 0, "scp_regex")
    bare = _rx(rules["bare_host_port_regex"], 0, "bare_host_port_regex")
    found = {str(h).strip().lower() for h in extra if str(h).strip()}
    for text in [*_strings(config), *[str(r) for r in remotes if r]]:
        candidates = [m.group(0).rstrip(".,;:)]}") for m in url.finditer(text)]
        candidates += [m.group(0) for m in scp.finditer(text)]
        candidates += [text.strip()] if bare.match(text.strip()) else []
        for candidate in candidates:
            host = reachability.host_of(candidate)[0].lower()
            if host and not host.startswith("-"):
                found.add(host)
    return sorted(found)


# --- identities and secret values (the impure edge) ------------------------------------------------------------------------

def _windows_display_name() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        buf, size = ctypes.create_unicode_buffer(1024), ctypes.c_ulong(1024)
        return buf.value if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)) else ""
    except Exception:
        return ""


def _text_of(source) -> str:
    try:
        value = source() if callable(source) else source
    except Exception:
        return ""
    return str(value).strip() if value else ""


def _git_reader(project_root):
    import project_inventory

    def run(args):
        code, out = project_inventory._git(Path(project_root or "."), *args)
        return out if code == 0 else ""
    return run


def machine_identities(*, env=None, home=None, run_git=None, hostname=None, display_name=None, project_root=None,
                       getuser=None) -> dict:
    """Who and what this machine is, as lists of names the redactor must not let out: {users, display_names, emails, machine,
    domain, gaps}. Every source is behind a seam; a source that gives nothing is a `gaps` row (the source's name, never a
    value). `getuser` defaults to `getpass.getuser` only when `env` is not injected (an injected environment is a test)."""
    environ = os.environ if env is None else env
    home_dir = os.path.expanduser("~") if home is None else home
    if getuser is None and env is None:
        import getpass
        getuser = getpass.getuser
    git = run_git or _git_reader(project_root)
    host = _text_of(socket.gethostname if hostname is None else hostname)
    sources = {
        "login name": [_text_of(getuser)], "USERNAME or USER": [environ.get("USERNAME"), environ.get("USER"), environ.get("LOGNAME")],
        "home folder name": [Path(home_dir).name if home_dir else ""],
        "git user.name": [_text_of(lambda: git(("config", "user.name")))],
        "git user.email": [_text_of(lambda: git(("config", "user.email")))],
        "display name": [_text_of(_windows_display_name if display_name is None else display_name)],
        "USERDOMAIN": [environ.get("USERDOMAIN")],
        "hostname or COMPUTERNAME": [host, host.split(".")[0], environ.get("COMPUTERNAME")]}
    got = {label: list(dict.fromkeys(str(v).strip() for v in values if v and str(v).strip())) for label, values in sources.items()}
    gaps = [{"kind": "identity_source_absent", "what": f"identity source gave nothing: {label}",
             "why": "nothing from this source is searched for in the archive"} for label, values in got.items() if not values]
    pick = lambda *labels: list(dict.fromkeys(v for label in labels for v in got[label]))     # noqa: E731
    return {"users": pick("login name", "USERNAME or USER", "home folder name"), "display_names": pick("git user.name", "display name"),
            "emails": pick("git user.email"), "machine": pick("hostname or COMPUTERNAME"), "domain": pick("USERDOMAIN"), "gaps": gaps}


def _env_file_values(rel, root, gaps: list) -> dict:
    if not rel:
        return {}
    path = Path(root or ".") / str(rel)
    if not path.is_file():
        gaps.append({"kind": "env_file_absent", "what": "the project's env_file was not found",
                     "why": "its values are not searched for in the archive"})
        return {}
    import env_probe
    try:
        parsed = env_probe.parse_env_file(path)
    except (OSError, ValueError):
        gaps.append({"kind": "env_file_unreadable", "what": "the project's env_file could not be read",
                     "why": "its values are not searched for in the archive"})
        return {}
    return {(k[len("export "):] if k.startswith("export ") else k).strip(): v for k, v in parsed.items()}


def _candidates(*values) -> list:
    out = []
    for value in values:
        if not value:
            continue
        out.append(value)
        cut = value.split(" #", 1)[0].strip().strip('"').strip("'")      # `KEY=abc # note` keeps its note in the value
        if cut and cut != value:
            out.append(cut)
    return list(dict.fromkeys(out))


def secret_values(config: dict, environ, *, root="") -> tuple:
    """(values, gaps): for each name in `environment.secret_keys` (+ `user_key`, `password_key`) the candidates found in
    `environ` AND in `environment.env_file` (read by `env_probe.parse_env_file`, never packed). `export KEY=` is taken as KEY and
    a ` # note` tail is cut as a second candidate. A value is never logged; a name with no value is a gap row naming the key."""
    block = (config or {}).get("environment") or {}
    names = [n for n in [*(block.get("secret_keys") or []), block.get("user_key"), block.get("password_key")] if isinstance(n, str) and n]
    gaps: list = []
    from_file = _env_file_values(block.get("env_file"), root, gaps)
    values = {}
    for name in dict.fromkeys(names):
        found = _candidates((environ or {}).get(name), from_file.get(name))
        if found:
            values[name] = found
        else:
            gaps.append({"kind": "secret_absent", "what": f"secret not found: {name}", "why": "no value in the environment or the env_file"})
    return values, gaps


# --- views of an output: escape and percent decoders ----------------------------------------------------------------------

class _NoFixpoint(Exception):
    pass


def _unescape(text: str, *, controls: bool = True) -> str:
    """`\\uXXXX` (surrogate pairs joined), `\\xXX`, `\\\\`, `\\/`, `\\"` and `\\n \\r \\t \\b \\f` decoded by a regex, never by
    `json.loads` (a text line is not a JSON string: a quote or a bad escape must not stop the view). One pass decodes one level:
    `\\\\n` (an escaped backslash and an n) is `\\n`, not a line break; the chain of views decodes the next level as a view of
    its own. `controls=False` leaves the five letter escapes alone: a Windows path `C:\\work\\new\\temp` is not a string literal."""
    text = _PAIR.sub(lambda m: chr(0x10000 + ((int(m[1], 16) - 0xD800) << 10) + (int(m[2], 16) - 0xDC00)), text)

    def one(m):
        if m[1]:
            return chr(int(m[1], 16))
        if m[2]:
            return chr(int(m[2], 16))
        if m[3] in _ESC_CHAR:
            return _ESC_CHAR[m[3]] if controls else m[0]
        return m[3]
    return _ESC.sub(one, text)


def _unquote(text: str) -> str:
    return urllib.parse.unquote(text) if _PCT.search(text) else text


def _chain(text: str, step, rounds: int) -> list:
    """The successive different values of `step` until it stops changing; no stop within `rounds` -> _NoFixpoint (the caller
    redacts the unit whole)."""
    out, cur = [], text
    for _ in range(rounds):
        nxt = step(cur)
        if nxt == cur:
            return out
        out.append(nxt)
        cur = nxt
    raise _NoFixpoint()


# --- name forms --------------------------------------------------------------------------------------------------------------

def _name_forms(name: str, separators: str, parts: bool, generic: set) -> list:
    """The name, its separator variants (`A_B` -> `A B`, `A.B`, `A-B`, `AB`) and, for a display name, each part of at least
    MIN_NAME_CHARS that is not a generic account."""
    pieces = [p for p in _NAME_SPLIT.split(name) if p]
    forms = [name]
    if len(pieces) > 1:
        forms += [sep.join(pieces) for sep in [*separators, ""]]
        if parts:
            forms += [p for p in pieces if len(p) >= MIN_NAME_CHARS and p.lower() not in generic]
    return [f for f in dict.fromkeys(forms) if len(f) >= MIN_NAME_CHARS]


def _alias_pattern(name: str):
    """The derived Windows 8.3 alias of a name that does not fit 8.3 (longer than 8, or with a space): the first 6 characters
    of the stem with spaces removed and `+,;=[]` as `_`, upper-cased, `~N`; dots removed except the last, whose first three
    characters are the extension. A regex source, or None."""
    if len(name) <= 8 and " " not in name:
        return None
    base = name.replace(" ", "")
    for char in "+,;=[]":
        base = base.replace(char, "_")
    stem, _, ext = base.rpartition(".") if "." in base else (base, "", "")
    head = stem.replace(".", "")[:6].upper()
    if len(head) < 2:
        return None
    return re.escape(head) + r"~\d{1,6}" + (r"(?:\." + re.escape(ext[:3].upper()) + ")?" if ext else "")


# --- the compiled redactor ---------------------------------------------------------------------------------------------------

class Result(NamedTuple):
    status: str                       # copied | empty | skipped | too_large
    kind: str                         # json | jsonl | text
    data: bytes | None
    reason: str
    redactions: dict                  # exactly the manifest keys {path, user, secret, host, email}
    jsonl_text_lines: int = 0         # JSONL lines that were not JSON and went through the text algorithm (F-3)
    json_as_text: int = 0             # JSON files that took the text algorithm (inf/nan, a lone surrogate)
    excerpt: str | None = None        # too_large: the first and last lines through the editor


class NotJson(ValueError):
    pass


class TooDeep(ValueError):
    pass


class JsonAsText(ValueError):
    """Valid JSON that cannot be re-dumped safely (inf/nan, a lone surrogate, an integer past the parser's limit)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _Pairs(list):
    """A JSON object as its (key, value) pairs in order, duplicates kept (the hook of `json.loads`)."""


def _gap(kind: str, what: str, why: str) -> dict:
    return {"kind": kind, "what": what, "why": why}


def _build_detectors(rules: dict, config_patterns) -> SimpleNamespace:
    names = "|".join(re.escape(h) for h in rules["header_names"])
    detectors, pem, assigned = [], None, None
    for row in rules["secret_patterns"]:
        unit, pattern = row.get("unit"), row["regex"].replace("{header_names}", names)
        if unit == "assigned_value":
            assigned = _rx(pattern, 0, row["id"])
        elif unit in ("line", "pem_block"):
            detectors.append((row["id"], _rx(pattern, 0, row["id"])))
            pem = detectors[-1][1] if unit == "pem_block" else pem
        else:
            raise RulesUnreadable(RULES_FILE, f"secret_patterns {row.get('id')}: unknown unit {unit!r}")
    if assigned is None or pem is None:
        raise RulesUnreadable(RULES_FILE, "secret_patterns lacks the pem or the assigned_value row")
    for number, pattern in enumerate(config_patterns, 1):
        try:
            re.compile(pattern)
        except (re.error, TypeError) as exc:
            raise PatternUnusable(number, str(exc)) from exc
    import guard_secrets
    merged = guard_secrets._patterns({"secret_content_patterns": list(config_patterns)}, "secret_content_patterns",
                                     list(guard_secrets.DEFAULT_SECRET_CONTENT_PATTERNS))
    detectors += [(f"guard:{i}", re.compile(p)) for i, p in enumerate(merged)]
    return SimpleNamespace(detectors=detectors, pem=pem, assigned=assigned)


def _build_key_matcher(rules: dict):
    names = _rx(rules["secret_key_names"], 0, "secret_key_names")
    headers = re.compile("|".join(re.escape(h) for h in rules["header_names"]), re.I)
    return lambda key: bool(names.fullmatch(key) or headers.fullmatch(key))


def _build_paths(rules: dict, paths: tuple, gaps: list, short) -> SimpleNamespace:
    """project, plugin, python, tmp, home (every spelling) -> their tokens; ONE alternation, longest spelling first, every
    spelling guarded: a path inside a path takes the longer one's token."""
    project, plugin, pythons, home, tmp = paths
    tok = rules["tokens"]
    table = machine_table(home=home, tmp=tmp, pythons=pythons, guard_all=True, short=short)
    wanted = {"project": project, "plugin": plugin, "python": pythons, "tmp": tmp, "home": home}
    lookup: dict = {}
    for fact, path in (("project", project), ("plugin", plugin)):
        for text in path_variants(path, short=short):
            lookup.setdefault(text.lower(), tok[fact])
    for fact, _kind, _rx_, variants in table.rows:         # home, python, tmp: the first spelling kept wins
        for text in variants:
            lookup.setdefault(text.lower(), tok[fact])
    for fact, path in wanted.items():
        for one in (path if isinstance(path, (list, tuple)) else [path]):
            if one and not path_variants(one, short=short):
                gaps.append(_gap("path_too_short", f"path too short: {fact}, {len(one)} chars", "a path of fewer than 3 characters is not searched"))
    if not lookup:
        return SimpleNamespace(rx=None, lookup={})
    body = "|".join(re.escape(t) for t in sorted(lookup, key=len, reverse=True))
    return SimpleNamespace(rx=re.compile(r"(?<![A-Za-z0-9])(?:" + body + r")(?![A-Za-z0-9])", re.I), lookup=lookup)


def _take_identity(rules: dict, group: tuple, name: str, literals: dict, aliases: list, gaps: list) -> None:
    """One non-empty name of one identity group: a gap row (too short, a generic account) or its forms and 8.3 alias."""
    key, label, floor, token, category, parts = group
    generic = {g.lower() for g in rules["generic_accounts"]}
    if len(name) < floor:
        gaps.append(_gap("identity_too_short", f"identity too short: {label}, {len(name)} chars", f"below {floor} characters: not searched in text"))
    elif name.lower() in generic and key != "emails":
        gaps.append(_gap("identity_generic", f"identity is a generic account name: {label}, {len(name)} chars", "not searched as a word"))
    else:
        for form in _name_forms(name, rules["name_separators"], parts, generic) if key != "emails" else [name]:
            literals.setdefault(form.lower(), (rules["tokens"][token], category))
        alias = _alias_pattern(name) if key in ("users", "display_names") else None
        aliases += [alias] if alias else []


def _build_identities(rules: dict, identities: dict, gaps: list) -> SimpleNamespace:
    literals: dict = {}
    aliases: list = []
    groups = (("users", "user", MIN_NAME_CHARS, "user", "user", False), ("display_names", "display name", MIN_NAME_CHARS, "user", "user", True),
              ("domain", "domain", MIN_NAME_CHARS, "domain", "user", False), ("machine", "machine", MIN_HOST_CHARS, "machine", "host", False),
              ("emails", "email", MIN_NAME_CHARS, "email", "email", False))
    for group in groups:
        for name in [str(raw).strip() for raw in identities.get(group[0]) or []]:
            if name:
                _take_identity(rules, group, name, literals, aliases, gaps)
    sources = [re.escape(t) for t in sorted(literals, key=len, reverse=True)] + list(dict.fromkeys(aliases))
    rx = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(sources) + r")(?![A-Za-z0-9])", re.I) if sources else None
    return SimpleNamespace(rx=rx, lookup=literals, default=(rules["tokens"]["user"], "user"))


def _build_hosts(rules: dict, hosts, gaps: list):
    kept = {h.lower() for h in rules["hosts_kept"]}
    wanted = sorted({str(h).strip().lower() for h in hosts if str(h).strip()} - kept, key=len, reverse=True)
    for host in [h for h in wanted if len(h) < MIN_NAME_CHARS]:
        gaps.append(_gap("host_too_short", f"known host too short: {len(host)} chars", "not searched in text"))
    wanted = [h for h in wanted if len(h) >= MIN_NAME_CHARS]
    if not wanted:
        return None
    return re.compile(r"(?<![A-Za-z0-9.-])(?:" + "|".join(re.escape(h) for h in wanted) + r")(?![A-Za-z0-9-]|\.[A-Za-z0-9])", re.I)


def _take_secret(rules: dict, name: str, one, named: dict, gaps: list) -> None:
    """One candidate value of a named secret, split at its line breaks: a gap row (empty, below the floor) or a searched piece."""
    floor = rules["limits"]["min_secret_value_chars"]
    pieces = [p.rstrip("\r") for p in str(one).split("\n")]
    if not any(pieces):
        gaps.append(_gap("secret_empty", f"secret is empty: {name}", "nothing to search for"))
    for piece in [p for p in pieces if p]:
        if len(piece) < floor:
            gaps.append(_gap("secret_below_limit", f"secret below {floor}: {name}, {len(piece)} chars", "a value this short matches by chance: not searched"))
        else:
            named.setdefault(piece, rules["tokens"]["secret_named"].replace("{name}", name))


def _build_secrets(rules: dict, values, gaps: list) -> SimpleNamespace:
    named: dict = {}
    for name, value in (values or {}).items():
        for one in [value] if isinstance(value, str) else list(value):
            _take_secret(rules, name, one, named, gaps)
    rx = re.compile("|".join(re.escape(v) for v in sorted(named, key=len, reverse=True))) if named else None
    return SimpleNamespace(rx=rx, token=named, names=sorted({t for t in named.values()}))


def compile_redactor(rules: dict, *, project_root="", plugin_root="", pythons=(), home="", tmp="", identities: dict, hosts=(),
                     secret_values=None, config_patterns=(), short=short83, source_gaps=()):
    """Compile the exit filter of one machine. `identities` is `machine_identities()`'s shape; `hosts` is `known_hosts()`'s;
    `secret_values` is `{NAME: value or [values]}`; `config_patterns` is the project's `secret_content_patterns` (an
    uncompilable one raises PatternUnusable). Every name or value it will not search for is a row of `.gaps`."""
    gaps = [*source_gaps, *(identities.get("gaps") or [])]
    t = _build_detectors(rules, config_patterns)
    t.rules, t.tok, t.lim = rules, dict(rules["tokens"]), rules["limits"]
    t.key_secret = _build_key_matcher(rules)
    t.paths = _build_paths(rules, (project_root, plugin_root, tuple(pythons), home, tmp), gaps, short)
    t.ident = _build_identities(rules, identities, gaps)
    t.host_rx = _build_hosts(rules, hosts, gaps)
    t.secrets = _build_secrets(rules, secret_values, gaps)
    t.email, t.url = _rx(rules["email_regex"], re.I, "email_regex"), _rx(rules["url_regex"], re.I, "url_regex")
    t.scp, t.cred = _rx(rules["scp_regex"], 0, "scp_regex"), _rx(rules["credential_url_regex"], re.I, "credential_url_regex")
    t.ipv4 = _rx(rules["ipv4_regex"], 0, "ipv4_regex")
    t.nets = [ipaddress.ip_network(n) for n in rules["private_ip_ranges"]]
    t.starts = [_rx(p, re.I, "residual_path_starts") for p in rules["residual_path_starts"]]
    t.stop = set(rules["path_stop_chars"])
    t.roots = {r.lower() for r in rules["home_roots"]}
    t.kept = {h.lower() for h in rules["hosts_kept"]}
    fixed = [t.tok[k] for k in ("project", "plugin", "python", "home", "tmp", "user", "machine", "domain", "abs", "secret", "email", "redacted")]
    parts = [re.escape(x) for x in fixed] + ["host-[0-9a-f]{8}"]
    if t.secrets.names:
        parts.append("|".join(re.escape(n) for n in t.secrets.names))
    t.token_rx = re.compile("|".join(parts))
    return Redactor(t, gaps)


class Redactor:
    """Immutable after compile; every method pure and deterministic. `text` is one unit; `lines`, `json_text`, `jsonl_text`
    and `file` are the algorithms over a whole text; `residue` is the post-check's finder over every view of a text."""

    def __init__(self, t: SimpleNamespace, gaps: list):
        self._t, self.gaps = t, gaps
        self._secret, self._redacted, self._abs = t.tok["secret"], t.tok["redacted"], t.tok["abs"]

    # -- the unit pipeline (section 5) --------------------------------------------------------------------------------------

    def _detector_hit(self, s: str):
        for _id, rx in self._t.detectors:
            if rx.search(s):
                return rx
        return None

    def _assigned(self, s: str, c: Counter) -> str:
        def one(m):
            c["secret"] += 1
            return m.group(0)[: m.start(2) - m.start(0)] + self._secret
        return self._t.assigned.sub(one, s)

    def _literals(self, s: str, c: Counter) -> str:
        rx = self._t.secrets.rx
        def one(m):
            c["secret"] += 1
            return self._t.secrets.token[m.group(0)]
        return rx.sub(one, s) if rx else s

    def _paths(self, s: str, c: Counter) -> str:
        paths = self._t.paths
        def one(m):
            c["path"] += 1
            return paths.lookup.get(m.group(0).lower(), self._abs)
        return paths.rx.sub(one, s) if paths.rx else s

    def _urls(self, s: str, c: Counter) -> str:
        def one(m):
            raw = m.group(0)
            core = raw.rstrip(".,;:)]}")
            if core.lower().startswith("file:"):
                return raw                                  # a path: the residual step reads it
            c["host"] += 1
            return scrub_url(core, kept=self._t.kept, redacted=self._redacted) + raw[len(core):]
        return self._t.url.sub(one, s)

    def _scp(self, s: str, c: Counter) -> str:
        def one(m):
            if m.group(1).lower() in self._t.kept:
                return m.group(0)
            c["host"] += 1
            return host_token(m.group(1)) + ":" + m.group(2)
        return self._t.scp.sub(one, s)

    def _outside(self, s: str, fn) -> str:
        """`fn` over the parts of `s` that are not an emitted token (a name never re-reads `<user>` or a hashed host)."""
        if "<" not in s and "host-" not in s:
            return fn(s)
        out, pos = [], 0
        for m in self._t.token_rx.finditer(s):
            out += [fn(s[pos:m.start()]), m.group(0)]
            pos = m.end()
        return "".join(out + [fn(s[pos:])])

    def _emails(self, s: str, c: Counter) -> str:
        def one(m):
            c["email"] += 1
            return self._t.tok["email"]
        return self._outside(s, lambda part: self._t.email.sub(one, part))

    def _private_ip(self, m, c: Counter) -> str:
        try:
            addr = ipaddress.ip_address(m.group(0))
        except ValueError:
            return m.group(0)
        if any(addr in net for net in self._t.nets):
            c["host"] += 1
            return host_token(m.group(0))
        return m.group(0)

    def _identities(self, s: str, c: Counter) -> str:
        t = self._t
        def host(m):
            c["host"] += 1
            return host_token(m.group(0))
        def name(m):
            token, category = t.ident.lookup.get(m.group(0).lower(), t.ident.default)
            c[category] += 1
            return token
        if t.host_rx:
            s = self._outside(s, lambda part: t.host_rx.sub(host, part))
        s = self._outside(s, lambda part: t.ipv4.sub(lambda m: self._private_ip(m, c), part))
        return self._outside(s, lambda part: t.ident.rx.sub(name, part)) if t.ident.rx else s

    def _masked_path_view(self, s: str) -> str:
        return self._t.token_rx.sub(lambda m: _PATH_MASK * len(m.group(0)), s)

    def _run_end(self, masked: str, start: int) -> int:
        i, n = start, len(masked)
        while i < n and masked[i] not in self._t.stop:
            if masked[i].isspace():
                nxt = masked[i + 1:].split(None, 1)[0] if masked[i + 1:i + 2].strip() else ""
                if masked[i] != " " or not ("\\" in nxt or "/" in nxt):
                    break
            i += 1
        return i

    def _residual_spans(self, s: str) -> list:
        masked = self._masked_path_view(s)
        after_token = {m.end() for m in self._t.token_rx.finditer(s)}       # by position: the input's own U+E000 is no token
        starts = sorted({m.start() for rx in self._t.starts for m in rx.finditer(masked)})
        spans, covered = [], -1
        for start in starts:
            if start < covered or start in after_token:
                continue                       # inside a run already taken, or the run grows back into an emitted token
            covered = self._run_end(masked, start)
            spans.append((start, covered))
        return spans

    def _abs_reading(self, run: str, hosted: bool) -> tuple:
        """(only, last) for one reading of a path run: whether it names a root alone, and its last segment."""
        segs = [x for x in re.split(r"[\\/]+", run) if x]
        if re.match(r"(?i)file:", run):
            segs = segs[1:]
        if not segs:
            return True, ""
        last, prev = segs[-1], segs[-2].lower() if len(segs) > 1 else ""
        only = bool(re.fullmatch(r"[A-Za-z]:", last)) or last.lower() in self._t.roots or prev in self._t.roots or (hosted and len(segs) <= 2)
        return only, last

    def _abs_text(self, run: str) -> str:
        """`<abs>` or `<abs>/<last segment>`. Step 9 cuts the run at its separators and the post-check reads only the output, so
        a segment that is an escape of its own (an escaped backslash or letter) would leave with its escape view gone (t-999
        M-3). The run is read twice, as written and with its hex and quote escapes decoded (the five letter escapes stay:
        `\\new`, `\\temp` are folders); a root alone in either reading, or two different last segments, leave `<abs>` alone."""
        hosted = bool(re.match(r"(?i)file:/{2}[^/]", run) or run.startswith("\\\\"))      # a server comes first
        decoded = _unescape(run, controls=False)
        readings = [self._abs_reading(run, hosted)] + ([self._abs_reading(decoded, hosted)] if decoded != run else [])
        if any(only for only, _last in readings) or len({last for _only, last in readings}) > 1:
            return self._abs
        return self._abs + "/" + readings[0][1]

    def _residual(self, s: str, c: Counter) -> str:
        out, pos = [], 0
        for start, end in self._residual_spans(s):
            out += [s[pos:start], self._abs_text(s[start:end])]
            c["path"] += 1
            pos = end
        return "".join(out) + s[pos:]

    def _pipeline(self, s: str, c: Counter, key: bool):
        if not key:
            if self._detector_hit(s):
                return None
            s = self._assigned(s, c)
        s = self._literals(s, c)
        s = self._paths(s, c)
        s = self._urls(s, c)
        s = self._scp(s, c)
        s = self._emails(s, c)
        s = self._identities(s, c)
        return self._residual(s, c)

    # -- the post-check (R1) ------------------------------------------------------------------------------------------------

    def _views(self, text: str) -> list:
        """raw, the escape-decoded chain, the percent-decoded chain, and each chain over the other; no fixpoint -> _NoFixpoint."""
        if "\\" not in text and "%" not in text:
            return [("raw", text)]
        lim = self._t.lim
        esc = lambda s: _chain(s, _unescape, lim["unescape_rounds"])         # noqa: E731
        pct = lambda s: _chain(s, _unquote, lim["percent_rounds"])           # noqa: E731
        views = [("raw", text)]
        views += [("escape", v) for v in esc(text)]
        for base in [text] + [v for _l, v in views[1:]]:
            views += [("percent", v) for v in pct(base)]
        views += [("percent+escape", w) for _l, v in list(views) if _l == "percent" for w in esc(v)]
        seen, out = set(), []
        for label, view in views:
            if view not in seen:
                seen.add(view)
                out.append((label, view))
        return out

    def _mask(self, view: str, tokens=None) -> str:
        rx = self._t.token_rx
        if tokens:
            rx = re.compile(rx.pattern + "|" + "|".join(re.escape(x) for x in tokens))
        return rx.sub(lambda m: " " * len(m.group(0)), view)

    def _scan_view(self, label: str, view: str, masked: str, key: bool) -> list:
        t = self._t
        checks = [] if key else [(f"detector:{i}", "secret", rx) for i, rx in t.detectors]
        checks += [("secret-value", "secret", t.secrets.rx), ("path-literal", "path", t.paths.rx), ("email", "email", t.email),
                   ("known-host", "host", t.host_rx), ("credential-url", "secret", t.cred), ("scp-remote", "host", t.scp)]
        found = []
        for finder, category, rx in checks:
            if rx is not None and rx.search(masked):
                found.append({"finder": finder, "category": category, "view": label})
        if t.ident.rx:
            m = t.ident.rx.search(masked)
            if m:
                found.append({"finder": "identity", "category": t.ident.lookup.get(m.group(0).lower(), t.ident.default)[1], "view": label})
        if any(self._private_ip(m, Counter()) != m.group(0) for m in t.ipv4.finditer(masked)):
            found.append({"finder": "private-ip", "category": "host", "view": label})
        if self._residual_spans(view):
            found.append({"finder": "residual-path", "category": "path", "view": label})
        return found

    def residue(self, text: str, tokens=None, *, _key: bool = False, _first: bool = False) -> list:
        """The post-check's finders over every view of `text` (emitted tokens masked): a list of {finder, category, view},
        empty when nothing leaks. `tokens` names extra token strings to mask."""
        try:
            views = self._views(text)
        except _NoFixpoint:
            return [{"finder": "views", "category": "secret", "view": "no fixpoint"}]
        found = []
        for label, view in views:
            found += self._scan_view(label, view, self._mask(view, tokens), _key)
            if found and _first:
                break
        return found

    def _leaves_of(self, body: str):
        """The (unit, is_key) pairs of ONE JSON text, parsed by the writer's own `_parse`: every string value, and every key (a
        secret-named key is read as `_key` writes it, with `key=True`). None when the writer would not parse it either."""
        try:
            tree = self._parse(body)
        except (NotJson, TooDeep, JsonAsText):
            return None
        out, stack = [], [(tree, False)]
        while stack:
            node, is_key = stack.pop()
            if is_key or isinstance(node, str):
                out.append((node, self._t.key_secret(node) if is_key else False))
            elif isinstance(node, _Pairs):
                stack += [pair for key, value in reversed(node) for pair in ((value, False), (key, True))]
            elif isinstance(node, list):
                stack += [(value, False) for value in reversed(node)]
        return out

    def _document_units(self, text: str, kind: str):
        """The units the writer works on, as it works on them: a JSON document by its string leaves (a text that does not parse is
        read by line), JSONL by line (a line that is not JSON by itself is a unit), anything else by line."""
        if kind == "json":
            leaves = self._leaves_of(text[1:] if text[:1] == chr(0xFEFF) else text)       # the BOM `json_text` writes back is not data
            if leaves is not None:
                yield from leaves
                return
        for line in text.split("\n"):
            core = line[:-1] if line.endswith("\r") else line
            parsable = kind == "jsonl" and core.strip() and len(core.encode("utf-8", "replace")) <= self._t.lim["parse_max_bytes"]
            leaves = self._leaves_of(core) if parsable else None
            yield from leaves if leaves is not None else [(core, False)]

    def residue_document(self, text: str, kind: str, tokens=None, *, _first: bool = False) -> list:
        """`residue` over a WHOLE file of the given kind ("json", "jsonl"; anything else is text): the same finders, the same
        {finder, category, view} rows, read unit by unit. The escaped text of a whole JSON file is not a unit the filter ever
        wrote (`\\.env\\.` of a pattern list reads as a UNC path there); a string leaf is."""
        found = []
        for unit, key in self._document_units(text, kind):
            found += self.residue(unit, tokens, _key=key, _first=_first)
            if found and _first:
                break
        return found

    # -- the public algorithms ----------------------------------------------------------------------------------------------

    def text(self, s: str, *, _key: bool = False):
        """ONE unit (a JSON string value, a key, a manifest string, one line) -> (redacted, Counter)."""
        c = Counter()
        if not s:
            return s, c
        out = self._pipeline(s, c, _key)
        if out is None:
            return self._secret, Counter(secret=1)
        found = self.residue(out, _key=_key, _first=True)
        if found:
            return self._redacted, Counter({found[0]["category"]: 1})
        return out, c

    def _line(self, core: str, in_pem: bool, c: Counter):
        closes = "-----END" in core
        if in_pem or self._t.pem.search(core):
            c["secret"] += 1
            return self._secret, not closes
        new, cc = self.text(core)
        c.update(cc)
        return new, False

    def lines(self, text: str):
        """The text algorithm: split on "\\n" only (a "\\r", U+2028 inside a line is data); a PEM block is replaced line by line
        up to its `-----END` line (or the end of the text)."""
        c, out, in_pem = Counter(), [], False
        for line in text.split("\n"):
            core = line[:-1] if line.endswith("\r") else line
            new, in_pem = self._line(core, in_pem, c)
            out.append(new + line[len(core):])
        return "\n".join(out), c

    def _parse(self, body: str):
        try:
            tree = json.loads(body, object_pairs_hook=_Pairs)
        except json.JSONDecodeError as exc:
            raise NotJson(str(exc)) from exc
        except RecursionError as exc:
            raise TooDeep("nesting too deep for the parser") from exc
        except ValueError as exc:
            raise JsonAsText(f"the parser refused a value ({exc.__class__.__name__})") from exc
        self._check(tree)
        return tree

    def _check(self, tree) -> None:
        """Depth (a top-level scalar is 0, an empty container is its own level) and the values that cannot be re-dumped."""
        limit, stack = self._t.lim["max_json_depth"], [(tree, 0)]
        while stack:
            node, level = stack.pop()
            if isinstance(node, _Pairs):
                kids = [x for pair in node for x in pair]
            elif isinstance(node, list):
                kids = node
            else:
                self._check_scalar(node)
                continue
            if level + 1 > limit:
                raise TooDeep(f"nesting deeper than {limit}")
            stack += [(k, level + 1) for k in kids]

    @staticmethod
    def _check_scalar(node) -> None:
        if isinstance(node, float) and node != node or isinstance(node, float) and node in (float("inf"), float("-inf")):
            raise JsonAsText("a number that is not finite (inf or nan)")
        if isinstance(node, str):
            try:
                node.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise JsonAsText("a lone surrogate in a string") from exc

    def _key(self, key: str, c: Counter):
        if self._t.key_secret(key):
            new, cc = self.text(key, _key=True)
            c.update(cc)
            return new, True
        if self._detector_hit(key):
            c["secret"] += 1
            return self._secret, True
        new, cc = self.text(key)
        c.update(cc)
        return new, False

    @staticmethod
    def _unique(keys: list) -> list:
        used, out = set(), []
        for key in keys:
            cand, n = key, 1
            while cand in used:
                n += 1
                cand = f"{key} #{n}"
            used.add(cand)
            out.append(cand)
        return out

    def _walk(self, node, c: Counter, secret: bool):
        if isinstance(node, _Pairs):
            subs = [self._key(k, c) for k, _v in node]
            keys = self._unique([k for k, _s in subs])
            return dict(zip(keys, [self._walk(v, c, secret or sub) for (_k, v), (_n, sub) in zip(node, subs)]))
        if isinstance(node, list):
            return [self._walk(x, c, secret) for x in node]
        if isinstance(node, str):
            if secret and node:
                c["secret"] += 1
                return self._secret
            new, cc = self.text(node)
            c.update(cc)
            return new
        if secret and not isinstance(node, bool) and node is not None:
            c["secret"] += 1
            return self._secret
        return node

    def json_text(self, text: str, *, compact: bool = False):
        """The JSON algorithm: parse, walk (keys and string values), dump. Raises NotJson, TooDeep or JsonAsText."""
        bom = "﻿" if text.startswith("﻿") else ""
        body = text[len(bom):]
        tree, c = self._parse(body), Counter()
        out = json.dumps(self._walk(tree, c, False), ensure_ascii=False, indent=None if compact or "\n" not in body else 2)
        return bom + out.translate(_JSON_ESC) + ("\n" if body.endswith("\n") else ""), c

    def _json_line(self, core: str):
        if len(core.encode("utf-8", "replace")) > self._t.lim["parse_max_bytes"]:
            raise NotJson("a line over the parse limit")
        return self.json_text(core, compact=True)

    def jsonl_text(self, text: str):
        """Line by line on "\\n"; a line that is not JSON goes through the text algorithm and is counted `jsonl_text_lines`."""
        c, out = Counter(), []
        for line in text.split("\n"):
            core = line[:-1] if line.endswith("\r") else line
            if not core.strip():
                out.append(line)
                continue
            try:
                new, cc = self._json_line(core)
            except (NotJson, TooDeep, JsonAsText):
                new, cc = self.lines(core)
                c["jsonl_text_lines"] += 1
            c.update(cc)
            out.append(new + line[len(core):])
        return "\n".join(out), c

    def member_name(self, rel: str) -> str:
        """An archive member name: the unit pipeline, then every token as `_name_` (a `<` or a `:` is not a Windows file name)."""
        out = self.text(rel)[0]
        out = re.sub(r"<([a-z]+)(?::([^>]*))?>", lambda m: "_" + m.group(1) + ("-" + m.group(2) if m.group(2) else "") + "_", out)
        return re.sub(r'[<>:"|?*]', "_", out)

    def _excerpt(self, text: str) -> tuple:
        lim, rows = self._t.lim, text.split("\n")
        n = lim["excerpt_lines"]
        picked = rows if len(rows) <= 2 * n else rows[:n] + [f"[{len(rows) - 2 * n} lines omitted]"] + rows[-n:]
        cap = lim["excerpt_line_chars"]
        safe = [r if len(r) <= cap else f"[line of {len(r)} chars omitted]" for r in picked]
        return self.lines("\n".join(safe))

    def _zero(self) -> dict:
        return {k: 0 for k in CATEGORIES}

    def _kind(self, name: str) -> str:
        low = str(name).lower()
        if any(low.endswith(s) for s in self._t.rules["jsonl_suffixes"]):
            return "jsonl"
        return "json" if any(low.endswith(s) for s in self._t.rules["json_suffixes"]) else "text"

    def _done(self, kind: str, out: str, c: Counter, reason: str = "") -> Result:
        try:
            data = out.encode("utf-8")
        except UnicodeEncodeError:
            return Result("skipped", kind, None, "unencodable", self._zero())
        return Result("copied", kind, data, reason, {k: int(c.get(k, 0)) for k in CATEGORIES},
                      int(c.get("jsonl_text_lines", 0)), int(c.get("json_as_text", 0)))

    def file(self, name: str, data: bytes) -> Result:
        """The bytes of one file -> Result. Order: empty, binary (a NUL, UTF-16 included), not UTF-8, over the cap, then the
        algorithm of the suffix. Nothing here raises."""
        kind, lim = self._kind(name), self._t.lim
        if not data:
            return Result("empty", kind, b"", "", self._zero())
        if b"\x00" in data:
            return Result("skipped", kind, None, "binary", self._zero())
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return Result("skipped", kind, None, "not_utf8", self._zero())
        cap = {"json": lim["parse_max_bytes"], "text": lim["text_max_bytes"]}.get(kind)
        if cap is not None and len(data) > cap:
            excerpt, c = self._excerpt(text)
            return Result("too_large", kind, None, f"over {cap} bytes", {k: int(c.get(k, 0)) for k in CATEGORIES}, excerpt=excerpt)
        try:
            if kind == "json":
                out, c = self.json_text(text)
            else:
                out, c = self.jsonl_text(text) if kind == "jsonl" else self.lines(text)
        except NotJson:
            return Result("skipped", kind, None, "json_unparsable", self._zero())
        except TooDeep:
            return Result("skipped", kind, None, "too_deep", self._zero())
        except JsonAsText as exc:
            out, c = self.lines(text)
            c["json_as_text"] += 1
            return self._done(kind, out, c, f"json_as_text: {exc.reason}")
        return self._done(kind, out, c)


# --- what this machine's table looks like, without a value --------------------------------------------------------------------

def table_summary(table: MachineTable) -> dict:
    """Counts only: which facts have rows and how many spellings, whether the machine name is searched. No value."""
    return {"rows": [{"fact": fact, "kind": kind, "spellings": len(variants)} for fact, kind, _rx_, variants in table.rows],
            "host_searched": bool(table.host)}


def main(argv=None) -> int:
    try:
        load_rules()
        rules_hash = rules_sha256()
    except RulesUnreadable as exc:
        print(f"COLLECT: {exc}", file=sys.stderr)
        return 1
    table = machine_table(home=os.path.expanduser("~"), tmp=tempfile.gettempdir(), pythons=[sys.executable], host=socket.gethostname(),
                          guard_all=True)
    print(json.dumps({"redaction_rules_sha256": rules_hash, "table": table_summary(table)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
