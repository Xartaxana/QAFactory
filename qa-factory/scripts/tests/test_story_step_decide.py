#!/usr/bin/env python3
"""story_step.py `decide`: the door where a person hands a window's cases to themselves (`--hand`), its rows, its refusals and
the area keys. Split off test_story_step.py (TQ1-10); the helpers are in story_step_common.py.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_step  # noqa: E402
from story_step_common import (  # noqa: E402
    DECIDE_WORDS,
    finish_s5,
    manifest_of,
    run_decide,
    s4_story,
    s5_window_story,
    set_rows,
    sha256_of,
)


def decide_door_checks(root: Path, env: dict) -> None:
    """t-721 C2-3 (T1, T1c form 3, T2c, T2d, T3, T4, T6; the rest of the door is in `hand_row_checks`, `open_close_checks`
    and `caller_pair_checks`): the door `story_step.py decide --hand` through a real controller, `finish` deriving the
    pair from the row it wrote."""
    from controller import Controller

    def decide(ticket, words, *more, text=DECIDE_WORDS):
        return run_decide(root, env, ticket, words, *more, text=text)
    manifest, clear_rows = manifest_of, set_rows
    art, window = s5_window_story(root, "QA-T1", handed=False)
    clear_rows(art, [])
    (art / "work/test-cases").mkdir(parents=True, exist_ok=True)
    (art / "work/test-cases/TC-2.md").write_text("the case TC-2", encoding="utf-8")   # t-827 FX-3: the steps lie in a file
    links_file = art / "state/story-case-links.json"   # the fixture pins its cases without a path: TC-2 gets its file's
    links = json.loads(links_file.read_text(encoding="utf-8"))
    for link in links["links"]:
        if link["case_id"] == "TC-2":
            link["path"] = "work/test-cases/TC-2.md"
    links_file.write_text(json.dumps(links), encoding="utf-8")
    done = decide("QA-T1", ["--hand", "TC-2"])
    check_eq("T1: decide --hand on a case with no instance exits 0", done.returncode, 0)
    row = manifest(art)["unresolved"][0]
    check_eq("T1: the row is whole - reason, words_ref, a detail that is steps (the case file's path) and holds no word of "
             "the person", (row["case"], row["reason"], row["detail"], row["words_ref"].startswith("state/words/")),
             ("TC-2", "handed_to_person", "by hand - the steps in work/test-cases/TC-2.md", True))
    check_eq("T1: the words are kept whole in the copy (CRLF, UTF-8)", (art / row["words_ref"]).read_bytes(),
             "I run it myself on the device.\r\nSecond line 00e9".encode("utf-8"))
    record = json.loads((art / "state/decisions/s5-critic.json").read_text(encoding="utf-8"))
    check_eq("T1: the decision record carries the cases, words_ref and the sha256",
             (record["hand"]["cases"], record["hand"]["words_ref"], len(record["hand"]["words_sha256"])),
             (["TC-2"], row["words_ref"], 64))
    again = decide("QA-T1", ["--hand", "TC-2"])
    check_in("T3: the same words again are a no-op", "already recorded", again.stdout)
    check_eq("T3: no second row, no second copy", (len(manifest(art)["unresolved"]), len(list((art / "state/words").iterdir()))),
             (1, 1))
    empty = decide("QA-T1", ["--hand", "TC-2"], text="   \r\n")
    check_eq("T4: empty words - exit 2", empty.returncode, 2)
    check_eq("T4: and nothing new is recorded", len(manifest(art)["unresolved"]), 1)
    check_eq("T6: on S5 --unresolved with --not-complete is still refused",
             (finish_s5(root, env, "QA-T1", "--not-complete", "--unresolved", "x", "--reason", "y").returncode,),
             (2,))
    (art / "work/windows").mkdir(parents=True, exist_ok=True)
    (art / "work/windows/s5-critic.json").write_text(json.dumps(window), encoding="utf-8")
    fin = finish_s5(root, env, "QA-T1")
    record = Controller(art).state()["dispatches"]["s5-critic"]
    check_eq("T1c (form 3): a green instance and a handed case with no instance - finish derives the pair, the "
             "controller accepts", (fin.returncode, record["status"], record.get("unresolved")),
             (0, "accepted", "handed_to_person"))
    check_in("T1c: and the pair names the case", "handed_to_person:TC-2", str(record.get("reason")))
    late = decide("QA-T1", ["--hand", "TC-2"], text="other words")
    check_eq("T2d: --hand on an accepted dispatch - exit 2", (late.returncode, "is accepted" in late.stdout), (2, True))
    # T2c: a row the stand blocked is never erased by the door
    art, _window = s5_window_story(root, "QA-T2", handed=False)
    clear_rows(art, [{"case": "TC-2", "reason": "blocked_by_env", "instance_ids": ["i-9"]}])
    before = hashlib.sha256((art / "work/automation-manifest.json").read_bytes()).hexdigest()
    blocked = decide("QA-T2", ["--hand", "TC-2"])
    check_eq("T2c: --hand over a blocked_by_env row - exit 2, names the stand and gate B, the manifest is untouched",
             (blocked.returncode, "blocked by the stand" in blocked.stdout, "gate B" in blocked.stdout,
              hashlib.sha256((art / "work/automation-manifest.json").read_bytes()).hexdigest() == before),
             (2, True, True, True))
    other = decide("QA-T2", ["--hand", "TC-99"])
    check_eq("an id outside the scope is refused with the scope listed", (other.returncode, "TC-1, TC-2" in other.stdout), (2, True))
    check("no decision record after a refusal", not (art / "state/decisions").exists())


def form_one_checks(root: Path, env: dict) -> None:
    """t-721 C2-3 T1, form 1 (section 3.2): a window whose every case lists NO instance and which the person took whole
    (`decide --hand TC-1,TC-2`): `finish` with no pair derives it from the rows the door wrote and the controller accepts."""
    from controller import Controller
    art, window = s5_window_story(root, "QA-T1F", handed=False)
    data = manifest_of(art)
    data.update(tests=[], unresolved=[])
    (art / "work/automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")
    window = dict(window, scope_instances={"TC-1": [], "TC-2": []}, instances=[])
    (art / "work/windows").mkdir(parents=True)
    (art / "work/windows/s5-critic.json").write_text(json.dumps(window), encoding="utf-8")
    done = run_decide(root, env, "QA-T1F", ["--hand", "TC-1,TC-2"])
    check_eq("T1 (form 1): decide --hand on a window of two cases with no instance exits 0, two rows added",
             (done.returncode, [row["case"] for row in manifest_of(art)["unresolved"]]), (0, ["TC-1", "TC-2"]))
    fin = finish_s5(root, env, "QA-T1F")
    record = Controller(art).state()["dispatches"]["s5-critic"]
    check_eq("T1 (form 1): finish derives the pair from the window (every case a handed case with no instance) and the "
             "controller accepts", (fin.returncode, record["status"], record.get("unresolved")),
             (0, "accepted", "handed_to_person"))
    check_in("T1 (form 1): the pair names both cases", "handed_to_person:TC-1; handed_to_person:TC-2", str(record.get("reason")))
    check_eq("T1 (FX-3): with no case file the detail is the `by hand - the steps of <case>` form",
             [row["detail"] for row in manifest_of(art)["unresolved"]],
             ["by hand - the steps of TC-1", "by hand - the steps of TC-2"])


def hand_row_checks(root: Path, env: dict) -> None:
    """t-721 C2-3: T2 (a case WITH instances), T2b (over the automator's row), T4b (the SS half: the one writer of
    `state/words`)."""
    import argparse
    import contextlib
    import io
    import re
    # T2: the row is INSTANCE-shaped (`instance_ids`), the `tests[]` rows stay, `detail` holds no word of the person
    art, _window = s5_window_story(root, "QA-T2I", handed=False)
    set_rows(art, [])
    tests_before = manifest_of(art)["tests"]
    done = run_decide(root, env, "QA-T2I", ["--hand", "TC-1"])
    check_eq("T2: decide --hand on a case with an instance exits 0", done.returncode, 0)
    row = manifest_of(art)["unresolved"][0]
    check_eq("T2: the row names the case, the reason and its instances", (row["case"], row["reason"], row["instance_ids"]),
             ("TC-1", "handed_to_person", ["i-1"]))
    check_eq("T2: `detail` is the selector of the test the person runs", row["detail"], "tests/test_one.py::test_one")
    check_not_in("T2: and holds no word of the person", "myself", row["detail"])
    check_eq("T2: the tests[] rows of the case are intact", manifest_of(art)["tests"], tests_before)
    # the profile's command leads the selectors (the `<test-file>` placeholder is left out)
    saved = story_step._config, __import__("gate_preflight").s5_profiles
    story_step._config = lambda: {"profiles": [{"profile_id": "api", "commands": {
        "one_test": {"argv": ["python", "-m", "pytest", "<test-file>"], "cwd": "."}}}]}
    sys.modules["gate_preflight"].s5_profiles = lambda _config, _root: {"api": {"cases": ["TC-1"]}}
    try:
        check_eq("T2: with a profile, `detail` = profile: command selectors",
                 story_step._hand_detail(art, "TC-1", story_step._tests_of(manifest_of(art), "TC-1")),
                 "api: python -m pytest tests/test_one.py::test_one")
    finally:
        story_step._config, sys.modules["gate_preflight"].s5_profiles = saved
    # T2b: the automator already wrote a handed row with a command - the door keeps it and adds only `words_ref`
    art, _window = s5_window_story(root, "QA-T2B", handed=True)
    command = "ios: python -m pytest tests/test_two.py::test_two"
    set_rows(art, [{"case": "TC-2", "reason": "handed_to_person", "detail": command}])
    done = run_decide(root, env, "QA-T2B", ["--hand", "TC-2"])
    rows = manifest_of(art)["unresolved"]
    check_eq("T2b: over the automator's handed row - exit 0, one row, its `detail` kept, `words_ref` added",
             (done.returncode, len(rows), rows[0]["detail"], rows[0]["words_ref"].startswith("state/words/")),
             (0, 1, command, True))
    check_in("T2b: and said so", "1 already there - their command kept", done.stdout)
    # T4b (the SS half): the copy of the words outside the story folder is written by person_words.write_words, once
    art, _window = s5_window_story(root, "QA-T4B", handed=False)
    set_rows(art, [])
    spied, real = [], story_step.person_words.write_words

    def spy(task_root, dispatch_id, kind, text):
        spied.append((dispatch_id, kind))
        return real(task_root, dispatch_id, kind, text)

    def in_process():
        path = root / "words-QA-T4B.txt"
        path.write_bytes(DECIDE_WORDS.encode("utf-8"))
        ns = argparse.Namespace(task="QA-T4B", dispatch_id="s5-critic", words_file=str(path), hand="TC-2", open=None,
                                close=False)
        with contextlib.redirect_stdout(io.StringIO()):
            return story_step.decide(ns)
    story_step.person_words.write_words = spy
    try:
        first = in_process()
        again = in_process()
    finally:
        story_step.person_words.write_words = real
    row = manifest_of(art)["unresolved"][0]
    record = json.loads((art / "state/decisions/s5-critic.json").read_text(encoding="utf-8"))
    check_eq("T4b: the door wrote the copy through person_words.write_words, once, kind `decidehand`",
             (first, again, spied), (0, 0, [("s5-critic", "decidehand")]))
    check_eq("T4b: the row and the decision record name that one copy",
             (row["words_ref"] == record["hand"]["words_ref"], sorted(p.name for p in (art / "state/words").iterdir())),
             (True, [Path(row["words_ref"]).name]))
    check("T4b: the name is the writer's own form `driver-decidehand-s5-critic-<stamp>.txt`",
          re.fullmatch(r"driver-decidehand-s5-critic-\d+(-\d+)?\.txt", Path(row["words_ref"]).name) is not None,
          row["words_ref"])
    # the one-writer pin: `state/words` is built in exactly one place - person_words.py (the SR half is C2-3s)
    built = lambda name: [line for line in (harness.SCRIPTS / name).read_text(encoding="utf-8").splitlines()
                          if re.search(r'/ "words"', line)]
    check_eq("T4b pin: story_step.py builds no path of `state/words` (0 lines)", built("story_step.py"), [])
    check_eq("T4b pin, positive control of the same grep: person_words.py has exactly one", len(built("person_words.py")), 1)
    # t-1253 F-3: manifest_put's exit 4 = the rows ARE in the journal and only the manifest's projection is stale; exit 3
    # = refused. The door names the replay for the first and never calls it a refusal; the second is unchanged.
    art, _window = s5_window_story(root, "QA-T4C", handed=False)
    set_rows(art, [])
    real_put = story_step._put_unresolved

    def put_exits(code, said):
        path = root / "words-QA-T4C.txt"
        path.write_bytes(DECIDE_WORDS.encode("utf-8"))
        ns = argparse.Namespace(task="QA-T4C", dispatch_id="s5-critic", words_file=str(path), hand="TC-2", open=None,
                                close=False)
        story_step._put_unresolved = lambda *_a: (code, said)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                return story_step.decide(ns), out.getvalue()
        finally:
            story_step._put_unresolved = real_put
    code, said = put_exits(4, "manifest_put: event committed; projection stale - the fragment is in the journal")
    check_eq("t-1253 F-3: exit 4 - decide stops with exit 2 and names the replay",
             (code, "`manifest_put.py --task QA-T4C --recover`" in said), (2, True))
    check("t-1253 F-3: ... and does not call the committed rows refused", "refused" not in said, said)
    code, said = put_exits(3, "manifest_put: nothing was committed")
    check_eq("t-1253 F-3: CONTROL - exit 3 is still `refused the rows`",
             (code, "manifest_put.py refused the rows" in said), (2, True))


def door_refusal_checks(root: Path, env: dict) -> None:
    """t-827 FX-5 (F6): the branches of the door that refuse and that no other check reaches - the F-15 refusal (a row the
    role wrote with another reason), `--hand` off S5, `--open`/`--close` on S5, a role that does not close the stage, and the
    OSError exit of the copy of the words. Each is exit 2 and NOTHING is recorded: the manifest keeps its sha256, no
    `state/decisions/<D>.json`, no copy under `state/words` (the words file lies OUTSIDE the story folder)."""
    import argparse
    import contextlib
    import io

    def untouched(art: Path) -> tuple:
        manifest = art / "work/automation-manifest.json"
        return (sha256_of(manifest) if manifest.is_file() else None, (art / "state/decisions").exists(),
                sorted(p.name for p in (art / "state/words").iterdir()) if (art / "state/words").is_dir() else [])

    def refused(label, ticket, art, words, dispatch, *expected):
        before = untouched(art)
        done = run_decide(root, env, ticket, words, dispatch=dispatch)
        check_eq(f"FX-5 {label}: exit 2, and nothing recorded (manifest sha256 equal, no decision file, no copy of the words)",
                 (done.returncode, untouched(art) == before, untouched(art)[1:]), (2, True, (False, [])))
        for part in expected:
            check_in(f"FX-5 {label}: the refusal says `{part}`", part, done.stdout)
    # F-15: the role wrote the row with another reason (`impossible`, the fixture's own): the person's word goes to that role
    art, _window = s5_window_story(root, "QA-FX15", handed=False)
    refused("F-15 (a row with another reason)", "QA-FX15", art, ["--hand", "TC-2"], "s5-critic",
            "carried by the manifest as `impossible` by the role that wrote it", "rework_stage", "Nothing was recorded.")
    # --hand off S5, on a real S4 dispatch
    art = s4_story(root, "QA-FX2")
    refused("--hand on an S4 dispatch", "QA-FX2", art, ["--hand", "TC-1"], "s4-critic",
            "`--hand` hands S5 cases; s4-critic is a S4 dispatch")
    # --open / --close on S5
    art, _window = s5_window_story(root, "QA-FX3", handed=False)
    refused("--open on S5", "QA-FX3", art, ["--open", "TC-1"], "s5-critic",
            "`--open` is for the other stages; s5-critic is an S5 dispatch")
    refused("--close on S5", "QA-FX3", art, ["--close"], "s5-critic",
            "`--close` is for the other stages; s5-critic is an S5 dispatch")
    # a role that does not close its stage (S4's designer comes before the critic)
    art = s4_story(root, "QA-FX4", role="qa-case-designer", did="s4-designer")
    refused("--open by a role that does not close the stage", "QA-FX4", art, ["--open", "TC-1"], "s4-designer",
            "s4-designer is qa-case-designer, which does not close S4")
    refused("--close by a role that does not close the stage", "QA-FX4", art, ["--close"], "s4-designer",
            "which does not close S4")
    # the OSError exit: the copy of the words cannot be written (write_words raises) - in process, the writer patched
    art, _window = s5_window_story(root, "QA-FX5", handed=False)
    set_rows(art, [])
    path = root / "words-QA-FX5.txt"
    path.write_bytes(DECIDE_WORDS.encode("utf-8"))
    ns = argparse.Namespace(task="QA-FX5", dispatch_id="s5-critic", words_file=str(path), hand="TC-2", open=None, close=False)
    before, real = untouched(art), story_step.person_words.write_words

    def cannot_write(*_args, **_kwargs):
        raise OSError(13, "Permission denied")
    story_step.person_words.write_words = cannot_write
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = story_step.decide(ns)
    finally:
        story_step.person_words.write_words = real
    check_eq("FX-5 OSError: the copy of the words cannot be saved - exit 2, nothing recorded, no half file",
             (code, untouched(art) == before, untouched(art)[1:]), (2, True, (False, [])))
    check_in("FX-5 OSError: the refusal names the reason and that nothing was recorded", "(Permission denied); nothing was recorded",
             out.getvalue())
    check_in("FX-5 OSError: and the door it can use (the same command again)", "run the same command again", out.getvalue())


def area_key_checks(root: Path) -> None:
    """t-845 C3-12: an S5 window whose scope key is an AREA key (`speakers/TC-9`) over a case with no instance.
    `decide --hand` writes the manifest row with the EXACT key, and `finish` derives the pair from it: the controller's
    map (`_cases_without_instances`, keyed through `contract.scope_keys`) is what `_handed_no_instance` reads, so the case
    is no longer «stray». The controller is a stand-in with the REAL map over the task root (the v2 story fixture is
    bare-keyed: a gate A decision binds the exact scope); the controller's own acceptance of the same row is in
    test_controller_state.py (`an_empty_case_answers_to_the_scope_key_its_manifest_cell_gives`)."""
    import argparse
    import contextlib
    import io
    import types
    from controller import Controller
    key, did = "speakers/TC-9", "s5-critic"
    art = root / "qa-factory/artifacts/QA-AK"
    (art / "work/windows").mkdir(parents=True)
    (art / "work/automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": []}), encoding="utf-8")
    window = {"schema_version": 2, "input_hash": "h", "required_quality_checks": [], "quality_receipts": [],
              "author_dispatch_id": "a", "reviewer_dispatch_id": did, "scope_instances": {key: []}, "instances": []}
    (art / f"work/windows/{did}.json").write_text(json.dumps(window), encoding="utf-8")
    seen: list = []

    class Stop(Exception):
        pass

    class AreaController:
        NO_INSTANCE_REASONS = Controller.NO_INSTANCE_REASONS

        def __init__(self, task_root, wait_seconds=0.0):
            self.store = types.SimpleNamespace(root=task_root)

        def state(self):
            return {"dispatches": {did: {"stage": "S5", "role": "qa-code-critic", "status": "running", "scope": [key]}}}

        def _cases_without_instances(self):
            return Controller._cases_without_instances(self)

        def prepare(self, options):
            seen.append(dict(options))
            raise Stop()
    saved = {name: getattr(story_step, name) for name in
             ("Controller", "_stages", "_handoff_check", "_evidence", "_role_receipts")}
    story_step.Controller = AreaController
    try:
        words = root / "words-QA-AK.txt"
        words.write_bytes(DECIDE_WORDS.encode("utf-8"))
        ns = argparse.Namespace(task="QA-AK", dispatch_id=did, words_file=str(words), hand=key, open=None, close=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = story_step.decide(ns)
        rows = manifest_of(art)["unresolved"]
        check_eq("C3-12: decide --hand on an area-keyed case with no instance exits 0 and writes ONE row under the exact key",
                 (code, [(row["case"], row["reason"]) for row in rows]), (0, [(key, "handed_to_person")]))
        check_eq("C3-12: the controller's map holds that exact key", AreaController(art)._cases_without_instances(),
                 {key: "handed_to_person"})
        check_eq("C3-12: `_handed_no_instance` names the area-keyed case (no «stray»)",
                 story_step._handed_no_instance(window, AreaController(art)), [key])
        word, reason = story_step._derived_pair([], "work/windows/s5-critic.json", (), [key])
        check_eq("C3-12: and the pair is derived from it", (word, reason.endswith("handed_to_person:" + key)),
                 ("handed_to_person", True))
        # finish end to end, up to the call the controller would get: the pair is derived, `empty_scope` is covered
        story_step._stages = lambda: {"S5": {"roles": ["qa-automator", "qa-code-critic"]}}
        story_step._handoff_check = lambda *_a: ("green", "", "")
        story_step._evidence, story_step._role_receipts = lambda *_a: ["work/x.json"], lambda *_a: []
        fin = argparse.Namespace(task="QA-AK", dispatch_id=did, digest="d", output=None, not_complete=False,
                                 complete=True, ignore_handoff=False, window=None, unresolved=None, reason=None)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                story_step.finish(fin)
        except Stop:
            pass
        got = seen[0] if seen else {}
        check_eq("C3-12: finish passes the derived pair to the controller", got.get("unresolved"), "handed_to_person")
        check_in("C3-12: the reason names the area-keyed case", "handed_to_person:" + key, str(got.get("reason")))
        # the control: with no row the same window derives nothing - the controller's «does not carry» stays reachable
        (art / "work/automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": []}), encoding="utf-8")
        seen.clear()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                story_step.finish(fin)
        except Stop:
            pass
        check_eq("C3-12 control: without the manifest row no pair is derived", (seen[0] if seen else {}).get("unresolved"), None)

        # critic t-853 F1: the hand door in the shape code produces (`manifest_from_tests.check_scope` stores the marker's own
        # bare spelling). The REAL controller's stray check (`_s5_collect`) is the judge; the decision record is dropped between
        # runs, else `decide` answers "the same decision is already recorded".
        def hand_over(rows):
            (art / "work/automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": rows}), encoding="utf-8")
            story_step._decision_path(art, did).unlink(missing_ok=True)
            with contextlib.redirect_stdout(io.StringIO()):
                code = story_step.decide(ns)
            written = manifest_of(art)["unresolved"]
            problems: list = []
            Controller(art)._s5_collect({"scope": [key], "input_hash": "h"},
                                        {"unresolved": ["x"], "reason": "handed_to_person; full list: work/windows/s5-critic.json"},
                                        {}, window, problems)
            return code, written, " | ".join(text for _cls, text in problems if "lists no instance" in text)
        bare = {"case": "TC-9", "reason": "handed_to_person", "detail": "the person's own command"}
        code, written, item = hand_over([bare])
        check_eq("C3-12 F1: a BARE handed row + the area-keyed scope - written in the scope's spelling, ONE row, its command kept",
                 (code, [(row["case"], row["reason"], row["detail"]) for row in written]),
                 (0, [(key, "handed_to_person", "the person's own command")]))
        check_eq("C3-12 F1: ...and the controller's stray check accepts the window", item, "")
        exact = {"case": key, "reason": "handed_to_person", "detail": "the person's own command"}
        code, written, item = hand_over([exact])
        check_eq("C3-12 F1 invariant: a row already in the exact spelling is written unchanged",
                 (code, [(row["case"], row["detail"]) for row in written], item), (0, [(key, "the person's own command")], ""))
        code, written, item = hand_over([])
        check_eq("C3-12 F1 negative: the same with no row at all - the row is added under the exact key and accepted",
                 (code, [row["case"] for row in written], item), (0, [key], ""))
        (art / "work/automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": []}), encoding="utf-8")
        stray: list = []
        Controller(art)._s5_collect({"scope": [key], "input_hash": "h"},
                                    {"unresolved": ["x"], "reason": "handed_to_person; full list: work/windows/s5-critic.json"},
                                    {}, window, stray)
        check_in("C3-12 F1 negative: row absent -> «does not carry» as today", "(it does not carry " + key + ")",
                 " | ".join(text for _cls, text in stray))
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)


def main() -> None:
    root = harness.temp_project("qa-story-step-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    try:
        harness.use_project(root)
        decide_door_checks(root, env)
        form_one_checks(root, env)
        hand_row_checks(root, env)
        door_refusal_checks(root, env)
        area_key_checks(root)
    finally:
        harness.cleanup(root)
    harness.finish("test_story_step_decide")


if __name__ == "__main__":
    main()
