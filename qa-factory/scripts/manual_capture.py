"""manual_capture.py - capture the evidence of a manual-agent case by code; the runner never types a file.

    python manual_capture.py http --task-root <T> --case <C> --method M --url U [--body-file F]
           [--header "K: V"]... [--state-url U2] [--phase pre_action|post_action|supporting]
           [--proves <word>]... [--attempt aN] [--profile <id>]
    python manual_capture.py ui   --task-root <T> --case <C> --steps-file S [--attempt aN] [--profile <id>]
    python manual_capture.py app  --task-root <T> --case <C> --steps-file S [--surface <id>] [--attempt aN] [--profile <id>]
           (the hands on a device stand; the steps are `app_steps` of references/manual-capture-steps.json)
    python manual_capture.py ui|http ... --session <actor>      (RN1-10: one browser profile per actor, kept between calls)
    python manual_capture.py session close --task-root <T> --case <C> [--attempt aN]

Sessions (RN1-10). `--session <actor>` (the forms of `--as`) keeps the actor's browser profile under
<attempt>/sessions/<actor-slug>/profile, so the cookies live between calls: the calls of one case and one `--profile` join ONE open attempt,
`ui` opens the page the last call ended on (`state.json`: `last_url`), and `http` sends through the profile's context
(its cookies, no Bearer login of the factory's) when it names the same `--profile` - without it `http` goes to its own `api`
attempt and signs in again. The sign-in is `sign_in` - the project's `login.ui` recipe, proven by
`await_landing` - and a session runs it only for a sign-in gate A PROVED (`state/sign-in-probe.json`, same recipe
fingerprint); else the call is refused (exit 2) before anything is opened. A proven sign-in that no longer lands is an
env_blocked of owner `environment`, cause `stand`, never `user`. A field of the recipe is `{"role","name"}` or
`{"test_id"}`. The profile holds credentials: `session close` deletes it, and `build` must come after.

Why it exists. The one manual-agent attempt the factory ever made (the driver's TC-011) ended in about
forty refused hand-written record files: the runner typed paths, hashes and phases it could get wrong,
and the validator refused each one. The runner now says WHAT to do; this script does it, hashes what it
saved, and `manual_evidence.py build` assembles the record from those files.

What it writes, under <T>/work/evidence/manual/<case>/<attempt>/ (`area/TC` is the directory `area__TC`;
an attempt is `a1`, `a2` ... and ONE stand identity brackets it: one profile per attempt - a call
without --attempt opens a new attempt when the open one holds captures of ANOTHER test profile (a project with one
profile joins the open attempt), and says so on stderr):
    NNN-<label>.png|json|txt|log   the evidence files (images, request+response, state, DOM reads, logs)
    captures.jsonl                 one line per file: {path, content_hash, kind, phase, captured_at,
                                   proves, command, limitation?}; the hash is over the stored bytes
    steps.jsonl                    one line per step run: {at, command, step, outcome ok|failed|timeout|
                                   refused, detail}; `build` turns it into `steps_actual`
    probes.jsonl                   the stand's runtime probe at the start and at the end of each call
    env_blocked.json               written only when a probe was unmatched or failed, or the login by code did
                                   not land (`do_not_retry`): no record then

Stdout is ONE JSON object, ASCII-escaped (a caller parses it - FR-14); the files are UTF-8. Exit codes:
0 every step ran; 1 a step failed or timed out (the evidence of it is saved, `failed` names the step);
2 refused (stderr says what is wrong, what to write, how to prove it); 3 the stand is held by another run
(`{"status": "stand_busy", ...}` on stdout, nothing opened: call again when it is free; every `ui`, `http` and `app` call holds the
stand's lease while it runs), or the stand could not be
identified, or the login by code did not land (`env_blocked` names the probe or the login line; no record is
possible for this attempt; a login that did not land also carries `do_not_retry` and an owner: `user` (the account
was refused after the submit) - make no further capture of any kind in this block, put the case in env_blocked[]
with the printed `login by code: ...` line and halt the block; `factory` (the recipe did not fit the page) - you may
sign in ONCE through `fill-account` steps in a new attempt, then the same halt; never `build` a blocked attempt).

The agent drives the UI as a user. After every step (the first 40) the summary's `steps[]` row also carries
`screenshot` and `text`: the screen of a passed step is saved in <attempt>/observe/ (not in captures.jsonl, so
never in the record) with a short excerpt (<= 160 chars; a failed step: its own screenshot, <= 600); the sum of the
excerpts is <= 8000 (`observation_trimmed`). `fill-account <selector> <actor> user|secret` types an account (value
read by code); from the first one until the URL leaves the sign-in addresses no screen is saved and no capture runs.
`fill-new-account <selector> user|secret [template]` makes a NEW account on a stand that may be changed (`safe_to_break`):
`user` generates the pair, records it under a lock and types the name (the template is `{generated_username}` plus what the
form needs, e.g. `{generated_username}@example.test`); `secret` types the same pair's password. It opens the same window.
The account is recorded `unconfirmed` and is an identity (`created:<name>`) only once a step other than `goto` shows a page whose
path differs from the form's; an app that answers on the same address stays `unconfirmed`.

Login: done here, and PROVEN to have landed (`login.ui.landed` in references/manual-capture-steps.json: the URL
holds none of `url_not` and the session cookie exists). Submitting the form is not signing in: on the local
stand the page stays on /auth/sign-in for about three seconds after the click, and a `goto` in that window cuts
the login off (measured 02.10, rehearsal/11-login-probe.txt).

Secrets: login is done here from the stand's `.env` named in config (never printed, never stored);
Authorization, Cookie and Set-Cookie values are replaced by [redacted] in every saved request and
response; a saved text that matches a config `secret_content_patterns` entry is NOT saved - the refusal
names the pattern's index, never the match.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.client
import json
import math
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grammar as G
import hooklib
import stand_lease
from profile_contract import (ACCEPTS, acceptable_provenance, command_argv, content_differs, person_confirmed, profile_commands,
                              refusal_text, say_refusal, stand_runs_other_build)
from role_cli import EXIT_REFUSED, command_from_argv, epilog, refuse, run_guarded

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PLUGIN_ROOT / "references" / "manual-capture-steps.json"
EVIDENCE_PARTS = ("work", "evidence", "manual")

BODY_CAP = 2 * 1024 * 1024          # a body is stored whole up to this many bytes, cut beyond it
DEFAULT_TIMEOUT_S = 180             # the limit of one step when the stand's page load was never measured
TIMEOUT_MARGIN_S = 30               # added to the measured full page load of the stand
ELEMENT_WAIT_S = 30                 # how long an element lookup (click, fill, drag, read, wait <selector>) may take:
                                    # the page objects' own upper wait; config manual_capture.element_wait_s overrides
EXIT_OK, EXIT_FAILED_STEP, EXIT_ENV_BLOCKED = 0, 1, 3
SUMMARY_DETAIL_CHARS = 300          # what one step line keeps of a read value; the file keeps it whole
LANDING_POLL_S = 0.25               # how often the landing is looked at after the sign-in click
LANDING_WORDS_CHARS = 120           # how much of the page's words a failed login keeps
COVER_TEXT_CHARS = 60               # how much of a covering element's text a failed step names
COVER_SCAN_CHARS = 500              # how much of it is read, so the secret scan sees more than is shown
OBSERVE_MAX_STEPS = 40              # steps observed (screenshot + excerpt); from the next one only the outcome
OBSERVE_OK_CHARS = 160              # the excerpt after a step that passed (cut with `...`)
OBSERVE_FAIL_CHARS = 600            # after a step that did not; never trimmed by the total
OBSERVE_TOTAL_CHARS = 8000          # the excerpts of one call's summary; the oldest passed ones are emptied beyond it
OBSERVE_DIR = "observe"             # `<attempt>/observe/NNN-<word>.png`: the screens of passed steps, not evidence; `NNN-excerpt.txt`: their text
PAGE_TEXT_CHARS = 20000             # how much of a page's text `page_words` reads, however large the DOM
GONE = "<gone>"                     # what a field or a watched element reads as when it is no longer there
WHOLE_FLAG = "--whole"              # the word that makes a `fill` set the whole value at once, when the data file does not say otherwise
MANUAL_DEFAULTS = {"type_delay_ms": 50, "settle_ms": 300}      # what config `manual_capture.<key>` is when absent (the template says the same)
NO_SHOT_IN_WINDOW = "no screenshot: the sign-in form may show the account"

_PART = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?")
_ATTEMPT = re.compile(r"a[0-9]{1,6}")
_LABEL_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


# The two reads a `type` that goes on without a new focus makes (TR1-1): whether the field is still in the page, and what has the focus.
CONNECTED_JS = "el => el.isConnected"
ACTIVE_JS = ("el => { const a = el.getRootNode().activeElement; if (!a) return 'nothing'; "
             "return a.tagName.toLowerCase() + (a.id ? '#' + a.id : ''); }")


class StepFailed(Exception):
    """The product (or the page) did not allow the step: no element matched, a drag found no box.

    `cover` is the text of the element that covers the target (a step's detail keeps it only after the secret scan,
    which needs the config the browser does not have), `said` is the browser's own first line, kept last."""

    def __init__(self, message="", *, cover=None, said="", by="Playwright"):
        super().__init__(message)
        self.head, self.cover, self.said, self.by = str(message), cover, said, by

    def render(self, cover_note=None, screenshot=None, shot_note=None) -> str:
        """The step's detail: what was found, the covering text (or `cover_note` in its place), the screenshot path
        (or `shot_note`, why there is none), and last the browser's own words."""
        text = self.head
        if cover_note is not None:
            text += f" ({cover_note})"
        elif self.cover:
            text += f' ("{self.cover[:COVER_TEXT_CHARS]}")'
        if screenshot:
            text += f"; screenshot: {screenshot}"
        elif shot_note:
            text += f"; {shot_note}"
        if self.said:
            text += f"; {self.by} said: {self.said}"
        return text

    def __str__(self):
        return self.render()


def _first_line(exc, fallback=None) -> str:
    """The first line of an exception's text, at most 200 characters; `fallback` (the class name when None) if empty."""
    lines = str(exc).strip().splitlines()
    if lines:
        return lines[0][:200]
    return exc.__class__.__name__ if fallback is None else fallback


class StepTimeout(Exception):
    """A step took longer than the limit; `elapsed_s` is how long it took."""

    def __init__(self, elapsed_s):
        super().__init__(f"{elapsed_s:g} s")
        self.elapsed_s = elapsed_s


class BrowserUnavailable(Exception):
    """No Playwright in this interpreter."""


#: the cause of an env_blocked row whose login by code was NOT TRIED (nothing was sent): the factory does not know this
#: project's sign-in request. One producer (`http_login_source`); `_blocked`, `choose_attempt`, `_account_steps_gate` and
#: `manual_evidence.build_record` read it by name (AR-13). Another spec imports it: name and value stay.
LOGIN_UNKNOWN_CAUSE = "login_unknown"


class EnvBlocked(Exception):
    """The stand could not be identified by its runtime probe: the case cannot be recorded. With `do_not_retry` the row
    locks the screen route only when the cause proves the same stand or account answers again (`build`, `device`, or
    a ui login refused after submit); cause `login_unknown` (`LOGIN_UNKNOWN_CAUSE`) is the factory's gap, nothing was
    sent, and it locks nothing."""

    def __init__(self, probe_line, remedy, owner, do_not_retry=False, cause=""):
        super().__init__(probe_line)
        self.row = {"probe_line": probe_line, "remedy": remedy, "owner": owner}
        if do_not_retry:
            # a login that did not land (cause: none written) or a stand that does not hold this story's build
            # (cause `build`): a capture again meets the same page or the same stand, so no door says "capture again"
            # while the cause stands (spec t-292 Q2; t-300 N2 X13, F5)
            self.row["do_not_retry"] = True
            if cause:
                self.row["cause"] = cause


class LoginMaterialMissing(ValueError):
    """The stand's test account cannot be read: `part` says which half is missing - `file` (the file config names is
    not there), `unreadable` (it is there but cannot be read: a folder in its place, no permission) or `key` (the file
    does not hold the account's name or password). A ValueError, so every caller
    of `read_login` that refuses on it still does; the pre-dispatch check of the driver reads `part`, never the
    words (FR-12)."""

    def __init__(self, text, part):
        super().__init__(text)
        self.part = part


# --------------------------------------------------------------------------------------------
# injection points (tests put fakes here; production leaves them None and the real ones are used)
# --------------------------------------------------------------------------------------------
BACKEND_FACTORY = None   # () -> a browser backend (see PlaywrightBackend for the methods)
HTTP = None              # an object with .request(method, url, headers, body, timeout_s) -> HttpResult
PROBE = None             # (spec) -> provenance dict; the default is run_suite.probe_runtime
NOW = None               # () -> aware datetime
MONOTONIC = None         # () -> seconds; the clock of the landing loop, the default is time.perf_counter


def _now() -> str:
    moment = NOW() if NOW else datetime.now(timezone.utc)
    return moment.isoformat(timespec="seconds")


class HttpResult:
    def __init__(self, status, headers, body, elapsed_s, unreadable=False):
        self.status, self.headers, self.body, self.elapsed_s = status, headers, body, elapsed_s
        # B-408 F1: the status arrived and the body did not (a read that stalled or failed). A capture of a body that
        # never came is no evidence of an empty body: `run_http` ends the step as a timeout, as it always did.
        self.unreadable = unreadable


# --------------------------------------------------------------------------------------------
# data and config
# --------------------------------------------------------------------------------------------

def spec() -> dict:
    try:
        return json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{SPEC_PATH.name} cannot be read ({exc.__class__.__name__}): the factory's list of capture "
                         "steps is missing from this install. This is a factory defect: record it as a finding "
                         "and go on with what does work")


def _absent_marker() -> str:
    """The word stored for an attribute the element does not have (`read_absent_marker`). Never an empty string: an
    absent attribute and an empty one are different facts (AR-28)."""
    marker = spec().get("read_absent_marker")
    if not isinstance(marker, str) or not marker:
        raise StepFailed("manual-capture-steps.json names no `read_absent_marker`, so an absent attribute cannot be told "
                         "from an empty one. This is a factory defect: record it as a finding")
    return marker


def load_config(task_root) -> tuple:
    """(config, project root): the nearest `qa-factory/config.json` above the task root."""
    task = Path(task_root).resolve()
    for folder in (task, *task.parents):
        path = folder / "qa-factory" / "config.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except ValueError as exc:
                raise ValueError(f"{path} is not valid JSON ({exc}): repair the project's config first")
            return (data if isinstance(data, dict) else {}), folder
    raise ValueError(f"no qa-factory/config.json above --task-root {task_root}: the stand's hosts and the secret "
                     "patterns come from it. Expected the story's folder under qa-factory/artifacts/<TICKET>")


def case_dir_name(case) -> str:
    """`area/TC` -> `area__TC`. Refused: empty, `..`, an absolute path, a part with anything but letters,
    digits and `. _ -`, a part holding `__` (it would collide with the separator)."""
    raw = str(case if case is not None else "")
    parts = raw.replace("\\", "/").split("/")
    for part in parts:
        if (part in ("", ".", "..") or not _PART.fullmatch(part) or "__" in part):
            why = ("is empty" if not raw.strip() else "is absolute or has an empty part" if part == "" else
                   "goes up a folder" if part in (".", "..") else "has a part that is not a plain id")
            raise ValueError(f"--case {raw!r} {why}. Expected the case id exactly as the dispatch scope spells it: "
                             "`<id>` or `<area>/<id>`, letters, digits and `. _ -` only, no `..`, no leading slash, "
                             "no `__`")
    return "__".join(parts)


def case_root(task_root, case) -> Path:
    return Path(task_root).resolve().joinpath(*EVIDENCE_PARTS, case_dir_name(case))


def attempt_number(name) -> int:
    found = _ATTEMPT.fullmatch(str(name))
    return int(str(name)[1:]) if found else -1


def attempts_of(root: Path) -> list:
    """The attempt directories of one case, oldest first (`a1`, `a2` ...)."""
    if not root.is_dir():
        return []
    return sorted((p.name for p in root.iterdir() if p.is_dir() and attempt_number(p.name) >= 0), key=attempt_number)


def attempt_state(attempt_dir: Path) -> str:
    """`written` (a record was built from it), `env_blocked`, or `open`."""
    if (attempt_dir / "record.json").is_file():
        return "written"
    if (attempt_dir / "env_blocked.json").is_file():
        return "env_blocked"
    return "open"


def _env_blocked_row(attempt_dir: Path) -> dict:
    """The row of an attempt's env_blocked.json, {} when it cannot be read (a broken file is read as a plain env_blocked
    attempt: the old refusal text, never a raise inside a refusal)."""
    try:
        data = json.loads((attempt_dir / "env_blocked.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def choose_attempt(root: Path, explicit) -> str:
    """The attempt a capture goes into: the one named, else the latest that is still open, else the next."""
    if explicit:
        if attempt_number(explicit) < 0:
            raise ValueError(f"--attempt {explicit!r} is not an attempt name. Expected a<number>, for example a1 "
                             "or a2")
        state = attempt_state(root / explicit)
        old = _env_blocked_row(root / explicit)
        if state == "env_blocked" and old.get("do_not_retry") is True and old.get("cause") == LOGIN_UNKNOWN_CAUSE:
            # a login by code that was not tried (nothing sent): the factory's gap, the door is a new attempt
            raise ValueError(f"attempt {explicit} holds a login by code that was not tried (nothing was sent); capture "
                             "into a new attempt (leave --attempt out)")
        if (state == "env_blocked" and old.get("do_not_retry") is True and old.get("owner") == "user"
                and not old.get("cause") and not _row_locks_screen_route(old, root / explicit)):
            # an old row (no cause) with no failed sign-in step in its steps: nothing shows a login was sent, and the screen route
            # is open (`_account_steps_gate`, the same test); the named attempt itself stays closed, the door is a new one
            raise ValueError(f"attempt {explicit} is env_blocked, but nothing shows a sign-in was sent from it (no cause is recorded "
                             "and its last step is not a failed `ui` step), so the screen route is open: capture into a new "
                             "attempt (leave --attempt out), signing in through fill-account steps")
        if state == "env_blocked" and old.get("do_not_retry") is True:
            # t-308 F2 (the Q2 invariant): an attempt whose login did not land never gets a "capture again" door while
            # the cause stands - the door is the one the runner has: the env_blocked line, then halt (FR-2, FR-57)
            line = old.get("probe_line")
            # the build cause and its door are DATA (refusals block, t-300 N2 F6); the login's stay as written
            which = old.get("cause")
            build = which == "build"
            # the device cause (EP1-41d) has its own words: a device is never described as a test account that did not land
            cause = (say_refusal("cause_build") if build else say_refusal("cause_device") if which == "device"
                     else "the cause is the stand or its test account, so a new capture would meet the same page")
            door = (say_refusal("door_build") if build else say_refusal("door_device") if which == "device" else
                    "once the account or the stand is fixed, a later dispatch starts a new attempt (leave --attempt out)")
            raise ValueError(f"attempt {explicit} of this case is env_blocked with do_not_retry"
                             + (f" ({str(line)[:200]})" if isinstance(line, str) and line else "")
                             + f": {cause}. Put the case in env_blocked[] with that line and the remedy in "
                             f"{explicit}/env_blocked.json, make no further capture of any kind in this block, and halt "
                             f"the block; {door}")
        if state != "open" and (root / explicit).is_dir():
            raise ValueError(f"attempt {explicit} of this case is already {state}: a "
                             f"capture never changes what a record was built from. Capture again with the next "
                             f"attempt (--attempt a{attempt_number(explicit) + 1}) or leave --attempt out")
        return explicit
    known = attempts_of(root)
    if known and attempt_state(root / known[-1]) == "open":
        return known[-1]
    return f"a{attempt_number(known[-1]) + 1}" if known else "a1"


def profiles_of(probe_rows) -> list:
    """The stand profiles of a list of probe rows (probes.jsonl lines), in the order first seen."""
    seen = []
    for row in probe_rows:
        profile = row.get("profile") if isinstance(row, dict) else None
        if isinstance(profile, str) and profile and profile not in seen:
            seen.append(profile)
    return seen


def attempt_profiles(attempt_dir: Path) -> list:
    """The stand profiles an attempt holds probes of: `[]` for an attempt nothing was probed in, one word for an
    attempt of one profile, more when two profiles were forced into one attempt with --attempt."""
    path = attempt_dir / "probes.jsonl"
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return profiles_of(rows)


def choose_attempt_for(root: Path, profile: str) -> tuple:
    """(attempt, note) of a capture on `profile` with no --attempt: the latest attempt that is still open ONLY when
    it holds probes of that same profile (or none), else the next one, and the note says why (one line, "" when
    the open attempt was joined). One attempt is one stand identity (t-277 F4): a `ui` session and the cleanup
    DELETE after it, when they are two test profiles, used to share an attempt, and `build` refused the pair as
    "provenance changed".
    Direction of error: toward a new attempt - an extra attempt costs a line, a mixed one costs the record."""
    known = attempts_of(root)
    if known and attempt_state(root / known[-1]) == "open":
        held = attempt_profiles(root / known[-1])
        if not held or held == [profile]:
            return known[-1], ""
        new = f"a{attempt_number(known[-1]) + 1}"
        return new, f"attempt {new} opened: {known[-1]} holds {' and '.join(held)} captures"
    return choose_attempt(root, None), ""


def _fits_surface(profile, row) -> bool:
    """Whether a test profile serves a capture surface (a row of `capture_surfaces`): its `capabilities` hold a word of the
    row, or its id is the row's `level`. The ONE reading, for `capture_profile` and `harness_argv` (a third surface joins here)."""
    if not isinstance(profile, dict):
        return False
    wanted = {str(w) for w in row.get("capabilities") or []}
    level = str(row.get("level") or "")
    caps = profile.get("capabilities") if isinstance(profile.get("capabilities"), list) else []
    return bool(wanted & {str(c) for c in caps} or (level and str(profile.get("profile_id")) == level))


def capture_profile(cfg, task_root, case, surface, asked=None) -> str:
    """The test profile a `ui` or `http` capture is about (EP1-28): the project's own profile, never a literal. Top down
    (`capture_surfaces` and `capture_words` of manual-capture-steps.json are the data): (1) `asked` (--profile) when it is a
    profile of config.json, else a refusal listing them; (2) the profiles whose `capabilities` hold a word of the surface,
    or whose id is the surface's plan `level` - one fits: it; (3) several: the profile the PLAN gives this case
    (`gate_preflight.stand_profiles`, manual-agent) when it is among them, else the one whose id is the level, else a
    refusal; (4) none fits and the project has ONE profile: it (the default `s5_profiles` has); (5) else the `level` word
    when `execution.runtime_probes` holds an entry by it (an older config); (6) else a refusal naming --profile.
    Every refusal is a ValueError (exit 2) raised BEFORE any attempt, browser or request exists. A profile is never made up."""
    data = spec()
    row = (data.get("capture_surfaces") or {}).get(surface) or {}
    words = data.get("capture_words") or {}
    listed = cfg.get("profiles") if isinstance(cfg, dict) and isinstance(cfg.get("profiles"), list) else []
    profiles = [p for p in listed if isinstance(p, dict) and str(p.get("profile_id") or "").strip()]
    ids = list(dict.fromkeys(str(p["profile_id"]) for p in profiles))
    if asked:
        if asked in ids:
            return asked
        raise ValueError(words["profile_unknown"].format(asked=asked, names=", ".join(ids) or "none"))
    wanted = {str(w) for w in row.get("capabilities") or []}
    level = str(row.get("level") or "")
    fits = list(dict.fromkeys(str(p["profile_id"]) for p in profiles if _fits_surface(p, row)))
    if len(fits) == 1:
        return fits[0]
    if len(fits) > 1:
        try:
            import gate_preflight
            plan = gate_preflight.stand_profiles(cfg, task_root, ("manual-agent",))
        except Exception:
            plan = {}
        spellings = {str(case), str(case).replace("\\", "/")}
        mine = [pid for pid in fits if spellings & {str(c) for c in (plan.get(pid) or {}).get("cases") or []}]
        if len(mine) == 1:
            return mine[0]
        if level in fits:
            return level
        raise ValueError(words["profile_several"].format(surface=surface, names=", ".join(fits)))
    if len(ids) == 1:
        return ids[0]
    probes = (cfg.get("execution") or {}).get("runtime_probes") if isinstance(cfg.get("execution"), dict) else None
    if level and isinstance(probes, dict) and level in probes:
        return level
    raise ValueError(words["profile_none"].format(surface=surface, capabilities=", ".join(f"`{w}`" for w in sorted(wanted))
                                                  or "the surface's word"))


def host_key(url):
    """(scheme, host, port) of an http(s) URL with no credentials in it, else None."""
    try:
        parts = urlsplit(str(url))
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        return None
    return parts.scheme, parts.hostname.lower().rstrip("."), port or (443 if parts.scheme == "https" else 80)


def _hosts_and_notes(cfg: dict, values=None, root=None) -> tuple:
    """({host key: environment}, frontend sources, notes) over each environments[] row's `base_url` and its frontend
    address - read ONLY through `env_probe.frontend_of` (AR-13, axis 29). `values` None: the reader loads the env file
    (under `root`; None: the project root of hooklib)."""
    import env_probe
    out, sources, notes = {}, [], []
    for env in cfg.get("environments") or []:
        if not isinstance(env, dict):
            continue
        found = env_probe.frontend_of(cfg, str(env.get("name") or ""), values, entry=env, root=root)
        notes.extend(n for n in found["notes"] if n not in notes)
        if found["url"] and not host_key(found["url"]):
            notes.append("a frontend address is not an http(s) address with a host and no user:password part, so it "
                         f"allows no host ({found['source']})")
        elif found["url"]:
            sources.append(found["source"])
        for address in (env.get("base_url"), found["url"]):
            key = host_key(address)
            if key:
                out.setdefault(key, env)
    return out, sources, notes


def stand_hosts(cfg: dict, values=None, root=None) -> dict:
    """{host key: environment} over environments[].base_url and the frontend address (`env_probe.frontend_of`)."""
    return _hosts_and_notes(cfg, values, root)[0]


def hosts_sentence(hosts) -> str:
    """The ONE way a refusal lists the hosts a call may reach: `scheme://host:port`, sorted, comma-separated, `none` for an empty set."""
    return ", ".join(sorted({f"{k[0]}://{k[1]}:{k[2]}" for k in hosts})) or "none"


def read_body_file(path) -> tuple:
    """`(bytes, "")` of a request body file (`--body-file`, the walk's `http` step), or `(None, the ONE refusal sentence)` when it cannot be
    read. A value, not a raise: the callers refuse it in their own way and no new refusal unit enters the judgment census (L-b)."""
    try:
        return Path(path).read_bytes(), ""
    except OSError as exc:
        return None, f"--body-file {str(path)!r} cannot be read ({exc.__class__.__name__}). Expected the path of the request body"


def environment_of(url, cfg: dict, values=None, root=None) -> dict:
    """The configured stand a URL belongs to; a host outside every `environments[]` base_url / frontend address is refused."""
    hosts, sources, notes = _hosts_and_notes(cfg, values, root)
    if not hosts:
        raise ValueError("config.json has no environments[] with a base_url or a frontend address: the hosts a capture "
                         "may reach are exactly those. Expected the onboarding's `environments[]`")
    env = hosts.get(host_key(url))
    if env is None:
        import env_probe
        frontend = ("the frontend address is read from " + ", ".join(sources) if sources
                    else "no frontend address is configured (" + env_probe.frontend_door(cfg)["none"] + ")")
        said = "; ".join(notes)
        raise ValueError(f"the URL {str(url)[:120]!r} is not on a configured stand (http or https, no user:password "
                         f"part). Allowed hosts: {hosts_sentence(hosts)}. Frontend address: {frontend}"
                         f"{'; ' + said if said else ''}. A capture never leaves the stand; a stand "
                         "that is not listed is added to `environments[]` first")
    return env


def timeout_for(env: dict) -> float:
    """The limit of one step: the stand's measured full page load plus 30 s, else 180 s."""
    measured = env.get("measured") if isinstance(env.get("measured"), dict) else {}
    record = measured.get("e2e_page_load_s")
    value = record.get("value") if isinstance(record, dict) else record
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return value + TIMEOUT_MARGIN_S
    return DEFAULT_TIMEOUT_S


def element_wait_for(cfg: dict) -> float:
    """The limit of one element lookup: config `manual_capture.element_wait_s` when it is a positive finite
    number, else ELEMENT_WAIT_S. A missing selector must not cost the page-load limit (smoke: 180 s)."""
    own = cfg.get("manual_capture") if isinstance(cfg.get("manual_capture"), dict) else {}
    value = own.get("element_wait_s")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return value
    return ELEMENT_WAIT_S


def secret_pattern_hit(text: str, cfg: dict):
    """The index of the first config `secret_content_patterns` entry that matches, else None."""
    for index, pattern in enumerate(cfg.get("secret_content_patterns") or []):
        try:
            found = re.search(pattern, text)
        except re.error as exc:
            raise ValueError(f"secret_content_patterns[{index}] in config.json is not a valid expression ({exc}): "
                             "nothing can be scanned until it is repaired, so nothing is captured")
        if found:
            return index
    return None


def redact(headers, spec_data) -> dict:
    hidden = {h.lower() for h in spec_data.get("redact_headers") or []}
    return {str(k): ("[redacted]" if str(k).lower() in hidden else str(v)) for k, v in dict(headers).items()}


class Credentials:
    """The test account of the stand's own `.env`; its repr never carries the values. `env_file`, `user_key` and
    `password_key` are the NAMES it was read from (a failed login says where the account comes from, never what it
    is)."""

    def __init__(self, username, password, env_file="", user_key="", password_key="", label=""):
        self.username, self.password = username, password
        self.env_file, self.user_key, self.password_key = env_file, user_key, password_key
        self.label = label      # who signs in when `--as` (or the case's own actor) chose it; "" = the stand's default

    def __repr__(self):
        return "<credentials: not shown>"


def _env_values(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        key = key[7:].strip() if key.startswith("export ") else key
        if not key:
            continue        # `=x` names nothing: it must never answer a key whose configured name is empty
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _env_files_state(files) -> tuple:
    """(values, state) of the env files `files`, read in the list's order (OH3-40). `state` is `ok` when at least one exists
    and every one that exists could be read; `file` when none exists; `unreadable` (values empty) at the first one that is
    there but is not a regular file or cannot be read. A later file wins over an earlier one for the same key, as in the gate's
    `env_values`; an empty value never replaces a held one (the gate leaves empties out). The pair is never built from the
    process environment; several files are layered, as in the gate (a later file may replace one key of an earlier one)."""
    values, seen = {}, False
    for path in files:
        path = Path(path)
        if not path.exists():
            continue
        seen = True
        try:
            if not path.is_file():
                raise IsADirectoryError(str(path))      # t-308 F6: there, but not a file: unreadable, not "not there"
            values.update({k: v for k, v in _env_values(path).items() if v})
        except OSError:
            return {}, "unreadable"
    return values, ("ok" if seen else "file")


def _file_names(files, root=None) -> str:
    """The files as a person reads them: the path under the project root when it is under it, else as written."""
    out = []
    for path in files:
        try:
            out.append(Path(path).relative_to(root).as_posix() if root is not None else str(path))
        except ValueError:
            out.append(str(path))
    return ", ".join(out)


def _read_pair(files, user_key: str, password_key: str, root=None) -> "Credentials":
    """The account held under two key NAMES in the env files config names (`gate_preflight.configured_env_files`, the
    reader the gate uses): the ONE reader of the files for the stand's default account and for every account a case is
    signed in as (`read_login`). Both keys come from the files or the call is refused: no process environment, no pair of
    two sources. No file existing, a file that cannot be read, or a missing key is refused by NAME, never by value."""
    names = _file_names(files, root)
    values, state = _env_files_state(files)
    if state == "file":
        raise LoginMaterialMissing(
            f"the file config names for the stand's login (environment.env_file = {names}) does not "
            f"exist. Expected it to hold {user_key} and {password_key}; login is done by code and "
            "the factory never asks you for them", "file")
    if state == "unreadable":
        raise LoginMaterialMissing(f"a file config names for the stand's login (environment.env_file = {names}) "
                                   f"cannot be read. Expected it to hold {user_key} and {password_key}", "unreadable")
    for key in (user_key, password_key):
        if not values.get(key):
            raise LoginMaterialMissing(
                f"{key} is not set in {names} (the key NAME only: values are never printed). Login by "
                f"code needs {user_key} and {password_key} there", "key")
    return Credentials(values[user_key], values[password_key], names, user_key, password_key)


def read_login(cfg: dict, project_root: Path, actor=None, stand=None, task_root=None):
    """Credentials from the stand's `.env` named in config (`environment.env_file`, the key NAMES
    `environment.user_key` / `environment.secret_keys[0]`, default AUTH_USERNAME / AUTH_PASSWORD).
    None when config names no file (no login is attempted). A missing file or key is refused by NAME.

    `actor` (HF5-3): who signs in, in the forms of `resolve_actor` (`default`, a role, `env:USER/SECRET`,
    `created:<name>`); `stand` is the environments[] row the call works on and `task_root` the story. The credentials
    then carry `label`. Without an actor the answer is exactly what it always was."""
    env = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
    import gate_preflight           # the gate's reading of which files config names (AR-13): what it calls `met`, this reads
    files = gate_preflight.configured_env_files(env, project_root)[0]
    env_file = _file_names(files, project_root)
    if actor is not None:
        user_key, secret_key, held, label = resolve_actor(cfg, stand, actor, task_root)
        if held is not None:
            found = Credentials(held["username"], held["password"])
        elif label == "default":
            found = read_login(cfg, project_root)
        elif not files:
            raise LoginMaterialMissing(
                f"config.json names no file for the stand's accounts (environment.env_file): `--as {actor}` reads "
                f"{user_key} and {secret_key} from it. Expected the path of the project's env file", "file")
        else:
            found = _read_pair(files, user_key, secret_key, project_root)
        if found is None:
            raise LoginMaterialMissing("config.json names no file for the stand's accounts (environment.env_file): "
                                       "`--as default` reads the default account from it. Expected the path of the "
                                       "project's env file", "file")
        found.label = label
        return found
    if not files:
        return None
    user_key, password_key = _default_keys(env)
    for key, setting in ((user_key, "environment.user_key"), (password_key, "environment.secret_keys[0]")):
        if not key.strip():
            raise LoginMaterialMissing(f"{setting} in config.json is empty. Expected the NAME of the key that holds "
                                       f"the account in {env_file}, for example AUTH_USERNAME / AUTH_PASSWORD", "key")
    return _read_pair(files, user_key, password_key, project_root)


def _default_keys(env: dict) -> tuple:
    """(user key, password key) NAMES of the stand's default account: `environment.user_key` /
    `environment.secret_keys[0]`, else AUTH_USERNAME / AUTH_PASSWORD."""
    secret_keys = env.get("secret_keys") if isinstance(env.get("secret_keys"), list) else []
    return str(env.get("user_key") or "AUTH_USERNAME"), str(secret_keys[0]) if secret_keys else "AUTH_PASSWORD"


# --------------------------------------------------------------------------------------------
# the actor of a case (HF5-3): who a capture signs in as
# --------------------------------------------------------------------------------------------

GENERATED_USER, GENERATED_PASSWORD = "{generated_username}", "{generated_password}"
UNCONFIRMED = "unconfirmed"       # a created user whose sign-up the app refused (N1c E1c.6): never an identity
ACCOUNT_LOCK_WAIT_S = 20          # how long `CreatedAccounts` waits for another walker's write (N1c E1c.2)
ACCOUNT_LOCK_WAIT_HTTP_S = 300    # the `http` create route has already made the user on the stand: it waits long rather than lose the password
NEW_ACCOUNT_TRIES = 3            # fresh pairs tried when a generated value matches a secret pattern (N1c E1c.3)
NO_LOGIN_AS = ("this project's captures need no login (manual_capture.login in config.json is null for this kind); `--as` "
               "has nothing to sign in. Leave `--as` out")
_SLUG_OUT = re.compile(r"[^a-z0-9-]")
_ACTOR_FORMS = ("`--as default` (the stand's default account), `--as \"<role>\"` (a role of the stand's "
                "credentials_by_role), `--as env:USER_KEY/SECRET_KEY` (two key names in the project's env file) or "
                "`--as created:<username>` (a user this story created)")
_ACTOR_DOOR = "`--as env:USER_KEY/SECRET_KEY`, or `--as default`"
_CREATE_ROUTE = ("the stand lists no other account, so create one: find the stand's create-user endpoint in the "
                 "project's code (config.json test_data.accounts_by_role says how the project makes users), then run "
                 "`manual_capture.py http --as default --method POST --url <endpoint> --body-file <file>` with "
                 f"`{GENERATED_USER}` and `{GENERATED_PASSWORD}` in the body (a user with the least rights the "
                 "precondition needs, never a global admin unless it says so); the summary's `created_account` is "
                 "the name for `--as created:<username>`; this project's way of getting more accounts is in config "
                 "`manual.accounts_way`; the factory asks the person once")


def _roles_of(stand) -> dict:
    roles = stand.get("credentials_by_role") if isinstance(stand, dict) else None
    return roles if isinstance(roles, dict) else {}


def _name_slug(text) -> str:
    return _SLUG_OUT.sub("-", str(text).lower())


def generated_account(task_root, case) -> tuple:
    """(name, password) of a user the story creates: `qa-factory-<ticket>-<case>-<hex8>` (lower case, a character outside
    `[a-z0-9-]` becomes `-`) and `secrets.token_urlsafe(18)`. The role puts any domain around the name (`{generated_username}@x`)."""
    import secrets
    return (f"qa-factory-{_name_slug(Path(task_root).resolve().name)}-{_name_slug(case)}-{secrets.token_hex(4)}",
            secrets.token_urlsafe(18))


def created_names_path(task_root) -> Path:
    """The ONE path of the story's list of created users (`<T>/state/created-accounts.json`, NAMES only): the store writes
    it and the report (`report_facts.created_accounts_line`) reads it through this function."""
    return Path(task_root) / "state" / "created-accounts.json"


class CreatedAccounts:
    """The users this story created on the stand. The PASSWORD lives only in the machine-local `qa-factory/state/
    created-accounts/<ticket>.json` (`runtime_paths.state_file`, not carried); the story's own folder
    (`<T>/state/created-accounts.json`) holds NAMES, the case, the time and the endpoint's path - never a value (B1)."""

    def __init__(self, task_root):
        import runtime_paths
        self.task = Path(task_root).resolve()
        project = runtime_paths.nearest_project(self.task)
        if project is None:
            raise ValueError(f"no qa-factory/config.json above --task-root {task_root}: the created users cannot be "
                             "kept anywhere. Expected the story's folder under qa-factory/artifacts/<TICKET>")
        self.secret_path = runtime_paths.state_file(project, "created-accounts", f"{self.task.name}.json")
        self.names_path = created_names_path(self.task)

    @staticmethod
    def _rows(path: Path) -> list:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        rows = data.get("accounts") if isinstance(data, dict) else None
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def password_of(self, name):
        """The password of a user this story created, None when there is none or the sign-up was refused (`unconfirmed`: never an identity)."""
        for row in self._rows(self.secret_path):
            if row.get("name") == name and row.get("password") and row.get("status") != UNCONFIRMED:
                return str(row["password"])
        return None

    def is_unconfirmed(self, name) -> bool:
        return any(row.get("name") == name and row.get("status") == UNCONFIRMED for row in self._rows(self.secret_path))

    @contextlib.contextmanager
    def _locked(self, wait_s=ACCOUNT_LOCK_WAIT_S):
        """The OS lock of the story's created users (t-1957 N1c, E1c.2): every read-modify-write of the two files runs under it, so two
        walkers adding at once keep both rows. The lock file is only opened, never deleted; it is released when the process dies. A lock
        not got within `wait_s` (ACCOUNT_LOCK_WAIT_S) is a refusal - the caller has written nothing, so no created password is lost."""
        from event_store import LockBroken, LockBusy, take_file_lock
        try:
            held = take_file_lock(self.secret_path.with_suffix(".lock"), wait_s, purpose="created accounts", record_holder=True,
                                  poll_s=0.05)
        except LockBusy as exc:
            raise TimeoutError(f"the list of created users is held by another walker for over {wait_s:g} s: nothing was written. "
                               f"Repeat the step; {exc.holder_clause}") from exc
        except LockBroken as exc:
            raise TimeoutError(str(exc)) from exc
        try:
            yield
        finally:
            held.release()

    def add(self, name, password, case, endpoint_path, status=None, reason=None, wait_s=ACCOUNT_LOCK_WAIT_S) -> None:
        """Record a created user. `status=None` (the `http` route: the stand answered 2xx) is a usable identity; `UNCONFIRMED` (the sign-up
        form: the app has not been seen to accept it) is recorded first and confirmed on evidence (`confirm`). `wait_s`: how long to wait
        for the lock; a lock not got raises TimeoutError and nothing is written."""
        from event_store import atomic_json
        at = _now()
        secret_row, names_row = {"name": name, "password": password}, {"name": name, "case": str(case), "at": at, "endpoint": endpoint_path}
        if status is not None:
            secret_row["status"] = names_row["status"] = status
            if reason:
                names_row["reason"] = reason
        with self._locked(wait_s):
            self.secret_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(self.secret_path, {"accounts": self._rows(self.secret_path) + [secret_row]})
            self.names_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(self.names_path, {"accounts": self._rows(self.names_path) + [names_row]})

    def row_of(self, name):
        """The names-file row of a user this story created (a dict), None when there is none."""
        return next((row for row in self._rows(self.names_path) if row.get("name") == name), None)

    def confirm(self, name, by="code", why="") -> None:
        """`name` has been seen to work: both rows lose `status` and `reason`, so it is an identity. `by="code"` (the page left the form's
        path) leaves the rows exactly as before; any other `by` (the walker's own word, TR3-10 A) is kept on the names row as `confirmed_by`
        and `why` (a row with no `confirmed_by` reads as confirmed by code; the report line marks the others). A name not in the store changes nothing."""
        from event_store import atomic_json
        with self._locked():
            for path in (self.secret_path, self.names_path):
                rows = self._rows(path)
                for row in rows:
                    if row.get("name") == name:
                        row.pop("status", None)
                        row.pop("reason", None)
                        if by != "code" and path == self.names_path:
                            row["confirmed_by"] = str(by)
                            row["why"] = str(why)
                atomic_json(path, {"accounts": rows})

    def mark_unconfirmed(self, name, reason) -> None:
        """The sign-up of `name` was refused or never landed (E1c.6): both rows say `unconfirmed`, the names row with the words
        (already hidden and scanned by the caller). A name not in the store changes nothing."""
        from event_store import atomic_json
        with self._locked():
            for path, with_reason in ((self.secret_path, False), (self.names_path, True)):
                rows = self._rows(path)
                for row in rows:
                    if row.get("name") == name:
                        row["status"] = UNCONFIRMED
                        if with_reason:
                            row["reason"] = reason
                            row.pop("confirmed_by", None)      # a role's earlier `confirmed` no longer stands
                            row.pop("why", None)
                atomic_json(path, {"accounts": rows})


def created_account_store(task_root) -> CreatedAccounts:
    """The one door to the users the story created (`resolve_actor` reads them, `run_http` writes them)."""
    return CreatedAccounts(task_root)


def account_doubts_path(task_root) -> Path:
    """The ONE path of the story's list of given accounts a walker doubted (`<T>/state/account-doubts.json`, handles and words only):
    `AccountDoubts` writes it; `account_doubt_rows` is the one reader of its bytes (`account_doubts` and the report read through it);
    nothing else names the file (AR-13, AR-14)."""
    return Path(task_root) / "state" / "account-doubts.json"


def account_doubt_rows(task_root) -> tuple:
    """`(rows, problem)` of the doubts file - the one reader of its bytes (`account_doubts` and the report's line read through it): a
    missing file is no doubt, an unreadable one is a problem in words."""
    path = account_doubts_path(task_root)
    if not path.is_file():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:        # UnicodeDecodeError is a ValueError
        return [], f"{path.name} cannot be read ({type(exc).__name__})"
    rows = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], f"{path.name} does not hold an `accounts` list"
    return [r for r in rows if isinstance(r, dict) and r.get("handle")], ""


class AccountDoubts:
    """The given accounts (`default`, a role, `env:U/S`) a walker said it could not confirm, this story only (TR3-10 A): one row per handle
    `{handle, why, case, at}`, the last why kept. The story never edits the project's credentials or env file (A.2). Every read-modify-write
    runs under `event_store.hold_file_lock` (AR-15), so two walkers writing at once keep both rows."""

    def __init__(self, task_root):
        self.task = Path(task_root).resolve()
        self.path = account_doubts_path(self.task)

    def rows(self) -> list:
        return account_doubt_rows(self.task)[0]

    def add(self, handle, why, case, wait_s=ACCOUNT_LOCK_WAIT_S) -> None:
        """Record a doubt. A lock not got within `wait_s`, or a file that cannot be read (rewriting it would drop the others' doubts), raises
        and nothing is written."""
        from event_store import LockBroken, LockBusy, atomic_json, hold_file_lock
        try:
            with hold_file_lock(self.path.with_suffix(".lock"), wait_s, purpose="account doubts", record_holder=False, poll_s=0.05):
                rows, problem = account_doubt_rows(self.task)
                if problem:
                    raise ValueError(f"the list of account doubts cannot be extended: {problem}. Nothing was written. Tell the person; "
                                     "the account is not used by the other walkers until the list is readable")
                rows = [r for r in rows if r.get("handle") != handle]
                rows.append({"handle": str(handle), "why": str(why), "case": str(case), "at": _now()})
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_json(self.path, {"accounts": rows})
        except LockBusy as exc:
            raise TimeoutError(f"the list of account doubts is held by another walker for over {wait_s:g} s: nothing was written. "
                               f"Repeat the step; {exc.holder_clause}") from exc
        except LockBroken as exc:
            raise TimeoutError(str(exc)) from exc


def account_doubts(task_root) -> tuple:
    """`(set of handles, problem)`: the ONE reader of the doubts (the pool and the report read it). A missing file: `(set(), "")`;
    an unreadable one: `(set(), "<why>")`, so a reader never uses an extra account on an unknown."""
    rows, problem = account_doubt_rows(task_root)
    return ({str(r["handle"]) for r in rows} if not problem else set()), problem


def resolve_actor(cfg: dict, stand, actor, task_root) -> tuple:
    """(user key | None, secret key | None, values | None, label): who `--as <actor>` signs in as - the ONE resolver of an
    account for a capture (the sign-in by code, and the `fill-account` word of the step list, resolve through it).
    Forms, the reserved ones winning over a role of the same name: `default` (`environment.user_key` / `secret_keys[0]`);
    `env:USER_KEY/SECRET_KEY` (two NAMES in the env file - an account a person put there); `created:<username>` (a user
    this story created: `values` holds its name and password, the keys are None); anything else is a role of the
    `credentials_by_role` of `stand`, whose note names the two keys (`gate_preflight.account_keys`, the user's then the
    password's). ERROR DIRECTION: a refusal with a door, never a sign-in as another account - the pair is never guessed."""
    import gate_preflight as GP
    text = str(actor if actor is not None else "")
    env = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
    if not text.strip():
        raise ValueError("--as is empty. Expected one of: " + _ACTOR_FORMS)
    if text == "default":
        return (*_default_keys(env), None, "default")
    if text.startswith("env:"):
        user, slash, secret = text[4:].partition("/")
        if not slash or "/" in secret or not GP._ENV_NAME_RE.match(user) or not GP._ENV_NAME_RE.match(secret):
            raise ValueError(f"--as {text[:80]!r} is not `env:USER_KEY/SECRET_KEY`. Expected two variable names of the "
                             "project's env file, the user's then the password's, for example "
                             "`--as env:QA_SECOND_USER_EMAIL/QA_SECOND_USER_PASSWORD` (put the account in the env file "
                             "and name its keys; the factory never keeps the value), or `--as default`")
        return user, secret, None, f"env:{user}"
    if text.startswith("created:"):
        name = text[len("created:"):]
        store = created_account_store(task_root)
        if name and store.is_unconfirmed(name):
            raise ValueError(f"`{name[:80]}` was created, but its sign-up was refused or was not seen to land (recorded `{UNCONFIRMED}`): it is not an identity. "
                             f"Create another user (the create route: {_CREATE_ROUTE}) or name an account: {_ACTOR_DOOR}")
        password = store.password_of(name) if name else None
        if password is None:
            raise ValueError(f"`{name[:80]}` was created on another machine or its record is gone; create another user "
                             f"(the create route: {_CREATE_ROUTE}) or name an account: {_ACTOR_DOOR}")
        return None, None, {"username": name, "password": password}, f"created:{name}"
    roles = _roles_of(stand)
    from config_contract import reserved_role
    reserved = [r for r in roles if reserved_role(r)]
    # GW1-27: the role is read through `GP.account_role` (the gate's own reader: a spelling that differs only in case, `_`,
    # `-` or spaces names the one role it matches; a doubt is a refusal, never the first of two). The real key is returned.
    real = GP.account_role(roles, text)
    if real is None:
        twins = GP.role_candidates(roles, text)
        lists = ("its accounts: " + ", ".join(f"`{r}`" for r in roles)) if roles else "it lists none"
        said = (f"; the role {', '.join(f'`{r}`' for r in reserved)} cannot be reached by --as: the forms default, env: "
                "and created: are reserved and win") if reserved else ""
        more = (f"; `{text[:80]}` could mean any of {', '.join(f'`{r}`' for r in twins)}: name one of them exactly"
                if len(twins) > 1 else "")
        raise ValueError(f"`{text[:80]}` is not an account this stand lists; {lists}{said}{more}; or {_ACTOR_DOOR}")
    keys = GP.account_keys(roles[real])
    if len(keys) != 2:
        raise ValueError(f"the note of `{real}` names {len(keys)} keys; a login needs two, the user's then the password's. "
                         f"Name the pair yourself: {_ACTOR_DOOR}")
    return keys[0], keys[1], None, real


def _case_actors(task_root, case) -> list:
    """The accounts the case's request names (`manual_evidence.request_actors`); one stderr line when the field cannot be read."""
    import manual_evidence as ME
    actors, why = ME.request_actors(task_root, case)
    if why:
        print(f"manual_capture: {why}; the case is captured as if it named no account", file=sys.stderr)
    return actors


def auto_actor(cfg: dict, stand, task_root, case):
    """The role to sign in as when the call has no `--as` but the case's request names its account (B3), else None
    (today's behaviour). Exactly one account that is a `stand_account` whose note names two keys: that role. Every
    other shape is a refusal with a door: an account named by one key (`env`), two or more accounts, an account no
    machine could check (`none`) or a role the stand does not list. Seeding under the admin is `--as default`.
    The create route is named only when the stand lists no role at all; the run of it is the role's, never ours."""
    import gate_preflight as GP
    mine = [a for a in _case_actors(task_root, case)
            if isinstance(a, dict) and isinstance(a.get("check"), dict) and a["check"]
            and next(iter(a["check"])) in ("env", "stand_account", "none")]
    if not mine:
        return None
    roles = _roles_of(stand)
    say = lambda a: f"{a.get('id')} ({' '.join(str(a.get('what') or '').split())[:80]})"      # noqa: E731
    if len(mine) > 1:
        raise ValueError(f"the case names {len(mine)} accounts: {'; '.join(say(a) for a in mine)}. A call signs in as one: "
                         "name it with `--as`, one call per account - `--as default` for a step the default account makes "
                         f"(seeding under the admin), and for the others {_ACTOR_FORMS}")
    actor = mine[0]
    kind, value = next(iter(actor["check"].items()))
    if kind == "env":
        raise ValueError(f"the case names its actor by one key ({value}); a login needs the user's and the password's key: "
                         f"`--as env:{value}/<password key>` (the key names are in the env file and in your brief), or "
                         "`--as default` for a step the default account makes")
    value = str(value).strip() if kind == "stand_account" else value
    if kind == "stand_account" and value == "default":
        return "default"      # GW1-27: the gate calls it met on the two keys of `environment`; `--as default` reads exactly those
    real = GP.account_role(roles, value) if kind == "stand_account" else None
    if real is not None and len(GP.account_keys(roles[real])) == 2:
        return real
    why = (f"the stand's role `{value}` has no note naming two keys" if real is not None else
           f"`{value}` could mean more than one role the stand lists, and the factory does not guess"
           if kind == "stand_account" and len(GP.role_candidates(roles, value)) > 1 else
           f"the stand lists no role `{value}`" if kind == "stand_account" else "its check names no account a machine can read")
    if roles:
        door = ("the accounts this stand lists: " + ", ".join(f"`--as \"{r}\"`" for r in roles) + f"; or {_ACTOR_DOOR}")
    else:
        door = f"{_CREATE_ROUTE}; or name one yourself: {_ACTOR_DOOR}"
    raise ValueError(f"the case's account {say(actor)} cannot be signed in by code: {why}. Name the account: {door}")


# --------------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------------

def _input_problem(word, args, row, shape) -> str:
    """Why a `type` / `paste` / `press` line is refused at parse time (every limit is data in the step's row), or ''. The
    empty text and the over-long text carry their door: a field is cleared with `press`, a long text goes in with `fill`."""
    if word == "press":
        keys = [str(k) for k in row.get("keys") or []]
        key = args[1]
        if key in keys or (len(key) == 1 and key.isprintable()):
            return ""
        return f"`press` takes {shape}; the key is one printable character or one of: {', '.join(keys)}"
    if args[1] == "":
        return (f"`{word}` takes {shape} with a text that holds at least one character; to clear a field: "
                f"`press {args[0]} Control+A`, then `press {args[0]} Backspace`")
    if word == "paste":
        return ""
    limit = row.get("max_chars")
    if isinstance(limit, int) and len(args[1]) > limit:
        return f"`type` takes at most {limit} characters (this text has {len(args[1])}); a longer text goes in with `fill`"
    if len(args) == 3:
        top = row.get("max_delay_ms")
        if not re.fullmatch(r"[0-9]+", args[2]) or int(args[2]) < 1 or (isinstance(top, int) and int(args[2]) > top):
            return f"`type` takes {shape}, the delay a whole number of milliseconds from 1 to {top}"
    return ""


def _whole_flag(spec_data) -> str:
    """The word that makes a `fill` set the whole value at once: the data's (`steps.fill.whole_flag`), the caller's spec data first."""
    for source in (spec_data, spec()):
        flag = ((source.get("steps") or {}).get("fill") or {}).get("whole_flag")
        if isinstance(flag, str) and flag:
            return flag
    return WHOLE_FLAG


def _fail_problem(args, spec_data, shape) -> str:
    """"" when `fail_request <glob> <status|timeout>` is well formed: a glob, then `timeout` or a whole number inside the
    data's bounds (a 2xx is not a failure; an unreadable word is never a status)."""
    low, high = _step_number(spec_data, "fail_request", "status_min"), _step_number(spec_data, "fail_request", "status_max")
    if not args[0].strip():
        return f"`fail_request` takes {shape}, the pattern not empty"
    if args[1] != "timeout" and not (re.fullmatch(r"[0-9]{1,4}", args[1]) and low <= int(args[1]) <= high):
        return f"`fail_request` takes {shape}, the second word `timeout` or a whole number from {low} to {high}"
    return ""


def _star_hint(glob) -> str:
    """TR1-2: "" or the hint line for a `fail_request` pattern with no `**` and no scheme whose path starts with a single `*` and goes on
    past a `/`: the `*` does not cross `/`, so it matches one segment of a host-less path only. A hint in the answer, never a refusal
    (a pattern is the role's, FR-47); `**/api/cart` and `http://...` patterns get none."""
    text = str(glob)
    if "**" in text or "://" in text or not text.startswith("*") or "/" not in text:
        return ""
    return spec()["capture_words"]["failure_star_hint"].format(glob=_detail(text))


def _read_problem(mode, spec_data, shape) -> str:
    """"" when the mode of `read <selector> <mode>` is `text`, `attr=<name>`, `style=<prop>` or `state=<name>` with the name
    one of the data's `read_states` (a state outside the list, or an empty one, is refused with the list)."""
    if mode == "text":
        return ""
    name = mode.split("=", 1)[1] if "=" in mode else ""
    if mode.startswith(("attr=", "style=")) and name:
        return ""
    if mode.startswith("state="):
        states = [str(s) for s in spec_data.get("read_states") or []]
        if name in states:
            return ""
        return f"`read` takes {shape}; the state is one of: {', '.join(states)}"
    return f"`read` takes {shape}"


EXPECT_PREFIX = "expect="      # the last argument of a browser `read`: the role's own planned text (t-1957 F12)


def read_args(args) -> tuple:
    """`(args without the expectation, the expected text or None)` of a browser `read`: `read <selector> [mode] expect=<text>`.
    The expectation is the LAST argument and only after a selector; the code compares bytes and never says who is right (FR-58)."""
    if len(args) > 1 and str(args[-1]).startswith(EXPECT_PREFIX):
        return list(args[:-1]), str(args[-1])[len(EXPECT_PREFIX):]
    return list(args), None


def lane_key(task_root, case) -> str:
    """The canonical key of a case's account set (t-1957 N1a): the accounts the case's request names (`check` kind `env` or
    `stand_account`, as `auto_actor` reads them), written `<kind>:<value>`, deduplicated, sorted, joined with `+`; `` when the case
    names none. One reader of the actors (`_case_actors`), so a lane is cut by the same facts the recorder reads."""
    keys = set()
    for actor in _case_actors(task_root, case):
        check = actor.get("check") if isinstance(actor, dict) else None
        if isinstance(check, dict) and check:
            kind, value = next(iter(check.items()))
            if kind in ("env", "stand_account"):
                keys.add(f"{kind}:{' '.join(str(value).split())}")
    return "+".join(sorted(keys))


APP_WORDS = "app_steps"            # the key of the steps file's closed list on a device surface (`parse_steps(words=APP_WORDS)`)


def _selector_problem(selector, strategies) -> str:
    """"" when `selector` is `<strategy>=<value>` (cut at the FIRST `=`) with a strategy the surface's row lists and a value that is
    not empty; else what is wrong. A device has no CSS: a selector with no listed strategy is refused before any session exists."""
    strategy, sep, value = str(selector).partition("=")
    listed = [str(s) for s in strategies or []]
    if sep and value and strategy in listed:
        return ""
    return (f"the selector is `<strategy>=<value>` with a value and a strategy of: {', '.join(listed) or 'none is listed'}")


def _app_read_problem(mode, shape) -> str:
    """"" when `read <selector> <mode>` of a device is `text` or `attr=<name>`; `style=` and `state=` are web reads."""
    if mode == "text" or (mode.startswith("attr=") and mode[5:]):
        return ""
    return f"`read` takes {shape}; `style=` and `state=` are reads of a browser, there is no such read on this surface"


def _new_account_problem(args, shape) -> str:
    """The shape problem of a `fill-new-account` line, "" when it is well formed: the kind is `user` or `secret`, a template belongs to
    `user` only and holds the placeholder `{generated_username}` (E1c.5: without it every user would get the same name)."""
    if args[1] not in ("user", "secret"):
        return f"`fill-new-account` takes {shape}, the second word `user` (the new account's name) or `secret` (its password)"
    if len(args) == 3 and args[1] != "user":
        return f"`fill-new-account` takes {shape}; a template goes with `user` only (the password has none)"
    if len(args) == 3 and GENERATED_USER not in args[2]:
        return f"`fill-new-account` template {args[2]!r} lacks the placeholder `{GENERATED_USER}`; expected for example `{GENERATED_USER}@example.test`"
    return ""


def _account_word_problem(args, row, spec_data, shape) -> str:
    """The shape problem of an `account <handle> confirmed|unconfirmed <why>` line, "" when it is well formed (A.4): the handle is not
    empty, the verdict is one of the data row's `verdicts`, the why holds 1..`why_max` characters. Nothing is recorded from a malformed word."""
    verdicts = [str(v) for v in row.get("verdicts") or []]
    example = "for example `account created:qa-user-1 unconfirmed \"the page stayed on the sign-up form\"`"
    if not args[0].strip():
        return f"`account` takes {shape}, the handle not empty ({example})"
    if args[1] not in verdicts:
        return f"`account` takes {shape}, the verdict one of: {', '.join(verdicts)} ({example})"
    top = _step_number(spec_data, "account", "why_max")
    if not args[2].strip():
        return f"`account` takes {shape}, the why not empty: quote what you saw ({example})"
    if len(args[2]) > top:
        return f"`account` takes at most {top} characters of why (this one has {len(args[2])}): say it shorter ({example})"
    return ""


def _http_word_problem(args, spec_data, shape, http_ok) -> str:
    """"" or what is wrong with an `http <METHOD> <path|url> [--body-file <file>]` step (FL-1 B). Only a walk session runs one
    (`http_ok`); a single request outside a walk is `manual_capture.py http`. Shape only: the stand, the file and the placeholders
    are the walk's to check (it knows its stand)."""
    if not http_ok:
        return ("`http` is a step of a walk session (`walk_session.py step`); a single request outside a walk is "
                "`manual_capture.py http --method <M> --url <url>`")
    methods = list(spec_data.get("http_methods") or spec().get("http_methods") or [])
    if str(args[0]).upper() not in methods:
        return f"`http` takes {shape}; the method {str(args[0])[:20]!r} is none of {', '.join(methods)}"
    target = str(args[1])
    if not (target.startswith("/") or target.startswith("http://") or target.startswith("https://")):
        return f"`http` takes {shape}; {target[:80]!r} is neither a path starting with `/` nor an http(s) URL"
    if not target.isascii():
        return f"`http` takes {shape}; the address holds a character outside ASCII: percent-encode the path (`%D0%...`), then send it"
    if len(args) == 3 or (len(args) == 4 and args[2] != "--body-file"):
        return f"`http` takes {shape}; the body goes in as `--body-file <file>`, the flag and its file together and last"
    return ""


def parse_steps(text: str, spec_data: dict, words: str = "steps", selectors=None, need_goto: bool = True, http_ok: bool = False) -> list:
    """[{n, line, word, args}] from a steps file; every problem is named with its line (one refusal). `words` names the closed list
    of the surface (`steps`: the browser; APP_WORDS: a device, whose selectors are checked against `selectors`, the row's
    strategies). Only the browser's list needs a `goto`, and only a call that opens a page: a step call of a kept walk session
    (t-1957 N1a, `need_goto=False`) goes on from the page the session is already on. `http_ok` (FL-1 B): the caller is a walk
    session, which may run an `http` step; every other caller refuses the word."""
    table = spec_data.get(words) or {}
    on_device = words != "steps"
    known = list(table)
    phases = list(spec_data.get("phases") or [])
    steps, problems = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            problems.append(f"line {number}: {exc} (quote a selector or a text that holds a space)")
            continue
        word, args = tokens[0], tokens[1:]
        if word not in known:
            elsewhere = on_device and word in (spec_data.get("steps") or {})
            problems.append(f"line {number}: " + (f"`{word}` is a step of the browser surface; there is no such step on this "
                                                  "surface. " if elsewhere else f"unknown step '{word}'. ")
                            + "The closed list: " + "; ".join(f"{name} {(table[name] or {}).get('args', '')}".strip() for name in known))
            continue
        shape = (table[word] or {}).get("args", "")
        arity = (table[word] or {}).get("arity") or [0, 0]
        if not arity[0] <= len(args) <= arity[1]:
            problems.append(f"line {number}: `{word}` takes {shape}" if shape else f"line {number}: `{word}` takes no argument; write `{word}` alone on its line")
            continue
        if on_device:
            target = args[0] if word in ("click", "fill", "fill-account", "drag", "read") else (
                args[0] if word == "wait" and not args[0].isdigit() else None)
            problem = _selector_problem(target, selectors) if target is not None else ""
            if problem:
                problems.append(f"line {number}: `{word}` takes {shape}; {problem}")
                continue
            if word == "read" and len(args) == 2 and _app_read_problem(args[1], shape):
                problems.append(f"line {number}: {_app_read_problem(args[1], shape)}")
                continue
        if word == "http":
            problem = _http_word_problem(args, spec_data, shape, http_ok)
            if problem:
                problems.append(f"line {number}: {problem}")
                continue
        if word == "drag":
            try:
                int(args[1]), int(args[2])
            except ValueError:
                problems.append(f"line {number}: `drag` takes {shape}, dx and dy whole numbers")
                continue
        if word in ("type", "paste", "press"):
            problem = _input_problem(word, args, spec_data["steps"][word] or {}, shape)
            if problem:
                problems.append(f"line {number}: {problem}")
                continue
        if word == "fail_request":
            problem = _fail_problem(args, spec_data, shape)
            if problem:
                problems.append(f"line {number}: {problem}")
                continue
        if word == "fill" and not on_device and (args[0] == _whole_flag(spec_data)) != (len(args) == 3):
            problems.append(f"line {number}: `fill` takes {shape}; the flag `{_whole_flag(spec_data)}` comes first, with a selector "
                            "and a text after it (and only then)")
            continue
        if word == "fill-account" and args[2] not in ("user", "secret"):
            problems.append(f"line {number}: `fill-account` takes {shape}, the last word `user` (the account's name) or "
                            "`secret` (its password)")
            continue
        if word == "fill-new-account":
            problem = _new_account_problem(args, shape)
            if problem:
                problems.append(f"line {number}: {problem}")
                continue
        if word == "account":
            problem = _account_word_problem(args, table[word] or {}, spec_data, shape)
            if problem:
                problems.append(f"line {number}: {problem}")
                continue
        if word == "read" and not on_device:
            rest = read_args(args)[0]
            if len(rest) == 2:
                problem = _read_problem(rest[1], spec_data, shape)
                if problem:
                    problems.append(f"line {number}: {problem}")
                    continue
            elif len(rest) > 2:        # three words and none of them an `expect=`: the arity [1, 3] is for the expectation only
                problems.append(f"line {number}: `read` takes {shape}")
                continue
        elif word == "read" and len(args) == 2:
            problem = _read_problem(args[1], spec_data, shape)
            if problem:
                problems.append(f"line {number}: {problem}")
                continue
        if word == "capture" and args[0] not in phases:
            hint = f" ({_old_words_hint()})" if args[0] in G.MANUAL_PHASE_ALIASES else ""
            problems.append(f"line {number}: capture phase '{args[0]}' is none of {' | '.join(phases)}{hint}")
            continue
        steps.append({"n": len(steps) + 1, "line": line, "word": word, "args": args})
    if problems:
        raise ValueError("the steps file has problems: " + " | ".join(problems))
    if not steps:
        raise ValueError("the steps file holds no steps (blank lines and # comments only). Expected one step per "
                         "line" + ("" if on_device else ", starting with a `goto <url>`") + ": " + "; ".join(
                             f"{n} {(table[n] or {}).get('args', '')}".strip() for n in known))
    if need_goto and not on_device and steps[0]["word"] != "goto" and not any(s["word"] == "goto" for s in steps):
        raise ValueError("a ui session needs a `goto <url>` step: the first one names the stand the session runs on "
                         "(its login, its page-load limit and its runtime probe)")
    return steps


def _old_words_hint(short=False) -> str:
    """"`before` and `after` are the old words: use pre_action and post_action" - from the data file's aliases,
    so the words in the refusal are the words the validator reads (F9)."""
    olds = list(G.MANUAL_PHASE_ALIASES)
    text = " and ".join(f"`{old}`" for old in olds) + " are the old words"
    return text if short else text + ": use " + " and ".join(G.MANUAL_PHASE_ALIASES[old] for old in olds)


def _label(text) -> str:
    return _LABEL_CHARS.sub("-", str(text)).strip("-")[:40] or "x"


# --------------------------------------------------------------------------------------------
# one attempt's files
# --------------------------------------------------------------------------------------------

class Attempt:
    """The files of one attempt: evidence, captures.jsonl, steps.jsonl, probes.jsonl."""

    def __init__(self, task_root, case, name, cfg):
        self.task = Path(task_root).resolve()
        self.case, self.name, self.cfg = case, name, cfg
        self.dir = case_root(task_root, case) / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.limitations: list = []
        self.failures_without_hits: list = []     # globs of a `fail_request` that matched no request (EP1-30)
        self.failure_declared = False             # a `fail_request` ran in this session
        self.command = "ui"                       # the word a step and a capture line carry; `run_app` sets "app" (EP1-41d)
        self.entry_limitation = ""                # what every file of a device capture also says (set by `run_app`)
        self.watches: dict = {}                   # label -> {"selector", "last"}: the elements `watch` reads after every step of this call
        self.call_surprises: list = []            # the `surprise` lines this call wrote (the summary lists them)
        self.last_input = None                    # {"selector", "text", "rows", "secret"} of the keyed step just run: the detector's `field` data
        self.type_chain = None                    # the selector the step just run typed in (a `type`), else None: any other step resets it (TR1-1)
        self.type_prior = None                    # what `type_chain` was when the step now running began
        self.blocked_seen: set = set()            # hosts a `blocked_host` line was already written for in this call
        self.unmet_pending: list = []             # `surprise: fail_request <glob> matched no request` lines a restore left, told by the next look/read (TR1-2)
        self.carry: list = []                     # the lines of `unmet_pending` the step now running adds to its answer if it ends ok

    def _lines(self, name) -> list:
        path = self.dir / name
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []

    def step_number(self) -> int:
        """The number of the step just written: its line in this attempt's steps.jsonl (what `surprises.jsonl` calls `step`)."""
        return len(self._lines("steps.jsonl"))

    def surprise(self, step_no, word, kind, fact, status=None) -> dict:
        """One `surprise` line of `surprises.jsonl` (a FACT the role is shown, never a verdict, AR-18). The file is created by the first
        line, never ahead of it. `k` runs on across the calls of an attempt; the id is `<attempt>-<surface>-S<k>`. `status` (t-1957 N1a):
        the answer's number, stored ONLY on a `status` line and only when it is a whole number - the walk server's stop rule reads it
        (a line without it matches every status rule, AR-28); a reader that ignores the field is unchanged."""
        number = sum(1 for r in _surprise_rows(self.dir)[0] if r.get("line") == "surprise") + 1
        entry = {"line": "surprise", "id": f"{self.name}-{self.command}-S{number}", "step": step_no, "word": word, "kind": kind,
                 "fact": " ".join(str(fact).split())[:int(_surprise_data({}, "fact_chars"))], "at": _now()}
        if kind == "status" and isinstance(status, int) and not isinstance(status, bool):
            entry["status"] = status
        self._append("surprises.jsonl", entry)
        return entry

    def detector(self, step_no, dead, kinds) -> dict:
        """The line that says the detector WATCHED a step: which listeners were alive and which kinds were checked. Without it a step is
        'not observed', and an empty `surprises.jsonl` never reads as 'nothing happened' (AR-28)."""
        entry = {"line": "detector", "step": step_no, "listeners": "ok" if not dead else "dead:" + ",".join(dead),
                 "kinds_checked": list(kinds), "at": _now()}
        self._append("surprises.jsonl", entry)
        return entry

    def _append(self, name, entry) -> None:
        path = self.dir / name
        torn = path.is_file() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")   # a call killed mid-append: do not glue onto it
        with path.open("a", encoding="utf-8", newline="\n") as out:
            out.write(("\n" if torn else "") + json.dumps(entry, ensure_ascii=False) + "\n")

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.task).as_posix()

    def next_name(self, label, suffix) -> Path:
        count = 0
        captures = self.dir / "captures.jsonl"
        if captures.is_file():
            count = sum(1 for line in captures.read_text(encoding="utf-8").splitlines() if line.strip())
        existing = len(list(self.dir.glob("[0-9][0-9][0-9]-*")))
        return self.dir / f"{max(count, existing) + 1:03d}-{_label(label)}{suffix}"

    def register(self, path: Path, kind, phase, proves, command, limitation=None) -> dict:
        entry = {"path": self.rel(path), "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "kind": kind, "phase": phase, "captured_at": _now(), "proves": list(proves), "command": command}
        if limitation:
            entry["limitation"] = limitation
            self.limitations.append(limitation)
        self._append("captures.jsonl", entry)
        return entry

    def store_text(self, label, data: bytes, kind, phase, proves, command, suffix=".txt", limitation=None) -> dict:
        path = self.next_name(label, suffix)
        path.write_bytes(data)
        return self.register(path, kind, phase, proves, command, limitation)

    def step(self, command, line, outcome, detail="", **extra) -> dict:
        told = [str(x) for x in (extra.pop("told", None) or []) if x]     # the lines a step tells the walker: typed, kept in `detail` too (F6)
        if self.carry and outcome == "ok":      # a restored rule that matched nothing is told once, by the first look/read after it
            detail = "\n".join(x for x in (detail, *self.carry) if x)
            told += self.carry
            self.unmet_pending = [x for x in self.unmet_pending if x not in self.carry]
            self.carry = []
        entry = {"at": _now(), "command": command, "step": line, "outcome": outcome, "detail": detail, **extra}
        if told:
            entry["told"] = told
        self._append("steps.jsonl", entry)
        return entry

    def keep_observation(self, entry, text) -> None:
        """Keep the excerpt `_observe` recorded for a step NEXT to its picture, in `<attempt>/observe/<line>-excerpt.txt` (a quote
        of a picture is checked against it; `<line>` is the step's 1-based line of steps.jsonl, three digits). steps.jsonl is an
        append-only carrier and is never rewritten (t-1747 F7, axis 29): a crash here loses an excerpt, never a step. No excerpt:
        no file, never an empty one. Only the step's own line (the last) is looked at, and only to number the file."""
        path = self.dir / "steps.jsonl"
        if not text or not path.is_file():
            return
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        try:
            last = json.loads(lines[-1])
        except (IndexError, ValueError):
            return
        if not isinstance(last, dict) or last.get("at") != entry.get("at") or last.get("step") != entry.get("step"):
            return
        target = self.dir / OBSERVE_DIR / f"{len(lines):03d}-excerpt.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    def probe(self, when, profile, command, value) -> None:
        self._append("probes.jsonl", {"at": _now(), "when": when, "profile": profile, "command": command,
                                      "probe": value})

    def env_blocked(self, case, row) -> dict:
        data = {"id": case, "probe_line": row["probe_line"], "remedy": row["remedy"], "owner": row["owner"]}
        if row.get("do_not_retry"):
            data["do_not_retry"] = True
            if row.get("cause"):
                data["cause"] = row["cause"]
        (self.dir / "env_blocked.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
        return data


def cut_body(raw: bytes) -> tuple:
    """(stored bytes, truncated): the body whole up to BODY_CAP bytes, cut beyond it."""
    return (raw[:BODY_CAP], True) if len(raw) > BODY_CAP else (raw, False)


def body_text(raw: bytes, truncated: bool) -> tuple:
    """(text, encoding): UTF-8 when the bytes are (a multi-byte character cut by the cap is trimmed), else base64."""
    for trim in range(0, 4 if truncated else 1):
        try:
            return raw[:len(raw) - trim].decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            continue
    return base64.b64encode(raw).decode("ascii"), "base64"


def _side(raw, headers, spec_data, **extra) -> dict:
    stored, truncated = cut_body(raw or b"")
    text, encoding = body_text(stored, truncated)
    side = dict(extra, headers=redact(headers, spec_data), body=text, body_encoding=encoding,
                body_bytes_stored=len(stored), truncated=truncated)
    return side


CUT_WORDS = "body cut at"      # the opening of the limitation sentence below; `manual_evidence` finds a cut capture by it (F11, one text)


def _limit_words(what) -> str:
    return (f"{what} {CUT_WORDS} {BODY_CAP} bytes: the saved file holds the first {BODY_CAP} bytes and its hash is "
            "over those bytes")


# --------------------------------------------------------------------------------------------
# the stand's identity
# --------------------------------------------------------------------------------------------

def _default_probe(probe_spec):
    from run_suite import probe_runtime
    # THE strict reader, the same one the automated paths use (t-300 N2 S9, Q18-B): `unknown` is refused even when it
    # names an image - the manual capture used to take it (t-279 K-IMG), which let a stand nobody had identified be
    # captured on; the person's word at the build question (`person_confirmed`) is the door for such a stand.
    return probe_runtime(probe_spec)


def _registry_where() -> str:
    """Where the person's build decisions live, spelled the way the layout spells it (FR-37)."""
    try:
        import stand_identity
        return stand_identity.registry_rel()
    except Exception:
        return "qa-factory/records/stand-identity.json"


def _other_profile_remedy(cfg, attempt, profile, stand):
    """EP1-28 (H-5): the door of an `unknown` that asks the person, when the build question of THIS stage was asked about
    ANOTHER profile than the one this capture chose. None (the ordinary `remedy_unknown_asks` stands) when the plan names
    this profile, names none, or anything here cannot be read. Else the person's word on a plan profile is the door
    (`remedy_other_profile_use`: capture again with --profile P - that choice stays the role's and is written in the
    record) or, with no such word, the conductor's (`remedy_other_profile_halt`). INVARIANT: a word given for profile P is
    taken only by a capture BY P; this function names the choice and never makes it."""
    try:
        import gate_preflight
        import stand_identity
        plan = sorted(gate_preflight.stand_profiles(cfg, attempt.task, ("manual-agent",)))
        name = str((stand or {}).get("name") or "")
        if not plan or profile in plan:
            return None
        said = [p for p in plan if stand_identity.task_confirmation(attempt.task, name, p)]
    except Exception:
        return None
    if said:
        return say_refusal("remedy_other_profile_use", plan=said[0], profile=profile)
    return say_refusal("remedy_other_profile_halt", plan=", ".join(plan), profile=profile)


def _stand_blocked(profile, when, record, said, story="", other_profile=None) -> "EnvBlocked":
    """The EnvBlocked of a probe answer the capture refused (t-300 N2 S9). Which door it names is read from FIELDS of the
    record (FR-12): a stand that PROVABLY runs another build, and an `unknown` that asks the person (`asks_person`: how to
    read the build, or whether this story's build is there), are the stand's facts - the same stand answers again, so
    `do_not_retry` (cause `build`: the halt the runner already has, never "capture again" while the cause stands, FR-2,
    FR-57). An `unknown` that asks nobody (docker was down, the probe raised) heals by itself: "capture again" stays.
    A valid word given for ANOTHER story (`story`: this one) is the same kind of fact - the probe has no `--task`, so it
    reads the newest pipeline and a second capture meets the same word - and its door is the person's word for THIS story.
    A CONTENT mismatch has no build to name: its remedy never offers `test deployed` (R(cm)); the person's
    `test as is` is its door (FB-8). Every remedy is
    DATA (`refusals`, F6)."""
    line = f"{profile} {when}: {said}"
    asks = isinstance(record, dict) and bool(record.get("asks_person"))
    where = _registry_where()
    if stand_runs_other_build(record):
        key = "remedy_other_content" if content_differs(record) else "remedy_other_build"
        return EnvBlocked(line, say_refusal(key), "user", do_not_retry=True, cause="build")
    if isinstance(record, dict):
        import runtime_probe
        if record.get("reason_code") == runtime_probe.NO_EXPECTED_REVISION:
            # a checkout that names no commit (EP1-28 H-4): no build can be named, so "capture again" is no door
            return EnvBlocked(line, say_refusal("remedy_no_revision", checkout=str(record.get("checkout") or "the checkout")),
                              "user", do_not_retry=True, cause="build")
        if record.get("reason_code") == runtime_probe.DEVICE_UNREADY:
            # a device stand whose build could not be read (no device, a tool that fails, two devices, a broken table): the
            # device's own halt, never "capture again" - the same device answers again (F-2, AR-25)
            return EnvBlocked(line, say_refusal("door_device"), "user", do_not_retry=True, cause="device")
    if story and person_confirmed(record) and not person_confirmed(record, story):
        return EnvBlocked(line, say_refusal("remedy_other_story", registry=where), "user", do_not_retry=True, cause="build")
    if asks:
        text = other_profile() if other_profile is not None else None
        return EnvBlocked(line, text or say_refusal("remedy_unknown_asks", registry=where), "user", do_not_retry=True, cause="build")
    return EnvBlocked(line, say_refusal("remedy_retry"), "user")


def stand_probe(attempt: Attempt, cfg, project_root, profile, when, command, stand=None) -> dict:
    """The profile's runtime probe, through run_suite.probe_runtime. Unmatched, failed or not registered is
    an EnvBlocked (the case gets no record). Taken: `matched`; `not_applicable` when the diff touches none of that
    checkout (`no_changed_file`); and the PERSON'S WORD for this build (`person_confirmed`), stored as the probe said it
    - never as `matched`. `unknown` is refused, with or without an image (t-300 N2 Q18-B: nothing is taken on an
    unknown, FR-59), and so is a word given for another story (F10: refused BEFORE the session is spent, not at the
    record). The sentence says what the probe said, what was expected and the door (`profile_contract.refusal_text`)."""
    from execution_request import ProvenanceRefused, stand_probe_spec
    story = attempt.task.name
    # EP1-28: the project's entry, else the default probe over the profile's checkout (never written to the config). No
    # probe at all is a stand fact the person can fix by one line of data, not a factory defect: owner `user`, `cause: build`
    probe_spec, why = stand_probe_spec(cfg, profile, str((stand or {}).get("name") or ""), story)
    if probe_spec is None:
        raise EnvBlocked(f"no runtime probe for profile {profile}: {why}",
                         say_refusal("remedy_no_probe_door", why=why, profile=profile), "user", do_not_retry=True, cause="build")
    folder = Path(probe_spec["cwd"])
    probe_spec = dict(probe_spec, cwd=str(folder if folder.is_absolute() else project_root / folder))

    def other():
        return _other_profile_remedy(cfg, attempt, profile, stand)
    try:
        value = (PROBE or _default_probe)(probe_spec)
    except ProvenanceRefused as exc:
        raise _stand_blocked(profile, when, exc.record, str(exc), other_profile=other) from exc
    except Exception as exc:
        raise EnvBlocked(f"runtime probe of {profile} {when}: {exc.__class__.__name__}: {str(exc)[:200]}",
                         say_refusal("remedy_retry"), "user")
    if not acceptable_provenance(value, ACCEPTS, task=story):
        raise _stand_blocked(profile, when, value, refusal_text(value, task=story), story, other_profile=other)
    attempt.probe(when, profile, command, value)
    return value


def _blocked(attempt: Attempt, case, exc: EnvBlocked) -> int:
    row = attempt.env_blocked(case, exc.row)
    print(json.dumps({"ok": False, "outcome": "env_blocked", "case": case, "attempt": attempt.name,
                      "env_blocked": row}))
    # The sentence of each variant is DATA (`refusals.blocked_*`, EP1-41d). The cause is a field (FR-12), and the device branch comes
    # BEFORE the login's: a device that is not ready is never told as "the login by code did not land" (the same halt, other words).
    cause, kept = exc.row.get("cause"), bool(exc.row.get("do_not_retry"))
    # build (t-300 N2 X13): the stand answered and it is not (or not known to be) this story's build; the same stand answers
    # again, so the way on is the halt and the door of the PERSON, named by the remedy. login: the sign-in did not land; capturing
    # again meets the same page (qa-runner.md "Refusals": env_blocked, halt). owner `factory`: the recipe did not fit the page
    key = ("blocked_login_unknown" if cause == LOGIN_UNKNOWN_CAUSE else
           "blocked_build" if kept and cause == "build" else "blocked_device" if kept and cause == "device" else
           ("blocked_login_factory" if exc.row["owner"] == "factory" else "blocked_login_user") if kept else "blocked_stand")
    print(say_refusal(key, probe_line=exc.row["probe_line"], remedy=exc.row["remedy"], owner=exc.row["owner"]), file=sys.stderr)
    return EXIT_ENV_BLOCKED


# --------------------------------------------------------------------------------------------
# the browser
# --------------------------------------------------------------------------------------------

class PlaywrightBackend:
    """The real browser: the harness's Playwright, headless chromium, one context, one page.

    Methods return the seconds the step took (`read` returns (value, seconds)) and raise StepFailed /
    StepTimeout; a fake with the same methods stands in for it in tests. Requests to a host that is not a
    configured stand are aborted, so a click can never take the session off the stand."""

    def __init__(self):
        try:
            from playwright.sync_api import sync_playwright, Error, TimeoutError as PwTimeout
        except ImportError as exc:
            raise BrowserUnavailable(str(exc))
        self._sync, self._Error, self._Timeout = sync_playwright, Error, PwTimeout
        self._pw = self._browser = self._context = self._page = None
        self._allowed, self._failing = set(), {}
        self._events, self._ours, self._dead, self._char = [], {}, set(), None       # the ONE log of what the page did (t-1765 X8-2)
        self._limit_ms = int(DEFAULT_TIMEOUT_S * 1000)
        self._element_ms = int(ELEMENT_WAIT_S * 1000)

    def open(self, timeout_s, allowed_hosts, local_storage=None, element_wait_s=ELEMENT_WAIT_S, profile_dir=None):
        self._limit_ms = int(timeout_s * 1000)          # a page load (goto, login)
        self._element_ms = int(element_wait_s * 1000)   # an element lookup
        self._allowed = set(allowed_hosts)              # the hosts `fail_request` may answer for (EP1-30)
        self._pw = _driver_acquire(self._sync)
        if profile_dir is not None:
            # RN1-10: a session lives between calls in the actor's own PERSISTENT profile (cookies and localStorage stay on
            # disk until `session close`), one browser process per call - nothing is left running between two calls
            context = self._context = self._pw.chromium.launch_persistent_context(
                str(profile_dir), headless=True, viewport={"width": 1920, "height": 1080}, ignore_https_errors=True)
        else:
            self._browser = self._pw.chromium.launch(headless=True)
            context = self._context = self._browser.new_context(viewport={"width": 1920, "height": 1080},
                                                                ignore_https_errors=True)
        context.set_default_timeout(self._element_ms)

        def guard(route):
            url = route.request.url
            key = host_key(url)
            if url.startswith(("data:", "blob:", "about:")) or key in allowed_hosts:
                if key in allowed_hosts:        # the ONE collector of the page's requests (X3, X8-2): a stand host only
                    self._record("request", method=route.request.method, url=url, rid=route.request)
                route.continue_()
            else:
                self._record("blocked", method=route.request.method, url=url)
                route.abort()
        context.route("**/*", guard)
        if local_storage:
            lines = "".join(f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in local_storage.items())
            context.add_init_script(lines)
        self._page = context.pages[0] if profile_dir is not None and context.pages else context.new_page()
        for kind, name, handler in (("response", "response", self._on_response), ("failed", "requestfailed", self._on_failed),
                                    ("console", "console", self._on_console), ("pageerror", "pageerror", self._on_pageerror)):
            self._page.on(name, self._guarded(kind, handler))

    # --- what the page did (t-1765 X8-2): every event carries the monotonic time of its handling and the character being typed
    def _record(self, kind, **fields) -> None:
        events = self.__dict__.setdefault("_events", [])
        events.append({"kind": kind, "t": time.monotonic(), "char": self.__dict__.get("_char"), "ours": False, **fields})

    def _guarded(self, kind, handler):
        """A listener that raises must not stop the page's event loop or the call: the kind is marked dead (the detector line says so) and
        the call goes on (P1). A dead listener is 'the detector did not see', never 'nothing happened' (AR-28)."""
        def run(*args):
            try:
                handler(*args)
            except Exception:  # noqa: BLE001
                self.__dict__.setdefault("_dead", set()).add(kind)
        return run

    def _is_ours(self, request) -> bool:
        return request in self.__dict__.get("_ours", {})

    def _on_response(self, response) -> None:
        request = response.request
        if host_key(response.url) in self._allowed:
            self._record("response", method=request.method, url=response.url, status=int(response.status), rid=request, ours=self._is_ours(request))

    def _on_failed(self, request) -> None:
        if host_key(request.url) in self._allowed:
            self._record("failed", method=request.method, url=request.url, failure=str(request.failure or ""), rid=request, ours=self._is_ours(request))

    def _on_console(self, message) -> None:
        if str(message.type) == "error":
            where = message.location if isinstance(message.location, dict) else {}
            self._record("console", text=str(message.text), location=str(where.get("url") or ""))

    def _on_pageerror(self, error) -> None:
        self._record("pageerror", text=str(error))

    def event_mark(self) -> int:
        return len(self.__dict__.get("_events", []))

    def events_since(self, mark) -> list:
        return [dict(e) for e in self.__dict__.get("_events", [])[mark:]]

    def dead_listeners(self) -> list:
        return sorted(self.__dict__.get("_dead", set()))

    # What the page says about the element at (x, y): evaluated on the target, so "is the top element the target or
    # inside it" needs no selector re-resolution. A plain object with no code of ours about the browser's wording.
    _TOP_AT_POINT = """(el, p) => {
        if (el.getRootNode() !== document) return null;
        const top = document.elementFromPoint(p[0], p[1]);
        if (!top) return null;
        if (top === el || el.contains(top)) return {covered: false};
        return {covered: true, tag: String(top.tagName || '').toLowerCase(),
                classes: Array.from(top.classList || []).slice(0, 2).map(String),
                text: String(top.innerText || top.textContent || '').slice(0, %d)};
    }""" % COVER_SCAN_CHARS

    def why_not_actionable(self, selector, need_pointer=False):
        """(what is wrong, the covering element's text or None) for an element step that ran out of time.

        Asked of the page with probes that wait for nothing - never read from the browser's wording. The only
        direction of error is "could not be established": a probe that fails is named, and the answer is then
        neither "no element matched" nor "covered"."""
        seconds = f"{self._element_ms / 1000:g}"

        def unknown(probe):
            return (f"{selector} was found, but why the action did not complete could not be established ({probe})", None)
        if selector is None:
            return ("the element could not be looked at, why the action did not complete could not be established "
                    "(no selector)", None)
        try:
            located = self._page.locator(selector)
            count = located.count()
        except Exception:
            return ("whether an element matched " + f"{selector} could not be established (count failed)", None)
        if count == 0:
            return (f"no element matched {selector} within {seconds} s", None)
        try:
            first = located.first
            if not first.is_visible():
                return (f"{selector} was found but is not visible", None)
            if not first.is_enabled():
                return (f"{selector} was found but is not enabled", None)
        except Exception:
            return unknown("a visibility or enabled probe failed")
        if not need_pointer:
            return unknown("it is visible and enabled")
        try:
            box = first.bounding_box()
            if not box:
                return unknown("it has no box on screen")
            point = [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2]
            top = first.evaluate(self._TOP_AT_POINT, point)
        except Exception:
            return unknown("the element at its center could not be read")
        if top is None:
            return unknown("the page names no element at its center")
        if not isinstance(top, dict) or not isinstance(top.get("covered"), bool):
            return unknown("the element at its center could not be read")
        if not top["covered"]:
            return unknown("no other element was found at its center")
        name = re.sub(r"[^A-Za-z0-9_-]+", "", str(top.get("tag") or "")) or "element"
        for css in top.get("classes") or []:
            css = re.sub(r"[^A-Za-z0-9_-]+", "", str(css))
            if css:
                name += "." + css
        text = " ".join(str(top.get("text") or "").split())[:COVER_SCAN_CHARS]
        return (f"{selector} is covered by {name}", text)

    def _timed(self, action, element=False, selector=None, need_pointer=False):
        started = time.perf_counter()
        try:
            action()
        except self._Timeout as exc:
            if element:
                head, cover = self.why_not_actionable(selector, need_pointer)
                raise StepFailed(head, cover=cover, said=_first_line(exc, ""))
            raise StepTimeout(time.perf_counter() - started)
        except self._Error as exc:
            raise StepFailed(_first_line(exc))
        return time.perf_counter() - started

    def goto(self, url):
        return self._timed(lambda: self._page.goto(url, timeout=self._limit_ms, wait_until="load"))

    def login(self, recipe, credentials, frontend_url):
        def run():
            page = self._page
            page.goto(frontend_url.rstrip("/") + recipe.get("path", "/"), timeout=self._limit_ms)
            page.wait_for_load_state("networkidle", timeout=self._limit_ms)
            expand = recipe.get("expand") or {}
            opener = (page.get_by_text(expand["text"]) if expand.get("text") else
                      page.get_by_test_id(expand["test_id"]) if expand.get("test_id") else None)
            if opener is not None and opener.is_visible():
                opener.click()
            field = self._field
            fit = recipe.get("fit_wait_s")
            if fit:
                # EP1-31: the factory's default form is only a guess - when it is not on this page within `fit` seconds,
                # say so at once instead of waiting out the element limit
                try:
                    field(recipe["username"]).wait_for(state="visible", timeout=fit * 1000)
                except self._Timeout:
                    raise StepFailed("the factory's default sign-in form is not on this page")
            field(recipe["username"]).fill(credentials.username)
            field(recipe["password"]).fill(credentials.password)
            field(recipe["submit"]).click()
            # No wait after the click: `networkidle` returned while the page was still /auth/sign-in with no
            # session (measured 02.10), and "ok" after it was a lie. Whether the login LANDED is `await_landing`'s
            # question, one deadline, URL and proof together.
        return self._timed(run)

    # What `await_landing` looks at. Read-only, none of them waits for anything but its own timer.
    def current_url(self) -> str:
        try:
            return str(self._page.url)
        except Exception:
            return ""

    def cookie_names(self) -> set:
        """The NAMES of the cookies the context holds, every domain, whose value is not empty. A value is never
        returned: it is a credential."""
        try:
            return {str(c.get("name")) for c in self._context.cookies() if c.get("value")}
        except self._Error as exc:
            raise StepFailed(_first_line(exc))

    def _field(self, row):
        """The locator of one field row of a login recipe: `{"test_id"}` (data-testid) or `{"role", "name"}` - a project's
        own way of naming its sign-in fields is a row of data (AR-1), never a branch of code."""
        if row.get("test_id"):
            return self._page.get_by_test_id(row["test_id"])
        return self._page.get_by_role(row["role"], name=row["name"])

    def field_visible(self, row) -> bool:
        try:
            return bool(self._field(row).is_visible())
        except self._Error as exc:
            raise StepFailed(_first_line(exc))

    def page_words(self, mode=None) -> str:
        """What the page says, on one line; "" when unreadable. `mode=None` (the failed login's words): the first visible
        heading, else the body's text. `"short"` (after a step that passed): the heading and the text of the visible
        dialogs and alerts (the body's text when the page has none of them). `"long"` (after a step that did not): the
        heading and the body's text. The body is read up to PAGE_TEXT_CHARS; any part that cannot be read is left out."""
        def heading():
            try:
                for element in self._page.locator("h1, h2, [role=heading]").all()[:20]:
                    if element.is_visible():
                        text = " ".join(element.inner_text(timeout=2000).split())
                        if text:
                            return text
            except Exception:
                pass
            return ""

        def body():
            try:
                return " ".join(self._page.locator("body").inner_text(timeout=2000)[:PAGE_TEXT_CHARS].split())
            except Exception:
                return ""

        def popups():
            found = []
            try:
                for element in self._page.locator("[role=dialog], [role=alert]").all()[:5]:
                    if element.is_visible():
                        text = " ".join(element.inner_text(timeout=2000)[:PAGE_TEXT_CHARS].split())
                        if text:
                            found.append(text)
            except Exception:
                pass
            return found
        if mode is None:
            return heading() or body()
        if mode == "short":
            parts = [heading(), *popups()]
            return " | ".join(p for p in parts if p) or body()
        return " | ".join(p for p in (heading(), body()) if p)

    def pause(self, seconds):
        """Wait inside Playwright, never `time.sleep`: the sync API handles navigation events only inside its own
        calls, so a sleeping process would never see the login complete."""
        try:
            self._page.wait_for_timeout(int(seconds * 1000))
        except self._Error as exc:
            raise StepFailed(_first_line(exc))

    def click(self, selector):
        return self._timed(lambda: self._page.locator(selector).first.click(timeout=self._element_ms), element=True,
                           selector=selector, need_pointer=True)

    def fill(self, selector, text):
        return self._timed(lambda: self._page.locator(selector).first.fill(text, timeout=self._element_ms), element=True,
                           selector=selector)

    def field_traits(self, selector) -> tuple:
        """({"type", "tag"}, seconds) of the field: the `type` attribute (`None` when it has none) and the lower-cased tag. Waits the element
        limit for the element, as every step with an element does; the caller (the data's `whole_types` / `whole_tags`) decides what
        can be keyed. The attribute is asked first: a field that never appears fails here, as a failed step, before any key."""
        box = {}

        def run():
            element = self._page.locator(selector).first
            box["type"] = element.get_attribute("type", timeout=self._element_ms)
            box["tag"] = str(element.evaluate("el => String(el.tagName || '').toLowerCase()", None) or "")
        seconds = self._timed(run, element=True, selector=selector)
        kind = box["type"]
        return {"type": None if kind is None else str(kind).lower(), "tag": box["tag"].lower()}, seconds

    def clear_field(self, selector):
        """(row, seconds, focus_s): the field emptied as a person does - focus, select all, delete - and one row `{n: "cleared", value,
        focus}` of what it holds afterwards (a mask or a controlled input may hand something back; the caller records it, FR-47)."""
        def act(page, sel):
            try:
                page.keyboard.press("ControlOrMeta+A")
            except self._Error:
                page.keyboard.press("Control+A")        # a Playwright older than 1.45 knows no ControlOrMeta
            page.keyboard.press("Delete")
            state = self._field_state(sel)
            return {"n": "cleared", "value": state["value"], "focus": state["focused"]}
        row, seconds, focus_s, _ = self._keyboard_step(selector, act)
        return row, seconds, focus_s

    def look(self, selector=None) -> tuple:
        """(text | None, form, why, seconds): what the page shows, the way a person sees it. `form` is `aria` (the accessibility tree of
        the element - the whole page when there is no selector) or `text` (the page's words, when the tree could not be read; `why` is the
        first line of the browser's reason). `None` text: nothing could be read, `why` says why. Never raises for the page's sake: the
        look is an observation (P1). A selector that matches nothing is NOT retried as text (it would wait the limit twice)."""
        started = time.perf_counter()
        target = selector or "body"
        why = ""
        try:
            tree = self._page.locator(target).first.aria_snapshot(timeout=self._element_ms)
            return str(tree or ""), "aria", "", time.perf_counter() - started
        except AttributeError:
            why = "this Playwright has no aria_snapshot"
        except Exception as exc:  # noqa: BLE001 - the browser's own error classes are not imported here
            why = _first_line(exc, "the accessibility tree could not be read")
            if selector and isinstance(exc, self._Timeout):
                return None, "", why, time.perf_counter() - started
        try:
            if selector:
                words = self._page.locator(selector).first.inner_text(timeout=self._element_ms)
            else:
                words = self.page_words("long")
        except Exception as exc:  # noqa: BLE001
            return None, "", why or _first_line(exc, "the page could not be read"), time.perf_counter() - started
        words = "\n".join(line for line in str(words or "").splitlines() if line.strip())
        return (words if words else None), "text", why, time.perf_counter() - started

    def watch_text(self, selector) -> str:
        """The text of the element NOW on one line (cut at PAGE_TEXT_CHARS), or `<gone>`: a short probe, never the element limit."""
        try:
            raw = self._page.locator(selector).first.inner_text(timeout=self._probe_ms())
        except Exception:  # noqa: BLE001
            return GONE
        return " ".join(str(raw or "").split())[:PAGE_TEXT_CHARS]

    def settle(self, settle_ms, idle_max_ms, remaining_s) -> bool:
        """Let the requests a step caused arrive (the sync API hands events over only inside its own calls): wait `settle_ms`, then for the
        network to go idle - for no longer than `idle_max_ms` and no longer than `remaining_s` in all. True: the network was idle; False: it
        was not, in the time there was (the step line says so); None: the page could not be asked (closed) - nothing is claimed."""
        budget_ms = max(0.0, float(remaining_s)) * 1000
        wait = min(float(settle_ms), budget_ms)
        try:
            if wait >= 1:
                self._page.wait_for_timeout(int(wait))
            idle_ms = min(float(idle_max_ms), budget_ms - wait)
            if idle_ms < 1:
                return False                          # a timeout of 0 would mean 'no limit' to the browser
            self._page.wait_for_load_state("networkidle", timeout=int(idle_ms))
            return True
        except self._Timeout:
            return False                              # the network did not quiet down in the time there was
        except Exception:  # noqa: BLE001 - a closed page is not this step's failure and says nothing about the network
            return None

    # --- keyboard input: fill sets the whole value at once and puts focus back, so it hides a lost character and a lost focus
    def _field_state(self, selector) -> dict:
        """{"value", "focused"} of the field NOW: a short probe (`probe_wait_ms` of the steps file), never the element limit.
        The value is `input_value`, else the element's text, else `<gone>`; a focus that cannot be read is `False`."""
        element = self._page.locator(selector).first
        wait = self._probe_ms()
        try:
            value = element.input_value(timeout=wait)
        except Exception:
            try:
                value = element.inner_text(timeout=wait)
            except Exception:
                value = GONE
        return {"value": value, "focused": self._has_focus(element, wait)}

    @staticmethod
    def _probe_ms() -> int:
        return int(spec().get("probe_wait_ms", 500))

    @staticmethod
    def _has_focus(element, wait) -> bool:
        try:
            return bool(element.evaluate("el => el.getRootNode().activeElement === el", timeout=wait))
        except Exception:
            return False

    def _keyboard_step(self, selector, act, refocus=True):
        """(rows, seconds, focus_s, focused_before): `act(page, selector)` runs after the focus - the ONE focus of the step, never one per
        character (a focus per character puts the focus back and hides the lost one). The focus is read BEFORE it is set.
        `refocus=False` (a `type` that goes on with the field the last step typed in, TR1-1): the focus is NOT set - a person who goes on
        typing does not click again; the keys go where the focus is, and when that is not the field `self.focus_lost_before` names what
        has it (the caller records the fact, FR-47). A field gone or detached is a failed step, nothing typed."""
        box = {}
        self.focus_lost_before = None

        def run():
            element = self._page.locator(selector).first
            if not refocus:
                try:
                    attached = bool(element.evaluate(CONNECTED_JS, timeout=self._probe_ms()))
                except Exception:
                    attached = False
                if not attached:
                    raise StepFailed("the field is gone or detached before the call: nothing was typed")
            box["before"] = self._has_focus(element, self._probe_ms())
            started = time.perf_counter()
            if refocus:
                element.focus(timeout=self._element_ms)
            elif not box["before"]:
                try:
                    self.focus_lost_before = str(element.evaluate(ACTIVE_JS, timeout=self._probe_ms()) or "nothing")
                except Exception:
                    self.focus_lost_before = "something that could not be read"
            box["focus_s"] = time.perf_counter() - started
            box["rows"] = act(self._page, selector)
        seconds = self._timed(run, element=True, selector=selector)
        return box["rows"], seconds, box["focus_s"], box["before"]

    def same_field(self, a, b) -> bool:
        """Do the selectors `a` and `b` resolve to ONE element of the page now? The page answers; anything not established is False (TR4-9)."""
        try:
            first, second = self._page.locator(a).first, self._page.locator(b).first
            other = second.element_handle(timeout=self._probe_ms())
            return bool(other) and bool(first.evaluate("(el, other) => el === other", other, timeout=self._probe_ms()))
        except Exception:
            return False

    def type_chars(self, selector, text, delay_ms, settle_ms=0, continued=False):
        """(rows, seconds, focus_s): one row per character `{n, value, focus}`, then `settled` after `settle_ms` - the page
        redraws after the server answers, later than any one character. Code records, the role judges (FR-47).
        `continued`: the call goes on with the field the step before typed in - no focus is set (see `_keyboard_step`)."""
        def act(page, sel):
            rows, deadline = [], time.perf_counter() + self._limit_ms / 1000
            try:
                for number, char in enumerate(text, 1):
                    if time.perf_counter() > deadline:      # the step limit holds INSIDE the loop; the rows read so far are kept
                        break
                    self._char = (number, len(text))        # the events handled during the pause belong to this character (X8-2)
                    page.keyboard.type(char)
                    page.wait_for_timeout(delay_ms)
                    state = self._field_state(sel)
                    rows.append({"n": number, "value": state["value"], "focus": state["focused"]})
            finally:
                self._char = None
            whole = len(rows) == len(text)
            if whole:
                page.wait_for_timeout(settle_ms)
            state = self._field_state(sel)
            rows.append({"n": "settled" if whole else "stopped", "value": state["value"], "focus": state["focused"]})
            return rows
        rows, seconds, focus_s, _ = self._keyboard_step(selector, act, refocus=not continued)
        return rows, seconds, focus_s

    def press_key(self, selector, key, continued=False):
        """(row, seconds, focus_s): the row carries `focused_before`, read before the focus is set. `continued`: as `type_chars` (TR1-2)."""
        return self._one_key_row(selector, key, lambda page: page.keyboard.press(key), continued)

    def paste_text(self, selector, text, continued=False):
        """(row, seconds, focus_s): inserted at once - the page gets an `input` event, not a `paste` event."""
        return self._one_key_row(selector, "paste", lambda page: page.keyboard.insert_text(text), continued)

    def _one_key_row(self, selector, name, do, continued=False):
        def act(page, sel):
            do(page)
            state = self._field_state(sel)
            return {"n": name, "value": state["value"], "focus": state["focused"]}
        row, seconds, focus_s, before = self._keyboard_step(selector, act, refocus=not continued)
        row["focused_before"] = before
        return row, seconds, focus_s

    # --- a failing dependency (EP1-30): a page route, laid over the context's `guard`, so a request of a host that is not a
    # stand is handed back to the guard (`fallback`) and never gets a made-up answer
    def allowed_hosts(self) -> set:
        return set(self._allowed)

    def fail_request(self, glob, how):
        """Every request of the page that matches `glob` gets the status `how` (a whole number, an empty JSON body) or is
        dropped as `timedout` (never held: the step does not hang). The record lives the whole session; a repeat of the
        glob takes the old route off and starts a new record, the last word wins."""
        old = self._failing.get(glob)
        if old and old["active"]:
            self._timed(lambda: self._page.unroute(glob, old["handler"]))
        top = _step_number({}, "fail_request", "max_logged")
        record = {"how": str(how), "hits": 0, "rows": [], "active": True}

        def handler(route):
            request = route.request
            if host_key(request.url) not in self._allowed:
                route.fallback()
                return
            self.__dict__.setdefault("_ours", {})[request] = True       # BEFORE it answers: its response/failure is ours, not the product's (X8-2)
            record["hits"] += 1
            if len(record["rows"]) < top:
                record["rows"].append({"method": request.method, "url": request.url})
            if record["how"] == "timeout":
                route.abort("timedout")
            else:
                route.fulfill(status=int(record["how"]), content_type="application/json", body="{}")
        record["handler"] = handler
        self._failing[glob] = record
        return self._timed(lambda: self._page.route(glob, handler))

    def restore_request(self, glob):
        record = self._failing.get(glob)
        if not record or not record["active"]:
            active = [g for g, r in self._failing.items() if r["active"]]
            raise StepFailed(f"no failing request is active for {glob}. Active: " + (", ".join(active) or "none"))
        seconds = self._timed(lambda: self._page.unroute(glob, record["handler"]))
        record["active"] = False
        return seconds

    def end_session(self):
        """TR1-3: (cookies deleted, seconds) - every cookie of THIS actor's browser context goes (the context is one actor's: a walk
        keeps one per actor); the page stays open as it was, as for a person whose session ran out. Only the count is returned: a
        cookie's name or value is a credential and never leaves here. A context with no cookie is a count of 0, not an error."""
        held = []

        def drop():
            held.append(len(self._context.cookies()))
            self._context.clear_cookies()
        seconds = self._timed(drop)
        return held[0], seconds

    def forget_failures(self) -> dict:
        """TR1-2: the end of an item of a walk - every failing rule is lifted (a route still on is taken off) and forgotten; what each caught
        is returned as `drain_failures` shows it, for the item's evidence. A rule never outlives the item that declared it."""
        seen = self.drain_failures()
        for glob, record in self._failing.items():
            if record["active"]:
                with contextlib.suppress(Exception):
                    self._page.unroute(glob, record["handler"])
                record["active"] = False
        self._failing = {}
        return seen

    def drain_requests(self) -> dict:
        """{rows: [{method, url, count}], count: n} - the requests the page sent to a stand host in this session (the context's guard
        sees every one that reaches the stand; it writes no file). A request `fail_request` answers never reaches the guard: it is in the
        `fail-request-*` log, not here."""
        seen: dict = {}
        for e in self.__dict__.get("_events", []):                  # a projection of the one collector, never a second counter
            if e["kind"] == "request":
                pair = (e["method"], _safe_url(e["url"]))
                seen[pair] = seen.get(pair, 0) + 1
        return {"rows": [{"method": m, "url": u, "count": c} for (m, u), c in seen.items()], "count": sum(seen.values())}

    def drain_failures(self) -> dict:
        """{glob: {how, hits, rows, active}} - what the routes saw. The handlers run inside Playwright and write no file."""
        return {g: {"how": r["how"], "hits": r["hits"], "rows": list(r["rows"]), "active": r["active"]}
                for g, r in self._failing.items()}

    def drag(self, selector, dx, dy):
        def run():
            box = self._page.locator(selector).first.bounding_box(timeout=self._element_ms)
            if not box:
                raise StepFailed("the element has no box on screen to drag")
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            self._page.mouse.move(x, y)
            self._page.mouse.down()
            self._page.mouse.move(x + dx, y + dy, steps=10)
            self._page.mouse.up()
        return self._timed(run, element=True, selector=selector, need_pointer=True)

    def wait_ms(self, ms):
        return self._timed(lambda: self._page.wait_for_timeout(ms))

    def wait_selector(self, selector):
        return self._timed(lambda: self._page.wait_for_selector(selector, timeout=self._element_ms), element=True,
                           selector=selector)

    def read(self, selector, mode):
        box = []

        def run():
            element = self._page.locator(selector).first
            if mode == "text":
                box.append(element.inner_text(timeout=self._element_ms))
            elif mode.startswith("attr="):
                got = element.get_attribute(mode[5:], timeout=self._element_ms)
                # absent is not empty: `None` is the data's marker, `""` (the attribute is there) stays `""`
                box.append(_absent_marker() if got is None else got)
            elif mode.startswith("state="):
                if mode[6:] not in (spec().get("read_states") or []):
                    raise StepFailed(f"`state={mode[6:]}` is not a state the factory reads")
                box.append("true" if getattr(element, "is_" + mode[6:])(timeout=self._element_ms) else "false")
            else:
                box.append(element.evaluate("(el, p) => getComputedStyle(el).getPropertyValue(p)", mode[6:]))
        seconds = self._timed(run, element=True, selector=selector)
        return box[0], seconds

    def screenshot(self, path):
        return self._timed(lambda: self._page.screenshot(path=str(path), full_page=False))

    def http(self, method, url, headers, body, timeout_s):
        """RN1-10: one request through the page's own context, so the session's cookies go with it (no Bearer token, no login
        request of the factory's). No redirect is followed (a 3xx is the answer, as `UrllibHttp`); an `HttpResult`."""
        started = time.perf_counter()
        try:
            answer = self._context.request.fetch(url, method=method, headers=dict(headers), data=body,
                                                 timeout=int(timeout_s * 1000), max_redirects=0, ignore_https_errors=True)
            raw = answer.body()
            heads = [(str(h.get("name")), str(h.get("value"))) for h in answer.headers_array]
        except self._Timeout:
            raise StepTimeout(time.perf_counter() - started)
        except self._Error as exc:
            raise StepFailed(f"the stand did not answer: {_first_line(exc)}")
        return HttpResult(answer.status, heads, raw[:BODY_CAP + 1], time.perf_counter() - started)

    def close(self):
        # a persistent context is closed itself (it has no browser object); the cookies stay in the profile on disk
        for closer in (lambda: self._context and self._browser is None and self._context.close(),
                       lambda: self._browser and self._browser.close(), lambda: self._pw and _driver_release(self._pw)):
            try:
                closer()
            except Exception:
                pass
        self._pw = None


_DRIVER = {"pw": None, "users": 0}      # ONE Playwright driver per process: a second `sync_playwright().start()` in the same thread is refused


def _driver_acquire(sync_factory):
    """The process's one driver, started by the first browser and shared by the others (a walk with two actors); every backend gets its own
    context or profile from it, so cookies are never shared."""
    if _DRIVER["pw"] is None:
        _DRIVER["pw"] = sync_factory().start()
    _DRIVER["users"] += 1
    return _DRIVER["pw"]


def _driver_release(pw):
    """Stops the driver when the last browser using it closes."""
    _DRIVER["users"] = max(0, _DRIVER["users"] - 1)
    if _DRIVER["users"] == 0 and _DRIVER["pw"] is not None:
        driver, _DRIVER["pw"] = _DRIVER["pw"], None
        driver.stop()


SLEEP = None                # (seconds) -> None; the pause of the device backend's polling, tests put a fake here
FIND_POLL_S = 0.5            # how often an element that is not there yet is looked for on a device
W3C_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"      # the W3C key of an element reference: general knowledge, not read from a real driver
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
WORD_ATTRS = ("text", "label", "content-desc")           # the attributes of a screen's element tree that carry words
SESSION_GONE = ("invalid session id", "session not created")


class _NoElement(Exception):
    """The driver said `no such element` (the field `error`, never its words, FR-12)."""

    def __init__(self, said=""):
        super().__init__(said)
        self.said = said


class AppiumBackend:
    """The hands on a device (EP1-41d): a W3C session of the driver server, one HTTP client (`http_client.fetch`, AR-15), the device
    stand's own functions for the device, the server and the session (`device_stand`, AR-15). The same methods as PlaywrightBackend
    plus `launch`, `back`, `source`, `device_log`. Every path and body below is general knowledge of the W3C protocol and of the driver,
    NOT read from a real driver (FR-33): a fake driver proves the factory's wiring, never a real server.

    Error direction: a doubtful answer is a failed step (less evidence), never a pass. `open` raises EnvBlocked (cause `device`) when
    the device, the server or the session is not ready. The session is deleted by `close` whatever happened."""
    close_note = ""

    def __init__(self, stand, row, values=None, sign_in=""):
        self.stand, self.row = stand, row
        self.values = os.environ if values is None else values
        self.sign_in = sign_in                     # the selector only the sign-in screen has ("" when none is recorded)
        self.sid = self.serial = ""
        self.clock = MONOTONIC or time.perf_counter
        self.sleep = SLEEP or time.sleep
        self._limit_s, self._element_s = DEFAULT_TIMEOUT_S, ELEMENT_WAIT_S

    # --- the session
    def _blocked(self, DS, state, line) -> "EnvBlocked":
        owner = "factory" if state in DS.FACTORY_STATES else "user"
        return EnvBlocked(line, DS.remedy(state, self.row, self.stand), owner, do_not_retry=True, cause="device")

    def open(self, timeout_s, allowed_hosts=(), local_storage=None, element_wait_s=ELEMENT_WAIT_S):
        import device_stand as DS
        self._limit_s, self._element_s = timeout_s, element_wait_s
        picked = DS.pick_device(self.row, self.stand, self.values)       # never "the first in the list"
        if picked["state"] != "picked":
            raise self._blocked(DS, picked["state"], picked["line"])
        said = DS.driver_status(self.stand, self.row)
        if said["state"] != "ready":
            raise self._blocked(DS, said["state"], said["line"])
        app = self.stand.get("app") if isinstance(self.stand.get("app"), dict) else {}
        session = dict(self.row.get("session") or {})
        if isinstance(app.get("extra_capabilities"), dict):
            session.update({str(k): v for k, v in app["extra_capabilities"].items()})
        if session.get("app_id_capability"):
            session[str(session["app_id_capability"])] = str(app.get("id") or "")      # the session starts this app
        if session.get("activity_capability") and str(app.get("activity") or "").strip():
            session[str(session["activity_capability"])] = str(app["activity"]).strip()      # and its first screen (F-10)
        made = DS.create_session(self.stand, dict(self.row, session=session), picked["serial"])
        if made["state"] != "ok":
            raise self._blocked(DS, made["state"], made["line"])
        self.sid, self.serial = made["session_id"], picked["serial"]

    def close(self):
        if not self.sid:
            return
        import device_stand as DS
        sid, self.sid = self.sid, ""
        try:
            gone = DS.delete_session(self.stand, self.row, sid)
        except Exception as exc:
            gone = {"state": "failed", "line": exc.__class__.__name__}
        if gone["state"] != "deleted":
            self.close_note = (f"the device session {sid[:60]} could not be deleted ({gone['line']}); the driver server ends it "
                               "by itself after its idle limit")

    # --- one request
    def _request(self, method, path, body=None, snapshot=False, what=""):
        import device_stand as DS
        data = DS.driver_data(self.row)
        base = DS.base_url(self.stand, data)
        if base is None or not self.sid:
            raise StepFailed("the environment row has no usable `driver.url`, or no session is open", by="the driver")
        limit = int(data["snapshot_max_body" if snapshot else "max_body"])
        url = base + str(data["session_path"]) + "/" + quote(self.sid, safe="") + path
        payload = None if body is None else json.dumps(body).encode("utf-8")
        started = self.clock()
        try:
            answer = DS.fetch(url, method=method, data=payload, timeout=self._limit_s, max_body=limit, expect="json",
                              headers={"Content-Type": "application/json; charset=utf-8"} if payload is not None else None)
        except (socket.timeout, TimeoutError):
            raise StepTimeout(self.clock() - started)
        except (OSError, http.client.HTTPException) as exc:
            if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise StepTimeout(self.clock() - started)
            raise StepFailed(f"the driver server did not answer ({exc.__class__.__name__})", by="the driver")
        if answer.truncated:
            raise StepFailed(f"the driver's answer is larger than the limit {limit}; nothing was kept", by="the driver")
        if answer.unreadable:
            raise StepFailed("the driver's answer could not be read to the end; nothing was kept", by="the driver")
        try:
            parsed = json.loads(bytes(answer.body or b"").decode("utf-8", errors="replace"))
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict) or "value" not in parsed:
            raise StepFailed(f"the driver's answer is not a W3C answer (HTTP {answer.status}, no `value`)", by="the driver")
        value = parsed["value"]
        if isinstance(value, dict) and isinstance(value.get("error"), str):
            code = value["error"]
            said = _first_line(value.get("message") or "", "")
            if code == "no such element":
                raise _NoElement(said)
            if code in SESSION_GONE:
                raise StepFailed("the driver's session is gone (" + code + "): the device or the server dropped it, so no further step "
                                 "can run in it; capture again in a new attempt", said=said, by="the driver")
            raise StepFailed(f"{what or 'the request'}: the driver answered `{code}`", said=said, by="the driver")
        if not 200 <= int(answer.status or 0) < 300:
            raise StepFailed(f"{what or 'the request'}: the driver answered HTTP {answer.status}", by="the driver")
        return value

    def _element(self, selector, wait_s=None):
        """The element reference the selector `<strategy>=<value>` finds, polled until the element wait ends."""
        using, _, value = str(selector).partition("=")
        wait = self._element_s if wait_s is None else wait_s
        deadline, said = self.clock() + wait, ""
        while True:
            try:
                found = self._request("POST", "/element", {"using": using, "value": value}, what=str(selector))
            except _NoElement as exc:
                said = exc.said
            else:
                ref = (found.get(W3C_ELEMENT) or found.get("ELEMENT")) if isinstance(found, dict) else None
                if isinstance(ref, str) and ref:
                    return ref
                raise StepFailed(f"the driver's answer names no element for {selector}", by="the driver")
            if self.clock() >= deadline:
                raise StepFailed(f"no element matched {selector} within {wait:g} s", said=said, by="the driver")
            self.sleep(min(FIND_POLL_S, max(deadline - self.clock(), 0)))

    def _on(self, selector, method, tail, body=None):
        started = self.clock()
        ref = self._element(selector)
        value = self._request(method, f"/element/{quote(ref, safe='')}{tail}", body, what=str(selector))
        return value, self.clock() - started

    # --- the steps
    def click(self, selector):
        return self._on(selector, "POST", "/click", {})[1]

    def fill(self, selector, text):
        started = self.clock()
        ref = self._element(selector)
        self._request("POST", f"/element/{quote(ref, safe='')}/clear", {}, what=str(selector))
        self._request("POST", f"/element/{quote(ref, safe='')}/value", {"text": text}, what=str(selector))
        return self.clock() - started

    def drag(self, selector, dx, dy):
        started = self.clock()
        rect, _ = self._on(selector, "GET", "/rect")
        try:
            x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        except (KeyError, TypeError):
            raise StepFailed("the element has no box on screen to drag", by="the driver")
        move = {"type": "pointerMove", "duration": 0, "x": int(x), "y": int(y)}
        finger = {"type": "pointer", "id": "finger", "parameters": {"pointerType": "touch"}, "actions": [
            move, {"type": "pointerDown", "button": 0}, {"type": "pause", "duration": 100},
            {"type": "pointerMove", "duration": 600, "origin": "pointer", "x": int(dx), "y": int(dy)}, {"type": "pointerUp", "button": 0}]}
        try:
            self._request("POST", "/actions", {"actions": [finger]}, what=str(selector))
        finally:
            try:
                self._request("DELETE", "/actions")
            except (StepFailed, StepTimeout, _NoElement):
                pass
        return self.clock() - started

    def wait_ms(self, ms):
        self.sleep(ms / 1000)
        return ms / 1000

    def wait_selector(self, selector):
        started = self.clock()
        self._element(selector)
        return self.clock() - started

    def read(self, selector, mode):
        if mode == "text":
            value, took = self._on(selector, "GET", "/text")
        elif mode.startswith("attr=") and mode[5:]:
            value, took = self._on(selector, "GET", "/attribute/" + quote(mode[5:], safe=""))
            value = _absent_marker() if value is None else value          # absent is not empty (AR-28)
        else:
            raise StepFailed(f"`{mode}` is not a read of this surface", by="the driver")
        if not isinstance(value, str):
            raise StepFailed(f"the driver's answer for {selector} is not a text", by="the driver")
        return value, took

    def screenshot(self, path):
        started = self.clock()
        value = self._request("GET", "/screenshot", snapshot=True, what="the screenshot")
        try:
            raw = base64.b64decode(value, validate=True) if isinstance(value, str) else b""
        except ValueError:
            raw = b""
        if not raw.startswith(PNG_SIGNATURE):       # a file that is no picture is never registered
            raise StepFailed("the driver's screenshot is not a base64 PNG; nothing was kept", by="the driver")
        Path(path).write_bytes(raw)
        return self.clock() - started

    def source(self):
        started = self.clock()
        value = self._request("GET", "/source", snapshot=True, what="the screen's source")
        if not isinstance(value, str):
            raise StepFailed("the driver's source is not a text", by="the driver")
        return value, self.clock() - started

    def launch(self):
        started = self.clock()
        app = str((self.stand.get("app") or {}).get("id") or "")
        key = (self.row.get("session") or {}).get("app_id_param")       # ONE key, the row's: Appium 2 refuses both together (F-1)
        if not isinstance(key, str) or not key:
            raise StepFailed("the table row names no key for the app id of `launch` (session.app_id_param of references/"
                             "surfaces.json): this is a factory defect; record it as a finding", by="the factory")
        self._request("POST", "/appium/device/activate_app", {key: app}, what="launch")
        return self.clock() - started

    def back(self):
        started = self.clock()
        self._request("POST", "/back", {}, what="back")
        return self.clock() - started

    def device_log(self):
        """(text, cut, seconds), or None when the surface keeps no log. The tool is the row's (`device_stand.run_tool`)."""
        spec = self.row.get("log")
        if not isinstance(spec, dict):
            return None
        import device_stand as DS
        tail = str(spec.get("tail_lines") or 200)
        argv = [str(p).replace("{device}", self.serial).replace("{tail}", tail) for p in spec.get("argv") or []]
        started = self.clock()
        ran = DS.run_tool(argv, DS.tool_timeout(), limit=BODY_CAP)
        if ran["state"] != "ok":
            raise StepFailed(ran["line"], by="the device tool")
        return ran["out"], ran["cut"], self.clock() - started

    # --- what the role and the landing look at
    def current_url(self) -> str:
        """`app://sign-in` while the recorded sign-in selector is found, else `app://screen`; "" when it cannot be told (the
        sign-in window then stays open: less screen)."""
        if not self.sign_in:
            return "app://screen"
        try:
            self._element(self.sign_in, 0)
        except StepFailed as exc:
            return "app://screen" if exc.head.startswith("no element matched") else ""
        except Exception:
            return ""
        return "app://sign-in"

    def _gone(self, selector) -> bool:
        """True only when the driver answered that nothing matches; any other failure is not an answer about the element."""
        try:
            self._element(selector, 0)
        except StepFailed as exc:
            return exc.head.startswith("no element matched")
        except Exception:
            return False
        return False

    def page_words(self, mode=None) -> str:
        try:
            return self.words_of(self.source()[0])
        except Exception:
            return ""

    @staticmethod
    def words_of(xml_text) -> str:
        """The words of an element tree: the attributes `WORD_ATTRS`, on one line, cut at PAGE_TEXT_CHARS. Entities and a doctype are
        refused up front (nothing expands); a tree that cannot be read gives "" (less text, never a failed step)."""
        lowered = str(xml_text).lower()
        if "<!entity" in lowered or "<!doctype" in lowered:
            return ""
        try:
            root = ET.fromstring(str(xml_text))
        except Exception:
            return ""
        parts = [" ".join(str(el.get(a) or "").split()) for el in root.iter() for a in WORD_ATTRS]
        return " ".join(p for p in parts if p)[:PAGE_TEXT_CHARS]

    def why_not_actionable(self, selector, need_pointer=False):
        if self._gone(selector):
            return (f"no element matched {selector} within {self._element_s:g} s", None)
        return (f"{selector} was found, but why the action did not complete could not be established", None)

    def drain_failures(self) -> dict:
        return {}               # a device has no failing routes (`fail_request` is a browser step)

    def drain_requests(self):
        return None             # a device has no browser requests: the capture says the log is a gap (t-1765 X3)

    def allowed_hosts(self) -> set:
        return set()


def harness_argv(cfg: dict, project_root: Path) -> tuple:
    """(argv, cwd): the interpreter of the first test profile that fits a `ui` capture (its `capabilities` hold a word of
    `capture_surfaces.ui`, or its id is that surface's level) and whose command runs `pytest` - the command up to `pytest`,
    then `python` - and its cwd. A project whose tests are not python has no such profile: the refusal then names the
    install of Playwright for the factory's own Python, and no profile id of any one project (EP1-28)."""
    unread = ""
    data = spec()
    row = (data.get("capture_surfaces") or {}).get("ui") or {}
    profiles = cfg.get("profiles")
    for profile in profiles if isinstance(profiles, list) else []:     # a config on disk may hold any shape: no profile
        if not _fits_surface(profile, row):
            continue
        # every command of the profile, through the ONE reader of the shape (OH3-27, AR-13): a shape it cannot read has no
        # command that runs `pytest`, and the refusal below says why
        commands, problem = profile_commands(profile)
        if problem:
            unread = f" (the profile's commands cannot be read: {problem})"
        for command in commands.values():
            argv, problem = command_argv(command)
            if problem or not argv:
                continue
            for index, token in enumerate(argv):
                if Path(str(token)).name.lower().removesuffix(".exe") == "pytest":
                    head = [str(a) for a in argv[:index]] + ["python"]
                    folder = Path(str(command.get("cwd") or "."))
                    return head, (folder if folder.is_absolute() else project_root / folder)
    raise ValueError(data["capture_words"]["harness_none"].format(
        door=_browser_door("this interpreter has no Playwright")) + unread)


def _browser_door(why) -> str:
    return spec()["capture_words"]["browser_door"].format(why=why)


def _reexec_in_harness(cfg, project_root, argv) -> int:
    head, folder = harness_argv(cfg, project_root)
    program = shutil.which(head[0]) or head[0]
    command = [program, *head[1:], str(Path(__file__).resolve()), *argv, "--in-harness"]
    try:
        return subprocess.run(command, cwd=str(folder)).returncode
    except OSError as exc:
        raise ValueError(spec()["capture_words"]["harness_unstarted"].format(
            head=head[0], error=exc.__class__.__name__, folder=folder,
            door=_browser_door("this interpreter has no Playwright and the harness one did not start")))


# --------------------------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------------------------

def _summary(attempt: Attempt, case, steps, captures_before, failed, probes, observed=False) -> dict:
    """The one JSON object on stdout. `observed` (a `ui` call): each step row also carries `screenshot` and `text` when
    it was observed, the sum of the excerpts is held to OBSERVE_TOTAL_CHARS (the excerpts of passed steps are emptied
    from the start, `observation_trimmed` counts them; a failed step's excerpt is never cut), and `observation` says
    where the screenshots of passed steps are and that they are not part of the record (FR-41)."""
    lines = [json.loads(x) for x in (attempt.dir / "captures.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (attempt.dir / "captures.jsonl").is_file() else []
    rows = [{"step": s["step"], "outcome": s["outcome"],
             **({"screenshot": s.get("screenshot"), "text": s.get("text") or ""} if "screenshot" in s else {}),
             **({"hits_at_capture": s["hits_at_capture"]} if "hits_at_capture" in s else {}),
             **({"surprise": s["surprise"]} if s.get("surprise") else {})}
            for s in steps]
    total, trimmed = sum(len(r.get("text") or "") for r in rows), 0
    for row in rows:
        if total <= OBSERVE_TOTAL_CHARS:
            break
        if row["outcome"] == "ok" and row.get("text"):
            total -= len(row["text"])
            row["text"], trimmed = "", trimmed + 1
    out = {"ok": failed is None, "case": case, "attempt": attempt.name, "dir": attempt.rel(attempt.dir),
           "captures": [{k: v for k, v in c.items() if k in ("path", "kind", "phase", "proves", "content_hash")}
                        for c in lines[captures_before:]],
           "steps": rows, "failed": failed, "limitations": list(attempt.limitations), "probe": probes}
    out["surprises"] = [{k: s[k] for k in ("id", "step", "kind", "fact")} for s in getattr(attempt, "call_surprises", [])]   # t-1765 X8-2: [] is NOT
    # 'nothing happened' - `surprise_detection` says whether anyone watched
    out["surprise_detection"] = _detection_of(attempt.dir)
    if attempt.failures_without_hits:      # a `fail_request` that matched nothing: the role reads it with `limitations` (EP1-30)
        out["failures_without_hits"] = list(attempt.failures_without_hits)
    if observed:
        out["observation"] = (f"screenshots of steps that passed are in {attempt.rel(attempt.dir)}/{OBSERVE_DIR} and are "
                              "not part of the record")
        if trimmed:
            out["observation_trimmed"] = trimmed
    return out


def _count_captures(attempt: Attempt) -> int:
    path = attempt.dir / "captures.jsonl"
    return sum(1 for x in path.read_text(encoding="utf-8").splitlines() if x.strip()) if path.is_file() else 0


def _detail(value) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= SUMMARY_DETAIL_CHARS else text[:SUMMARY_DETAIL_CHARS] + "..."


def _safe_url(url) -> str:
    """scheme://host[:port]/path of a URL: no credentials, no query, no fragment (an OAuth `code=` is a secret)."""
    text = str(url or "")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return ""
    if not parts.scheme:
        return ""
    host = parts.hostname or ""
    if not host:
        return f"{parts.scheme}:{parts.path}"
    return f"{parts.scheme}://{host}{f':{port}' if port else ''}{parts.path}"


def _poll_landing(backend, recipe, url_not, cookie, hosts) -> tuple:
    """(missing clauses, the URL seen, the error of this poll or ""): one look at the page. All of the following
    must hold to land: the URL is http(s) on a configured stand host (Q5: `chrome-error://` and `about:blank` are
    pages, not sessions), the URL holds no `url_not` fragment, and the proof holds - the session cookie exists, or
    with no cookie named the username field is gone. A primitive that raises is NOT a proof: the poll is "not
    landed" and the error is kept (E9)."""
    missing, error = [], ""
    try:
        url = str(backend.current_url() or "")
    except StepFailed as exc:
        url, error = "", str(exc)
    key = host_key(url)
    if key is None or key not in hosts:
        missing.append("not on a stand address")
    if any(piece in url for piece in url_not):
        missing.append("still on a sign-in address")
    try:
        if cookie:
            if cookie not in backend.cookie_names():
                missing.append(f"no cookie {cookie}")
        elif backend.field_visible(recipe["username"]):
            missing.append("the sign-in field is still visible")
    except StepFailed as exc:
        error = str(exc)
        missing.append(f"no cookie {cookie}" if cookie else "the sign-in field is still visible")
    return missing, url, error


def await_landing(backend, recipe, hosts, limit_s) -> dict:
    """Wait for a submitted login to LAND, to ONE deadline (t-292). Submitting is not signing in: the page stays on
    the sign-in address for a few seconds and then the stand's own redirect chain finishes (measured on the local
    stand, rehearsal/11-login-probe.txt), and a `goto` before that cuts it off. Polled every LANDING_POLL_S through
    the backend's own timer; the last poll is AT the limit and never later, so a landing exactly at the limit counts
    and one poll beyond it does not (the error direction of a short limit is a false "failed", never a false ok).

    {"landed": True, "url": <no query, no fragment>, "elapsed_s", "proof": "cookie <name>" | "the sign-in field is
    gone"}; not landed adds "missing" (the clauses that did not hold), "words" (what the page says, read once at the
    end: "" when unreadable) and "error" (the last primitive error, or "")."""
    url_not, cookie = landing_rule(recipe)
    clock = MONOTONIC or time.perf_counter
    start = clock()
    error = ""
    while True:
        missing, url, poll_error = _poll_landing(backend, recipe, url_not, cookie, hosts)
        elapsed = clock() - start
        if not missing:
            return {"landed": True, "url": _safe_url(url), "elapsed_s": round(elapsed, 2),
                    "proof": f"cookie {cookie}" if cookie else "the sign-in field is gone"}
        error = poll_error or error
        if elapsed >= limit_s:
            break
        try:
            backend.pause(min(LANDING_POLL_S, limit_s - elapsed))
        except StepFailed as exc:
            error = str(exc)        # the browser cannot even wait: nothing more can be proven, say so now
            break
    try:
        words = " ".join(str(backend.page_words() or "").split())
    except Exception:
        words = ""
    return {"landed": False, "url": _safe_url(url), "elapsed_s": round(clock() - start, 2), "missing": missing,
            "words": words, "error": error}


def _hide(text, credentials) -> str:
    """`text` with the account's name and password replaced by [redacted] (the longer value first)."""
    out = str(text or "")
    for value in sorted({credentials.username, credentials.password}, key=len, reverse=True):
        if value:
            out = out.replace(value, "[redacted]")
    return out


def _login_failure_detail(result, limit_s, credentials, cfg) -> str:
    """The step detail of a login that did not land (spec t-292 section 4). The NAMES come before the page's words, so
    the cut of `_detail` takes only words. The words never carry the account (replaced), never match a secret
    pattern (then they are not kept, and the text says which one) and are cut at LANDING_WORDS_CHARS."""
    words = _hide(result.get("words"), credentials)
    hit = secret_pattern_hit(words, cfg) if words else None
    if hit is not None:
        shows = f"the page shows: \"(not kept: matches secret_content_patterns[{hit}])\""
    elif words:
        shows = "the page shows: \"" + (words if len(words) <= LANDING_WORDS_CHARS
                                         else words[:LANDING_WORDS_CHARS] + "...") + "\""
    else:
        shows = "the page's words could not be read"
    error = _hide(result.get("error"), credentials)
    if credentials.label and not credentials.user_key:
        account = f"{credentials.label}, a user this story created"        # the name of a created user, never its password
    elif credentials.label:
        account = f"{credentials.label}: {credentials.user_key} in {credentials.env_file}"
    else:
        account = f"{credentials.user_key} in {credentials.env_file}"
    return (f"login did not land within {limit_s:g} s: the page is {result.get('url') or 'unknown'}, "
            + " and ".join(result.get("missing") or ["not proven"])
            + f" (account: {account}, names only)"
            + (f"; the last error was: {error[:120]}" if error else "") + f"; {shows}")


def _login_blocked(detail, credentials, frontend_url, owner, cause="") -> EnvBlocked:
    """The env_blocked row of a login by code that did not land: `do_not_retry` (the same page answers again) and an
    owner - `user` after the submit (the stand or its test account), `factory` before it (the page never loaded or a
    sign-in field was not found: the recipe does not fit the page). A session whose sign-in gate A had PROVED
    (RN1-10) names `environment` with the cause `stand`: the account worked when probed, so what changed is the stand."""
    host = urlsplit(str(frontend_url)).netloc.rpartition("@")[2] or str(frontend_url)
    if credentials.label and not credentials.user_key:
        remedy = (f"the user {credentials.label} (created in this story) does not sign in on {host}, or the stand's "
                  "sign-in is down: create another user (see the create route in your brief) or name an account "
                  f"({_ACTOR_DOOR}), then capture again. Do not capture this case again as {credentials.label} "
                  "before that")
    elif credentials.label:
        remedy = (f"the account {credentials.label} ({credentials.user_key} / {credentials.password_key} in "
                  f"{credentials.env_file}) does not sign in on {host}, or the stand's sign-in is down: fix the account "
                  f"or the stand, or name another account ({_ACTOR_DOOR}), then capture again. Do not capture this "
                  f"case again as {credentials.label} before that")
    else:
        remedy = (f"the stand's test account ({credentials.user_key} / {credentials.password_key} in "
                  f"{credentials.env_file}) does not sign in on {host}, or the stand's sign-in is down: fix the account "
                  "or the stand, then capture again. Do not capture this case again before that")
    return EnvBlocked("login by code: " + detail, remedy, owner, do_not_retry=True, cause=cause)


def _session_login(cfg: dict, project_root, kind: str, args, stand):
    """The credentials a call signs in with, or None when it signs in as nobody (HF5-3). t-308 F1: a login declared null
    is never read (the driver's gate already says "no problem" for it), and `--as` with it is refused. Else who signs in:
    `--as`, else the one account the case's own request names (B3), else the stand's default."""
    actor = getattr(args, "actor", None)
    if login_declared_none(cfg, kind):
        if actor is not None:
            raise ValueError(NO_LOGIN_AS)
        return None
    actor = actor if actor is not None else auto_actor(cfg, stand, args.task_root, args.case)
    return (read_login(cfg, project_root) if actor is None else
            read_login(cfg, project_root, actor=actor, stand=stand, task_root=args.task_root))


# --------------------------------------------------------------------------------------------
# a session per actor (RN1-10): the hands of a manual case sign in as the project, step by step
# --------------------------------------------------------------------------------------------

SESSIONS_DIR = "sessions"                         # <attempt>/sessions/<actor-slug>/{profile/, state.json}
SIGN_IN_PROBE = ("state", "sign-in-probe.json")   # gate A's proof of each actor's sign-in, under the story's folder
SESSION_VS_AS = ("`--session <actor>` names the account the session signs in as; `--as` names one too. Leave `--as` out "
                 "(the actor of `--session` takes the same forms: default, a role, env:USER_KEY/SECRET_KEY, created:<name>)")
_NOT_PLAIN = re.compile(r"[^a-z0-9]+")


def recipe_sha(recipe) -> str:
    """The fingerprint of a login recipe: sha256 of its JSON with sorted keys. Gate A writes it beside the proof of an actor's
    sign-in and a `--session` call compares it: a proof made for another recipe proves nothing for this one."""
    text = json.dumps(recipe if isinstance(recipe, dict) else {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def actor_slug(actor) -> str:
    """The folder name of an actor's session. A name that is not already plain lower case gets a short hash of the actor, so
    two actors never share a folder (and so a profile, whose cookies are a credential)."""
    text = str(actor)
    plain = _NOT_PLAIN.sub("-", text.lower()).strip("-")[:40] or "actor"
    return plain if re.fullmatch(r"[a-z0-9-]+", text) else f"{plain}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:6]}"


class ActorSession:
    """One actor's session inside one attempt: `<attempt>/sessions/<slug>/profile` (the browser's persistent profile - the
    cookies are a credential, so `session close` deletes it) and `state.json` (no cookie in it: who, whether the profile
    holds a proven sign-in, the last page). Calls of one case with the same `--session` meet the same profile."""

    def __init__(self, attempt_dir, actor, folder=None):
        self.actor = str(actor)
        self.dir = Path(folder) if folder is not None else Path(attempt_dir) / SESSIONS_DIR / actor_slug(actor)
        self.profile = self.dir / "profile"
        self.state_path = self.dir / "state.json"

    def state(self) -> dict:
        return hooklib.read_json(self.state_path, {}, kind=dict)

    def save(self, **fields) -> dict:
        data = {**self.state(), **fields, "actor": self.actor}
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data

    def signed_in(self) -> bool:
        """A sign-in recorded for THIS actor whose profile is still on disk (a closed or lost profile signs in again)."""
        state = self.state()
        return state.get("signed_in") is True and state.get("actor") == self.actor and self.profile.is_dir()

    def prove_after_form(self, backend, recipe, hosts) -> None:
        """The agent signed in through the form (`fill-account` steps): the proof is the same `await_landing`, asked once (limit 0 =
        one look), and a landed page is written to the state for the next call (F1, F10). Nothing is written when it did not land
        or the profile already holds a proof."""
        if self.signed_in():
            return
        try:
            landing = await_landing(backend, recipe, hosts, 0)
        except Exception:
            landing = {"landed": False}
        if landing.get("landed"):
            self.save(signed_in=True, proof="fill-account steps; " + landing["proof"], at=_now())

    def last_url(self) -> str:
        url = self.state().get("last_url")
        return url if isinstance(url, str) else ""

    def remember(self, backend, hosts) -> None:
        """Keep the page the call ended on, for the next call to open: a stand address, no query, no fragment. Anything else
        (a page of another host, an unreadable URL) leaves the old one."""
        try:
            url = _safe_url(backend.current_url())
        except Exception:
            return
        if url and host_key(url) in hosts:
            self.save(last_url=url)


def sign_in_row(task_root, actor):
    """The row of `state/sign-in-probe.json` for `actor`, or None (a missing, unreadable or malformed file is no proof)."""
    try:
        data = json.loads(Path(task_root).joinpath(*SIGN_IN_PROBE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    row = data.get(str(actor)) if isinstance(data, dict) else None
    return row if isinstance(row, dict) else None


def _probe_readable(task_root) -> bool:
    """True when the probe file is absent (then a missing row is just missing) or a readable JSON object."""
    path = Path(task_root).joinpath(*SIGN_IN_PROBE)
    if not path.is_file():
        return True
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8-sig")), dict)
    except (OSError, ValueError):
        return False


def _profile_signed_in(args, attempt_name, actor) -> bool:
    """True when the actor's profile in the named attempt already holds a proven sign-in (F1: the form sign-in of an earlier
    call). ERROR DIRECTION: any doubt (no attempt yet, no state, a closed profile) is False and the probe row is asked."""
    return bool(attempt_name) and ActorSession(case_root(args.task_root, args.case) / attempt_name, actor).signed_in()


def sign_in_refusal(task_root, actor, recipe) -> str:
    """"" when the stand probe of gate A proved this actor's sign-in with THIS recipe, else the refusal of a `--session` call
    (exit 2, the factory's: nothing was opened). ERROR DIRECTION: no row, an unreadable file, an outcome other than `ok` or
    another recipe's fingerprint all refuse - a sign-in nobody proved is never run in S6, and is never put on a person."""
    row = sign_in_row(task_root, actor)
    if row is not None and row.get("outcome") == "ok" and row.get("recipe_sha") == recipe_sha(recipe):
        return ""
    why = ("it has no row" if row is None and _probe_readable(task_root)
           else "the file is unreadable or malformed, so it has no usable row" if row is None
           else f"its row says {str(row.get('outcome'))[:30]!r}" if row.get("outcome") != "ok"
           else "its row was made for another login recipe")
    return (f"the sign-in of `{str(actor)[:80]}` was not proved by the stand probe (gate A; {why} in "
            f"{'/'.join(SIGN_IN_PROBE)}); nothing was opened. This is the factory's to fix: run `gate_preflight.py --task "
            f"{Path(task_root).resolve().name} --gate A` so the probe signs the account in, or sign in yourself with "
            "`fill-account <selector> <actor> user|secret` steps in this session")


def recipe_rows_problem(recipe) -> str:
    """"" or what is wrong with the field rows of a login recipe. A row is `{"test_id": <data-testid>}` or `{"role", "name"}`;
    the opener (`expand`) is `{"text"}` or `{"test_id"}`. Only a key that is present is judged: a recipe that leaves a row out
    keeps the meaning it always had."""
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    for key in ("username", "password", "submit"):
        if key in recipe:
            row = recipe[key]
            if not (isinstance(row, dict) and (text(row.get("test_id")) or (text(row.get("role")) and text(row.get("name"))))):
                return (f"manual_capture.login.ui.{key} in config.json names neither a `test_id` nor a `role` with a `name`. "
                        "Expected {\"test_id\": \"<data-testid of the field>\"} or {\"role\": \"textbox\", \"name\": "
                        "\"<its accessible name>\"} (the factory's default, references/manual-capture-steps.json); leave "
                        "the key out to take the default")
    expand = recipe.get("expand")
    if expand is not None and not isinstance(expand, dict):
        return ("manual_capture.login.ui.expand in config.json is not an object. Expected {\"text\": \"<words of the "
                "opener>\"} or {\"test_id\": \"<its data-testid>\"}; leave the key out to take the default")
    return ""


def _frontend_of(cfg, stand, project_root) -> str:
    import env_probe
    return env_probe.frontend_of(cfg, str((stand or {}).get("name") or ""), entry=stand, root=project_root)["url"] \
        or str((stand or {}).get("base_url") or "")


def sign_in(backend, cfg, project_root, actor, stand, *, task_root=None, session=None, credentials=None, spec_data=None,
            hosts=None, timeout_s=None) -> dict:
    """Sign `actor` in through the project's `login.ui` recipe and PROVE it landed (`await_landing`) - the ONE sign-in of a
    manual capture, called by a session and by gate A's probe alike (AR-13, AR-15). `session` (an `ActorSession`): a profile that
    already holds a proven sign-in of this actor is reused and nothing is done; a new proof is written to its state.json.
    The answer, always a dict: `{"signed_in": True, "actor", "proof", "at", "url", "elapsed_s"}` (+ `"reused": True`, + `"weak":
    True` when the recipe has no `landed` rule and the proof is only the sign-in field being gone); or `{"signed_in": False,
    "kind", "actor", "detail"}` with `kind` = `no_recipe` (the project records no UI sign-in), `before_submit` (the page never
    loaded or a field was not found: the recipe does not fit the page) or `not_landed` (it was submitted and did not land);
    `detail` never holds the account (`_hide`). ERROR DIRECTION: a false `not_landed`, never a false `signed_in`."""
    spec_data = spec_data or spec()
    actor = str(actor)
    if session is not None and session.signed_in():
        state = session.state()
        return {"signed_in": True, "reused": True, "actor": actor, "proof": str(state.get("proof") or ""),
                "at": str(state.get("at") or "")}
    recipe = login_recipe(cfg, spec_data, "ui")
    if not recipe:
        return {"signed_in": False, "kind": "no_recipe", "actor": actor,
                "detail": "the project records no UI sign-in (manual_capture.login.ui is empty)"}
    credentials = credentials or read_login(cfg, project_root, actor=actor, stand=stand, task_root=task_root)
    if credentials is None:
        return {"signed_in": False, "kind": "no_recipe", "actor": actor,
                "detail": "config.json names no file for the stand's accounts (environment.env_file)"}
    hosts = set(hosts) if hosts is not None else set(stand_hosts(cfg, root=project_root))
    timeout_s = timeout_s or timeout_for(stand or {})
    fit = spec_data.get("login", {}).get("ui_fit_wait_s") if "ui" not in _own_login(cfg) else None
    try:
        backend.login(dict(recipe, fit_wait_s=fit) if fit else recipe, credentials, _frontend_of(cfg, stand, project_root))
    except (StepFailed, StepTimeout) as exc:
        return {"signed_in": False, "kind": "before_submit", "actor": actor, "detail": _detail(_hide(exc, credentials))}
    landing = await_landing(backend, recipe, hosts, timeout_s)
    if not landing["landed"]:
        return {"signed_in": False, "kind": "not_landed", "actor": actor,
                "detail": _detail(_login_failure_detail(landing, timeout_s, credentials, cfg))}
    record = {"signed_in": True, "actor": actor, "proof": landing["proof"], "at": _now(), "url": landing["url"],
              "elapsed_s": landing["elapsed_s"]}
    if not isinstance(recipe.get("landed"), dict):
        record["weak"] = True       # the weaker proof is said, never shown as the strong one (E6, FR-41)
    if session is not None:
        session.save(signed_in=True, proof=record["proof"], at=record["at"])
    return record


def _session_blocked(result, login, frontend) -> EnvBlocked:
    """The EnvBlocked of a `sign_in` that did not sign in, inside a session call. `before_submit` / `no_recipe`: the recipe does
    not fit the page, the factory's (the old owner). `not_landed`: gate A had proved this sign-in, so the stand changed since -
    owner `environment`, cause `stand` (E2): a stand event is never put on a person (FR-3, FR-19)."""
    stand_side = result.get("kind") == "not_landed"
    return _login_blocked(result.get("detail") or "not proven", login, frontend, "environment" if stand_side else "factory",
                          cause="stand" if stand_side else "")


def _resume(backend, attempt: Attempt, actor_session: ActorSession, hosts, frontend, timeout_s):
    """The first step of a call into a session that already has a page: open the page the last call ended on. A page that is
    not on a stand host (E4) is never opened - the stand's own address is, and the limitation says so. (the steps.jsonl row, or
    None when there was nothing to open)."""
    last = actor_session.last_url()
    if not last:
        return None
    target = last
    if host_key(last) not in hosts:
        if not frontend:
            return None
        target = frontend
        attempt.limitations.append(f"the session's last page ({_safe_url(last) or 'unreadable'}) is not on a stand host: the call "
                                   "began at the stand's address instead")
    line = f"resume session {actor_session.actor} at {_safe_url(target)}"
    try:
        elapsed = backend.goto(target)
        if elapsed > timeout_s:
            raise StepTimeout(elapsed)
    except StepTimeout as exc:
        return attempt.step("ui", line, "timeout", f"took {exc.elapsed_s:g} s, the limit is {timeout_s:g} s")
    except StepFailed as exc:
        return attempt.step("ui", line, "failed", _detail(exc))
    return attempt.step("ui", line, "ok", f"{elapsed:.2f} s")


def _session_attempt(args, case, profile) -> tuple:
    """(attempt name, note) of a `--session` call: the open attempt of this profile (calls of one case share it), else the next -
    `ui` without `--session` always opens a new one. `--attempt` is taken as given."""
    root = case_root(args.task_root, case)
    if args.attempt:
        return choose_attempt(root, args.attempt), ""
    return choose_attempt_for(root, profile)


class _BackendHttp:
    """The `HTTP` client of a `http --session` call: the request goes through the session's own browser context (its cookies),
    never through the factory's login request."""

    def __init__(self, backend):
        self.backend = backend

    def request(self, method, url, headers, body, timeout_s):
        return self.backend.http(method, url, headers, body, timeout_s)


def _new_backend(args, cfg, project_root, passthrough):
    """(backend, None), or (None, exit code) when the harness interpreter ran the call instead; a ValueError (the door to install
    Playwright) inside the harness. The same three branches `run_ui` has."""
    if BACKEND_FACTORY is not None:
        return BACKEND_FACTORY(), None
    try:
        return PlaywrightBackend(), None
    except BrowserUnavailable as exc:
        if args.in_harness:
            raise ValueError(_browser_door(exc))
        return None, _reexec_in_harness(cfg, project_root, passthrough)


def run_session_close(args) -> int:
    """`manual_capture.py session close --task-root T --case C [--attempt aN]`: delete the browser profiles of the attempt
    (their cookies are a credential and must not outlive the case), keep each state.json with the sign-in marked closed, and
    write one line per actor to steps.jsonl. Without `--attempt`: the latest attempt that holds sessions. Nothing to close is a
    refusal that says so (exit 2), not a silent success."""
    cfg, _ = load_config(args.task_root)
    root = case_root(args.task_root, args.case)
    if args.attempt:
        name = _attempt_to_close(root, args.attempt)
    else:
        held = [a for a in attempts_of(root) if (root / a / SESSIONS_DIR).is_dir()]
        if not held:
            raise ValueError(f"case {args.case} holds no session: nothing to close. A session exists after a `ui` or `http` "
                             "call with --session")
        name = held[-1]
    attempt = Attempt(args.task_root, args.case, name, cfg)
    folders = sorted(p for p in (attempt.dir / SESSIONS_DIR).iterdir() if p.is_dir()) if (attempt.dir / SESSIONS_DIR).is_dir() else []
    if not folders:
        raise ValueError(f"attempt {name} of {args.case} holds no session: nothing to close")
    closed, stuck = [], []
    for folder in folders:
        actor = ActorSession(attempt.dir, folder.name, folder=folder)
        actor.actor = str(actor.state().get("actor") or folder.name)
        try:
            shutil.rmtree(actor.profile)
        except FileNotFoundError:
            pass
        except OSError as exc:
            stuck.append(f"{attempt.rel(actor.profile)} ({exc.__class__.__name__})")
            continue
        actor.save(signed_in=False, last_url="", closed_at=_now())
        attempt.step("session", f"session close {actor.actor}", "ok", "browser profile deleted (its cookies are gone)")
        closed.append(actor.actor)
    if stuck:
        raise ValueError("a browser profile could not be deleted: " + ", ".join(stuck) + ". Its cookies are a credential: close "
                         "whatever holds it open and run `session close` again; do not `build` before")
    print(json.dumps({"ok": True, "case": args.case, "attempt": name, "closed": closed}))
    return EXIT_OK


def _attempt_to_close(root: Path, explicit) -> str:
    if attempt_number(explicit) < 0 or not (root / explicit).is_dir():
        raise ValueError(f"--attempt {explicit!r} is not an attempt of this case. Expected one of: "
                         f"{', '.join(attempts_of(root)) or 'none (no capture was made)'}")
    return explicit


def run_ui(args, spec_data, passthrough) -> int:
    cfg, project_root = load_config(args.task_root)
    case_dir_name(args.case)
    steps_path = Path(args.steps_file)
    if not steps_path.is_file():
        raise ValueError(f"--steps-file {args.steps_file!r} does not exist. Expected a text file, one step per line")
    try:
        text = steps_path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"--steps-file {args.steps_file!r} is not UTF-8 text")
    steps = parse_steps(text, spec_data)
    if (hit := secret_pattern_hit(text, cfg)) is not None:
        raise ValueError(f"the steps file matches secret_content_patterns[{hit}] of config.json: steps are saved in "
                         "the record, so a credential never goes in one. To type an account use the step "
                         "`fill-account <selector> <actor> user|secret` (the factory puts the value in); otherwise "
                         "sign in by code and leave the sign-in out of the steps")
    stand = None
    for step in steps:
        if step["word"] == "goto":
            env = environment_of(step["args"][0], cfg, root=project_root)
            stand = stand or env
    # RN1-10: `--session <actor>` keeps the account's browser profile between calls of the case (they join the open attempt)
    session_actor = getattr(args, "session", None)
    session_name = session_note = None
    if session_actor is not None:
        if getattr(args, "actor", None) is not None:
            raise ValueError(SESSION_VS_AS)
        session_name, session_note = _session_attempt(
            args, args.case, capture_profile(cfg, args.task_root, args.case, "ui", getattr(args, "profile", None)))
    timeout_s = timeout_for(stand)
    element_s = element_wait_for(cfg)
    # The recipe and its landing rule are read HERE, before any attempt exists: a malformed rule is a refusal like every
    # other one (no attempt folder, no probe, no browser), and the call's fault (FR-46).
    recipe = login_recipe(cfg, spec_data, "ui")
    landing_rule(recipe)
    if (problem := recipe_rows_problem(recipe)):
        raise ValueError(problem)
    _account_steps_gate(steps, cfg, stand, args.task_root, args.case)
    # EP1-28: the profile is the project's own, chosen BEFORE any attempt folder, browser or probe exists (a refusal is exit 2)
    profile = capture_profile(cfg, args.task_root, args.case, "ui", getattr(args, "profile", None))
    # t-308 F1: a login declared null is never read - the driver's gate (`stand_login_problem`) already says "no
    # problem" for it, so the capture must not refuse on the env file the gate skipped (the forbidden direction).
    if session_actor is not None:
        # a session signs in through `sign_in` (the one function gate A's probe calls too) and only on a sign-in the probe PROVED
        # (E1): the call is refused before anything is opened; steps that sign in by `fill-account` need no proof, and a project
        # that declares no UI login has nothing to prove
        login = None
        # F1 (t-1747): a profile that already holds a sign-in proven by `await_landing` (the agent's own form sign-in of an
        # earlier call) is the same strength of proof as gate A's: it needs no probe row and no second login
        if not any(s["word"] == "fill-account" for s in steps) and not login_declared_none(cfg, "ui")                 and not _profile_signed_in(args, session_name, session_actor):
            if (why := sign_in_refusal(args.task_root, session_actor, recipe)):
                raise ValueError(why)
            login = read_login(cfg, project_root, actor=session_actor, stand=stand, task_root=args.task_root)
    elif any(s["word"] == "fill-account" for s in steps):
        # F1: the steps sign in through the form, so the code signs in NOT - a code login that failed (owner factory) would
        # meet the same recipe in the new attempt and the door "sign in through fill-account" could never be walked
        if getattr(args, "actor", None) is not None:
            raise ValueError("`--as` signs in by code; a steps file with `fill-account` signs in through the form: leave "
                             "`--as` out (the account is named in each `fill-account` step)")
        login = None
    else:
        login = _session_login(cfg, project_root, "ui", args, stand)
    login_step = "login by code" + (f" as {login.label}" if login is not None and login.label else "")
    root = case_root(args.task_root, args.case)
    # One `ui` call is one whole session (pre, action and post in the same page), so without --attempt it is
    # a NEW attempt: a rerun never mixes its captures with an earlier session's. `http` calls of one case, by
    # contrast, share the open attempt (a before-read and an action are two calls).
    known = attempts_of(root)
    name = (session_name if session_actor is not None else
            choose_attempt(root, args.attempt) if args.attempt else f"a{attempt_number(known[-1]) + 1}" if known else "a1")
    factory = BACKEND_FACTORY
    backend = None
    if factory is None:
        try:
            backend = PlaywrightBackend()
        except BrowserUnavailable as exc:
            if args.in_harness:
                raise ValueError(_browser_door(exc))
            return _reexec_in_harness(cfg, project_root, passthrough)
    else:
        backend = factory()
    if session_note:
        print(session_note, file=sys.stderr)       # stderr: stdout stays ONE JSON object (FR-14)
    attempt = Attempt(args.task_root, args.case, name, cfg)

    def session(backend):
        hosts = set(stand_hosts(cfg, root=project_root))
        done, failed, login_block = [], None, None
        backend.open(timeout_s, hosts, recipe.get("local_storage"), element_s)
        if login is not None and recipe:
            import env_probe
            frontend = (env_probe.frontend_of(cfg, str(stand.get("name") or ""), entry=stand, root=project_root)["url"]
                        or stand.get("base_url"))
            try:
                # EP1-31: the factory's own default form is waited for a short time, a project's own recipe for the full
                # element wait - a quick refusal never hits a slow page the project confirmed
                fit = spec_data.get("login", {}).get("ui_fit_wait_s") if "ui" not in _own_login(cfg) else None
                backend.login(dict(recipe, fit_wait_s=fit) if fit else recipe, login, frontend)
            except (StepFailed, StepTimeout) as exc:
                # before the submit: the page never loaded or a sign-in field was not found - the recipe does not
                # fit the page, which is the factory's to fix (Q3, E8)
                detail = _detail(_hide(exc, login))
                login_block = _login_blocked(detail, login, frontend, "factory")
            else:
                landing = await_landing(backend, recipe, hosts, timeout_s)
                if landing["landed"]:
                    detail = (f"landed on {urlsplit(landing['url']).path or '/'} in {landing['elapsed_s']:g} s "
                              f"({landing['proof']})")
                    if not isinstance(recipe.get("landed"), dict):
                        # an override with no `landed` rule: the weaker proof (the field is gone, on a stand URL)
                        # is said, never shown as the strong one (E6, FR-41)
                        detail += "; no landing rule in config, weak proof"
                        print("manual_capture: the login recipe in config has no `landed` rule "
                              "(manual_capture.login.ui.landed): the login is proven only by the sign-in field being "
                              "gone on a stand address (weak proof)", file=sys.stderr)
                    done.append(attempt.step("ui", login_step, "ok", _detail(detail)))
                else:
                    # after the submit: the stand or its test account did not sign in (Q3). No screenshot: the form
                    # may show the account name (E10)
                    detail = _detail(_login_failure_detail(landing, timeout_s, login, cfg))
                    login_block = _login_blocked(detail, login, frontend, "user")
            if login_block is not None:
                failed = {"step": login_step, "outcome": "failed", "detail": detail}
                done.append(attempt.step("ui", login_step, "failed", detail))
        if failed is None:
            account = SessionAccount(login, stand, project_root, args.task_root, landing_rule(recipe)[0])
            account.preload(cfg, [s["args"][1] for s in steps if s["word"] == "fill-account"])
            rows, failed = _run_steps(backend, attempt, steps, timeout_s, cfg, spec_data, element_s, account)
            done.extend(rows)
        return done, failed, login_block

    summary_extra = {}

    def session_run(backend):
        """A `--session` call: the actor's persistent profile, the proven sign-in (reused when the profile holds it), the page
        the last call ended on, then the steps, and the page this call ends on for the next one (RN1-10)."""
        hosts = set(stand_hosts(cfg, root=project_root))
        done, failed, block = [], None, None
        actor_session = ActorSession(attempt.dir, session_actor)
        backend.open(timeout_s, hosts, recipe.get("local_storage"), element_s, profile_dir=actor_session.profile)
        frontend = _frontend_of(cfg, stand, project_root)
        if login is not None:
            result = sign_in(backend, cfg, project_root, session_actor, stand, task_root=args.task_root, session=actor_session,
                             credentials=login, spec_data=spec_data, hosts=hosts, timeout_s=timeout_s)
            if result["signed_in"] and not result.get("reused"):
                detail = f"landed on {urlsplit(result['url']).path or '/'} in {result['elapsed_s']:g} s ({result['proof']})"
                if result.get("weak"):
                    detail += "; no landing rule in config, weak proof"
                done.append(attempt.step("ui", f"login by code as {login.label}", "ok", _detail(detail)))
            elif not result["signed_in"]:
                block = _session_blocked(result, login, frontend)
                line = f"login by code as {login.label}"
                failed = {"step": line, "outcome": "failed", "detail": result["detail"]}
                done.append(attempt.step("ui", line, "failed", result["detail"]))
        if failed is None and (login is None or result.get("reused")):
            row = _resume(backend, attempt, actor_session, hosts, frontend, timeout_s)
            if row is not None:
                done.append(row)
                if row["outcome"] != "ok":
                    failed = {"step": row["step"], "outcome": row["outcome"], "detail": row["detail"]}
        if failed is None:
            account = SessionAccount(login, stand, project_root, args.task_root, landing_rule(recipe)[0])
            account.preload(cfg, [s["args"][1] for s in steps if s["word"] == "fill-account"])
            rows, failed = _run_steps(backend, attempt, steps, timeout_s, cfg, spec_data, element_s, account)
            done.extend(rows)
            if failed is None and any(s["word"] == "fill-account" for s in steps) and not account.window:
                actor_session.prove_after_form(backend, recipe, hosts)
        if block is None:
            actor_session.remember(backend, hosts)
        summary_extra["session"] = {"actor": session_actor, "signed_in": actor_session.signed_in()}
        return done, failed, block

    return _session_cycle(attempt, backend, args, profile, cfg, project_root, stand, "ui",
                          session_run if session_actor is not None else session, summary_extra)


def _session_cycle(attempt: Attempt, backend, args, profile, cfg, project_root, stand, command, session, extra=None) -> int:
    """The part of a `ui` and an `app` call that does not depend on the surface (EP1-41d): the stand's probe at the start, the
    session (`session(backend) -> (rows, failed, block)`, which opens, signs in and runs the steps), the close of the backend in
    `finally`, the probe at the end, the block, the summary. `block` is an EnvBlocked that ended the call (a sign-in that did not
    land; a device that was not ready): told AFTER the end probe, because a stand that cannot be identified is the more basic cause.
    The whole cycle holds the stand's lease (`_hold_stand`, job `manual:<case>:<attempt>`); a stand still held is `stand_busy`, exit 3."""
    try:
        with _hold_stand(cfg, project_root, stand, f"manual:{args.case}:{attempt.name}", attempt.dir):
            return _session_cycle_held(attempt, backend, args, profile, cfg, project_root, stand, command, session, extra)
    except StandHeld as held:
        return held.code


def _session_cycle_held(attempt: Attempt, backend, args, profile, cfg, project_root, stand, command, session, extra=None) -> int:
    before = _count_captures(attempt)
    try:
        stand_probe(attempt, cfg, project_root, profile, "start", command, stand)
    except EnvBlocked as exc:
        return _blocked(attempt, args.case, exc)
    try:
        done, failed, block = session(backend)
        try:
            _store_requests_seen(backend, attempt, cfg)         # t-1765 X3: what the page sent, before the browser closes
        except Exception as exc:  # noqa: BLE001 - a log of the page's requests never costs the call its summary; the gap is said
            attempt.limitations.append(f"the log of the requests this page sent failed ({type(exc).__name__}: {str(exc)[:120]})")
    finally:
        try:
            backend.close()
        except Exception:
            pass
        if getattr(backend, "close_note", ""):       # a device session that stays behind is said, never silent
            attempt.limitations.append(backend.close_note)
    try:
        stand_probe(attempt, cfg, project_root, profile, "end", command, stand)
    except EnvBlocked as exc:
        return _blocked(attempt, args.case, exc)       # the stand not being identified is the more basic cause
    if block is not None:
        return _blocked(attempt, args.case, block)
    print(json.dumps({**_summary(attempt, args.case, done, before, failed, {"profile": profile, "start": "ok", "end": "ok"},
                                 observed=True), **(extra or {})}))
    return EXIT_OK if failed is None else EXIT_FAILED_STEP


def run_app(args, spec_data) -> int:
    """`manual_capture.py app`: the steps of a device surface on the project's device stand (EP1-41d). Every refusal below is the
    call's (exit 2) and comes BEFORE an attempt, a session or a probe exists: no stand, two stands and none named (a surface is never
    guessed), an app id that is empty, `--as` (a device has no sign-in by code), a step the surface lacks, a selector with no listed
    strategy, a secret in the steps. The profile is the project's own (`capture_profile` surface `app`)."""
    import surfaces
    cfg, project_root = load_config(args.task_root)
    case_dir_name(args.case)
    steps_path = Path(args.steps_file)
    if not steps_path.is_file():
        raise ValueError(f"--steps-file {args.steps_file!r} does not exist. Expected a text file, one step per line")
    try:
        text = steps_path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"--steps-file {args.steps_file!r} is not UTF-8 text")
    stand = surfaces.stand_for(cfg, getattr(args, "surface", "") or "")
    row = surfaces.row_of(stand)
    app_id = str((stand.get("app") or {}).get("id") or "").strip() if isinstance(stand.get("app"), dict) else ""
    if not app_id:
        raise ValueError(f"the device stand {stand.get('name')!r} names no application: `app.id` of its environments[] row in "
                         "config.json is empty. Expected the id of the application under test (it is not a secret); run the "
                         "onboarding again or write it in")
    if getattr(args, "actor", None) is not None:
        raise ValueError("`--as` signs in by code, and a device has no sign-in by code. To type an account use the step "
                         "`fill-account <selector> <actor> user|secret` (the factory puts the value in)")
    steps = parse_steps(text, spec_data, APP_WORDS, row.get("selectors"))
    if (hit := secret_pattern_hit(text, cfg)) is not None:
        raise ValueError(f"the steps file matches secret_content_patterns[{hit}] of config.json: steps are saved in the record, so a "
                         "credential never goes in one. To type an account use the step `fill-account <selector> <actor> "
                         "user|secret` (the factory puts the value in)")
    recipe = login_recipe(cfg, spec_data, "app")
    sign_in = str(recipe.get("sign_in_selector") or "")
    if "sign_in_selector" in recipe and (not isinstance(recipe["sign_in_selector"], str)
                                         or _selector_problem(sign_in, row.get("selectors"))):
        raise ValueError("manual_capture.login.app.sign_in_selector in config.json is not a selector. Expected "
                         f"`<strategy>=<value>` naming an element only the sign-in screen has; {_selector_problem(sign_in, row.get('selectors'))}")
    _account_steps_gate(steps, cfg, stand, args.task_root, args.case)
    profile = capture_profile(cfg, args.task_root, args.case, "app", getattr(args, "profile", None))
    root = case_root(args.task_root, args.case)
    known = attempts_of(root)
    name = choose_attempt(root, args.attempt) if args.attempt else f"a{attempt_number(known[-1]) + 1}" if known else "a1"
    backend = (BACKEND_FACTORY or (lambda: AppiumBackend(stand, row, sign_in=sign_in)))()
    attempt = Attempt(args.task_root, args.case, name, cfg)
    attempt.command = "app"
    attempt.entry_limitation = str((spec_data.get("capture_surfaces", {}).get("app") or {}).get("limitation") or "")
    timeout_s, element_s = timeout_for(stand), element_wait_for(cfg)

    def session(backend):
        try:
            backend.open(timeout_s, (), None, element_s)
        except EnvBlocked as exc:
            return [], None, exc
        account = SessionAccount(None, stand, project_root, args.task_root, ["app://sign-in"] if sign_in else [])
        account.preload(cfg, [s["args"][1] for s in steps if s["word"] == "fill-account"])
        rows, failed = _run_steps(backend, attempt, steps, timeout_s, cfg, spec_data, element_s, account)
        return rows, failed, None

    return _session_cycle(attempt, backend, args, profile, cfg, project_root, stand, "app", session)


def jsonl_rows(path) -> list:
    """The parseable object lines of a recorder jsonl file (`steps.jsonl`, `probes.jsonl`); `[]` when it is absent, unreadable
    or empty. Tolerant on purpose: a damaged line is not a row, and it never stops a walk from being read (the recorder is the
    only writer, AR-14). The ONE tolerant reader of these files (AR-13)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _last_step_row(attempt_dir) -> dict:
    """The LAST parseable row of the attempt's steps.jsonl; {} when the file is absent, unreadable, empty or holds no
    JSON object line (non-JSON lines are skipped)."""
    rows = jsonl_rows(Path(attempt_dir) / "steps.jsonl")
    return rows[-1] if rows else {}


def _row_locks_screen_route(row: dict, attempt_dir) -> bool:
    """Whether an env_blocked row keeps the screen route (`fill-account` steps) shut. Only a do_not_retry row of owner
    `user` can; the cause test comes first: `login_unknown` (nothing was sent) never locks, any other cause locks. A row
    with no cause locks only on step evidence of a SENT login: the last steps.jsonl row is a failed `ui` step. The error
    direction is toward NOT locking: an attempt where nothing was sent never closes the door (spec t-1955 E2.1-E2.3)."""
    if row.get("do_not_retry") is not True or row.get("owner") != "user":
        return False
    cause = row.get("cause")
    if cause == LOGIN_UNKNOWN_CAUSE:
        return False
    if cause:
        return True
    last = _last_step_row(attempt_dir)
    return last.get("outcome") == "failed" and last.get("command") == "ui"


def _account_steps_gate(steps, cfg, stand, task_root, case) -> None:
    """The refusals of a step file that signs in by `fill-account`, before any attempt or browser exists (exit 2): an
    actor the call cannot resolve is refused with the doors of `--as` (the line named), and so is a case whose last
    attempt was refused by the account itself (`do_not_retry`, owner `user`): the same page answers again, so the door
    is the runner's `env_blocked[]` line, not another sign-in. An attempt the FACTORY failed (owner `factory`: the code's
    recipe did not fit the page) leaves the door open - that is the one a person-like sign-in by steps is for."""
    mine = [s for s in steps if s["word"] == "fill-account"]
    if not mine:
        return
    for step in mine:
        try:
            resolve_actor(cfg, stand, step["args"][1], task_root)
        except ValueError as exc:
            raise ValueError(f"step `{step['line']}`: {exc}")
    root = case_root(task_root, case)
    known = attempts_of(root)
    if known and attempt_state(root / known[-1]) == "env_blocked":
        row = _env_blocked_row(root / known[-1])
        if _row_locks_screen_route(row, root / known[-1]):
            raise ValueError(f"attempt {known[-1]} of this case is env_blocked with do_not_retry and owner user"
                             + (f" ({str(row.get('probe_line'))[:200]})" if row.get("probe_line") else "")
                             + ": the account or the stand was refused, so signing in through `fill-account` meets the same "
                             "page. Put the case in env_blocked[] with the printed line and halt the block")


def _cover_note(cover, cfg):
    """What stands in place of the covering element's text, or None to keep it. The text is page text like a `read`
    value: it passes the same secret scan, and only the match's index is kept, never the text (the config is here,
    not in the browser)."""
    if not cover:
        return None
    try:
        hit = secret_pattern_hit(cover, cfg)
    except ValueError:
        return "text not kept: secret_content_patterns could not be scanned"
    return None if hit is None else f"text not kept: matches secret_content_patterns[{hit}]"


def _excerpt(backend, mode, limit, cfg, account) -> str:
    """What the page says after a step, for the role: `page_words(mode)` on one line, the session's accounts replaced
    by [redacted], then the secret scan (a match keeps only the pattern's index), then cut at `limit` with `...`.
    ERROR DIRECTION: an unreadable page, a primitive that raises or a pattern that cannot be scanned give less text,
    never a step that fails and never a secret in a file."""
    try:
        words = " ".join(str(backend.page_words(mode) or "").split())
    except Exception:
        return ""
    words = account.hide(words)
    try:
        hit = secret_pattern_hit(words, cfg) if words else None
    except ValueError:
        return "(text not kept: secret_content_patterns could not be scanned)"
    if hit is not None:
        return f"(text not kept: matches secret_content_patterns[{hit}])"
    return words if len(words) <= limit else words[:limit] + "..."


def _observe_shot(backend, attempt: Attempt, step):
    """The screen after a passed step, in `<attempt>/observe/NNN-<word>.png` - NOT registered in captures.jsonl, so
    `build` never carries it into a record. None when it could not be taken."""
    path = attempt.dir / OBSERVE_DIR / f"{step['n']:03d}-{_label(step['word'])}.png"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        backend.screenshot(path)
        return attempt.rel(path) if path.is_file() else None
    except Exception:
        path.unlink(missing_ok=True)
        return None


def _observe(backend, attempt: Attempt, step, outcome, cfg, account) -> dict:
    """{"screenshot", "text"} of the screen after one step. A passed step: its observation PNG (none inside the sign-in
    window) and a short excerpt; any other outcome: the failed step's own screenshot (already in captures.jsonl) and a
    long excerpt. Observing never changes the step's outcome."""
    try:
        passed = outcome["entry"]["outcome"] == "ok"
        shot = (None if account.window else _observe_shot(backend, attempt, step)) if passed else outcome.get("shot")
        return {"screenshot": shot, "text": _excerpt(backend, "short" if passed else "long",
                                                     OBSERVE_OK_CHARS if passed else OBSERVE_FAIL_CHARS, cfg, account)}
    except Exception:
        return {"screenshot": None, "text": ""}


def _run_steps(backend, attempt: Attempt, steps, timeout_s, cfg, spec_data, element_s, account, stop=None) -> tuple:
    """(rows, failed): every step run, in order, until one does not pass. A row is the steps.jsonl entry plus what the
    role sees after it (`screenshot`, `text`) for the first OBSERVE_MAX_STEPS steps; the sign-in window of `account` is
    kept here, after the observation of the step that opened or closed it.
    `stop` (t-1957 N1a, the walk server's call-back; `None` = the `ui` road, exactly as before): `stop(step, row, found, late=False)`
    is called after each step's surprise lines are written, with the surprise rows of THAT step (`found`), and once more with
    `late=True` for the lines that arrive after the last step; a truthy answer ends the loop like a step that did not pass, the
    row's own outcome unchanged (`failed` stays what the outcome says). The call-back keeps what it answered; this loop reads only
    whether to go on."""
    rows, failed = [], None
    watching = hasattr(backend, "event_mark") and hasattr(backend, "events_since")       # the surprise detector (t-1765 X8-2)
    last_step, last_end = None, None
    mark_next = None
    for step in steps:
        mark = (mark_next if mark_next is not None else backend.event_mark()) if watching else None      # the window starts where the last one ended: no event falls between (B-1)
        before = _url_of(backend) if watching else ""
        found = []
        outcome = _run_step(backend, attempt, step, timeout_s, cfg, spec_data, element_s, account)
        row = dict(outcome["entry"])
        found = list(outcome.get("surprises") or [])      # an `http` step writes its own surprise lines (FL-1 B); the stop rule and the answer read them as a screen step's
        if "excerpt" in outcome:      # an `http` step has no screen to observe: its excerpt is the head of the answer it saved
            row["text"] = outcome["excerpt"]
        elif step["n"] <= OBSERVE_MAX_STEPS:
            row.update(_observe(backend, attempt, step, outcome, cfg, account))
            attempt.keep_observation(outcome["entry"], row.get("text"))
        elif step["n"] == OBSERVE_MAX_STEPS + 1:
            attempt.limitations.append(f"observation stopped after {OBSERVE_MAX_STEPS} steps")
        if watching:
            if not attempt.call_surprises and last_step is None:
                attempt.limitations.append(str(_surprise_data(spec_data, "limitation")))
            fresh, last_end = _surprises_after(backend, attempt, step, mark, before, cfg, spec_data, account)
            found = [*found, *fresh]
            last_step, mark_next = step, last_end
        if found:
            attempt.call_surprises.extend(found)
            shown = [_surprise_line(r) for r in found]
            top = int(_surprise_data(spec_data, "max_per_step_lines"))
            row["surprise"] = shown[:top] + ([f"... and {len(shown) - top} more"] if len(shown) > top else [])
        rows.append(row)
        stopped = bool(stop(step, row, found)) if stop is not None else False
        if row["outcome"] != "ok":
            _settle_new_accounts(attempt, account, cfg, row)
            failed = {"step": step["line"], "outcome": row["outcome"], "detail": row["detail"]}
            break
        account.watch(backend)
        _confirm_new_accounts(backend, attempt, account, step)      # the window keeps its own job; the sign-up is confirmed by a path change (N1c E1c.6)
        if stopped:
            break
    if watching and failed is None and last_step is not None:
        _pump(backend, "goto", time.perf_counter(), timeout_s, cfg, spec_data)         # what the last step caused after it was left
        late, _ = _surprises_after(backend, attempt, last_step, last_end, "", cfg, spec_data, account, late=True)
        attempt.call_surprises.extend(late)
        if late:
            for row in reversed(rows):
                if row.get("step") == last_step["line"]:
                    row["surprise"] = [*(row.get("surprise") or []), *[_surprise_line(r) for r in late]]
                    break
            if stop is not None:
                stop(last_step, rows[-1], late, late=True)
    if attempt.call_surprises:         # the evidence a role (and the analyst) quotes: one file per call, the same lines as the summary
        text = "\n".join(_surprise_line(r) for r in attempt.call_surprises) + "\n"
        attempt.store_text("surprises", text.encode("utf-8"), "log", "supporting", ["surprises"], _cmd(attempt), ".txt")
    _store_open_failures(backend, attempt, cfg, account)
    return rows, failed


class SessionAccount:
    """What the step loop of one `ui` call knows of accounts: every credential the session has used (the sign-in by code
    and each `fill-account`), so every text the call keeps passes `hide`; and the sign-in WINDOW - from the first
    `fill-account` until the URL holds none of the landing rule's `url_not` fragments - in which the screen is never saved
    (the form may show the account: E10). With no `url_not` the window never closes (error direction: less screen)."""

    def __init__(self, login=None, stand=None, project_root=None, task_root=None, url_not=()):
        self.credentials = [login] if login is not None else []
        self.stand, self.project_root, self.task_root = stand, project_root, task_root
        self.url_not, self.window = list(url_not), False
        self._found = {}

    def preload(self, cfg, actors) -> None:
        """Every account the steps will type is hidden from the first step on (a page may show it before the form is
        reached). An actor that cannot be read yet is skipped: its own `fill-account` step is refused, by name, when it runs."""
        for actor in dict.fromkeys(actors):
            try:
                self.credentials_of(cfg, actor)
            except ValueError:
                continue

    def hide(self, text) -> str:
        out = str(text or "")
        for found in self.credentials:
            out = _hide(out, found)
        return out

    def credentials_of(self, cfg, actor):
        """The account `actor` names, through the ONE resolver (`read_login` over `resolve_actor`)."""
        if actor not in self._found:
            self._found[actor] = read_login(cfg, self.project_root, actor=actor, stand=self.stand, task_root=self.task_root)
            self.credentials.append(self._found[actor])
        return self._found[actor]

    def watch(self, backend) -> None:
        """Close the window when the page has left the sign-in addresses; a URL that cannot be read keeps it open."""
        if not self.window or not self.url_not:
            return
        try:
            url = str(backend.current_url() or "")
        except Exception:
            return
        if url and not any(piece in url for piece in self.url_not):
            self.window = False


def _step_number(spec_data, word, key) -> int:
    """A whole number >= 0 of a step's row in the data file (the caller's spec data, else the package's own)."""
    row = (spec_data.get("steps") or {}).get(word) or (spec().get("steps") or {}).get(word) or {}
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"manual-capture-steps.json: steps.{word}.{key} is not a whole number >= 0 ({value!r}): the factory's "
                         "list of capture steps is damaged in this install. This is a factory defect: record it as a finding")
    return value


def _manual_number(cfg, key) -> int:
    """`manual_capture.<key>` of the project's config (a whole number >= 0), else MANUAL_DEFAULTS (AR-3: a default for every key, the
    template of config.json carries the same numbers; a value that is not such a number is the default - the project's typo never stops
    a capture)."""
    own = cfg.get("manual_capture") if isinstance(cfg, dict) and isinstance(cfg.get("manual_capture"), dict) else {}
    value = own.get(key)
    return MANUAL_DEFAULTS[key] if isinstance(value, bool) or not isinstance(value, int) or value < 0 else value


def _surprise_data(spec_data, key):
    """`surprise.<key>` of the data file (the caller's spec data first, else the package's own): the closed lists and limits of the
    detector are data (AR-1); a key the file lacks is a damaged install and fails loudly (KeyError), as `spec()['steps']` does."""
    block = spec_data.get("surprise") if key in (spec_data.get("surprise") or {}) else spec()["surprise"]
    return block[key]


def _joined(detail, note) -> str:
    return "; ".join(x for x in (detail, note) if x)


def _pump(backend, word, started, timeout_s, cfg, spec_data, waited=False) -> str:
    """After a step that acts or types: let the requests it caused arrive BEFORE the next step starts (the sync API hands events over only
    inside its own calls), by `backend.settle` - `settle_ms`, then the network idle, held to the step's remaining limit and to
    `surprise.settle_idle_max_ms`. `waited`: the step has already waited `settle_ms` itself. Returns "" or `idle: not reached` for the step
    line. A backend with no `settle`, a word that neither acts nor types, or a pump that raises, change nothing: the step is never failed
    by its own wait (P1)."""
    if word not in [*_surprise_data(spec_data, "action_steps"), *_surprise_data(spec_data, "input_steps")]:
        return ""
    settle = getattr(backend, "settle", None)
    if settle is None:
        return ""
    try:
        idle = settle(0 if waited else _manual_number(cfg, "settle_ms"), int(_surprise_data(spec_data, "settle_idle_max_ms")),
                      timeout_s - (time.perf_counter() - started))
    except Exception:  # noqa: BLE001
        return ""
    return "idle: not reached" if idle is False else ""


def _look_limit(cfg, spec_data) -> int:
    """The most bytes a `look` file keeps: `steps.look.max_bytes`, and no more than the role's own whole-read limit leaves (`read.max_bytes`
    of the config, read by its one reader `guard_pre_tool.big_read_cap`, less 1024 for the file's first lines); a limit of 0 or less is
    'the guard is off'."""
    top = _step_number(spec_data, "look", "max_bytes")
    try:
        import guard_pre_tool
        cap = int(guard_pre_tool.big_read_cap(cfg))
    except Exception:  # noqa: BLE001
        return top
    return top if cap <= 0 else max(1, min(top, cap - 1024))


def _run_look(backend, attempt: Attempt, step, timeout_s, cfg, spec_data, account) -> dict:
    """`look [<selector>]` (t-1765 X8): what the page shows, stored as a state file the role may cite. The code reads and stores; the role
    judges what it sees (FR-47). Refused inside the sign-in window (the tree holds the form), on a device with a selector, and when the
    text matches a secret pattern or cannot be scanned. Nothing read: the step stays `ok` and says so, with a limitation (P1)."""
    line, args = step["line"], step["args"]
    selector = args[0] if args else None
    on_device = _cmd(attempt) == "app"
    if on_device and selector is not None:
        return attempt.step(_cmd(attempt), line, "refused", "a device has no page to narrow by a selector: repeat the step as `look` "
                            "with no argument (it stores the screen's whole element tree)")
    if account.window:
        return _window_refusal(attempt, line, account, "a look")["entry"]
    limit = _look_limit(cfg, spec_data)
    short_lines, short_chars = _step_number(spec_data, "look", "short_lines"), _step_number(spec_data, "look", "short_chars")
    label = _label(selector or "page")

    def says(kept, made):
        lines = kept.splitlines()
        said = f"look: {len(lines)} lines, {len(kept.encode('utf-8'))} bytes -> {made['path']}\n" + "\n".join(lines[:short_lines])
        return said if len(said) <= short_chars else said[:short_chars] + "..."
    if on_device:
        text, took = backend.source()
        if took > timeout_s:
            raise StepTimeout(took)
        return _store_device_text(attempt, step, account, cfg, "state", "look", text, ".xml", max_bytes=limit,
                                  cut_note="[cut: {k} more lines not stored]", says=says)
    looker = getattr(backend, "look", None)
    if looker is None:
        raise StepFailed("this capture backend cannot look at a page", by="the factory")
    text, form, why, took = looker(selector)
    if took > timeout_s:
        raise StepTimeout(took)
    if text is None:
        said = f"nothing read: {_first_line(why, 'the page could not be read')}"
        attempt.limitations.append(f"look {selector or 'page'} read nothing ({_first_line(why, 'the page could not be read')}): "
                                   "the page was not seen by this step")
        return attempt.step(_cmd(attempt), line, "ok", _detail(account.hide(said)))
    if form == "aria" and not str(text).strip():
        text = "the page has no accessible content"
    head = "form: aria\n" if form == "aria" else f"form: text ({_first_line(why, 'the accessibility tree could not be read')})\n"
    return _store_device_text(attempt, step, account, cfg, "state", label, str(text).rstrip("\n") + "\n", ".txt", max_bytes=limit,
                              cut_note="[cut: {k} more lines not stored; look <selector> narrows it]", head=head, says=says)


def _run_watch(backend, attempt: Attempt, step, cfg, spec_data, account) -> dict:
    """`watch <selector> [<label>]`: from now on every step reads the element's text (the detector of X8-2 compares it). The reading now
    is the baseline. At most `steps.watch.max_watched` different labels per call; a repeat of a label replaces its element."""
    line, args = step["line"], step["args"]
    selector = args[0]
    label = args[1] if len(args) == 2 else selector
    top = _step_number(spec_data, "watch", "max_watched")
    if label not in attempt.watches and len(attempt.watches) >= top:
        return attempt.step(_cmd(attempt), line, "refused", f"{len(attempt.watches)} elements are already watched in this call and at most "
                            f"{top} can be: watch the ones that matter, or repeat a label to point it at another element "
                            f"(watched: {', '.join(attempt.watches)})")
    reader = getattr(backend, "watch_text", None)
    if reader is None:
        raise StepFailed("this capture backend cannot read an element's text", by="the factory")
    text = str(reader(selector))
    attempt.watches[label] = {"selector": selector, "last": text}
    return attempt.step(_cmd(attempt), line, "ok", _detail(_kept_text(f'watching {label}: "{text}"', cfg, account)))


def _fill_detail(text, rows, settle_ms, secret) -> str:
    """The step line of a human `fill`: that the field was cleared (and what it still held), what was typed and what the field holds
    after. `rows[0]` is the clearing. A secret-looking text is told by its length only."""
    cleared = rows[0]
    prefix = "cleared" + (f' (it still held "{cleared["value"]}")' if cleared["value"] not in ("", GONE) else "")
    if secret:
        chars = rows[1:-1]
        return f"{prefix}; typed {len(chars)} of {len(text)} characters; value not shown (it looks like a secret)"
    return f"{prefix}; " + _input_detail("type", ["", text], rows[1:], settle_ms)


def _run_fill(backend, attempt: Attempt, step, timeout_s, cfg, spec_data, account, lookup, started) -> dict:
    """`fill [--whole] <selector> <text>` (t-1765 X8): the field ends holding the text, typed as a person types it. The text is scanned for
    secrets ONCE, before any key (a hit keys it all the same and stores no log - the fill before X8 never refused); a text that would take
    longer than the step limit at `manual_capture.type_delay_ms` is refused BEFORE the first key, with the door `fill --whole`; the field is
    emptied first (select all, delete) so what it ends with is the given text whatever it held; an empty text only empties it. A field that
    cannot be keyed (the data's `whole_types` / `whole_tags`) and `--whole` set the whole value at once and the line says `input: whole`.
    A backend with no `clear_field` (a device, an older fake) keeps the plain `backend.fill`."""
    line, args = step["line"], step["args"]
    asked = args[0] == _whole_flag(spec_data)
    selector, text = (args[1], args[2]) if asked else (args[0], args[1])
    human = all(hasattr(backend, name) for name in ("clear_field", "field_traits", "type_chars"))
    if not human:
        elapsed = lookup(backend.fill(selector, text))
        idle = _pump(backend, "fill", started, timeout_s, cfg, spec_data)
        return {"entry": attempt.step(_cmd(attempt), line, "ok", _joined("input: whole (this backend sets a field's value at once)"
                                                                         if asked else "", idle)), "shot": None}
    try:
        hit = secret_pattern_hit(text, cfg)
        unscanned = False
    except ValueError:
        hit, unscanned = None, True
    delay, settle = _manual_number(cfg, "type_delay_ms"), _manual_number(cfg, "settle_ms")
    if not asked and len(text) * delay > timeout_s * 1000:
        return {"entry": attempt.step(_cmd(attempt), line, "refused",
                                      f"typing {len(text)} characters at {delay} ms each takes {len(text) * delay / 1000:g} s, over the step "
                                      f"limit of {timeout_s:g} s: nothing was typed. Use `fill {_whole_flag(spec_data)} {selector} <text>` "
                                      "(it sets the whole value at once) or a shorter text"), "shot": None}
    why = _whole_flag(spec_data) if asked else ""
    if not why:
        traits, took = backend.field_traits(selector)
        lookup(took)
        if traits.get("type") in _step_list(spec_data, "whole_types"):
            why = f"type={traits['type']}"
        elif traits.get("tag") in _step_list(spec_data, "whole_tags"):
            why = f"<{traits['tag']}>"
    if why:
        elapsed = lookup(backend.fill(selector, text))
        if elapsed > timeout_s:
            raise StepTimeout(elapsed)
        return {"entry": attempt.step(_cmd(attempt), line, "ok", _joined(f"input: whole ({why})", _pump(backend, "fill", started, timeout_s,
                                                                                                          cfg, spec_data))), "shot": None}
    cleared, took_clear, focus_clear = backend.clear_field(selector)
    lookup(focus_clear)
    rows, took, focus_s = backend.type_chars(selector, text, delay, settle)
    lookup(focus_s)
    rows = [cleared, *rows]
    log = account.hide("\n".join(_input_line(r) for r in rows))
    try:
        log_hit = secret_pattern_hit(log, cfg)
    except ValueError:
        log_hit, unscanned = None, True
    if hit is not None or log_hit is not None or unscanned:
        attempt.limitations.append(
            f"the log of `fill {selector}` was not stored: " + ("a secret_content_patterns entry could not be scanned" if unscanned else
            f"the text matches secret_content_patterns[{hit if hit is not None else log_hit}]") + " (the field was filled all the same)")
    else:
        stored, truncated = cut_body(log.encode("utf-8"))
        kept, _ = body_text(stored, truncated)
        attempt.store_text(f"fill-{selector}", kept.encode("utf-8"), "log", "supporting", [f"fill {selector}"], "ui", ".txt",
                           _limit_words("read") if truncated else None)
    if took_clear + took > timeout_s:
        raise StepTimeout(took_clear + took)
    secret = hit is not None or log_hit is not None or unscanned
    attempt.last_input = {"selector": selector, "text": text, "rows": rows, "secret": secret, "cleared": True}
    idle = _pump(backend, "fill", started, timeout_s, cfg, spec_data, waited=True)
    return {"entry": attempt.step(_cmd(attempt), line, "ok", _joined(_detail(account.hide(_fill_detail(text, rows, settle, secret))), idle)),
            "shot": None}


def _url_of(backend) -> str:
    try:
        return str(backend.current_url() or "")
    except Exception:  # noqa: BLE001
        return ""


def _path_of(url) -> str:
    return urlsplit(str(url or "")).path or "/"


def _surprise_line(row) -> str:
    """The ONE form of a `surprise` in the summary and in `NNN-surprises.txt`: `surprise: <id> step <n> (<word>) <kind>: <fact>`."""
    return f"surprise: {row['id']} step {row['step']} ({row['word']}) {row['kind']}: {row['fact']}"


def _span(numbers) -> str:
    """[2, 3, 4, 7] -> `2-4, 7`."""
    out, run = [], []
    for n in sorted(set(numbers)):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}")
        run = [n]
    if run:
        out.append(str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}")
    return ", ".join(out)


def _surprise_rows(attempt_dir) -> tuple:
    """`(rows, torn)` of `<attempt_dir>/surprises.jsonl`: the ONE tolerant reader of the file (AR-13) - `Attempt.surprise`, `_detection_of`
    and `manual_evidence.surprises_of` all ask it. A line that is not a JSON object (a call killed mid-append) is skipped and counted in
    `torn`; it never raises for content (the OSError of an unreadable file is the caller's). `[]` and 0 for no file."""
    path = Path(attempt_dir) / "surprises.jsonl"
    rows, torn = [], 0
    if not path.is_file():
        return rows, torn
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            torn += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            torn += 1
    return rows, torn


def _detection_of(attempt_dir) -> str:
    """How much of the attempt the detector WATCHED, from the `detector` lines of `surprises.jsonl` (never from the surprises): `on` -
    every step of the attempt has a line and every listener was alive; `partial: <kind> dead at steps a-b; steps c-d not observed`;
    an unreadable line (`<n> unreadable line(s)`) makes it `partial`; `absent: <why>` - no detector line at all (no file, an empty file, a backend that does not log the page). `absent` and `partial`
    are never read as 'no surprises' (AR-28). The sign-in by code is the factory's own step and is not a step to observe."""
    rows, torn = _surprise_rows(attempt_dir)
    seen = [r for r in rows if r.get("line") == "detector" and isinstance(r.get("step"), int)]
    if not seen:
        return ("absent: no detector line was written for this attempt (the backend does not log the page's events, or nothing ran)"
                + (f"; {torn} unreadable line(s) in surprises.jsonl" if torn else ""))
    observed = {r["step"] for r in seen}
    dead: dict = {}
    for r in seen:
        if r.get("listeners") != "ok":
            for kind in str(r["listeners"]).split(":", 1)[-1].split(","):
                dead.setdefault(kind, []).append(r["step"])
    path = Path(attempt_dir) / "steps.jsonl"
    steps = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []
    missing = [i for i, s in enumerate(steps, 1) if i not in observed and not str(s.get("step", "")).startswith("login by code")]
    parts = [f"{kind} dead at steps {_span(ns)}" for kind, ns in dead.items()] + ([f"steps {_span(missing)} not observed"] if missing else []) \
        + ([f"{torn} unreadable line(s) in surprises.jsonl"] if torn else [])
    return "on" if not parts else "partial: " + "; ".join(parts)


def _candidates(backend, attempt, step, events, before, after, spec_data) -> list:
    """[(kind, subject, fact, count, status)] of one step (`status`: the answer's number on a `status` line, else None): what the page did, as plain facts. On a step that ACTS (goto, click, drag) a request or
    a change of address is the action's own and goes to the step line; errors are reported on any step. The code does not say whether a
    fact is a defect (FR-47): the role reads it, the analyst judges it."""
    word, args = step["word"], step["args"]
    acts = word in _surprise_data(spec_data, "action_steps")
    out, answered = [], {e["rid"]: e.get("status") for e in events if e["kind"] == "response"}
    broken, numbers = set(), {}       # `numbers`: (kind, subject, fact) of a `status` line -> the answer's number (t-1957 N1a)
    for e in events:
        who = f"{e.get('method', 'GET')} {_path_of(e.get('url'))}"
        if e["kind"] == "response" and not e["ours"] and int(e.get("status") or 0) >= 400:
            broken.add(e["url"])
            out.append(("status", f"{who} -> {e['status']}", f"{who} -> {e['status']}", 1))
            numbers[("status", f"{who} -> {e['status']}", f"{who} -> {e['status']}")] = int(e["status"])
        elif e["kind"] == "failed" and not e["ours"]:
            broken.add(e["url"])
            out.append(("failed", who, f"{who} failed: {e.get('failure') or 'no reason given'}", 1))
    for e in events:
        if e["kind"] in ("console", "pageerror"):
            if e["kind"] == "console" and str(e["text"]).startswith("Failed to load resource") and e.get("location") in broken:
                continue                                  # the browser's own echo of a status/failed line of this step
            out.append(("console", e["text"], f"{'pageerror' if e['kind'] == 'pageerror' else 'console'}: {e['text']}", 1))
    groups: dict = {}
    for e in events:
        if e["kind"] == "request":
            groups.setdefault((e["method"], _path_of(e["url"])), []).append(e)
    for (method, path), found in groups.items():
        if acts:
            if method != "GET" and len(found) > 1:
                out.append(("request", f"{method} {path}", f"{method} {path} sent {len(found)} times", 1))
            continue
        status = answered.get(found[0]["rid"])
        said = f"{method} {path} -> {status}" if status is not None else f"{method} {path} (no answer yet)"
        if found[0].get("char"):
            said += f" after character {found[0]['char'][0]} of {found[0]['char'][1]}"
        out.append(("request", f"{method} {path}", said, len(found)))
    if word == "goto" and after and _safe_url(after) != _safe_url(args[0]):
        out.append(("url", f"{_path_of(args[0])} -> {_path_of(after)}", f"goto {_path_of(args[0])} landed on {_path_of(after)}", 1))
    elif not acts and before and after and _safe_url(before) != _safe_url(after):
        out.append(("url", f"{_path_of(before)} -> {_path_of(after)}", f"url changed {_path_of(before)} -> {_path_of(after)}", 1))
    typed, attempt.last_input = attempt.last_input, None
    if typed and word in _surprise_data(spec_data, "input_steps"):
        said = _field_fact(typed)
        if said:
            out.append(("field", typed["selector"], said, 1))
    reader = getattr(backend, "watch_text", None)
    for label, watched in list(attempt.watches.items()):
        if reader is None:
            break
        now = str(reader(watched["selector"]))
        if now != watched["last"]:
            if not acts:
                out.append(("text", label, f'watch {label}: "{watched["last"]}" -> "{now}"', 1))
            watched["last"] = now
    hosts: dict = {}
    for e in events:
        if e["kind"] == "blocked":
            hosts[urlsplit(e["url"]).hostname or e["url"]] = hosts.get(urlsplit(e["url"]).hostname or e["url"], 0) + 1
    for host, count in hosts.items():
        if host not in attempt.blocked_seen:
            attempt.blocked_seen.add(host)
            out.append(("blocked_host", host, f"requests to {host} blocked (not a stand host): {count}", 1))
    merged: dict = {}                                   # one line per (kind, subject, fact) of the step, `xN` for a repeat
    for kind, subject, fact, count in out:
        merged[(kind, subject, fact)] = merged.get((kind, subject, fact), 0) + count
    return [(kind, subject, fact, count, numbers.get((kind, subject, fact))) for (kind, subject, fact), count in merged.items()]


def _field_fact(typed) -> str:
    """'' or the one `field` fact of a keyed step: the first reading that is not the typed prefix, the settled value, a lost focus.
    A `fill` cleared the field first (equality); a `type` appends to what was there (the value must END with the prefix)."""
    text, rows = typed["text"], [r for r in typed["rows"] if r["n"] != "cleared"]
    same = (lambda value, want: value == want) if typed.get("cleared") else (lambda value, want: str(value).endswith(want))
    parts = [typed["lost_before"]] if typed.get("lost_before") else []
    for r in rows:
        want = text if r["n"] in ("settled", "stopped") else text[:r["n"]]
        if not same(r["value"], want):
            when = "after settling" if r["n"] == "settled" else f"after character {r['n']}"
            parts.append(f"{when} the field shows \"{r['value']}\" (typed \"{want}\")" if not typed.get("secret")
                         else f"{when} the field does not hold what was typed (values not shown)")
            break
    lost = next((r["n"] for r in rows if isinstance(r["n"], int) and not r["focus"]), None)
    if lost is not None:
        parts.append(f"focus lost after character {lost - 1}" if lost > 1 else "no focus already at the reading after character 1")
    return "; ".join(parts)


def _kept_text(text, cfg, account) -> str:
    """A text the call keeps, as the file may hold it: through `account.hide` and the secret scan (a hit keeps only the pattern's
    index). The ONE place of these words for the surprise facts, the action note and the watch baseline (D-7, B-2)."""
    text = account.hide(text)
    try:
        hit = secret_pattern_hit(text, cfg)
    except ValueError:
        return "not kept: secret_content_patterns could not be scanned"
    return text if hit is None else f"not kept: matches secret_content_patterns[{hit}]"


def _surprises_after(backend, attempt, step, mark, before, cfg, spec_data, account, late=False) -> tuple:
    """`(lines, end)`: the surprise lines of one step, written to `surprises.jsonl` (every one),
    and the detector line that says the step was watched. The window is [`mark`, the end of the step's observation]; `end` is the
    index it consumed, and the next step's window starts there, so an event handed over while the detector itself reads the page
    (`watch`) falls into a window all the same. Facts pass `account.hide` and the secret scan like every text the call keeps.
    Nothing here refuses, stops or judges (P1, AR-18): a failure of the detector's own code is a dead listener `detector`."""
    try:
        events, dead = backend.events_since(mark), list(backend.dead_listeners())
    except Exception:  # noqa: BLE001
        events, dead = [], ["events"]
    end = (mark or 0) + len(events)
    kinds, word, step_no = _surprise_data(spec_data, "kinds"), step["word"], attempt.step_number()
    written = []
    try:
        for kind, subject, fact, count, number in _candidates(backend, attempt, step, events, before, _url_of(backend), spec_data):
            if late and kind == "url":
                continue                                       # where the last step landed was told on the step itself
            text = _kept_text(fact + (f" x{count}" if count > 1 else "") + (" (after the last step)" if late else ""), cfg, account)
            written.append(attempt.surprise(step_no, word, kind, text, status=number))
    except Exception:  # noqa: BLE001
        dead = [*dead, "detector"]
    if not late:
        attempt.detector(step_no, dead, kinds)
    return written, end


def _action_note(backend, mark, before, step, cfg, account) -> str:
    """The step line of a step that ACTS: the requests it caused and the address it moved to (its own effects, not surprises)."""
    if mark is None or step["word"] not in _surprise_data({}, "action_steps"):
        return ""
    try:
        events = backend.events_since(mark)
    except Exception:  # noqa: BLE001
        return ""
    answered = {e["rid"]: e.get("status") for e in events if e["kind"] == "response"}
    seen = [_kept_text(f"{e['method']} {_path_of(e['url'])}" + (f" -> {answered[e['rid']]}" if e["rid"] in answered else ""), cfg, account)
            for e in events if e["kind"] == "request"]
    parts = []
    if seen:
        parts.append("requests: " + ", ".join(seen[:5]) + (f" and {len(seen) - 5} more" if len(seen) > 5 else ""))
    after = _url_of(backend)
    if step["word"] != "goto" and before and after and _safe_url(before) != _safe_url(after):
        parts.append(_kept_text(f"url: {_path_of(before)} -> {_path_of(after)}", cfg, account))
    return "; ".join(parts)


def _step_list(spec_data, key) -> list:
    """`steps.fill.<key>` of the data (a list of words), the caller's spec data first."""
    for source in (spec_data, spec()):
        value = ((source.get("steps") or {}).get("fill") or {}).get(key)
        if isinstance(value, list):
            return [str(v) for v in value]
    return []


def _input_line(row) -> str:
    """One line of a keyboard step's log: `<n>\\t<value>\\tfocus=yes|no` (+ `\\tfocused_before=yes|no`); the value on one line."""
    flat = " ".join(str(row["value"]).replace("\t", " ").splitlines())
    line = f"{row['n']}\t{flat}\tfocus={'yes' if row['focus'] else 'no'}"
    if "focused_before" in row:
        line += f"\tfocused_before={'yes' if row['focused_before'] else 'no'}"
    return line


def _input_detail(word, args, rows, settle_ms) -> str:
    """The step line of `type` / `press` / `paste`: what was done and what the field held. A lost focus is told, not judged:
    the step stays `ok` so the post-action screenshot of the defect can still be taken (P1, FR-47)."""
    last = rows[-1]
    if word != "type":
        return (f'{"pressed " + args[1] if word == "press" else "pasted"}; value "{last["value"]}"; '
                f'focus={"yes" if last["focus"] else "no"}; focused before={"yes" if last["focused_before"] else "no"}')
    chars = rows[:-1]
    lost = next((r["n"] for r in chars if not r["focus"]), None)        # the first character typed with no focus on the field
    said = f'typed {len(chars)} of {len(args[1])}; value "{last["value"]}" after {settle_ms} ms'
    if chars and chars[-1]["value"] != last["value"]:
        said += f' (it was "{chars[-1]["value"]}" at the last character)'
    if lost is not None:
        return said + (f"; focus lost after character {lost - 1}" if lost > 1 else "; no focus already at the reading after character 1")
    return said + ("" if last["focus"] else "; focus lost after the wait")


def _continues_field(backend, prior, selector) -> bool:
    """Does a `type` / `press` / `paste` on `selector` go on with the field the step before typed in (`prior`)? The same spelling does; a
    different one only when the backend says both resolve to one field (`same_field`: the page decides, no list of spellings here).
    A doubt - no `same_field`, an error, any answer but True - is a new field, never a continuation (TR4-9)."""
    if not prior:
        return False
    if prior == selector:
        return True
    ask = getattr(backend, "same_field", None)
    if not callable(ask):
        return False
    try:
        return ask(prior, selector) is True
    except Exception:  # noqa: BLE001 - a backend that cannot tell is a doubt, not a stop
        return False


def _run_input(backend, attempt: Attempt, step, timeout_s, cfg, spec_data, account, lookup, started=None) -> dict:
    """`type` / `press` / `paste`: the backend does the keys, code stores one log line per character (or per key) and names
    the result. The element lookup limit applies to the FOCUS only (a long text must not fail as 'element not found'); the
    whole step is held to `timeout_s`."""
    word, args, line = step["word"], step["args"], step["line"]
    settle = 0
    # the step before typed in this very field (a `type`): this one - `type`, `press` or `paste` - goes on, no new focus (TR1-1, TR1-2).
    # ONE rule for the three; a backend gets `continued=True` only then (an older backend or fake keeps its signature).
    continued = _continues_field(backend, attempt.type_prior, args[0])
    more = {"continued": True} if continued else {}
    if word == "type":
        delay = int(args[2]) if len(args) == 3 else _step_number(spec_data, "type", "default_delay_ms")
        settle = _step_number(spec_data, "type", "settle_ms")
        rows, took, focus_s = backend.type_chars(args[0], args[1], delay, settle, **more)
        attempt.type_chain = args[0]
    elif word == "press":
        row, took, focus_s = backend.press_key(args[0], args[1], **more)
        rows = [row]
    else:
        row, took, focus_s = backend.paste_text(args[0], args[1], **more)
        rows = [row]
    lost_before = getattr(backend, "focus_lost_before", None) if continued else None
    lookup(focus_s)
    text = account.hide("\n".join(_input_line(r) for r in rows))
    hit = secret_pattern_hit(text, cfg)
    fact = f"focus lost before the call: keys went to {lost_before}" if lost_before else ""       # ONE text, three readers
    if word == "type":
        attempt.last_input = {"selector": args[0], "text": args[1], "rows": rows, "secret": hit is not None, "cleared": False,
                              "lost_before": fact}
    elif lost_before:       # a `press` / `paste` that went on and found no focus: the same fact for the detector, no rows to compare
        attempt.last_input = {"selector": args[0], "text": "", "rows": [], "secret": False, "cleared": False, "lost_before": fact}
    if hit is not None:
        return {"entry": attempt.step(_cmd(attempt), line, "refused",
                                      f"the value read back matches secret_content_patterns[{hit}]: nothing was stored; "
                                      "type something narrower"), "shot": None}
    stored, truncated = cut_body(text.encode("utf-8"))
    kept, _ = body_text(stored, truncated)
    attempt.store_text(f"{word}-{args[0]}", kept.encode("utf-8"), "log", "supporting", [f"{word} {args[0]}"], "ui", ".txt",
                       _limit_words("read") if truncated else None)
    if took > timeout_s:       # after the rows are kept: the lines read before the stop are the evidence of the defect
        raise StepTimeout(took)
    if lost_before:         # the keys went elsewhere: the step is not ok (a fact, no pass is set over it); the rows above are its evidence
        raise StepFailed(fact + "; a `click` on the field is a person's new click")
    idle = _pump(backend, word, time.perf_counter() if started is None else started, timeout_s, cfg, spec_data, waited=settle > 0)
    return {"entry": attempt.step(_cmd(attempt), line, "ok", _joined(_detail(account.hide(_input_detail(word, args, rows, settle))), idle)),
            "shot": None}


def _drained(backend):
    """{glob: record} of the page's failing routes; {} for a backend with none; None when it cannot be read."""
    drain = getattr(backend, "drain_failures", None)
    if drain is None:
        return {}
    try:
        return dict(drain())
    except Exception:
        return None


def _store_failure(attempt: Attempt, cfg, account, glob, record) -> None:
    """The log of what one `fail_request` caught: the pattern, the failure, the count and the first `max_logged` request lines
    (`METHOD url`, no query; a line that matches a secret pattern is counted, not kept). A record that caught nothing is a
    limitation of the attempt and a name in the summary's `failures_without_hits`."""
    shown, withheld = [], 0
    for row in record["rows"]:
        line = account.hide(f"{row['method']} {_safe_url(row['url'])}")
        try:
            hit = secret_pattern_hit(line, cfg)
        except ValueError:
            hit = -1                                # a pattern that cannot be scanned keeps no line (less text, never a secret)
        if hit is None:
            shown.append(line)
        else:
            withheld += 1
    lines = [account.hide(f"pattern: {glob}"), f"failure: {record['how']}", f"requests failed: {record['hits']}", *shown]
    if record["hits"] > len(record["rows"]):
        lines.append(f"... and {record['hits'] - len(record['rows'])} more")
    if withheld:
        lines.append(f"{withheld} request line(s) not stored: they match secret_content_patterns")
    idle = record["hits"] == 0
    attempt.store_text(f"fail-request-{glob}", "\n".join(lines).encode("utf-8"), "log", "supporting",
                       [f"fail_request {glob}"], "ui", ".txt",
                       spec()["capture_words"]["failure_idle"].format(glob=glob) if idle else None)
    if idle:
        attempt.failures_without_hits.append(glob)


def _store_open_failures(backend, attempt: Attempt, cfg, account) -> None:
    """End of the session: the log of every failure that was never restored."""
    for glob, record in (_drained(backend) or {}).items():
        if record["active"]:
            _store_failure(attempt, cfg, account, glob, record)


def _store_requests_seen(backend, attempt: Attempt, cfg, account=None, since=None) -> None:
    """End of a `ui` session (t-1765 X3): the log of the requests the page sent to a stand host, as `requests-seen.txt`: `METHOD address`
    (no query), one line per distinct pair (`xN` for a repeat), the first `requests_seen.max_logged` lines, then `... and K more`; a line
    that matches a secret pattern is counted, not kept (as `_store_failure`). No request: the file says `requests seen: 0` and the
    attempt carries the `requests_none` limitation (the log reads the browser only, so zero is not 'none sent'). A backend that says it
    cannot list requests (`drain_requests()` answers None: a device) writes no file and says so in the attempt's limitations (AR-28);
    a backend with no `drain_requests` at all (an older backend or fake) is left alone: it never claimed to log."""
    data = spec().get("requests_seen") or {}
    top = data.get("max_logged")
    if isinstance(top, bool) or not isinstance(top, int) or top < 0:
        raise ValueError(f"manual-capture-steps.json: requests_seen.max_logged is not a whole number >= 0 ({top!r}): the factory's "
                         "list of capture steps is damaged in this install. This is a factory defect: record it as a finding")
    drain = getattr(backend, "drain_requests", None)
    if drain is None:
        return
    try:
        seen = drain()
        if since is not None and seen is not None:
            # t-1957 N1a (E1.13): a kept session serves several items, so the log of ONE item is the part of the backend's single
            # collector that began at `since` (an `event_mark()`); a backend that cannot give that part is said, never read whole
            # (a request is never attributed to another item's attempt)
            events = backend.events_since(since)
            seen = {"rows": [{"method": e.get("method"), "url": e.get("url"), "count": 1} for e in events if e.get("kind") == "request"]}
    except Exception:
        seen = None
    if seen is None:
        attempt.limitations.append(str(data.get("unlogged") or "the requests this page sent are not logged by this capture backend"))
        return
    allowed = backend.allowed_hosts() if hasattr(backend, "allowed_hosts") else None
    pairs: dict = {}
    for row in seen.get("rows") or []:
        url = _safe_url(row.get("url"))
        if not url or (allowed and host_key(row.get("url")) not in allowed):
            continue                                  # a host that is no stand is never listed as the page's request
        pair = (str(row.get("method") or "GET").upper(), url)
        pairs[pair] = pairs.get(pair, 0) + int(row.get("count") or 1)
    shown, withheld, more = [], 0, 0
    for (method, url), count in pairs.items():
        line = f"{method} {url}" + (f" x{count}" if count > 1 else "")
        try:
            hit = secret_pattern_hit(line, cfg)
        except ValueError:
            hit = -1
        if hit is not None:
            withheld += 1
        elif len(shown) < top:
            shown.append(line)
        else:
            more += 1
    # `requests seen: 0` only when the page sent none; a log whose every pair was withheld or cut says how many there were instead
    lines = shown or ([f"requests seen: {len(pairs)} pair(s), none listed below"] if pairs else ["requests seen: 0"])
    if more:
        lines.append(f"... and {more} more")
    if withheld:
        lines.append(f"{withheld} request line(s) not stored: they match secret_content_patterns")
    none = not pairs
    attempt.store_text("requests-seen", "\n".join(lines).encode("utf-8"), "log", "supporting", ["requests seen"], _cmd(attempt), ".txt",
                       spec()["capture_words"]["requests_none"] if none else None)


MANUAL_STAND_WAIT_S = 120      # the wait of a role's call for a held stand, when neither the project nor the data says otherwise


class StandHeld(Exception):
    """The stand stayed held for the whole wait: `run_suite.hold_stand` has already printed the ONE `stand_busy` answer; `code` is its exit."""

    def __init__(self, code: int):
        super().__init__("stand_busy")
        self.code = code


def _manual_stand_wait_s(cfg: dict) -> int:
    """How long a role's capture call waits for a held stand: `run.manual_stand_wait_s` of the project, else `stand_lease.wait_s` of
    `manual-capture-steps.json`, else MANUAL_STAND_WAIT_S. Short on purpose: a role's shell call is killed by its host long before the
    suites' 30 minutes, and the role must see `stand_busy`, not a dead command."""
    run = cfg.get("run") if isinstance(cfg, dict) and isinstance(cfg.get("run"), dict) else {}
    for value in (run.get("manual_stand_wait_s"), (spec().get("stand_lease") or {}).get("wait_s")):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return MANUAL_STAND_WAIT_S


@contextlib.contextmanager
def _hold_stand(cfg: dict, project_root, stand, job_id: str, attempt_dir=None, mode: str = "exclusive", max_shared: int = 1):
    """Every `ui`, `http` and `app` call holds the stand's lease while it runs (t-1765 X3, F-X3-5): the whole call, released on a normal
    exit and on an exception. ONE lease helper for the suites and the captures: `run_suite.hold_stand` (it prints the one `stand_busy`
    answer, AR-18); a busy stand is `StandHeld` (exit 3, before anything is opened; an empty attempt folder this call made is removed).
    A lease file that cannot be used - raised or yielded as `lease_error` - is a stderr note naming the file, and the call goes on."""
    import run_suite
    name = str((stand or {}).get("name") or "") if isinstance(stand, dict) else ""
    stack = contextlib.ExitStack()
    extra = {} if mode == "exclusive" else {"mode": mode, "max_shared": max_shared}     # the default call stays the old 4-argument call
    try:
        lease = stack.enter_context(run_suite.hold_stand(cfg, job_id, name, _manual_stand_wait_s(cfg), **extra))
    except SystemExit as stop:
        if attempt_dir is not None:
            try:
                Path(attempt_dir).rmdir()             # only when empty: a joined attempt keeps its files
            except OSError:
                pass
        raise StandHeld(stop.code if isinstance(stop.code, int) else EXIT_ENV_BLOCKED) from None
    error = lease.get("lease_error") if isinstance(lease, dict) else None
    if error:
        print(f"STAND LEASE (note, not a block): the lease file {stand_lease._paths(project_root)[0]} cannot be used, the call goes on "
              f"unprotected - {error}", file=sys.stderr)
    with stack:
        yield lease


def _failure_refusal(backend, attempt: Attempt, line, glob) -> dict:
    """A refused `fail_request`: the pattern names a host that is no configured stand (the route would answer in its name)."""
    host = glob.split("://", 1)[1].split("/", 1)[0]
    hosts = ", ".join(sorted(f"{k[0]}://{k[1]}:{k[2]}" for k in backend.allowed_hosts() if k)) or "none"
    return {"entry": attempt.step(_cmd(attempt), line, "refused", spec()["capture_words"]["failure_host"].format(
        glob=glob, host=host, hosts=hosts)), "shot": None}


def _cmd(attempt) -> str:
    """The word a call writes in `command` of its step and capture lines: `ui` for the browser, `app` for a device."""
    return getattr(attempt, "command", "ui")      # `getattr`: a test's fake attempt may lack the field


def _with_limit(attempt, own=None):
    """The limitation of one stored file: `own` (a cut body), and on a device every file also says the network of the device is not
    confined to the stand (the browser's guard cannot be laid over a device, so 'the session never leaves the stand' is not promised,
    FR-41). The browser's files get `own` unchanged."""
    wide = getattr(attempt, "entry_limitation", "")
    return "; ".join(x for x in (own, wide) if x) or None


def _cut_lines(text, max_bytes, cut_note) -> tuple:
    """(text, lines left out): `text` whole when it fits `max_bytes`, else its first whole lines that fit, then `cut_note` (its `{k}` is
    the number of lines left out) as the last line - the file says it was cut, and where, never ends in the middle of a line."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text, 0
    lines, kept, used = text.splitlines(), [], 0
    for one in lines:
        size = len(one.encode("utf-8")) + 1
        if used + size > max_bytes:
            break
        kept.append(one)
        used += size
    left = len(lines) - len(kept)
    return "\n".join([*kept, cut_note.format(k=left)]) + "\n", left


def _store_device_text(attempt, step, account, cfg, kind, label, text, suffix, cut=False, max_bytes=None, cut_note="", head="", says=None):
    """A device's `source` or `log` (EP1-41d) and a page's `look` (t-1765 X8): the text hidden from the session's accounts, scanned for
    secrets (a match - or a pattern that cannot be scanned - is a refusal that names only the pattern's index), cut at BODY_CAP with its
    limitation, stored as a `supporting` file of `kind`. `head` is a first line the file starts with (scanned with it); `max_bytes` cuts the
    text at a line with `cut_note` and a limitation of its own (`look` is read by a role through a guard that refuses a large file whole);
    `says(kept_text, capture_entry)` words the step line (default: the byte count). Returns the steps.jsonl entry."""
    line, word = step["line"], step["word"]
    text = account.hide(head + text)
    try:
        hit = secret_pattern_hit(text, cfg)
    except ValueError:
        return attempt.step(_cmd(attempt), line, "refused", f"the {word} could not be scanned for secrets (secret_content_patterns of "
                            "config.json is broken): nothing was stored. Repair the pattern, then repeat the step")
    if hit is not None:
        return attempt.step(_cmd(attempt), line, "refused", f"the {word} matches secret_content_patterns[{hit}]: nothing was stored")
    own = None
    if max_bytes is not None:
        text, left = _cut_lines(text, max_bytes, cut_note)
        if left:
            own = f"{word} cut: {left} more lines not stored (the file holds at most {max_bytes} bytes)"
    stored, truncated = cut_body(text.encode("utf-8"))
    kept, _ = body_text(stored, truncated)
    made = attempt.store_text(f"{word}-{label}", kept.encode("utf-8"), kind, "supporting", [f"{word} {label}"], _cmd(attempt), suffix,
                              _with_limit(attempt, _limit_words(word) if (truncated or cut) else own))
    return attempt.step(_cmd(attempt), line, "ok", says(kept, made) if says else f"{len(kept.encode('utf-8'))} bytes")


def _window_refusal(attempt, line, account, what: str) -> dict:
    """The refused step inside the sign-in window: nothing of the form's screen is saved. Its door is the recorded end of the window."""
    door = ("capture after the page has left the sign-in address" if account.url_not else
            "config.json has no manual_capture.login.ui.landed.url_not, so the sign-in window never closes: "
            "add it (onboarding names the sign-in address), or sign in by code (a steps file without "
            "`fill-account`)")
    if _cmd(attempt) == "app":       # a device has no address and no sign-in by code: the recorded element is the door
        door = ("capture after the sign-in screen is gone" if account.url_not else
                "config.json has no manual_capture.login.app.sign_in_selector, so the sign-in window never closes: "
                "add it (`<strategy>=<value>` of an element only the sign-in screen has; onboarding names it)")
    return {"entry": attempt.step(_cmd(attempt), line, "refused", NO_SHOT_IN_WINDOW + f" ({what} inside the sign-in window); "
                                  + door), "shot": None}


def _stand_may_change(stand, no_words=()) -> bool:
    """Whether the stand's row records that it may be changed (`safe_to_break`: true, or the person's words about what may break).
    ERROR DIRECTION (FR-59): an absent, empty or false value, no row at all, or a string that IS one of the data row `safe_to_break_no`
    (the WHOLE stripped, case-folded value: "no", "false", "unknown" ...) is `no` - a new account is never made on a guess. A sentence
    is not searched for those words (FR-12)."""
    value = stand.get("safe_to_break") if isinstance(stand, dict) else None
    if value is True:
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    return value.strip().casefold() not in {str(w).strip().casefold() for w in no_words}


def _new_account_template(args, spec_data) -> str:
    return args[2] if len(args) == 3 else str(spec_data.get("generated_user_template") or spec()["generated_user_template"])


def _type_new_value(backend, cfg, selector, text, lookup, timeout_s) -> None:
    """Type `text` into the field character by character, as `fill` does; the rows the backend keeps hold the value and are NOT stored.
    A backend that cannot key a field (a device, an older fake) sets the value at once."""
    if all(hasattr(backend, name) for name in ("clear_field", "type_chars")):
        _, took_clear, focus_clear = backend.clear_field(selector)
        lookup(focus_clear)
        _, took, focus_s = backend.type_chars(selector, text, _manual_number(cfg, "type_delay_ms"), _manual_number(cfg, "settle_ms"))
        lookup(focus_s)
        if took_clear + took > timeout_s:
            raise StepTimeout(took_clear + took)
    else:
        lookup(backend.fill(selector, text))


def _run_new_account(backend, attempt: Attempt, step, cfg, spec_data, account, lookup, timeout_s=0) -> dict:
    """`fill-new-account <selector> user|secret [template]` (t-1957 N1c): a NEW account made through the app's own sign-up form.
    `user`: the pair is generated (`generated_account`), the name shaped by the template, BOTH are recorded through
    `CreatedAccounts.add` (under its lock) BEFORE anything is typed, so a created password is never lost; then the name is typed.
    `secret`: the same pair's password. The step line, the answer and the evidence say `created:<name> [generated]`, never a value;
    the pair is added to the call's `account` so every kept text hides it. Refused, with a door: a stand that is not `safe_to_break`
    (E1c.4), a `secret` with no `user` before it in the item (E1c.1), a template without the placeholder (E1c.5), a generated value that
    matches a `secret_content_patterns` entry three times running (E1c.3: nothing stored)."""
    line, args = step["line"], step["args"]

    def stop(words):
        return {"entry": attempt.step(_cmd(attempt), line, "refused", _detail(words)), "shot": None}

    if not _stand_may_change(account.stand, spec_data.get("safe_to_break_no") or spec()["safe_to_break_no"]):
        return stop("this stand may not be changed: its row in config.json environments[] does not record `safe_to_break`, so no "
                      "account is made on it. Ask the person to record what may be changed on it, or sign in with an account the stand "
                      "already lists: `fill-account <selector> <actor> user|secret`")
    if account.task_root is None:
        return stop("the story's folder is not known to this call, so a created user cannot be recorded: nothing was typed")
    if args[1] == "secret":
        pair = getattr(account, "generated", None)
        if pair is None or pair[0] != attempt.case:         # the pair of ANOTHER item of the walk is not this item's (E1c.1)
            return stop("type the user first: a `fill-new-account <selector> user` step comes before `secret` in the same item, "
                          "so the password belongs to a recorded account")
        _, name, password = pair
    else:
        template = _new_account_template(args, spec_data)
        if GENERATED_USER not in template:
            return stop(f"the template {template!r} lacks the placeholder `{GENERATED_USER}`; expected for example "
                          f"`{GENERATED_USER}@example.test`")
        for _ in range(NEW_ACCOUNT_TRIES):
            name, password = generated_account(account.task_root, attempt.case)
            name = template.replace(GENERATED_USER, name)
            try:
                hit = next((h for h in (secret_pattern_hit(name, cfg), secret_pattern_hit(password, cfg)) if h is not None), None)
            except ValueError:
                return stop("a generated account could not be scanned for secrets (secret_content_patterns of config.json is broken): "
                              "nothing was stored. Repair the pattern, then repeat the step")
            if hit is None:
                break
        else:
            return stop(f"the generated account matched secret_content_patterns[{hit}] {NEW_ACCOUNT_TRIES} times: nothing was stored. "
                          "Repeat the step; if it happens again the pattern is too broad for a generated value")
        form_path = _path_of(_url_of(backend))
        try:       # recorded FIRST and `unconfirmed`: an identity only once the sign-up is seen to land (`_confirm_new_accounts`)
            created_account_store(account.task_root).add(name, password, attempt.case, form_path, status=UNCONFIRMED,
                                                         reason="the sign-up has not been seen to land")
        except (ValueError, TimeoutError) as exc:
            return stop(str(exc))
        account.credentials.append(Credentials(name, password))
        account.generated = (attempt.case, name, password)
        account.pending_new = [*(getattr(account, "pending_new", None) or []), (name, form_path)]
    _type_new_value(backend, cfg, args[0], name if args[1] == "user" else password, lookup, timeout_s)
    return {"entry": attempt.step(_cmd(attempt), line, "ok", f"created:{name} [generated]"), "shot": None}


def _settle_new_accounts(attempt: Attempt, account, cfg, row) -> None:
    """A step did not pass while a created account was still unconfirmed (the page has not left the form's path, `_confirm_new_accounts`):
    the app refused the sign-up or it never landed (E1c.6). The account is already recorded `unconfirmed`; the page's words (hidden,
    scanned for secrets, cut) replace its reason. A confirmed account is off the list, so a later failure elsewhere does not touch it.
    A step that was only refused changes nothing: nothing was submitted. A name the walker confirmed (`account created:<n> confirmed`)
    while it was still pending is re-marked `unconfirmed` here when a later step fails on the form's path, and the walker's
    `confirmed_by` goes with it: code may override the word only in the safe direction (the account becomes unusable, FR-59)."""
    pending = list(getattr(account, "pending_new", None) or [])
    if not pending or row.get("outcome") not in ("failed", "timeout"):
        return
    account.pending_new = []
    words = account.hide(row.get("text") or row.get("detail") or "")
    try:
        hit = secret_pattern_hit(words, cfg)
        words = f"(not kept: matches secret_content_patterns[{hit}])" if hit is not None else _detail(words)
    except ValueError:
        words = "(not kept: secret_content_patterns could not be scanned)"
    store = created_account_store(account.task_root)
    for name, _ in pending:
        try:
            store.mark_unconfirmed(name, words)
        except (ValueError, TimeoutError) as exc:
            attempt.limitations.append(f"the account {name} could not be recorded as {UNCONFIRMED}: {exc}")


def _confirm_new_accounts(backend, attempt: Attempt, account, step) -> None:
    """After a step that passed (E1c.6, F11): a created account recorded `unconfirmed` is confirmed when a step other than `goto` shows a
    page whose path differs from the path it was added on - the sign-up form was left, which is the evidence it landed. A `goto` is
    no proof (the walker moved itself): it only moves the path an account is compared with. An unreadable URL changes nothing. No clause
    on `url_not`: a sign-up commonly lands on the sign-in page. An app that shows success on the form's own address stays `unconfirmed`
    (the safe direction); the role's confirm word is TR3-10."""
    pending = list(getattr(account, "pending_new", None) or [])
    if not pending:
        return
    now = _url_of(backend)
    if not now:
        return
    path = _path_of(now)
    if step["word"] == "goto":
        account.pending_new = [(name, path) for name, _ in pending]
        return
    keep = []
    store = created_account_store(account.task_root)
    for name, form_path in pending:
        if path == form_path:
            keep.append((name, form_path))
            continue
        try:
            store.confirm(name)
        except (ValueError, TimeoutError) as exc:
            keep.append((name, form_path))
            attempt.limitations.append(f"the account {name} could not be confirmed: {exc}")
    account.pending_new = keep


def _run_account_word(backend, attempt: Attempt, step, cfg, account) -> dict:
    """`account <handle> confirmed|unconfirmed <why>` (TR3-10 A): the walker's own word about an account. It acts on nothing in the browser;
    the step records `account <handle> <verdict>`, the why and the page's path. The verdict is the WALKER'S judgment (the analyst reads it
    at S7 beside the sign-in steps); this function only checks the shape and records it (AR-29). `created:<name>`: `confirmed` ->
    `CreatedAccounts.confirm(name, by="role", why=...)`, `unconfirmed` -> `mark_unconfirmed`; a name this story did not create is refused,
    nothing written. A given handle (`default`, a role, `env:U/S`): `unconfirmed` -> `AccountDoubts.add`, `confirmed` -> the step only.
    The handle is checked by shape through `resolve_actor` (no value is read, nothing is signed in). A why that matches a secret pattern is
    refused, nothing written (the walk's request check and the `ui` file check already refuse the whole text; this is the same test)."""
    line, (handle, verdict, why) = step["line"], step["args"]

    def stop(words, as_line=None):
        # `as_line`: the step line recorded in place of the walker's raw line (a why that is secret-shaped or unscanned is never recorded)
        return {"entry": attempt.step(_cmd(attempt), account.hide(as_line) if as_line else line, "refused", _detail(account.hide(words))), "shot": None}

    try:
        hit = secret_pattern_hit(why, cfg)
    except ValueError:
        return stop("the why could not be scanned for secrets (secret_content_patterns of config.json is broken): nothing was written. "
                    "Repair the pattern, then repeat the step", f"account {handle} {verdict} (why not kept: could not be scanned)")
    if hit is not None:
        return stop(f"the why matches secret_content_patterns[{hit}]: nothing was written. Repeat the step with words that quote what you "
                    "saw and no credential", f"account {handle} {verdict} (why not kept: secret_content_patterns[{hit}])")
    if account.task_root is None:
        return stop("the story's folder is not known to this call, so the word cannot be recorded: nothing was written")
    kept, note = account.hide(why), ""
    created = handle.startswith("created:")
    try:
        if created:
            name = handle[len("created:"):]
            store = created_account_store(account.task_root)
            row = store.row_of(name) if name else None
            if row is None:
                return stop(f"`{name[:80]}` is not a user this story created (`created:` names a user the sign-up or the `http` create route "
                            f"recorded). Expected `account created:<username> ...` with a name from `fill-new-account` or `created_account`, or "
                            f"a given account: {_ACTOR_FORMS}")
            if verdict == "confirmed":
                if row.get("status") != UNCONFIRMED:
                    note = "already confirmed; nothing changed"
                else:
                    store.confirm(name, by="role", why=kept)
            else:
                store.mark_unconfirmed(name, kept)
                # the role's doubt wins over a later code confirmation in the same call (the page may well have left the form)
                account.pending_new = [(n, p) for n, p in (getattr(account, "pending_new", None) or []) if n != name]
        else:
            try:
                label = resolve_actor(cfg, account.stand, handle, account.task_root)[3]
            except ValueError as exc:
                return stop(str(exc))
            if verdict == "unconfirmed":
                # a role is stored under the stand's real role key (spellings of one role are one doubt, the pool reads that key);
                # `default` and `env:U/S` keep the text as typed (the env label drops the secret key)
                role = not (handle == "default" or handle.startswith(("env:", "created:")))
                AccountDoubts(account.task_root).add(label if role else handle, kept, attempt.case)
            else:
                note = "a given account needs no confirmation; nothing written"
    except (ValueError, TimeoutError) as exc:       # a lock not got, an unreadable list: nothing was written
        return stop(str(exc))
    page = _path_of(_url_of(backend)) if _url_of(backend) else ""
    said = _joined(f"account {handle} {verdict}: {kept}", _joined(f"page: {page}" if page else "", note))
    return {"entry": attempt.step(_cmd(attempt), line, "ok", _detail(account.hide(said))), "shot": None}


def _run_step(backend, attempt: Attempt, step, timeout_s, cfg, spec_data, element_s=ELEMENT_WAIT_S, account=None) -> dict:
    """One step: {"entry": the steps.jsonl line, "shot": the path of the failed step's screenshot or None}."""
    word, args, line = step["word"], step["args"], step["line"]
    account = account or SessionAccount()
    # an ACTION between two `type`s breaks the run of typing; a passive step (data: the `keeps_run` list of the `type` row) does not - a person
    # who types '1', looks and types '2' does not click again (B1). The list is read through spec(): a caller's spec data may be empty.
    if word not in (spec().get("steps", {}).get("type", {}).get("keeps_run") or []):
        attempt.type_prior, attempt.type_chain = attempt.type_chain, None
    attempt.carry = list(attempt.unmet_pending) if word in ("look", "read") else []
    told = ""       # what a failure step adds to its own answer (a hint for the pattern, the restored rule's empty result)
    if word in ("fill-account", "fill-new-account"):
        account.window = True       # before the field is filled: nothing of this form is saved, not even a failure's screen
    elapsed = 0.0
    started = time.perf_counter()
    mark = backend.event_mark() if hasattr(backend, "event_mark") else None
    before = _url_of(backend) if mark is not None else ""

    def lookup(took):
        """An element lookup that took longer than the element limit found nothing in time: a failed step (with
        its screenshot), not a page-load timeout."""
        if took > element_s:
            raise StepFailed(f"the step completed after the element limit (took {took:.2f} s, limit {element_s:g} s)")
        return took
    try:
        if word == "goto":
            elapsed = backend.goto(args[0])
        elif word == "click":
            elapsed = lookup(backend.click(args[0]))
        elif word == "fill":
            return _run_fill(backend, attempt, step, timeout_s, cfg, spec_data, account, lookup, started)
        elif word == "look":
            return {"entry": _run_look(backend, attempt, step, timeout_s, cfg, spec_data, account), "shot": None}
        elif word == "watch":
            return {"entry": _run_watch(backend, attempt, step, cfg, spec_data, account), "shot": None}
        elif word in ("type", "press", "paste"):
            return _run_input(backend, attempt, step, timeout_s, cfg, spec_data, account, lookup, started)
        elif word == "fill-account":
            try:
                found = account.credentials_of(cfg, args[1])
            except ValueError as exc:       # a key the env file lacks, an actor the call cannot resolve: named, no value
                return {"entry": attempt.step(_cmd(attempt), line, "refused", _detail(account.hide(exc))), "shot": None}
            elapsed = lookup(backend.fill(args[0], found.username if args[2] == "user" else found.password))
        elif word == "fill-new-account":
            return _run_new_account(backend, attempt, step, cfg, spec_data, account, lookup, timeout_s)
        elif word == "account":
            return _run_account_word(backend, attempt, step, cfg, account)
        elif word in _surprise_data(spec_data, "http_steps"):
            return _run_http_word(backend, attempt, step, timeout_s, cfg, spec_data, account)
        elif word == "fail_request":
            if "://" in args[0] and host_key(args[0]) not in set(backend.allowed_hosts()):
                return _failure_refusal(backend, attempt, line, args[0])
            old = (_drained(backend) or {}).get(args[0])
            if old and old["active"]:       # the repeat replaces the record: what the old one caught is kept first
                _store_failure(attempt, cfg, account, args[0], old)
            elapsed = backend.fail_request(args[0], args[1])
            attempt.failure_declared = True
            told = account.hide(_star_hint(args[0]))
        elif word == "restore_request":
            elapsed = backend.restore_request(args[0])
            record = (_drained(backend) or {}).get(args[0])
            if record:
                _store_failure(attempt, cfg, account, args[0], record)
                if record["hits"] == 0:     # lifted with no match: told here and by the first look/read after it, never silent (TR1-2)
                    told = spec()["capture_words"]["failure_unmatched"].format(glob=_detail(account.hide(args[0])))
                    attempt.unmet_pending.append(told)
        elif word == "end-session":
            dropped, elapsed = backend.end_session()
            if elapsed > timeout_s:
                raise StepTimeout(elapsed)
            words = spec()["capture_words"]
            said = words["session_ended"].format(n=dropped, unit="cookie" if dropped == 1 else "cookies") if dropped else words["session_none"]
            return {"entry": attempt.step(_cmd(attempt), line, "ok", said), "shot": None}
        elif word in ("launch", "back"):                 # the steps of a device (EP1-41d): they exist only in `app_steps`
            elapsed = getattr(backend, word)()
        elif word == "source":
            if account.window:          # the screen's tree holds the rest of the sign-in form (a one-time code): not stored (F-15)
                return _window_refusal(attempt, line, account, "a source")
            text, took = backend.source()
            if took > timeout_s:
                raise StepTimeout(took)
            return {"entry": _store_device_text(attempt, step, account, cfg, "state", args[0] if args else "source", text, ".xml"),
                    "shot": None}
        elif word == "log":
            got = backend.device_log()
            if got is None:
                return {"entry": attempt.step(_cmd(attempt), line, "refused", "this surface keeps no log of the device, so there is "
                                              "nothing to store; leave the `log` step out"), "shot": None}
            if got[2] > timeout_s:
                raise StepTimeout(got[2])
            return {"entry": _store_device_text(attempt, step, account, cfg, "log", args[0] if args else "log", got[0], ".log",
                                                cut=got[1]), "shot": None}
        elif word == "drag":
            elapsed = lookup(backend.drag(args[0], int(args[1]), int(args[2])))
        elif word == "wait":
            if args[0].isdigit():
                if int(args[0]) / 1000 > timeout_s:
                    raise StepTimeout(int(args[0]) / 1000)
                elapsed = backend.wait_ms(int(args[0]))
            else:
                elapsed = lookup(backend.wait_selector(args[0]))
        elif word == "read":
            plain, expected = read_args(args) if _cmd(attempt) != "app" else (list(args), None)
            mode = plain[1] if len(plain) == 2 else "text"
            value, took = backend.read(args[0], mode)
            lookup(took)
            raw = str(value).encode("utf-8")
            stored, truncated = cut_body(raw)
            text, _ = body_text(stored, truncated)
            text = account.hide(text)       # an account's value read back from a field (attr=value) is never stored
            hit = secret_pattern_hit(text, cfg)
            if hit is not None:
                return {"entry": attempt.step(_cmd(attempt), line, "refused",
                                              f"the value read matches secret_content_patterns[{hit}]: nothing "
                                              "was stored; read something narrower"), "shot": None}
            limitation = _limit_words("read") if truncated else None
            attempt.store_text(f"read-{args[0]}", text.encode("utf-8"), "log", "supporting",
                               [f"read {args[0]}" + ("" if mode == "text" else f" {mode}")], _cmd(attempt), ".txt",
                               _with_limit(attempt, limitation))
            if expected is None:
                return {"entry": attempt.step(_cmd(attempt), line, "ok", _detail(account.hide(value))), "shot": None}
            # F12 (a): the role's own planned text against the value read, whitespace collapsed; a different value is RECORDED (the
            # step's `expect` field and its detail) - a walk call stops on it, a `ui` call only records. Code compares bytes.
            same = " ".join(str(value).split()) == " ".join(expected.split())
            said = "expect: matched" if same else f"expect: differs, expected \"{_kept_text(expected, cfg, account)}\""
            return {"entry": attempt.step(_cmd(attempt), line, "ok", _joined(_detail(account.hide(value)), said),
                                          expect="matched" if same else "differs"), "shot": None}
        elif word == "capture":
            if account.window:
                return _window_refusal(attempt, line, account, "a capture")
            phase = args[0]
            seen = _drained(backend) if phase == "post_action" else {}
            if seen is None and attempt.failure_declared:
                return {"entry": attempt.step(_cmd(attempt), line, "refused", "whether the failure declared with `fail_request` was met "
                                              "could not be established, so no post_action screen is taken. Repeat the "
                                              "check in a new attempt"), "shot": None}
            idle = [g for g, r in (seen or {}).items() if r["active"] and r["hits"] == 0]     # a lifted rule reported its result at the lifting (TR1-2)
            if idle:        # a screen of a page that never met the failure proves nothing about it (EP1-30, FR-18)
                return {"entry": attempt.step(_cmd(attempt), line, "refused", spec()["capture_words"]["failure_unmet"].format(
                    globs=", ".join(idle))), "shot": None}
            label = args[1] if len(args) == 2 else phase
            path = attempt.next_name(f"{phase}-{label}", ".png")
            elapsed = backend.screenshot(path)
            if elapsed > timeout_s:
                path.unlink(missing_ok=True)
                raise StepTimeout(elapsed)
            attempt.register(path, "image", phase, [label] if len(args) == 2 else [f"state at {phase}"], _cmd(attempt),
                             _with_limit(attempt))
            if seen:        # the count of each failure at this screen: the role compares it with the count before the action
                counts = {g: r["hits"] for g, r in seen.items()}
                return {"entry": attempt.step(_cmd(attempt), line, "ok", "hits_at_capture " + json.dumps(counts, ensure_ascii=False),
                                              hits_at_capture=counts), "shot": None}
            return {"entry": attempt.step(_cmd(attempt), line, "ok", ""), "shot": None}
        if elapsed > timeout_s:
            raise StepTimeout(elapsed)
        idle = _pump(backend, word, started, timeout_s, cfg, spec_data)
        note = _action_note(backend, mark, before, step, cfg, account)
        return {"entry": attempt.step(_cmd(attempt), line, "ok", _joined(_joined(_joined(f"{elapsed:.2f} s" if word == "goto" else "", note), idle),
                                                                         told), told=[told] if told else []), "shot": None}
    except StepTimeout as exc:
        note = (f"step: {line}\nlimit_s: {timeout_s:g}\nelapsed_s: {exc.elapsed_s:g}\n"
                "the step took longer than the limit; no screenshot was taken\n")
        attempt.store_text("timeout", note.encode("utf-8"), "log", "supporting", ["timeout"], _cmd(attempt), ".log",
                           limitation=_with_limit(attempt))
        return {"entry": attempt.step(_cmd(attempt), line, "timeout", f"took {exc.elapsed_s:g} s, the limit is {timeout_s:g} s"),
                "shot": None}
    except StepFailed as exc:
        _pump(backend, word, started, timeout_s, cfg, spec_data)       # what the failed step already caused still reaches it
        shot = None
        if not account.window:
            try:
                path = attempt.next_name("failed-step", ".png")
                backend.screenshot(path)
                attempt.register(path, "image", "supporting", [f"failed step: {line}"], _cmd(attempt), _with_limit(attempt))
                shot = attempt.rel(path)
            except Exception:
                pass
        detail = exc.render(cover_note=_cover_note(exc.cover, cfg), screenshot=shot,
                            shot_note=NO_SHOT_IN_WINDOW if account.window else None)
        return {"entry": attempt.step(_cmd(attempt), line, "failed", _detail(account.hide(detail))), "shot": shot}


class UrllibHttp:
    """The real HTTP client: no redirect is followed (a 3xx is the answer), TLS errors are ignored for the
    configured stand hosts only (the harness's own VERIFY_SSL=False), the body is read up to BODY_CAP + 1."""

    def request(self, method, url, headers, body, timeout_s):
        import socket
        import ssl
        import urllib.error
        import http_client

        context = ssl._create_unverified_context()
        started = time.perf_counter()
        try:
            # B-408: through the factory's one HTTP helper - no redirect followed, the factory's User-Agent unless the
            # request already carries one (`run_http` puts it in the recorded headers), the body read up to BODY_CAP + 1
            # bytes on any status. The TLS context is the same unverified one: only configured stand hosts get here.
            answer = http_client.fetch(url, method=method, data=body, headers=headers, timeout=timeout_s,
                                       max_body=BODY_CAP + 1, ssl_context=context)
        except (socket.timeout, TimeoutError):
            raise StepTimeout(time.perf_counter() - started)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise StepTimeout(time.perf_counter() - started)
            raise StepFailed(f"the stand did not answer: {exc.reason}")
        return HttpResult(answer.status, list(answer.headers), answer.body, time.perf_counter() - started,
                          unreadable=answer.unreadable)


class HttpOnlyBackend:
    """The surface of a walk that has no screen (FL-1 B: a story with an API and no UI). It is the walk's `backends[actor]` and has only
    what an `http` step needs: `http` (one request through `client`, the Bearer token of the actor's account added when there is one and
    the request names no Authorization of its own), `allowed_hosts` (the walk's stand hosts: `http_call` sends nowhere else), `close`.
    `sign_in_problem` is set by the walk when the actor has no HTTP sign-in the factory knows; a step of that actor then ends `failed`
    BEFORE anything is sent. The token lives in memory only. `screenless` tells the walk server there is no page to look at."""
    screenless = True

    def __init__(self, client=None, hosts=(), token="", sign_in_problem=""):
        self.client, self._hosts, self.token, self.sign_in_problem = client or UrllibHttp(), set(hosts), str(token or ""), sign_in_problem

    def allowed_hosts(self) -> set:
        return set(self._hosts)

    def http(self, method, url, headers, body, timeout_s):
        sent = dict(headers)
        if self.token and not any(str(k).lower() == "authorization" for k in sent):
            sent["Authorization"] = "Bearer " + self.token
        return self.client.request(method, url, sent, body, timeout_s)

    def close(self):
        self.token = ""


def _own_login(cfg: dict) -> dict:
    """The project's `manual_capture.login` object, else {} (the ONE read of it: the recipe lookup, `login_declared_none`
    and the sign-in source all go through it)."""
    own = cfg.get("manual_capture") if isinstance(cfg.get("manual_capture"), dict) else {}
    return own.get("login") if isinstance(own.get("login"), dict) else {}


def _access_of(cfg: dict):
    """The project's `environment.access` object, else None."""
    environment = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
    return environment.get("access") if isinstance(environment.get("access"), dict) else None


def login_recipe(cfg: dict, spec_data: dict, kind: str) -> dict:
    """The login recipe of `kind` (`ui` | `http`), looked up PER KIND (t-292 Q6, Q7): a key `manual_capture.login.<kind>`
    in config replaces that kind whole; an absent key falls back to the factory's default; a present `null` means
    "this kind needs no login" ({}). A config that overrides only `ui` used to lose the `http` recipe with it."""
    mine = _own_login(cfg)
    if kind in mine and mine[kind] is not None and not isinstance(mine[kind], dict):
        # t-308 F3: a string or a list used to mean "no login" in silence - the capture then ran signed out and the
        # gate said nothing. A recipe defect is the call's fault (FR-46, exit 2), named by its key (FR-1).
        raise ValueError(f"manual_capture.login.{kind} in config.json is neither an object nor null. Expected a login "
                         f"recipe (an object shaped like `login.{kind}` in references/manual-capture-steps.json) to "
                         f"replace the factory's, or null for a {kind} capture that needs no login; leave the key out "
                         "to take the factory's default")
    recipe = mine[kind] if kind in mine else (spec_data.get("login") or {}).get(kind)
    return recipe if isinstance(recipe, dict) else {}


def login_declared_none(cfg: dict, kind: str) -> bool:
    """True when config says, explicitly, that `kind` needs no login: `manual_capture.login.<kind>: null`. The
    driver reads it (it asks the person nothing for such a project); an ABSENT key is not this - except for `http`
    (EP1-31): with no `login.http` key, a project whose `environment.access.kind` is `none` has recorded that it signs
    in by no request, so the answer is the same and no account is ever sent to a guessed address."""
    mine = _own_login(cfg)
    if kind in mine:
        return mine[kind] is None
    return kind == "http" and str((_access_of(cfg) or {}).get("kind") or "").strip() == "none"


def landing_rule(recipe: dict) -> tuple:
    """(url_not, session_cookie) of a recipe's `landed` rule: the address fragments a landed page's URL must NOT
    hold, and the cookie whose presence proves the session. Absent `landed` / `url_not` -> []; absent or null
    `session_cookie` -> None (the proof is then the sign-in field being gone). A malformed one is the CALL's fault
    (FR-46, exit 2): "" would never land, and a string would be read letter by letter."""
    landed = recipe.get("landed") if isinstance(recipe, dict) else None
    if landed is not None and not isinstance(landed, dict):
        # t-308 F3: a string or a list used to be read as "no rule" while the message said there was none in config -
        # false. Present and not an object is a defect of the call; absent or null is the weak proof, said (E6).
        raise ValueError("manual_capture.login.ui.landed in config.json is neither an object nor null. Expected the "
                         "landing rule, for example {\"url_not\": [\"/auth/sign-in\", \"openid-connect\"], "
                         "\"session_cookie\": \"session_id\"}; leave the key out to take the default "
                         "(references/manual-capture-steps.json: no cookie, the landing is proved by the sign-in "
                         "field being gone), or null to prove the landing by the sign-in field being gone")
    landed = landed or {}
    url_not = landed.get("url_not", [])
    if (not isinstance(url_not, list) or any(not isinstance(piece, str) or not piece for piece in url_not)):
        raise ValueError("manual_capture.login.ui.landed.url_not in config.json is not a list of non-empty strings. "
                         "Expected the address fragments a landed page's URL must not hold, for example "
                         "[\"/auth/sign-in\", \"openid-connect\"] (the factory's default, "
                         "references/manual-capture-steps.json); leave the key out to take the default")
    cookie = landed.get("session_cookie")
    if cookie is not None and (not isinstance(cookie, str) or not cookie):
        raise ValueError("manual_capture.login.ui.landed.session_cookie in config.json is not a non-empty string. "
                         "Expected the NAME of the cookie the stand sets when the login lands, for example "
                         "\"session_id\"; leave it out or null to prove the landing by the sign-in field being gone")
    return list(url_not), cookie


def _foreign_said(result, expect="any") -> str:
    """What answered, in the factory's words, when the answer of `result` (an `HttpResult`, or None) is NOT shown to be
    the stand's own (B-408: a page, a text, an authorship marker among the headers); else ``. Only an error status
    (and, for a login, a 2xx that is no token) is described: a 2xx the step asked for is simply the answer."""
    if result is None:
        return ""
    import http_client
    try:
        return http_client.unattributed(result.status, result.body, result.headers, expect=expect)
    except Exception:  # noqa: BLE001 - a fake's odd shape never fails the capture over a sentence
        return ""


def _token_of(recipe: dict, raw: str):
    """The token a login answer carries, else None (the ONE read of it): under the recipe's `token_field` when the recipe
    names one; a recipe that names none (the one read from `environment.access`) takes the token by the names and
    wrappers every login of the factory knows (`stand_access.token_value`)."""
    if "token_field" not in recipe:
        import stand_access
        return stand_access.token_value(raw)
    try:
        return json.loads(raw).get(recipe["token_field"])
    except (ValueError, AttributeError):
        return None


def _login_words(spec_data: dict) -> dict:
    """The words of the HTTP sign-in (`login.words` of manual-capture-steps.json); the file's own when the caller's
    `spec_data` is a stand-in without them."""
    words = (spec_data.get("login") or {}).get("words") if isinstance(spec_data, dict) else None
    return words if isinstance(words, dict) else spec()["login"]["words"]


def http_login_source(cfg: dict, spec_data: dict, env: dict, root=None) -> tuple:
    """(recipe, source) of the HTTP sign-in of a capture - the ONE reader of where it comes from (EP1-31, AR-13).
    `source` is `project` (`manual_capture.login.http`), `access` (`environment.access` of kind `local_login`: the address
    it records, resolved here as the probe resolves it) or `factory_default` (only for a project that records NO access
    kind at all). Any other kind (`harness_command`, `bearer_env`, `oidc_password`, `none`, an unknown one), or a
    `local_login` whose address does not resolve, has no request the factory knows: EnvBlocked, raised before anything is
    sent. Invariant: an account never goes to an address, or in a form, that the project did not record. `root=None`
    resolves no key name (only an address written out or a path under `env["base_url"]`)."""
    recipe = login_recipe(cfg, spec_data, "http")      # a malformed one is refused here, by its key
    if "http" in _own_login(cfg):
        return recipe, "project"
    access = _access_of(cfg)
    kind = str((access or {}).get("kind") or "").strip()
    if not kind:
        return recipe, "factory_default"
    if kind == "local_login":
        import stand_access
        values = {}
        if root is not None:
            import gate_preflight
            files, _how = gate_preflight.configured_env_files(cfg.get("environment"), root)
            values = gate_preflight.env_values(files)
        url = stand_access.resolve_url(access.get("url"), values, str((env or {}).get("base_url") or ""))
        if url:
            return {"url": url}, "access"
    words = _login_words(spec_data)
    raise EnvBlocked(words["not_known_line"].replace("{kind}", kind[:40]), words["not_known_door"], "factory",
                     do_not_retry=True, cause=LOGIN_UNKNOWN_CAUSE)


def _pairs_login(post, cfg, creds: Credentials, secrets: tuple) -> list:
    """The pairs branch of `_http_login`: the field names of environment.access, else the pairs of the data row, through
    the probe's own loop (FB-3). Refused field names raise before anything is sent."""
    import config_contract
    import stand_access
    access = (cfg.get("environment") or {}).get("access") if isinstance(cfg.get("environment"), dict) else None
    refused = config_contract.body_field_errors(access)
    if refused:
        raise ValueError(refused[0] + " - fix it in qa-factory/config.json; nothing was sent")

    def send(u: str, s: str) -> tuple:
        answer = post({u: creds.username, s: creds.password})
        return answer.status, answer.body.decode("utf-8", "replace")

    return stand_access.try_body_pairs(config_contract.body_field_candidates(access), send, secrets)


def _http_login(client, env, creds: Credentials, spec_data, cfg, timeout_s, root=None) -> str:
    import stand_access
    recipe, source = http_login_source(cfg, spec_data, env, root)      # EnvBlocked here: nothing has been sent
    words = _login_words(spec_data)
    whence = words["source_" + source]
    own_url = recipe.get("url") if source == "access" else None      # only the address the access record names
    url = own_url.strip() if isinstance(own_url, str) and own_url.strip() else (
        str(env.get("base_url") or "").rstrip("/") + recipe.get("path", ""))
    status, code, token, result, attempts = "no usable answer", None, None, None, None
    held = {"result": None}
    secrets = (creds.username, creds.password)

    def post(body: dict):
        held["result"] = None  # the answer of the attempt in hand only, never of an earlier one
        held["result"] = client.request("POST", url, {"Content-Type": "application/json"},
                                        json.dumps(body).encode("utf-8"), timeout_s)
        return held["result"]

    if "body" in recipe:  # a project's own recipe is sent as written, once
        body = {k: str(v).replace("{username}", creds.username).replace("{password}", creds.password)
                for k, v in (recipe.get("body") or {}).items()}
        try:
            result = post(body)
            status = f"status {result.status}"
            code = result.status
            token = _token_of(recipe, result.body.decode("utf-8"))
        except (StepTimeout, StepFailed, ValueError, AttributeError):
            result = held["result"]
    else:
        attempts = _pairs_login(post, cfg, creds, secrets)
        result, last = held["result"], attempts[-1]
        if "text" in last:
            status = f"status {last['code']}"
            code = last["code"]
            token = _token_of(recipe, last["text"])
    if attempts and stand_access.ran_out_of_pairs(attempts, secrets):
        sent = ", then ".join(f"`{a['user_field']}` / `{a['secret_field']}`" for a in attempts)
        asked = ", ".join(f"`{n}`" for n in attempts[-1]["complained"])
        raise ValueError(f"login by code at {url} ({whence}) was refused for its body shape (sent the fields {sent}); the "
                         f"stand asks for {asked} - {stand_access.LOGIN_FIELD_FIX}; say so in your findings")
    if not token:
        if source == "factory_default" and code in (words.get("default_unconfirmed_status") or ()):
            # the address is the factory's guess and the stand says it is not there (an HTML page included): nobody
            # judged the account
            raise ValueError(words["default_unconfirmed"].replace("{url}", url).replace("{status}", status))
        said = _foreign_said(result, expect="json")
        if said:
            # B-408: what answered is not shown to be the stand's own (a protection page, a text): the account was NOT
            # judged, so the sentence must not say the stand rejected it
            raise ValueError(f"login by code at {url} ({whence}) did not give a token ({status}), and what answered is "
                             f"not shown to be the stand's own ({said}), so the account named in config "
                             "environment.env_file was not judged. Check the stand's address from this machine, outside "
                             "the factory (a protection layer in front of it may be refusing the factory's requests), "
                             "and say so in your findings")
        raise ValueError(f"login by code at {url} ({whence}) did not give a token ({status}). The stand rejected the "
                         "account named in config environment.env_file, or it does not use local login: say so in your "
                         "findings")
    return str(token)


def http_call(attempt, client, method, url, body, headers, *, hosts, timeout_s, spec_data, cfg, phase, proves, step_line,
              label="request-response", kind="request_response", hide=(), created=None, store=None, case="", earlier=None) -> dict:
    """ONE request on a stand that is already chosen, into an attempt that is already open (FL-1 B, AR-15: the one request executor
    of `manual_capture.py http` and of the walk's `http` step). `{"entry": the steps.jsonl line, "result": HttpResult | None, "failed":
    {step, outcome, detail} | None, "recorded": the name of the account the stand made | None}`. Done here: (1) the URL's host is one of
    `hosts`, else a refusal and NOTHING is sent; the URL and the headers hold no generated-value placeholder, the body holds one only
    when `created` is given (its pair is put in the sent bytes, never in the recorded request); the request text matches no
    `secret_content_patterns` (the headers of `redact_headers`, which code sets, are not scanned); (2) the request; a timeout or a failed transport is the step line `timeout` / `failed`; (3) the document
    {request, response} through `_side` (`cut_body`/`body_text`: the one cut and the one encoding) and `redact`, then `_hide` over each
    credential of `hide` and over `created`, then the secret scan - a hit saves NOTHING and is a refusal; (4) the document is stored, with the
    cut said in the limitation. Not done here, by the caller: the stand lease, the choice of stand and of attempt, the sign-in.
    `earlier`: the account an earlier call of the same capture recorded (only its refusal sentence names it). A refusal is RETURNED as
    `{"refused": sentence, "recorded": ...}` (the other keys None): the caller raises or ends its step with it (L-b: no refusal unit here)."""
    def turned_back(text, recorded=None):
        return {"entry": None, "result": None, "failed": None, "recorded": recorded, "refused": text}
    if host_key(url) not in set(hosts):
        return turned_back(f"the URL {str(url)[:120]!r} is not on this call's stand (http or https, no user:password part). Allowed hosts: "
                       f"{hosts_sentence(hosts)}. Nothing was sent: a request never leaves the stand")
    # the headers code itself sets (`redact_headers`: the Bearer the tool adds) are not a request the role wrote: they are not scanned for a
    # credential shape (a JWT token is one), they are redacted in the record
    own = {str(n).lower() for n in spec_data.get("redact_headers") or []}
    pairs = [("the URL", str(url)), *((f"the header {k}", f"{k}: {v}") for k, v in headers.items())]
    scanned = [pairs[0], *(p for p, k in zip(pairs[1:], headers) if str(k).lower() not in own)]
    for where, text in pairs:
        if GENERATED_USER in text or GENERATED_PASSWORD in text:
            return turned_back(f"{where} holds a generated-value placeholder: generated values go only into the request body (--body-file)")
    placeholders = bool(body) and (GENERATED_USER.encode() in body or GENERATED_PASSWORD.encode() in body)
    if placeholders and created is None:
        return turned_back("the body holds a generated-value placeholder and this call creates no account: nothing was sent. Expected a body "
                       "with the real values, or `manual_capture.py http` for a request that creates a user")
    for text in [*(t for _w, t in scanned), body.decode("utf-8", "replace") if body else ""]:
        hit = secret_pattern_hit(text, cfg)
        if hit is not None:
            return turned_back(f"the request matches secret_content_patterns[{hit}] of config.json: nothing was sent "
                           "or saved. A credential never goes in a request you write; login is done by code")
    sent = body
    if placeholders:
        sent = (body.replace(GENERATED_USER.encode(), created.username.encode())
                .replace(GENERATED_PASSWORD.encode(), created.password.encode()))
    step, recorded = step_line, None
    try:
        result = client.request(method, url, dict(headers), sent, timeout_s)
        if created is not None and store is not None and kind == "request_response" and 200 <= result.status < 300:
            # the stand made the user: its password is kept at once, before the answer is judged, timed or stored (a slow
            # or refused answer below must not leave a user nobody can sign in as) - machine-local; the story folder
            # gets the NAME
            store.add(created.username, created.password, case, urlsplit(url).path, wait_s=ACCOUNT_LOCK_WAIT_HTTP_S)
            recorded = created.username
        if result.elapsed_s > timeout_s or getattr(result, "unreadable", False):
            raise StepTimeout(result.elapsed_s)
    except StepTimeout as exc:
        note = (f"step: {step}\nlimit_s: {timeout_s:g}\nelapsed_s: {exc.elapsed_s:g}\n"
                "the call took longer than the limit; no response was saved\n")
        attempt.store_text("timeout", note.encode("utf-8"), "log", "supporting", ["timeout"], "http", ".log")
        late = (f"; account recorded as created:{recorded}; the answer came after the limit"
                if recorded and kind == "request_response" else "")
        entry = attempt.step("http", step, "timeout", f"took {exc.elapsed_s:g} s, the limit is {timeout_s:g} s" + late)
        return {"entry": entry, "result": None, "failed": {"step": step, "outcome": "timeout", "detail": entry["detail"]},
                "recorded": recorded}
    except StepFailed as exc:
        entry = attempt.step("http", step, "failed", _detail(exc))
        return {"entry": entry, "result": None, "failed": {"step": step, "outcome": "failed", "detail": entry["detail"]},
                "recorded": recorded}
    document = {"request": _side(body, headers, spec_data, method=method, url=url),
                "response": _side(result.body, result.headers, spec_data, status=result.status,
                                  elapsed_s=round(result.elapsed_s, 3))}
    text = json.dumps(document, ensure_ascii=False, indent=2)
    for credentials in hide:
        text = _hide(text, credentials)
    if created is not None:
        text = _hide(text, created)       # B2: an answer that echoes the generated values is saved without them
    hit = secret_pattern_hit(text, cfg)
    if hit is not None:
        return turned_back(f"the response of {method} {url[:80]} matches secret_content_patterns[{hit}] of "
                       "config.json: it was NOT saved. Ask for a narrower answer or a field that carries no "
                       "secret" + (f". The account WAS recorded as created:{recorded or earlier}: use it with "
                                   f"`--as created:{recorded or earlier}` and do not create another" if recorded or earlier else ""), recorded)
    limit = None
    if document["response"]["truncated"]:
        limit = _limit_words("response")
    elif document["request"]["truncated"]:
        limit = _limit_words("request")
    attempt.store_text(label, text.encode("utf-8"), kind, phase, proves, "http", ".json", limit)
    # B-408: an answer that is not shown to be the stand's own (a protection page, an unreadable text) keeps the step
    # `ok` - the call completed and the answer is saved - but the detail says so instead of leaving a bare status
    said = _foreign_said(result) if result.status >= 300 else ""
    made = ""
    if created is not None and kind == "request_response":
        made = (f"; account recorded as created:{recorded}" if recorded else
                f"; no account was recorded (status {result.status})")
    entry = attempt.step("http", step, "ok", f"status {result.status}" + (f"; what answered is not shown to be "
                                                                         f"the stand's own: {said}" if said else "")
                         + made)
    return {"entry": entry, "result": result, "failed": None, "recorded": recorded}


def _http_surprises(attempt, step_no, result, hosts, spec_data, hide=()) -> list:
    """The `surprise` lines of one `http` step, through the same writer as a screen step's (`Attempt.surprise`, no new kind), then the
    `detector` line that says the step was watched (FL-1 B). FACTS, never a verdict (AR-18): a `status` line with the number for a 3xx
    (its fact says `redirect to <path>`), 4xx or 5xx; `blocked_host` for a redirect whose Location is not on `hosts` (nothing follows a
    redirect: it is the answer); `text` for an answer that says it is JSON and does not parse. An empty body is no `text` line (nothing
    to read), and a body cut at the cap is not read as JSON. A timeout or a failed transport is the step's outcome, not a surprise.
    Every fact passes `hide` and the secret scan, as the screen's facts do."""
    kinds, word = _surprise_data(spec_data, "http_kinds"), _surprise_data(spec_data, "http_steps")[0]
    heads = {str(k).lower(): str(v) for k, v in dict(result.headers or {}).items()}
    written = []

    def keep(kind, fact, number=None):
        if kind not in kinds:
            return
        text = " ".join(str(fact).split())
        for credentials in hide:
            text = _hide(text, credentials)
        try:
            hit = secret_pattern_hit(text, attempt.cfg)
        except ValueError:
            text, hit = "not kept: secret_content_patterns could not be scanned", None
        if hit is not None:
            text = f"not kept: matches secret_content_patterns[{hit}]"
        written.append(attempt.surprise(step_no, word, kind, text, status=number))
    status = int(result.status)
    if 300 <= status < 400:
        location = heads.get("location", "")
        try:
            went = _path_of(location) if location else "(no Location header)"
        except ValueError:
            went = "(an address that does not parse)"
        keep("status", f"status {status}: redirect to {went}", status)
        try:
            absolute = bool(urlsplit(location).scheme or urlsplit(location).netloc)
        except ValueError:
            absolute = True
        if location and absolute and host_key(location) not in set(hosts):
            try:
                where = urlsplit(location).hostname or "an address that is no http(s) host"
            except ValueError:
                where = "an address that is no http(s) host"
            keep("blocked_host", f"the redirect points to {where}, which is not a host of this walk's stand: it was not followed", None)
    elif status >= 400:
        keep("status", f"status {status}", status)
    body = result.body or b""
    if "json" in heads.get("content-type", "").lower() and body and len(body) <= BODY_CAP:
        try:
            json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            keep("text", "the answer says it is JSON and its body does not parse as JSON")
    attempt.detector(step_no, [], kinds)
    return written


def _saved_excerpt(attempt, chars=300) -> str:
    """The first `chars` characters of the body of the answer the attempt's LAST capture holds - read from the saved document, which
    is already redacted and scanned - never from the live answer. "" when it cannot be read. A base64 body is not quoted: the
    sentence says so."""
    try:
        last = attempt._lines("captures.jsonl")[-1]
        side = json.loads((attempt.task / str(last["path"])).read_text(encoding="utf-8"))["response"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return ""
    if side.get("body_encoding") != "utf-8":
        return f"(a body of {side.get('body_bytes_stored')} bytes stored as base64: read the capture)"
    return str(side.get("body") or "")[:chars]


def _run_http_word(backend, attempt, step, timeout_s, cfg, spec_data, account) -> dict:
    """The walk's `http <METHOD> <path|url> [--body-file <file>]` step (FL-1 B): one request through the walk's client for the
    actor (`_BackendHttp`: the actor's browser cookies on a walk with a screen, the Bearer token of the actor's account on a walk
    without one), by `http_call`, on the hosts the backend names (a backend that names none sends nothing). `{"entry", "shot", "excerpt",
    "surprises"}`: `excerpt` is the head of the SAVED answer (`_saved_excerpt`), `surprises` the lines `_http_surprises` wrote.
    A refusal before the send, and a response that matches a secret pattern, end the step as `refused`; the walk server asks the same
    questions earlier, so these are the second guard."""
    line, args = step["line"], step["args"]

    def ended(outcome, detail):
        return {"entry": attempt.step("http", line, outcome, _detail(account.hide(detail))), "shot": None, "excerpt": ""}
    blocked = str(getattr(backend, "sign_in_problem", "") or "")
    if blocked:
        return ended("failed", blocked)      # the actor has no HTTP sign-in: said before anything is sent
    names = getattr(backend, "allowed_hosts", None)
    if not callable(names):
        return ended("refused", "this surface names no stand hosts, so no request was sent. A request is sent only on a host the walk's stand names")
    # the walk's OWN stand only (B2): the walk names it in the step; the browser's hosts (every stand of a no-`--env` walk) are never the answer
    hosts = set(step["hosts"]) if step.get("hosts") is not None else set(names())
    url = str(step.get("url") or args[1])
    if not url.startswith(("http://", "https://")):
        return ended("refused", f"the address {url[:80]!r} is a path and the walk did not resolve it on its stand: nothing was sent. "
                                "Expected a full URL on the stand, or a path on a stand that records base_url")
    body = None
    if len(args) == 4:
        body, problem = read_body_file(args[3])
        if problem:
            return ended("refused", problem)
    import http_client
    headers = {"User-Agent": http_client.user_agent()}      # B-408: part of the request the evidence records
    hide = list(getattr(account, "credentials", None) or [])
    out = http_call(attempt, _BackendHttp(backend), args[0].upper(), url, body, headers, hosts=hosts, timeout_s=timeout_s,
                    spec_data=spec_data, cfg=cfg, phase="supporting", proves=["request and response"], step_line=line, hide=hide,
                    case=attempt.case)
    if out.get("refused"):
        return ended("refused", out["refused"])
    result = out["result"]
    found = _http_surprises(attempt, attempt.step_number(), result, hosts, spec_data, hide=hide) if result is not None else []
    return {"entry": out["entry"], "shot": None, "excerpt": _saved_excerpt(attempt) if result is not None else "", "surprises": found}


def run_http(args, spec_data, passthrough=None) -> int:
    """`manual_capture.py http`. With `--session <actor>` the request goes through that actor's browser profile (`closers` holds
    what the call must close however it ends)."""
    closers = []
    try:
        # t-1765 X3 (F-X3-5): the call holds the stand's lease. A call whose config or address is refused takes none: `_run_http`
        # meets the same refusal first and says it (exit 2), before anything is sent
        try:
            cfg, project_root = load_config(args.task_root)
            stand = environment_of(args.url, cfg, root=project_root)
        except (ValueError, OSError):
            return _run_http(args, spec_data, passthrough, closers)
        try:
            with _hold_stand(cfg, project_root, stand, f"manual:{args.case}:{getattr(args, 'attempt', None) or 'http'}"):
                return _run_http(args, spec_data, passthrough, closers)
        except StandHeld as held:
            return held.code
    finally:
        for close in closers:
            try:
                close()
            except Exception:
                pass


def _run_http(args, spec_data, passthrough, closers) -> int:
    cfg, project_root = load_config(args.task_root)
    case_dir_name(args.case)
    methods = list(spec_data.get("http_methods") or [])
    method = str(args.method).upper()
    if method not in methods:
        raise ValueError(f"--method {args.method!r} is none of {', '.join(methods)}")
    phases = list(spec_data.get("phases") or [])
    if args.phase not in phases:
        hint = " (" + _old_words_hint(short=True) + ")" if args.phase in G.MANUAL_PHASE_ALIASES else ""
        raise ValueError(f"--phase {args.phase!r} is none of {' | '.join(phases)}{hint}: pre_action is the state before "
                         "the action under test, post_action after it, supporting anything else")
    env = environment_of(args.url, cfg, root=project_root)
    if args.state_url:
        environment_of(args.state_url, cfg, root=project_root)
    headers = {}
    for raw in args.header or []:
        name, sep, value = str(raw).partition(":")
        if not sep or not name.strip():
            raise ValueError(f"--header {raw!r} is not `Name: value`")
        headers[name.strip()] = value.strip()
    body = None
    if args.body_file:
        body, problem = read_body_file(args.body_file)
        if problem:
            raise ValueError(problem)
    for where, text in [("--url", args.url), ("--state-url", args.state_url or ""),
                        *(("--header", f"{k}: {v}") for k, v in headers.items())]:
        if GENERATED_USER in text or GENERATED_PASSWORD in text:
            raise ValueError(f"{where} holds a generated-value placeholder: generated values go only into the request "
                             "body (--body-file)")
    # B2: the template check runs over the file AS WRITTEN, with the placeholders in it; the values are put in only below,
    # into the bytes that are sent - never into what is checked or stored
    for text in [args.url, args.state_url or "", *(f"{k}: {v}" for k, v in headers.items()),
                 body.decode("utf-8", "replace") if body else ""]:
        hit = secret_pattern_hit(text, cfg)
        if hit is not None:
            raise ValueError(f"the request matches secret_content_patterns[{hit}] of config.json: nothing was sent "
                             "or saved. A credential never goes in a request you write; login is done by code")
    created, store = None, None      # `http_call` puts the pair into the sent bytes, never into the recorded request
    if body and (GENERATED_USER.encode() in body or GENERATED_PASSWORD.encode() in body):
        new_name, new_password = generated_account(args.task_root, args.case)
        created = Credentials(new_name, new_password)
        store = created_account_store(args.task_root)      # opened BEFORE anything is sent: a user must never be created unrecorded
    timeout_s = timeout_for(env)
    # B-408 (E4): the factory's User-Agent is part of the request the evidence records - put into `headers` HERE, before the
    # request document is built, so the saved request shows what was sent. A role's own User-Agent (any case) wins.
    if not any(k.lower() == "user-agent" for k in headers):
        import http_client
        headers["User-Agent"] = http_client.user_agent()
    login_recipe(cfg, spec_data, "http")      # a malformed `login.http` is refused here, before any attempt exists (t-308 F3)
    session_actor = getattr(args, "session", None)
    session_login = ui_recipe = None
    if session_actor is not None:
        # RN1-10: the request goes through the actor's browser profile (its cookies), so the factory's own Bearer login - and with
        # it `http_login_source`, the place a project with no known HTTP sign-in was refused - is never reached. What a session
        # needs is the UI sign-in gate A proved (E1), refused before anything is opened
        if getattr(args, "actor", None) is not None:
            raise ValueError(SESSION_VS_AS)
        ui_recipe = login_recipe(cfg, spec_data, "ui")
        landing_rule(ui_recipe)
        if (problem := recipe_rows_problem(ui_recipe)):
            raise ValueError(problem)
        login = None
        held_name = _session_attempt(args, args.case, capture_profile(cfg, args.task_root, args.case, "http",
                                                                      getattr(args, "profile", None)))[0]
        if not login_declared_none(cfg, "ui") and not _profile_signed_in(args, held_name, session_actor):
            if (why := sign_in_refusal(args.task_root, session_actor, ui_recipe)):
                raise ValueError(why)
            session_login = read_login(cfg, project_root, actor=session_actor, stand=env, task_root=args.task_root)
    else:
        login = _session_login(cfg, project_root, "http", args, env)
    client = HTTP or UrllibHttp()
    # EP1-28: the project's own profile; nothing has been sent, no attempt exists, and a refusal is exit 2
    profile = capture_profile(cfg, args.task_root, args.case, "http", getattr(args, "profile", None))
    note = ""
    if args.attempt:
        name = choose_attempt(case_root(args.task_root, args.case), args.attempt)
    else:
        name, note = choose_attempt_for(case_root(args.task_root, args.case), profile)
    backend = None
    if session_actor is not None:
        backend, code = _new_backend(args, cfg, project_root, passthrough)
        if backend is None:
            return code
        closers.append(backend.close)
    if note:
        print(note, file=sys.stderr)    # stderr: stdout stays ONE JSON object (FR-14)
    attempt = Attempt(args.task_root, args.case, name, cfg)
    before = _count_captures(attempt)
    try:
        stand_probe(attempt, cfg, project_root, profile, "start", "http", env)
    except EnvBlocked as exc:
        return _blocked(attempt, args.case, exc)
    done, failed = [], None
    if login is None and session_actor is None and "http" not in _own_login(cfg) and login_declared_none(cfg, "http"):
        print(_login_words(spec_data)["none_said"], file=sys.stderr)    # the record says "no login": said, never silent
    if session_actor is not None:
        actor_session = ActorSession(attempt.dir, session_actor)
        hosts = set(stand_hosts(cfg, root=project_root))
        backend.open(timeout_s, hosts, ui_recipe.get("local_storage"), element_wait_for(cfg), profile_dir=actor_session.profile)
        client = _BackendHttp(backend)
        if session_login is not None:
            result = sign_in(backend, cfg, project_root, session_actor, env, task_root=args.task_root, session=actor_session,
                             credentials=session_login, spec_data=spec_data, hosts=hosts, timeout_s=timeout_s)
            if not result["signed_in"]:
                return _blocked(attempt, args.case, _session_blocked(result, session_login, _frontend_of(cfg, env, project_root)))
            if not result.get("reused"):
                done.append(attempt.step("http", f"login by code as {session_login.label}", "ok",
                                         _detail(f"signed in through the browser ({result['proof']})")))
    if login is not None and not any(k.lower() == "authorization" for k in headers):
        try:
            headers["Authorization"] = "Bearer " + _http_login(client, env, login, spec_data, cfg, timeout_s, project_root)
        except EnvBlocked as exc:     # the project's sign-in is not a request the factory knows: nothing was sent
            return _blocked(attempt, args.case, exc)
        if login.label:      # the line shows who signed in, only when `--as` or the case's own account chose it (K6)
            done.append(attempt.step("http", f"login by code as {login.label}", "ok", "token obtained"))
    proves = list(args.proves or []) or ["request and response"]
    line = f"http {method} {args.url}"
    calls = [("request-response", method, args.url, body, "request_response", proves)]
    if args.state_url:
        calls.append(("state", "GET", args.state_url, None, "state", ["state"]))
    recorded = None
    hosts = set(stand_hosts(cfg, root=project_root))
    for label, verb, url, payload, kind, words in calls:
        step = line if kind == "request_response" else f"http GET {url} (state)"
        out = http_call(attempt, client, verb, url, payload, headers, hosts=hosts, timeout_s=timeout_s, spec_data=spec_data, cfg=cfg,
                        phase=args.phase, proves=words, step_line=step, label=label, kind=kind, created=created, store=store,
                        case=args.case, earlier=recorded)
        if out.get("refused"):
            raise ValueError(out["refused"])
        done.append(out["entry"])
        recorded = out["recorded"] or recorded
        if out["failed"] is not None:
            failed = out["failed"]
            break
    try:
        stand_probe(attempt, cfg, project_root, profile, "end", "http", env)
    except EnvBlocked as exc:
        return _blocked(attempt, args.case, exc)
    summary = _summary(attempt, args.case, done, before, failed, {"profile": profile, "start": "ok", "end": "ok"})
    if session_actor is not None:
        summary["session"] = {"actor": session_actor, "signed_in": actor_session.signed_in()}
    if recorded:
        summary["created_account"] = f"created:{recorded}"      # the name for `--as`; the password is not in any output
    print(json.dumps(summary))
    return EXIT_OK if failed is None else EXIT_FAILED_STEP


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        refuse(self._command, message)
        sys.exit(EXIT_REFUSED)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="manual_capture.py", epilog=epilog("manual_capture.py"),
                     formatter_class=argparse.RawDescriptionHelpFormatter,
                     description="Capture the evidence of a manual-agent case by code (see the module's docstring).")
    parser._command = "manual_capture.py"
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for name in ("http", "ui", "app"):
        one = sub.add_parser(name, epilog=epilog("manual_capture.py"),
                             formatter_class=argparse.RawDescriptionHelpFormatter)
        one._command = f"manual_capture.py {name}"
        one.add_argument("--task-root", required=True, help="the story's folder, qa-factory/artifacts/<TICKET>")
        one.add_argument("--case", required=True, help="the case id as the dispatch scope spells it")
        one.add_argument("--attempt", help="a<number>; default: the latest attempt still open (for `http`: only when "
                                           "it holds the same stand profile), else the next")
        one.add_argument("--profile", help="the test profile of config.json this capture is about; default: the one that fits "
                                           "the surface (`capabilities`), else the plan's for this case, else the only one")
        one.add_argument("--as", dest="actor", help="who signs in: `default`, a role of the stand's credentials_by_role, "
                                                    "`env:USER_KEY/SECRET_KEY` (two names in the project's env file) or "
                                                    "`created:<username>`; default: the account the case's request names, "
                                                    "else the stand's default account")
        if name in ("http", "ui"):
            one.add_argument("--session", metavar="ACTOR", help="keep this account's browser profile between calls of the case "
                             "(same forms as --as: default, a role, env:USER_KEY/SECRET_KEY, created:<name>): the calls of one "
                             "--profile join one open attempt, the sign-in gate A proved is reused, and `http` sends the session's "
                             "cookies only in that attempt (name the same `--profile`; without it `http` opens its own attempt "
                             "and signs in again). Close it with `manual_capture.py session close` before `build`")
        if name == "http":
            one.add_argument("--in-harness", action="store_true", help=argparse.SUPPRESS)
            one.add_argument("--method", required=True)
            one.add_argument("--url", required=True)
            one.add_argument("--body-file")
            one.add_argument("--header", action="append")
            one.add_argument("--state-url", help="also GET this URL and save it as the state")
            one.add_argument("--phase", default="post_action", help="pre_action | post_action | supporting")
            one.add_argument("--proves", action="append", help="what this call proves; `completion` marks the "
                                                               "completion condition reached")
        else:
            one.add_argument("--steps-file", required=True)
            if name == "app":
                one.add_argument("--surface", help="the surface id (`surface` of an environments[] row) of the device stand; default: "
                                                   "the only device stand; with two and none named the call is refused")
            else:
                one.add_argument("--in-harness", action="store_true", help=argparse.SUPPRESS)
    closing = sub.add_parser("session", epilog=epilog("manual_capture.py"), formatter_class=argparse.RawDescriptionHelpFormatter,
                             help="`session close`: delete the browser profiles a --session call left (their cookies are a credential)")
    closing._command = "manual_capture.py session"
    closing_sub = closing.add_subparsers(dest="session_command", required=True, parser_class=_Parser)
    close = closing_sub.add_parser("close", epilog=epilog("manual_capture.py"), formatter_class=argparse.RawDescriptionHelpFormatter)
    close._command = "manual_capture.py session close"
    close.add_argument("--task-root", required=True, help="the story's folder, qa-factory/artifacts/<TICKET>")
    close.add_argument("--case", required=True, help="the case id as the dispatch scope spells it")
    close.add_argument("--attempt", help="a<number>; default: the latest attempt that holds a session")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = hooklib.exact_options(build_parser()).parse_args(argv)      # walks the `http`/`ui` subparsers too
    try:        # the story first (CX1-18): a phantom root creates no evidence folder; the refusal is this script's own
        hooklib.story_of("manual_capture.py", root=args.task_root, key_flag=None)
    except ValueError as exc:
        return refuse(f"manual_capture.py {args.command}", str(exc))
    data = spec()
    passthrough = [a for a in argv if a != "--in-harness"]
    if args.command == "http":
        return run_http(args, data, passthrough)
    if args.command == "app":
        return run_app(args, data)
    if args.command == "session":
        return run_session_close(args)
    return run_ui(args, data, passthrough)


if __name__ == "__main__":
    sys.exit(run_guarded(command_from_argv("manual_capture.py"), main))
