"""PC-4 (t-2181 §1.3 C1-C6, S9, S10, B5; joint plan t-2277 J-C5): the S5 exit checks of the sides of a story.

`s5_precheck.check_sides` reads `tests[].sides`, `then_bindings[].about`, `provisional[]` and the `pending_implementation`
rows against the sides reader (`contract.story_sides`) and the run blocks. Each check has one positive and one negative case
here; the excuse of a run (`acceptance.pending_instances`, C5) is proved through `check_run_mapping` as well. DATA only: no
case asks whether a placeholder is reasonable - that stays the code critic's.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import first_look as FL  # noqa: E402
import grounding_table as GT  # noqa: E402
import s5_precheck as P  # noqa: E402

TICKET = "QA-600"
TEST_FILE = "tests/test_ui.py"
HOME_FILE = "tests/pages.py"
MARKED = 'LOGIN = "#login"  # qa-provisional: P-1\n'


def sides_of(**reality) -> dict:
    return C.story_sides({"sides": {name: {"reality": value, "deliverable": True, "source": "launch"}
                                    for name, value in reality.items()}})


def row(iid="test_a", case="TC-1", sides=None) -> dict:
    out = {"instance_id": iid, "case": case, "covers": [case], "file": TEST_FILE, "status": "Draft"}
    if sides is not None:
        out["sides"] = sides
    return out


def prov(pid="P-1", status="open", side="backend", kind="side_substitute", **over) -> dict:
    out = {"id": pid, "kind": kind, "what": "a mock", "assumed_from": "requirement:R-1", "settles_on": side,
           "home": {"file": HOME_FILE, "line_hint": 1}, "dependents": [{"case": "TC-1", "then": 1}], "status": status}
    out.update(over)
    return out


def story(project: Path, manifest: dict, pipeline=None, blocks=(), home=MARKED) -> Path:
    task = project / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "run-blocks").mkdir(parents=True, exist_ok=True)
    for old in (task / "work" / "run-blocks").glob("*.json"):       # each call is a fresh story: no block of the last one
        old.unlink()
    manifest.setdefault("then_bindings", [{"case": "TC-1", "then": 1, "instance_id": "test_a"}])
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps(pipeline or {}), encoding="utf-8")
    (project / "tests").mkdir(exist_ok=True)
    (project / TEST_FILE).write_text("def test_a():\n    pass\n\n\ndef test_b():\n    pass\n", encoding="utf-8")
    (project / HOME_FILE).write_text(home, encoding="utf-8")
    for i, block in enumerate(blocks):
        (task / "work" / "run-blocks" / f"2026110{i}T000000Z-b{i}.json").write_text(json.dumps(block), encoding="utf-8")
    return task


def found(task: Path, sides: dict, manifest=None) -> list:
    manifest = manifest if manifest is not None else json.loads(
        (task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    out: list = []
    P.check_sides(manifest, sides, task, out)
    return out


def tags(findings: list) -> list:
    return [P._finding_tag(f) for f in findings]


def with_tag(findings: list, start: str) -> list:
    return [t for t in tags(findings) if t.startswith(start)]


def block(bid="r1", results=(("test_a", "passed"),), **over) -> dict:
    out = {"block_id": bid, "results": [{"instance_id": i, "status": s} for i, s in results]}
    out.update(over)
    return out


def c1_c2() -> None:
    project = temp_project("qa-sides-c1-")
    use_project(project)
    try:
        two = sides_of(ui="real", backend="absent")
        task = story(project, {"tests": [row()]})
        check_eq("C1 negative: a test with no `sides` on a story with a non-real side is a finding by the tag",
                 with_tag(found(task, two), P.SIDES_UNDECLARED), ["sides-undeclared-test_a"])
        task = story(project, {"tests": [row(sides={})]})
        check_eq("C1 positive: an explicit {} is legal", found(task, two), [])
        task = story(project, {"tests": [row()], "unresolved": [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["x"]}]})
        check_eq("TEMPORAL: a story with no `pipeline.sides` record and no provisional rows is read exactly as before - nothing",
                 found(task, C.story_sides({})), [])
        task = story(project, {"tests": [row(sides={"UI": "real"})]})
        check_eq("C2 negative: a side name is compared EXACTLY (`UI` is not `ui`)",
                 with_tag(found(task, two), "sides-name-"), ["sides-name-test_a-UI"])
        task = story(project, {"tests": [row(sides={"ui": "real"})],
                               "then_bindings": [{"case": "TC-1", "then": 1, "about": ["ui", "backned"]}]})
        check_eq("C2 negative: `about` names a side the story does not have",
                 with_tag(found(task, two), "about-name-"), ["about-name-TC-1-1-backned"])
        task = story(project, {"tests": [row(sides={"ui": "real", "backend": "absent"})],
                               "then_bindings": [{"case": "TC-1", "then": 1, "about": ["ui", "backend"]}]})
        check_eq("C2 positive: exact names in `sides` and `about`", found(task, two), [])
    finally:
        cleanup(project)


def c3_c4() -> None:
    project = temp_project("qa-sides-c3-")
    use_project(project)
    try:
        two = sides_of(ui="real", backend="substituted")

        def one(**over):
            return story(project, {"tests": [row(sides={"backend": "substituted"})], "provisional": [prov(**over)]})

        check_eq("C3 positive: a well-formed open row with its marker found", found(one(), two), [])
        check_eq("C3 negative: a kind that is not in the kinds file",
                 with_tag(found(one(kind="made_up"), two), "provisional-kind-"), ["provisional-kind-P-1"])
        check_eq("C3 negative: `settles_on` is not a side of the story",
                 with_tag(found(one(side="cloud"), two), "provisional-side-"), ["provisional-side-P-1"])
        check_eq("C3 negative: a dependent that is no (case, Then) of then_bindings",
                 with_tag(found(one(dependents=[{"case": "TC-9", "then": 4}]), two), "provisional-dependent-"),
                 ["provisional-dependent-P-1-TC-9"])
        task = one()
        (project / HOME_FILE).write_text("LOGIN = 1\n", encoding="utf-8")
        check_eq("C3 negative: the home file holds no marker", with_tag(found(task, two), "provisional-home-"),
                 ["provisional-home-P-1"])
        task = one(home={"file": "tests/gone.py", "line_hint": 1})
        check_eq("C3 negative: the home file does not exist", with_tag(found(task, two), "provisional-home-"),
                 ["provisional-home-P-1"])
        # C4: a marker with no row; a marker that moved
        task = story(project, {"tests": [row(sides={"backend": "substituted"})], "provisional": []})
        (project / TEST_FILE).write_text("def test_a():\n    pass\n# qa-provisional: P-7\n", encoding="utf-8")
        check_eq("C4 negative: a marker in a test file with no provisional[] row",
                 with_tag(found(task, two), "provisional-marker-"), ["provisional-marker-P-7"])
        task = one()
        check_eq("C4 positive: the marker has its row (home file marker is the row's home)", found(task, two), [])
        before = C.marked_line_hash(project, HOME_FILE, "P-1")[0]
        (project / HOME_FILE).write_text("# an edit above\n" + MARKED, encoding="utf-8")
        check_eq("C4 / E-P2: the marked line moved one line - no finding (the home is found by its marker)",
                 found(task, two), [])
        check_eq("E-P2: and the hash of the marked line is the same wherever it is",
                 C.marked_line_hash(project, HOME_FILE, "P-1")[0], before)
    finally:
        cleanup(project)


def c5_and_pending() -> None:
    project = temp_project("qa-sides-c5-")
    use_project(project)
    try:
        pending_row = {"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]}
        absent = sides_of(ui="real", backend="absent")
        items = [{"instance_id": "test_a"}]
        manifest = {"tests": [row(sides={"backend": "absent"})], "unresolved": [pending_row]}
        check_eq("C5 positive: the row names it, the test declares an absent side, the reader says absent",
                 sorted(AC.pending_instances(manifest, items, {"TC-1": ["test_a"]}, absent)), ["test_a"])
        check_eq("C5 positive: manifest-only mode (no sides reader) checks the first two conditions",
                 sorted(AC.pending_instances(manifest, items)), ["test_a"])
        check_eq("C5 negative: the author says absent, the reader says real - not excused",
                 AC.pending_instances(manifest, items, None, sides_of(ui="real", backend="real")), {})
        mixed = {"tests": [row(sides={"ui": "real", "backend": "substituted"})], "unresolved": [pending_row]}
        check_eq("C5 negative: real + substituted sides, a pending row: not excused",
                 AC.pending_instances(mixed, items, None, sides_of(ui="real", backend="substituted")), {})
        check_eq("C5 negative: a whole-case row with no instance_ids excuses no instance (E-X2)",
                 AC.pending_instances({"tests": manifest["tests"], "unresolved": [{"case": "TC-1", "reason": "pending_implementation"}]},
                                      items, None, absent), {})
        check_eq("C5 negative: an `about`-only declaration with no `sides` is not an excuse",
                 AC.pending_instances({"tests": [row()], "unresolved": [pending_row]}, items, None, absent), {})

        # the S5 exit: an instance on real + substituted sides with no run is refused even with a pending row
        two = sides_of(ui="real", backend="substituted")
        task = story(project, mixed, {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "substituted"}}})
        result = P.run(task)
        check_in("C5: real + substituted with a pending row and no run: the run mapping still refuses it",
                 "test_a", " ".join(f["message"] for f in result["findings"] if f["check"] == "run_mapping"))
        check_eq("C5: and the sides check names the row", with_tag(found(task, two), "pending-not-excused-"),
                 ["pending-not-excused-test_a"])
        # all real: a pending row on an instance whose sides are all real is refused
        all_real = sides_of(ui="real", backend="real")
        task = story(project, {"tests": [row(sides={"ui": "real"})], "unresolved": [pending_row]},
                     {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "real"}}})
        check_eq("C5: a pending row on an instance whose sides are all real is refused",
                 with_tag(found(task, all_real), "pending-not-excused-"), ["pending-not-excused-test_a"])
        # absent: excused from the run mapping, and ONLY from it
        task = story(project, manifest, {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "absent"}}})
        result = P.run(task)
        check_eq("C5 positive / B1: an absent side excuses the run mapping, and the WHOLE exit has no finding (the pending row with "
                 "`instance_ids` is not `both-lists`)", result["findings"], [])
        # B1: a GREEN instance named by a pending row is a contradiction, the twin of blocked-but-green
        task = story(project, {"tests": [{**row(sides={"backend": "absent"}), "status": "green"}], "unresolved": [pending_row]},
                     {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "absent"}}})
        check_in("B1: a green tests[] row of a pending instance is `pending-but-green`", "pending-but-green",
                 " ".join(P._finding_tag(f) for f in P.run(task)["findings"]))
        check_eq("C5: the pending row on an absent side is accepted by the sides check", found(task, absent), [])
        task = story(project, {**manifest, "provisional": [prov(kind="nope")]},
                     {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "absent"}}})
        result = P.run(task)
        check_eq("POSITIONAL: a pending instance never excuses C3 - the kind finding stands beside the excused run",
                 (with_tag(result["findings"], "provisional-kind-"), [f for f in result["findings"] if f["check"] == "run_mapping"]),
                 (["provisional-kind-P-1"], []))
    finally:
        cleanup(project)


def scope_of_a_window() -> None:
    """B5: `check_sides(..., scope)` judges only the tests, Thens, pending rows and provisional rows of the window; a provisional row
    with no readable dependent is judged in every window; `scope=None` is the whole-story read."""
    project = temp_project("qa-sides-scope-")
    use_project(project)
    try:
        two = sides_of(ui="real", backend="absent")
        pipeline = {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "absent"}}}
        manifest = {"tests": [row(sides={"backend": "absent"}), row(iid="test_b", case="TC-2")],
                    "then_bindings": [{"case": "TC-1", "then": 1, "instance_id": "test_a"},
                                      {"case": "TC-2", "then": 1, "instance_id": "test_b", "about": "ui"}]}
        task = story(project, manifest, pipeline)
        window = {"TC-1": ["test_a"]}
        got: list = []
        P.check_sides(manifest, two, task, got, window)
        check_eq("B5: a TC-1 window is not refused over the undeclared test or the malformed `about` of TC-2", got, [])
        got = []
        P.check_sides(manifest, two, task, got, {"TC-2": ["test_b"]})
        check_eq("B5: the TC-2 window finds its own two defects", sorted(tags(got)),
                 ["about-shape-TC-2-1", "sides-undeclared-test_b"])
        check_eq("B5: scope=None is the whole-story read (both windows' findings)", sorted(tags(found(task, two, manifest))),
                 ["about-shape-TC-2-1", "sides-undeclared-test_b"])
        # provisional rows: owned by their dependents, and a row nobody owns is judged in every window
        owned = {**manifest, "provisional": [prov(kind="nope", dependents=[{"case": "TC-2", "then": 1}])]}
        task = story(project, owned, pipeline)
        got = []
        P.check_sides(owned, two, task, got, window)
        check_eq("B5: a row whose dependent is TC-2 is not judged in the TC-1 window", with_tag(got, "provisional-kind-"), [])
        orphan = {**manifest, "provisional": [prov(kind="nope", dependents=[])]}
        task = story(project, orphan, pipeline)
        got = []
        P.check_sides(orphan, two, task, got, window)
        check_eq("B5: a dependent-less row is judged in the TC-1 window too (fail-closed)", with_tag(got, "provisional-kind-"),
                 ["provisional-kind-P-1"])
        # a pending row of another window's case is not read here either
        elsewhere = {"tests": [row(sides={"backend": "absent"}), row(iid="test_b", case="TC-2", sides={"ui": "real"})],
                     "unresolved": [{"case": "TC-2", "reason": "pending_implementation", "instance_ids": ["test_b"]}]}
        task = story(project, elsewhere, pipeline)
        got = []
        P.check_sides(elsewhere, two, task, got, window)
        check_eq("B5: the pending row of TC-2 (not excused) is not named in the TC-1 window", with_tag(got, "pending-not-excused-"), [])
        check_eq("B5: and is named when its own window is asked", with_tag(found(task, two, elsewhere), "pending-not-excused-"),
                 ["pending-not-excused-test_b"])
    finally:
        cleanup(project)


def home_hash_root_is_the_writers() -> None:
    """F8: the marker file is looked up under `hooklib.project_root()` - the root `manifest_put` hashes against - not under a walk
    of the ancestors of the story."""
    mine = temp_project("qa-sides-root-a-")
    other = temp_project("qa-sides-root-b-")
    try:
        two = sides_of(ui="real", backend="substituted")
        use_project(mine)
        task = story(mine, {"tests": [row(sides={"backend": "substituted"})], "provisional": [prov()]})
        (other / "tests").mkdir(exist_ok=True)
        (other / HOME_FILE).write_text(MARKED, encoding="utf-8")
        (mine / HOME_FILE).unlink()
        check_eq("F8: the home file is only under another project, and the writer's root is this one: the row is refused",
                 with_tag(found(task, two), "provisional-home-"), ["provisional-home-P-1"])
        use_project(other)
        check_eq("F8: with the writer's root on the project that holds the file, the same story finds the marker",
                 with_tag(found(task, two), "provisional-home-"), [])
    finally:
        cleanup(mine)
        cleanup(other)


def one_pending_reader() -> None:
    """F9: one pending-row filter and one alias map (the FIRST row wins on a repeated alias)."""
    first, second = row(sides={"backend": "absent"}), {**row(), "file": "tests/test_other.py"}
    manifest = {"tests": [first, second],
                "unresolved": [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]},
                               {"case": "TC-2", "reason": "pending_implementation"},
                               {"case": "TC-3", "reason": "pending_implementation", "instance_ids": [" "]},
                               {"case": "TC-4", "reason": "blocked_by_env", "instance_ids": ["x"]}]}
    check_eq("F9: pending_rows keeps only a pending row that names an instance", [r["case"] for r in AC.pending_rows(manifest)], ["TC-1"])
    check("F9: tests_by_alias is first-wins", AC.tests_by_alias(manifest)["test_a"] is first)
    check_eq("F9: the word has one home", AC.PENDING_OUTCOME, C.PENDING_IMPLEMENTATION)


def c6() -> None:
    project = temp_project("qa-sides-c6-")
    use_project(project)
    try:
        real = sides_of(ui="real", backend="real")

        def settle(status, evidence, blocks, now=MARKED, **over):
            (project / HOME_FILE).parent.mkdir(exist_ok=True)
            (project / HOME_FILE).write_text(MARKED, encoding="utf-8")       # the line as it was when the row was written
            over.setdefault("home_hash", C.marked_line_hash(project, HOME_FILE, "P-1")[0])
            manifest = {"tests": [row(sides={"backend": "substituted"})],
                        "provisional": [prov(status=status, evidence=evidence, **over)]}
            return story(project, manifest, {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "real"}}}, blocks,
                         home=now)

        task = settle("open", {}, [])
        check_eq("C6 a negative: an open row whose side is now real - finding by its tag",
                 with_tag(found(task, real), P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
        check_eq("C6 a positive: the same row still open while its side is not real - nothing",
                 found(task, sides_of(ui="real", backend="substituted")), [])
        task = settle("kept_by_decision", {"why": "the person's word"}, [])
        check_eq("C6 a positive: a row kept by decision is not open", found(task, real), [])
        good = {"run": "r1"}
        task = settle("settled_matched", good, [block(sides_met={"ui": "real", "backend": "real"})])
        check_eq("C6 b positive: matched hash, a run block that is a run, stamped real", found(task, real), [])
        task = settle("settled_matched", good, [block(sides_met={"ui": "real", "backend": "substituted"})])
        check_eq("C6 b negative: the stamp says the side was substituted", with_tag(found(task, real), "provisional-stamp-"),
                 ["provisional-stamp-P-1"])
        task = settle("settled_matched", {"run": "nope"}, [block()])
        check_eq("C6 b negative: the cited run block does not exist", with_tag(found(task, real), "provisional-evidence-"),
                 ["provisional-evidence-P-1"])
        task = settle("settled_matched", {"run": "c1"}, [block("c1", kind="collect")])
        check_in("C6 b negative: a cited collect is no run", "collect", found(task, real)[0]["message"])
        moved = 'LOGIN = "#new"  # qa-provisional: P-1\n'
        task = settle("settled_matched", good, [block(sides_met={"ui": "real", "backend": "real"})], now=moved)
        check_eq("C6 b negative: settled_matched while the marked line changed", with_tag(found(task, real), "provisional-hash-"),
                 ["provisional-hash-P-1"])
        (project / HOME_FILE).write_text(moved, encoding="utf-8")
        after = C.marked_line_hash(project, HOME_FILE, "P-1")[0]
        task = settle("settled_edited", {"run": "r1", "home_hash_after": after}, [block(sides_met={"ui": "real", "backend": "real"})],
                      now=moved)
        check_eq("C6 b positive: settled_edited with the hash of the line now", found(task, real), [])
        # F7: the comparison reads the TOOL-stamped value; a line edited after the stamp is refused, and the door does not ask the
        # role for the hash
        (project / HOME_FILE).write_text('LOGIN = "#newer"  # qa-provisional: P-1\n', encoding="utf-8")
        got = [f for f in found(task, real) if P._finding_tag(f) == "provisional-hash-P-1"]
        check_eq("F7: settled_edited whose line changed AFTER the tool's stamp is `provisional-hash-P-1`", len(got), 1)
        said = " ".join(f["fix"] for f in got)
        check("F7: its door asks for `status` and `evidence.run`, never `evidence.home_hash_after` from the role",
              "evidence.run" in said and "send `evidence.home_hash_after`" not in said and "home_hash_after}" not in said, said)
        (project / HOME_FILE).write_text(moved, encoding="utf-8")
        # an absent stamp reads as real only when every side is real and nothing is unknown
        task = settle("settled_matched", good, [block()])
        check_eq("C6 b: no stamp, every side real: read as real", found(task, real), [])
        check_eq("C6 b: no stamp, a side not real now: NOT read as real",
                 with_tag(found(task, sides_of(ui="real", backend="substituted")), "provisional-stamp-"), ["provisional-stamp-P-1"])
        (task / "pipeline.json").write_text(json.dumps({"sides_unknown": "registry unreadable"}), encoding="utf-8")
        check_eq("C6 b: no stamp while `sides_unknown` stands: NOT read as real",
                 with_tag(found(task, real), "provisional-stamp-"), ["provisional-stamp-P-1"])
    finally:
        cleanup(project)


def one_finding_per_pending_row_after_arrival() -> None:
    """F10: after arrival an instance whose latest run is terminal is not told to run (C5); C6 (c) owns that state."""
    project = temp_project("qa-sides-f10-")
    use_project(project)
    try:
        real = sides_of(ui="real", backend="real")
        pipeline = {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "real"}}}
        manifest = {"tests": [row(sides={"ui": "real", "backend": "absent"})],
                    "unresolved": [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]}]}
        task = story(project, manifest, pipeline, [block(sides_met={"ui": "real", "backend": "real"})])
        check_eq("F10: one finding for the row after real runs - the leftover, not also `run it`", tags(found(task, real)),
                 ["pending-row-leftover-TC-1"])
        task = story(project, manifest, pipeline, [])
        check_eq("F10: with no run the instance still owes its run (C5)", tags(found(task, real)), ["pending-not-excused-test_a"])
    finally:
        cleanup(project)


def leftover_pending_row_after_real_runs_refused() -> None:
    """B5 / C6 (c): after the arrival every instance of a pending row ran stamped real, and the row still stands."""
    project = temp_project("qa-sides-b5-")
    use_project(project)
    try:
        real = sides_of(ui="real", backend="real")
        pipeline = {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "real"}}}
        manifest = {"tests": [row(sides={"ui": "real", "backend": "absent"})],
                    "unresolved": [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]}]}
        task = story(project, manifest, pipeline, [block(sides_met={"ui": "real", "backend": "real"})])
        got = found(task, real)
        check_eq("B5: a pending row left standing after real runs is refused (repair: retracted_unresolved)",
                 with_tag(got, "pending-row-leftover-"), ["pending-row-leftover-TC-1"])
        check_in("B5: and the finding names the door", "retracted_unresolved", got[-1]["fix"])
        task = story(project, manifest, pipeline, [block(sides_met={"ui": "real", "backend": "substituted"})])
        check_eq("B5 negative: the run was stamped substituted - the row is not a leftover",
                 with_tag(found(task, real), "pending-row-leftover-"), [])
        task = story(project, manifest, pipeline, [])
        check_eq("B5 negative: nothing ran - the row is not a leftover", with_tag(found(task, real), "pending-row-leftover-"), [])
        check_eq("B5: a retracted row (no row) is clean", found(story(project, {"tests": manifest["tests"]}, pipeline,
                                                                       [block(sides_met={"ui": "real", "backend": "real"})]), real), [])
    finally:
        cleanup(project)


REAL = C.story_sides({})                 # the default side `product`, real: no `pipeline.sides` record
REAL_SIDE = next(iter(REAL))
FL_ROW = {"req": "R-1", "status": "missing", "blocked_by": "product", "why": "the stand shows no Pay button"}


def first_look_record(task: Path, rows="ok") -> None:
    """The first-look record of the story as the reader (`first_look.read`) wants it: a register, and `work/first-look.yaml` holding
    `rows` ("ok" = the one row of R-1 missing by the product; "absent" = no file; "garbage" = a file that is no record; "stale" = the
    register changed after the walk)."""
    work = task / "work"
    work.mkdir(parents=True, exist_ok=True)

    def register(text="The stand shows R-1."):
        (work / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n"
            f"| R-1 | {text} | task |\n| R-2 | The stand shows R-2. | task |\n", encoding="utf-8")

    register()
    if rows == "absent":
        return
    if rows == "garbage":
        (work / "first-look.yaml").write_text("rows: [unclosed\n  - : :\n", encoding="utf-8")
        return
    record = {"rows": [FL_ROW] if rows in ("ok", "stale") else rows, "gaps": [], "source_head": {},
              "register_hash": FL.current_keys(task)[1], "walk": "S3-first-look", "stand": "dev", "walked_at": "2026-11-11T10:00:00+00:00"}
    (work / "first-look.yaml").write_text(GT.dump_yaml(record), encoding="utf-8")
    if rows == "stale":
        register("The stand shows R-1 differently.")


def fl_case(project: Path, record="ok", declared=True, blocks="failed", extra=None, test_over=None, **prov_over) -> Path:
    """A real-side story with ONE accounting row P-1 (`placeholder_locator`, `first_look:R-1`) bound to Then 1 of TC-1 and its test."""
    entry = dict(row())
    if declared:
        entry["provisional"] = ["P-1"]
    entry.update(test_over or {})
    over = {"side": REAL_SIDE, "kind": "placeholder_locator", "assumed_from": "first_look:R-1", **prov_over}
    manifest = {"tests": [entry], "provisional": [prov(**over)], **(extra or {})}
    if isinstance(blocks, str):
        blocks = {"none": [], "failed": [block(results=(("test_a", "failed"),))],
                  "passed": [block(results=(("test_a", "passed"),))]}.get(blocks) or [block(results=(("test_a", blocks),))]
    task = story(project, manifest, blocks=blocks)
    first_look_record(task, record)
    return task


def with_project(body) -> None:
    project = temp_project("qa-sides-fl7-")
    use_project(project)
    try:
        body(project)
    finally:
        cleanup(project)


def real_side_placeholder_with_first_look_basis_accepted() -> None:
    def body(project):
        check_eq("J-C5: missing + product, fresh record, declared and run: accounted, nothing", found(fl_case(project), REAL), [])
        rows = [dict(FL_ROW, status="unreachable")]
        check_eq("J-C5: `unreachable` + product is as good as `missing`", found(fl_case(project, record=rows), REAL), [])
    with_project(body)


def real_side_placeholder_without_basis_refused() -> None:
    def body(project):
        got = found(fl_case(project, assumed_from="requirement:R-1"), REAL)
        check_eq("J-C5: the same row assumed from a requirement is an open row on a real side",
                 with_tag(got, P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
        check_eq("J-C5: a first-look reference of no R-n is not the basis either",
                 with_tag(found(fl_case(project, assumed_from="first_look:"), REAL), P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
    with_project(body)


def _other_kind_on_real(kind: str) -> None:
    def body(project):
        for assumed in ("first_look:R-1", "requirement:R-1"):
            got = found(fl_case(project, kind=kind, assumed_from=assumed), REAL)
            check_eq(f"J-C5: `{kind}` ({assumed}) on a real side is refused",
                     with_tag(got, P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
    with_project(body)


def real_side_side_substitute_refused() -> None:
    _other_kind_on_real("side_substitute")


def real_side_assumed_contract_refused() -> None:
    _other_kind_on_real("assumed_contract")


def real_side_reference_value_refused() -> None:
    _other_kind_on_real("reference_value")


def kind_without_on_real_refused_on_real() -> None:
    def body(project):
        kinds = project / "kinds.json"
        kinds.write_text(json.dumps({"kinds": {"placeholder_locator": {"what": "a locator"}}}), encoding="utf-8")
        shipped = C.PROVISIONAL_KINDS_PATH
        C.PROVISIONAL_KINDS_PATH = kinds
        try:
            got = found(fl_case(project), REAL)
        finally:
            C.PROVISIONAL_KINDS_PATH = shipped
        check_eq("J-C5: a kind with no `on_real` reads `never`: the first-look row of it is open on a real side",
                 with_tag(got, P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
        check_eq("control: the shipped file says `first_look_only` for the placeholder locator, `never` for the other three",
                 [C.provisional_kind_on_real(k) for k in ("placeholder_locator", "assumed_contract", "side_substitute", "reference_value", "made_up")],
                 ["first_look_only", "never", "never", "never", "never"])
    with_project(body)


def on_real_read_only_through_contract_reader() -> None:
    """F1 (AR-13): s5_precheck holds no reader of the kinds file; it asks `contract.provisional_kind_on_real`."""
    def body(project):
        check_eq("AR-13: no second reader of the kinds file in s5_precheck", hasattr(P, "_kind_on_real"), False)
        shipped = C.provisional_kind_on_real
        C.provisional_kind_on_real = lambda kind: "never"
        try:
            got = found(fl_case(project), REAL)
        finally:
            C.provisional_kind_on_real = shipped
        check_eq("AR-13: the contract reader's `never` is what the check follows (open on a real side)",
                 with_tag(got, P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
        check_eq("control: with the real reader the same story is accounted", with_tag(found(fl_case(project), REAL), P.PROVISIONAL_OPEN_ON_REAL), [])
    with_project(body)


def _basis_refused(label: str, **kw) -> None:
    def body(project):
        got = found(fl_case(project, **kw), REAL)
        check_eq(f"J-C5 {label}: refused by the tag", with_tag(got, "placeholder-basis-"), ["placeholder-basis-P-1"])
        check_eq(f"J-C5 {label}: and only that", len(got), 1)
    with_project(body)


def basis_row_confirms_refused() -> None:
    _basis_refused("`confirms`", record=[dict(FL_ROW, status="confirms", blocked_by=None)])
    _basis_refused("`contradicts`", record=[dict(FL_ROW, status="contradicts", blocked_by=None)])


def basis_missing_access_refused() -> None:
    _basis_refused("`missing` + access", record=[dict(FL_ROW, blocked_by="access")])


def basis_unreachable_access_refused() -> None:
    _basis_refused("`unreachable` + access", record=[dict(FL_ROW, status="unreachable", blocked_by="access")])


def basis_nature_refused() -> None:
    _basis_refused("`unreachable` + nature", record=[dict(FL_ROW, status="unreachable", blocked_by="nature")])
    _basis_refused("`missing` + nature", record=[dict(FL_ROW, blocked_by="nature")])


def basis_row_absent_refused() -> None:
    _basis_refused("R-9 not in the record", assumed_from="first_look:R-9")
    _basis_refused("a null record (no rows)", record=[])


def basis_record_unreadable_refused() -> None:
    _basis_refused("no record file", record="absent")
    _basis_refused("a file that is no record", record="garbage")


def basis_record_stale_refused() -> None:
    _basis_refused("a record about another register", record="stale")


def c6a_skips_open_first_look_row() -> None:
    def body(project):
        check_eq("C6 (a): an open accounting row on a real side is not `provisional-open-on-real`",
                 with_tag(found(fl_case(project), REAL), P.PROVISIONAL_OPEN_ON_REAL), [])
        check_eq("C6 (a): a first-look row whose status is `kept_by_decision` is not an open-on-real finding either, its basis is read",
                 with_tag(found(fl_case(project, status="kept_by_decision"), REAL), P.PROVISIONAL_OPEN_ON_REAL), [])
    with_project(body)


def c6b_absent_stamp_real_only_when_reader_all_real() -> None:
    def body(project):
        two = sides_of(ui="real", backend="absent")
        task = fl_case(project, status="settled_matched", side="ui", evidence={"run": "r1"},
                       home_hash=C.marked_line_hash(project, HOME_FILE, "P-1")[0], blocks=[block(), block()])
        (task / "work" / "run-blocks" / "20261100T000000Z-b0.json").write_text(json.dumps(block()), encoding="utf-8")
        got = found(task, two)
        check_eq("C6 (b): a story with a non-real side reads an absent stamp as NOT real",
                 with_tag(got, "provisional-stamp-"), ["provisional-stamp-P-1"])
        check_eq("control: with every side real the same absent stamp is real",
                 with_tag(found(task, REAL), "provisional-stamp-"), [])
    with_project(body)


def undeclared_test_on_dependent_then_refused() -> None:
    def body(project):
        got = found(fl_case(project, declared=False), REAL)
        check_eq("J-C9 (a): a test bound to a Then of the open row's `dependents` and not declaring it",
                 with_tag(got, "placeholder-undeclared-"), ["placeholder-undeclared-test_a-P-1"])
        check_in("... the finding says the declaration is accounting, not a claim", "accounting, not a claim", got[0]["fix"])
        two = {"tests": [dict(row(), provisional=["P-1"]), dict(row(iid="test_b"))], "then_bindings": [
            {"case": "TC-1", "then": 1, "instance_id": "test_a"}, {"case": "TC-1", "then": 1, "instance_id": "test_b"}]}
        task = fl_case(project, extra=two, blocks=[block(results=(("test_a", "failed"), ("test_b", "passed")))])
        check_eq("J-C9 (a): the second test bound to the same Then is refused, the declaring one is not",
                 with_tag(found(task, REAL), "placeholder-undeclared-"), ["placeholder-undeclared-test_b-P-1"])
        check_eq("ERROR DIRECTION: a test that does not touch the placeholder is owed the declaration too (a needless one is no finding)",
                 with_tag(found(fl_case(project), REAL), "placeholder-"), [])
    with_project(body)


def tests_provisional_unknown_p_refused() -> None:
    def body(project):
        got = found(fl_case(project, test_over={"provisional": ["P-1", "P-9"]}), REAL)
        check_eq("J-C9 (a): a P-n of `tests[].provisional` that is no row of `provisional[]`",
                 with_tag(got, "provisional-unknown-"), ["provisional-unknown-test_a-P-9"])
        task = story(project, {"tests": [dict(row(), provisional=["P-3"])]})
        check_eq("... also when the story has no row at all and every side is real (the early return does not hide it)",
                 with_tag(found(task, REAL), "provisional-unknown-"), ["provisional-unknown-test_a-P-3"])
        check_eq("control: a story with no `provisional` anywhere reads exactly as before",
                 found(story(project, {"tests": [row()]}), REAL), [])
    with_project(body)


def placeholder_test_not_excused_by_blocked_by_env() -> None:
    def body(project):
        for label, unresolved in (("naming the instance", {"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_a"]}),
                                  ("naming none (its case)", {"case": "TC-1", "reason": "blocked_by_env"})):
            got = found(fl_case(project, extra={"unresolved": [unresolved]}), REAL)
            check_eq(f"J-C9 (b): an instance of the test in a `blocked_by_env` row {label}",
                     with_tag(got, "placeholder-test-blocked-"), ["placeholder-test-blocked-test_a-P-1"])
        other = {"case": "TC-7", "reason": "blocked_by_env", "instance_ids": ["test_z"]}
        check_eq("control: a `blocked_by_env` row of another test is not this test's",
                 with_tag(found(fl_case(project, extra={"unresolved": [other]}), REAL), "placeholder-test-blocked-"), [])
    with_project(body)


def placeholder_test_not_excused_by_handing() -> None:
    def body(project):
        handed = {"case": "TC-1", "reason": "handed_to_person", "detail": "ui: the person checks the Pay button"}
        got = found(fl_case(project, extra={"unresolved": [handed]}), REAL)
        check_eq("J-C9 (c): the test's case is handed to the person", with_tag(got, "placeholder-test-handed-"),
                 ["placeholder-test-handed-test_a-P-1"])
    with_project(body)


def placeholder_test_skipped_refused() -> None:
    def body(project):
        for status in ("skipped", "xfail", "deselected"):
            got = found(fl_case(project, blocks=status), REAL)
            check_eq(f"J-C9 (d): the only run row of the test is `{status}`", with_tag(got, "placeholder-test-norun-"),
                     ["placeholder-test-norun-test_a-P-1"])
    with_project(body)


def placeholder_test_without_run_refused() -> None:
    def body(project):
        check_eq("J-C9 (d): no run block at all", with_tag(found(fl_case(project, blocks="none"), REAL), "placeholder-test-norun-"),
                 ["placeholder-test-norun-test_a-P-1"])
        check_eq("J-C9 (d): a collect-only block is no run",
                 with_tag(found(fl_case(project, blocks=[block(kind="collect", results=(("test_a", "passed"),))]), REAL),
                          "placeholder-test-norun-"), ["placeholder-test-norun-test_a-P-1"])
        check_eq("control: a red row is a run (the red is the point)",
                 with_tag(found(fl_case(project, blocks="failed"), REAL), "placeholder-test-norun-"), [])
        check_eq("control: a green row is a run too (the ledger takes the proof away, not this check)",
                 with_tag(found(fl_case(project, blocks="passed"), REAL), "placeholder-test-norun-"), [])
    with_project(body)


def later_non_terminal_row_wins_in_both_readers() -> None:
    """F6: ONE rule (`_latest_runs`, over `contract.TERMINAL_RESULT_STATUSES`) for J-C9 (d) and C5: a `skipped` row after a `failed` one
    leaves the instance with no terminal run, in both callers."""
    def body(project):
        red_then_skip = [block(results=(("test_a", "failed"),)), block(bid="r2", results=(("test_a", "skipped"),))]
        check_eq("J-C9 (d): failed, then skipped -> no terminal run",
                 with_tag(found(fl_case(project, blocks=red_then_skip), REAL), "placeholder-test-norun-"), ["placeholder-test-norun-test_a-P-1"])
        check_eq("control (d): the red alone is a run",
                 with_tag(found(fl_case(project, blocks=[red_then_skip[0]]), REAL), "placeholder-test-norun-"), [])
        pipeline = {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "real"}}}
        manifest = {"tests": [row(sides={"ui": "real", "backend": "absent"})],
                    "unresolved": [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]}]}
        real = sides_of(ui="real", backend="real")
        met = {"ui": "real", "backend": "real"}
        task = story(project, manifest, pipeline, [block(sides_met=met, results=(("test_a", "failed"),)),
                                                   block(bid="r2", results=(("test_a", "skipped"),))])
        check_eq("C5: failed, then skipped -> the instance owes its run again", tags(found(task, real)), ["pending-not-excused-test_a"])
        task = story(project, manifest, pipeline, [block(sides_met=met, results=(("test_a", "failed"),))])
        check_eq("control (C5): the red alone is terminal, only the leftover row is reported", tags(found(task, real)),
                 ["pending-row-leftover-TC-1"])
        task = story(project, manifest, pipeline, [block(sides_met=met, results=(("test_a", "failed"),)),
                                                   block(bid="r2", kind="collect", results=(("test_a", "passed"),))])
        check_eq("C5: a collect-only block after the red erases nothing", tags(found(task, real)), ["pending-row-leftover-TC-1"])
    with_project(body)


def placeholder_never_excuses_run() -> None:
    def body(project):
        task = fl_case(project, blocks="none")
        entries = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"]
        out: list = []
        P.check_run_mapping("TC-1", entries, [], [], out)
        check("the run-mapping check still owes the row of a test with an open placeholder (nothing excuses its run)",
              bool(out) and "no run block carries a result row" in str(out), str(out))
    with_project(body)


CHARTER_KEYS = {
    "qa-automator": ("The first look before your own discovery", "the carried-over sample", "A missing element filed as a skip",
                     "`tests[].provisional`", "never a skip, `blocked_by_env` or a hand-off"),
    "qa-code-critic": ("A selector or route found again", "where the first look saw it", "A placeholder locator's test",
                       "`tests[].provisional`", "accounting, not a claim of reliance", "A requirement opposite to it is no finding"),
}


def _keys_missing(text: str, keys) -> list:
    return [k for k in keys if k not in text]


def automator_charter_first_look_before_discovery() -> None:
    text = (Path(P.__file__).resolve().parents[1] / "agents" / "qa-automator.md").read_text(encoding="utf-8")
    check_eq("charter keys of qa-automator present", _keys_missing(text, CHARTER_KEYS["qa-automator"]), [])
    check("negative control: a key removed from the text is reported",
          _keys_missing(text.replace("the carried-over sample", ""), CHARTER_KEYS["qa-automator"]) == ["the carried-over sample"])
    check("the first look is named before the live check in the order line",
          text.index("what the first look saw") < text.index("your live check"))


def code_critic_charter_rediscovered_selector_is_finding() -> None:
    text = (Path(P.__file__).resolve().parents[1] / "agents" / "qa-code-critic.md").read_text(encoding="utf-8")
    check_eq("charter keys of qa-code-critic present", _keys_missing(text, CHARTER_KEYS["qa-code-critic"]), [])
    check("negative control: a key removed from the text is reported",
          _keys_missing(text.replace("A selector or route found again", ""), CHARTER_KEYS["qa-code-critic"]) == ["A selector or route found again"])


def first_look_placeholder_on_real_side_is_accounted() -> None:
    """Joint plan §5 item 3 (J-C5): a placeholder locator with `assumed_from: first_look:<R-n>` on a REAL side is the accounting row
    of a red test: C3 holds, C6 (a) is not applied to it while it is open, C6 (b) reads an absent stamp as real only when every
    side is real and `sides_unknown` is not set."""
    project = temp_project("qa-sides-fl-")
    use_project(project)
    try:
        real = C.story_sides({})        # the default side `product`, real: no `pipeline.sides` record
        side = next(iter(real))

        def one(status="open", assumed="first_look:R-1", kind="placeholder_locator", **over):
            task = story(project, {"tests": [dict(row(), provisional=["P-1"])],
                                   "provisional": [prov(side=side, kind=kind, assumed_from=assumed, status=status, **over)]},
                         blocks=[block(results=(("test_a", "failed"),))])
            first_look_record(task)         # J-C5: the basis the accounting row stands on, and J-C9: the declared, run test
            return task

        check_eq("J-C5: an open first-look placeholder on a real side is accounted - no finding", found(one(), real), [])
        check_eq("J-C5: the same row assumed from a requirement is an open row on a real side (C6 a)",
                 with_tag(found(one(assumed="requirement:R-1"), real), P.PROVISIONAL_OPEN_ON_REAL), ["provisional-open-on-real-P-1"])
        check_eq("J-C5: C3 still holds for it - a home with no marker is a finding",
                 with_tag(found(one(home={"file": "tests/gone.py", "line_hint": 1}), real), "provisional-home-"),
                 ["provisional-home-P-1"])
        settled = one(status="settled_matched", evidence={"run": "r1"}, home_hash=C.marked_line_hash(project, HOME_FILE, "P-1")[0])
        (settled / "work" / "run-blocks" / "20261100T000000Z-b0.json").write_text(json.dumps(block()), encoding="utf-8")
        check_eq("C6 (b): every side real, no `sides_unknown`, no stamp: real", found(settled, real), [])
        (settled / "pipeline.json").write_text(json.dumps({"sides_unknown": "x"}), encoding="utf-8")
        check_eq("C6 (b): with `sides_unknown` the absent stamp is not real",
                 with_tag(found(settled, real), "provisional-stamp-"), ["provisional-stamp-P-1"])
    finally:
        cleanup(project)


def s10_words() -> None:
    """S10: the family `sides` is NOT passable; `sides-undeclared` and `provisional-open-on-real` are, by tag; a C3 finding is not."""
    project = temp_project("qa-sides-s10-")
    use_project(project)
    try:
        two = sides_of(ui="real", backend="absent")
        task = story(project, {"tests": [row(), row(iid="test_b")], "provisional": [prov(kind="nope")]},
                     {"sides": {"ui": {"reality": "real"}, "backend": {"reality": "absent"}}})
        findings = found(task, two)
        word = {"stage": "S5", "match": "sides-undeclared-test_a", "decision": "the person says it is not needed", "by": "human"}
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [word, {**word, "match": "*"}]
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        left = P.passed_by_word(task, findings, [])
        kept = [P._finding_tag(f) for f in left]
        check("S10: a word for `sides-undeclared-test_a` passes that finding", "sides-undeclared-test_a" not in kept, str(kept))
        check("S10: and `*` passes the other undeclared one by its tag", "sides-undeclared-test_b" not in kept, str(kept))
        check_eq("S10: a C3 finding (kind) is not passed by any word, `*` included", [t for t in kept if t.startswith("provisional-kind-")],
                 ["provisional-kind-P-1"])
        check("S10: the family is not passable, only the tags are", "sides" not in P.PASSABLE
              and P.SIDES_UNDECLARED in P.WORD_PASSABLE_TAGS and P.PROVISIONAL_OPEN_ON_REAL in P.WORD_PASSABLE_TAGS)
    finally:
        cleanup(project)


def main() -> None:
    c1_c2()
    c3_c4()
    c5_and_pending()
    scope_of_a_window()
    home_hash_root_is_the_writers()
    one_pending_reader()
    c6()
    one_finding_per_pending_row_after_arrival()
    leftover_pending_row_after_real_runs_refused()
    first_look_placeholder_on_real_side_is_accounted()
    for fn in (real_side_placeholder_with_first_look_basis_accepted, real_side_placeholder_without_basis_refused,
               real_side_side_substitute_refused, real_side_assumed_contract_refused, real_side_reference_value_refused,
               kind_without_on_real_refused_on_real, basis_row_confirms_refused, basis_missing_access_refused,
               basis_unreachable_access_refused, basis_nature_refused, basis_row_absent_refused, basis_record_unreadable_refused,
               basis_record_stale_refused, c6a_skips_open_first_look_row, c6b_absent_stamp_real_only_when_reader_all_real,
               undeclared_test_on_dependent_then_refused, tests_provisional_unknown_p_refused,
               placeholder_test_not_excused_by_blocked_by_env, placeholder_test_not_excused_by_handing,
               placeholder_test_skipped_refused, placeholder_test_without_run_refused, later_non_terminal_row_wins_in_both_readers,
               placeholder_never_excuses_run, on_real_read_only_through_contract_reader,
               automator_charter_first_look_before_discovery, code_critic_charter_rediscovered_selector_is_finding):
        fn()
    s10_words()
    finish("s5 precheck sides")


if __name__ == "__main__":
    main()
