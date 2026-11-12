#!/usr/bin/env python3
"""The onboarding probe of the test command (B-220, part 1): does each profile's command leave a report the factory
can read - and when it does not, what is the cure, and does the person say yes to it?

TP2-2553: Karma ran with no JUnit reporter, the profile said the run writes a report, and the factory found
out inside S5, after the approval. The owner's ruling of 03.10: the test command is recorded at onboarding, and right
there the factory PROBES it; when it needs a change for the factory it proposes the fix in words ("I propose to run it
as: `<command>`. Do it?") and applies it only on the person's yes; when it does not know the fix, the LLM explains the
situation and asks how to proceed (FR-50's three answers). Gate A keeps its reporter card as the safety net.

    onboarding_probe.py --root . --probe-profiles --proposals-dir <a folder OUTSIDE the project> [--profile ID ...] --json
    onboarding_probe.py --root . --profile ID --command "<the person's line>" [--kind junit-xml|trx] --proposals-dir <dir> --json
    onboarding_probe.py --question <sealed proposal>        # the sentence to ask, RENDERED FROM THE SEALED FILE (F4)

stdout is ONE JSON object for the first two (FR-14; progress lines go to stderr), the sentence as text for the third.
The probe writes nothing into the project but the durable proven-rehearsal record (`qa-factory/state/
reporter-rehearsals.json`, which gate A reads): a sealed proposal goes to the folder the caller names, which may not be
inside the project (FR-45). A change to config.json is never written here - every write is `config_contract.py
--record-approval` and `--apply` (`apply_plan`), on the person's recorded yes.

The steps are the gate A rehearsal's own (`gate_preflight.Rehearsal`): the same collect, the same test choice, the same
run, the same reading of the report - imported, not copied (FR-17: one proof, two moments). What this module adds:

  * the CANDIDATE probe: a cure is probed on a copy of the config in memory BEFORE it is proposed, and it must also pass S5's
    command contract (`execution_request._command_from_profile` and the `{report_path}` rules): a command the probe
    reads and S5 would refuse is not proven (F1, FR-59). No "Do it?" is ever shown for such a command;
  * ONE proposal per profile, sealed when it is asked (F2): the next profile's proposal is made only after this one's
    answer is applied or refused, against the config as it is then, so none is ever stale;
  * the durable record keyed WITHOUT the stand (the reporter proof is a property of the command on this machine) and
    carrying the argv it proved, so gate A can say "the command changed" or "it stopped working" (F11).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_contract as C  # noqa: E402
import gate_preflight as G  # noqa: E402
import report_cures as RC  # noqa: E402

CHECK = "s5_reporter"
STATES = ("proven", "no_report", "timed_out", "launcher_missing", "no_test", "not_checked")
# what the skill does next, per probe result (FR-42: every state has a move)
MOVES = ("nothing", "do_it", "explain_and_ask", "tell", "waits_for_turn")
SHELL_WORDS = ("&&", "||", "|", ";", "&", ">", ">>", "<", "2>", "2>&1")
QUESTION_KEYS = ("intro_cure", "intro_person", "report_path_note", "propose_text", "change_note", "kind_note", "env_note", "answer_block")


# --- the cure table (references/report-cures.json) -----------------------------------------------------------------

def _row_problem(row) -> str:
    """Why this row of the cure table cannot be used, or ''."""
    if not isinstance(row, dict):
        return "a row is not an object"
    name = f"row `{row.get('id')}`"
    if not (isinstance(row.get("id"), str) and row["id"].strip()):
        return "a row has no `id`"
    match = row.get("match")
    if not (isinstance(match, list) and match and all(isinstance(t, str) and t.strip() for t in match)):
        return f"{name}: `match` must list at least one framework word"
    if not isinstance(row.get("words"), str):
        return f"{name}: `words` must be text (empty when the runner equips the framework itself)"
    for key in ("flag", "needs"):
        if not (isinstance(row.get(key), list) and all(isinstance(t, str) and t.strip() for t in row[key])):
            return f"{name}: `{key}` must be a list of words"
    if not isinstance(row.get("person_words"), str) or (row["words"].strip() and not row["person_words"].strip()):
        return f"{name}: `person_words` (the cure told to a person, with no flag in it) is required wherever `words` is"
    add = row.get("add_argv")
    if add is not None:
        if not (isinstance(add, list) and add and all(isinstance(t, str) and t.strip() for t in add)):
            return f"{name}: `add_argv` must be null or a non-empty list of words"
        if row.get("reporter_kind") not in C.REPORT_KINDS:
            return f"{name}: a cure that adds words must say which report it writes (`reporter_kind`: {', '.join(C.REPORT_KINDS)})"
        if not (isinstance(row.get("propose_text"), str) and "{command}" in row["propose_text"]):
            return f"{name}: a cure that adds words needs a `propose_text` carrying `{{command}}`"
    elif row.get("reporter_kind") not in (None, *C.REPORT_KINDS):
        return f"{name}: `reporter_kind` must be null, {' or '.join(C.REPORT_KINDS)}"
    add_env = row.get("add_env")
    if add_env is not None:
        # a variable the cure sets is one change of the command only beside the words it adds: `classify_cure` reads `add_env`
        # on the `add_argv` branch, and `reporter_kind` / `propose_text` are checked only there (EP1-22)
        if not add:
            return f"{name}: `add_env` goes with a non-empty `add_argv` (a cure that sets a variable is one change of the command)"
        import profile_contract as PC     # the ONE reader of an `env` (EP1-22, AR-13)
        _held, env_problem = PC.command_env({"env": add_env})
        if env_problem or not add_env:
            return f"{name}: `add_env` must be null or a non-empty object of variable name to exactly {{report_path}}" + (
                f" ({env_problem})" if env_problem else "")
    return ""


def cure_table(path=None) -> tuple:
    """(table, why). `table` is {"question": {...}, "rows": [...]} - the usable rows only. `why` is '' when the whole file
    could be read, else a sentence a person can be given: "the cure table could not be read: <why>" for a file that cannot
    be read at all (no cure is then known: the probe falls to the explaining question, FR-1), or a line naming the rows
    left out. A broken row never blinds the others."""
    empty = {"question": {}, "rows": []}
    try:
        data = RC.load(path)            # the ONE reader of the file (report_cures.py)
    except RC.CureTableUnreadable as exc:
        return empty, str(exc)
    question = data.get("question")
    if not (isinstance(question, dict) and all(isinstance(question.get(k), str) and question[k].strip() for k in QUESTION_KEYS)):
        return empty, "the cure table could not be read: its `question` text is incomplete (it needs " + ", ".join(QUESTION_KEYS) + ")"
    good, bad = [], []
    for row in data["rows"]:
        problem = _row_problem(row)
        (bad if problem else good).append(problem or row)
    return ({"question": question, "rows": good},
            ("the cure table has rows the probe cannot use, left out: " + "; ".join(bad)) if bad else "")


# The matching rule and the words are ONE implementation, in the leaf `report_cures` (FR-13: one home of the words). These names
# stay here as the same callables - `run_suite.report_cure` reads through that leaf too, so the runner, gate A's card and the
# probe say the same words by construction. (`cure_words(argv, table)` takes a table already read; with none it reads the file.)
row_for = RC.row_for
cure_words = RC.cure_words


def _pairs(words) -> list:
    """The cure's words as (option name, value, shape): `--a=b` is ("--a", "b", "eq"), `--a b` is ("--a", "b", "sep"), a bare
    `--a` is ("--a", None, "bare"), a loose word is (None, word, "word"). Options are matched by NAME (F6)."""
    words, out, i = [str(w) for w in words], [], 0
    while i < len(words):
        word = words[i]
        if word.startswith("-") and "=" in word:
            out.append((word.split("=", 1)[0], word.split("=", 1)[1], "eq"))
        elif word.startswith("-") and i + 1 < len(words) and not words[i + 1].startswith("-"):
            out.append((word, words[i + 1], "sep"))
            i += 1
        elif word.startswith("-"):
            out.append((word, None, "bare"))
        else:
            out.append((None, word, "word"))
        i += 1
    return out


def _occurrences(argv, name) -> list:
    """[(index of the word holding the option, its value or None, shape)] of every place `name` stands in `argv`."""
    found = []
    for i, word in enumerate(argv):
        if word.startswith(name + "="):
            found.append((i, word.split("=", 1)[1], "eq"))
        elif word == name:
            nxt = argv[i + 1] if i + 1 < len(argv) and not str(argv[i + 1]).startswith("-") else None
            found.append((i, nxt, "sep" if nxt is not None else "bare"))
    return found


def merge_cure(argv, add) -> tuple:
    """(the command with the cure in, the option names whose value it CHANGED, whether it changed anything at all).

    By the option's NAME, never by the exact run (F6): an option already there with the same value is left alone (the cure's
    own flag, `--reporter=junit`, is never written twice); an option there with ANOTHER value has that value replaced in place
    (the first place it stands); an option not there is added, with the loose words, before a bare `--`."""
    argv, changed, missing = [str(a) for a in argv], [], []
    for name, value, shape in _pairs(add):
        if name is None:
            if value not in argv:
                missing.append(value)
            continue
        places = _occurrences(argv, name)
        if any(v == value for _i, v, _s in places):
            continue
        if not places:
            missing.extend([f"{name}={value}"] if shape == "eq" else [name] + ([value] if value is not None else []))
            continue
        i, was, form = places[0]
        if form == "eq" or value is None:
            argv[i] = name if value is None else f"{name}={value}"
        elif form == "sep":
            argv[i + 1] = value
        else:                                           # a bare option that now takes a value
            argv[i:i + 1] = [f"{name}={value}"] if shape == "eq" else [name, value]
        changed.append(name)
    return with_added(argv, missing), changed, bool(missing or changed)


def _flag_state(argv, flag) -> str:
    """`same` (every option of the cure is in the command with the cure's value), `other` (one is there with another value),
    `absent` (the rest)."""
    pairs = [p for p in _pairs(flag) if p[0] is not None]
    if not pairs:
        return "absent"
    states = []
    for name, value, _shape in pairs:
        places = _occurrences([str(a) for a in argv], name)
        states.append("same" if any(v == value for _i, v, _s in places) else "other" if places else "absent")
    return "same" if all(s == "same" for s in states) else "other" if "other" in states else "absent"


def with_added(argv, add) -> list:
    """`argv` with `add` put before a bare `--` (what follows it belongs to the inner runner), else at the end."""
    argv = [str(a) for a in argv]
    cut = argv.index("--") if "--" in argv else len(argv)
    return argv[:cut] + list(add) + argv[cut:]


def _one_test_argv(profile) -> list:
    import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
    return PC.one_test_argv(profile)[0]      # a shape it cannot read has no argv here: the cure is `unknown`, not a crash


def _direct_form_note(profile) -> str:
    """The words for a profile whose one-test command is the project's OWN script (no known run form, not pytest): the factory
    reads no script, so per-test selection and the probe stay "not probed" on it, by name (B-6). `launch_check.runner_identity`
    is the one reader (AR-13); "" for a command it knows, one it cannot read, or a profile with no command."""
    import launch_check
    return str(launch_check.runner_identity(_one_test_argv(profile))["no_direct_form"] or "")


def classify_cure(profile, rows) -> dict:
    """What can be done about a profile whose run left no report: {action, row, candidate}.

    `unknown` (no row names this framework), `diagnosis` (the runner equips it itself: a missing report has another cause and
    there is no flag to add), `explain` (the cure is not one argv change: a package, a config edit, an environment variable),
    `dependency_only` (the flag is ALREADY in the command and only what it needs is missing: no second flag is added),
    `present` (the flag is in and nothing it needs is missing, yet no report comes out), `kind_conflict` (the cure writes
    one report kind and the profile says another: a recorded kind is not overwritten), `add` (a one-flag cure: `candidate`
    is the command with it, `changed` the option names whose value it REPLACES - an option already in the command is matched by
    its name and never written twice, F6). `dependency_only` / `present` are the cure's options being ALREADY the command: its
    words in the `argv` AND its variables (`add_env`) in the `env`. On `add`, `candidate_env` is the `env` the cured command carries
    (the variables it has plus the cure's), or None when the cure sets none (the command's `env` is then left as it is)."""
    argv = _one_test_argv(profile)
    row = row_for(argv, rows)
    if row is None:
        return {"action": "unknown", "row": None, "candidate": None, "changed": []}
    if not row["words"]:
        return {"action": "diagnosis", "row": row, "candidate": None, "changed": []}
    if row["add_argv"] is None:
        if _flag_state(argv, row["flag"]) == "same":
            return {"action": "dependency_only" if row["needs"] else "present", "row": row, "candidate": None, "changed": []}
        return {"action": "explain", "row": row, "candidate": None, "changed": []}
    candidate, changed, anything = merge_cure(argv, row["add_argv"])
    # EP1-22: the cure's variables are part of the command. The flag may be there and the variable not (a command that asks for
    # the report and never names its file): that is still ONE change, so `add`, never `present`.
    import profile_contract as PC     # the ONE reader of an `env` (AR-13)
    env_now = PC.command_env(PC.profile_command(profile, "one_test")[0])[0]
    add_env = row.get("add_env") or {}
    if any("{report_path}" in w for w in candidate) or any(v == PC.REPORT_HOLDER for v in env_now.values()):
        add_env = {}        # a holder is already there (a word, or a variable of the command): a second one is refused by S5 for ever
    env_missing = {k: v for k, v in add_env.items() if env_now.get(k) != v}
    if not anything and not env_missing:   # every option of the cure is in the command with the cure's value: "already the command"
        return {"action": "dependency_only" if row["needs"] else "present", "row": row, "candidate": None, "changed": []}
    declared = (profile.get("reporter") or {}).get("kind") if isinstance(profile.get("reporter"), dict) else None
    if declared not in (None, "") and declared != row["reporter_kind"]:
        return {"action": "kind_conflict", "row": row, "candidate": None, "changed": []}
    return {"action": "add", "row": row, "candidate": candidate, "changed": changed,
            "candidate_env": ({**env_now, **add_env} if add_env else None)}


# --- the S5 contract: a command the probe reads and S5 refuses is not proven (F1) ---------------------------------

def s5_contract_refusals(root, profile) -> list:
    """The reasons S5 would refuse the command of this profile, in words; [] when it would take it.

    S5 builds the command from the profile (`execution_request._command_from_profile`) and `validate_request` demands, for a
    junit-xml or trx report, EXACTLY ONE word of the command carrying `{report_path}` (whole, or embedded as in `trx;
    LogFileName={report_path}`) - and `run_suite` replaces it inside that word, as the gate's probe does. A command whose
    report kind is `none` is read by nobody: S5 would record every run as not executed. Error direction: toward REFUSING -
    a contract that cannot be read refuses (a command is never called proven on a guess). A test holds this function and
    `validate_request` to the same answer (the twin test), so the two cannot drift apart unseen."""
    try:
        import execution_request as ER
    except Exception as exc:     # noqa: BLE001 - the direction is "refuse"
        return [f"S5's command contract could not be read ({type(exc).__name__}: {exc}), so no command can be called proven"]
    try:
        command = ER._command_from_profile(profile)
    except ER.RequestError as exc:
        return [str(exc)]
    out = []
    reporter, words = command["reporter"], [str(w) for w in command["argv"]]
    if reporter == "none":
        out.append("S5 would read no report from this command: the profile names no report kind and the command is not pytest, "
                   "so every run would be recorded as not executed. Say which report it writes (junit-xml or trx)")
    elif reporter in ("junit-xml", "trx"):
        # the words of the argv AND the values of the command's `env` (EP1-22): the same count `validate_request` makes
        env_values = [str(v) for v in (command.get("env") or {}).values()]
        holders = [w for w in words + env_values if "{report_path}" in w]
        if not holders:
            out.append(f"S5 would refuse this command: its report kind is `{reporter}` and no word of it carries `{{report_path}}`, "
                       "the place the factory reads the report from, and no value of the command's `env` does. Put it in exactly one "
                       "word (`{report_path}` alone, or inside a word such as `trx;LogFileName={report_path}`) or in one value of `env`")
        elif len(holders) > 1:
            out.append("S5 would refuse this command: `{report_path}` stands in more than one word or value of it (" + ", ".join(
                f"`{w}`" for w in holders) + "), which would write two reports under one name. Keep it in exactly one word or value")
    cwd = Path(root) / str(command.get("cwd") or ".")
    if not cwd.is_dir():
        out.append(f"S5 would refuse this command: the folder it runs in (`{command.get('cwd')}`) is not in the project")
    return out


# --- the rehearsal, as the onboarding runs it -------------------------------------------------------------------------

class ProbeRehearsal(G.Rehearsal):
    """The gate A rehearsal over EVERY profile of the config, no story, with what each profile's reporter step did captured
    as data (so no state is read out of a sentence). Two differences from the gate, both on purpose: the durable proven
    record is keyed WITHOUT the stand and carries the argv it proved (F11), and a candidate (`durable=False`) neither reads
    nor writes that record - a cure is measured, never remembered, until the person said yes and the confirmation ran."""
    SHARED_ROOT_PICKS_NOTHING = False   # a probe learns a command's report; any test under the root serves (EP1-10)

    def __init__(self, project_root, config=None, durable: bool = True):
        super().__init__(Path(project_root), "A")
        if config is not None:
            self.config = config
        self.durable = durable
        self.captured = None        # what `_probe_reporter` returned, with the command it ran
        self.reused = None          # the durable row a proven rehearsal was reused from
        self.chosen = ""            # the test it chose
        self.proved_argv: list = []

    def keyed_profiles(self) -> dict:
        return {str(p["profile_id"]): {"cases": [], "keyed_on": "the onboarding probes every profile of the configuration"}
                for p in (self.config.get("profiles") or []) if isinstance(p, dict) and p.get("profile_id")}

    def _selected_environment(self) -> dict:
        # F11: the proof that a command writes a readable report is a property of the command on this machine, not of a stand;
        # at onboarding there is no pipeline to name one, so with two or more stands a stand-keyed proof would never be reused
        return {}

    def _observed_identity(self, profile_id: str, root) -> str:
        # F11: nor of what a stand runs. The proof is a property of the command on this machine, not of a stand or an image, and
        # onboarding has no story identity: a key that held one would never match at gate A. So no stand is asked (no run).
        return ""

    def _rehearsal_key(self, profile_id, cwd, argv, chosen, fmt, identity, root) -> str:
        self.proved_argv, self.chosen = [str(a) for a in argv], chosen
        if not self.durable:
            return ""           # "not durable": never matches, never recorded (the base reads '' that way)
        key = super()._rehearsal_key(profile_id, cwd, argv, chosen, fmt, "", root)
        hit = (getattr(self, "_rehearsals", None) or {}).get(key) if key else None
        if isinstance(hit, dict) and isinstance(hit.get("at"), str):
            self.reused = hit
        return key

    def _probe_reporter(self, launch, cwd, timeout, report, fmt, env=None) -> dict:
        outcome = (super()._probe_reporter(launch, cwd, timeout, report, fmt, env=env) if env
                   else super()._probe_reporter(launch, cwd, timeout, report, fmt))
        self.captured = {"outcome": outcome, "launch": [str(t) for t in launch], "fmt": fmt}
        return outcome

    def _record_rehearsal(self, check, durable, profile_id, chosen, fmt, identity, tests) -> None:
        super()._record_rehearsal(check, durable, profile_id, chosen, fmt, identity, tests)
        rows = getattr(self, "_rehearsals", None) or {}
        if durable in rows:
            # what the proof was OF: gate A tells "the command changed" from "it stopped working" by this (F11)
            rows[durable].update({"argv": list(self.proved_argv), "argv_digest": argv_digest(self.proved_argv),
                                  "source": "onboarding"})
            try:
                from event_store import atomic_json
                atomic_json(self._rehearsals_path(), {"schema_version": 1, "rehearsals": rows})
            except Exception:    # noqa: BLE001 - the base already said the file could not be saved
                pass


def argv_digest(argv) -> str:
    """The digest of a command's WORDS. Callers pass the command's IDENTITY (`profile_contract.command_identity`, EP1-22 B-2): the
    argv words, and after them the `env` when the command sets one - so this stays the one definition and a command without an
    `env` keeps the digest it always had."""
    return hashlib.sha256(json.dumps([str(a) for a in argv], ensure_ascii=False).encode("utf-8")).hexdigest()


def earlier_proof(project_root, profile_id, argv) -> dict:
    """What the durable record says about THIS command of this profile: `same_command` (a row proved exactly this argv),
    `command_changed` (rows of the profile exist, none for this argv: the command is not the one that was proven), `none` (no
    row of this profile carries an argv: nothing was proven before, or only by gate A's own older rows) or `unreadable`.
    `at` is the day of the newest row. Gate A reads it to say "it wrote a report on <date>; now it does not" for the SAME
    command and "the command changed since" for another - two different sentences (F11, FR-41: "no longer" only on a record)."""
    path = Path(project_root) / "qa-factory" / "state" / G.REPORTER_REHEARSALS_FILE
    if not path.is_file():
        return {"state": "none", "at": ""}
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("rehearsals")
        if not isinstance(rows, dict):
            raise ValueError("no `rehearsals` map")
    except Exception:      # noqa: BLE001 - an unreadable record proves nothing
        return {"state": "unreadable", "at": ""}
    mine = sorted((r for r in rows.values() if isinstance(r, dict) and r.get("profile_id") == profile_id
                   and isinstance(r.get("argv_digest"), str)), key=lambda r: str(r.get("at") or ""))
    if not mine:
        return {"state": "none", "at": ""}
    digest = argv_digest(argv)
    same = [r for r in mine if r["argv_digest"] == digest]
    return {"state": "same_command" if same else "command_changed", "at": str((same or mine)[-1].get("at") or "")[:10]}


def _tail(outcome: dict) -> str:
    return " ".join(str(outcome.get("stderr") or outcome.get("stdout") or "").split())[-400:]


def _probe_one(rehearsal: ProbeRehearsal, profile: dict, root: Path, timeout: int, declared) -> dict:
    """One profile's report step, as data: {state, why, detail, test, returncode, launcher}."""
    pid = str(profile["profile_id"])
    cfg = rehearsal.config.get("gate_rehearsal") if isinstance(rehearsal.config.get("gate_rehearsal"), dict) else {}
    if cfg.get("skip_reporter"):
        return {"state": "not_checked", "why": "the project's own settings turn the report rehearsal off", "detail": ""}
    if not _one_test_argv(profile):
        return {"state": "not_checked", "why": "the profile records no command that runs one test", "detail": ""}
    rehearsal.captured, rehearsal.reused, rehearsal.chosen = None, None, ""
    before = len(rehearsal.findings)
    G._REPORTER_PROBES.clear()      # the per-process cache would hand back an earlier run: an onboarding probe measures NOW
    temp = Path(tempfile.mkdtemp(prefix="qa-onboarding-reporter-"))
    try:
        rehearsal._rehearse_reporter(CHECK, pid, {"cases": [], "keyed_on": "onboarding"}, profile, root, temp, timeout, declared)
    except Exception as exc:        # noqa: BLE001 - P1: the probe says what it could not do and goes on
        return {"state": "not_checked", "why": f"the probe could not run ({type(exc).__name__}: {str(exc)[:160]})", "detail": ""}
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    if rehearsal.reused is not None:
        return {"state": "proven", "why": "reused: a run of exactly this command already left a report the factory can read, on "
                f"{str(rehearsal.reused.get('at'))[:10]}", "detail": "", "test": rehearsal.chosen, "reused": True}
    got = rehearsal.captured
    if got is not None:
        outcome = got["outcome"]
        if outcome.get("launcher_missing"):
            import project_env
            return {"state": "launcher_missing", "why": project_env.head_not_found((got["launch"] or ["?"])[0]), "detail": "",
                    "test": rehearsal.chosen, "launcher": (got["launch"] or [""])[0]}
        if outcome.get("timed_out"):
            return {"state": "timed_out", "why": f"one test did not finish within {timeout} s", "detail": "", "test": rehearsal.chosen}
        if outcome.get("tests"):
            return {"state": "proven", "why": f"{outcome['tests']} test(s) counted from the report", "detail": "",
                    "test": rehearsal.chosen, "returncode": outcome.get("returncode")}
        detail = _tail(outcome)
        if got["fmt"] == "pytest":
            detail = G.collect_failure(str(outcome.get("stdout") or ""), str(outcome.get("stderr") or "")) or detail
        return {"state": "no_report", "why": str(outcome.get("why") or "no report file was written"), "detail": detail,
                "test": rehearsal.chosen, "returncode": outcome.get("returncode"), "format": got["fmt"]}
    if len(rehearsal.findings) > before:
        # the card's closed code (HF8-14): the last finding of THIS call says why nothing was chosen; an unknown or empty code keeps the old words
        code = next((str(f.get("why_empty") or "") for f in reversed(rehearsal.findings[before:]) if f.get("check") == CHECK), "")
        why = ("the gate's collect listed tests, none under this profile's folder" if code == "nothing_under_profile"
               else "there is no existing test to run through this command")
        return {"state": "no_test", "why": why, "detail": ""}
    note = next((n["message"] for n in reversed(rehearsal.info) if n.get("check") == CHECK), "")
    return {"state": "not_checked", "why": note or "the probe did not run this profile", "detail": ""}


def _timeout_of(config: dict) -> int:
    cfg = config.get("gate_rehearsal") if isinstance(config.get("gate_rehearsal"), dict) else {}
    try:
        return int(cfg.get("reporter_timeout_s") or 180)
    except Exception:       # noqa: BLE001
        return 180


def _progress(text: str) -> None:
    print(f"onboarding_probe: {text}", file=sys.stderr, flush=True)       # FR-43; stdout stays one JSON object (FR-14)


# --- the candidate probe -----------------------------------------------------------------------------------------------

def probe_candidate(project_root, profile_id, argv, kind=None, *, config=None, collect_stdout: str = "",
                    timeout: int | None = None, env=None) -> dict:
    """Is THIS command of THIS profile proven - by the probe AND by S5's contract? -> {proven, state, why, detail, ...}.

    Pure with respect to the project: the candidate lives in a copy of the config in memory, the report goes to the OS temp,
    and nothing durable is read or written (`ProbeRehearsal(durable=False)`). `kind` is the report kind to set beside the
    command (junit-xml or trx); None keeps the profile's own. The order is the invariant: S5's contract FIRST (a command it
    refuses is not run at all), then one run; `proven` is true only when both agree. A state that is not `proven` carries its
    reason in words and never an exit code.

    `env` (EP1-22): the variables the candidate command sets (each exactly `{report_path}`). None = leave the `env` the spec has
    as it is - EXCEPT that a command whose own words carry `{report_path}` drops it (two holders would be refused by S5 for ever:
    M-4); a dict sets it, `{}` takes it out. The result carries `env_change`: None when the candidate's `env` is the spec's own,
    else the dict the proposal must seal (`{}` = taken out)."""
    root = Path(project_root).resolve()

    def no(state: str, why: str, detail: str = "") -> dict:
        return {"proven": False, "state": state, "why": why, "detail": detail, "contract": [why] if state == "refused_by_s5" else []}

    try:
        current = config if config is not None else C.read_config_file(root)
    except C.ConfigUnreadable as exc:
        return no("not_checked", str(exc))
    if current is None:
        return no("not_checked", "there is no qa-factory/config.json to probe a command of")
    candidate = copy.deepcopy(current)
    _index, profile = C._profile_slot(candidate, profile_id)
    if profile is None:
        return no("not_checked", f"the profile `{profile_id}` is not in qa-factory/config.json")
    if not (isinstance(argv, (list, tuple)) and argv and all(isinstance(a, str) and a.strip() for a in argv)):
        return no("not_checked", "a command is a non-empty list of words")
    if kind is not None and kind not in C.REPORT_KINDS:
        return no("not_checked", f"the report kind is one of: {', '.join(C.REPORT_KINDS)}")
    import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
    _held, problem = PC.profile_command(profile, "one_test")
    if problem:
        # a foreign shape is not "no commands" to be replaced by `{}` on the copy: the probe would prove a command of a
        # profile that is not the one the project holds (nothing is written here, but a proof is a claim)
        return no("not_checked", f"the profile `{profile_id}` cannot be probed: {problem}")
    commands = profile["commands"] = PC.profile_commands(profile)[0]     # absent or null: created on the copy, as it always was
    spec = commands.get("one_test")
    if not isinstance(spec, dict):
        spec = commands["one_test"] = {}
    env_before, env_problem = PC.command_env(spec)
    if env_problem:
        return no("not_checked", f"the profile `{profile_id}` cannot be probed: commands.one_test.{env_problem}")
    spec["argv"] = [str(a) for a in argv]
    if env is None and env_before and any("{report_path}" in a for a in spec["argv"]):
        env = {}            # the command carries the placeholder itself now: the profile's own `env` would be a second holder
    if env is not None:
        env_problem = PC.command_env({"env": env})[1]
        if env_problem:
            return no("not_checked", f"the variables of the command are not valid: {env_problem}")
        if env:
            spec["env"] = dict(env)
        else:
            spec.pop("env", None)
    env_change = None if (env is None or dict(env) == env_before) else dict(env)
    if kind is not None:
        reporter = profile.get("reporter") if isinstance(profile.get("reporter"), dict) else {}
        if reporter.get("kind") not in (None, "", kind):
            return no("not_checked", f"the profile already says its report is `{reporter.get('kind')}` and this command writes `{kind}`: "
                      "a recorded kind is not overwritten")
        reporter["kind"] = kind
        profile["reporter"] = reporter
    refusals = s5_contract_refusals(root, profile)
    if refusals:
        return no("refused_by_s5", "; ".join(refusals))
    rehearsal = ProbeRehearsal(root, candidate, durable=False)
    rehearsal.collect_stdout = collect_stdout
    cfg = candidate.get("gate_rehearsal") if isinstance(candidate.get("gate_rehearsal"), dict) else {}
    report = _probe_one(rehearsal, profile, root, timeout or _timeout_of(candidate), cfg.get("reporter_probe_test"))
    return {"proven": report["state"] == "proven", "contract": [], "env_change": env_change, **report}


# --- the question and the proposal --------------------------------------------------------------------------------------

def render_question(table: dict, profile_id: str, argv, source: str = "cure", row: dict | None = None,
                    changed=(), kind_new: bool = False, env=None) -> str:
    """The text the person is asked, from the cure table's own words (data, FR-13): why, the sentence `I propose to run
    the <profile> tests as: `<command>`. Do it? yes / no`, and the block that says how to answer. It is sealed into the
    proposal (`listing`), so the yes is bound to exactly these words (F4); the skill shows what `--question` prints from the
    sealed file. Every part obeys human-questions.md (a test runs `human_text.problems` on it, F6)."""
    q = table["question"]
    command = C.display_command(argv)
    sentence = str((row or {}).get("propose_text") or q["propose_text"])
    parts = [q["intro_person" if source == "command" else "intro_cure"], ]
    if "{report_path}" in command:
        parts.append(q["report_path_note"])
    if changed:         # F6: an option already in the command with another value is REPLACED, and the sentence says so
        parts.append(q["change_note"])
    if kind_new:        # F7: the same command with a report kind it did not carry before is a proposal of its own
        parts.append(q["kind_note"])
    if env:             # EP1-22: a variable the command sets is a part of what the person says yes to, and is said in words
        parts.append(q["env_note"])
    parts.append(sentence)
    text = "\n\n".join(parts) + "\n\n" + q["answer_block"] + "\n"
    names = " and ".join(f"`{name}`" for name in sorted(env or {}))
    return text.replace("{profile}", str(profile_id)).replace("{command}", command).replace("{variables}", names)


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(text))[:60] or "profile"


def _outside(root: Path, directory: Path) -> bool:
    try:
        Path(directory).resolve().relative_to(Path(root).resolve())
        return False
    except ValueError:
        return True


def _need_outside(root: Path, proposals_dir) -> None:
    """A folder for sealed proposals inside the project is refused, before anything runs: a proposal file there would be a
    trace of the probe in the project (FR-45), and a sealed file is not the project's."""
    if proposals_dir and not _outside(root, Path(proposals_dir)):
        raise ValueError("the folder for sealed proposals is inside the project, where a proposal file would be a trace of the "
                         "probe: name a folder outside it (a temporary folder)")


def _seal(root: Path, table: dict, profile_id: str, argv, reporter_kind, source: str, row, proposals_dir,
          changed=(), kind_new: bool = False, env=None) -> dict:
    """The sealed proposal of ONE changed command and where it went: {path, sealed (when no folder was named),
    approval_ref, proposal_hash, question, command}. `env` (EP1-22): None leaves the command's `env`, `{}` takes it out, a dict
    sets it; the question names the variables a dict sets."""
    _need_outside(root, proposals_dir)
    question = render_question(table, profile_id, argv, source, row, changed, kind_new, env)
    proposal = C.command_proposal(root, {"profile_id": profile_id}, list(argv), reporter_kind=reporter_kind,
                                  reason="probe cure" if source == "cure" else "person's command",
                                  kind=source, question=question, env=env)
    out = {"path": None, "approval_ref": C.command_approval_ref(proposal), "proposal_hash": proposal["proposal_hash"],
           "question": question, "command": C.display_command(argv)}
    if proposals_dir:
        if not _outside(root, Path(proposals_dir)):
            raise ValueError("the folder for sealed proposals is inside the project, where a proposal file would be a trace "
                             "of the probe: name a folder outside it (a temporary folder)")
        directory = Path(proposals_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{source}-{_safe_name(profile_id)}-{proposal['proposal_hash'][:12]}.json"
        path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        out["path"] = str(path)
    else:
        out["sealed"] = proposal
    return out


# --- the probe of every profile ----------------------------------------------------------------------------------------

def _says_no_report(pid: str, report: dict, cls: dict, why_table: str) -> str:
    # `detail` (the raw tail of the run's own stderr) is a CODE field: it never enters a sentence a person may be shown (F2)
    base = (f"one existing test ran through the `{pid}` command" + (f" ({report['test']})" if report.get("test") else "")
            + f" and left no report the factory can read ({report['why']})")
    row, action = cls["row"], cls["action"]
    if action == "diagnosis":
        return base + ". The runner already asks this framework for the report itself, so there is no flag to add: the report is "\
                      "missing for another reason, the one the run printed"
    if action == "unknown":
        return base + ". The cure table has no row for this kind of command" + (f" ({why_table})" if why_table else "")
    if action == "kind_conflict":
        return base + f". The usual cure writes a `{row['reporter_kind']}` report, and the profile already says another kind: " \
                      "a kind a person recorded is not overwritten"
    if action == "dependency_only":
        return base + ". The report flag is already in the command, so no second one is added; what is missing is: " + "; ".join(row["needs"])
    if action == "present":
        return base + ". The report flag the cure would add is already in the command and nothing it needs is missing, so the cause is elsewhere"
    if action == "explain":
        return (base + ". The cure is not one change of the command: " + row["words"]
                + (". It also needs " + "; ".join(row["needs"]) if row["needs"] else ""))
    return base


def left_out_files(info) -> list:
    """`[{"path", "head"}]` - the test files the gate's collect went on past (the `broken_files` of the `s5_toolchain` notes
    of a rehearsal's `info`), whole; [] when it left none out."""
    return [dict(b) for n in info or [] if n.get("check") == "s5_toolchain" for b in n.get("broken_files") or []]


def probe_profiles(project_root, proposals_dir=None, *, only=(), table_path=None, timeout: int | None = None) -> dict:
    """Probe each profile's command for a report the factory can read, and make ONE proposal when a cure is proven.

    -> {schema_version, profiles: [{profile, report: {state, why, detail, ...}, cure, proposal, move, says}], toolchain: [...],
    cure_table: <why not, or ''>, problem: <when nothing could be probed>, unknown_profiles: [...]}.

    `report.state` is one of STATES and `move` says what the skill does next (MOVES, FR-42): `nothing` (proven), `do_it` (a
    proposal is sealed: show `--question`, ask yes / no), `explain_and_ask` (no cure, or the cure did not prove: the LLM says
    what was run and what came out and offers FR-50's three answers), `tell` (one line: no test / timed out / launcher
    missing / not checked - gate A's card asks again at the first story), `waits_for_turn` (a cure is known, but another
    profile's proposal is open: it is made, against the config as it will be, once that one is answered).

    ONE proposal per profile, sealed when it is asked (F2): the first profile with a proven cure gets it; the others wait.
    After the answer is applied, call this again: the confirmation run of the first, the proposal of the next. `only` limits
    the probe to those profile ids (a profile whose "Do it?" the person declined is left out this way)."""
    root = Path(project_root).resolve()
    _need_outside(root, proposals_dir)
    out = {"schema_version": 1, "profiles": [], "toolchain": [], "cure_table": "", "unknown_profiles": []}
    try:
        config = C.read_config_file(root)
    except C.ConfigUnreadable as exc:
        out["problem"] = str(exc)
        return out
    if config is None:
        out["problem"] = ("there is no qa-factory/config.json yet, so there is no test command to probe: onboarding writes the "
                          "configuration first")
        return out
    table, why_table = cure_table(table_path)
    out["cure_table"] = why_table
    profiles = [p for p in (config.get("profiles") or []) if isinstance(p, dict) and p.get("profile_id")]
    wanted = [str(i) for i in (only or ())]
    if wanted:
        out["unknown_profiles"] = [i for i in wanted if i not in {str(p["profile_id"]) for p in profiles}]
        profiles = [p for p in profiles if str(p["profile_id"]) in wanted]
    if not profiles:
        out["problem"] = ("the configuration records no execution profile" if not wanted else
                          "none of the named profiles is in the configuration") + ", so there is no test command to probe"
        return out
    rehearsal = ProbeRehearsal(root, config, durable=True)
    rehearsal._rehearsals = rehearsal._load_rehearsals(CHECK)
    seconds = timeout or _timeout_of(config)
    _progress("collecting the project's existing tests")
    rehearsal.check_s5_toolchain()
    out["toolchain"] = [f["message"] for f in rehearsal.findings if f.get("check") == "s5_toolchain"]
    # RH1-3 (AR-22): the test files the collect went on past are a NOTE of the step, not a finding; the probe hands them on
    # (additive, FR-14: the key is there only when some file was left out) so the files found at onboarding are not dropped
    left_out = left_out_files(rehearsal.info)
    if left_out:
        out["broken_files"] = left_out
    cfg = config.get("gate_rehearsal") if isinstance(config.get("gate_rehearsal"), dict) else {}
    sealed_for = ""
    for profile in profiles:
        pid = str(profile["profile_id"])
        if profile.get("selected") is False:
            # a profile the project did not select never runs a story's tests: zero runs, said as `not_checked`
            out["profiles"].append({"profile": pid, "report": {"state": "not_checked", "why": "not selected", "detail": ""},
                                    "cure": None, "proposal": None, "move": "tell",
                                    "says": f"`{pid}`: the report was not checked: not selected"})
            continue
        _progress(f"running one existing test through the `{pid}` command")
        report = _probe_one(rehearsal, profile, root, seconds, cfg.get("reporter_probe_test"))
        entry = {"profile": pid, "report": report, "cure": None, "proposal": None, "move": "tell", "says": ""}
        direct = _direct_form_note(profile)
        if direct:
            entry["direct_form"] = {"says": direct}      # whatever the move: the profile's command is the project's own script (B-6)
        state = report["state"]
        if state == "proven":
            entry.update(move="nothing", says=f"`{pid}`: one existing test ran and left a report the factory can read ({report['why']})")
        elif state == "no_test":
            entry["says"] = "no existing test to prove the report with; the first story's gate checks it"
        elif state == "timed_out":
            entry["says"] = (f"one test of `{pid}` did not finish within {seconds} s, so whether it writes a report is unknown; "
                             "the first story's gate asks again")
        elif state == "launcher_missing":
            import project_env
            entry["says"] = f"{project_env.head_not_found(report.get('launcher'))}, so the report of `{pid}` is unproven; the launch check comes first"
        elif state == "not_checked":
            entry["says"] = f"`{pid}`: the report was not checked: {report['why']}"
        else:
            cls = classify_cure(profile, table["rows"])
            row = cls["row"]
            cure = {"id": row["id"] if row else None, "action": cls["action"], "words": row["words"] if row else "",
                    "person_words": row["person_words"] if row else "", "reporter_kind": row["reporter_kind"] if row else None,
                    "needs": list(row["needs"]) if row else [], "candidate": cls["candidate"], "candidate_command": None,
                    "changed": list(cls.get("changed") or []), "proven": None, "why_not": "", "why_short": "", "waits_for": ""}
            entry["cure"] = cure
            entry["move"] = "explain_and_ask"
            entry["says"] = _says_no_report(pid, report, cls, why_table)
            if cls["action"] == "add":
                cure["candidate_command"] = C.display_command(cls["candidate"])
                if sealed_for:
                    entry["move"] = "waits_for_turn"
                    entry["says"] += (f". A cure is known (`{cure['candidate_command']}`); it is proposed after the question about "
                                      f"`{sealed_for}` is answered, against the configuration as it will be then")
                    cure["why_not"] = f"waits for the answer about `{sealed_for}`"
                    cure["waits_for"] = sealed_for
                else:
                    _progress(f"proving the cure for `{pid}` before it is proposed")
                    got = probe_candidate(root, pid, cls["candidate"], row["reporter_kind"], config=config,
                                          collect_stdout=rehearsal.collect_stdout, timeout=seconds, env=cls.get("candidate_env"))
                    cure["proven"] = got["proven"]
                    if got["proven"]:
                        entry["proposal"] = _seal(root, table, pid, cls["candidate"], row["reporter_kind"], "cure", row, proposals_dir,
                                                  changed=cls.get("changed") or (), env=got.get("env_change"))
                        entry["move"] = "do_it"
                        sealed_for = pid
                    else:
                        cure["why_not"] = (f"the cure was run before it was proposed and did not prove: {got['why']}"
                                           + (f" ({got['detail']})" if got.get("detail") else ""))
                        cure["why_short"] = ("the factory's later test run would refuse the command with the cure in it"
                                             if got.get("state") == "refused_by_s5" else str(got["why"]))
                        entry["says"] += f". The cure was run before it was proposed and did not prove: {got['why']}"
        out["profiles"].append(entry)
    return out


def probe_person_command(project_root, profile_id, line, proposals_dir=None, kind=None, *, table_path=None,
                         timeout: int | None = None) -> dict:
    """The person's own command (FR-50 answer "here is the command that writes a JUnit report"): split, refused in words
    when it cannot be a command, probed as a candidate (S5's contract first), and, when proven, sealed as ONE proposal for
    the same "Do it?" - a person-given command is never written raw, it goes through the same approved path (F3).

    -> {profile, command, move, says, report, proposal}. `move`: `do_it` (sealed), `explain_and_ask` (the command did not
    prove: what came out), `refused` (the line is not a command the factory can run: why, in words), `nothing` (it is the
    command the profile already has)."""
    root = Path(project_root).resolve()
    _need_outside(root, proposals_dir)
    result = {"profile": str(profile_id), "command": None, "move": "refused", "says": "", "report": None, "proposal": None}
    try:
        config = C.read_config_file(root)
    except C.ConfigUnreadable as exc:
        result["says"] = str(exc)
        return result
    if config is None:
        result["says"] = "there is no qa-factory/config.json yet: onboarding writes it first"
        return result
    _i, profile = C._profile_slot(config, profile_id)
    if profile is None:
        result["says"] = f"the profile `{profile_id}` is not in the configuration"
        return result
    try:
        from stand_identity import command_argv
        argv = command_argv(str(line or ""))
    except ValueError as exc:
        result["says"] = f"the line cannot be split into a command ({exc}): close the quote and give it again"
        return result
    if not argv or not all(a.strip() for a in argv):
        result["says"] = "the line holds no command (or an empty word): give the command as you would type it"
        return result
    result["command"] = C.display_command(argv)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
        # a leading `NAME=value` is shell syntax: the factory runs a command without a shell, so the word would be run as the
        # program (EP1-22 M-4). Refused in words; never run, never read as a variable
        result["says"] = ("the factory runs a command without a shell, so a variable at the start of the line is not set this way; "
                          "give the command without it, and the factory sets that variable itself")
        return result
    shell = [a for a in argv if a in SHELL_WORDS]
    if shell:
        result["says"] = (f"the line uses `{shell[0]}`, which needs a shell; the factory runs a command without one. Give the "
                          "command itself, or put the pipeline in a script of the project and give that script")
        return result
    try:
        absolute = [a for a in argv if C._machine_local_value(a)]
    except Exception as exc:     # noqa: BLE001 - the direction is "refuse"
        result["says"] = f"the line could not be checked for places that exist only on this machine ({type(exc).__name__}: {exc})"
        return result
    if absolute:
        result["says"] = ("the line names " + ", ".join(f"`{a}`" for a in absolute) + ", a place that exists only on this machine, "
                          "and this file is shared with the team. Give it relative to the project, or through the project's own "
                          "launcher (`poetry run ...`, `npx ...`)")
        return result
    if kind is not None and kind not in C.REPORT_KINDS:
        result["says"] = f"the report kind is one of: {', '.join(C.REPORT_KINDS)}"
        return result
    declared = (profile.get("reporter") or {}).get("kind") if isinstance(profile.get("reporter"), dict) else None
    kind_new = kind is not None and kind != declared
    table, why_table = cure_table(table_path)
    # EP1-22 (M-4): a command of the person's with no placeholder of its own gets the variables of its cure row (`add_env`), so the
    # factory does for it what it does for its own cure; a command that carries the placeholder keeps none (the proposal takes the
    # profile's `env` out: `probe_candidate`). The door is live: without it S5 would refuse the person's command and the person
    # could set no variable (FR-2, FR-57).
    import profile_contract as PC
    env_now = PC.command_env(PC.profile_command(profile, "one_test")[0])[0]
    holder_in_argv = any("{report_path}" in a for a in argv)
    cure_row = row_for(argv, table["rows"]) if not holder_in_argv else None
    env_new = {**env_now, **cure_row["add_env"]} if cure_row and cure_row.get("add_env") else None
    if env_new is None and holder_in_argv and env_now:
        env_new = {}        # the same words, and the profile's saved `env` is a second holder: taking it out is a change, not "nothing"
    if argv == _one_test_argv(profile) and not kind_new and (env_new is None or env_new == env_now):
        # F7: the same words with a report kind the profile did not carry are NOT "already the command": that is a kind-only
        # proposal, below. The same words with the same kind (or none given) are.
        result.update(move="nothing", says=f"that is already the command of `{profile_id}`; nothing to change")
        return result
    if why_table.startswith("the cure table could not be read"):
        # the person's command does not need a cure row, but the sentence is made from the table's own words
        result["says"] = why_table + ", and the question to ask is made from it"
        return result
    _progress(f"running one existing test through the command given for `{profile_id}`")
    got = probe_candidate(root, profile_id, argv, kind, config=config, timeout=timeout or _timeout_of(config), env=env_new)
    result["report"] = {k: v for k, v in got.items() if k != "proven"}
    if not got["proven"]:
        result.update(move="explain_and_ask", says=f"that command did not prove: {got['why']}")
        return result
    result["proposal"] = _seal(root, table, profile_id, argv, kind, "command", None, proposals_dir, kind_new=kind_new,
                               env=got.get("env_change"))
    result.update(move="do_it", says="that command left a report the factory can read; ask the person to confirm the change")
    return result


THREE_ANSWERS = ("You can: (a) give me the command that writes a JUnit report and I will try it; (b) fix it yourself and tell me, "
                 "and I will check again; (c) leave it for now - nothing is recorded, and the first story's check asks again.")
# what a person is told per probe state that is only told (FR-42: every state has a move); {pid} is the profile's name
TELL_TEXT = {
    "no_test": "I found no existing test of the {pid} tests to prove the report with, so I could not check whether they leave a report "
               "the factory can read. The first story's check looks at it again.",
    "timed_out": "One test of the {pid} tests did not finish in time, so I do not know whether they leave a report the factory can "
                 "read. The first story's check asks again.",
    "launcher_missing": "The program that runs the {pid} tests was looked for on this machine (PATH, with its Windows wrapper forms) and not "
                        "found, so I could not check the report they leave. The launch check and the first story's check come first.",
}
NOT_CHECKED_KNOWN = ("not selected", "the project's own settings turn the report rehearsal off",
                     "the profile records no command that runs one test")


def _block(note: str) -> str:
    return "\n\n---\nAnswer: " + note + "\n"


def problem_text(problem: str) -> str:
    """ONE sentence for a probe that could not run: it carries the problem, and says nothing was changed by it (F2)."""
    return ("The check of the test commands could not run: " + str(problem).strip().rstrip(".") + ". Nothing was changed by it, and "
            "the first story's check looks at the commands again." + _block("nothing to answer now."))


def _question_of(proposal: dict) -> str:
    """The sentence to ask, RENDERED FROM THE SEALED FILE (F10): the one `--question` prints, so the apply's text and the
    CLI's are one renderer. A file that cannot be read back is said, never replaced by the maker's own copy."""
    sealed = proposal.get("sealed")
    if sealed is None:
        sealed = json.loads(Path(proposal["path"]).read_text(encoding="utf-8"))
    return C.command_question(sealed)


def _explain_text(entry: dict, why_table: str) -> str:
    pid, cure = entry["profile"], entry.get("cure") or {}
    action = cure.get("action")
    text = (f"One existing test of the {pid} tests was run through the command the project records, and it left no report the "
            "factory can read, so every later run of them would be recorded as not executed.")
    if action == "diagnosis":
        text += (" The runner already asks for the report itself, so there is no option to add to the command: the report is "
                 "missing for another reason that I cannot name from here.")
    elif action == "kind_conflict":
        text += (f" The usual cure writes a {cure.get('reporter_kind')} report, and the profile already says another kind; a kind "
                 "that was recorded is not overwritten.")
    elif action == "dependency_only":
        text += (" The option that writes the report is already in the command, so I add nothing; what is missing is: "
                 + "; ".join(cure.get("needs") or []) + ".")
    elif action == "present":
        text += " The option that writes the report is already in the command and nothing it needs is missing, so the cause is somewhere else."
    elif action == "explain":
        text += " " + str(cure.get("person_words") or "").strip()
    elif action == "add":       # a cure that was tried and did not prove
        text += (" The usual cure was tried on this machine before I asked you, and it did not prove: "
                 + str(cure.get("why_short") or "it left no report").strip().rstrip(".") + ". " + str(cure.get("person_words") or "").strip())
    else:                       # unknown: no row names this kind of command
        text += " I know no cure for this kind of command" + (", and the list of known cures could not be read" if why_table.startswith(
            "the cure table could not be read") else "") + "."
    return text.strip() + "\n\n" + THREE_ANSWERS + _block("say (a), (b) or (c), and for (a) give me the command.")


def person_text(entry: dict, why_table: str = "") -> str:
    """What is said to the person for ONE profile entry of the probe, '' when nothing is. Built from the entry's FIELDS, never
    from `says` (a line for code and for the LLM), so a flag, a file name or the raw tail of a run (`report.detail`) cannot ride in
    on it. Every text passes `human_text.problems`: a test runs it on the apply's real JSON (F2)."""
    move, pid = entry.get("move"), entry["profile"]
    if move == "nothing":
        return ""
    if move == "do_it":
        try:
            return _question_of(entry["proposal"])
        except (OSError, ValueError, KeyError):
            # the reason the file was refused is a message for code (it names a script and its options): not for this sentence
            return problem_text(f"the question about the {pid} tests could not be read back from its sealed file, so it is not asked")
    if move == "waits_for_turn":
        return (f"The {pid} tests have a known cure too, but I ask about {(entry.get('cure') or {}).get('waits_for') or 'the other profile'} "
                "first, and about these after that answer. Nothing is asked of you for them now." + _block("nothing to answer for this one yet."))
    if move == "explain_and_ask":
        return _explain_text(entry, why_table)
    state = (entry.get("report") or {}).get("state")
    why = str((entry.get("report") or {}).get("why") or "")
    text = TELL_TEXT.get(state, "").replace("{pid}", pid)
    if not text:
        text = (f"I did not check the report of the {pid} tests: " + (why if why in NOT_CHECKED_KNOWN else "the check could not run")
                + ". The first story's check looks at it again.")
    return text + _block("nothing to answer now.")


def person_texts(result: dict) -> list:
    """[{profile, move, text}] - what is said to the person for each profile that needs a word (P3: code runs the command on
    the transition, the LLM relays). `do_it`: the sealed sentence with its "Do it?"; `explain_and_ask`: what happened and FR-50's
    three answers; `tell` / `waits_for_turn`: one short text. A proven profile says nothing. The `problem` of a probe that
    could not start is one entry of its own."""
    out = []
    if result.get("problem"):
        out.append({"profile": "", "move": "tell", "text": problem_text(result["problem"])})
    for entry in result.get("profiles") or []:
        text = person_text(entry, str(result.get("cure_table") or ""))
        if text:
            out.append({"profile": entry["profile"], "move": entry["move"], "text": text})
    return out


# --- command line ---------------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--probe-profiles", action="store_true", help="probe every profile's command; one proposal when a cure is proven")
    ap.add_argument("--profile", action="append", default=[], help="limit the probe to this profile id (repeatable); with --command, the profile it is for")
    ap.add_argument("--command", help="the person's own command line for --profile: probed and sealed as one proposal")
    ap.add_argument("--kind", choices=C.REPORT_KINDS, help="with --command: the report format the command writes")
    ap.add_argument("--proposals-dir", type=Path, help="where sealed proposals go: a folder OUTSIDE the project")
    ap.add_argument("--question", type=Path, help="print the sentence to ask, rendered from this sealed proposal")
    ap.add_argument("--json", action="store_true", help="accepted for symmetry: the probe's stdout is always one JSON object")
    ns = ap.parse_args(argv)
    modes = [bool(ns.probe_profiles), ns.command is not None, ns.question is not None]
    if sum(modes) != 1:
        ap.error("choose one of --probe-profiles, --command (with one --profile) or --question <sealed proposal>")
    try:
        if ns.question is not None:
            try:
                proposal = json.loads(ns.question.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"{ns.question} cannot be read as a sealed proposal ({exc})") from exc
            print(C.command_question(proposal))
            return 0
        root = ns.root.resolve()
        if ns.command is not None:
            if len(ns.profile) != 1:
                ap.error("--command names its profile: give exactly one --profile")
            result = probe_person_command(root, ns.profile[0], ns.command, ns.proposals_dir, ns.kind)
        else:
            result = probe_profiles(root, ns.proposals_dir, only=ns.profile)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except ValueError as exc:
        print(f"onboarding_probe: refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
