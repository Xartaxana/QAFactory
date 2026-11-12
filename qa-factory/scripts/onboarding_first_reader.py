"""onboarding_first_reader.py - the check `onboarding_notes.py close` runs before it closes a run (OH3-29).

The first reader of the config the onboarding just wrote is `readiness.py` and, behind it, the one-test command of each
profile (`profile_contract.one_test_argv`): S5 builds every run from nothing else. A phase 4 that ends while that reader
fails, or while a profile has no command that runs one test, ends with a defect nobody recorded. `problems(root)` names
each such defect with the door that passes it; `close` refuses while the list is not empty (FR-4: a silent pass is
stopped, an informed one is not).

What it reads, and in which order (AR-28: an unknown here is a problem, never a pass):
  1. the LIVE `qa-factory/config.json` of `root` - not `state/readiness.json`, because phase 4 lets a role edit the written
     config in place after the apply (`hooklib.read_json`, the one JSON reader; a leading BOM is not a problem);
  2. `readiness.py --no-trace` through `onboard_apply._run_script` (the one place a script is launched at onboarding; no
     `--write`, no `--json`, and `--no-trace` so the tracker is neither asked nor written to);
  3. every row of `profiles[]` through `profile_contract.one_test_argv(profile, drop_placeholders=True)`.

It answers "a command is RECORDED", not "the command will START": the launch check is the judge of that. Passes that are
allowed and known: `[5]`, `["--file", "<x>"]`, `["{report_path}"]`, `[" <x> "]`. The `env` of the command is read by the
same reader S5 uses (`profile_contract.command_env`): a form S5 refuses (not an object, a name that is no variable name, a
value other than `{report_path}`) is a problem here, so the defect surfaces at onboarding and not at the first run.

The recorded gap. Only a record in `qa-factory/factory-backlog.md` about the SAME subject lifts a problem: an open DD whose
`field_refs` hold exactly `/profiles/<n>`, `/profiles/<n>/commands`, `/profiles/<n>/commands/one_test` or
`/profiles/<n>/commands/one_test/argv` for the profile's place `n` (for an empty `profiles`: exactly `/profiles`; a
`profiles` that is not a list is lifted by nothing), or an open finding whose witness cell ends with
`; idempotency:launch-<profile-id>` (`no-test-framework` for an empty list, `first-reader-crash` for a failed readiness).
Known false passes, both visible in the journal and to the doctor: a DD written by index before the profiles were
reordered; an old open `launch-<id>` finding. The journal is read only when a problem exists that a record could lift.
"""
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import hooklib  # noqa: E402
import profile_contract as PC  # noqa: E402
import project_decisions as PD  # noqa: E402

MAX_NAMED = 20                      # a refusal names this many problems; the rest is "+K more" (the count is of ALL)
CONFIG_REL = "qa-factory/config.json"
BACKLOG_REL = "qa-factory/factory-backlog.md"
CRASH_KEY = "first-reader-crash"
NO_FRAMEWORK_KEY = "no-test-framework"
ASKED = "<the question as it was put>"


def _line(text) -> str:
    """A value as one line of text."""
    return " ".join(str(text).split())


def _one(text) -> str:
    """A value of a door command as ONE shell word: one line, quoted for the shell (a `$`, a backtick, `&`, `;` or a space
    in it stays data). A door is a line a role runs as printed (FR-2)."""
    return shlex.quote(_line(text))


def _kind(value) -> str:
    return "null" if value is None else type(value).__name__


def _problem(text: str, door: str, refs=(), key: str | None = None) -> dict:
    return {"text": text, "door": door, "refs": set(refs), "key": key}


def _add_form(ref: str, essence: str) -> str:
    return f"`project_decisions.py --root . add --field-ref {_one(ref)} --essence {_one(essence)} --asked {_one(ASKED)}`"


def _finding_form(essence: str, witness: str, key: str) -> str:
    """The form sits in backticks, so the sentence's own period is never part of the command (the key is its last word)."""
    return (f"`project_decisions.py --root . add-finding --essence {_one(essence)} --scope local-urgent "
            f"--witness {_one(witness)} --idempotency-key {shlex.quote(key)}`")   # the key as it is: it is compared as written


def _profile_problem(index: int, profile, detail: str) -> dict:
    pid = str(profile.get("profile_id") or "").strip() if isinstance(profile, dict) else ""
    where = f"/profiles/{index}"
    refs = [where, where + "/commands", where + "/commands/one_test", where + "/commands/one_test/argv"]
    if not pid:
        label = f"profiles[{index}]"
        return _problem(
            f"{label}: {detail}",
            "Fix it in qa-factory/config.json (give the profile a profile_id) and close again. Cannot be fixed now: "
            f"if you asked a person, {_add_form(where, f'{label}: {detail}')}.", refs)
    what = f"{pid}: {detail}"
    return _problem(
        f"profile {pid}: {detail}",
        "Fix it in qa-factory/config.json and close again. Cannot be fixed now: if you asked a person, "
        f"{_add_form(where + '/commands/one_test/argv', what)}; if you asked nobody, "
        f"{_finding_form(what, 'onboarding_notes.py close: ' + detail, 'launch-' + pid)}.",
        refs, "launch-" + pid)


def _collect(root) -> tuple[list, bool]:
    """(problems, journal_may_lift): every problem found, each with its door; no record is consulted here."""
    config = Path(root) / CONFIG_REL
    if not config.is_file():
        return [_problem(
            f"no {CONFIG_REL} yet",
            "Run `onboard_apply.py --root . --proposal <sealed.json> --apply --approval-ref <ref> --phase early` (the config "
            "is written by that phase; the proposal is the sealed one phase 4 gives), then close again.")], False
    cfg = hooklib.read_json(config, None, errors=Exception, kind=dict)
    if cfg is None:
        return [_problem(f"{CONFIG_REL} is not a JSON object",
                         "Repair the file (it must hold one JSON object) and close again; no record passes this.")], False
    found = []
    import onboard_apply as OA           # inside: the notes module does not load the apply module just to be imported
    done = OA._run_script(root, "readiness.py", ("--no-trace",))
    if not done["ok"]:
        note = _line(done["note"])
        found.append(_problem(
            f"readiness.py could not finish: {note}",
            "Fix what it names and close again. If the cause is not yours to fix, record it: "
            f"{_finding_form('readiness.py could not finish at onboarding: ' + note, note, CRASH_KEY)}.",
            key=CRASH_KEY))
    profiles = cfg.get("profiles")
    if "profiles" not in cfg or profiles == []:        # `null` is not a list: it is the branch below, and no record lifts it
        found.append(_problem(
            f"{CONFIG_REL} lists no profiles, so nothing can run one test",
            "Add the project's profile and close again. No test framework, or it cannot be added now: if you asked a "
            f"person, {_add_form('/profiles', 'profiles: none: <why>')}; if you asked nobody, "
            f"{_finding_form('no test framework recorded: profiles stays empty', 'onboarding_notes.py close: profiles is empty', NO_FRAMEWORK_KEY)}.",
            ["/profiles"], NO_FRAMEWORK_KEY))
    elif not isinstance(profiles, list):
        found.append(_problem(
            f"profiles is {_kind(profiles)}; expected a list of profile objects",
            "Fix it in qa-factory/config.json and close again; no record passes this."))
    else:
        for index, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                found.append(_profile_problem(index, profile, f"the profile is {_kind(profile)}; expected an object"))
                continue
            words, detail = PC.one_test_argv(profile, drop_placeholders=True)
            if detail:
                found.append(_profile_problem(index, profile, detail))
            elif not words:
                found.append(_profile_problem(index, profile, "no command that runs one test (commands.one_test.argv holds no word)"))
            else:
                env_problem = PC.command_env(PC.profile_command(profile, "one_test")[0])[1]    # S5 refuses the same form
                if env_problem:
                    found.append(_profile_problem(index, profile, f"commands.one_test.{env_problem}"))
    return found, any(p["refs"] or p["key"] for p in found)


def _journal(root) -> tuple[list, list, list]:
    """(open DD ref sets, findings, unreadable-cell problems) of the backlog; a file that is absent or cannot be read holds none."""
    try:
        text = PD._paths(Path(root))[0].read_text(encoding="utf-8")
    except (OSError, ValueError):
        return [], [], []
    refs, bad = [], []
    for row in PD.parse_rows(text):
        if row.get("status") != "open" or not row.get("field_refs", ""):
            continue
        try:
            refs.append(set(PD._refs(row["field_refs"])))
        except ValueError as exc:
            bad.append(_problem(
                f"row {row.get('id')} of {BACKLOG_REL} has a field_refs cell that cannot be read ({exc})",
                "Correct that cell to a JSON pointer or doc:<path>[#<anchor>], then close again."))
    return refs, PD.parse_findings(text), bad


def _marker(key: str) -> str:
    return "; idempotency:" + PD._read_back(key)


def problems(root) -> list[str]:
    """Every defect that keeps `close` from passing, as a line a role can act on; `[]` is the pass."""
    found, may_lift = _collect(root)
    if not may_lift:
        return [f"{p['text']}. {p['door']}" for p in found]
    dd_refs, findings, bad_cells = _journal(root)
    kept = []
    for p in found:
        if p["refs"] and any(p["refs"] & held for held in dd_refs):
            continue
        if p["key"] and any(f.get("status") == "open" and f.get("witness/details", "").endswith(_marker(p["key"])) for f in findings):
            continue
        taken = [f for f in findings if p["key"] and f.get("witness/details", "").endswith(_marker(p["key"]))]
        if taken:
            p = dict(p, door=p["door"] + f" The key {p['key']} is held by {taken[0].get('id')} (status {taken[0].get('status')!r}), "
                     "so the finding form returns that row and lifts nothing: record a DD after asking the person, or "
                     "set that row back to `open` by hand.")
        kept.append(p)
    return [f"{p['text']}. {p['door']}" for p in kept + bad_cells]


def refusal(found: list) -> str:
    """The text of the refusal: the problems, `MAX_NAMED` of them at most, and the count of the rest."""
    lines = ["the notes stay open: the first reader of this config is not satisfied."]
    lines += [f"  - {line}" for line in found[:MAX_NAMED]]
    if len(found) > MAX_NAMED:
        lines.append(f"  +{len(found) - MAX_NAMED} more")
    return "\n".join(lines)
