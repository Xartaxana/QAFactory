#!/usr/bin/env python3
"""walk_session.py - the kept-session server of a manual walk (t-1957 N1a).

One server process per walk keeps ONE recorder browser (one persistent context per actor) open between the role's calls, so a manual
item is walked live with the recorder's full evidence (P26) without a browser start per call. The role drives it with these commands
(every command takes `--task-root <T> --walk <W>`; the walk id W is the dispatch id):

    open    --items i1,i2 --actor <handle|guest> [--actor2 <handle>] [--parent-pid N] [--place case|settle|control|survey] [--env <name>]
            spawn the detached server, wait for it, print ONE JSON line {status, walk, state, signed_in, landed_on, actors, ...}
            `--place case` (default) is the S6 lane: the stand lease is held for the session's life, `idle_s` applies. `settle` and `control`
            are the S7 lanes (t-1991 U0): the lease is taken per request (item, step, look, final, close; at most `request_lease_wait_s`,
            then exit 3 `stand_busy`), `idle_s` does not apply; attempts go under work/evidence/manual/settle-<item>/aN/ (the root of
            `manual_capture.py http|ui --case settle-<item>`) or evidence/control-<item>/aN/
            `--place survey` (FL-1 A) is the first look: the stand lease is held for the session's life (as `case`), `idle_s` applies, a
            request takes no lease of its own, there is no verdict (the item is `R-n` or an element id; attempts go under
            work/evidence/manual/survey-<item>/aN/), the close writes the timing. `--env <name>` walks the environments[] row of that
            exact name (default: the first row) and only that stand's hosts; the record names `place`, `stand`, `profiles` and `attempts`.
            A survey of a project with no profile that fits a UI capture (FL-1 B) has NO browser: `profiles` says `http`, each actor signs in
            once by the HTTP request the project records, and the steps are `http <METHOD> <path|url> [--body-file F]` only (any other word
            is refused whole, exit 2); neither a UI nor an HTTP profile refuses `open` (exit 2, cause `no_reachable_surface`)
    item    --item i [--as <actor>]                     open the item's next attempt aN (a `step` opens it by itself)
    step    --item i [--as <actor>] (--steps-file F | --line "<one step>") [--stop-on <rules>] [--final]
            1..max_batch_steps steps in the recorder's step vocabulary; a call of one step is the SAME call. Stops at the first deviation.
            `http <METHOD> <path|url> [--body-file F]` (FL-1 B) is a step like the others: one request on the walk's stand, sent as the
            actor, stored as one JSON document in the item's attempt; a path is joined to the stand's base_url
    look    --item i [--as <actor>] [--selector S]      store what the page shows (a state file)
    final   --item i [--as <actor>]                     the final snapshot and ONE screenshot
    verdict --item i --file V.json                      check the role's verdict against the item's attempt, store the item's result record
    claim   --item i --kind K (--instance X | --all)    say, BEFORE changing a record other walkers could use, which one; waits up to
            `claim_wait_s` for a record another live walk holds, then refuses naming the holder (case lanes only); the verdict of
            the item frees its claims when the case names a teardown, else they stay `dirty` (changed, not restored)
    done                                                the role's work is over (flushes the requests seen)
    close                                               end probe into every item attempt, close the browser, release the stand
    status                                              always answered, read-only

Answer: ONE JSON object on stdout (ASCII-escaped). Exit codes: 0 done / ok, 1 the step call stopped at a deviation (the session stays
`ready`), 2 refused (nothing was run; stderr names the door), 3 the session is not ready / did not start.
Files, all under the story folder: `state/walks/<W>.json` (the record: pid, started, port, token, state, ...), `state/walks/<W>.log`,
`state/walks/<W>/sessions/<slug>-<n>/` (browser profiles, deleted at close), `state/walks/<W>/batches/<item>-b<n>.json` (the full answer
of every step call), `work/walks/<W>/<item>.json` (the item's result record, spec 3.4) with `work/walks/<W>/timing.jsonl`, and the evidence under `work/evidence/manual/<case>/aN/`.
The stop rules and the limits are DATA: `references/manual-capture-steps.json` `walk_session`.
"""
from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import queue
import re
import secrets
import shlex
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import event_store
import execution_scheduler
import hooklib
import manual_capture as MC
import manual_evidence as ME
from role_cli import RefusingParser, command_from_argv, epilog, refuse, run_guarded

GUEST = "guest"
OPS = ("item", "step", "look", "final", "verdict", "claim", "done", "close", "status")
PAGE_OPS = ("item", "step", "look", "final", "verdict", "done", "close")
ITEM_OPS = ("item", "step", "look", "final", "verdict")
LEASE_OPS = ("item", "step", "look", "final", "close")      # the requests of an S7 lane that take the stand lease, each for its own length (U0)
PLACES = ("case", "settle", "control", "survey")      # roots named in references/artifact-writers.json as work/evidence/manual/settle-*/, survey-*/ and evidence/control-*/
LANE_PREFIX = {"case": "", "settle": "settle-", "control": "control-", "survey": "survey-"}
LIFE_LEASE_PLACES = ("case", "survey")      # the places whose walk holds the stand lease for its whole life (a survey walk takes no per-request lease: it would refuse itself `stand_busy`)
SURVEY = "survey"
REFUSED_CAUSES = ("no_reachable_surface",)      # causes (`ServerDead.cause`) that end `open` as a refused call, exit 2, not as a session that failed to start
SURVEY_DOOR = ("a survey item is a requirement id (R-n) or an element id of the snapshot; what the walk found is recorded with "
               "`first_look.py put` / `reference_snapshot.py put`")
CONTROL_PARTS = ("evidence",)               # a control's attempts: evidence/control-<item>/aN/, where contract.triage_control_problems looks
LANE_ID = re.compile(r"[A-Za-z0-9._-]+")
RANGE = re.compile(r"status:([0-9]+)-([0-9]+)")
PLAIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SEAMS = {"clock": None, "spawn": None, "sleep": None}      # tests put fakes here: clock() -> seconds; spawn(argv, log_path) -> a handle with kill(); sleep(seconds)
OVERRIDE: dict = {}                         # tests narrow a limit of the data object `walk_session`
_JOB = []                                   # the Windows job object lives as long as the process


class ServerDead(Exception):
    """The server cannot go on: `code` is the exit its `open` answers with."""

    def __init__(self, reason, code=3, cause=""):
        super().__init__(reason)
        self.reason, self.code, self.cause = reason, code, cause      # `cause`: a closed word for the driver (t-2027 F11), never a phrase of `reason`


def data() -> dict:
    return {**(MC.spec().get("walk_session") or {}), **OVERRIDE}


def _clock() -> float:
    return (SEAMS["clock"] or time.monotonic)()


def record_path(task_root, walk) -> Path:
    return Path(task_root).resolve() / "state" / "walks" / f"{walk}.json"


def walk_dir(task_root, walk) -> Path:
    return Path(task_root).resolve() / "state" / "walks" / str(walk)


def read_record(task_root, walk) -> dict:
    return hooklib.read_json(record_path(task_root, walk), {}, kind=dict)


def alive(record) -> bool:
    """A record whose server process is still the one that wrote it (pid + birth: Windows reuses pids)."""
    return bool(record.get("pid")) and execution_scheduler._same_process(int(record["pid"]), str(record.get("started") or ""))


# --------------------------------------------------------------------------------------------
# the stop rules (data in, a reason out; nothing here says that a stop is a bug)
# --------------------------------------------------------------------------------------------

def token_fault(token, d) -> str:
    """"" or what is wrong with one `--stop-on` token: a kind of `surprise.kinds`, `status:<lo>-<hi>` (400-599), `default`, `none`,
    optionally with a leading + or -."""
    kinds = list((MC.spec().get("surprise") or {}).get("kinds") or [])
    sign = token[:1] if token[:1] in ("+", "-") else ""
    body = token[len(sign):]
    if body == "default" or (not sign and body == "none") or body in kinds:
        return ""
    found = RANGE.fullmatch(body)
    if found:
        low, high = int(found.group(1)), int(found.group(2))
        return "" if 400 <= low <= high <= 599 else f"`{token}`: a status range is `status:<lo>-<hi>` with 400 <= lo <= hi <= 599"
    return (f"`{token}` is not a stop rule. A rule is a kind ({', '.join(kinds)}), `status:<lo>-<hi>` with 400 <= lo <= hi <= 599, "
            "`default` (the data default) or `none`; `+rule` adds to the default, `-rule` removes from it, rules without a sign replace it")


def stop_rules(tokens, d) -> list:
    """The rule list of one call. Rules without a sign REPLACE the data default (`default` stands for it, `none` for the empty list);
    then `+x` adds and `-x` removes (`-kind` removes the kind whatever its range). No token: the data default."""
    default = list(d["stop_on_default"])
    plain = [t for t in tokens if t[:1] not in ("+", "-")]
    rules = []
    for token in plain:
        rules += default if token == "default" else [] if token == "none" else [token]
    if not plain:
        rules = list(default)
    for token in (t for t in tokens if t[:1] in ("+", "-")):
        body = token[1:]
        items = default if body == "default" else [body]
        if token[0] == "+":
            rules += [i for i in items if i not in rules]
        else:
            rules = [r for r in rules if not any(r == i or (":" not in i and r.split(":")[0] == i) for i in items)]
    return list(dict.fromkeys(rules))


def matches_rule(rule, line) -> bool:
    """Does a surprise line match a rule. A `status` line whose number is absent or unreadable matches EVERY status rule (AR-28: an
    unknown is never read as `below 500`; the cost of the error is one more stop)."""
    kind = line.get("kind")
    found = RANGE.fullmatch(rule)
    if found:
        if kind != "status":
            return False
        number = line.get("status")
        return True if (not isinstance(number, int) or isinstance(number, bool)) else int(found.group(1)) <= number <= int(found.group(2))
    return kind == rule


def stop_at(row, found, rules, started, d, more=True):
    """None, or {reason, detail, facts}: why a call stops after one step. Order: the step's outcome is not `ok` -> failed|timeout|refused;
    the role's own `expect=` read otherwise -> expect; a surprise line of THIS step matches a rule -> surprise; the call's time spent
    beyond `batch_max_s` while steps remain (`more`) -> batch_time. ERROR DIRECTION: it may stop where the role would have gone on; it
    never lets a planned step run after a step that did not run, a 5xx the role did not cause, a console error or an unasked navigation."""
    outcome = row.get("outcome")
    if outcome != "ok":
        return {"reason": outcome if outcome in d["stop_reasons"] else "failed", "detail": str(row.get("detail") or ""), "facts": []}
    if row.get("expect") == "differs":
        return {"reason": "expect", "detail": str(row.get("detail") or ""), "facts": []}
    hits = [f for f in found if any(matches_rule(r, f) for r in rules)]
    if hits:
        return {"reason": "surprise", "detail": str(hits[0].get("fact") or ""), "facts": [_fact(h) for h in hits]}
    if more and _clock() - started > d["batch_max_s"]:
        return {"reason": "batch_time", "detail": f"the call has run longer than {d['batch_max_s']} s", "facts": []}
    return None


def _fact(line) -> dict:
    out = {"id": line.get("id"), "kind": line.get("kind"), "fact": str(line.get("fact") or "")[:200]}
    if "status" in line:
        out["status"] = line["status"]
    return out


class CallStop:
    """The call-back `_run_steps` asks after each step (and once late); it remembers its own answer and the rows it saw."""

    def __init__(self, rules, started, d, total):
        self.rules, self.started, self.d, self.total = rules, started, d, total
        self.hit, self.rows, self.k = None, [], 0

    def __call__(self, step, row, found, late=False):
        if late:
            hit = stop_at({"outcome": "ok"}, found, self.rules, self.started, self.d, more=False)
            if hit and self.hit is None:
                self.hit = {**hit, "k": step["n"], "step": step["line"]}
            elif hit:
                self.hit["facts"] += hit["facts"]
            return bool(hit)
        self.rows.append(row)
        self.k = step["n"]
        hit = stop_at(row, found, self.rules, self.started, self.d, more=step["n"] < self.total)
        if hit and self.hit is None:
            self.hit = {**hit, "k": step["n"], "step": step["line"]}
        return bool(hit)


# --------------------------------------------------------------------------------------------
# problems and the one refusal
# --------------------------------------------------------------------------------------------

def _step_lines(text) -> list:
    return [x.strip() for x in str(text or "").splitlines() if x.strip() and not x.strip().startswith("#")]


def lane_item_ok(item) -> bool:
    """True when `item` is a plain id a settle or control lane may carry (`open` and a later new item use this one test; t-2027 F9 the driver too)."""
    text = str(item)
    if not LANE_ID.fullmatch(text) or ".." in text or "__" in text:
        return False
    try:
        MC.case_dir_name(LANE_PREFIX["settle"] + text)
    except ValueError:
        return False
    return True


def env_row(cfg, name) -> tuple:
    """`(row, problem)`: the `environments[]` row whose `name` is EXACTLY `name` (no case folding: `Dev` is not `dev`; a name that repeats is
    refused, never resolved to the first row), or `({}, why)` naming the stands there are (J-C1). The one reader of `--env` for `open` and for the server."""
    rows = [e for e in (cfg.get("environments") if isinstance(cfg, dict) else None) or [] if isinstance(e, dict)]
    found = [row for row in rows if str(name) and str(row.get("name") or "") == str(name)]
    if len(found) > 1:      # the name must pick ONE stand: never walk the first of two silently (FR-59)
        return {}, (f"the stand `{name}` names {len(found)} rows of environments[] in config.json; rename one so the name picks one stand")
    if found:
        return found[0], ""
    names = [str(r["name"]) for r in rows if str(r.get("name") or "")]
    return {}, (f"the stand `{name}` is not in config.json; there are: {', '.join(names) or 'none'}. "
                "Expected `--env <name>` spelled exactly as `environments[].name` (case counts), or no `--env` for the first row")


NO_SCREEN_STEP = "http <METHOD> <path|url> [--body-file <file>]"


def http_url(target, stand) -> tuple:
    """`(url, problem)` of the address of an `http` step on `stand` (the walk's environments[] row): a path (`/v1/x`) is joined to the row's
    `base_url` (the twin of `manual_capture._http_login`'s join: two readers of `stand["base_url"]`); a full URL is itself. A path on a stand that records no base_url is a problem naming the way
    out. Where the URL points is NOT judged here: `request_problems` checks it against the walk's hosts and `http_call` checks it again."""
    text = str(target)
    if not text.startswith("/"):
        return text, ""
    base = str((stand or {}).get("base_url") or "").rstrip("/")
    if not base:
        return "", (f"the stand `{(stand or {}).get('name') or '?'}` records no base_url, so the path {text[:80]!r} has no address. "
                    "Give a full URL on one of the walk's hosts")
    return base + text, ""


def _http_step_faults(walk, steps) -> list:
    """What is wrong with the `http` steps of a call BEFORE any step runs (FL-1 B). A walk with no screen refuses every other word, whole
    (nothing is run). For each `http` step: the address resolves on the walk's stand and its host is one of the walk's hosts (J-C1: the
    refusal lists them); the body file reads, holds no generated-value placeholder (a walk creates no accounts) and matches no
    `secret_content_patterns`; the URL holds no placeholder. The same questions `http_call` asks again at the send: two guards."""
    out = []
    if walk.screenless:
        other = [s for s in steps if s["word"] not in walk.http_words()]
        if other:
            return [f"this walk has no screen: `{other[0]['word']}` (step {other[0]['n']}) needs a browser. Nothing was run. A walk with no screen "
                    f"runs `{NO_SCREEN_STEP}` only"]
    for step in steps:
        if step["word"] not in walk.http_words():
            continue
        label = f"step {step['n']} (`{step['line'][:80]}`)"
        url, why = http_url(step["args"][1], walk.stand)
        if why:
            out.append(f"{label}: {why}")
            continue
        if MC.host_key(url) not in walk.http_hosts:
            out.append(f"{label}: the address is not on this walk's stand (http or https, no user:password part). Allowed hosts: "
                       f"{MC.hosts_sentence(walk.http_hosts)}. A walk never leaves its stand")
        if MC.GENERATED_USER in url or MC.GENERATED_PASSWORD in url:
            out.append(f"{label}: the address holds a generated-value placeholder; a walk creates no accounts")
        if len(step["args"]) == 4:
            body, problem = MC.read_body_file(step["args"][3])
            if problem:
                out.append(f"{label}: {problem}")
                continue
            if MC.GENERATED_USER.encode() in body or MC.GENERATED_PASSWORD.encode() in body:
                out.append(f"{label}: the body holds a generated-value placeholder; a walk creates no accounts (a user is made with `manual_capture.py http`)")
            if (hit := MC.secret_pattern_hit(body.decode("utf-8", "replace"), walk.cfg)) is not None:
                out.append(f"{label}: the body matches secret_content_patterns[{hit}] of config.json: nothing was sent. A credential never goes in a "
                           "request you write; the walk signs in by code")
    return out


def request_problems(subject, req) -> list:
    """[problem]: what is wrong with a request BEFORE anything runs; each names its door. `subject` is the live `Walk` (the server's
    view), or the record dict / None (the client's view, before it connects, and the `open` request)."""
    d = data()
    op = req.get("op")
    out = []
    if op == "open":
        items = [i for i in req.get("items") or [] if str(i).strip()]
        if not items:
            return ["a walk has at least one item: `--items` is empty. Expected `--items <case id>[,<case id>...]`"]
        actors = [a for a in req.get("actors") or [] if a]
        if not actors or len(actors) > d["max_actors"]:
            out.append(f"a walk has 1 to {d['max_actors']} actors ({len(actors)} given). Expected `--actor <handle|guest>` and at most one `--actor2`")
        place = req.get("place") or "case"
        if place not in PLACES:
            out.append(f"--place {place!r} is not a place of a walk. Expected one of: {', '.join(PLACES)}")
            place = "case"
        for item in items:
            text = str(item)
            if place != "case" and (not LANE_ID.fullmatch(text) or ".." in text or "__" in text):
                spelled = ("one requirement id (R-n) or element id of the snapshot" if place == SURVEY
                           else "one place or control id, as `place_answers.py list` spells it")
                out.append(f"item {item!r} of the {place} lane is not a plain id. Expected `[A-Za-z0-9._-]+` (no `/`, no drive, "
                           f"no `..`, no `__`): {spelled}")
                continue
            try:
                MC.case_dir_name(LANE_PREFIX[place] + text)
            except ValueError as exc:
                out.append(str(exc))
        if not PLAIN_ID.fullmatch(str(req.get("walk") or "")):
            out.append(f"walk id {req.get('walk')!r} is not a plain id (letters, digits, . _ -): use the dispatch id")
        for other in _live_records(req["task_root"]):
            held = sorted(set(actors) - {GUEST} & set(other.get("actors") or []))
            if other.get("walk") == req.get("walk"):
                out.append(f"walk {other['walk']} is already open ({other.get('state')}). Ask `walk_session.py status --walk {other['walk']}`")
            elif held:
                out.append(f"account {held[0]} is walking in {other['walk']}; wait for it to close or name another account")
        return out
    if not isinstance(subject, Walk):
        record = subject or {}
        walk = req.get("walk")
        if not record:
            return [f"walk {walk} is unknown here: nothing is open under it. Expected `walk_session.py open` first; `status --walk {walk}` shows what exists"]
        if op != "status" and record.get("state") not in ("ready", "opening"):
            out.append(f"walk {walk} is {record.get('state')} ({record.get('reason') or 'ended'}): nothing can be run in it. `status --walk {walk}` says why")
        elif op != "status" and not alive(record):
            out.append(f"the server of walk {walk} is gone though its record says {record.get('state')}. `status --walk {walk}` says what it left")
        return out
    walk = subject
    if not hmac.compare_digest(str(req.get("token") or ""), walk.token):
        walk.log(f"refused a request without the right token (op {op})")
        return [f"the request carries no valid token for walk {walk.walk}: use the walk_session.py command, which reads it; `status --walk {walk.walk}` shows the walk"]
    if op not in OPS:
        return [f"unknown command {op!r}. Expected one of: open, {', '.join(OPS)}"]
    if op == "status":
        return []
    if op in ITEM_OPS:
        item, actor = req.get("item"), walk.actor_of(req)
        if item not in walk.items and not walk.takes_new_item(item):
            out.append(f"item {item!r} is not in walk {walk.walk} (items: {', '.join(walk.items)}). `status --walk {walk.walk}` lists them"
                       + ("" if walk.place == "case" else f"; {SURVEY_DOOR}" if walk.place == SURVEY
                          else "; a place of your own is captured with `manual_capture.py ui|http --case settle-<place id>`"))
        elif has_verdict(walk.verdict_path(item)) and op != "verdict":
            out.append(f"item {item} has a verdict on disk: it is not walked again in this dispatch (`status --walk {walk.walk}`)")
        if actor not in walk.actors:
            out.append(f"actor {actor!r} is not one of walk {walk.walk}'s actors ({', '.join(walk.actors)}; at most {d['max_actors']} per walk)")
    if walk.busy.locked() and op != "status":
        out.append(walk.busy_text())
    if op == "step" and not out:
        text = str(req.get("steps") or "")
        lines = _step_lines(text)
        if not lines:
            out.append("a step call has at least one step: the steps hold no step (blank lines and # lines only). Nothing was run. "
                       "Expected `--line \"<step>\"` or a steps file with one step per line")
        elif len(lines) > d["max_batch_steps"]:
            out.append(f"{len(lines)} steps; a call holds at most {d['max_batch_steps']}: send steps 1-{d['max_batch_steps']} now and the rest as the next call")
        else:
            try:
                steps = MC.parse_steps(text, walk.spec, need_goto=False, http_ok=True)
                for token in req.get("stop_on") or []:
                    if (fault := token_fault(str(token), d)):
                        out.append(fault)
                if (hit := MC.secret_pattern_hit(text, walk.cfg)) is not None:
                    out.append(f"the steps match secret_content_patterns[{hit}] of config.json: steps are saved in the record, so a credential never goes "
                               "in one. To type an account use `fill-account <selector> <actor> user|secret`")
                if not out:
                    out.extend(_http_step_faults(walk, steps))
                if not out:
                    MC._account_steps_gate(steps, walk.cfg, walk.stand, walk.task_root, req.get("item"))
            except ValueError as exc:
                out.append(str(exc))
    if (op in ("look", "final") or (op == "step" and req.get("final"))) and walk.screenless and not out:
        what = op if op != "step" else "step --final"
        out.append(f"`{what}` needs a screen and this walk has no screen; its steps are `{NO_SCREEN_STEP}`")
    if op in ("look", "final") and not out and getattr(walk.accounts.get(walk.actor_of(req)), "window", False):
        out.append(f"{MC.NO_SHOT_IN_WINDOW} (a {op} inside the sign-in window). Capture after the page has left the sign-in address")
    if op == "verdict" and not out and not isinstance(req.get("verdict"), dict):
        out.append("the verdict is a JSON object: `--file V.json` holding one")
    return out


def _refuse(problems):
    """The ONE refusal of the server: turns a problem list into the refusal text (exit 2 at the caller)."""
    raise ValueError(" | ".join(str(p) for p in problems))


def _refusal(problems) -> tuple:
    try:
        _refuse(problems)
    except ValueError as exc:
        return 2, {"status": "refused", "problems": list(problems), "text": str(exc)}
    return 2, {"status": "refused", "problems": list(problems)}


# --------------------------------------------------------------------------------------------
# the result record of one item (t-1957 N2, spec 3.4): the verdict checked against the item's ATTEMPT, never against a call answer
# --------------------------------------------------------------------------------------------

THEN_RESULTS = (*ME.RESULTS, "unreached")
TEARDOWN_WORDS = ("done", "not_done", "none")
PLACE = "case"                  # Slice 1 walks S6 cases only; Slices 3 add `control` and `explore` (the grouping key of walk_timing)
ENDED_WITHOUT_VERDICT = "the walker ended before its verdict"
PRE_DOOR = ("Door: say what the evidence allows - `inconclusive` with a `limitation` of the Then when a picture of the page before the action "
            "is missing (the server takes it before the item's first click/fill of a call that starts signed in: sign in with `fill-account` in a "
            "call of its own, and walk the item in the next one; a picture taken after you acted is no \"before\"), or an observation whose "
            "`quote` is words copied from the capture it names")


class _RootedAttempt(MC.Attempt):
    """An attempt whose folder is `root/<name>` instead of the manual case root (the `control` lane). `dir` is fixed by the constructor, so
    the base class never creates the manual case folder of the control's name."""

    def __init__(self, task_root, case, name, cfg, root):
        self._fixed = Path(root) / name
        super().__init__(task_root, case, name, cfg)

    @property
    def dir(self) -> Path:
        return self._fixed

    @dir.setter
    def dir(self, value):
        pass


def _word(row) -> str:
    parts = str((row or {}).get("step") or "").split()
    return parts[0] if parts else ""


def attempt_dir(task_root, item, attempt) -> Path:
    return MC.case_root(task_root, item) / str(attempt)


def attempt_rows(task_root, item, attempt) -> tuple:
    """`(steps, captures)`: the EXECUTED step rows and the captures of the item's attempt, in the order the recorder wrote them. A step that
    did not run (`not_run` of a stopped call) has no row, so it is neither evidence nor an action. A call's batch size is invisible here:
    steps sent one per call and steps sent as one call leave the same rows (E2.10). `([], [])` for an attempt that does not exist."""
    if not attempt:
        return [], []
    folder = attempt_dir(task_root, item, attempt)
    return MC.jsonl_rows(folder / "steps.jsonl"), MC.jsonl_rows(folder / "captures.jsonl")


SIGN_IN_SUBMIT_ROWS = 1          # the acting rows right after the last `fill-account` row that are the sign-in's own submit (one click or one key)


def acting_words(d=None) -> set:
    """The words of a step that ACT on the page for the item (click, drag, fill, type, press, paste; not `goto`): the one set `_with_pre_action`
    and the before-picture's order rule read (data keys `surprise.action_steps`, `surprise.input_steps`, `walk_session.pre_not_before`)."""
    surprise = MC.spec().get("surprise") or {}
    return (set(surprise.get("action_steps") or []) | set(surprise.get("input_steps") or [])) - set((d or data())["pre_not_before"])


def first_action_row(rows, d=None) -> int:
    """The index of the item's FIRST acting row beyond the sign-in, -1 when there is none. The sign-in is every row up to the last
    `fill-account` row plus `SIGN_IN_SUBMIT_ROWS` acting row(s) right after it (the submit): a row cannot say more, so a second action
    right after the sign-in counts as the item's own (ERROR DIRECTION: a before-picture taken after it is refused, with a door)."""
    acting = acting_words(d)
    start = max((i for i, row in enumerate(rows) if _word(row) == "fill-account"), default=-1) + 1
    for _ in range(SIGN_IN_SUBMIT_ROWS if start else 0):
        if start < len(rows) and _word(rows[start]) in acting:
            start += 1
    return next((i for i in range(start, len(rows)) if _word(rows[i]) in acting), -1)


def _capture_row(rows, phase) -> int:
    """The index of the first successful `capture <phase> ...` row of the attempt (the phase read through `PHASE_ALIAS`), -1 when none."""
    for i, row in enumerate(rows):
        words = str(row.get("step") or "").split()
        if row.get("outcome") == "ok" and words[:1] == ["capture"] and len(words) > 1 and ME.PHASE_ALIAS.get(words[1], words[1]) == phase:
            return i
    return -1


def before_order_problems(rows) -> list:
    """The ORDER of the attempt's rows, never what a picture shows (data, AR-29; t-2022 N4): the "before" picture stands before the item's
    first action beyond the sign-in, and before the "after" picture (unless an action stands after it). A `pre_action` taken after the page was acted on is a false "before"
    (P26). `[]` when the attempt holds no before-picture (the record rule says that) or none of the two orderings is broken."""
    before, after, act = _capture_row(rows, "before"), _capture_row(rows, "after"), first_action_row(rows)
    if before < 0:
        return []
    out = []
    if 0 <= act < before:
        out.append(f"the `pre_action` picture is step {before + 1} of the attempt, taken AFTER the item's first action (step {act + 1}: "
                   f"{rows[act].get('step')}): that is no picture of the page before. Sign in in a call of its own, then send the item's steps in "
                   "the next call (the server takes `pre_action` before its first action), or say `inconclusive` with the limitation")
    if 0 <= after < before and act < before:          # an action after it keeps it a "before" (a read-only `final` taken first, then the item acted)
        out.append(f"the `pre_action` picture (step {before + 1}) was taken after the `post_action` one (step {after + 1}): that is no picture of "
                   "the page before. Say `inconclusive` with the limitation: the before picture of this attempt cannot be taken again")
    return out


def final_state(task_root, item, attempt) -> dict:
    """`{final: {snapshot, screenshot} | None, after_action: bool, why}`. A `final` is the screenshot `capture post_action completion` stored (it proves `completion`, which a pass needs; the
    step row says it ran, the capture row holds the file). It counts as AFTER THE LAST ACTION when its step row stands later in `steps.jsonl`
    than the last executed action row (`surprise.action_steps` + `input_steps` of the step data) - the order of one file, not the clocks of
    two (a second is too coarse). ERROR DIRECTION: it may refuse a pass an earlier capture showed (one `final` call); it never accepts a
    pass with no capture after the last action: a final of another item is another attempt's file, one before the last action stands
    earlier, a file deleted afterwards is not there, a stop snapshot is a state file with no `final` step."""
    task = Path(task_root).resolve()
    steps, captures = attempt_rows(task, item, attempt)
    surprise = MC.spec().get("surprise") or {}
    d = data()
    actions = set(surprise.get("action_steps") or []) | set(surprise.get("input_steps") or []) | set(d["final_also_actions"])
    label = d["final_label"]
    last_action = max([i for i, row in enumerate(steps) if _word(row) in actions], default=-1)
    final_steps = [i for i, row in enumerate(steps) if str(row.get("step") or "").split()[:3] == ["capture", "post_action", label]
                   and row.get("outcome") == "ok"]
    shots = [i for i, c in enumerate(captures) if c.get("kind") == "image" and Path(str(c.get("path") or "")).stem.endswith("-" + label)]
    if not final_steps or not shots:
        return {"final": None, "after_action": False, "why": "no final snapshot of this item's attempt"}
    shot = captures[shots[-1]]
    snap = captures[shots[-1] - 1] if shots[-1] > 0 and captures[shots[-1] - 1].get("kind") == "state" else None
    final = {"snapshot": snap.get("path") if snap else None, "screenshot": shot.get("path")}
    if len(final_steps) != len(shots):
        return {"final": final, "after_action": False, "why": "the final steps and the final pictures of this attempt do not match"}
    if not (task / str(shot.get("path") or "-")).is_file():
        return {"final": final, "after_action": False, "why": "the final picture is no longer on disk"}
    if final_steps[-1] < last_action:
        return {"final": final, "after_action": False, "why": "the last final snapshot was taken BEFORE the last action of the item"}
    return {"final": final, "after_action": True, "why": ""}


def _quote_home(task, quote, captures, named="") -> str:
    """The path of the capture of THIS attempt whose text holds the quote ('' when none). `named` narrows the search to one capture."""
    for ref in captures:
        if named and str(ref.get("path")) != named:
            continue
        if ME._quote_in(task, ref, quote):
            return str(ref.get("path"))
    return ""


def capture_cited(task_root, walk, item, path, quote="", stand="") -> str:
    """"" when `quote` is words of the capture `path` of THIS survey walk's attempt of `item`, else why not, each reason with its door
    (FL-1 A, J-C2: the evidence of one walk is never cited by a record of another). Pure: it reads the walk's record (`place`, `stand`,
    `attempts`), the attempt's `captures.jsonl` and the capture file; it writes nothing. All of these hold, in this order: the record
    of `walk` reads; its `place` is `survey` (a reference walk or a case walk is no first look); its `stand` is named, and is `stand`
    when one is given; it names an attempt of `item`; `path` is a capture file of THAT attempt under
    `work/evidence/manual/survey-<item>/<attempt>/` (an earlier attempt, another item or outside the story is refused); the quote is
    found by `_quote_home` in the capture as it is STORED. ERROR DIRECTION: a quote that crosses a character the stored JSON writes
    escaped (a quotation mark, a line break), or stands in the part cut at `BODY_CAP` or in a base64 body, is refused - it is not in the
    stored text; a good quote is sometimes refused, a made-up one never accepted. An empty quote is refused too."""
    task = Path(task_root).resolve()
    door = ("Door: cite a capture of this walk's own attempt of that item (`walk_session.py status --walk "
            f"{walk}` lists the attempts), words copied as the capture holds them")
    if not PLAIN_ID.fullmatch(str(walk)):
        return f"walk id {str(walk)[:80]!r} is not a plain id (letters, digits, . _ -). {door}"
    record = read_record(task, walk)
    if not record:
        return f"walk {walk} has no record that can be read: its evidence is no first look's. {door}"
    if record.get("place") != SURVEY:
        return f"walk {walk} is a {record.get('place') or 'unknown'} walk, not a survey walk: only a survey walk's captures are cited by a first look. {door}"
    named = str(record.get("stand") or "")
    if not named:
        return f"the record of walk {walk} names no stand, so no capture of it can be tied to one. Open the walk again with `walk_session.py open --place survey --env <name>`"
    if stand and str(stand) != named:
        return f"walk {walk} walked the stand `{named}`, not `{stand}`: its captures are no evidence of that stand. {door}"
    attempts = record.get("attempts") if isinstance(record.get("attempts"), dict) else {}
    attempt = attempts.get(item)
    if not isinstance(attempt, str) or MC.attempt_number(attempt) < 0:
        return f"walk {walk} has no attempt of item {str(item)[:80]!r} (its items: {', '.join(map(str, attempts)) or 'none'}). {door}"
    try:
        folder = MC.case_root(task, LANE_PREFIX[SURVEY] + str(item)) / attempt
    except ValueError as exc:
        return f"{exc}. {door}"
    try:
        file = ME._safe_evidence_path(task, path)
    except (ValueError, OSError, IndexError):
        return f"`{str(path)[:120]}` is no evidence file of the story (a task-relative path under work/evidence, no symlink, a file that exists). {door}"
    if not file.is_relative_to(folder):
        return (f"`{str(path)[:120]}` is not in attempt {attempt} of item {item} of walk {walk} ({folder.relative_to(task).as_posix()}/): "
                f"a capture of another item, another walk or an earlier attempt holds nothing for this walk. {door}")
    rel = file.relative_to(task).as_posix()
    refs = [r for r in MC.jsonl_rows(folder / "captures.jsonl") if str(r.get("path") or "").replace("\\", "/") == rel]
    if not refs:
        return f"`{rel}` is not a capture the recorder wrote for attempt {attempt} (its captures.jsonl does not list it). {door}"
    wanted = ME._squash(quote)
    if not wanted:
        return f"nothing is quoted: copy the words of `{rel}` that show what you saw. {door}"
    if not _quote_home(task, wanted, refs, rel):
        return (f"the quote is not in `{rel}` as the capture stores it{ME._beyond_words(task, refs[0])}. Copy words that stand in it; "
                f"a base64 body is described in `why`, not quoted. {door}")
    if wanted not in ME._text_views(task, refs[0])[0]:
        return (f"the quote is in `{rel}` only after its JSON is decoded: it crosses a character the stored document writes escaped "
                f"(a quotation mark or a line break). Quote a fragment without such characters. {door}")
    return ""


def _names_teardown(task, item) -> bool:
    """Does the case name a teardown: its `## Teardown` section, the carrier the walk brief shows (`brief_pack.case_teardown`, the one
    reader). "None named" (also a case that cannot be found) asks nothing of the verdict."""
    import brief_pack
    return bool(brief_pack.case_teardown(Path(task), str(item)))


def verdict_problems(task_root, item, attempt, verdict) -> list:
    """[problem]: what is wrong with the role's verdict of ONE item, each with its door. It reads the item's attempt (steps.jsonl,
    captures.jsonl) and NEVER the call answer files, so a quote's validity does not depend on how the steps were grouped (E2.10). Code checks
    that the words are THERE, not whether they show the Then (AR-29, FR-12): a Then without a result (when `request.json` lists the Thens);
    a pass or fail without a quote found in a capture of THIS attempt (P26: no pass without recorded words; a quote that stands only in
    another item's attempt holds nothing, E2.2); a pass with no `final` after the last action (E2.3); a `teardown` missing or unknown when the
    case names one. The error goes toward refusing a good quote, never toward accepting a made-up one."""
    task = Path(task_root).resolve()
    if not isinstance(verdict.get("thens"), list) or any(not isinstance(t, dict) for t in verdict["thens"]):
        return ["the verdict's `thens` is a list of {n, result, quote, capture} ([] for a case with no Then)"]
    wanted = ME._request_thens(task, item)
    steps, captures = attempt_rows(task, item, attempt)
    out, given = [], set()
    for entry in verdict["thens"]:
        n = entry.get("n")
        number = int(n) if isinstance(n, int) and not isinstance(n, bool) else int(n) if isinstance(n, str) and n.isascii() and n.isdigit() else None
        if number is None:
            out.append(f"a Then of the verdict has no number `n` ({entry!r:.80}): give `{{\"n\": 1, \"result\": \"pass|fail|inconclusive|unreached\", ...}}`")
            continue
        if wanted and number not in wanted:
            out.append(f"Then {number} is not a Then of this case (its Thens: {', '.join(map(str, wanted))})")
            continue
        if number in given:
            out.append(f"Then {number} is given twice")
            continue
        given.add(number)
        result = entry.get("result")
        if result not in THEN_RESULTS:
            out.append(f"Then {number} has no result: say pass | fail | inconclusive | unreached")
            continue
        if result not in ("pass", "fail"):
            continue
        quote = ME._squash(entry.get("quote") or "")
        if not quote:
            out.append(f"Then {number} is `{result}` but quotes nothing: quote the capture that shows it - the words copied from a capture of this "
                       "item's attempt (`look`, `read`, a response), or say `inconclusive` with a `limitation`")
        elif len(quote) > ME.THEN_QUOTE_MAX:
            out.append(f"the quote for Then {number} is {len(quote)} characters: quote at most {ME.THEN_QUOTE_MAX}, the shortest part that decides")
        else:
            named = str(entry.get("capture") or "").strip()
            if named and named not in {str(c.get("path")) for c in captures}:
                out.append(f"Then {number}: `{named}` is no capture of this item's attempt {attempt or '(none yet)'}; a capture of another item or "
                           "attempt holds nothing for this verdict - name one of this attempt or leave `capture` out")
            elif not _quote_home(task, quote, captures, named):
                held = ", ".join(Path(str(c.get("path"))).name for c in captures if Path(str(c.get("path") or "")).suffix.lower() in ME.QUOTE_SUFFIXES)
                out.append(f"the quote for Then {number} is not in the text this item's attempt {attempt or '(none yet)'} captured "
                           f"({held or 'no text capture'}): copy the words as a capture holds them, or capture the page first")
    for number in wanted:
        if number not in given:
            out.append(f"Then {number} has no result in the verdict: give every Then of the case one of pass | fail | inconclusive | unreached")
    if any(t.get("result") == "pass" for t in verdict["thens"]):
        state = final_state(task, item, attempt)
        if not state["after_action"]:
            out.append(f"a `pass` needs a final snapshot taken after the item's last action ({state['why']}): "
                       f"run `walk_session.py final --item {item}` (or send the last steps with `--final`), then send the verdict again")
    if any(t.get("result") in ("pass", "fail") for t in verdict["thens"]):
        out.extend(before_order_problems(steps))          # N4: a judged Then stands on a "before" that was taken before the action
    teardown = verdict.get("teardown")
    if teardown is not None and teardown not in TEARDOWN_WORDS:
        out.append(f"`teardown` is one of {' | '.join(TEARDOWN_WORDS)}, not {teardown!r}")
    elif teardown is None and _names_teardown(task, item):
        out.append("this case names a teardown: say in the verdict `\"teardown\": \"done\"`, `\"not_done\"` or `\"none\"`")
    if verdict.get("observations") is not None and (not isinstance(verdict["observations"], list)
                                                    or any(not isinstance(o, dict) for o in verdict["observations"])):
        out.append("`observations` is a list of objects ([] when nothing was doubtful)")
    return out


def _batch_answers(task_root, walk, item) -> list:
    """`[(n, answer)]` of the item's stored call answers, by call number (what `stops` and a missing verdict's limitation are counted from)."""
    folder, name = walk_dir(task_root, walk) / "batches", MC.case_dir_name(item)
    found = []
    for path in sorted(folder.glob(f"{name}-b*.json")) if folder.is_dir() else []:
        match = re.fullmatch(re.escape(name) + r"-b([0-9]+)\.json", path.name)
        if match:
            found.append((int(match.group(1)), hooklib.read_json(path, {}, kind=dict)))
    return sorted(found, key=lambda pair: pair[0])


def timing_line(task_root, walk, item, attempt, *, index, started_at, ended_at, batches, place=PLACE) -> dict:
    """The one line of `work/walks/<W>/timing.jsonl` for an item: `{item, index, place, started_at, ended_at, steps, batches, stops, attempt}`
    (`steps` = executed step rows of the attempt, `batches` = recorder step calls, `stops` = stored call answers that say `stopped`)."""
    steps, _ = attempt_rows(task_root, item, attempt)
    stops = sum(1 for _, answer in _batch_answers(task_root, walk, item) if answer.get("status") == "stopped")
    return {"item": item, "index": index, "place": place, "started_at": started_at, "ended_at": ended_at, "steps": len(steps),
            "batches": batches, "stops": stops, "attempt": attempt}


def _missing_verdict(task, walk, item) -> dict:
    """The verdict of an item whose walker ended without one: every Then `inconclusive`, the limitation saying so (AR-28) and, when the last
    call of the item stopped, where (E2.14: never a silent inconclusive)."""
    limitation = ENDED_WITHOUT_VERDICT
    answers = _batch_answers(task, walk, item)
    if answers and answers[-1][1].get("status") == "stopped":
        at = answers[-1][1].get("stopped_at") or {}
        limitation += (f"; its last call stopped at step {at.get('k')} ({at.get('step')}): {at.get('reason')}"
                       + (f" - {at['detail']}" if at.get("detail") else ""))
    return {"thens": [{"n": n, "result": "inconclusive", "quote": "", "capture": ""} for n in ME._request_thens(task, item)],
            "observations": [], "teardown": "not_done" if _names_teardown(task, item) else "none", "limitation": limitation}


def _joined_limitation(verdict) -> str:
    """The record's one `limitation`: the verdict's own and each Then's (`Then n: ...`), once each. A Then-level limitation is the
    recipe's example D (a silent `inconclusive`): it joins the record's, never dropped."""
    parts = [str(verdict.get("limitation") or "").strip()]
    parts += [f"Then {t.get('n')}: {str(t['limitation']).strip()}" for t in verdict.get("thens") or []
              if isinstance(t, dict) and str(t.get("limitation") or "").strip()]
    return "; ".join(dict.fromkeys(p for p in parts if p))


def write_verdict(task_root, walk, item, verdict, *, actor="", attempt="", started_at="", ended_at="", index=None, batches=None) -> dict:
    """Store the result record of one item, `work/walks/<W>/<item>.json`, and its timing line; returns the record. `verdict` None = the
    walker ended without one (`_missing_verdict`); the record is still built (FR-23) and MARKED `missing_verdict` - it is no verdict
    (`has_verdict`): the item may still be walked and given a real one (t-2016 F4). The server passes what it knows (`actor`, `attempt`,
    `started_at`, `index`, `batches`); the driver's `walk_after`, after the server is gone, passes none and everything is read from disk."""
    task = Path(task_root).resolve()
    record = walk_record_of(task, walk, item, verdict, actor=actor, attempt=attempt, started_at=started_at, ended_at=ended_at, index=index, batches=batches)
    path = task / "work" / "walks" / str(walk) / f"{MC.case_dir_name(item)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    event_store.atomic_json(path, record)
    line = timing_line(task, walk, item, record["attempt"], index=record["index"], started_at=record["started_at"], ended_at=record["ended_at"],
                       batches=record["batches"])
    timing = path.parent / "timing.jsonl"
    kept = [r for r in MC.jsonl_rows(timing) if r.get("item") != item]
    timing.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [*kept, line]), encoding="utf-8", newline="\n")
    return record


def has_verdict(path) -> bool:
    """True when `path` is the result record of a REAL verdict: it exists and is not the record written for a missing one."""
    record = hooklib.read_json(Path(path), {}, kind=dict) if Path(path).is_file() else {}
    return bool(record) and not record.get("missing_verdict")


def walk_record_of(task, walk, item, verdict, *, actor="", attempt="", started_at="", ended_at="", index=None, batches=None) -> dict:
    """The result record of one item (spec 3.4), made and NOT written: `write_verdict` stores it, `Walk.op_verdict` asks the case record's
    rules of it first (`ME.walk_rule_errors`) while the session lives."""
    task = Path(task).resolve()
    state = read_record(task, walk)
    if not attempt:
        names = [n for n in MC.attempts_of(MC.case_root(task, item)) if MC.jsonl_rows(attempt_dir(task, item, n) / "steps.jsonl")]
        attempt = names[-1] if names else ""
    steps, captures = attempt_rows(task, item, attempt)
    missing = verdict is None
    verdict = _missing_verdict(task, walk, item) if missing else verdict
    moments = [str(r["at"]) for r in steps if r.get("at")]
    items = list(state.get("items") or [])
    index = index if index is not None else (items.index(item) if item in items else 0)
    batches = batches if batches is not None else len(_batch_answers(task, walk, item))
    thens = []
    for entry in verdict.get("thens") or []:
        quote = ME._squash(entry.get("quote") or "")
        home = str(entry.get("capture") or "") or (_quote_home(task, quote, captures) if quote and entry.get("result") in ("pass", "fail") else "")
        thens.append({"n": int(entry["n"]), "result": entry["result"], "quote": quote, "capture": home})
    record = {"walk": str(walk), "place": PLACE, "item": item, "index": index, "actor": actor or str((state.get("actors") or [GUEST])[0]),
              "attempt": attempt, "started_at": started_at or (min(moments) if moments else MC._now()),
              "ended_at": ended_at or (max(moments) if moments else MC._now()), "steps": len(steps), "batches": batches,
              "stops": sum(1 for _, a in _batch_answers(task, walk, item) if a.get("status") == "stopped"), "thens": thens,
              "final": final_state(task, item, attempt)["final"] if attempt else None,
              "observations": list(verdict.get("observations") or []),
              "teardown": verdict.get("teardown") or "none"}
    if (limitation := _joined_limitation(verdict)):
        record["limitation"] = limitation
    if verdict.get("actual"):
        record["actual"] = str(verdict["actual"])
    if verdict.get("about") is not None:       # t-2181 PC-5a: the sides the walk speaks about travel to the case record (C11 checks the names)
        record["about"] = verdict["about"]
    if missing:
        record["missing_verdict"] = True
    return record


def _live_records(task_root, take_over=True) -> list:
    """The records of walks whose server is alive and not over: the ONE reader of that (the claims read it too, AR-13). An orphan (a record
    that says ready but whose process is gone) is taken over: its record becomes `dead (taken over)` and its profile folders are deleted
    when possible (a failure is a note). `take_over=False` is the read-only look (the claims'): nothing is written, and a record whose
    pid or birth cannot be read is not live (its in-use claims read `dirty`, never free)."""
    out = []
    folder = Path(task_root).resolve() / "state" / "walks"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        record = hooklib.read_json(path, {}, kind=dict)
        if record.get("state") not in ("ready", "opening"):
            continue
        try:
            is_alive = alive(record)
        except (TypeError, ValueError):
            if take_over:
                raise
            continue
        if is_alive:
            out.append(record)
            continue
        if not take_over:
            continue
        notes = _delete_profiles(folder / str(record.get("walk") or path.stem))
        event_store.atomic_json(path, {**record, "state": "dead", "reason": "dead (taken over)", "notes": [*(record.get("notes") or []), *notes]})
    return out


def _delete_profiles(base) -> list:
    notes = []
    sessions = Path(base) / "sessions"
    for child in sorted(sessions.iterdir()) if sessions.is_dir() else []:
        try:
            shutil.rmtree(child)
        except OSError as exc:
            notes.append(f"profile folder {child.name} was not deleted: {type(exc).__name__}: {str(exc)[:100]}")
    return notes


# --------------------------------------------------------------------------------------------
# claims (t-2174 TR3-10 C): what a walk changes in the app that other walkers also read. The walker says it BEFORE it changes a record
# (`claim`); code keeps the list, refuses a second live holder and tells whose it is. Whether a step changes a record is the walker's
# judgment (AR-29): code only compares the names the walker gave, and reads the walks' liveness.
# --------------------------------------------------------------------------------------------

CLAIM_STATES = ("in_use", "free", "dirty")
CLAIM_ALL = "*"                  # the instance of a claim on the whole collection of a kind
CLAIM_POLL_S = 0.5               # a refused claim re-reads the list this often until `claim_wait_s`
CLAIM_TEXT_MAX = 200             # an instance or a kind is kept as given in the list, cut at this length in every text
CLAIM_LOCK_WAIT_S = MC.ACCOUNT_LOCK_WAIT_S      # the list is written in a moment: another walker's write is waited for this long
CLAIM_DOOR = ("Door: use another record of that kind (or make one, when this project's way allows: see your brief), or end this item "
              "`inconclusive` saying which record was held")


def _sleep(seconds) -> None:
    (SEAMS["sleep"] or time.sleep)(seconds)


def fold_kind(text) -> str:
    """The spelling of a kind that is compared: casefold, strip, runs of white space as one space. `Book` / ` book ` / `BOOK` are one kind;
    `books` and `book` are two (the walker's words, not ours: the charter asks for one spelling per kind)."""
    return " ".join(str(text if text is not None else "").split()).casefold()


def cut_text(text, limit=CLAIM_TEXT_MAX) -> str:
    """`text` cut at `limit` (200: an instance, a kind or a handle is kept whole in the data and cut in every text); the ONE cut of the walk
    modules (`walk_pool` uses it)."""
    text = str(text)
    return text if len(text) <= limit else text[:limit]


def claims_path(task_root) -> Path:
    """The ONE path of the story's list of claims (`<T>/state/walk-entities.json`): `update_claims` writes it, `claims_of` reads it
    (AR-13, AR-14); nothing else names the file."""
    return Path(task_root).resolve() / "state" / "walk-entities.json"


def claims_of(task_root, walk=None) -> tuple:
    """`(rows, problem)`: the ONE reader of the claims, `{kind, instance|"*", walk, item, state, at}`; `walk` keeps one walk's rows. A missing
    file is no claim (`([], "")`: a walk written before claims, or one that never claimed). A file that cannot be read, or holds a row that
    cannot be read, is a problem in words and no rows: a reader never grants on an unknown (AR-28)."""
    path = claims_path(task_root)
    if not path.is_file():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:        # UnicodeDecodeError is a ValueError
        return [], f"{path.name} cannot be read ({type(exc).__name__})"
    rows = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], f"{path.name} does not hold a `claims` list"
    for row in rows:
        if not (isinstance(row, dict) and row.get("kind") and row.get("walk") and row.get("instance") and row.get("state") in CLAIM_STATES):
            return [], f"{path.name} holds a claim that cannot be read"
    return [r for r in rows if walk is None or r["walk"] == str(walk)], ""


def live_walk_ids(task_root) -> set:
    """The walks whose server is alive and not over (a read-only look at the records: nothing is taken over here). A record that cannot
    be read as alive is not live: its in-use claims read `dirty`, never free. The judgment is `_live_records`'s (one liveness reader)."""
    folder = Path(task_root).resolve() / "state" / "walks"
    return {str(r.get("walk") or "") for r in _live_records(task_root, take_over=False)} - {""} if folder.is_dir() else set()


def _has_record(task_root, walk) -> bool:
    try:
        return record_path(task_root, walk).is_file()
    except (OSError, ValueError):
        return False        # a record that cannot be looked at counts as none: the row stays held (the safe side for a second holder)


def held_walk_ids(task_root, rows) -> set:
    """The walks that hold their `in_use` rows: the live ones, and those with NO record yet (`assign_entities` wrote the row before the agent
    opened the walk: the row is HELD, never dirty, until the walk opens and is read by the live rule - or until the dispatch is settled,
    Part D). INVARIANT (C.1): between an assignment and the walk's opening no other walk gets the instance or the whole list. A walk with a
    record that is not alive is NOT held: its rows read `dirty`."""
    held = live_walk_ids(task_root)
    return held | {r["walk"] for r in rows if r["state"] == "in_use" and r["walk"] not in held and not _has_record(task_root, r["walk"])}


def claim_state(row, held) -> str:
    """`held | dirty | free`: what state a claim row has for another walk, the ONE rule every reader uses. `held`: `in_use` by a walk in
    `held` (`held_walk_ids`). `dirty`: a `dirty` row, or `in_use` by a walk that is not held (its walk ended before it released the claim:
    changed and not restored). `free`: a `free` row."""
    if row["state"] == "in_use":
        return "held" if row["walk"] in held else "dirty"
    return row["state"] if row["state"] == "dirty" else "free"


def _blockers(rows, claim, live) -> list:
    """`[(row, state)]` of the rows that refuse `claim` (`{kind (folded), instance|"*", walk}`): another walk's row of the same kind that is
    held (`claim_state`; `live` is `held_walk_ids`) and the same instance, or holds `*`, or (the claim being `*`) any instance; or that is
    `dirty` on the same instance. A row `in_use` by a walk that is not held is read as `dirty`, never free. The claimer's own rows never
    block (a walk is never blocked by itself). `state` in the answer is `in_use` (held) or `dirty`."""
    out = []
    for row in rows:
        if row["walk"] == claim["walk"] or fold_kind(row["kind"]) != claim["kind"]:
            continue
        state = claim_state(row, live)
        state = "in_use" if state == "held" else state
        held = str(row["instance"])
        if state == "in_use" and (claim["instance"] == CLAIM_ALL or held == CLAIM_ALL or held == claim["instance"]):
            out.append((row, state))
        elif state == "dirty" and held == claim["instance"]:
            out.append((row, state))
    return out


def _dirty_instances(rows, kind, live) -> list:
    """The instances of the folded `kind` that read `dirty` (a row `dirty`, or `in_use` by a walk that is not live), in the list's order,
    each once: what a `--all` grant names (decision L1: a fact for the walker, never a refusal). The whole-list row `*` is not an instance."""
    out = []
    for row in rows:
        held = str(row["instance"])
        if fold_kind(row["kind"]) == kind and claim_state(row, live) == "dirty" and held != CLAIM_ALL and held not in out:
            out.append(held)
    return out


def _held_words(row) -> str:
    kind = cut_text(row["kind"])
    return f"the whole list of `{kind}`" if str(row["instance"]) == CLAIM_ALL else f"the {kind} `{cut_text(row['instance'])}`"


def _blocker_text(row, state) -> str:
    if state == "in_use":
        return f"{_held_words(row)} is in use by walk {row['walk']} (item {row.get('item')})"
    ended = " (its walk ended before it released the claim)" if row["state"] == "in_use" else ""
    return f"{_held_words(row)} was changed by walk {row['walk']} (item {row.get('item')}) and not restored{ended}: use another record"


def claim_problems(store, claim, live_walks) -> list:
    """`[problem]`: why `claim` is refused (each names the holder walk, the item and the state), `[]` when it can be granted. `store` is
    the rows of `claims_of`, `live_walks` the ids `held_walk_ids` reads (live walks and walks not opened yet). INVARIANT: never two live walks hold one instance `in_use`; the
    error direction is a needless refusal (a wait, another record), never a double grant."""
    return [_blocker_text(row, state) for row, state in _blockers(store, claim, set(live_walks))]


def update_claims(task_root, change, wait_s=None):
    """The ONE writer of the claims list (with `walk_pool.assign_entities`, which calls it): `change(rows) -> (new rows | None, result)` runs
    under `event_store.hold_file_lock` (AR-15), and a `None` writes nothing. Returns `(problem, result)`: a list that cannot be read is a
    non-empty `problem` and no `result` (nothing was written, nothing granted: the caller refuses). A lock not got in `wait_s` raises
    TimeoutError (nothing was written)."""
    path = claims_path(task_root)
    wait_s = CLAIM_LOCK_WAIT_S if wait_s is None else wait_s
    try:
        with event_store.hold_file_lock(path.with_suffix(".lock"), wait_s, purpose="walk claims", record_holder=False, poll_s=0.05):
            rows, problem = claims_of(task_root)
            if problem:
                return (f"the record of claims cannot be read: {problem}. Nothing was written and nothing was granted. Tell the person: "
                        "the walkers cannot share records until the list of claims is readable"), None
            new, result = change(rows)
            if new is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                event_store.atomic_json(path, {"claims": new})
            return "", result
    except event_store.LockBusy as exc:
        raise TimeoutError(f"the list of claims is held by another walker for over {wait_s:g} s: nothing was written. "
                           f"Repeat the step; {exc.holder_clause}") from exc
    except event_store.LockBroken as exc:
        raise TimeoutError(str(exc)) from exc


def _release_claims(walk, item=None, teardown=False) -> int:
    """Move the `in_use` claims of `walk` (a `Walk`) on: with an `item` (its verdict is stored) those of the item go `free` only when
    `teardown` is True - the case names a teardown AND the stored verdict says `"teardown": "done"` (B1: the walker's own word that the
    record was restored) - else `dirty`, changed and not restored; with no item (the walk ends) every one left goes `dirty`.
    Returns how many moved. Never raises: a failure is a note of the walk, and a claim not released stays held until the walk ends, when
    the shutdown (or a reader that finds the walk gone) reads it `dirty` - the safe direction."""
    try:
        mine, problem = claims_of(walk.task_root, walk.walk)
        if problem:
            walk.notes.append(f"claims were not released: {problem}")
            return 0
        if not any(r["state"] == "in_use" and (item is None or r.get("item") == item) for r in mine):
            return 0        # nothing of this walk to move: no lock is taken, no file is made (a walk that never claimed runs as before)
        state = "free" if item is not None and teardown else "dirty"

        def change(rows):
            moved = [{**r, "state": state, "at": MC._now()} if r["walk"] == walk.walk and r["state"] == "in_use"
                     and (item is None or r.get("item") == item) else r for r in rows]
            return moved, sum(1 for a, b in zip(rows, moved) if a is not b)
        problem, moved = update_claims(walk.task_root, change)
        if problem:
            walk.notes.append(f"claims were not released: {problem[:160]}")
        return moved or 0
    except Exception as exc:  # noqa: BLE001 - the release never stops a verdict or a shutdown
        walk.notes.append(f"claims were not released: {type(exc).__name__}: {str(exc)[:160]}")
        return 0


def settle_unopened(task_root, walk, state="dirty") -> tuple:
    """`(moved, problem)`: the ONE exit of a walk that never opened (t-2174 §10, critic R1; AR-25: a held row always has an exit). The `in_use`
    rows `walk_pool.assign_entities` wrote for `walk` before its record existed go to `state` (`dirty` by default: the lane may still have run
    on the recorder and changed the record; `free` for a reservation no dispatch ever took). A walk that HAS a record is not touched (its own
    verdict and shutdown release its rows), so this is safe to call at every place a dispatch ends. Never raises: a failure is the `problem`
    in words, and the rows then read as before (held, until the next entry settles them)."""
    try:
        if _has_record(task_root, walk):
            return 0, ""
        mine, problem = claims_of(task_root, walk)
        if problem:
            return 0, f"claims of walk {walk} were not settled: {problem}"
        if not any(r["state"] == "in_use" for r in mine):
            return 0, ""        # no row of this walk: no lock, no file

        def change(rows):
            moved = [{**r, "state": state, "at": MC._now()} if r["walk"] == str(walk) and r["state"] == "in_use" else r for r in rows]
            return moved, sum(1 for a, b in zip(rows, moved) if a is not b)
        problem, moved = update_claims(task_root, change)
        return (moved or 0), (f"claims of walk {walk} were not settled: {problem[:160]}" if problem else "")
    except Exception as exc:  # noqa: BLE001 - settling never stops a lane
        return 0, f"claims of walk {walk} were not settled: {type(exc).__name__}: {str(exc)[:160]}"


def _fit(full, limit, path_rel) -> dict:
    """The answer a role is sent: the full answer when it fits `limit`, else narrowed step by step (the stopped step, its reason and the
    `not_run` count are never cut) with a `cut` line naming the file that holds it whole."""
    text = json.dumps(full, ensure_ascii=True)
    if len(text) <= limit:
        return full
    out = dict(full)
    stages = (lambda o: o.get("page") and o.__setitem__("page", {**o["page"], "excerpt": str(o["page"].get("excerpt") or "")[:200]}),
              lambda o: o.__setitem__("steps", [{k: v for k, v in s.items() if k != "surprise"} for s in o.get("steps", [])]),
              lambda o: o.__setitem__("steps", [{**s, "step": s["step"][:80]} for s in o.get("steps", [])]),
              lambda o: o.__setitem__("not_run", o.get("not_run", [])[:3]) if "not_run" in o else None,
              lambda o: [o.pop(k, None) for k in ("console", "limitations", "captures", "last_excerpt", "final")],
              lambda o: o.__setitem__("steps", o.get("steps", [])[-3:]),
              lambda o: o.get("page") and o.__setitem__("page", {"url": o["page"].get("url"), "snapshot_file": o["page"].get("snapshot_file")}),
              lambda o: o.get("stopped_at") and o["stopped_at"].update(detail=str(o["stopped_at"].get("detail"))[:120], facts=o["stopped_at"].get("facts", [])[:2]),
              lambda o: o.__setitem__("steps", o.get("steps", [])[-1:]))
    for stage in stages:
        stage(out)
        if len(json.dumps(out, ensure_ascii=True)) <= limit - 120:
            break
    left = max(0, len(text) - len(json.dumps(out, ensure_ascii=True)))
    out["cut"] = f"[cut: {left} more chars in {path_rel}]"
    return out


# --------------------------------------------------------------------------------------------
# the walk
# --------------------------------------------------------------------------------------------

class _Sink:
    """Where the session-level stand probe writes (it has no attempt of its own): the rows are copied into each item attempt."""

    def __init__(self, task_root):
        self.task = Path(task_root).resolve()
        self.rows = []

    def probe(self, when, profile, command, value):
        self.rows.append({"at": MC._now(), "when": when, "profile": profile, "command": command, "probe": value})


class Walk:
    def __init__(self, task_root, walk, items, actors, *, parent_pid=0, parent_started="", port=0, reopened=0, notes=(), place="case", max_shared=1, env=None):
        self.task_root, self.walk, self.place = Path(task_root).resolve(), str(walk), place
        self.env = env      # FL-1 A: the NAME of the environments[] row to walk (`--env`), exactly; None = the first row, as before
        self.hosts = set()           # the hosts of the walk's stand, set by `_start`
        self.http_hosts = set()      # B2: the hosts of the walk's OWN stand only (`self.stand`): where an `http` step may send and a Bearer token may go
        self.screenless = False      # FL-1 B: a survey walk of a project with no UI profile has no browser and walks by `http` steps (`_surface_profile`)
        self.max_shared = max(1, int(max_shared or 1))      # t-2147 C1: given by `open --max-shared`; an old caller reads 1 (the class default)
        self.items, self.actors = list(items), list(actors)
        self.token, self.port = secrets.token_hex(32), port
        self.parent_pid, self.parent_started, self.reopened = int(parent_pid or 0), str(parent_started or ""), reopened
        self.pid = os.getpid()
        self.started = execution_scheduler._started(self.pid)
        self.state, self.reason, self.notes, self.cause = "opening", "", list(notes), ""
        self.busy = threading.Lock()
        self.running, self.last_call, self.current, self.role_done = None, None, None, False
        self.backends, self.accounts, self.sessions, self.item_rec, self.blocked = {}, {}, {}, {}, {}
        self.spec = MC.spec()
        self.cfg, self.stand, self.project_root = {}, {}, None      # set by `start`; a request that arrives earlier meets the `not ready` answer
        self.sink = _Sink(self.task_root)
        self.stack = contextlib.ExitStack()
        self.started_at = _clock()
        self.last_request = self.started_at

    # --- small readers -----------------------------------------------------------------------
    @property
    def d(self) -> dict:
        return data()

    @property
    def surface(self) -> str:
        """The word the stand probe records for this walk: `ui`, or `http` for a walk with no screen."""
        return "http" if self.screenless else "ui"

    def log(self, text):
        path = record_path(self.task_root, self.walk).with_suffix(".log")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(f"{MC._now()} {text}\n")

    def actor_of(self, req):
        return str(req.get("actor") or self.actors[0])

    def verdict_path(self, item) -> Path:
        return self.task_root / "work" / "walks" / self.walk / f"{MC.case_dir_name(item)}.json"

    def batch_path(self, item, n) -> Path:
        return walk_dir(self.task_root, self.walk) / "batches" / f"{MC.case_dir_name(item)}-b{n}.json"

    def rel(self, path) -> str:
        return Path(path).resolve().relative_to(self.task_root).as_posix()

    def busy_text(self) -> str:
        run = self.running
        where = (f"call {run['batch']} of item {run['item']} is running: step {run['k'] + 1} of {run['n']} since {run['since']}; "
                 f"its answer is stored at {run['file']}") if run else "a call has just been accepted and is starting"
        return f"{where}. Wait for its answer (it is also stored at the file named) or ask `walk_session.py status --walk {self.walk}`"

    def write_state(self):
        sessions = {a: {k: v for k, v in s.items()} for a, s in self.sessions.items()}
        first = sessions.get(self.actors[0], {})
        record = {"walk": self.walk, "pid": self.pid, "started": self.started, "port": self.port, "token": self.token,
                  "parent_pid": self.parent_pid, "parent_started": self.parent_started, "actors": self.actors, "items": self.items,
                  "state": self.state, "reason": self.reason, "signed_in": bool(first.get("signed_in")), "landed_on": first.get("landed_on", ""),
                  "sessions": sessions, "reopened": self.reopened, "notes": self.notes, "role_done": self.role_done,
                  "last_call": self.last_call, "blocked": self.blocked, "place": self.place, "cause": self.cause,
                  "max_shared": self.max_shared,
                  # FL-1 A (what `capture_cited` reads): the stand the walk is on, the test profile of its UI, the attempt of every item opened
                  "stand": str(self.stand.get("name") or ""),
                  "profiles": {self.surface: getattr(self, "profile", "")} if getattr(self, "profile", "") else {},      # FL-1 B: `http` for a walk with no screen
                  "attempts": {i: r["attempt"].name for i, r in self.item_rec.items()}}
        event_store.atomic_json(record_path(self.task_root, self.walk), record)

    # --- start / end -------------------------------------------------------------------------
    def start(self):
        """Lease, stand probe, one browser context per actor, sign-in by code only where gate A proved it. A `ServerDead` leaves nothing open."""
        try:
            self._start()
        except BaseException as exc:
            self.cause = getattr(exc, "cause", "")
            self._shutdown("dead", getattr(exc, "reason", None) or f"{type(exc).__name__}: {str(exc)[:200]}", probe=False)
            raise
        self.state = "ready"
        self.write_state()

    def _start(self):
        try:
            self.cfg, self.project_root = MC.load_config(self.task_root)
            if self.env is None:
                self.stand = next((e for e in self.cfg.get("environments") or [] if isinstance(e, dict)), {})
                self.hosts = set(MC.stand_hosts(self.cfg, root=self.project_root))      # a screen walk without --env keeps every stand's hosts, as before
            else:
                self.stand, problem = env_row(self.cfg, self.env)
                if problem:
                    raise ServerDead(problem)
                self.hosts = set(MC.stand_hosts({**self.cfg, "environments": [self.stand]}, root=self.project_root))      # the named stand's hosts ONLY (AR-4)
            self.http_hosts = set(MC.stand_hosts({**self.cfg, "environments": [self.stand]}, root=self.project_root))
            self.profile = self._surface_profile()
            self.timeout_s, self.element_s = MC.timeout_for(self.stand), MC.element_wait_for(self.cfg)
            if self.screenless:       # no browser: no sign-in page, no landing rule (the actor signs in by the HTTP request, `_open_actor`)
                self.recipe, url_not = {}, ()
            else:
                self.recipe = MC.login_recipe(self.cfg, self.spec, "ui")
                url_not = MC.landing_rule(self.recipe)[0]
                if (problem := MC.recipe_rows_problem(self.recipe)):
                    raise ServerDead(problem)
        except ValueError as exc:
            raise ServerDead(str(exc)) from None
        try:
            if self.place in LIFE_LEASE_PLACES:
                self.stack.enter_context(self._hold_walk())
                self._open_actors(url_not)
            else:
                with self.page_lease():             # an S7 lane holds the lease for the start only (U0): sign-in and the start probe touch the stand
                    self._open_actors(url_not)
        except MC.StandHeld as held:
            raise ServerDead("the stand is held by another run: " + (self.log_tail() or "stand_busy"), held.code, "stand_busy") from None

    def _surface_profile(self) -> str:
        """The test profile the walk is about, and with it the walk's surface (FL-1 B, L1). A walk with a screen as before: the profile of a UI
        capture. A SURVEY walk whose project has none that fits a UI capture (`profile_none`) takes the one that fits an HTTP capture and has NO
        browser (`self.screenless`); none for either is the refusal `no_reachable_surface`, before any capture. Several UI profiles and no plan
        to choose is `profile_not_chosen` (a survey walk names it; the other places keep the refusal they had). A project with ONE profile of
        any kind walks with the screen, as before: `capture_profile` gives it for the UI."""
        try:
            profile = MC.capture_profile(self.cfg, self.task_root, self.items[0], "ui", None)
            if self.place == SURVEY:      # L-a: the one profile the UI capture gave fits HTTP and not UI (a single `api` profile): no browser
                rows = self.spec.get("capture_surfaces") or {}
                held = next((p for p in self.cfg.get("profiles") or [] if isinstance(p, dict) and str(p.get("profile_id")) == profile), None)
                if held is not None and not MC._fits_surface(held, rows.get("ui") or {}) and MC._fits_surface(held, rows.get("http") or {}):
                    self.screenless = True
            return profile
        except ValueError as exc:
            if self.place != SURVEY:
                raise
            words = self.spec.get("capture_words") or {}
            if str(exc).startswith(str(words.get("profile_none") or "\0").split("{", 1)[0]):
                try:
                    profile = MC.capture_profile(self.cfg, self.task_root, self.items[0], "http", None)
                except ValueError:
                    raise ServerDead("this project has neither a test profile that fits a UI capture nor one that fits an HTTP capture, so the "
                                     "walk has no surface: nothing was captured. Expected a profile in config.json `profiles[]` whose "
                                     "capabilities hold `web` or `api` (or a profile id `e2e-ui` / `api`)", 2, "no_reachable_surface") from None
                self.screenless = True
                return profile
            raise ServerDead(str(exc), 3, "profile_not_chosen") from None

    def _open_actors(self, url_not):
        try:
            MC.stand_probe(self.sink, self.cfg, self.project_root, self.profile, "start", self.surface, self.stand)
        except MC.EnvBlocked as exc:
            raise ServerDead(f"{exc.row['probe_line']}. {exc.row['remedy']}") from None
        base = walk_dir(self.task_root, self.walk) / "sessions"
        for actor in self.actors:
            number = 1 + max([int(m.group(1)) for p in base.glob(f"{MC.actor_slug(actor)}-*") if (m := re.search(r"-([0-9]+)$", p.name))] or [0])
            self._open_actor(actor, MC.ActorSession(self.task_root, actor, folder=base / f"{MC.actor_slug(actor)}-{number}"), url_not)
        for actor, block in self.blocked_blocks.items():
            for item in self.items:
                attempt = self._new_attempt(item, with_probe=False)
                attempt.env_blocked(item, block.row)
                self.blocked.setdefault(actor, {})[item] = attempt.name

    blocked_blocks: dict = {}

    def _open_actor_http(self, actor, session):
        """A walk with no screen (FL-1 B, J-18): the actor's session is a request client. A named actor signs in ONCE, by the HTTP request
        the project's record says (`_http_login`: the named actor's own stored account, any account the factory has, not only `default`);
        the token stays in memory. No account, no HTTP sign-in the factory knows, or no token: the walk OPENS, the session says `signed_in:
        false` with the door, and every `http` step of that actor ends `failed` (`http_sign_in_unknown: <actor>: <door>`) before it sends -
        the runner then records the requirement that needs the sign-in as unreachable (access), without a question to the person."""
        backend = MC.HttpOnlyBackend(client=MC.HTTP or MC.UrllibHttp(), hosts=self.http_hosts)
        self.backends[actor] = backend
        info = {"state": "ready", "signed_in": False, "landed_on": "", "folder": self.rel(session.dir)}
        login = None
        if actor != GUEST:
            door = ""
            try:
                login = MC.read_login(self.cfg, self.project_root, actor=actor, stand=self.stand, task_root=self.task_root)
                if login is None:
                    door = "config.json names no file for the stand's accounts (environment.env_file), so the account of this actor cannot be read"
                else:
                    backend.token = MC._http_login(backend.client, self.stand, login, self.spec, self.cfg, self.timeout_s, self.project_root)
                    info["signed_in"] = True
            except MC.EnvBlocked as exc:
                door = f"{exc.row['probe_line']}. {exc.row['remedy']}"
            except (ValueError, MC.StepFailed, MC.StepTimeout) as exc:
                door = str(exc) or exc.__class__.__name__
            if door:
                info["note"] = "opened unsigned (the factory's): " + door[:300]
                backend.sign_in_problem = f"http_sign_in_unknown: {actor}: {door[:300]}"
        self.sessions[actor] = info
        self.accounts[actor] = MC.SessionAccount(login, self.stand, self.project_root, self.task_root, ())

    def _open_actor(self, actor, session, url_not):
        if self.screenless:
            return self._open_actor_http(actor, session)
        try:
            backend, _ = MC._new_backend(argparse.Namespace(in_harness=True), self.cfg, self.project_root, [])
            backend.open(self.timeout_s, self.hosts, self.recipe.get("local_storage"), self.element_s, profile_dir=session.profile)
        except ValueError as exc:
            raise ServerDead(str(exc)) from None
        self.backends[actor] = backend
        info = {"state": "ready", "signed_in": False, "landed_on": "", "folder": self.rel(session.dir)}
        login = None
        if actor != GUEST and self.recipe and not MC.login_declared_none(self.cfg, "ui"):
            if (why := MC.sign_in_refusal(self.task_root, actor, self.recipe)):
                info["note"] = "opened unsigned (the factory's): " + why.split("; nothing was opened")[0][:300]
            else:
                try:
                    login = MC.read_login(self.cfg, self.project_root, actor=actor, stand=self.stand, task_root=self.task_root)
                    result = MC.sign_in(backend, self.cfg, self.project_root, actor, self.stand, task_root=self.task_root, session=session,
                                        credentials=login, spec_data=self.spec, hosts=self.hosts, timeout_s=self.timeout_s)
                except MC.EnvBlocked as exc:
                    result = {"signed_in": False, "kind": "no_recipe", "detail": exc.row["probe_line"]}
                except ValueError as exc:
                    result = {"signed_in": False, "kind": "no_recipe", "detail": str(exc)[:200]}
                if result["signed_in"]:
                    info.update(signed_in=True, landed_on=MC._path_of(result.get("url") or ""))
                elif result.get("kind") == "not_landed":
                    info.update(state="dead", note="the sign-in was refused after the submit (the stand's): " + str(result.get("detail"))[:200])
                    self.blocked_blocks = {**self.blocked_blocks, actor: MC._session_blocked(result, login, MC._frontend_of(self.cfg, self.stand, self.project_root))}
                else:
                    info["note"] = "opened unsigned (the factory's): " + str(result.get("detail"))[:300]
        self.sessions[actor] = info
        self.accounts[actor] = MC.SessionAccount(login, self.stand, self.project_root, self.task_root, url_not)

    def log_tail(self) -> str:
        path = record_path(self.task_root, self.walk).with_suffix(".log")
        try:
            return path.read_text(encoding="utf-8")[-300:]
        except OSError:
            return ""

    def _shutdown(self, state, reason, probe):
        """Flush, (close: end probe into every item attempt), close the browsers, delete the profiles, release the lease. Never raises."""
        end_failed = ""
        try:
            for item in list(self.item_rec):
                self._flush(item)
            if probe:
                try:
                    MC.stand_probe(self.sink, self.cfg, self.project_root, self.profile, "end", self.surface, self.stand)
                except MC.EnvBlocked as exc:
                    end_failed = exc
                ends = [r for r in self.sink.rows if r["when"] == "end"]
                for item, rec in self.item_rec.items():
                    if end_failed:
                        rec["attempt"].env_blocked(item, end_failed.row)
                    for row in ends:
                        rec["attempt"]._append("probes.jsonl", dict(row))
        except Exception as exc:  # noqa: BLE001 - a failure of the end bookkeeping is said, the teardown goes on
            self.notes.append(f"end bookkeeping failed: {type(exc).__name__}: {str(exc)[:120]}")
        for backend in self.backends.values():
            with contextlib.suppress(Exception):
                backend.close()
        self.notes += _delete_profiles(walk_dir(self.task_root, self.walk))
        _release_claims(self)        # the walk ends: what it still holds `in_use` is changed and not restored (`dirty`)
        with contextlib.suppress(Exception):
            self.stack.close()
        self.state, self.reason = state, reason
        with contextlib.suppress(Exception):
            self.write_state()

    # --- items and evidence ------------------------------------------------------------------
    def item_root(self, item) -> Path:
        """The folder of an item's attempts: `case` -> the case root; `settle` -> the case root of `settle-<item>` (the one root of
        `manual_capture.py http|ui --case settle-<item>` too); `survey` -> the case root of `survey-<item>`; `control` -> `evidence/control-<item>/`, where
        `contract.triage_control_problems` looks for a control's output. Never created here: the first attempt creates it."""
        if self.place == "control":
            return self.task_root.joinpath(*CONTROL_PARTS, MC.case_dir_name(LANE_PREFIX["control"] + str(item)))
        return MC.case_root(self.task_root, LANE_PREFIX[self.place] + str(item))

    @contextlib.contextmanager
    def page_lease(self):
        """The stand lease of ONE request of an S7 lane (job `walk:<W>`), waiting at most `request_lease_wait_s`; `MC.StandHeld` beyond it.
        INVARIANT: no lease is held while no request runs, so the role's own `run_suite`, `red_sandbox` and `manual_capture http` never wait
        for its session."""
        run = self.cfg.get("run") if isinstance(self.cfg.get("run"), dict) else {}
        cfg = {**self.cfg, "run": {**run, "manual_stand_wait_s": int(self.d["request_lease_wait_s"])}}
        with MC._hold_stand(cfg, self.project_root, self.stand, f"walk:{self.walk}"):
            yield

    max_shared = 1          # walkers that may share the stand: given by whoever starts the walk (N5p), never read from the project here

    @contextlib.contextmanager
    def _hold_walk(self):
        """The lease of a whole case-lane or survey walk, in `walk` mode: up to `max_shared` walks of distinct jobs share the stand and no suite
        or capture does (E1b.1). One helper: `MC._hold_stand` with the mode passed through."""
        with MC._hold_stand(self.cfg, self.project_root, self.stand, f"walk:{self.walk}", mode="walk", max_shared=self.max_shared) as lease:
            yield lease

    def _stand_busy(self) -> dict:
        holder = {}
        with contextlib.suppress(Exception):
            import run_suite
            import stand_lease
            name = str(self.stand.get("name") or "").strip() or stand_lease.DEFAULT_ENVIRONMENT
            row = next((r for r in stand_lease.status(run_suite.project_root())["leases"] if r.get("environment") == name), {})
            held = next((h for h in row.get("holders") or [] if isinstance(h, dict) and h.get("state") != "gone"), {})
            holder = {k: held.get(src) for k, src in (("job_id", "job"), ("pid", "pid"), ("acquired_at", "acquired_at")) if held.get(src)}
        job = holder.get("job_id") or "another run"
        return {"status": "stand_busy", "holder": holder, "waited_s": self.d["request_lease_wait_s"],
                "door": f"the stand is in use by {job}; call again when your own run has ended"}

    def _new_attempt(self, item, with_probe=True):
        root = self.item_root(item)
        known = MC.attempts_of(root)
        name = f"a{MC.attempt_number(known[-1]) + 1}" if known else "a1"
        if self.place == "control":
            attempt = _RootedAttempt(self.task_root, LANE_PREFIX["control"] + str(item), name, self.cfg, root)
        else:
            attempt = MC.Attempt(self.task_root, item if self.place == "case" else LANE_PREFIX[self.place] + str(item), name, self.cfg)
        if with_probe:
            for row in (r for r in self.sink.rows if r["when"] == "start"):
                attempt._append("probes.jsonl", dict(row))
        return attempt

    def takes_new_item(self, item) -> bool:
        """t-2027 F8: a settle, control or survey lane takes any plain id the role names later (its own `new-<slug>`, a place the dispatch's draft
        names); a case lane never does. The same id test as `open`."""
        return self.place != "case" and lane_item_ok(item)

    def _open_item(self, item, actor):
        if item not in self.items and self.takes_new_item(item):
            self.items.append(item)
        if item not in self.item_rec:
            self.item_rec[item] = {"attempt": self._new_attempt(item), "item": item, "actor": actor, "marks": {}, "batches": 0, "started_at": MC._now()}
            self.write_state()      # FL-1 A: the record names the attempt (`attempts`) as soon as it exists, for `capture_cited`
        return self.item_rec[item]

    def _flush(self, item):
        """The requests of the item since its first step (or its last flush), into its own attempt (E1.13)."""
        rec = self.item_rec.get(item)
        for actor, mark in list((rec or {}).get("marks", {}).items()):
            try:
                MC._store_requests_seen(self.backends[actor], rec["attempt"], self.cfg, self.accounts[actor], since=mark)
            except Exception as exc:  # noqa: BLE001
                rec["attempt"].limitations.append(f"the log of the requests this item sent failed ({type(exc).__name__}: {str(exc)[:100]})")
        if rec:
            rec["marks"] = {}

    def _lift_failures(self, item):
        """TR1-2: the boundary between two items - every failing rule the item left is lifted and forgotten, and the result of each one still on
        (`requests failed: N`) goes into THAT item's evidence; the next item starts with none (a rule of item one is invisible to item two).
        A rule the item restored itself was stored when it was restored. A backend with no `forget_failures` (a device, an older fake) has none."""
        rec = self.item_rec.get(item)
        for actor, backend in self.backends.items():
            forget = getattr(backend, "forget_failures", None)
            if forget is None:
                continue
            try:
                seen = forget()
                for glob, record in seen.items():
                    if rec and record["active"]:
                        MC._store_failure(rec["attempt"], self.cfg, self.accounts[actor], glob, record)
            except Exception as exc:  # noqa: BLE001 - said in the item's own limitations, the switch goes on
                if rec:
                    rec["attempt"].limitations.append(f"the failing rules of this item were not lifted cleanly ({type(exc).__name__}: {str(exc)[:100]})")

    def _switch_to(self, item):
        if self.current not in (None, item):
            self._lift_failures(self.current)
            self._flush(self.current)
        self.current = item

    # --- the dispatcher ----------------------------------------------------------------------
    def dispatch(self, req, runner=None) -> tuple:
        """(exit code, answer). `runner(fn)` executes the page-touching work on the thread that owns the browser; with none the caller's thread does."""
        self.last_request = _clock()
        problems = request_problems(self, req)
        if problems:
            return _refusal(problems)
        op = req.get("op")
        if op == "status":
            return 0, self.status()
        if self.state != "ready":
            return 3, {"status": "not_ready", "state": self.state, "reason": self.reason,
                       "door": f"`walk_session.py status --walk {self.walk}` says what the walk left; a walk that is over is reopened by the driver"}
        if op in ITEM_OPS and self.sessions[self.actor_of(req)]["state"] != "ready":
            return 3, {"status": "not_ready", "state": "dead", "reason": f"the session of {self.actor_of(req)} is dead: " + str(self.sessions[self.actor_of(req)].get("note")),
                       "door": "see env_blocked.json of the item attempt; the sign-in was refused after the submit"}
        if not self.busy.acquire(blocking=False):
            return _refusal([self.busy_text()])
        try:
            with (self.page_lease() if self.place not in LIFE_LEASE_PLACES and op in LEASE_OPS else contextlib.nullcontext()):
                return (runner or (lambda fn: fn()))(lambda: self._do(op, req))
        except MC.StandHeld:
            if op == "close":       # t-2027 F4: a session that cannot close would outlive its dispatch by max_s; it shuts down without the end probe
                return (runner or (lambda fn: fn()))(lambda: self.op_close(req, probe=False))
            return 3, self._stand_busy()
        finally:
            self.busy.release()

    def status(self) -> dict:
        return {"status": "ok", "op": "status", "walk": self.walk, "state": self.state, "reason": self.reason, "actors": self.sessions,
                "items": {i: {"attempt": r["attempt"].name, "batches": r["batches"]} for i, r in self.item_rec.items()},
                "running": self.running, "last_call": self.last_call, "notes": self.notes, "reopened": self.reopened}

    def _do(self, op, req) -> tuple:
        try:
            return getattr(self, f"op_{op}")(req)
        except Exception as exc:  # noqa: BLE001 - the recorder broke under a call: said, the session stays as it is
            self.log(f"op {op} raised {type(exc).__name__}: {exc}")
            return 1, {"status": "error", "op": op, "detail": f"{type(exc).__name__}: {str(exc)[:300]}"}

    def op_item(self, req) -> tuple:
        item = req["item"]
        self._switch_to(item)
        rec = self._open_item(item, self.actor_of(req))
        return 0, {"status": "ok", "op": "item", "item": item, "attempt": rec["attempt"].name, "dir": self.rel(rec["attempt"].dir)}

    def op_step(self, req) -> tuple:
        item, actor = req["item"], self.actor_of(req)
        self._switch_to(item)
        rec = self._open_item(item, actor)
        backend, account, attempt = self.backends[actor], self.accounts[actor], rec["attempt"]
        if rec.get("last_actor") not in (None, actor):      # the attempt is shared by the actors: a typing chain is one actor's page (TR4-9)
            attempt.type_chain = attempt.type_prior = None
        rec["last_actor"] = actor
        steps = MC.parse_steps(req["steps"], self.spec, need_goto=False, http_ok=True)
        for one in steps:
            if one["word"] in self.http_words():      # the address the request goes to, resolved on THIS walk's stand (`request_problems` checked it)
                one["url"] = http_url(one["args"][1], self.stand)[0]
                one["hosts"] = sorted(self.http_hosts)      # B2: the step is sent on the walk's own stand only, never on another stand's host
        added = self._with_pre_action(rec, actor, steps)
        rec["batches"] += 1
        batch, path = rec["batches"], self.batch_path(item, rec["batches"])
        attempt.call_surprises, attempt.watches, attempt.last_input, attempt.blocked_seen = [], {}, None, set()
        lim0, caps0 = len(attempt.limitations), MC._count_captures(attempt)
        started = _clock()
        stop = CallStop(stop_rules([str(t) for t in req.get("stop_on") or []], self.d), started, self.d, len(steps))
        self.running = {"item": item, "batch": batch, "n": len(steps), "k": 0, "since": MC._now(), "file": self.rel(path)}
        if not self.screenless:      # a walk with no screen sees no page requests: nothing to flush into the item's attempt
            rec["marks"].setdefault(actor, backend.event_mark() if hasattr(backend, "event_mark") else 0)
        account.preload(self.cfg, [s["args"][1] for s in steps if s["word"] == "fill-account"])
        crashed = ""
        try:
            MC._run_steps(backend, attempt, steps, self.timeout_s, self.cfg, self.spec, self.element_s, account, stop=_Counting(stop, self.running))
        except Exception as exc:  # noqa: BLE001 - what ran is in the rows; the rest did not run
            crashed = f"the recorder raised {type(exc).__name__}: {str(exc)[:200]}"
            stop.hit = stop.hit or {"reason": "failed", "detail": crashed, "facts": [], "k": max(stop.k, 1), "step": steps[max(stop.k, 1) - 1]["line"]}
        finally:
            self.running = None
        rows, hit = stop.rows, stop.hit
        answer = {"status": "stopped" if hit else "done", "walk": self.walk, "item": item, "batch": batch}
        if hit:
            answer["stopped_at"] = {"k": hit["k"], "step": hit["step"], "reason": hit["reason"], "detail": hit["detail"][:300], "facts": hit["facts"]}
            answer["not_run_count"] = len(steps) - len(rows)
        answer["steps"] = [{"k": i + 1, "step": r.get("step"), "outcome": r.get("outcome"), **({"surprise": r["surprise"]} if r.get("surprise") else {}),
                            **({"told": r["told"]} if r.get("told") else {})}
                           for i, r in enumerate(rows)]
        answer["last_excerpt"] = str((rows[-1].get("text") if rows else "") or "")[:300]
        answer["console"] = [s["fact"] for s in attempt.call_surprises if s.get("kind") == "console"][:5]
        answer["limitations"] = attempt.limitations[lim0:]
        answer["captures"] = [c["path"] for c in attempt._lines("captures.jsonl")[caps0:]]
        answer["answer_file"] = self.rel(path)
        if added:
            answer["added_step"] = added
        if hit:
            answer["not_run"] = [s["line"] for s in steps[len(rows):]]
            answer["page"] = self._snapshot(rec, actor, batch, hit["k"])
            if req.get("final"):
                answer["final"] = "no final: the call stopped"
        elif req.get("final"):
            answer["final"] = self._take_final(rec, actor)
        path.parent.mkdir(parents=True, exist_ok=True)
        event_store.atomic_json(path, answer)
        self.last_call = {"item": item, "batch": batch, "status": answer["status"], "file": self.rel(path)}
        self.write_state()
        return (1 if hit else 0), _fit(answer, self.d["batch_answer_chars"], self.rel(path))

    def _with_pre_action(self, rec, actor, steps) -> str:
        """Put `capture pre_action <pre_label>` into `steps` (in place, renumbered) before the item's FIRST action that is not a `goto`, when
        the attempt holds no pre_action yet: the picture of "before" is evidence a role cannot take afterwards (P26: code writes the
        evidence, F1). Returns the line added, "" when nothing was. INVARIANT: never while the sign-in window is open (a capture there is
        refused and would stop the batch), and never past a `fill-account` of the same call (the sign-in comes first; the role's own
        `capture pre_action` after it is the door, named by the verdict's refusal); an item whose steps never reach an action gets none; and
        never once the attempt holds an action beyond the sign-in (`first_action_row`): a picture then is a false "before" (t-2022 N4)."""
        d, attempt = self.d, rec["attempt"]
        if self.accounts[actor].window or any(ME.PHASE_ALIAS.get(c.get("phase"), c.get("phase")) == "before" for c in attempt._lines("captures.jsonl")):
            return ""
        if first_action_row(attempt._lines("steps.jsonl"), d) >= 0:        # N4: the page was acted on already: a picture now is no "before"
            return ""
        acting = acting_words(d)
        for at, step in enumerate(steps):
            if step["word"] == "fill-account":
                return ""
            if step["word"] in acting:
                line = f"capture pre_action {d['pre_label']}"
                steps.insert(at, MC.parse_steps(line, self.spec, need_goto=False, http_ok=True)[0])
                for number, one in enumerate(steps, 1):
                    one["n"] = number
                return line
        return ""

    def http_words(self) -> list:
        """The step words that send a request (data `surprise.http_steps`): the words whose address `request_problems` resolves and checks."""
        return list(MC._surprise_data(self.spec, "http_steps"))

    def _snapshot(self, rec, actor, batch, k) -> dict:
        backend, account, attempt = self.backends[actor], self.accounts[actor], rec["attempt"]
        if self.screenless:
            return {"url": "", "snapshot_file": None, "excerpt": "no snapshot: this walk has no screen (the answer's `last_excerpt` is the head of the last response)"}
        page = {"url": MC._safe_url(MC._url_of(backend)), "snapshot_file": None}
        if account.window:
            return {**page, "excerpt": "no snapshot: the sign-in window is open"}
        try:
            text, form, why, _took = backend.look(None)
        except Exception as exc:  # noqa: BLE001
            return {**page, "excerpt": f"no snapshot: the page could not be read ({type(exc).__name__})"}
        if text is None:
            return {**page, "excerpt": "no snapshot: the page could not be read"}
        kept = {}

        def says(body, made):
            kept.update(body=body, path=made["path"])
            return "stop snapshot"
        entry = MC._store_device_text(attempt, {"line": f"stop snapshot {batch}.{k}", "word": "look"}, account, self.cfg, "state", f"stop-{batch}-{k}",
                                      str(text).rstrip("\n") + "\n", ".txt", max_bytes=MC._look_limit(self.cfg, self.spec),
                                      cut_note="[cut: {k} more lines not stored]", head="form: aria\n" if form == "aria" else "form: text\n", says=says)
        if entry["outcome"] != "ok":
            return {**page, "excerpt": "no snapshot: " + str(entry["detail"])[:200]}
        return {**page, "snapshot_file": kept["path"], "excerpt": " ".join(kept["body"].split())[:self.d["stop_look_chars"]]}

    def _run_words(self, rec, actor, text) -> list:
        backend, account, attempt = self.backends[actor], self.accounts[actor], rec["attempt"]
        out = []
        for step in MC.parse_steps(text, self.spec, need_goto=False, http_ok=True):
            caps0 = MC._count_captures(attempt)
            entry = MC._run_step(backend, attempt, step, self.timeout_s, self.cfg, self.spec, self.element_s, account)["entry"]
            account.watch(backend)
            out.append({"step": entry["step"], "outcome": entry["outcome"], "detail": str(entry["detail"])[:300],
                        "captures": [c["path"] for c in attempt._lines("captures.jsonl")[caps0:]]})
        return out

    def _take_final(self, rec, actor):
        if self.accounts[actor].window:
            return f"no final: {MC.NO_SHOT_IN_WINDOW}"
        out = self._run_words(rec, actor, f"look\ncapture post_action {self.d['final_label']}\n")      # the completion proof a pass needs (F1)
        self._flush(rec["item"])
        return out

    def op_look(self, req) -> tuple:
        item, actor = req["item"], self.actor_of(req)
        self._switch_to(item)
        rec = self._open_item(item, actor)
        selector = req.get("selector")
        out = self._run_words(rec, actor, "look" + (f" {shlex.quote(str(selector))}" if selector else ""))
        return (0 if out[0]["outcome"] == "ok" else 1), {"status": "ok" if out[0]["outcome"] == "ok" else "stopped", "op": "look", "item": item, "look": out[0]}

    def op_final(self, req) -> tuple:
        item, actor = req["item"], self.actor_of(req)
        self._switch_to(item)
        rec = self._open_item(item, actor)
        out = self._take_final(rec, actor)
        good = isinstance(out, list) and all(o["outcome"] == "ok" for o in out)
        return (0 if good else 1), {"status": "ok" if good else "stopped", "op": "final", "item": item, "final": out}

    def op_verdict(self, req) -> tuple:
        item = req["item"]
        if self.place == SURVEY:    # FL-1 A: a survey item is no case either; what the walk found goes through the commands that record a walk
            return _refusal([f"a {self.place} walk has no verdict: its item is not a case. Door: {SURVEY_DOOR}, not `walk_session.py verdict`"])
        if self.place != "case":    # t-1991 U3b: a verdict is a case's (it reads the CASE root of the bare item id); a settle or control item has none
            return _refusal([f"a {self.place} walk has no verdict: its item is not a case. Door: a place is answered with `place_answers.py write "
                             "--task-root <T> --dispatch <your dispatch id> --place <id> --file <answer.json>`, not with `walk_session.py verdict`"])
        rec = self._open_item(item, self.actor_of(req))
        self._flush(item)           # the requests seen are captures of the attempt: a quote may stand in them
        if (problems := verdict_problems(self.task_root, item, rec["attempt"].name, req["verdict"])):
            return _refusal(problems)
        stored = dict(actor=rec["actor"], attempt=rec["attempt"].name, started_at=rec["started_at"], ended_at=MC._now(),
                      index=self.items.index(item), batches=rec["batches"])
        if self.place == "case":        # F2: the rules of the case record, asked while the role can still act (one function with `validate`)
            self._look_when_empty(rec)
            made =walk_record_of(self.task_root, self.walk, item, req["verdict"], **stored)
            if (found := ME.walk_rule_errors(self.task_root, item, made)):
                return _refusal([f"the case record of {item} would be refused: {e}" for e in found] + [PRE_DOOR])
        write_verdict(self.task_root, self.walk, item, req["verdict"], **stored)
        # C.5: only a STORED verdict releases the item's claims; B1: they go free only when the verdict itself says the teardown was done
        # (a refused verdict never gets here; `verdict_problems` takes only the exact words, so a stored `teardown` is one of TEARDOWN_WORDS)
        _release_claims(self, item, teardown=_names_teardown(self.task_root, item) and req["verdict"].get("teardown") == "done")
        return 0, {"status": "ok", "op": "verdict", "item": item, "file": self.rel(self.verdict_path(item))}

    def _look_when_empty(self, rec) -> None:
        """An attempt with NO capture takes one `look` before its verdict is built (t-2022 N1; P26: code writes the evidence): the case record
        is refused for an attempt that holds none, and a verdict with no step ("Case file: not found ... say so in its verdict", an item the
        walker declines to touch) would be accepted here and lost after the session. Not while the sign-in window is open (a capture there is
        refused): the record rule then names the door. A `look` that fails leaves the attempt as it is; the rule refuses with the door."""
        if attempt_rows(self.task_root, rec["item"], rec["attempt"].name)[1] or self.accounts[rec["actor"]].window:
            return
        self._run_words(rec, rec["actor"], "look")
        self._flush(rec["item"])

    def op_claim(self, req) -> tuple:
        """The walker says, BEFORE it changes a record of the app that other walkers could also use, which one (`kind` in its own words,
        `instance` its id or name as shown, or `all`: the whole collection of the kind, for a check whose Then reads the list). Granted
        when no other LIVE walk holds it `in_use` and nobody left it `dirty`; otherwise the call waits up to `claim_wait_s` (data),
        re-reading the list every CLAIM_POLL_S, and then refuses naming the holder walk, its item and the door (C.3: a claim never
        waits longer, so two walks that want each other's record each get the door). A dirty record is refused at once: waiting does not
        restore it. A list that cannot be read refuses and never grants. A settle, control or survey walk has no claims (axis 5)."""
        if self.place == SURVEY:    # FL-1 A F1: a survey walk holds the stand for its whole life, so the settle door and the lease wording are false for it
            return _refusal([f"a survey walk has no claims: it walks the stand alone. Door: {SURVEY_DOOR}"])
        if self.place != "case":
            return _refusal([f"claims are for case lanes: this is a {self.place} walk, which takes the stand lease per request and walks one item. "
                             "Door: a place is captured with `manual_capture.py ui|http --case settle-<place id>`; nothing here needs a claim"])
        item, kind = req.get("item"), fold_kind(req.get("kind"))
        whole, instance = bool(req.get("all")), req.get("instance")
        problems = []
        if item not in self.items:
            problems.append(f"item {item!r} is not in walk {self.walk} (items: {', '.join(self.items)}). `status --walk {self.walk}` lists them")
        if not kind:
            problems.append("a claim says what the record is: expected `--kind <what it is, in your own words>`, for example `--kind book`")
        if whole == (instance is not None):
            problems.append("a claim names ONE record or the whole list: give exactly one of `--instance <its id or name as the app shows it>` or `--all`")
        elif instance is not None and (not str(instance).strip() or str(instance).strip() == CLAIM_ALL):
            problems.append(f"the instance {cut_text(instance)!r} names no record: expected its id or name as the app shows it, or `--all` for the whole list")
        if problems:
            return _refusal(problems)
        claim = {"kind": kind, "instance": CLAIM_ALL if whole else str(instance), "walk": self.walk, "item": item}

        def grant(rows):
            held = held_walk_ids(self.task_root, rows) | {self.walk}       # read inside the lock: a walk that opens meanwhile is read by its record
            found = _blockers(rows, claim, held)
            if found:
                return None, ([state for _row, state in found], claim_problems(rows, claim, held))
            kept = [r for r in rows if not (r["walk"] == self.walk and fold_kind(r["kind"]) == kind and str(r["instance"]) == claim["instance"])]
            dirty[:] = _dirty_instances(rows, kind, held) if whole else []
            return [*kept, {**claim, "state": "in_use", "at": MC._now()}], None
        dirty: list = []
        started = _clock()
        deadline = started + float(self.d["claim_wait_s"])
        while True:
            try:
                problem, found = update_claims(self.task_root, grant)
            except TimeoutError as exc:
                return _refusal([str(exc)])
            except OSError as exc:      # N3: the write failed (atomic: nothing was written); the walker is told to repeat the step
                self.notes.append(f"claim not written: {type(exc).__name__}: {str(exc)[:160]}")
                return _refusal(["the list of claims could not be written: nothing was written. Repeat the step."])
            if problem:
                return _refusal([problem])
            if not found:
                self.last_request = _clock()
                answer = {"status": "ok", "op": "claim", "item": item, "kind": kind, "instance": claim["instance"], "waited_s": round(_clock() - started, 1)}
                if dirty:       # L1: a fact for the walker to judge, not a refusal: `--all` is granted over a dirty instance
                    answer["note"] = "changed earlier and not restored: " + cut_text(", ".join(dirty))
                return 0, answer
            states, problems_found = found
            if all(state == "dirty" for state in states) or _clock() >= deadline:
                self.last_request = _clock()
                return _refusal([f"{p}. {CLAIM_DOOR}" for p in problems_found])       # N2: the one builder of the refusal is `claim_problems`
            _sleep(CLAIM_POLL_S)

    def op_done(self, req) -> tuple:
        for item in list(self.item_rec):
            self._flush(item)
        self.role_done = True
        self.write_state()
        return 0, {"status": "ok", "op": "done", "walk": self.walk, "items": {i: r["attempt"].name for i, r in self.item_rec.items()}}

    def op_close(self, req, probe=True) -> tuple:
        if not probe:
            self.notes.append("closed while the stand was held by another job: the end probe was not taken")
        if self.place != "case":
            self._time_items()
        self._shutdown("closed", "closed by the driver", probe=probe)
        return 0, {"status": "ok", "op": "close", "walk": self.walk, "state": self.state, "notes": self.notes,
                   "items": {i: r["attempt"].name for i, r in self.item_rec.items()}}

    def _time_items(self) -> None:
        """t-2027 F8 (Stage 2 of t-1991): a settle, control or survey item has no verdict, so no timing line; the close writes one per item walked,
        with the lane's own place (the `walk_timing.py` grouping key). Never raises."""
        try:
            timing = self.task_root / "work" / "walks" / str(self.walk) / "timing.jsonl"
            kept = [r for r in MC.jsonl_rows(timing) if r.get("item") not in self.item_rec]
            lines = [timing_line(self.task_root, self.walk, item, rec["attempt"].name, index=self.items.index(item) if item in self.items else 0,
                                 started_at=rec["started_at"], ended_at=MC._now(), batches=rec["batches"], place=self.place)
                     for item, rec in self.item_rec.items()]
            timing.parent.mkdir(parents=True, exist_ok=True)
            timing.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [*kept, *lines]), encoding="utf-8", newline="\n")
        except Exception as exc:  # noqa: BLE001
            self.log(f"the timing of the {self.place} items was not written ({type(exc).__name__}: {str(exc)[:100]})")

    def watchdog(self) -> str:
        now, d = _clock(), self.d
        if self.place not in (d.get("idle_places_exempt") or ()) and now - self.last_request > d["idle_s"]:
            return f"idle for more than {d['idle_s']} s"
        if now - self.started_at > d["max_s"]:
            return f"open for more than {d['max_s']} s"
        if self.parent_pid and not execution_scheduler._same_process(self.parent_pid, self.parent_started):
            return "the process that opened the walk is gone"
        return ""


class _Counting:
    """Lets `status` and the busy refusal say which step of the call is running."""

    def __init__(self, stop, running):
        self.stop, self.running = stop, running

    def __call__(self, step, row, found, late=False):
        answer = self.stop(step, row, found, late=late)
        if not late:
            self.running["k"] = step["n"]
        return answer


# --------------------------------------------------------------------------------------------
# the server process
# --------------------------------------------------------------------------------------------

class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server
        with server.lock:
            server.inflight += 1
        try:
            req = json.loads(self.rfile.readline().decode("utf-8") or "{}")
            result = server.walk.dispatch(req, server.run_on_main)
            with contextlib.suppress(OSError):
                self.wfile.write((json.dumps({"exit": result[0], "answer": result[1]}, ensure_ascii=True) + "\n").encode("ascii"))
        except (ValueError, OSError):
            pass
        finally:
            with server.lock:
                server.inflight -= 1


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, walk):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.walk, self.jobs, self.lock, self.inflight = walk, queue.Queue(), threading.Lock(), 0

    def run_on_main(self, fn):
        box = {"done": threading.Event()}
        self.jobs.put((fn, box))
        box["done"].wait()
        if "error" in box:
            raise box["error"]
        return box["result"]


def serve(args) -> int:
    """Run the server until the walk is closed or dead. The main thread owns the browser: it runs every page-touching request."""
    items = [i for i in args.items.split(",") if i]
    actors = [a for a in (args.actor, args.actor2) if a]
    walk = Walk(args.task_root, args.walk, items, actors, parent_pid=args.parent_pid, parent_started=args.parent_started or "", reopened=args.reopened,
                 place=getattr(args, "place", "case"), max_shared=getattr(args, "max_shared", 1), env=getattr(args, "env", None))
    server = _Server(walk)
    walk.port = server.server_address[1]
    walk.write_state()
    note = _join_job() if args.own_process else ""
    if note:
        walk.notes.append(note)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        walk.start()
    except BaseException as exc:
        server.shutdown()
        walk.log(f"did not start: {getattr(exc, 'reason', exc)}")
        return getattr(exc, "code", 3) if isinstance(exc, ServerDead) else 3
    try:
        while walk.state == "ready":
            try:
                fn, box = server.jobs.get(timeout=min(float(walk.d["parent_check_s"]), 1.0))
            except queue.Empty:
                if (why := walk.watchdog()):
                    walk._shutdown("dead", why, probe=False)
                continue
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            box["done"].set()
        waited = 0.0
        while server.inflight and waited < 5:
            time.sleep(0.05)
            waited += 0.05
    finally:
        server.shutdown()
        server.server_close()
        if args.own_process:
            _kill_group()
    return 0


def _join_job() -> str:
    """Windows: assign this process to a job object that kills its children (node, chromium) when the job closes. POSIX: nothing here."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                        ("e", wintypes.DWORD), ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("io", ctypes.c_uint64 * 6), ("p", ctypes.c_size_t), ("j", ctypes.c_size_t), ("pp", ctypes.c_size_t), ("pj", ctypes.c_size_t)]
        kernel = ctypes.windll.kernel32
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
                or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
            return "no job object: a browser may outlive this server on a hard kill"
        _JOB.append(job)
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"no job object ({type(exc).__name__}): a browser may outlive this server on a hard kill"


def _kill_group() -> None:
    if os.name != "nt":
        with contextlib.suppress(OSError):
            os.killpg(os.getpgrp(), signal.SIGKILL)


# --------------------------------------------------------------------------------------------
# the client side: what the role's command does
# --------------------------------------------------------------------------------------------

def _print(answer):
    print(json.dumps(answer, ensure_ascii=True))


def call(task_root, walk, req) -> int:
    record = read_record(task_root, walk)
    req = {**req, "walk": walk}
    if (problems := request_problems(record, req)):
        code, answer = _refusal(problems)
    else:
        try:
            with socket.create_connection(("127.0.0.1", int(record["port"])), timeout=10) as link:
                link.settimeout(None)
                link.sendall((json.dumps({**req, "token": record.get("token")}) + "\n").encode("utf-8"))
                reply = json.loads(link.makefile("rb").readline().decode("utf-8") or "{}")
            code, answer = int(reply["exit"]), reply["answer"]
        except (OSError, ValueError, KeyError):
            code, answer = 3, {"status": "not_ready", "reason": "the server did not answer", "door": f"`status --walk {walk}`; a walk that is gone is reopened by the driver"}
    _print(answer)
    if code == 2:
        return refuse(f"walk_session.py {req.get('op')}", str(answer.get("text") or ""))
    return code


def open_walk(args, wait_s=None) -> int:
    task_root = Path(args.task_root).resolve()
    req = {"op": "open", "task_root": str(task_root), "walk": args.walk, "items": [i for i in args.items.split(",") if i],
           "actors": [a for a in (args.actor, args.actor2) if a], "place": getattr(args, "place", "case")}
    if (problems := request_problems(None, req)):
        code, answer = _refusal(problems)
        _print(answer)
        return refuse("walk_session.py open", answer["text"])
    env = getattr(args, "env", None)
    if env is not None:         # FL-1 A: a stand that is not named exactly is refused here, before a process is spawned (the server checks it again)
        with contextlib.suppress(ValueError, OSError):      # a config that cannot be read is the server's refusal, with its own words
            if (problem := env_row(MC.load_config(task_root)[0], env)[1]):
                _print(_refusal([problem])[1])
                return refuse("walk_session.py open", problem)
    old = read_record(task_root, args.walk)
    reopened = int(old.get("reopened", -1)) + 1 if old else 0
    parent = args.parent_pid or os.getppid()
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "serve", "--task-root", str(task_root), "--walk", args.walk, "--items", args.items,
            "--actor", args.actor, "--parent-pid", str(parent), "--parent-started", execution_scheduler._started(parent), "--reopened", str(reopened),
            "--place", req["place"]]
    if args.actor2:
        argv += ["--actor2", args.actor2]
    if env is not None:             # no flag, no `--env`: the old argv of every existing place
        argv += ["--env", env]
    if getattr(args, "max_shared", 1) != 1:        # t-2147 C1: the own process reads the same number; the default call stays the old argv
        argv += ["--max-shared", str(args.max_shared)]
    log = record_path(task_root, args.walk).with_suffix(".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    event_store.atomic_json(record_path(task_root, args.walk), {"walk": args.walk, "state": "opening", "pid": 0, "actors": req["actors"], "items": req["items"], "reopened": reopened, "place": req["place"],
                                                                         "max_shared": max(1, int(getattr(args, "max_shared", 1) or 1))})
    handle = (SEAMS["spawn"] or _spawn)(argv, log)
    deadline, limit = time.monotonic() + (wait_s if wait_s is not None else data()["open_wait_s"]), None
    while time.monotonic() < deadline:
        record = read_record(task_root, args.walk)
        if record.get("state") in ("ready", "dead", "closed") and record.get("pid"):
            limit = record
            break
        time.sleep(0.1)
    if limit is None or limit.get("state") != "ready":
        _kill(handle)
        why = (limit or {}).get("reason") or "it was not ready in time"
        tail = log.read_text(encoding="utf-8")[-300:] if log.is_file() else ""
        event_store.atomic_json(record_path(task_root, args.walk), {**(limit or read_record(task_root, args.walk)), "state": "dead", "reason": f"did not start: {why}"})
        _print({"status": "not_started", "walk": args.walk, "reason": why, "cause": (limit or {}).get("cause", ""), "log_tail": tail})
        if (limit or {}).get("cause") in REFUSED_CAUSES:      # FL-1 B: the project has no surface to walk: the call is refused (exit 2), not a session that failed
            return refuse("walk_session.py open", why)
        print(f"the walk session did not start: {why} {tail}".strip()[:300 + len(why)], file=sys.stderr)
        return 3
    _print({"status": "ready", "walk": args.walk, "state": "ready", "signed_in": limit["signed_in"], "landed_on": limit["landed_on"], "actors": limit["sessions"],
            "items": limit["items"], "reopened": limit["reopened"], "notes": limit["notes"]})
    return 0


def _spawn(argv, log):
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0       # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    out = open(log, "ab")
    return subprocess.Popen([*argv, "--own-process"], stdin=subprocess.DEVNULL, stdout=out, stderr=out, creationflags=flags,
                            start_new_session=(os.name != "nt"), close_fds=True)


def _kill(handle) -> None:
    with contextlib.suppress(Exception):
        if os.name == "nt" and getattr(handle, "pid", None):
            subprocess.run(["taskkill", "/PID", str(handle.pid), "/T", "/F"], capture_output=True)
        elif hasattr(handle, "pid"):
            os.killpg(handle.pid, signal.SIGKILL)
        else:
            handle.kill()


def _whole_one_or_more(text) -> int:
    """`--max-shared`: an int >= 1; anything else is a usage refusal that says what is expected."""
    try:
        value = int(str(text).strip())
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"`--max-shared` takes a whole number of 1 or more (got {text!r})")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = RefusingParser(prog="walk_session.py", command="walk_session.py", description=__doc__, epilog=epilog("walk_session.py"), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    for name in ("open", *OPS, "serve"):
        one = sub.add_parser(name, command=f"walk_session.py {name}")
        one.add_argument("--task-root", required=True, help="the story's folder, qa-factory/artifacts/<TICKET>")
        one.add_argument("--walk", required=True, help="the walk id (the dispatch id)")
        if name in ("open", "serve"):
            one.add_argument("--items", required=True, help="case ids, comma separated")
            one.add_argument("--actor", required=True, help="a handle of the stand's accounts, or guest")
            one.add_argument("--actor2")
            one.add_argument("--place", default="case", help="the lane of the walk: case (an S6 case, the default), settle (a place of the "
                             "failure analyst, root work/evidence/manual/settle-<id>/), control (a control experiment, root evidence/control-<id>/) "
                             "or survey (the first look at a story or a reference stand, root work/evidence/manual/survey-<id>/)")
            one.add_argument("--env", default=None, help="the NAME of the environments[] row of config.json to walk, spelled exactly (default: the "
                             "first row); only that stand's hosts are reachable")
            one.add_argument("--parent-pid", type=int, default=0, help="the process whose end ends the walk (default: the parent of this command)")
            one.add_argument("--max-shared", type=_whole_one_or_more, default=1, help="how many walkers may share the stand (a whole number of 1 or "
                             "more, default 1: this walk alone); given by the driver from `manual.walkers`")
        if name == "serve":
            one.add_argument("--parent-started", default="")
            one.add_argument("--reopened", type=int, default=0)
            one.add_argument("--own-process", action="store_true")
        if name in ITEM_OPS:
            one.add_argument("--item", required=True)
        if name in ("item", "step", "look", "final"):
            one.add_argument("--as", dest="actor", help="the actor of the walk this call acts as (default: the first)")
        if name == "step":
            one.add_argument("--steps-file")
            one.add_argument("--line")
            one.add_argument("--stop-on", help="comma separated stop rules: kinds, status:<lo>-<hi>, default, none, +rule, -rule")
            one.add_argument("--final", action="store_true", help="after the last step of a call that did not stop, take the final snapshot")
        if name == "look":
            one.add_argument("--selector")
        if name == "verdict":
            one.add_argument("--file", required=True, help="the verdict, a JSON object")
        if name == "claim":
            one.add_argument("--item", required=True, help="the item you are walking, the one the change belongs to")
            one.add_argument("--kind", required=True, help="what the record is, in your own words (compared without case or extra spaces)")
            one.add_argument("--instance", help="the record's id or name as the app shows it")
            one.add_argument("--all", action="store_true", help="the whole list of that kind, for a check whose Then reads the list other walkers change")
    return parser


def main(argv=None) -> int:
    args = hooklib.exact_options(build_parser()).parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        hooklib.story_of("walk_session.py", root=args.task_root, key_flag=None)
    except ValueError as exc:
        return refuse(f"walk_session.py {args.command}", str(exc))
    if args.command == "open":
        return open_walk(args)
    if args.command == "serve":
        args.own_process = getattr(args, "own_process", False)
        return serve(args)
    req = {"op": args.command, "item": getattr(args, "item", None), "actor": getattr(args, "actor", None)}
    if args.command == "step":
        if bool(args.steps_file) == bool(args.line):
            return refuse("walk_session.py step", "give exactly one of `--steps-file <file>` or `--line \"<one step>\"`")
        req["steps"] = args.line if args.line else Path(args.steps_file).read_bytes().decode("utf-8-sig")
        req["stop_on"] = [t.strip() for t in args.stop_on.split(",")] if args.stop_on is not None else []
        req["final"] = bool(args.final)
    elif args.command == "look":
        req["selector"] = args.selector
    elif args.command == "claim":
        req.update(kind=args.kind, instance=args.instance, all=bool(args.all))
    elif args.command == "verdict":
        try:
            req["verdict"] = json.loads(Path(args.file).read_bytes().decode("utf-8-sig"))
        except ValueError:
            req["verdict"] = None
    return call(args.task_root, args.walk, req)


if __name__ == "__main__":
    sys.exit(run_guarded(command_from_argv("walk_session.py"), main))
