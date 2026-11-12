"""OH3-27: the ONE reader of `profiles[].commands` (AR-13), and every site that asks it.

A project's own config carried `commands` as a LIST (the onboarding wrote it, OH3-26 now refuses it at the gate), and a dozen
readers each parsed the shape their own way: `readiness.py` raised an AttributeError, a string `argv` was read letter by
letter (a false "runnable"), and the one-key writers erased the other commands of a list. Keys:

  R-table      the whole table of the reader, one parameter per branch (the id names the branch)
  R-text       a problem names the sample file, and the sample file exists
  R-readiness  `check_execution_profile` / `profile_readiness` on the report's config, and `readiness.py --json` as a process
  R-string     a string `argv` is not a runnable command
  R-mine       `_command_from_profile` refuses with the problem; `_profile_argv` never raises, and a good precedent is kept
  R-sites      every other site: a list and a string `one_test` do not raise, each says its own thing on a problem
  R-proposal   `command_proposal` refuses a foreign shape and leaves the file alone
  R-census     no module outside the reader reads `commands` of a profile (AST, with a positive and a negative control)
"""
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

import harness
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project

sys.path.insert(0, str(harness.SCRIPTS))
import config_contract as C  # noqa: E402
import dependency_drift  # noqa: E402
import environment_record  # noqa: E402
import execution_request as er  # noqa: E402
import gate_preflight  # noqa: E402
import launch_check  # noqa: E402
import manual_capture  # noqa: E402
import onboarding_probe  # noqa: E402
import probe_by_code  # noqa: E402
import profile_contract as PC  # noqa: E402
import project_env  # noqa: E402
import readiness  # noqa: E402
import report_adapt  # noqa: E402

PY = sys.executable
DOOR = "references/profile-shape.json"
LIST_PROBLEM = f"commands is a list; expected an object keyed by command name, see {DOOR}"
# the repro of the report: a profile whose `commands` is a list
ASK = "I propose to run the tests as: `npx vitest run`. Do it? yes / no"
REPORT_PROFILE = {"profile_id": "x", "commands": [{"kind": "one_test", "argv": ["x"]}]}


def good_profile(pid="api", argv=None) -> dict:
    return {"profile_id": pid, "commands": {"one_test": {"kind": "test", "scope": "selected",
                                                         "argv": argv or ["pytest", "<test-file>"], "cwd": "."}}}


# --- R-table ----------------------------------------------------------------------------------------------------------

def r_table() -> None:
    def case(branch: str, got, expected) -> None:
        check_eq(f"R-table[{branch}]", got, expected)

    # profile_commands: absence is no problem, a foreign shape is named
    for branch, profile in (("profile-is-none", None), ("profile-is-string", "x"), ("profile-is-list", []),
                            ("profile-is-number", 5), ("no-commands-key", {"profile_id": "x"}),
                            ("commands-null", {"commands": None}), ("commands-empty-object", {"commands": {}})):
        case(f"commands/{branch}", PC.profile_commands(profile), ({}, ""))
    case("commands/object-is-returned", PC.profile_commands({"commands": {"run": {}}}), ({"run": {}}, ""))
    for branch, value, kind in (("list", [{"a": 1}], "a list"), ("empty-list", [], "a list"), ("string", "npx test", "a string"),
                                ("empty-string", "", "a string"), ("number", 5, "a number"), ("bool", True, "a boolean")):
        case(f"commands/{branch}", PC.profile_commands({"commands": value}),
             ({}, f"commands is {kind}; expected an object keyed by command name, see {DOOR}"))
    case("commands/list-problem-is-the-spec-sentence", PC.profile_commands(REPORT_PROFILE), ({}, LIST_PROBLEM))

    # profile_command: the one command of the object
    case("command/absent", PC.profile_command({"commands": {"run": {"argv": ["x"]}}}, "one_test"), ({}, ""))
    case("command/commands-absent", PC.profile_command({"profile_id": "x"}), ({}, ""))
    case("command/empty-object", PC.profile_command({"commands": {"one_test": {}}}), ({}, ""))
    case("command/present", PC.profile_command({"commands": {"one_test": {"argv": ["a"]}}}), ({"argv": ["a"]}, ""))
    case("command/named-by-the-caller", PC.profile_command({"commands": {"install": {"argv": ["i"]}}}, "install"), ({"argv": ["i"]}, ""))
    case("command/string", PC.profile_command({"commands": {"one_test": "npx"}}),
         ({}, f"commands.one_test is a string; expected an object {{argv, cwd, kind, scope}}, see {DOOR}"))
    for branch, value, kind in (("list", ["npx"], "a list"), ("number", 3, "a number"), ("bool", False, "a boolean")):
        case(f"command/{branch}", PC.profile_command({"commands": {"one_test": value}}),
             ({}, f"commands.one_test is {kind}; expected an object {{argv, cwd, kind, scope}}, see {DOOR}"))
    case("command/commands-list-is-the-commands-problem", PC.profile_command(REPORT_PROFILE), ({}, LIST_PROBLEM))

    # command_argv: the ONLY parsing of an argv
    case("argv/spec-none", PC.command_argv(None), ([], ""))
    case("argv/spec-empty", PC.command_argv({}), ([], ""))
    case("argv/key-absent", PC.command_argv({"cwd": "."}), ([], ""))
    case("argv/null", PC.command_argv({"argv": None}), ([], ""))
    case("argv/empty-list", PC.command_argv({"argv": []}), ([], ""))
    case("argv/words", PC.command_argv({"argv": ["npx", "vitest", "run"]}), (["npx", "vitest", "run"], ""))
    case("argv/tuple", PC.command_argv({"argv": ("a", "b")}), (["a", "b"], ""))
    case("argv/numbers-are-words", PC.command_argv({"argv": ["x", 5, 1.5]}), (["x", "5", "1.5"], ""))
    case("argv/empty-and-blank-words-dropped", PC.command_argv({"argv": ["x", "", "  ", "y"]}), (["x", "y"], ""))
    case("argv/string-is-never-read-by-letters", PC.command_argv({"argv": "npx test"}),
         ([], f"argv is a string; expected an array of words, see {DOOR}"))
    case("argv/object", PC.command_argv({"argv": {"a": 1}}), ([], f"argv is an object; expected an array of words, see {DOOR}"))
    case("argv/number", PC.command_argv({"argv": 7}), ([], f"argv is a number; expected an array of words, see {DOOR}"))
    for branch, junk, kind in (("bool", True, "a boolean"), ("object", {"a": 1}, "an object"), ("list", ["a"], "a list"),
                               ("null", None, "null")):
        case(f"argv/junk-{branch}-in-the-words", PC.command_argv({"argv": ["ok", junk]}),
             ([], f"argv holds {kind}; expected only words (strings), see {DOOR}"))
    case("argv/spec-is-a-string", PC.command_argv("npx"),
         ([], f"the command is a string; expected an object {{argv, cwd, kind, scope}}, see {DOOR}"))
    case("argv/spec-is-a-list", PC.command_argv(["npx"])[0], [])
    with_ph = {"argv": ["npx", "<test-file>", "--x", "<>"]}
    case("argv/placeholders-kept-by-default", PC.command_argv(with_ph), (["npx", "<test-file>", "--x", "<>"], ""))
    case("argv/placeholders-dropped-on-request", PC.command_argv(with_ph, drop_placeholders=True), (["npx", "--x"], ""))
    case("argv/only-placeholders-is-no-command", PC.command_argv({"argv": ["<a>", "<b>"]}, drop_placeholders=True), ([], ""))
    case("argv/a-lone-bracket-is-a-word", PC.command_argv({"argv": ["<", ">"]}, drop_placeholders=True), (["<", ">"], ""))

    # one_test_argv reads ONE command, `command_argv` reads the object it is handed
    other = {"commands": {"run": {"argv": ["r"]}, "install": {"argv": ["i"]}, "collect": {"argv": ["c"]}}}
    case("one_test_argv/does-not-read-run-install-collect", PC.one_test_argv(other), ([], ""))
    case("command_argv/reads-the-object-it-is-handed", [PC.command_argv(other["commands"][k])[0] for k in ("run", "install", "collect")],
         [["r"], ["i"], ["c"]])
    case("one_test_argv/words", PC.one_test_argv(good_profile(argv=["pytest", "<test-file>"])), (["pytest", "<test-file>"], ""))
    case("one_test_argv/placeholders-dropped", PC.one_test_argv(good_profile(), drop_placeholders=True), (["pytest"], ""))
    case("one_test_argv/commands-list", PC.one_test_argv(REPORT_PROFILE), ([], LIST_PROBLEM))
    case("one_test_argv/one-test-string", PC.one_test_argv({"commands": {"one_test": "x"}})[0], [])
    case("one_test_argv/argv-string-names-its-place", PC.one_test_argv({"commands": {"one_test": {"argv": "a b"}}}),
         ([], f"commands.one_test.argv is a string; expected an array of words, see {DOOR}"))

    # resolve_profile_command goes through the reader: a ValueError that says why, never an AttributeError
    roots = {"r": Path(tempfile.gettempdir())}
    report = Path(tempfile.gettempdir()) / "report.xml"
    for branch, profile, needle in (("commands-list", REPORT_PROFILE, "commands is a list"),
                                    ("absent-command", {"commands": {}}, "unknown profile command"),
                                    ("argv-string", {"commands": {"run": {"repo_id": "r", "argv": "npx test"}}}, "argv is a string"),
                                    ("command-is-a-string", {"commands": {"run": "x"}}, "unknown profile command")):
        try:
            PC.resolve_profile_command(profile, "run", roots, report)
            said = ""
        except ValueError as exc:
            said = str(exc)
        except Exception as exc:    # an AttributeError is the defect this key stands for
            said = f"RAISED {type(exc).__name__}"
        check_in(f"R-table[resolve/{branch}]", needle, said)
    resolved = PC.resolve_profile_command({"commands": {"run": {"repo_id": "r", "argv": ["a", "{report_path}"], "cwd": "."}}},
                                          "run", roots, report)
    check_eq("R-table[resolve/valid-form-unchanged]", resolved["argv"], ["a", str(report.resolve())])


# --- R-text -----------------------------------------------------------------------------------------------------------

def r_text() -> None:
    problems = [PC.profile_commands({"commands": []})[1], PC.profile_command({"commands": {"one_test": "x"}})[1],
                PC.command_argv({"argv": "x"})[1], PC.command_argv({"argv": [True]})[1], PC.command_argv("x")[1],
                PC.one_test_argv({"commands": {"one_test": {"argv": 3}}})[1]]
    check("R-text: every problem names the sample file", all(DOOR in p for p in problems), "\n".join(problems))
    check("R-text: and the sample file exists", (PLUGIN_ROOT / DOOR).is_file())
    check_eq("R-text: and the constant the reader prints is that path", PC.SHAPE_FILE, DOOR)
    check("R-text: no path of a machine in a problem (AR-4)", not any(":\\" in p or p.startswith("/") for p in problems))


# --- R-readiness, R-string --------------------------------------------------------------------------------------------

def r_readiness() -> None:
    broken = readiness.check_execution_profile({"profiles": [REPORT_PROFILE]})
    check_eq("R-readiness: the repro of the report - not_configured, no AttributeError", broken["status"], "not_configured")
    check_in("R-readiness: the note names the profile and the problem", f"profile x: {LIST_PROBLEM}", broken["note"])
    check("R-readiness: the remedy of old is kept", broken.get("remedy", {}).get("kind") == "human_step")
    mixed = readiness.check_execution_profile({"profiles": [REPORT_PROFILE, good_profile("api")]})
    check_eq("R-readiness: a healthy profile is not taken away by a broken one - ok", mixed["status"], "ok")
    check_in("R-readiness: the healthy one is named", "api", mixed["note"])
    check_in("R-readiness: and a healthy one does not hide the broken one", f"profile x: {LIST_PROBLEM}", mixed["note"])
    reversed_ = readiness.check_execution_profile({"profiles": [good_profile("api"), REPORT_PROFILE]})
    check_eq("R-readiness: the order of the rows changes nothing", reversed_["status"], "ok")
    clean = readiness.check_execution_profile({"profiles": [good_profile("api")]})
    check_eq("R-readiness: a valid form is as it was", (clean["status"], clean["note"]),
             ("ok", "execution profile(s) with a one-test command: api"))
    check_eq("R-readiness: only placeholders is no command, as before",
             readiness.check_execution_profile({"profiles": [good_profile("p", ["<a>"])]})["status"], "not_configured")
    check_eq("R-readiness: no profiles - the old words", readiness.check_execution_profile({"profiles": []})["status"], "not_configured")
    ready = {"profiles": [REPORT_PROFILE, {"profile_id": ["a", "list"], "commands": []}, "x", 5]}
    try:
        answers = PC.profile_readiness(ready)
        raised = ""
    except Exception as exc:
        answers, raised = {}, type(exc).__name__
    check_eq("R-readiness: profile_readiness on the report config (and a list as an id) does not raise", raised, "")
    gaps = answers.get("x", {}).get("gaps", [])
    check_eq("R-readiness: profiles[x] names the cause as a gap of `commands`",
             [(g.get("command"), g.get("status"), g.get("note")) for g in gaps], [("commands", "unavailable", LIST_PROBLEM)])
    check_eq("R-readiness: and the profile is unavailable, not ready", answers.get("x", {}).get("status"), "unavailable")
    check_eq("R-readiness: a row with a list as its id is not keyed", sorted(answers), ["x"])
    letters = PC.profile_readiness({"profiles": [{"profile_id": "s", "commands": {"run": {"kind": "run", "cwd": ".", "argv": "npx test"}}}]},
                                   root=Path(tempfile.gettempdir()))
    check_in("R-readiness: a string argv is a named gap, not the letters `n`, `p`, `x`",
             "argv is a string", [str(g.get("note")) for g in letters["s"]["gaps"]])

    # the process: `readiness.py --json` on a copy of a project that holds the report's profile
    root = temp_project("qa-profile-reader-")
    try:
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["profiles"] = [REPORT_PROFILE]
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        done = run_script("readiness.py", "--json", env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        try:
            data = json.loads(done.stdout)
        except ValueError:
            data = {}
        check_eq("R-readiness: readiness.py --json on the report config exits 0 (it exited 1 on an AttributeError)", done.returncode, 0)
        check("R-readiness: and prints JSON", bool(data), done.stderr[-400:])
        check_eq("R-readiness: whose execution_profile names the cause",
                 (data.get("execution_profile", {}).get("status"), LIST_PROBLEM in data.get("execution_profile", {}).get("note", "")),
                 ("not_configured", True))
        check_in("R-readiness: and whose profiles[x] does too", LIST_PROBLEM, json.dumps(data.get("profiles", {}).get("x", {})))
        check_in("R-readiness: and the contract lists its errors", "profiles[0].commands", json.dumps(data.get("profile_contract", {})))
    finally:
        cleanup(root)


def r_string() -> None:
    for branch, profile in (("string", {"profile_id": "s", "commands": {"one_test": {"argv": "npx test"}}}),
                            ("string-of-one-letter-words", {"profile_id": "s", "commands": {"one_test": {"argv": "n p x"}}})):
        got = readiness.check_execution_profile({"profiles": [profile]})
        check_eq(f"R-string[{branch}]: a string argv is not runnable", got["status"], "not_configured")
        check_in(f"R-string[{branch}]: and the note says why", "argv is a string", got["note"])
    check_eq("R-string: a one-test that is itself a string is not runnable either",
             readiness.check_execution_profile({"profiles": [{"profile_id": "s", "commands": {"one_test": "npx"}}]})["status"],
             "not_configured")


# --- R-mine -----------------------------------------------------------------------------------------------------------

PROVENANCE = {"profile_id": "api", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "localhost",
              "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
              "evidence_refs": ["probe"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact", "deployed_source_revision": "source-1"}}


def r_mine() -> None:
    for branch, profile in (("commands-list", REPORT_PROFILE), ("one-test-string", {"profile_id": "x", "commands": {"one_test": "npx"}}),
                            ("argv-string", {"profile_id": "x", "commands": {"one_test": {"argv": "npx test"}}})):
        try:
            words = er._profile_argv(profile)
            raised = ""
        except Exception as exc:
            words, raised = None, type(exc).__name__
        check_eq(f"R-mine[{branch}]: _profile_argv never raises or refuses (the precedent's comparison reads [] as 'not compared')",
                 (words, raised), ([], ""))
        try:
            er._command_from_profile(profile)
            said = ""
        except er.MineRefusal as exc:
            said = str(exc)
        except Exception as exc:
            said = f"RAISED {type(exc).__name__}"
        check_in(f"R-mine[{branch}]: _command_from_profile refuses with the problem", "profile x: ", said)
        check_in(f"R-mine[{branch}]: and keeps its door (the onboarding)", "`/qa-factory:qa-onboarding`", said)
        check_not_in(f"R-mine[{branch}]: and is not the 'no command' sentence", "has no commands.one_test.argv", said)
    try:
        er._command_from_profile({"profile_id": "x", "commands": {}})
        said = ""
    except er.MineRefusal as exc:
        said = str(exc)
    check_in("R-mine[commands-absent]: no command at all keeps its own sentence, word for word", "profile x has no commands.one_test.argv", said)
    check_eq("R-mine[valid]: a valid profile builds the command as before",
             er._command_from_profile(good_profile("a", ["pytest", "<test-file>"]))["argv"], ["pytest"])

    # a good precedent is NOT turned into a refusal by a profile in a foreign shape: it is copied and the note says so
    root = Path(tempfile.mkdtemp(prefix="qa-profile-reader-mine-")).resolve()
    try:
        (root / "fake").mkdir()
        (root / "fake" / "pytest").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (root / "probe.py").write_text("import json\nprint(json.dumps(" + repr(PROVENANCE) + "))\n", encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "conftest.py").write_text("# fixtures\n", encoding="utf-8")
        (root / "tests" / "test_a.py").write_text("def test_green():\n    pass\n", encoding="utf-8")
        task = "PREC-1"
        task_root = root / "qa-factory" / "artifacts" / task

        def write(path: Path, value) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=1), encoding="utf-8")

        def config(commands) -> dict:
            profile = {"profile_id": "api", "selected": True, "roots": {"test": "tests"}, "reporter": {"kind": "pytest"},
                       "selectors": {"verified": True}}
            if commands is not None:
                profile["commands"] = commands
            return {"profiles": [profile], "execution": {"runtime_probes": {"api": {"argv": [PY, str(root / "probe.py")], "cwd": ".",
                                                                                     "timeout_s": 20}}}}

        good = config({"one_test": {"argv": [PY, str(root / "fake" / "pytest"), "<test-file>"], "cwd": "."}})
        write(root / "qa-factory" / "config.json", good)
        write(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
        write(task_root / "state" / "controller.json", {
            "schema_version": "2", "revision": "41", "source_revision": "source-1",
            "dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "status": "running",
                                                "scope": ["TC-001"], "budget": {"requests": 150}}}})
        write(task_root / "work" / "automation-manifest.json",
              {"tests": [{"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"}]})

        def build(cfg) -> tuple:
            try:
                request, notes, _reuse, _verified = er.build_mine_request(root, ["TC-001"], task=task, cfg=cfg, again=True,
                                                                          probe=lambda spec: dict(PROVENANCE))
                return request, notes, ""
            except er.MineRefusal as exc:
                return None, [], str(exc)

        base, _notes, refusal = build(good)
        check_eq("R-mine[precedent]: the fixture builds from the profile alone", (bool(base), refusal), (True, ""))
        if base:
            request = json.loads(json.dumps(base))
            request["idempotency_key"] = "prec-old"
            request["command"] = {**request["command"], "argv": [PY, str(root / "fake" / "pytest")], "from_job": "job-old"}
            summary = root / "prec-summaries" / "job-old.json"
            write(summary, {"exit_code": 1, "execution_status": "failed",
                            "totals": {"tests": 2, "failures": 1, "errors": 0, "skipped": 0, "passed": 1}})
            store = er.JobStore(task_root / "state" / "execution-jobs")
            store.write({"job_id": "job-old", "idempotency_key": "prec-old", "request_digest": "d" * 64, "status": "completed",
                         "request": request, "created_at": "2026-09-30T04:00:01+00:00", "execution_status": "failed",
                         "summary": "prec-summaries/job-old.json"})
            for branch, commands in (("commands-list", [{"kind": "one_test", "argv": ["x"]}]),
                                     ("one-test-string", {"one_test": "npx"}), ("argv-string", {"one_test": {"argv": "npx test"}})):
                built, notes, refusal = build(config(commands))
                check_eq(f"R-mine[precedent/{branch}]: the precedent is copied, not refused",
                         (((built or {}).get("command") or {}).get("from_job"), refusal), ("job-old", ""))
                check_in(f"R-mine[precedent/{branch}]: and the note says the two were not compared",
                         "no readable commands.one_test.argv", notes)
    finally:
        cleanup(root)


# --- R-sites ----------------------------------------------------------------------------------------------------------

def never_raises(name: str, call) -> object:
    try:
        return call()
    except Exception as exc:
        check(f"R-sites: {name} does not raise", False, f"{type(exc).__name__}: {exc}")
        return None


def r_sites() -> None:
    string_one = {"profile_id": "x", "commands": {"one_test": "x"}}
    string_argv = {"profile_id": "x", "commands": {"one_test": {"argv": "npx test", "cwd": "."}}}
    root = temp_project("qa-profile-reader-sites-")
    try:
        shapes = (("commands-list", REPORT_PROFILE), ("one-test-string", string_one), ("argv-string", string_argv))
        for branch, profile in shapes:
            cfg = {"profiles": [profile]}
            check_eq(f"R-sites[{branch}]: report_adapt._argv", never_raises("report_adapt._argv", lambda: report_adapt._argv(profile)), [])
            check_eq(f"R-sites[{branch}]: environment_record._argv_of",
                     never_raises("environment_record._argv_of", lambda: environment_record._argv_of(cfg, "x")), [])
            check_eq(f"R-sites[{branch}]: onboarding_probe._one_test_argv",
                     never_raises("onboarding_probe._one_test_argv", lambda: onboarding_probe._one_test_argv(profile)), [])
            check_eq(f"R-sites[{branch}]: project_env._test_commands",
                     never_raises("project_env._test_commands", lambda: project_env._test_commands(profile)), [])
            check_eq(f"R-sites[{branch}]: dependency_drift._profile_install (the `install` command is not there)",
                     never_raises("dependency_drift._profile_install", lambda: dependency_drift._profile_install(profile)), None)
            check_eq(f"R-sites[{branch}]: probe_by_code._profile_cwd (a shape it cannot read names no directory)",
                     never_raises("probe_by_code._profile_cwd", lambda: probe_by_code._profile_cwd(cfg, "tests/a.py", "x")), ".")
            launched = never_raises("launch_check.probe", lambda: launch_check.probe(
                profile, root, config={}, run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("a probe must not start")),
                which=lambda *a, **k: None))
            check_eq(f"R-sites[{branch}]: launch_check.probe starts nothing and says it checked nothing",
                     (launched or {}).get("status"), "not_checked")
            try:
                manual_capture.harness_argv({"profiles": [dict(profile, profile_id="e2e-ui")]}, root)
                said = ""
            except ValueError as exc:
                said = str(exc)
            except Exception as exc:
                said = f"RAISED {type(exc).__name__}"
            check_in(f"R-sites[{branch}]: manual_capture.harness_argv refuses in words", "no test profile that fits a `ui` capture has a command that runs `pytest`", said)   # EP1-28: no profile id of any one project
        check_in("R-sites[commands-list]: manual_capture.harness_argv adds why the commands cannot be read",
                 LIST_PROBLEM, _harness_said(REPORT_PROFILE, root))
        check_eq("R-sites[valid]: manual_capture.harness_argv finds `pytest` in any command of the profile as before",
                 manual_capture.harness_argv({"profiles": [{"profile_id": "e2e-ui", "commands": {
                     "suite": {"argv": ["poetry", "run", "pytest", "tests"], "cwd": "e2e"}}}]}, root),
                 (["poetry", "run", "python"], root / "e2e"))
        check_eq("R-sites[valid]: dependency_drift._profile_install reads the `install` command as before",
                 dependency_drift._profile_install({"commands": {"install": {"argv": ["make", "deps"], "cwd": "b"}}}),
                 (["make", "deps"], "b"))
        check_eq("R-sites[valid]: project_env._test_commands lists the commands that start tests, in file order",
                 project_env._test_commands({"commands": {"one_test": {"kind": "test", "argv": ["a", 1], "cwd": "d"},
                                                          "install": {"kind": "setup", "argv": ["i"]},
                                                          "suite": {"kind": "collect", "argv": ["c"]}}}),
                 [("one_test", ["a", "1"], "d"), ("suite", ["c"], ".")])
        check_eq("R-sites[valid]: report_adapt._argv", report_adapt._argv(good_profile("g", ["a", " ", "b"])), ["a", "b"])
        check_eq("R-sites[valid]: environment_record._argv_of", environment_record._argv_of({"profiles": [good_profile("g", ["a", "b"])]}, "g"),
                 ["a", "b"])

        # onboarding_probe.probe_candidate: a foreign shape is named and not written over on the copy
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["profiles"] = [REPORT_PROFILE]
        before = json.dumps(cfg, sort_keys=True)
        answer = never_raises("onboarding_probe.probe_candidate", lambda: onboarding_probe.probe_candidate(
            root, "x", ["npx", "vitest", "run"], config=cfg))
        check_eq("R-sites[commands-list]: probe_candidate says not_checked", (answer or {}).get("state"), "not_checked")
        check_in("R-sites[commands-list]: with the problem", LIST_PROBLEM, (answer or {}).get("why", ""))
        check_eq("R-sites[commands-list]: and the config it was handed is as it was", json.dumps(cfg, sort_keys=True), before)

        # the gate rehearsal: a note, no probe, no finding
        task_root = root / "qa-factory" / "artifacts" / "T-1"
        task_root.mkdir(parents=True)
        for branch, profile in shapes:
            r = gate_preflight.Rehearsal(task_root, "A")
            r.config = {"profiles": [dict(profile, profile_id="web")]}
            r._keyed = {"web": {"cases": ["TC-1"], "keyed_on": "the root"}}
            r._automate = [("TC-1", {})]
            never_raises("Rehearsal.check_s5_executor", r.check_s5_executor)
            notes = [i["message"] for i in r.info if i["check"] == "s5_executor"]
            check_eq(f"R-sites[{branch}]: check_s5_executor asks no question about a launcher nobody could name", r.findings, [])
            check_in(f"R-sites[{branch}]: check_s5_executor says the shape problem in a note", "`web`: ", notes)
            r2 = gate_preflight.Rehearsal(task_root, "A")
            never_raises("Rehearsal._rehearse_reporter", lambda: r2._rehearse_reporter(
                "s5_reporter", "web", {"cases": ["TC-1"]}, dict(profile, profile_id="web"), root, None, 1, None))
            notes = [i["message"] for i in r2.info if i["check"] == "s5_reporter"]
            check_in(f"R-sites[{branch}]: _rehearse_reporter says the shape problem, not 'no commands.one_test.argv'", "so no run could prove", notes)
            check_not_in(f"R-sites[{branch}]: and does not call it a missing command", "no `commands.one_test.argv` in the profile", notes)
        r3 = gate_preflight.Rehearsal(task_root, "A")
        r3.config = {"profiles": [{"profile_id": "web", "commands": {}}]}
        r3._keyed = {"web": {"cases": ["TC-1"], "keyed_on": "the root"}}
        r3._automate = [("TC-1", {})]
        r3.check_s5_executor()
        check_eq("R-sites[commands-absent]: check_s5_executor on no command at all is as it was (no launcher to look for: no note, no finding)",
                 (r3.findings, [i for i in r3.info if i["check"] == "s5_executor"]), ([], []))
        r4 = gate_preflight.Rehearsal(task_root, "A")
        r4.config = {"profiles": [{"profile_id": "web", "commands": {"run": {"argv": [PY], "cwd": "."}}}]}
        r4._keyed = {"web": {"cases": ["TC-1"], "keyed_on": "the root"}}
        r4._automate = [("TC-1", {})]
        r4.check_s5_executor()
        check_eq("R-sites[run-fallback]: with no `one_test` the `run` command is probed, as before (the launcher is here: no finding)",
                 (r4.findings, [i for i in r4.info if i["check"] == "s5_executor"]), ([], []))
        r5 = gate_preflight.Rehearsal(task_root, "A")
        r5.config = {"profiles": [{"profile_id": "web", "commands": {"run": "x"}}]}
        r5._keyed = {"web": {"cases": ["TC-1"], "keyed_on": "the root"}}
        r5._automate = [("TC-1", {})]
        r5.check_s5_executor()
        check_in("R-sites[run-string]: a `run` that is not an object is named", "commands.run is a string",
                 [i["message"] for i in r5.info if i["check"] == "s5_executor"])
    finally:
        cleanup(root)
    run_shape_site()


def _harness_said(profile: dict, root: Path) -> str:
    try:
        manual_capture.harness_argv({"profiles": [dict(profile, profile_id="e2e-ui")]}, root)
    except ValueError as exc:
        return str(exc)
    return ""


def run_shape_site() -> None:
    """`probe_by_code.run_shape_checks` on a COMPILED test: a profile whose command cannot be read is a refusal (no words, no
    proof that the build is the one that rebuilds), never "no flag found"."""
    spec = probe_by_code.parse_detector_node("tests/CalcTests.cs::CalcTests.Adds", "tests/CalcTests.cs", "CalcTests.Adds")
    flag = spec["entry"]["no_rebuild_flags"][0]
    row = {"case": "TC-1", "file": "tests/CalcTests.cs", "selector": "CalcTests.Adds", "instance_id": "TC-1",
           "selector_args": ["--filter", "Adds"], "report_test_id": "CalcTests.Adds"}

    def shaped(commands) -> dict:
        return {"profiles": [{"profile_id": "dotnet", "roots": {"test": "tests"}, "selectors": {"verified": True},
                              **({} if commands is None else {"commands": commands})}]}

    def run(commands) -> str:
        try:
            probe_by_code.run_shape_checks(shaped(commands), {"tests": [row]}, "TC-1", row, spec, "TC-1", "", "class CalcTests {}")
            return "passed"
        except probe_by_code.Refusal as exc:
            return str(exc)
        except Exception as exc:
            return f"RAISED {type(exc).__name__}: {exc}"

    check_eq("R-sites[run_shape_checks/valid]: a command that builds passes", run({"one_test": {"argv": ["dotnet", "test"]}}), "passed")
    check_in("R-sites[run_shape_checks/valid]: a command that forbids a rebuild is refused as before", flag,
             run({"one_test": {"argv": ["dotnet", "test", flag]}}))
    for branch, commands in (("commands-list", [{"argv": ["dotnet", "test"]}]), ("one-test-string", {"one_test": "dotnet test"}),
                             ("argv-string", {"one_test": {"argv": f"dotnet test {flag}"}})):
        said = run(commands)
        check_in(f"R-sites[run_shape_checks/{branch}]: refused with the profile and the problem", "profile dotnet: ", said)
        check_in(f"R-sites[run_shape_checks/{branch}]: and nothing was changed", "Nothing was changed.", said)
    check_eq("R-sites[run_shape_checks/commands-absent]: no command at all is as it was (no flag to find)", run(None), "passed")


# --- R-proposal -------------------------------------------------------------------------------------------------------

def r_proposal() -> None:
    for branch, commands, needle in (("commands-list", [{"kind": "one_test", "argv": ["npx", "vitest", "run"]}], "commands is a list"),
                                     ("one-test-string", {"one_test": "npx vitest run", "suite": {"argv": ["s"]}}, "commands.one_test is a string"),
                                     ("commands-string", "npx vitest run", "commands is a string")):
        root = temp_project("qa-profile-reader-proposal-")
        try:
            path = root / "qa-factory" / "config.json"
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg["profiles"] = [{"profile_id": "web", "commands": commands}]
            path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            kept = path.read_bytes()
            try:
                C.command_proposal(root, {"profile_id": "web"}, ["npx", "vitest", "run", "--reporter=junit"], question=ASK)
                said = ""
            except ValueError as exc:
                said = str(exc)
            except Exception as exc:
                said = f"RAISED {type(exc).__name__}"
            check_in(f"R-proposal[{branch}]: refuses with the problem", needle, said)
            check_in(f"R-proposal[{branch}]: and the door (correct the profile first, by the sample)", f"correct the profile first, by `{DOOR}`", said)
            check_eq(f"R-proposal[{branch}]: the config is as it was, byte for byte", path.read_bytes(), kept)
            check_eq(f"R-proposal[{branch}]: _command_value reads no command of it", C._command_value(cfg, {"target": {"profile_id": "web"}}), None)
        finally:
            cleanup(root)
    root = temp_project("qa-profile-reader-proposal-")
    try:
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["profiles"] = [{"profile_id": "web"}, {"profile_id": "api", "commands": {"suite": {"argv": ["s"]}}}]
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        proposal = C.command_proposal(root, {"profile_id": "web"}, ["npx", "vitest", "run"], question=ASK)
        check_eq("R-proposal[commands-absent]: a profile with no commands gets the one key, as before",
                 proposal["proposed_config"]["profiles"][0]["commands"], {"one_test": {"argv": ["npx", "vitest", "run"]}})
        proposal = C.command_proposal(root, {"profile_id": "api"}, ["npx", "vitest", "run"], question=ASK)
        check_eq("R-proposal[valid]: the other commands of the profile are kept, the one key is set",
                 proposal["proposed_config"]["profiles"][1]["commands"],
                 {"suite": {"argv": ["s"]}, "one_test": {"argv": ["npx", "vitest", "run"]}})
        check_eq("R-proposal[valid]: _command_value reads the argv of a good profile",
                 C._command_value({"profiles": [good_profile("g", ["a"])]}, {"target": {"profile_id": "g"}}), ["a"])
        check_eq("R-proposal[profiles-not-a-list]: _profile_slot holds none", C._profile_slot({"profiles": "x"}, "x"), (None, None))
        # a config already on disk may hold `profiles` as a number or a boolean: no profile, no argv, never a raise
        import environment_record as ER
        import manual_capture as MC
        for held in (5, True, "x", [1]):
            check_eq(f"R-proposal[profiles={held!r}]: environment_record._argv_of holds no argv",
                     ER._argv_of({"profiles": held}, "api"), [])
            try:
                MC.harness_argv({"profiles": held}, Path(root))
                check(f"R-proposal[profiles={held!r}]: harness_argv refuses", False)
            except ValueError as exc:
                check_in(f"R-proposal[profiles={held!r}]: harness_argv refuses by its own sentence", "no test profile that fits a `ui` capture", str(exc))
    finally:
        cleanup(root)


# --- R-census ---------------------------------------------------------------------------------------------------------

def commands_reads(source: str) -> list:
    """`[(function, line)]` of every read of a key `"commands"` in `source`: `<x>.get("commands"[, default])` and `<x>["commands"]`,
    in any quotes, in whichever context (a write over the key is a read of the shape too: it is where a foreign one was erased)."""
    found = []

    def walk(node, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = child.name if scope == "<module>" else f"{scope}.{child.name}"
            call = (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "get"
                    and bool(child.args) and isinstance(child.args[0], ast.Constant) and child.args[0].value == "commands")
            sub = isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant) and child.slice.value == "commands"
            if call or sub:
                found.append((scope, child.lineno))
            walk(child, name)

    walk(ast.parse(source), "<module>")
    return found


# (file, function) -> what the `commands` it reads IS. Not line numbers: another change to the file moves them. The list only
# SHRINKS: an entry whose read is gone fails the key until the entry is deleted, and a new read has no entry to hide in.
CENSUS_EXEMPT = {
    ("profile_contract.py", "profile_commands"): "the reader itself",
    ("profile_contract.py", "validate_profile"): "the validator of the shape (OH3-26)",
    ("config_contract.py", "migration_plan"): "external_writes.commands (a channel table), not a profile",
    ("config_contract.py", "command_proposal"): "the writer of one key: creates an absent `commands` after profile_command found no foreign shape",
    ("onboarding_probe.py", "probe_candidate"): "a writer on the in-memory copy, after profile_command found no foreign shape",
    ("environment_preparation.py", "execute_environment"): "the commands of an environment plan, not a profile",
    ("external_writes.py", "command_for"): "external_writes.commands, not a profile",
    ("guard_pre_tool.py", "_declared_write_commands"): "external_writes.commands, not a profile",
    ("install_smoke.py", "main"): "external_writes.commands, not a profile",
    ("tracker_write.py", "fingerprint"): "external_writes.commands, not a profile",
    ("role_cli.py", "registry"): "the role-commands registry, not a profile",
}


def r_census() -> None:
    scripts = harness.SCRIPTS
    seen = {}
    for path in sorted(scripts.glob("*.py")):
        for function, _line in commands_reads(path.read_text(encoding="utf-8")):
            seen.setdefault((path.name, function), 0)
            seen[(path.name, function)] += 1
    check("R-census: positive control - the census finds the reader itself and a known writer",
          ("profile_contract.py", "profile_commands") in seen and ("config_contract.py", "command_proposal") in seen, str(sorted(seen)))
    strangers = sorted(set(seen) - set(CENSUS_EXEMPT))
    check_eq("R-census: no module outside the reader reads `commands` of a profile (a new read: ask profile_contract.profile_command)",
             strangers, [])
    stale = sorted(set(CENSUS_EXEMPT) - set(seen))
    check_eq("R-census: no exemption outlives its read (the list only shrinks)", stale, [])
    check_eq("R-census: inside profile_contract.py only the reader and the validator are exempt",
             sorted(name for (file, name) in CENSUS_EXEMPT if file == "profile_contract.py"), ["profile_commands", "validate_profile"])
    # the negative control: a reader planted in each spelling is found, in the function it sits in
    planted = ("def reader(profile):\n    return (profile.get('commands', {})).get('one_test')\n"
               "def second(profile):\n    return profile[\"commands\"]\n"
               "def third(profile):\n    return profile.get(\n        'commands')\n"
               "def fourth(profile):\n    commands = {}\n    return commands.items()\n"
               "class K:\n    def fifth(self, p):\n        return p.get(\"commands\", None)\n")
    check_eq("R-census: negative control - a planted reader (`.get('commands', {})`, a subscript, a wrapped call, a method) is found",
             sorted({f for f, _ in commands_reads(planted)}), ["K.fifth", "reader", "second", "third"])
    check_eq("R-census: and `commands.items()` on a local name is not a read of a profile", commands_reads("def f():\n    commands = {}\n    return commands.items()\n"), [])
    # the mutation the key stands for, run on the real file: one new read in report_adapt is a stranger
    mutated = (scripts / "report_adapt.py").read_text(encoding="utf-8") + "\n\ndef planted(profile):\n    return profile.get(\"commands\")\n"
    check_eq("R-census: a read added to report_adapt.py is not exempt", [f for f, _ in commands_reads(mutated)
                                                                         if ("report_adapt.py", f) not in CENSUS_EXEMPT], ["planted"])


def main() -> None:
    r_table()
    r_text()
    r_readiness()
    r_string()
    r_mine()
    r_sites()
    r_proposal()
    r_census()
    finish("test_profile_reader")


if __name__ == "__main__":
    main()
