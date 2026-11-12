"""Build the complete, local-only repository inventory used by onboarding and doctor."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_files  # noqa: E402


def _resolved(root: Path, raw: str) -> Path:
    path = Path(raw or ".")
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _key(path: Path) -> str:
    value = os.path.normpath(str(path))
    return os.path.normcase(value) if os.name == "nt" else value


def _safe_remote(remote: str) -> str:
    remote = re.sub(r"(?i)(https?://)[^/@]+@", r"\1", remote.strip())
    remote = re.sub(r"(?i)([?&](?:token|key|secret|password)=)[^&#]+", r"\1REDACTED", remote)
    return remote


def _git(path: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""


def configured_entries(config: dict) -> list[dict]:
    entries: list[dict] = []
    for i, item in enumerate(config.get("code_repos") or []):
        item = item if isinstance(item, dict) else {"path": item}
        entries.append({"name": item.get("name") or f"code-{i+1}", "role": "application",
                        "path": item.get("path") or "", "config_ref": f"/code_repos/{i}",
                        "profile_id": item.get("profile_id"), "scope_required": item.get("scope_required"),
                        "default_branch": item.get("default_branch")})   # the producer of `declared_default_branch` (AR-22)
    for i, item in enumerate(config.get("implementation_repos") or []):
        if not isinstance(item, dict): item = {"local_path": item}
        entries.append({"name": item.get("repo_id") or f"implementation-{i+1}",
                        "role": item.get("role") or "implementation",
                        "path": item.get("local_path") or item.get("path") or "",
                        "config_ref": f"/implementation_repos/{i}",
                        "profile_id": item.get("execution_profile_id"),
                        "scope_required": item.get("scope_required"),
                        "default_branch": item.get("default_branch")})
    if "tests_root" in config:
        entries.append({"name": "tests", "role": "tests", "path": config.get("tests_root") or ".",
                        "config_ref": "/tests_root", "profile_id": None, "scope_required": None})
    if config.get("app_root") and config.get("protected_app_paths"):
        entries.append({"name": "app_root", "role": "application", "path": config["app_root"],
                        "config_ref": "/app_root", "profile_id": None, "scope_required": None})
    return entries


def build_inventory(config: dict, root: Path, selected_repo_ids: set[str] | None = None) -> dict:
    selected_repo_ids = selected_repo_ids or set()
    entries = configured_entries(config)
    groups: dict[str, dict] = {}
    for entry in entries:
        raw = str(entry["path"] or "")
        if not raw or "\x00" in raw:
            key = f"invalid:{entry['config_ref']}"
            path = None
        else:
            path = _resolved(root, raw); key = _key(path)
        group = groups.setdefault(key, {"path": path, "entries": []})
        group["entries"].append(entry)
    repos = []
    for key in sorted(groups):
        group = groups[key]; path = group["path"]; members = group["entries"]
        names = sorted(set(str(x["name"]) for x in members))
        refs = sorted(x["config_ref"] for x in members)
        required = (any(n in selected_repo_ids for n in names) if selected_repo_ids else None)
        presence = bool(path and path.exists())
        status, reason, git_status, branch, remote = "ready", "", "not_git", None, None
        evidence = refs[:]
        if path is None:
            status, reason = "invalid", "empty or invalid configured path"
        elif not presence:
            status, reason = "missing", "configured checkout is absent"
        elif not path.is_dir():
            status, reason = "invalid", "configured path is not a directory"
        else:
            rc, top = _git(path, "rev-parse", "--show-toplevel")
            if rc != 0:
                status, reason = "unknown", "path exists but is not a readable Git checkout"
            else:
                git_status = "clean"
                rc_dirty, dirty = _git(path, "status", "--porcelain")
                if rc_dirty == 0 and dirty: git_status = "dirty"
                rc_branch, branch_value = _git(path, "branch", "--show-current")
                branch = branch_value if rc_branch == 0 else None
                rc_remote, remote_value = _git(path, "config", "--get", "remote.origin.url")
                remote = _safe_remote(remote_value) if rc_remote == 0 else None
                evidence.append("git:rev-parse/status/branch/config (local, <=10s each)")
        declared = sorted(set(str(x.get("default_branch")) for x in members if x.get("default_branch")))
        repo_id = names[0] if len(names) == 1 else "repo-" + hashlib.sha256(key.encode()).hexdigest()[:10]
        repos.append({"repo_id": repo_id, "names": names,
                      "roles": sorted(set(str(x["role"]) for x in members)),
                      "path": str(path) if path else None, "config_refs": refs,
                      "profile_ids": sorted(set(str(x["profile_id"]) for x in members if x.get("profile_id"))),
                      "presence": presence, "git_status": git_status, "observed_branch": branch,
                      "declared_default_branch": declared[0] if len(declared) == 1 else declared or None,
                      "remote_identity": remote, "scope_required": required,
                      "status": status, "reason": reason, "evidence_refs": evidence})
    unresolved = sum(len(groups[key]["entries"]) for key, repo in
                     zip(sorted(groups), repos) if repo["status"] != "ready")
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "configured_entries": len(entries), "distinct_checkouts": len(groups),
            "unresolved_entries": unresolved,
            "repositories": repos}


# --- how this project reaches its stand -------------------------------------------------
# Another checkout of the same test harness, 23.09.2026: onboarding read the project's key
# INVENTORY - a cli/constants.py with ~100 `KEY_X = "X"` lines - and copied four names into
# environment.secret_keys that no .env file holds and no test of the first story needs
# (AUTH_CLIENT_SECRET, AWS_SESSION_TOKEN, AWS_PROFILE, HEADLESS). The story then stopped on
# keys nobody needed. So this discovery keeps two lists apart and never merges them: the
# names an env file actually HOLDS, and the names the code READS that the file does not
# hold. Only the first may become secret_keys/user_key/base_url_key; the second belongs in
# integrations[] (`integration_proposals` has the facts: required_by when the call sites are tests, read_at always), where
# a missing key blocks an area and not the stand.
# A constant assignment is not a read: `KEY_X = "X"` names a key, it does not ask for one.
#
# NO VALUE IS EVER LET OUT OF THESE FILES. Only names, file paths and line numbers leave
# this module, because its output travels into the interview and from there into a
# transcript. (A value may be tested for the shape of an http address, `frontend_candidates`; it
# does not leave that call.)
SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "dist", "build", "target",
             "vendor", "coverage", "htmlcov", "qa-factory", "venv", "env"}
# Which files are code is the markers file's word (`test_files.is_code_file`, B-407 A-map Q-d); when it cannot be read the
# floor decides (FR-59). These shell and config files are not code by that list but a script or a compose file reads an
# env key too, so the sweep reads them whatever the language list says.
ENV_SWEEP_SUFFIXES = {".sh", ".ps1", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
# The inventory's own floor, used when the markers cannot be read: what the sweep read before the move. The safe direction
# of this sweep is to read MORE, so it is not the leaf's narrower CODE_EXTENSION_FLOOR.
_SWEEP_FLOOR = (".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".cs", ".rb", ".go", ".php", ".sh", ".ps1", ".yaml",
                ".yml", ".toml", ".cfg", ".ini")
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 4000
KEY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,63}$")
_NAME = r"([A-Z][A-Z0-9_]{2,63})"
# A read of the environment, in the shapes the languages this factory has met use. A bare
# assignment or a dictionary literal is deliberately absent - that is the inventory trap.
ENV_READ_RES = tuple(re.compile(p) for p in (
    r"\bos\.environ\s*\[\s*[\"']" + _NAME,
    r"\bos\.environ\.get\(\s*[\"']" + _NAME,
    r"\b(?:os\.)?getenv\(\s*[\"']" + _NAME,
    r"\bget_parameter\(\s*[\"']" + _NAME,
    r"\bprocess\.env\.(?:" + _NAME + r")\b",
    r"\bprocess\.env\[\s*[\"']" + _NAME,
    r"\bSystem\.getenv\(\s*[\"']" + _NAME,
    r"\bEnvironment\.GetEnvironmentVariable\(\s*[\"']" + _NAME,
    r"\bENV\[\s*[\"']" + _NAME,
    r"\benv\.(?:str|int|bool|get)\(\s*[\"']" + _NAME,
))
# Where a project logs in. The kind is the vocabulary `environment.access.kind` uses; the
# two trailing ones have no kind of their own and are reported so the interview ASKS rather
# than the factory guessing a scheme it does not model.
LOGIN_RES = (
    ("harness_command", re.compile(
        r"(?i)(?:add_parser|\.command|@\w+\.command)\(\s*[\"']([\w:-]*(?:login|signin|authenticate)[\w:-]*)[\"']")),
    ("oidc_password", re.compile(
        r"(?i)[\"'`]?([\w./-]*(?:protocol/openid-connect/token|realms/[\w.-]+|oauth2?/token)[\w./-]*)")),
    ("oidc_password", re.compile(r"(?i)[\"'](grant_type)[\"']?\s*[:=]\s*[\"']password[\"']")),
    ("local_login", re.compile(
        r"(?i)[\"'`](/[\w./{}-]*/?(?:local-auth/login|login|signin|authenticate|sessions?))[\"'`]")),
    ("bearer_env", re.compile(r"(?i)[\"']?(Authorization)[\"']?\s*[:=]\s*[\"'`]?\s*Bearer")),
    ("cookie_session", re.compile(r"(?i)\b(CookieJar|session\.cookies|cookies\.set)\b")),
    ("mtls", re.compile(r"(?i)\b(client_cert|cert=\(|ssl_keyfile|SSLContext\.load_cert_chain)")),
)
# Kinds LOGIN_RES can observe that `access.kind` has no slot for: they make the proposal
# empty and the question explicit instead of being bent into the nearest kind.
UNMODELLED_KINDS = ("cookie_session", "mtls")
KIND_PRIORITY = ("harness_command", "oidc_password", "local_login", "bearer_env")
# Names the FACTORY sets for the project (run_suite.py sets HEADLESS itself) and switches
# that belong to a client library, not to the stand. Neither is a credential of this
# project, and both were found in one project's secret_keys.
FACTORY_OWNED_RE = re.compile(r"^(HEADLESS|QA_FACTORY_[A-Z0-9_]*)$")
CLIENT_SWITCH_RE = re.compile(r"^(AWS_PROFILE|[A-Z0-9_]*_SESSION_TOKEN)$")


def key_role(name: str) -> str:
    """Which `access` slot a key NAME looks like it fills. A guess for the interview to
    confirm by name - never a reason to write the key without an answer."""
    upper = name.upper()
    for needle, role in (("CLIENT_ID", "client_id_key"), ("REALM", "realm_key"),
                         ("PASSWORD", "secret_key"), ("PASSWD", "secret_key"),
                         ("USERNAME", "user_key"), ("USER", "user_key"), ("EMAIL", "user_key"),
                         ("LOGIN", "user_key"), ("TOKEN", "token_key"), ("SECRET", "secret_key"),
                         ("DOMAIN", "url_key"), ("URL", "url_key"), ("HOST", "url_key"),
                         ("ENDPOINT", "url_key")):
        if needle in upper:
            return role
    return ""


def env_file_keys(path: Path) -> list[str]:
    """The NAMES an env file declares, in file order. Values are never read."""
    keys: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keys
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name.lower().startswith("export "):
            name = name[7:].strip()
        if KEY_NAME_RE.match(name) and name not in keys:
            keys.append(name)
    return keys


def _is_env_file(name: str) -> bool:
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def _is_swept_source(name: str, known: dict) -> bool:
    """Code by the markers' `code_extensions` (the floor when they are unknown), or a shell / config file. The answer
    is asked once per extension: `known` is the walk's own memory of it."""
    suffix = Path(name).suffix.lower()
    if suffix not in known:
        code = test_files.is_code_file("x" + suffix)    # the leaf reads the extension, so ask it about the extension alone
        known[suffix] = suffix in ENV_SWEEP_SUFFIXES or (suffix in _SWEEP_FLOOR if code is None else code)
    return known[suffix]


def _walk(root: Path):
    count = 0
    known: dict = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not (d.startswith(".") and d != ".env"))
        for name in sorted(filenames):
            if count >= MAX_FILES:
                return
            path = Path(dirpath) / name
            if _is_env_file(name) or _is_swept_source(name, known):
                count += 1
                yield path


def scan_sources(root: Path) -> dict:
    """Read-only sweep: env files with their key names, env reads by key, login call sites."""
    env_files: list[dict] = []
    reads: dict[str, list[str]] = {}
    per_file: dict[str, list[str]] = {}
    sites: list[dict] = []
    seen_sites: set[tuple[str, str]] = set()
    for path in _walk(root):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if _is_env_file(path.name):
            env_files.append({"path": rel, "keys": env_file_keys(path),
                              "example": bool(re.search(r"(?i)(example|sample|template|dist)$",
                                                        path.name))})
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for pattern in ENV_READ_RES:
                for name in pattern.findall(line):
                    where = reads.setdefault(name, [])
                    if len(where) < 3 and f"{rel}:{number}" not in where:
                        where.append(f"{rel}:{number}")
                    names = per_file.setdefault(rel, [])
                    if name not in names:
                        names.append(name)
            if len(sites) >= 40:
                continue
            for kind, pattern in LOGIN_RES:
                match = pattern.search(line)
                if not match:
                    continue
                evidence = match.group(1)[:120]
                if (kind, evidence) in seen_sites:
                    continue
                seen_sites.add((kind, evidence))
                sites.append({"kind": kind, "where": f"{rel}:{number}", "evidence": evidence,
                              "file": rel})
    for site in sites:
        site["keys"] = sorted(per_file.get(site["file"], []))
    env_files.sort(key=lambda e: (e["example"], e["path"]))
    return {"env_files": env_files, "reads": reads, "sites": sites}


def propose_access(scan: dict, env_keys: list[str]) -> dict:
    """The `environment.access` block discovery can defend, for the interview to confirm.
    Every `*_key` is chosen from the keys the env file HOLDS: a login cannot be proved with a
    name that is not there, and a name that is not there is what stopped a first story."""
    present = set(env_keys)
    kinds = {site["kind"] for site in scan["sites"]}
    chosen = next((k for k in KIND_PRIORITY if k in kinds), "")
    access = {"kind": chosen, "command": "", "url": "", "client_id_key": "", "realm_key": "",
              "user_key": "", "secret_key": "", "user_field": "", "secret_field": "", "token_key": "",
              "unauth_status": []}
    note = ""
    if not chosen:
        unmodelled = sorted(kinds.intersection(UNMODELLED_KINDS))
        note = ("no login call site was found - ask outright how this project reaches its stand"
                if not unmodelled else
                "the only evidence found is " + ", ".join(unmodelled) +
                ", which access.kind does not model - ask which of the recorded kinds applies")
    evidence = [site for site in scan["sites"] if site["kind"] == chosen]
    for site in evidence:
        if chosen == "harness_command" and not access["command"]:
            access["command"] = site["evidence"]
        elif chosen in ("local_login", "oidc_password") and not access["url"]:
            access["url"] = site["evidence"]
        for name in site["keys"]:
            if name not in present:
                continue
            role = key_role(name)
            if role in ("client_id_key", "realm_key", "user_key", "secret_key", "token_key") \
                    and not access[role]:
                access[role] = name
    if chosen == "bearer_env" and not access["token_key"]:
        access["token_key"] = next((k for k in env_keys if key_role(k) == "token_key"), "")
    if chosen and not (access["user_key"] or access["token_key"]):
        # The live case this guards: a repository carries an identity-provider helper AND a
        # local login, and the env file holds the keys of neither under those names. Saying so
        # turns the interview's first question into a real choice instead of a rubber stamp.
        note = (f"the {chosen} call sites read no key that the env file holds - confirm the kind "
                "and the key names before anything is written")
    return {"access": access, "note": note,
            "evidence": [{"where": s["where"], "evidence": s["evidence"]} for s in evidence][:5],
            # One row per OTHER kind seen, not ten rows of the same one: the interview has to
            # show every scheme the repository contains, because the one the team actually
            # uses is often not the one with the most call sites.
            "other_evidence": list({s["kind"]: {"kind": s["kind"], "where": s["where"],
                                                "evidence": s["evidence"]}
                                    for s in reversed(scan["sites"])
                                    if s["kind"] != chosen}.values())}


ACCOUNT_PAIRS_MAX = 8   # pairs one discovery names; a longer list says how many were left out (`account_pairs_more`), as `STAND_ROLES_MAX`


def _all_pairs(env_keys: list[str]) -> list[tuple]:
    """(user key, secret key) of every two names the env file holds that share a stem (the name up to its last underscore, "" for a
    name with none) and are, by `key_role`, a user name and a secret. File order, one row per user name. A GUESS for the interview
    to put to the person: which pair is whose account, and whether it is a login to the stand at all, is theirs (AR-2)."""
    stem = lambda name: name.rsplit("_", 1)[0] if "_" in name else ""      # noqa: E731
    out = []
    for user in env_keys:
        if key_role(user) != "user_key":
            continue
        out.extend((user, secret) for secret in env_keys
                   if key_role(secret) == "secret_key" and stem(secret) == stem(user))
    return out


def _pair_readable(user: str, secret: str) -> bool:
    """Does `gate_preflight.account_keys` read this pair back from a `credentials_by_role` note? The note form is `U / S`; names it
    cannot read (no underscore, lower case) are reached by `--as env:U/S` in a case and cannot be recorded under a role."""
    from gate_preflight import account_keys
    return account_keys(f"{user} / {secret}") == [user, secret]


def account_pairs(env_keys: list[str], login_user_key: str = "") -> list[dict]:
    """The accounts an env file's NAMES suggest, `[{"user_key", "secret_key", "is_login"}]`: the pairs `_all_pairs` finds whose two
    names the gate can read back (`_pair_readable`); `is_login` - the user name is the one the proposed login uses. Not cut: the
    cut and the count of the unreadable ones are `access_discovery`'s. No value is read."""
    return [{"user_key": user, "secret_key": secret, "is_login": bool(login_user_key) and user == login_user_key}
            for user, secret in _all_pairs(env_keys) if _pair_readable(user, secret)]


def frontend_candidates(root: Path, env_file: dict | None, base_url_key: str = "") -> list[str]:
    """The NAMES the chosen env file holds an http(s) address under - the candidates for the stand's UI, for the interview to put to
    the person (HF8-10). `env_file` None (no file, or only an `.env.example`) or a file that cannot be read -> `[]`: no file, no
    statement. The enumeration is `env_probe.http_address_keys` (the one the `frontend:` hint also uses); the API's own address
    (the value under `base_url_key`) is no candidate. The value is tested there and never leaves this call (module note above)."""
    if not env_file:
        return []
    import env_probe
    try:
        values = env_probe.parse_env_file(Path(root) / env_file["path"])
    except (OSError, ValueError):
        return []
    base = str(values.get(base_url_key, "") or "").strip().rstrip("/") if base_url_key else ""
    return env_probe.http_address_keys(values, set(), base)


def same_origin_keys(root: Path, env_file: dict | None, base_url_key: str = "") -> dict:
    """`{"base_url_key": <name>, "keys": [<names>]}` - the API's own address key and the NAMES of the other keys of the chosen env file
    that hold an http(s) address on the SAME origin (scheme, host and port, `env_probe.origin`, the one origin reader), in file order;
    `{}` when `base_url_key` is empty, `env_file` is None (no file, or only an `.env.example`), the file cannot be read, or the
    value under the base key is not an http address - discovery says nothing it did not read (RN1-3). An empty `keys` with a known
    base still says "base known, no other key on its origin". It is the role's judgment, from the project's UI test config, whether
    the UI tests open that address (AR-2); this is the fact it is helped by. Names only - a value never leaves this call."""
    base_key = str(base_url_key or "").strip()
    if not env_file or not base_key:
        return {}
    import env_probe
    try:
        values = env_probe.parse_env_file(Path(root) / env_file["path"])
    except (OSError, ValueError):
        return {}
    base = str(values.get(base_key, "") or "").strip()
    if not base.lower().startswith(("http://", "https://")) or not env_probe.origin(base):
        return {}
    names = env_probe.http_address_keys(values, {base_key})
    return {"base_url_key": base_key, "keys": [n for n in names if env_probe.origin(values[n]) == env_probe.origin(base)]}


def access_discovery(root: Path, config: dict | None = None) -> dict:
    """What phase 1 hands the environment batch: the env files with their key names, the
    proposed access scheme, and the keys the code reads that no env file holds."""
    scan = scan_sources(root)
    declared = str(((config or {}).get("environment") or {}).get("env_file") or "").strip()
    env_files = scan["env_files"]
    chosen_file = next((e for e in env_files if e["path"] == declared), None) or \
        next((e for e in env_files if not e["example"]), None) or \
        (env_files[0] if env_files else None)
    env_keys = list(chosen_file["keys"]) if chosen_file else []
    proposal = propose_access(scan, env_keys)
    login_files = {site["file"] for site in scan["sites"]}
    absent, in_code, at_login = [], [], []
    for name in sorted(scan["reads"]):
        row = {"key": name, "read_at": scan["reads"][name],
               "looks_like": key_role(name),
               "owned_by_factory": bool(FACTORY_OWNED_RE.match(name)),
               "client_switch": bool(CLIENT_SWITCH_RE.match(name))}
        in_code.append(row)
        if chosen_file and name not in env_keys:
            absent.append(row)
            if any(where.split(":")[0] in login_files for where in row["read_at"]):
                at_login.append(row)
    # A suite that exercises integrations reads hundreds of names; naming each one is a wall. Group the rest
    # by prefix (AWS_*, JIRA_*, SONAR_*): the interview counts the groups and nobody is asked about their keys -
    # phase 1 records them from `integration_proposals` (OH3-8).
    at_login_keys = {row["key"] for row in at_login}
    groups = _prefix_groups(absent, at_login_keys)
    grouped = sorted(({"prefix": prefix, "count": len(keys), "keys": sorted(keys)}
                      for prefix, keys in groups.items()),
                     key=lambda g: (-g["count"], g["prefix"]))
    # HF8-11 (F-4): the proposals leave out only the keys the proposed login itself USES. A key merely read in a file that
    # holds a login call (a shared conftest) may belong to an integration - Server's JIRA_URL and JIRA_TOKEN next to Cloud's
    # set - and dropping it left that set invisible with no move for the role.
    from config_contract import ACCESS_KEY_FIELDS
    login_named = {str(proposal["access"].get(field) or "") for field in ACCESS_KEY_FIELDS} - {""}
    proposals = integration_proposals(in_code, absent, login_named, env_keys)
    # HF8-9: the accounts the file's names suggest. Only a file the project really uses (`.env.example` holds names nobody set).
    pair_keys = env_keys if chosen_file and not chosen_file["example"] else []
    pairs = account_pairs(pair_keys, str(proposal["access"].get("user_key") or ""))
    unreadable = len(_all_pairs(pair_keys)) - len(pairs)
    found_pairs = {"account_pairs": pairs[:ACCOUNT_PAIRS_MAX], "account_pairs_unreadable": unreadable}
    if len(pairs) > ACCOUNT_PAIRS_MAX:
        found_pairs["account_pairs_more"] = len(pairs) - ACCOUNT_PAIRS_MAX
    # HF8-10: the names that hold an http address, for the interview to ask which one is the stand's UI.
    used_file = chosen_file if chosen_file and not chosen_file["example"] else None
    base_key = str(((config or {}).get("environment") or {}).get("base_url_key") or "").strip()
    candidates = frontend_candidates(root, used_file, base_key)
    # RN1-3: the API's own address key and the keys on its origin - `frontend_candidates` leaves the base key out, and a UI on the
    # API's address (Next.js, Rails, Django) IS that key; whether the UI tests open it is the role's judgment (AR-2)
    found_pairs["frontend_same_origin"] = same_origin_keys(root, used_file, base_key)
    from env_probe import HINT_MAX_NAMES      # the cut the `frontend:` hint makes: one limit for both
    found_pairs["frontend_candidates"] = candidates[:HINT_MAX_NAMES]
    if len(candidates) > HINT_MAX_NAMES:
        found_pairs["frontend_candidates_more"] = len(candidates) - HINT_MAX_NAMES
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "env_file": chosen_file["path"] if chosen_file else "",
            "env_file_found": bool(chosen_file),
            "env_files": env_files, "env_keys": env_keys,
            "proposed_access": proposal["access"], "proposal_note": proposal["note"],
            "access_evidence": proposal["evidence"],
            "other_login_evidence": proposal["other_evidence"],
            "keys_read_in_code": in_code,
            "keys_absent_from_env_file": absent,
            "login_keys_absent_from_env_file": at_login,
            "absent_key_groups": grouped,
            "integration_proposals": proposals, **found_pairs}


def _prefix_groups(rows: list, skip: set) -> dict:
    """{prefix: [key]} of the rows whose key is not in `skip`, the prefix being the name up to its first underscore. The
    one grouping both `absent_key_groups` (what the interview counts) and `integration_proposals` (what phase 1 records)
    are built from, so the two can never split a prefix differently (OH3-8)."""
    groups: dict[str, list[str]] = {}
    for row in rows:
        if row["key"] in skip:
            continue
        groups.setdefault(_prefix_of(row["key"]), []).append(row["key"])
    return groups


def _prefix_of(key: str) -> str:
    """The name up to its first underscore - the one tokenisation `_prefix_groups` and `integration_proposals` share."""
    return key.split("_")[0]


PROPOSAL_LIST_LIMIT = 5   # places / areas one proposal names; a longer list says how many were left out (`*_more`)


def _cut(items: list, name: str, record: dict) -> None:
    """Put `items` into `record[name]` - at most `PROPOSAL_LIST_LIMIT`, and `<name>_more` only when some were cut."""
    record[name] = items[:PROPOSAL_LIST_LIMIT]
    if len(items) > PROPOSAL_LIST_LIMIT:
        record[f"{name}_more"] = len(items) - PROPOSAL_LIST_LIMIT


def _test_area(place: str) -> str:
    """The folder of a call site that is a TEST (`names_a_test` says so), else "". A helper under `tests/` is not an area
    (`in_test_folder` is not asked), and a marker file that cannot be read (None) makes it no test: an unknown is never an
    area (AR-28). A test at the root of the project is its file name."""
    path = place.rsplit(":", 1)[0]
    if test_files.names_a_test(path) is not True:
        return ""
    folder = path.rpartition("/")[0]
    return folder or path


def integration_proposals(in_code: list, absent: list, at_login_keys: set, env_keys: list) -> list:
    """One record per prefix with at least one key the code reads and the env file does not hold - the facts phase 1 judges
    when it writes `integrations[]` (OH3-8). `keys` are ALL the keys of the prefix the code reads (except the ones the
    proposed login itself uses, `at_login_keys`), the held ones too, and
    `set_in_env_file` names those the file holds: a set that is already whole is the evidence an alternative can be
    recorded from (HF8-11); built from the absent keys alone it would show only the unset half of a service whose other
    way is set. `read_at` is the union of the call sites; `required_by` the folders of those that are tests. Nothing here
    decides: how a group splits into alternatives, what it is called and who needs it are the role's (AR-2). Names, paths
    and line numbers only - no value is read."""
    def counted(row: dict) -> bool:
        return row["key"] not in at_login_keys and not row["owned_by_factory"] and not row["client_switch"]
    prefixes = _prefix_groups([row for row in absent if counted(row)], set())
    held = set(env_keys)
    out = []
    for prefix in prefixes:
        rows = [row for row in in_code if _prefix_of(row["key"]) == prefix and counted(row)]
        places = sorted({place for row in rows for place in row["read_at"]})
        areas = sorted({area for area in map(_test_area, places) if area})
        record = {"name": f"{prefix.lower()}-integration", "keys": sorted(row["key"] for row in rows),
                  "set_in_env_file": sorted(row["key"] for row in rows if row["key"] in held)}
        if areas:
            _cut(areas, "required_by", record)
        _cut(places, "read_at", record)
        out.append(record)
    return sorted(out, key=lambda r: (-len(r["keys"]), r["name"]))


def render_access(discovery: dict) -> str:
    """The proposal as the interview shows it. Names, paths and line numbers only."""
    access = discovery["proposed_access"]
    lines = [f"env file: {discovery['env_file'] or 'none found - values come from the process environment'}"
             f" ({len(discovery['env_keys'])} keys)"]
    lines.append(f"access.kind: {access['kind'] or 'UNKNOWN'}"
                 + (f" - {discovery['proposal_note']}" if discovery["proposal_note"] else ""))
    for field in ("command", "url", "user_key", "secret_key", "client_id_key", "realm_key",
                  "token_key", "user_field", "secret_field"):
        if access.get(field):
            lines.append(f"  {field}: {access[field]}")
    if access["kind"] == "local_login" and not (access.get("user_field") or access.get("secret_field")):
        # OH3-10: the login body's field names are access data; discovery does not read them from the call site yet,
        # so say what the probe will send and that the interview confirms it (the producer is the person until then)
        from config_contract import body_field_candidates
        lines.append("  user_field / secret_field: not found at the call site - the probe tries "
                     + " then ".join(f"`{u}` / `{s}`" for u, s in body_field_candidates({}))
                     + " and reports the pair the endpoint accepts; onboarding records it")
    for row in discovery["access_evidence"]:
        lines.append(f"  evidence: {row['where']} ({row['evidence']})")
    other = discovery["other_login_evidence"]
    if other:
        lines.append("  other schemes seen (the question is a choice, not a confirmation): "
                     + "; ".join(f"{row['kind']} at {row['where']}" for row in other[:5]))
    where = discovery["env_file"] or "any env file"
    at_login = discovery["login_keys_absent_from_env_file"]
    lines.append(f"keys read at a login call site but absent from {where}: "
                 + (", ".join(r["key"] for r in at_login) if at_login else "none"))
    groups = discovery["absent_key_groups"]
    total = sum(g["count"] for g in groups)
    if groups:
        lines.append(f"further names read in code and absent from {where}: {total}, by prefix: "
                     + ", ".join(f"{g['prefix']}_* ({g['count']})" for g in groups[:12])
                     + ("; --json has them all" if len(groups) > 12 else ""))
    proposals = discovery.get("integration_proposals") or []
    if proposals:
        lines.append(f"integration proposals: {len(proposals)} groups, "
                     f"{sum(len(p['keys']) for p in proposals)} keys; --json has them")
        lines.append("  -> phase 1 records these in integrations[]; nobody is asked about them")
    pairs = discovery.get("account_pairs") or []
    if pairs:
        more = discovery.get("account_pairs_more") or 0
        lines.append("accounts in the env file: " + "; ".join(f"{p['user_key']} / {p['secret_key']}" + (" (the login's)" if p["is_login"] else "")
                                                              for p in pairs) + (f"; and {more} more, they are in the file" if more else ""))
    candidates = discovery.get("frontend_candidates") or []
    if candidates:
        more = discovery.get("frontend_candidates_more") or 0
        lines.append("http addresses in the env file: " + ", ".join(candidates) + (f"; and {more} more, they are in the file" if more else "")
                     + " - names only; which one (if any) is the stand's UI is for the interview to ask")
    same = discovery.get("frontend_same_origin") or {}
    if same.get("base_url_key"):
        lines.append(f"the API's own address {same['base_url_key']}"
                     + (f"; on the same address: {', '.join(same.get('keys') or [])}" if same.get("keys") else "")
                     + f" - if the project's UI tests open {same['base_url_key']}, the UI is on the API's address (topic 2 proposes it)")
    unreadable = discovery.get("account_pairs_unreadable") or 0
    if unreadable:
        lines.append(f"{unreadable} more user/password name pair(s) the gate cannot read back (no underscore or lower case): a case "
                     "takes such an account as `--as env:USER_KEY/SECRET_KEY`; it cannot be recorded under a role")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--selected", default="")
    parser.add_argument("--access", action="store_true",
                        help="propose environment.access and list the keys read in code only")
    parser.add_argument("--json", action="store_true", help="with --access: full JSON")
    args = parser.parse_args()
    root = args.root.resolve(); path = args.config or root / "qa-factory" / "config.json"
    if args.access:
        # Phase 1 runs before any config exists: discovery must work without one.
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        discovery = access_discovery(root, cfg)
        print(json.dumps(discovery, indent=2) if args.json else render_access(discovery))
        return
    cfg = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(build_inventory(cfg, root, set(filter(None, args.selected.split(",")))), indent=2))


if __name__ == "__main__": main()
