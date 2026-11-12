"""One outbound HTTP helper for the factory: a User-Agent that names the factory, the error body read, and an
answer classified by WHO wrote it (B-408).

Why. 06.10.2026, a colleague's machine behind the company's protection layer: every REST read of the tracker
answered 403 with an HTML page, the Jira client sent no User-Agent (urllib's own `Python-urllib/3.x` was all a
protection service could see), it never read the body of an error, and `auth_gate` took the 403 for a dead token:
the person was told to "renew the token" for a token that was fine. Four more places open an HTTP socket with the
same blind spots (`env_probe`, `gate_preflight`, `stand_access`, `manual_capture`).

The rule this module serves: the token is never declared lost on an answer the service has not been shown to
write. A classification may err toward `intermediary` or `unclear` (a stop that names what answered, the token
unjudged) and never toward "the service refused" (`service`) on an answer it has not been shown to write.

A library: standard library only, no CLI, prints nothing, writes nothing. The closed variety (which headers prove
an author, which only a path, which body keys are the service's own) lives in `references/http-answers.json`
(FR-13); the code reads it. A missing or unreadable table gives EMPTY tables and `verdict["table"] ==
"unreadable"`: fewer markers can only push an answer toward `intermediary`/`unclear`, the safe side.

Classification reads shapes and header names, never the words of a page title (FR-12); the title is only
shown, after cleaning, to a person who must be able to tell what answered.
"""
from __future__ import annotations

import codecs
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
ANSWERS_PATH = PACKAGE_ROOT / "references" / "http-answers.json"

# Kinds that are NOT the service speaking, or that say nothing about it. `auth_gate` and the callers that decide
# on a login read this tuple, so the safe side is spelled in one place.
FOREIGN_KINDS = ("intermediary", "unclear", "page")
KINDS = ("ok", "page", "redirect", "service", "intermediary", "unclear", "empty")

_UA_SAFE = re.compile(r"[^A-Za-z0-9._+-]")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_HTML_START_RE = re.compile(r"\s*(<!doctype\s+html|<html)", re.IGNORECASE)
_REDACTED = "<redacted>"
_SENTENCE_LIMIT = 300

_ua_cache: str | None = None
_table_cache: dict = {}


# ---- the User-Agent ----------------------------------------------------------------------------------------------

def user_agent() -> str:
    """`qa-factory/<version>`, the version of the installed package. Characters outside `[A-Za-z0-9._+-]` are
    dropped (the header must encode as latin-1); an unreadable or empty version is `unknown`. Cached per process.
    It never contains `python` or `urllib`: those are exactly what a protection service blocks on."""
    global _ua_cache
    if _ua_cache is None:
        version = ""
        try:
            import story_version
            version = str(story_version.installed_version() or "")
        except Exception:  # noqa: BLE001 - an unreadable manifest is `unknown`, never a failed request
            version = ""
        _ua_cache = "qa-factory/" + (_UA_SAFE.sub("", version) or "unknown")
    return _ua_cache


# ---- the closed variety --------------------------------------------------------------------------------------------

def _empty_tables() -> dict:
    return {"classify_limit_bytes": 65536, "title_limit_chars": 120, "service_auth_headers": [],
            "authorship_markers": [], "path_markers": [], "message_keys": [], "service_message_keys": {},
            "table": "unreadable"}


def tables() -> dict:
    """`references/http-answers.json`, read once per path. Absent or unreadable: empty tables (`table:
    "unreadable"`), never an exception - a classifier that raised would stop a read it was only asked to describe."""
    key = str(ANSWERS_PATH)
    if key not in _table_cache:
        loaded = _empty_tables()
        try:
            data = json.loads(Path(ANSWERS_PATH).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for name in ("service_auth_headers", "authorship_markers", "path_markers", "message_keys"):
                    if isinstance(data.get(name), list):
                        loaded[name] = [item for item in data[name] if isinstance(item, (dict, str))]
                if isinstance(data.get("service_message_keys"), dict):
                    loaded["service_message_keys"] = {str(k): [str(x) for x in v] for k, v in
                                                      data["service_message_keys"].items() if isinstance(v, list)}
                for name in ("classify_limit_bytes", "title_limit_chars"):
                    if isinstance(data.get(name), int) and data[name] > 0:
                        loaded[name] = data[name]
                loaded["table"] = "ok"
        except (OSError, ValueError):
            pass
        _table_cache[key] = loaded
    return _table_cache[key]


def reload_tables() -> None:
    """Forget what was read (a test points `ANSWERS_PATH` elsewhere)."""
    _table_cache.clear()


# ---- headers ---------------------------------------------------------------------------------------------------------

class Headers(list):
    """A list of `(name, value)` pairs with a case-insensitive `get`: what a response said, in order."""

    def get(self, name, default=None):
        wanted = str(name).lower()
        for key, value in self:
            if str(key).lower() == wanted:
                return value
        return default


def _pairs(headers):
    """`None` when the caller has no headers at all (the 2-tuple and int seams: nobody may be named as the author
    then, E11); else a `Headers` list from a dict, a list of pairs or an `email.message.Message`."""
    if headers is None:
        return None
    if isinstance(headers, Headers):
        return headers
    try:
        items = headers.items() if hasattr(headers, "items") else list(headers)
        return Headers((str(k), str(v)) for k, v in items)
    except (TypeError, ValueError):
        return Headers()


# ---- the answer -----------------------------------------------------------------------------------------------------

class Answer:
    """One finished exchange. `headers` is `Headers`; `location` is the safe form of a 3xx's `Location`."""

    def __init__(self, status, headers, body, truncated, unreadable, location, url, elapsed_s, verdict):
        self.status, self.headers, self.body = status, headers, body
        self.truncated, self.unreadable = truncated, unreadable
        self.location, self.url, self.elapsed_s, self.verdict = location, url, elapsed_s, verdict

    def __repr__(self):  # no body, no headers: nothing sensitive in a log line
        return f"Answer(status={self.status}, kind={self.verdict.get('kind')}, url={self.location or safe_url(self.url)})"


def safe_url(url) -> str:
    """The URL with the userinfo, query and fragment removed: a stand's address routinely carries a credential in
    one of the three, and the person is shown this form."""
    try:
        parts = urllib.parse.urlsplit(str(url))
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", "")) or "(no url)"
    except ValueError:
        return "(unprintable url)"


def curl_line(url) -> str:
    """The check a person can run from this machine, OUTSIDE the factory: a GET (the factory's own method) that
    prints the status and the content type, to the safe form of the address. No credential is in it, ever.
    `curl.exe` on Windows (PowerShell's `curl` is another program), `curl` elsewhere."""
    if sys.platform == "win32":
        return f'curl.exe -sS -o NUL -w "%{{http_code}} %{{content_type}}\\n" {safe_url(url)}'
    return f'curl -sS -o /dev/null -w "%{{http_code}} %{{content_type}}\\n" {safe_url(url)}'


# ---- reading ---------------------------------------------------------------------------------------------------------

def read_error(exc, limit: int) -> tuple:
    """`(bytes, unreadable)`: the body of an `HTTPError`, at most `limit` bytes, or `(b"", True)` when the read
    itself raised. An empty body that READ fine is `(b"", False)`: the two are different facts and only the second
    may be taken for "nobody wrote anything" (E14)."""
    try:
        data = exc.read(int(limit))
        return (bytes(data or b""), False)
    except Exception:  # noqa: BLE001 - any failure of the read is "could not read", not a crash of the caller
        return (b"", True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is the answer: following it lands on an identity provider's page and reports 200 (the probe artifact
    that once recorded a healthy stand as dead)."""

    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, *, method="GET", data=None, headers=None, timeout, max_body: int = 1048576, ssl_context=None,
          expect="any", service="any", secrets=()) -> Answer:
    """One request, redirects NOT followed, the User-Agent added unless the caller set one (any case), the body
    read on any status up to `max_body` (one more byte is read to know whether it was cut: `truncated`).
    urllib's own proxy handling is kept. Its timeout and connection exceptions are re-raised UNCHANGED, so every
    existing `except` keeps catching what it caught. No retries here: the caller owns its policy."""
    if timeout is None or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("fetch needs a positive timeout in seconds; got " + repr(timeout))
    if max_body is None or int(max_body) < 0:
        raise ValueError("fetch needs max_body >= 0 bytes; got " + repr(max_body))
    max_body = int(max_body)
    sent = dict(headers or {})
    if not any(str(name).lower() == "user-agent" for name in sent):
        sent["User-Agent"] = user_agent()
    handlers = [_NoRedirect]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, data=data, method=method, headers=sent)
    started = time.perf_counter()
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return error_answer(exc, url, max_body=max_body, expect=expect, service=service, secrets=secrets,
                            started=started)
    unreadable = False
    try:
        raw = response.read(max_body + 1)
    except TimeoutError:
        # The status and headers ARRIVED and the body did not: on EVERY status that is `unreadable`, never a raised
        # timeout that would turn a stand that answered into "no answer" (B-408 F1: env_probe called a 200 with a
        # stalled body dead). A caller that must treat a stalled body as a timeout reads the flag.
        raw, unreadable = b"", True
    return _finish(int(response.getcode()), response, raw, unreadable, url, started, max_body, expect, service, secrets)


def error_answer(exc, url, *, max_body: int = 65536, expect="any", service="any", secrets=(), started=None) -> Answer:
    """The `Answer` of an `HTTPError`: ONE construction path for every caller, `fetch` and the Jira client alike (B-408
    F2). The body is read up to `max_body` plus ONE byte so `truncated` means exactly "more than `max_body` bytes";
    a read that fails is `unreadable` (the status is kept)."""
    raw, unreadable = read_error(exc, int(max_body) + 1)
    return _finish(int(exc.code), exc, raw, unreadable, url, started, int(max_body), expect, service, secrets)


def _finish(status, response, raw, unreadable, url, started, max_body, expect, service, secrets) -> Answer:
    pairs = _pairs(getattr(response, "headers", None))      # None = no headers at all (nobody may be named, E11)
    try:
        response.close()
    except Exception:  # noqa: BLE001
        pass
    truncated = len(raw) > max_body
    body = raw[:max_body]
    location = None
    if pairs is not None and 300 <= status < 400 and pairs.get("Location"):
        location = safe_url(urllib.parse.urljoin(str(url), str(pairs.get("Location"))))
    verdict = classify(status, pairs, body, truncated=truncated, unreadable=unreadable, expect=expect,
                       service=service, secrets=secrets)
    return Answer(status, pairs if pairs is not None else Headers(), body, truncated, unreadable, location, str(url),
                  (time.perf_counter() - started) if started is not None else 0.0, verdict)


# ---- classification --------------------------------------------------------------------------------------------------

def _redact(text, secrets) -> str:
    text = str(text or "")
    for secret in secrets or ():
        secret = str(secret or "")
        if secret:
            text = text.replace(secret, _REDACTED)
    return text


def _clean_title(raw, limit: int, secrets) -> str | None:
    """Entities unescaped, control bytes removed, whitespace collapsed, at most `limit` characters plus "...": no raw
    HTML and no control byte reaches a person (E18)."""
    text = " ".join(_CONTROL_RE.sub(" ", html.unescape(str(raw or ""))).split())
    text = _redact(text, secrets)
    if not text:
        return None
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _header_marker_hit(pairs, marker) -> bool:
    value = pairs.get(str(marker.get("name") or ""))
    if value is None:
        return False
    equals = marker.get("equals")
    return equals is None or str(value).strip().lower() == str(equals).strip().lower()


def _service_denied(pairs, status: int, table: dict) -> bool:
    """Rule 3: a header the SERVICE (not a CDN) sets when it refuses a login."""
    for item in table["service_auth_headers"]:
        if not isinstance(item, dict):
            continue
        value = pairs.get(str(item.get("name") or ""))
        if value is None:
            continue
        if "statuses" in item:
            if status in item["statuses"]:
                return True
            continue
        allowed = {str(x).strip().upper() for x in (item.get("denied_unless") or [])}
        if str(value).strip().upper() not in allowed:
            return True
    return False


def _who(pairs, markers) -> str | None:
    for marker in markers:
        if isinstance(marker, dict) and _header_marker_hit(pairs, marker):
            return str(marker.get("who") or "").strip() or None
    return None


def _decode_prefix(prefix: bytes, cut: bool):
    """The prefix as text, or None when it is not UTF-8. A prefix CUT by the classification limit may end inside a
    multi-byte character: that is not "not UTF-8" (the incremental decoder holds the tail back)."""
    try:
        return codecs.getincrementaldecoder("utf-8-sig")().decode(prefix, final=not cut)
    except UnicodeDecodeError:
        return None


def _message_present(parsed, keys) -> bool:
    if not isinstance(parsed, dict):
        return False
    for key in keys:
        value = parsed.get(key)
        if value is None or value is False:
            continue
        if isinstance(value, (str, list, dict)) and not value:
            continue
        return True
    return False


def classify(status, headers, body, *, truncated=False, unreadable=False, expect="any", service="any",
             secrets=()) -> dict:
    """`{kind, said, title, via, auth_denied, table}`: who wrote this answer, by SHAPE, applying the rules in
    order (the first that holds decides):

    1. 2xx: `page` when `expect="json"` and the body is HTML; else `ok`.
    2. 3xx: `redirect`.
    3. headers known and a service-auth header signals denial (the table): `service`, `auth_denied` True.
    4. headers known and an authorship marker present: `intermediary`.
    5. unreadable (the read failed, `Content-Encoding` other than identity, a prefix that is not UTF-8): `unclear`.
    6. JSON (an object or a list): a message under the keys of `service` -> `service`; none -> `unclear`.
    7. HTML: headers known -> `intermediary`; headers unknown -> `unclear`.
    8. empty body: `empty`.
    9. other text: 401 -> `service` (when not cut); anything else -> `unclear`.

    `headers=None` means none are available (nobody may then be NAMED as the author). The error direction is
    toward `intermediary`/`unclear`: "the service refused" is only ever said on a shape the service writes."""
    table = tables()
    pairs = _pairs(headers)
    status = int(status) if isinstance(status, int) else 0
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    body = bytes(body or b"")
    limit = int(table["classify_limit_bytes"])
    prefix = body[:limit]
    cut = bool(truncated) or len(body) > limit
    text = _decode_prefix(prefix, cut)
    verdict = {"kind": "unclear", "said": "", "title": None, "via": None, "auth_denied": False,
               "table": table["table"]}

    def done(kind, said="", title=None, via=None, auth_denied=False):
        verdict.update(kind=kind, said=said, title=title, via=via, auth_denied=auth_denied)
        return verdict

    looks_html = False
    if text is not None:
        content_type = str((pairs.get("Content-Type") if pairs is not None else "") or "").lower()
        # A Content-Type with NOTHING behind it is an empty body, not a page (E7): a lost login whose 401 has no
        # body must stay `empty` however its Content-Type reads.
        looks_html = bool(_HTML_START_RE.match(text)) or (
            bool(text.strip()) and pairs is not None and (content_type.startswith("text/html")
                                                          or content_type.startswith("application/xhtml+xml")))
    title = None
    if looks_html and text is not None:
        found = _TITLE_RE.search(text)
        title = _clean_title(found.group(1), int(table["title_limit_chars"]), secrets) if found else None
    html_said = f'an HTML page titled "{title}"' if title else "an HTML page"

    if 200 <= status < 300:
        if expect == "json" and looks_html:
            return done("page", html_said, title)
        return done("ok")
    if 300 <= status < 400:
        return done("redirect", "a redirect")
    if pairs is not None and _service_denied(pairs, status, table):
        return done("service", "the service's own refusal of the login", auth_denied=True)
    if pairs is not None:
        who = _who(pairs, table["authorship_markers"])
        if who:
            via = who
            if looks_html:
                return done("intermediary", html_said, title, via)
            return done("intermediary", "an answer carrying " + who + "'s marks", None, via)
    encoding = str((pairs.get("Content-Encoding") if pairs is not None else "") or "").strip().lower()
    if unreadable or (encoding and encoding != "identity") or text is None:
        return done("unclear", "a body that could not be read")
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            keys = table["service_message_keys"].get(service) if service != "any" else None
            if keys is None:
                keys = [k for k in table["message_keys"] if isinstance(k, str)]
            if _message_present(parsed, keys):
                return done("service", "JSON with the service's message")
            return done("unclear", "JSON with no message of the service's own")
    if looks_html:
        if pairs is None:
            return done("unclear", html_said, title)
        via = _who(pairs, table["path_markers"])
        return done("intermediary", html_said, title, via)
    if not stripped:
        return done("empty", "an empty body")
    if status == 401 and not cut:
        return done("service", "a text body")
    return done("unclear", "a text body")


def describe(status, verdict, *, with_status: bool = True) -> str:
    """One bounded sentence for a person: what answered, in the factory's words. It asserts an author only where
    the classification had a header to stand on (FR-41); `unclear` and `page` say they could not tell.
    `with_status=False` leaves out the leading `HTTP <status>, ` for a caller that already printed it."""
    verdict = verdict or {}
    kind, said, via = verdict.get("kind"), str(verdict.get("said") or ""), verdict.get("via")
    if kind == "service":
        text = "written by the service itself"
    elif kind == "intermediary":
        text = (f"{said}, which did not come from the service itself"
                + (f" (the path shows {via})" if via else ""))
    elif kind == "page":
        text = f"{said} where the service's data was expected"
    elif kind == "empty":
        text = "an empty body"
    elif kind == "redirect":
        text = "a redirect that was not followed"
    elif kind == "ok":
        text = "as expected"
    else:
        text = f"{said or 'a body'}; whether the service wrote it could not be told"
    if with_status:
        text = (f"HTTP {status}, " if status else "an answer, ") + text
    text = " ".join(text.split())
    return text if len(text) <= _SENTENCE_LIMIT else text[:_SENTENCE_LIMIT - 3].rstrip() + "..."


def unattributed(status, body, headers=None, *, expect="any", secrets=()) -> str:
    """For a caller that holds only a status and a body text (the 2-tuple seams of `stand_access` and
    `gate_preflight`): a bounded description of what answered when it is NOT shown to be the service's own - a page,
    a text the service is not shown to have written, an answer that could not be told - else ``. A JSON body no known
    message key is in is the service's own shape of an answer this table does not know: nothing is said about it.
    With no `headers` nobody is named as the author (E11)."""
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    verdict = classify(status, headers, body, expect=expect, secrets=secrets)
    if verdict["kind"] not in ("unclear", "page", "intermediary"):
        return ""
    if verdict["kind"] == "unclear" and bytes(body or b"").lstrip()[:1] in (b"{", b"["):
        return ""
    return describe(status, verdict, with_status=False)


def is_foreign(verdict) -> bool:
    """True when the answer is NOT shown to be the service's own (`intermediary`, `unclear`, `page`)."""
    return bool(verdict) and verdict.get("kind") in FOREIGN_KINDS
