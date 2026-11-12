"""exploration.py - the core of an exploration (qa-explore): a phrase of a person becomes a folder, a state and ONE question.

A person names a feature in a few words. This library turns the phrase into a slug and a root
`qa-factory/explorations/<slug>/`, records the step state E0-E3 in `explore.json`, probes the tracker and the repositories, asks
ONE priced question (the frame packet, E0), records the answer, says which step is next and writes the brief of a role. The ONE CLI
over it is `explore_step.py`; this module has no argparse and no `sys.exit` (a refusal is `ExplorationRefused`, a `ValueError`).

What the code owns and what it leaves to a role (AR-2, FR-47): code names the folder, the order of the steps, the lock and the
words it was given; it never reads a free answer as a token (the conductor reads it and calls `answer --token`), never judges a
requirement, never searches. Every number, every reserved name, every step action is a row of references/exploration.json
(`table()` is its ONE reader, AR-1, AR-13); `explore.json` is read only by `load()` and written only here (AR-14), except the
status of a step E1-E3, which a later node writes through `set_step`.

Writes: `qa-factory/explorations/<slug>/` and `qa-factory/state/explorations/` (the lock, git-ignored with the rest of state/).
Nothing is ever written outside them. An unreadable input is a refusal, never an empty table or a fresh root (AR-28, FR-59).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib  # noqa: E402
# `no_move` (-> controller), `human_text`, `person_words`, `event_store`, `hashlib` and `unicodedata` are imported INSIDE the functions that use them: the guards
# (`stage_guard.exploration_named`) import this module on every hook call, and a story dispatch must not pay for the
# controller (AR-12; pinned by `test_exploration_identity.py` import_light).

SCRIPT = "explore_step.py"
TABLE_FILE = "exploration.json"
SCHEMA_VERSION = 1
NARROW = "narrow"
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SECONDS_PER_HOUR = 3600
WORDS_KIND = "exploreframe"

# The options of the frame packet: the words stay in code (they carry the role's name), the prices are the rows of
# question-prices.json under the key `explore.frame` (the one resolution: `NM.priced_options`, FR-6).
FRAME_OPTIONS = [
    {"answer": "yes", "token": "yes", "says": "go on as described above: search the tracker, read the code of the repositories that have hits, and write what is found under the exploration folder",
     "slots": {"role": "the scout (one session per repository with hits) and the requirements tester"}},
    {"answer": NARROW, "token": NARROW, "says": "go on, but read less: tell me which issues, repositories or search words to stay with",
     "slots": {"role": "the scout (one session per repository with hits) and the requirements tester"}},
    {"answer": "stop", "token": "stop", "says": "stop here: nothing is read and nothing is written to your tracker or your repositories"},
]
OFFERED = tuple(option["token"] for option in FRAME_OPTIONS if option["token"] != NARROW)
HOW_TO_ANSWER = ("\n## How to answer\n\nReply with one word: `yes` or `stop`, or tell me what to narrow to "
                 "(issue keys, repositories, or search words).\n")
REPO_DOORS = {"missing": "clone it to the path the project settings name, or correct that path",
              "invalid": "correct the repository path in the project settings",
              "unknown": "check that the folder is a git checkout",
              "not_configured": "name it in the project settings, or say which repositories to read when you answer",
              "nothing_configured": "name the repositories to read in the project settings, or say which to read when you answer"}


class ExplorationRefused(ValueError):
    """A refusal that says what is wrong, what was expected and a door the receiver can run (FR-1, FR-2). The CLI prints it as exit 2."""


# --- the table: ONE reader ---------------------------------------------------------------------------------------------
def _unreadable_table(what: str) -> ExplorationRefused:
    return ExplorationRefused(f"exploration table references/{TABLE_FILE} is unreadable ({what}): reinstall the plugin; nothing was written")


def table() -> dict:
    """references/exploration.json, validated; `ExplorationRefused` when it is absent, not JSON, not an object, or a required key is
    missing or ill-typed - an empty table is never a table with no rules (AR-28)."""
    found = hooklib.load_ref_json(TABLE_FILE)
    if not isinstance(found, dict) or not found:
        raise _unreadable_table("it is absent, not JSON, or empty")
    if found.get("schema_version") != SCHEMA_VERSION:
        raise _unreadable_table(f"schema_version is {found.get('schema_version')!r}, not {SCHEMA_VERSION}")
    for key, kind in (("label", str), ("env_prefix", str), ("question_key", str), ("limits", dict), ("slug", dict), ("roles", dict),
                      ("steps", dict), ("artifacts", dict), ("ready_repo_statuses", list)):
        if not isinstance(found.get(key), kind) or not found[key]:
            raise _unreadable_table(f"`{key}` is missing or is not a {kind.__name__}")
    for name, value in found["limits"].items():
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise _unreadable_table(f"`limits.{name}` is not a whole number above zero")
    slug = found["slug"]
    if not (isinstance(slug.get("hash_prefix"), str) and isinstance(slug.get("hash_chars"), int) and slug["hash_chars"] > 0
            and isinstance(slug.get("reserved"), list) and all(isinstance(x, str) for x in slug["reserved"])):
        raise _unreadable_table("`slug` lacks hash_prefix, hash_chars or reserved")
    for step, row in found["steps"].items():
        if not (isinstance(row, dict) and isinstance(row.get("statuses"), list) and row["statuses"]
                and isinstance(row.get("actions"), list) and row["actions"] and isinstance(row.get("inputs"), list)):
            raise _unreadable_table(f"`steps.{step}` lacks statuses, inputs or actions")
        for action in row["actions"]:
            if not (isinstance(action, dict) and action.get("kind") in ("run", "dispatch", "check")):
                raise _unreadable_table(f"an action of `steps.{step}` has no kind of run, dispatch or check")
    return found


def limit(name: str) -> int:
    """One number of `limits`; `ExplorationRefused` naming `limits.<name>` when the table does not hold it."""
    value = table()["limits"].get(name)
    if not isinstance(value, int):
        raise _unreadable_table(f"`limits.{name}` is absent")
    return value


def step_ids() -> list:
    return sorted(table()["steps"])


# --- the slug ----------------------------------------------------------------------------------------------------------
def collapse(phrase) -> str:
    """The phrase on ONE line: all whitespace, newlines included, becomes one space."""
    return " ".join(str(phrase if phrase is not None else "").split())


def slug_key(phrase) -> str:
    """The uncut name of a phrase: its ascii letters and digits joined by `-`, or the hash form when the phrase has too few of them,
    more non-ascii letters than ascii ones, or is a reserved device name. Case, punctuation and spacing do not change it."""
    import hashlib
    import unicodedata
    cfg = table()["slug"]
    collapsed = collapse(phrase)
    folded = "".join(c for c in unicodedata.normalize("NFKD", collapsed.casefold()) if not unicodedata.combining(c))
    ascii_alnum = len(re.findall(r"[a-z0-9]", folded))
    non_ascii_letters = sum(1 for c in folded if c.isalpha() and not c.isascii())
    key = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    if ascii_alnum < limit("slug_min_chars") or non_ascii_letters > ascii_alnum or key in cfg["reserved"]:
        digest = hashlib.sha256(collapsed.casefold().encode("utf-8")).hexdigest()
        key = cfg["hash_prefix"] + digest[:cfg["hash_chars"]]
    return key


def is_slug(name) -> bool:
    return (isinstance(name, str) and SLUG_RE.fullmatch(name) is not None and len(name) <= limit("slug_chars")
            and hooklib.is_one_component(name) and name not in table()["slug"]["reserved"])


def _not_a_name(name) -> ExplorationRefused:
    return ExplorationRefused(f"`{name}` is not an exploration name: a name is lowercase letters and digits joined by single hyphens, "
                              f"at most {limit('slug_chars')} characters, and is not a reserved device name. Use the name "
                              f"`{SCRIPT} frame` printed as `slug:`")


def root(slug: str, project) -> Path:
    """The folder of an exploration. Pure: it touches no disk; a name that is no slug is refused."""
    if not is_slug(slug):
        raise _not_a_name(slug)
    return Path(project) / "qa-factory" / "explorations" / slug


def lock_path(slug: str, project) -> Path:
    root(slug, project)                       # the name rule, once
    return Path(project) / "qa-factory" / "state" / "explorations" / f"{slug}.lock"


def exists(slug: str, project) -> bool:
    return (root(slug, project) / "explore.json").is_file()


# --- the identity the guards read (XT1-2) --------------------------------------------------------------------------------
def labels_in(text) -> list:
    """The slugs named by `Exploration: <slug>` lines of `text`, in order, without repeats. ONLY a whole line counts - the label,
    one word, nothing else on the line (`brief` writes it as its first line): the label inside a sentence is no exploration, so a
    story dispatch that quotes it is never taken for one. The label is the table's (AR-13)."""
    pattern = re.compile(r"^" + re.escape(table()["label"]) + r"[ \t]*(\S+)[ \t\r]*$", re.MULTILINE)
    found = []
    for slug in pattern.findall(str(text or "")):
        if slug not in found:
            found.append(slug)
    return found


def env_slug(value) -> str:
    """The slug of an `explore:<slug>` value (`$QA_FACTORY_TASK`, an explicit task id), else "". Not a check of the slug."""
    prefix = table()["env_prefix"]
    text = str(value or "").strip()
    return text[len(prefix):] if text.startswith(prefix) and len(text) > len(prefix) else ""


def task_id(slug: str) -> str:
    """The identity an exploration carries where a story id goes (a receipt's `task_id`, a journal line's `task`)."""
    return table()["env_prefix"] + slug


def opening_prompt(transcript) -> str:
    """The text of the FIRST user row of a transcript file - the prompt a child was dispatched with - or "" (never raises: an
    absent, unreadable or foreign-shaped file proves nothing). Reads only up to that row. Same row-to-text rule as
    `hooklib.subagent_meta`, which cannot be reused whole because it reads the entire file."""
    try:
        with open(str(transcript), encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or row.get("type") != "user":
                    continue
                content = (row.get("message") or {}).get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                return ""
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return ""


def _rel(path, project) -> str:
    return Path(path).relative_to(Path(project)).as_posix()


def _no_exploration(slug: str) -> ExplorationRefused:
    return ExplorationRefused(f"no exploration `{slug}` under qa-factory/explorations/: run "
                              f"`{SCRIPT} frame \"<the feature, in the person's words>\"` first")


def _bad_state(slug: str, why: str) -> ExplorationRefused:
    return ExplorationRefused(f"qa-factory/explorations/{slug}/explore.json cannot be read ({why}): the factory does not rewrite it; "
                              "restore it from git, or move the folder aside and run frame again")


def load(slug: str, project) -> dict:
    """`explore.json` of an exploration. Absent: the refusal that names `frame`. Unreadable, another schema or a missing part: the
    refusal that names the file - it is never rewritten, never replaced by an empty record."""
    path = root(slug, project) / "explore.json"
    if not path.exists():
        raise _no_exploration(slug)
    data = hooklib.read_json(path, None, kind=dict)
    if data is None:
        raise _bad_state(slug, "not JSON, or not an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise _bad_state(slug, f"schema_version is {data.get('schema_version')!r}, not {SCHEMA_VERSION}")
    steps = data.get("steps")
    e0 = steps.get("E0") if isinstance(steps, dict) else None
    problems = []
    if not isinstance(e0, dict) or e0.get("status") not in ("asked", "answered") or not isinstance(e0.get("words_refs"), list) \
            or e0.get("answer_token") not in (None, "yes", NARROW, "stop") or (e0.get("status") == "answered" and not e0.get("answer_token")):
        problems.append("steps.E0")
    for step in step_ids():
        if not (isinstance(steps, dict) and isinstance(steps.get(step), dict) and steps[step].get("status") in table()["steps"][step]["statuses"]):
            problems.append(f"steps.{step}")
    for key, kind in (("probes", list), ("stories", list), ("repos_named", list), ("jql", str), ("phrase", str), ("slug_key", str)):
        if not isinstance(data.get(key), kind):
            problems.append(key)
    if problems:
        raise _bad_state(slug, "it lacks or mistypes " + ", ".join(problems))
    return data


def _save(slug: str, project, data: dict) -> None:
    from event_store import atomic_json
    atomic_json(root(slug, project) / "explore.json", data)


def place(phrase, project) -> tuple:
    """`(slug, "new" | "continue")`: the folder a phrase goes to. The same `slug_key` always reaches the same folder (continuation);
    another `slug_key` that cuts to the same name gets `-2`, `-3` ... (the cut comes FIRST, then the suffix, so a name never passes
    its limit). A folder with no `explore.json` (empty, or left by a crash) is adopted as new; an unreadable `explore.json` is a refusal."""
    key = slug_key(phrase)
    chars, most = limit("slug_chars"), limit("slug_suffix_max")
    for n in range(1, most + 1):
        suffix = "" if n == 1 else f"-{n}"
        candidate = key[:chars - len(suffix)].rstrip("-") + suffix
        if not is_slug(candidate):
            raise ExplorationRefused(f"defect: the name `{candidate}` broke its own rule: tell the factory's owner; nothing was written")
        folder = root(candidate, project)
        if not folder.exists() or not (folder / "explore.json").exists():
            return candidate, "new"
        if load(candidate, project)["slug_key"] == key:
            return candidate, "continue"
    raise ExplorationRefused(f"{most} explorations already start with this name: name the feature with other words")


def path_budget_problem(root_abs, limits: dict, nt: bool) -> str:
    """"" or the refusal: on Windows (`nt`) the folder plus the files an exploration writes under it must stay inside the path budget
    of `source_inventory._atomic_write` (the last guard). Equal to the budget passes, one over refuses."""
    size = len(str(root_abs))
    if nt and size + limits["path_reserve"] > limits["path_max"]:
        return (f"the exploration folder {root_abs} is {size} characters long; with the files an exploration writes under it, paths would "
                f"pass the {limits['path_max']}-character Windows budget: open the project from a shorter folder")
    return ""


# --- the lock: one session per exploration -----------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _need_session(session) -> str:
    if not isinstance(session, str) or not session.strip():
        raise ExplorationRefused("no session id: the exploration is held by one session at a time, and this call has none; "
                                 f"run `{SCRIPT}` from the session that explores, or give the id a person tells you with `--session`")
    return session.strip()


def _read_lock(path: Path) -> dict | None:
    """`{session, since}` of a lock, or None when it is empty, not JSON, or names no session (a crash between create and write)."""
    found = hooklib.read_json(path, None, kind=dict)
    if not found or not isinstance(found.get("session"), str) or not found["session"].strip():
        return None
    return {"session": found["session"].strip(), "since": str(found.get("since") or "")}


def _since_and_age(path: Path, holder: dict | None) -> tuple:
    """`(since, hours)` for the refusal: the lock's own `since`, else the file's modified time (never a guess)."""
    moment = None
    if holder and holder["since"]:
        try:
            moment = datetime.fromisoformat(holder["since"].replace("Z", "+00:00"))
        except ValueError:
            moment = None
    if moment is None:
        moment = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    hours = max(0, int((datetime.now(timezone.utc) - moment).total_seconds() // SECONDS_PER_HOUR))
    return moment.isoformat(timespec="seconds"), hours


def _held_by(slug: str, path: Path, holder: dict | None) -> ExplorationRefused:
    import person_words
    since, hours = _since_and_age(path, holder)
    who = f"another session ({holder['session']})" if holder else "another session (an unknown session)"
    return ExplorationRefused(f"{who} has been exploring {slug} since {since} ({hours} h ago): wait for it, or release it: "
                              f"`{person_words.door(f'{SCRIPT} release --slug {slug}')}`")


def acquire(project, slug: str, session: str) -> str:
    """Take the exploration's lock: `created` or `held` (the same session already has it). Another session, or a lock nobody can read
    (a crash between create and write): a refusal naming the holder, the time and the door `release`. A lock is NEVER removed here,
    whatever its age. The file's existence is the lock (`O_CREAT|O_EXCL`): two sessions never both pass."""
    session = _need_session(session)
    path = lock_path(slug, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = _read_lock(path)
        if holder and holder["session"] == session:
            return "held"
        raise _held_by(slug, path, holder) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"session": session, "since": _now(), "pid": os.getpid()}, stream)
    except BaseException:
        try:
            path.unlink()                       # this call made the file: half a lock is not left behind
        except OSError:
            pass
        raise
    return "created"


def release_lock(project, slug: str, session: str, words_path=None) -> str:
    """Remove the lock: by the session that holds it, or on a person's word (`words_path`, copied whole into the exploration). Returns
    the line to print. No lock: nothing to release (not an error)."""
    import person_words
    path = lock_path(slug, project)
    if not path.exists():
        return f"no lock on {slug}: nothing to release"
    holder = _read_lock(path)
    text = person_words.read(None, words_path, "--words") if words_path else None
    if not (holder and session and holder["session"] == session) and text is None:
        since, _ = _since_and_age(path, holder)
        who = f"session {holder['session']}" if holder else "an unknown session"
        raise ExplorationRefused(f"the lock of {slug} is held by {who} since {since}; only that session, or a person's word, releases it: "
                                 f"`{person_words.door(f'{SCRIPT} release --slug {slug}')}`")
    if text is not None:
        person_words.write_words(root(slug, project), "", WORDS_KIND + "release", text)
    since, _ = _since_and_age(path, holder)
    who = holder["session"] if holder else "an unknown session"
    path.unlink()
    return f"released: {slug} (held by {who} since {since})"


# --- the probes --------------------------------------------------------------------------------------------------------
def _config(project) -> dict:
    """The project's config through its ONE reader (`config_contract.read_config_file`, AR-13); absent or unreadable is a refusal."""
    import config_contract
    try:
        cfg = config_contract.read_config_file(project)
    except config_contract.ConfigUnreadable as exc:
        raise ExplorationRefused(f"{exc} The exploration probes the tracker and the repositories it names; nothing was written.") from exc
    if cfg is None:
        raise ExplorationRefused("qa-factory/config.json is absent: the exploration probes the tracker and the repositories it names; "
                                 "restore the file from git, or run the onboarding; nothing was written")
    return cfg


def _first_line(text) -> str:
    return (str(text).strip().splitlines() or [""])[0]


def _source_row(cfg: dict, project) -> dict:
    """ONE row for the tracker, mapped from `readiness.check_jira_direct` BY FIELDS (FR-12: no prose is read). ERROR DIRECTION: the
    answer may err only toward a line the person can act on or `unknown` - never toward `verified`, never toward silence (a
    function written as the doctor's advice, used here to decide what the packet offers)."""
    entry = (cfg.get("adapters") or {}).get("ticket") if isinstance(cfg.get("adapters"), dict) else None
    if not isinstance(entry, dict) or not entry:
        return {"kind": "source", "id": "tracker", "status": "not_configured", "reason": "no tracker is configured for this project", "door": ""}
    name = str(entry.get("name") or entry.get("kind") or "tracker")
    row = {"kind": "source", "id": name, "status": "unknown", "reason": "", "door": ""}
    try:
        import readiness
        from config_contract import effective_config
        result = readiness.check_jira_direct(effective_config(cfg), Path(project))
    except Exception as exc:  # noqa: BLE001 - any failure of the probe is `unknown`, never a pass
        return {**row, "reason": f"{type(exc).__name__}: {_first_line(exc)}"}
    if not isinstance(result, dict):
        return {**row, "reason": "the tracker check answered nothing this step can read"}
    status, remedy = result.get("status"), result.get("remedy")
    if result.get("applicable") is False:
        return {**row, "status": "not_applicable", "reason": "the factory searches Jira only"}
    if status == "ok":
        return {**row, "status": "verified"}
    if isinstance(remedy, dict) and status in ("missing", "not_configured"):
        steps = remedy.get("steps") if isinstance(remedy.get("steps"), list) else []
        return {**row, "status": "needs_person", "reason": str(remedy.get("need") or result.get("note") or "access is missing"),
                "door": str(steps[0]) if steps else ""}
    if isinstance(remedy, dict) and status == "unknown" and remedy.get("kind") == "probe":
        return {**row, "status": "credentials_present", "reason": "credentials are set; access is checked when the search runs"}
    if isinstance(remedy, dict) and status == "unknown" and remedy.get("kind") == "human_step":
        return {**row, "status": "unreachable", "reason": str(remedy.get("need") or "no route to the tracker from this machine")}
    return {**row, "reason": f"the tracker check answered {status!r}, which this step cannot read"}


def _probe_sources(cfg: dict, project) -> list:
    return [_source_row(cfg, project)]


def _probe_repos(cfg: dict, project, repos_named) -> list:
    """The repository rows: the inventory's own statuses carried as they are (`ready` / `missing` / `invalid` / `unknown`), filtered
    by the names the person gave. A name that matches nothing is `not_configured`; no repository at all is `nothing_configured`."""
    try:
        import project_inventory
        found = project_inventory.build_inventory(cfg, Path(project))["repositories"]
    except Exception as exc:  # noqa: BLE001 - no inventory is `unknown`, never a pass
        return [{"kind": "repo", "id": "", "status": "unknown", "reason": f"{type(exc).__name__}: {_first_line(exc)}", "door": REPO_DOORS["unknown"]}]
    named = [str(name) for name in repos_named or []]
    rows, matched = [], set()
    for repo in found:
        hit = ({str(repo.get("repo_id"))} | {str(x) for x in repo.get("names") or []}) & set(named)
        if named and not hit:
            continue
        matched |= hit
        status = str(repo.get("status") or "unknown")
        rows.append({"kind": "repo", "id": str(repo.get("repo_id") or ""), "status": status, "reason": str(repo.get("reason") or ""),
                     "door": REPO_DOORS.get(status, "")})
    for name in named:
        if name not in matched:
            rows.append({"kind": "repo", "id": name, "status": "not_configured",
                         "reason": f"no repository named {name} is recorded in the project settings", "door": REPO_DOORS["not_configured"]})
    if not rows:
        rows.append({"kind": "repo", "id": "", "status": "nothing_configured", "reason": "no repository recorded in qa-factory/config.json",
                     "door": REPO_DOORS["nothing_configured"]})
    return rows


def _probe(project, repos_named) -> list:
    cfg = _config(project)
    return _probe_sources(cfg, project) + _probe_repos(cfg, project, repos_named)


def probe_line(row: dict) -> str:
    """One line of the packet (and of the narrow report) for one probe row; a line with no door when the person has none to use."""
    status, ident, reason, door = row.get("status"), row.get("id"), row.get("reason") or "", row.get("door") or ""
    if row.get("kind") == "source":
        head = f"Tracker ({ident})"
        if status == "not_applicable":
            return f"- {head}: not searched: {reason}."
        if status == "verified":
            return f"- {head}: read access was verified recently."
        if status == "needs_person":
            same = door.rstrip(".").strip() == reason.rstrip(".").strip()      # the fix step repeats the reason: say it once
            return f"- {head}: cannot be searched yet: {reason.rstrip('.')}." + (f" To fix it: {door.rstrip('.')}." if door and not same else "")
        if status == "credentials_present":
            return f"- {head}: {reason.rstrip('.')}."
        if status == "unreachable":
            return f"- {head}: not reachable from this machine; it will be a gap in the result."
        if status == "not_configured":
            return f"- {head}: {reason.rstrip('.')}; nothing is searched there."
        return f"- {head}: could not be established ({reason.rstrip('.')}); it will be reported as a gap."
    head = f"Repository {ident}" if ident else "Repositories"
    if status == "ready":
        return f"- {head}: ready to search."
    return f"- {head}: {status.replace('_', ' ')} ({reason.rstrip('.')})" + (f"; {door.rstrip('.')}." if door else ".")


def probe_lines(probes: list) -> list:
    return [probe_line(row) for row in probes]


# --- the frame packet (E0): ONE priced question ------------------------------------------------------------------------
def closed_question(key: str, lead: str, options: list, defects: list | None = None) -> tuple:
    """`(text, tokens)`: the lead, then the priced section of the question `key` of question-prices.json, through the ONE renderer
    (`NM.priced_options`, `NM.render_question`). Prices or labels that cannot be read: the options are shown WITHOUT price lines and
    the reason is appended to `defects` (a question is never withheld for its prices, FR-41)."""
    import human_text
    import no_move as NM
    try:
        verdicts = (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
        priced = NM.priced_options(key, options, NM.data(), verdicts)
        return NM.render_question(lead, priced, human_text.price_labels()), [o["token"] for o in priced if o["token"]]
    except (NM.DataUnreadable, human_text.LabelsUnreadable) as exc:
        if defects is not None:
            defects.append(f"owner: factory - the prices of the question {key} could not be read ({exc}); it was shown without its price lines")
        plain = [{"token": o.get("token"), "says": str(o.get("says") or "").strip()} for o in options]
        return str(lead).rstrip() + "\n\n" + NM.render_options(plain, []), [o["token"] for o in plain if o["token"]]


def frame_text(phrase: str, probes: list, defects: list | None = None) -> str:
    lead = (f"Before anything runs, this is what the factory will do for the feature \"{collapse(phrase)}\".\n\n"
            "It will look for requirements in the tracker, then read the code of every repository that has hits, one scout session per "
            "repository, and a requirements tester will compare the two. Nothing is written to your tracker or your repositories.\n\n"
            "What it can reach right now:\n" + "\n".join(probe_lines(probes)) + "\n\nChoose how to go on.")
    text, _tokens = closed_question("explore.frame", lead, FRAME_OPTIONS, defects)
    return text.rstrip() + "\n" + HOW_TO_ANSWER


def _packet_path(slug: str, project) -> Path:
    return root(slug, project) / "work" / "frame-packet.md"


# --- state -------------------------------------------------------------------------------------------------------------
def _clean_names(values) -> list:
    out = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def _clean_stories(values) -> list:
    out = _clean_names(values)
    for story in out:
        if not hooklib.is_one_component(story) or len(story.split()) != 1:
            raise ExplorationRefused(f"the issue key `{story}` is not one word and one path component: give the key as the tracker writes it "
                                     "(for example PROJ-12), one `--story` for each")
    return out


def _new_state(slug: str, phrase: str, stories: list, repos: list, jql: str, probes: list) -> dict:
    return {"schema_version": SCHEMA_VERSION, "slug": slug, "slug_key": slug_key(phrase), "phrase": collapse(phrase), "created_at": _now(),
            "stories": stories, "repos_named": repos, "jql": jql, "probes": probes,
            "steps": {"E0": {"status": "asked", "answer_token": None, "asked": True, "words_refs": [], "answered_at": None},
                      **{step: {"status": "pending"} for step in step_ids()}}}


def frame(project, phrase, stories, repos, jql, session) -> dict:
    """Frame an exploration: place the phrase, probe, ask. Returns `{slug, state, root, next, packet_text, price_defect}`. The same
    phrase (same `slug_key`) again is a continuation: an unanswered frame is probed and rendered again, an answered one is never
    asked again (FR-7). Another scope on a continuation is a refusal naming `narrow`."""
    from event_store import atomic_text
    collapsed = collapse(phrase)
    if not collapsed:
        raise ExplorationRefused("the feature phrase is empty: say in a few words which feature to explore")
    if len(collapsed) > limit("phrase_chars"):
        raise ExplorationRefused(f"the feature phrase is {len(collapsed)} characters; the limit is {limit('phrase_chars')}: "
                                 "shorten it to the feature's name or one sentence")
    stories, repos, jql_given = _clean_stories(stories), _clean_names(repos), (str(jql).strip() if jql is not None else None)
    _need_session(session)
    slug, state = place(collapsed, project)
    folder = root(slug, project)
    problem = path_budget_problem(folder, table()["limits"], os.name == "nt")
    if problem:
        raise ExplorationRefused(problem)
    existing = load(slug, project) if state == "continue" else None
    if existing is not None:
        for given, stored in ((stories, existing["stories"]), (repos, existing["repos_named"])):
            if given and set(given) != set(stored):
                raise _scope_differs(slug, existing)
        if jql_given is not None and jql_given != existing["jql"]:
            raise _scope_differs(slug, existing)
    cfg_needed = existing is None or (existing["steps"]["E0"]["status"] == "asked" and not existing["steps"]["E0"]["words_refs"])
    if cfg_needed:
        _config(project)                              # unreadable: refused BEFORE a lock is taken
    acquire(project, slug, session)
    defects: list = []
    if existing is None:
        data = _new_state(slug, collapsed, stories, repos, jql_given or "", _probe(project, repos))
    else:
        data = load(slug, project)
        e0 = data["steps"]["E0"]
        if e0["status"] == "asked" and not e0["words_refs"]:
            data["probes"] = _probe(project, data["repos_named"])
    e0, packet_text = data["steps"]["E0"], None
    if e0["status"] == "asked" and not e0["words_refs"]:
        packet_text = frame_text(data["phrase"], data["probes"], defects)
        atomic_text(_packet_path(slug, project), packet_text)          # the packet first: explore.json is the commit
    _save(slug, project, data)
    return {"slug": slug, "state": state, "root": _rel(folder, project), "next": next_step(project, slug), "packet_text": packet_text,
            "price_defect": defects[0] if defects else None}


def _narrow_door(slug: str) -> str:
    import person_words
    return person_words.door(f"{SCRIPT} narrow --slug {slug} [--story KEY] [--repo NAME] [--jql TEXT]")


def _answer_door(slug: str, token: str = "") -> str:
    import person_words
    return person_words.door(f"{SCRIPT} answer --slug {slug}" + (f" --token {token}" if token else ""))


def _scope_differs(slug: str, existing: dict) -> ExplorationRefused:
    return ExplorationRefused(f"exploration {slug} already reads stories {existing['stories']} repos {existing['repos_named']} jql "
                              f"\"{existing['jql']}\": to change what it reads run `{_narrow_door(slug)}`")


def _normal_word(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" .!'\"`")


def record_answer(project, slug: str, session: str, words_path=None, token=None, not_asked=False) -> dict:
    """Record the person's answer to the frame. Words equal to an offered token (`yes`, `stop`), or a `token` the conductor read
    from them, answer it; any other words are FREE: E0 stays asked, the words are kept, the conductor reads them. Code never turns
    free words into a token itself. `not_asked`: the recommended answer taken for a person who is away (`yes`, `asked: false`)."""
    import person_words
    if not exists(slug, project):
        raise _no_exploration(slug)
    if bool(words_path) == bool(not_asked):
        raise ExplorationRefused("say what the person answered: give exactly one of their words (`{_answer_door(slug)}`) or `--not-asked` "
                                 "(nobody was asked; the recommended answer `yes` is taken and the report says so)")
    if token is not None and token not in OFFERED:
        if token == NARROW:
            raise ExplorationRefused(f"`{NARROW}` needs what to narrow to: run `{_narrow_door(slug)}`")
        raise ExplorationRefused(f"`{token}` is not an answer of the frame: the answers are " + ", ".join(f"`{x}`" for x in OFFERED) +
                                 f"; for anything else give the person's words and no token: `{_answer_door(slug)}`")
    if token is not None and not_asked:
        raise ExplorationRefused("`--not-asked` takes the answer `yes` by itself: leave `--token` out")
    acquire(project, slug, session)
    data = load(slug, project)
    e0 = data["steps"]["E0"]
    if e0["status"] == "answered" and not words_path:
        raise ExplorationRefused(f"the frame is answered ({e0['answer_token']}): a new answer needs the person's words: "
                                 f"`{_answer_door(slug)}`")
    if not_asked and e0["words_refs"]:
        raise ExplorationRefused(f"the person already answered in words ({len(e0['words_refs'])} recorded): `--not-asked` would say nobody was asked. "
                                 f"Record the word they chose: `{_answer_door(slug, 'yes|stop')}`, or `{_narrow_door(slug)}`")
    now = _now()
    if not_asked:
        e0.update({"status": "answered", "answer_token": "yes", "asked": False, "answered_at": now})
    else:
        text = person_words.read(None, words_path, "--words")
        said = _normal_word(text)
        if token is not None and said in OFFERED and said != token:
            raise ExplorationRefused(f"the person's words are `{said}` but `--token {token}` says otherwise: the token is the word they chose; "
                                     "run again with the matching token, or with no token to hand the words to the conductor")
        copy = person_words.write_words(root(slug, project), "", WORDS_KIND, text)
        e0["words_refs"].append(_rel(copy, project))
        chosen = token or (said if said in OFFERED else None)
        if chosen:
            e0.update({"status": "answered", "answer_token": chosen, "answered_at": now})
    _save(slug, project, data)
    nxt = next_step(project, slug)
    if not_asked or chosen:
        return nxt
    # FREE words, whatever the frame's state (asked, or already answered stop/yes): the conductor reads THESE words (FR-8, AR-24, P22).
    # E0 keeps its status and token until the conductor runs `answer --token` or `narrow`.
    return {**nxt, "kind": "read", "step": "E0", "words": e0["words_refs"][-1]}


def narrow(project, slug: str, session: str, words_path, stories=None, repos=None, jql=None, clear=()) -> dict:
    """The command the `narrow` answer runs: replace what the exploration reads (a given flag replaces that field, an absent one keeps
    it, `clear` empties it), probe again, record E0 as answered with `narrow`. Prints no packet: the person has answered."""
    import person_words
    if not exists(slug, project):
        raise _no_exploration(slug)
    stories, repos, clear = _clean_stories(stories), _clean_names(repos), tuple(clear or ())
    jql_given = str(jql).strip() if jql is not None else None
    if not words_path:
        raise ExplorationRefused(f"narrowing is the person's word: give their words: `{_narrow_door(slug)}`")
    if not (stories or repos or jql_given is not None or clear):
        raise ExplorationRefused("say what to narrow to: `--story`, `--repo`, `--jql` or `--clear stories|repos|jql`")
    for field, flag, given in (("stories", "--story", stories), ("repos", "--repo", repos), ("jql", "--jql", jql_given)):
        if field in clear and given:
            raise ExplorationRefused(f"`{flag}` and `--clear {field}` both set the same field: give one of them")
    acquire(project, slug, session)
    data = load(slug, project)
    text = person_words.read(None, words_path, "--words")
    if stories:
        data["stories"] = stories
    if repos:
        data["repos_named"] = repos
    if jql_given is not None:
        data["jql"] = jql_given
    for field, key, empty in (("stories", "stories", []), ("repos", "repos_named", []), ("jql", "jql", "")):
        if field in clear:
            data[key] = empty
    data["probes"] = _probe(project, data["repos_named"])
    copy = person_words.write_words(root(slug, project), "", WORDS_KIND, text)
    data["steps"]["E0"].update({"status": "answered", "answer_token": NARROW, "answered_at": _now()})
    data["steps"]["E0"]["words_refs"].append(_rel(copy, project))
    _save(slug, project, data)
    return {"probes": data["probes"], "next": next_step(project, slug)}


def set_step(project, slug: str, step: str, status: str) -> None:
    """The ONE writer of the status of a step E1-E3 for the later nodes (`feature_map.py` on a passing check). The status must be one the
    table names for the step; a step past `pending` needs every earlier step done or partial and the frame answered with `yes` or
    `narrow`. It takes NO lock: it is called by the tools of a step, not by a session of the exploration."""
    table_steps = table()["steps"]
    if step not in table_steps:
        raise ExplorationRefused(f"`{step}` is not a step with a status: the steps are " + ", ".join(step_ids()))
    if status not in table_steps[step]["statuses"]:
        raise ExplorationRefused(f"`{status}` is not a status of {step}: its statuses are " + ", ".join(table_steps[step]["statuses"]))
    data = load(slug, project)
    if status != "pending":
        e0 = data["steps"]["E0"]
        if e0["status"] != "answered" or e0["answer_token"] not in ("yes", NARROW):
            raise ExplorationRefused(f"{step} cannot be {status}: the frame of {slug} is not answered with `yes` or `narrow`")
        for earlier in step_ids()[:step_ids().index(step)]:
            if data["steps"][earlier]["status"] not in ("done", "partial"):
                raise ExplorationRefused(f"{step} cannot be {status}: {earlier} of {slug} is {data['steps'][earlier]['status']}, not done")
    data["steps"][step]["status"] = status
    _save(slug, project, data)


# --- the next step and the brief ---------------------------------------------------------------------------------------
def _hit_repos(project, slug: str) -> list:
    """The repositories of `work/feature-hits.json` a scout is sent to: ready and with hits. Unreadable: a refusal that names the file."""
    path = root(slug, project) / "work" / "feature-hits.json"
    again = f"run `feature_hits.py search --exploration {slug}` again"
    found = hooklib.read_json(path, None, kind=dict)
    if found is None or not isinstance(found.get("repos"), list):
        raise ExplorationRefused(f"qa-factory/explorations/{slug}/work/feature-hits.json cannot be read (absent, not JSON, or no repos list): {again}")
    ready, out = table()["ready_repo_statuses"], []
    for row in found["repos"]:
        if not (isinstance(row, dict) and isinstance(row.get("repo"), str) and isinstance(row.get("hits_total"), int)
                and isinstance(row.get("status"), str)):
            raise ExplorationRefused(f"qa-factory/explorations/{slug}/work/feature-hits.json has a repos row with no repo, status or hits_total: {again}")
        if row["status"] in ready and row["hits_total"] > 0:
            if not hooklib.is_one_component(row["repo"]):
                raise ExplorationRefused(f"the repository name `{row['repo']}` in work/feature-hits.json is not one path component: {again}")
            out.append(row["repo"])
    return out


def _step_command(step: str, slug: str, repo=None) -> str:
    return f"{SCRIPT} brief --slug {slug} --step {step}" + (f" --repo {repo}" if repo else "")


def next_step(project, slug: str) -> dict:
    """What happens next, read-only (no lock): `{kind, slug, step, run, role, repo, brief, packet, words}` with absent parts None.
    Kinds: ask, read, stopped, run, dispatch, done. The first action of the first step not yet done or partial that is not satisfied
    (a `run` and a `dispatch` by their file; a `check` is printed while the step is pending - the check sets the status)."""
    data = load(slug, project)
    folder, steps = root(slug, project), table()["steps"]
    out = {"kind": None, "slug": slug, "step": None, "run": None, "role": None, "repo": None, "brief": None, "packet": None, "words": None}
    e0 = data["steps"]["E0"]
    refs = e0["words_refs"]
    if e0["status"] == "asked":
        if refs:
            return {**out, "kind": "read", "step": "E0", "words": refs[-1]}
        return {**out, "kind": "ask", "step": "E0", "packet": _rel(_packet_path(slug, project), project)}
    if e0["answer_token"] == "stop":
        return {**out, "kind": "stopped", "step": "E0", "words": refs[-1] if refs else None}
    for step in step_ids():
        if data["steps"][step]["status"] in ("done", "partial"):
            continue
        for action in steps[step]["actions"]:
            if action["kind"] == "check":
                return {**out, "kind": "run", "step": step, "run": action["run"].replace("{slug}", slug)}
            if action["kind"] == "run":
                if not (folder / action["writes"]).is_file():
                    return {**out, "kind": "run", "step": step, "run": action["run"].replace("{slug}", slug)}
                continue
            repos = _hit_repos(project, slug) if action.get("per_repo") else [None]
            for repo in repos:
                if not (folder / action["writes"].replace("{repo}", repo or "")).is_file():
                    return {**out, "kind": "dispatch", "step": step, "role": action["role"], "repo": repo,
                            "brief": _step_command(step, slug, repo)}
    return {**out, "kind": "done", "run": f"{SCRIPT} finish --slug {slug}"}


def next_lines(nxt: dict) -> list:
    """The `next` dict as lines; every line starts with one of ask: read: stopped: run: dispatch: brief: done:."""
    slug, kind = nxt["slug"], nxt["kind"]
    if kind == "ask":
        return [f"ask: {nxt['packet']}"]
    if kind == "read":
        return [f"read: {nxt['words']} (the person answered in their own words: read them, then run `{_narrow_door(slug)}`, "
                f"or answer with the word they chose: `{_answer_door(slug, 'yes|stop')}`)"]
    if kind == "stopped":
        return [f"stopped: the person answered stop at the frame (to go on after all, with their new words: "
                f"`{_answer_door(slug, 'yes')}`)"]
    if kind == "run":
        return [f"run: {nxt['run']}"]
    if kind == "dispatch":
        return [f"dispatch: {nxt['role']} {nxt['step']}" + (f" {nxt['repo']}" if nxt["repo"] else ""), f"brief: {nxt['brief']}"]
    return [f"done: {nxt['run']}"]


def brief(project, slug: str, step: str, repo_id=None) -> str:
    """The brief a role is dispatched with for E1-E3: the label line first and once, the step, the feature on ONE line, every path the
    role needs (FR-15), the mode it reads and its budget. E2 names the repository and refuses one that has no hits."""
    data = load(slug, project)
    steps = table()["steps"]
    if step == "E0":
        raise ExplorationRefused("E0 has no dispatch: the person answers the frame packet")
    if step not in steps:
        raise ExplorationRefused(f"`{step}` is not a step: the steps with a dispatch are " + ", ".join(step_ids()))
    action = next((a for a in steps[step]["actions"] if a["kind"] == "dispatch"), None)
    if action is None:
        raise ExplorationRefused(f"{step} has no dispatch in the table")
    if bool(action.get("per_repo")) != bool(repo_id):
        raise ExplorationRefused(f"{step} " + ("is read one repository at a time: add `--repo <name>`, a repository with hits in "
                                               "work/feature-hits.json" if action.get("per_repo") else "is not read per repository: leave `--repo` out"))
    if repo_id and repo_id not in _hit_repos(project, slug):
        raise ExplorationRefused(f"`{repo_id}` is not a repository with hits in work/feature-hits.json of {slug}: run "
                                 f"`{SCRIPT} next --slug {slug}` to see which repositories are open")
    base = _rel(root(slug, project), project)
    lines = [f"{table()['label']} {slug}", f"Step: {step}", f"Feature: \"{collapse(data['phrase'])}\"", f"Root: {base}"]
    if repo_id:
        lines.append(f"Repository: {repo_id}")
    lines += [f"Input: {base}/{path}" for path in steps[step]["inputs"]]
    lines.append(f"Output: {base}/" + action["writes"].replace("{repo}", repo_id or ""))
    lines += [f"Mode: references/explore-modes.md, section \"{action['role']} {step}\"",
              f"Budget: {limit('e2_files_per_scout')} files, {limit('turns_per_scout')} turns"]
    return "\n".join(lines) + "\n"
