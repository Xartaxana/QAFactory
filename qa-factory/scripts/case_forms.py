"""The shape of a case id is a fact about the PROJECT, so it is data (`config.case_id_form`).

The contract used to know case ids only as `TC-\\d+`, while TP1-13877's strategy writes
`TP1-13877_TC_001`: `contract.case_ids("TP1-13877_TC_001")` came back empty, so every
manifest binding was "missing" for all cases and the automator spent about 35 calls reading factory
code before it halted (B-013, FR-13). The fix is not a second regex, it is a template the project
owns and one place that turns templates into matchers.

A template is text with two placeholders and literal characters:
  `{ticket}`  any ticket key (`TP1-13877`), at most once
  `{nnn}`     the case number, exactly once
e.g. `{ticket}_TC_{nnn}`. The config value is one template or a list of them. The default form
`TC-{nnn}` is ALWAYS recognised as well, after the configured ones: 0.7.x records, fixtures and
mixed stores keep their meaning, and a project that never sets the key sees exactly what it saw
before (the default compiles to the same `TC-\\d+`, with no boundary guards).

Stdlib plus `adapter_forms` (itself stdlib only), and it reads no config: the caller hands over the
config dict (an empty dict, None or anything that is not a dict means "no key"), so this file is
the one place that can be tested without a project and cannot fail because of one. Nothing here
raises on any input: a form that cannot be understood is reported by `problems()` and ignored.

`{ticket}` is the ticket key shape of the PROJECT's tracker (`adapter_forms.key_form(cfg)`, the cfg
the caller already passes): `TP1-13877` on Jira, `123` on GitHub issues. When the forms table
cannot be read, the templates that carry `{ticket}` cannot be compiled: they are ignored, `problems()`
names the file, and the default `TC-{nnn}` (and any form without a ticket) still applies. The
boundary rules of the key come from this file's guards below, not from the key pattern.
"""
import re
from functools import lru_cache

import adapter_forms as AF

CONFIG_KEY = "case_id_form"
DEFAULT_FORM = "TC-{nnn}"
EXAMPLE_TEMPLATE = "{ticket}_TC_{nnn}"

_NNN = r"\d+"
# A configured form must not start or end inside a longer alphanumeric run: `XTP1-13877_TC_001x`
# names no case. The default form keeps no guards so that it stays the legacy `TC-\d+` exactly
# (`ATC-12` has always read as TC-12).
_BEFORE = r"(?<![A-Za-z0-9])"
_AFTER = r"(?![A-Za-z0-9])"
_ALNUM = re.compile(r"[A-Za-z0-9]")
_TOKEN = re.compile(r"\{[^{}]*\}")
# Characters a template literal may not carry: the area/compound separator, the instance
# separators (`::`, `--`, `#`), scope lists, parametrize brackets, glob and shell characters and the
# filesystem's own. A case id travels through every one of those positions, so a literal that
# contains one would be cut in half by the first reader that splits on it. The backslash is built
# from chr(92) (FR-29).
_RESERVED = frozenset("/:#,[]*?\"<>|" + chr(92))
_GRAMMAR = ("write it as literal text around {nnn} (once) and, if needed, {ticket} (once), "
            "for example " + EXAMPLE_TEMPLATE)


def _analyse(template) -> tuple:
    """(parts, reasons): the compiled pieces of one template and every reason it is invalid.

    `parts` is a list of ("lit", text) / ("ticket",) / ("nnn",), and None when there is any reason."""
    if not isinstance(template, str):
        return None, [f"{template!r} is not text - {_GRAMMAR}"]
    if not template.strip():
        return None, [f"an empty form names nothing - {_GRAMMAR}"]
    parts, reasons, position = [], [], 0
    counts = {"ticket": 0, "nnn": 0}

    def literal(chunk: str) -> None:
        if not chunk:
            return
        if "{" in chunk or "}" in chunk:
            reasons.append(f"has an unmatched brace in {chunk!r} - braces only wrap {{ticket}} or {{nnn}}")
        if any(c.isspace() for c in chunk):
            reasons.append(f"has whitespace in {chunk!r} - a case id is one word")
        bad = sorted({c for c in chunk if c in _RESERVED})
        if bad:
            reasons.append(f"has {' '.join(repr(c) for c in bad)} in {chunk!r} - those characters separate "
                           "areas, instances, scopes or path parts, so an id cannot carry them")
        if "--" in chunk:
            reasons.append(f"has '--' in {chunk!r} - '--' separates an instance from its case")
        parts.append(("lit", chunk))

    for match in _TOKEN.finditer(template):
        literal(template[position:match.start()])
        token = match.group(0)
        if token == "{ticket}":
            counts["ticket"] += 1
            parts.append(("ticket",))
        elif token == "{nnn}":
            counts["nnn"] += 1
            parts.append(("nnn",))
        else:
            reasons.append(f"{token} is not a placeholder - only {{ticket}} and {{nnn}} are; "
                           "anything else must be literal text")
        position = match.end()
    literal(template[position:])
    if counts["nnn"] != 1:
        reasons.append(f"has {counts['nnn']} of {{nnn}} - a form needs the case number exactly once")
    if counts["ticket"] > 1:
        reasons.append("has {ticket} more than once - a form names one ticket")
    if any(a[0] == "ticket" and b[0] == "nnn" for a, b in zip(parts, parts[1:])):
        # A ticket key ends in digits, so `{ticket}{nnn}` cannot say where the key stops and the
        # number starts (an example would read TP1-13877001), and the matcher backtracks
        # quadratically over a long digit run.
        reasons.append("has {ticket} directly followed by {nnn} - the digits of the key and the case "
                       "number would run together; put literal text between them, e.g. {ticket}_TC_{nnn}")
    if template.startswith("-") or template.endswith("-"):
        reasons.append("starts or ends with '-' - it would glue onto the '--' that separates an instance "
                       "from its case (TC1---x would read as TC1-); end the literal text with a letter or digit")
    if not any(c.isalnum() for part in parts if part[0] == "lit" for c in part[1]):
        # Without a letter or digit of its own the form would read every bare number (or every
        # ticket-number pair) in any text as a case id: phantom ids.
        reasons.append("has no letter or digit of its own outside the placeholders - it would read "
                       "every bare number as a case id; add literal text such as TC")
    return (None if reasons else parts), reasons


def _body(parts: list, ticket: str) -> str:
    out = []
    for part in parts:
        if part[0] == "lit":
            # re.escape also escapes '-', which is literal outside a character class; leaving
            # it out keeps the default form's source exactly the legacy `TC-\d+`.
            out.append(re.escape(part[1]).replace(chr(92) + "-", "-"))
        elif part[0] == "ticket":
            out.append(ticket)
        else:
            out.append(_NNN)
    return "".join(out)


@lru_cache(maxsize=128)
def _compiled(templates: tuple, ticket: str, ignore_case: bool):
    """One matcher for a tuple of VALID templates and the `{ticket}` pattern they read with, cached by
    both (the config is re-read per call by callers; the regex is not rebuilt, and two projects with two
    key shapes never share an entry)."""
    bodies = []
    for template in templates:
        body = _body(_analyse(template)[0], ticket)
        bodies.append(body if template == DEFAULT_FORM else _BEFORE + body + _AFTER)
    return re.compile("|".join(bodies), re.IGNORECASE if ignore_case else 0)


def _value(cfg):
    return cfg.get(CONFIG_KEY) if isinstance(cfg, dict) else None


def _entries(cfg) -> list:
    """The configured entries as a list; [] for an absent/None/""/[] key. Anything else that is
    not text or a list is one entry that `_analyse` will refuse."""
    value = _value(cfg)
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return list(value)
    return [value]


_DEFAULT_ONLY = (DEFAULT_FORM,)
_FORMS_BY_VALUE: dict = {}


def _ticket_pattern(cfg):
    """The `{ticket}` pattern of this project (its tracker's key shape), or None when the forms table
    cannot be read - and then no template that carries `{ticket}` is compiled."""
    try:
        return AF.key_form(cfg).story_pattern
    except AF.FormsTableError:
        return None


def _resolve(cfg) -> tuple:
    """(the templates in force, the `{ticket}` pattern they are compiled with), cached by the key's own
    value AND the ticket pattern, so two projects with two key shapes never share an answer.

    Called on every id question, so tokenising each template again per call was most of the cost of
    `case_matches` inside a loop over tests x results (B-013 performance). No key, "" or [] takes the
    constant answer without a lookup (and without reading the key shape: the default form has no ticket)."""
    value = cfg.get(CONFIG_KEY) if isinstance(cfg, dict) else None
    if value is None or value == "" or (isinstance(value, list) and not value):
        return _DEFAULT_ONLY, ""
    ticket = _ticket_pattern(cfg)
    key = (repr(value), ticket)
    found = _FORMS_BY_VALUE.get(key)
    if found is None:
        if len(_FORMS_BY_VALUE) > 256:
            _FORMS_BY_VALUE.clear()
        found = _FORMS_BY_VALUE[key] = _forms_of(cfg, ticket is not None)
    return found, ticket or ""


def forms(cfg=None) -> tuple:
    """The valid configured templates in config order, then the default `TC-{nnn}`, no repeats."""
    return _resolve(cfg)[0]


def _forms_of(cfg, ticket_readable: bool) -> tuple:
    out = []
    for entry in _entries(cfg):
        template = entry if isinstance(entry, str) else None
        if template is not None and not _analyse(template)[1] and template not in out \
                and template != DEFAULT_FORM and (ticket_readable or "{ticket}" not in template):
            out.append(template)
    out.append(DEFAULT_FORM)
    return tuple(out)


def problems(cfg=None) -> list:
    """One sentence per invalid entry, each naming the entry, what is wrong and what is expected.
    Empty when the key is absent, empty or valid."""
    out = []
    value = _value(cfg)
    if value is not None and not isinstance(value, (str, list)):
        return [f"config.{CONFIG_KEY} is {type(value).__name__}, not text or a list of texts - {_GRAMMAR}"]
    for entry in _entries(cfg):
        for reason in _analyse(entry)[1]:
            out.append(f"config.{CONFIG_KEY} entry {entry!r} {reason}" if isinstance(entry, str)
                       else f"config.{CONFIG_KEY} entry {reason}")
    try:
        AF.key_form(cfg)
    except AF.FormsTableError as exc:
        if any(isinstance(e, str) and "{ticket}" in e and not _analyse(e)[1] for e in _entries(cfg)):
            out.append(f"config.{CONFIG_KEY} reads the ticket key shape, and {exc} - until it is restored "
                       "only the forms that carry no {ticket} apply, and the default TC-{nnn}")
    return out


def pattern(cfg=None):
    """The compiled matcher for every form in force (case-sensitive: text and cells)."""
    templates, ticket = _resolve(cfg)
    return _compiled(templates, ticket, False)


def _text(value) -> str:
    return value if isinstance(value, str) else str(value or "")


def ids_in(text, cfg=None) -> list:
    """Every case id in `text`: maximal, non-overlapping, in order, each once.

    Maximal means the LONGEST id any form reads at that position, whatever the order of the forms
    in the config (`{ticket}_TC_{nnn}` and `{ticket}_TC_{nnn}_v2` both read `AB-1_TC_1_v2` as one
    id). With only the default form there is nothing to compare and the legacy findall runs as is."""
    subject = text if isinstance(text, str) else str(text or "")
    templates, ticket = _resolve(cfg)
    combined = _compiled(templates, ticket, False)
    if len(templates) == 1:
        return list(dict.fromkeys(combined.findall(subject)))
    singles = [_compiled((template,), ticket, False) for template in templates]
    found, position = [], 0
    while True:
        first = combined.search(subject, position)
        if first is None:
            break
        start, end = first.start(), first.end()
        for single in singles:
            hit = single.match(subject, start)
            if hit is not None and hit.end() > end:
                end = hit.end()
        found.append(subject[start:end])
        position = max(end, start + 1)
    return list(dict.fromkeys(found))


def is_id(value, cfg=None) -> bool:
    """Is the WHOLE value one case id in a form in force? Not a string -> False."""
    return isinstance(value, str) and pattern(cfg).fullmatch(value) is not None


def is_case_file_name(name, cfg=None) -> bool:
    """A case document's file name: `.md` (any case), and the stem either IS an id or starts with
    one followed by a character that is not a letter or digit (`TC-001-login.md`). File names are
    matched case-insensitively: Windows globs have always found `tc-001.md` and Linux ones did not."""
    base = _text(name).replace(chr(92), "/").rsplit("/", 1)[-1]
    if not base.lower().endswith(".md") or len(base) == 3:
        return False
    stem = base[:-3]
    templates, ticket = _resolve(cfg)
    for template in templates:
        found = _compiled((template,), ticket, True).match(stem)
        if found and (found.end() == len(stem) or not _ALNUM.match(stem[found.end()])):
            return True
    return False


def example(ticket, cfg=None, n: int = 1) -> str:
    """A well-formed id for the FIRST form in force: `TP1-13797_TC_001`, or `TC-001` under the
    default. A ticket that is not a key of the project's tracker stays a visible placeholder
    (`<TICKET>_TC_001`) instead of an invented key."""
    try:
        number = f"{int(n):03d}"
    except (TypeError, ValueError):
        number = "001"
    key = str(ticket or "").strip()
    if not AF.is_key(key, cfg):
        key = "<TICKET>"
    return forms(cfg)[0].replace("{ticket}", key).replace("{nnn}", number)
