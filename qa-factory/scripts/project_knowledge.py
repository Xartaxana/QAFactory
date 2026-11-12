"""The project's answer registry: what a person told the factory ONCE about the product, kept with their words (t-2142, phase 0).

A question used to be asked again in every story: "which account is the auditor?", "is `superuser` a role of this product?". The
registry keeps the answer in `qa-factory/records/project-knowledge.json` (carried by the project, like the environment record),
with the scope it holds in, the person's own words, who recorded it and when. It is built on the record family of
`environment_record` (`load_rows` / `write_rows` / `next_id` / `revoke_row`): one writer (`record`), one pure reader (`state`).

The registry holds STATE and PROVENANCE, never a judgment: which roles a story needs is the strategist's call, what an account's
value is stays in `config.json` (written by `project_decisions.record_stand_account`, whose decision receipt is what keeps it across
`restore_config`). `state()` of an account is CONFIG FIRST: `known` only when the stand's entry names two variables.

ERROR DIRECTION: toward asking (FR-59). An unreadable registry, another `schema_version`, a revoked row, a row with an empty key or
stand, a state outside the list, an unparseable `at`, twins, a malformed note - each reads as `unknown`, never as `known`. The ONE
input that suppresses a question is a live `not_needed` row, and only through a road that says so in the packet (PK0-9).

Before the first `record` the file does not exist; every reader treats an absent file as "config only".

  project_knowledge.py show [--json]
  project_knowledge.py account --task T --role R --user-key U --secret-key S --words-file F [--replace]
  project_knowledge.py role --task T --role R --state known|not_needed [--sign-in account|none] --words-file F
  project_knowledge.py revoke --task T --id PK-n --words-file F
  project_knowledge.py side --task T --name S [--stand N] (--reality real|substituted|absent | --deliverable yes|no
                          [--settles-by-file F] | --reference) --words-file F
"""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import environment_record as ER  # the record family this registry is built on: no copy of its reader, writer or numbering

RECORD_REL = "qa-factory/records/project-knowledge.json"
LOCK_REL = "qa-factory/state/project-knowledge.lock"
SCHEMA_VERSION = 1
LIST_KEY = "facts"
ID_PREFIX = "PK-"
ROLES_KEY = "product.roles"
ACCOUNTS_KEY = "environments.credentials_by_role"
# t-2181 PC-1b: the standing facts about the product's sides. The element of each row is the side NAME, compared exactly
# (`UI` and `ui` are two sides); every row is written `state: known`.
SIDES_KEY = "product.sides"                     # project scope: {"deliverable": bool, "settles_by": str}
STAND_SIDES_KEY = "environments.sides"          # stand scope: {"reality": a word of references/side-realities.json}
REFERENCE_KEY = "environments.reference_for"    # stand scope: {"reference": True} - this stand runs the OLD version of the side
SIDE_KEYS = (SIDES_KEY, STAND_SIDES_KEY, REFERENCE_KEY)
# S15: one table; the comparator registered for a key compares its elements (phase 0: the role form for both keys). Phase 1's
# catalogue replaces this literal.
KEYS = {
    ROLES_KEY: {"scope": "project", "compare": "role_form"},
    ACCOUNTS_KEY: {"scope": "stand", "compare": "role_form"},
    SIDES_KEY: {"scope": "project", "compare": "exact"},
    STAND_SIDES_KEY: {"scope": "stand", "compare": "exact"},
    REFERENCE_KEY: {"scope": "stand", "compare": "exact"},
}
KNOWN, NOT_NEEDED, NOTICED, UNKNOWN = "known", "not_needed", "noticed_unconfirmed", "unknown"
# `asked` is RESERVED for phase 2 (no producer here); `unreachable` is run-scoped and never stored. A row in any other state is skipped.
STATES = (KNOWN, NOT_NEEDED, NOTICED)
SOURCES = ("person", "role", "legacy_config")
BY = ("conductor", "driver")
SIGN_INS = ("account", "none")
NO_TRACE_WORDS = "an experiment leaves no trace: the answer stays in this story's words (waiver); nothing was recorded"
PLACEHOLDER_STAND = "this stand"


def _unsafe_role(text) -> str:
    """The reason the decision registry cannot carry this role name, or "". The ONE predicate is the account road's own
    (`project_decisions._refuse_unsafe_role`: comma, bar, backslash, control bytes, every line break); an import or runtime failure
    is a refusal, never a pass (FR-59)."""
    try:
        import project_decisions as PD
        PD._refuse_unsafe_role(text)
    except ValueError as exc:
        return str(exc).replace("nothing was written", "nothing was recorded")
    except Exception as exc:    # noqa: BLE001 - could not be checked: toward refusing
        return (f"whether the role {str(text).strip()[:60]!r} is safe to carry could not be established ({type(exc).__name__}); "
                "name the role in plain words without commas, bars, backslashes or line breaks; nothing was recorded")
    return ""


# --- the comparators (S15) ---------------------------------------------------------------------------------------------

def _role_form(text) -> str:
    import gate_preflight as GP     # the ONE reader of a role's normal form (AR-13); lazy: that module is large
    return GP._role_form(text)


def _exact_form(text) -> str:
    """The element unchanged: a side name is compared EXACTLY (`UI` is not `ui`, no trimming, no case fold). t-2181 S2."""
    return text if isinstance(text, str) else str(text)


_COMPARATORS = {"role_form": _role_form, "exact": _exact_form}


def _form(key, element) -> str:
    """The element as the comparator registered for `key` reads it."""
    compare = _COMPARATORS.get((KEYS.get(key) or {}).get("compare"))
    return compare(element) if compare else str(element).strip()


# --- the file ----------------------------------------------------------------------------------------------------------

def record_path(root) -> Path:
    return Path(root) / Path(RECORD_REL)


def load(root) -> tuple:
    """`(rows, problem)`. Never raises. An absent file is `([], "")` - the state before the first `record`; an unreadable one is
    `([], <why>)`: nothing is known from it and the writers refuse to write over it."""
    return ER.load_rows(record_path(root), LIST_KEY, SCHEMA_VERSION, RECORD_REL)


@contextmanager
def lock(root, timeout: float = 10.0):
    """The writers' lock: an OS byte lock on a file (`event_store.take_file_lock`, as `project_decisions.lock`). A busy or an
    unmakeable lock is a `TimeoutError` that says so; the CLI prints it and exits 2."""
    import event_store as ES
    try:
        held = ES.take_file_lock(Path(root) / Path(LOCK_REL), timeout, purpose="project knowledge", record_holder=True)
    except ES.LockBusy as exc:
        raise TimeoutError(f"the record of project knowledge is busy; run the same command again ({exc.holder_clause})") from exc
    except ES.LockBroken as exc:
        raise TimeoutError(str(exc)) from exc
    try:
        yield
    finally:
        held.release()


def _usable(row) -> bool:
    """A row the readers believe: a live row of a known key, in a written state, whose scope is the key's own and whose element
    (and, for a stand fact, stand) is present. Anything else is skipped - the asking side."""
    if not isinstance(row, dict) or row.get("revoked_at"):
        return False
    spec = KEYS.get(row.get("key"))
    if spec is None or row.get("state") not in STATES or row.get("scope") != spec["scope"]:
        return False
    if not isinstance(row.get("element"), str) or not row["element"].strip() or not isinstance(row.get("environment"), str):
        return False
    return bool(row["environment"]) if spec["scope"] == "stand" else True


def _latest(rows, key, environment, element, states=STATES):
    """The latest usable row of the subject `(key, environment, element)`: the later `at` wins, on a tie the later row; a row whose
    `at` cannot be parsed is the oldest there is. The environment is compared exactly, the element by the key's comparator."""
    form = _form(key, element)
    if not form:
        return None
    best, best_order = None, None
    for index, row in enumerate(rows or []):
        if (not _usable(row) or row["key"] != key or row["environment"] != environment or row["state"] not in states
                or _form(key, row["element"]) != form):
            continue
        order = (ER._moment(row.get("at")), index)
        if best_order is None or order >= best_order:
            best, best_order = row, order
    return best


# --- the one reader ----------------------------------------------------------------------------------------------------

def _config(root, cfg):
    if isinstance(cfg, dict):
        return cfg
    try:
        data = json.loads((Path(root) / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stands(cfg) -> list:
    raw = cfg.get("environments") if isinstance(cfg, dict) else None
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _stand_roles(cfg, environment):
    """The `credentials_by_role` object of the stand NAMED `environment` (exact), or None: no such stand, two of one name, no object."""
    named = [e for e in _stands(cfg) if str(e.get("name") or "") == environment] if environment else []
    roles = named[0].get("credentials_by_role") if len(named) == 1 else None
    return roles if isinstance(roles, dict) else None


def _blank(problem) -> dict:
    return {"state": UNKNOWN, "row": None, "source": "", "problem": problem, "twins": [], "malformed": False}


def _source_of(row) -> str:
    provenance = row.get("provenance") if isinstance(row, dict) else None
    return str(provenance.get("source") or "") if isinstance(provenance, dict) else ""


def _account_state(rows, problem, environment, element, cfg) -> dict:
    """CONFIG FIRST: `known` exactly when the stand's entry for the role holds two variable names. The registry only adds provenance;
    a `known` row whose config entry is gone, twinned or malformed reads as `unknown` (the value carrier wins)."""
    import gate_preflight as GP
    out = _blank(problem)
    roles = _stand_roles(cfg, environment)
    candidates = GP.role_candidates(roles, element) if roles is not None else []
    if len(candidates) > 1:
        out["twins"] = list(candidates)
        return out
    if not candidates:
        return out
    real = candidates[0]
    if len(GP.account_keys(roles[real])) != 2:
        out["malformed"] = True
        return out
    row = _latest(rows, ACCOUNTS_KEY, environment, real, states=(KNOWN,))
    out.update(state=KNOWN, row=row, source=(_source_of(row) or "registry") if row else "legacy_config")
    return out


def state(root, key, environment="", element="", cfg=None) -> dict:
    """`{"state", "row", "source", "problem", "twins", "malformed"}` of ONE fact. PURE: writes nothing, never raises.

    `state` is `known` / `not_needed` / `noticed_unconfirmed` / `unknown`; `unknown` is never stored. `problem` is the registry's
    load problem ("" when it reads) so the caller can say it (FR-41). `twins`: the config keys a role could mean when more than
    one does; `malformed`: the stand's entry exists but names fewer than two variables. For `product.roles` only registry rows
    count: a role known only from `credentials_by_role` is a roster element via `roster()` and `unknown` here."""
    try:
        rows, problem = load(root)
        if key == ACCOUNTS_KEY:
            return _account_state(rows, problem, str(environment or ""), str(element or ""), _config(root, cfg))
        row = _latest(rows, key, str(environment or ""), str(element or ""))
        out = _blank(problem)
        if row is not None:
            out.update(state=row["state"], row=row, source=_source_of(row) or "registry")
        return out
    except Exception as exc:    # a reader never stops a gate: an unknown it could not establish is `unknown`
        return _blank(f"the record of project knowledge could not be read ({type(exc).__name__})")


def subjects(root, key, environment=None) -> dict:
    """`{"subjects": [(environment, element)], "problem": str}`: the subjects of `key` that have a live row - ALL stands when
    `environment` is None, else that stand only (compared exactly). PURE: writes nothing, never raises. The precedence is this
    module's own (`_usable`, then the later `at`, a tie the later row, an unparseable `at` the oldest): a revoked row, a row in a state
    the registry does not store and a row of another scope are skipped; the element returned is the latest row's, as written.
    `problem` is the registry's load problem ("" when it reads), so a caller can tell "no row" from "could not read" (FR-41)."""
    out = {"subjects": [], "problem": ""}
    try:
        rows, out["problem"] = load(root)
        latest = {}
        for index, row in enumerate(rows):
            if not _usable(row) or row["key"] != key or (environment is not None and row["environment"] != environment):
                continue
            subject, order = (row["environment"], _form(key, row["element"])), (ER._moment(row.get("at")), index)
            if subject not in latest or order >= latest[subject][0]:
                latest[subject] = (order, row)
        out["subjects"] = sorted((env, row["element"]) for (env, _), (_, row) in latest.items())
    except Exception as exc:    # a lister never stops a gate: what it could not read is a problem, not an empty list
        out["problem"] = f"the record of project knowledge could not be read ({type(exc).__name__})"
        out["subjects"] = []
    return out


def roster(root, cfg, stand) -> dict:
    """`{"elements": [...], "removed": [...], "problem"}`: the product's roles. PURE: writes nothing, never raises.

    Elements: the live registry rows of `product.roles` (`known`, `noticed_unconfirmed`) UNION every role key of
    `credentials_by_role` on any stand (`known`, `legacy_config`, sign-in an account), one per role form, a registry row winning
    over config evidence. A `not_needed` role is OUT of the roster (listed under `removed`) even when a config account exists; that
    account's own `state()` stays `known`. `default`, `env:...` and `created:...` are never elements. `account` on an element is
    True / False for the account on `stand`, None when no stand is chosen."""
    out = {"elements": [], "removed": [], "problem": ""}
    try:
        import config_contract as CC
        import gate_preflight as GP
        rows, out["problem"] = load(root)
        cfg = _config(root, cfg)
        stand = str(stand or "").strip()
        seen = set()
        newest = {}
        for _, row in sorted(((i, r) for i, r in enumerate(rows) if _usable(r) and r["key"] == ROLES_KEY and r["environment"] == ""),
                             key=lambda pair: (ER._moment(pair[1].get("at")), pair[0])):
            newest[_form(ROLES_KEY, row["element"])] = row         # the latest row of each role form
        for form, row in newest.items():
            if not form or CC.reserved_role(row["element"]):
                continue
            seen.add(form)
            provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
            if row["state"] == NOT_NEEDED:
                out["removed"].append({"role": row["element"], "id": row.get("id"), "story": provenance.get("story", ""),
                                       "words": provenance.get("words", ""), "at": row.get("at", "")})
                continue
            value = row.get("value") if isinstance(row.get("value"), dict) else {}
            out["elements"].append({"role": row["element"], "state": row["state"], "source": _source_of(row) or "registry",
                                    "sign_in": value.get("sign_in") if value.get("sign_in") in SIGN_INS else "account",
                                    "story": provenance.get("story", ""), "at": row.get("at", ""), "id": row.get("id")})
        for entry in _stands(cfg):
            held = entry.get("credentials_by_role")
            for name in held if isinstance(held, dict) else []:
                form = GP._role_form(name) if isinstance(name, str) else ""
                if not form or CC.reserved_role(name) or form in seen:
                    continue
                seen.add(form)
                out["elements"].append({"role": name, "state": KNOWN, "source": "legacy_config", "sign_in": "account",
                                        "story": "", "at": "", "id": None})
        for element in out["elements"]:
            element["account"] = (state(root, ACCOUNTS_KEY, stand, element["role"], cfg)["state"] == KNOWN) if stand else None
    except Exception as exc:
        out["problem"] = out["problem"] or f"the record of project knowledge could not be read ({type(exc).__name__})"
    return out


# --- the one writer ----------------------------------------------------------------------------------------------------

def _refuse_no_trace(task_root) -> str:
    """The reason a story that leaves no trace may not record an answer, or "" (P8, FR-53). The one reader of `no_trace` is
    `external_writes.closed_by_run`. A story that is not known (`task_root` None) is no experiment. Returns a reason; never raises."""
    if task_root is None:
        return ""
    try:
        import external_writes
        if external_writes.closed_by_run(task_root):
            return NO_TRACE_WORDS
    except Exception:
        return ("whether this story is an experiment that leaves no trace could not be established; check `pipeline.json` of the story "
                "and run the same command again; nothing was recorded")
    return ""


# part of the record_problems unit (C16, census row record_problems); not a unit of its own
def _side_value_faults(key, value) -> list:
    """The shape of the `value` of a side row (t-2181 C16), words from `references/side-realities.json` (the one reader,
    `contract.side_realities`). A data file that cannot be read refuses the write (FR-59): no word is invented in code."""
    if key == SIDES_KEY:
        if (not isinstance(value, dict) or not isinstance(value.get("deliverable"), bool) or set(value) - {"deliverable", "settles_by"}
                or not isinstance(value.get("settles_by", ""), str)):
            return [f"{key} carries {{\"deliverable\": true or false, \"settles_by\": words (may be empty)}}, not {value!r}; give "
                    "whether this story's team delivers the side (`--deliverable yes|no`); nothing was recorded"]
        return []
    if key == REFERENCE_KEY:
        if not isinstance(value, dict) or value != {"reference": True}:
            return [f"{key} carries {{\"reference\": true}}, not {value!r}; record it with `side --reference`; nothing was recorded"]
        return []
    import contract
    words = contract.side_realities().get("realities")
    if not isinstance(words, list) or not words:
        return ["the reality words of references/side-realities.json cannot be read, so a side's reality cannot be checked; "
                "restore that file and run the same command again; nothing was recorded"]
    if not isinstance(value, dict) or set(value) != {"reality"} or value.get("reality") not in words:
        return [f"{key} carries {{\"reality\": one of {', '.join(str(w) for w in words)}}}, not {value!r}; "
                "record it with `side --reality <word>`; nothing was recorded"]
    return []


def record_problems(key, environment, element, state, scope, words, source, by, load_problem="", value=None) -> list:
    """The reasons a row may not be written, as sentences with their door; `[]` when it may. Form and presence only (AR-29): a bad
    key, a state or a scope the key does not take, an empty stand or element, an element the decision registry cannot carry, empty
    words for a person's answer, an unreadable registry; for the three side keys also the shape of `value` and an exact, untrimmed
    side name. Returns the reasons; never raises."""
    spec = KEYS.get(key)
    if spec is None:
        return [f"the key {key!r} is not a project-knowledge key (the keys: {', '.join(KEYS)}); nothing was recorded"]
    out = []
    if state not in STATES:
        out.append(f"the state {state!r} cannot be recorded here (one of {', '.join(STATES)}); nothing was recorded")
    elif (spec["scope"] == "stand" or key in SIDE_KEYS) and state != KNOWN:
        out.append(f"a fact of a stand or of a side is recorded as `known` only, not {state!r}; nothing was recorded")
    if scope != spec["scope"]:
        out.append(f"{key} holds for the {spec['scope']}, not {scope!r} (an answer for one story only is a waiver in that story); "
                   "nothing was recorded")
    if spec["scope"] == "stand" and not str(environment or "").strip():
        out.append(f"{key} is a fact of a stand and no stand is named; name the stand (the story's chosen stand); nothing was recorded")
    text = str(element or "")
    if key in SIDE_KEYS:
        out += _side_value_faults(key, value)
        if not text.strip():
            out.append("the side's name is empty; name it; nothing was recorded")
        elif text != text.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            out.append(f"the side name {text.strip()[:60]!r} carries a space at an end or a control character; side names are compared "
                       "exactly, so give the name as it is written in the tests; nothing was recorded")
        elif "." in text or "=" in text:
            out.append(f"the side name {text[:60]!r} holds a dot or an equals sign; name the side without them, because the name is a key "
                       "of the story's record (`sides.<name>.<attribute>=<value>`); nothing was recorded")
    elif not text.strip():
        out.append("the element (the role) is empty; name it; nothing was recorded")
    elif _unsafe_role(text):
        out.append(_unsafe_role(text))
    else:
        import config_contract as CC
        if CC.reserved_role(text):
            out.append(f"the role {text.strip()[:60]!r} is a reserved form (`default`, `env:...`, `created:...`), never a product role; "
                       "choose another name; nothing was recorded")
        elif not _form(key, text):
            out.append(f"the role {text.strip()[:60]!r} holds no letter or digit to tell it from another; name it; nothing was recorded")
    if source not in SOURCES:
        out.append(f"the source {source!r} is not one of {', '.join(SOURCES)}; nothing was recorded")
    if by not in BY:
        out.append(f"`by` {by!r} is not one of {', '.join(BY)}; nothing was recorded")
    if source == "person" and not str(words or "").strip():
        import person_words
        out.append("the person's words are empty; record the answer with their own words in a file: "
                   + person_words.door("project_knowledge.py role --task <T> --role <role> --state <state>"))
    if load_problem:
        out.append(load_problem + "; nothing was written over it; `project_knowledge.py show` says what it holds")
    return out


def record(root, *, key, environment, element, state, scope, value, words, source, story, by, where="", task_root=None) -> tuple:
    """`(row, problem, created)`: ONE fact put in the registry, with the person's words whole.

    Under the lock it LOADS, checks (`record_problems`, `_refuse_no_trace`), numbers (`next_id`) and writes, so two stories never
    lose a row. Refused, nothing written, `row` None and `problem` says why and the door. The same live state AND value for the same
    subject again is the existing row with `created` False (a changed `value`, e.g. `sign_in`, is a new row). A busy lock raises `TimeoutError` (the CLI exits 2: run it again)."""
    root = Path(root)
    with lock(root):
        rows, load_problem = load(root)
        problems = record_problems(key, environment, element, state, scope, words, source, by, load_problem, value)
        if problems:
            return None, "; ".join(problems), False
        reason = _refuse_no_trace(task_root)
        if reason:
            return None, reason, False
        held = _latest(rows, key, environment, element)
        if held is not None and held.get("state") == state and held.get("value") == value:     # a changed value is the person's new word
            return held, "", False
        row = {"id": ER.next_id(rows, ID_PREFIX), "key": key, "environment": str(environment or ""), "element": str(element).strip(),
               "state": state, "scope": scope, "value": value,
               "provenance": {"source": source, "words": str(words or "").strip(), "story": str(story or ""), "by": by,
                              "where": " ".join(str(where or "").split())[:160]},
               "at": ER.now_iso()}
        problem = ER.write_rows(record_path(root), LIST_KEY, SCHEMA_VERSION, rows + [row], RECORD_REL)
        return (None, problem, False) if problem else (row, "", True)


def revoke(root, pk_id, words) -> tuple:
    """`(row, problem)`: take one row back, under the same lock as `record`. The row stays, with `revoked_at` and the words said now.
    An unknown id, an id already taken back, empty words and an unreadable registry are refused with the door (`show`)."""
    with lock(Path(root)):
        return ER.revoke_row(record_path(root), LIST_KEY, SCHEMA_VERSION, pk_id, words, "`project_knowledge.py show`",
                             noun="fact", label=RECORD_REL)


# --- readers for the stages --------------------------------------------------------------------------------------------

def story_roles(task_root) -> tuple:
    """`(roles, reason)`: the roles the S3 strategist named in the optional handoff section `product_roles`, as
    `[{"role", "sign_in", "where"}]`. PURE; never raises. A row whose `role` is empty or a template placeholder is SKIPPED (a
    placeholder never becomes a noticed role); a `sign_in` that is a placeholder or not `account` / `none` reads as `account`
    (toward asking); a placeholder `where` reads as "". No form, an unreadable one, no section, `[]` and placeholder rows only all
    give `[]`; `reason` is "" except for a form that could not be read."""
    try:
        import brief_pack
        import handoff
        relative = brief_pack.last_accepted_form(Path(task_root), "S3", "qa-test-strategist")
        if not relative:
            return [], ""
        try:
            text = (Path(task_root) / relative).read_text(encoding="utf-8-sig")
        except OSError as exc:
            return [], f"the strategist's form {relative} cannot be read ({exc.strerror or type(exc).__name__})"
        data = handoff.parse(text).data
        rows = data.get("product_roles") if isinstance(data, dict) else None
        out = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("role"), str) or handoff.is_placeholder(row.get("role")):
                continue
            sign_in = str(row.get("sign_in") or "").strip()
            where = row.get("where")
            out.append({"role": row["role"].strip(), "sign_in": sign_in if sign_in in SIGN_INS else "account",
                        "where": "" if handoff.is_placeholder(where) else " ".join(str(where).split())})
        return out, ""
    except Exception as exc:
        return [], f"the strategist's form could not be read ({type(exc).__name__})"


def notice_from_handoff(root, task_root, story) -> list:
    """The ids of the rows written: ONE `noticed_unconfirmed` row per role the strategist named in `product_roles` that the roster
    does not hold (`known` or legacy by form) and the person has not turned down (`not_needed`). Idempotent (a role already noticed
    is the existing row); a `no_trace` story, an absent form, `[]` and placeholder rows write nothing. Never raises: a failure is one
    stderr line and nothing more, the gate is still shown. `noticed` is never `known`: the person confirms it at gate A."""
    written = []
    try:
        roles, reason = story_roles(task_root)
        if reason:
            print(f"project_knowledge: {reason}", file=sys.stderr)
        if not roles:
            return written
        refused = _refuse_no_trace(task_root)
        if refused:                                             # one line for the story, not one per role
            print(f"project_knowledge: noticed roles were not recorded ({refused})", file=sys.stderr)
            return written
        held = roster(root, None, "")
        have = {_form(ROLES_KEY, e["role"]) for e in held["elements"] if e.get("state") == KNOWN}
        have |= {_form(ROLES_KEY, e["role"]) for e in held["removed"]}
        for item in roles:
            if _form(ROLES_KEY, item["role"]) in have:
                continue
            row, problem, created = record(root, key=ROLES_KEY, environment="", element=item["role"], state=NOTICED, scope="project",
                                           value={"sign_in": item["sign_in"]}, words="", source="role", story=story, by="driver",
                                           where=item["where"], task_root=task_root)
            if row is None:
                print(f"project_knowledge: the role {item['role']!r} the strategist named was not recorded as noticed ({problem})",
                      file=sys.stderr)
            elif created:
                written.append(row["id"])
    except Exception as exc:
        print(f"project_knowledge: noticed roles were not recorded ({type(exc).__name__}: {str(exc)[:120]})", file=sys.stderr)
    return written


def acting_line(rows) -> str:
    """The ONE note a packet carries for accounts the person gave in an earlier story, or "" when there are none. `rows` are
    registry rows of `environments.credentials_by_role`."""
    parts = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        given = " ".join(x for x in ((f"in {provenance['story']}" if provenance.get("story") else ""),
                                     (f"on {str(row['at'])[:10]}" if row.get("at") else "")) if x)
        parts.append(f"the account of \"{row.get('element')}\" on \"{row.get('environment')}\"" + (f" (given {given})" if given else ""))
    if not parts:
        return ""
    return "Acting on your earlier answers: " + "; ".join(parts) + ". To change it, say so."


# --- the command line (the conductor's) --------------------------------------------------------------------------------

def _fail(message: str) -> int:
    print(f"project_knowledge: {message}", file=sys.stderr)
    return 2


def _words(ns, command: str) -> tuple:
    """`(words, refusal)`: the person's words from `--words-file`, read ONCE, before any file is touched (the one reader of
    environment_record, named for this script's door text)."""
    return ER._words(ns, command, "project_knowledge.py")


def _context(task: str) -> tuple:
    """`(project root, story folder, config, the story's id, problem)` from `--task`; a story that is not there is a problem, not a raise."""
    try:
        import hooklib
        import runtime_paths
        task_root = hooklib.artifacts_dir(task)
        if not task_root.is_dir():
            return None, None, {}, "", (f"there is no story `{task}` in this project, so nothing was recorded; pass the id of the "
                                        "story that is running as --task")
        root = runtime_paths.project_for_task(task_root)
    except ValueError as exc:
        return None, None, {}, "", f"the story `{task}` cannot be placed in a project ({str(exc)[:160]}); nothing was recorded"
    try:
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pipeline = {}
    story = str(pipeline.get("ticket") or task) if isinstance(pipeline, dict) else task
    return root, task_root, _config(root, None), story, ""


def _verb(row, created) -> str:
    return f"recorded ({row['id']})" if created else f"already recorded ({row['id']})"


def _write_prologue(ns, command: str) -> tuple:
    """`((words, root, task_root, cfg, story), refusal)`: the common start of a command that writes - the person's words, the
    story's place, and the no-trace refusal, in that order; the first thing wrong is the refusal text, nothing is written."""
    words, refusal = _words(ns, command)
    if refusal:
        return None, refusal
    root, task_root, cfg, story, problem = _context(ns.task)
    if problem:
        return None, problem
    reason = _refuse_no_trace(task_root)
    if reason:
        return None, reason
    return (words, root, task_root, cfg, story), ""


def cmd_account(ns) -> int:
    got, refusal = _write_prologue(ns, "account --task <T> --role <role> --user-key <NAME> --secret-key <NAME>")
    if refusal:
        return _fail(refusal)
    words, root, task_root, cfg, story = got
    import stand_gaps
    stand = stand_gaps.stand_name(task_root)
    if stand == PLACEHOLDER_STAND:
        if _stands(cfg):
            return _fail("the story has no chosen stand; name it first (the stands: "
                         + ", ".join(f"`{e.get('name')}`" for e in _stands(cfg)) + "); nothing was recorded")
        stand = ""                  # no `environments[]` row at all: the account writer says so, with its own door
    import project_decisions as PD
    try:
        result = PD.record_stand_account(root, stand=stand, role=ns.role, user_key=ns.user_key, secret_key=ns.secret_key,
                                         words=words, replace=ns.replace)
    except ValueError as exc:
        return _fail(f"account refused - {exc}")
    except TimeoutError as exc:
        import event_store as ES
        if isinstance(exc.__cause__, ES.LockBroken):     # a lock that cannot be made is not another writer: its own sentence
            return _fail(f"account refused - {exc}")
        return _fail(f"the registry is busy; run the same command again ({str(exc)[:120]})")
    where = f"{result['role']} on {result['stand']}"
    row, problem, created = record(root, key=ACCOUNTS_KEY, environment=result["stand"], element=result["role"], state=KNOWN,
                                   scope="stand", value=None, words=words, source="person", story=story, by="conductor",
                                   task_root=task_root)
    if row is None:
        return _fail(f"{where}: the account is in the project's settings, but its record was not written ({problem}); "
                      "run the same command again once that is fixed")
    line = f"{where}: " + (f"already recorded ({row['id']})" if result.get("unchanged") else
                           f"recorded ({result.get('decision', '-')}, {row['id']})")
    if state(root, ROLES_KEY, "", result["role"])["state"] != KNOWN:
        role_row, problem, _ = record(root, key=ROLES_KEY, environment="", element=result["role"], state=KNOWN, scope="project",
                                      value={"sign_in": "account"}, words=words, source="person", story=story, by="conductor",
                                      task_root=task_root)
        line += f"; the role is a product role now ({role_row['id']})" if role_row else f"; the role itself was not recorded ({problem})"
    print(line)
    return 0


def cmd_role(ns) -> int:
    words, refusal = _words(ns, "role --task <T> --role <role> --state <known|not_needed>")
    if refusal:
        return _fail(refusal)
    root, task_root, _cfg, story, problem = _context(ns.task)
    if problem:
        return _fail(problem)
    sign_in = ns.sign_in
    if ns.state == KNOWN and not sign_in:
        held = state(root, ROLES_KEY, "", ns.role)["row"]
        value = held.get("value") if isinstance(held, dict) else None
        sign_in = value.get("sign_in") if isinstance(value, dict) and value.get("sign_in") in SIGN_INS else "account"
    row, problem, created = record(root, key=ROLES_KEY, environment="", element=ns.role, state=ns.state, scope="project",
                                   value={"sign_in": sign_in} if ns.state == KNOWN else None, words=words, source="person",
                                   story=story, by="conductor", task_root=task_root)
    if row is None:
        return _fail(problem)
    print(f"{ns.role}: {ns.state} " + _verb(row, created))
    return 0


def cmd_revoke(ns) -> int:
    got, refusal = _write_prologue(ns, "revoke --task <T> --id <PK-n>")
    if refusal:
        return _fail(refusal)
    words, root = got[0], got[1]
    row, problem = revoke(root, ns.id, words)
    if row is None:
        return _fail(problem)
    print(f"{row['id']} is taken back ({row.get('key')} {row.get('element')}): it is asked again where it is needed; an account "
          "value in the project's settings stays until it is changed with `account --replace` or by hand.")
    return 0


def cmd_side(ns) -> int:
    """One fact about a side, on the person's words: how a stand holds it (`--reality`), whether this team's stories deliver it
    (`--deliverable yes|no`, project-wide), or that a stand runs its old version (`--reference`). The stand is `--stand`, else the
    story's chosen stand. A story that leaves no trace refuses it with the door (the answer stays in that story)."""
    got, refusal = _write_prologue(ns, "side --task <T> --name <side> (--reality <word> | --deliverable yes|no | --reference) --words-file <file>")
    if refusal:
        return _fail(refusal)
    words, root, task_root, cfg, story = got
    if ns.deliverable is not None:
        settles = ""
        if ns.settles_by_file:
            try:
                settles = " ".join(Path(ns.settles_by_file).read_text(encoding="utf-8-sig").split())
            except (OSError, ValueError) as exc:
                return _fail(f"the file of who makes the side real, {ns.settles_by_file}, cannot be read ({type(exc).__name__}); nothing was recorded")
        key, environment, scope, value = SIDES_KEY, "", "project", {"deliverable": ns.deliverable == "yes", "settles_by": settles}
    else:
        environment = ns.stand or ""
        if not environment:
            import stand_gaps
            environment = stand_gaps.stand_name(task_root)
            if environment == PLACEHOLDER_STAND:
                names = ", ".join(f"`{e.get('name')}`" for e in _stands(cfg))
                return _fail("no stand is named and the story has none chosen; pass --stand <name>"
                             + (f" (the stands: {names})" if names else "") + "; nothing was recorded")
        key, scope = (STAND_SIDES_KEY, "stand") if ns.reality else (REFERENCE_KEY, "stand")
        value = {"reality": ns.reality} if ns.reality else {"reference": True}
    row, problem, created = record(root, key=key, environment=environment, element=ns.name, state=KNOWN, scope=scope, value=value,
                                   words=words, source="person", story=story, by="conductor", task_root=task_root)
    if row is None:
        return _fail(problem)
    print(f"{ns.name}{' on ' + environment if environment else ''}: {key} " + _verb(row, created))
    if ns.deliverable is not None and ns.stand:
        # critic t-2475 N3: `--deliverable` is the project's fact; a `--stand` beside it was dropped, and the person is told so
        print(f"note: --stand {ns.stand} was not used: whether this team delivers {ns.name} holds for the whole project, not for one stand.")
    return 0


def show_lines(rows) -> list:
    out = []
    for row in rows:
        flag = f"taken back {str(row['revoked_at'])[:10]}" if row.get("revoked_at") else "live"
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        words = " ".join(str(provenance.get("words") or "").split())[:160]
        where = f" on {row['environment']}" if row.get("environment") else ""
        out.append(f"{row.get('id')} ({flag}): {row.get('key')} {row.get('element')}{where} [{row.get('state')}, {row.get('scope')}] - "
                   f"recorded {str(row.get('at') or '')[:10]}{' in ' + str(provenance['story']) if provenance.get('story') else ''}"
                   f" by {provenance.get('source') or '?'}: \"{words}\"")
    return out


def cmd_show(ns) -> int:
    import hooklib
    rows, problem = load(hooklib.project_root())
    if ns.json:
        print(json.dumps({LIST_KEY: rows, "problem": problem}, indent=2, ensure_ascii=False))
    elif problem:
        print(problem)
    elif not rows:
        print("no project knowledge is recorded.")
    else:
        print("\n".join(show_lines(rows)))
    return 1 if problem else 0


def main(argv=None) -> int:
    ap, sub = ER.command_parser("The project's answer registry: what a person told the factory once, with their words.", cmd_show)
    acc = sub.add_parser("account")
    acc.add_argument("--task", required=True)
    acc.add_argument("--role", required=True)
    acc.add_argument("--user-key", dest="user_key", required=True)
    acc.add_argument("--secret-key", dest="secret_key", required=True)
    acc.add_argument("--replace", action="store_true")
    acc.add_argument("--words-file", dest="words_file", default=None)
    acc.set_defaults(fn=cmd_account)
    role = sub.add_parser("role")
    role.add_argument("--task", required=True)
    role.add_argument("--role", required=True)
    role.add_argument("--state", required=True, choices=(KNOWN, NOT_NEEDED))
    role.add_argument("--sign-in", dest="sign_in", choices=SIGN_INS, default=None)
    role.add_argument("--words-file", dest="words_file", default=None)
    role.set_defaults(fn=cmd_role)
    rev = sub.add_parser("revoke")
    rev.add_argument("--task", required=True)
    rev.add_argument("--id", required=True)
    rev.add_argument("--words-file", dest="words_file", default=None)
    rev.set_defaults(fn=cmd_revoke)
    side = sub.add_parser("side")
    side.add_argument("--task", required=True)
    side.add_argument("--name", required=True)
    side.add_argument("--stand", default=None)
    mode = side.add_mutually_exclusive_group(required=True)
    mode.add_argument("--reality")                  # the words are checked against references/side-realities.json by `record`
    mode.add_argument("--deliverable", choices=("yes", "no"))
    mode.add_argument("--reference", action="store_true")
    side.add_argument("--settles-by-file", dest="settles_by_file", default=None)
    side.add_argument("--words-file", dest="words_file", default=None)
    side.set_defaults(fn=cmd_side)
    ns = ap.parse_args(argv)
    if getattr(ns, "settles_by_file", None) and getattr(ns, "deliverable", None) is None:
        ap.error("--settles-by-file goes with --deliverable only")
    try:
        return ns.fn(ns)
    except TimeoutError as exc:     # a busy lock: nothing was written; the same command again
        return _fail(str(exc))


if __name__ == "__main__":
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    sys.exit(main())
