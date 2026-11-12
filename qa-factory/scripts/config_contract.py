"""Canonical qa-factory configuration defaults, validation and migration.

The template is the source for generated project configuration.  Runtime readers use
``effective_config`` so additive optional fields do not force old projects through
onboarding.  Migration is deliberately two-step: a proposal is read-only and applying it
requires both that exact proposal and an approval reference.

Installing IS migrating (t-232): a project with no config is the empty input of the same
``migration_plan`` (``proposed_config`` None, the role fills it from discovery), and a project
with an older config gets the shape a fresh install would write - every template key present,
canonical key order, deprecated keys removed, a person's changed notes moved to
``answers_legacy`` - by code, not by a role's judgment.  What the code knows about each key
(``since``, ``absent_means``, removed/renamed/reasked, every earlier text of a note) lives in
``references/config-keys.json`` (FR-13), not here.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
# The keys no script reads any more used to be a tuple here (INACTIVE_KEYS); they are the
# `removed` table of references/config-keys.json now, one reason each (FR-13).
IMPACT_DEFAULTS = {
    "data-loss": {"priority": "P0", "severity": "blocker"},
    "money": {"priority": "P0", "severity": "blocker"},
    "access": {"priority": "P0", "severity": "critical"},
    "blocked-flow": {"priority": "P1", "severity": "major"},
    "degraded": {"priority": "P2", "severity": "minor"},
    "cosmetic": {"priority": "P3", "severity": "minor"},
    "none": {"priority": "P3", "severity": "minor"},
}
RUNTIME_DEFAULTS = {
    "turns": {"soft": 60, "repeat": 30},
    "execution": {"parallel": {"mode": "auto", "min_selected_instances": 8,
                                 "max_workers": None}},
    "requirements_sources": [],
    "strategy_documents": [],
    "cost": {"rate_overrides": [],
             "rate_confirmation": {"status": "unconfirmed", "decision_ref": None}},
    "metrics": {"window_days": 30,
                "severity_weights": {"blocker": 8, "critical": 5, "major": 3, "minor": 1},
                "bugginess_report_share": 0.5},
    "impact_scale": IMPACT_DEFAULTS,
}
SECRET_QUERY_RE = re.compile(r"(?i)(token|secret|password|key)=([^&#]*)")
# a value that is a PLACEHOLDER, never a secret: `{key}` or `$NAME` (the shape a route is written in, SS1-15 section 3.2)
PLACEHOLDER_VALUE_RE = re.compile(r"^(\{[^{}]*\}|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)$")


def route_has_secret(text) -> bool:
    """Does a ROUTE text (a `requirements_sources` row's `invoke_or_command_ref`) hold a credential-like `name=value` whose value
    is a real value? `issue_key={key}` / `token=$JIRA_TOKEN` name a placeholder or a variable, no secret (t-586 F-10c); the
    locator check stays on `SECRET_QUERY_RE` whole."""
    return any(not PLACEHOLDER_VALUE_RE.match(m.group(2).strip()) for m in SECRET_QUERY_RE.finditer(str(text or "")))

# OH3-39: the kinds and statuses of a `requirements_sources` row, and the route each kind is read by, are a data table (FR-13,
# AR-1). `requirement_source_kinds` is its ONE reader (AR-13): the validator below and `source_inventory.requirement_source_lines`
# both call it, so they cannot disagree.
REQUIREMENT_SOURCE_KINDS_PATH = Path(__file__).resolve().parents[1] / "references" / "requirement-source-kinds.json"
# the optional fields of a row that name a variable (names only, never a value)
REQUIREMENT_SOURCE_NAME_FIELDS = ("auth_type", "secret_ref", "username_ref")


def requirement_source_kinds() -> dict:
    """`{"kinds": {kind: {"route": text}}, "statuses": [text], "not_read_routes": [text], "pointer_ref_prefixes": [text]}` read
    from references/requirement-source-kinds.json (`not_read_routes`: the lower-cased `method` words of a WRITE channel, never
    a read route; `pointer_ref_prefixes`: a route ref that STARTS with one points into a config setting, e.g. `adapters.`,
    and is no route; SS1-15, t-586 F-6/F-7). A table that is absent, not JSON or not of this shape raises `ValueError` naming the file: it is
    never read as an empty table, which would refuse (or let through) every source of every project without saying why
    (AR-28); a table with no `not_read_routes` list is damaged too, never "an agent is a route" (AR-6)."""
    name = REQUIREMENT_SOURCE_KINDS_PATH.name
    try:
        table = json.loads(REQUIREMENT_SOURCE_KINDS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"references/{name} cannot be read ({type(exc).__name__}): restore the file from the plugin") from exc
    kinds, statuses = (table.get("kinds"), table.get("statuses")) if isinstance(table, dict) else (None, None)
    if not (isinstance(kinds, dict) and kinds and all(isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("route"), str)
                                                       for k, v in kinds.items())
            and isinstance(statuses, list) and statuses and all(isinstance(s, str) for s in statuses)
            and all(isinstance(table.get(word), list) and all(isinstance(w, str) for w in table[word])
                    for word in ("not_read_routes", "pointer_ref_prefixes"))):
        raise ValueError(f"references/{name} is not a table of kinds ({{kind: {{route}}}}), statuses, not_read_routes and "
                         "pointer_ref_prefixes (lists of words): restore the file from the plugin")
    return {"kinds": kinds, "statuses": statuses,
            "not_read_routes": [w.strip().lower() for w in table["not_read_routes"]],
            "pointer_ref_prefixes": [w.strip().lower() for w in table["pointer_ref_prefixes"] if w.strip()]}

# --- the access scheme is a fact of the config, not prose -------------------------------
# Another checkout of the same test harness, 23.09.2026: the stand sat behind an identity
# provider, every unauthenticated path answered 302, and because no config said how the
# project logs in, the probe could only guess and the person was handed a guess. The scheme
# is recorded here as names and codes: which of the five ways the project reaches its stand,
# which key NAMES that way needs, and what an unauthenticated request answers on a healthy
# stand. Keycloak is one instance of `oidc_password`, not the design.
ACCESS_KINDS = ("harness_command", "local_login", "oidc_password", "bearer_env", "none")
ACCESS_KEY_FIELDS = ("client_id_key", "realm_key", "user_key", "secret_key", "token_key")
# Every `*_key` is a variable NAME. The regex is the whole guarantee that a value never
# lands in a committed file by being typed into a field that asks for a name.
KEY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,63}$")
# Keys the FACTORY sets for the project (run_suite.py sets HEADLESS itself) and switches
# that belong to a client library rather than to the stand. Both were found in one
# project's secret_keys, where they blocked a story that needed neither.
FACTORY_OWNED_KEY_RE = re.compile(r"^(HEADLESS|QA_FACTORY_[A-Z0-9_]*)$")
CLIENT_SWITCH_KEY_RE = re.compile(r"^(AWS_PROFILE|[A-Z0-9_]*_SESSION_TOKEN)$")


# What `login_probe.outcome` may say (RH1-7): the receipt words of stand_access.login. Only `ok` is a proof.
LOGIN_OUTCOMES = ("ok", "failed", "skipped", "not_recorded")
# A path is glued behind the frontend's own host only when it starts with exactly one `/`: `//host`, `/\host`, `host/x`,
# `http://host/x` and `@host/x` would move a request to another host.
API_PATH_RE = re.compile(r"^/(?![/\\])")


def frontend_errors(label: str, raw, ref_field: str) -> list[str]:
    """Why a `frontend` object ({url_key, api_path} in the block, {url, api_path} in an `environments[]` entry) is not
    one - empty when it is. Absent is not an error: the stand has no frontend."""
    if not isinstance(raw, dict):
        return [f"{label} must be an object {{{ref_field}, api_path}}"]
    errors: list[str] = []
    ref, path = raw.get(ref_field), raw.get("api_path")
    if ref is not None and not isinstance(ref, str):
        errors.append(f"{label}.{ref_field} must be text")
    elif ref_field == "url_key":
        errors.extend(_name_errors(f"{label}.url_key", ref))
    elif isinstance(ref, str) and ref.strip() and not ref.strip().lower().startswith(("http://", "https://")):
        errors.append(f"{label}.url must be an http(s) address")
    if path is not None and not isinstance(path, str):
        errors.append(f"{label}.api_path must be a path starting with one /")
    elif isinstance(path, str) and path.strip() and not API_PATH_RE.match(path.strip()):
        errors.append(f"{label}.api_path must be a path starting with one /")
    elif isinstance(path, str) and path.strip() and not str(ref or "").strip():
        errors.append(f"{label}.api_path is set but {label}.{ref_field} is empty: a path needs the frontend's address")
    return errors


def environments_frontend_errors(environments) -> list[str]:
    """The `frontend` object of each `environments[]` entry that carries one."""
    errors: list[str] = []
    for i, entry in enumerate(environments if isinstance(environments, list) else []):
        if isinstance(entry, dict) and "frontend" in entry:
            errors.extend(frontend_errors(f"environments[{i}].frontend", entry["frontend"], "url"))
    return errors


def environments_surface_errors(environments) -> list[str]:
    """EP1-41c: why the `surface` of an `environments[]` entry is not a stand the factory can describe - empty when it is, and
    EMPTY for every entry that carries no `surface` (the table is not read: the web road). The name must be a row of
    references/surfaces.json (a typo never becomes the web); a row whose hands are a `driver` also needs `driver.url` as an http(s)
    address with no user or password in it (a secret never reaches a file that is committed), `device.serial_key` as a variable
    NAME, and `app` as an object. Names and paths only: no address is repeated in an error. An unreadable table is an error
    that says so (a factory defect), never silence."""
    errors: list[str] = []
    named = [(i, e) for i, e in enumerate(environments if isinstance(environments, list) else []) if isinstance(e, dict) and "surface" in e]
    if not named:
        return errors
    surfaces = _sibling("surfaces")
    for i, entry in named:
        label = f"environments[{i}]"
        try:
            row = surfaces.row_of(entry)
        except ValueError as exc:
            errors.append(f"{label}.surface: {' '.join(str(exc).split())[:300]}")
            continue
        if not surfaces.is_device_row(row):
            continue
        driver = entry.get("driver")
        # the ONE reading of the address is `surfaces.driver_url_problem`, the same `device_stand` uses (F-7): an empty or absent
        # `driver.url` is "I do not know" (the onboarding leaves it for the doctor) and is no contract error
        problem = surfaces.driver_url_problem(driver.get("url") if isinstance(driver, dict) else (None if driver is None else 0))
        if problem == "secret":
            errors.append(f"{label}.driver.url must not hold a user, a password, a query or a fragment: a secret in this file is committed; use an address without them")
        elif problem == "unusable":
            errors.append(f"{label}.driver.url must be the http(s) address of the Appium server (an object `driver` with `url`)")
        device = entry.get("device")
        if device is not None and not isinstance(device, dict):
            errors.append(f"{label}.device must be an object")
        elif isinstance(device, dict):
            errors.extend(_name_errors(f"{label}.device.serial_key", device.get("serial_key")))
        if entry.get("app") is not None and not isinstance(entry.get("app"), dict):
            errors.append(f"{label}.app must be an object with the application's `id`")
    return errors


def reserved_role(role) -> bool:
    """Is this `credentials_by_role` key one of the forms `manual_capture.resolve_actor` reads before any role (`default`, `env:...`,
    `created:...`)? Such a role could never be reached by `--as`, so it is never written (HF8-9)."""
    text = str(role).strip()
    return text == "default" or text.startswith(("env:", "created:"))


def environments_account_errors(environments, env_keys) -> list[str]:
    """HF8-9: why a `credentials_by_role` of an `environments[]` entry is not a recorded account - empty when it is. Called by
    `--check-environment` only (`validate` is not asked: S2a's). A role is non-empty text and not reserved, its note is text; the names
    `gate_preflight.account_keys` reads from the note must all be among `env_keys` (the names the env file and the process hold, the
    one reading of them: `env_key_names`). A note that names no key ("NOT provisioned locally") is a legal record of a gap. Names
    only: no note is repeated in an error."""
    errors: list[str] = []
    account_keys = _sibling("gate_preflight").account_keys     # lazy: that module imports this one
    held = set(env_keys)
    for i, entry in enumerate(environments if isinstance(environments, list) else []):
        roles = entry.get("credentials_by_role") if isinstance(entry, dict) else None
        if not isinstance(roles, dict):
            continue
        for role, note in roles.items():
            label = f"environments[{i}].credentials_by_role[{str(role)[:60]!r}]"
            if not str(role).strip():
                errors.append(f"{label}: the role is empty; name the account's role or remove the entry")
            elif reserved_role(role):
                errors.append(f"{label}: `default`, `env:...` and `created:...` are read before any role, so this role can never be "
                              "reached by --as; rename the role")
            elif not isinstance(note, str):
                errors.append(f"{label} must be text: `<USER_KEY> / <SECRET_KEY>` (names of the env file, never a value)")
            else:
                keys = account_keys(note)
                if len(keys) != len(set(keys)):
                    errors.append(f"{label} names {next(k for k in keys if keys.count(k) > 1)} twice: a login and a password are two variables, so one name is not "
                                  "an account; give the two different names of the env file, or remove the role")
                absent = [name for name in keys if name not in held]
                if absent:
                    errors.append(f"{label} names {', '.join(absent)}, which the env file does not hold: add the name(s) to the file "
                                  "(the password goes there, never into config.json), or remove the role")
    return errors


# HF8-11: a place the code reads a key, `relative/path.py:12` (AR-4: never a machine's absolute path). Refused by the one
# pattern: a `~` start (a home directory is one machine's), a `..` segment (outside the project), a trailing newline.
READ_AT_RE = re.compile(r"^(?!~)(?!(?:.*[\\/])?\.\.(?:[\\/]|:\d+\Z))\S.*:\d+\Z")
ABSOLUTE_PATH_RE = re.compile(r"^(?:/|\\|[A-Za-z]:[\\/])")


def reads_recorded(integration) -> bool:
    """Does an `integrations[]` row say WHERE its code reads the keys (`read_at`: a non-empty list holding some text)? The
    presence of the field only - its form is `_read_at_errors`' to judge. The one predicate the gate and
    `environment_key_errors` share (AR-13)."""
    places = integration.get("read_at") if isinstance(integration, dict) else None
    return isinstance(places, list) and any(isinstance(p, str) and p.strip() for p in places)


def _name_errors(label: str, value, allow_empty: bool = True) -> list[str]:
    text = str(value or "")
    if not text:
        return [] if allow_empty else [f"{label} is empty"]
    return [] if KEY_NAME_RE.match(text) else [f"{label} must be a variable NAME, not a value"]


# OH3-10: the JSON body field NAMES a `local_login` endpoint expects. Names, never values; absent or empty = the
# default of a bare login form. One reader (`body_fields`) for the probe and the validator, so they cannot disagree.
BODY_FIELD_KEYS = ("user_field", "secret_field")
# the fallback when the row cannot be read; equal to its first pair (pinned by a test) - FB-3, AR-1
BODY_FIELD_DEFAULTS = {"user_field": "username", "secret_field": "password"}
BODY_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,63}$")
# FB-3 / FB-5: the pairs of field NAMES a local_login endpoint is tried with, a data row (FR-13, AR-1)
LOGIN_BODY_FIELDS_PATH = Path(__file__).resolve().parents[1] / "references" / "login-body-fields.json"


def _body_field_rows() -> list[tuple[str, str]]:
    """The valid pairs of references/login-body-fields.json, in order: a list of exactly two strings that both match
    `BODY_FIELD_RE` (stripped), the two different; a duplicate pair is dropped. Nothing valid (file absent or damaged,
    no `pairs`) reads as the single fallback pair - today's request, never no request (FR-59, AR-28)."""
    import hooklib  # the one JSON reader (AR-13)
    pairs = hooklib.read_json(LOGIN_BODY_FIELDS_PATH, {}, kind=dict).get("pairs")
    rows: list[tuple[str, str]] = []
    for item in pairs if isinstance(pairs, list) else []:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) for x in item)):
            continue
        pair = (item[0].strip(), item[1].strip())
        if all(BODY_FIELD_RE.match(x) for x in pair) and pair[0] != pair[1] and pair not in rows:
            rows.append(pair)
    return rows or [(BODY_FIELD_DEFAULTS["user_field"], BODY_FIELD_DEFAULTS["secret_field"])]


def default_body_fields() -> tuple[str, str]:
    """The first pair of the row: what an empty field of a recorded login reads as."""
    return _body_field_rows()[0]


def body_fields(access) -> tuple[str, str]:
    """(user field, secret field) the login body is built from: the recorded name, else the default. A recorded value
    that is not a string reads as the default here; `body_field_errors` is what refuses it."""
    access = access if isinstance(access, dict) else {}
    chosen = []
    for key, fallback in zip(BODY_FIELD_KEYS, default_body_fields()):
        raw = access.get(key)
        text = raw.strip() if isinstance(raw, str) else ""
        chosen.append(text or fallback)
    return chosen[0], chosen[1]


def body_fields_recorded(access) -> bool:
    """Whether the access block names either login body field (a non-blank string): the ONE reader of that fact."""
    access = access if isinstance(access, dict) else {}
    return any(isinstance(access.get(k), str) and access.get(k).strip() for k in BODY_FIELD_KEYS)


def body_field_candidates(access) -> list[tuple[str, str]]:
    """The pairs a login is tried with, in order: ONE pair when the access block names either field (recorded - never
    overridden by probing), else the rows of the data file. Never raises; it does not validate - callers run
    `body_field_errors` first."""
    if body_fields_recorded(access):
        return [body_fields(access)]
    return _body_field_rows()


def _field_name_error(label: str) -> str:
    """The one sentence for 'this is not a JSON body field name' (FR-1: one text per constraint)."""
    return f"{label} must be a JSON body field NAME (letters, digits, _ . -; at most 64), not a value or an object"


def body_field_errors(access) -> list[str]:
    """Why `access.user_field` / `access.secret_field` cannot shape a login body - empty when they can. A name that is
    not a field-name string is refused, and so are two equal names: the body is one JSON object, so equal names would
    drop the user from it while the login still read `ok` (invariant: the user is never silently dropped)."""
    if not isinstance(access, dict):
        return []
    errors: list[str] = []
    for key in BODY_FIELD_KEYS:
        raw = access.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue  # absent or empty = the default
        if not isinstance(raw, str) or not BODY_FIELD_RE.match(raw.strip()):
            errors.append(_field_name_error(f"environment.access.{key}"))
    if not errors:
        user, secret = body_fields(access)
        if user == secret:
            default_user, default_secret = default_body_fields()
            errors.append(f"environment.access.user_field and environment.access.secret_field both name the body "
                          f"field `{user}` (an empty one means `{default_user}` / "
                          f"`{default_secret}`), so one of the two would be dropped from the "
                          "login body - give them two different names")
    return errors


def access_errors(access) -> list[str]:
    """Why an `environment.access` block is not one - empty when it is."""
    if not isinstance(access, dict):
        return ["environment.access must be an object"]
    errors: list[str] = []
    # An empty `kind` is the template's own default: not recorded yet. The probe says that out
    # loud ("schema not recorded - onboarding gap") and readiness reports it; a config that has
    # not been through this version's onboarding is not a schema error.
    kind = str(access.get("kind") or "")
    if kind and kind not in ACCESS_KINDS:
        errors.append("environment.access.kind must be one of " + " | ".join(ACCESS_KINDS))
    for field in ACCESS_KEY_FIELDS:
        errors.extend(_name_errors(f"environment.access.{field}", access.get(field)))
    for field in ("command", "url"):
        if field in access and not isinstance(access.get(field), str):
            errors.append(f"environment.access.{field} must be a string")
    errors.extend(body_field_errors(access))
    if kind == "harness_command" and not str(access.get("command") or "").strip():
        errors.append("environment.access.command is required for kind harness_command")
    if kind in ("local_login", "oidc_password") and not str(access.get("url") or "").strip():
        errors.append(f"environment.access.url is required for kind {kind}")
    if kind == "bearer_env" and not str(access.get("token_key") or "").strip():
        errors.append("environment.access.token_key is required for kind bearer_env")
    codes = access.get("unauth_status", [])
    if not isinstance(codes, list):
        errors.append("environment.access.unauth_status must be a list of HTTP codes")
    else:
        for code in codes:
            if not isinstance(code, int) or isinstance(code, bool) or not 100 <= code <= 599:
                errors.append("environment.access.unauth_status must contain HTTP codes only")
                break
    probe = access.get("login_probe")
    if probe:  # an empty object is "no login proved yet", not a malformed proof
        if not isinstance(probe, dict):
            errors.append("environment.access.login_probe must be an object")
        else:
            errors.extend(_name_errors("environment.access.login_probe.user_key",
                                       probe.get("user_key")))
            for key in BODY_FIELD_KEYS:  # what the proof stored: names only (FB-3)
                raw = probe.get(key)
                if raw is not None and raw != "" and not (isinstance(raw, str) and BODY_FIELD_RE.match(raw)):
                    errors.append(_field_name_error(f"environment.access.login_probe.{key}"))
            status = probe.get("status")
            if status is not None and (not isinstance(status, int) or isinstance(status, bool)):
                errors.append("environment.access.login_probe.status must be an HTTP code")
            if "outcome" in probe and probe.get("outcome") not in LOGIN_OUTCOMES:
                errors.append("environment.access.login_probe.outcome must be one of " + " | ".join(LOGIN_OUTCOMES)
                              + " (only `ok` is a proof; leave it out when the login was not re-checked)")
            if not str(probe.get("checked_at") or "").strip():
                errors.append("environment.access.login_probe.checked_at is empty - a proof "
                              "without a date is prose")
            if "seconds" in probe:   # RN1-3: absent is never an error; a present one is read by the next login's ceiling
                import stand_access  # the ONE validity test of the field (AR-13); a local import: no cycle at load
                if stand_access.recorded_seconds({"login_probe": probe}) is None:
                    errors.append("environment.access.login_probe.seconds must be a positive number of seconds (how long "
                                  "the recorded login took); leave it out when unknown")
    return errors


def environment_errors(environment) -> list[str]:
    """Shape of the whole `environment` block: names where names belong, the access scheme,
    and `integrations[].required_by`. Absent optional parts are not errors - a config written
    before this version keeps working."""
    if environment is None:
        return []
    if not isinstance(environment, dict):
        return ["environment must be an object"]
    errors: list[str] = []
    for field in ("base_url_key", "user_key"):
        errors.extend(_name_errors(f"environment.{field}", environment.get(field)))
    for field in ("secret_keys", "extra_keys"):
        for i, name in enumerate(environment.get(field) or []):
            errors.extend(_name_errors(f"environment.{field}[{i}]", name, allow_empty=False))
    if "access" in environment:
        errors.extend(access_errors(environment.get("access")))
    if "frontend" in environment:
        errors.extend(frontend_errors("environment.frontend", environment.get("frontend"), "url_key"))
    for i, integration in enumerate(environment.get("integrations") or []):
        if not isinstance(integration, dict):
            errors.append(f"environment.integrations[{i}] must be an object")
            continue
        for j, name in enumerate(integration.get("keys") or []):
            errors.extend(_name_errors(f"environment.integrations[{i}].keys[{j}]", name,
                                       allow_empty=False))
        if "required_by" in integration:
            areas = integration.get("required_by")
            if not isinstance(areas, list) or not areas or \
                    not all(str(a or "").strip() for a in areas):
                errors.append(f"environment.integrations[{i}].required_by must be a non-empty "
                              "list of area or profile ids")
        errors.extend(_integration_alternative_errors(i, integration))
    return errors


def _integration_alternative_errors(index: int, integration: dict) -> list[str]:
    """HF8-11: the form of the fields onboarding writes next to `keys` - `credential_alternatives` (the data form of
    "another way to the same service", read by `env_probe.integration_readiness` and the gate), `read_at` and the two
    counters of a cut list. An ABSENT field is no error (a config written before this version keeps working); a field
    that is there is read as written, and the union of the alternatives must be `keys` (one statement of the names).
    Whether an alternative is SATISFIED is not asked here: `integration_readiness` is the one reader of that."""
    label = f"environment.integrations[{index}]"
    errors: list[str] = []
    if "credential_alternatives" in integration:
        errors.extend(_alternatives_errors(label, integration))
    if "read_at" in integration:
        errors.extend(_read_at_errors(label, integration.get("read_at")))
    for field in ("read_at_more", "required_by_more"):
        if field in integration:
            count = integration.get(field)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                errors.append(f"{label}.{field} must be a whole number of 1 or more")
    return errors


def _alternatives_errors(label: str, integration: dict) -> list[str]:
    """The shape of `credential_alternatives` and its union with `keys` (an error in the shape stops the union check)."""
    options = integration.get("credential_alternatives")
    if not isinstance(options, list) or not options or \
            not all(isinstance(option, list) and option for option in options):
        return [f"{label}.credential_alternatives must be a non-empty list of non-empty lists of variable names"]
    errors: list[str] = []
    named: list[str] = []
    for j, option in enumerate(options):
        for k, name in enumerate(option):
            problems = _name_errors(f"{label}.credential_alternatives[{j}][{k}]", name, allow_empty=False)
            errors.extend(problems)
            if not problems:
                named.append(str(name))
    keys = [str(k) for k in (integration.get("keys") or []) if isinstance(k, str)] \
        if isinstance(integration.get("keys") or [], list) else []
    odd = sorted(set(named) ^ set(keys))
    if not errors and odd:
        errors.append(f"{label}.keys must be the union of credential_alternatives; they differ in: " + ", ".join(odd))
    return errors


def _read_at_errors(label: str, places) -> list[str]:
    """`read_at`: a non-empty list of `path:line`, relative to the project (no absolute path, no `..`, no `~`)."""
    if not isinstance(places, list) or not places:
        return [f"{label}.read_at must be a non-empty list of `path:line` places"]
    errors: list[str] = []
    for j, place in enumerate(places):
        text = str(place) if isinstance(place, str) else ""
        if not READ_AT_RE.match(text):
            errors.append(f"{label}.read_at[{j}] must be `path:line`, inside the project (no `..`, no `~`)")
        elif ABSOLUTE_PATH_RE.match(text):
            errors.append(f"{label}.read_at[{j}] must be relative to the project, not an absolute path")
    return errors


def environment_key_errors(environment, env_keys, strict_integrations: bool = False) -> list[str]:
    """The check onboarding must pass before it writes: does this config's own probe survive
    the env file it names? `env_keys` are the NAMES that file (plus the process environment)
    holds right now. Each error says the two places a key may go instead."""
    if not isinstance(environment, dict):
        return []
    present = {str(k) for k in env_keys or []}
    errors: list[str] = []
    access = environment.get("access") if isinstance(environment.get("access"), dict) else {}
    wanted: list[tuple[str, str]] = [("user_key", str(environment.get("user_key") or "")),
                                     ("base_url_key", str(environment.get("base_url_key") or ""))]
    wanted += [(f"secret_keys[{i}]", str(k)) for i, k in enumerate(environment.get("secret_keys") or [])]
    wanted += [(f"access.{f}", str(access.get(f) or "")) for f in ACCESS_KEY_FIELDS]
    for label, name in wanted:
        if not name:
            continue
        if FACTORY_OWNED_KEY_RE.match(name):
            errors.append(f"{name} in environment.{label} is set by the factory itself, not by "
                          "this project - remove it")
            continue
        if CLIENT_SWITCH_KEY_RE.match(name):
            errors.append(f"{name} in environment.{label} is a client-side switch, not a stand "
                          "credential - move it to integrations[] with required_by, or remove it")
            continue
        if name not in present:
            errors.append(f"{name} is in environment.{label} but not in the env file - remove it "
                          "or move it to integrations[] with required_by")
    for i, name in enumerate(environment.get("extra_keys") or []):
        if FACTORY_OWNED_KEY_RE.match(str(name)) or CLIENT_SWITCH_KEY_RE.match(str(name)):
            errors.append(f"{name} in environment.extra_keys[{i}] is not this project's "
                          "credential - the factory sets it, or the client library does")
    if strict_integrations:
        for i, integration in enumerate(environment.get("integrations") or []):
            if not isinstance(integration, dict):
                continue
            absent = [str(k) for k in integration.get("keys") or [] if str(k) not in present]
            if absent and not (integration.get("required_by") or []):
                # HF8-11 / OH3-8: the place the code reads the keys is a legal stand-in for the area - the factory
                # knows where, and who needs it is not settled (a row that is only a fact). A named alternative that
                # is not set is no error either way: a key is wanted only in the set the project uses.
                if reads_recorded(integration):
                    continue
                errors.append(f"environment.integrations[{i}] names keys the env file does not "
                              f"hold ({', '.join(absent)}) without required_by - say which area "
                              "or profile needs them, record where the code reads them (read_at), "
                              "or drop them")
    return errors


def template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "templates" / "config.json"


def canonical_template() -> dict:
    return json.loads(template_path().read_text(encoding="utf-8"))


PARALLEL_WINDOWS_DEFAULT = 3


def parallel_windows(config) -> tuple[int, str | None]:
    """`dispatch.parallel_windows` as (value, note): how many S5 windows may run their role
    sessions at once. An absent key (every config written before the key existed), an absent
    `dispatch` or a config that is not an object reads the default 3 with no note; a value that
    is not an int >= 1 (0, -1, '3', 1.5, true, null) reads the default with ONE `note:` line and
    never a stop (P1, AR-3). The caller prints the note."""
    block = config.get("dispatch") if isinstance(config, dict) else None
    if not isinstance(block, dict) or "parallel_windows" not in block:
        return PARALLEL_WINDOWS_DEFAULT, None
    value = block["parallel_windows"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return PARALLEL_WINDOWS_DEFAULT, (
            f"note: dispatch.parallel_windows is {json.dumps(value)}, not a whole number of 1 or more; "
            f"S5 windows run {PARALLEL_WINDOWS_DEFAULT} at a time (the default) until it is corrected in "
            "qa-factory/config.json")
    return value, None


MANUAL_WALKERS_DEFAULT = 3


def walkers(config) -> tuple[int, str | None]:
    """`manual.walkers` as (value, note): how many S6 manual walkers (lanes) may run at once (t-2147 TR3-9d). THE reader for the
    driver and the controller (AR-13). An absent key (every config written before the key existed), an absent `manual` or a config
    that is not an object reads the default 3 with no note; a value that is not an int >= 1 (0, -1, '3', 1.5, true, null) reads the
    default with ONE `note:` line and never a stop (P1, AR-3). The caller prints the note."""
    block = config.get("manual") if isinstance(config, dict) else None
    if not isinstance(block, dict) or "walkers" not in block:
        return MANUAL_WALKERS_DEFAULT, None
    value = block["walkers"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return MANUAL_WALKERS_DEFAULT, (
            f"note: manual.walkers is {json.dumps(value)}, not a whole number of 1 or more; "
            f"{MANUAL_WALKERS_DEFAULT} manual walkers run at a time (the default) until it is corrected in "
            "qa-factory/config.json (1 runs one walker at a time)")
    return value, None


# t-2174 TR3-10b: `manual.accounts_way` and `manual.data_way` - how the project gets more test accounts and which records walkers
# may share or make. THE reader is `walk_supply` (AR-13); it judges SHAPE only (AR-29), tells and never stops (P1), and never
# consults the stand's breakability mark (P13: a recorded answer is returned as given).
WALK_SUPPLY_NOT_KNOWN = "not known"
# the three option sentences of the data-change question (the `answer` texts of `s6.data_change` in question-prices.json;
# test prices_data_change_three_options pins the two together) -> the value `walk_supply` returns for `data.may`
DATA_MAY_OPTIONS = {"only use what exists": "existing_only", "may create, never delete": "create",
                    "may create and delete": "create_and_delete"}
_WALK_SUPPLY_NAME_MAX = 40


def _supply_defaults() -> dict:
    return {"accounts": {"words": WALK_SUPPLY_NOT_KNOWN, "known": False, "self_sign_up_roles": [], "more_accounts": {},
                         "limit_by_role": {}},
            "data": {"words": WALK_SUPPLY_NOT_KNOWN, "known": False, "pools": {}, "may": "existing_only", "may_known": False}}


def _supply_name(text) -> str:
    return str(text)[:_WALK_SUPPLY_NAME_MAX]


def _supply_secret_hit(text: str, patterns: list) -> bool:
    """Does `text` match one of the project's `secret_content_patterns`? A pattern that does not compile is skipped (the reader never
    raises; guard_secrets reports the broken pattern where it is used)."""
    for pattern in patterns:
        try:
            if re.search(pattern, text):
                return True
        except re.error:
            continue
    return False


def _supply_words(block: dict, label: str, notes: list) -> tuple:
    """(words, known): the person's words whole, `not known` when absent, not a string or blank."""
    if "words" not in block:
        return WALK_SUPPLY_NOT_KNOWN, False
    value = block["words"]
    if not isinstance(value, str) or not value.strip():
        # the TYPE, never the value: a non-string `words` can hold anything, a credential included
        shown = type(value).__name__ if not isinstance(value, str) else "blank"
        notes.append(f"note: {label}.words is {shown}, not the person's words; it reads `{WALK_SUPPLY_NOT_KNOWN}` "
                     "until the question is answered")
        return WALK_SUPPLY_NOT_KNOWN, False
    return value, value.strip().casefold() != WALK_SUPPLY_NOT_KNOWN


def _supply_accounts(block: dict, patterns: list, notes: list) -> dict:
    out = _supply_defaults()["accounts"]
    out["words"], out["known"] = _supply_words(block, "manual.accounts_way", notes)
    label = "manual.accounts_way"
    sign_up = block.get("self_sign_up", {})
    if sign_up != {}:
        roles = sign_up.get("roles") if isinstance(sign_up, dict) else None
        if isinstance(roles, list) and all(isinstance(r, str) and r.strip() for r in roles):
            for role in roles:
                if role.strip() not in out["self_sign_up_roles"]:
                    out["self_sign_up_roles"].append(role.strip())
        else:
            notes.append(f"note: {label}.self_sign_up is not {{\"roles\": [a role or default, ...]}}; it reads as not mapped")
    more = block.get("more_accounts", {})
    if not isinstance(more, dict):
        notes.append(f"note: {label}.more_accounts is not an object of role -> env key pairs; it reads as empty")
    else:
        env_name = _sibling("gate_preflight")._ENV_NAME_RE
        for role, entries in more.items():
            if not isinstance(role, str) or not role.strip():
                notes.append(f"note: {label}.more_accounts has an entry with no role name; it was left out")
                continue
            if not isinstance(entries, list):
                notes.append(f"note: {label}.more_accounts for role `{_supply_name(role)}` is not a list of env:USER_KEY/SECRET_KEY "
                             "handles; the role was left out")
                continue
            kept = []
            for entry in entries:
                user, slash, secret = entry[4:].partition("/") if isinstance(entry, str) and entry.startswith("env:") else ("", "", "")
                if (isinstance(entry, str) and _supply_secret_hit(entry, patterns)) or not (
                        slash and env_name.match(user) and env_name.match(secret)):
                    notes.append(f"note: {label}.more_accounts for role `{_supply_name(role)}` holds an entry that is not an "
                                 "env:USER_KEY/SECRET_KEY handle of two key names (or looks like a secret); it was left out")
                    continue
                if entry not in kept:
                    kept.append(entry)
            if kept:
                out["more_accounts"][role.strip()] = kept
    limits = block.get("limit_by_role", {})
    if not isinstance(limits, dict):
        notes.append(f"note: {label}.limit_by_role is not an object of role -> a whole number of 1 or more; it reads as empty")
    else:
        for role, count in limits.items():
            if not isinstance(role, str) or not role.strip() or isinstance(count, bool) or not isinstance(count, int) or count < 1:
                notes.append(f"note: {label}.limit_by_role for role `{_supply_name(role)}` is not a whole number of 1 or more; "
                             "the entry was left out")
                continue
            out["limit_by_role"][role.strip()] = count
    return out


def _supply_pools(raw, patterns: list, notes: list) -> dict:
    """The shape-checked pools: `{kind (strip + casefold): {"existing": [...], ["create_request": text], ["delete_request": text]}}`."""
    label = "manual.data_way.pools"
    pools: dict = {}
    if raw == {}:
        return pools
    if not isinstance(raw, dict):
        notes.append(f"note: {label} is not an object of kind -> {{existing, create_request, delete_request}}; it reads as empty")
        return pools
    for kind, spec in raw.items():
        name = kind.strip().casefold() if isinstance(kind, str) else ""
        if not name or not isinstance(spec, dict):
            notes.append(f"note: {label} has a kind `{_supply_name(kind)}` that is not an object with a kind name; it was left out")
            continue
        existing = []
        listed = spec.get("existing", [])
        if not isinstance(listed, list):
            notes.append(f"note: {label} kind `{_supply_name(name)}`: `existing` is not a list of instance ids; it reads as empty")
            listed = []
        for item in listed:
            if not isinstance(item, str) or not item.strip():
                notes.append(f"note: {label} kind `{_supply_name(name)}` holds an instance id that is not a non-empty text; it was left out")
            elif _supply_secret_hit(item, patterns):
                notes.append(f"note: {label} kind `{_supply_name(name)}` holds an instance id that looks like a secret; it was left out")
            elif item.strip() not in existing:
                existing.append(item.strip())
        entry: dict = {"existing": existing}
        for field in ("create_request", "delete_request"):
            if field not in spec:
                continue
            text = spec[field]
            if not isinstance(text, str) or not text.strip():
                notes.append(f"note: {label} kind `{_supply_name(name)}`: `{field}` is not a non-empty text; it was left out")
            elif _supply_secret_hit(text, patterns):
                notes.append(f"note: {label} kind `{_supply_name(name)}`: `{field}` looks like a secret; it was left out")
            else:
                entry[field] = text
        if not entry["existing"] and "create_request" not in entry:
            notes.append(f"note: {label} kind `{_supply_name(name)}` has neither an `existing` list nor a `create_request`; it was left out")
            continue
        if name in pools:
            for item in entry["existing"]:
                if item not in pools[name]["existing"]:
                    pools[name]["existing"].append(item)
            for field in ("create_request", "delete_request"):
                if field in entry and field not in pools[name]:
                    pools[name][field] = entry[field]
                elif field in entry and entry[field] != pools[name][field]:
                    notes.append(f"note: {label} kinds that differ only in case or spaces (`{_supply_name(name)}`) carry two different "
                                 f"`{field}`s; the first is kept")
        else:
            pools[name] = entry
    return pools


def _supply_data(block: dict, patterns: list, notes: list) -> dict:
    out = _supply_defaults()["data"]
    out["words"], out["known"] = _supply_words(block, "manual.data_way", notes)
    if "may" in block:
        value = block["may"]
        sentence = value.strip().casefold() if isinstance(value, str) else None
        if sentence in DATA_MAY_OPTIONS:
            out["may"], out["may_known"] = DATA_MAY_OPTIONS[sentence], True
        elif sentence != WALK_SUPPLY_NOT_KNOWN:
            notes.append("note: manual.data_way.may is not one of the three answers (" + ", ".join(f"`{s}`" for s in DATA_MAY_OPTIONS)
                         + f"); it reads `{WALK_SUPPLY_NOT_KNOWN}` and walkers only use records that exist")
    pools = _supply_pools(block.get("pools", {}), patterns, notes)
    may = out["may"]
    withheld = []
    for field, allowed in (("create_request", may in ("create", "create_and_delete")),
                           ("delete_request", may == "create_and_delete")):
        if allowed:
            continue
        for kind in sorted(kind for kind, entry in pools.items() if field in entry):
            del pools[kind][field]
            withheld.append(f"`{field}` of `{_supply_name(kind)}`")
    if withheld:
        notes.append(f"note: manual.data_way.pools {', '.join(withheld)} not carried: the data-change answer reads `{may}`, "
                     "which does not allow it")
    out["pools"] = pools
    return out


def walk_supply(config) -> tuple[dict, list]:
    """`manual.accounts_way` and `manual.data_way` as (value, notes), THE reader of both (t-2174 TR3-10b, AR-13):
    `({"accounts": {"words", "known", "self_sign_up_roles", "more_accounts", "limit_by_role"},
       "data": {"words", "known", "pools", "may", "may_known"}}, [note, ...])`.
    Shape only (AR-29): `known` is a recorded answer, `data.may` is `existing_only` / `create` / `create_and_delete` and `existing_only`
    with `may_known: False` for anything else (FR-59: the safe default, never a pass); the pools carry only the requests the answer
    allows (AR-28); a value that looks like a secret (the config's `secret_content_patterns`) is dropped and never printed (the guard's default patterns plus the config's, even when the config list is empty).
    the stand's breakability mark is never consulted (P13). An absent `manual`, either block or key reads the defaults with no note; a bad value
    reads its default with ONE `note:` line; it never raises (a failure reads the defaults with one note naming the exception class).
    Shares nothing with `walkers`: a bad block here never changes it, nor the reverse. The caller prints the notes."""
    notes: list = []
    try:
        if not isinstance(config, dict) or "manual" not in config:
            return _supply_defaults(), notes
        manual = config["manual"]
        if not isinstance(manual, dict):
            return _supply_defaults(), ["note: manual is not an object; manual.accounts_way and manual.data_way read their defaults"]
        # the guard's own list (its defaults plus the project's), so `secret_content_patterns: []` never leaves a text unscanned;
        # a project pattern that does not compile is named once and left out (never silently skipped)
        guard = _sibling("guard_secrets")
        raw = config.get("secret_content_patterns")
        project = [p for p in raw if isinstance(p, str) and p] if isinstance(raw, list) else []
        broken = []
        for index, pattern in enumerate(project):
            try:
                re.compile(pattern)
            except re.error:
                broken.append(index)
        if broken:
            notes.append(f"note: secret_content_patterns[{', '.join(str(i) for i in broken)}] does not compile; "
                         "manual.* values were not scanned against it")
        project = [p for i, p in enumerate(project) if i not in broken]
        patterns = guard._patterns({"secret_content_patterns": project}, "secret_content_patterns",
                                   list(guard.DEFAULT_SECRET_CONTENT_PATTERNS))
        result = _supply_defaults()
        for key, build, slot in (("accounts_way", _supply_accounts, "accounts"), ("data_way", _supply_data, "data")):
            if key not in manual:
                continue
            block = manual[key]
            if not isinstance(block, dict):
                notes.append(f"note: manual.{key} is not an object; it reads its defaults")
                continue
            result[slot] = build(block, patterns, notes)
        return result, notes
    except Exception as exc:  # P1: a reader of the person's own config tells, never stops
        return _supply_defaults(), [f"note: manual.accounts_way and manual.data_way could not be read ({type(exc).__name__}); they read "
                                    f"their defaults (nothing known, only records that exist)"]


def walk_supply_keys() -> dict:
    """The config key names of the two supply blocks under `manual`, keyed by the slot `walk_supply` uses (AR-13: they stand here alone)."""
    return {"accounts": "accounts_way", "data": "data_way"}


def walk_supply_raw(config) -> dict:
    """`{"accounts": <manual.accounts_way as the config holds it or {}>, "data": <manual.data_way likewise or {}>}`: RAW - unknown and
    hand-added keys kept, nothing renamed or dropped (a deep copy). A missing or non-dict node reads `{}`; a non-dict config reads both `{}`.
    INVARIANT: used ONLY where an object is written back whole (merge on write); every reader that decides something keeps using the
    normalized `walk_supply`."""
    manual = config.get("manual") if isinstance(config, dict) else None
    manual = manual if isinstance(manual, dict) else {}
    return {slot: copy.deepcopy(manual[key]) if isinstance(manual.get(key), dict) else {} for slot, key in walk_supply_keys().items()}


def _merge_missing(target: dict, defaults: dict) -> dict:
    result = copy.deepcopy(target)
    for key, value in defaults.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = _merge_missing(result[key], value)
    return result


def effective_config(config: dict) -> dict:
    """Return runtime defaults without inventing project facts or mutating input."""
    return _merge_missing(config, RUNTIME_DEFAULTS)


def editable_strategy_paths(config: dict, root: Path) -> set[Path]:
    """Resolve the exact strategy files the factory may write; never return directories."""
    allowed: set[Path] = set()
    for doc in config.get("strategy_documents") or []:
        if not isinstance(doc, dict) or doc.get("editable") is not True:
            continue
        raw = str(doc.get("path") or "")
        if raw and not Path(raw).is_absolute():
            allowed.add((root / raw).resolve(strict=False))
    # Compatibility permission is intentionally limited to the two historical targets.
    if config.get("factory_may_edit_strategy") is True:
        allowed.update({(root / "qa-factory/strategy/test-strategy.md").resolve(strict=False),
                        (root / "qa-factory/strategy/framework-rules.md").resolve(strict=False)})
    return allowed


def strategy_document(config: dict, name: str) -> str | None:
    """The project-root-relative path of the project's own copy of `strategy/<name>`, else None.

    A project with a pre-existing `docs/test-strategy.md` lists it in `strategy_documents[]`, and that file - not the
    conventional generated path - is the document a role reads. This is the ONE place the basename redirect is
    decided: the injection (`inject_context.resolve_entry`) and the brief's doors (`brief_pack._resolve`) both call
    it, so they cannot name two files for one document (SC1-9/10 fix round, finding F1).

    Error direction: None - the conventional path stays - for anything but exactly one relative entry with that
    basename: no `strategy_documents`, an empty or non-list value, two entries with the same basename (no guess
    between them), an absolute entry, a config that is not an object."""
    docs = config.get("strategy_documents") if isinstance(config, dict) else None
    if not name or not isinstance(docs, list):
        return None
    matches = [str(doc.get("path") or "") for doc in docs
               if isinstance(doc, dict) and Path(str(doc.get("path") or "")).name == name]
    if len(matches) == 1 and matches[0] and not Path(matches[0]).is_absolute():
        return matches[0]
    return None


TEST_DATA_UNKNOWN = ("unknown", "tbd", "?")     # a recorded "I do not know" (the template's `test_data_note`); "" is silence


def test_data_states(config) -> dict:
    """The ONE reader of the project's `test_data` block (AR-13): the brief of the roles and the code judge both ask it.

    -> {"state": "read"|"absent"|"malformed", "keys": [(key, status)], "values": {key: value}}. `absent`: no config, a
    config that is not an object, or no `test_data` key; `malformed`: `test_data` is not an object. Otherwise the keys are
    those of the template's block in its order (the closed variety is a data file, AR-1), then the project's own keys in
    file order. A key's status: `not_recorded` (missing, or blank text), `unknown` (TEST_DATA_UNKNOWN, any case, "TBD" too),
    `none` (an empty list: no exception), `recorded` (any other non-empty value). `values` holds the `recorded` ones as
    given. Never raises: a template that cannot be read leaves the project's own keys."""
    block = config.get("test_data") if isinstance(config, dict) else None
    if not isinstance(config, dict) or "test_data" not in config:
        return {"state": "absent", "keys": [], "values": {}}
    if not isinstance(block, dict):
        return {"state": "malformed", "keys": [], "values": {}}
    try:
        template = canonical_template().get("test_data")
        names = [str(k) for k in template] if isinstance(template, dict) else []
    except Exception:
        names = []
    names += [str(k) for k in block if str(k) not in names]
    keys, values = [], {}
    for name in names:
        value = block.get(name)
        if isinstance(value, list):
            status = "recorded" if value else "none"
        elif value is None or (isinstance(value, str) and not value.strip()):
            status = "not_recorded"
        elif isinstance(value, str) and value.strip().lower() in TEST_DATA_UNKNOWN:
            status = "unknown"
        else:
            status = "recorded"
        keys.append((name, status))
        if status == "recorded":
            values[name] = value
    return {"state": "read", "keys": keys, "values": values}


def stop_after_problem(config, short: bool = False) -> str:
    """`''` when `pipeline.stop_after` is fine (no key, null, gate_A, gate_B, or a config that is not an object), else ONE
    line naming what the project wrote. The reader (`controller.stop_after`) reads any other value as no stop at all, so the
    story runs to the end: this line is how the person learns it (GW1-19). It is NOT a `validate` error: a `validate`
    error locks `apply_plan` and makes `config_schema` not_configured (P1); the caller adds the line, the status stays.
    The value is shown cut to 80 characters (`short`: 40, the line <= 180 for the gate brief), the verdict never depends
    on the cut."""
    if not isinstance(config, dict) or "pipeline" not in config:
        return ""
    import hooklib  # the one list of stop values (AR-13); a local import: no cycle at load
    block = config["pipeline"]
    if not isinstance(block, dict):
        return ("`pipeline` must be an object in qa-factory/config.json: it is not, so `pipeline.stop_after` cannot be read "
                "and every story runs to the end.")
    value = block.get("stop_after")
    if value is None or (isinstance(value, str) and value in hooklib.STOP_VALUES):
        return ""
    limit = 40 if short else 80
    try:
        shown = json.dumps(value)
    except (TypeError, ValueError, RecursionError):
        shown = repr(type(value).__name__)
    shown = shown[:limit] + ("…" if len(shown) > limit else "")
    names = " or ".join(hooklib.STOP_VALUES)
    if short:
        return f"`pipeline.stop_after` is {shown}, not {names}: this story will not stop after the gate."
    return (f"`pipeline.stop_after` is {shown}: it is not one of {', '.join(hooklib.STOP_VALUES)}, null, so it stops "
            "nothing and every story runs to the end. Correct it in qa-factory/config.json.")


def validate(config: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["config must be an object"]
    if config.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    parallel = (((effective_config(config).get("execution") or {}).get("parallel")) or {})
    if parallel.get("mode") not in {"auto", "serial"}:
        errors.append("execution.parallel.mode must be auto or serial")
    threshold = parallel.get("min_selected_instances")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        errors.append("execution.parallel.min_selected_instances must be a positive integer")
    workers = parallel.get("max_workers")
    if workers is not None and (not isinstance(workers, int) or isinstance(workers, bool) or workers < 1):
        errors.append("execution.parallel.max_workers must be null or a positive integer")
    sources = config.get("requirements_sources") or []
    try:
        source_table = requirement_source_kinds() if sources else None
    except ValueError as exc:        # a damaged table is an error naming the file, not "no kinds" (AR-28)
        source_table = None
        errors.append(f"requirements_sources cannot be checked: {exc}")
        # the rows are still checked below for shape, locator and names; only the kind and status words need the table
    for i, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"requirements_sources[{i}] must be an object")
            continue
        if source_table and source.get("kind") not in source_table["kinds"]:
            errors.append(f"requirements_sources[{i}].kind is invalid")
        if source_table and source.get("status") not in source_table["statuses"]:
            errors.append(f"requirements_sources[{i}].status is invalid")
        locator = str(source.get("locator") or "")
        if SECRET_QUERY_RE.search(locator):
            errors.append(f"requirements_sources[{i}].locator contains a credential-like query field")
        for field in ("method", "invoke_or_command_ref"):     # the route of a tracker row (SS1-15): text or absent (t-586 F-2)
            value = source.get(field)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                errors.append(f"requirements_sources[{i}].{field} must be text")
            elif field == "invoke_or_command_ref" and route_has_secret(value):
                errors.append(f"requirements_sources[{i}].{field} contains a credential-like query field")
        for field in REQUIREMENT_SOURCE_NAME_FIELDS:
            value = source.get(field)
            if value is None or value == "":
                continue            # optional: absent or empty is no name given
            if not isinstance(value, str):
                errors.append(f"requirements_sources[{i}].{field} must be a variable NAME, not a value")
            else:
                errors.extend(_name_errors(f"requirements_sources[{i}].{field}", value))
    for i, doc in enumerate(config.get("strategy_documents") or []):
        if not isinstance(doc, dict):
            errors.append(f"strategy_documents[{i}] must be an object")
            continue
        if Path(str(doc.get("path") or "")).is_absolute() or not str(doc.get("path") or ""):
            errors.append(f"strategy_documents[{i}].path must be a non-empty relative path")
        if doc.get("provenance") not in {"factory_created", "pre_existing", "legacy_unknown"}:
            errors.append(f"strategy_documents[{i}].provenance is invalid")
        if not isinstance(doc.get("editable"), bool):
            errors.append(f"strategy_documents[{i}].editable must be boolean")
    errors.extend(environment_errors(config.get("environment")))
    errors.extend(environments_frontend_errors(config.get("environments")))
    errors.extend(environments_surface_errors(config.get("environments")))
    scale = config.get("impact_scale")
    if scale is not None:
        if not isinstance(scale, dict):
            errors.append("impact_scale must be an object")
        else:
            for key, value in scale.items():
                if not isinstance(value, dict) or set(value) < {"priority", "severity"}:
                    errors.append(f"impact_scale.{key} must contain priority and severity (numeric legacy values require a decision)")
    metrics = effective_config(config)["metrics"]
    if not isinstance(metrics.get("window_days"), int) or metrics["window_days"] < 1:
        errors.append("metrics.window_days must be a positive integer")
    share = metrics.get("bugginess_report_share")
    if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 < share <= 1:
        errors.append("metrics.bugginess_report_share must be in (0,1]")
    cost = effective_config(config).get("cost") or {}
    for i, override in enumerate(cost.get("rate_overrides") or []):
        if not isinstance(override, dict) or not str(override.get("model_id") or ""):
            errors.append(f"cost.rate_overrides[{i}].model_id is required")
            continue
        if not isinstance(override.get("aliases", []), list):
            errors.append(f"cost.rate_overrides[{i}].aliases must be an array")
        rates = override.get("rates")
        if not isinstance(rates, dict):
            errors.append(f"cost.rate_overrides[{i}].rates must be an object")
        else:
            for field in PRICE_FIELDS:
                value = rates.get(field)
                if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
                    errors.append(f"cost.rate_overrides[{i}].rates.{field} must be nonnegative")
    return errors


def env_key_names(root: Path, environment: dict) -> list[str]:
    """The NAMES available to this project right now: the configured env file plus the process
    environment, the same two sources `env_probe` reads. Values are never touched."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project_inventory import env_file_keys  # noqa: E402
    names = list(os.environ)
    rel = str((environment or {}).get("env_file") or "").strip()
    if rel:
        path = root / rel
        if path.exists():
            names.extend(env_file_keys(path))
    for extra in (environment or {}).get("env_files") or []:
        path = root / str(extra)
        if path.exists():
            names.extend(env_file_keys(path))
    return sorted(set(names))


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


# --- the old project price table (B-225) --------------------------------------------------
# One price per model: the factory's own list (references/model-rates.json). A project's rate
# exists only as a person's explicit correction of a NAMED model (`cost.rate_overrides`). An
# older config may still carry `cost.model_prices`, a table keyed by model FAMILY ("claude-
# sonnet" prices every model whose id contains it). The 29.09 comparison run priced the same
# story at two figures because such a key shadowed the list price of `claude-sonnet-5-5`
# (3/15 against 2/10). Whether the old numbers are the project's real prices or only stale
# is a fact only the person holds, so the plan asks; it never guesses in either direction.
PRICE_TABLE_PATH = "/cost/model_prices"
PRICE_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
PRICE_ANSWERS = ("builtin", "own")


def _catalogue_entries(catalogue: dict | None = None) -> list[dict]:
    """The built-in list's entries. An unreadable list yields none: there is nothing to
    compare the table with, and the cost reader says so on its own."""
    if catalogue is None:
        try:
            catalogue = json.loads((Path(__file__).resolve().parents[1] / "references"
                                    / "model-rates.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    entries = catalogue.get("entries") if isinstance(catalogue, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _table_rates(value) -> dict | None:
    """A table entry as the cost reader prices with it: the old single `cache_write` figure
    stands for both write tiers. None when the entry is not an object at all."""
    if not isinstance(value, dict):
        return None
    rates = dict(value)
    if "cache_write" in rates:
        rates.setdefault("cache_write_5m", rates["cache_write"])
        rates.setdefault("cache_write_1h", rates["cache_write"])
    return rates


def _same_rates(table_value, catalogue_rates) -> bool:
    """Equal in every price field. A field only one side has, or a value that is not a
    number, counts as different: the error is a question too many, never a silent pass."""
    rates = _table_rates(table_value)
    if rates is None:
        return False
    listed = catalogue_rates if isinstance(catalogue_rates, dict) else {}
    for field in PRICE_FIELDS:
        old, new = rates.get(field), listed.get(field)
        if old is None and new is None:
            continue
        if not (_is_number(old) and _is_number(new)) or old != new:
            return False
    return True


def _price_shadows(config: dict, catalogue: dict | None = None) -> tuple[dict, set]:
    """({catalogue model id: (table key, table entry as written, list rates)}, every table
    key that reaches at least one catalogue id). A key reaches an id that contains it; the
    longest key wins per id, as the cost reader resolves it. A key that reaches no
    catalogue id is never part of this, so it is never asked about and never removed."""
    cost = config.get("cost") if isinstance(config, dict) else None
    table = cost.get("model_prices") if isinstance(cost, dict) else None
    if not isinstance(table, dict) or not table:
        return {}, set()
    shadows: dict = {}
    reaching: set = set()
    for entry in _catalogue_entries(catalogue):
        model_id = entry.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            continue
        keys = [k for k in table if isinstance(k, str) and k and k in model_id]
        if keys:
            key = max(keys, key=len)
            shadows[model_id] = (key, table[key], entry.get("rates"))
            reaching.update(keys)
    return shadows, reaching


def _rate_text(value) -> str:
    """One rate set as a person reads it: input / output / cache read / cache write 5 min /
    cache write 1 h. A value that is not a set of numbers is shown as written."""
    rates = value if not isinstance(value, dict) else _table_rates(value)
    if not isinstance(rates, dict):
        return json.dumps(value, ensure_ascii=False)
    parts = []
    for field in PRICE_FIELDS:
        item = rates.get(field)
        parts.append("not set" if item is None else f"{item:.10g}" if _is_number(item)
                     else json.dumps(item, ensure_ascii=False))
    return " / ".join(parts)


def _override_covers(entry, model_id: str) -> bool:
    """An own-price entry prices this id: by its model id or as an alias. A value that is not
    an object names no model."""
    if not isinstance(entry, dict):
        return False
    aliases = entry.get("aliases") if isinstance(entry.get("aliases"), list) else []
    return model_id in [entry.get("model_id"), *aliases]


def _override_text(entry: dict) -> str:
    """The rates of an own-price entry as a person reads them, or as written when they are
    not a set of numbers."""
    if "rates" not in entry:
        return "with no rates set"
    return _rate_text(entry["rates"])


def price_table_conflict(config: dict, catalogue: dict | None = None) -> dict | None:
    """The question about an old price table, or None when there is nothing to decide: no
    table, or every catalogue model the table reaches carries the same rates in it."""
    shadows, _ = _price_shadows(config, catalogue)
    rows = [{"model_id": model_id, "table_key": key, "table_rates": value, "catalogue_rates": listed,
             "line": f"{model_id}: old table {_rate_text(value)}; built-in {_rate_text(listed)}"}
            for model_id, (key, value, listed) in sorted(shadows.items())
            if not _same_rates(value, listed)]
    if not rows:
        return None
    models = ", ".join(row["model_id"] for row in rows)
    listing = "\n".join(f"- {row['line']}" for row in rows)
    question = (
        "The factory prices every model by its built-in list prices. This project's configuration "
        f"also carries an older price table, and for {models} it sets a different price. The "
        "factory has changed nothing: it cannot know whether the old numbers are prices your team "
        "really pays or only figures that went out of date.\n\n"
        "Prices per million tokens (input / output / cache read / cache write 5 min / cache write "
        f"1 h), old table against built-in:\n{listing}\n\n"
        "Which prices should this project use?\n"
        "(a) The built-in prices (the default). The old table entries that cover models the "
        "factory knows are removed; entries for models it does not know stay.\n"
        "(b) Our own prices. Name the exact models whose old price is really yours: those become "
        "your project's own prices, and the old table entries that cover known models are removed.\n"
        "(c) Something else. Say it in your own words: the factory changes nothing and passes your "
        "words on as written.\n\n"
        "---\n"
        "Answer: reply (a), or (b) with the model names, or (c) with your words. The doctor "
        "changes nothing; the onboarding skill carries (a) and (b) out and shows you the changed "
        "configuration for approval before anything is written:\n"
        "  python \"${CLAUDE_PLUGIN_ROOT}/scripts/config_contract.py\" --root . --migration-plan "
        "--price-table-answer builtin\n"
        "  python \"${CLAUDE_PLUGIN_ROOT}/scripts/config_contract.py\" --root . --migration-plan "
        "--price-table-answer own --model-id <model> [--model-id <model> ...]\n")
    return {"path": PRICE_TABLE_PATH, "question": question, "default": "builtin", "rows": rows}


def _apply_price_answer(proposed: dict, answer: str, model_ids, catalogue: dict | None) -> list[dict]:
    """Carry answer (a) `builtin` or (b) `own` out on `proposed`, in place; return the change
    rows. Every table key that reaches a catalogue model is removed, so the plan of the result
    has nothing left to ask (FR-7); a key for a model the catalogue does not know stays."""
    shadows, reaching = _price_shadows(proposed, catalogue)
    cost = proposed["cost"]
    old_table = cost["model_prices"]
    changes: list[dict] = []
    if answer == "own":
        named = list(dict.fromkeys(str(m).strip() for m in (model_ids or []) if str(m).strip()))
        if not named:
            raise ValueError("answer own needs at least one exact model id (--model-id); "
                             "to use the built-in prices instead, answer builtin")
        overrides = cost.get("rate_overrides")
        if overrides is None:
            overrides = []
        if not isinstance(overrides, list):
            raise ValueError("cost.rate_overrides is not a list, so own prices cannot be added to it")
        added = []
        new_overrides = list(overrides)
        model_rows: list[dict] = []
        for model_id in named:
            covering = next((i for i, o in enumerate(new_overrides) if _override_covers(o, model_id)), None)
            if model_id not in shadows:
                if covering is None:
                    raise ValueError(f"{model_id} is not a model the old price table reaches; "
                                     "the exact ids it reaches: " + ", ".join(sorted(shadows)))
                # The model has its own price and the old table has none for it: nothing to take
                # from the table, the price stays, and the plan says so.
                kept = new_overrides[covering]
                model_rows.append({"path": f"/cost/rate_overrides/{model_id}", "from": copy.deepcopy(kept),
                                   "to": copy.deepcopy(kept),
                                   "reason": f"the old price table has no price for {model_id}; its own price "
                                             f"{_override_text(kept)} is left as it is"})
                continue
            key, value, _ = shadows[model_id]
            rates = _table_rates(value)
            if rates is None or not all(_is_number(rates[f]) and rates[f] >= 0
                                        for f in PRICE_FIELDS if rates.get(f) is not None) \
                    or not any(rates.get(f) is not None for f in PRICE_FIELDS):
                raise ValueError(f"the old price for {model_id} is not a set of numbers "
                                 f"({_rate_text(value)}); give the numbers in your own words (answer c) "
                                 "or use the built-in prices (answer builtin)")
            entry = {"model_id": model_id, "aliases": [],
                     "rates": {f: rates[f] for f in PRICE_FIELDS if rates.get(f) is not None},
                     "note": f"from the old project price table entry {key}"}
            if covering is None:
                added.append(entry)
                continue
            # The person's answer is the newer word (P13): an own price already there is replaced,
            # and the row keeps the old one beside the new one. Equal prices change nothing.
            old = new_overrides[covering]
            if _same_rates(entry["rates"], old.get("rates")):
                continue
            if old.get("model_id") == model_id:
                if isinstance(old.get("aliases"), list):
                    entry["aliases"] = copy.deepcopy(old["aliases"])
                new_overrides[covering] = entry
            else:  # the old entry covers the id only as an alias: the id leaves it, nothing else of it moves
                stripped = copy.deepcopy(old)
                stripped["aliases"] = [a for a in old["aliases"] if a != model_id]
                new_overrides[covering] = stripped
                new_overrides.insert(covering, entry)
            model_rows.append({"path": f"/cost/rate_overrides/{model_id}", "from": copy.deepcopy(old),
                               "to": copy.deepcopy(entry),
                               "reason": f"{model_id} already has your own price {_override_text(old)}; "
                                         f"your answer replaces it with {_rate_text(entry['rates'])}"})
        new_overrides.extend(added)
        if new_overrides != overrides:
            changes.append({"path": "/cost/rate_overrides", "from": copy.deepcopy(cost.get("rate_overrides")),
                            "to": new_overrides, "reason": "own prices named by the person (answer b)"})
        changes.extend(model_rows)
        cost["rate_overrides"] = new_overrides
    cost["model_prices"] = {k: v for k, v in old_table.items() if k not in reaching}
    changes.insert(0, {"path": PRICE_TABLE_PATH, "from": old_table, "to": cost["model_prices"],
                       "reason": "built-in prices (answer a)" if answer == "builtin"
                       else "own prices named, shadowing entries removed (answer b)"})
    return changes


# --- installing is migrating (t-232): the table, the hash, the plan --------------------------
KEYS_PATH = Path(__file__).resolve().parents[1] / "references" / "config-keys.json"
PLUGIN_JSON_PATH = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"
# What an approval authorizes: the exact configuration that will be written and everything the
# plan says it removed, renamed, moved or left to be asked. `conflicts`, `reasked` and `added`
# are in it so that deleting an open question from the proposal file cannot keep the approval
# valid (the whole proposal was hashed before this change, and that guarantee is kept; `added`
# joined it with the answers gate, t-239 O2-5: apply refuses a proposal that still lists a
# required key nobody answered, and a proposal file with that row deleted must not slip past).
# `input_hash` is not: `apply_plan` compares it with the config on disk, so it needs no second
# check. A proposal that carries a `listing` (what onboard_apply will retire) covers it as well.
PROPOSAL_COVERS = ("proposed_config", "removed", "renamed", "answers_legacy", "conflicts", "reasked", "added")


class ConfigUnreadable(ValueError):
    """qa-factory/config.json exists but is empty, not JSON, or not an object. The message
    names the door (FR-1, FR-57): the factory does not guess what the file should have said."""


def config_keys() -> dict:
    """The parsed references/config-keys.json. A damaged table is a plugin install problem,
    named as one - never an empty table that would pass every key."""
    try:
        data = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"references/config-keys.json of the plugin is unreadable "
                         f"({type(exc).__name__}: {exc}); the plugin install is damaged - "
                         "reinstall the plugin") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
        raise ValueError("references/config-keys.json of the plugin has no `keys` table; "
                         "the plugin install is damaged - reinstall the plugin")
    return data


def package_version() -> str:
    """`version` of .claude-plugin/plugin.json, or the word `unknown` (FR-41)."""
    try:
        return str(json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8")).get("version") or "unknown")
    except (OSError, ValueError, AttributeError):
        return "unknown"


def read_config_file(root: Path) -> dict | None:
    """The project's config as a dict, None when there is no qa-factory/config.json (the empty
    input of the migration), ConfigUnreadable when the file is there and cannot be read as one
    JSON object. A byte-order mark is tolerated: an editor put it there, nobody meant it."""
    path = Path(root) / "qa-factory" / "config.json"
    if not path.exists():
        return None
    door = ("The factory does not guess what it should say: fix the file by hand, or move it "
            "aside (rename it, for example to config.broken.json) and run onboarding again to "
            "write a new one.")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigUnreadable(f"qa-factory/config.json cannot be read ({type(exc).__name__}: {exc}). "
                               + door) from exc
    if not text.strip():
        raise ConfigUnreadable("qa-factory/config.json is empty; it must hold one JSON object. " + door)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigUnreadable(f"qa-factory/config.json is not valid JSON ({exc}); it must hold one "
                               "JSON object. " + door) from exc
    if not isinstance(data, dict):
        kind = {list: "list", str: "string", type(None): "null", bool: "boolean"}.get(type(data), "number")
        raise ConfigUnreadable(f"qa-factory/config.json holds a JSON {kind}, not a JSON object. " + door)
    return data


def proposal_hash(proposal: dict, extra: dict | None = None) -> str:
    """The hash an approval is bound to (C2): sha256 over PROPOSAL_COVERS of the proposal, over its
    `listing` when it has one, and over `extra` - the documented hook for whatever else a caller
    wants an approval to authorize (name -> JSON value). The same function seals a proposal and
    checks it, so a caller that passes `extra` when sealing passes it again to
    `record_approval`, `apply_plan` and `is_approved`."""
    covered = {key: proposal.get(key) for key in PROPOSAL_COVERS}
    if "listing" in proposal:
        covered["listing"] = proposal["listing"]
    if extra:
        covered.update(extra)
    return _json_hash(covered)


def _pointer(dotted: str) -> str:
    return "/" + dotted.replace(".", "/")


def _parent_of(root, dotted: str, create: bool = False):
    """(the object holding the last step of a dotted path, that last key); the object is None
    when a step on the way is not an object (and `create` is off)."""
    parts = dotted.split(".")
    node = root
    for part in parts[:-1]:
        if not isinstance(node, dict):
            return None, parts[-1]
        if part not in node and create:
            node[part] = {}
        node = node.get(part)
    return (node if isinstance(node, dict) else None), parts[-1]


def _canonical_order(value, template, path: str, moved: list):
    """`value` with the template's key order: template keys first, in template order, then the
    keys the template does not know (a person's) in their original order; nested objects the
    same way. Values are never touched. `moved` collects the JSON pointers of every object
    whose key order changed (the top level is "/")."""
    if not (isinstance(value, dict) and isinstance(template, dict)):
        return value
    ordered = {key: _canonical_order(value[key], template[key], f"{path.rstrip('/')}/{key}", moved)
               for key in template if key in value}
    ordered.update({key: item for key, item in value.items() if key not in ordered})
    if list(ordered) != list(value):
        moved.append(path)
    return ordered


def _legacy_slot(legacy: dict, key: str, value, version: str):
    """Where a person's note goes inside `answers_legacy`: under its own key when that is free,
    else under `<key>@<package_version>` (numbered when even that is taken) - an existing entry
    is never overwritten. None when an equal value is already kept for the key."""
    kept = [name for name in legacy if name == key or name.startswith(key + "@")]
    if any(legacy[name] == value for name in kept):
        return None
    if key not in legacy:
        return key
    slot, number = f"{key}@{version}", 2
    while slot in legacy:
        slot, number = f"{key}@{version}#{number}", number + 1
    return slot


def _machine_local_value(value) -> bool:
    # audit A20's own gate, reused: the migration drops what that gate would refuse, and the gate
    # may err only toward "machine-local" (dropped, then derived again on this machine). Imported
    # here, not at the top: audit_factory pulls the whole hook layer in, which nothing else that
    # imports this module needs.
    import sys as _sys
    here = str(Path(__file__).resolve().parent)
    if here not in _sys.path:
        _sys.path.insert(0, here)
    from audit_factory import _machine_local
    return _machine_local(value)


def _probe_has_machine_local(spec) -> bool:
    """Does this `execution.runtime_probes` entry name a place only the machine that wrote it can resolve? audit A20's
    `_probe_machine_local` answers per element: a container path after `--app-root` is not one, and the gate may err
    only toward "machine-local" for everything else (an absolute checkout, an absolute interpreter, a drive)."""
    import sys as _sys
    here = str(Path(__file__).resolve().parent)
    if here not in _sys.path:
        _sys.path.insert(0, here)
    from audit_factory import _probe_machine_local
    return bool(_probe_machine_local(spec))


def _set_pointer(root: dict, pointer: str, value, drop: bool = False) -> bool:
    """Put `value` at a JSON pointer (`/environment/access/kind`), creating the objects on the
    way when they are absent. False - nothing written - when a step is not an object or the
    pointer is not one. `drop`: take the key at the pointer out instead (`value` is ignored);
    a step that is absent is then False too, nothing is created on the way."""
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        return False
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]
    node = root
    for part in parts[:-1]:
        if part not in node:
            if drop:
                return False
            node[part] = {}
        node = node[part]
        if not isinstance(node, dict):
            return False
    if drop:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value
    return True


APPROVALS_NAME = "onboarding-approvals.jsonl"      # a carried record: qa-factory/records/ (runtime_paths.py)
MIGRATIONS_NAME = "config-migrations"              # the backups of replaced configs: the same folder
# The receipt the role's fold step records (`--record-approval ... --fold`): onboard_apply reads it
# before it lets the old product passport go.
FOLD_TOKEN = "product-passport -> project-profile"


def _paths():
    """runtime_paths, the one source of where the carried records live (the new folder, or the old
    one while a project has not been re-onboarded). Imported here, not at the top: this module is
    also imported by tests and tools that put `scripts/` on the path themselves."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import runtime_paths
    return runtime_paths


def approvals_path(root) -> Path:
    return _paths().record(Path(root), APPROVALS_NAME)


ANSWERED_PREFIX = "answered"        # the `kept` reasons of an answered pointer all start with this
DEFAULT_RENAMED = "changed: default path renamed"   # the `kept` row of a value migration (config-keys.json `value_migrations`); the value DOES change, so the word is not "kept" (t-272 item 5)


def _pointer_get(value, pointer: str) -> tuple:
    """(found, value) at a JSON pointer, `(False, None)` when a step is missing or not an object."""
    node = value
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _answers_of(proposal: dict, tmpl: dict) -> tuple:
    """({pointer: value}, {pointer: template default}) of the pointers this proposal's `kept` rows
    say a person answered (now or earlier): the memory a later plan reads (FR-7). The default of
    the template is stored next to the answer because the answer is only good while that default
    stands - a key whose default moved is a different question (None when the template has no
    default there)."""
    config = proposal.get("proposed_config")
    answers, defaults = {}, {}
    for row in proposal.get("kept") or []:
        pointer = row.get("path") if isinstance(row, dict) else None
        if not (isinstance(pointer, str) and pointer.startswith("/") and pointer != "/"
                and str(row.get("reason", "")).startswith(ANSWERED_PREFIX)):
            continue
        found, value = _pointer_get(config, pointer)
        if found:
            answers[pointer] = copy.deepcopy(value)
            defaults[pointer] = copy.deepcopy(_pointer_get(tmpl, pointer)[1])
    return answers, defaults


def remembered_answers(root, template: dict | None = None) -> dict:
    """{pointer: value}: the answers earlier approvals recorded, the latest record of each
    pointer winning, kept only while the template default recorded beside the answer is still the
    template's default. A log line that cannot be read is skipped: a remembered answer is a
    convenience, and a question asked once too often is the safe direction (FR-41)."""
    path = approvals_path(root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    tmpl = canonical_template() if template is None else template
    out: dict = {}
    for line in lines:
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if not (isinstance(record, dict) and record.get("status") == "approved"
                and isinstance(record.get("answers"), dict) and isinstance(record.get("answer_defaults"), dict)):
            continue
        for pointer, value in record["answers"].items():
            if pointer in record["answer_defaults"]:
                out[pointer] = (value, record["answer_defaults"][pointer])
    return {pointer: value for pointer, (value, default) in out.items()
            if _pointer_get(tmpl, pointer)[1] == default}


def _is_note(name: str) -> bool:
    return name == "note" or name.endswith("_note")


def _added_row(parts: list, table: dict) -> dict:
    """The `added` row of one filled key. A top-level key is described by the table
    (`unknown` when it is not there). A nested key inherits the `since` of its top-level key
    unless the table lists the pointer itself, and is `default` unless the table says
    otherwise: its parent object is what was missing or present, not a new requirement."""
    note_table = table.get("notes") or {}
    key_table = table.get("keys") or {}
    dotted = ".".join(parts)
    meta = (note_table if _is_note(parts[-1]) else key_table).get(dotted) or {}
    if len(parts) == 1:
        return {"path": _pointer(dotted), "since": meta.get("since") or "unknown",
                "absent_means": meta.get("absent_means") or ("default" if _is_note(parts[0]) else "unknown")}
    top = (note_table if _is_note(parts[0]) else key_table).get(parts[0]) or {}
    return {"path": "/" + "/".join(parts), "since": meta.get("since") or top.get("since") or "unknown",
            "absent_means": meta.get("absent_means") or "default"}


def fill_missing_keys(node: dict, template_node: dict, parts: list, added: list, conflicts: list, row_for) -> None:
    """Every template key `node` lacks, at any depth through OBJECTS; each filled key appends its
    `row_for(parts)` to `added`. Never into a template LIST (profiles[], environments[] hold the
    person's records), and never over an existing value: a scalar where the template has an object
    is an open question, appended to `conflicts` once per path."""
    for key, value in template_node.items():
        here = parts + [key]
        if key not in node:
            node[key] = copy.deepcopy(value)
            added.append(row_for(here))
        elif isinstance(value, dict) and not isinstance(node[key], dict):
            path = "/" + "/".join(here)
            if not any(c.get("path") == path for c in conflicts):
                conflicts.append({"path": path, "current": node[key],
                                  "question": f"Your configuration has {json.dumps(node[key], ensure_ascii=False)} "
                                              f"at {path}, but the factory keeps a group of named settings there. "
                                              "It does not replace what a person wrote: fix it by hand or move "
                                              "it aside, then plan again."})
        elif isinstance(value, dict):
            fill_missing_keys(node[key], value, here, added, conflicts, row_for)


def _project_facts(template: dict, table: dict) -> set:
    """The top-level template keys config-keys.json flags `project_fact: true` (OH3-31): what the
    project IS (its roots, its commands, its stands, its adapters), which no template default can
    know. The flag is read on top-level keys only."""
    key_table = table.get("keys") or {}
    return {key for key in template if isinstance((key_table.get(key) or {}), dict)
            and (key_table.get(key) or {}).get("project_fact") is True}


def not_filled(proposed, template: dict | None = None, keys: dict | None = None) -> list:
    """The project-fact keys (config-keys.json `project_fact`) a proposed configuration does not
    hold, in the template's order: facts that `fill_proposal` leaves for the person to name. A pure
    function of `proposed_config` and the template, so the proposal needs no field of its own for
    it (PROPOSAL_COVERS stays closed). Not a dict (no configuration) -> []."""
    if not isinstance(proposed, dict):
        return []
    tmpl = canonical_template() if template is None else template
    table = config_keys() if keys is None else keys
    facts = _project_facts(tmpl, table)
    return [key for key in tmpl if key in facts and key not in proposed]


def _refuse_foreign_rows(proposal: dict) -> None:
    """A role's proposal whose `conflicts` or `added` is not the migration plan's shape is refused with a sentence that names
    the field and what it must be (FR-1), before anything is read from it: it was a traceback (F-4). `conflicts` is a list of
    objects ({path, current, question}); `added` a list of objects with a text `path`. Absent / null / [] are fine."""
    conflicts = proposal.get("conflicts")
    if conflicts not in (None, []) and not (isinstance(conflicts, list) and all(isinstance(c, dict) for c in conflicts)):
        raise ValueError("the proposal's `conflicts` is not a list of objects ({path, current, question}): leave it out of "
                         "the proposal or make the proposal again from the migration plan")
    added = proposal.get("added")
    if added not in (None, []) and not (isinstance(added, list)
                                         and all(isinstance(r, dict) and isinstance(r.get("path"), str) for r in added)):
        raise ValueError("the proposal's `added` is not a list of objects with a text `path` ({path, since, absent_means}): "
                         "leave it out of the proposal or make the proposal again from the migration plan")


def fill_proposal(proposal: dict, template: dict | None = None, keys: dict | None = None) -> dict:
    """OH3-31: the template keys a role's proposal lacks get the template's value, so what the
    proposal writes is the shape a fresh install writes, and `proposal_hash` covers it (the keys
    are in `proposed_config` and their rows in `added`; the listing shows both). Mutates and returns
    `proposal`. Direction of error: not filling, and saying so.

    Not filled: a key flagged `project_fact` in config-keys.json (listed by `not_filled`, never
    written, and nothing under a project-fact key that is present is filled either); a key that is
    present with ANY value (`null`, "", [], a scalar - a scalar where the template has an object is
    a `conflicts` row, as in `migration_plan`); a proposal with no `proposed_config` object; the
    proposal of ONE test command (`command_kind`). Rows already in `added` are not repeated."""
    config = proposal.get("proposed_config") if isinstance(proposal, dict) else None
    if not isinstance(config, dict) or command_kind(proposal):
        return proposal
    tmpl = canonical_template() if template is None else template
    table = config_keys() if keys is None else keys
    facts = _project_facts(tmpl, table)
    # A fact that is present stays whole, but a scalar where the template has a group is still a conflict.
    fillable = {key: ({} if key in facts else value) for key, value in tmpl.items()
                if key not in facts or (key in config and isinstance(value, dict))}
    _refuse_foreign_rows(proposal)
    rows: list = []
    found = list(proposal.get("conflicts") or [])
    # Decision Q1 (OH3-31, by recommendation): a filled row is `absent_means: default`, not the table's
    # `required` - the person's "yes" to the listing is the answer, so `unanswered_pointers` does not read it
    # as an open question and a proposal that omits a non-fact key still installs (AR-3).
    fill_missing_keys(config, fillable, [], rows, found,
                      lambda parts: {**_added_row(parts, table), "absent_means": "default"})
    if rows:
        have = list(proposal.get("added") or [])
        known = {r.get("path") for r in have if isinstance(r, dict)}
        proposal["added"] = have + [r for r in rows if r["path"] not in known]
    if found:
        proposal["conflicts"] = found
    return proposal


def migration_plan(config: dict | None, price_table_answer: str | None = None, model_ids=(),
                   catalogue: dict | None = None, *, template: dict | None = None,
                   keys: dict | None = None, answers: dict | None = None,
                   root: Path | str | None = None) -> dict:
    """Read-only proposal - the ONE shape, whether the project has a config or not (G1).

    `config` None is the empty input (a fresh install): the same fields, `proposed_config` None
    - the role fills it from discovery, the code never invents a config. `template` (default:
    references/templates/config.json) and `keys` (default: references/config-keys.json) are
    injectable so a test can prove a rule on a table of its own.

    Returns {schema_version, input_hash, proposal_hash, proposed_config, conflicts[], changes[],
    removed[], renamed[], reasked[], answers_legacy{}, added[], kept[], reordered[],
    deprecated_keys[], evidence_refs[]}. `removed` rows are {path, was, reason}; `renamed`
    {from, to, value}; `reasked` {path, was, question} (the old value is NOT carried: the
    template default stands in until it is answered); `added` {path, since, absent_means} for
    every template key the old config lacked, at any depth through objects (a nested key carries
    its top-level key's `since`); `kept` {path, reason} for notes that are not template keys, for
    answers (`answered by the person` / `not asked: <pointer>`) and for a value that still held an
    old template's exact default and took the current one (`changed: default path renamed`, from
    config-keys.json `value_migrations`); `reordered` the JSON pointers of objects whose key order changed (values
    unchanged). `price_table_answer` (`builtin` or `own` + `model_ids`) carries the person's
    answer to the old-price-table question into `proposed_config`; without it the question
    stays a conflict and `apply_plan` refuses the proposal.

    `answers` (O2-5): {JSON pointer: value} the role collected from the person in one batched
    question, or a headless caller reads from a fixture. A key the plan had to invent that the
    config REQUIRES (an `added` row with absent_means `required`, except schema_version) and every
    `reasked` row stays open - and `apply_plan` refuses the proposal - until its pointer is
    answered; a key named in config-keys.json `asked_until_answered` (t-298: `environment.access`, whose
    template default is the empty "not recorded") joins the `reasked` rows while its proposed value still
    equals the template default, and its `added` row goes when it is answered; the answer is written into
    `proposed_config` and the row moves to `kept`. An answer
    for any other pointer is ignored and listed in `kept` as `not asked: <pointer>`. With no
    config (`config` None) there is nothing to ask and `answers` is not read.

    The memory (FR-7, t-232): when `root` names a project, the answers earlier approvals recorded
    (`record_approval` stores them) fill the open `required`/`reasked` rows - and only those rows,
    never another key - so a person who answered a question is not asked it again. The row moves
    to `kept` as `answered earlier, not asked again`. An answer is forgotten when the template
    default of its key changed since it was given: that is a new question. An explicit `answers`
    MERGES with the memory: per pointer the explicit value wins (its row says `answered by the
    person`), and the memory fills every other open row; `answers={}` therefore asks nothing the
    memory knows."""
    if price_table_answer is not None and price_table_answer not in PRICE_ANSWERS:
        raise ValueError(f"price table answer must be one of: {', '.join(PRICE_ANSWERS)}")
    if config is not None and not isinstance(config, dict):
        raise ValueError("config must be a JSON object, or None when the project has no config")
    tmpl = canonical_template() if template is None else template
    table = config_keys() if keys is None else keys
    changes: list[dict] = []
    conflicts: list[dict] = []
    removed: list[dict] = []
    renamed: list[dict] = []
    reasked: list[dict] = []
    added: list[dict] = []
    kept: list[dict] = []
    reordered: list[str] = []
    moved_legacy: dict = {}
    deprecated: list[str] = []

    def seal(proposed, evidence) -> dict:
        result = {"schema_version": 1, "input_hash": _json_hash(config), "changes": changes,
                  "conflicts": conflicts, "deprecated_keys": sorted(set(deprecated)),
                  "removed": removed, "renamed": renamed, "reasked": reasked, "added": added,
                  "kept": kept, "reordered": reordered, "answers_legacy": moved_legacy,
                  "evidence_refs": evidence, "proposed_config": proposed}
        result["proposal_hash"] = proposal_hash(result)
        return result

    if config is None:
        return seal(None, [])

    proposed = copy.deepcopy(config)
    price_conflict = price_table_conflict(config, catalogue)
    if price_conflict and price_table_answer:
        changes.extend(_apply_price_answer(proposed, price_table_answer, model_ids, catalogue))
    elif price_conflict:
        conflicts.append(price_conflict)
    external = proposed.get("external_writes")
    if isinstance(external, dict):
        legacy = external.get("commands")
        channels = external.setdefault("channels", {}) if isinstance(legacy, dict) else external.get("channels", {})
        if isinstance(legacy, dict) and isinstance(channels, dict):
            open_names = 0
            for name, command in legacy.items():
                wanted = {"method": "command", "command": command}
                current = channels.get(name)
                path = f"/external_writes/channels/{name}"
                if current is None:
                    channels[name] = wanted
                    changes.append({"path": path, "from": None, "to": wanted,
                                    "reason": "legacy command channel"})
                elif current != wanted:
                    open_names += 1
                    conflicts.append({"path": path, "legacy": wanted, "current": current,
                                      "question": "Which exact delivery definition should be retained?"})
            if not open_names:
                # Every command now lives in `channels`; the old map would be a second, stale
                # copy of the same delivery. With a conflict open it stays: it is the evidence.
                del external["commands"]
                removed.append({"path": "/external_writes/commands", "was": legacy,
                                "reason": "every command is now a channel under external_writes.channels"})
    impact = config.get("impact_scale")
    if isinstance(impact, dict):
        for name, value in impact.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                conflicts.append({"path": f"/impact_scale/{name}", "current": value,
                                  "question": "Choose priority and severity for this impact class; numeric multipliers have no safe translation."})
    # A schema other than this plugin's is named, never rewritten and never a crash. A MISSING
    # schema_version is a missing template key and is added below like any other.
    if "schema_version" in config:
        found = config["schema_version"]
        if not (isinstance(found, int) and not isinstance(found, bool) and found == SCHEMA_VERSION):
            conflicts.append({"path": "/schema_version", "current": found,
                              "question": f"This plugin writes schema_version {SCHEMA_VERSION}, and this "
                                          f"configuration says {json.dumps(found)}. A newer factory may "
                                          "have written it: update the plugin before onboarding. The "
                                          "factory does not rewrite a schema it does not know."})
    # Keys the factory dropped: gone from the proposal, each with the reason and the old value.
    for path, meta in (table.get("removed") or {}).items():
        if "." not in path and path in tmpl:
            continue  # the template carries it: not retired
        parent, last = _parent_of(proposed, path)
        if parent is not None and last in parent:
            removed.append({"path": _pointer(path), "was": parent.pop(last),
                            "reason": str((meta or {}).get("reason") or "no longer read by the factory")})
            deprecated.append(path)
    for old_path, new_path in (table.get("renamed") or {}).items():
        parent, last = _parent_of(proposed, old_path)
        if parent is None or last not in parent:
            continue
        target, target_last = _parent_of(proposed, new_path, create=False)
        if target is not None and target_last in target:
            conflicts.append({"path": _pointer(new_path), "legacy": parent[last], "current": target[target_last],
                              "question": f"`{old_path}` was renamed `{new_path}` and both are set: "
                                          "which value should be kept?"})
            continue
        target, target_last = _parent_of(proposed, new_path, create=True)
        if target is None:
            continue  # the new place sits under something that is not an object: left as it is
        target[target_last] = parent.pop(last)
        renamed.append({"from": _pointer(old_path), "to": _pointer(new_path), "value": target[target_last]})
    for path, meta in (table.get("reasked") or {}).items():
        parent, last = _parent_of(proposed, path)
        if parent is None or last not in parent:
            continue
        was = parent[last]
        default_parent, default_last = _parent_of(tmpl, path)
        has_default = default_parent is not None and default_last in default_parent
        if has_default and was == default_parent[default_last]:
            continue  # it already is the new default: nothing to ask, and a second plan asks nothing
        if has_default:
            parent[last] = copy.deepcopy(default_parent[default_last])
        else:
            del parent[last]
        reasked.append({"path": _pointer(path), "was": was,
                        "question": str((meta or {}).get("question") or f"What should {path} be now?")})
    # A key still holding the EXACT text an old template carried as its default gets the current
    # template's value (`journal_path`: state/ -> records/). The comparison goes through the ONE
    # path normaliser the writer uses (runtime_paths.normalise_project_path: `./`, backslashes,
    # blanks, a trailing slash; case KEPT), so a spelling the writer already resolves to the old
    # default is renamed here too, while a different path - another folder, another case, an
    # extension - is a person's own and is never touched (t-272 item 5).
    norm = _paths().normalise_project_path
    for path, meta in (table.get("value_migrations") or {}).items():
        parent, last = _parent_of(proposed, path)
        source, source_last = _parent_of(tmpl, path)
        old_default = (meta or {}).get("from_default")
        if parent is None or last not in parent or source is None or source_last not in source:
            continue
        if isinstance(old_default, str) and isinstance(parent[last], str) and norm(parent[last]) == norm(old_default) \
                and source[source_last] != old_default:
            changes.append({"path": _pointer(path), "from": parent[last], "to": source[source_last],
                            "reason": DEFAULT_RENAMED})
            kept.append({"path": _pointer(path), "reason": DEFAULT_RENAMED})
            parent[last] = copy.deepcopy(source[source_last])
    # A launch command naming a place on the machine that wrote it works nowhere else; the
    # probe is derived again on this machine (runtime_probe.py --suggest), so it is dropped.
    probes = (proposed.get("execution") or {}).get("runtime_probes") if isinstance(proposed.get("execution"), dict) else None
    if isinstance(probes, dict):
        for profile in list(probes):
            spec = probes[profile]
            # B-260 (first half, t-300 Q5): the container-aware judge of ONE probe entry (audit A20's own), not the
            # plain gate over the list. `--app-root /app` is a place INSIDE the stand's container, the same on every
            # machine; the plain gate read its leading slash as a place on the writing machine and dropped BOTH
            # probes of a project on every reinstall - and with no probe the build question has nothing to ask.
            if isinstance(spec, dict) and _probe_has_machine_local(spec):
                removed.append({"path": f"/execution/runtime_probes/{profile}", "was": probes.pop(profile),
                                "reason": "its launch command names a place on the machine that wrote it "
                                          "(an absolute path), so it works nowhere else; "
                                          "`runtime_probe.py --suggest` derives it again on this machine"})
    # A note is the factory's text. Its text of any known version is reset to the current one;
    # anything else is a person's answer: moved whole into answers_legacy, never overwritten.
    version = package_version()
    note_table = table.get("notes") or {}

    def settle_note(holder: dict, last: str, text: str, label: str, history) -> None:
        """One note, top-level or nested (O2-2, same C5 rule): `holder[last]` is the person's or
        the factory's; `label` is its dotted name (`environment.note`) - the key under which a
        person's text is kept in answers_legacy."""
        old, pointer = holder[last], _pointer(label)
        known = set(history or []) | {text}
        if isinstance(old, str) and old in known:
            if old != text:
                holder[last] = text
                changes.append({"path": pointer, "from": old, "to": text,
                                "reason": "an earlier text of the factory's own note, replaced by the current one"})
            return
        if old is None or (isinstance(old, str) and not old.strip()):
            holder[last] = text
            changes.append({"path": pointer, "from": old, "to": text,
                            "reason": "an empty note, replaced by the factory's text"})
            return
        legacy_store = proposed.setdefault("answers_legacy", {})
        if not isinstance(legacy_store, dict):
            conflicts.append({"path": "/answers_legacy", "current": legacy_store,
                              "question": "answers_legacy must be an object: it keeps the text a person "
                                          f"wrote in {label}. Fix it or move it aside."})
            return
        slot = _legacy_slot(legacy_store, label, old, version)
        if slot is not None:
            legacy_store[slot] = old
            moved_legacy[slot] = old
        holder[last] = text
        changes.append({"path": pointer, "from": old, "to": text,
                        "reason": "a person's text: kept whole under answers_legacy"
                        + (f".{slot}" if slot is not None else " (already kept there)")
                        + ", the note is the factory's text again"})

    for key in [k for k in proposed if k.endswith("_note")]:
        if key not in tmpl:
            kept.append({"path": f"/{key}", "reason": "kept: not a template key"})
            continue
        settle_note(proposed, key, tmpl[key], key, (note_table.get(key) or {}).get("note_history"))
    # Notes nested in template objects (environment.note, cost.note): the table names them by
    # their dotted path. An absent note or an absent parent object is the fill's business below.
    for dotted, meta in note_table.items():
        if "." not in dotted:
            continue
        holder, last = _parent_of(proposed, dotted)
        source, source_last = _parent_of(tmpl, dotted)
        if holder is None or last not in holder or source is None or not isinstance(source.get(source_last), str):
            continue
        settle_note(holder, last, source[source_last], dotted, (meta or {}).get("note_history"))
    # The shape a fresh install would write: the order first (a change of order is shown, values
    # unchanged), then every template key the config lacks, in its canonical place.
    proposed = _canonical_order(proposed, tmpl, "/", reordered)

    def row_for(parts: list) -> dict:
        return _added_row(parts, table)

    fill_missing_keys(proposed, tmpl, [], added, conflicts, row_for)
    proposed = _canonical_order(proposed, tmpl, "/", [])
    # Answers (O2-5): the person's words for what the plan could only default. A key the plan had
    # to invent (a required key the config lacked) or a key whose meaning changed (reasked) is
    # open until answered; apply refuses a proposal that still lists one. An answer moves its row
    # to `kept`; answered means "the pointer is in `answers`" - a value equal to the template
    # default is still an answer. An answer for a pointer nobody asked is ignored and listed.
    if answers is not None and not isinstance(answers, dict):
        raise ValueError("answers must be a JSON object mapping a JSON pointer (like /dod) to the person's answer")
    # The memory FILLS what the caller did not answer; it never overrides what the caller gave: an
    # explicit partial `answers` wins per pointer and the earlier answers fill the rest (a headless
    # caller that answers one new question must not bring the ones already answered back).
    remembered = remembered_answers(root, tmpl) if root is not None else {}
    explicit = dict(answers) if answers is not None else {}
    given = {**remembered, **explicit}
    used: set = set()

    def settle(rows: list, open_row) -> None:
        for row in [r for r in rows if open_row(r) and r["path"] in given]:
            if _set_pointer(proposed, row["path"], copy.deepcopy(given[row["path"]])):
                rows.remove(row)
                kept.append({"path": row["path"], "reason": "answered by the person" if row["path"] in explicit
                             else f"{ANSWERED_PREFIX} earlier, not asked again"})
                used.add(row["path"])

    settle(added, lambda r: r.get("absent_means") == "required" and r["path"] != "/schema_version")
    # Keys asked until answered (config-keys.json `asked_until_answered`, t-298): a key whose template
    # default is EMPTY ("not recorded") has no earlier value for "keep everything as before" to keep, so a
    # proposed value that still equals the template default is asked as a `reasked` row - whether the key was
    # absent (the fill put the default in) or the config already holds the default (a project reinstalled
    # once without answering). POSITION, and the invariant it keeps: after `settle(added, required)` - an
    # answer given at an ANCESTOR pointer (a whole /environment) has been written by then, and is honoured
    # before the check - and before `settle(reasked)`, which closes the new row with an explicit or a
    # remembered answer, so a person's word (even "not now": the default given explicitly) is never asked
    # twice. A key whose value a person set (anything but the default) never gets a row, and a key the table
    # names that the template lacks, or that sits inside a list, is skipped without a word.
    for dotted, meta in (table.get("asked_until_answered") or {}).items():
        if not isinstance(dotted, str) or not dotted:
            continue
        template_parent, template_last = _parent_of(tmpl, dotted)
        proposed_parent, proposed_last = _parent_of(proposed, dotted)
        if template_parent is None or template_last not in template_parent \
                or proposed_parent is None or proposed_last not in proposed_parent:
            continue
        if proposed_parent[proposed_last] != template_parent[template_last] or any(r.get("path") == _pointer(dotted) for r in reasked):
            continue
        old_parent, old_last = _parent_of(config, dotted)
        reasked.append({"path": _pointer(dotted),
                        "was": copy.deepcopy(old_parent[old_last]) if old_parent is not None and old_last in old_parent else None,
                        "question": str((meta.get("question") if isinstance(meta, dict) else None) or f"What should {dotted} be?")})
    settle(reasked, lambda r: True)
    # The listing says "the values a fresh install writes" for an `added` row (FR-10): a key the person has
    # just answered is not one of those, so its `added` row goes when the question closes.
    answered_asked = {_pointer(d) for d in (table.get("asked_until_answered") or {}) if isinstance(d, str)} & used
    added[:] = [r for r in added if r.get("path") not in answered_asked]
    for pointer in (answers or {}):     # only what a caller GAVE can be "not asked"; the memory is silent
        if pointer not in used:
            kept.append({"path": pointer, "reason": f"not asked: {pointer}"})
    proposed = _canonical_order(proposed, tmpl, "/", [])
    return seal(proposed, ["qa-factory/config.json"])


def is_approved(root: Path, proposal: dict, extra: dict | None = None) -> bool:
    """Is THIS proposal already approved (FR-7: a boundary answered is not asked again)? True only
    when the proposal's `proposal_hash` is the true hash of its own content AND a recorded,
    approved onboarding approval carries that same hash. The `input_hash` never counts by
    itself: the same input can produce a different proposal (a newer plugin, another answer),
    and a different input can produce the very proposal that was approved (C2). An approvals log
    that cannot be read line by line proves nothing for the lines it cannot read - the answer
    for those is no, and the question is asked again (a question too many, never a silent pass)."""
    if not isinstance(proposal, dict):
        return False
    sealed = proposal.get("proposal_hash")
    if not isinstance(sealed, str) or not sealed or sealed != proposal_hash(proposal, extra):
        return False
    path = approvals_path(root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("status") == "approved" \
                and record.get("proposal_hash") == sealed:
            return True
    return False


def _approval_record(root: Path, approval_ref: str, proposal: dict) -> dict:
    path = approvals_path(root)
    if not path.exists():
        raise ValueError("recorded onboarding approval was not found")
    matches = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid onboarding approval record at line {number}") from exc
        if record.get("approval_ref") == approval_ref:
            matches.append(record)
    if len(matches) != 1:
        raise ValueError("approval-ref must resolve to exactly one onboarding approval")
    record = matches[0]
    # The approval is of the proposal's content (`proposal_hash`), never of its input alone (C2).
    if record.get("status") != "approved" or record.get("proposal_hash") != proposal.get("proposal_hash"):
        raise ValueError("onboarding approval does not authorize this exact proposal")
    return record


def _check_sealed(proposal: dict, extra: dict | None) -> None:
    if proposal.get("proposal_hash") != proposal_hash(proposal, extra):
        raise ValueError("proposal hash is invalid")


def _need_proposed_config(proposal: dict) -> None:
    if not isinstance(proposal.get("proposed_config"), dict):
        raise ValueError("the proposal has no proposed_config yet: for a project with no configuration "
                         "the role writes it from discovery first, then the proposal is sealed with "
                         "proposal_hash and shown for approval")


def record_approval(root: Path, proposal: dict, approval_ref: str,
                    evidence_ref: str, extra: dict | None = None) -> Path:
    """Persist explicit onboarding approval bound to this exact proposal. A project with no
    config.json is the empty input: its proposal carries the hash of nothing as `input_hash`."""
    if not approval_ref.strip() or not evidence_ref.strip():
        raise ValueError("approval-ref and evidence-ref are required")
    _check_sealed(proposal, extra)
    _need_proposed_config(proposal)
    kind = command_kind(proposal)
    if kind and any(str(word).strip().lower().startswith("headless:") for word in (approval_ref, evidence_ref)):
        # B-220 F9: a changed test command is the person's decision and nobody else's. `onboard_apply --apply` with no
        # --approval-ref records the COMMAND LINE as the word (a headless entry); for any other proposal that is the
        # documented way, for this one it would let a script approve what a person never saw.
        raise ValueError("this proposal changes a test command, and only a person's word approves that: a headless "
                         "approval (an --approval-ref or --evidence-ref that starts with `headless:`) is refused. Show the "
                         "person the sentence (`onboarding_probe.py --question <the sealed file>`), and record their "
                         "yes with the approval ref the proposal names and the transcript line as the evidence")
    current = read_config_file(root)
    if proposal.get("input_hash") != _json_hash(current):
        raise ValueError(STALE_COMMAND_DOOR if kind else "proposal is stale")
    path = approvals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    records = [json.loads(line) for line in existing if line.strip()]
    matches = [record for record in records if record.get("approval_ref") == approval_ref]
    record = {"schema_version": 1, "approval_ref": approval_ref, "status": "approved",
              "input_hash": proposal["input_hash"], "proposal_hash": proposal["proposal_hash"],
              "evidence_ref": evidence_ref,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    if kind:
        record["kind"] = kind       # what was approved, for the audit of approvals B-294 (c) queues
    # The person's answers travel with the approval (FR-7): the next plan reads them back instead
    # of asking the same question again. `answer_defaults` is the template default each answer
    # was given against; an answer outlives its question only while that default stands.
    answers, defaults = _answers_of(proposal, canonical_template())
    if answers:
        record["answers"], record["answer_defaults"] = answers, defaults
    if matches:
        stable = ("schema_version", "approval_ref", "status", "input_hash", "proposal_hash", "evidence_ref")
        if len(matches) == 1 and all(matches[0].get(key) == record.get(key) for key in stable):
            return path
        raise ValueError("approval-ref already exists with different evidence")
    content = "\n".join(existing + [json.dumps(record, ensure_ascii=False)]) + "\n"
    _replace_bytes(path, content.encode("utf-8"))
    return path


def record_fold(root: Path, proposal: dict, approval_ref: str, evidence_ref: str = "") -> Path:
    """Record that the old product passport was folded into the project profile, FOR this approval:
    one line `{"fold": FOLD_TOKEN, "for_approval": <ref>}` in the approvals log. The line names the
    approval by `for_approval`, never by `approval_ref` (the log resolves a ref to exactly one
    line), and `onboard_apply.fold_receipt` reads it before the final half lets the passport go.
    Refused - nothing written - when no approval of THIS proposal is on record under that ref, and
    when this approval already has its fold line (once per approval: a second receipt would say
    nothing the first does not, and the retirement must rest on one, FR-7)."""
    if not approval_ref.strip():
        raise ValueError("approval-ref is required: the fold is recorded for the approval the person gave")
    try:
        _approval_record(root, approval_ref, proposal)
    except ValueError as exc:
        raise ValueError(f"{exc}; the fold is recorded for an approval that is on record for this exact proposal: give the "
                         "sealed proposal onboard_apply made and the --approval-ref it was approved under") from exc
    path = approvals_path(root)
    existing = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(existing, 1):
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("fold") == FOLD_TOKEN and record.get("for_approval") == approval_ref:
            raise ValueError(f"already folded for this approval ({approval_ref}: line {number} of {path.name} is its fold receipt); "
                             "nothing was written. The receipt is recorded once per approval - the final apply half "
                             "retires the old passport on it")
    record = {"schema_version": 1, "fold": FOLD_TOKEN, "for_approval": approval_ref,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    if evidence_ref.strip():
        record["evidence_ref"] = evidence_ref
    content = "\n".join(existing + [json.dumps(record, ensure_ascii=False)]) + "\n"
    _replace_bytes(path, content.encode("utf-8"))
    return path


def unanswered_pointers(proposal: dict) -> list:
    """The JSON pointers a proposal still waits on: every `added` row that is `required` (except
    schema_version, which the plan fills itself) and every `reasked` row. Listed once each, in
    the order the proposal names them."""
    rows = [r for r in (proposal.get("added") or [])
            if isinstance(r, dict) and r.get("absent_means") == "required" and r.get("path") != "/schema_version"]
    rows += [r for r in (proposal.get("reasked") or []) if isinstance(r, dict)]
    return list(dict.fromkeys(str(r.get("path")) for r in rows))


def apply_plan(root: Path, proposal: dict, approval_ref: str, extra: dict | None = None) -> Path | None:
    """Write the approved proposal as qa-factory/config.json, in the template's key order (O2-3:
    whoever filled the proposal, a fresh install and a reinstall write the same bytes). Returns
    the backup of the config it replaced, or None when there was none to back up (O2-4: a fresh
    install leaves no backup file and no config-migrations directory)."""
    if not approval_ref.strip():
        raise ValueError("approval-ref is required")
    _check_sealed(proposal, extra)
    _approval_record(root, approval_ref, proposal)
    current = read_config_file(root)  # None: a fresh install writes the first config
    if proposal.get("input_hash") != _json_hash(current):
        raise ValueError(STALE_COMMAND_DOOR if command_kind(proposal) else "proposal input hash does not match current config")
    if proposal.get("conflicts"):
        raise ValueError("proposal has unresolved conflicts")
    waiting = unanswered_pointers(proposal)
    if waiting:
        # FR-41/P20: a value the plan invented is not the person's answer. One batched list, in
        # the person's terms; no config is written, no backup, nothing half-applied.
        raise ValueError("the factory needs these answers before it writes the config: "
                         + ", ".join(waiting) + ". Ask the person once for all of them, then make the "
                         "proposal again with their answers.")
    _need_proposed_config(proposal)
    proposed = proposal.get("proposed_config")
    errors = validate(proposed)
    if errors:
        raise ValueError("proposed config is invalid: " + "; ".join(errors)
                         + ". Nothing was written. Correct the answer that caused it (an answer is the whole value at its pointer), make the "
                           "proposal again and ask the person's \"yes\" for the corrected summary")
    return _write_config(root, current, proposed, proposal["input_hash"], approval_ref)


def _write_config(root: Path, current, proposed: dict, input_hash: str, approval_ref: str) -> Path | None:
    """The ONE writer of `qa-factory/config.json` (FR-17; `apply_plan` and `apply_adaptation` both end here): `proposed` in the template's
    key order, the config it replaces backed up under `config-migrations/<input_hash>.json` (the backup's `approval_ref` is the ref that
    authorized the write - a person's approval, or `RA-<n>` for a report adaptation), the file replaced atomically. Returns the backup, or
    None when there was nothing to back up (O2-4: a fresh install leaves no backup file and no config-migrations directory)."""
    config_path = root / "qa-factory" / "config.json"
    proposed = _canonical_order(proposed, canonical_template(), "/", [])
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if current is not None:
        migration_dir = _paths().record(root, MIGRATIONS_NAME)
        migration_dir.mkdir(parents=True, exist_ok=True)
        backup = migration_dir / f"{input_hash}.json"
        if not backup.exists():
            _replace_bytes(backup, (json.dumps({"schema_version": 1, "approval_ref": approval_ref,
                                                "config": current}, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    _replace_bytes(config_path, (json.dumps(proposed, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return backup


def _replace_bytes(path, data: bytes) -> None:
    """THE atomic byte writer of this module (AR-14): a temp file in the target's folder, flushed and fsynced, then `os.replace`d over
    the target, so a reader sees the old bytes or the new ones and never half of them. `_write_config` (the config and its backup),
    `record_approval` and `record_fold` (the approvals log) and `restore_config` (the config, its pre-revert copy and the story's
    snapshot) all end here; a second writer of these files would be a second way to lose half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        if os.path.exists(raw): os.unlink(raw)


# --- HF5-6: the story's copy of config.json at its start, and the revert after S9 --------------------------------------
#
# On TP1-12586 the run changed the stand's `qa-factory/config.json` by hand (the account keys, a flat `frontend_url`) and
# nothing took it back. A story that STARTS FRESH keeps the bytes it found (`snapshot_config`); when the story ends, `restore_config`
# gives the file back, EXCEPT what a recorded writer wrote in the story's window (an onboarding approval, a report adaptation, the
# runtime probe's `--suggest --write`): that is the project's own, and it stays. Nothing here decides for the person: a copy that was
# not kept, another story in flight, a copy that cannot be read are each a refusal that says so (`not_kept_copy` / `skipped`),
# never "unchanged" (AR-28). The pre-revert file is kept machine-locally (`qa-factory/state/config-reverts/`), so the person can apply
# any change again from it.
SNAPSHOT_NAME = "config-at-start.json"      # in <story>/state/
REVERTS_NAME = "config-reverts"             # in qa-factory/state/ (machine-local, ignored by git)
NOT_KEPT_WHY = "the story started before the factory kept a copy"
SUGGEST_SOURCE = "runtime_probe --suggest --write"
_SHOWN_POINTERS = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sibling(name: str):
    """A sibling script module, imported where it is used: this module is also imported by tests and tools that put `scripts/` on the
    path themselves (the same reason as `_paths`)."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    return __import__(name)


def _moment(value) -> float | None:
    """An ISO time as epoch seconds (no zone = UTC), None when it is not one: `contract._answer_moment`, the package's one reading of
    an answer's time, with its "oldest moment there is" turned into None."""
    moment = _sibling("contract")._answer_moment(value)
    return None if moment == float("-inf") else moment


def _snapshot_file(task_root) -> Path:
    return Path(task_root) / "state" / SNAPSHOT_NAME


def _read_object(path: Path) -> tuple:
    """`(dict, "")`, or `(None, "absent")`, or `(None, <why it cannot be read>)`: `hooklib.read_json`, the package's one JSON reader."""
    if not Path(path).exists():
        return None, "absent"
    data = _sibling("hooklib").read_json(path, kind=dict)
    return (data, "") if data is not None else (None, "it is not readable JSON or not a JSON object")


def _parse_config(raw: bytes):
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def snapshot_config(root, task_root, fresh: bool, why: str = "") -> dict:
    """Keep the bytes of `qa-factory/config.json` as a story STARTS (B4): `<task_root>/state/config-at-start.json` =
    `{"bytes_b64", "sha256", "taken_at"}`, or `{"absent": true, "taken_at"}` when there was no file. Only when `fresh` (the caller
    saw no recorded stage and no dispatch); a story that is not fresh (a resume, a story begun before the factory kept copies) gets
    `{"not_kept_copy": <why>}` instead - its middle is never taken for its base. A copy that is already there is never touched (the S0
    stops re-enter the start). Returns `{"state": kept|exists|not_kept_copy, "why", "taken_at", "notes"}`; `notes` name a
    story that kept a copy and did not end while the file differs from it."""
    root, path = Path(root), _snapshot_file(task_root)
    if path.exists():
        held, _ = _read_object(path)
        return {"state": "exists", "why": "", "taken_at": str((held or {}).get("taken_at") or ""), "notes": []}
    if not fresh:
        reason = f"{NOT_KEPT_WHY} ({why or 'it had recorded work when the factory first looked'})"
        _replace_bytes(path, (json.dumps({"not_kept_copy": reason}, indent=2) + "\n").encode("utf-8"))
        return {"state": "not_kept_copy", "why": reason, "taken_at": "", "notes": []}
    taken = _now_iso()
    try:
        raw = _config_file(root).read_bytes()
        body = {"bytes_b64": base64.b64encode(raw).decode("ascii"), "sha256": hashlib.sha256(raw).hexdigest(), "taken_at": taken}
        sha = body["sha256"]
    except FileNotFoundError:
        body, sha = {"absent": True, "taken_at": taken}, ""
    except OSError as exc:
        reason = f"{NOT_KEPT_WHY} (config.json could not be read: {type(exc).__name__})"
        _replace_bytes(path, (json.dumps({"not_kept_copy": reason}, indent=2) + "\n").encode("utf-8"))
        return {"state": "not_kept_copy", "why": reason, "taken_at": "", "notes": []}
    _replace_bytes(path, (json.dumps(body, indent=2) + "\n").encode("utf-8"))
    return {"state": "kept", "why": "", "taken_at": taken, "notes": _unended_copy_notes(path.parent.parent, sha)}


def _config_file(root) -> Path:
    return Path(root) / "qa-factory" / "config.json"


def _unended_copy_notes(own: Path, sha: str) -> list:
    """The stories of this project that kept a copy at their start, never restored it, and whose copy is not the file now (a killed
    story: no `stop`, no S9). A note, nothing more: whether the difference is the person's is theirs to say."""
    notes = []
    for other in siblings(own):
        held, _ = _read_object(_snapshot_file(other))
        if held and "sha256" in held and "restored_at" not in held and held.get("sha256") != sha:
            notes.append(f"config.json differs from the copy {other.name} kept at its start, and {other.name} did not end")
    return notes


def siblings(own: Path) -> list:
    """The other story folders beside `own` (this story and `_archive` / `archive` are never among them); `[]` when the parent cannot be listed."""
    try:
        folders = sorted(p for p in Path(own).parent.iterdir() if p.is_dir())
    except OSError:
        return []
    mine = Path(own).resolve()
    return [p for p in folders if p.resolve() != mine and p.name not in ("_archive", "archive")]


def _esc(part) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _same_json(a, b) -> bool:
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def _leaf_diff(a, b, pointer: str = "") -> list:
    """The JSON pointers where `a` and `b` differ, as deep as the objects agree (by key); a list is a leaf, so a changed list is ONE
    pointer and is put back or kept whole (`_pointer_get` / `_set_pointer` read objects only)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in list(a) + [k for k in b if k not in a]:
            if key in a and key in b:
                out += _leaf_diff(a[key], b[key], f"{pointer}/{_esc(key)}")
            else:
                out.append(f"{pointer}/{_esc(key)}")
        return out
    return [] if _same_json(a, b) else [pointer or "/"]


def _migration_config(root, input_hash) -> dict | None:
    """The config a write replaced: `config-migrations/<input_hash>.json` -> `config` (a dict), None when there is none."""
    held, _ = _read_object(_paths().record(Path(root), MIGRATIONS_NAME) / f"{input_hash}.json")
    config = (held or {}).get("config")
    return config if isinstance(config, dict) else None


def _adaptation_before(root, ref: str) -> dict | None:
    """The config the report adaptation `RA-n` replaced: the backup that carries that ref (the adaptation's own record has no hash)."""
    folder = _paths().record(Path(root), MIGRATIONS_NAME)
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return None
    for file in files:
        held, _ = _read_object(file)
        if held and held.get("approval_ref") == ref and isinstance(held.get("config"), dict):
            return held["config"]
    return None


def recorded_writes(root, since) -> list:
    """The config writes a RECORDED writer made from `since` on (N10): `[{"ref", "at", "source", "before"}]` oldest first, `before`
    being the config as it was just before that write (its backup under `config-migrations/`, or the `before` of a project decision's
    receipt, HF8-9). The window is the record's own time (the approval's `recorded_at`, the adaptation's `at`, the receipt's
    `recorded_at`), never a backup's mtime. A record whose backup is not there is left out
    (its pointers are then not kept: the safe side for a file the person has a copy of). The runtime probe's `--suggest --write`
    leaves no record at all; `restore_config` knows it by its entry's note."""
    start = _moment(since)
    if start is None:
        return []
    out = []
    try:
        lines = approvals_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("fold") or record.get("status") != "approved":
            continue
        at, before = _moment(record.get("recorded_at")), _migration_config(root, record.get("input_hash"))
        if at is not None and at >= start and before is not None and record.get("approval_ref"):
            out.append({"ref": str(record["approval_ref"]), "at": at, "source": "onboarding approval", "before": before})
    try:
        import report_adapt
        rows, _ = report_adapt.load(root)
    except Exception:
        rows = []
    for row in rows:
        at, ref = _moment(row.get("at")), str(row.get("id") or "")
        before = _adaptation_before(root, ref) if ref and row.get("kind") == "reporter_kind" else None
        if at is not None and at >= start and before is not None:
            out.append({"ref": ref, "at": at, "source": "report adaptation", "before": before})
    for write in _decision_writes(root):
        if write["at"] >= start:
            out.append(write)
    return sorted(out, key=lambda w: (w["at"], w["ref"]))


DECISIONS_SOURCE = "project decision"


def _decision_writes(root) -> list:
    """The config writes `project_decisions.resolve` made (HF8-9): a receipt `qa-factory/state/decision-transactions/DD-n.json` that is
    `complete` and carries the `recorded_at` of the write and the config as it was `before` it. Every `resolve` that wrote a pointer
    is one - the account of a stand (`stand-account`), the address of its UI (`stand-frontend`), a deferred decision answered at a gate:
    a story's recorded answer to the project's own question is the project's, so the revert keeps it (a hand edit of the same pointer
    in the same window is kept with it: the safe side, as everywhere here). A receipt without those fields (written before this
    version, or one that wrote no pointer) is left out: its pointers are then not kept."""
    folder = Path(root) / "qa-factory" / "state" / "decision-transactions"
    try:
        files = sorted(folder.glob("DD-*.json"))
    except OSError:
        return []
    out = []
    for file in files:
        held, _ = _read_object(file)
        if not held or held.get("status") != "complete" or not isinstance(held.get("before"), dict):
            continue
        at = _moment(held.get("recorded_at"))
        if at is not None:
            out.append({"ref": str(held.get("decision_id") or file.stem), "at": at, "source": DECISIONS_SOURCE, "before": held["before"]})
    return out


def _suggest_note() -> str:
    try:
        import runtime_probe
        return str(runtime_probe.SUGGEST_NOTE)
    except Exception:
        return ""


def _kept_pointers(root, since, snapshot: dict, current: dict) -> dict:
    """`{pointer: source}` of what the story's recorded writers changed and is still different from the copy: for write i, the
    pointers where its `before` and the state right after it differ (the next write's `before`, for the last one the file now);
    plus each `execution.runtime_probes.<profile>` entry whose note is `runtime_probe.SUGGEST_NOTE`. A hand edit that lands between
    two writes is among the kept ones (the safe side; the report line says what was kept and by whom)."""
    found = {}
    writes = recorded_writes(root, since)
    for index, write in enumerate(writes):
        after = writes[index + 1]["before"] if index + 1 < len(writes) else current
        for pointer in _leaf_diff(write["before"], after):
            found.setdefault(pointer, write["source"])
    note, probes = _suggest_note(), (current.get("execution") or {}).get("runtime_probes") if isinstance(current.get("execution"), dict) else None
    if note and isinstance(probes, dict):
        for profile, spec in probes.items():
            if isinstance(spec, dict) and spec.get("note") == note:
                found.setdefault(f"/execution/runtime_probes/{_esc(profile)}", SUGGEST_SOURCE)
    differing = {p: s for p, s in found.items() if not _same_json(_pointer_get(snapshot, p), _pointer_get(current, p))}
    return {p: s for p, s in differing.items() if not any(q != p and p.startswith(q + "/") for q in differing)}


def _activity(story: Path):
    """`(in_flight, last activity as epoch seconds | None, why-unknown)` of another story folder, or None when it is no story."""
    pipeline, problem = _read_object(story / "pipeline.json")
    held, _ = _read_object(_snapshot_file(story))
    began = _moment((held or {}).get("taken_at")) if held else None
    if pipeline is None and problem != "absent":
        return True, began, f"{story.name}/pipeline.json cannot be read ({problem})"
    if pipeline is None:
        if held and "sha256" in held or held and held.get("absent"):
            return ("restored_at" not in held), began, ""
        return None
    stamp = _sibling("archive_task").last_activity(pipeline)
    seen = max([x for x in (stamp.timestamp() if stamp else None, began) if x is not None], default=None)
    stages = pipeline.get("stages")
    retro_stage = stages.get("S9") if isinstance(stages, dict) else None
    retro = retro_stage.get("status") if isinstance(retro_stage, dict) else None
    finished = bool(pipeline.get("archived")) or (bool(_sibling("hooklib").story_closed(pipeline)) and retro in ("done", "skipped", "completed"))
    return (not finished), seen, ""


def _activity_of(story: Path):
    """`_activity`, but a sibling whose state cannot be read at all (a shape nobody expected) is IN FLIGHT with the reason, never an
    exception and never "not a story": an unknown is not a pass (AR-28), and the revert stays a named skip."""
    try:
        return _activity(story)
    except Exception as exc:
        return True, None, f"{story.name} cannot be read ({type(exc).__name__})"


def _other_story_problem(task_root, since: float) -> str:
    """"" when no other story of the project is in flight or ran inside this one's window (B5); else the sentence that says so. The
    in-flight check comes first and is on the story's own state (not only an open dispatch); a story whose last activity is not before
    `since` ran inside the window, and what it changed is not this story's to give back."""
    for story in siblings(task_root):
        verdict = _activity_of(story)
        if verdict is None:
            continue
        in_flight, seen, unknown = verdict
        if in_flight:
            return (f"another story of this project is still in flight ({story.name}"
                    + (f": {unknown}" if unknown else "") + "), and a revert now could undo or restore its changes; config.json was left as it is. "
                    f"If {story.name} is abandoned, archive it (archive_task.py) so the next story's revert is not held back by it")
    for story in siblings(task_root):
        verdict = _activity_of(story)
        if verdict is not None and verdict[1] is not None and verdict[1] >= since:
            return f"another story ran inside this one's window ({story.name}), so its changes to config.json cannot be told from this one's"
    return ""


def _result(state: str, reverted=(), kept=(), backup: str = "", why: str = "") -> dict:
    return {"state": state, "reverted": list(reverted), "kept": list(kept), "backup": backup, "why": why}


def restore_config(root, task_root) -> dict:
    """Give back `qa-factory/config.json` as the story found it, except what a recorded writer wrote in the window. Returns
    `{"state", "reverted", "kept", "backup", "why"}`; `state` is one of `reverted`, `unchanged`, `already_restored`, `not_kept_copy`
    (no copy was kept: the story started before the factory kept one), `skipped` (`why` says what stopped it; the file is not
    touched). The direction of error is one: not reverting, and saying why. Never raises - it catches `Exception` on purpose (P1): a
    story is not stopped by its config revert, whatever shape a sibling story's state has. The file before the revert is kept at
    `backup` (machine-local, `qa-factory/state/config-reverts/`). The story's copy is marked ended with the outcome when the revert
    is done AND when it is held back for a reason that passes (another story in flight or in the window, a config that appeared):
    a second call on a finished story reverts nothing, so an edit made after the story ended is never taken for the story's."""
    try:
        return _restore(Path(root), Path(task_root))
    except Exception as exc:
        return _result("skipped", why=f"the revert did not finish ({type(exc).__name__}: {str(exc)[:200]}); check config.json")


def _already(held: dict) -> dict:
    outcome = held.get("outcome") if isinstance(held.get("outcome"), dict) else {}
    if outcome.get("state") == "skipped":
        return _result("already_restored", why=f"config.json was not given back when this story ended: {outcome.get('why')}")
    return _result("already_restored", why="config.json was already given back when this story ended")


def _restore(root: Path, task_root: Path) -> dict:
    path = _snapshot_file(task_root)
    held, problem = _read_object(path)
    if held is None:
        if problem == "absent":
            return _result("not_kept_copy", why=NOT_KEPT_WHY)
        return _result("skipped", why=f"the copy of config.json kept at the start of this story cannot be read ({problem})")
    if "not_kept_copy" in held:
        return _result("not_kept_copy", why=str(held["not_kept_copy"]))
    if "restored_at" in held:
        return _already(held)
    since = _moment(held.get("taken_at"))
    if since is None:
        return _result("skipped", why="the copy of config.json kept at the start of this story has no readable time")
    other = _other_story_problem(task_root, since)
    if other:
        return _mark_restored(path, held, _result("skipped", why=other))
    target = _config_file(root)
    try:
        now = target.read_bytes()
    except FileNotFoundError:
        now = None
    if held.get("absent"):
        if now is None:
            return _mark_restored(path, held, _result("unchanged"))
        return _mark_restored(path, held, _result(
            "skipped", why="there was no config.json when the story started and one is there now; a project's config is never deleted"))
    try:
        start = base64.b64decode(str(held.get("bytes_b64") or ""), validate=True)
    except ValueError:
        start = b""
    if not start or hashlib.sha256(start).hexdigest() != held.get("sha256"):
        return _result("skipped", why="the copy of config.json kept at the start of this story is damaged (its checksum does not match)")
    if now == start:
        return _mark_restored(path, held, _result("unchanged"))
    begin, current = _parse_config(start), (_parse_config(now) if now is not None else None)
    kept, why, final = {}, "", start
    if now is None:
        why = "config.json was deleted during the story; the copy was put back"
    elif begin is None or current is None:
        why = "config.json is not valid JSON now, so its changes cannot be read one by one; the copy was put back whole"
    else:
        kept = _kept_pointers(root, held.get("taken_at"), begin, current)
        if kept:
            final = _merge_kept(begin, current, kept)
            if _parse_config(final) == current:
                return _mark_restored(path, held, _result("unchanged", kept=list(kept)))
    reverted = ["/"] if (begin is None or current is None) else _leaf_diff(current, _parse_config(final))
    backup = ""
    if now is not None:
        pre_revert = _paths().state_file(root, REVERTS_NAME, f"{task_root.name}-{hashlib.sha256(now).hexdigest()[:8]}.json")
        _replace_bytes(pre_revert, now)
        backup = _display(root, pre_revert)
    _replace_bytes(target, final)
    result = _result("reverted", reverted=reverted, kept=list(kept), backup=backup, why=why)
    result["kept_sources"] = sorted(set(kept.values()))
    return _mark_restored(path, held, result)


def _merge_kept(begin: dict, current: dict, kept: dict) -> bytes:
    """The copy with the kept pointers put in from the file now (a pointer the file no longer has is taken out): the bytes to write."""
    merged = copy.deepcopy(begin)
    for pointer in sorted(kept, key=len):
        found, value = _pointer_get(current, pointer)
        _set_pointer(merged, pointer, value, drop=not found)
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _display(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _mark_restored(path: Path, held: dict, result: dict) -> dict:
    """The story ended: mark its copy with the time and the OUTCOME (the result and its report line). One-shot: a later call finds the
    mark and reverts nothing. The outcome is the producer of the report's revert line (`stored_revert_line`, AR-22)."""
    marked = dict(held, restored_at=_now_iso(), outcome=dict(result, line=revert_line(result)))
    _replace_bytes(path, (json.dumps(marked, indent=2) + "\n").encode("utf-8"))
    return result


def stored_revert_line(task_root) -> str:
    """The report line a finished story's revert left in its copy (`outcome.line`); "" when the story has not ended, kept no copy, or
    the revert had nothing to say. Reads, writes nothing."""
    held, _ = _read_object(_snapshot_file(task_root))
    outcome = (held or {}).get("outcome")
    return str(outcome.get("line") or "") if isinstance(outcome, dict) else ""


def revert_line(result: dict) -> str:
    """The one report line for a `restore_config` result; "" when there is nothing to say (`unchanged`, `already_restored`)."""
    state = result.get("state")
    if state in ("not_kept_copy", "skipped"):
        return f"config.json: not reverted: {result.get('why')}"
    if state != "reverted":
        return ""
    pointers, kept = list(result.get("reverted") or []), list(result.get("kept") or [])
    shown = ", ".join(pointers[:_SHOWN_POINTERS]) + (f", +{len(pointers) - _SHOWN_POINTERS} more" if len(pointers) > _SHOWN_POINTERS else "")
    line = (f"config.json: {len(pointers)} change(s) made during the story were reverted ({shown})" if pointers
            else "config.json: the file's formatting changed during the story and was restored")
    if kept:
        line += f"; {len(kept)} kept (written by {' and '.join(result.get('kept_sources') or ['a recorded writer'])})"
    if result.get("why"):
        line += f"; {result['why']}"
    where = result.get("backup")
    return line + (f"; the config as it was before the revert is at {where} - to keep a change, apply it again from there" if where else "")


# --- B-220: ONE changed test command, made as a proposal, approved by a person, applied by apply_plan -------
#
# The onboarding probes each profile's test command for a report the factory can read (`onboarding_probe.py`). When
# a cure is known and PROVEN on this machine, or the person gives a command of their own and it is proven, the change is
# one key of config.json. `apply_plan` can write any sealed, approved proposal; what did not exist was a MAKER of a
# one-key proposal: `migration_plan(answers=)` ignores every pointer but the required ones, both pointer setters walk
# objects only (`profiles` is a list), and `migration_plan` would drag in every template migration due on that config.
# So this is a pure maker: the CURRENT config with the target set, sealed - and no new writer (O4, t-379/t-380).
# What a stale yes to a command proposal is told (F8): the refusal AND its door, in both CLIs (`--record-approval`, `--apply`) and in
# `command_state`: the config moved after the proposal was made, so the yes would change a command nobody was asked about.
STALE_COMMAND_DOOR = ("proposal is stale: the config changed after this proposal was made, so a yes to it would change a command nobody "
                      "asked about. Make the proposal again: run `onboarding_probe.py --root <project> --probe-profiles --proposals-dir "
                      "<a folder outside the project>` (for a command the person gave: `onboarding_probe.py --root <project> --profile "
                      "<id> --command \"<their line>\" --proposals-dir <a folder outside the project>`), show the person the new "
                      "sentence, and record their yes on the new file.")
COMMAND_KINDS = ("cure", "command")     # `listing.kind`: a probe's cure, or the command a person gave; hash-covered
REPORT_KINDS = ("junit-xml", "trx")     # what a cure or a person may set beside the command (`pytest` is the runner's own)


def command_kind(proposal) -> str | None:
    """`cure` / `command` when this proposal changes a test command (its `listing.kind`, which `proposal_hash`
    covers: a kind cannot be dropped or changed without breaking the seal), else None."""
    listing = proposal.get("listing") if isinstance(proposal, dict) else None
    kind = listing.get("kind") if isinstance(listing, dict) else None
    return kind if kind in COMMAND_KINDS else None


def display_command(argv) -> str:
    """The command as a person reads it and could type it: words with a space or a shell character in double quotes,
    a `<placeholder>` the factory fills in left as it is. One renderer: the sentence the person is asked and the check
    that the sentence names the command the proposal writes both use it (E30)."""
    def word(token) -> str:
        text = str(token)
        if text == "":
            return '""'
        if re.fullmatch(r"<[^<>\s]+>", text):
            return text
        if not any(ch in " \t;\"'|&()*?$`\\!" for ch in text):
            return text
        if not any(ch in "\"\\$`" for ch in text):
            return '"' + text + '"'
        return shlex.quote(text) if "'" in text else "'" + text + "'"
    return " ".join(word(t) for t in argv) if isinstance(argv, (list, tuple)) else str(argv)


def _profile_slot(config: dict, profile_id: str):
    """(index, the profile) of the profile with this id, or (None, None). `profiles` that is not a list holds none."""
    rows = config.get("profiles") if isinstance(config, dict) else None
    for index, profile in enumerate(rows if isinstance(rows, list) else []):
        if isinstance(profile, dict) and str(profile.get("profile_id")) == str(profile_id):
            return index, profile
    return None, None


def _command_value(config: dict, listing: dict):
    """What this target holds in `config`: the profile's one-test argv, or the template's text; None when it is absent."""
    target = listing.get("target") if isinstance(listing.get("target"), dict) else {}
    if "profile_id" in target:
        import profile_contract as PC   # the ONE reader of `commands` (OH3-27, AR-13)
        profile = _profile_slot(config, target["profile_id"])[1]
        spec, problem = PC.profile_command(profile, "one_test")
        return None if problem else spec.get("argv")
    if "template_key" in target:
        templates = config.get("test_command_templates")
        return templates.get(target["template_key"]) if isinstance(templates, dict) else None
    return None


def _command_env_of(config: dict, listing: dict) -> dict:
    """The variables the target profile's one-test command sets in `config` (`profile_contract.command_env`, the ONE reader, AR-13);
    `{}` for a template target, an absent command or a foreign shape."""
    target = listing.get("target") if isinstance(listing.get("target"), dict) else {}
    if "profile_id" not in target:
        return {}
    import profile_contract as PC
    spec, problem = PC.profile_command(_profile_slot(config, target["profile_id"])[1], "one_test")
    return {} if problem else PC.command_env(spec)[0]


def command_proposal(root, target: dict, value, *, reporter_kind: str | None = None, reason: str = "probe cure",
                     kind: str = "cure", question: str = "", env: dict | None = None) -> dict:
    """The sealed proposal that changes ONE test command: the current config with only the target set.

    `target` is `{"profile_id": <id>}` (the profile's `commands.one_test.argv`, `value` a list of words) or
    `{"template_key": <key>}` (`test_command_templates.<key>`, `value` the command line as text). `reporter_kind`
    (profile target only) sets `reporter.kind` in the same profile: a trx report is read as trx only when the profile
    says so (F5), so the proposal carries both pointers, in ONE `changes` row (`also`). `kind` is `cure` or `command` and
    goes into `listing`, which the hash covers. `question` is the sentence the person is asked: it goes into
    `listing` too (F4), so a yes is bound to the words the person read, and it must name the command it would write.
    `env` (profile target only; EP1-22): the variables the command sets (`commands.one_test.env`, each exactly `{report_path}`);
    None leaves the command's `env` as it is, `{}` takes it out (the argv now carries the placeholder itself), a dict sets it. It
    is one more row of the SAME `also` (`/profiles/<i>/commands/one_test/env`, `to: null` when it is taken out) - one approval,
    one command, however many of its keys move.

    Pure: it writes nothing, never calls `migration_plan`, and leaves `conflicts`, `reasked`, `added` and every other list
    empty - what `apply_plan` can still refuse on is `validate` (F7), which is why the person is asked about one key and
    nothing else. Refuses, with its reason, when the config is absent (ConfigUnreadable when it cannot be read), the
    target is not there, the value is not a command, the sentence does not carry the command, or the profile already
    says its report is another kind (a person's recorded kind is not overwritten)."""
    if kind not in COMMAND_KINDS:
        raise ValueError(f"the kind of a command proposal is one of: {', '.join(COMMAND_KINDS)}")
    if reporter_kind is not None and reporter_kind not in REPORT_KINDS:
        raise ValueError(f"the report kind a command change may set is one of: {', '.join(REPORT_KINDS)}")
    current = read_config_file(Path(root))
    if current is None:
        raise ValueError("there is no qa-factory/config.json yet, so there is no command to change: onboarding writes the "
                         "configuration first, then the report probe may propose a change to a command in it")
    proposed = copy.deepcopy(current)
    pointers: list = []
    if isinstance(target, dict) and "profile_id" in target:
        if not (isinstance(value, (list, tuple)) and value and all(isinstance(w, str) and w.strip() for w in value)):
            raise ValueError("a profile's command is a non-empty list of words (an argv); it is not a line of text")
        index, profile = _profile_slot(proposed, target["profile_id"])
        if profile is None:
            known = ", ".join(str(p.get("profile_id")) for p in proposed.get("profiles") or [] if isinstance(p, dict)) or "none"
            raise ValueError(f"the profile `{target['profile_id']}` is not in qa-factory/config.json (it has: {known}), "
                             "so there is no command of it to change")
        import profile_contract as PC   # the ONE reader of `commands` (OH3-27, AR-13)
        _held, problem = PC.profile_command(profile, "one_test")
        if problem:
            # one approval changes ONE key: a foreign shape (a list of commands) is not "no commands" to be written over, and
            # the other commands of it would be erased by the one the person approved
            raise ValueError(f"the profile `{target['profile_id']}` in qa-factory/config.json has a command shape that is not "
                             f"read: {problem}. Nothing was changed: correct the profile first, by `references/profile-shape.json` "
                             "(`/qa-factory:qa-onboarding` writes it), then the command may be proposed")
        commands = profile["commands"] = PC.profile_commands(profile)[0]    # absent or null: created, as it always was
        spec = commands.get("one_test")
        if not isinstance(spec, dict):
            spec = commands["one_test"] = {}
        old = copy.deepcopy(spec.get("argv"))
        spec["argv"] = [str(w) for w in value]
        shown = display_command(spec["argv"])
        row = {"path": f"/profiles/{index}/commands/one_test/argv", "from": old, "to": list(spec["argv"]), "reason": reason}
        pointers.append(row["path"])
        if reporter_kind is not None:
            reporter = profile.get("reporter") if isinstance(profile.get("reporter"), dict) else {}
            was = reporter.get("kind")
            if was not in (None, "") and was != reporter_kind:
                raise ValueError(f"the profile `{target['profile_id']}` already says its report is `{was}`, and this change would "
                                 f"make it `{reporter_kind}`: a kind a person recorded is not overwritten. Say which is right "
                                 "(the command and its report kind change together, or not at all)")
            reporter["kind"] = reporter_kind
            profile["reporter"] = reporter
            row["also"] = [{"path": f"/profiles/{index}/reporter/kind", "from": was, "to": reporter_kind}]
            pointers.append(row["also"][0]["path"])
        if env is not None:
            env_problem = PC.command_env({"env": env})[1]
            if env_problem:
                raise ValueError(f"the variables a command change may set are not valid: {env_problem}")
            was_env = copy.deepcopy(spec.get("env"))
            if env:
                spec["env"] = dict(env)
            else:
                spec.pop("env", None)
            if (was_env or None) != (dict(env) or None):
                path = f"/profiles/{index}/commands/one_test/env"
                row.setdefault("also", []).append({"path": path, "from": was_env, "to": (dict(env) or None)})
                pointers.append(path)
        target_row = {"profile_id": str(target["profile_id"])}
    elif isinstance(target, dict) and "template_key" in target:
        if reporter_kind is not None:
            raise ValueError("a command template has no report kind to set: `reporter_kind` goes with a profile")
        if env is not None:
            raise ValueError("a command template has no variables to set: `env` goes with a profile")
        if not (isinstance(value, str) and value.strip()):
            raise ValueError("a command template is a non-empty line of text")
        templates = proposed.get("test_command_templates")
        if not isinstance(templates, dict):
            templates = proposed["test_command_templates"] = {}
        key = str(target["template_key"])
        old = templates.get(key)
        templates[key] = value
        shown = value
        row = {"path": f"/test_command_templates/{key}", "from": old, "to": value, "reason": reason}
        pointers.append(row["path"])
        target_row = {"template_key": key}
    else:
        raise ValueError("a command proposal names its target: {\"profile_id\": <id>} or {\"template_key\": <key>}")
    if not str(question).strip():
        raise ValueError("the sentence the person is asked is sealed with the proposal (it is what their yes is bound to): "
                         "give `question`")
    if shown not in question:
        raise ValueError("the sentence the person is asked does not carry the command this proposal would write, so a yes to "
                         f"it would not be a yes to this command: expected `{shown}` inside the sentence")
    proposal = {"schema_version": 1, "input_hash": _json_hash(current), "changes": [row], "conflicts": [],
                "deprecated_keys": [], "removed": [], "renamed": [], "reasked": [], "added": [], "kept": [],
                "reordered": [], "answers_legacy": {}, "evidence_refs": [], "proposed_config": proposed,
                "listing": {"kind": kind, "target": target_row, "command": shown, "question": question,
                            "pointers": pointers, "reporter_kind": reporter_kind,
                            **({"env": dict(env)} if env is not None else {}),
                            # the install half of onboard_apply reads these three lists of a listing; a command change
                            # retires, writes and regenerates nothing
                            "retire": [], "write": [], "regenerate": []}}
    proposal["proposal_hash"] = proposal_hash(proposal)
    return proposal


def command_approval_ref(proposal: dict) -> str:
    """The approval ref a person's yes to this proposal is recorded under: `onboarding-cure:<profile>:<hash12>` (or
    `onboarding-command:`), so two profiles' yeses, and a re-approval with other words, never collide."""
    kind = command_kind(proposal)
    if not kind:
        raise ValueError("this is not a proposal to change a test command")
    target = proposal["listing"].get("target") or {}
    name = str(target.get("profile_id") or target.get("template_key") or "command")
    return f"onboarding-{kind}:{name}:{str(proposal.get('proposal_hash'))[:12]}"


def command_question(proposal: dict) -> str:
    """The sentence the person is asked, RENDERED FROM THE SEALED FILE (F4): the one that was bound into `listing`, shown
    only when the file is still what was sealed and the sentence still names the command the proposal writes. A file edited
    after it was made is refused in words, not shown with a yes that would bind to other bytes."""
    if command_kind(proposal) is None:
        raise ValueError("this is not a proposal to change a test command, so it has no sentence to ask")
    if proposal.get("proposal_hash") != proposal_hash(proposal):
        raise ValueError("proposal is stale: the file was changed after it was sealed (its hash is no longer its own). Make "
                         "the proposal again (`onboarding_probe.py --probe-profiles`) and show the person the new sentence")
    listing = proposal["listing"]
    written = _command_value(proposal.get("proposed_config") or {}, listing)
    shown = display_command(written) if isinstance(written, list) else str(written)
    question = str(listing.get("question") or "")
    if not question.strip() or listing.get("command") != shown or shown not in question:
        raise ValueError("proposal is stale: the sealed sentence does not name the command this proposal writes. Make the "
                         "proposal again and show the person the new sentence")
    return question


def command_state(root, proposal: dict) -> dict:
    """Where a command proposal stands against the config as it is now: `pending` (a yes can still be recorded and
    applied), `already_done` (the config already holds this command - a second yes after an apply is "already done",
    never a stale refusal, F8), `stale` (the config moved on: make the proposal again) or `invalid` (not sealed, or not a
    command proposal). `why` says it in words. Reads only."""
    if command_kind(proposal) is None or proposal.get("proposal_hash") != proposal_hash(proposal):
        return {"state": "invalid", "why": "this is not a sealed proposal to change a test command"}
    listing = proposal["listing"]
    current = read_config_file(Path(root))
    if current is None:
        return {"state": "stale", "why": "there is no qa-factory/config.json any more"}
    now, wanted = _command_value(current, listing), _command_value(proposal.get("proposed_config") or {}, listing)
    # the command is its argv AND its env (EP1-22): a proposal that sets only `env` is pending until the env is on disk, and
    # an env that moved after sealing is not "already done"; absent, null and `{}` on both sides are equal
    env_ok = _command_env_of(current, listing) == _command_env_of(proposal.get("proposed_config") or {}, listing)
    kind_ok = True
    if listing.get("reporter_kind") and "profile_id" in (listing.get("target") or {}):
        kind_ok = ((_profile_slot(current, listing["target"]["profile_id"])[1] or {}).get("reporter") or {}).get("kind") == listing["reporter_kind"]
    if now is not None and now == wanted and kind_ok and env_ok:
        return {"state": "already_done",
                "why": f"already done: {listing.get('command')} is the command in qa-factory/config.json; nothing was changed"}
    if proposal.get("input_hash") == _json_hash(current):
        return {"state": "pending", "why": "the config is as it was when the proposal was made"}
    return {"state": "stale", "why": STALE_COMMAND_DOOR}


def _without_report_kind(config: dict, index: int) -> dict:
    """A copy of `config` with the one `reporter.kind` of profile `index` taken out (and the `reporter` object with it when that leaves it
    empty), so two configs can be compared for EVERYTHING ELSE."""
    copy_ = copy.deepcopy(config)
    profile = (copy_.get("profiles") or [])[index]
    reporter = profile.get("reporter")
    if isinstance(reporter, dict):
        reporter.pop("kind", None)
        if not reporter:
            profile.pop("reporter")
    return copy_


def _first_difference(a, b, pointer: str = "") -> str:
    """The JSON pointer of the first place two values differ ("" when they are equal)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                return f"{pointer}/{key}"
            found = _first_difference(a[key], b[key], f"{pointer}/{key}")
            if found:
                return found
        return ""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return pointer or "/"
        for index, (left, right) in enumerate(zip(a, b)):
            found = _first_difference(left, right, f"{pointer}/{index}")
            if found:
                return found
        return ""
    return "" if a == b and type(a) is type(b) else (pointer or "/")


def apply_adaptation(root, proposal: dict, adaptation_ref: str) -> Path | None:
    """Write a sealed `command_proposal` that is nothing but a REPORT ADAPTATION (B-416 F20 (b), D-0031): an EMPTY `reporter.kind` of one
    profile set to `junit-xml` or `trx`, its command unchanged. The authority is the helper's own record row (`adaptation_ref`, `RA-<n>`),
    not a person's approval, so no approval line is written and the approvals log stays a log of people's words - the same sealed
    proposal, the same checks (seal, input hash, `validate`, the canonical key order, the migration backup), and the same ONE writer
    (`_write_config`) as `apply_plan` (FR-17).

    The proposal's own `changes` and `listing` are NEVER trusted (the seal proves integrity, not origin: anyone can recompute it): the
    check compares its `proposed_config` with the CURRENT config - equal once the one `reporter.kind` pointer of the one profile that
    differs is removed. Refused, nothing written, with the door `report_adapt.py understood`: any other change, a profile that already
    records a kind, a kind outside REPORT_KINDS, more than one profile changed, a stale or unsealed proposal. Returns the backup."""
    root = Path(root)
    if not str(adaptation_ref).strip():
        raise ValueError("an adaptation ref (RA-<n>) is required: the helper's record row is the authority of this write")
    _check_sealed(proposal, None)
    if command_kind(proposal) != "cure":
        raise ValueError("this is not a proposal the report adaptation made: nothing was written")
    _need_proposed_config(proposal)
    current = read_config_file(root)
    if current is None:
        raise ValueError("there is no qa-factory/config.json any more, so there is nothing to adapt; nothing was written")
    if proposal.get("input_hash") != _json_hash(current):
        raise ValueError(STALE_COMMAND_DOOR)
    proposed = proposal["proposed_config"]
    before, after = current.get("profiles"), proposed.get("profiles")
    door = "record what was understood instead (`report_adapt.py understood`)"
    if not (isinstance(before, list) and isinstance(after, list) and len(before) == len(after)
            and all(isinstance(p, dict) for p in before + after)):
        raise ValueError("nothing was written: an adaptation may only set an empty report kind of one profile to junit-xml or trx with its "
                         f"command unchanged, and this proposal also changes /profiles; {door}")

    def kind_of(profile: dict):
        return (profile.get("reporter") or {}).get("kind") if isinstance(profile.get("reporter"), dict) else None
    kinded = [i for i, (x, y) in enumerate(zip(before, after)) if kind_of(x) != kind_of(y)]
    if len(kinded) != 1:
        first = _first_difference(current, proposed)
        if not first:
            raise ValueError("the config already holds what this adaptation sets; nothing was written")
        also = f"/profiles/{kinded[1]}/reporter/kind" if len(kinded) > 1 else first
        raise ValueError("nothing was written: an adaptation may only set an empty report kind of one profile to junit-xml or trx with its "
                         f"command unchanged, and this proposal also changes {also}; {door}")
    index = kinded[0]
    name = str(after[index].get("profile_id"))
    head = f"nothing was written: an adaptation may only set an empty report kind of profile {name} to junit-xml or trx with its command unchanged"
    was, new = kind_of(before[index]), kind_of(after[index])
    if was not in (None, ""):
        raise ValueError(f"{head}, and profile {name} already records `{was}`; {door}")
    if new not in REPORT_KINDS:
        raise ValueError(f"{head}, and this proposal sets `{new}`, which is not one of {', '.join(REPORT_KINDS)}; {door}")
    other = _first_difference(_without_report_kind(current, index), _without_report_kind(proposed, index))
    if other:
        raise ValueError(f"{head}, and this proposal also changes {other}; {door}")
    errors = validate(proposed)
    if errors:
        raise ValueError("proposed config is invalid: " + "; ".join(errors) + ". Nothing was written")
    return _write_config(root, current, proposed, proposal["input_hash"], str(adaptation_ref))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--migration-plan", action="store_true")
    parser.add_argument("--apply", type=Path)
    parser.add_argument("--record-approval", type=Path)
    parser.add_argument("--approval-ref", default="")
    parser.add_argument("--evidence-ref", default="")
    parser.add_argument("--fold", action="store_true",
                        help="with --record-approval: record that the old product passport was folded into the "
                             "project profile, for the approval --approval-ref names (once per approval)")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--price-table-answer", choices=PRICE_ANSWERS,
                        help="with --migration-plan: the person's answer to the old price table "
                             "question - builtin, or own together with one --model-id per model")
    parser.add_argument("--answers", type=Path,
                        help="with --migration-plan: a JSON file mapping a pointer (like /dod) to the person's "
                             "answer, for every key the plan listed as needing one")
    parser.add_argument("--model-id", action="append", default=[],
                        help="with --price-table-answer own: an exact model id whose old price is the project's")
    parser.add_argument("--check-environment", action="store_true",
                        help="does this config survive its own probe against the env file it names?")
    args = parser.parse_args()
    try:
        _dispatch(args, parser)
    except ConfigUnreadable as exc:
        # An unreadable config is refused with its door, exit 2 (the code of a malformed call
        # that argparse uses), never a traceback and never a guess at what it should have said.
        print(f"config_contract: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except ValueError as exc:
        # A refused proposal (stale, not approved, unresolved conflict, nothing to approve yet):
        # its message says what is wrong and what to do; a traceback around it only hides that.
        print(f"config_contract: refused: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _already_done(root: Path, proposal: dict) -> bool:
    """A second yes (or a second apply) on a command proposal the config already carries is "already done": said, exit
    0, nothing written - never the stale refusal a repeated `record_approval` would give once the first apply changed the
    config (F8). Prints the JSON line and returns True when that is the case."""
    if command_kind(proposal) and command_state(root, proposal)["state"] == "already_done":
        print(json.dumps({"already_done": True, "says": command_state(root, proposal)["why"]}, ensure_ascii=False))
        return True
    return False


def _dispatch(args, parser) -> None:
    if args.fold and not args.record_approval:
        parser.error("--fold goes with --record-approval <the sealed proposal> --approval-ref <the approval it was recorded under>")
    if args.record_approval:
        proposal = json.loads(args.record_approval.read_text(encoding="utf-8"))
        if args.fold:
            print(json.dumps({"fold_log": str(record_fold(args.root.resolve(), proposal, args.approval_ref, args.evidence_ref))}))
            return
        if _already_done(args.root.resolve(), proposal):
            return
        print(json.dumps({"approval_log": str(record_approval(args.root.resolve(), proposal,
                                                               args.approval_ref, args.evidence_ref))}))
        return
    if args.apply:
        proposal = json.loads(args.apply.read_text(encoding="utf-8"))
        if _already_done(args.root.resolve(), proposal):
            return
        backup = apply_plan(args.root.resolve(), proposal, args.approval_ref)
        print(json.dumps({"backup": str(backup) if backup is not None else None}))
        return
    config = read_config_file(args.root.resolve())  # None: no config.json, the empty input
    if config is None and not args.migration_plan:
        what = "--check-environment" if args.check_environment else "--validate"
        print(f"config_contract: {what} has nothing to read: {args.root.resolve() / 'qa-factory' / 'config.json'} "
              "does not exist. Run /qa-factory:qa-onboarding to write it, or --migration-plan to see "
              "the proposal for a project with no configuration.", file=sys.stderr)
        raise SystemExit(1)
    if args.check_environment:
        root = args.root.resolve()
        environment = config.get("environment") or {}
        names = env_key_names(root, environment)
        errors = environment_errors(environment) + environments_frontend_errors(config.get("environments")) + environments_surface_errors(
            config.get("environments")) + environment_key_errors(
            environment, names, strict_integrations=True) + environments_account_errors(config.get("environments"), names)
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2, ensure_ascii=False))
        raise SystemExit(1 if errors else 0)
    if args.migration_plan:
        try:
            answers = None
            if args.answers:
                try:
                    answers = json.loads(args.answers.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError) as exc:
                    raise ValueError(f"{args.answers} cannot be read as JSON ({exc}); it must hold one JSON "
                                     "object that maps a pointer like /dod to the person's answer") from exc
            plan = migration_plan(config, args.price_table_answer, args.model_id, answers=answers,
                                  root=args.root.resolve())
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    elif args.validate:
        errors = validate(config)
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
        raise SystemExit(1 if errors else 0)
    else:
        parser.error("choose --migration-plan, --record-approval, --apply or --validate")


if __name__ == "__main__":
    main()
