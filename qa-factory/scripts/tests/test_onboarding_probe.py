#!/usr/bin/env python3
"""The onboarding probe of the test command (B-220 part 1, t-385): probe, prove the cure, propose it, apply it on a yes.

TP2-2553: Karma ran with no JUnit reporter and the factory found out inside S5. The owner's ruling (03.10): the
command is probed where it is recorded; a known one-flag cure is PROVEN on this machine and proposed in words ("I propose to
run it as: `...`. Do it?"), applied only on the person's yes through the existing approved path; no known cure - the LLM
explains and asks (FR-50). This file judges the probe and the yes path (KO1-KO4, the node spec's F1, F2, F3, F8, F11):

  KO1  a profile whose run writes no report and whose command matches a cure row: the cured argv, a SEALED proposal in the
       folder the caller named, the sentence, and a project tree byte-identical to what it was
  KO2  the yes path: record_approval + apply_plan on that file -> the cured argv and the report kind, everything else equal, a
       backup; the probe again -> proven, and the durable record carries the argv it proved
  KO3  an unknown framework, a row with `add_argv: null`, a pytest `no_report`: no cure proposed, the words present, nothing written
  KO4  a cure the candidate probe rejects is withdrawn BEFORE it is shown (and one S5 would refuse is not proven, F1)
  K-two-profiles  two cured profiles: two "Do it?" rounds, both applied, the second never stale (F2)
  F3   the person's own command: split, refused in words (absolute path, shell, quote), probed, sealed, applied the same way
  F8   the edges: unreadable cure table, `add_argv` already present, a kind conflict, a second yes, a folder inside the project
  F11  the durable record is keyed without the stand and carries the argv: "the command changed" is told from "it stopped"
"""
import contextlib
import copy
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import config_contract as C  # noqa: E402
import gate_preflight as G  # noqa: E402
import onboarding_probe as P  # noqa: E402

# Stand-ins for a project's runners: each writes whatever report its flag asks for into the path it was handed, so a test here
# proves the probe's reading and never a real framework. The file names carry the framework word the cure table matches.
TRX = ('<?xml version="1.0"?><TestRun><ResultSummary outcome="Completed"><Counters total="1" executed="1" passed="1" '
       'failed="0" error="0" notExecuted="0" inconclusive="0"/></ResultSummary><Results><UnitTestResult testName="t1" '
       'outcome="Passed"/></Results></TestRun>')
JUNIT = ('<?xml version="1.0"?><testsuite name="s" tests="1" failures="0" errors="0" skipped="0" time="0.1">'
         '<testcase classname="c" name="t1"/></testsuite>')
FAKE_DOTNET = f'''import sys
from pathlib import Path
for arg in sys.argv[1:]:
    if arg.startswith("trx;LogFileName="):
        Path(arg.split("=", 1)[1]).write_text({TRX!r}, encoding="utf-8")
        break
print("Passed! 1 test")
'''
FAKE_VITEST = f'''import sys
from pathlib import Path
args = sys.argv[1:]
if "--reporter=junit" in args:
    for arg in args:
        if arg.startswith("--outputFile="):
            Path(arg.split("=", 1)[1]).write_text({JUNIT!r}, encoding="utf-8")
print("1 passed")
'''
FAKE_KARMA = '''import sys
print("Executed 1 of 1 SUCCESS", file=sys.stderr)
'''
FAKE_BROKEN_DOTNET = '''import sys
print("the logger is not installed", file=sys.stderr)
'''
# a runner whose own flag is `--out <path>` (a person's command; and the two-holder cure of the S5 negative control)
FAKE_REPORT = f'''import sys
from pathlib import Path
args = sys.argv[1:]
if "--out" in args:
    Path(args[args.index("--out") + 1]).write_text({JUNIT!r}, encoding="utf-8")
'''
SCRIPT_FILES = {"fake_dotnet.py": FAKE_DOTNET, "fake_vitest.py": FAKE_VITEST, "fake_karma.py": FAKE_KARMA,
                "fake_broken_dotnet.py": FAKE_BROKEN_DOTNET, "fake_report.py": FAKE_REPORT}
PY = sys.executable


def profile(pid: str, argv: list, **extra) -> dict:
    return {"profile_id": pid, "capabilities": ["api"], "roots": {"test": "tests"},
            "commands": {"one_test": {"argv": argv, "cwd": "."}}, **extra}


def project(profiles: list, **top) -> Path:
    root = harness.temp_project("qa-onb-probe-")
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["profiles"] = profiles
    cfg.update(top)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (root / "tests" / "test_one.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
    for name, source in SCRIPT_FILES.items():
        (root / name).write_text(source, encoding="utf-8")
    use_project(root)
    return root


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def config_of(root: Path) -> dict:
    return json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))


def argv_of(config: dict, pid: str) -> list:
    return next(p for p in config["profiles"] if p["profile_id"] == pid)["commands"]["one_test"]["argv"]


def quiet(func, *args, **kwargs):
    """The probe's progress lines go to stderr; a test does not need them on its own."""
    with contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


def entry_of(result: dict, pid: str) -> dict:
    return next(e for e in result["profiles"] if e["profile"] == pid)


def load_sealed(entry: dict) -> dict:
    return json.loads(Path(entry["proposal"]["path"]).read_text(encoding="utf-8"))


def say_yes(root: Path, entry: dict, evidence: str = "transcript:the person said yes") -> Path | None:
    """The existing approved path, exactly as phase 4 runs it: record the person's yes, then apply the sealed file."""
    proposal = load_sealed(entry)
    ref = entry["proposal"]["approval_ref"]
    C.record_approval(root, proposal, ref, evidence)
    return C.apply_plan(root, proposal, ref)


def refusal_of(func) -> str:
    try:
        func()
    except ValueError as exc:
        return str(exc)
    return ""


def ko1_a_proven_cure_becomes_one_sealed_proposal() -> None:
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = snapshot(root)
        result = quiet(P.probe_profiles, root, proposals)
        entry = entry_of(result, "web")
        check_eq("KO1: the run left no report, said as a state", entry["report"]["state"], "no_report")
        check_eq("KO1: the cure is the dotnet row's, an argv change", (entry["cure"]["id"], entry["cure"]["action"]), ("dotnet", "add"))
        check_eq("KO1: the cure was PROVEN on this machine before it was proposed", entry["cure"]["proven"], True)
        check_eq("KO1: the skill's next move is the question", entry["move"], "do_it")
        cured = [PY, "fake_dotnet.py", "test", "--logger", "trx;LogFileName={report_path}"]
        check_eq("KO1: the cured argv is the profile's own command with the flag added at the end", entry["cure"]["candidate"], cured)
        sealed = load_sealed(entry)
        check("KO1: the proposal is a file in the folder the caller named", Path(entry["proposal"]["path"]).parent == proposals)
        check_eq("KO1: it carries the cured argv, and the report kind the cure writes (F5)",
                 (argv_of(sealed["proposed_config"], "web"), sealed["proposed_config"]["profiles"][0]["reporter"]), (cured, {"kind": "trx"}))
        check_eq("KO1: it is a proposal of the kind `cure`, inside the hash", sealed["listing"]["kind"], "cure")
        check_eq("KO1: the sealed proposal's hash is its own", sealed["proposal_hash"], C.proposal_hash(sealed))
        question = entry["proposal"]["question"]
        check_in("KO1: the sentence says what is proposed, in the owner's words",
                 "I propose to run the web tests as: `", question)
        check_in("KO1: with the command that carries the flag", 'trx;LogFileName={report_path}', question)
        check_in("KO1: and asks", "Do it? yes / no", question)
        check_eq("KO1: the question is rendered from the sealed file as the maker made it", C.command_question(sealed), question)
        check_eq("KO1: the project tree is byte-identical (a failed probe records nothing, a proposal is outside)",
                 snapshot(root), before)
        check_eq("KO1: one proposal file, nothing else in the folder", len(list(proposals.iterdir())), 1)
        check_eq("KO1: the result is plain JSON", json.loads(json.dumps(result)), result)
        inline = entry_of(quiet(P.probe_profiles, root, ""), "web")["proposal"]
        check_eq("edge: no folder named (empty): the sealed proposal comes back inline and no file is made",
                 (inline["path"], inline["sealed"]["proposal_hash"] == inline["proposal_hash"], len(list(proposals.iterdir())), snapshot(root)),
                 (None, True, 1, before))
        fresh = proposals / "not" / "yet"
        entry_of(quiet(P.probe_profiles, root, fresh), "web")
        check_eq("edge: a folder that does not exist yet is made (outside the project), and holds the proposal", len(list(fresh.iterdir())), 1)
    finally:
        cleanup(root)
        cleanup(proposals)


def ko2_the_yes_path_writes_one_command_and_the_probe_confirms() -> None:
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = config_of(root)
        entry = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        backup = say_yes(root, entry)
        after = config_of(root)
        expected = copy.deepcopy(before)
        expected["profiles"][0]["commands"]["one_test"]["argv"] = entry["cure"]["candidate"]
        expected["profiles"][0]["reporter"] = {"kind": "trx"}
        check_eq("KO2: config.json carries the cured argv and the kind, and everything else is equal", after, expected)
        check("KO2: a backup of the config it replaced is in records/config-migrations",
              backup is not None and backup.parent.name == "config-migrations" and backup.is_file(), str(backup))
        check_eq("KO2: the backup holds the config as it was", json.loads(backup.read_text(encoding="utf-8"))["config"], before)
        log = (C.approvals_path(root)).read_text(encoding="utf-8").splitlines()
        check_eq("KO2: one approval recorded, of the kind `cure`, with the person's words as evidence",
                 [(json.loads(l)["approval_ref"], json.loads(l)["kind"], json.loads(l)["evidence_ref"]) for l in log],
                 [(entry["proposal"]["approval_ref"], "cure", "transcript:the person said yes")])
        again = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_eq("KO2: the probe again - the cured command is proven (the confirmation run)", again["report"]["state"], "proven")
        check_eq("KO2: and nothing more is proposed", (again["move"], again["proposal"]), ("nothing", None))
        rows = json.loads((root / "qa-factory" / "state" / G.REPORTER_REHEARSALS_FILE).read_text(encoding="utf-8"))["rehearsals"]
        row = next(iter(rows.values()))
        check_eq("KO2/F11: the durable row carries the argv it proved and its digest",
                 (row["argv"], row["argv_digest"], row["environment"]), (entry["cure"]["candidate"], P.argv_digest(entry["cure"]["candidate"]), ""))
        check_eq("KO2/F11: it is the onboarding's own row", row["source"], "onboarding")
        third = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_in("KO2/F11: a third probe reuses the proof and says so", "reused", third["report"]["why"])
        check_eq("F11: the same command: the record says so", P.earlier_proof(root, "web", entry["cure"]["candidate"])["state"], "same_command")
        check_eq("F11: another command: 'the command changed', not 'it stopped working'",
                 P.earlier_proof(root, "web", [PY, "fake_dotnet.py", "other"])["state"], "command_changed")
        check_eq("F11: a profile never proven: no record", P.earlier_proof(root, "api", ["x"])["state"], "none")
        check_in("F11: and the day it was proven is there", "20", P.earlier_proof(root, "web", entry["cure"]["candidate"])["at"])
    finally:
        cleanup(root)
        cleanup(proposals)


def ko3_no_cure_known_means_words_and_nothing_written() -> None:
    root = project([profile("web", [PY, "fake_karma.py", "ng", "test"]),
                    profile("api", [PY, "fake_unheard_of.py", "run"]),
                    profile("py", [PY, "-m", "pytest", "-p", "no:junitxml", "-p", "no:cacheprovider", "<test-id>"])])
    (root / "fake_unheard_of.py").write_text("print('ran')\n", encoding="utf-8")
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = snapshot(root)
        result = quiet(P.probe_profiles, root, proposals)
        karma, unknown, pytest_ = (entry_of(result, p) for p in ("web", "api", "py"))
        check_eq("KO3: a row whose cure is not one argv change (`add_argv: null`) is explained, not proposed",
                 (karma["cure"]["action"], karma["proposal"], karma["move"]), ("explain", None, "explain_and_ask"))
        check_in("KO3: and its words are the row's", "karma-junit-reporter", karma["says"])
        check_in("KO3: with what the cure still needs", "karma-junit-reporter", " ".join(karma["cure"]["needs"]))
        check_eq("KO3: a framework nobody wrote a row for: no cure, no proposal, the explaining question",
                 (unknown["cure"]["action"], unknown["proposal"], unknown["move"]), ("unknown", None, "explain_and_ask"))
        check_in("KO3: it says the table has no row", "no row for this kind of command", unknown["says"])
        check_eq("KO3/F8: pytest `no_report` is a DIAGNOSIS: no flag, no proposal, the explaining question",
                 (pytest_["report"]["state"], pytest_["cure"]["action"], pytest_["proposal"], pytest_["move"]),
                 ("no_report", "diagnosis", None, "explain_and_ask"))
        check_in("KO3/F8: it says the runner equips pytest itself", "no flag to add", pytest_["says"])
        check_eq("KO3: nothing was written", snapshot(root), before)
        check_eq("KO3: and no proposal file", list(proposals.iterdir()), [])
    finally:
        cleanup(root)
        cleanup(proposals)


def ko3_the_cure_table_unreadable_falls_to_the_explaining_question() -> None:
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    try:
        missing = root.parent / "no-such-cures.json"
        result = quiet(P.probe_profiles, root, None, table_path=missing)
        entry = entry_of(result, "web")
        check_in("F8: the probe says the table could not be read, and why", "the cure table could not be read:", result["cure_table"])
        check_eq("F8: no cure is known, so the explaining question (FR-1: it says what it could not do)",
                 (entry["cure"]["action"], entry["proposal"], entry["move"]), ("unknown", None, "explain_and_ask"))
        check_in("F8: and the sentence carries the same reason", "the cure table could not be read", entry["says"])
        table, why = P.cure_table(missing)
        check_eq("F8: the reader gives no rows for a missing file", (table["rows"], why.startswith("the cure table could not be read:")), ([], True))
        bad = root / "cures.json"
        bad.write_text("{not json", encoding="utf-8")
        check_in("F8: a file that is not JSON is 'could not be read' too", "could not be read", P.cure_table(bad)[1])
        data = json.loads((harness.PLUGIN_ROOT / "references" / "report-cures.json").read_text(encoding="utf-8"))
        data["rows"][3] = dict(data["rows"][3], reporter_kind=None)     # the dotnet row: adds words, writes no kind
        bad.write_text(json.dumps(data), encoding="utf-8")
        table, why = P.cure_table(bad)
        check_eq("F8: one broken row is left out and NAMED, the others still work",
                 ("dotnet" in why, "dotnet" in [r["id"] for r in table["rows"]], len(table["rows"])), (True, False, len(data["rows"]) - 1))
        data["rows"][3] = dict(data["rows"][3], reporter_kind="trx")
        data["rows"][1] = {k: v for k, v in data["rows"][1].items() if k != "person_words"}
        bad.write_text(json.dumps(data), encoding="utf-8")
        table, why = P.cure_table(bad)
        check_eq("F2: a row with words and no `person_words` (the cure told to a person, flag-free) is left out and named",
                 ("jest" in why and "person_words" in why, "jest" in [r["id"] for r in table["rows"]]), (True, False))
        shipped = P.cure_table()[0]["rows"]
        check_eq("F2: every shipped row's person words carry no option (the flag lives on the proposal line only)",
                 [r["id"] for r in shipped if "--" in r["person_words"] or "`" in r["person_words"]], [])
    finally:
        cleanup(root)


def ko4_a_cure_the_probe_rejects_is_withdrawn_before_it_is_shown() -> None:
    root = project([profile("web", [PY, "fake_broken_dotnet.py", "dotnet", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = snapshot(root)
        entry = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_eq("KO4: the cure was run and did NOT prove", (entry["cure"]["action"], entry["cure"]["proven"]), ("add", False))
        check_eq("KO4: no proposal is made, so none is ever shown", (entry["proposal"], entry["move"]), (None, "explain_and_ask"))
        check_in("KO4: the result carries the reason, in words", "did not prove", entry["cure"]["why_not"])
        check_in("KO4: and the sentence the skill explains from says the cure was tried", "was run before it was proposed", entry["says"])
        check_eq("KO4: no file written, anywhere in the project", snapshot(root), before)
        check_eq("KO4: and none in the proposals folder", list(proposals.iterdir()), [])
    finally:
        cleanup(root)
        cleanup(proposals)


# a cure whose command the probe can run and READ, and S5 refuses: `{report_path}` stands in two words (F1)
TWO_HOLDER_TABLE = {
    "question": json.loads((harness.PLUGIN_ROOT / "references" / "report-cures.json").read_text(encoding="utf-8"))["question"],
    "rows": [{"id": "fakecure", "match": ["fake_report"], "words": "fake: add the report flags", "person_words": "The fake runner can write its report when asked.",
              "flag": ["--also"],
              "add_argv": ["--out", "{report_path}", "--also", "{report_path}"], "reporter_kind": "junit-xml", "needs": [],
              "propose_text": "I propose to run the {profile} tests as: `{command}`. Do it? yes / no"}]}


def ko4_a_command_the_probe_reads_and_s5_refuses_is_not_proven() -> None:
    root = project([profile("web", [PY, "fake_report.py"])])
    proposals = temp_dir("qa-onb-proposals-")
    table_path = root.parent / f"{root.name}-two-holders.json"
    table_path.write_text(json.dumps(TWO_HOLDER_TABLE), encoding="utf-8")
    try:
        before = snapshot(root)
        entry = entry_of(quiet(P.probe_profiles, root, proposals, table_path=table_path), "web")
        check_eq("F1: the cure's command is not proven, because S5 would refuse it", (entry["cure"]["proven"], entry["proposal"]), (False, None))
        check_in("F1: the words name the rule and both words that carry the placeholder",
                 "more than one word", entry["cure"]["why_not"])
        check_in("F1: both of them", "`{report_path}`, `{report_path}`", entry["cure"]["why_not"])
        # the control: the SAME run proves a report when S5's contract is out of the way - so the refusal above is the contract's doing
        real = P.s5_contract_refusals
        P.s5_contract_refusals = lambda root_, profile_: []
        try:
            control = quiet(P.probe_candidate, root, "web", [PY, "fake_report.py", "--out", "{report_path}", "--also", "{report_path}"],
                            "junit-xml")
        finally:
            P.s5_contract_refusals = real
        check_eq("F1 (control): without the contract the probe reads that report and calls it proven", control["proven"], True)
        got = quiet(P.probe_candidate, root, "web", [PY, "fake_report.py", "--out", "{report_path}", "--also", "{report_path}"], "junit-xml")
        check_eq("F1: with the contract it is not proven, and the state says S5 refused it", (got["proven"], got["state"]), (False, "refused_by_s5"))
        check_in("F1: and no run was made for it (the contract comes first)", "S5 would refuse", got["why"])
        check_eq("F1: nothing written", snapshot(root), before)
    finally:
        cleanup(root)
        cleanup(proposals)
        table_path.unlink(missing_ok=True)


def f1_the_embedded_report_path_is_what_s5_reads_too() -> None:
    """The dotnet cure's `trx;LogFileName={report_path}` is ONE word with the placeholder inside it: the validator (the node
    spec's F1 hunk, execution_request) and run_suite's substitution must both take it, or the cure is proven by a probe that
    S5 cannot run. Held to the sources, so a revert of either side is seen here."""
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    try:
        import execution_request as ER
        import inspect
        import run_suite
        base = {"argv": [PY, "fake_dotnet.py", "test", "--logger", "trx;LogFileName={report_path}"], "cwd": ".", "reporter": "trx",
                "report_path": "{report_path}"}

        def validator_says(argv, reporter="trx") -> str:
            try:
                ER.validate_request({"command": dict(base, argv=argv, reporter=reporter)}, root)
            except ER.RequestError as exc:
                return str(exc)
            return ""

        cases = {"embedded in one word": base["argv"],
                 "a whole word": [PY, "x.py", "{report_path}"],
                 "no word carries it": [PY, "x.py", "test"],
                 "two words carry it": [PY, "x.py", "--a={report_path}", "--b", "{report_path}"]}
        for label, argv in cases.items():
            prof = profile("web", argv, reporter={"kind": "trx"})
            mine = P.s5_contract_refusals(root, prof)
            theirs = validator_says(argv)
            none_ = "explicit {report_path} token" in theirs
            two = "exactly one token" in theirs
            check_eq(f"F1 twin: {label}: my contract and validate_request agree on 'no word' and 'two words'",
                     (bool(mine), none_ or two), (label in ("no word carries it", "two words carry it"), label in ("no word carries it", "two words carry it")))
            check_eq(f"F1 twin: {label}: they name the same fault",
                     ("no word of it carries" in " ".join(mine), "more than one word" in " ".join(mine)), (none_, two))
        source = inspect.getsource(run_suite)
        check("F1: run_suite replaces the placeholder INSIDE a word (the probe does, and the cure's word has it embedded)",
              'part.replace("{report_path}"' in source, "run_suite no longer substitutes inside a word")
        check("F1: the validator accepts the placeholder embedded in a word",
              'holders = [x for x in argv if isinstance(x, str) and "{report_path}" in x]' in inspect.getsource(ER),
              "execution_request no longer counts holders by `in`")
    finally:
        cleanup(root)


def k_two_profiles_two_rounds_both_applied_the_second_never_stale() -> None:
    root = project([profile("api", [PY, "fake_vitest.py", "run", "vitest"]), profile("web", [PY, "fake_dotnet.py", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        first = quiet(P.probe_profiles, root, proposals)
        api, web = entry_of(first, "api"), entry_of(first, "web")
        check_eq("K-two-profiles: round 1 seals ONE proposal, the first profile's", (api["move"], web["move"]), ("do_it", "waits_for_turn"))
        check_eq("K-two-profiles: the second profile has none yet", web["proposal"], None)
        check_in("K-two-profiles: and its sentence says it waits, and for whom", "`api`", web["says"])
        check_eq("K-two-profiles: its cure is known and not yet measured", (web["cure"]["action"], web["cure"]["proven"]), ("add", None))
        check_eq("K-two-profiles: one file in the folder", len(list(proposals.iterdir())), 1)
        say_yes(root, api)
        second = quiet(P.probe_profiles, root, proposals)
        api2, web2 = entry_of(second, "api"), entry_of(second, "web")
        check_eq("K-two-profiles: round 2 - the first is proven (the confirmation), the second is asked now",
                 (api2["report"]["state"], api2["move"], web2["move"]), ("proven", "nothing", "do_it"))
        sealed = load_sealed(web2)
        check_eq("K-two-profiles: the second proposal is sealed against the config as it IS now (the first one's cure is in it)",
                 (sealed["input_hash"], argv_of(sealed["proposed_config"], "api")),
                 (C._json_hash(config_of(root)), argv_of(config_of(root), "api")))
        say_yes(root, web2)
        final = config_of(root)
        check_eq("K-two-profiles: BOTH cures are in the config", [argv_of(final, "api")[-2:], argv_of(final, "web")[-2:]],
                 [["--reporter=junit", "--outputFile={report_path}"], ["--logger", "trx;LogFileName={report_path}"]])
        check_eq("K-two-profiles: each profile's report kind is its own cure's",
                 [p["reporter"]["kind"] for p in final["profiles"]], ["junit-xml", "trx"])
        third = quiet(P.probe_profiles, root, proposals)
        check_eq("K-two-profiles: and both prove", [e["report"]["state"] for e in third["profiles"]], ["proven", "proven"])
        old = refusal_of(lambda: C.record_approval(root, api["proposal"] and load_sealed(api), "onboarding-cure:api:again", "t:2"))
        check_in("K-two-profiles (the replay the critic witnessed): an OLD proposal is refused as stale, never applied", "stale", old)
        # a decline leaves the profile alone: `only` probes the others and the declined one is not proposed again
        only = quiet(P.probe_profiles, root, proposals, only=["web", "nobody"])
        check_eq("K-two-profiles: `only` limits the probe, and names an id that is not there",
                 ([e["profile"] for e in only["profiles"]], only["unknown_profiles"]), (["web"], ["nobody"]))
    finally:
        cleanup(root)
        cleanup(proposals)


def f3_a_person_gives_a_command_it_is_proven_and_sealed_like_a_cure() -> None:
    root = project([profile("web", [PY, "fake_karma.py", "ng", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    line = "python fake_report.py --out {report_path}"
    try:
        before = snapshot(root)
        got = quiet(P.probe_person_command, root, "web", line, proposals, "junit-xml")
        check_eq("F3: the person's command is proven (S5's contract first, then one run) and sealed", (got["move"], got["report"]["state"]), ("do_it", "proven"))
        sealed = load_sealed(got)
        check_eq("F3: it is a proposal of the kind `command` (hash-covered), a sibling of the cure", sealed["listing"]["kind"], "command")
        check_eq("F3: the argv is the line, split", argv_of(sealed["proposed_config"], "web"), ["python", "fake_report.py", "--out", "{report_path}"])
        check_eq("F3: nothing is written before the yes", snapshot(root), before)
        question = got["proposal"]["question"]
        check_in("F3: the sentence names the command the person gave", "python fake_report.py --out {report_path}", question)
        check_in("F3: and says it proved", "you gave", question)
        say_yes(root, got)
        check_eq("F3: the yes applies it through the same path", (argv_of(config_of(root), "web"),
                 config_of(root)["profiles"][0]["reporter"]["kind"]), (["python", "fake_report.py", "--out", "{report_path}"], "junit-xml"))
        same = quiet(P.probe_person_command, root, "web", line, proposals, "junit-xml")
        check_eq("F3 (E18): the same command again is 'already the command', no proposal", (same["move"], same["proposal"]), ("nothing", None))
        # no kind given on a profile that names none, command not pytest: S5 would read no report - not proven, said in words
        other = project([profile("api", [PY, "fake_karma.py", "ng", "test"])])
        try:
            nokind = quiet(P.probe_person_command, other, "api", line, proposals)
            check_eq("F3: with no report kind anywhere, S5 would read nothing: not proven", (nokind["move"], nokind["proposal"]), ("explain_and_ask", None))
            check_in("F3: and the words say which kind is missing", "Say which report it writes", nokind["says"])
        finally:
            cleanup(other)
    finally:
        cleanup(root)
        cleanup(proposals)


def f3_a_line_that_is_no_command_is_refused_in_words_and_nothing_is_run() -> None:
    root = project([profile("web", [PY, "fake_karma.py", "ng", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = snapshot(root)
        ran = []
        real = P.probe_candidate
        P.probe_candidate = lambda *a, **k: ran.append(a) or {"proven": False, "state": "x", "why": "x", "detail": ""}
        try:
            rows = [("Y9: a drive-rooted path", r"C:\tools\runner.exe --out {report_path}", "exists only on this machine"),
                    ("Y9: a posix absolute path", "/usr/local/bin/runner --out {report_path}", "exists only on this machine"),
                    ("Y9: a path inside an option", "runner --config=/home/anna/x.cfg", "exists only on this machine"),
                    ("Y9: a home shortcut", "~/bin/runner --out {report_path}", "exists only on this machine"),
                    ("an unclosed quote", 'python "fake_report.py --out {report_path}', "cannot be split into a command"),
                    ("an empty line", "   ", "holds no command"),
                    ("a shell pipeline", "python fake_report.py | tee out.txt", "needs a shell"),
                    ("a chained command", "python a.py && python b.py", "needs a shell"),
                    ("a redirect", "python a.py > out.txt", "needs a shell")]
            for label, text, words in rows:
                got = P.probe_person_command(root, "web", text, proposals, "junit-xml")
                check_eq(f"F3: {label} is refused", (got["move"], got["proposal"]), ("refused", None))
                check_in(f"F3: {label}: the words say why", words, got["says"])
            got = P.probe_person_command(root, "nobody", "python x.py", proposals)
            check_in("F3: a profile that is not there is named", "`nobody` is not in the configuration", got["says"])
            got = P.probe_person_command(root, "web", "python x.py", proposals, "xunit")
            check_in("F3: a report kind outside the list is refused", "junit-xml, trx", got["says"])
            refused_ran = list(ran)
            P.probe_person_command(root, "web", "python fake_report.py --out {report_path}", proposals, "junit-xml")
            check_eq("F10 (positive control): a line that IS a command reaches the probe with the same patch in place - so `ran == []` means something",
                     len(ran), 1)
        finally:
            P.probe_candidate = real
        check_eq("F3: none of the refused lines ran a test (the refusal comes before the probe)", refused_ran, [])
        check_eq("F3: and none wrote anything", snapshot(root), before)
    finally:
        cleanup(root)
        cleanup(proposals)


def f8_the_edges_of_the_cure() -> None:
    # `add_argv` already in the command and only what it needs is missing: no second flag, the dependency named
    flagged = {"id": "fakecure", "match": ["fake_report"], "words": "fake: the reporter package is missing", "flag": ["--out", "{report_path}"],
               "add_argv": ["--out", "{report_path}"], "reporter_kind": "junit-xml", "needs": ["the `fake-reporter` package"],
               "propose_text": "I propose to run the {profile} tests as: `{command}`. Do it? yes / no"}
    prof = profile("web", [PY, "fake_report.py", "--out", "{report_path}"])
    cls = P.classify_cure(prof, [flagged])
    check_eq("F8: the flag is already there and a dependency is missing: the dependency step only, no candidate with a second flag",
             (cls["action"], cls["candidate"]), ("dependency_only", None))
    cls = P.classify_cure(prof, [dict(flagged, needs=[])])
    check_eq("F8: flag present, nothing missing: 'present' (the cause is elsewhere), still no second flag", (cls["action"], cls["candidate"]), ("present", None))
    cls = P.classify_cure(profile("web", [PY, "fake_report.py"]), [flagged])
    check_eq("F8: flag absent: a candidate with it added", (cls["action"], cls["candidate"]), ("add", [PY, "fake_report.py", "--out", "{report_path}"]))
    check_eq("F8: the flag goes before a bare `--` (what follows belongs to the inner runner)",
             P.with_added(["run", "--", "x"], ["--a"]), ["run", "--a", "--", "x"])
    # a cure that sets the report kind on a profile whose kind is already another one: refused in words, the explaining question
    conflict = profile("web", [PY, "fake_dotnet.py", "test"], reporter={"kind": "junit-xml"})
    table = P.cure_table()[0]
    cls = P.classify_cure(conflict, table["rows"])
    check_eq("F8: the dotnet cure writes trx and the profile says junit-xml: no candidate", (cls["action"], cls["candidate"]), ("kind_conflict", None))
    root = project([conflict])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        entry = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_eq("F8: so no proposal, the explaining question", (entry["proposal"], entry["move"]), (None, "explain_and_ask"))
        check_in("F8: and it says a recorded kind is not overwritten", "not overwritten", entry["says"])
        check_in("F8: the maker refuses the same in words", "not overwritten",
                 refusal_of(lambda: C.command_proposal(root, {"profile_id": "web"}, [PY, "x"], reporter_kind="trx", question=f"`{PY} x`")))
        # a pytest command whose path says `karma` is never handed a karma cure
        pyk = profile("web", ["python", "-m", "pytest", "tests/test_karma_things.py"])
        check_eq("F8: pytest-shaped wins over a framework word in a path", P.classify_cure(pyk, table["rows"])["action"], "diagnosis")
        check_eq("F8: while a command that is not pytest-shaped is still read by its words",
                 P.classify_cure(profile("web", ["npx", "karma", "start"]), table["rows"])["action"], "explain")
        # a folder for proposals INSIDE the project is refused: a proposal file there is a trace of the probe
        inside = root / "qa-factory" / "tmp-proposals"
        rejected = refusal_of(lambda: quiet(P.probe_profiles, root, inside))
        check_in("F8: a proposals folder inside the project is refused, with the door", "name a folder outside it", rejected)
        check("F8: and nothing was made there", not inside.exists())
    finally:
        cleanup(root)
        cleanup(proposals)


def f6_a_flag_is_matched_by_its_name_and_never_written_twice() -> None:
    rows = P.cure_table()[0]["rows"]

    def classify(argv: list) -> dict:
        return P.classify_cure(profile("web", argv), rows)

    vit = ["npx", "vitest", "run"]
    half = classify(vit + ["--reporter=junit"])
    check_eq("F6: an option half there is never written twice - only the missing one is added",
             (half["action"], half["candidate"], half["changed"]), ("add", vit + ["--reporter=junit", "--outputFile={report_path}"], []))
    check_eq("F6 AT: every option there with the cure's own value is 'already the command' (no candidate)",
             (lambda c: (c["action"], c["candidate"]))(classify(vit + ["--reporter=junit", "--outputFile={report_path}"])), ("present", None))
    other = classify(vit + ["--reporter=dot", "--outputFile=out.xml"])
    check_eq("F6 BEYOND: the same options with ANOTHER value: the cure proposes the change - values replaced in place, nothing twice",
             (other["action"], other["candidate"], other["changed"]),
             ("add", vit + ["--reporter=junit", "--outputFile={report_path}"], ["--reporter", "--outputFile"]))
    dot = classify(["dotnet", "test", "--logger", "junit;LogFilePath=x"])
    check_eq("F6 BEYOND: dotnet with another logger: replaced in place, ONE --logger", (dot["action"], dot["candidate"], dot["changed"]),
             ("add", ["dotnet", "test", "--logger", "trx;LogFileName={report_path}"], ["--logger"]))
    glued = classify(["dotnet", "test", "--logger=junit;LogFilePath=x"])
    check_eq("F6 BEYOND: the glued form is replaced in the glued form", glued["candidate"], ["dotnet", "test", "--logger=trx;LogFileName={report_path}"])
    check_eq("F6 AT: dotnet with the cure's logger is 'already the command'", classify(["dotnet", "test", "--logger", "trx;LogFileName={report_path}"])["action"], "present")
    check_eq("F6: and the `--` rule still holds with a changed option in front of it",
             classify(["dotnet", "test", "--logger", "x", "--", "RunConfiguration.Y=1"])["candidate"],
             ["dotnet", "test", "--logger", "trx;LogFileName={report_path}", "--", "RunConfiguration.Y=1"])
    # the whole way: the probe proves the REPLACED command, the sentence says it replaces, the command carries one logger
    root = project([profile("web", [PY, "fake_dotnet.py", "test", "--logger", "junit;LogFilePath=x"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        entry = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_eq("F6: the replaced command is proven and proposed", (entry["move"], entry["cure"]["changed"]), ("do_it", ["--logger"]))
        question = entry["proposal"]["question"]
        check_eq("F6: the proposed command carries ONE logger", entry["proposal"]["command"].count("--logger"), 1)
        check_in("F6: and the sentence SAYS it replaces a value", "replaces that value and adds nothing twice", question)
        plain = project([profile("web", [PY, "fake_dotnet.py", "test"])])
        try:
            check_not_in("F6 (twin): a cure that only adds says no such thing", "replaces that value",
                         entry_of(quiet(P.probe_profiles, plain, proposals), "web")["proposal"]["question"])
        finally:
            cleanup(plain)
    finally:
        cleanup(root)
        cleanup(proposals)


def f7_the_same_command_with_a_new_kind_is_a_kind_only_proposal() -> None:
    line = "python fake_report.py --out {report_path}"
    argv = ["python", "fake_report.py", "--out", "{report_path}"]
    root = project([profile("web", argv)])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = snapshot(root)
        got = quiet(P.probe_person_command, root, "web", line, proposals, "junit-xml")
        check_eq("F7: the same words and a report kind the profile did not carry: NOT 'already the command' - a proposal", got["move"], "do_it")
        sealed = load_sealed(got)
        check_eq("F7: kind-only: the argv is unchanged, the kind is the change", (argv_of(sealed["proposed_config"], "web"), sealed["changes"][0]["from"],
                 sealed["changes"][0]["also"][0]["to"]), (argv, argv, "junit-xml"))
        check_in("F7: and the sentence says the kind is new", "records which kind of report that command writes", got["proposal"]["question"])
        check_eq("F7: nothing written before the yes", snapshot(root), before)
        say_yes(root, got)
        check_eq("F7: the yes records the kind", config_of(root)["profiles"][0]["reporter"], {"kind": "junit-xml"})
        again = quiet(P.probe_person_command, root, "web", line, proposals, "junit-xml")
        check_eq("F7 (twin): the same words and the kind it now carries: 'already the command'", (again["move"], again["proposal"]), ("nothing", None))
        none_given = quiet(P.probe_person_command, root, "web", line, proposals)
        check_eq("F7 (twin): the same words and no kind given: 'already the command'", none_given["move"], "nothing")
        other_kind = quiet(P.probe_person_command, root, "web", line, proposals, "trx")
        check_eq("F7: a kind that contradicts the recorded one is not overwritten (not proven, said)", (other_kind["move"], other_kind["proposal"]), ("explain_and_ask", None))
    finally:
        cleanup(root)
        cleanup(proposals)


def f8_zero_profiles_a_profile_with_no_command_and_a_config_that_is_not_there() -> None:
    root = project([])
    try:
        result = quiet(P.probe_profiles, root)
        check_in("edge: a config with zero profiles says so, in words", "records no execution profile", result["problem"])
        check_eq("edge: and probes nothing", result["profiles"], [])
        empty = project([{"profile_id": "web", "commands": {}}])
        entry = entry_of(quiet(P.probe_profiles, empty), "web")
        check_eq("edge: a profile with no `one_test` is `not_checked`, with the reason, and the next move is a line",
                 (entry["report"]["state"], entry["move"]), ("not_checked", "tell"))
        check_in("edge: the reason names the missing command", "records no command", entry["report"]["why"])
        cleanup(empty)
        (root / "qa-factory" / "config.json").unlink()
        gone = quiet(P.probe_profiles, root)
        check_in("edge: no config at all: onboarding writes it first", "there is no qa-factory/config.json yet", gone["problem"])
        (root / "qa-factory" / "config.json").write_text("{broken", encoding="utf-8")
        broken = quiet(P.probe_profiles, root)
        check_in("edge: an unreadable config is named with its door", "not valid JSON", broken["problem"])
        check_in("edge: and the maker refuses it the same way",  "not valid JSON",
                 refusal_of(lambda: C.command_proposal(root, {"profile_id": "web"}, ["x"], question="`x`")))
    finally:
        cleanup(root)


def states_every_state_has_a_move() -> None:
    """FR-42: no_test, launcher_missing, timed_out, not_checked, proven, no_report - each ends in a move the skill can make."""
    seen = {}
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    try:
        (root / "tests" / "test_one.py").unlink()
        entry = entry_of(quiet(P.probe_profiles, root), "web")
        seen["no_test"] = (entry["report"]["state"], entry["move"])
        check_in("E23: no existing test: one line, and the gate checks it at the first story", "no existing test to prove the report with", entry["says"])
        (root / "tests" / "test_one.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
        cfg = config_of(root)
        cfg["profiles"][0]["commands"]["one_test"]["argv"] = ["no-such-launcher-qa-onb", "test"]
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        entry = entry_of(quiet(P.probe_profiles, root), "web")
        seen["launcher_missing"] = (entry["report"]["state"], entry["move"])
        check_in("F-5: the missing launcher line says what was checked (PATH with PATHEXT), not 'not on this machine'",
                 "`no-such-launcher-qa-onb` was looked up on PATH with PATHEXT and not found", entry["says"])
        check_in("F-5: ... and the door", "correct argv[0] of the profile", entry["says"])
        cfg["profiles"][0]["commands"]["one_test"]["argv"] = [PY, "-c", "import time; time.sleep(30)"]
        cfg["gate_rehearsal"] = {"reporter_timeout_s": 1}
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        entry = entry_of(quiet(P.probe_profiles, root), "web")
        seen["timed_out"] = (entry["report"]["state"], entry["move"])
        check_in("E24: a timeout gives no proposal and one line", "did not finish within 1 s", entry["says"])
        cfg["gate_rehearsal"] = {"skip_reporter": True}
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        entry = entry_of(quiet(P.probe_profiles, root), "web")
        seen["not_checked"] = (entry["report"]["state"], entry["move"])
        check_in("the project's own switch turns the probe off, and that is said", "turn the report rehearsal off", entry["report"]["why"])
    finally:
        cleanup(root)
    check_eq("FR-42: each state ends in a move", seen, {"no_test": ("no_test", "tell"), "launcher_missing": ("launcher_missing", "tell"),
                                                         "timed_out": ("timed_out", "tell"), "not_checked": ("not_checked", "tell")})


# What the gate's own collect (`check_s5_toolchain`, real pytest, no `-p no:cacheprovider`) may leave in the tests folder of a
# project: pytest's cache folder, and only that. Gate_preflight is not this node's to fix (an analog, FR-45). Which files lie in
# that folder is pytest's business and changes with its version - pytest 8.3 wrote four (.gitignore, CACHEDIR.TAG, README.md,
# v/cache/stepwise), pytest 9.1 writes none for a `--collect-only` (CI, B-305 b / B-307: the same test file was green on 8.3 and
# red on 9.1 for exactly that) - so the folder is left out of the comparison whole, and what is compared is everything else.
COLLECT_CACHE_DIR = "tests/.pytest_cache/"


def outside_the_collect_cache(paths) -> set:
    """The paths that are not inside pytest's own cache folder of the collect."""
    return {p for p in paths if not str(p).replace("\\", "/").startswith(COLLECT_CACHE_DIR)}
PYTEST_TEMPLATES = {"one_test": "python -m pytest <test-file>", "suite": "python -m pytest", "quiet": ""}


def c_the_probe_leaves_the_project_as_it_was_but_for_the_known_collect_cache() -> None:
    """Real collect: the temp report folder is outside the project (removed), and the ONLY thing left in the tree is the pytest
    cache of the gate's collect, named file by file - a wildcard would let a new leftover pass."""
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])], test_command_templates=PYTEST_TEMPLATES)
    proposals = temp_dir("qa-onb-proposals-")
    try:
        before = snapshot(root)
        entry = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_eq("c: the probe ran and proposed (the collect did not stop it)", entry["move"], "do_it")
        after = snapshot(root)
        check_eq("c: nothing was removed or changed", {k: v for k, v in after.items() if k in before}, before)
        check_eq("c: the only new files are the collect's pytest cache folder, whichever files this pytest writes into it",
                 outside_the_collect_cache(set(after) - set(before)), set())
    finally:
        cleanup(root)
        cleanup(proposals)


FAKE_BOMB = '''import sys
from pathlib import Path
Path(sys.argv[1]).write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><testsuite tests="1"><testcase classname="c" name="&b;"/></testsuite>', encoding="utf-8")
'''


def b416_g12_the_onboarding_inherits_the_readers_and_keeps_nothing() -> None:
    """B-416 G12: `ProbeRehearsal` inherits the entity refusal and the reader trial of the gate's rehearsal; a candidate
    (`durable=False`) keeps NOTHING under `reporter-unread/`, and neither does the onboarding's own probe (no story, no conductor turn
    is owed there: the probe leaves the project as it was but for the proven-rehearsal record). Onboarding's own text is unchanged."""
    root = project([profile("web", [PY, "fake_bomb.py", "{report_path}"], reporter={"kind": "junit-xml"})])
    (root / "fake_bomb.py").write_text(FAKE_BOMB, encoding="utf-8")
    proposals = temp_dir("qa-onb-proposals-")
    try:
        got = quiet(P.probe_candidate, root, "web", [PY, "fake_bomb.py", "{report_path}"], "junit-xml")
        check_eq("G12: a candidate whose report declares entities is not proven (the refusal is inherited)", got["proven"], False)
        check_in("G12: and the words say the factory does not expand entities", "does not expand", got["why"])
        check_eq("G12: a candidate keeps nothing: no `reporter-unread/` folder", (root / "qa-factory" / "state" / "reporter-unread").exists(), False)
        before = snapshot(root)
        entry = entry_of(quiet(P.probe_profiles, root, proposals), "web")
        check_eq("G12: the onboarding's own probe reads the same refusal", entry["report"]["state"] != "proven", True)
        check_eq("G12: and it keeps nothing either (the project is as it was, but for the collect's cache)",
                 outside_the_collect_cache({k for k in set(snapshot(root)) - set(before)}), set())
        check_eq("G12: no `reporter-unread/` folder, and no record of the helper's", ((root / "qa-factory" / "state" / "reporter-unread").exists(),
                 (root / "qa-factory" / "records" / "report-adaptations.json").exists()), (False, False))
    finally:
        cleanup(root)
        cleanup(proposals)


def selected_false_is_not_probed_at_all() -> None:
    marker = "import pathlib; pathlib.Path('ran.txt').write_text('x')"
    root = project([profile("off", [PY, "-c", marker], selected=False), profile("web", [PY, "fake_dotnet.py", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        result = quiet(P.probe_profiles, root, proposals)
        off = entry_of(result, "off")
        check_eq("a profile that is not selected: `not_checked`, 'not selected', a line, no cure, no proposal",
                 (off["report"]["state"], off["report"]["why"], off["move"], off["cure"], off["proposal"]), ("not_checked", "not selected", "tell", None, None))
        check("and ZERO runs for it (its command would have left a marker)", not (root / "ran.txt").exists())
        check_eq("the selected profile beside it is probed as ever", entry_of(result, "web")["move"], "do_it")
    finally:
        cleanup(root)
        cleanup(proposals)


def f11_the_durable_key_leaves_out_the_stand() -> None:
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    try:
        one0 = config_of(root)
        ids = [P.ProbeRehearsal(root, one0)._rehearsal_key("web", root, [PY, "x"], "t", "trx", ident, root) for ident in ("sha-a", "sha-b", "")]
        check_eq("F11: nor on what a stand runs: the key is profile + argv + test + format + dependency bytes, whatever identity is offered",
                 len(set(ids)), 1)
        gate_base = G.Rehearsal(root, "A")
        gate_base.config = one0
        check_eq("F11 (B-220 part 2): gate A's own key no longer moves with the identity either - the override and the base now agree",
                 gate_base._rehearsal_key("web", root, [PY, "x"], "t", "trx", "sha-a", root), gate_base._rehearsal_key("web", root, [PY, "x"], "t", "trx", "sha-b", root))
        check_eq("F11: and the probe asks no stand for one (no run of a runtime probe)", P.ProbeRehearsal(root, one0)._observed_identity("web", root), "")
    finally:
        cleanup(root)
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    try:
        one = copy.deepcopy(config_of(root))
        two = copy.deepcopy(one)
        two["environments"] = [{"name": "staging"}]
        keys = []
        for cfg in (one, two):
            rehearsal = P.ProbeRehearsal(root, cfg)
            keys.append(rehearsal._rehearsal_key("web", root, [PY, "x"], "tests/test_one.py", "trx", "", root))
        check("F11: the key is built (not empty)", bool(keys[0]))
        check_eq("F11: the proof does not depend on which stand is recorded", keys[0], keys[1])
        gate = []
        for cfg in (one, two):
            base = G.Rehearsal(root, "A")
            base.config = cfg
            gate.append(base._rehearsal_key("web", root, [PY, "x"], "tests/test_one.py", "trx", "", root))
        check_eq("F11 (B-220 part 2): gate A's own key no longer moves with the stand - the override and the base now agree", gate[0], gate[1])
        check("F11 (control): another command IS another key (a control that can fail)",
              G.Rehearsal(root, "A")._rehearsal_key("web", root, [PY, "x"], "t", "trx", "", root)
              != G.Rehearsal(root, "A")._rehearsal_key("web", root, [PY, "y"], "t", "trx", "", root))
        candidate = P.ProbeRehearsal(root, one, durable=False)
        check_eq("a candidate is never durable: its key is empty (never matches, never recorded)",
                 candidate._rehearsal_key("web", root, [PY, "x"], "t", "trx", "", root), "")
    finally:
        cleanup(root)


def cli_stdout_is_json_only_and_the_sentence_comes_from_the_sealed_file() -> None:
    root = project([profile("web", [PY, "fake_dotnet.py", "test"])])
    proposals = temp_dir("qa-onb-proposals-")
    try:
        done = harness.run_script("onboarding_probe.py", "--root", root, "--probe-profiles", "--proposals-dir", proposals, "--json", cwd=root)
        check_eq("CLI: exits 0 - the report is the answer", done.returncode, 0)
        data = json.loads(done.stdout)
        check("CLI: stdout is ONE JSON object (FR-14)", isinstance(data, dict) and data["profiles"][0]["move"] == "do_it", done.stdout[:300])
        check_in("CLI: progress goes to stderr, line by line (FR-43)", "onboarding_probe: running one existing test", done.stderr)
        path = data["profiles"][0]["proposal"]["path"]
        asked = harness.run_script("onboarding_probe.py", "--question", path, cwd=root)
        check_eq("CLI --question: prints the sentence of the sealed file", asked.stdout.strip(), data["profiles"][0]["proposal"]["question"].strip())
        sealed = json.loads(Path(path).read_text(encoding="utf-8"))
        sealed["listing"]["question"] = sealed["listing"]["question"].replace("Do it?", "Do it now?")
        Path(path).write_text(json.dumps(sealed), encoding="utf-8")
        edited = harness.run_script("onboarding_probe.py", "--question", path, cwd=root)
        check_eq("CLI --question: a sealed file edited after it was made is refused (exit 1), nothing shown", (edited.returncode, edited.stdout.strip()), (1, ""))
        check_in("CLI --question: with the word the person's yes would have been bound to", "stale", edited.stderr)
        inside = harness.run_script("onboarding_probe.py", "--root", root, "--probe-profiles", "--proposals-dir", root / "qa-factory" / "p", cwd=root)
        check_eq("CLI: a proposals folder inside the project is refused (exit 1)", inside.returncode, 1)
        check_in("CLI: with its reason on stderr and nothing on stdout", "inside the project", inside.stderr)
        check_eq("CLI: stdout stays empty on a refusal", inside.stdout.strip(), "")
        person = harness.run_script("onboarding_probe.py", "--root", root, "--profile", "web", "--command", "python fake_report.py --out {report_path}",
                                    "--kind", "junit-xml", "--proposals-dir", proposals, cwd=root)
        got = json.loads(person.stdout)
        check_eq("CLI --command: one JSON object, proven and sealed", (got["move"], got["proposal"]["approval_ref"].startswith("onboarding-command:web:")),
                 ("do_it", True))
        misuse = harness.run_script("onboarding_probe.py", "--root", root, "--command", "x", cwd=root)
        check_eq("CLI --command: without exactly one --profile is a misuse (exit 2)", misuse.returncode, 2)
    finally:
        cleanup(root)
        cleanup(proposals)


def one_home_of_the_words() -> None:
    """The cure words have ONE home (FR-13, t-398): references/report-cures.json, read through ONE module (`report_cures`). The
    probe's `row_for` / `cure_words` ARE the leaf's functions, and `run_suite.report_cure` reads through the same one, so the
    runner and the probe say the same words for every row - vitest's corrected row included (F8)."""
    import report_cures
    import run_suite
    check_eq("one home: the probe's row_for is the leaf's, not a copy", (P.row_for is report_cures.row_for, P.cure_words is report_cures.cure_words),
             (True, True))
    check_eq("one home: the runner carries no table of its own", hasattr(run_suite, "REPORT_CURES"), False)
    samples = {"karma": ["ng", "test"], "ng e2e": ["ng", "e2e"], "jest": ["npx", "jest"], "vitest": ["npx", "vitest", "run"],
               "dotnet": ["dotnet", "test"], "vstest": ["vstest.console.exe", "x.dll"], "playwright": ["npx", "playwright", "test"],
               "pytest": ["python", "-m", "pytest"], "unknown": ["make", "check"], "empty": []}
    for label, argv in samples.items():
        check_eq(f"one home: `{label}` - the runner and the probe say the same words", P.cure_words(argv), run_suite.report_cure(argv))
    check_in("F8: the vitest row says vitest's own junit reporter, with its output file", "--reporter=junit --outputFile={report_path}",
             P.cure_words(["npx", "vitest", "run"]))
    check_not_in("F8: and not jest's package", "jest-junit", P.cure_words(["npx", "vitest", "run"]))
    check_eq("pytest -> '' (the runner equips it)", P.cure_words(["pytest"]), "")
    table, why = P.cure_table()
    check_eq("the shipped table is read whole", (why, [r["id"] for r in table["rows"]]), ("", ["karma", "jest", "vitest", "dotnet", "playwright", "pytest"]))
    check_eq("only the argv cures carry words to add: vitest, dotnet and playwright (EP1-22: its flag, with the variable in add_env)",
             [r["id"] for r in table["rows"] if r["add_argv"] is not None], ["vitest", "dotnet", "playwright"])


def ep1_37_direct_form_note() -> None:
    """EP1-37 p. 7 (B-6): a profile whose one-test command is the project's OWN script (no known run form, not pytest) gets
    `direct_form` words whatever the move; a known form, pytest, no command and an unreadable command get none."""
    import onboarding_probe as OP

    def profile(argv):
        return {"profile_id": "p", "commands": {"one_test": {"argv": argv}}}
    note = OP._direct_form_note(profile(["./run-tests.sh", "<test-id>"]))
    check_in("the project's script: the factory names it and says it builds no selector", "the project's own script", note)
    check_in("and names the program", "./run-tests.sh", note)
    check_eq("pytest: no note", OP._direct_form_note(profile(["python", "-m", "pytest", "<test-file>"])), "")
    check_eq("a known run form (the runner's own direct command): no note", OP._direct_form_note(profile(["npx", "playwright", "test"])), "")
    check_eq("no command: no note", OP._direct_form_note({"profile_id": "p"}), "")
    check_eq("a command it cannot read: no note", OP._direct_form_note(profile("not a list")), "")


def main() -> None:
    ko1_a_proven_cure_becomes_one_sealed_proposal()
    ko2_the_yes_path_writes_one_command_and_the_probe_confirms()
    ko3_no_cure_known_means_words_and_nothing_written()
    ko3_the_cure_table_unreadable_falls_to_the_explaining_question()
    ko4_a_cure_the_probe_rejects_is_withdrawn_before_it_is_shown()
    ko4_a_command_the_probe_reads_and_s5_refuses_is_not_proven()
    f1_the_embedded_report_path_is_what_s5_reads_too()
    k_two_profiles_two_rounds_both_applied_the_second_never_stale()
    f3_a_person_gives_a_command_it_is_proven_and_sealed_like_a_cure()
    f3_a_line_that_is_no_command_is_refused_in_words_and_nothing_is_run()
    f8_the_edges_of_the_cure()
    f6_a_flag_is_matched_by_its_name_and_never_written_twice()
    f7_the_same_command_with_a_new_kind_is_a_kind_only_proposal()
    f8_zero_profiles_a_profile_with_no_command_and_a_config_that_is_not_there()
    states_every_state_has_a_move()
    c_the_probe_leaves_the_project_as_it_was_but_for_the_known_collect_cache()
    b416_g12_the_onboarding_inherits_the_readers_and_keeps_nothing()
    selected_false_is_not_probed_at_all()
    f11_the_durable_key_leaves_out_the_stand()
    cli_stdout_is_json_only_and_the_sentence_comes_from_the_sealed_file()
    one_home_of_the_words()
    ep1_37_direct_form_note()
    finish("test_onboarding_probe")


if __name__ == "__main__":
    main()
