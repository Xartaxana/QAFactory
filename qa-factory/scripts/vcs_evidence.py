"""Read-only GitLab authentication and complete, revision-pinned MR collection.

CLI: vcs_evidence.py --url URL [--output FILE]
No output file means probe only. Credentials and raw stderr never enter receipts.

A merge request the person left out BEFORE the run (`source_exclusions.py`, B-231) is refused with exit 2
and no network call - probe-only too, since the probe already reads the request's metadata.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote
from hooklib import project_root, read_json, sorted_paths

# How long a read of a merge request through the API stands as proof that the API works (HF8-12, fork F-3: 7 days).
# The gate does not lean on it: it judges against the start of the story (gate_brief), so this only bounds the
# project-level `readiness.json` and the doctor's report.
RECEIPT_TTL_S = 7 * 86400


class AccessError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


# One catch-all code used to cover three different problems — an unreachable host, a broken
# local CLI configuration and a momentary network failure — and the note derived from it
# talked about credentials in all three cases. On 2026-09-20 a dropped VPN was reported as
# "GitLab API authentication failed ... SSH credentials do not authenticate the API", which
# is the wrong owner, the wrong remedy and the wrong fact at once.
_UNREACHABLE = re.compile(
    r"no such host|name or service not known|nodename nor servname|temporary failure in name resolution"
    r"|could not resolve|network is unreachable|no route to host|connection refused|dial tcp", re.I)
_TRANSIENT = re.compile(r"timeout|timed out|connection reset|eof|temporarily unavailable|502|503|504", re.I)


def classify_failure(error: str) -> str:
    """Name the failure precisely enough that the remedy can be right."""
    text = str(error or "")
    if _UNREACHABLE.search(text):
        return "host_unreachable"
    if _TRANSIENT.search(text):
        return "network_transient"
    return "cli_config_error"


def api(host, endpoint):
    if not shutil.which("glab"):
        raise AccessError("cli_missing")
    try:
        result = subprocess.run(["glab", "api", "--hostname", host, endpoint],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        raise AccessError("network_timeout") from None
    except OSError:
        raise AccessError("cli_config_or_sandbox_denied") from None
    if result.returncode:
        error = result.stderr + result.stdout
        code = next((str(n) for n in (401, 403, 404, 429) if re.search(rf"\b{n}\b", error)), None)
        raise AccessError({"401": "unauthenticated", "403": "forbidden", "404": "not_found_or_hidden",
                           "429": "rate_limited"}.get(code, classify_failure(error)))
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise AccessError("invalid_api_response") from None


def parse_mr(url):
    parsed = urlparse(url)
    match = re.fullmatch(r"/(.+)/-/merge_requests/(\d+)/?", parsed.path)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or not match:
        raise ValueError("expected an HTTPS GitLab MR URL without credentials")
    return parsed.netloc, match[1], match[2]


def mr_iid(value) -> str:
    """The merge request number of a manifest's `mr` field, or '' - the ONE reader of that field (AR-13); the base slice (receipt lookup) and
    the first look (the head asked of the remote) both call it. The manifest holds what the story was given: a bare number (`4214`, an int),
    `!42`, or a link whose path has `/merge_requests/<n>` followed by `/`, `?`, `#` or the end (https or http, with or without `-/`, with a
    `/diffs` suffix). The number is the digits without leading zeros (`007` -> `7`: the receipt is `mr-7.json`); zero, empty, text, a sign,
    a non-MR link and any other type are '' - unknown, never a guess at a number. Not `parse_mr`: that one refuses what an API fetch must
    refuse (http, credentials, no `-/`); a number looked up in a local file needs none of it."""
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    got = re.fullmatch(r"!?([0-9]+)", text) or re.search(r"/merge_requests/([0-9]+)(?:[/?#]|$)", text)
    return got[1].lstrip("0") if got else ""


def pages(host, endpoint, read=api):
    rows, seen, page = [], set(), 1
    while True:
        batch = read(host, endpoint + f"?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise AccessError("invalid_page")
        signature = hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest()
        if batch and signature in seen:
            raise AccessError("pagination_did_not_advance")
        seen.add(signature)
        rows.extend(batch)
        if len(batch) < 100:
            return rows
        page += 1


def collect(url, read=api, full=True):
    host, project, iid = parse_mr(url)
    result = {"url": url, "host": host, "project": project, "iid": iid,
              "status": "unavailable", "required": True,
              "fetched_at": datetime.now(timezone.utc).isoformat(), "api_authenticated": False}
    endpoint = "projects/" + quote(project, safe="")
    try:
        read(host, "user")
        result["api_authenticated"] = True
        read(host, endpoint)
        mr_path = endpoint + "/merge_requests/" + iid
        metadata = read(host, mr_path)
        revision = metadata.get("sha") or (metadata.get("diff_refs") or {}).get("head_sha")
        if not revision:
            raise AccessError("missing_revision")
        result.update(revision=revision, metadata=metadata)
        if full:
            for kind in ("notes", "discussions", "diffs"):
                result[kind] = pages(host, mr_path + "/" + kind, read)
            if any(d.get("too_large") or d.get("collapsed") or d.get("overflow") for d in result["diffs"]):
                raise AccessError("diff_truncated")
            after = read(host, mr_path)
            if (after.get("sha") or (after.get("diff_refs") or {}).get("head_sha")) != revision or after.get("updated_at") != metadata.get("updated_at"):
                raise AccessError("mr_changed_during_collection")
        result.update(status="read", complete=full,
                      inspection_status="pending", error=None)
    except AccessError as exc:
        result.update(error=exc.code, complete=False,
                      next_action="MR collection through this API route is incomplete. Check an available authorized connector/browser for equivalent complete MR evidence (references/mr-access-routes.md). If none is accessible, request sign-in or local API authentication. SSH refs alone do not supply MR descriptions or discussions.")
    return result


def git_readiness(root, remote='origin'):
    """Probe the actual Git transport without fetching, prompting or changing credentials."""
    base = {'owner': 'factory', 'remote': remote,
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'evidence': ['git remote get-url', 'git ls-remote --exit-code <remote> HEAD']}
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    try:
        url = subprocess.run(['git', 'remote', 'get-url', remote], cwd=root,
                             capture_output=True, text=True, timeout=10)
        if url.returncode:
            return dict(base, status='unknown', note='Git remote URL could not be resolved.')
        raw = url.stdout.strip()
        transport = ('ssh' if raw.startswith('ssh://') or re.match(r'[^/@:]+@[^/:]+:', raw)
                     else urlparse(raw).scheme or 'local')
        base['transport'] = transport
        if transport == 'ssh' and not env.get('GIT_SSH_COMMAND') and not env.get('GIT_SSH'):
            configured = subprocess.run(['git', 'config', '--get', 'core.sshCommand'], cwd=root,
                                        capture_output=True, text=True, timeout=10)
            if configured.returncode not in (0, 1):
                return dict(base, status='unknown', note='Git SSH configuration could not be read.')
            if not configured.stdout.strip():
                env['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes'
        result = subprocess.run(['git', 'ls-remote', '--exit-code', remote, 'HEAD'], cwd=root,
                                env=env, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return dict(base, status='unknown', note='Git remote read probe unavailable or timed out; check network/sandbox access.')
    if result.returncode == 0 and re.search(r'^[0-9a-fA-F]{40,64}\s+HEAD$', result.stdout.strip(), re.M):
        return dict(base, status='ok', note=f'Git remote read access verified via {transport} (ls-remote HEAD); push and provider API are separate.')
    if transport == 'ssh':
        # The probe runs with BatchMode, so it cannot ask for a passphrase: an existing key that
        # is merely locked fails exactly like a missing one. What was established is only that
        # the remote read was not verified - the note must not send the person to redo
        # credentials that may be fine. Every door below is non-destructive.
        remedy = ('the unattended read got no answer, which does not show why: check the network, '
                  'the SSH key authorization on the remote, or unlock an existing '
                  'passphrase-protected key interactively (enter its passphrase once in your own '
                  'terminal), then run this check again')
    else:
        remedy = 'check network/credentials or an empty remote'
    return dict(base, status='unknown', note=f'Git remote read access via {transport} not verified (exit {result.returncode}); {remedy}. Local Git remains available.')


def readiness(cfg, root):
    adapter = (cfg.get("adapters") or {}).get("vcs") or {}
    name = str(adapter.get("name") or adapter.get("kind") or "")
    method = adapter.get("method") or ""
    if method in {"mcp_tool", "agent", "skill"}:
        return {"status": "unknown", "owner": "orchestrator", "note": "Verify MR read access through the configured connector; Git reachability is insufficient."}
    if name not in {"gitlab", "glab"}:
        return {"status": "unknown", "owner": "orchestrator", "note": "Provider MR API access is not verified; probe the configured route for the required MR."}
    try:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        host = urlparse(remote).hostname if "://" in remote else remote.split("@")[-1].split(":")[0]
        if not host or host.startswith("-") or "/" in host:
            raise AccessError("host_unresolved")
        try:
            api(host, "user")
        except AccessError as exc:
            # One retry, and only for a failure that is transient by nature. A refusal is not
            # retried: the answer will not change, and asking twice does not make it kinder.
            if exc.code not in {"network_transient", "network_timeout", "rate_limited"}:
                raise
            api(host, "user")
    except (AccessError, OSError, subprocess.TimeoutExpired) as exc:
        code = getattr(exc, "code", "probe_failed")
        host = locals().get("host", "")
        # Reachability EXPLAINS a failure; it does not pre-empt the attempt. Asking the socket
        # first would cost every healthy run a probe it does not need, and would let a network
        # hiccup overrule a server that answered perfectly clearly. A refusal stays a refusal
        # whatever the socket says — but anything else deserves the question "was the host even
        # there?", because that answer has a different owner and a five-second remedy.
        if code not in CONFIRMED_DENIAL and host:
            import reachability
            route = reachability.probe(host)
            if route["status"] == "unreachable":
                answer = unreachable_readiness(host, route)
                if code == "host_unresolved":
                    answer.pop("host")      # the probe never addressed a host it could not resolve
                return answer
        if code in _DENIAL_RECEIPT_CODES and host:
            # A refusal the probe itself established is as good a fact as a read: a later `--write` without the probe
            # and the gate must not see the older `ok` alone (AR-28). Never raises, never changes the answer.
            record_api_receipt(root, {"host": host, "error": code})
        # Only a refusal the host itself gave costs the extra `glab auth status` (AR-12): a healthy probe, a network
        # failure, a 404 or a missing CLI never reach it. The receipt above keeps the code, not the case (F-3).
        case = _token_case(host, code) if code in _DENIAL_RECEIPT_CODES and host else None
        return failed_readiness(code, host, case)
    return {"status": "ok", "owner": "factory", "host": host,
            "note": "GitLab API identity verified; each required project/MR still needs its own read probe."}


def unreachable_readiness(host, route):
    """No network route: the access question was never asked, so it has no answer yet."""
    return {
        "status": "unknown", "owner": "factory", "host": host,
        "note": f"no network route to `{host}` ({route.get('detail')}) — API access is NOT verified "
                "and NOT denied, because nothing was asked of the host. Git/SSH and everything "
                "local are untouched by this.",
        "remedy": {
            "kind": "human_step", "autorun": False, "owner": "user",
            "need": f"a network route to `{host}`",
            "blocks": "reading MR descriptions and discussions through the API while it lasts; "
                      "local git, tests and anything that does not leave the machine keep working",
            "steps": ["turn the corporate VPN on if it is off — that is the usual cause",
                      f"if the VPN is already on, `{host}` is down or blocked for this machine: "
                      "report it to whoever runs it rather than changing anything locally"],
            "verify": "say the word and the probe runs again; nothing else is needed",
        },
    }


# Only these mean "the host answered and refused". Everything else is an unfinished question.
CONFIRMED_DENIAL = {"unauthenticated", "forbidden", "cli_missing"}
# `cli_missing` is a refusal of the local tool, not of the host: the host never answered, so no receipt says "denied".
_DENIAL_RECEIPT_CODES = CONFIRMED_DENIAL - {"cli_missing"}


# The refusal in words, for the note a person reads (the code is a label of ours, OH3-11).
_REFUSAL_WORDS = {"unauthenticated": "the host answered 401: the call was not authenticated",
                  "forbidden": "the host refused the request (403)",
                  "cli_missing": "`glab` is not on PATH"}
_HTTP_OF = {"unauthenticated": "401", "forbidden": "403"}
_CONNECTOR_STEP = ("first, let an authorized connector or browser be tried for the exact MR — it "
                   "yields the same evidence and needs nothing from you "
                   "(references/mr-access-routes.md)")
OTHER_HOSTS_SHOWN = 3
AUTH_STATUS_TIMEOUT_S = 15
GLAB_AUTH_PATH = Path(__file__).resolve().parents[1] / "references" / "glab-auth.json"


def _hosts_phrase(hosts):
    """`a`, `b`, `c` and 1 more: a long list never pushes the step out (OH3-11, E12)."""
    shown = ", ".join(f"`{h}`" for h in hosts[:OTHER_HOSTS_SHOWN])
    more = len(hosts) - OTHER_HOSTS_SHOWN
    return shown + (f" and {more} more" if more > 0 else "")


def _case_steps(case, host, code, env, others):
    """The steps after the connector for a token case; None for a case with no text (the old steps stay)."""
    issue = (f"issue a personal access token in your `{host}` profile with `read_api` and "
             "`read_repository` scopes")
    login = f"then run `glab auth login --hostname {host}` and paste that token when asked"
    if case == "env_overrides":
        listed = f" glab also lists {_hosts_phrase(others)}." if others else ""
        return [f"The variable `{env}` is set in this environment; glab prefers it to a token saved for a host, "
                f"and `{host}` answered {_HTTP_OF[code]}.{listed}", issue,
                "take the variable out of the environment glab runs in (other tools of yours may read it, "
                f"check them first), run `glab auth login --hostname {host}`, and reopen the session"]
    if case == "other_host_token":
        return [f"glab holds a token for {_hosts_phrase(others)} only; this project lives on `{host}`.", issue, login]
    if case == "host_token_rejected":
        return [f"glab holds a token for `{host}` and the host rejected it: it is expired or revoked.",
                "issue a new personal access token in that profile with `read_api` and `read_repository` scopes",
                login]
    if case == "lacks_rights":
        return [f"`{host}` accepted the token and refused the request: the token lacks `read_api`, or your "
                "account has no access to this project.",
                f"check that your account can open this project on `{host}`; if it can, issue a new token with "
                "`read_api` and `read_repository` scopes", login]
    if case == "no_token":
        return ["glab holds no token.", issue, login]
    return None


def failed_readiness(code, host, token_case=None):
    """`token_case` is `_token_case`'s answer; None or `unknown` leaves every step as it always was."""
    confirmed = code in CONFIRMED_DENIAL
    remedy = {"kind": "human_step", "autorun": False, "owner": "user" if confirmed else "factory",
              "blocks": "operations that require the provider API — MR metadata, descriptions and "
                        "discussions. Git over SSH, branch and commit access, and a diff taken "
                        "between pinned base/head SHAs are unaffected.",
              "verify": "re-run readiness.py --probe-vcs, or say the word and the probe runs again"}
    case = token_case.get("case") if isinstance(token_case, dict) else None
    if code == "cli_missing":
        remedy.update(need="the `glab` CLI on PATH in this session",
                      steps=["install `glab` and reopen the session, or record another authorized "
                             "MR read route in the config (references/mr-access-routes.md)"])
    elif code in {"unauthenticated", "forbidden"}:
        by_case = _case_steps(case, host, code, token_case.get("env"), token_case.get("others") or []) if case else None
        remedy.update(
            need=f"a GitLab token for `{host}` with read access",
            steps=[_CONNECTOR_STEP, *by_case] if by_case else
                  [_CONNECTOR_STEP,
                   f"if that route is unavailable: issue a personal access token in your `{host}` "
                   "profile with `read_api` and `read_repository` scopes",
                   f"then `glab auth login --hostname {host}` and paste that token when asked"])
    else:
        remedy.update(need="a finished probe — this one did not reach a verdict",
                      steps=[f"the local `glab` configuration for `{host}` reported `{code}`; "
                             "re-running the probe is the first step, and it is free"])
    answer = {"status": "missing" if confirmed else "unknown",
              "owner": "user" if confirmed else "factory",
              "note": ("GitLab API access refused: " if confirmed else "GitLab API access not verified: ")
                      + (_REFUSAL_WORDS.get(code, code) if confirmed else code)
                      + ". This does not invalidate Git/SSH access and blocks only operations "
                      "requiring the provider API.",
              "remedy": remedy}
    if host and code != "host_unresolved":
        answer["host"] = host       # the probe addressed this host; `api_capability` compares it with the receipts
    if code in _HTTP_OF and case and case != "unknown":
        # A final field (AR-22): its readers are the test and the doctor's eval; the receipt does not carry it, and a
        # later `--write` reads only the code.
        answer["token_case"] = case
    return answer


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _auth_rules():
    """`references/glab-auth.json` as compiled rules, or None (absent, unreadable, a foreign shape): the caller then
    knows nothing and keeps the old steps (OH3-11, E8). The closed variety of `glab`'s wording lives there (FR-13)."""
    try:
        data = read_json(GLAB_AUTH_PATH, None, kind=dict)
        if data is None:
            return None
        env = data.get("token_env")
        lists = [data.get("token_present"), data.get("token_absent")]
        if not (isinstance(env, list) and env and all(isinstance(n, str) and n for n in env)
                and all(isinstance(g, list) and g and all(isinstance(p, str) and p for p in g) for g in lists)
                and isinstance(data.get("host_line"), str)):
            return None
        host_line = re.compile(data["host_line"])
        if "host" not in host_line.groupindex:
            return None
        return {"env": list(env), "host_line": host_line,
                "present": [re.compile(p) for p in lists[0]], "absent": [re.compile(p) for p in lists[1]]}
    except Exception:
        return None


def _auth_blocks(text, rules):
    """`glab auth status` text -> [(host as printed, "present" | "absent" | None)] in order of appearance. A header is a
    line with no indent made only of a host name: it opens a block but is NOT a token (the default host is listed on a
    machine with none). In a block exactly one of the two groups decides; both, or neither, is None - not understood."""
    blocks = []
    for raw in _ANSI.sub("", str(text or "")).splitlines():
        line = raw.rstrip()
        header = rules["host_line"].match(line)
        if header:
            blocks.append([header.group("host"), False, False])
        elif blocks:
            blocks[-1][1] = blocks[-1][1] or any(p.search(line) for p in rules["present"])
            blocks[-1][2] = blocks[-1][2] or any(p.search(line) for p in rules["absent"])
    return [(host, "present" if has and not lacks else "absent" if lacks and not has else None)
            for host, has, lacks in blocks]


def _auth_status_blocks(rules):
    """Run `glab auth status` (no `--all`: older builds refuse it) and parse it; None when it did not run or was not
    understood. Reads stdout and stderr together; the exit code is no signal (1 on one build, 0 on another)."""
    try:
        result = subprocess.run(["glab", "auth", "status"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=AUTH_STATUS_TIMEOUT_S, env=dict(os.environ, NO_COLOR="1"))
        return _auth_blocks((result.stdout or "") + "\n" + (result.stderr or ""), rules)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _clean_host(value):
    """A host name from the output, or '' when it could carry something else (a path, a login, a space)."""
    value = str(value or "")
    return "" if not value or any(c in value for c in "/@ \t") else _host_key(value)


def _token_case(host, code):
    """Whose token is it and what is wrong with it, for the person (OH3-11): `{"case", "env", "others"}`. Never raises,
    never holds a token value: the variable is read only as set / not set. Called only after a CONFIRMED refusal of a
    known host. Error direction: say less - an output that was not understood is `unknown`, never `no_token` (FR-41)."""
    unknown = {"case": "unknown", "env": None, "others": []}
    try:
        rules = _auth_rules()
        if rules is None or code not in _HTTP_OF or not _host_key(host):
            return unknown
        env = next((n for n in rules["env"] if str(os.environ.get(n) or "").strip()), None)
        if code == "forbidden" and env is None:
            return {"case": "lacks_rights", "env": None, "others": []}
        blocks = _auth_status_blocks(rules)
        listed = [(_clean_host(h), state) for h, state in (blocks or [])]
        me = _host_key(host)
        others = []
        for name, state in listed:
            if state == "present" and name and name != me and name not in others:
                others.append(name)
        if env:
            return {"case": "env_overrides", "env": env, "others": others}
        if not listed:
            return unknown
        mine = [state for name, state in listed if name == me]
        if "present" in mine:
            return {"case": "host_token_rejected", "env": None, "others": others}
        if any(state is None for _name, state in listed):
            return unknown      # a block that was not understood may hold a token: "only" is not known (FR-41)
        if others:
            return {"case": "other_host_token", "env": None, "others": others}
        if all(state == "absent" for _name, state in listed):
            return {"case": "no_token", "env": None, "others": []}
        return unknown
    except Exception:
        return unknown


def _host_key(host):
    """THE spelling of a host for comparing and hashing: `collect` hands `netloc` (port, any case), `readiness` hands
    `hostname`; both are one host. '' when it cannot be told."""
    try:
        return urlparse("https://" + str(host or "")).hostname or ""
    except ValueError:
        return ""


def _current_adapter(root):
    """`adapters.vcs` (name, method) of the project's config, the route a receipt was earned on; None when the config
    cannot be read (a project before onboarding has no home for a receipt)."""
    cfg = read_json(Path(root) / "qa-factory" / "config.json", None, kind=dict)
    if cfg is None:
        return None
    adapters = cfg.get("adapters")
    adapter = adapters.get("vcs") if isinstance(adapters, dict) else None
    adapter = adapter if isinstance(adapter, dict) else {}
    return {"name": str(adapter.get("name") or adapter.get("kind") or ""), "method": str(adapter.get("method") or "")}


def _receipt_path(root, key):
    return (Path(root) / "qa-factory" / "state" / "host-receipts"
            / f"vcs-api-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}.json")


def record_api_receipt(root, result):
    """Keep what one read (or one live probe) established about the API of one host: `ok` after a merge request was
    read through an authenticated API, `denied` after the host itself refused (HF8-12, W-4). The ONE writer of
    `host-receipts/vcs-api-*.json` (AR-14); a browser, SSH or a person's paste never reaches it (mr-access-routes).

    The answer of the caller never changes: any failure here is swallowed (FR-14). Not written: a network error, a
    404 (a hidden project reads like one), `cli_missing`, a truncated diff - they neither prove nor deny, and the
    older receipt of the host stays as it was. No `qa-factory/config.json`: nothing, the code never creates a project's
    home. Neither a token nor stderr nor any content of the MR enters the file. Returns the path written, or None."""
    try:
        if result.get("status") == "read" and result.get("api_authenticated") is True:
            status, code = "ok", "read"
        elif result.get("error") in _DENIAL_RECEIPT_CODES:
            status, code = "denied", result["error"]
        else:
            return None
        key = _host_key(result.get("host"))
        adapter = _current_adapter(root)
        if not key or adapter is None:
            return None
        from event_store import atomic_json
        path = _receipt_path(root, key)
        atomic_json(path, {"host": key, "status": status, "code": code,
                           "observed_at": datetime.now(timezone.utc).isoformat(), "adapter": adapter})
        return path
    except Exception:
        return None


def read_api_receipts(root, now=None):
    """The fresh receipts of `record_api_receipt`, newest first: `{"ok": [...], "denied": [...]}`. The ONE reader (AR-13).

    Fresh means: age in [0, RECEIPT_TTL_S) - a future date is not evidence - the config's `adapters.vcs` (name, method)
    is the one the receipt was earned on, and `glab` is on PATH now. A file that cannot be read, is not an object or has
    other fields is skipped; nothing raises: no receipt is `unknown`, never `ok` (AR-28)."""
    out = {"ok": [], "denied": []}
    try:
        adapter = _current_adapter(root)
        if adapter is None or not shutil.which("glab"):
            return out
        now = now or datetime.now(timezone.utc)
        found = []
        for path in sorted_paths((Path(root) / "qa-factory" / "state" / "host-receipts").glob("vcs-api-*.json")):
            row = read_json(path, None, kind=dict)
            if row is None or row.get("status") not in out or not isinstance(row.get("host"), str) or not row["host"]:
                continue
            try:
                seen = datetime.fromisoformat(str(row.get("observed_at")))
            except ValueError:
                continue
            if seen.tzinfo is None or not 0 <= (now - seen).total_seconds() < RECEIPT_TTL_S or row.get("adapter") != adapter:
                continue
            found.append((seen, row))
        for _seen, row in sorted(found, key=lambda pair: pair[0], reverse=True):
            out[row["status"]].append(row)
        return out
    except Exception:
        return {"ok": [], "denied": []}


def _read_phrase(row):
    return f"a merge request on `{row['host']}` was read through the API at {row['observed_at']}"


def api_capability(live, receipts):
    """The `vcs_api` capability from the live probe (`live`: `readiness()`'s answer, or None when it was not run) and
    the fresh receipts of `read_api_receipts`. None means "no receipt changes the answer and there is no live one":
    the caller keeps its own default. `required_for` is the caller's. The table is HF8-12 spec section 4.

    The error direction: an unknown is never turned into `ok`. A fresh `denied` on any host forbids `ok`; a live
    answer that asked and got nothing keeps its remedy; a live refusal on the receipt's own host outranks the older
    read (AR-28, FR-59)."""
    oks, denied = receipts.get("ok") or [], receipts.get("denied") or []
    if live is None:
        if denied:
            refused = "; ".join(f"the API of `{row['host']}` refused access ({row.get('code')}) at {row['observed_at']}"
                                for row in denied)
            read = "".join("; " + _read_phrase(row) for row in oks)
            return {"status": "unknown", "owner": "orchestrator",
                    "note": f"GitLab API access is not proven: {refused}{read}. "
                            "Run readiness.py --probe-vcs to ask again, or read the exact required MR."}
        if oks:
            return {"status": "ok", "owner": "factory", "proved_by": "receipt",
                    "note": "; ".join(_read_phrase(row) for row in oks)
                            + "; each required project/MR still needs its own read"}
        return None
    answer = dict(live)
    if not oks:
        return answer
    status, host = live.get("status"), live.get("host")
    if status == "missing":
        other = [row for row in oks if host and _host_key(row["host"]) != _host_key(host)]
        # A refusal found now, on the receipt's own host, is newer than the read; on another host the read is a
        # fact worth naming, not a reason to hide the refusal (F-4).
        if other:
            answer["note"] = f"{live.get('note', '')} Also: " + "; ".join(_read_phrase(row) for row in other) + "."
        return answer
    if status == "unknown" and host:
        answer["note"] = (f"{live.get('note', '')} Also: " + _read_phrase(oks[0])
                          + "; this check got no answer now.")
        return answer
    if status == "unknown" and not denied:
        return {"status": "ok", "owner": "factory", "proved_by": "receipt",
                "note": "; ".join(_read_phrase(row) for row in oks)
                        + "; there is no live probe for this route; each required project/MR still needs its own read"}
    return answer


def _story_root_of(output) -> "Path | None":
    """`<...>/qa-factory/artifacts/<T>` when `output` lies under it, else None (no story is known)."""
    if not output:
        return None
    parts = Path(output).resolve().parts
    for index in range(len(parts) - 2, 0, -1):
        if parts[index] == "artifacts" and parts[index - 1] == "qa-factory":
            return Path(*parts[:index + 2])
    return None


def left_out_by_person(url, output=None):
    """Did the person say BEFORE the run not to read this merge request (B-231, P8a)? None, or
    (exit code, what to print to stderr, the record's id).

    Three places ask, and they are one rule. With `--output` under `qa-factory/artifacts/<T>/` the story is
    known: only `<T>`'s own list is consulted. Probe-only (no `--output`) and `--output` outside a story name
    no story, and the tool reads MR metadata either way (`collect` calls the API for `sha` before anything
    else): every story's list under `artifacts/*/work/source-exclusions.json` is consulted, because a tool
    that cannot tell which story is asking must not be the door around the word. Only a MERGE REQUEST link
    can match here, so a ticket-kind word - the only kind a story's own key could be - never does.

    Nothing recorded anywhere: None, and the tool runs as it always did. A record of the asking story that
    exists and cannot be read refuses (it errs toward not reading); another story's unreadable record is
    not this call's business and is skipped."""
    try:
        import source_exclusions as SE
        from hooklib import artifact_root
    except Exception:
        return None       # a half-installed tree degrades to "feature absent" - never a block on its own
    story = _story_root_of(output)
    try:
        roots = [story] if story else sorted_paths(p for p in Path(artifact_root()).iterdir() if p.is_dir())
    except OSError:
        return None
    for root in roots:
        try:
            live = SE.live(root)
        except SE.ExclusionRecordError as exc:
            if story:
                return 2, f"vcs_evidence: {exc}", ""
            continue
        for exclusion in live:
            if SE.matches(exclusion, url=url):
                reason = str(exclusion.get("reason") or "")
                if story:
                    text = "vcs_evidence: " + SE.refusal_text(url, reason)
                else:
                    text = (f"vcs_evidence: the person of story {root.name} asked before the run not to read `{url}` "
                            f"(\"{reason}\"). Nothing was fetched. If this read belongs to another story, run it with "
                            "`--output` under that story's own folder (`qa-factory/artifacts/<that story>/work/`): "
                            "a story is held only to its own word.")
                return 2, text, str(exclusion.get("id") or "")
    return None


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument("--url", required=True)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    refused = left_out_by_person(args.url, args.output)
    if refused:
        code, text, exclusion = refused
        print(text, file=sys.stderr)
        # stdout keeps its shape (FR-14): one JSON object, like every other answer of this tool.
        print(json.dumps({"url": args.url, "status": "excluded", "error": "left_out_by_person",
                          "exclusion": exclusion, "fetched": False}))
        return code
    result = collect(args.url, full=bool(args.output))
    try:
        story = _story_root_of(args.output)
        record_api_receipt(story.parents[2] if story else project_root(), result)
    except Exception:
        pass            # accounting never changes what the tool answers (FR-14)
    if args.output:
        from event_store import atomic_json
        atomic_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"metadata", "notes", "discussions", "diffs"}}))
    return 0 if result["status"] == "read" else 2


if __name__ == "__main__":
    raise SystemExit(main())
