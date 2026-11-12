"""HF4-10: a quality receipt that nothing in the factory produces is not demanded (FR-5); what is not run is named in the window
and printed in the testing report (FR-4/FR-59). Keys K1a..K8 of spec t-1469 §5.5 over the recorded run-12586 windows
(`fixtures/run-12586-s5-quality/`, README.txt there)."""
import json
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CONTROLLER  # noqa: E402
import coverage_contract as CC  # noqa: E402
import report_facts as RF  # noqa: E402
import window_record as WR  # noqa: E402
from acceptance import validate_window  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-s5-quality"
FOUR = ["ticket_adapter", "test_repo", "vcs", "config_schema"]
PACKAGE = SCRIPTS.parent
REAL_FILE = WR.QUALITY_PRODUCERS_FILE


def producers(root: Path, mapping=None, raw=None):
    """Point the reader at a data file naming `mapping` as the producers (or holding `raw` text verbatim)."""
    path = root / "producers.json"
    path.write_text(raw if raw is not None else json.dumps({"schema_version": 1, "producers": mapping or {},
                                                            "why": {"no_producer": "no producer", "checked_at_s0": "ran at S0",
                                                                    "unknown_s0": "S0 unreadable"}}), encoding="utf-8")
    WR.QUALITY_PRODUCERS_FILE = path


def real_data():
    WR.QUALITY_PRODUCERS_FILE = REAL_FILE


def fixture(root: Path) -> tuple:
    """A copy of the recorded story in `root`: (project, task, windows by number)."""
    project = root / "project"
    shutil.copytree(FIXTURE / "project", project)
    task = project / "qa-factory" / "artifacts" / "TP1-12586"
    windows = {n: json.loads((task / "work" / "windows" / f"S5-qa-code-critic-{n}.json").read_text(encoding="utf-8"))
               for n in (2, 3, 4)}
    return project, task, windows


def quality_gaps(window, task) -> list:
    return [g for g in validate_window(window, task) if g.startswith("quality:")]


def the_shipped_data_and_the_recorded_windows():
    """K1a (the seam) and K0: the shipped data names no producer, so the four readiness ids are not demanded."""
    real_data()
    root = temp_dir("qa-quality-")
    try:
        project, task, windows = fixture(root)
        check_eq("K0: the shipped data file has no producer today", json.loads(REAL_FILE.read_text(encoding="utf-8"))["producers"], {})
        demanded, not_run, why = WR.demanded_quality_checks(FOUR, task)
        check_eq("K0: nothing is demanded", demanded, [])
        check_eq("K0: all four were checked at S0 (the readiness record holds them)",
                 not_run, [{"id": i, "why": "checked_at_s0"} for i in FOUR])
        check_in("K0: the reasons carry their words from data", "readiness step", why["checked_at_s0"])
        for n, window in windows.items():
            check_eq(f"K1a: window {n} of the run (four readiness ids) has no `quality:*` gap", quality_gaps(window, task), [])
        # the control: with the producers named the same windows DO owe them (the state before this change)
        producers(root, {i: "x.py" for i in FOUR})
        check_eq("K1a control: with a producer named for each, window 3 owes all four",
                 sorted(quality_gaps(windows[3], task)), sorted("quality:" + i for i in FOUR))
        real_data()
    finally:
        real_data()
        cleanup(root)


class AcceptedState:
    """`Controller(task).state()` as `window_of_ref` reads it: the accepted S5 dispatch that holds the recorded window and
    the digest of the window file as its evidence. Set `windows` ({dispatch id: (window, task-relative path)}) before use."""
    windows: dict = {}

    def __init__(self, task_root):
        self.root = Path(task_root)

    def state(self):
        import hashlib
        out = {}
        for ident, (window, ref) in self.windows.items():
            digest = hashlib.sha256((self.root / ref).read_bytes()).hexdigest()
            out[ident] = {"id": ident, "stage": "S5", "status": "accepted", "window": window,
                          "evidence_refs": [{"path": ref, "sha256": digest}]}
        return {"dispatches": out}


def own_probe(binding: dict, window: dict) -> tuple:
    """`(binding, ids)`: the OB-1 binding of the run narrowed to its first instance, its `probe_receipt_ref` pointed at that
    instance's own probe. The stand's binding was written on a later round than the window and names another receipt, which
    makes it false for a reason that is not this node's (the spec's 'false for another reason'); the quality fields are
    untouched."""
    first = binding["instance_ids"][0]
    item = next(i for i in window["instances"] if i["instance_id"] == first)
    return dict(binding, probe_receipt_ref=item["probe"]["evidence_ref"], instance_ids=[first]), [first]


def witnessed(task, binding, ids, window, ref) -> bool:
    """`coverage_contract.witnessed_binding` over a state in which `window` (the file at `ref`) is the accepted window."""
    import acceptance
    real, CONTROLLER.Controller = CONTROLLER.Controller, AcceptedState
    real_validate = acceptance.validate_window
    AcceptedState.windows = {window["reviewer_dispatch_id"]: (window, ref)}
    # the recorded evidence files (run blocks, receipts) are not copied into the fixture: the other gaps of the window are
    # not this key's question, so only its `quality:*` gaps are read (the quality branch is what K1b/K3 hold)
    acceptance.validate_window = lambda w, r: [g for g in real_validate(w, r) if g.startswith("quality:")]
    try:
        return CC.witnessed_binding(task, dict(binding, review_receipt_ref=ref), ids)
    finally:
        CONTROLLER.Controller = real
        acceptance.validate_window = real_validate


def the_binding_of_the_run_needs_no_quality_field():
    """K1b (B10-1): the OB-1 binding of the run, plus ONLY the receipt ref, is witnessed when nothing is demanded."""
    real_data()
    root = temp_dir("qa-quality-")
    try:
        project, task, windows = fixture(root)
        binding = json.loads((FIXTURE / "binding-OB-1.json").read_text(encoding="utf-8"))
        binding, ids = own_probe(binding, windows[2])
        ref = "work/windows/S5-qa-code-critic-2.json"
        check_eq("K1b: the binding carries no quality field", [k for k in binding if k.startswith("quality")], [])
        check_eq("K1b: nothing demanded -> the branch of quality passes with neither refs nor reason",
                 witnessed(task, binding, ids, windows[2], ref), True)
        check_eq("K1b: a ref to a receipt that is not owed is false",
                 witnessed(task, dict(binding, quality_receipt_refs=["vcs"]), ids, windows[2], ref), False)
        producers(root, {i: "x.py" for i in FOUR})
        check_eq("K1b control: with the four demanded, the same binding is false for quality",
                 witnessed(task, binding, ids, windows[2], ref), False)
    finally:
        real_data()
        cleanup(root)


def the_data_decides_and_the_error_goes_toward_demanding():
    """K3 (a producer keeps the demand alive) and K4 (inconvenient inputs)."""
    root = temp_dir("qa-quality-")
    try:
        project, task, windows = fixture(root)
        producers(root, {"lint": "lint_receipt.py"})
        check_eq("K3: `lint` with a producer is demanded", WR.demanded_quality_checks(["lint", "vcs"], task)[0], ["lint"])
        window = dict(windows[3], required_quality_checks=["lint"])
        check_eq("K3: and stays a gap of the window", quality_gaps(window, task), ["quality:lint"])
        binding = json.loads((FIXTURE / "binding-OB-1.json").read_text(encoding="utf-8"))
        window2 = dict(windows[2], required_quality_checks=["lint"])
        (task / "work/windows/lint.json").write_text(json.dumps(window2), encoding="utf-8")
        binding, ids = own_probe(binding, window2)
        ref = "work/windows/lint.json"
        check_eq("K3: a binding without `quality_receipt_refs` is false while `lint` is demanded",
                 witnessed(task, binding, ids, window2, ref), False)
        producers(root, {})
        check_eq("K3 control: the same binding and window, no producer for `lint` -> witnessed",
                 witnessed(task, binding, ids, window2, ref), True)
        producers(root, {"lint": "lint_receipt.py"})
        # K4: exact match, no normalisation
        check_eq("K4: `Lint` is not `lint`: not demanded, named", WR.demanded_quality_checks(["Lint"], task)[:2],
                 ([], [{"id": "Lint", "why": "no_producer"}]))
        check_eq("K4: `lint ` (a blank) is not `lint` either", WR.demanded_quality_checks(["lint "], task)[0], [])
        # an id that is no string is demanded, as written, and raises nothing
        got = WR.demanded_quality_checks([{"id": "lint"}, 7, None, "lint"], task)
        N = WR.NON_STRING_ID
        check_eq("K4: ids that are no strings stay demanded, as one normalised string", got[0],
                 [N + '{"id": "lint"}', N + "7", N + "null", "lint"])
        check_eq("K4: ... and the gate over them raises nothing", quality_gaps(dict(windows[3], required_quality_checks=[{"id": "lint"}]), task),
                 ['quality:' + N + '{"id": "lint"}'])
        # F1: written -> read back. The writer's output (strings) is read by the SAME reader and demands every id again
        for recorded in ([7], [{"id": "lint"}], [{"id": {"deep": [1, 2]}}, 5, None, True], ["vcs", 7]):
            first = WR.demanded_quality_checks(recorded, task)
            again = WR.demanded_quality_checks(first[0], task)
            check_eq(f"F1: {recorded!r} written and read back demands the same ids", again[0], first[0])
            check_eq("F1: ... and the second reading (the written window) has nothing left over for `not_run`", again[1], [])
            window = dict(windows[3], required_quality_checks=first[0])
            check_eq(f"F1: the window validator demands `quality:*` for each id of {recorded!r}",
                     sorted(quality_gaps(window, task)), sorted("quality:" + i for i in first[0]))
            problems: list = []
            state = {"required_quality_checks": recorded, "source_revision": "src-1"}
            CONTROLLER.Controller._s5_collect(types.SimpleNamespace(), {"scope": list(window["scope_instances"]), "input_hash": window["input_hash"]},
                                              {}, state, dict(window, source_revision="src-1"), problems)
            check_eq(f"F1: `_s5_collect` does not refuse the window written from {recorded!r}",
                     [str(m) for _c, m in problems if "quality" in str(m)], [])
        for label, raw in (("a file that is not JSON", "{nope"), ("`producers` a list", '{"producers": ["lint"]}'),
                           ("`producers` missing", "{}"), ("an empty file", "")):
            producers(root, raw=raw)
            check_eq(f"K4: {label} -> the requirement stands as recorded", WR.demanded_quality_checks(["vcs", "lint"], task)[:2],
                     (["vcs", "lint"], []))
        WR.QUALITY_PRODUCERS_FILE = root / "absent.json"
        check_eq("K4: a data file that is absent -> as recorded", WR.demanded_quality_checks(["vcs"], task)[:2], (["vcs"], []))
        real_data()
        for recorded in (None, [], "vcs", {"a": 1}):
            check_eq(f"K4: a state value {recorded!r} that is no list of ids demands nothing and raises nothing",
                     WR.demanded_quality_checks(recorded, task)[0], [])
    finally:
        real_data()
        cleanup(root)


class StandIn:
    """`controller.Controller(task_root).state()` for `window_record.build`: one critic dispatch, the quality ids of the story."""
    required = FOUR

    def __init__(self, task_root):
        self.store = types.SimpleNamespace(root=task_root)

    def state(self):
        return {"dispatches": {"S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1", "role": "qa-code-critic", "stage": "S5",
                                                       "scope": ["TC-1"], "input_hash": "h"}},
                "required_quality_checks": list(self.required), "source_revision": "src-1"}

    def _cases_without_instances(self):
        return ["TC-1"]


def the_writer_and_the_reader_agree():
    """K2 (writer -> reader) and K5 (the field is always written; the receipt carries it)."""
    real_data()
    root = temp_dir("qa-quality-")
    try:
        project, task, windows = fixture(root)
        (task / "work" / "automation-manifest.json").write_text(json.dumps({"schema_version": 2, "tests": []}), encoding="utf-8")
        real, CONTROLLER.Controller = CONTROLLER.Controller, StandIn
        try:
            built = {}
            for label, required in (("four", FOUR), ("four and lint", FOUR + ["lint"]), ("none", [])):
                StandIn.required = required
                built[label] = WR.build(task, "S5-qa-code-critic-1")[0]
        finally:
            CONTROLLER.Controller = real
            StandIn.required = FOUR
        four = built["four"]
        check_eq("K5: the window demands nothing", four["required_quality_checks"], [])
        check_eq("K5: and names the four as run by S0", four["quality_not_run"], [{"id": i, "why": "checked_at_s0"} for i in FOUR])
        check_eq("K5: an id with no readiness result is `no_producer`", [r for r in built["four and lint"]["quality_not_run"] if r["id"] == "lint"],
                 [{"id": "lint", "why": "no_producer"}])
        check_eq("K5: with nothing recorded the key is still written, empty", built["none"].get("quality_not_run"), [])
        check_eq("K5: `quality_receipts` stays an empty list", four["quality_receipts"], [])
        check_not_in("F3: the receipt does not carry `quality_not_run` (not part of its immutable identity)", "quality_not_run",
                     WR.receipt_dict(four))
        check_not_in("F3: a window of an older build has none either", "quality_not_run", WR.receipt_dict(windows[3]))
        # F3: the same window rebuilt after the readiness record changed -> the receipt already on disk is no collision
        readiness = project / "qa-factory" / "state" / "readiness.json"
        record = json.loads(readiness.read_text(encoding="utf-8"))
        first_ref = WR.write_review_receipt(task, four, "S5-qa-code-critic-1")
        del record["capabilities"]["vcs"]
        readiness.write_text(json.dumps(record), encoding="utf-8")
        real, CONTROLLER.Controller = CONTROLLER.Controller, StandIn
        try:
            StandIn.required = FOUR
            rebuilt = WR.build(task, "S5-qa-code-critic-1")[0]
        finally:
            CONTROLLER.Controller = real
        check_eq("F3: the changed record changes the window's `quality_not_run`", [r for r in rebuilt["quality_not_run"] if r["id"] == "vcs"],
                 [{"id": "vcs", "why": "no_producer"}])
        check_eq("F3: ... and the rebuilt receipt is the same one, no collision", WR.write_review_receipt(task, rebuilt, "S5-qa-code-critic-1"),
                 first_ref)
        # K2: the reader of the controller, over the written window and over a window of 0.10.3 (the four ids)
        state = {"required_quality_checks": list(FOUR), "source_revision": "src-1"}

        def omitted(window):
            problems: list = []
            d = {"scope": list(window["scope_instances"]), "input_hash": window["input_hash"]}
            CONTROLLER.Controller._s5_collect(types.SimpleNamespace(), d, {}, state, window, problems)
            return [str(m) for _cls, m in problems if "quality" in str(m)]
        written = dict(windows[3], required_quality_checks=four["required_quality_checks"], quality_not_run=four["quality_not_run"],
                       source_revision="src-1")
        check_eq("K2: the window the writer wrote does not 'omit project quality checks'", omitted(written), [])
        check_eq("K2: a 0.10.3 window (the four ids) against the same state does not either (N10-2)",
                 omitted(dict(windows[3], source_revision="src-1")), [])
        check_eq("K2 control: a window that dropped a DEMANDED id is still refused", (producers(root, {i: "x.py" for i in FOUR}), omitted(
            dict(windows[3], source_revision="src-1", required_quality_checks=FOUR[:2])))[1],
                 ["window cannot omit project quality checks"])
    finally:
        real_data()
        cleanup(root)


def the_project_is_the_stories_own():
    """F5: the readiness record is read from the project `runtime_paths.project_for_task` names for the story, not from a marker
    above the story's folder (a story whose artifact root lies outside its project has none above it)."""
    import runtime_paths as RP
    real_data()
    root = temp_dir("qa-quality-")
    real = RP.project_for_task
    try:
        project, task, windows = fixture(root)
        outside = root / "elsewhere" / "TP1-12586"
        outside.mkdir(parents=True)
        check_eq("F5 control: nothing above the story's folder is a project", RP.nearest_project(outside), None)
        check_eq("F5: without the resolver the record cannot be found", WR._s0_checked_names(outside, None), None)
        RP.project_for_task = lambda task_root, hint=None: project
        check("F5: the story's own project is the resolver's answer", set(FOUR) <= (WR._s0_checked_names(outside, None) or set()))
        RP.project_for_task = real
        check_eq("F5: ... the resolver's refusal reads as an unknown record, not an exception",
                 WR.demanded_quality_checks(["vcs"], outside)[1], [{"id": "vcs", "why": "unknown_s0"}])
    finally:
        RP.project_for_task = real
        real_data()
        cleanup(root)


def the_gap_names_its_producer():
    """K6 (the door names the script of the data, FR-2). `_code_review_refusal` holds no quality text: the window gap does."""
    root = temp_dir("qa-quality-")
    try:
        producers(root, {"lint": "lint_receipt.py"})
        check_in("K6: the door of a quality gap names the producer script", "lint_receipt.py", WR._explain("quality:lint", []))
        check_in("K6: ... and still the person's word", "not receipted", WR._explain("quality:lint", []))
        check_not_in("K6: a check without a producer gets no invented script", "lint_receipt.py", WR._explain("quality:vcs", []))
    finally:
        real_data()
        cleanup(root)


def the_report_names_what_was_not_run():
    """K8 (reader of the report, B10-2) and the seam: the three windows of the run through the gate and the report."""
    real_data()
    root = temp_dir("qa-quality-")
    try:
        project, task, windows = fixture(root)
        def line(t):
            unknown: dict = {}
            rows = RF._quality_not_run(t, project, unknown)
            return RF._r_quality_not_run({"unknown": unknown, "quality_not_run": rows})
        check_eq("K8: the run as recorded (four ids, all run by S0): no line", line(task), "")
        # the seam: one check S0 did not run -> printed; the others stay silent; the gate has no quality gap in any window
        readiness = project / "qa-factory" / "state" / "readiness.json"
        record = json.loads(readiness.read_text(encoding="utf-8"))
        del record["capabilities"]["vcs"]
        readiness.write_text(json.dumps(record), encoding="utf-8")
        for n, window in windows.items():
            check_eq(f"SEAM: window {n} -> no `quality:*` gap", quality_gaps(window, task), [])
        check_eq("SEAM: the report prints the line for the one S0 did not run",
                 line(task), "Quality checks the factory did not run: vcs (" + json.loads(REAL_FILE.read_text(encoding="utf-8"))["why"]["no_producer"] + ")\n")
        # lint recorded in a window of the old build (no `quality_not_run` key) -> the line is still there
        old = dict(windows[3], required_quality_checks=FOUR + ["lint"])
        (task / "work/windows/S5-qa-code-critic-3.json").write_text(json.dumps(old), encoding="utf-8")
        check_in("K8: a 0.10.3 window with `lint` and no `quality_not_run` still gives the line", "lint (recorded at initialize",
                 line(task))
        check_eq("K8: ... ids once, in order of first appearance", line(task).count("vcs ("), 1)
        shutil.copy(FIXTURE / "project/qa-factory/state/readiness.json", readiness)
        check_eq("K8: the lint line alone (the four were run by S0)", line(task),
                 "Quality checks the factory did not run: lint (" + json.loads(REAL_FILE.read_text(encoding="utf-8"))["why"]["no_producer"] + ")\n")
        # the readiness record deleted: the four ids are printed as unknown
        readiness.unlink()
        out = line(task)
        for i in FOUR:
            check_in(f"K8: no readiness record -> `{i}` is printed", i + " (the record of the readiness step could not be read)", out)
        # a window that cannot be read is named, not dropped
        (task / "work/windows/S5-qa-code-critic-4.json").write_text("{broken", encoding="utf-8")
        unknown: dict = {}
        RF._quality_not_run(task, project, unknown)
        check_in("K8: an unreadable window is an `unknown`, not silence", "S5-qa-code-critic-4.json", unknown.get("quality_not_run", ""))
        # F4: one unreadable window does not hide the ids the readable ones already gave
        shutil.copy(FIXTURE / "project/qa-factory/state/readiness.json", readiness)
        printed = line(task)
        check_in("F4: the known unrun id is still printed", "Quality checks the factory did not run: lint (", printed)
        check_in("F4: ... and the unreadable window is named beside it", "S5-qa-code-critic-4.json", printed)
        check_eq("F4: two lines, the known one first", printed.count("\n"), 2)
        # the whole report: the line sits in the regression block
        shutil.copy(FIXTURE / "project/qa-factory/state/readiness.json", readiness)
        (task / "work/windows/S5-qa-code-critic-4.json").write_text(json.dumps(windows[4]), encoding="utf-8")
        facts = RF.build(task, project)
        check_eq("K8: build carries the fact", facts["quality_not_run"], [{"id": "lint", "why": "no_producer"}])
        check_in("K8: the report block carries the line", "Quality checks the factory did not run: lint (",
                 RF.render(facts)["regression"])
    finally:
        real_data()
        cleanup(root)


def the_texts_say_it():
    """K7: DOC-WITNESS - the keys are quoted verbatim from the DoD before the run; the negative control removes one."""
    keys = {
        "skills/qa-story/phases/s0.md": ["references/quality-receipt-producers.json", "not the readiness check IDs"],
        "references/controller-api.md": ["`required_quality_checks` (quality check IDs with a producer)"],
        "references/artifact-contract-automation.md": ["WINDOW's `required_quality_checks`", "neither `quality_receipt_refs` nor"],
        "references/slices/qa-automator/artifact-contract-automation.md": ["WINDOW's `required_quality_checks`"],
        "references/slices/qa-code-critic/artifact-contract-automation.md": ["WINDOW's `required_quality_checks`"],
    }

    def missing(table, text_of):
        return [(f, k) for f, ks in table.items() for k in ks if " ".join(k.split()) not in " ".join(text_of(f).split())]

    read = lambda f: (PACKAGE / f).read_text(encoding="utf-8")  # noqa: E731
    check_eq("K7: every key is in its text", missing(keys, read), [])
    check_eq("K7 negative control: a key that is not there is reported",
             missing({"references/controller-api.md": ["a sentence nobody wrote"]}, read),
             [("references/controller-api.md", "a sentence nobody wrote")])


def main():
    the_shipped_data_and_the_recorded_windows()
    the_binding_of_the_run_needs_no_quality_field()
    the_data_decides_and_the_error_goes_toward_demanding()
    the_writer_and_the_reader_agree()
    the_project_is_the_stories_own()
    the_gap_names_its_producer()
    the_report_names_what_was_not_run()
    the_texts_say_it()
    finish("quality demand")


if __name__ == "__main__":
    main()
