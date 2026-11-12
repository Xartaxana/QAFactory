"""The environment record: what a person accepted ONCE as a property of this environment (B-414, D-0029, D-0032).

A stand-gap card used to be asked again at every gate of every story: the same fact about the environment ("the mocks stand in
for a real API", "this service does not exist on this stand") was answered `accept` for one story and forgotten. The record
keeps such an answer, with the person's own words, in `qa-factory/records/environment-properties.json` (carried by the project:
every machine that uses it reads the same file), and the gates read it before they build a card.

What may be recorded (D-0032): a gap whose cause is the environment's CONFIGURATION. A gap whose cause is a FILE or the machine -
the report file was not written, the runner ended with an error, a dependency is missing - is a fault that gets fixed, never a
property: `lasting` refuses it, with the door `accept` (for this story only). The key says WHAT the answer is about, so it never
covers another command, another stand or another failure:

  level  `{scope, contour, argv_digest, reason_class}` - the one test command of an execution contour, as the config records it
  case   `{scope, environment, definition_sha, precondition_kind, check_digest}` - one declared precondition on one stand

ERROR DIRECTION: toward asking (FR-59). A record that cannot be read, a row that is revoked, a key that has changed, a gap with
no key - each is "not covered", and the card is shown. Nothing is recorded under a placeholder key.

  environment_record.py show [--json]
  environment_record.py record --task T --contour web --reason zero_tests --exit-code 0 --option accept --words-file F
  environment_record.py record --task T --case TC-007 --gap PC-1 --option accept --words-file F
  environment_record.py revoke --id EP-1 --words-file F
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RECORD_REL = "qa-factory/records/environment-properties.json"
SCHEMA_VERSION = 1
LEVEL, CASE = "level", "case"
# The reasons a reporter card gives for a report the factory cannot read (`gate_preflight._read_probe_report`).
REASON_CLASSES = ("no_file", "unparsable", "zero_tests")
# What each class says when it is a FAULT of a file or the machine (M13: the card prints it in one line).
FAULT_WORDS = {
    "no_file": "the report was not written",
    "unparsable": "the report could not be read",
    "zero_tests": "the run ended with an error and counted no test",
}
FAULT_TAIL = ("a fault of this machine, not a property of the environment - fix it, or write `accept` to go on without "
              "it for this story")
# the checks a machine made about the stand; prose `none` and the like have no key. `integration` (GW1-16) is keyed by the
# NAME the case declares, so a word about a service holds on this stand while its keys change (G-6 a)
KEYED_CHECKS = ("env", "http", "integration")
PLACEHOLDER_STAND = "this stand"
LEVEL_FIELDS = ("scope", "contour", "argv_digest", "reason_class")
CASE_FIELDS = ("scope", "environment", "definition_sha", "precondition_kind", "check_digest")
# `why` of `lasting`: "" = a key exists; `fault` = the cause is a file or the machine; `no_key` = nothing to key it by
FAULT, NO_KEY = "fault", "no_key"


def record_path(root) -> Path:
    return Path(root) / Path(RECORD_REL)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _moment(value) -> float:
    import contract
    return contract._answer_moment(value)


# --- the key ---------------------------------------------------------------------------------------------------------

def fault_line(reason_class) -> str:
    """The ONE line a card gives where `accept always` is not offered because the cause is a fault (M13)."""
    return f"{FAULT_WORDS.get(str(reason_class), 'the report could not be used')}: {FAULT_TAIL}"


def _argv_of(cfg, contour) -> list:
    profiles = (cfg or {}).get("profiles")
    for profile in profiles if isinstance(profiles, list) else []:     # a config on disk may hold any shape: no profile, no argv
        if isinstance(profile, dict) and str(profile.get("profile_id") or "") == str(contour):
            import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
            return PC.one_test_argv(profile)[0]      # a shape it cannot read keys nothing here: no argv, as no command
    return []


def _identity_of(cfg, contour) -> list:
    """The words that say WHICH command the contour's profile records (`profile_contract.command_identity`, EP1-22 B-2): the one
    input of its digest, here and in the gate's manifest and rows. The argv words when the command sets no `env`, so an
    `accept always` given on a command without one is covered exactly as before - and no longer once the command gains an `env`."""
    profiles = (cfg or {}).get("profiles")
    for profile in profiles if isinstance(profiles, list) else []:
        if isinstance(profile, dict) and str(profile.get("profile_id") or "") == str(contour):
            import profile_contract as PC
            return PC.command_identity(PC.profile_command(profile, "one_test")[0])
    return []


def _level_key(gap, cfg) -> dict:
    contour, reason = str(gap.get("contour") or ""), str(gap.get("reason_class") or "")
    if reason not in REASON_CLASSES:
        return {"key": None, "why": NO_KEY}
    exit_code = gap.get("exit_code")
    normal_exit = isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code == 0
    if reason in ("no_file", "unparsable") or not normal_exit:
        # `zero_tests` after a run that ended normally says the selected test counts nothing HERE (a configuration);
        # with an error exit, or an exit nobody recorded, it is as much a fault as a missing file (the unknown is a fault)
        return {"key": None, "why": FAULT}
    argv = _argv_of(cfg, contour)
    if not contour or not argv:
        return {"key": None, "why": NO_KEY}
    from onboarding_probe import argv_digest
    return {"key": {"scope": LEVEL, "contour": contour, "argv_digest": argv_digest(_identity_of(cfg, contour)), "reason_class": reason}, "why": ""}


def check_digest(check) -> str:
    return hashlib.sha256(json.dumps(check, sort_keys=True).encode("utf-8")).hexdigest()


def _case_key(gap, cfg, stand) -> dict:
    check = gap.get("check")
    name = next(iter(check)) if isinstance(check, dict) and len(check) == 1 else ""
    stand = str(stand or "").strip()
    kind = str(gap.get("kind") or "").strip()
    if name not in KEYED_CHECKS or not kind or not stand or stand == PLACEHOLDER_STAND:
        return {"key": None, "why": NO_KEY}
    from stand_identity import definition_sha_for
    sha = definition_sha_for(cfg, stand)
    if not sha:
        return {"key": None, "why": NO_KEY}
    return {"key": {"scope": CASE, "environment": stand, "definition_sha": sha, "precondition_kind": kind,
                    "check_digest": check_digest(check)}, "why": ""}


def lasting(gap, cfg, stand) -> dict:
    """`{key, why}` of one stand gap: the key an `accept always` on it would be recorded under, or why there is none.

    `gap` is a gate A gap row: `scope` ("level" or "case"), and for a level `contour`, `reason_class`, `exit_code`; for a case
    `check` (the precondition's own check) and `kind`. `stand` is `stand_gaps.stand_name(task_root)` - the ONE derivation
    the gates and the command line share (M8). Never raises."""
    try:
        gap = gap if isinstance(gap, dict) else {}
        if gap.get("scope") == LEVEL:
            return _level_key(gap, cfg)
        if gap.get("scope") == CASE:
            return _case_key(gap, cfg, stand)
    except Exception:
        pass
    return {"key": None, "why": NO_KEY}


def property_key(gap, cfg, stand):
    """The key of `lasting`, or None."""
    return lasting(gap, cfg, stand)["key"]


def about_of(gap) -> str:
    """What the record says cannot be checked on this environment, for the person's line (`on this environment <X> cannot
    be checked`): a level - its tests; a case - the precondition's own words, in quotes."""
    gap = gap if isinstance(gap, dict) else {}
    if gap.get("scope") == LEVEL:
        return f"the {gap.get('contour')} tests"
    what = " ".join(str(gap.get("what") or "").split())[:120]
    return f'"{what}"' if what else "something this case needs"


def current_key(subject, cfg, stand):
    """The key the SAME subject has NOW: a level - the contour's command as the config records it now; a case - the stand's
    definition as the config records it now. None when it cannot be built. A carried answer is still covered only while
    `covering` finds its record under this key (C4 of `stand_gaps.carried_change`)."""
    if not isinstance(subject, dict):
        return None
    try:
        if subject.get("scope") == LEVEL:
            argv = _argv_of(cfg, subject.get("contour"))
            if not argv:
                return None
            from onboarding_probe import argv_digest
            return dict(subject, argv_digest=argv_digest(_identity_of(cfg, subject.get("contour"))))
        if subject.get("scope") == CASE:
            stand = str(stand or "").strip()
            from stand_identity import definition_sha_for
            sha = definition_sha_for(cfg, stand) if stand and stand != PLACEHOLDER_STAND else ""
            return dict(subject, environment=stand, definition_sha=sha) if sha else None
    except Exception:
        return None
    return None


def near_miss(rows, key):
    """`(row, why)` of a live accepted row that is ABOUT the same thing as `key` but not covered by it (the command changed,
    the failure is another one, the stand's address changed) - so the card can say "your earlier answer no longer applies" and
    why. `(None, "")` when there is none. `why`: `command`, `reason`, `address`."""
    if not _valid_key(key):
        return None, ""
    for row in sorted((r for r in rows or [] if _live(r)), key=lambda r: (_moment(r.get("at"))), reverse=True):
        subject = row.get("subject")
        if not isinstance(subject, dict) or subject.get("scope") != key["scope"] or subject == key:
            continue
        if key["scope"] == LEVEL and subject.get("contour") == key["contour"]:
            return row, ("command" if subject.get("argv_digest") != key["argv_digest"] else "reason")
        if (key["scope"] == CASE and subject.get("environment") == key["environment"]
                and subject.get("check_digest") == key["check_digest"] and subject.get("definition_sha") != key["definition_sha"]):
            return row, "address"
    return None, ""


# --- the file --------------------------------------------------------------------------------------------------------

def load_rows(path, list_key, schema_version, label=None) -> tuple:
    """`(rows, problem)` of ONE record file of the shape `{"schema_version": n, <list_key>: [...]}`. Never raises. An absent
    file is `([], "")`. A file that cannot be read, is not an object, holds another `schema_version` or no list is
    `([], <why>)`: nothing is covered by it, and the writers refuse to write over it (E9: an unknown never suppresses a
    question, and words are never overwritten). Shared by the environment record and the gap-class record
    (`source_inventory.live_gap_classes`): ONE reader of a record file."""
    path = Path(path)
    label = label or path.name
    try:
        if not path.is_file():
            return [], ""
    except OSError as exc:
        return [], f"{path.name} cannot be reached ({exc.strerror or type(exc).__name__})"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [], f"{label} cannot be read ({str(exc)[:80] or type(exc).__name__})"
    if not isinstance(data, dict):
        return [], f"{label} is not an object"
    if data.get("schema_version") != schema_version:
        return [], f"{label} has schema_version {data.get('schema_version')!r}, not {schema_version}"
    rows = data.get(list_key)
    if not isinstance(rows, list):
        return [], f"{label} has no `{list_key}` list"
    return [r for r in rows if isinstance(r, dict)], ""


def write_rows(path, list_key, schema_version, rows, label=None) -> str:
    """Write the rows atomically; `""` or the problem."""
    label = label or Path(path).name
    try:
        from event_store import atomic_json
        atomic_json(Path(path), {"schema_version": schema_version, list_key: rows})
    except Exception as exc:
        return f"{label} could not be written ({str(exc)[:80] or type(exc).__name__})"
    return ""


def next_id(rows, prefix) -> str:
    """`<prefix><n+1>`: the next id of a record whose ids are `<prefix><n>`."""
    numbers = [int(str(r.get("id"))[len(prefix):]) for r in rows
               if str(r.get("id") or "").startswith(prefix) and str(r.get("id"))[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def revoke_row(path, list_key, schema_version, row_id, words, show_door, now=None, noun="property", label=None) -> tuple:
    """`(row, problem)`: take one row of a record file back. The row stays, with `revoked_at` and the words said now. An
    unknown id, an id already taken back, empty words and an unreadable record are refused with the door (`show_door`,
    the command that lists the rows) in the text."""
    text = str(words or "").strip()
    if not text:
        return None, "the person's words are empty"
    label = label or Path(path).name
    rows, problem = load_rows(path, list_key, schema_version, label)
    if problem:
        return None, problem + "; nothing was written over it"
    row = next((r for r in rows if str(r.get("id")) == str(row_id)), None)
    if row is None:
        return None, f"there is no {noun} {row_id} in {label}; {show_door} lists them"
    if row.get("revoked_at"):
        return None, f"{row_id} was already taken back on {str(row['revoked_at'])[:10]}; {show_door} lists the live ones"
    row["revoked_at"] = now or now_iso()
    row["revoked_words"] = text
    problem = write_rows(path, list_key, schema_version, rows, label)
    return (None, problem) if problem else (row, "")


def load(root) -> tuple:
    """`(rows, problem)` of the environment record. Never raises. An absent file is `([], "")` - the normal state before the
    first `accept always`; an unreadable one is `([], <why>)`: nothing is covered by it, and `record` / `revoke` refuse to
    write over it."""
    return load_rows(record_path(root), "properties", SCHEMA_VERSION, RECORD_REL)


def _live(row) -> bool:
    return (isinstance(row, dict) and not row.get("revoked_at") and row.get("option") == "accept"
            and isinstance(row.get("subject"), dict))


def live_level(row) -> bool:
    """Is this a live row about a level (the contour of a test command)?"""
    return _live(row) and row["subject"].get("scope") == LEVEL


def _valid_key(key) -> bool:
    if not isinstance(key, dict):
        return False
    fields = LEVEL_FIELDS if key.get("scope") == LEVEL else CASE_FIELDS if key.get("scope") == CASE else None
    return (fields is not None and set(key) == set(fields)
            and all(isinstance(key[f], str) and key[f].strip() for f in fields))


def covering(rows, key):
    """The live row that holds exactly this key, or None. PURE.

    Several live rows of one key: the latest `at` wins, on a tie the later row (E10). A revoked row, a row with no `subject`
    or an `option` other than `accept`, and a key that is incomplete (an empty field, another scope's fields) cover nothing:
    the only error this function may make is "not covered" (E14)."""
    if not _valid_key(key):
        return None
    best, best_order = None, None
    for index, row in enumerate(rows or []):
        if not _live(row) or row["subject"] != key:
            continue
        order = (_moment(row.get("at")), index)
        if best_order is None or order >= best_order:
            best, best_order = row, order
    return best


def _next_id(rows) -> str:
    return next_id(rows, "EP-")


def _write(root, rows) -> str:
    return write_rows(record_path(root), "properties", SCHEMA_VERSION, rows, RECORD_REL)


def record(root, key, option, words, story, about="", now=None) -> tuple:
    """`(row, problem, created)`: one `accept always` put in the record, with the person's words whole.

    Refused (nothing written, `row` None, `problem` says why): an option other than `accept`, a key that is not whole, empty
    words, an unreadable record. A key that is already covered returns that row with `created` False - the earlier word stands
    and the record never holds two live rows of one key by this door."""
    if option != "accept":
        return None, f"only `accept` has a lasting form, not {option!r}", False
    if not _valid_key(key):
        return None, "this gap has no key to record it under", False
    text = str(words or "").strip()
    if not text:
        return None, "the person's words are empty", False
    rows, problem = load(root)
    if problem:
        return None, problem + "; nothing was written over it", False
    held = covering(rows, key)
    if held is not None:
        return held, "", False
    row = {"id": _next_id(rows), "subject": dict(key), "option": "accept", "words": text, "at": now or now_iso(),
           "story": str(story or ""), "about": " ".join(str(about or "").split())[:160]}
    problem = _write(root, rows + [row])
    return (None, problem, False) if problem else (row, "", True)


def revoke(root, ep_id, words, now=None) -> tuple:
    """`(row, problem)`: take one row back. The row stays, with `revoked_at` and the words said now; past stories are
    untouched (their own overrides are theirs). An unknown id, an id already taken back, empty words and an unreadable
    record are refused with the door in the text (`show`)."""
    return revoke_row(record_path(root), "properties", SCHEMA_VERSION, ep_id, words, "`environment_record.py show`",
                      now=now, noun="property", label=RECORD_REL)


def says(row) -> str:
    """The record's own sentence for one row, as the person reads it."""
    about = str((row or {}).get("about") or "").strip() or "this"
    return f"on this environment {about} cannot be checked"


def show_lines(rows) -> list:
    out = []
    for row in rows:
        state = f"taken back {str(row['revoked_at'])[:10]}" if row.get("revoked_at") else "live"
        words = " ".join(str(row.get("words") or "").split())[:160]
        out.append(f"{row.get('id')} ({state}): {says(row)} - recorded {str(row.get('at') or '')[:10]}"
                   f"{' in ' + str(row['story']) if row.get('story') else ''}: \"{words}\"")
    return out


# --- the command line ------------------------------------------------------------------------------------------------

def _refuse(message: str) -> int:
    print(f"environment_record: {message}", file=sys.stderr)
    return 2


def _words(ns, command: str, script: str = "environment_record.py"):
    """The person's words from `--words-file`, or the refusal text (a `str`) - read ONCE, before any file is touched.
    `script` names the command line in the door text: project_knowledge.py shares this reader."""
    import person_words
    try:
        words = person_words.read(None, ns.words_file, "--words")
    except person_words.WordsRefused as exc:
        return None, str(exc)
    if not str(words or "").strip():
        return None, ("--words-file is required: the person's own words, exactly as they were given. "
                      + person_words.door(f"{script} {command}"))
    return words, ""


def _story_context(task: str):
    """`(project root, story folder, config, the story's own id)` from `--task`, through the ONE resolver (axis 8)."""
    import hooklib
    import runtime_paths
    task_root = hooklib.artifacts_dir(task)
    if not task_root.is_dir():
        raise ValueError(f"there is no story `{task}` in this project, so nothing was recorded; pass the id of the story "
                         "that is running as --task")
    root = runtime_paths.project_for_task(task_root)
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    try:
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pipeline = {}
    return root, task_root, cfg if isinstance(cfg, dict) else {}, str(pipeline.get("ticket") or task)


def _gap_from_case(task_root, ns):
    """The precondition `--gap` of `--case`, as a gate A gap row, with no probe: from what the case declares."""
    import stand_gaps
    for item in stand_gaps.declared_preconditions(task_root):
        raw = str(item.get("pc_id") or item.get("id"))
        if str(item.get("case")) == ns.case and ns.gap in (str(item.get("id")), raw):
            return dict(item, scope=CASE, check=item.get("check"))
    return None


def cmd_record(ns) -> int:
    command = ("record --task <T> --contour <id> --reason <class> --option accept" if ns.contour else
               "record --task <T> --case <id> --gap <PC id> --option accept")
    words, refusal = _words(ns, command)
    if refusal:
        return _refuse(refusal)
    if bool(ns.contour) == bool(ns.case):
        return _refuse("give exactly one subject: --contour <id> --reason <class>, or --case <id> --gap <PC id>; "
                       "nothing was recorded")
    try:
        root, task_root, cfg, story = _story_context(ns.task)
    except ValueError as exc:
        return _refuse(str(exc))
    import stand_gaps
    stand = stand_gaps.stand_name(task_root)
    if ns.contour:
        if ns.reason not in REASON_CLASSES:
            return _refuse(f"--reason must be one of {', '.join(REASON_CLASSES)}; nothing was recorded")
        gap = {"scope": LEVEL, "contour": ns.contour, "reason_class": ns.reason,
               "exit_code": ns.exit_code}      # a missing --exit-code is an UNKNOWN exit: a fault, never a normal one (M13, FR-59)
    else:
        if not ns.gap:
            return _refuse("--case needs --gap <the precondition id>; nothing was recorded")
        gap = _gap_from_case(task_root, ns)
        if gap is None:
            return _refuse(f"case {ns.case} declares no precondition {ns.gap}; `stand_gaps.py --task {ns.task} --gate A` "
                           "lists the gaps; nothing was recorded")
    got = lasting(gap, cfg, stand)
    if got["why"] == FAULT:
        return _refuse(f"{fault_line(gap.get('reason_class'))}; nothing was recorded")
    if got["key"] is None:
        return _refuse("this gap has no key to record it under (no machine check of it, no stand with an address of its own, "
                       "or no command in the config); the answer for this story is `accept` on the card; nothing was recorded")
    row, problem, created = record(root, got["key"], ns.option, words, story, about_of(gap))
    if row is None:
        return _refuse(f"{problem}; nothing was recorded")
    print(f"{row['id']}: {says(row)}" + ("" if created else " (already recorded; the earlier words stand)"))
    return 0


def cmd_revoke(ns) -> int:
    words, refusal = _words(ns, "revoke --id <EP-n>")
    if refusal:
        return _refuse(refusal)
    import hooklib
    row, problem = revoke(hooklib.project_root(), ns.id, words)
    if row is None:
        return _refuse(problem)
    print(f"{row['id']} is taken back: {says(row)} is asked again at every gate; the stories already answered keep their own answers.")
    return 0


def cmd_show(ns) -> int:
    import hooklib
    rows, problem = load(hooklib.project_root())
    if ns.json:
        print(json.dumps({"properties": rows, "problem": problem}, indent=2, ensure_ascii=False))
    elif problem:
        print(problem)
    elif not rows:
        print("no environment property is recorded.")
    else:
        print("\n".join(show_lines(rows)))
    return 1 if problem else 0


def command_parser(description: str, show_fn):
    """`(parser, subparsers)` with the `show [--json]` command already in: the one command-line start of this record family
    (project_knowledge.py builds its own parser through it)."""
    ap = argparse.ArgumentParser(description=description)
    sub = ap.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    show.set_defaults(fn=show_fn)
    return ap, sub


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap, sub = command_parser("The environment record: what a person accepted once as a property of this environment.", cmd_show)
    rec = sub.add_parser("record")
    rec.add_argument("--task", required=True)
    rec.add_argument("--contour", default="")
    rec.add_argument("--reason", default="")
    rec.add_argument("--exit-code", dest="exit_code", type=int, default=None,
                     help="how the run ended; missing = unknown = a fault (a `zero_tests` after an error exit is a fault, not a property)")
    rec.add_argument("--case", default="")
    rec.add_argument("--gap", default="")
    rec.add_argument("--option", required=True, choices=("accept",))
    rec.add_argument("--words-file", dest="words_file", default=None)
    rec.set_defaults(fn=cmd_record)
    rev = sub.add_parser("revoke")
    rev.add_argument("--id", required=True)
    rev.add_argument("--words-file", dest="words_file", default=None)
    rev.set_defaults(fn=cmd_revoke)
    ns = ap.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(main())
