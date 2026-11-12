"""Environment helper: one command instead of every role parsing .env for itself.

Usage (any role that needs the stand):
    env_probe.py [--env <name>] [--task <TICKET>] [--json] [--no-login] [--project-root DIR]

THREE FACTS, THREE VERDICTS. The output always ends in exactly these three lines:

    liveness: alive|dead|wants_login — <url> -> HTTP <code>
    login:    ok as <user_key>|failed HTTP <code>|not_recorded|skipped — <why>
    keys:     ok|<N> missing — <KEY>: needed by <areas or "nothing in this story">; ...

Why three. 23.09.2026, a second checkout of the same harness: a stand behind an identity
provider answered 302 to every path without a token, the probe reported one undivided
verdict, and the orchestrator told the person "Layer 1 still failing ... HTTP 302 on all
endpoints ... likely clears once the auth credentials above are in place". The block had
come from somewhere else entirely (four keys in `secret_keys` that no test in that story
read), and the 302 was the stand behaving exactly as designed. One verdict over three
different facts leaves a guess as the only thing to say.

LAYER 1 — the environment cannot be used, exit 1 — is ONLY: the stand does not answer, the
login was refused, or a key the LOGIN ITSELF needs is not set. A missing key that no login
needs is a line naming who needs it, never a halt: `<KEY>: MISSING — needed by <area>` comes
from `integrations[].required_by` or from the cases whose `preconditions` name the key
(`--task` says which story to look in), and "nothing in this story" is a legitimate answer.
With `login: ok` no missing key is Layer 1 at all — we are demonstrably inside.

SECRETS ARE NEVER PRINTED. For a secret key only "present"/"MISSING" and a length are
shown: the helper's output travels into the role's context and from there into the
transcript, and secrets have no business being there (the same rule as guard_secrets). The
secret's value is taken from env by the test framework, not by a role out of the chat.

The project's conventions live in config.json -> environment (filled in by onboarding):
    "environment": {
      "env_file": "path to the variables file relative to the project root (empty - values
                   come from the process environment: credentials in CI or a secret
                   manager rather than in a file)",
      "base_url_key": "name of the key holding the stand's address",
      "user_key": "name of the key holding the account",
      "secret_keys": ["names of secret keys"],
      "health_path": "liveness path relative to base_url, e.g. /health - this way the
                      stand's address is NOT duplicated: a shared stand moves and only one
                      place is edited",
      "health_url": "full liveness url; overrides health_path when liveness does not live
                     on the stand itself (an external probe, a separate service)",
      "health_expect": [extra codes counted as alive; a stand behind authentication answers
                        401, and that is 'alive' too. 200..399 always count],
      "extra_keys": ["other useful non-secret keys"],
      "access": {"kind": ..., "unauth_status": [302, 401], ...}
                      — HOW this project logs in, by key NAMES (see stand_access.py). A
                      project whose config predates it gets `login: not_recorded`, which is
                      an onboarding gap and never a refusal,
      "integrations": [{"name": "gitlab", "keys": ["GITLAB_URL", "GITLAB_TOKEN"],
                        "owner": "who issues them", "required_by": ["<area or profile>"]}]
                      — the stand's integration prerequisites: printed with an owner and
                      with who needs them; exit code unchanged
    }

Boundaries. The block describes ONE environment - the one this factory installation works
against. A project that tests on several (Dev/QA/Stage) makes that a deferred decision of
onboarding, not a silent pick of whichever came first.

An explicit `--env NAME` selects exactly one `environments[]` entry (FB-36). That entry's own
address (`api_base_url` | `api_url` | `base_url`) and its own health_url/health_path/health_expect
are what is probed; the global `environment.health_url` is never borrowed for a named stand
unless it is at that stand's own address, so a dead stand cannot be qualified by a different, live default stack. A name that is missing or
ambiguous stops the probe before any request, and so does an entry with no address of its own
when `environments[]` holds two or more entries AND the env file names none either. An entry
with a name only is the live shape: the stand's address is the env file's `base_url_key`, the
probe asks it, and the verdict line says "address_source: env file" (and what became of the block's absolute
health_url: kept when its scheme, host and port are the env-file address's own, dropped otherwise). The ONLY entry is the other
exception: the `environment` block is then that stand, the probe goes to the block's address, and
the verdict line says "address inherited from the project" (JSON: `liveness.address_source`:
own | inherited | env file | block). Under `--env` a liveness of `unchecked` (no address
anywhere) is Layer 1, never a pass. Every URL printed passes `http_client.safe_url`, so a
credential in an address never reaches a role's context. Without `--env` the `environment` block
is the stand - never a pick by list order.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import project_root, load_config  # noqa: E402
import stand_access  # noqa: E402

# A guard against a configuration mistake: a key with such a name is masked even if it was
# put into extra_keys. Being over-careful is cheaper than printing a password once.
SECRET_NAME = re.compile(r"(pass|secret|token|key|credential|auth)", re.IGNORECASE)
HEALTH_TIMEOUT_S = 5
LOGIN_TIMEOUT_S = 8
# Keys the FACTORY sets for its own runs, and switches of the machine's own client: found in
# a project's `secret_keys` they are an inventory of the harness's code, not credentials of
# the stand, and asking a person to "add these four keys" is asking for the wrong thing.
FACTORY_SET_KEY = re.compile(r"^(HEADLESS|QA_FACTORY_[A-Z0-9_]*)$")
CLIENT_SWITCH_KEY = re.compile(r"^(AWS_PROFILE|[A-Z0-9_]*_SESSION_TOKEN)$")
NOTHING_IN_STORY = "nothing in this story"


def parse_env_file(path: Path) -> dict:
    """A simple KEY=VALUE parser. Quotes are stripped, comments and blank lines skipped."""
    data = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_env(cfg: dict, root=None) -> tuple:
    """(values, where they came from, a fatal error or None).

    A file is not the only way to keep credentials: on a shared stand they often live in
    environment variables, in CI or in a secret manager. The file, when configured, is laid
    over the process variables - a local setting beats the shared one."""
    data = dict(os.environ)
    sources = ["process environment"]
    rel = (cfg.get("env_file") or "").strip()
    if rel:
        path = Path(root or project_root()) / rel
        if path.exists():
            data.update(parse_env_file(path))
            sources.append(rel)
        else:
            return (data, " + ".join(sources),
                    f"the file {rel} was not found (looked at {path}): the path in config.json "
                    "is stale, or the environment is not deployed")
    return (data, " + ".join(sources), None)


def resolve_health(cfg: dict, base: str) -> str:
    """A full url overrides the path; the path is glued to base_url so it is not duplicated."""
    if (cfg.get("health_url") or "").strip():
        return cfg["health_url"].strip()
    path = (cfg.get("health_path") or "").strip()
    if path and base:
        return base.rstrip("/") + "/" + path.lstrip("/")
    return ""


def _fetch(url: str, timeout: float):
    """The `http_client.Answer` of one anonymous GET (its `.status` is the code), redirects NOT followed. Raises
    when nothing answered. Mirrors `gate_preflight.http_get`: urllib follows a 302 to an identity
    provider and reports 200 on its login page, which is how a healthy stand was once
    recorded as MISSING. B-408: the request carries the factory's User-Agent and the body is read (bounded), so a
    protection page can be told from the stand's own answer. A test may return a bare int: `liveness` reads it as a
    status with nothing else known."""
    import http_client
    return http_client.fetch(url, headers={"Accept": "*/*"}, timeout=timeout, max_body=65536, expect="json")


def _shown(url) -> str:
    """The form of an address that may be printed: `http_client.safe_url` drops userinfo, query and fragment."""
    import http_client
    return http_client.safe_url(url) if str(url or "").strip() else ""


# ---- what an answer means: the table `references/stand-answers.json` (RH1-7, AR-1) ------------------------------------
STAND_ANSWERS_PATH = Path(__file__).resolve().parents[1] / "references" / "stand-answers.json"
_stand_cache: dict = {}
_UNREADABLE_ROW = {"id": "unreadable", "verdict": "dead", "means": "table_unreadable", "note": "",
                   "direct": {"words": ""}, "through_frontend": {"class": "unknown", "words": ""}}


def _empty_stand_answers() -> dict:
    return {"codes": [], "no_answer": [], "order": [], "login_remedies": [], "login_recheck": "", "remedy": {},
            "texts": {}, "table": "unreadable"}


def stand_answers() -> dict:
    """`references/stand-answers.json`, read once per path - the ONE reader of that table (mirrors
    `http_client.tables()`). Absent, unreadable, not an object, or without `codes`/`order`: empty tables with `table:
    "unreadable"`, never an exception. `order` rows come back sorted by their `order` number."""
    key = str(STAND_ANSWERS_PATH)
    if key not in _stand_cache:
        loaded = _empty_stand_answers()
        try:
            data = json.loads(Path(STAND_ANSWERS_PATH).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for name in ("codes", "no_answer", "order", "login_remedies"):
                    if isinstance(data.get(name), list):
                        loaded[name] = [row for row in data[name] if isinstance(row, dict)]
                for name in ("remedy", "texts"):
                    if isinstance(data.get(name), dict):
                        loaded[name] = data[name]
                if isinstance(data.get("login_recheck"), str):
                    loaded["login_recheck"] = data["login_recheck"].strip()
                loaded["order"] = sorted((r for r in loaded["order"] if isinstance(r.get("order"), (int, float))),
                                         key=lambda r: r["order"])
                if loaded["codes"] and loaded["order"]:
                    loaded["table"] = "ok"
        except (OSError, ValueError):
            pass
        _stand_cache[key] = loaded
    return _stand_cache[key]


def reload_stand_answers() -> None:
    """Forget what was read (a test points `STAND_ANSWERS_PATH` elsewhere)."""
    _stand_cache.clear()


def _row_takes(row: dict, code, kind, outcome=None) -> bool:
    """Does a table row take this answer: `any`, or a recorded `outcome` the row lists, or a code (`codes` / `from`..`to`)
    whose `kinds` / `not_kinds` fit. The one matcher of the `codes` and `login_remedies` tables."""
    if row.get("any"):
        return True
    if outcome is not None and outcome in (row.get("outcomes") or []):
        return True
    if isinstance(code, bool) or not isinstance(code, int):
        return False
    if code not in (row.get("codes") or []) and not (isinstance(row.get("from"), int) and isinstance(row.get("to"), int)
                                                    and row["from"] <= code <= row["to"]):
        return False
    if "kinds" in row and kind not in row["kinds"]:
        return False
    return kind not in (row.get("not_kinds") or [])


def answer_meaning(code, kind=None) -> dict:
    """The `codes` row for an HTTP answer (first match wins); a code no row covers is the catch-all row, and an
    unreadable table says `table_unreadable` - never `alive` (invariant C)."""
    tables = stand_answers()
    if tables["table"] != "ok":
        return _UNREADABLE_ROW
    for row in tables["codes"]:
        if _row_takes(row, code, kind):
            return row
    return {**_UNREADABLE_ROW, "id": "none", "means": "unknown_code"}


def no_answer_cause(exc) -> dict:
    """The `no_answer` row for an exception: the class NAME of `URLError.reason` (one unwrap level) else of the
    exception itself, then of its ancestors, most specific first (`RemoteDisconnected` is a reset, a certificate failure
    an `SSLError`); then the one code fallback `isinstance(exc, OSError)`; else the row marked `other`. An exception is
    never alive - the class only chooses the words."""
    rows = stand_answers()["no_answer"]
    target = exc
    inner = getattr(exc, "reason", None)
    if isinstance(inner, BaseException):
        target = inner
    if not isinstance(getattr(target, "reason", None), BaseException):  # still a wrapper: beyond the one level
        for cls in type(target).__mro__:  # a subclass takes the row of its most specific listed ancestor (B2)
            for row in rows:
                if cls.__name__ in (row.get("names") or []):
                    return row
        if isinstance(target, OSError):
            for row in rows:
                if row.get("fallback") == "OSError":
                    return row
    for row in rows:
        if row.get("fallback") == "other":
            return row
    return {"id": "N6", "cause": "no_answer", "direct": {"words": ""}, "through_frontend": {"class": "upstream", "words": ""}}


class _Words(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill(template, **values) -> str:
    """A table text with its {placeholders} filled; an unknown placeholder stays as written, a stray brace never raises."""
    try:
        return str(template or "").format_map(_Words(values))
    except (ValueError, IndexError, KeyError, AttributeError):
        return str(template or "")


# ---- the stand's frontend address: ONE reader (HF5-2, axis 29) ---------------------------------------------------
NO_FRONTEND = object()
FRONTEND_ALIAS_KEY = "frontend_url"   # the flat spelling a stand entry may carry; read ONLY here (axis 29), others use the name
HINT_MAX_NAMES = 5


def frontend_door(config) -> dict:
    """The one place the door texts about a missing frontend address come from (the hint and the host refusal).
    `set`: what a person sets; `why`: why the block's key cannot serve (only when it is configured and the config
    has two stands or more - the block serves a single-entry `environments[]` only); `none`: the refusal's clause."""
    cfg = config if isinstance(config, dict) else {}
    rows = [row for row in cfg.get("environments") or [] if isinstance(row, dict)]
    if len(rows) <= 1:
        return {"set": "environment.frontend.url_key", "why": "",
                "none": "environment.frontend.url_key or environments[].frontend.url"}
    block = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
    keyed = isinstance(block.get("frontend"), dict) and bool(str(block["frontend"].get("url_key") or "").strip())
    where = "environments[<name>].frontend.url in the entry of that stand"
    why = "environment.frontend.url_key serves only a single-entry environments[]" if keyed else ""
    return {"set": where, "why": why, "none": where + (f"; {why}" if why else "")}


def read_frontend(raw, ref_field: str, texts: dict, notes: list):
    """`(ref, api_path)` of a `frontend` object (`ref` is a key NAME in the block, a URL in an `environments[]` entry),
    or None - API-only, or a block the probe says it could not read (E-F7, E-F18). Never raises."""
    if raw is NO_FRONTEND:
        return None
    if not isinstance(raw, dict):
        notes.append(fill(texts.get("frontend_unreadable") or "frontend block unreadable"))
        return None
    ref, path = raw.get(ref_field), raw.get("api_path")
    ref, path = "" if ref is None else ref, "" if path is None else path
    if not isinstance(ref, str) or not isinstance(path, str):
        notes.append(fill(texts.get("frontend_unreadable") or "frontend block unreadable"))
        return None
    ref, path = ref.strip(), path.strip()
    if not ref and not path:
        return None
    if not ref:
        notes.append(fill(texts.get("frontend_no_address") or "frontend.api_path has no frontend address"))
        return None
    return ref, path


def frontend_address(url: str, label: str, texts: dict, notes: list) -> str:
    url = str(url or "").strip()
    if url.lower().startswith(("http://", "https://")):
        return url
    notes.append(fill(texts.get("frontend_unset" if not url else "frontend_not_http")
                      or "the frontend address is missing or not an http address", key=label))
    return ""


def _block_frontend(block: dict, values, root, texts: dict, notes: list) -> tuple:
    """`(address, key name, api_path)` under the `environment.frontend.url_key` of the block, `("", "", "")` when none (a
    note says why). `values` None: the env file laid over the process environment is loaded here (an unreadable file is
    a note, not a pass)."""
    ref = read_frontend(block["frontend"] if "frontend" in block else NO_FRONTEND, "url_key", texts, notes)
    if not ref:
        return "", "", ""
    if values is None:
        try:
            values, _source, fatal = load_env(block, root)
        except OSError as exc:
            values, fatal = {}, f"the env file could not be read ({exc.__class__.__name__})"
        if fatal:
            notes.append(f"the frontend address ({ref[0]}) is unknown: the env file named in environment.env_file "
                         "was not found or cannot be read")
            return "", "", ""
    return frontend_address(values.get(ref[0], ""), ref[0], texts, notes), ref[0], ref[1]


def frontend_of(config, env_name, values=None, *, entry=None, root=None) -> dict:
    """{"url", "source", "notes", "api_path", "key", "same_origin"} - the stand's frontend address, the ONE reader (AR-13); '' when none
    is configured. `api_path` is the frontend's API path beside the address ('' when none), `key` the env-file key name
    when the address came from the block ('' otherwise).

    Order: (1) the entry's `frontend.url`; (2) the same entry's flat `frontend_url` (an alias, kept readable); (3) the
    block's `environment.frontend.url_key` (a key NAME, its value in `values`) - ONLY when the entry is the one and only
    `environments[]` row, or no name is asked for (the block is then the stand; E-F13/F-2); (4) the stand's own base address,
    when the block names no UI address, a harness-command login recorded ok and a browser profile exist, and no other-origin
    http key could be the UI (RN1-3; errs toward ''; `same_origin` True, `source` `base_url (ui login probe)`); (5) ''. The address of the
    entry itself is never overridden by the block, and an entry that names an address it could not give (an unreadable
    `frontend`, a non-http value) is not given the block's either: the direction of an error is "the host is not
    allowed". `entry` names the row directly (a row without a unique name); `values` None loads the env file (`root`
    None: the project root of hooklib). Never raises; what could not be read is said into `notes` (names only, never a
    value)."""
    notes: list = []
    texts = stand_answers().get("texts") or {}
    cfg = config if isinstance(config, dict) else {}
    rows = [row for row in cfg.get("environments") or [] if isinstance(row, dict)]
    if entry is None and env_name:
        named = [row for row in rows if str(row.get("name") or "") == str(env_name)]
        entry = named[0] if len(named) == 1 else None
    index = next((i for i, row in enumerate(cfg.get("environments") or []) if row is entry), None) if entry is not None else None
    where = f"environments[{index}]" if index is not None else "environments[]"
    label = f"{(entry or {}).get('name') or where}.frontend"
    if entry is not None:
        before = len(notes)
        own = read_frontend(entry["frontend"] if "frontend" in entry else NO_FRONTEND, "url", texts, notes)
        url = frontend_address(own[0], label, texts, notes) if own else ""
        alias_raw = entry.get(FRONTEND_ALIAS_KEY)
        alias_raw = alias_raw.strip() if isinstance(alias_raw, str) else ""
        alias = frontend_address(alias_raw, f"{where}.frontend_url", texts, notes) if alias_raw else ""
        if url:
            if alias and alias != url:
                notes.append(f"{where} names a frontend.url and a different frontend_url; frontend.url is used")
            return {"url": url, "source": f"{where}.frontend.url", "notes": notes, "api_path": own[1], "key": "", "same_origin": False}
        if alias:
            return {"url": alias, "source": f"{where}.frontend_url (alias)", "notes": notes, "api_path": "", "key": "", "same_origin": False}
        if len(notes) > before or own or alias_raw:
            return {"url": "", "source": "", "notes": notes, "api_path": "", "key": "", "same_origin": False}   # the entry spoke, said nothing usable
    block = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else None
    sole = entry is not None and len(rows) == 1 and rows[0] is entry
    if block is not None and (sole or (entry is None and not env_name)):
        url, key, path = _block_frontend(block, values, root, texts, notes)
        if url:
            return {"url": url, "source": "environment.frontend.url_key", "notes": notes, "api_path": path, "key": key, "same_origin": False}
        derived = _derived_frontend(cfg, block, entry, values, root, texts, notes)
        if derived:
            return {"url": derived[0], "source": "base_url (ui login probe)", "notes": notes, "api_path": "", "key": derived[1],
                    "same_origin": True}
    return {"url": "", "source": "", "notes": notes, "api_path": "", "key": "", "same_origin": False}


def _own_ui_address(entry: dict) -> str:
    """The stand entry's own address read as a UI: its `base_url`; any other address key (`api_url`) only as the origin root
    (scheme://host[:port]) - an API path is never the UI. "" when the entry carries none."""
    for key in ("base_url",) + tuple(k for k in STAND_ADDRESS_KEYS if k != "base_url"):
        value = str(entry.get(key) or "").strip()
        if value:
            if key == "base_url":
                return value
            parts = urlsplit(value)
            return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    return ""


def _declared_keys(block: dict, *, extra_keys: bool) -> set:
    """The env-file key NAMES the block already declares (base, user, secrets, access keys, frontend url key, integrations'
    keys; `extra_keys` too when asked). The ONE exclusion set of the frontend hint and of the UI derivation (RN1-3)."""
    access = block.get("access") if isinstance(block.get("access"), dict) else {}
    frontend = block.get("frontend") if isinstance(block.get("frontend"), dict) else {}
    declared = {str(block.get(k) or "") for k in ("base_url_key", "user_key")}
    declared |= {str(access.get(k) or "") for k in ("user_key", "secret_key", "token_key", "client_id_key", "realm_key")}
    declared.add(str(frontend.get("url_key") or ""))
    url_ref = str(access.get("url") or "").strip()
    if url_ref and not url_ref.lower().startswith(("http://", "https://")):
        declared.add(url_ref)
    declared |= {str(k) for k in block.get("secret_keys") or []}
    if extra_keys:
        declared |= {str(k) for k in block.get("extra_keys") or []}
    for integ in block.get("integrations") or []:
        if isinstance(integ, dict):
            declared |= {str(k) for k in integ.get("keys") or []}
    return declared


def _derived_frontend(cfg: dict, block: dict, entry, values, root, texts: dict, notes: list):
    """`(address, base key name or "")` of the stand's OWN address taken as its UI - or None (RN1-3). Only when nothing is recorded
    and every guard holds: the block names no `frontend.url_key` (a configured but unreadable one is a refusal, not a gap); the
    entry has no `frontend` or `frontend_url`; `access.kind` is `harness_command` and its recorded login is exactly `ok` (an HTTP
    login proves the API, not a UI); a profile of the project is driven by a browser (`surfaces.profiles_driven_by`); the base
    address resolves to http(s); and no other undeclared http key of the env file sits on ANOTHER origin (it could be the UI).
    ERROR DIRECTION: a missed derivation is a question to a person, as before; a wrong one hands the host a UI that is not there.
    Never raises."""
    if entry is not None and ("frontend" in entry or str(entry.get(FRONTEND_ALIAS_KEY) or "").strip()):
        return None
    scratch: list = []
    if read_frontend(block["frontend"] if "frontend" in block else NO_FRONTEND, "url_key", texts, scratch) or scratch:
        return None
    access = block.get("access") if isinstance(block.get("access"), dict) else {}
    recorded = access.get("login_probe") if isinstance(access.get("login_probe"), dict) else {}
    if access.get("kind") != "harness_command" or recorded.get("outcome") != "ok":
        return None
    try:
        import surfaces
        if not surfaces.profiles_driven_by(cfg, "browser"):
            return None
    except ValueError:
        notes.append("the table of test surfaces could not be read, so a UI on the stand's own address was not derived")
        return None
    base_key = str(block.get("base_url_key") or "").strip()
    if values is None:
        try:
            values, _source, fatal = load_env(block, root)
        except OSError as exc:
            values, fatal = {}, f"the env file could not be read ({exc.__class__.__name__})"
        if fatal:
            notes.append(f"the frontend address ({base_key or 'base_url_key'}) is unknown: the env file named in "
                         "environment.env_file was not found or cannot be read")
            return None
    own = _own_ui_address(entry) if entry is not None and len(cfg.get("environments") or []) == 1 else ""
    base = own or (str(values.get(base_key, "") or "").strip() if base_key else "")
    if not base.lower().startswith(("http://", "https://")) or not origin(base):
        return None
    declared = _declared_keys(block, extra_keys=False)
    # `values` is the env file laid over the PROCESS environment (`load_env`): a proxy variable (HTTP_PROXY) of the machine is no
    # candidate for the stand's UI, so with an env file the keys are the file's own (the same set `_frontend_hint` reads)
    stand_keys = values
    rel = str(block.get("env_file") or "").strip()
    if rel:
        try:
            stand_keys = parse_env_file(Path(root or project_root()) / rel)
        except OSError:
            # the stand's own keys were not read, so the other-origin check cannot be made: an unknown is not a pass (FR-41)
            notes.append("the env file named in environment.env_file cannot be read, so the stand's own address "
                         f"({base_key or 'base_url_key'}) was not taken as its UI")
            return None
    blocking = [name for name in http_address_keys(stand_keys, declared, base.rstrip("/"))
                if origin(stand_keys[name]) != origin(base)]
    if blocking:    # a key that could be the real UI: the person is asked, as before - the note names the KEYS, never a value
        more = f" (+{len(blocking) - HINT_MAX_NAMES} more)" if len(blocking) > HINT_MAX_NAMES else ""
        notes.append(f"{', '.join(blocking[:HINT_MAX_NAMES])}{more} hold{'s' if len(blocking) == 1 else ''} an http address "
                     "on another origin than the stand's, so the stand's own address was not taken as its UI")
        return None
    return base, ("" if own else base_key)


def http_address_keys(values: dict, exclude, base: str = "") -> list:
    """The NAMES in an env file's `values` that hold an http(s) address and could be a stand's frontend: not in `exclude`, not
    secret-looking (`SECRET_NAME`), the value not equal to `base` (the API's own address, compared with a trailing slash cut).
    File order. The ONE enumeration the hint above (`_frontend_hint`) and the onboarding discovery
    (`project_inventory.access_discovery`) share (HF8-10, AR-15). A candidate is a guess: whether it is the UI is the role's
    and the person's to say (AR-2). Names only - the value is tested here and never returned."""
    return [name for name, value in (values or {}).items()
            if name and name not in exclude and not SECRET_NAME.search(name)
            and isinstance(value, str) and value.lower().startswith(("http://", "https://"))
            and value.strip().rstrip("/") != base]


def _frontend_hint(cfg: dict, env: dict, root, full_cfg=None) -> list:
    """The one detail line that names env-file keys holding an http address nothing declares as the frontend
    (a person's `FRONTEND_URL` the onboarding did not wire). NAMES only, never a value; a secret-looking name is not
    named; at most HINT_MAX_NAMES, then `(+K more)`. Whether such a key is the frontend is onboarding's to judge (AR-2)."""
    rel = str(cfg.get("env_file") or "").strip()
    if not rel:
        return []
    try:
        values = parse_env_file(Path(root or project_root()) / rel)
    except OSError:
        return []
    declared = _declared_keys(cfg, extra_keys=True)
    base = str(env.get(str(cfg.get("base_url_key") or ""), "") or "").strip().rstrip("/")
    names = http_address_keys(values, declared, base)
    if not names:
        return []
    shown = ", ".join(names[:HINT_MAX_NAMES]) + (f" (+{len(names) - HINT_MAX_NAMES} more)" if len(names) > HINT_MAX_NAMES else "")
    one = len(names) == 1
    door = frontend_door(full_cfg)
    return [f"  frontend: not configured; {shown} in {rel} {'holds an http address' if one else 'hold http addresses'}"
            f" - if {'it is' if one else 'one of them is'} this stand's frontend, set {door['set']} to it (onboarding)"
            + (f"; {door['why']}" if door["why"] else "")]


def liveness(url: str, expect=(), unauth=()) -> dict:
    """{"verdict", "code", "url", "note", "means", "cause", "said_kind"} — is anything answering at that address.

    `alive` the stand answered for itself; `wants_login` it answered and asked for a login
    (a redirect to an identity provider, a 401/403, or any code the project recorded as its
    norm in `access.unauth_status`/`health_expect`) — that is a live stand, not a blocker;
    `dead` nothing answered, or what answered cannot be a stand (5xx, a path that is not
    there). `unchecked` only when the config names no address at all. The verdict word and the note's suffix of
    an answer come from `references/stand-answers.json` (no code in this function compares a status); `means` is the
    row's meaning of an HTTP answer, `cause` the `no_answer` row's of an exception (one of the two, the other None)."""
    declared = {c for c in list(expect or []) + list(unauth or []) if isinstance(c, int)}
    if not url:
        return {"verdict": "unchecked", "code": None, "url": "",
                "note": "no address: neither health_path/health_url nor base_url_key resolves "
                        "to one, so nothing was asked", "means": None, "cause": None, "said_kind": None}
    shown = _shown(url)  # M-2: what is printed never carries the address's userinfo, query or fragment
    try:
        result = _fetch(url, HEALTH_TIMEOUT_S)
    except Exception as exc:
        return {"verdict": "dead", "code": None, "url": shown,
                "note": f"{shown} -> NO ANSWER ({type(exc).__name__})",
                "means": None, "cause": no_answer_cause(exc).get("cause"), "said_kind": None}
    # B-408: an int (a test's stand-in) is "a status and nothing else known"; an Answer also says WHO wrote the body.
    code = getattr(result, "status", result)
    said = (getattr(result, "verdict", None) or {})
    kind = said.get("kind")
    note = f"{shown} -> HTTP {code}"
    if not isinstance(code, bool) and code in declared:
        return {"verdict": "wants_login", "code": code, "url": shown,
                "note": note + " (the code this project recorded as its norm)",
                "means": "declared", "cause": None, "said_kind": kind}
    row = answer_meaning(code, kind)
    suffix = str(row.get("note") or "")
    if suffix:
        described = ""
        if "{described}" in suffix:
            import http_client
            described = http_client.describe(code, said, with_status=False)
        # a page is not the stand's data, and its title may be a protection service's - said, not decided (FR-41)
        suffix = fill(suffix, said=said.get("said"), described=described)
    return {"verdict": row.get("verdict") or "dead", "code": code, "url": shown, "note": note + suffix,
            "means": row.get("means"), "cause": None, "said_kind": kind}


ALIVE = ("alive", "wants_login")


def health(url: str, expect: list) -> tuple:
    """(alive, a human description). An unreachable stand is not an exception but a fact.

    Kept for `stand_health`, which probes several addresses and only needs the boolean: a
    stand that wants a login is alive - the one sentence the second project's 302 taught."""
    result = liveness(url, expect)
    return (result["verdict"] in ALIVE, result["note"])


CLEANUP_NONE = ("none", "nobody", "no one", "no-one", "n/a", "na", "-")
CLEANUP_UNKNOWN = ("", "unknown", "tbd", "?")


def data_cleanup(full_cfg: dict, env_name: str) -> tuple:
    """(state, one line about it). state: available | absent | unknown.

    The fact nobody asked for until it was too late. On TP2-2386 an early TC-002
    created 50 COMPLETED conferences on a persistent local stand; the product had no delete
    endpoint and the stand's own guard refused a database reset. A later test that expected
    exactly one COMPLETED record then found 20 of 51, and it took roughly eight runs and 267
    seconds of execution to prove the failure was the data and not the product. The data was
    designed and created before anyone established whether it could ever be removed — and
    the answer was already in config.json, unread: `test_data.cleanup_owner`.

    This never changes the exit code: a stand without cleanup is usable, it just has to be
    tested differently (own data under a run-unique tag, no assertion on a global count)."""
    td = (full_cfg or {}).get("test_data") or {}
    owner = str(td.get("cleanup_owner") or "").strip()
    stands = [e for e in (full_cfg or {}).get("environments") or [] if isinstance(e, dict)]
    stand = next((e for e in stands if str(e.get("name") or "") == env_name), None) if env_name else None
    safe = str((stand or {}).get("safe_to_break") or "").strip()

    if owner.lower() in CLEANUP_NONE:
        state = "absent"
        note = f"nobody resets this data (cleanup_owner: {owner or 'none'})"
    elif owner.lower() in CLEANUP_UNKNOWN:
        state = "unknown"
        note = ("cleanup_owner is not recorded — onboarding asks it (topic 3); until it is, "
                "assume the data you create stays")
    else:
        state = "available"
        note = f"cleanup_owner: {owner}"
    if env_name and stand is None:
        note += f"; no environments[] entry named `{env_name}`"
    elif safe:
        note += f"; safe_to_break on {env_name}: {safe}"
    return state, note


def integration_readiness(spec, values, environment_id="", obligation_ids=None):
    """Scope-aware credential discovery. Presence is never an access receipt."""
    environments = spec.get("environments") or []
    required_by = spec.get("required_by") or []
    if spec.get("applicability") == "not_required" or (environment_id and environments and environment_id not in environments):
        return {"status": "not_required", "reason": "outside selected scope"}
    if obligation_ids is not None and required_by and not set(required_by).intersection(obligation_ids):
        return {"status": "not_required", "reason": "no selected obligation requires this integration"}
    if spec.get("applicability") != "required" and not required_by:
        return {"status": "unknown", "reason": "applicability not established; no credentials requested"}
    alternatives = spec.get("credential_alternatives")
    if not alternatives:
        return {"status": "unknown", "reason": "credential alternatives not discovered; migrate legacy keys"}
    satisfied = any(isinstance(option, list) and option and all(values.get(k) for k in option)
                    for option in alternatives)
    if not satisfied:
        return {"status": "missing", "reason": "no credential alternative available for required scope"}
    probe = spec.get("probe_receipt") or {}
    if probe.get("status") == "ok" and probe.get("environment_id") == environment_id and probe.get("fresh") is True:
        return {"status": "ok", "reason": "credential alternative and fresh access probe verified"}
    return {"status": "unknown", "reason": "credential alternative present; access probe required"}


# --- who needs a key ---------------------------------------------------------------------

def _integration_needs(cfg: dict) -> dict:
    """{KEY: [areas or profiles]} from `integrations[].required_by` — the place a key found in
    the project's code but absent from its env file belongs, so that a story is told which
    AREA loses something rather than being stopped over a key nothing in it reads."""
    out: dict = {}
    for integ in cfg.get("integrations") or []:
        if not isinstance(integ, dict):
            continue
        areas = [str(a) for a in (integ.get("required_by") or []) if str(a or "").strip()]
        for key in integ.get("keys") or []:
            if isinstance(key, str) and key.strip():
                out.setdefault(key.strip(), []).extend(areas or [])
    return out


def _case_needs(task: str, root=None) -> dict:
    """{KEY: [case ids]} from the story's own cases — a `preconditions` entry whose check is
    `{"env": "NAME"}` is the one place a case says which variable it needs. Read through
    `gate_preflight`, which owns that shape, so the gate and the probe can never disagree."""
    out: dict = {}
    if not task:
        return out
    try:
        from gate_preflight import case_preconditions_raw, parse_preconditions
        from contract import case_files, case_glob
    except Exception:
        return out
    task_root = Path(root or project_root()) / "qa-factory" / "artifacts" / task
    if not task_root.exists():
        return out
    try:
        files = case_files(task_root)
    except Exception:
        files = case_glob(task_root / "work" / "test-cases", task_root)
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        items, _ = parse_preconditions(case_preconditions_raw(text))
        case_id = (re.search(r"^id:\s*(\S+)", text, re.MULTILINE) or [None, Path(path).stem])[1]
        for item in items:
            check = item.get("check") if isinstance(item, dict) else None
            name = (check or {}).get("env") if isinstance(check, dict) else None
            if isinstance(name, str) and name.strip():
                out.setdefault(name.strip(), []).append(str(case_id))
    return out


def needed_by(key: str, integration_needs: dict, case_needs: dict, login_keys) -> str:
    """The one phrase that turns a missing key from a halt into an address."""
    if key in (login_keys or []):
        return "the login itself"
    areas = [a for a in (integration_needs.get(key) or []) if a]
    if areas:
        return ", ".join(dict.fromkeys(areas))
    cases = [c for c in (case_needs.get(key) or []) if c]
    if cases:
        return ", ".join(dict.fromkeys(cases))
    if key in integration_needs:
        return "an integration that does not say which area needs it"
    return NOTHING_IN_STORY


def misplaced_keys(cfg: dict) -> list:
    """[(KEY, why it is not a credential of this stand)] — keys the factory sets for its own
    runs and switches of the machine's own client, found in `secret_keys`/`extra_keys`. They
    reach a config when onboarding inventories the key names in the harness's code instead of
    the keys the login actually used."""
    found = []
    for key in list(cfg.get("secret_keys") or []) + list(cfg.get("extra_keys") or []):
        if not isinstance(key, str) or not key.strip():
            continue
        name = key.strip()
        if FACTORY_SET_KEY.match(name):
            found.append((name, "the factory sets it for its own runs (run_suite.py), so the "
                                "project never has to hold it"))
        elif CLIENT_SWITCH_KEY.match(name):
            found.append((name, "a switch of this machine's own client, not a credential of "
                                "the stand"))
    return found


# --- the probe ---------------------------------------------------------------------------

# The keys an `environments[]` entry may carry its own address under, first match wins
# (`stand_health.py` reads every `*url` key of an entry for its wider sweep; the probe needs ONE).
STAND_ADDRESS_KEYS = ("api_base_url", "api_url", "base_url")
STAND_HEALTH_KEYS = ("health_url", "health_path", "health_expect")
INHERITED = "address inherited from the project"
FROM_ENV_FILE = "address_source: env file"
SELECTION_DOOR = ("give the environments[] entry its own base_url (or health_url) in qa-factory/config.json, "
                  "and keep exactly one entry per name")


def selected_probe_config(full_cfg: dict, env_name: str) -> tuple:
    """(cfg, base, error, source) - the `environment` block as the named stand sees it (FB-36).

    The selection replaces only the ADDRESS: the entry's own base and its own liveness keys. Everything
    else (env file, login keys, integrations, access) stays the project's - a named stand is the same
    project on another address. `source`: `block` (no name), `own` (the entry's address), `inherited`
    (the entry names none and is the ONLY entry, so the block is that stand and its address is read by
    the caller from the env file), `env file` (the entry names none and there are two or more entries - the live
    shape: the stand's address is the env file's `base_url_key`, read by the caller; the block's absolute
    health_url stays in the returned config only as a CANDIDATE: the caller keeps it when its scheme, host and port
    are the env-file address's own and drops it otherwise - `_same_origin`). `error` names what stops the probe BEFORE any request; with a borrowed
    global health_url a missing or unaddressed stand was once reported alive by the default stack.
    Pure: the caller's config is never changed. Same name rule as `data_cleanup` (the exact `name`)."""
    cfg = dict((full_cfg or {}).get("environment") or {})
    if not env_name:
        return cfg, "", None, "block"
    rows = [row for row in (full_cfg or {}).get("environments") or [] if isinstance(row, dict)]
    chosen = [row for row in rows if str(row.get("name") or "") == env_name]
    if len(chosen) != 1:
        return cfg, "", (f"the environment {env_name!r} is missing or ambiguous in environments[] "
                         f"({len(chosen)} entries carry that name); no stand was probed. Door: {SELECTION_DOOR}."), "none"
    stand = chosen[0]
    base = next((str(stand[k]).strip() for k in STAND_ADDRESS_KEYS if str(stand.get(k) or "").strip()), "")
    own_health = str(stand.get("health_url") or "").strip()
    if base or own_health:
        cfg.pop("health_url", None)  # a global absolute URL belongs to the default stand, not this one
        source = "own"
    elif len(rows) == 1:
        source = "inherited"  # the only stand: the environment block is it, global health_url included
    else:
        # The live shape (config-live-shape.json): `environments[]` names the stands and the stand's address is
        # the env file's `base_url_key` - not a stop. The block's global ABSOLUTE health_url may belong to the
        # default stack, so an address-less entry never borrows it blindly: it stays a candidate and the caller (which
        # reads the env file) keeps it only when it is at the env-file address; with no env-file address either the
        # probe ends as `unchecked` = Layer 1 (never a pass).
        source = "env file"
    for key in STAND_HEALTH_KEYS:
        if stand.get(key):
            cfg[key] = stand[key]
    return cfg, base, None, source


def origin(url) -> tuple:
    """(scheme, host, port) of an absolute URL, the default port filled in; () when it is not one (a bad port, no
    scheme or host, a scheme-less `host:port`). The ONE origin reader (AR-13): `_derived_frontend` and the onboarding
    discovery (`project_inventory.same_origin_keys`) use it too."""
    try:
        parts = urlsplit(str(url or "").strip())
        scheme, host, port = parts.scheme.lower(), (parts.hostname or "").lower(), parts.port
    except ValueError:
        return ()
    if scheme not in ("http", "https") or not host:
        return ()
    return (scheme, host, port or (443 if scheme == "https" else 80))


_origin = origin   # the old private name, kept readable


def _same_origin(url: str, other: str) -> bool:
    """Is `url` at the address `other` names - same scheme, host AND port (a different port is another stand)?
    The error direction is the asymmetric one: anything not provably the same is NOT the same, and the caller then
    asks the env-file address instead of the block's URL."""
    left = _origin(url)
    return bool(left) and left == _origin(other)


def _block_health_words(block_health: str, kept: bool, base: str) -> str:
    """What the verdict line says about the environment block's absolute health_url for an `env file` stand - true in
    each of the four cases (none / kept / on another address / no env-file address to compare with)."""
    if not block_health:
        return "the environment block names no health_url"
    if kept:
        return "the environment block's health_url is at that same address and is used"
    if base:
        return "the environment block names a health_url on another host or port — the env file address is used"
    return "the environment block names a health_url, but no env file address says it is this stand's, so it is not used"


def login_record(cfg: dict, access: dict, login_keys: list, receipt: dict):
    """The ready `environment.access.login_probe` object for this receipt (RH1-7, N4): `user_key` is the configured login
    key NAME (never the receipt's own, which is empty on a skipped one), `status` the receipt's code, `outcome` its
    status, `checked_at` now. None when no login key is configured - then there is nothing to record. A name, a code, a
    word and a date; never a value."""
    name = ""
    for key in (access.get("user_key"), cfg.get("user_key"), access.get("token_key")):
        if str(key or "").strip() and str(key).strip() in login_keys:
            name = str(key).strip()
            break
    if not name:
        return None
    record = {"user_key": name, "status": receipt.get("code"), "outcome": receipt.get("status"),
              "checked_at": datetime.now().replace(microsecond=0).isoformat()}
    fields = receipt.get("accepted_fields")
    if isinstance(fields, dict):
        for field in ("user_field", "secret_field"):
            if isinstance(fields.get(field), str) and fields[field].strip():
                record[field] = fields[field].strip()
    seconds = receipt.get("seconds")
    if stand_access.recorded_seconds({"login_probe": {"seconds": seconds}}) is not None:
        record["seconds"] = seconds   # how long an ok harness login took: the ceiling of the next one (RN1-3)
    return record


def _device_answer(full_cfg: dict, env_name: str):
    """The answer for a NAMED stand whose row is a device stand (`surface` -> a `hands: driver` row of surfaces.json), in the
    shape of `probe`; None for every other call (no name, no row of that name, no `surface`, any other hands) - then `probe` goes
    its old road and the table is never read. The device is asked by `device_stand.probe(..., deep=False)`: no session, nothing
    launched. ERROR DIRECTION: only toward Layer 1 - a probe that cannot run, an unreadable table, an unknown `surface`, a reply
    that is not `ok` are each a line, never exit 0; a device stand has no login by code and no key to miss, said as such."""
    if not env_name:
        return None
    rows = [r for r in (full_cfg or {}).get("environments") or [] if isinstance(r, dict) and str(r.get("name") or "") == env_name]
    if len(rows) != 1 or "surface" not in rows[0]:
        return None
    details: list = []

    def answer(verdict: str, line: str, failed: bool) -> dict:
        skipped = {"status": "skipped", "code": None, "user_key": "", "why": "a device stand has no login by code"}
        return {"liveness": {"verdict": verdict, "code": None, "url": "", "note": line, "address_source": "own"},
                "login": skipped, "keys": {"verdict": "ok", "missing": []}, "layer1": [line] if failed else [],
                "details": details, "source": "", "address_source": "own"}
    try:
        import surfaces
        device = surfaces.is_device_row(surfaces.row_of(rows[0]))
    except ValueError as exc:
        return answer("dead", "the surface of the environments[] row " + repr(env_name) + " could not be read: "
                      + " ".join(str(exc).split())[:300], True)
    if not device:
        return None
    try:
        import device_stand
        reply = device_stand.probe(full_cfg, env_name, deep=False)
    except Exception as exc:        # the probe is another script's: whatever it raises is a line, not a pass
        return answer("dead", f"the device stand {env_name!r} could not be checked ({type(exc).__name__}: "
                      + " ".join(str(exc).split())[:200] + ")", True)
    if not isinstance(reply, dict) or not isinstance(reply.get("verdict"), str):
        return answer("dead", f"the device stand {env_name!r} gave no verdict, so it is not taken as usable", True)
    for check in reply.get("checks") or []:
        if isinstance(check, dict) and check.get("line"):
            details.append(f"  device stand check {check.get('name') or '?'}: {check.get('state') or '?'} - {str(check['line'])[:200]}")
    block = reply.get("block") if isinstance(reply.get("block"), dict) else {}
    if reply["verdict"] == "ok":
        shown = "; ".join(str(c["line"])[:200] for c in reply.get("checks") or [] if isinstance(c, dict) and c.get("line"))
        return answer("ok", shown or f"the device stand {env_name!r} answers", False)
    line = str(block.get("probe_line") or f"the device stand {env_name!r}: the check says {reply['verdict']}")[:300]
    if block.get("remedy"):
        line += "; " + str(block["remedy"])[:300]
    return answer("dead", line, True)


def probe(full_cfg: dict, env_name: str = "", task: str = "", root=None,
          obligation_ids=None, do_login: bool = True) -> dict:
    """The whole answer as data: the three verdicts, what is Layer 1, and the detail lines.

    {"liveness": {...}, "login": {...}, "keys": {...}, "layer1": [...], "details": [...]}

    A named stand that is a device stand (EP1-41c) is answered FIRST, by `_device_answer`, before `selected_probe_config`: a row
    with no address would otherwise reach `unchecked_under_env`; a row with no `surface` and a call with no name keep the road
    below, byte for byte."""
    device = _device_answer(full_cfg, env_name)
    if device is not None:
        return device
    cfg, selected_base, selection_error, address_source = selected_probe_config(full_cfg, env_name)
    env, source, fatal = (({}, "the environments[] selection", selection_error) if selection_error
                          else load_env(cfg, root))
    # Every detail line is INDENTED: the three verdict lines are the only ones at column 0,
    # so a digest (or a person in a hurry) can take those three and nothing else.
    details: list = []
    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else {}
    login_keys = stand_access.login_keys(access)
    if str(access.get("kind") or "").strip() not in stand_access.KINDS:
        # A config written before the access block existed — or carrying the template's empty
        # one — still has ONE key without which no story can run: the account it was onboarded
        # with. Everything else belongs to an area, and blocks an area at most.
        login_keys = [k for k in [str(cfg.get("user_key") or "").strip(),
                                  next((str(k) for k in cfg.get("secret_keys") or [] if str(k or "").strip()), "")]
                      if k]
    if fatal:
        # FR-10: the three lines name the REAL reason - the selection or the env file - not one shared phrase.
        why = ("the selected environment could not be probed" if selection_error
               else "the env file was not found")
        fatal_login = {"status": "skipped", "code": None, "user_key": "", "why": f"{why}, so nothing was tried"}
        record = login_record(cfg, access, login_keys, fatal_login)
        if record:
            fatal_login["record"] = record
        return {"liveness": {"verdict": "dead", "code": None, "url": "", "note": fatal,
                             "address_source": address_source},
                "login": fatal_login,
                "keys": {"verdict": "unchecked", "missing": [], "why": why},
                "layer1": [fatal], "details": details, "source": source, "address_source": address_source}

    base_key = str(cfg.get("base_url_key") or "")
    # A stand with an address of its own is probed at THAT address; the env-file key answers for the block
    # (no name) and for the only stand that inherits it.
    base = selected_base if address_source == "own" else env.get(base_key, "") if base_key else ""
    # The live shape: the block's absolute health_url is a candidate, kept only at the env-file address (F2, t-1057);
    # `cfg` is this call's copy, so dropping it changes nothing the caller holds.
    block_health = str(cfg.get("health_url") or "").strip() if address_source == "env file" else ""
    health_kept = bool(block_health) and _same_origin(block_health, base)
    if block_health and not health_kept:
        cfg.pop("health_url", None)
    label = (f"{env_name} (environments[])" if address_source == "own"
             else f"{base_key or 'no key configured'}" + {"inherited": f"; {INHERITED}",
                                                          "env file": f"; {FROM_ENV_FILE}"}.get(address_source, ""))
    details.append(f"  base_url ({label}): {_shown(base) or 'MISSING'}")
    user_key = str(cfg.get("user_key") or "")
    if user_key:
        # user_key is printed as is: the operator declared it the account, and a role needs to
        # know WHO it works as - otherwise "access denied" is indistinguishable from "wrong user".
        # The defensive name-based masking stays on extra_keys, where a mistake is likelier.
        details.append(f"  account ({user_key}): {env.get(user_key, '') or 'MISSING'}")
    for key in cfg.get("secret_keys") or []:
        value = env.get(str(key), "")
        details.append(f"  {key}: {'present (' + str(len(value)) + ' chars)' if value else 'MISSING'}")
    for key in cfg.get("extra_keys") or []:
        value = env.get(str(key), "")
        if SECRET_NAME.search(str(key)):
            details.append(f"  {key}: {'present' if value else 'MISSING'} (the name looks secret - the value is not printed)")
        else:
            details.append(f"  {key}: {value or 'MISSING'}")
    front = frontend_of(full_cfg, env_name, env, root=root)
    if front.get("same_origin"):
        shown_key = f"{front['key']} - " if front.get("key") else ""
        details.append(f"  frontend: {shown_key}the stand's own address "
                       "(a UI login probe passed there: UI and API on one address)")
    elif not front["url"]:
        details.extend(_frontend_hint(cfg, env, root, full_cfg))

    # The stand's integration prerequisites (flags, external credentials, neighbouring services) —
    # by name, each with an owner. They do NOT change the exit code: a missing integration blocks an
    # area, not the stand; which areas are affected is the runner's preflight call (Phase 8 canon).
    for integ in cfg.get("integrations") or []:
        if not isinstance(integ, dict):
            continue
        result = integration_readiness(integ, env, env_name, obligation_ids)
        wanted = ", ".join(str(a) for a in integ.get("required_by") or []) or NOTHING_IN_STORY
        details.append(f"  integration {integ.get('name', 'unnamed')}: {result['status']} "
                       f"({result['reason']}; owner: {integ.get('owner') or 'unknown'}; "
                       f"needed by: {wanted})")
        if result["status"] != "not_required" and integ.get("health_url"):
            details.append(f"    liveness: {health(integ['health_url'], integ.get('health_expect') or [])[1]}")

    health_url = resolve_health(cfg, base)
    if not health_url and base:
        # No liveness path of its own: the address itself answers or nothing does.
        health_url = base
    live = liveness(health_url, cfg.get("health_expect") or [], access.get("unauth_status") or [])
    if not health_url and base_key and not base:
        live = {"verdict": "dead", "code": None, "url": "",
                "note": f"no address: {base_key} is not set in {source}"}

    live["address_source"] = address_source   # a key of the liveness object: the JSON keeps its four top-level fields
    if address_source == "inherited":
        # said in the VERDICT line, not only in a detail line: a digest, `--json` and the driver's three
        # `--env` calls read that line (or the exit code) and nothing else, and a pass through the project's
        # address must not be silent (FR-4)
        live["note"] += f" ({INHERITED}: the entry {env_name!r} names none and is the only one)"
    elif address_source == "env file":
        # the live shape, said on the verdict line like the inherited pass: the entry names the stand only
        live["note"] += (f" ({FROM_ENV_FILE}: the entry {env_name!r} names none, the stand is at {base_key or 'the address'} "
                         f"read from {source}; {_block_health_words(block_health, health_kept, base)})")
    unchecked_under_env = bool(env_name) and live["verdict"] == "unchecked"
    if unchecked_under_env:
        block_says = (", and the environment block's health_url is not used (no env file address says it is this "
                      "stand's)" if block_health else ", and the environment block names none")
        live["note"] = (f"no address: the environments[] entry {env_name!r} has none of its own{block_says}, "
                        f"so nothing was asked. Door: {SELECTION_DOOR}")

    if not do_login:
        receipt = {"status": "skipped", "code": None, "user_key": "",
                   "why": "not asked for (--no-login)"}
    elif live["verdict"] == "dead":
        receipt = {"status": "skipped", "code": None, "user_key": "",
                   "why": "the stand is not answering, so no login was tried"}
    elif unchecked_under_env:
        receipt = {"status": "skipped", "code": None, "user_key": "",
                   "why": "the stand has no address, so no login was tried"}
    elif address_source == "own" and not base:
        receipt = {"status": "skipped", "code": None, "user_key": "",
                   "why": "the stand has a health_url but no base address of its own, so no login was tried"}
    else:
        receipt = stand_access.login(access, env, base, LOGIN_TIMEOUT_S, health_url,
                                     Path(root or project_root()))
    record = login_record(cfg, access, login_keys, receipt)
    if record:
        receipt["record"] = record   # N4: the ready login_probe object; the onboarding role copies it whole

    integration_needs = _integration_needs(cfg)
    case_needs = _case_needs(task, root)
    missing = []
    for key in [user_key] + [str(k) for k in cfg.get("secret_keys") or []]:
        if not key or env.get(key, ""):
            continue
        missing.append({"key": key, "needed_by": needed_by(key, integration_needs, case_needs, login_keys),
                        "login_key": key in login_keys})
    keys = {"verdict": "ok" if not missing else f"{len(missing)} missing", "missing": missing}

    layer1 = []
    if live["verdict"] == "dead":
        layer1.append("the stand does not answer: " + live["note"])
    if unchecked_under_env:
        # An unknown stand is not a usable one: without --env `unchecked` stays a pass (the block names nothing to
        # ask - queued), with --env the person named a stand and a pass would confirm one nobody asked.
        layer1.append("the stand has no address: " + live["note"])
    if receipt["status"] == "failed":
        if receipt.get("refusal") == "body_shape":  # FB-3: the one-line fix FIRST, the why after it
            layer1.append(str(receipt.get("fix") or "") + " - " + receipt["why"])
        elif receipt.get("refusal") == "timeout":   # RN1-3: a login that did not finish is not a login the stand refused
            layer1.append("the login this project records did not finish in time: " + receipt["why"])
        else:
            layer1.append("the login this project records was refused: " + receipt["why"])
    if receipt["status"] != "ok":
        # With a proven login a missing key cannot be the login's own, whatever a stale
        # config lists: the story was stopped over exactly that contradiction once.
        for item in missing:
            if item["login_key"]:
                layer1.append(f"{item['key']} is not set, and the login needs it")

    state, note = data_cleanup(full_cfg, env_name)
    details.append(f"  data_cleanup: {state} ({note})")
    if state != "available":
        details.append("    -> design for it: every test creates its own data under a run-unique "
                       "tag and asserts only within that tag. No Then compares a global total "
                       "(TotalCount, list length, \"exactly one\"), and bulk data on this stand "
                       "is a decision for gate A, not a detail of a case.")
    return {"liveness": live, "login": receipt, "keys": keys, "layer1": layer1,
            "details": details, "source": source, "address_source": address_source}


def verdict_lines(result: dict) -> list:
    """The three lines, in the fixed order, each starting at column 0. Everything else the
    probe prints is indented, so a reader (and a digest) can take these three and nothing else."""
    live = result.get("liveness") or {}
    receipt = result.get("login") or {}
    keys = result.get("keys") or {}
    lines = [f"liveness: {live.get('verdict', 'unchecked')} — {live.get('note', '')}"]

    status = str(receipt.get("status") or "not_recorded")
    if status == "ok":
        head = f"ok as {receipt.get('user_key') or 'the recorded account'}"
    elif status == "failed" and receipt.get("code"):
        head = f"failed HTTP {receipt['code']}"
    else:
        head = status
    lines.append(f"login: {head} — {receipt.get('why', '')}")

    missing = keys.get("missing") or []
    where = f" (read from {result['source']})" if result.get("source") else ""
    if keys.get("verdict") == "unchecked":
        lines.append(f"keys: ok — not checked, {keys.get('why') or 'the env file was not found'}")
    elif not missing:
        lines.append("keys: ok — every key the config declares is set" + where)
    else:
        lines.append(f"keys: {len(missing)} missing — " + "; ".join(
            f"{item['key']}: needed by {item['needed_by']}" for item in missing) + where)
    return lines


def main() -> None:
    argv = sys.argv[1:]

    def option(name: str) -> str:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else ""

    env_name, task = option("--env"), option("--task")
    root = Path(option("--project-root")).resolve() if option("--project-root") else None
    obligation_ids = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--obligation"] or None
    full_cfg = (json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
                if root else load_config()) or {}
    cfg = full_cfg.get("environment") or {}
    declared = [cfg.get(k) for k in ("env_file", "base_url_key", "user_key", "health_url", "health_path")]
    # A named stand is judged by `probe`: one with an address of its own does not need the block, and one
    # without it ends as Layer 1 there (never as "not configured", never as a pass).
    if (not env_name and not any((x or "") for x in declared)
            and not (cfg.get("secret_keys") or cfg.get("extra_keys"))):
        print("ENVIRONMENT: not configured - the environment block in qa-factory/config.json is empty "
              "(onboarding fills it in: env_file or the process environment, base_url_key, user_key, "
              "secret_keys, health_path/health_url, access).\n"
              "While it is empty a role obtains the environment on its own - and that is a finding about "
              "the factory, not the norm: file it in qa-factory/factory-backlog.md.", file=sys.stderr)
        sys.exit(1)

    result = probe(full_cfg, env_name, task, root, obligation_ids, "--no-login" not in argv)
    if "--json" in argv:
        print(json.dumps({k: result[k] for k in ("liveness", "login", "keys", "layer1")}, indent=2))
        sys.exit(1 if result["layer1"] else 0)
    print("\n".join(result["details"] + verdict_lines(result)))
    sys.stdout.flush()  # the block of facts must land before the error output
    if result["layer1"]:
        print("\nTHE ENVIRONMENT CANNOT BE USED:\n- " + "\n- ".join(result["layer1"]) +
              "\nLayer 1 is these three lines only - a stand that does not answer, a login that was "
              "refused, or a key the login itself needs. A key nothing in this story reads is named "
              "above and blocks nothing.", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
