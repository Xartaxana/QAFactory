"""session_identity.py - the one carrier of the session a command runs in (B-410, spec t-471 / t-496).

Keys: K2 (E4-E8, E10-E15, E21-E23 through the pure function with injected `now`, `rules`, `env` and
spool), K3 (what the writer writes, where, and what it prunes), K5 (`onboard_apply._own_session`, the
E18 inputs), K6 (the three SKILL.md texts), E24 (the spool is under the home, never under TMPDIR),
E26 (nothing here depends on the session that runs the test: every name the rules read is cleared and
the home is redirected).

Mutations this file kills (each by this file alone): the newest receipt chosen instead of `ambiguous` |
the cwd filter dropped | `>` becomes `>=` at the warm boundary | the writer writes for any command | the
receipt wins over a disagreeing env | leading-`cd` targets not recorded | `probe_command` replaced by
`command`/`cmd` | `spool_root` reads `tempfile` | `_own_session` reads env only

Run: python -B scripts/tests/test_session_identity.py
"""
import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

use_project(temp_project("qa-session-identity-"))  # onboard_apply pulls config_contract, which reads the hook layer

import hooklib as H  # noqa: E402
import onboard_apply as OA  # noqa: E402
import session_identity as SI  # noqa: E402
import telemetry_hook as TH  # noqa: E402

RULES = SI.load_rules()
NAMES = list(RULES["env_vars"])
REAL_SPOOL_ROOT = SI.spool_root
NOW = 1_800_000_000.0
SCRIPT = "activity_capture.py"
WARM = RULES["warm_seconds"]
DAY = 86400


@contextlib.contextmanager
def world(env=None):
    """E26: a throwaway home (the spool lives under it), a project folder with no config, none of the
    variables the rules read, and the per-process project cache cleared. `env` sets variables on top."""
    home, proj = temp_dir("qa-sid-home-"), temp_dir("qa-sid-proj-")
    keys = (*NAMES, "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR", "CLAUDE_PROJECT_DIR")
    saved, saved_spool = {k: os.environ.get(k) for k in keys}, SI.spool_root
    try:
        for key in keys:
            os.environ.pop(key, None)
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        os.environ.update(env or {})
        SI.spool_root = lambda: home / ".qa-factory" / "spool"
        H._PROJECT_ROOT_CACHE = None
        yield home, proj
    finally:
        SI.spool_root = saved_spool
        for key, value in saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
        H._PROJECT_ROOT_CACHE = None
        cleanup(home)
        cleanup(proj)


def spool_dir() -> Path:
    return SI.spool_root() / RULES["spool_dir"]


def state_dir(root: Path) -> Path:
    return root / "qa-factory" / "state" / "host-receipts"


def key_of(session: str) -> str:
    return hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]


def receipt(folder: Path, session: str, script: str = SCRIPT, cwds=(), age: float = 1.0, now: float = NOW, name=None, **extra) -> Path:
    """A receipt as the writer makes it, aged `age` seconds at `now`."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name or f"pretool-{key_of(session)}-{Path(script).stem}.json")
    doc = {"session_id": session, "script": script, "cwds": [str(c) for c in cwds], "command": "python " + script, "observed_at": "t"}
    doc.update(extra)
    path.write_text(json.dumps(doc), encoding="utf-8")
    os.utime(path, (now - age, now - age))
    return path


def res(cwd, env=None, now: float = NOW, script: str = SCRIPT, event=None, explicit: str = "", rules=RULES) -> dict:
    H._PROJECT_ROOT_CACHE = None
    return SI.resolve(event or {}, explicit, script, cwd=str(cwd), now=now, rules=rules, env=env or {})


def shown(r: dict) -> tuple:
    return (r["session_id"], r["source"], r["problem"])


def event_of(session: str, command: str, cwd, tool_input=None, name: str = "Bash") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": name, "session_id": session, "cwd": str(cwd),
            "tool_input": tool_input if tool_input is not None else {"command": command}}


def docs(folder: Path) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("pretool-*-*.json"))] if folder.is_dir() else []


def same_paths(got, want) -> bool:
    return [os.path.normcase(os.path.normpath(p)) for p in got] == [os.path.normcase(os.path.normpath(str(p))) for p in want]


# --- the rules file (R2, FR-13) ---------------------------------------------------------------------

def rules_file() -> None:
    check("R2: the shipped rules load", RULES is not None)
    check_eq("R2: env_vars name the host's own variable first, then Codex's, then the package's copy",
             NAMES, ["CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID"])
    check_eq("R2: the warm window and the scan limit stay what they were before B-410", (WARM, RULES["scan_limit"]), (30, 20))
    tmp = temp_dir("qa-sid-rules-")
    try:
        def bad(label, change):
            data = json.loads((PLUGIN_ROOT / "references" / "session-identity.json").read_text(encoding="utf-8"))
            change(data)
            path = tmp / "r.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            check_eq(f"R2: invalid rules are None: {label}", SI.load_rules(path), None)
        bad("an empty list", lambda d: d.__setitem__("env_vars", []))
        bad("a list holding an empty string", lambda d: d.__setitem__("cd_words", ["cd", " "]))
        bad("a zero window", lambda d: d.__setitem__("warm_seconds", 0))
        bad("a negative limit", lambda d: d.__setitem__("scan_limit", -1))
        bad("a boolean for a number", lambda d: d.__setitem__("spool_prune_days", True))
        bad("pruning that could reach a warm receipt (days * 86400 <= warm_seconds)", lambda d: d.update(warm_seconds=86400, spool_prune_days=1))
        bad("a spool folder that is a path", lambda d: d.__setitem__("spool_dir", "../x"))
        bad("a script name that is a path", lambda d: d.__setitem__("receipt_scripts", ["a/b.py"]))
        (tmp / "broken.json").write_text("{not json", encoding="utf-8")
        check_eq("R2: broken JSON is None", SI.load_rules(tmp / "broken.json"), None)
        check_eq("R2: an absent file is None", SI.load_rules(tmp / "absent.json"), None)
    finally:
        cleanup(tmp)


# --- E24: where the spool is ----------------------------------------------------------------------------

def spool_location() -> None:
    with world() as (home, _proj):
        os.environ["TMPDIR"] = os.environ["TEMP"] = os.environ["TMP"] = str(home / "elsewhere")
        check_eq("E24: the spool root is under the home and ignores TMPDIR, TEMP and TMP",
                 REAL_SPOOL_ROOT(), Path.home() / ".qa-factory" / "spool")
        check_eq("E24: ...and the home is the redirected one (USERPROFILE / HOME), so a hook and a tool process agree",
                 REAL_SPOOL_ROOT(), home / ".qa-factory" / "spool")


# --- E11, E12: the ids that are given -----------------------------------------------------------------------

def given_ids() -> None:
    with world() as (_home, proj):
        r = res(proj, explicit="s-given")
        check_eq("E11: an explicit id decides", shown(r), ("s-given", "explicit", "none"))
        check_eq("E11: an explicit id wins over an event id, a receipt and the environment (the person's word, P13)",
                 shown(res(proj, explicit="s-given", event={"session_id": "ev"}, env={NAMES[0]: "inherited"})), ("s-given", "explicit", "none"))
        check_eq("E11: '' counts as absent", shown(res(proj, explicit="")), ("", "none", "missing"))
        check_eq("E12: the event's session_id decides after an explicit id, and is not checked against the environment",
                 shown(res(proj, event={"session_id": "ev"}, env={NAMES[0]: "inherited"})), ("ev", "event", "none"))
        for label, value in (("a dot", "."), ("two dots", ".."), ("a slash", "a/b"), ("a backslash", "a\\b"), ("a drive", "C:x"),
                             ("Cyrillic", "\u0441\u0435\u0441\u0441\u0438\u044f"), ("a space", " "), ("129 characters", "a" * 129)):
            got = res(proj, explicit=value)
            check_eq(f"E11: {label} is unsafe: no id, the source named", (got["session_id"], got["source"], got["problem"]), ("", "explicit", "unsafe"))
        check_eq("E11 boundary: exactly 128 characters is accepted", shown(res(proj, explicit="a" * 128)), ("a" * 128, "explicit", "none"))
        check_eq("E11: the characters the rule allows are accepted", res(proj, explicit="a.b-C_9")["session_id"], "a.b-C_9")
        check_in("E11: the refusal names an event id's source in words", "the hook event", SI.refusal(res(proj, event={"session_id": "../x"}), SCRIPT))
        check_in("E11: ...and a variable's source in words", f"the variable {NAMES[1]}", SI.refusal(res(proj, env={NAMES[1]: "a/b"}), SCRIPT))
        check_eq("E11: an unsafe event id is refused the same way, naming the event",
                 shown(res(proj, event={"session_id": "../x"})), ("", "event", "unsafe"))
        check_eq("E11: an unsafe id from the environment is refused, naming the variable",
                 shown(res(proj, env={NAMES[1]: "a/b"})), ("", f"env:{NAMES[1]}", "unsafe"))
        say = SI.refusal(res(proj, explicit="a/b"), SCRIPT)
        check("E11: the refusal for an unsafe id names the source and the rule, and offers no placeholder",
              "the `--session` argument" in say and "1 to 128 characters" in say and "an id a person gives you" in say and "<" not in say, say)


# --- the receipt reader: E4-E8, E14, E17 ----------------------------------------------------------------------

def receipt_reader() -> None:
    with world() as (_home, proj):
        folder = spool_dir()
        mine = receipt(folder, "own", cwds=[proj], age=WARM)
        check_eq("E4 boundary: a receipt aged exactly warm_seconds counts", shown(res(proj)), ("own", "receipt", "none"))
        os.utime(mine, (NOW - WARM - 0.001, NOW - WARM - 0.001))
        check_eq("E4 boundary: warm_seconds + 0.001 does not: an old receipt is never taken", shown(res(proj)), ("", "none", "missing"))
        os.utime(mine, (NOW - 1, NOW - 1))
        check_eq("E4: a young one counts", shown(res(proj)), ("own", "receipt", "none"))
        check_eq("E4: the same receipt read through the hook-event shape (no event id) names the source `receipt`", res(proj)["source"], "receipt")
        # E6: a warm receipt of another session in ANOTHER folder is ignored (the control of E5)
        elsewhere = temp_dir("qa-sid-else-")
        try:
            receipt(folder, "other", cwds=[elsewhere], age=0.5)
            check_eq("E6: another session's warm receipt in a different cwd is ignored; the own id resolves (the control of E5)",
                     shown(res(proj)), ("own", "receipt", "none"))
            check_eq("E6: ...and the same other receipt serves the reader that runs in ITS folder", shown(res(elsewhere)), ("other", "receipt", "none"))
            # E5: the same folder, two sessions, both naming the script: never chosen between
            receipt(folder, "rival", cwds=[proj], age=0.1)
            got = res(proj)
            check_eq("E5: two sessions ran the script in this cwd within the window: ambiguous, no id", shown(got), ("", "none", "ambiguous"))
            check_eq("E5: ...a receipt ambiguity carries no `conflict`", got["conflict"], None)
            say = SI.refusal(got, SCRIPT)
            check("E5: ...and the refusal says two sessions ran it here, and to run it again as its own shell call",
                  "Two or more sessions ran activity_capture.py" in say and "as its own shell call" in say, say)
            check_eq("E5: a receipt of another SCRIPT never counts for this reader", shown(res(proj, script="host_probe.py")), ("", "none", "missing"))
            receipt(folder, "probe-owner", script="host_probe.py", cwds=[proj], age=0.1)
            check_eq("E5: ...and a receipt of this script's own name does, for its reader", shown(res(proj, script="host_probe.py")), ("probe-owner", "receipt", "none"))
        finally:
            cleanup(elsewhere)

    # E14: what cannot prove its script and its folder never counts; the same dir with a good receipt is the control
    with world() as (_home, proj):
        folder = spool_dir()
        folder.mkdir(parents=True)
        (folder / "pretool-0123456789abcdef.json").write_text(json.dumps({"session_id": "legacy", "script": SCRIPT, "cwds": [str(proj)]}), encoding="utf-8")
        os.utime(folder / "pretool-0123456789abcdef.json", (NOW - 1, NOW - 1))
        receipt(folder, "no-script", cwds=[proj], name="pretool-aaaa-no-script.json", script="")
        data = json.loads((folder / "pretool-aaaa-no-script.json").read_text(encoding="utf-8"))
        data.pop("script")
        (folder / "pretool-aaaa-no-script.json").write_text(json.dumps(data), encoding="utf-8")
        os.utime(folder / "pretool-aaaa-no-script.json", (NOW - 1, NOW - 1))
        p = receipt(folder, "no-cwds", name="pretool-bbbb-no-cwds.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        data.pop("cwds")
        p.write_text(json.dumps(data), encoding="utf-8")
        os.utime(p, (NOW - 1, NOW - 1))
        receipt(folder, "empty-cwds", cwds=[], name="pretool-cccc-empty-cwds.json")
        broken = folder / "pretool-dddd-broken.json"
        broken.write_text("{nope", encoding="utf-8")
        os.utime(broken, (NOW - 1, NOW - 1))
        receipt(folder, "blank-id", cwds=[proj], name="pretool-eeee-blank-id.json")
        data = json.loads((folder / "pretool-eeee-blank-id.json").read_text(encoding="utf-8"))
        data["session_id"] = " "
        (folder / "pretool-eeee-blank-id.json").write_text(json.dumps(data), encoding="utf-8")
        os.utime(folder / "pretool-eeee-blank-id.json", (NOW - 1, NOW - 1))
        check_eq("E14: a legacy name, a receipt with no script, no cwds, empty cwds, a blank id or broken JSON never counts",
                 shown(res(proj)), ("", "none", "missing"))
        receipt(folder, "good", cwds=[proj], age=1)
        check_eq("E14 control: the same folder with one good receipt resolves it", shown(res(proj)), ("good", "receipt", "none"))

    # E17: a directory the receipt does not prove
    with world() as (_home, proj):
        sub = proj / "sub"
        sub.mkdir()
        receipt(spool_dir(), "own", cwds=[proj], age=1)
        check_eq("E17: running in a directory that is not among the receipt's cwds: the receipt does not count", shown(res(sub)), ("", "none", "missing"))
        check_eq("E17: ...and in one that is, it does", shown(res(proj)), ("own", "receipt", "none"))
        receipt(spool_dir(), "own2", cwds=[sub, proj], age=1)
        check("E17: ...a receipt that lists several directories counts for each of them (two sessions: ambiguous, not one of them chosen)",
              shown(res(sub)) == ("own2", "receipt", "none") and res(proj)["problem"] == "ambiguous", str(shown(res(proj))))

    # E8: the scan limit
    limit = RULES["scan_limit"]
    with world() as (_home, proj):
        others = temp_dir("qa-sid-others-")
        try:
            for n in range(limit - 1):
                receipt(spool_dir(), f"other-{n}", cwds=[others], age=1 + n * 0.01)
            receipt(spool_dir(), "own", cwds=[proj], age=5)
            check_eq(f"E8 boundary: exactly {limit} warm files (19 other sessions elsewhere plus the own, no further) resolve",
                     shown(res(proj)), ("own", "receipt", "none"))
            extra = receipt(spool_dir(), "one-too-many", cwds=[others], age=0.5)
            check_eq(f"E8 beyond: {limit + 1} warm files of distinct sessions, the own one past the limit and so never read: ambiguous - uniqueness is never claimed over files that were not read",
                     shown(res(proj)), ("", "none", "ambiguous"))
            check_eq("E8 beyond: ...and the environment does not rescue it (ambiguous with any E)", shown(res(proj, env={NAMES[0]: "own"})), ("", "none", "ambiguous"))
            os.utime(extra, (NOW - WARM - 5, NOW - WARM - 5))
            check_eq("E8: the extra file, no longer warm, is no problem (the limit is about warm files)", shown(res(proj)), ("own", "receipt", "none"))
        finally:
            cleanup(others)

    # E9: config appears mid-session: the reader reads the state folder and the spool
    with world() as (_home, _proj):
        root = temp_project("qa-sid-onboarded-")
        try:
            receipt(spool_dir(), "mid", cwds=[root], age=3)
            check_eq("E9: before config.json exists the receipt is in the spool: read", shown(res(root)), ("mid", "receipt", "none"))
            receipt(state_dir(root), "mid", cwds=[root], age=1)
            check_eq("E9: after it, the receipt is in state/ as well: the same session in both folders is ONE id", shown(res(root)), ("mid", "receipt", "none"))
            (spool_dir() / f"pretool-{key_of('mid')}-{Path(SCRIPT).stem}.json").unlink()
            check_eq("E9: ...and the state folder alone serves", shown(res(root)), ("mid", "receipt", "none"))
            receipt(spool_dir(), "rival", cwds=[root], age=2)
            check_eq("E9: two sessions, one in each folder: ambiguous", shown(res(root)), ("", "none", "ambiguous"))
        finally:
            cleanup(root)


# --- E10, E23: the agreement rule ---------------------------------------------------------------------------

def agreement() -> None:
    with world() as (_home, proj):
        def reset():
            for path in spool_dir().glob("pretool-*-*.json"):
                path.unlink()
        a, b = NAMES[0], NAMES[1]
        receipt(spool_dir(), "R", cwds=[proj], age=1)
        check_eq("E23: R unique, E empty -> R (source receipt)", shown(res(proj)), ("R", "receipt", "none"))
        check_eq("E23: R unique, E = {R} -> R", shown(res(proj, env={a: "R"})), ("R", "receipt", "none"))
        check_eq("E23: R unique, E = {R, R} (the same id in two variables counts once) -> R", shown(res(proj, env={a: "R", b: "R"})), ("R", "receipt", "none"))
        got = res(proj, env={a: "X"})
        check_eq("E23/E10: R unique, E = {X != R} -> ambiguous (the receipt does not override the environment, nor the reverse)", shown(got), ("", "none", "ambiguous"))
        check_eq("E23: ...and `conflict` names the variable", got["conflict"], [f"{a}=X"])
        say = SI.refusal(got, SCRIPT)
        check("E23: ...the refusal says the receipt and the variable name different sessions, and to start from a fresh terminal if it repeats",
              f"{a} name different sessions" in say and "fresh terminal" in say and "own shell call" in say, say)
        check_eq("E23: R unique, E = {R, Y}: R is among E's ids -> R", shown(res(proj, env={a: "R", b: "Y"})), ("R", "receipt", "none"))
        reset()
        check_eq("E23: R none, E = {} -> missing", shown(res(proj)), ("", "none", "missing"))
        check_eq("E23: R none, E = {X} -> X, the source names the first variable that holds it", shown(res(proj, env={b: "X"})), ("X", f"env:{b}", "none"))
        check_eq("E23: ...the same id in two variables is one id, the source the first by the rules' order", shown(res(proj, env={a: "X", NAMES[2]: "X"})), ("X", f"env:{a}", "none"))
        got = res(proj, env={a: "X", b: "Y"})
        check_eq("E23: R none, E = {X, Y} -> ambiguous, `conflict` names both", (shown(got), got["conflict"]), (("", "none", "ambiguous"), [f"{a}=X", f"{b}=Y"]))
        check_eq("E23: a variable that is empty or blank is no id", shown(res(proj, env={a: "  ", b: ""})), ("", "none", "missing"))
        receipt(spool_dir(), "R1", cwds=[proj], age=1)
        receipt(spool_dir(), "R2", cwds=[proj], age=1)
        check_eq("E23: R ambiguous with any E -> ambiguous", shown(res(proj, env={a: "R1"})), ("", "none", "ambiguous"))


# --- the missing door (critic t-544 F1) and no home directory (F2) -------------------------------------------

def missing_door_and_no_home() -> None:
    with world() as (home, proj):
        spaced = proj / "a project with a space"
        spaced.mkdir()
        old = os.getcwd()
        os.chdir(spaced)
        try:
            say = SI.refusal(res(Path(os.getcwd())), SCRIPT)
            door = f'`cd "{Path(os.getcwd()).as_posix()}"`'
        finally:
            os.chdir(old)
        check_in("F1: the missing door quotes the directory and spells it with forward slashes (a backslash is eaten by Git Bash, a space breaks PowerShell)", door, say)
        check("F1: ...no backslash inside the cd command", "\\" not in say.split("`cd ")[1].split("`")[0], say)
    with world() as (home, proj):
        names = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
        saved = {k: os.environ.get(k) for k in names}

        def no_home() -> Path:
            # the world with no home directory, on every platform: on Windows Path.home() raises once
            # USERPROFILE / HOMEDRIVE / HOMEPATH are gone, on Linux it falls back to the passwd database
            # and never raises (CI red on 30b6a26: 158/159) - the contract under test is spool_root()
            # raising RuntimeError, so the test raises it itself and strips the variables as well
            raise RuntimeError("Could not determine home directory.")

        SI.spool_root = no_home
        try:
            for key in names:
                os.environ.pop(key, None)
            try:
                got = SI.resolve({}, "", SCRIPT, cwd=str(proj), now=NOW, rules=RULES, env={})
                err = ""
            except Exception as exc:  # noqa: BLE001
                got, err = None, repr(exc)
            check_eq("F2: with no home directory resolve raises nothing and refuses (missing)", (err, got and got["problem"]), ("", "missing"))
            check_in("F2: ...and says the spool was not looked at", "no home directory: the spool was not looked at", " ".join(got["checked"]) if got else "")
            alone = SI.resolve({}, "", SCRIPT, cwd=str(proj), now=NOW, rules=RULES, env={NAMES[0]: "env-id"})
            check_eq("F2: ...the environment still answers", shown(alone), ("env-id", f"env:{NAMES[0]}", "none"))
        finally:
            SI.spool_root = REAL_SPOOL_ROOT
            for key, value in saved.items():
                os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)


# --- rules missing: E13 -----------------------------------------------------------------------------------

def rules_missing() -> None:
    with world() as (_home, proj):
        saved = SI.load_rules
        SI.load_rules = lambda path=None: None
        try:
            SI.write_receipt(proj, event_of("s", "python activity_capture.py", proj))
            check_eq("E13: with the rules unreadable the writer writes nothing", docs(spool_dir()), [])
            got = SI.resolve({}, "", SCRIPT, cwd=str(proj), now=NOW, env={NAMES[0]: "X"})
            check_eq("E13: ...and nothing is guessed from the environment: rules_unreadable, no id", shown(got), ("", "none", "rules_unreadable"))
            check_eq("E13: ...an explicit id still works", SI.resolve({}, "ok", SCRIPT, env={})["session_id"], "ok")
            check_eq("E13: ...and the hook event's id", SI.resolve({"session_id": "ev"}, "", SCRIPT, env={})["session_id"], "ev")
            say = SI.refusal(got, SCRIPT)
            check("E13: the refusal names the data file and its owner", "session-identity.json" in say and "owner: factory" in say, say)
        finally:
            SI.load_rules = saved


# --- the writer: K3, E1, E2, E7, E15, E16, E21, E22, E25 ----------------------------------------------------

def writer() -> None:
    with world() as (_home, proj):
        cmd = "python scripts/activity_capture.py --action start --type story"
        SI.write_receipt(proj, event_of("s-w", cmd, proj), rules=RULES)
        got = docs(spool_dir())
        check_eq("K3/E1: before config.json exists the receipt goes to the spool, one file per session and script",
                 [(d["session_id"], d["script"]) for d in got], [("s-w", "activity_capture.py")])
        check_eq("E1: ...the project is not touched: no qa-factory/ appears", (proj / "qa-factory").exists(), False)
        check_eq("K3: ...the name is pretool-<sha16 of the session>-<script stem>.json",
                 [p.name for p in spool_dir().glob("*.json")], [f"pretool-{key_of('s-w')}-activity_capture.json"])
        check("K3: ...it carries the absolute cwds, the command (400 characters at most) and the time",
              same_paths(got[0]["cwds"], [proj]) and got[0]["command"] == cmd and "observed_at" in got[0], str(got[0]))
        SI.write_receipt(proj, event_of("s-w", "x " * 400 + "activity_capture.py", proj), rules=RULES)
        check_eq("K3: a command longer than 400 characters is cut at 400", len(docs(spool_dir())[0]["command"]), 400)

        # E2: a command that names no reader script writes nothing, and the prefilter keeps the writer from being called
        before = sorted((p.name, p.read_text(encoding="utf-8")) for p in spool_dir().glob("*"))
        SI.write_receipt(proj, event_of("s-w", "git status", proj), rules=RULES)
        SI.write_receipt(proj, event_of("s-w", "echo hi", proj), rules=RULES)
        SI.write_receipt(proj, event_of("s-unrelated", "git status", proj), rules=RULES)
        check_eq("E2/E7: an unrelated command writes nothing (not even for another session) and does not overwrite the session's receipt",
                 sorted((p.name, p.read_text(encoding="utf-8")) for p in spool_dir().glob("*")), before)
        check_eq("E7: ...the own receipt still resolves after the session's next unrelated call", res(proj, now=time.time())["session_id"], "s-w")
        calls = []
        saved = SI.write_receipt
        SI.write_receipt = lambda *a, **k: calls.append(a)
        try:
            TH._write_pretool_receipt(proj, event_of("s-w", "git status", proj), json.dumps(event_of("s-w", "git status", proj)))
            check_eq("E2: telemetry_hook's prefilter: raw text naming no reader script never reaches the writer", calls, [])
            TH._write_pretool_receipt(proj, event_of("s-w", cmd, proj), json.dumps(event_of("s-w", cmd, proj)))
            check_eq("E2 control: the same call with a reader script's name does", len(calls), 1)
        finally:
            SI.write_receipt = saved

        # nothing without a session, a command or a named script
        fresh = spool_dir().parent / "fresh"
        SI.spool_root = lambda: fresh
        SI.write_receipt(proj, event_of("", cmd, proj), rules=RULES)
        SI.write_receipt(proj, event_of("s", "", proj), rules=RULES)
        SI.write_receipt(proj, {"hook_event_name": "PreToolUse", "session_id": "s", "tool_input": "not a call"}, rules=RULES)
        check_eq("K3: no session id, no command, or an unreadable tool_input: nothing is written", fresh.exists(), False)
        SI.spool_root = lambda: _home / ".qa-factory" / "spool"

        # one receipt per named script of one command
        SI.write_receipt(proj, event_of("s-two", "python activity_capture.py && python host_probe.py --prepare", proj), rules=RULES)
        check_eq("K3: a command naming two reader scripts leaves one receipt for each",
                 sorted(d["script"] for d in docs(spool_dir()) if d["session_id"] == "s-two"), ["activity_capture.py", "host_probe.py"])

    # K3: after config the receipt goes to state/, and the spool is not used
    with world() as (_home, _proj):
        root = temp_project("qa-sid-onb-")
        try:
            SI.write_receipt(root, event_of("s-on", "python activity_capture.py", root), rules=RULES)
            check_eq("K3/E9: once config.json exists the receipt goes to qa-factory/state/host-receipts/ and not to the spool",
                     (len(docs(state_dir(root))), docs(spool_dir())), (1, []))
        finally:
            cleanup(root)

    # E16: a write that fails is silent
    with world() as (home, proj):
        blocker = home / "blocker"
        blocker.write_text("a file where the spool folder should be", encoding="utf-8")
        SI.spool_root = lambda: blocker / "spool"
        try:
            SI.write_receipt(proj, event_of("s", "python activity_capture.py", proj), rules=RULES)
            TH._write_pretool_receipt(proj, event_of("s", "python activity_capture.py", proj), "activity_capture.py")
            check("E16: a receipt that cannot be written raises nothing (the hook never changes the tool call's outcome)", True)
        except Exception as exc:  # noqa: BLE001
            check("E16: a receipt that cannot be written raises nothing", False, repr(exc))
        check_eq("E16: ...and the reader then falls to the environment", shown(res(proj, env={NAMES[1]: "from-env"})), ("from-env", f"env:{NAMES[1]}", "none"))


def prune() -> None:
    now = float(int(time.time()))
    limit = RULES["spool_prune_days"] * DAY
    for label, make in (("the spool", lambda home, root: spool_dir()), ("state/host-receipts", lambda home, root: state_dir(root))):
        with world() as (home, _proj):
            root = temp_project("qa-sid-prune-")
            try:
                folder = make(home, root)
                dest_root = root if folder == state_dir(root) else _proj
                ev = event_of("s-new", "python activity_capture.py", dest_root)
                kept = receipt(folder, "s-at", cwds=[root], age=limit, now=now, name="pretool-at-boundary.json")
                gone = receipt(folder, "s-over", cwds=[root], age=limit + 1, now=now, name="pretool-over-boundary.json")
                SI.write_receipt(dest_root, ev, rules=RULES, now=now)
                check_eq(f"E15 boundary ({label}): a file aged exactly spool_prune_days is kept, one second older is deleted",
                         (kept.exists(), gone.exists()), (True, False))
                old = [receipt(folder, f"old-{n}", cwds=[root], age=limit + 10, now=now, name=f"pretool-old{n:03d}-x.json") for n in range(51)]
                warm = [receipt(folder, "s-warm", cwds=[root], age=age, now=now, name=f"pretool-warm{age}-x.json") for age in (WARM, DAY)]
                SI.write_receipt(dest_root, ev, rules=RULES, now=now)
                check_eq(f"E15 boundary ({label}): at most 50 deletions per call: 51 stale files, one call, one is left", sum(p.exists() for p in old), 1)
                SI.write_receipt(dest_root, ev, rules=RULES, now=now)
                check_eq(f"E15 ({label}): ...the next call takes the rest", sum(p.exists() for p in old), 0)
                check_eq(f"E15 ({label}): ...a warm receipt (30 s, a day) is never pruned, and the call's own receipt is written",
                         ([p.exists() for p in warm], (folder / f"pretool-{key_of('s-new')}-activity_capture.json").is_file()), ([True, True], True))
            finally:
                cleanup(root)
    # E25: the pruning is the writer's own receipts only
    with world() as (_home, _proj):
        root = temp_project("qa-sid-prune-own-")
        try:
            folder = state_dir(root)
            folder.mkdir(parents=True, exist_ok=True)
            others = []
            for name in ("package-aaaaaaaaaaaaaaaa.json", "guard-parse-qa.json", "0123456789abcdef.json", "pretool-0123456789abcdef.json", "host-probe-note.txt"):
                p = folder / name
                p.write_text("{}", encoding="utf-8")
                os.utime(p, (time.time() - 30 * DAY, time.time() - 30 * DAY))
                others.append(p)
            SI.write_receipt(root, event_of("s", "python activity_capture.py", root), rules=RULES)
            check_eq("E25: pruning never touches package-*, guard-parse-*, <hash>.json or the legacy pretool-<hash>.json receipts (ten times past the limit)",
                     [p.exists() for p in others], [True] * len(others))
        finally:
            cleanup(root)


# --- E21, E22: the cwds the writer records ---------------------------------------------------------------------

def wipe() -> None:
    for path in list(spool_dir().glob("*.json")) if spool_dir().is_dir() else []:
        path.unlink()


def cwds_of(proj, command, tool_input=None, script=SCRIPT) -> list:
    wipe()
    SI.write_receipt(proj, event_of("s-cwd", command, proj, tool_input), rules=RULES)
    found = [d["cwds"] for d in docs(spool_dir()) if d["script"] == script]
    return found[0] if found else None


def cwd_walk() -> None:
    with world() as (home, proj):
        a, b = temp_dir("qa-sid-a-"), temp_dir("qa-sid-b-")
        try:
            c = f"python scripts/{SCRIPT} --action start"
            check("E21: with no cd and no workdir the cwds are the event's cwd alone", same_paths(cwds_of(proj, c), [proj]))
            check("E21: Codex `workdir` (absolute) follows the event's cwd",
                  same_paths(cwds_of(proj, c, {"cmd": c, "workdir": str(a)}), [proj, a]))
            check("E21: ...a relative `workdir` is resolved against the event's cwd", same_paths(cwds_of(proj, c, {"cmd": c, "workdir": "sub"}), [proj, proj / "sub"]))
            check("E21: `cd X && python ...`", same_paths(cwds_of(proj, f'cd "{a}" && {c}'), [proj, a]))
            check("E21: `cd /d X & python ...` (cmd's drive switch is not the target)", same_paths(cwds_of(proj, f'cd /d {a} & {c}'), [proj, a]))
            check("E21: `Set-Location X; python ...`", same_paths(cwds_of(proj, f"Set-Location {a}; {c}"), [proj, a]))
            check("E21: the verb is case-insensitive", same_paths(cwds_of(proj, f"SET-LOCATION {a}; {c}"), [proj, a]))
            check("E21: `pushd X`", same_paths(cwds_of(proj, f"pushd {a}\n{c}"), [proj, a]))
            check("E21: `Set-Location -Path X` skips the option", same_paths(cwds_of(proj, f"Set-Location -Path {a}; {c}"), [proj, a]))
            check("E21: a chain `cd a; cd rel` keeps each target, the second resolved against the first",
                  same_paths(cwds_of(proj, f"cd {a}; cd rel; {c}"), [proj, a, Path(a) / "rel"]))
            check("E21: a quoted path with spaces is one word", same_paths(cwds_of(proj, f'cd "{a}/with space" && {c}'), [proj, Path(a) / "with space"]))
            check("E21: `cd ~/p` is the home (the redirected one) plus p", same_paths(cwds_of(proj, f"cd ~/p && {c}"), [proj, Path(home) / "p"]))
            if os.name == "nt":
                check("E21: `cd /c/p` on Windows is C:/p", same_paths(cwds_of(proj, f"cd /c/p && {c}"), [proj, "C:/p"]))
            else:
                print("INFO: E21 `cd /c/p` is a Windows spelling: not run on this platform")
            check("E21: `cd $DIR` adds nothing", same_paths(cwds_of(proj, f"cd $DIR && {c}"), [proj]))
            check("E21: `cd %X%` adds nothing", same_paths(cwds_of(proj, f"cd %X% && {c}"), [proj]))
            check("E21: `cd -` adds nothing", same_paths(cwds_of(proj, f"cd - && {c}"), [proj]))
            check("E21: a backtick adds nothing", same_paths(cwds_of(proj, f"cd `pwd` && {c}"), [proj]))
            check("E21: an unfollowed target stops the walk: what comes after it is not added",
                  same_paths(cwds_of(proj, f"cd $D; cd {a}; {c}"), [proj]))
            check("E21: `cd` with no target adds nothing", same_paths(cwds_of(proj, f"cd && {c}"), [proj]))
            check("E21: a cd AFTER the script's name is ignored", same_paths(cwds_of(proj, f"{c} && cd {a}"), [proj]))
            check("E21: the walk is per script: a cd between two scripts counts for the second only",
                  (same_paths(cwds_of(proj, f"python activity_capture.py && cd {a} && python host_probe.py", script="activity_capture.py"), [proj])
                   and same_paths(cwds_of(proj, f"python activity_capture.py && cd {a} && python host_probe.py", script="host_probe.py"), [proj, a])))
            wipe()
            SI.write_receipt(proj, event_of("s-cd", f'cd "{a}" && {c}', proj), rules=RULES)
            check_eq("E21: the receipt then serves a reader that runs in the directory the cd led to", res(a, now=time.time())["session_id"], "s-cd")
            check_eq("E21/E17: ...and still serves the event's own cwd", res(proj, now=time.time())["session_id"], "s-cd")
        finally:
            cleanup(a)
            cleanup(b)


def code_mode() -> None:
    with world() as (_home, proj):
        command = f"python scripts/{SCRIPT} --action start --type story"
        source = "text(await tools.exec_command(" + json.dumps({"cmd": command}) + "));"
        for label, tool_input in (("an object with `input`", {"input": source}), ("plain text", source)):
            wipe()
            SI.write_receipt(proj, event_of("s-code", "", proj, tool_input, name="functions.exec"), rules=RULES)
            got = docs(spool_dir())
            check(f"E22: a Codex code-mode functions.exec wrapper ({label}) gives a receipt, read the way host_probe reads the command",
                  [(d["session_id"], d["script"]) for d in got] == [("s-code", SCRIPT)] and command in got[0]["command"], str(got))
        check_eq("E22: ...and the reader resolves it", res(proj, now=time.time())["session_id"], "s-code")


# --- K5: onboard_apply's own session (E18) ---------------------------------------------------------------------

def own_session() -> None:
    here = Path(os.getcwd())
    script = "onboard_apply.py"
    a, b = NAMES[0], NAMES[1]
    now = time.time()
    with world() as (_home, _proj):
        check_eq("K5: no receipt and no variable: ''", OA._own_session(), "")
    with world() as (_home, _proj):
        receipt(spool_dir(), "own", script=script, cwds=[here], age=1, now=now)
        check_eq("K5: _own_session resolves from the receipt alone (a mutation that reads the environment only dies here)", OA._own_session(), "own")
    with world({"CLAUDE_SESSION_ID": "env-own"}) as (_home, _proj):
        check_eq("K-OWN: the environment alone still resolves", OA._own_session(), "env-own")
    with world({a: "own"}) as (_home, _proj):
        receipt(spool_dir(), "own", script=script, cwds=[here], age=1, now=now)
        check_eq("K5: a receipt and the environment that agree resolve", OA._own_session(), "own")
    # the adversarial inputs: each must give '' (a foreign id would let a foreign live writer pass)
    with world({a: "inherited"}) as (_home, _proj):
        receipt(spool_dir(), "own", script=script, cwds=[here], age=1, now=now)
        check_eq("E18 input 1: an inherited id in the environment and the own warm receipt naming a different id -> ''", OA._own_session(), "")
    with world({a: "own"}) as (_home, _proj):
        receipt(spool_dir(), "foreign", script=script, cwds=[here], age=1, now=now)
        check_eq("E18 input 2: the own receipt absent, a foreign warm receipt in the same cwd, the correct id in the environment -> '' (receipt wins over env: the mutation dies here)",
                 OA._own_session(), "")
    with world({a: "x", b: "y"}) as (_home, _proj):
        check_eq("E18 input 3: two environment ids that disagree -> ''", OA._own_session(), "")
    with world() as (_home, _proj):
        receipt(spool_dir(), "own", script=script, cwds=[here], age=WARM + 90, now=now)
        check_eq("E18 input 4: a stale own receipt with nothing in the environment -> ''", OA._own_session(), "")
    with world({a: "a/b"}) as (_home, _proj):
        check_eq("E18 input 5: an unsafe id -> ''", OA._own_session(), "")
    with world({a: "x"}) as (_home, _proj):
        receipt(spool_dir(), "x", script=script, cwds=[here], age=1, now=now)
        receipt(spool_dir(), "y", script=script, cwds=[here], age=1, now=now)
        check_eq("E18: two sessions' receipts in the same cwd -> ''", OA._own_session(), "")


# --- K6: the skill texts ----------------------------------------------------------------------------------------



def skill_texts() -> None:
    skills = PLUGIN_ROOT / "skills"
    # the per-file "no larger than before" pins of B-410's own edit were dropped: another node's
    # legitimate line (B-412's Arguments line, +77 B) made the onboarding pin a CI red on c1ce205
    # (11626 <= 11589); the cap that holds across nodes is the 19000-byte limit selftest --limits
    # enforces, and A22/A25 bound the dispatch weight (test_audit_rules)
    for name in ("qa-story", "qa-doctor", "qa-onboarding"):
        raw = (skills / name / "SKILL.md").read_bytes()
        check(f"K6: {name}/SKILL.md is within the 19000-byte cap ({len(raw)})", len(raw) <= 19000, str(len(raw)))
    # the "finds its own session" sentence of qa-story and qa-onboarding is a row of design/role-rules.json


def receipt_named() -> None:
    """XT1-2 m-7: `explore_step.py` is a receipt script - a Bash call naming it leaves a receipt, and the script finds its session by it."""
    import time
    with world() as (_home, proj):
        check("receipt_named: explore_step.py is in receipt_scripts", "explore_step.py" in RULES["receipt_scripts"])
        SI.write_receipt(proj, event_of("s-explore", 'python scripts/explore_step.py frame "add to cart"', proj), rules=RULES)
        got = res(proj, now=time.time(), script="explore_step.py")
        check_eq("receipt_named: the receipt resolves the session of explore_step.py", shown(got), ("s-explore", "receipt", "none"))


def main() -> None:
    for step in (rules_file, spool_location, given_ids, receipt_reader, agreement, missing_door_and_no_home, rules_missing, writer, prune, cwd_walk, code_mode, own_session, skill_texts, receipt_named):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - one step crashing must not hide the others
            check(f"{step.__name__} ran to the end", False, f"{type(exc).__name__}: {exc}")
    finish("test_session_identity")


if __name__ == "__main__":
    main()
