"""Canonical requirement-source inventory and direct Jira original collector.

The inventory is the mutable source registry.  Original ticket snapshots and attachment
bytes are immutable evidence addressed from it; credentials are environment references
and are never persisted or included in errors.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import http_client
import person_words
import ticket_light as TL

VALID_RELATIONS = {"task", "subject", "parent", "normative", "referenced"}
VALID_RELEVANCE = {"pending", "relevant", "not_relevant", "unknown"}
VALID_STATUS = {"pending", "read", "unavailable", "excluded"}
# One key shape for the whole factory (t-267 C11): ticket_light.KEY_RE, uppercase only, the whole key
# is one candidate (`MY_PROJ-12` never yields `PROJ-12`). Group 1 is the key, as it always was.
TICKET_KEY_RE = TL.KEY_RE


def runtime_credential_values(config: dict | None = None, root: Path | None = None,
                              environ: dict | None = None) -> dict:
    """The process environment, with every name it lacks filled from the configured env file(s).

    A direct tracker read runs in its own Python process and used to look at the process
    environment only, while `env_probe` also read `environment.env_file`: a project that kept
    its tracker token there was told "credentials missing" by the reader that needed it, and
    the person had to export the token in every shell.

    Precedence: a NON-EMPTY process value always wins; an empty one counts as missing. Files:
    `environment.env_file` first, then `environment.env_files` in order, the first file that
    holds a non-empty value for a name wins; paths are relative to the project root. An absent
    or unreadable file is skipped silently and no config means the process environment alone.
    The values travel to the caller only - nothing here prints, logs or persists them.
    `env_probe.load_env` merges the other way round (file over process) - left as is, see the
    node's report."""
    values = dict(os.environ if environ is None else environ)
    try:
        if config is None or root is None:
            from hooklib import load_config, project_root
            config = load_config() if config is None else config
            root = project_root() if root is None else root
        environment = (config or {}).get("environment") or {}
        declared = []
        primary = str(environment.get("env_file") or "").strip()
        if primary:
            declared.append(primary)
        listed = environment.get("env_files")
        if isinstance(listed, list):
            declared.extend(str(item).strip() for item in listed if str(item or "").strip())
        if not declared:
            return values
        from env_probe import parse_env_file
    except Exception:  # a config this reader cannot resolve is "no env file", not a failure
        return values
    for rel in declared:
        try:
            path = Path(root) / rel
            if not path.is_file():
                continue
            found = parse_env_file(path)
        except Exception:  # unreadable file: skipped, the process environment still stands
            continue
        for key, value in found.items():
            if value and not values.get(key):
                values[key] = value
    return values


def conflicting_task_source(sources: list[dict], relation: str, canonical_ref: str) -> dict | None:
    """One story has one task source: TP1-15045 collected its parent and its
    normative predecessor with the unexamined default `--relation task`, and S2's register
    then carried two "the task" sources. `None` when `relation` is not `task`, or this ticket
    already IS the recorded task source (a re-collect, not a second one)."""
    if relation != "task":
        return None
    return next((item for item in sources if item.get("relation") == "task"
                and item.get("canonical_ref") != canonical_ref), None)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_ticket(instance: str, key: str) -> str:
    return f"{instance.rstrip('/').lower()}/browse/{key.upper()}"


def stable_source_id(instance: str, canonical_ref: str) -> str:
    raw = f"{instance.rstrip('/').lower()}\n{canonical_ref}".encode("utf-8")
    return "SRC-" + hashlib.sha256(raw).hexdigest()[:20]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(value or "attachment").name).strip(".-")
    return (value or "attachment")[:120]


def _atomic_write(path: Path, data: bytes) -> None:
    # Reserve space for the atomic temporary filename on legacy Windows paths.
    if os.name == "nt" and len(str(path.resolve()).encode("utf-16-le")) // 2 > 240:
        raise OSError("source storage path exceeds Windows budget; shorten the project root")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        pending = Path(handle.name)
    try:
        pending.replace(path)
    finally:
        if pending.exists():
            pending.unlink()


def _text(value) -> str:
    """Flatten Jira v3 ADF without interpreting embedded instructions. LEGACY, no caller in the ticket
    route since t-267 (ticket_light.text_of keeps the list markers this drops): kept because
    test_ticket_light.py holds it as the negative control of why the markers matter."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        own = str(value.get("text") or "")
        children = _text(value.get("content") or [])
        return "\n".join(filter(None, (own, children)))
    return str(value)


# Text that has the shape of a tracker key and is not one. TP1-15045 "mentioned" UTF-8,
# ISO-8601 and LICENSE-2, and every such token became a required source somebody had to
# assess. Project-local plan ids (BE-1, FE-2) cannot be listed; `peek` settles those: the
# tracker answers 404 and the record is left out with that as its reason.
# The list is DATA (FR-13): references/jira-fields.json `not_tracker_prefixes`. The constant stays
# for importers that read it, as the loader's result; a damaged table leaves it EMPTY here and is
# REFUSED, naming the file, by every call that decides with it (`not_tracker_prefixes()`) - an empty
# list that silently let UTF-8 become a required source would be the failure the list exists for.
def not_tracker_prefixes() -> set:
    return set(TL.load_fields_table()["not_tracker_prefixes"])


try:
    NOT_TRACKER_PREFIXES = not_tracker_prefixes()
except TL.TableError:
    NOT_TRACKER_PREFIXES = set()

# The reference-kinds table, loaded ONCE by the loader every other caller uses (t-280: the extractor
# below and the `/browse/KEY` finder `_BROWSE_KEY_RE` both read it). A damaged table leaves it None here
# and is REFUSED, naming the file, by `reference_kinds()` at the call that needs it - never read as "no
# kinds", which would let a tracker link be swallowed.
try:
    _REFERENCE_KINDS = TL.load_reference_kinds()
except TL.TableError:
    _REFERENCE_KINDS = None


def reference_kinds() -> dict:
    return _REFERENCE_KINDS if _REFERENCE_KINDS is not None else TL.load_reference_kinds()
# Link targets an HTML/SVG export is made of: namespaces, licence texts, library homepages.
_NOISE_URL_RE = re.compile(r"^https?://(www\.)?(w3\.org|apache\.org/licenses|opensource\.org|"
                           r"creativecommons\.org|schemas\.[a-z.]+|cdn\.|cdnjs\.|unpkg\.com|"
                           r"fonts\.(googleapis|gstatic)\.com)", re.IGNORECASE)
# Attachments a person wrote are mined for keys and links; machine exports are not.
_HUMAN_TEXT_SUFFIXES = {".md", ".txt"}


def extract_ticket_keys(*values: str) -> list[str]:
    """The ticket keys the texts carry, sorted and unique. ONE extractor with the references of S0
    (t-280, FR-17): this delegates to `ticket_light.references`, which classifies and CONSUMES URLs, local
    paths and merge-request forms BEFORE it reads keys - so `https://host/browse/ABC-7` yields ABC-7 from the
    link row's own key, and a key inside another link's path (`https://host/x/ABC-9/doc`) is not a key. A
    prefix on the table's not-tracker list is skipped, from every source of a key. A table that cannot be
    read refuses (TableError, naming the file)."""
    skip = not_tracker_prefixes()
    rows = TL.references({f"text-{number}": value for number, value in enumerate(values)},
                         known_prefixes=(), not_tracker_prefixes=skip, reference_kinds=reference_kinds(),
                         known_hosts=(), repos=())
    keys = {row.get("key") or row["ref"] for row in rows if row.get("kind") == "ticket"}
    return sorted(key for key in keys if key.rsplit("-", 1)[0] not in skip)


def extract_media_urls(*values) -> list[str]:
    found: set[str] = set()
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"url", "href", "src"} and isinstance(child, str) and child.startswith(("http://", "https://")):
                    found.add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            found.update(re.findall(r"https?://[^\s<>()\]\[\"']+", value))
    for value in values:
        visit(value)
    return sorted(url for url in found if not _NOISE_URL_RE.match(url))


class FetchError(RuntimeError):
    def __init__(self, status: int | None, reason: str, retryable: bool = False,
                 retry_at: str | None = None, login_page: bool = False, answer=None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.retryable = retryable
        self.retry_at = retry_at
        # A 200 that is a login page: no status code says so, and the reader of this error must not
        # have to match the reason's words (FR-12). Set only where the response was recognised.
        self.login_page = login_page
        # B-408: the answer the failure came with (`http_client.Answer`, its `verdict` says WHO wrote it), or None
        # where no HTTP answer was read (a timeout, a missing credential, a redirect refusal). The gate reads the
        # verdict, never the reason's words (FR-12): an answer the service is not shown to have written is no
        # evidence about the token.
        self.answer = answer


class MissingCredential(FetchError):
    """No request was made: an environment variable that holds the token (or the user name) is not set in this
    process (t-287 item 3). Still a FetchError - a WRITE (`post_json`) reads it as it always did - and carries the
    NAMES of the variables, never a value. A READ (`get_bytes`) turns it into `AuthLost`: the person's shell lacks the
    variable, which is neither the tracker's fault nor a question about the ticket."""

    def __init__(self, names: list):
        super().__init__(None, "missing credential environment reference(s): " + ", ".join(names))
        self.names = list(names)


class AuthLost(Exception):
    """The tracker stopped accepting this run's credentials (t-267 C4/C5).

    NOT a FetchError, and not a RuntimeError, on purpose: every `except FetchError` of this module
    turns a failed read into an `unavailable` or a not-found row, and a dead token must never become
    N such rows (TP1-13877: a login error went to the person as a question about a call no role
    had made). It propagates to the command, which prints `str(exc)` as ONE line and exits with the
    infrastructure code the driver turns into `InfraStop:auth`. `status` is the HTTP code of the
    refused call (None for a login page), `door` names the environment variable to renew,
    `stopped_at` what was being read."""

    # Whose stop this is, as the adapter's error object names it (`ticket_adapter.OWNERS`): the login's (`auth`) or,
    # for `Intercepted`, something between this machine and the tracker (`intermediary`).
    cause = "auth"

    def __init__(self, message: str, *, status: int | None = None, door: str = "", stopped_at: str = ""):
        super().__init__(message)
        self.status = status
        self.door = door
        self.stopped_at = stopped_at


class Intercepted(AuthLost):
    """An answer the tracker is not shown to have written stopped the run (B-408), and the login check says nothing
    about the token either: a firewall, a proxy or a protection service answered, or the answer could not be read.
    It IS an `AuthLost` on purpose - the same one-line stop, exit 5, nothing after it attempted or booked as not
    found - but its owner is `intermediary` and its sentence never says the token was refused or must be renewed:
    the token was not judged."""
    cause = "intermediary"


ERROR_BODY_LIMIT = 65536      # an error body is read up to this, always bounded (B-408 E5)


def _http_reason(status: int, answer) -> str:
    """The reason of a failed HTTP call: `HTTP <status>` when the body was readable and empty (the lost-login
    controls K8b/K10 are about exactly that answer), else `HTTP <status>: <what answered>` in the factory's own words.
    Never the raw body: a page is not text for a person (human-questions.md)."""
    verdict = getattr(answer, "verdict", None) or {}
    if answer is None or verdict.get("kind") == "empty":
        return f"HTTP {status}"
    return f"HTTP {status}: " + http_client.describe(status, verdict, with_status=False)


def _foreign(exc) -> bool:
    """The answer this failure carried is NOT shown to be the tracker's own (a firewall's or a protection service's
    page, a JSON no Jira field is in, a body that could not be read). An error with no answer is not foreign."""
    answer = getattr(exc, "answer", None)
    return answer is not None and http_client.is_foreign(answer.verdict)


LOGIN_REDIRECT_REASON = ("redirected to another host, which is how a lost login looks when the tracker sits "
                         "behind single sign-on (read as a login page)")


def _other_host(url: str, own_host) -> bool:
    """Is the host of `url` another host than the tracker's? A URL with no host (a relative `Location`)
    is the same host; an unreadable URL is not called another host (the caller then treats it as it did
    before). t-280 F9: an SSO redirect to an identity provider is a LOGIN PAGE, not a network fault."""
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError:
        return False
    return bool(host) and host.lower() != str(own_host or "").lower()


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # a `Location` with no host is relative to the request: the same host (urllib joins it already;
        # this keeps the rule true for a caller that does not)
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        target = urllib.parse.urlsplit(newurl)
        target_origin = (target.scheme.lower(), target.hostname, target.port)
        if target_origin != self.origin:
            # Another HOST is a login page (the SSO redirect, t-280 F9); the same host on another scheme
            # or port keeps the old refusal. A same-host redirect (`/browse/X` -> `/jira/browse/X`) never
            # gets here: it is followed, and it is not auth.
            if _other_host(newurl, self.origin[1]):
                raise FetchError(None, LOGIN_REDIRECT_REASON, retryable=False, login_page=True)
            raise FetchError(None, "cross-origin Jira redirect refused", retryable=False)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class JiraClient:
    def __init__(self, base_url: str, username_ref: str, secret_ref: str, auth_type: str = "basic_token",
                 api_version: str = "2", acceptance_criteria_fields: list[str] | None = None,
                 opener: Callable | None = None, sleeper: Callable = time.sleep,
                 project_keys: list[str] | None = None, custom_fields=None, acceptance_headings=None,
                 attachment_policy=None, telemetry_path=None, telemetry_task: str | None = None,
                 config: dict | None = None, root: Path | None = None):
        # `config`/`root` only say WHERE a missing credential may be looked up (the project's
        # `environment` env file); left None they are resolved from the project when needed.
        self._config = config
        self._root = root
        self.base_url = base_url.rstrip("/")
        self.username_ref = username_ref
        self.secret_ref = secret_ref
        self.auth_type = auth_type
        self.api_version = str(api_version)
        self.acceptance_criteria_fields = list(acceptance_criteria_fields or [])
        # t-267: the three config keys of the light form, kept AS GIVEN - a wrong shape is refused where
        # it is used (ticket_light / attachment_policy_for), by the key's own name, never reshaped here
        # (list("customfield_1") would quietly become eleven field ids).
        # direct_api.custom_fields, direct_api.acceptance_headings, adapters.ticket.attachments
        self.custom_fields = custom_fields if custom_fields is not None else []
        self.acceptance_headings = acceptance_headings if acceptance_headings is not None else []
        self.attachment_config = attachment_policy if attachment_policy is not None else {}
        # Every REST call is a `command` span (K10) when a path is named; the CLI names it. Fail-silent.
        self.telemetry_path = telemetry_path
        self.telemetry_task = telemetry_task
        # The project's repositories and known hosts, for the references (set by the CLI from config).
        self.references_context: dict = {}
        # What this process has seen of the login (C5): the first ticket it read (a resource that is
        # known to exist, so a re-GET of it tells a lost login from a real 404), whether a probe
        # already said the login works, and the refusal that stopped it (nothing is asked after one).
        self.proof_key: str | None = None
        self.auth_ok = False
        self.auth_lost: "AuthLost | None" = None
        # B-408: the first answer this process met that the tracker is not shown to have written is checked once
        # against the login (the probe); the word is kept, so a protection layer that blocks every path costs one
        # probe, not one per row (E20).
        self.foreign_probed = False
        self.foreign_word: str | None = None
        # The optional reads this process could not make and said so (t-280 F8): `[{call, status, why}]`.
        self.reads_skipped: list = []
        # A project this run is already told about costs no probe at all: the
        # instance's own local-numbering projects, or ones onboarding already knows are noise.
        self.project_keys = sorted({str(p).strip().upper() for p in (project_keys or []) if str(p).strip()})
        origin = urllib.parse.urlsplit(self.base_url)
        self._origin = (origin.scheme.lower(), origin.hostname, origin.port)
        self.opener = opener or urllib.request.build_opener(_SameOriginRedirect(self._origin)).open
        self.sleeper = sleeper

    def _headers(self) -> dict[str, str]:
        if self.auth_type not in {"basic_token", "bearer"}:
            raise FetchError(None, f"unsupported Jira auth_type: {self.auth_type}")
        username = os.environ.get(self.username_ref, "") if self.username_ref else ""
        token = os.environ.get(self.secret_ref, "")
        if not token or (self.auth_type == "basic_token" and not username):
            # Only a name the process lacks sends us to the configured env file; a healthy
            # process environment costs no config read and no file read.
            values = runtime_credential_values(self._config, self._root)
            username = values.get(self.username_ref, "") if self.username_ref else ""
            token = values.get(self.secret_ref, "")
        if not token or (self.auth_type == "basic_token" and not username):
            pairs = [(self.secret_ref, token)]
            if self.auth_type == "basic_token":
                pairs.append((self.username_ref, username))
            missing = [name for name, value in pairs if not value]
            raise MissingCredential(missing)
        if self.auth_type == "bearer":
            return {"Accept": "application/json", "Authorization": "Bearer " + token,
                    "User-Agent": http_client.user_agent()}
        encoded = base64.b64encode(f"{username}:{token}".encode()).decode("ascii")
        return {"Accept": "application/json", "Authorization": "Basic " + encoded,
                "User-Agent": http_client.user_agent()}

    def _secret_values(self) -> tuple:
        """The credential values of this process, for redaction only (the names are in the config, the values never
        leave the environment)."""
        return tuple(v for v in (os.environ.get(self.secret_ref, "") if self.secret_ref else "",
                                 os.environ.get(self.username_ref, "") if self.username_ref else "") if v)

    def get_bytes(self, url: str, accept: str = "application/octet-stream") -> bytes:
        """One GET, as the retry policy below makes it, as one `command` span when the CLI named a
        telemetry file. A login the run has already lost is never tried again (C5: nothing later is
        attempted)."""
        if self.auth_lost is not None:
            raise self.auth_lost
        try:
            self._headers()
        except MissingCredential as exc:
            # t-287 item 3: before any request - nothing is sent, no span is written, and nothing later is tried.
            # The sentence names the VARIABLES (never a value) and no "network or VPN": the shell lacks them.
            names = exc.names
            many = len(names) > 1
            raise AuthLost(
                f"the environment variable{'s' if many else ''} {' and '.join(names)} "
                f"{'are' if many else 'is'} not set in this shell, so no token can be sent to the tracker: set "
                f"{'them' if many else 'it'} (and make sure the shell you run this from has "
                f"{'them' if many else 'it'}) and run the same command again - no request was made and nothing was "
                "recorded as not found.",
                status=None, door=", ".join(names), stopped_at="the first request") from None
        except FetchError:
            pass                    # another header fault (an unsupported auth_type) keeps its old way: `_get_bytes` raises it
        path = getattr(self, "telemetry_path", None)
        span = None
        if path:
            try:
                from telemetry_capture import Span
                span = Span(path, span_kind="command", source="plugin:ticket_adapter.py",
                            task=getattr(self, "telemetry_task", None), reason_code="jira_rest_read")
            except Exception:  # noqa: BLE001 - telemetry is fail-silent: it never fails a read
                span = None
        if span is None:
            return self._get_bytes(url, accept)
        with span:
            data = self._get_bytes(url, accept)
            span.bytes = len(data)
            return data

    def _get_bytes(self, url: str, accept: str = "application/octet-stream") -> bytes:
        target = urllib.parse.urlsplit(url)
        if (target.scheme.lower(), target.hostname, target.port) != self._origin:
            raise FetchError(None, "cross-origin Jira content URL refused", retryable=False)
        delays = (5, 15)
        for attempt in range(3):
            request = urllib.request.Request(url, headers={**self._headers(), "Accept": accept})
            try:
                response = self.opener(request, timeout=60)
                final_url = response.geturl() if hasattr(response, "geturl") else url
                final = urllib.parse.urlsplit(final_url)
                if (final.scheme.lower(), final.hostname, final.port) != self._origin:
                    # a 200 that ended on another host is the identity provider's page (t-280 F9)
                    if _other_host(final_url, self._origin[1]):
                        raise FetchError(None, LOGIN_REDIRECT_REASON, retryable=False, login_page=True)
                    raise FetchError(None, "cross-origin Jira redirect refused", retryable=False)
                data = response.read()
                content_type = str(response.headers.get("Content-Type") or "") if getattr(response, "headers", None) else ""
                headers = response.headers if getattr(response, "headers", None) else {}
                login_reason = str(headers.get("X-Seraph-LoginReason") or "").strip().upper()
                denied_reason = str(headers.get("X-Authentication-Denied-Reason") or "").strip()
                final_path = final.path.lower()
                explicit_login_path = any(marker in final_path for marker in ("/login.jsp", "/signin", "/sso/login"))
                if content_type.lower().startswith("text/html") and (
                        login_reason not in {"", "OK"} or denied_reason or explicit_login_path):
                    raise FetchError(None, "HTML login response refused", retryable=False, login_page=True)
                return data
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                if 300 <= status < 400:
                    # A redirect the opener did not follow. Its `Location` on another host is the SSO
                    # login page (t-280 F9 -> auth_gate -> the probe -> InfraStop:auth), never a network
                    # fault; on the same host, or with no host at all (a relative `Location`), it stays the
                    # ordinary failure it was.
                    location = exc.headers.get("Location") if exc.headers else None
                    if location and _other_host(urllib.parse.urljoin(url, str(location)), self._origin[1]):
                        raise FetchError(None, LOGIN_REDIRECT_REASON, retryable=False, login_page=True) from None
                retryable = status == 429 or 500 <= status <= 599
                # B-408: the body is read (bounded) and the answer is told apart by WHO wrote it, so the gate can
                # tell the tracker's own refusal from a page a firewall or a protection service put in its place.
                # The retry policy below is unchanged; only the FINAL error carries the answer (E30).
                answer = http_client.error_answer(exc, url, max_body=ERROR_BODY_LIMIT, service="jira",
                                                  secrets=self._secret_values())
                if not retryable or attempt == 2:
                    raise FetchError(status, _http_reason(status, answer), retryable=retryable,
                                     answer=answer) from None
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and retry_after.isdigit() and int(retry_after) > 15:
                    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=int(retry_after))).isoformat().replace("+00:00", "Z")
                    raise FetchError(status, "server requested delayed retry", retryable=True,
                                     retry_at=retry_at, answer=answer) from None
                delay = int(retry_after) if retry_after and retry_after.isdigit() else delays[attempt]
                self.sleeper(delay)
            except (TimeoutError, urllib.error.URLError):
                if attempt == 2:
                    raise FetchError(None, "network timeout", retryable=True) from None
                self.sleeper(delays[attempt])
        raise FetchError(None, "request failed", retryable=True)

    def get_json_with_raw(self, path_or_url: str) -> tuple:
        """`(parsed, the response bytes exactly as they came)`: the raw folder keeps what the tracker
        said, and a hash over it must be a hash of those bytes (t-267 C8), not of a re-serialisation."""
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        raw = self.get_bytes(url, "application/json")
        try:
            return json.loads(raw.decode("utf-8")), raw
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError(None, "Jira JSON response was not valid JSON", retryable=False) from exc

    def get_json(self, path_or_url: str) -> dict:
        return self.get_json_with_raw(path_or_url)[0]

    def post_json(self, path_or_url: str, body: dict) -> dict:
        """The one write verb this client knows — added for `external_writes.py`'s
        `adapters.ticket.direct_api` delivery. Deliberately NOT `get_bytes`'s retry
        loop: a POST that timed out may already have created the issue, and retrying it blind
        risks a duplicate the caller never asked for — one attempt, one answer, the tracker's
        own error message surfaced on failure so the caller can report it and stop, exactly
        the "never retried blindly" rule external_writes.py already keeps for its `command`
        channel. Every other verb (PUT/DELETE) is out of scope: this build creates issues and
        adds comments, nothing that mutates or removes what a human already entered."""
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        target = urllib.parse.urlsplit(url)
        if (target.scheme.lower(), target.hostname, target.port) != self._origin:
            raise FetchError(None, "cross-origin Jira write URL refused", retryable=False)
        data = json.dumps(body).encode("utf-8")
        headers = {**self._headers(), "Accept": "application/json",
                   "Content-Type": "application/json"}
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            response = self.opener(request, timeout=60)
            raw = response.read()
        except urllib.error.HTTPError as exc:
            answer = http_client.error_answer(exc, url, max_body=ERROR_BODY_LIMIT, service="jira",
                                              secrets=self._secret_values())
            detail = answer.body.decode("utf-8", "replace").strip()
            # Jira's own validation error, e.g. {"errorMessages": [...], "errors": {...}} -
            # surfaced verbatim (trimmed) so the person sees what the tracker actually said,
            # never a bare "HTTP 400". B-408: only a JSON body carrying one of Jira's own keys is relayed so; a page
            # (a firewall's HTML, a text) is DESCRIBED, never relayed raw - a raw page is not text for a person
            # (human-questions.md), and 500 characters of markup said nothing about who wrote it.
            verdict = answer.verdict
            own_json = verdict.get("kind") == "service" and detail[:1] in ("{", "[")
            if own_json:
                reason = f"HTTP {exc.code}: {detail[:500]}"
            else:
                reason = _http_reason(int(exc.code), answer)
            raise FetchError(int(exc.code), reason, retryable=False, answer=answer) from None
        except (TimeoutError, urllib.error.URLError) as exc:
            raise FetchError(None, f"network error: {exc}", retryable=False) from None
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def issue_with_raw(self, key: str) -> tuple:
        """The issue with EVERY field on the wire (`fields=*all`, t-267 F1: the bytes cost no LLM
        tokens, and an acceptance criterion in a custom field nobody configured is never lost; what a
        role sees is decided by the projection, not by what is asked for). The first ticket read
        becomes this process's proof that the login works (`proof_key`)."""
        issue, raw = self.get_json_with_raw(f"/rest/api/{self.api_version}/issue/{urllib.parse.quote(key)}?fields=*all")
        if self.proof_key is None:
            self.proof_key = key
        return issue, raw

    def issue(self, key: str) -> dict:
        return self.issue_with_raw(key)[0]

    def all_comments(self, key: str, embedded: dict | None = None, raw_sink: list | None = None) -> list[dict]:
        """Every comment of the ticket. Comments the issue embeds come free; the rest by pages of 100.
        `raw_sink`, when a list, receives each FETCHED page's bytes verbatim, for the raw folder."""
        page = embedded or {}
        comments = list(page.get("comments") or [])
        total = int(page.get("total") or len(comments))
        start = int(page.get("startAt") or 0) + len(comments)
        while start < total:
            page, raw = self.get_json_with_raw(f"/rest/api/{self.api_version}/issue/{urllib.parse.quote(key)}/comment?startAt={start}&maxResults=100")
            if raw_sink is not None:
                raw_sink.append(raw)
            batch = list(page.get("comments") or [])
            if not batch:
                raise FetchError(None, "comment pagination returned an empty page", retryable=False)
            comments.extend(batch)
            start += len(batch)
            total = int(page.get("total") or total)
        return comments


def _revision(issue: dict) -> str:
    fields = issue.get("fields") or {}
    return str(fields.get("updated") or issue.get("version") or "unknown")


AC_HEADING_RE = re.compile(r"(?im)^\s*(?:h[1-6]\.\s*|#{1,6}\s*|\*{0,2})acceptance\s+criteria\**\s*:?\s*$")
NEXT_HEADING_RE = re.compile(r"(?im)^\s*(?:h[1-6]\.\s+\S|#{1,6}\s+\S)")
AC_ITEM_RE = re.compile(r"^\s*(?:[*\-#•]+|\d+[.)])\s+(.+?)\s*$")


def acceptance_criteria_from_description(description: str) -> list[str]:
    """LEGACY, no caller in the ticket route since t-267: `ticket_light.acceptance_criteria` finds the
    criteria now (headings from data, wiki `# ` lists, ADF lists, the glue of the next section).
    Kept only because test_ticket_light.py (K1 negative (ii)) holds that THIS function gave `[]` on the
    TP1-15045 description - the proof of why the parser was replaced. Its line split is
    ticket_light's (C7: `splitlines()` also cuts at U+2028 and U+0085).

    The criteria of a ticket whose AC live in its description, as most Jira instances keep
    them: a heading `h2. Acceptance Criteria` (wiki markup), `## Acceptance Criteria` or a bold
    line, then bullets or a numbered list, up to the next heading. Standard Jira, no field to
    configure: TP1-13797 carried 13 criteria this way and an empty AC field."""
    text = description or ""
    m = AC_HEADING_RE.search(text)
    if not m:
        return []
    rest = text[m.end():]
    n = NEXT_HEADING_RE.search(rest)
    block = rest[:n.start()] if n else rest
    items = []
    for line in TL.split_lines(block):
        im = AC_ITEM_RE.match(line)
        if im:
            items.append(im.group(1).strip())
        elif items and line.strip() and not line.startswith((" ", "\t")):
            # a wrapped continuation of the previous bullet
            items[-1] = items[-1] + " " + line.strip()
    return items


# ---- a lost login is not a missing ticket (t-267 C4/C5) ------------------------------------------
# Jira answers 404 for "no permission" too, and a token that expired mid-run turns the next answers
# into 401, 403, a login page or a CAPTCHA 403. Booked as "unavailable" or "not found", one dead token
# became fifty rows and a question to the person about nothing they had done. So a failure that COULD
# be a lost login is checked once, by a re-GET of something this run already read; a lost login stops
# the run with ONE refusal and nothing after it is attempted or written as not-found.

def _auth_stop_door(client) -> str:
    return client.secret_ref or "the token environment variable"


def mark_auth_stop(output, *, stopped_at: str, status, door: str, cause: str = "auth") -> None:
    """The inventory says where the run stopped (`auth_stop`), so the next reader of it knows the
    sources after that point were never tried, not that they do not exist. The next successful read
    removes the mark (`update_inventory`). `cause` (B-408, additive) says whose stop it was: `auth` the login's,
    `intermediary` an answer the tracker is not shown to have written. Fail-soft: the refusal itself is what
    matters."""
    if not output:
        return
    try:
        _set_top_level(Path(output), auth_stop={"stopped_at": stopped_at, "status": status, "door": door,
                                                "cause": cause, "at": utc_now()})
    except (OSError, ValueError):
        pass


def _probe(client: "JiraClient", output=None) -> tuple:
    """`(word, the probe's own FetchError or None)`; the words are `ok | lost | unavailable | intercepted`.

    `ok` needs a 200 whose body parses as JSON (E13: the login counts as working only on the service's own JSON).
    `lost` needs the probe's own answer to be the service's - `service`, `empty` or a login page (an answer with no
    classification, a stand-in's FetchError, keeps the old reading by its status). A foreign probe answer (a page,
    a JSON no Jira field is in, an unreadable body) or a 200 that is not JSON is `intercepted`: the token is not
    judged. Anything else (429, 5xx, a timeout) is `unavailable`."""
    key = client.proof_key or _proof_key_of(output)
    path = (f"/rest/api/{client.api_version}/issue/{urllib.parse.quote(key)}?fields=updated" if key
            else f"/rest/api/{client.api_version}/myself")
    try:
        data = client.get_bytes(client.base_url + path, "application/json")
    except FetchError as exc:
        if _foreign(exc):
            return "intercepted", exc
        if exc.status in (401, 403, 404) or exc.login_page:
            return "lost", exc
        return "unavailable", exc
    try:
        json.loads((data or b"").decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "intercepted", None
    return "ok", None


def auth_probe(client: "JiraClient", output=None) -> str:
    """`ok` - the login still works; `lost` - it does not; `unavailable` - the probe itself could not be
    answered (429, 5xx, a timeout), so nothing is known and nothing may be booked as not-found; `intercepted` -
    what answered is not shown to be the tracker (B-408), so the login is neither confirmed nor refused.

    The probe re-GETs a resource this run has ALREADY read (`?fields=updated` on the first ticket
    read, in this process or, from the inventory, in an earlier one): it exists, so any answer but 200
    is about the login. `/myself` only before any read has succeeded - a token scoped narrowly may refuse
    it, which is why it is the last resort (estimate, not measured). A 404 on the already-read ticket is
    read as lost: Jira shows a ticket the token may no longer see as 404."""
    return _probe(client, output)[0]


def auth_gate(client: "JiraClient", exc: FetchError, output, *, what: str, prefix_proven: bool = False) -> str | None:
    """Call from an `except FetchError` BEFORE the failure is booked as anything. Returns None when the
    failure is not one that could be a lost login (the caller handles it as before); `ok` when it
    could and the probe says the login works (book a not-found / no-permission row); `unavailable`
    when the probe could not tell (book unavailable, retryable). Raises AuthLost, after marking the
    inventory, when the login is lost.

    Trigger: 401, 403, a login page, or a 404 on a ticket whose project prefix is PROVEN in this run.
    A 401 and a login page are unambiguous - they always probe again. A 403 and a 404 are ordinary
    answers for a ticket one may not see, so once the probe has said `ok` they are not re-probed
    (fifty not-found keys must not cost fifty probes); a later 401 or login page still is.

    B-408: an answer the tracker is not SHOWN to have written (`_foreign`: a page from a firewall or a protection
    service, a JSON no Jira field is in, a body that could not be read) is never "lost" by itself and is never
    `hard`: it is checked BEFORE the hard/soft reading and never takes the `auth_ok` shortcut (a protection layer that
    starts blocking after the login was proven would otherwise book every later key as `unavailable` and never
    stop). The first foreign answer of a process probes once (`client.foreign_probed`, `client.foreign_word`), later
    ones reuse that word: at most one foreign probe per process. `intercepted` raises `Intercepted` (exit 5, owner
    `intermediary`, the token not judged); `ok` makes the row `unavailable`, retryable, with the classified reason;
    `lost` stays `AuthLost`, citing the probe's own answer - a real lost login behind a firewall is still reported.

    Only the real client has a login to probe: a stand-in that serves tickets from a table (the tests
    of the stages after S1) gets None and is called as it always was."""
    if not isinstance(client, JiraClient):
        return None
    foreign = _foreign(exc)
    hard = (exc.status == 401 or exc.login_page) and not foreign
    soft = exc.status == 403 or (exc.status == 404 and prefix_proven) or (foreign and exc.status == 401)
    if not hard and not soft:
        return None
    probe_exc = None
    if foreign:
        if client.foreign_probed:
            verdict = client.foreign_word or "unavailable"
        else:
            verdict, probe_exc = _probe(client, output)
            client.foreign_probed, client.foreign_word = True, verdict
    else:
        if soft and client.auth_ok:
            return "ok"
        verdict, probe_exc = _probe(client, output)
    if verdict == "ok":
        client.auth_ok = True
        if foreign:
            exc.retryable = True        # a block of THIS path is not a fact about the ticket: asked again, not booked as gone
        return "ok"
    if verdict == "unavailable":
        client.auth_ok = False
        return "unavailable"
    client.auth_ok = False
    door = _auth_stop_door(client)
    if verdict == "intercepted":
        seen = next((e.answer for e in (exc, probe_exc) if e is not None and _foreign(e)), None)
        said = (http_client.describe(seen.status, seen.verdict) if seen is not None
                else "a 200 that is not the tracker's JSON")
        lost = Intercepted(
            f"the tracker could not be read while reading {what}: {said}; the token was not judged - check the "
            "tracker's address from this machine outside the factory, then run the same command again; nothing "
            "after this point was attempted and nothing was recorded as not found.",
            status=exc.status, door=door, stopped_at=what)
        client.auth_lost = lost
        mark_auth_stop(output, stopped_at=what, status=exc.status, door=door, cause=Intercepted.cause)
        raise lost
    cited = probe_exc if (foreign and probe_exc is not None) else exc
    shown = ("a login page" if cited.login_page else f"HTTP {cited.status}")
    if cited is not exc:
        shown += f" on the login check that followed HTTP {exc.status}"
    lost = AuthLost(
        f"Jira stopped accepting the token ({shown} while reading {what}): renew the token held in the "
        f"environment variable {door} and run the same command again - nothing after this point was "
        "attempted and nothing was recorded as not found.",
        status=cited.status, door=door, stopped_at=what)
    client.auth_lost = lost
    mark_auth_stop(output, stopped_at=what, status=cited.status, door=door)
    raise lost


def _gated(client, output, what: str, call: Callable, *, prefix_proven: bool = False):
    """`call()`, and a failure that could be a lost login goes through `auth_gate` first; the verdict
    rides on the re-raised FetchError (`auth_verdict`) for the caller that books it."""
    try:
        return call()
    except FetchError as exc:
        exc.auth_verdict = auth_gate(client, exc, output, what=what, prefix_proven=prefix_proven)
        raise


def _issue_and_raw(client, key: str) -> tuple:
    """`(issue, the response bytes)`. A client that can only hand over the parsed issue (a stand-in) has
    no verbatim bytes; the raw is then the issue re-serialised, which still says what was read."""
    method = getattr(client, "issue_with_raw", None)
    if method is not None:
        return method(key)
    issue = client.issue(key)
    return issue, json.dumps(issue, ensure_ascii=False).encode("utf-8")


def _all_comments(client, key: str, embedded: dict, pages: list) -> list:
    if hasattr(client, "get_json_with_raw"):
        return client.all_comments(key, embedded, raw_sink=pages)
    return client.all_comments(key, embedded)


def _proof_key_of(output) -> str | None:
    """The first ticket an earlier process of this run read, from the inventory: a source `read`, else
    the `proof_key` S0 seeded."""
    if not output:
        return None
    try:
        inventory = json.loads(Path(output).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for item in inventory.get("sources") or []:
        if isinstance(item, dict) and item.get("status") == "read":
            ref_key = str(item.get("canonical_ref") or "").rsplit("/browse/", 1)[-1]
            if ref_key:
                return ref_key
    proof = inventory.get("proof_key")
    return str(proof) if isinstance(proof, str) and proof else None


# ---- what the run learns once and S1 reuses (t-267 C3) ----------------------------------------------

def _read_inventory_file(output) -> dict:
    if output and Path(output).exists():
        try:
            data = json.loads(Path(output).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {"schema_version": 1, "sources": []}


def _set_top_level(output, **values) -> None:
    """Merge top-level keys into the inventory file, keeping every source and every other key:
    `update_inventory` rewrites {schema_version, sources} and keeps what else it finds, and this is
    the one writer of those other keys (`prefix_probes`, `field_ids`, `proof_key`, `auth_stop`)."""
    output = Path(output)
    inventory = _read_inventory_file(output)
    inventory.setdefault("schema_version", 1)
    inventory.setdefault("sources", [])
    for name, value in values.items():
        if value is None:
            inventory.pop(name, None)
        else:
            inventory[name] = value
    _atomic_write(output, json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")


def persisted_epic_fields(output) -> list[str]:
    """The Epic Link field ids S0 stored (`field_ids.epic_link`); `[]` when S0 stored none - S1 never
    asks `/field` itself (no second `/field` per story)."""
    ids = (_read_inventory_file(output).get("field_ids") or {}).get("epic_link")
    return [str(x) for x in ids] if isinstance(ids, list) else []


# ---- an optional read that was NOT made is said, not swallowed (t-280 F8, FR-41) ----------------------
# `/remotelink` and `/field` are optional by nature: the ticket is read without them. But a 503 after the
# retries, a timeout or a 404 on the endpoint turned into `[]` / "no fields" with nothing recorded, so
# "this ticket has no remote links" and "the remote links were not read" looked the same. Now the
# inventory carries `reads_skipped` ([] when nothing was skipped - FR-23) and the S1 brief says it. A lost
# login never gets here: `auth_gate` raised AuthLost first and stops the run (C4/C5).
SKIPPED_CALLS = ("/remotelink", "/field")


def skip_why(exc) -> str:
    """One sentence for a failed optional read: what the tracker said, in words, no secret in it."""
    if isinstance(exc, FetchError):
        if exc.retry_at:
            return f"the tracker answered HTTP {exc.status} and asked to retry later (not before {exc.retry_at})"
        if exc.status is not None:
            return f"the tracker answered HTTP {exc.status}" + (" on every attempt" if exc.retryable else "")
        return (f"{exc.reason} on every attempt" if exc.retryable else str(exc.reason)).replace("\n", " ")
    return f"the read failed ({exc.__class__.__name__})"


def book_read_skipped(client, output, call: str, exc) -> dict:
    """Record that `call` (`/remotelink` or `/field`) was not read: on the client, so the S0 write of the
    inventory carries it, and at once in `output` (the inventory) when one is named. One entry per call:
    a second failure of the same call replaces the first. Fail-soft on the write - the read is optional,
    the record is best effort and the S0 write repeats it."""
    status = getattr(exc, "status", None)
    entry = {"call": call, "status": status if isinstance(status, int) and not isinstance(status, bool) else None,
             "why": skip_why(exc)}
    booked = [row for row in (getattr(client, "reads_skipped", None) or []) if row.get("call") != call] + [entry]
    client.reads_skipped = booked
    if output:
        try:
            _set_top_level(Path(output), reads_skipped=booked)
        except (OSError, ValueError):
            pass
    return entry


def stored_epic_fields(output):
    """The Epic Link ids an earlier S0 stored, or None when none were stored (a list, even an empty one,
    is a stored catalogue; a missing or malformed `field_ids` is not)."""
    stored = _read_inventory_file(output).get("field_ids") if output else None
    ids = stored.get("epic_link") if isinstance(stored, dict) else None
    return [str(x) for x in ids] if isinstance(ids, list) else None


def fetch_field_catalog(client: "JiraClient", output=None, raw_parts: dict | None = None) -> dict:
    """`/field`, once per process (cached on the client): `{"epic_link": [ids of the fields named Epic
    Link / Parent Link], "ids": {every field id the instance has} | None, "unavailable": reason | None,
    "from_store": bool}`. Classic Jira projects keep the epic in a custom field, not in `parent`; the name is
    standard, the id is per instance. A lost login raises; any other failure leaves `ids` None - the check
    of the configured fields then cannot be made, and says so by that. And it is BOOKED (t-280 F8,
    `reads_skipped`): "the field catalogue was not read" must not look like "the instance has no fields" -
    unless an earlier S0 stored the Epic Link ids (`field_ids`): those are used and nothing is booked, the
    read the earlier S0 made still holds (K11, temporal)."""
    cached = getattr(client, "_field_catalog", None)
    if cached is not None:
        return cached
    catalog = {"epic_link": [], "ids": None, "unavailable": None, "from_store": False}
    try:
        rows, raw = _gated(client, output, "the list of fields (/field)",
                           lambda: client.get_json_with_raw(f"/rest/api/{client.api_version}/field"))
        if raw_parts is not None:
            raw_parts["field.json"] = raw
        ids, epic = set(), []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            ids.add(str(row["id"]))
            if str(row.get("name") or "").strip().lower() in {"epic link", "parent link", "epic"}:
                epic.append(str(row["id"]))
        catalog.update(epic_link=epic, ids=ids)
    except AuthLost:
        raise
    except Exception as exc:  # noqa: BLE001 - a field list that cannot be read costs the epic parent and the check, not the ticket
        stored = stored_epic_fields(output)
        if stored is not None:
            catalog.update(epic_link=stored, from_store=True)
        else:
            catalog["unavailable"] = getattr(exc, "reason", None) or exc.__class__.__name__
            book_read_skipped(client, output, "/field", exc)
    client._field_catalog = catalog
    return catalog


def epic_link_field_ids(client) -> list[str]:
    return fetch_field_catalog(client)["epic_link"]


# ---- the light snapshot (t-267): ticket_light.project over the RAW issue -------------------------------

def _extra_headings(client) -> list:
    extra = getattr(client, "acceptance_headings", [])
    if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
        raise TL.TableError("direct_api.acceptance_headings must be a list of strings, got "
                            f"{type(extra).__name__}; fix it in qa-factory/config.json (or remove it: the "
                            "headings of references/jira-fields.json are used)")
    return extra


def light_snapshot(client: "JiraClient", issue: dict, comments: list, *, table: dict | None = None,
                   epic_fields=(), remote_links=None, raw: bytes | None = None) -> dict:
    """The light form of one raw issue for a role: the whitelist applied in the PROJECTION (what the
    wire carried is kept whole beside it). Custom fields: only the ids the project named
    (`direct_api.custom_fields`, `direct_api.acceptance_criteria_fields`) and the epic link fields. The
    caller passes EVERY comment; `raw`, the response bytes, puts bytes and sha256 into the provenance
    (by code, from the route - never from what a pasted file says)."""
    table = table or TL.load_fields_table()
    headings = list(table["acceptance_headings"])
    headings += [h for h in _extra_headings(client) if h.strip().casefold() not in {x.casefold() for x in headings}]
    shaped = dict(issue)
    shaped["fields"] = dict(issue.get("fields") or {}, comment={"comments": list(comments)})
    snapshot = TL.project(shaped, fields_table=table, config_custom_fields=getattr(client, "custom_fields", []),
                          acceptance_fields=getattr(client, "acceptance_criteria_fields", []),
                          acceptance_headings=headings,
                          section_names=table["section_names"], epic_fields=epic_fields,
                          remote_links=remote_links)
    if raw is not None:
        snapshot["provenance"] = {"source": "fetched", "fields_requested": "*all", "bytes": len(raw),
                                  "sha256": sha256_bytes(raw)}
    return snapshot


def _remote_links(client: "JiraClient", key: str, output, raw_parts: dict | None) -> list:
    """`/remotelink` of the ticket, raw. Optional by nature (a ticket with no remote links answers `[]`; an
    instance that refuses the call costs the MR links, not the ticket) - but a lost login is never
    swallowed here, and the raw answer is kept whole."""
    try:
        rows, raw = _gated(client, output, f"the remote links of {key}",
                           lambda: client.get_json_with_raw(
                               f"/rest/api/{client.api_version}/issue/{urllib.parse.quote(key)}/remotelink"))
        if raw_parts is not None:
            raw_parts["remotelink.json"] = raw
        return rows if isinstance(rows, list) else []
    except AuthLost:
        raise
    except Exception as exc:  # noqa: BLE001 - the ticket is read without its remote links, but never silently
        book_read_skipped(client, output, "/remotelink", exc)
        return []


def jira_ticket(client: JiraClient, key: str, raw_dir=None, *, say: Callable | None = None,
                context: dict | None = None) -> dict:
    """The ticket by REST, in the light form (D-06: the tracker agent is not a data source).

    One GET of the issue with every field (`fields=*all`), the comment pages the issue did not embed,
    `/field` (once) and `/remotelink` - so on a ticket whose comments are all embedded the read costs
    three requests. The last two are optional: one that could not be read (not a lost login - that stops
    the run) is booked in the inventory's `reads_skipped` and the S1 brief says so (t-280 F8). The snapshot is `ticket_light.project` over the raw issue; provenance is set HERE,
    from the route taken: `{source: fetched, fetched_at, fields_requested: "*all", bytes, sha256}`, the
    hash over the verbatim response bytes.

    With `raw_dir` (S0: `work/ticket-raw`) it also leaves, in that folder, EVERY response as it came
    (`issue.json`, `field.json`, `remotelink.json`, `comments-<n>.json`) and a pretty-printed copy of the
    issue (`issue.pretty.json`: `big_read_check` refuses whole reads over the read limit (`big_read_cap`) and a one-line
    JSON cannot be sliced), beside it in `work/` the role-facing line view `ticket-view.md` and the
    references `ticket-references.json`, and seeds `work/source-inventory.json` with what S1 reuses
    (`field_ids`, `prefix_probes`, `proof_key`) so S1 asks neither `/field` nor a project it already knows.

    `say(line)` receives the one-line notes (a configured field the instance does not have, a
    description over the size limit). `context`: `{"repos": [...], "known_hosts": [...]}` from the
    project's config, for the references. A table of the light form that is missing or empty REFUSES
    (TL.TableError, naming the file) before any request is made."""
    say = say or (lambda line: None)
    table = TL.load_fields_table()
    kinds = TL.load_reference_kinds() if raw_dir else None
    work = Path(raw_dir).parent if raw_dir else None
    inventory_path = (work / "source-inventory.json") if work else None
    proven = key.rsplit("-", 1)[0].upper() in set(client.project_keys)
    issue, issue_raw = _gated(client, inventory_path, f"the ticket {key}",
                              lambda: client.issue_with_raw(key), prefix_proven=proven)
    fields = issue.get("fields") or {}
    raw_parts = {"issue.json": issue_raw}
    pages: list = []
    comments = _gated(client, inventory_path, f"the comments of {key}",
                      lambda: client.all_comments(key, fields.get("comment") or {}, raw_sink=pages))
    for number, page in enumerate(pages, 1):
        raw_parts[f"comments-{number}.json"] = page
    catalog = fetch_field_catalog(client, inventory_path, raw_parts)
    # this call reads /remotelink afresh: an entry an earlier read of this client booked is not this read's
    client.reads_skipped = [row for row in (getattr(client, "reads_skipped", None) or [])
                            if row.get("call") != "/remotelink"]
    remote_links = _remote_links(client, key, inventory_path, raw_parts)
    snapshot = light_snapshot(client, issue, comments, table=table, epic_fields=catalog["epic_link"],
                              remote_links=remote_links, raw=issue_raw)
    snapshot["provenance"]["fetched_at"] = utc_now()
    named = list(dict.fromkeys(list(client.custom_fields) + list(client.acceptance_criteria_fields)))
    if catalog["ids"] is not None:
        gone = [fid for fid in named if fid not in catalog["ids"]]
        if gone:
            snapshot["provenance"]["fields_missing"] = gone
            say(f"The configured field(s) {', '.join(gone)} are not on this Jira instance (GET /field does not "
                "list them), so the ticket was read without them: correct direct_api.custom_fields / "
                "direct_api.acceptance_criteria_fields in qa-factory/config.json.")
    note = TL.description_note(snapshot["description"], limit_bytes=table["description_limit_bytes"])
    if note:
        say(note)
    if raw_dir:
        _write_raw_folder(Path(raw_dir), issue, raw_parts)
        _write_s0_files(client, key, snapshot, work, catalog, remote_links, table, kinds, context or {})
    return snapshot


def _write_raw_folder(raw_dir: Path, issue: dict, parts: dict) -> None:
    """Every response of the read, byte for byte, plus the readable copy of the issue."""
    for name, data in parts.items():
        _atomic_write(raw_dir / name, data)
    _atomic_write(raw_dir / "issue.pretty.json",
                  json.dumps(issue, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")


def ticket_view_text(snapshot: dict) -> str:
    """`work/ticket-view.md`: the ticket as a role reads it - title, description whole, the criteria,
    and the comments one per line, id first, newlines inside a text written as `\\n` (ticket_light
    escapes backslash first, so the line view is reversible). Plain text: no field the role does not
    need, and no JSON to read around."""
    ac = [str(item) for item in snapshot.get("acceptance_criteria") or []]
    comments = snapshot.get("comments") or []
    lines = [f"{snapshot.get('key')} {TL.MID_DOT} {snapshot.get('title') or ''}",
             f"Type: {snapshot.get('type') or '-'} | Status: {snapshot.get('status') or '-'}"
             + (f" | Parent: {snapshot['parent']}" if snapshot.get("parent") else ""),
             "", "DESCRIPTION", snapshot.get("description") or "(empty)", "", "ACCEPTANCE CRITERIA"]
    lines += [f"{number}. {item}" for number, item in enumerate(ac, 1)] or ["(none found in the ticket)"]
    lines += ["", f"COMMENTS ({len(comments)}) - one per line: id {TL.MID_DOT} created {TL.MID_DOT} author {TL.MID_DOT} text"]
    lines += [TL.comment_lines(comments)] if comments else ["(no comments)"]
    return "\n".join(lines) + "\n"


def _link_seeds(snapshot: dict) -> list:
    seeds = []
    if snapshot.get("parent"):
        seeds.append({"ref": snapshot["parent"], "origins": ["field:parent"]})
    for link in (snapshot.get("links") or {}).get("issue_links") or []:
        if link.get("key"):
            seeds.append({"ref": link["key"], "origins": [f"field:issuelinks:{link.get('type') or link.get('relation') or 'link'}"]})
    for sub in snapshot.get("subtasks") or []:
        if sub.get("key"):
            seeds.append({"ref": sub["key"], "origins": ["field:subtasks"]})
    return seeds


def build_references(client: "JiraClient", key: str, snapshot: dict, extra_texts: dict, *, known_prefixes,
                     kinds: dict, context: dict, seeded: list | None = None) -> list:
    """The reference rows `{ref, kind, origins[], status}` of the story's text and typed fields:
    `ticket_light.references` with the project's own repositories and hosts and the prefixes this run
    already knows (the per-prefix probe is S1's, and costs one request per unknown prefix)."""
    hosts = list(context.get("known_hosts") or []) + [client.base_url]
    texts = {"mention:summary": snapshot.get("title") or "", "mention:description": snapshot.get("description") or ""}
    for comment in snapshot.get("comments") or []:
        texts[f"mention:comment:{comment.get('id')}"] = comment.get("text") or ""
    urls = [row["url"] for row in (snapshot.get("links") or {}).get("remote_links") or [] if row.get("url")]
    if urls:
        texts["field:remotelink"] = "\n".join(urls)
    texts.update(extra_texts or {})
    return TL.references(texts, known_prefixes=known_prefixes, not_tracker_prefixes=not_tracker_prefixes(),
                         reference_kinds=kinds, known_hosts=hosts, repos=context.get("repos") or [],
                         seeded=_link_seeds(snapshot) if seeded is None else seeded, own_key=key)


def _write_s0_files(client, key, snapshot, work: Path, catalog: dict, remote_links: list, table: dict,
                    kinds: dict, context: dict) -> None:
    inventory_path = work / "source-inventory.json"
    known = _known_prefixes(client, inventory_path, key, snapshot, ())
    rows = build_references(client, key, snapshot, {}, known_prefixes=known, kinds=kinds, context=context)
    _atomic_write(work / "ticket-view.md", ticket_view_text(snapshot).encode("utf-8"))
    # `scanned` says which texts the rows come from (S0 does not read attachments - C12; S1 `collect`
    # appends them and says so); `written_by` the stages that wrote to the file.
    document = {"schema_version": 1, "ticket": key, "written_by": ["S0"],
                "scanned": ["summary", "description", "comments", "remote links"], "rows": rows}
    _atomic_write(work / "ticket-references.json",
                  json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    cache = dict(_prefix_cache(inventory_path))
    seeded_at = utc_now()
    for prefix in sorted(known):
        cache.setdefault(prefix, {"result": "tracker", "checked_at": seeded_at,
                                  "reason": "known at S0 without a request: the story's own prefix, its parent or links, "
                                            "a /browse/ link in its text, or adapters.ticket.project_keys"})
    # `auth_stop=None` removes the mark an earlier refused read left: this read worked, the login is back.
    # `field_ids` is what `/field` said THIS time: a catalogue that was not read (booked in `reads_skipped`)
    # or came from an earlier S0's store is left as it is, never overwritten by an empty list that looks like
    # "the instance has no epic field". `reads_skipped` is written every time, `[]` when nothing was skipped
    # (FR-23: the null outcome is a recorded state).
    seeded = {"prefix_probes": cache, "proof_key": key, "auth_stop": None,
              "reads_skipped": list(getattr(client, "reads_skipped", None) or [])}
    if catalog.get("ids") is not None:
        seeded["field_ids"] = {"epic_link": catalog["epic_link"], "fetched_at": seeded_at}
    _set_top_level(inventory_path, **seeded)


def _media_group_status(items: list) -> str:
    """The status of the whole external-media block from its items: `read` only when every item is,
    `pending` while any is unsettled, `partial` when all are read or partial, else `unavailable`.

    An item the person left out before the run (`excluded`, see source_exclusions.py) is not counted
    at all: it owes nothing, and it must neither hold the block `pending` nor make it look
    unavailable. When EVERY item is excluded the block is therefore `read` - although nothing was
    read. Consumers that show the block (`context_bundle`'s `external_media.status`) thus show `read`
    for a block whose items are all left out; the items' own `excluded` status and `excluded_by` say
    what happened (the critic's C7 of t-173: stated here, not hidden)."""
    items = [value for value in items if value.get("status") != "excluded"]
    settled = {"read", "partial", "unavailable"}
    return ("read" if all(value.get("status") == "read" for value in items)
            else "pending" if any(value.get("status") not in settled for value in items)
            else "partial" if all(value.get("status") in {"read", "partial"} for value in items)
            else "unavailable")


def _media_receipt_holds(row: dict, base: Path) -> bool:
    """A media receipt may be carried into a re-collect of the SAME revision only when what it
    points at is still there: a `read` or `partial` item names a file whose hash it recorded."""
    status = row.get("status")
    if status in {"pending", "unavailable"}:
        return True
    if status not in {"read", "partial"}:
        return False
    ref = row.get("local_ref")
    if not _safe_rel(ref) or not row.get("content_hash"):
        return False
    try:
        path = (base / str(ref)).resolve()
        path.relative_to(base.resolve())
        return path.is_file() and sha256_bytes(path.read_bytes()) == row.get("content_hash")
    except (OSError, ValueError):
        return False


def _media_items_for(urls: list, carried: dict | None, base: Path) -> list:
    """One external-media item per URL: pending, unless the stored record of the same revision
    already holds a receipt for that exact URL (see `collect_jira_source`)."""
    previous: dict = {}
    if carried:
        block = (carried.get("materials") or {}).get("external_media") or {}
        for row in block.get("items") or []:
            if isinstance(row, dict) and row.get("url") is not None:
                previous.setdefault(row["url"], row)
    items = []
    for url in urls:
        row = previous.get(url)
        if row is not None and _media_receipt_holds(row, base):
            items.append(json.loads(json.dumps(row)))
        else:
            items.append({"url": url, "status": "pending", "content_hash": None,
                          "local_ref": None, "error": None})
    return items


# ---- the person's word before the run (source_exclusions.py) --------------------------------------
# A source the person asked, before the run, not to read is marked in the inventory (`excluded_by`),
# and every way into it - the collector, the peek, the media receipt - checks the record first.
# `source_exclusions` imports this module at the top, so it is imported here only when called.
LEFT_OUT_PREFIX = "left out before the run by the person's word: "
LEFT_OUT_BY_WORD = "left out by you (before the run)"


def _live_exclusions(output: Path) -> list:
    """The live exclusions of the story whose `work/` holds `output`. [] when it has no record; an
    unreadable record RAISES (ExclusionRecordError): it errs toward refusing, never toward ignoring."""
    import source_exclusions
    return source_exclusions.live_in(Path(output).parent)


def _mark_of(exclusion: dict) -> dict:
    return {"exclusion": exclusion["id"], "origin": exclusion.get("origin"), "at": exclusion.get("at")}


def _marked_live(entry: dict, live_ids: set) -> bool:
    mark = entry.get("excluded_by")
    return isinstance(mark, dict) and mark.get("exclusion") in live_ids


def _mark_source(item: dict, exclusion: dict) -> None:
    text = LEFT_OUT_PREFIX + '"' + str(exclusion.get("reason") or "") + '"'
    item.update(relevance="not_relevant", status="excluded", relevance_reason=text,
                exclusion_or_error=text, assessment_ref=item.get("assessment_ref") or None,
                excluded_by=_mark_of(exclusion))


def _left_out_hit(output: Path, canonical_ref: str) -> dict | None:
    """The live exclusion that names this ticket, or None."""
    import source_exclusions
    return source_exclusions.first_match(_live_exclusions(output), canonical_ref=canonical_ref)


def _left_out_record(client: JiraClient, key: str, relation: str, discovered_from, relation_evidence,
                     required: bool, fetched_at: str, exclusion: dict) -> dict:
    """The record of a ticket the person left out: nothing was fetched, so nothing of it is known
    but its key. Shaped like the excluded mentions a prefix probe writes."""
    canonical = canonical_ticket(client.base_url, key)
    record = {"source_id": stable_source_id(client.base_url, canonical), "canonical_ref": canonical,
              "relation": relation, "relevance": "pending", "relevance_reason": "", "assessment_ref": None,
              "discovered_from": discovered_from, "relation_evidence": relation_evidence,
              "required": required, "status": "pending", "revision": None, "content_hash": None,
              "snapshot_ref": None, "fetched_at": fetched_at, "exclusion_or_error": None,
              "inspection_status": "pending", "inspection_ref": None,
              "materials": {"comments": {"status": "unknown", "count": None},
                            "attachments": {"status": "unknown", "count": None, "items": []}},
              "mentioned_ticket_keys": []}
    _mark_source(record, exclusion)
    return record


def apply_exclusion_marks(sources: list, exclusions: list) -> list:
    """Mark, in place, every entry of `sources` that a live exclusion names. Returns what was newly
    marked: [{"exclusion": id, "source_id", "key"}] for a ticket and [{..., "url"}] for a media item.

    A Jira source that is already `read` is left alone (the record lists bytes on disk, and the load
    refusal of source_exclusions makes this state unreachable); a media item is marked whatever it
    was and keeps its `local_ref` - the record never lies about bytes already on disk. The first
    matching exclusion in line order is the one recorded; an entry already marked by a live one is
    not touched again. Nothing here is written to disk: the caller writes, which is why this runs
    LAST in `update_inventory`."""
    import source_exclusions as sx
    live_ids = {e["id"] for e in exclusions}
    applied = []
    if not exclusions:
        return applied
    for item in sources:
        if item.get("status") != "read" and not _marked_live(item, live_ids):
            hit = sx.first_match(exclusions, canonical_ref=item.get("canonical_ref"))
            if hit:
                _mark_source(item, hit)
                applied.append({"exclusion": hit["id"], "source_id": item.get("source_id"), "key": _key(item)})
        block = (item.get("materials") or {}).get("external_media")
        rows = _item_rows(block or {})
        touched = False
        for row in rows:
            if _marked_live(row, live_ids):
                continue
            hit = sx.first_match(exclusions, url=row.get("url"))
            if hit:
                row.update(status="excluded", excluded_by=_mark_of(hit))
                touched = True
                applied.append({"exclusion": hit["id"], "source_id": item.get("source_id"), "url": row.get("url")})
        if touched:
            block["status"] = _media_group_status(block.get("items") or [])
    return applied


def marks_in(inventory: dict) -> set:
    """{(source_id, url or None, exclusion id)} for every live mark of an inventory."""
    found = set()
    for item in inventory.get("sources", []):
        if isinstance(item.get("excluded_by"), dict):
            found.add((item.get("source_id"), None, item["excluded_by"].get("exclusion")))
        for row in _item_rows((item.get("materials") or {}).get("external_media") or {}):
            if isinstance(row.get("excluded_by"), dict):
                found.add((item.get("source_id"), row.get("url"), row["excluded_by"].get("exclusion")))
    return found


def revoke_marks(output: Path, exclusion_id: str) -> list:
    """The person took an exclusion back: its marks move into `excluded_by_history[]` (with
    `revoked_at`) and what they held goes back to waiting - a ticket with no snapshot to `pending` /
    `pending`, a media item to `pending`, the block status recomputed. Works whatever stage the story
    is in; whether anything then reads it is the conductor's (source_exclusions prints the door).
    Returns [{"source_id", "key"}] / [{"source_id", "url"}] of what went back."""
    output = Path(output)
    if not output.exists():
        return []
    inventory = load_inventory(output)
    at = utc_now()
    restored = []

    def release(entry: dict) -> bool:
        mark = entry.get("excluded_by")
        if not isinstance(mark, dict) or mark.get("exclusion") != exclusion_id:
            return False
        entry.setdefault("excluded_by_history", []).append(dict(mark, revoked_at=at))
        entry.pop("excluded_by")
        return True

    for item in inventory.get("sources", []):
        if release(item):
            if not item.get("snapshot_ref"):
                item.update(relevance="pending", status="pending",
                            relevance_reason="mentioned source requires assessment", exclusion_or_error=None)
            restored.append({"source_id": item.get("source_id"), "key": _key(item)})
        block = (item.get("materials") or {}).get("external_media")
        touched = False
        for row in _item_rows(block or {}):
            if release(row):
                row["status"] = "pending"
                touched = True
                restored.append({"source_id": item.get("source_id"), "url": row.get("url")})
        if touched:
            block["status"] = _media_group_status(block.get("items") or [])
    if restored:
        _write_inventory(output, inventory)
    return restored


# ---- what S1 downloads (t-267 F11, K9) -------------------------------------------------------------------
# A video recording of 8 MB held the S1 gate shut on TP1-15045, and every image was downloaded
# whole whatever its size. The policy is DATA - references/jira-fields.json `attachment_policy`, a
# proposal nobody has measured - and the project may replace it (`adapters.ticket.attachments`). An
# attachment the policy leaves out is LISTED with its reason, settled-but-listed: it is not a gap a
# person must accept, because the factory decided it, and the receipt says so.
SKIPPED_BY_POLICY = "skipped_by_policy"


def attachment_policy_for(client) -> dict | None:
    """The policy in force: `None` when the project switched it off (`{"policy": "off"}` - every
    attachment is downloaded, as before D-06), else the table's `attachment_policy`, with the keys
    `adapters.ticket.attachments` names replaced (`rules`, `never_suffixes`). A wrong shape is REFUSED
    naming the key, never read as "no policy". A stand-in client with no `attachment_config` at all (a
    test double of the stages after S1, which serves tickets from a table) has no policy, as before."""
    if not hasattr(client, "attachment_config"):
        return None
    table = TL.load_fields_table()["attachment_policy"]
    config = client.attachment_config
    if config in (None, {}):
        return table
    if not isinstance(config, dict):
        raise TL.TableError("adapters.ticket.attachments must be an object ({} for the default policy, "
                            f"{{\"policy\": \"off\"}} to download everything), got {type(config).__name__}; "
                            "fix it in qa-factory/config.json")
    if str(config.get("policy") or "").strip().lower() == "off":
        return None
    policy = dict(table)
    for name in ("rules", "never_suffixes"):
        if name in config:
            policy[name] = config[name]
    rules, suffixes = policy.get("rules"), policy.get("never_suffixes", [])
    if (not isinstance(rules, list) or not all(isinstance(rule, dict) and isinstance(rule.get("mime_prefixes"), list)
                                               for rule in rules)
            or not isinstance(suffixes, list) or not all(isinstance(s, str) for s in suffixes)):
        raise TL.TableError("adapters.ticket.attachments.rules must be a list of {class, mime_prefixes[], "
                            "max_bytes | never} and never_suffixes a list of strings; fix it in "
                            "qa-factory/config.json")
    return policy


def attachment_verdict(policy: dict | None, filename, mime, size) -> str | None:
    """`None` = download it; else the rule that leaves it out: `never` (a video or an archive, or a
    suffix on the never list - `.mp4` whatever its mime type says), `size` (over the class's limit; AT the
    limit it is downloaded), `type` (no rule names its mime type). An unknown size cannot be judged:
    the attachment is downloaded."""
    if policy is None:
        return None
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix in {s.lower() for s in policy.get("never_suffixes") or []}:
        return "never"
    mime = str(mime or "").strip().lower()
    if not mime:
        # Jira sends `null` for a file it could not label (plan.md, a screenshot). The data names the type
        # such a file is judged as; a project policy with no such key leaves it `type` (safe).
        mime = str(policy.get("empty_mime_as") or "").strip().lower()
    for rule in policy.get("rules") or []:
        if any(mime.startswith(str(prefix).lower()) for prefix in rule.get("mime_prefixes") or []):
            if rule.get("never"):
                return "never"
            limit = rule.get("max_bytes")
            if limit is not None and size is not None and int(size) > int(limit):
                return "size"
            return None
    return "type"


def blob_suffix(policy: dict | None, filename, mime) -> str:
    """The suffix a stored blob carries, from the table's `blob_suffixes` ({suffix, mime_prefix} rows): a
    PDF is stored as `blobs/<digest>.pdf` so the `Read` tool opens it as a document; the hash is still
    over the content. Every other file keeps the bare `blobs/<digest>`. No policy or no rows: no suffix."""
    name, kind = str(filename or "").lower(), str(mime or "").strip().lower()
    table = TL.load_fields_table()["attachment_policy"].get("blob_suffixes") or []
    rows = (policy or {}).get("blob_suffixes", table) if policy is not None else table
    for row in rows:
        suffix = str(row.get("suffix") or "").lower()
        prefix = str(row.get("mime_prefix") or "").lower()
        if suffix and ((prefix and kind.startswith(prefix)) or name.endswith(suffix)):
            return suffix
    return ""


def collect_jira_source(client: JiraClient, key: str, output: Path, relation: str = "task",
                        discovered_from: str | None = None, relation_evidence: str | None = None,
                        relevance: str = "relevant", relevance_reason: str = "explicit required source",
                        required: bool = True, fetched_at: str | None = None,
                        existing_record: dict | None = None) -> dict:
    if relation not in VALID_RELATIONS or relevance not in VALID_RELEVANCE:
        raise ValueError("invalid source relation or relevance")
    fetched_at = fetched_at or utc_now()
    canonical = canonical_ticket(client.base_url, key)
    source_id = stable_source_id(client.base_url, canonical)
    # The person's word comes before any byte is asked for: this is the library door, so `ticket_adapter
    # collect`, `refresh` and `judge_sources` all pass it. The position is the invariant: a check after
    # `client.issue` would fetch the ticket it then refuses to keep.
    left_out = _left_out_hit(output, canonical)
    if left_out:
        return _left_out_record(client, key, relation, discovered_from, relation_evidence, required,
                                fetched_at, left_out)
    try:
        # A failure that could be a lost login is checked before it is booked (C5): AuthLost leaves this
        # function - no `unavailable` record, nothing written for this source.
        issue, issue_raw = _gated(client, output, f"the ticket {key}", lambda: _issue_and_raw(client, key),
                                  prefix_proven=_prefix_of(key) in _proven_prefixes(client, output))
        remote_revision = _revision(issue)
        # TP1-13797 (cmp1): every source with an open or an accepted gap was re-collected on each
        # `refresh`, and a re-collect wrote `inspection_status: pending` and reset every media item
        # (below), so a receipt the role had recorded was wiped before gate A could read it. On an
        # UNCHANGED revision whose stored files verify, what the role recorded belongs to THIS
        # revision and is carried over, whatever `completeness` says; a changed revision resets it.
        # A source that is not complete is still re-collected (comments and failed attachments are
        # retried, test_source_inventory: "incomplete revision is not silently reused") - only its
        # receipts are no longer lost with it.
        carried = None
        if (existing_record and remote_revision != "unknown" and
                existing_record.get("revision") == remote_revision):
            verified = verify_inventory_files(output.parent.parent,
                                              {"schema_version": 1, "sources": [existing_record]})
            if verified["valid"]:
                carried = existing_record
            if carried and completeness({"sources": [existing_record]})["complete"]:
                reused = json.loads(json.dumps(existing_record))
                reused["_refresh_result"] = "unchanged"
                return reused
        fields = issue.get("fields") or {}
        pages: list = []
        comments = _gated(client, output, f"the comments of {key}",
                          lambda: _all_comments(client, key, fields.get("comment") or {}, pages))
        # The light form (ticket_light.project): the whitelist is applied here, the response is kept
        # whole beside it (`raw.json`, named in no brief - F23). The Epic Link ids are the ones S0 stored:
        # S1 never asks `/field` (C3).
        snapshot = light_snapshot(client, issue, comments, epic_fields=persisted_epic_fields(output), raw=issue_raw)
        external_urls = extract_media_urls(fields.get("description"),
                                           *(comment.get("body") for comment in comments))
        snapshot_bytes = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
        revision_locator = hashlib.sha256(remote_revision.encode("utf-8")).hexdigest()[:16]
        snapshot_relative = Path("sources") / source_id / revision_locator / "ticket.json"
        snapshot_path = output.parent / snapshot_relative
        _atomic_write(snapshot_path, snapshot_bytes)
        _atomic_write(snapshot_path.with_name("raw.json"), issue_raw)
        for number, page in enumerate(pages, 1):
            _atomic_write(snapshot_path.with_name(f"raw-comments-{number}.json"), page)
        policy = attachment_policy_for(client)
        receipts = []
        for attachment in fields.get("attachment") or []:
            attachment_id = str(attachment.get("id") or "unknown")
            receipt = {"attachment_id": attachment_id, "filename": attachment.get("filename"),
                       "media_type": attachment.get("mimeType"), "size": attachment.get("size"),
                       "original_ref": attachment.get("content"), "status": "pending",
                       "local_ref": None, "content_hash": None,
                       "analysis_status": "pending", "error": None}
            try:
                previous = next((r for r in ((existing_record or {}).get("materials", {}).get("attachments", {}).get("items") or [])
                                 if r.get("attachment_id") == attachment_id and r.get("original_ref") == attachment.get("content")
                                 and r.get("status") == "read"), None)
                if previous and existing_record.get("revision") == remote_revision:
                    saved = (output.parent / str(previous.get("local_ref") or "")).resolve()
                    if saved.is_relative_to(output.parent.resolve()) and saved.is_file() and sha256_bytes(saved.read_bytes()) == previous.get("content_hash"):
                        receipts.append(dict(previous))
                        continue
                verdict = attachment_verdict(policy, attachment.get("filename"), attachment.get("mimeType"),
                                             attachment.get("size"))
                if verdict:
                    # Settled by the factory's own policy and LISTED, with the rule: not a gap a person
                    # has to accept, and not silently absent either. `skipped_by_policy` is in neither
                    # `_UNSETTLED` nor the gap statuses of `_gap_point_details`, so it blocks nothing.
                    receipt.update(status=SKIPPED_BY_POLICY, analysis_status=SKIPPED_BY_POLICY,
                                   skipped_by_policy=verdict, reason=f"{SKIPPED_BY_POLICY}:{verdict}")
                    receipts.append(receipt)
                    continue
                data = client.get_bytes(str(attachment.get("content") or ""))
                if attachment.get("size") is not None and len(data) != int(attachment["size"]):
                    raise FetchError(None, "attachment size mismatch", retryable=True)
                digest = sha256_bytes(data)
                # Full content hash prevents collisions; original names remain in metadata.
                relative = Path("blobs") / (digest + blob_suffix(policy, attachment.get("filename"), attachment.get("mimeType")))
                _atomic_write(output.parent / relative, data)
                receipt.update(status="read", content_hash=digest, local_ref=relative.as_posix())
            except FetchError as exc:
                # A login that died mid-collect would otherwise be booked as one `unavailable` receipt
                # per attachment (C5): the gate raises AuthLost, or lets the ordinary failure through.
                exc.auth_verdict = auth_gate(client, exc, output,
                                             what=f"attachment {attachment.get('filename')} of {key}")
                receipt.update(status="unavailable", analysis_status="unavailable", error=exc.reason, retryable=exc.retryable,
                               retry_at=exc.retry_at)
            except OSError as exc:
                receipt.update(status="unavailable", analysis_status="unavailable",
                               error=f"attachment storage failed ({type(exc).__name__}); check path length and permissions",
                               retryable=True)
            receipts.append(receipt)
        attachment_texts, attachment_named = [], {}
        for receipt in receipts:
            if receipt.get('status') != 'read':
                continue
            # Only what a person wrote. An analytics .html or a .json export carries
            # namespace URLs and key-shaped tokens by the dozen and not one reference.
            if Path(str(receipt.get('filename') or '')).suffix.lower() in _HUMAN_TEXT_SUFFIXES:
                original = output.parent / receipt['local_ref']
                try:
                    if original.stat().st_size <= 2_000_000:
                        text = original.read_text(encoding='utf-8', errors='replace')
                        attachment_texts.append(text)
                        attachment_named[f"mention:attachment:{receipt.get('filename')}"] = text
                except OSError:
                    receipt.update(analysis_status='unavailable', error='stored attachment could not be read; retry inspection')
        external_urls = sorted(set(external_urls + extract_media_urls(*attachment_texts)))
        revision = remote_revision
        media_items = _media_items_for(external_urls, carried, output.parent)
        # "Nothing changed" also needs every media receipt that held a file to have been carried: one
        # whose file no longer verifies is reset to pending above, and that is work for the role again.
        now_by_url = {row.get("url"): row.get("status") for row in media_items}
        nothing_lost = all(now_by_url.get(row.get("url")) == row.get("status")
                           for row in ((carried or {}).get("materials", {}).get("external_media") or {}).get("items") or []
                           if isinstance(row, dict) and row.get("status") in {"read", "partial"})
        # Custom fields are NOT scanned for keys (t-267 F17 (b)): the light form holds only the ids the
        # project named, and the raw response keeps the rest whole; a key that lives only in a custom
        # field nobody configured is found in the raw by a person, not mined from 164 fields of noise.
        candidate_keys = extract_ticket_keys(snapshot["description"],
                                             "\n".join(snapshot["acceptance_criteria"]),
                                             str(snapshot.get("parent") or ""),
                                             json.dumps(snapshot.get("links") or {}),
                                             *(c["text"] for c in snapshot["comments"]), *attachment_texts)
        # This very call just fetched `key` successfully: that IS proof this Jira instance
        # is readable right now, even before it is persisted to disk.
        resolved_mentions = resolve_mentioned_keys(client, output, key, snapshot, candidate_keys,
                                                   source_id, snapshot_relative.as_posix(),
                                                   attachment_texts, access_proven=True)
        if relation == "task":
            # C12: S0 wrote the story's references from its fields, summary, description and comments;
            # the text attachments S1 has now downloaded add rows (`mention:attachment:<name>`).
            append_attachment_references(client, output, key, snapshot, attachment_named)
        return {"source_id": source_id, "canonical_ref": canonical, "relation": relation,
                "relevance": relevance, "relevance_reason": relevance_reason,
                "assessment_ref": snapshot_relative.as_posix(),
                "discovered_from": discovered_from, "relation_evidence": relation_evidence,
                "required": required, "status": "read", "revision": revision,
                "content_hash": sha256_bytes(snapshot_bytes),
                "snapshot_ref": snapshot_relative.as_posix(),
                "fetched_at": fetched_at, "exclusion_or_error": None,
                "inspection_status": (carried or {}).get("inspection_status") or "pending",
                "inspection_ref": (carried or {}).get("inspection_ref"),
                # "Nothing changed" = the same revision, every stored file still verifies, no media
                # receipt lost. A source re-collected only to retry what failed is still `unchanged`:
                # `changed` tells the role the content moved and to inspect it again (s1.md, refresh).
                "_refresh_result": ("unchanged" if carried and nothing_lost
                                    else "changed" if existing_record else "new"),
                "materials": {"comments": {"status": "read", "count": len(comments)},
                              "attachments": {"status": "read" if all(r["status"] in ("read", SKIPPED_BY_POLICY) for r in receipts) else "unavailable",
                                              "count": len(receipts), "items": receipts},
                              "external_media": {"status": _media_group_status(media_items),
                                                 "count": len(external_urls), "items": media_items}},
                "mentioned_ticket_keys": resolved_mentions["pending"],
                "_new_excluded_mentions": resolved_mentions["records"]}
    except (FetchError, OSError) as exc:
        # `auth_verdict == "unavailable"`: a 401/403/404 the probe could not settle (429, 5xx, a timeout) -
        # nothing is known, so it is retryable and never a not-found.
        unsettled = getattr(exc, "auth_verdict", None) == "unavailable"
        reason = (exc.reason if isinstance(exc, FetchError) else "source storage failed; check path length and permissions")
        if unsettled:
            reason += " (and the login could not be confirmed either: the tracker did not answer the check)"
        return {"source_id": source_id, "canonical_ref": canonical, "relation": relation,
                "relevance": "unknown", "relevance_reason": "source could not be assessed",
                "assessment_ref": None, "discovered_from": discovered_from,
                "relation_evidence": relation_evidence, "required": required,
                "status": "unavailable", "revision": None, "content_hash": None,
                "snapshot_ref": None, "fetched_at": fetched_at, "exclusion_or_error": reason,
                "inspection_status": "unknown", "inspection_ref": None,
                "retryable": True if unsettled else getattr(exc, "retryable", True), "retry_at": getattr(exc, "retry_at", None),
                "materials": {"comments": {"status": "unknown", "count": None},
                              "attachments": {"status": "unknown", "count": None, "items": []},
                              "external_media": {"status": "unknown", "count": None, "items": []}},
                "mentioned_ticket_keys": []}


def _access_proven(output: Path, base_url: str) -> bool:
    try:
        inventory = load_inventory(output)
    except Exception:
        return False
    prefix = str(base_url).rstrip("/") + "/browse/"
    return any(item.get("status") == "read" and str(item.get("canonical_ref") or "").startswith(prefix)
               for item in inventory.get("sources", []))


def _prefix_of(key: str) -> str:
    return str(key).rsplit("-", 1)[0].upper()


# A key mentioned anywhere in a ticket — description, a comment, or an attachment a person
# wrote — is treated alike: TP1-15045 showed that a REAL bug id is just as likely to turn
# up in an attachment as in the description, so a whitelist scoped to attachments would have
# kept losing exactly those. What differs is the prefix: one already tied to this tracker
# costs nothing more; a new one costs one probe of the PROJECT, not one per key.
# The finder of `<ticket path marker><KEY>` is BUILT from the reference-kinds table's ticket rules and the
# one key shape (TL.KEY_RE), not written here a second time (t-280 F7, FR-13/FR-17): the kind rule and this
# finder read the same marker (`(?:^|/)browse/`), so a tracker behind a context path (`/jira/browse/ABC-5`)
# is a ticket link to both. None when the table is damaged; `_browse_key_re()` then refuses, naming the file.
try:
    _BROWSE_KEY_RE = TL.ticket_url_regex(_REFERENCE_KINDS) if _REFERENCE_KINDS is not None else None
except TL.TableError:
    _BROWSE_KEY_RE = None


def _browse_key_re():
    return _BROWSE_KEY_RE if _BROWSE_KEY_RE is not None else TL.ticket_url_regex(reference_kinds())


def _known_prefixes(client: JiraClient, output: Path, task_key: str, snapshot: dict,
                    extra_text_blobs: tuple[str, ...] = ()) -> set[str]:
    """Prefixes this run already knows belong to a real tracker, at zero extra Jira cost: the
    task's own, its parent, its issue links and subtasks, a `/browse/KEY` url in the ticket's text, a
    ticket this inventory already read, `adapters.ticket.project_keys`, and a prefix a probe of an
    earlier call (or S0's seed) already found to be a tracker project. `snapshot` is the LIGHT form:
    `links` is `{issue_links, remote_links, ...}`."""
    prefixes = {_prefix_of(task_key)}
    parent = str(snapshot.get("parent") or "")
    if parent:
        prefixes.add(_prefix_of(parent))
    links = snapshot.get("links") if isinstance(snapshot.get("links"), dict) else {}
    for link in links.get("issue_links") or []:
        if isinstance(link, dict) and link.get("key"):
            prefixes.add(_prefix_of(str(link["key"])))
    for sub in snapshot.get("subtasks") or []:
        if isinstance(sub, dict) and sub.get("key"):
            prefixes.add(_prefix_of(str(sub["key"])))
    blobs = (str(snapshot.get("title") or ""), str(snapshot.get("description") or ""),
             "\n".join(str(item) for item in snapshot.get("acceptance_criteria") or []),
             json.dumps(links), "\n".join(str(c.get("text") or "") for c in snapshot.get("comments") or []),
             *extra_text_blobs)
    browse_re = _browse_key_re()
    for blob in blobs:
        for m in browse_re.finditer(blob):
            prefixes.add(_prefix_of(m.group(1)))
    prefixes |= _proven_prefixes(client, output)
    return prefixes


def _proven_prefixes(client, output) -> set[str]:
    """Prefixes proven in THIS run without a request now: a ticket of the prefix was read, the
    project told us (`project_keys`), or a probe found a tracker project (S0 seeds the story's own)."""
    prefixes = {str(p).upper() for p in (getattr(client, "project_keys", None) or [])}
    existing = _read_inventory_file(output) if output else {}
    for item in existing.get("sources", []) or []:
        if item.get("status") == "read":
            ref_key = str(item.get("canonical_ref") or "").rsplit("/browse/", 1)[-1]
            if ref_key:
                prefixes.add(_prefix_of(ref_key))
    for prefix, row in (existing.get("prefix_probes") or {}).items():
        if isinstance(row, dict) and row.get("result") == "tracker":
            prefixes.add(str(prefix).upper())
    return prefixes


def _prefix_cache(output: Path) -> dict:
    if not output.exists():
        return {}
    try:
        return json.loads(output.read_text(encoding="utf-8")).get("prefix_probes") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefix_probe(output: Path, prefix: str, result: str, reason: str | None) -> None:
    # A top-level map, not a source: `update_inventory` rewrites {schema_version, sources}
    # on every call, so it is taught (below) to keep any other top-level key it finds here.
    inventory = {"schema_version": 1, "sources": []}
    if output.exists():
        try:
            inventory = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            inventory = {"schema_version": 1, "sources": []}
    inventory.setdefault("schema_version", 1)
    inventory.setdefault("sources", [])
    cache = dict(inventory.get("prefix_probes") or {})
    cache[prefix] = {"result": result, "reason": reason, "checked_at": utc_now()}
    inventory["prefix_probes"] = cache
    _atomic_write(output, json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")


def _project_prefix_status(client: JiraClient, output: Path, prefix: str, access_proven: bool) -> str:
    """One request per PREFIX, cached for the run: 'tracker' the project exists, 'not_tracker'
    the tracker answered 404 for it while access is proven (0.7.4's rule: 404 also means "no
    permission", so this is trusted only once some ticket of the instance is known `read` —
    `access_proven` is True already inside `collect_jira_source`, whose OWN successful fetch
    is that proof, even before it is written to disk), or 'unproven' — 404 without that proof,
    or any other error. 51 individual `peek` calls on TP1-15045 (BR-1..11, FTR-01..13,
    TC-001..016, US-1..7, BE-1/2, FE-1/2) were 7 prefixes."""
    cached = _prefix_cache(output).get(prefix)
    if cached is not None and cached.get("result") in ("tracker", "not_tracker"):
        return cached["result"]
    try:
        # A 401/403/login page here may be a dead token, not a fact about the project (C5): the gate
        # raises AuthLost, and AuthLost leaves nothing cached - a prefix refused by a lost login
        # yesterday is asked again today, with the renewed token.
        _gated(client, output, f"the project {prefix}",
               lambda: client.get_json(f"/rest/api/{client.api_version}/project/{urllib.parse.quote(prefix)}"))
        result, reason = "tracker", None
    except FetchError as exc:
        if exc.status == 404 and access_proven and not _foreign(exc):
            result = "not_tracker"
            reason = ("tracker answered 404 for the project while other tickets of this "
                      "tracker were readable: local numbering (a document's own requirement "
                      "or case ids), not a tracker project")
        else:
            # `unproven` is NOT cached (t-267 K8b): it records a refusal or a transient failure, not a
            # fact about the prefix, and a cached one outlived the token (or the outage) that caused it.
            return "unproven"
    _save_prefix_probe(output, prefix, result, reason)
    return result


def resolve_mentioned_keys(client: JiraClient, output: Path, task_key: str, snapshot: dict,
                           candidate_keys: list[str], source_id: str, snapshot_ref: str,
                           attachment_texts: list[str], access_proven: bool = False) -> dict:
    """Split key-shaped tokens into ones that become ordinary pending mentions (known or
    proven-tracker prefix) and ones already resolved by a prefix probe — excluded (`not_found`)
    or left `unavailable` — so a flood of local document numbering never costs one Jira
    request per token, and never disappears without a trace either."""
    # A local key (SS1-14) is held by no tracker: no request, no record. The ONE reader of that fact is local_keys.is_local
    # (imported here: it imports adapter_forms and hooklib, which this module must not need at import time).
    import local_keys
    candidate_keys = [key for key in candidate_keys or [] if not local_keys.is_local(key)]
    if not candidate_keys:
        return {"pending": [], "records": []}
    known = _known_prefixes(client, output, task_key, snapshot, tuple(attachment_texts))
    access_proven = access_proven or _access_proven(output, client.base_url)
    by_prefix: dict[str, list[str]] = {}
    pending: list[str] = []
    for candidate in candidate_keys:
        prefix = _prefix_of(candidate)
        if prefix in known:
            pending.append(candidate)
        else:
            by_prefix.setdefault(prefix, []).append(candidate)
    records = []
    for prefix in sorted(by_prefix):
        status = _project_prefix_status(client, output, prefix, access_proven)
        keys = by_prefix[prefix]
        if status == "tracker":
            pending.extend(keys)
            continue
        excluded = status == "not_tracker"
        reason = (f"tracker project '{prefix}' does not exist while other tickets of this "
                  "tracker were readable: local numbering, not a tracker project" if excluded else
                  f"tracker project '{prefix}' could not be confirmed: source could not be assessed")
        for candidate in keys:
            canonical = canonical_ticket(client.base_url, candidate)
            record = {"source_id": stable_source_id(client.base_url, canonical), "canonical_ref": canonical,
                      "relation": "referenced", "relevance": "not_relevant" if excluded else "unknown",
                      "relevance_reason": reason, "assessment_ref": None,
                      "discovered_from": source_id, "relation_evidence": snapshot_ref,
                      "required": True, "status": "excluded" if excluded else "unavailable",
                      "revision": None, "content_hash": None, "snapshot_ref": None,
                      "fetched_at": utc_now(), "exclusion_or_error": reason,
                      "inspection_status": "pending" if excluded else "unknown", "inspection_ref": None,
                      "materials": {"comments": {"status": "unknown", "count": None},
                                    "attachments": {"status": "unknown", "count": None, "items": []}},
                      "mentioned_ticket_keys": []}
            if excluded:
                record["not_found"] = True
            records.append(record)
    return {"pending": sorted(set(pending)), "records": records}


def peek_jira_source(client: JiraClient, key: str, output: Path,
                     discovered_from: str | None = None,
                     relation_evidence: str | None = None,
                     fetched_at: str | None = None) -> dict:
    """Read what a relevance decision needs — title, type, status, description, acceptance
    criteria, parent and links — and nothing else. No comment page, no attachment byte and
    no mention of this ticket enters the story until it is judged relevant: on TP1-15045
    two unrelated tickets brought ten attachments with them, 8 MB of video among them, and
    those attachments then held the S1 gate shut."""
    fetched_at = fetched_at or utc_now()
    canonical = canonical_ticket(client.base_url, key)
    source_id = stable_source_id(client.base_url, canonical)
    base = {"source_id": source_id, "canonical_ref": canonical, "relation": "referenced",
            "relevance": "pending", "relevance_reason": "mentioned source requires assessment",
            "discovered_from": discovered_from, "relation_evidence": relation_evidence,
            "required": True, "status": "pending", "revision": None, "content_hash": None,
            "snapshot_ref": None, "fetched_at": fetched_at, "exclusion_or_error": None,
            "inspection_status": "pending", "inspection_ref": None,
            "materials": {"comments": {"status": "unknown", "count": None},
                          "attachments": {"status": "unknown", "count": None, "items": []}},
            "mentioned_ticket_keys": []}
    # Before `client.issue`, as in `collect_jira_source`: nothing of a left-out ticket is asked for.
    left_out = _left_out_hit(output, canonical)
    if left_out:
        _mark_source(base, left_out)
        return base
    try:
        issue, issue_raw = _gated(client, output, f"the ticket {key}", lambda: _issue_and_raw(client, key),
                                  prefix_proven=_prefix_of(key) in _proven_prefixes(client, output))
        fields = issue.get("fields") or {}
        # No comment page enters the story at this depth: the light form is built over the issue WITHOUT
        # its embedded comments (`comment_count` still says how many there are).
        snapshot = light_snapshot(client, issue, [], epic_fields=persisted_epic_fields(output), raw=issue_raw)
        snapshot["depth"] = "assessment"
        snapshot["attachment_names"] = [a.get("filename") for a in fields.get("attachment") or []]
        snapshot["comment_count"] = (fields.get("comment") or {}).get("total")
        data = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
        relative = Path("sources") / source_id / "assessment" / "ticket.json"
        _atomic_write(output.parent / relative, data)
        _atomic_write((output.parent / relative).with_name("raw.json"), issue_raw)
        base.update(assessment_ref=relative.as_posix(),
                    materials={"comments": {"status": "unknown", "count": snapshot["comment_count"]},
                               "attachments": {"status": "unknown",
                                               "count": len(snapshot["attachment_names"]),
                                               "items": []}})
        return base
    except (FetchError, OSError) as exc:
        # Jira answers 404 both for "no such issue" and for "you may not see it", and an
        # expired session can turn every answer into 404. So a 404 leaves a key out only
        # when this same inventory proves the tracker is readable right now (a source of this
        # instance is `read`), it is flagged `not_found` so the person sees it as its own
        # line in the review, and without that proof it stays an unavailable source.
        # C5: the probe's own verdict - `ok` (the login works) is the proof that a 404 or 403 is about
        # the ticket, whether or not a source was read before; `unavailable` (the check itself got no
        # answer) is never a not-found. A lost login never reaches here: it raised AuthLost.
        verdict = getattr(exc, "auth_verdict", None)
        proven = verdict == "ok" or (verdict is None and _access_proven(output, client.base_url))
        # B-408 (E20): a 404 whose answer the tracker is not shown to have written (a protection layer's page) is
        # no fact about the ticket, whatever the login check said: never `not_found`.
        if isinstance(exc, FetchError) and exc.status == 404 and proven and not _foreign(exc):
            reason = ("tracker answered 404 while other tickets of this tracker were readable: "
                      "no such issue (key-shaped text), or an issue you have no permission to see")
            base.update(assessment_ref=None, relevance="not_relevant", status="excluded",
                        relevance_reason=reason, exclusion_or_error=reason, not_found=True)
            return base
        unsettled = verdict == "unavailable"
        base.update(assessment_ref=None, relevance="unknown", status="unavailable",
                    relevance_reason="source could not be assessed",
                    exclusion_or_error=((exc.reason if isinstance(exc, FetchError) else
                                         "source storage failed; check path length and permissions")
                                        + (" (and the login could not be confirmed either: the tracker did "
                                           "not answer the check)" if unsettled else "")),
                    inspection_status="unknown", retryable=True if unsettled else getattr(exc, "retryable", True),
                    retry_at=getattr(exc, "retry_at", None))
        return base


def update_inventory(output: Path, record: dict) -> dict:
    record = dict(record)
    record.pop("_refresh_result", None)
    excluded_mentions = record.pop("_new_excluded_mentions", None) or []
    existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"schema_version": 1, "sources": []}
    replaced = [item for item in existing.get("sources", [])
                if item.get("canonical_ref") == record["canonical_ref"]]
    sources = [item for item in existing.get("sources", [])
               if item.get("canonical_ref") != record["canonical_ref"]]
    history = list(record.get("prior_revisions") or [])
    for item in replaced:
        revision = item.get("revision")
        if revision and revision != record.get("revision") and not any(h.get("revision") == revision for h in history):
            history.append({"revision": revision, "content_hash": item.get("content_hash"),
                            "snapshot_ref": item.get("snapshot_ref"),
                            "fetched_at": item.get("fetched_at")})
    if history:
        record["prior_revisions"] = history
    if record.get("inspection_status") != "read" or record.get("inspection_by") == STAMP_BY:
        # The writer of the snapshot stamps its receipt (t-721 3.5): the file it just stored is the fact. A receipt a
        # role wrote (`assess`) is never overwritten; a code stamp over an older revision is renewed.
        invalid = verify_inventory_files(Path(output).resolve().parent.parent, {"sources": [record]})["invalid_source_ids"]
        if snapshot_receipt(record, set(invalid)):
            _stamp(record)
    for item in replaced:
        for human_key in ("gap_acceptance", "human_review"):
            if human_key in item and human_key not in record:
                record[human_key] = item[human_key]
    sources.append(record)
    instance = record["canonical_ref"].rsplit("/browse/", 1)[0]
    known_refs = {item.get("canonical_ref") for item in sources}
    mentions = record.get("mentioned_ticket_keys") if record.get("status") == "read" else []
    for key in mentions or []:
        canonical = canonical_ticket(instance, key)
        if canonical in known_refs or canonical == record["canonical_ref"]:
            continue
        mentioned_id = stable_source_id(instance, canonical)
        sources.append({"source_id": mentioned_id, "canonical_ref": canonical,
                        "relation": "referenced", "relevance": "pending",
                        "relevance_reason": "mentioned source requires assessment",
                        "assessment_ref": None, "discovered_from": record["source_id"],
                        "relation_evidence": record.get("snapshot_ref"), "required": True,
                        "status": "pending", "revision": None, "content_hash": None,
                        "snapshot_ref": None, "fetched_at": record.get("fetched_at"),
                        "exclusion_or_error": None,
                        "inspection_status": "pending", "inspection_ref": None,
                        "materials": {"comments": {"status": "unknown", "count": None},
                                      "attachments": {"status": "unknown", "count": None,
                                                      "items": []}},
                        "mentioned_ticket_keys": []})
        known_refs.add(canonical)
    # Already resolved by a prefix probe: excluded/unavailable in one step, no
    # individual `peek` needed, and still added only once per canonical ref.
    for excluded in (excluded_mentions if record.get("status") == "read" else []):
        canonical = excluded.get("canonical_ref")
        if canonical in known_refs:
            continue
        sources.append(dict(excluded))
        known_refs.add(canonical)
    # The person's word before the run is applied LAST - after the mentions and the excluded
    # mentions above are merged, just before the write - so that no write through this function can
    # persist a matched entry as `pending` or `relevant`. No record file, no marks: the output is
    # then what it always was. An unreadable record raises here, before anything is written.
    apply_exclusion_marks(sources, _live_exclusions(output))
    sources.sort(key=lambda item: (str(item.get("canonical_ref")), str(item.get("revision"))))
    result = {"schema_version": 1, "sources": sources}
    # A top-level map (like `prefix_probes`) would otherwise be silently dropped on every
    # rewrite of this file; keep whatever the disk copy already carried beside sources.
    result.update({k: v for k, v in existing.items() if k not in ("schema_version", "sources")})
    if record.get("status") == "read":
        # A ticket was read after an `auth_stop`: the login works again, the mark is history.
        result.pop("auth_stop", None)
    _atomic_write(output, json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    _settle_references(output, [record] + [dict(m) for m in excluded_mentions])
    return result


def _reference_status_of(item: dict) -> str | None:
    """What a source record says about the ticket reference it settles; None = it settles nothing yet."""
    if item.get("status") == "read" or (item.get("assessment_ref") and item.get("status") == "pending"):
        return "fetched"
    if item.get("status") == "excluded":
        word = "not found (404)" if item.get("not_found") else "left out"
        return f"not_fetched:{word} - " + _clip(item.get("relevance_reason") or "excluded", 100)
    if item.get("status") == "unavailable":
        return "not_fetched:unavailable - " + _clip(item.get("exclusion_or_error") or "no reason recorded", 100)
    return None


def _settle_references(output: Path, items: list) -> None:
    """The story's `ticket-references.json` (S0) says, per ticket row, whether the ticket was fetched or
    why not (FR-41: a reference present in the text never vanishes). A source record that settles a
    ticket row moves its status. No file (a story older than the file) means nothing to settle."""
    path = Path(output).parent / "ticket-references.json"
    if not path.is_file():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rows = document.get("rows") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return
    updates = {}
    for item in items:
        status = _reference_status_of(item)
        if status and item.get("canonical_ref"):
            updates[_key(item)] = status
    changed = False
    for row in rows:
        if isinstance(row, dict) and row.get("kind") == "ticket" and row.get("ref") in updates \
                and row.get("status") != updates[row["ref"]]:
            row["status"] = updates[row["ref"]]
            changed = True
    if changed:
        _atomic_write(path, json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")


def append_attachment_references(client, output: Path, key: str, snapshot: dict, named_texts: dict) -> None:
    """S1 (C12): the text attachments just downloaded add reference rows to the story's
    `ticket-references.json` - origins `mention:attachment:<name>` - and a row already there gains the
    origin instead of a twin. No file (a story older than S0's file) or no text: nothing to add. A table
    that cannot be read refuses (TableError), as everywhere else."""
    path = Path(output).parent / "ticket-references.json"
    if not named_texts or not path.is_file():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rows = document.get("rows") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return
    context = getattr(client, "references_context", None) or {}
    known = _known_prefixes(client, Path(output), key, snapshot, tuple(named_texts.values()))
    fresh = TL.references(named_texts, known_prefixes=known, not_tracker_prefixes=not_tracker_prefixes(),
                          reference_kinds=TL.load_reference_kinds(),
                          known_hosts=list(context.get("known_hosts") or []) + [client.base_url],
                          repos=context.get("repos") or [], seeded=[], own_key=key)

    def identity(row):
        return (row.get("kind"), row.get("ref"), row.get("repo_id") or row.get("repo"))

    index = {identity(row): row for row in rows if isinstance(row, dict)}
    for row in fresh:
        have = index.get(identity(row))
        if have is None:
            rows.append(row)
            index[identity(row)] = row
        else:
            for origin in row.get("origins") or []:
                if origin not in have.setdefault("origins", []):
                    have["origins"].append(origin)
    if "attachments" not in document.setdefault("scanned", []):
        document["scanned"].append("attachments")
    if "S1" not in document.setdefault("written_by", []):
        document["written_by"].append("S1")
    _atomic_write(path, json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")


def refresh_targets(inventory: dict) -> list:
    """The sources `refresh` reads again from the tracker: relevant, read, and NOT a text the factory recorded (a text source
    is no Jira key; reading it as one would replace its `read` with `unavailable`)."""
    return [item for item in inventory.get("sources", [])
            if item.get("relevance") == "relevant" and item.get("status") == "read" and not item.get("text_source")]


def only_text_sources(inventory: dict) -> bool:
    """Does the inventory hold sources, and are ALL of them texts the factory recorded (`text_source`)? Then no tracker is
    needed to review or refresh it. An empty list is False: nothing recorded is no reason to lift a requirement."""
    sources = [item for item in (inventory or {}).get("sources") or [] if isinstance(item, dict)]
    return bool(sources) and all(item.get("text_source") is True for item in sources)


def text_snapshot(ref: str, text: str) -> dict:
    """The snapshot of a text source: the shape of a ticket's snapshot (the readers of a source open it as JSON), a document
    titled by the last part of its locator, its text as the description. No criteria, no comments."""
    parts = [part for part in re.split(r"[\\/]", str(ref).rstrip("/\\")) if part]
    return {"key": ref, "type": "document", "title": parts[-1] if parts else ref, "description": text,
            "acceptance_criteria": [], "comments": [], "provenance": {"source": "file"}}


def record_text_source(output: Path, *, relation: str, ref: str, snapshot: dict, required: bool) -> dict:
    """Record a TEXT the factory holds as a source (the story's own local text, a document a role read): the snapshot is stored
    under `sources/<source id>/<hash>/ticket.json` beside `output`, the record is `status: read` with `text_source: True`, and
    `update_inventory` writes it (so the receipt stamp, `prior_revisions` and the references settling are the ones every source
    gets). The same locator with the same bytes is the same revision (no new record); other bytes are a new revision. The
    record names no ticket (`mentioned_ticket_keys: []`): the links of the text are read from `ticket-references.json`.
    Raises ValueError for a relation outside `VALID_RELATIONS`, for a second task source, and for a locator that already
    names a record which is not a text of the same relation (a text never replaces a ticket, a gap or the task source)."""
    if relation not in VALID_RELATIONS:
        raise ValueError(f"relation {relation!r} is not one of {', '.join(sorted(VALID_RELATIONS))}")
    output = Path(output)
    if output.exists():
        sources = load_inventory(output).get("sources", [])
        other = conflicting_task_source(sources, relation, ref)
        if other:
            raise ValueError(f"a task-relation source already exists ({other.get('canonical_ref')}); one story has one task source")
        same = next((s for s in sources if s.get("canonical_ref") == ref), None)
        if same and (same.get("text_source") is not True or same.get("relation") != relation):
            raise ValueError(f"{ref} is already a source of this story ({same.get('relation')}, {same.get('status')}): a text "
                             "never replaces it. Record the text under its own locator; a gap is closed by accept-gap with the "
                             "person's words")
    # The very bytes `ticket_adapter.snapshot_bytes` gives a ticket's snapshot (a test holds the two equal); written here
    # because ticket_adapter imports this module.
    data = (json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    digest = sha256_bytes(data)
    source_id = stable_source_id("text", ref)
    snapshot_relative = Path("sources") / source_id / digest[:12] / "ticket.json"   # no colon in a folder name: Windows
    _atomic_write(output.parent / snapshot_relative, data)
    # t-586 F-4: the counts are the SNAPSHOT's (a tracker's snapshot holds comments and attachments; a local text holds none, so
    # `.get` keeps it at 0). An attachment the snapshot names was not read by the factory: a row with analysis_status
    # `unavailable`, so S2 meets it as a gap (FR-41, AR-27), never as "read, 0".
    comments = snapshot.get("comments") if isinstance(snapshot.get("comments"), list) else []
    named = [a for a in (snapshot.get("attachments") if isinstance(snapshot.get("attachments"), list) else []) if isinstance(a, dict)]
    held = [{"attachment_id": str(a.get("id") or f"attachment-{n}"), "filename": a.get("filename"), "media_type": a.get("mimeType"),
             "size": a.get("size"), "original_ref": None, "status": "unavailable", "local_ref": None, "content_hash": None,
             "analysis_status": "unavailable", "error": "named by the tracker's snapshot; not read or recorded by the factory"}
            for n, a in enumerate(named, 1)]
    record = {"source_id": source_id, "canonical_ref": ref, "relation": relation, "relevance": "relevant",
              "relevance_reason": "text recorded by the factory", "assessment_ref": snapshot_relative.as_posix(),
              "discovered_from": None, "relation_evidence": None, "required": required, "status": "read",
              "revision": "sha256:" + digest[:12], "content_hash": digest, "snapshot_ref": snapshot_relative.as_posix(),
              "fetched_at": utc_now(), "exclusion_or_error": None, "inspection_status": "pending", "inspection_ref": None,
              "materials": {"comments": {"status": "read", "count": len(comments)},
                            "attachments": {"status": "unavailable" if held else "read", "count": len(held), "items": held},
                            "external_media": {"status": "read", "count": 0, "items": []}},
              "mentioned_ticket_keys": [], "text_source": True}
    result = update_inventory(output, record)
    return next(item for item in result["sources"] if item.get("canonical_ref") == ref)   # the record as it was stored


# OH3-39: the scout's brief names the places a project keeps requirements (config.json `requirements_sources`).
REQUIREMENT_SOURCE_LINE_LIMIT = 20        # sources shown; the rest are ONE line `and <k> more in config.json`
REQUIREMENT_SOURCE_LOCATOR_LIMIT = 200    # characters of a locator shown
NO_REQUIREMENT_SOURCES = "Requirement sources: no other sources are recorded; the ticket and its links are the sources"
LOCATOR_WITHHELD = "locator withheld: it holds a credential-like field"


def _shown(value, secret_re) -> str:
    """A config text as one line of the brief: a credential-like value is never printed, the rest is cut at the locator limit."""
    text = " ".join(str(value or "").split())
    return LOCATOR_WITHHELD if secret_re.search(text) else text[:REQUIREMENT_SOURCE_LOCATOR_LIMIT]


# SS1-15: how a role reads a tracker the factory holds no client for. ONE route per project, recorded by onboarding in the
# `tracker` row of `requirements_sources` (`method`, `invoke_or_command_ref`); the code only SHOWS it to the role, it never
# parses or runs it (AR-2). The six general rules are one constant: the driver hands them to the scout and `s1.md` carries the
# same lines (a test holds the two equal, AR-15). At most TRACKER_RULES_LIMIT bytes: the lines go to the brief outside the
# 6 KB cap and the A22 role start load (role_load.py), so their weight is bounded here (AR-11).
TRACKER_RULES_LIMIT = 900
TRACKER_RULES = (
    "1. An agent, a skill or an assistant is never a read route: it drops comments and attachments silently.",
    "2. Record the task: ticket_adapter.py collect <KEY> --relation task --output <INV>. From it read, by the route: the direct parent, "
    "the links, every comment, every attachment.",
    "3. Save each ticket whole, comments in it, under work/raw/, then record-source --ref <KEY> --file <file> "
    "--relation <parent|subject|normative|referenced> --output <INV>.",
    "4. A key or link in what you read: read it, keep only what can carry a requirement for this story, record that. "
    "Children and siblings are not enumerated.",
    "5. Could not reach it after one try by the route: no question. A line in unresolved_facts: id = the key and why, "
    "reason = missing_evidence.",
    "6. Only writes that change something are refused; never write to the tracker.",
)
ROUTE_CUT = "… (whole in config.json)"


def _route_cut(text: str) -> str:
    """A route text as the brief shows it: whole up to the locator limit, else cut with the ROUTE_CUT mark."""
    return text if len(text) <= REQUIREMENT_SOURCE_LOCATOR_LIMIT else text[:REQUIREMENT_SOURCE_LOCATOR_LIMIT] + ROUTE_CUT


def _tracker_state(cfg) -> dict:
    """What the `tracker` rows of `cfg["requirements_sources"]` give: the FIRST row whose kind the table routes through the
    adapter, whose status is not `unavailable` and whose `invoke_or_command_ref` is a non-empty text is THE tracker row the
    brief's `Tracker:` line speaks for (`index`; the others are ordinary rows; with no such row `index` is the first adapter row
    that has no ref, or None). `route` is `{method, ref, status, index}` when that row has a usable `invoke_or_command_ref`, else None
    and then `not_read` is the word of a write channel its `method` named, `pointer` says its ref points into a config setting
    (`pointer_ref_prefixes`, an onboarding row such as `adapters.ticket.direct_api`: no route, t-586 F-6) and `withheld` says its
    ref held a credential-like field (checked on the WHOLE text, before any cut; a `{key}` / `$NAME` value is no secret). The
    words come from `config_contract.requirement_source_kinds`, the one reader; a table it cannot read gives no route (AR-6)."""
    from config_contract import requirement_source_kinds, route_has_secret
    state = {"route": None, "not_read": "", "withheld": False, "pointer": False, "index": None}
    sources = cfg.get("requirements_sources") if isinstance(cfg, dict) else None
    if not isinstance(sources, list):
        return state
    try:
        table = requirement_source_kinds()
    except ValueError:
        return state
    adapter_kinds = {k for k, v in table["kinds"].items() if v.get("route") == "adapter"}
    for index, row in enumerate(sources):
        if (not isinstance(row, dict) or not isinstance(row.get("kind"), str) or row["kind"] not in adapter_kinds
                or row.get("status") == "unavailable"):
            continue
        ref = " ".join(row["invoke_or_command_ref"].split()) if isinstance(row.get("invoke_or_command_ref"), str) else ""
        if not ref:
            if state["index"] is None:
                state["index"] = index      # no route yet: the head speaks for this row unless a later row has one
            continue
        state["index"] = index
        method = row["method"].strip() if isinstance(row.get("method"), str) else ""
        if method.lower() in table["not_read_routes"]:
            state["not_read"] = method
        elif ref.lower().startswith(tuple(table["pointer_ref_prefixes"])):
            state["pointer"] = True
        elif route_has_secret(ref):
            state["withheld"] = True
        else:
            state["route"] = {"method": method, "ref": _route_cut(ref), "status": row.get("status"), "index": index}
        return state
    return state


def tracker_route(cfg) -> dict | None:
    """The route onboarding recorded for reading the project's tracker, or None: `{method, ref, status, index}` (see
    `_tracker_state`). A pure reader: nothing is parsed, run or probed."""
    return _tracker_state(cfg)["route"]


def tracker_route_lines(cfg, *, by_role: bool) -> list:
    """The scout's brief about a tracker the ROLE reads (`ticket_adapter.reads_by_role`): the route as recorded, then the six
    general rules. `by_role` False (a client reads it): []. With no route, the first line says so and names the door (a
    command the config holds is offered once; nothing else is guessed): unreachable is a gap, never a question (D-0043)."""
    if not by_role:
        return []
    import adapter_forms
    state = _tracker_state(cfg)
    kind = adapter_forms.ticket_kind(cfg) or "unnamed"
    route = state["route"]
    if route:
        head = (f"Tracker: {kind}, read by this route: {route['method'] + ': ' if route['method'] else ''}{route['ref']}. "
                "<KEY> stands for a key." + ("" if route["status"] == "verified" else " Not proven yet: try it once."))
        return [head] + list(TRACKER_RULES)
    entry = adapter_forms.ticket_entry(cfg)
    command = " ".join(str(entry.get("command") or "").split())
    from config_contract import route_has_secret
    if state["not_read"]:
        why = f"{state['not_read']} is not a read route (FR-50); "
    elif state["pointer"]:
        why = "the recorded route points to a setting of the config, not to a way to read; "
    elif state["withheld"]:
        why = "route withheld: it holds a credential-like field; "
    else:
        why = ""
    if command and str(entry.get("status") or "").strip() == "configured" and not route_has_secret(command):
        head = f"Tracker: {kind}: {why}no route is recorded; adapters.ticket names {kind}: try {_route_cut(command)} once"
    else:
        head = (f"Tracker: {kind}: {why}no read route is recorded for this tracker: parents and links in the text are named "
                "gaps; /qa-factory:qa-onboarding records one")
    return [head] + list(TRACKER_RULES)


def requirement_source_lines(cfg: dict, *, local: bool, by_role: bool = False) -> list:
    """The lines of the scout's brief about `cfg["requirements_sources"]`: a pure function (no read, no write). The route a
    source is read by comes from the kinds table (`config_contract.requirement_source_kinds`, the one reader), never from a
    literal here; a kind outside the table, or a table that cannot be read, is routed to the role itself (AR-1, AR-2, FR-59).
    Status decides first: `unavailable` and `unknown` are lines of their own whatever the kind. `local` is a story that no
    tracker holds: a tracker source is then "not queried", never "unreachable" (FR-41). At most REQUIREMENT_SOURCE_LINE_LIMIT
    sources are shown, then one line for the rest. Nothing recorded (no key, an empty list, not a list) is the one line
    NO_REQUIREMENT_SOURCES; otherwise the first line is the heading `Requirement sources:`."""
    from config_contract import SECRET_QUERY_RE, requirement_source_kinds, route_has_secret
    sources = cfg.get("requirements_sources") if isinstance(cfg, dict) else None
    if not isinstance(sources, list) or not sources:
        return [NO_REQUIREMENT_SOURCES]
    try:
        kinds = requirement_source_kinds()["kinds"]
    except ValueError:
        kinds = {}
    lines = ["Requirement sources:"]
    # SS1-15: a tracker the ROLE reads is told by `tracker_route_lines`; the leading tracker row is that block's, and no row of
    # the adapter route says "read through collect/peek" (it is not true when the role reads it); a story with no key
    # keeps its "not queried" line.
    # (t-586 F-9a) the row the `Tracker:` line speaks for is that line's even when it names no route: one brief never says
    # "named gaps" there and "read it yourself" in the row.
    lead = _tracker_state(cfg)["index"] if by_role and not local else None
    for index, row in enumerate(sources[:REQUIREMENT_SOURCE_LINE_LIMIT]):
        if index == lead:
            continue
        if not isinstance(row, dict):
            lines.append(f"requirements_sources[{index}] is unreadable and was skipped")
            continue
        kind = row.get("kind") if isinstance(row.get("kind"), str) else ""
        name = _shown(row.get("source_id") or kind or f"source {index + 1}", SECRET_QUERY_RE)
        locator = _shown(row.get("locator"), SECRET_QUERY_RE)
        status = row.get("status")
        if status == "unavailable":
            evidence = row.get("evidence_refs")
            first = next((e for e in evidence if isinstance(e, str) and e.strip()), "") if isinstance(evidence, list) else ""
            lines.append(f"{name}: unavailable: {_shown(first, SECRET_QUERY_RE) or 'no evidence recorded'}; "
                         "a gap by default, not a question (D-0043)")
            continue
        if status != "verified":
            lines.append(f"{name}: not established: try the route once; a failed probe is a gap with its reason")
            continue
        route = (kinds.get(kind) or {}).get("route")
        own_route = ""      # a second tracker row keeps ITS route in the line (t-586 F-9b): another tracker does not vanish
        if route == "adapter" and by_role and not local:
            route = "role"
            ref = " ".join(row["invoke_or_command_ref"].split()) if isinstance(row.get("invoke_or_command_ref"), str) else ""
            own_route = f"; its route: {_route_cut(ref)}" if ref and not route_has_secret(ref) else ""
        if route == "adapter" and local:
            lines.append(f"{name} ({kind}): not queried: this story has no key there and the factory has no search; keys and "
                         "links in its text are read. Record the reason \"not queried: search needed\", never \"unreachable\"")
        elif route == "adapter":
            lines.append(f"{name} ({kind}): read through collect/peek, as the ticket")
        elif route == "grep":
            # `--ref` is the locator only when it is shown WHOLE; a withheld or cut one is a placeholder, never a wrong ref (F-10b)
            whole = locator if locator and locator == " ".join(str(row.get("locator") or "").split()) else "<locator>"
            lines.append(f"{name}: search {locator} for the story's words with Grep; what you read is recorded with "
                         f"ticket_adapter.py record-source --ref {whole} --file <file> --relation normative; it reaches the "
                         "manifest from the inventory")
        else:
            lines.append(f"{name}: read it yourself if you can reach it: {locator}{own_route}; save what you read under work/raw/, "
                         "record it with ticket_adapter.py record-source; otherwise record it as a gap with the reason")
    if len(sources) > REQUIREMENT_SOURCE_LINE_LIMIT:
        lines.append(f"and {len(sources) - REQUIREMENT_SOURCE_LINE_LIMIT} more in config.json")
    return [] if lead is not None and lines == ["Requirement sources:"] else lines


def refresh_relevant_sources(client: JiraClient, output: Path) -> dict:
    inventory = load_inventory(output)
    targets = refresh_targets(inventory)
    results = []
    for existing in targets:
        key = existing["canonical_ref"].rsplit("/browse/", 1)[-1]
        refreshed = collect_jira_source(
            client, key, output, relation=existing["relation"],
            discovered_from=existing.get("discovered_from"),
            relation_evidence=existing.get("relation_evidence"),
            relevance=existing["relevance"], relevance_reason=existing["relevance_reason"],
            required=existing["required"], existing_record=existing)
        refresh_result = refreshed.get("_refresh_result")
        inventory = update_inventory(output, refreshed)
        results.append({"source_id": refreshed["source_id"],
                        "result": refresh_result})
    return {"inventory": inventory, "results": results}


def load_inventory(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_inventory(inventory: dict, fresh: bool = True) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, object]] = set()
    required = ("source_id", "canonical_ref", "relation", "relevance", "relevance_reason",
                "assessment_ref", "discovered_from", "relation_evidence", "required", "status",
                "revision", "content_hash", "snapshot_ref", "fetched_at", "exclusion_or_error")
    if inventory.get("schema_version") != 1 or not isinstance(inventory.get("sources"), list):
        return ["inventory must have schema_version=1 and a sources array"]
    for index, item in enumerate(inventory["sources"]):
        prefix = f"sources[{index}]"
        for field in required:
            if field not in item:
                errors.append(f"{prefix}.{field} is required")
        if item.get("relation") not in VALID_RELATIONS:
            errors.append(f"{prefix}.relation is invalid")
        if item.get("relevance") not in VALID_RELEVANCE:
            errors.append(f"{prefix}.relevance is invalid")
        if item.get("status") not in VALID_STATUS:
            errors.append(f"{prefix}.status is invalid")
        if fresh and item.get("status") == "read" and (not item.get("revision") or not item.get("content_hash")):
            errors.append(f"{prefix} read source needs revision and content_hash")
        identity = (str(item.get("canonical_ref")), item.get("revision"))
        if identity in seen:
            errors.append(f"{prefix} duplicates canonical_ref + revision")
        seen.add(identity)
    return errors


def _gap_accepted(item: dict) -> bool:
    acceptance = item.get("gap_acceptance")
    return isinstance(acceptance, dict) and bool(str(acceptance.get("words") or "").strip())


def _reviewed(item: dict) -> bool:
    """A person saw THIS decision. A relevance flipped after the review is unreviewed again."""
    review = item.get("human_review")
    if not isinstance(review, dict) or not str(review.get("words") or "").strip():
        return False
    return (review.get("shown") or {}).get("relevance") == item.get("relevance")


def _late(item: dict) -> bool:
    """Shown at a gate (`review --late`) without pretending it is the person's answer: TP1-15045 recorded a `review --record` in the factory's own words for a
    source the person never actually spoke about. A relevance flip after the mark is late
    again, same as a flip after a real review."""
    shown = item.get("shown_at_gate")
    if not isinstance(shown, dict):
        return False
    return (shown.get("shown") or {}).get("relevance") == item.get("relevance")


# ---- points ------------------------------------------------------------------------------------
# TP1-13797 (cmp1, 30.09): a person answered "go on without the recording (SharePoint)" and the
# whole-source acceptance closed everything the source owed - the factory's own unfinished work
# (the inspection receipt was never written) and three merge requests the same words asked to have
# READ. An acceptance now closes POINTS: the single things a source still owes, each with an id that
# is stable across a re-collect. A point is one of two classes. GAP - the world did not give it
# (a source or material unavailable, partial or skipped): a person may decide to go on without it.
# WORK - the factory has not done it yet (not read, not inspected, a block or an attachment still
# pending): a person's words never close it by themselves.
POINT_GAP = "gap"
POINT_WORK = "work"
_UNSETTLED = {"pending", "unknown", None}
# `excluded` (the person left it out before the run) is deliberately NOT here: an excluded media item
# makes no point, in any block, and `_media_group_status` does not count it either.
_GAP_ITEM_STATUS = {"unavailable", "partial", "skipped"}
_BLOCK_LABEL = {"comments": "comments", "attachments": "attachments",
                "external_media": "external material"}
POINT_TEXT_LIMIT = 120
LEGACY_UNAVAILABLE_PREFIX = "materials unavailable: "


def _clip(text: str, limit: int = POINT_TEXT_LIMIT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _short_url(url: str, room: int) -> str:
    """The host and the last path segment of a URL: the part a person recognises. A 1.4 KB
    SharePoint link is one line, and its query string (an address with a login in it) is not shown."""
    text = normalize_url(url).strip()
    try:
        parts = urllib.parse.urlsplit(text)
        host, path = parts.hostname or "", parts.path
    except ValueError:
        host, path = "", ""
    segments = [urllib.parse.unquote(part) for part in path.split("/") if part]
    if host and segments and len(segments) > 1 and segments[-1].isdigit():
        # `.../merge_requests/510` says what 510 is, a bare number does not - and WHICH repository it
        # belongs to is the part that tells `team/sdk/-/merge_requests/510` from
        # `team/ui/-/merge_requests/510`: keep as much of the path as fits, the end of it first.
        short = ""
        for keep in range(len(segments), 1, -1):
            tail = segments[-keep:]
            short = host + ("/.../" if keep < len(segments) else "/") + "/".join(tail)
            if len(short) <= room:
                break
    elif host and segments:
        short = host + ("/.../" if len(segments) > 1 else "/") + segments[-1]
    else:
        short = host or text
    return short if len(short) <= room else short[:max(room - 3, 1)] + "..."


def _attachment_ids(receipts: list, with_ref: bool = True) -> list:
    """`attachment:<id>` - except when the id cannot tell two files apart: a missing or "unknown" id
    (the collector's own fallback) or one id on two receipts. Those get the position and a hash of
    name, size and the original address (`original_ref`), so an id may split one file into two points
    but never merge two files into one - two different files of one name and size, in two revisions,
    are told apart by where they came from. A receipt with no `original_ref` hashes name and size only
    (the id every earlier acceptance was stored under); `with_ref=False` gives that earlier spelling for
    EVERY receipt, which `_all_point_ids` uses to recognise an id stored before `original_ref` joined
    the hash."""
    raw = []
    for receipt in receipts:
        value = receipt.get("attachment_id")
        raw.append("" if value in (None, "") else str(value))
    ids = []
    for index, (receipt, value) in enumerate(zip(receipts, raw)):
        if value in ("", "unknown") or raw.count(value) > 1:
            origin = receipt.get("original_ref") if with_ref else None
            basis = f"{receipt.get('filename')}|{receipt.get('size')}" + (f"|{origin}" if origin else "")
            digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
            ids.append(f"attachment:{value or 'unknown'}:{index}:{digest}")
        else:
            ids.append(f"attachment:{value}")
    return ids


def _media_id(row: dict, index: int) -> str:
    """`media:<hash of the normalized URL>`: the markdown-escaped and the plain spelling of one
    address are one material. An item with no URL cannot be told from another: it is its position."""
    url = str(row.get("url") or "")
    if not url.strip():
        return f"media:none:{index}"
    return "media:" + hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def _item_rows(block: dict) -> list:
    return [row for row in (block.get("items") or []) if isinstance(row, dict)]


def _gap_point_details(item: dict) -> list:
    """[(point, aliases)] of ONE source, ignoring every acceptance. `aliases` are the raw spellings a
    legacy acceptance string may have used for the material's name (private: only the reader of a
    legacy `accepted` list needs them). The rules are exactly the old `completeness()` rules,
    itemised - test_gap_points.py holds the two equal on inventories with no acceptance."""
    if item.get("status") == "excluded" and item.get("relevance") == "not_relevant":
        return []
    details = []

    def add(pid, kind, cls, text, name="", aliases=()):
        details.append(({"id": pid, "kind": kind, "class": cls, "text": _clip(text), "name": name},
                        set(aliases) | ({name} if name else set())))

    if item.get("status") == "pending" or item.get("relevance") == "pending":
        add("source:pending", "source", POINT_WORK, "not read yet")
    elif item.get("status") == "unavailable" or item.get("relevance") == "unknown":
        add("source:unavailable", "source", POINT_GAP, _legacy_unavailable_text(item))
    if item.get("status") != "read":
        return details
    if item.get("inspection_status") != "read":
        add("source:not_inspected", "source", POINT_WORK, "materials not inspected")
    materials = item.get("materials") or {}
    for kind in ("comments", "attachments", "external_media"):
        block = materials.get(kind) or {}
        status = block.get("status")
        label = _BLOCK_LABEL[kind]
        explained = False
        if kind == "attachments":
            rows = _item_rows(block)
            for row, pid in zip(rows, _attachment_ids(rows)):
                analysis = row.get("analysis_status")
                name = str(row.get("filename")) if row.get("filename") is not None else ""
                shown = name or str(row.get("attachment_id") or "unnamed")
                if analysis in _UNSETTLED:
                    add(pid, "attachment", POINT_WORK, f"attachment {shown} not inspected", name,
                        {str(row.get("filename"))})
                elif analysis in {"unavailable", "skipped"}:
                    explained = True
                    add(pid, "attachment", POINT_GAP, f"attachment {shown}: {analysis}", name,
                        {str(row.get("filename"))})
        elif kind == "external_media" and status in {"unavailable", "partial"}:
            # Old rule: the block's own status decides, the items are never read. So an item makes a
            # point only inside an unavailable/partial block, and only one that explains it.
            groups: dict = {}
            for index, row in enumerate(_item_rows(block)):
                if row.get("status") in _GAP_ITEM_STATUS:
                    groups.setdefault(_media_id(row, index), []).append(row)
            for pid, rows in groups.items():
                explained = True
                first = rows[0]
                name = normalize_url(str(first.get("url") or ""))
                prefix, suffix = "external material ", f": {first.get('status')}"
                room = POINT_TEXT_LIMIT - len(prefix) - len(suffix)
                add(pid, "media", POINT_GAP, prefix + _short_url(str(first.get("url") or ""), room) + suffix,
                    name, {str(row.get("url")) for row in rows})
        if status in _UNSETTLED:
            add(f"{kind}:block", "block", POINT_WORK, f"{label} not collected or inspected yet")
        elif status in {"unavailable", "partial"} and not explained:
            add(f"{kind}:block", "block", POINT_GAP, f"{label} unavailable or only partly collected")
    return details


def _legacy_unavailable_text(item: dict) -> str:
    return "unavailable: " + str(item.get("exclusion_or_error") or "no reason recorded")


def gap_points(item: dict) -> list:
    """Every open point of one source, ignoring acceptance:
    `{"id", "kind", "class": "gap"|"work", "text", "name"}`. Ids: `source:pending`,
    `source:unavailable`, `source:not_inspected`, `<comments|attachments|external_media>:block`,
    `attachment:<attachment_id>` (`attachment:unknown:<index>:<hash>` when the id is missing, "unknown"
    or shared), `media:<sha256 of the normalized URL>[:16]`. `text` is one line a person can read
    (at most 120 characters, no source id); `name` is the file name or the normalized URL."""
    return [point for point, _ in _gap_point_details(item)]


def _all_point_ids(item: dict) -> set:
    """Every id that names something of this source, open or not - to tell an id that is no longer
    open (the material arrived, the receipt was written) from one that never existed here."""
    ids = {"source:pending", "source:unavailable", "source:not_inspected",
           "comments:block", "attachments:block", "external_media:block"}
    materials = item.get("materials") or {}
    rows = _item_rows(materials.get("attachments") or {})
    ids.update(_attachment_ids(rows))
    ids.update(_attachment_ids(rows, with_ref=False))  # an id an acceptance stored before `original_ref` joined the hash
    ids.update(_media_id(row, index) for index, row in enumerate(_item_rows(materials.get("external_media") or {})))
    return ids


def _material_entries(item: dict) -> list:
    """[(id, aliases)] of every attachment and every distinct external material of the source, read
    or not: how many things a legacy name could have meant."""
    materials = item.get("materials") or {}
    rows = _item_rows(materials.get("attachments") or {})
    entries = [(pid, {str(row.get("filename"))}) for row, pid in zip(rows, _attachment_ids(rows))]
    groups: dict = {}
    for index, row in enumerate(_item_rows(materials.get("external_media") or {})):
        names = groups.setdefault(_media_id(row, index), set())
        names.update({str(row.get("url")), normalize_url(str(row.get("url") or ""))})
    return entries + list(groups.items())


def _legacy_closed_ids(item: dict, details: list, acceptance: dict) -> set:
    """What an acceptance recorded BEFORE `accepted_points` existed closes. It closes gap-class points
    only, whatever it says: "materials not inspected", "not read yet" and any string this code does
    not recognise close nothing. Words with no `accepted` list at all close every open gap-class
    point (the old whole-source meaning, narrowed to the class the person could decide)."""
    if not str(acceptance.get("words") or "").strip():
        return set()
    gap = [(point, aliases) for point, aliases in details if point["class"] == POINT_GAP]
    accepted = acceptance.get("accepted")
    if accepted is None or accepted == []:
        return {point["id"] for point, _ in gap}
    if not isinstance(accepted, list):
        return set()
    strings = [value for value in accepted if isinstance(value, str)]
    entries = _material_entries(item)
    all_gap_material_unnamed = not any(point["kind"] in {"attachment", "media"} for point, _ in gap)
    named = set()
    for value in strings:
        if value.startswith(LEGACY_UNAVAILABLE_PREFIX):
            named |= _legacy_named_material_ids(value[len(LEGACY_UNAVAILABLE_PREFIX):], entries)
    closed = set()
    for point, aliases in gap:
        for value in strings:
            if point["id"] == "source:unavailable" and value == _legacy_unavailable_text(item):
                closed.add(point["id"])
            elif point["kind"] == "block" and all_gap_material_unnamed and value == LEGACY_UNAVAILABLE_PREFIX + "unnamed":
                closed.add(point["id"])
        if point["kind"] in {"attachment", "media"} and point["id"] in named:
            closed.add(point["id"])
    return closed


def _legacy_named_material_ids(names: str, entries: list) -> set:
    """The materials ONE legacy `materials unavailable: <names>` string names, or nothing. The old
    recorder wrote `", ".join(names)`, so the string cannot say whether `a, b.png` is one file or two:
    the whole text is tried first as one exact name, and failing that it is split. A string is read only
    when EVERY piece of it is a material of this source - one piece that matches nothing (an empty or
    blank one included) means the string is not what this code can read, and it closes nothing, so a
    name that happens to match a neighbour is never closed by words that named something else. A name
    carried by two materials of the source (two files called the same) closes neither (G9)."""
    whole = [pid for pid, material_names in entries if names in material_names]
    pieces = [names] if whole else names.split(", ")
    closed = set()
    for piece in pieces:
        found = [pid for pid, material_names in entries if piece in material_names] if piece.strip() else []
        if not found:
            return set()
        if len(found) == 1:
            closed.add(found[0])
    return closed


def _legacy_record(acceptance) -> dict | None:
    """The whole-source acceptance an older recorder wrote, if this source carries one: the acceptance
    itself while it has no `accepted_points`, or the copy `apply_gap_acceptance` keeps under `legacy`
    when the first point acceptance is recorded on top of it. `None` when there is none (or its words
    are blank). The old meaning of it - the whole source stops blocking - is honoured for a story whose
    S1 is already closed (`completeness(s1_closed=True)`), whether or not points were added since."""
    if not isinstance(acceptance, dict):
        return None
    record = acceptance if not isinstance(acceptance.get("accepted_points"), list) else acceptance.get("legacy")
    if isinstance(record, dict) and str(record.get("words") or "").strip():
        return record
    return None


def _entry_in_force(entry: dict, point: dict, item: dict) -> bool:
    """Does this stored accepted point close THIS open point now. Same id and same class: a gap-class
    acceptance closes a gap-class point (it persists across a re-collect, the person decided to go on
    without that material); a work-class one closes only with the sentence the person was shown, and
    only for the revision it was given on - new content is new work."""
    if not isinstance(entry, dict) or not str(entry.get("words") or "").strip():
        return False
    if entry.get("id") != point["id"] or entry.get("class") != point["class"]:
        return False
    if point["class"] == POINT_GAP:
        return True
    return bool(str(entry.get("shown_text") or "").strip()) and entry.get("revision") == item.get("revision")


def _closed_point_ids(item: dict, details: list) -> set:
    acceptance = item.get("gap_acceptance")
    if not isinstance(acceptance, dict):
        return set()
    stored = acceptance.get("accepted_points")
    if not isinstance(stored, list):
        return _legacy_closed_ids(item, details, acceptance)
    return {point["id"] for point, _ in details
            if any(_entry_in_force(entry, point, item) for entry in stored)}


def _key(item: dict) -> str:
    return str(item.get("canonical_ref") or item.get("source_id") or "").rsplit("/browse/", 1)[-1]


SOURCE_UNAVAILABLE = "source_unavailable"      # a pseudo cause: only a class record may carry it, never a default
GAP_CLASSES_FILE = "gap-classes.json"
GAP_CLASSES_KEY, GAP_CLASSES_SCHEMA = "classes", 1


def _point_row(item: dict, point: dict):
    """The row of the item that makes this point, or None: the attachment receipt, the first row of the media group, the
    source itself for `source:unavailable`."""
    materials = item.get("materials") or {}
    if point["kind"] == "attachment":
        rows = _item_rows(materials.get("attachments") or {})
        return next((row for row, pid in zip(rows, _attachment_ids(rows)) if pid == point["id"]), None)
    if point["kind"] == "media":
        for index, row in enumerate(_item_rows(materials.get("external_media") or {})):
            if _media_id(row, index) == point["id"] and row.get("status") in _GAP_ITEM_STATUS:
                return row
        return None
    return item if point["id"] == "source:unavailable" else None


def point_cause(item: dict, point: dict) -> str:
    """Why the world did not give this GAP point: the `cause` of its row (a word of `media_causes`), `source_unavailable` for
    a source whose status IS `unavailable` (N14: a source merely `relevance: unknown` is not called unreachable), `""` for
    everything else (a block, a work point, a row whose cause is not a word). PURE; `gap_points` keeps its form."""
    if point.get("class") != POINT_GAP:
        return ""
    row = _point_row(item, point)
    if row is None:
        return ""
    if point["kind"] == "source":
        return SOURCE_UNAVAILABLE if item.get("status") == "unavailable" else ""
    cause = row.get("analysis_cause") if point["kind"] == "attachment" else row.get("cause")
    return cause if isinstance(cause, str) else ""


def _safe_rel(ref) -> bool:
    """A work-relative path in either spelling: not rooted, no drive, no `..` - whichever OS reads it."""
    from pathlib import PurePosixPath, PureWindowsPath
    if not isinstance(ref, str) or not ref.strip() or ref.startswith(("/", "\\")):
        return False
    return not (PureWindowsPath(ref).drive or PureWindowsPath(ref).is_absolute() or PurePosixPath(ref).is_absolute()
                or ".." in PureWindowsPath(ref).parts or ".." in PurePosixPath(ref).parts)


def _default_causes() -> tuple:
    """`(default_causes, vcs_codes, problem)` of the table; an unreadable table gives NO default and a problem line."""
    try:
        table = cause_table()
    except ValueError as exc:
        return {}, {}, f"references/source-causes.json cannot be read: {exc}"
    return table["default_causes"], table["vcs_codes"], ""


def _task_config(task_root):
    """The config (a dict) of the project the TASK lives in - the nearest `qa-factory/config.json` above the task root, not the
    cwd's or the environment's; `None` when there is none or it cannot be read. The one walk of `size_limit_of` and
    `image_size_limit_of`."""
    try:
        import runtime_paths
        project = runtime_paths.nearest_project(task_root)
        if project is not None:
            cfg = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
            return cfg if isinstance(cfg, dict) else None
    except Exception:
        pass
    return None


def size_limit_of(task_root) -> int:
    """The size from which a role cannot open a file whole (`guard_pre_tool.big_read_cap`) in the config of the project the
    TASK lives in (`_task_config`). 0 = it cannot be told (no config, an unreadable one): a size then decides nothing and the
    point is asked (FR-59, FR-15)."""
    cfg = _task_config(task_root)
    if cfg is None:
        return 0
    try:
        import guard_pre_tool
        return int(guard_pre_tool.big_read_cap(cfg))
    except Exception:
        return 0


def image_size_limit_of(task_root) -> int:
    """The size from which a role cannot open a PICTURE whole (`guard_pre_tool.big_read_image_cap`, the one reader of
    `read.max_image_bytes`) in the config of the project the TASK lives in. 0 = it cannot be told: `defaulted` then keeps the text
    limit for a picture, the old meaning (FR-59)."""
    cfg = _task_config(task_root)
    if cfg is None:
        return 0
    try:
        import guard_pre_tool
        return int(guard_pre_tool.big_read_image_cap(cfg))
    except Exception:
        return 0


def defaulted(item: dict, point: dict, default_causes=None, vcs_codes=None, size_limit=None, image_size_limit=None) -> str:
    """The BASIS (a sentence) when the factory itself established that this GAP point cannot be reached, else `""`. The
    existing fields in a more responsible role (a hint that becomes the end of a question), so the error goes ONE way: any
    doubt gives `""` and the point is asked (FR-59). True only when ALL hold: a gap point of an attachment or a media item; its
    cause is in `default_causes`; and the carrier of that cause is in the row -
      probe       a `probe_ref`/`probe_code` whose code the table maps to `host_unreachable` (media only; the writer checked
                  the receipt, `verify_inventory_files` its hash);
      structural  `no_tool` on a URL that is not a merge/pull request (media only; the collector for those exists);
      size        a measured `size` (an int, not a bool, >= 0) at or above the read limit OF ITS KIND (attachments only): the text
                  limit (`size_limit`) for a text file or a PDF, the larger of that and `image_size_limit` for a picture or a file
                  of unknown form (`branch_accounting.read_form`, the one reader). With no `image_size_limit` the text limit
                  decides for every row (the old meaning). The larger limit is the safe side: it defaults fewer points.
    `forbidden_by_policy` has no carrier (no record of the run's standing decision exists to check it against): a role's
    word alone is never a default, on any address, and the point is asked (FR-59, the critic's F-1)."""
    if default_causes is None:
        default_causes, vcs_codes, _ = _default_causes()
    if point.get("class") != POINT_GAP or point.get("kind") not in {"attachment", "media"}:
        return ""
    cause = point_cause(item, point)
    carrier = default_causes.get(cause) if cause else None
    row = _point_row(item, point)
    if not carrier or row is None:
        return ""
    if carrier == "probe":
        ref, code = row.get("probe_ref"), row.get("probe_code")
        if (point["kind"] != "media" or not _safe_rel(ref) or not isinstance(code, str)
                or (vcs_codes or {}).get(code) != "host_unreachable"):
            return ""
        return f"the factory's own collector answered {code} (receipt {ref})"
    if carrier == "structural":
        url = row.get("url")
        if point["kind"] != "media" or not isinstance(url, str) or not url.strip() or VCS_URL_RE.search(normalize_url(url)):
            return ""
        return "nothing in this run can open that kind of address"
    if carrier == "size":
        size = row.get("size")
        limit = size_limit or 0
        if image_size_limit is not None and point["kind"] == "attachment":
            try:
                import branch_accounting
                form = branch_accounting.read_form(row.get("media_type"), row.get("filename") or row.get("local_ref"))
            except Exception:
                form = ""
            if form in ("limit_1", ""):
                limit = max(limit, image_size_limit if isinstance(image_size_limit, int) and not isinstance(image_size_limit, bool) else 0)
        if (point["kind"] != "attachment" or isinstance(size, bool) or not isinstance(size, int) or size < 0
                or not isinstance(limit, int) or limit <= 0 or size < limit):
            return ""
        return f"measured size {size} bytes, over the {limit} bytes a role can open"
    return ""


def _live_class(row) -> bool:
    return (isinstance(row, dict) and not row.get("revoked_at") and str(row.get("words") or "").strip() != ""
            and (row.get("cause") in MEDIA_CAUSES or row.get("cause") == SOURCE_UNAVAILABLE))


def gap_classes_path(task_root) -> Path:
    return Path(task_root) / "work" / GAP_CLASSES_FILE


def live_gap_classes(task_root) -> tuple:
    """`(rows, problem)`: the live rows of `work/gap-classes.json` - one answer of a person about a whole KIND of gap, kept for
    the story (D-0043). No file: `([], "")`. A file that cannot be read: `([], <why>)` - it covers nothing (FR-59)."""
    import environment_record
    rows, problem = environment_record.load_rows(gap_classes_path(task_root), GAP_CLASSES_KEY, GAP_CLASSES_SCHEMA,
                                                 f"work/{GAP_CLASSES_FILE}")
    return [row for row in rows if not row.get("revoked_at")], problem


def class_kwargs(task_root) -> dict:
    """The keyword arguments `completeness` takes for a story - its class record and the read limit of ITS project - the callers' one line."""
    rows, problem = live_gap_classes(task_root)
    return {"classes": rows, "class_problem": problem, "size_limit": size_limit_of(task_root),
            "image_size_limit": image_size_limit_of(task_root)}


def record_gap_class(output, causes, words, shown, story) -> tuple:
    """`(written, already, problem)`: one live row per cause, with the person's words whole. A cause outside `media_causes` and
    `source_unavailable` is a `ValueError` listing them (FR-1). A cause that has a live row stays as it is (`already`: the
    earlier words stand). An unreadable file is a problem and nothing is written over it."""
    import environment_record
    cause_table()
    allowed = list(MEDIA_CAUSES) + [SOURCE_UNAVAILABLE]
    causes = list(dict.fromkeys(str(value).strip() for value in causes))
    unknown = [value for value in causes if value not in allowed]
    if not causes or unknown:
        raise ValueError(f"unknown cause {', '.join(unknown) or '(none given)'}; the kinds of gap a word can cover: "
                         + ", ".join(allowed))
    text = str(words or "").strip()
    if not text:
        raise ValueError("a kind of gap is accepted in the person's own words; --words is empty")
    path = gap_classes_path(Path(output).parent.parent)
    rows, problem = environment_record.load_rows(path, GAP_CLASSES_KEY, GAP_CLASSES_SCHEMA, f"work/{GAP_CLASSES_FILE}")
    if problem:
        return [], [], problem + "; nothing was written over it"
    written, already = [], []
    for cause in causes:
        held = next((row for row in rows if not row.get("revoked_at") and row.get("cause") == cause), None)
        if held is not None:
            already.append(held)
            continue
        row = {"id": environment_record.next_id(rows + written, "GC-"), "cause": cause, "words": text,
               "shown": " ".join(str(shown or "").split()), "by": "human", "at": utc_now(), "story": str(story or ""),
               "revoked_at": None, "revoked_words": None}
        written.append(row)
    if written:
        problem = environment_record.write_rows(path, GAP_CLASSES_KEY, GAP_CLASSES_SCHEMA, rows + written,
                                                f"work/{GAP_CLASSES_FILE}")
        if problem:
            return [], [], problem
    return written, already, ""


def revoke_gap_class(output, gc_id, words, s1_closed) -> tuple:
    """`(row, problem)`: take a kind back. After S1 closed it is refused with the door (I7: taking it back would re-open
    sources the later stages were planned on); before, the row stays with `revoked_at` and the words said now."""
    import environment_record
    if s1_closed:
        return None, (f"{gc_id} cannot be taken back: S1 of this story is closed, and taking it back would re-open sources the "
                      "later stages were planned on. A source to be read after S1 goes through a rework of S1: the conductor's "
                      "`rework_stage` S1 with the person's words.")
    path = gap_classes_path(Path(output).parent.parent)
    live, problem = live_gap_classes(Path(output).parent.parent)
    if problem:
        return None, problem + "; nothing was written over it"
    if gc_id not in {str(row.get("id")) for row in live}:
        return None, f"{gc_id} is not a live record of a kind of gap; the live ones: " + (", ".join(
            f"{row.get('id')} ({row.get('cause')})" for row in live) or "none")
    return environment_record.revoke_row(path, GAP_CLASSES_KEY, GAP_CLASSES_SCHEMA, gc_id, words, "`ticket_adapter.py accept-gap`",
                                         noun="record", label=f"work/{GAP_CLASSES_FILE}")


def gap_words(item: dict, closed_by_class: dict, classes) -> str:
    """The words a person gave for the gaps of ONE source: its point acceptance, and the words of every kind record
    (`class_ref`) that closed a point of it. The one helper of the readers that print them (N4)."""
    acceptance = item.get("gap_acceptance") if isinstance(item.get("gap_acceptance"), dict) else {}
    parts = []
    first = str(acceptance.get("words") or "").strip()
    if first:
        parts.append(first)
    by_id = {str(row.get("id")): row for row in classes or [] if isinstance(row, dict)}
    for gc in dict.fromkeys((closed_by_class or {}).get(item.get("source_id"), {}).values()):
        words = str((by_id.get(gc) or {}).get("words") or "").strip()
        if words and words not in parts:
            parts.append(words)
    return " | ".join(parts)


def class_basis(closed_by_class: dict, classes, source_id) -> str:
    """The provenance sentence of a point closed by a kind record (D-0047): whose word, when - read from the record, with the
    file named when the record has no date; `""` when no kind record closed anything of the source."""
    by_id = {str(row.get("id")): row for row in classes or [] if isinstance(row, dict)}
    out = []
    for gc in dict.fromkeys((closed_by_class or {}).get(source_id, {}).values()):
        row = by_id.get(gc)
        if row is None:
            out.append(f"by the record work/{GAP_CLASSES_FILE}")
            continue
        when = str(row.get("at") or "")[:10]
        out.append(f"on the basis of your answer {gc}" + (f" of {when}" if when else f" (work/{GAP_CLASSES_FILE})")
                   + f": \"{' '.join(str(row.get('words') or '').split())[:120]}\"")
    return "; ".join(out)


def completeness(inventory: dict, s1_closed: bool = False, classes=None, class_problem: str = "",
                 size_limit=None, image_size_limit=None) -> dict:
    """What still stands between this inventory and the next stage.

    Three rules, each one a lesson of a story that halted three times at S1:
    an excluded source owes no materials — nobody inspects the attachments of a ticket
    that was judged unrelated; a gap a person accepted in their own words stops blocking
    and stays on the record as `accepted_gaps`; and no inventory passes before a person
    has been shown which sources the factory kept and which it left out.

    The unit of an acceptance is a POINT (`gap_points`), not the source: a source is in
    `accepted_gaps` when at least one of its points is closed, and it is still in a blocking list
    for every point that is not - one source can be in both. `open_points` and `closed_by_person`
    give the point ids per source.

    `s1_closed`: the story's S1 is already `completed`. Its recorded acceptance keeps the OLD
    meaning (the whole source stops blocking) so that a story in flight is not re-blocked at every
    later dispatch (builder-rules 9); `earlier_rule_line` then says so in one line. The caller knows
    the stage (`controller.source_inputs` and `project` pass it from the state); this module reads no
    pipeline file. An acceptance recorded with `accepted_points` and with no `legacy` record is a point
    acceptance under both; one that carries the `legacy` copy of an older whole-source acceptance keeps
    its old meaning for a closed S1 even after points were added on top of it."""
    pending, unavailable, incomplete_materials, unavailable_materials = [], [], [], []
    accepted_gaps, unreviewed = [], []
    open_by_source, closed_by_source, earlier_sources = {}, {}, []
    closed_by_class, defaulted_points, defaulted_gaps = {}, {}, []
    default_causes, vcs_codes, table_problem = _default_causes()
    live_classes = [row for row in classes or [] if _live_class(row)] if not class_problem else []
    required_sources = [item for item in inventory.get("sources", []) if item.get("required")]
    for item in required_sources:
        source_id = item.get("source_id")
        if not _reviewed(item):
            unreviewed.append(source_id)
        if item.get("status") == "excluded" and item.get("relevance") == "not_relevant":
            continue
        details = _gap_point_details(item)
        if not details:
            continue
        if s1_closed and _legacy_record(item.get("gap_acceptance")) is not None:
            accepted_gaps.append(source_id)
            closed_by_source.setdefault(source_id, []).extend(point["id"] for point, _ in details)
            if any(point["class"] == POINT_WORK for point, _ in details):
                earlier_sources.append(item)
            continue
        closed = _closed_point_ids(item, details)
        if closed:
            accepted_gaps.append(source_id)
            closed_by_source.setdefault(source_id, []).extend(
                point["id"] for point, _ in details if point["id"] in closed)
        for point, _ in details:
            if point["id"] in closed:
                continue
            if point["class"] == POINT_GAP:
                # The order on a point: the person's word on it (above) -> a kind the person answered -> the factory's own
                # verdict. A WORK point never reaches here (I3); a point outside all three stays in the lists below and is asked.
                cause = point_cause(item, point)
                cover = next((row for row in live_classes if cause and row["cause"] == cause), None)
                if cover is None and s1_closed and class_problem:
                    cover = {"id": "unreadable"}     # G3: a closed S1 is not blocked again by a record that cannot be read
                if cover is not None:
                    closed_by_class.setdefault(source_id, {})[point["id"]] = cover["id"]
                    accepted_gaps.append(source_id)
                    continue
                basis = defaulted(item, point, default_causes, vcs_codes, size_limit, image_size_limit)
                if basis:
                    defaulted_points.setdefault(source_id, []).append(
                        {"id": point["id"], "cause": cause, "name": point["name"] or point["text"],
                         "text": point["text"], "basis": basis})
                    defaulted_gaps.append(source_id)
                    continue
            open_by_source.setdefault(source_id, []).append(point["id"])
            if point["id"] == "source:pending":
                pending.append(source_id)
            elif point["id"] == "source:unavailable":
                unavailable.append(source_id)
            elif point["class"] == POINT_WORK:
                incomplete_materials.append(source_id)
            else:
                unavailable_materials.append(source_id)
    incomplete_materials = sorted(set(incomplete_materials))
    unavailable_materials = sorted(set(unavailable_materials))
    accepted_gaps = sorted(set(accepted_gaps))
    defaulted_gaps = sorted(set(defaulted_gaps))
    earlier_line = ""
    if earlier_sources:
        earlier_line = ("S1 closed under the earlier acceptance rule: "
                        + ", ".join(sorted({_key(item) for item in earlier_sources})) + " not inspected")
    # A source found after the review is shown at gate A; only an inventory nobody has
    # looked at at all is a silent pass.
    review_missing = bool(required_sources) and len(unreviewed) == len(required_sources)
    blocking = bool(pending or unavailable or incomplete_materials or unavailable_materials)
    # Informational only (F7): what the person left out before the run owes nothing and is read by
    # no blocking list above - gate A and the retro name it. `{}` means nothing was left out by word.
    left_out_by_word = {}
    for item in inventory.get("sources", []):
        names = [_key(item)] if isinstance(item.get("excluded_by"), dict) else []
        names += [str(row.get("url")) for row in _item_rows((item.get("materials") or {}).get("external_media") or {})
                  if isinstance(row.get("excluded_by"), dict)]
        if names:
            left_out_by_word[item.get("source_id")] = names
    return {"complete": bool(required_sources) and not blocking and not accepted_gaps,
            "gate_blocked": not required_sources or blocking or review_missing,
            "pending": pending, "unavailable": unavailable,
            "incomplete_materials": incomplete_materials,
            "unavailable_materials": unavailable_materials,
            "accepted_gaps": accepted_gaps,
            "review_missing": review_missing,
            "unreviewed": [] if review_missing else sorted(set(unreviewed)),
            "awaiting_review": review_missing and not any(
                item.get("relevance") == "pending" for item in required_sources),
            "open_points": open_by_source, "closed_by_person": closed_by_source,
            "closed_by_class": closed_by_class, "defaulted_points": defaulted_points, "defaulted_gaps": defaulted_gaps,
            "gap_class_problem": class_problem or table_problem,
            "left_out_by_word": left_out_by_word,
            "earlier_rule_line": earlier_line,
            "earlier_rule_sources": sorted({str(item.get("source_id")) for item in earlier_sources})}


def verify_inventory_files(root: Path, inventory: dict | None = None) -> dict:
    """Verify persisted source evidence beneath a task root without mutating the inventory."""
    root = Path(root).resolve()
    inventory_path = root / "work" / "source-inventory.json"
    inventory = inventory if inventory is not None else load_inventory(inventory_path)
    work = (root / "work").resolve()
    errors, invalid_source_ids = [], set()

    def verify_ref(source_id: str, label: str, ref, expected) -> None:
        if not ref or not expected:
            errors.append(f"{source_id} {label} lacks ref or content_hash")
            invalid_source_ids.add(source_id)
            return
        path = (work / str(ref)).resolve()
        try:
            path.relative_to(work)
        except ValueError:
            errors.append(f"{source_id} {label} escapes work root")
            invalid_source_ids.add(source_id)
            return
        if not path.is_file():
            errors.append(f"{source_id} {label} is missing")
            invalid_source_ids.add(source_id)
        elif sha256_bytes(path.read_bytes()) != expected:
            errors.append(f"{source_id} {label} content hash changed")
            invalid_source_ids.add(source_id)

    for item in inventory.get("sources", []):
        if item.get("status") != "read":
            continue
        source_id = str(item.get("source_id") or "unknown")
        verify_ref(source_id, "snapshot", item.get("snapshot_ref"), item.get("content_hash"))
        for receipt in ((item.get("materials") or {}).get("attachments") or {}).get("items") or []:
            if receipt.get("status") == "read":
                verify_ref(source_id, f"attachment {receipt.get('attachment_id')}",
                           receipt.get("local_ref"), receipt.get("content_hash"))
        for receipt in ((item.get("materials") or {}).get("external_media") or {}).get("items") or []:
            if receipt.get("status") == "read":
                verify_ref(source_id, f"external media {receipt.get('url')}",
                           receipt.get("local_ref"), receipt.get("content_hash"))
            if receipt.get("probe_ref") and receipt.get("status") == "unavailable":
                # the carrier of a `host_unreachable` default (C2-9): a receipt that changed is not the one the verdict was made on
                verify_ref(source_id, f"probe receipt of {receipt.get('url')}",
                           receipt.get("probe_ref"), receipt.get("probe_sha256"))
    return {"valid": not errors, "errors": errors,
            "invalid_source_ids": sorted(invalid_source_ids),
            "requires_refresh": bool(errors)}


STAMP_BY = "code:snapshot"   # `inspection_by` of a receipt the CODE wrote: the snapshot lies on disk, whole


def snapshot_receipt(item: dict, invalid_ids) -> bool:
    """Is this source's snapshot a fact the code can receipt? (t-721 3.5, K2-12/K9-6.) The source was READ, it names its
    snapshot and the snapshot's hash, and its files verify (`verify_inventory_files`: under `work/`, sha256 equal) -
    `invalid_ids` is that function's `invalid_source_ids`. The receipt is a fact of the disk, not a judgment: what the
    role judges (relevance) stays `assess`."""
    return (item.get("status") == "read" and bool(item.get("snapshot_ref")) and bool(item.get("content_hash"))
            and item.get("source_id") not in invalid_ids)


def _stamp(item: dict) -> None:
    item.update(inspection_status="read", inspection_ref=item["snapshot_ref"], inspection_by=STAMP_BY)


def stamp_snapshot_receipts(output: Path) -> tuple:
    """`(stamped, left)`: write the receipt on every source of the inventory that has the fact and no `read` receipt yet.
    Idempotent (a second run stamps 0) and never over a receipt a role wrote (`assess` wins). The one door for a story
    that was running before the writer stamped (`ticket_adapter.py receipts`)."""
    inventory = load_inventory(output)
    invalid = set(verify_inventory_files(Path(output).resolve().parent.parent, inventory)["invalid_source_ids"])
    stamped = 0
    for item in inventory.get("sources", []):
        if item.get("inspection_status") != "read" and snapshot_receipt(item, invalid):
            _stamp(item)
            stamped += 1
    if stamped:
        _write_inventory(output, inventory)
    return stamped, len(inventory.get("sources", [])) - stamped


def record_attachment_inspection(output: Path, source_id: str, attachment_id: str,
                                 status: str, evidence_ref: str, reason: str = "") -> dict:
    if status not in {"read", "skipped", "unavailable"}:
        raise ValueError("inspection status must be read, skipped or unavailable")
    if not _safe_rel(evidence_ref):
        raise ValueError("inspection evidence_ref must be a task-relative safe path")
    inventory = load_inventory(output)
    matches = []
    for source in inventory.get("sources", []):
        if source.get("source_id") != source_id:
            continue
        for receipt in ((source.get("materials") or {}).get("attachments") or {}).get("items") or []:
            if str(receipt.get("attachment_id")) == str(attachment_id):
                matches.append(receipt)
    if len(matches) != 1:
        raise ValueError(_attachment_refusal(inventory, source_id, attachment_id, matches))
    receipt = matches[0]
    if receipt.get("status") != "read" and status == "read":
        raise ValueError("attachment bytes must be read before inspection can be read")
    cause = ""
    if status == "skipped":
        # A DECISION not to open it, which is a different fact from not being able to: the judge's
        # `disc_attachment_worth_opening` verdict lands here. It must name who decided, and it stays
        # a visible gap in `completeness` — the judge closes nothing on its own.
        if not re.match(r"skipped_by_(judge|person|role)", reason.strip()):
            raise ValueError("a skipped attachment must name who decided: --reason "
                             '"skipped_by_judge|skipped_by_person|skipped_by_role: <why>"')
    if status == "unavailable":
        # The same rule as external media, for the same reason: on TP1-13797 an attachment of
        # the precedent ticket stood `analysis_status: unavailable` with `error: null`, so the
        # person's question said "attachment: ? — no cause recorded" and named neither the file nor
        # what went wrong. A screenshot no role can read is `no_tool`, and that cause is what tells
        # the person they can look at it themselves and paste what it shows.
        cause, fact = media_cause(reason)
        if not cause or not fact:
            raise ValueError(
                "an uninspected attachment needs a cause from the closed list and then the fact you "
                'observed: --reason "<cause>: <what you tried and what answered>". Causes: '
                + "; ".join(f"{name} ({what})" for name, what in MEDIA_CAUSES.items())
                + ". A screenshot or a video no role in this run can read is `no_tool` — say so, and "
                "the person can read it themselves; a judgement that it is not needed is not a cause")
    receipt.update(analysis_status=status, analysis_evidence_ref=evidence_ref,
                   analysis_reason=reason or None, analyzed_at=utc_now(),
                   analysis_cause=cause or None,
                   access_problem=cause in ACCESS_CAUSES if cause else None)
    _atomic_write(output, json.dumps(inventory, indent=2, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8") + b"\n")
    return inventory


def record_relevance_assessment(output: Path, source_id: str, relevance: str,
                                reason: str, assessment_ref: str) -> dict:
    if relevance not in {"relevant", "not_relevant", "unknown"} or not reason.strip():
        raise ValueError("assessment needs relevant|not_relevant|unknown and a nonempty reason")
    if not _safe_rel(assessment_ref):
        raise ValueError("assessment_ref must be a task-relative safe path")
    inventory = load_inventory(output)
    matches = [item for item in inventory.get("sources", []) if item.get("source_id") == source_id]
    if len(matches) != 1:
        raise ValueError("source_id must identify exactly one source")
    item = matches[0]
    if isinstance(item.get("excluded_by"), dict):
        # The person's word before the run outranks a role's assessment: "relevant" is refused, and
        # the other two would only repeat what is recorded, so they change nothing (FR-57: a ban with
        # its door - the handoff, where the person sees it at the source review).
        shown = str(item.get("relevance_reason") or "")
        shown = shown[len(LEFT_OUT_PREFIX):].strip('"') if shown.startswith(LEFT_OUT_PREFIX) else shown
        if relevance == "relevant":
            import source_exclusions
            raise ValueError(source_exclusions.refusal_text(_key(item), shown)
                             + " Only the person can take the exclusion back.")
        print("already left out by the person's word before the run; nothing changed", file=sys.stderr)
        return inventory
    item.update(relevance=relevance, relevance_reason=reason, assessment_ref=assessment_ref)
    if relevance == "not_relevant":
        item.update(status="excluded", exclusion_or_error=reason)
    elif relevance == "unknown":
        item.update(status="unavailable", exclusion_or_error=reason)
    elif item.get("status") == "read":
        # The role's assessment outranks the code's stamp (t-721 3.5): it carries a judgment, the stamp only the fact
        # that the file lies there - so over a stamp it takes `inspection_ref` and clears the code's mark.
        item.update(inspection_status="read", inspection_ref=assessment_ref)
        item.pop("inspection_by", None)
    # Relevant remains pending until the complete collector replaces it.
    _atomic_write(output, json.dumps(inventory, indent=2, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8") + b"\n")
    return inventory


def _write_inventory(output: Path, inventory: dict) -> dict:
    _atomic_write(output, json.dumps(inventory, indent=2, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8") + b"\n")
    return inventory


def _valid_points_text(item: dict) -> str:
    points = gap_points(item)
    return "; ".join(f"{p['id']} = {p['text']}" for p in points) or "none - this source has no open point"


def _stored_entry(point: dict, item: dict, words: str, by: str, at: str, shown: bool,
                  shown_text: str = "") -> dict:
    entry = {"id": point["id"], "kind": point["kind"], "class": point["class"], "text": point["text"],
             "words": words, "by": by, "at": at, "revision": item.get("revision"), "shown": shown}
    if point["class"] == POINT_WORK:
        # The factory's own work passed on a person's word: only with the sentence they were shown,
        # and it is the factory's to report (FR-4), so the entry says whose it is.
        entry.update(factory_owned=True, shown_text=shown_text.strip())
    return entry


def _migrate_legacy_entries(item: dict, acceptance: dict) -> list:
    """The first point acceptance on a source that carries an older, whole-source one: what the old
    record still closes (`_legacy_closed_ids`) becomes stored points, so recording one more point does
    not quietly re-open what the person had accepted before."""
    if not isinstance(acceptance, dict) or not _gap_accepted(item):
        return []
    details = _gap_point_details(item)
    closed = _legacy_closed_ids(item, details, acceptance)
    words = str(acceptance.get("words") or "").strip()
    return [dict(_stored_entry(point, item, words, str(acceptance.get("by") or "human"),
                               str(acceptance.get("at") or ""), False), legacy=True)
            for point, _ in details if point["id"] in closed]


def apply_gap_acceptance(output: Path, source_ids: list, words: str, by: str = "human",
                         points: list | None = None, shown_text: str | None = None) -> tuple:
    """`record_gap_acceptance` with a report: (inventory, {"accepted": {source_id: [point]},
    "already_accepted": {source_id: [point]}, "no_longer_open": {source_id: [id]},
    "factory_owned": [{source_id, id, text}], "shown_text_unused": bool}). `accepted` names every point
    the call asked for that is open (what the old readers print); `already_accepted` is the part of it an
    earlier acceptance still in force already closed - nothing was recorded for those."""
    words = str(words or "").strip()
    if not words:
        raise ValueError("a gap is accepted in the person's own words; --words is empty")
    inventory = load_inventory(output)
    by_id = {item.get("source_id"): item for item in inventory.get("sources", [])}
    source_ids = list(dict.fromkeys(source_ids))
    unknown = [sid for sid in source_ids if sid not in by_id]
    if unknown:
        raise ValueError("unknown source_id: " + ", ".join(unknown))
    plan, no_longer = {}, {}
    if points is not None:
        if len(source_ids) != 1:
            raise ValueError("--point names points of ONE source: pass exactly one --source-id with it "
                             "(or drop --point to accept every open gap of each named source)")
        sid = source_ids[0]
        item = by_id[sid]
        ids = [str(value).strip() for value in points]
        if not ids or any(not value for value in ids):
            raise ValueError(f"--point needs point ids and none of them empty; the points of {sid}: "
                             + _valid_points_text(item))
        repeated = sorted({value for value in ids if ids.count(value) > 1})
        if repeated:
            raise ValueError(f"--point names {', '.join(repeated)} more than once; the points of {sid}: "
                             + _valid_points_text(item))
        open_now = {point["id"]: point for point in gap_points(item)}
        known = _all_point_ids(item)
        foreign = [value for value in ids if value not in open_now and value not in known]
        if foreign:
            raise ValueError(f"{sid} has no point {', '.join(foreign)}; its open points: "
                             + _valid_points_text(item)
                             + ". Use: " + person_words.door(
                                 f"ticket_adapter.py accept-gap --output <inventory> --source-id {sid} "
                                 "--point <id>[,<id>]"))
        chosen = [open_now[value] for value in ids if value in open_now]
        no_longer[sid] = [value for value in ids if value not in open_now]
        work = [point for point in chosen if point["class"] == POINT_WORK]
        if work and not str(shown_text or "").strip():
            raise ValueError("a point of the factory's own work (" + ", ".join(p["id"] for p in work)
                             + ") passes only with the sentence the person was shown: add "
                               '--shown-text "<that sentence, as the person read it>" - a role\'s unfinished '
                               "work is the role's to finish, and a person's word passes it only when "
                               "they were told what it is")
        plan[sid] = chosen
    else:
        for sid in source_ids:
            found = gap_points(by_id[sid])
            gaps = [point for point in found if point["class"] == POINT_GAP]
            if not gaps:
                work = [point["text"] for point in found]
                raise ValueError(f"{sid} has no open gap to accept"
                                 + (" - its open points are the role's work, not a gap: " + "; ".join(work)
                                    if work else ""))
            plan[sid] = gaps
    at = utc_now()
    report = {"accepted": {}, "already_accepted": {},
              "no_longer_open": {sid: ids for sid, ids in no_longer.items() if ids},
              "factory_owned": [], "shown_text_unused": False}
    changed = False
    for sid, chosen in plan.items():
        if not chosen:
            continue
        item = by_id[sid]
        acceptance = item.get("gap_acceptance") if isinstance(item.get("gap_acceptance"), dict) else {}
        stored = acceptance.get("accepted_points")
        entries = ([entry for entry in stored if isinstance(entry, dict)] if isinstance(stored, list)
                   else _migrate_legacy_entries(item, acceptance))
        # The older whole-source record is KEPT whole, beside the points it was migrated into: a story
        # whose S1 is already closed still reads it with its old meaning (`completeness(s1_closed=True)`),
        # and recording one point on top must not quietly take that away.
        older = _legacy_record(acceptance)
        legacy = ({"words": str(older.get("words") or "").strip(), "by": str(older.get("by") or "human"),
                   "at": str(older.get("at") or ""),
                   "accepted": list(older["accepted"]) if isinstance(older.get("accepted"), list) else []}
                  if older is not None else None)
        added = False
        for point in chosen:
            report["accepted"].setdefault(sid, []).append(point)
            if any(_entry_in_force(entry, point, item) for entry in entries if entry.get("id") == point["id"]):
                report["already_accepted"].setdefault(sid, []).append(point)
                continue  # an acceptance still in force is never overwritten: each point keeps its own words
            entries = [entry for entry in entries if entry.get("id") != point["id"]]
            entries.append(_stored_entry(point, item, words, by, at, shown=points is not None,
                                         shown_text=str(shown_text or "")))
            added = True
            if point["class"] == POINT_WORK:
                report["factory_owned"].append({"source_id": sid, "id": point["id"], "text": point["text"]})
        if added:
            texts = list(dict.fromkeys(str(entry.get("text")) for entry in entries))
            item["gap_acceptance"] = {"words": words, "by": by, "at": at, "accepted": texts,
                                      "accepted_points": entries}
            if legacy is not None:
                item["gap_acceptance"]["legacy"] = legacy
            changed = True
    report["shown_text_unused"] = bool(str(shown_text or "").strip()) and not report["factory_owned"]
    if changed:
        _write_inventory(output, inventory)
    return inventory, report


def record_gap_acceptance(output: Path, source_ids: list[str], words: str,
                          by: str = "human", points: list | None = None,
                          shown_text: str | None = None) -> dict:
    """A person said, in their own words, that the story goes on without this. The facts
    stay as they are — unavailable stays unavailable — and the gate stops blocking on the points
    they accepted, and on those only.

    Without `points`: every open GAP-class point of each named source, never one of the factory's
    own work (not read, not inspected, still pending): a source whose only open points are that work
    is refused, because accepting it would be a blank cheque. With `points` (ids of ONE source): those
    ids that are open; an id that is no longer open (the material arrived meanwhile) is skipped and
    reported by `apply_gap_acceptance`, an id that never existed on the source is refused with the
    valid list. A work-class id needs `shown_text`, the sentence the person was shown (FR-4: the pass
    is stored `factory_owned` and the caller files it as a factory finding)."""
    return apply_gap_acceptance(output, source_ids, words, by, points, shown_text)[0]


def sources_with_open_gaps(inventory: dict) -> list[str]:
    summary = completeness(inventory)
    return sorted(set(summary["unavailable"]) | set(summary["unavailable_materials"]))


# The factory's own narration about a silence is not the person's answer:
# TP1-15045 recorded "person replied only '...' and did not object" as if it were one.
# The check is deliberately narrow — it catches the factory describing what happened around
# an answer, not any particular short or terse reply.
_NARRATION_PHRASES = ("did not object", "no objection", "person replied", "was shown to")


def record_source_review(output: Path, words: str, by: str = "human") -> dict:
    """The person was shown every source with the factory's decision and answered. The
    decision they saw is stored beside their words, so a later flip is visible as a flip."""
    if not str(words or "").strip():
        raise ValueError("a review is recorded with the person's own words; --words is empty")
    hit = next((p for p in _NARRATION_PHRASES if p in words.lower()), None)
    if hit:
        raise ValueError(f"--words reads like the factory's own narration ('{hit}'), not a "
                         "person's answer — a source only shown at a gate, with no answer "
                         "from the person, is marked with `review --late`, not recorded here")
    inventory = load_inventory(output)
    undecided = [item.get("source_id") for item in inventory.get("sources", [])
                 if item.get("required") and item.get("relevance") == "pending"]
    if undecided:
        raise ValueError("assess these sources before showing the review: " + ", ".join(undecided))
    at = utc_now()
    for item in inventory.get("sources", []):
        if not item.get("required"):
            continue
        shown = {"relevance": item.get("relevance"), "status": item.get("status")}
        if _reviewed(item):
            continue
        item["human_review"] = {"words": words.strip(), "by": by, "at": at, "shown": shown}
        item.pop("shown_at_gate", None)
    return _write_inventory(output, inventory)


def record_late_review(output: Path, gate: str = "A") -> tuple[dict, list[str]]:
    """A source discovered after the review is shown at the next gate and marked as shown —
    with no words, because none were given. It stops appearing among the sources
    still awaiting review; it is not recorded as one the person answered."""
    inventory = load_inventory(output)
    at = utc_now()
    marked = []
    for item in inventory.get("sources", []):
        if not item.get("required") or _reviewed(item) or _late(item):
            continue
        shown = {"relevance": item.get("relevance"), "status": item.get("status")}
        item["shown_at_gate"] = {"gate": gate, "at": at, "shown": shown}
        marked.append(item.get("source_id"))
    return _write_inventory(output, inventory), marked


def review_rows(inventory: dict, only_unreviewed: bool = False) -> list[dict]:
    """One row per source for the person: what it is, what the factory decided, and why."""
    rows = []
    for item in inventory.get("sources", []):
        if not item.get("required"):
            continue
        seen = _reviewed(item)
        late = _late(item)
        if only_unreviewed and (seen or late):
            continue
        key = str(item.get("canonical_ref") or "").rsplit("/browse/", 1)[-1]
        decision = {"relevant": "kept", "not_relevant": "left out",
                    "unknown": "cannot tell", "pending": "not assessed"}.get(item.get("relevance"), "?")
        if item.get("not_found"):
            decision = "not found (404)"
        reason = item.get("relevance_reason") or item.get("exclusion_or_error") or ""
        if isinstance(item.get("excluded_by"), dict):
            # The person's own word, given before the run: said as theirs, with their reason.
            decision = LEFT_OUT_BY_WORD
            words = str(reason)[len(LEFT_OUT_PREFIX):].strip('"') if str(reason).startswith(LEFT_OUT_PREFIX) else str(reason)
            reason = f'your word before the run: "{_clip(words)}"'
        # Point by point: `(accepted by you)` belongs to a point the acceptance actually closes, not
        # to a source whose person said something once.
        details = [] if item.get("relevance") == "not_relevant" else _gap_point_details(item)
        closed = _closed_point_ids(item, details)
        tail = " left out by your word before the run"
        left_out_media = [f"external material {_short_url(str(row.get('url') or ''), POINT_TEXT_LIMIT - 18 - len(tail))}:{tail}"
                          for row in _item_rows((item.get("materials") or {}).get("external_media") or {})
                          if isinstance(row.get("excluded_by"), dict)]
        rows.append({"source_id": item.get("source_id"), "key": key,
                     "relation": item.get("relation"), "decision": decision,
                     "reason": reason,
                     "open_points": [point["text"] for point, _ in details],
                     "points": [dict(point, closed=point["id"] in closed) for point, _ in details],
                     "left_out_media": left_out_media,
                     "gap_accepted": _gap_accepted(item), "reviewed": seen, "late": late})
    order = {"kept": 0, "cannot tell": 1, "not assessed": 2, "not found (404)": 3, "left out": 4,
             LEFT_OUT_BY_WORD: 5}
    rows.sort(key=lambda row: (order.get(row["decision"], 9), row["key"]))
    return rows


def _collapse_not_found(rows: list[dict]) -> list[dict]:
    """56 sources, 51 of them a 404 for local document numbering: one line each still
    buries the five real decisions in the table. Two or more collapse into one row that names
    every prefix and the total count; one alone is not worth collapsing."""
    not_found = [row for row in rows if row["decision"] == "not found (404)"]
    if len(not_found) < 2:
        return rows
    prefixes = sorted({row["key"].rsplit("-", 1)[0] for row in not_found})
    shown_prefixes = ", ".join(prefixes[:6]) + (" …" if len(prefixes) > 6 else "")
    collapsed = {"key": f"{len(not_found)} key-shaped tokens of {len(prefixes)} unknown "
                        f"prefixes: {shown_prefixes}",
                "relation": "referenced", "decision": "not found (404)",
                "reason": "not tracker issues", "open_points": [], "gap_accepted": False,
                "reviewed": all(row["reviewed"] for row in not_found)}
    result, folded = [], False
    for row in rows:
        if row["decision"] != "not found (404)":
            result.append(row)
        elif not folded:
            result.append(collapsed)
            folded = True
    return result


def render_review(rows: list[dict], expand_not_found: bool = False) -> str:
    if not rows:
        return "No source is waiting for your review."
    display_rows = rows if expand_not_found else _collapse_not_found(rows)
    lines = ["| Source | Why it is here | Factory decision | Reason | Open points |",
             "|---|---|---|---|---|"]
    for row in display_rows:
        if row.get("points"):
            points = "; ".join(p["text"] + (" (accepted by you)" if p.get("closed") else "")
                               for p in row["points"])
        else:
            points = "; ".join(row["open_points"]) or "-"
        if row.get("left_out_media"):
            points = "; ".join(([] if points == "-" else [points]) + row["left_out_media"])
        reason = " ".join(str(row["reason"]).replace("|", "/").split())
        lines.append(f"| {row['key']} | {row['relation']} | {row['decision']} | {reason} | {points} |")
    return "\n".join(lines)


# A material is unavailable only when a mechanical fact says so, and that fact has a name.
# TP1-13797, 26.09: the scout filed four merge-request pages as `unavailable` with the reason
# "Superseded closed precedent MR for TP1-8384; content already captured from ticket text" — a
# judgement about relevance, written into the field that means "I could not get it". Nothing was
# red: any non-empty string passed. The person then read "get me access, or go on without it" about
# material nothing had tried to fetch, and the factory's own `vcs_evidence.py` collects all four
# (`api_authenticated: true`, revision pinned). A cause from this list, plus the fact observed, is
# what the person needs to tell a lost login from a missing source.
#
# D-0043 (13.10.2026) amends this for the causes the FACTORY itself established (`default_causes` of the table below): a
# point with such a cause is a gap in the report and is not asked (`completeness`); the rest stay questions.
#
# The causes are data (FR-13): references/source-causes.json, read by ONE reader, `cause_table()`.
CAUSES_PATH = Path(__file__).resolve().parent.parent / "references" / "source-causes.json"
_CAUSE_KEYS = ("media_causes", "access_causes", "default_causes", "vcs_codes")
_CAUSE_CACHE: dict = {}


def cause_table(path=None) -> dict:
    """references/source-causes.json: `media_causes`, `access_causes`, `default_causes`, `vcs_codes`. Loaded once per
    process and file. Raises `ValueError` naming the file when it is missing or malformed - the WRITERS (`inspect`) refuse
    by it (FR-1), and `completeness` reads it through `_default_causes`, which turns the failure into no default at all."""
    path = Path(path or CAUSES_PATH)
    key = str(path)
    if key in _CAUSE_CACHE:
        return _CAUSE_CACHE[key]
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.name} cannot be read ({str(exc)[:80] or type(exc).__name__})") from None
    ok = (isinstance(data, dict) and isinstance(data.get("media_causes"), dict) and data["media_causes"]
          and isinstance(data.get("access_causes"), list) and isinstance(data.get("default_causes"), dict)
          and isinstance(data.get("vcs_codes"), dict))
    if not ok:
        raise ValueError(f"{path.name} is not a table with " + ", ".join(_CAUSE_KEYS))
    _CAUSE_CACHE[key] = data
    return data


try:
    MEDIA_CAUSES = cause_table()["media_causes"]
    ACCESS_CAUSES = tuple(cause_table()["access_causes"])
except ValueError:
    # A damaged table leaves the names EMPTY here and is REFUSED, naming the file, by every writer (`cause_table()`); the
    # reader of `completeness` then has no default at all - a broken table never lets a question go unasked.
    MEDIA_CAUSES, ACCESS_CAUSES = {}, ()
# Which route produced the file. `person_pasted` is a first-class route, not a workaround: when no
# automated route reaches the material, the person can read it themselves and paste what matters,
# and the record must say that is where it came from rather than implying the factory fetched it.
MEDIA_PROVENANCE = ("fetched", "browser", "person_pasted")
# A merge request or a pull request is not external media: the factory has a read-only collector
# for it (`vcs_evidence.py`), so `no_tool` is never true for one.
VCS_URL_RE = re.compile(r"/-/merge_requests/\d+|/merge_requests/\d+|/pull/\d+|/pull-requests/\d+")


def normalize_url(url: str) -> str:
    """A URL as a tracker comment stored it, back to a URL a tool can open. Markdown escaping is
    the case that bit: TP1-8384's fourth precedent arrived as
    `.../testproject1/-/merge\\_requests/3890`, so a pattern looking for `/-/merge_requests/` missed it
    and that one MR stayed uncollected while its three siblings came in clean."""
    return str(url or "").replace("\\_", "_").replace("\\", "")


def media_cause(reason: str) -> tuple:
    """`<cause>: <observed fact>` -> (cause, fact). Unknown cause -> ("", the text as given)."""
    head, _, fact = str(reason or "").partition(":")
    cause = head.strip().lower()
    return (cause, fact.strip()) if cause in MEDIA_CAUSES else ("", str(reason or "").strip())


def _probe_fields(output: Path, url: str, reason: str, probe_ref: str) -> dict:
    """The code carrier of a `host_unreachable` verdict (C2-9, N9): a vcs_evidence receipt of THIS url. `{probe_ref, probe_code,
    probe_sha256}` for the row, or `ValueError`. The receipt's `error` code must be one the table names, and the cause the
    caller records must be the one the table gives that code - a role cannot claim a cause the collector did not observe."""
    table = cause_table()
    if not _safe_rel(probe_ref):
        raise ValueError("--probe-ref must be a safe work-relative path of the vcs_evidence receipt")
    path = (output.parent / probe_ref).resolve()
    try:
        path.relative_to(output.parent.resolve())
    except ValueError:
        raise ValueError("--probe-ref escapes the work root") from None
    if not path.is_file():
        raise ValueError(f"--probe-ref {probe_ref} does not exist")
    try:
        receipt = json.loads(path.read_bytes().decode("utf-8-sig"))
    except ValueError:
        receipt = None
    if not isinstance(receipt, dict) or not isinstance(receipt.get("error"), str) or not receipt.get("error"):
        raise ValueError(f"--probe-ref {probe_ref} is not a vcs_evidence receipt that names an error code")
    if normalize_url(str(receipt.get("url") or "")) != normalize_url(url):
        raise ValueError(f"--probe-ref {probe_ref} is the receipt of another address ({receipt.get('url')}), not of {url}")
    code = receipt["error"]
    cause = table["vcs_codes"].get(code)
    if not cause:
        raise ValueError(f"the receipt answered {code}, which the table of {CAUSES_PATH.name} does not know; record the cause "
                         "you observed without --probe-ref - the person is asked")
    if media_cause(reason)[0] != cause:
        raise ValueError(f"the receipt says {code}, which is {cause}; record that cause")
    return {"probe_ref": probe_ref, "probe_code": code, "probe_sha256": sha256_bytes(path.read_bytes())}


_LIST_LIMIT = 5


def _listed(names: list) -> str:
    """At most `_LIST_LIMIT` names, then `(+N more)`; exactly the limit has no tail."""
    shown = ", ".join(str(n) for n in names[:_LIST_LIMIT])
    return shown + (f" (+{len(names) - _LIST_LIMIT} more)" if len(names) > _LIST_LIMIT else "")


def _sources_hint(inventory: dict, source_id: str) -> str:
    """The known `source_id` values, when the one given is not among them; '' when it is."""
    known = [str(s.get("source_id")) for s in inventory.get("sources", [])]
    if source_id in known:
        return ""
    if not known:
        return (f"source_id {source_id!r} is not in the inventory, which holds no source yet; "
                "`collect` adds a source, then pass its source_id")
    return (f"source_id {source_id!r} is not in the inventory; known source_id values: "
            f"{_listed(known)}. Pass one of them")


def _mr_request(url: str):
    """`(kind, host, project, iid)` when `url` is a merge or pull request link, else None. The kind comes from
    `ticket_light.classify_url` (reference-kinds.json, the path only: a request path inside a query string is
    none), and the number must end the path or be followed by `/` (the end-of-number check of `story_run`:
    `.../5a` is no request). Every error direction is toward "not a request"."""
    try:
        kind, host, found = TL.classify_url(normalize_url(url))
    except TL.TableError:
        return None
    if kind not in TL.MR_KINDS or not found:
        return None
    if found.end(2) < len(found.string) and found.string[found.end(2)] != "/":
        return None
    return kind, host, found.group(1), found.group(2)


def _mr_receipts(root: Path, request: tuple) -> tuple:
    """`(collected, notes)` for the receipts `sources/<SRC>/mr-<iid>.json` under `root/work`: `collected` are the
    work-relative paths of receipts that were READ (`status: read`) for this very request (host and project);
    `notes` name every other receipt by what it is (its status, or the other project), because a file's
    existence is no proof of a read (FR-41, AR-28). A search that fails finds nothing."""
    _kind, host, project, iid = request
    try:
        import base_slice          # inside: base_slice imports source_exclusions, no cycle at load
        import hooklib
        paths = base_slice.receipt_files(root, iid)
    except (ImportError, OSError):
        return [], []
    collected, notes = [], []
    for path in sorted(paths):
        rel = path.relative_to(root).as_posix()    # receipt_files returns paths under root/work
        row = hooklib.read_json(path, None, kind=dict)
        if row is None:
            notes.append(f"{rel} is unreadable")
        elif str(row.get("host") or "").partition(":")[0].lower() != host or row.get("project") != project:
            notes.append(f"{rel} is the receipt of another request: {row.get('host') or '?'}/{row.get('project') or '?'}")
        elif row.get("status") == "read":
            collected.append(rel)
        else:
            notes.append(f"{rel} has status {row.get('status')!r}, so it was not read")
    return collected, notes


def _mr_refusal(source_id: str, root: Path, request: tuple) -> str:
    """AK1 / AK2: the text for a GitLab merge request link that is not an item of the source."""
    collected, notes = _mr_receipts(root, request)
    tail = f"; other receipts of this number: {_listed(notes)}" if notes else ""
    if collected:
        return ("this URL is a development link (a merge request), not a material, so no inspection receipt is "
                f"needed and nothing is to be done; the factory already collected it: {_listed(collected)}" + tail)
    door = (root / "work" / "sources" / source_id / f"mr-{request[3]}.json").as_posix()
    return ("this URL is a development link (a merge request), not a material; no inspection receipt applies to it. "
            f"No collected receipt for it was found{tail}. Read it with `vcs_evidence.py --url <url> --output {door}`")


def _media_refusal(inventory: dict, source_id: str, url: str, output: Path, matches: list) -> str:
    """Why `inspect --media-url` found no ONE item for (source_id, url), in the order of what is
    wrong: unknown source, two items, a development link (a merge or pull request is not a material),
    or an address the source does not list. Pure: reads the inventory and, for a development link,
    the receipt files; writes nothing. Called only when `len(matches) != 1` (a link that IS one of
    the source's items takes the writer's own path)."""
    hint = _sources_hint(inventory, source_id)
    if hint:
        return hint
    if len(matches) > 1:
        return (f"{len(matches)} items carry this URL in source {source_id} (statuses: "
                + _listed([str(m.get("status")) for m in matches])
                + "); the inventory should hold one. Run `collect` again for this source to rebuild it")
    request = _mr_request(url)
    if request and request[0] == "pull_request":
        return ("this URL is a pull request, a development link and not a material; `vcs_evidence.py` reads GitLab "
                "merge requests only, so no receipt can be collected for it and `inspect --media-url` does not apply "
                "to it. Name it in your report for the person to read")
    if request:
        return _mr_refusal(source_id, output.parent.parent, request)
    items = [str(i.get("url")) for s in inventory.get("sources", []) if s.get("source_id") == source_id
             for i in ((s.get("materials") or {}).get("external_media") or {}).get("items") or []]
    listing = (f"the URLs of its external media: {_listed(items)}" if items
               else "this source has no external media")
    return (f"this URL is not an external media item of source {source_id}; {listing}. A new address enters the "
            "inventory only through `collect` of the source (there is no command that adds one); run it, "
            "then `inspect --media-url` with a URL it lists")


def _attachment_refusal(inventory: dict, source_id: str, attachment_id: str, matches: list) -> str:
    """The neighbour of `_media_refusal` (axis 5) for `inspect --attachment-id`."""
    hint = _sources_hint(inventory, source_id)
    if hint:
        return hint
    if len(matches) > 1:
        return f"{len(matches)} attachments carry id {attachment_id} in source {source_id}; run `collect` for it again"
    ids = [str(r.get("attachment_id")) for s in inventory.get("sources", []) if s.get("source_id") == source_id
           for r in ((s.get("materials") or {}).get("attachments") or {}).get("items") or []]
    if not ids:
        return (f"attachment_id {attachment_id!r} is not an attachment of source {source_id}; this source has no "
                "attachments, so there is nothing to inspect here. `collect` of the source records them")
    return (f"attachment_id {attachment_id!r} is not an attachment of source {source_id}; its attachment_id "
            f"values: {_listed(ids)}. Pass one of them")


def record_external_media(output: Path, source_id: str, url: str, status: str,
                          reason: str = "", local_ref: str = "", provenance: str = "fetched",
                          probe_ref: str = "") -> dict:
    """`read` (all of it, with the file), `partial` (some of it, with the file AND what is missing)
    or `unavailable` (none of it, with a cause). `partial` exists because the routes differ in what
    they reach: the API gives an MR's description and its discussions, a local merged commit gives
    the change and no discussion at all. "We have the MR, we do not have its comments" is a fact a
    person can act on — they can read the comments themselves and paste what matters — and it is
    not the same fact as "we could not reach it", which is what one status for both used to say.
    `provenance` says which route produced the file: fetched, browser, or person_pasted."""
    if status not in {"read", "partial", "unavailable"}:
        raise ValueError("external media status must be read, partial or unavailable")
    if provenance not in MEDIA_PROVENANCE:
        raise ValueError("external media provenance must be one of " + ", ".join(MEDIA_PROVENANCE))
    if status != "read":
        cause_table()      # a damaged table refuses the writer, naming the file (FR-1)
    if probe_ref and status != "unavailable":
        raise ValueError("--probe-ref is the carrier of an `unavailable` verdict; a read or partial item has its local_ref")
    inventory = load_inventory(output)
    matches = []
    for source in inventory.get("sources", []):
        if source.get("source_id") == source_id:
            matches.extend(item for item in ((source.get("materials") or {}).get("external_media") or {}).get("items") or []
                           if item.get("url") == url)
    if len(matches) != 1:
        raise ValueError(_media_refusal(inventory, source_id, url, output, matches))
    item = matches[0]
    if item.get("status") == "excluded":
        # Whatever `status` the caller asked to record: a receipt for an item the person left out
        # before the run would turn their word into "read" or "unavailable". The door is the handoff.
        import source_exclusions
        reason = next((str(e.get("reason") or "") for e in _live_exclusions(output)
                       if e.get("id") == (item.get("excluded_by") or {}).get("exclusion")), "")
        raise ValueError(source_exclusions.refusal_text(url, reason))
    if status in {"read", "partial"}:
        if not _safe_rel(local_ref):
            raise ValueError(f"{status} external media needs a safe work-relative local_ref")
        path = (output.parent / local_ref).resolve()
        try:
            path.relative_to(output.parent.resolve())
        except ValueError:
            raise ValueError("external media local_ref escapes work root") from None
        if not path.is_file():
            raise ValueError("external media local_ref does not exist")
        if status == "partial" and not reason.strip():
            raise ValueError("partial external media needs to name what is still missing, and the "
                             "route that did not give it: --reason \"<cause>: <what is missing>\"")
        for stale in ("probe_ref", "probe_code", "probe_sha256"):
            item.pop(stale, None)
        item.update(status=status, local_ref=local_ref, content_hash=sha256_bytes(path.read_bytes()),
                    error=(reason.strip() or None), provenance=provenance)
        if status == "partial":
            cause, _ = media_cause(reason)
            item.update(cause=cause or "partial_route", access_problem=cause in ACCESS_CAUSES)
    else:
        if not reason.strip():
            raise ValueError("unavailable external media needs a concrete reason")
        cause, fact = media_cause(reason)
        if not cause:
            raise ValueError(
                "unavailable external media needs a cause from the closed list and then the fact "
                'you observed: --reason "<cause>: <what the host or the tool answered>". Causes: '
                + "; ".join(f"{name} ({what})" for name, what in MEDIA_CAUSES.items())
                + ". Pick by what you OBSERVED, not by how it felt: a login page or an SSO redirect "
                "is `auth_required` (not `forbidden_by_policy` - policy means the factory is not "
                "allowed to fetch it at all); nothing in this run can open that kind of address is "
                "`no_tool`; DNS or routing failing is `host_unreachable`. A judgement that the "
                "material is not needed is not a cause at all - that is `assess --relevance "
                "not_relevant` on the source, not unavailability of its material")
        if not fact:
            raise ValueError(f"cause `{cause}` needs the fact you observed after the colon: the "
                             "status code, the redirect target, or the tool's own refusal text")
        if cause == "no_tool" and VCS_URL_RE.search(normalize_url(url)):
            raise ValueError(
                "this URL is a merge request, not external media, and the factory has a collector "
                "for it: `vcs_evidence.py --url <url> --output <file>` authenticates read-only and "
                "pins the MR revision. Run that and record the result with --inspection-status read "
                "--local-ref <file>. If vcs_evidence.py itself fails, use the cause it names "
                "(host_unreachable, auth_required, transient)")
        probe = _probe_fields(output, url, reason, probe_ref) if probe_ref else {}
        for stale in ("probe_ref", "probe_code", "probe_sha256"):
            item.pop(stale, None)       # a carrier belongs to THIS verdict only
        item.update(status="unavailable", error=reason, cause=cause,
                    access_problem=cause in ACCESS_CAUSES, local_ref=None, content_hash=None, **probe)
    source = next(source for source in inventory["sources"] if source.get("source_id") == source_id)
    group = source["materials"]["external_media"]
    group["status"] = _media_group_status(group["items"])
    _atomic_write(output, json.dumps(inventory, indent=2, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8") + b"\n")
    return inventory


def probe_jira_direct(client: JiraClient, output: Path, ticket: str | None = None) -> dict:
    """Persist a secret-free read-only capability receipt for readiness consumers."""
    checked_at = utc_now()
    try:
        checks = []
        server = client.get_json(f"/rest/api/{client.api_version}/serverInfo")
        checks.append({"name": "server_info", "status": "available"})
        identity = client.get_json(f"/rest/api/{client.api_version}/myself")
        account = identity.get("accountId") or identity.get("key") or identity.get("name")
        if not account:
            raise FetchError(None, "authenticated identity response lacks an account identifier",
                             retryable=False)
        checks.append({"name": "authenticated_identity", "status": "available",
                       "account": account})
        if not ticket:
            raise FetchError(None, "sample ticket is required for Jira direct probe", retryable=False)
        issue = client.issue(ticket)
        issue_key = issue.get("key")
        if not issue_key:
            raise FetchError(None, "sample issue response lacks key", retryable=False)
        checks.append({"name": "sample_issue", "status": "available", "ticket": issue_key})
        comments = client.all_comments(ticket, (issue.get("fields") or {}).get("comment") or {})
        checks.append({"name": "paginated_comments", "status": "available", "count": len(comments)})
        attachments = (issue.get("fields") or {}).get("attachment") or []
        if attachments:
            sample = attachments[0]
            data = client.get_bytes(str(sample.get("content") or ""))
            if sample.get("size") is not None and len(data) != int(sample["size"]):
                raise FetchError(None, "probe attachment size mismatch", retryable=True)
            checks.append({"name": "attachment_original", "status": "available",
                           "attachment_id": str(sample.get("id")), "content_hash": sha256_bytes(data)})
        else:
            checks.append({"name": "attachment_original", "status": "not_applicable",
                           "reason": "sample issue has no attachments"})
        receipt = {"schema_version": 1, "capability": "jira_direct_read",
                   "status": "available", "checked_at": checked_at,
                   "base_url": client.base_url, "api_version": client.api_version,
                   "auth_type": client.auth_type, "secret_ref": client.secret_ref,
                   "username_ref": client.username_ref or None,
                   "server_title": server.get("serverTitle"), "ticket": issue_key,
                   "checks": checks, "error": None, "retryable": False, "retry_at": None}
    except FetchError as exc:
        receipt = {"schema_version": 1, "capability": "jira_direct_read",
                   "status": "unavailable", "checked_at": checked_at,
                   "base_url": client.base_url, "api_version": client.api_version,
                   "auth_type": client.auth_type, "secret_ref": client.secret_ref,
                   "username_ref": client.username_ref or None, "server_title": None,
                   "ticket": ticket, "error": exc.reason, "retryable": exc.retryable,
                   "retry_at": exc.retry_at, "checks": locals().get("checks", [])}
    _atomic_write(output, json.dumps(receipt, indent=2, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8") + b"\n")
    return receipt


def client_from_config(adapter_cfg: dict) -> JiraClient:
    direct = adapter_cfg.get("direct_api") or adapter_cfg
    base_url = str(direct.get("base_url") or "").strip()
    auth_type = str(direct.get("auth_type") or "").strip()
    username_ref = str(direct.get("username_ref") or "").strip()
    secret_ref = str(direct.get("secret_ref") or "").strip()
    if not base_url or not auth_type or not secret_ref or (auth_type == "basic_token" and not username_ref):
        raise ValueError("direct Jira collection requires base_url, explicit auth_type, secret_ref, and username_ref for basic_token")
    api_version = str(direct.get("api_version") or "2").strip()
    ac_fields = direct.get("acceptance_criteria_fields") or []
    if not isinstance(ac_fields, list) or not all(isinstance(value, str) and value for value in ac_fields):
        raise ValueError("direct Jira acceptance_criteria_fields must be a string array")
    # adapters.ticket.project_keys (not direct_api) — a project prefix the person already
    # knows is this tracker's, so a mentioned key of it never needs the project probe.
    project_keys = adapter_cfg.get("project_keys") or []
    if not isinstance(project_keys, list) or not all(isinstance(value, str) and value for value in project_keys):
        raise ValueError("adapters.ticket.project_keys must be a string array")
    # t-267: the keys of the light form, handed over AS WRITTEN. Absent = the default (no extra field,
    # the headings of references/jira-fields.json, the attachment policy of the same file); a wrong
    # shape is refused where it is used, by the key's own name, not here - an optional key must never
    # make a usable `direct_api` read as "not recorded".
    return JiraClient(base_url, username_ref, secret_ref, auth_type=auth_type,
                      api_version=api_version, acceptance_criteria_fields=ac_fields,
                      project_keys=project_keys, custom_fields=direct.get("custom_fields"),
                      acceptance_headings=direct.get("acceptance_headings"),
                      attachment_policy=adapter_cfg.get("attachments"))
