#!/usr/bin/env python3
"""The launch path pays the dashboard once, the fingerprint once per process, and the gate collects like S5 (SC1-12).

Run 12586 / CX2-3 / C3-26 / EP1-11: `stage_done --status running` re-rendered the dashboard and the metrics after
each of its two calls per dispatch (about 57 s on a story copy), `resolve_runtime` read and hashed every file of the
package on every call, and the gate rehearsal ran its own collect that knew none of S5's retries. Keys L1-L13 are the
spec's (docs/tasks/specs/t-1245, section 5.2); L14 pins the `CollectError.kind` values the gate branches on.

Each key names the mutation it kills (N1-N8), so a reader can see what the test is FOR.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import dashboard_refresh  # noqa: E402
import event_store  # noqa: E402
import gate_preflight  # noqa: E402
import node_ids  # noqa: E402
import release_fingerprint as RF  # noqa: E402
import runtime_paths as RP  # noqa: E402
import stage_done  # noqa: E402
from controller import RETURNED, Controller  # noqa: E402

import test_controller_state as BASE  # noqa: E402  (accept_stage: a stage the controller has accepted)

HAVE_PYTEST = importlib.util.find_spec("pytest") is not None
MARKER = "state/dashboard-deferred.json"


# --- the dashboard (L1-L6) -----------------------------------------------------------------------------------------------

class Refreshes:
    """A `dashboard_refresh.refresh_for_task` stand-in that counts its calls and answers `answer`."""

    def __init__(self, answer="current"):
        self.calls = 0
        self.answer = answer

    def __call__(self, task_root):
        self.calls += 1
        return {"status": self.answer}


@contextlib.contextmanager
def counted(answer="current"):
    original = dashboard_refresh.refresh_for_task
    probe = Refreshes(answer)
    dashboard_refresh.refresh_for_task = probe
    try:
        yield probe
    finally:
        dashboard_refresh.refresh_for_task = original


def managed_story(prefix):
    """(project, story folder, controller): an initialized controller story under a project, S0 not yet dispatched."""
    root = temp_project(prefix)
    task = root / "qa-factory" / "artifacts" / "QA-1"
    task.mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}), encoding="utf-8")
    use_project(root)
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "r", "known_paths": {"root": str(root)},
                                    "idempotency_key": "init"})
    return root, task, controller


def dispatch_s0(controller, identifier="dS0"):
    controller.apply("dispatch", {"id": identifier, "stage": "S0", "role": "qa-scout", "scope": ["TC-1"], "input_hash": "h",
                                  "budget": {}, "known_paths": {}, "idempotency_key": "d-" + identifier})


def run_stage_done(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stage_done.run(*args, **kwargs)
    return code, out.getvalue(), err.getvalue()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def l1_running_defers_the_render():
    """KILLS N1 (the substitution also on `done`: L2/L6 go red the other way) and a `running` that renders again."""
    root, task, controller = managed_story("qa-lpc-l1-")
    try:
        dispatch_s0(controller)
        with counted() as probe:
            code, out, _err = run_stage_done("QA-1", "S0", "running", "qa-scout", "", False)
        check_eq("L1 running: exit 0", code, 0)
        check_eq("L1 running: the dashboard was rendered 0 times", probe.calls, 0)
        marker = read_json(task / MARKER)
        check_eq("L1 the marker names the factory as its owner", (marker.get("status"), marker.get("owner")), ("deferred", "factory"))
        check_in("L1 and says how to refresh now (recover)", "--operation recover", marker.get("reason", ""))
        check_in("L1 and names the stage", "stage S0 running", marker.get("reason", ""))
        # F3 (t-1329, AR-4): the door names the story by its key; a story copied to another worktree carries this file
        check_in("L1 the door is `controller.py --task <KEY> --operation recover`", "controller.py --task QA-1 --operation recover",
                 marker.get("reason", ""))
        check_not_in("L1 ... and no absolute path of this machine is in the marker", str(task), json.dumps(marker))
        check_not_in("L1 ... nor `--task-root`", "--task-root", marker.get("reason", ""))
        stage = (read_json(task / "pipeline.json").get("stages") or {}).get("S0") or {}
        check("L1 pipeline.json has the stage running with its start (E17: only the render is deferred)",
              stage.get("status") == "running" and bool(stage.get("started")), str(stage))
        journal = RP.record(root, "journal.jsonl")
        lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()] if journal.is_file() else []
        check("L1 the journal holds the `delegated` line of the transition", any(r.get("event") == "delegated" for r in lines), str(lines))
        check_not_in("L1 the marker write is silent on success", "deferral marker not written", out)
    finally:
        cleanup(root)


def l2_done_renders_once_and_clears_the_marker():
    """KILLS N1: a substitution that also covers `done` renders 0 times here."""
    root, task, controller = managed_story("qa-lpc-l2-")
    try:
        with counted("pending") as probe:             # a view that was NOT brought up to date keeps the marker (FR-41)
            run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
            BASE.accept_stage(controller, task, "S0")  # the controller's own commits render as ever
        check("L2 a refresh that answered `pending` leaves the marker standing", (task / MARKER).is_file())
        with counted("current") as probe:
            code, _out, err = run_stage_done("QA-1", "S0", "done", "qa-scout", "S0 closed", True)
        check_eq("L2 the next `done` of the accepted stage: exit 0", (code, err), (0, ""))
        check_eq("L2 ... renders the view exactly once", probe.calls, 1)
        check("L2 ... and the view is current, so the marker is gone", not (task / MARKER).exists())
    finally:
        cleanup(root)


def l3_running_twice_never_renders():
    root, task, controller = managed_story("qa-lpc-l3-")
    try:
        dispatch_s0(controller)
        with counted() as probe:
            first = run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
            second = run_stage_done("QA-1", "S0", "running", "qa-scout", "", True, "agent-1", dispatch_id="dS0")
        check_eq("L3 start then bind (--agent-id/--dispatch-id): both exit 0", (first[0], second[0]), (0, 0))
        check_eq("L3 and not one render on the launch path (E15)", probe.calls, 0)
        check_eq("L3 the second call wrote the marker again with the same content", read_json(task / MARKER).get("status"), "deferred")
        bound = (controller.state().get("dispatches") or {}).get("dS0") or {}
        check("L3 the bind still reached the dispatch record (nothing but the render was deferred)",
              "agent-1" in json.dumps(bound), str(bound)[:200])
    finally:
        cleanup(root)


def l4_a_refused_running_leaves_no_trace():
    """KILLS N2 (the substitution before the refusal): `_defer_refresh` is called on a refused call, which is the trace."""
    calls = []
    original = stage_done._defer_refresh
    stage_done._defer_refresh = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
    root, task, controller = managed_story("qa-lpc-l4-")
    try:
        BASE.accept_stage(controller, task, "S0")
        with counted() as probe:
            code, _out, err = run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
        check_eq("L4 running over an accepted stage is refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("L4 ... by the rule that names rework", "already accepted by the controller", err)
        check_eq("L4 the refused call replaced the after-commit step of no store (E19)", calls, [])
        check("L4 ... and left no marker", not (task / MARKER).exists())
        check_eq("L4 ... and rendered nothing", probe.calls, 0)
    finally:
        cleanup(root)
    # control: the SAME probe IS called by a `running` call that passes (the empty list above means the refusal, not a dead probe)
    root, task, controller = managed_story("qa-lpc-l4b-")
    try:
        dispatch_s0(controller)
        run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
        check_eq("L4 control: a running call that passes calls it once", len(calls), 1)
    finally:
        stage_done._defer_refresh = original
        cleanup(root)


def l5_a_marker_that_cannot_be_written_is_one_line():
    root, task, controller = managed_story("qa-lpc-l5-")
    real = event_store.atomic_json

    def refusing(path, data, *a, **k):
        if Path(path).name == "dashboard-deferred.json":
            raise PermissionError("seam: the marker is held")
        return real(path, data, *a, **k)
    try:
        dispatch_s0(controller)
        event_store.atomic_json = refusing
        try:
            with counted() as probe:
                code, out, err = run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
        finally:
            event_store.atomic_json = real
        check_eq("L5 the exit is unchanged", code, 0)
        check_in("L5 one stdout line says the marker was not written", "dashboard: deferral marker not written (PermissionError", out)
        check_eq("L5 nothing went to stderr", err, "")
        stage = (read_json(task / "pipeline.json").get("stages") or {}).get("S0") or {}
        check_eq("L5 the transition itself is durable (E18)", stage.get("status"), "running")
        check_eq("L5 and still no render", probe.calls, 0)
    finally:
        event_store.atomic_json = real
        cleanup(root)


def l5b_a_failure_marker_of_the_refresh_is_kept():
    """KILLS N10 (`_defer_refresh` overwrites what `controller.refresh_derived` recorded: the failure record is lost, t-1329 Q-2)."""
    for label, left in (("a failed refresh", {"status": "deferred", "owner": "factory", "file": "", "error": "OSError: disk full",
                                              "reason": "the dashboard could not be refreshed after the event was committed"}),
                        ("a held telemetry file", {"status": "deferred", "owner": "factory", "file": "state/telemetry/hook-x.json",
                                                   "reason": "telemetry file held by another process"})):
        root, task, controller = managed_story("qa-lpc-l5b-")
        try:
            dispatch_s0(controller)
            (task / "state").mkdir(parents=True, exist_ok=True)
            (task / MARKER).write_text(json.dumps(left), encoding="utf-8")
            with counted() as probe:
                code, out, err = run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
            check_eq(f"L5b {label}: running exits 0", (code, err), (0, ""))
            check_eq(f"L5b {label}: the marker the refresh left is kept as it was", read_json(task / MARKER), left)
            check_not_in(f"L5b {label}: and nothing is printed over it", "deferral marker not written", out)
            check_eq(f"L5b {label}: and still no render", probe.calls, 0)
        finally:
            cleanup(root)
    # control: a marker of OUR kind (no error, no file) is rewritten as before - the guard is the failure record, not any file
    root, task, controller = managed_story("qa-lpc-l5c-")
    try:
        dispatch_s0(controller)
        (task / "state").mkdir(parents=True, exist_ok=True)
        (task / MARKER).write_text(json.dumps({"status": "deferred", "owner": "factory", "reason": "stage S9 running: old"}),
                                   encoding="utf-8")
        run_stage_done("QA-1", "S0", "running", "qa-scout", "", True)
        check_in("L5b control: our own earlier marker is rewritten with this stage", "stage S0 running",
                 read_json(task / MARKER).get("reason", ""))
    finally:
        cleanup(root)


def l6_done_and_halted_render_as_before():
    root, task, controller = managed_story("qa-lpc-l6-")
    try:
        dispatch_s0(controller)
        with counted() as probe:
            code, _out, _err = run_stage_done("QA-1", "S0", "halted", "qa-scout", "waiting for a person", True)
        check_eq("L6 halted: exit 0", code, 0)
        check_eq("L6 halted renders as it always did", probe.calls, 1)
    finally:
        cleanup(root)


# --- the package fingerprint (L7, L8) ------------------------------------------------------------------------------------

def mini_package():
    """A package-shaped tree the recipe can walk: a manifest, the entrypoints `resolve_runtime` demands, one extra recipe file."""
    root = temp_dir("qa-lpc-pkg-")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    (root / "scripts").mkdir()
    for name in RP.ENTRYPOINT_NAMES:
        (root / "scripts" / (name + ".py")).write_text("# " + name + "\n", encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "r.json").write_text('{"a": 1}', encoding="utf-8")
    return root


@contextlib.contextmanager
def counting_recipe():
    """`release_fingerprint.package_fingerprint` counted, delegating to the real recipe."""
    real = RF.package_fingerprint
    calls = []

    def counting(root=None, files=None):
        calls.append(str(root))
        return real(root, files=files)
    RF.package_fingerprint = counting
    try:
        yield calls
    finally:
        RF.package_fingerprint = real


def l7_the_fingerprint_is_hashed_once_while_the_files_are_unchanged():
    """KILLS N3 (a signature without `size`: step 2 stays cached) and N4 (a signature of the path alone: steps 2-5)."""
    project = temp_project("qa-lpc-l7-")
    package = mini_package()
    task = project / "qa-factory" / "artifacts" / "QA-1"
    task.mkdir(parents=True)
    held, RP.package_root = RP.package_root, (lambda: package)
    RP._FINGERPRINTS.clear()
    try:
        target = package / "references" / "r.json"
        with counting_recipe() as calls:
            RP.resolve_runtime(task, project)
            RP.resolve_runtime(task, project)
            check_eq("L7 two calls in one process hash the package once", len(calls), 1)
            # a rewrite of ANOTHER length with the mtime put back: only the size tells (N3)
            old = target.stat()
            target.write_text('{"a": 1, "bb": 22}', encoding="utf-8")
            os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
            RP.resolve_runtime(task, project)
            check_eq("L7 a file rewritten with another length is hashed again", len(calls), 2)
            # the same length, a new time: only the mtime tells
            old = target.stat()
            target.write_text('{"a": 1, "bb": 33}', encoding="utf-8")
            os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns + 5_000_000_000))
            RP.resolve_runtime(task, project)
            check_eq("L7 a new mtime over the same length is hashed again", len(calls), 3)
            target.unlink()
            RP.resolve_runtime(task, project)
            check_eq("L7 a file that is gone is hashed again", len(calls), 4)
            (package / "scripts" / "extra.py").write_text("# new\n", encoding="utf-8")
            RP.resolve_runtime(task, project)
            check_eq("L7 a file added to the recipe is hashed again", len(calls), 5)
            RP.resolve_runtime(task, project)
            check_eq("L7 and an unchanged tree after that is a hit", len(calls), 5)
            # E21: a stat that fails is never cached, and the value is still the recipe's
            real_stat = Path.stat

            def failing(self, *args, **kwargs):      # only the signature's own stat fails; the walk and the read are the real ones
                if sys._getframe(1).f_code.co_name == "_package_fingerprint":
                    raise PermissionError("seam: stat refused")
                return real_stat(self, *args, **kwargs)
            Path.stat = failing
            try:
                a = RP._package_fingerprint(package)
                b = RP._package_fingerprint(package)
            finally:
                Path.stat = real_stat
            check_eq("L7 an unreadable signature recomputes every time (two calls, two hashes)", len(calls), 7)
            check_eq("L7 ... with the same value", a, b)
        # the seam K3 of test_release_fingerprint: a swapped recipe function is followed, never answered from memory
        saved = RF.package_fingerprint
        RF.package_fingerprint = lambda root=None, files=None: "SENTINEL"
        try:
            check_eq("L7 a replaced recipe function is followed", RP.resolve_runtime(task, project)["package_fingerprint"], "SENTINEL")
        finally:
            RF.package_fingerprint = saved
    finally:
        RP.package_root = held
        RP._FINGERPRINTS.clear()
        cleanup(project)
        cleanup(package)


def l7b_a_miss_walks_the_tree_once():
    """KILLS N9 (the recipe called without `files=`: the signature walked the tree and the hash walked it again, t-1329 B1)."""
    project = temp_project("qa-lpc-l7b-")
    package = mini_package()
    held, RP.package_root = RP.package_root, (lambda: package)
    RP._FINGERPRINTS.clear()
    walks = []
    real_walk = RF.recipe_files
    RF.recipe_files = lambda root=None: walks.append(str(root)) or real_walk(root)
    try:
        value = RP._package_fingerprint(package)
        check_eq("L7b a miss (the first call) walks the recipe tree exactly once", len(walks), 1)
        check_eq("L7b ... and the value is the recipe's", value, RF.package_fingerprint(package))
        walks.clear()
        RP._package_fingerprint(package)
        check_eq("L7b a hit walks it once too (the signature) and hashes nothing", len(walks), 1)
    finally:
        RF.recipe_files = real_walk
        RP.package_root = held
        RP._FINGERPRINTS.clear()
        cleanup(project)
        cleanup(package)


def l8_the_cache_does_not_change_the_value():
    project = temp_project("qa-lpc-l8-")
    package = mini_package()
    task = project / "qa-factory" / "artifacts" / "QA-1"
    task.mkdir(parents=True)
    held, RP.package_root = RP.package_root, (lambda: package)
    RP._FINGERPRINTS.clear()
    try:
        first = RP.resolve_runtime(task, project)["package_fingerprint"]
        second = RP.resolve_runtime(task, project)["package_fingerprint"]
        expected = RF.package_fingerprint(package)
        check_eq("L8 the first (computed) value is the recipe's", first, expected)
        check_eq("L8 the second (cached) value is the recipe's", second, expected)
        (package / "references" / "r.json").write_text('{"a": 2222}', encoding="utf-8")
        third = RP.resolve_runtime(task, project)["package_fingerprint"]
        check_eq("L8 after a change the value is the recipe's new one", third, RF.package_fingerprint(package))
        check("L8 ... and it differs from the old one", third != expected)
    finally:
        RP.package_root = held
        RP._FINGERPRINTS.clear()
        cleanup(project)
        cleanup(package)


# --- the gate's collect (L9-L12) -----------------------------------------------------------------------------------------

def gate_project(prefix, template, gate_rehearsal=None):
    """(project, task folder, config): a project whose `quiet` template is `template`, tests under `tests/`."""
    root = temp_project(prefix)
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    config["test_command_templates"] = {"quiet": template}
    if gate_rehearsal:
        config["gate_rehearsal"] = gate_rehearsal
    (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / "QA-1"
    task.mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}}), encoding="utf-8")
    use_project(root)
    return root, task, config


def rehearse_toolchain(task):
    rehearsal = gate_preflight.Rehearsal(task, "A")
    rehearsal.check_s5_toolchain()
    return rehearsal


PYTEST_TEMPLATE = f'"{sys.executable}" -m pytest -p no:cacheprovider'
THREE_TESTS = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n\n\ndef test_three():\n    pass\n"


def l9_the_gate_reads_the_ids_s5_reads():
    """KILLS N5 (the gate through a plain `subprocess.run` again: `collect_stdout` is `test_a.py: 3`, no id)."""
    if not HAVE_PYTEST:
        check("L9 SKIPPED: pytest is not importable in this interpreter (the key needs a real pytest, like test_node_ids)", True)
        return
    root, task, config = gate_project("qa-lpc-l9-", PYTEST_TEMPLATE)
    try:
        tests = root / "tests"
        (tests / "test_a.py").write_text(THREE_TESTS, encoding="utf-8")
        (tests / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        rehearsal = rehearse_toolchain(task)
        read = node_ids.parse_collected(rehearsal.collect_stdout)
        check_eq("L9 a project whose addopts carry -q: the gate read its three ids", len(read), 3)
        check_eq("L9 ... and raised nothing", rehearsal.findings, [])
        s5 = node_ids.collect(gate_preflight.collect_base(config), tests, 120)
        check_eq("L9 S5's collect of the same project gives the same list (AR-13/AR-15)", read, s5)
        # the negative control: the OLD path - the command the gate used to run, as it stood - sees counts, no ids
        old = subprocess.run(gate_preflight.collect_command(config), cwd=str(tests), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        check("L9 control: the old command line prints `file.py: N` on this fixture", "test_a.py: 3" in old.stdout, old.stdout[:200])
        check_eq("L9 control: and the one parser reads 0 ids from it", node_ids.parse_collected(old.stdout), [])
    finally:
        cleanup(root)


def l10_the_gate_branches_by_the_kind_of_the_failure():
    """KILLS N6 (a timeout read as `not_started`: the executor question for a sleeping runner)."""
    root, task, _config = gate_project("qa-lpc-l10a-", '"no-such-runner-xyz-1" pytest')
    try:
        rehearsal = rehearse_toolchain(task)
        found = [f for f in rehearsal.findings if f["check"] == "s5_toolchain"]
        statement, _options = gate_preflight.executor_question("no-such-runner-xyz-1", "the project command", [], rehearsal.next_stage)
        check_eq("L10 a runner that is not there: one finding", len(found), 1)
        check_eq("L10 ... the person's", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_eq("L10 ... in the executor question's own words (FR-7)", found[0]["message"], " ".join(statement.split()))
        check_eq("L10 ... naming the tool", found[0].get("tool"), "no-such-runner-xyz-1")
    finally:
        cleanup(root)
    root, task, _config = gate_project("qa-lpc-l10b-", f'"{sys.executable}" -m pytest', {"collect_timeout_s": 1})
    try:
        (root / "tests" / "pytest.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        rehearsal = rehearse_toolchain(task)
        found = [f for f in rehearsal.findings if f["check"] == "s5_toolchain"]
        check_eq("L10 a collect that never finishes: one finding", len(found), 1)
        check_eq("L10 ... the person's decision", found[0]["class"], gate_preflight.PERSON_DECIDES)
        check_in("L10 ... in the old words, with the limit", "did not finish within 1s", found[0]["message"])
        check_not_in("L10 ... and not the executor question", "is not available to me in this session", found[0]["message"])
    finally:
        cleanup(root)
    root, task, _config = gate_project("qa-lpc-l10c-", f'"{sys.executable}" -m pytest')
    held = node_ids.collect_output

    def odd(*_a, **_k):
        raise node_ids.CollectError("a kind nobody wrote a branch for", kind="from-the-future")
    node_ids.collect_output = odd
    try:
        rehearsal = rehearse_toolchain(task)
        found = [f for f in rehearsal.findings if f["check"] == "s5_toolchain"]
        check_eq("L10 an unknown kind is an unavailable step (the factory's own), never green and never a question",
                 [f["class"] for f in found], [gate_preflight.FACTORY_DEFECT])
    finally:
        node_ids.collect_output = held
        cleanup(root)


@contextlib.contextmanager
def launch_refused(error):
    """`subprocess.Popen` as `node_ids.run_bounded` sees it refuses to launch with `error` (the OS's own answer)."""
    real = node_ids.subprocess.Popen

    def refusing(*_a, **_k):
        raise error
    node_ids.subprocess.Popen = refusing
    try:
        yield
    finally:
        node_ids.subprocess.Popen = real


def l10d_only_a_missing_runner_is_the_executor_question():
    """KILLS N11 (any OSError of the launch read as `not_started`: a person is asked about an executor that is not missing, FR-3)."""
    for label, error, question in (("FileNotFoundError", FileNotFoundError(2, "No such file"), True),
                                   ("PermissionError", PermissionError(13, "Permission denied"), True),
                                   ("OSError [WinError 193]", OSError(8, "%1 is not a valid Win32 application"), False),
                                   ("OSError E2BIG", OSError(7, "Argument list too long"), False)):
        root, task, _config = gate_project("qa-lpc-l10d-", f'"{sys.executable}" -m pytest')
        try:
            with launch_refused(error):
                rehearsal = rehearse_toolchain(task)
            found = [f for f in rehearsal.findings if f["check"] == "s5_toolchain"]
            check_eq(f"L10d {label}: one finding", len(found), 1)
            want = gate_preflight.PERSON_DECIDES if question else gate_preflight.FACTORY_DEFECT
            check_eq(f"L10d {label}: {'the executor question, the person' if question else 'an unavailable step, the factory'}'s",
                     found[0]["class"], want)
            if not question:
                check_not_in(f"L10d {label}: and not the executor question", "is not available to me in this session", found[0]["message"])
        finally:
            cleanup(root)
        try:
            with launch_refused(error):
                node_ids.collect([sys.executable, "-m", "pytest"], ".", 5)
            got = "no error"
        except node_ids.CollectError as exc:
            got = exc.kind
        check_eq(f"L10d {label}: CollectError.kind", got, "not_started" if question else "launch_failed")


def l10e_a_quiet_template_costs_one_collect():
    """KILLS N12 (the template's own `-q` handed on: `collect_output` adds a second one, `-qq`, and collects again with `-v`, t-1329 F2)."""
    if not HAVE_PYTEST:
        check("L10e SKIPPED: pytest is not importable in this interpreter", True)
        return
    root, task, _config = gate_project("qa-lpc-l10e-", f'"{sys.executable}" -m pytest -q -p no:cacheprovider')
    real_run, runs = node_ids._run, []
    node_ids._run = lambda command, *a, **k: (runs.append(list(command)), real_run(command, *a, **k))[1]
    try:
        (root / "tests" / "test_a.py").write_text(THREE_TESTS, encoding="utf-8")
        rehearsal = rehearse_toolchain(task)
        check_eq("L10e a `quiet` template that says -q: ONE collect", len(runs), 1)
        check_eq("L10e ... with exactly one -q in it", [t for t in runs[0] if t in ("-q", "--quiet")] if runs else None, ["-q"])
        check_eq("L10e ... the gate read the three ids", len(node_ids.parse_collected(rehearsal.collect_stdout)), 3)
        check_eq("L10e ... and raised nothing", rehearsal.findings, [])
    finally:
        node_ids._run = real_run
        cleanup(root)
    # control: the template that carries `--quiet` is stripped too, and a project whose addopts carry -q still earns the retry
    # (the same as S5): that is a second collect on purpose, not the template's.
    root, task, _config = gate_project("qa-lpc-l10f-", f'"{sys.executable}" -m pytest --quiet -p no:cacheprovider')
    runs.clear()
    node_ids._run = lambda command, *a, **k: (runs.append(list(command)), real_run(command, *a, **k))[1]
    try:
        (root / "tests" / "test_a.py").write_text(THREE_TESTS, encoding="utf-8")
        (root / "tests" / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        rehearse_toolchain(task)
        check_eq("L10e control: --quiet in the template and -q in the addopts: the retry is S5's (two collects)", len(runs), 2)
    finally:
        node_ids._run = real_run
        cleanup(root)


def l11_collect_command_is_what_it_was():
    """KILLS N7 (`collect_command` no longer adds `-q`)."""
    def command(template, key="quiet"):
        return gate_preflight.collect_command({"test_command_templates": {key: template}})
    check_eq("L11 quiet: placeholder and its flag dropped, -q and --collect-only added",
             command('python -m pytest -m "<test-id>" --reruns 2'),
             ["python", "-m", "pytest", "--reruns", "2", "-q", "--collect-only"])
    check_eq("L11 suite: a template that already says -q is not given a second one",
             command("pytest -q <test-file>", "suite"), ["pytest", "-q", "--collect-only"])
    check_eq("L11 one_test: a wrapper stays, the id goes",
             command('poetry run pytest "<test-id>"', "one_test"), ["poetry", "run", "pytest", "-q", "--collect-only"])
    check_eq("L11 --quiet counts as -q", command("pytest --quiet", "suite"), ["pytest", "--quiet", "--collect-only"])
    check_eq("L11 a command that is not pytest is no collect", command("npx playwright test"), [])
    check_eq("L11 collect_base is the same command with nothing added",
             gate_preflight.collect_base({"test_command_templates": {"quiet": 'python -m pytest -m "<test-id>" --reruns 2'}}),
             ["python", "-m", "pytest", "--reruns", "2"])
    check_eq("L11 ... and [] when there is no pytest-shaped template", gate_preflight.collect_base({}), [])


def l12_a_warning_on_stderr_does_not_move_the_first_node():
    runner = "import sys\nsys.stderr.write({warn})\nsys.stderr.flush()\nsys.stdout.write('tests/test_a.py::test_one\\n'" \
             " 'tests/test_a.py::test_two\\n2 tests collected in 0.01s\\n')\n"
    firsts = []
    for warn in ("''", "'PytestWarning: a plugin said something\\n'"):
        root, task, _config = gate_project("qa-lpc-l12-", f'"{sys.executable}" "@RUNNER@" pytest')
        try:
            fake = root / "fake_pytest.py"
            fake.write_text(runner.format(warn=warn), encoding="utf-8")
            config_path = root / "qa-factory" / "config.json"
            config_path.write_text(config_path.read_text(encoding="utf-8").replace("@RUNNER@", fake.as_posix()), encoding="utf-8")
            rehearsal = rehearse_toolchain(task)
            firsts.append((gate_preflight.first_collected_node(rehearsal.collect_stdout), [f["check"] for f in rehearsal.findings]))
        finally:
            cleanup(root)
    check_eq("L12 stderr is one stream with stdout; the first node is the same with and without a warning before it",
             firsts[0], firsts[1])
    check_eq("L12 ... and it is the first id", firsts[1][0], "tests/test_a.py::test_one")
    check_eq("L12 ... with no finding", firsts[1][1], [])


# --- the door of stage_done (L13) ----------------------------------------------------------------------------------------

def l13_the_done_without_acceptance_door_is_story_step_finish():
    """KILLS N8 (the first of two dispatches taken as the door's id)."""
    root, task, controller = managed_story("qa-lpc-l13-")
    try:
        dispatch_s0(controller, "dS0")
        code, _out, err = run_stage_done("QA-1", "S0", "done", "qa-scout", "x", True)
        check_eq("L13 done over a stage the controller has not accepted is refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("L13 the old words that the driver's rows read stay at the head", "is a controller-managed stage and the controller has not accepted it", err)
        check_in("L13 the door is the command that writes the whole request, for THIS story", "story_step.py finish --task QA-1 ", err)
        check_in("L13 ... with the id of the stage's only open dispatch", "--dispatch-id dS0 ", err)
        check_not_in("L13 ... and the hand-built receipt is not taught any more", "--input <receipt>.json", err)
        check_in("L13 the person's word still passes it (waiver door)", "waiver.py --task QA-1 --stage S0", err)
        # the controller never lets a sequential story hold two open dispatches, so the second candidate is put into the
        # state the refusal reads (a repaired story can hold a running one and a returned one of the same stage)
        real_state = Controller.state

        def two_open(self, *a, **k):
            state = real_state(self, *a, **k)
            dispatches = dict(state.get("dispatches") or {})
            dispatches["dS0b"] = dict(dispatches.get("dS0") or {}, status=RETURNED)
            return dict(state, dispatches=dispatches)
        Controller.state = two_open
        try:
            code, _out, err = run_stage_done("QA-1", "S0", "done", "qa-scout", "x", True)
        finally:
            Controller.state = real_state
        check_eq("L13 two open dispatches of the stage: still refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("L13 ... and the id is a placeholder naming both, not a pick", "--dispatch-id <one of: dS0, dS0b>", err)
    finally:
        cleanup(root)


# --- CollectError.kind (L14) ---------------------------------------------------------------------------------------------

def l14_collect_errors_carry_their_kind():
    check_eq("L14 an old CollectError(msg) has no kind", node_ids.CollectError("m").kind, "")
    check_eq("L14 ... and an old CollectError(msg, head) keeps its head", node_ids.CollectError("m", "h").head, "h")
    for argv, kind in (([], "no_command"), (["no-such-runner-xyz-2", "pytest"], "not_started")):
        try:
            node_ids.collect(argv, ".", 5)
            got = "no error"
        except node_ids.CollectError as exc:
            got = exc.kind
        check_eq(f"L14 collect({argv!r}) raises kind {kind!r}", got, kind)
    root = temp_dir("qa-lpc-l14-")
    try:
        (root / "pytest.py").write_text("import sys, time\nmode = open('mode.txt').read()\n"
                                        "if mode == 'slow': time.sleep(60)\n"
                                        "if mode == 'broken': print('boom'); sys.exit(2)\n"
                                        "print('3 tests collected in 0.01s')\n", encoding="utf-8")
        for flag, kind in (("slow", "timeout"), ("broken", "exit"), ("unread", "unread")):
            (root / "mode.txt").write_text(flag, encoding="utf-8")
            try:
                node_ids.collect([sys.executable, "-m", "pytest"], root, 1 if flag == "slow" else 30)
                got = "no error"
            except node_ids.CollectError as exc:
                got = exc.kind
            check_eq(f"L14 a runner that {flag}: kind {kind!r}", got, kind)
        code, text = node_ids.collect_output([sys.executable, "-m", "pytest"], root, 30)
        check_eq("L14 collect_output returns the code and the text, and decides nothing", (code, "3 tests collected" in text), (0, True))
    finally:
        cleanup(root)


def main():
    l1_running_defers_the_render()
    l2_done_renders_once_and_clears_the_marker()
    l3_running_twice_never_renders()
    l4_a_refused_running_leaves_no_trace()
    l5_a_marker_that_cannot_be_written_is_one_line()
    l5b_a_failure_marker_of_the_refresh_is_kept()
    l6_done_and_halted_render_as_before()
    l7_the_fingerprint_is_hashed_once_while_the_files_are_unchanged()
    l7b_a_miss_walks_the_tree_once()
    l8_the_cache_does_not_change_the_value()
    l9_the_gate_reads_the_ids_s5_reads()
    l10_the_gate_branches_by_the_kind_of_the_failure()
    l10d_only_a_missing_runner_is_the_executor_question()
    l10e_a_quiet_template_costs_one_collect()
    l11_collect_command_is_what_it_was()
    l12_a_warning_on_stderr_does_not_move_the_first_node()
    l13_the_done_without_acceptance_door_is_story_step_finish()
    l14_collect_errors_carry_their_kind()
    finish("test_launch_path_costs")


if __name__ == "__main__":
    main()
