#!/usr/bin/env python3
"""B-014: one package generation per run.

The driver loads ONE copy of the package (`--plugin-dir`), and a project may enable another one; nothing
recorded which generation's hooks ran under a role, so a role could be judged by the guards of one version
and told its rules by another. What is proved here, nothing of it reaching a network or a model (`claude`
is the stub of `story_run_common.py`, which writes the receipt a real SessionStart hook writes):

  R  the receipt: `telemetry_hook.py` upserts `package-<hash>.json` per session - two roots kept, one root
     deduped, no fingerprint, fail-silent, and nothing for a project that is not enabled;
  D  the driver's check after a session: a match is recorded once and checking stops; a mismatch, a second
     root and a MISSING receipt (AT one session, BEYOND it, and no session id = nothing to check) raise
     Person("package") before anything is bound or finished, the saved result is set aside as `.mixed.json`;
     the text obeys the human-text rules (versions only), the person's word is recorded (FR-4) and the same
     root pair then passes once, silently after that, while another pair asks again;
  E  `CLAUDE_PLUGIN_ROOT` and the run mode are in the child environment, and a role's Bash sees the
     driver's own root even when the parent's environment holds another one (step 0, R6b);
  P  absolute script paths in the brief card and in the prompt - no `${` in text nobody expands;
  M  the run mode: stamped once by `story_step start`, a switch refused with its door, passed on the
     person's word per stage, a story with no stamp adopts the current mode; the driver asks the same at the
     start of a run and records the answer by code.
"""
import contextlib
import io
import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402

TASK = "QA-14"
START_CWD = os.getcwd()
VERSION = json.loads((harness.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
OTHER_VERSION = "0.0.1-other"
DISPATCH = "S1-qa-scout-1"

# What a role's Bash tool is: a child of `claude -p`, so a child of this stub, with the stub's environment.
ENV_STUB = T.RECEIPT + r'''
import json, os, subprocess, sys
from pathlib import Path
sys.stdin.buffer.read()
probe = subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('CLAUDE_PLUGIN_ROOT') or '')"],
                       capture_output=True, text=True, env=os.environ.copy())
Path(os.environ["STUB_ENV_OUT"]).write_text(json.dumps(
    {"bash_sees": probe.stdout.strip(), "mode": os.environ.get("QA_FACTORY_RUN_MODE")}), encoding="utf-8")
write_receipt("sess-env")
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-env",
                  "num_turns": 2, "total_cost_usd": 0.0, "duration_ms": 1, "result": "done"}))
'''


def done(root):
    os.chdir(START_CWD)
    harness.cleanup(root)


def scenario(fn):
    try:
        fn()
    except Exception:  # a scenario that cannot even run is a red result, not a crash of the others
        check(f"{fn.__name__} ran to its end", False, traceback.format_exc()[-1800:])
        os.chdir(START_CWD)


def project(task=TASK, receipt=None):
    """A seeded project (S0 done, controller initialized), the stub that writes receipts, and a Driver."""
    root, task_root, env = T.seed(task)
    T.set_control(root, {"receipt": receipt} if receipt is not None else {})
    return root, task_root, env, T.driver_for(root, env, task)


def other_root(root):
    return str(root / "another-copy")


def foreign(root, version=OTHER_VERSION):
    return [{"plugin_root": other_root(root), "version": version, "first_hook": "SessionStart:session_env.py"}]


def call(driver, task_root, dispatch=DISPATCH, **kwargs):
    prompt = f"You are qa-scout. Dispatch: {dispatch}.\nArtifacts dir: {task_root}\nDo the work."
    return driver.run_claude("role", prompt, role="qa-scout", dispatch=dispatch, stage="S1", **kwargs)


def person_of(driver, task_root, **kwargs):
    import story_run
    try:
        return None, call(driver, task_root, **kwargs)
    except story_run.Person as person:
        return person, None


def journal(root):
    return T.jsonl(root / "qa-factory" / "records" / "journal.jsonl")


def receipt_dir(root):
    return root / "qa-factory" / "state" / "host-receipts"


def problems_of(text):
    """The rules a text breaks as a person sees it: `ask()` puts the answer block under every question, and
    the check wants one (`no_how_to_answer`), so a body checked on its own gets the same block."""
    import human_text
    if "\nAnswer:" not in text:
        text += "\n\n---\nAnswer: write your words to a file and run\n  python story_run.py --task T --answer <file>"
    return [p["rule"] for p in human_text.problems(text)]


# --- R: the receipt ------------------------------------------------------------------------------
def r_the_receipt():
    import hashlib
    root = harness.temp_project("qa-pkg-r-")
    noop = root / "noop_hook.py"
    noop.write_text("pass\n", encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    session = "session-r-1"
    event = json.dumps({"session_id": session, "hook_event_name": "SessionStart", "cwd": str(root)})
    hook = harness.SCRIPTS / "telemetry_hook.py"
    import subprocess

    def fire(text=event, project_env=env):
        return subprocess.run([sys.executable, "-B", str(hook), str(noop)], input=text, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=project_env, cwd=str(root))

    try:
        done_run = fire()
        check_eq("R1 the real hook wrapper runs the hook it wraps", done_run.returncode, 0)
        path = receipt_dir(root) / f"package-{hashlib.sha256(session.encode('utf-8')).hexdigest()[:16]}.json"
        check("R1 a receipt named by the hash of the session is written", path.is_file(), str(list(receipt_dir(root).glob('*'))))
        receipt = json.loads(path.read_text(encoding="utf-8"))
        check_eq("R1 its keys are the session, the roots and the time - no fingerprint",
                 sorted(receipt), ["observed_at", "roots", "session_id"])
        check_eq("R1 the session id is the event's", receipt["session_id"], session)
        row = receipt["roots"][0]
        check_eq("R1 a root's keys", sorted(row), ["first_hook", "plugin_root", "version"])
        check_eq("R1 the root is the copy that ran (its own resolved directory)", row["plugin_root"],
                 str(harness.PLUGIN_ROOT.resolve()))
        check_eq("R1 the version is that copy's manifest", row["version"], VERSION)
        check_in("R1 the first hook is named with its event", "SessionStart:noop_hook.py", row["first_hook"])
        fire()
        check_eq("R2 the same root again is deduped", len(json.loads(path.read_text(encoding="utf-8"))["roots"]), 1)

        # A second copy: the module's own location is what names the root, so a copy is a module whose
        # __file__ lies in another tree. Its manifest carries its own version.
        copy = harness.temp_dir("qa-pkg-copy-")
        (copy / "scripts").mkdir()
        (copy / ".claude-plugin").mkdir()
        (copy / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9+build"}), encoding="utf-8")
        import telemetry_hook
        real = telemetry_hook.__file__
        telemetry_hook.__file__ = str(copy / "scripts" / "telemetry_hook.py")
        try:
            telemetry_hook._write_package_receipt(root, json.loads(event), "other_hook.py")
            telemetry_hook._write_package_receipt(root, json.loads(event), "other_hook.py")
        finally:
            telemetry_hook.__file__ = real
        roots = json.loads(path.read_text(encoding="utf-8"))["roots"]
        check_eq("R3 a different root joins the first: two kept, the second one once", len(roots), 2)
        check_eq("R3 its version is its own manifest's (build suffix dropped)",
                 sorted(r["version"] for r in roots), sorted([VERSION, "9.9.9"]))
        harness.cleanup(copy)

        fire(json.dumps({"hook_event_name": "SessionStart", "cwd": str(root)}))
        check_eq("R4 an event with no session id writes no receipt for it", len(list(receipt_dir(root).glob("package-*.json"))), 1)
        cold = harness.temp_dir("qa-pkg-cold-")     # not a factory project: no qa-factory/config.json
        fire(project_env=dict(env, CLAUDE_PROJECT_DIR=str(cold)))
        check("R5 a project that is not enabled gets nothing", not (cold / "qa-factory").exists(), str(list(cold.rglob("*"))))
        harness.cleanup(cold)

        # fail-silent: the receipt directory is a FILE, so nothing can be written there
        blocked = harness.temp_project("qa-pkg-blocked-")
        (blocked / "qa-factory" / "state" / "host-receipts").write_text("in the way", encoding="utf-8")
        result = fire(project_env=dict(env, CLAUDE_PROJECT_DIR=str(blocked)))
        check_eq("R6 a receipt that cannot be written never fails the hook", result.returncode, 0)
        harness.cleanup(blocked)
    finally:
        harness.cleanup(root)


# --- D: the driver's check ---------------------------------------------------------------------------
def d_a_match_is_recorded_and_checking_stops():
    root, task_root, env, driver = project()
    try:
        person, result = person_of(driver, task_root)
        check("D1 a session whose hooks ran from the driver's own root is accepted", person is None and result is not None,
              str(getattr(person, "text", "")))
        record = driver.state.get("package_check") or {}
        check_eq("D1 recorded ok, with the driver's root, its version and the session",
                 (record.get("ok"), record.get("root"), record.get("version"), record.get("session")),
                 (True, str(driver.plugin), VERSION, "sess-" + DISPATCH))
        check("D1 this process has its verdict", driver.package_verdict is True)
        T.set_control(root, {"receipt": "none"})
        person, result = person_of(driver, task_root, )
        check("D2 after the verdict nothing is checked again (one generation per run): a session with no receipt passes",
              person is None and result is not None)
        check_eq("D2 the receipt file really is absent for it", len(list(receipt_dir(root).glob("package-*.json"))), 1)
    finally:
        done(root)


def d_a_mismatch_stops_before_anything_is_accepted():
    root, task_root, env, driver = project(receipt=None)
    T.set_control(root, {"receipt": foreign(root)})
    try:
        saved = task_root / "state" / "driver-runs" / f"{DISPATCH}.json"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"session_id": "sess-old", "result": "an answer of an earlier session"}), encoding="utf-8")
        person, result = person_of(driver, task_root)
        check("D3 another root raises a question for the person", person is not None and result is None)
        if person is None:
            return
        check_eq("D3 of kind package, with the stage and the dispatch", (person.kind, person.stage, person.dispatch),
                 ("package", "S1", DISPATCH))
        check("D3 the saved result is set aside as .mixed.json, and no result of that name is left",
              saved.with_name(f"{DISPATCH}.mixed.json").is_file() and not saved.exists())
        check_eq("D3 the mixed file is the result that was there",
                 json.loads(saved.with_name(f"{DISPATCH}.mixed.json").read_text(encoding="utf-8"))["session_id"], "sess-old")
        check_in("D3 the text names the driver's version", VERSION, person.text)
        check_in("D3 and the other copy's version", OTHER_VERSION, person.text)
        for word in ("another-copy", str(driver.plugin), "--plugin-dir", "package-", ".json", DISPATCH):
            check_not_in(f"D3 FR-6: the text carries no `{word}`", word, person.text)
        check_eq("D3 FR-6: the text obeys the human-text rules", problems_of(person.text), [])
        for answer in ("`retry`", "`go on`", "`stop`"):
            check_in(f"D3 the three answers, as closed tokens: {answer}", answer, person.text)
        check_in("D3 the wording says what was accepted (what the role wrote stays)", "was accepted (what the role wrote stays)", person.text)
        check_not_in("D3 and no longer says nothing was recorded", "was recorded and", person.text)
        check_in("D3 paths and the way to fix it are in the details", other_root(root), person.details)
        check_in("D3 the details name the door", "claude plugin disable", person.details)
        check_eq("D3 the driver keeps what it needs to record the answer",
                 sorted(driver.state["package_question"]),
                 ["details", "driver_root", "hook_roots", "session", "text", "what"])
        check("D3 the mismatched session was NOT stored as the dispatch's session", DISPATCH not in driver.state["sessions"])
        check("D3 and the process has no verdict", driver.package_verdict is False)
        check_eq("D3 the call is journalled as any call is", len(T.jsonl(task_root / "state/driver-runs.jsonl")), 1)

        # A fresh driver with nothing saved: a mismatch on a call that has no saved result renames nothing.
        T.set_control(root, {"receipt": foreign(root)})
        again = T.driver_for(root, env, TASK)
        person, _ = person_of(again, task_root, dispatch="S1-qa-scout-2")
        check("D4 no saved result: the question is raised all the same", person is not None)
        check("D4 and no .mixed.json is invented", not list((task_root / "state" / "driver-runs").glob("S1-qa-scout-2*")))
        check("D4 (checked with a positive control) the earlier one is still there",
              bool(list((task_root / "state" / "driver-runs").glob(f"{DISPATCH}.mixed.json"))))

        # Two roots in one session - the driver's own and another - is the mixed case too.
        both = [{"plugin_root": str(driver.plugin), "version": VERSION, "first_hook": "SessionStart:a.py"}] + foreign(root)
        T.set_control(root, {"receipt": both})
        third = T.driver_for(root, env, TASK)
        person, _ = person_of(third, task_root, dispatch="S1-qa-scout-3")
        check("D5 the driver's root PLUS another one is a mismatch", person is not None)
        check_in("D5 the text says more than one copy", "more than one copy", getattr(person, "text", ""))
        check_eq("D5 and it is still plain words", problems_of(getattr(person, "text", "")), [])

        # The same version at another place is different too, and says so without a path.
        T.set_control(root, {"receipt": foreign(root, VERSION)})
        fourth = T.driver_for(root, env, TASK)
        person, _ = person_of(fourth, task_root, dispatch="S1-qa-scout-4")
        check_in("D6 the same version elsewhere: named as another copy of the same version",
                 "another copy of the same version", getattr(person, "text", ""))
        T.set_control(root, {"receipt": [{"plugin_root": other_root(root), "first_hook": "x"}]})
        fifth = T.driver_for(root, env, TASK)
        person, _ = person_of(fifth, task_root, dispatch="S1-qa-scout-5")
        check_in("D6 a root with no version: 'another copy', no version invented", "another copy.", getattr(person, "text", ""))
    finally:
        done(root)


def d_a_mismatch_reaches_no_finish():
    """The mismatch is raised inside run_claude, before run_role binds, hands the answer to the handoff
    check or finishes the dispatch: none of that happens for a mixed session."""
    import story_run
    root, task_root, env, driver = project()
    T.set_control(root, {"receipt": foreign(root), "roles": {"qa-scout": {"result": T.SCOUT_DIGEST.replace("{task}", TASK)}}})
    seen = []
    real_py = driver.py

    def spy_py(script, *args, **kwargs):
        seen.append((script, args[0] if args else ""))
        return real_py(script, *args, **kwargs)

    driver.py = spy_py
    driver.handoff = lambda *a, **k: seen.append(("handoff", "")) or ""
    driver.finish = lambda *a, **k: seen.append(("finish", "")) or ("", {})
    try:
        try:
            driver.run_role("S1", "qa-scout")
            raised = None
        except story_run.Person as person:
            raised = person
        check("D7 run_role raises the package question", raised is not None and raised.kind == "package",
              str(seen))
        called = [name for name, _ in seen]
        check("D7 the dispatch was registered (start ran)", ("story_step.py", "start") in seen, str(seen))
        check("D7 bind was not run", ("story_step.py", "bind") not in seen, str(seen))
        check("D7 the handoff check was not reached", "handoff" not in called, str(seen))
        check("D7 finish was not called", "finish" not in called and ("story_step.py", "finish") not in seen, str(seen))
        check("D7 no result of that session is saved for the dispatch",
              not list((task_root / "state" / "driver-runs").glob("S1-qa-scout-1*.json")))
    finally:
        done(root)


def d_a_missing_receipt_is_a_mismatch_at_the_first_session():
    root, task_root, env, driver = project()
    T.set_control(root, {"receipt": "none"})
    try:
        person, result = person_of(driver, task_root)
        check("D8 AT the limit: ONE session with no receipt is a mismatch (SessionStart fires in `claude -p`)",
              person is not None and result is None)
        check_in("D8 the text says the checks did not report", "did not report", getattr(person, "text", ""))
        check_eq("D8 and stays in plain words", problems_of(getattr(person, "text", "")), [])
        check_eq("D8 the question keeps an empty root list", driver.state["package_question"]["hook_roots"], [])
        # BEYOND: the second session with no receipt is no more forgiven than the first
        again = T.driver_for(root, env, TASK)
        person, _ = person_of(again, task_root, dispatch="S1-qa-scout-2")
        check("D9 BEYOND the limit: a second session with no receipt asks again", person is not None)
        # and the boundary on the other side: no session id, no session to look up
        unnamed = T.driver_for(root, env, TASK)
        unnamed.package_check("", stage="S1", dispatch=DISPATCH)
        check("D10 a call that returned no session id has nothing to check (no question)", unnamed.package_verdict is False)
    finally:
        done(root)


def d_the_persons_word_passes_that_pair_once():
    import story_run
    root, task_root, env, driver = project()
    T.set_control(root, {"receipt": foreign(root)})
    try:
        person, _ = person_of(driver, task_root)
        check("D11 setup: the mismatch is raised", person is not None)
        driver.ask(person)
        shown = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_eq("D11 the question as shown obeys the human-text rules", problems_of(shown), [])
        check_in("D11 it names the file with the factory's own words", "driver-question-details.md", shown)
        answer = root / "answer.md"
        answer.write_text("Go on.", encoding="utf-8")
        driver.take_answer(answer)
        passed = driver.state.get("package_pass") or {}
        check_eq("D12 the pass is recorded: root pair, words, time",
                 (sorted(passed), passed.get("words"), passed.get("driver_root"), len(passed.get("hook_roots") or [])),
                 (["driver_root", "hook_roots", "ts", "words"], "Go on.",
                  driver._root_key(driver.plugin), 1))
        events = journal(root)
        answers = [e for e in events if e.get("event") == "human_answer" and "package" in str(e.get("notes"))]
        check_in("D12 the person's words are journalled (human_answer)", "Go on.",
                 " ".join(str(e.get("notes")) for e in answers))
        finding = [e for e in events if e.get("event") == "defect_found"]
        check_eq("D12 and the mismatch is filed as a finding of ours against the dispatch (FR-4)",
                 [(e.get("ref"), "owner: factory" in str(e.get("notes"))) for e in finding], [(DISPATCH, True)])
        check("D12 the question is closed", not (driver.state.get("asked") or {}).get("kind"))

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            person2, result2 = person_of(driver, task_root)
        check("D13 the same pair then passes: the step runs on", person2 is None and result2 is not None)
        check_eq("D13 the pass is printed once, on the call it covered",
                 buffer.getvalue().count("passed on the person's word"), 1)
        check("D13 and recorded as passed by the person", (driver.state["package_check"] or {}).get("passed_by_person") is True)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            person3, _ = person_of(driver, task_root, dispatch="S1-qa-scout-2")
        check("D14 afterwards it is silent", person3 is None and "passed on the person's word" not in buffer.getvalue())

        # The pass is the person's word about ONE pair of roots: it survives the process (state file) ...
        fresh = T.driver_for(root, env, TASK)
        check_eq("D15 the pass survives the process (state file)", bool(fresh.state.get("package_pass")), True)
        fresh_person, fresh_result = person_of(fresh, task_root, dispatch="S1-qa-scout-3")
        check("D15 ... and covers that same pair in the next process", fresh_person is None and fresh_result is not None)
        # ... and a different pair is a different question.
        other = harness.temp_dir("qa-pkg-copy-")
        T.set_control(root, {"receipt": [{"plugin_root": str(other), "version": OTHER_VERSION, "first_hook": "x"}]})
        elsewhere = T.driver_for(root, env, TASK)
        elsewhere_person, _ = person_of(elsewhere, task_root, dispatch="S1-qa-scout-4")
        check("D15 the pass is keyed on the pair: the same driver, another hook root, asks", elsewhere_person is not None)
        harness.cleanup(other)

        # an empty answer is today's stop, not a pass
        driver.ask(story_run.Person("package", "A question.", "S1", DISPATCH))
        empty = root / "empty.md"
        empty.write_text("  \n", encoding="utf-8")
        try:
            driver.take_answer(empty)
            stopped = ""
        except story_run.Stop as stop:
            stopped = stop.reason
        check_in("D16 an empty package answer is the empty-answer stop", "is empty", stopped)
    finally:
        done(root)


def d_the_real_hook_and_the_driver_agree():
    """The stub writes the receipt by hand; here the REAL hook writes it, and the driver reads that."""
    import subprocess
    root, task_root, env, driver = project()
    try:
        session = "sess-real-hook"
        noop = root / "noop_hook.py"
        noop.write_text("pass\n", encoding="utf-8")
        subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "telemetry_hook.py"), str(noop)],
                       input=json.dumps({"session_id": session, "hook_event_name": "SessionStart"}), text=True,
                       capture_output=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)), cwd=str(root))
        driver.package_check(session, stage="S1", dispatch=DISPATCH)
        check("D17 a receipt written by the real hook satisfies the driver's check", driver.package_verdict is True)
        check_eq("D17 it recorded the version the real hook read", driver.state["package_check"]["version"], VERSION)
    finally:
        done(root)


def d_dry_run_checks_nothing():
    root, task_root, env, _ = project()
    try:
        driver = T.driver_for(root, env, TASK, dry_run=True)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = driver.describe()
        check_eq("D18 a dry run describes and exits", code, 0)
        check("D18 and never asked for a package verdict", "package_check" not in driver.state and not driver.package_verdict)
    finally:
        done(root)


# --- E: the child environment ---------------------------------------------------------------------------
def e_a_roles_bash_sees_the_drivers_root():
    root, task_root, env = T.seed(TASK)
    (root / "env_claude.py").write_text(ENV_STUB, encoding="utf-8")
    out = root / "env-seen.json"
    saved = {key: os.environ.get(key) for key in ("CLAUDE_PLUGIN_ROOT", "STUB_ENV_OUT", "QA_FACTORY_RUN_MODE")}
    try:
        # the parent (a desktop host, another session) holds ANOTHER root: R6b of step 0 showed a Bash tool inherits it
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(root / "the-parents-root")
        os.environ["STUB_ENV_OUT"] = str(out)
        os.environ.pop("QA_FACTORY_RUN_MODE", None)
        env["STORY_RUN_CLAUDE"] = str(root / "env_claude.py")
        driver = T.driver_for(root, env, TASK)
        check_eq("E1 the driver's own environment names its own root", driver.env["CLAUDE_PLUGIN_ROOT"], str(driver.plugin))
        check_eq("E1 ... and the `claude -p` child's too (after the infra removal list)",
                 driver.claude_env["CLAUDE_PLUGIN_ROOT"], str(driver.plugin))
        check_eq("E1 the run mode is `driver`", driver.claude_env["QA_FACTORY_RUN_MODE"], "driver")
        import infra_failure
        listed = json.dumps(infra_failure.rules()[0].get("child_env"))
        check_not_in("E1 (control) the removal list of driver-infra.json does not name CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", listed)
        check_in("E1 (positive control of that search) it does name a variable it removes", "ANTHROPIC_BASE_URL", listed)
        call(driver, task_root)
        seen = json.loads(out.read_text(encoding="utf-8"))
        check_eq("E2 a role's Bash sees the DRIVER's root, not the parent's", seen["bash_sees"], str(driver.plugin))
        check_eq("E2 and the run mode", seen["mode"], "driver")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        done(root)


# --- P: absolute paths in text nobody expands ------------------------------------------------------------
def p_absolute_script_paths():
    import brief_pack
    import story_step
    root, task_root, env, driver = project()
    try:
        here = Path(brief_pack.__file__).resolve().parent.as_posix()
        check_eq("P1 the brief's script root is this copy's own scripts directory", brief_pack.SCRIPTS, here)
        driver.step("start", "--task", TASK, "--stage", "S1", "--role", "qa-scout")
        brief = (task_root / "work" / "briefs" / DISPATCH).with_suffix(".md")
        text = brief.read_text(encoding="utf-8")
        check_in("P2 the brief card names the command with an absolute path", f'python "{here}/<script>"', text)
        check_not_in("P2 and carries no `${` anywhere", "${", text)
        prompt = story_step._prompt(TASK, {"inputs": []}, "qa-scout", DISPATCH, [], "", "qa-factory/x.yaml")
        check_in("P3 the prompt's handover line runs this copy's checker by absolute path",
                 f'python "{here}/handoff_check.py"', prompt)
        check_not_in("P3 and carries no `${`", "${", prompt)
    finally:
        done(root)


def p_agents_name_the_plugin_root():
    agents = harness.PLUGIN_ROOT / "agents"
    runner = (agents / "qa-runner.md").read_text(encoding="utf-8")
    check_in("P4 qa-runner runs manual_evidence.py like its other commands",
             'python "${CLAUDE_PLUGIN_ROOT}/scripts/manual_evidence.py" validate', runner)
    check_not_in("P4 and no relative `python scripts/` command is left in it", "python scripts/", runner)
    check_in("P5 the retro analyst names the numbers script through the root", "${CLAUDE_PLUGIN_ROOT}/scripts/retro_numbers.py",
             (agents / "qa-retro-analyst.md").read_text(encoding="utf-8"))
    check_in("P5 the failure analyst names the snapshot script through the root", "${CLAUDE_PLUGIN_ROOT}/scripts/bug_snapshot.py",
             (agents / "qa-failure-analyst.md").read_text(encoding="utf-8"))
    check_not_in("P6 the retro analyst names no relative scripts/ path", "`scripts/", (agents / "qa-retro-analyst.md").read_text(encoding="utf-8"))
    check_not_in("P6 the failure analyst names no relative scripts/ path", "`scripts/", (agents / "qa-failure-analyst.md").read_text(encoding="utf-8"))


# --- M: the run mode -------------------------------------------------------------------------------------
def m_the_decision_function():
    import story_step as S
    stamped = {"mode": "desktop", "plugin_root": "/x", "plugin_version": "1.0.0", "since": "t"}
    live = {"stage": "S1", "match": "mode switch", "decision": "yes, go on", "at": "t", "by": "human"}
    same = S.run_mode_switch({"run_mode": stamped}, "S1", "desktop")
    check("M1 the same mode: nothing to refuse", same is None)
    check("M2 a pipeline with no run_mode adopts the current one (no switch)", S.run_mode_switch({}, "S1", "driver") is None)
    check("M2 ... also with an empty mode", S.run_mode_switch({"run_mode": {"mode": " "}}, "S1", "driver") is None)
    check("M3 another mode is a switch", (S.run_mode_switch({"run_mode": stamped}, "S1", "driver") or {}).get("current") == "driver")
    check("M4 a live override of that stage passes it",
          S.run_mode_switch({"run_mode": stamped, "stage_overrides": [live]}, "S1", "driver") is None)
    check("M5 an override of ANOTHER stage does not",
          S.run_mode_switch({"run_mode": stamped, "stage_overrides": [live]}, "S2", "driver") is not None)
    check("M6 a revoked override does not",
          S.run_mode_switch({"run_mode": stamped, "stage_overrides": [dict(live, revoked_at="t")]}, "S1", "driver") is not None)
    check("M7 an override with another block does not",
          S.run_mode_switch({"run_mode": stamped, "stage_overrides": [dict(live, match="stand not confirmed")]}, "S1", "driver") is not None)
    check("M7 the wildcard `*` is not the block named `mode switch`",
          S.run_mode_switch({"run_mode": stamped, "stage_overrides": [dict(live, match="*")]}, "S1", "driver") is not None)
    check("M7 an override with no words does not",
          S.run_mode_switch({"run_mode": stamped, "stage_overrides": [dict(live, decision=" ")]}, "S1", "driver") is not None)
    text = S.run_mode_refusal("QA-1", S.run_mode_switch({"run_mode": stamped}, "S1", "driver"))
    check_in("M8 FR-1: the refusal names what differs", "`desktop` mode", text)
    check_in("M8 ... and the current one", "`driver` mode", text)
    check_in("M8 FR-57: and the door, with the task and the stage", '--task QA-1 --stage S1 --block "mode switch" --decision', text)
    check_in("M8 the door is this copy's waiver.py by absolute path", f'python "{S.HERE.as_posix()}/waiver.py"', text)


def m_stamp_refuse_pass_through_story_step():
    root, task_root, env = T.seed(TASK)
    try:
        from controller import Controller

        def controller_count():
            return len(Controller(task_root).state().get("dispatches", {}))

        pipeline_path = task_root / "pipeline.json"
        check("M9 the legacy pipeline has no run_mode", "run_mode" not in json.loads(pipeline_path.read_text(encoding="utf-8")))
        driver_env = dict(env, QA_FACTORY_RUN_MODE="driver")
        first = harness.run_script("story_step.py", "start", "--task", TASK, "--stage", "S1", "--role", "qa-scout",
                                   cwd=root, env=driver_env)
        check_eq("M9 the first start in driver mode goes through", first.returncode, 0)
        stamp = json.loads(pipeline_path.read_text(encoding="utf-8")).get("run_mode") or {}
        check_eq("M10 it stamped the mode silently (a story with no stamp adopts the current mode)", stamp.get("mode"), "driver")
        check_eq("M10 with the copy's root and version", (stamp.get("plugin_root"), stamp.get("plugin_version")),
                 (str(harness.PLUGIN_ROOT), VERSION))
        check("M10 and when", bool(stamp.get("since")))
        n = controller_count()

        desktop_env = {k: v for k, v in env.items() if k != "QA_FACTORY_RUN_MODE"}
        second = harness.run_script("story_step.py", "start", "--task", TASK, "--stage", "S1", "--role", "qa-scout",
                                    cwd=root, env=desktop_env)
        check_eq("M11 a start in ANOTHER mode is refused", second.returncode, 2)
        check_in("M11 the refusal names both modes and the door", '--block "mode switch"', second.stdout)
        check_in("M11 ... naming what differs", "started in `driver` mode", second.stdout)
        check_eq("M11 nothing was registered by the refused call (position invariant)", controller_count(), n)
        check_eq("M11 and the stamp is untouched", (json.loads(pipeline_path.read_text(encoding="utf-8")).get("run_mode") or {}).get("mode"), "driver")

        word = harness.run_script("waiver.py", "--task", TASK, "--stage", "S1", "--block", "mode switch",
                                  "--decision", "yes, continue in the desktop session", cwd=root, env=desktop_env)
        check_eq("M12 the door named in the refusal works", word.returncode, 0)
        third = harness.run_script("story_step.py", "start", "--task", TASK, "--stage", "S1", "--role", "qa-scout",
                                   cwd=root, env=desktop_env)
        check_not_in("M12 with the person's word recorded, that stage is no longer refused for the switch", "mode switch", third.stdout)
        elsewhere = harness.run_script("story_step.py", "start", "--task", TASK, "--stage", "S2", "--role", "qa-requirements-tester",
                                       cwd=root, env=desktop_env)
        check_eq("M13 the word is per stage: another stage is refused", elsewhere.returncode, 2)
        check_in("M13 with the same door", '--stage S2 --block "mode switch"', elsewhere.stdout)
    finally:
        done(root)


def m_the_driver_asks_at_the_start_of_a_run():
    import story_run
    root, task_root, env, driver = project()
    try:
        pipeline_path = task_root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        driver.check_run_mode()
        check("M14 a story with no stamp: the driver adopts the mode and asks nothing", "package_question" not in driver.state)
        pipeline["run_mode"] = {"mode": "driver", "plugin_root": str(driver.plugin), "plugin_version": VERSION, "since": "t"}
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        driver.check_run_mode()
        check("M15 a story stamped `driver`: nothing to ask", "package_question" not in driver.state)
        pipeline["run_mode"]["mode"] = "desktop"
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        try:
            driver.check_run_mode()
            person = None
        except story_run.Person as raised:
            person = raised
        check("M16 a story stamped `desktop`: the driver asks (kind package)", person is not None and person.kind == "package")
        if person is None:
            return
        check_eq("M16 for the first stage not done", person.stage, "S1")
        check_eq("M16 FR-6: in plain words", problems_of(person.text), [])
        check_in("M16 naming both modes", "desktop mode", person.text)
        check_in("M16 the way to record the word is in the details", '--block "mode switch"', person.details)
        check_eq("M16 the run() entry raises it as a question (exit 3)", story_run.EXIT_PERSON, 3)
        check_eq("M17 run() itself returns the person's exit code", T.driver_for(root, env, TASK).run(), 3)
        question = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_in("M17 and writes the question of kind package", "kind: package", question)
        check_eq("M17 which obeys the rules as shown", problems_of(question), [])

        answering = T.driver_for(root, env, TASK)
        answer = root / "mode-answer.md"
        answer.write_text("go on", encoding="utf-8")
        answering.take_answer(answer)
        overrides = json.loads(pipeline_path.read_text(encoding="utf-8")).get("stage_overrides") or []
        check_eq("M18 the answer is recorded by code as the person's word for that stage",
                 [(o.get("stage"), o.get("match"), o.get("decision")) for o in overrides],
                 [("S1", "mode switch", "go on")])
        try:
            answering.check_run_mode()
            asked_again = False
        except story_run.Person:
            asked_again = True
        check("M18 and the same check no longer asks", not asked_again)
        check_eq("M18 a mode switch is the person's choice, not our defect: no defect_found",
                 [e for e in journal(root) if e.get("event") == "defect_found"], [])
        check("M18 the word is journalled as a human_answer",
              any(e.get("event") == "human_answer" and "run mode switch" in str(e.get("notes")) for e in journal(root)))
    finally:
        done(root)


# --- T: the closed answers (FR-9) --------------------------------------------------------------------------
def answer_run(root, env, text, name="ans.md"):
    """One driver process entry with `--answer`, as a person's answer arrives: (exit code, driver)."""
    path = root / name
    path.write_text(text, encoding="utf-8")
    driver = T.driver_for(root, env, TASK, answer=str(path))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = driver.run()
    return code, driver


# C1-3 node B (D-0041): an answer the package question cannot read is NEW words for the conductor - exactly one call each - and the
# question comes back with the one lead; a conductor with no usable options is the case that shows the site's own question again.
UNREAD = "is not one of the answers this question takes, so nothing has moved yet."
NO_USABLE = {"conductor": {"action": "ask_person", "question": "", "did": "no options"}}


def conductor_kinds(root):
    return [c["kind"] for c in T.stub_calls(root)]


def t_mode_tokens():
    root, task_root, env, driver = project()
    T.set_control(root, dict(NO_USABLE))
    try:
        pipeline_path = task_root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        pipeline["run_mode"] = {"mode": "desktop", "plugin_root": "x", "plugin_version": "1", "since": "t"}
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("T1 setup: the run asks the mode question", T.driver_for(root, env, TASK).run(), 3)
        shown = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        for token in ("`desktop`", "`go on`", "`stop`"):
            check_in(f"T1 the question names the answer {token}", token, shown)

        code, again = answer_run(root, env, "I will think about it")
        again_text = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_eq("T2 an unknown answer: the question is asked again (exit 3)", code, 3)
        check_in("T2 it says the answer was not read and nothing has moved yet (the one lead)", f'Your answer "I will think about it" {UNREAD}', again_text)
        check_in("T2 and still names the tokens (FR-1), as priced option lines", "`desktop`", again_text)
        check_in("T2 it quotes what was said", "I will think about it", again_text)
        check_in("T2 and carries the whole question again", "started in desktop mode", again_text)
        check_eq("T2 and the plain-words rules still hold", problems_of(again_text), [])
        check("T2 no role was run, no override was recorded, and the conductor read the words exactly once (D-0041)",
              conductor_kinds(root) == ["conductor"] and not (json.loads(pipeline_path.read_text(encoding="utf-8")).get("stage_overrides")))
        check("T2 the question is still open", (again.state.get("asked") or {}).get("kind") == "package")

        code, _ = answer_run(root, env, "retry")
        check_in("T3 `retry` is not an answer to the MODE question: asked again with the one lead", 'Your answer "retry" ' + UNREAD,
                 (task_root / "state" / "driver-question.md").read_text(encoding="utf-8"))

        code, held = answer_run(root, env, "Desktop.")
        held_text = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_eq("T4 `desktop`: the run ends with the question open (exit 3)", code, 3)
        check_in("T4 the text says the story waits for the desktop app", "waits for it", held_text)
        check_in("T4 and offers `go on`", "answer `go on`", held_text)
        check("T4 NO role was called and no stage ran (only the two unread answers reached the conductor; `desktop` made no call)",
              conductor_kinds(root) == ["conductor", "conductor"], str(conductor_kinds(root)))
        check("T4 no mode switch was recorded",
              not (json.loads(pipeline_path.read_text(encoding="utf-8")).get("stage_overrides")))
        check("T4 the word is journalled",
              any(e.get("event") == "human_answer" and "Desktop." in str(e.get("notes")) for e in journal(root)))
        check("T4 the question is still open", (held.state.get("asked") or {}).get("kind") == "package")

        code, _ = answer_run(root, env, "STOP")
        stopped_text = (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_eq("T5 `stop`: the run ends with the question open (exit 3)", code, 3)
        check_in("T5 nothing runs and nothing is spent", "Nothing runs and nothing is spent", stopped_text)
        check("T5 no new call: `stop` is a token with an executor (the conductor was called for the two unread answers only)",
              conductor_kinds(root) == ["conductor", "conductor"])
        check_eq("T5 and the plain-words rules still hold", problems_of(stopped_text), [])
        check("T5 still no mode switch recorded",
              not (json.loads(pipeline_path.read_text(encoding="utf-8")).get("stage_overrides")))

        answering = T.driver_for(root, env, TASK)
        path = root / "goon.md"
        path.write_text("`Go on`.", encoding="utf-8")
        answering.take_answer(path)
        overrides = json.loads(pipeline_path.read_text(encoding="utf-8")).get("stage_overrides") or []
        check_eq("T6 `go on` (quoted, capitalised, full stop) is today's pass, recorded", [o.get("match") for o in overrides],
                 ["mode switch"])
    finally:
        done(root)


def t_hooks_tokens():
    root, task_root, env, driver = project()
    T.set_control(root, dict({"receipt": foreign(root)}, **NO_USABLE))
    try:
        person, _ = person_of(driver, task_root)
        driver.ask(person)
        for token in ("`retry`", "`go on`", "`stop`"):
            check_in(f"T7 the question names the answer {token}", token, person.text)
        answer = root / "a.md"

        def answer_with(words):
            answer.write_text(words, encoding="utf-8")
            try:
                driver.take_answer(answer)
                return None
            except story_run_mod().Person as again:
                driver.ask(again)
                return again

        before = len(T.stub_calls(root))
        again = answer_with("maybe later")
        # In THIS project the receipt is foreign for every session, so the conductor's own session meets the same mismatch and the
        # check raises the package question itself (the unread lead is not shown; the words are on the record first): the question
        # comes back with its priced tokens, after exactly one conductor call.
        check("T8 an unknown answer comes back as the package question, priced, after exactly one conductor call",
              again is not None and again.kind == "package" and "`retry`" in again.text and "`go on`" in again.text
              and "## What each answer costs and does" in again.text and "could not tell which answer" not in again.text
              and len(T.stub_calls(root)) == before + 1, str(len(T.stub_calls(root)) - before))
        check("T8 with the details still attached", bool(again and again.details))
        check("T8 nothing passed", not driver.state.get("package_pass"))
        desktop = answer_with("desktop")
        check("T9 `desktop` is not an answer to the hooks question: asked again (the package question, priced)",
              desktop is not None and desktop.kind == "package" and "## What each answer costs and does" in desktop.text)
        held = answer_with("stop")
        check("T10 `stop`: recorded, the question stays open with the same door",
              held is not None and "Nothing runs and nothing is spent" in held.text and "`retry`" in held.text)
        check("T10 nothing passed and no finding filed",
              not driver.state.get("package_pass") and not [e for e in journal(root) if e.get("event") == "defect_found"])
        check("T10 the word is journalled", any(e.get("event") == "human_answer" and "stop" in str(e.get("notes")) for e in journal(root)))
        check("T10 the mixed session was never stored; the two unread answers were one conductor call each and `stop` made none",
              len(T.stub_calls(root)) == before + 2, str((before, len(T.stub_calls(root)))))
        retried = answer_with("retry")
        check("T11 `retry`: the run goes on (nothing raised)", retried is None)
        check("T11 and nothing was passed: the next check asks again", not driver.state.get("package_pass"))
        check("T11 no finding is filed for a retry", not [e for e in journal(root) if e.get("event") == "defect_found"])
        person2, _ = person_of(driver, task_root, dispatch="S1-qa-scout-2")
        check("T11 the copies are compared again, and the same mismatch asks again", person2 is not None)
    finally:
        done(root)


def story_run_mod():
    import story_run
    return story_run


# --- H: roots seen by the older receipts (0.7.9 on) -----------------------------------------------------
def h_host_receipts():
    root, task_root, env, driver = project()
    try:
        import hashlib
        old = harness.temp_dir("qa-pkg-old-")
        (old / ".claude-plugin").mkdir()
        (old / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.7.9"}), encoding="utf-8")

        def host_receipt(sid, plugin_root, script="guard_pre_tool.py"):
            key = hashlib.sha256((sid + script + "PreToolUse").encode()).hexdigest()
            path = receipt_dir(root) / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"host": "claude-code", "script": script, "hook": "PreToolUse", "session_id": sid,
                                        "plugin_root": str(plugin_root)}), encoding="utf-8")

        host_receipt("another-session", old)
        person, result = person_of(driver, task_root)
        check("H1 (control) a host receipt of ANOTHER session is not this session's", person is None and result is not None)
        again = T.driver_for(root, env, TASK)
        host_receipt("sess-S1-qa-scout-2", driver.plugin)
        person, result = person_of(again, task_root, dispatch="S1-qa-scout-2")
        check("H2 (control) a host receipt naming the driver's own root changes nothing", person is None)
        third = T.driver_for(root, env, TASK)
        host_receipt("sess-S1-qa-scout-3", old)
        person, _ = person_of(third, task_root, dispatch="S1-qa-scout-3")
        check("H3 a package receipt of the driver's root PLUS a 0.7.9 root in a host receipt is a mismatch",
              person is not None and "more than one copy" in person.text, getattr(person, "text", ""))
        check_in("H3 the older copy's version is read from its manifest", "0.7.9", getattr(person, "text", ""))
        T.set_control(root, {"receipt": "none"})
        fourth = T.driver_for(root, env, TASK)
        host_receipt("sess-S1-qa-scout-4", old)
        person, _ = person_of(fourth, task_root, dispatch="S1-qa-scout-4")
        check("H4 an older generation that wrote no package receipt at all is still seen",
              person is not None and "another copy, version 0.7.9" in person.text, getattr(person, "text", ""))
        harness.cleanup(old)
    finally:
        done(root)


def main():
    for fn in (r_the_receipt, d_a_match_is_recorded_and_checking_stops, d_a_mismatch_stops_before_anything_is_accepted,
               d_a_mismatch_reaches_no_finish, d_a_missing_receipt_is_a_mismatch_at_the_first_session,
               d_the_persons_word_passes_that_pair_once, d_the_real_hook_and_the_driver_agree, d_dry_run_checks_nothing,
               e_a_roles_bash_sees_the_drivers_root, p_absolute_script_paths, p_agents_name_the_plugin_root,
               m_the_decision_function, m_stamp_refuse_pass_through_story_step, m_the_driver_asks_at_the_start_of_a_run,
               t_mode_tokens, t_hooks_tokens, h_host_receipts):
        scenario(fn)
    finish("test_package_generation")


if __name__ == "__main__":
    main()
