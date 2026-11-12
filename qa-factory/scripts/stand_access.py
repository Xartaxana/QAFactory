"""Log in to the stand the way THIS project logs in — the recorded scheme, never a guess.

Why. 23.09.2026, a second checkout of the same harness: every path of the stand answered
302 to an identity provider without a token, and the orchestrator reported "env_probe
(Layer 1) still failing ... HTTP 302 on all endpoints ... likely clears once the auth
credentials above are in place". Nothing in the factory had ever tried to log in, so the
sentence was a guess dressed as a diagnosis. A stand is three separate facts — is it
answering, did we get in, are the keys there — and only the second one needs a login recipe.

The recipe is a fact of the project, recorded at onboarding as `environment.access`:

    "access": {
      "kind": "harness_command" | "local_login" | "oidc_password" | "bearer_env" | "none",
      "command": "<shell command, for harness_command>",
      "url": "<login or token endpoint, or the NAME of the key that holds it>",
      "client_id_key": "", "realm_key": "", "user_key": "", "secret_key": "",
      "user_field": "" (local_login: the JSON body field the endpoint expects; empty = the probe tries the
                        pairs of references/login-body-fields.json in order and reports the accepted one),
      "secret_field": "" (local_login: likewise),
      "token_key": "<for bearer_env>", "unauth_status": [302, 401],
      "login_probe": {"user_key": "", "status": 200, "checked_at": "<ISO>",
                      "outcome": "ok|failed|skipped|not_recorded" (what the login came to; only `ok` is a proof - a
                                 record without it predates the field and is not confirmed),
                      "user_field": "" (optional), "secret_field": "" (optional),
                      "seconds": <float> (harness_command only: how long the ok login took; the ceiling of the next
                                 login is twice it, 60..300 s; absent = 300 s)}
                      (`env_probe.py --json` emits this object whole as `login.record`)
    }

Every value here is a key NAME or a URL. No value of a secret is read from config, printed,
or stored: the receipt this module returns carries the NAME of the user key and a status
code, which is what a person needs to tell "wrong account" from "wrong password" from
"the stand never asked".

An identity provider is one instance of `oidc_password`, not the design: a project that
issues its own token, or whose own harness knows how to log in, is served by the other
kinds. When the harness can log in by itself, the factory calls IT rather than
reimplementing a protocol it would get subtly wrong.
"""
from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

KINDS = ("harness_command", "local_login", "oidc_password", "bearer_env", "none")
NOT_RECORDED_WHY = "schema not recorded - onboarding gap"
# A login that answers with one of these carries a session we can prove. `data`/`result` are
# unwrapped one level: a wrapper object is the commonest shape after a bare token.
TOKEN_FIELDS = ("access_token", "accessToken", "token", "id_token", "idToken", "jwt")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# The data row of the shapes a 400/422 login answer names its complained body fields in (OH3-10, FR-13).
LOGIN_ERROR_SHAPES_PATH = Path(__file__).resolve().parents[1] / "references" / "login-error-shapes.json"
# A command login is a whole test-harness start-up, not one request: five seconds is the
# budget of an HTTP probe and would call a healthy harness broken.
COMMAND_MIN_TIMEOUT_S = 60.0
# RN1-3: the ceiling of the next harness login is twice the duration the onboarding recorded, kept inside [60, 300] s; with no
# usable record it is the declared default (300 s, half the host's 600 s call limit), never the floor - an 80 s harness is not "broken".
COMMAND_TIMEOUT_FACTOR = 2.0
COMMAND_MAX_TIMEOUT_S = 300.0
COMMAND_UNRECORDED_TIMEOUT_S = 300.0


def recorded_seconds(access):
    """`access.login_probe.seconds` when it is an int or float (not a bool), finite and > 0, else None. The ONE validity test of
    the field (AR-13): absent, 0, negative, a string, NaN, Infinity and a `login_probe` that is not an object are all None."""
    probe = access.get("login_probe") if isinstance(access, dict) else None
    value = probe.get("seconds") if isinstance(probe, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def command_timeout(access, timeout) -> float:
    """The ceiling, in seconds, of one harness-command login: twice the recorded duration (at least 60), 300 when none is
    recorded; the caller's `timeout` may raise it; the cap binds every input, so the result is always inside [60, 300]."""
    seconds = recorded_seconds(access)
    wanted = (COMMAND_UNRECORDED_TIMEOUT_S if seconds is None
              else max(COMMAND_MIN_TIMEOUT_S, COMMAND_TIMEOUT_FACTOR * seconds))
    return min(COMMAND_MAX_TIMEOUT_S, max(float(timeout), wanted))


def _safe(url: str) -> str:
    """A URL with the userinfo, query and fragment removed — the same rule `stand_health`
    prints by. A stand address routinely carries credentials in one of the three."""
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", "")) or "(no url)"
    except ValueError:
        return "(unprintable url)"


def _value(values: dict, key: str) -> str:
    return str((values or {}).get(str(key or ""), "") or "").strip()


def resolve_url(raw: str, values: dict, base_url: str = "") -> str:
    """A URL from config, from the key it names, or glued to the stand's address.

    `url` is allowed to be a key NAME because that is where a project usually keeps the
    address of its identity provider — the same place the harness reads it from, so the two
    can never drift apart."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(("http://", "https://")):
        return raw
    if ENV_NAME.match(raw):
        return _value(values, raw)
    if raw.startswith("/") and base_url:
        return base_url.rstrip("/") + raw
    return ""


def _open(url: str, method: str, data: bytes | None, headers: dict, timeout: float) -> tuple:
    """(code, body) of one request, redirects NOT followed. Raises when nothing answered.

    Mirrors `gate_preflight.http_get`: following a redirect lands on a login page and
    reports 200, which is the probe artifact that once recorded a healthy stand as dead.
    B-408: through the factory's one HTTP helper (its User-Agent), and the body of an ERROR answer is kept too
    (it used to be dropped), so a failed login can say what answered."""
    import http_client
    answer = http_client.fetch(url, method=method, data=data, headers=headers, timeout=timeout, max_body=262144)
    if answer.unreadable and 200 <= answer.status < 300:
        # a stalled body of a 2xx was always a timeout here (the login's `NO ANSWER (TimeoutError)`); the helper keeps the
        # status and says `unreadable`, so this caller keeps its old word by raising the same exception (B-408 F1)
        raise TimeoutError("the body of the answer did not arrive")
    return (answer.status, answer.body.decode("utf-8", errors="replace"))


def _who_answered(code, text: str, secrets: tuple, expect: str = "json") -> str:
    """` (the answer is ...)` when what came back is NOT shown to be the stand's own (a page, a JSON no known message
    key is in, a text), else ``. The body is classified with no headers - this seam carries none (E11) - so nobody is
    named as the author. The credential values this call used are redacted from what is said."""
    import http_client
    said = http_client.unattributed(code, str(text or ""), None, expect=expect, secrets=secrets)
    return f" (the answer: {said})" if said else ""


def token_value(body: str):
    """The session token a login answer carries, else None - the ONE walk of the answer (AR-13): the top object, then its
    `data` and `result` wrappers, each by the names of TOKEN_FIELDS in order. A caller that only needs to know whether
    there is one asks `_token_in`; a caller that signs in with it (the manual capture) takes the value, and the value
    never goes into a receipt, a message or a file."""
    try:
        parsed = json.loads(body or "")
    except ValueError:
        return None
    for node in (parsed, (parsed or {}).get("data") if isinstance(parsed, dict) else None,
                 (parsed or {}).get("result") if isinstance(parsed, dict) else None):
        if isinstance(node, dict):
            for name in TOKEN_FIELDS:
                value = str(node.get(name) or "").strip()
                if value:
                    return value
    return None


def _token_in(body: str) -> bool:
    """Whether the answer carries a session token - the same walk as `token_value`; nothing from the body is ever put
    into the receipt."""
    return token_value(body) is not None


def _receipt(status: str, why: str, code=None, user_key: str = "") -> dict:
    return {"status": status, "code": code, "user_key": str(user_key or ""), "why": why}


def _argv(command: str) -> list:
    """The command line as a list, the way `readiness.executable_of` reads one: split without
    POSIX escaping (a Windows path is full of backslashes) and then unquoted token by token."""
    try:
        parts = shlex.split(str(command or ""), posix=False)
    except ValueError:
        parts = str(command or "").split()
    return [p.strip('"').strip("'") for p in parts if p.strip()]


def _harness_command(access: dict, values: dict, timeout: float, cwd=None) -> dict:
    """The harness proves its own login: exit 0 and we are in.

    Its output is never shown. A login command routinely prints the token it just obtained,
    and this receipt travels into a role's context and from there into the transcript."""
    command = str(access.get("command") or "").strip()
    user_key = str(access.get("user_key") or "")
    if not command:
        return _receipt("not_recorded", "access.kind is harness_command but access.command is empty")
    argv = _argv(command)
    if not argv:
        return _receipt("not_recorded", "access.command is empty")
    child = dict(os.environ)
    child.update({k: v for k, v in (values or {}).items() if isinstance(v, str)})
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    ceiling = command_timeout(access, timeout)
    started = time.monotonic()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=child, cwd=str(cwd) if cwd else None,
                              timeout=ceiling)
    except FileNotFoundError:
        return _receipt("failed", f"`{argv[0]}` is not on PATH - access.command names a program "
                                  "this machine does not have")
    except subprocess.TimeoutExpired:
        seconds = recorded_seconds(access)
        if seconds is None:
            why = (f"`{argv[0]}` did not finish within {int(ceiling)}s (no login duration is recorded in "
                   "environment.access.login_probe.seconds; run the onboarding's login proof to record one)")
        else:
            why = (f"`{argv[0]}` did not finish within {int(ceiling)}s (the login took ~{int(round(seconds))}s when onboarding "
                   "recorded it; the ceiling is twice that, at least 60s and at most 300s)")
        receipt = _receipt("failed", why)
        receipt["refusal"] = "timeout"
        return receipt
    except OSError as exc:
        return _receipt("failed", f"`{argv[0]}` could not be run ({type(exc).__name__})")
    if done.returncode == 0:
        receipt = _receipt("ok", f"the project's own login command `{argv[0]}` exited 0", None, user_key)
        receipt["seconds"] = round(time.monotonic() - started, 1)   # only an ok login sets the next ceiling (RN1-3)
        return receipt
    return _receipt("failed", f"the project's own login command `{argv[0]}` exited "
                              f"{done.returncode}; its output is not shown here because a login "
                              "command prints tokens", None, user_key)


def _login_error_shapes() -> dict:
    """references/login-error-shapes.json - the data row of the shapes a 400/422 names its complained fields in. An
    unreadable or damaged file reads as no shapes: the receipt then says the status and names no field (FR-59)."""
    import hooklib  # the one JSON reader (AR-13); imported here like `http_client` below, so the module's import surface is unchanged
    return hooklib.read_json(LOGIN_ERROR_SHAPES_PATH, {}, kind=dict)


def _name_at(item, path) -> str:
    """The string at `path` (object keys) inside one list item; a list there yields its LAST string element (FastAPI's
    `loc` is [\"body\", \"email\"]). Empty when the item does not have that shape."""
    node = item
    for step in path:
        if not isinstance(node, dict) or not isinstance(step, str):
            return ""
        node = node.get(step)
    if isinstance(node, list):
        node = next((x for x in reversed(node) if isinstance(x, str)), "")
    return node if isinstance(node, str) else ""


def complained_fields(text: str, secrets: tuple = ()) -> list:
    """The body field NAMES a stand's 400/422 answer complains about, read through the shapes of
    references/login-error-shapes.json (OH3-10). NAMES only: a candidate must match the row's `name_pattern`, is not
    a place word (`body`, `query`), and contains none of the credential values this call used (a stand that echoed a
    value as a key would otherwise print it); at most the row's `max_names` come out, in the order the answer gave
    them. No other part of the answer is read out. Empty when the answer is not JSON or no shape in the row fits."""
    row = _login_error_shapes()
    limit, raw_pattern = row.get("max_names"), row.get("name_pattern")
    if not isinstance(raw_pattern, str) or not raw_pattern or not isinstance(limit, int) or isinstance(limit, bool) \
            or limit < 1:
        return []
    try:
        pattern = re.compile(raw_pattern)
    except re.error:
        return []
    try:
        parsed = json.loads(text or "")
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []
    candidates: list = []
    for shape in row.get("shapes") or []:
        if not isinstance(shape, dict):
            continue
        where, path = shape.get("list") or shape.get("map"), shape.get("name_at")
        node = parsed.get(where) if isinstance(where, str) else None
        if shape.get("kind") == "list_item_path" and isinstance(node, list) and isinstance(path, list):
            candidates.extend(_name_at(item, path) for item in node)
        elif shape.get("kind") == "key_names" and isinstance(node, dict):
            candidates.extend(str(key) for key in node)
    places = {str(p).lower() for p in row.get("not_fields") or []}
    held = [s.lower() for s in secrets if isinstance(s, str) and s]
    names: list = []
    for name in candidates:
        if (name and name not in names and pattern.match(name) and name.lower() not in places
                and not any(value in name.lower() for value in held)):
            names.append(name)
    return names[:limit]


# FB-3 / FB-5: the one line a body-shape refusal ends in. A constant with no slot, at most 155 characters: the gate's
# `missing` environment note is shown cut at 160 (gate_preflight.check_stand), and the fix is the FIRST thing in it.
LOGIN_FIELD_FIX = ("login field name unknown: write the body field names the login endpoint expects into "
                   "environment.access.user_field / secret_field (qa-factory/config.json)")


def shape_refused(code, text: str, secrets: tuple = (), sent: tuple = ()) -> bool:
    """Whether a login answer asks for a body field that was NOT sent - the ONE rule that moves a login to its next pair.
    True only for a 400/422 whose answer names (through `complained_fields`) at least one field outside `sent`
    (case-insensitive). Everything else is False: another code, no answer, an answer naming nothing, naming only
    fields that were sent (a wrong password or a throttle judged the account - it is never re-sent), non-JSON."""
    if code not in (400, 422):
        return False
    held = {str(name).lower() for name in sent}
    return any(name.lower() not in held for name in complained_fields(text, secrets))


def try_body_pairs(candidates, send, secrets: tuple = ()) -> list:
    """The ONE attempt loop of a body-field login (the probe and the manual capture both call it). For each (user field,
    secret field) in order `send(u, s)` returns (code, text) or raises; an exception is no answer and ends the loop. The
    loop goes on only while the answer is `shape_refused`. Returns the attempts; `text` is the caller's own and never
    goes into a receipt or a message."""
    attempts: list = []
    for u, s in candidates:
        try:
            code, text = send(u, s)
        except Exception as exc:
            attempts.append({"user_field": u, "secret_field": s, "code": None, "error": type(exc).__name__})
            break
        attempts.append({"user_field": u, "secret_field": s, "code": code, "text": text,
                         "complained": complained_fields(text, secrets) if code in (400, 422) else []})
        if not shape_refused(code, text, secrets, (u, s)):
            break
    return attempts


def ran_out_of_pairs(attempts: list, secrets: tuple = ()) -> bool:
    """Whether every pair of a `try_body_pairs` run was asked for other field names: the loop goes on only while the
    answer is shape-refused, so this is whether the LAST attempt was (an exception attempt never is)."""
    last = attempts[-1] if attempts else None
    return bool(last) and shape_refused(last["code"], last.get("text") or "", secrets,
                                        (last["user_field"], last["secret_field"]))


def _login_why(url: str, att: dict, secrets: tuple) -> tuple:
    """(status, why) of ONE attempt, the receipt texts of a single-body login."""
    code, text = att["code"], att.get("text") or ""
    if att.get("error"):
        return "failed", f"POST {_safe(url)} -> NO ANSWER ({att['error']})"
    if 200 <= code < 300 and _token_in(text):
        return "ok", f"POST {_safe(url)} -> HTTP {code} with a session token"
    if 200 <= code < 300:
        return "failed", (f"POST {_safe(url)} -> HTTP {code}, but the answer carries none of "
                          f"{', '.join(TOKEN_FIELDS[:3])} - the endpoint in access.url may not "
                          "be the login one" + _who_answered(code, text, secrets))
    door = ""
    if code in (400, 422):
        named = att["complained"]
        door = (f" - the endpoint rejected the body shape (sent the fields `{att['user_field']}` and "
                f"`{att['secret_field']}`)"
                + (f"; its answer complains about {', '.join(f'`{n}`' for n in named)}" if named else "")
                + "; `access.user_field` / `access.secret_field` in qa-factory/config.json name the fields it expects")
    return "failed", f"POST {_safe(url)} -> HTTP {code}" + door + _who_answered(code, text, secrets)


def _local_login(access: dict, values: dict, base_url: str, timeout: float) -> dict:
    """POST {<user_field>, <secret_field>} to the endpoint the project logs in through. The two field NAMES are
    data: recorded in `access` (one request), else the pairs of references/login-body-fields.json tried in order
    through `try_body_pairs` (FR-13, OH3-10, FB-3). The probe writes nothing; the accepted pair rides in the receipt."""
    from config_contract import body_field_candidates, body_field_errors, body_fields_recorded
    user_key = str(access.get("user_key") or "")
    secret_key = str(access.get("secret_key") or "")
    url = resolve_url(access.get("url"), values, base_url)
    if not url:
        return _receipt("not_recorded", "access.url does not resolve to a login endpoint", None, user_key)
    user, secret = _value(values, user_key), _value(values, secret_key)
    if not user or not secret:
        missing = " and ".join(k for k, v in ((user_key, user), (secret_key, secret)) if not v)
        return _receipt("skipped", f"{missing or 'the login key'} is not set, so nothing was tried",
                        None, user_key)
    refused = body_field_errors(access)
    if refused:
        # equal or malformed field names would send a body without the user while the login read `ok`: nothing is sent
        return _receipt("not_recorded", refused[0], None, user_key)
    secrets = (user, secret)

    def send(u: str, s: str) -> tuple:
        return _open(url, "POST", json.dumps({u: user, s: secret}).encode("utf-8"),
                     {"Content-Type": "application/json", "Accept": "application/json"}, timeout)

    attempts = try_body_pairs(body_field_candidates(access), send, secrets)
    last = attempts[-1]
    status, why = _login_why(url, last, secrets)
    receipt = _receipt(status, "".join(
        f"tried the body fields `{a['user_field']}` / `{a['secret_field']}` (HTTP {a['code']}); then "
        for a in attempts[:-1]) + why, last["code"], user_key)
    receipt["tried"] = [{k: a[k] for k in ("user_field", "secret_field", "code")} for a in attempts]
    receipt["fields_recorded"] = body_fields_recorded(access)
    if last["code"] in (400, 422):
        receipt["complained"] = list(last["complained"])
    if status == "ok":
        receipt["accepted_fields"] = {"user_field": last["user_field"], "secret_field": last["secret_field"]}
        if not receipt["fields_recorded"]:
            receipt["why"] += (f"; the body fields `{last['user_field']}` / `{last['secret_field']}` are not "
                               "recorded in environment.access (onboarding records them)")
    elif ran_out_of_pairs(attempts, secrets):
        receipt["refusal"], receipt["fix"] = "body_shape", LOGIN_FIELD_FIX
    return receipt


def _oidc_password(access: dict, values: dict, base_url: str, timeout: float) -> dict:
    """The password grant, for a project whose stand is fronted by an identity provider.

    `url` is the token endpoint. A realm key is honoured when the project keeps its realm
    separately (one provider's layout), and then the endpoint is composed the way that
    provider publishes it — but a project that simply records its token endpoint is served
    without the factory knowing whose provider it is."""
    user_key = str(access.get("user_key") or "")
    secret_key = str(access.get("secret_key") or "")
    base = resolve_url(access.get("url"), values, base_url)
    if not base:
        return _receipt("not_recorded", "access.url does not resolve to a token endpoint", None, user_key)
    realm = _value(values, access.get("realm_key")) if access.get("realm_key") else ""
    url = base
    if realm and "/token" not in base:
        url = base.rstrip("/") + f"/realms/{urllib.parse.quote(realm)}/protocol/openid-connect/token"
    client_id = _value(values, access.get("client_id_key")) if access.get("client_id_key") else ""
    user, secret = _value(values, user_key), _value(values, secret_key)
    if not user or not secret:
        missing = " and ".join(k for k, v in ((user_key, user), (secret_key, secret)) if not v)
        return _receipt("skipped", f"{missing or 'the login key'} is not set, so nothing was tried",
                        None, user_key)
    form = {"grant_type": "password", "username": user, "password": secret}
    if client_id:
        form["client_id"] = client_id
    data = urllib.parse.urlencode(form).encode("utf-8")
    try:
        code, text = _open(url, "POST", data,
                           {"Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "application/json"}, timeout)
    except Exception as exc:
        return _receipt("failed", f"POST {_safe(url)} -> NO ANSWER ({type(exc).__name__})",
                        None, user_key)
    if code == 200 and _token_in(text):
        return _receipt("ok", f"password grant at {_safe(url)} -> HTTP 200 with an access token",
                        code, user_key)
    if code == 200:
        return _receipt("failed", f"password grant at {_safe(url)} -> HTTP 200 without an "
                                  "access_token - access.url may not be the token endpoint"
                                  + _who_answered(code, text, (user, secret)), code, user_key)
    return _receipt("failed", f"password grant at {_safe(url)} -> HTTP {code}"
                    + _who_answered(code, text, (user, secret)), code, user_key)


def _bearer_env(access: dict, values: dict, base_url: str, health_url: str, timeout: float) -> dict:
    """A token the project already holds: the proof is that the stand accepts it."""
    token_key = str(access.get("token_key") or "")
    token = _value(values, token_key)
    url = resolve_url(access.get("url"), values, base_url) or health_url or base_url
    if not token_key:
        return _receipt("not_recorded", "access.kind is bearer_env but access.token_key is empty")
    if not token:
        return _receipt("skipped", f"{token_key} is not set, so nothing was tried", None, token_key)
    if not url:
        return _receipt("not_recorded", "there is no address to present the token to "
                                        "(access.url, health_path/health_url, base_url_key)",
                        None, token_key)
    try:
        code, text = _open(url, "GET", None, {"Authorization": f"Bearer {token}",
                                              "Accept": "application/json"}, timeout)
    except Exception as exc:
        return _receipt("failed", f"GET {_safe(url)} -> NO ANSWER ({type(exc).__name__})",
                        None, token_key)
    if 200 <= code < 300:
        return _receipt("ok", f"GET {_safe(url)} with the token in {token_key} -> HTTP {code}",
                        code, token_key)
    return _receipt("failed", f"GET {_safe(url)} with the token in {token_key} -> HTTP {code}"
                    + _who_answered(code, text, (token,), expect="any"), code, token_key)


def login(access, values: dict, base_url: str = "", timeout: float = 8.0,
          health_url: str = "", cwd=None) -> dict:
    """{"status", "code", "user_key", "why"} — did we get in, and how do we know.

    status: `ok` (we are in) · `failed` (the stand refused us) · `not_recorded` (this project
    never recorded how it logs in — an onboarding gap, never the person's fault) · `skipped`
    (the stand needs no login, or a key the login needs is not set, so nothing was tried).

    `user_key` is a NAME. Nothing this function returns contains a credential."""
    if not isinstance(access, dict) or not str(access.get("kind") or "").strip():
        return _receipt("not_recorded", NOT_RECORDED_WHY)
    kind = str(access.get("kind")).strip()
    if kind not in KINDS:
        return _receipt("not_recorded", f"access.kind `{kind}` is outside {' | '.join(KINDS)}")
    if kind == "none":
        return _receipt("skipped", "this stand needs no login (access.kind: none) - liveness is "
                                   "the whole answer")
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 8.0
    values = values if isinstance(values, dict) else {}
    if kind == "harness_command":
        return _harness_command(access, values, timeout, cwd)
    if kind == "local_login":
        return _local_login(access, values, base_url, timeout)
    if kind == "oidc_password":
        return _oidc_password(access, values, base_url, timeout)
    return _bearer_env(access, values, base_url, health_url, timeout)


def login_keys(access) -> list:
    """The key NAMES this project's login itself needs — the only keys whose absence stops a
    story. Everything else a config lists blocks an area at most, and saying otherwise is how
    one story halted on four keys no test in it ever read."""
    if not isinstance(access, dict):
        return []
    kind = str(access.get("kind") or "").strip()
    if kind == "none" or kind not in KINDS:
        return []
    fields = ("token_key",) if kind == "bearer_env" else ("user_key", "secret_key")
    return [str(access.get(f) or "").strip() for f in fields if str(access.get(f) or "").strip()]
