#!/usr/bin/env python3
"""TR3-15 (spec t-1937, N-P1-2b): the per-window artifacts of S5 - probe debt, its memory, advice, notes, the judge's file - and the
settle that never touches a running window. Every key below is named in the spec section of the node.

A window's critic reads only ITS window's debt, advice and judge file; the notes are shared (every window reads all of them); the memory
is one story-wide file; a settle leaves what a live window owns, with reason `running_window`, and starts no subprocess for it.
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import test_probe_debt as T  # noqa: E402  (its world, rows, records and stub subprocesses: one set of fixtures for the settle)
import probe_debt as D  # noqa: E402

LATER = "S5-qa-code-critic-3"
WINDOW2 = "S5-qa-automator-4"


def boom(argv, cwd=None, timeout=None):
    raise AssertionError("a subprocess was started: " + " ".join(str(a) for a in argv[2:6]))


def put_controller(w, **statuses):
    for ident, status in statuses.items():
        w.controller["dispatches"][ident]["status"] = status
    T.write(w.task_root / "state" / "controller.json", w.controller)


def add_window(w, ident, status, scope, role="qa-automator"):
    w.controller["dispatches"][ident] = {"id": ident, "stage": "S5", "role": role, "status": status, "scope": list(scope)}
    T.write(w.task_root / "state" / "controller.json", w.controller)


def one_item_world(scope=("TC-1",)):
    w = T.world(scope=scope)
    T.put_manifest(w, [T.row(w, "t1")])
    T.record(w, "t1")
    return w


def settle_never_touches_running_window():
    """KILLS: the B5 branch removed from `settle` (the runner would be called for the item of a running window)."""
    for status in ("running", "returned_unaccepted"):
        w = one_item_world()
        try:
            put_controller(w, **{T.AUTHOR: "accepted"})
            add_window(w, WINDOW2, status, ["TC-1"])
            doc = T.settle(w, _Boom(w))
            check_eq(f"{status} window of the item's case: left with reason running_window",
                     [(i["instance_id"], i["reason"]) for i in doc["left"]], [("t1", "running_window")])
            check_in("...the words name the window", WINDOW2, doc["left"][0]["reason_words"])
            check_eq("...and no outcome, no probe", doc["outcomes"], [])
            check("...running_window is not a stable reason (the scan runs again next time)", "running_window" not in D.STABLE_LEFT)
        finally:
            cleanup(w.project)
    # the window shares the FILE, not the case: another case of the manifest on the same test file
    w = one_item_world()
    try:
        T.put_manifest(w, [T.row(w, "t1"), T.row(w, "t9", case="TC-9")])
        T.record(w, "t1")
        add_window(w, WINDOW2, "running", ["TC-9"])
        doc = T.settle(w, _Boom(w))
        check_eq("a running window whose test file is the item's: left", [i["reason"] for i in doc["left"]], ["running_window"])
        check_in("...by the shared file", "shares the file", doc["left"][0]["reason_words"])
        # the window closes: the same settle probes
        put_controller(w, **{WINDOW2: "accepted"})
        stub = T.Stub(w)
        T.settle(w, stub)
        check_eq("the window accepted: the item is probed", stub.kinds(), ["probe:t1"])
    finally:
        cleanup(w.project)
    # an unreadable controller record: every item out of the settling dispatch's scope is left, the dispatch's own goes on
    w = T.world(scope=("TC-1", "TC-2"))
    try:
        T.put_manifest(w, [T.row(w, "t1"), T.row(w, "t2", case="TC-2")])
        T.record(w, "t1")
        T.record(w, "t2")
        (w.task_root / "state" / "controller.json").write_text("{not json", encoding="utf-8")
        record = dict(w.controller["dispatches"][T.CRITIC], scope=["TC-1"])
        stub = T.Stub(w)
        doc = D.settle(T.TASK, w.task_root, w.project, T.CRITIC, dispatch_record=record, runner=stub, clock=stub.clock,
                       stand=lambda: (False, ""))
        by = T.by_id(doc["left"])
        check_eq("unreadable state: the item outside the scope is left (never a pass, FR-59)", by["t2"]["reason"], "running_window")
        check_eq("...the item of the dispatch's own scope is probed as before", stub.kinds(), ["probe:t1"])
    finally:
        cleanup(w.project)


class _Boom:
    """A runner that raises on any call; `clock` for the settle."""

    def __init__(self, w):
        self.w = w

    def __call__(self, argv, cwd=None, timeout=None):
        return boom(argv, cwd, timeout)

    def clock(self):
        return 0.0


def settle_serial_unchanged():
    """At N=1 no other dispatch is live: the branch never fires, the item is probed, the doc has no `running_window`."""
    w = one_item_world()
    try:
        stub = T.Stub(w)
        doc = T.settle(w, stub)
        check_eq("one dispatch: the item is probed as today", stub.kinds(), ["probe:t1"])
        check_eq("...nothing is left with running_window", [i for i in doc["left"] if i["reason"] == "running_window"], [])
        check("...no controller file at all (the tests of the settle before windows): the same", D.other_windows(w.task_root / "x", "d", {}) == ([], True))
    finally:
        cleanup(w.project)


def _with_record(w, ident, record, first=False):
    """The controller file with `record` added (`first`: before every other dispatch, so it is the older one)."""
    records = dict(w.controller["dispatches"])
    w.controller["dispatches"] = dict({ident: record}, **records) if first else dict(records, **{ident: record})
    T.write(w.task_root / "state" / "controller.json", w.controller)


def settle_stale_returned_record_is_history():
    """KILLS: LIVE_STATUSES counting a returned record that later work (or `recover`, or the plan form) made history: at N=1, after a
    crash and a relaunch, the settle probes the window again. A live window of another dispatch still blocks (the last rows)."""
    old_author = {"id": "S5-qa-automator-0", "stage": "S5", "role": "qa-automator", "status": "returned_unaccepted", "scope": ["TC-1"]}
    rows = (
        ("a returned automator of the same window, a later automator accepted", "S5-qa-automator-0", old_author, True),
        ("a returned dispatch with no scope (a story from before scopes), older than the critic", "S5-qa-automator-0",
         dict(old_author, scope=None), True),
        ("a returned S5 plan dispatch with no scope, whatever its place", "S5-qa-automator-9",
         {"id": "S5-qa-automator-9", "stage": "S5", "role": "qa-automator", "status": "returned_unaccepted",
          "request_binding": {"purpose": "s5_plan"}}, False),
        ("a returned dispatch that recover repaired", "S5-qa-automator-9",
         dict(old_author, id="S5-qa-automator-9", repaired_by_recover=True), False),
        ("a RUNNING record of the same case, older than the settling critic (its predecessor)", "S5-qa-automator-0",
         dict(old_author, status="running"), True))
    for label, ident, record, first in rows:
        w = one_item_world()
        try:
            _with_record(w, ident, record, first)
            stub = T.Stub(w)
            doc = T.settle(w, stub)
            check_eq(f"{label}: the item is probed", (stub.kinds(), [i["reason"] for i in doc["left"]]), (["probe:t1"], []))
        finally:
            cleanup(w.project)
    for label, record in (
            ("a returned dispatch of the case that STARTED AFTER the settling critic", dict(old_author, id="S5-qa-automator-9")),
            ("a returned dispatch with no scope that started after it", dict(old_author, id="S5-qa-automator-9", scope=None))):
        w = one_item_world()
        try:
            _with_record(w, record["id"], record)
            doc = T.settle(w, _Boom(w))
            check_eq(f"{label}: a live window, the item is left", [i["reason"] for i in doc["left"]], ["running_window"])
        finally:
            cleanup(w.project)


def settle_older_window_of_another_case_still_blocks():
    """KILLS: `_is_history` made stage-wide (any later dispatch, the settling critic itself, hides every older record). Two windows launched
    together: window A's critic settles while window B's automator, OLDER in the file, still runs or returned and was never accepted."""
    older = {"id": "S5-qa-automator-0", "stage": "S5", "role": "qa-automator", "scope": ["TC-9"]}
    for status in ("running", "returned_unaccepted"):
        w = one_item_world()
        try:    # another case of the manifest on the SAME test file as the item
            T.put_manifest(w, [T.row(w, "t1"), T.row(w, "t9", case="TC-9")])
            T.record(w, "t1")
            _with_record(w, older["id"], dict(older, status=status), first=True)
            doc = T.settle(w, _Boom(w))
            check_eq(f"an older {status} window of another case that shares the file: the item is left, nothing started",
                     [(i["instance_id"], i["reason"]) for i in doc["left"]], [("t1", "running_window")])
            check_in("...by the shared file", "shares the file", doc["left"][0]["reason_words"])
        finally:
            cleanup(w.project)
        w = one_item_world(scope=("TC-9",))
        try:    # the older window's scope holds the item's case, the settling critic's scope does not
            _with_record(w, older["id"], dict(older, status=status, scope=["TC-1"]), first=True)
            doc = T.settle(w, _Boom(w))
            check_eq(f"an older {status} window whose scope holds the item's case, the critic's scope does not: left for the window",
                     [(i["instance_id"], i["reason"]) for i in doc["left"]], [("t1", "running_window")])
        finally:
            cleanup(w.project)


def settle_empty_find_answers_the_old_debt_file():
    """KILLS: F4 reverted (`if path.is_file():`): a story from before has only `work/probe-debt.json`, written for critic X; an empty settle
    of critic Y writes Y's own empty file, so Y's brief carries no 'written for dispatch X' note."""
    import story_step
    w = T.world()
    try:
        T.put_manifest(w, [])
        old = w.task_root / D.OLD_DEBT_REL
        T.write(old, {"schema_version": D.SCHEMA_VERSION, "task": T.TASK, "dispatch": "S5-qa-code-critic-1", "outcomes": [],
                      "left": [{"instance_id": "t1", "reason": "rebind"}], "info": []})
        (w.task_root / D.MEMORY_REL).unlink(missing_ok=True)
        check("control: before the settle Y reads the old file and is told it is X's",
              any("written for dispatch S5-qa-code-critic-1" in n for n in story_step._debt_input(T.TASK, w.task_root, T.CRITIC)[1]))
        T.settle(w, T.Stub(w))
        check("the critic's own empty file is written beside the old one", (w.task_root / D.debt_rel(T.CRITIC)).is_file())
        check_eq("...and Y's debt input is no input and no note", story_step._debt_input(T.TASK, w.task_root, T.CRITIC), ([], []))
    finally:
        cleanup(w.project)


def memory_survives_per_dispatch_files():
    w = one_item_world()
    try:
        T.put_manifest(w, [T.row(w, "ra", bound=T.STALE)])
        T.record(w, "ra", measured=T.STALE)
        stub = T.Stub(w)
        stub.dry_ids = []
        T.settle(w, stub)
        first = w.task_root / D.debt_rel(T.CRITIC)
        check("the critic's own file is written", first.is_file())
        check("...and the story-wide memory beside it", (w.task_root / D.MEMORY_REL).is_file())
        put_controller(w, **{T.CRITIC: "accepted"})
        w.controller["dispatches"][LATER] = {"id": LATER, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                              "scope": w.scope}
        T.write(w.task_root / "state" / "controller.json", w.controller)
        first.unlink()                    # the earlier critic's file is gone: the memory still carries
        calls = []
        doc = D.settle(T.TASK, w.task_root, w.project, LATER, dispatch_record=w.controller["dispatches"][LATER],
                       runner=lambda *a, **k: calls.append(a) or (1, "", ""), clock=lambda: 0.0, stand=lambda: (False, ""))
        check_eq("the next critic's settle stands on the memory: nothing was started", (len(calls), doc.get("unchanged_since")), (0, T.CRITIC))
        check_eq("...its own file names ITS dispatch, the memory the last settle's", json.loads(
            (w.task_root / D.debt_rel(LATER)).read_text(encoding="utf-8"))["dispatch"], LATER)
        check_eq("...and the earlier critic's file was not recreated", (w.task_root / D.debt_rel(T.CRITIC)).exists(), False)
    finally:
        cleanup(w.project)


def memory_absent_reads_old_file():
    w = one_item_world()
    try:
        T.put_manifest(w, [T.row(w, "ra", bound=T.STALE)])
        T.record(w, "ra", measured=T.STALE)
        stub = T.Stub(w)
        stub.dry_ids = []
        T.settle(w, stub)
        memory = json.loads((w.task_root / D.MEMORY_REL).read_text(encoding="utf-8"))
        check_eq("no memory file, no old file: no memory", D._memory_doc(w.task_root / "nowhere", T.TASK), None)
        (w.task_root / D.MEMORY_REL).unlink()
        T.write(w.task_root / D.OLD_DEBT_REL, memory)
        check_eq("no memory file, the old file of a story from before is the memory", (D._memory_doc(w.task_root, T.TASK) or {}).get("dispatch"),
                 T.CRITIC)
        stub = T.Stub(w)
        stub.dry_ids = []
        doc = D.settle(T.TASK, w.task_root, w.project, LATER, dispatch_record=dict(
            w.controller["dispatches"][T.CRITIC], id=LATER), runner=lambda *a, **k: boom(a[0]), clock=lambda: 0.0, stand=lambda: (False, ""))
        check_eq("...and a settle on it starts nothing", doc.get("unchanged_since"), T.CRITIC)
        check("the old file is read, never written by the settle", json.loads((w.task_root / D.OLD_DEBT_REL).read_text(encoding="utf-8")) == memory)
    finally:
        cleanup(w.project)


def memory_unreadable_runs():
    w = one_item_world()
    try:
        T.put_manifest(w, [T.row(w, "ra", bound=T.STALE)])
        T.record(w, "ra", measured=T.STALE)
        stub = T.Stub(w)
        stub.dry_ids = []
        T.settle(w, stub)
        good = (w.task_root / D.MEMORY_REL).read_text(encoding="utf-8")
        T.write(w.task_root / D.OLD_DEBT_REL, good)         # a valid OLD file must not stand behind an unreadable memory
        (w.task_root / D.MEMORY_REL).write_text("{not json", encoding="utf-8")
        check_eq("an unreadable memory is no memory (and the old file is not consulted behind it)", D._memory_doc(w.task_root, T.TASK), None)
        stub = T.Stub(w)
        stub.dry_ids = []
        T.settle(w, stub)
        check_eq("the settle runs: the dry run is made", stub.kinds(), ["dry"])
        # a memory write that fails is reported, and the file it could not replace is removed so the next settle runs
        real = D.atomic_json

        def failing(path, value):
            if Path(path).name == Path(D.MEMORY_REL).name:
                raise OSError("disk full")
            return real(path, value)
        D.atomic_json = failing
        try:
            stub = T.Stub(w)
            stub.dry_ids = []
            doc = T.settle(w, stub)
        finally:
            D.atomic_json = real
        check_in("a memory that was not written is told in the doc", "was not written", doc.get("memory_error", ""))
        check("...the critic's own file stands", (w.task_root / D.debt_rel(T.CRITIC)).is_file())
        check("...and no stale memory is left behind", not (w.task_root / D.MEMORY_REL).exists())
    finally:
        cleanup(w.project)


def kept_rebind_has_own_word():
    check_in("a kept rebind remembered has its own reason, stable", "rebind_same_bytes", D.STABLE_LEFT)
    check_in("...and `same_bytes` stays the probe's", "same_bytes", D.STABLE_LEFT)
    w = T.world()
    try:
        T._refused_world(w)
        T.settle(w, T._refused_stub(w))
        second = T.settle(w, T._refused_stub(w))
        left = T.by_id(second["left"])
        check_eq("the kept rebind of the same bytes", left["ra"]["reason"], "rebind_same_bytes")
    finally:
        cleanup(w.project)


def _story(root_name="qa-win-art-"):
    """A story folder with two windows: automators A1/A2 accepted, critics C1/C2 running; (root, task_root, controller)."""
    import harness
    root = harness.temp_project(root_name)
    task_root = root / "qa-factory" / "artifacts" / "WA-1"
    rows = {}
    for n, case in ((1, "TC-1"), (2, "TC-2")):
        rows[f"S5-qa-automator-{n}"] = {"id": f"S5-qa-automator-{n}", "stage": "S5", "role": "qa-automator", "status": "accepted", "scope": [case]}
        rows[f"S5-qa-code-critic-{n}"] = {"id": f"S5-qa-code-critic-{n}", "stage": "S5", "role": "qa-code-critic", "status": "running", "scope": [case]}
    controller = {"dispatches": rows}
    T.write(task_root / "state" / "controller.json", controller)
    return root, task_root, controller


def debt_input_reads_only_its_own():
    import story_step
    root, task_root, _controller = _story()
    try:
        for n in (1, 2):
            T.write(task_root / D.debt_rel(f"S5-qa-code-critic-{n}"), {"dispatch": f"S5-qa-code-critic-{n}", "left": [{"instance_id": f"t{n}"}]})
        got = story_step._debt_input("WA-1", task_root, "S5-qa-code-critic-2")[0]
        check_eq("critic 2 is handed critic 2's file", got, ["qa-factory/artifacts/WA-1/" + D.debt_rel("S5-qa-code-critic-2")])
        (task_root / D.debt_rel("S5-qa-code-critic-2")).unlink()
        check_eq("critic 2 with no file of its own is handed nothing - never critic 1's", story_step._debt_input("WA-1", task_root, "S5-qa-code-critic-2"), ([], []))
    finally:
        cleanup(root)


def debt_old_story_falls_back():
    import story_step
    root, task_root, _controller = _story()
    try:
        T.write(task_root / D.OLD_DEBT_REL, {"dispatch": "S5-qa-code-critic-1", "left": [{"instance_id": "t1"}]})
        check_eq("no file of its own: the old single file of that dispatch, by today's rule",
                 story_step._debt_input("WA-1", task_root, "S5-qa-code-critic-1")[0], ["qa-factory/artifacts/WA-1/" + D.OLD_DEBT_REL])
        extras, notes = story_step._debt_input("WA-1", task_root, "S5-qa-code-critic-2")
        check_eq("...an old file written for another dispatch is no input, and says so", (extras, len(notes)), ([], 1))
        check_in("...naming the dispatch it was written for", "S5-qa-code-critic-1", notes[0])
    finally:
        cleanup(root)


def advice_per_dispatch_atomic():
    import event_store
    import exit_gate
    root, task_root, _controller = _story()
    try:
        calls = []
        real = event_store.atomic_text
        event_store.atomic_text = lambda path, text: calls.append(Path(path).name) or real(path, text)
        try:
            why = exit_gate.write_advice(task_root, "S5", "qa-automator", [], [], "S5-qa-automator-2")
            other = exit_gate.write_advice(task_root, "S2", "qa-requirements-tester", [], [])
        finally:
            event_store.atomic_text = real
        check_eq("written", (why, other), ("", ""))
        check_eq("S5 with an identity: one file per dispatch, through the one atomic publisher",
                 calls, ["advice-S5-S5-qa-automator-2.json", "advice-S2.json"])
        body = json.loads((task_root / "work" / "advice-S5-S5-qa-automator-2.json").read_text(encoding="utf-8"))
        check_eq("...the file says whose it is", (body["stage"], body["dispatch"]), ("S5", "S5-qa-automator-2"))
        check_eq("...no temp file is left", [p.name for p in (task_root / "work").glob("*.tmp")], [])
        check("a non-S5 stage keeps `advice-<stage>.json`", (task_root / "work" / "advice-S2.json").is_file())
    finally:
        cleanup(root)


def advice_no_identity_old_path():
    import exit_gate
    root, task_root, _controller = _story()
    try:
        check_eq("no identity: the old path", exit_gate.advice_rel("S5", ""), "work/advice-S5.json")
        check_eq("an identity: the dispatch's", exit_gate.advice_rel("S5", "S5-qa-automator-2"), "work/advice-S5-S5-qa-automator-2.json")
        exit_gate.write_advice(task_root, "S5", "qa-automator", [], [])
        check("the skill road (no identity) writes the old file", (task_root / "work" / "advice-S5.json").is_file())
        body = json.loads((task_root / "work" / "advice-S5.json").read_text(encoding="utf-8"))
        check_not_in("...with no dispatch key (the shape of before)", "dispatch", body)
    finally:
        cleanup(root)


def critic_reads_only_its_window():
    """KILLS: `advice_of` taking the newest advice file, or `_debt_input` / the judge input reading another window's file."""
    import brief_pack
    import story_step
    root, task_root, controller = _story()
    try:
        for n in (1, 2):
            T.write(task_root / "work" / f"advice-S5-S5-qa-automator-{n}.json", {"stage": "S5", "dispatch": f"S5-qa-automator-{n}"})
            T.write(task_root / D.debt_rel(f"S5-qa-code-critic-{n}"), {"dispatch": f"S5-qa-code-critic-{n}", "left": [1]})
            T.write(task_root / f"work/judge-code-S5-qa-code-critic-{n}.json", {})
        for n in (1, 2):
            critic = controller["dispatches"][f"S5-qa-code-critic-{n}"]
            check_eq(f"critic {n}: the advice of automator {n}", brief_pack.advice_of(task_root, controller, critic),
                     f"work/advice-S5-S5-qa-automator-{n}.json")
        T.write(task_root / "work" / "advice-S5.json", {"stage": "S5"})
        check_eq("two windows: the old advice file answers nothing (it could be a neighbour's)",
                 brief_pack.advice_of(task_root, controller, controller["dispatches"]["S5-qa-code-critic-2"]),
                 "work/advice-S5-S5-qa-automator-2.json")
        (task_root / "work" / "advice-S5-S5-qa-automator-2.json").unlink()
        check_eq("...even when the window's own is absent: the absence line names ITS file, never the neighbour's or the old one",
                 brief_pack.advice_of(task_root, controller, controller["dispatches"]["S5-qa-code-critic-2"]),
                 "work/advice-S5-S5-qa-automator-2.json")
        real = story_step.judge.active
        story_step.judge.active = lambda *a, **k: True
        try:
            got = story_step._prompt_inputs("WA-1", "S5", "qa-code-critic", task_root, "S5-qa-code-critic-2")
        finally:
            story_step.judge.active = real
        check_eq("critic 2's inputs: its judge file and its debt, nothing of window 1",
                 sorted(got), sorted(f"qa-factory/artifacts/WA-1/{p}" for p in ("work/judge-code-S5-qa-code-critic-2.json", D.debt_rel("S5-qa-code-critic-2"))))
        names = brief_pack._input_names({}, "qa-code-critic", "window", "", "work/advice-S5-S5-qa-automator-2.json")
        check_in("the brief's names carry the one advice file", "work/advice-S5-S5-qa-automator-2.json", names)
        check_not_in("...and no other advice file or the old name", "work/advice-S5.json", names)
        # one window (a story from before): the old name answers
        one = {"dispatches": {k: v for k, v in controller["dispatches"].items() if k.endswith("-1")}}
        T.write(task_root / "state" / "controller.json", one)
        (task_root / "work" / "advice-S5-S5-qa-automator-1.json").unlink()
        check_eq("one window, no file of its own: the old file", brief_pack.advice_of(task_root, one, one["dispatches"]["S5-qa-code-critic-1"]),
                 "work/advice-S5.json")
    finally:
        cleanup(root)


def notes_of_both_windows_in_next_brief():
    import brief_pack
    import controller as CT
    root, task_root, _controller = _story()
    try:
        (task_root / "work" / "s5-notes").mkdir(parents=True)
        for name in ("S5-qa-automator-1", "S5-qa-automator-2", "S5-qa-code-critic-1"):
            (task_root / "work" / "s5-notes" / f"{name}.md").write_text("page object `Login`: tests/pages/login.py\n", encoding="utf-8")
        (task_root / "work" / "s5-notes.md").write_text("old notes\n", encoding="utf-8")
        lines = brief_pack.file_lines(["work/s5-notes.md", brief_pack.NOTES_GLOB], task_root, root, True)
        shown = "\n".join(lines)
        for name in ("work/s5-notes.md", "S5-qa-automator-1.md", "S5-qa-automator-2.md", "S5-qa-code-critic-1.md"):
            check_in(f"the brief lists {name}", name, shown)
        check_eq("the brief's names: each per-dispatch file, in place of the glob", brief_pack.notes_names(task_root),
                 ["work/s5-notes/S5-qa-automator-1.md", "work/s5-notes/S5-qa-automator-2.md", "work/s5-notes/S5-qa-code-critic-1.md"])
        check_eq("...a story with no notes folder adds nothing (its brief is the brief it had)", brief_pack.notes_names(task_root / "nowhere"), [])
        fake = types.SimpleNamespace(store=types.SimpleNamespace(root=task_root))
        first = CT.Controller._read_first(fake, "S5")
        check_eq("the receipt's read_first: the old file, then every per-dispatch file in name order", first,
                 ["work/s5-notes.md", "work/s5-notes/S5-qa-automator-1.md", "work/s5-notes/S5-qa-automator-2.md",
                  "work/s5-notes/S5-qa-code-critic-1.md"])
        check_eq("...other stages: nothing", CT.Controller._read_first(fake, "S6"), [])
        for role in ("qa-automator", "qa-code-critic", "qa-runner"):
            check_in(f"{role} reads the notes folder", brief_pack.NOTES_GLOB, brief_pack.ROLE_FILES[role])
        owners = json.loads((SCRIPTS.parent / "references" / "artifact-writers.json").read_text(encoding="utf-8"))["artifacts"]
        check_eq("registry: the critic's notes are the critic's", owners["work/s5-notes/S5-qa-code-critic-*.md"]["writer"], "qa-code-critic (the role)")
        check_eq("registry: the automator's notes are the automator's", owners["work/s5-notes/S5-qa-automator-*.md"]["writer"], "qa-automator (the role)")
        import guard_pre_tool as G
        check_eq("the guard resolves a critic's notes file to the critic", G._owner_of_path("qa-factory/artifacts/WA-1/work/s5-notes/S5-qa-code-critic-2.md")[0],
                 "qa-code-critic")
        check_eq("...and an automator's to the automator", G._owner_of_path("qa-factory/artifacts/WA-1/work/s5-notes/S5-qa-automator-2.md")[0],
                 "qa-automator")
    finally:
        cleanup(root)


def judge_per_dispatch():
    import judge_code
    import story_step
    check_eq("one file per critic dispatch", judge_code.report_rel("S5-qa-code-critic-2"), "work/judge-code-S5-qa-code-critic-2.json")
    check_eq("no dispatch (a manual run): the old name", judge_code.report_rel(None), "work/judge-code.json")
    script, argv, output = story_step.PRE_WORK["qa-code-critic"][0]
    check_eq("PRE_WORK names the same file for the dispatch it runs for", output.replace("{dispatch}", "S5-qa-code-critic-2"),
             judge_code.report_rel("S5-qa-code-critic-2"))
    check_in("the prompt line names the file of the dispatch", "work/judge-code-S5-qa-code-critic-2.json",
             story_step.JUDGE_GUIDANCE["qa-code-critic"].replace("{dispatch}", "S5-qa-code-critic-2"))
    import brief_pack
    import judge
    old = judge.active
    judge.active = lambda *a, **k: True
    try:
        lines = "\n".join(brief_pack.judge_lines("qa-code-critic", True, "S5-qa-code-critic-2"))
    finally:
        judge.active = old
    check_in("the brief's judge line names its own file", "work/judge-code-S5-qa-code-critic-2.json", lines)
    check_not_in("...with no placeholder left", "{dispatch}", lines)


def main():
    settle_never_touches_running_window()
    settle_serial_unchanged()
    settle_stale_returned_record_is_history()
    settle_older_window_of_another_case_still_blocks()
    settle_empty_find_answers_the_old_debt_file()
    memory_survives_per_dispatch_files()
    memory_absent_reads_old_file()
    memory_unreadable_runs()
    kept_rebind_has_own_word()
    debt_input_reads_only_its_own()
    debt_old_story_falls_back()
    advice_per_dispatch_atomic()
    advice_no_identity_old_path()
    critic_reads_only_its_window()
    notes_of_both_windows_in_next_brief()
    judge_per_dispatch()
    finish("test_window_artifacts")


if __name__ == "__main__":
    main()
