"""OH3-29: `onboarding_notes.py close` runs the first reader of the config (scripts/onboarding_first_reader.py).

Keys R1-R13 (r0107-oh3-29-33.md section 5 N1 as the plan critic's review rewrote it): a healthy config closes; the
inputs `one_test_argv` must refuse and the four it is known to pass; an empty `profiles` needs its record; a failed
readiness has a door (`first-reader-crash`); the wording of every door; a timeout; which record lifts which problem;
the door actually opened with the real `project_decisions.py` commands; absent / broken config, journal cells and
backlog; the position of the check in `cmd_close`; a healthy and a broken profile together; the command-line battery;
(the text of p4-generate.md is rows of design/role-rules.json).
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import config_contract  # noqa: E402
import onboard_apply as OA  # noqa: E402
import onboarding_first_reader as FR  # noqa: E402
import onboarding_notes as N  # noqa: E402
import project_decisions as PD  # noqa: E402

DATA = N.load_data()
GOOD = {"profile_id": "api", "commands": {"one_test": {"argv": ["pytest", "<test-file>"]}}}
UNSET = object()
NAME = "".join(chr(code) for code in (0x3c4, 0x3b5, 0x3c3, 0x3c4)) + "%s{0}"       # a non-ASCII id (Greek: the package has no Cyrillic) with format characters


# --------------------------------------------------------------------------------------- helpers

def call(root, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = N.main(["--root", str(root), *map(str, args)])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def readiness(ok=True, note=""):
    """`readiness.py` replaced by an answer (the launch itself is `OA._run_script`'s, proved by R4 and R6); the calls are listed."""
    calls = []
    saved = OA._run_script

    def fake(root, script, args=()):
        calls.append((script, tuple(args)))
        return {"step": script, "ok": ok, "rc": 0 if ok else 1, "note": note}
    OA._run_script = fake
    try:
        yield calls
    finally:
        OA._run_script = saved


def project(profiles=UNSET, raw=None) -> Path:
    root = temp_dir("qa-first-reader-")
    (root / "qa-factory").mkdir()
    path = root / "qa-factory" / "config.json"
    if raw is not None:
        path.write_bytes(raw)
    else:
        cfg = {"schema_version": 1}
        if profiles is not UNSET:
            cfg["profiles"] = profiles
        path.write_text(json.dumps(cfg), encoding="utf-8")
    return root


def problems(root) -> list:
    with readiness():
        return FR.problems(root)


def approve(root, ref):
    path = config_contract.approvals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"schema_version": 1, "approval_ref": ref, "status": "approved"}) + "\n")


def frozen(profiles=UNSET, raw=None, ref="r1") -> Path:
    """A project with its config and a run frozen at p4 under `ref`."""
    root = project(profiles, raw)
    assert call(root, "start", "--tree", "clean")[0] == 0
    approve(root, ref)
    code, _out, err = call(root, "phase", "--set", "p4", "--approval-ref", ref)
    assert code == 0, err
    return root


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "qa-factory").rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def pd(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "project_decisions.py"), "--root", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


def close_rows(root):
    path = root / "qa-factory" / "factory-backlog.md"
    path.write_text(path.read_text(encoding="utf-8").replace("| open |", "| resolved |"), encoding="utf-8")


def dd(ref):
    return lambda root: PD.upsert(root, field_refs=[ref], essence="x", asked="did you ask", scope="project", owner="user")


def fb(key, witness="w"):
    return lambda root: PD.add_finding(root, essence="x", scope="local-urgent", witness=witness, idempotency_key=key)


# --------------------------------------------------------------------------------------- R1, R11

def healthy_and_mixed() -> None:
    root = frozen([GOOD])
    try:
        before = (root / "qa-factory" / "state").exists()
        check_eq("R1: a healthy config, the REAL readiness.py: no problem", FR.problems(root), [])
        check("R1: ...the check left no readiness.json and no tracker receipt (--no-trace, no --write)",
              not (root / "qa-factory" / "state" / "readiness.json").exists()
              and not (root / "qa-factory" / "state" / "integrations").exists(), str(sorted(os.listdir(root / "qa-factory"))))
        code, out, err = call(root, "close", "--approval-ref", "r1")
        check_eq("R1: close passes and moves the run", (code, json.loads(out).get("closed")), (0, True))
        check("R1: state/ existed before the call exactly as after it", before == (root / "qa-factory" / "state").exists())
    finally:
        cleanup(root)
    broken = {"profile_id": "web", "commands": {"run": {"argv": ["npx", "x"]}}}
    root = project([GOOD, broken])
    try:
        found = problems(root)
        check("R11: a healthy and a broken profile: the refusal names the broken one only",
              len(found) == 1 and "profile web:" in found[0] and "profile api" not in found[0], str(found))
        with readiness() as calls:
            FR.problems(root)
        check_eq("R11/F-4: readiness is launched as `readiness.py --no-trace`, once", calls, [("readiness.py", ("--no-trace",))])
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R2

BAD = {
    "commands-list": {"profile_id": "p", "commands": []},
    "commands-number": {"profile_id": "p", "commands": 5},
    "commands-null": {"profile_id": "p", "commands": None},
    "no-commands": {"profile_id": "p"},
    "one_test-string": {"profile_id": "p", "commands": {"one_test": "pytest"}},
    "argv-string": {"profile_id": "p", "commands": {"one_test": {"argv": "pytest"}}},
    "argv-only-placeholder": {"profile_id": "p", "commands": {"one_test": {"argv": ["<test-file>"]}}},
    "argv-null-word": {"profile_id": "p", "commands": {"one_test": {"argv": [None]}}},
    "argv-empty": {"profile_id": "p", "commands": {"one_test": {"argv": []}}},
    "argv-blank-words": {"profile_id": "p", "commands": {"one_test": {"argv": [" ", ""]}}},
    "run-only": {"profile_id": "p", "commands": {"run": {"argv": ["pytest"]}}},        # F-3 (a): S5 builds a run from one_test only
    # r0107 F-5: S5 (`execution_request._command_from_profile`) refuses an `env` of these forms with the same words
    "env-string": {"profile_id": "p", "commands": {"one_test": {"argv": ["pytest", "x"], "env": "BAD"}}},
    "env-bad-name": {"profile_id": "p", "commands": {"one_test": {"argv": ["pytest", "x"], "env": {"A B": "{report_path}"}}}},
    "env-other-value": {"profile_id": "p", "commands": {"one_test": {"argv": ["pytest", "x"], "env": {"TOKEN": "secret"}}}},
}
# Known false passes (review F-6): the gate answers "a command is recorded", the launch check judges "it starts".
PASS = {
    "argv-number": [5],
    "argv-flag-then-placeholder": ["--file", "<x>"],
    "argv-report-holder": ["{report_path}"],
    "argv-spaced-placeholder": [" <x> "],
}
ENV_OK = {"profile_id": "p", "commands": {"one_test": {"argv": ["pytest", "x"], "env": {"REPORT": "{report_path}"}}}}


def argv_inputs() -> None:
    for label, profile in BAD.items():
        root = project([profile])
        try:
            found = problems(root)
            check(f"R2 [{label}]: a problem naming profile p", len(found) == 1 and found[0].startswith("profile p: "), str(found))
        finally:
            cleanup(root)
    for label, argv in PASS.items():
        root = project([{"profile_id": "p", "commands": {"one_test": {"argv": argv}}}])
        try:
            check_eq(f"R2 [{label}]: a known false pass (named in the module docstring), no problem", problems(root), [])
        finally:
            cleanup(root)
    root = project([ENV_OK])
    try:
        check_eq("R2 [env-report-holder]: an env that sets exactly {report_path} is a command S5 accepts: no problem", problems(root), [])
    finally:
        cleanup(root)
    source = (SCRIPTS / "onboarding_first_reader.py").read_text(encoding="utf-8")
    check("R2/AR-13: the module reads a command only through profile_contract.one_test_argv (no .get(\"commands\"))",
          'one_test_argv(profile, drop_placeholders=True)' in source and '.get("commands")' not in source)
    check("R2/AR-13 control: the same search finds the reader's call in readiness.py",
          "one_test_argv(profile, drop_placeholders=True)" in (SCRIPTS / "readiness.py").read_text(encoding="utf-8"))
    check("R2/AR-13: the module keeps no table parser of its own (PD.parse_rows / parse_findings only)",
          "PD.parse_rows" in source and "PD.parse_findings" in source and 'split("|")' not in source)


# --------------------------------------------------------------------------------------- R3

def empty_profiles() -> None:
    for label, make in (("empty list", lambda: project([])), ("no key", lambda: project())):
        root = make()
        try:
            found = problems(root)
            check(f"R3 [{label}]: without a record, a problem with both doors",
                  len(found) == 1 and "--field-ref /profiles " in found[0] and "--idempotency-key no-test-framework" in found[0], str(found))
            dd("/profiles")(root)
            check_eq(f"R3 [{label}]: an open DD on /profiles passes", problems(root), [])
        finally:
            cleanup(root)
        root = make()
        try:
            fb("no-test-framework")(root)
            check_eq(f"R3 [{label}]: an open finding no-test-framework passes", problems(root), [])
        finally:
            cleanup(root)
    for label, value in (("string", "x"), ("object", {"a": 1}), ("number", 3), ("null", None)):    # r0107 F-4: null is no list
        root = project(value)
        try:
            dd("/profiles")(root)
            fb("no-test-framework")(root)
            found = problems(root)
            check(f"R3 [{label}]: profiles that is not a list is refused, and no record lifts it",
                  len(found) == 1 and "expected a list of profile objects" in found[0], str(found))
        finally:
            cleanup(root)
    root = project([{"profile_id": "api"}])
    try:
        dd("/profiles")(root)
        fb("no-test-framework")(root)
        check("R3/F-2: /profiles and no-test-framework do not lift a broken profile of a NON-empty list",
              len(problems(root)) == 1)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R4, R6

def fake_readiness(text: str) -> Path:
    folder = temp_dir("qa-fake-readiness-")
    (folder / "readiness.py").write_text(text, encoding="utf-8")
    return folder


def crash_and_timeout() -> None:
    folder = fake_readiness("import sys\nraise RuntimeError('boom')\n")
    root = project([GOOD])
    saved = OA.HERE
    try:
        OA.HERE = folder
        found = FR.problems(root)
        check("R4: a readiness that crashes: one problem with its LAST line, not the traceback",
              len(found) == 1 and "readiness.py could not finish: RuntimeError: boom" in found[0] and "Traceback" not in found[0], str(found))
        check("R4: ...and no record, the refusal stands", len(found) == 1)
        fb("first-reader-crash")(root)
        check_eq("R4: ...an open finding first-reader-crash lifts it", FR.problems(root), [])
    finally:
        OA.HERE = saved
        cleanup(root)
        cleanup(folder)
    for length in (200, 201):
        folder = fake_readiness(f"import sys\nsys.stderr.write('q' * {length} + chr(10))\nsys.exit(1)\n")
        root = project([GOOD])
        try:
            OA.HERE = folder
            line = FR.problems(root)[0]
            check_eq(f"R4: a last line of {length} characters reaches the problem as {min(length, 200)} (the cut is _run_script's)",
                     ("q" * 200 in line, "q" * 201 in line), (True, False))
        finally:
            OA.HERE = saved
            cleanup(root)
            cleanup(folder)


def timeout() -> None:
    root = project([GOOD])
    saved = subprocess.run

    def hang(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 600)
    try:
        subprocess.run = hang
        found = FR.problems(root)
    finally:
        subprocess.run = saved
    try:
        check("R6: a readiness that times out is a problem (could not finish), never a pass",
              len(found) == 1 and "readiness.py could not finish: could not run" in found[0] and "--idempotency-key first-reader-crash" in found[0], str(found))
        fb("first-reader-crash")(root)
        check_eq("R6: ...with the crash door open it passes", problems(root), [])
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R5

def text_and_no_writes() -> None:
    root = frozen([{"profile_id": "api", "commands": {}}])
    try:
        before = tree_hash(root)
        with readiness():
            code, out, err = call(root, "close", "--approval-ref", "r1")
        check_eq("R5: a refusal is exit 2 and prints nothing on stdout", (code, out), (2, ""))
        for needle in ("the notes stay open", "profile api: no command that runs one test", "Fix it in qa-factory/config.json and close again",
                       "project_decisions.py --root . add --field-ref /profiles/0/commands/one_test/argv",
                       "--asked '<the question as it was put>'", "project_decisions.py --root . add-finding",
                       "--scope local-urgent", "--witness 'onboarding_notes.py close: ", "--idempotency-key launch-api`"):
            check(f"R5: the refusal carries `{needle}`", needle in err, err)
        check("R5: ...and no `...` stands in for a required flag", "..." not in err.replace("<the question as it was put>", ""), err)
        check_eq("R5: the hash of the whole qa-factory/ tree is equal before and after the refusal", tree_hash(root), before)
        doc = json.loads(call(root, "status")[1])
        check("R5: ...the run is open at p4 and nothing is in done/",
              doc["phase"] == "p4" and not (N.notes_dir(root, DATA) / "done").exists(), str(doc["phase"]))
    finally:
        cleanup(root)
    root = project([{"profile_id": "api"}, {"commands": {}}, 7])
    try:
        found = problems(root)
        check("R5: a profile with no profile_id gets only the DD door and the advice to name it",
              "profiles[1]: no command that runs one test" in found[1] and "give the profile a profile_id" in found[1]
              and "add-finding" not in found[1], found[1])
        check("R5: a profile that is not an object is named by its place", "profiles[2]: the profile is int; expected an object" in found[2], found[2])
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R7

def lifts(profiles, setup, expect_problems: int, label: str) -> None:
    root = project(profiles)
    try:
        setup(root)
        found = problems(root)
        check_eq(f"R7 [{label}]", len(found), expect_problems)
    finally:
        cleanup(root)


def which_record_lifts() -> None:
    one = [{"profile_id": "api"}]
    two = [GOOD, {"profile_id": "web"}]                   # the broken profile is at place 1
    for ref in ("/profiles/0", "/profiles/0/commands", "/profiles/0/commands/one_test", "/profiles/0/commands/one_test/argv", "profiles/0"):
        lifts(one, dd(ref), 0, f"DD {ref} lifts the profile at place 0")
    lifts(one, fb("launch-api"), 0, "finding launch-api lifts it")
    lifts(two, dd("/profiles/1"), 0, "DD /profiles/1 lifts the profile at place 1")
    lifts(two, dd("/profiles/0"), 1, "DD on ANOTHER profile (place 0) does not lift place 1")
    for ref in ("/profiles/0/selectors", "/profiles/0/commands/run/argv", "/profiles/0/commands/one_test/argv/0", "/profiles", "/profilesX",
                "/profiles/01", "/environment", "/profiles/1"):
        lifts(one, dd(ref), 1, f"DD {ref} does not lift place 0")

    def closed(setup):
        def run(root):
            setup(root)
            close_rows(root)
        return run
    lifts(one, closed(dd("/profiles/0")), 1, "a CLOSED DD does not lift")
    lifts(one, closed(fb("launch-api")), 1, "a CLOSED finding does not lift")
    lifts([{"profile_id": "a"}], fb("launch-ab"), 1, "a finding whose key has the profile's key as a PREFIX does not lift")
    lifts([{"profile_id": "ab"}], fb("launch-a"), 1, "a finding for launch-a does not lift launch-ab")
    lifts(one, fb("launch-other"), 1, "a finding for another profile does not lift")
    lifts(one, fb("other-key", witness="seen; idempotency:launch-api today"), 1, "a marker typed INSIDE the witness words does not lift")
    lifts([{"profile_id": "x\ny"}], fb("launch-x\ny"), 0, "an id with a line break: the finding's key is compared as the table reads it back")
    root = project(one)
    try:
        fb("launch-api")(root)
        close_rows(root)
        line = problems(root)[0]
        check("R7/F-1: a key held by a CLOSED finding: the refusal names FB-1 and its status",
              "FB-1" in line and "'resolved'" in line, line)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R8

def printed_door(err: str, subcommand: str, root) -> list:
    """The door command AS PRINTED in the refusal (the backticked span), split the way a shell splits it; only `--root .`
    is pointed at the test project. Nothing is typed by hand here (r0107 F-3): what a role would run is what runs."""
    for span in re.findall(r"`(project_decisions\.py [^`]*)`", err):
        words = shlex.split(span)
        if words[3] == subcommand:
            words[words.index("--root") + 1] = str(root)
            return words[1:]
    return []


def doors_opened_for_real() -> None:
    odd = "my api"                                         # a space, `&;`, `$` and a trailing period are all data in a door
    hostile = "a&b;rm $HOME."
    cases = [
        ("a DD after a person was asked", [{"profile_id": "api"}], "add", ["--asked", "which command starts the tests"]),
        ("a finding when nobody was asked", [{"profile_id": "api"}], "add-finding", []),
        ("a finding, an id with a space", [{"profile_id": odd}], "add-finding", []),
        ("a finding, an id with shell characters and a period", [{"profile_id": hostile}], "add-finding", []),
        ("a DD /profiles on an empty list", [], "add", ["--asked", "is there a test framework"]),
        ("a finding no-test-framework on an empty list", [], "add-finding", []),
    ]
    for label, profiles, sub, extra in cases:
        root = frozen(profiles)
        try:
            with readiness():
                code, out, err = call(root, "close", "--approval-ref", "r1")
                check(f"R8 [{label}]: before the door, close is refused", code == 2, err)
                command = printed_door(err, sub, root)
                check(f"R8 [{label}]: the refusal prints a `{sub}` door", bool(command), err)
                if extra:                                  # the question is the person's words: the one value the door cannot print
                    command[command.index("--asked") + 1] = extra[1]
                done = pd(root, *command)
                check(f"R8 [{label}]: the PRINTED command runs", done.returncode == 0, str(command) + done.stdout + done.stderr)
                code, out, err = call(root, "close", "--approval-ref", "r1")
                check_eq(f"R8 [{label}]: after the door, close passes", (code, json.loads(out).get("closed") if code == 0 else err), (0, True))
        finally:
            cleanup(root)
    root = frozen([GOOD])
    try:
        with readiness(ok=False, note="crash: not mine to fix"):
            code, out, err = call(root, "close", "--approval-ref", "r1")
            check("R8 [could not finish]: refused, and the refusal names the crash door",
                  code == 2 and "--idempotency-key first-reader-crash" in err and "crash: not mine to fix" in err, err)
            done = pd(root, *printed_door(err, "add-finding", root))
            check("R8 [could not finish]: the printed add-finding works", done.returncode == 0, done.stdout + done.stderr)
            code, out, err = call(root, "close", "--approval-ref", "r1")
            check_eq("R8 [could not finish]: after first-reader-crash, close passes", code, 0)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R9

def absent_broken_and_journal() -> None:
    root = temp_dir("qa-first-reader-")
    try:
        found = FR.problems(root)
        check("R9: no config: one problem naming the file and the door --phase early",
              len(found) == 1 and "no qa-factory/config.json yet" in found[0] and "--phase early" in found[0], str(found))
        check("R9/F-2: ...and the door carries --proposal <sealed.json> (onboard_apply refuses an apply without a config and a proposal)",
              "--proposal <sealed.json> --apply --approval-ref <ref> --phase early" in found[0], str(found))
    finally:
        cleanup(root)
    for label, raw in (("not JSON", b"{bad"), ("a list", b"[]"), ("empty file", b"")):
        root = project(raw=raw)
        try:
            dd("/profiles")(root)
            with readiness() as calls:
                found = FR.problems(root)
            check(f"R9 [{label}]: a problem of its own, readiness is not even launched, and an open DD /profiles does not lift it",
                  len(found) == 1 and "is not a JSON object" in found[0] and calls == [], str(found) + str(calls))
        finally:
            cleanup(root)
    bom = project(raw=b"\xef\xbb\xbf" + json.dumps({"profiles": [GOOD]}).encode("utf-8"))
    try:
        check_eq("R9: a BOM config is the project's config: no problem", problems(bom), [])
    finally:
        cleanup(bom)
    root = project([{"profile_id": "api"}])
    try:
        dd("/profiles/0")(root)
        path = root / "qa-factory" / "factory-backlog.md"
        path.write_text(path.read_text(encoding="utf-8").replace("/profiles/0", "doc:../escape"), encoding="utf-8")
        found = problems(root)
        check("R9: a field_refs cell that cannot be read: the refusal names the row, the profile problem stays",
              len(found) == 2 and any("row DD-1 of qa-factory/factory-backlog.md has a field_refs cell that cannot be read" in x for x in found), str(found))
    finally:
        cleanup(root)
    root = project([GOOD])
    try:
        (root / "qa-factory" / "factory-backlog.md").write_bytes(b"\xff\xfe not text")
        check_eq("R9: a healthy config is not refused for an unreadable journal (it is read only when a problem exists)", problems(root), [])
    finally:
        cleanup(root)
    root = project([{"profile_id": "api"}])
    try:
        (root / "qa-factory" / "factory-backlog.md").write_bytes(b"\xff\xfe not text")
        check_eq("R9: no journal that can be read: no record, the problem stands", len(problems(root)), 1)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R10

def position() -> None:
    root = frozen([{"profile_id": "api"}])
    try:
        with readiness() as calls:
            code, out, err = call(root, "close", "--approval-ref", "wrong")
        check("R10: a wrong approval ref keeps the old refusal and starts no probe",
              code == 2 and "is not the approval this run is frozen under" in err and calls == [], err + str(calls))
        notes = N.notes_dir(root, DATA)
        run = N.read_run(notes, DATA)
        progress = dict(run["progress"])
        progress["phase"] = "done"
        N._save_progress(notes, progress)
        with readiness() as calls:
            code, out, err = call(root, "close", "--approval-ref", "r1")
        check("R10: a run whose phase is already done in an open folder finishes without a second check",
              code == 0 and json.loads(out).get("closed") is True and calls == [], out + err + str(calls))
        with readiness() as calls:
            code, out, err = call(root, "close", "--approval-ref", "r1")
        check("R10: `already closed` starts no probe either (close stays idempotent)",
              code == 0 and json.loads(out).get("already") is True and calls == [], out + err + str(calls))
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- R12

def battery() -> None:
    many = [{"profile_id": f"p{i}"} for i in range(1000)]
    root = frozen(many)
    try:
        with readiness():
            code, out, err = call(root, "close", "--approval-ref", "r1")
        check("R12: 1000 broken profiles: 20 named, `+980 more`, exit 2",
              code == 2 and err.count("\n  - ") == 20 and "+980 more" in err, str(err.count("\n  - ")))
    finally:
        cleanup(root)
    for count, tail in ((20, False), (21, "+1 more")):
        root = frozen([{"profile_id": f"p{i}"} for i in range(count)])
        try:
            with readiness():
                code, out, err = call(root, "close", "--approval-ref", "r1")
            check_eq(f"R12: {count} problems: {count if count == 20 else 20} named" + (f" and `{tail}`" if tail else " and no `more`"),
                     (err.count("\n  - "), tail in err if tail else "more" in err), (20, bool(tail)))
        finally:
            cleanup(root)
    root = frozen([{"profile_id": "api", "commands": {"one_test": {"argv": {"a": {"b": [1]}}}}}])
    try:
        with readiness():
            code, out, err = call(root, "close", "--approval-ref", "r1")
        check("R12: a nested object where argv should be a list is a problem, not a crash",
              code == 2 and "profile api: commands.one_test.argv is" in err, err)
    finally:
        cleanup(root)
    root = frozen([{"profile_id": NAME}])
    try:
        env = dict(os.environ, PYTHONIOENCODING="ascii", PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "onboarding_notes.py"), "--root", str(root), "close", "--approval-ref", "r1"],
                              capture_output=True, env=env, timeout=300)
        text = done.stderr.decode("utf-8", errors="replace")
        check("R12: a non-ASCII id with % and {0} under PYTHONIOENCODING=ascii (REAL readiness): exit 2, the id printed, no traceback",
              done.returncode == 2 and NAME in text and "Traceback" not in text, str(done.returncode) + text[:300])
    finally:
        cleanup(root)
    root = frozen(raw=b"")
    try:
        code, out, err = call(root, "close", "--approval-ref", "r1")
        check("R12: an empty config file is a refusal naming the file, not a crash", code == 2 and "is not a JSON object" in err, err)
    finally:
        cleanup(root)


def main() -> None:
    healthy_and_mixed()
    argv_inputs()
    empty_profiles()
    crash_and_timeout()
    timeout()
    text_and_no_writes()
    which_record_lifts()
    doors_opened_for_real()
    absent_broken_and_journal()
    position()
    battery()
    finish("onboarding first reader")


if __name__ == "__main__":
    main()
