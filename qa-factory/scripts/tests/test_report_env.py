#!/usr/bin/env python3
"""EP1-22: a runner that names its report file by a variable (Playwright) writes a report S5 can read, and the probe judges
the FILE and nothing beside it.

  E-table      `command_env`: the shapes of an `env`, and the same three inputs through `validate_request`
  E-holders    `{report_path}` held by 0 / 1 / 2 places over the argv words AND the env values: `validate_request` and
               `s5_contract_refusals` agree (the twin)
  E-noreader   an `env` beside a pytest / none reporter is refused (a field nothing reads)
  E-run        `run_suite --request` sets the variable to the run's own file; the parent's environment keeps none
  E-order      HEADLESS of the environment is kept; a variable of the parent is overridden by the command's own
  E-identity   the digest of a command with an `env` is the same everywhere (the gate's manifest, the helper, the record)
  E-receipt    a receipt given for another `env` is not the same command; with no `env` the key is the one it always was
  E-entity     the probe reads the report FILE: an empty file, a missing one and a folder are `no_file`; a neighbour with a DOCTYPE
               is never read; the report itself with one is `unparsable`
  E-neighbour  no report, a valid neighbour: `no_file`, nothing tried, no fit, no command for the conductor to run
  E-cure       the Playwright row is data; `classify_cure` reads the flag AND the variable
  E-question   the question names the variable, in words that pass `human_text.problems`
  E-person     a line that starts with `NAME=value` is refused; a person's command takes the cure row's variable
  E-sample     the shipped sample of the shape passes S5's own contract
  E-data       the row is in `report-cures.json` and the scripts hold no framework word of it
  E-unread     an `env` that cannot be read: the command is not run and a line says so
"""
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in, cleanup, finish, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import profile_contract as PC  # noqa: E402
import execution_request as ER  # noqa: E402
import onboarding_probe as P  # noqa: E402
import gate_preflight  # noqa: E402
import test_execution_request as TE  # noqa: E402
import test_reporter_rehearsal as TR  # noqa: E402

VAR = "PLAYWRIGHT_JUNIT_OUTPUT_NAME"
HOLDER = "{report_path}"
# a runner that writes its JUnit report to the file a VARIABLE names (the shape of Playwright's own reporter)
WRITES_BY_VARIABLE = f"""import os, sys
from pathlib import Path
report = Path(os.environ["{VAR}"])
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text('<testsuite name="s" tests="1" failures="1" errors="0" skipped="0"><testcase classname="c" name="t"><failure message="red"/></testcase></testsuite>', encoding="utf-8")
sys.exit(1)
"""
WRITES_FOLDER = """import sys
from pathlib import Path
folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
(folder / "a.xml").write_text('<testsuite tests="1"><testcase classname="c" name="t"/></testsuite>', encoding="utf-8")
"""
WRITES_NEIGHBOUR = """import sys
from pathlib import Path
Path(sys.argv[1]).with_name("TESTS-chrome.xml").write_text('<testsuite tests="1"><testcase classname="c" name="t"/></testsuite>', encoding="utf-8")
"""
WRITES_NEIGHBOUR_DOCTYPE = """import sys
from pathlib import Path
Path(sys.argv[1]).with_name("TESTS-evil.xml").write_text('<!DOCTYPE a [<!ENTITY x "y">]><testsuite tests="1"><testcase classname="c" name="t"/></testsuite>', encoding="utf-8")
"""
WRITES_EMPTY = """import sys
from pathlib import Path
Path(sys.argv[1]).write_text("", encoding="utf-8")
"""
WRITES_OWN_DOCTYPE = """import sys
from pathlib import Path
Path(sys.argv[1]).write_text('<!DOCTYPE a [<!ENTITY x "y">]><testsuite tests="1"><testcase classname="c" name="t"/></testsuite>', encoding="utf-8")
"""


def spec(argv, env=None, **extra) -> dict:
    out = {"kind": "test", "scope": "selected", "argv": argv, "cwd": "."}
    if env is not None:
        out["env"] = env
    out.update(extra)
    return out


def table_checks() -> None:
    """E-table."""
    cases = [("no env", None, True), ("null", "NULL", True), ("empty object", {}, True), ("a list", [], False), ("a string", "x", False),
             ("a number", 3, False), ("nested 50", {"A": {"B": HOLDER}}, False), ("a Cyrillic name", {"\u0438\u043c\u044f": HOLDER}, False),
             ("a name with =", {"A=B": HOLDER}, False), ("a value without the holder", {"A": "value"}, False),
             ("a list as a value", {"A": [HOLDER]}, False), ("a prefix on the holder", {"A": "abc123" + HOLDER}, False),
             ("a path of this machine", {"A": "C:\\Users\\dev3\\" + HOLDER}, False), ("the holder twice", {"A": HOLDER + HOLDER}, False),
             ("an empty value", {"A": ""}, False), ("a trailing newline in the name (F4)", {"A\n": HOLDER}, False),
             ("a newline inside the name", {"A\nB": HOLDER}, False), ("exactly the holder", {"A": HOLDER}, True)]
    deep = {"A": HOLDER}
    for _ in range(50):
        deep = {"A": deep}
    cases.append(("nested 50 deep", deep, False))
    for label, env, ok in cases:
        command = {"argv": ["x"]} if env is None else {"argv": ["x"], "env": None if env == "NULL" else env}
        got, problem = PC.command_env(command)
        check_eq(f"E-table: {label}: readable or named", (problem == ""), ok)
        check_eq(f"E-table: {label}: never a half-read dict on a problem", (got == {}) if problem else True, True)
        errors = PC.validate_profile({"profile_id": "p", "commands": {"one_test": command}}, "p")
        check_eq(f"E-table: {label}: `validate_profile` says the same", any(e.startswith("p.commands.one_test.env") for e in errors), not ok)
    check_eq("E-table: a spec that is no object is no env and no crash", (PC.command_env(None), PC.command_env("x"), PC.command_env([1])),
             (({}, ""), ({}, ""), ({}, "")))
    # the same three bad inputs through the request validator
    for label, env in (("a prefix", {"A": "abc" + HOLDER}), ("the holder twice", {"A": HOLDER + HOLDER}), ("a bad name", {"A-B": HOLDER})):
        request = TE.base_request(f"env-table-{label}".replace(" ", "-"))
        request["command"]["argv"] = [sys.executable, str(TE.ROOT / "dummy_runner.py")]
        request["command"]["env"] = env
        check_in(f"E-table: `validate_request` refuses {label}", "command.env", TE.refusal(request))


def holders_checks() -> None:
    """E-holders and E-noreader: validate_request and s5_contract_refusals count the same places."""
    py, runner = sys.executable, str(TE.ROOT / "dummy_runner.py")
    cases = [("none", [py, runner], None, 0), ("argv only", [py, runner, HOLDER], None, 1), ("env only", [py, runner], {"A": HOLDER}, 1),
             ("argv and env", [py, runner, HOLDER], {"A": HOLDER}, 2), ("env and env", [py, runner], {"A": HOLDER, "B": HOLDER}, 2)]
    for label, argv, env, count in cases:
        request = TE.base_request(f"env-holders-{label}".replace(" ", "-"))
        request["command"]["argv"] = argv
        if env is not None:
            request["command"]["env"] = env
        refused = TE.refusal(request)
        profile = {"profile_id": "api", "reporter": {"kind": "junit-xml"}, "commands": {"one_test": spec(argv, env)}}
        twin = P.s5_contract_refusals(str(TE.ROOT), profile)
        if count == 1:
            check_eq(f"E-holders: {label}: one holder passes in both", (refused, twin), ("", []))
        else:
            check_eq(f"E-holders: {label}: {count} holders refused by both", (bool(refused), bool(twin)), (True, True))
        if env and count == 0:
            pass
    for reporter in ("pytest", "none"):
        request = TE.base_request(f"env-noreader-{reporter}")
        request["command"]["reporter"] = reporter
        request["command"].pop("report_path", None)
        request["command"]["env"] = {"A": HOLDER}
        check_in(f"E-noreader: an env beside `{reporter}` is refused: nothing reads it", "nothing reads this report", TE.refusal(request))


def run_checks() -> None:
    """E-run and E-order."""
    (TE.ROOT / "env_runner.py").write_text(
        "import os, sys\nfrom pathlib import Path\n"
        f"report = Path(os.environ['{VAR}'])\nreport.parent.mkdir(parents=True, exist_ok=True)\n"
        "ids = sys.argv[1:]\n"
        "Path('env-seen.txt').write_text(os.environ.get('HEADLESS', 'unset') + '|' + os.environ[" + repr(VAR) + "])\n"
        "cases = ''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in ids)\n"
        "report.write_text(f'<testsuite tests=\"{len(ids)}\" failures=\"0\" errors=\"0\" skipped=\"0\">{cases}</testsuite>')\n",
        encoding="utf-8")
    request = TE.base_request("env-run-1")
    request["input_fingerprint"] = "sha256:env-run-1"
    request["command"]["argv"] = [sys.executable, str(TE.ROOT / "env_runner.py")]
    request["command"]["env"] = {VAR: HOLDER}
    request["command"]["selector_args"] = {k: [k] for k in request["selected_instance_ids"]}
    saved = {k: os.environ.get(k) for k in ("HEADLESS", VAR)}
    os.environ["HEADLESS"] = "0"
    os.environ[VAR] = "from-the-parent"
    try:
        done = TE.invoke(request)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    seen = (TE.ROOT / "env-seen.txt").read_text(encoding="utf-8") if (TE.ROOT / "env-seen.txt").is_file() else ""
    headless, _, path = seen.partition("|")
    check_eq("E-run: the run launched (exit 0 and a path was seen)", (done.returncode, bool(path)), (0, True))
    check_eq("E-order: HEADLESS of the environment is respected", headless, "0")
    check_eq("E-order: the parent's value of the variable is overridden by the command's own", path != "from-the-parent", True)
    reports = sorted(p for p in TE.ROOT.rglob("report.junit.xml"))
    check_eq("E-run: the variable names the run's own report file, and the summary read that file",
             (len(reports) >= 1 and str(reports[-1].resolve()) == str(Path(path).resolve()), os.environ.get(VAR)), (True, None))
    check_in("E-run: the summary counted the tests of that file", "10", done.stdout + done.stderr)


def identity_checks() -> None:
    """E-identity and E-receipt."""
    plain = spec(["npx", "playwright", "test"])
    with_env = spec(["npx", "playwright", "test"], {VAR: HOLDER})
    check_eq("E-identity: no env: the identity is the argv words, byte for byte", PC.command_identity(plain), ["npx", "playwright", "test"])
    check_eq("E-identity: an `env` is another command", PC.command_identity(with_env) != PC.command_identity(plain), True)
    word_in_argv = spec(["x", f"{VAR}={HOLDER}"])
    env_of_same = spec(["x"], {VAR: HOLDER})
    check_eq("E-identity: `A={report_path}` as an argv word and `env: {A: ..}` are not one command",
             P.argv_digest(PC.command_identity(word_in_argv)) != P.argv_digest(PC.command_identity(env_of_same)), True)
    check_eq("E-identity: no env keeps the digest the code had before", P.argv_digest(PC.command_identity(plain)), P.argv_digest(["npx", "playwright", "test"]))
    import report_adapt
    import environment_record as ER2
    cfg = {"profiles": [{"profile_id": "web", "commands": {"one_test": with_env}}]}
    cfg_plain = {"profiles": [{"profile_id": "web", "commands": {"one_test": plain}}]}
    check_eq("E-identity: the helper reads the same identity the gate writes into its manifest",
             report_adapt._digest(report_adapt._identity(cfg["profiles"][0])), P.argv_digest(PC.command_identity(with_env)))
    live = ER2.current_key({"scope": "level", "contour": "web"}, cfg, "")
    old = ER2.current_key({"scope": "level", "contour": "web"}, cfg_plain, "")
    check_eq("E-identity: the environment record keys a command with an `env` apart from the same words without one",
             live["argv_digest"] != old["argv_digest"], True)
    check_eq("E-identity: ... and without an `env` it is the digest it always was", old["argv_digest"], P.argv_digest(["npx", "playwright", "test"]))
    # E-receipt: the durable key and the earlier proof
    root = TR.project("qa-env-receipt-", runner=TR.WRITES_JUNIT)
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TR.TICKET, "A")
        argv = ["x", HOLDER]
        key_plain = r._rehearsal_key("web", root, argv, "t", "junit-xml", "", root)
        key_env = r._rehearsal_key("web", root, argv + ["\u0000env", f"A={HOLDER}"], "t", "junit-xml", "", root)
        check_eq("E-receipt: the same words with an `env` do not key the same receipt", key_plain != key_env, True)
        import hashlib
        check_eq("E-receipt: with no `env` the key is the formula's own (literal)", len(key_plain), len(hashlib.sha256(b"").hexdigest()))
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        one = config["profiles"][0]["commands"]["one_test"]
        one["argv"] = [sys.executable, str(root / "fake_runner.py"), HOLDER, "<test-id>"]
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        TR.gate_preflight._REPORTER_PROBES.clear()
        first = TR.rehearse(root)
        check_eq("E-receipt: the first rehearsal proves the report and records the receipt", first.findings, [])
        # the profile now gains an `env` on the same argv: the receipt of the old command is not this command's
        one["env"] = {"UNUSED_BY_THE_RUNNER": HOLDER}
        one["argv"] = [sys.executable, str(root / "fake_runner.py"), "<test-id>"]
        one["argv"] = [sys.executable, str(root / "fake_runner.py"), HOLDER, "<test-id>"]
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        probe = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TR.TICKET, "A")
        check_eq("E-receipt: a receipt of the same argv under another `env` is `command_changed`, not `same_command`",
                 probe._earlier_proof("web", PC.command_identity(one))["state"], "command_changed")
        check_eq("E-receipt: and the old command's own identity still finds its receipt", probe._earlier_proof("web", PC.command_identity(
            {"argv": [sys.executable, str(root / "fake_runner.py"), HOLDER, "<test-id>"]}))["state"], "same_command")
    finally:
        cleanup(root)


def kept_identity_checks() -> None:
    """E-identity, t-427 (canon part A, survivor 3): `report_adapt.prove_kept` compares the kept manifest's digest with the digest of
    the profile's command IDENTITY (argv words plus `env`), not with the argv words alone."""
    import tempfile
    import report_adapt
    root = Path(tempfile.mkdtemp(prefix="qa-env-kept-"))
    try:
        slot = root / "slot"
        slot.mkdir()
        (slot / "report.xml").write_text('<testsuite tests="1"><testcase classname="c" name="t"/></testsuite>', encoding="utf-8")
        argv = ["npx", "playwright", "test", "<test-id>"]
        with_env = spec(argv, {VAR: HOLDER})
        profile = {"profile_id": "web", "commands": {"one_test": with_env}}
        cfg = {"profiles": [profile]}
        meta = {"argv": argv, "argv_digest": P.argv_digest(PC.command_identity(with_env))}
        manifest, why = report_adapt.keep_unread(root, "web", slot, meta, 5, 100000)
        check_eq("E-identity: a kept report is written for the profile's command with an `env`", (manifest is not None, why), (True, ""))
        tests, problem = report_adapt.prove_kept(root, "web", "junit-xml", cfg)
        check_eq("E-identity: the kept report of the same command (env included) is accepted and read", (tests, problem), (1, ""))
        changed = {"profiles": [{"profile_id": "web", "commands": {"one_test": spec(argv, {VAR + "_OTHER": HOLDER})}}]}
        tests2, problem2 = report_adapt.prove_kept(root, "web", "junit-xml", changed)
        check_eq("E-identity: after the `env` changed the kept report is refused as another command", tests2, 0)
        check_in("E-identity: ... and the refusal says so", "another command", problem2)
        plain_cfg = {"profiles": [{"profile_id": "web", "commands": {"one_test": spec(argv)}}]}
        check_eq("E-identity: the same words with no `env` are another command too", report_adapt.prove_kept(root, "web", "junit-xml", plain_cfg)[0], 0)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def rehearsal_of(runner: str, argv_tail=None, env=None):
    root = TR.project("qa-env-probe-", runner=runner)
    use_project(root)
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    one = config["profiles"][0]["commands"]["one_test"]
    if argv_tail is not None:
        one["argv"] = [sys.executable, str(root / "fake_runner.py")] + argv_tail
    if env is not None:
        one["env"] = env
    (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    TR.gate_preflight._REPORTER_PROBES.clear()
    return root, TR.rehearse(root)


def probe_checks() -> None:
    """E-probe, E-entity, E-folder, E-neighbour, E-unread."""
    root, r = rehearsal_of(WRITES_BY_VARIABLE, [], {VAR: HOLDER})
    try:
        check_eq("E-probe: a profile with an `env` and a runner that writes by the variable is proven", (r.findings, r.stand_gaps), ([], []))
        check_in("E-probe: and said so", "1 test(s) counted", r.info[-1]["message"])
    finally:
        cleanup(root)
    for label, runner, why, reason in (
            ("an empty report file", WRITES_EMPTY, "the report file it wrote is empty", "no_file"),
            ("a neighbour with a DOCTYPE and no report", WRITES_NEIGHBOUR_DOCTYPE, "no report file was written", "no_file"),
            ("a valid neighbour and no report", WRITES_NEIGHBOUR, "no report file was written", "no_file"),
            ("the path is a folder", WRITES_FOLDER, "the path it was given is a folder, not a file", "no_file"),
            ("the report itself with a DOCTYPE", WRITES_OWN_DOCTYPE, "declares XML entities", "unparsable")):
        root = TR.project("qa-env-read-", runner=runner)
        try:
            use_project(root)
            rehearsal = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TR.TICKET, "A")
            folder = Path(os.environ.get("TEMP") or "/tmp") / ("env-read-" + re.sub(r"\W", "", label))
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
            report = folder / "report.xml"
            import subprocess
            subprocess.run([sys.executable, str(root / "fake_runner.py"), str(report)], check=False, capture_output=True)
            tests, said, cls, tried, fit = rehearsal._read_probe_report(report, "junit-xml")
            check_eq(f"E-entity/E-neighbour: {label}: nothing is counted and the class is typed", (tests, cls), (0, reason))
            check_in(f"E-entity/E-neighbour: {label}: the reason", why, said)
            if reason == "no_file":
                check_eq(f"E-neighbour: {label}: nothing tried and no reader fits (a neighbour is no proof)", (tried, fit), ([], ""))
                check_not_in(f"E-entity: {label}: the neighbour's DOCTYPE is never read", "declares XML entities", said)
            if label == "a valid neighbour and no report":
                check_in("E-neighbour: the neighbours are named", "1 other file(s) beside it (TESTS-chrome.xml)", said)
            shutil.rmtree(folder, ignore_errors=True)
        finally:
            cleanup(root)
    # E-neighbour: no typed command for the conductor, and no config written, by a neighbour
    root = TR.project("qa-env-adapt-", runner=WRITES_NEIGHBOUR, helped=False)
    try:
        use_project(root)
        TR.no_kind(root)
        TR.gate_preflight._REPORTER_PROBES.clear()
        finding = TR.rehearse(root).findings[0]
        check_eq("E-neighbour: the finding carries no fit and no command to run", (finding["fit"], "argv" in finding), ("", False))
    finally:
        cleanup(root)
    # E-unread: an `env` that cannot be read: not run, one line
    root, r = rehearsal_of(WRITES_BY_VARIABLE, [], {VAR: "abc" + HOLDER})
    try:
        check_eq("E-unread: nothing is run and nobody is asked", (r.findings, r.stand_gaps), ([], []))
        check_in("E-unread: a line says the env could not be read", "commands.one_test.env", r.info[-1]["message"])
    finally:
        cleanup(root)


def cure_checks() -> None:
    """E-cure, E-question, E-person, E-data, E-sample, E-precedent."""
    table, why = P.cure_table()
    check_eq("E-data: the shipped table is read whole", why, "")
    row = next(r for r in table["rows"] if r["id"] == "playwright")
    check_eq("E-data: the playwright row is data", (row["add_argv"], row["add_env"], row["reporter_kind"]),
             (["--reporter=junit"], {VAR: HOLDER}, "junit-xml"))
    check_not_in("E-data: person_words says nothing of a variable the factory cannot set", "cannot set", row["person_words"])
    bad = dict(row, add_argv=None)
    check_in("E-data: `add_env` without words to add is refused", "add_env", P._row_problem(bad))
    check_in("E-data: `add_env` with a value of its own is refused", "add_env", P._row_problem(dict(row, add_env={VAR: "x"})))
    scripts = harness.SCRIPTS
    # the word of the framework lives in the data file, never in a script (m-4: the scripts' own top level, not the tests)
    needle = "PLAYWRIGHT_" + "JUNIT"
    holders = [p.name for p in scripts.glob("*.py") if needle in p.read_text(encoding="utf-8")]
    check_eq("E-data: no script of the package holds the variable name", holders, [])
    check_eq("E-data (control): the same search finds it in the data file",
             needle in (scripts.parent / "references" / "report-cures.json").read_text(encoding="utf-8"), True)

    def profile(argv, env=None, kind=None):
        p = {"profile_id": "web", "commands": {"one_test": spec(argv, env)}}
        if kind:
            p["reporter"] = {"kind": kind}
        return p
    pw = ["npx", "playwright", "test", "<test-file>"]
    got = P.classify_cure(profile(pw), table["rows"])
    check_eq("E-cure: no flag, no variable: add, with the variable", (got["action"], got["candidate"], got["candidate_env"]),
             ("add", ["npx", "playwright", "test", "<test-file>", "--reporter=junit"], {VAR: HOLDER}))
    got = P.classify_cure(profile(pw + ["--reporter=junit"]), table["rows"])
    check_eq("E-cure: the flag is there and the variable is not: still add (one change)", (got["action"], got["candidate_env"]), ("add", {VAR: HOLDER}))
    got = P.classify_cure(profile(pw + ["--reporter=junit"], {VAR: HOLDER}), table["rows"])
    check_eq("E-cure: both there: present", got["action"], "present")
    got = P.classify_cure(profile(pw + ["--reporter=junit", f"--output={HOLDER}"]), table["rows"])
    check_eq("E-cure (F9): the flag is there and the argv already holds the placeholder: present, no second holder added", (got["action"], got.get("candidate_env")), ("present", None))
    got = P.classify_cure(profile(pw + [f"--output={HOLDER}"]), table["rows"])
    check_eq("E-cure (F9): the argv holds the placeholder and the flag is missing: add the flag, and NO variable", (got["action"], got["candidate_env"]), ("add", None))
    got = P.classify_cure(profile(pw, {"OTHER_NAME": HOLDER}), table["rows"])
    check_eq("E-cure (F9): another variable already holds the placeholder: add the flag, and no second variable", (got["action"], got["candidate_env"]), ("add", None))
    got = P.classify_cure(profile(pw, None, "trx"), table["rows"])
    check_eq("E-cure: another recorded kind is not overwritten", got["action"], "kind_conflict")
    # E-question
    cured = ["npx", "playwright", "test", "--reporter=junit", "<test-file>"]
    text = P.render_question(table, "web", cured, "cure", row, (), False, {VAR: HOLDER})
    check_in("E-question: the question names the variable", f"`{VAR}`", text)
    check_eq("E-question: and obeys human-questions.md", __import__("human_text").problems(text), [])
    check_not_in("E-question: with no env there is no variable in it", VAR, P.render_question(table, "web", cured, "cure", row))
    os.environ.pop("PYTHONIOENCODING", None)
    # E-sample and E-person need a project
    root = harness.temp_project("qa-env-sample-")
    try:
        use_project(root)
        sample = json.loads((harness.SCRIPTS.parent / "references" / "profile-shape.json").read_text(encoding="utf-8"))["profile"]
        command = ER._command_from_profile(sample)
        check_eq("E-sample: the sample's command carries the variable and one holder", (command.get("env"), command["reporter"]),
                 ({VAR: HOLDER}, "junit-xml"))
        check_eq("E-sample: S5's own contract takes the sample", P.s5_contract_refusals(str(root), dict(sample, profile_id="web")), [])
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["profiles"] = [dict(profile(pw), selected=True)]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        refused = P.probe_person_command(root, "web", f"{VAR}=x npx playwright test")
        check_eq("E-person: a leading NAME=value is refused in words, nothing run", (refused["move"], refused["report"]), ("refused", None))
        check_in("E-person: and says what to do", "the factory sets that variable itself", refused["says"])
        # E-person-env: the cure row's variable goes with a command the person gives
        candidate = P.probe_candidate(root, "web", cured, "junit-xml", config=json.loads(cfg_path.read_text(encoding="utf-8")), env={VAR: HOLDER})
        check_eq("E-person-env: the candidate is checked by S5's contract with the variable (one holder: no refusal)",
                 candidate.get("state") != "refused_by_s5", True)
        check_eq("E-person-env: and carries the env the proposal must seal", candidate.get("env_change"), {VAR: HOLDER})
        # E-seal: the sealed proposal writes argv, kind and env and nothing else
        proposal = __import__("config_contract").command_proposal(
            root, {"profile_id": "web"}, cured, reporter_kind="junit-xml", question=P.render_question(table, "web", cured, "cure", row, (), False, {VAR: HOLDER}), env={VAR: HOLDER})
        written = proposal["proposed_config"]["profiles"][0]
        check_eq("E-seal: the proposed profile holds argv, kind and env", (written["commands"]["one_test"]["argv"], written["reporter"]["kind"],
                 written["commands"]["one_test"]["env"]), (cured, "junit-xml", {VAR: HOLDER}))
        check_eq("E-seal: the pointers name all three", sorted(proposal["listing"]["pointers"]), sorted(
            ["/profiles/0/commands/one_test/argv", "/profiles/0/reporter/kind", "/profiles/0/commands/one_test/env"]))
        # E-person-holder: a command with its own holder, a saved env: the proposal takes the env out
        cfg["profiles"][0]["commands"]["one_test"]["env"] = {VAR: HOLDER}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        own = ["npx", "vitest", "run", f"--outputFile={HOLDER}"]
        got = P.probe_candidate(root, "web", own, "junit-xml", config=json.loads(cfg_path.read_text(encoding="utf-8")), timeout=30)
        check_eq("E-person-holder: S5 would not see two holders, and the proposal takes the env out", (got.get("state") != "refused_by_s5", got.get("env_change")), (True, {}))
        taken = __import__("config_contract").command_proposal(root, {"profile_id": "web"}, own, reporter_kind="junit-xml", env={},
                                                              question="I propose to run the web tests as: `" + __import__("config_contract").display_command(own) + "`. Do it? yes / no")
        row_env = [a for a in taken["changes"][0]["also"] if a["path"].endswith("/env")]
        check_eq("E-person-holder: the also-row says the env goes (`to: null`)", (row_env[0]["from"], row_env[0]["to"]), ({VAR: HOLDER}, None))
        # F2: the doors through `probe_person_command` itself (the probe is replaced by a recorder: no launcher is needed)
        seen: list = []
        real_probe = P.probe_candidate

        def recorder(*args, **kwargs):
            seen.append(dict(kwargs))
            return {"proven": False, "state": "launcher_missing", "why": "recorded", "detail": "", "contract": []}
        P.probe_candidate = recorder
        try:
            cfg["profiles"][0]["commands"]["one_test"].pop("env", None)
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            seen.clear()
            P.probe_person_command(root, "web", "npx playwright test --reporter=junit tests/a.spec.ts")
            check_eq("E-person-env: a person's command with no holder of its own is probed WITH the cure row's variable (`cure_row` is read)",
                     [s.get("env") for s in seen], [{VAR: HOLDER}])
            cfg["profiles"][0]["commands"]["one_test"]["env"] = {VAR: HOLDER}
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            seen.clear()
            P.probe_person_command(root, "web", f"npx vitest run --outputFile={HOLDER}")
            check_eq("E-person-holder: a person's command that carries its own holder is probed with the saved env TAKEN OUT",
                     [s.get("env") for s in seen], [{}])
            cfg["profiles"][0]["commands"]["one_test"]["argv"] = ["npx", "vitest", "run", f"--outputFile={HOLDER}"]
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            seen.clear()
            same = P.probe_person_command(root, "web", f"npx vitest run --outputFile={HOLDER}")
            check_eq("E-person-holder: the SAME words with a saved env are not 'already the command': taking the env out is a change",
                     (same["move"] != "nothing", [s.get("env") for s in seen]), (True, [{}]))
            cfg["profiles"][0]["commands"]["one_test"].pop("env")
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            seen.clear()
            same = P.probe_person_command(root, "web", f"npx vitest run --outputFile={HOLDER}")
            check_eq("E-person-holder (control): the same words and no saved env are 'already the command', nothing probed",
                     (same["move"], seen), ("nothing", []))
        finally:
            P.probe_candidate = real_probe
        # E-seal through the real writer: a yes through `record_approval` and `apply_plan` writes argv, kind and env and nothing else
        cfg["profiles"][0]["commands"]["one_test"] = spec(pw)
        cfg["profiles"][0].pop("reporter", None)
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        C = __import__("config_contract")
        before = json.loads(cfg_path.read_text(encoding="utf-8"))
        sealed = C.command_proposal(root, {"profile_id": "web"}, cured, reporter_kind="junit-xml", env={VAR: HOLDER},
                                    question=P.render_question(table, "web", cured, "cure", row, (), False, {VAR: HOLDER}))
        ref = C.command_approval_ref(sealed)
        C.record_approval(root, sealed, ref, "transcript:yes")
        C.apply_plan(root, sealed, ref)
        after = json.loads(cfg_path.read_text(encoding="utf-8"))
        one = after["profiles"][0]["commands"]["one_test"]
        check_eq("E-seal: after the yes and the apply the disk holds argv, kind and env", (one["argv"], after["profiles"][0]["reporter"]["kind"], one.get("env")),
                 (cured, "junit-xml", {VAR: HOLDER}))
        expected = copy.deepcopy(before)
        expected["profiles"][0]["commands"]["one_test"].update(argv=cured, env={VAR: HOLDER})
        expected["profiles"][0]["reporter"] = {"kind": "junit-xml"}
        after_cmp = {k: v for k, v in after.items() if k not in ("migration", "config_sha")}
        expected_cmp = {k: v for k, v in expected.items() if k not in ("migration", "config_sha")}
        check_eq("E-seal: and nothing else of the config moved", after_cmp, expected_cmp)
    finally:
        cleanup(root)
    # E-precedent: the profile's env is a part of the command a precedent is compared with
    check_eq("E-precedent: the profile's env is read through the one reader", ER._profile_env(profile(pw, {VAR: HOLDER})), ({VAR: HOLDER}, ""))
    check_in("E-precedent: an unreadable env of the profile is a named problem", "env",
             ER._profile_env(profile(pw, {VAR: "abc"}))[1])
    try:
        ER._command_from_profile(profile(pw, {VAR: "abc"}))
        refusal = ""
    except ER.MineRefusal as exc:
        refusal = str(exc)
    check_in("E-precedent: no precedent and an unreadable env: a refusal with the problem", "commands.one_test.env", refusal)
    check_eq("E-precedent: a readable env goes into the built command, as written", ER._command_from_profile(
        profile(pw + ["--reporter=junit"], {VAR: HOLDER}, "junit-xml")).get("env"), {VAR: HOLDER})


def precedent_checks() -> None:
    """E-precedent (F2), through the real `build_mine_request`: a typed run's command is copied as the story's command only when its
    `env` is the profile's too (absent, null and `{}` are one value); a different `env` is a different command, and a note says so."""
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="qa-env-precedent-")).resolve()
    task = "PREC-ENV"
    task_root = root / "qa-factory" / "artifacts" / task

    def put(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    try:
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_a.py").write_text("def test_green():\n    pass\n", encoding="utf-8")
        (root / "probe.py").write_text("import json\nprint(json.dumps({'profile_id': 'web', 'timestamp': '2026-09-22T10:00:00Z', "
                                       "'environment_id': 'localhost', 'expected_source_revision': 'source-1', "
                                       "'observed_runtime_identity': 'build-1', 'evidence_refs': ['probe'], 'result': 'matched', "
                                       "'provenance': {'technical_verification': True, 'source_linkage': 'exact', "
                                       "'deployed_source_revision': 'source-1'}}))\n", encoding="utf-8")
        provenance = {"profile_id": "web", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "localhost",
                      "expected_source_revision": "source-1", "observed_runtime_identity": "build-1", "evidence_refs": ["probe"],
                      "result": "matched", "provenance": {"technical_verification": True, "source_linkage": "exact",
                                                          "deployed_source_revision": "source-1"}}
        argv = [sys.executable, str(root / "runner.py"), "<test-file>"]
        words = [sys.executable, str(root / "runner.py")]

        def config(env) -> dict:
            one = {"argv": list(argv), "cwd": "."}
            if env != "ABSENT":
                one["env"] = env
            return {"profiles": [{"profile_id": "web", "selected": True, "roots": {"test": "tests"}, "commands": {"one_test": one},
                                  "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}],
                    "execution": {"runtime_probes": {"web": {"argv": [sys.executable, str(root / "probe.py")], "cwd": ".", "timeout_s": 20}}}}
        put(root / "qa-factory" / "config.json", config("ABSENT"))
        put(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
        put(task_root / "state" / "controller.json", {"schema_version": "2", "revision": "1", "source_revision": "source-1", "dispatches": {
            "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "status": "running",
                                  "scope": ["TC-001"], "budget": {"requests": 150}}}})
        put(task_root / "work" / "automation-manifest.json", {"tests": [{"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green",
                                                                  "selector_args": ["--grep", "test_green"], "report_test_id": "test_green"}]})
        store = ER.JobStore(task_root / "state" / "execution-jobs")

        def build(profile_env):
            try:
                request, notes, _r, _v = ER.build_mine_request(root, ["TC-001"], task=task, cfg=config(profile_env), again=True,
                                                               probe=lambda spec: dict(provenance))
                return request, notes
            except ER.MineRefusal as exc:
                return None, [str(exc)]

        def scenario(old_env, profile_env):
            for path in (task_root / "state" / "execution-jobs").glob("*.json"):
                path.unlink()
            base, notes = build("ABSENT")
            if base is None:
                return None, notes
            request = json.loads(json.dumps(base))
            request["idempotency_key"] = "prec-env"
            request["command"] = {**request["command"], "argv": list(words), "from_job": "job-old"}
            if old_env != "ABSENT":
                request["command"]["env"] = old_env
            summary = root / "prec-summary.json"
            put(summary, {"exit_code": 0, "execution_status": "passed", "totals": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0, "passed": 1}})
            store.write({"job_id": "job-old", "idempotency_key": "prec-env", "request_digest": "d" * 64, "status": "completed", "request": request,
                         "execution_status": "passed", "summary": str(summary), "created_at": "2026-09-30T04:00:01+00:00"})
            built, notes = build(profile_env)
            return ((built or {}).get("command") or {}).get("from_job", "<profile>"), notes
        sample = {VAR: HOLDER}
        got, notes = scenario("ABSENT", sample)
        check_eq("E-precedent: a precedent with no env and a profile that sets one is NOT copied (the profile's command is built)", got, "<profile>")
        check_in("E-precedent: and the note names the env", "the profile's commands.one_test.env", notes)
        got, _ = scenario(sample, sample)
        check_eq("E-precedent: a precedent with the profile's own env is copied", got, "job-old")
        got, _ = scenario(sample, "ABSENT")
        check_eq("E-precedent: a precedent with an env the profile no longer gives is NOT copied", got, "<profile>")
        got, _ = scenario({"OTHER_NAME": HOLDER}, sample)
        check_eq("E-precedent: a precedent with another variable is NOT copied", got, "<profile>")
        for label, old, new in (("no env on both sides", "ABSENT", "ABSENT"), ("null on both sides", None, None), ("`{}` and absent", {}, "ABSENT"),
                                ("absent and `{}`", "ABSENT", {})):
            got, _ = scenario(old, new)
            check_eq(f"E-precedent: {label}: copied, as it always was", got, "job-old")
        got, _ = scenario("ABSENT", {VAR: "abc" + HOLDER})
        check_eq("E-precedent: an env of the profile that cannot be read is 'not compared' for the precedent (the refusal is the profile's)",
                 got, "job-old")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    shutil.rmtree(TE.ROOT, ignore_errors=True)
    (TE.ROOT / "qa-factory" / "state").mkdir(parents=True)
    (TE.ROOT / "qa-factory" / "artifacts" / "REQ-1").mkdir(parents=True)
    (TE.ROOT / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    (TE.ROOT / "dummy_runner.py").write_text(
        "from pathlib import Path\nreport=Path(__import__('sys').argv[1]); report.parent.mkdir(parents=True, exist_ok=True)\n"
        "ids=__import__('sys').argv[2:]\ncases=''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in ids)\n"
        "report.write_text(f'<testsuite tests=\"{len(ids)}\" failures=\"0\" errors=\"0\" skipped=\"0\">{cases}</testsuite>')\n", encoding="utf-8")
    (TE.ROOT / "runtime_probe.py").write_text(
        "import json\nprint(json.dumps({\"profile_id\":\"api\",\"timestamp\":\"2026-09-17T12:00:00Z\","
        "\"environment_id\":\"qa\",\"expected_source_revision\":\"source-1\",\"observed_runtime_identity\":\"build-1\","
        "\"evidence_refs\":[\"probe\"],\"provenance\":{\"technical_verification\":True,\"source_linkage\":\"exact\","
        "\"deployed_source_revision\":\"source-1\"},\"result\":\"matched\"}))\n", encoding="utf-8")
    try:
        table_checks()
        holders_checks()
        run_checks()
    finally:
        shutil.rmtree(TE.ROOT, ignore_errors=True)
    precedent_checks()
    identity_checks()
    kept_identity_checks()
    probe_checks()
    cure_checks()
    finish("EP1-22: env with the report holder, the probe reads the file")


if __name__ == "__main__":
    main()
