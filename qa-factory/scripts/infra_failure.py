#!/usr/bin/env python3
"""An infrastructure failure of `claude -p` is not a role's result (B-012).

On TP1-13877 a login error, a usage limit and a Cloudflare page each came back from `claude -p`
as the "final message" of a role. The driver read them as a handoff that was not in the form, resumed
the role, called the conductor with the login error as the refusal, and put "Not logged in" to the
person as the conductor's question: five conductor sessions and four resumes, all for texts no role
wrote (`state/driver-runs.jsonl` rows 1-4, 7 and 17). This module is the ONE place that tells such a
call from a role's own answer, and `story_run.Driver.run_claude` is its one caller.

    rules()                          -> (rules dict, notes)      # references/driver-infra.json
    classify(result, rules)          -> None | {kind, rule, retry_code, reset}
    child_env(base, rules, driver_cfg) -> (env, removed_present, notes)

What is read is a DATA file (FR-13): the vocabulary of failures is closed today and grows with the
service, and a table in code fails on the first wording it does not hold. What is NOT read is the
text of a call that succeeded (FR-12): only a call that failed (`is_error` or a non-zero exit) has
its text matched, and a role that wrote the words "Not logged in" in a successful handoff is a
role's result like any other. A failure no row matches is `unclassified` and goes on exactly as it
did before this module existed - the callers keep their own refusal for it.

Nothing here decides a retry: `kind` names the failure, `retry_code` names the row's word for
`runtime_policy.retry_decision`, and the driver asks that function. Nothing here prints; the notes
are returned for the caller to say once.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402

RULES_FILE = "driver-infra.json"
KINDS = ("auth", "limit", "transient")
UNREADABLE = "infrastructure failures not recognised: references/driver-infra.json unreadable"


def rules() -> tuple:
    """(rules, notes). An absent or unreadable file gives `{}` and one note - classification is then
    `unclassified` for every failure, which is the driver's behaviour before this file existed. A
    row whose regex does not compile, or whose kind is not one the driver has a move for, is skipped
    with a note; the other rows still match."""
    data = hooklib.load_ref_json(RULES_FILE)
    if not isinstance(data, dict) or not data:
        return {}, [UNREADABLE]
    notes, good = [], []
    for row in data.get("failures") or []:
        if not isinstance(row, dict):
            notes.append("infrastructure failures: a row that is not an object was skipped")
            continue
        name = str(row.get("id") or "?")
        if row.get("kind") not in KINDS:
            notes.append(f"infrastructure failures: row `{name}` skipped: its kind is not one of "
                         + ", ".join(KINDS))
            continue
        try:
            re.compile(str(row.get("pattern") or ""))
            if row.get("reset_pattern"):
                re.compile(str(row["reset_pattern"]))
        except re.error as exc:
            notes.append(f"infrastructure failures: row `{name}` skipped: its pattern does not compile ({exc})")
            continue
        if not row.get("pattern"):
            notes.append(f"infrastructure failures: row `{name}` skipped: it has no pattern")
            continue
        hosts = row.get("hosts")
        if hosts is not None and not (isinstance(hosts, list) and hosts and all(isinstance(h, str) and h for h in hosts)):
            notes.append(f"infrastructure failures: row `{name}` skipped: `hosts` must be a non-empty list of host names")
            continue
        good.append(row)
    return dict(data, failures=good), notes


def classify(result: dict, rules: dict, host=None):
    """None when the call is a role's own result; else {kind, rule, retry_code, reset}.

    None on a call that did not fail, and the text is not read on that path at all. None on a
    subtype the data names as the role's own outcome (`error_max_turns`). Otherwise the result text
    plus stderr are searched against the rows in file order, first match wins; no match is
    `{"kind": "unclassified", "rule": ""}`.

    A row with a `hosts` list (the `codex_*` rows: `["codex"]`) is tried only for a call of one of those hosts;
    a row without the key is tried for every call. `host=None` (a caller that does not say) tries the rows
    without the key only - exactly the rows there were before `hosts` existed - so the broad wording of a Codex
    row (`401`, `unauthorized`) never reads a role's text on a call of another host (CX1-15 F-4)."""
    result = result or {}
    if not result.get("is_error") and int(result.get("exit_code") or 0) == 0:
        return None
    rules = rules if isinstance(rules, dict) else {}
    if str(result.get("subtype") or "") in (rules.get("not_infra_subtypes") or []):
        return None
    text = str(result.get("result") or "") + "\n" + str(result.get("stderr") or "")
    for row in rules.get("failures") or []:
        try:
            if row.get("hosts") is not None and host not in row["hosts"]:
                continue
            if not re.search(str(row.get("pattern") or ""), text):
                continue
            reset = ""
            if row.get("reset_pattern"):
                found = re.search(str(row["reset_pattern"]), text)
                if found:
                    reset = (found.group(1) if found.groups() else found.group(0)).strip()
        except (re.error, AttributeError, TypeError):
            continue  # a row the caller built by hand and got wrong: the other rows still get their turn
        return {"kind": row.get("kind"), "rule": str(row.get("id") or ""),
                "retry_code": str(row.get("retry_code") or ""), "reset": reset}
    return {"kind": "unclassified", "rule": ""}


def _names(value, label: str, notes: list) -> list:
    """A config list of variable names; anything else is ignored, and says so."""
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    notes.append(f"driver.child_env.{label} ignored: it must be a list of variable names")
    return []


def _key(env: dict, name: str):
    """The key of `env` that `name` denotes: exact, and on Windows any case (the host uppercases)."""
    if name in env:
        return name
    if os.name == "nt":
        wanted = name.upper()
        return next((k for k in env if k.upper() == wanted), None)
    return None


def child_env(base: dict, rules: dict, driver_cfg: dict) -> tuple:
    """(env, removed_present, notes): `base` without what a `claude -p` child must not inherit.

    removed = (the data's `remove` + every name with a listed prefix + the variables the
    `remove_named_by` variables NAME + `driver.child_env.remove`) - `driver.child_env.keep`.
    `keep` is the project's door for a gateway or an API-key setup it uses on purpose; a name in
    both `keep` and the config's own `remove` is kept and says so. `removed_present` lists only
    the names that were in `base`: a list of what was taken away, not of what was looked for."""
    notes = []
    spec = (rules or {}).get("child_env") if isinstance((rules or {}).get("child_env"), dict) else {}
    cfg = (driver_cfg or {}).get("child_env") if isinstance((driver_cfg or {}).get("child_env"), dict) else {}
    remove = set(_names(spec.get("remove"), "remove", []))
    prefixes = _names(spec.get("remove_prefixes"), "remove_prefixes", [])
    remove |= {name for name in base
               if any(name.startswith(p) or (os.name == "nt" and name.upper().startswith(p.upper()))
                      for p in prefixes)}
    for holder in _names(spec.get("remove_named_by"), "remove_named_by", []):
        found = _key(base, holder)
        target = str(base.get(found) or "").strip() if found else ""
        if target:
            remove.add(target)
    keep = set(_names(cfg.get("keep"), "keep", notes))
    extra = set(_names(cfg.get("remove"), "remove", notes))
    for name in sorted(keep & extra):
        notes.append(f"driver.child_env: `{name}` is in both keep and remove; it is kept")
    remove |= extra
    dropped = {}
    for name in sorted(remove):
        found = _key(base, name)
        if found is None:
            continue
        if any(_key({found: 1}, k) for k in keep):
            continue
        dropped[found] = True
    env = {k: v for k, v in base.items() if k not in dropped}
    return env, sorted(dropped), notes
