#!/usr/bin/env python3
"""walk_pool.py - an account per lane and the records a lane may change (t-2174 TR3-10 Part C, AR-13/14/15/28).

Code here READS and COUNTS (AR-29): which handles a lane may sign in as, which free record of a kind a lane is given. It never decides
whether a step changes a record (the walker's claim does) and never reads a value of an env key: only key NAMES leave this module.
Every function returns `(result, notes)` with `notes` a list of plain strings; nothing is printed (the caller prints, once).

- `lane_handles(task_root, case, key)`   the accounts of one lane (`Driver.walk_actors`, the same logic: Part D makes the driver call it)
- `pool_of(task_root, cfg, case, part, supply, doubts)`   the handles one key part may be signed in as
- `obtain_roles_of(supply, stand_roles)`   the roles the person said a user may sign up as, those the stand lists
- `assign_lanes(lanes, pools, obtain_roles, stand_may_change, keys)`   `{lane n: {part: handle}}`, round robin, deterministic
- `assign_entities(lanes, requests, pools, task_root, walks, may)`   the free record of an exclusive kind a lane is given, written `in_use`
- `short_parts(assignment, pools, supply, walkers)`   the parts where lanes wait for one handle (the way question reads it)

`lanes` is what `Driver.manual_lane_plan` returns in `plan["blocks"]`: a list of lanes, a lane a list of case ids; a lane's NUMBER is its
position in that list counted from 1 (the `[L<n>]` of the console) and its key is `keys[lane[0]]` (`controller.lane_keys`, the one reader:
`{case: key}`, the shape `controller.walk_lanes` takes).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_preflight as GP  # noqa: E402
import manual_capture as MC  # noqa: E402
import walk_session as WS  # noqa: E402

GUEST = WS.GUEST                    # one definition: the guest actor of the walk
GUEST_PREFIX = "guest#"             # a guest lane's handle: one per lane, never shared (owner's word F4); it opens as `guest`
OBTAIN_PREFIX = "obtain:"           # `obtain:<role>#<lane n>`: the lane's walker makes its own user; it opens as `guest` (C.8)
CREATE_PREFIX = "create:"           # `create:<kind>#<lane n>`: the lane's walker makes its own record of the kind
MAY_VALUES = ("existing_only", "create", "create_and_delete")      # `config_contract.walk_supply` `data.may`
_cut = WS.cut_text                  # one definition of the 200-character cut of every text (an instance, a kind or a handle stays whole in data)


class Pool(list):
    """The handles one key part may be signed in as, the base account first when it is usable; `role` is the stand's role the part
    resolves to (`obtain_roles` is compared with it); `limit` is the project's `limit_by_role` for it (0: none): at most that many lanes
    of the role run at once, pool handles and obtain handles together (`assign_lanes`)."""

    def __init__(self, handles=(), role="", limit=0):
        super().__init__(handles)
        self.role = role
        self.limit = limit


# --------------------------------------------------------------------------------------------
# one lane's accounts: the body of `Driver.walk_actors`, lifted (AR-15)
# --------------------------------------------------------------------------------------------

def walk_env_pair(stand, value: str) -> tuple:
    """`(role, why)` for an account named by ONE key `value` (the login key of `env:<key>`): the role of `stand`'s `credentials_by_role`
    whose note names exactly two keys with `value` first - read by the readers `--as` uses (`MC._roles_of`, `GP.account_keys`,
    `GP.account_role`). Exactly one such role that `--as` can reach: that role, `why` empty. None, or two or more (no guess; both are
    named), or a stand with no records: `role` is "" and `why` is the reason in the story's words. ERROR DIRECTION: a doubt is never
    another account. (`Driver.walk_env_pair`, lifted; Part D makes the driver call this one.)"""
    import config_contract as CC
    roles = MC._roles_of(stand)
    base = f"for this case's account the factory does not know the password: named by one key {value}"
    found = [r for r in roles if isinstance(r, str) and (k := GP.account_keys(roles[r])) and len(k) == 2 and k[0] == value]
    if len(found) > 1:
        return "", f"{base}; the stand lists {len(found)} roles with this login key ({', '.join(f'`{r}`' for r in found)}) and the factory does not guess"
    if not found:
        return "", base
    if CC.reserved_role(found[0]) or GP.account_role(roles, found[0]) != found[0]:
        return "", f"{base}; the stand's role `{found[0]}` holds the pair but `--as` cannot reach it by that name"
    return found[0], ""


def _stand_of(cfg) -> dict:
    return next((e for e in (cfg.get("environments") if isinstance(cfg, dict) else None) or [] if isinstance(e, dict)), {})


def _part_handle(roles, stand, part, case) -> tuple:
    """`(handle, why)` of ONE part `<kind>:<value>` of a many-account key, as `walk_actors` resolves each part of one: the stand's `default`,
    an `env:` login key found in the stand's records, or a `stand_account` role whose note names two keys. `handle` is "" with the reason
    when no account a machine can sign in as is named."""
    kind, _, value = part.partition(":")
    real = GP.account_role(roles, value) if kind == "stand_account" else None
    if kind == "stand_account" and value == "default":
        return "default", ""
    if kind == "env":         # B5: a login key inside a many-account key is found like a lone one
        return walk_env_pair(stand, value)
    if real is not None and len(GP.account_keys(roles[real])) == 2:
        return real, ""
    return "", f"the account {part} of {case} is not one a machine can sign in as (the stand lists no such role with a note naming two keys)"


def lane_handles(task_root, case: str, key: str) -> tuple:
    """`([handle, ...], why)` for the account set `key` of a lane (`lane_keys`), at most `walk_session.data()['max_actors']` handles in
    the key's order: ONE account is `manual_capture.auto_actor`'s (its refusals and doors, unchanged); two are each resolved like
    `auto_actor` resolves its one - a `stand_account` role whose note names two keys, or `default` - so `--actor` and `--actor2` are
    the lane's two accounts (the walker acts as either with `--as`). `why` is non-empty when the lane cannot walk: more accounts than
    a walk holds, or an account a machine cannot sign in as (today's road, with the reason). Same logic as `Driver.walk_actors`
    (test `lane_handles_same_as_walk_actors`); Part D's first step makes `walk_actors` call this."""
    parts = [p for p in key.split("+") if p]
    if not parts:
        return [], f"the accounts of {case} could not be read from its request"
    try:
        cfg, _root = MC.load_config(task_root)
    except ValueError:
        cfg = {}            # no stand records at all equals no pair (a one-account lane then names the missing records)
    stand = _stand_of(cfg)
    if len(parts) == 1 and parts[0].startswith("env:"):
        # TR1-4: an account named by ONE key (`env:<login key>`) is found in the stand's records by its login key (the reader `--as` uses)
        role, why = walk_env_pair(stand, parts[0].partition(":")[2])
        return ([role], "") if role else ([], why)
    if len(parts) == 1:
        try:
            actor = MC.auto_actor(cfg, stand, task_root, case) or ""
        except ValueError:      # B5: `auto_actor` refuses what a machine cannot sign in as; that is a reason, not the old road
            actor = ""
        return ([actor], "") if actor else ([], f"the account of {case} ({key}) is not one a machine can sign in as")
    limit = int(WS.data()["max_actors"])
    if len(parts) > limit:
        return [], f"the lane names {len(parts)} accounts ({key}); a walk holds at most {limit}"
    roles, handles = MC._roles_of(stand), []
    for part in parts:
        handle, why = _part_handle(roles, stand, part, case)
        if not handle:
            return [], why
        if handle not in handles:       # two parts that resolve to one role are one account
            handles.append(handle)
    return handles, ""


# --------------------------------------------------------------------------------------------
# the pool of one key part
# --------------------------------------------------------------------------------------------

def _by_role(mapping, role):
    """The value of `mapping` (`supply` keys are a role or `default`) for the stand's `role`: the exact key, else the one key the gate's
    role reader (`GP.account_role`) names; a doubt is None."""
    if not isinstance(mapping, dict) or not role:
        return None
    if role in mapping:
        return mapping[role]
    real = GP.account_role(mapping, role) if role != "default" else None
    return mapping[real] if real is not None else None


def _env_key_names(cfg, project_root) -> tuple:
    """`(set of key NAMES set in the env files the recorder reads, state)`: the recorder's own reader (`MC._env_files_state`, the one
    `read_login` uses) over the files `GP.configured_env_files` names. Only names leave this function; a value never does."""
    env = cfg.get("environment") if isinstance(cfg, dict) and isinstance(cfg.get("environment"), dict) else {}
    files = GP.configured_env_files(env, project_root)[0]
    values, state = MC._env_files_state(files)
    return set(values), state


def pool_of(task_root, cfg, case: str, part: str, supply, doubts) -> tuple:
    """`(Pool, notes)`: the handles key part `part` may be signed in as. The BASE (the stand's role, or `default`) first, then the
    `supply.accounts.more_accounts` entries of its role - each kept only when it resolves like `--as` does (no value read), both its
    key NAMES are set in the env files the recorder reads, it is not the same key pair as one already in the pool (`pool_dedupes_same_pair`)
    and it has an `ok` probe row of gate A for the stand's login recipe - minus every handle in `doubts` (the reader's return,
    `manual_capture.account_doubts`: `(handles, problem)`), capped at `limit_by_role[role]`. The base is never dropped for a missing probe
    row (today's road asks none: the pool never makes the base worse) and, when every handle is doubted, it stays with a note: a doubt is a
    report line, not a refusal. An unreadable doubts store: `[base]` only, with a note. A guest part (`""`) is `[guest]`: `assign_lanes`
    gives each guest lane its own `guest#<lane n>`. A part with no base account is an empty pool with the reason."""
    notes: list = []
    if not part:
        return Pool([GUEST]), notes
    stand = _stand_of(cfg)
    roles = MC._roles_of(stand)
    base, why = _part_handle(roles, stand, part, case)
    if not base:
        return Pool(), [why]
    accounts = (supply or {}).get("accounts") if isinstance(supply, dict) else None
    accounts = accounts if isinstance(accounts, dict) else {}
    limit = _by_role(accounts.get("limit_by_role"), base)
    limit = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 1 else 0
    doubted, problem = doubts if isinstance(doubts, tuple) and len(doubts) == 2 else (doubts or set(), "")
    if problem:
        return Pool([base], base, limit), [f"the doubts of this story's accounts cannot be read ({_cut(problem)}); {part} keeps `{_cut(base)}` only"]
    extras = [str(h) for h in _by_role(accounts.get("more_accounts"), base) or []]
    names, kept = None, []
    try:
        pairs = {tuple(MC.resolve_actor(cfg, stand, base, task_root)[:2]): base}
    except ValueError:
        pairs = {}
    if extras:
        try:
            names, state = _env_key_names(cfg, MC.load_config(task_root)[1])
            if state != "ok":
                names = None
                notes.append(f"the env files of the stand cannot be read ({state}); the extra accounts of `{_cut(base)}` were left out")
        except ValueError as exc:
            notes.append(f"the project's config cannot be read ({_cut(' '.join(str(exc).split()))}); the extra accounts of `{_cut(base)}` were left out")
    for handle in extras if names is not None else []:
        try:
            user, secret = MC.resolve_actor(cfg, stand, handle, task_root)[:2]
        except ValueError:
            notes.append(f"the extra account `{_cut(handle)}` is not a form `--as` takes; it was left out")
            continue
        if (user, secret) in pairs:
            notes.append(f"the extra account `{_cut(handle)}` is the same key pair as `{_cut(pairs[(user, secret)])}`; it counts once")
            continue
        absent = [k for k in (user, secret) if k not in names]
        if absent:
            notes.append(f"the extra account `{_cut(handle)}` was left out: {', '.join(absent)} not set in the env files")
            continue
        pairs[(user, secret)] = handle
        kept.append(handle)
    pool = [h for h in [base, *kept] if h not in doubted]
    if kept:
        try:
            recipe = MC.login_recipe(cfg, MC.spec(), "ui")
        except ValueError:
            recipe = {}
        proven = [h for h in pool if h == base or MC.sign_in_refusal(task_root, h, recipe) == ""]
        for h in pool:
            if h not in proven:
                notes.append(f"the extra account `{_cut(h)}` has no `ok` sign-in probe row for this login; it was left out")
        pool = proven
    if not pool:
        notes.append(f"every account of {part} is doubted by this story; `{_cut(base)}` is kept: nothing better exists")
        pool = [base]
    if limit and len(pool) > limit:
        notes.append(f"{part} is cut to {limit} account(s) by the project's limit for `{_cut(base)}`")
        pool = pool[:limit]
    return Pool(pool, base, limit), notes


def obtain_roles_of(supply, stand_roles) -> tuple:
    """`(roles, notes)`: `supply.accounts.self_sign_up_roles` as the stand's real role names (`default` stays), a role the stand does not
    list dropped with a note (B.4: the reader judged shape only; this is where the stand is known). `stand_roles` is the stand's
    `credentials_by_role` (or None)."""
    notes: list = []
    accounts = (supply or {}).get("accounts") if isinstance(supply, dict) else None
    listed = (accounts or {}).get("self_sign_up_roles") if isinstance(accounts, dict) else None
    roles: list = []
    for role in listed if isinstance(listed, list) else []:
        real = role if role == "default" else GP.account_role(stand_roles if isinstance(stand_roles, dict) else {}, role)
        if real is None:
            notes.append(f"the role `{_cut(role)}` the person said a user may sign up as is not a role this stand lists; it was left out")
        elif real not in roles:
            roles.append(real)
    return roles, notes


# --------------------------------------------------------------------------------------------
# lanes -> handles
# --------------------------------------------------------------------------------------------

def open_as(handle) -> str:
    """What `walk_session.py open --actor` takes for an assigned handle: a guest or an obtain handle opens as `guest` (C.8: an `obtain:`
    handle is never a value for `--as`; the lane signs in only with `created:` after its walker made the user)."""
    text = str(handle)
    return GUEST if text == GUEST or text.startswith((GUEST_PREFIX, OBTAIN_PREFIX)) else text


def assign_lanes(lanes, pools, obtain_roles, stand_may_change, keys) -> tuple:
    """`({lane n: {part: handle}}, notes)`, deterministic: per key part, the lanes that carry it in plan order take `pool[i % len(pool)]`; when
    the part's role (`Pool.role`) is in `obtain_roles` AND the stand may be changed, lanes past `len(pool)` take `obtain:<role>#<lane n>`
    instead - but never more lanes of the role than its `Pool.limit` (`limit_by_role`, 0 = none): pool and obtain handles count together, the
    lanes past the cap take a pool handle in turn. A two-part key takes a handle per part, each from its own part's round (the same pass). A guest lane (`""`) takes
    `guest#<lane n>`. ERROR DIRECTION: a lane may wait (lanes whose handle sets meet hold a common `account:<handle>`, so they run in
    turn); no handle is ever given to two lanes that could run at once - guests and obtain handles are one per lane. A part with no pool
    gets NO handle and a note (never a guessed account: the caller keeps today's refusal). `keys` is `{case: key}` (`lane_keys`)."""
    notes: list = []
    out: dict = {}
    carriers: dict = {}
    for n, lane in enumerate(lanes or (), 1):
        cases = [str(c) for c in lane or ()]
        key = (keys or {}).get(cases[0]) if cases else None
        if not isinstance(key, str):
            notes.append(f"lane {n} has no readable account key; it gets no handle")
            continue
        parts = [p for p in key.split("+") if p]
        out[n] = {} if parts else {"": f"{GUEST_PREFIX}{n}"}
        for part in parts:
            carriers.setdefault(part, []).append(n)
    obtain = list(obtain_roles or ())
    given: dict = {}        # role -> the pool handles already given to a lane
    active: dict = {}       # R2: role -> the lanes that run at once on a handle of their own (a pool handle not shared, or an obtain handle)
    for part, numbers in carriers.items():
        pool = pools.get(part) if isinstance(pools, dict) else None
        handles = [str(h) for h in pool or ()]
        if not handles:
            notes.append(f"the account {_cut(part)} has no handle to give; its lanes keep today's refusal")
            continue
        role = str(getattr(pool, "role", "") or "")
        obtains = bool(role) and role in obtain and bool(stand_may_change)
        cap = int(getattr(pool, "limit", 0) or 0)       # N1/R2: `limit_by_role` caps the lanes of the ROLE, across every part of it, obtain included
        mine = active.setdefault(role, set())
        used = given.setdefault(role, set())
        for i, n in enumerate(numbers):
            if i < len(handles):
                out[n][part] = handles[i]
                if handles[i] not in used:      # a handle another part already gave away is shared: that lane waits, it is not a lane at once
                    mine.add(n)
                    used.add(handles[i])
            elif obtains and (not cap or len(mine) < cap):
                out[n][part] = f"{OBTAIN_PREFIX}{role}#{n}"
                mine.add(n)
            else:
                out[n][part] = handles[i % len(handles)]
    return out, notes


def short_parts(assignment, pools, supply, walkers) -> tuple:
    """`([(part, lanes waiting, pool size)], notes)` for the parts where lanes share a handle (so some lane waits), `walkers` is above 1, the
    person has not answered the accounts question (`supply.accounts.known` False) and no obtain handle was given (an obtain lane has its own
    user, so it shares nothing). The way question reads it (D). `assignment` is `assign_lanes`'s answer."""
    accounts = (supply or {}).get("accounts") if isinstance(supply, dict) else None
    if not isinstance(walkers, int) or isinstance(walkers, bool) or walkers < 2 or (isinstance(accounts, dict) and accounts.get("known")):
        return [], []
    given: dict = {}
    for _n, parts in (assignment or {}).items():
        for part, handle in parts.items():
            if part:
                given.setdefault(part, []).append(handle)
    out = []
    for part, handles in given.items():
        if any(h.startswith(OBTAIN_PREFIX) for h in handles):
            continue
        waiting = len(handles) - len(set(handles))
        if waiting:
            out.append((part, waiting, len((pools or {}).get(part) or set(handles))))
    return out, []


# --------------------------------------------------------------------------------------------
# lanes -> records (the one writer of `in_use` claims besides the walker's own `claim`)
# --------------------------------------------------------------------------------------------

def _kind_key(kind) -> str:
    return str(kind).strip().casefold()


def _needs(lanes, requests) -> dict:
    """`{lane n: {item: [(kind key, kind as written)]}}`: the exclusive kinds the S3 plan names (`walk_data` of the item's request), once
    per kind per item. An item with no `walk_data`, an empty one or no exclusive entry has no need (no constraint, today's behaviour)."""
    out: dict = {}
    for n, lane in enumerate(lanes or (), 1):
        for item in (str(c) for c in lane or ()):
            request = (requests or {}).get(item)
            entries = request.get("walk_data") if isinstance(request, dict) else None
            wanted: list = []
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict) and entry.get("exclusive") is True and isinstance(entry.get("kind"), str) and entry["kind"].strip():
                    if _kind_key(entry["kind"]) not in [k for k, _t in wanted]:
                        wanted.append((_kind_key(entry["kind"]), entry["kind"].strip()))
            if wanted:
                out.setdefault(n, {})[item] = wanted
    return out


def _state_of(rows, held_walks) -> tuple:
    """`(busy, unusable, whole)` from the claim rows, each read by `walk_session.claim_state` (the one rule; `held_walks` is
    `walk_session.held_walk_ids`): the (kind, instance) pairs held (a live walk, or a walk assigned and not opened yet), the pairs that
    read `dirty`, and the kinds whose whole list a held walk holds."""
    busy, unusable, whole = set(), set(), set()
    for row in rows:
        kind, held = WS.fold_kind(row["kind"]), str(row["instance"])
        state = WS.claim_state(row, held_walks)
        if state == "held":
            (whole.add(kind) if held == WS.CLAIM_ALL else busy.add((kind, held)))
        elif state == "dirty":
            unusable.add((kind, held))
    return busy, unusable, whole


def _plan_entities(rows, held_walks, needs, pools, walks, may, now, notes) -> tuple:
    """`(plan, new rows)`: lane by lane in plan order, ALL the entries of the lane or none (an item's entries are given together or none, and a
    lane walks its items in one session, so a lane that cannot be given them all is given none). A kind's instance is the first of
    `existing` that is neither held by a live walk, nor dirty, nor taken by an earlier lane in this pass; a lane takes ONE per kind for all
    its items. None free: `create:<kind>#<lane n>` when the answer allows (`may`) and the kind has a `create_request`; else `wait` when
    some instance will be free again, `alone` when none can be. A kind with no pool is not constrained (the walker claims what it picks)."""
    busy, unusable, whole = _state_of(rows, held_walks)
    taken: set = set()
    plan: dict = {}
    added: list = []
    for n, items in needs.items():
        picks: dict = {}
        failure = ""
        for item, wanted in items.items():
            for key, text in wanted:
                pool = pools.get(key) if isinstance(pools, dict) else None
                if not isinstance(pool, dict) or key in picks:
                    continue
                folded = WS.fold_kind(key)
                listed = [str(i) for i in pool.get("existing") or []]
                existing = [i for i in listed if i.strip() not in ("", WS.CLAIM_ALL)]
                if len(existing) < len(listed) and (note := f"the {_cut(text)} list holds an id that is `*` or empty; it was skipped (it would read as a claim on the whole list)") not in notes:
                    notes.append(note)
                free = [i for i in existing if (folded, i) not in unusable and (folded, i) not in busy and (folded, i) not in taken
                        and folded not in whole and (folded, i) not in {(WS.fold_kind(k), p.get("instance")) for k, p in picks.items()}]
                if free:
                    picks[key] = {"kind": text, "instance": free[0], "how": "existing", "handle": ""}
                elif may in ("create", "create_and_delete") and pool.get("create_request"):
                    pick = {"kind": text, "instance": "", "how": "create", "handle": f"{CREATE_PREFIX}{key}#{n}", "create_request": pool["create_request"]}
                    if may == "create_and_delete" and pool.get("delete_request"):
                        pick["delete_request"] = pool["delete_request"]
                    picks[key] = pick
                else:
                    later = [i for i in existing if (folded, i) not in unusable]
                    failure = "wait" if later else "alone"
                    plan[n] = {"state": failure, "entries": {}, "why": (f"every {_cut(text)} the project listed is held by another lane for now" if failure == "wait"
                                                                    else f"no {_cut(text)} is left that this lane may use: none listed, or all changed and not restored")}
                    break
            if failure:
                break
        if failure:
            continue
        entries = {item: [picks[k] for k, _t in wanted if k in picks] for item, wanted in items.items()}
        entries = {item: found for item, found in entries.items() if found}
        if not entries:
            continue            # no kind of this lane has a pool: not constrained
        walk = walks.get(n)
        if not walk:
            plan[n] = {"state": "alone", "entries": {}, "why": f"lane {n} has no walk id to hold records for"}
            continue
        plan[n] = {"state": "given", "entries": entries, "why": ""}
        for item, found in entries.items():
            for pick in found:
                if pick["how"] == "existing":
                    taken.add((WS.fold_kind(pick["kind"]), pick["instance"]))
                    added.append({"kind": WS.fold_kind(pick["kind"]), "instance": pick["instance"], "walk": str(walk), "item": item,
                                  "state": "in_use", "at": now})
    return plan, added


def assign_entities(lanes, requests, pools, task_root, walks=None, may="existing_only") -> tuple:
    """`({lane n: {"state": given|wait|alone, "entries": {item: [entry]}, "why"}}, notes)`: the records the lanes' S3 plan rows say a lane must
    have for itself (`walk_data` with `exclusive: true`, from `requests` = `{item: request}` as `request.json` carries it). `pools` is
    `supply["data"]["pools"]`, `task_root` the story root (`<T>/state/walk-entities.json`, read by `walk_session.claims_of`, written by
    `walk_session.update_claims` under its lock: one writer), `walks` `{lane n: walk id}` (the dispatch id the instance is held for),
    `may` `supply["data"]["may"]` (before any answer it is `existing_only`: no `create:` assignment, FR-59; the stand's `safe_to_break`
    is not consulted, P13). An entry is `{kind, instance, how: existing|create, handle, [create_request], [delete_request]}`; `existing`
    entries are written `in_use` for the lane's walk in ONE write BEFORE any dispatch (all lanes of the pass, or none). A lane with no
    exclusive kind is not in the answer and the store is not touched. A store that cannot be read, a lock not got or a write that failed:
    no assignment, every lane that needed one is `alone` (AR-28) with the reason in `why`. Entry texts cut at 200 in `entity_lines`."""
    notes: list = []
    may = may if may in MAY_VALUES else "existing_only"
    needs = _needs(lanes, requests)
    if not needs:
        return {}, notes
    walks = dict(walks or {})

    def change(rows):
        # the one reader of who holds a row (`held_walk_ids`: live walks, and walks assigned but not opened yet); a claim of a walk that
        # has a record and is not alive reads dirty
        held = WS.held_walk_ids(task_root, rows)
        plan, added = _plan_entities(rows, held, needs, pools or {}, walks, may, MC._now(), notes)
        return ([*rows, *added] if added else None), plan
    try:
        problem, plan = WS.update_claims(task_root, change)
    except (TimeoutError, OSError) as exc:      # the lock was not got in time, or the write failed: nothing was assumed written
        problem, plan = f"the list of claims could not be used: {_cut(' '.join(str(exc).split()), 300)}", None
    if problem or plan is None:
        why = _cut(problem or "the list of claims could not be used", 300)
        notes.append(f"records were not assigned: {why}")
        return {n: {"state": "alone", "entries": {}, "why": why} for n in needs}, notes
    for n, found in plan.items():
        if found["state"] != "given":
            notes.append(f"lane {n}: {found['state']} - {found['why']}")
    return plan, notes


def entity_lines(entries) -> list:
    """The lines of a lane's prompt for its entries (`{item: [entry]}` of `assign_entities`, one lane): the record it uses only; the record
    it makes with the `create_request`; and, only under `create_and_delete` (the entry carries a `delete_request`), how to remove what it
    made. Under `create` nothing is said about removal. Kind and instance are cut at 200 characters in the text, whole in the entry."""
    lines: list = []
    for item, found in (entries or {}).items():
        for entry in found:
            kind = _cut(entry["kind"])
            if entry["how"] == "existing":
                lines.append(f"{item}: your {kind} is `{_cut(entry['instance'])}`; use only it.")
            else:
                lines.append(f"{item}: make your own {kind} with: {entry['create_request']}; claim it and use only that one.")
                if entry.get("delete_request"):
                    lines.append(f"{item}: when your item is done, remove the record you made with: {entry['delete_request']}")
    return lines
