"""HF8-14: when the gate's reporter step has no test to run, the card says WHY, from what the gate gathered.

An empty choice had one text for every cause - "I found no existing test under `tests`" - and it was untrue when test files
were there and the choice was refused (two profiles over one folder, EP1-10) or when the gate's collect listed tests that
lie elsewhere. `_choose_test` now returns a closed code (`why_empty`) and the collect's numbers; the card is built from
them; the onboarding probe reads the same code, so the two twins on one axis say the same thing.

Keys: H-shared, H-nothing, H-empty, H-found, H-named, H-doors, H-probe, H-encoding, H-old.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import gate_preflight  # noqa: E402
import human_text  # noqa: E402
import onboarding_probe  # noqa: E402
import test_reporter_rehearsal as fx  # noqa: E402

PYTEST_ARGV = [fx.D3_PY, "-m", "pytest"]
OLD_TEXT = "I found no existing test under"


def two_profiles(root: Path, ui_root: str = "tests") -> dict:
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    web = cfg["profiles"][0]
    web["profile_id"] = "api"
    web["roots"] = {"test": "tests"}
    cfg["profiles"] = [web, {**json.loads(json.dumps(web)), "profile_id": "ui", "roots": {"test": ui_root}}]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def turn(root, profile_id="api", roots=None, collect="", argv=None, declared=None, rehearsal=None, cwd="."):
    return fx.d3_turn(root, fx.d3_command(argv or [fx.D3_PY, fx.D3_RUNNER, "<t>"], cwd=cwd), profile_id=profile_id,
                      roots=roots or {"test": "tests"}, collect=collect, declared=declared, rehearsal=rehearsal)


def card_text(finding: dict) -> str:
    return f"{finding.get('message', '')} {finding.get('fix', '')}"


def h_shared() -> None:
    """H-shared: two profiles over one folder with files in it -> one card each, in the words of the cause, with the door's price."""
    root = fx.project("qa-choice-shared-")
    try:
        two_profiles(root)
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / fx.TICKET, "A")
        for pid in ("api", "ui"):
            turn(root, profile_id=pid, rehearsal=r)
        check_eq("H-shared: one card per profile", [f.get("profile") for f in r.findings], ["api", "ui"])
        check_eq("H-shared: one note per card", len(r.info), 2)
        for finding in r.findings:
            pid = finding["profile"]
            other = "ui" if pid == "api" else "api"
            check_in(f"H-shared {pid}: says the folder is one", f"The `{pid}` tests and the `{other}` tests are kept in one folder (`tests`)", finding["message"])
            check_not_in(f"H-shared {pid}: never the untrue sentence", OLD_TEXT, card_text(finding))
            check_in(f"H-shared {pid}: and that none was run", "none was run to prove its report", finding["message"])
            check_in(f"H-shared {pid}: the price of going on", "every run of `" + pid + "` is recorded as not executed", finding["fix"])
            check_eq(f"H-shared {pid}: the machine code", finding.get("why_empty"), "shared_root")
        # H-doors for this code
        doors("shared_root", r.findings[0])
    finally:
        cleanup(root)


def doors(code: str, finding: dict) -> None:
    fix = finding.get("fix", "")
    check_in(f"H-doors {code}: the door is the one setting", "gate_rehearsal.reporter_probe_test", fix)
    check_in(f"H-doors {code}: and the other door", "go on and let S5 find out", fix)
    pid = finding.get("profile")
    check_in(f"H-doors {code}: and its price, whatever the cause (F6)", f"every run of `{pid}` is recorded as not executed", fix)
    # a card is ONE PART of a gate question: its message is a sentence, its fix stands on a `the fix:` line, where a setting's key in
    # backticks is allowed (`action_lines`); NOTHING is subtracted from what the checker finds (F8)
    found = human_text.shape_problems(finding.get("message", "") + "\nthe fix: " + fix, kind="question")
    check_eq(f"H-doors {code}: the shape checker finds nothing, on the same form the gate renders", found, [])
    check(f"H-doors {code}: the message is whole inside the packet's cut ({gate_preflight.BRIEF_CUT} characters)",
          len(finding.get("message", "")) <= gate_preflight.BRIEF_CUT, str(len(finding.get("message", ""))))


def h_nothing() -> None:
    """H-nothing: the collect lists tests of another folder and the profile's folder holds no test file."""
    root = fx.project("qa-choice-nothing-")
    try:
        (root / "tests" / "sub").mkdir()
        use_project(root)
        collect = "other/test_x.py::test_x\nother/test_y.py::test_y\n"
        r, calls, _ = turn(root, roots={"test": "tests/sub"}, argv=PYTEST_ARGV, collect=collect)
        finding = r.findings[0] if r.findings else {}
        check_eq("H-nothing: one card, no run", (len(r.findings), calls), (1, []))
        check_eq("H-nothing: the code", finding.get("why_empty"), "nothing_under_profile")
        check_in("H-nothing: N from the data and the folder", "The list of tests the gate read holds 2, none of them under `sub`, the folder of the `api` tests",
                 finding.get("message", ""))
        check_in("H-nothing: no file either", "no test file was found there either", finding.get("message", ""))
        check_not_in("H-nothing: not the untrue sentence", OLD_TEXT, card_text(finding))
        doors("nothing_under_profile", finding)
        # the key is the data, not the text: the same collect in another count says another N
        r, _calls, _ = turn(root, roots={"test": "tests/sub"}, argv=PYTEST_ARGV, collect=collect + "other/test_z.py::test_z\n")
        check_in("H-nothing: N follows the collect", "gate read holds 3,", r.findings[0]["message"])
    finally:
        cleanup(root)


def h_empty() -> None:
    """H-empty: nothing collected (empty output) and no file with a test name -> not 'none of them': the collect is unknown."""
    root = fx.project("qa-choice-empty-")
    try:
        for name in ("test_a_first.py", "test_z_named.py"):
            (root / "tests" / name).unlink()
        use_project(root)
        read_none = "ERROR collecting tests/test_a.py\n=== no tests ran in 0.1s ===\n"
        for label, argv, collect, head in (
                ("pytest, empty collect", PYTEST_ARGV, "", "I have no list of this project's tests (the listing did not run)"),
                ("not pytest", None, "", "I could not list this project's tests (only pytest can be asked, this is not pytest)"),
                ("pytest, a collect that ran and found none (F5)", PYTEST_ARGV, read_none, "The listing of this project's tests found none")):
            r, calls, _ = turn(root, argv=argv, collect=collect)
            finding = r.findings[0] if r.findings else {}
            message = finding.get("message", "")
            check_eq(f"H-empty ({label}): one card, no run", (len(r.findings), calls), (1, []))
            check_eq(f"H-empty ({label}): the code", finding.get("why_empty"), "no_test_files")
            check_in(f"H-empty ({label}): says what the gate had", head, message)
            check_in(f"H-empty ({label}): and no file has a test name", "no file under `tests` has a usual test name", message)
            check_in(f"H-empty ({label}): and what it means for the report", "nothing proves `api` writes a report the tests stage reads", message)
            check_not_in(f"H-empty ({label}): no count of zero tests", "0 test", message)
            check_not_in(f"H-empty ({label}): none of the gate's insides", "collect", message)
            if collect:
                check_not_in(f"H-empty ({label}): a listing that ran is never called 'no output'", "did not run", message)
            doors("no_test_files", finding)
    finally:
        cleanup(root)


def h_found() -> None:
    """H-found: one profile on its folder -> a test is chosen, no card (the regression)."""
    root = fx.project("qa-choice-found-")
    try:
        use_project(root)
        r, calls, _ = turn(root, roots={"test": "tests"})
        check_eq("H-found: no card, and the first test file ran", (r.findings, calls[0]["launch"][-1] if calls else None), ([], "tests/test_a_first.py"))
        chosen = gate_preflight.Rehearsal._choose_test(r, gate_preflight.ReporterCtx("s5_reporter", "api", root, root.resolve(), (fx.D3_PY,), "junit-xml", "junit-xml", 30),
                                                       {}, {"profile_id": "api", "roots": {"test": "tests"}}, {"cwd": "."}, False)
        check_eq("H-found: `_choose_test` returns four elements, the code empty", (len(chosen), chosen[0], chosen[2]), (4, "tests/test_a_first.py", ""))
        check_eq("H-found: the counts are the three named keys", sorted(chosen[3]), ["collected", "prefix", "under_prefix"])
    finally:
        cleanup(root)


def h_named() -> None:
    """H-named: a shared root, but the project named a test -> that test runs, no card."""
    root = fx.project("qa-choice-named-")
    try:
        two_profiles(root)
        use_project(root)
        r, calls, _ = turn(root, declared={"api": "tests/test_z_named.py"})
        check_eq("H-named: no card, the named test ran", (r.findings, calls[0]["launch"][-1] if calls else None), ([], "tests/test_z_named.py"))
    finally:
        cleanup(root)


def h_probe() -> None:
    """H-probe: the onboarding probe reads `why_empty`: nothing_under_profile has its own words; the other codes keep the old ones.
    `shared_root` is unreachable there (`SHARED_ROOT_PICKS_NOTHING` is False)."""
    check_eq("H-probe: the probe never refuses by shared root", onboarding_probe.ProbeRehearsal.SHARED_ROOT_PICKS_NOTHING, False)
    old = "there is no existing test to run through this command"
    root = fx.project("qa-choice-probe-")
    try:
        (root / "tests" / "sub").mkdir()
        use_project(root)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))

        def probe(collect, roots, argv):
            profile = json.loads(json.dumps(cfg["profiles"][0]))
            profile["roots"] = roots
            profile["commands"]["one_test"]["argv"] = argv
            rehearsal = onboarding_probe.ProbeRehearsal(root, cfg, durable=False)
            rehearsal.collect_stdout = collect
            return onboarding_probe._probe_one(rehearsal, profile, root, 30, None)

        got = probe("other/test_x.py::test_x\n", {"test": "tests/sub"}, [sys.executable, "-m", "pytest"])
        check_eq("H-probe: nothing_under_profile", (got["state"], got["why"]), ("no_test", "the gate's collect listed tests, none under this profile's folder"))
        got = probe("", {"test": "tests/sub"}, [sys.executable, "-m", "pytest"])
        check_eq("H-probe: no_test_files keeps the old words", (got["state"], got["why"]), ("no_test", old))
        got = probe("other/test_x.py::test_x\n", {"test": "tests/sub"}, [sys.executable, "runner.py", "<t>"])
        check_eq("H-probe: not pytest (an empty code of the collect) keeps the old words", (got["state"], got["why"]), ("no_test", old))
    finally:
        cleanup(root)


def h_encoding() -> None:
    """H-encoding: a profile id in Cyrillic and an ASCII console -> the gate's CLI prints the card, no traceback."""
    pid = "".join(chr(code) for code in (0x432, 0x435, 0x431))      # three Cyrillic letters, built so that the file holds none (FR-30)
    root = fx.project("qa-choice-encoding-")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["profiles"][0]["profile_id"] = pid
        cfg["profiles"][0]["roots"] = {"test": "tests/sub"}
        cfg["profiles"][0]["capabilities"] = ["api"]
        cfg["profiles"][0]["commands"]["one_test"]["argv"] = [sys.executable, "-m", "pytest"]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        (root / "tests" / "sub").mkdir()
        env = dict(os.environ, PYTHONIOENCODING="ascii", PYTHONDONTWRITEBYTECODE="1", CLAUDE_PROJECT_DIR=str(root))
        task_root = root / "qa-factory" / "artifacts" / fx.TICKET
        for flag in ([], ["--text"]):
            done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gate_preflight.py"), "--task-root", str(task_root), "--gate", "A", *flag],
                                  capture_output=True, env=env, cwd=str(root), timeout=300)
            err = done.stderr.decode("utf-8", errors="replace")
            check(f"H-encoding {flag or 'json'}: no traceback", "Traceback" not in err and "UnicodeEncodeError" not in err, err[-600:])
            check(f"H-encoding {flag or 'json'}: the card is printed", pid.encode("utf-8") in done.stdout, done.stdout[:300].decode("utf-8", errors="replace"))
    finally:
        cleanup(root)


def h_old() -> None:
    """H-old: a person's word recorded on the OLD text (`stage_overrides[].match`, a substring of the message) neither passes the
    new card silently nor throws: the old text is gone, so the question is asked again. `*` still passes (it always did)."""
    root = fx.project("qa-choice-old-")
    try:
        two_profiles(root)
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / fx.TICKET, "A")
        r.pipeline = {"stage_overrides": [{"stage": r.next_stage, "match": f"{OLD_TEXT} `tests` to prove that `api` write",
                                           "decision": "go on", "at": "2026-10-01T00:00:00"}]}
        turn(root, rehearsal=r)
        check_eq("H-old: the card is raised again on the new text", [f.get("why_empty") for f in r.findings], ["shared_root"])
        r.pipeline = {"stage_overrides": [{"stage": r.next_stage, "match": "*", "decision": "go on", "at": "2026-10-01T00:00:00"}]}
        r.findings.clear()
        turn(root, rehearsal=r)
        check_eq("H-old: a word that passes everything still does", r.findings, [])
    finally:
        cleanup(root)


def main() -> None:
    h_shared()
    h_nothing()
    h_empty()
    h_found()
    h_named()
    h_probe()
    h_encoding()
    h_old()
    finish("test_reporter_choice")


if __name__ == "__main__":
    main()
