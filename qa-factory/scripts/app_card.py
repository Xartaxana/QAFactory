#!/usr/bin/env python3
"""The app card of a story (t-1957 N3, AR-8): ONE small file, `work/app-card.md`, that hands a walker the routes, the sign-in,
the account NAMES and the test data of the application, so the walker does not read the application's sources.

    python -B scripts/app_card.py build --task-root <T>

Prints ONE line and never refuses (AR-23): every section is lines or `not known: <why>`; the sections are, in this order,
Stand, Entry routes, First look, Sign-in, Accounts, Test data, Page objects, Notes from walkers. The first line says the card is no
oracle (FR-58): the expected result of a step comes only from the case's Thens. The card holds NAMES and handles, never a
credential value (E3.3): every free text passes `scrub`, and a value is read only by the readers named below, never printed.

Readers reused, none copied (AR-13): `env_probe.frontend_of` (through `brief_pack.manual_stand_lines`, which also gives the
account roles and the env key NAMES), `manual_capture.login_recipe` / `sign_in_refusal` / `read_login` (key names only),
`user_path_failures.read_requests`, `report_facts.created_accounts_line` (through `manual_capture.created_names_path`),
`first_look.read` (the First look section: what the walker saw per requirement, an observation and never an oracle - t-2277 FL-4).

The card is rebuilt only when its inputs change: the last line carries a hash of the inputs, and a build whose hash equals the
file's leaves the file alone. The card is at most CARD_MAX_BYTES; beyond it the entry routes are cut, the tail line names how
many and the file that holds them; before that, the First look section collapses to a pointer to its file. The other sections are
bounded by their own per-line and per-list limits (below), so only the First look section and the routes give way to the limit.

This module holds no refusal site and no judgment: it reads data and assembles it (AR-29).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib  # noqa: E402

CARD_REL = "work/app-card.md"
NOTES_REL = "work/app-card-notes.jsonl"
FLOW_REL = "work/flow-requests.json"
PROFILE_REL = "qa-factory/strategy/project-profile.md"
CONFIG_REL = "qa-factory/config.json"
BRIEFS_REL = "work/briefs"
CARD_MAX_BYTES = 8000
FORMAT = "1"

FIRST_LOOK_REL = "work/first-look.yaml"
FIRST_LOOK_REQ_MAX = 20     # requirements the First look section shows; the rest is `+N: work/first-look.yaml`
FIRST_LOOK_REQ_LINES = 8    # lines one requirement shows; the rest is `+N: work/first-look.yaml`
FIRST_LOOK_LINE_CHARS = 200
FIRST_LOOK_POINTER = f"- First look: not shown, the card is full; read {FIRST_LOOK_REL} (an observation of the stand, never an expected value)"

NO_ORACLE = "routes and data to walk with; expectations come only from the case's Thens"
SECTIONS = ("Stand", "Entry routes", "First look", "Sign-in", "Accounts", "Test data", "Page objects", "Notes from walkers")
NO_PROFILE = "no strategy/project-profile.md (onboarding)"
NO_CONFIG = "no qa-factory/config.json above the task root (the project is not onboarded)"
DASH = "—"
NOT_PROVEN = f"Sign-in: not proven at gate A {DASH} sign in with fill-account"

LINE_CHARS = 300          # one line of a free text keeps this many characters
PROFILE_LINES = 10        # lines of a profile section the card keeps; the rest is counted
NOTE_LINES = 12           # the newest walker notes the card keeps; the rest is counted
NOTE_CHARS = 200
PAGE_OBJECT_LINES = 8
TEST_DATA_NAMES = 8       # names shown of a structured test-data key

_KEYWORD = (r"pass(?:word|wd|phrase)?|pwd|pw|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|credential")
_KV = re.compile(rf"(?i)\b({_KEYWORD})s?[\"']?(?:\s*[:=]|\s+(?:is|are|was)\b)\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;\"'}}\]]+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_PREFIXED = re.compile(r"\b(?:sk|pk|ghp|gho|glpat|xox[abp]|AKIA)[-_]?[A-Za-z0-9_-]{12,}")
_LONG_MIXED = re.compile(r"(?<![A-Za-z0-9_/.-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_/.-])")
_USERINFO = re.compile(r"(?<=://)[^/\s@]+@")


def scrub(text, *, tokens: bool = True) -> str:
    """`text` with every secret-looking value replaced (E3.3): a `password: x` / `token=x` / `secret is x` pair, a Bearer or
    Basic value, a JWT, a known token prefix, an address's `user:pass@`, and (when `tokens`) a long letters-and-digits run.
    The error direction is over-redaction. Names of keys are kept - the card hands names, not values."""
    out = " ".join(str(text if text is not None else "").split())
    out = _USERINFO.sub("", out)
    out = _KV.sub(lambda m: f"{m.group(1)}: [not printed]", out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} [not printed]", out)
    out = _JWT.sub("[not printed]", out)
    out = _PREFIXED.sub("[not printed]", out)
    return _LONG_MIXED.sub("[not printed]", out) if tokens else out


def _clip(text, limit: int = LINE_CHARS, tokens: bool = True) -> str:
    text = scrub(text, tokens=tokens)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _why(exc) -> str:
    return _clip(f"{exc.__class__.__name__}: {exc}" if str(exc) else exc.__class__.__name__, 160, tokens=False)


# --- reading the inputs ------------------------------------------------------------------------------------------

def _project_of(task_root: Path):
    import runtime_paths
    return runtime_paths.nearest_project(task_root)


def _read_text(path: Path):
    """`(text, "")`, `(None, "absent")` or `(None, why)`."""
    if not path.is_file():
        return None, "absent"
    try:
        return path.read_text(encoding="utf-8-sig"), ""
    except (OSError, ValueError) as exc:
        return None, _why(exc)


def _read_config(project):
    """`(config dict, "")` or `({}, why)`: why names the project's problem in the words of a `not known`."""
    if project is None:
        return {}, NO_CONFIG
    path = Path(project) / CONFIG_REL
    data = hooklib.read_json(path, None, errors=Exception, kind=dict)
    return (data, "") if data is not None else ({}, f"{CONFIG_REL} cannot be read as a JSON object")


def _profile_section(text: str, title: str) -> list:
    """The lines of the profile's section `title` (a heading, or a `- **Title** - text` item): the rest of the item's first
    line, then the lines up to the next heading or the next bold item. [] when the section is absent or empty."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        low = line.lower()
        if title not in low:
            continue
        is_heading = re.match(r"^\s*#{1,6}\s", line) and title in low
        is_item = re.match(r"^\s*[-*]\s+\*\*" + re.escape(title), low) or re.match(r"^\s*\*\*" + re.escape(title), low)
        if not (is_heading or is_item):
            continue
        body = []
        if is_item:
            first = re.sub(r"^\s*[-*]?\s*\*\*[^*]*\*\*\s*[:—–-]*\s*", "", line).strip()
            if first:
                body.append(first)
        for nxt in lines[i + 1:]:
            if re.match(r"^\s*#{1,6}\s", nxt) or re.match(r"^\s*[-*]\s+\*\*", nxt):
                break
            if nxt.strip():
                body.append(nxt.strip())
        return body
    return []


def _bounded(lines: list, rel: str, limit: int = PROFILE_LINES) -> list:
    out = [f"- {_clip(line.lstrip('-* '))}" for line in lines[:limit]]
    if len(lines) > limit:
        out.append(f"- (+{len(lines) - limit} more lines: {rel})")
    return out


# --- the sections: each returns (lines, [why it is not known]) ---------------------------------------------------

def _stand_lines(task_root, project, cfg, cfg_why):
    """(Stand lines, Accounts lines from the stand reader, Accounts why) from `brief_pack.manual_stand_lines` - the stand's
    addresses, the account roles and the env key NAMES; no case scope, no repo map (those are not the card's)."""
    if cfg_why:
        return [], [], cfg_why
    import brief_pack as BP
    got = BP.manual_stand_lines(task_root, project, cfg, [], "", None)
    stand = [_clip(x, tokens=False) for x in got if x.startswith(("- Stand:", "- API:", "- Frontend:"))]
    accounts = [_clip(x, tokens=False) for x in got if x.startswith(("- Accounts:", "- Env keys:"))]
    return stand, accounts, ""


def _route_rows(task_root):
    """(rows, why): `- METHOD address (path:line)` for each request of `work/flow-requests.json`, the query string dropped
    (a token may sit in it) - through `user_path_failures.read_requests`, the one reader."""
    import user_path_failures as UPF
    requests, said = UPF.read_requests(task_root)
    if requests is None:
        return [], (said or f"no {FLOW_REL} (the S3 plan step writes it)")
    rows = []
    for r in requests:
        if not isinstance(r, dict) or not r.get("url_template"):
            continue
        url = scrub(str(r["url_template"]).split("?", 1)[0].split("#", 1)[0], tokens=False)
        rows.append(f"- {_clip(r.get('method') or '?', 12, tokens=False)} {url} ({_clip(r.get('path') or '?', 120, tokens=False)}:{r.get('line', '?')})")
    return rows, ("" if rows else f"{FLOW_REL} lists no request")


def _signin(task_root, cfg, cfg_why):
    """(lines, why). The recipe's route and field NAMES, and whether gate A proved a sign-in for this recipe."""
    if cfg_why:
        return [], cfg_why
    import manual_capture as MC
    try:
        recipe = MC.login_recipe(cfg, MC.spec(), "ui")
    except ValueError as exc:
        return [], f"the sign-in recipe cannot be read ({_why(exc)})"
    if not recipe:
        return ["Sign-in: this stand needs no UI sign-in (manual_capture.login.ui is null in config.json)"], ""

    def box(sel):
        if isinstance(sel, dict):
            return _clip(f"{sel.get('role', 'field')} \"{sel.get('name', '')}\"", 80, tokens=False)
        return _clip(sel, 80, tokens=False)

    lines = [f"- Sign-in route: {_clip(recipe.get('path') or '/', 120, tokens=False)}; fields: username {box(recipe.get('username'))}, "
             f"password {box(recipe.get('password'))}, submit {box(recipe.get('submit'))}"]
    probe = hooklib.read_json(Path(task_root).joinpath(*MC.SIGN_IN_PROBE), None, errors=Exception, kind=dict) or {}
    proven = [a for a in probe if MC.sign_in_refusal(task_root, a, recipe) == ""]
    if proven:
        lines.append("Sign-in: proven at gate A for " + ", ".join(_clip(a, 60, tokens=False) for a in proven[:8])
                     + " (a `ui --session <account>` call signs in by code)")
    else:
        lines.append(NOT_PROVEN)
    return lines, ""


def _accounts(task_root, project, cfg, stand_accounts, cfg_why):
    """(lines, why): the roles and env key NAMES (the stand reader), the default account's key names (`read_login`, names
    only - its values are never read out of the object), the users the story created (names only)."""
    import report_facts as RF
    lines = list(stand_accounts)
    if not cfg_why:
        import manual_capture as MC
        try:
            found = MC.read_login(cfg, Path(project))
            if found is None:
                lines.append("- Default account: config.json names no env file for it")
            else:
                lines.append(f"- Default account: keys {_clip(found.user_key, 60, tokens=False)} / {_clip(found.password_key, 60, tokens=False)} "
                             f"in {_clip(found.env_file, 120, tokens=False)} (`--as default`; names only)")
        except ValueError as exc:
            lines.append(f"- Default account: not known ({_why(exc)})")
    created = RF.created_accounts_line(Path(task_root))
    if created:
        lines.append(f"- {_clip(created, 400, tokens=False)} (`--as created:<username>`)")
    return lines, ("" if lines else (cfg_why or "no account is recorded for this stand"))


def _test_data(project_text, profile_why, cfg, cfg_why):
    """(lines, [why]): the profile's `Test data` section and the config's `test_data` keys (names; a scalar's text only when
    the key does not look like a secret)."""
    import env_probe as EP
    lines, whys = [], []
    if project_text is None:
        whys.append(profile_why)
    else:
        section = _profile_section(project_text, "test data")
        lines += _bounded(section, PROFILE_REL) if section else []
        if not section:
            whys.append(f"{PROFILE_REL} has no Test data section")
    data = cfg.get("test_data") if isinstance(cfg, dict) else None
    if cfg_why:
        whys.append(cfg_why)
    elif not isinstance(data, dict) or not data:
        whys.append("config.json has no test_data")
    else:
        for key, value in list(data.items())[:PROFILE_LINES]:
            key = _clip(key, 60, tokens=False)
            if EP.SECRET_NAME.search(key):
                lines.append(f"- config test_data.{key}: (value not printed)")
            elif isinstance(value, dict):
                names = ", ".join(_clip(k, 40, tokens=False) for k in list(value)[:TEST_DATA_NAMES])
                lines.append(f"- config test_data.{key}: {len(value)} entries" + (f" (names: {names})" if names else ""))
            elif isinstance(value, list):
                lines.append(f"- config test_data.{key}: {len(value)} items")
            else:
                lines.append(f"- config test_data.{key}: {_clip(value)}")
        if len(data) > PROFILE_LINES:
            lines.append(f"- (+{len(data) - PROFILE_LINES} more keys: {CONFIG_REL})")
    return lines, whys


def _repo_map_file(task_root):
    folder = Path(task_root) / BRIEFS_REL
    try:
        found = sorted(folder.glob("repo-map-*.md"), key=lambda p: (p.stat().st_mtime, p.name))
    except OSError:
        return None
    return found[-1] if found else None


def _page_objects(map_file):
    """(lines, why): the bullets of the repo map's `Utils, page objects and test data` section - the map that
    `repo_map.py` wrote (not built here)."""
    if map_file is None:
        return [], f"no repo map built for this story yet ({BRIEFS_REL}/repo-map-*.md)"
    text, why = _read_text(map_file)
    if text is None:
        return [], f"{BRIEFS_REL}/{map_file.name} cannot be read ({why})"
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.startswith("## Utils, page objects")
            continue
        if inside and line.startswith("- `"):
            lines.append(line)
    if not lines:
        return [], f"{BRIEFS_REL}/{map_file.name} names no page object or helper module"
    shown = [f"- {_clip(x[2:], 200, tokens=False)}" for x in lines[:PAGE_OBJECT_LINES]]
    if len(lines) > PAGE_OBJECT_LINES:
        shown.append(f"- (+{len(lines) - PAGE_OBJECT_LINES} more: {BRIEFS_REL}/{map_file.name})")
    return shown, ""


def _notes(task_root):
    """(lines, why): the newest NOTE_LINES notes of the walkers about the card (`work/app-card-notes.jsonl`, one JSON object
    per line, `about: "card"`, the text in `note`, else `text`)."""
    path = Path(task_root) / NOTES_REL
    text, why = _read_text(path)
    if text is None:
        return [], (f"no walker has left a note yet ({NOTES_REL})" if why == "absent" else f"{NOTES_REL} cannot be read ({why})")
    notes, bad = [], 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
        elif row.get("about") == "card":
            body = row.get("note") if row.get("note") else row.get("text")
            if isinstance(body, str) and body.strip():
                notes.append(body)
    lines = [f"- {_clip(n, NOTE_CHARS)}" for n in notes[-NOTE_LINES:]]
    if len(notes) > NOTE_LINES:
        lines.insert(0, f"- (+{len(notes) - NOTE_LINES} older notes: {NOTES_REL})")
    if bad:
        lines.append(f"- ({bad} unreadable line(s) of {NOTES_REL} skipped)")
    if not notes:
        return [], (f"{NOTES_REL} has no readable note about the card" if bad else f"no note about the card in {NOTES_REL}")
    return lines, ""


# --- the first look (t-2277 FL-4) --------------------------------------------------------------------------------

def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _cut(text: str, limit: int) -> str:
    """`text` cut to `limit` characters with `...` - no scrub (the items it cuts were scrubbed once; a second pass garbles `[not printed]`)."""
    return text if len(text) <= limit else text[:limit - 3] + "..."


def first_look_path_items(row) -> list:
    """`[(kind, text)]` of what ONE row of the first look says about where the requirement lives on the stand - the ONE survivor of this
    reading (AR-13, AR-15): the card and the briefs of S4 and S5 both call it. Kinds, in this order: `screen`, `step`, `locator`, `api`,
    `sample`, `data`, `roles`. Observations only (FR-58, P20): the walker's `why`, `quote` and every key a record might carry that is not a
    key of the form's `path` (`expected`, `then`, `should`, ...) are never read here; every data value and every sample is prefixed
    `seen:` in its text. Every text passes `scrub`: the STRUCTURAL fields (url, steps, locators, api method/path/auth/seen) with
    `tokens=False` - a long `data-testid` is not a secret and the automator must be shown it whole (a `token=...` pair, a Bearer, a JWT and a
    known prefix are still hidden) - the VALUE fields (data, sample, roles) with `tokens=True` (a value may be a token). Never raises; a
    malformed `path` is no items."""
    path = row.get("path") if isinstance(row, dict) else None
    if not isinstance(path, dict):
        return []

    def keep(text):
        return scrub(text, tokens=False)

    out = []
    if _text(path.get("url")):
        out.append(("screen", f"screen {keep(path['url'])}"))
    steps = path.get("steps") if isinstance(path.get("steps"), list) else []
    out += [("step", f"step {keep(s)}") for s in steps if _text(s)]
    for item in path.get("locators") if isinstance(path.get("locators"), list) else []:
        if isinstance(item, dict) and _text(item.get("selector")):
            out.append(("locator", f"locator {keep(_text(item.get('what')) or '?')}: {keep(item['selector'])} (seen {keep(item.get('seen') or '?')})"))
    for item in path.get("api") if isinstance(path.get("api"), list) else []:
        if not isinstance(item, dict) or not (_text(item.get("method")) or _text(item.get("path"))):
            continue
        out.append(("api", f"api {keep(_text(item.get('method')) or '?')} {keep(_text(item.get('path')) or '?')} "
                           f"(auth {keep(item.get('auth') or '?')}, seen {keep(item.get('seen') or '?')})"))
        sample = item.get("sample")
        if isinstance(sample, dict) and any(_text(str(sample.get(k) or "")) for k in ("request", "status", "response")):
            bits = [scrub(str(sample.get(k))) for k in ("request", "status", "response") if str(sample.get(k) or "").strip()]
            out.append(("sample", "sample seen: " + " | ".join(bits)))
    data = path.get("data") if isinstance(path.get("data"), list) else []
    out += [("data", f"data seen: {scrub(d)}") for d in data if _text(d)]
    roles = [scrub(r) for r in (path.get("roles") if isinstance(path.get("roles"), list) else []) if _text(r)]
    if roles:
        out.append(("roles", "roles seen: " + ", ".join(roles)))
    return out


def first_look_head(row) -> str:
    """`R-n status[ (blocked_by)]` of one row - the ONE head of a first-look line, used by the card and by the briefs (AR-15)."""
    status = scrub(_text(row.get("status")) or "?")
    blocked = _text(row.get("blocked_by"))
    return f"{scrub(_text(row.get('req')) or '?')} {status}" + (f" ({scrub(blocked)})" if blocked else "")


def _first_look(task_root):
    """`(lines, [why])` of the First look section: per requirement of the record (at most FIRST_LOOK_REQ_MAX, in the record's order) its
    status, `blocked_by` and its path items, at most FIRST_LOOK_REQ_LINES lines each and FIRST_LOOK_LINE_CHARS characters a line, the rest
    `+N: work/first-look.yaml`. Read through `first_look.read` (the one reader). No record, a `null` one, an unreadable one and a STALE
    one are each ONE reason line, never an empty section and never a guess that the stand was walked (AR-23); a stale record shows no row
    (it confirms nothing). An observation, never an oracle: the section holds no key of a row but its status, `blocked_by` and `path`."""
    import first_look as FL
    state = FL.state(task_root)     # the one classification of the record's state (AR-15); this function only words it
    kind, got = state["kind"], state["got"]
    if kind == "error":
        raise RuntimeError(state["error"])      # `_safe` turns it into the section's one reason line
    if kind == "null":
        return [], [f"there was no first look: the stand was not walked ({_clip(got['null'].replace('_', ' '), 80, tokens=False)})"]
    if kind == "stale":
        return [], ["the first look is STALE: it was walked on other code or another register than the current ones; it confirms nothing, "
                    f"read {FIRST_LOOK_REL} as history" + (f" ({_clip(got['problem'], 80, tokens=False)})" if got["problem"] else "")]
    if kind == "absent":
        return [], ["there was no first look"]
    if kind == "unreadable":
        return [], [f"the first look cannot be read ({_clip(got['problem'], 120, tokens=False)})"]
    rows = got["rows"]
    out = []
    for row in rows[:FIRST_LOOK_REQ_MAX]:
        lines = [first_look_head(row)] + [text for _kind, text in first_look_path_items(row)]
        block = [("- " + _cut(x, FIRST_LOOK_LINE_CHARS - 2)) if i == 0 else ("  - " + _cut(x, FIRST_LOOK_LINE_CHARS - 4))
                 for i, x in enumerate(lines[:FIRST_LOOK_REQ_LINES])]
        if len(lines) > FIRST_LOOK_REQ_LINES:
            block.append(f"  - +{len(lines) - FIRST_LOOK_REQ_LINES}: {FIRST_LOOK_REL}")
        out += block
    if len(rows) > FIRST_LOOK_REQ_MAX:
        out.append(f"- +{len(rows) - FIRST_LOOK_REQ_MAX}: {FIRST_LOOK_REL}")
    return out, ([] if rows else [f"the first look holds no row ({FIRST_LOOK_REL})"])


# --- assembling --------------------------------------------------------------------------------------------------

def inputs_hash(task_root, project, map_file) -> str:
    """The hash of everything the card reads (bytes of each input file or its absence), the format and the limit."""
    h = hashlib.sha256(f"{FORMAT}|{CARD_MAX_BYTES}".encode("utf-8"))
    paths = [Path(task_root) / FLOW_REL, Path(task_root) / NOTES_REL, Path(task_root) / "state" / "sign-in-probe.json",
             Path(task_root) / "state" / "created-accounts.json", Path(task_root) / FIRST_LOOK_REL]
    try:        # the section says STALE when the code or the register moved since the walk: that verdict is an input too
        import first_look as FL
        kind = FL.state(task_root)["kind"]
        h.update(b"\0first-look-stale\0" + (b"-" if kind == "error" else b"1" if kind == "stale" else b"0"))
    except Exception:  # noqa: BLE001 - the hash must always be made; an unreadable reader changes nothing here
        h.update(b"\0first-look-stale\0-")
    if project is not None:
        paths += [Path(project) / PROFILE_REL, Path(project) / CONFIG_REL]
    if map_file is not None:
        paths.append(map_file)
    for path in paths:
        h.update(b"\0" + path.name.encode("utf-8", "replace") + b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            h.update(b"-")
    return h.hexdigest()[:24]


def _safe(section, call):
    """A section that fails to read says so (AR-23); the others are still built."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - a malformed source must cost one section, not the card
        return [], f"cannot be read ({_why(exc)})"


def _section_text(name, lines, whys):
    if lines:
        return [f"## {name}"] + lines + [f"- not known: {w}" for w in whys if w]
    return [f"## {name}", "not known: " + ("; ".join(w for w in whys if w) or "nothing recorded")]


def build_card(task_root) -> tuple:
    """`(text, not_known_count)` - the card for the story at `task_root` (does not write)."""
    task_root = Path(task_root)
    project = _project_of(task_root)
    cfg, cfg_why = _read_config(project)
    profile, profile_why = (None, NO_PROFILE) if project is None else _read_text(Path(project) / PROFILE_REL)
    if profile is None:
        profile_why = NO_PROFILE if profile_why == "absent" else f"{PROFILE_REL} cannot be read ({profile_why})"
    map_file = _repo_map_file(task_root)
    digest = inputs_hash(task_root, project, map_file)

    stand = _safe("stand", lambda: _stand_lines(task_root, project, cfg, cfg_why))
    stand_lines, stand_accounts, stand_why = stand if len(stand) == 3 else ([], [], stand[1])
    rows, rows_why = _safe("routes", lambda: _route_rows(task_root))
    routes_head = []
    routes_whys = []
    if profile is not None:
        entry = _profile_section(profile, "components and entry points")
        routes_head = _bounded(entry, PROFILE_REL) if entry else []
        if not entry:
            routes_whys.append(f"{PROFILE_REL} has no Components and entry points section")
    else:
        routes_whys.append(profile_why)
    if not rows:
        routes_whys.append(rows_why)
    signin, signin_why = _safe("signin", lambda: _signin(task_root, cfg, cfg_why))
    accounts, accounts_why = _safe("accounts", lambda: _accounts(task_root, project, cfg, stand_accounts, cfg_why))
    data, data_whys = _safe("data", lambda: _test_data(profile, profile_why, cfg, cfg_why))
    pages, pages_why = _safe("pages", lambda: _page_objects(map_file))
    notes, notes_why = _safe("notes", lambda: _notes(task_root))
    look, look_why = _safe("first look", lambda: _first_look(task_root))
    look_whys = look_why if isinstance(look_why, list) else [look_why]

    fixed = {
        "Stand": _section_text("Stand", stand_lines, [stand_why]),
        "Sign-in": _section_text("Sign-in", signin, [signin_why]),
        "Accounts": _section_text("Accounts", accounts, [accounts_why]),
        "Test data": _section_text("Test data", data, data_whys if isinstance(data_whys, list) else [data_whys]),
        "Page objects": _section_text("Page objects", pages, [pages_why]),
        "Notes from walkers": _section_text("Notes from walkers", notes, [notes_why]),
    }
    tail_hash = f"inputs: {digest}"

    def render(shown: int, force_real: bool = False, look_full: bool = True) -> str:
        left = len(rows) - shown
        body = routes_head + rows[:shown] + ([f"- +{left} more: {FLOW_REL}"] if left > 0 else [])
        if body or force_real:
            routes = ["## Entry routes"] + body + [f"- not known: {w}" for w in routes_whys if w]
        else:
            routes = _section_text("Entry routes", [], routes_whys)
        # the First look section gives way FIRST: a pointer to its file, before a single route is cut
        first = _section_text("First look", look, look_whys) if look_full or not look else ["## First look", FIRST_LOOK_POINTER]
        parts = {**fixed, "Entry routes": routes, "First look": first}
        out = [NO_ORACLE]
        for name in SECTIONS:
            out += parts[name]
        return "\n".join(out + [tail_hash]) + "\n"

    size = lambda s: len(s.encode("utf-8"))  # noqa: E731
    shown = len(rows)
    look_full = True
    if size(render(shown)) > CARD_MAX_BYTES and look:
        look_full = False       # the section collapses to a pointer before the routes are cut
    if size(render(shown, look_full=look_full)) > CARD_MAX_BYTES:
        base = size(render(0, force_real=True, look_full=look_full))
        # the tail line `+N more` is counted per k; rows' sizes are prefix sums, so the search is linear
        prefix = [0]
        for row in rows:
            prefix.append(prefix[-1] + len(row.encode("utf-8")) + 1)
        shown = 0
        for k in range(len(rows) - 1, -1, -1):
            tail = len(f"- +{len(rows) - k} more: {FLOW_REL}".encode("utf-8")) + 1
            if base - (len(f"- +{len(rows)} more: {FLOW_REL}".encode("utf-8")) + 1) + prefix[k] + tail <= CARD_MAX_BYTES:
                shown = k
                break
    text = render(shown, look_full=look_full)
    count = sum(1 for line in text.splitlines() if line.startswith("not known:") or line.startswith("- not known:"))
    return text, count


def _last_hash(path: Path) -> str:
    try:
        last = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()][-1]
    except (OSError, ValueError, IndexError):
        return ""
    return last[len("inputs: "):] if last.startswith("inputs: ") else ""


def build(task_root) -> str:
    """Write `work/app-card.md` when its inputs changed; return the ONE line to print. Never raises."""
    task_root = Path(task_root)
    if not task_root.is_dir():
        return "app-card: not written - the task root is not a folder"
    try:
        project = _project_of(task_root)
        card = task_root / CARD_REL
        if card.is_file() and _last_hash(card) == inputs_hash(task_root, project, _repo_map_file(task_root)):
            return f"app-card: unchanged {CARD_REL}"
        text, unknown = build_card(task_root)
        card.parent.mkdir(parents=True, exist_ok=True)
        tmp = card.with_name(card.name + ".tmp")
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, card)
        return f"app-card: written {CARD_REL} ({len(text.encode('utf-8'))} B, {unknown} not known)"
    except Exception as exc:  # noqa: BLE001 - the card is a courtesy: the walk goes on without it
        return f"app-card: not written ({exc.__class__.__name__}); the walker reads the page with `look`"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("build", help="write work/app-card.md when its inputs changed; print one line")
    one.add_argument("--task-root", required=True, help="the story's folder (qa-factory/artifacts/<TICKET>)")
    ns = ap.parse_args(argv)
    line = build(ns.task_root)
    print(line.encode("ascii", "replace").decode("ascii"))     # one ASCII line: a console of any code page prints it
    return 0


if __name__ == "__main__":
    sys.exit(main())
